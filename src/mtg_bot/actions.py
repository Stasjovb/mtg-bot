"""Action types, mana payment, and action application."""

from __future__ import annotations

from dataclasses import dataclass

from mtg_bot.cards import ManaCost
from mtg_bot.game import (
    GameObject, GameState, StackItem, Zone, effective_land_produces,
)


def _format_log_targets(state: GameState, targets: tuple) -> str:
    """Return a ``" targeting Goblin Runner, Player 1"`` suffix for a
    log line announcing a spell or triggered ability going on the
    stack. Returns an empty string when there are no targets so the
    caller can unconditionally append it.

    Permanent ids resolve via the battlefield; spell/ability ids fall
    back to the stack (rare but possible for triggers that target
    in-flight spells). Unknown ids stringify as ``"?{kind}#{id}"`` —
    visible enough that a missing target shows up as a UI bug rather
    than a silent gap."""
    if not targets:
        return ""
    parts: list[str] = []
    for kind, tid in targets:
        if kind == "player":
            parts.append(f"Player {tid}")
            continue
        if kind == "stack":
            # Counter-spell-style targets: ``tid`` is a stack INDEX,
            # not an object id. Resolve via state.stack[index].
            if 0 <= tid < len(state.stack):
                parts.append(state.stack[tid].source.printing.name)
                continue
        obj = next((o for o in state.battlefield if o.id == tid), None)
        if obj is not None:
            parts.append(obj.printing.name)
            continue
        on_stack = next((s for s in state.stack if s.source.id == tid), None)
        if on_stack is not None:
            parts.append(on_stack.source.printing.name)
            continue
        if kind == "exile_card":
            in_exile = next(
                (c for p in state.players for c in p.exile if c.id == tid),
                None,
            )
            if in_exile is not None:
                parts.append(f"{in_exile.printing.name} (exiled)")
                continue
        parts.append(f"?{kind}#{tid}")
    return " targeting " + ", ".join(parts)


@dataclass(frozen=True)
class Action:
    pass


@dataclass(frozen=True)
class PassPriority(Action):
    pass


@dataclass(frozen=True)
class PlayLand(Action):
    card_id: int


@dataclass(frozen=True)
class CastSpell(Action):
    card_id: int
    # If True, cast from hand for the card's warp alt-cost (and trigger an
    # end-of-turn exile). If False (default), cast at the normal cost — from
    # hand OR from the "warped" exile zone if the card is sitting there.
    use_warp: bool = False
    # If True, pay the card's kicker cost on top of its base cost.
    # Only legal when the card has a kicker_cost.
    kicked: bool = False
    # If True, cast without paying any mana cost (Weftwalking's "first
    # spell each player casts during each of their turns may be cast
    # without paying its mana cost"). Mutually exclusive with use_warp
    # and kicked. Targets/additional costs are still paid; only the
    # mana cost is skipped.
    cast_for_free: bool = False
    # If True, cast from hand for the card's Impending alt-cost (the
    # Duskmourn Overlord cycle's deferred-cast mechanic). The card
    # enters the battlefield with ``printing.impending_count`` time
    # counters and ``impending_active=True`` — its printed creature
    # type is suppressed via ``is_creature_now`` until the last time
    # counter is removed at the controller's end step. Sorcery-speed
    # only (gated in ``legal_actions``); mutually exclusive with
    # ``use_warp``, ``kicked``, and ``cast_for_free``. The Overlord's
    # printed cost remains castable for the normal "enters as a
    # creature" line — flipping ``use_impending`` selects which arm
    # runs.
    use_impending: bool = False


@dataclass(frozen=True)
class ActivateAbility(Action):
    """Activate the N-th activated ability on a permanent the player
    controls. Pays the cost and puts the ability on the stack. Ineligibility
    (can't pay, creature summoning-sick for tap-cost abilities, etc.) is
    filtered in ``legal_actions`` and silently no-ops here as defense.
    """

    source_id: int
    ability_index: int


@dataclass(frozen=True)
class ActivateStation(Action):
    """Activate the Station ability of a Spacecraft.

    Cost: tap ``crew_id`` (another untapped creature the player controls).
    Effect: add charge counters to ``spacecraft_id`` equal to the crew's
    power. Sorcery-speed only (enforced by ``legal_actions``).
    """

    spacecraft_id: int
    crew_id: int


@dataclass(frozen=True)
class TurnFaceUp(Action):
    """Turn a face-down permanent face up by paying its underlying
    card's mana cost. CR 701.34 / 707.4: the controller may turn it
    face up at any time as a special action by revealing what it is
    and paying its mana cost. Currently only relevant for Manifest
    Dread / Morph face-down permanents — we accept the action only
    when the underlying ``printing`` is a creature card (CR 701.34
    explicitly: the manifest-side rules require the face-down card to
    be a creature card to turn it face up for its mana cost).

    Special action — does not use the stack. Costs are paid
    immediately and the flip resolves at once.
    """

    card_id: int


@dataclass(frozen=True)
class DeclareAttackers(Action):
    """Declare a set of creatures as attackers during the declare-attackers step.

    Ineligible ids (summoning-sick creatures, tapped creatures, etc.) are
    silently filtered during application.
    """
    attacker_ids: frozenset[int] = frozenset()


@dataclass(frozen=True)
class DeclareBlockers(Action):
    """Declare block assignments during the declare-blockers step.

    ``assignments`` is a tuple of (blocker_id, attacker_id) pairs (tuples
    instead of a dict so the action itself is hashable). Illegal pairs are
    silently filtered during application.
    """
    assignments: tuple[tuple[int, int], ...] = ()


def _untapped_lands(state: GameState, player_id: int) -> list[GameObject]:
    return [
        o for o in state.battlefield
        if o.controller_id == player_id and o.printing.is_land and not o.tapped
    ]


def _coin_matches_color(coin: "ManaCoin", color: str) -> bool:
    """True if ``coin`` can pay for a ``{color}`` requirement."""
    if coin.color == "any":
        return True
    return coin.color == color


def _coin_satisfies_context(
    coin: "ManaCoin", spell_kind: "str | frozenset[str]",
) -> bool:
    """True if ``coin``'s spend restriction is compatible with a
    payment in the given context.

    ``spell_kind`` is either a single string (legacy callers) or a
    frozenset of context tags. A single string is treated as a
    one-element set. The coin satisfies the context if its restriction
    is None (unrestricted) or matches at least one of the tags below.

    Known context tags:
      - "spell" (default): only unrestricted coins satisfy.
      - "artifact_spell": adds coins tagged "artifact_spell".
        Set when casting a spell whose printed types include Artifact
        (Steelswarm Operator / Power Depot's first mana ability).
      - "artifact_activation": adds coins tagged "artifact_activation".
        Set when activating an ability on an artifact source
        (Steelswarm Operator's second mana ability: "Spend this mana
        only to activate abilities of artifact sources").
      - "colorless_eldrazi_spell" / "colorless_eldrazi_ability": adds
        coins tagged "colorless_eldrazi" (Eldrazi Temple's second mana
        ability). Set when casting a colorless Eldrazi or activating an
        ability on a colorless-Eldrazi permanent.
      - "legendary_spell": adds coins tagged "legendary_spell". Set
        when casting a legendary spell (Plaza of Heroes's second mana
        ability — "Spend this mana only to cast a legendary spell").
      - "legendary_permanent_ability": adds coins tagged
        "legendary_permanent_ability". Set when activating an ability
        on a legendary permanent (Plaza of Heroes's third mana ability
        — "Add one mana of any color among legendary permanents you
        control"; we read that as "spend only to activate abilities of
        legendary permanents you control", matching how Eldrazi
        Temple's parallel "among colorless Eldrazi" line is modeled).
      - "land_activation": adds coins tagged "land_activation". Set
        when activating an ability on a land source (Sunken Citadel's
        second mana ability — "Spend this mana only to activate
        abilities of land sources").
      - "cast_from_outside_hand": adds coins tagged
        "cast_from_outside_hand" (Mm'menon, the Right Hand's grant —
        "Spend this mana only to cast a spell from anywhere other than
        your hand"). Set in ``_cast_spell`` when the spell is being
        cast from a zone other than the caster's hand (graveyard,
        exile, or top of library).
      - "activated_ability": unrestricted only (a generic
        non-artifact ability activation).
    """
    if coin.spend_restriction is None:
        return True
    if isinstance(spell_kind, str):
        kinds: frozenset[str] = frozenset({spell_kind})
    else:
        kinds = spell_kind
    if (
        coin.spend_restriction == "artifact_spell"
        and "artifact_spell" in kinds
    ):
        return True
    if (
        coin.spend_restriction == "artifact_activation"
        and "artifact_activation" in kinds
    ):
        return True
    if (
        coin.spend_restriction == "colorless_eldrazi"
        and (
            "colorless_eldrazi_spell" in kinds
            or "colorless_eldrazi_ability" in kinds
        )
    ):
        return True
    if (
        coin.spend_restriction == "legendary_spell"
        and "legendary_spell" in kinds
    ):
        return True
    if (
        coin.spend_restriction == "legendary_permanent_ability"
        and "legendary_permanent_ability" in kinds
    ):
        return True
    if (
        coin.spend_restriction == "land_activation"
        and "land_activation" in kinds
    ):
        return True
    if (
        coin.spend_restriction == "cast_from_outside_hand"
        and "cast_from_outside_hand" in kinds
    ):
        return True
    return False


def can_pay_cost(
    state: GameState, player_id: int, cost: ManaCost,
    spell_kind: "str | frozenset[str]" = "spell",
    *, convoke: bool = False, sac_for_mana: bool = False,
) -> bool:
    """Check whether the player can pay ``cost`` by consuming floating
    mana in their pool (respecting spend restrictions for ``spell_kind``)
    then tapping untapped lands.

    ``spell_kind`` accepts a single string (legacy) or a frozenset of
    context tags — see ``_coin_satisfies_context`` for the supported
    tags.

    When ``convoke=True``, the controller's untapped creatures are
    pre-applied as convoke contributions before checking pool + lands.
    Convoke is optional and only ever makes a spell cheaper, so for
    legality we use the maximum convoke contribution.

    When ``sac_for_mana=True``, the controller's sac-for-mana mana
    abilities (Treasure-style "Sacrifice this: Add ...") are
    optimistically counted as available coverage. Like convoke, this
    is upper-bound: the cast pipeline activates only what's needed.
    """
    if convoke:
        cost = _convoke_max_contribution(state, player_id, cost)
    if sac_for_mana:
        cost = _sac_for_mana_max_contribution(state, player_id, cost)
    p = state.player_by_id(player_id)
    usable_pool = [
        c for c in p.mana_pool
        if _coin_satisfies_context(c, spell_kind)
    ]
    lands = _untapped_lands(state, player_id)
    used_coins: set[int] = set()
    used_lands: set[int] = set()
    # Pay colored requirements first — prefer pool coins, then lands.
    for color, count in cost.colored:
        need = count
        for idx, coin in enumerate(usable_pool):
            if idx in used_coins:
                continue
            if _coin_matches_color(coin, color):
                used_coins.add(idx)
                need -= 1
                if need == 0:
                    break
        if need == 0:
            continue
        matching = [
            l for l in lands
            if color in effective_land_produces(state, l)
            and l.id not in used_lands
        ]
        if len(matching) < need:
            return False
        for l in matching[:need]:
            used_lands.add(l.id)
    # Pay generic with remaining pool coins (any color) + remaining lands.
    remaining_pool = len(usable_pool) - len(used_coins)
    remaining_lands = sum(1 for l in lands if l.id not in used_lands)
    return remaining_pool + remaining_lands >= cost.generic


def apply_cost_reductions(
    printing: "CardPrinting",
    state: GameState,
    caster_id: int,
    base_cost: ManaCost,
    chosen_targets: "tuple[tuple[str, int], ...] | None" = None,
) -> ManaCost:
    """Walk ``printing.cost_reductions`` and return a ManaCost with
    generic mana reduced accordingly. Unknown conditions are treated as
    False (no reduction), which is safe and warns via a log entry.

    Spell-local conditions:
      - ``another_spell_cast_this_turn``: caster's spells_cast_this_turn
        is already ≥ 1 (this spell will be their 2nd or later).
      - ``attacked_with_spacecraft_this_turn``: caster attacked with any
        Spacecraft earlier this turn.
      - ``per_differently_named_land`` (with ``per_land_group=True``):
        amount is multiplied by the number of distinct basic-land names
        the caster controls.
      - ``target_is_blocking_creature``: the spell's chosen target is a
        creature whose ``blocking`` attribute is set (Dark Endurance).
        When ``chosen_targets`` is None — the legal_actions
        affordability probe before the cast actually starts — this is
        evaluated optimistically: the discount applies if any creature
        on the battlefield is currently blocking, since the caster
        could pick it as the target. ``_cast_spell`` passes the actual
        chosen targets, so the discount only sticks if the caster
        commits to a blocker at cast time.
      - ``during_your_turn``: the caster is the active player (Mental
        Modulation's ``"This spell costs {1} less to cast during your
        turn."`` rider).

    External reductions: also walks every permanent the caster controls
    on the battlefield and applies any ``external_cost_reductions``
    that match (Uthros Psionicist's "your second spell costs {2} less"
    lives here). Externals stack with the spell's own reductions —
    a 5-cost spell with a 3-less self-reduction and a 2-less external
    ends up at 0 generic.
    """
    cost = base_cost
    cost = _apply_external_cost_reductions(state, caster_id, cost)
    for rule in printing.cost_reductions:
        reduction = _evaluate_cost_reduction(
            rule, state, caster_id, chosen_targets=chosen_targets,
        )
        if reduction > 0:
            cost = cost.reduced(reduction)
            state.log.append(
                f"cost reduced by {reduction} ({rule.condition})"
            )
    return cost


