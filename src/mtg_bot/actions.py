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
        obj = next((o for o in state.battlefield if o.id == tid), None)
        if obj is not None:
            parts.append(obj.printing.name)
            continue
        on_stack = next((s for s in state.stack if s.source.id == tid), None)
        if on_stack is not None:
            parts.append(on_stack.source.printing.name)
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


def _coin_satisfies_context(coin: "ManaCoin", spell_kind: str) -> bool:
    """True if ``coin``'s spend restriction is compatible with a
    payment for ``spell_kind``. Known spell_kind values:
      - "spell" (default): only unrestricted coins.
      - "artifact_spell": unrestricted or "artifact_spell"-tagged.
      - "colorless_eldrazi_spell": unrestricted or
        "colorless_eldrazi"-tagged (Eldrazi Temple's second mana
        ability). Set when casting a spell that is a colorless
        Eldrazi (``"Eldrazi" in subtypes`` and no colored pips).
      - "colorless_eldrazi_ability": unrestricted or
        "colorless_eldrazi"-tagged. Set when activating an ability
        on a colorless-Eldrazi permanent.
      - "activated_ability": unrestricted only (for now — future
        "artifact_activation" tag would go here).
    """
    if coin.spend_restriction is None:
        return True
    if spell_kind == "artifact_spell" and coin.spend_restriction == "artifact_spell":
        return True
    if spell_kind in (
        "colorless_eldrazi_spell", "colorless_eldrazi_ability"
    ) and coin.spend_restriction == "colorless_eldrazi":
        return True
    return False


def can_pay_cost(
    state: GameState, player_id: int, cost: ManaCost,
    spell_kind: str = "spell",
) -> bool:
    """Check whether the player can pay ``cost`` by consuming floating
    mana in their pool (respecting spend restrictions for ``spell_kind``)
    then tapping untapped lands.
    """
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
        reduction = 0
        if rule.condition == "another_spell_cast_this_turn":
            if state.player_by_id(caster_id).spells_cast_this_turn >= 1:
                reduction = rule.amount
        elif rule.condition == "attacked_with_spacecraft_this_turn":
            if state.player_by_id(
                caster_id
            ).attacked_with_spacecraft_this_turn:
                reduction = rule.amount
        elif rule.condition == "void_active":
            from mtg_bot.game import is_void_active

            if is_void_active(state):
                reduction = rule.amount
        elif rule.condition == "opponents_control_three_or_more_creatures":
            opp_creatures = sum(
                1 for o in state.battlefield
                if o.controller_id != caster_id and o.printing.is_creature
            )
            if opp_creatures >= 3:
                reduction = rule.amount
        elif rule.condition == "per_differently_named_land":
            if rule.per_land_group:
                names: set[str] = set()
                for o in state.battlefield:
                    if (
                        o.controller_id == caster_id
                        and o.printing.is_land
                    ):
                        names.add(o.printing.name)
                reduction = rule.amount * len(names)
        else:
            state.log.append(
                f"unknown cost-reduction condition {rule.condition!r}; "
                f"treating as no reduction"
            )
        if reduction > 0:
            cost = cost.reduced(reduction)
            state.log.append(
                f"cost reduced by {reduction} ({rule.condition})"
            )
    return cost


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


