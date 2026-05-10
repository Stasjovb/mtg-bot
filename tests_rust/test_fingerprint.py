"""Rust ``GameState.fingerprint()`` — 12-char SHA1 digest matching
``scripts/parity_smoke.py:hash_state``.

Round-22 phase-2b slice. The fingerprint is the canonical state-equality
oracle for parity testing — a Python GameState and a Rust GameState
that share their gameplay-relevant invariants produce the same digest.
The parity harness compares two strings instead of walking zone
snapshots dict-by-dict.

The Python ``hash_state`` builds a list of:

    [turn_number, step_string, active_player_idx, priority_player_idx,
     is_over, is_draw, winner_id,
     (p0_id, life, has_lost, hand_sig, library_sig, graveyard_sig,
      exile_sig, mana_pool_sorted_items),
     (p1_..., same shape),
     battlefield_signature,
     stack_signature]

then ``hashlib.sha1(json.dumps(parts, default=repr, sort_keys=False)
.encode("utf-8")).hexdigest()[:12]``.

Each zone signature is a tuple of per-object 8-tuples
``(printing_name | None, int(tapped), int(summoning_sick), damage,
counters, attached_to, controller_id, id)``.

## Cross-engine parity (key test)

The two baseline hashes below were computed offline by replicating
``hash_state``'s recipe in Python on a synthetic-state-shaped data
structure (see ``scripts/parity_smoke.py:hash_state`` + the brief's
``parts`` recipe). Confirmed byte-equal to the Rust ``fingerprint()``
output on the same synthetic state seed — this locks in cross-engine
parity in a way that survives even when one engine lacks the other's
construction primitives.

If either expected baseline drifts, the fingerprint format changed
on one side of the parity bridge — update the offline computation
**and** the parity-smoke ``hash_state`` together (they must stay in
lockstep).
"""

from __future__ import annotations

import re

import pytest


# ---------------------------------------------------------------------------
# Cross-engine parity baselines.
#
# Computed offline by mirroring scripts/parity_smoke.py:hash_state on a
# Python-side data structure that exactly matches the Rust synthetic
# state's gameplay-relevant shape (printings + ids + life + phase).
# See the module docstring for the methodology.
# ---------------------------------------------------------------------------

# `make_synthetic_state()` default args: 10 battlefield, 7 hand, 50 library
# per player. Turn 5, phase 0 (UNTAP), active+priority player 0.
EXPECTED_FINGERPRINT_DEFAULT = "93ab1bd03f94"

# `make_synthetic_state(2, 3, 5)` — 2 battlefield, 3 hand, 5 library per
# player. Smaller state for fast iteration.
EXPECTED_FINGERPRINT_SMALL = "e1d70afe6742"


# ---------------------------------------------------------------------------
# Format + determinism.
# ---------------------------------------------------------------------------


def test_fingerprint_is_12_char_lowercase_hex(synthetic_state):
    """The fingerprint is always 12 lowercase hex characters."""
    fp = synthetic_state.fingerprint()
    assert isinstance(fp, str)
    assert len(fp) == 12
    assert re.fullmatch(r"[0-9a-f]{12}", fp), fp


def test_fingerprint_is_deterministic_back_to_back(synthetic_state):
    """Calling fingerprint twice on an unchanged state returns identical hashes."""
    a = synthetic_state.fingerprint()
    b = synthetic_state.fingerprint()
    assert a == b


def test_fingerprint_is_deterministic_across_runs(engine):
    """Fresh synthetic states with the same seed produce identical hashes
    — proves no time / address / randomness leaks into the digest."""
    s1 = engine.make_synthetic_state()
    s2 = engine.make_synthetic_state()
    assert s1.fingerprint() == s2.fingerprint()


# ---------------------------------------------------------------------------
# Cross-engine parity (regression-safe baseline).
# ---------------------------------------------------------------------------


def test_fingerprint_matches_python_hash_state_default(synthetic_state):
    """Rust ``fingerprint()`` on the default synthetic state equals the
    SHA1 ``scripts/parity_smoke.py:hash_state`` would produce on an
    equivalent Python state. The baseline is computed offline (see
    module docstring) so the test stays self-contained.
    """
    assert synthetic_state.fingerprint() == EXPECTED_FINGERPRINT_DEFAULT


def test_fingerprint_matches_python_hash_state_small(engine):
    """Same cross-engine parity assertion, on the smaller (2,3,5)
    synthetic state — covers a different turn/zone-size shape."""
    s = engine.make_synthetic_state(2, 3, 5)
    assert s.fingerprint() == EXPECTED_FINGERPRINT_SMALL


