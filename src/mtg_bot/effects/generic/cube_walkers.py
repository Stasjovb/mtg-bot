"""Generic effect primitives introduced for the PowerLSV cube's
planeswalkers (Jace, Wielder of Mysteries; The Wandering Emperor;
Elspeth, Storm Slayer; Teferi, Time Raveler; Narset, Parter of Veils;
Minsc & Boo, Timeless Heroes).

Every class here is card-agnostic and parameterized by the pieces of
the printed shape that vary, so a future card with the same surface
claims through the same primitive. They live in one module (rather
than being spread across the per-cluster ``generic/*`` files) to keep
the cube campaign's parallel branches from colliding in the shared
cluster modules; each class notes the cluster it belongs to.

Parser entry points: :mod:`mtg_bot.cards.parser.effects_ext`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mtg_bot.effects.base import Effect, Target, _apply_damage
from mtg_bot.effects.conditions import Condition
from mtg_bot.effects.generic.targets_helpers import (
    _describe_targets,
    _fizzle_message,
    _slot_target_still_legal,
)
from mtg_bot.effects.object_predicates import ObjectPredicate

if TYPE_CHECKING:
    from mtg_bot.cards import CardPrinting
    from mtg_bot.game import GameObject, GameState


# ---------------------------------------------------------------------------
# Object predicates (object_predicates cluster)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HasManaValueAtLeast(ObjectPredicate):
    """"with mana value N or greater" — the object's printed mana value
    (``printing.mana_cost.total``; CR 202.3) is at least ``n``. Players
    have no mana value and evaluate False."""

    n: int

    def test(self, obj, state):
        if not hasattr(obj, "printing"):
            return False
        return obj.printing.mana_cost.total >= self.n


@dataclass(frozen=True)
class HasManaValueAtMost(ObjectPredicate):
    """"with mana value N or less" — mirror of
    :class:`HasManaValueAtLeast`."""

    n: int

    def test(self, obj, state):
        if not hasattr(obj, "printing"):
            return False
        return obj.printing.mana_cost.total <= self.n


@dataclass(frozen=True)
class IsPermanent(ObjectPredicate):
    """"target permanent" -- any battlefield object (players, which
    carry no printing, are rejected)."""

    def test(self, obj, state):
        return hasattr(obj, "printing")


@dataclass(frozen=True)
class HasPrintedCardType(ObjectPredicate):
    """The object's printed type line carries ``card_type`` (e.g.
    ``"Creature"``). Used for cards outside the battlefield (library /
    graveyard), where only printed characteristics exist -- "a
    noncreature, nonland card" composes as
    ``~HasPrintedCardType("Creature") & ~HasPrintedCardType("Land")``."""

    card_type: str

    def test(self, obj, state):
        printing = getattr(obj, "printing", None)
        return printing is not None and self.card_type in printing.card_types


# ---------------------------------------------------------------------------
# Conditions + conditional combinator (conditions / combinators cluster)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class YourLibraryHasNoCards(Condition):
    """"if your library has no cards in it" — the viewer's library is
    empty at evaluation time."""

    def matches(self, state, viewer_id, chosen_targets=None):
        return not state.player_by_id(viewer_id).library


@dataclass(frozen=True)
class IfCondition(Effect):
    """"If <condition>, <effect>." — run ``then`` only when
    ``condition.matches(state, controller_id)`` holds at resolve time.

    The positive twin of :class:`mtg_bot.effects.combinators.IfNot`.
    Targeting delegates to ``then``.
    """

    condition: Condition
    then: Effect

    def requires_target(self) -> bool:
        return self.then.requires_target()

    def legal_targets(
        self, state: "GameState", controller_id: int,
    ) -> list[Target]:
        return self.then.legal_targets(state, controller_id)

    def target_count_range(self) -> tuple[int, int]:
        return self.then.target_count_range()

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> bool | None:
        if not self.condition.matches(state, controller_id):
            state.log.append(
                f"P{controller_id} skips '{self.then.describe()}' "
                f"(if-condition not met)"
            )
            return False
        return self.then.resolve(state, controller_id, targets)

    def describe(self) -> str:
        return f"if {self.condition!r}, {self.then.describe()}"


# ---------------------------------------------------------------------------
# Game outcome (life / misc cluster)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WinTheGame(Effect):
    """"You win the game." (CR 104.2a) — every opponent of the
    controller loses. See :func:`mtg_bot.turn.win_the_game` for the
    empty-library-draw interaction."""

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import win_the_game

        source = state.resolving_source
        reason = source.printing.name if source is not None else "effect"
        win_the_game(state, controller_id, reason=reason)

    def describe(self) -> str:
        return "you win the game"


# ---------------------------------------------------------------------------
# Casting-permission grant (stack_control cluster)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MayCastSorceriesAsThoughFlashUntilYourNextTurn(Effect):
    """"Until your next turn, you may cast sorcery spells as though they
    had flash." (Teferi, Time Raveler's +1).

    Writes a ``cast_sorceries_as_flash`` continuous-effect registry
    entry (``params=(controller_id,)``) that expires at the
    controller's next untap step (``expires_at="controller_untap"``).
    The entry is a rules-modifying effect rather than a CR 613
    characteristic change, so it carries ``layer=0``; the entry
    survives its source leaving the battlefield (its lifetime is the
    printed duration). ``legal.legal_actions`` reads the registry and
    offers the covered player's sorceries at instant speed.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.legal import CAST_SORCERIES_AS_FLASH_KIND

        source = state.resolving_source
        source_id = source.id if source is not None else -1
        state.add_continuous_effect(
            source_id=source_id,
            layer=0,
            kind=CAST_SORCERIES_AS_FLASH_KIND,
            params=(controller_id,),
            expires_at="controller_untap",
            expires_at_player_id=controller_id,
            description=(
                f"P{controller_id} may cast sorceries as though they had "
                f"flash until their next turn"
            ),
        )
        state.log.append(
            f"P{controller_id} may cast sorcery spells as though they had "
            f"flash until their next turn"
        )

    def describe(self) -> str:
        return (
            "until your next turn, you may cast sorcery spells as though "
            "they had flash"
        )


