"""Cleanup-step hand-size limit primitive on ``GameState``.

Ports the hand-size enforcement logic from ``run_cleanup_step`` in
``src/mtg_bot/turn.py`` (lines 969-990 on `feature/rust-tdd-base-r6`):

    while len(ap.hand) > 7:
        card = ap.hand.pop()
        card.zone = Zone.GRAVEYARD
        ap.graveyard.append(card)

Real MTG rule (CR 514.1):

    "If the active player's hand contains more cards than their maximum
    hand size (normally seven), they discard enough cards to reduce
    their hand size to that number."

This slice composes round-4's ``discard`` (library slice) with round-2's
``PHASE_CLEANUP = 11`` (steps slice). The Rust API exposes a single
primitive ``enforce_hand_size_limit(player_id, max_hand_size)`` that the
caller invokes — a future slice can wire it into ``advance_phase`` so
it fires automatically when the active player enters cleanup.

**Scope decisions** (kept narrow for this slice):

- Default max hand size is 7 — encoded by the caller; the primitive
  takes ``max_hand_size`` explicitly so cards like Reliquary Tower (no
  maximum hand size) plug in by passing a sentinel later.
- Active-player only: the primitive takes ``player_id`` explicitly
  rather than reading ``state.active_player``. Whoever calls it picks.
- **Discard target choice is deterministic**: cards come off the END
  of the hand Vec (most recently drawn / pushed). Real MTG: the player
  chooses which cards to discard. This is a stepping-stone — once the
  search side has a discard-decision node, it picks. For now the
  primitive's deterministic choice is good enough for state-evolution
  parity tests and lets the cleanup step make forward progress in
  search rollouts.
- Discarded cards land in the same player's graveyard (CR 514.1 →
  "discard" → CR 701.8 → "owner's graveyard"; for synthetic states
  controller == owner so the same-player target is correct).
"""

from __future__ import annotations

import pytest


def test_hand_at_or_below_max_no_discard(synthetic_state):
    """Synthetic state seeds 7 cards in player 0's hand. Enforcing a
    max of 7 is a no-op — hand stays at 7, graveyard stays at 0."""
    assert synthetic_state.hand_sizes[0] == 7
    gy_before = synthetic_state.graveyard_sizes
    discarded = synthetic_state.enforce_hand_size_limit(0, 7)
    assert discarded == 0
    assert synthetic_state.hand_sizes[0] == 7
    assert synthetic_state.graveyard_sizes == gy_before


def test_hand_above_max_discards_to_max(synthetic_state):
    """Bring hand to 10 via three draws, enforce max=7, expect three
    discards and a hand size of exactly 7."""
    for _ in range(3):
        synthetic_state.draw_card(0)
    assert synthetic_state.hand_sizes[0] == 10

    discarded = synthetic_state.enforce_hand_size_limit(0, 7)
    assert discarded == 3
    assert synthetic_state.hand_sizes[0] == 7


def test_discarded_cards_go_to_graveyard(synthetic_state):
    """Same setup as above; the three discarded cards land in player
    0's graveyard. Player 1's graveyard is untouched."""
    for _ in range(3):
        synthetic_state.draw_card(0)
    gy_before = synthetic_state.graveyard_sizes
    synthetic_state.enforce_hand_size_limit(0, 7)
    assert synthetic_state.graveyard_sizes[0] == gy_before[0] + 3
    assert synthetic_state.graveyard_sizes[1] == gy_before[1]


def test_discard_count_returns_number_discarded(synthetic_state):
    """The return value is the count of cards moved hand -> graveyard."""
    for _ in range(3):
        synthetic_state.draw_card(0)
    assert synthetic_state.enforce_hand_size_limit(0, 7) == 3


def test_no_discard_returns_zero(synthetic_state):
    """No discard needed -> returns 0."""
    assert synthetic_state.enforce_hand_size_limit(0, 7) == 0
    # Even with a generous limit on a small hand:
    assert synthetic_state.enforce_hand_size_limit(0, 100) == 0


def test_max_hand_size_zero_discards_everything(synthetic_state):
    """``max_hand_size=0`` empties the hand (all 7 cards into
    graveyard)."""
    discarded = synthetic_state.enforce_hand_size_limit(0, 0)
    assert discarded == 7
    assert synthetic_state.hand_sizes[0] == 0
    assert synthetic_state.graveyard_sizes[0] == 7


def test_only_discards_target_player(synthetic_state):
    """Bring both hands to 10; enforce on player 0 only — player 1's
    hand is unchanged."""
    for _ in range(3):
        synthetic_state.draw_card(0)
        synthetic_state.draw_card(1)
    assert synthetic_state.hand_sizes == [10, 10]

    synthetic_state.enforce_hand_size_limit(0, 7)
    assert synthetic_state.hand_sizes[0] == 7
    assert synthetic_state.hand_sizes[1] == 10
    # Player 1's graveyard untouched.
    assert synthetic_state.graveyard_sizes[1] == 0


def test_unknown_player_raises(synthetic_state):
    """Out-of-range player_id (only 0 / 1 are valid for two-player)
    raises ValueError rather than silently no-op'ing."""
    with pytest.raises(ValueError):
        synthetic_state.enforce_hand_size_limit(99, 7)


def test_negative_max_raises(synthetic_state):
    """A negative max_hand_size makes no sense (you can't reduce hand
    size below zero); raise rather than treat as max=0."""
    with pytest.raises(ValueError):
        synthetic_state.enforce_hand_size_limit(0, -1)


def test_clone_then_discard_does_not_affect_original(synthetic_state):
    """Load-bearing CoW canary: enforcing on a clone must not leak
    back into the source state. Both hand and graveyard are mutated,
    so this is the strictest CoW check in the slice."""
    for _ in range(3):
        synthetic_state.draw_card(0)
    cloned = synthetic_state.clone_once()
    hand_source_before = synthetic_state.hand_sizes
    gy_source_before = synthetic_state.graveyard_sizes

    discarded = cloned.enforce_hand_size_limit(0, 7)
    assert discarded == 3

    # Clone diverged.
    assert cloned.hand_sizes[0] == 7
    assert cloned.graveyard_sizes[0] == gy_source_before[0] + 3
    # Source untouched.
    assert synthetic_state.hand_sizes == hand_source_before
    assert synthetic_state.graveyard_sizes == gy_source_before