def _evaluate_cost_reduction(
    rule, state: GameState, caster_id: int,
    chosen_targets: "tuple[tuple[str, int], ...] | None" = None,
) -> int:
    """Resolve a single ``CostReduction`` rule to a generic-mana amount
    against current game state. Shared by spell-cast cost reductions
    (``apply_cost_reductions``) and ability-cost reductions
    (``_effective_ability_mana_cost``).

    ``chosen_targets`` is the spell's chosen targets when this is invoked
    from the cast pipeline. ``None`` means the caller doesn't have target
    context (e.g., ``legal_actions``' affordability probe before targets
    are picked, or ability cost reductions that don't depend on targets).
    Conditions that depend on the chosen target evaluate optimistically
    against the battlefield when ``chosen_targets`` is None.
    """
    if rule.condition == "another_spell_cast_this_turn":
        if state.player_by_id(caster_id).spells_cast_this_turn >= 1:
            return rule.amount
    elif rule.condition == "attacked_with_spacecraft_this_turn":
        if state.player_by_id(
            caster_id
        ).attacked_with_spacecraft_this_turn:
            return rule.amount
    elif rule.condition == "void_active":
        from mtg_bot.game import is_void_active

        if is_void_active(state):
            return rule.amount
    elif rule.condition == "opponents_control_three_or_more_creatures":
        opp_creatures = sum(
            1 for o in state.battlefield
            if o.controller_id != caster_id and o.printing.is_creature
        )
        if opp_creatures >= 3:
            return rule.amount
    elif rule.condition == "control_creature_with_plus_one_counter":
        if any(
            o.controller_id == caster_id
            and o.printing.is_creature
            and o.plus_one_counters > 0
            for o in state.battlefield
        ):
            return rule.amount
    elif rule.condition == "per_differently_named_land":
        if rule.per_land_group:
            names: set[str] = set()
            for o in state.battlefield:
                if (
                    o.controller_id == caster_id
                    and o.printing.is_land
                ):
                    names.add(o.printing.name)
            return rule.amount * len(names)
    elif rule.condition == "affinity_for_slivers":
        # Thrumming Hivepool: "Affinity for Slivers (This spell costs
        # {1} less to cast for each Sliver you control.)" — count
        # Slivers the caster controls on the battlefield. The spell
        # itself is on the stack, not the battlefield, so it isn't
        # counted (matches MTG rules 702.41 for Affinity).
        from mtg_bot.game import effective_subtypes
        sliver_count = sum(
            1 for o in state.battlefield
            if o.controller_id == caster_id
            and "Sliver" in effective_subtypes(state, o)
        )
        return rule.amount * sliver_count
    elif rule.condition == "during_your_turn":
        # Mental Modulation: "This spell costs {1} less to cast during
        # your turn." — discount applies whenever the caster is the
        # active player. Read off ``state.active_player_idx`` rather
        # than spinning up a phase check; the discount is independent
        # of which step/phase the spell is being cast in.
        if state.active_player().id == caster_id:
            return rule.amount
    elif rule.condition == "target_is_blocking_creature":
        # Dark Endurance: "this spell costs {1} less to cast if it
        # targets a blocking creature." Cast-pipeline path passes the
        # actual chosen targets; we apply the discount only when the
        # picked creature is currently blocking. legal_actions'
        # affordability probe (chosen_targets=None) evaluates
        # optimistically — the discount applies if any blocker exists
        # on the battlefield, since the caster could pick it.
        if chosen_targets is None:
            if any(
                o.printing.is_creature and o.blocking is not None
                for o in state.battlefield
            ):
                return rule.amount
        else:
            for kind, tid in chosen_targets:
                if kind != "creature":
                    continue
                obj = next(
                    (o for o in state.battlefield if o.id == tid),
                    None,
                )
                if (
                    obj is not None
                    and obj.printing.is_creature
                    and obj.blocking is not None
                ):
                    return rule.amount
    else:
        state.log.append(
            f"unknown cost-reduction condition {rule.condition!r}; "
            f"treating as no reduction"
        )
    return 0


def _apply_external_cost_reductions(
    state: GameState, caster_id: int, cost: "ManaCost",
) -> "ManaCost":
    """Walk the caster's battlefield for permanents that grant external
    cost reductions to other spells. Each permanent's
    ``external_cost_reductions`` are evaluated against the same caster
    state used by spell-local reductions. Reductions stack (multiple
    permanents granting the same reduction sum together)."""
    caster = state.player_by_id(caster_id)
    for permanent in state.battlefield:
        if permanent.controller_id != caster_id:
            continue
        if permanent.phased_out:
            continue
        externals = getattr(
            permanent.printing, "external_cost_reductions", ()
        )
        for ext in externals:
            reduction = 0
            if ext.condition == "second_spell_this_turn":
                # The second spell is the one cast when
                # spells_cast_this_turn is currently 1 (the spell-cast
                # path increments AFTER cost is paid, so we check the
                # pre-increment value here).
                if caster.spells_cast_this_turn == 1:
                    reduction = ext.amount
            elif ext.condition == "affinity_for_artifacts":
                # Sami, Wildcat Captain: "Spells you cast have affinity
                # for artifacts. (They cost {1} less to cast for each
                # artifact you control.)" — count artifacts the caster
                # controls on the battlefield. The spell being cast is
                # on the stack, not the battlefield, so it isn't
                # counted (matches MTG rules 702.41).
                artifact_count = sum(
                    1 for o in state.battlefield
                    if o.controller_id == caster_id
                    and o.printing.is_artifact
                )
                reduction = ext.amount * artifact_count
            else:
                state.log.append(
                    f"unknown external cost-reduction condition "
                    f"{ext.condition!r}; treating as no reduction"
                )
            if reduction > 0:
                cost = cost.reduced(reduction)
                state.log.append(
                    f"cost reduced by {reduction} from "
                    f"{permanent.printing.name} ({ext.condition})"
                )
    return cost


def _x_upper_bound(
    state: GameState, player_id: int, base_cost: ManaCost
) -> int:
    """Max X the caster can afford for ``base_cost`` (which still has its
    ``x_pips`` set). Iterates upward from 0 until a payment with the next
    X would exceed available mana. Practical X values are small (0–6),
    so linear probing is fine.
    """
    x = 0
    while True:
        trial = ManaCost(
            generic=base_cost.generic + base_cost.x_pips * (x + 1),
            colored=base_cost.colored,
        )
        if not can_pay_cost(state, player_id, trial):
            return x
        x += 1


def _choose_and_apply_x(
    state: GameState, player_id: int, card: GameObject, cost: ManaCost
) -> int:
    """Ask the caster's agent for an X value, bounded by what they can
    actually pay. Returns the chosen X (clamped into ``[0, upper_bound]``)
    and logs the choice.
    """
    p = state.player_by_id(player_id)
    upper_bound = _x_upper_bound(state, player_id, cost)
    if p.agent is None:  # pragma: no cover - games run with agents set
        chosen = 0
    else:
        chosen = p.agent.choose_x(
            state, player_id, card.printing.name, upper_bound
        )
    if chosen < 0:
        chosen = 0
    if chosen > upper_bound:
        chosen = upper_bound
    state.log.append(f"P{player_id} chooses X={chosen} for {card.printing.name}")
    return chosen


def _convoke_candidates(
    state: GameState, player_id: int
) -> list[GameObject]:
    """Untapped creatures ``player_id`` controls. CR 702.51 doesn't
    care about summoning sickness because tapping a creature for
    convoke isn't an activated ability."""
    from mtg_bot.game import is_creature_now
    return [
        o for o in state.battlefield
        if o.controller_id == player_id
        and is_creature_now(o)
        and not o.tapped
    ]


def _cost_is_zero(cost: ManaCost) -> bool:
    """True when a ManaCost has no remaining generic or colored requirement."""
    return cost.generic == 0 and not any(n > 0 for _, n in cost.colored)


def _apply_convoke_pip(
    state: GameState, creature: GameObject,
    generic: int, colored: list[tuple[str, int]],
) -> tuple[int, list[tuple[str, int]], bool]:
    """Apply one creature's convoke contribution to ``(generic, colored)``.

    Per CR 702.51: each tapped creature pays {1} OR one mana of one of
    its colors. Greedy: prefer paying a still-owed colored pip the
    creature matches; otherwise drop {1} from generic. If the creature
    can't pay anything (cost already 0), returns the inputs unchanged
    with ``applied=False`` so the caller can skip the tap.
    """
    from mtg_bot.game import effective_colors
    cols = effective_colors(state, creature)
    for i, (color, n) in enumerate(colored):
        if n > 0 and color in cols:
            new_colored = list(colored)
            new_colored[i] = (color, n - 1)
            return generic, new_colored, True
    if generic > 0:
        return generic - 1, colored, True
    return generic, colored, False


def _convoke_max_contribution(
    state: GameState, player_id: int, cost: ManaCost
) -> ManaCost:
    """Lower ``cost`` by the maximum convoke contribution available.

    Used by the affordability check (``can_pay_cost(..., convoke=True)``)
    to compute "cheapest possible cost after convoke". Convoke is
    always optional and only ever makes a spell cheaper, so the
    legality check uses the upper-bound contribution. The actual cast
    pipeline taps whatever subset the agent chooses.
    """
    if _cost_is_zero(cost):
        return cost
    candidates = _convoke_candidates(state, player_id)
    generic = cost.generic
    colored = list(cost.colored)
    for o in candidates:
        if generic == 0 and all(n == 0 for _, n in colored):
            break
        generic, colored, _applied = _apply_convoke_pip(
            state, o, generic, colored,
        )
    return ManaCost(
        generic=generic,
        colored=tuple((c, n) for c, n in colored if n > 0),
        x_pips=cost.x_pips,
    )


def _apply_convoke(
    state: GameState, player_id: int, cost: ManaCost,
) -> ManaCost:
    """Run the convoke prompt during cost-payment (CR 601.2g/h with
    702.51). Asks the controller's agent which untapped creatures to
    tap, then taps each one and reduces the cost by one pip per
    creature. Returns the post-convoke cost for ``auto_tap_for_cost``
    to finish paying from pool + lands.

    A creature tapped for convoke can't separately activate its own
    sac-or-tap mana ability for the same cast (it's already tapped),
    matching the CR-required mutual exclusion that flagged Eldrazi
    Scion + convoke spells in the original design audit.
    """
    p = state.player_by_id(player_id)
    if p.agent is None:
        return cost
    if _cost_is_zero(cost):
        return cost
    candidates = _convoke_candidates(state, player_id)
    if not candidates:
        return cost
    candidate_ids = [o.id for o in candidates]
    chosen_ids = p.agent.choose_convoke_creatures(
        state, player_id, candidate_ids,
        cost.generic, list(cost.colored),
    )
    if not chosen_ids:
        return cost
    from mtg_bot.turn import tap_permanent
    by_id = {o.id: o for o in candidates}
    seen: set[int] = set()
    generic = cost.generic
    colored = list(cost.colored)
    for cid in chosen_ids:
        if cid in seen:
            continue
        seen.add(cid)
        creature = by_id.get(cid)
        if creature is None or creature.tapped:
            continue
        if generic == 0 and all(n == 0 for _, n in colored):
            break
        generic, colored, applied = _apply_convoke_pip(
            state, creature, generic, colored,
        )
        if not applied:
            continue
        tap_permanent(state, creature)
        state.log.append(
            f"P{player_id} taps {creature.printing.name} for convoke"
        )
    return ManaCost(
        generic=generic,
        colored=tuple((c, n) for c, n in colored if n > 0),
        x_pips=cost.x_pips,
    )


def _classify_sac_for_mana(
    state: GameState, source: GameObject,
) -> "list[tuple[int, tuple[tuple[str, int], ...]]]":
    """For ``source``, list its qualifying sac-for-mana mana abilities
    as ``(ability_idx, produces)`` pairs.

    A qualifying ability:
      - is a mana ability (``is_mana_ability=True``)
      - costs the source's sacrifice (``sacrifice_self=True``)
      - has no other resource costs (no mana cost, no extra sacs, no
        life payment) — Treasure-style "Sacrifice this: Add ..." or
        "{T}, Sacrifice this: Add ..." both qualify
      - resolves into ``AddManaToPool`` with concrete ``produces``
    """
    from mtg_bot.effects.generic import AddManaToPool
    from mtg_bot.game import effective_activated_abilities
    out: list[tuple[int, tuple[tuple[str, int], ...]]] = []
    for idx, ability in enumerate(effective_activated_abilities(state, source)):
        if not ability.is_mana_ability:
            continue
        c = ability.cost
        if not c.sacrifice_self:
            continue
        if c.mana is not None and c.mana.total > 0:
            continue
        if (
            c.sacrifice_another_creature_or_artifact
            or c.sacrifice_another_artifact_or_land
            or c.sacrifice_another_artifact
            or c.sacrifice_food
            or c.sacrifice_a_land
            or c.sacrifice_a_desert
            or c.remove_plus_one_counter_from_your_creature
            or c.exile_granting_equipment
            or c.pay_life
        ):
            continue
        if not isinstance(ability.effect, AddManaToPool):
            continue
        out.append((idx, ability.effect.produces))
    return out