# ---------------------------------------------------------------------------
# Counters (counters cluster)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PutPlusOneCountersOnTargetThenGrantKeywordsUEOT(Effect):
    """"Put N +1/+1 counter(s) on [up to one] target <filter>. It gains
    <keywords> until end of turn." — new-shape targeted counters with an
    anaphoric keyword grant on the same object (The Wandering Emperor's
    +1). ``granted_keywords`` may be empty (plain counters on a filtered
    / optional target, Minsc & Boo's +1).

    Target legality is re-verified at resolution (CR 608.2b); an
    illegal target gets neither counters nor keywords.
    """

    amount: int = 1
    targets: tuple = ()
    granted_keywords: frozenset = frozenset()

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        from mtg_bot.effects.combinators import ApplyEffect
        from mtg_bot.effects.durations import EndOfTurn
        from mtg_bot.effects.generic.grant_keywords import GrantKeywords
        from mtg_bot.game import add_plus_one_counters

        slot = self.targets[0]
        chosen = targets[0]
        prior = getattr(state, "resolving_controller_id", None)
        try:
            state.resolving_controller_id = controller_id
            legal = _slot_target_still_legal(state, slot, chosen)
        finally:
            state.resolving_controller_id = prior
        if not legal:
            state.log.append(
                _fizzle_message(state, chosen, action="counter placement")
            )
            return
        obj = next(
            (o for o in state.battlefield if o.id == chosen[1]), None,
        )
        if obj is None:  # pragma: no cover - legality check covers it
            return
        add_plus_one_counters(state, obj, self.amount)
        state.log.append(
            f"{obj.printing.name} gets {self.amount} +1/+1 counter(s) "
            f"(now {obj.plus_one_counters})"
        )
        if self.granted_keywords:
            ApplyEffect(
                inner=GrantKeywords(keywords=frozenset(self.granted_keywords)),
                ends_at=EndOfTurn(),
            ).resolve(state, controller_id, (chosen,))

    def describe(self) -> str:
        noun = "a +1/+1 counter" if self.amount == 1 else (
            f"{self.amount} +1/+1 counters"
        )
        out = f"put {noun} on {_describe_targets(self.targets)}"
        if self.granted_keywords:
            out += (
                f"; it gains {', '.join(sorted(self.granted_keywords))} "
                f"until end of turn"
            )
        return out


