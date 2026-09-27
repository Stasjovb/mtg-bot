"""Card-flow effects: targeted draw, tutors, hand disruption, library
look-and-select, wheels, and mass zone moves.

Generic primitives introduced for the PowerLSV cube's "spells B" bucket
(Ancestral Recall, Demonic Tutor, Thoughtseize, Brainstorm, Stock Up,
Timetwister, Wheel of Fortune, Upheaval, ...). Every effect here is
parameterized by a small :class:`CardFilter` (printed characteristics of
a card in a hidden zone or graveyard) and / or a
:class:`mtg_bot.effects.formulas.Formula` amount, so one class covers a
whole printed shape rather than one card.

Decision hooks reuse the existing agent protocol (no new hook):

* tutor / look-at-top picks -> ``choose_card_from_library``
* caster's pick from a revealed hand -> ``choose_card_from_opponent_hand``
* "put a card from your hand on top" (Brainstorm) -> ``choose_discard``
  (the same "which hand card do I give up" decision surface)
* optional riders -> ``choose_yes_no``

Copy-on-write discipline (see ``game._CowList``): every site that moves a
card out of a library / graveyard / exile list removes it from the list
(a list mutator, which forks the share group) BEFORE mutating the card
object, so sibling search states never observe the mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Union

from mtg_bot.effects.base import Effect, Target

if TYPE_CHECKING:
    from mtg_bot.cards.base import CardPrinting
    from mtg_bot.effects.formulas import Formula
    from mtg_bot.game import GameObject, GameState, Player


Amount = Union[int, "Formula"]


def _amount(amount: Amount, state: "GameState", controller_id: int) -> int:
    """Evaluate an ``int`` or ``Formula`` amount at resolve time."""
    if isinstance(amount, int):
        return max(0, amount)
    return max(0, amount.value(state, controller_id))


def _describe_amount(amount: Amount) -> str:
    return str(amount) if isinstance(amount, int) else "X"


# ---------------------------------------------------------------------
# CardFilter — printed-characteristics filter for non-battlefield cards
# ---------------------------------------------------------------------


_PSEUDO_TYPE_PERMANENT = "Permanent"


@dataclass(frozen=True)
class CardFilter:
    """Filter over a card's printed characteristics.

    Used for cards in libraries, hands and graveyards, where the
    battlefield-oriented ``ObjectPredicate`` atoms (which read layered
    state such as ``is_creature_now``) don't apply.

    * ``any_types`` — the card must have at least one of these card
      types. ``"Permanent"`` is a pseudo-type matching any permanent
      card (``CardPrinting.is_permanent``). Empty = no type restriction.
    * ``excluded_types`` — the card must have none of these card types
      ("noncreature, nonland card").
    * ``max_mv`` — mana value at most N ("with mana value 3 or less").
    * ``color`` — the card must be this color ("a green creature card").
    * ``supertype`` — e.g. ``"Legendary"``.
    """

    any_types: tuple[str, ...] = ()
    excluded_types: tuple[str, ...] = ()
    max_mv: "int | None" = None
    color: "str | None" = None
    supertype: "str | None" = None

    @property
    def has_quality(self) -> bool:
        """CR 701.19b: a search for a card with a stated quality may
        fail to find; a search for just "a card" may not (unless the
        library is empty)."""
        return bool(
            self.any_types or self.excluded_types
            or self.max_mv is not None or self.color is not None
            or self.supertype is not None
        )

    def matches(self, printing: "CardPrinting") -> bool:
        if self.any_types:
            ok = False
            for t in self.any_types:
                if t == _PSEUDO_TYPE_PERMANENT:
                    if printing.is_permanent:
                        ok = True
                        break
                elif t in printing.card_types:
                    ok = True
                    break
            if not ok:
                return False
        for t in self.excluded_types:
            if t in printing.card_types:
                return False
        if self.max_mv is not None and printing.mana_cost.total > self.max_mv:
            return False
        if self.color is not None and self.color not in printing.mana_cost.colors:
            return False
        if self.supertype is not None and self.supertype not in printing.supertypes:
            return False
        return True

    def describe(self) -> str:
        words: list[str] = []
        if self.supertype:
            words.append(self.supertype.lower())
        if self.color:
            words.append({
                "W": "white", "U": "blue", "B": "black",
                "R": "red", "G": "green",
            }.get(self.color, self.color))
        for t in self.excluded_types:
            words.append(f"non{t.lower()}")
        if self.any_types:
            words.append(" or ".join(t.lower() for t in self.any_types))
        words.append("card")
        text = " ".join(words)
        if self.max_mv is not None:
            text += f" with mana value {self.max_mv} or less"
        return text


ANY_CARD = CardFilter()


# ---------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------


def _player_targets(
    state: "GameState", controller_id: int, opponent_only: bool,
) -> list[Target]:
    return [
        ("player", p.id) for p in state.players
        if not p.has_lost and not (opponent_only and p.id == controller_id)
    ]


def _target_player(
    state: "GameState", targets: tuple[Target, ...],
) -> "Player | None":
    """Resolve the first ``("player", id)`` target, or ``None`` when the
    spell has no (still-legal) player target."""
    if not targets:
        return None
    kind, pid = targets[0]
    if kind != "player":
        return None
    p = state.player_by_id(pid)
    if p.has_lost:
        return None
    return p


def discard_card(state: "GameState", player: "Player", card: "GameObject") -> None:
    """Move ``card`` from ``player``'s hand to their graveyard as a
    discard and fire the ``DISCARDS_CARD`` observers."""
    from mtg_bot.game import Zone
    from mtg_bot.turn import fire_opponent_discards_triggers

    player.hand.remove(card)
    card.zone = Zone.GRAVEYARD
    player.graveyard.append(card)
    state.log.append(f"P{player.id} discards {card.printing.name}")
    fire_opponent_discards_triggers(state, player.id)


def _agent_pick(options: list, picked_id) -> "GameObject | None":
    return next((c for c in options if c.id == picked_id), None)


# ---------------------------------------------------------------------
# Targeted draw / extra turn
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class TargetPlayerDraws(Effect):
    """"Target player draws N cards." (Ancestral Recall.)"""

    amount: Amount = 1

    def requires_target(self) -> bool:
        return True

    def legal_targets(self, state, controller_id):
        return _player_targets(state, controller_id, opponent_only=False)

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.turn import draw_n_cards

        p = _target_player(state, targets)
        if p is None:
            return
        drawn = draw_n_cards(state, p.id, _amount(self.amount, state, controller_id))
        state.log.append(f"P{p.id} draws {drawn} card(s)")

    def describe(self) -> str:
        return f"target player draws {_describe_amount(self.amount)} card(s)"


@dataclass(frozen=True)
class TargetPlayerTakesExtraTurn(Effect):
    """"Target player takes an extra turn after this one." (Time Warp.)

    Queues the target on ``state.extra_turn_queue`` — the same queue
    ``TakeExtraTurnAfterThisOne`` (Nexus of Fate) feeds.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(self, state, controller_id):
        return _player_targets(state, controller_id, opponent_only=False)

    def resolve(self, state, controller_id, targets=()):
        p = _target_player(state, targets)
        if p is None:
            return
        state.extra_turn_queue.append(p.id)
        state.log.append(f"P{p.id} is scheduled to take an extra turn")

    def describe(self) -> str:
        return "target player takes an extra turn after this one"


