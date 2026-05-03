"""Tests for ``mtg_bot.mulligan.heuristic_*`` — the extreme-only
mulligan policy and the high-MV-first bottom selector.

The policy is deliberately conservative: only the catastrophic
hands (0 lands, all lands) mulligan; everything else keeps. These
tests pin both the conservative behavior (don't mulligan borderline
hands) AND the extreme behavior (do mulligan the actual disasters).
"""

from __future__ import annotations

from dataclasses import dataclass

from mtg_bot.mulligan import (
    heuristic_bottom_choice, heuristic_mulligan_decision,
)


@dataclass
class _FakePrinting:
    """Stand-in for CardPrinting — only the fields the heuristic
    looks at. Keeps tests tight (no decklist setup, no engine
    initialization)."""

    is_land: bool
    mana_value: int = 0

    @property
    def mana_cost(self):
        # Mimics the real ManaCost interface: ``.total()`` returns
        # the integer cost.
        class _MC:
            def __init__(self, t):
                self._t = t

            def total(self):
                return self._t

        return _MC(self.mana_value)


@dataclass
class _FakeCard:
    id: int
    printing: _FakePrinting


def _h(*specs):
    """Build a hand from (is_land, mana_value) specs. Sequential
    ids 1..N so tests can assert returned ids unambiguously."""
    return [
        _FakeCard(id=i + 1, printing=_FakePrinting(is_land=bool(is_l), mana_value=mv))
        for i, (is_l, mv) in enumerate(specs)
    ]


# ---------- mulligan decision -----------------------------------------------


def test_mulligan_when_zero_lands():
    hand = _h(*[(False, 3)] * 7)  # 7 spells, 0 lands
    assert heuristic_mulligan_decision(hand, 0) is True
    assert heuristic_mulligan_decision(hand, 5) is True  # always


def test_mulligan_when_all_lands():
    hand = _h(*[(True, 0)] * 7)  # 7 lands, 0 spells
    assert heuristic_mulligan_decision(hand, 0) is True


def test_keep_one_land():
    """Borderline 1-land hand keeps under this conservative policy.
    A smarter policy might mulligan; we don't, by design."""
    hand = _h((True, 0), *[(False, 3)] * 6)
    assert heuristic_mulligan_decision(hand, 0) is False


def test_keep_six_lands():
    """Mirror: 6 lands + 1 spell. Borderline flood, but the policy
    keeps."""
    hand = _h(*[(True, 0)] * 6, (False, 4))
    assert heuristic_mulligan_decision(hand, 0) is False


def test_keep_balanced_hand():
    hand = _h(
        (True, 0), (True, 0), (True, 0),  # 3 lands
        (False, 1), (False, 2), (False, 3), (False, 4),  # 4 spells
    )
    assert heuristic_mulligan_decision(hand, 0) is False


def test_decision_independent_of_mulls_taken():
    """The extreme-only policy doesn't change with mulligan count
    (we always mulligan if extreme; the engine forces keep at
    max_mulligans, but the policy itself is mulls-agnostic)."""
    hand_no_lands = _h(*[(False, 2)] * 7)
    for mulls in range(7):
        assert heuristic_mulligan_decision(hand_no_lands, mulls) is True


def test_empty_hand_keeps():
    """Defensive edge case: empty hand can't possibly be ``all
    lands`` or ``no lands`` meaningfully — return False (keep) so
    the engine doesn't loop forever on an impossible hand."""
    assert heuristic_mulligan_decision([], 0) is False


# ---------- bottom choice ---------------------------------------------------


def test_bottom_prefers_high_mv_nonland():
    """4-cost spell goes before 1-cost spell when bottoming 1."""
    hand = _h(
        (True, 0), (True, 0), (True, 0),
        (False, 1), (False, 2), (False, 4), (False, 6),
    )
    bottom = heuristic_bottom_choice(hand, 1)
    assert bottom == [7]  # the 6-cost spell