def _sac_for_mana_sources(
    state: GameState, player_id: int,
) -> "list[tuple[GameObject, int, tuple[tuple[str, int], ...]]]":
    """Battlefield sources controlled by ``player_id`` whose
    sac-for-mana mana abilities can fire as part of the current cast.
    Already-tapped sources can still fire (a tap-then-sac ability needs
    {T} which a tapped source can't pay; ``_can_fire_now`` filters that).
    """
    sources: list[tuple[GameObject, int, tuple[tuple[str, int], ...]]] = []
    for o in state.battlefield:
        if o.controller_id != player_id:
            continue
        if o.phased_out:
            continue
        for idx, produces in _classify_sac_for_mana(state, o):
            sources.append((o, idx, produces))
    return sources


def _can_fire_sac_for_mana(state: GameState, source: GameObject, ability_idx: int) -> bool:
    """True if ``source``'s ``ability_idx`` ability can be activated
    right now to add mana. Gates the {T} cost on the source being
    untapped (sacrifice and any-cost-zero parts always work)."""
    from mtg_bot.game import effective_activated_abilities
    abilities = effective_activated_abilities(state, source)
    if ability_idx >= len(abilities):
        return False
    if abilities[ability_idx].cost.tap_self and source.tapped:
        return False
    return True


def _produces_satisfies(
    produces: "tuple[tuple[str, int], ...]", color: str,
) -> bool:
    """True if ``produces`` (one activation's mana output) covers a
    requirement for one pip of ``color``. ``"any"`` matches any color;
    a colored requirement is satisfied only by exact match or "any";
    a generic requirement (color="" / None) is satisfied by any output.
    """
    for c, n in produces:
        if n <= 0:
            continue
        if color == "" or color is None:
            return True
        if c == color or c == "any":
            return True
    return False


def _produces_total(produces: "tuple[tuple[str, int], ...]") -> int:
    return sum(n for _, n in produces)


def _sac_for_mana_max_contribution(
    state: GameState, player_id: int, cost: ManaCost,
) -> ManaCost:
    """Lower ``cost`` by the maximum coverage available from the
    caster's sac-for-mana mana abilities. Used by the affordability
    check (``can_pay_cost(..., sac_for_mana=True)``). Each source can
    fire at most once per cast; greedy color-first matching mirrors
    the runtime ``_activate_sac_for_mana_for_cost`` allocator.
    """
    if _cost_is_zero(cost):
        return cost
    sources = _sac_for_mana_sources(state, player_id)
    if not sources:
        return cost
    consumed: set[int] = set()
    generic = cost.generic
    colored = list(cost.colored)
    # Pay colored first.
    for i, (color, n) in enumerate(colored):
        need = n
        while need > 0:
            chosen_idx: "int | None" = None
            for sidx, (src, ai, produces) in enumerate(sources):
                if src.id in consumed:
                    continue
                if not _can_fire_sac_for_mana(state, src, ai):
                    continue
                if _produces_satisfies(produces, color):
                    chosen_idx = sidx
                    break
            if chosen_idx is None:
                break
            consumed.add(sources[chosen_idx][0].id)
            need -= 1
        colored[i] = (color, need)
    # Then generic.
    while generic > 0:
        chosen_idx = None
        for sidx, (src, ai, produces) in enumerate(sources):
            if src.id in consumed:
                continue
            if not _can_fire_sac_for_mana(state, src, ai):
                continue
            if _produces_total(produces) > 0:
                chosen_idx = sidx
                break
        if chosen_idx is None:
            break
        consumed.add(sources[chosen_idx][0].id)
        generic -= 1
    return ManaCost(
        generic=generic,
        colored=tuple((c, n) for c, n in colored if n > 0),
        x_pips=cost.x_pips,
    )


def _activate_sac_for_mana_for_cost(
    state: GameState, player_id: int, cost: ManaCost,
    spell_kind: "frozenset[str]",
) -> ManaCost:
    """During 601.2g cost payment, activate the caster's sac-for-mana
    mana abilities to cover any shortfall left after pool + lands.

    Returns the (still-unpaid) cost — typically equal to ``cost``
    unmodified, since auto_tap_for_cost runs after this and consumes
    the freshly-pooled mana. We don't pay the cost here; we just push
    coins into the pool.

    Greedy: for each unmet colored pip, find a sac source whose mana
    output covers that color and activate it. For generic shortfall,
    any sac source qualifies. Only fires when the cost can't already
    be paid from pool + lands — Treasures aren't blown up unless
    they're actually needed.
    """
    if _cost_is_zero(cost):
        return cost
    if can_pay_cost(state, player_id, cost, spell_kind=spell_kind):
        return cost
    sources = _sac_for_mana_sources(state, player_id)
    if not sources:
        return cost
    # Ask the agent which sources to activate. Default returns every
    # candidate in engine order, matching the prior auto-greedy
    # behavior. The agent's ordered list is iterated only while the
    # cost is still unpayable — once we can pay, remaining picks are
    # skipped (Treasures aren't blown up unnecessarily).
    p = state.player_by_id(player_id)
    candidates = [(src.id, produces) for src, _idx, produces in sources]
    if p.agent is None:
        ordered_ids = [oid for oid, _produces in candidates]
    else:
        ordered_ids = p.agent.choose_sac_for_mana(
            state, player_id, candidates,
            cost.generic, list(cost.colored),
        )
    by_id = {
        src.id: (src, idx, produces)
        for src, idx, produces in sources
    }
    seen: set[int] = set()
    for oid in ordered_ids:
        if oid in seen:
            continue
        seen.add(oid)
        entry = by_id.get(oid)
        if entry is None:
            continue
        src, idx, produces = entry
        if not _can_fire_sac_for_mana(state, src, idx):
            continue
        if can_pay_cost(state, player_id, cost, spell_kind=spell_kind):
            break
        # Skip sources whose mana output can't reduce the still-unmet
        # cost — a Treasure-{C} doesn't help against a colored-only
        # {R} cost. The agent's ordered list provides preference;
        # this gate keeps Treasures from being blown up uselessly
        # even if the agent listed them.
        helps_color = any(
            n > 0 and _produces_satisfies(produces, color)
            for color, n in cost.colored
        )
        helps_generic = (
            cost.generic > 0 and _produces_total(produces) > 0
        )
        if not (helps_color or helps_generic):
            continue
        state.log.append(
            f"P{player_id} activates {src.printing.name}'s "
            f"sac-for-mana ability to pay cost"
        )
        _activate_ability(state, player_id, src.id, idx)
    return cost


def auto_tap_for_cost(
    state: GameState, player_id: int, cost: ManaCost,
    spell_kind: "str | frozenset[str]" = "spell",
) -> list[GameObject]:
    """Pay ``cost`` by consuming floating mana first (respecting spend
    restrictions for ``spell_kind``), then tapping lands for the
    remainder. Returns the list of lands tapped. Mutates the pool
    and the tapped lands.

    ``spell_kind`` accepts a single string (legacy) or a frozenset of
    context tags — see ``_coin_satisfies_context`` for the supported
    tags.
    """
    p = state.player_by_id(player_id)
    lands = _untapped_lands(state, player_id)
    used_coin_ids: list[int] = []  # indices into p.mana_pool
    used_lands: set[int] = set()
    tapped: list[GameObject] = []
    # Consume pool coins by preference for colored requirements.
    for color, count in cost.colored:
        need = count
        for idx, coin in enumerate(p.mana_pool):
            if idx in used_coin_ids:
                continue
            if not _coin_satisfies_context(coin, spell_kind):
                continue
            if _coin_matches_color(coin, color):
                used_coin_ids.append(idx)
                need -= 1
                if need == 0:
                    break
        if need == 0:
            continue
        matching = [
            l for l in lands
            if color in effective_land_produces(state, l)
            and l.id not in used_lands
        ]
        for l in matching[:need]:
            used_lands.add(l.id)
            tapped.append(l)
    # Generic cost: pool first, then lands.
    generic_need = cost.generic
    for idx, coin in enumerate(p.mana_pool):
        if generic_need == 0:
            break
        if idx in used_coin_ids:
            continue
        if not _coin_satisfies_context(coin, spell_kind):
            continue
        used_coin_ids.append(idx)
        generic_need -= 1
    remaining_lands = [l for l in lands if l.id not in used_lands]
    for l in remaining_lands[:generic_need]:
        tapped.append(l)
    # Remove consumed coins from the pool (high index first to keep
    # lower indices stable).
    for idx in sorted(used_coin_ids, reverse=True):
        del p.mana_pool[idx]
    # Route through tap_permanent so becomes_tapped triggers fire
    # (Chrome Companion, Grove of the Burnwillows, etc.).
    from mtg_bot.turn import tap_permanent
    for l in tapped:
        tap_permanent(state, l)
    return tapped


def apply_action(state: GameState, player_id: int, action: Action) -> None:
    if isinstance(action, PassPriority):
        return
    if isinstance(action, PlayLand):
        _play_land(state, player_id, action.card_id)
        return
    if isinstance(action, CastSpell):
        _cast_spell(
            state, player_id, action.card_id,
            use_warp=action.use_warp, kicked=action.kicked,
            cast_for_free=action.cast_for_free,
            use_impending=action.use_impending,
        )
        return
    if isinstance(action, DeclareAttackers):
        _declare_attackers(state, player_id, action.attacker_ids)
        return
    if isinstance(action, DeclareBlockers):
        _declare_blockers(state, player_id, action.assignments)
        return
    if isinstance(action, ActivateStation):
        _activate_station(state, player_id, action.spacecraft_id, action.crew_id)
        return
    if isinstance(action, ActivateAbility):
        _activate_ability(
            state, player_id, action.source_id, action.ability_index
        )
        return
    if isinstance(action, TurnFaceUp):
        _turn_face_up(state, player_id, action.card_id)
        return
    raise ValueError(f"unknown action: {action!r}")


def _turn_face_up(state: GameState, player_id: int, card_id: int) -> None:
    """Turn a face-down permanent face up. Pays the mana cost from
    ``can_pay_cost`` and clears ``face_down``. CR 701.34: only legal
    when the underlying printing is a creature card; otherwise no-ops
    (legal_actions gates this — defensive here).
    """
    obj = next(
        (
            o for o in state.battlefield
            if o.id == card_id
            and o.controller_id == player_id
            and o.face_down
        ),
        None,
    )
    if obj is None:
        return
    if not obj.printing.is_creature:
        return
    cost_obj = obj.printing.mana_cost
    if not can_pay_cost(state, player_id, cost_obj):
        return
    auto_tap_for_cost(state, player_id, cost_obj, spell_kind="activated_ability")
    obj.face_down = False
    state.log.append(
        f"P{player_id} turns {obj.printing.name} face up"
    )


def _play_land(state: GameState, player_id: int, card_id: int) -> None:
    p = state.player_by_id(player_id)
    # Source may be hand (normal play), exile (impulse-cast lands), or
    # graveyard (Icetill Explorer's "you may play lands from your
    # graveyard" — gated in legal_actions on the controller having any
    # battlefield permanent with grants_play_lands_from_graveyard=True).
    card = next((c for c in p.hand if c.id == card_id), None)
    if card is not None:
        p.hand.remove(card)
    elif (card := next(
        (c for c in p.graveyard if c.id == card_id), None
    )) is not None:
        p.graveyard.remove(card)
    else:
        card = next(
            (c for c in p.exile if c.id == card_id), None
        )
        if card is None:  # pragma: no cover - defensive; legal_actions gates
            raise ValueError(
                f"land {card_id} not playable by P{player_id}"
            )
        p.exile.remove(card)
        card.playable_from_exile_this_turn = False
        card.play_from_exile_requires_kavu = False
    card.zone = Zone.BATTLEFIELD
    card.controller_id = player_id
    # "Enters tapped" covers Planets + most non-basic utility lands.
    card.tapped = bool(card.printing.enters_tapped)
    # Shock land: optional life payment on ETB. Agent decides; if they
    # can't/won't pay, the land enters tapped.
    life_cost = card.printing.shock_land_life_cost
    if life_cost > 0 and p.agent is not None:
        pay = p.agent.choose_pay_shock_life(state, player_id, life_cost)
        if pay:
            p.life -= life_cost
            state.log.append(
                f"P{player_id} pays {life_cost} life for "
                f"{card.printing.name} (life: {p.life})"
            )
        else:
            card.tapped = True
            state.log.append(
                f"P{player_id} declines shock life — "
                f"{card.printing.name} enters tapped"
            )
    # Echoing Deeps: "You may have this land enter tapped as a copy of
    # any land card in a graveyard, except it's a Cave in addition to
    # its other types." Agent target-selection over graveyard lands.
    if card.printing.optional_copy_land_from_graveyard and p.agent is not None:
        _offer_echoing_deeps_copy(state, player_id, card)
    state.battlefield.append(card)
    p.lands_played_this_turn += 1
    p.lands_entered_this_turn += 1
    state.log.append(f"P{player_id} plays {card.printing.name}")
    # ETB triggers on the land itself (Command Bridge's
    # sacrifice-unless-tap rider). Push them on the stack like any
    # other ETB. Mirrors put_into_battlefield's call site for
    # creatures/artifacts. Lands go through _play_land, not
    # put_into_battlefield, so we have to call this here.
    # ``_trigger_etb_abilities`` itself dispatches ``Event.ENTERS``,
    # which fires every predicate-style landfall trigger
    # (``IsLand() & Controlled(YOU)``); we no longer need to call
    # ``fire_landfall_triggers`` here as well — that was the
    # legacy-only landfall path and the dispatcher handles the
    # migrated abilities.
    _trigger_etb_abilities(state, card)
    # Phase-8 ``Event.PLAYS_LAND`` dispatch (via
    # ``fire_opponent_plays_land_triggers``, kept named for backward-
    # compatible direct test access). The function's internal legacy
    # walk over ``opponent_plays_land`` string-key abilities is now
    # dead — every land-play observer in the static pool migrated to
    # predicate shape (Burgeoning's ``Controlled(by=OPPONENT,
    # subject="controller")`` and The Endstone's land-half
    # ``Controlled(YOU, subject="controller")``). Both ride the same
    # PLAYS_LAND dispatch sweep.
    from mtg_bot.turn import fire_opponent_plays_land_triggers
    fire_opponent_plays_land_triggers(state, player_id, land=card)