# ---------------------------------------------------------------------
# Hand disruption
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class TargetPlayerDiscardsAtRandom(Effect):
    """"Target player discards N cards at random." (Hymn to Tourach;
    Mind Twist with ``amount=ResolvingX()``.) Random picks draw from
    ``state.rng`` so the result is reproducible under a seeded game."""

    amount: Amount = 1

    def requires_target(self) -> bool:
        return True

    def legal_targets(self, state, controller_id):
        return _player_targets(state, controller_id, opponent_only=False)

    def resolve(self, state, controller_id, targets=()):
        p = _target_player(state, targets)
        if p is None:
            return
        n = _amount(self.amount, state, controller_id)
        for _ in range(n):
            if not p.hand:
                break
            card = p.hand[state.rng.randrange(len(p.hand))]
            discard_card(state, p, card)

    def describe(self) -> str:
        return (
            f"target player discards {_describe_amount(self.amount)} "
            f"card(s) at random"
        )


@dataclass(frozen=True)
class TargetPlayerRevealsHandYouChooseDiscard(Effect):
    """"Target player reveals their hand. You choose a <filter> card from
    it. That player discards that card." (Thoughtseize, Inquisition of
    Kozilek, Duress.)

    ``opponent_only`` is True for the "Target opponent" wording (Duress).
    Every card in the revealed hand becomes known to the caster
    (``reveal_to``). The caster's pick goes through
    ``choose_card_from_opponent_hand`` (exposed to search).
    """

    card_filter: CardFilter = ANY_CARD
    opponent_only: bool = False

    def requires_target(self) -> bool:
        return True

    def legal_targets(self, state, controller_id):
        return _player_targets(state, controller_id, self.opponent_only)

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.game import reveal_to

        p = _target_player(state, targets)
        if p is None:
            return
        for c in p.hand:
            reveal_to(c, controller_id)
        options = [c for c in p.hand if self.card_filter.matches(c.printing)]
        if not options:
            state.log.append(
                f"P{p.id} reveals a hand with no "
                f"{self.card_filter.describe()}"
            )
            return
        caster = state.player_by_id(controller_id)
        chosen = options[0]
        if caster.agent is not None:
            picked = caster.agent.choose_card_from_opponent_hand(
                state, controller_id, [c.id for c in options],
            )
            chosen = _agent_pick(options, picked) or options[0]
        discard_card(state, p, chosen)

    def describe(self) -> str:
        who = "opponent" if self.opponent_only else "player"
        return (
            f"target {who} reveals their hand; you choose a "
            f"{self.card_filter.describe()} from it; that player discards it"
        )


