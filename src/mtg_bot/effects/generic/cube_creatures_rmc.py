"""Engine pieces for the cube creatures bucket: red / multicolor /
colorless creatures (PowerLSV cube).

Everything here is card-agnostic: each class models one printed shape
(a cost atom, a permission, an effect) that the oracle-text grammar in
:mod:`mtg_bot.cards.parser.creature_rmc_grammar` composes. Sections:

* **Cost atoms** carried on ``ActivationCost.extra_costs`` —
  ``SacrificePermanentsCost`` ("Sacrifice a Forest", "Sacrifice an
  artifact", "Sacrifice five Treasures"), ``RemoveCountersFromSelfCost``
  ("Remove a +1/+1 counter from this creature"),
  ``TapUntappedPermanentsCost`` ("Tap an untapped Rebel you control"),
  ``ExileSelfFromGraveyardCost`` ("Exile this card from your
  graveyard"). Each exposes ``payable`` / ``pay`` / ``describe``.
* **Exile play permissions** — ``ExilePlayPermission`` rides
  ``GameObject.exile_play_permission`` and is honored by
  ``legal_actions`` / ``_cast_spell`` / ``_play_land`` for cards in ANY
  player's exile (Ragavan casts the opponent's card).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from mtg_bot.effects.base import Effect, Target

if TYPE_CHECKING:
    from mtg_bot.effects.object_predicates import ObjectPredicate
    from mtg_bot.game import GameObject, GameState


# ---------------------------------------------------------------------------
# Cost atoms (ActivationCost.extra_costs)
# ---------------------------------------------------------------------------


def _pick_ids(state, player_id: int, options: list, n: int, *, tap: bool = False):
    """Let ``player_id``'s agent pick ``n`` distinct objects out of
    ``options`` (one ``choose_sacrifice`` / ``choose_permanent_to_tap``
    call per pick; an out-of-range answer takes the first remaining)."""
    agent = state.player_by_id(player_id).agent
    remaining = list(options)
    chosen = []
    for _ in range(n):
        if not remaining:
            break
        pick_id = None
        if agent is not None:
            ids = [o.id for o in remaining]
            if tap:
                pick_id = agent.choose_permanent_to_tap(state, player_id, ids)
            else:
                pick_id = agent.choose_sacrifice(state, player_id, ids)
        obj = next((o for o in remaining if o.id == pick_id), remaining[0])
        remaining.remove(obj)
        chosen.append(obj)
    return chosen


@dataclass(frozen=True)
class SacrificePermanentsCost:
    """Sacrifice ``count`` permanents you control matching
    ``permanent_filter`` ("Sacrifice a Forest", "Sacrifice an artifact",
    "Sacrifice five Treasures"). ``another`` excludes the source."""

    permanent_filter: "ObjectPredicate"
    count: int = 1
    another: bool = False
    label: str = "a permanent"

    def candidates(self, state, player_id: int, source) -> list:
        return [
            o for o in state.battlefield
            if o.controller_id == player_id
            and not (self.another and source is not None and o.id == source.id)
            and self.permanent_filter.test(o, state)
        ]

    def payable(self, state, player_id: int, source) -> bool:
        return len(self.candidates(state, player_id, source)) >= self.count

    def pay(self, state, player_id: int, source) -> list:
        from mtg_bot.turn import sacrifice

        paid = _pick_ids(
            state, player_id, self.candidates(state, player_id, source),
            self.count,
        )
        for obj in paid:
            state.log.append(
                f"P{player_id} sacrifices {obj.printing.name} (cost)"
            )
            sacrifice(state, obj)
        return paid

    def describe(self) -> str:
        return f"Sacrifice {self.label}"


@dataclass(frozen=True)
class RemoveCountersFromSelfCost:
    """Remove ``count`` +1/+1 counters from the source (Walking
    Ballista)."""

    count: int = 1

    def payable(self, state, player_id: int, source) -> bool:
        return source is not None and source.plus_one_counters >= self.count

    def pay(self, state, player_id: int, source) -> list:
        source.plus_one_counters -= self.count
        state.log.append(
            f"P{player_id} removes {self.count} +1/+1 counter(s) from "
            f"{source.printing.name} (cost)"
        )
        return []

    def describe(self) -> str:
        noun = "a +1/+1 counter" if self.count == 1 else (
            f"{self.count} +1/+1 counters"
        )
        return f"Remove {noun} from ~"


@dataclass(frozen=True)
class TapUntappedPermanentsCost:
    """Tap ``count`` untapped permanents you control matching
    ``permanent_filter`` ("Tap an untapped Rebel you control"). Unlike
    ``{T}``, summoning sickness doesn't matter (CR 302.6 only restricts
    ``{T}`` / ``{Q}`` abilities of the creature itself)."""

    permanent_filter: "ObjectPredicate"
    count: int = 1
    label: str = "an untapped permanent you control"

    def candidates(self, state, player_id: int, source) -> list:
        return [
            o for o in state.battlefield
            if o.controller_id == player_id
            and not o.tapped
            and not (source is not None and o.id == source.id)
            and self.permanent_filter.test(o, state)
        ]

    def payable(self, state, player_id: int, source) -> bool:
        return len(self.candidates(state, player_id, source)) >= self.count

    def pay(self, state, player_id: int, source) -> list:
        from mtg_bot.turn import tap_permanent

        paid = _pick_ids(
            state, player_id, self.candidates(state, player_id, source),
            self.count, tap=True,
        )
        for obj in paid:
            state.log.append(f"P{player_id} taps {obj.printing.name} (cost)")
            tap_permanent(state, obj)
        return paid

    def describe(self) -> str:
        return f"Tap {self.label}"


@dataclass(frozen=True)
class ExileSelfFromGraveyardCost:
    """"Exile this card from your graveyard" — the cost atom of an
    ability that functions from the graveyard (Seasoned Pyromancer)."""

    def payable(self, state, player_id: int, source) -> bool:
        if source is None:
            return False
        return source in state.player_by_id(source.owner_id).graveyard

    def pay(self, state, player_id: int, source) -> list:
        from mtg_bot.game import Zone

        owner = state.player_by_id(source.owner_id)
        owner.graveyard.remove(source)
        source.zone = Zone.EXILE
        owner.exile.append(source)
        state.log.append(
            f"P{player_id} exiles {source.printing.name} from their "
            f"graveyard (cost)"
        )
        return [source]

    def describe(self) -> str:
        return "Exile this card from your graveyard"


def extra_costs_payable(state, player_id: int, source, cost) -> bool:
    """True when every ``cost.extra_costs`` atom can be paid."""
    return all(
        atom.payable(state, player_id, source) for atom in cost.extra_costs
    )


def pay_extra_costs(state, player_id: int, source, cost) -> list:
    """Pay every ``cost.extra_costs`` atom in printed order; returns the
    paid objects (for ``StackItem.cost_paid_objects``)."""
    paid: list = []
    for atom in cost.extra_costs:
        paid.extend(atom.pay(state, player_id, source))
    return paid


# ---------------------------------------------------------------------------
# Exile play permissions
# ---------------------------------------------------------------------------

# Permission lifetimes.
THIS_TURN = "this_turn"
UNTIL_YOUR_NEXT_END_STEP = "until_your_next_end_step"
UNTIL_END_OF_YOUR_NEXT_TURN = "until_end_of_your_next_turn"


@dataclass(frozen=True)
class ExilePlayPermission:
    """"You may play / cast that card <duration>" on a card sitting in
    exile (any player's exile zone).

    * ``player_id`` — who may play it.
    * ``duration`` — ``THIS_TURN`` (expires at this turn's cleanup),
      ``UNTIL_YOUR_NEXT_END_STEP`` (expires at the cleanup of the next
      turn of ``player_id``, this one included), or
      ``UNTIL_END_OF_YOUR_NEXT_TURN`` (expires at the cleanup of
      ``player_id``'s next turn after the granting one).
    * ``granted_turn`` / ``granted_player_turns`` — ``state.turn_number``
      and ``player_id``'s ``turns_started`` when granted.
    * ``free`` — "without paying its mana cost".
    * ``cast_only`` — "you may cast that card" (a land can't be played).
    * ``requires_attacked_with_subtype`` — "During any turn you attacked
      with a <Subtype>" (Robber of the Rich); never expires on its own.
    * ``any_color_mana`` — "you may spend mana as though it were mana of
      any color to cast that spell".
    """

    player_id: int
    duration: str = THIS_TURN
    granted_turn: int = 0
    granted_player_turns: int = 0
    free: bool = False
    cast_only: bool = False
    requires_attacked_with_subtype: str = ""
    any_color_mana: bool = False

    def expired_after_cleanup(self, state: "GameState") -> bool:
        """Whether this permission ends at the cleanup step that is
        running now (called from ``turn.run_cleanup_step``)."""
        if self.requires_attacked_with_subtype:
            return False
        if self.duration == THIS_TURN:
            return True
        active = state.active_player()
        if active.id != self.player_id:
            return False
        if self.duration == UNTIL_YOUR_NEXT_END_STEP:
            return True
        # UNTIL_END_OF_YOUR_NEXT_TURN: the granting turn itself (if it
        # was this player's) doesn't count.
        return active.turns_started > self.granted_player_turns

    def usable_now(self, state: "GameState", player_id: int) -> bool:
        if player_id != self.player_id:
            return False
        if self.requires_attacked_with_subtype:
            from mtg_bot.game import effective_subtypes

            p = state.player_by_id(player_id)
            return any(
                self.requires_attacked_with_subtype
                in effective_subtypes(state, o)
                for o in p.attacked_this_turn
            )
        return True


def grant_exile_play(
    state: "GameState", card: "GameObject", player_id: int, **kwargs,
) -> None:
    """Attach an :class:`ExilePlayPermission` for ``player_id`` to
    ``card`` (which must already sit in an exile zone)."""
    p = state.player_by_id(player_id)
    card.exile_play_permission = ExilePlayPermission(
        player_id=player_id,
        granted_turn=state.turn_number,
        granted_player_turns=p.turns_started,
        **kwargs,
    )


def exile_permission_cast_cost(card: "GameObject", perm: ExilePlayPermission):
    """The mana cost to cast ``card`` under ``perm``: nothing when free;
    every colored / hybrid / Phyrexian pip generic when "mana of any
    type" may pay (Robber of the Rich); else the printed cost."""
    from mtg_bot.cards.base import ManaCost

    cost = card.printing.mana_cost
    if perm.free:
        return ManaCost()
    if perm.any_color_mana:
        return ManaCost(
            generic=cost.generic + sum(n for _, n in cost.colored)
            + len(cost.hybrid) + len(cost.phyrexian),
            x_pips=cost.x_pips,
        )
    return cost


def exile_cards_playable_by(state: "GameState", player_id: int) -> list:
    """Cards in any exile zone whose permission lets ``player_id`` play
    them right now."""
    out = []
    for pl in state.players:
        for card in pl.exile:
            perm = card.exile_play_permission
            if perm is not None and perm.usable_now(state, player_id):
                out.append(card)
    return out


def find_permitted_exile_card(state: "GameState", player_id: int, card_id: int):
    """``(card, owner)`` for a permission-playable exile card, else
    ``(None, None)``."""
    for pl in state.players:
        for card in pl.exile:
            if card.id != card_id:
                continue
            perm = card.exile_play_permission
            if perm is not None and perm.usable_now(state, player_id):
                return card, pl
    return None, None


def expire_exile_play_permissions(state: "GameState") -> None:
    """Cleanup-step hook: drop every permission whose duration ends
    now. Forks the (copy-on-write) exile lists first — the per-card
    attribute write must not leak into sibling search states."""
    from mtg_bot.game import _CowList

    for pl in state.players:
        if not any(c.exile_play_permission is not None for c in pl.exile):
            continue
        if isinstance(pl.exile, _CowList):
            pl.exile.fork()
        for card in pl.exile:
            perm = card.exile_play_permission
            if perm is not None and perm.expired_after_cleanup(state):
                card.exile_play_permission = None


def exile_card(state: "GameState", card: "GameObject", *, face_down_for: int | None = None) -> None:
    """Move ``card`` (already removed from its previous zone list) into
    its owner's exile. ``face_down_for`` (a player id) keeps the card's
    identity known only to that player ("exile ... face down. You may
    look at ... that card")."""
    from mtg_bot.game import Zone, reveal_to, reveal_to_all

    card.zone = Zone.EXILE
    state.player_by_id(card.owner_id).exile.append(card)
    if face_down_for is None:
        reveal_to_all(state, card)
    else:
        card.publicly_known_to = frozenset()
        reveal_to(card, face_down_for)


# ---------------------------------------------------------------------------
# Static-ability helpers
# ---------------------------------------------------------------------------


def effective_ward_life_cost(state: "GameState", obj: "GameObject") -> int:
    """Total "Ward—Pay N life" on ``obj``: its printed ward plus every
    'have "Ward—Pay N life."' grant from a static that applies to it
    (Hexing Squelcher). Each instance is a separate ward trigger
    (CR 702.21d); the simplified ward model pays them together."""
    total = obj.printing.ward_life_cost
    for source in state.battlefield:
        for sa in source.printing.static_abilities:
            if sa.grants_ward_life_cost and sa.applies_to(source, obj, state):
                total += sa.grants_ward_life_cost
    return total


# ---------------------------------------------------------------------------
# Effects
# ---------------------------------------------------------------------------


def _live_source_in_graveyard(state: "GameState"):
    """The resolving ability's source if it still sits in its owner's
    graveyard (CR 400.7: a card that left and came back is a new
    object; this engine keeps ids, so zone membership is the check)."""
    src = state.resolving_source
    if src is None:
        return None
    owner = state.player_by_id(src.owner_id)
    return src if src in owner.graveyard else None


@dataclass(frozen=True)
class ReturnThisCardFromGraveyardToBattlefield(Effect):
    """"Return this card from your graveyard to the battlefield
    [tapped]." — the effect of an ability that functions from the
    graveyard (Otharri, Suns' Glory). No-op if the card has left the
    graveyard by the time the ability resolves."""

    tapped: bool = False
    functions_from_graveyard = True

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.actions import put_into_battlefield

        card = _live_source_in_graveyard(state)
        if card is None:
            return
        state.player_by_id(card.owner_id).graveyard.remove(card)
        state.log.append(
            f"{card.printing.name} returns from the graveyard to the "
            f"battlefield" + (" tapped" if self.tapped else "")
        )
        put_into_battlefield(state, card, controller_id)
        if self.tapped:
            card.tapped = True

    def describe(self) -> str:
        return (
            "return this card from your graveyard to the battlefield"
            + (" tapped" if self.tapped else "")
        )


@dataclass(frozen=True)
class ExileTopCardsWithPlayPermission(Effect):
    """"Exile the top N cards of <whose> library[ face down]. <You may
    play / cast that card <duration>>." — the impulse family (Golos,
    Ragavan, Laelia, Headliner Scarlett, Caves of Chaos Adventurer,
    Robber of the Rich). Each exiled card carries an
    :class:`ExilePlayPermission` for the controller.

    * ``whose`` — ``"you"`` (the controller's library),
      ``"that_player"`` (the player in the anaphoric ``targets`` tuple —
      the damaged player of a combat-damage trigger) or
      ``"defending_player"`` (the opponent, for attack triggers).
    * ``free`` / ``free_if`` — "without paying its mana cost" always, or
      only while ``free_if`` (a ``StatePredicate`` for the controller)
      holds at resolution ("If you've completed a dungeon, ...
      Otherwise, ...").
    * ``cast_only`` — "you may cast that card" (lands excluded).
    * ``face_down`` — only the controller learns the card.
    * ``requires_attacked_with_subtype`` / ``any_color_mana`` — Robber
      of the Rich's permission shape.
    """

    count: int = 1
    free: bool = False
    duration: str = THIS_TURN
    whose: str = "you"
    cast_only: bool = False
    face_down: bool = False
    free_if: object = None
    requires_attacked_with_subtype: str = ""
    any_color_mana: bool = False

    def _library_owner(self, state, controller_id, targets):
        if self.whose == "you":
            return controller_id
        if self.whose == "that_player":
            return next((tid for kind, tid in targets if kind == "player"), None)
        # defending player: the (single) opponent.
        return next(
            (pl.id for pl in state.players
             if pl.id != controller_id and not pl.has_lost),
            None,
        )

    def resolve(self, state, controller_id, targets=()):
        owner_id = self._library_owner(state, controller_id, targets)
        if owner_id is None:
            return
        p = state.player_by_id(owner_id)
        free = self.free or (
            self.free_if is not None and self.free_if.test(state, controller_id)
        )
        exiled = []
        for _ in range(self.count):
            if not p.library:
                break
            card = p.library.pop(0)
            exile_card(
                state, card,
                face_down_for=controller_id if self.face_down else None,
            )
            grant_exile_play(
                state, card, controller_id,
                duration=self.duration, free=free,
                cast_only=self.cast_only,
                requires_attacked_with_subtype=self.requires_attacked_with_subtype,
                any_color_mana=self.any_color_mana,
            )
            exiled.append("a card" if self.face_down else card.printing.name)
        verb = "cast" if self.cast_only else "play"
        state.log.append(
            f"P{controller_id} exiles {', '.join(exiled) or 'nothing'} from "
            f"P{owner_id}'s library (may {verb} "
            f"{'free ' if free else ''}{self.duration})"
        )

    def describe(self) -> str:
        return (
            f"exile the top {self.count} card(s) of your library; you may "
            f"play them this turn"
            + (" without paying their mana costs" if self.free else "")
        )


# ---------------------------------------------------------------------------
# Dash (CR 702.109)
# ---------------------------------------------------------------------------


def apply_dash_etb(state: "GameState", obj: "GameObject", controller_id: int) -> None:
    """A dashed permanent entering: it has haste for as long as it stays
    on the battlefield, and a delayed trigger returns it to its owner's
    hand at the beginning of the next end step (CR 702.109a)."""
    state.add_continuous_effect(
        source_id=obj.id, layer=6, kind="grant_keyword",
        target_id=obj.id, params=("haste",),
        description=f"{obj.printing.name}: dash (haste)",
    )
    state.delayed_triggers.append({
        "fire_at_turn": state.turn_number,
        "controller_id": controller_id,
        "source_id": obj.id,
        "effect": ReturnDashedPermanentToHand(etb_timestamp=obj.etb_timestamp),
        "any_player_end_step": True,
    })
    state.log.append(f"{obj.printing.name} was dashed (haste; returns at end step)")


@dataclass(frozen=True)
class ReturnDashedPermanentToHand(Effect):
    """Dash's delayed trigger: return the dashed permanent to its
    owner's hand — only if it's the same object that entered
    (``etb_timestamp`` match; CR 400.7)."""

    etb_timestamp: int = 0

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.turn import move_off_battlefield

        ref = state.resolving_source
        if ref is None:
            return
        obj = next((o for o in state.battlefield if o.id == ref.id), None)
        if obj is None or obj.etb_timestamp != self.etb_timestamp:
            return
        state.log.append(f"{obj.printing.name} returns to its owner's hand (dash)")
        move_off_battlefield(state, obj, destination="hand")

    def describe(self) -> str:
        return "return the dashed permanent to its owner's hand"


# ---------------------------------------------------------------------------
# Escape (CR 702.138c: "escaped")
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SacrificeSelfUnlessEscaped(Effect):
    """"When this creature enters, sacrifice it unless it escaped."
    (Phlage, Uro)."""

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.turn import sacrifice

        ref = state.resolving_source
        if ref is None:
            return
        obj = next((o for o in state.battlefield if o.id == ref.id), None)
        if obj is None or obj.escaped:
            return
        state.log.append(f"{obj.printing.name} is sacrificed (didn't escape)")
        sacrifice(state, obj)

    def describe(self) -> str:
        return "sacrifice it unless it escaped"


# ---------------------------------------------------------------------------
# "When you cast this spell" (cast triggers from the stack)
# ---------------------------------------------------------------------------

from mtg_bot.effects.predicates import TriggerPredicate as _TriggerPredicate  # noqa: E402


@dataclass(frozen=True)
class IsThisSpell(_TriggerPredicate):
    """IS_CAST subject ``spell`` IS the ability's own card — "When you
    cast this spell". Never true for a battlefield permanent observing
    some other spell; the cast pipeline stacks these abilities itself
    (:func:`fire_this_spell_cast_triggers`)."""

    def matches(self, state, subjects, source):
        return subjects.get("spell") is source


def _is_this_spell_ability(ability) -> bool:
    from mtg_bot.effects.predicates import And, Event

    if ability.event != Event.IS_CAST:
        return False
    pred = ability.predicate
    stack = [pred]
    while stack:
        p = stack.pop()
        if isinstance(p, IsThisSpell):
            return True
        if isinstance(p, And):
            stack.extend((p.left, p.right))
    return False


def fire_this_spell_cast_triggers(state: "GameState", card: "GameObject", controller_id: int) -> None:
    """Stack every "When you cast this spell" ability of ``card``, the
    spell just put on the stack (source = the spell)."""
    from mtg_bot.actions import push_triggered_ability

    caster = state.player_by_id(controller_id)
    subjects = {"spell": card, "controller": caster}
    for idx, ability in enumerate(card.printing.triggered_abilities):
        if not _is_this_spell_ability(ability):
            continue
        if not ability.matches_event(ability.event, subjects, card, state):
            continue
        push_triggered_ability(
            state, source=card, ability=ability, ability_index=idx,
            controller_id=controller_id, label="cast",
        )


def cast_card_from_exile_for_free(state: "GameState", player_id: int, card: "GameObject") -> bool:
    """Cast ``card`` (in some exile zone) without paying its mana cost
    in the middle of a resolving ability (cascade, CR 608.2g: timing is
    ignored). Returns False — leaving the card where it is — when the
    spell couldn't be cast (no legal targets / unpayable additional
    costs)."""
    from mtg_bot.actions import _cast_spell
    from mtg_bot.legal import _additional_costs_payable, _targets_are_satisfiable

    if card.printing.is_land:
        return False
    grant_exile_play(state, card, player_id, free=True, cast_only=True)
    if not (
        _targets_are_satisfiable(state, player_id, card)
        and _additional_costs_payable(state, player_id, card)
    ):
        card.exile_play_permission = None
        return False
    _cast_spell(state, player_id, card.id, cast_for_free=True)
    return True


@dataclass(frozen=True)
class Cascade(Effect):
    """Cascade (CR 702.85a): "When you cast this spell, exile cards from
    the top of your library until you exile a nonland card whose mana
    value is less than this spell's mana value. You may cast that card
    without paying its mana cost. Then put all cards exiled this way that
    weren't cast on the bottom of your library in a random order."

    The spell is the resolving ability's source (its printed mana value
    is read even if it has since left the stack)."""

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.game import Zone

        spell = state.resolving_source
        if spell is None:
            return
        threshold = spell.printing.mana_cost.total
        p = state.player_by_id(controller_id)
        exiled: list = []
        hit = None
        while p.library:
            card = p.library.pop(0)
            exile_card(state, card)
            exiled.append(card)
            if not card.printing.is_land and card.printing.mana_cost.total < threshold:
                hit = card
                break
        state.log.append(
            f"P{controller_id} cascades into "
            f"{hit.printing.name if hit else 'nothing'} "
            f"({len(exiled)} card(s) exiled)"
        )
        cast = False
        if hit is not None:
            agent = p.agent
            wants = agent is None or agent.choose_yes_no(
                state, controller_id,
                f"Cascade: cast {hit.printing.name} without paying its mana cost?",
            )
            if wants:
                cast = cast_card_from_exile_for_free(state, controller_id, hit)
        rest = [c for c in exiled if not (cast and c is hit)]
        state.rng.shuffle(rest)
        for c in rest:
            state.player_by_id(c.owner_id).exile.remove(c)
            c.exile_play_permission = None
            c.zone = Zone.LIBRARY
            p.library.append(c)

    def describe(self) -> str:
        return "cascade"


# ---------------------------------------------------------------------------
# More impulse variants
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CardTypeOrSubtypeFilter:
    """A card matching ANY of ``types`` (card types) or ``subtypes``
    ("Equipment, instant, or sorcery card"; "artifact or Dragon card").
    Same ``matches(printing)`` protocol as ``card_flow.CardFilter``."""

    types: tuple[str, ...] = ()
    subtypes: tuple[str, ...] = ()

    @property
    def has_quality(self) -> bool:
        return True

    def matches(self, printing) -> bool:
        return any(t in printing.card_types for t in self.types) or any(
            s in printing.subtypes for s in self.subtypes
        )

    def describe(self) -> str:
        return " or ".join((*self.types, *self.subtypes)) + " card"


@dataclass(frozen=True)
class ExileRandomGraveyardCardWithPlayPermission(Effect):
    """"Exile a card at random from your graveyard. You may play that
    card this turn." (Tersa Lightshatter)."""

    duration: str = THIS_TURN

    def resolve(self, state, controller_id, targets=()):
        p = state.player_by_id(controller_id)
        if not p.graveyard:
            return
        card = state.rng.choice(list(p.graveyard))
        p.graveyard.remove(card)
        exile_card(state, card)
        grant_exile_play(state, card, controller_id, duration=self.duration)
        state.log.append(
            f"P{controller_id} exiles {card.printing.name} at random from "
            f"their graveyard (may play {self.duration})"
        )

    def describe(self) -> str:
        return "exile a card at random from your graveyard; you may play it"


@dataclass(frozen=True)
class ExileTargetGraveyardCardWithPlayPermission(Effect):
    """"Exile target <card filter> card from your graveyard. <Until the
    end of your next turn>, you may play that card." (Thor, God of
    Thunder). ``card_filter`` is a ``CardFilter`` over printings."""

    card_filter: object = None
    duration: str = UNTIL_END_OF_YOUR_NEXT_TURN

    def requires_target(self) -> bool:
        return True

    def legal_targets(self, state, controller_id):
        p = state.player_by_id(controller_id)
        return [
            ("graveyard_card", c.id) for c in p.graveyard
            if self.card_filter is None or self.card_filter.matches(c.printing)
        ]

    def resolve(self, state, controller_id, targets=()):
        p = state.player_by_id(controller_id)
        for kind, tid in targets:
            if kind != "graveyard_card":
                continue
            card = next((c for c in p.graveyard if c.id == tid), None)
            if card is None:
                continue
            p.graveyard.remove(card)
            exile_card(state, card)
            grant_exile_play(state, card, controller_id, duration=self.duration)
            state.log.append(
                f"P{controller_id} exiles {card.printing.name} from their "
                f"graveyard (may play {self.duration})"
            )

    def describe(self) -> str:
        return "exile target card from your graveyard; you may play it"


# ---------------------------------------------------------------------------
# "can't block this turn"
# ---------------------------------------------------------------------------

_CANT_BLOCK = "cant_block"
_CREATURES_CANT_BLOCK = "creatures_cant_block"


def creature_cant_block(state: "GameState", obj: "GameObject") -> bool:
    """Whether a "can't block this turn" effect applies to ``obj``: a
    per-creature entry (``TargetCreatureCantBlockThisTurn``) or a
    player-wide one (``CreaturesCantBlockThisTurn`` — every creature the
    named player controls, including ones that arrive later this turn;
    ``params == (None,)`` means every player)."""
    for ce in state.continuous_effects:
        if ce.kind == _CANT_BLOCK and ce.target_id == obj.id:
            return True
        if ce.kind == _CREATURES_CANT_BLOCK and ce.params and (
            ce.params[0] is None or ce.params[0] == obj.controller_id
        ):
            return True
    return False


@dataclass(frozen=True)
class TargetCreatureCantBlockThisTurn(Effect):
    """"[Up to one ]target creature can't block this turn." """

    optional: bool = False
    targets: tuple = ()

    def __post_init__(self) -> None:
        from mtg_bot.effects.object_predicates import IsCreature
        from mtg_bot.effects.targets import TargetSpec

        object.__setattr__(self, "targets", (TargetSpec(
            IsCreature(), count_min=0 if self.optional else 1, count_max=1,
        ),))

    def resolve(self, state, controller_id, targets=()):
        for kind, tid in targets:
            if kind == "player":
                continue
            obj = next((o for o in state.battlefield if o.id == tid), None)
            if obj is None:
                continue
            src = state.resolving_source
            state.add_continuous_effect(
                source_id=src.id if src is not None else -1,
                layer=6, kind=_CANT_BLOCK, target_id=obj.id,
                expires_at="cleanup",
                description=f"{obj.printing.name} can't block this turn",
            )
            state.log.append(f"{obj.printing.name} can't block this turn")

    def describe(self) -> str:
        return ("up to one " if self.optional else "") + (
            "target creature can't block this turn"
        )


@dataclass(frozen=True)
class CreaturesCantBlockThisTurn(Effect):
    """"Creatures can't block this turn." / "Creatures target player
    controls can't block this turn." (``target_player``)."""

    target_player: bool = False

    def requires_target(self) -> bool:
        return self.target_player

    def target_count_range(self):
        return (1, 1) if self.target_player else (0, 0)

    def legal_targets(self, state, controller_id):
        if not self.target_player:
            return []
        return [("player", pl.id) for pl in state.players if not pl.has_lost]

    def resolve(self, state, controller_id, targets=()):
        pid = None
        if self.target_player:
            pid = next((tid for kind, tid in targets if kind == "player"), None)
            if pid is None:
                return
        src = state.resolving_source
        label = (
            "creatures can't block this turn" if pid is None
            else f"creatures P{pid} controls can't block this turn"
        )
        state.add_continuous_effect(
            source_id=src.id if src is not None else -1,
            layer=6, kind=_CREATURES_CANT_BLOCK, params=(pid,),
            expires_at="cleanup", description=label,
        )
        state.log.append(label)

    def describe(self) -> str:
        return (
            "creatures target player controls can't block this turn"
            if self.target_player else "creatures can't block this turn"
        )


# ---------------------------------------------------------------------------
# Conditions / formulas / formula damage
# ---------------------------------------------------------------------------

from mtg_bot.effects.conditions import Condition as _Condition  # noqa: E402
from mtg_bot.effects.formulas import Formula as _Formula  # noqa: E402


@dataclass(frozen=True)
class StateCondition(_Condition):
    """Adapter: a viewer-scoped ``StatePredicate`` as a ``Condition``
    ("if you're the monarch", "if you've completed a dungeon")."""

    predicate: object = None

    def matches(self, state, viewer_id, chosen_targets=None):
        return self.predicate.test(state, viewer_id)


@dataclass(frozen=True)
class ResolvingDamageAmount(_Formula):
    """"that much damage" — the damage amount carried by the resolving
    dealt-damage / combat-damage trigger."""

    def value(self, state, controller_id):
        return max(0, state.resolving_combat_damage_amount)


@dataclass(frozen=True)
class DealDamageByFormula(Effect):
    """"<source> deals damage equal to <formula> to <target>" — the
    unified ``DealDamage`` resolve with a runtime amount (Broadside
    Bombardiers: 2 plus the sacrificed permanent's mana value)."""

    amount: object = None
    targets: tuple = ()

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.effects.base import _apply_damage
        from mtg_bot.effects.generic.targets_helpers import (
            _fizzle_message,
            _slot_target_still_legal,
        )
        from mtg_bot.effects.targets import TargetSpec

        n = self.amount.value(state, controller_id)
        prior = getattr(state, "resolving_controller_id", None)
        try:
            state.resolving_controller_id = controller_id
            for slot, chosen in zip(self.targets, targets):
                if not isinstance(slot, TargetSpec):
                    continue
                if not _slot_target_still_legal(state, slot, chosen):
                    state.log.append(_fizzle_message(state, chosen))
                    continue
                if n > 0:
                    _apply_damage(state, chosen, n)
        finally:
            state.resolving_controller_id = prior

    def describe(self) -> str:
        return "deals damage equal to X to target"


# ---------------------------------------------------------------------------
# Event back-references, formulas and formula effects (batch 3)
# ---------------------------------------------------------------------------


def find_object_anywhere(state: "GameState", obj_id: int):
    """The object with ``obj_id`` on the battlefield, the stack or in any
    zone (last-known information for "that spell" / "that creature")."""
    for o in state.battlefield:
        if o.id == obj_id:
            return o
    for item in state.stack:
        if item.source.id == obj_id:
            return item.source
    for pl in state.players:
        for zone in (pl.graveyard, pl.exile, pl.hand, pl.library):
            for o in zone:
                if o.id == obj_id:
                    return o
    return None


@dataclass(frozen=True)
class EventSubjectManaValue(_Formula):
    """"that spell's mana value" — the triggering spell (the resolving
    ability's ``event_subject_id``)."""

    def value(self, state, controller_id):
        obj = find_object_anywhere(state, state.resolving_event_subject_id)
        return obj.printing.mana_cost.total if obj is not None else 0


@dataclass(frozen=True)
class EventSubjectPower(_Formula):
    """"its power" of the triggering creature ("that creature deals
    damage equal to its power"); its last known power if it left."""

    def value(self, state, controller_id):
        from mtg_bot.game import effective_power

        obj = find_object_anywhere(state, state.resolving_event_subject_id)
        if obj is None:
            return 0
        if obj in state.battlefield:
            return max(0, effective_power(state, obj))
        return max(0, (obj.printing.power or 0) + obj.plus_one_counters)


@dataclass(frozen=True)
class ExperienceCounters(_Formula):
    """"for each experience counter you have"."""

    def value(self, state, controller_id):
        return state.player_by_id(controller_id).experience_counters


@dataclass(frozen=True)
class CountPermanentsOfPlayer(_Formula):
    """Number of permanents matching ``predicate`` that ``whose``
    controls: ``"defending"`` = the (single) opponent of the controller
    ("the number of artifacts they control" in an attack trigger)."""

    predicate: object = None

    def value(self, state, controller_id):
        opp = next(
            (pl.id for pl in state.players if pl.id != controller_id), None,
        )
        return sum(
            1 for o in state.battlefield
            if o.controller_id == opp and self.predicate.test(o, state)
        )


@dataclass(frozen=True)
class DealDamageFromEvent(Effect):
    """Formula damage with an event back-reference: ``subject_slot`` names
    the dispatch subject the stack item remembers (``"spell"`` for
    "that spell's mana value", ``"obj"`` for "that creature ... its
    power"). ``targets`` is the chosen-target slot tuple (any target /
    any other target); ``to_defending_player`` instead hits the
    controller's opponent (no target). ``no_lifegain_if_player_hit``:
    "If a player is dealt damage this way, they can't gain life for
    the rest of the game." (Screaming Nemesis)."""

    amount: object = None
    targets: tuple = ()
    subject_slot: str = ""
    to_defending_player: bool = False
    no_lifegain_if_player_hit: bool = False

    def event_subject_id(self, subjects) -> int:
        if not self.subject_slot:
            return -1
        obj = subjects.get(self.subject_slot)
        return getattr(obj, "id", -1) if obj is not None else -1

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.effects.base import _apply_damage
        from mtg_bot.effects.generic.targets_helpers import (
            _fizzle_message,
            _slot_target_still_legal,
        )
        from mtg_bot.effects.targets import TargetSpec

        n = self.amount.value(state, controller_id)
        if self.to_defending_player:
            opp = next(
                (pl.id for pl in state.players if pl.id != controller_id), None,
            )
            if opp is not None and n > 0:
                _apply_damage(state, ("player", opp), n)
            return
        prior = getattr(state, "resolving_controller_id", None)
        try:
            state.resolving_controller_id = controller_id
            for slot, chosen in zip(self.targets, targets):
                if not isinstance(slot, TargetSpec):
                    continue
                if not _slot_target_still_legal(state, slot, chosen):
                    state.log.append(_fizzle_message(state, chosen))
                    continue
                if n <= 0:
                    continue
                _apply_damage(state, chosen, n)
                if self.no_lifegain_if_player_hit and chosen[0] == "player":
                    state.player_by_id(chosen[1]).cant_gain_life = True
                    state.log.append(
                        f"P{chosen[1]} can't gain life for the rest of the game"
                    )
        finally:
            state.resolving_controller_id = prior

    def describe(self) -> str:
        return "deals damage equal to X"


# ---------------------------------------------------------------------------
# Dynamic P/T formulas (lhurgoyf card-type count, domain)
# ---------------------------------------------------------------------------

_GRAVEYARD_CARD_TYPES = (
    "Artifact", "Battle", "Creature", "Enchantment", "Instant", "Kindred",
    "Land", "Planeswalker", "Sorcery", "Tribal",
)
_BASIC_TYPES = ("Plains", "Island", "Swamp", "Mountain", "Forest")


def rmc_dynamic_base_pt(state: "GameState", obj: "GameObject", formula: str):
    """``(power, toughness)`` for the bucket's ``dynamic_pt_formula``
    keys, or ``None``:

    * ``card_types_in_all_graveyards+K`` — P = card types among cards in
      all graveyards, T = P + K (Pyrogoyf, Barrowgoyf).
    * ``domain`` — P = T = basic land types among lands you control
      (Territorial Kavu).
    """
    if formula.startswith("card_types_in_all_graveyards+"):
        k = int(formula.rsplit("+", 1)[1])
        types: set[str] = set()
        for pl in state.players:
            for c in pl.graveyard:
                types.update(
                    t for t in c.printing.card_types if t in _GRAVEYARD_CARD_TYPES
                )
        n = len(types)
        return n, n + k
    if formula == "domain":
        from mtg_bot.game import effective_subtypes

        seen: set[str] = set()
        for o in state.battlefield:
            if o.controller_id != obj.controller_id or not o.printing.is_land:
                continue
            seen.update(
                s for s in effective_subtypes(state, o) if s in _BASIC_TYPES
            )
        n = len(seen)
        return n, n
    return None  # pragma: no cover - defensive fallback


# ---------------------------------------------------------------------------
# Hand / discard shapes
# ---------------------------------------------------------------------------


def _discard_chosen(state, player_id: int, n: int) -> list:
    """Discard ``n`` cards chosen by ``player_id`` (fewer if the hand
    runs out); returns the discarded cards."""
    from mtg_bot.game import Zone
    from mtg_bot.turn import fire_opponent_discards_triggers

    p = state.player_by_id(player_id)
    out = []
    for _ in range(n):
        if not p.hand:
            break
        ids = [c.id for c in p.hand]
        pick = p.agent.choose_discard(state, player_id, ids) if p.agent else ids[0]
        card = next((c for c in p.hand if c.id == pick), p.hand[0])
        p.hand.remove(card)
        card.zone = Zone.GRAVEYARD
        p.graveyard.append(card)
        state.log.append(f"P{player_id} discards {card.printing.name}")
        fire_opponent_discards_triggers(state, player_id, card=card)
        out.append(card)
    return out


@dataclass(frozen=True)
class DiscardYourHand(Effect):
    """"discard your hand"."""

    def resolve(self, state, controller_id, targets=()):
        p = state.player_by_id(controller_id)
        _discard_chosen(state, controller_id, len(p.hand))

    def describe(self) -> str:
        return "discard your hand"


@dataclass(frozen=True)
class DiscardThenDrawTokensPerNonland(Effect):
    """"discard N cards, then draw M cards. For each nonland card
    discarded this way, <create token>." (Seasoned Pyromancer)."""

    discard: int = 2
    draw: int = 2
    token_effect: object = None

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.turn import draw_n_cards

        discarded = _discard_chosen(state, controller_id, self.discard)
        draw_n_cards(state, controller_id, self.draw)
        nonland = sum(1 for c in discarded if not c.printing.is_land)
        for _ in range(nonland):
            self.token_effect.resolve(state, controller_id, ())

    def describe(self) -> str:
        return (
            f"discard {self.discard} cards, then draw {self.draw}; a token "
            f"per nonland card discarded"
        )


@dataclass(frozen=True)
class DiscardUpToNThenDrawThatMany(Effect):
    """"discard up to N cards, then draw that many cards" (Tersa
    Lightshatter). The count is the controller's ``choose_x``."""

    n: int = 2

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.turn import draw_n_cards

        p = state.player_by_id(controller_id)
        cap = min(self.n, len(p.hand))
        k = cap
        if p.agent is not None and cap > 0:
            k = max(0, min(cap, p.agent.choose_x(
                state, controller_id, "discard up to", cap,
            )))
        discarded = _discard_chosen(state, controller_id, k)
        if discarded:
            draw_n_cards(state, controller_id, len(discarded))

    def describe(self) -> str:
        return f"discard up to {self.n} cards, then draw that many"


# ---------------------------------------------------------------------------
# Counters / tokens / pumps
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GetExperienceCounter(Effect):
    """"you get an experience counter"."""

    def resolve(self, state, controller_id, targets=()):
        p = state.player_by_id(controller_id)
        p.experience_counters += 1
        state.log.append(
            f"P{controller_id} gets an experience counter "
            f"({p.experience_counters})"
        )

    def describe(self) -> str:
        return "you get an experience counter"


@dataclass(frozen=True)
class CreateTokenPerFormula(Effect):
    """"create <token> for each <formula unit>" — the wrapped
    ``CreateToken`` resolves with its count replaced by the formula."""

    token_effect: object = None
    amount: object = None

    def resolve(self, state, controller_id, targets=()):
        n = self.amount.value(state, controller_id)
        if n <= 0:
            return
        replace(self.token_effect, count=n).resolve(state, controller_id, ())

    def describe(self) -> str:
        return f"{self.token_effect.describe()} for each X"


@dataclass(frozen=True)
class TargetOpponentCreatesToken(Effect):
    """"target opponent creates <token>" — the token is created under
    the targeted opponent's control."""

    token_effect: object = None

    def requires_target(self) -> bool:
        return True

    def legal_targets(self, state, controller_id):
        return [
            ("player", pl.id) for pl in state.players
            if pl.id != controller_id and not pl.has_lost
        ]

    def resolve(self, state, controller_id, targets=()):
        pid = next((tid for kind, tid in targets if kind == "player"), None)
        if pid is None:
            return
        self.token_effect.resolve(state, pid, ())

    def describe(self) -> str:
        return f"target opponent {self.token_effect.describe()}"


@dataclass(frozen=True)
class MayDoThenReflexive(Effect):
    """"You may <first>. When you do, <then>." — a reflexive trigger
    (CR 603.12). ``then``'s targets are chosen with the enclosing
    ability (the Minsc & Boo precedent; see SEARCH_LIMITATIONS) and it
    resolves right after ``first`` when the controller chose to."""

    first: object = None
    then: object = None

    def requires_target(self) -> bool:
        return self.then.requires_target()

    def target_count_range(self):
        return self.then.target_count_range()

    def legal_targets(self, state, controller_id):
        return self.then.legal_targets(state, controller_id)

    def resolve(self, state, controller_id, targets=()):
        p = state.player_by_id(controller_id)
        if p.agent is not None and not p.agent.choose_yes_no(
            state, controller_id, f"You may {self.first.describe()}",
        ):
            return
        self.first.resolve(state, controller_id, ())
        self.then.resolve(state, controller_id, targets)

    def describe(self) -> str:
        return f"you may {self.first.describe()}; when you do, {self.then.describe()}"


@dataclass(frozen=True)
class PumpTargetCreatureByFormulaUEOT(Effect):
    """"Target creature gets <±X>/<±X> until end of turn, where X is
    <formula>." ``power_sign`` / ``toughness_sign`` are -1/0/+1."""

    amount: object = None
    power_sign: int = -1
    toughness_sign: int = -1
    targets: tuple = ()

    def __post_init__(self) -> None:
        from mtg_bot.effects.object_predicates import IsCreature
        from mtg_bot.effects.targets import TargetSpec

        object.__setattr__(self, "targets", (TargetSpec(IsCreature()),))

    def resolve(self, state, controller_id, targets=()):
        x = self.amount.value(state, controller_id)
        for kind, tid in targets:
            obj = next((o for o in state.battlefield if o.id == tid), None)
            if obj is None:
                continue
            src = state.resolving_source
            state.grant_pt_pump_ueot(
                source_id=src.id if src is not None else -1,
                target_id=obj.id,
                power=self.power_sign * x, toughness=self.toughness_sign * x,
                description=f"{obj.printing.name} gets X/X (X={x})",
            )

    def describe(self) -> str:
        return "target creature gets ±X/±X until end of turn"


from mtg_bot.effects.generic.exile import (  # noqa: E402
    ExileTargetCardFromGraveyard as _ExileTargetCardFromGraveyard,
)


class ExileUpToOneTargetCardFromGraveyard(_ExileTargetCardFromGraveyard):
    """"Exile up to one target card from a graveyard." — zero or one
    target. ``requires_target`` stays True so a ``ModalChooseOne``
    around it still surfaces the graveyard pool when the trigger is put
    on the stack (the modal combinator keys "targeted mode" on it); the
    ``(0, 1)`` count range lets the controller choose no target."""

    def target_count_range(self):
        return (0, 1)

    def describe(self) -> str:
        return "exile up to one target card from a graveyard"