def _offer_echoing_deeps_copy(
    state: GameState, player_id: int, card: "GameObject",
) -> None:
    """Ask the controller's agent whether to have ``card`` enter as a
    copy of any land card in any graveyard, with "Cave" injected.

    Agent hook: reuses ``choose_target`` with kind
    ``"graveyard_land_card"``. Returning None (or no legal targets)
    declines — ``card`` enters normally.

    On accept, ``card.printing`` is replaced with a fresh CardPrinting
    derived from the target's, with "Cave" added to its subtypes if
    absent. The card enters tapped.
    """
    import dataclasses as _dc

    candidates: list[tuple[str, int]] = [
        ("graveyard_land_card", c.id)
        for pp in state.players
        for c in pp.graveyard
        if c.printing.is_land
    ]
    if not candidates:
        return
    p = state.player_by_id(player_id)
    chosen = p.agent.choose_target(state, player_id, candidates)
    if chosen is None:
        return
    kind, target_id = chosen
    if kind != "graveyard_land_card":
        return
    target = None
    for pp in state.players:
        for c in pp.graveyard:
            if c.id == target_id:
                target = c
                break
        if target is not None:
            break
    if target is None:
        return
    subtypes = tuple(target.printing.subtypes)
    if "Cave" not in subtypes:
        subtypes = subtypes + ("Cave",)
    card.printing = _dc.replace(target.printing, subtypes=subtypes)
    card.tapped = True
    state.log.append(
        f"Echoing Deeps enters as a copy of {target.printing.name} "
        f"(Cave added), tapped"
    )


def _choose_modes_at_cast(
    state: GameState, player_id: int, card: GameObject,
) -> tuple[int, ...]:
    """CR 601.2e: pick mode(s) for a modal spell at cast time, before
    total cost is determined. Returns the chosen mode indices in
    resolution order, or ``()`` for non-modal spells.

    For "Choose one" returns a 1-tuple. For "Choose one or both"
    returns a 1- or 2-tuple. Resolution runs the chosen modes via
    ``state.resolving_modes`` instead of prompting the agent again
    at resolve time.
    """
    from mtg_bot.effects.combinators import ModalChooseOne
    spell_effect = card.printing.spell_effect
    if not isinstance(spell_effect, ModalChooseOne):
        return ()
    p = state.player_by_id(player_id)
    if p.agent is None:
        return (0,)
    if spell_effect.or_both:
        order = p.agent.choose_modes(
            state, player_id,
            [m.describe() for m in spell_effect.modes],
        )
        seen: set[int] = set()
        clean: list[int] = []
        for idx in order:
            if 0 <= idx < len(spell_effect.modes) and idx not in seen:
                clean.append(idx)
                seen.add(idx)
        if not clean:
            clean = [0]
        return tuple(clean)
    idx = p.agent.choose_mode(
        state, player_id,
        [m.describe() for m in spell_effect.modes],
    )
    idx = max(0, min(idx, len(spell_effect.modes) - 1))
    return (idx,)


def _effective_spell_effect_for_targets(
    spell_effect, mode_indices: tuple[int, ...],
):
    """Given a spell's printed effect and the cast-time mode picks,
    return the effect that drives target selection.

    For non-modal spells, passes through. For ``ModalChooseOne`` with
    one mode picked, returns that mode's effect. For ``or_both`` with
    multiple picks where at most one mode targets, returns a
    ``Sequence`` of the chosen modes (target selection on the single
    targeted sub-effect). When more than one chosen mode targets we
    fall back to the printed ``ModalChooseOne`` (its union-of-modes
    legal_targets / target_count_range), since ``Sequence`` doesn't
    support multi-targeted sub-effects today.
    """
    from mtg_bot.effects.combinators import ModalChooseOne, Sequence
    if not isinstance(spell_effect, ModalChooseOne):
        return spell_effect
    if not mode_indices:
        return spell_effect
    if len(mode_indices) == 1:
        return spell_effect.modes[mode_indices[0]]
    chosen = tuple(spell_effect.modes[i] for i in mode_indices)
    targeted_count = sum(1 for m in chosen if m.requires_target())
    if targeted_count <= 1:
        return Sequence(effects=chosen)
    return spell_effect


def _select_spell_targets(
    state: GameState, player_id: int, card: GameObject,
    mode_indices: tuple[int, ...] = (),
) -> tuple[tuple[str, int], ...]:
    """Pick target(s) for a spell about to be cast. Mirrors CR
    601.2c-d (mode/target choices happen BEFORE total cost is
    determined). Called from ``_cast_spell`` ahead of
    ``apply_cost_reductions`` so target-dependent cost riders (Dark
    Endurance) can see the choice.

    Handles both regular ``spell_effect`` targets (single- and
    multi-target via ``Effect.target_count_range``) and aura
    enchant-target picks. ``mode_indices`` carries the cast-time
    modal pick so target selection runs against the chosen mode's
    targets, not the union over all modes. Returns an empty tuple
    for non-targeting spells.
    """
    p = state.player_by_id(player_id)
    targets: tuple[tuple[str, int], ...] = ()
    spell_effect = card.printing.spell_effect
    if spell_effect is not None:
        spell_effect = _effective_spell_effect_for_targets(
            spell_effect, mode_indices,
        )
        min_t, max_t = spell_effect.target_count_range()
        if max_t > 0:
            legal = spell_effect.legal_targets(state, player_id)
            chosen_list: list[tuple[str, int]] = []
            remaining = list(legal)
            slot_kinds = spell_effect.target_slot_kinds()
            for slot_idx in range(max_t):
                if slot_kinds and slot_idx < len(slot_kinds):
                    needed = slot_kinds[slot_idx]
                    pool = [t for t in remaining if t[0] == needed]
                else:
                    pool = remaining
                if not pool:
                    break
                pick = p.agent.choose_target(state, player_id, pool)
                # CR 601.2c: when the agent must pick (slot_idx < min_t)
                # a None / out-of-range answer is illegal — coerce to
                # the first legal pool entry. Above min_t, the agent's
                # decline is honored as "stop adding optional targets"
                # since target_count_range allows fewer than max_t.
                # Removing the picked target from ``remaining`` keeps
                # subsequent slots different (CR 115.1b).
                if pick is None or pick not in pool:
                    if slot_idx < min_t:
                        pick = pool[0]
                    else:
                        break
                chosen_list.append(pick)
                remaining.remove(pick)
            targets = tuple(chosen_list)
    # Auras pick their enchanted-target at cast time. The target is
    # recorded on the StackItem and consumed at resolution to set
    # attached_to. ``aura_enchant_type`` picks the scope: "creature"
    # (default) or "artifact" (Hardlight Containment).
    if card.printing.is_aura:
        enchant_type = card.printing.aura_enchant_type
        if enchant_type == "artifact":
            legal = [
                (enchant_type, o.id)
                for o in state.battlefield
                if o.printing.is_artifact
            ]
        else:
            legal = [
                ("creature", o.id)
                for o in state.battlefield
                if o.printing.is_creature
            ]
        if legal:
            chosen = p.agent.choose_target(state, player_id, legal)
            if chosen is not None:
                targets = (chosen,)
    return targets


