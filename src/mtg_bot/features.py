"""Fixed-length feature extraction for the NN evaluator.

Phase B of the learned-evaluator work. Turns an engine ``GameState``
into a fixed-length ``numpy.ndarray`` of floats — the input layer
for the eventual MLP. Pure function, deterministic, no NN code yet.

Design constraints:

- **Fixed length, fixed schema.** The MLP's input dimension is
  ``FEATURE_DIM`` and never changes once a network is trained. New
  features have to go at the end and bump ``FEATURE_DIM`` (which
  invalidates old trained networks — that's the cost). Indices are
  named constants so feature analysis (importance, activations) is
  doable later.
- **Viewer-relative.** Features are extracted from
  ``viewer_id``'s perspective: the first per-side block is
  ``viewer``'s, the second is the opponent's. Means a single trained
  network works for both seats — call once with viewer=0, call
  again with viewer=1.
- **Raw values, not normalized.** Life is the integer life total,
  not life/20. Phase C handles input normalization at the network
  boundary (computed from training-data mean/std).
- **No card-identity awareness.** Features are aggregates (counts,
  sums, max). A "good 4/3" and a "bad 4/3" look identical here.
  That's the documented ceiling of this representation; per-card
  embeddings are a Phase E ambition.

Layout (51 features total — see indices below):

- ``[ 0..15)`` viewer per-side block (16 features)
- ``[16..32)`` opponent per-side block (16 features)
- ``[32..40)`` viewer keyword counts on creatures (8 features)
- ``[40..48)`` opponent keyword counts on creatures (8 features)
- ``[48..51)`` global state (3 features)
"""

from __future__ import annotations

import numpy as np

from mtg_bot.game import (
    GameState,
    effective_keywords,
    effective_power,
    effective_toughness,
    is_creature_now,
)
from mtg_bot.turn import STEP_ORDER

# ---------------------------------------------------------------------------
# Layout: feature indices as named constants. Keep these in sync with the
# extraction logic in extract_features() — coverage tests below also assert
# the layout is consistent with FEATURE_DIM.
# ---------------------------------------------------------------------------

# Per-side block (16 features each, two blocks back-to-back: viewer then
# opponent). Shared offsets within a block.
_PER_SIDE_LIFE = 0
_PER_SIDE_POISON = 1
_PER_SIDE_HAND_SIZE = 2
_PER_SIDE_LIBRARY_SIZE = 3
_PER_SIDE_GRAVEYARD_SIZE = 4
_PER_SIDE_EXILE_SIZE = 5
_PER_SIDE_NUM_LANDS = 6
_PER_SIDE_NUM_UNTAPPED_LANDS = 7
_PER_SIDE_NUM_CREATURES = 8
_PER_SIDE_NUM_OTHER_PERMANENTS = 9
_PER_SIDE_TOTAL_POWER = 10
_PER_SIDE_TOTAL_TOUGHNESS = 11
_PER_SIDE_MAX_THREAT_PT = 12
_PER_SIDE_NUM_TAPPED_PERMANENTS = 13
_PER_SIDE_LANDS_PLAYED_THIS_TURN = 14
_PER_SIDE_SPELLS_CAST_THIS_TURN = 15
_PER_SIDE_BLOCK_SIZE = 16

# Keyword block (8 features each, two blocks back-to-back: viewer then
# opponent). Counts of viewer/opponent creatures on the battlefield with
# each evergreen keyword.
_KW_OFFSETS = {
    "flying": 0,
    "first strike": 1,
    "double strike": 2,
    "deathtouch": 3,
    "lifelink": 4,
    "trample": 5,
    "vigilance": 6,
    "reach": 7,
}
_KW_BLOCK_SIZE = len(_KW_OFFSETS)  # 8

# Global features (3, after both per-side and keyword blocks).
_GLOBAL_STACK_SIZE = 0
_GLOBAL_IS_VIEWER_TURN = 1
_GLOBAL_STEP_INDEX = 2  # ordinal position in STEP_ORDER (0..11)
_GLOBAL_BLOCK_SIZE = 3

# Block start offsets in the final vector.
_VIEWER_BLOCK_START = 0
_OPPONENT_BLOCK_START = _VIEWER_BLOCK_START + _PER_SIDE_BLOCK_SIZE
_VIEWER_KW_START = _OPPONENT_BLOCK_START + _PER_SIDE_BLOCK_SIZE
_OPPONENT_KW_START = _VIEWER_KW_START + _KW_BLOCK_SIZE
_GLOBAL_BLOCK_START = _OPPONENT_KW_START + _KW_BLOCK_SIZE

FEATURE_DIM: int = _GLOBAL_BLOCK_START + _GLOBAL_BLOCK_SIZE  # 51

_DTYPE = np.float32