@dataclass(frozen=True)
class EachPlayerDiscardsHand(Effect):
    """"Each player discards their hand" (Wheel of Fortune's first half)."""

    def resolve(self, state, controller_id, targets=()):
        for i in range(len(state.players)):
            p = state.players[(state.active_player_idx + i) % len(state.players)]
            if p.has_lost:
                continue
            for card in list(p.hand):
                discard_card(state, p, card)

    def describe(self) -> str:
        return "each player discards their hand"


@dataclass(frozen=True)
class PutCardsFromHandOnTopOfLibrary(Effect):
    """"Put N cards from your hand on top of your library in any order."
    (Brainstorm's second half.)

    Each pick goes through the controller's ``choose_discard`` hook (the
    "which hand card do I give up" decision); every picked card is put
    on top in turn, so the LAST pick ends on top. The cards stay known
    to their owner (``reveal_to``).
    """

    amount: int = 1

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.game import Zone, reveal_to

        p = state.player_by_id(controller_id)
        moved = 0
        for _ in range(self.amount):
            if not p.hand:
                break
            chosen = p.hand[0]
            if p.agent is not None:
                picked = p.agent.choose_discard(
                    state, controller_id, [c.id for c in p.hand],
                )
                chosen = _agent_pick(p.hand, picked) or p.hand[0]
            p.hand.remove(chosen)
            chosen.zone = Zone.LIBRARY
            p.library.insert(0, chosen)
            reveal_to(chosen, controller_id)
            moved += 1
        state.log.append(
            f"P{controller_id} puts {moved} card(s) from hand on top of "
            f"their library"
        )

    def describe(self) -> str:
        return (
            f"put {self.amount} card(s) from your hand on top of your "
            f"library in any order"
        )


# ---------------------------------------------------------------------
# Library search (tutors)
# ---------------------------------------------------------------------


SEARCH_DESTINATIONS = ("hand", "graveyard", "top", "battlefield")