def _cast_spell(
    state: GameState, player_id: int, card_id: int,
    use_warp: bool = False, kicked: bool = False,
    cast_for_free: bool = False,
    use_impending: bool = False,
) -> None:
    p = state.player_by_id(player_id)

    # A spell can be cast from the hand (normal or warp cost), from
    # the "warped" / impulse-playable exile zone (normal cost), or —
    # when a permanent grants it — from the top of the library
    # (Mm'menon, the Right Hand). We resolve the source zone up
    # front so the rest of the flow treats it uniformly.
    # ``cast_from_outside_hand`` flags non-hand origins for the
    # spend-restriction tag set composed below (Mm'menon's blue mana
    # ability is usable only for these casts).
    cast_from_outside_hand = False
    card = next((c for c in p.hand if c.id == card_id), None)
    if card is not None:
        if use_impending:
            cost = card.printing.impending_cost
        elif use_warp:
            cost = card.printing.warp_cost
        else:
            cost = card.printing.mana_cost
        p.hand.remove(card)
        # Mark the spell as warp-cast so it triggers the end-step exile once
        # it resolves onto the battlefield.
        card.cast_via_warp = bool(use_warp)
        # Mark the spell as impending-cast so put_into_battlefield
        # initializes ``time_counters`` and sets ``impending_active``.
        # Stored on the card itself (not the StackItem) because the
        # ETB handler in put_into_battlefield reads from the
        # GameObject as it transitions BATTLEFIELD; mirrors the
        # ``cast_via_warp`` precedent. Cleared at ETB after the
        # counter init to avoid double-application if a future
        # effect blinks the permanent.
        card.cast_via_impending = bool(use_impending)
        if use_warp:
            state.spell_warped_this_turn = True
            # Pay the warp ability's "Pay N life" rider, if any (Timeline
            # Culler). legal_actions has already gated p.life > cost.
            life_cost = card.printing.warp_additional_life_cost
            if life_cost > 0:
                p.life -= life_cost
                state.log.append(
                    f"P{player_id} pays {life_cost} life for warp "
                    f"(life: {p.life})"
                )
    elif (
        use_warp
        and (
            grave_card := next(
                (c for c in p.graveyard if c.id == card_id), None
            )
        ) is not None
        and grave_card.printing.warp_castable_from_graveyard
    ):
        # Warp-cast from the graveyard (Timeline Culler).
        card = grave_card
        cost = card.printing.warp_cost
        cast_from_outside_hand = True
        p.graveyard.remove(card)
        card.cast_via_warp = True
        state.spell_warped_this_turn = True
        life_cost = card.printing.warp_additional_life_cost
        if life_cost > 0:
            p.life -= life_cost
            state.log.append(
                f"P{player_id} pays {life_cost} life for warp from "
                f"graveyard (life: {p.life})"
            )
    else:
        # Cast from exile: legal for (a) cards previously exiled by warp
        # (warped=True), (b) cards marked impulse-playable this turn
        # (playable_from_exile_this_turn=True), or (c) cards exiled by
        # Possibility Technician (play_from_exile_requires_kavu=True),
        # provided the controller still controls a Kavu. All pay
        # normal cost. (legal_actions enforces the Kavu-control gate
        # on (c); the predicate here just authorizes the cast site.)
        card = next(
            (
                c for c in p.exile
                if c.id == card_id and (
                    c.warped
                    or c.playable_from_exile_this_turn
                    or c.play_from_exile_requires_kavu
                )
            ),
            None,
        )
        if card is not None:
            cost = card.printing.mana_cost
            cast_from_outside_hand = True
            p.exile.remove(card)
            card.warped = False
            card.playable_from_exile_this_turn = False
            card.play_from_exile_requires_kavu = False
            card.cast_via_warp = False
        else:
            # Cast from top of library (Mm'menon grant). Legal only
            # for the topmost card, and only if the controller has a
            # permanent granting it. legal_actions also requires the
            # card to be an artifact.
            if (
                p.library
                and p.library[0].id == card_id
                and any(
                    o.printing.grants_cast_artifact_from_top_of_library
                    for o in state.battlefield
                    if o.controller_id == player_id
                )
            ):
                card = p.library.pop(0)
                cost = card.printing.mana_cost
                cast_from_outside_hand = True
                card.cast_via_warp = False
            else:  # pragma: no cover - defensive (legal_actions gates)
                raise ValueError(
                    f"card {card_id} not castable by P{player_id}"
                )

    # Schedule the warp end-step exile as a proper delayed triggered
    # ability (CR 603.7). The trigger fires once on the controller's
    # next end step — same turn for sorcery-speed warps cast on the
    # caster's own turn (offset 0), next turn for instant-speed warps
    # cast on an opponent's turn (offset 1, when caster becomes
    # active). At end step, ``run_delayed_end_step_triggers`` wraps
    # this entry as a synthetic ``TriggeredAbility`` and pushes it
    # onto the stack via ``push_triggered_ability``; players then get
    # priority and the standard ``resolve_top_of_stack`` path drains
    # it (logged as "<source>'s delayed trigger goes on the stack").
    # ``WarpExileSelf`` re-checks the battlefield by id at resolve
    # time — if the warp permanent has already left the battlefield
    # (countered, died, bounced, etc.), the resolution is a no-op
    # per CR 603.6c.
    if use_warp:
        from mtg_bot.effects import WarpExileSelf

        offset = 0 if state.active_player().id == player_id else 1
        state.delayed_triggers.append({
            "fire_at_turn": state.turn_number + offset,
            "controller_id": player_id,
            "source_id": card.id,
            "effect": WarpExileSelf(),
        })

    # CR 601.2e: pick modes BEFORE 601.2f cost determination so a
    # mode-dependent cost rider (or a target picked in the chosen
    # mode) can feed into the discount layer. Returns () for non-modal
    # spells. Stored on the StackItem and replayed via
    # state.resolving_modes during resolution so the modal effect
    # doesn't re-prompt.
    chosen_modes: tuple[int, ...] = _choose_modes_at_cast(
        state, player_id, card,
    )
    # Select target(s) BEFORE applying cost reductions. CR 601.2c-f
    # orders modes/targets BEFORE total-cost determination, so any
    # "costs {N} less if it targets <X>" rider (Dark Endurance) needs
    # the chosen target visible to the cost-reduction layer. The
    # ``targets`` tuple flows into ``apply_cost_reductions`` below and
    # later onto the StackItem unchanged.
    targets: tuple[tuple[str, int], ...] = _select_spell_targets(
        state, player_id, card, mode_indices=chosen_modes,
    )

    # Apply cost reductions (e.g., "costs {3} less if you've cast another
    # spell this turn"). Warp costs are reduced too — the rules don't
    # special-case this.
    cost = apply_cost_reductions(
        card.printing, state, player_id, cost, chosen_targets=targets,
    )
    # Kicker: add the optional kicker cost onto the generic+colored
    # portion before X is resolved.
    if kicked and card.printing.kicker_cost is not None:
        kc = card.printing.kicker_cost
        merged_colored: dict[str, int] = dict(cost.colored)
        for color, n in kc.colored:
            merged_colored[color] = merged_colored.get(color, 0) + n
        cost = ManaCost(
            generic=cost.generic + kc.generic,
            colored=tuple(sorted(merged_colored.items())),
            x_pips=cost.x_pips,
        )
        state.log.append(
            f"P{player_id} kicks {card.printing.name} for "
            f"{card.printing.kicker_cost_str}"
        )
    # X-cost spells: ask the agent how much X to pay, fold X*x_pips into
    # generic, then zero x_pips so the payment step sees a concrete cost.
    x_value = 0
    if cost.x_pips > 0:
        x_value = _choose_and_apply_x(state, player_id, card, cost)
        cost = ManaCost(
            generic=cost.generic + cost.x_pips * x_value,
            colored=cost.colored,
            x_pips=0,
        )
    # "Cast without paying its mana cost" (Weftwalking's static
    # alt-cast). Zero out the cost; auto_tap_for_cost still runs but
    # has nothing to pay. Additional non-mana costs (sacrifices, etc.)
    # are paid normally. X is treated as 0 (per CR 601.2f).
    if cast_for_free:
        cost = ManaCost(generic=0, colored=(), x_pips=0)
        x_value = 0
    # Build the set of spend-restriction context tags for this cast.
    # A spell can match more than one (e.g., a legendary artifact
    # spell satisfies both "artifact_spell" and "legendary_spell"
    # restrictions on coins in the pool).
    spell_kinds: set[str] = {"spell"}
    if card.printing.is_artifact:
        spell_kinds.add("artifact_spell")
    # Eldrazi Temple's second mana ability produces coins usable only
    # for colorless-Eldrazi costs. Detect colorless-Eldrazi casts here
    # ("Eldrazi" in subtypes + no colored pips in the printed cost).
    if (
        "Eldrazi" in card.printing.subtypes
        and not card.printing.mana_cost.colored
    ):
        spell_kinds.add("colorless_eldrazi_spell")
    # Plaza of Heroes's second mana ability produces coins usable only
    # to cast a legendary spell.
    if card.printing.is_legendary:
        spell_kinds.add("legendary_spell")
    # Mm'menon, the Right Hand's grant produces coins usable only for
    # casts from outside the controller's hand (graveyard, exile, top
    # of library — set above when we resolved the spell's source zone).
    if cast_from_outside_hand:
        spell_kinds.add("cast_from_outside_hand")
    # CR 601.2g (mana abilities) precedes 601.2h (pay total cost). Sac
    # Treasures and other "sacrifice: Add ..." mana abilities fire
    # FIRST, filling the pool. Convoke is part of paying the cost
    # (CR 702.51b: tapped creatures "pay for" {1} or one mana of
    # their color), so it runs afterwards. The ordering matters when
    # a single source could be used for both — e.g. an Eldrazi Scion
    # with "{T}, Sacrifice this: Add {C}" can EITHER sac for mana
    # here OR convoke below, never both: sacing removes it before
    # convoke runs; if it survives this step, convoke taps it and
    # the {T} portion of the sac cost is no longer payable.
    cost = _activate_sac_for_mana_for_cost(
        state, player_id, cost, frozenset(spell_kinds),
    )
    # Convoke (CR 702.51): part of cost payment at 601.2h. Tapping a
    # creature this way pays for {1} or one mana of its color.
    # ``cast_for_free`` zeroed the cost above, so convoke is a no-op
    # there.
    if card.printing.has_convoke:
        cost = _apply_convoke(state, player_id, cost)
    auto_tap_for_cost(
        state, player_id, cost, spell_kind=frozenset(spell_kinds),
    )
    # Additional cost: sacrifice a creature or artifact. Legal_actions
    # already gated casting on a valid sac target existing; here we
    # just pay by calling sacrifice() on the agent's pick.
    if card.printing.additional_cost_sacrifice_creature_or_artifact:
        sac_options = [
            o for o in state.battlefield
            if o.controller_id == player_id
            and (o.printing.is_creature or o.printing.is_artifact)
        ]
        if sac_options:
            from mtg_bot.turn import sacrifice as _sacrifice

            chosen = sac_options[0]
            if p.agent is not None:
                pick_id = p.agent.choose_sacrifice(
                    state, player_id, [o.id for o in sac_options]
                )
                chosen = next(
                    (o for o in sac_options if o.id == pick_id),
                    sac_options[0],
                )
            state.log.append(
                f"additional cost: P{player_id} sacrifices "
                f"{chosen.printing.name}"
            )
            _sacrifice(state, chosen)
    # Additional cost: designate a creature you control or a warped
    # creature card you own in exile (Close Encounter). Ungated by
    # sacrifice/tap — just a choice. The chosen id lands on the StackItem
    # for the effect to read at resolve.
    additional_cost_choice_id: int | None = None
    if card.printing.additional_cost_choose_your_creature:
        options = [
            o for o in state.battlefield
            if o.controller_id == player_id and o.printing.is_creature
        ]
        options.extend(
            o for o in p.exile
            if o.owner_id == player_id
            and o.warped
            and o.printing.is_creature
        )
        if options:
            chosen_id = options[0].id
            if p.agent is not None:
                pick = p.agent.choose_sacrifice(
                    state, player_id, [o.id for o in options]
                )
                if pick in {o.id for o in options}:
                    chosen_id = pick
            additional_cost_choice_id = chosen_id
            chosen = next(o for o in options if o.id == chosen_id)
            state.log.append(
                f"additional cost: P{player_id} designates "
                f"{chosen.printing.name}"
            )
    card.zone = Zone.STACK
    card.controller_id = player_id

    # Targets were already selected up-front (before cost reductions)
    # so cost-reduction rules that key off the chosen target — e.g.
    # Dark Endurance's "costs {1} less if it targets a blocking
    # creature" — could see the choice.
    countered = _apply_ward_check(state, player_id, targets)
    state.stack.append(
        StackItem(
            source=card, controller_id=player_id, targets=targets,
            countered=countered, x_value=x_value, kicked=kicked,
            additional_cost_choice_id=additional_cost_choice_id,
            chosen_modes=chosen_modes,
        )
    )
    mode = " (warp)" if use_warp else ""
    state.log.append(
        f"P{player_id} casts {card.printing.name}{mode}"
        + _format_log_targets(state, targets)
    )

    # Track cast-count for "whenever you cast your Nth spell" triggers.
    p.spells_cast_this_turn += 1
    # Track noncreature-spell casts for the Deafening Silence
    # restriction ("each player can't cast more than one noncreature
    # spell each turn").
    if not card.printing.is_creature:
        p.noncreature_spells_cast_this_turn += 1
    # Phase-8 predicate-style dispatch: fire the IS_CAST event for
    # every spell cast. The legacy ``second_spell_each_turn`` /
    # ``cast_spell_or_play_land`` (spell half) /
    # ``cast_artifact_spell`` per-key walks were collapsed into this
    # single dispatch when the last in-pool static migrated to
    # predicate shape — every spell-cast observer now flows through
    # the dispatcher's predicate-evaluation loop. The
    # ``Controlled(YOU, subject="controller")`` and
    # ``IsArtifact(subject="spell")`` and ``SpellsCastThisTurn(n=2)``
    # branches all evaluate against the same subject mapping in a
    # single sweep over the battlefield.
    from mtg_bot.effects.predicates import Event as _Event
    dispatch_event(
        state, _Event.IS_CAST, label="is-cast",
        spell=card, controller=p,
    )


def _apply_ward_check(
    state: GameState, caster_id: int,
    targets: tuple[tuple[str, int], ...],
) -> bool:
    """Apply Ward at cast time. For each permanent target controlled by an
    opponent with Ward {cost}, the caster auto-pays the cost by tapping
    additional lands. If they can't pay, the spell is countered and this
    returns True.

    Simplified: no pay-or-counter decision — caster always pays if they
    can. No player-choice surface; Ward is essentially an additional mana
    cost on top of the spell's printed cost.

    Looks at permanent-shaped target kinds (``creature``, ``permanent``,
    ``artifact``, etc.) — anything that resolves to a battlefield object.
    Skips ``player`` and ``stack`` targets. The effective ward cost
    aggregates printed ward and any ward riders granted by attached
    Auras/Equipment (Hardlight Containment).
    """
    from mtg_bot.game import effective_ward_cost

    _NON_PERMANENT_KINDS = {"player", "stack", "spell", "card"}
    for kind, tid in targets:
        if kind in _NON_PERMANENT_KINDS:
            continue
        obj = next((o for o in state.battlefield if o.id == tid), None)
        if obj is None:
            continue
        if obj.controller_id == caster_id:
            continue  # ward doesn't fire on your own permanents
        # Ward — Discard a card at random (Alpharael, Stonechosen).
        if obj.printing.ward_discard_random:
            p = state.player_by_id(caster_id)
            if not p.hand:
                state.log.append(
                    f"Spell countered by {obj.printing.name}'s Ward "
                    f"(hand empty, can't discard)"
                )
                return True
            card = state.rng.choice(p.hand)
            p.hand.remove(card)
            card.zone = Zone.GRAVEYARD
            p.graveyard.append(card)
            state.log.append(
                f"P{caster_id} discards {card.printing.name} at random "
                f"to pay Ward for {obj.printing.name}"
            )
            continue
        # Ward — Discard a card (chosen by caster). Sunset Saboteur.
        if obj.printing.ward_discard_chosen:
            p = state.player_by_id(caster_id)
            if not p.hand:
                state.log.append(
                    f"Spell countered by {obj.printing.name}'s Ward "
                    f"(hand empty, can't discard)"
                )
                return True
            hand_ids = [c.id for c in p.hand]
            chosen_id = p.agent.choose_discard(state, caster_id, hand_ids)
            card = next(c for c in p.hand if c.id == chosen_id)
            p.hand.remove(card)
            card.zone = Zone.GRAVEYARD
            p.graveyard.append(card)
            state.log.append(
                f"P{caster_id} discards {card.printing.name} "
                f"to pay Ward for {obj.printing.name}"
            )
            continue
        ward, ward_str = effective_ward_cost(state, obj)
        if ward is None:
            continue
        if can_pay_cost(state, caster_id, ward):
            auto_tap_for_cost(state, caster_id, ward)
            state.log.append(
                f"P{caster_id} pays Ward {ward_str} "
                f"for {obj.printing.name}"
            )
        else:
            state.log.append(
                f"Spell countered by {obj.printing.name}'s Ward "
                f"{ward_str} (unpaid)"
            )
            return True
    return False


def _effective_ability_mana_cost(
    state: GameState, source: "GameObject", ability,
) -> ManaCost:
    """Return the mana portion of ``ability.cost`` after applying any
    ability-level cost reductions:

      - The Dominion Bracelet's "costs {X} less, where X is this
        creature's power" (flag ``mana_reduced_by_source_power``).
      - Conditional ``CostReduction`` rules attached to the ability via
        ``ActivatedAbility.cost_reductions``. Routed through the same
        ``_evaluate_cost_reduction`` helper that spell-cost reductions
        use, so any condition value supported there works here too
        (currently: ``"another_spell_cast_this_turn"``,
        ``"attacked_with_spacecraft_this_turn"`` (Thaumaton Torpedo),
        ``"void_active"``, ``"opponents_control_three_or_more_creatures"``,
        ``"per_differently_named_land"``,
        ``"control_creature_with_plus_one_counter"`` (Starport Security)).

    Clamps the generic portion at zero.
    """
    from mtg_bot.game import effective_power

    cost = ability.cost.mana
    if cost is None:
        return cost
    if ability.cost.mana_reduced_by_source_power:
        reduction = effective_power(state, source)
        if reduction > 0:
            cost = cost.reduced(reduction)
    for rule in getattr(ability, "cost_reductions", ()):
        reduction = _evaluate_cost_reduction(
            rule, state, source.controller_id,
        )
        if reduction > 0:
            cost = cost.reduced(reduction)
            state.log.append(
                f"ability cost reduced by {reduction} ({rule.condition})"
            )
    return cost


