"""Heuristic mulligan and bottom policy.

Pre-game decision-making is its own little corner of the engine —
``simulate.setup_game`` calls ``Agent.choose_mulligan`` once per
player at game start, and ``Agent.choose_bottom`` once after the
final keep. This module provides a generic two-tier mulligan
heuristic that any agent can plug in. The base ``Agent`` defaults
to "always keep" (preserves Stage-1 behavior); concrete agents
that want a real policy delegate to the helpers here.

The policy mulligans the screw (≤1 land) and flood (≥6 lands)
ends through the first two looks, then narrows to "only mulligan
zero lands" at the third look and beyond — by that point the
London-mulligan bottoming cost (3+ cards) outweighs further
optimization on borderline hands. See
``heuristic_mulligan_decision`` for the exact rule.

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
    handful of {0}-cost cards correctly compare as cheapest).

    Defensive against ``mana_cost`` being either a ``ManaCost``
    instance (the typical case — has a ``.total()`` method) or
    a plain ``int`` (some printings store the integer cost
    directly). Anything else (including ``None``) falls back to
    0. The mulligan policy uses this only for ranking, so the
    exact value matters less than not raising on the lookup —
    a TypeError in the bottom-pick path would crash the whole
    setup_game call.
    """
    cost = getattr(card.printing, "mana_cost", None)
    if cost is None:
        return 0
    if isinstance(cost, int):
        return cost
    total = getattr(cost, "total", None)
    if callable(total):
        return total()
    return 0


def heuristic_mulligan_decision(
    hand: Iterable["GameObject"], mulls_taken: int,
) -> bool:
    """Should this hand be mulliganed? Returns True for mulligan,
    False for keep.

    Decision rule (the "aggressive" 7-card heuristic):

    * At ``mulls_taken < 2`` (first or second look): mulligan if the
      land count is in ``{0, 1, 6, 7}`` — both the screw end (≤1 land)
      and the flood end (≥6 lands) are unkeepable at this mulligan
      cost. Hands with 2-5 lands keep.
    * At ``mulls_taken >= 2`` (already paid for two mulligans):
      mulligan only if the hand has zero lands. By the third look the
      bottoming cost (3+ cards) outweighs the marginal improvement
      from any non-zero-land hand; even a mana-flood 6/7 keeps. Only
      the truly catastrophic 0-land hand justifies a third mull.

    The London-mulligan rule still bottoms ``mulls_taken`` cards on
    keep, so each mulligan costs a card. The two-tier policy spends
    that cost where it matters most (early flood/screw) and stops
    paying it once the hand size starts hurting.

    The decision is a pure function of ``(hand, mulls_taken)`` —
    no engine state, no RNG. Two clones of the same opening with
    the same ``mulls_taken`` make identical choices, important for
    search reproducibility.
    """
    cards = list(hand)
    if not cards:
        return False  # empty hand is a forced-keep edge case
    n_lands = sum(1 for c in cards if _is_land(c))
    if mulls_taken < 2:
        return n_lands <= 1 or n_lands >= 6
    return n_lands == 0


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