@dataclass(frozen=True)
class SearchLibrary(Effect):
    """Search your library for a ``card_filter`` card and put it into
    ``destination``, then shuffle.

    ``destination``:
      * ``"hand"`` — Demonic Tutor.
      * ``"graveyard"`` — Entomb.
      * ``"top"`` — "then shuffle and put that card on top" (Vampiric
        Tutor, Mystical Tutor); the shuffle happens BEFORE the card is
        placed on top.
      * ``"battlefield"`` — Tinker / Natural Order / Crop Rotation;
        enters through ``put_into_battlefield`` so ETBs fire.

    ``reveal`` marks the found card as known to every player; otherwise
    the controller alone knows it (relevant for the top-of-library
    destination). Per CR 701.19b a search for a card with a stated
    quality may fail (the agent may return ``None``); a search for just
    "a card" finds one whenever the library is non-empty.
    """

    card_filter: CardFilter = ANY_CARD
    destination: str = "hand"
    reveal: bool = False

    def __post_init__(self) -> None:
        if self.destination not in SEARCH_DESTINATIONS:
            raise ValueError(
                f"SearchLibrary destination must be one of "
                f"{SEARCH_DESTINATIONS}, got {self.destination!r}"
            )

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.actions import put_into_battlefield
        from mtg_bot.game import Zone, reveal_to, reveal_to_all, shuffle_library

        p = state.player_by_id(controller_id)
        options = [c for c in p.library if self.card_filter.matches(c.printing)]
        chosen = None
        if options:
            picked = None
            if p.agent is not None:
                picked = p.agent.choose_card_from_library(
                    state, controller_id, [c.id for c in options],
                )
            chosen = _agent_pick(options, picked)
            if chosen is None and not self.card_filter.has_quality:
                chosen = options[0]
        if chosen is None:
            state.log.append(
                f"P{controller_id} searches for a "
                f"{self.card_filter.describe()} and finds nothing"
            )
            shuffle_library(state, controller_id)
            return
        p.library.remove(chosen)
        if self.reveal:
            reveal_to_all(state, chosen)
        dest = self.destination
        if dest == "top":
            shuffle_library(state, controller_id)
            chosen.zone = Zone.LIBRARY
            p.library.insert(0, chosen)
            if self.reveal:
                reveal_to_all(state, chosen)
            else:
                reveal_to(chosen, controller_id)
            state.log.append(
                f"P{controller_id} tutors a card to the top of their library"
                + (f" ({chosen.printing.name})" if self.reveal else "")
            )
            return
        if dest == "hand":
            chosen.zone = Zone.HAND
            p.hand.append(chosen)
            reveal_to(chosen, controller_id)
            state.log.append(f"P{controller_id} tutors a card into hand")
        elif dest == "graveyard":
            chosen.zone = Zone.GRAVEYARD
            p.graveyard.append(chosen)
            reveal_to_all(state, chosen)
            state.log.append(
                f"P{controller_id} puts {chosen.printing.name} into their "
                f"graveyard"
            )
        else:  # battlefield
            state.log.append(
                f"P{controller_id} puts {chosen.printing.name} onto the "
                f"battlefield"
            )
            put_into_battlefield(state, chosen, controller_id)
        shuffle_library(state, controller_id)

    def describe(self) -> str:
        where = {
            "hand": "put it into your hand",
            "graveyard": "put it into your graveyard",
            "top": "then shuffle and put it on top",
            "battlefield": "put it onto the battlefield",
        }[self.destination]
        return f"search your library for a {self.card_filter.describe()}, {where}"


# ---------------------------------------------------------------------
# Look at the top N and select
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class LookAtTopCardsPutIntoHand(Effect):
    """Look at (or reveal) the top ``count`` cards of your library, put
    ``take`` of them matching ``take_filter`` into your hand, and move
    the rest to ``rest_zone``.

    Covers:
      * Stock Up / Dig Through Time — look at top 5/7, put two into
        hand, rest on the bottom in any order.
      * Pillage the Bog — top X (a ``Formula``), one into hand, rest on
        the bottom in a random order.
      * Once Upon a Time — top five, you MAY reveal a creature or land
        card and put it into your hand, rest on the bottom in a random
        order.
      * Malevolent Rumble — reveal the top four, you MAY put a permanent
        card into your hand, rest into your graveyard.

    ``optional`` (the printed "you may") lets the agent decline a pick
    (``choose_card_from_library`` returning ``None``). A mandatory pick
    falls back to the first eligible card when the agent declines.
    ``rest_random`` shuffles the leftovers before bottoming ("in a
    random order"); otherwise they keep their library order ("in any
    order" — the ordering choice is not modeled, see
    ``docs/SEARCH_LIMITATIONS.md``).
    """

    count: Amount = 1
    take: int = 1
    take_filter: CardFilter = ANY_CARD
    optional: bool = False
    reveal: bool = False
    reveal_taken: bool = False
    rest_zone: str = "bottom"
    rest_random: bool = False

    def __post_init__(self) -> None:
        if self.rest_zone not in ("bottom", "graveyard"):
            raise ValueError(
                f"rest_zone must be 'bottom' or 'graveyard', got "
                f"{self.rest_zone!r}"
            )

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.game import Zone, reveal_to, reveal_to_all

        p = state.player_by_id(controller_id)
        n = min(_amount(self.count, state, controller_id), len(p.library))
        looked = [p.library.pop(0) for _ in range(n)]
        for c in looked:
            if self.reveal:
                reveal_to_all(state, c)
            else:
                reveal_to(c, controller_id)
        taken: list = []
        for _ in range(self.take):
            options = [
                c for c in looked
                if c not in taken and self.take_filter.matches(c.printing)
            ]
            if not options:
                break
            picked = None
            if p.agent is not None:
                picked = p.agent.choose_card_from_library(
                    state, controller_id, [c.id for c in options],
                )
            chosen = _agent_pick(options, picked)
            if chosen is None:
                if self.optional:
                    break
                chosen = options[0]
            taken.append(chosen)
        for c in taken:
            c.zone = Zone.HAND
            p.hand.append(c)
            if self.reveal_taken:
                reveal_to_all(state, c)
        rest = [c for c in looked if c not in taken]
        if self.rest_random:
            state.rng.shuffle(rest)
        for c in rest:
            if self.rest_zone == "graveyard":
                c.zone = Zone.GRAVEYARD
                p.graveyard.append(c)
            else:
                c.zone = Zone.LIBRARY
                p.library.append(c)
        state.log.append(
            f"P{controller_id} looks at {n} card(s), takes {len(taken)}, "
            f"puts {len(rest)} into {self.rest_zone}"
        )

    def describe(self) -> str:
        verb = "reveal" if self.reveal else "look at"
        may = "you may put" if self.optional else "put"
        return (
            f"{verb} the top {_describe_amount(self.count)} cards of your "
            f"library; {may} {self.take} {self.take_filter.describe()}(s) "
            f"into your hand; the rest go to the {self.rest_zone}"
        )