@dataclass(frozen=True)
class PutPlusOneCounterOnEachCreatureYouControlThenGrantKeywords(Effect):
    """"Put a +1/+1 counter on each creature you control. Those
    creatures gain <keywords> until <end of turn | your next turn>."
    (Elspeth, Storm Slayer's 0).

    "Those creatures" is the set that received counters — snapshotted
    at resolution, so a creature entering later is not covered.
    ``until_your_next_turn`` picks the grant's lifetime
    (``EndOfYourNextTurn`` vs ``EndOfTurn``).
    """

    amount: int = 1
    granted_keywords: frozenset = frozenset()
    until_your_next_turn: bool = False

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.effects.combinators import ApplyEffect
        from mtg_bot.effects.durations import EndOfTurn, EndOfYourNextTurn
        from mtg_bot.effects.generic.grant_keywords import GrantKeywords
        from mtg_bot.game import add_plus_one_counters, is_creature_now

        those = [
            o for o in state.battlefield
            if o.controller_id == controller_id and is_creature_now(o)
        ]
        duration = EndOfYourNextTurn() if self.until_your_next_turn else (
            EndOfTurn()
        )
        grant = ApplyEffect(
            inner=GrantKeywords(keywords=frozenset(self.granted_keywords)),
            ends_at=duration,
        )
        for obj in those:
            add_plus_one_counters(state, obj, self.amount)
            if self.granted_keywords:
                grant.resolve(state, controller_id, (("creature", obj.id),))
        state.log.append(
            f"P{controller_id} puts +1/+1 counter(s) on {len(those)} "
            f"creature(s)"
            + (
                f"; they gain {', '.join(sorted(self.granted_keywords))} "
                f"{duration.describe()}"
                if self.granted_keywords else ""
            )
        )

    def describe(self) -> str:
        dur = "your next turn" if self.until_your_next_turn else "end of turn"
        return (
            f"put a +1/+1 counter on each creature you control; those "
            f"creatures gain {', '.join(sorted(self.granted_keywords))} "
            f"until {dur}"
        )


# ---------------------------------------------------------------------------
# Library dig (library_lookat cluster)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LookTopNMayRevealMatchingToHandRestBottomRandom(Effect):
    """"Look at the top N cards of your library. You may reveal a
    <filter> card from among them and put it into your hand. Put the
    rest on the bottom of your library in a random order." (Narset,
    Parter of Veils' -2).

    ``card_filter`` is an :class:`ObjectPredicate` over the examined
    cards (their printed characteristics). The optional pick is two
    agent decisions: ``choose_yes_no`` (take one?) then
    ``choose_card_from_library`` among the matching cards. The chosen
    card is revealed to all players; the remainder go to the bottom in
    an order drawn from ``state.rng`` (CR 401.4 "random order").
    """

    n: int = 4
    card_filter: ObjectPredicate | None = None

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone, reveal_to_all

        p = state.player_by_id(controller_id)
        examined = list(p.library[:self.n])
        if not examined:
            return
        for c in examined:
            p.library.remove(c)
        matching = [
            c for c in examined
            if self.card_filter is None or self.card_filter.test(c, state)
        ]
        taken = None
        if matching and (
            p.agent is None
            or p.agent.choose_yes_no(
                state, controller_id,
                "Reveal a card from among them and put it into your hand?",
            )
        ):
            pick_id = None
            if p.agent is not None:
                pick_id = p.agent.choose_card_from_library(
                    state, controller_id, [c.id for c in matching],
                )
            taken = next(
                (c for c in matching if c.id == pick_id), matching[0],
            )
            taken.zone = Zone.HAND
            p.hand.append(taken)
            reveal_to_all(state, taken)
            state.log.append(
                f"P{controller_id} reveals {taken.printing.name} and puts "
                f"it into their hand (look at top {self.n})"
            )
        rest = [c for c in examined if c is not taken]
        state.rng.shuffle(rest)
        for c in rest:
            c.zone = Zone.LIBRARY
            p.library.append(c)
        if rest:
            state.log.append(
                f"P{controller_id} puts {len(rest)} card(s) on the bottom "
                f"of their library in a random order"
            )

    def describe(self) -> str:
        return (
            f"look at the top {self.n} cards of your library; you may "
            f"reveal a matching card and put it into your hand; put the "
            f"rest on the bottom in a random order"
        )