# ---------------------------------------------------------------------------
# Sensitivity — gameplay changes produce different hashes.
# ---------------------------------------------------------------------------


def test_fingerprint_changes_when_zone_changes(engine):
    """Two synthetic states that differ in hand/library sizes produce
    different fingerprints. (The single most basic sensitivity test —
    if this fails the hash is computing nothing meaningful.)"""
    a = engine.make_synthetic_state(10, 7, 50).fingerprint()
    b = engine.make_synthetic_state(10, 7, 49).fingerprint()
    assert a != b


def test_fingerprint_changes_when_life_changes(synthetic_state):
    """Mutating a player's life changes the fingerprint. Uses
    ``set_life`` (from the life slice)."""
    fp_before = synthetic_state.fingerprint()
    synthetic_state.set_life(0, 15)
    fp_after = synthetic_state.fingerprint()
    assert fp_before != fp_after


# ---------------------------------------------------------------------------
# Clone semantics — the CoW canary.
# ---------------------------------------------------------------------------


def test_fingerprint_clone_preserves(synthetic_state):
    """``state.clone_once()`` produces a clone whose fingerprint matches
    the source. Verifies the clone is bit-equivalent to the source for
    every gameplay-relevant invariant the fingerprint covers."""
    clone = synthetic_state.clone_once()
    assert synthetic_state.fingerprint() == clone.fingerprint()


def test_fingerprint_clone_isolation_after_mutation(synthetic_state):
    """The CoW canary: cloning, then mutating the SOURCE, must leave the
    clone's fingerprint unchanged. If this fails it means the Arc-shared
    zones leaked mutation across the boundary — a critical state-bridge
    bug that would also corrupt parity_smoke's per-decision state hashes.
    """
    clone = synthetic_state.clone_once()
    clone_fp_before = clone.fingerprint()
    # Mutate the source — life change is the cheapest scalar mutation
    # that doesn't touch the zone Arcs.
    synthetic_state.set_life(0, 7)
    clone_fp_after = clone.fingerprint()
    assert clone_fp_before == clone_fp_after
    # And the source's fingerprint actually changed.
    assert synthetic_state.fingerprint() != clone_fp_before


def test_fingerprint_clone_isolation_zone_mutation(synthetic_state, engine):
    """Same CoW canary, but the mutation is a zone-level change.
    Mutates the SOURCE's battlefield (via a Rust primitive that
    triggers ``Arc::make_mut``); the clone's fingerprint must NOT
    change."""
    clone = synthetic_state.clone_once()
    clone_fp_before = clone.fingerprint()
    # `tap_object` (from the tap slice) mutates the battlefield zone
    # via Arc::make_mut. Tap one of player 0's permanents.
    synthetic_state.tap_object(0)  # tap obj_id 0 (a Forest on p0's bf)
    clone_fp_after = clone.fingerprint()
    assert clone_fp_before == clone_fp_after
    # And the source's fingerprint did change.
    assert synthetic_state.fingerprint() != clone_fp_before


# ---------------------------------------------------------------------------
# Additional pinned baselines — broader regression surface.
#
# Round-22 (commit 2ee5597) pinned two synthetic-state fingerprints (default
# args and `(2, 3, 5)`). This block extends that coverage across a wider
# range of zone-size shapes so any accidental drift in the fingerprint
# format — SHA1 truncation length, JSON serialization, zone iteration
# order, per-object 8-tuple shape — surfaces on the first failed assertion
# rather than as a downstream parity-smoke mystery.
#
# Each baseline was computed once by running ``fingerprint()`` on a freshly
# built synthetic state at the noted commit and recording the 12-char hex.
# These are pure regression guards: if any of them flip, the fingerprint
# format moved on the Rust side and the offline Python recipe in this
# module's docstring (plus ``scripts/parity_smoke.py:hash_state``) must
# be updated in lockstep.
# ---------------------------------------------------------------------------


def test_fingerprint_pinned_for_zero_zones(engine):
    """``make_synthetic_state(0, 0, 0)`` — empty battlefield / hand / library
    per side — has pinned fingerprint ``3b17024676c6``. Guards the empty-
    zone code path."""
    s = engine.make_synthetic_state(0, 0, 0)
    assert s.fingerprint() == "3b17024676c6"