def _activate_ability(
    state: GameState, player_id: int, source_id: int, ability_index: int
) -> None:
    """Pay an activated ability's cost and put it on the stack."""
    from mtg_bot.turn import move_off_battlefield

    source = next((o for o in state.battlefield if o.id == source_id), None)
    if source is None or source.controller_id != player_id:
        return
    from mtg_bot.game import effective_activated_abilities
    abilities = effective_activated_abilities(state, source)
    if ability_index < 0 or ability_index >= len(abilities):
        return
    ability = abilities[ability_index]

    # Pay mana first (auto-tap lands). Dominion Bracelet's granted
    # ability reduces its generic cost by the equipped creature's
    # effective power. For abilities with an X in the cost (Blast
    # Zone's {X}{X}: put X charge counters on this land), ask the
    # agent for X, fold X*x_pips into generic, and stash the chosen
    # X on the StackItem so the resolving effect can read it via
    # state.resolving_x_value.
    ability_x_value = 0
    if ability.cost.mana is not None:
        mana = _effective_ability_mana_cost(state, source, ability)
        if mana.x_pips > 0:
            ability_x_value = _choose_and_apply_x(
                state, player_id, source, mana,
            )
            mana = ManaCost(
                generic=mana.generic + mana.x_pips * ability_x_value,
                colored=mana.colored,
                x_pips=0,
            )
        # Build the set of activation-context spend-restriction tags.
        # Eldrazi Temple's second mana ability lets the colorless
        # Eldrazi owner pay for activations on their Eldrazi.
        # Steelswarm Operator's second mana ability lets the
        # controller pay for activations on artifact sources. Plaza of
        # Heroes's third mana ability ("among legendary permanents you
        # control") is read as "spend only to activate abilities of
        # legendary permanents you control".
        ability_spell_kinds: set[str] = {"spell"}
        if (
            "Eldrazi" in source.printing.subtypes
            and not source.printing.mana_cost.colored
        ):
            ability_spell_kinds.add("colorless_eldrazi_ability")
        if source.printing.is_artifact:
            ability_spell_kinds.add("artifact_activation")
        if source.printing.is_legendary:
            ability_spell_kinds.add("legendary_permanent_ability")
        if source.printing.is_land:
            ability_spell_kinds.add("land_activation")
        auto_tap_for_cost(
            state, player_id, mana,
            spell_kind=frozenset(ability_spell_kinds),
        )

    # Tap-self (if cost requires it).
    if ability.cost.tap_self:
        from mtg_bot.turn import tap_permanent
        tap_permanent(state, source)

    # Target selection for the effect (if it targets). Source is exposed
    # via state.resolving_source during selection so effects with
    # self-exclusion filters (e.g. "another target creature") can read
    # it. Cleared after selection; re-set at resolve_top_of_stack.
    # When the cost sacrifices the source, exclude the source from
    # legal targets — Strip Mine, Petrified Field, etc. can't target
    # themselves because they're sacrificed as part of cost.
    # Supports multi-target via Effect.target_count_range() → (min, max)
    # (Nesting Grounds's "from target permanent you control onto a
    # second target permanent" picks two targets per activation).
    targets: tuple[tuple[str, int], ...] = ()
    if ability.effect.requires_target():
        state.resolving_source = source
        try:
            legal = ability.effect.legal_targets(state, player_id)
        finally:
            state.resolving_source = None
        if ability.cost.sacrifice_self:
            legal = [t for t in legal if t[1] != source.id]
        _, max_t = ability.effect.target_count_range()
        if max_t <= 0:
            max_t = 1  # back-compat with older requires_target-only effects
        if legal:
            p = state.player_by_id(player_id)
            chosen_list: list[tuple[str, int]] = []
            remaining = list(legal)
            slot_kinds = ability.effect.target_slot_kinds()
            for slot_idx in range(max_t):
                if slot_kinds and slot_idx < len(slot_kinds):
                    needed = slot_kinds[slot_idx]
                    pool = [t for t in remaining if t[0] == needed]
                else:
                    pool = remaining
                if not pool:
                    break
                if p.agent is not None:
                    pick = p.agent.choose_target(
                        state, player_id, pool,
                    )
                else:
                    pick = pool[0]
                if pick is None or pick not in pool:
                    break
                chosen_list.append(pick)
                remaining.remove(pick)
            targets = tuple(chosen_list)

    # "Sacrifice another ..." paid BEFORE sacrifice-self so the source
    # stays on the battlefield and is excluded from the option set.
    # legal_actions gates activation on a valid sac existing, so the
    # option list is non-empty when we reach this code.
    if (
        ability.cost.sacrifice_another_creature_or_artifact
        or ability.cost.sacrifice_another_artifact_or_land
        or ability.cost.sacrifice_another_artifact
    ):
        from mtg_bot.turn import sacrifice as _sacrifice

        p = state.player_by_id(player_id)
        if ability.cost.sacrifice_another_creature_or_artifact:
            def _is_valid_sac(o):
                return o.printing.is_creature or o.printing.is_artifact
        elif ability.cost.sacrifice_another_artifact_or_land:
            def _is_valid_sac(o):
                return o.printing.is_artifact or o.printing.is_land
        else:
            def _is_valid_sac(o):
                return o.printing.is_artifact
        options = [
            o for o in state.battlefield
            if o.controller_id == player_id
            and o.id != source.id
            and _is_valid_sac(o)
        ]
        chosen = options[0]
        if p.agent is not None:
            pick_id = p.agent.choose_sacrifice(
                state, player_id, [o.id for o in options]
            )
            chosen = next(
                (o for o in options if o.id == pick_id), options[0]
            )
        state.log.append(
            f"P{player_id} sacrifices {chosen.printing.name} "
            f"(cost for {source.printing.name}'s ability)"
        )
        _sacrifice(state, chosen)

    # "Remove a +1/+1 counter from a creature you control" cost. The
    # agent picks which creature via choose_sacrifice (reusing the
    # existing sacrifice-picker agent hook since the shape is the
    # same: pick an id from a list of battlefield ids). Decrements by
    # one; legal_actions gates on at least one such creature existing.
    if ability.cost.remove_plus_one_counter_from_your_creature:
        p = state.player_by_id(player_id)
        options = [
            o for o in state.battlefield
            if o.controller_id == player_id
            and o.printing.is_creature
            and o.plus_one_counters > 0
        ]
        chosen = options[0]
        if p.agent is not None:
            pick_id = p.agent.choose_sacrifice(
                state, player_id, [o.id for o in options]
            )
            chosen = next(
                (o for o in options if o.id == pick_id), options[0]
            )
        chosen.plus_one_counters -= 1
        state.log.append(
            f"P{player_id} removes a +1/+1 counter from "
            f"{chosen.printing.name} (now {chosen.plus_one_counters}) "
            f"(cost for {source.printing.name}'s ability)"
        )

    # "Pay N life" cost (Mana Confluence etc.). Straight life debit.
    if ability.cost.pay_life:
        p = state.player_by_id(player_id)
        p.life -= ability.cost.pay_life
        state.log.append(
            f"P{player_id} pays {ability.cost.pay_life} life "
            f"(cost for {source.printing.name}'s ability; life: {p.life})"
        )

    # "Sacrifice a land" cost (Dust Bowl). Agent picks; excludes source.
    if ability.cost.sacrifice_a_land:
        from mtg_bot.turn import sacrifice as _sacrifice

        p = state.player_by_id(player_id)
        options = [
            o for o in state.battlefield
            if o.controller_id == player_id
            and o.printing.is_land
            and o.id != source.id
        ]
        if options:
            chosen = options[0]
            if p.agent is not None:
                pick_id = p.agent.choose_sacrifice(
                    state, player_id, [o.id for o in options]
                )
                chosen = next(
                    (o for o in options if o.id == pick_id), options[0]
                )
            state.log.append(
                f"P{player_id} sacrifices {chosen.printing.name} "
                f"(cost for {source.printing.name}'s ability)"
            )
            _sacrifice(state, chosen)

    # "Sacrifice a Desert" cost (Scavenger Grounds). Subtype-filtered.
    if ability.cost.sacrifice_a_desert:
        from mtg_bot.game import effective_subtypes
        from mtg_bot.turn import sacrifice as _sacrifice

        p = state.player_by_id(player_id)
        options = [
            o for o in state.battlefield
            if o.controller_id == player_id
            and "Desert" in effective_subtypes(state, o)
        ]
        if options:
            chosen = options[0]
            if p.agent is not None:
                pick_id = p.agent.choose_sacrifice(
                    state, player_id, [o.id for o in options]
                )
                chosen = next(
                    (o for o in options if o.id == pick_id), options[0]
                )
            state.log.append(
                f"P{player_id} sacrifices {chosen.printing.name} "
                f"(cost for {source.printing.name}'s ability)"
            )
            _sacrifice(state, chosen)

    # "Exile this equipment" cost (Dominion Bracelet). Walk the
    # source's attached equipment with a matching grant flag and exile
    # one. Legal_actions already gated on at least one existing.
    if ability.cost.exile_granting_equipment:
        granter = next(
            (
                eq for eq in state.battlefield
                if eq.attached_to == source.id
                and eq.printing.grants_control_opponent_ability_when_equipped
            ),
            None,
        )
        if granter is not None:
            from mtg_bot.turn import move_off_battlefield
            state.log.append(
                f"P{player_id} exiles {granter.printing.name} "
                f"(cost for {source.printing.name}'s ability)"
            )
            move_off_battlefield(state, granter, destination="exile")

    # "Sacrifice a Food" cost (Ragost). Agent picks via choose_sacrifice.
    # Food status read through effective_subtypes so Ragost-granted
    # Foods count. legal_actions gates on at least one legal Food
    # being available.
    if ability.cost.sacrifice_food:
        from mtg_bot.game import effective_subtypes
        from mtg_bot.turn import sacrifice as _sacrifice

        p = state.player_by_id(player_id)
        options = [
            o for o in state.battlefield
            if o.controller_id == player_id
            and "Food" in effective_subtypes(state, o)
        ]
        chosen = options[0]
        if p.agent is not None:
            pick_id = p.agent.choose_sacrifice(
                state, player_id, [o.id for o in options]
            )
            chosen = next(
                (o for o in options if o.id == pick_id), options[0]
            )
        state.log.append(
            f"P{player_id} sacrifices {chosen.printing.name} "
            f"(Food cost for {source.printing.name}'s ability)"
        )
        _sacrifice(state, chosen)

    # Sacrifice-self is paid LAST so the source is still on the battlefield
    # for target selection — the Lander case where the ability's effect
    # doesn't reference the source but the controller needs to still own it.
    if ability.cost.sacrifice_self:
        from mtg_bot.turn import sacrifice as _sacrifice

        state.log.append(
            f"P{player_id} sacrifices {source.printing.name}"
        )
        _sacrifice(state, source)

    # Mana abilities bypass the stack — resolve the effect immediately
    # (MTG rule 605). Source is exposed via resolving_source for any
    # effect that needs it.
    if ability.is_mana_ability:
        state.resolving_source = source
        try:
            ability.effect.resolve(state, player_id, targets)
        finally:
            state.resolving_source = None
        state.log.append(
            f"P{player_id} activates {source.printing.name}'s mana ability"
        )
        return

    # Put the ability on the stack using the existing StackItem shape.
    state.stack.append(
        StackItem(
            source=source,
            controller_id=player_id,
            ability=ability,
            targets=targets,
            x_value=ability_x_value,
        )
    )
    state.log.append(
        f"P{player_id} activates {source.printing.name}'s ability"
        + _format_log_targets(state, targets)
    )


def _activate_station(
    state: GameState, player_id: int, spacecraft_id: int, crew_id: int
) -> None:
    """Validate and apply a Station activation. Silently no-ops on invalid
    inputs (crew isn't eligible, spacecraft isn't under our control, etc.)."""
    from mtg_bot.game import effective_power

    spacecraft = next(
        (o for o in state.battlefield if o.id == spacecraft_id), None
    )
    crew = next((o for o in state.battlefield if o.id == crew_id), None)
    if spacecraft is None or crew is None:
        return
    if not spacecraft.printing.is_spacecraft:
        return
    if spacecraft.controller_id != player_id:
        return
    if crew.controller_id != player_id:
        return
    if crew.id == spacecraft.id:
        return  # "another creature"
    if not crew.printing.is_creature:
        return  # spacecraft can't crew another spacecraft in Stage 3
    if crew.tapped:
        return
    if crew.summoning_sick:
        # Activated abilities with tap in their cost can't be used on
        # summoning-sick creatures, even for Station.
        return

    from mtg_bot.turn import tap_permanent

    from mtg_bot.game import add_charge_counters
    crew_power = effective_power(state, crew)
    tap_permanent(state, crew)
    added = add_charge_counters(state, spacecraft, crew_power)
    state.log.append(
        f"{crew.printing.name} stations {spacecraft.printing.name} "
        f"(+{added} counters, now {spacecraft.charge_counters})"
    )


def _declare_attackers(
    state: GameState, player_id: int, attacker_ids: frozenset[int]
) -> None:
    from mtg_bot.combat import declare_attackers, eligible_attackers

    eligible_ids = {o.id for o in eligible_attackers(state, player_id)}
    valid = [oid for oid in attacker_ids if oid in eligible_ids]
    declare_attackers(state, valid)


def _declare_blockers(
    state: GameState,
    player_id: int,
    assignments: tuple[tuple[int, int], ...],
) -> None:
    from mtg_bot.combat import can_block, declare_blockers, eligible_blockers

    eligible_ids = {o.id for o in eligible_blockers(state, player_id)}
    attackers = {o.id: o for o in state.battlefield if o.attacking}
    blockers_on_bf = {o.id: o for o in state.battlefield}

    validated: dict[int, int] = {}
    for blocker_id, attacker_id in assignments:
        if blocker_id not in eligible_ids:
            continue
        if attacker_id not in attackers:
            continue
        if blocker_id not in blockers_on_bf:
            continue
        if not can_block(state, blockers_on_bf[blocker_id], attackers[attacker_id]):
            continue
        validated[blocker_id] = attacker_id

    # Menace: if an attacker has menace and was assigned exactly one blocker,
    # the block is illegal — drop it so the attacker goes through unblocked.
    blockers_by_attacker: dict[int, list[int]] = {}
    for bid, aid in validated.items():
        blockers_by_attacker.setdefault(aid, []).append(bid)
    for aid, blocker_ids in blockers_by_attacker.items():
        if (
            "menace" in attackers[aid].printing.keywords
            and len(blocker_ids) < 2
        ):
            for bid in blocker_ids:
                validated.pop(bid, None)

    declare_blockers(state, validated)


