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


# ---------------------------------------------------------------------------
# Cross-feature edge-case coverage.
#
# This block extends the slice-1 sensitivity tests above with one-per-field
# sensitivity checks (each top-level GameState field and each per-object
# GameObject field) plus parity-load-bearing invariants — order sensitivity
# in zones / stack, order INSENSITIVITY for mana pool, content-vs-allocation
# equality, and cross-feature composition with the ``apply_effect`` family
# of primitives (deal_damage, gain_life, add_mana, add_counters, tap_object).
#
# These are the same digest invariants the 1000-game cross-engine parity
# smoke will rely on — if any of these flips, the parity hash on either
# side has drifted from the other and parity_smoke.py's hash_state needs
# to follow.
# ---------------------------------------------------------------------------


# --- per-field sensitivity (top-level GameState fields) ---------------


def test_fingerprint_sensitive_to_priority_player(synthetic_state):
    """Flipping ``priority_player`` (via ``pass_priority`` — the only
    primitive that touches priority_player WITHOUT also touching
    active_player / phase / turn) must change the fingerprint. Pins
    that the priority_player field flows into the digest."""
    fp_before = synthetic_state.fingerprint()
    synthetic_state.pass_priority()
    fp_after = synthetic_state.fingerprint()
    assert fp_before != fp_after


def test_fingerprint_sensitive_to_phase(synthetic_state):
    """``set_phase`` (the raw-assignment phase setter that does NOT
    touch active_player / turn_number / untap-sweep) shifts the
    fingerprint. Pins that the phase field flows into the digest as
    the ``Step.<NAME>`` string — distinct from active_player /
    turn_number sensitivity tested separately below."""
    fp_before = synthetic_state.fingerprint()
    # Default synthetic phase is UNTAP (0); jump to PRECOMBAT_MAIN (3)
    # — a real phase change with no side-effects on other fields.
    synthetic_state.set_phase(3)
    fp_after = synthetic_state.fingerprint()
    assert fp_before != fp_after


def test_fingerprint_sensitive_to_active_player_and_turn_number(engine):
    """A full turn cycle (12 ``advance_phase`` calls) wraps CLEANUP ->
    UNTAP, which bumps ``turn_number`` AND flips ``active_player``.
    The post-cycle fingerprint must differ from the starting one —
    pins that both fields flow into the digest. (No direct setter
    exists for either field in isolation; this composition test is
    the closest we can get with current primitives.)"""
    a = engine.make_synthetic_state()
    b = engine.make_synthetic_state()
    fp_before = a.fingerprint()
    for _ in range(12):
        b.advance_phase()
    # After one full cycle: turn_number 5 -> 6, active_player 0 -> 1,
    # phase wraps back to UNTAP (0 == default). Three independent
    # field changes; the digest must move.
    assert b.turn_number == a.turn_number + 1
    assert b.active_player != a.active_player
    assert b.fingerprint() != fp_before


# --- per-object sensitivity (GameObject fields inside zones) -----------


def test_fingerprint_sensitive_to_tapped_flag(synthetic_state):
    """``tap_object`` flips the ``tapped`` flag on one battlefield
    permanent — fingerprint must change. Pins the ``int(tapped)``
    slot of the per-object 8-tuple."""
    fp_before = synthetic_state.fingerprint()
    assert synthetic_state.tap_object(0) is True
    fp_after = synthetic_state.fingerprint()
    assert fp_before != fp_after


def test_fingerprint_sensitive_to_damage_stamp(synthetic_state):
    """``deal_damage`` stamps damage onto a battlefield permanent —
    fingerprint must change. Pins the ``damage`` slot of the per-
    object 8-tuple. Cross-feature with the damage slice: any future
    apply_effect DealDamage routes through the same damage-stamp
    primitive."""
    fp_before = synthetic_state.fingerprint()
    # obj_id 0 is a Forest on p0's battlefield in the default seed.
    assert synthetic_state.deal_damage(0, 1) is True
    fp_after = synthetic_state.fingerprint()
    assert fp_before != fp_after


def test_fingerprint_sensitive_to_counters_value(synthetic_state):
    """``set_counters`` writes the ``counters`` slot — fingerprint
    must change. Pins the ``counters`` slot of the per-object 8-tuple.
    Cross-feature with the counters slice / apply_effect's PutCounter
    arms."""
    fp_before = synthetic_state.fingerprint()
    assert synthetic_state.set_counters(0, 1) is True
    fp_after = synthetic_state.fingerprint()
    assert fp_before != fp_after


# --- determinism canary ------------------------------------------------


def test_fingerprint_no_salt_or_time_bits(engine):
    """Stronger determinism canary: build five fresh synthetic states
    in a row and assert ALL five fingerprints are identical. If any
    time-based bit, RNG salt, allocator-address, or interning-id
    leaked into the digest, the runs would diverge across the loop.
    Bigger than ``test_fingerprint_is_deterministic_across_runs``
    (which only compares two) — proves stability across a small
    burst."""
    fps = [engine.make_synthetic_state().fingerprint() for _ in range(5)]
    assert len(set(fps)) == 1, fps


