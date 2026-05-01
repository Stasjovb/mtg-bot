"""State-tier predicates: subject-independent boolean tests over the
``GameState``, viewed from a particular player's perspective.

This module is the second leaf-layer of the two-tier predicate stack
alongside :mod:`mtg_bot.effects.object_predicates`. A
``StatePredicate`` doesn't know about subject slots or source objects;
it just answers "does the game state satisfy this property right now,
viewed from ``viewer_id``'s perspective?"

The trigger-combinator layer in :mod:`mtg_bot.effects.predicates`
binds these atoms via ``StateBound(inner)`` (wraps a ``StatePredicate``
into a trigger predicate, evaluating with
``viewer_id = source.controller_id``).

Composition: ``&`` / ``|`` / ``~`` build state-level And/Or/Not
combinators. The resulting trees are themselves ``StatePredicate``s
and can be wrapped by ``StateBound`` exactly like the atoms.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mtg_bot.game import GameState


# Player ids are plain ints engine-side; alias for clarity at call
# sites and in documentation.
PlayerId = int


class StatePredicate(ABC):
    """A boolean over the ``GameState`` plus a viewer player id.

    Subclasses implement :meth:`test`. Combine with ``&`` / ``|`` /
    ``~``; the operators return ``StateAnd`` / ``StateOr`` /
    ``StateNot`` instances that recursively delegate.
    """

    @abstractmethod
    def test(self, state: "GameState", viewer_id: PlayerId) -> bool:
        ...

    def __and__(self, other: "StatePredicate") -> "StatePredicate":
        return StateAnd(self, other)

    def __or__(self, other: "StatePredicate") -> "StatePredicate":
        return StateOr(self, other)

    def __invert__(self) -> "StatePredicate":
        return StateNot(self)


@dataclass(frozen=True)
class StateAnd(StatePredicate):
    left: StatePredicate
    right: StatePredicate

    def test(self, state, viewer_id):
        return (
            self.left.test(state, viewer_id)
            and self.right.test(state, viewer_id)
        )


@dataclass(frozen=True)
class StateOr(StatePredicate):
    left: StatePredicate
    right: StatePredicate

    def test(self, state, viewer_id):
        return (
            self.left.test(state, viewer_id)
            or self.right.test(state, viewer_id)
        )


@dataclass(frozen=True)
class StateNot(StatePredicate):
    inner: StatePredicate

    def test(self, state, viewer_id):
        return not self.inner.test(state, viewer_id)


# ---------- atoms ----------


@dataclass(frozen=True)
class VoidActive(StatePredicate):
    """Void is active right now — i.e. a nonland permanent left the
    battlefield this turn or a spell was warped this turn. Viewer-
    independent (Void state is global, not per-player).

    Models the EoE "Void —" intervening-if gate that appears on
    triggered-ability lines like ``Void — Whenever <X>, if a nonland
    permanent left the battlefield this turn or a spell was warped this
    turn, <effect>.`` (Alpharael Stonechosen, Roving Actuator).
    """

    def test(self, state, viewer_id):
        from mtg_bot.game import is_void_active

        return is_void_active(state)


@dataclass(frozen=True)
class OpponentControlsMoreLandsThanYou(StatePredicate):
    """At least one opponent of ``viewer_id`` controls strictly more
    lands than ``viewer_id`` does.

    Models the "if an opponent controls more lands than you"
    intervening-if gate on Sunstar Expansionist's ETB. The static-side
    equivalent is ``ConditionalIfOpponentHasMoreLands`` (an effect
    combinator that gates resolution).
    """

    def test(self, state, viewer_id):
        my_lands = sum(
            1 for o in state.battlefield
            if o.controller_id == viewer_id and o.printing.is_land
        )
        for p in state.players:
            if p.id == viewer_id or getattr(p, "has_lost", False):
                continue
            count = sum(
                1 for o in state.battlefield
                if o.controller_id == p.id and o.printing.is_land
            )
            if count > my_lands:
                return True
        return False


# The Duskmourn "Delirium" mechanic counts distinct *card types* in the
# viewer's graveyard — Creature, Land, Sorcery, Instant, Enchantment,
# Artifact, Planeswalker, Battle, Tribal. The threshold is the printed
# "four or more" gate on every Delirium card. Supertypes (Legendary,
# Snow, Basic) and subtypes (Goblin, Forest, Equipment) don't count.
_DELIRIUM_CARD_TYPES: frozenset[str] = frozenset({
    "Creature",
    "Land",
    "Sorcery",
    "Instant",
    "Enchantment",
    "Artifact",
    "Planeswalker",
    "Battle",
    "Tribal",
})


@dataclass(frozen=True)
class Delirium(StatePredicate):
    """The viewer has at least four distinct card types among cards in
    their graveyard.

    Models the Duskmourn "Delirium" mechanic — every card that prints a
    ``Delirium —`` ability word or the ``if there are four or more
    card types among cards in your graveyard`` intervening-if gate
    delegates to this predicate. The card-type set is fixed by the
    comprehensive rules' card-type taxonomy (CR 205.2a).
    """

    def test(self, state, viewer_id):
        try:
            player = state.player_by_id(viewer_id)
        except (KeyError, AttributeError):
            return False
        seen: set[str] = set()
        for card in player.graveyard:
            for t in card.printing.card_types:
                if t in _DELIRIUM_CARD_TYPES:
                    seen.add(t)
                    if len(seen) >= 4:
                        return True
        return False


@dataclass(frozen=True)
class SpellsCastThisTurn(StatePredicate):
    """The viewer has cast exactly ``n`` spells this turn (counted via
    ``Player.spells_cast_this_turn``).

    Models the "second spell each turn" trigger family (Illvoi
    Operative, Sunstar Lightsmith, Cosmogrand Zenith, Station Monitor):
    paired with ``Subject("controller", IsControllerYou)`` (or the
    pre-existing ``Controlled(YOU, "controller")`` trigger gate at the
    trigger-combinator layer), this latches the moment the source's
    own controller's running total flips to ``n``. The predicate reads
    the count post-increment of ``spells_cast_this_turn`` since the
    dispatcher fires AFTER ``actions._cast_spell`` has bumped the
    counter.
    """

    n: int

    def test(self, state, viewer_id):
        try:
            player = state.player_by_id(viewer_id)
        except (KeyError, AttributeError):
            return False
        return getattr(player, "spells_cast_this_turn", 0) == self.n


@dataclass(frozen=True)
class LoneAttackerForYou(StatePredicate):
    """Exactly one creature is currently attacking AND that lone
    attacker is controlled by ``viewer_id``.

    Models the "Whenever a creature you control attacks alone, ..."
    trigger qualifier (Widow's Walk on Derelict Attic // Widow's Walk).
    Pairs with the once-per-pass ``Event.YOU_ATTACK`` event so the
    predicate is evaluated AFTER every attacker for the active
    declare-attackers pass has flipped to ``attacking=True`` —
    distinct from the per-attacker ``Event.ATTACKS`` event whose
    dispatch fires inside the per-attacker loop.
    """

    def test(self, state, viewer_id):
        attackers = [o for o in state.battlefield if o.attacking]
        if len(attackers) != 1:
            return False
        return attackers[0].controller_id == viewer_id


@dataclass(frozen=True)
class AnyPlayerControlsNoCreatures(StatePredicate):
    """At least one (non-eliminated) player controls zero creatures on
    the battlefield.

    Viewer-independent: the predicate walks every active player and
    returns True the moment one of them owns no battlefield creatures.
    Any creature on the battlefield (printed creature, animated land,
    stationed Spacecraft) counts via ``printing.is_creature``; the
    legacy bespoke effect used the same surface check, so we mirror
    that scope here.

    Models the intervening-if gate "if a player controls no creatures"
    on Sothera, the Supervoid's end-step trigger. The trigger fires only
    when, at the beginning of the controller's end step, at least one
    player has been wiped of creatures — the gate is the printed
    "give up your last creature, get one back" pivot.
    """

    def test(self, state, viewer_id):
        for p in state.players:
            if getattr(p, "has_lost", False):
                continue
            has_creature = any(
                o.controller_id == p.id and o.printing.is_creature
                for o in state.battlefield
            )
            if not has_creature:
                return True
        return False