def _send_to_graveyard_or_library(state: GameState, card) -> None:
    """Route a non-permanent spell (or failed-cost / countered card) to
    its owner's graveyard — unless the card's printing has
    ``shuffles_into_library_instead_of_graveyard`` set, in which case
    it's shuffled into the owner's library instead.

    Nexus of Fate + Green Sun's Zenith both use this redirect. Shuffle
    draws from ``state.rng`` so the run is reproducible from the
    caller-supplied seed.
    """
    owner = state.player_by_id(card.owner_id)
    if card.printing.shuffles_into_library_instead_of_graveyard:
        from mtg_bot.game import shuffle_library
        card.zone = Zone.LIBRARY
        owner.library.append(card)
        shuffle_library(state, owner.id)
        state.log.append(
            f"{card.printing.name} is shuffled into P{card.owner_id}'s "
            f"library instead of graveyard"
        )
        return
    card.zone = Zone.GRAVEYARD
    owner.graveyard.append(card)


def drain_stack(state: GameState) -> None:
    """Resolve every StackItem until empty, interleaving SBAs.

    Engine-level utility used by tests that fire triggers via direct calls
    (``declare_attackers``, ``declare_blockers``, ``put_into_battlefield``,
    etc.) and then need to observe the trigger's *resolved* effects. The
    real engine drains the stack via the priority loop; tests that bypass
    priority must drain explicitly.
    """
    from mtg_bot.turn import state_based_actions
    while state.stack:
        resolve_top_of_stack(state)
        state_based_actions(state)


def resolve_top_of_stack(state: GameState) -> None:
    item = state.stack.pop()

    # Countered spells: no effects, no ETBs; the card goes to its owner's
    # graveyard (permanents and non-permanents alike) per rule 701.5a.
    if item.countered:
        state.log.append(f"{item.source.printing.name} is countered")
        _send_to_graveyard_or_library(state, item.source)
        return

    # Triggered- or activated-ability resolution. StackItem.ability holds
    # either a TriggeredAbility or an ActivatedAbility — distinguish by
    # type so the log accurately names which kind resolved.
    if item.ability is not None:
        from mtg_bot.effects import ActivatedAbility

        kind = (
            "activated"
            if isinstance(item.ability, ActivatedAbility)
            else "triggered"
        )
        state.log.append(
            f"{item.source.printing.name}'s {kind} ability resolves"
        )
        state.resolving_source = item.source
        state.resolving_x_value = item.x_value
        state.resolving_kicked = item.kicked
        state.resolving_additional_cost_choice_id = (
            item.additional_cost_choice_id
        )
        state.resolving_combat_damage_amount = item.combat_damage_amount
        state.resolving_combat_damage_source_controller_id = (
            item.combat_damage_source_controller_id
        )
        state.resolving_counter_amount = item.counter_amount
        state.resolving_modes = item.chosen_modes
        try:
            item.ability.effect.resolve(state, item.controller_id, item.targets)
        finally:
            state.resolving_source = None
            state.resolving_x_value = 0
            state.resolving_kicked = False
            state.resolving_additional_cost_choice_id = None
            state.resolving_combat_damage_amount = 0
            state.resolving_combat_damage_source_controller_id = None
            state.resolving_counter_amount = 0
            state.resolving_modes = ()
        return

    # Spell resolution
    card = item.source
    state.resolving_x_value = item.x_value
    state.resolving_kicked = item.kicked
    state.resolving_additional_cost_choice_id = item.additional_cost_choice_id
    state.resolving_modes = item.chosen_modes
    try:
        if card.printing.is_permanent and not (
            card.printing.is_instant or card.printing.is_sorcery
        ):
            # Aura: check the cast-time target is still a legal creature/
            # artifact depending on aura_enchant_type. If not, the Aura
            # fizzles to its owner's graveyard without entering.
            if card.printing.is_aura:
                enchant_type = card.printing.aura_enchant_type
                target_obj = None
                if item.targets:
                    kind, target_id = item.targets[0]
                    if kind == enchant_type:
                        if enchant_type == "artifact":
                            target_obj = next(
                                (o for o in state.battlefield
                                 if o.id == target_id
                                 and o.printing.is_artifact),
                                None,
                            )
                        else:
                            target_obj = next(
                                (o for o in state.battlefield
                                 if o.id == target_id
                                 and o.printing.is_creature),
                                None,
                            )
                if target_obj is None:
                    state.log.append(
                        f"{card.printing.name} fizzles (no legal enchant target)"
                    )
                    _send_to_graveyard_or_library(state, card)
                    return
                card.attached_to = target_obj.id
                state.log.append(
                    f"{card.printing.name} enters attached to "
                    f"{target_obj.printing.name}"
                )
                # Static "you control enchanted permanent" applies
                # immediately when the aura enters — BEFORE any ETB
                # triggers go on the stack. Static abilities are
                # continuous, not stack-based, so the swap kicks in
                # the moment the aura is attached. Tractor Beam.
                apply_aura_static_grants_on_attach(
                    state, card, target_obj, item.controller_id,
                )
            else:
                state.log.append(
                    f"{card.printing.name} resolves onto the battlefield"
                )
                if card.printing.enters_as_copy_of_creature:
                    apply_clone_enters_as_copy_replacement(
                        state, card, item.controller_id,
                    )
            put_into_battlefield(state, card, item.controller_id)
            return
        if card.printing.is_instant or card.printing.is_sorcery:
            state.log.append(f"{card.printing.name} resolves")
            if card.printing.spell_effect is not None:
                card.printing.spell_effect.resolve(
                    state, item.controller_id, item.targets
                )
            # Non-permanent spells go to their owner's graveyard —
            # unless a zone-change replacement routes them elsewhere
            # (Nexus of Fate + Green Sun's Zenith shuffle back in).
            _send_to_graveyard_or_library(state, card)
            return
        raise ValueError(f"don't know how to resolve {card.printing.name}")
    finally:
        state.resolving_x_value = 0
        state.resolving_kicked = False
        state.resolving_additional_cost_choice_id = None
        state.resolving_modes = ()


def apply_aura_static_grants_on_attach(
    state: GameState, aura: "GameObject", target: "GameObject",
    controller_id: int,
) -> None:
    """Apply an aura's continuous-while-attached statics to its
    target the moment the aura enters attached. Static abilities are
    continuous (not stack-based), so they take effect immediately —
    before any ETB triggers go on the stack.

    Models the following printing flags by writing matching
    registry entries with ``expires_at=None`` (static-while-attached;
    ``move_off_battlefield`` drops them via
    ``remove_continuous_effects_from_source(only_static=True)``):

    - ``attached_grants_control`` → layer 2 ``"control_change"``
      (Tractor Beam). Most-recent timestamp wins; baseline captured
      on the first grant for revert order.
    - ``attached_sets_base_pt`` → layer 7 sublayer 1 ``"set_base_pt"``
      (Lignify). Overrides base P/T while attached.
    - ``attached_grants_lose_all_abilities`` → layer 6
      ``"lose_all_abilities"`` (Lignify). Suppresses every printed
      and granted ability/keyword/trigger.
    - ``attached_grants_subtype`` → layer 4 ``"add_subtype"``
      (Lignify granting "Treefolk").

    Each is independent — a printing may set any combination.
    """
    from mtg_bot.game import effective_controller

    if aura.printing.attached_grants_control:
        if effective_controller(state, target) != controller_id:
            # First control-grant on this target: capture the baseline.
            has_prior_grant = any(
                ce.layer == 2
                and ce.kind == "control_change"
                and ce.target_id == target.id
                for ce in state.continuous_effects
            )
            if not has_prior_grant:
                target.controller_id_before_any_aura_swap = target.controller_id
            state.add_continuous_effect(
                source_id=aura.id,
                layer=2,
                kind="control_change",
                target_id=target.id,
                params=(controller_id,),
                description=(
                    f"{aura.printing.name} grants P{controller_id} "
                    f"control of {target.printing.name}"
                ),
            )
            target.controller_id = effective_controller(state, target)
            state.log.append(
                f"P{controller_id} gains control of "
                f"{target.printing.name} via {aura.printing.name}"
            )

    if aura.printing.attached_sets_base_pt is not None:
        power, toughness = aura.printing.attached_sets_base_pt
        state.add_continuous_effect(
            source_id=aura.id,
            layer=7,
            sublayer=1,
            kind="set_base_pt",
            target_id=target.id,
            params=(power, toughness),
            description=(
                f"{aura.printing.name} sets {target.printing.name} "
                f"base P/T to {power}/{toughness}"
            ),
        )

    if aura.printing.attached_grants_lose_all_abilities:
        state.add_continuous_effect(
            source_id=aura.id,
            layer=6,
            kind="lose_all_abilities",
            target_id=target.id,
            params=(),
            description=(
                f"{aura.printing.name}: {target.printing.name} loses "
                f"all abilities"
            ),
        )

    if aura.printing.attached_grants_subtype is not None:
        sub = aura.printing.attached_grants_subtype
        state.add_continuous_effect(
            source_id=aura.id,
            layer=4,
            kind="add_subtype",
            target_id=target.id,
            params=(sub,),
            description=(
                f"{aura.printing.name}: {target.printing.name} is "
                f"a {sub}"
            ),
        )


def apply_clone_enters_as_copy_replacement(
    state: GameState, clone: "GameObject", controller_id: int,
) -> None:
    """Clone-style ETB replacement: 'this creature may enter as a
    copy of any creature on the battlefield.' Called during spell
    resolution AFTER the resolves-onto-battlefield log line and
    BEFORE ``put_into_battlefield``, so the clone is still off-
    battlefield when the controller picks a target.

    Asks the controller's agent to choose a creature on the
    battlefield. If chosen, snapshots ``original_printing`` (so the
    clone remembers what it was) and replaces ``printing`` with the
    target's printing (CR 706.2 copiable values — auras, counters,
    animations, and other continuous effects on the target are NOT
    copied since they don't live on the printing). Writes a layer-1
    ``"is_copy"`` registry entry sourced by the clone with
    ``expires_at=None``; ``move_off_battlefield(only_static=True)``
    drops the entry when the clone leaves play (the entry is
    informational since the printing mutation is the source of
    truth for cached reads).

    If no creature is on the battlefield or the agent declines, the
    clone enters as its printed self (no mutation, no log).
    """
    from mtg_bot.game import is_creature_now

    if not clone.printing.enters_as_copy_of_creature:
        return
    # ``is_creature_now`` (not just ``printing.is_creature``) so an
    # animated manland is a legal copy target. The clone still copies
    # the manland's printing — which is the LAND printing — so the
    # clone enters as a land. See test_clone_of_animated_manland.
    candidates: list[tuple[str, int]] = [
        ("creature", o.id)
        for o in state.battlefield
        if is_creature_now(o)
    ]
    if not candidates:
        return
    p = state.players[controller_id]
    chosen = p.agent.choose_target(state, controller_id, candidates)
    if chosen is None:
        return
    _, target_id = chosen
    target = next(
        (o for o in state.battlefield if o.id == target_id), None,
    )
    if target is None:
        return
    if clone.original_printing is None:
        clone.original_printing = clone.printing
    target_printing = target.printing
    clone.printing = target_printing
    state.add_continuous_effect(
        source_id=clone.id,
        layer=1,
        kind="is_copy",
        target_id=clone.id,
        params=(target_printing,),
        description=(
            f"{clone.original_printing.name} is a copy of "
            f"{target_printing.name}"
        ),
    )
    state.log.append(
        f"{clone.original_printing.name} enters as a copy of "
        f"{target_printing.name}"
    )