def auto_tap_for_cost(
    state: GameState, player_id: int, cost: ManaCost,
    spell_kind: str = "spell",
) -> list[GameObject]:
    """Pay ``cost`` by consuming floating mana first (respecting spend
    restrictions for ``spell_kind``), then tapping lands for the
    remainder. Returns the list of lands tapped. Mutates the pool
    and the tapped lands.
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
    raise ValueError(f"unknown action: {action!r}")


def _play_land(state: GameState, player_id: int, card_id: int) -> None:
    from mtg_bot.turn import fire_landfall_triggers

    p = state.player_by_id(player_id)
    # Source may be hand (normal play) or exile (impulse-cast lands).
    card = next((c for c in p.hand if c.id == card_id), None)
    if card is not None:
        p.hand.remove(card)
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
    _trigger_etb_abilities(state, card)
    fire_landfall_triggers(state, card)
    # "Whenever an opponent plays a land" triggers (Burgeoning) —
    # specifically the land-drop action, not any ETB. Fires under each
    # opposing permanent-controller.
    from mtg_bot.turn import fire_opponent_plays_land_triggers
    fire_opponent_plays_land_triggers(state, player_id)
    # Fire "whenever you play a land or cast a spell" triggers (The
    # Endstone). The spell-cast path fires the same from _cast_spell.
    _fire_cast_or_play_triggers(state, player_id)


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


def _cast_spell(
    state: GameState, player_id: int, card_id: int,
    use_warp: bool = False, kicked: bool = False,
) -> None:
    p = state.player_by_id(player_id)

    # A spell can be cast from the hand (normal or warp cost), from
    # the "warped" / impulse-playable exile zone (normal cost), or —
    # when a permanent grants it — from the top of the library
    # (Mm'menon, the Right Hand). We resolve the source zone up
    # front so the rest of the flow treats it uniformly.
    card = next((c for c in p.hand if c.id == card_id), None)
    if card is not None:
        cost = (
            card.printing.warp_cost
            if use_warp
            else card.printing.mana_cost
        )
        p.hand.remove(card)
        # Mark the spell as warp-cast so it triggers the end-step exile once
        # it resolves onto the battlefield.
        card.cast_via_warp = bool(use_warp)
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
        # (warped=True), or (b) cards marked impulse-playable this turn
        # (playable_from_exile_this_turn=True). Both pay normal cost.
        card = next(
            (
                c for c in p.exile
                if c.id == card_id and (
                    c.warped or c.playable_from_exile_this_turn
                )
            ),
            None,
        )
        if card is not None:
            cost = card.printing.mana_cost
            p.exile.remove(card)
            card.warped = False
            card.playable_from_exile_this_turn = False
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
                card.cast_via_warp = False
            else:  # pragma: no cover - defensive (legal_actions gates)
                raise ValueError(
                    f"card {card_id} not castable by P{player_id}"
                )

    # Apply cost reductions (e.g., "costs {3} less if you've cast another
    # spell this turn"). Warp costs are reduced too — the rules don't
    # special-case this.
    cost = apply_cost_reductions(card.printing, state, player_id, cost)
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
    spell_kind = (
        "artifact_spell" if card.printing.is_artifact else "spell"
    )
    # Eldrazi Temple's second mana ability produces coins usable only
    # for colorless-Eldrazi costs. Detect colorless-Eldrazi casts here
    # ("Eldrazi" in subtypes + no colored pips in the printed cost).
    if (
        "Eldrazi" in card.printing.subtypes
        and not card.printing.mana_cost.colored
    ):
        spell_kind = "colorless_eldrazi_spell"
    auto_tap_for_cost(state, player_id, cost, spell_kind=spell_kind)
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

    # If this spell has a targeted spell_effect, select target(s) now.
    # Supports multi-target via Effect.target_count_range() → (min, max).
    targets: tuple[tuple[str, int], ...] = ()
    spell_effect = card.printing.spell_effect
    if spell_effect is not None:
        min_t, max_t = spell_effect.target_count_range()
        if max_t > 0:
            legal = spell_effect.legal_targets(state, player_id)
            chosen_list: list[tuple[str, int]] = []
            remaining = list(legal)
            for _ in range(max_t):
                if not remaining:
                    break
                pick = p.agent.choose_target(state, player_id, remaining)
                # Agent declines → stop. In practice every EoE multi-
                # target effect we model has min_t=0 so declines are
                # always honored. If min_t > 0 is ever added, revive
                # the "forced pick" branch.
                if pick is None:
                    break
                if pick not in remaining:
                    # Agent picked an out-of-range target; ignore.
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

    countered = _apply_ward_check(state, player_id, targets)
    state.stack.append(
        StackItem(
            source=card, controller_id=player_id, targets=targets,
            countered=countered, x_value=x_value, kicked=kicked,
            additional_cost_choice_id=additional_cost_choice_id,
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
    if p.spells_cast_this_turn == 2:
        _fire_second_spell_triggers(state, player_id)
    # Fire "whenever you play a land or cast a spell" triggers — both
    # events share a trigger type since The Endstone wants them both.
    _fire_cast_or_play_triggers(state, player_id)
    # Fire "whenever you cast an artifact spell" triggers when the
    # spell being cast is an artifact.
    if card.printing.is_artifact:
        _fire_cast_artifact_spell_triggers(state, player_id)


def _fire_second_spell_triggers(state: GameState, caster_id: int) -> None:
    """Push "whenever you cast your second spell each turn" triggers onto
    the stack for permanents the caster controls.
    """
    for obj in list(state.battlefield):
        if obj.controller_id != caster_id:
            continue
        for i, ability in enumerate(obj.printing.triggered_abilities):
            if ability.trigger != "second_spell_each_turn":
                continue
            push_triggered_ability(
                state,
                source=obj,
                ability=ability,
                ability_index=i,
                controller_id=caster_id,
                label="second-spell",
            )


def _fire_cast_artifact_spell_triggers(
    state: GameState, player_id: int
) -> None:
    """Push "whenever you cast an artifact spell" triggers onto the
    stack. Called from _cast_spell after the StackItem is pushed when
    the spell being cast is an artifact. Matches Pinnacle Emissary and
    similar EoE artifact-matters cards.
    """
    for obj in list(state.battlefield):
        if obj.controller_id != player_id:
            continue
        for i, ability in enumerate(obj.printing.triggered_abilities):
            if ability.trigger != "cast_artifact_spell":
                continue
            push_triggered_ability(
                state,
                source=obj,
                ability=ability,
                ability_index=i,
                controller_id=player_id,
                label="cast-artifact-spell",
            )


def _fire_cast_or_play_triggers(state: GameState, player_id: int) -> None:
    """Push "whenever you play a land or cast a spell" triggers onto the
    stack. Called from both _play_land (land event) and _cast_spell
    (spell event) so both paths fire it. Matches The Endstone.
    """
    for obj in list(state.battlefield):
        if obj.controller_id != player_id:
            continue
        for i, ability in enumerate(obj.printing.triggered_abilities):
            if ability.trigger != "cast_spell_or_play_land":
                continue
            push_triggered_ability(
                state,
                source=obj,
                ability=ability,
                ability_index=i,
                controller_id=player_id,
                label="cast-or-play",
            )


def _apply_ward_check(
    state: GameState, caster_id: int,
    targets: tuple[tuple[str, int], ...],
) -> bool:
    """Apply Ward at cast time. For each creature target controlled by an
    opponent with Ward {cost}, the caster auto-pays the cost by tapping
    additional lands. If they can't pay, the spell is countered and this
    returns True.

    Simplified: no pay-or-counter decision — caster always pays if they
    can. No player-choice surface; Ward is essentially an additional mana
    cost on top of the spell's printed cost.
    """
    for kind, tid in targets:
        if kind != "creature":
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
        ward = obj.printing.ward_cost
        if ward is None:
            continue
        if can_pay_cost(state, caster_id, ward):
            auto_tap_for_cost(state, caster_id, ward)
            state.log.append(
                f"P{caster_id} pays Ward {obj.printing.ward_cost_str} "
                f"for {obj.printing.name}"
            )
        else:
            state.log.append(
                f"Spell countered by {obj.printing.name}'s Ward "
                f"{obj.printing.ward_cost_str} (unpaid)"
            )
            return True
    return False


def _effective_ability_mana_cost(
    state: GameState, source: "GameObject", ability,
) -> ManaCost:
    """Return the mana portion of ``ability.cost`` after applying any
    ability-level cost reductions. Currently only The Dominion
    Bracelet's "costs {X} less, where X is this creature's power"
    (flag ``mana_reduced_by_source_power``). Clamps the generic
    portion at zero.
    """
    from mtg_bot.game import effective_power

    cost = ability.cost.mana
    if cost is None:
        return cost
    if ability.cost.mana_reduced_by_source_power:
        reduction = effective_power(state, source)
        if reduction > 0:
            cost = cost.reduced(reduction)
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
        # Eldrazi Temple's second mana ability lets the colorless
        # Eldrazi owner pay for activations on their Eldrazi.
        ability_spell_kind = "spell"
        if (
            "Eldrazi" in source.printing.subtypes
            and not source.printing.mana_cost.colored
        ):
            ability_spell_kind = "colorless_eldrazi_ability"
        auto_tap_for_cost(
            state, player_id, mana, spell_kind=ability_spell_kind,
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
            for _ in range(max_t):
                if not remaining:
                    break
                if p.agent is not None:
                    pick = p.agent.choose_target(
                        state, player_id, remaining,
                    )
                else:
                    pick = remaining[0]
                if pick is None or pick not in remaining:
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
    ):
        from mtg_bot.turn import sacrifice as _sacrifice

        p = state.player_by_id(player_id)
        if ability.cost.sacrifice_another_creature_or_artifact:
            def _is_valid_sac(o):
                return o.printing.is_creature or o.printing.is_artifact
        else:
            def _is_valid_sac(o):
                return o.printing.is_artifact or o.printing.is_land
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
        from mtg_bot.turn import sacrifice as _sacrifice

        p = state.player_by_id(player_id)
        options = [
            o for o in state.battlefield
            if o.controller_id == player_id
            and "Desert" in o.printing.subtypes
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

    added = effective_power(state, crew)
    tap_permanent(state, crew)
    spacecraft.charge_counters += added
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

    # Triggered-ability resolution
    if item.ability is not None:
        state.log.append(
            f"{item.source.printing.name}'s triggered ability resolves"
        )
        state.resolving_source = item.source
        state.resolving_x_value = item.x_value
        state.resolving_kicked = item.kicked
        state.resolving_additional_cost_choice_id = (
            item.additional_cost_choice_id
        )
        state.resolving_combat_damage_amount = item.combat_damage_amount
        state.resolving_counter_amount = item.counter_amount
        try:
            item.ability.effect.resolve(state, item.controller_id, item.targets)
        finally:
            state.resolving_source = None
            state.resolving_x_value = 0
            state.resolving_kicked = False
            state.resolving_additional_cost_choice_id = None
            state.resolving_combat_damage_amount = 0
            state.resolving_counter_amount = 0
        return

    # Spell resolution
    card = item.source
    state.resolving_x_value = item.x_value
    state.resolving_kicked = item.kicked
    state.resolving_additional_cost_choice_id = item.additional_cost_choice_id
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
            else:
                state.log.append(
                    f"{card.printing.name} resolves onto the battlefield"
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
    if obj.printing.is_artifact:
        _fire_artifact_enters_triggers(state, obj)
    if obj.printing.is_creature or obj.printing.is_artifact:
        _fire_creature_or_artifact_enters_triggers(state, obj)


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


def _fire_creature_or_artifact_enters_triggers(
    state: GameState, new_obj: "GameObject"
) -> None:
    """Push 'whenever another creature or artifact you control enters'
    triggers onto the stack for other permanents the controller controls.
    Excludes the entering object itself. Honors etb_trigger_multiplier
    (Panharmonicon-style) by pushing the trigger N times.
    """
    from mtg_bot.game import etb_trigger_multiplier

    controller = new_obj.controller_id
    firings = etb_trigger_multiplier(state, controller)
    for obj in list(state.battlefield):
        if obj.id == new_obj.id:
            continue
        if obj.controller_id != controller:
            continue
        for i, ability in enumerate(obj.printing.triggered_abilities):
            if ability.trigger != "creature_or_artifact_enters_you_control":
                continue
            for _ in range(firings):
                push_triggered_ability(
                    state,
                    source=obj,
                    ability=ability,
                    ability_index=i,
                    controller_id=controller,
                    label="creature-or-artifact-enters",
                )


def _fire_artifact_enters_triggers(
    state: GameState, new_artifact: "GameObject"
) -> None:
    """Push "whenever another artifact you control enters" triggers onto
    the stack. Also pushes "nontoken_artifact_enters_you_control"
    triggers when the entering artifact is not a token. Honors
    etb_trigger_multiplier by pushing N times.
    """
    from mtg_bot.game import etb_trigger_multiplier

    controller = new_artifact.controller_id
    firings = etb_trigger_multiplier(state, controller)
    is_nontoken = not new_artifact.printing.is_token
    for obj in list(state.battlefield):
        if obj.id == new_artifact.id:
            continue
        if obj.controller_id != controller:
            continue
        for i, ability in enumerate(obj.printing.triggered_abilities):
            if ability.trigger == "nontoken_artifact_enters_you_control":
                if not is_nontoken:
                    continue
            elif ability.trigger != "artifact_enters_you_control":
                continue
            for _ in range(firings):
                push_triggered_ability(
                    state,
                    source=obj,
                    ability=ability,
                    ability_index=i,
                    controller_id=controller,
                    label="artifact-enters",
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
            for _ in range(max_t):
                if not remaining:
                    break
                if controller.agent is None:  # pragma: no cover
                    break
                pick = controller.agent.choose_target(
                    state, controller_id, remaining
                )
                if pick is None or pick not in remaining:
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
            counter_amount=counter_amount,
        )
    )
    state.log.append(
        f"{source.printing.name}'s {label} trigger goes on the stack"
        + _format_log_targets(state, targets)
    )
    return True


def _trigger_etb_abilities(state: GameState, creature: "GameObject") -> None:
    """Push any ETB triggers from ``creature`` onto the stack, in printing order.

    If an ability requires a target, legal targets are gathered and the
    controller's agent picks one as the ability goes on the stack. If there
    are no legal targets, the ability fizzles (doesn't go on the stack at
    all), per the simplified Stage-3 targeting model.
    """
    from mtg_bot.game import etb_trigger_multiplier

    for ability_index, ability in enumerate(creature.printing.triggered_abilities):
        if ability.trigger != "etb":
            continue
        controller_id = creature.controller_id
        # Starfield Vocalist and similar permanents multiply ETB-caused
        # trigger firings. Each firing independently selects its target
        # set via the controller's agent.
        firings = etb_trigger_multiplier(state, controller_id)
        for _ in range(firings):
            push_triggered_ability(
                state,
                source=creature,
                ability=ability,
                ability_index=ability_index,
                controller_id=controller_id,
                label="ETB",
            )