@dataclass(frozen=True)
class ReorderTopCards(Effect):
    """"Look at the top N cards of your library, then put them back in
    any order." (Ponder's first sentence.)

    The new order is built top-down: each position is filled by a
    ``choose_card_from_library`` pick among the not-yet-placed cards.
    The reordered cards stay known to their owner.
    """

    count: int = 3

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.game import Zone, reveal_to

        p = state.player_by_id(controller_id)
        n = min(self.count, len(p.library))
        looked = [p.library.pop(0) for _ in range(n)]
        ordered: list = []
        remaining = list(looked)
        while remaining:
            chosen = remaining[0]
            if p.agent is not None and len(remaining) > 1:
                picked = p.agent.choose_card_from_library(
                    state, controller_id, [c.id for c in remaining],
                )
                chosen = _agent_pick(remaining, picked) or remaining[0]
            remaining.remove(chosen)
            ordered.append(chosen)
        for c in reversed(ordered):
            c.zone = Zone.LIBRARY
            p.library.insert(0, c)
            reveal_to(c, controller_id)
        state.log.append(f"P{controller_id} reorders the top {n} card(s)")

    def describe(self) -> str:
        return (
            f"look at the top {self.count} cards of your library, then put "
            f"them back in any order"
        )


@dataclass(frozen=True)
class ShuffleYourLibrary(Effect):
    """"Shuffle." / "You may shuffle." (Ponder's second sentence.)

    With ``optional`` the controller decides via ``choose_yes_no``.
    """

    optional: bool = False

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.game import shuffle_library

        p = state.player_by_id(controller_id)
        if self.optional and p.agent is not None and not p.agent.choose_yes_no(
            state, controller_id, "Shuffle your library?",
        ):
            state.log.append(f"P{controller_id} declines to shuffle")
            return
        shuffle_library(state, controller_id)
        state.log.append(f"P{controller_id} shuffles their library")

    def describe(self) -> str:
        return "you may shuffle" if self.optional else "shuffle"


@dataclass(frozen=True)
class LookAtTargetPlayersHand(Effect):
    """"Look at target player's hand." Every card in the target's hand
    becomes known to the controller (``reveal_to``)."""

    def requires_target(self) -> bool:
        return True

    def legal_targets(self, state, controller_id):
        return _player_targets(state, controller_id, opponent_only=False)

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.game import reveal_to

        p = _target_player(state, targets)
        if p is None:
            return
        for c in p.hand:
            reveal_to(c, controller_id)
        state.log.append(f"P{controller_id} looks at P{p.id}'s hand")

    def describe(self) -> str:
        return "look at target player's hand"