def put_into_battlefield(
    state: GameState, obj: "GameObject", controller_id: int
) -> None:
    """Move ``obj`` onto the battlefield and fire any ETB triggers.

    Shared by spell resolution and token-creation effects so both flows go
    through the same state transition and trigger pipeline.

    After the object's own ETB triggers, fires "whenever another artifact
    you control enters" triggers on other permanents the controller
    controls if the entering object is an artifact.
    """
    obj.zone = Zone.BATTLEFIELD
    obj.controller_id = controller_id
    obj.tapped = False
    obj.summoning_sick = True
    # Impending: a spell cast for its impending cost enters with N
    # time counters and is suppressed-as-non-creature until the
    # last counter is removed. The cast site set
    # ``cast_via_impending`` on the GameObject; consume the flag
    # here (so a future blink-and-recast under the printed cost
    # doesn't reactivate the suppression) and initialize the
    # impending state. The end-step turn-based action
    # ``run_impending_decrement_turn_based_action`` decrements
    # ``time_counters`` and clears ``impending_active`` when the
    # last counter is removed.
    if obj.cast_via_impending and obj.printing.impending_count > 0:
        obj.time_counters = obj.printing.impending_count
        obj.impending_active = True
    obj.cast_via_impending = False
    # Snapshot the moment of ETB for static-effect timestamp use
    # (Magus / Dryad layer-4 synthesizing in effective_subtypes,
    # Painter's Servant layer-5, Humility layer-6/7b). Bump
    # ``next_timestamp`` past this snapshot so subsequent registry
    # writes (including the synthesizing-side's expectation of a
    # higher timestamp) are strictly later in the layer walks.
    obj.etb_timestamp = state.next_timestamp
    state.next_timestamp += 1
    # Painter's Servant: "As Painter's Servant enters, choose a
    # color." The chosen color is captured on the GameObject and
    # consumed by ``effective_colors`` when synthesizing the
    # layer-5 ``add_colors`` entry sourced by this permanent.
    if obj.printing.paints_all_objects_chosen_color_at_etb:
        chosen = state.players[controller_id].agent.choose_mana_color(
            state, controller_id, ["W", "U", "B", "R", "G"],
        )
        if chosen in ("W", "U", "B", "R", "G"):
            obj.painter_chosen_color = chosen
            state.log.append(
                f"{obj.printing.name} enters; chose color {chosen}"
            )
    # (Kavu observer trigger fires below, after own ETB.)
    # "Enters with +1/+1 counters equal to X" replacement effects. Applied
    # before triggered abilities so any ETB that reads the creature's
    # state sees the counters already in place.
    mode = obj.printing.enters_with_counters_from_x
    if mode == "x":
        from mtg_bot.game import add_plus_one_counters
        add_plus_one_counters(state, obj, state.resolving_x_value)
    elif mode == "mana_spent":
        from mtg_bot.game import add_plus_one_counters
        mc = obj.printing.mana_cost
        add_plus_one_counters(
            state, obj,
            state.resolving_x_value
            + mc.generic
            + sum(n for _, n in mc.colored),
        )
    # External anthems that grant extra ETB counters to creatures:
    # "Each creature you control enters with an additional +1/+1 counter
    # on it for each land that entered the battlefield under your control
    # this turn" (Bioengineered Future). Applied per source on the
    # controller's battlefield — multiple sources stack.
    if obj.printing.is_creature:
        controller = state.player_by_id(controller_id)
        anthem_sources = sum(
            1 for o in state.battlefield
            if o.controller_id == controller_id
            and getattr(
                o.printing,
                "grants_etb_counter_per_land_entered_this_turn",
                False,
            )
        )
        if anthem_sources and controller.lands_entered_this_turn:
            from mtg_bot.game import add_plus_one_counters
            add_plus_one_counters(
                state, obj,
                anthem_sources * controller.lands_entered_this_turn,
            )
    # Planeswalker: initialize loyalty counters to the printed starting
    # loyalty. Only applied the first time the card enters the
    # battlefield (loyalty_counters starts at 0).
    if obj.printing.is_planeswalker and obj.printing.loyalty is not None:
        obj.loyalty_counters = obj.printing.loyalty
    # Devour land N: as ``obj`` enters, agent may sacrifice any number
    # of lands; obj enters with N counters per land sacrificed.
    # Simplification: the random baseline doesn't ramp Famished's own
    # counters — see docstring on CardPrinting.devour_land_multiplier.
    if obj.printing.devour_land_multiplier > 0:
        _apply_devour(state, obj, controller_id)
    state.battlefield.append(obj)
    # Track land ETBs for "lands entered under your control this turn"
    # (Bioengineered Future). Distinct from lands_played_this_turn — this
    # also covers basics fetched via Lander tokens or other search-and-
    # put-onto-battlefield effects that don't go through _play_land.
    if obj.printing.is_land:
        state.player_by_id(controller_id).lands_entered_this_turn += 1
    if obj.printing.is_artifact:
        # Track per-player "an artifact entered under your control
        # this turn" for static-ability gates like Mechan Shieldmate's
        # conditional attack-bypass for defenders. Counts artifact
        # creatures and artifact tokens too. Reset at cleanup.
        state.player_by_id(
            controller_id
        ).artifacts_entered_under_your_control_this_turn += 1
    _trigger_etb_abilities(state, obj)


def _apply_devour(
    state: GameState, obj: "GameObject", controller_id: int
) -> None:
    """Devour land N: ask the agent (via ``choose_devour_lands``) for
    the subset of lands to sacrifice; sacrifice those and add
    N * (count sacrificed) +1/+1 counters to ``obj``.
    """
    from mtg_bot.turn import sacrifice as _sacrifice

    p = state.player_by_id(controller_id)
    if p.agent is None:
        return
    land_ids = [
        o.id for o in state.battlefield
        if o.controller_id == controller_id and o.printing.is_land
    ]
    if not land_ids:
        return
    picks = p.agent.choose_devour_lands(state, controller_id, land_ids)
    valid_picks = [pid for pid in picks if pid in set(land_ids)]
    sacrificed = 0
    for pid in valid_picks:
        victim = next(
            (o for o in state.battlefield if o.id == pid), None
        )
        if victim is None or not victim.printing.is_land:
            continue
        _sacrifice(state, victim)
        sacrificed += 1
    if sacrificed > 0:
        from mtg_bot.game import add_plus_one_counters
        counters = obj.printing.devour_land_multiplier * sacrificed
        add_plus_one_counters(state, obj, counters)
        state.log.append(
            f"{obj.printing.name} devours {sacrificed} land(s) and "
            f"enters with {counters} +1/+1 counters"
        )


def push_triggered_ability(
    state: GameState,
    *,
    source: "GameObject",
    ability,
    ability_index: int,
    controller_id: int,
    label: str,
    combat_damage_amount: int = 0,
    combat_damage_source_controller_id: int | None = None,
    counter_amount: int = 0,
    fixed_targets: tuple[tuple[str, int], ...] | None = None,
) -> bool:
    """Push a triggered ability onto the stack, picking targets if needed.

    Centralizes the trigger-firing path so every triggered ability gets a
    response window instead of resolving immediately at the fire site.

    - ``label``: short descriptor used in the log (e.g. ``"dies"``,
      ``"attacks"``). The log line reads
      ``f"{source.name}'s {label} trigger goes on the stack" + targets``.
    - ``ability_index``: index into ``source.printing.triggered_abilities``;
      used by ``should_fire_trigger`` for the ``once_per_turn`` ledger.
    - ``combat_damage_amount``: stashed on the StackItem for
      combat-damage triggers so the resolving effect can read
      ``state.resolving_combat_damage_amount``.
    - ``fixed_targets``: when the trigger's targets are determined by the
      event itself (e.g. "the player who was hit"), pass them here and
      target selection is skipped. Otherwise the controller's agent picks
      from ``effect.legal_targets`` as the ability goes on the stack.

    Returns True when the ability lands on the stack, False when it's
    gated off (tier/once-per-turn/void) or fizzles (no legal targets).
    """
    from mtg_bot.turn import should_fire_trigger

    if not should_fire_trigger(state, source.id, ability_index, ability):
        return False
    effect = ability.effect
    if fixed_targets is not None:
        targets: tuple[tuple[str, int], ...] = fixed_targets
    else:
        targets = ()
        min_t, max_t = effect.target_count_range()
        if max_t > 0:
            state.resolving_source = source
            state.resolving_combat_damage_amount = combat_damage_amount
            try:
                legal = effect.legal_targets(state, controller_id)
            finally:
                state.resolving_source = None
                state.resolving_combat_damage_amount = 0
            if not legal and min_t > 0:
                state.log.append(
                    f"{source.printing.name}'s {label} trigger has no "
                    f"legal targets; fizzles"
                )
                return False
            controller = state.player_by_id(controller_id)
            chosen_list: list[tuple[str, int]] = []
            remaining = list(legal)
            slot_kinds = effect.target_slot_kinds()
            for slot_idx in range(max_t):
                # Per-slot kind enforcement: when the effect declares
                # ``target_slot_kinds`` (e.g., Diplomatic Relations:
                # ``("my_creature", "creature")``), restrict the agent's
                # choices for THIS slot to entries of the declared kind.
                # Empty tuple keeps the legacy flat-pool behavior.
                if slot_kinds and slot_idx < len(slot_kinds):
                    needed = slot_kinds[slot_idx]
                    pool = [t for t in remaining if t[0] == needed]
                else:
                    pool = remaining
                if not pool:
                    break
                if controller.agent is None:  # pragma: no cover
                    break
                pick = controller.agent.choose_target(
                    state, controller_id, pool
                )
                if pick is None or pick not in pool:
                    break
                chosen_list.append(pick)
                remaining.remove(pick)
            if len(chosen_list) < min_t:  # pragma: no cover
                state.log.append(
                    f"{source.printing.name}'s {label} trigger had no "
                    f"target chosen; fizzles"
                )
                return False
            targets = tuple(chosen_list)
    state.stack.append(
        StackItem(
            source=source,
            controller_id=controller_id,
            ability=ability,
            targets=targets,
            combat_damage_amount=combat_damage_amount,
            combat_damage_source_controller_id=(
                combat_damage_source_controller_id
            ),
            counter_amount=counter_amount,
        )
    )
    state.log.append(
        f"{source.printing.name}'s {label} trigger goes on the stack"
        + _format_log_targets(state, targets)
    )
    return True


def dispatch_event(
    state: GameState,
    event,
    *,
    label: str | None = None,
    extra_observers: "list | None" = None,
    combat_damage_amount: int = 0,
    combat_damage_source_controller_id: int | None = None,
    counter_amount: int = 0,
    fixed_targets: tuple[tuple[str, int], ...] | None = None,
    **subjects,
) -> None:
    """Centralized predicate-trigger dispatcher.

    Walks every battlefield permanent and fires any predicate-style
    triggered ability whose ``event`` matches ``event`` and whose
    ``predicate`` evaluates true against ``subjects`` and the source.
    String-key (legacy) abilities are NOT fired here — they continue
    flowing through the per-event ``_fire_*`` paths until migration
    is complete. Both styles coexist; ``__post_init__`` on
    ``TriggeredAbility`` enforces that no single ability sets both.

    ``label`` is the human-readable string attached to the resulting
    stack item (defaults to the event's value, e.g. ``"enters"``).
    ``subjects`` is the named subject mapping for the event — see
    ``EVENT_SUBJECTS`` in ``effects/predicates.py``.

    ``extra_observers`` is an additional list of ``GameObject`` whose
    triggered abilities should be checked alongside the battlefield.
    Used by DIES / LEAVES_BATTLEFIELD dispatch to include the dearly-
    departed (already moved off the battlefield by the caller) as a
    candidate observer for its own self-triggers (``IsSelf()`` against
    the dying object). Permanents on the battlefield that ALSO appear
    in ``extra_observers`` are not double-counted.

    ``combat_damage_amount`` threads the damage amount through to each
    pushed StackItem so resolving effects can read
    ``state.resolving_combat_damage_amount``. Used by the DEALT_DAMAGE
    dispatch (Pain for All's echo, Cryoshatter's destroy-on-damage,
    etc.); zero for events that don't carry damage. ``counter_amount``
    is the analogous channel for the COUNTERS_ADDED event
    (Terrasymbiosis's "draw that many cards" rider). ``fixed_targets``
    forwards a pre-determined target tuple to every pushed StackItem
    (used by DISCARDS_CARD to expose the discarding player as
    ``("player", id)`` so Entropic Battlecruiser's "they lose 3 life"
    half can damage them without needing target selection).

    For ``Event.ENTERS`` the per-source firings are multiplied by
    ``etb_trigger_multiplier`` (Starfield Vocalist's "triggers an
    additional time" replacement). The legacy ``_fire_*`` paths apply
    the same multiplier — keeping the dispatcher consistent means a
    landfall trigger migrated to the predicate path keeps doubling
    under Starfield, the same way the ``etb`` self-trigger path does
    in ``_trigger_etb_abilities``.
    """
    from mtg_bot.effects.predicates import Event as _Event
    from mtg_bot.game import etb_trigger_multiplier

    if label is None:
        label = event.value
    # Snapshot the battlefield: triggers that ETB new permanents during
    # dispatch must not themselves see those new permanents on the
    # original event's pass.
    permanents = list(state.battlefield)
    if extra_observers:
        seen_ids = {p.id for p in permanents}
        for extra in extra_observers:
            if extra.id not in seen_ids:
                permanents.append(extra)
                seen_ids.add(extra.id)
    for source in permanents:
        for ability_index, ability in enumerate(
            source.printing.triggered_abilities
        ):
            if not ability.matches_event(event, subjects, source, state):
                continue
            firings = (
                etb_trigger_multiplier(state, source.controller_id)
                if event is _Event.ENTERS else 1
            )
            for _ in range(firings):
                push_triggered_ability(
                    state,
                    source=source,
                    ability=ability,
                    ability_index=ability_index,
                    controller_id=source.controller_id,
                    label=label,
                    combat_damage_amount=combat_damage_amount,
                    combat_damage_source_controller_id=(
                        combat_damage_source_controller_id
                    ),
                    counter_amount=counter_amount,
                    fixed_targets=fixed_targets,
                )


def _trigger_etb_abilities(state: GameState, creature: "GameObject") -> None:
    """Push every ENTERS-event triggered ability that matches when
    ``creature`` enters the battlefield.

    All ETB-family triggers (this-creature-enters, landfall,
    artifact-enters-you-control, kavu-enters-you-control, etc.) flow
    through ``dispatch_event(state, Event.ENTERS, obj=creature)``. The
    dispatcher walks every battlefield permanent, evaluates each
    ability's predicate against the entering object, and pushes
    matched abilities onto the stack via ``push_triggered_ability``.

    Phase 2 migrated every static card from the legacy string-key
    ``trigger="etb"`` (and the family of ``"landfall"`` /
    ``"artifact_enters_you_control"`` / etc. keys) to the predicate
    shape, so the legacy per-key ``_fire_*`` paths are gone — there
    are no string-key abilities left to fire.
    """
    from mtg_bot.effects.predicates import Event

    dispatch_event(state, Event.ENTERS, label="enters", obj=creature)