def extract_features(
    state: GameState, viewer_id: int,
) -> np.ndarray:
    """Return a fixed-length ``np.float32`` array of features for
    ``state`` from ``viewer_id``'s perspective.

    Output shape: ``(FEATURE_DIM,)``. Schema described in the module
    docstring; named index constants are module-private (callers
    operate on the whole vector, not by name).

    Pure function: same input → same output, no mutation, no
    randomness. Two-player only — opponent is whichever player isn't
    ``viewer_id``.

    **Seat-id symmetry invariant.** Self-play exhibits a strong
    seat-0 win bias (engine-structural — going first wins games),
    so any signal in the feature vector that lets the value head
    distinguish "I am seated at index 0" from "I am seated at
    index 1" becomes a training shortcut: with ~70-80% seat-0 wins,
    seat-0 viewer rows skew +1 and seat-1 viewer rows skew -1, and
    the model latches onto seat id instead of evaluating the
    position. The features here are strictly viewer-relative —
    every per-side block is keyed off ``player_id`` (not list
    index), the global ``is_viewer_turn`` compares ids, and nothing
    here reads ``state.priority_player_idx`` or ``state.turn_number``
    directly. Pinned by ``test_features_are_invariant_under_seat_swap``
    and friends in ``tests/test_features.py``; if those start
    failing, a leak has been introduced and must be fixed before
    training a new value head.
    """
    out = np.zeros(FEATURE_DIM, dtype=_DTYPE)

    viewer = state.player_by_id(viewer_id)
    opponents = [p for p in state.players if p.id != viewer_id]
    if not opponents:
        # Singleton (defensive — 2-player MTG always has an opponent).
        # Return all-zero features rather than raising.
        return out
    opponent = opponents[0]

    _fill_per_side_block(out, _VIEWER_BLOCK_START, state, viewer_id)
    _fill_per_side_block(out, _OPPONENT_BLOCK_START, state, opponent.id)
    _fill_keyword_block(out, _VIEWER_KW_START, state, viewer_id)
    _fill_keyword_block(out, _OPPONENT_KW_START, state, opponent.id)
    _fill_global_block(out, _GLOBAL_BLOCK_START, state, viewer_id)

    return out


def _fill_per_side_block(
    out: np.ndarray, start: int, state: GameState, player_id: int,
) -> None:
    p = state.player_by_id(player_id)
    creatures = []
    lands = 0
    untapped_lands = 0
    other_permanents = 0
    tapped_permanents = 0

    for o in state.battlefield:
        if o.controller_id != player_id:
            continue
        if o.tapped:
            tapped_permanents += 1
        if o.printing.is_land:
            lands += 1
            if not o.tapped:
                untapped_lands += 1
        elif is_creature_now(o):
            creatures.append(o)
        else:
            other_permanents += 1

    total_power = 0
    total_toughness = 0
    max_threat_pt = 0
    for c in creatures:
        cp = effective_power(state, c)
        ct = effective_toughness(state, c)
        total_power += cp
        total_toughness += ct
        if cp + ct > max_threat_pt:
            max_threat_pt = cp + ct

    out[start + _PER_SIDE_LIFE] = p.life
    out[start + _PER_SIDE_POISON] = p.poison_counters
    out[start + _PER_SIDE_HAND_SIZE] = len(p.hand)
    out[start + _PER_SIDE_LIBRARY_SIZE] = len(p.library)
    out[start + _PER_SIDE_GRAVEYARD_SIZE] = len(p.graveyard)
    out[start + _PER_SIDE_EXILE_SIZE] = len(p.exile)
    out[start + _PER_SIDE_NUM_LANDS] = lands
    out[start + _PER_SIDE_NUM_UNTAPPED_LANDS] = untapped_lands
    out[start + _PER_SIDE_NUM_CREATURES] = len(creatures)
    out[start + _PER_SIDE_NUM_OTHER_PERMANENTS] = other_permanents
    out[start + _PER_SIDE_TOTAL_POWER] = total_power
    out[start + _PER_SIDE_TOTAL_TOUGHNESS] = total_toughness
    out[start + _PER_SIDE_MAX_THREAT_PT] = max_threat_pt
    out[start + _PER_SIDE_NUM_TAPPED_PERMANENTS] = tapped_permanents
    out[start + _PER_SIDE_LANDS_PLAYED_THIS_TURN] = p.lands_played_this_turn
    out[start + _PER_SIDE_SPELLS_CAST_THIS_TURN] = p.spells_cast_this_turn


def _fill_keyword_block(
    out: np.ndarray, start: int, state: GameState, player_id: int,
) -> None:
    for o in state.battlefield:
        if o.controller_id != player_id:
            continue
        if not is_creature_now(o):
            continue
        kws = effective_keywords(state, o)
        for kw, offset in _KW_OFFSETS.items():
            if kw in kws:
                out[start + offset] += 1


def _fill_global_block(
    out: np.ndarray, start: int, state: GameState, viewer_id: int,
) -> None:
    out[start + _GLOBAL_STACK_SIZE] = len(state.stack)
    active_player = (
        state.players[state.active_player_idx].id
        if state.players else viewer_id
    )
    out[start + _GLOBAL_IS_VIEWER_TURN] = float(active_player == viewer_id)
    if state.step is not None:
        try:
            out[start + _GLOBAL_STEP_INDEX] = STEP_ORDER.index(state.step)
        except ValueError:
            # Unknown step — leave at 0. Defensive only; engine always
            # uses STEP_ORDER values.
            pass