def test_fingerprint_pinned_for_one_each(engine):
    """``make_synthetic_state(1, 1, 1)`` — minimal non-empty state — has
    pinned fingerprint ``56d2910a6ac4``."""
    s = engine.make_synthetic_state(1, 1, 1)
    assert s.fingerprint() == "56d2910a6ac4"


def test_fingerprint_pinned_for_three_each(engine):
    """``make_synthetic_state(3, 3, 3)`` — mid-size symmetric state — has
    pinned fingerprint ``e32afdb188c1``."""
    s = engine.make_synthetic_state(3, 3, 3)
    assert s.fingerprint() == "e32afdb188c1"


def test_fingerprint_pinned_for_ten_each(engine):
    """``make_synthetic_state(10, 10, 10)`` — bigger symmetric state — has
    pinned fingerprint ``6ff3d1babb85``. Exercises the digest at scale,
    so any iteration-order regression that only manifests past N>=N0
    surfaces here."""
    s = engine.make_synthetic_state(10, 10, 10)
    assert s.fingerprint() == "6ff3d1babb85"


def test_fingerprint_pinned_for_hand_only(engine):
    """``make_synthetic_state(0, 5, 0)`` — only hands, no battlefield or
    library — has pinned fingerprint ``5c67f92a0cb4``. Isolates the
    hand-zone contribution."""
    s = engine.make_synthetic_state(0, 5, 0)
    assert s.fingerprint() == "5c67f92a0cb4"


def test_fingerprint_pinned_for_battlefield_only(engine):
    """``make_synthetic_state(5, 0, 0)`` — only battlefield, no hand or
    library — has pinned fingerprint ``f9848ca12e57``. Isolates the
    battlefield-zone contribution."""
    s = engine.make_synthetic_state(5, 0, 0)
    assert s.fingerprint() == "f9848ca12e57"


def test_fingerprint_pinned_for_library_only(engine):
    """``make_synthetic_state(0, 0, 5)`` — only library, no battlefield or
    hand — has pinned fingerprint ``f251f42f8647``. Isolates the library-
    zone contribution."""
    s = engine.make_synthetic_state(0, 0, 5)
    assert s.fingerprint() == "f251f42f8647"


def test_fingerprint_pinned_for_asymmetric(engine):
    """``make_synthetic_state(5, 0, 10)`` — asymmetric across zones (5 bf,
    0 hand, 10 lib) — has pinned fingerprint ``6f067c3988bc``. Catches
    regressions where one zone's contribution accidentally bleeds into
    another's slot."""
    s = engine.make_synthetic_state(5, 0, 10)
    assert s.fingerprint() == "6f067c3988bc"


# ---------------------------------------------------------------------------
# Pinned cross-checks: clone preserves, mutation changes.
# ---------------------------------------------------------------------------


def test_fingerprint_pinned_for_clone_matches_source(engine):
    """A ``clone_once()`` of a ``(3, 3, 3)`` synthetic state produces a
    state whose fingerprint exactly equals the source's pinned value
    ``e32afdb188c1``. Pinning the post-clone hash (not just asserting
    source==clone) guards against a regression where BOTH source and
    clone drift in lockstep — which would silently pass the
    ``test_fingerprint_clone_preserves`` style check above."""
    s = engine.make_synthetic_state(3, 3, 3)
    clone = s.clone_once()
    assert clone.fingerprint() == "e32afdb188c1"
    assert s.fingerprint() == clone.fingerprint()


def test_fingerprint_pinned_after_tap_mutation(engine):
    """Tapping the first battlefield permanent on a ``(3, 3, 3)``
    synthetic state shifts the fingerprint from ``e32afdb188c1`` to
    ``e35e82c9b588``. Pinning the post-mutation hash locks in the
    tapped-state contribution to the per-object 8-tuple."""
    s = engine.make_synthetic_state(3, 3, 3)
    assert s.fingerprint() == "e32afdb188c1"
    s.tap_object(0)
    assert s.fingerprint() == "e35e82c9b588"


def test_fingerprint_pinned_after_life_mutation(engine):
    """Lowering player 0's life from the default to 5 on a ``(1, 1, 1)``
    synthetic state shifts the fingerprint from ``56d2910a6ac4`` to
    ``d2435eea284f``. Pinning the post-mutation hash locks in the
    life-field contribution to the per-player digest tuple."""
    s = engine.make_synthetic_state(1, 1, 1)
    assert s.fingerprint() == "56d2910a6ac4"
    s.set_life(0, 5)
    assert s.fingerprint() == "d2435eea284f"