# --- order sensitivity (parity-load-bearing) ---------------------------


def test_fingerprint_sensitive_to_library_order(engine):
    """Swapping the order of two library cards (achieved by moving
    obj 0 out to hand and back to library — which appends to the END
    of the library Vec) produces a different fingerprint. This is
    parity-load-bearing: Python's ``hash_state`` walks the library
    list in iteration order, so any divergence in zone iteration
    order between Python and Rust would surface as silent
    fingerprint mismatch. Pins the order-sensitive shape of
    ``_zone_signature``."""
    ZONE_LIBRARY = 1
    ZONE_HAND = 0
    a = engine.make_synthetic_state(0, 0, 2)
    b = engine.make_synthetic_state(0, 0, 2)
    fp_a = a.fingerprint()
    # In b, take obj 0 from library to hand then back to library —
    # this reverses the per-player library order from [0, 1] to [1, 0].
    assert b.move_object(0, ZONE_HAND, 0) is True
    assert b.move_object(0, ZONE_LIBRARY, 0) is True
    fp_b = b.fingerprint()
    assert fp_a != fp_b


def test_fingerprint_sensitive_to_stack_order(synthetic_state, engine):
    """Two states with the same two stack items in opposite orders
    produce different fingerprints. The Rust stack-signature in
    state_ops_fingerprint.rs walks ``self.stack`` in Vec iteration
    order — Python's hash_state walks its stack list the same way,
    so a swap is observable. Parity-load-bearing: if Python ever
    re-sorted the stack before hashing (or vice versa), this test
    would catch it."""
    sA = engine.make_synthetic_state()
    sB = engine.make_synthetic_state()
    sA.push_to_stack(42, 0)
    sA.push_to_stack(43, 1)
    sB.push_to_stack(43, 1)
    sB.push_to_stack(42, 0)
    assert sA.fingerprint() != sB.fingerprint()


def test_fingerprint_insensitive_to_mana_pool_add_order(engine):
    """The mana pool is sorted by color-key inside the fingerprint
    (Python: ``tuple(sorted({"W":w, ...}.items()))``; Rust: a fixed-
    order 6-element vec keyed B/C/G/R/U/W). Adding {W} then {B}
    produces the same pool content as adding {B} then {W} —
    therefore the same fingerprint. Pins the order-INSENSITIVE
    treatment of the mana pool; if either side switched to an
    insertion-order representation this test would fail."""
    sa = engine.make_synthetic_state()
    sb = engine.make_synthetic_state()
    sa.add_mana(0, "W", 1)
    sa.add_mana(0, "B", 1)
    sb.add_mana(0, "B", 1)
    sb.add_mana(0, "W", 1)
    assert sa.fingerprint() == sb.fingerprint()


# --- clone-replay equality + content-vs-allocation --------------------


def test_fingerprint_clone_replay_equality_after_each_mutation(synthetic_state):
    """``state.clone_once().fingerprint() == state.fingerprint()``
    must hold AT EVERY STEP of a mutation sequence — not just on a
    freshly built state. Pins that the CoW clone is bit-equivalent
    after each in-place write, with no lazily-promoted Arc that
    diverges only after a second mutation."""
    assert synthetic_state.clone_once().fingerprint() == synthetic_state.fingerprint()
    synthetic_state.set_life(0, 17)
    assert synthetic_state.clone_once().fingerprint() == synthetic_state.fingerprint()
    synthetic_state.tap_object(0)
    assert synthetic_state.clone_once().fingerprint() == synthetic_state.fingerprint()
    synthetic_state.add_mana(0, "G", 2)
    assert synthetic_state.clone_once().fingerprint() == synthetic_state.fingerprint()
    synthetic_state.set_counters(0, 3)
    assert synthetic_state.clone_once().fingerprint() == synthetic_state.fingerprint()


def test_fingerprint_content_equality_across_independent_states(engine):
    """Two independently constructed states that reach the same
    gameplay-relevant content via different mutation sequences must
    share a fingerprint — state identity is by content, not by
    allocation or construction history. Pins the load-bearing
    property that an arbitrary parity-smoke run can compare two
    states regardless of how each side got there."""
    # State A: set_life(0, 15) then set_life(1, 18).
    a = engine.make_synthetic_state()
    a.set_life(0, 15)
    a.set_life(1, 18)
    # State B: same end content, opposite mutation order.
    b = engine.make_synthetic_state()
    b.set_life(1, 18)
    b.set_life(0, 15)
    assert a.fingerprint() == b.fingerprint()