def test_bottom_keeps_lands_first():
    """Bottoming 3 cards from a hand with 3 lands + 4 spells:
    bottom the 3 highest-cost spells, keep all lands."""
    hand = _h(
        (True, 0), (True, 0), (True, 0),
        (False, 6), (False, 5), (False, 1), (False, 4),
    )
    bottom = heuristic_bottom_choice(hand, 3)
    # IDs of the 3 highest-MV nonland: 4 (cost 6), 5 (cost 5), 7 (cost 4)
    assert sorted(bottom) == [4, 5, 7]


def test_bottom_falls_back_to_lands_when_nonland_runs_out():
    """All-land hand asked to bottom 2 → bottoms first 2 lands by id."""
    hand = _h(*[(True, 0)] * 7)
    bottom = heuristic_bottom_choice(hand, 2)
    assert sorted(bottom) == [1, 2]


def test_bottom_n_zero_returns_empty():
    hand = _h((False, 3), (True, 0))
    assert heuristic_bottom_choice(hand, 0) == []


def test_bottom_n_eq_hand_size_returns_all_ids():
    hand = _h((False, 3), (True, 0), (False, 1))
    bottom = heuristic_bottom_choice(hand, 3)
    assert sorted(bottom) == [1, 2, 3]


def test_bottom_is_deterministic_in_hand_order():
    """Same hand → same selection. Critical for search reproducibility."""
    hand = _h(
        (True, 0), (False, 4), (False, 4),  # tie on MV (id breaks)
        (True, 0), (False, 1), (True, 0), (False, 4),
    )
    a = heuristic_bottom_choice(hand, 2)
    b = heuristic_bottom_choice(hand, 2)
    assert a == b
    # Tied 4-cost spells: ids 2, 3, 7 → first 2 by id are 2 and 3.
    assert a == [2, 3]


def test_bottom_returns_distinct_ids():
    """No agent should bottom the same card twice — the engine
    validates this and would raise, but the heuristic shouldn't
    produce duplicates in the first place."""
    hand = _h(
        (False, 5), (False, 5), (False, 5),
        (True, 0), (True, 0), (True, 0), (True, 0),
    )
    bottom = heuristic_bottom_choice(hand, 3)
    assert len(set(bottom)) == 3


def test_bottom_handles_int_mana_cost():
    """``card.printing.mana_cost`` is sometimes a plain ``int``
    rather than a ``ManaCost`` instance — production hit this on
    multiple v6-vs-v5 eval games as ``TypeError: 'int' object is
    not callable`` from ``cost.total()``. The defensive guard in
    ``_mana_value`` should accept both shapes."""
    from dataclasses import dataclass

    @dataclass
    class _IntCostPrinting:
        is_land: bool = False
        mana_cost: int = 5  # plain int, not a ManaCost

    @dataclass
    class _IntCostCard:
        id: int
        printing: _IntCostPrinting

    hand = [
        _IntCostCard(id=1, printing=_IntCostPrinting(mana_cost=2)),
        _IntCostCard(id=2, printing=_IntCostPrinting(mana_cost=8)),
        _IntCostCard(id=3, printing=_IntCostPrinting(mana_cost=4)),
    ]
    # Bottom 1 card → highest mana value (id=2, cost 8) goes first.
    # If the int-cost branch wasn't handled, this would raise
    # TypeError instead.
    bottom = heuristic_bottom_choice(hand, 1)
    assert bottom == [2]


def test_bottom_handles_missing_mana_cost():
    """Some printings have no ``mana_cost`` attribute at all
    (e.g. tokens). Defensive ``getattr(..., None)`` plus the
    ``isinstance``/``callable`` checks should fall back to 0
    rather than raising."""
    from dataclasses import dataclass

    @dataclass
    class _NoCostPrinting:
        is_land: bool = False
        # no mana_cost attribute

    @dataclass
    class _NoCostCard:
        id: int
        printing: _NoCostPrinting

    hand = [
        _NoCostCard(id=1, printing=_NoCostPrinting()),
        _NoCostCard(id=2, printing=_NoCostPrinting()),
    ]
    # All cards have mana_value=0 → tie-break on id; first id wins.
    bottom = heuristic_bottom_choice(hand, 1)
    assert bottom == [1]