@dataclass(frozen=True)
class ExileThisSpell(Effect):
    """"Exile <this spell's name>." as part of a spell's own resolution
    (Time Spiral). Moves ``state.resolving_spell`` to its owner's exile;
    ``resolve_top_of_stack`` sees the zone change and skips the usual
    graveyard routing."""

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.game import Zone

        card = state.resolving_spell
        if card is None:
            return
        card.cast_via_flashback = False
        card.zone = Zone.EXILE
        state.player_by_id(card.owner_id).exile.append(card)
        state.log.append(f"{card.printing.name} exiles itself")

    def describe(self) -> str:
        return "exile this spell"


# ---------------------------------------------------------------------
# Wheels / mass zone moves
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class EachPlayerShufflesZonesIntoLibrary(Effect):
    """"Each player shuffles their hand and graveyard into their library"
    (Timetwister, Echo of Eons, Time Spiral). ``zones`` is a subset of
    ``("hand", "graveyard")``. Cards leave their zone lists before their
    ``zone`` field is rewritten (copy-on-write safe)."""

    zones: tuple[str, ...] = ("hand", "graveyard")

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.game import Zone, shuffle_library

        for i in range(len(state.players)):
            p = state.players[(state.active_player_idx + i) % len(state.players)]
            if p.has_lost:
                continue
            moved: list = []
            if "hand" in self.zones:
                moved.extend(p.hand)
                p.hand.clear()
            if "graveyard" in self.zones:
                moved.extend(p.graveyard)
                p.graveyard.clear()
            for c in moved:
                c.zone = Zone.LIBRARY
                p.library.append(c)
            shuffle_library(state, p.id)
            state.log.append(
                f"P{p.id} shuffles {len(moved)} card(s) into their library"
            )

    def describe(self) -> str:
        return (
            "each player shuffles their "
            + " and ".join(self.zones) + " into their library"
        )


@dataclass(frozen=True)
class UntapUpToNLands(Effect):
    """"Untap up to N lands." (Frantic Search, Time Spiral.)

    Untaps up to ``amount`` tapped lands the controller controls,
    preferring lands that produce the most colors. Untapping an
    opponent's land is legal but never in the caster's interest, so the
    choice is restricted to the controller's own lands (documented in
    ``docs/SEARCH_LIMITATIONS.md``).
    """

    amount: int = 1

    def resolve(self, state, controller_id, targets=()):
        tapped = [
            o for o in state.battlefield
            if o.controller_id == controller_id
            and o.printing.is_land and o.tapped
        ]
        tapped.sort(key=lambda o: (-len(o.printing.produces), o.id))
        for o in tapped[: self.amount]:
            o.tapped = False
        state.log.append(
            f"P{controller_id} untaps {min(self.amount, len(tapped))} land(s)"
        )

    def describe(self) -> str:
        return f"untap up to {self.amount} lands"


@dataclass(frozen=True)
class ReturnAllPermanentsToOwnersHands(Effect):
    """"Return all permanents to their owners' hands." (Upheaval.)

    Attached permanents (Auras, Equipment) are returned first so an
    Aura isn't buried as a state-based consequence of its host leaving
    — every permanent leaves simultaneously. Tokens cease to exist.
    """

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.turn import move_off_battlefield

        snapshot = sorted(
            state.battlefield, key=lambda o: (o.attached_to is None, o.id),
        )
        for obj in snapshot:
            if obj in state.battlefield:
                move_off_battlefield(state, obj, destination="hand")
        state.log.append(
            f"{len(snapshot)} permanent(s) return to their owners' hands"
        )

    def describe(self) -> str:
        return "return all permanents to their owners' hands"


@dataclass(frozen=True)
class ReturnTargetSpellToOwnersHand(Effect):
    """"Return target spell to its owner's hand." (Reprieve.)

    Targets a spell on the stack by index (the ``"stack"`` target kind
    ``CounterTargetSpell`` uses). The spell leaves the stack without
    resolving; a spell cast with flashback is exiled instead (CR
    702.34a) via :func:`mtg_bot.actions.move_spell_off_stack`.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(self, state, controller_id):
        return [
            ("stack", i) for i, item in enumerate(state.stack)
            if item.ability is None and not item.countered
        ]

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.actions import move_spell_off_stack

        if not targets:
            return
        kind, idx = targets[0]
        if kind != "stack" or not (0 <= idx < len(state.stack)):
            return
        item = state.stack[idx]
        if item.ability is not None or item.countered:
            return
        del state.stack[idx]
        move_spell_off_stack(state, item.source, destination="hand")

    def describe(self) -> str:
        return "return target spell to its owner's hand"