# --- cross-feature with the apply_effect-style primitive family -------
#
# The Rust ``apply_effect`` dispatcher (state_ops_resolve.rs) routes each
# Effect variant through these primitives:
#   - DealDamage         -> deal_damage / direct life subtraction
#   - GainLife / LoseLife -> set_life / direct life write
#   - AddManaToPool      -> add_mana
#   - PutCounter family  -> add_counters / set_counters
#   - Tap                -> tap_object
# Each of these must move the fingerprint when called — verifying that the
# downstream effect path through apply_effect will also move it. Single-call
# parametrize-style coverage so a regression on any one primitive surfaces
# independently.


def test_fingerprint_changes_after_deal_damage(synthetic_state):
    """The ``deal_damage`` primitive (the same one apply_effect's
    DealDamage->AnyCreature arm uses) changes the fingerprint."""
    fp_before = synthetic_state.fingerprint()
    synthetic_state.deal_damage(0, 2)
    assert synthetic_state.fingerprint() != fp_before


def test_fingerprint_changes_after_gain_life(synthetic_state):
    """The ``gain_life`` primitive (the same one apply_effect's
    GainLife arm uses) changes the fingerprint."""
    fp_before = synthetic_state.fingerprint()
    synthetic_state.gain_life(0, 3)
    assert synthetic_state.fingerprint() != fp_before


def test_fingerprint_changes_after_add_mana(synthetic_state):
    """The ``add_mana`` primitive (the same one apply_effect's
    AddManaToPool / tap_for_mana paths use) changes the fingerprint."""
    fp_before = synthetic_state.fingerprint()
    synthetic_state.add_mana(0, "G", 1)
    assert synthetic_state.fingerprint() != fp_before


def test_fingerprint_changes_after_add_counters(synthetic_state):
    """The ``add_counters`` primitive (the same one apply_effect's
    PutCounter family routes through) changes the fingerprint."""
    fp_before = synthetic_state.fingerprint()
    assert synthetic_state.add_counters(0, 1) is True
    assert synthetic_state.fingerprint() != fp_before


def test_fingerprint_changes_after_tap_target(synthetic_state):
    """The ``tap_object`` primitive (the same one apply_effect's
    TapTarget arm uses) changes the fingerprint."""
    fp_before = synthetic_state.fingerprint()
    assert synthetic_state.tap_object(0) is True
    assert synthetic_state.fingerprint() != fp_before


def test_fingerprint_changes_through_full_effect_resolution(synthetic_state):
    """End-to-end cross-feature: register a deal-damage spell, push
    it to the stack, then ``resolve_top_of_stack`` (which invokes
    ``apply_effect`` internally). The fingerprint must change at
    each stage — inject (registry + zone), push (stack +1), resolve
    (stack -1 + damage applied + source moved to graveyard). This is
    the integration shape parity-smoke exercises during real games."""
    ZONE_BATTLEFIELD = 2
    bombard = {
        "name": "Test Bombard",
        "card_types": ["Sorcery"],
        "mana_cost": {"R": 1, "generic": 2},
        "effects": [
            {
                "kind": "deal_damage",
                "amount": 3,
                "target": {"kind": "any_player"},
            }
        ],
    }
    fp0 = synthetic_state.fingerprint()
    obj_id = synthetic_state.register_and_inject_object(
        bombard, 0, ZONE_BATTLEFIELD
    )
    fp1 = synthetic_state.fingerprint()
    synthetic_state.push_to_stack(obj_id, 0)
    fp2 = synthetic_state.fingerprint()
    synthetic_state.resolve_top_of_stack()
    fp3 = synthetic_state.fingerprint()
    # All four stages produce distinct fingerprints — the digest
    # tracks every step of the effect-resolution pipeline.
    assert len({fp0, fp1, fp2, fp3}) == 4, (fp0, fp1, fp2, fp3)


# --- regression-detection: re-pin existing baselines ------------------
#
# The two existing pinned baselines (default-args + (2,3,5)) already have
# dedicated tests near the top of the file; this consolidates a sanity
# check that BOTH still match in a single test. Useful as a fast-fail
# trigger — if either drifts the parity-smoke ``hash_state`` recipe in
# scripts/parity_smoke.py must follow.


def test_fingerprint_baselines_still_match(engine):
    """Both Round-22 pinned baselines still match after any subsequent
    Rust-side change — a one-shot regression sentinel guarding the
    cross-engine parity contract. If this fails together with one of
    the slice-1 ``test_fingerprint_matches_python_hash_state_*`` tests,
    the format moved on the Rust side and the offline Python recipe
    + parity_smoke.py:hash_state must be updated in lockstep."""
    default = engine.make_synthetic_state()
    small = engine.make_synthetic_state(2, 3, 5)
    assert default.fingerprint() == EXPECTED_FINGERPRINT_DEFAULT
    assert small.fingerprint() == EXPECTED_FINGERPRINT_SMALL
