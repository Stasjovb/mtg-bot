"""Heuristic mulligan and bottom policy.

Pre-game decision-making is its own little corner of the engine —
``simulate.setup_game`` calls ``Agent.choose_mulligan`` once per
player at game start, and ``Agent.choose_bottom`` once after the
final keep. This module provides a generic extreme-only heuristic
that any agent can plug in. The base ``Agent`` defaults to "always
keep" (preserves Stage-1 behavior); concrete agents that want a
real policy delegate to the helpers here.

The policy is deliberately simple and conservative — it only
mulligans the catastrophically-bad opening hands (no lands or all
lands). Everything else keeps. This catches the worst variance
source (mana screw / mana flood at game 1 turn 1) while staying
agent-agnostic and doing nothing surprising on borderline hands.

A future smarter policy can replace ``heuristic_mulligan_decision``
without changing any caller — it's a pure function of (hand,
mulls_taken).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from mtg_bot.game import GameObject


def _is_land(card: "GameObject") -> bool:
    return card.printing.is_land


def _mana_value(card: "GameObject") -> int:
    """Total mana cost of the card's printed mana_cost. Lands and
    cards without a mana_cost return 0 (lands are free, and the
    handful of {0}-cost cards correctly compare as cheapest)."""
    cost = getattr(card.printing, "mana_cost", None)
    if cost is None:
        return 0
    return cost.total()


def heuristic_mulligan_decision(
    hand: Iterable["GameObject"], mulls_taken: int,
) -> bool:
    """Should this hand be mulliganed? Returns True for mulligan,
    False for keep.

    Decision rule: mulligan only if the hand has zero lands or
    every card is a land. Both extremes are essentially unwinnable
    (mana-screw or mana-flood at turn 1) and a free 7-redraw is
    almost always better even at the cost of bottoming a card.
    Every other hand keeps — borderline cases (1 land, 6 lands,
    weird curves) are left to play out.

    The London-mulligan rule still bottoms ``mulls_taken`` cards
    on keep, so this isn't a free reroll: each mulligan costs a
    card. Limiting mulligans to the extremes preserves that cost
    discipline.
    """
    cards = list(hand)
    if not cards:
        return False  # empty hand is a forced-keep edge case
    n_lands = sum(1 for c in cards if _is_land(c))
    return n_lands == 0 or n_lands == len(cards)


def heuristic_bottom_choice(
    hand: list["GameObject"], n: int,
) -> list[int]:
    """Pick ``n`` cards to put on the bottom of the library.

    Strategy: bottom the highest-mana-value non-land cards first
    (they're the slowest to deploy and give the worst tempo if
    drawn). If that runs out, bottom remaining cards by hand
    position. Lands are kept by default — once we've already
    decided to keep this hand, the lands in it are part of why.

    Tie-breaks: stable on hand position (so two clones with the
    same hand make the same choice — search reproducibility).

    Returns ``n`` distinct ids drawn from the hand.
    """
    if n <= 0:
        return []
    if n >= len(hand):
        return [c.id for c in hand]

    # High-MV non-land first; ties broken by hand-order id.
    nonland_sorted = sorted(
        (c for c in hand if not _is_land(c)),
        key=lambda c: (-_mana_value(c), c.id),
    )
    bottom: list[int] = [c.id for c in nonland_sorted[:n]]

    # Fallback: hand was lands-and-zeros, fill the remaining slots
    # with whatever's left in hand order.
    if len(bottom) < n:
        sent = set(bottom)
        for c in hand:
            if c.id in sent:
                continue
            bottom.append(c.id)
            if len(bottom) == n:
                break

    return bottom[:n]