# ---------------------------------------------------------------------------
# Sacrifice + reflexive trigger (opponent_punishers / damage cluster)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SacrificeCreatureThenDamageEqualToItsPower(Effect):
    """"Sacrifice a creature. When you do, <source> deals X damage to
    any target, where X is that creature's power. If the sacrificed
    creature was a <subtype>, draw X cards." (Minsc & Boo, Timeless
    Heroes' -2).

    The sacrifice is mandatory; with no creature to sacrifice there is
    no reflexive trigger. X is the sacrificed creature's last-known
    power (CR 608.2h) and its last-known subtypes decide the draw rider
    (``draw_if_subtype``; empty string = no rider).

    Engine simplification (same precedent as Boilerbilges Ripper /
    Selfcraft Mechan, documented in docs/SEARCH_LIMITATIONS.md): the
    reflexive trigger's "any target" is chosen when the ability is
    activated and the damage + draw resolve inline instead of as a
    separate reflexive trigger on the stack.
    """

    draw_if_subtype: str = ""

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int,
    ) -> list[Target]:
        from mtg_bot.effects.targets import any_target_filter

        return self._enumerate_for_filter(
            state, controller_id, any_target_filter(),
        )

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> bool | None:
        from mtg_bot.game import (
            effective_power, effective_subtypes, is_creature_now,
        )
        from mtg_bot.turn import draw_n_cards, sacrifice as _sacrifice

        p = state.player_by_id(controller_id)
        candidates = [
            o for o in state.battlefield
            if o.controller_id == controller_id and is_creature_now(o)
        ]
        if not candidates:
            state.log.append(
                f"P{controller_id} has no creature to sacrifice"
            )
            return False
        chosen = candidates[0]
        if p.agent is not None:
            pick_id = p.agent.choose_sacrifice(
                state, controller_id, [o.id for o in candidates],
            )
            chosen = next(
                (o for o in candidates if o.id == pick_id), candidates[0],
            )
        x = max(0, effective_power(state, chosen))
        was_subtype = bool(self.draw_if_subtype) and (
            self.draw_if_subtype in effective_subtypes(state, chosen)
        )
        state.log.append(
            f"P{controller_id} sacrifices {chosen.printing.name} "
            f"(power {x})"
        )
        _sacrifice(state, chosen)
        if targets:
            target = targets[0]
            still_legal = target in self.legal_targets(state, controller_id)
            if still_legal and x > 0:
                _apply_damage(state, target, x)
            elif not still_legal:
                state.log.append(
                    _fizzle_message(state, target, action="damage")
                )
        if was_subtype and x > 0:
            draw_n_cards(state, controller_id, x)
        return True

    def describe(self) -> str:
        rider = (
            f"; if it was a {self.draw_if_subtype}, draw X cards"
            if self.draw_if_subtype else ""
        )
        return (
            "sacrifice a creature; when you do, deal X damage to any "
            f"target where X is its power{rider}"
        )


__all__ = [
    "HasManaValueAtLeast",
    "HasPrintedCardType",
    "IsPermanent",
    "HasManaValueAtMost",
    "IfCondition",
    "LookTopNMayRevealMatchingToHandRestBottomRandom",
    "MayCastSorceriesAsThoughFlashUntilYourNextTurn",
    "PutPlusOneCounterOnEachCreatureYouControlThenGrantKeywords",
    "PutPlusOneCountersOnTargetThenGrantKeywordsUEOT",
    "SacrificeCreatureThenDamageEqualToItsPower",
    "WinTheGame",
    "YourLibraryHasNoCards",
]
