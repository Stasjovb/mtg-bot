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
    """"Exile the top N cards of your library. You may play them this
    turn [without paying their mana costs]." (Golos, Tireless Pilgrim)
    — the exiled cards carry an :class:`ExilePlayPermission` for the
    controller (``free`` for the no-mana-cost form)."""

    count: int = 1
    free: bool = False
    duration: str = THIS_TURN

    def resolve(self, state, controller_id, targets=()):
        p = state.player_by_id(controller_id)
        exiled = []
        for _ in range(self.count):
            if not p.library:
                break
            card = p.library.pop(0)
            exile_card(state, card)
            grant_exile_play(
                state, card, controller_id,
                duration=self.duration, free=self.free,
            )
            exiled.append(card.printing.name)
        state.log.append(
            f"P{controller_id} exiles {', '.join(exiled) or 'nothing'} "
            f"(may play {'free ' if self.free else ''}{self.duration})"
        )

    def describe(self) -> str:
        return (
            f"exile the top {self.count} card(s) of your library; you may "
            f"play them this turn"
            + (" without paying their mana costs" if self.free else "")
        )
