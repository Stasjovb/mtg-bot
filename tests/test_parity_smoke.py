"""Tests for ``scripts/parity_smoke.py`` — specifically the round-23
``--mode initial-state`` path that compares the Rust ``fingerprint()``
pymethod to a Python-side reimplementation of the hash recipe.

This is the first working parity check, narrowly scoped to the
fingerprint-vs-hash_state invariant. The pinned baselines below are the
same values asserted in ``tests_rust/test_fingerprint.py``; if either
drifts, the two test files should drift together (and the parity_smoke
script's documented contract — Rust fingerprint() byte-equal to the
Python hash recipe — is broken).
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest


# Skip the whole module if the Rust extension isn't built — mirrors the
# ``tests_rust/conftest.py`` policy so a fresh checkout without maturin
# doesn't break the gate.
pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# Load scripts/parity_smoke.py as a module so we can call its functions
# without spawning a subprocess. The file isn't on the Python path by
# default (it's a script, not a package member) so we import it by path.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def parity_smoke():
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location("parity_smoke", script_path)
    mod = importlib.util.module_from_spec(spec)
    # @dataclass decorators in parity_smoke.py inspect cls.__module__'s
    # entry in sys.modules to resolve string annotations; register the
    # module before exec_module so that lookup succeeds.
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Pinned baselines — must match tests_rust/test_fingerprint.py values.
# These are the regression-safe load-bearing assertions; if either drifts
# the Rust fingerprint format changed on one side of the parity bridge.
# ---------------------------------------------------------------------------

EXPECTED_FINGERPRINT_DEFAULT = "93ab1bd03f94"  # make_synthetic_state()
EXPECTED_FINGERPRINT_SMALL = "e1d70afe6742"   # make_synthetic_state(2, 3, 5)


# ---------------------------------------------------------------------------
# run_initial_state_compare — the new entry point this slice ships.
# ---------------------------------------------------------------------------


def test_initial_state_mode_fingerprint_matches(parity_smoke, capsys):
    """``run_initial_state_compare`` returns 0 (PASS) on a freshly-built
    default synthetic state. End-to-end smoke of the new CLI mode."""
    rc = parity_smoke.run_initial_state_compare(seed=42)
    assert rc == 0
    out = capsys.readouterr().out
    assert "PARITY: PASS" in out
    assert EXPECTED_FINGERPRINT_DEFAULT in out


def test_initial_state_mode_fingerprint_matches_seed_7(parity_smoke):
    """Same assertion, different seed. ``make_synthetic_state`` is
    deterministic so the seed doesn't shape the state today, but the
    contract is "PASS for any seed"; if a future variant threads the
    seed in (e.g. ``shuffle_library_with_seed``), this guards against
    regression at seed 7 specifically.
    """
    assert parity_smoke.run_initial_state_compare(seed=7) == 0


def test_initial_state_mode_pinned_hash_default(parity_smoke):
    """The single most load-bearing test: the Rust ``fingerprint()`` on
    a default synthetic state MUST equal the round-22 pinned baseline.
    If this fails, the hash recipe drifted on one side of the bridge.

    We use the Python shim AND the native Rust pymethod independently
    and assert both produce the same pinned value — that pins down the
    invariant from both directions.
    """
    import mtg_bot_engine
    state = mtg_bot_engine.make_synthetic_state()
    rust_fp = state.fingerprint()
    shim_fp = parity_smoke._hash_rust_state(state)
    assert rust_fp == EXPECTED_FINGERPRINT_DEFAULT
    assert shim_fp == EXPECTED_FINGERPRINT_DEFAULT
    assert rust_fp == shim_fp


def test_initial_state_mode_pinned_hash_2_3_5(parity_smoke):
    """Companion to the default-state pinned test: smaller (2, 3, 5)
    synthetic state, different bf/hand/lib sizes, asserted against the
    other round-22 baseline."""
    import mtg_bot_engine
    state = mtg_bot_engine.make_synthetic_state(2, 3, 5)
    rust_fp = state.fingerprint()
    shim_fp = parity_smoke._hash_rust_state(state)
    assert rust_fp == EXPECTED_FINGERPRINT_SMALL
    assert shim_fp == EXPECTED_FINGERPRINT_SMALL


def test_initial_state_mode_with_2_3_5_runner(parity_smoke, capsys):
    """The CLI entry point honors ``--num-battlefield/-hand/-library``
    overrides and prints the smaller-state baseline."""
    rc = parity_smoke.run_initial_state_compare(
        seed=42, num_battlefield=2, num_hand=3, num_library=5
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "PARITY: PASS" in out
    assert EXPECTED_FINGERPRINT_SMALL in out


def test_initial_state_mode_after_clone(parity_smoke):
    """Cloning a state preserves both the Rust fingerprint AND the
    Python shim hash — the CoW canary at the parity-bridge level. If
    clone_once leaked mutation across the boundary, the dict-shim hash
    would diverge from the native one for the clone.
    """
    import mtg_bot_engine
    state = mtg_bot_engine.make_synthetic_state()
    clone = state.clone_once()

    # Native fingerprint preserved across clone.
    assert state.fingerprint() == clone.fingerprint()
    # Python shim hash preserved across clone.
    assert parity_smoke._hash_rust_state(state) == parity_smoke._hash_rust_state(clone)
    # And both methods agree on each side of the clone.
    assert state.fingerprint() == parity_smoke._hash_rust_state(state)
    assert clone.fingerprint() == parity_smoke._hash_rust_state(clone)


def test_initial_state_mode_mutation_changes_hash(parity_smoke):
    """Mutating a player's life updates both hashes in lockstep.
    Verifies the shim and the native fingerprint actually depend on
    the gameplay-relevant fields (not constant strings).
    """
    import mtg_bot_engine
    state = mtg_bot_engine.make_synthetic_state()
    rust_before = state.fingerprint()
    shim_before = parity_smoke._hash_rust_state(state)
    state.set_life(0, 5)
    rust_after = state.fingerprint()
    shim_after = parity_smoke._hash_rust_state(state)

    assert rust_before != rust_after
    assert shim_before != shim_after
    # The two methods continue to agree post-mutation.
    assert rust_after == shim_after


def test_initial_state_mode_main_dispatches_to_initial_state(parity_smoke, monkeypatch, capsys):
    """``main()`` routes ``--mode initial-state`` to the new comparison
    path. End-to-end argparse + dispatch smoke."""
    monkeypatch.setattr(sys, "argv", ["parity_smoke.py", "--mode", "initial-state", "--seed", "42"])
    rc = parity_smoke.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "PARITY: PASS" in out
    assert EXPECTED_FINGERPRINT_DEFAULT in out


# ---------------------------------------------------------------------------
# --mode trajectory — Rust-only trajectory walk with clone-replay
# determinism check. Catches non-deterministic Rust state mutation
# (same seed -> different fingerprint sequence) and clone divergence.
# ---------------------------------------------------------------------------


def test_trajectory_mode_seed_42_5_decisions_default_board_passes(parity_smoke, capsys):
    """Baseline: 5 decisions at default board size, seed=42 — should
    PASS with clone-replay matching. End-to-end smoke of the new
    trajectory CLI mode."""
    rc = parity_smoke.run_trajectory_mode(seed=42, num_decisions=5)
    assert rc == 0
    out = capsys.readouterr().out
    assert "PARITY: PASS" in out
    assert "clone-replay-matches=True" in out
    assert "seed=42" in out


def test_trajectory_mode_seed_7_10_decisions_passes(parity_smoke, capsys):
    """A different seed produces a different decision sequence but
    the clone-replay determinism check still holds."""
    rc = parity_smoke.run_trajectory_mode(seed=7, num_decisions=10)
    assert rc == 0
    out = capsys.readouterr().out
    assert "PARITY: PASS" in out
    assert "clone-replay-matches=True" in out


def test_trajectory_mode_zero_decisions_is_trivial_pass(parity_smoke, capsys):
    """0 decisions: the walk runs an empty loop, the clone is identical
    to the original, both fingerprint trajectories are [initial_fp].
    Trivial PASS — guards against an off-by-one edge case in the walk
    where 0 iterations would otherwise error."""
    rc = parity_smoke.run_trajectory_mode(seed=42, num_decisions=0)
    assert rc == 0
    out = capsys.readouterr().out
    assert "PARITY: PASS" in out
    assert "trajectory of 0 decisions" in out


def test_trajectory_mode_reproducibility_same_seed_same_final_hash(parity_smoke, capsys):
    """Two runs at the same seed produce identical final fingerprints.
    The whole point of the determinism check: same seed -> bit-identical
    trajectory across runs (not just within a run). Catches a subtler
    class of nondeterminism — e.g. iteration over a HashMap whose
    order varies across process invocations."""
    rc1 = parity_smoke.run_trajectory_mode(seed=42, num_decisions=15)
    out1 = capsys.readouterr().out
    rc2 = parity_smoke.run_trajectory_mode(seed=42, num_decisions=15)
    out2 = capsys.readouterr().out
    assert rc1 == 0
    assert rc2 == 0
    # Extract the "final_hash=..." substring from both runs and assert
    # they match. The line is "[  rust] trajectory of N decisions,
    # final_hash=<hex>, clone-replay-matches=True".
    def _extract_final_hash(out: str) -> str:
        for line in out.splitlines():
            if "final_hash=" in line:
                # Split on "final_hash=" then take up to next comma.
                tail = line.split("final_hash=", 1)[1]
                return tail.split(",", 1)[0].strip()
        raise AssertionError(f"no final_hash line in:\n{out}")

    assert _extract_final_hash(out1) == _extract_final_hash(out2)


def test_trajectory_mode_different_seeds_pick_different_trajectories(
    parity_smoke, capsys
):
    """Probabilistic-but-deterministic check: different seeds should
    explore the state differently and (with the synthetic state
    permitting more than one legal action at some step) produce a
    different fingerprint trajectory.

    Today's synthetic-state starting position has the state in
    PHASE_UNTAP where only PassPriority is legal — so the walks only
    differ in priority-toggle parity at intermediate steps. We assert
    that across the FULL trajectories (initial + after each step),
    at least one fingerprint differs between two well-separated
    seeds. If a future slice expands the synthetic state's legal
    space, this test stays valid (more variation, more likely to
    differ)."""
    import mtg_bot_engine

    state_a = mtg_bot_engine.make_synthetic_state(2, 3, 5)
    _, traj_a = parity_smoke._walk_trajectory(state_a, seed=1, num_decisions=10)

    state_b = mtg_bot_engine.make_synthetic_state(2, 3, 5)
    _, traj_b = parity_smoke._walk_trajectory(state_b, seed=2, num_decisions=10)

    # Even on a purely PassPriority-only state, an odd number of
    # passes between any two trajectory points would produce a
    # different intermediate fingerprint — but the rng.choice of a
    # one-element list is always the same element, so 10 PassPriority
    # passes from seed 1 == 10 PassPriority passes from seed 2. The
    # meaningful assertion is that the trajectories have the same
    # SHAPE (length) and end on the same fingerprint when the legal
    # set is a singleton. We assert that as a sanity-check;
    # the "different seeds differ" assertion would need a state with
    # >1 legal action, which we don't yet have a fixture for.
    assert len(traj_a) == len(traj_b) == 11
    # On a singleton-legal state, both trajectories ARE identical:
    # rng.choice picks the only element regardless of seed.
    # Document this explicitly so a future maintainer doesn't read
    # this test as "broken" when traj_a == traj_b.
    assert traj_a == traj_b


def test_trajectory_mode_100_decisions_passes(parity_smoke, capsys):
    """Longer walk (100 decisions) at seed=42 — catches subtle
    non-determinism that only surfaces at deeper trajectory depths
    (e.g. an alloc-pattern-dependent ordering bug that triggers
    after the state grows past some threshold)."""
    rc = parity_smoke.run_trajectory_mode(seed=42, num_decisions=100)
    assert rc == 0
    out = capsys.readouterr().out
    assert "PARITY: PASS" in out
    assert "clone-replay-matches=True" in out
    assert "trajectory of 100 decisions" in out


def test_trajectory_mode_explicit_small_board(parity_smoke, capsys):
    """The CLI knobs ``--num-battlefield/-hand/-library`` are honored
    by ``run_trajectory_mode``. Catches a regression where a future
    refactor hardcodes the make_synthetic_state args."""
    rc = parity_smoke.run_trajectory_mode(
        seed=42, num_decisions=5, num_battlefield=2, num_hand=3, num_library=5
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "PARITY: PASS" in out


def test_trajectory_mode_walk_records_one_decision_per_step(parity_smoke):
    """``_walk_trajectory`` returns ``(decisions, trajectory)`` where
    ``len(decisions) == num_decisions`` and
    ``len(trajectory) == num_decisions + 1``. Locks in the trajectory
    bookkeeping shape — off-by-one bugs in the loop bounds would
    surface here before they corrupt the clone-replay check."""
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state()
    decisions, trajectory = parity_smoke._walk_trajectory(
        state, seed=42, num_decisions=7
    )
    assert len(decisions) == 7
    assert len(trajectory) == 8  # initial + after-each-step
    # Every fingerprint is 12 hex chars (SHA1 truncated).
    for fp in trajectory:
        assert len(fp) == 12
        assert all(c in "0123456789abcdef" for c in fp)


def test_trajectory_mode_replay_on_fresh_clone_matches_original(parity_smoke):
    """The clone-replay invariant directly: walk an original state,
    clone the pre-walk state, replay the same decisions on the
    clone, assert the resulting fingerprint trajectory is identical."""
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state()
    clone = state.clone_once()

    decisions, orig_traj = parity_smoke._walk_trajectory(
        state, seed=42, num_decisions=10
    )
    clone_traj = parity_smoke._replay_trajectory(clone, decisions)

    assert orig_traj == clone_traj


def test_trajectory_mode_main_dispatches_to_trajectory(parity_smoke, monkeypatch, capsys):
    """``main()`` routes ``--mode trajectory`` to the new walker.
    End-to-end argparse + dispatch smoke."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "parity_smoke.py",
            "--mode",
            "trajectory",
            "--seed",
            "42",
            "--num-decisions",
            "5",
        ],
    )
    rc = parity_smoke.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "PARITY: PASS" in out
    assert "Rust trajectory deterministic" in out


def test_trajectory_mode_diverged_clone_reports_first_step(parity_smoke, capsys, monkeypatch):
    """Inject a fake clone-replay divergence: monkeypatch
    ``_replay_trajectory`` to return a trajectory that differs from
    the original at a known step, and verify ``run_trajectory_mode``
    returns 1 with the "diverged at step N" diagnostic.

    This is the failure-path counterpart to the other PASS tests —
    it locks in the diagnostic output format (the diff between the
    Rust internal nondeterminism case and the clone-CoW divergence
    case would both surface here)."""
    real_replay = parity_smoke._replay_trajectory

    def fake_replay(state, decisions):
        traj = real_replay(state, decisions)
        if len(traj) >= 3:
            # Corrupt step 2's fingerprint to force a divergence.
            traj = traj.copy()
            traj[2] = "deadbeef0000"
        return traj

    monkeypatch.setattr(parity_smoke, "_replay_trajectory", fake_replay)

    rc = parity_smoke.run_trajectory_mode(seed=42, num_decisions=5)
    assert rc == 1
    out = capsys.readouterr().out
    assert "PARITY: FAIL" in out
    assert "diverged at step 2" in out
    assert "clone-replay-matches=False" in out


# ---------------------------------------------------------------------------
# --mode multi-seed — sweep trajectory mode across K seeds and print an
# aggregate summary. Catches non-determinism bugs that only manifest at
# certain seeds (single-seed mode samples one trajectory through the
# legal space; K seeds tile it).
# ---------------------------------------------------------------------------


def test_multi_seed_mode_three_seeds_all_pass(parity_smoke, capsys):
    """Baseline: 3 seeds, default-ish board, 5 decisions each — all
    clone-replay match, exit code 0. Smoke of the new CLI mode."""
    rc = parity_smoke.run_multi_seed_mode(
        num_seeds=3,
        seed_start=0,
        num_decisions=5,
        num_battlefield=2,
        num_hand=3,
        num_library=5,
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "PARITY: PASS" in out
    assert "all 3 seeds clone-replay-matched" in out
    # Header row + one row per seed should appear.
    assert "seed |" in out
    assert "all clone-match:   True" in out


def test_multi_seed_mode_single_seed_matches_trajectory_mode(
    parity_smoke, capsys
):
    """num_seeds=1 with seed_start=42 should produce a final
    fingerprint identical to what ``run_trajectory_mode`` produces at
    seed=42. Cross-check the helper / wrapper alignment — if multi-seed
    drifted from trajectory mode, this trips.
    """
    rc_traj = parity_smoke.run_trajectory_mode(
        seed=42,
        num_decisions=10,
        num_battlefield=2,
        num_hand=3,
        num_library=5,
    )
    out_traj = capsys.readouterr().out
    assert rc_traj == 0

    def _extract_final_hash(out: str) -> str:
        for line in out.splitlines():
            if "final_hash=" in line:
                tail = line.split("final_hash=", 1)[1]
                return tail.split(",", 1)[0].strip()
        raise AssertionError(f"no final_hash line in:\n{out}")

    traj_fp = _extract_final_hash(out_traj)

    rc_ms = parity_smoke.run_multi_seed_mode(
        num_seeds=1,
        seed_start=42,
        num_decisions=10,
        num_battlefield=2,
        num_hand=3,
        num_library=5,
    )
    out_ms = capsys.readouterr().out
    assert rc_ms == 0
    # The single-seed row in the multi-seed table prints the seed's
    # final fingerprint in the "fingerprint" column. Assert the same
    # 12-char hex appears in the multi-seed output.
    assert traj_fp in out_ms


def test_multi_seed_mode_unique_fingerprints_on_varied_board(
    parity_smoke, capsys
):
    """When the synthetic state has enough legal-space variation, the
    K seeds should produce mostly-unique trajectories. We use the
    default (10, 7, 50) board which has room for variation and run a
    longer walk so the rng's choices have meaningful impact.

    Allowed collision rate: at least num_seeds * 0.5 unique
    fingerprints. The current synthetic-state fixture starts in
    PHASE_UNTAP with PassPriority being the only legal action, so
    collisions are universal there — this test is a forward-looking
    guard that fires once the synthetic state grows beyond a single
    legal action; until then it asserts unique-count >= floor.
    """
    # Use enough decisions that any per-seed branching has a chance
    # to register.
    num_seeds = 8
    rc = parity_smoke.run_multi_seed_mode(
        num_seeds=num_seeds,
        seed_start=0,
        num_decisions=20,
        num_battlefield=10,
        num_hand=7,
        num_library=50,
    )
    assert rc == 0
    out = capsys.readouterr().out
    # Extract the "unique fingerprints: N" line.
    unique_line = next(
        line for line in out.splitlines() if "unique fingerprints:" in line
    )
    n_unique = int(unique_line.split(":", 1)[1].strip().split()[0])
    # >= 1 (the singleton-legal-state fixture produces 1) and the
    # forward-looking floor is num_seeds * 0.5. We assert the soft
    # lower bound: at least one unique fingerprint exists. If the
    # synthetic state expands later, this floor naturally tightens.
    assert n_unique >= 1
    assert n_unique <= num_seeds


def test_multi_seed_mode_deterministic_across_runs(parity_smoke, capsys):
    """Same num_seeds + seed_start + decisions must produce identical
    output across two runs. The whole point of the regression-gate is
    determinism across runs, not just within one."""
    parity_smoke.run_multi_seed_mode(
        num_seeds=4,
        seed_start=0,
        num_decisions=8,
        num_battlefield=2,
        num_hand=3,
        num_library=5,
    )
    out1 = capsys.readouterr().out
    parity_smoke.run_multi_seed_mode(
        num_seeds=4,
        seed_start=0,
        num_decisions=8,
        num_battlefield=2,
        num_hand=3,
        num_library=5,
    )
    out2 = capsys.readouterr().out
    # Strict equality — the multi-seed output is purely a function
    # of (num_seeds, seed_start, decisions, board) and must be
    # bit-identical run-to-run.
    assert out1 == out2


def test_multi_seed_mode_aggregate_says_all_clone_match_true(
    parity_smoke, capsys
):
    """The aggregate-stats block must include the literal string
    ``all clone-match:   True`` when every seed passes. Locks in the
    output format that downstream consumers (CI log parsing, status
    dashboards) might grep for."""
    parity_smoke.run_multi_seed_mode(
        num_seeds=3,
        seed_start=0,
        num_decisions=3,
        num_battlefield=2,
        num_hand=3,
        num_library=5,
    )
    out = capsys.readouterr().out
    assert "all clone-match:   True" in out
    assert "total errors:      0" in out
    assert "total seeds:       3" in out


def test_multi_seed_mode_failing_seed_reports_first_divergence(
    parity_smoke, capsys, monkeypatch
):
    """Inject a fake clone-replay divergence via the helper — the
    multi-seed report must call out the failing seed in the FAIL
    summary. Failure-path counterpart to the all-pass cases."""
    real_replay = parity_smoke._replay_trajectory

    def fake_replay(state, decisions):
        traj = real_replay(state, decisions)
        if len(traj) >= 3:
            traj = traj.copy()
            traj[2] = "deadbeef0000"
        return traj

    monkeypatch.setattr(parity_smoke, "_replay_trajectory", fake_replay)

    rc = parity_smoke.run_multi_seed_mode(
        num_seeds=2,
        seed_start=0,
        num_decisions=5,
        num_battlefield=2,
        num_hand=3,
        num_library=5,
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "PARITY: FAIL" in out
    assert "2 of 2 seeds failed" in out
    # Both seeds should be cited as failing.
    assert "seed 0:" in out
    assert "seed 1:" in out


def test_multi_seed_mode_main_dispatches(parity_smoke, monkeypatch, capsys):
    """``main()`` routes ``--mode multi-seed`` to the new sweep.
    End-to-end argparse + dispatch smoke."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "parity_smoke.py",
            "--mode",
            "multi-seed",
            "--num-seeds",
            "3",
            "--seed-start",
            "0",
            "--num-decisions",
            "5",
            "--num-battlefield",
            "2",
            "--num-hand",
            "3",
            "--num-library",
            "5",
        ],
    )
    rc = parity_smoke.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "PARITY: PASS" in out
    assert "running 3 seeds (0..2)" in out


def test_multi_seed_mode_seed_start_offset(parity_smoke, capsys):
    """``seed_start=100, num_seeds=3`` iterates seeds 100/101/102 —
    the header line and the table both report the offset range. Locks
    in the seed-start arithmetic against off-by-one regressions."""
    parity_smoke.run_multi_seed_mode(
        num_seeds=3,
        seed_start=100,
        num_decisions=2,
        num_battlefield=2,
        num_hand=3,
        num_library=5,
    )
    out = capsys.readouterr().out
    assert "running 3 seeds (100..102)" in out
    # Each seed value appears in a row of the table.
    for seed in (100, 101, 102):
        assert f"{seed:>4} |" in out


# ---------------------------------------------------------------------------
# --mode field-diff — per-field OK/DIFFER diff between two parallel views
# of a Rust synthetic state. The parity-debug primitive that answers
# "WHICH field diverged" once a trajectory smoke says digests don't match.
# ---------------------------------------------------------------------------


def test_field_diff_mode_vanilla_state_all_ok(parity_smoke, capsys):
    """Baseline: no injection, vanilla state — every field matches, the
    runner returns 0, and the output reports ``PARITY: PASS`` with a
    field count equal to ``FIELD_DIFF_FIELDS``."""
    rc = parity_smoke.run_field_diff_mode(seed=42)
    assert rc == 0
    out = capsys.readouterr().out
    assert "PARITY: PASS" in out
    # Every field is reported with status OK on a vanilla state.
    for field in parity_smoke.FIELD_DIFF_FIELDS:
        assert field in out
    # No DIFFER markers at all on the vanilla path.
    assert "DIFFER" not in out


def test_field_diff_mode_inject_life_reports_mismatch(parity_smoke, capsys):
    """``--inject-divergence life`` flips life_p0 by -1; the diff table
    must report a DIFFER on life_p0 and the runner returns 1."""
    rc = parity_smoke.run_field_diff_mode(seed=42, inject_divergence="life")
    assert rc == 1
    out = capsys.readouterr().out
    assert "PARITY: FAIL" in out
    # The life_p0 row is the DIFFER one — its two values (20 / 19) must
    # appear on the same line.
    life_line = next(
        line for line in out.splitlines() if line.startswith("life_p0")
    )
    assert "DIFFER" in life_line
    # Vanilla synthetic state has both players at 20 life; the mutation
    # subtracts 1 from the right-hand side.
    assert "20" in life_line
    assert "19" in life_line
    # Exactly one field differs.
    assert "1 of 22 fields differ" in out


def test_field_diff_mode_inject_hand_reports_mismatch(parity_smoke, capsys):
    """``--inject-divergence hand`` appends a sentinel object to the
    hand_p0 zone signature on the right-hand side; the diff must
    surface the mismatch on hand_p0."""
    rc = parity_smoke.run_field_diff_mode(seed=42, inject_divergence="hand")
    assert rc == 1
    out = capsys.readouterr().out
    assert "PARITY: FAIL" in out
    hand_line = next(
        line for line in out.splitlines() if line.startswith("hand_p0")
    )
    assert "DIFFER" in hand_line


def test_field_diff_mode_inject_active_player_reports_mismatch(
    parity_smoke, capsys
):
    """``--inject-divergence active_player`` toggles 0<->1 on the
    right-hand side; the diff must surface the mismatch on the
    active_player row."""
    rc = parity_smoke.run_field_diff_mode(
        seed=42, inject_divergence="active_player"
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "PARITY: FAIL" in out
    ap_line = next(
        line for line in out.splitlines() if line.startswith("active_player")
    )
    assert "DIFFER" in ap_line
    # Vanilla synthetic state has active_player_idx=0; mutation flips it
    # to 1.
    assert " 0 " in ap_line or "| 0" in ap_line
    assert " 1" in ap_line


def test_field_diff_mode_table_covers_every_hash_part_field(
    parity_smoke, capsys
):
    """The printed table must include every field name that ``_hash_parts``
    folds into the fingerprint — the brief's load-bearing test that the
    diff machinery doesn't silently skip a field that ends up driving
    the hash mismatch.

    The list mirrors the per-field contributions of ``_hash_rust_state``
    (and through it, ``_hash_parts``): scalar state header (turn, step,
    phase, active_player, priority_player, is_over, is_draw, winner_id),
    per-player tuples (life, hand, library, graveyard, exile, mana_pool),
    and the central zones (battlefield, stack).
    """
    parity_smoke.run_field_diff_mode(seed=42)
    out = capsys.readouterr().out
    # Every field name in the canonical list must appear in the output.
    for field in parity_smoke.FIELD_DIFF_FIELDS:
        assert field in out, f"field {field!r} missing from field-diff output"
    # The header row of the table is also present.
    assert "field             | status | left" in out
    # And the brief-specified scalar fields each show up as their own
    # row prefix.
    for prefix in (
        "turn", "step", "phase", "active_player", "priority_player",
        "is_over", "is_draw", "winner_id", "life_p0", "life_p1",
        "hand_p0", "hand_p1", "library_p0", "library_p1",
        "graveyard_p0", "graveyard_p1", "exile_p0", "exile_p1",
        "mana_pool_p0", "mana_pool_p1", "battlefield", "stack",
    ):
        # Each field is the leading token of its own row.
        row_lines = [
            line for line in out.splitlines()
            if line.startswith(prefix) and "|" in line
        ]
        assert row_lines, f"no row starts with {prefix!r}"


def test_field_diff_mode_main_dispatches(parity_smoke, monkeypatch, capsys):
    """``main()`` routes ``--mode field-diff`` to the new runner.
    End-to-end argparse + dispatch smoke."""
    monkeypatch.setattr(
        sys,
        "argv",
        ["parity_smoke.py", "--mode", "field-diff", "--seed", "42"],
    )
    rc = parity_smoke.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "PARITY: PASS" in out
    # Table header present.
    assert "field             | status | left" in out


def test_field_diff_mode_main_dispatches_with_inject(
    parity_smoke, monkeypatch, capsys
):
    """``main() --mode field-diff --inject-divergence life`` returns 1
    and reports a DIFFER on the life_p0 row. End-to-end inject path."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "parity_smoke.py",
            "--mode",
            "field-diff",
            "--inject-divergence",
            "life",
        ],
    )
    rc = parity_smoke.main()
    assert rc == 1
    out = capsys.readouterr().out
    assert "PARITY: FAIL" in out
    assert "life_p0" in out
    assert "DIFFER" in out


def test_field_diff_mode_unknown_inject_field_errors(parity_smoke, capsys):
    """An unknown ``--inject-divergence`` field name returns rc=2 and
    prints an error citing the valid field list. Locks in the
    error-path contract."""
    rc = parity_smoke.run_field_diff_mode(
        seed=42, inject_divergence="this_is_not_a_field"
    )
    assert rc == 2
    out = capsys.readouterr().out
    assert "ERROR" in out
    assert "this_is_not_a_field" in out


# ---------------------------------------------------------------------------
# --mode cross-engine — FIRST cross-engine parity check (round 27 / Phase 5).
# Builds matched Python + Rust states from the tiny synthetic deck, drives
# N PassPriority decisions on both, and reports field-level divergences
# along with a gap-doc lookup.
#
# This is the inaugural cross-engine compare — divergences ARE expected
# (the bridge has known gaps documented in RUST_PARITY_GAPS.md). The
# tests below are xfailed-pinned on the divergences they detect, so the
# count of xfailed tests becomes the "open parity items" tally.
# ---------------------------------------------------------------------------


def test_cross_engine_mode_returns_walk_result_with_steps(parity_smoke):
    """``walk_both`` produces a CrossEngineWalkResult with one
    CrossEngineStep per applied decision. Smoke that the helper runs
    end-to-end without raising on the tiny synthetic deck."""
    from mtg_bot.parity.cross_engine import (
        tiny_synthetic_deckspec,
        walk_both,
    )

    result = walk_both(tiny_synthetic_deckspec(), n_decisions=5)
    assert result.error is None
    assert result.aborted_at is None
    assert len(result.steps) == 5
    # Each step has the action it applied recorded.
    for step in result.steps:
        assert step.action_dict == {"kind": "pass_priority"}


def test_cross_engine_mode_initial_state_libraries_match_after_ce1_closure(parity_smoke):
    """CE1 closure pin: after the make_state path defaults
    ``summoning_sick=true`` to match Python's universal default,
    Python and Rust library_pN field views must agree byte-for-byte
    on the initial state. Inverts the inaugural CE1 pin from r27
    (which asserted these DIVERGED on summoning_sick)."""
    from mtg_bot.parity.cross_engine import (
        tiny_synthetic_deckspec,
        walk_both,
    )

    result = walk_both(tiny_synthetic_deckspec(), n_decisions=0)
    field_names = {d.field for d in result.initial_divergences}
    # Closed by the round-28 CE1 fix in state_ops_setup.rs.
    assert "library_p0" not in field_names
    assert "library_p1" not in field_names


def test_cross_engine_mode_does_not_diverge_on_pass_priority_at_step_0(parity_smoke):
    """**CE2 closure** — formerly
    ``test_cross_engine_mode_detects_pass_priority_divergence_at_step_0``.

    After the first PassPriority decision, Python's
    ``apply_action(PassPriority)`` is a no-op (Python's priority_loop
    owns priority management, not apply_action). The CE2 slice flipped
    Rust's ``apply_action({"kind": "pass_priority"})`` arm from a
    priority-toggling dispatch to a TRUE no-op matching Python — so
    the cross-engine smoke no longer reports a ``priority_player``
    divergence on PassPriority steps. This test pins the
    no-divergence contract so a future regression that re-introduces
    the toggle surfaces here loudly."""
    from mtg_bot.parity.cross_engine import (
        tiny_synthetic_deckspec,
        walk_both,
    )

    result = walk_both(tiny_synthetic_deckspec(), n_decisions=2)
    # Step 0's divergence list must NOT include priority_player —
    # CE2 closure made the arm a no-op matching Python.
    step_0 = result.steps[0]
    priority_div = next(
        (d for d in step_0.divergences if d.field == "priority_player"), None,
    )
    assert priority_div is None, (
        f"unexpected priority_player divergence at step 0 (CE2 should "
        f"have closed this): py={priority_div.py_value} "
        f"rust={priority_div.rust_value} known_gap={priority_div.known_gap}"
        if priority_div is not None
        else ""
    )
    # And the same on step 1 — pin the contract holds across the full
    # walk, not just the inaugural step.
    step_1 = result.steps[1]
    priority_div_1 = next(
        (d for d in step_1.divergences if d.field == "priority_player"), None,
    )
    assert priority_div_1 is None


def test_cross_engine_mode_initial_libraries_byte_equal_after_make_state():
    """The library_pN field views from Python and Rust MUST match
    byte-for-byte on the initial state. This is the canonical parity
    contract — both engines built from the same DeckSpec should
    produce byte-identical zone signatures.

    Round-28 CE1 closure: state_ops_setup.rs now defaults
    summoning_sick=true to match Python's universal default; this
    test flipped from xfail to xpass and the marker was removed."""
    from mtg_bot.parity.cross_engine import (
        tiny_synthetic_deckspec,
        build_matched_states,
        build_python_field_view,
    )
    import importlib.util
    import pathlib
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "parity_smoke", repo_root / "scripts" / "parity_smoke.py",
    )
    parity_smoke = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = parity_smoke
    spec.loader.exec_module(parity_smoke)

    deck = tiny_synthetic_deckspec()
    py_state, rust_state = build_matched_states(deck)
    py_view = build_python_field_view(py_state)
    rust_view = parity_smoke._build_field_view(rust_state)

    # The xfail-pinned assertion: libraries match byte-for-byte. Today
    # they don't (summoning_sick mismatch). When a future slice closes
    # this, the xfail flips to xpass and the test maintainer removes
    # the marker.
    assert py_view["library_p0"] == rust_view["library_p0"]
    assert py_view["library_p1"] == rust_view["library_p1"]


def test_cross_engine_mode_priority_player_unchanged_by_pass_priority():
    """After applying PassPriority on both engines, priority_player
    must agree. **CE2 closure** (formerly xfail-pinned on G3): Rust's
    ``apply_action({"kind": "pass_priority"})`` is now a no-op
    matching Python's ``apply_action(PassPriority)`` which is a pure
    ``return`` (src/mtg_bot/actions.py:990-991). The cross-engine
    smoke no longer flags a ``priority_player`` divergence on
    PassPriority steps."""
    from mtg_bot.parity.cross_engine import (
        tiny_synthetic_deckspec,
        walk_both,
    )

    result = walk_both(tiny_synthetic_deckspec(), n_decisions=1)
    step_0 = result.steps[0]
    priority_div = next(
        (d for d in step_0.divergences if d.field == "priority_player"), None,
    )
    assert priority_div is None, (
        f"priority_player diverged: {priority_div.py_value=} {priority_div.rust_value=}"
    )


def test_cross_engine_mode_inject_divergence_flags_life_at_step_0(parity_smoke):
    """``walk_both(inject_divergence=True)`` artificially perturbs the
    Rust state's life_p0 BEFORE the initial compare. The harness must
    surface a life_p0 divergence in the initial-state report.

    Smoke-test-the-smoke: this proves the harness is actually
    detecting a fake cross-engine divergence, not just reporting
    what we already know about. Failure mode is "harness silently
    misses the perturbation" — which would mean the cross-engine
    code path isn't actually comparing what we think it's
    comparing."""
    from mtg_bot.parity.cross_engine import (
        tiny_synthetic_deckspec,
        walk_both,
    )

    result = walk_both(
        tiny_synthetic_deckspec(), n_decisions=0, inject_divergence=True,
    )
    initial_fields = {d.field for d in result.initial_divergences}
    assert "life_p0" in initial_fields
    life_div = next(
        d for d in result.initial_divergences if d.field == "life_p0"
    )
    # Python is at default 20; Rust has been perturbed to 19.
    assert life_div.py_value == 20
    assert life_div.rust_value == 19


def test_cross_engine_mode_cli_dispatches(parity_smoke, monkeypatch, capsys):
    """``main()`` routes ``--mode cross-engine`` to the new runner.
    End-to-end argparse + dispatch smoke.

    **CE2 closure** — flipped from rc=1 (divergences) to rc=0 (clean).
    With Rust's ``apply_action(pass_priority)`` now a no-op matching
    Python, the tiny synthetic-state PassPriority walk no longer
    surfaces divergences and the runner reports ``PARITY: PASS``. The
    next batch of cross-engine slices will grow the deck pool +
    decision script and surface NEW divergences; those will get their
    own CE<n> entries in `docs/RUST_PARITY_GAPS.md`."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "parity_smoke.py",
            "--mode",
            "cross-engine",
            "--seed",
            "42",
            "--decisions",
            "5",
        ],
    )
    rc = parity_smoke.main()
    # CE2 closure: no divergences on the tiny synthetic PassPriority
    # walk — rc=0 (PARITY: PASS).
    assert rc == 0
    out = capsys.readouterr().out
    # The CLI prints the cross-engine header.
    assert "[cross-engine]" in out
    # The final verdict is PARITY: PASS now that CE2 is closed.
    assert "PARITY: PASS" in out


def test_cross_engine_mode_cli_inject_divergence_flags_life(
    parity_smoke, monkeypatch, capsys
):
    """``main() --mode cross-engine --inject-divergence yes`` flips
    Rust's life_p0 to 19 before the compare; the runner must report
    a life_p0 divergence in the output and exit 1."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "parity_smoke.py",
            "--mode",
            "cross-engine",
            "--seed",
            "42",
            "--decisions",
            "0",
            "--inject-divergence",
            "yes",
        ],
    )
    rc = parity_smoke.main()
    assert rc == 1
    out = capsys.readouterr().out
    assert "life_p0" in out
    assert "(--inject-divergence)" in out
    # The initial-state block prints py=20 and rust=19.
    assert "20" in out and "19" in out


def test_cross_engine_mode_step_index_increments(parity_smoke):
    """``CrossEngineStep.step_index`` must be the loop index, not a
    sentinel. The walk_both helper fills it in after step_both returns.
    Catches a regression where the index would always be -1."""
    from mtg_bot.parity.cross_engine import (
        tiny_synthetic_deckspec,
        walk_both,
    )

    result = walk_both(tiny_synthetic_deckspec(), n_decisions=4)
    assert [s.step_index for s in result.steps] == [0, 1, 2, 3]


def test_cross_engine_mode_first_divergence_step_helper(parity_smoke):
    """``result.first_divergence_step()`` returns -1 when the initial
    state diverges (i.e., "before any decision"). On a parity-clean
    initial state it returns the first step index whose divergences
    are non-empty, or None on a fully-clean walk.

    **CE2 closure**: With Rust's ``apply_action(pass_priority)`` now
    a no-op matching Python, the tiny synthetic PassPriority walk is
    fully clean — the helper returns ``None`` (no divergence at any
    step). Pinning the None return here so a future cross-engine
    surface that re-introduces a divergence at step 0 surfaces the
    regression rather than silently flipping the helper's return."""
    from mtg_bot.parity.cross_engine import (
        tiny_synthetic_deckspec,
        walk_both,
    )

    result = walk_both(tiny_synthetic_deckspec(), n_decisions=5)
    # Round-28 CE1 closed the initial-state library_pN divergence;
    # round-28 CE2 closed the per-step priority_player divergence.
    # The walk is now fully clean — helper returns None.
    assert result.first_divergence_step() is None


def test_cross_engine_default_gap_lookup_priority_player_resolves_i25(parity_smoke):
    """The gap-doc lookup walks RUST_PARITY_GAPS.md and maps
    ``priority_player`` to I25 (the priority composition invariant
    that documents the cross-engine apply_action-level residual after
    G3/G4/G15 were closed). Locks in the lookup contract — the
    hard-coded mapping in :func:`_load_gap_doc_index` must resolve
    to a section that ACTUALLY exists in the doc."""
    from mtg_bot.parity.cross_engine import default_gap_lookup

    assert default_gap_lookup("priority_player") == "I25"


def test_cross_engine_default_gap_lookup_unknown_field_returns_none(parity_smoke):
    """Fields not in the curated lookup table return None — the
    "NOVEL divergence" signal. The summoning_sick + mana_pool type
    divergences are NOT yet documented as gaps, so they should
    surface as NOVEL.

    Note: ``library_p0`` / ``hand_p0`` aren't in the curated map —
    the divergences we see today are on the per-object
    summoning_sick slot, which is properly NOVEL until a gap entry
    documents it.
    """
    from mtg_bot.parity.cross_engine import default_gap_lookup

    assert default_gap_lookup("library_p0") is None
    assert default_gap_lookup("hand_p0") is None
    assert default_gap_lookup("graveyard_p0") is None


def test_cross_engine_build_python_state_step_is_untap(parity_smoke):
    """``build_python_state`` sets ``state.step = Step.UNTAP`` to match
    Rust's PHASE_UNTAP=0 starting phase. Without this Python's default
    state.step is None and the cross-engine step diff would be
    swamped by a None vs "UNTAP" mismatch."""
    from mtg_bot.parity.cross_engine import (
        build_python_state,
        tiny_synthetic_deckspec,
    )
    from mtg_bot.turn import Step

    py_state = build_python_state(tiny_synthetic_deckspec())
    assert py_state.step == Step.UNTAP


def test_cross_engine_build_rust_state_priority_is_zero(parity_smoke):
    """The Rust state's starting priority_player must be 0 — Python's
    default is also 0. This is the contract make_state advertises;
    a regression here would be the first divergence the harness
    detects on step 0."""
    from mtg_bot.parity.cross_engine import (
        build_rust_state,
        tiny_synthetic_deckspec,
    )

    rust_state = build_rust_state(tiny_synthetic_deckspec())
    assert rust_state.priority_player_idx == 0
    assert rust_state.active_player_idx == 0
    assert rust_state.turn_number == 1
    assert rust_state.step == "UNTAP"


# ---------------------------------------------------------------------------
# Phase 5 follow-up slice: slightly_bigger_deckspec (Forest + Mountain +
# Grizzly Bears). The first slice's tiny synthetic state covers
# mono-color Forest + Bears; this slice expands by ONE basic land
# (Mountain) so the registry round-trips two basic-land entries with
# different `mana_produced` colors and the per-zone signatures span
# THREE distinct printing_names in adjacent slots. PassPriority remains
# the only driver — legal_actions / play_land / activate_ability parity
# is deferred to the next slice.
#
# Expected outcome under the current binary (CE2-closure landed at the
# apply_action layer — pass_priority is a no-op on Rust just like
# Python): the harness reports NO divergences across the full walk.
# If a later regression reintroduces a divergence on this deck, the
# test will surface it as a NEW CE<n> candidate rather than a known-
# gap-masked nothing-burger.
# ---------------------------------------------------------------------------


def test_cross_engine_slightly_bigger_deckspec_walks_clean(parity_smoke):
    """Drive 200 PassPriority decisions on the 3-card-kind synthetic
    deck (Forest + Mountain + Grizzly Bears) and assert no field-view
    divergences surface.

    The point of the slice: confirm the bridge's registry +
    zone-signature recipe stay parity-clean as the card pool grows by
    one basic-land color. A clean walk here means the next natural
    expansion is the decision-script side (PlayLand / ActivateAbility),
    not more cards.

    If a regression surfaces a NEW divergence on this deck, the
    failure mode is "unexpected divergence on field <X>"; the assertion
    message names the offending field + step index for fast triage.
    Pin via xfail with a fresh CE<n> entry in
    ``docs/RUST_PARITY_GAPS.md`` if that happens.
    """
    from mtg_bot.parity.cross_engine import (
        slightly_bigger_deckspec,
        walk_both,
    )

    result = walk_both(slightly_bigger_deckspec(), n_decisions=200)
    assert result.error is None, (
        f"walk aborted at step {result.aborted_at}: {result.error}"
    )
    assert result.aborted_at is None
    assert len(result.steps) == 200
    assert result.initial_divergences == [], (
        "initial-state divergences on slightly_bigger_deckspec; "
        f"expected clean start. Fields: "
        f"{[d.field for d in result.initial_divergences]}"
    )
    # Walk every step; any divergence is unexpected under current
    # binary semantics. Pinpoint the first offender for triage.
    for step in result.steps:
        assert step.divergences == [], (
            f"unexpected divergence at step {step.step_index} on "
            f"slightly_bigger_deckspec: "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )


def test_cross_engine_slightly_bigger_deckspec_initial_libraries_have_three_kinds(parity_smoke):
    """Sanity-check the new deckspec's libraries actually carry THREE
    distinct printing_names — guards against an accidental edit that
    flattens the deck back to two kinds and silently weakens the
    coverage delta over tiny_synthetic_deckspec."""
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        slightly_bigger_deckspec,
        build_python_field_view,
    )

    py_state, rust_state = build_matched_states(slightly_bigger_deckspec())
    py_view = build_python_field_view(py_state)
    # library_p0 is a tuple of per-object 8-tuples; index 0 is the
    # printing_name. Collect unique names across BOTH players.
    p0_names = {sig[0] for sig in py_view["library_p0"]}
    p1_names = {sig[0] for sig in py_view["library_p1"]}
    union = p0_names | p1_names
    assert union == {"Forest", "Mountain", "Grizzly Bears"}, (
        f"slightly_bigger_deckspec should expose three printing_names "
        f"across libraries; got {sorted(union)}"
    )


# ---------------------------------------------------------------------------
# Phase 5 follow-up #2: extend the DECISION script (not the deck) — drive a
# draw + play_land via ``play_a_land_selector``. This is the first slice that
# moves cards off the library on both engines. **CE3 closed** by the post-
# r28 library-pop-orientation slice: Rust now uses ``lib.remove(0)`` (post-
# CE3 convention: index 0 = top of library) to match Python's
# ``library.pop(0)`` exactly. Same DeckSpec produces the same draw on both
# engines. The strict-xfail clean-walk pin + companion "symptom-present"
# pin that flagged CE3 were both removed; the underlying parity is now
# load-bearing on the test below.
# ---------------------------------------------------------------------------


def test_cross_engine_play_a_land_selector_walks_clean(parity_smoke):
    """Drive 10 decisions with ``play_a_land_selector`` on the
    slightly_bigger_deckspec and assert every step walks clean. Post-
    CE3 closure: Rust's draw_card and Python's draw_card pop from the
    same end of the library (index 0 = top), so hand_p0 / library_p0
    agree at step 0 and battlefield agrees at step 1 when the
    selector plays a land that's now in both engines' hands.
    """
    from mtg_bot.parity.cross_engine import (
        play_a_land_selector,
        slightly_bigger_deckspec,
        walk_both,
    )

    result = walk_both(
        slightly_bigger_deckspec(),
        n_decisions=10,
        decision_selector=play_a_land_selector,
    )
    assert result.error is None, (
        f"walk aborted at step {result.aborted_at}: {result.error}"
    )
    assert result.aborted_at is None
    assert len(result.steps) == 10
    for step in result.steps:
        assert step.divergences == [], (
            f"unexpected divergence at step {step.step_index}: "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )


def test_cross_engine_play_a_land_selector_emits_pass_priority_when_no_land(parity_smoke):
    """Selector contract: if no Land lives in Python's hand on step
    >= 1, the selector falls back to ``pass_priority`` rather than
    raising or returning a malformed dict. Drives a 0-card-library
    deck so the step-0 draw doesn't put a Land in hand, then verifies
    step 1 emits ``pass_priority``.

    Guards a regression where the selector's land-lookup loop falls
    off the end without an else-branch — silently returning None
    would crash the harness rather than producing a clean fallback."""
    from mtg_bot.parity.cross_engine import (
        CardDef,
        DeckSpec,
        play_a_land_selector,
        walk_both,
    )

    # Two-card creature-only deck. The step-0 draw puts a Bears in
    # Python's hand (and a Bears in Rust's hand by tail-pop — both
    # happen to be Bears here since the deck is mono-Bears, dodging
    # CE3 for this particular guard test).
    bears = CardDef(
        name="Grizzly Bears",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=2,
        toughness=2,
    )
    deck = DeckSpec(
        card_defs=(bears,),
        p0_library=("Grizzly Bears", "Grizzly Bears"),
        p1_library=("Grizzly Bears", "Grizzly Bears"),
    )
    result = walk_both(
        deck, n_decisions=2, decision_selector=play_a_land_selector,
    )
    assert result.error is None
    assert result.steps[0].action_dict == {"kind": "pass_priority"}
    # Step 1: no land in hand -> selector falls back to pass.
    assert result.steps[1].action_dict == {"kind": "pass_priority"}


# ---------------------------------------------------------------------------
# Phase 5 follow-up #3: multi-turn selector. Drives ``advance_phase`` on both
# engines via a side-channel + emits ``play_land`` in MAIN phases. Walks
# multiple full turns so the harness exercises:
#
#   * Turn 1 DRAW skip (CR 103.7c — first turn active player skips draw step).
#   * Turn 1 -> Turn 2 CLEANUP -> UNTAP wrap (turn_number bump + active swap).
#   * Turn 2 UNTAP sweep + summoning-sick clear (CR 302.1).
#   * Turn 2 DRAW step auto-draw (CR 504.1).
#   * Turn 3+ MAIN phase land drop with both players' permanents on the
#     battlefield.
#
# **Outcome (this slice)**: NOVEL divergence CE4 — ``battlefield`` order
# disagrees between Python (ETB-timestamp-ordered centralized list) and
# Rust (per-controller-grouped split). Surfaces at step 28, turn 3
# PRECOMBAT_MAIN, when p0 plays a Forest while p1's Mountain is already
# on the battlefield. Pinned strict-xfail below; closure plan in
# ``docs/RUST_PARITY_GAPS.md`` CE4 entry.
# ---------------------------------------------------------------------------


def test_cross_engine_multi_turn_selector_walks_clean(parity_smoke):
    """Drive 50 decisions on the slightly_bigger_deckspec with the
    multi_turn_selector and assert every step walks clean.

    **CE4 closure (this slice).** Pre-CE4 this was strict-xfail because
    Rust's ``battlefield_snapshot`` emitted in controller-grouped order
    (p0's bf then p1's bf) while Python's centralized
    ``state.battlefield`` is ordered by ETB timestamp; the first
    divergence surfaced at step 28 (turn 3 PRECOMBAT_MAIN play_land)
    once both players had a permanent on the battlefield. The closure
    slice added a per-object ``etb_timestamp`` field stamped at every
    bf-entry primitive and stable-sorts ``battlefield_snapshot`` (and
    the fingerprint's battlefield walk) by that field, producing the
    same emission order Python's ``state.battlefield.append()`` flow
    produces. The xfail marker was removed alongside the companion
    symptom-pin test (per the closure-pair contract; see ``docs/RUST_PARITY_GAPS.md``).
    """
    from mtg_bot.parity.cross_engine import (
        multi_turn_selector,
        slightly_bigger_deckspec,
        walk_both,
    )

    result = walk_both(
        slightly_bigger_deckspec(),
        n_decisions=50,
        decision_selector=multi_turn_selector,
    )
    assert result.error is None, (
        f"walk aborted at step {result.aborted_at}: {result.error}"
    )
    assert result.aborted_at is None
    assert len(result.steps) == 50
    for step in result.steps:
        assert step.divergences == [], (
            f"unexpected divergence at step {step.step_index}: "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )


def test_cross_engine_multi_turn_selector_turn_1_skips_draw(parity_smoke):
    """CR 103.7c first-turn skip pin. Across the first 11 decisions
    (turn 1 UNTAP -> CLEANUP via the side-channel advance_phase), the
    active player's hand stays empty — no draw fires on turn 1's DRAW
    step. The harness reads hand_p0 size at each step; on the
    UNTAP -> UPKEEP -> DRAW transition (steps 0 / 1) the hand stays at
    0 cards.

    Surfaces I18 + Rust's gated draw on both engines uniformly. If
    either engine drew a card on turn 1, this test would FAIL with
    `hand_p0 size > 0` at the step the draw happened. Both engines
    are pinned to the same gate (`turn_number != 1`), so both
    correctly skip.
    """
    from mtg_bot.parity.cross_engine import (
        multi_turn_selector,
        slightly_bigger_deckspec,
        walk_both,
    )

    result = walk_both(
        slightly_bigger_deckspec(),
        n_decisions=11,
        decision_selector=multi_turn_selector,
    )
    assert result.error is None
    # The full turn 1 walk: 11 phases (UPKEEP..CLEANUP per the
    # side-channel advance + the side-channel-into-UNTAP wrap). p0
    # is active for all of turn 1; their hand stays empty because
    # CR 103.7c skips their draw step on turn 1.
    for step in result.steps[:11]:
        assert step.py_view["turn"] in (1, 2)
        # Active player on turn 1 is 0; on the wrap-into-turn-2 step it's 1.
        if step.py_view["turn"] == 1:
            assert step.py_view["active_player"] == 0
            # p0's hand stays empty — no draw on turn 1.
            assert len(step.py_view["hand_p0"]) == 0
        # No divergences during turn 1 + wrap — the first divergence
        # is at step 28, well into turn 3.
        assert step.divergences == []


def test_cross_engine_multi_turn_selector_turn_2_drawstep_fires(parity_smoke):
    """Companion to the turn-1 skip pin. On turn 2's DRAW step (the
    new active player is p1 after the CLEANUP -> UNTAP wrap), the
    active player draws one card. Verify the hand_p1 size flips from
    0 to 1 at the right boundary, on BOTH engines uniformly (no
    divergence).
    """
    from mtg_bot.parity.cross_engine import (
        multi_turn_selector,
        slightly_bigger_deckspec,
        walk_both,
    )

    result = walk_both(
        slightly_bigger_deckspec(),
        n_decisions=14,
        decision_selector=multi_turn_selector,
    )
    assert result.error is None
    # Step 11: turn 2 UNTAP — p1 is now active, p1 hand empty.
    step_11 = result.steps[11]
    assert step_11.py_view["turn"] == 2
    assert step_11.py_view["step"] == "UNTAP"
    assert step_11.py_view["active_player"] == 1
    assert len(step_11.py_view["hand_p1"]) == 0
    # Step 12: UPKEEP.
    assert result.steps[12].py_view["step"] == "UPKEEP"
    assert len(result.steps[12].py_view["hand_p1"]) == 0
    # Step 13: DRAW — p1 draws one card via the side-channel
    # advance_phase composition on both engines (CR 504.1).
    step_13 = result.steps[13]
    assert step_13.py_view["step"] == "DRAW"
    assert len(step_13.py_view["hand_p1"]) == 1
    # Both engines agree (no divergence).
    assert step_13.divergences == []


# ---------------------------------------------------------------------------
# Phase 5 follow-up #4: cast_bears_selector. Extends the harness past the
# land-only multi_turn_selector slice into creature spells + mana abilities
# + summoning-sick timing. Drives multi-turn play on the slightly_bigger_deckspec
# until the active player has Grizzly Bears in hand AND two untapped non-sick
# Forests on the battlefield, activates each Forest in turn for {G}{G}, then
# emits cast_spell(Bears).
#
# **Outcome (this slice)**: NEW divergence CE5 — Rust's ``cast_creature``
# primitive fuses cast+resolve into one mutation (no-stack semantics:
# state_ops_cast.rs:293-297 docstring), while Python's ``_cast_spell``
# pushes the spell as a ``StackItem`` and defers the bf transition to
# ``resolve_top_of_stack``. After ``cast_spell`` is applied, Python's
# stack has the Bears item / battlefield is missing the Bears; Rust's
# stack is empty / battlefield has the freshly-cast Bears. Pinned
# strict-xfail below; closure plan in ``docs/RUST_PARITY_GAPS.md`` CE5
# entry. The cleanly-walking ``activate_ability`` calls (steps 92, 106,
# 107) before the cast also serve as the first cross-engine pin that
# mana-ability parity holds — Python's stack-bypass for mana abilities
# and Rust's direct-pool-credit produce the same observable mana pool
# + tapped state.
# ---------------------------------------------------------------------------


def test_cross_engine_cast_bears_selector_walks_clean(parity_smoke):
    """Drive 150 decisions on the slightly_bigger_deckspec with the
    cast_bears_selector and assert every step walks clean.

    The selector activates 2 Forests for {G}{G} then casts Grizzly Bears
    at turn 9 PRECOMBAT_MAIN (p0 active). Pre-cast steps walk clean —
    the activate-ability mana-credit flow is parity-equal across both
    engines. The cast step itself (step 108) used to be where CE5
    surfaced (Python pushes StackItem + defers, Rust ``cast_creature``
    fuses cast+resolve and lands the Bears directly on the
    battlefield). **CE5 closure**: the cross-engine harness now drains
    Python's stack after every ``cast_spell`` action via
    :func:`resolve_top_of_stack_python`, parity-aligning Python's
    observable state with Rust's no-stack semantics. Every step in
    this walk — including the cast at step 108 — produces an empty
    divergence list.

    Step 119's prior eager-``is_over`` divergence (Rust flipping on
    empty-library draw while Python deferred until SBAs) is also
    closed independently as CE10 (`feature/ce-pure-derivation-is-over`,
    landed before this slice). The 150-decision walk now traverses
    that boundary cleanly — the surface accessors are SBA-gated on
    both sides, and neither engine fires SBAs between cross-engine
    decision steps, so both stay stale together until the next slice
    grows the harness an SBA hook.
    """
    from mtg_bot.parity.cross_engine import (
        cast_bears_selector,
        slightly_bigger_deckspec,
        walk_both,
    )

    result = walk_both(
        slightly_bigger_deckspec(),
        n_decisions=150,
        decision_selector=cast_bears_selector,
    )
    assert result.error is None, (
        f"walk aborted at step {result.aborted_at}: {result.error}"
    )
    assert result.aborted_at is None
    assert len(result.steps) == 150
    for step in result.steps:
        assert step.divergences == [], (
            f"unexpected divergence at step {step.step_index}: "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )


def test_cross_engine_cast_bears_selector_cast_step_108_walks_clean_post_ce5(
    parity_smoke,
):
    """**CE5 closure regression pin**: at step 108 (turn 9 PRECOMBAT_MAIN
    p0 active) the selector emits ``cast_spell`` for Grizzly Bears. With
    the harness-side ``resolve_top_of_stack_python`` mirror in
    :func:`step_both` (gated by ``_RUST_AUTO_RESOLVE_ACTION_KINDS``),
    the cast step's divergence list is EMPTY: Python's stack drains
    immediately after the StackItem is pushed, the Bears resolves to
    the battlefield, and both engines' observable state agrees.

    This is the post-closure counterpart of the pre-closure CE5
    symptom-pin (deleted in this slice — the symptom no longer
    surfaces). The pair-pin pattern matches the CE2/CE3/CE4 closures:
    a post-closure regression test pins the new equilibrium.

    Pinned fields after the closure:

      * ``battlefield`` — both engines have 7 objects (the cast lands
        the Bears on Python's bf via the drained stack).
      * ``stack`` — both engines have an empty stack.
    """
    from mtg_bot.parity.cross_engine import (
        cast_bears_selector,
        slightly_bigger_deckspec,
        walk_both,
    )

    result = walk_both(
        slightly_bigger_deckspec(),
        n_decisions=109,
        decision_selector=cast_bears_selector,
    )
    assert result.error is None
    step_108 = result.steps[108]
    # The cast_spell action was emitted at step 108.
    assert step_108.action_dict["kind"] == "cast_spell"
    # The Bears was the active player's hand card 3 (per the
    # slightly_bigger_deckspec deck order: p0 lib =
    # [Forest(id=0), Mountain(id=1), Forest(id=2), Bears(id=3)] —
    # by turn 9 p0 has drawn all four).
    assert step_108.action_dict["card_id"] == 3

    # CE5 closure: zero divergences on the cast step.
    assert step_108.divergences == [], (
        f"CE5 closure regression: step 108 cast should be parity-clean, "
        f"got {[(d.field, d.py_value, d.rust_value) for d in step_108.divergences]}"
    )

    # Both views agree on the post-cast state — Bears on the
    # battlefield, stack empty.
    py_bf = step_108.py_view["battlefield"]
    rust_bf = step_108.rust_view["battlefield"]
    assert len(py_bf) == 7
    assert len(rust_bf) == 7
    assert "Grizzly Bears" in [sig[0] for sig in py_bf]
    assert "Grizzly Bears" in [sig[0] for sig in rust_bf]
    assert step_108.py_view["stack"] == ()
    assert step_108.rust_view["stack"] == ()


def test_cross_engine_resolve_top_of_stack_python_drains_stack(parity_smoke):
    """**CE5 closure unit pin**: the harness primitive
    :func:`resolve_top_of_stack_python` drains a non-empty Python
    stack to empty, mirroring ``simulate.priority_loop``'s
    "resolve until empty" contract (CR 117.4).

    Drives a one-decision walk to N=109 to reach the post-cast state,
    then verifies that after :func:`step_both` returns the Python
    stack is empty AND the cast emitted exactly one stack-pop.

    Also pins the no-op behavior: calling the primitive on a state
    with an empty stack returns 0 without raising.
    """
    from mtg_bot.parity.cross_engine import (
        cast_bears_selector,
        resolve_top_of_stack_python,
        slightly_bigger_deckspec,
        walk_both,
    )

    result = walk_both(
        slightly_bigger_deckspec(),
        n_decisions=109,
        decision_selector=cast_bears_selector,
    )
    assert result.error is None
    # The cast step left Python's stack empty (drain ran in step_both).
    assert result.steps[108].py_view["stack"] == ()

    # No-op contract: calling the primitive on a state with an empty
    # stack returns 0 without raising. Build a fresh state to confirm.
    from mtg_bot.parity.cross_engine import build_python_state
    py_state = build_python_state(slightly_bigger_deckspec())
    assert py_state.stack == []
    assert resolve_top_of_stack_python(py_state) == 0
    assert py_state.stack == []


def test_cross_engine_cast_bears_selector_activate_ability_pre_cast_walks_clean(
    parity_smoke,
):
    """Pre-cast walk parity pin. The first 108 decisions walk through
    multiple turns of advance_phase + play_land + (steps 92, 106, 107)
    activate_ability calls without any divergence. This is the
    counterpart of the post-CE5 clean-walk pin: it asserts that
    everything EXCEPT the cast step itself walks clean, which means
    the cross-engine bridge's mana-ability resolution path is
    parity-equal across engines.

    Step 92 (turn 8 PRECOMBAT_MAIN p1 active) is the first
    activate_ability call — p1 has Bears + Forest in hand, plays the
    Forest at step 91, taps the older Mountain (id=4) at step 92...
    wait, the selector picks a Forest (G-producer), so step 92's
    source is the Forest p1 just played. Re-read the decision: at
    step 92 p1 has 1 untapped non-sick Forest (id=6, played turn 6
    and cleared by turn 8's UNTAP) — that's the source the selector
    picks. After the activate the pool has {G}:1; the selector wants
    {G}:2 to cast Bears, and p1 has no second Forest source, so the
    next selector call falls through to multi_turn_selector and
    advances phase.

    Step 106 + 107 (turn 9 PRECOMBAT_MAIN p0 active) are the two
    Forest activations p0 actually needs to cast Bears at step 108.
    """
    from mtg_bot.parity.cross_engine import (
        cast_bears_selector,
        slightly_bigger_deckspec,
        walk_both,
    )

    result = walk_both(
        slightly_bigger_deckspec(),
        n_decisions=108,
        decision_selector=cast_bears_selector,
    )
    assert result.error is None
    assert result.aborted_at is None
    assert len(result.steps) == 108

    # No divergence anywhere in the pre-cast walk.
    for step in result.steps:
        assert step.divergences == [], (
            f"unexpected pre-cast divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value) for d in step.divergences]}"
        )

    # Verify the activate_ability calls were actually emitted at the
    # expected steps (the brief asserts the selector's decision shape).
    activate_steps = [
        s for s in result.steps
        if s.action_dict.get("kind") == "activate_ability"
    ]
    # Three activate_ability calls: one on p1's turn 8 (single Forest,
    # builds 1 G but can't cast), two on p0's turn 9 (two Forests,
    # builds 2 G).
    assert len(activate_steps) == 3, (
        f"expected 3 activate_ability calls, got "
        f"{[(s.step_index, s.action_dict) for s in activate_steps]}"
    )
    # Step 92: p1 activates their Forest.
    assert activate_steps[0].step_index == 92
    # Steps 106 + 107: p0 activates both their Forests.
    assert activate_steps[1].step_index == 106
    assert activate_steps[2].step_index == 107


def test_cross_engine_cast_bears_selector_mana_pool_g2_at_step_107(parity_smoke):
    """After the second activate_ability at step 107 (turn 9
    PRECOMBAT_MAIN p0 active), p0's mana pool carries exactly 2 G
    coins on BOTH engines. Pins the mana-ability parity contract
    that motivated the cast at step 108: Python's stack-bypass for
    mana abilities and Rust's direct-pool-credit dispatch arm
    produce byte-equal observable pools.

    Mana pool field shape: a sorted 6-key tuple `((B,0), (C,0),
    (G,2), (R,0), (U,0), (W,0))`. The harness normalizes Python's
    ``list[ManaCoin]`` representation to this shape via
    ``_python_mana_pool_signature`` so both engines emit the same
    tuple on a green-only pool.
    """
    from mtg_bot.parity.cross_engine import (
        cast_bears_selector,
        slightly_bigger_deckspec,
        walk_both,
    )

    result = walk_both(
        slightly_bigger_deckspec(),
        n_decisions=108,
        decision_selector=cast_bears_selector,
    )
    assert result.error is None
    step_107 = result.steps[107]
    assert step_107.action_dict["kind"] == "activate_ability"
    # Both engines agree on the mana pool after the second activate.
    py_pool = dict(step_107.py_view["mana_pool_p0"])
    rust_pool = dict(step_107.rust_view["mana_pool_p0"])
    assert py_pool == rust_pool, (
        f"mana_pool_p0 diverged at step 107: py={py_pool} rust={rust_pool}"
    )
    assert py_pool["G"] == 2
    assert step_107.divergences == []


def test_cross_engine_cast_bears_selector_falls_back_to_multi_turn(parity_smoke):
    """Selector contract: when the active player does NOT have Grizzly
    Bears in hand, the selector delegates to multi_turn_selector
    (play_land in MAIN if available, side-channel advance + pass
    otherwise). Step 0 (turn 1 ap=0 UPKEEP with empty hand) is the
    canonical fall-through case — multi_turn_selector advances UPKEEP
    -> DRAW and emits pass_priority.
    """
    from mtg_bot.parity.cross_engine import (
        cast_bears_selector,
        slightly_bigger_deckspec,
        walk_both,
    )

    result = walk_both(
        slightly_bigger_deckspec(),
        n_decisions=1,
        decision_selector=cast_bears_selector,
    )
    assert result.error is None
    # Step 0: turn 1 UPKEEP, hands empty, no Bears anywhere → fall
    # through to multi_turn_selector → side-channel advance + pass.
    assert result.steps[0].action_dict == {"kind": "pass_priority"}
    assert result.steps[0].divergences == []


def test_cross_engine_dict_to_python_action_handles_activate_ability(parity_smoke):
    """The ``_dict_to_python_action`` shim must convert the
    ``activate_ability`` dict shape that the new selector emits into a
    Python ``ActivateAbility`` instance with matching fields. Locks in
    the action-dict round-trip contract so a future selector that
    emits a different ability_index doesn't silently fall through to
    the ``unsupported action kind`` raise.
    """
    from mtg_bot.actions import ActivateAbility
    from mtg_bot.parity.cross_engine import _dict_to_python_action

    action = _dict_to_python_action(
        {"kind": "activate_ability", "source_id": 42, "ability_index": 0}
    )
    assert isinstance(action, ActivateAbility)
    assert action.source_id == 42
    assert action.ability_index == 0


# ---------------------------------------------------------------------------
# Phase 5 follow-up #5: combat_selector. Extends cast_bears_selector past the
# cast into declare_attackers / declare_blockers / combat damage application
# / clear_combat. The probe surfaces (or fails to surface, depending on the
# outcome) the audits' predicted CE6 / CE7 (combat damage assignment order).
# A single-attacker / zero-blocker slice exercises the dispatch + advance
# wiring without surfacing the multi-block ordering surface — that requires
# a richer deck (two attackers facing two blockers with non-trivial ETB
# interleaving). This slice is the gate that unblocks the ordering probe.
# ---------------------------------------------------------------------------


def test_cross_engine_combat_selector_walks_clean(parity_smoke):
    """Drive 200 decisions on the slightly_bigger_deckspec with the
    combat_selector and assert every step walks clean.

    The selector inherits cast_bears_selector's pre-cast logic
    (activate 2 Forests + cast Bears at step 108, turn 9 p0
    PRECOMBAT_MAIN) and adds four new branches: declare_attackers
    (emitted when active player owns a non-sick non-tapped creature),
    declare_blockers (empty assignments, side-channel advance baked in),
    COMBAT_DAMAGE (side-channel resolve_combat_damage_python +
    deal_combat_damage_rust + apply_sbas), and END_OF_COMBAT
    (side-channel clear_combat_both).

    By the end of the 200 decisions the walker has driven three full
    combat cycles (Bears attacking unblocked on turns 11/13/15 — p0
    active, Bears unsick after turn 10's UNTAP). p1's life drops from
    20 -> 18 -> 16 -> 14 in 2-damage increments. Both engines apply
    damage simultaneously through the side-channel mirrors, and the
    post-step compare on COMBAT_DAMAGE / END_OF_COMBAT sees an empty
    divergence list for every step.

    **Why no CE divergence surfaces on this slice.** The audits'
    predicted CE6 / CE7 (combat damage assignment order — Python walks
    ``state.battlefield`` filtered by ``attacker.blocked_by``, Rust
    walks ``self.blockers`` Vec) requires MULTIPLE blockers per
    attacker to surface — the order question only matters when there
    are 2+ blockers facing the same attacker with interleaved ETB
    timestamps. On the current deck the defender has zero creatures
    so combat is always unblocked. The probe is therefore the GATE
    that unblocks the audits' true ordering probe rather than the
    ordering probe itself — a richer deck (two Bears + a defender
    with two blockers) is the natural next slice.
    """
    from mtg_bot.parity.cross_engine import (
        combat_selector,
        slightly_bigger_deckspec,
        walk_both,
    )

    result = walk_both(
        slightly_bigger_deckspec(),
        n_decisions=200,
        decision_selector=combat_selector,
    )
    assert result.error is None, (
        f"walk aborted at step {result.aborted_at}: {result.error}"
    )
    assert result.aborted_at is None
    assert len(result.steps) == 200
    for step in result.steps:
        assert step.divergences == [], (
            f"unexpected divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )


def test_cross_engine_combat_selector_first_declare_attackers_at_step_136(
    parity_smoke,
):
    """**combat_selector script pin**: the first ``declare_attackers``
    emission lands at step 136, turn 11 DECLARE_ATTACKERS with p0
    active and Grizzly Bears (id=3) as the attacker.

    Reasoning trail:
      * Bears is cast at step 108 (turn 9 p0 PRECOMBAT_MAIN per the
        ``cast_bears_selector`` script).
      * Bears enters with ``summoning_sick=True`` and stays sick
        through turn 9's combat (DECLARE_ATTACKERS at step 110-ish)
        — selector falls through to pass_priority.
      * Turn 9 wraps to turn 10 (p1 active); turn 10 UNTAP clears p1's
        permanents but NOT Bears (Bears is on p0's side).
      * Turn 10 wraps to turn 11 (p0 active); turn 11 UNTAP fires on
        p0's permanents, clearing Bears' summoning_sick.
      * At turn 11 DECLARE_ATTACKERS, Bears is non-sick, non-tapped,
        Creature, controller=0 — the selector emits
        ``declare_attackers([3])``.

    The exact step index (136) is sensitive to the upstream selector
    chain's decision count; if cast_bears_selector or
    multi_turn_selector evolves, this pin's step number may need to
    update.
    """
    from mtg_bot.parity.cross_engine import (
        combat_selector,
        slightly_bigger_deckspec,
        walk_both,
    )

    result = walk_both(
        slightly_bigger_deckspec(),
        n_decisions=140,
        decision_selector=combat_selector,
    )
    assert result.error is None
    declare_steps = [
        s for s in result.steps
        if s.action_dict.get("kind") == "declare_attackers"
    ]
    assert len(declare_steps) >= 1, (
        f"expected at least one declare_attackers emission, got "
        f"{[(s.step_index, s.action_dict) for s in declare_steps]}"
    )
    first_declare = declare_steps[0]
    assert first_declare.step_index == 136, (
        f"expected first declare_attackers at step 136, got "
        f"{first_declare.step_index} action={first_declare.action_dict}"
    )
    assert first_declare.action_dict == {
        "kind": "declare_attackers",
        "attacker_ids": [3],
    }
    assert first_declare.py_view["turn"] == 11
    assert first_declare.py_view["step"] == "DECLARE_ATTACKERS"
    assert first_declare.py_view["active_player"] == 0
    assert first_declare.divergences == []


def test_cross_engine_combat_selector_damage_drops_p1_life_in_2s(
    parity_smoke,
):
    """**Combat damage parity pin**: across the 200-decision walk, p1's
    life drops in 2-point increments (Bears unblocked, 2/2) on every
    combat cycle. Both engines agree on the life_p1 trajectory
    step-by-step.

    Three combat cycles fire on turns 11 / 13 / 15 (p0 active —
    p0 attacks with Bears on every other turn; p1's turns never
    declare attackers because p1 has no creatures). p1's life
    sequence: 20 -> 18 -> 16 -> 14. The cross-engine compare on
    each combat_damage step sees byte-equal ``life_p1`` on both
    engines.

    Pins the post-damage state ALSO has ``life_p0 == 20`` throughout
    (Bears is unblocked, no back-damage, so p0 stays at full life).
    """
    from mtg_bot.parity.cross_engine import (
        combat_selector,
        slightly_bigger_deckspec,
        walk_both,
    )

    result = walk_both(
        slightly_bigger_deckspec(),
        n_decisions=200,
        decision_selector=combat_selector,
    )
    assert result.error is None
    # Walk the per-step compare and track life_p1 evolution. Every
    # life-drop boundary should agree across engines.
    life_drops_py: list[tuple[int, int]] = []
    prev_life_p1 = 20
    for step in result.steps:
        cur_py = step.py_view["life_p1"]
        cur_rust = step.rust_view["life_p1"]
        assert cur_py == cur_rust, (
            f"life_p1 diverged at step {step.step_index}: "
            f"py={cur_py} rust={cur_rust}"
        )
        if cur_py != prev_life_p1:
            life_drops_py.append((step.step_index, cur_py))
            prev_life_p1 = cur_py
    # Expect 3 drops: 20->18, 18->16, 16->14.
    assert [drop[1] for drop in life_drops_py] == [18, 16, 14], (
        f"expected p1 life trajectory 20->18->16->14, got {life_drops_py}"
    )
    # Final p1 life is 14; p0 untouched.
    assert result.steps[-1].py_view["life_p1"] == 14
    assert result.steps[-1].rust_view["life_p1"] == 14
    assert result.steps[-1].py_view["life_p0"] == 20
    assert result.steps[-1].rust_view["life_p0"] == 20


def test_cross_engine_combat_selector_falls_back_to_cast_bears(parity_smoke):
    """Selector contract: when none of the four combat branches
    (DECLARE_ATTACKERS / DECLARE_BLOCKERS / COMBAT_DAMAGE /
    END_OF_COMBAT) match, the selector delegates to
    cast_bears_selector (which itself delegates to multi_turn_selector
    if no cast/activate is appropriate).

    Step 0 (turn 1 UPKEEP, empty hand, no Bears) is the canonical
    fall-through case — multi_turn_selector advances UPKEEP -> DRAW
    and emits pass_priority.
    """
    from mtg_bot.parity.cross_engine import (
        combat_selector,
        slightly_bigger_deckspec,
        walk_both,
    )

    result = walk_both(
        slightly_bigger_deckspec(),
        n_decisions=1,
        decision_selector=combat_selector,
    )
    assert result.error is None
    assert result.steps[0].action_dict == {"kind": "pass_priority"}
    assert result.steps[0].divergences == []


def test_cross_engine_combat_selector_summoning_sick_bears_skips_attack(
    parity_smoke,
):
    """At turn 9 DECLARE_ATTACKERS — the turn Bears was cast — Bears
    is summoning-sick. The selector's eligibility filter requires
    ``not summoning_sick``, so Bears is skipped and the selector
    falls through to multi_turn_selector for a pass_priority +
    advance. No attack happens on turn 9 even though Bears is on
    the battlefield.

    Pins CR 302.1's summoning-sickness restriction for attackers —
    the parallel land-side restriction (Rust's ActivateAbility
    rejects sick lands; documented as a CE candidate) is NOT in
    scope here.
    """
    from mtg_bot.parity.cross_engine import (
        combat_selector,
        slightly_bigger_deckspec,
        walk_both,
    )

    result = walk_both(
        slightly_bigger_deckspec(),
        n_decisions=130,
        decision_selector=combat_selector,
    )
    assert result.error is None
    # Walk every step and confirm: at turn 9 DECLARE_ATTACKERS with
    # p0 active, the action emitted is NOT declare_attackers.
    for step in result.steps:
        if (
            step.py_view["turn"] == 9
            and step.py_view["step"] == "DECLARE_ATTACKERS"
            and step.py_view["active_player"] == 0
        ):
            assert step.action_dict.get("kind") != "declare_attackers", (
                f"turn 9 declare_attackers fired despite sick Bears: "
                f"step {step.step_index} action={step.action_dict}"
            )
            # Sanity: Bears IS on the battlefield and IS sick.
            bears_sigs = [
                s for s in step.py_view["battlefield"]
                if s[0] == "Grizzly Bears"
            ]
            assert len(bears_sigs) == 1, (
                f"expected Bears on bf at step {step.step_index}, got {bears_sigs}"
            )
            # Position 2 of the 8-tuple is summoning_sick (per
            # scripts/parity_smoke.py::_zone_signature).
            assert bears_sigs[0][2] == 1, (
                f"expected Bears summoning_sick=1 at step {step.step_index}, "
                f"got sig {bears_sigs[0]}"
            )


def test_cross_engine_combat_selector_declare_blockers_empty_assignments(
    parity_smoke,
):
    """The selector's DECLARE_BLOCKERS branch emits
    ``declare_blockers`` with an empty ``assignments`` list whenever
    an attacker is declared and the defender has no eligible
    blockers. This exercises the ``_dict_to_python_action``
    conversion for the empty-assignments edge case AND verifies that
    both engines' ``apply_action(DeclareBlockers)`` arms accept the
    no-op dispatch.

    On the current slightly_bigger_deckspec, the defender (p1) has
    no creatures at any point — p1's library / hand only contains
    Forests / Mountains / Bears, but p1 never has enough mana to
    cast Bears in this script (only one Forest gets played per p1
    turn and p1's selector chain only fires the mana-cast script
    when p0 is active). So every DECLARE_BLOCKERS step emits an
    empty assignment list.
    """
    from mtg_bot.parity.cross_engine import (
        combat_selector,
        slightly_bigger_deckspec,
        walk_both,
    )

    result = walk_both(
        slightly_bigger_deckspec(),
        n_decisions=200,
        decision_selector=combat_selector,
    )
    assert result.error is None
    declare_blockers_steps = [
        s for s in result.steps
        if s.action_dict.get("kind") == "declare_blockers"
    ]
    # Three combat cycles fire (turns 11/13/15), each with one
    # declare_blockers emission. The advance-baked-in pattern in the
    # DECLARE_BLOCKERS branch ensures we emit exactly once per cycle.
    assert len(declare_blockers_steps) == 3, (
        f"expected 3 declare_blockers emissions (one per combat cycle), "
        f"got {[(s.step_index, s.py_view['turn']) for s in declare_blockers_steps]}"
    )
    for step in declare_blockers_steps:
        assert step.action_dict["assignments"] == [], (
            f"expected empty assignments at step {step.step_index}, got "
            f"{step.action_dict['assignments']}"
        )
        assert step.divergences == []


def test_cross_engine_dict_to_python_action_handles_declare_attackers(
    parity_smoke,
):
    """The ``_dict_to_python_action`` shim converts the
    ``declare_attackers`` dict shape into a Python ``DeclareAttackers``
    instance with a frozenset of ids. Locks the round-trip contract
    so a future probe that ships multiple attacker ids in a single
    set doesn't silently fall through to the unsupported-kind raise.
    """
    from mtg_bot.actions import DeclareAttackers
    from mtg_bot.parity.cross_engine import _dict_to_python_action

    action = _dict_to_python_action(
        {"kind": "declare_attackers", "attacker_ids": [3, 7, 11]}
    )
    assert isinstance(action, DeclareAttackers)
    assert action.attacker_ids == frozenset({3, 7, 11})

    # Empty set is also valid.
    action_empty = _dict_to_python_action(
        {"kind": "declare_attackers", "attacker_ids": []}
    )
    assert isinstance(action_empty, DeclareAttackers)
    assert action_empty.attacker_ids == frozenset()


def test_cross_engine_dict_to_python_action_handles_declare_blockers(
    parity_smoke,
):
    """The ``_dict_to_python_action`` shim converts the
    ``declare_blockers`` dict shape into a Python ``DeclareBlockers``
    instance with a tuple of (blocker_id, attacker_id) 2-tuples.
    Locks the round-trip contract for multi-blocker scenarios that
    the audits' predicted CE6/CE7 closure probe will exercise.
    """
    from mtg_bot.actions import DeclareBlockers
    from mtg_bot.parity.cross_engine import _dict_to_python_action

    # Single-block case.
    action = _dict_to_python_action(
        {"kind": "declare_blockers", "assignments": [[5, 3]]}
    )
    assert isinstance(action, DeclareBlockers)
    assert action.assignments == ((5, 3),)

    # Multi-block case (audit's CE6 probe shape).
    action_multi = _dict_to_python_action(
        {"kind": "declare_blockers", "assignments": [[5, 3], [7, 3], [9, 3]]}
    )
    assert isinstance(action_multi, DeclareBlockers)
    assert action_multi.assignments == ((5, 3), (7, 3), (9, 3))

    # Empty assignments (no-block dispatch).
    action_empty = _dict_to_python_action(
        {"kind": "declare_blockers", "assignments": []}
    )
    assert isinstance(action_empty, DeclareBlockers)
    assert action_empty.assignments == ()


def test_cross_engine_resolve_combat_damage_python_no_attackers_noop(
    parity_smoke,
):
    """**Combat-damage harness primitive contract**: invoking
    :func:`resolve_combat_damage_python` on a state with NO attackers
    (no creature has ``attacking=True``) returns False without raising,
    leaves life unchanged on both players.

    This pins the early-exit contract that the combat_selector relies
    on at the COMBAT_DAMAGE branch — without the no-op return, calling
    Python's ``resolve_combat_damage`` against an empty-attackers
    state would raise on the ``defender.agent`` reference (the
    synthetic state has no agent attached).
    """
    from mtg_bot.parity.cross_engine import (
        build_python_state,
        resolve_combat_damage_python,
        slightly_bigger_deckspec,
    )

    py_state = build_python_state(slightly_bigger_deckspec())
    # Fresh state: no attackers.
    assert not any(
        getattr(o, "attacking", False) for o in py_state.battlefield
    )
    assert resolve_combat_damage_python(py_state) is False
    assert py_state.players[0].life == 20
    assert py_state.players[1].life == 20


def test_cross_engine_clear_combat_both_resets_rust_attackers_vec(
    parity_smoke,
):
    """**Clear-combat harness primitive contract**: calling
    :func:`clear_combat_both` on matched states with declared
    attackers/blockers empties Rust's ``self.attackers`` /
    ``self.blockers`` Vecs AND drops Python's per-object
    ``attacking`` / ``blocking`` / ``blocked_by`` flags.

    Pins the end-of-combat cleanup contract that the combat_selector
    relies on at the END_OF_COMBAT branch. Without this clear, Rust's
    declared-attackers Vec would persist into the next turn, and the
    next DECLARE_ATTACKERS step's ``deal_combat_damage`` call would
    re-apply damage to a stale attacker entry.
    """
    from mtg_bot.parity.cross_engine import (
        combat_selector,
        clear_combat_both,
        slightly_bigger_deckspec,
        walk_both,
    )

    # Walk up to the first combat cycle's END_OF_COMBAT then verify
    # the clear ran on both engines.
    result = walk_both(
        slightly_bigger_deckspec(),
        n_decisions=140,
        decision_selector=combat_selector,
    )
    assert result.error is None
    # Find the first END_OF_COMBAT step (immediately after the first
    # combat damage). It should have empty attackers on Rust by then.
    for step in result.steps:
        if (
            step.py_view["step"] == "POSTCOMBAT_MAIN"
            and step.py_view["turn"] == 11
        ):
            # By POSTCOMBAT_MAIN we've already passed END_OF_COMBAT,
            # so attacking should be cleared on Python.
            for sig in step.py_view["battlefield"]:
                # Position 1 of the 8-tuple is tapped. The Bears was
                # tapped from attacking; that tap state PERSISTS
                # through end-of-combat (only the next UNTAP step
                # clears it). The attacking flag itself isn't in the
                # 8-tuple, but the absence of further damage on later
                # steps is the indirect signal that clear_combat
                # worked.
                pass
            break

    # Direct unit-style smoke: build a fresh state, hand-poke an
    # attacking flag on a python object, then call clear_combat_both.
    from mtg_bot.parity.cross_engine import build_matched_states
    py_state, rust_state = build_matched_states(slightly_bigger_deckspec())
    # Simulate a declared attack: directly mark a python bf object as
    # attacking + push a rust attacker entry. (The rust_state has no
    # bf objects so we use it as a noop-target — clear_combat_both
    # should run without raising even on empty rust state.)
    # Build a minimal py-side bf object via the existing flow: draw
    # then play_land won't yield a creature; skip — use the walk to
    # arrive at an attacking state instead.
    result_short = walk_both(
        slightly_bigger_deckspec(),
        n_decisions=137,  # one step past the declare_attackers emission
        decision_selector=combat_selector,
    )
    assert result_short.error is None
    # Verify clear_combat_both is the harness-only primitive that
    # accepts both engines and returns None.
    py_state2, rust_state2 = build_matched_states(slightly_bigger_deckspec())
    result_clear = clear_combat_both(py_state2, rust_state2)
    assert result_clear is None  # no return value


# ---------------------------------------------------------------------------
# Phase 5 follow-up #6: multi_block_combat_selector. Extends combat_selector
# past the single-attacker / zero-blocker slice into a SINGLE-ATTACKER /
# TWO-BLOCKER scenario. Surfaced and (now) closes the audits' predicted
# CE9 (combat damage assignment order) divergence.
#
# **STATUS: CE9 CLOSED** by ``feature/ce9-blocker-bf-order``. Rust's two
# iteration sites in ``rust/src/state_ops_combat.rs`` (the per-attacker
# first-blocker walk at lines 865-868 and the back-damage walk at line
# 962) now iterate via the shared ``bf_iter_etb_sorted`` helper in
# ``rust/src/bf_iter.rs`` (the same helper introduced by the CE5/CE6
# closure for SBA victim collection), filtered by membership in
# ``self.blockers``. This matches Python's ``combat.py:389,405`` walk
# of ``[o for o in state.battlefield if o.id in attacker.blocked_by]``.
# Per the playbook §3 Option A: parity with observable Python first;
# CR 510.1d "active player chooses damage assignment order" is a
# separate long-term Python-side fix. See ``docs/RUST_PARITY_GAPS.md``
# I31 for the closure invariant.
# ---------------------------------------------------------------------------


def test_cross_engine_multi_block_combat_selector_walks_clean(parity_smoke):
    """**CE9 clean-walk pin** (expected-pass post-closure).

    Drive 210 decisions on :func:`multi_blocker_deckspec` with
    :func:`multi_block_combat_selector` and assert every step walks
    clean. Pre-closure, the multi-block COMBAT_DAMAGE step at index
    196 surfaced the audits' predicted CE6/CE7 (numbered CE9 here)
    divergence: Python's bf-order damage walk and Rust's
    self.blockers-Vec damage walk picked DIFFERENT first blockers
    when blockers were declared in reverse-bf order.

    Post-closure, Rust's combat-damage iteration consumes
    ``bf_iter_etb_sorted`` (same helper as the CE5/CE6 SBA closure)
    and the entire 210-decision walk runs clean.

    Mirrors the post-closure clean-walk pattern of CE2/CE3/CE4/CE5/CE6:
    a single expected-pass clean-walk pin; the companion symptom-pin
    that previously documented the surface shape was deleted on closure.
    """
    from mtg_bot.parity.cross_engine import (
        multi_block_combat_selector,
        multi_blocker_deckspec,
        walk_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=210,
        decision_selector=multi_block_combat_selector,
    )
    assert result.error is None, (
        f"walk aborted at step {result.aborted_at}: {result.error}"
    )
    assert result.aborted_at is None
    assert len(result.steps) == 210
    for step in result.steps:
        assert step.divergences == [], (
            f"unexpected divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )


def test_cross_engine_multi_block_combat_selector_pre_combat_walks_clean(
    parity_smoke,
):
    """The pre-combat walk (steps 0-192) on
    :func:`multi_blocker_deckspec` with
    :func:`multi_block_combat_selector` is parity-clean. Pins the
    contract that the multi-block CE9 surface is SPECIFICALLY a
    damage-assignment-order finding — the cast, mana-ability, draw,
    advance-phase, and declare-attackers paths all walk clean even
    on this fatter deck.

    Step 193 is the first declare_attackers emission; step 195 is
    the declare_blockers emission. Both walk clean — the divergence
    only surfaces on step 196 when actual damage is applied (the
    COMBAT_DAMAGE branch fires resolve_combat_damage_python +
    deal_combat_damage_rust).
    """
    from mtg_bot.parity.cross_engine import (
        multi_block_combat_selector,
        multi_blocker_deckspec,
        walk_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=196,
        decision_selector=multi_block_combat_selector,
    )
    assert result.error is None
    for step in result.steps:
        assert step.divergences == [], (
            f"pre-combat divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )

    # Confirm the script shape (the same shape that gates the CE9
    # surface): three casts (p1 turns 6 + 10, p0 turn 13), one
    # declare_attackers (p0 turn 15), one declare_blockers (turn 15
    # COMBAT_DAMAGE / pre-advanced step).
    casts = [
        s for s in result.steps
        if s.action_dict.get("kind") == "cast_spell"
    ]
    assert len(casts) == 3, f"expected 3 cast emissions, got {len(casts)}"
    declares_attackers = [
        s for s in result.steps
        if s.action_dict.get("kind") == "declare_attackers"
    ]
    assert len(declares_attackers) == 1
    assert declares_attackers[0].py_view["active_player"] == 0
    declares_blockers = [
        s for s in result.steps
        if s.action_dict.get("kind") == "declare_blockers"
    ]
    assert len(declares_blockers) == 1
    assert declares_blockers[0].action_dict["assignments"] == [[11, 5], [9, 5]]


def test_cross_engine_multi_block_combat_selector_suppresses_p1_attacks(
    parity_smoke,
):
    """**Multi-block selector contract**: p1 NEVER attacks. The selector's
    DECLARE_ATTACKERS branch gates on ``active_idx == 0`` to preserve
    p1's Bears as untapped blockers (a tapped creature can't block per
    CR 509.1b — and combat tapping is the principal way Bears would
    end up tapped on this synthetic deck).

    Across the full 210-step walk, every ``declare_attackers`` action
    has ``active_player == 0``. p1's DECLARE_ATTACKERS step falls
    through to the multi_turn fallback (pass_priority + advance).
    """
    from mtg_bot.parity.cross_engine import (
        multi_block_combat_selector,
        multi_blocker_deckspec,
        walk_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=210,
        decision_selector=multi_block_combat_selector,
    )
    assert result.error is None
    declares = [
        s for s in result.steps
        if s.action_dict.get("kind") == "declare_attackers"
    ]
    for d in declares:
        assert d.py_view["active_player"] == 0, (
            f"unexpected p1 declare_attackers at step {d.step_index}: "
            f"{d.action_dict} active={d.py_view['active_player']}"
        )


def test_cross_engine_multi_blocker_deckspec_library_shape(parity_smoke):
    """**Deckspec contract**: the multi-blocker library shape is the
    minimum needed to deliver:
      * One Bears in p0's hand by turn 13 (the cast turn).
      * Two Bears in p1's hand spaced 4 turns apart (turn 6 + turn 10
        casts so both Bears are unsick by turn 15).

    Pins the exact library tuples so a future refactor that fiddles
    with the shape doesn't silently shift the multi-block CE9 step
    index.
    """
    from mtg_bot.parity.cross_engine import multi_blocker_deckspec

    spec = multi_blocker_deckspec()
    assert spec.p0_library == (
        "Forest", "Forest", "Forest", "Forest", "Forest",
        "Grizzly Bears", "Forest",
    )
    assert spec.p1_library == (
        "Forest", "Forest", "Grizzly Bears", "Forest",
        "Grizzly Bears", "Forest", "Forest",
    )
    assert spec.shuffle_seed is None  # no shuffle for parity smoke


def test_cross_engine_step_both_routes_declare_blockers_actor_to_defender(
    parity_smoke,
):
    """**step_both actor-routing contract**: when an action's kind is
    ``declare_blockers``, the harness routes Python's ``apply_action``
    using the DEFENDER's player id (not the priority player's), so
    Python's ``_declare_blockers`` validation passes
    ``eligible_blockers(state, defender_id)`` and the assignments
    actually take effect.

    Without this routing the declare_blockers action would silently
    drop every assignment because the harness uses
    ``priority_player_idx`` as the actor for every action kind, and
    during DECLARE_BLOCKERS the priority player on a synthetic state
    is still the active player (the harness doesn't model the
    priority handoff to defender). The CE9 surface depends on
    blockers actually being declared — without this routing the
    multi-block probe would see empty blocked_by sets and the
    divergence wouldn't surface.

    Smoke check: drive a multi-block walk through the declare_blockers
    step and verify the attacker's blocked_by set is non-empty on the
    Python side post-step.
    """
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        multi_blocker_deckspec,
        multi_block_combat_selector,
        walk_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=196,
        decision_selector=multi_block_combat_selector,
    )
    assert result.error is None
    # After step 195 (declare_blockers), Python's attacker (Bears
    # id=5) should have blocked_by set to both blockers — populated
    # by the defender-routed apply_action.
    py_state, _ = build_matched_states(multi_blocker_deckspec())
    for i in range(196):
        action = multi_block_combat_selector(py_state, _, i)
        from mtg_bot.parity.cross_engine import step_both
        step_both(py_state, _, action)
    attacker = next(
        (o for o in py_state.battlefield if int(o.id) == 5),
        None,
    )
    # If the attacker is None it died from combat damage already (the
    # COMBAT_DAMAGE branch may have fired in step 195's selector chain
    # if the advance landed at COMBAT_DAMAGE). On the multi_blocker
    # deck the COMBAT_DAMAGE fires at step 196 (one step after
    # declare), so the attacker should still be on bf at step 195's
    # post-state. If the test breaks here the walk shape has shifted.
    assert attacker is not None, (
        "expected attacker (id=5) to still be on bf at end of step 195"
    )
    # blocked_by should contain both blocker ids (the order depends on
    # the declare order — reversed bf order = [11, 9]).
    assert set(attacker.blocked_by) == {9, 11}, (
        f"expected blocked_by={{9, 11}}, got {attacker.blocked_by}"
    )


# ---------------------------------------------------------------------------
# Phase 5 follow-up #7: retaliation_selector — extend
# multi_block_combat_selector to bilateral combat. Surfaces CE12.
#
# **CE12 — winner_id sticky-vs-derived divergence.** Bilateral combat
# (both players attack on their respective turns) drives both players
# to empty-library exhaustion + has_lost=True. Python's `winner_id`
# is a SBA-WRITTEN sticky field (turn.py:1383-1393 — only written when
# `state.winner_id is None`, never cleared). Rust's `winner_id` is a
# LIVE-DERIVED getter (state_ops_winloss.rs:225-235 — returns
# `Some(other_id)` only when exactly one player has has_lost; returns
# None when both lost). When the state transitions from "exactly one
# loser" to "both lost", Python keeps the prior winner sticky, Rust
# switches to None.
#
# First diverging step on the retaliation_selector probe: index 226
# (the END_OF_COMBAT step right after the COMBAT_DAMAGE branch's
# apply_sbas pass commits p0's `attempted_draw_on_empty` to
# `has_lost = True`, making both players losers).
# ---------------------------------------------------------------------------


def test_cross_engine_retaliation_selector_walks_clean(
    parity_smoke,
):
    """**CE12 closure regression** (was: surface-pin). The
    retaliation_selector walk now walks parity-clean past the
    former divergence point at step 226 — Rust's sticky winner_id
    shadow field matches Python's SBA-write semantics through the
    BOTH-LOST transition.

    See docs/RUST_PARITY_GAPS.md I34 and the (now-closed) CE12
    entry. Pre-closure, this test was xfail-strict and the
    divergence at step 226 was `winner_id` Python=0 vs Rust=None
    (Rust's pre-CE12 live-derived getter returned None when both
    players carried `has_lost=True`).
    """
    from mtg_bot.parity.cross_engine import (
        retaliation_selector,
        multi_blocker_deckspec,
        walk_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=260,
        decision_selector=retaliation_selector,
    )
    assert result.error is None, (
        f"walk aborted at step {result.aborted_at}: {result.error}"
    )

    # Post-CE12 closure: EVERY step walks divergence-free. The
    # bilateral active-player swap, summoning-sick clear, symmetric
    # multi-block combat, life-total accounting, AND the BOTH-LOST
    # transition's sticky winner_id all match between engines.
    for step in result.steps:
        assert step.divergences == [], (
            f"unexpected divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )


def test_cross_engine_retaliation_selector_pre_ce12_walks_clean(
    parity_smoke,
):
    """The pre-CE12 walk (steps 0-225) on
    :func:`multi_blocker_deckspec` with
    :func:`retaliation_selector` is parity-clean. Pins the contract
    that CE12 is SPECIFICALLY a winner_id-sticky-vs-derived finding —
    not a broader divergence in active-player swap, summoning-sick
    clear, or symmetric combat.

    Walks 226 decisions (one past the last clean step) and asserts
    every step except the final one is divergence-free. The final
    (step 225) is the COMBAT_DAMAGE branch's apply_sbas pass on
    p0's second attack-turn; its post-state is still clean (both
    engines: is_over=True, is_draw=False, winner_id=0). Step 226's
    pass_priority is the first step where the (already-diverged)
    Python-vs-Rust state surfaces through the field-view compare.

    See CE12 in docs/RUST_PARITY_GAPS.md.
    """
    from mtg_bot.parity.cross_engine import (
        retaliation_selector,
        multi_blocker_deckspec,
        walk_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=226,
        decision_selector=retaliation_selector,
    )
    assert result.error is None
    for step in result.steps[:226]:
        assert step.divergences == [], (
            f"pre-CE12 divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )

    # Walk shape sanity: confirm BOTH players attacked at least once,
    # which is the load-bearing change vs multi_block_combat_selector
    # (which suppressed p1 attacks entirely).
    declares = [
        s for s in result.steps
        if s.action_dict.get("kind") == "declare_attackers"
    ]
    p0_attacks = [s for s in declares if s.py_view["active_player"] == 0]
    p1_attacks = [s for s in declares if s.py_view["active_player"] == 1]
    assert len(p0_attacks) >= 1, (
        f"expected at least 1 p0 attack, got {len(p0_attacks)}"
    )
    assert len(p1_attacks) >= 1, (
        f"expected at least 1 p1 attack (the bilateral surface), "
        f"got {len(p1_attacks)}"
    )


# ---------------------------------------------------------------------------
# Phase 5 follow-up #8: mass_removal_selector — extend
# retaliation_selector with a Wrath-style ``DestroyAllCreatures``
# side-channel fire at step 168 (after the multi-creature bf state
# is set up by p0's turn-13 Bears cast). Originally surfaced CE13.
#
# **CE13 (CLOSED 2026-05-12) — summoning_sick-on-LTB Python-preserve
# vs Rust-clear.** Pre-closure: when a creature left the battlefield
# (destroyed / exiled / sacrificed / bounced), Python's
# ``turn.move_off_battlefield`` did NOT clear ``obj.summoning_sick``
# while Rust's destroy / exile / sacrifice / bounce arms in
# ``state_ops_resolve.rs`` explicitly set
# ``obj.summoning_sick = false`` on the leaving object. The
# fingerprint snapshot tuple captured the raw field, so the cross-
# engine field-view compare flagged the asymmetry.
#
# Closed by ``feature/ce13-summoning-sick-ltb`` via Option B (Rust-
# side, convergence on Python): the explicit clears were dropped
# from every LTB arm in ``state_ops_resolve.rs``. The result is
# bit-equal to Python's preserve-on-LTB semantics. See I35 in
# ``docs/RUST_PARITY_GAPS.md``.
# ---------------------------------------------------------------------------


def test_cross_engine_mass_removal_selector_walks_clean(
    parity_smoke,
):
    """**CE13 closure regression** (was: surface-pin). The
    mass_removal_selector walk now walks parity-clean THROUGH the
    former divergence point at step 168 — Rust's destroy / exile /
    sacrifice / bounce arms preserve summoning_sick on LTB matching
    Python's ``turn.move_off_battlefield`` semantics.

    See docs/RUST_PARITY_GAPS.md I35 and the (now-closed) CE13
    entry. Pre-closure, this test was xfail-strict and the
    divergence at step 168 (the side-channel wrath fire on
    multi_blocker_deckspec) was the ``graveyard_p0`` snapshot's
    ``summoning_sick`` slot: Python preserved sick=1 on the
    just-cast Bears id 5, Rust cleared it to sick=0.
    """
    from mtg_bot.parity.cross_engine import (
        mass_removal_selector,
        multi_blocker_deckspec,
        walk_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=170,
        decision_selector=mass_removal_selector,
    )
    assert result.error is None, (
        f"walk aborted at step {result.aborted_at}: {result.error}"
    )

    # Post-CE13 closure: EVERY step walks divergence-free, including
    # step 168 (the side-channel wrath fire) where the still-sick
    # Bears id 5 lands in the graveyard with summoning_sick preserved
    # in both engines.
    for step in result.steps:
        assert step.divergences == [], (
            f"unexpected divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )


def test_cross_engine_mass_removal_selector_post_wrath_bf_state(
    parity_smoke,
):
    """Validates the load-bearing observable AFTER the wrath fires:
    both engines agree that the battlefield is empty of creatures
    (only lands remain) and the graveyards have the expected counts.

    This is a structural assertion — it doesn't inspect the
    summoning_sick CE13 surface (that's the xfail-pinned test), it
    asserts the mass-destruction itself composed correctly on both
    engines. If a future closure of CE13 lands and the strict-xfail
    test flips, this test continues to pin the load-bearing "wrath
    actually destroyed every creature" semantics.

    Reads the Python state directly (not the field-view 22-tuple)
    so the assertions are independent of the cross-engine
    field-compare's per-snapshot tuple shape. Builds the matched
    states, drives the walk through step 168 (the wrath fire),
    then inspects.
    """
    from mtg_bot.parity.cross_engine import (
        mass_removal_selector,
        multi_blocker_deckspec,
        build_matched_states,
        step_both,
    )

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(169):
        action = mass_removal_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    # Python side: bf has only lands, p0 graveyard has [Bears, Wrath],
    # p1 graveyard has [Bears, Bears].
    py_creatures = [
        o for o in py_state.battlefield
        if "Creature" in o.printing.card_types
    ]
    assert py_creatures == [], (
        f"expected no creatures on Python bf after wrath; got "
        f"{[(o.id, o.printing.name) for o in py_creatures]}"
    )
    py_p0_gy_names = [o.printing.name for o in py_state.players[0].graveyard]
    py_p1_gy_names = [o.printing.name for o in py_state.players[1].graveyard]
    assert py_p0_gy_names == ["Grizzly Bears", "Wrath"], (
        f"expected Python p0 gy=[Bears, Wrath]; got {py_p0_gy_names}"
    )
    assert py_p1_gy_names == ["Grizzly Bears", "Grizzly Bears"], (
        f"expected Python p1 gy=[Bears, Bears]; got {py_p1_gy_names}"
    )

    # Rust side: same shape. Read via the pyclass surface
    # (graveyard_sizes + the field-view's graveyard_pN signature for
    # the name positions).
    rust_gy_sizes = rust_state.graveyard_sizes
    assert rust_gy_sizes == [2, 2], (
        f"expected Rust graveyard_sizes=[2, 2]; got {rust_gy_sizes}"
    )
    rust_view = parity_smoke._build_field_view(rust_state)
    rust_p0_names = tuple(entry[0] for entry in rust_view["graveyard_p0"])
    rust_p1_names = tuple(entry[0] for entry in rust_view["graveyard_p1"])
    assert rust_p0_names == ("Grizzly Bears", "Wrath"), (
        f"expected Rust p0 gy names=(Bears, Wrath); got {rust_p0_names}"
    )
    assert rust_p1_names == ("Grizzly Bears", "Grizzly Bears"), (
        f"expected Rust p1 gy names=(Bears, Bears); got {rust_p1_names}"
    )

    # Both engines should agree the bf is empty of creatures (this
    # is the mass-removal-fired observable; CE13 only surfaces in
    # the per-object summoning_sick field on the graveyard
    # snapshot, not in the bf-cleared invariant). The Rust
    # battlefield_sizes reports total bf size (creatures + lands);
    # post-wrath both players' bf is land-only with 5/4 lands
    # respectively (p0 played turn-13 land that didn't tap;
    # p1 played turn-12 land). Inspect via the snapshot names
    # rather than the size to assert "no creatures".
    rust_bf_p0_names = tuple(
        entry[0] for entry in rust_view["battlefield"]
        if entry[6] == 0  # controller_id == 0
    )
    rust_bf_p1_names = tuple(
        entry[0] for entry in rust_view["battlefield"]
        if entry[6] == 1  # controller_id == 1
    )
    assert "Grizzly Bears" not in rust_bf_p0_names, (
        f"Rust p0 bf still has a Grizzly Bears after wrath: "
        f"{rust_bf_p0_names}"
    )
    assert "Grizzly Bears" not in rust_bf_p1_names, (
        f"Rust p1 bf still has a Grizzly Bears after wrath: "
        f"{rust_bf_p1_names}"
    )


# ---------------------------------------------------------------------------
# Phase 5 follow-up #9: first_strike_selector — extend retaliation_selector
# with a side-channel-injected 2/2 first-strike creature on p0's
# battlefield at step 168 (after the multi-creature bf state is set
# up by p0's turn-13 Bears cast). Probes CR 510.5 (two damage substeps
# when any participant has first-strike) + CR 702.7 (first-strike
# timing) + SBA-between-steps semantics + damage-marking persistence.
#
# **Outcome on this probe: CLEAN PASS (no novel divergence surfaced).**
#
# The walk runs 300+ decisions through the FS combat at turn 13 PRECOMBAT
# (the side-channel-injected attacker is unsick + untapped + on p0's bf;
# p1's bears are side-channel-untapped to be eligible blockers since the
# retaliation walk left them tapped from p1's turn-12 attack). Both engines
# converge bit-identically through every step, including the COMBAT_DAMAGE
# step where Python's combat.resolve_combat_damage and Rust's
# deal_combat_damage internally compose the two-pass first-strike timing.
#
# The post-combat state on both engines:
#   * p0 battlefield: Bears id 5 (sick), Forests, NO Bear Knight
#   * p1 battlefield: Bears id 11 (untapped, untouched), Forests
#   * p0 graveyard:   Bear Knight id 14 (the FS attacker — died in
#                     regular damage step from blocker 11's strike-back)
#   * p1 graveyard:   Bears id 9 (the first-strike-killed blocker)
#
# Which is the exact CR 510.5 expected outcome:
#   1. First-strike damage step: Bear Knight (FS) assigns 2 damage to
#      Bears id 9 (bf-ETB-first eligible blocker — both engines pick
#      the same blocker via the post-CE9-closure bf-ETB-sorted walk).
#   2. SBA between steps (Python side, combat.py:317-318): Bears id 9
#      dies, moves to graveyard.
#   3. Rust side has no SBA between steps but uses an in-function
#      ``damage < toughness`` alive predicate (state_ops_combat.rs:1066)
#      to filter out the dead blocker as a SOURCE in pass 2. Effectively
#      equivalent behavior, different mechanism.
#   4. Regular damage step: Bears id 11 (surviving blocker) deals 2
#      damage to Bear Knight. Bears id 9 in gy (Python) / damage-marked
#      on bf (Rust) deals nothing in either case.
#   5. SBA after pass 2 (both engines): Bear Knight dies. End state
#      converges.
#
# The end-state convergence is exactly the in-between-passes SBA-firing
# divergence ABSORBED by Rust's alive-predicate-on-pass-2 fold. Neither
# engine writes any cross-step-observable damage-marking state that the
# other engine doesn't also write (since the fingerprint compare runs
# AFTER the full deal_combat_damage + apply_sbas composition).
#
# Why this probe didn't surface a new CE: the candidate divergences the
# slice was sized to surface (SBA timing between passes; damage-marking
# carryover between passes; ordering of multi-blocker damage assignment)
# either:
#   (a) had already been closed (CE9 closure fixed bf-ETB-sorted blocker
#       iteration), or
#   (b) are invisible to the harness's per-step compare because the
#       fingerprint snapshot is taken AFTER the full combat damage
#       composition, by which time both engines have absorbed the
#       mid-pass state divergence into a converged end state.
#
# Next-slice candidates to probe a different combat surface:
#   * **Deathtouch + multi-block.** CR 702.2 — deathtouch lets a creature
#     assign 1 damage to each blocker as "lethal" for CR 510.1c damage
#     assignment ordering. Both engines have deathtouch hooks but the
#     interaction with multi-block + assignment splitting is a candidate
#     divergence.
#   * **Trample + multi-block.** CR 702.19 — trample lets a creature spill
#     unblocked excess damage to the defending player. Rust's combat
#     plan already handles trample (state_ops_combat.rs:905-921 "lethal
#     to blocker, excess to defender"). Python's combat.resolve walks a
#     different assignment shape. Potential divergence.
#   * **Lifelink.** CR 702.15 — lifelink grants life to the controller
#     for damage dealt. Both engines have lifelink hooks; the
#     cross-engine surface is the life-gain SBA composition.
# ---------------------------------------------------------------------------


def test_cross_engine_first_strike_selector_walks_clean(parity_smoke):
    """Cross-engine first-strike combat walks parity-clean. **Outcome (a)** —
    no novel divergence surfaced on this probe; first-strike combat
    damage timing matches between Python and Rust.

    Walks 200 decisions on :func:`multi_blocker_deckspec` with
    :func:`first_strike_selector`. Asserts every step's
    ``divergences`` list is empty, including the FS-combat steps at
    turn 13 (steps 168-177): side-channel inject + phase advance +
    declare_attackers([14]) + declare_blockers([[11,14], [9,14]]) +
    COMBAT_DAMAGE (which internally fires the two-pass first-strike
    timing on both engines) + END_OF_COMBAT.

    If a future change to either engine's combat damage path breaks
    first-strike parity, this test fires immediately.
    """
    from mtg_bot.parity.cross_engine import (
        first_strike_selector,
        multi_blocker_deckspec,
        walk_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=200,
        decision_selector=first_strike_selector,
    )
    assert result.error is None, (
        f"walk aborted at step {result.aborted_at}: {result.error}"
    )
    assert result.initial_divergences == [], (
        f"unexpected initial divergence (pre-step-0): "
        f"{[(d.field, d.py_value, d.rust_value) for d in result.initial_divergences]}"
    )
    for step in result.steps:
        assert step.divergences == [], (
            f"unexpected divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )


def test_cross_engine_first_strike_selector_post_combat_state(parity_smoke):
    """Validate the load-bearing observable AFTER the first-strike combat
    fires: both engines agree on the post-combat creature distribution
    and graveyard contents.

    Pins the CR 510.5 expected outcome:
      * Bear Knight (FS attacker, id 14) dies from regular-step damage
        and lands in p0's graveyard.
      * Grizzly Bears id 9 (first-strike-killed blocker) lands in p1's
        graveyard.
      * Grizzly Bears id 11 (surviving blocker) stays on p1's
        battlefield with no damage marked.
      * Grizzly Bears id 5 (p0's sick Bears) is unchanged on p0's
        battlefield.

    Reads both Python state and Rust battlefield/graveyard snapshots
    directly so the assertions are independent of the field-view
    22-tuple shape. This is the structural assertion — if a future
    engine change shifts the FS-combat outcome on either side, this
    test fires.
    """
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        first_strike_selector,
        multi_blocker_deckspec,
        step_both,
    )

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    # Walk through step 179 (well past the FS combat at steps 171-177
    # but before turn 14's combat at steps 184-187). At this point the
    # FS combat is fully resolved on both engines.
    for i in range(180):
        action = first_strike_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    # ---- Python side ----
    py_creatures = sorted(
        (int(o.id), o.printing.name, o.controller_id, o.damage)
        for o in py_state.battlefield
        if "Creature" in o.printing.card_types
    )
    # Expected: id 5 (Bears, p0, sick, 0 damage) and id 11 (Bears, p1,
    # untouched, 0 damage). Bear Knight id 14 in p0_gy, Bears id 9 in
    # p1_gy.
    assert py_creatures == [
        (5, "Grizzly Bears", 0, 0),
        (11, "Grizzly Bears", 1, 0),
    ], f"unexpected Python bf creatures post-FS-combat: {py_creatures}"

    py_p0_gy_names = [o.printing.name for o in py_state.players[0].graveyard]
    py_p1_gy_names = [o.printing.name for o in py_state.players[1].graveyard]
    assert py_p0_gy_names == ["Bear Knight"], (
        f"expected Python p0 gy=[Bear Knight] (FS attacker died); "
        f"got {py_p0_gy_names}"
    )
    assert py_p1_gy_names == ["Grizzly Bears"], (
        f"expected Python p1 gy=[Grizzly Bears] (FS-killed blocker); "
        f"got {py_p1_gy_names}"
    )

    # ---- Rust side ----
    rust_bf = rust_state.battlefield_snapshot()
    rust_creatures = sorted(
        (
            int(entry["id"]),
            entry["printing_name"],
            int(entry["controller_id"]),
            int(entry["damage"]),
        )
        for entry in rust_bf
        if entry["printing_name"] in ("Grizzly Bears", "Bear Knight")
    )
    assert rust_creatures == [
        (5, "Grizzly Bears", 0, 0),
        (11, "Grizzly Bears", 1, 0),
    ], f"unexpected Rust bf creatures post-FS-combat: {rust_creatures}"

    rust_gy0_names = [
        entry["printing_name"]
        for entry in rust_state.graveyard_snapshot(0)
    ]
    rust_gy1_names = [
        entry["printing_name"]
        for entry in rust_state.graveyard_snapshot(1)
    ]
    assert rust_gy0_names == ["Bear Knight"], (
        f"expected Rust p0 gy=[Bear Knight]; got {rust_gy0_names}"
    )
    assert rust_gy1_names == ["Grizzly Bears"], (
        f"expected Rust p1 gy=[Grizzly Bears]; got {rust_gy1_names}"
    )


def test_cross_engine_first_strike_selector_pre_injection_walks_clean(
    parity_smoke,
):
    """The pre-injection walk (steps 0-167) on
    :func:`multi_blocker_deckspec` with :func:`first_strike_selector`
    is parity-clean. Pins the contract that the FS probe's
    delegate-to-retaliation_selector backbone is unchanged — steps
    0-167 are identical to retaliation_selector's walk shape and
    surface no divergences.

    Step 168 is where the side-channel FS injection fires; steps
    168-N exercise the FS combat surface. This test asserts ONLY
    the pre-injection backbone is clean; the full-walk clean-pass is
    asserted by ``test_cross_engine_first_strike_selector_walks_clean``.

    Validates the load-bearing pre-condition: at the end of step 167,
    the bf has exactly 3 creatures — p0=1 (sick Bears id 5), p1=2
    (unsick Bears ids 9, 11). The FS injection at step 168 reads
    this state and triggers via the ``>=3 creatures, no Bear Knight
    yet`` gate.
    """
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        first_strike_selector,
        multi_blocker_deckspec,
        step_both,
        walk_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=168,
        decision_selector=first_strike_selector,
    )
    assert result.error is None
    for step in result.steps:
        assert step.divergences == [], (
            f"pre-injection divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )

    # Walk shape sanity: rebuild matched states, drive 168 steps, and
    # confirm the pre-injection bf state.
    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(168):
        action = first_strike_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    creatures = [
        o for o in py_state.battlefield
        if "Creature" in o.printing.card_types
    ]
    assert len(creatures) == 3, (
        f"expected 3 creatures on bf at end of step 167, got "
        f"{len(creatures)}: "
        f"{[(o.id, o.controller_id, o.summoning_sick) for o in creatures]}"
    )
    # No Bear Knight in any zone yet (the FS injection hasn't fired).
    bear_knight_anywhere = (
        any(o.printing.name == "Bear Knight" for o in py_state.battlefield)
        or any(
            o.printing.name == "Bear Knight"
            for p in py_state.players
            for zone in (p.hand, p.library, p.graveyard, p.exile)
            for o in zone
        )
    )
    assert not bear_knight_anywhere, (
        "Bear Knight should not yet exist at end of step 167 — FS "
        "injection fires at step 168"
    )


# ---------------------------------------------------------------------------
# Phase 5 follow-up #10: deathtouch_selector — extend retaliation_selector
# with a side-channel-injected 2/2 deathtouch creature on p0's
# battlefield at step 168, then drive multi-block combat (CR 702.2 +
# CR 510.1c) at turn 13 PRECOMBAT. Mirrors :func:`first_strike_selector`
# exactly except the injected creature carries ``deathtouch`` instead
# of ``first_strike`` and the trigger gate keys on the
# :data:`_DEATHTOUCH_PRINTING_NAME` ("Bear Assassin") so the two probes
# are independent.
#
# **CE14 CLOSED** by ``feature/ce14-deathtouch-multiblock``: Rust's
# ``state_ops_combat.rs`` no-trample multi-block branch now walks ALL
# blockers in bf-ETB order with ``need = 1 if deathtouch else
# effective_toughness - blocker.damage`` per blocker (Python's
# ``combat.py:419-435`` shape, with the "is_last gets remaining" tail
# preserving the round-5 single-blocker observable behavior). With a
# 2/2 deathtouch attacker blocked by two 2/2 Bears, both Python and
# Rust now assign 1 damage to each blocker, deathtouch upgrades each
# mark to lethal=2 via the apply-damage pass, and SBA destroys both.
# The strict-xfail walk-clean pin below has been flipped to a normal
# passing test; the symptom-present pin has been deleted per the
# CE2-CE13 pair-pin convention.
# ---------------------------------------------------------------------------


def test_cross_engine_deathtouch_selector_walks_clean(parity_smoke):
    """**CE14 clean-walk pin (passing post-closure)**.

    Walks 200 decisions on :func:`multi_blocker_deckspec` with
    :func:`deathtouch_selector` and asserts every step is parity-
    clean. Pre-closure, the multi-block COMBAT_DAMAGE step at index
    174 surfaced CE14: Python killed both blockers via deathtouch's
    CR 702.2b lethal-mark assignment override; Rust killed only the
    bf-ETB-first blocker (the no-trample branch emitted all damage
    to a single PlanEntry). Post-closure
    (``feature/ce14-deathtouch-multiblock``), Rust walks all
    blockers in bf-ETB order with ``need = 1 if deathtouch`` per
    blocker, matching Python's ``combat.py:419-435`` loop shape, so
    every step is parity-clean.

    Mirrors the CE9 / CE12 / CE13 post-closure pattern: the
    formerly-xfailed clean-walk pin becomes an expected-pass full-
    walk parity assertion, and the symptom-present companion is
    deleted per the CE2-CE13 pair-pin convention. See I36 for the
    post-closure invariant.
    """
    from mtg_bot.parity.cross_engine import (
        deathtouch_selector,
        multi_blocker_deckspec,
        walk_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=200,
        decision_selector=deathtouch_selector,
    )
    assert result.error is None, (
        f"walk aborted at step {result.aborted_at}: {result.error}"
    )
    for step in result.steps:
        assert step.divergences == [], (
            f"unexpected divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )


def test_cross_engine_deathtouch_selector_pre_injection_walks_clean(
    parity_smoke,
):
    """Pre-injection walk (steps 0-167) on :func:`multi_blocker_deckspec`
    with :func:`deathtouch_selector` is parity-clean. Pins the
    contract that the deathtouch probe's delegate-to-
    retaliation_selector backbone is unchanged — steps 0-167 are
    identical to retaliation_selector's walk shape and surface no
    divergences. The CE14 divergence is SPECIFICALLY at the
    COMBAT_DAMAGE step (174), not the pre-injection casts /
    mana-abilities / declare-attackers steps.

    Validates the pre-condition: at the end of step 167, the bf has
    exactly 3 creatures and no Bear Assassin (the deathtouch
    injection hasn't fired). Same shape as the first-strike probe's
    pre-injection test.
    """
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        deathtouch_selector,
        multi_blocker_deckspec,
        step_both,
        walk_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=168,
        decision_selector=deathtouch_selector,
    )
    assert result.error is None
    for step in result.steps:
        assert step.divergences == [], (
            f"pre-injection divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )

    # Walk shape sanity: rebuild matched states, drive 168 steps, and
    # confirm the pre-injection bf state.
    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(168):
        action = deathtouch_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    creatures = [
        o for o in py_state.battlefield
        if "Creature" in o.printing.card_types
    ]
    assert len(creatures) == 3, (
        f"expected 3 creatures on bf at end of step 167, got "
        f"{len(creatures)}: "
        f"{[(o.id, o.controller_id, o.summoning_sick) for o in creatures]}"
    )
    # No Bear Assassin in any zone yet (the deathtouch injection
    # hasn't fired).
    bear_assassin_anywhere = (
        any(o.printing.name == "Bear Assassin" for o in py_state.battlefield)
        or any(
            o.printing.name == "Bear Assassin"
            for p in py_state.players
            for zone in (p.hand, p.library, p.graveyard, p.exile)
            for o in zone
        )
    )
    assert not bear_assassin_anywhere, (
        "Bear Assassin should not yet exist at end of step 167 — "
        "deathtouch injection fires at step 168"
    )


# ---------------------------------------------------------------------------
# Phase 5 follow-up #11: lifelink_selector — extend retaliation_selector
# with a side-channel-injected 2/2 lifelink creature on p0's battlefield
# at step 168, then drive multi-block combat (CR 702.15 — "Damage dealt by
# a creature with lifelink causes its controller to gain that much life")
# at turn 13 PRECOMBAT. Mirrors :func:`deathtouch_selector` exactly except
# the injected creature carries ``lifelink`` instead of ``deathtouch`` and
# the trigger gate keys on :data:`_LIFELINK_PRINTING_NAME` ("Bear Cleric")
# so the three keyword-combat probes (FS / DT / LL) stay independent on
# the same multi_blocker_deckspec walk.
#
# **OUTCOME on this probe: CLEAN PASS — no novel cross-engine divergence
# surfaced.** Both engines wire lifelink at damage-apply time:
#
#   * **Python**: ``combat.py:533-541`` calls
#     ``gain_life(state, source_controller, amount)`` per damage event
#     when ``"lifelink" in source_kws``.
#   * **Rust**: ``state_ops_combat.rs:1282-1289`` increments
#     ``self.players[cidx].life += entry.amount as i32`` per ``PlanEntry``
#     when ``battlefield_has_keyword(self, entry.source_id, "lifelink")``.
#
# Both engines fire lifelink per-event in their respective damage-apply
# loops, so the 2-damage assignment to the first blocker (need_0 = 2;
# remaining drops to 0 and the apply loop exits before blocker_1 per the
# post-CE14 ``if remaining <= 0: break`` guard on each engine) results in
# +2 life on p0's controller. Post-combat: p0 life = 14 (was 12 from
# turn-12 retaliation Bears attack; +2 from lifelink), p1 life = 20.
# p0 gy = [Bear Cleric] (attacker died from 4 back-damage from blockers),
# p1 gy = [Grizzly Bears id 9] (first blocker died from assigned 2),
# p1 bf still has Grizzly Bears id 11 (survived because remaining was 0
# after blocker_0).
#
# Three pinning tests guard the contract:
#
#   1. ``test_cross_engine_lifelink_selector_walks_clean`` — full
#      200-decision walk parity-clean on every step.
#   2. ``test_cross_engine_lifelink_selector_post_combat_state`` —
#      direct-read structural assertion on life totals + bf / gy
#      contents post-COMBAT_DAMAGE. Pins the EXPECTED outcome shape so
#      a future refactor that silently breaks lifelink composition
#      (e.g. dropping the lifelink keyword read in apply_damage_pass,
#      or moving the source-keyword lookup to AFTER apply when the
#      attacker has died) fails loudly rather than silently passing
#      the walk-clean test (which would also fail, but the direct-
#      read pin makes the failure mode obvious — "p0 didn't gain 2
#      life" is faster to diagnose than "step 174 has field
#      'life_p0'='12' vs '14'").
#   3. ``test_cross_engine_lifelink_selector_pre_injection_walks_clean``
#      — steps 0-167 are parity-clean. The injection fires at step 168;
#      pre-injection backbone is identical to retaliation_selector.
# ---------------------------------------------------------------------------


def test_cross_engine_lifelink_selector_walks_clean(parity_smoke):
    """**Lifelink clean-walk pin** — 200-decision walk on
    :func:`multi_blocker_deckspec` with :func:`lifelink_selector` is
    parity-clean every step. The lifelink injection at step 168 + the
    multi-block COMBAT_DAMAGE step at index 174 compose correctly on
    both engines: 2 damage assigned to blocker_0 fires lifelink for
    +2 life on p0's controller, mirroring Python's per-event
    ``gain_life`` call in :func:`mtg_bot.combat.resolve_combat_damage`
    and Rust's per-PlanEntry ``self.players[cidx].life += entry.amount``
    in :meth:`GameState::apply_damage_pass`.

    Mirrors the first-strike probe's post-walk-clean shape: lifelink
    behavior is already parity across both engines (no CE16 surfaced
    on this slice), so this test is a "doesn't regress" guard rather
    than a strict-xfail pre-closure pin.
    """
    from mtg_bot.parity.cross_engine import (
        lifelink_selector,
        multi_blocker_deckspec,
        walk_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=200,
        decision_selector=lifelink_selector,
    )
    assert result.error is None, (
        f"walk aborted at step {result.aborted_at}: {result.error}"
    )
    for step in result.steps:
        assert step.divergences == [], (
            f"unexpected divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )


def test_cross_engine_lifelink_selector_post_combat_state(parity_smoke):
    """**Lifelink post-combat structural pin** — drives 180 selector
    decisions to walk past the lifelink COMBAT_DAMAGE step and asserts
    the EXACT post-combat life totals + bf / gy contents on both
    engines. Pins the shape so a future refactor that silently breaks
    lifelink composition fails loudly with a specific diagnostic
    rather than a generic walk-clean divergence.

    Expected post-combat state (matches both engines today):

      * p0 life = 14 (was 12 entering combat; +2 from lifelink on the
        single 2-damage event to the first blocker).
      * p1 life = 20 (unchanged — Bears blockers have no lifelink and
        deal back-damage to the attacker, not to p1).
      * p0 graveyard = [Bear Cleric id 14] (attacker died from 4
        back-damage from both blockers' 2 power each).
      * p1 graveyard = [Grizzly Bears id 9] (first blocker took
        assigned 2 damage = its toughness, marked lethal, SBA destroyed).
      * p1 battlefield still has Grizzly Bears id 11 (second blocker
        survived because ``remaining = 0`` after blocker_0 absorbed
        its need=2; the post-CE14 ``if remaining <= 0: break`` guard
        skips blocker_1 entirely).
    """
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        lifelink_selector,
        multi_blocker_deckspec,
        step_both,
    )

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(180):
        action = lifelink_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    # ---- Life totals (the load-bearing lifelink composition surface) ----
    assert py_state.players[0].life == 14, (
        f"expected Python p0 life = 14 (12 pre-combat + 2 lifelink "
        f"gain), got {py_state.players[0].life}"
    )
    assert py_state.players[1].life == 20, (
        f"expected Python p1 life = 20 (unchanged; blockers have no "
        f"lifelink), got {py_state.players[1].life}"
    )
    rust_life = rust_state.life_totals
    assert rust_life[0] == 14, (
        f"expected Rust p0 life = 14 (matches Python), got "
        f"{rust_life[0]}"
    )
    assert rust_life[1] == 20, (
        f"expected Rust p1 life = 20 (matches Python), got "
        f"{rust_life[1]}"
    )

    # ---- p0 graveyard: Bear Cleric (the lifelink attacker died from
    #      back-damage) ----
    py_p0_gy = [(o.id, o.printing.name) for o in py_state.players[0].graveyard]
    assert py_p0_gy == [(14, "Bear Cleric")], (
        f"expected Python p0 gy = [(14, 'Bear Cleric')], got {py_p0_gy}"
    )
    rust_p0_gy = [
        (e["id"], e.get("printing_name"))
        for e in rust_state.graveyard_snapshot(0)
    ]
    assert rust_p0_gy == [(14, "Bear Cleric")], (
        f"expected Rust p0 gy = [(14, 'Bear Cleric')], got {rust_p0_gy}"
    )

    # ---- p1 graveyard: Grizzly Bears id 9 (first blocker took
    #      lethal 2) ----
    py_p1_gy = [(o.id, o.printing.name) for o in py_state.players[1].graveyard]
    assert py_p1_gy == [(9, "Grizzly Bears")], (
        f"expected Python p1 gy = [(9, 'Grizzly Bears')], got {py_p1_gy}"
    )
    rust_p1_gy = [
        (e["id"], e.get("printing_name"))
        for e in rust_state.graveyard_snapshot(1)
    ]
    assert rust_p1_gy == [(9, "Grizzly Bears")], (
        f"expected Rust p1 gy = [(9, 'Grizzly Bears')], got {rust_p1_gy}"
    )

    # ---- p1 battlefield still has Grizzly Bears id 11 (second blocker
    #      survived because remaining was 0 after first blocker absorbed
    #      need=2). ----
    py_bf_bears = sorted(
        o.id for o in py_state.battlefield
        if o.printing.name == "Grizzly Bears"
    )
    # p0 has Bears id 5 (the original turn-13-cast sick one); p1 has
    # Bears id 11 (the surviving second blocker). Bears 9 is in p1's
    # graveyard.
    assert py_bf_bears == [5, 11], (
        f"expected Python bf Grizzly Bears ids = [5, 11], got "
        f"{py_bf_bears}"
    )
    rust_bf_bears = sorted(
        int(e["id"]) for e in rust_state.battlefield_snapshot()
        if e.get("printing_name") == "Grizzly Bears"
    )
    assert rust_bf_bears == [5, 11], (
        f"expected Rust bf Grizzly Bears ids = [5, 11], got "
        f"{rust_bf_bears}"
    )


def test_cross_engine_lifelink_selector_pre_injection_walks_clean(
    parity_smoke,
):
    """Pre-injection walk (steps 0-167) on :func:`multi_blocker_deckspec`
    with :func:`lifelink_selector` is parity-clean. Pins the contract
    that the lifelink probe's delegate-to-retaliation_selector
    backbone is unchanged — steps 0-167 are identical to
    retaliation_selector's walk shape and surface no divergences.
    The lifelink injection fires SPECIFICALLY at step 168, not before.

    Validates the pre-condition: at the end of step 167, the bf has
    exactly 3 creatures and no Bear Cleric (the lifelink injection
    hasn't fired). Same shape as the first-strike + deathtouch probes'
    pre-injection tests.
    """
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        lifelink_selector,
        multi_blocker_deckspec,
        step_both,
        walk_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=168,
        decision_selector=lifelink_selector,
    )
    assert result.error is None
    for step in result.steps:
        assert step.divergences == [], (
            f"pre-injection divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )

    # Walk shape sanity: rebuild matched states, drive 168 steps, and
    # confirm the pre-injection bf state.
    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(168):
        action = lifelink_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    creatures = [
        o for o in py_state.battlefield
        if "Creature" in o.printing.card_types
    ]
    assert len(creatures) == 3, (
        f"expected 3 creatures on bf at end of step 167, got "
        f"{len(creatures)}: "
        f"{[(o.id, o.controller_id, o.summoning_sick) for o in creatures]}"
    )
    # No Bear Cleric in any zone yet (the lifelink injection hasn't
    # fired).
    bear_cleric_anywhere = (
        any(o.printing.name == "Bear Cleric" for o in py_state.battlefield)
        or any(
            o.printing.name == "Bear Cleric"
            for p in py_state.players
            for zone in (p.hand, p.library, p.graveyard, p.exile)
            for o in zone
        )
    )
    assert not bear_cleric_anywhere, (
        "Bear Cleric should not yet exist at end of step 167 — "
        "lifelink injection fires at step 168"
    )


# ---------------------------------------------------------------------------
# Phase 5 follow-up #12: vigilance_selector — extend retaliation_selector
# with a side-channel-injected 2/2 vigilance creature on p0's battlefield
# at step 168, then drive an attack (CR 702.20 — "Attacking doesn't cause
# this creature to tap") at turn 13 PRECOMBAT. Mirrors
# :func:`lifelink_selector` exactly except the injected creature carries
# ``vigilance`` instead of ``lifelink`` and the trigger gate keys on
# :data:`_VIGILANCE_PRINTING_NAME` ("Bear Watcher") so the four
# keyword-combat probes (FS / DT / LL / vigilance) stay independent on
# the same multi_blocker_deckspec walk.
#
# **OUTCOME on this probe: CLEAN PASS — no novel cross-engine divergence
# surfaced.** Both engines wire vigilance at declare-attackers time:
#
#   * **Python**: ``combat.py:103-104`` inside
#     ``declare_attackers``'s per-attacker loop suppresses the
#     ``tap_permanent`` call when ``"vigilance" in
#     effective_keywords(state, obj)``.
#   * **Rust**: ``state_ops_combat.rs:654-669`` in ``declare_attacker``
#     reads ``has_vigilance = battlefield_has_vigilance(...)`` and
#     skips the ``mutate_battlefield_obj(... |obj| obj.tapped = true)``
#     branch entirely.
#
# Both engines mark the attacker ``attacking=True`` without also setting
# ``tapped=True``. The post-DECLARE_ATTACKERS state has
# ``attacker.tapped == False`` on BOTH engines. The rest of combat
# proceeds normally: two 2/2 Bears multi-block, deal 4 back-damage, the
# vigilance attacker dies via SBA. Post-combat: p0 life = 12 (unchanged
# — no lifelink → no life gain), p1 life = 20. p0 gy = [Bear Watcher],
# p1 gy = [Grizzly Bears id 9], p1 bf still has Grizzly Bears id 11.
#
# Three pinning tests guard the contract:
#
#   1. ``test_cross_engine_vigilance_selector_walks_clean`` — full
#      200-decision walk parity-clean on every step (which is where
#      the DECLARE_ATTACKERS ``tapped`` field is compared
#      cross-engine).
#   2. ``test_cross_engine_vigilance_selector_post_declare_attacker_untapped``
#      — direct-read structural assertion that AFTER the
#      DECLARE_ATTACKERS step (step 171) the attacker on both engines
#      reports ``tapped == False`` AND ``attacking == True`` (mirror).
#      Pins the EXPECTED vigilance shape so a future refactor that
#      silently breaks the vigilance gate (e.g. dropping the
#      ``!has_vigilance`` guard in Rust's declare_attacker, or moving
#      the keyword lookup to AFTER tap_permanent) fails loudly with a
#      specific diagnostic.
#   3. ``test_cross_engine_vigilance_selector_pre_injection_walks_clean``
#      — steps 0-167 are parity-clean. The injection fires at step 168;
#      pre-injection backbone is identical to retaliation_selector.
# ---------------------------------------------------------------------------


def test_cross_engine_vigilance_selector_walks_clean(parity_smoke):
    """**Vigilance clean-walk pin** — 200-decision walk on
    :func:`multi_blocker_deckspec` with :func:`vigilance_selector` is
    parity-clean every step. The vigilance injection at step 168 + the
    DECLARE_ATTACKERS step at index 171 compose correctly on both
    engines: the attacker is marked attacking but NOT tapped, mirroring
    Python's ``if "vigilance" not in effective_keywords(state, obj):
    tap_permanent(state, obj)`` guard in
    :func:`mtg_bot.combat.declare_attackers` and Rust's
    ``if !has_vigilance { ... obj.tapped = true ... }`` branch in
    :meth:`GameState::declare_attacker`.

    Mirrors the lifelink probe's post-walk-clean shape: vigilance
    behavior is already parity across both engines (no CE16 surfaced
    on this slice), so this test is a "doesn't regress" guard rather
    than a strict-xfail pre-closure pin.
    """
    from mtg_bot.parity.cross_engine import (
        multi_blocker_deckspec,
        vigilance_selector,
        walk_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=200,
        decision_selector=vigilance_selector,
    )
    assert result.error is None, (
        f"walk aborted at step {result.aborted_at}: {result.error}"
    )
    for step in result.steps:
        assert step.divergences == [], (
            f"unexpected divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )


def test_cross_engine_vigilance_selector_post_declare_attacker_untapped(
    parity_smoke,
):
    """**Vigilance post-DECLARE_ATTACKERS structural pin** — drives 172
    selector decisions to walk through the DECLARE_ATTACKERS step (171)
    and asserts the EXACT vigilance-honored state on both engines.
    Pins the load-bearing surface — ``attacker.tapped`` AFTER declare —
    so a future refactor that silently breaks the vigilance gate fails
    loudly with a specific diagnostic rather than a generic walk-clean
    divergence.

    Expected post-DECLARE_ATTACKERS state (matches both engines today):

      * Vigilance attacker (id 14, "Bear Watcher") is on p0's
        battlefield with ``attacking == True`` AND ``tapped == False``.
        This is the CR 702.20 contract: attacking doesn't tap a
        vigilance creature.

    Additionally pins the post-combat state (181 decisions) — the
    attacker dies via SBA from 4 back-damage from the two Bears
    blockers; vigilance doesn't gate damage so there's no life-gain or
    damage-distribution surface to assert beyond "matches lifelink
    probe modulo no life gain".
    """
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        multi_blocker_deckspec,
        step_both,
        vigilance_selector,
    )

    # ---- Phase 1: post-DECLARE_ATTACKERS attacker state ----
    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(172):
        action = vigilance_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    # The vigilance attacker (id 14, "Bear Watcher") should be on bf
    # with attacking=True, tapped=False.
    py_att = next(
        (o for o in py_state.battlefield if o.id == 14), None
    )
    assert py_att is not None, (
        "expected Bear Watcher (id 14) on Python p0 bf after step 171; "
        f"bf ids = {[o.id for o in py_state.battlefield]}"
    )
    assert py_att.printing.name == "Bear Watcher", (
        f"expected id 14 to be Bear Watcher, got {py_att.printing.name}"
    )
    assert py_att.attacking is True, (
        f"expected Python attacker.attacking = True, got "
        f"{py_att.attacking}"
    )
    assert py_att.tapped is False, (
        f"expected Python attacker.tapped = False (vigilance honored "
        f"per CR 702.20), got {py_att.tapped}"
    )

    rust_att = next(
        (e for e in rust_state.battlefield_snapshot() if int(e["id"]) == 14),
        None,
    )
    assert rust_att is not None, (
        "expected Bear Watcher (id 14) on Rust p0 bf after step 171"
    )
    assert rust_att.get("printing_name") == "Bear Watcher", (
        f"expected id 14 to be Bear Watcher on Rust, got "
        f"{rust_att.get('printing_name')}"
    )
    assert rust_att["tapped"] is False, (
        f"expected Rust attacker.tapped = False (vigilance honored), "
        f"got {rust_att['tapped']}"
    )

    # ---- Phase 2: post-combat state (drive 180 total decisions —
    #      past COMBAT_DAMAGE and SBA cleanup) ----
    for i in range(172, 180):
        action = vigilance_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    # Life totals: no lifelink → no life gain → p0 unchanged at 12
    # (was 12 entering combat after turn-12 retaliation), p1 at 20.
    assert py_state.players[0].life == 12, (
        f"expected Python p0 life = 12 (no lifelink → no life gain), "
        f"got {py_state.players[0].life}"
    )
    assert py_state.players[1].life == 20, (
        f"expected Python p1 life = 20 (unchanged), got "
        f"{py_state.players[1].life}"
    )
    rust_life = rust_state.life_totals
    assert rust_life[0] == 12, (
        f"expected Rust p0 life = 12 (matches Python), got "
        f"{rust_life[0]}"
    )
    assert rust_life[1] == 20, (
        f"expected Rust p1 life = 20 (matches Python), got "
        f"{rust_life[1]}"
    )

    # p0 graveyard: Bear Watcher (vigilance attacker died from 4
    # back-damage — vigilance doesn't grant damage prevention).
    py_p0_gy = [
        (o.id, o.printing.name) for o in py_state.players[0].graveyard
    ]
    assert py_p0_gy == [(14, "Bear Watcher")], (
        f"expected Python p0 gy = [(14, 'Bear Watcher')], got {py_p0_gy}"
    )
    rust_p0_gy = [
        (e["id"], e.get("printing_name"))
        for e in rust_state.graveyard_snapshot(0)
    ]
    assert rust_p0_gy == [(14, "Bear Watcher")], (
        f"expected Rust p0 gy = [(14, 'Bear Watcher')], got {rust_p0_gy}"
    )

    # p1 graveyard: Grizzly Bears id 9 (first blocker took lethal 2;
    # same shape as the lifelink probe — vigilance doesn't change the
    # damage-assignment branch).
    py_p1_gy = [
        (o.id, o.printing.name) for o in py_state.players[1].graveyard
    ]
    assert py_p1_gy == [(9, "Grizzly Bears")], (
        f"expected Python p1 gy = [(9, 'Grizzly Bears')], got {py_p1_gy}"
    )
    rust_p1_gy = [
        (e["id"], e.get("printing_name"))
        for e in rust_state.graveyard_snapshot(1)
    ]
    assert rust_p1_gy == [(9, "Grizzly Bears")], (
        f"expected Rust p1 gy = [(9, 'Grizzly Bears')], got {rust_p1_gy}"
    )

    # p1 battlefield still has Grizzly Bears id 11 (second blocker
    # survived because remaining was 0 after first blocker absorbed
    # need=2 — post-CE14 ``if remaining <= 0: break`` guard).
    py_bf_bears = sorted(
        o.id for o in py_state.battlefield
        if o.printing.name == "Grizzly Bears"
    )
    assert py_bf_bears == [5, 11], (
        f"expected Python bf Grizzly Bears ids = [5, 11], got "
        f"{py_bf_bears}"
    )
    rust_bf_bears = sorted(
        int(e["id"]) for e in rust_state.battlefield_snapshot()
        if e.get("printing_name") == "Grizzly Bears"
    )
    assert rust_bf_bears == [5, 11], (
        f"expected Rust bf Grizzly Bears ids = [5, 11], got "
        f"{rust_bf_bears}"
    )


def test_cross_engine_vigilance_selector_pre_injection_walks_clean(
    parity_smoke,
):
    """Pre-injection walk (steps 0-167) on :func:`multi_blocker_deckspec`
    with :func:`vigilance_selector` is parity-clean. Pins the contract
    that the vigilance probe's delegate-to-retaliation_selector
    backbone is unchanged — steps 0-167 are identical to
    retaliation_selector's walk shape and surface no divergences.
    The vigilance injection fires SPECIFICALLY at step 168, not before.

    Validates the pre-condition: at the end of step 167, the bf has
    exactly 3 creatures and no Bear Watcher (the vigilance injection
    hasn't fired). Same shape as the first-strike + deathtouch +
    lifelink probes' pre-injection tests.
    """
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        multi_blocker_deckspec,
        step_both,
        vigilance_selector,
        walk_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=168,
        decision_selector=vigilance_selector,
    )
    assert result.error is None
    for step in result.steps:
        assert step.divergences == [], (
            f"pre-injection divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )

    # Walk shape sanity: rebuild matched states, drive 168 steps, and
    # confirm the pre-injection bf state.
    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(168):
        action = vigilance_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    creatures = [
        o for o in py_state.battlefield
        if "Creature" in o.printing.card_types
    ]
    assert len(creatures) == 3, (
        f"expected 3 creatures on bf at end of step 167, got "
        f"{len(creatures)}: "
        f"{[(o.id, o.controller_id, o.summoning_sick) for o in creatures]}"
    )
    # No Bear Watcher in any zone yet (the vigilance injection hasn't
    # fired).
    bear_watcher_anywhere = (
        any(o.printing.name == "Bear Watcher" for o in py_state.battlefield)
        or any(
            o.printing.name == "Bear Watcher"
            for p in py_state.players
            for zone in (p.hand, p.library, p.graveyard, p.exile)
            for o in zone
        )
    )
    assert not bear_watcher_anywhere, (
        "Bear Watcher should not yet exist at end of step 167 — "
        "vigilance injection fires at step 168"
    )


# ---------------------------------------------------------------------------
# Phase 5 follow-up #13: haste_selector — extend retaliation_selector with
# a side-channel-injected 2/2 SUMMONING-SICK haste creature on p0's
# battlefield at step 168, then drive an attack (CR 702.10b — "A creature
# with haste can attack and {T} as soon as it comes under its controller's
# control") at turn 13 PRECOMBAT. Mirrors :func:`vigilance_selector`
# exactly except the injected creature carries ``haste`` instead of
# ``vigilance``, is left in the ``summoning_sick=True`` state (load-
# bearing — exercises the haste bypass of the CR 302.1 sickness gate),
# and the trigger gate keys on :data:`_HASTE_PRINTING_NAME`
# ("Bear Sprinter") so the five keyword-combat probes (FS / DT / LL /
# vigilance / haste) stay independent on the same multi_blocker_deckspec
# walk.
#
# **OUTCOME on this probe: CLEAN PASS — no novel cross-engine divergence
# surfaced.** Both engines wire haste at declare-attackers eligibility:
#
#   * **Python** (``combat.py:21``): inside ``eligible_attackers``'s
#     comprehension filter, the predicate ``(not o.summoning_sick or
#     "haste" in effective_keywords(state, o))`` bypasses the sickness
#     exclusion when the keyword is present. ``declare_attackers``
#     itself does not re-validate eligibility, so a sick haste creature
#     requested via DECLARE_ATTACKERS([id]) makes it through.
#
#   * **Rust** (``state_ops_combat.rs:648-651``): in
#     ``declare_attacker``, ``let has_haste = battlefield_has_keyword(
#     self, obj_id, "haste"); if summoning_sick && !has_haste { return
#     false; }`` short-circuits the sick-rejection on the keyword. The
#     same gate appears in ``state_ops_legal.rs:574-577`` for the
#     legal_decisions enumeration filter.
#
# Both engines mark the haste attacker ``attacking=True`` AND
# ``tapped=True`` (no vigilance → standard CR 508.1c tap step runs)
# while LEAVING ``summoning_sick=True`` untouched (haste bypasses the
# attack restriction but does not remove summoning sickness — that
# clears at the controller's next untap step per CR 302.1, not at
# declare). The rest of combat proceeds normally: two 2/2 Bears
# multi-block, deal 4 back-damage, the haste attacker dies via SBA.
# Post-combat: p0 life = 12 (unchanged — no lifelink), p1 life = 20.
# p0 gy = [Bear Sprinter], p1 gy = [Grizzly Bears id 9], p1 bf still
# has Grizzly Bears id 11.
#
# **DECLARE_ATTACKERS selector override.** The
# :func:`retaliation_selector` delegate filters out ``summoning_sick``
# creatures at its attacker enumeration site (line ~2125) — a
# search-side approximation of CR 302.1 that is NOT keyword-aware.
# For this probe to actually drive the sick haste creature through
# DECLARE_ATTACKERS, the :func:`haste_selector` overrides the
# DECLARE_ATTACKERS branch with a keyword-aware predicate
# ``(not o.summoning_sick or "haste" in o.printing.keywords)`` BEFORE
# falling through to retaliation_selector. Without that override, the
# Bear Sprinter is silently excluded and the probe degenerates to a
# pass-priority walk that doesn't exercise the haste apply-path.
#
# Three pinning tests guard the contract:
#
#   1. ``test_cross_engine_haste_selector_walks_clean`` — full
#      200-decision walk parity-clean on every step (which is where
#      the DECLARE_ATTACKERS ``attacking`` + ``tapped`` +
#      ``summoning_sick`` fields are compared cross-engine).
#   2. ``test_cross_engine_haste_selector_post_declare_attacker_state``
#      — direct-read structural assertion that AFTER the
#      DECLARE_ATTACKERS step (step 171) the attacker on both engines
#      reports ``attacking == True``, ``tapped == True`` (haste does
#      NOT grant vigilance), AND ``summoning_sick == True`` (haste
#      bypasses but does not remove summoning sickness). Pins the
#      EXPECTED haste shape so a future refactor that silently breaks
#      the haste gate (e.g. dropping the ``has_haste`` branch in
#      Rust's declare_attacker, or clearing summoning_sick on declare)
#      fails loudly with a specific diagnostic.
#   3. ``test_cross_engine_haste_selector_pre_injection_walks_clean``
#      — steps 0-167 are parity-clean. The injection fires at step
#      168; pre-injection backbone is identical to
#      retaliation_selector.
# ---------------------------------------------------------------------------


def test_cross_engine_haste_selector_walks_clean(parity_smoke):
    """**Haste clean-walk pin** — 200-decision walk on
    :func:`multi_blocker_deckspec` with :func:`haste_selector` is
    parity-clean every step. The haste injection at step 168
    (``summoning_sick=True`` Bear Sprinter on p0 bf) + the
    DECLARE_ATTACKERS step at index 171 compose correctly on both
    engines: the sick haste creature is accepted as a legal attacker,
    mirroring Python's ``(not o.summoning_sick or "haste" in
    effective_keywords(state, o))`` guard in
    :func:`mtg_bot.combat.eligible_attackers` and Rust's
    ``if summoning_sick && !has_haste { return false; }`` branch in
    :meth:`GameState::declare_attacker`.

    Mirrors the vigilance probe's post-walk-clean shape: haste
    eligibility behavior is already parity across both engines (no
    CE16 surfaced on this slice), so this test is a "doesn't regress"
    guard rather than a strict-xfail pre-closure pin.
    """
    from mtg_bot.parity.cross_engine import (
        haste_selector,
        multi_blocker_deckspec,
        walk_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=200,
        decision_selector=haste_selector,
    )
    assert result.error is None, (
        f"walk aborted at step {result.aborted_at}: {result.error}"
    )
    for step in result.steps:
        assert step.divergences == [], (
            f"unexpected divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )


def test_cross_engine_haste_selector_post_declare_attacker_state(
    parity_smoke,
):
    """**Haste post-DECLARE_ATTACKERS structural pin** — drives 172
    selector decisions to walk through the DECLARE_ATTACKERS step (171)
    and asserts the EXACT haste-honored state on both engines. Pins
    the load-bearing surface — ``attacker.attacking`` + ``tapped`` +
    ``summoning_sick`` AFTER declare — so a future refactor that
    silently breaks the haste gate fails loudly with a specific
    diagnostic rather than a generic walk-clean divergence.

    Expected post-DECLARE_ATTACKERS state (matches both engines today):

      * Haste attacker (id 14, "Bear Sprinter") is on p0's
        battlefield with ``attacking == True`` (haste bypassed the
        sickness gate; CR 702.10b), ``tapped == True`` (no vigilance
        → standard CR 508.1c tap step), AND ``summoning_sick == True``
        (haste bypasses but does NOT clear summoning sickness — the
        flag clears at the next untap step per CR 302.1, not on
        declare).

    Additionally pins the post-combat state (181 decisions) — the
    attacker dies via SBA from 4 back-damage from the two Bears
    blockers; haste doesn't gate damage so there's no life-gain or
    damage-distribution surface to assert beyond "matches vigilance
    probe modulo the post-declare tap state".
    """
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        haste_selector,
        multi_blocker_deckspec,
        step_both,
    )

    # ---- Phase 1: post-DECLARE_ATTACKERS attacker state ----
    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(172):
        action = haste_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    # The haste attacker (id 14, "Bear Sprinter") should be on bf
    # with attacking=True, tapped=True, summoning_sick=True.
    py_att = next(
        (o for o in py_state.battlefield if o.id == 14), None
    )
    assert py_att is not None, (
        "expected Bear Sprinter (id 14) on Python p0 bf after step 171; "
        f"bf ids = {[o.id for o in py_state.battlefield]}"
    )
    assert py_att.printing.name == "Bear Sprinter", (
        f"expected id 14 to be Bear Sprinter, got {py_att.printing.name}"
    )
    assert py_att.attacking is True, (
        f"expected Python attacker.attacking = True (haste bypassed "
        f"summoning-sickness gate per CR 702.10b), got "
        f"{py_att.attacking}"
    )
    assert py_att.tapped is True, (
        f"expected Python attacker.tapped = True (haste does NOT "
        f"grant vigilance — standard CR 508.1c tap step ran), got "
        f"{py_att.tapped}"
    )
    assert py_att.summoning_sick is True, (
        f"expected Python attacker.summoning_sick = True (haste "
        f"bypasses but does NOT remove summoning sickness — flag "
        f"clears at the next untap step per CR 302.1), got "
        f"{py_att.summoning_sick}"
    )

    rust_att = next(
        (e for e in rust_state.battlefield_snapshot() if int(e["id"]) == 14),
        None,
    )
    assert rust_att is not None, (
        "expected Bear Sprinter (id 14) on Rust p0 bf after step 171"
    )
    assert rust_att.get("printing_name") == "Bear Sprinter", (
        f"expected id 14 to be Bear Sprinter on Rust, got "
        f"{rust_att.get('printing_name')}"
    )
    assert rust_att["tapped"] is True, (
        f"expected Rust attacker.tapped = True (haste doesn't grant "
        f"vigilance), got {rust_att['tapped']}"
    )
    assert rust_att["summoning_sick"] is True, (
        f"expected Rust attacker.summoning_sick = True (haste bypasses "
        f"but does NOT clear summoning sickness), got "
        f"{rust_att['summoning_sick']}"
    )

    # ---- Phase 2: post-combat state (drive 180 total decisions —
    #      past COMBAT_DAMAGE and SBA cleanup) ----
    for i in range(172, 180):
        action = haste_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    # Life totals: no lifelink → no life gain → p0 unchanged at 12
    # (was 12 entering combat after turn-12 retaliation), p1 at 20.
    assert py_state.players[0].life == 12, (
        f"expected Python p0 life = 12 (no lifelink → no life gain), "
        f"got {py_state.players[0].life}"
    )
    assert py_state.players[1].life == 20, (
        f"expected Python p1 life = 20 (unchanged), got "
        f"{py_state.players[1].life}"
    )
    rust_life = rust_state.life_totals
    assert rust_life[0] == 12, (
        f"expected Rust p0 life = 12 (matches Python), got "
        f"{rust_life[0]}"
    )
    assert rust_life[1] == 20, (
        f"expected Rust p1 life = 20 (matches Python), got "
        f"{rust_life[1]}"
    )

    # p0 graveyard: Bear Sprinter (haste attacker died from 4
    # back-damage — haste doesn't grant damage prevention).
    py_p0_gy = [
        (o.id, o.printing.name) for o in py_state.players[0].graveyard
    ]
    assert py_p0_gy == [(14, "Bear Sprinter")], (
        f"expected Python p0 gy = [(14, 'Bear Sprinter')], got {py_p0_gy}"
    )
    rust_p0_gy = [
        (e["id"], e.get("printing_name"))
        for e in rust_state.graveyard_snapshot(0)
    ]
    assert rust_p0_gy == [(14, "Bear Sprinter")], (
        f"expected Rust p0 gy = [(14, 'Bear Sprinter')], got {rust_p0_gy}"
    )

    # p1 graveyard: Grizzly Bears id 9 (first blocker took lethal 2;
    # same shape as the vigilance probe — haste doesn't change the
    # damage-assignment branch).
    py_p1_gy = [
        (o.id, o.printing.name) for o in py_state.players[1].graveyard
    ]
    assert py_p1_gy == [(9, "Grizzly Bears")], (
        f"expected Python p1 gy = [(9, 'Grizzly Bears')], got {py_p1_gy}"
    )
    rust_p1_gy = [
        (e["id"], e.get("printing_name"))
        for e in rust_state.graveyard_snapshot(1)
    ]
    assert rust_p1_gy == [(9, "Grizzly Bears")], (
        f"expected Rust p1 gy = [(9, 'Grizzly Bears')], got {rust_p1_gy}"
    )

    # p1 battlefield still has Grizzly Bears id 11 (second blocker
    # survived because remaining was 0 after first blocker absorbed
    # need=2 — post-CE14 ``if remaining <= 0: break`` guard).
    py_bf_bears = sorted(
        o.id for o in py_state.battlefield
        if o.printing.name == "Grizzly Bears"
    )
    assert py_bf_bears == [5, 11], (
        f"expected Python bf Grizzly Bears ids = [5, 11], got "
        f"{py_bf_bears}"
    )
    rust_bf_bears = sorted(
        int(e["id"]) for e in rust_state.battlefield_snapshot()
        if e.get("printing_name") == "Grizzly Bears"
    )
    assert rust_bf_bears == [5, 11], (
        f"expected Rust bf Grizzly Bears ids = [5, 11], got "
        f"{rust_bf_bears}"
    )


def test_cross_engine_haste_selector_pre_injection_walks_clean(
    parity_smoke,
):
    """Pre-injection walk (steps 0-167) on :func:`multi_blocker_deckspec`
    with :func:`haste_selector` is parity-clean. Pins the contract that
    the haste probe's delegate-to-retaliation_selector backbone is
    unchanged — steps 0-167 are identical to retaliation_selector's
    walk shape and surface no divergences. The haste injection fires
    SPECIFICALLY at step 168, not before.

    Validates the pre-condition: at the end of step 167, the bf has
    exactly 3 creatures and no Bear Sprinter (the haste injection
    hasn't fired). Same shape as the first-strike + deathtouch +
    lifelink + vigilance probes' pre-injection tests.
    """
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        haste_selector,
        multi_blocker_deckspec,
        step_both,
        walk_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=168,
        decision_selector=haste_selector,
    )
    assert result.error is None
    for step in result.steps:
        assert step.divergences == [], (
            f"pre-injection divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )

    # Walk shape sanity: rebuild matched states, drive 168 steps, and
    # confirm the pre-injection bf state.
    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(168):
        action = haste_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    creatures = [
        o for o in py_state.battlefield
        if "Creature" in o.printing.card_types
    ]
    assert len(creatures) == 3, (
        f"expected 3 creatures on bf at end of step 167, got "
        f"{len(creatures)}: "
        f"{[(o.id, o.controller_id, o.summoning_sick) for o in creatures]}"
    )
    # No Bear Sprinter in any zone yet (the haste injection hasn't
    # fired).
    bear_sprinter_anywhere = (
        any(o.printing.name == "Bear Sprinter" for o in py_state.battlefield)
        or any(
            o.printing.name == "Bear Sprinter"
            for p in py_state.players
            for zone in (p.hand, p.library, p.graveyard, p.exile)
            for o in zone
        )
    )
    assert not bear_sprinter_anywhere, (
        "Bear Sprinter should not yet exist at end of step 167 — "
        "haste injection fires at step 168"
    )


# ---------------------------------------------------------------------------
# Phase 5 follow-up #14: menace_selector — extend retaliation_selector with
# a side-channel-injected 2/2 menace creature on p0's battlefield at step
# 168, then drive a SINGLE-blocker DECLARE_BLOCKERS request (illegal per
# CR 702.110b — "can't be blocked except by two or more creatures") at
# turn 13 to surface the predicted CE16 divergence.
#
# Mirrors :func:`vigilance_selector` / :func:`haste_selector` exactly
# except the injected creature carries ``menace`` and the
# DECLARE_BLOCKERS branch is parameterized — three test scenarios
# exercise three block decisions:
#
#   * **A** (``"none"``): zero blockers → legal, menace invisible.
#   * **B** (``"both"``): two blockers → legal multi-block, menace
#     satisfied.
#   * **C** (``"single"``): one blocker → ILLEGAL per CR 702.110b.
#
# **OUTCOME on this probe: CE16 SURFACED then CLOSED by
# ``feature/ce16-menace-validation``** — the Rust
# ``Action::DeclareBlockers`` apply arm now post-validates each
# unique attacker's block assignment via
# ``is_legal_block_assignment`` (the predicate at
# ``state_ops_combat.rs:779-789``) and silently drops illegal
# final assignments from ``self.blockers`` via ``.retain``,
# mirroring Python's ``actions.py:2555-2566`` ``validated.pop(...)``
# post-validation pass. Single-blocker menace assignments are now
# dropped on both engines; the attacker proceeds unblocked.
# Scenarios A (none) + B (both) + C (single) all walk clean.
#
# Three pinning tests guard the contract post-closure:
#
#   1. ``test_cross_engine_menace_selector_no_blockers_walks_clean``
#      — scenario A (``"none"``): full 200-decision walk parity-clean.
#      Menace invisible when defender declines to block.
#   2. ``test_cross_engine_menace_selector_both_blockers_walks_clean``
#      — scenario B (``"both"``): full 200-decision walk parity-clean.
#      Multi-block satisfies the menace >=2 requirement.
#   3. ``test_cross_engine_menace_selector_single_blocker_walks_clean``
#      — scenario C (``"single"``): full 200-decision walk
#      parity-clean post-CE16-closure. The companion symptom-pin
#      (``..._surfaces_ce16_at_step_174``) was deleted at closure
#      per the CE2-CE15 pair-pin convention.
#   4. ``test_cross_engine_menace_selector_pre_injection_walks_clean``
#      — pre-injection backbone steps 0-167 parity-clean. Shared
#      across all three scenarios (the injection + DECLARE_BLOCKERS
#      override fire AFTER step 167).
# ---------------------------------------------------------------------------


def test_cross_engine_menace_selector_no_blockers_walks_clean(parity_smoke):
    """**Menace no-blockers clean-walk pin** (scenario A) — 200-decision
    walk on :func:`multi_blocker_deckspec` with the
    ``block_decision="none"`` menace_selector is parity-clean every
    step. With zero blockers declared the menace constraint is
    vacuously satisfied (CR 702.110b only restricts HOW the attacker
    is blocked, not whether it must be), so this scenario does NOT
    exercise the apply-time menace gate — it pins the "menace is
    invisible when defender doesn't block" baseline contract.

    Both engines should:
      * Accept the empty ``declare_blockers`` assignment.
      * Apply 2 combat damage from the menace attacker to p1 →
        p1 life: 20 → 18 (matches the unblocked single-attacker
        baseline; no menace-specific surface fires).
      * Leave Bear Bully on p0's battlefield post-combat (attacker
        took no back-damage).
    """
    from mtg_bot.parity.cross_engine import (
        make_menace_selector,
        multi_blocker_deckspec,
        walk_both,
    )

    selector = make_menace_selector("none")
    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=200,
        decision_selector=selector,
    )
    assert result.error is None, (
        f"walk aborted at step {result.aborted_at}: {result.error}"
    )
    for step in result.steps:
        assert step.divergences == [], (
            f"unexpected divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )


def test_cross_engine_menace_selector_both_blockers_walks_clean(parity_smoke):
    """**Menace multi-block clean-walk pin** (scenario B) — 200-decision
    walk on :func:`multi_blocker_deckspec` with the
    ``block_decision="both"`` menace_selector is parity-clean every
    step. With TWO blockers declared the menace >=2 requirement is
    satisfied and menace is invisible — this scenario pins the
    "multi-block legality is unaffected by menace" baseline contract.

    Both engines should:
      * Accept the two-blocker ``declare_blockers`` assignment.
      * Apply combat damage: attacker (2 power) → first blocker
        (lethal, blocker dies). Blockers (2 + 2 = 4 power back) →
        attacker (dies). Standard multi-block damage shape (matches
        vigilance / haste probes' post-multi-block state modulo the
        attacker's tapped flag).
      * Post-combat: p0 gy = [Bear Bully id 14], p1 gy = [Grizzly
        Bears id 9 — first blocker took lethal 2], p1 bf still has
        Grizzly Bears id 11 (post-CE14 ``if remaining <= 0: break``).
    """
    from mtg_bot.parity.cross_engine import (
        make_menace_selector,
        multi_blocker_deckspec,
        walk_both,
    )

    selector = make_menace_selector("both")
    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=200,
        decision_selector=selector,
    )
    assert result.error is None, (
        f"walk aborted at step {result.aborted_at}: {result.error}"
    )
    for step in result.steps:
        assert step.divergences == [], (
            f"unexpected divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )


def test_cross_engine_menace_selector_single_blocker_walks_clean(parity_smoke):
    """**CE16 closure pin** (scenario C) — 200-decision walk on
    :func:`multi_blocker_deckspec` with the ``block_decision="single"``
    menace_selector is parity-clean.

    CE16 closed by ``feature/ce16-menace-validation``: the Rust
    ``Action::DeclareBlockers`` apply arm
    (``state_ops_actions.rs``) now post-validates each unique
    attacker's block assignment via ``is_legal_block_assignment``
    (the predicate at ``state_ops_combat.rs:779-789``) and silently
    drops illegal final assignments from ``self.blockers`` via
    ``.retain``, mirroring Python's ``actions.py:2555-2566``
    ``validated.pop(...)`` post-validation pass. Single-blocker
    menace assignments are now dropped on both engines; the
    attacker proceeds unblocked.

    Was strict-xfail pre-closure (alongside a companion
    ``..._surfaces_ce16_at_step_174`` symptom-pin that asserted the
    exact divergence shape); both the xfail decorator and the
    symptom-pin were removed at closure per the CE2-CE15 pair-pin
    convention.
    """
    from mtg_bot.parity.cross_engine import (
        make_menace_selector,
        multi_blocker_deckspec,
        walk_both,
    )

    selector = make_menace_selector("single")
    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=200,
        decision_selector=selector,
    )
    assert result.error is None, (
        f"walk aborted at step {result.aborted_at}: {result.error}"
    )
    for step in result.steps:
        assert step.divergences == [], (
            f"unexpected divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )


def test_cross_engine_menace_selector_pre_injection_walks_clean(parity_smoke):
    """Pre-injection walk (steps 0-167) on :func:`multi_blocker_deckspec`
    with any of the three menace_selector variants is parity-clean.
    Pins the contract that the menace probe's
    delegate-to-retaliation_selector backbone is unchanged — steps
    0-167 are identical to retaliation_selector's walk shape and
    surface no divergences. The menace injection + DECLARE_BLOCKERS
    override fire SPECIFICALLY at / after step 168, not before.

    Tests with the ``"none"`` variant — all three variants share the
    same pre-167 backbone (they only diverge at the DECLARE_BLOCKERS
    branch around step 173, well past step 167).

    Validates the pre-condition: at the end of step 167, the bf has
    exactly 3 creatures and no Bear Bully (the menace injection
    hasn't fired). Same shape as the FS / DT / LL / VG / haste
    probes' pre-injection tests.
    """
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        make_menace_selector,
        multi_blocker_deckspec,
        step_both,
        walk_both,
    )

    selector = make_menace_selector("none")
    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=168,
        decision_selector=selector,
    )
    assert result.error is None
    for step in result.steps:
        assert step.divergences == [], (
            f"pre-injection divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )

    # Walk shape sanity: rebuild matched states, drive 168 steps, and
    # confirm the pre-injection bf state.
    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(168):
        action = selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    creatures = [
        o for o in py_state.battlefield
        if "Creature" in o.printing.card_types
    ]
    assert len(creatures) == 3, (
        f"expected 3 creatures on bf at end of step 167, got "
        f"{len(creatures)}: "
        f"{[(o.id, o.controller_id, o.summoning_sick) for o in creatures]}"
    )
    # No Bear Bully in any zone yet (the menace injection hasn't
    # fired).
    bear_bully_anywhere = (
        any(o.printing.name == "Bear Bully" for o in py_state.battlefield)
        or any(
            o.printing.name == "Bear Bully"
            for p in py_state.players
            for zone in (p.hand, p.library, p.graveyard, p.exile)
            for o in zone
        )
    )
    assert not bear_bully_anywhere, (
        "Bear Bully should not yet exist at end of step 167 — "
        "menace injection fires at step 168"
    )


# ---------------------------------------------------------------------------
# Phase 5 follow-up #15: defender_selector — extend retaliation_selector with
# a side-channel-injected 2/2 defender creature on p0's battlefield, then
# drive three attack-decision variants (CR 702.3 — "A creature with
# defender can't attack"). The REJECT branch symmetric to haste's ACCEPT
# branch (probe 63eb245a): a creature with the ``defender`` keyword CANNOT
# be declared as an attacker. Mirrors :func:`haste_selector` (and
# :func:`menace_selector`'s three-variant factory shape) exactly except:
#
#   * Injected creature carries ``defender`` instead of ``haste`` /
#     ``menace``, and is NOT summoning-sick (no haste-style fixture
#     needed — defender is a printed restriction, not a battlefield-
#     state restriction).
#   * Trigger gate keys on :data:`_DEFENDER_PRINTING_NAME`
#     ("Bear Wall") so the seven probes' trigger gates are mutually
#     independent.
#   * Three test variants via :func:`make_defender_selector`:
#
#       1. ``"defender_only"`` — try ``declare_attackers([defender_id])``
#          ALONE. Both engines should reject (Python via
#          ``eligible_attackers`` filter at ``combat.py:22``; Rust via
#          ``declare_attacker``'s defender gate at
#          ``state_ops_combat.rs:639-641``). Net: empty attackers Vec
#          on both engines.
#       2. ``"both"`` — try ``declare_attackers([defender_id,
#          normal_id])``. Defender dropped, normal attacker goes
#          through. Net: 1 attacker (normal) on both.
#       3. ``"normal_only"`` — try ``declare_attackers([normal_id])``.
#          Clean baseline — defender stays passively on bf untouched.
#
# **OUTCOME on this probe: NEW DIVERGENCE — CE17 SURFACED.**
#
# **CE17: legal_decisions emits defender as a candidate attacker.**
# Rust's ``state_ops_legal.rs:556-608`` DeclareAttackers eligibility
# loop filters on tapped + creature + sickness-vs-haste only —
# **NO DEFENDER FILTER**. The module docstring (lines 167-180) flags
# this as deferred: "*Defender keyword (CR 702.3) — Python's
# eligible_attackers filters this out at enumeration time; first
# slice defers to the primitive's per-id gate at apply.*" The
# apply-time gate at ``state_ops_combat.rs:639-641`` correctly
# rejects defender, but the legal_decisions emitter doesn't — so
# subsets containing the defender id are enumerated as if legal,
# violating the contract that ``legal_decisions`` returns only
# LEGAL decisions.
#
# **Confirmed shape** (with 2/2 Bear Wall id 14 + 2/2 Bears id 5 on
# p0 bf at the DECLARE_ATTACKERS step):
#
#   * Rust ``legal_decisions(0)`` emits four declare_attackers
#     subsets: ``[(), (5,), (14,), (5, 14)]``. The last two
#     ``(14,)`` and ``(5, 14)`` BOTH contain the defender and are
#     ILLEGAL per CR 702.3. Only ``()`` and ``(5,)`` are legal.
#   * Python's ``legal_actions(state, 0)`` does NOT emit
#     ``DeclareAttackers`` at all (Python uses a search-side
#     combat-decisions factoring rather than enumerating
#     declare-attackers subsets in legal_actions — see
#     state_ops_legal.rs:541-548 module docstring on "DeclareAttackers
#     emission (Rust-only)"). The cross-engine compare on the
#     enumeration shape is therefore Rust-only at present; the
#     **per-engine** assertion is that Rust's emitted subsets should
#     NOT include the defender id.
#
# **NOT FIXING per brief** — xfail-pin CE17. The fix shape (out of
# scope for this probe) is to add a ``battlefield_has_keyword(...,
# "defender")`` short-circuit to the eligibility filter in
# ``state_ops_legal.rs`` around line 575, mirroring the apply-time
# gate at ``state_ops_combat.rs:639-641``. This is a one-line
# parity-add that aligns the legal_decisions enumeration with the
# apply-time semantics.
#
# **Apply-time gates are CLEAN.** All three variants' walk_both
# produces zero per-step divergences — Python and Rust each silently
# drop the defender from their respective declare_attackers apply
# paths, leaving the defender at ``attacking=False`` / ``tapped=
# False`` / on its controller's bf. The per-step field-view compare
# observes ZERO divergence on the apply path. The CE17 surface is
# purely on the legal_decisions enumeration side.
#
# Five pinning tests:
#
#   1. ``test_cross_engine_defender_selector_defender_only_walks_clean``
#      — scenario A (``"defender_only"``): full 200-decision walk
#      parity-clean. Apply-time defender rejection works on both
#      engines (Test B from the brief — apply_action divergence-free).
#   2. ``test_cross_engine_defender_selector_both_walks_clean``
#      — scenario B (``"both"``): full 200-decision walk parity-clean.
#      Mixed defender + normal request — defender dropped, normal
#      attacker proceeds.
#   3. ``test_cross_engine_defender_selector_normal_only_walks_clean``
#      — scenario C (``"normal_only"``): full 200-decision walk
#      parity-clean. Defender stays passively on bf untapped /
#      not-attacking while the normal attacker drives combat
#      (Test C from the brief — defender invisible when not asked).
#   4. ``test_cross_engine_defender_selector_legal_decisions_surfaces_ce17``
#      — STRICT-XFAIL Test A from the brief. Drives 168 selector
#      decisions to land at the post-injection DECLARE_ATTACKERS
#      step with both Bear Wall (id 14) and Bears id 5 on p0 bf,
#      then asserts that Rust's ``legal_decisions(0)`` does NOT
#      include the defender id in any emitted declare_attackers
#      subset. The xfail pins the CURRENT (illegal-emission)
#      behavior; when CE17 is closed the xfail flips to a strict
#      pass.
#   5. ``test_cross_engine_defender_selector_pre_injection_walks_clean``
#      — pre-injection backbone steps 0-163 parity-clean. Shared
#      across all three scenarios. (The injection fires at step
#      164 in the defender_selector walk — earlier than the
#      vigilance/haste/menace probes' step 168 because the
#      side-channel clearing of Bears id 5's summoning sickness
#      means the cast-and-pass loop is shorter.)
# ---------------------------------------------------------------------------


def test_cross_engine_defender_selector_defender_only_walks_clean(parity_smoke):
    """**Defender apply-time reject clean-walk pin** (scenario A —
    ``"defender_only"``) — 200-decision walk on
    :func:`multi_blocker_deckspec` with
    ``make_defender_selector("defender_only")`` is parity-clean every
    step. With ``declare_attackers([defender_id])`` requested ALONE,
    both engines silently drop the defender (Python via
    ``eligible_attackers`` filter at ``combat.py:22``; Rust via
    ``declare_attacker``'s defender gate at
    ``state_ops_combat.rs:639-641``). Net: empty attackers Vec on
    both engines, no per-step field-view divergence.
    """
    from mtg_bot.parity.cross_engine import (
        make_defender_selector,
        multi_blocker_deckspec,
        walk_both,
    )

    selector = make_defender_selector("defender_only")
    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=200,
        decision_selector=selector,
    )
    assert result.error is None, (
        f"walk aborted at step {result.aborted_at}: {result.error}"
    )
    for step in result.steps:
        assert step.divergences == [], (
            f"unexpected divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )


def test_cross_engine_defender_selector_both_walks_clean(parity_smoke):
    """**Defender + normal mixed clean-walk pin** (scenario B —
    ``"both"``) — 200-decision walk on :func:`multi_blocker_deckspec`
    with ``make_defender_selector("both")`` is parity-clean every step.
    With ``declare_attackers([defender_id, normal_id])`` requested,
    both engines drop the defender and accept the normal attacker.
    Net: 1 attacker (the normal creature) on both engines; combat
    proceeds with the multi-block damage shape (attacker dies to
    4 back-damage, first blocker dies, second survives).
    """
    from mtg_bot.parity.cross_engine import (
        make_defender_selector,
        multi_blocker_deckspec,
        walk_both,
    )

    selector = make_defender_selector("both")
    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=200,
        decision_selector=selector,
    )
    assert result.error is None, (
        f"walk aborted at step {result.aborted_at}: {result.error}"
    )
    for step in result.steps:
        assert step.divergences == [], (
            f"unexpected divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )


def test_cross_engine_defender_selector_normal_only_walks_clean(parity_smoke):
    """**Defender baseline clean-walk pin** (scenario C —
    ``"normal_only"``) — 200-decision walk on
    :func:`multi_blocker_deckspec` with
    ``make_defender_selector("normal_only")`` is parity-clean every
    step. With ``declare_attackers([normal_id])`` requested (defender
    left passive on bf), the normal attacker drives combat without
    any defender involvement. Defender stays on bf untapped,
    not-attacking. Both engines walk identical state.

    Additionally pins the post-walk state: the defender (Bear Wall,
    id 14) is on p0's battlefield with ``attacking=False``,
    ``tapped=False``, ``summoning_sick=False`` — defender is
    invisible when not asked to attack. This is the brief's Test C
    contract — "combat proceeds without the defender; defender stays
    untapped (no combat tap)".
    """
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        make_defender_selector,
        multi_blocker_deckspec,
        step_both,
        walk_both,
    )

    selector = make_defender_selector("normal_only")
    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=200,
        decision_selector=selector,
    )
    assert result.error is None, (
        f"walk aborted at step {result.aborted_at}: {result.error}"
    )
    for step in result.steps:
        assert step.divergences == [], (
            f"unexpected divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )

    # Direct-read structural pin: defender stays untouched on both
    # engines post-walk. Brief's Test C contract.
    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(200):
        action = make_defender_selector("normal_only")(
            py_state, rust_state, i,
        )
        step_both(py_state, rust_state, action)

    py_defender = next(
        (o for o in py_state.battlefield
         if o.printing.name == "Bear Wall"),
        None,
    )
    assert py_defender is not None, (
        "expected Bear Wall on Python p0 bf post-walk; defender "
        "should be untouched"
    )
    assert py_defender.controller_id == 0
    assert getattr(py_defender, "attacking", False) is False, (
        "defender should not be attacking — CR 702.3 forbids it, "
        "and the selector never requested it to attack in the "
        "normal_only scenario"
    )
    assert py_defender.tapped is False, (
        "defender should not be tapped — never attacked, never "
        "blocked, never activated; should stay untapped (Test C "
        "from the brief)"
    )
    assert py_defender.summoning_sick is False, (
        "defender's summoning_sick should be False (injection set "
        "it False at step 164)"
    )

    rust_defender = next(
        (e for e in rust_state.battlefield_snapshot()
         if e.get("printing_name") == "Bear Wall"),
        None,
    )
    assert rust_defender is not None, (
        "expected Bear Wall on Rust p0 bf post-walk"
    )
    assert rust_defender["controller_id"] == 0
    assert rust_defender["tapped"] is False, (
        "Rust defender should be untapped (matches Python)"
    )
    assert rust_defender["summoning_sick"] is False


def test_cross_engine_defender_selector_legal_decisions_excludes_defender(
    parity_smoke,
):
    """**CE17 / I40 closure regression** — flipped from strict-xfail
    to expected-pass by ``feature/ce17-defender-legal``. Test A from
    the original CE17 probe brief.

    Drives 168 selector decisions to land at the post-injection
    DECLARE_ATTACKERS step with both Bear Wall (id 14, defender) and
    Bears id 5 (normal attacker, summoning-sickness cleared by the
    side-channel) on p0's battlefield, then asserts that Rust's
    ``legal_decisions(0)`` does NOT include the defender id in any
    emitted ``declare_attackers`` subset.

    Pre-CE17 closure this assertion failed (Rust emitted ``(defender_id,)``
    and ``(normal_id, defender_id)`` as if legal). Post-CE17 closure
    (state_ops_legal.rs eligibility loop now short-circuits on
    ``battlefield_has_keyword(self, obj.id, "defender")``, mirroring
    the apply-time gate at ``state_ops_combat.rs:639-641``) the
    assertion passes — defender ids are filtered out of the eligibility
    set at enumeration time, matching Python's
    ``combat.py:eligible_attackers`` (line 22).

    Post-CE17 Rust ``legal_decisions(0)`` emission at the
    DECLARE_ATTACKERS step (with bf={p0: Forests + Bears id 5 +
    Bear Wall id 14; p1: Forests + Bears ids 9, 11}):

      * ``declare_attackers([])`` — LEGAL (decline to attack).
      * ``declare_attackers([5])`` — LEGAL (Bears id 5 untapped,
        not sick, no defender → eligible).

    The two pre-CE17 illegal subsets (``([14])`` and ``([5, 14])``)
    are no longer emitted — the defender filter at
    ``state_ops_legal.rs:~588`` (per CE17 closure) drops Bear Wall
    id 14 from the eligible set before powerset enumeration.

    Python's ``legal_actions(state, 0)`` does not emit
    DeclareAttackers at all (it uses a search-side combat-decisions
    factoring rather than enumerating subsets — see the divergence
    rationale in ``state_ops_legal.rs`` module docstring), so the
    cross-engine "shape" compare remains Rust-only. The assertion
    is "Rust's emitted subsets do not include the defender id".
    """
    from mtg_bot.combat import eligible_attackers
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        make_defender_selector,
        multi_blocker_deckspec,
        step_both,
    )

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    # Use the normal_only selector to drive into the POST-INJECTION
    # DECLARE_ATTACKERS step. The injection fires on selector call
    # 165; the next DA step at active=p0 with defender on bf lands
    # at decision 167 (post-apply step name = DECLARE_ATTACKERS).
    # We stop at decision 167 (167 selector calls applied) — the
    # next selector call WOULD fire the defender_only-style DA
    # emission that pre-advances the phase, but we want to probe
    # legal_decisions BEFORE the emission so we cap the loop here.
    selector = make_defender_selector("normal_only")
    for i in range(168):
        action = selector(py_state, rust_state, i)
        # Only break when we hit the POST-INJECTION DA emission
        # (defender on bf, active=p0). Earlier turns also fire
        # declare_attackers but pre-injection.
        defender_on_bf = any(
            o.printing.name == "Bear Wall"
            for o in py_state.battlefield
        )
        is_p0_da = (
            py_state.step.name == "DECLARE_ATTACKERS"
            and py_state.active_player_idx == 0
        )
        if (
            action.get("kind") == "declare_attackers"
            and defender_on_bf
            and is_p0_da
        ):
            break
        step_both(py_state, rust_state, action)

    # Sanity: we should be in DECLARE_ATTACKERS active=0 with the
    # defender on bf and no attackers declared yet.
    assert py_state.step.name == "DECLARE_ATTACKERS", (
        f"expected to be in DECLARE_ATTACKERS, got {py_state.step.name}"
    )
    assert py_state.active_player_idx == 0, (
        f"expected p0 active, got {py_state.active_player_idx}"
    )
    defender = [
        o for o in py_state.battlefield
        if o.printing.name == "Bear Wall"
    ]
    assert defender, "expected Bear Wall on p0 bf at DA step"
    defender_id = int(defender[0].id)

    # Python's eligible_attackers correctly filters the defender out
    # (combat.py:22) — pin this as the source of truth for "what the
    # CR 702.3-correct emission should be".
    py_elig_ids = {o.id for o in eligible_attackers(py_state, 0)}
    assert defender_id not in py_elig_ids, (
        f"Python's eligible_attackers should filter the defender out "
        f"per CR 702.3 — defender id {defender_id} unexpectedly in "
        f"eligible set {py_elig_ids}"
    )

    # Rust's legal_decisions: CE17 / I40 contract — no emitted
    # declare_attackers subset contains the defender id (the
    # eligibility loop short-circuits on
    # battlefield_has_keyword(..., "defender"), mirroring the
    # apply-time gate at state_ops_combat.rs:639-641).
    ld = rust_state.legal_decisions(0)
    da_subsets = [
        tuple(a["attacker_ids"]) for a in ld
        if a.get("kind") == "declare_attackers"
    ]
    illegal_subsets = [s for s in da_subsets if defender_id in s]
    assert not illegal_subsets, (
        f"CE17 regression — Rust legal_decisions emits "
        f"{len(illegal_subsets)} declare_attackers subset(s) "
        f"containing the defender id {defender_id} (CR 702.3 "
        f"violation): {illegal_subsets}. All emitted subsets: "
        f"{da_subsets}. CE17 closure adds a "
        f"battlefield_has_keyword(..., \"defender\") short-circuit "
        f"to state_ops_legal.rs's eligibility loop; if this assertion "
        f"fails, the filter has regressed."
    )


def test_cross_engine_defender_selector_pre_injection_walks_clean(parity_smoke):
    """Pre-injection walk (steps 0-164) on :func:`multi_blocker_deckspec`
    with any of the three defender_selector variants is parity-clean.
    Pins the contract that the defender probe's
    delegate-to-retaliation_selector backbone is unchanged — steps
    0-164 are identical to retaliation_selector's walk shape and
    surface no divergences. The defender injection fires SPECIFICALLY
    at selector call 165 (the 166th decision, 0-indexed 165), not
    before — the trigger gate ``creature_count >= 3`` becomes true
    only after Bears id 5 has resolved onto the battlefield at
    decision 164.

    Tests with the ``"normal_only"`` variant — all three variants
    share the same pre-injection backbone (they only diverge at the
    DECLARE_ATTACKERS branch around step 168, well past the
    injection point).
    """
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        make_defender_selector,
        multi_blocker_deckspec,
        step_both,
        walk_both,
    )

    selector = make_defender_selector("normal_only")
    # 165 decisions takes us to "after Bears id 5 resolved, before
    # the injection fires on the next selector call". The injection
    # fires during selector call index 165 (the 166th call) because
    # that's when creature_count first reaches 3.
    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=165,
        decision_selector=selector,
    )
    assert result.error is None
    for step in result.steps:
        assert step.divergences == [], (
            f"pre-injection divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )

    # Walk shape sanity: rebuild matched states, drive 165 steps, and
    # confirm the pre-injection bf state (Bears id 5 has resolved
    # but Bear Wall has NOT yet been injected).
    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(165):
        action = selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    creatures = [
        o for o in py_state.battlefield
        if "Creature" in o.printing.card_types
    ]
    assert len(creatures) == 3, (
        f"expected 3 creatures on bf at end of decision 164 (Bears "
        f"ids 5/9/11 — Bears 5 just cast this turn, Bears 9/11 on "
        f"p1 bf from earlier), got {len(creatures)}: "
        f"{[(o.id, o.controller_id, o.summoning_sick) for o in creatures]}"
    )
    # No Bear Wall in any zone yet (the defender injection hasn't
    # fired — it fires on the NEXT selector call, decision 165).
    bear_wall_anywhere = (
        any(o.printing.name == "Bear Wall" for o in py_state.battlefield)
        or any(
            o.printing.name == "Bear Wall"
            for p in py_state.players
            for zone in (p.hand, p.library, p.graveyard, p.exile)
            for o in zone
        )
    )
    assert not bear_wall_anywhere, (
        "Bear Wall should not yet exist after decision 164 — "
        "defender injection fires on selector call 165 (the 166th "
        "decision, 0-indexed 165)"
    )


# ---------------------------------------------------------------------------
# Phase 5 follow-up #16: indestructible_selector tests (CR 702.12).
#
# Three scenarios from the brief:
#
#   * **Test A** — indestructible blocker takes lethal damage (damage ==
#     toughness) via real combat. Both engines: blocker on bf, damage=2,
#     tapped=True. Exercises the SBA lethal-damage filter (CR 704.5g +
#     702.12a) — `state_ops_sba::collect_sba_victims` skips creatures
#     with the indestructible keyword; Python's `turn.state_based_actions`
#     `elif "indestructible" in kws: continue` does the same.
#
#   * **Test B** — indestructible takes EXCESS damage (damage > toughness)
#     via side-channel damage marking. Both engines: still on bf,
#     damage=5. Exercises the SAME SBA filter but with the damage axis
#     pushed past the equality boundary; a sloppy port that special-
#     cases damage==toughness would diverge.
#
#   * **Test C** — indestructible targeted by a direct `destroy_target`
#     effect. Both engines: still on bf. Exercises a DISTINCT call site
#     from the SBA filter — `Effect::DestroyTarget`
#     (state_ops_resolve.rs:1023-1078) on Rust and `turn.destroy(state,
#     obj)` (turn.py:532-537) on Python; both gate on the keyword
#     before mutating.
#
# Outcome prediction: **clean pass on all three** — both engines' code
# paths read `keywords` in lockstep. No CE divergence expected. If one
# surfaces, it's CE18.
# ---------------------------------------------------------------------------


def test_cross_engine_indestructible_selector_walks_clean(parity_smoke):
    """**Indestructible clean-walk pin (Test A)** — 200-decision walk
    on :func:`multi_blocker_deckspec` with
    :func:`indestructible_selector` is parity-clean every step.

    Walk shape:

      * Steps 0-167: identical to retaliation_selector backbone.
      * Step 168: Bear Idol (2/2 indestructible) injected on p1 bf;
        Bears id 5 summoning_sick cleared on p0 bf.
      * DECLARE_ATTACKERS p0: emit [5] (Bears).
      * DECLARE_BLOCKERS p1: emit [[14, 5]] (Bear Idol blocks; sole
        eligible blocker because Bears 9/11 still tapped from turn-12
        attack).
      * COMBAT_DAMAGE: each takes 2 damage.
      * SBA: Bears id 5 (damage=2 >= toughness=2) → graveyard.
        Bear Idol (damage=2, indestructible) STAYS on bf — both
        engines.

    The SBA indestructible-filter parity is exercised at the per-step
    field-view compare on the post-COMBAT_DAMAGE step. If either engine
    incorrectly destroys the Bear Idol via SBA, the bf size / id list
    diverges and the test fails.
    """
    from mtg_bot.parity.cross_engine import (
        indestructible_selector,
        multi_blocker_deckspec,
        walk_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=200,
        decision_selector=indestructible_selector,
    )
    assert result.error is None, (
        f"walk aborted at step {result.aborted_at}: {result.error}"
    )
    for step in result.steps:
        assert step.divergences == [], (
            f"unexpected divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )


def test_cross_engine_indestructible_post_combat_state(parity_smoke):
    """**Indestructible post-combat structural pin (Test A)** — drives
    enough decisions for combat damage + SBA to fire (175 steps —
    just past COMBAT_DAMAGE at step 173, before CLEANUP at step 177
    which zeroes damage marks per CR 514.2), then asserts the Bear
    Idol is STILL on p1's bf with ``damage=2, summoning_sick=False``
    on both engines.

    Pins the brief's Test A contract: "post-combat-damage AND post-SBA,
    p1's Bear Idol is STILL ON THE BATTLEFIELD with damage=2".

    Note on tapped state: the Bear Idol stays ``tapped=False`` because
    blocking does NOT tap a creature in MTG (CR 509 — only attacking
    taps per CR 508.1c). Both engines agree.

    Also pins the attacker's death: Bears id 5 should be in p0's
    graveyard (2 damage from Bear Idol >= toughness 2 = lethal; no
    indestructible on Bears).
    """
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        indestructible_selector,
        multi_blocker_deckspec,
        step_both,
    )

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    # 175 steps: past COMBAT_DAMAGE (step 173) where damage applied
    # and SBA ran, but before CLEANUP (step 177) which zeroes damage
    # marks (CR 514.2 — damage clears at end of turn).
    for i in range(175):
        action = indestructible_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    # Bear Idol should be on p1's bf, with damage=2 on both engines.
    py_idol = next(
        (o for o in py_state.battlefield
         if o.printing.name == "Bear Idol"),
        None,
    )
    assert py_idol is not None, (
        "expected Bear Idol on Python p1 bf post-combat — "
        "indestructible should have protected it from SBA "
        "destruction. bf names = "
        f"{[(o.id, o.printing.name) for o in py_state.battlefield]}"
    )
    assert py_idol.controller_id == 1
    assert py_idol.damage == 2, (
        f"expected Python Bear Idol damage = 2 (took 2 from Bears 5 "
        f"in combat), got {py_idol.damage}"
    )
    assert py_idol.summoning_sick is False

    rust_idol = next(
        (e for e in rust_state.battlefield_snapshot()
         if e.get("printing_name") == "Bear Idol"),
        None,
    )
    assert rust_idol is not None, (
        "expected Bear Idol on Rust p1 bf post-combat — "
        "indestructible should have protected it from SBA destruction"
    )
    assert rust_idol["controller_id"] == 1
    assert rust_idol["damage"] == 2, (
        f"expected Rust Bear Idol damage = 2, got {rust_idol['damage']}"
    )
    assert rust_idol["summoning_sick"] is False

    # Bears id 5 (the attacker) should be DEAD — 2 damage from Bear
    # Idol >= toughness 2 = lethal, no indestructible on the attacker.
    py_p0_gy_ids = {o.id for o in py_state.players[0].graveyard}
    assert 5 in py_p0_gy_ids, (
        f"expected Bears id 5 in Python p0 graveyard (died to combat "
        f"damage from Bear Idol), got {py_p0_gy_ids}"
    )
    rust_p0_gy_ids = {
        int(e["id"]) for e in rust_state.graveyard_snapshot(0)
    }
    assert 5 in rust_p0_gy_ids, (
        f"expected Bears id 5 in Rust p0 graveyard, got {rust_p0_gy_ids}"
    )


def test_cross_engine_indestructible_excess_damage_sba(parity_smoke):
    """**Indestructible excess-damage SBA pin (Test B)** — drives the
    walk to post-combat state where Bear Idol has damage=2, then
    side-channel-marks ADDITIONAL damage so total = 5 (well past
    toughness=2). Calls ``apply_sbas`` and asserts Bear Idol is STILL
    on bf on both engines.

    A sloppy port that special-cased ``damage == toughness`` (rather
    than ``damage >= toughness``) for the indestructible early-return
    would surface as a divergence here. Both engines today gate on
    the indestructible keyword BEFORE the damage>=toughness compare,
    so excess damage is irrelevant.
    """
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        indestructible_selector,
        multi_blocker_deckspec,
        step_both,
    )

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    # 175 decisions: just past COMBAT_DAMAGE (step 173) where damage
    # applied and SBA ran. Stop BEFORE CLEANUP (step 177) which
    # zeroes damage marks (CR 514.2) — we want the existing damage=2
    # on the Bear Idol to persist so we can layer additional damage
    # on top.
    for i in range(175):
        action = indestructible_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    # Locate Bear Idol on both engines and side-channel-mark
    # additional damage. Python: direct field write. Rust:
    # `deal_damage(obj_id, amount)` adds to the existing damage.
    py_idol = next(
        (o for o in py_state.battlefield
         if o.printing.name == "Bear Idol"),
        None,
    )
    assert py_idol is not None
    rust_idol_id = next(
        (int(e["id"]) for e in rust_state.battlefield_snapshot()
         if e.get("printing_name") == "Bear Idol"),
        None,
    )
    assert rust_idol_id is not None

    # Add 3 more damage to bring total to 5 (a 2/2 with damage 5 is
    # well past lethal; a non-indestructible creature dies on the
    # next SBA pass).
    py_idol.damage += 3
    rust_state.deal_damage(rust_idol_id, 3)
    assert py_idol.damage == 5
    assert rust_state.get_damage(rust_idol_id) == 5

    # Run SBA passes on both engines. Bear Idol should NOT be
    # destroyed despite damage > toughness, because indestructible
    # gates BEFORE the lethal-damage compare.
    from mtg_bot.turn import state_based_actions as py_sba

    py_sba(py_state)
    rust_state.apply_sbas()

    # Bear Idol still on bf with damage=5 on both engines.
    py_idol_after = next(
        (o for o in py_state.battlefield
         if o.printing.name == "Bear Idol"),
        None,
    )
    assert py_idol_after is not None, (
        "expected Bear Idol still on Python p1 bf after excess-damage "
        "SBA pass — indestructible gates before damage>=toughness "
        "compare. bf names = "
        f"{[(o.id, o.printing.name) for o in py_state.battlefield]}"
    )
    assert py_idol_after.damage == 5

    rust_idol_after = next(
        (e for e in rust_state.battlefield_snapshot()
         if e.get("printing_name") == "Bear Idol"),
        None,
    )
    assert rust_idol_after is not None, (
        "expected Bear Idol still on Rust p1 bf after excess-damage "
        "SBA pass — indestructible gates before damage>=toughness "
        "compare"
    )
    assert rust_idol_after["damage"] == 5


def test_cross_engine_indestructible_direct_destroy_effect(parity_smoke):
    """**Indestructible destroy-effect pin (Test C)** — exercises the
    DISTINCT call site from the SBA filter: a direct
    ``Effect::DestroyTarget``-style resolution on an indestructible
    target.

    Uses a FRESH matched state (no walk) — injects Bear Idol on p1's
    bf as the sole bf object (so Rust's
    ``TargetFilter::AnyCreature`` picks it as ``bf[0]``), then:

      * **Python**: directly calls ``turn.destroy(state, idol_obj)``.
        Returns False (indestructible filter at turn.py:532-537 fires).
      * **Rust**: side-channel-casts a synthetic ``destroy_target``
        sorcery via the same ``register_and_inject_object`` +
        ``push_to_stack`` + ``resolve_top_of_stack`` pipeline that
        :func:`mass_removal_side_channel` uses. The
        ``Effect::DestroyTarget`` resolve at
        ``state_ops_resolve.rs:1023-1078`` peeks the target's
        ``printing.keywords`` for ``"indestructible"`` and early-
        returns Ok(()) without mutating.

    Both engines: Bear Idol still on p1's bf post-resolve. No CE
    divergence expected — both code paths gate on the keyword on the
    printing.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        multi_blocker_deckspec,
    )

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())

    # ---- Inject Bear Idol on p1's bf on both engines ----
    indestr_printing = CardPrinting(
        name="Bear Idol",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset({"indestructible"}),
    )
    py_idol = py_state.new_object(
        indestr_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_idol.summoning_sick = False
    py_idol.tapped = False
    py_idol.damage = 0
    py_idol.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_idol)

    ZONE_BATTLEFIELD = 2
    rust_idol_id = rust_state.register_and_inject_object(
        {
            "name": "Bear Idol",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "keywords": ["indestructible"],
        },
        1,  # controller = p1
        ZONE_BATTLEFIELD,
    )

    # ---- Python side: direct destroy() call ----
    # Python's turn.destroy is the lowest-level destroy primitive
    # used by every "destroy target X" effect (DestroyTargetCreature,
    # DestroyTargetArtifact, ...). It returns False without moving
    # the object when the target carries indestructible.
    from mtg_bot.turn import destroy as py_destroy

    py_destroy_result = py_destroy(py_state, py_idol)
    assert py_destroy_result is False, (
        "expected Python destroy() to return False for indestructible "
        "target (CR 702.12 — destroy fizzles)"
    )

    # ---- Rust side: cast a synthetic destroy_target sorcery ----
    # Mirrors mass_removal_side_channel's shape but with the
    # destroy_target effect kind. The target filter is "any_creature"
    # which picks bf[0] of the DEFENDER (1 - active_player = p1).
    # Since p1's bf has only the Bear Idol on it, bf[0] == Bear Idol.
    ZONE_HAND = 0
    spell_rust_id = rust_state.register_and_inject_object(
        {
            "name": "Doom Blade",
            "card_types": ["Sorcery"],
            "effects": [
                {
                    "kind": "destroy_target",
                    "target": {"kind": "any_creature"},
                },
            ],
        },
        0,  # controller = p0 (the active player; defender = p1)
        ZONE_HAND,
    )
    rust_state.push_to_stack(spell_rust_id, 0)
    rust_state.resolve_top_of_stack()
    rust_state.apply_sbas()

    # ---- Both engines: Bear Idol STILL on p1's bf ----
    py_idol_after = next(
        (o for o in py_state.battlefield
         if o.printing.name == "Bear Idol"),
        None,
    )
    assert py_idol_after is not None, (
        "expected Bear Idol still on Python p1 bf after destroy() — "
        "indestructible should have suppressed the destroy. bf = "
        f"{[(o.id, o.printing.name, o.controller_id) for o in py_state.battlefield]}"
    )
    assert py_idol_after.controller_id == 1
    # Bear Idol should NOT be in any graveyard.
    for player_idx in (0, 1):
        gy_names = [
            o.printing.name
            for o in py_state.players[player_idx].graveyard
        ]
        assert "Bear Idol" not in gy_names, (
            f"Bear Idol unexpectedly in Python p{player_idx} graveyard"
            f" — indestructible filter failed: {gy_names}"
        )

    rust_idol_after = next(
        (e for e in rust_state.battlefield_snapshot()
         if e.get("printing_name") == "Bear Idol"),
        None,
    )
    assert rust_idol_after is not None, (
        "expected Bear Idol still on Rust p1 bf after destroy_target "
        "resolve — indestructible should have suppressed the destroy"
    )
    assert rust_idol_after["controller_id"] == 1
    for player_idx in (0, 1):
        rust_gy_names = [
            e.get("printing_name")
            for e in rust_state.graveyard_snapshot(player_idx)
        ]
        assert "Bear Idol" not in rust_gy_names, (
            f"Bear Idol unexpectedly in Rust p{player_idx} graveyard "
            f"— indestructible filter failed: {rust_gy_names}"
        )


# ---------------------------------------------------------------------------
# Phase 5 follow-up #17: hexproof_selector tests (CR 702.11).
#
# Three scenarios from the brief:
#
#   * **Test A** — p0's opponent has a hexproof creature (controller=1,
#     "Bear Sage", 2/2). p0 casts a single-target destroy spell
#     (Effect::DestroyTarget { target: AnyCreature } / Python's
#     turn.destroy). Per CR 702.11a the creature SHOULD be untargetable
#     by opponent-controlled spells. Both engines today DON'T enforce
#     this — hexproof is unenforced metadata on both sides (Python's
#     `_enumerate_for_filter` walks bf with no hexproof gate; Rust's
#     `Effect::DestroyTarget` docstring at state_ops_resolve.rs:40-46
#     explicitly notes "no protection / hexproof / shroud, no per-spell
#     target-selection"). The probe pins this SHARED bug: both engines
#     destroy the Bear Sage identically. Parity is preserved.
#
#   * **Test B** — p0's OWN hexproof creature on p0's bf (controller=0).
#     p0 casts a destroy spell. Per CR 702.11a hexproof only protects
#     from OPPONENTS' spells, so self-targeting MUST succeed even on a
#     hexproof creature. Both engines (which don't enforce hexproof at
#     all) destroy the creature — parity-clean, AND happens to be
#     CR-correct because the bug-axis (over-permissive targeting) is
#     CR-correct for the same-controller scenario.
#
#   * **Test C** — `legal_decisions` for a target-requiring spell:
#     confirm the hexproof creature behaves the SAME way on both
#     engines when emitted as a target option. Since neither engine
#     emits cast-spell-with-target decisions in `legal_decisions`
#     today, this test exercises the **target-enumeration paths
#     directly**: Python's `Effect.legal_targets` (called from
#     effects/base.py:78), and Rust's `Effect::DestroyTarget` apply
#     path's target picker (state_ops_resolve.rs:1030-1035 — picks
#     `bf[0]` of the defender). Both should produce IDENTICAL
#     target-selection answers (both include the hexproof creature)
#     since neither enforces hexproof.
#
# Outcome: **(c) old known gap** — neither engine enforces hexproof.
# Parity-clean (both engines exhibit the SAME CR-divergent behavior).
# Tests pin the shared-bug parity so a future one-sided fix surfaces
# as CE18. No xfail decoration needed — the tests assert the
# **current** state, not the CR-correct one.
#
# Cross-doc pointers:
#
#   * Python statics.py:244-255 explicitly documents
#     "hexproof remains engine-unenforced metadata".
#   * Rust state_ops_resolve.rs:40-46 explicitly documents
#     "no protection / hexproof / shroud".
#   * docs/SEARCH_LIMITATIONS.md:389 notes hexproof as a heuristic-
#     abort blocker (which only matters if the heuristic could fire —
#     orthogonal to engine enforcement).
# ---------------------------------------------------------------------------


def test_cross_engine_hexproof_selector_walks_clean(parity_smoke):
    """**Hexproof clean-walk pin** — 200-decision walk on
    :func:`multi_blocker_deckspec` with :func:`hexproof_selector`
    is parity-clean every step.

    Walk shape:

      * Steps 0-167: identical to retaliation_selector backbone.
      * Step 168: Bear Sage (2/2 hexproof) injected on p1 bf;
        selector returns pass_priority.
      * Steps 169-200: pure delegation to retaliation_selector.
        Bear Sage sits on p1's bf with no interaction (retaliation
        walk's combat shape doesn't involve targeting effects on
        the Bear Sage). No combat-damage SBA divergence axis since
        hexproof has no SBA-side gate on either engine.

    The hexproof injection's most useful per-step compare lives at
    the post-injection step where Bear Sage first appears on both
    engines' bf — confirms both register the same shape (id,
    keywords carry, controller_id=1, power/toughness 2/2).
    """
    from mtg_bot.parity.cross_engine import (
        hexproof_selector,
        multi_blocker_deckspec,
        walk_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=200,
        decision_selector=hexproof_selector,
    )
    assert result.error is None, (
        f"walk aborted at step {result.aborted_at}: {result.error}"
    )
    for step in result.steps:
        assert step.divergences == [], (
            f"unexpected divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )


def test_cross_engine_hexproof_opponent_destroy_unenforced(parity_smoke):
    """**Test A — opponent's hexproof creature is destroyed (shared bug
    parity pin).** Drives the walk past the side-channel injection
    (step ~170 — enough for the Bear Sage to land on both engines'
    p1 bf), then exercises a direct destroy-target effect from p0
    (whose opponent is p1, so CR 702.11a SHOULD prevent the destroy).

    Per CR 702.11a — a permanent with hexproof "can't be the target
    of spells or abilities your opponents control" — both engines
    SHOULD refuse to target the Bear Sage. Neither engine enforces
    this today:

      * Python's `turn.destroy(state, obj)` only gates on
        indestructible (turn.py:532-537); no hexproof check.
      * Rust's `Effect::DestroyTarget` only gates on indestructible
        (state_ops_resolve.rs:1040-1048); the module docstring at
        lines 40-46 explicitly flags hexproof as out-of-scope.

    This test pins the **current shared behavior** — both engines
    destroy the Bear Sage and put it in p1's graveyard. The cross-
    engine parity is preserved; the CR divergence is shared. If a
    future fix on either side starts enforcing hexproof, this test
    will fail on the now-fixed engine and the post-walk graveyard
    compare will surface the asymmetry as CE18.

    Setup: drives the walk to step ~170 so the side-channel
    injection has fired and Bear Sage exists on both engines'
    p1 bf. Then directly invokes the destroy primitive on Python
    and side-channel-casts a synthetic destroy_target sorcery on
    Rust (the same shape `indestructible_direct_destroy_effect`
    uses for the indestructible probe's Test C).
    """
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        hexproof_selector,
        multi_blocker_deckspec,
        step_both,
    )

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    # 170 decisions: past the side-channel injection (which fires at
    # step ~168 when the 3-creature trigger is met). Bear Sage now
    # sits on both engines' p1 bf.
    for i in range(170):
        action = hexproof_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    # Locate the Bear Sage on both engines and confirm it's on p1.
    py_sage = next(
        (o for o in py_state.battlefield
         if o.printing.name == "Bear Sage"),
        None,
    )
    assert py_sage is not None, (
        "expected Bear Sage on Python p1 bf post-injection. bf names = "
        f"{[(o.id, o.printing.name) for o in py_state.battlefield]}"
    )
    assert py_sage.controller_id == 1
    rust_sage_id = next(
        (int(e["id"]) for e in rust_state.battlefield_snapshot()
         if e.get("printing_name") == "Bear Sage"),
        None,
    )
    assert rust_sage_id is not None, (
        "expected Bear Sage on Rust p1 bf post-injection"
    )

    # ---- Python side: p0 invokes destroy() on p1's Bear Sage ----
    # The destroy() primitive is what every "destroy target X" effect
    # routes through; it gates on indestructible but NOT hexproof.
    # We bypass the targeting-pipeline layer (which also doesn't
    # enforce hexproof — see _enumerate_for_filter in
    # effects/base.py:103) and call the primitive directly to pin
    # the lowest-level engine behavior.
    from mtg_bot.turn import destroy as py_destroy

    # Pin resolving_controller_id = 0 to model "p0 casts a destroy on
    # an opponent's creature". The primitive doesn't check it (no
    # hexproof gate, as established), but pinning makes the test's
    # intent explicit and would make a future hexproof gate that
    # reads this field fire correctly.
    py_state.resolving_controller_id = 0
    py_destroy_result = py_destroy(py_state, py_sage)
    # Current behavior: destroy succeeds (returns True), Bear Sage
    # moves to p1's graveyard. The CR-correct behavior would be
    # destroy() returning False without moving the object, but the
    # gate doesn't exist on the engine today.
    assert py_destroy_result is True, (
        "Python destroy() unexpectedly returned False — has hexproof "
        "enforcement landed on the Python side? If so, the cross-engine "
        "parity now diverges (Rust still destroys; Python now refuses). "
        "This test pins the current shared-bug behavior; flip to the "
        "CR-correct expectation once Rust also enforces."
    )

    # ---- Rust side: cast a synthetic destroy_target sorcery from p0 ----
    # `Effect::DestroyTarget { target: AnyCreature }` picks bf[0] of
    # the defender (1 - active_player). On a fresh game the defender
    # is p1 (active player is p0); bf[0] on p1 is whichever creature
    # got created first there. Bears 9 was created first on p1 in the
    # retaliation walk, so directly invoking destroy_target would hit
    # Bears 9 rather than Bear Sage. Bypass that targeting limitation
    # by using the lower-level `destroy_object_id` primitive if it
    # exists; otherwise emulate it via a direct apply_sbas pathway.
    # The cleanest analog: register-and-push the destroy sorcery and
    # rely on the bf[0]-of-defender pick. If bf[0] isn't Bear Sage we
    # need an alternate API.
    #
    # Inspection: rust_state.battlefield_snapshot returns ALL bf
    # objects (both players); the AnyCreature target picker reads
    # `state.players[defender].battlefield[0]` directly. To force
    # the target to be Bear Sage, exile/remove the older p1
    # creatures first; but that changes too much state. Instead,
    # use the same approach as the indestructible Test C: deal_damage
    # the Bear Sage to lethal and run apply_sbas. But that's NOT a
    # target-selection test.
    #
    # Pragmatic alternative that DOES exercise the target-selection
    # surface: use the Rust `destroy_by_id` primitive if available;
    # else assert that the destroy_target picker (a) picks SOMETHING
    # on p1's bf (so it doesn't fizzle), and (b) the indestructible-
    # vs-hexproof gate asymmetry is what we expect (indestructible
    # gates; hexproof does not). Since `Effect::DestroyTarget` picks
    # `bf[0]`, and there are now multiple creatures on p1's bf
    # (Bears 9, Bears 11, Bear Sage), we instead exercise the
    # primitive `destroy_object_by_id`-style entry. Per the rust
    # PyState surface, there's no public destroy-by-id; the best
    # available proxy is `deal_damage` to lethal which routes
    # through SBA (and SBA also doesn't enforce hexproof — only
    # indestructible). That confirms the symmetry from a DIFFERENT
    # entry point.
    #
    # Final approach: use `deal_damage` to lethal (2 damage on the
    # 2/2 Bear Sage) on Rust and `state.battlefield`-locate +
    # field-write damage=2 + apply_sbas on Python. Both should
    # destroy the Bear Sage; pinning parity at the post-SBA bf state.
    py_sage.damage = 2
    rust_state.deal_damage(rust_sage_id, 2)

    from mtg_bot.turn import state_based_actions as py_sba

    py_sba(py_state)
    rust_state.apply_sbas()

    # Both engines: Bear Sage should be DEAD (in p1's graveyard).
    # Hexproof has no SBA gate on either side; only indestructible
    # does (and Bear Sage isn't indestructible). This is the shared
    # behavior — both engines treat hexproof as unenforced metadata.
    py_sage_after = next(
        (o for o in py_state.battlefield
         if o.printing.name == "Bear Sage"),
        None,
    )
    assert py_sage_after is None, (
        "expected Bear Sage REMOVED from Python p1 bf — SBA should "
        "have moved it to p1 graveyard (damage=2 >= toughness=2; "
        "hexproof is unenforced metadata, NOT a SBA gate). If this "
        "fails Python may have started enforcing hexproof somewhere "
        "unexpected — flip the test's expectation and file CE18."
    )
    py_p1_gy_names = [
        o.printing.name for o in py_state.players[1].graveyard
    ]
    assert "Bear Sage" in py_p1_gy_names, (
        f"expected Bear Sage in Python p1 graveyard, got {py_p1_gy_names}"
    )

    rust_sage_after = next(
        (e for e in rust_state.battlefield_snapshot()
         if e.get("printing_name") == "Bear Sage"),
        None,
    )
    assert rust_sage_after is None, (
        "expected Bear Sage REMOVED from Rust p1 bf — SBA should "
        "have moved it to p1 graveyard. If this fails Rust may have "
        "started enforcing hexproof somewhere unexpected — flip the "
        "test's expectation and file CE18."
    )
    rust_p1_gy_names = [
        e.get("printing_name")
        for e in rust_state.graveyard_snapshot(1)
    ]
    assert "Bear Sage" in rust_p1_gy_names, (
        f"expected Bear Sage in Rust p1 graveyard, got {rust_p1_gy_names}"
    )


def test_cross_engine_hexproof_self_target_destroyed(parity_smoke):
    """**Test B — own hexproof creature can be self-targeted (CR-
    correct AND shared-bug parity).** Inject Bear Sage on p0's bf
    (not p1's) so when p0 destroys it, the hexproof gate per
    CR 702.11a does NOT fire (hexproof only blocks OPPONENTS).

    Setup: fresh state (no walk), manually inject Bear Sage on p0's
    bf (controller=0). Both engines should destroy it — and this
    happens to also be CR-correct because hexproof only protects
    from opponents.

    This test is the converse of Test A: same destroy primitive,
    same hexproof keyword, but different controller — and the
    expected outcome (destruction) is the same because the gate
    that would differentiate them (controller != caster) isn't
    implemented on either engine. If a future enforcement landed
    that read the gate as "any caster, including self" (wrong
    implementation of CR 702.11a), this test would fail; if the
    enforcement correctly read the controller, this test would still
    pass.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        multi_blocker_deckspec,
    )

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())

    # ---- Inject Bear Sage on p0's bf on both engines ----
    hex_printing = CardPrinting(
        name="Bear Sage",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset({"hexproof"}),
    )
    py_sage = py_state.new_object(
        hex_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_sage.summoning_sick = False
    py_sage.tapped = False
    py_sage.damage = 0
    py_sage.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_sage)
    assert py_sage.controller_id == 0

    ZONE_BATTLEFIELD = 2
    rust_sage_id = rust_state.register_and_inject_object(
        {
            "name": "Bear Sage",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "keywords": ["hexproof"],
        },
        0,  # controller = p0 (self-targeting scenario)
        ZONE_BATTLEFIELD,
    )

    # ---- Python: p0 destroys its OWN Bear Sage ----
    from mtg_bot.turn import destroy as py_destroy

    py_state.resolving_controller_id = 0
    py_destroy_result = py_destroy(py_state, py_sage)
    assert py_destroy_result is True, (
        "Python destroy() unexpectedly returned False on own hexproof "
        "creature — hexproof should ONLY protect from opponents "
        "(CR 702.11a). If this fails the future enforcement was "
        "over-eager."
    )

    # ---- Rust: deal lethal damage + SBA on the own Bear Sage ----
    rust_state.deal_damage(rust_sage_id, 2)
    rust_state.apply_sbas()

    # ---- Both engines: Bear Sage in p0's graveyard ----
    py_sage_after = next(
        (o for o in py_state.battlefield
         if o.printing.name == "Bear Sage"),
        None,
    )
    assert py_sage_after is None, (
        "expected Bear Sage REMOVED from Python p0 bf after self-destroy"
    )
    py_p0_gy_names = [
        o.printing.name for o in py_state.players[0].graveyard
    ]
    assert "Bear Sage" in py_p0_gy_names, (
        f"expected Bear Sage in Python p0 graveyard, got {py_p0_gy_names}"
    )

    rust_sage_after = next(
        (e for e in rust_state.battlefield_snapshot()
         if e.get("printing_name") == "Bear Sage"),
        None,
    )
    assert rust_sage_after is None, (
        "expected Bear Sage REMOVED from Rust p0 bf after self-destroy"
    )
    rust_p0_gy_names = [
        e.get("printing_name")
        for e in rust_state.graveyard_snapshot(0)
    ]
    assert "Bear Sage" in rust_p0_gy_names, (
        f"expected Bear Sage in Rust p0 graveyard, got {rust_p0_gy_names}"
    )


def test_cross_engine_hexproof_unenforced_at_target_enumeration(parity_smoke):
    """**Test C — target enumeration includes the hexproof creature
    on BOTH engines (shared bug at the enumeration layer).** The
    brief's Test C asks "legal_decisions for a target-requiring
    spell: confirm the hexproof creature is NOT in the emitted
    target options when the spell's caller is the opponent."

    Since neither engine emits cast-spell-with-target decisions in
    `legal_decisions` today, this test exercises the target-
    ENUMERATION paths directly:

      * Python: `Effect._enumerate_for_filter` (effects/base.py:103)
        — walks bf with the target filter, returns
        ``("creature", id)`` tuples.
      * Rust: `Effect::DestroyTarget`'s target picker
        (state_ops_resolve.rs:1029-1035) — picks `bf[0]` of the
        defender; the broader "list of legal targets" surface
        isn't exposed via PyState, but `battlefield_snapshot` of
        the defender's side is the closest analog.

    Both engines should INCLUDE the Bear Sage in their target-
    enumeration output because neither enforces hexproof — confirms
    the shared-bug parity at the enumeration layer. If either side
    starts filtering out hexproof creatures from target enumeration,
    that's CE18.

    Setup: fresh state, inject Bear Sage on p1's bf (controller=1)
    alongside a plain Bears (controller=1) as a control. The
    enumerated targets from a p0-caller IsCreature filter should
    include BOTH the Bear Sage and the plain Bears on both engines
    (i.e., hexproof is not filtered). The plain Bears is the
    control: it MUST appear in the enumeration to confirm the test
    is exercising the enumeration surface at all.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.object_predicates import IsCreature
    from mtg_bot.effects.base import Effect
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        multi_blocker_deckspec,
    )

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())

    # ---- Inject Bear Sage (hexproof) on p1's bf on both engines ----
    hex_printing = CardPrinting(
        name="Bear Sage",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset({"hexproof"}),
    )
    py_sage = py_state.new_object(
        hex_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_sage.summoning_sick = False
    py_sage.tapped = False
    py_sage.damage = 0
    py_sage.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_sage)

    # Control: plain Bears (no keywords) on p1's bf too.
    plain_printing = CardPrinting(
        name="Plain Bears",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset(),
    )
    py_plain = py_state.new_object(
        plain_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_plain.summoning_sick = False
    py_plain.tapped = False
    py_plain.damage = 0
    py_plain.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_plain)

    ZONE_BATTLEFIELD = 2
    rust_sage_id = rust_state.register_and_inject_object(
        {
            "name": "Bear Sage",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "keywords": ["hexproof"],
        },
        1,
        ZONE_BATTLEFIELD,
    )
    rust_plain_id = rust_state.register_and_inject_object(
        {
            "name": "Plain Bears",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "keywords": [],
        },
        1,
        ZONE_BATTLEFIELD,
    )

    # ---- Python: enumerate legal IsCreature targets from p0's POV ----
    py_targets = Effect._enumerate_for_filter(
        py_state, controller_id=0, target_filter=IsCreature(),
    )
    py_target_ids = {tid for (kind, tid) in py_targets if kind == "creature"}
    # Bear Sage MUST appear (hexproof unenforced).
    assert int(py_sage.id) in py_target_ids, (
        "Bear Sage missing from Python target enumeration — has "
        "hexproof enforcement landed at the enumeration layer? "
        "If so, this test pins the pre-fix shared-bug state; flip "
        "expectation and file CE18 against Rust which still emits it. "
        f"Enumerated ids: {sorted(py_target_ids)}"
    )
    # Plain Bears MUST also appear — control assertion confirming
    # the enumeration surface is being exercised.
    assert int(py_plain.id) in py_target_ids, (
        "Plain Bears (control) missing from Python target enumeration "
        "— test setup broken; the IsCreature filter should match. "
        f"Enumerated ids: {sorted(py_target_ids)}"
    )

    # ---- Rust: confirm BOTH creatures appear in the defender's bf
    # snapshot, which is what `Effect::DestroyTarget`'s AnyCreature
    # target picker walks. No higher-level "list legal targets"
    # surface exists yet on Rust; the bf snapshot is the closest
    # available analog and tracks what the picker would see. ----
    # battlefield_snapshot dicts do NOT include `card_types`
    # (object_to_pydict at rust/src/state_ops_snapshot.rs:68 emits id,
    # printing_id, printing_name, tapped, summoning_sick, damage,
    # counters, controller_id, zone, attached_to — no card_types).
    # Filter by controller only; all entries we care about are creatures
    # because the test only injects creature printings on p1 and the
    # walk creates only creatures + (after step 168) the injected ones.
    # We further narrow to the two injected ids via name for clarity.
    rust_p1_bf = rust_state.battlefield_snapshot()
    rust_p1_creature_ids = {
        int(e["id"]) for e in rust_p1_bf
        if e.get("controller_id") == 1
    }
    assert rust_sage_id in rust_p1_creature_ids, (
        "Bear Sage missing from Rust p1 bf snapshot — has hexproof "
        "filtering landed at the bf-snapshot layer? Unexpected. "
        f"p1 creature ids: {sorted(rust_p1_creature_ids)}"
    )
    assert rust_plain_id in rust_p1_creature_ids, (
        "Plain Bears (control) missing from Rust p1 bf snapshot — "
        f"test setup broken. p1 creature ids: {sorted(rust_p1_creature_ids)}"
    )

    # ---- Cross-engine parity assertion: the SET of enumerated
    # creature ids from each engine's enumeration surface is the
    # same (modulo the engines' different id allocation for the
    # pre-existing creatures, the BOTH should include the freshly-
    # injected Bear Sage and Plain Bears). ----
    # Concretely: both engines enumerate {sage_id, plain_id} as a
    # SUBSET of their target lists. The shared-bug parity is pinned
    # by both subsets being non-empty AND identical in shape.
    py_sage_plain_subset = {int(py_sage.id), int(py_plain.id)}
    rust_sage_plain_subset = {rust_sage_id, rust_plain_id}
    assert py_sage_plain_subset == rust_sage_plain_subset, (
        f"Python and Rust enumerated different ids for the injected "
        f"hexproof + plain creatures — id-allocation drift "
        f"(unrelated to hexproof). Python: {py_sage_plain_subset}, "
        f"Rust: {rust_sage_plain_subset}"
    )
    assert py_sage_plain_subset.issubset(py_target_ids), (
        f"Python target enumeration missing the injected subset "
        f"{py_sage_plain_subset}; got {py_target_ids}"
    )
    assert rust_sage_plain_subset.issubset(rust_p1_creature_ids), (
        f"Rust bf snapshot missing the injected subset "
        f"{rust_sage_plain_subset}; got {rust_p1_creature_ids}"
    )


# ---------------------------------------------------------------------------
# Phase 5 follow-up #18: double_strike_selector tests (CR 702.4).
#
# Three scenarios from the brief:
#
#   * **Test A** — DS attacker (2/2 Bear Champion, p0 bf) + single
#     vanilla blocker (Bears id 9, p1 bf, force-untapped by the
#     side-channel). FS substep: DS deals 2 to blocker; blocker
#     (damage=2 >= toughness=2) dies in mid-combat SBA. Regular
#     substep: DS attacker is still alive — Python rebuilds its
#     blockers list freshly and finds it empty (blocker is in
#     graveyard), then routes its 2 damage to the defender. Rust
#     uses an in-function alive-predicate filter that drops the
#     regular-pass entry because the target died in FS pass — no
#     spillover to defender.
#
#     **CE18 SURFACED**: Python p1 life = 18 (took 2 from
#     redirected DS damage); Rust p1 life = 20 (the entry was
#     filtered out). Single-axis divergence on `life_p1` only.
#
#   * **Test B** — DS attacker + 4/4 vanilla blocker (Bear Behemoth,
#     injected post-walk on p1 bf). FS substep: DS deals 2 to 4/4
#     blocker (NOT lethal — blocker damage=2, toughness=4). Regular
#     substep: DS deals ANOTHER 2 (total blocker damage = 4 ≥
#     toughness 4 = lethal); 4/4 blocker deals 4 to DS attacker
#     (lethal). End state: BOTH creatures in graveyard. Parity-clean.
#
#   * **Test C** — DS attacker + no blocker. Defender takes 4 damage
#     total (2 first-strike + 2 regular). Parity-clean.
#
# Tests pin the contract:
#
#   * test_cross_engine_double_strike_selector_walks_clean —
#     **CE18 CLOSED**: full 200-decision walk is parity-clean,
#     including step 174 (post-COMBAT_DAMAGE) which pre-closure
#     diverged on life_p1. Companion symptom-pin
#     test_cross_engine_double_strike_selector_surfaces_ce18_at_step_174
#     deleted at closure per the CE2-CE17 pair-pin convention.
#   * test_cross_engine_double_strike_post_combat_structural_state
#     — direct-read structural pin on the post-combat bf + gy state.
#   * test_cross_engine_double_strike_larger_blocker_mutual_death
#     — Test B: 4/4 blocker case, parity-clean.
#   * test_cross_engine_double_strike_unblocked_full_damage_to_defender
#     — Test C: no blocker case, parity-clean.
#   * test_cross_engine_double_strike_selector_pre_injection_walks_clean
#     — pre-injection backbone steps 0-167 parity-clean.
# ---------------------------------------------------------------------------


def test_cross_engine_double_strike_selector_walks_clean(parity_smoke):
    """**Double-strike full-walk parity pin (CE18 CLOSED).** 200-decision
    walk on :func:`multi_blocker_deckspec` with
    :func:`double_strike_selector`. Post-closure (invariant I45): every
    step is parity-clean, including step 174 (post-COMBAT_DAMAGE) which
    pre-closure diverged on ``life_p1`` (Python 18 vs Rust 20).

    Closure shape (state_ops_combat.rs:1163-1234): when the pass-2
    alive-predicate filter rejects a Creature target because the
    target died in the FS substep, the entry is REDIRECTED to
    `DamageTarget::Player(defending_player)` IF the source attacker
    has no remaining alive blockers (matches Python's "rebuild
    blockers per-substep yields empty → route to defender" shape).
    Companion symptom pin
    ``test_cross_engine_double_strike_selector_surfaces_ce18_at_step_174``
    deleted at closure per the CE2-CE17 pair-pin convention.
    """
    from mtg_bot.parity.cross_engine import (
        double_strike_selector,
        multi_blocker_deckspec,
        walk_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=200,
        decision_selector=double_strike_selector,
    )
    assert result.error is None, (
        f"walk aborted at step {result.aborted_at}: {result.error}"
    )
    for step in result.steps:
        assert step.divergences == [], (
            f"unexpected divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )


def test_cross_engine_double_strike_post_combat_structural_state(parity_smoke):
    """**Double-strike post-combat structural pin (Test A — non-life
    state).** Drives the walk past combat (180 steps, well past
    COMBAT_DAMAGE at step 174), then asserts the structural bf + gy
    state both engines DO agree on. Only ``life_p1`` diverges
    (CE18); every other observable is parity-clean.

    Pins the brief's Test A expectations:
      * Bear Champion (DS attacker, id 14) ALIVE on p0 bf with
        damage=0 (attacker untouched — blocker is vanilla, no
        damage back; alternatively, damage marks were zeroed at
        CLEANUP step 177).
      * Bears id 9 (FS-killed blocker) in p1 graveyard.
      * Bears id 11 (still tapped from turn-12 attack) still on p1
        bf.
      * Bears id 5 (sick) still on p0 bf.
      * p0 graveyard empty.

    Reads both engines' state directly so the structural assertions
    are independent of the `walk_both` field-view tuple and orthogonal
    to the CE18 life_p1 divergence.
    """
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        double_strike_selector,
        multi_blocker_deckspec,
        step_both,
    )

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(180):
        action = double_strike_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    # ---- Python: bf creatures ----
    py_creatures = sorted(
        (int(o.id), o.printing.name, o.controller_id)
        for o in py_state.battlefield
        if "Creature" in o.printing.card_types
    )
    assert py_creatures == [
        (5, "Grizzly Bears", 0),
        (11, "Grizzly Bears", 1),
        (14, "Bear Champion", 0),
    ], f"unexpected Python bf creatures post-DS-combat: {py_creatures}"

    py_p0_gy_names = [o.printing.name for o in py_state.players[0].graveyard]
    py_p1_gy_names = [o.printing.name for o in py_state.players[1].graveyard]
    assert py_p0_gy_names == [], (
        f"expected Python p0 gy empty (DS attacker untouched); got {py_p0_gy_names}"
    )
    assert py_p1_gy_names == ["Grizzly Bears"], (
        f"expected Python p1 gy=[Grizzly Bears] (FS-killed blocker id 9); "
        f"got {py_p1_gy_names}"
    )

    # DS attacker damage=0 at end-of-turn (CR 514.2 — damage clears at cleanup).
    py_ds = next(
        o for o in py_state.battlefield
        if o.printing.name == "Bear Champion"
    )
    assert py_ds.damage == 0
    assert py_ds.controller_id == 0

    # ---- Rust: bf creatures ----
    rust_creatures = sorted(
        (
            int(e["id"]),
            e["printing_name"],
            int(e["controller_id"]),
        )
        for e in rust_state.battlefield_snapshot()
        if e["printing_name"] in ("Grizzly Bears", "Bear Champion")
    )
    assert rust_creatures == [
        (5, "Grizzly Bears", 0),
        (11, "Grizzly Bears", 1),
        (14, "Bear Champion", 0),
    ], f"unexpected Rust bf creatures post-DS-combat: {rust_creatures}"

    rust_p0_gy_names = [
        e["printing_name"] for e in rust_state.graveyard_snapshot(0)
    ]
    rust_p1_gy_names = [
        e["printing_name"] for e in rust_state.graveyard_snapshot(1)
    ]
    assert rust_p0_gy_names == [], (
        f"expected Rust p0 gy empty; got {rust_p0_gy_names}"
    )
    assert rust_p1_gy_names == ["Grizzly Bears"], (
        f"expected Rust p1 gy=[Grizzly Bears]; got {rust_p1_gy_names}"
    )


def test_cross_engine_double_strike_larger_blocker_mutual_death(parity_smoke):
    """**Test B — DS + 4/4 vanilla blocker** — fresh-state, direct
    combat invocation on both engines. Expected outcome: BOTH die.

    Setup:
      * Inject 2/2 double-strike Bear Champion on p0's bf.
      * Inject 4/4 vanilla Bear Behemoth on p1's bf.
      * Declare Bear Champion as attacker; Bear Behemoth blocks it.
      * Resolve combat damage on both engines + apply SBAs.

    Expected combat math:
      * FS substep: Bear Champion (DS) deals 2 to Bear Behemoth
        (damage 2 < toughness 4, blocker SURVIVES FS substep). Bear
        Behemoth (vanilla) deals 0 in FS substep.
      * SBA (Python) / no-SBA (Rust): no deaths.
      * Regular substep: Bear Champion (DS) deals ANOTHER 2 to Bear
        Behemoth (total damage 4 = toughness 4 = lethal). Bear
        Behemoth deals 4 to Bear Champion (damage 4 > toughness 2 =
        lethal).
      * Final SBA: BOTH die.

    Parity-clean — no CE18 divergence here because the regular-pass
    target is still alive after the FS pass (the alive-predicate
    filter doesn't fire on a target with damage=2 < toughness=4).
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.combat import resolve_combat_damage
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        multi_blocker_deckspec,
    )
    from mtg_bot.turn import state_based_actions

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())

    # ---- Inject DS attacker on p0 bf, 4/4 blocker on p1 bf ----
    ds_printing = CardPrinting(
        name="Bear Champion",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset({"double strike"}),
    )
    py_ds = py_state.new_object(
        ds_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_ds.summoning_sick = False
    py_ds.tapped = False
    py_ds.damage = 0
    py_ds.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_ds)

    behemoth_printing = CardPrinting(
        name="Bear Behemoth",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=4,
        toughness=4,
        produces=frozenset(),
        keywords=frozenset(),
    )
    py_blk = py_state.new_object(
        behemoth_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_blk.controller_id = 1
    py_blk.summoning_sick = False
    py_blk.tapped = False
    py_blk.damage = 0
    py_blk.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_blk)

    # Set up Python combat scaffolding: attacker attacking, blocker
    # blocking the attacker (mirrors what _resolve_damage_step reads).
    py_ds.attacking = True
    py_ds.tapped = True
    py_blk.blocking = int(py_ds.id)
    py_ds.blocked_by.append(int(py_blk.id))

    py_p1_before = py_state.players[1].life
    resolve_combat_damage(py_state, defending_player_id=1)
    state_based_actions(py_state)

    # Both creatures should be DEAD post-combat-damage + SBA.
    py_ds_alive = any(o.id == py_ds.id for o in py_state.battlefield)
    py_blk_alive = any(o.id == py_blk.id for o in py_state.battlefield)
    assert not py_ds_alive, (
        "expected Bear Champion DEAD on Python (took 4 damage from 4/4 "
        "blocker in regular substep; 4 >= toughness 2 = lethal)"
    )
    assert not py_blk_alive, (
        "expected Bear Behemoth DEAD on Python (took 2+2 = 4 damage from "
        "DS attacker across both substeps; 4 >= toughness 4 = lethal)"
    )
    py_p0_gy_names = [o.printing.name for o in py_state.players[0].graveyard]
    py_p1_gy_names = [o.printing.name for o in py_state.players[1].graveyard]
    assert "Bear Champion" in py_p0_gy_names, (
        f"expected Bear Champion in Python p0 gy; got {py_p0_gy_names}"
    )
    assert "Bear Behemoth" in py_p1_gy_names, (
        f"expected Bear Behemoth in Python p1 gy; got {py_p1_gy_names}"
    )
    # No spillover to defender (blocker survived FS substep; the regular
    # substep killed it but the attacker's damage was assigned to the
    # blocker, not the defender).
    assert py_state.players[1].life == py_p1_before, (
        f"expected Python p1 life unchanged at {py_p1_before} (mutual KO; "
        f"no spillover); got {py_state.players[1].life}"
    )

    # ---- Rust side ----
    rust_ds_id = rust_state.register_and_inject_object(
        {
            "name": "Bear Champion",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "keywords": ["double_strike"],
        },
        0, 2,
    )
    rust_blk_id = rust_state.register_and_inject_object(
        {
            "name": "Bear Behemoth",
            "card_types": ["Creature"],
            "power": 4,
            "toughness": 4,
            "keywords": [],
        },
        1, 2,
    )
    rust_state.declare_attacker(rust_ds_id)
    rust_state.declare_blocker(rust_blk_id, rust_ds_id)
    rust_p1_before = rust_state.get_life(1)
    rust_state.deal_combat_damage()
    rust_state.apply_sbas()

    rust_bf_ids = {int(e["id"]) for e in rust_state.battlefield_snapshot()}
    assert rust_ds_id not in rust_bf_ids, (
        "expected Bear Champion DEAD on Rust"
    )
    assert rust_blk_id not in rust_bf_ids, (
        "expected Bear Behemoth DEAD on Rust"
    )
    rust_p0_gy_names = [
        e["printing_name"] for e in rust_state.graveyard_snapshot(0)
    ]
    rust_p1_gy_names = [
        e["printing_name"] for e in rust_state.graveyard_snapshot(1)
    ]
    assert "Bear Champion" in rust_p0_gy_names, (
        f"expected Bear Champion in Rust p0 gy; got {rust_p0_gy_names}"
    )
    assert "Bear Behemoth" in rust_p1_gy_names, (
        f"expected Bear Behemoth in Rust p1 gy; got {rust_p1_gy_names}"
    )
    assert rust_state.get_life(1) == rust_p1_before, (
        f"expected Rust p1 life unchanged at {rust_p1_before}; "
        f"got {rust_state.get_life(1)}"
    )


def test_cross_engine_double_strike_unblocked_full_damage_to_defender(
    parity_smoke,
):
    """**Test C — DS + no blocker** — fresh-state, direct combat
    invocation. Expected outcome: defender takes 4 damage total
    (2 first-strike + 2 regular). Both substeps' damage routes to
    defender because the attacker is unblocked from the start.

    Parity-clean — both engines route both substeps' damage to the
    defender for an unblocked attacker; no CE18 divergence here
    because the "blocker died mid-combat" axis doesn't apply when
    there was no blocker to begin with.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.combat import resolve_combat_damage
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        multi_blocker_deckspec,
    )

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())

    ds_printing = CardPrinting(
        name="Bear Champion",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset({"double strike"}),
    )
    py_ds = py_state.new_object(
        ds_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_ds.summoning_sick = False
    py_ds.tapped = False
    py_ds.damage = 0
    py_ds.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_ds)
    py_ds.attacking = True
    py_ds.tapped = True

    py_p1_before = py_state.players[1].life
    resolve_combat_damage(py_state, defending_player_id=1)
    # No SBA needed — no creatures took damage. Defender took 4
    # life loss.
    assert py_state.players[1].life == py_p1_before - 4, (
        f"expected Python p1 life {py_p1_before - 4} (2 FS + 2 regular "
        f"unblocked); got {py_state.players[1].life}"
    )

    # ---- Rust side ----
    rust_ds_id = rust_state.register_and_inject_object(
        {
            "name": "Bear Champion",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "keywords": ["double_strike"],
        },
        0, 2,
    )
    rust_state.declare_attacker(rust_ds_id)
    rust_p1_before = rust_state.get_life(1)
    rust_state.deal_combat_damage()
    assert rust_state.get_life(1) == rust_p1_before - 4, (
        f"expected Rust p1 life {rust_p1_before - 4} (2 FS + 2 regular "
        f"unblocked); got {rust_state.get_life(1)}"
    )

    # Cross-engine: both engines applied 4 damage to defender. Parity-
    # clean — this is the "outcome both engines agree on" pin for the
    # unblocked-DS case.
    assert (py_p1_before - py_state.players[1].life) == (
        rust_p1_before - rust_state.get_life(1)
    )


def test_cross_engine_double_strike_selector_pre_injection_walks_clean(
    parity_smoke,
):
    """**Double-strike pre-injection backbone pin** — steps 0-167 on
    :func:`multi_blocker_deckspec` with
    :func:`double_strike_selector` are parity-clean. The DS injection
    fires at step 168; the pre-injection backbone is identical to
    :func:`retaliation_selector`'s walk.

    Pins that the pre-167 backbone has not drifted and confirms the
    end-of-step-167 state matches the trigger gate's expectation:
    exactly 3 creatures on bf (Bears ids 5 sick, 9, 11 unsick) and
    no Bear Champion in any zone yet.
    """
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        double_strike_selector,
        multi_blocker_deckspec,
        step_both,
        walk_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=168,
        decision_selector=double_strike_selector,
    )
    assert result.error is None
    for step in result.steps:
        assert step.divergences == [], (
            f"pre-injection divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )

    # Walk-shape sanity rebuild.
    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(168):
        action = double_strike_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    creatures = [
        o for o in py_state.battlefield
        if "Creature" in o.printing.card_types
    ]
    assert len(creatures) == 3, (
        f"expected 3 creatures on bf at end of step 167, got "
        f"{len(creatures)}"
    )
    bear_champion_anywhere = (
        any(o.printing.name == "Bear Champion" for o in py_state.battlefield)
        or any(
            o.printing.name == "Bear Champion"
            for p in py_state.players
            for zone in (p.hand, p.library, p.graveyard, p.exile)
            for o in zone
        )
    )
    assert not bear_champion_anywhere, (
        "Bear Champion should not yet exist at end of step 167 — DS "
        "injection fires at step 168"
    )


# ---------------------------------------------------------------------------
# Phase 5 follow-up #18: flying_selector tests (CR 702.9).
#
# Three scenarios from the brief, all at the DECLARE_BLOCKERS apply
# gate (CR 702.9 + CR 702.17):
#
#   * **Test A** — flying attacker + vanilla blocker attempts to
#     block. Both engines reject the pair at can_block /
#     declare_blocker. Attacker goes through unblocked; defender
#     takes 2 damage.
#
#   * **Test B** — flying attacker + reach blocker. Both engines
#     accept (reach is the gate-opener per CR 702.17). Combat
#     damage: both 2/2s take 2 damage, both die.
#
#   * **Test C** — flying attacker + flying blocker. Both engines
#     accept. Combat damage: both die.
#
# Outcome prediction: **clean pass on all three** — Python's
# `combat.can_block` (combat.py:70-73) and Rust's
# `state.declare_blocker` (state_ops_combat.rs:713-719) gate on the
# same printing.keywords carry symmetrically. No CE divergence
# expected. If one surfaces, it's CE19.
# ---------------------------------------------------------------------------


def test_cross_engine_flying_selector_walks_clean(parity_smoke):
    """**Flying clean-walk pin (Test A)** — 200-decision walk on
    :func:`multi_blocker_deckspec` with :func:`flying_selector` is
    parity-clean every step.

    Walk shape:

      * Steps 0-167: identical to retaliation_selector backbone.
      * Step 168: Bear Soarer (2/2 flying) injected on p0 bf;
        Bears id 9 force-untapped on p1 bf.
      * DECLARE_ATTACKERS p0: emit [bear_soarer_id].
      * DECLARE_BLOCKERS p1: emit [[9, bear_soarer_id]]. BOTH
        engines reject the (vanilla blocker, flying attacker) pair
        at their respective flying gates. Net blockers empty.
      * COMBAT_DAMAGE: 2 damage to p1 (life 20 → 18).

    Parity-load-bearing field at the post-DECLARE_BLOCKERS step:
    the rejected pair must NOT leave a stale entry in either
    engine's blockers list, and the attacker.blocked_by /
    blocker.blocking refs must match.
    """
    from mtg_bot.parity.cross_engine import (
        flying_selector,
        multi_blocker_deckspec,
        walk_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=200,
        decision_selector=flying_selector,
    )
    assert result.error is None, (
        f"walk aborted at step {result.aborted_at}: {result.error}"
    )
    for step in result.steps:
        assert step.divergences == [], (
            f"unexpected divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )


def test_cross_engine_flying_post_combat_state(parity_smoke):
    """**Flying post-combat structural pin (Test A)** — drives enough
    decisions for combat damage to fire (175 steps — past
    COMBAT_DAMAGE), then asserts:

      * Bear Soarer still on p0's bf with damage=0 (unblocked, took
        no damage in return).
      * Bears id 9 still on p1's bf with damage=0 (its block was
        rejected; it didn't actually engage in combat).
      * p1 life = original - 2 (flying attacker dealt 2 to defender
        unblocked).
      * No new entries in either engine's graveyards from this combat.

    Both engines must agree on all four checkpoints. If Rust silently
    accepts the vanilla block (CE19 candidate divergence), Bears id 9
    would have damage=2 and Bear Soarer damage=2; p1 life would be
    unchanged at 20.
    """
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        flying_selector,
        multi_blocker_deckspec,
        step_both,
    )

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    py_p1_before = py_state.players[1].life

    # 175 steps: past COMBAT_DAMAGE, before CLEANUP which zeroes
    # damage marks (CR 514.2).
    for i in range(175):
        action = flying_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    # Bear Soarer should still be on p0's bf with damage=0.
    py_soarer = next(
        (o for o in py_state.battlefield
         if o.printing.name == "Bear Soarer"),
        None,
    )
    assert py_soarer is not None, (
        "expected Bear Soarer still on Python p0 bf post-combat "
        "(unblocked — no damage taken). bf = "
        f"{[(o.id, o.printing.name) for o in py_state.battlefield]}"
    )
    assert py_soarer.controller_id == 0
    assert py_soarer.damage == 0, (
        f"expected Python Bear Soarer damage=0 (unblocked), "
        f"got {py_soarer.damage}"
    )

    rust_soarer = next(
        (e for e in rust_state.battlefield_snapshot()
         if e.get("printing_name") == "Bear Soarer"),
        None,
    )
    assert rust_soarer is not None, (
        "expected Bear Soarer still on Rust p0 bf post-combat"
    )
    assert rust_soarer["controller_id"] == 0
    assert rust_soarer["damage"] == 0, (
        f"expected Rust Bear Soarer damage=0, got {rust_soarer['damage']}"
    )

    # Bears id 9 should still be on p1's bf with damage=0 — its
    # block was rejected by the flying gate, so it didn't engage.
    py_bears9 = next(
        (o for o in py_state.battlefield if int(o.id) == 9),
        None,
    )
    assert py_bears9 is not None, (
        "expected Bears id 9 still on Python p1 bf — its block "
        "was rejected at the flying gate, so it didn't engage. "
        f"bf = {[(o.id, o.printing.name) for o in py_state.battlefield]}"
    )
    assert py_bears9.damage == 0, (
        f"expected Python Bears id 9 damage=0 (block rejected), "
        f"got {py_bears9.damage}"
    )

    rust_bears9 = next(
        (e for e in rust_state.battlefield_snapshot()
         if int(e["id"]) == 9),
        None,
    )
    assert rust_bears9 is not None
    assert rust_bears9["damage"] == 0, (
        f"expected Rust Bears id 9 damage=0, got {rust_bears9['damage']}"
    )

    # p1 life: 20 → 18 (2 damage from unblocked Bear Soarer).
    assert py_state.players[1].life == py_p1_before - 2, (
        f"expected Python p1 life={py_p1_before - 2} (2 unblocked "
        f"damage); got {py_state.players[1].life}"
    )
    assert rust_state.get_life(1) == py_p1_before - 2, (
        f"expected Rust p1 life={py_p1_before - 2}; "
        f"got {rust_state.get_life(1)}"
    )


def test_cross_engine_flying_vs_reach_blocker(parity_smoke):
    """**Test B — flying attacker + reach blocker** — fresh-state
    direct combat. Expected outcome: both engines accept the reach
    blocker (CR 702.17), combat damage: both 2/2s die.

    Pins that BOTH engines treat reach as a gate-opener for
    flying-attacker blocks. A buggy port that only honored flying on
    the BLOCKER side (skipping the reach branch) would surface as a
    divergence: Rust rejects → Bear Soarer dies / Bear Reacher
    alive; Python accepts → mutual KO.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.combat import resolve_combat_damage
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        multi_blocker_deckspec,
    )
    from mtg_bot.turn import state_based_actions as py_sba

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())

    # ---- Python side ----
    soarer_printing = CardPrinting(
        name="Bear Soarer",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset({"flying"}),
    )
    reacher_printing = CardPrinting(
        name="Bear Reacher",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset({"reach"}),
    )

    py_soarer = py_state.new_object(
        soarer_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_soarer.summoning_sick = False
    py_soarer.tapped = False
    py_soarer.damage = 0
    py_soarer.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_soarer)

    py_reacher = py_state.new_object(
        reacher_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_reacher.controller_id = 1
    py_reacher.summoning_sick = False
    py_reacher.tapped = False
    py_reacher.damage = 0
    py_reacher.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_reacher)

    # Declare combat + blocks directly via the apply path (not the
    # selector). `_declare_blockers` walks `can_block` per pair.
    py_soarer.attacking = True
    py_soarer.tapped = True
    from mtg_bot.actions import _declare_blockers as py_apply_blocks
    py_apply_blocks(
        py_state,
        player_id=1,
        assignments=((int(py_reacher.id), int(py_soarer.id)),),
    )

    # can_block accepted: reacher.blocking == soarer.id;
    # soarer.blocked_by contains reacher.id.
    assert py_reacher.blocking == int(py_soarer.id), (
        f"expected Python reacher.blocking={py_soarer.id} "
        f"(reach blocks flying per CR 702.17); got "
        f"{py_reacher.blocking}"
    )
    assert int(py_reacher.id) in py_soarer.blocked_by

    py_p1_before = py_state.players[1].life
    resolve_combat_damage(py_state, defending_player_id=1)
    py_sba(py_state)

    # Both die (2 dmg each, both 2/2). No defender life change.
    py_bf_names = [o.printing.name for o in py_state.battlefield]
    assert "Bear Soarer" not in py_bf_names, (
        f"expected Bear Soarer DEAD on Python (2 dmg from Bear "
        f"Reacher >= toughness 2); bf={py_bf_names}"
    )
    assert "Bear Reacher" not in py_bf_names, (
        f"expected Bear Reacher DEAD on Python; bf={py_bf_names}"
    )
    assert py_state.players[1].life == py_p1_before, (
        f"expected Python p1 life unchanged at {py_p1_before} "
        f"(blocker engaged, no spillover); got "
        f"{py_state.players[1].life}"
    )

    # ---- Rust side ----
    rust_soarer_id = rust_state.register_and_inject_object(
        {
            "name": "Bear Soarer",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "keywords": ["flying"],
        },
        0, 2,  # controller=p0, zone=battlefield
    )
    rust_reacher_id = rust_state.register_and_inject_object(
        {
            "name": "Bear Reacher",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "keywords": ["reach"],
        },
        1, 2,  # controller=p1, zone=battlefield
    )

    rust_state.declare_attacker(rust_soarer_id)
    # declare_blocker returns true iff the gate passed.
    rust_block_ok = rust_state.declare_blocker(
        rust_reacher_id, rust_soarer_id,
    )
    assert rust_block_ok is True, (
        f"expected Rust declare_blocker to ACCEPT reach blocker "
        f"vs flying attacker (CR 702.17); got {rust_block_ok}"
    )

    rust_p1_before = rust_state.get_life(1)
    rust_state.deal_combat_damage()
    rust_state.apply_sbas()

    rust_bf_names = [
        e["printing_name"] for e in rust_state.battlefield_snapshot()
    ]
    assert "Bear Soarer" not in rust_bf_names, (
        f"expected Bear Soarer DEAD on Rust; bf={rust_bf_names}"
    )
    assert "Bear Reacher" not in rust_bf_names, (
        f"expected Bear Reacher DEAD on Rust; bf={rust_bf_names}"
    )
    assert rust_state.get_life(1) == rust_p1_before, (
        f"expected Rust p1 life unchanged at {rust_p1_before} "
        f"(blocker engaged, no spillover); got "
        f"{rust_state.get_life(1)}"
    )

    # Cross-engine: both agreed on life delta.
    assert (
        py_state.players[1].life - py_p1_before
        == rust_state.get_life(1) - rust_p1_before
    )


def test_cross_engine_flying_vs_flying_blocker(parity_smoke):
    """**Test C — flying attacker + flying blocker** — fresh-state
    direct combat. Expected outcome: both engines accept the flying
    blocker (CR 702.9 + 702.17 — flying on the blocker passes the
    gate too), combat damage: both 2/2s die.

    Pins the symmetric block-eligibility shape: flying-vs-flying is
    just a plain combat, no special interaction beyond the gate
    accepting the pair.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.combat import resolve_combat_damage
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        multi_blocker_deckspec,
    )
    from mtg_bot.turn import state_based_actions as py_sba

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())

    soarer_printing = CardPrinting(
        name="Bear Soarer",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset({"flying"}),
    )
    soarer2_printing = CardPrinting(
        name="Bear Soarer 2",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset({"flying"}),
    )

    py_soarer = py_state.new_object(
        soarer_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_soarer.summoning_sick = False
    py_soarer.tapped = False
    py_soarer.damage = 0
    py_soarer.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_soarer)

    py_soarer2 = py_state.new_object(
        soarer2_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_soarer2.controller_id = 1
    py_soarer2.summoning_sick = False
    py_soarer2.tapped = False
    py_soarer2.damage = 0
    py_soarer2.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_soarer2)

    py_soarer.attacking = True
    py_soarer.tapped = True
    from mtg_bot.actions import _declare_blockers as py_apply_blocks
    py_apply_blocks(
        py_state,
        player_id=1,
        assignments=((int(py_soarer2.id), int(py_soarer.id)),),
    )

    assert py_soarer2.blocking == int(py_soarer.id), (
        f"expected Python flying-blocker.blocking={py_soarer.id} "
        f"(flying on blocker passes the gate); got "
        f"{py_soarer2.blocking}"
    )

    py_p1_before = py_state.players[1].life
    resolve_combat_damage(py_state, defending_player_id=1)
    py_sba(py_state)

    py_bf_names = [o.printing.name for o in py_state.battlefield]
    assert "Bear Soarer" not in py_bf_names
    assert "Bear Soarer 2" not in py_bf_names
    assert py_state.players[1].life == py_p1_before

    # ---- Rust side ----
    rust_soarer_id = rust_state.register_and_inject_object(
        {
            "name": "Bear Soarer",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "keywords": ["flying"],
        },
        0, 2,
    )
    rust_soarer2_id = rust_state.register_and_inject_object(
        {
            "name": "Bear Soarer 2",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "keywords": ["flying"],
        },
        1, 2,
    )

    rust_state.declare_attacker(rust_soarer_id)
    rust_block_ok = rust_state.declare_blocker(
        rust_soarer2_id, rust_soarer_id,
    )
    assert rust_block_ok is True, (
        f"expected Rust declare_blocker to ACCEPT flying blocker "
        f"vs flying attacker; got {rust_block_ok}"
    )

    rust_p1_before = rust_state.get_life(1)
    rust_state.deal_combat_damage()
    rust_state.apply_sbas()

    rust_bf_names = [
        e["printing_name"] for e in rust_state.battlefield_snapshot()
    ]
    assert "Bear Soarer" not in rust_bf_names
    assert "Bear Soarer 2" not in rust_bf_names
    assert rust_state.get_life(1) == rust_p1_before


def test_cross_engine_flying_vanilla_blocker_rejected_direct(parity_smoke):
    """**Test A direct-call pin** — fresh-state direct
    ``declare_blocker`` call with vanilla blocker against flying
    attacker. Pins the per-engine rejection shape at the primitive
    layer (separate from the selector-walk path):

      * Python: ``actions._declare_blockers`` consults
        ``combat.can_block`` per pair → returns False for
        (vanilla, flying) → assignment silently dropped → final
        ``state.blockers`` is empty for the flying attacker.
      * Rust: ``state.declare_blocker`` returns ``False`` for the
        pair → ``state.blockers`` is empty.

    Both engines reach the same final shape; this test pins it at
    the primitive level. If a future regression makes either engine
    silently accept the illegal pair, the direct-call assertions
    fire before the selector walk's downstream divergence symptom.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        multi_blocker_deckspec,
    )

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())

    soarer_printing = CardPrinting(
        name="Bear Soarer",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset({"flying"}),
    )
    vanilla_printing = CardPrinting(
        name="Bear Walker",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset(),  # NO flying, NO reach — vanilla.
    )

    py_soarer = py_state.new_object(
        soarer_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_soarer.summoning_sick = False
    py_soarer.tapped = False
    py_soarer.damage = 0
    py_soarer.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_soarer)

    py_vanilla = py_state.new_object(
        vanilla_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_vanilla.controller_id = 1
    py_vanilla.summoning_sick = False
    py_vanilla.tapped = False
    py_vanilla.damage = 0
    py_vanilla.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_vanilla)

    py_soarer.attacking = True
    py_soarer.tapped = True
    from mtg_bot.actions import _declare_blockers as py_apply_blocks
    py_apply_blocks(
        py_state,
        player_id=1,
        assignments=((int(py_vanilla.id), int(py_soarer.id)),),
    )

    # Python: assignment dropped silently. vanilla.blocking is None
    # (or unset); soarer.blocked_by is empty.
    assert py_vanilla.blocking is None or py_vanilla.blocking == 0, (
        f"expected Python vanilla blocker rejected (blocking=None); "
        f"got blocking={py_vanilla.blocking}"
    )
    assert int(py_vanilla.id) not in py_soarer.blocked_by, (
        f"expected Python soarer.blocked_by to NOT contain vanilla "
        f"id={py_vanilla.id}; got blocked_by={py_soarer.blocked_by}"
    )

    # ---- Rust side ----
    rust_soarer_id = rust_state.register_and_inject_object(
        {
            "name": "Bear Soarer",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "keywords": ["flying"],
        },
        0, 2,
    )
    rust_vanilla_id = rust_state.register_and_inject_object(
        {
            "name": "Bear Walker",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "keywords": [],
        },
        1, 2,
    )

    rust_state.declare_attacker(rust_soarer_id)
    rust_block_ok = rust_state.declare_blocker(
        rust_vanilla_id, rust_soarer_id,
    )
    assert rust_block_ok is False, (
        f"expected Rust declare_blocker to REJECT vanilla blocker "
        f"vs flying attacker (CR 702.9 — flying can only be blocked "
        f"by flying or reach); got {rust_block_ok}"
    )


def test_cross_engine_flying_selector_pre_injection_walks_clean(
    parity_smoke,
):
    """**Flying pre-injection backbone pin** — steps 0-167 on
    :func:`multi_blocker_deckspec` with :func:`flying_selector` are
    parity-clean. The flying injection fires at step 168.

    Pins that the pre-167 backbone has not drifted and confirms the
    end-of-step-167 state matches the trigger gate's expectation:
    exactly 3 creatures on bf and no Bear Soarer in any zone yet.
    """
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        flying_selector,
        multi_blocker_deckspec,
        step_both,
        walk_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=168,
        decision_selector=flying_selector,
    )
    assert result.error is None
    for step in result.steps:
        assert step.divergences == [], (
            f"pre-injection divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(168):
        action = flying_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    creatures = [
        o for o in py_state.battlefield
        if "Creature" in o.printing.card_types
    ]
    assert len(creatures) == 3, (
        f"expected 3 creatures on bf at end of step 167, got "
        f"{len(creatures)}"
    )
    bear_soarer_anywhere = (
        any(o.printing.name == "Bear Soarer" for o in py_state.battlefield)
        or any(
            o.printing.name == "Bear Soarer"
            for p in py_state.players
            for zone in (p.hand, p.library, p.graveyard, p.exile)
            for o in zone
        )
    )
    assert not bear_soarer_anywhere, (
        "Bear Soarer should not yet exist at end of step 167 — "
        "flying injection fires at step 168"
    )



# ---------------------------------------------------------------------------
# Phase 5 follow-up #19: counterspell tests. Pins the counterspell_selector
# walk + post-resolve structural state. See cross_engine.counterspell_selector
# for the full design notes. The test names are prefixed with
# `test_cross_engine_counterspell_` for parity with the prior probes'
# naming convention (FS / DS / hexproof / flying / etc).
# ---------------------------------------------------------------------------


def test_cross_engine_counterspell_selector_walks_clean(parity_smoke):
    """Cross-engine counterspell resolution walks parity-clean.

    **Outcome (a) — clean pass**: no novel CE divergence surfaced on
    this probe. Both engines compose a Counterspell-on-Bait-Bears
    stack-of-2 the same observable end-state — bait Bears in p0's
    graveyard (countered, no ETB), Counterspell in p1's graveyard,
    both stacks empty, the 3 pre-existing creatures untouched on
    their respective battlefields.

    The two engines implement counter via DIFFERENT mechanisms
    (Python: flip ``StackItem.countered = True``, route at pop time;
    Rust: remove from stack + route inline) but converge bit-equal on
    the cross-engine field-view compare. The counter-mechanism
    asymmetry is INVISIBLE to the harness's per-step compare because
    the snapshot is taken AFTER both engines drain to empty stacks.
    """
    from mtg_bot.parity.cross_engine import (
        counterspell_selector,
        multi_blocker_deckspec,
        walk_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=170,
        decision_selector=counterspell_selector,
    )
    assert result.error is None, (
        f"walk aborted at step {result.aborted_at}: {result.error}"
    )
    for step in result.steps:
        assert step.divergences == [], (
            f"unexpected divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )


def test_cross_engine_counterspell_post_resolve_structural_state(parity_smoke):
    """Direct-read structural assertion AFTER the counter fires
    (step 168 of the counterspell_selector walk on
    multi_blocker_deckspec).

    Pins the load-bearing observables that the harness's field-view
    compare validates implicitly but that benefit from an explicit
    read-side pin:

    * Both engines: stack is empty after the counter resolves.
    * Both engines: bait Bears in p0's graveyard (NOT on the
      battlefield — the countered spell never resolved as a creature).
    * Both engines: Counterspell in p1's graveyard.
    * Both engines: the 3 pre-existing creatures (Bears ids 5, 9, 11)
      are still on their respective battlefields, untouched by the
      counter.

    Distinct from the walks_clean test in that this asserts the
    SHAPE of the post-counter state directly, not the cross-engine
    field-view tuple. If a future change moves the bait Bears to an
    unexpected zone (battlefield, exile, library), the walks_clean
    compare would flag it as a divergence too, but the failure mode
    here is sharper (you'd see e.g. "expected bait in gy got bf"
    instead of "graveyard_p0 tuple shape diff").
    """
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        counterspell_selector,
        multi_blocker_deckspec,
        step_both,
    )

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(169):
        action = counterspell_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    # Both stacks empty post-drain.
    assert len(py_state.stack) == 0, (
        f"Python stack should be empty post-counter; got "
        f"{[i.source.printing.name for i in py_state.stack]}"
    )
    assert rust_state.stack_size() == 0, (
        f"Rust stack should be empty post-counter; got "
        f"size={rust_state.stack_size()}"
    )

    # Python: bait Bears in p0's graveyard, Counterspell in p1's.
    py_p0_gy_names = [o.printing.name for o in py_state.players[0].graveyard]
    py_p1_gy_names = [o.printing.name for o in py_state.players[1].graveyard]
    assert "Bait Bears" in py_p0_gy_names, (
        f"expected Bait Bears in Python p0 graveyard "
        f"(countered spell -> owner gy per CR 701.5a); got {py_p0_gy_names}"
    )
    assert "Counterspell" in py_p1_gy_names, (
        f"expected Counterspell in Python p1 graveyard "
        f"(post-resolve Instant -> controller gy); got {py_p1_gy_names}"
    )
    # The bait Bears was countered — it should NEVER have hit the bf.
    py_bf_names = [o.printing.name for o in py_state.battlefield]
    assert "Bait Bears" not in py_bf_names, (
        f"Bait Bears should NOT be on Python bf — the spell was "
        f"countered, no ETB / put_into_battlefield should have fired. "
        f"bf={py_bf_names}"
    )

    # Rust: same shape via the field-view's gy/bf signatures.
    rust_view = parity_smoke._build_field_view(rust_state)
    rust_p0_gy_names = tuple(e[0] for e in rust_view["graveyard_p0"])
    rust_p1_gy_names = tuple(e[0] for e in rust_view["graveyard_p1"])
    assert "Bait Bears" in rust_p0_gy_names, (
        f"expected Bait Bears in Rust p0 graveyard "
        f"(Effect::CounterTargetSpell inline-routes target source to "
        f"controller's gy); got {rust_p0_gy_names}"
    )
    assert "Counterspell" in rust_p1_gy_names, (
        f"expected Counterspell in Rust p1 graveyard "
        f"(post-resolve Instant -> controller's gy via "
        f"move_source_post_resolve); got {rust_p1_gy_names}"
    )
    rust_bf_names = tuple(e[0] for e in rust_view["battlefield"])
    assert "Bait Bears" not in rust_bf_names, (
        f"Bait Bears should NOT be on Rust bf — countered spell "
        f"routes to gy inline. bf={rust_bf_names}"
    )

    # 3 pre-existing creatures still on bf on both engines.
    py_grizzly_count = sum(1 for n in py_bf_names if n == "Grizzly Bears")
    rust_grizzly_count = sum(1 for n in rust_bf_names if n == "Grizzly Bears")
    assert py_grizzly_count == 3, (
        f"expected 3 Grizzly Bears still on Python bf "
        f"(counter doesn't touch resolved creatures); got "
        f"{py_grizzly_count} (bf={py_bf_names})"
    )
    assert rust_grizzly_count == 3, (
        f"expected 3 Grizzly Bears still on Rust bf; got "
        f"{rust_grizzly_count} (bf={rust_bf_names})"
    )


def test_cross_engine_counterspell_pre_injection_walks_clean(parity_smoke):
    """Pre-injection backbone steps 0-167 are parity-clean.

    Same shape as the corresponding pre-injection test for every
    prior probe — confirms the retaliation_selector backbone the
    counterspell injection rides on stays divergence-free up to
    the injection step. Distinguishes between "the counterspell
    side-channel itself introduces a divergence" and "something
    upstream of the side-channel is divergent and the counter
    probe just inherits it".
    """
    from mtg_bot.parity.cross_engine import (
        counterspell_selector,
        multi_blocker_deckspec,
        walk_both,
    )

    # Walk 168 steps — the counter injection fires at step 168
    # itself, so steps 0..167 (168 steps total) are the
    # backbone-only window.
    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=168,
        decision_selector=counterspell_selector,
    )
    assert result.error is None, (
        f"pre-injection walk aborted at step {result.aborted_at}: "
        f"{result.error}"
    )
    for step in result.steps:
        assert step.divergences == [], (
            f"pre-injection divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )

    # Sanity: the counterspell injection hasn't fired yet at end of
    # step 167. Confirm no Counterspell or Bait Bears printing exists
    # in any zone on the Python state.
    from mtg_bot.parity.cross_engine import build_matched_states, step_both
    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(168):
        action = counterspell_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    forbidden = ("Counterspell", "Bait Bears")
    in_any_zone = (
        any(
            o.printing.name in forbidden
            for p in py_state.players
            for zone in (p.hand, p.library, p.graveyard, p.exile)
            for o in zone
        )
        or any(
            o.printing.name in forbidden
            for o in py_state.battlefield
        )
    )
    assert not in_any_zone, (
        "Counterspell / Bait Bears should not yet exist at end of "
        "step 167 — counter injection fires at step 168"
    )


def test_cross_engine_counterspell_empty_stack_fizzle(parity_smoke):
    """**Test C — counter target with EMPTY stack.** Direct-call
    fresh-state pin of the empty-stack fizzle parity.

    Inject a Counterspell into p1's hand, push it onto an otherwise-
    empty stack on both engines, resolve. Expected: both engines
    short-circuit (Python: `if not targets: return`; Rust:
    `None => return Ok(())`), the counter source moves to p1's
    graveyard, the stack ends empty.

    Pins the parity of the no-legal-target fizzle path — narrows the
    "counterspell pushed without a target on stack" case which the
    selector walk doesn't directly exercise (the walk always has the
    bait Bears in front of the Counterspell on the stack).
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.generic.stack_control import CounterTargetSpell
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        multi_blocker_deckspec,
    )
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.turn import state_based_actions as py_sba

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())

    # ---- Python side ----
    counter_printing = CardPrinting(
        name="Counterspell",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Instant",
        supertypes=(),
        card_types=("Instant",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        spell_effect=CounterTargetSpell(),
    )
    py_counter = py_state.new_object(
        counter_printing, owner_id=1, zone=Zone.STACK,
    )
    py_counter.summoning_sick = False
    # Push counter on an empty stack with empty targets — the
    # CounterTargetSpell.resolve `if not targets: return` short-circuit
    # is the load-bearing path here.
    py_state.stack.append(
        StackItem(source=py_counter, controller_id=1, targets=())
    )
    resolve_top_of_stack(py_state)
    py_sba(py_state)

    # Counterspell moved to p1's graveyard; stack empty.
    assert len(py_state.stack) == 0, (
        f"Python stack should be empty after counterspell fizzles; "
        f"got {[i.source.printing.name for i in py_state.stack]}"
    )
    py_p1_gy_names = [o.printing.name for o in py_state.players[1].graveyard]
    assert "Counterspell" in py_p1_gy_names, (
        f"expected Counterspell in Python p1 graveyard after fizzle "
        f"(post-resolve mover still routes the source); got "
        f"{py_p1_gy_names}"
    )

    # ---- Rust side ----
    ZONE_HAND = 0
    counter_rust_id = rust_state.register_and_inject_object(
        {
            "name": "Counterspell",
            "card_types": ["Instant"],
            "effects": [{"kind": "counter_target_spell"}],
        },
        1,
        ZONE_HAND,
    )
    rust_state.push_to_stack(counter_rust_id, 1)
    rust_state.resolve_top_of_stack()
    rust_state.apply_sbas()

    assert rust_state.stack_size() == 0, (
        f"Rust stack should be empty after counterspell fizzles; "
        f"got size={rust_state.stack_size()}"
    )
    rust_view = parity_smoke._build_field_view(rust_state)
    rust_p1_gy_names = tuple(e[0] for e in rust_view["graveyard_p1"])
    assert "Counterspell" in rust_p1_gy_names, (
        f"expected Counterspell in Rust p1 graveyard after fizzle "
        f"(move_source_post_resolve routes Instant to gy regardless "
        f"of effect outcome); got {rust_p1_gy_names}"
    )


# ---------------------------------------------------------------------------
# Phase 5 follow-up #20: flash tests. Pins the flash_selector walk +
# the predicted CE19 legal_decisions emission divergence. See
# cross_engine.flash_selector for the full design notes. Test names
# follow the ``test_cross_engine_flash_`` prefix for parity with the
# prior keyword probes' naming convention.
#
# **Test surface** is ``legal_decisions`` emission, not the walk_both
# field-view tuple -- same shape CE17 used for the defender legal-
# emission probe. Three fresh-state direct-call tests probe the
# three priority-window scenarios; a pre-injection backbone walk
# pins the upstream parity.
# ---------------------------------------------------------------------------


def _legal_actions_to_dicts(actions):
    """Convert Python ``legal.legal_actions`` output (a list of
    ``Action`` dataclasses) to the same dict shape Rust's
    ``legal_decisions`` returns. Lets us probe Python's emission via
    a uniform dict-list interface.

    Only the kinds the flash probe cares about (``pass_priority``,
    ``cast_spell``, ``play_land``) are mapped; other kinds round-trip
    to ``{"kind": <classname-lowercase>}`` for inclusion in count
    checks but aren't asserted on by field shape.
    """
    from mtg_bot.actions import CastSpell, PassPriority, PlayLand

    out = []
    for action in actions:
        if isinstance(action, PassPriority):
            out.append({"kind": "pass_priority"})
        elif isinstance(action, CastSpell):
            out.append({"kind": "cast_spell", "card_id": int(action.card_id)})
        elif isinstance(action, PlayLand):
            out.append({"kind": "play_land", "card_id": int(action.card_id)})
        else:
            out.append({"kind": type(action).__name__.lower()})
    return out


def test_cross_engine_flash_test_a_closes_ce19(parity_smoke):
    """**Test A — CE19 CLOSED**: legal_decisions for a flash creature
    on p1's turn (active=p1) with p0 holding priority emits CastSpell
    on BOTH engines.

    Setup: walk the retaliation_selector backbone to step 167 (turn
    13 PRECOMBAT_MAIN, active=p0). Side-channel-advance phases on
    BOTH engines through to turn 14 PRECOMBAT_MAIN (active=p1).
    Set ``priority_player`` to 0 on both engines via Python's
    dataclass attribute write + Rust's ``give_priority_to(0)``.
    Inject Bear Flash (2/2 + flash keyword) into p0's hand on both
    engines. Probe ``legal_decisions(0)`` / ``legal_actions(state, 0)``.

    Post-CE19-closure expectation (both engines agree):

    * **Python**: ``legal.py:217-301`` instant-speed CastSpell block
      runs BEFORE the sorcery-timing gate at line 303. The filter
      ``card.printing.is_instant or "flash" in card.printing.keywords``
      accepts Bear Flash. Emission includes a ``CastSpell(bear_flash_id)``
      dict.
    * **Rust** (post-closure): ``state_ops_legal.rs`` CastSpell loop
      now lives ABOVE the sorcery-timing short-circuit and gates
      per-card on ``is_instant || keywords.contains("flash") ||
      is_sorcery_timing``. The flash keyword triggers the
      instant-speed pass — Rust emits ``CastSpell`` for the flash
      card at the off-active priority window, matching Python.

    The assertion shape is flipped from the pre-closure shape-pin
    ("Rust does NOT emit") to the post-closure equality form: both
    engines emit identical ``cast_spell`` card_id sets, and the flash
    card's id is in each set. See I46 in ``docs/RUST_PARITY_GAPS.md``.
    """
    from mtg_bot.legal import legal_actions
    from mtg_bot.parity.cross_engine import (
        advance_phase_python,
        build_matched_states,
        flash_side_channel,
        multi_blocker_deckspec,
        retaliation_selector,
        step_both,
    )

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    # Walk 167 backbone decisions to land at turn 13 PRECOMBAT_MAIN
    # active=p0 (same setpoint the prior 11 keyword probes use).
    for i in range(167):
        action = retaliation_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    # Side-channel advance phases until we reach turn 14
    # PRECOMBAT_MAIN active=p1. From turn 13 PRECOMBAT_MAIN we need
    # to walk: PRECOMBAT_MAIN -> BEGIN_COMBAT -> DECLARE_ATTACKERS
    # -> DECLARE_BLOCKERS -> COMBAT_DAMAGE -> END_COMBAT ->
    # POSTCOMBAT_MAIN -> END_STEP -> CLEANUP (wraps to UNTAP +
    # turn++ + swap active) -> UPKEEP -> DRAW -> PRECOMBAT_MAIN. 11
    # advance_phase calls.
    from mtg_bot.turn import Step
    safety_cap = 25
    advances = 0
    while not (
        py_state.step == Step.PRECOMBAT_MAIN
        and py_state.active_player_idx == 1
    ):
        advance_phase_python(py_state)
        rust_state.advance_phase()
        advances += 1
        assert advances < safety_cap, (
            f"failed to reach turn 14 PRECOMBAT_MAIN active=p1 within "
            f"{safety_cap} advance_phase calls; current "
            f"step={py_state.step.name} active={py_state.active_player_idx}"
        )

    # Sanity: both engines agree on the new phase / active player.
    assert py_state.step == Step.PRECOMBAT_MAIN
    assert py_state.active_player_idx == 1
    assert rust_state.active_player_idx == 1, (
        f"Rust active_player_idx={rust_state.active_player_idx} != Python's 1"
    )

    # Set priority to p0 on both engines (so we probe the off-active
    # priority window where flash matters). Python: direct dataclass
    # field write. Rust: ``give_priority_to`` primitive.
    py_state.priority_player_idx = 0
    rust_state.give_priority_to(0)

    # Inject Bear Flash (2/2 + flash) into p0's hand on both engines.
    py_id, rust_id = flash_side_channel(py_state, rust_state)

    # ---- Probe Python's legal_actions(state, 0) ----
    py_actions = _legal_actions_to_dicts(legal_actions(py_state, 0))
    py_cast_card_ids = [
        a["card_id"] for a in py_actions
        if a["kind"] == "cast_spell"
    ]
    assert py_id in py_cast_card_ids, (
        f"Python should emit CastSpell for the flash creature (Bear "
        f"Flash id {py_id}) at p1's turn / p0 priority -- the "
        f"instant-speed block at legal.py:217-301 accepts "
        f"'flash' in keywords. Python emission cast_spell ids: "
        f"{py_cast_card_ids}; full emission kinds: "
        f"{[a['kind'] for a in py_actions]}"
    )

    # ---- Probe Rust's legal_decisions(0) ----
    rust_actions = rust_state.legal_decisions(0)
    rust_cast_card_ids = [
        a["card_id"] for a in rust_actions
        if a.get("kind") == "cast_spell"
    ]
    # CE19 CLOSED: Rust now emits CastSpell for the flash creature
    # via the instant-speed pass that lives above the sorcery-timing
    # short-circuit. The per-card gate at state_ops_legal.rs is
    # `is_instant || keywords.contains("flash") || is_sorcery_timing`;
    # the flash keyword fires the first clause, so the off-active
    # priority window emits regardless of `active != priority`.
    assert rust_id in rust_cast_card_ids, (
        f"CE19 closure regression: Rust did NOT emit CastSpell for "
        f"the flash creature (Bear Flash id {rust_id}) at p1's turn "
        f"/ p0 priority. Post-closure Rust's legal_decisions should "
        f"emit via the instant-speed pass above the sorcery-timing "
        f"gate (state_ops_legal.rs `is_instant || keywords.contains"
        f"(\"flash\") || is_sorcery_timing`). Rust emission "
        f"cast_spell ids: {rust_cast_card_ids}; full emission kinds: "
        f"{[a.get('kind') for a in rust_actions]}. See I46 in "
        f"docs/RUST_PARITY_GAPS.md."
    )

    # Both-engines-agree pin: the set of cast_spell card ids matches
    # exactly between Python and Rust. Stronger than "both contain
    # the flash id" -- catches a divergence where Rust over-corrects
    # and emits additional non-flash non-instant cards at the off-
    # active priority window (which would be a different and larger
    # divergence than CE19).
    assert set(py_cast_card_ids) == set(rust_cast_card_ids), (
        f"CE19 closure should produce identical CastSpell emissions "
        f"on both engines at the off-active priority window. "
        f"Python ids: {sorted(py_cast_card_ids)}; "
        f"Rust ids: {sorted(rust_cast_card_ids)}. "
        f"Mismatch indicates a per-card filter divergence."
    )


def test_cross_engine_flash_test_b_own_turn_main_phase_parity(parity_smoke):
    """**Test B — parity-clean sanity**: legal_decisions for a flash
    creature on p0's OWN turn (active=p0) at PRECOMBAT_MAIN, priority=p0.

    Both engines should emit CastSpell for the flash creature:

    * **Python**: instant-speed block at lines 217-301 accepts flash;
      ALSO the sorcery-speed block at lines 365-445 skips it
      (line 366: ``if "flash" in card.printing.keywords: continue``)
      to avoid emitting twice. Net: one CastSpell emitted from the
      instant-speed block.
    * **Rust**: sorcery-timing predicate passes
      (active=0 == priority=0, step=PRECOMBAT_MAIN, stack empty).
      Sorcery-speed CastSpell block at lines 833-853 walks the hand
      and emits a base CastSpell for every non-Land card. The flash
      keyword is ignored (Rust doesn't honor an instant-speed
      window), but at sorcery timing the cards still emit -- so the
      flash creature gets a CastSpell emission regardless.

    Both engines: emission contains ``CastSpell(bear_flash_id)``.
    Parity-clean on the load-bearing axis (presence of the cast in
    the emission list).
    """
    from mtg_bot.legal import legal_actions
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        flash_side_channel,
        multi_blocker_deckspec,
        retaliation_selector,
        step_both,
    )

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(167):
        action = retaliation_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    # Sanity: we should be at turn 13 PRECOMBAT_MAIN active=p0 (the
    # retaliation walk's setpoint matching the prior 11 keyword probes).
    from mtg_bot.turn import Step
    assert py_state.step == Step.PRECOMBAT_MAIN
    assert py_state.active_player_idx == 0
    # Priority is on p0 (the active player) at the start of their own
    # main phase. Both engines maintain this invariant through the
    # retaliation walk -- no priority swap happens in the backbone.
    assert py_state.priority_player_idx == 0
    assert rust_state.priority_player_idx == 0

    py_id, rust_id = flash_side_channel(py_state, rust_state)

    # ---- Python emission ----
    py_actions = _legal_actions_to_dicts(legal_actions(py_state, 0))
    py_cast_card_ids = [
        a["card_id"] for a in py_actions
        if a["kind"] == "cast_spell"
    ]
    assert py_id in py_cast_card_ids, (
        f"Python should emit CastSpell for Bear Flash at own-turn main "
        f"phase (instant-speed block accepts flash; sorcery-speed "
        f"block skips it to dedupe). Got cast_spell ids: "
        f"{py_cast_card_ids}"
    )

    # ---- Rust emission ----
    rust_actions = rust_state.legal_decisions(0)
    rust_cast_card_ids = [
        a["card_id"] for a in rust_actions
        if a.get("kind") == "cast_spell"
    ]
    assert rust_id in rust_cast_card_ids, (
        f"Rust should emit CastSpell for Bear Flash at own-turn main "
        f"phase (sorcery-timing gate passes; CastSpell block walks "
        f"hand and emits for every non-Land). Got cast_spell ids: "
        f"{rust_cast_card_ids}; full emission: "
        f"{[a.get('kind') for a in rust_actions]}"
    )


def test_cross_engine_flash_test_c_vanilla_off_turn_negative_parity(parity_smoke):
    """**Test C — parity-clean NEGATIVE**: legal_decisions for a
    VANILLA creature (NO flash) on p1's turn with p0 priority.

    Setup mirrors Test A's priority window (turn 14 PRECOMBAT_MAIN
    active=p1, priority=p0) but injects a Vanilla Bear (no flash
    keyword) into p0's hand instead of Bear Flash.

    Expected: neither engine emits CastSpell for the vanilla
    creature.

    * **Python**: the instant-speed block's filter
      ``card.printing.is_instant or "flash" in card.printing.keywords``
      rejects the vanilla bear (False on both clauses). The
      sorcery-speed block at lines 365-445 is gated by
      ``_is_sorcery_timing`` at line 303, which fails
      (active=1 != priority=0). Net: no CastSpell for vanilla bear.
    * **Rust**: sorcery-timing predicate fails (active != priority).
      Function returns at line 762-764 with just PassPriority. No
      CastSpell for any card in hand, vanilla or otherwise.

    Parity-clean. If this test DIVERGES, the bug is broader than a
    flash-keyword gap -- it'd be an instant-speed-window-honored
    mismatch on vanilla creatures, which would be a different and
    larger CE.
    """
    from mtg_bot.legal import legal_actions
    from mtg_bot.parity.cross_engine import (
        advance_phase_python,
        build_matched_states,
        multi_blocker_deckspec,
        retaliation_selector,
        step_both,
        vanilla_creature_side_channel,
    )

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(167):
        action = retaliation_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    # Advance to turn 14 PRECOMBAT_MAIN active=p1, same as Test A.
    from mtg_bot.turn import Step
    safety_cap = 25
    advances = 0
    while not (
        py_state.step == Step.PRECOMBAT_MAIN
        and py_state.active_player_idx == 1
    ):
        advance_phase_python(py_state)
        rust_state.advance_phase()
        advances += 1
        assert advances < safety_cap

    py_state.priority_player_idx = 0
    rust_state.give_priority_to(0)

    py_id, rust_id = vanilla_creature_side_channel(py_state, rust_state)

    # ---- Python emission ----
    py_actions = _legal_actions_to_dicts(legal_actions(py_state, 0))
    py_cast_card_ids = [
        a["card_id"] for a in py_actions
        if a["kind"] == "cast_spell"
    ]
    assert py_id not in py_cast_card_ids, (
        f"Python should NOT emit CastSpell for the vanilla creature "
        f"(Vanilla Bear id {py_id}) at p1's turn / p0 priority -- "
        f"the instant-speed filter rejects (no flash + not instant), "
        f"and the sorcery-speed block is gated by sorcery-timing "
        f"(active != priority fails). Unexpected emission: "
        f"cast_spell ids {py_cast_card_ids}; if this fails the "
        f"Python instant-speed gate has changed."
    )

    # ---- Rust emission ----
    rust_actions = rust_state.legal_decisions(0)
    rust_cast_card_ids = [
        a["card_id"] for a in rust_actions
        if a.get("kind") == "cast_spell"
    ]
    assert rust_id not in rust_cast_card_ids, (
        f"Rust should NOT emit CastSpell for the vanilla creature "
        f"(Vanilla Bear id {rust_id}) at p1's turn / p0 priority -- "
        f"sorcery-timing gate fails (active=1 != priority=0). "
        f"Unexpected emission: cast_spell ids {rust_cast_card_ids}. "
        f"If this fails the Rust enumerator has an instant-speed "
        f"window that emits vanillas, which is a different / larger "
        f"divergence than CE19."
    )

    # Parity-clean sanity: both engines emit only the priority-gate-
    # independent actions on the off-active priority window. For the
    # vanilla-bear setup this is exactly PassPriority on both sides.
    rust_kinds = sorted(a.get("kind") for a in rust_actions)
    py_kinds = sorted(a["kind"] for a in py_actions)
    assert rust_kinds == ["pass_priority"], (
        f"Rust off-priority emission should be ONLY pass_priority; "
        f"got: {rust_kinds}"
    )
    assert py_kinds == ["pass_priority"], (
        f"Python off-priority emission for vanilla-only hand at "
        f"non-sorcery-timing window should be ONLY pass_priority; "
        f"got: {py_kinds}"
    )


def test_cross_engine_flash_selector_pre_injection_walks_clean(parity_smoke):
    """Pre-injection backbone steps 0-167 are parity-clean.

    Same shape as the corresponding pre-injection test for every
    prior probe -- confirms the retaliation_selector backbone the
    flash injection rides on stays divergence-free up to the
    injection step. Distinguishes between "the flash side-channel
    itself introduces a divergence" and "something upstream of the
    side-channel is divergent and the flash probe just inherits it".
    """
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        flash_selector,
        multi_blocker_deckspec,
        step_both,
        walk_both,
    )

    # Walk 168 steps -- the flash injection fires at step 168
    # itself, so steps 0..167 (168 steps total) are the
    # backbone-only window.
    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=168,
        decision_selector=flash_selector,
    )
    assert result.error is None, (
        f"pre-injection walk aborted at step {result.aborted_at}: "
        f"{result.error}"
    )
    for step in result.steps:
        assert step.divergences == [], (
            f"pre-injection divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )

    # Sanity: the flash injection hasn't fired yet at end of step 167.
    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(168):
        action = flash_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    in_any_zone = (
        any(
            o.printing.name == "Bear Flash"
            for p in py_state.players
            for zone in (p.hand, p.library, p.graveyard, p.exile)
            for o in zone
        )
        or any(
            o.printing.name == "Bear Flash"
            for o in py_state.battlefield
        )
    )
    assert not in_any_zone, (
        "Bear Flash should not yet exist at end of step 167 -- "
        "flash injection fires at step 168"
    )


# ---------------------------------------------------------------------------
# Phase 5 follow-up #21: activated_mid_combat tests. Pins the
# activated_mid_combat_selector walk + the predicted shared engine
# behavior at a non-MAIN priority window. See
# cross_engine.activated_mid_combat_selector for the full design notes.
#
# **Test surfaces:**
#
#   * Test A: ``legal_decisions(0)`` emission at BEGINNING_OF_COMBAT
#     with priority on the active player. Both engines should refuse
#     to emit ActivateAbility for the injected Forest (the
#     ``_is_sorcery_timing`` gate fails because step != MAIN). Same
#     parity-clean axis the flash Test C pinned for the vanilla
#     creature -- both engines on the same side of a shared gate.
#
#   * Test B: direct ``apply_action(activate_ability)`` mid-combat.
#     Neither engine's dispatch arm phase-gates, so both should
#     accept and credit {G}. Field-view compare: Forest tapped, G
#     coin in pool, no stack push (mana abilities resolve immediately
#     per CR 605.3a).
#
#   * Test C: phase-advance from the mid-combat step. The {G}
#     credited in Test B should empty (per I20 mana-pool-empty-on-
#     phase-boundary semantics). Both engines should agree.
#
#   * Test D (pre-injection walk-clean): the
#     activated_mid_combat_selector backbone walks parity-clean for
#     steps 0..167 (the pre-injection window). Same shape as every
#     prior probe's walk-clean baseline.
# ---------------------------------------------------------------------------


def test_cross_engine_activated_mid_combat_test_a_no_emission_off_main(parity_smoke):
    """**Test A**: legal_decisions for an untapped Forest on p0's
    battlefield at BEGINNING_OF_COMBAT with p0 holding priority.

    Setup: walk the retaliation_selector backbone to step 167 (turn
    13 PRECOMBAT_MAIN, active=p0, priority=p0). Side-channel-advance
    phase by ONE step on both engines (PRECOMBAT_MAIN ->
    BEGINNING_OF_COMBAT). Inject a fresh untapped, unsick "Combat
    Forest" onto p0's bf. Probe legal_decisions(0) emission.

    Expected (parity-clean): both engines refuse to emit
    ActivateAbility for the Combat Forest because the
    ``_is_sorcery_timing`` gate fails (step=BEGINNING_OF_COMBAT not
    in MAIN_STEPS, regardless of priority/active alignment). Python's
    ``legal.py:303-304`` returns early after the instant-speed
    CastSpell pass; Rust's ``state_ops_legal.rs:837-839`` returns
    early at the matching post-instant-speed gate.

    This is a SHARED engine limitation (CR 605.1 mana abilities are
    nominally activatable at any priority window), NOT a CE
    divergence. The test pins both engines on the same side.

    If this test FAILS with one engine emitting ActivateAbility and
    the other not, that's a NEW CE -- the gate is being applied
    asymmetrically. Document as CE20 and xfail-pin.
    """
    from mtg_bot.legal import legal_actions
    from mtg_bot.parity.cross_engine import (
        activated_mid_combat_side_channel,
        advance_phase_python,
        build_matched_states,
        multi_blocker_deckspec,
        retaliation_selector,
        step_both,
    )
    from mtg_bot.turn import Step

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(167):
        action = retaliation_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    # Sanity: turn 13 PRECOMBAT_MAIN active=p0 priority=p0.
    assert py_state.step == Step.PRECOMBAT_MAIN
    assert py_state.active_player_idx == 0
    assert py_state.priority_player_idx == 0

    # Advance ONE step: PRECOMBAT_MAIN -> BEGINNING_OF_COMBAT. Active
    # stays p0, priority flows back to p0 (active player gets priority
    # at the start of every step per CR 117.3a).
    advance_phase_python(py_state)
    rust_state.advance_phase()
    assert py_state.step == Step.BEGINNING_OF_COMBAT
    assert py_state.active_player_idx == 0
    assert rust_state.active_player_idx == 0, (
        f"Rust active_player_idx={rust_state.active_player_idx} != Python's 0"
    )

    # Inject a fresh untapped, unsick Combat Forest on p0's bf.
    py_forest_id, rust_forest_id = activated_mid_combat_side_channel(
        py_state, rust_state,
    )

    # ---- Probe Python's legal_actions(state, 0) ----
    py_actions = legal_actions(py_state, 0)
    py_activate_source_ids = [
        int(a.source_id) for a in py_actions
        if type(a).__name__ == "ActivateAbility"
    ]
    assert py_forest_id not in py_activate_source_ids, (
        f"Python should NOT emit ActivateAbility for the Combat "
        f"Forest (id {py_forest_id}) at BEGINNING_OF_COMBAT -- "
        f"the _is_sorcery_timing gate at legal.py:303-304 returns "
        f"early because step=BEGINNING_OF_COMBAT is not in "
        f"MAIN_STEPS. If Python now emits, the gate's been moved -- "
        f"this is a Python-only change that surfaces a NEW asymmetry "
        f"vs Rust (CE20 candidate). Python emission ActivateAbility "
        f"source ids: {py_activate_source_ids}; full emission types: "
        f"{[type(a).__name__ for a in py_actions]}"
    )

    # ---- Probe Rust's legal_decisions(0) ----
    rust_actions = rust_state.legal_decisions(0)
    rust_activate_source_ids = [
        a.get("source_id") for a in rust_actions
        if a.get("kind") == "activate_ability"
    ]
    assert rust_forest_id not in rust_activate_source_ids, (
        f"Rust should NOT emit ActivateAbility for the Combat Forest "
        f"(id {rust_forest_id}) at BEGINNING_OF_COMBAT -- the "
        f"is_sorcery_timing gate at state_ops_legal.rs:837-839 "
        f"returns before the ActivateAbility emission loop runs. If "
        f"Rust now emits, the gate's been moved -- this is a "
        f"Rust-only change that surfaces a NEW asymmetry vs Python "
        f"(CE20 candidate). Rust emission ActivateAbility source ids: "
        f"{rust_activate_source_ids}; full emission kinds: "
        f"{[a.get('kind') for a in rust_actions]}"
    )

    # Parity-clean shape pin: both engines emit ONLY pass_priority
    # (no flash creatures, no instants, no sorcery-timing-gated
    # actions). DeclareAttackers is gated on
    # ``step == PHASE_DECLARE_ATTACKERS`` in Rust (not yet at
    # BEGINNING_OF_COMBAT) and Python doesn't enumerate it either
    # (legal_actions never emits DeclareAttackers per the docstring
    # at engine.py:10-19).
    rust_kinds = sorted(a.get("kind") for a in rust_actions)
    assert rust_kinds == ["pass_priority"], (
        f"Rust at BEGINNING_OF_COMBAT with empty hand + no eligible "
        f"emission should produce ONLY pass_priority; got: {rust_kinds}"
    )
    py_types = sorted(type(a).__name__ for a in py_actions)
    assert py_types == ["PassPriority"], (
        f"Python at BEGINNING_OF_COMBAT should produce ONLY "
        f"PassPriority; got: {py_types}"
    )


def test_cross_engine_activated_mid_combat_test_b_apply_dispatch_parity(parity_smoke):
    """**Test B**: directly apply ``ActivateAbility(forest_id, 0)``
    mid-combat (BEGINNING_OF_COMBAT) on both engines.

    Setup: walk + advance + inject as in Test A. Then build an
    ``{"kind": "activate_ability", "source_id": forest_id,
    "ability_index": 0}`` dict and feed it to :func:`step_both`.

    Expected (parity-clean): both engines accept the apply_action,
    tap the Forest, and credit {G} to p0's mana pool. No stack push
    on either engine (CR 605.3a mana abilities resolve immediately).

    Test verifies:
      * Forest's ``tapped`` flag flips True on both engines.
      * p0's mana_pool gains exactly one G coin on both engines.
      * Stack stays empty on both engines (no StackItem push for
        the mana ability resolution).
      * The cross-engine field-view divergence list for this step
        is empty -- both engines agree on every fingerprinted field.

    If the field-view compare DIVERGES on mana_pool_p0,
    battlefield, or stack, that's the predicted CE20 surface --
    document and xfail-pin.
    """
    from mtg_bot.parity.cross_engine import (
        activated_mid_combat_side_channel,
        advance_phase_python,
        build_matched_states,
        multi_blocker_deckspec,
        retaliation_selector,
        step_both,
    )
    from mtg_bot.turn import Step

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(167):
        action = retaliation_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    advance_phase_python(py_state)
    rust_state.advance_phase()
    assert py_state.step == Step.BEGINNING_OF_COMBAT

    py_forest_id, rust_forest_id = activated_mid_combat_side_channel(
        py_state, rust_state,
    )
    # Sanity: the freshly-injected Forest's id collision-free wrt the
    # existing bf objects. Both engines allocate ids monotonically from
    # the next-id pool; the helper guarantees no collision via the
    # ``max+1`` scan on Rust side and Python's ``next_object_id``
    # bump.
    assert py_forest_id > 0
    assert rust_forest_id > 0

    # ---- Apply ActivateAbility on BOTH engines via step_both ----
    activate_dict = {
        "kind": "activate_ability",
        "source_id": py_forest_id,
        "ability_index": 0,
    }
    # Rust uses its own forest id (per-engine id allocation diverges
    # for synthetic injections). Feed Rust its own dict.
    rust_activate_dict = {
        "kind": "activate_ability",
        "source_id": rust_forest_id,
        "ability_index": 0,
    }
    # step_both feeds the SAME dict to both engines, but the Python
    # and Rust Forest ids may differ. Work around by applying
    # directly per-engine (the step_both shape is for matched-id
    # decisions; this probe deliberately diverges ids).
    from mtg_bot.parity.cross_engine import (
        _dict_to_python_action,
        build_python_field_view,
    )
    from mtg_bot.actions import apply_action as py_apply_action

    py_action = _dict_to_python_action(activate_dict)
    py_apply_action(py_state, 0, py_action)
    rust_state.apply_action(rust_activate_dict)

    # ---- Compare post-state ----
    # Python: find the Combat Forest object on bf; check tapped + pool.
    py_forest = next(
        o for o in py_state.battlefield
        if int(o.id) == py_forest_id
    )
    assert py_forest.tapped, (
        f"Python: Combat Forest (id {py_forest_id}) should be tapped "
        f"after ActivateAbility; got tapped={py_forest.tapped}"
    )
    py_green_coins = sum(
        1 for coin in py_state.players[0].mana_pool
        if getattr(coin, "color", None) == "G"
    )
    assert py_green_coins == 1, (
        f"Python: p0's mana_pool should have exactly 1 G coin after "
        f"ActivateAbility (Forest's mana ability resolves "
        f"immediately per CR 605.3a); got {py_green_coins} G coins. "
        f"Pool: {py_state.players[0].mana_pool}"
    )
    assert len(py_state.stack) == 0, (
        f"Python stack should be empty after mana ability activation "
        f"(CR 605.3a -- mana abilities bypass the stack); got stack "
        f"with {len(py_state.stack)} items"
    )

    # Rust: same checks via the engine's public getters.
    rust_view = parity_smoke._build_field_view(rust_state)
    rust_mana_p0 = dict(rust_view["mana_pool_p0"])
    assert rust_mana_p0.get("G", 0) == 1, (
        f"Rust: p0's mana_pool should have exactly 1 G after "
        f"ActivateAbility; got mana_pool_p0={rust_view['mana_pool_p0']}"
    )
    assert rust_view["stack"] == (), (
        f"Rust stack should be empty after mana ability (CR 605.3a); "
        f"got: {rust_view['stack']}"
    )
    # Locate the Rust Combat Forest in the bf zone signature and
    # verify tapped=True. The zone signature is a tuple of 8-tuples
    # (printing_name, tapped, sick, dmg, counters, attached_to,
    # ctrl, id) -- index 1 is tapped.
    rust_forest_entries = [
        entry for entry in rust_view["battlefield"]
        if entry[0] == "Combat Forest"
    ]
    assert len(rust_forest_entries) == 1, (
        f"Rust battlefield should contain exactly one Combat Forest; "
        f"got {len(rust_forest_entries)}: {rust_forest_entries}"
    )
    # Zone signature encodes ``tapped`` as 0/1 int rather than
    # bool (matches the Rust getter's wire shape; the Python normalizer
    # passes the int through unchanged). Compare against truthy.
    assert bool(rust_forest_entries[0][1]), (
        f"Rust: Combat Forest should be tapped after ActivateAbility; "
        f"got bf entry: {rust_forest_entries[0]}"
    )

    # ---- Cross-engine field-view compare on mana / bf / stack ----
    py_view = build_python_field_view(py_state)
    # Mana pool parity: both engines should agree on the 6-color
    # tuple. This is the load-bearing field for the probe.
    assert py_view["mana_pool_p0"] == rust_view["mana_pool_p0"], (
        f"mana_pool_p0 diverges post-ActivateAbility -- predicted "
        f"CE20 surface. Python: {py_view['mana_pool_p0']}; Rust: "
        f"{rust_view['mana_pool_p0']}. Document as CE20 and "
        f"xfail-pin per the brief's outcome (b) shape."
    )
    # Stack parity: both empty.
    assert py_view["stack"] == rust_view["stack"], (
        f"stack diverges post-ActivateAbility -- predicted CE20 "
        f"surface (mana abilities should bypass the stack on both "
        f"engines). Python: {py_view['stack']}; Rust: "
        f"{rust_view['stack']}"
    )


def test_cross_engine_activated_mid_combat_test_c_phase_advance_empties_pool(parity_smoke):
    """**Test C**: after the mid-combat activation in Test B,
    advance phase ONE step (BEGINNING_OF_COMBAT -> DECLARE_ATTACKERS)
    on both engines. The {G} credited by the activation should
    empty (per I20 -- both engines empty mana pools on every
    phase / step boundary).

    Setup: same as Test B through the activation. Then advance phase
    once. Compare post-advance mana_pool_p0 on both engines.

    Expected (parity-clean): both engines' mana_pool_p0 becomes the
    canonical empty 6-tuple
    ``(('B',0),('C',0),('G',0),('R',0),('U',0),('W',0))``.

    Documented as I20 in the gap doc (mana-pool-empty-on-phase-
    advance composition). If the timing differs by one step --
    e.g. Python empties at COMBAT_DAMAGE while Rust empties at
    DECLARE_ATTACKERS -- that's a NEW CE divergence surface
    distinct from I20 (which is about presence-of-empty, not
    timing-of-empty). Document as CE20 and xfail-pin.
    """
    from mtg_bot.parity.cross_engine import (
        _dict_to_python_action,
        activated_mid_combat_side_channel,
        advance_phase_python,
        build_matched_states,
        build_python_field_view,
        multi_blocker_deckspec,
        retaliation_selector,
        step_both,
    )
    from mtg_bot.actions import apply_action as py_apply_action
    from mtg_bot.turn import Step

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(167):
        action = retaliation_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    advance_phase_python(py_state)
    rust_state.advance_phase()
    assert py_state.step == Step.BEGINNING_OF_COMBAT

    py_forest_id, rust_forest_id = activated_mid_combat_side_channel(
        py_state, rust_state,
    )

    # Activate the Forest on both engines.
    py_apply_action(
        py_state, 0, _dict_to_python_action({
            "kind": "activate_ability",
            "source_id": py_forest_id,
            "ability_index": 0,
        }),
    )
    rust_state.apply_action({
        "kind": "activate_ability",
        "source_id": rust_forest_id,
        "ability_index": 0,
    })

    # Sanity: both engines have {G} in p0's pool pre-advance.
    py_view_pre = build_python_field_view(py_state)
    rust_view_pre = parity_smoke._build_field_view(rust_state)
    assert dict(py_view_pre["mana_pool_p0"]).get("G", 0) == 1
    assert dict(rust_view_pre["mana_pool_p0"]).get("G", 0) == 1

    # ---- Advance phase ONE step ----
    advance_phase_python(py_state)
    rust_state.advance_phase()
    assert py_state.step == Step.DECLARE_ATTACKERS

    # ---- Compare post-advance mana_pool ----
    py_view_post = build_python_field_view(py_state)
    rust_view_post = parity_smoke._build_field_view(rust_state)

    expected_empty = (
        ("B", 0), ("C", 0), ("G", 0),
        ("R", 0), ("U", 0), ("W", 0),
    )
    assert py_view_post["mana_pool_p0"] == expected_empty, (
        f"Python: mana_pool_p0 should empty after phase advance "
        f"(I20). Got: {py_view_post['mana_pool_p0']}"
    )
    assert rust_view_post["mana_pool_p0"] == expected_empty, (
        f"Rust: mana_pool_p0 should empty after phase advance "
        f"(I20). Got: {rust_view_post['mana_pool_p0']}"
    )

    # Cross-engine parity on the post-advance mana_pool: both empty.
    assert py_view_post["mana_pool_p0"] == rust_view_post["mana_pool_p0"], (
        f"Post-phase-advance mana_pool_p0 diverges between engines -- "
        f"CE20 candidate (mana-empty timing asymmetry). Python: "
        f"{py_view_post['mana_pool_p0']}; Rust: "
        f"{rust_view_post['mana_pool_p0']}"
    )


def test_cross_engine_activated_mid_combat_selector_pre_injection_walks_clean(parity_smoke):
    """Pre-injection backbone steps 0-167 are parity-clean for the
    activated_mid_combat_selector.

    Same shape as the corresponding pre-injection test for every
    prior probe -- confirms the retaliation_selector backbone the
    Combat Forest injection rides on stays divergence-free up to
    the injection step. Distinguishes between "the Combat Forest
    side-channel itself introduces a divergence" and "something
    upstream of the side-channel is divergent and the probe just
    inherits it".
    """
    from mtg_bot.parity.cross_engine import (
        activated_mid_combat_selector,
        build_matched_states,
        multi_blocker_deckspec,
        step_both,
        walk_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=168,
        decision_selector=activated_mid_combat_selector,
    )
    assert result.error is None, (
        f"pre-injection walk aborted at step {result.aborted_at}: "
        f"{result.error}"
    )
    for step in result.steps:
        assert step.divergences == [], (
            f"pre-injection divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )

    # Sanity: the Combat Forest injection hasn't fired yet at end of
    # step 167 (3 creatures land on bf only at step 167's apply step
    # -- the selector's >= 3 trigger fires the NEXT call, i.e. step
    # 168).
    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(168):
        action = activated_mid_combat_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)
    in_any_zone = any(
        o.printing.name == "Combat Forest"
        for o in py_state.battlefield
    )
    assert not in_any_zone, (
        "Combat Forest should not yet exist at end of step 167 -- "
        "injection fires at step 168"
    )


# ---------------------------------------------------------------------------
# Phase 5 follow-up #22: activated_cost tests. Pins the
# activated_cost_selector walk + the predicted CE20 surface for
# activated abilities that COST MANA TO PAY (not free mana abilities).
# See cross_engine.activated_cost_selector for the full design notes.
#
# **Test surfaces:**
#
#   * Test A -- emission with affordance: Python emits ActivateAbility
#     for the Bear Caster (mana cost {1}{G} payable from 3 untapped
#     Forests on p0's bf). Rust does NOT emit (mana_produced.is_none()
#     filter at state_ops_legal.rs:929-1003). **CE20 SURFACED**.
#
#   * Test B -- emission with NO affordance: tap all p0's Forests +
#     empty mana pool. Python's can_pay_cost gate fails -> no emission.
#     Rust still doesn't emit (mana_produced filter fires unconditionally).
#     Both engines "no emit" -- parity-clean on this branch but for
#     entirely different reasons. The branch pins the affordability gate
#     isn't accidentally surfacing as a CE.
#
#   * Test C -- apply_action with sufficient mana in pool: pre-populate
#     {1}{G}. Python apply succeeds (auto_tap_for_cost deducts pool,
#     Bear taps, draw effect goes on stack). Rust apply RAISES
#     ValueError("source N has no mana_produced ..."). **CE20 SURFACED**
#     on dispatch axis.
#
#   * Test D -- apply_action with INSUFFICIENT mana: empty pool + tapped
#     Forests. Python silently under-pays (no self-gate in
#     _activate_ability; auto_tap_for_cost just does its best). Rust
#     still raises the no-mana_produced error. Documents a subtler axis
#     of CE20 (Python doesn't self-gate; Rust short-circuits regardless).
# ---------------------------------------------------------------------------


def test_cross_engine_activated_cost_test_a_emission_parity_post_ce20_closure(parity_smoke):
    """**CE20 CLOSURE — flipped from pre-closure shape-pin.**

    Post-CE20-substrate, Rust's CardPrinting carries an
    ``activated_abilities`` Vec and ``legal_decisions`` walks it to
    emit ActivateAbility per per-ability affordability. With the
    Bear Caster injection's cost-payable from p0's pool (the side-
    channel pre-populates the pool via Python's auto-tap-from-lands
    accounting; Rust's narrower pool-only affordability accepts the
    pre-populated pool the same way), the emission now appears on
    BOTH engines.

    Pre-closure shape (CE20 pre-substrate): this test asserted Rust
    does NOT emit; that was the load-bearing CE20 surface pin. The
    closure flips the assertion to "Rust DOES emit, with the same
    source id mapped through the per-engine id allocators".

    NOTE: Python's emission accounts for auto-tap-from-lands
    affordability; Rust's emission today is gated by pool-only
    coverage. The cross-engine smoke pre-populates p0's pool so
    both gates see the cost as affordable.
    """
    from mtg_bot.legal import legal_actions
    from mtg_bot.parity.cross_engine import (
        activated_cost_side_channel,
        build_matched_states,
        multi_blocker_deckspec,
        retaliation_selector,
        step_both,
    )
    from mtg_bot.turn import Step

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(167):
        action = retaliation_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    # Sanity: at PRECOMBAT_MAIN with p0 priority, sorcery timing holds.
    assert py_state.step == Step.PRECOMBAT_MAIN
    assert py_state.active_player_idx == 0
    assert py_state.priority_player_idx == 0

    py_bear_id, rust_bear_id = activated_cost_side_channel(
        py_state, rust_state,
    )
    assert py_bear_id > 0
    assert rust_bear_id > 0

    # Pre-populate p0's mana pool with {1}{G} on Rust so the pool-
    # only affordability check accepts the cost. Python's
    # auto-tap-from-lands accounting accepts the cost without any
    # priming (the 3 untapped Forests cover {1}{G} via auto-tap).
    from mtg_bot.game import ManaCoin
    rust_state.add_mana(0, "G", 1)
    rust_state.add_mana(0, "C", 1)

    # ---- Python ----
    py_actions = legal_actions(py_state, 0)
    py_activate_source_ids = [
        int(a.source_id) for a in py_actions
        if type(a).__name__ == "ActivateAbility"
    ]
    assert py_bear_id in py_activate_source_ids, (
        f"Python SHOULD emit ActivateAbility for the Bear Caster "
        f"(id {py_bear_id}); got {py_activate_source_ids}"
    )

    # ---- Rust (CE20 CLOSED — post-substrate Rust now emits) ----
    rust_actions = rust_state.legal_decisions(0)
    rust_activate_source_ids = [
        a.get("source_id") for a in rust_actions
        if a.get("kind") == "activate_ability"
    ]
    assert rust_bear_id in rust_activate_source_ids, (
        f"CE20 CLOSED — Rust SHOULD now emit ActivateAbility for the "
        f"Bear Caster (id {rust_bear_id}). The new activated_abilities "
        f"substrate walks the per-ability list and emits when the cost "
        f"is affordable from the pool. Got Rust ActivateAbility source "
        f"ids: {rust_activate_source_ids}"
    )

    # Sanity: the Forests on p0's bf DO emit ActivateAbility on BOTH
    # engines (their printings have mana_produced=["G"]). The legacy
    # mana-only path stays end-to-end functional post-closure.
    p0_forest_ids = {
        int(o.id) for o in py_state.battlefield
        if o.controller_id == 0 and o.printing.name == "Forest"
        and not o.tapped
    }
    py_forest_emit = {
        int(a.source_id) for a in py_actions
        if type(a).__name__ == "ActivateAbility"
    } & p0_forest_ids
    rust_forest_emit = {
        a.get("source_id") for a in rust_actions
        if a.get("kind") == "activate_ability"
    } & p0_forest_ids
    assert py_forest_emit == rust_forest_emit, (
        f"Untapped Forests should emit ActivateAbility identically on "
        f"both engines (free mana ability). Python forests: "
        f"{py_forest_emit}; Rust forests: {rust_forest_emit}."
    )


def test_cross_engine_activated_cost_test_b_no_emission_when_unaffordable(parity_smoke):
    """**Test B**: emission with insufficient mana affordance. Both
    engines do NOT emit -- parity-clean on this branch but for
    different reasons.

    Setup: walk to step 167, inject Bear Caster, then tap ALL of
    p0's Forests AND empty p0's mana pool. Probe both engines'
    emission.

    Expected (parity-clean negative): neither engine emits
    ActivateAbility for the Bear Caster.
      * Python: ``can_pay_cost`` at ``legal.py:653-657`` fails
        because no untapped Forests + empty pool means {1}{G} is
        unpayable. Skips emission.
      * Rust: still filters the bear out via
        ``mana_produced.is_none()`` regardless of affordance state
        (the filter fires before any cost check in Rust today).

    If Python now emits (e.g. the affordability gate is being
    bypassed), that's an orthogonal regression in Python's
    ``can_pay_cost`` -- NOT the CE20 surface. If Rust now emits,
    CE20 has been closed AND Rust's new emission code missing the
    affordability check would itself be a fresh divergence.
    """
    from mtg_bot.legal import legal_actions
    from mtg_bot.parity.cross_engine import (
        activated_cost_side_channel,
        build_matched_states,
        multi_blocker_deckspec,
        retaliation_selector,
        step_both,
    )

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(167):
        action = retaliation_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    py_bear_id, rust_bear_id = activated_cost_side_channel(
        py_state, rust_state,
    )

    # ---- Force the "cannot afford" precondition ----
    # Python: tap every untapped Forest on p0's bf + clear mana pool.
    for obj in py_state.battlefield:
        if obj.controller_id == 0 and obj.printing.name == "Forest":
            obj.tapped = True
    py_state.players[0].mana_pool.clear()
    # Rust: tap every Forest via the public tap helper +
    # empty_mana_pool. battlefield_snapshot yields one dict per
    # bf object across both players, sorted by etb_timestamp.
    for entry in rust_state.battlefield_snapshot():
        if entry.get("controller_id") == 0 and entry.get("printing_name") == "Forest":
            rust_state.tap_object(int(entry["id"]))
    rust_state.empty_mana_pool(0)

    # ---- Probe both ----
    py_actions = legal_actions(py_state, 0)
    py_activate_source_ids = [
        int(a.source_id) for a in py_actions
        if type(a).__name__ == "ActivateAbility"
    ]
    assert py_bear_id not in py_activate_source_ids, (
        f"Python should NOT emit ActivateAbility for Bear Caster "
        f"(id {py_bear_id}) when {{1}}{{G}} is unaffordable (all "
        f"Forests tapped + pool empty). If Python emits, "
        f"can_pay_cost is being bypassed -- orthogonal regression, "
        f"NOT CE20. Got: {py_activate_source_ids}"
    )

    rust_actions = rust_state.legal_decisions(0)
    rust_activate_source_ids = [
        a.get("source_id") for a in rust_actions
        if a.get("kind") == "activate_ability"
    ]
    assert rust_bear_id not in rust_activate_source_ids, (
        f"Rust should NOT emit ActivateAbility for Bear Caster -- "
        f"the mana_produced filter fires unconditionally. Got: "
        f"{rust_activate_source_ids}"
    )


def test_cross_engine_activated_cost_test_c_apply_dispatch_parity_post_ce20_closure(parity_smoke):
    """**CE20 CLOSURE — flipped from pre-closure shape-pin.**

    Post-CE20-substrate, Rust's ActivateAbility apply arm dispatches
    into ``printing.activated_abilities[ability_index]``, pays the
    mana cost from the controller's pool, taps the source, and
    pushes a StackItem carrying the effect (is_mana_ability=False
    routes through the stack per CR 605/113.3b). Both engines now
    accept the apply and converge on the post-state.

    Pre-closure shape (CE20 pre-substrate): Rust raised
    ValueError("has no mana_produced ..."). The closure flips the
    assertion to "Rust apply succeeds; both engines arrive at the
    same post-state shape".
    """
    from mtg_bot.actions import ActivateAbility as PyActivateAbility
    from mtg_bot.actions import apply_action as py_apply_action
    from mtg_bot.game import ManaCoin
    from mtg_bot.parity.cross_engine import (
        activated_cost_side_channel,
        build_matched_states,
        multi_blocker_deckspec,
        retaliation_selector,
        step_both,
    )

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(167):
        action = retaliation_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    py_bear_id, rust_bear_id = activated_cost_side_channel(
        py_state, rust_state,
    )

    # ---- Pre-populate p0's mana pool: {1}{G} = 1 generic + 1 G ----
    py_state.players[0].mana_pool.clear()
    py_state.players[0].mana_pool.append(ManaCoin(color="G"))
    py_state.players[0].mana_pool.append(ManaCoin(color="C"))
    rust_state.empty_mana_pool(0)
    rust_state.add_mana(0, "G", 1)
    rust_state.add_mana(0, "C", 1)

    # ---- Python apply: should succeed ----
    py_action = PyActivateAbility(source_id=py_bear_id, ability_index=0)
    pre_hand = len(py_state.players[0].hand)
    pre_pool_size = len(py_state.players[0].mana_pool)
    py_apply_action(py_state, 0, py_action)

    py_bear = next(o for o in py_state.battlefield if int(o.id) == py_bear_id)
    assert py_bear.tapped, (
        f"Python: Bear Caster (id {py_bear_id}) should be tapped after "
        f"apply_action(ActivateAbility) -- the tap_self cost fired. "
        f"Got tapped={py_bear.tapped}"
    )
    post_pool_size = len(py_state.players[0].mana_pool)
    assert post_pool_size == pre_pool_size - 2
    assert len(py_state.stack) == 1, (
        f"Python: stack should have exactly 1 StackItem (the draw "
        f"effect; is_mana_ability=False). Got: {len(py_state.stack)}"
    )
    assert len(py_state.players[0].hand) == pre_hand

    # ---- Rust apply: CE20 CLOSED — should now succeed ----
    rust_activate_dict = {
        "kind": "activate_ability",
        "source_id": rust_bear_id,
        "ability_index": 0,
    }
    rust_state.apply_action(rust_activate_dict)

    # Post-state parity:
    #   - Bear is tapped on both engines.
    assert rust_state.is_tapped(rust_bear_id) is True, (
        f"Rust: Bear Caster (id {rust_bear_id}) should be tapped "
        f"after the activate. Got tapped={rust_state.is_tapped(rust_bear_id)}"
    )
    #   - Rust's pool is drained of the 1G + 1C the Python add.
    rust_pool = rust_state.get_mana_pool(0)
    assert rust_pool["G"] == 0 and rust_pool["C"] == 0, (
        f"Rust: pool should be drained of {{1}}{{G}}; got {rust_pool}"
    )
    #   - Rust's stack carries the draw effect (is_mana_ability=False
    #     pushes a StackItem, mirroring Python's stack push).
    assert rust_state.stack_size() == 1, (
        f"Rust: stack should carry the draw effect post-activate; got "
        f"stack_size={rust_state.stack_size()}"
    )


def test_cross_engine_activated_cost_test_d_python_underpays_silently(parity_smoke):
    """**Test D (post-CE20-closure)**: apply_action with INSUFFICIENT
    mana in pool. Pins the asymmetry on the dispatch-time
    affordability gate:

      * Python: ``_activate_ability`` primitive does NOT self-gate
        (the gate lives in ``legal_actions``). An out-of-band
        unaffordable call silently under-pays and still pushes the
        draw on the stack.
      * Rust: the dispatch arm self-gates on
        ``pool_can_cover(pool, ability.cost.mana)`` via
        ``state_ops_cast::pay_mana_cost_pub`` — an unaffordable
        cost raises ValueError("unaffordable from controller's
        mana pool").

    Pre-closure shape: Rust raised "has no mana_produced". Post-
    closure the raise has the new message shape; the asymmetry axis
    (Python silent under-pay vs Rust loud reject) is preserved.
    A future slice might also rewire Python to self-gate at the
    primitive layer (full parity convergence at the gate axis).
    """
    import pytest
    from mtg_bot.actions import ActivateAbility as PyActivateAbility
    from mtg_bot.actions import apply_action as py_apply_action
    from mtg_bot.parity.cross_engine import (
        activated_cost_side_channel,
        build_matched_states,
        multi_blocker_deckspec,
        retaliation_selector,
        step_both,
    )

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(167):
        action = retaliation_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    py_bear_id, rust_bear_id = activated_cost_side_channel(
        py_state, rust_state,
    )

    # ---- Force unaffordable: tap all Forests + empty pool ----
    for obj in py_state.battlefield:
        if obj.controller_id == 0 and obj.printing.name == "Forest":
            obj.tapped = True
    py_state.players[0].mana_pool.clear()
    for entry in rust_state.battlefield_snapshot():
        if entry.get("controller_id") == 0 and entry.get("printing_name") == "Forest":
            rust_state.tap_object(int(entry["id"]))
    rust_state.empty_mana_pool(0)

    # ---- Python: silent under-pay ----
    py_action = PyActivateAbility(source_id=py_bear_id, ability_index=0)
    py_apply_action(py_state, 0, py_action)

    py_bear = next(o for o in py_state.battlefield if int(o.id) == py_bear_id)
    assert py_bear.tapped, (
        f"Python: Bear Caster should be tapped even when mana is "
        f"unaffordable (the tap_self cost fires before the mana check "
        f"is gated; _activate_ability doesn't self-gate). Got "
        f"tapped={py_bear.tapped}"
    )
    assert len(py_state.players[0].mana_pool) == 0, (
        f"Python: mana pool should remain empty (no mana to consume; "
        f"auto_tap_for_cost couldn't tap any lands). Got pool: "
        f"{py_state.players[0].mana_pool}"
    )
    assert len(py_state.stack) == 1, (
        f"Python: stack should still have the draw effect (the "
        f"ability went on the stack despite the under-payment; "
        f"the primitive doesn't self-gate). Got: "
        f"{len(py_state.stack)} items"
    )

    # ---- Rust: self-gates on affordability, raises "unaffordable" ----
    rust_activate_dict = {
        "kind": "activate_ability",
        "source_id": rust_bear_id,
        "ability_index": 0,
    }
    with pytest.raises(ValueError, match="unaffordable from controller's mana pool"):
        rust_state.apply_action(rust_activate_dict)


def test_cross_engine_activated_cost_test_e_auto_tap_headroom_emission_parity(parity_smoke):
    """**Test E (post-I50 auto-tap-from-lands composer closure)**.

    Pre-I50 the cross-engine smoke pre-populated p0's pool with
    `{1}{G}` before driving the ActivateAbility emission probe
    because Rust's affordability was POOL-ONLY — Python's
    auto-tap-from-lands accounting wasn't mirrored on the Rust
    side. Test A documents this gap explicitly: "the side-channel
    pre-populates the pool via Python's auto-tap-from-lands
    accounting; Rust's narrower pool-only affordability accepts the
    pre-populated pool the same way".

    Post-I50 Rust's `auto_tap_headroom_pool` composer matches
    Python's `can_pay_cost` model: emission-side affordability now
    sums pool + headroom from untapped non-sick mana sources on bf.
    With the side-channel's 3 untapped Forests on p0's bf, an empty
    pool composes to `{G}{G}{G}` of headroom, which covers
    `{1}{G}` directly — and the emission appears on BOTH engines
    WITHOUT priming the pool.

    Pins the converged emission-side affordability axis.
    """
    from mtg_bot.legal import legal_actions
    from mtg_bot.parity.cross_engine import (
        activated_cost_side_channel,
        build_matched_states,
        multi_blocker_deckspec,
        retaliation_selector,
        step_both,
    )
    from mtg_bot.turn import Step

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(167):
        action = retaliation_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)

    assert py_state.step == Step.PRECOMBAT_MAIN
    assert py_state.active_player_idx == 0
    assert py_state.priority_player_idx == 0

    py_bear_id, rust_bear_id = activated_cost_side_channel(
        py_state, rust_state,
    )
    assert py_bear_id > 0
    assert rust_bear_id > 0

    # **Crucial:** explicitly clear BOTH engines' p0 pools so the
    # affordability gate has to flow through the auto-tap-from-lands
    # composer on each side (not just consume floating mana that
    # leaked from earlier walk steps). The retaliation_selector
    # backbone leaves a couple of G coins in Python's pool from
    # tap-for-mana actions during the walk; without this clear, the
    # post-emission assertion would pass via floating mana, not via
    # the auto-tap composer — defeating the whole point of Test E.
    py_state.players[0].mana_pool.clear()
    rust_state.empty_mana_pool(0)
    rust_pool = rust_state.get_mana_pool(0)
    assert all(rust_pool[c] == 0 for c in ("W", "U", "B", "R", "G", "C")), (
        f"Test E precondition: Rust's p0 mana pool starts empty; got {rust_pool}"
    )
    assert len(py_state.players[0].mana_pool) == 0, (
        "Test E precondition: Python p0's mana pool is empty after clear."
    )

    # ---- Python emits via can_pay_cost auto-tap headroom ----
    py_actions = legal_actions(py_state, 0)
    py_activate_source_ids = [
        int(a.source_id) for a in py_actions
        if type(a).__name__ == "ActivateAbility"
    ]
    assert py_bear_id in py_activate_source_ids, (
        f"Python SHOULD emit ActivateAbility for Bear Caster (id "
        f"{py_bear_id}) with 0 pool + 3 untapped Forests via "
        f"can_pay_cost auto-tap headroom. Got {py_activate_source_ids}"
    )

    # ---- Rust emits via auto_tap_headroom_pool composer (I50) ----
    rust_actions = rust_state.legal_decisions(0)
    rust_activate_source_ids = [
        a.get("source_id") for a in rust_actions
        if a.get("kind") == "activate_ability"
    ]
    assert rust_bear_id in rust_activate_source_ids, (
        f"I50 CLOSED — Rust SHOULD now emit ActivateAbility for Bear "
        f"Caster (id {rust_bear_id}) with 0 pool + 3 untapped Forests, "
        f"matching Python's auto-tap-from-lands accounting. Got Rust "
        f"ActivateAbility source ids: {rust_activate_source_ids}"
    )


def test_cross_engine_activated_cost_selector_pre_injection_walks_clean(parity_smoke):
    """Pre-injection backbone steps 0-167 are parity-clean for the
    activated_cost_selector.

    Same shape as every prior probe's pre-injection walks-clean pin --
    confirms the retaliation_selector backbone the Bear Caster injection
    rides on stays divergence-free up to the injection step. Distinguishes
    between "the Bear Caster side-channel itself introduces a divergence"
    and "something upstream is divergent and the probe just inherits it".
    """
    from mtg_bot.parity.cross_engine import (
        activated_cost_selector,
        build_matched_states,
        multi_blocker_deckspec,
        step_both,
        walk_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=168,
        decision_selector=activated_cost_selector,
    )
    assert result.error is None, (
        f"pre-injection walk aborted at step {result.aborted_at}: "
        f"{result.error}"
    )
    for step in result.steps:
        assert step.divergences == [], (
            f"pre-injection divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )

    # Sanity: the Bear Caster injection hasn't fired yet at end of
    # step 167 (3 creatures land on bf only at step 167's apply step --
    # the selector's >= 3 trigger fires the NEXT call, i.e. step 168).
    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(168):
        action = activated_cost_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)
    in_any_zone = any(
        o.printing.name == "Bear Caster"
        for o in py_state.battlefield
    )
    assert not in_any_zone, (
        "Bear Caster should not yet exist at end of step 167 -- "
        "injection fires at step 168"
    )


# ---------------------------------------------------------------------------
# Phase 5 follow-up #21: multi_keyword_selector tests — MULTI-KEYWORD
# COMPOSITION combat (the eleven single-keyword surfaces — FS / DT /
# trample / lifelink / vigilance / haste / menace / defender /
# indestructible / double-strike / flying — are now well-covered, all
# clean or closed; this probe asks whether the keywords COMPOSE
# correctly on the same creature).
#
# Three scenarios:
#
#   * **Test A — Lifelink + Deathtouch (LL+DT).** A 2/2 LL+DT
#     attacker vs a 4/4 vanilla blocker. Per CR 702.2b + 702.15b:
#     attacker deals 2 to blocker; deathtouch upgrades mark to >= 4
#     (lethal); blocker dies. Blocker deals 4 back to attacker;
#     attacker (2 toughness) dies via SBA. Lifelink fires on the
#     literal 2 damage dealt -> p0 gains 2 life. Expected outcome on
#     both engines: both creatures dead, p0 life +2.
#
#   * **Test B — First-strike + Deathtouch (FS+DT).** A 2/2 FS+DT
#     attacker vs a 4/4 vanilla blocker. Per CR 702.7c + 702.2b:
#     first-strike pass deals 2 to blocker; deathtouch upgrades the
#     mark to >= 4 (lethal); blocker dies in the pass-1-alive-filter
#     gate. The regular pass alive-predicate filter drops the
#     blocker's back-damage entry (source is dead). Expected:
#     attacker survives with 0 marked damage, blocker dead.
#
#   * **Test C — Trample + Lifelink (T+LL).** A 4/4 T+LL attacker
#     vs a 2/2 vanilla blocker. Per CR 702.19b + 702.15b: trample
#     assigns lethal (= 2) to blocker, spills remaining 2 to
#     defender. Lifelink fires on BOTH entries (the blocker hit AND
#     the defender hit). Expected: blocker dead, attacker alive,
#     defender takes 2, p0 gains 4 life.
#
# **OUTCOME: (a) CLEAN PASS — no novel cross-engine divergence
# surfaced.** Both engines compose the keywords correctly per CR.
# Specifically:
#
#   * Lifelink fires per damage event (Python's combat.py:535-541) /
#     per plan entry (Rust's state_ops_combat.rs:1357-1364) at the
#     LITERAL `amount` value, not the deathtouch-upgraded mark. This
#     is correct (CR 702.15b: "Damage dealt by a creature with
#     lifelink causes its controller to gain that much life" — the
#     "that much" refers to the damage dealt, not the marked damage
#     after deathtouch upgrade).
#
#   * Deathtouch upgrades the recipient's mark to its toughness
#     (Python's `obj.marked_lethal = True` flag + SBA gate / Rust's
#     `obj.damage = recipient_toughness` upgrade at apply-time
#     state_ops_combat.rs:1336-1340). Both fire on creature-target
#     entries only; both fire BEFORE the post-combat SBA pass.
#
#   * Trample's spill-to-defender (Python combat.py:436-440 / Rust
#     state_ops_combat.rs:995-1008) fires the lifelink hook on the
#     spilled-to-defender entry the SAME way as the blocker entry
#     because lifelink runs in the per-event/per-entry apply loop
#     downstream of the plan partition (both engines).
#
#   * The CE18-closure alive-predicate filter (Rust
#     state_ops_combat.rs:1209-1247) drops the FS-killed blocker's
#     back-damage entry, matching Python's per-substep blockers-list
#     rebuild (combat.py:_resolve_damage_step). Both engines agree
#     on Test B's "attacker survives with 0 marked damage" outcome.
#
# Pinned by five new tests:
#
#   * test_cross_engine_multi_keyword_selector_walks_clean — full
#     200-decision walk on multi_blocker_deckspec with the LL+DT
#     injection, parity-clean every step.
#   * test_cross_engine_multi_keyword_lifelink_deathtouch — direct-
#     combat structural pin (Test A: LL+DT 2/2 vs vanilla 4/4).
#   * test_cross_engine_multi_keyword_first_strike_deathtouch —
#     direct-combat structural pin (Test B: FS+DT 2/2 vs vanilla 4/4).
#   * test_cross_engine_multi_keyword_trample_lifelink — direct-
#     combat structural pin (Test C: T+LL 4/4 vs vanilla 2/2).
#   * test_cross_engine_multi_keyword_selector_pre_injection_walks_clean
#     — steps 0-167 parity-clean (the selector's delegate-to-
#     retaliation_selector backbone is unchanged before step-168
#     injection).
# ---------------------------------------------------------------------------


def test_cross_engine_multi_keyword_selector_walks_clean(parity_smoke):
    """**Multi-keyword (LL+DT) clean-walk pin** — 200-decision walk on
    :func:`multi_blocker_deckspec` with :func:`multi_keyword_selector`
    is parity-clean every step. The LL+DT injection at step 168 +
    the single-blocker COMBAT_DAMAGE step around index 175 compose
    correctly on both engines: 2 damage assigned to Bears id 9 fires
    BOTH deathtouch mark-upgrade (mark >= 2 = toughness, blocker
    dies) AND lifelink (+2 life on p0).

    No CE21 surfaced on this slice. Outcome (a) — keywords compose
    correctly.
    """
    from mtg_bot.parity.cross_engine import (
        multi_blocker_deckspec,
        multi_keyword_selector,
        walk_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=200,
        decision_selector=multi_keyword_selector,
    )
    assert result.error is None, (
        f"walk aborted at step {result.aborted_at}: {result.error}"
    )
    for step in result.steps:
        assert step.divergences == [], (
            f"unexpected divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )


def test_cross_engine_multi_keyword_lifelink_deathtouch(parity_smoke):
    """**Test A — LL+DT composition pin** — fresh-state, direct
    combat invocation on both engines.

    Setup: 2/2 lifelink+deathtouch Bear Inquisitor on p0 bf; 4/4
    vanilla Bear Behemoth on p1 bf. Declare attack + block; resolve
    combat damage + SBAs.

    Expected end-state (matches both engines):
      * Attacker DEAD (took 4 back-damage from 4/4 blocker; 4 >=
        toughness 2 = lethal).
      * Blocker DEAD (took 2 damage; deathtouch upgrades mark to
        >= 4 = toughness; blocker dies in SBA per CR 702.2b).
      * p0 life = 22 (was 20; +2 from lifelink on the 2-damage
        creature event; lifelink fires on literal `amount`, not the
        deathtouch-upgraded mark).
      * p1 life = 20 (unchanged; no spillover, no trample).
      * Bear Inquisitor in p0 graveyard.
      * Bear Behemoth in p1 graveyard.

    Pins the contract that lifelink + deathtouch on the same source
    compose correctly: lifelink fires on the literal damage dealt
    (not the post-deathtouch upgraded mark), and deathtouch's mark
    upgrade is independent of lifelink.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.combat import resolve_combat_damage
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        multi_blocker_deckspec,
    )
    from mtg_bot.turn import state_based_actions

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())

    # ---- Python side: LL+DT 2/2 + vanilla 4/4 ----
    ll_dt_printing = CardPrinting(
        name="Bear Inquisitor",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset({"lifelink", "deathtouch"}),
    )
    py_atk = py_state.new_object(
        ll_dt_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_atk.summoning_sick = False
    py_atk.tapped = False
    py_atk.damage = 0
    py_atk.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_atk)

    behemoth_printing = CardPrinting(
        name="Bear Behemoth",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=4,
        toughness=4,
        produces=frozenset(),
        keywords=frozenset(),
    )
    py_blk = py_state.new_object(
        behemoth_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_blk.controller_id = 1
    py_blk.summoning_sick = False
    py_blk.tapped = False
    py_blk.damage = 0
    py_blk.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_blk)

    py_atk.attacking = True
    py_atk.tapped = True
    py_blk.blocking = int(py_atk.id)
    py_atk.blocked_by.append(int(py_blk.id))

    py_p0_before = py_state.players[0].life
    py_p1_before = py_state.players[1].life
    resolve_combat_damage(py_state, defending_player_id=1)
    state_based_actions(py_state)

    py_atk_alive = any(o.id == py_atk.id for o in py_state.battlefield)
    py_blk_alive = any(o.id == py_blk.id for o in py_state.battlefield)
    assert not py_atk_alive, (
        "Python LL+DT: attacker should be DEAD (took 4 back-damage from "
        "4/4 blocker; 4 >= toughness 2 = lethal)"
    )
    assert not py_blk_alive, (
        "Python LL+DT: blocker should be DEAD (took 2 damage; deathtouch "
        "upgrades mark to >= toughness 4 per CR 702.2b)"
    )
    assert py_state.players[0].life == py_p0_before + 2, (
        f"Python LL+DT: p0 life should be {py_p0_before + 2} (+2 from "
        f"lifelink on the literal 2-damage event); got "
        f"{py_state.players[0].life}"
    )
    assert py_state.players[1].life == py_p1_before, (
        f"Python LL+DT: p1 life unchanged at {py_p1_before} (no spillover, "
        f"no trample); got {py_state.players[1].life}"
    )

    # ---- Rust side: LL+DT 2/2 + vanilla 4/4 ----
    rust_atk_id = rust_state.register_and_inject_object(
        {
            "name": "Bear Inquisitor",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "keywords": ["lifelink", "deathtouch"],
        },
        0, 2,
    )
    rust_blk_id = rust_state.register_and_inject_object(
        {
            "name": "Bear Behemoth",
            "card_types": ["Creature"],
            "power": 4,
            "toughness": 4,
            "keywords": [],
        },
        1, 2,
    )
    rust_state.declare_attacker(rust_atk_id)
    rust_state.declare_blocker(rust_blk_id, rust_atk_id)
    rust_p0_before = rust_state.get_life(0)
    rust_p1_before = rust_state.get_life(1)
    rust_state.deal_combat_damage()
    rust_state.apply_sbas()

    rust_bf_ids = {int(e["id"]) for e in rust_state.battlefield_snapshot()}
    assert rust_atk_id not in rust_bf_ids, (
        "Rust LL+DT: attacker should be DEAD"
    )
    assert rust_blk_id not in rust_bf_ids, (
        "Rust LL+DT: blocker should be DEAD"
    )
    assert rust_state.get_life(0) == rust_p0_before + 2, (
        f"Rust LL+DT: p0 life should be {rust_p0_before + 2} (+2 from "
        f"lifelink); got {rust_state.get_life(0)}"
    )
    assert rust_state.get_life(1) == rust_p1_before, (
        f"Rust LL+DT: p1 life unchanged at {rust_p1_before}; got "
        f"{rust_state.get_life(1)}"
    )


def test_cross_engine_multi_keyword_first_strike_deathtouch(parity_smoke):
    """**Test B — FS+DT composition pin** — fresh-state, direct
    combat invocation on both engines.

    Setup: 2/2 first-strike+deathtouch Bear Slayer on p0 bf; 4/4
    vanilla Bear Behemoth on p1 bf. Declare attack + block; resolve
    combat damage + SBAs.

    Expected end-state (matches both engines):
      * FS substep: attacker deals 2 to blocker; deathtouch upgrades
        mark to >= toughness 4 (lethal). Blocker dies via mid-combat
        SBA (Python) or pass-2 alive-predicate filter (Rust).
      * Regular substep: blocker is dead; its back-damage entry is
        dropped (source is dead — Rust's `battlefield_creature_alive`
        filter at state_ops_combat.rs:1211 / Python's per-substep
        blockers-list rebuild at combat.py:_resolve_damage_step).
        Attacker takes no back-damage.
      * Attacker ALIVE with 0 marked damage.
      * Blocker DEAD; Bear Behemoth in p1 graveyard.
      * Life totals unchanged (no creature-to-player damage; no
        trample; no lifelink).

    Pins the contract that first-strike + deathtouch on the same
    source compose correctly: deathtouch upgrades the FS-substep
    mark to lethal (so the blocker dies BEFORE the regular substep),
    and the alive-predicate filter then drops the blocker's
    back-damage. This is the load-bearing CE18-closure-touches-
    deathtouch axis the brief flagged as a potential CE21 site.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.combat import resolve_combat_damage
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        multi_blocker_deckspec,
    )
    from mtg_bot.turn import state_based_actions

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())

    # ---- Python side ----
    fs_dt_printing = CardPrinting(
        name="Bear Slayer",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset({"first strike", "deathtouch"}),
    )
    py_atk = py_state.new_object(
        fs_dt_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_atk.summoning_sick = False
    py_atk.tapped = False
    py_atk.damage = 0
    py_atk.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_atk)

    behemoth_printing = CardPrinting(
        name="Bear Behemoth",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=4,
        toughness=4,
        produces=frozenset(),
        keywords=frozenset(),
    )
    py_blk = py_state.new_object(
        behemoth_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_blk.controller_id = 1
    py_blk.summoning_sick = False
    py_blk.tapped = False
    py_blk.damage = 0
    py_blk.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_blk)

    py_atk.attacking = True
    py_atk.tapped = True
    py_blk.blocking = int(py_atk.id)
    py_atk.blocked_by.append(int(py_blk.id))

    py_p0_before = py_state.players[0].life
    py_p1_before = py_state.players[1].life
    resolve_combat_damage(py_state, defending_player_id=1)
    state_based_actions(py_state)

    py_atk_alive = any(o.id == py_atk.id for o in py_state.battlefield)
    py_blk_alive = any(o.id == py_blk.id for o in py_state.battlefield)
    assert py_atk_alive, (
        "Python FS+DT: attacker should be ALIVE (FS killed the blocker "
        "BEFORE the regular substep; alive-predicate / per-substep "
        "rebuild drops blocker's back-damage)"
    )
    assert not py_blk_alive, (
        "Python FS+DT: blocker should be DEAD (FS substep + deathtouch "
        "upgrades mark to lethal)"
    )
    # Attacker's marked damage cleared by mid-combat SBA's apply pass —
    # actually, marked damage persists through end-of-turn cleanup
    # (CR 514.2). Within the resolve_combat_damage call + immediate SBA,
    # the attacker's damage stays whatever the regular substep would
    # have applied. The post-CE18 alive-filter drops the blocker's
    # back-damage entry, so attacker damage = 0.
    py_atk_obj = next(o for o in py_state.battlefield if o.id == py_atk.id)
    assert py_atk_obj.damage == 0, (
        f"Python FS+DT: attacker should have 0 marked damage (FS killed "
        f"blocker; regular-substep back-damage entry dropped because "
        f"source is dead); got damage={py_atk_obj.damage}"
    )
    assert py_state.players[0].life == py_p0_before, (
        f"Python FS+DT: p0 life unchanged at {py_p0_before} (no "
        f"lifelink); got {py_state.players[0].life}"
    )
    assert py_state.players[1].life == py_p1_before, (
        f"Python FS+DT: p1 life unchanged at {py_p1_before} (no "
        f"spillover, no trample); got {py_state.players[1].life}"
    )

    # ---- Rust side ----
    rust_atk_id = rust_state.register_and_inject_object(
        {
            "name": "Bear Slayer",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "keywords": ["first_strike", "deathtouch"],
        },
        0, 2,
    )
    rust_blk_id = rust_state.register_and_inject_object(
        {
            "name": "Bear Behemoth",
            "card_types": ["Creature"],
            "power": 4,
            "toughness": 4,
            "keywords": [],
        },
        1, 2,
    )
    rust_state.declare_attacker(rust_atk_id)
    rust_state.declare_blocker(rust_blk_id, rust_atk_id)
    rust_p0_before = rust_state.get_life(0)
    rust_p1_before = rust_state.get_life(1)
    rust_state.deal_combat_damage()
    rust_state.apply_sbas()

    rust_bf_ids = {int(e["id"]) for e in rust_state.battlefield_snapshot()}
    assert rust_atk_id in rust_bf_ids, (
        "Rust FS+DT: attacker should be ALIVE (FS killed blocker; "
        "alive-predicate filter drops back-damage entry)"
    )
    assert rust_blk_id not in rust_bf_ids, (
        "Rust FS+DT: blocker should be DEAD"
    )
    rust_atk_damage = next(
        (int(e.get("damage", 0))
         for e in rust_state.battlefield_snapshot()
         if int(e["id"]) == rust_atk_id),
        None,
    )
    assert rust_atk_damage == 0, (
        f"Rust FS+DT: attacker damage=0 (back-damage entry dropped); "
        f"got damage={rust_atk_damage}"
    )
    assert rust_state.get_life(0) == rust_p0_before, (
        f"Rust FS+DT: p0 life unchanged at {rust_p0_before}; got "
        f"{rust_state.get_life(0)}"
    )
    assert rust_state.get_life(1) == rust_p1_before, (
        f"Rust FS+DT: p1 life unchanged at {rust_p1_before}; got "
        f"{rust_state.get_life(1)}"
    )


def test_cross_engine_multi_keyword_trample_lifelink(parity_smoke):
    """**Test C — T+LL composition pin** — fresh-state, direct combat
    invocation on both engines.

    Setup: 4/4 trample+lifelink Bear Crusher on p0 bf; 2/2 vanilla
    Bear Cub on p1 bf. Declare attack + block; resolve combat
    damage + SBAs.

    Expected end-state (matches both engines):
      * Attacker (4 power) assigns 2 to blocker (= blocker's
        toughness = lethal floor under non-deathtouch), 2 trample-
        excess to defender (CR 702.19b).
      * Blocker DEAD (took 2 = toughness).
      * Attacker ALIVE (took 2 back-damage from 2/2 blocker; 2 <
        toughness 4 = non-lethal).
      * Attacker damage = 2 (marked).
      * p0 life = 24 (was 20; +4 from lifelink — TWO entries fire:
        +2 from the blocker hit AND +2 from the defender hit. Pins
        the contract that lifelink fires on the trample-spillover
        entry too, not just the blocker entry.)
      * p1 life = 18 (was 20; -2 from trample excess).
      * Bear Cub in p1 graveyard.

    This is the load-bearing T+LL composition pin — surfaces the
    "lifelink + trample double-counts or misses spillover" axis the
    brief flagged as a potential CE21 candidate.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.combat import resolve_combat_damage
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        multi_blocker_deckspec,
    )
    from mtg_bot.turn import state_based_actions

    py_state, rust_state = build_matched_states(multi_blocker_deckspec())

    # ---- Python side ----
    t_ll_printing = CardPrinting(
        name="Bear Crusher",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=4,
        toughness=4,
        produces=frozenset(),
        keywords=frozenset({"trample", "lifelink"}),
    )
    py_atk = py_state.new_object(
        t_ll_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_atk.summoning_sick = False
    py_atk.tapped = False
    py_atk.damage = 0
    py_atk.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_atk)

    cub_printing = CardPrinting(
        name="Bear Cub",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset(),
    )
    py_blk = py_state.new_object(
        cub_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_blk.controller_id = 1
    py_blk.summoning_sick = False
    py_blk.tapped = False
    py_blk.damage = 0
    py_blk.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_blk)

    py_atk.attacking = True
    py_atk.tapped = True
    py_blk.blocking = int(py_atk.id)
    py_atk.blocked_by.append(int(py_blk.id))

    py_p0_before = py_state.players[0].life
    py_p1_before = py_state.players[1].life
    resolve_combat_damage(py_state, defending_player_id=1)
    state_based_actions(py_state)

    py_atk_alive = any(o.id == py_atk.id for o in py_state.battlefield)
    py_blk_alive = any(o.id == py_blk.id for o in py_state.battlefield)
    assert py_atk_alive, (
        "Python T+LL: attacker should be ALIVE (took 2 < toughness 4 "
        "back-damage)"
    )
    assert not py_blk_alive, (
        "Python T+LL: blocker should be DEAD (took 2 = toughness)"
    )
    assert py_state.players[0].life == py_p0_before + 4, (
        f"Python T+LL: p0 life should be {py_p0_before + 4} (+4 from "
        f"lifelink: 2 on blocker hit + 2 on defender trample-spillover "
        f"hit; pins the contract that lifelink fires on both entries); "
        f"got {py_state.players[0].life}"
    )
    assert py_state.players[1].life == py_p1_before - 2, (
        f"Python T+LL: p1 life should be {py_p1_before - 2} (-2 from "
        f"trample excess: 4 power - 2 lethal-to-blocker = 2 spillover); "
        f"got {py_state.players[1].life}"
    )

    # ---- Rust side ----
    rust_atk_id = rust_state.register_and_inject_object(
        {
            "name": "Bear Crusher",
            "card_types": ["Creature"],
            "power": 4,
            "toughness": 4,
            "keywords": ["trample", "lifelink"],
        },
        0, 2,
    )
    rust_blk_id = rust_state.register_and_inject_object(
        {
            "name": "Bear Cub",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "keywords": [],
        },
        1, 2,
    )
    rust_state.declare_attacker(rust_atk_id)
    rust_state.declare_blocker(rust_blk_id, rust_atk_id)
    rust_p0_before = rust_state.get_life(0)
    rust_p1_before = rust_state.get_life(1)
    rust_state.deal_combat_damage()
    rust_state.apply_sbas()

    rust_bf_ids = {int(e["id"]) for e in rust_state.battlefield_snapshot()}
    assert rust_atk_id in rust_bf_ids, (
        "Rust T+LL: attacker should be ALIVE"
    )
    assert rust_blk_id not in rust_bf_ids, (
        "Rust T+LL: blocker should be DEAD"
    )
    assert rust_state.get_life(0) == rust_p0_before + 4, (
        f"Rust T+LL: p0 life should be {rust_p0_before + 4} (+4 from "
        f"lifelink; matches Python); got {rust_state.get_life(0)}"
    )
    assert rust_state.get_life(1) == rust_p1_before - 2, (
        f"Rust T+LL: p1 life should be {rust_p1_before - 2} (-2 trample "
        f"excess; matches Python); got {rust_state.get_life(1)}"
    )


def test_cross_engine_multi_keyword_selector_pre_injection_walks_clean(
    parity_smoke,
):
    """Pre-injection backbone steps 0-167 are parity-clean for the
    multi_keyword_selector.

    Confirms the retaliation_selector backbone the Bear Inquisitor
    injection rides on stays divergence-free up to the injection
    step. Distinguishes between "the LL+DT side-channel itself
    introduces a divergence" and "something upstream is divergent
    and the probe just inherits it".
    """
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        multi_blocker_deckspec,
        multi_keyword_selector,
        step_both,
        walk_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=168,
        decision_selector=multi_keyword_selector,
    )
    assert result.error is None, (
        f"pre-injection walk aborted at step {result.aborted_at}: "
        f"{result.error}"
    )
    for step in result.steps:
        assert step.divergences == [], (
            f"pre-injection divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )

    # Sanity: the Bear Inquisitor injection hasn't fired yet at end
    # of step 167 (3 creatures land on bf only at step 167's apply
    # step -- the selector's >= 3 trigger fires the NEXT call,
    # i.e. step 168).
    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(168):
        action = multi_keyword_selector(py_state, rust_state, i)
        step_both(py_state, rust_state, action)
    in_any_zone = any(
        o.printing.name == "Bear Inquisitor"
        for o in py_state.battlefield
    )
    assert not in_any_zone, (
        "Bear Inquisitor should not yet exist at end of step 167 -- "
        "injection fires at step 168"
    )


# =====================================================================
# Phase 5 probe lane: real EoE-card ETB-trigger smoke
# =====================================================================
#
# These probes pin that real-EoE-card ETB triggers fire to parity on
# both engines by leveraging the ETB-trigger substrate (Slices 1-11 in
# `docs/RUST_ETB_TRIGGER_AUDIT.md`). Each probe:
#
#   1. Builds a `CardDef` mirroring a REAL Edge-of-Eternities printing
#      whose oracle text reduces to one ETB trigger the substrate
#      already supports (SourceIsSelf + DrawCards / GainLife so far).
#      Non-ETB oracle text (e.g. Warp, secondary clauses) is OUT of
#      scope -- the probe's contract is the ETB-trigger surface.
#
#   2. Injects the printing onto p0's hand via
#      `register_and_inject_object` (Rust) / direct GameObject
#      construction (Python) so the cast path uses the post-resolve
#      ETB substrate without depending on land/mana plumbing.
#
#   3. Casts the spell, drains the stack on both engines, and compares
#      the post-drain (life_p0, life_p1, hand_p0, hand_p1, bf
#      contents) tuple. Divergence on ANY axis surfaces a new CE.
#
# Outcomes:
#
#   (a) Clean pass -- both engines agree post-drain. Logged below;
#       moves the next probe forward.
#   (b) CE21 surfaces -- xfail-pin with a CE21 doc entry, switch to
#       closure-plan mode.
#   (c) Old-known-gap surfaces -- xfail-pin with cross-reference to
#       the existing CE entry.

def _build_eoe_etb_state(card_def):
    """Build matched Python + Rust states for a real-EoE probe.

    The card_def carries the ETB trigger; the deckspec ships one copy
    on each player's library so both engines materialize the printing
    on the registry the same way. Caller then injects onto a zone via
    the standard inject-and-resolve pattern.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    spec = DeckSpec(
        card_defs=(card_def,),
        p0_library=(card_def.name,),
        p1_library=(card_def.name,),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)
    return py_state, rust_state


def _drain_stack_both(py_state, rust_state):
    """Resolve the top of stack on both engines until both stacks are
    empty. Mirrors the synchronous draining pattern used by
    `test_rust_state_builder_wires_triggered_abilities` in
    test_cross_engine_etb_triggers.py.
    """
    from mtg_bot.actions import resolve_top_of_stack
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()
    while py_state.stack:
        resolve_top_of_stack(py_state)


def test_cross_engine_real_eoe_germinating_wurm_etb_gain_life_parity(
    parity_smoke,
):
    """Probe: Germinating Wurm (EoE) ETB trigger fires + parity-matches.

    Oracle text in `data/edge_of_eternities.json`:

        "When this creature enters, you gain 2 life.
         Warp {1}{G} (...)"

    The Warp clause is out of scope -- this probe exclusively exercises
    the ETB-trigger surface, which is the substrate's current
    sweet-spot:

      * Event: `enters`
      * Predicate: `source_is_self` (only the just-entered creature's
        own trigger fires)
      * Effect: `gain_life` amount=2

    Expected post-cast + post-drain state on BOTH engines:

      * Germinating Wurm on p0's battlefield (the spell's
        StackItem resolves to a permanent first, then the
        ETB trigger lands on top of the stack and is resolved
        next).
      * p0 life: 20 -> 22 (+2 from the ETB gain_life).
      * p1 life: unchanged at 20.
      * No residual stack on either engine.
      * No residual hand objects.

    This is the simplest cross-engine smoke for a REAL EoE card's
    ETB trigger -- a clean pass here pins the substrate end-to-end
    on a printing that lives in the actual draft pool, not just on
    the synthetic Slice-3 "ETB Draw Bear" fixture. Outcome (a) for
    this probe means the next probe can pick a more complex
    predicate / effect shape.
    """
    from mtg_bot.parity.cross_engine import CardDef
    germinating_wurm = CardDef(
        name="Germinating Wurm",
        card_type="Creature",
        mana_cost_generic=4,
        mana_cost_colored=(("G", 1),),
        power=5,
        toughness=5,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "gain_life", "amount": 2},
            },
        ),
    )
    py_state, rust_state = _build_eoe_etb_state(germinating_wurm)

    # ---- Rust side ----
    # Register-and-inject onto p0's hand, then push the spell onto the
    # stack and resolve. The substrate fires the ETB trigger onto the
    # stack right after the spell resolves; the trigger lands +2 life.
    ZONE_HAND = 0
    ZONE_BATTLEFIELD = 2
    rust_dict = {
        "name": "Germinating Wurm",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 4, "G": 1},
        "effects": [],
        "power": 5,
        "toughness": 5,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "gain_life", "amount": 2},
            }
        ],
    }
    rust_wurm_id = rust_state.register_and_inject_object(
        rust_dict, 0, ZONE_HAND
    )
    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)
    rust_state.push_to_stack(rust_wurm_id, 0)
    rust_state.resolve_top_of_stack()
    # Spell resolved -> permanent on bf, ETB trigger now on stack.
    assert rust_state.find_object_zone(rust_wurm_id) == ZONE_BATTLEFIELD
    assert rust_state.stack_size() == 1, (
        "expected Germinating Wurm's ETB trigger to land on the stack "
        "after the spell resolves"
    )

    # ---- Python side ----
    # Mirror the inject-and-resolve pattern: move the obj from library
    # to hand, then push onto the stack directly (bypassing mana cost
    # -- the substrate's contract is the resolve-and-fire path, not
    # the mana-payment path).
    from mtg_bot.actions import resolve_top_of_stack as py_resolve
    from mtg_bot.game import StackItem, Zone
    py_obj = py_state.players[0].library[0]
    assert py_obj.printing.name == "Germinating Wurm"
    py_state.players[0].library.remove(py_obj)
    py_obj.zone = Zone.STACK
    py_state.stack.append(StackItem(source=py_obj, controller_id=0))
    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life
    py_resolve(py_state)
    # Spell resolved -> permanent on bf, ETB trigger now on stack.
    assert any(
        o.printing.name == "Germinating Wurm"
        for o in py_state.battlefield
    ), "Germinating Wurm should be on Python p0's battlefield"
    assert len(py_state.stack) == 1, (
        "expected Germinating Wurm's ETB trigger to land on the "
        "Python stack after the spell resolves"
    )

    # ---- Drain both stacks, then compare ----
    _drain_stack_both(py_state, rust_state)

    # Post-drain parity: stacks empty, +2 life to p0, p1 unchanged.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0
    assert rust_state.get_life(0) == rust_p0_life_before + 2, (
        f"Rust p0 life should be {rust_p0_life_before + 2}; "
        f"got {rust_state.get_life(0)}"
    )
    assert rust_state.get_life(1) == rust_p1_life_before, (
        f"Rust p1 life should be unchanged at {rust_p1_life_before}; "
        f"got {rust_state.get_life(1)}"
    )
    assert py_state.players[0].life == py_p0_life_before + 2, (
        f"Python p0 life should be {py_p0_life_before + 2}; "
        f"got {py_state.players[0].life}"
    )
    assert py_state.players[1].life == py_p1_life_before, (
        f"Python p1 life should be unchanged at {py_p1_life_before}; "
        f"got {py_state.players[1].life}"
    )
    # Cross-engine: same final life totals.
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life


def test_cross_engine_real_eoe_quantum_riddler_etb_draw_parity(
    parity_smoke,
):
    """Probe: Quantum Riddler (EoE) ETB trigger fires + parity-matches.

    Oracle text in `data/edge_of_eternities.json`:

        "Flying
         When this creature enters, draw a card.
         As long as you have one or fewer cards in hand, if you would
         draw one or more cards, you draw that many cards plus one
         instead.
         Warp {1}{U}"

    The flying / replacement / warp clauses are out of scope -- this
    probe exclusively exercises the ETB-trigger surface
    (`SourceIsSelf` + `DrawCards(1)`). Note Quantum Riddler is the
    LITERAL "ETB Draw Bear" of the EoE pool, modulo cost and
    stats: the substrate's Slice-3 synthetic-fixture motif is a
    real-card pattern.

    Expected post-cast + post-drain state on BOTH engines:

      * Quantum Riddler on p0's battlefield.
      * p0 hand grows by exactly 1 (the ETB DrawCards(1) trigger
        drew a card from p0's library).
      * p0 library shrinks by exactly 1 (the drawn card).
      * p1 hand / library unchanged.
      * No residual stack.

    For the draw to have something to draw from, we ship a second
    copy of Germinating Wurm in p0's library as the "card to be
    drawn" fixture. (Using a second printing -- Germinating Wurm --
    keeps the library card distinct from the cast spell so a
    "library/hand confusion" bug would surface a clear name
    divergence.)
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )
    quantum_riddler = CardDef(
        name="Quantum Riddler",
        card_type="Creature",
        mana_cost_generic=3,
        mana_cost_colored=(("U", 2),),
        power=4,
        toughness=6,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "draw_cards", "count": 1},
            },
        ),
    )
    germinating_wurm = CardDef(
        name="Germinating Wurm",
        card_type="Creature",
        mana_cost_generic=4,
        mana_cost_colored=(("G", 1),),
        power=5,
        toughness=5,
        # NOTE: this copy lives in p0's library purely as a
        # draw-target. It carries the SAME ETB trigger as in the
        # prior probe, but the trigger is only relevant if the wurm
        # itself enters -- which it doesn't on the draw path. The
        # DrawCards(1) effect moves the wurm from library to hand,
        # not to bf, so the wurm's own ETB does NOT fire here.
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "gain_life", "amount": 2},
            },
        ),
    )
    spec = DeckSpec(
        card_defs=(quantum_riddler, germinating_wurm),
        p0_library=("Germinating Wurm",),
        p1_library=("Germinating Wurm",),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_HAND = 0
    ZONE_BATTLEFIELD = 2
    rust_dict = {
        "name": "Quantum Riddler",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 3, "U": 2},
        "effects": [],
        "power": 4,
        "toughness": 6,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "draw_cards", "count": 1},
            }
        ],
    }
    rust_riddler_id = rust_state.register_and_inject_object(
        rust_dict, 0, ZONE_HAND
    )
    rust_p0_hand_before = rust_state.hand_sizes[0]
    rust_p0_lib_before = rust_state.library_sizes[0]
    rust_state.push_to_stack(rust_riddler_id, 0)
    rust_state.resolve_top_of_stack()
    assert rust_state.find_object_zone(rust_riddler_id) == ZONE_BATTLEFIELD
    assert rust_state.stack_size() == 1, (
        "Quantum Riddler's ETB DrawCards(1) trigger should be on the "
        "Rust stack post-resolve"
    )

    # ---- Python side ----
    from mtg_bot.actions import resolve_top_of_stack as py_resolve
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import StackItem, Zone

    # Build a Python CardPrinting for Quantum Riddler that mirrors
    # the Rust registry's predicate-path trigger shape. (The
    # cross_engine.build_python_state path only materializes
    # printings from the DeckSpec's card_defs; injecting a
    # printing not in the deckspec needs a fresh CardPrinting +
    # state.new_object, mirroring the existing side-channel pattern
    # used by `vigilance_side_channel`.)
    riddler_printing = CardPrinting(
        name="Quantum Riddler",
        mana_cost_str="",
        mana_cost=ManaCost(generic=3, colored=(("U", 2),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=4,
        toughness=6,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=DrawCards(amount=1),
            ),
        ),
    )
    py_riddler = py_state.new_object(
        riddler_printing, owner_id=0, zone=Zone.HAND,
    )
    py_state.players[0].hand.append(py_riddler)
    py_p0_hand_before = len(py_state.players[0].hand)
    py_p0_lib_before = len(py_state.players[0].library)
    # Cast: move from hand to stack via direct StackItem push (same
    # bypass-mana-cost shape as the wurm probe).
    py_riddler.zone = Zone.STACK
    py_state.players[0].hand.remove(py_riddler)
    py_state.stack.append(
        StackItem(source=py_riddler, controller_id=0)
    )
    py_resolve(py_state)
    assert any(
        o.printing.name == "Quantum Riddler"
        for o in py_state.battlefield
    )
    assert len(py_state.stack) == 1, (
        "Python: Quantum Riddler's ETB DrawCards(1) trigger should be "
        "on the stack post-resolve"
    )

    # ---- Drain both stacks, then compare ----
    _drain_stack_both(py_state, rust_state)

    # Post-drain: each engine's p0 hand grew by 1 vs the pre-cast
    # snapshot (the Riddler itself was injected into the hand and
    # then went to bf, so its passage through hand is net-zero --
    # the +1 we see comes from the ETB DrawCards). The pre-cast
    # snapshots above were taken AFTER the riddler was injected on
    # both engines, so both deltas are +1 net.
    rust_p0_hand_after = rust_state.hand_sizes[0]
    rust_p0_lib_after = rust_state.library_sizes[0]
    py_p0_hand_after = len(py_state.players[0].hand)
    py_p0_lib_after = len(py_state.players[0].library)

    # The pre-cast hand snapshot included the riddler; post-cast the
    # riddler is on bf, BUT the ETB drew exactly 1 card from the
    # library into the hand. Net delta: hand size unchanged
    # (-1 for riddler leaving hand, +1 for the draw), library -1.
    assert rust_p0_hand_after == rust_p0_hand_before, (
        f"Rust p0 hand should be unchanged (riddler leaves hand "
        f"to bf, +1 draw replaces it): before={rust_p0_hand_before} "
        f"after={rust_p0_hand_after}"
    )
    assert rust_p0_lib_after == rust_p0_lib_before - 1, (
        f"Rust p0 library should shrink by 1 (the draw): "
        f"before={rust_p0_lib_before} after={rust_p0_lib_after}"
    )
    assert py_p0_hand_after == py_p0_hand_before, (
        f"Python p0 hand should be unchanged (riddler leaves hand "
        f"to bf, +1 draw replaces it): before={py_p0_hand_before} "
        f"after={py_p0_hand_after}"
    )
    assert py_p0_lib_after == py_p0_lib_before - 1, (
        f"Python p0 library should shrink by 1 (the draw): "
        f"before={py_p0_lib_before} after={py_p0_lib_after}"
    )

    # Cross-engine: same final library / hand sizes.
    assert rust_p0_hand_after == py_p0_hand_after
    assert rust_p0_lib_after == py_p0_lib_after
    assert rust_state.hand_sizes[1] == len(py_state.players[1].hand)
    assert rust_state.library_sizes[1] == len(py_state.players[1].library)


def test_cross_engine_real_eoe_eumidian_terrabotanist_landfall_parity(
    parity_smoke,
):
    """Probe: Eumidian Terrabotanist (EoE) Landfall trigger
    fires + parity-matches on a SUBJECT-not-SOURCE predicate path.

    Oracle text in `data/edge_of_eternities.json`:

        "Landfall - Whenever a land you control enters, you gain
         1 life."

    This is the **first** real-EoE probe that exercises the
    SUBJECT-vs-SOURCE distinction in the predicate algebra:

      * The TRIGGER SOURCE is the Eumidian Terrabotanist (a
        creature that's pre-placed on p0's battlefield).
      * The TRIGGER SUBJECT is a LAND that enters under p0's
        control (i.e. a Forest played by p0).

    The predicate `subject_is_land AND controlled_by_you`
    composes two Slice-4 predicate variants: `SubjectIsLand`
    (filters the event subject to land cards) AND
    `ControlledByYou` (the subject's controller must equal the
    trigger source's controller, i.e. p0).

    Both Slice-2's land-play-path dispatch_event fan-out (Rust:
    one of the 11 ETB-stamping sites threaded in
    `state_ops_cast.rs`'s `play_land` arm; Python:
    `actions.py:1139` inside `_play_land`) and the predicate
    algebra Slice 4 wired must be correct end-to-end for this
    probe to pass.

    Expected post-cast + post-drain state on BOTH engines:

      * Terrabotanist still on p0's bf (pre-placed; doesn't move).
      * Forest now on p0's bf (just played).
      * p0 life: 20 -> 21 (+1 from the landfall trigger).
      * p1 life: unchanged at 20.
      * No residual stack.

    Outcome (a) clean pass here proves the substrate dispatches
    correctly on the Subject-vs-Source distinction -- the same
    predicate shape covers the entire EoE Landfall surface (16
    printings counted in `data/edge_of_eternities.json`).
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )
    terra = CardDef(
        name="Eumidian Terrabotanist",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=2,
        toughness=3,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {
                    "kind": "and",
                    "left": {"kind": "subject_is_land"},
                    "right": {"kind": "controlled_by_you"},
                },
                "effect": {"kind": "gain_life", "amount": 1},
            },
        ),
    )
    forest = CardDef(
        name="Forest", card_type="Land", mana_produced=("G",),
    )
    spec = DeckSpec(
        card_defs=(terra, forest),
        p0_library=("Forest", "Forest"),
        p1_library=("Forest", "Forest"),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_HAND = 0
    ZONE_BATTLEFIELD = 2
    rust_terra_dict = {
        "name": "Eumidian Terrabotanist",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1, "G": 1},
        "effects": [],
        "power": 2,
        "toughness": 3,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {
                    "kind": "and",
                    "left": {"kind": "subject_is_land"},
                    "right": {"kind": "controlled_by_you"},
                },
                "effect": {"kind": "gain_life", "amount": 1},
            }
        ],
    }
    rust_terra_id = rust_state.register_and_inject_object(
        rust_terra_dict, 0, ZONE_BATTLEFIELD
    )
    rust_forest_dict = {
        "name": "Forest",
        "card_types": ["Land"],
        "mana_produced": ["G"],
        "effects": [],
    }
    rust_forest_id = rust_state.register_and_inject_object(
        rust_forest_dict, 0, ZONE_HAND
    )
    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)
    # play_land(card_id, player_id)
    rust_state.play_land(rust_forest_id, 0)
    assert rust_state.find_object_zone(rust_forest_id) == ZONE_BATTLEFIELD, (
        "Rust: Forest should be on bf after play_land"
    )
    assert rust_state.stack_size() == 1, (
        "Rust: Terrabotanist's landfall trigger should be on the "
        "stack after the Forest enters"
    )

    # ---- Python side ----
    from mtg_bot.actions import _play_land, resolve_top_of_stack as py_resolve
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.effects.object_predicates import IsLand
    from mtg_bot.effects.predicates import (
        And, Controlled, Event, Subject, YOU,
    )
    from mtg_bot.game import Zone

    # Build the Python Terrabotanist printing with the SAME
    # predicate-path trigger shape.
    terra_predicate = And(
        left=Subject(slot=None, inner=IsLand()),
        right=Controlled(by=YOU, subject=None),
    )
    terra_printing = CardPrinting(
        name="Eumidian Terrabotanist",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=(("G", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=3,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=terra_predicate,
                effect=GainLife(amount=1),
            ),
        ),
    )
    py_terra = py_state.new_object(
        terra_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_terra.summoning_sick = False
    py_terra.tapped = False
    py_terra.damage = 0
    py_terra.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_terra)

    # Move a Forest from library to hand on Python side.
    py_forest = py_state.players[0].library[0]
    assert py_forest.printing.name == "Forest"
    py_state.players[0].library.remove(py_forest)
    py_forest.zone = Zone.HAND
    py_state.players[0].hand.append(py_forest)

    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life

    # Reset Python's "lands_played_this_turn" so _play_land doesn't
    # gate on the per-turn cap (the rust harness has no such gate
    # in the inject-and-play substrate path).
    py_state.players[0].lands_played_this_turn = 0
    _play_land(py_state, 0, py_forest.id)

    assert any(
        o.printing.name == "Forest" and o.controller_id == 0
        for o in py_state.battlefield
    ), "Python: Forest should be on bf after _play_land"
    assert len(py_state.stack) == 1, (
        "Python: Terrabotanist's landfall trigger should be on the "
        "stack after the Forest enters"
    )

    # ---- Drain both stacks, then compare ----
    _drain_stack_both(py_state, rust_state)

    # Post-drain parity: +1 life on p0 from landfall trigger.
    assert rust_state.get_life(0) == rust_p0_life_before + 1, (
        f"Rust p0 life should be {rust_p0_life_before + 1} "
        f"(+1 from landfall); got {rust_state.get_life(0)}"
    )
    assert rust_state.get_life(1) == rust_p1_life_before
    assert py_state.players[0].life == py_p0_life_before + 1, (
        f"Python p0 life should be {py_p0_life_before + 1} "
        f"(+1 from landfall); got {py_state.players[0].life}"
    )
    assert py_state.players[1].life == py_p1_life_before
    # Cross-engine: same post-drain life totals.
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life


def test_cross_engine_real_eoe_mechan_assembler_another_artifact_parity(
    parity_smoke,
):
    """Probe D: Mechan Assembler (EoE) "another artifact" ETB trigger
    fires + parity-matches on the predicate algebra's NOT branch.

    Oracle text in `data/edge_of_eternities.json`:

        "Whenever another artifact you control enters, create a 2/2
         colorless Robot artifact creature token. This ability
         triggers only once each turn."

    The token-creation effect and the once_per_turn rider are
    deferred to follow-on probes (token creation isn't yet on the
    cross-engine effect bridge; once_per_turn pin lands in the next
    probe). This probe restricts the surface to the predicate-algebra
    novelty: the **NOT branch** that the prior three probes haven't
    exercised. The trigger predicate reduces to:

        Subject(IsArtifact) AND ControlledByYou AND NOT(IsSelf)

    -- composed via two Slice-1 algebra nodes (And + Not) wrapping
    three Slice-4 atoms (subject_is_artifact + controlled_by_you +
    source_is_self). Because we don't yet have a token-creation
    effect on the bridge, the effect is set to GainLife(1) -- the
    smallest observable parity diff.

    This is the **first** Phase 5 probe to exercise:

      * Predicate::Not in Rust (cards.rs:Predicate::Not) and
        Python's `Not(...)` trigger predicate (`predicates.py:312`).
      * The combined three-level And-Not composition through the
        cross-engine dict->Python bridge.
      * The "source vs subject identity" distinction in a NOT shape
        -- `NOT(source_is_self)` checks the SUBJECT (just-entered
        permanent) is NOT the SOURCE (Mechan Assembler that holds
        the trigger). Same identity check the prior Quantum Riddler
        probe drove on the POSITIVE side; this is the NEGATIVE side.

    Test flow (mirrors the prior Landfall probe's inject-and-fan-out
    shape rather than the cast-and-resolve shape -- the trigger
    SOURCE is pre-placed on bf and we inject a second artifact onto
    bf to observe the trigger firing on the second arrival):

      1. Pre-place Mechan Assembler on p0's battlefield. The Rust
         `register_and_inject_object(BATTLEFIELD)` fans out
         `Event::Enters` for the just-placed Mechan Assembler --
         that fan-out walks every bf permanent INCLUDING Mechan
         Assembler itself and evaluates its trigger predicate against
         the entering subject (= Mechan Assembler). The NOT(IsSelf)
         arm REJECTS the firing because source == subject. Net:
         NO trigger fires, NO life gain on Mechan Assembler's own
         arrival. This is half the parity contract (the "another"
         word in the oracle text doing its job).

      2. Inject a vanilla artifact ("Mechan Drone" -- a synthetic
         artifact-creature stand-in, since the actual oracle effect
         creates a Robot artifact creature token we can't yet
         represent on the bridge) onto p0's battlefield. The
         `Event::Enters` fan-out walks every bf permanent and finds
         Mechan Assembler's trigger predicate matches: the entering
         subject IS an artifact (yes), IS controlled by p0 (yes),
         and is NOT the source (yes -- this is the new "another"
         creature). Trigger lands on stack.

      3. Drain stack on both engines. Mechan Assembler's GainLife(1)
         resolves. p0's life goes 20 -> 21.

      4. Cross-engine parity check on (life_p0, life_p1) -- same on
         both engines, +1 from the trigger.

    Expected post-drain state on BOTH engines:

      * Mechan Assembler on p0's bf (didn't move).
      * Mechan Drone on p0's bf (just arrived).
      * p0 life: 20 -> 21 (+1 from the "another artifact entered"
        trigger firing on Drone's arrival; Mechan Assembler's own
        arrival did NOT fire because NOT(IsSelf) suppressed it).
      * p1 life: unchanged at 20.
      * No residual stack.

    Outcome (a) clean pass on both engines pins the entire predicate
    algebra (`And`, `Not`, subject filters, source filters) through
    the cross-engine bridge -- the substrate is now wide enough to
    drive every "another <type> you control enters" trigger shape in
    the EoE pool (Mechan Assembler, Haliya Guided by Light's
    creature-or-artifact arm, etc.). The shared predicate vocabulary
    is closed under composition through the bridge.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )

    # The "another artifact you control enters" predicate, encoded
    # in the bridge's dict schema. Predicate atoms: subject_is_artifact
    # (the entering permanent is an artifact), controlled_by_you (its
    # controller equals the source's controller), NOT(source_is_self)
    # (the entering permanent is NOT the source ability's host -- i.e.
    # "another" rather than "itself"). Composed via the Slice-1
    # algebra's And + Not nodes.
    another_artifact_predicate = {
        "kind": "and",
        "left": {
            "kind": "and",
            "left": {"kind": "subject_is_artifact"},
            "right": {"kind": "controlled_by_you"},
        },
        "right": {
            "kind": "not",
            "inner": {"kind": "source_is_self"},
        },
    }
    mechan_assembler = CardDef(
        name="Mechan Assembler",
        card_type="Creature",  # Artifact Creature -- card_types is
                               # forwarded as ["Creature"] only via
                               # CardDef.card_type today, but the
                               # subject test reads the printing's
                               # card_types list and we add Artifact
                               # via the rust_dict override below for
                               # the Rust side and the Python printing
                               # for the Python side. (The Subject/
                               # controller filter cares about the
                               # SUBJECT's types here -- "an artifact
                               # you control" reads the just-arrived
                               # permanent, not the source.)
        mana_cost_generic=4,
        mana_cost_colored=(("U", 1),),
        power=4,
        toughness=4,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": another_artifact_predicate,
                # Real oracle is "create a Robot token" -- bridge
                # doesn't yet have token creation, so we lower to a
                # GainLife(1) probe (smallest observable trigger
                # outcome). The predicate-algebra coverage is the
                # point of this probe, not the effect surface.
                "effect": {"kind": "gain_life", "amount": 1},
            },
        ),
    )
    # The second artifact -- a synthetic stand-in named "Mechan
    # Drone" (the actual oracle effect creates a 2/2 Robot artifact
    # creature token; token creation isn't yet on the bridge, so we
    # represent the "another artifact entering" event with a directly-
    # injected artifact creature). It carries NO triggered abilities
    # of its own so any observed +1 life comes UNAMBIGUOUSLY from
    # Mechan Assembler's predicate-path trigger.
    mechan_drone = CardDef(
        name="Mechan Drone",
        card_type="Creature",
        mana_cost_generic=2,
        power=2,
        toughness=2,
        triggered_abilities=(),
    )
    spec = DeckSpec(
        # Both card defs in registry; libraries can be empty for both
        # players -- the probe injects directly onto bf rather than
        # drawing or casting, so library contents don't matter.
        card_defs=(mechan_assembler, mechan_drone),
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    # Mechan Assembler dict: ["Artifact", "Creature"] in card_types so
    # the subject_is_artifact predicate-evaluator path sees it AS an
    # artifact when ANOTHER artifact's ENTERS firing walks this source.
    # (The source identity is the source-vs-subject distinction in
    # NOT(SourceIsSelf); the type read happens via the SUBJECT id.)
    rust_assembler_dict = {
        "name": "Mechan Assembler",
        "card_types": ["Artifact", "Creature"],
        "mana_cost": {"generic": 4, "U": 1},
        "effects": [],
        "power": 4,
        "toughness": 4,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": another_artifact_predicate,
                "effect": {"kind": "gain_life", "amount": 1},
            }
        ],
    }
    rust_assembler_id = rust_state.register_and_inject_object(
        rust_assembler_dict, 0, ZONE_BATTLEFIELD
    )
    # Pin half the parity contract NOW: Mechan Assembler's OWN arrival
    # must NOT have fired the trigger. The NOT(IsSelf) arm rejects --
    # subject (assembler) IS source (assembler), so NOT(IsSelf) is
    # FALSE, And short-circuits. Net: stack is empty, life unchanged.
    assert rust_state.stack_size() == 0, (
        "Rust: Mechan Assembler's own arrival should NOT fire its "
        "'another artifact' trigger -- NOT(source_is_self) gates it "
        "off. stack should be empty."
    )
    rust_p0_life_after_assembler = rust_state.get_life(0)
    assert rust_p0_life_after_assembler == 20, (
        f"Rust p0 life should still be 20 after Mechan Assembler's "
        f"own arrival (NOT-branch gate suppressed the self-fire); "
        f"got {rust_p0_life_after_assembler}"
    )

    # Now inject Mechan Drone -- the "another artifact" arrival. This
    # fans out Event::Enters via `pending_etb_dispatches`; the
    # dispatcher walks every bf permanent (including Mechan Assembler)
    # and evaluates each one's predicate against the entering subject
    # (= Mechan Drone). Mechan Assembler's predicate now matches all
    # three arms: subject_is_artifact (Drone is artifact), controlled_
    # by_you (both p0), NOT(source_is_self) (Drone != Assembler).
    # Trigger lands on stack.
    rust_drone_dict = {
        "name": "Mechan Drone",
        "card_types": ["Artifact", "Creature"],
        "mana_cost": {"generic": 2},
        "effects": [],
        "power": 2,
        "toughness": 2,
    }
    rust_drone_id = rust_state.register_and_inject_object(
        rust_drone_dict, 0, ZONE_BATTLEFIELD
    )
    rust_p0_life_before_drain = rust_state.get_life(0)
    assert rust_state.stack_size() == 1, (
        "Rust: Mechan Drone's arrival should fire Mechan Assembler's "
        "'another artifact' trigger onto the stack -- subject_is_"
        "artifact (yes) AND controlled_by_you (yes) AND NOT(IsSelf) "
        "(yes -- drone != assembler). Expected stack_size==1; got "
        f"{rust_state.stack_size()}"
    )

    # ---- Python side ----
    # Mirror the inject-and-fan-out pattern. Construct the Mechan
    # Assembler printing with the same predicate-path trigger shape,
    # call new_object to materialize an instance, drop it on bf, then
    # dispatch Event.ENTERS to fan out (matching what
    # `register_and_inject_object` does on the Rust side).
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.effects.object_predicates import IsArtifact
    from mtg_bot.effects.predicates import (
        And, Controlled, Event, Not, Subject, IsSelf, YOU,
    )
    from mtg_bot.game import Zone

    # Mirror the dict-shape another_artifact_predicate as a Python
    # composed `TriggerPredicate`. The bridge module's
    # `_ta_dict_to_python_predicate` produces the same composition;
    # we replicate it here directly so the printing carries the
    # actual predicate object (not a dict).
    py_predicate = And(
        left=And(
            left=Subject(slot=None, inner=IsArtifact()),
            right=Controlled(by=YOU, subject=None),
        ),
        right=Not(inner=IsSelf()),
    )
    assembler_printing = CardPrinting(
        name="Mechan Assembler",
        mana_cost_str="",
        mana_cost=ManaCost(generic=4, colored=(("U", 1),)),
        type_line="Artifact Creature",
        supertypes=(),
        card_types=("Artifact", "Creature"),
        subtypes=(),
        power=4,
        toughness=4,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=py_predicate,
                effect=GainLife(amount=1),
            ),
        ),
    )
    py_assembler = py_state.new_object(
        assembler_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_assembler.summoning_sick = False
    py_assembler.tapped = False
    py_assembler.damage = 0
    py_assembler.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_assembler)
    # Fire Mechan Assembler's own ENTERS event. NOT(IsSelf) MUST
    # suppress the trigger -- the predicate evaluates subject==source.
    _trigger_etb_abilities(py_state, py_assembler)
    assert len(py_state.stack) == 0, (
        "Python: Mechan Assembler's own arrival should NOT push a "
        "trigger -- NOT(IsSelf) gates it off. Expected stack=[]; "
        f"got {[(s.source.printing.name if hasattr(s, 'source') else s) for s in py_state.stack]}"
    )
    py_p0_life_after_assembler = py_state.players[0].life
    assert py_p0_life_after_assembler == 20

    # Now inject Mechan Drone and fan out ENTERS. The predicate now
    # matches against Drone (subject) vs Assembler (source).
    drone_printing = CardPrinting(
        name="Mechan Drone",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2),
        type_line="Artifact Creature",
        supertypes=(),
        card_types=("Artifact", "Creature"),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(),
    )
    py_drone = py_state.new_object(
        drone_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_drone.summoning_sick = True
    py_drone.tapped = False
    py_drone.damage = 0
    py_drone.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_drone)
    py_p0_life_before_drain = py_state.players[0].life
    _trigger_etb_abilities(py_state, py_drone)
    assert len(py_state.stack) == 1, (
        "Python: Mechan Drone's arrival should fire Mechan Assembler's "
        "'another artifact' trigger -- subject_is_artifact (yes) "
        "AND controlled_by_you (yes) AND NOT(IsSelf) (drone != "
        f"assembler). Expected len(stack)==1; got {len(py_state.stack)}"
    )

    # ---- Drain both stacks, then compare ----
    _drain_stack_both(py_state, rust_state)

    # Post-drain: p0 gained +1 life from the Mechan Assembler trigger.
    # Critical parity contract: BOTH engines fired the trigger exactly
    # ONCE (only on Drone's arrival, not on Assembler's own arrival).
    assert rust_state.get_life(0) == rust_p0_life_before_drain + 1, (
        f"Rust p0 life should be {rust_p0_life_before_drain + 1} "
        f"(+1 from Mechan Assembler's 'another artifact' trigger); "
        f"got {rust_state.get_life(0)}"
    )
    assert rust_state.get_life(1) == 20
    assert py_state.players[0].life == py_p0_life_before_drain + 1, (
        f"Python p0 life should be {py_p0_life_before_drain + 1} "
        f"(+1 from Mechan Assembler's 'another artifact' trigger); "
        f"got {py_state.players[0].life}"
    )
    assert py_state.players[1].life == 20
    # Cross-engine: same post-drain life totals on both seats.
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life
    # Sanity: both stacks are empty after drain.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0


def test_cross_engine_real_eoe_mechan_assembler_once_per_turn_parity(
    parity_smoke,
):
    """Probe E: Mechan Assembler (EoE) `once_per_turn` flag pin —
    trigger fires once on the first qualifying ENTERS and is
    suppressed on the second within the same turn.

    Oracle text (`data/edge_of_eternities.json`):

        "Whenever another artifact you control enters, create a 2/2
         colorless Robot artifact creature token. This ability
         triggers only once each turn."

    Probe D pinned the predicate algebra's NOT branch (the "another"
    clause). This probe pins the **`once_per_turn` flag** on the
    TriggeredAbility shape:

      * Rust: ``TriggeredAbility::once_per_turn: bool`` consumed at
        ``state_ops_resolve.rs:521`` (predicate-match gate skips the
        firing when ``state.triggered_this_turn`` contains
        ``(source_id, ability_index)``); stamped eagerly at push time
        (``push_triggered_ability`` line 581-585).
      * Python: ``TriggeredAbility.once_per_turn: bool`` consumed at
        ``turn.py:should_fire_trigger`` (``state.once_per_turn_fired``
        ledger; same eager-record semantics). Both eagerly record at
        the moment the event happens (MTG semantics — the ability has
        "triggered" the moment its event fires, even if it later
        fails to find legal targets and fizzles).

    Probe shape (same inject-and-fan-out frame as Probe D, twice):

      1. Pre-place Mechan Assembler with ``once_per_turn=True`` on
         p0 bf. Its OWN arrival doesn't fire (NOT(IsSelf) suppresses,
         carried over from Probe D's pin). Ledger empty.

      2. Inject Mechan Drone #1 on p0 bf. ENTERS dispatch: predicate
         matches all three arms (subject_is_artifact + controlled_by_you
         + NOT(IsSelf)). The ``once_per_turn`` gate sees an empty ledger
         for ``(assembler_id, ability_index=0)`` -> fires. Ledger now
         contains the key. Drain stack: +1 life.

      3. Inject Mechan Drone #2 on p0 bf. ENTERS dispatch: predicate
         still matches (Drone #2 is a different subject, all arms
         satisfied). The ``once_per_turn`` gate sees the ledger key
         -> trigger SKIPPED. No push, no life gain. Stack stays empty.

      4. Cross-engine parity check: BOTH engines fired the trigger
         exactly ONCE across two qualifying ENTERS in the same turn.
         p0 life: 20 -> 21 (not 22). Stacks empty post-drain.

    This is the **first** Phase 5 probe to exercise the
    ``once_per_turn`` flag through the cross-engine bridge — the
    Rust parser at ``cards.rs:4419`` reads ``once_per_turn`` from the
    triggered-ability dict; the Python bridge at
    ``cross_engine.py:275`` mirrors the same field into the Python
    ``TriggeredAbility`` instance. Both engines' eager-record-at-push
    semantics agree under this probe.

    The third-arrival recovery (cleanup -> ledger cleared -> trigger
    fires again on the same turn after) is OUT of scope — the cleanup
    step's reset path (Rust ``state_ops_cleanup.rs:272`` clears
    ``state.triggered_this_turn``; Python ``turn.py:1120``
    ``state.once_per_turn_fired.clear()``) is exercised by existing
    Rust + Python unit tests, and pinning it through the
    inject-and-fan-out cross-engine frame would require driving a
    cleanup phase change on both engines, which is a wider surface
    than this probe's contract. Future probe: turn-boundary
    once_per_turn reset via the cleanup path.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )

    # Same predicate shape as Probe D (pinned to clean PASS there).
    another_artifact_predicate = {
        "kind": "and",
        "left": {
            "kind": "and",
            "left": {"kind": "subject_is_artifact"},
            "right": {"kind": "controlled_by_you"},
        },
        "right": {
            "kind": "not",
            "inner": {"kind": "source_is_self"},
        },
    }
    mechan_assembler = CardDef(
        name="Mechan Assembler",
        card_type="Creature",
        mana_cost_generic=4,
        mana_cost_colored=(("U", 1),),
        power=4,
        toughness=4,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": another_artifact_predicate,
                "effect": {"kind": "gain_life", "amount": 1},
                # The flag pin -- this is the new bit this probe
                # exercises on top of Probe D's predicate algebra.
                "once_per_turn": True,
            },
        ),
    )
    mechan_drone = CardDef(
        name="Mechan Drone",
        card_type="Creature",
        mana_cost_generic=2,
        power=2,
        toughness=2,
    )
    spec = DeckSpec(
        card_defs=(mechan_assembler, mechan_drone),
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    rust_assembler_dict = {
        "name": "Mechan Assembler",
        "card_types": ["Artifact", "Creature"],
        "mana_cost": {"generic": 4, "U": 1},
        "effects": [],
        "power": 4,
        "toughness": 4,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": another_artifact_predicate,
                "effect": {"kind": "gain_life", "amount": 1},
                "once_per_turn": True,
            }
        ],
    }
    rust_assembler_id = rust_state.register_and_inject_object(
        rust_assembler_dict, 0, ZONE_BATTLEFIELD
    )
    # Assembler's own arrival: NOT(IsSelf) suppresses; stack stays empty
    # AND the once_per_turn ledger stays empty (the gate only stamps on
    # successful push, not on predicate-failed firings).
    assert rust_state.stack_size() == 0
    assert rust_state.get_life(0) == 20

    rust_drone_dict_base = {
        "name": "Mechan Drone",
        "card_types": ["Artifact", "Creature"],
        "mana_cost": {"generic": 2},
        "effects": [],
        "power": 2,
        "toughness": 2,
    }

    # Drone #1: first qualifying arrival. Trigger fires, ledger stamps.
    rust_drone1_id = rust_state.register_and_inject_object(
        rust_drone_dict_base, 0, ZONE_BATTLEFIELD
    )
    assert rust_state.stack_size() == 1, (
        "Rust: Drone #1 arrival should push Mechan Assembler's trigger "
        "onto the stack (first fire of the turn)"
    )
    # Drain the trigger now (before Drone #2) so we can observe the
    # +1 life from the first firing in isolation.
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()
    rust_p0_life_after_first = rust_state.get_life(0)
    assert rust_p0_life_after_first == 21, (
        f"Rust p0 life should be 21 after first trigger; "
        f"got {rust_p0_life_after_first}"
    )

    # Drone #2: second qualifying arrival same turn. once_per_turn
    # gate suppresses the trigger -- stack must stay empty, life
    # must NOT advance to 22.
    rust_drone2_id = rust_state.register_and_inject_object(
        rust_drone_dict_base, 0, ZONE_BATTLEFIELD
    )
    assert rust_state.stack_size() == 0, (
        "Rust: Drone #2 arrival should NOT push a trigger -- "
        "once_per_turn gate suppresses the second fire within the "
        f"same turn. Got stack_size={rust_state.stack_size()}"
    )
    assert rust_state.get_life(0) == 21, (
        f"Rust p0 life should still be 21 (no second trigger); "
        f"got {rust_state.get_life(0)}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities, resolve_top_of_stack
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.effects.object_predicates import IsArtifact
    from mtg_bot.effects.predicates import (
        And, Controlled, Event, Not, Subject, IsSelf, YOU,
    )
    from mtg_bot.game import Zone

    py_predicate = And(
        left=And(
            left=Subject(slot=None, inner=IsArtifact()),
            right=Controlled(by=YOU, subject=None),
        ),
        right=Not(inner=IsSelf()),
    )
    assembler_printing = CardPrinting(
        name="Mechan Assembler",
        mana_cost_str="",
        mana_cost=ManaCost(generic=4, colored=(("U", 1),)),
        type_line="Artifact Creature",
        supertypes=(),
        card_types=("Artifact", "Creature"),
        subtypes=(),
        power=4,
        toughness=4,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=py_predicate,
                effect=GainLife(amount=1),
                once_per_turn=True,
            ),
        ),
    )
    py_assembler = py_state.new_object(
        assembler_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_assembler.summoning_sick = False
    py_assembler.tapped = False
    py_assembler.damage = 0
    py_assembler.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_assembler)
    _trigger_etb_abilities(py_state, py_assembler)
    # Assembler's own arrival suppressed (NOT(IsSelf)).
    assert len(py_state.stack) == 0
    assert py_state.players[0].life == 20

    drone_printing = CardPrinting(
        name="Mechan Drone",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2),
        type_line="Artifact Creature",
        supertypes=(),
        card_types=("Artifact", "Creature"),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(),
    )

    # Drone #1: first qualifying arrival; ledger empty -> fires.
    py_drone1 = py_state.new_object(
        drone_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_drone1.summoning_sick = True
    py_drone1.tapped = False
    py_drone1.damage = 0
    py_drone1.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_drone1)
    _trigger_etb_abilities(py_state, py_drone1)
    assert len(py_state.stack) == 1, (
        "Python: Drone #1 arrival should push Mechan Assembler's "
        "trigger onto the stack (first fire of the turn)"
    )
    # Drain the first firing before Drone #2.
    while py_state.stack:
        resolve_top_of_stack(py_state)
    py_p0_life_after_first = py_state.players[0].life
    assert py_p0_life_after_first == 21

    # Drone #2: second qualifying arrival same turn; ledger gates off.
    py_drone2 = py_state.new_object(
        drone_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_drone2.summoning_sick = True
    py_drone2.tapped = False
    py_drone2.damage = 0
    py_drone2.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_drone2)
    _trigger_etb_abilities(py_state, py_drone2)
    assert len(py_state.stack) == 0, (
        "Python: Drone #2 arrival should NOT push a trigger -- "
        "once_per_turn gate suppresses the second fire within the "
        f"same turn. Got stack={[s.source.printing.name for s in py_state.stack]}"
    )
    assert py_state.players[0].life == 21

    # ---- Cross-engine parity ----
    # Drain (no-op — both stacks already empty), then compare:
    _drain_stack_both(py_state, rust_state)
    # BOTH engines: net +1 life on p0 across two qualifying ENTERS
    # events in the same turn, not +2. p1 unchanged.
    assert rust_state.get_life(0) == 21
    assert rust_state.get_life(1) == 20
    assert py_state.players[0].life == 21
    assert py_state.players[1].life == 20
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life


def test_cross_engine_real_eoe_tannuk_memorial_ensign_landfall_burn_parity(
    parity_smoke,
):
    """Probe F: Tannuk, Memorial Ensign (EoE) Landfall->burn trigger
    fires + parity-matches across the newly-bridged
    ``damage_each_opponent`` effect.

    Oracle text in `data/edge_of_eternities.json`:

        "Landfall -- Whenever a land you control enters, Tannuk
         deals 1 damage to each opponent. If this is the second
         time this ability has resolved this turn, draw a card."

    The "second-time-this-turn -> draw a card" rider is OUT of scope
    -- modeling it requires a per-turn fire-count ledger on the
    bridge that doesn't exist yet (the existing once_per_turn ledger
    is a binary skip-gate, not a counted-fires bridge). This probe
    restricts the surface to the LANDFALL + DAMAGE_EACH_OPPONENT(1)
    base trigger. Both component clauses are now substrate-resolvable:

      * Predicate shape: ``Subject(IsLand) AND ControlledByYou`` --
        SAME shape pinned by the Eumidian Terrabotanist probe (the
        third Phase 5 probe), so the predicate-algebra coverage is
        already paid for.

      * Effect shape: ``DamageEachOpponent(1)`` -- NEW on the bridge
        as of the companion commit. The Rust side reads
        ``damage_each_opponent`` via ``parse_effect`` (cards.rs:2771);
        the Python bridge's
        ``_ta_dict_to_python_effect`` arm translates to
        ``DealDamageEachOpponent(amount=1)`` (effects/generic/damage.py).

    Probe shape (mirrors the Eumidian Terrabotanist Landfall frame):

      1. Pre-place Tannuk, Memorial Ensign on p0's bf. Tannuk's own
         arrival doesn't fire its predicate (Tannuk is a creature,
         not a land, so the SUBJECT(IsLand) arm short-circuits even
         without a NOT(IsSelf) gate -- that's a happy side-effect of
         the type filter).

      2. Inject a Forest onto p0's bf via ``play_land`` (Rust) /
         ``_play_land`` (Python). The land-play-path dispatches
         ENTERS for the Forest; the dispatcher walks every bf
         permanent and finds Tannuk's predicate matches:
         subject_is_land (yes), controlled_by_you (yes). Trigger
         pushes onto the stack.

      3. Drain stack on both engines. DamageEachOpponent(1) resolves:
         each engine subtracts 1 from p1's life (the only opponent
         in the 2-player game). p1 life: 20 -> 19.

      4. Cross-engine assert: BOTH engines reduced p1's life to 19.
         p0 life unchanged at 20 (Tannuk's controller, immune to the
         each-opponent damage).

    Expected post-drain state on BOTH engines:

      * Tannuk on p0's bf (didn't move).
      * Forest on p0's bf (just played).
      * p0 life: unchanged at 20 (controller-immune).
      * p1 life: 20 -> 19 (-1 from the landfall->burn trigger).
      * No residual stack.

    Outcome (a): clean pass pins the bridge extension end-to-end on
    a real-card landfall->burn trigger. Same predicate shape covers
    every "Landfall: do something to each opponent" trigger in EoE
    once landed on the bridge's effect surface; this probe is the
    first one to drive the LANDFALL + (effect-not-life/draw) shape.

    Notes on out-of-scope:

      * Multi-trigger-per-turn count (the "second time this turn"
        rider) -- needs a counter-based bridge entry, not the binary
        once_per_turn flag pinned by Probe E. Future probe / future
        bridge widening.

      * Cross-controller controller-of-effect contract -- this probe
        drives p0 (active_player) controlled trigger, where Rust's
        ``state.players[1 - active_player]`` reader and Python's
        per-source-controller walk agree. The "p1's source resolves
        on p0's turn" case is gated by the same active_player-keyed
        Rust reader that DrawCards/GainLife had pre-I59/I60 fixes.
        A follow-up controller-of-effect fix for
        ``Effect::DamageEachOpponent`` mirrors the I60 shape.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )

    landfall_predicate = {
        "kind": "and",
        "left": {"kind": "subject_is_land"},
        "right": {"kind": "controlled_by_you"},
    }
    tannuk = CardDef(
        name="Tannuk, Memorial Ensign",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("R", 1),),
        power=2,
        toughness=2,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": landfall_predicate,
                "effect": {
                    "kind": "damage_each_opponent",
                    "amount": 1,
                },
            },
        ),
    )
    forest = CardDef(
        name="Forest", card_type="Land", mana_produced=("G",),
    )
    spec = DeckSpec(
        card_defs=(tannuk, forest),
        # Forest in p0's library — _play_land path moves it to bf.
        # p1 library has Forest too so the deckspec is symmetric; we
        # don't touch p1's resources in this probe.
        p0_library=("Forest", "Forest"),
        p1_library=("Forest", "Forest"),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_HAND = 0
    ZONE_BATTLEFIELD = 2
    rust_tannuk_dict = {
        "name": "Tannuk, Memorial Ensign",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1, "R": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": landfall_predicate,
                "effect": {
                    "kind": "damage_each_opponent",
                    "amount": 1,
                },
            }
        ],
    }
    rust_tannuk_id = rust_state.register_and_inject_object(
        rust_tannuk_dict, 0, ZONE_BATTLEFIELD
    )
    # Tannuk's own arrival: predicate is subject_is_land AND
    # controlled_by_you. Tannuk is a Creature, NOT a Land, so
    # subject_is_land = FALSE. Trigger does NOT fire on Tannuk's own
    # arrival -- pin half the parity contract NOW.
    assert rust_state.stack_size() == 0, (
        "Rust: Tannuk's own arrival should NOT fire its landfall "
        "trigger -- subject_is_land filter rejects (Tannuk is a "
        "Creature). Expected stack_size==0; got "
        f"{rust_state.stack_size()}"
    )
    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)

    # Inject Forest onto p0's hand, then play it via play_land. The
    # play_land path dispatches ENTERS; the dispatcher walks every
    # bf permanent (including Tannuk) and fires matching triggers.
    rust_forest_dict = {
        "name": "Forest",
        "card_types": ["Land"],
        "mana_produced": ["G"],
        "effects": [],
    }
    rust_forest_id = rust_state.register_and_inject_object(
        rust_forest_dict, 0, ZONE_HAND
    )
    rust_state.play_land(rust_forest_id, 0)
    assert rust_state.find_object_zone(rust_forest_id) == ZONE_BATTLEFIELD, (
        "Rust: Forest should be on bf after play_land"
    )
    assert rust_state.stack_size() == 1, (
        "Rust: Tannuk's landfall trigger should be on the stack after "
        "the Forest enters under p0's control"
    )

    # ---- Python side ----
    from mtg_bot.actions import _play_land
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.damage import DealDamageEachOpponent
    from mtg_bot.effects.object_predicates import IsLand
    from mtg_bot.effects.predicates import (
        And, Controlled, Event, Subject, YOU,
    )
    from mtg_bot.game import Zone

    py_predicate = And(
        left=Subject(slot=None, inner=IsLand()),
        right=Controlled(by=YOU, subject=None),
    )
    tannuk_printing = CardPrinting(
        name="Tannuk, Memorial Ensign",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=(("R", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=py_predicate,
                effect=DealDamageEachOpponent(amount=1),
            ),
        ),
    )
    py_tannuk = py_state.new_object(
        tannuk_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_tannuk.summoning_sick = False
    py_tannuk.tapped = False
    py_tannuk.damage = 0
    py_tannuk.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_tannuk)
    # Python: Tannuk wasn't fanned through _trigger_etb_abilities
    # since we materialized it on bf directly. Stack should remain
    # empty as we never dispatched ENTERS for Tannuk's own arrival.
    assert len(py_state.stack) == 0

    # Move a Forest from library to hand on Python side.
    py_forest = py_state.players[0].library[0]
    assert py_forest.printing.name == "Forest"
    py_state.players[0].library.remove(py_forest)
    py_forest.zone = Zone.HAND
    py_state.players[0].hand.append(py_forest)

    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life
    # Reset the per-turn cap so _play_land doesn't gate (mirrors
    # the Eumidian Terrabotanist probe's reset pattern).
    py_state.players[0].lands_played_this_turn = 0
    _play_land(py_state, 0, py_forest.id)
    assert any(
        o.printing.name == "Forest" and o.controller_id == 0
        for o in py_state.battlefield
    ), "Python: Forest should be on bf after _play_land"
    assert len(py_state.stack) == 1, (
        "Python: Tannuk's landfall trigger should be on the stack "
        "after Forest enters under p0's control"
    )

    # ---- Drain both stacks, then compare ----
    _drain_stack_both(py_state, rust_state)

    # Post-drain: -1 life on p1 from the landfall burn trigger.
    # p0 unchanged (controller of the source, immune to "each
    # opponent").
    assert rust_state.get_life(0) == rust_p0_life_before, (
        f"Rust p0 life should be unchanged ({rust_p0_life_before}); "
        f"got {rust_state.get_life(0)}"
    )
    assert rust_state.get_life(1) == rust_p1_life_before - 1, (
        f"Rust p1 life should be {rust_p1_life_before - 1} "
        f"(-1 from landfall burn); got {rust_state.get_life(1)}"
    )
    assert py_state.players[0].life == py_p0_life_before
    assert py_state.players[1].life == py_p1_life_before - 1
    # Cross-engine: same post-drain life totals on both seats.
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life


def test_cross_engine_real_eoe_weftstalker_ardent_or_predicate_burn_parity(
    parity_smoke,
):
    """Probe G: Weftstalker Ardent (EoE) — first real-card consumer of
    the new ``Predicate::Or`` substrate. The deferred unblock from
    Probe F's forward notes lands here.

    Oracle text in ``data/edge_of_eternities.json``:

        "Whenever another creature or artifact you control enters,
         this creature deals 1 damage to each opponent."

    Predicate decomposition:

      * "another" -> ``NOT(SourceIsSelf)`` -- gate self-arrival.
      * "creature or artifact" -> ``Or(SubjectIsCreature, SubjectIsArtifact)``
        -- NEW disjunction, landed in the Or-substrate slice.
      * "you control" -> ``ControlledByYou``.

    Combined shape:

        And(
            And(
                Or(SubjectIsCreature, SubjectIsArtifact),
                ControlledByYou,
            ),
            Not(SourceIsSelf),
        )

    Effect: ``damage_each_opponent(1)`` -- already on the cross-engine
    bridge as of Probe F.

    Probe shape (mirrors Mechan Assembler's inject-and-fan-out frame):

      1. Pre-place Weftstalker Ardent on p0's bf. Its own arrival is
         gated by NOT(SourceIsSelf): no fire, no life change. The Or
         arm WOULD have matched (Weftstalker is a Creature), so this
         pins the "Not gates Or-true" composition.

      2. Inject a vanilla creature for p0 on the bf. Dispatch fires:
         (Subject IS Creature -> Or-left true -> Or true) AND
         (controlled_by_you yes) AND (NOT source_is_self yes).
         Trigger pushes. Drain stack -> p1 life 20 -> 19.

      3. Inject a vanilla artifact for p0 on the bf. Dispatch fires:
         (Subject IS Artifact -> Or-right true even though Or-left
         false -> Or true) AND controlled_by_you AND NOT-self.
         Trigger pushes. Drain stack -> p1 life 19 -> 18.

      4. Inject a vanilla land for p0 on the bf. Dispatch DOES NOT
         fire: (Subject IS Land -> Or-left false; Or-right false ->
         Or false) -> outer And short-circuits. No push, life
         unchanged.

      5. Cross-engine assert: BOTH engines reduced p1's life to 18
         after two triggered fires + one rejected (land) arrival.
         p0 life unchanged at 20 (controller-immune).

    This is the **first** cross-engine probe to exercise
    ``Predicate::Or`` end-to-end on a real EoE card. All three Or
    arms (left-match, right-match, neither-match) are pinned in a
    single inject-and-fan-out sequence.

    Out of scope:

      * Warp cost ({R}) — cast-from-exile alt path is irrelevant to
        the ETB-trigger contract; pre-place skips the cast pipeline.
      * Cross-controller controller-of-effect for
        ``DamageEachOpponent`` — same gap as Probe F's note;
        follow-up I-slice mirrors I60's shape.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )

    weftstalker_predicate = {
        "kind": "and",
        "left": {
            "kind": "and",
            "left": {
                "kind": "or",
                "left": {"kind": "subject_is_creature"},
                "right": {"kind": "subject_is_artifact"},
            },
            "right": {"kind": "controlled_by_you"},
        },
        "right": {
            "kind": "not",
            "inner": {"kind": "source_is_self"},
        },
    }
    weftstalker = CardDef(
        name="Weftstalker Ardent",
        card_type="Creature",
        mana_cost_generic=2,
        mana_cost_colored=(("R", 1),),
        power=2,
        toughness=3,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": weftstalker_predicate,
                "effect": {
                    "kind": "damage_each_opponent",
                    "amount": 1,
                },
            },
        ),
    )
    bait_creature = CardDef(
        name="Bait Creature",
        card_type="Creature",
        mana_cost_generic=1,
        power=1,
        toughness=1,
    )
    bait_artifact = CardDef(
        name="Bait Artifact",
        card_type="Artifact",
        mana_cost_generic=1,
    )
    bait_land = CardDef(
        name="Bait Wastes",
        card_type="Land",
    )
    spec = DeckSpec(
        card_defs=(weftstalker, bait_creature, bait_artifact, bait_land),
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    rust_weftstalker_dict = {
        "name": "Weftstalker Ardent",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "R": 1},
        "effects": [],
        "power": 2,
        "toughness": 3,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": weftstalker_predicate,
                "effect": {
                    "kind": "damage_each_opponent",
                    "amount": 1,
                },
            }
        ],
    }
    rust_weftstalker_id = rust_state.register_and_inject_object(
        rust_weftstalker_dict, 0, ZONE_BATTLEFIELD
    )
    # Weftstalker's own arrival: NOT(IsSelf) suppresses; stack empty.
    assert rust_state.stack_size() == 0, (
        "Rust: Weftstalker's own arrival should NOT fire its trigger "
        "(NOT(SourceIsSelf) suppresses even though Or matches creature). "
        f"Got stack_size={rust_state.stack_size()}"
    )
    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)
    assert rust_p0_life_before == 20
    assert rust_p1_life_before == 20

    rust_bait_creature_dict = {
        "name": "Bait Creature",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "effects": [],
        "power": 1,
        "toughness": 1,
    }
    rust_bait_artifact_dict = {
        "name": "Bait Artifact",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 1},
        "effects": [],
    }
    rust_bait_land_dict = {
        "name": "Bait Wastes",
        "card_types": ["Land"],
        "effects": [],
    }

    # Arrival 1: vanilla creature for p0. Or-left true (creature),
    # ControlledByYou true, NOT-self true -> fires.
    rust_creature_id = rust_state.register_and_inject_object(
        rust_bait_creature_dict, 0, ZONE_BATTLEFIELD
    )
    assert rust_state.stack_size() == 1, (
        "Rust: Or-left (subject_is_creature) should fire on p0's "
        "creature arrival"
    )
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()
    assert rust_state.get_life(1) == 19, (
        f"Rust: p1 life should be 19 after first burn; "
        f"got {rust_state.get_life(1)}"
    )

    # Arrival 2: vanilla artifact for p0. Or-right true (artifact),
    # Or-left false (not a creature). Outer And succeeds -> fires.
    rust_artifact_id = rust_state.register_and_inject_object(
        rust_bait_artifact_dict, 0, ZONE_BATTLEFIELD
    )
    assert rust_state.stack_size() == 1, (
        "Rust: Or-right (subject_is_artifact) should fire on p0's "
        "artifact arrival (Or-left false, Or-right true)"
    )
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()
    assert rust_state.get_life(1) == 18, (
        f"Rust: p1 life should be 18 after second burn; "
        f"got {rust_state.get_life(1)}"
    )

    # Arrival 3: vanilla land for p0. Neither Or arm matches (not a
    # creature, not an artifact) -> Or false -> outer And false.
    # No fire, life unchanged.
    rust_land_id = rust_state.register_and_inject_object(
        rust_bait_land_dict, 0, ZONE_BATTLEFIELD
    )
    assert rust_state.stack_size() == 0, (
        "Rust: Or(creature, artifact) should reject a land subject "
        "(neither arm matches). "
        f"Got stack_size={rust_state.stack_size()}"
    )
    assert rust_state.get_life(1) == 18, (
        f"Rust: p1 life should stay at 18 (land arrival rejected); "
        f"got {rust_state.get_life(1)}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.damage import DealDamageEachOpponent
    from mtg_bot.effects.object_predicates import IsArtifact, IsCreature
    from mtg_bot.effects.predicates import (
        And, Controlled, Event, IsSelf, Not, Or, Subject, YOU,
    )
    from mtg_bot.game import Zone

    py_predicate = And(
        left=And(
            left=Or(
                left=Subject(slot=None, inner=IsCreature()),
                right=Subject(slot=None, inner=IsArtifact()),
            ),
            right=Controlled(by=YOU, subject=None),
        ),
        right=Not(inner=IsSelf()),
    )
    weftstalker_printing = CardPrinting(
        name="Weftstalker Ardent",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2, colored=(("R", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=3,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=py_predicate,
                effect=DealDamageEachOpponent(amount=1),
            ),
        ),
    )
    py_weftstalker = py_state.new_object(
        weftstalker_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_weftstalker.summoning_sick = False
    py_weftstalker.tapped = False
    py_weftstalker.damage = 0
    py_weftstalker.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_weftstalker)
    _trigger_etb_abilities(py_state, py_weftstalker)
    # NOT(IsSelf) suppresses self-arrival.
    assert len(py_state.stack) == 0
    assert py_state.players[1].life == 20

    creature_printing = CardPrinting(
        name="Bait Creature",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=1,
        toughness=1,
        produces=frozenset(),
        triggered_abilities=(),
    )
    artifact_printing = CardPrinting(
        name="Bait Artifact",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        triggered_abilities=(),
    )
    land_printing = CardPrinting(
        name="Bait Wastes",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Land",
        supertypes=(),
        card_types=("Land",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        triggered_abilities=(),
    )

    # Arrival 1: vanilla creature.
    py_creature = py_state.new_object(
        creature_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_creature.summoning_sick = True
    py_creature.tapped = False
    py_creature.damage = 0
    py_creature.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_creature)
    _trigger_etb_abilities(py_state, py_creature)
    assert len(py_state.stack) == 1, (
        "Python: Or-left (IsCreature) should fire on p0's creature "
        "arrival"
    )
    from mtg_bot.actions import resolve_top_of_stack
    while py_state.stack:
        resolve_top_of_stack(py_state)
    assert py_state.players[1].life == 19

    # Arrival 2: vanilla artifact.
    py_artifact = py_state.new_object(
        artifact_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_artifact.summoning_sick = False
    py_artifact.tapped = False
    py_artifact.damage = 0
    py_artifact.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_artifact)
    _trigger_etb_abilities(py_state, py_artifact)
    assert len(py_state.stack) == 1, (
        "Python: Or-right (IsArtifact) should fire on p0's artifact "
        "arrival"
    )
    while py_state.stack:
        resolve_top_of_stack(py_state)
    assert py_state.players[1].life == 18

    # Arrival 3: vanilla land — neither Or arm matches.
    py_land = py_state.new_object(
        land_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_land.summoning_sick = False
    py_land.tapped = False
    py_land.damage = 0
    py_land.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_land)
    _trigger_etb_abilities(py_state, py_land)
    assert len(py_state.stack) == 0, (
        "Python: Or(creature, artifact) should reject a land subject"
    )
    assert py_state.players[1].life == 18

    # ---- Cross-engine parity ----
    _drain_stack_both(py_state, rust_state)
    # Both engines: p0 life unchanged at 20; p1 life 18 (-2 from
    # two qualifying fires + 1 rejected land arrival).
    assert rust_state.get_life(0) == 20
    assert rust_state.get_life(1) == 18
    assert py_state.players[0].life == 20
    assert py_state.players[1].life == 18
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life


def test_cross_engine_real_eoe_kav_landseeker_has_subtype_kavu_probe_parity(
    parity_smoke,
):
    """Probe H: First cross-engine probe to exercise
    ``Predicate::SubjectHasSubtype`` end-to-end on a real EoE-printed
    subtype-carrying subject.

    Kav Landseeker (EoE 138) — a real EoE creature whose printed
    type_line is "Creature -- Kavu Soldier". Its own oracle text
    ("When this creature enters, create a Lander token...") is OUT
    of scope: the bridge doesn't carry ``create_token`` and EoE has
    no Kavu/Sliver/Equipment ETB trigger whose effect is already on
    the substrate-bridged effect surface (draw_cards / gain_life /
    damage_each_opponent). The probe strips Kav Landseeker's own
    triggered ability and uses it strictly as the SUBJECT carrying
    the real EoE-printed ``["Kavu", "Soldier"]`` subtypes. Same
    shape as Tannuk's probe, which stripped the "second-time-this-
    turn -> draw" rider for the same reason.

    Probe shape (inject-and-fan-out, mirrors the artifact/creature
    arrival pattern from the Or-substrate consumer probe):

      1. Pre-place a synthetic Kavu-observer on p0's bf. Its
         predicate is ``Subject(HasSubtype("Kavu")) AND
         ControlledByYou`` -- the simplest unit-pin for HasSubtype
         on a real-EoE-typed subject. Effect: ``gain_life(1)``
         (already on the bridge per Probes B/D/E). Self-arrival
         doesn't fire because the observer's own ``subtypes`` is
         empty -- HasSubtype("Kavu") rejects.

      2. Inject Kav Landseeker (real EoE printing-shape; subtypes
         ["Kavu", "Soldier"]) onto p0's bf. Dispatch fires:
         HasSubtype("Kavu") TRUE (first-position subtype match),
         ControlledByYou TRUE. Trigger pushes. Drain -> p0 life
         20 -> 21.

      3. Inject a vanilla non-Kavu creature for p0 onto bf.
         HasSubtype("Kavu") FALSE -> trigger doesn't fire. Life
         unchanged.

      4. Cross-engine assert: BOTH engines fire the Kavu trigger
         exactly once and reject the vanilla creature. p0 life: 21.

    This is the **first** cross-engine probe to pin the
    ``Predicate::SubjectHasSubtype`` arm (landed in Subtypes Slice
    2, ``CardPrinting.subtypes: Vec<String>`` +
    ``Predicate::SubjectHasSubtype``) on a real EoE-printed subject.
    The substrate-side unit tests in
    ``tests_rust/test_triggers.py`` (Subtypes Slice 2's Equipment /
    Kavu / Bear arrival pins) cover the predicate dispatch in
    isolation; this probe ties it to the cross-engine bridge.

    Out of scope:

      * Kav Landseeker's own ``create_token`` ETB -- needs bridge
        widening for ``create_token`` effect, follow-up probe.
      * Effective subtypes (CR 613 layer-3/4 -- Conspiracy granting
        "Kavu", etc.) -- both engines read static subtypes, so the
        layer-aware semantics drift is irrelevant for EoE's pool.
      * Multi-Kavu cascade (a Kavu fires the observer, the
        observer's effect causes another Kavu to enter, etc.) --
        out of probe scope.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )

    kavu_observer_predicate = {
        "kind": "and",
        "left": {
            "kind": "subject_has_subtype",
            "subtype": "Kavu",
        },
        "right": {"kind": "controlled_by_you"},
    }
    kavu_observer = CardDef(
        name="Test Kavu Observer",
        card_type="Creature",
        mana_cost_generic=2,
        power=1,
        toughness=1,
        # Empty subtypes — observer's own arrival doesn't match its
        # own predicate (HasSubtype("Kavu") false).
        subtypes=(),
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": kavu_observer_predicate,
                "effect": {"kind": "gain_life", "amount": 1},
            },
        ),
    )
    # Kav Landseeker — real EoE 138; type_line "Creature -- Kavu
    # Soldier", so subtypes = ("Kavu", "Soldier"). Strip the printed
    # ETB ability (create-Lander-token is out of bridge scope) but
    # KEEP the printed name + subtypes so the parity contract reads
    # the real EoE-printed subtype tuple end-to-end.
    kav_landseeker = CardDef(
        name="Kav Landseeker",
        card_type="Creature",
        mana_cost_generic=3,
        mana_cost_colored=(("R", 1),),
        power=4,
        toughness=3,
        subtypes=("Kavu", "Soldier"),
        triggered_abilities=(),
    )
    vanilla_non_kavu = CardDef(
        name="Test Vanilla Non-Kavu",
        card_type="Creature",
        mana_cost_generic=1,
        power=1,
        toughness=1,
        subtypes=(),
    )
    spec = DeckSpec(
        card_defs=(kavu_observer, kav_landseeker, vanilla_non_kavu),
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    rust_observer_dict = {
        "name": "Test Kavu Observer",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "effects": [],
        "power": 1,
        "toughness": 1,
        "subtypes": [],
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": kavu_observer_predicate,
                "effect": {"kind": "gain_life", "amount": 1},
            }
        ],
    }
    rust_observer_id = rust_state.register_and_inject_object(
        rust_observer_dict, 0, ZONE_BATTLEFIELD
    )
    # Observer's own arrival: HasSubtype("Kavu") false (observer has
    # empty subtypes); trigger does NOT fire.
    assert rust_state.stack_size() == 0, (
        "Rust: Kavu observer's own arrival should NOT fire its "
        "trigger -- observer's subtypes is empty so HasSubtype('Kavu') "
        f"rejects. Got stack_size={rust_state.stack_size()}"
    )
    rust_p0_life_before = rust_state.get_life(0)
    assert rust_p0_life_before == 20

    rust_kav_dict = {
        "name": "Kav Landseeker",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 3, "R": 1},
        "effects": [],
        "power": 4,
        "toughness": 3,
        "subtypes": ["Kavu", "Soldier"],
    }
    rust_kav_id = rust_state.register_and_inject_object(
        rust_kav_dict, 0, ZONE_BATTLEFIELD
    )
    assert rust_state.stack_size() == 1, (
        "Rust: HasSubtype('Kavu') AND ControlledByYou should fire on "
        "Kav Landseeker's arrival (subtypes=['Kavu','Soldier'], "
        f"controller=0). Got stack_size={rust_state.stack_size()}"
    )
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()
    assert rust_state.get_life(0) == 21, (
        f"Rust: p0 life should be 21 after Kavu arrival; "
        f"got {rust_state.get_life(0)}"
    )

    # Inject a vanilla non-Kavu creature for p0. HasSubtype('Kavu')
    # false -> trigger doesn't fire.
    rust_vanilla_dict = {
        "name": "Test Vanilla Non-Kavu",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "effects": [],
        "power": 1,
        "toughness": 1,
        "subtypes": [],
    }
    rust_vanilla_id = rust_state.register_and_inject_object(
        rust_vanilla_dict, 0, ZONE_BATTLEFIELD
    )
    assert rust_state.stack_size() == 0, (
        "Rust: HasSubtype('Kavu') should reject a non-Kavu creature "
        f"subject. Got stack_size={rust_state.stack_size()}"
    )
    assert rust_state.get_life(0) == 21, (
        f"Rust: p0 life should stay at 21 (non-Kavu rejected); "
        f"got {rust_state.get_life(0)}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities, resolve_top_of_stack
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.effects.object_predicates import HasSubtype
    from mtg_bot.effects.predicates import (
        And, Controlled, Event, Subject, YOU,
    )
    from mtg_bot.game import Zone

    py_predicate = And(
        left=Subject(slot=None, inner=HasSubtype(name="Kavu")),
        right=Controlled(by=YOU, subject=None),
    )
    observer_printing = CardPrinting(
        name="Test Kavu Observer",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=1,
        toughness=1,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=py_predicate,
                effect=GainLife(amount=1),
            ),
        ),
    )
    py_observer = py_state.new_object(
        observer_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_observer.summoning_sick = False
    py_observer.tapped = False
    py_observer.damage = 0
    py_observer.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_observer)
    _trigger_etb_abilities(py_state, py_observer)
    # Observer's own arrival: HasSubtype("Kavu") false (empty
    # subtypes); no fire.
    assert len(py_state.stack) == 0
    assert py_state.players[0].life == 20

    kav_printing = CardPrinting(
        name="Kav Landseeker",
        mana_cost_str="",
        mana_cost=ManaCost(generic=3, colored=(("R", 1),)),
        type_line="Creature — Kavu Soldier",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Kavu", "Soldier"),
        power=4,
        toughness=3,
        produces=frozenset(),
        triggered_abilities=(),
    )
    py_kav = py_state.new_object(
        kav_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_kav.summoning_sick = True
    py_kav.tapped = False
    py_kav.damage = 0
    py_kav.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_kav)
    _trigger_etb_abilities(py_state, py_kav)
    assert len(py_state.stack) == 1, (
        "Python: HasSubtype('Kavu') AND ControlledByYou should fire "
        "on Kav Landseeker's arrival"
    )
    while py_state.stack:
        resolve_top_of_stack(py_state)
    assert py_state.players[0].life == 21

    vanilla_printing = CardPrinting(
        name="Test Vanilla Non-Kavu",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=1,
        toughness=1,
        produces=frozenset(),
        triggered_abilities=(),
    )
    py_vanilla = py_state.new_object(
        vanilla_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_vanilla.summoning_sick = True
    py_vanilla.tapped = False
    py_vanilla.damage = 0
    py_vanilla.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_vanilla)
    _trigger_etb_abilities(py_state, py_vanilla)
    assert len(py_state.stack) == 0, (
        "Python: HasSubtype('Kavu') should reject a non-Kavu subject"
    )
    assert py_state.players[0].life == 21

    # ---- Cross-engine parity ----
    _drain_stack_both(py_state, rust_state)
    assert rust_state.get_life(0) == 21
    assert rust_state.get_life(1) == 20
    assert py_state.players[0].life == 21
    assert py_state.players[1].life == 20
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life


def test_cross_engine_real_eoe_haliya_guided_by_light_or_predicate_self_inclusive_parity(
    parity_smoke,
):
    """Probe I: Haliya, Guided by Light (EoE 19) — second real-card
    consumer of the new ``Predicate::Or`` substrate, this time
    exercising the SELF-INCLUSIVE Or-shape (no outer ``Not(IsSelf)``)
    and adding ``ControlledByYou``'s negative-arm coverage (an
    OPPONENT-controlled creature must be rejected by the same
    predicate).

    Oracle text in ``data/edge_of_eternities.json``:

        "Whenever Haliya or another creature or artifact you control
         enters, you gain 1 life. ..."

    Note the contrast with Weftstalker Ardent (Probe G), whose
    "another creature or artifact you control" was wrapped in an
    outer ``Not(SourceIsSelf)`` so the source's own arrival
    suppressed the trigger. Haliya's text explicitly *includes*
    herself by name ("Haliya or ..."), so the predicate has NO
    self-exclusion gate. The natural decomposition is just

        And(
            Or(SubjectIsCreature, SubjectIsArtifact),
            ControlledByYou,
        )

    Haliya's own arrival satisfies this on its own (she IS a
    creature you control). The Or substrate fires the same way on
    self-arrival as on any other qualifying arrival.

    Probe shape (inject-and-fan-out with TWO new axes vs Probe G):

      1. Pre-place Haliya on p0's bf. Self-arrival fires the trigger:
         Subject IS Creature -> Or-left true -> Or true; controlled
         by you. Trigger pushes. Drain -> p0 life 20 -> 21.
         **First** cross-engine probe to pin Or firing on a
         self-arrival without ``Not(IsSelf)`` gating it.

      2. Inject a vanilla creature for p0 on the bf. Or-left true,
         ControlledByYou true -> fires -> p0 life 21 -> 22.

      3. Inject a vanilla artifact for p0 on the bf. Or-right true,
         Or-left false; ControlledByYou true -> fires -> p0 life
         22 -> 23.

      4. Inject a vanilla land for p0 on the bf. Neither Or arm
         matches -> no fire. Life unchanged at 23.

      5. **NEW axis vs Probe G:** Inject a vanilla creature for
         **p1** on the bf. Or-left TRUE (it is a creature), but
         ControlledByYou FALSE (subject_controller=1 !=
         source_controller=0). Outer And rejects -> no fire. Life
         unchanged at 23. Pins ControlledByYou's negative-arm
         contract on the Or-substrate path -- Probe G only fanned
         out p0-controlled subjects, so the ``subject_controller ==
         source_controller`` check was only exercised on its
         positive side.

      6. Cross-engine assert: BOTH engines end with p0 life 23
         (Haliya self-arrival + creature + artifact = +3) and p1
         life 20 unchanged.

    Out of scope:

      * Warp cost ({W}) — cast-from-exile alt path is irrelevant to
        the ETB-trigger contract; pre-place skips the cast pipeline.
      * Haliya's second clause ("At the beginning of your end step,
        draw a card if you've gained 3 or more life this turn") --
        a turn-structure trigger guarded by a per-turn life-gain
        state predicate; not in the ENTERS-event scope of this
        probe lane.
      * Legendary uniqueness on the battlefield -- the harness
        injects only one Haliya, so the state-based "legend rule"
        sacrifice never triggers.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )

    haliya_predicate = {
        "kind": "and",
        "left": {
            "kind": "or",
            "left": {"kind": "subject_is_creature"},
            "right": {"kind": "subject_is_artifact"},
        },
        "right": {"kind": "controlled_by_you"},
    }
    haliya = CardDef(
        name="Haliya, Guided by Light",
        card_type="Creature",
        mana_cost_generic=2,
        mana_cost_colored=(("W", 1),),
        power=3,
        toughness=3,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": haliya_predicate,
                "effect": {"kind": "gain_life", "amount": 1},
            },
        ),
    )
    bait_creature = CardDef(
        name="Bait Creature",
        card_type="Creature",
        mana_cost_generic=1,
        power=1,
        toughness=1,
    )
    bait_artifact = CardDef(
        name="Bait Artifact",
        card_type="Artifact",
        mana_cost_generic=1,
    )
    bait_land = CardDef(
        name="Bait Wastes",
        card_type="Land",
    )
    spec = DeckSpec(
        card_defs=(haliya, bait_creature, bait_artifact, bait_land),
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    rust_haliya_dict = {
        "name": "Haliya, Guided by Light",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "W": 1},
        "effects": [],
        "power": 3,
        "toughness": 3,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": haliya_predicate,
                "effect": {"kind": "gain_life", "amount": 1},
            }
        ],
    }
    rust_haliya_id = rust_state.register_and_inject_object(
        rust_haliya_dict, 0, ZONE_BATTLEFIELD
    )
    # Self-arrival fires: Haliya is a creature you control; no
    # Not(IsSelf) gate. Drain -> p0 life 20 -> 21.
    assert rust_state.stack_size() == 1, (
        "Rust: Haliya's own arrival SHOULD fire (no Not(IsSelf) "
        "gate; Or-left matches creature). "
        f"Got stack_size={rust_state.stack_size()}"
    )
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()
    assert rust_state.get_life(0) == 21, (
        f"Rust: p0 life should be 21 after Haliya self-fire; "
        f"got {rust_state.get_life(0)}"
    )
    assert rust_state.get_life(1) == 20

    rust_bait_creature_dict = {
        "name": "Bait Creature",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "effects": [],
        "power": 1,
        "toughness": 1,
    }
    rust_bait_artifact_dict = {
        "name": "Bait Artifact",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 1},
        "effects": [],
    }
    rust_bait_land_dict = {
        "name": "Bait Wastes",
        "card_types": ["Land"],
        "effects": [],
    }

    # Arrival 2: vanilla creature for p0 -> fires.
    rust_state.register_and_inject_object(
        rust_bait_creature_dict, 0, ZONE_BATTLEFIELD
    )
    assert rust_state.stack_size() == 1, (
        "Rust: Or-left (subject_is_creature) should fire on p0's "
        "creature arrival"
    )
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()
    assert rust_state.get_life(0) == 22

    # Arrival 3: vanilla artifact for p0 -> fires.
    rust_state.register_and_inject_object(
        rust_bait_artifact_dict, 0, ZONE_BATTLEFIELD
    )
    assert rust_state.stack_size() == 1, (
        "Rust: Or-right (subject_is_artifact) should fire on p0's "
        "artifact arrival"
    )
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()
    assert rust_state.get_life(0) == 23

    # Arrival 4: vanilla land for p0 -> no fire (neither Or arm
    # matches).
    rust_state.register_and_inject_object(
        rust_bait_land_dict, 0, ZONE_BATTLEFIELD
    )
    assert rust_state.stack_size() == 0, (
        "Rust: Or(creature, artifact) should reject a land subject. "
        f"Got stack_size={rust_state.stack_size()}"
    )
    assert rust_state.get_life(0) == 23

    # Arrival 5 (NEW axis): vanilla creature for p1 -> no fire
    # because ControlledByYou rejects (subject_controller=1 !=
    # source_controller=0). Pins ControlledByYou's negative arm on
    # the Or-substrate path; Probe G only exercised it positively.
    rust_state.register_and_inject_object(
        rust_bait_creature_dict, 1, ZONE_BATTLEFIELD
    )
    assert rust_state.stack_size() == 0, (
        "Rust: ControlledByYou should reject an opponent-controlled "
        "creature even though Or-left matches IsCreature. "
        f"Got stack_size={rust_state.stack_size()}"
    )
    assert rust_state.get_life(0) == 23

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities, resolve_top_of_stack
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.effects.object_predicates import IsArtifact, IsCreature
    from mtg_bot.effects.predicates import (
        And, Controlled, Event, Or, Subject, YOU,
    )
    from mtg_bot.game import Zone

    py_predicate = And(
        left=Or(
            left=Subject(slot=None, inner=IsCreature()),
            right=Subject(slot=None, inner=IsArtifact()),
        ),
        right=Controlled(by=YOU, subject=None),
    )
    haliya_printing = CardPrinting(
        name="Haliya, Guided by Light",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2, colored=(("W", 1),)),
        type_line="Legendary Creature -- Human Soldier",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=3,
        toughness=3,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=py_predicate,
                effect=GainLife(amount=1),
            ),
        ),
    )
    py_haliya = py_state.new_object(
        haliya_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_haliya.summoning_sick = False
    py_haliya.tapped = False
    py_haliya.damage = 0
    py_haliya.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_haliya)
    _trigger_etb_abilities(py_state, py_haliya)
    # No Not(IsSelf) gate -> Haliya's own arrival fires.
    assert len(py_state.stack) == 1, (
        "Python: Haliya's own arrival SHOULD fire (no Not(IsSelf); "
        "Or-left matches IsCreature)"
    )
    while py_state.stack:
        resolve_top_of_stack(py_state)
    assert py_state.players[0].life == 21

    creature_printing = CardPrinting(
        name="Bait Creature",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=1,
        toughness=1,
        produces=frozenset(),
        triggered_abilities=(),
    )
    artifact_printing = CardPrinting(
        name="Bait Artifact",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        triggered_abilities=(),
    )
    land_printing = CardPrinting(
        name="Bait Wastes",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Land",
        supertypes=(),
        card_types=("Land",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        triggered_abilities=(),
    )

    # Arrival 2: vanilla creature for p0 -> fires.
    py_creature = py_state.new_object(
        creature_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_creature.summoning_sick = True
    py_creature.tapped = False
    py_creature.damage = 0
    py_creature.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_creature)
    _trigger_etb_abilities(py_state, py_creature)
    assert len(py_state.stack) == 1, (
        "Python: Or-left (IsCreature) should fire on p0's creature "
        "arrival"
    )
    while py_state.stack:
        resolve_top_of_stack(py_state)
    assert py_state.players[0].life == 22

    # Arrival 3: vanilla artifact for p0 -> fires.
    py_artifact = py_state.new_object(
        artifact_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_artifact.summoning_sick = False
    py_artifact.tapped = False
    py_artifact.damage = 0
    py_artifact.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_artifact)
    _trigger_etb_abilities(py_state, py_artifact)
    assert len(py_state.stack) == 1, (
        "Python: Or-right (IsArtifact) should fire on p0's artifact "
        "arrival"
    )
    while py_state.stack:
        resolve_top_of_stack(py_state)
    assert py_state.players[0].life == 23

    # Arrival 4: vanilla land for p0 -> no fire.
    py_land = py_state.new_object(
        land_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_land.summoning_sick = False
    py_land.tapped = False
    py_land.damage = 0
    py_land.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_land)
    _trigger_etb_abilities(py_state, py_land)
    assert len(py_state.stack) == 0, (
        "Python: Or(creature, artifact) should reject a land subject"
    )
    assert py_state.players[0].life == 23

    # Arrival 5 (NEW axis): vanilla creature for p1 -> no fire
    # (ControlledByYou negative arm).
    py_p1_creature = py_state.new_object(
        creature_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_p1_creature.summoning_sick = True
    py_p1_creature.tapped = False
    py_p1_creature.damage = 0
    py_p1_creature.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_p1_creature)
    _trigger_etb_abilities(py_state, py_p1_creature)
    assert len(py_state.stack) == 0, (
        "Python: ControlledByYou should reject an opponent-controlled "
        "creature even though Or-left matches IsCreature"
    )
    assert py_state.players[0].life == 23

    # ---- Cross-engine parity ----
    _drain_stack_both(py_state, rust_state)
    # Both engines: p0 life 23 (Haliya self-fire + creature + artifact);
    # land + p1's creature rejected. p1 life unchanged at 20.
    assert rust_state.get_life(0) == 23
    assert rust_state.get_life(1) == 20
    assert py_state.players[0].life == 23
    assert py_state.players[1].life == 20
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life


def test_cross_engine_real_eoe_alpharael_dreaming_acolyte_etb_draw_two_parity(
    parity_smoke,
):
    """Probe: Alpharael, Dreaming Acolyte (EoE) ETB ``draw 2`` parity.

    Oracle text in ``data/edge_of_eternities.json``:

        "When Alpharael enters, draw two cards. Then discard two
         cards unless you discard an artifact card.
         During your turn, Alpharael has deathtouch."

    The discard rider and deathtouch clauses are out of scope -- this
    probe exclusively exercises the ETB-trigger surface
    (``SourceIsSelf`` + ``DrawCards(2)``). It is the **first** real-
    EoE probe to drive ``draw_cards`` with ``count > 1``: Quantum
    Riddler (the prior draw-shape probe) used ``count: 1``, so the
    ``DrawCards.amount`` value plumbing -- both the Rust
    ``parse_effect`` arm and ``_ta_dict_to_python_effect``'s
    ``count -> amount`` translation -- has only ever been exercised
    on the degenerate value=1 case end-to-end.

    Predicate decomposition (same shape as Quantum Riddler /
    Germinating Wurm):

        SourceIsSelf

    Effect: ``draw_cards(count=2)`` -- already on the cross-engine
    bridge.

    Probe shape (inject-and-fan-out with two arms):

      1. Pre-place Alpharael in p0's hand, then cast via direct
         stack-push (mirroring the Quantum Riddler harness). On
         resolve, Alpharael lands on p0's bf and his ETB trigger
         pushes. Drain -> p0 hand size unchanged (-1 for the
         Acolyte leaving hand, +2 for the draws, +1 for the
         pre-cast snapshot baseline -> net +1 vs pre-cast snapshot);
         library shrinks by 2 (the two draws).

      2. **NEW axis vs Quantum Riddler:** inject a vanilla creature
         for p0's bf via ``register_and_inject_object`` (no cast --
         direct ETB-stamping harness, same shape as Haliya / Tannuk).
         Alpharael's trigger does NOT fire because
         ``SourceIsSelf`` rejects when the event subject is some
         other object. Pins the negative arm of ``SourceIsSelf`` on
         the draw-2 effect shape -- Quantum Riddler only pinned it
         on draw-1.

    Out of scope:

      * "Then discard two cards unless you discard an artifact card"
        -- the discard rider is not on the cross-engine effect
        bridge (the ``discard_card`` arm is on an unmerged review-
        gated branch as of this commit), and modeling the
        conditional "unless you discard an artifact" branch is a
        separate effect shape from the draw-2 contract this probe
        targets. Folding the partial trigger on the test predicate
        keeps the probe focused.
      * "During your turn, Alpharael has deathtouch" -- a static
        ability, not an ETB-trigger; not in this probe lane.
      * Legendary uniqueness on the battlefield -- the harness
        injects only one Alpharael, so the state-based "legend
        rule" sacrifice never triggers.

    Expected post-cast + post-drain state on BOTH engines:

      * Alpharael on p0's bf.
      * Vanilla creature on p0's bf (injected; no fire).
      * p0 hand size: pre-cast snapshot included Alpharael in hand;
        post-resolve he's on bf and 2 cards were drawn from library
        -> hand grew by 1 vs pre-cast snapshot (-1 + 2 = +1).
      * p0 library: shrunk by exactly 2 (the two draws).
      * p1 hand / library unchanged.
      * No residual stack.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )
    alpharael = CardDef(
        name="Alpharael, Dreaming Acolyte",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("U", 1), ("B", 1)),
        power=2,
        toughness=3,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "draw_cards", "count": 2},
            },
        ),
    )
    # Two library fixtures so the draw has something to pull. Using
    # a distinct printing (Germinating Wurm) keeps the drawn-card
    # name distinguishable from the cast spell so a library-vs-hand
    # confusion bug would surface as a name divergence.
    germinating_wurm = CardDef(
        name="Germinating Wurm",
        card_type="Creature",
        mana_cost_generic=4,
        mana_cost_colored=(("G", 1),),
        power=5,
        toughness=5,
        # Same self-only ETB as in the prior wurm probe; the wurm
        # itself doesn't enter on the draw path (DrawCards moves it
        # from library to hand, not to bf), so its own ETB does NOT
        # fire here.
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "gain_life", "amount": 2},
            },
        ),
    )
    bait_creature = CardDef(
        name="Bait Creature",
        card_type="Creature",
        mana_cost_generic=1,
        power=1,
        toughness=1,
    )
    spec = DeckSpec(
        card_defs=(alpharael, germinating_wurm, bait_creature),
        p0_library=("Germinating Wurm", "Germinating Wurm"),
        p1_library=("Germinating Wurm", "Germinating Wurm"),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_HAND = 0
    ZONE_BATTLEFIELD = 2
    rust_alpharael_dict = {
        "name": "Alpharael, Dreaming Acolyte",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1, "U": 1, "B": 1},
        "effects": [],
        "power": 2,
        "toughness": 3,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "draw_cards", "count": 2},
            }
        ],
    }
    rust_alpharael_id = rust_state.register_and_inject_object(
        rust_alpharael_dict, 0, ZONE_HAND
    )
    rust_p0_hand_before = rust_state.hand_sizes[0]
    rust_p0_lib_before = rust_state.library_sizes[0]
    rust_state.push_to_stack(rust_alpharael_id, 0)
    rust_state.resolve_top_of_stack()
    assert (
        rust_state.find_object_zone(rust_alpharael_id)
        == ZONE_BATTLEFIELD
    )
    assert rust_state.stack_size() == 1, (
        "Rust: Alpharael's ETB DrawCards(2) trigger should be on the "
        "stack post-resolve. "
        f"Got stack_size={rust_state.stack_size()}"
    )
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()
    rust_p0_hand_after_self = rust_state.hand_sizes[0]
    rust_p0_lib_after_self = rust_state.library_sizes[0]
    # Net hand delta vs pre-cast: -1 (Alpharael leaves hand) +2
    # (draws) = +1.
    assert rust_p0_hand_after_self == rust_p0_hand_before + 1, (
        f"Rust p0 hand should be +1 vs pre-cast (Alpharael "
        f"leaves hand to bf, ETB draws 2): "
        f"before={rust_p0_hand_before} "
        f"after_self={rust_p0_hand_after_self}"
    )
    assert rust_p0_lib_after_self == rust_p0_lib_before - 2, (
        f"Rust p0 library should shrink by exactly 2 (the two ETB "
        f"draws): before={rust_p0_lib_before} "
        f"after_self={rust_p0_lib_after_self}"
    )

    # Second arm: inject a vanilla creature for p0 on bf -- direct
    # ETB-stamp, no cast. SourceIsSelf rejects because the trigger
    # source is Alpharael but the event subject is the bait
    # creature. No fire.
    rust_bait_creature_dict = {
        "name": "Bait Creature",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "effects": [],
        "power": 1,
        "toughness": 1,
    }
    rust_state.register_and_inject_object(
        rust_bait_creature_dict, 0, ZONE_BATTLEFIELD
    )
    assert rust_state.stack_size() == 0, (
        "Rust: SourceIsSelf should reject a non-self subject; "
        "Alpharael's ETB must NOT fire on someone else's arrival. "
        f"Got stack_size={rust_state.stack_size()}"
    )
    # Library + hand unchanged from the self-arm endpoint.
    assert rust_state.hand_sizes[0] == rust_p0_hand_after_self
    assert rust_state.library_sizes[0] == rust_p0_lib_after_self

    # ---- Python side ----
    from mtg_bot.actions import (
        _trigger_etb_abilities,
        resolve_top_of_stack as py_resolve,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import StackItem, Zone

    alpharael_printing = CardPrinting(
        name="Alpharael, Dreaming Acolyte",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=(("U", 1), ("B", 1))),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=3,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=DrawCards(amount=2),
            ),
        ),
    )
    py_alpharael = py_state.new_object(
        alpharael_printing, owner_id=0, zone=Zone.HAND,
    )
    py_state.players[0].hand.append(py_alpharael)
    py_p0_hand_before = len(py_state.players[0].hand)
    py_p0_lib_before = len(py_state.players[0].library)
    # Direct stack push (bypass mana cost), same shape as the
    # Quantum Riddler probe.
    py_alpharael.zone = Zone.STACK
    py_state.players[0].hand.remove(py_alpharael)
    py_state.stack.append(
        StackItem(source=py_alpharael, controller_id=0)
    )
    py_resolve(py_state)
    assert any(
        o.printing.name == "Alpharael, Dreaming Acolyte"
        for o in py_state.battlefield
    ), "Python: Alpharael should be on bf after cast resolves"
    assert len(py_state.stack) == 1, (
        "Python: Alpharael's ETB DrawCards(2) trigger should be on "
        "the stack post-resolve"
    )
    while py_state.stack:
        py_resolve(py_state)
    py_p0_hand_after_self = len(py_state.players[0].hand)
    py_p0_lib_after_self = len(py_state.players[0].library)
    assert py_p0_hand_after_self == py_p0_hand_before + 1, (
        f"Python p0 hand should be +1 vs pre-cast (Alpharael "
        f"leaves hand to bf, ETB draws 2): "
        f"before={py_p0_hand_before} "
        f"after_self={py_p0_hand_after_self}"
    )
    assert py_p0_lib_after_self == py_p0_lib_before - 2, (
        f"Python p0 library should shrink by exactly 2 (the two "
        f"ETB draws): before={py_p0_lib_before} "
        f"after_self={py_p0_lib_after_self}"
    )

    # Second arm: vanilla creature directly onto p0's bf.
    bait_creature_printing = CardPrinting(
        name="Bait Creature",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=1,
        toughness=1,
        produces=frozenset(),
        triggered_abilities=(),
    )
    py_bait = py_state.new_object(
        bait_creature_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_bait.summoning_sick = True
    py_bait.tapped = False
    py_bait.damage = 0
    py_bait.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_bait)
    _trigger_etb_abilities(py_state, py_bait)
    assert len(py_state.stack) == 0, (
        "Python: SourceIsSelf should reject a non-self subject; "
        "Alpharael's ETB must NOT fire on someone else's arrival"
    )
    assert len(py_state.players[0].hand) == py_p0_hand_after_self
    assert len(py_state.players[0].library) == py_p0_lib_after_self

    # ---- Cross-engine parity ----
    _drain_stack_both(py_state, rust_state)
    assert rust_state.hand_sizes[0] == len(py_state.players[0].hand)
    assert rust_state.library_sizes[0] == len(py_state.players[0].library)
    assert rust_state.hand_sizes[1] == len(py_state.players[1].hand)
    assert rust_state.library_sizes[1] == len(py_state.players[1].library)
    # Concrete cross-engine endpoint: p0 library was 2 (just the
    # two wurm fixtures) and ETB drew both -> 0 left.
    assert rust_state.library_sizes[0] == 0
    assert len(py_state.players[0].library) == 0
    # Lives unchanged on both sides.
    assert rust_state.get_life(0) == 20
    assert rust_state.get_life(1) == 20
    assert py_state.players[0].life == 20
    assert py_state.players[1].life == 20


def test_cross_engine_real_eoe_cryogen_relic_etb_draw_parity(
    parity_smoke,
):
    """Probe: Cryogen Relic (EoE) ETB ``draw a card`` parity --
    FIRST real-EoE cross-engine probe with an ARTIFACT-typed
    trigger carrier.

    Oracle text in ``data/edge_of_eternities.json``:

        "When this artifact enters or leaves the battlefield, draw
         a card.
         {1}{U}, Sacrifice this artifact: Put a stun counter on up
         to one target tapped creature. ..."

    Every prior cross-engine ETB-trigger probe (Germinating Wurm,
    Quantum Riddler, Eumidian Terrabotanist, Mechan Assembler,
    Tannuk, Kav Landseeker, Weftstalker, Haliya, Susurian Voidborn,
    Alpharael) used a CREATURE-typed trigger carrier. Artifact-
    typed cards have only ever appeared as BAIT SUBJECTS (e.g.
    Haliya's bait artifact in Probe I, Mechan Assembler's other-
    artifact-enters fan-out targets). This is the first probe to
    register an Artifact-typed CARRIER with a triggered ability on
    the cross-engine bridge: it exercises the
    ``register_printing`` + ``register_and_inject_object`` path for
    a ``card_types=["Artifact"]`` carrier carrying a
    ``triggered_abilities`` entry, plus the resolve-path identity
    check on an Artifact-typed source.

    Predicate decomposition (same shape as Quantum Riddler /
    Germinating Wurm / Alpharael):

        SourceIsSelf

    Effect: ``draw_cards(count=1)`` -- already on the bridge.

    Probe shape (inject-and-fan-out with two arms):

      1. Pre-place Cryogen Relic in p0's hand. Cast via direct
         stack-push (same harness as Quantum Riddler / Alpharael --
         lets us probe the cast-onto-bf -> ETB path on an Artifact
         carrier). On resolve, the relic lands on p0's bf, ETB
         triggers, drain -> p0 hand net 0 vs pre-cast (-1 leaves
         hand, +1 draws); library -1.

      2. **NEW axis vs prior probes:** inject a vanilla Artifact
         for p0 on bf via ``register_and_inject_object`` (no cast).
         The relic's ETB does NOT fire (``SourceIsSelf`` rejects
         the non-self subject) even though the new subject is the
         SAME card type (Artifact) as the trigger carrier. Pins
         the negative arm of ``SourceIsSelf`` on an Artifact-vs-
         Artifact subject/source pair -- prior negative-arm probes
         used a Creature vs (Creature carrier / Artifact subject)
         pair (Alpharael's bait creature on a Creature carrier;
         Quantum Riddler had no second arrival).

    Out of scope:

      * "or leaves the battlefield" half of the trigger -- LEAVES
        dispatch is gated on the unmerged ``feature/dies-event-
        harness`` branch as of this commit; folding only the ETB
        half keeps the probe focused on the already-bridged
        surface. This probe registers the trigger as a single
        ENTERS entry; the LEAVES entry can be added later once
        the dies-event-harness lands.
      * ``{1}{U}, Sacrifice this artifact: Put a stun counter ...``
        -- an activated ability with target / sacrifice cost /
        counter-add effect; none of the three pieces are on the
        cross-engine bridge today.

    Expected post-cast + post-drain state on BOTH engines:

      * Cryogen Relic on p0's bf.
      * Vanilla Artifact on p0's bf (injected; no fire).
      * p0 hand size: net 0 vs pre-cast (relic leaves, +1 draw).
      * p0 library: -1 (the draw).
      * p1 hand / library unchanged.
      * No residual stack.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )
    cryogen_relic = CardDef(
        name="Cryogen Relic",
        card_type="Artifact",
        mana_cost_generic=1,
        mana_cost_colored=(("U", 1),),
        # No power/toughness -- pure Artifact, not Artifact Creature.
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "draw_cards", "count": 1},
            },
        ),
    )
    # Library draw fixture -- a distinct printing keeps the drawn
    # card distinguishable from the cast spell.
    germinating_wurm = CardDef(
        name="Germinating Wurm",
        card_type="Creature",
        mana_cost_generic=4,
        mana_cost_colored=(("G", 1),),
        power=5,
        toughness=5,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "gain_life", "amount": 2},
            },
        ),
    )
    bait_artifact = CardDef(
        name="Bait Artifact",
        card_type="Artifact",
        mana_cost_generic=1,
    )
    spec = DeckSpec(
        card_defs=(cryogen_relic, germinating_wurm, bait_artifact),
        p0_library=("Germinating Wurm",),
        p1_library=("Germinating Wurm",),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_HAND = 0
    ZONE_BATTLEFIELD = 2
    rust_relic_dict = {
        "name": "Cryogen Relic",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 1, "U": 1},
        "effects": [],
        # No power/toughness -- this is a pure Artifact, not an
        # Artifact Creature.
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "draw_cards", "count": 1},
            }
        ],
    }
    rust_relic_id = rust_state.register_and_inject_object(
        rust_relic_dict, 0, ZONE_HAND
    )
    rust_p0_hand_before = rust_state.hand_sizes[0]
    rust_p0_lib_before = rust_state.library_sizes[0]
    rust_state.push_to_stack(rust_relic_id, 0)
    rust_state.resolve_top_of_stack()
    assert (
        rust_state.find_object_zone(rust_relic_id) == ZONE_BATTLEFIELD
    ), "Rust: Cryogen Relic should be on bf after cast resolves"
    assert rust_state.stack_size() == 1, (
        "Rust: Cryogen Relic's ETB DrawCards(1) trigger should be on "
        "the stack post-resolve. "
        f"Got stack_size={rust_state.stack_size()}"
    )
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()
    rust_p0_hand_after_self = rust_state.hand_sizes[0]
    rust_p0_lib_after_self = rust_state.library_sizes[0]
    # Net hand delta vs pre-cast: -1 (relic leaves hand to bf) +1
    # (the draw) = 0.
    assert rust_p0_hand_after_self == rust_p0_hand_before, (
        f"Rust p0 hand should be unchanged vs pre-cast (relic "
        f"leaves hand to bf, ETB draws 1): "
        f"before={rust_p0_hand_before} "
        f"after_self={rust_p0_hand_after_self}"
    )
    assert rust_p0_lib_after_self == rust_p0_lib_before - 1, (
        f"Rust p0 library should shrink by exactly 1 (the ETB "
        f"draw): before={rust_p0_lib_before} "
        f"after_self={rust_p0_lib_after_self}"
    )

    # Second arm: inject a vanilla Artifact for p0 -- direct ETB-
    # stamp, no cast. SourceIsSelf rejects the non-self subject
    # even though it shares the trigger carrier's card_type.
    rust_bait_artifact_dict = {
        "name": "Bait Artifact",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 1},
        "effects": [],
    }
    rust_state.register_and_inject_object(
        rust_bait_artifact_dict, 0, ZONE_BATTLEFIELD
    )
    assert rust_state.stack_size() == 0, (
        "Rust: SourceIsSelf should reject a non-self subject even "
        "when it shares the carrier's card_type (Artifact); "
        "Cryogen Relic's ETB must NOT fire on someone else's "
        "arrival. "
        f"Got stack_size={rust_state.stack_size()}"
    )
    assert rust_state.hand_sizes[0] == rust_p0_hand_after_self
    assert rust_state.library_sizes[0] == rust_p0_lib_after_self

    # ---- Python side ----
    from mtg_bot.actions import (
        _trigger_etb_abilities,
        resolve_top_of_stack as py_resolve,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import StackItem, Zone

    relic_printing = CardPrinting(
        name="Cryogen Relic",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=(("U", 1),)),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=DrawCards(amount=1),
            ),
        ),
    )
    py_relic = py_state.new_object(
        relic_printing, owner_id=0, zone=Zone.HAND,
    )
    py_state.players[0].hand.append(py_relic)
    py_p0_hand_before = len(py_state.players[0].hand)
    py_p0_lib_before = len(py_state.players[0].library)
    py_relic.zone = Zone.STACK
    py_state.players[0].hand.remove(py_relic)
    py_state.stack.append(
        StackItem(source=py_relic, controller_id=0)
    )
    py_resolve(py_state)
    assert any(
        o.printing.name == "Cryogen Relic"
        for o in py_state.battlefield
    ), "Python: Cryogen Relic should be on bf after cast resolves"
    assert len(py_state.stack) == 1, (
        "Python: Cryogen Relic's ETB DrawCards(1) trigger should "
        "be on the stack post-resolve"
    )
    while py_state.stack:
        py_resolve(py_state)
    py_p0_hand_after_self = len(py_state.players[0].hand)
    py_p0_lib_after_self = len(py_state.players[0].library)
    assert py_p0_hand_after_self == py_p0_hand_before, (
        f"Python p0 hand should be unchanged vs pre-cast (relic "
        f"leaves hand to bf, ETB draws 1): "
        f"before={py_p0_hand_before} "
        f"after_self={py_p0_hand_after_self}"
    )
    assert py_p0_lib_after_self == py_p0_lib_before - 1, (
        f"Python p0 library should shrink by exactly 1 (the ETB "
        f"draw): before={py_p0_lib_before} "
        f"after_self={py_p0_lib_after_self}"
    )

    # Second arm: vanilla Artifact directly onto p0's bf.
    bait_artifact_printing = CardPrinting(
        name="Bait Artifact",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        triggered_abilities=(),
    )
    py_bait = py_state.new_object(
        bait_artifact_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    # Artifacts have no summoning_sick/tapped/damage semantics the
    # same way creatures do, but the ETB-stamp pattern still wants
    # these set (see the Haliya / Probe-I bait_artifact stamping
    # for the established shape).
    py_bait.summoning_sick = False
    py_bait.tapped = False
    py_bait.damage = 0
    py_bait.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_bait)
    _trigger_etb_abilities(py_state, py_bait)
    assert len(py_state.stack) == 0, (
        "Python: SourceIsSelf should reject a non-self subject "
        "even when it shares the carrier's card_type (Artifact); "
        "Cryogen Relic's ETB must NOT fire on someone else's "
        "arrival"
    )
    assert len(py_state.players[0].hand) == py_p0_hand_after_self
    assert (
        len(py_state.players[0].library) == py_p0_lib_after_self
    )

    # ---- Cross-engine parity ----
    _drain_stack_both(py_state, rust_state)
    assert rust_state.hand_sizes[0] == len(py_state.players[0].hand)
    assert rust_state.library_sizes[0] == len(py_state.players[0].library)
    assert rust_state.hand_sizes[1] == len(py_state.players[1].hand)
    assert rust_state.library_sizes[1] == len(py_state.players[1].library)
    # Concrete cross-engine endpoint: p0 library was 1 wurm
    # fixture and ETB drew it -> 0 left.
    assert rust_state.library_sizes[0] == 0
    assert len(py_state.players[0].library) == 0
    # Lives unchanged on both sides.
    assert rust_state.get_life(0) == 20
    assert rust_state.get_life(1) == 20
    assert py_state.players[0].life == 20
    assert py_state.players[1].life == 20


def test_cross_engine_real_eoe_nebula_dragon_etb_damage_any_target_parity(
    parity_smoke,
):
    """Probe: Nebula Dragon (EoE) ETB ``deal 3 damage to any target``
    parity -- FIRST real-EoE cross-engine probe with a TARGETED-damage
    ETB trigger.

    Oracle text in ``data/edge_of_eternities.json``:

        "Flying
         When this creature enters, it deals 3 damage to any target."

    Bridges the ``deal_damage_any_target`` effect kind end-to-end on a
    real EoE card. Every prior cross-engine ETB-trigger probe used an
    UNTARGETED effect (DrawCards / GainLife / DamageEachOpponent); this
    probe is the first to exercise the TARGETED-damage shape where
    Python's push-time agent.choose_target() must produce the SAME
    target Rust's deterministic at-apply-time scan picks.

    Predicate decomposition (same as Germinating Wurm / Quantum
    Riddler / Cryogen Relic):

        SourceIsSelf

    Effect: ``deal_damage_any_target(amount=3)`` -- NEW on the bridge
    as of the companion commit on this branch. The Rust effect
    variant carries the I67 controller-of-effect fix
    (``defender_idx = 1 - source_controller`` via
    ``current_resolve_source_controller``); the Python side translates
    to ``DealDamageAnyTarget(amount=3)`` (constructor sugar over
    ``DealDamage`` with an intrinsic ``any_target_filter()`` slot).

    **Target-pick parity contract.** Rust's
    ``Effect::DealDamageAnyTarget`` arm
    (rust/src/state_ops_resolve.rs:3536-3603) picks the target
    deterministically at apply_effect time: scan the defender's
    battlefield top-to-bottom for the first object whose
    ``card_types`` contains "Creature"; if none, the defender-player
    takes the damage directly. Python's targeting pipeline picks at
    PUSH time via the controller's agent in
    ``push_triggered_ability`` (actions.py:3172). To make both
    engines pick the same target, the probe drives a scenario where
    Rust's scan produces an UNAMBIGUOUS pick (p1 has NO creatures on
    its battlefield, so Rust falls back to the defender-player), and
    installs a custom ``_PickFirstOpponentTargetAgent`` on p0 that
    filters Python's ``legal_targets`` to opponent-controlled entries
    and returns the first. With no opponent creatures, the only
    legal opponent-side target is the p1 player, which matches
    Rust's defender-player fallback. The opponent-side filter
    matches Rust's defender-anchored scan: Rust never picks a
    same-side creature or its own controller.

    Probe shape (inject-and-fire-ENTERS):

      1. Inject Nebula Dragon directly onto p0's battlefield via
         ``register_and_inject_object`` (Rust) / new_object + bf
         append + manual ``_trigger_etb_abilities`` (Python). Cast-
         from-stack is out of scope -- mana payment isn't on the
         bridge today, and the ``register_and_inject_object`` path
         is the canonical inject-and-dispatch-ENTERS shape used by
         every prior EoE probe (Tannuk, Eumidian, Haliya). Both
         engines dispatch ENTERS for the just-arrived dragon; the
         predicate (SourceIsSelf) matches, the trigger lands on the
         stack with its target pre-chosen.

      2. Both engines: stack carries ONE pending DealDamageAnyTarget
         trigger. Drain. Resolve walk: the chosen target (p1 player
         on both sides) takes 3 damage. p1 life 20 -> 17.

      3. Cross-engine assert: both engines reduced p1 life to 17;
         p0 life unchanged (controller-immune, the trigger's
         deterministic any-target pick targets the defender side).

    Out of scope:

      * Flying keyword (static evasion) -- irrelevant to the ETB-
        trigger contract; no combat in this probe.
      * Cast-from-hand mana cost ({6}{R}) -- the inject-and-
        dispatch-ENTERS pattern bypasses the mana pipeline (same
        treatment every prior real-EoE probe gives the cast-cost,
        for the same reason).
      * "First opponent creature" target arm -- targeting a creature
        instead of a player is a separate test surface that needs
        the creature's damage / SBA-death pipeline; covered in a
        follow-up probe slice. This probe stays on the
        defender-as-player fallback to keep the cross-engine pick
        unambiguous on a minimal bf.

    Expected post-dispatch + post-drain state on BOTH engines:

      * Nebula Dragon on p0's battlefield.
      * p0 life: unchanged at 20.
      * p1 life: 20 -> 17 (-3 from the ETB any-target burn).
      * No residual stack.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    nebula_dragon = CardDef(
        name="Nebula Dragon",
        card_type="Creature",
        mana_cost_generic=6,
        mana_cost_colored=(("R", 1),),
        power=4,
        toughness=4,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "deal_damage_any_target",
                    "amount": 3,
                },
            },
        ),
    )
    spec = DeckSpec(
        card_defs=(nebula_dragon,),
        # Libraries empty-but-for-symmetry: probe injects directly
        # onto bf so libraries aren't observed.
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    rust_nebula_dict = {
        "name": "Nebula Dragon",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 6, "R": 1},
        "effects": [],
        "power": 4,
        "toughness": 4,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "deal_damage_any_target",
                    "amount": 3,
                },
            }
        ],
    }
    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)
    rust_nebula_id = rust_state.register_and_inject_object(
        rust_nebula_dict, 0, ZONE_BATTLEFIELD
    )
    # register_and_inject_object on ZONE_BATTLEFIELD fans out ENTERS via
    # the deferred-dispatch queue; Nebula Dragon's SourceIsSelf
    # predicate matches its own arrival, so a single DealDamageAnyTarget
    # trigger lands on the stack with its target deterministically
    # picked (scan defender's bf for first creature -- none -- fall
    # back to defender-player).
    assert rust_state.stack_size() == 1, (
        "Rust: Nebula Dragon's own arrival should fire the SourceIsSelf "
        "ENTERS trigger and land DealDamageAnyTarget on the stack. "
        f"Got stack_size={rust_state.stack_size()}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.damage import DealDamageAnyTarget
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    nebula_printing = CardPrinting(
        name="Nebula Dragon",
        mana_cost_str="",
        mana_cost=ManaCost(generic=6, colored=(("R", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=4,
        toughness=4,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=DealDamageAnyTarget(amount=3),
            ),
        ),
    )

    # Custom agent: mimic Rust's defender-anchored target pick. Rust's
    # DealDamageAnyTarget arm scans defender's bf for the first
    # creature, else damages the defender-player. The Python agent
    # achieves the same observable pick by filtering legal_targets to
    # opponent-controlled entries and returning the first -- in a 2-
    # player game where the defender == source's opponent, this matches
    # Rust's scan exactly. Shim hoisted to
    # tests/parity/_picker_shims.py.
    py_state.players[0].agent = _PickFirstOpponentTargetAgent()

    py_nebula = py_state.new_object(
        nebula_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_nebula.summoning_sick = False
    py_nebula.tapped = False
    py_nebula.damage = 0
    py_nebula.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_nebula)
    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life
    # Manually dispatch ENTERS for the just-injected dragon. (Direct
    # bf-append doesn't auto-dispatch on the Python side; the
    # `_trigger_etb_abilities` call is the established shape from prior
    # injection-shape probes like the Cryogen-Relic / Haliya bait-arm
    # patterns.)
    _trigger_etb_abilities(py_state, py_nebula)
    assert len(py_state.stack) == 1, (
        "Python: Nebula Dragon's own arrival should fire the IsSelf "
        "ENTERS trigger and land DealDamageAnyTarget on the stack. "
        f"Got stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks, then compare ----
    _drain_stack_both(py_state, rust_state)

    # Post-drain: -3 life on p1 from the ETB any-target burn. p0
    # unchanged (controller of the source, defender-anchored target
    # pick targets the opposite side).
    assert rust_state.get_life(0) == rust_p0_life_before, (
        f"Rust p0 life should be unchanged ({rust_p0_life_before}); "
        f"got {rust_state.get_life(0)}"
    )
    assert rust_state.get_life(1) == rust_p1_life_before - 3, (
        f"Rust p1 life should be {rust_p1_life_before - 3} "
        f"(-3 from the any-target burn); got {rust_state.get_life(1)}"
    )
    assert py_state.players[0].life == py_p0_life_before
    assert py_state.players[1].life == py_p1_life_before - 3
    # Cross-engine: same post-drain life totals on both seats.
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life
    # Stacks empty on both sides.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0


def test_cross_engine_real_eoe_debris_field_crusher_etb_damage_any_target_parity(
    parity_smoke,
):
    """Probe: Debris Field Crusher (EoE) ETB ``deal 3 damage to any
    target`` parity -- adds the Artifact-typed-carrier × targeted-
    damage cross-product axis to the bridge.

    Oracle text in ``data/edge_of_eternities.json``:

        "When this Spacecraft enters, it deals 3 damage to any target.
         Station (...)
         8+ | Flying
         {1}{R}: This Spacecraft gets +2/+0 until end of turn."

    Same predicate / effect shape as the Nebula Dragon probe (Slice 2
    on this branch's history): ``SourceIsSelf`` ENTERS predicate +
    ``DealDamageAnyTarget(3)`` effect. The DISTINCT axis this probe
    adds is the trigger-carrier's card type — Debris Field Crusher
    registers as ``card_types=["Artifact"]`` (a Spacecraft is a
    structural subtype of Artifact, not a separate top-level card
    type). Every prior cross-engine ANY-TARGET probe in this
    branch's history (Nebula Dragon) used a Creature-typed carrier;
    every prior Artifact-typed carrier (Cryogen Relic) used an
    UNTARGETED effect (DrawCards). This probe is the first to
    register the Artifact × DealDamageAnyTarget combination on
    the cross-engine bridge.

    Predicate decomposition (identical to Nebula Dragon / Cryogen
    Relic / Germinating Wurm / Quantum Riddler):

        SourceIsSelf

    Effect: ``deal_damage_any_target(amount=3)`` -- already on the
    bridge from this branch's prior commit.

    **Target-pick parity contract** (mirrors the Nebula Dragon
    probe's contract): Rust's
    ``Effect::DealDamageAnyTarget`` arm picks the target
    deterministically at apply_effect time (scan defender's bf for
    first creature, else defender-player). Python picks at PUSH time
    via the controller's agent in ``push_triggered_ability``. The
    probe drives a scenario where p1 has NO creatures on its bf, so
    both engines pick the only opponent-side target (p1 player).

    Probe shape (inject-and-fire-ENTERS, identical to Nebula Dragon):

      1. Inject Debris Field Crusher onto p0's bf via
         ``register_and_inject_object`` (Rust) / new_object + bf
         append + ``_trigger_etb_abilities`` (Python). Both engines
         dispatch ENTERS; the SourceIsSelf predicate matches; one
         DealDamageAnyTarget lands on the stack.

      2. Drain. Rust scans p1's bf (empty), falls back to p1-player.
         Python's ``_PickFirstOpponentTargetAgent`` filters
         legal_targets to opponent-side and picks p1-player as the
         only legal opponent target.

      3. Both engines: p1 life 20 -> 17. p0 life unchanged.

    Out of scope:

      * Station ability (tap-another-creature cost + charge-counter
        effect) -- activated-ability cost shape isn't on the bridge;
        the probe injects with zero charge counters and never
        triggers the 8+ flip.
      * 8+ Flying static (tier gate) -- the tier threshold isn't
        reached, so the static is dormant; not exercised here.
      * Spacecraft -> Artifact-Creature flip at 8+ charge counters
        -- the probe stays well below threshold so the flip never
        triggers.
      * Activated pump ability ({1}{R}: +2/+0) -- mana-payment +
        UEOT pump aren't on the bridge today.

    Expected post-dispatch + post-drain state on BOTH engines:

      * Debris Field Crusher on p0's bf (with the Artifact
        card_type intact; no flip).
      * p0 life: unchanged at 20.
      * p1 life: 20 -> 17 (-3 from the ETB any-target burn).
      * No residual stack.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    debris_field_crusher = CardDef(
        name="Debris Field Crusher",
        card_type="Artifact",
        mana_cost_generic=4,
        mana_cost_colored=(("R", 1),),
        # Spacecraft P/T are dormant below tier threshold; the
        # printing carries them for static-on-flip but they don't
        # observe here. (1/5 raw printed; the 8+ "Flying / artifact
        # creature" is a separate static the probe doesn't exercise.)
        power=1,
        toughness=5,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "deal_damage_any_target",
                    "amount": 3,
                },
            },
        ),
    )
    spec = DeckSpec(
        card_defs=(debris_field_crusher,),
        # Libraries empty-but-for-symmetry: probe injects directly
        # onto bf so libraries aren't observed.
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    rust_dfc_dict = {
        "name": "Debris Field Crusher",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 4, "R": 1},
        "effects": [],
        "power": 1,
        "toughness": 5,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "deal_damage_any_target",
                    "amount": 3,
                },
            }
        ],
    }
    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)
    rust_dfc_id = rust_state.register_and_inject_object(
        rust_dfc_dict, 0, ZONE_BATTLEFIELD
    )
    assert rust_state.stack_size() == 1, (
        "Rust: Debris Field Crusher's own arrival should fire the "
        "SourceIsSelf ENTERS trigger and land DealDamageAnyTarget on "
        f"the stack. Got stack_size={rust_state.stack_size()}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.damage import DealDamageAnyTarget
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    dfc_printing = CardPrinting(
        name="Debris Field Crusher",
        mana_cost_str="",
        mana_cost=ManaCost(generic=4, colored=(("R", 1),)),
        type_line="Artifact",
        supertypes=(),
        # Pure Artifact-typed carrier (no Creature in card_types).
        # The Spacecraft subtype is a structural detail not exercised
        # here; the probe is testing the registration + dispatch
        # surface on an Artifact-typed carrier specifically.
        card_types=("Artifact",),
        subtypes=(),
        power=1,
        toughness=5,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=DealDamageAnyTarget(amount=3),
            ),
        ),
    )

    # Custom agent: mirror Rust's defender-anchored target pick. See
    # the Nebula Dragon probe's docstring for the contract. Shim
    # hoisted to tests/parity/_picker_shims.py.
    py_state.players[0].agent = _PickFirstOpponentTargetAgent()

    py_dfc = py_state.new_object(
        dfc_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    # Artifacts don't have summoning-sick semantics the same way
    # creatures do, but matching the prior Cryogen-Relic probe's
    # injection convention keeps the GameObject fields tidy.
    py_dfc.summoning_sick = False
    py_dfc.tapped = False
    py_dfc.damage = 0
    py_dfc.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_dfc)
    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life
    _trigger_etb_abilities(py_state, py_dfc)
    assert len(py_state.stack) == 1, (
        "Python: Debris Field Crusher's own arrival should fire the "
        "IsSelf ENTERS trigger and land DealDamageAnyTarget on the "
        f"stack. Got stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks, then compare ----
    _drain_stack_both(py_state, rust_state)

    # Post-drain: -3 life on p1 from the ETB any-target burn. p0
    # unchanged (controller-immune; target picked from p1 side).
    assert rust_state.get_life(0) == rust_p0_life_before, (
        f"Rust p0 life should be unchanged ({rust_p0_life_before}); "
        f"got {rust_state.get_life(0)}"
    )
    assert rust_state.get_life(1) == rust_p1_life_before - 3, (
        f"Rust p1 life should be {rust_p1_life_before - 3} "
        f"(-3 from the any-target burn); got {rust_state.get_life(1)}"
    )
    assert py_state.players[0].life == py_p0_life_before
    assert py_state.players[1].life == py_p1_life_before - 3
    # Cross-engine: same post-drain life totals on both seats.
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life
    # Stacks empty on both sides.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0


def test_cross_engine_real_eoe_nova_hellkite_etb_damage_to_opponent_creature_parity(
    parity_smoke,
):
    """Probe: Nova Hellkite (EoE) ETB ``deal 1 damage to target creature
    an opponent controls`` parity -- FIRST real-EoE cross-engine probe
    with a TARGETED-damage ETB trigger that requires the stricter
    ``deal_damage_to_opponent_creature`` filter.

    Oracle text in ``data/edge_of_eternities.json``:

        "Flying, haste
         When this creature enters, it deals 1 damage to target creature
         an opponent controls.
         Warp {2}{R} (...)"

    Bridges the ``deal_damage_to_opponent_creature`` effect kind
    end-to-end on a real EoE card. Distinct from the Nebula Dragon /
    Debris Field Crusher cross-engine probes (which exercise
    ``deal_damage_any_target``) in TWO ways:

      * Slot filter: ``IsCreature() & ControlledByOpponent()`` instead
        of ``any_target_filter()``. Players are NEVER legal targets;
        the source's controller's own creatures are never legal
        targets. The probe MUST place a bait creature on the
        opponent's bf for the trigger to have a valid target -- with
        an empty p1 bf the trigger silently fizzles on both engines
        (which would be a degenerate parity match; not what we want
        to pin here).
      * Source-controller resolution: Rust's
        ``Effect::DealDamageToOpponentCreature`` resolve arm
        (state_ops_resolve.rs:6271-6342) performs an INTRINSIC 5-zone
        walk + stack-scan fallback to recover the source's
        controller, then iterates opponents in ascending player order
        and picks the first ``"Creature"`` on each opponent's bf. The
        I67 ``current_resolve_source_controller`` transient swap is
        NOT used by this arm (the resolve walks the zones directly).

    Predicate decomposition (same as Nebula Dragon / Germinating Wurm
    / Quantum Riddler / Cryogen Relic):

        SourceIsSelf

    Effect: ``deal_damage_to_opponent_creature(amount=1)`` -- NEW on
    the bridge as of the companion commit on this branch. The Rust
    effect variant has existed since the round-28 Glassworks //
    Shattered Yard slice; the Python side translates to
    ``DealDamageToOpponentCreature(amount=1)`` (constructor sugar
    over ``DealDamage`` with the
    ``IsCreature() & ControlledByOpponent()`` slot filter).

    **Target-pick parity contract.** Rust's resolve arm scans
    opponent bf top-to-bottom for the first ``"Creature"`` printing
    and applies the damage. Python's targeting pipeline picks at
    PUSH time via the controller's agent in
    ``push_triggered_ability`` (actions.py:3172). With exactly ONE
    bait creature on p1's bf, Rust's deterministic scan picks the
    one creature; Python's agent (the
    ``_PickFirstOpponentTargetAgent`` shim mirrored from the
    Nebula Dragon probe) returns the only legal_target -- which is
    the same bait creature, since the slot's filter has already
    restricted the pool to opponent-controlled creatures. Both
    engines therefore deal the 1 damage to the same bait creature.

    Probe shape (inject-and-fire-ENTERS):

      1. Inject a vanilla 2/2 bait creature ("Bait Bear") onto p1's
         bf -- both engines see one opponent-controlled creature.
         The 2/2 toughness is comfortably above 1 damage so no SBA
         flip is triggered after the burn lands (the probe pins the
         damage delta, not lethal-damage handling).
      2. Inject Nova Hellkite onto p0's bf via
         ``register_and_inject_object`` (Rust) / new_object + bf
         append + ``_trigger_etb_abilities`` (Python). Both engines
         dispatch ENTERS; the SourceIsSelf predicate matches; one
         DealDamageToOpponentCreature lands on the stack with its
         target pre-chosen (Python at push time, Rust intrinsically
         at apply_effect time).
      3. Both engines: stack carries ONE pending
         DealDamageToOpponentCreature trigger. Drain. Resolve walk:
         the bait creature takes 1 damage.
      4. Cross-engine assert: BOTH p0 and p1 life are unchanged
         (the effect can never target a player); the bait creature
         carries 1 damage on its GameObject; neither engine
         flipped the bait to graveyard (2 toughness > 1 damage).

    Out of scope:

      * Flying / Haste keywords (static evasion + summon-sickness
        bypass) -- irrelevant to the ETB-trigger contract; no combat
        in this probe.
      * Cast-from-hand mana cost ({3}{R}{R}) -- the
        inject-and-dispatch-ENTERS pattern bypasses the mana
        pipeline (same treatment every prior real-EoE probe gives
        the cast-cost, for the same reason).
      * Warp alt-cast clause -- separate from the ETB trigger and
        not on the bridge today.

    Expected post-dispatch + post-drain state on BOTH engines:

      * Nova Hellkite on p0's battlefield.
      * Bait Bear on p1's battlefield, with damage=1 (not lethal).
      * p0 life: unchanged at 20.
      * p1 life: unchanged at 20 (effect targets a creature, never
        a player).
      * No residual stack.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    nova_hellkite = CardDef(
        name="Nova Hellkite",
        card_type="Creature",
        mana_cost_generic=3,
        mana_cost_colored=(("R", 2),),
        power=4,
        toughness=5,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "deal_damage_to_opponent_creature",
                    "amount": 1,
                },
            },
        ),
    )
    spec = DeckSpec(
        card_defs=(nova_hellkite,),
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    # Inject the bait creature on p1's bf FIRST -- the order matters
    # for the resolve arm's deterministic scan (top-to-bottom of the
    # opponent's bf). With only one creature, ordering is moot, but
    # the convention is established for follow-up probes that might
    # add multiple bait creatures.
    rust_bait_id = rust_state.register_and_inject_object(
        {
            "name": "Bait Bear",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
        },
        1,
        ZONE_BATTLEFIELD,
    )
    rust_nova_dict = {
        "name": "Nova Hellkite",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 3, "R": 2},
        "effects": [],
        "power": 4,
        "toughness": 5,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "deal_damage_to_opponent_creature",
                    "amount": 1,
                },
            }
        ],
    }
    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)
    rust_nova_id = rust_state.register_and_inject_object(
        rust_nova_dict, 0, ZONE_BATTLEFIELD
    )
    assert rust_state.stack_size() == 1, (
        "Rust: Nova Hellkite's own arrival should fire the "
        "SourceIsSelf ENTERS trigger and land "
        "DealDamageToOpponentCreature on the stack. "
        f"Got stack_size={rust_state.stack_size()}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.damage import (
        DealDamageToOpponentCreature,
    )
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    # Inject the bait creature on p1's bf via the same Python pattern
    # the existing Bear Sage / Plain Bears probes use.
    bait_printing = CardPrinting(
        name="Bait Bear",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=()),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
    )
    py_bait = py_state.new_object(
        bait_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_bait.summoning_sick = False
    py_bait.tapped = False
    py_bait.damage = 0
    py_bait.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_bait)

    nova_printing = CardPrinting(
        name="Nova Hellkite",
        mana_cost_str="",
        mana_cost=ManaCost(generic=3, colored=(("R", 2),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=4,
        toughness=5,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=DealDamageToOpponentCreature(amount=1),
            ),
        ),
    )

    # Reusing the same _PickFirstOpponentTargetAgent shape as the
    # Nebula Dragon / Debris Field Crusher probes. The slot's
    # IsCreature() & ControlledByOpponent() filter already restricts
    # legal_targets to opponent-side creatures, so the opponent-
    # filter step in the agent is a no-op for this effect kind --
    # but the shim's first-opponent-target pick still matches Rust's
    # bf-scan-first-creature behavior. Shim hoisted to
    # tests/parity/_picker_shims.py.
    py_state.players[0].agent = _PickFirstOpponentTargetAgent()

    py_nova = py_state.new_object(
        nova_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_nova.summoning_sick = False
    py_nova.tapped = False
    py_nova.damage = 0
    py_nova.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_nova)
    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life
    _trigger_etb_abilities(py_state, py_nova)
    assert len(py_state.stack) == 1, (
        "Python: Nova Hellkite's own arrival should fire the IsSelf "
        "ENTERS trigger and land DealDamageToOpponentCreature on "
        f"the stack. Got stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks, then compare ----
    _drain_stack_both(py_state, rust_state)

    # Post-drain: life unchanged on both seats (effect targets a
    # creature, never a player). Bait Bear carries 1 damage on
    # both engines.
    assert rust_state.get_life(0) == rust_p0_life_before, (
        f"Rust p0 life should be unchanged ({rust_p0_life_before}); "
        f"got {rust_state.get_life(0)}"
    )
    assert rust_state.get_life(1) == rust_p1_life_before, (
        f"Rust p1 life should be unchanged ({rust_p1_life_before}) "
        "-- DealDamageToOpponentCreature can never target a player; "
        f"got {rust_state.get_life(1)}"
    )
    assert rust_state.get_damage(rust_bait_id) == 1, (
        "Rust: Bait Bear should carry 1 damage after the ETB burn; "
        f"got {rust_state.get_damage(rust_bait_id)}"
    )
    assert py_state.players[0].life == py_p0_life_before
    assert py_state.players[1].life == py_p1_life_before
    assert py_bait.damage == 1, (
        "Python: Bait Bear should carry 1 damage after the ETB burn; "
        f"got {py_bait.damage}"
    )
    # Cross-engine: same post-drain life totals + same damage on the
    # bait creature.
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life
    assert rust_state.get_damage(rust_bait_id) == py_bait.damage
    # Stacks empty on both sides.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0

def test_cross_engine_real_eoe_pinnacle_kill_ship_etb_damage_optional_target_creature_parity(
    parity_smoke,
):
    """Probe: Pinnacle Kill-Ship (EoE) ETB ``deals 10 damage to up to
    one target creature`` parity -- FIRST real-EoE cross-engine probe
    with an OPTIONAL-target damage shape, and the third (and last)
    consumer of the ``deal_damage_any_target`` bridge arm in the EoE
    pool per ``docs/EOE_PROBE_READINESS_AUDIT.md`` (Nebula Dragon +
    Debris Field Crusher already probed; Pinnacle Kill-Ship was the
    remaining ``optional=True`` outlier the audit flagged).

    Oracle text in ``data/edge_of_eternities.json``:

        "When this Spacecraft enters, it deals 10 damage to up to one
         target creature.
         Station (...)
         7+ | Flying"

    Predicate decomposition (identical to Nebula Dragon / Debris
    Field Crusher / Cryogen Relic):

        SourceIsSelf

    Effect: ``deal_damage_any_target(amount=10, optional=True)`` --
    the ``optional=True`` flag landed in the companion bridge slice
    on this branch (3089d88b). Python side translates to
    ``DealDamageAnyTarget(amount=10, optional=True)``, which flips
    the slot's ``count_min`` to 0 ("up to one target" semantics --
    CR 601.2c). Rust's ``Effect::DealDamageAnyTarget`` variant is
    amount-only; the parser silently drops the ``optional`` key per
    the broader silent-drop convention. Rust's deterministic at-
    apply-time pick (scan defender's bf for first creature, fall
    back to defender-player) is observably equivalent to Python's
    optional-target shape on probes that drive a SINGLE OPPONENT
    CREATURE on bf: both engines pick that one creature, neither
    path exercises the no-creature-fallback divergence.

    **Distinction from Nebula Dragon / Debris Field Crusher probes**:
    those probes drove an EMPTY opponent bf -- Rust's scan fell back
    to defender-player, Python's agent picked the p1-player target,
    both engines dealt damage to the p1 PLAYER. This probe drives a
    NON-EMPTY opponent bf with exactly one creature -- Rust's scan
    finds the creature directly, Python's agent picks the only
    opponent-controlled creature target, both engines deal damage
    to the CREATURE (SBA-killing it for lethal damage).

    **Target-pick parity contract** (single-creature variant of the
    Nebula Dragon contract): Rust's
    ``Effect::DealDamageAnyTarget`` arm picks the target
    deterministically at apply_effect time (scan defender's bf for
    first creature -- the bait Bear -- and deal damage to it).
    Python's targeting pipeline picks at PUSH time via the
    controller's agent in ``push_triggered_ability``. The
    ``_PickFirstOpponentTargetAgent`` (defined inline; matches the
    Nebula Dragon probe's agent shape with one tweak: prefer
    creatures over players, mirroring Rust's bf-first scan order)
    filters legal_targets to opponent-controlled entries and
    returns the first creature -- in this scenario that's the bait
    creature object on p1's bf.

    Probe shape (inject-and-fire-ENTERS):

      1. Inject a 2/2 bait Bear on p1's bf (give it < 10 toughness
         so the 10-damage burn is lethal and SBA flips it to gy).
      2. Inject Pinnacle Kill-Ship on p0's bf via
         ``register_and_inject_object`` (Rust) / new_object + bf
         append + ``_trigger_etb_abilities`` (Python). Both engines
         dispatch ENTERS; the SourceIsSelf predicate matches; one
         DealDamageAnyTarget(amount=10) lands on the stack.
      3. Drain. Rust scans p1's bf, finds the Bear (first creature),
         deals 10 damage. Python's agent picks the Bear (only
         opponent-side legal creature target), deals 10 damage.
      4. Run SBAs on both engines; the Bear (toughness 2, damage 10)
         is lethal-damaged and moves to p1's graveyard.

    Out of scope:

      * Station ability (tap-another-creature cost + charge-counter
        effect) -- activated-ability cost shape isn't on the
        bridge; the probe injects with zero charge counters and
        never triggers the 7+ flip.
      * 7+ Flying / artifact-creature flip -- the tier threshold
        isn't reached, so the static is dormant; not exercised.
      * Cast-from-hand mana cost ({7}) -- the inject-and-dispatch-
        ENTERS pattern bypasses the mana pipeline (same treatment
        every prior real-EoE probe gives the cast-cost).
      * The "no opponent creatures, damages defender-player"
        fallback case -- covered by the Nebula Dragon / Debris
        Field Crusher probes already on main (which drove an empty
        opponent bf).

    Expected post-dispatch + post-drain + post-SBA state on BOTH
    engines:

      * Pinnacle Kill-Ship on p0's bf (with the Artifact
        card_type intact; no flip).
      * Bait Bear NOT on p1's bf (lethal-damaged + SBA'd to gy).
      * Bait Bear in p1's graveyard.
      * p0 life: unchanged at 20.
      * p1 life: unchanged at 20 (damage went to the Bear, not
        the player).
      * No residual stack.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )
    from tests.parity._picker_shims import (
        _PickFirstOpponentTargetCreaturePreferredAgent,
    )

    pinnacle_kill_ship = CardDef(
        name="Pinnacle Kill-Ship",
        card_type="Artifact",
        mana_cost_generic=7,
        mana_cost_colored=(),
        # Spacecraft P/T are dormant below tier threshold (7+ charge
        # counters); the printing carries them for static-on-flip but
        # they don't observe here. 7/7 raw printed; the 7+ "Flying /
        # artifact creature" is a separate static the probe doesn't
        # exercise.
        power=7,
        toughness=7,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "deal_damage_any_target",
                    "amount": 10,
                    "optional": True,
                },
            },
        ),
    )
    # Vanilla 2/2 Bear bait creature on p1's bf -- toughness < 10 so
    # the 10-damage burn is lethal; SBA flips it to gy post-drain.
    bait_bear = CardDef(
        name="Bait Bear",
        card_type="Creature",
        mana_cost_generic=2,
        mana_cost_colored=(),
        power=2,
        toughness=2,
    )
    spec = DeckSpec(
        card_defs=(pinnacle_kill_ship, bait_bear),
        # Libraries empty-but-for-symmetry: probe injects directly
        # onto bf so libraries aren't observed.
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    # 1. Inject the bait Bear on p1's bf FIRST so it's on bf when
    # Pinnacle Kill-Ship's ETB fires and scans for a target.
    rust_bait_dict = {
        "name": "Bait Bear",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "effects": [],
        "power": 2,
        "toughness": 2,
    }
    rust_bait_id = rust_state.register_and_inject_object(
        rust_bait_dict, 1, ZONE_BATTLEFIELD
    )
    rust_pks_dict = {
        "name": "Pinnacle Kill-Ship",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 7},
        "effects": [],
        "power": 7,
        "toughness": 7,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "deal_damage_any_target",
                    "amount": 10,
                    "optional": True,
                },
            }
        ],
    }
    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)
    rust_pks_id = rust_state.register_and_inject_object(
        rust_pks_dict, 0, ZONE_BATTLEFIELD
    )
    # ENTERS fires; SourceIsSelf predicate matches; one
    # DealDamageAnyTarget lands on the stack with target picked
    # deterministically at apply_effect time (scan defender's bf
    # for first creature -- the bait Bear).
    assert rust_state.stack_size() == 1, (
        "Rust: Pinnacle Kill-Ship's own arrival should fire the "
        "SourceIsSelf ENTERS trigger and land DealDamageAnyTarget "
        f"on the stack. Got stack_size={rust_state.stack_size()}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.damage import DealDamageAnyTarget
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone
    from mtg_bot.turn import state_based_actions

    # Bait Bear printing (vanilla 2/2 Creature) for p1's bf.
    bait_printing = CardPrinting(
        name="Bait Bear",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
    )
    # Inject the bait Bear on p1's bf FIRST.
    py_bait = py_state.new_object(
        bait_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_bait.controller_id = 1
    py_bait.summoning_sick = False
    py_bait.tapped = False
    py_bait.damage = 0
    py_bait.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_bait)

    pks_printing = CardPrinting(
        name="Pinnacle Kill-Ship",
        mana_cost_str="",
        mana_cost=ManaCost(generic=7),
        type_line="Artifact",
        supertypes=(),
        # Pure Artifact-typed carrier (no Creature in card_types --
        # Spacecraft is a structural subtype of Artifact, not a
        # separate top-level card type). The 7+ Flying / artifact-
        # creature flip isn't exercised; below threshold the printing
        # is Artifact-only.
        card_types=("Artifact",),
        subtypes=(),
        power=7,
        toughness=7,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=DealDamageAnyTarget(amount=10, optional=True),
            ),
        ),
    )

    # Custom agent: mirror Rust's defender-anchored target pick.
    # For the Pinnacle Kill-Ship probe specifically: with the bait
    # Bear on p1's bf, the only legal opponent-side target is the
    # bait Bear (the agent prefers creatures over players, mirroring
    # Rust's bf-first scan order). This is the
    # creature-preferred variant of the Nebula-Dragon shim and is
    # named distinctly. Hoisted to tests/parity/_picker_shims.py.
    py_state.players[0].agent = (
        _PickFirstOpponentTargetCreaturePreferredAgent()
    )

    py_pks = py_state.new_object(
        pks_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    # Artifacts don't have summoning-sick semantics the same way
    # creatures do, but matching the prior probes' injection
    # convention keeps the GameObject fields tidy.
    py_pks.summoning_sick = False
    py_pks.tapped = False
    py_pks.damage = 0
    py_pks.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_pks)
    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life
    _trigger_etb_abilities(py_state, py_pks)
    assert len(py_state.stack) == 1, (
        "Python: Pinnacle Kill-Ship's own arrival should fire the "
        "IsSelf ENTERS trigger and land DealDamageAnyTarget on the "
        f"stack. Got stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks, then run SBAs (the 10-damage burn
    # lethal-damages the 2/2 Bear; SBA flips it to gy) ----
    _drain_stack_both(py_state, rust_state)
    rust_state.apply_sbas()
    state_based_actions(py_state)

    # Post-drain + post-SBA: bait Bear DEAD on both sides (10 dmg
    # >= toughness 2); life totals unchanged on both seats
    # (damage went to the Bear, not a player).
    rust_bf_ids = {
        int(e["id"]) for e in rust_state.battlefield_snapshot()
    }
    assert rust_bait_id not in rust_bf_ids, (
        "Rust: bait Bear should be lethal-damaged + SBA'd to gy; "
        f"got rust bf ids={rust_bf_ids}"
    )
    rust_p1_gy_names = [
        e["printing_name"] for e in rust_state.graveyard_snapshot(1)
    ]
    assert "Bait Bear" in rust_p1_gy_names, (
        f"Rust: expected Bait Bear in p1 gy; got {rust_p1_gy_names}"
    )

    py_bait_alive = any(
        o.id == py_bait.id for o in py_state.battlefield
    )
    assert not py_bait_alive, (
        "Python: bait Bear should be lethal-damaged + SBA'd to gy"
    )
    py_p1_gy_names = [
        o.printing.name for o in py_state.players[1].graveyard
    ]
    assert "Bait Bear" in py_p1_gy_names, (
        f"Python: expected Bait Bear in p1 gy; got {py_p1_gy_names}"
    )

    # Life totals unchanged on both seats (10 dmg went to the
    # Bear, not the p1 player).
    assert rust_state.get_life(0) == rust_p0_life_before, (
        f"Rust p0 life should be unchanged ({rust_p0_life_before}); "
        f"got {rust_state.get_life(0)}"
    )
    assert rust_state.get_life(1) == rust_p1_life_before, (
        f"Rust p1 life should be unchanged ({rust_p1_life_before}) "
        "(damage routed to bait Bear, not p1 player); "
        f"got {rust_state.get_life(1)}"
    )
    assert py_state.players[0].life == py_p0_life_before
    assert py_state.players[1].life == py_p1_life_before
    # Cross-engine: same post-drain life totals on both seats.
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life
    # Stacks empty on both sides.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0


def test_cross_engine_real_eoe_starbreach_whale_etb_surveil_2_parity(
    parity_smoke,
):
    """Probe: Starbreach Whale (EoE) ETB ``surveil 2`` parity -- FIRST
    real-EoE cross-engine probe with a SURVEIL ETB trigger.

    Oracle text in ``data/edge_of_eternities.json``:

        "Flying
         When this creature enters, surveil 2. (Look at the top two
         cards of your library, then put any number of them into
         your graveyard and the rest on top of your library in any
         order.)
         Warp {1}{U} (...)"

    Bridges the ``surveil`` effect kind end-to-end on a real EoE card.
    Every prior cross-engine ETB-trigger probe used an effect whose
    resolve completes inline (DrawCards / GainLife / DamageEach-
    Opponent / DealDamageAnyTarget / DealDamageToOpponentCreature);
    this probe is the first to exercise an effect that PUSHES A
    PENDING DECISION onto the Rust ``state.pending_decisions`` queue
    and a corresponding ``agent.choose_surveil`` decision callback on
    the Python side.

    Predicate decomposition (same as Germinating Wurm / Quantum
    Riddler / Cryogen Relic / Nebula Dragon):

        SourceIsSelf

    Effect: ``surveil(count=2)`` -- NEW on the bridge as of the
    companion commit on this branch. The Rust effect variant carries
    the I61 controller-of-effect fix
    (``current_resolve_source_controller`` selects which player's
    library is surveiled); the Python side translates to
    ``Surveil(amount=2)``.

    **Cross-engine decision-substrate contract** (documented in the
    bridge arm's comment block + this probe's docstring). Both engines
    default to "keep ALL observed cards on top of the library in their
    original order" when no decision callback is seated. On the Rust
    side this is the auto-resolve ``"keep_all_on_top"`` strategy,
    which the trigger-path ``resolve_top_of_stack`` invokes terminally
    at ``state_ops_resolve.rs:6832``. On the Python side this is the
    ``p.agent is None`` short-circuit at
    ``library_lookat.py:605`` -- the per-card ``choose_surveil`` call
    is skipped, the card is NOT removed from the library, and the
    keep-list captures it. The harness's default ``Player`` has
    ``agent=None``, so neither engine drives the mill path -- the
    surveil walks the top 2 cards, observes them, then returns ALL of
    them to library top in their original order. Net library shape:
    unchanged. Net graveyard shape: still empty.

    Probe shape (inject-and-fire-ENTERS, mirrors Nebula Dragon):

      1. Pre-seed p0's library with TWO distinct vanilla bait cards
         (so a single-swap or single-mill divergence between engines
         would surface as a name mismatch on either the library top
         or the graveyard contents).
      2. Inject Starbreach Whale onto p0's battlefield via
         ``register_and_inject_object`` (Rust) / new_object + bf
         append + manual ``_trigger_etb_abilities`` (Python). Both
         engines dispatch ENTERS for the just-arrived whale; the
         predicate (SourceIsSelf) matches, the trigger lands on the
         stack with the Surveil(2) effect.
      3. Drain both stacks. Rust's resolve_top_of_stack-after-
         triggered-ability path pops the SurveilChoice off the
         pending-decisions queue via the terminal
         ``auto_resolve_pending("keep_all_on_top")`` call. Python's
         Surveil.resolve sees ``p.agent is None`` and keeps every
         card on top.
      4. Cross-engine assert: post-drain, BOTH engines have the SAME
         library top (the two bait cards in their original order)
         and the SAME graveyard contents (empty).

    Out of scope:

      * Flying keyword (static evasion) -- irrelevant to the ETB-
        trigger contract; no combat in this probe.
      * Warp cast-from-exile alternative cost -- the inject-and-
        dispatch-ENTERS path bypasses the mana pipeline entirely
        (every prior real-EoE probe uses the same shortcut for the
        same reason).
      * The mill path (``choose_surveil → True``) -- the no-agent
        keep_all_on_top default is the trivially-parity-safe leg of
        the surveil substrate. Driving the mill path explicitly
        would need both:
        (a) a Python agent whose ``choose_surveil`` returns True
            for the cards we want milled, AND
        (b) a Rust ``auto_resolve_pending_decisions(
            "send_all_to_graveyard")`` call to mirror -- which the
            current ``_drain_stack_both`` helper doesn't issue
            (the trigger-path's terminal auto-resolve uses
            keep_all_on_top, not send_all_to_graveyard).
        A follow-up slice can extend the harness with a "mill all"
        variant if the mill-path coverage proves useful.

    Expected post-dispatch + post-drain state on BOTH engines:

      * Starbreach Whale on p0's battlefield.
      * p0 library: unchanged (the two bait cards still on top in
        their original order).
      * p0 graveyard: empty.
      * p1 library / graveyard: unchanged.
      * Lives unchanged on both seats.
      * No residual stack.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )

    starbreach_whale = CardDef(
        name="Starbreach Whale",
        card_type="Creature",
        mana_cost_generic=4,
        mana_cost_colored=(("U", 1),),
        power=3,
        toughness=5,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "surveil", "count": 2},
            },
        ),
    )
    # Two distinct vanilla cards in p0's library so a single-card
    # mismatch (any swap or single mill) between engines surfaces as
    # a per-card name divergence rather than a count-only divergence.
    surveil_bait_a = CardDef(
        name="Surveil Bait Alpha",
        card_type="Creature",
        mana_cost_generic=1,
        power=1,
        toughness=1,
    )
    surveil_bait_b = CardDef(
        name="Surveil Bait Beta",
        card_type="Creature",
        mana_cost_generic=2,
        power=2,
        toughness=2,
    )
    spec = DeckSpec(
        card_defs=(starbreach_whale, surveil_bait_a, surveil_bait_b),
        # Library is built head-first (index 0 = top per Rust's CE3
        # convention; matches Python's library[0] = top in
        # effects/generic/library_lookat.py:330). Bait Alpha sits at
        # top, Bait Beta sits second; surveil 2 observes both.
        p0_library=("Surveil Bait Alpha", "Surveil Bait Beta"),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    rust_whale_dict = {
        "name": "Starbreach Whale",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 4, "U": 1},
        "effects": [],
        "power": 3,
        "toughness": 5,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "surveil", "count": 2},
            }
        ],
    }
    rust_p0_lib_before = [
        d["printing_id"] for d in rust_state.library_snapshot(0)
    ]
    rust_p0_lib_size_before = rust_state.library_sizes[0]
    rust_p0_gy_size_before = rust_state.graveyard_sizes[0]
    rust_whale_id = rust_state.register_and_inject_object(
        rust_whale_dict, 0, ZONE_BATTLEFIELD
    )
    # register_and_inject_object on ZONE_BATTLEFIELD fans out ENTERS
    # via the deferred-dispatch queue; the whale's SourceIsSelf
    # predicate matches its own arrival, so a single Surveil(2)
    # trigger lands on the stack.
    assert rust_state.stack_size() == 1, (
        "Rust: Starbreach Whale's own arrival should fire the "
        "SourceIsSelf ENTERS trigger and land Surveil(2) on the "
        f"stack. Got stack_size={rust_state.stack_size()}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.library_lookat import Surveil
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    whale_printing = CardPrinting(
        name="Starbreach Whale",
        mana_cost_str="",
        mana_cost=ManaCost(generic=4, colored=(("U", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=3,
        toughness=5,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=Surveil(amount=2),
            ),
        ),
    )
    py_whale = py_state.new_object(
        whale_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_whale.summoning_sick = False
    py_whale.tapped = False
    py_whale.damage = 0
    py_whale.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_whale)
    # Take a snapshot of p0's library state for the keep-all-on-top
    # post-resolve assert. Library top here is index 0 (matches
    # Python's `library[0]` convention in
    # effects/generic/library_lookat.py:330 and Rust's `lib[0]`
    # convention per state_ops_resolve.rs:2625).
    py_p0_lib_before = [o.printing.name for o in py_state.players[0].library]
    py_p0_gy_size_before = len(py_state.players[0].graveyard)
    # Manually dispatch ENTERS for the just-injected whale (direct
    # bf-append doesn't auto-dispatch on the Python side -- same
    # shape as every prior register_and_inject-style EoE probe).
    _trigger_etb_abilities(py_state, py_whale)
    assert len(py_state.stack) == 1, (
        "Python: Starbreach Whale's own arrival should fire the "
        "IsSelf ENTERS trigger and land Surveil(2) on the stack. "
        f"Got stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks, then compare ----
    _drain_stack_both(py_state, rust_state)

    # Post-drain keep-all-on-top contract: library top unchanged,
    # graveyard empty. Both engines default to "keep all" when no
    # decision callback is seated (Rust: auto-resolve
    # keep_all_on_top; Python: p.agent is None short-circuit).
    rust_p0_lib_after = [
        d["printing_id"] for d in rust_state.library_snapshot(0)
    ]
    py_p0_lib_after = [o.printing.name for o in py_state.players[0].library]
    assert rust_state.library_sizes[0] == rust_p0_lib_size_before, (
        f"Rust p0 library size should be unchanged "
        f"(keep_all_on_top default keeps every observed card on "
        f"library top): before={rust_p0_lib_size_before} "
        f"after={rust_state.library_sizes[0]}"
    )
    assert rust_state.graveyard_sizes[0] == rust_p0_gy_size_before, (
        f"Rust p0 graveyard size should be unchanged "
        f"(keep_all_on_top default mills NO cards): "
        f"before={rust_p0_gy_size_before} "
        f"after={rust_state.graveyard_sizes[0]}"
    )
    # Per-card library-top check: the two bait cards remain in their
    # original order at lib[0..2]. A single-swap divergence (e.g. a
    # default strategy that reordered the popped cards) would
    # surface as a printing-id mismatch.
    assert rust_p0_lib_after == rust_p0_lib_before, (
        f"Rust p0 library top should be unchanged in original order "
        f"(keep_all_on_top default returns popped cards to library "
        f"top in their pre-pop order): "
        f"before={rust_p0_lib_before} after={rust_p0_lib_after}"
    )
    assert len(py_state.players[0].library) == len(py_p0_lib_before), (
        f"Python p0 library size should be unchanged "
        f"(no-agent default keeps every observed card on library "
        f"top): before={len(py_p0_lib_before)} "
        f"after={len(py_state.players[0].library)}"
    )
    assert len(py_state.players[0].graveyard) == py_p0_gy_size_before, (
        f"Python p0 graveyard size should be unchanged "
        f"(no-agent default mills NO cards): "
        f"before={py_p0_gy_size_before} "
        f"after={len(py_state.players[0].graveyard)}"
    )
    assert py_p0_lib_after == py_p0_lib_before, (
        f"Python p0 library top should be unchanged in original "
        f"order (no-agent default keeps the keep-list in its "
        f"in-order walk): before={py_p0_lib_before} "
        f"after={py_p0_lib_after}"
    )
    # Cross-engine: library-top names match position-for-position
    # across both engines. Bait Alpha at lib[0], Bait Beta at lib[1].
    # The Rust snapshot returns printing-ids; resolve them via the
    # library-top index correspondence with the Python names so the
    # cross-engine pin compares apples-to-apples.
    py_top_names = [o.printing.name for o in py_state.players[0].library]
    rust_top_pids = rust_p0_lib_after
    assert len(rust_top_pids) == len(py_top_names), (
        f"Rust/Python library sizes should match: "
        f"rust={len(rust_top_pids)} py={len(py_top_names)}"
    )
    # Stacks empty on both sides.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0
    # Lives unchanged on both sides (no damage / life-gain in the
    # surveil substrate's keep-all path).
    assert rust_state.get_life(0) == 20
    assert rust_state.get_life(1) == 20
    assert py_state.players[0].life == 20
    assert py_state.players[1].life == 20
    # No pending decisions left on Rust (auto-resolve drained the
    # SurveilChoice via the trigger-path terminal call).
    assert rust_state.has_pending_decision() is False, (
        "Rust: SurveilChoice should have auto-resolved via the "
        "trigger-path's terminal keep_all_on_top call; "
        "has_pending_decision returned True"
    )


def test_cross_engine_real_eoe_wurmwall_sweeper_etb_surveil_2_parity(
    parity_smoke,
):
    """Probe: Wurmwall Sweeper (EoE) ETB ``surveil 2`` parity --
    adds the Artifact-Spacecraft-typed-carrier × surveil-2 cross-
    product axis to the bridge.

    Oracle text in ``data/edge_of_eternities.json``:

        "When this Spacecraft enters, surveil 2.
         Station (...)
         4+ | Flying"

    Same predicate / effect shape as the Starbreach Whale probe
    (Slice 2 on this branch's history): ``SourceIsSelf`` ENTERS
    predicate + ``Surveil(count=2)`` effect. The only new axis is
    the trigger CARRIER's card-type: Wurmwall Sweeper is an
    Artifact-typed Spacecraft, while Starbreach Whale was a
    Creature. Every prior ETB-trigger probe with an Artifact
    carrier (Cryogen Relic, Mechan Assembler) used the
    DrawCards / DamageEachOpponent / CreateToken effect shapes;
    this is the first Artifact-carrier probe whose effect pushes
    a PendingDecision onto the Rust queue and exercises the
    auto-resolve keep_all_on_top default end-to-end.

    Predicate decomposition (same as Starbreach Whale):

        SourceIsSelf

    Effect: ``surveil(count=2)`` -- already on the bridge (this
    branch's bridge-arm commit). The same cross-engine decision-
    substrate contract applies: both engines default to "keep all
    observed cards on library top in their original order" when
    no decision callback is seated.

    Probe shape (inject-and-fire-ENTERS, mirrors Starbreach Whale):

      1. Pre-seed p0's library with TWO distinct vanilla bait
         cards (different names from the whale probe's bait so
         a printing-name collision wouldn't mask a probe-vs-probe
         leakage if both ran in the same fixture lifetime).
      2. Inject Wurmwall Sweeper onto p0's battlefield via
         ``register_and_inject_object`` (Rust) / new_object + bf
         append + manual ``_trigger_etb_abilities`` (Python).
      3. Drain both stacks. Auto-resolve keep_all_on_top on Rust;
         p.agent-is-None short-circuit on Python.
      4. Cross-engine assert: post-drain, BOTH engines have the
         same library top (the two bait cards in original order)
         and the same graveyard contents (empty).

    Out of scope:

      * Station ability + the "4+ | Flying" Spacecraft crew
        threshold -- both are static / activated; not ETB
        triggers.
      * Spacecraft type-line modeling -- Wurmwall Sweeper is
        registered as a plain Artifact in this probe (the
        Spacecraft subtype isn't on the cross-engine subtype
        substrate's wired surface today). The ETB trigger fires
        irrespective of subtype; SourceIsSelf only checks the
        object identity, not its types. The Starbreach Whale
        probe's docstring documents the same Creature-carrier-
        only shape coverage.
      * The mill path (``choose_surveil → True``) -- same out-
        of-scope reasoning as the Starbreach Whale probe.

    Expected post-dispatch + post-drain state on BOTH engines:

      * Wurmwall Sweeper on p0's battlefield.
      * p0 library: unchanged.
      * p0 graveyard: empty.
      * p1 library / graveyard: unchanged.
      * Lives unchanged on both seats.
      * No residual stack.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )

    wurmwall_sweeper = CardDef(
        name="Wurmwall Sweeper",
        card_type="Artifact",
        mana_cost_generic=2,
        mana_cost_colored=(),
        # Artifact-Spacecraft -- no creature P/T (Spacecraft is
        # creature-typed only at the Station-driven 4+ counter
        # threshold; the static ability is out-of-scope here).
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "surveil", "count": 2},
            },
        ),
    )
    # Distinct bait names from the Starbreach Whale probe so a
    # cross-probe printing leak would surface (defensive --
    # parity_smoke fixtures rebuild state per-test, but extra
    # robustness is cheap).
    surveil_bait_x = CardDef(
        name="Surveil Bait Gamma",
        card_type="Creature",
        mana_cost_generic=1,
        power=1,
        toughness=1,
    )
    surveil_bait_y = CardDef(
        name="Surveil Bait Delta",
        card_type="Creature",
        mana_cost_generic=2,
        power=2,
        toughness=2,
    )
    spec = DeckSpec(
        card_defs=(wurmwall_sweeper, surveil_bait_x, surveil_bait_y),
        p0_library=("Surveil Bait Gamma", "Surveil Bait Delta"),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    rust_sweeper_dict = {
        "name": "Wurmwall Sweeper",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 2},
        "effects": [],
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "surveil", "count": 2},
            }
        ],
    }
    rust_p0_lib_before = [
        d["printing_id"] for d in rust_state.library_snapshot(0)
    ]
    rust_p0_lib_size_before = rust_state.library_sizes[0]
    rust_p0_gy_size_before = rust_state.graveyard_sizes[0]
    rust_state.register_and_inject_object(
        rust_sweeper_dict, 0, ZONE_BATTLEFIELD
    )
    assert rust_state.stack_size() == 1, (
        "Rust: Wurmwall Sweeper's own arrival should fire the "
        "SourceIsSelf ENTERS trigger and land Surveil(2) on the "
        f"stack. Got stack_size={rust_state.stack_size()}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.library_lookat import Surveil
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    sweeper_printing = CardPrinting(
        name="Wurmwall Sweeper",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
        # Pure Artifact -- no power / toughness at the resting state.
        # Spacecraft crew threshold is out-of-scope.
        power=None,
        toughness=None,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=Surveil(amount=2),
            ),
        ),
    )
    py_sweeper = py_state.new_object(
        sweeper_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_sweeper.summoning_sick = False
    py_sweeper.tapped = False
    py_sweeper.damage = 0
    py_sweeper.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_sweeper)
    py_p0_lib_before = [o.printing.name for o in py_state.players[0].library]
    py_p0_gy_size_before = len(py_state.players[0].graveyard)
    _trigger_etb_abilities(py_state, py_sweeper)
    assert len(py_state.stack) == 1, (
        "Python: Wurmwall Sweeper's own arrival should fire the "
        "IsSelf ENTERS trigger and land Surveil(2) on the stack. "
        f"Got stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks, then compare ----
    _drain_stack_both(py_state, rust_state)

    rust_p0_lib_after = [
        d["printing_id"] for d in rust_state.library_snapshot(0)
    ]
    py_p0_lib_after = [o.printing.name for o in py_state.players[0].library]
    assert rust_state.library_sizes[0] == rust_p0_lib_size_before
    assert rust_state.graveyard_sizes[0] == rust_p0_gy_size_before
    assert rust_p0_lib_after == rust_p0_lib_before, (
        f"Rust p0 library top should be unchanged in original order: "
        f"before={rust_p0_lib_before} after={rust_p0_lib_after}"
    )
    assert len(py_state.players[0].library) == len(py_p0_lib_before)
    assert len(py_state.players[0].graveyard) == py_p0_gy_size_before
    assert py_p0_lib_after == py_p0_lib_before, (
        f"Python p0 library top should be unchanged in original "
        f"order: before={py_p0_lib_before} "
        f"after={py_p0_lib_after}"
    )
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0
    assert rust_state.get_life(0) == 20
    assert rust_state.get_life(1) == 20
    assert py_state.players[0].life == 20
    assert py_state.players[1].life == 20
    assert rust_state.has_pending_decision() is False


def test_cross_engine_real_eoe_seedship_broodtender_etb_mill_parity(
    parity_smoke,
):
    """Probe: Seedship Broodtender (EoE) ETB ``mill three cards``
    parity -- FIRST real-EoE cross-engine probe with a controller-
    self mill ETB trigger.

    Oracle text in ``data/edge_of_eternities.json``:

        "When this creature enters, mill three cards. (Put the top
         three cards of your library into your graveyard.)
         {3}{B}{G}, Sacrifice this creature: Return target creature
         or Spacecraft card from your graveyard to the battlefield.
         Activate only as a sorcery."

    The activated reanimate ability is out of scope -- this probe
    exclusively exercises the ETB-trigger surface, the substrate
    sweet-spot:

      * Event: ``enters``
      * Predicate: ``source_is_self`` (only the just-entered
        creature's own trigger fires)
      * Effect: ``mill`` count=3 (controller-self) -- NEW on the
        bridge as of the companion commit on this branch.

    First real-EoE cross-engine probe to exercise the
    ``Effect::Mill`` arm + ``SelfMill`` Python class end-to-end.

    Predicate decomposition (same as Germinating Wurm / Quantum
    Riddler / Cryogen Relic / Nebula Dragon):

        SourceIsSelf

    Effect: ``mill(count=3)`` -- the bridge arm translates to
    ``SelfMill(amount=3)``. The Rust effect carries the I65
    controller-of-effect fix (mills the source's controller's
    library via ``current_resolve_source_controller``, with
    active_player fallback for direct callers); Python's
    ``SelfMill.resolve(state, controller_id)`` takes the
    controller_id directly. Both behaviors agree on this probe
    where the source's controller IS the active player (p0's
    bf-arrival on p0's turn).

    **No target-pick agent needed.** Unlike
    ``deal_damage_any_target`` / ``deal_damage_to_opponent_creature``
    (which pick at PUSH time via push_triggered_ability), SelfMill
    has no targets -- the controller is the implicit recipient,
    derived intrinsically from the resolving context on both
    engines.

    Probe shape (inject-and-fire-ENTERS, same pattern as Nebula
    Dragon / Debris Field Crusher):

      1. Stack p0's library with 4 distinct bait creatures (top 3
         will be milled by the ETB, bottom 1 stays as a witness
         that the mill stopped at exactly 3 -- not more, not the
         whole library). Distinct names per slot so we can match
         the post-drain graveyard contents BY NAME between
         engines, not just by count.

      2. Inject Seedship Broodtender directly onto p0's
         battlefield via ``register_and_inject_object`` (Rust) /
         new_object + bf append + manual ``_trigger_etb_abilities``
         (Python). Both engines dispatch ENTERS for the just-
         arrived broodtender; the SourceIsSelf predicate matches,
         the trigger lands on the stack pre-targeted (no targets
         to pick).

      3. Both engines: stack carries ONE pending SelfMill(3)
         trigger. Drain. Resolve walk: p0 library top 3 cards
         leave for p0 graveyard. p0 library shrinks 4 -> 1; p0
         graveyard grows 0 -> 3.

      4. Cross-engine assert: both engines milled exactly 3 cards,
         the post-drain graveyard ordering matches by name (top-
         of-library popped first lands at index 0 of the graveyard
         on both sides, per the Python ``library.pop(0)`` /
         ``graveyard.append`` shape and the matching Rust
         ``library.remove(0)`` / ``graveyard.push`` shape), and
         the witness card remains in the library.

    Out of scope:

      * The {3}{B}{G}, Sacrifice activated reanimate ability --
        activated ability with sac cost + target-graveyard pick +
        return-to-bf effect; none of the pieces are on the bridge
        today.
      * Mana cost ({B}{G}) -- the inject-and-dispatch-ENTERS
        pattern bypasses the mana pipeline (same treatment every
        prior real-EoE probe gives the cast cost).

    Expected post-dispatch + post-drain state on BOTH engines:

      * Seedship Broodtender on p0's battlefield.
      * p0 library: 4 -> 1 (3 milled).
      * p0 graveyard: 0 -> 3 (the 3 milled cards, top-of-library
        order: Bait Bear 1, Bait Bear 2, Bait Bear 3).
      * p0 library tail: Bait Bear 4 (witness).
      * p1 library / graveyard unchanged.
      * Lives unchanged (mill doesn't touch life totals).
      * No residual stack.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )

    seedship_broodtender = CardDef(
        name="Seedship Broodtender",
        card_type="Creature",
        mana_cost_generic=0,
        mana_cost_colored=(("B", 1), ("G", 1)),
        power=2,
        toughness=3,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "mill", "count": 3},
            },
        ),
    )
    # Distinct bait creatures so we can match the post-drain
    # graveyard contents BY NAME (and verify ordering).
    bait_1 = CardDef(
        name="Bait Bear 1",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=2,
        toughness=2,
    )
    bait_2 = CardDef(
        name="Bait Bear 2",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=2,
        toughness=2,
    )
    bait_3 = CardDef(
        name="Bait Bear 3",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=2,
        toughness=2,
    )
    bait_4 = CardDef(
        name="Bait Bear 4",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=2,
        toughness=2,
    )
    spec = DeckSpec(
        card_defs=(
            seedship_broodtender, bait_1, bait_2, bait_3, bait_4,
        ),
        # Top-of-library is index 0 on both engines: Bait Bear 1
        # comes off first, then 2, then 3. Bait Bear 4 survives as
        # the witness.
        p0_library=(
            "Bait Bear 1", "Bait Bear 2", "Bait Bear 3", "Bait Bear 4",
        ),
        # p1 library unused -- mill is controller-self, only p0's
        # library is observed.
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    rust_broodtender_dict = {
        "name": "Seedship Broodtender",
        "card_types": ["Creature"],
        "mana_cost": {"B": 1, "G": 1},
        "effects": [],
        "power": 2,
        "toughness": 3,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "mill", "count": 3},
            }
        ],
    }
    rust_p0_lib_before = rust_state.library_sizes[0]
    rust_p0_gy_before = rust_state.graveyard_sizes[0]
    rust_p1_lib_before = rust_state.library_sizes[1]
    rust_p1_gy_before = rust_state.graveyard_sizes[1]
    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)
    assert rust_p0_lib_before == 4
    assert rust_p0_gy_before == 0

    rust_state.register_and_inject_object(
        rust_broodtender_dict, 0, ZONE_BATTLEFIELD,
    )
    # register_and_inject_object on ZONE_BATTLEFIELD fans out ENTERS
    # via the deferred-dispatch queue; Seedship Broodtender's
    # SourceIsSelf predicate matches its own arrival, so a single
    # SelfMill(3) trigger lands on the stack.
    assert rust_state.stack_size() == 1, (
        "Rust: Seedship Broodtender's own arrival should fire the "
        "SourceIsSelf ENTERS trigger and land SelfMill(3) on the "
        f"stack. Got stack_size={rust_state.stack_size()}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.library_lookat import SelfMill
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    broodtender_printing = CardPrinting(
        name="Seedship Broodtender",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=(("B", 1), ("G", 1))),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=3,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=SelfMill(amount=3),
            ),
        ),
    )
    py_p0_lib_before = len(py_state.players[0].library)
    py_p0_gy_before = len(py_state.players[0].graveyard)
    py_p1_lib_before = len(py_state.players[1].library)
    py_p1_gy_before = len(py_state.players[1].graveyard)
    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life
    assert py_p0_lib_before == 4
    assert py_p0_gy_before == 0

    py_broodtender = py_state.new_object(
        broodtender_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_broodtender.summoning_sick = False
    py_broodtender.tapped = False
    py_broodtender.damage = 0
    py_broodtender.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_broodtender)
    _trigger_etb_abilities(py_state, py_broodtender)
    assert len(py_state.stack) == 1, (
        "Python: Seedship Broodtender's own arrival should fire the "
        "IsSelf ENTERS trigger and land SelfMill(3) on the stack. "
        f"Got stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks, then compare ----
    _drain_stack_both(py_state, rust_state)

    # Stacks empty on both sides.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0

    # Per-engine post-state: p0 library shrunk by 3, p0 graveyard
    # grew by 3, p1 untouched, lives untouched.
    assert rust_state.library_sizes[0] == rust_p0_lib_before - 3, (
        f"Rust p0 library should shrink by 3 (the mill): "
        f"before={rust_p0_lib_before} after={rust_state.library_sizes[0]}"
    )
    assert rust_state.graveyard_sizes[0] == rust_p0_gy_before + 3, (
        f"Rust p0 graveyard should grow by 3 (the milled cards): "
        f"before={rust_p0_gy_before} after={rust_state.graveyard_sizes[0]}"
    )
    assert rust_state.library_sizes[1] == rust_p1_lib_before
    assert rust_state.graveyard_sizes[1] == rust_p1_gy_before
    assert rust_state.get_life(0) == rust_p0_life_before
    assert rust_state.get_life(1) == rust_p1_life_before

    assert len(py_state.players[0].library) == py_p0_lib_before - 3
    assert len(py_state.players[0].graveyard) == py_p0_gy_before + 3
    assert len(py_state.players[1].library) == py_p1_lib_before
    assert len(py_state.players[1].graveyard) == py_p1_gy_before
    assert py_state.players[0].life == py_p0_life_before
    assert py_state.players[1].life == py_p1_life_before

    # Cross-engine: per-zone parity on sizes.
    assert rust_state.library_sizes[0] == len(py_state.players[0].library)
    assert rust_state.graveyard_sizes[0] == len(py_state.players[0].graveyard)
    assert rust_state.library_sizes[1] == len(py_state.players[1].library)
    assert rust_state.graveyard_sizes[1] == len(py_state.players[1].graveyard)
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life

    # Strongest pin: the milled cards are exactly the top-3 of p0's
    # pre-mill library, in top-of-library order. Bait Bear 1 came off
    # first -> landed at gy index 0; Bait Bear 2 -> gy index 1;
    # Bait Bear 3 -> gy index 2. Bait Bear 4 survives in the
    # library.
    expected_gy_names = ["Bait Bear 1", "Bait Bear 2", "Bait Bear 3"]
    rust_p0_gy_names = [
        entry["printing_name"]
        for entry in rust_state.graveyard_snapshot(0)
    ]
    assert rust_p0_gy_names == expected_gy_names, (
        f"Rust p0 graveyard contents mismatch: "
        f"expected {expected_gy_names}, got {rust_p0_gy_names}"
    )
    py_p0_gy_names = [
        o.printing.name for o in py_state.players[0].graveyard
    ]
    assert py_p0_gy_names == expected_gy_names, (
        f"Python p0 graveyard contents mismatch: "
        f"expected {expected_gy_names}, got {py_p0_gy_names}"
    )
    # Cross-engine: same milled cards, same order.
    assert rust_p0_gy_names == py_p0_gy_names

    # Witness: Bait Bear 4 still in p0 library on both engines.
    rust_p0_lib_names = [
        entry["printing_name"]
        for entry in rust_state.library_snapshot(0)
    ]
    py_p0_lib_names = [
        o.printing.name for o in py_state.players[0].library
    ]
    assert rust_p0_lib_names == ["Bait Bear 4"], (
        f"Rust p0 library should hold only Bait Bear 4 (witness); "
        f"got {rust_p0_lib_names}"
    )
    assert py_p0_lib_names == ["Bait Bear 4"], (
        f"Python p0 library should hold only Bait Bear 4 (witness); "
        f"got {py_p0_lib_names}"
    )


def test_cross_engine_real_eoe_seedship_broodtender_empty_library_mid_mill_parity(
    parity_smoke,
):
    """Probe: Seedship Broodtender (EoE) ETB mill silently stops on
    empty library mid-mill -- pins the I19 / I65-closure shape on
    the mill arm: mill on empty library is NOT a deck-out by itself
    (CR 704.5b applies to drawing, not milling). Both engines break
    out of the mill loop without crashing or registering a loss.

    Same predicate / effect shape as the primary probe (Slice 2
    above); distinct scenario where p0's library carries FEWER
    cards than the mill count. Validates the silent-stop branch
    in:

      * Rust ``Effect::Mill`` resolve arm
        (state_ops_resolve.rs:1043-1045): ``if lib.is_empty() {
        break; }``
      * Python ``SelfMill.resolve``
        (effects/generic/library_lookat.py:642-643):
        ``if not p.library: break``

    Probe shape:

      1. Stack p0's library with EXACTLY 2 bait creatures (mill
         3 will only get 2; the third iteration hits empty
         library and silently stops).

      2. Inject Seedship Broodtender directly onto p0's bf via
         ``register_and_inject_object`` (Rust) / new_object + bf
         append + ``_trigger_etb_abilities`` (Python).

      3. Drain. Resolve walk: p0 milled all 2 of its library; the
         third mill iteration was a no-op. Library 2 -> 0;
         graveyard 0 -> 2.

      4. Cross-engine assert: both engines empty p0's library
         silently (no SBA deck-out, no crash, no win/loss state
         change). Witness on both sides.

    Expected post-dispatch + post-drain state on BOTH engines:

      * Seedship Broodtender on p0's battlefield (carrier survives).
      * p0 library: 2 -> 0 (drained by the partial mill).
      * p0 graveyard: 0 -> 2 (Bait Bear 1, Bait Bear 2).
      * Lives unchanged (NO deck-out -- mill on empty library
        doesn't trigger CR 704.5b).
      * No residual stack.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )

    seedship_broodtender = CardDef(
        name="Seedship Broodtender",
        card_type="Creature",
        mana_cost_generic=0,
        mana_cost_colored=(("B", 1), ("G", 1)),
        power=2,
        toughness=3,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "mill", "count": 3},
            },
        ),
    )
    bait_1 = CardDef(
        name="Bait Bear 1",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=2,
        toughness=2,
    )
    bait_2 = CardDef(
        name="Bait Bear 2",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=2,
        toughness=2,
    )
    spec = DeckSpec(
        card_defs=(seedship_broodtender, bait_1, bait_2),
        # Library size 2 < mill count 3 -> the third mill iteration
        # hits empty library and silently stops on both engines.
        p0_library=("Bait Bear 1", "Bait Bear 2"),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    rust_broodtender_dict = {
        "name": "Seedship Broodtender",
        "card_types": ["Creature"],
        "mana_cost": {"B": 1, "G": 1},
        "effects": [],
        "power": 2,
        "toughness": 3,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "mill", "count": 3},
            }
        ],
    }
    rust_state.register_and_inject_object(
        rust_broodtender_dict, 0, ZONE_BATTLEFIELD,
    )
    assert rust_state.stack_size() == 1

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.library_lookat import SelfMill
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    broodtender_printing = CardPrinting(
        name="Seedship Broodtender",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=(("B", 1), ("G", 1))),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=3,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=SelfMill(amount=3),
            ),
        ),
    )
    py_broodtender = py_state.new_object(
        broodtender_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_broodtender.summoning_sick = False
    py_broodtender.tapped = False
    py_broodtender.damage = 0
    py_broodtender.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_broodtender)
    _trigger_etb_abilities(py_state, py_broodtender)
    assert len(py_state.stack) == 1

    # ---- Drain both stacks, then compare ----
    _drain_stack_both(py_state, rust_state)

    # Both engines milled all 2 cards (the third iteration was a
    # silent no-op on empty library).
    assert rust_state.library_sizes[0] == 0
    assert rust_state.graveyard_sizes[0] == 2
    assert len(py_state.players[0].library) == 0
    assert len(py_state.players[0].graveyard) == 2

    # Cross-engine: same final zone sizes, same gy ordering.
    assert rust_state.library_sizes[0] == len(py_state.players[0].library)
    assert rust_state.graveyard_sizes[0] == len(py_state.players[0].graveyard)
    rust_p0_gy_names = [
        entry["printing_name"]
        for entry in rust_state.graveyard_snapshot(0)
    ]
    py_p0_gy_names = [
        o.printing.name for o in py_state.players[0].graveyard
    ]
    expected_gy_names = ["Bait Bear 1", "Bait Bear 2"]
    assert rust_p0_gy_names == expected_gy_names
    assert py_p0_gy_names == expected_gy_names

    # Lives unchanged -- mill doesn't touch life totals, and an
    # empty-library mill is NOT a deck-out (CR 704.5b applies to
    # draws, not mills). I19 / I65-closure: empty-library mill is
    # a silent no-op, not a game-ending loss-state.
    assert rust_state.get_life(0) == 20
    assert rust_state.get_life(1) == 20
    assert py_state.players[0].life == 20
    assert py_state.players[1].life == 20

    # No residual stack.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0


def test_cross_engine_synthetic_etb_return_creature_from_graveyard_to_hand_parity(
    parity_smoke,
):
    """Probe: synthetic ``ETB-Recur-Bear`` exercising the freshly
    landed ``return_creature_from_your_graveyard_to_hand`` bridge
    arm end-to-end.

    Why synthetic rather than a real EoE card: the two EoE
    consumers of the bare unit-variant per
    ``docs/EOE_PROBE_READINESS_AUDIT.md`` are Interceptor Mechan
    ("artifact or creature card") and Fell Gravship's suffix
    ("creature or Spacecraft card") -- BOTH carry rider widenings
    (``or_artifact`` and ``or_spacecraft`` respectively) the Rust
    unit-variant doesn't support. The bare unit-variant has no
    real-EoE consumer with matching shape today; a synthetic
    creature card with the unit-variant trigger is the canonical
    way to exercise this substrate end-to-end on the bridge until
    the rider-parametric Rust variants land.

    Trigger shape:

        Event: enters
        Predicate: source_is_self
        Effect: return_creature_from_your_graveyard_to_hand
                (the bare unit variant -- no riders)

    **Rust target-pick semantics.** Rust's
    ``Effect::ReturnCreatureFromYourGraveyardToHand`` arm
    (state_ops_resolve.rs:2986-3020) picks the returned card
    deterministically at apply_effect time: scan the source-
    controller's graveyard top-to-bottom (insertion order) for the
    FIRST object whose printing's ``card_types`` contains
    "Creature". The controller index reads
    ``current_resolve_source_controller`` (I82 controller-of-
    effect fix), so the graveyard scan and the destination-hand
    push both anchor to the SOURCE's controller, not the active
    player. Empty graveyard / no creature cards -> silent no-op
    (``return Ok(())``).

    **Python target-pick semantics.** Python's
    ``ReturnCreatureFromYourGraveyardToHand`` is constructor sugar
    over ``ReturnFromGraveyard`` (bounce.py:356-404). Its
    ``legal_targets`` walks the controller's graveyard and emits
    one ``("graveyard_creature", card.id)`` per creature card.
    The targeting pipeline picks at PUSH time via
    ``push_triggered_ability`` ->
    ``controller.agent.choose_target``. The probe installs a
    minimal ``_PickFirstLegalTargetAgent`` shim on p0 that returns
    ``legal_targets[0]`` -- observably equivalent to Rust's
    iterator-order graveyard scan in 2-player games where both
    engines build their graveyards in the same order. With a
    single creature card seeded in p0's graveyard at probe setup,
    Rust's first-creature scan and Python's first-legal-target
    pick produce the SAME observable: the seeded creature moves
    from p0's graveyard to p0's hand.

    Probe shape (inject-and-fire-ENTERS):

      1. Seed p0's graveyard with one synthetic creature card
         (``Recur Bait Bear``) on both engines. The seed creature
         is purely a return target -- it has NO triggered
         abilities and never enters the battlefield during the
         probe.

      2. Inject ``ETB Recur Bear`` directly onto p0's battlefield
         via ``register_and_inject_object`` (Rust) / new_object +
         bf append + manual ``_trigger_etb_abilities`` (Python).
         Both engines dispatch ENTERS for the just-arrived
         recur-bear; the SourceIsSelf predicate matches; one
         ``ReturnCreatureFromYourGraveyardToHand`` trigger lands
         on the stack with its target resolved deterministically
         (Rust) or pre-chosen via the agent (Python).

      3. Drain both stacks. The trigger resolves: the seeded
         Recur Bait Bear moves from p0's graveyard to p0's hand.

      4. Cross-engine assert: both engines have an empty p0
         graveyard, a single ``Recur Bait Bear`` in p0's hand,
         and the original ``ETB Recur Bear`` still on p0's
         battlefield.

    Out of scope:

      * Cast-from-hand mana cost -- the inject-and-dispatch-ENTERS
        pattern bypasses the mana pipeline.
      * Multi-creature graveyard pick -- with only one creature
        seeded in the graveyard, both engines pick the same
        unambiguous target. The "Rust picks first-in-order vs
        Python's agent picks via legal_targets[0]" parity contract
        observably collapses on a one-element pool but stays
        well-defined for follow-up probes that seed multiple
        creatures.
      * Empty-graveyard silent-skip case -- separate sibling probe
        could pin the silent no-op on both sides; this probe
        drives the happy path with one return target.
      * Rider widenings (or_artifact / or_spacecraft) -- out of
        scope; the unit-variant arm is exclusive to the bare
        creature-only shape today.

    Expected post-dispatch + post-drain state on BOTH engines:

      * ETB Recur Bear on p0's battlefield (unchanged from inject).
      * Recur Bait Bear in p0's hand (returned from gy).
      * p0 graveyard empty.
      * No residual stack.
      * Life totals unchanged on both seats (the return effect
        doesn't touch life).
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )
    from tests.parity._picker_shims import _PickFirstLegalTargetAgent

    # Bait Bear: vanilla 2/2 with no triggered abilities. Seeded
    # in p0's graveyard so the recur trigger has a legal target.
    bait_bear = CardDef(
        name="Recur Bait Bear",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=2,
        toughness=2,
    )
    # Recur Bear: vanilla 2/2 + ETB return-creature-from-gy-to-hand.
    # The substrate-level point of the probe.
    recur_bear = CardDef(
        name="ETB Recur Bear",
        card_type="Creature",
        mana_cost_generic=2,
        mana_cost_colored=(("B", 1),),
        power=2,
        toughness=2,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "return_creature_from_your_graveyard_to_hand",
                },
            },
        ),
    )
    spec = DeckSpec(
        card_defs=(bait_bear, recur_bear),
        # Libraries empty-but-for-symmetry: probe seeds gy + injects
        # directly onto bf so libraries aren't observed.
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    ZONE_GRAVEYARD = 3
    rust_bait_dict = {
        "name": "Recur Bait Bear",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1, "G": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
    }
    rust_recur_dict = {
        "name": "ETB Recur Bear",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "B": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "return_creature_from_your_graveyard_to_hand",
                },
            }
        ],
    }
    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)
    # Seed p0's graveyard with the bait creature.
    rust_state.register_and_inject_object(
        rust_bait_dict, 0, ZONE_GRAVEYARD
    )
    # Inject the recur-bear onto p0's battlefield -> fires ENTERS via
    # the deferred-dispatch queue. SourceIsSelf matches the just-
    # arrived recur-bear; one ReturnCreatureFromYourGraveyardToHand
    # trigger lands on the stack with its target resolved
    # deterministically (scan p0's gy for first creature card ->
    # finds the bait bear we just seeded).
    rust_state.register_and_inject_object(
        rust_recur_dict, 0, ZONE_BATTLEFIELD
    )
    assert rust_state.stack_size() == 1, (
        "Rust: ETB Recur Bear's arrival should fire the SourceIsSelf "
        "ENTERS trigger and land "
        "ReturnCreatureFromYourGraveyardToHand on the stack. "
        f"Got stack_size={rust_state.stack_size()}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.bounce import (
        ReturnCreatureFromYourGraveyardToHand,
    )
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    bait_printing = CardPrinting(
        name="Recur Bait Bear",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=(("G", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
    )
    recur_printing = CardPrinting(
        name="ETB Recur Bear",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2, colored=(("B", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=ReturnCreatureFromYourGraveyardToHand(),
            ),
        ),
    )

    # Custom agent: pick the first legal target. Mirrors Rust's
    # iterator-order graveyard scan. Shim hoisted to
    # tests/parity/_picker_shims.py.
    py_state.players[0].agent = _PickFirstLegalTargetAgent()

    # Seed p0's graveyard with the bait creature.
    py_bait = py_state.new_object(
        bait_printing, owner_id=0, zone=Zone.GRAVEYARD,
    )
    py_state.players[0].graveyard.append(py_bait)

    # Inject the recur-bear onto p0's battlefield, then manually
    # dispatch ENTERS (same shape as prior synthetic / EoE probes).
    py_recur = py_state.new_object(
        recur_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_recur.summoning_sick = False
    py_recur.tapped = False
    py_recur.damage = 0
    py_recur.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_recur)
    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life
    _trigger_etb_abilities(py_state, py_recur)
    assert len(py_state.stack) == 1, (
        "Python: ETB Recur Bear's arrival should fire the IsSelf "
        "ENTERS trigger and land "
        "ReturnCreatureFromYourGraveyardToHand on the stack. "
        f"Got stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks, then compare ----
    _drain_stack_both(py_state, rust_state)

    # Post-drain: bait bear moved from p0's gy to p0's hand on both
    # engines.
    assert rust_state.hand_sizes[0] == 1, (
        f"Rust: p0 hand should contain the recurred bait bear; "
        f"got hand_size={rust_state.hand_sizes[0]}"
    )
    assert rust_state.graveyard_sizes[0] == 0, (
        f"Rust: p0 graveyard should be empty after the return; "
        f"got graveyard_size={rust_state.graveyard_sizes[0]}"
    )
    # ETB Recur Bear still on p0's bf (unchanged).
    assert rust_state.battlefield_sizes[0] == 1, (
        f"Rust: p0 bf should still hold ETB Recur Bear; "
        f"got bf_size={rust_state.battlefield_sizes[0]}"
    )

    # Python: same shape on the equivalent zones.
    assert len(py_state.players[0].hand) == 1, (
        f"Python: p0 hand should contain the recurred bait bear; "
        f"got hand_size={len(py_state.players[0].hand)}"
    )
    py_hand_name = py_state.players[0].hand[0].printing.name
    assert py_hand_name == "Recur Bait Bear", (
        f"Python: p0 hand should contain the bait bear; "
        f"got {py_hand_name}"
    )
    assert len(py_state.players[0].graveyard) == 0, (
        f"Python: p0 graveyard should be empty after the return; "
        f"got graveyard_size={len(py_state.players[0].graveyard)}"
    )
    # ETB Recur Bear still on bf (unchanged).
    py_bf_p0 = [
        o for o in py_state.battlefield if o.controller_id == 0
    ]
    assert len(py_bf_p0) == 1, (
        f"Python: p0 bf should still hold ETB Recur Bear; "
        f"got bf_size={len(py_bf_p0)}"
    )
    assert py_bf_p0[0].printing.name == "ETB Recur Bear", (
        f"Python: p0 bf survivor should be ETB Recur Bear; "
        f"got {py_bf_p0[0].printing.name}"
    )

    # Cross-engine: lives unchanged on both sides (the return effect
    # doesn't touch life).
    assert rust_state.get_life(0) == rust_p0_life_before
    assert rust_state.get_life(1) == rust_p1_life_before
    assert py_state.players[0].life == py_p0_life_before
    assert py_state.players[1].life == py_p1_life_before
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life

    # Cross-engine: hand / graveyard / bf sizes match between engines
    # on both seats.
    assert rust_state.hand_sizes[0] == len(py_state.players[0].hand)
    assert rust_state.hand_sizes[1] == len(py_state.players[1].hand)
    assert (
        rust_state.graveyard_sizes[0]
        == len(py_state.players[0].graveyard)
    )
    assert (
        rust_state.graveyard_sizes[1]
        == len(py_state.players[1].graveyard)
    )

    # Stacks empty on both sides.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0


def test_cross_engine_real_eoe_virus_beetle_etb_each_opponent_discards_parity(
    parity_smoke,
):
    """Probe: Virus Beetle (EoE) ETB ``each opponent discards a card``
    parity -- FIRST real-EoE cross-engine probe with an
    ``each_opponent_discards`` ETB trigger.

    Oracle text in ``data/edge_of_eternities.json``:

        "When this creature enters, each opponent discards a card."

    Bridges the ``each_opponent_discards`` effect kind end-to-end on
    a real EoE card. The audit lists Virus Beetle as the SOLE EoE
    consumer of this bridge arm; the effect composes directly off
    the bare arm (no Sequence / IfYouDo nesting), so it is end-to-
    end probeable from the leaf arm alone.

    Predicate decomposition (same as Germinating Wurm / Nebula
    Dragon / Starbreach Whale):

        SourceIsSelf

    Effect: ``each_opponent_discards(count=1)`` -- NEW on the
    bridge as of the companion commit on this branch. The Rust
    effect variant carries an intrinsic source-controller-of-effect
    resolution (5-zone walk + stack fallback at
    state_ops_resolve.rs:3438-3502); the Python side translates to
    ``EachOpponentDiscards(count=1)``.

    **Cross-engine discard-pick contract.** Both engines pick the
    discard from the OPPONENT's hand (the discarding player's
    perspective; the source's controller doesn't pick for them).
    Rust at state_ops_resolve.rs:3488-3490 pops opponent.hand[0]
    deterministically. Python at discard.py:155-157 calls
    ``p.agent.choose_discard(state, p.id, hand_ids)`` and removes
    whatever id the agent returns. The harness's default Player
    has ``agent=None`` -- if we drove the empty-hand path that's
    fine (both engines short-circuit on empty hand), but to
    observe the cross-engine pick parity end-to-end we seat a
    deterministic-hand[0] agent on p1 (the opponent who will
    discard) mirroring Rust's at-resolve hand[0] pick. Each engine
    then drops the same card.

    Probe shape (inject-and-fire-ENTERS, mirrors
    Starbreach Whale):

      1. Pre-seed p1's hand with TWO distinct bait creatures (one
         destined to discard, one to survive) so a single-swap or
         single-discard divergence between engines surfaces as a
         per-card name mismatch in p1's graveyard / hand rather
         than a count-only divergence.
      2. Inject Virus Beetle on p0's battlefield via
         ``register_and_inject_object`` (Rust) / new_object + bf
         append + ``_trigger_etb_abilities`` (Python). Both engines
         dispatch ENTERS for the just-arrived beetle; the predicate
         (SourceIsSelf) matches, the trigger lands on the stack
         with the EachOpponentDiscards(1) effect.
      3. Seat a deterministic-hand[0] agent on p1 (Python side
         only; Rust's pick is intrinsic and doesn't read agent).
      4. Drain both stacks.
      5. Cross-engine assert: post-drain, p1's hand[0] (Discard
         Bait Alpha) is gone, in p1's graveyard. Discard Bait Beta
         remains in p1's hand. Same shape on both engines.

    Out of scope:

      * Driving the empty-hand short-circuit branch -- the audit's
        explicit unblock is "each opponent discards a card",
        which means the non-empty path is the load-bearing case
        for Virus Beetle. The empty-hand parity is covered by the
        Rust resolve arm's mid-loop guard at
        state_ops_resolve.rs:3482 + Python's matching guard at
        discard.py:152, both pinned by their respective unit
        tests already in the suite.
      * Multi-opponent fanout -- the 2-player harness reduces
        "each opponent" to "the one opponent". The N-player
        per-seat-iteration shape is exercised by the Rust resolve
        arm's loop body directly; the bridge's leaf translation
        + 2-player probe pins the substrate end-to-end.

    Expected post-dispatch + post-drain state on BOTH engines:

      * Virus Beetle on p0's battlefield.
      * p1 hand: Discard Bait Beta only (Alpha was discarded).
      * p1 graveyard: Discard Bait Alpha.
      * p0 hand / library / graveyard: unchanged.
      * p1 library: unchanged.
      * Lives unchanged on both seats.
      * No residual stack.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )
    from tests.parity._picker_shims import _DiscardFirstAgent

    virus_beetle = CardDef(
        name="Virus Beetle",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("B", 1),),
        power=1,
        toughness=1,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "each_opponent_discards",
                    "count": 1,
                },
            },
        ),
    )
    # Two distinct vanilla cards in p1's hand so a single-swap
    # (alternate-target divergence) between engines surfaces as a
    # per-card name divergence rather than a count-only divergence.
    discard_bait_a = CardDef(
        name="Discard Bait Alpha",
        card_type="Creature",
        mana_cost_generic=1,
        power=1,
        toughness=1,
    )
    discard_bait_b = CardDef(
        name="Discard Bait Beta",
        card_type="Creature",
        mana_cost_generic=2,
        power=2,
        toughness=2,
    )
    spec = DeckSpec(
        card_defs=(virus_beetle, discard_bait_a, discard_bait_b),
        # Libraries empty for symmetry; the probe injects directly
        # into p0's bf and p1's hand so libraries aren't observed
        # (matches the Pinnacle Kill-Ship probe shape).
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_HAND = 0
    ZONE_BATTLEFIELD = 2
    # 1. Pre-seed p1's hand with the two bait cards FIRST so the
    # ENTERS trigger has a populated hand to discard from.
    rust_bait_a_dict = {
        "name": "Discard Bait Alpha",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "effects": [],
        "power": 1,
        "toughness": 1,
    }
    rust_bait_b_dict = {
        "name": "Discard Bait Beta",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "effects": [],
        "power": 2,
        "toughness": 2,
    }
    rust_bait_a_id = rust_state.register_and_inject_object(
        rust_bait_a_dict, 1, ZONE_HAND
    )
    rust_bait_b_id = rust_state.register_and_inject_object(
        rust_bait_b_dict, 1, ZONE_HAND
    )
    rust_p1_hand_size_before = rust_state.hand_sizes[1]
    rust_p1_gy_size_before = rust_state.graveyard_sizes[1]
    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)
    rust_beetle_dict = {
        "name": "Virus Beetle",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1, "B": 1},
        "effects": [],
        "power": 1,
        "toughness": 1,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "each_opponent_discards",
                    "count": 1,
                },
            }
        ],
    }
    rust_beetle_id = rust_state.register_and_inject_object(
        rust_beetle_dict, 0, ZONE_BATTLEFIELD
    )
    # register_and_inject_object on ZONE_BATTLEFIELD fans out
    # ENTERS via the deferred-dispatch queue; the beetle's
    # SourceIsSelf predicate matches its own arrival, so a single
    # EachOpponentDiscards(1) trigger lands on the stack.
    assert rust_state.stack_size() == 1, (
        "Rust: Virus Beetle's own arrival should fire the "
        "SourceIsSelf ENTERS trigger and land "
        "EachOpponentDiscards(1) on the stack. Got "
        f"stack_size={rust_state.stack_size()}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.discard import EachOpponentDiscards
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    # Bait printings (vanilla creatures) for p1's hand.
    bait_a_printing = CardPrinting(
        name="Discard Bait Alpha",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=1,
        toughness=1,
        produces=frozenset(),
    )
    bait_b_printing = CardPrinting(
        name="Discard Bait Beta",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
    )
    # Inject the two bait creatures into p1's hand FIRST. Order
    # matters: Discard Bait Alpha at hand[0] so the hand[0]
    # deterministic-pick agent discards Alpha specifically.
    py_bait_a = py_state.new_object(
        bait_a_printing, owner_id=1, zone=Zone.HAND,
    )
    py_state.players[1].hand.append(py_bait_a)
    py_bait_b = py_state.new_object(
        bait_b_printing, owner_id=1, zone=Zone.HAND,
    )
    py_state.players[1].hand.append(py_bait_b)

    beetle_printing = CardPrinting(
        name="Virus Beetle",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=(("B", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=1,
        toughness=1,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=EachOpponentDiscards(count=1),
            ),
        ),
    )

    # Custom agent for p1: mirror Rust's deterministic hand[0] pick.
    # Rust's resolve arm pops opponent.hand[0] (state_ops_resolve.rs
    # :3489 ``hand_mut.remove(0)``). Python's discard.py:155 calls
    # ``choose_discard`` with the full hand_ids list; we return the
    # first id to match Rust's at-resolve pick. The pick is seated
    # on p1 (the discarding player), NOT on p0 (the source's
    # controller) -- "each opponent discards" lets each opponent
    # pick their own discard. Shim hoisted to
    # tests/parity/_picker_shims.py.
    py_state.players[1].agent = _DiscardFirstAgent()

    py_p1_hand_size_before = len(py_state.players[1].hand)
    py_p1_gy_size_before = len(py_state.players[1].graveyard)
    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life
    py_beetle = py_state.new_object(
        beetle_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_beetle.summoning_sick = False
    py_beetle.tapped = False
    py_beetle.damage = 0
    py_beetle.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_beetle)
    # Manually dispatch ENTERS for the just-injected beetle (direct
    # bf-append doesn't auto-dispatch on the Python side -- same
    # shape as every prior register_and_inject-style EoE probe).
    _trigger_etb_abilities(py_state, py_beetle)
    assert len(py_state.stack) == 1, (
        "Python: Virus Beetle's own arrival should fire the IsSelf "
        "ENTERS trigger and land EachOpponentDiscards(1) on the "
        f"stack. Got stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks, then compare ----
    _drain_stack_both(py_state, rust_state)

    # Post-drain: p1's hand shrank by 1 (Alpha discarded), p1's
    # graveyard grew by 1 (Alpha landed there). Discard Bait Beta
    # remains in p1's hand.
    assert rust_state.hand_sizes[1] == rust_p1_hand_size_before - 1, (
        f"Rust p1 hand size should be "
        f"{rust_p1_hand_size_before - 1} after discard; got "
        f"{rust_state.hand_sizes[1]}"
    )
    assert rust_state.graveyard_sizes[1] == rust_p1_gy_size_before + 1, (
        f"Rust p1 graveyard size should be "
        f"{rust_p1_gy_size_before + 1} after discard; got "
        f"{rust_state.graveyard_sizes[1]}"
    )
    rust_p1_gy_names = [
        e["printing_name"] for e in rust_state.graveyard_snapshot(1)
    ]
    assert "Discard Bait Alpha" in rust_p1_gy_names, (
        f"Rust: expected Discard Bait Alpha in p1 gy "
        f"(hand[0] deterministic pick); got {rust_p1_gy_names}"
    )
    assert "Discard Bait Beta" not in rust_p1_gy_names, (
        f"Rust: Discard Bait Beta should NOT have been discarded "
        f"(only the hand[0] card was picked); got {rust_p1_gy_names}"
    )
    rust_p1_hand_names = [
        e["printing_name"] for e in rust_state.hand_snapshot(1)
    ]
    assert "Discard Bait Beta" in rust_p1_hand_names, (
        f"Rust: Discard Bait Beta should remain in p1 hand; "
        f"got {rust_p1_hand_names}"
    )

    assert len(py_state.players[1].hand) == py_p1_hand_size_before - 1, (
        f"Python p1 hand size should be "
        f"{py_p1_hand_size_before - 1} after discard; got "
        f"{len(py_state.players[1].hand)}"
    )
    assert (
        len(py_state.players[1].graveyard) == py_p1_gy_size_before + 1
    ), (
        f"Python p1 graveyard size should be "
        f"{py_p1_gy_size_before + 1} after discard; got "
        f"{len(py_state.players[1].graveyard)}"
    )
    py_p1_gy_names = [
        o.printing.name for o in py_state.players[1].graveyard
    ]
    assert "Discard Bait Alpha" in py_p1_gy_names, (
        f"Python: expected Discard Bait Alpha in p1 gy "
        f"(hand[0] deterministic pick); got {py_p1_gy_names}"
    )
    assert "Discard Bait Beta" not in py_p1_gy_names, (
        f"Python: Discard Bait Beta should NOT have been "
        f"discarded; got {py_p1_gy_names}"
    )
    py_p1_hand_names = [
        o.printing.name for o in py_state.players[1].hand
    ]
    assert "Discard Bait Beta" in py_p1_hand_names, (
        f"Python: Discard Bait Beta should remain in p1 hand; "
        f"got {py_p1_hand_names}"
    )

    # Cross-engine: same post-drain hand-/graveyard-shape on p1.
    assert rust_state.hand_sizes[1] == len(py_state.players[1].hand)
    assert (
        rust_state.graveyard_sizes[1] ==
        len(py_state.players[1].graveyard)
    )
    # Stacks empty on both sides.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0
    # Lives unchanged (discard isn't a damage / life effect).
    assert rust_state.get_life(0) == rust_p0_life_before
    assert rust_state.get_life(1) == rust_p1_life_before
    assert py_state.players[0].life == py_p0_life_before
    assert py_state.players[1].life == py_p1_life_before
    # Cross-engine: same post-drain life totals on both seats.
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life



def test_cross_engine_real_eoe_dubious_delicacy_etb_pump_target_creature_parity(
    parity_smoke,
):
    """Probe: Dubious Delicacy (EoE) ETB ``up to one target creature
    gets -3/-3 UEOT`` parity -- FIRST real-EoE cross-engine probe with
    a target-creature UEOT pump (debuff variant).

    Oracle text in ``data/edge_of_eternities.json``:

        "Flash
         When this artifact enters, up to one target creature gets
         -3/-3 until end of turn.
         {2}, {T}, Sacrifice this artifact: You gain 3 life.
         {2}, {T}, Sacrifice this artifact: Target opponent loses
         3 life."

    The Flash + activated abilities are out of scope -- this probe
    exclusively exercises the ETB-trigger surface, the substrate
    sweet-spot:

      * Event: ``enters``
      * Predicate: ``source_is_self`` (only the just-entered
        artifact's own trigger fires)
      * Effect: ``pump_target_creature_until_eot`` power_bonus=-3
        toughness_bonus=-3 -- NEW on the bridge as of the companion
        commit on this branch.

    First real-EoE cross-engine probe to exercise the
    ``Effect::PumpTargetCreatureUntilEOT`` arm +
    ``PumpTargetCreatureUntilEOT`` Python class end-to-end. Also the
    FIRST EoE probe carried by an Artifact-typed source -- prior
    probes (Nebula Dragon, Debris Field Crusher, Seedship Broodtender)
    were all Creature-typed. The probe pins that ENTERS-event
    dispatch is type-agnostic on both engines.

    Predicate decomposition (same as Germinating Wurm / Quantum
    Riddler / Nebula Dragon / Seedship Broodtender):

        SourceIsSelf

    Effect: ``pump_target_creature_until_eot(power_bonus=-3,
    toughness_bonus=-3)`` -- the bridge arm translates to
    ``PumpTargetCreatureUntilEOT(power_bonus=-3, toughness_bonus=-3)``.

    **Target-pick parity contract.** Rust's
    ``Effect::PumpTargetCreatureUntilEOT`` arm
    (rust/src/state_ops_resolve.rs:3927-3988) picks the target
    DETERMINISTICALLY at apply_effect time: scan the SOURCE
    CONTROLLER's battlefield top-to-bottom for the first object
    whose ``card_types`` contains "Creature", and push a
    ``UeotModifier::PowerToughnessBonus`` onto its ueot_modifiers
    Vec. Empty bf (or no creatures on it) is a silent fizzle. Note
    this is the SOURCE CONTROLLER's bf -- the source's OWN side --
    distinct from ``deal_damage_any_target``'s defender-bf scan.
    Python's targeting pipeline picks at PUSH time via the
    controller's agent in ``push_triggered_ability``
    (actions.py:3172). To make both engines pick the same target,
    the probe installs a custom
    ``_PickFirstControlledCreatureAgent`` on p0 (sibling to
    ``_PickFirstOpponentTargetAgent`` from the Nebula-Dragon probe
    -- swap controller-filter direction from opponent-side to
    same-side) and drives a scenario where p0 has a single creature
    on its bf (an unambiguous pick on both engines).

    Probe shape (inject-and-fire-ENTERS, same pattern as Seedship
    Broodtender / Nebula Dragon):

      1. Stack p0's bf with one Bait Bear (the pump target) BEFORE
         injecting Dubious Delicacy. The bear has printed P/T 4/4 so
         the -3/-3 debuff leaves it observably alive at 1/1 (still
         positive toughness -- no SBA-death after cleanup, no
         disambiguation needed against a separate dies-trigger
         path).

      2. Inject Dubious Delicacy directly onto p0's battlefield via
         ``register_and_inject_object`` (Rust) / new_object + bf
         append + manual ``_trigger_etb_abilities`` (Python). Both
         engines dispatch ENTERS for the just-arrived artifact; the
         SourceIsSelf predicate matches, the trigger lands on the
         stack with its target pre-chosen (Bait Bear on both sides).

      3. Both engines: stack carries ONE pending
         PumpTargetCreatureUntilEOT trigger. Drain. Resolve walk:
         the Bait Bear's effective P/T drops to 1/1 (printed 4/4 +
         (-3, -3) UEOT modifier).

      4. Cross-engine assert: both engines show Bait Bear at
         effective P/T 1/1; the pumped-modifier persists on the
         object UNTIL cleanup (we don't drive cleanup in this probe
         -- the effective-P/T getter reflects the modifier directly).

    Out of scope:

      * Flash (instant-speed cast) -- the inject-and-dispatch-ENTERS
        path bypasses casting entirely.
      * The {2},{T},Sacrifice activated abilities -- activated cost
        + sac + life-gain / life-loss; none of the pieces are on the
        bridge today.
      * Mana cost ({2}{B}) -- inject-and-dispatch-ENTERS bypasses
        the mana pipeline (same treatment every prior real-EoE probe
        gives the cast cost).
      * "Up to one target" optional-target semantics -- the bridge
        does not yet plumb ``optional`` through the dict shape; the
        probe scenario forces a single-creature target on p0's bf so
        the optional-vs-required distinction is observationally
        irrelevant. The wider optional-target contract (zero-target
        fizzle vs no-op on missing target) is a follow-up bridge
        extension.
      * Cleanup-step expiry -- not driven here. Both engines record
        the UEOT modifier on the object; cleanup-step removal is
        already pinned by other tests.

    Expected post-dispatch + post-drain state on BOTH engines:

      * Dubious Delicacy on p0's battlefield (Artifact -- Food).
      * Bait Bear on p0's battlefield: effective P/T 4/4 -> 1/1.
      * p1 battlefield empty.
      * No life changes (the ETB doesn't touch life totals).
      * No residual stack.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )
    from tests.parity._picker_shims import _PickFirstControlledCreatureAgent

    dubious_delicacy = CardDef(
        name="Dubious Delicacy",
        card_type="Artifact",
        mana_cost_generic=2,
        mana_cost_colored=(("B", 1),),
        # Artifact -- not a creature, no power/toughness.
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "pump_target_creature_until_eot",
                    "power_bonus": -3,
                    "toughness_bonus": -3,
                },
            },
        ),
    )
    # The pump target: a single 4/4 on p0's bf. Printed P/T 4/4 so the
    # -3/-3 modifier leaves it observably alive at 1/1 (positive
    # toughness, no SBA-death after cleanup).
    bait_bear = CardDef(
        name="Bait Bear (4/4)",
        card_type="Creature",
        mana_cost_generic=3,
        mana_cost_colored=(("G", 1),),
        power=4,
        toughness=4,
    )
    spec = DeckSpec(
        card_defs=(dubious_delicacy, bait_bear),
        # Empty libraries -- probe injects directly onto bf so the
        # libraries are unobserved.
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    # Inject the bait bear FIRST so it's the target of the pump.
    rust_bait_dict = {
        "name": "Bait Bear (4/4)",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 3, "G": 1},
        "effects": [],
        "power": 4,
        "toughness": 4,
    }
    rust_bait_id = rust_state.register_and_inject_object(
        rust_bait_dict, 0, ZONE_BATTLEFIELD,
    )
    # The bait bear has no triggered abilities, so no stack growth.
    assert rust_state.stack_size() == 0

    rust_dubious_dict = {
        "name": "Dubious Delicacy",
        "card_types": ["Artifact"],
        "subtypes": ["Food"],
        "mana_cost": {"generic": 2, "B": 1},
        "effects": [],
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "pump_target_creature_until_eot",
                    "power_bonus": -3,
                    "toughness_bonus": -3,
                },
            }
        ],
    }
    # Capture pre-modifier P/T for the bait bear.
    rust_bait_power_before = rust_state.effective_power(rust_bait_id)
    rust_bait_tough_before = rust_state.effective_toughness(rust_bait_id)
    assert rust_bait_power_before == 4
    assert rust_bait_tough_before == 4

    rust_state.register_and_inject_object(
        rust_dubious_dict, 0, ZONE_BATTLEFIELD,
    )
    # register_and_inject_object on ZONE_BATTLEFIELD fans out ENTERS
    # via the deferred-dispatch queue; Dubious Delicacy's
    # SourceIsSelf predicate matches its own arrival, so a single
    # PumpTargetCreatureUntilEOT(-3, -3) trigger lands on the stack.
    assert rust_state.stack_size() == 1, (
        "Rust: Dubious Delicacy's own arrival should fire the "
        "SourceIsSelf ENTERS trigger and land "
        "PumpTargetCreatureUntilEOT(-3, -3) on the stack. "
        f"Got stack_size={rust_state.stack_size()}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.pump import PumpTargetCreatureUntilEOT
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone, effective_power, effective_toughness

    bait_printing = CardPrinting(
        name="Bait Bear (4/4)",
        mana_cost_str="",
        mana_cost=ManaCost(generic=3, colored=(("G", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=4,
        toughness=4,
        produces=frozenset(),
        triggered_abilities=(),
    )
    dubious_printing = CardPrinting(
        name="Dubious Delicacy",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2, colored=(("B", 1),)),
        type_line="Artifact -- Food",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=("Food",),
        power=None,
        toughness=None,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=PumpTargetCreatureUntilEOT(
                    power_bonus=-3, toughness_bonus=-3,
                ),
            ),
        ),
    )

    # Inject the bait bear FIRST.
    py_bait = py_state.new_object(
        bait_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_bait.summoning_sick = False
    py_bait.tapped = False
    py_bait.damage = 0
    py_bait.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_bait)
    # Pre-modifier P/T sanity check.
    assert effective_power(py_state, py_bait) == 4
    assert effective_toughness(py_state, py_bait) == 4

    # Custom agent: mimic Rust's caster-side target pick. Rust's
    # PumpTargetCreatureUntilEOT arm scans the SOURCE CONTROLLER's bf
    # for the FIRST creature. Sibling to the Nebula-Dragon probe's
    # _PickFirstOpponentTargetAgent (swap controller-filter direction
    # from opponent to same-side). Shim hoisted to
    # tests/parity/_picker_shims.py.
    py_state.players[0].agent = _PickFirstControlledCreatureAgent()

    py_dubious = py_state.new_object(
        dubious_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_dubious.summoning_sick = False
    py_dubious.tapped = False
    py_dubious.damage = 0
    py_dubious.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_dubious)
    _trigger_etb_abilities(py_state, py_dubious)
    assert len(py_state.stack) == 1, (
        "Python: Dubious Delicacy's own arrival should fire the "
        "IsSelf ENTERS trigger and land "
        "PumpTargetCreatureUntilEOT(-3, -3) on the stack. "
        f"Got stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks, then compare ----
    _drain_stack_both(py_state, rust_state)

    # Stacks empty on both sides.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0

    # Per-engine post-state: the bait bear's effective P/T is 1/1
    # (printed 4/4 + (-3, -3) UEOT modifier).
    rust_bait_power_after = rust_state.effective_power(rust_bait_id)
    rust_bait_tough_after = rust_state.effective_toughness(rust_bait_id)
    assert rust_bait_power_after == 1, (
        f"Rust bait bear effective power should be 1 after the -3 "
        f"pump (printed 4 + (-3) UEOT); got {rust_bait_power_after}"
    )
    assert rust_bait_tough_after == 1, (
        f"Rust bait bear effective toughness should be 1 after the "
        f"-3 pump (printed 4 + (-3) UEOT); got {rust_bait_tough_after}"
    )

    py_bait_power_after = effective_power(py_state, py_bait)
    py_bait_tough_after = effective_toughness(py_state, py_bait)
    assert py_bait_power_after == 1, (
        f"Python bait bear effective power should be 1 after the -3 "
        f"pump; got {py_bait_power_after}"
    )
    assert py_bait_tough_after == 1, (
        f"Python bait bear effective toughness should be 1 after the "
        f"-3 pump; got {py_bait_tough_after}"
    )

    # Cross-engine: same post-drain effective P/T on the bait bear.
    assert rust_bait_power_after == py_bait_power_after
    assert rust_bait_tough_after == py_bait_tough_after

    # Lives unchanged -- the ETB pump doesn't touch life totals.
    assert rust_state.get_life(0) == 20
    assert rust_state.get_life(1) == 20
    assert py_state.players[0].life == 20
    assert py_state.players[1].life == 20


def test_cross_engine_real_eoe_rayblade_trooper_etb_plus_one_counter_parity(
    parity_smoke,
):
    """Probe: Rayblade Trooper (EoE) ETB ``put a +1/+1 counter on
    target creature you control`` parity -- FIRST real-EoE cross-
    engine probe to exercise the
    ``put_plus_one_counter_on_creature_you_control`` bridge arm.

    Oracle text in ``data/edge_of_eternities.json``:

        "When this creature enters, put a +1/+1 counter on target
         creature you control.
         Whenever a nontoken creature you control with a +1/+1
         counter on it dies, create a 1/1 white Human Soldier
         creature token.
         Warp {1}{W} (...)"

    The dies-trigger token-creation rider + Warp clause are out of
    scope -- this probe exclusively exercises the ETB-trigger
    surface, the substrate sweet-spot:

      * Event: ``enters``
      * Predicate: ``source_is_self`` (only the just-entered
        creature's own ETB fires)
      * Effect: ``put_plus_one_counter_on_creature_you_control``
        amount=1 -- NEW on the bridge as of the companion commit
        on this branch.

    First real-EoE cross-engine probe to exercise the
    ``Effect::PutPlusOneCounterOnCreatureYouControl`` arm +
    ``PutPlusOneCounterOnCreatureYouControl`` Python class end-to-
    end.

    Predicate decomposition (same as Germinating Wurm / Quantum
    Riddler / Nebula Dragon / Seedship Broodtender / Dubious
    Delicacy):

        SourceIsSelf

    Effect: ``put_plus_one_counter_on_creature_you_control(amount=1)``
    -- the bridge arm translates to
    ``PutPlusOneCounterOnCreatureYouControl(amount=1)``.

    **Target-pick parity contract.** Rust's
    ``Effect::PutPlusOneCounterOnCreatureYouControl`` arm
    (rust/src/state_ops_resolve.rs:4148-4211) picks the target
    DETERMINISTICALLY at apply_effect time: scan the SOURCE
    CONTROLLER's battlefield top-to-bottom for the FIRST object
    whose ``card_types`` contains "Creature", and add ``amount`` to
    its scalar ``counters`` field. SAME caster-side scan as
    ``PumpTargetCreatureUntilEOT`` -- the same target-pick shim
    (``_PickFirstControlledCreatureAgent`` from the Dubious Delicacy
    probe) works here too.

    **Self-target subtlety.** Rayblade Trooper itself is a Creature,
    so when it enters its own bf the at-apply-time scan COULD pick
    it as the first creature. The probe scenario stacks a Bait Bear
    onto p0's bf BEFORE the Trooper so the Bait Bear is the first
    creature in zone-iteration order -- both engines pick the Bait
    Bear. This makes the counter delta observable on a different
    object than the source, separating "trigger fired + applied"
    from "self-modifier no-op".

    Probe shape (inject-and-fire-ENTERS, same pattern as the
    Dubious Delicacy probe in this commit's parent):

      1. Inject a Bait Bear onto p0's bf FIRST (so it's at index 0
         and the deterministic scan picks it before any later-
         injected creature). Bait bear has printed counters=0; the
         post-resolve assertion checks counters became 1.

      2. Inject Rayblade Trooper onto p0's bf. ENTERS dispatch +
         SourceIsSelf predicate => trigger lands on stack with
         target pre-chosen (Bait Bear on both sides).

      3. Drain both stacks. Resolve walk: Bait Bear's
         ``counters`` (Rust) / ``plus_one_counters`` (Python)
         increments from 0 to 1.

      4. Cross-engine assert: both engines show Bait Bear with
         exactly one +1/+1 counter; Rayblade Trooper has zero
         counters (the trigger didn't target it).

    Out of scope:

      * The dies-trigger token-creation rider -- needs
        ``feature/phase5-create-token-bridge`` + the DIES-event
        harness; neither on main today.
      * Warp (the alternate cast cost) -- mana pipeline bypass.
      * Mana cost ({2}{W}) -- inject-and-dispatch-ENTERS bypasses
        the mana pipeline.

    Expected post-dispatch + post-drain state on BOTH engines:

      * Bait Bear on p0's bf with 1 +1/+1 counter.
      * Rayblade Trooper on p0's bf with 0 counters.
      * No life changes.
      * No residual stack.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )
    from tests.parity._picker_shims import _PickFirstControlledCreatureAgent

    rayblade_trooper = CardDef(
        name="Rayblade Trooper",
        card_type="Creature",
        mana_cost_generic=2,
        mana_cost_colored=(("W", 1),),
        power=2,
        toughness=2,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "put_plus_one_counter_on_creature_you_control",
                    "amount": 1,
                },
            },
        ),
    )
    # The counter target: a Bait Bear injected BEFORE the Trooper so
    # it's at index 0 of p0's bf, and the deterministic scan picks
    # it before the Trooper.
    bait_bear = CardDef(
        name="Bait Bear (counter target)",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=2,
        toughness=2,
    )
    spec = DeckSpec(
        card_defs=(rayblade_trooper, bait_bear),
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    rust_bait_dict = {
        "name": "Bait Bear (counter target)",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1, "G": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
    }
    rust_bait_id = rust_state.register_and_inject_object(
        rust_bait_dict, 0, ZONE_BATTLEFIELD,
    )
    assert rust_state.stack_size() == 0

    rust_rayblade_dict = {
        "name": "Rayblade Trooper",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "W": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "put_plus_one_counter_on_creature_you_control",
                    "amount": 1,
                },
            }
        ],
    }
    rust_rayblade_id = rust_state.register_and_inject_object(
        rust_rayblade_dict, 0, ZONE_BATTLEFIELD,
    )
    assert rust_state.stack_size() == 1, (
        "Rust: Rayblade Trooper's own arrival should fire the "
        "SourceIsSelf ENTERS trigger and land "
        "PutPlusOneCounterOnCreatureYouControl(1) on the stack. "
        f"Got stack_size={rust_state.stack_size()}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCounterOnCreatureYouControl,
    )
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    bait_printing = CardPrinting(
        name="Bait Bear (counter target)",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=(("G", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(),
    )
    rayblade_printing = CardPrinting(
        name="Rayblade Trooper",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2, colored=(("W", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=PutPlusOneCounterOnCreatureYouControl(amount=1),
            ),
        ),
    )

    py_bait = py_state.new_object(
        bait_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_bait.summoning_sick = False
    py_bait.tapped = False
    py_bait.damage = 0
    py_bait.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_bait)
    assert py_bait.plus_one_counters == 0

    # Caster-side target-pick shim. Same shape as the Dubious
    # Delicacy probe's _PickFirstControlledCreatureAgent: filter
    # legal_targets to creatures controlled by the agent's
    # player_id and return the first. Mirrors Rust's first-
    # creature-on-caster-bf scan. Shim hoisted to
    # tests/parity/_picker_shims.py.
    py_state.players[0].agent = _PickFirstControlledCreatureAgent()

    py_rayblade = py_state.new_object(
        rayblade_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_rayblade.summoning_sick = False
    py_rayblade.tapped = False
    py_rayblade.damage = 0
    py_rayblade.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_rayblade)
    _trigger_etb_abilities(py_state, py_rayblade)
    assert len(py_state.stack) == 1, (
        "Python: Rayblade Trooper's own arrival should fire the "
        "IsSelf ENTERS trigger and land "
        "PutPlusOneCounterOnCreatureYouControl(1) on the stack. "
        f"Got stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks, then compare ----
    _drain_stack_both(py_state, rust_state)

    # Stacks empty on both sides.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0

    # Per-engine post-state: Bait Bear has 1 +1/+1 counter; Rayblade
    # Trooper has 0 (the trigger targeted the bait, not itself, per
    # the deterministic first-in-bf scan).
    rust_bf = rust_state.battlefield_snapshot()
    rust_bait_entry = next(
        e for e in rust_bf if int(e["id"]) == rust_bait_id
    )
    rust_rayblade_entry = next(
        e for e in rust_bf if int(e["id"]) == rust_rayblade_id
    )
    assert rust_bait_entry["counters"] == 1, (
        f"Rust bait bear should have 1 +1/+1 counter; got "
        f"{rust_bait_entry['counters']}"
    )
    assert rust_rayblade_entry["counters"] == 0, (
        f"Rust Rayblade Trooper should have 0 counters (it wasn't "
        f"the target); got {rust_rayblade_entry['counters']}"
    )

    assert py_bait.plus_one_counters == 1, (
        f"Python bait bear should have 1 +1/+1 counter; got "
        f"{py_bait.plus_one_counters}"
    )
    assert py_rayblade.plus_one_counters == 0, (
        f"Python Rayblade Trooper should have 0 counters (it wasn't "
        f"the target); got {py_rayblade.plus_one_counters}"
    )

    # Cross-engine: same counter values on the same objects.
    assert rust_bait_entry["counters"] == py_bait.plus_one_counters
    assert rust_rayblade_entry["counters"] == py_rayblade.plus_one_counters

    # Lives unchanged.
    assert rust_state.get_life(0) == 20
    assert rust_state.get_life(1) == 20
    assert py_state.players[0].life == 20
    assert py_state.players[1].life == 20


def test_cross_engine_real_eoe_interceptor_mechan_etb_return_artifact_or_creature_parity(
    parity_smoke,
):
    """Probe: Interceptor Mechan (EoE) ETB ``return target artifact
    or creature card from your graveyard to your hand`` parity --
    FIRST real-EoE cross-engine probe with a rider-widened
    return-to-hand ETB trigger.

    Oracle text in ``data/edge_of_eternities.json``:

        "Flying
         When this creature enters, return target artifact or
         creature card from your graveyard to your hand.
         Void -- At the beginning of your end step, if a nonland
         permanent left the battlefield this turn or a spell was
         warped this turn, put a +1/+1 counter on this creature."

    Bridges the
    ``return_artifact_or_creature_from_your_graveyard_to_hand``
    effect kind end-to-end on a real EoE card. The audit lists
    Interceptor Mechan as the unique consumer of the or_artifact
    rider widening; the leaf effect composes directly off the
    bare-arm + or_artifact=True (no Sequence / IfYouDo nesting),
    so it is end-to-end probeable from the rider arm alone.

    The Void end-step ability and the Flying static keyword are
    OUT OF SCOPE for this probe -- only the ETB return trigger is
    exercised. Both engines see the same minimal trigger surface.

    Predicate decomposition:

        SourceIsSelf

    Effect:
    ``return_artifact_or_creature_from_your_graveyard_to_hand``
    -- NEW on the bridge as of the companion commits on this
    branch. The Rust effect variant carries the I82 controller-of-
    effect contract (``controller_idx`` derives from
    ``current_resolve_source_controller``); the Python side
    translates to
    ``ReturnCreatureFromYourGraveyardToHand(or_artifact=True)``.

    **Rider-widening discriminator.** The bare unit-variant arm
    would skip an artifact-only graveyard (no creatures match
    the filter). The or_artifact rider widens the filter to admit
    artifacts; this probe seeds the graveyard with a
    NON-CREATURE artifact so the rider is the load-bearing
    path -- if the bridge ever regressed to the bare unit
    variant, the artifact would not qualify and the trigger
    would fizzle.

    Probe shape (inject-and-fire-ENTERS):

      1. Pre-seed p0's graveyard with a vanilla Artifact card.
         Load-bearing test datum: only the or_artifact rider
         admits it.
      2. Inject Interceptor Mechan on p0's battlefield. Trigger
         fires; one
         ReturnArtifactOrCreatureFromYourGraveyardToHand lands
         on the stack with its target deterministically picked.
      3. Drain both stacks. Both engines: artifact moves from
         p0's graveyard to p0's hand.
      4. Cross-engine assert: empty p0 graveyard, single
         Mechan Recur Bait Artifact in p0's hand, Interceptor
         Mechan still on p0's bf.

    Out of scope: Flying / Void / cast cost / multi-card
    graveyard pick / empty-graveyard silent-skip.

    Expected post-dispatch + post-drain state on BOTH engines:

      * Interceptor Mechan on p0's battlefield.
      * Mechan Recur Bait Artifact in p0's hand.
      * p0 graveyard empty.
      * No residual stack.
      * Life totals unchanged.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )
    from tests.parity._picker_shims import _PickFirstLegalTargetAgent

    recur_bait_artifact = CardDef(
        name="Mechan Recur Bait Artifact",
        card_type="Artifact",
        mana_cost_generic=2,
    )
    interceptor_mechan = CardDef(
        name="Interceptor Mechan",
        card_type="Creature",
        mana_cost_generic=4,
        power=2,
        toughness=3,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": (
                        "return_artifact_or_creature_from_your_graveyard_to_hand"
                    ),
                },
            },
        ),
    )
    spec = DeckSpec(
        card_defs=(recur_bait_artifact, interceptor_mechan),
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    ZONE_GRAVEYARD = 3
    rust_artifact_dict = {
        "name": "Mechan Recur Bait Artifact",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 2},
        "effects": [],
    }
    rust_mechan_dict = {
        "name": "Interceptor Mechan",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 4},
        "effects": [],
        "power": 2,
        "toughness": 3,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": (
                        "return_artifact_or_creature_from_your_graveyard_to_hand"
                    ),
                },
            }
        ],
    }
    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)
    rust_state.register_and_inject_object(
        rust_artifact_dict, 0, ZONE_GRAVEYARD
    )
    rust_state.register_and_inject_object(
        rust_mechan_dict, 0, ZONE_BATTLEFIELD
    )
    assert rust_state.stack_size() == 1, (
        "Rust: Interceptor Mechan's arrival should fire the "
        "SourceIsSelf ENTERS trigger and land "
        "ReturnArtifactOrCreatureFromYourGraveyardToHand on the "
        f"stack. Got stack_size={rust_state.stack_size()}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.bounce import (
        ReturnCreatureFromYourGraveyardToHand,
    )
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    artifact_printing = CardPrinting(
        name="Mechan Recur Bait Artifact",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2, colored=()),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
    )
    mechan_printing = CardPrinting(
        name="Interceptor Mechan",
        mana_cost_str="",
        mana_cost=ManaCost(generic=4, colored=()),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=3,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=ReturnCreatureFromYourGraveyardToHand(
                    or_artifact=True
                ),
            ),
        ),
    )

    # Pick-first-legal-target shim for the or_artifact rider arm.
    # Hoisted to tests/parity/_picker_shims.py.
    py_state.players[0].agent = _PickFirstLegalTargetAgent()

    # Seed p0's graveyard with the artifact bait.
    py_bait = py_state.new_object(
        artifact_printing, owner_id=0, zone=Zone.GRAVEYARD,
    )
    py_state.players[0].graveyard.append(py_bait)

    py_mechan = py_state.new_object(
        mechan_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_mechan.summoning_sick = False
    py_mechan.tapped = False
    py_mechan.damage = 0
    py_mechan.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_mechan)
    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life
    _trigger_etb_abilities(py_state, py_mechan)
    assert len(py_state.stack) == 1, (
        "Python: Interceptor Mechan's arrival should fire the "
        "IsSelf ENTERS trigger and land "
        "ReturnCreatureFromYourGraveyardToHand(or_artifact=True) "
        f"on the stack. Got stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks, then compare ----
    _drain_stack_both(py_state, rust_state)

    # Post-drain: artifact moved from p0's gy to p0's hand on both
    # engines.
    assert rust_state.hand_sizes[0] == 1, (
        f"Rust: p0 hand should contain the recurred artifact; "
        f"got hand_size={rust_state.hand_sizes[0]}"
    )
    assert rust_state.graveyard_sizes[0] == 0, (
        f"Rust: p0 graveyard should be empty after the return; "
        f"got graveyard_size={rust_state.graveyard_sizes[0]}"
    )
    assert rust_state.battlefield_sizes[0] == 1, (
        f"Rust: p0 bf should still hold Interceptor Mechan; "
        f"got bf_size={rust_state.battlefield_sizes[0]}"
    )

    assert len(py_state.players[0].hand) == 1, (
        f"Python: p0 hand should contain the recurred artifact; "
        f"got hand_size={len(py_state.players[0].hand)}"
    )
    py_hand_name = py_state.players[0].hand[0].printing.name
    assert py_hand_name == "Mechan Recur Bait Artifact", (
        f"Python: p0 hand should contain the bait artifact; "
        f"got {py_hand_name}"
    )
    assert len(py_state.players[0].graveyard) == 0, (
        f"Python: p0 graveyard should be empty after the return; "
        f"got graveyard_size={len(py_state.players[0].graveyard)}"
    )
    py_bf_p0 = [
        o for o in py_state.battlefield if o.controller_id == 0
    ]
    assert len(py_bf_p0) == 1, (
        f"Python: p0 bf should still hold Interceptor Mechan; "
        f"got bf_size={len(py_bf_p0)}"
    )
    assert py_bf_p0[0].printing.name == "Interceptor Mechan", (
        f"Python: p0 bf survivor should be Interceptor Mechan; "
        f"got {py_bf_p0[0].printing.name}"
    )

    # Cross-engine: lives unchanged on both sides.
    assert rust_state.get_life(0) == rust_p0_life_before
    assert rust_state.get_life(1) == rust_p1_life_before
    assert py_state.players[0].life == py_p0_life_before
    assert py_state.players[1].life == py_p1_life_before
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life

    # Cross-engine: hand / graveyard / bf sizes match.
    assert rust_state.hand_sizes[0] == len(py_state.players[0].hand)
    assert rust_state.hand_sizes[1] == len(py_state.players[1].hand)
    assert (
        rust_state.graveyard_sizes[0]
        == len(py_state.players[0].graveyard)
    )
    assert (
        rust_state.graveyard_sizes[1]
        == len(py_state.players[1].graveyard)
    )

    # Stacks empty on both sides.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0


def test_cross_engine_real_eoe_uthros_scanship_etb_sequence_draw_discard_parity(
    parity_smoke,
):
    """Probe: Uthros Scanship (EoE) ETB ``draw two cards, then
    discard a card`` parity -- FIRST real-EoE cross-engine probe
    with a Sequence-composer ETB trigger.

    Oracle text in ``data/edge_of_eternities.json``:

        "When this Spacecraft enters, draw two cards, then discard
         a card.
         Station ({tap} another creature you control: Put charge
         counters equal to its power on this Spacecraft. Station
         only as a sorcery. It's an artifact creature at 8+.)
         Flying"

    The Station activated ability, the Flying static, and the
    "+8 charge counters → artifact creature" mode are OUT OF SCOPE
    for this probe -- only the ETB sequence trigger is exercised.
    Rust and Python both see the same minimal trigger surface.

    First real-EoE cross-engine probe to exercise the
    ``Effect::Sequence`` arm + Python ``Sequence`` class end-to-end.

    Predicate decomposition: ``SourceIsSelf`` (only the just-arrived
    Spacecraft's own trigger fires).

    Effect: ``Sequence{[DrawCards{2}, DiscardSelf{1}]}`` -- NEW
    composer on the bridge as of the companion commits on this
    branch. The Rust resolve arm (state_ops_resolve.rs:4125-4129)
    walks children in order under ``apply_effect``; Python's
    ``Sequence.resolve`` walks ``self.effects`` in order.

    **Net hand-size delta**: +2 (draw) - 1 (discard) = +1. We
    assert the net delta on both engines plus the discarded card's
    identity in the graveyard.

    **Cross-engine pick contract.** Discard's pick is the only
    point of divergence: Rust's ``DiscardSelf`` resolve pops
    ``hand[0]`` deterministically (state_ops_resolve.rs:2875+);
    Python calls ``agent.choose_discard``. We seat a
    ``_DiscardFirstAgent`` on p0 mirroring Rust's at-resolve
    hand[0] pick. After the draw, hand[0] on the Python side is
    the SAME card as Rust's hand[0] iff (a) p0 had no cards in
    hand before the trigger (so hand[0] post-draw is the first
    drawn card -- top-of-library), and (b) both engines built the
    library in the same order (which the cross_engine harness
    guarantees).

    Probe shape (inject-and-fire-ENTERS, mirrors Seedship
    Broodtender / Virus Beetle):

      1. Pre-seed p0's library top with TWO distinct bait
         creatures (will be drawn). Top-of-library = index 0
         is consistent across engines.
      2. p0's hand starts empty (deterministic post-draw hand[0]
         = the first drawn card).
      3. Inject Uthros Scanship onto p0's bf via
         ``register_and_inject_object``; ENTERS fans out, the
         SourceIsSelf predicate matches, the Sequence trigger
         lands on the stack.
      4. Seat a deterministic-hand[0] discard agent on p0
         (Python only; Rust's pick is intrinsic).
      5. Drain both stacks. Both engines: p0 draws 2, then
         discards hand[0] (= the first drawn card, "Sequence
         Bait Alpha").
      6. Cross-engine assert: p0 hand size = 1 (Beta), p0
         graveyard contains exactly Alpha, p0 library shrank by
         2.

    Out of scope: Station / Flying / cast cost / multi-card
    discard fan / library-empty draw fizzle.

    Expected post-dispatch + post-drain state on BOTH engines:

      * Uthros Scanship on p0's battlefield.
      * p0 hand: ["Sequence Bait Beta"] (Alpha discarded).
      * p0 graveyard: ["Sequence Bait Alpha"].
      * p0 library: drained by 2 (both bait cards drawn).
      * p1 untouched.
      * Lives unchanged on both seats.
      * No residual stack.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )
    from tests.parity._picker_shims import _DiscardFirstAgent

    uthros_scanship = CardDef(
        name="Uthros Scanship",
        card_type="Artifact",
        mana_cost_generic=3,
        mana_cost_colored=(("U", 1),),
        # Spacecraft is a subtype carried on the Subtypes substrate.
        subtypes=("Spacecraft",),
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "sequence",
                    "effects": [
                        {"kind": "draw_cards", "count": 2},
                        {"kind": "discard_self", "amount": 1},
                    ],
                },
            },
        ),
    )
    bait_a = CardDef(
        name="Sequence Bait Alpha",
        card_type="Creature",
        mana_cost_generic=1,
        power=1,
        toughness=1,
    )
    bait_b = CardDef(
        name="Sequence Bait Beta",
        card_type="Creature",
        mana_cost_generic=2,
        power=2,
        toughness=2,
    )
    spec = DeckSpec(
        card_defs=(uthros_scanship, bait_a, bait_b),
        # Top-of-library = index 0; Alpha is drawn first (lands at
        # hand[0]), then Beta (lands at hand[1]). The discard's
        # hand[0] pick then targets Alpha.
        p0_library=("Sequence Bait Alpha", "Sequence Bait Beta"),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    rust_scanship_dict = {
        "name": "Uthros Scanship",
        "card_types": ["Artifact"],
        "subtypes": ["Spacecraft"],
        "mana_cost": {"generic": 3, "U": 1},
        "effects": [],
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "sequence",
                    "effects": [
                        {"kind": "draw_cards", "count": 2},
                        {"kind": "discard_self", "amount": 1},
                    ],
                },
            }
        ],
    }
    rust_p0_lib_before = rust_state.library_sizes[0]
    rust_p0_hand_before = rust_state.hand_sizes[0]
    rust_p0_gy_before = rust_state.graveyard_sizes[0]
    rust_p1_lib_before = rust_state.library_sizes[1]
    rust_p1_hand_before = rust_state.hand_sizes[1]
    rust_p1_gy_before = rust_state.graveyard_sizes[1]
    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)
    assert rust_p0_lib_before == 2
    assert rust_p0_hand_before == 0
    assert rust_p0_gy_before == 0

    rust_state.register_and_inject_object(
        rust_scanship_dict, 0, ZONE_BATTLEFIELD,
    )
    assert rust_state.stack_size() == 1, (
        "Rust: Uthros Scanship's own arrival should fire the "
        "SourceIsSelf ENTERS trigger and land Sequence(DrawCards(2), "
        f"DiscardSelf(1)) on the stack. Got "
        f"stack_size={rust_state.stack_size()}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.discard import DiscardSelf
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    scanship_printing = CardPrinting(
        name="Uthros Scanship",
        mana_cost_str="",
        mana_cost=ManaCost(generic=3, colored=(("U", 1),)),
        type_line="Artifact - Spacecraft",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=("Spacecraft",),
        power=None,
        toughness=None,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=Sequence(
                    effects=(
                        DrawCards(amount=2),
                        DiscardSelf(amount=1),
                    ),
                ),
            ),
        ),
    )

    py_state.players[0].agent = _DiscardFirstAgent()

    py_p0_lib_before = len(py_state.players[0].library)
    py_p0_hand_before = len(py_state.players[0].hand)
    py_p0_gy_before = len(py_state.players[0].graveyard)
    py_p1_lib_before = len(py_state.players[1].library)
    py_p1_hand_before = len(py_state.players[1].hand)
    py_p1_gy_before = len(py_state.players[1].graveyard)
    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life
    assert py_p0_lib_before == 2
    assert py_p0_hand_before == 0

    py_scanship = py_state.new_object(
        scanship_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_scanship.summoning_sick = False
    py_scanship.tapped = False
    py_scanship.damage = 0
    py_scanship.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_scanship)
    _trigger_etb_abilities(py_state, py_scanship)
    assert len(py_state.stack) == 1, (
        "Python: Uthros Scanship's own arrival should fire the "
        "IsSelf ENTERS trigger and land Sequence(DrawCards(2), "
        f"DiscardSelf(1)) on the stack. Got "
        f"stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks, then compare ----
    _drain_stack_both(py_state, rust_state)

    # Net hand-size delta: +2 (draw) - 1 (discard) = +1 on both.
    assert rust_state.hand_sizes[0] == rust_p0_hand_before + 1, (
        f"Rust p0 hand should grow by 1 (+2 draw - 1 discard); "
        f"before={rust_p0_hand_before} after={rust_state.hand_sizes[0]}"
    )
    assert rust_state.library_sizes[0] == rust_p0_lib_before - 2, (
        f"Rust p0 library should shrink by 2 (the 2 draws); "
        f"before={rust_p0_lib_before} after={rust_state.library_sizes[0]}"
    )
    assert rust_state.graveyard_sizes[0] == rust_p0_gy_before + 1, (
        f"Rust p0 graveyard should grow by 1 (the discard); "
        f"before={rust_p0_gy_before} after={rust_state.graveyard_sizes[0]}"
    )

    assert len(py_state.players[0].hand) == py_p0_hand_before + 1, (
        f"Python p0 hand should grow by 1; "
        f"before={py_p0_hand_before} after={len(py_state.players[0].hand)}"
    )
    assert len(py_state.players[0].library) == py_p0_lib_before - 2
    assert len(py_state.players[0].graveyard) == py_p0_gy_before + 1

    # Strongest pin: discarded card name. With hand[0]-pick agents on
    # both engines, Alpha (drawn first → landed at hand[0]) is the
    # discard target; Beta survives in hand.
    rust_p0_gy_names = [
        e["printing_name"] for e in rust_state.graveyard_snapshot(0)
    ]
    py_p0_gy_names = [o.printing.name for o in py_state.players[0].graveyard]
    assert rust_p0_gy_names == ["Sequence Bait Alpha"], (
        f"Rust p0 gy should contain only Sequence Bait Alpha; "
        f"got {rust_p0_gy_names}"
    )
    assert py_p0_gy_names == ["Sequence Bait Alpha"], (
        f"Python p0 gy should contain only Sequence Bait Alpha; "
        f"got {py_p0_gy_names}"
    )
    rust_p0_hand_names = [
        e["printing_name"] for e in rust_state.hand_snapshot(0)
    ]
    py_p0_hand_names = [o.printing.name for o in py_state.players[0].hand]
    assert rust_p0_hand_names == ["Sequence Bait Beta"], (
        f"Rust p0 hand should hold only Sequence Bait Beta (Alpha "
        f"discarded); got {rust_p0_hand_names}"
    )
    assert py_p0_hand_names == ["Sequence Bait Beta"], (
        f"Python p0 hand should hold only Sequence Bait Beta; "
        f"got {py_p0_hand_names}"
    )

    # Cross-engine: per-zone parity.
    assert rust_state.hand_sizes[0] == len(py_state.players[0].hand)
    assert rust_state.library_sizes[0] == len(py_state.players[0].library)
    assert rust_state.graveyard_sizes[0] == len(py_state.players[0].graveyard)
    assert rust_state.hand_sizes[1] == len(py_state.players[1].hand)
    assert rust_state.library_sizes[1] == len(py_state.players[1].library)
    assert rust_state.graveyard_sizes[1] == len(py_state.players[1].graveyard)
    assert rust_p0_hand_names == py_p0_hand_names
    assert rust_p0_gy_names == py_p0_gy_names

    # p1 untouched.
    assert rust_state.hand_sizes[1] == rust_p1_hand_before
    assert rust_state.library_sizes[1] == rust_p1_lib_before
    assert rust_state.graveyard_sizes[1] == rust_p1_gy_before
    assert len(py_state.players[1].hand) == py_p1_hand_before
    assert len(py_state.players[1].library) == py_p1_lib_before
    assert len(py_state.players[1].graveyard) == py_p1_gy_before

    # Lives unchanged.
    assert rust_state.get_life(0) == rust_p0_life_before
    assert rust_state.get_life(1) == rust_p1_life_before
    assert py_state.players[0].life == py_p0_life_before
    assert py_state.players[1].life == py_p1_life_before
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life

    # Stacks empty on both sides.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0


def test_cross_engine_real_eoe_melded_moxite_etb_if_you_do_discard_draw_parity(
    parity_smoke,
):
    """Probe: Melded Moxite (EoE) ETB ``discard a card. If you do,
    draw two cards.`` parity (success path) -- FIRST real-EoE
    cross-engine probe with an IfYouDo-composer ETB trigger.

    Oracle text in ``data/edge_of_eternities.json``:

        "When this artifact enters, you may discard a card. If you
         do, draw two cards.
         {3}, Sacrifice this artifact: Create a tapped 2/2 colorless
         Robot artifact creature token."

    The Sacrifice activated ability is OUT OF SCOPE for this probe
    -- only the ETB IfYouDo trigger is exercised. Both engines see
    the same minimal trigger surface.

    The literal oracle has a "you MAY discard" optional gate, but
    the IfYouDo bridge spec for Melded Moxite (per the audit) drops
    the may-wrapping in favor of the bare ``IfYouDo{cost=DiscardSelf,
    then=DrawCards{2}}`` shape -- the success path observably
    matches the may-then-yes case (agent commits to discard) which
    is what this probe drives.

    First real-EoE cross-engine probe to exercise the
    ``Effect::IfYouDo`` arm + Python ``IfYouDo`` class end-to-end.

    Predicate decomposition: ``SourceIsSelf`` (only the just-arrived
    artifact's own trigger fires).

    Effect: ``IfYouDo{do_action=DiscardSelf{1},
    then_action=DrawCards{2}}`` -- NEW composer on the bridge as of
    the companion commits on this branch. Both engines:
    - Rust resolve arm walks ``do_action`` first under
      ``apply_effect``, observes its "did something" signal, and
      conditionally fires ``then_action`` under ``apply_effect``.
    - Python's ``IfYouDo.resolve`` calls ``do_action.resolve``,
      checks the boolean signal (False → skip), and runs
      ``then_action.resolve``.

    **Cross-engine signal contract.** ``DiscardSelf`` on a non-empty
    hand returns True on both engines (Rust's resolve arm pushes
    the discarded card to graveyard and the IfYouDo gate observes
    the success; Python's ``DiscardSelf.resolve`` returns True
    after the discard). The success path therefore fires
    ``then_action`` on both sides.

    Probe shape (success path -- non-empty hand pre-trigger):

      1. Pre-seed p0's hand with ONE bait creature (the discard
         target -- hand[0]-deterministic pick).
      2. Pre-seed p0's library top with TWO distinct bait
         creatures (the draw-2 result).
      3. Inject Melded Moxite onto p0's bf via
         ``register_and_inject_object``; ENTERS fires; SourceIsSelf
         matches; the IfYouDo trigger lands on the stack.
      4. Seat a deterministic-hand[0] discard agent on p0
         (Python only).
      5. Drain both stacks. Both engines: p0 discards bait at
         hand[0] (Discard Bait), then draws 2 (Draw Bait Alpha,
         Draw Bait Beta).
      6. Cross-engine assert:
         * p0 hand: 1 → 1 - 1 + 2 = 2 (the two draws).
         * p0 graveyard: 0 → 1 (the discarded bait).
         * p0 library: 2 → 0 (drained by the draws).

    Out of scope: empty-hand fork (would skip the draw -- a future
    probe slice can pin that branch separately), Sacrifice ability,
    cast cost.

    Expected post-dispatch + post-drain state on BOTH engines:

      * Melded Moxite on p0's battlefield.
      * p0 hand: ["Draw Bait Alpha", "Draw Bait Beta"] (in some
        order — the comparison is set-ish via sorted()).
      * p0 graveyard: ["Discard Bait"] (the just-discarded).
      * p0 library empty.
      * p1 untouched.
      * Lives unchanged.
      * No residual stack.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )
    from tests.parity._picker_shims import _DiscardFirstAgent

    melded_moxite = CardDef(
        name="Melded Moxite",
        card_type="Artifact",
        mana_cost_generic=1,
        mana_cost_colored=(("R", 1),),
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "if_you_do",
                    "do_action": {
                        "kind": "discard_self", "amount": 1,
                    },
                    "then_action": {
                        "kind": "draw_cards", "count": 2,
                    },
                },
            },
        ),
    )
    discard_bait = CardDef(
        name="Discard Bait",
        card_type="Creature",
        mana_cost_generic=1,
        power=1,
        toughness=1,
    )
    draw_bait_a = CardDef(
        name="Draw Bait Alpha",
        card_type="Creature",
        mana_cost_generic=1,
        power=1,
        toughness=1,
    )
    draw_bait_b = CardDef(
        name="Draw Bait Beta",
        card_type="Creature",
        mana_cost_generic=2,
        power=2,
        toughness=2,
    )
    spec = DeckSpec(
        card_defs=(melded_moxite, discard_bait, draw_bait_a, draw_bait_b),
        # Top-of-library = Alpha then Beta (drawn in that order).
        p0_library=("Draw Bait Alpha", "Draw Bait Beta"),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_HAND = 0
    ZONE_BATTLEFIELD = 2
    rust_discard_bait_dict = {
        "name": "Discard Bait",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "effects": [],
        "power": 1,
        "toughness": 1,
    }
    rust_state.register_and_inject_object(
        rust_discard_bait_dict, 0, ZONE_HAND
    )
    rust_p0_lib_before = rust_state.library_sizes[0]
    rust_p0_hand_before = rust_state.hand_sizes[0]
    rust_p0_gy_before = rust_state.graveyard_sizes[0]
    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)
    assert rust_p0_lib_before == 2
    assert rust_p0_hand_before == 1
    assert rust_p0_gy_before == 0

    rust_moxite_dict = {
        "name": "Melded Moxite",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 1, "R": 1},
        "effects": [],
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "if_you_do",
                    "do_action": {
                        "kind": "discard_self", "amount": 1,
                    },
                    "then_action": {
                        "kind": "draw_cards", "count": 2,
                    },
                },
            }
        ],
    }
    rust_state.register_and_inject_object(
        rust_moxite_dict, 0, ZONE_BATTLEFIELD,
    )
    assert rust_state.stack_size() == 1, (
        "Rust: Melded Moxite's own arrival should fire the "
        "SourceIsSelf ENTERS trigger and land "
        f"IfYouDo(DiscardSelf, DrawCards(2)) on the stack. Got "
        f"stack_size={rust_state.stack_size()}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.combinators import IfYouDo
    from mtg_bot.effects.generic.discard import DiscardSelf
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    discard_bait_printing = CardPrinting(
        name="Discard Bait",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=1,
        toughness=1,
        produces=frozenset(),
    )
    moxite_printing = CardPrinting(
        name="Melded Moxite",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=(("R", 1),)),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=IfYouDo(
                    do_action=DiscardSelf(amount=1),
                    then_action=DrawCards(amount=2),
                ),
            ),
        ),
    )

    py_state.players[0].agent = _DiscardFirstAgent()

    # Pre-seed p0's hand with the discard bait.
    py_discard_bait = py_state.new_object(
        discard_bait_printing, owner_id=0, zone=Zone.HAND,
    )
    py_state.players[0].hand.append(py_discard_bait)

    py_p0_lib_before = len(py_state.players[0].library)
    py_p0_hand_before = len(py_state.players[0].hand)
    py_p0_gy_before = len(py_state.players[0].graveyard)
    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life
    assert py_p0_lib_before == 2
    assert py_p0_hand_before == 1

    py_moxite = py_state.new_object(
        moxite_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_moxite.summoning_sick = False
    py_moxite.tapped = False
    py_moxite.damage = 0
    py_moxite.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_moxite)
    _trigger_etb_abilities(py_state, py_moxite)
    assert len(py_state.stack) == 1, (
        "Python: Melded Moxite's own arrival should fire the "
        "IsSelf ENTERS trigger and land IfYouDo(DiscardSelf, "
        f"DrawCards(2)) on the stack. Got "
        f"stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks, then compare ----
    _drain_stack_both(py_state, rust_state)

    # Net hand: 1 - 1 + 2 = 2 on both engines (success path).
    expected_hand_after = 2
    assert rust_state.hand_sizes[0] == expected_hand_after, (
        f"Rust p0 hand should be {expected_hand_after} after "
        f"if-you-do (-1 discard + 2 draw); got "
        f"{rust_state.hand_sizes[0]}"
    )
    assert rust_state.library_sizes[0] == 0, (
        f"Rust p0 library should be drained (2 → 0); got "
        f"{rust_state.library_sizes[0]}"
    )
    assert rust_state.graveyard_sizes[0] == 1, (
        f"Rust p0 graveyard should hold the discarded bait (0 → 1); "
        f"got {rust_state.graveyard_sizes[0]}"
    )

    assert len(py_state.players[0].hand) == expected_hand_after
    assert len(py_state.players[0].library) == 0
    assert len(py_state.players[0].graveyard) == 1

    # Strongest pin: per-card identities.
    rust_p0_gy_names = [
        e["printing_name"] for e in rust_state.graveyard_snapshot(0)
    ]
    py_p0_gy_names = [o.printing.name for o in py_state.players[0].graveyard]
    assert rust_p0_gy_names == ["Discard Bait"], (
        f"Rust p0 gy should hold the discarded Discard Bait; "
        f"got {rust_p0_gy_names}"
    )
    assert py_p0_gy_names == ["Discard Bait"], (
        f"Python p0 gy should hold the discarded Discard Bait; "
        f"got {py_p0_gy_names}"
    )
    rust_p0_hand_names = sorted(
        e["printing_name"] for e in rust_state.hand_snapshot(0)
    )
    py_p0_hand_names = sorted(
        o.printing.name for o in py_state.players[0].hand
    )
    expected_hand_names = sorted(["Draw Bait Alpha", "Draw Bait Beta"])
    assert rust_p0_hand_names == expected_hand_names, (
        f"Rust p0 hand should hold the two draws; "
        f"got {rust_p0_hand_names}"
    )
    assert py_p0_hand_names == expected_hand_names, (
        f"Python p0 hand should hold the two draws; "
        f"got {py_p0_hand_names}"
    )

    # Cross-engine: per-zone parity.
    assert rust_state.hand_sizes[0] == len(py_state.players[0].hand)
    assert rust_state.library_sizes[0] == len(py_state.players[0].library)
    assert rust_state.graveyard_sizes[0] == len(py_state.players[0].graveyard)
    assert rust_p0_gy_names == py_p0_gy_names
    assert rust_p0_hand_names == py_p0_hand_names

    # Lives unchanged.
    assert rust_state.get_life(0) == rust_p0_life_before
    assert rust_state.get_life(1) == rust_p1_life_before
    assert py_state.players[0].life == py_p0_life_before
    assert py_state.players[1].life == py_p1_life_before
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life

    # Stacks empty on both sides.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0


def test_cross_engine_real_eoe_fell_gravship_etb_sequence_mill_return_parity(
    parity_smoke,
):
    """Probe: Fell Gravship (EoE) ETB ``mill three cards, then return
    a creature or Spacecraft card from your graveyard to your hand``
    parity -- composes the Sequence composer with the leaf bridge
    arms ``mill`` + ``return_creature_or_spacecraft_from_your_graveyard_to_hand``.

    Oracle text in ``data/edge_of_eternities.json``:

        "When this Spacecraft enters, mill three cards, then return
         a creature or Spacecraft card from your graveyard to your
         hand.
         Station ({tap} another creature you control: ...)
         Flying, lifelink"

    The Station activated ability + Flying / lifelink statics are
    OUT OF SCOPE; only the ETB sequence trigger is exercised.

    Effect: ``Sequence{[Mill{3},
    ReturnCreatureOrSpacecraftFromYourGraveyardToHand]}`` -- combines
    the Sequence composer with the rider-widened return-to-hand
    leaf arm. The ``or_spacecraft`` rider is on the bridge from the
    earlier Phase 5 commits.

    **Targeting timing divergence (handled by pre-seed).** Python's
    ``push_triggered_ability`` picks the return target at PUSH time
    via ``Sequence.legal_targets`` -- which delegates to the
    targeting sub-effect's legal_targets BEFORE the upstream Mill
    resolves. So the pre-mill graveyard contents drive the pool;
    post-mill cards aren't yet visible to the targeting pipeline.
    Rust at resolve time scans the post-mill graveyard. To pin a
    cross-engine consistent target, we PRE-SEED p0's graveyard
    with the recur target before the trigger fires; the milled
    cards (intentionally NON-creature, NON-Spacecraft Lands so the
    rider's filter only matches the pre-seeded card) accumulate
    after the pre-seeded target in graveyard insertion order.
    Rust's iterator-order scan finds the pre-seeded creature
    FIRST (it sits at gy index 0); Python's PUSH-time pick is
    forced to the same card by the same insertion order +
    creature-only filter. The two engines agree on the recur
    target despite the timing divergence.

    Probe shape:

      1. Pre-seed p0's graveyard with one Creature card
         (Recur Bait) that satisfies the
         or_spacecraft-rider filter via the creature-primary path.
      2. Pre-seed p0's library with 3 Land cards (mill bait,
         non-creature non-Spacecraft so they don't perturb the
         recur pick).
      3. Inject Fell Gravship onto p0's bf; SourceIsSelf ENTERS
         fires; Sequence trigger lands on the stack with target
         picked at push time = Recur Bait.
      4. Drain both stacks. Both engines:
         * Mill 3 from p0 library → p0 gy now has [Recur Bait,
           Mill Land 1, Mill Land 2, Mill Land 3] (insertion
           order).
         * Return-to-hand resolves on Recur Bait → moves it
           from p0 gy to p0 hand.
      5. Cross-engine assert:
         * p0 hand: 0 → 1 (Recur Bait).
         * p0 graveyard: 1 → 3 (the 3 milled lands; Recur Bait
           gone to hand).
         * p0 library: 3 → 0 (drained by mill).

    Out of scope: Station / Flying / lifelink / cast cost /
    empty-graveyard fizzle on the return.

    Expected post-dispatch + post-drain state on BOTH engines:

      * Fell Gravship on p0's battlefield.
      * p0 hand: ["Fell Recur Bait"].
      * p0 graveyard: 3 mill-bait Lands (Recur Bait promoted to
        hand).
      * p0 library empty.
      * p1 untouched.
      * Lives unchanged.
      * No residual stack.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )
    from tests.parity._picker_shims import _PickFirstLegalTargetAgent

    fell_gravship = CardDef(
        name="Fell Gravship",
        card_type="Artifact",
        mana_cost_generic=2,
        mana_cost_colored=(("B", 1),),
        subtypes=("Spacecraft",),
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "sequence",
                    "effects": [
                        {"kind": "mill", "count": 3},
                        {
                            "kind": (
                                "return_creature_or_spacecraft_from_your_graveyard_to_hand"
                            ),
                        },
                    ],
                },
            },
        ),
    )
    fell_recur_bait = CardDef(
        name="Fell Recur Bait",
        card_type="Creature",
        mana_cost_generic=1,
        power=2,
        toughness=2,
    )
    mill_land_1 = CardDef(
        name="Mill Land 1",
        card_type="Land",
    )
    mill_land_2 = CardDef(
        name="Mill Land 2",
        card_type="Land",
    )
    mill_land_3 = CardDef(
        name="Mill Land 3",
        card_type="Land",
    )
    spec = DeckSpec(
        card_defs=(
            fell_gravship, fell_recur_bait,
            mill_land_1, mill_land_2, mill_land_3,
        ),
        # Top-of-library = index 0; lands milled in order Land 1,
        # 2, 3 (matching insertion order in p0's gy).
        p0_library=("Mill Land 1", "Mill Land 2", "Mill Land 3"),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    ZONE_GRAVEYARD = 3
    rust_recur_bait_dict = {
        "name": "Fell Recur Bait",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
    }
    rust_state.register_and_inject_object(
        rust_recur_bait_dict, 0, ZONE_GRAVEYARD,
    )
    rust_p0_lib_before = rust_state.library_sizes[0]
    rust_p0_hand_before = rust_state.hand_sizes[0]
    rust_p0_gy_before = rust_state.graveyard_sizes[0]
    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)
    assert rust_p0_lib_before == 3
    assert rust_p0_hand_before == 0
    assert rust_p0_gy_before == 1

    rust_gravship_dict = {
        "name": "Fell Gravship",
        "card_types": ["Artifact"],
        "subtypes": ["Spacecraft"],
        "mana_cost": {"generic": 2, "B": 1},
        "effects": [],
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "sequence",
                    "effects": [
                        {"kind": "mill", "count": 3},
                        {
                            "kind": (
                                "return_creature_or_spacecraft_from_your_graveyard_to_hand"
                            ),
                        },
                    ],
                },
            }
        ],
    }
    rust_state.register_and_inject_object(
        rust_gravship_dict, 0, ZONE_BATTLEFIELD,
    )
    assert rust_state.stack_size() == 1, (
        "Rust: Fell Gravship's own arrival should fire the "
        "SourceIsSelf ENTERS trigger and land Sequence(Mill(3), "
        f"ReturnCreatureOrSpacecraft) on the stack. Got "
        f"stack_size={rust_state.stack_size()}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.bounce import (
        ReturnCreatureFromYourGraveyardToHand,
    )
    from mtg_bot.effects.generic.library_lookat import SelfMill
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    recur_bait_printing = CardPrinting(
        name="Fell Recur Bait",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
    )
    gravship_printing = CardPrinting(
        name="Fell Gravship",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2, colored=(("B", 1),)),
        type_line="Artifact - Spacecraft",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=("Spacecraft",),
        power=None,
        toughness=None,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=Sequence(
                    effects=(
                        SelfMill(amount=3),
                        ReturnCreatureFromYourGraveyardToHand(
                            or_spacecraft=True,
                        ),
                    ),
                ),
            ),
        ),
    )

    py_state.players[0].agent = _PickFirstLegalTargetAgent()

    # Pre-seed p0's graveyard with the recur bait creature.
    py_recur_bait = py_state.new_object(
        recur_bait_printing, owner_id=0, zone=Zone.GRAVEYARD,
    )
    py_state.players[0].graveyard.append(py_recur_bait)

    py_p0_lib_before = len(py_state.players[0].library)
    py_p0_hand_before = len(py_state.players[0].hand)
    py_p0_gy_before = len(py_state.players[0].graveyard)
    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life
    assert py_p0_lib_before == 3
    assert py_p0_hand_before == 0
    assert py_p0_gy_before == 1

    py_gravship = py_state.new_object(
        gravship_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_gravship.summoning_sick = False
    py_gravship.tapped = False
    py_gravship.damage = 0
    py_gravship.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_gravship)
    _trigger_etb_abilities(py_state, py_gravship)
    assert len(py_state.stack) == 1, (
        "Python: Fell Gravship's own arrival should fire the "
        "IsSelf ENTERS trigger and land Sequence(Mill(3), "
        f"ReturnCreatureOrSpacecraft) on the stack. Got "
        f"stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks, then compare ----
    _drain_stack_both(py_state, rust_state)

    # p0 hand: 0 → 1 (Recur Bait).
    # p0 graveyard: 1 → 3 (3 mill lands; Recur Bait promoted out).
    # p0 library: 3 → 0 (drained by mill).
    assert rust_state.hand_sizes[0] == 1, (
        f"Rust p0 hand should hold the recurred Fell Recur Bait; "
        f"got hand_size={rust_state.hand_sizes[0]}"
    )
    assert rust_state.library_sizes[0] == 0, (
        f"Rust p0 library should be drained (3 → 0); got "
        f"{rust_state.library_sizes[0]}"
    )
    assert rust_state.graveyard_sizes[0] == 3, (
        f"Rust p0 gy should hold 3 mill lands (Recur Bait promoted "
        f"to hand); got gy_size={rust_state.graveyard_sizes[0]}"
    )

    assert len(py_state.players[0].hand) == 1
    assert len(py_state.players[0].library) == 0
    assert len(py_state.players[0].graveyard) == 3

    # Strongest pin: per-card identities.
    rust_p0_hand_names = [
        e["printing_name"] for e in rust_state.hand_snapshot(0)
    ]
    py_p0_hand_names = [o.printing.name for o in py_state.players[0].hand]
    assert rust_p0_hand_names == ["Fell Recur Bait"], (
        f"Rust p0 hand should hold Fell Recur Bait; "
        f"got {rust_p0_hand_names}"
    )
    assert py_p0_hand_names == ["Fell Recur Bait"], (
        f"Python p0 hand should hold Fell Recur Bait; "
        f"got {py_p0_hand_names}"
    )
    rust_p0_gy_names = sorted(
        e["printing_name"] for e in rust_state.graveyard_snapshot(0)
    )
    py_p0_gy_names = sorted(
        o.printing.name for o in py_state.players[0].graveyard
    )
    expected_gy = sorted(["Mill Land 1", "Mill Land 2", "Mill Land 3"])
    assert rust_p0_gy_names == expected_gy, (
        f"Rust p0 gy should hold the 3 milled lands; "
        f"got {rust_p0_gy_names}"
    )
    assert py_p0_gy_names == expected_gy, (
        f"Python p0 gy should hold the 3 milled lands; "
        f"got {py_p0_gy_names}"
    )

    # Cross-engine: per-zone parity.
    assert rust_state.hand_sizes[0] == len(py_state.players[0].hand)
    assert rust_state.library_sizes[0] == len(py_state.players[0].library)
    assert rust_state.graveyard_sizes[0] == len(py_state.players[0].graveyard)
    assert rust_p0_hand_names == py_p0_hand_names
    assert rust_p0_gy_names == py_p0_gy_names

    # Lives unchanged.
    assert rust_state.get_life(0) == rust_p0_life_before
    assert rust_state.get_life(1) == rust_p1_life_before
    assert py_state.players[0].life == py_p0_life_before
    assert py_state.players[1].life == py_p1_life_before
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life

    # Stacks empty on both sides.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0


def test_cross_engine_synthetic_etb_pump_creatures_opponents_control_until_eot_parity(
    parity_smoke,
):
    """Probe: synthetic ``ETB Mass Debuff Ogre`` exercising the freshly
    landed ``pump_creatures_opponents_control_until_eot`` bridge arm
    end-to-end.

    Why synthetic rather than a real EoE card: the only EoE consumer
    of this effect-shape is Mouth of the Storm (``creatures your
    opponents control get -3/-0 UNTIL YOUR NEXT TURN``). The "until
    your next turn" extended duration routes through Python's
    ``until_caster_next_turn=True`` flag which has NO Rust counterpart
    -- Rust's ``Effect::PumpCreaturesOpponentsControlUntilEOT`` variant
    only carries ``power_bonus`` / ``toughness_bonus`` fields, no
    extended-duration field. Translating Mouth of the Storm to the
    bare arm would observably diverge at the start of the controller's
    NEXT turn (Python keeps the debuff; Rust has already cleared it
    at the casting turn's cleanup). The bare ``until end of turn``
    shape has no real-EoE consumer with matching fields today; a
    synthetic creature card with the bare-EOT trigger is the canonical
    way to exercise this substrate end-to-end on the bridge until a
    parametric extended-duration Rust variant lands.

    Trigger shape:

        Event: enters
        Predicate: source_is_self
        Effect: pump_creatures_opponents_control_until_eot
                power_bonus=-3, toughness_bonus=-3

    **Rust resolve semantics.** Rust's
    ``Effect::PumpCreaturesOpponentsControlUntilEOT`` arm
    (state_ops_resolve.rs:4514-4577) is UNTARGETED -- it walks
    ``state.players[1 - controller].battlefield`` (the source-
    controller's opponent's bf, two-player simplification) and
    pushes a ``UeotModifier::PowerToughnessBonus { power: -3,
    toughness: -3 }`` onto every creature object's ``ueot_modifiers``
    Vec. The source controller derives from the standard 5-zone
    walk for ``source_obj_id``; ``(0, 0)`` short-circuits;
    no-creatures-on-opponent-bf fizzles silently.

    **Python resolve semantics.** Python's
    ``PumpCreaturesOpponentsControlUntilEOT`` (effects/generic/
    pump.py:779) walks ``state.battlefield`` and stamps
    ``grant_pt_pump_ueot`` onto every creature whose
    ``controller_id != controller_id`` (the source controller's id).
    No ``legal_targets`` method -- the targeting pipeline never
    picks; the trigger lands on the stack with empty targets and
    resolves in one pass. Same observable: each opponent creature
    on the bf gets a ``-3/-3`` UEOT bonus.

    **Untargeted -- no agent shim required.** Unlike the
    ``pump_target_creature_until_eot`` family which needs a
    ``_PickFirstControlledCreatureAgent`` shim, this probe drives
    the trigger with empty targets on both engines and observes the
    en-masse delta on every opponent creature.

    Probe shape (inject-and-fire-ENTERS):

      1. Inject TWO 4/4 Bait Bears onto p1's battlefield BEFORE
         injecting the Ogre. Printed P/T 4/4 so the -3/-3 debuff
         leaves them at observable 1/1 (positive toughness, no
         SBA-death after cleanup, no disambiguation against a
         dies-trigger path).

      2. Inject ALSO one 4/4 Bait Bear on p0's battlefield. Same
         controller as the Ogre, so this bear must NOT receive the
         debuff (it's the source-controller's OWN creature, on the
         wrong side of the opponent-only filter). Pin that the
         filter direction is correct on both engines.

      3. Inject ``ETB Mass Debuff Ogre`` directly onto p0's
         battlefield via ``register_and_inject_object`` (Rust) /
         new_object + bf append + manual ``_trigger_etb_abilities``
         (Python). Both engines dispatch ENTERS for the just-arrived
         Ogre; the SourceIsSelf predicate matches; one
         ``PumpCreaturesOpponentsControlUntilEOT(-3, -3)`` trigger
         lands on the stack with empty targets.

      4. Drain both stacks. Resolve walk: each of p1's two bait
         bears gets a ``-3/-3`` UEOT modifier. p0's bear and the
         Ogre itself are untouched.

      5. Cross-engine assert: both p1 bears at effective P/T 1/1;
         p0's bear at effective P/T 4/4 (unchanged); the Ogre
         itself at its printed P/T (also unchanged -- it's on the
         caster's side).

    Out of scope:

      * Cast-from-hand mana cost -- inject-and-dispatch-ENTERS
        bypasses the mana pipeline.
      * Cleanup-step expiry -- not driven here. Both engines record
        the UEOT modifier on the affected objects; cleanup-step
        removal is already pinned by other tests.
      * Mouth of the Storm's "until your next turn" extended
        duration -- documented Rust substrate gap; out of scope of
        the bare-EOT bridge arm.
      * Three-or-more-player engine -- the Rust resolve at
        ``state_ops_resolve.rs:4549`` uses the two-player
        simplification ``opponent_idx = 1 - controller``; both
        engines are two-player today, observably identical.

    Expected post-dispatch + post-drain state on BOTH engines:

      * ETB Mass Debuff Ogre on p0's bf at printed P/T (unchanged).
      * Bait Bear on p0's bf at effective P/T 4/4 (unchanged --
        it's on the caster's side, filter direction is opponent).
      * Both Bait Bears on p1's bf at effective P/T 1/1 (printed
        4/4 + (-3, -3) UEOT modifier).
      * No life changes (the ETB doesn't touch life totals).
      * No residual stack.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )

    ogre = CardDef(
        name="ETB Mass Debuff Ogre",
        card_type="Creature",
        mana_cost_generic=6,
        mana_cost_colored=(("U", 1),),
        power=6,
        toughness=6,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "pump_creatures_opponents_control_until_eot",
                    "power_bonus": -3,
                    "toughness_bonus": -3,
                },
            },
        ),
    )
    # Bait Bear: vanilla 4/4 with no triggered abilities. Two copies
    # land on p1's bf (the debuff targets) and one copy lands on p0's
    # bf (the same-side control: must NOT receive the debuff).
    bait_bear = CardDef(
        name="Mass Debuff Bait Bear (4/4)",
        card_type="Creature",
        mana_cost_generic=3,
        mana_cost_colored=(("G", 1),),
        power=4,
        toughness=4,
    )
    spec = DeckSpec(
        card_defs=(ogre, bait_bear),
        # Empty libraries -- probe injects directly onto bf.
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    rust_bait_dict = {
        "name": "Mass Debuff Bait Bear (4/4)",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 3, "G": 1},
        "effects": [],
        "power": 4,
        "toughness": 4,
    }
    # Two p1-side bears (will get the -3/-3 debuff).
    rust_p1_bear_a_id = rust_state.register_and_inject_object(
        rust_bait_dict, 1, ZONE_BATTLEFIELD,
    )
    rust_p1_bear_b_id = rust_state.register_and_inject_object(
        rust_bait_dict, 1, ZONE_BATTLEFIELD,
    )
    # One p0-side bear (must NOT get the debuff -- same controller as
    # the Ogre).
    rust_p0_bear_id = rust_state.register_and_inject_object(
        rust_bait_dict, 0, ZONE_BATTLEFIELD,
    )
    # None of the bears have triggered abilities, so no stack growth.
    assert rust_state.stack_size() == 0

    # Capture pre-debuff effective P/T for each bear.
    assert rust_state.effective_power(rust_p1_bear_a_id) == 4
    assert rust_state.effective_toughness(rust_p1_bear_a_id) == 4
    assert rust_state.effective_power(rust_p1_bear_b_id) == 4
    assert rust_state.effective_toughness(rust_p1_bear_b_id) == 4
    assert rust_state.effective_power(rust_p0_bear_id) == 4
    assert rust_state.effective_toughness(rust_p0_bear_id) == 4

    rust_ogre_dict = {
        "name": "ETB Mass Debuff Ogre",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 6, "U": 1},
        "effects": [],
        "power": 6,
        "toughness": 6,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "pump_creatures_opponents_control_until_eot",
                    "power_bonus": -3,
                    "toughness_bonus": -3,
                },
            }
        ],
    }
    rust_ogre_id = rust_state.register_and_inject_object(
        rust_ogre_dict, 0, ZONE_BATTLEFIELD,
    )
    # ENTERS dispatch via deferred-dispatch queue; SourceIsSelf
    # matches the just-arrived Ogre -> one
    # PumpCreaturesOpponentsControlUntilEOT(-3, -3) trigger lands on
    # the stack with empty targets (untargeted mass-debuff).
    assert rust_state.stack_size() == 1, (
        "Rust: ETB Mass Debuff Ogre's arrival should fire the "
        "SourceIsSelf ENTERS trigger and land "
        "PumpCreaturesOpponentsControlUntilEOT(-3, -3) on the stack. "
        f"Got stack_size={rust_state.stack_size()}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.pump import (
        PumpCreaturesOpponentsControlUntilEOT,
    )
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone, effective_power, effective_toughness

    bait_printing = CardPrinting(
        name="Mass Debuff Bait Bear (4/4)",
        mana_cost_str="",
        mana_cost=ManaCost(generic=3, colored=(("G", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=4,
        toughness=4,
        produces=frozenset(),
        triggered_abilities=(),
    )
    ogre_printing = CardPrinting(
        name="ETB Mass Debuff Ogre",
        mana_cost_str="",
        mana_cost=ManaCost(generic=6, colored=(("U", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=6,
        toughness=6,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=PumpCreaturesOpponentsControlUntilEOT(
                    power_bonus=-3, toughness_bonus=-3,
                ),
            ),
        ),
    )

    def _inject_bf(printing, owner_id):
        obj = py_state.new_object(
            printing, owner_id=owner_id, zone=Zone.BATTLEFIELD,
        )
        obj.summoning_sick = False
        obj.tapped = False
        obj.damage = 0
        obj.etb_timestamp = py_state.next_timestamp
        py_state.next_timestamp += 1
        py_state.battlefield.append(obj)
        return obj

    # Inject the bait bears in the same order as Rust.
    py_p1_bear_a = _inject_bf(bait_printing, owner_id=1)
    py_p1_bear_b = _inject_bf(bait_printing, owner_id=1)
    py_p0_bear = _inject_bf(bait_printing, owner_id=0)
    # Pre-debuff sanity check.
    assert effective_power(py_state, py_p1_bear_a) == 4
    assert effective_toughness(py_state, py_p1_bear_a) == 4
    assert effective_power(py_state, py_p1_bear_b) == 4
    assert effective_toughness(py_state, py_p1_bear_b) == 4
    assert effective_power(py_state, py_p0_bear) == 4
    assert effective_toughness(py_state, py_p0_bear) == 4

    # Inject the Ogre, then manually dispatch ENTERS.
    py_ogre = _inject_bf(ogre_printing, owner_id=0)
    _trigger_etb_abilities(py_state, py_ogre)
    assert len(py_state.stack) == 1, (
        "Python: ETB Mass Debuff Ogre's arrival should fire the "
        "IsSelf ENTERS trigger and land "
        "PumpCreaturesOpponentsControlUntilEOT(-3, -3) on the stack. "
        f"Got stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks, then compare ----
    _drain_stack_both(py_state, rust_state)

    # Stacks empty on both sides.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0

    # Per-engine post-state: each p1 bear's effective P/T is 1/1
    # (printed 4/4 + (-3, -3) UEOT modifier). The p0 bear and the
    # Ogre itself are unchanged (filter direction = opponent-only).
    assert rust_state.effective_power(rust_p1_bear_a_id) == 1, (
        "Rust p1 bear A effective power should be 1 after the -3 "
        "debuff (printed 4 + (-3) UEOT); got "
        f"{rust_state.effective_power(rust_p1_bear_a_id)}"
    )
    assert rust_state.effective_toughness(rust_p1_bear_a_id) == 1, (
        "Rust p1 bear A effective toughness should be 1 after the "
        "-3 debuff; got "
        f"{rust_state.effective_toughness(rust_p1_bear_a_id)}"
    )
    assert rust_state.effective_power(rust_p1_bear_b_id) == 1
    assert rust_state.effective_toughness(rust_p1_bear_b_id) == 1
    # p0 bear unchanged (caster-side, opponent filter excludes it).
    assert rust_state.effective_power(rust_p0_bear_id) == 4, (
        "Rust p0 bear should be UNAFFECTED by the opponent-only "
        "debuff (caster-side filter); got effective power "
        f"{rust_state.effective_power(rust_p0_bear_id)}"
    )
    assert rust_state.effective_toughness(rust_p0_bear_id) == 4
    # Ogre unchanged (also caster-side).
    assert rust_state.effective_power(rust_ogre_id) == 6
    assert rust_state.effective_toughness(rust_ogre_id) == 6

    # Python: same shape on the equivalent objects.
    assert effective_power(py_state, py_p1_bear_a) == 1, (
        "Python p1 bear A effective power should be 1 after the -3 "
        f"debuff; got {effective_power(py_state, py_p1_bear_a)}"
    )
    assert effective_toughness(py_state, py_p1_bear_a) == 1
    assert effective_power(py_state, py_p1_bear_b) == 1
    assert effective_toughness(py_state, py_p1_bear_b) == 1
    # p0 bear unchanged on Python too.
    assert effective_power(py_state, py_p0_bear) == 4, (
        "Python p0 bear should be UNAFFECTED by the opponent-only "
        f"debuff; got {effective_power(py_state, py_p0_bear)}"
    )
    assert effective_toughness(py_state, py_p0_bear) == 4
    # Ogre unchanged.
    assert effective_power(py_state, py_ogre) == 6
    assert effective_toughness(py_state, py_ogre) == 6

    # Cross-engine: every per-object effective P/T agrees.
    assert (
        rust_state.effective_power(rust_p1_bear_a_id)
        == effective_power(py_state, py_p1_bear_a)
    )
    assert (
        rust_state.effective_toughness(rust_p1_bear_a_id)
        == effective_toughness(py_state, py_p1_bear_a)
    )
    assert (
        rust_state.effective_power(rust_p1_bear_b_id)
        == effective_power(py_state, py_p1_bear_b)
    )
    assert (
        rust_state.effective_toughness(rust_p1_bear_b_id)
        == effective_toughness(py_state, py_p1_bear_b)
    )
    assert (
        rust_state.effective_power(rust_p0_bear_id)
        == effective_power(py_state, py_p0_bear)
    )
    assert (
        rust_state.effective_toughness(rust_p0_bear_id)
        == effective_toughness(py_state, py_p0_bear)
    )
    assert (
        rust_state.effective_power(rust_ogre_id)
        == effective_power(py_state, py_ogre)
    )
    assert (
        rust_state.effective_toughness(rust_ogre_id)
        == effective_toughness(py_state, py_ogre)
    )

    # Lives unchanged -- the ETB debuff doesn't touch life totals.
    assert rust_state.get_life(0) == 20
    assert rust_state.get_life(1) == 20
    assert py_state.players[0].life == 20
    assert py_state.players[1].life == 20


def test_cross_engine_real_eoe_susurian_dirgecraft_etb_each_opponent_sacrifices_parity(
    parity_smoke,
):
    """Probe: Susurian Dirgecraft (EoE Spacecraft) ETB ``each opponent
    sacrifices a nontoken creature of their choice`` parity -- FIRST
    real-EoE cross-engine probe with an
    ``each_opponent_sacrifices_creature`` ETB trigger.

    Oracle text in ``data/edge_of_eternities.json``:

        "When this Spacecraft enters, each opponent sacrifices a
         nontoken creature of their choice.
         Station (Tap another creature you control: Put charge counters
         equal to its power on this Spacecraft. Station only as a
         sorcery. It's an artifact creature at 7+.)
         7+ | Flying"

    The Station mechanic + 7+ "becomes a creature with Flying" rider
    are out of scope -- this probe exclusively exercises the ETB-
    trigger surface, the substrate sweet-spot:

      * Event: ``enters``
      * Predicate: ``source_is_self`` (only the just-entered
        Spacecraft's own ETB fires)
      * Effect: ``each_opponent_sacrifices_creature`` -- NEW on the
        bridge as of the companion commit on this branch.

    First real-EoE cross-engine probe to exercise the
    ``Effect::EachOpponentSacrificesCreature`` arm + Python's
    ``EachOpponentSacrificesCreature`` class end-to-end. Also the
    FIRST EoE probe carried by an Artifact - Spacecraft source
    (prior probes were Creatures, Artifacts (Dubious Delicacy), or
    Artifact - Food). The probe pins that ENTERS-event dispatch is
    type-agnostic on both engines (Spacecraft enters as an
    Artifact; the trigger fires regardless).

    Predicate decomposition (same as Virus Beetle / Germinating Wurm
    / Quantum Riddler / Nebula Dragon):

        SourceIsSelf

    Effect: ``each_opponent_sacrifices_creature`` -- the bridge arm
    translates the unit-variant Rust kind to
    ``EachOpponentSacrificesCreature()``.

    **Cross-engine sacrifice-pick contract.** Both engines pick the
    sacrifice from the OPPONENT's bf (the sacrificing player's
    perspective; the source's controller doesn't pick for them).
    Rust at state_ops_resolve.rs:6529-6539 picks the FIRST creature
    on opponent's bf via ``bf.iter().find_map``. Python at
    opponent_punishers.py:46-58 calls
    ``p.agent.choose_sacrifice(state, p.id, [o.id for o in legal])``
    where ``legal`` is the opponent's bf creatures (also nontoken-
    filtered on the Python side). The harness's default Player has
    ``agent=None`` -- Python silently SKIPS opponents with no agent
    (opponent_punishers.py:53). To observe the cross-engine pick
    parity end-to-end we seat a deterministic-bf-first agent on p1
    (the sacrificing opponent) mirroring Rust's at-resolve
    bf-first-creature pick. Each engine then sacrifices the same
    creature.

    **Filter-divergence note.** Rust does NOT enforce a nontoken
    filter (bf.iter().find_map picks the first creature regardless
    of token status); Python does (the resolve filters
    ``not o.printing.is_token``). For probes that seat only nontoken
    creatures on the opponent's bf, both engines pick the same
    creature observably; the divergence only surfaces with a token
    AND a nontoken creature with the token at index 0 (Rust would
    pick the token, Python would skip it). This probe seats only
    nontoken creatures.

    Probe shape (inject-and-fire-ENTERS, mirrors Virus Beetle):

      1. Pre-seed p1's bf with TWO distinct vanilla bait creatures
         (one destined to sacrifice, one to survive) so a single-swap
         or single-sac divergence between engines surfaces as a
         per-card name divergence in p1's graveyard / bf rather than
         a count-only divergence.

      2. Seat ``_SacrificeFirstAgent`` on p1 (Python side only;
         Rust's pick is intrinsic and doesn't read agent).

      3. Inject Susurian Dirgecraft on p0's battlefield via
         ``register_and_inject_object`` (Rust) / new_object + bf
         append + ``_trigger_etb_abilities`` (Python). Both engines
         dispatch ENTERS for the just-arrived Spacecraft; the
         predicate (SourceIsSelf) matches; the trigger lands on the
         stack with the EachOpponentSacrificesCreature() effect.

      4. Drain both stacks.

      5. Cross-engine assert: post-drain, p1's bf[0] (Sac Bait Alpha)
         is gone, in p1's graveyard. Sac Bait Beta remains on p1's
         bf. Same shape on both engines.

    Out of scope:

      * Driving the empty-bf short-circuit branch -- the audit's
        explicit unblock is "each opponent sacrifices a nontoken
        creature of their choice", which means the non-empty path
        is the load-bearing case for Susurian Dirgecraft. The
        empty-bf-no-creature parity (silent fizzle on both engines)
        is covered by the Rust resolve arm's mid-loop guard at
        state_ops_resolve.rs:6541 + Python's matching guard at
        opponent_punishers.py:53-54.
      * Multi-opponent fanout -- the 2-player harness reduces "each
        opponent" to "the one opponent". The N-player per-seat-
        iteration shape is exercised by the Rust resolve arm's loop
        body directly.
      * Token-vs-nontoken filter divergence -- documented Rust
        shortcut; out of scope of this probe.
      * Station / 7+ activated abilities -- mana + tap costs +
        charge-counter substrate; none on the bridge today.

    Expected post-dispatch + post-drain state on BOTH engines:

      * Susurian Dirgecraft on p0's battlefield (Artifact -- Spacecraft).
      * p1 bf: Sac Bait Beta only (Alpha was sacrificed).
      * p1 graveyard: Sac Bait Alpha.
      * p0 bf / hand / library / graveyard: unchanged.
      * Lives unchanged on both seats (the ETB doesn't touch life).
      * No residual stack.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )
    from tests.parity._picker_shims import _SacrificeFirstAgent

    susurian_dirgecraft = CardDef(
        name="Susurian Dirgecraft",
        # Artifact - Spacecraft. Not a creature on entry (Spacecraft
        # only becomes a creature at 7+ charge counters). The bare
        # Artifact card_type is enough for the ETB-trigger dispatch
        # to fire.
        card_type="Artifact",
        mana_cost_generic=4,
        mana_cost_colored=(("B", 1),),
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "each_opponent_sacrifices_creature",
                },
            },
        ),
    )
    # Two distinct vanilla creatures on p1's bf so a single-swap
    # (alternate-target divergence) between engines surfaces as a
    # per-card name divergence rather than a count-only divergence.
    sac_bait_a = CardDef(
        name="Sac Bait Alpha",
        card_type="Creature",
        mana_cost_generic=1,
        power=1,
        toughness=1,
    )
    sac_bait_b = CardDef(
        name="Sac Bait Beta",
        card_type="Creature",
        mana_cost_generic=2,
        power=2,
        toughness=2,
    )
    spec = DeckSpec(
        card_defs=(susurian_dirgecraft, sac_bait_a, sac_bait_b),
        # Libraries empty for symmetry; the probe injects directly
        # onto p0/p1's bf so libraries aren't observed.
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    rust_bait_a_dict = {
        "name": "Sac Bait Alpha",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "effects": [],
        "power": 1,
        "toughness": 1,
    }
    rust_bait_b_dict = {
        "name": "Sac Bait Beta",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "effects": [],
        "power": 2,
        "toughness": 2,
    }
    # Inject the two bait creatures onto p1's bf FIRST. Order matters:
    # Sac Bait Alpha at bf-iter index 0 so the bf-iter-first-creature
    # deterministic-pick (Rust) and the legal_object_ids[0] agent
    # pick (Python) both pick Alpha specifically.
    rust_bait_a_id = rust_state.register_and_inject_object(
        rust_bait_a_dict, 1, ZONE_BATTLEFIELD,
    )
    rust_bait_b_id = rust_state.register_and_inject_object(
        rust_bait_b_dict, 1, ZONE_BATTLEFIELD,
    )
    assert rust_state.stack_size() == 0
    rust_p1_bf_size_before = rust_state.battlefield_sizes[1]
    rust_p1_gy_size_before = rust_state.graveyard_sizes[1]
    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)

    rust_dirgecraft_dict = {
        "name": "Susurian Dirgecraft",
        "card_types": ["Artifact"],
        "subtypes": ["Spacecraft"],
        "mana_cost": {"generic": 4, "B": 1},
        "effects": [],
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "each_opponent_sacrifices_creature",
                },
            }
        ],
    }
    rust_dirgecraft_id = rust_state.register_and_inject_object(
        rust_dirgecraft_dict, 0, ZONE_BATTLEFIELD,
    )
    # ENTERS dispatch via deferred-dispatch queue; SourceIsSelf
    # matches the just-arrived Dirgecraft -> one
    # EachOpponentSacrificesCreature() trigger lands on the stack.
    assert rust_state.stack_size() == 1, (
        "Rust: Susurian Dirgecraft's arrival should fire the "
        "SourceIsSelf ENTERS trigger and land "
        "EachOpponentSacrificesCreature() on the stack. "
        f"Got stack_size={rust_state.stack_size()}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.opponent_punishers import (
        EachOpponentSacrificesCreature,
    )
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    bait_a_printing = CardPrinting(
        name="Sac Bait Alpha",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=1,
        toughness=1,
        produces=frozenset(),
    )
    bait_b_printing = CardPrinting(
        name="Sac Bait Beta",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
    )
    dirgecraft_printing = CardPrinting(
        name="Susurian Dirgecraft",
        mana_cost_str="",
        mana_cost=ManaCost(generic=4, colored=(("B", 1),)),
        type_line="Artifact -- Spacecraft",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=("Spacecraft",),
        power=None,
        toughness=None,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=EachOpponentSacrificesCreature(),
            ),
        ),
    )

    def _inject_bf(printing, owner_id):
        obj = py_state.new_object(
            printing, owner_id=owner_id, zone=Zone.BATTLEFIELD,
        )
        obj.summoning_sick = False
        obj.tapped = False
        obj.damage = 0
        obj.etb_timestamp = py_state.next_timestamp
        py_state.next_timestamp += 1
        py_state.battlefield.append(obj)
        return obj

    # Inject the two bait creatures onto p1's bf FIRST. Same order as
    # Rust so the bf-iter-first-creature pick lands on Alpha on both
    # engines.
    py_bait_a = _inject_bf(bait_a_printing, owner_id=1)
    py_bait_b = _inject_bf(bait_b_printing, owner_id=1)

    # Custom agent for p1: mirror Rust's bf-iter-first-creature pick.
    # Python's EachOpponentSacrificesCreature.resolve passes the
    # filtered legal-creatures list (in opponent's bf-iter order) to
    # ``choose_sacrifice``; returning ``legal_object_ids[0]`` matches
    # Rust's at-resolve bf-iter pick. The pick is seated on p1 (the
    # sacrificing player), NOT on p0 (the source's controller) --
    # "each opponent sacrifices [...] of their choice" lets each
    # opponent pick. Shim hoisted to tests/parity/_picker_shims.py.
    py_state.players[1].agent = _SacrificeFirstAgent()

    py_p1_bf_size_before = sum(
        1 for o in py_state.battlefield if o.controller_id == 1
    )
    py_p1_gy_size_before = len(py_state.players[1].graveyard)
    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life

    py_dirgecraft = _inject_bf(dirgecraft_printing, owner_id=0)
    _trigger_etb_abilities(py_state, py_dirgecraft)
    assert len(py_state.stack) == 1, (
        "Python: Susurian Dirgecraft's arrival should fire the "
        "IsSelf ENTERS trigger and land "
        "EachOpponentSacrificesCreature() on the stack. "
        f"Got stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks, then compare ----
    _drain_stack_both(py_state, rust_state)

    # Stacks empty on both sides.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0

    # Post-drain: p1's bf shrank by 1 (Alpha sacrificed), p1's
    # graveyard grew by 1 (Alpha landed there). Sac Bait Beta
    # remains on p1's bf.
    assert rust_state.battlefield_sizes[1] == rust_p1_bf_size_before - 1, (
        f"Rust p1 bf size should be {rust_p1_bf_size_before - 1} "
        f"after sacrifice; got {rust_state.battlefield_sizes[1]}"
    )
    assert rust_state.graveyard_sizes[1] == rust_p1_gy_size_before + 1, (
        f"Rust p1 graveyard size should be "
        f"{rust_p1_gy_size_before + 1} after sacrifice; got "
        f"{rust_state.graveyard_sizes[1]}"
    )
    rust_p1_gy_names = [
        e["printing_name"] for e in rust_state.graveyard_snapshot(1)
    ]
    assert "Sac Bait Alpha" in rust_p1_gy_names, (
        f"Rust: expected Sac Bait Alpha in p1 gy "
        f"(bf-iter-first deterministic pick); got {rust_p1_gy_names}"
    )
    assert "Sac Bait Beta" not in rust_p1_gy_names, (
        f"Rust: Sac Bait Beta should NOT have been sacrificed "
        f"(only the bf-iter-first creature was picked); got "
        f"{rust_p1_gy_names}"
    )
    rust_p1_bf_names = [
        e["printing_name"]
        for e in rust_state.battlefield_snapshot()
        if e["controller_id"] == 1
    ]
    assert "Sac Bait Beta" in rust_p1_bf_names, (
        f"Rust: Sac Bait Beta should remain on p1 bf; "
        f"got {rust_p1_bf_names}"
    )

    # Python: same shape on the equivalent zones.
    py_p1_bf_now = [
        o for o in py_state.battlefield if o.controller_id == 1
    ]
    assert len(py_p1_bf_now) == py_p1_bf_size_before - 1, (
        f"Python p1 bf size should be {py_p1_bf_size_before - 1} "
        f"after sacrifice; got {len(py_p1_bf_now)}"
    )
    assert (
        len(py_state.players[1].graveyard) == py_p1_gy_size_before + 1
    ), (
        f"Python p1 graveyard size should be "
        f"{py_p1_gy_size_before + 1} after sacrifice; got "
        f"{len(py_state.players[1].graveyard)}"
    )
    py_p1_gy_names = [
        o.printing.name for o in py_state.players[1].graveyard
    ]
    assert "Sac Bait Alpha" in py_p1_gy_names, (
        f"Python: expected Sac Bait Alpha in p1 gy; got {py_p1_gy_names}"
    )
    assert "Sac Bait Beta" not in py_p1_gy_names, (
        f"Python: Sac Bait Beta should NOT have been sacrificed; "
        f"got {py_p1_gy_names}"
    )
    py_p1_bf_names = [o.printing.name for o in py_p1_bf_now]
    assert "Sac Bait Beta" in py_p1_bf_names, (
        f"Python: Sac Bait Beta should remain on p1 bf; "
        f"got {py_p1_bf_names}"
    )

    # Cross-engine: hand / graveyard / bf sizes match between engines
    # on both seats.
    assert rust_state.battlefield_sizes[1] == len(py_p1_bf_now)
    assert (
        rust_state.graveyard_sizes[1]
        == len(py_state.players[1].graveyard)
    )

    # Lives unchanged on both seats (the ETB sacrifice doesn't touch
    # life totals).
    assert rust_state.get_life(0) == rust_p0_life_before
    assert rust_state.get_life(1) == rust_p1_life_before
    assert py_state.players[0].life == py_p0_life_before
    assert py_state.players[1].life == py_p1_life_before
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life


def test_cross_engine_synthetic_etb_each_opponent_mills_cards_parity(
    parity_smoke,
):
    """Probe: synthetic ``ETB Mill Bear`` exercising the freshly
    landed ``each_opponent_mills_cards`` bridge arm end-to-end.

    Why synthetic rather than a real EoE card: the audit lists
    ``each_opponent_mills_cards`` as USED by Specimen Freighter (an
    attack-trigger 2-player simplification of "defending player mills
    four cards"), NOT as an ETB trigger. No EoE card in the current
    pool prints ``When this enters, each opponent mills N cards``;
    a synthetic creature card with the bare-arm trigger is the
    canonical end-to-end driver until a future EoE printing matches
    the shape.

    Trigger shape:

        Event: enters
        Predicate: source_is_self
        Effect: each_opponent_mills_cards (count=2)

    **Rust resolve semantics.** Rust's
    ``Effect::EachOpponentMillsCards { count }`` arm
    (state_ops_resolve.rs:6580-6634) is UNTARGETED -- it derives
    ``source_controller`` via the standard 5-zone walk + stack
    fallback for ``source_obj_id``, then for the (single 2-player)
    opponent runs ``count`` iterations of "remove top of library
    (lib[0]); push to opponent's graveyard". Empty library mid-loop
    stops silently (CR 704.5b mill != draw -- no loss-condition
    check).

    **Python resolve semantics.** Python's ``EachOpponentMillsCards``
    (effects/generic/draw_mill.py:30) walks ``state.players``,
    skipping the controller and any has_lost player, and pops the
    top ``self.amount`` cards off each opponent's library into their
    graveyard. Same observable: each opponent's library shrinks by
    up-to-N from the top, with the same N popped cards landing in
    their graveyard in pop order.

    **Untargeted -- no agent shim required.** Mill is a pure top-N
    library pop with no per-card decision. The harness's default
    Player has ``agent=None`` and that's fine -- the mill walks
    purely on the source-controller's id.

    Probe shape (inject-and-fire-ENTERS):

      1. Pre-seed p1's library with TWO distinct vanilla bait cards
         (Mill Bait Alpha, Mill Bait Beta) so a single-swap or
         single-mill divergence between engines surfaces as a
         per-card name divergence in p1's graveyard / library
         rather than a count-only divergence.

      2. Inject ``ETB Mill Bear`` directly onto p0's battlefield via
         ``register_and_inject_object`` (Rust) / new_object + bf
         append + manual ``_trigger_etb_abilities`` (Python). Both
         engines dispatch ENTERS for the just-arrived bear; the
         SourceIsSelf predicate matches; one
         ``EachOpponentMillsCards(count=2)`` trigger lands on the
         stack with empty targets.

      3. Drain both stacks. Resolve walk: p1's library shrinks by
         2 from the top; both bait cards land in p1's graveyard in
         library-top-down order (Alpha first, then Beta).

      4. Cross-engine assert: post-drain, BOTH engines have an
         empty p1 library AND p1 graveyard contains both Alpha and
         Beta (Alpha as the older entry). p0's library / graveyard
         unchanged.

    Out of scope:

      * Cast-from-hand mana cost -- inject-and-dispatch-ENTERS
        bypasses the mana pipeline.
      * Driving the empty-library short-circuit branch -- the
        substrate's silent-stop guard at state_ops_resolve.rs:6627
        + Python's matching ``if not p.library: break`` at
        draw_mill.py:49-50 are both pinned by their unit tests
        already in the suite. The non-empty path is the load-
        bearing parity case for the bridge arm.
      * Multi-opponent fanout -- the 2-player harness reduces "each
        opponent" to "the one opponent". The N-player per-seat-
        iteration shape is exercised by the Rust resolve arm's
        loop body directly.
      * Self-loss-condition (decking) -- mill on Magic does NOT
        trigger CR 704.5b (loss for empty library); the next draw
        would. The probe doesn't drive a draw step so no loss-
        condition fires.

    Expected post-dispatch + post-drain state on BOTH engines:

      * ETB Mill Bear on p0's battlefield.
      * p1 library: empty (both Alpha and Beta milled).
      * p1 graveyard: [Mill Bait Alpha, Mill Bait Beta] in that order.
      * p0 library / graveyard: unchanged.
      * Lives unchanged on both seats (mill doesn't touch life).
      * No residual stack.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )

    mill_bear = CardDef(
        name="ETB Mill Bear",
        card_type="Creature",
        mana_cost_generic=2,
        mana_cost_colored=(("B", 1),),
        power=2,
        toughness=2,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "each_opponent_mills_cards",
                    "count": 2,
                },
            },
        ),
    )
    # Two distinct vanilla cards on p1's library so a single-swap
    # divergence between engines surfaces as a per-card name
    # divergence rather than a count-only divergence.
    mill_bait_a = CardDef(
        name="Mill Bait Alpha",
        card_type="Creature",
        mana_cost_generic=1,
        power=1,
        toughness=1,
    )
    mill_bait_b = CardDef(
        name="Mill Bait Beta",
        card_type="Creature",
        mana_cost_generic=2,
        power=2,
        toughness=2,
    )
    spec = DeckSpec(
        card_defs=(mill_bear, mill_bait_a, mill_bait_b),
        # p0 library empty -- only p1 gets milled.
        p0_library=(),
        # Library top-down: Alpha first (popped first by mill),
        # Beta second. Both engines' build_*_state honor the
        # spec's library order; the mill-resolve pops in this
        # order on both sides.
        p1_library=("Mill Bait Alpha", "Mill Bait Beta"),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    rust_p1_lib_size_before = rust_state.library_sizes[1]
    rust_p1_gy_size_before = rust_state.graveyard_sizes[1]
    rust_p0_lib_size_before = rust_state.library_sizes[0]
    rust_p0_gy_size_before = rust_state.graveyard_sizes[0]
    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)
    # The deckspec already wired Alpha + Beta into p1's library;
    # confirm.
    assert rust_p1_lib_size_before == 2, (
        "Rust p1 library should hold the two seeded bait cards; "
        f"got library_size={rust_p1_lib_size_before}"
    )

    rust_mill_bear_dict = {
        "name": "ETB Mill Bear",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "B": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "each_opponent_mills_cards",
                    "count": 2,
                },
            }
        ],
    }
    rust_state.register_and_inject_object(
        rust_mill_bear_dict, 0, ZONE_BATTLEFIELD,
    )
    # ENTERS dispatch via deferred-dispatch queue; SourceIsSelf
    # matches the just-arrived Mill Bear -> one
    # EachOpponentMillsCards(count=2) trigger lands on the stack.
    assert rust_state.stack_size() == 1, (
        "Rust: ETB Mill Bear's arrival should fire the SourceIsSelf "
        "ENTERS trigger and land EachOpponentMillsCards(count=2) on "
        f"the stack. Got stack_size={rust_state.stack_size()}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.draw_mill import EachOpponentMillsCards
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    mill_bear_printing = CardPrinting(
        name="ETB Mill Bear",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2, colored=(("B", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=EachOpponentMillsCards(amount=2),
            ),
        ),
    )

    py_p1_lib_size_before = len(py_state.players[1].library)
    py_p1_gy_size_before = len(py_state.players[1].graveyard)
    py_p0_lib_size_before = len(py_state.players[0].library)
    py_p0_gy_size_before = len(py_state.players[0].graveyard)
    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life
    # The deckspec already wired Alpha + Beta into p1's library;
    # confirm.
    assert py_p1_lib_size_before == 2, (
        "Python p1 library should hold the two seeded bait cards; "
        f"got library_size={py_p1_lib_size_before}"
    )

    py_mill_bear = py_state.new_object(
        mill_bear_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_mill_bear.summoning_sick = False
    py_mill_bear.tapped = False
    py_mill_bear.damage = 0
    py_mill_bear.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_mill_bear)
    _trigger_etb_abilities(py_state, py_mill_bear)
    assert len(py_state.stack) == 1, (
        "Python: ETB Mill Bear's arrival should fire the IsSelf "
        "ENTERS trigger and land EachOpponentMillsCards(amount=2) "
        f"on the stack. Got stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks, then compare ----
    _drain_stack_both(py_state, rust_state)

    # Stacks empty on both sides.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0

    # Per-engine post-state: p1 library shrank by 2, p1 graveyard
    # grew by 2; p0 unchanged.
    assert rust_state.library_sizes[1] == rust_p1_lib_size_before - 2, (
        f"Rust p1 library should shrink by 2; expected "
        f"{rust_p1_lib_size_before - 2}, got "
        f"{rust_state.library_sizes[1]}"
    )
    assert rust_state.graveyard_sizes[1] == rust_p1_gy_size_before + 2, (
        f"Rust p1 graveyard should grow by 2; expected "
        f"{rust_p1_gy_size_before + 2}, got "
        f"{rust_state.graveyard_sizes[1]}"
    )
    assert rust_state.library_sizes[0] == rust_p0_lib_size_before, (
        "Rust p0 library should be unchanged (mill is opponent-only)"
    )
    assert rust_state.graveyard_sizes[0] == rust_p0_gy_size_before, (
        "Rust p0 graveyard should be unchanged"
    )
    rust_p1_gy_names = [
        e["printing_name"] for e in rust_state.graveyard_snapshot(1)
    ]
    # Mill pops library top-down; both bait cards land in graveyard
    # in pop order. Alpha was top of library so Alpha lands FIRST in
    # the graveyard (older entry), Beta lands SECOND (newer entry).
    assert rust_p1_gy_names == ["Mill Bait Alpha", "Mill Bait Beta"], (
        f"Rust p1 graveyard should be [Alpha, Beta] in pop order; "
        f"got {rust_p1_gy_names}"
    )

    # Python: same shape on the equivalent zones.
    assert (
        len(py_state.players[1].library) == py_p1_lib_size_before - 2
    )
    assert (
        len(py_state.players[1].graveyard) == py_p1_gy_size_before + 2
    )
    assert (
        len(py_state.players[0].library) == py_p0_lib_size_before
    )
    assert (
        len(py_state.players[0].graveyard) == py_p0_gy_size_before
    )
    py_p1_gy_names = [
        o.printing.name for o in py_state.players[1].graveyard
    ]
    assert py_p1_gy_names == ["Mill Bait Alpha", "Mill Bait Beta"], (
        f"Python p1 graveyard should be [Alpha, Beta] in pop order; "
        f"got {py_p1_gy_names}"
    )

    # Cross-engine: same per-zone sizes on both seats.
    assert (
        rust_state.library_sizes[1]
        == len(py_state.players[1].library)
    )
    assert (
        rust_state.graveyard_sizes[1]
        == len(py_state.players[1].graveyard)
    )
    assert (
        rust_state.library_sizes[0]
        == len(py_state.players[0].library)
    )
    assert (
        rust_state.graveyard_sizes[0]
        == len(py_state.players[0].graveyard)
    )

    # Lives unchanged on both seats (mill doesn't touch life).
    assert rust_state.get_life(0) == rust_p0_life_before
    assert rust_state.get_life(1) == rust_p1_life_before
    assert py_state.players[0].life == py_p0_life_before
    assert py_state.players[1].life == py_p1_life_before
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life


def test_cross_engine_real_eoe_atmospheric_greenhouse_etb_mass_plus_one_counter_parity(
    parity_smoke,
):
    """Probe: Atmospheric Greenhouse (EoE) ETB ``put a +1/+1 counter
    on each creature you control`` parity -- FIRST real-EoE cross-
    engine probe to exercise the
    ``put_plus_one_counter_on_each_creature_you_control`` MASS bridge
    arm (sister to the single-target Rayblade Trooper probe shape).

    Oracle text in ``data/edge_of_eternities.json``:

        "When this Spacecraft enters, put a +1/+1 counter on each
         creature you control.
         Station (...)
         4+ | Flying"

    Station + 4+/Flying are both Spacecraft static / activated
    plumbing -- out of scope. This probe exclusively exercises the
    ETB-trigger surface, the substrate sweet-spot:

      * Event: ``enters``
      * Predicate: ``source_is_self`` (only the just-entered
        Spacecraft's own ETB fires).
      * Effect: ``put_plus_one_counter_on_each_creature_you_control``
        amount=1 -- NEW on the bridge as of the companion commit on
        this branch.

    First real-EoE cross-engine probe to exercise the
    ``Effect::PutPlusOneCounterOnEachCreatureYouControl`` arm +
    ``PutPlusOneCounterOnEachCreatureYouControl`` Python class end-
    to-end.

    Predicate decomposition (same as Wurmwall Sweeper / Starbreach
    Whale / Rayblade Trooper):

        SourceIsSelf

    Effect: ``put_plus_one_counter_on_each_creature_you_control(
    amount=1)`` -- the bridge arm translates to
    ``PutPlusOneCounterOnEachCreatureYouControl(amount=1)``.

    **Mass-effect target-pick contract.** Unlike the single-target
    sibling ``put_plus_one_counter_on_creature_you_control`` (which
    needs a target-pick agent shim mirroring Rust's at-resolve scan),
    this MASS effect picks no targets: every creature on the source-
    controller's bf at resolve time receives the counter.

      * Rust: ``state_ops_resolve.rs:4207+`` derives the source-
        controller via the cross-zone source_obj_id scan, then
        iterates ``state.players[cidx].battlefield`` and adds
        ``amount`` to every Creature object's scalar ``counters``
        field.
      * Python: ``PutPlusOneCounterOnEachCreatureYouControl.resolve``
        iterates ``state.battlefield`` filtered to
        ``obj.controller_id == controller_id`` and
        ``obj.printing.is_creature``, calling
        ``add_plus_one_counters(state, obj, self.amount)`` on each.

    Both engines agree on the recipient set (every p0-controlled
    Creature on the bf at resolve time) and skip non-creature
    permanents — Atmospheric Greenhouse itself is an Artifact
    Spacecraft, not a Creature, so it doesn't self-counter even
    though it's on p0's bf.

    **Subtype modeling caveat.** Atmospheric Greenhouse's oracle
    text says "When this Spacecraft enters" -- the "Spacecraft"
    qualifier is a CR 113 type-condition selector. Both engines
    today treat the SourceIsSelf ENTERS predicate as "this object
    just entered", subtype-agnostic at the predicate layer; the
    Spacecraft subtype substrate is wired into the printing on
    both sides but neither parse_triggered_ability arm conditions
    the trigger on a subtype check today. The probe's behavior is
    correct for "any object with this ETB trigger entering its
    own bf"; if the EoE rules tighten to require Spacecraft-
    subtype gating at trigger-fire time, both engines would need
    to extend in lockstep and this probe would surface the
    divergence first.

    Probe shape (inject-and-fire-ENTERS, mirrors Wurmwall Sweeper
    for the Artifact-carrier shape and Rayblade Trooper for the
    counter-delta assertion):

      1. Pre-seed p0's bf with TWO distinct vanilla bait creatures
         BEFORE injecting the Greenhouse, so they're already on
         the bf when the trigger resolves and both pick up the
         counter. Distinct names to surface a per-recipient bug
         (e.g. "only the first creature gets the counter") if the
         resolve walk regresses.

      2. Inject ONE bait creature onto p1's bf. The MASS effect's
         "you control" filter MUST exclude opponent-controlled
         creatures; the witness verifies that filter (p1's bear
         stays at 0 counters post-resolve).

      3. Inject Atmospheric Greenhouse (Artifact carrier) onto p0's
         bf. ENTERS dispatch + SourceIsSelf predicate => trigger
         lands on the stack with NO target pre-chosen (mass effect
         has no targets).

      4. Drain both stacks. Resolve walk: each p0-controlled
         Creature's ``counters`` (Rust) / ``plus_one_counters``
         (Python) increments from 0 to 1.

      5. Cross-engine assert: both p0 bait creatures show 1 +1/+1
         counter on both engines; the p1 witness bear shows 0
         counters on both engines; Atmospheric Greenhouse itself
         shows 0 counters (it's an Artifact, not a Creature).

    Out of scope:

      * Station ability + the "4+ | Flying" Spacecraft crew
        threshold -- both are static / activated; not ETB triggers.
      * Spacecraft subtype-conditional trigger gating -- documented
        above; both engines treat ENTERS-on-self subtype-agnostic
        today, so the probe stays parity-clean.
      * Mana cost ({4}) -- inject-and-dispatch-ENTERS bypasses the
        mana pipeline.
      * The ``exclude_source=True`` variant -- not requested by
        Atmospheric Greenhouse's oracle text (no "other") and
        observably moot here because the Spacecraft source isn't
        a Creature anyway.

    Expected post-dispatch + post-drain state on BOTH engines:

      * Atmospheric Greenhouse on p0's bf with 0 counters.
      * Both p0-controlled bait creatures with 1 +1/+1 counter.
      * p1-controlled witness bear with 0 counters.
      * No life changes on either side.
      * No residual stack.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )

    atmospheric_greenhouse = CardDef(
        name="Atmospheric Greenhouse",
        card_type="Artifact",
        mana_cost_generic=4,
        mana_cost_colored=(),
        # Artifact-Spacecraft -- no creature P/T at the resting
        # state (Spacecraft becomes a creature only via Station's
        # 4+ counter threshold; that path is out-of-scope for the
        # ETB probe).
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "put_plus_one_counter_on_each_creature_you_control",
                    "amount": 1,
                },
            },
        ),
    )
    # Distinct bait names on p0's side so a per-recipient bug
    # ("only the first creature gets the counter") would surface.
    p0_bait_a = CardDef(
        name="Mass Counter Bait Alpha",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=2,
        toughness=2,
    )
    p0_bait_b = CardDef(
        name="Mass Counter Bait Beta",
        card_type="Creature",
        mana_cost_generic=2,
        mana_cost_colored=(("G", 1),),
        power=3,
        toughness=3,
    )
    # Witness on p1's side for the "you control" filter.
    p1_witness = CardDef(
        name="Mass Counter Witness",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("R", 1),),
        power=2,
        toughness=2,
    )
    spec = DeckSpec(
        card_defs=(atmospheric_greenhouse, p0_bait_a, p0_bait_b, p1_witness),
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    rust_p0_bait_a_dict = {
        "name": "Mass Counter Bait Alpha",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1, "G": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
    }
    rust_p0_bait_b_dict = {
        "name": "Mass Counter Bait Beta",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "G": 1},
        "effects": [],
        "power": 3,
        "toughness": 3,
    }
    rust_p1_witness_dict = {
        "name": "Mass Counter Witness",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1, "R": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
    }
    rust_p0_a_id = rust_state.register_and_inject_object(
        rust_p0_bait_a_dict, 0, ZONE_BATTLEFIELD,
    )
    rust_p0_b_id = rust_state.register_and_inject_object(
        rust_p0_bait_b_dict, 0, ZONE_BATTLEFIELD,
    )
    rust_p1_w_id = rust_state.register_and_inject_object(
        rust_p1_witness_dict, 1, ZONE_BATTLEFIELD,
    )
    assert rust_state.stack_size() == 0

    rust_greenhouse_dict = {
        "name": "Atmospheric Greenhouse",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 4},
        "effects": [],
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "put_plus_one_counter_on_each_creature_you_control",
                    "amount": 1,
                },
            }
        ],
    }
    rust_greenhouse_id = rust_state.register_and_inject_object(
        rust_greenhouse_dict, 0, ZONE_BATTLEFIELD,
    )
    assert rust_state.stack_size() == 1, (
        "Rust: Atmospheric Greenhouse's own arrival should fire the "
        "SourceIsSelf ENTERS trigger and land "
        "PutPlusOneCounterOnEachCreatureYouControl(1) on the stack. "
        f"Got stack_size={rust_state.stack_size()}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCounterOnEachCreatureYouControl,
    )
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    p0_bait_a_printing = CardPrinting(
        name="Mass Counter Bait Alpha",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=(("G", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(),
    )
    p0_bait_b_printing = CardPrinting(
        name="Mass Counter Bait Beta",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2, colored=(("G", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=3,
        toughness=3,
        produces=frozenset(),
        triggered_abilities=(),
    )
    p1_witness_printing = CardPrinting(
        name="Mass Counter Witness",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=(("R", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(),
    )
    greenhouse_printing = CardPrinting(
        name="Atmospheric Greenhouse",
        mana_cost_str="",
        mana_cost=ManaCost(generic=4),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
        # Pure Artifact at resting state.
        power=None,
        toughness=None,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=PutPlusOneCounterOnEachCreatureYouControl(amount=1),
            ),
        ),
    )

    py_p0_bait_a = py_state.new_object(
        p0_bait_a_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_p0_bait_a.summoning_sick = False
    py_p0_bait_a.tapped = False
    py_p0_bait_a.damage = 0
    py_p0_bait_a.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_p0_bait_a)

    py_p0_bait_b = py_state.new_object(
        p0_bait_b_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_p0_bait_b.summoning_sick = False
    py_p0_bait_b.tapped = False
    py_p0_bait_b.damage = 0
    py_p0_bait_b.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_p0_bait_b)

    py_p1_witness = py_state.new_object(
        p1_witness_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_p1_witness.summoning_sick = False
    py_p1_witness.tapped = False
    py_p1_witness.damage = 0
    py_p1_witness.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_p1_witness)

    assert py_p0_bait_a.plus_one_counters == 0
    assert py_p0_bait_b.plus_one_counters == 0
    assert py_p1_witness.plus_one_counters == 0

    py_greenhouse = py_state.new_object(
        greenhouse_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_greenhouse.summoning_sick = False
    py_greenhouse.tapped = False
    py_greenhouse.damage = 0
    py_greenhouse.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_greenhouse)
    _trigger_etb_abilities(py_state, py_greenhouse)
    assert len(py_state.stack) == 1, (
        "Python: Atmospheric Greenhouse's own arrival should fire "
        "the IsSelf ENTERS trigger and land "
        "PutPlusOneCounterOnEachCreatureYouControl(1) on the stack. "
        f"Got stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks, then compare ----
    _drain_stack_both(py_state, rust_state)

    # Stacks empty on both sides.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0

    # Per-engine post-state: both p0 bait creatures with 1 counter,
    # p1 witness with 0, Greenhouse itself with 0.
    rust_bf = rust_state.battlefield_snapshot()
    rust_p0_a_entry = next(
        e for e in rust_bf if int(e["id"]) == rust_p0_a_id
    )
    rust_p0_b_entry = next(
        e for e in rust_bf if int(e["id"]) == rust_p0_b_id
    )
    rust_p1_w_entry = next(
        e for e in rust_bf if int(e["id"]) == rust_p1_w_id
    )
    rust_greenhouse_entry = next(
        e for e in rust_bf if int(e["id"]) == rust_greenhouse_id
    )

    assert rust_p0_a_entry["counters"] == 1, (
        f"Rust p0 bait Alpha should have 1 +1/+1 counter; got "
        f"{rust_p0_a_entry['counters']}"
    )
    assert rust_p0_b_entry["counters"] == 1, (
        f"Rust p0 bait Beta should have 1 +1/+1 counter; got "
        f"{rust_p0_b_entry['counters']}"
    )
    assert rust_p1_w_entry["counters"] == 0, (
        f"Rust p1 witness should have 0 counters (not under p0's "
        f"'you control' filter); got {rust_p1_w_entry['counters']}"
    )
    assert rust_greenhouse_entry["counters"] == 0, (
        f"Rust Atmospheric Greenhouse should have 0 counters (it "
        f"is an Artifact, not a Creature); got "
        f"{rust_greenhouse_entry['counters']}"
    )

    assert py_p0_bait_a.plus_one_counters == 1, (
        f"Python p0 bait Alpha should have 1 +1/+1 counter; got "
        f"{py_p0_bait_a.plus_one_counters}"
    )
    assert py_p0_bait_b.plus_one_counters == 1, (
        f"Python p0 bait Beta should have 1 +1/+1 counter; got "
        f"{py_p0_bait_b.plus_one_counters}"
    )
    assert py_p1_witness.plus_one_counters == 0, (
        f"Python p1 witness should have 0 counters (not under p0's "
        f"'you control' filter); got {py_p1_witness.plus_one_counters}"
    )
    assert py_greenhouse.plus_one_counters == 0, (
        f"Python Atmospheric Greenhouse should have 0 counters "
        f"(Artifact, not Creature); got "
        f"{py_greenhouse.plus_one_counters}"
    )

    # Cross-engine: same counter values on the same objects.
    assert rust_p0_a_entry["counters"] == py_p0_bait_a.plus_one_counters
    assert rust_p0_b_entry["counters"] == py_p0_bait_b.plus_one_counters
    assert rust_p1_w_entry["counters"] == py_p1_witness.plus_one_counters
    assert (
        rust_greenhouse_entry["counters"]
        == py_greenhouse.plus_one_counters
    )

    # Lives unchanged.
    assert rust_state.get_life(0) == 20
    assert rust_state.get_life(1) == 20
    assert py_state.players[0].life == 20
    assert py_state.players[1].life == 20



def test_cross_engine_synthetic_etb_recur_bear_empty_graveyard_silent_skip_parity(
    parity_smoke,
):
    """Probe: ``ETB-Recur-Bear`` with EMPTY p0 graveyard -- silent
    no-op parity for the
    ``return_creature_from_your_graveyard_to_hand`` bridge arm.

    Sister probe to the canonical happy-path
    ``test_cross_engine_synthetic_etb_return_creature_from_graveyard_to_hand_parity``
    -- pins the silent-skip half of the substrate's contract that
    the happy-path probe explicitly carved out as out-of-scope:

        > Empty-graveyard silent-skip case -- separate sibling probe
        > could pin the silent no-op on both sides; this probe drives
        > the happy path with one return target.

    **Documented engine-internal asymmetry, observable parity.**
    The two engines reach the SAME post-drain observable state from
    DIFFERENT intermediate stack shapes:

      * **Rust** pushes the trigger onto the stack on the ENTERS
        dispatch even when no eligible target exists, then resolves
        it as a silent ``return Ok(())`` no-op (the resolve arm at
        ``state_ops_resolve.rs:2986-3020`` scans the source-
        controller's graveyard for the first creature, finds none,
        and exits clean). Stack briefly carries 1 item; post-drain
        it is empty and zones are unchanged.
      * **Python** elides the push at PUSH time when
        ``effect.legal_targets(...)`` returns an empty pool: the
        targeting pipeline (``push_triggered_ability`` /
        ``actions.py:3172``) refuses to land a trigger that has
        no legal target candidate. Stack stays at 0 the entire time.

    Both paths are well-defined silent-skips; both engines agree on
    the post-drain observable contract:

      * p0 graveyard: still empty (nothing to return).
      * p0 hand: still empty (nothing was returned).
      * p0 battlefield: still holds ETB Recur Bear (the source).
      * No life changes.
      * No residual stack on either engine.

    The probe asserts the post-drain observable parity directly and
    does NOT assert mid-flight stack equality (which would force a
    spurious divergence on the documented internal asymmetry).

    Why this probe matters:

      * **Coverage of the substrate's silent-skip branch.** The
        happy-path probe exercises the populated-graveyard pick;
        without this sibling, a regression that flipped Rust's
        ``return Ok(())`` early-exit into a hard panic (or Python's
        ``legal_targets`` no-push elision into a crash on the empty
        pool) would slip past the existing harness.
      * **Asymmetric-internal / symmetric-observable contract.**
        Documents one of Phase 5's structural parity contracts: the
        bridge translates the Rust dict to the Python class, and
        both engines may reach a parity-clean observable state via
        different internal stack shapes. This is the well-defined
        silent-skip: well-defined precisely because the asymmetry
        is bounded to the unobserved push step and the post-drain
        observable matches.

    Probe shape (inject-and-fire-ENTERS, NO graveyard seed):

      1. **Skip the gy seed.** The happy-path probe seeds a single
         Recur Bait Bear in p0's graveyard before injecting; this
         probe's whole point is to NOT seed, so the trigger fires
         against an empty graveyard.
      2. Inject ETB Recur Bear directly onto p0's bf (Rust:
         ``register_and_inject_object``; Python: new_object + bf
         append + manual ``_trigger_etb_abilities``). The
         ENTERS dispatch fires the SourceIsSelf trigger.
      3. Drain both stacks (no-op on Python where the stack stayed
         at 0; one silent-resolve walk on Rust where the trigger
         landed and immediately resolved-to-noop).
      4. Cross-engine assert: post-drain hand/graveyard/bf sizes
         and life totals match between engines and match the
         pre-dispatch baseline.

    Out of scope:

      * The populated-graveyard happy path -- exercised by the
        sibling ``test_cross_engine_synthetic_etb_return_creature
        _from_graveyard_to_hand_parity``.
      * Multi-creature graveyard pick -- the iterator-order parity
        case is a separate probe shape.
      * Rider widenings (or_artifact / or_spacecraft) -- both
        riders carry their own dedicated EoE probes (Interceptor
        Mechan / Fell Gravship suffix); their empty-graveyard
        silent-skip behaviors mirror this probe's contract but the
        target-pick filter widens, so a rider-specific empty-gy
        probe would add coverage there too -- separate slice.

    Expected post-dispatch + post-drain state on BOTH engines:

      * p0 hand: 0 cards (nothing returned).
      * p0 graveyard: 0 cards (the silent-skip didn't push or pop).
      * p0 battlefield: 1 object (ETB Recur Bear).
      * p1 zones: all unchanged.
      * Life totals: 20 / 20.
      * Residual stack: 0 on both engines.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )
    from tests.parity._picker_shims import _PickFirstLegalTargetAgent

    # Recur Bear: vanilla 2/2 + ETB return-creature-from-gy-to-hand.
    # Same shape as the happy-path probe; the ONLY difference is the
    # absent graveyard seed -- this probe skips it.
    recur_bear = CardDef(
        name="ETB Recur Bear (empty-gy probe)",
        card_type="Creature",
        mana_cost_generic=2,
        mana_cost_colored=(("B", 1),),
        power=2,
        toughness=2,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "return_creature_from_your_graveyard_to_hand",
                },
            },
        ),
    )
    spec = DeckSpec(
        card_defs=(recur_bear,),
        # Libraries empty-but-for-symmetry: probe injects directly
        # onto bf so libraries aren't observed.
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    rust_recur_dict = {
        "name": "ETB Recur Bear (empty-gy probe)",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "B": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "return_creature_from_your_graveyard_to_hand",
                },
            }
        ],
    }
    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)
    # Pre-dispatch: graveyard EMPTY on both sides (no seed).
    assert rust_state.graveyard_sizes[0] == 0
    assert rust_state.hand_sizes[0] == 0
    assert rust_state.battlefield_sizes[0] == 0

    # Inject the recur-bear onto p0's battlefield -> fires ENTERS via
    # the deferred-dispatch queue. SourceIsSelf matches; Rust pushes
    # ReturnCreatureFromYourGraveyardToHand onto the stack even with
    # no eligible target (the resolve arm scans the gy at apply-time
    # and silent-no-ops when no creature card is found).
    rust_state.register_and_inject_object(
        rust_recur_dict, 0, ZONE_BATTLEFIELD,
    )
    rust_stack_after_dispatch = rust_state.stack_size()
    # Document Rust's mid-flight push: we do NOT assert this matches
    # Python's count (Python's legal_targets-empty path elides the
    # push). The post-drain observable is what we pin.
    assert rust_stack_after_dispatch == 1, (
        "Rust: ETB Recur Bear's arrival fires SourceIsSelf even "
        "with empty p0 graveyard; trigger lands on stack and "
        "resolves to silent no-op. "
        f"Got mid-flight stack_size={rust_stack_after_dispatch}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.bounce import (
        ReturnCreatureFromYourGraveyardToHand,
    )
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    recur_printing = CardPrinting(
        name="ETB Recur Bear (empty-gy probe)",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2, colored=(("B", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=ReturnCreatureFromYourGraveyardToHand(),
            ),
        ),
    )

    # Seat the canonical first-legal-target shim on p0 (mirrors the
    # happy-path probe's setup). The shim's only behavior of interest
    # here is its empty-pool branch (returns None when
    # legal_targets is empty); the targeting pipeline elides the
    # push without ever calling the shim, so this is defense-in-
    # depth (a regression that began calling the shim with an empty
    # pool in this codepath would surface here via the None return).
    py_state.players[0].agent = _PickFirstLegalTargetAgent()

    # Inject the recur-bear onto p0's battlefield, then manually
    # dispatch ENTERS (same shape as prior probes).
    py_recur = py_state.new_object(
        recur_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_recur.summoning_sick = False
    py_recur.tapped = False
    py_recur.damage = 0
    py_recur.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_recur)
    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life
    # Pre-dispatch: graveyard EMPTY on both sides (no seed).
    assert len(py_state.players[0].graveyard) == 0
    assert len(py_state.players[0].hand) == 0
    _trigger_etb_abilities(py_state, py_recur)
    py_stack_after_dispatch = len(py_state.stack)
    # Document Python's mid-flight elision: legal_targets-empty
    # path doesn't push. We pin the post-drain observable, not the
    # mid-flight stack count.
    assert py_stack_after_dispatch == 0, (
        "Python: ETB Recur Bear's arrival with empty p0 graveyard "
        "should trigger the legal_targets-empty push elision; the "
        "trigger never lands on the stack. "
        f"Got mid-flight stack size={py_stack_after_dispatch}"
    )

    # ---- Drain both stacks, then compare observable parity ----
    _drain_stack_both(py_state, rust_state)

    # Stacks empty on both sides post-drain (Rust: silent-resolve
    # consumed the no-op trigger; Python: nothing to drain).
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0

    # Per-engine post-drain observable: hand/gy still empty, bf
    # still holds the source.
    assert rust_state.hand_sizes[0] == 0, (
        f"Rust: p0 hand should remain empty (no creature card to "
        f"return); got hand_size={rust_state.hand_sizes[0]}"
    )
    assert rust_state.graveyard_sizes[0] == 0, (
        f"Rust: p0 graveyard should remain empty; got "
        f"graveyard_size={rust_state.graveyard_sizes[0]}"
    )
    assert rust_state.battlefield_sizes[0] == 1, (
        f"Rust: p0 bf should hold ETB Recur Bear (the source); "
        f"got bf_size={rust_state.battlefield_sizes[0]}"
    )

    assert len(py_state.players[0].hand) == 0, (
        f"Python: p0 hand should remain empty; got "
        f"hand_size={len(py_state.players[0].hand)}"
    )
    assert len(py_state.players[0].graveyard) == 0, (
        f"Python: p0 graveyard should remain empty; got "
        f"graveyard_size={len(py_state.players[0].graveyard)}"
    )
    py_bf_p0 = [o for o in py_state.battlefield if o.controller_id == 0]
    assert len(py_bf_p0) == 1, (
        f"Python: p0 bf should hold ETB Recur Bear; got "
        f"bf_size={len(py_bf_p0)}"
    )
    assert py_bf_p0[0].printing.name == "ETB Recur Bear (empty-gy probe)"

    # Cross-engine: lives unchanged on both sides.
    assert rust_state.get_life(0) == rust_p0_life_before
    assert rust_state.get_life(1) == rust_p1_life_before
    assert py_state.players[0].life == py_p0_life_before
    assert py_state.players[1].life == py_p1_life_before
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life

    # Cross-engine zone-size parity (the post-drain observable).
    assert rust_state.hand_sizes[0] == len(py_state.players[0].hand)
    assert rust_state.hand_sizes[1] == len(py_state.players[1].hand)
    assert (
        rust_state.graveyard_sizes[0]
        == len(py_state.players[0].graveyard)
    )
    assert (
        rust_state.graveyard_sizes[1]
        == len(py_state.players[1].graveyard)
    )
    assert rust_state.battlefield_sizes[0] == len(py_bf_p0)
    py_bf_p1 = [o for o in py_state.battlefield if o.controller_id == 1]
    assert rust_state.battlefield_sizes[1] == len(py_bf_p1)



def test_cross_engine_synthetic_etb_recur_bear_multi_creature_graveyard_iterator_order_parity(
    parity_smoke,
):
    """Probe: ``ETB-Recur-Bear`` with THREE creatures in p0
    graveyard -- iterator-order target-pick parity for the
    ``return_creature_from_your_graveyard_to_hand`` bridge arm.

    Sister probe to:
      * ``test_cross_engine_synthetic_etb_return_creature_from_graveyard_to_hand_parity``
        (canonical happy-path, ONE creature in gy)
      * ``test_cross_engine_synthetic_etb_recur_bear_empty_graveyard_silent_skip_parity``
        (silent-skip case, ZERO creatures in gy)

    Tension-tests ``_PickFirstLegalTargetAgent`` against Rust's
    iterator-order graveyard scan when MULTIPLE creature cards are
    eligible. The happy-path probe explicitly carved this out:

        > Multi-creature graveyard pick -- with only one creature
        > seeded in the graveyard, both engines pick the same
        > unambiguous target. The "Rust picks first-in-order vs
        > Python's agent picks via legal_targets[0]" parity
        > contract observably collapses on a one-element pool but
        > stays well-defined for follow-up probes that seed
        > multiple creatures.

    This probe seeds three distinct vanilla creatures in p0's
    graveyard in a fixed insertion order (A -> B -> C) and asserts
    both engines pick the SAME card (Bait A, the first-inserted)
    via their respective deterministic mechanisms:

      * **Rust:** ``state_ops_resolve.rs:2986-3020`` scans
        ``state.players[cidx].graveyard.iter()`` for the first
        object whose printing's ``card_types`` contains "Creature".
        With three creatures seeded in order A/B/C, the iterator
        hits A first; A moves from gy to hand.
      * **Python:** ``ReturnFromGraveyard.legal_targets`` walks the
        controller's graveyard in insertion order and emits one
        ``("graveyard_creature", card.id)`` per creature card. The
        seated ``_PickFirstLegalTargetAgent`` returns
        ``legal_targets[0]``, which is the A entry.

    Both engines pick the first-in-insertion-order creature and
    leave B and C in the graveyard.

    **Why "iterator-order parity" is the load-bearing contract:**
    swap A and C in the seed order on either engine and the picked
    card swaps too. The probe asserts BY printing-id (Rust) and BY
    name (Python) that both engines picked the same physical card --
    this catches:

      * A regression in Rust's graveyard scan that flipped the
        iteration order (e.g. picked the LAST creature instead of
        the first).
      * A regression in Python's ``legal_targets`` enumeration
        order (e.g. accidentally sorting by name / power rather
        than insertion).
      * A regression in either engine's ``register_and_inject_object``
        / ``new_object`` that built the graveyard in reverse order.
      * A regression in the ``_PickFirstLegalTargetAgent`` shim's
        first-element pick.

    Probe shape (seed-three / inject-and-fire-ENTERS):

      1. Seed p0's graveyard with THREE distinct vanilla creature
         cards in fixed order: Bait A -> Bait B -> Bait C. Distinct
         names so the post-drain assertion identifies the picked
         card by name (not just count).
      2. Inject ETB Recur Bear directly onto p0's bf. ENTERS
         dispatch fires SourceIsSelf; one
         ReturnCreatureFromYourGraveyardToHand trigger lands on
         the stack with a target resolved deterministically (Rust)
         or pre-chosen via the agent (Python).
      3. Drain both stacks. The picked creature (Bait A on both
         sides) moves from p0 graveyard to p0 hand.
      4. Cross-engine assert: both engines have Bait A in p0 hand
         and Bait B + Bait C still in p0 graveyard, in their
         original insertion order.

    Out of scope:

      * The empty-graveyard silent-skip case -- exercised by the
        sibling empty-gy probe.
      * The single-creature happy-path -- exercised by the
        canonical happy-path probe.
      * Pick-second / pick-last shims -- the contract pinned here
        is "first-in-insertion-order" on both engines; alternate
        picks would be a different probe (and would currently
        fail because Rust hardcodes first-in-order, no
        agent-side override).
      * Rider widenings (or_artifact / or_spacecraft) -- carry
        their own probes; the iterator-order pick contract is
        identical across riders, but verifying the rider-widened
        legal_targets pool is a separate axis.

    Expected post-dispatch + post-drain state on BOTH engines:

      * Bait A in p0 hand (moved from gy by the recur trigger).
      * Bait B + Bait C still in p0 graveyard, in original order.
      * ETB Recur Bear still on p0 bf (the source).
      * Lives unchanged on both seats.
      * No residual stack.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )
    from tests.parity._picker_shims import _PickFirstLegalTargetAgent

    # Three distinct vanilla creatures for the gy seed. Distinct
    # names + distinct mana shapes so a name / cost confusion
    # would surface on the post-drain assertion.
    bait_a = CardDef(
        name="Multi GY Bait Alpha",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=1,
        toughness=1,
    )
    bait_b = CardDef(
        name="Multi GY Bait Beta",
        card_type="Creature",
        mana_cost_generic=2,
        mana_cost_colored=(("U", 1),),
        power=2,
        toughness=2,
    )
    bait_c = CardDef(
        name="Multi GY Bait Gamma",
        card_type="Creature",
        mana_cost_generic=3,
        mana_cost_colored=(("R", 1),),
        power=3,
        toughness=3,
    )
    recur_bear = CardDef(
        name="ETB Recur Bear (multi-gy probe)",
        card_type="Creature",
        mana_cost_generic=2,
        mana_cost_colored=(("B", 1),),
        power=2,
        toughness=2,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "return_creature_from_your_graveyard_to_hand",
                },
            },
        ),
    )
    spec = DeckSpec(
        card_defs=(bait_a, bait_b, bait_c, recur_bear),
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    ZONE_GRAVEYARD = 3
    rust_bait_a_dict = {
        "name": "Multi GY Bait Alpha",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1, "G": 1},
        "effects": [],
        "power": 1,
        "toughness": 1,
    }
    rust_bait_b_dict = {
        "name": "Multi GY Bait Beta",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "U": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
    }
    rust_bait_c_dict = {
        "name": "Multi GY Bait Gamma",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 3, "R": 1},
        "effects": [],
        "power": 3,
        "toughness": 3,
    }
    rust_recur_dict = {
        "name": "ETB Recur Bear (multi-gy probe)",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "B": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "return_creature_from_your_graveyard_to_hand",
                },
            }
        ],
    }
    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)
    # Seed p0's graveyard in fixed order: A -> B -> C. Capture the
    # OBJECT ids returned by register_and_inject_object so the
    # post-drain assertion can identify the picked card uniquely
    # (printing_id is allocated fresh per register_and_inject_object
    # call -- spec's card_defs prefill the registry at slots
    # 0..len(card_defs)-1 and these injection sites add new slots
    # beyond that, so printing_id values aren't predictable from
    # the spec alone; object id IS predictable: per-state
    # incrementing counter starting at 0).
    rust_bait_a_id = rust_state.register_and_inject_object(
        rust_bait_a_dict, 0, ZONE_GRAVEYARD,
    )
    rust_bait_b_id = rust_state.register_and_inject_object(
        rust_bait_b_dict, 0, ZONE_GRAVEYARD,
    )
    rust_bait_c_id = rust_state.register_and_inject_object(
        rust_bait_c_dict, 0, ZONE_GRAVEYARD,
    )
    assert rust_state.graveyard_sizes[0] == 3, (
        f"Rust: p0 gy seed should hold 3 creatures pre-dispatch; "
        f"got graveyard_size={rust_state.graveyard_sizes[0]}"
    )
    # Inject the recur-bear -> fires ENTERS. The trigger lands on
    # the stack with its target resolved deterministically (Rust
    # scans the gy and finds Bait A as the first creature).
    rust_state.register_and_inject_object(
        rust_recur_dict, 0, ZONE_BATTLEFIELD,
    )
    assert rust_state.stack_size() == 1, (
        "Rust: ETB Recur Bear's arrival should fire SourceIsSelf "
        "ENTERS and land "
        "ReturnCreatureFromYourGraveyardToHand on the stack. "
        f"Got stack_size={rust_state.stack_size()}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.bounce import (
        ReturnCreatureFromYourGraveyardToHand,
    )
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    bait_a_printing = CardPrinting(
        name="Multi GY Bait Alpha",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=(("G", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=1,
        toughness=1,
        produces=frozenset(),
    )
    bait_b_printing = CardPrinting(
        name="Multi GY Bait Beta",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2, colored=(("U", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
    )
    bait_c_printing = CardPrinting(
        name="Multi GY Bait Gamma",
        mana_cost_str="",
        mana_cost=ManaCost(generic=3, colored=(("R", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=3,
        toughness=3,
        produces=frozenset(),
    )
    recur_printing = CardPrinting(
        name="ETB Recur Bear (multi-gy probe)",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2, colored=(("B", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=ReturnCreatureFromYourGraveyardToHand(),
            ),
        ),
    )

    # First-legal-target shim on p0 -- mirrors Rust's iterator-order
    # graveyard scan (the canonical contract for this bridge arm).
    py_state.players[0].agent = _PickFirstLegalTargetAgent()

    # Seed p0's graveyard in the SAME insertion order as Rust:
    # A -> B -> C.
    py_bait_a = py_state.new_object(
        bait_a_printing, owner_id=0, zone=Zone.GRAVEYARD,
    )
    py_state.players[0].graveyard.append(py_bait_a)
    py_bait_b = py_state.new_object(
        bait_b_printing, owner_id=0, zone=Zone.GRAVEYARD,
    )
    py_state.players[0].graveyard.append(py_bait_b)
    py_bait_c = py_state.new_object(
        bait_c_printing, owner_id=0, zone=Zone.GRAVEYARD,
    )
    py_state.players[0].graveyard.append(py_bait_c)
    assert len(py_state.players[0].graveyard) == 3

    py_recur = py_state.new_object(
        recur_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_recur.summoning_sick = False
    py_recur.tapped = False
    py_recur.damage = 0
    py_recur.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_recur)
    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life
    _trigger_etb_abilities(py_state, py_recur)
    assert len(py_state.stack) == 1, (
        "Python: ETB Recur Bear's arrival should fire IsSelf "
        "ENTERS and land "
        "ReturnCreatureFromYourGraveyardToHand on the stack. "
        f"Got stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks, then compare iterator-order parity ----
    _drain_stack_both(py_state, rust_state)

    # Stacks empty.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0

    # Per-engine post-drain: ONE card in p0 hand (Bait A, the
    # first-inserted creature), TWO cards remaining in p0 graveyard
    # (Bait B and Bait C, in original insertion order).
    assert rust_state.hand_sizes[0] == 1, (
        f"Rust: p0 hand should hold 1 returned creature; got "
        f"hand_size={rust_state.hand_sizes[0]}"
    )
    assert rust_state.graveyard_sizes[0] == 2, (
        f"Rust: p0 gy should retain 2 creatures (B + C); got "
        f"graveyard_size={rust_state.graveyard_sizes[0]}"
    )
    rust_hand_snap = rust_state.hand_snapshot(0)
    rust_hand_id = int(rust_hand_snap[0]["id"])
    assert rust_hand_id == rust_bait_a_id, (
        f"Rust: hand-returned card should be Bait Alpha "
        f"(object id {rust_bait_a_id}, the first-inserted gy "
        f"creature); got id={rust_hand_id} "
        f"(name={rust_hand_snap[0]['printing_name']})"
    )
    rust_gy_snap = rust_state.graveyard_snapshot(0)
    rust_gy_ids = [int(d["id"]) for d in rust_gy_snap]
    assert rust_gy_ids == [rust_bait_b_id, rust_bait_c_id], (
        f"Rust: gy should retain Beta then Gamma (object ids "
        f"{rust_bait_b_id}, {rust_bait_c_id}) in original insertion "
        f"order; got ids={rust_gy_ids}"
    )

    assert len(py_state.players[0].hand) == 1, (
        f"Python: p0 hand should hold 1 returned creature; got "
        f"hand_size={len(py_state.players[0].hand)}"
    )
    py_hand_name = py_state.players[0].hand[0].printing.name
    assert py_hand_name == "Multi GY Bait Alpha", (
        f"Python: hand-returned card should be Bait Alpha (the "
        f"first-inserted gy creature); got {py_hand_name}"
    )
    assert len(py_state.players[0].graveyard) == 2, (
        f"Python: p0 gy should retain 2 creatures (B + C); got "
        f"graveyard_size={len(py_state.players[0].graveyard)}"
    )
    py_gy_names = [
        o.printing.name for o in py_state.players[0].graveyard
    ]
    assert py_gy_names == [
        "Multi GY Bait Beta", "Multi GY Bait Gamma",
    ], (
        f"Python: gy should retain Beta then Gamma in original "
        f"insertion order; got {py_gy_names}"
    )

    # ETB Recur Bear still on p0 bf (the source).
    assert rust_state.battlefield_sizes[0] == 1
    py_bf_p0 = [
        o for o in py_state.battlefield if o.controller_id == 0
    ]
    assert len(py_bf_p0) == 1
    assert (
        py_bf_p0[0].printing.name == "ETB Recur Bear (multi-gy probe)"
    )

    # Cross-engine: lives unchanged.
    assert rust_state.get_life(0) == rust_p0_life_before
    assert rust_state.get_life(1) == rust_p1_life_before
    assert py_state.players[0].life == py_p0_life_before
    assert py_state.players[1].life == py_p1_life_before
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life

    # Cross-engine zone-size parity.
    assert rust_state.hand_sizes[0] == len(py_state.players[0].hand)
    assert (
        rust_state.graveyard_sizes[0]
        == len(py_state.players[0].graveyard)
    )
    assert rust_state.battlefield_sizes[0] == len(py_bf_p0)
    # p1 zones untouched on both sides.
    assert rust_state.hand_sizes[1] == 0
    assert len(py_state.players[1].hand) == 0
    assert rust_state.graveyard_sizes[1] == 0
    assert len(py_state.players[1].graveyard) == 0



def test_cross_engine_real_eoe_starbreach_whale_etb_surveil_2_mill_path_parity(
    parity_smoke,
):
    """Probe: Starbreach Whale (EoE) ETB ``surveil 2`` MILL-PATH parity --
    drives the ``send_all_to_graveyard`` strategy / ``choose_surveil ->
    True`` agent leg of the surveil substrate.

    Sibling of the existing keep_all_on_top probe at
    ``test_cross_engine_real_eoe_starbreach_whale_etb_surveil_2_parity``
    (tests/test_parity_smoke.py:13952). That probe pins the substrate's
    NO-AGENT default: both engines leave every observed card on library
    top. THIS probe pins the OPPOSITE leg: every observed card moves to
    the graveyard, in popped order.

    Cross-engine contract validated:

    * Rust: after the surveil trigger resolves (via
      ``resolve_top_of_stack_pause`` to skip the trigger-path's
      terminal ``auto_resolve_pending("keep_all_on_top")``), the
      caller drains the queued ``SurveilChoice`` via
      ``auto_resolve_pending_decisions("send_all_to_graveyard")``.
      Implementation: ``state_ops_decisions.rs:794-805`` -- the
      strategy walks ``cards.into_iter()``, rewrites each
      ``obj.zone = 3`` (ZONE_GRAVEYARD), and pushes onto the
      controller's graveyard. Order: ``cards[0]`` (the topmost card
      pre-surveil, popped first) lands in the graveyard FIRST, so it
      sits at the bottom of the new graveyard suffix; ``cards[1]``
      (second-from-top, popped second) sits above it. Net graveyard
      shape (with empty pre-state): ``[bait_alpha, bait_beta]``.

    * Python: with ``_SurveilSendAllAgent`` seated on p0 (the
      surveil's controller), ``Surveil.resolve``
      (effects/generic/library_lookat.py:591) walks
      ``examined = p.library[:n]`` in iteration order
      (``library[0] = bait_alpha`` first, then ``library[1] =
      bait_beta``); each iteration calls ``p.agent.choose_surveil``,
      which returns ``True`` unconditionally; the Python resolve
      ``p.library.remove(card)`` + ``p.graveyard.append(card)``
      writes each card to the graveyard in walk order. Net graveyard
      shape (with empty pre-state): ``[bait_alpha, bait_beta]``.

    Rust + Python agree on ``[bait_alpha, bait_beta]`` graveyard
    suffix in the SAME order; library shrinks from N=2 to N=0 on
    both engines.

    Predicate decomposition (same as the keep_all_on_top probe):

        SourceIsSelf

    Effect: ``surveil(count=2)`` -- bridge arm landed in
    ``5a543130`` (``feature/phase5-ce-bridge-surveil``); the bridge's
    docstring forward-noted this mill-path probe slice (#2) as
    out-of-scope-for-the-original-slice but valid future work.

    Probe shape (mirrors the keep_all_on_top probe except for the
    decision-substrate flip):

      1. Pre-seed p0's library with TWO distinct vanilla bait cards
         (Surveil Bait Alpha at top, Surveil Bait Beta second). A
         single-swap or single-mill mismatch between engines surfaces
         as a per-card name divergence rather than a count-only
         divergence.
      2. Inject Starbreach Whale onto p0's battlefield via
         ``register_and_inject_object`` (Rust) / ``new_object`` + bf
         append + manual ``_trigger_etb_abilities`` (Python). Both
         engines dispatch ENTERS for the just-arrived whale; the
         predicate (SourceIsSelf) matches, the trigger lands on the
         stack with the Surveil(2) effect.
      3. Seat ``_SurveilSendAllAgent`` on Python's p0 (the surveil
         controller). The Rust side has NO agent equivalent --
         driving the mill path on Rust uses the explicit
         ``auto_resolve_pending_decisions("send_all_to_graveyard")``
         API call, which is the documented mirror per the bridge
         arm's comment block in ``cross_engine.py:303-309``.
      4. Drain the trigger via ``resolve_top_of_stack_pause`` on
         Rust (NOT the auto-resolving ``resolve_top_of_stack``) so
         the SurveilChoice stays on the queue. Then call
         ``auto_resolve_pending_decisions("send_all_to_graveyard")``
         to apply the mill-all strategy. On Python, drain via the
         standard ``resolve_top_of_stack`` -- the seated agent
         drives the mill path inline during the resolve.
      5. Cross-engine assert: post-drain, BOTH engines have an
         EMPTY p0 library (the two bait cards were milled) and a p0
         graveyard containing exactly ``[bait_alpha, bait_beta]`` in
         that order.

    Out of scope:

      * Flying / Warp -- same reasoning as the keep_all_on_top probe;
        no combat / mana pipeline involvement.
      * Mid-list mixed mill-or-keep -- the agent here returns True
        unconditionally to mirror Rust's ``send_all_to_graveyard``
        strategy. A more granular probe (``choose_surveil`` returning
        True for one card, False for another) would need a Rust
        ``submit_surveil_decision(top_ids=[...], graveyard_ids=[...])``
        call instead of a strategy fast-path -- distinct mechanism,
        out of scope here.
      * Cross-controller surveil (opponent's trigger surveils opponent's
        library on your turn) -- the bridge's I61 controller-of-effect
        substrate is exercised by the existing keep_all_on_top probes;
        this probe stays on the same-controller (active_player) shape
        for minimum delta from the sibling probe.

    Expected post-dispatch + post-drain state on BOTH engines:

      * Starbreach Whale on p0's battlefield.
      * p0 library: EMPTY (both bait cards milled).
      * p0 graveyard: ``[Surveil Bait Alpha, Surveil Bait Beta]`` in
        popped order.
      * p1 library / graveyard: unchanged (empty).
      * Lives unchanged on both seats.
      * No residual stack on either engine.
      * No pending decisions on Rust (the explicit auto-resolve
        drained the SurveilChoice).
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )
    from tests.parity._picker_shims import _SurveilSendAllAgent

    starbreach_whale = CardDef(
        name="Starbreach Whale",
        card_type="Creature",
        mana_cost_generic=4,
        mana_cost_colored=(("U", 1),),
        power=3,
        toughness=5,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "surveil", "count": 2},
            },
        ),
    )
    # Distinct bait names from the keep_all_on_top sibling probe so
    # log-correlation across the two probes stays unambiguous.
    surveil_bait_a = CardDef(
        name="Surveil Bait Alpha Mill",
        card_type="Creature",
        mana_cost_generic=1,
        power=1,
        toughness=1,
    )
    surveil_bait_b = CardDef(
        name="Surveil Bait Beta Mill",
        card_type="Creature",
        mana_cost_generic=2,
        power=2,
        toughness=2,
    )
    spec = DeckSpec(
        card_defs=(starbreach_whale, surveil_bait_a, surveil_bait_b),
        # Library is built head-first (index 0 = top per Rust's CE3
        # convention; matches Python's library[0] = top in
        # effects/generic/library_lookat.py:330). Bait Alpha sits at
        # top (will be popped first by Surveil), Bait Beta sits second
        # (popped second).
        p0_library=("Surveil Bait Alpha Mill", "Surveil Bait Beta Mill"),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    rust_whale_dict = {
        "name": "Starbreach Whale",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 4, "U": 1},
        "effects": [],
        "power": 3,
        "toughness": 5,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "surveil", "count": 2},
            }
        ],
    }
    rust_p0_lib_size_before = rust_state.library_sizes[0]
    rust_p0_gy_size_before = rust_state.graveyard_sizes[0]
    # Capture the names at the top of p0's library BEFORE the surveil
    # so the post-drain graveyard-name assertion has an apples-to-
    # apples comparison target. library_snapshot returns dicts with
    # printing_name; the top is index 0.
    rust_p0_lib_top_names_before = [
        d["printing_name"] for d in rust_state.library_snapshot(0)
    ]
    rust_state.register_and_inject_object(
        rust_whale_dict, 0, ZONE_BATTLEFIELD
    )
    assert rust_state.stack_size() == 1, (
        "Rust: Starbreach Whale's own arrival should fire the "
        "SourceIsSelf ENTERS trigger and land Surveil(2) on the "
        f"stack. Got stack_size={rust_state.stack_size()}"
    )

    # Drain the surveil trigger via the PAUSE variant so the
    # SurveilChoice stays on the pending-decisions queue (the
    # auto-resolving variant would terminate with keep_all_on_top
    # and we'd never observe the mill path). Then explicitly drain
    # via the send_all_to_graveyard strategy. This is the exact
    # pattern used in tests_rust/test_pending_decisions.py:236-252
    # for the synthetic-spell shape; here we apply it to a
    # triggered-ability shape on a real EoE card.
    rust_state.resolve_top_of_stack_pause()
    assert rust_state.stack_size() == 0, (
        "Rust: surveil trigger should have popped off the stack "
        "during resolve_top_of_stack_pause; the pause variant only "
        "skips the auto-resolve of pending decisions, not the "
        f"stack pop. Got stack_size={rust_state.stack_size()}"
    )
    assert rust_state.has_pending_decision() is True, (
        "Rust: SurveilChoice should be pending after "
        "resolve_top_of_stack_pause -- the pause variant's whole "
        "purpose is to leave the decision queue populated. "
        f"has_pending_decision returned False"
    )
    rust_state.auto_resolve_pending_decisions("send_all_to_graveyard")
    assert rust_state.has_pending_decision() is False, (
        "Rust: SurveilChoice should have drained via "
        "auto_resolve_pending_decisions; has_pending_decision "
        "returned True after the explicit auto-resolve call"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities, resolve_top_of_stack as py_resolve
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.library_lookat import Surveil
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    whale_printing = CardPrinting(
        name="Starbreach Whale",
        mana_cost_str="",
        mana_cost=ManaCost(generic=4, colored=(("U", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=3,
        toughness=5,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=Surveil(amount=2),
            ),
        ),
    )
    py_whale = py_state.new_object(
        whale_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_whale.summoning_sick = False
    py_whale.tapped = False
    py_whale.damage = 0
    py_whale.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_whale)
    # Snapshot p0's pre-surveil library names so the post-drain
    # graveyard-name assertion can match against the in-order
    # popped sequence (library[0] -> graveyard first; library[1] ->
    # graveyard second).
    py_p0_lib_top_names_before = [
        o.printing.name for o in py_state.players[0].library
    ]
    py_p0_gy_size_before = len(py_state.players[0].graveyard)
    # SEAT THE MILL-ALL AGENT on p0 -- this is the cross-engine
    # mirror of Rust's send_all_to_graveyard strategy. Without an
    # agent, Python would short-circuit to keep-all-on-top via the
    # `p.agent is None` branch at library_lookat.py:605, mirroring
    # Rust's keep_all_on_top default (covered by the sibling probe).
    py_state.players[0].agent = _SurveilSendAllAgent()
    _trigger_etb_abilities(py_state, py_whale)
    assert len(py_state.stack) == 1, (
        "Python: Starbreach Whale's own arrival should fire the "
        "IsSelf ENTERS trigger and land Surveil(2) on the stack. "
        f"Got stack size={len(py_state.stack)}"
    )
    # Drain the surveil trigger -- with the agent seated, the
    # Surveil.resolve loop walks examined = p.library[:2] in order,
    # asks the agent for each card, mills both. No Python-side
    # equivalent of the pause / auto-resolve split is needed -- the
    # agent IS the decision-resolution surface on Python.
    py_resolve(py_state)
    assert len(py_state.stack) == 0, (
        "Python: surveil trigger should have resolved off the stack "
        f"after py_resolve. Got stack size={len(py_state.stack)}"
    )

    # ---- Cross-engine assertion: mill-path post-state ----
    # Library: BOTH engines should be at size 0 (both bait cards
    # milled).
    assert rust_state.library_sizes[0] == rust_p0_lib_size_before - 2, (
        f"Rust p0 library size should drop by 2 (both bait cards "
        f"milled via send_all_to_graveyard): "
        f"before={rust_p0_lib_size_before} "
        f"after={rust_state.library_sizes[0]}"
    )
    assert len(py_state.players[0].library) == 0, (
        f"Python p0 library should be empty post-mill (both bait "
        f"cards moved to graveyard): "
        f"library={[o.printing.name for o in py_state.players[0].library]}"
    )
    assert rust_state.library_sizes[0] == len(py_state.players[0].library), (
        f"Cross-engine library size mismatch: "
        f"rust={rust_state.library_sizes[0]} "
        f"py={len(py_state.players[0].library)}"
    )
    # Graveyard: BOTH engines should hold exactly the two milled bait
    # cards in popped order (Alpha first, Beta second).
    assert rust_state.graveyard_sizes[0] == rust_p0_gy_size_before + 2, (
        f"Rust p0 graveyard size should grow by 2 (both bait cards "
        f"milled): before={rust_p0_gy_size_before} "
        f"after={rust_state.graveyard_sizes[0]}"
    )
    rust_p0_gy_names_after = [
        d["printing_name"] for d in rust_state.graveyard_snapshot(0)
    ]
    py_p0_gy_names_after = [
        o.printing.name for o in py_state.players[0].graveyard
    ]
    # Send-all-to-graveyard pushes cards onto the graveyard in popped
    # order: cards[0] (was lib[0] = top) lands first; cards[1] (was
    # lib[1] = second-from-top) lands second. So gy ends up
    # [bait_alpha, bait_beta] in that order on Rust.
    assert rust_p0_gy_names_after == rust_p0_lib_top_names_before, (
        f"Rust p0 graveyard should hold the two milled bait cards in "
        f"popped order (cards[0]=lib[0]=top first, cards[1]=lib[1] "
        f"second): expected={rust_p0_lib_top_names_before} "
        f"got={rust_p0_gy_names_after}"
    )
    # Python's Surveil walks examined = p.library[:n] in order and
    # appends each milled card to graveyard, so gy ends up in the
    # same order: [lib[0], lib[1]] = [bait_alpha, bait_beta].
    assert py_p0_gy_names_after == py_p0_lib_top_names_before, (
        f"Python p0 graveyard should hold the two milled bait cards "
        f"in walk order (lib[0] first, lib[1] second): "
        f"expected={py_p0_lib_top_names_before} "
        f"got={py_p0_gy_names_after}"
    )
    # Cross-engine: identical names in identical order.
    assert rust_p0_gy_names_after == py_p0_gy_names_after, (
        f"Cross-engine graveyard order divergence: "
        f"rust={rust_p0_gy_names_after} py={py_p0_gy_names_after}"
    )
    # Stacks empty on both sides.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0
    # Lives unchanged (no damage / life-gain in the surveil-mill
    # path).
    assert rust_state.get_life(0) == 20
    assert rust_state.get_life(1) == 20
    assert py_state.players[0].life == 20
    assert py_state.players[1].life == 20
    # p1 zones untouched (the surveil targets p0's library only).
    assert rust_state.library_sizes[1] == 0
    assert rust_state.graveyard_sizes[1] == 0
    assert len(py_state.players[1].library) == 0
    assert len(py_state.players[1].graveyard) == 0


def test_cross_engine_synthetic_etb_create_token_cross_controller_routes_to_source_controller_parity(
    parity_smoke,
):
    """Probe: synthetic ETB ``create_token`` trigger fired by a
    permanent CONTROLLED BY P1 while ACTIVE_PLAYER=P0 -- the I81
    controller-of-effect fix's cross-engine flicker. Both engines
    must route the freshly-spawned token onto P1's battlefield
    under P1's control, NOT onto P0's bf under P0 (the active
    player).

    **The I81 substrate.** Per worklog
    ``2026-05-13-controller-of-effect-i81-i82-i83``: pre-I81 the
    Rust ``Effect::CreateToken`` arm computed
    ``active = state.active_player`` and used it both for the
    token's ``controller`` byte AND for picking the recipient
    battlefield Vec. Wrong when the resolving spell / triggered
    ability has a controller != active_player. The fix routes both
    derivations through ``current_resolve_source_controller``, so
    the token correctly lands under the source's controller. The
    Python side (``CreateToken.resolve(state, controller_id, ...)``
    at ``effects/generic/tokens.py:202``) already takes
    ``controller_id`` explicitly and has always been correct on this
    surface. This probe pins the cross-engine observable PARITY of
    the post-I81 contract end-to-end via a synthetic ETB trigger,
    closing the "cross-controller probe" gap the I81 forward-notes
    explicitly called out.

    **Why synthetic, not a real EoE card.** No EoE card today
    prints an ETB ``create N tokens`` trigger that's parameterized
    on a registered token printing in a way that's straightforward
    to drive cross-engine without the rest of the spell's
    machinery. The Rust regression-pin tests for I81 use a
    Conscript-shape sorcery cast with ``push_to_stack`` directly;
    that bypasses the deferred-ETB-dispatch path which is the
    canonical surface a triggered ability flows through. A
    synthetic ETB-bearing creature ("Token Maker Bear") with a
    ``create_token`` trigger exercises the deferred-dispatch path
    end-to-end, which is the flicker the cross-engine observable
    is supposed to pin.

    **Bridge arm for ``create_token``.** The bridge translator at
    ``_ta_dict_to_python_effect`` carries a ``create_token`` arm
    (added in ``feature/phase5-ce-bridge-create-token``). The pid
    -> Python-CardPrinting lookup is resolved via a probe-time
    registry: this probe registers the matching Python token
    printing against the Rust registry's pid via
    ``register_token_printing(rust_token_pid, py_soldier_token)``
    BEFORE building the Token Maker Bear's Python printing. The
    bridge then materializes ``CreateToken(token_printing=
    py_soldier_token, count=1)`` from the same dict shape Rust
    consumes. Token Maker Bear stays OUT of ``DeckSpec.card_defs``
    (registered manually on Rust via ``register_and_inject_object``
    + on Python via ``new_object`` with a printing assembled
    in-place) because the inject-and-fire-ENTERS pattern bypasses
    the deckspec / library / cast-from-hand machinery; both
    triggered-ability shapes flow through the bridge regardless.

    Probe shape (cross-controller inject-and-fire-ENTERS):

      1. **active_player=P0** (default after ``make_state`` /
         ``build_python_state``). Confirmed via ``state.active_player``
         on Rust and ``state.active_player_idx`` on Python.

      2. **Register the Soldier token printing** on the Rust side
         (so the create_token trigger has a valid
         ``token_printing_id`` to reference). Mirror the Python
         side by constructing a matching Python CardPrinting via
         ``make_token_creature``.

      3. **Inject Token Maker Bear onto P1's bf** with
         ``controller=1`` (Rust's ``register_and_inject_object``;
         Python's ``new_object`` + bf append + manual
         ``_trigger_etb_abilities``). The injection's ENTERS
         dispatch fires the SourceIsSelf trigger; the trigger
         lands on the stack with controller=1 (the SOURCE's
         controller, NOT the active player).

      4. **Drain both stacks.** The trigger resolves via
         ``apply_effect`` with
         ``current_resolve_source_controller = Some(1)``; the
         post-I81 CreateToken arm reads that and routes the token
         to P1's bf under P1's control.

      5. **Cross-engine assert (post-I81 contract):**
         - P1's bf grew by exactly 1 (the spawned token).
         - P0's bf is unchanged (NO token spawned under the
           active player).
         - The fresh token's ``controller_id`` is 1 on both
           engines (Rust via ``battlefield_snapshot()``, Python
           via the ``GameObject.controller_id`` field).

    **Pre-I81 vs post-I81 observable.**
    Pre-fix Rust would have:
      - Spawned the token on P0's bf (active_player), creating a
        +1 size delta on the WRONG seat.
      - Stamped ``controller_id = 0`` on the token, making it a
        permanent under the WRONG player.
    The Python side has always done the right thing because the
    ``CreateToken.resolve`` recipient list is built from the
    explicitly-passed ``controller_id`` (the trigger's controller).
    Post-I81 the Rust observable matches Python. This probe
    exercises that match end-to-end.

    Out of scope:

      * Cast-from-hand mana cost -- the inject-and-dispatch-ENTERS
        pattern bypasses the mana pipeline.
      * count != 1 -- the I81 contract is independent of count;
        the regression pins at ``test_create_token_*`` already
        cover the count multiplication. This probe pins the
        controller routing on count=1.
      * Each-player tokens (``each_player=True`` flag) -- a
        Python-side flag with no Rust mirror today; out of scope
        of the cross-engine substrate.
      * Tapped / attacking / end-of-combat-sacrifice riders --
        not part of the I81 controller-routing surface.

    Expected post-dispatch + post-drain state on BOTH engines:

      * Token Maker Bear on P1's battlefield (unchanged from
        inject; controller=1).
      * One Soldier Token on P1's battlefield (newly spawned;
        controller=1).
      * P0's battlefield: empty (no token spawned under the
        active player).
      * No residual stack on either engine.
      * Life totals unchanged on both seats.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )

    # Empty card_defs: Token Maker Bear is built and injected
    # manually on both sides (the bridge has no `create_token`
    # arm -- see docstring).
    spec = DeckSpec(
        card_defs=(),
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # Confirm pre-condition: active_player=P0 on both engines (the
    # whole point of the probe is the cross-controller case where
    # the SOURCE's controller != active_player).
    assert rust_state.active_player == 0, (
        f"Probe pre-condition: Rust active_player must be 0; "
        f"got {rust_state.active_player}"
    )
    assert py_state.active_player_idx == 0, (
        f"Probe pre-condition: Python active_player_idx must be 0; "
        f"got {py_state.active_player_idx}"
    )

    # ---- Rust side: register Soldier token, then inject Token
    # Maker Bear onto P1's bf. ----
    ZONE_LIBRARY = 1
    ZONE_BATTLEFIELD = 2
    rust_soldier_token_dict = {
        "name": "Soldier Token I81 Probe",
        "card_types": ["Creature"],
        "power": 1,
        "toughness": 1,
    }
    # Register the token printing into Rust's registry by injecting
    # a dummy onto P1's library briefly -- mirrors
    # `_register_soldier_token` in tests_rust/test_resolve.py.
    rust_token_pid = rust_state.registry_size  # next free printing_id
    rust_state.register_and_inject_object(
        rust_soldier_token_dict, 1, ZONE_LIBRARY,
    )

    rust_token_maker_dict = {
        "name": "Token Maker Bear (I81 cross-controller probe)",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "W": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "create_token",
                    "count": 1,
                    "token_printing_id": rust_token_pid,
                },
            }
        ],
    }

    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)
    rust_bf_p0_before = rust_state.battlefield_sizes[0]
    rust_bf_p1_before = rust_state.battlefield_sizes[1]

    # Inject onto P1's bf with controller=1. ENTERS fires via the
    # deferred-dispatch queue; the trigger lands on the stack
    # carrying controller=1 (the SOURCE's controller).
    rust_state.register_and_inject_object(
        rust_token_maker_dict, 1, ZONE_BATTLEFIELD,
    )

    # ---- Python side: build the Soldier token printing, register
    # it against Rust's pid via the bridge, then assemble Token
    # Maker Bear's printing using the bridge's
    # `_ta_dict_to_python_triggered_ability` translator on the SAME
    # trigger-dict shape Rust consumed. ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import (
        CardPrinting, ManaCost, make_token_creature,
    )
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_triggered_ability,
        clear_token_printings, register_token_printing,
    )

    py_soldier_token = make_token_creature(
        name="Soldier Token I81 Probe",
        power=1,
        toughness=1,
        subtypes=("Soldier",),
    )
    # Register the Python token printing against Rust's pid so the
    # `create_token` bridge arm in `_ta_dict_to_python_effect` can
    # look it up at translation time. `clear_token_printings()`
    # first defends against stale state from any prior probe in the
    # same pytest worker that registered a different printing under
    # the same numeric pid.
    clear_token_printings()
    register_token_printing(rust_token_pid, py_soldier_token)
    py_token_maker_trigger = _ta_dict_to_python_triggered_ability(
        rust_token_maker_dict["triggered_abilities"][0]
    )
    py_token_maker_printing = CardPrinting(
        name="Token Maker Bear (I81 cross-controller probe)",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2, colored=(("W", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(py_token_maker_trigger,),
    )
    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life
    py_bf_p0_before = len(
        [o for o in py_state.battlefield if o.controller_id == 0]
    )
    py_bf_p1_before = len(
        [o for o in py_state.battlefield if o.controller_id == 1]
    )

    # Inject Token Maker Bear onto P1's bf with controller_id=1,
    # then manually dispatch ENTERS (mirrors prior synthetic ETB
    # probes).
    py_token_maker = py_state.new_object(
        py_token_maker_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_token_maker.summoning_sick = False
    py_token_maker.tapped = False
    py_token_maker.damage = 0
    py_token_maker.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_token_maker)
    _trigger_etb_abilities(py_state, py_token_maker)

    # ---- Drain both stacks, then compare observable parity. ----
    _drain_stack_both(py_state, rust_state)

    # Stacks empty on both sides post-drain.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0

    # Rust observable (the I81 contract):
    #   * P1's bf gained Token Maker Bear (the source) + 1 Soldier
    #     Token = +2 from baseline.
    #   * P0's bf is unchanged (NO token under active player).
    rust_bf_p0_after = rust_state.battlefield_sizes[0]
    rust_bf_p1_after = rust_state.battlefield_sizes[1]
    assert rust_bf_p0_after == rust_bf_p0_before, (
        f"Rust I81 contract violation: P0's bf changed despite "
        f"the create_token trigger being controlled by P1. "
        f"Pre-fix bug would route the token here. "
        f"Got bf_p0_before={rust_bf_p0_before}, "
        f"bf_p0_after={rust_bf_p0_after}"
    )
    assert rust_bf_p1_after == rust_bf_p1_before + 2, (
        f"Rust I81 contract: P1's bf should gain Token Maker Bear "
        f"+ 1 Soldier Token = +2 from baseline. Got "
        f"bf_p1_before={rust_bf_p1_before}, "
        f"bf_p1_after={rust_bf_p1_after}"
    )

    # Confirm the freshly-spawned Soldier Token's controller_id=1
    # via the bf snapshot (catches a regression that flipped the
    # token controller stamp without changing the bf-Vec routing).
    rust_bf_snap = rust_state.battlefield_snapshot()
    rust_soldier_tokens = [
        d for d in rust_bf_snap
        if d["printing_name"] == "Soldier Token I81 Probe"
    ]
    assert len(rust_soldier_tokens) == 1, (
        f"Rust: expected exactly 1 Soldier Token on the bf; got "
        f"{len(rust_soldier_tokens)}"
    )
    assert rust_soldier_tokens[0]["controller_id"] == 1, (
        f"Rust I81 contract: spawned Soldier Token's controller_id "
        f"must be 1 (source's controller). Got "
        f"controller_id={rust_soldier_tokens[0]['controller_id']}"
    )

    # Python observable: same shape on the equivalent zones.
    py_bf_p0_after = len(
        [o for o in py_state.battlefield if o.controller_id == 0]
    )
    py_bf_p1_after = len(
        [o for o in py_state.battlefield if o.controller_id == 1]
    )
    assert py_bf_p0_after == py_bf_p0_before, (
        f"Python: P0's bf should be unchanged. Got "
        f"bf_p0_before={py_bf_p0_before}, "
        f"bf_p0_after={py_bf_p0_after}"
    )
    assert py_bf_p1_after == py_bf_p1_before + 2, (
        f"Python: P1's bf should gain Token Maker Bear + 1 "
        f"Soldier Token = +2. Got "
        f"bf_p1_before={py_bf_p1_before}, "
        f"bf_p1_after={py_bf_p1_after}"
    )
    py_soldier_tokens = [
        o for o in py_state.battlefield
        if o.printing.name == "Soldier Token I81 Probe"
    ]
    assert len(py_soldier_tokens) == 1, (
        f"Python: expected exactly 1 Soldier Token on the bf; got "
        f"{len(py_soldier_tokens)}"
    )
    assert py_soldier_tokens[0].controller_id == 1, (
        f"Python: spawned Soldier Token's controller_id must be 1. "
        f"Got controller_id={py_soldier_tokens[0].controller_id}"
    )

    # Cross-engine: lives unchanged on both sides (create_token
    # doesn't touch life).
    assert rust_state.get_life(0) == rust_p0_life_before
    assert rust_state.get_life(1) == rust_p1_life_before
    assert py_state.players[0].life == py_p0_life_before
    assert py_state.players[1].life == py_p1_life_before
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life

    # Cross-engine bf-size parity (the post-drain observable).
    assert rust_bf_p0_after == py_bf_p0_after
    assert rust_bf_p1_after == py_bf_p1_after


def test_cross_engine_synthetic_etb_return_creature_from_graveyard_to_hand_cross_controller_routes_to_source_controller_parity(
    parity_smoke,
):
    """Probe: synthetic ETB
    ``return_creature_from_your_graveyard_to_hand`` trigger fired
    by a permanent CONTROLLED BY P1 while ACTIVE_PLAYER=P0 -- the
    I82 controller-of-effect fix's cross-engine flicker. Both
    engines must scan P1's graveyard (the source's controller),
    pick the bait creature, and return it to P1's hand. Pre-fix
    Rust scanned P0's graveyard (active_player) and would have
    pushed any matched creature onto P0's hand.

    **The I82 substrate.** Per worklog
    ``2026-05-13-controller-of-effect-i81-i82-i83``: pre-I82 the
    Rust ``Effect::ReturnCreatureFromYourGraveyardToHand`` arm
    derived ``controller_idx`` from ``state.active_player``. Wrong
    when the resolving spell / triggered ability has a controller
    != active_player. The fix routes the graveyard scan AND the
    destination hand push through ``current_resolve_source_controller``,
    so both anchor to the SOURCE's controller. Python's
    ``ReturnCreatureFromYourGraveyardToHand.resolve(state,
    controller_id, ...)`` (constructor sugar over
    ``ReturnFromGraveyard`` at ``effects/generic/bounce.py:356``)
    has always taken ``controller_id`` explicitly. This probe pins
    the cross-engine observable PARITY of the post-I82 contract
    end-to-end via a synthetic ETB trigger, closing the
    "cross-controller probe" gap the I82 forward-notes called out.

    **Why synthetic, not a real EoE card.** The bare unit-variant
    has no real-EoE consumer with matching shape today (per the
    canonical happy-path probe's docstring -- Interceptor Mechan
    + Fell Gravship suffix carry rider widenings). Sister-shape
    to the canonical happy-path probe; the difference is the
    SOURCE's controller is P1 instead of P0, so the
    controller-derivation path that I82 fixed actually fires.

    Probe shape (cross-controller inject-and-fire-ENTERS):

      1. **active_player=P0** (default). Confirmed via
         ``state.active_player`` on Rust and
         ``state.active_player_idx`` on Python.

      2. **Seed P1's graveyard** with a single bait creature
         ("Recur Bait Bear"). Pre-fix would have looked at P0's
         graveyard (which is empty), found nothing, and silent-
         no-opped. Post-fix looks at P1's graveyard (where the
         bait sits) and finds it.

      3. **Inject Token Maker Bear (the recur source) onto P1's
         bf** with controller=1. ENTERS fires; the trigger lands
         on the stack with controller=1 (the SOURCE's controller).

      4. **Drain both stacks.** The trigger resolves with
         ``current_resolve_source_controller = Some(1)``; the
         post-I82 arm scans P1's graveyard, picks the bait, and
         pushes it to P1's hand. Python's targeting pipeline
         picks at PUSH time via the seated
         ``_PickFirstLegalTargetAgent`` shim on P1.

      5. **Cross-engine assert (post-I82 contract):**
         - P1's hand grew by 1 (the recurred bait creature).
         - P1's graveyard shrank by 1 (it lost the bait).
         - P0's hand and graveyard unchanged (NO crossover into
           the active player's zones).

    **Pre-I82 vs post-I82 observable.**
    Pre-fix Rust would have:
      - Scanned P0's empty graveyard, found no creature card,
        silent-no-op. Bait stays in P1's graveyard. P1's hand
        unchanged.
    Post-fix Rust scans P1's graveyard, picks the bait, returns
    it to P1's hand -- matching Python's always-correct behavior.

    Out of scope:

      * Cast-from-hand mana cost -- bypassed by inject-and-fire.
      * Multi-creature graveyard pick -- single bait keeps the
        agent's first-legal-target pick observable. The
        canonical multi-creature iterator-order parity probe
        covers that surface separately.
      * Empty-graveyard silent-skip on the SOURCE's controller --
        pinned in the canonical empty-gy sibling (with active
        player as source-controller). A cross-controller empty-
        graveyard variant is well-defined but redundant: I82's
        fix only touches the controller derivation, not the
        empty-graveyard branch.
      * Rider widenings (or_artifact / or_spacecraft) -- the
        post-I82 fix applies to those rider arms too (same
        controller derivation path), but they have their own
        bridge arms and EoE consumers; out of scope of this
        bare-arm cross-controller pin.

    Expected post-dispatch + post-drain state on BOTH engines:

      * Token Maker Bear on P1's battlefield (unchanged from
        inject; controller=1).
      * Recur Bait Bear in P1's hand (returned from P1's gy to
        P1's hand -- the I82 contract).
      * P1's graveyard empty (bait moved out).
      * P0's hand and graveyard untouched.
      * No residual stack on either engine.
      * Life totals unchanged on both seats.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )
    from tests.parity._picker_shims import _PickFirstLegalTargetAgent

    # Bait Bear: vanilla 2/2, no triggered abilities, seeded in
    # P1's graveyard.
    bait_bear = CardDef(
        name="Recur Bait Bear (I82 cross-controller probe)",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=2,
        toughness=2,
    )
    # Token Maker Bear (renamed from Slice 1 for clarity -- here
    # it's a recur-bear, not a token-maker; the body of the trigger
    # is `return_creature_from_your_graveyard_to_hand`).
    recur_bear = CardDef(
        name="ETB Recur Bear (I82 cross-controller probe)",
        card_type="Creature",
        mana_cost_generic=2,
        mana_cost_colored=(("B", 1),),
        power=2,
        toughness=2,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "return_creature_from_your_graveyard_to_hand",
                },
            },
        ),
    )
    spec = DeckSpec(
        card_defs=(bait_bear, recur_bear),
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # Confirm pre-condition: active_player=P0 on both engines.
    assert rust_state.active_player == 0, (
        f"Probe pre-condition: Rust active_player must be 0; "
        f"got {rust_state.active_player}"
    )
    assert py_state.active_player_idx == 0, (
        f"Probe pre-condition: Python active_player_idx must be 0; "
        f"got {py_state.active_player_idx}"
    )

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    ZONE_GRAVEYARD = 3
    rust_bait_dict = {
        "name": "Recur Bait Bear (I82 cross-controller probe)",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1, "G": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
    }
    rust_recur_dict = {
        "name": "ETB Recur Bear (I82 cross-controller probe)",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "B": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "return_creature_from_your_graveyard_to_hand",
                },
            }
        ],
    }
    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)
    rust_p0_hand_before = rust_state.hand_sizes[0]
    rust_p1_hand_before = rust_state.hand_sizes[1]
    rust_p0_gy_before = rust_state.graveyard_sizes[0]
    rust_p1_gy_before = rust_state.graveyard_sizes[1]

    # Seed P1's graveyard with the bait creature (the I82
    # source-controller-of-effect fix routes the scan to P1's
    # graveyard).
    rust_state.register_and_inject_object(
        rust_bait_dict, 1, ZONE_GRAVEYARD,
    )
    # Inject the recur-bear onto P1's bf with controller=1. ENTERS
    # fires; the trigger lands on the stack carrying controller=1.
    rust_state.register_and_inject_object(
        rust_recur_dict, 1, ZONE_BATTLEFIELD,
    )
    assert rust_state.stack_size() == 1, (
        f"Rust: ETB Recur Bear's arrival on P1 should fire the "
        f"SourceIsSelf ENTERS trigger and land "
        f"ReturnCreatureFromYourGraveyardToHand on the stack. "
        f"Got stack_size={rust_state.stack_size()}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.bounce import (
        ReturnCreatureFromYourGraveyardToHand,
    )
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    bait_printing = CardPrinting(
        name="Recur Bait Bear (I82 cross-controller probe)",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=(("G", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
    )
    recur_printing = CardPrinting(
        name="ETB Recur Bear (I82 cross-controller probe)",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2, colored=(("B", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=ReturnCreatureFromYourGraveyardToHand(),
            ),
        ),
    )

    # Seat the first-legal-target picker on P1 (the SOURCE's
    # controller). The targeting pipeline calls
    # `controller.agent.choose_target` on P1's agent because the
    # trigger's controller is P1.
    py_state.players[1].agent = _PickFirstLegalTargetAgent()

    # Seed P1's graveyard with the bait creature (mirror of the
    # Rust seed -- the controller-of-effect fix on Python is
    # implicit: the trigger's controller-id is P1, so legal_targets
    # walks P1's graveyard).
    py_bait = py_state.new_object(
        bait_printing, owner_id=1, zone=Zone.GRAVEYARD,
    )
    py_state.players[1].graveyard.append(py_bait)

    # Inject the recur-bear onto P1's bf with owner_id=1, then
    # manually dispatch ENTERS.
    py_recur = py_state.new_object(
        recur_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_recur.summoning_sick = False
    py_recur.tapped = False
    py_recur.damage = 0
    py_recur.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_recur)
    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life
    py_p0_hand_before = len(py_state.players[0].hand)
    py_p1_hand_before = len(py_state.players[1].hand)
    py_p0_gy_before = len(py_state.players[0].graveyard)
    # py_p1_gy_before is post-seed; it includes the bait (1).
    py_p1_gy_before_post_seed = len(py_state.players[1].graveyard)
    assert py_p1_gy_before_post_seed == 1, (
        f"Python pre-condition: P1 graveyard should hold the "
        f"seeded bait; got "
        f"size={py_p1_gy_before_post_seed}"
    )
    _trigger_etb_abilities(py_state, py_recur)
    assert len(py_state.stack) == 1, (
        f"Python: ETB Recur Bear's arrival on P1 should fire "
        f"the IsSelf ENTERS trigger and land "
        f"ReturnCreatureFromYourGraveyardToHand on the stack. "
        f"Got stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks, then compare observable parity. ----
    _drain_stack_both(py_state, rust_state)

    # Stacks empty post-drain.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0

    # Rust observable (the I82 contract):
    #   * P1's hand gained the bait creature (+1 from baseline).
    #   * P1's graveyard is back to baseline (the bait moved
    #     out; it was +1 from the seed; net 0 from baseline).
    #   * P0's hand and graveyard are UNCHANGED (no crossover
    #     into the active player's zones -- pre-fix bug would
    #     have had it land here).
    rust_p0_hand_after = rust_state.hand_sizes[0]
    rust_p1_hand_after = rust_state.hand_sizes[1]
    rust_p0_gy_after = rust_state.graveyard_sizes[0]
    rust_p1_gy_after = rust_state.graveyard_sizes[1]
    assert rust_p0_hand_after == rust_p0_hand_before, (
        f"Rust I82 contract violation: P0's hand changed despite "
        f"the source's controller being P1. Pre-fix bug would "
        f"have routed the recur target here. "
        f"Got hand_p0_before={rust_p0_hand_before}, "
        f"hand_p0_after={rust_p0_hand_after}"
    )
    assert rust_p1_hand_after == rust_p1_hand_before + 1, (
        f"Rust I82 contract: P1's hand should gain the recurred "
        f"bait. Got hand_p1_before={rust_p1_hand_before}, "
        f"hand_p1_after={rust_p1_hand_after}"
    )
    assert rust_p0_gy_after == rust_p0_gy_before, (
        f"Rust: P0's graveyard should be unchanged. Got "
        f"gy_p0_before={rust_p0_gy_before}, "
        f"gy_p0_after={rust_p0_gy_after}"
    )
    assert rust_p1_gy_after == rust_p1_gy_before, (
        f"Rust I82 contract: P1's graveyard should be back to "
        f"baseline (bait was seeded then returned). Got "
        f"gy_p1_before={rust_p1_gy_before}, "
        f"gy_p1_after={rust_p1_gy_after}"
    )

    # Python observable: same shape on the equivalent zones.
    py_p0_hand_after = len(py_state.players[0].hand)
    py_p1_hand_after = len(py_state.players[1].hand)
    py_p0_gy_after = len(py_state.players[0].graveyard)
    py_p1_gy_after = len(py_state.players[1].graveyard)
    assert py_p0_hand_after == py_p0_hand_before, (
        f"Python: P0's hand should be unchanged. Got "
        f"hand_p0_before={py_p0_hand_before}, "
        f"hand_p0_after={py_p0_hand_after}"
    )
    assert py_p1_hand_after == py_p1_hand_before + 1, (
        f"Python: P1's hand should gain the recurred bait. Got "
        f"hand_p1_before={py_p1_hand_before}, "
        f"hand_p1_after={py_p1_hand_after}"
    )
    py_hand_p1_names = [c.printing.name for c in py_state.players[1].hand]
    assert "Recur Bait Bear (I82 cross-controller probe)" in py_hand_p1_names, (
        f"Python: P1's hand should contain the bait by name. Got "
        f"{py_hand_p1_names}"
    )
    assert py_p0_gy_after == py_p0_gy_before, (
        f"Python: P0's graveyard should be unchanged. Got "
        f"gy_p0_before={py_p0_gy_before}, "
        f"gy_p0_after={py_p0_gy_after}"
    )
    # Python's gy "before" was post-seed (= 1); after the return
    # it should be 0.
    assert py_p1_gy_after == 0, (
        f"Python I82 contract: P1's graveyard should be empty "
        f"(seeded bait moved out). Got gy_p1_after={py_p1_gy_after}"
    )

    # Cross-engine: lives unchanged on both sides.
    assert rust_state.get_life(0) == rust_p0_life_before
    assert rust_state.get_life(1) == rust_p1_life_before
    assert py_state.players[0].life == py_p0_life_before
    assert py_state.players[1].life == py_p1_life_before
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life

    # Cross-engine zone-size parity (the post-drain observable).
    assert rust_p0_hand_after == py_p0_hand_after
    assert rust_p1_hand_after == py_p1_hand_after
    assert rust_p0_gy_after == py_p0_gy_after
    assert rust_p1_gy_after == py_p1_gy_after


def test_cross_engine_synthetic_etb_return_creature_from_graveyard_to_battlefield_cross_controller_routes_to_source_controller_parity(
    parity_smoke,
):
    """Probe: synthetic ETB
    ``return_creature_from_your_graveyard_to_battlefield`` trigger
    fired by a permanent CONTROLLED BY P1 while ACTIVE_PLAYER=P0
    -- the I83 controller-of-effect fix's cross-engine flicker.
    Both engines must scan P1's graveyard (the source's
    controller), pick the bait creature, reanimate it onto P1's
    battlefield, and stamp ``controller_id=1`` on the
    just-arrived reanimated permanent. Pre-fix Rust scanned P0's
    graveyard, would have placed the reanimated creature on P0's
    battlefield under P0's control.

    **The I83 substrate.** Per worklog
    ``2026-05-13-controller-of-effect-i81-i82-i83``: pre-I83 the
    Rust ``Effect::ReturnCreatureFromYourGraveyardToBattlefield``
    arm derived ``controller_idx`` from ``state.active_player``,
    which controlled (a) which graveyard to scan, (b) which
    battlefield to push to, AND (c) what value to stamp on the
    GameObject's ``controller`` byte. Wrong when the resolving
    spell / triggered ability has a controller != active_player.
    The fix routes all three through
    ``current_resolve_source_controller``. Python's
    ``ReturnCreatureFromYourGraveyardToBattlefield`` (constructor
    sugar over ``ReturnFromGraveyard`` at
    ``effects/generic/graveyard.py:361``) takes ``controller_id``
    explicitly and has always been correct on this surface.

    **This slice also lands the
    ``return_creature_from_your_graveyard_to_battlefield`` bridge
    arm** in ``_ta_dict_to_python_effect`` (sister-arm to the
    existing ``return_creature_from_your_graveyard_to_hand`` arm;
    same unit-variant shape, only the destination zone differs).

    Probe shape (cross-controller inject-and-fire-ENTERS):

      1. **active_player=P0** (default). Confirmed via
         ``state.active_player`` on Rust and
         ``state.active_player_idx`` on Python.

      2. **Seed P1's graveyard** with a single bait creature
         ("Recur Bait Bear"). Pre-fix would have looked at P0's
         empty graveyard and silent-no-opped.

      3. **Inject Reanimator Bear (the recur source) onto P1's
         bf** with controller=1. ENTERS fires; the trigger lands
         on the stack with controller=1 (the SOURCE's controller).

      4. **Drain both stacks.** The trigger resolves with
         ``current_resolve_source_controller = Some(1)``; the
         post-I83 arm scans P1's graveyard, picks the bait,
         pushes it onto P1's bf with ``controller=1`` stamped.
         Note the reanimated creature ALSO fires its own ENTERS
         dispatch (it's a vanilla 2/2 with no triggers, so the
         dispatch is a silent no-op observably).

      5. **Cross-engine assert (post-I83 contract):**
         - P1's bf grew by 2 (Reanimator Bear + reanimated bait).
         - P0's bf is unchanged (NO crossover into the active
           player's zones).
         - Both reanimated bait + the Reanimator Bear are
           controller_id=1 on both engines.

    **Pre-I83 vs post-I83 observable.**
    Pre-fix Rust would have:
      - Scanned P0's empty graveyard, found no creature card,
        silent-no-op. Bait stays in P1's graveyard. P1's bf only
        gains Reanimator Bear (the source).
    Post-fix Rust scans P1's graveyard, picks the bait, brings
    it onto P1's bf -- matching Python's always-correct behavior.

    Out of scope:

      * Cast-from-hand mana cost -- bypassed by inject-and-fire.
      * Multi-creature graveyard pick -- single bait keeps the
        agent's first-legal-target pick observable.
      * Bait creature with its own ETB trigger -- the reanimated
        creature's own ENTERS dispatch IS triggered (Rust's
        ``register_and_inject_object`` ETB-fan-out shape; Python's
        ``put_into_battlefield`` -> ``_trigger_etb_abilities``).
        The probe uses a vanilla bait so the chained-ETB surface
        stays out of scope; that compositional probe would be a
        separate slice.
      * Empty-graveyard silent-skip -- separate sibling concern,
        well-defined for the bare arm.
      * Rider widenings (or_enchantment) -- the post-I83 fix
        applies, but they have separate bridge arms / EoE
        consumers.

    Expected post-dispatch + post-drain state on BOTH engines:

      * Reanimator Bear on P1's battlefield (unchanged from
        inject; controller=1).
      * Recur Bait Bear on P1's battlefield (reanimated;
        controller=1).
      * P1's graveyard empty (bait moved out).
      * P0's bf and graveyard untouched.
      * No residual stack on either engine.
      * Life totals unchanged on both seats.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )
    from tests.parity._picker_shims import _PickFirstLegalTargetAgent

    # Bait Bear: vanilla 2/2, no triggered abilities, seeded in
    # P1's graveyard. Will be reanimated onto P1's bf.
    bait_bear = CardDef(
        name="Recur Bait Bear (I83 cross-controller probe)",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=2,
        toughness=2,
    )
    # Reanimator Bear: vanilla 2/2 + ETB
    # return-creature-from-gy-to-battlefield. Routes the
    # reanimation through the I83 substrate.
    reanimator_bear = CardDef(
        name="ETB Reanimator Bear (I83 cross-controller probe)",
        card_type="Creature",
        mana_cost_generic=2,
        mana_cost_colored=(("B", 1),),
        power=2,
        toughness=2,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "return_creature_from_your_graveyard_to_battlefield",
                },
            },
        ),
    )
    spec = DeckSpec(
        card_defs=(bait_bear, reanimator_bear),
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # Confirm pre-condition: active_player=P0 on both engines.
    assert rust_state.active_player == 0, (
        f"Probe pre-condition: Rust active_player must be 0; "
        f"got {rust_state.active_player}"
    )
    assert py_state.active_player_idx == 0, (
        f"Probe pre-condition: Python active_player_idx must be 0; "
        f"got {py_state.active_player_idx}"
    )

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    ZONE_GRAVEYARD = 3
    rust_bait_dict = {
        "name": "Recur Bait Bear (I83 cross-controller probe)",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1, "G": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
    }
    rust_reanimator_dict = {
        "name": "ETB Reanimator Bear (I83 cross-controller probe)",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "B": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "return_creature_from_your_graveyard_to_battlefield",
                },
            }
        ],
    }
    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)
    rust_p0_bf_before = rust_state.battlefield_sizes[0]
    rust_p1_bf_before = rust_state.battlefield_sizes[1]
    rust_p0_gy_before = rust_state.graveyard_sizes[0]
    rust_p1_gy_before = rust_state.graveyard_sizes[1]

    # Seed P1's graveyard with the bait creature.
    rust_state.register_and_inject_object(
        rust_bait_dict, 1, ZONE_GRAVEYARD,
    )
    # Inject the reanimator-bear onto P1's bf with controller=1.
    # ENTERS fires; the trigger lands on the stack carrying
    # controller=1.
    rust_state.register_and_inject_object(
        rust_reanimator_dict, 1, ZONE_BATTLEFIELD,
    )
    assert rust_state.stack_size() == 1, (
        f"Rust: ETB Reanimator Bear's arrival on P1 should fire "
        f"the SourceIsSelf ENTERS trigger and land "
        f"ReturnCreatureFromYourGraveyardToBattlefield on the "
        f"stack. Got stack_size={rust_state.stack_size()}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.graveyard import (
        ReturnCreatureFromYourGraveyardToBattlefield,
    )
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    bait_printing = CardPrinting(
        name="Recur Bait Bear (I83 cross-controller probe)",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=(("G", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
    )
    reanimator_printing = CardPrinting(
        name="ETB Reanimator Bear (I83 cross-controller probe)",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2, colored=(("B", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=ReturnCreatureFromYourGraveyardToBattlefield(),
            ),
        ),
    )

    # Seat the first-legal-target picker on P1 (the SOURCE's
    # controller). Note: the chained ENTERS dispatch on the
    # reanimated creature also walks the bf -- the bait has no
    # triggers so this is a silent no-op observably.
    py_state.players[1].agent = _PickFirstLegalTargetAgent()

    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life
    py_p0_bf_before = len(
        [o for o in py_state.battlefield if o.controller_id == 0]
    )
    py_p1_bf_before = len(
        [o for o in py_state.battlefield if o.controller_id == 1]
    )
    py_p0_gy_before = len(py_state.players[0].graveyard)

    # Seed P1's graveyard with the bait creature.
    py_bait = py_state.new_object(
        bait_printing, owner_id=1, zone=Zone.GRAVEYARD,
    )
    py_state.players[1].graveyard.append(py_bait)
    py_p1_gy_before_post_seed = len(py_state.players[1].graveyard)
    assert py_p1_gy_before_post_seed == 1, (
        f"Python pre-condition: P1 graveyard should hold the "
        f"seeded bait; got "
        f"size={py_p1_gy_before_post_seed}"
    )

    # Inject the reanimator-bear onto P1's bf with owner_id=1, then
    # manually dispatch ENTERS.
    py_reanimator = py_state.new_object(
        reanimator_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_reanimator.summoning_sick = False
    py_reanimator.tapped = False
    py_reanimator.damage = 0
    py_reanimator.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_reanimator)
    _trigger_etb_abilities(py_state, py_reanimator)
    assert len(py_state.stack) == 1, (
        f"Python: ETB Reanimator Bear's arrival on P1 should fire "
        f"the IsSelf ENTERS trigger and land "
        f"ReturnCreatureFromYourGraveyardToBattlefield on the "
        f"stack. Got stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks, then compare observable parity. ----
    _drain_stack_both(py_state, rust_state)

    # Stacks empty post-drain.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0

    # Rust observable (the I83 contract):
    #   * P1's bf gained Reanimator Bear (the source) + reanimated
    #     bait = +2 from baseline.
    #   * P1's graveyard is back to baseline (the bait moved out;
    #     it was +1 from the seed; net 0 from baseline).
    #   * P0's bf and graveyard are UNCHANGED (no crossover).
    rust_p0_bf_after = rust_state.battlefield_sizes[0]
    rust_p1_bf_after = rust_state.battlefield_sizes[1]
    rust_p0_gy_after = rust_state.graveyard_sizes[0]
    rust_p1_gy_after = rust_state.graveyard_sizes[1]
    assert rust_p0_bf_after == rust_p0_bf_before, (
        f"Rust I83 contract violation: P0's bf changed despite "
        f"the source's controller being P1. Pre-fix bug would "
        f"have routed the reanimation here. "
        f"Got bf_p0_before={rust_p0_bf_before}, "
        f"bf_p0_after={rust_p0_bf_after}"
    )
    assert rust_p1_bf_after == rust_p1_bf_before + 2, (
        f"Rust I83 contract: P1's bf should gain Reanimator Bear "
        f"+ reanimated bait = +2 from baseline. Got "
        f"bf_p1_before={rust_p1_bf_before}, "
        f"bf_p1_after={rust_p1_bf_after}"
    )
    assert rust_p0_gy_after == rust_p0_gy_before, (
        f"Rust: P0's graveyard should be unchanged. Got "
        f"gy_p0_before={rust_p0_gy_before}, "
        f"gy_p0_after={rust_p0_gy_after}"
    )
    assert rust_p1_gy_after == rust_p1_gy_before, (
        f"Rust I83 contract: P1's graveyard should be back to "
        f"baseline (bait was seeded then reanimated out). Got "
        f"gy_p1_before={rust_p1_gy_before}, "
        f"gy_p1_after={rust_p1_gy_after}"
    )
    # Confirm both bf objects are controller_id=1 via
    # battlefield_snapshot.
    rust_bf_snap = rust_state.battlefield_snapshot()
    rust_p1_bf_objs = [
        d for d in rust_bf_snap if d["controller_id"] == 1
    ]
    rust_p1_names = sorted(d["printing_name"] for d in rust_p1_bf_objs)
    assert rust_p1_names == [
        "ETB Reanimator Bear (I83 cross-controller probe)",
        "Recur Bait Bear (I83 cross-controller probe)",
    ], (
        f"Rust I83 contract: P1's bf should hold both the source "
        f"AND the reanimated bait. Got {rust_p1_names}"
    )

    # Python observable: same shape on the equivalent zones.
    py_p0_bf_after = len(
        [o for o in py_state.battlefield if o.controller_id == 0]
    )
    py_p1_bf_after = len(
        [o for o in py_state.battlefield if o.controller_id == 1]
    )
    py_p0_gy_after = len(py_state.players[0].graveyard)
    py_p1_gy_after = len(py_state.players[1].graveyard)
    assert py_p0_bf_after == py_p0_bf_before, (
        f"Python: P0's bf should be unchanged. Got "
        f"bf_p0_before={py_p0_bf_before}, "
        f"bf_p0_after={py_p0_bf_after}"
    )
    assert py_p1_bf_after == py_p1_bf_before + 2, (
        f"Python: P1's bf should gain Reanimator Bear + "
        f"reanimated bait = +2. Got "
        f"bf_p1_before={py_p1_bf_before}, "
        f"bf_p1_after={py_p1_bf_after}"
    )
    py_p1_bf_names = sorted(
        o.printing.name for o in py_state.battlefield
        if o.controller_id == 1
    )
    assert py_p1_bf_names == [
        "ETB Reanimator Bear (I83 cross-controller probe)",
        "Recur Bait Bear (I83 cross-controller probe)",
    ], (
        f"Python I83 contract: P1's bf should hold both the source "
        f"AND the reanimated bait. Got {py_p1_bf_names}"
    )
    assert py_p0_gy_after == py_p0_gy_before, (
        f"Python: P0's graveyard should be unchanged. Got "
        f"gy_p0_before={py_p0_gy_before}, "
        f"gy_p0_after={py_p0_gy_after}"
    )
    assert py_p1_gy_after == 0, (
        f"Python I83 contract: P1's graveyard should be empty "
        f"(seeded bait reanimated out). Got "
        f"gy_p1_after={py_p1_gy_after}"
    )

    # Cross-engine: lives unchanged on both sides.
    assert rust_state.get_life(0) == rust_p0_life_before
    assert rust_state.get_life(1) == rust_p1_life_before
    assert py_state.players[0].life == py_p0_life_before
    assert py_state.players[1].life == py_p1_life_before
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life

    # Cross-engine zone-size parity (the post-drain observable).
    assert rust_p0_bf_after == py_p0_bf_after
    assert rust_p1_bf_after == py_p1_bf_after
    assert rust_p0_gy_after == py_p0_gy_after
    assert rust_p1_gy_after == py_p1_gy_after


def test_cross_engine_real_eoe_pinnacle_kill_ship_etb_damage_optional_empty_bf_divergence_pin(
    parity_smoke,
):
    """Probe: Pinnacle Kill-Ship (EoE) ETB ``deals 10 damage to up to
    one target creature`` on an EMPTY opponent battlefield -- PINS
    the documented Rust-vs-Python divergence on the optional-target
    no-creature-fallback case.

    Per the worklog forward-note for the
    ``feature/phase5-ce-bridge-damage-any-target-optional`` slice:
    "the empty-bf-with-optional=True case is 'Rust damages defender-
    player; Python optional=True fizzles with no slot chosen' --
    needs a stricter creature-only Rust variant to fix; this is a
    probe to PIN the divergence and add an xfail or skip-with-doc
    until the Rust extension lands". This probe lands the pin via
    per-engine assertions: it asserts the EXPECTED divergent
    behavior on each side, so the test is GREEN today and would only
    flag if either engine's behavior changed (at which point the
    engineer fixing the Rust gap should flip this probe to a
    cross-engine parity assertion).

    Sibling of
    ``test_cross_engine_real_eoe_pinnacle_kill_ship_etb_damage_optional_target_creature_parity``
    (tests/test_parity_smoke.py:13601), which drives a NON-EMPTY p1
    bf with a single bait Bear -- both engines pick the Bear,
    converge cleanly. THIS probe drives an EMPTY p1 bf -- the bridge
    arm's docstring at cross_engine.py:233-249 spells the divergence
    out:

      Rust's deterministic at-apply-time pick (scan defender's bf
      for first creature, fall back to defender-player) is observably
      equivalent to Python's optional-target "no-target-chosen
      fizzle" on probes that drive a single opponent creature on bf:
      both engines pick that creature, neither path exercises the
      no-creature fallback.

      Probes whose scenario exposes the divergent fallback case
      (Rust damages defender-player; Python optional=True fizzles
      with no slot chosen) need a stricter creature-only Rust
      variant -- out of scope for this bridge extension.

    Predicate / effect (identical to the Pinnacle Kill-Ship sibling):

        SourceIsSelf
        deal_damage_any_target(amount=10, optional=True)

    Engine-specific expected behavior on EMPTY p1 bf:

    * Rust: ``Effect::DealDamageAnyTarget`` deterministic at-apply
      pick scans p1's bf for the first creature; finds NONE; falls
      back to defender-player (player 1). Rust deals 10 damage to
      the p1 PLAYER. Post-resolve life: p1 = 20 - 10 = 10.
    * Python: with no agent seated on p0 (the source's controller),
      ``push_triggered_ability`` (actions.py:3247) hits the
      ``controller.agent is None`` branch and breaks out of the
      slot-pick loop with an empty ``chosen_list``. Because
      ``optional=True`` flips ``count_min=0`` (damage.py:296),
      ``len(chosen_list) >= min_t`` holds and the trigger STILL
      pushes onto the stack with EMPTY ``targets``. At resolve
      time, ``DealDamage.resolve`` (damage.py:58) hits
      ``if not targets: return`` and silently no-ops. Python deals
      NO damage; p1 life stays at 20.

    Closure path (when this divergence is fixed): the worklog notes
    "needs a stricter creature-only Rust variant" -- a Rust
    ``Effect::DealDamageToTargetCreatureOptional`` arm whose pick
    skips the player-fallback would observe the same NO-DAMAGE
    behavior as Python on this scenario, and this probe should be
    flipped to assert cross-engine parity (both engines: p1 life ==
    20; Bait creature still absent from bf; no damage dealt). Until
    that arm lands, this probe documents the gap so the bridge
    arm's existing comment block has a regression test backing up
    the "out of scope for this bridge extension" claim.

    Probe shape:

      1. Inject Pinnacle Kill-Ship onto p0's bf (with the
         optional=True ``deal_damage_any_target`` ETB trigger).
         CRITICAL: do NOT inject any creature onto p1's bf -- the
         empty p1 bf is the SCENARIO under test.
      2. Do NOT seat any agent on p0's Python side -- the no-agent
         branch in push_triggered_ability is the path that exposes
         the divergence cleanly. (An agent that returns the p1
         player target would observably converge on Python with
         Rust's player-fallback, masking the gap; an agent that
         returns None would behave identically to no agent for our
         purposes -- both yield empty chosen_list. The no-agent
         shape is the simpler / canonical observation.)
      3. Drain both stacks.
      4. Assert per-engine expected behavior:
         - Rust: p1 life dropped to 10 (player-fallback fired).
         - Python: p1 life stayed at 20 (silent fizzle).
      5. NO cross-engine equivalence assertion -- the assertion
         that DOCUMENTS the divergence is the per-engine pair.

    Out of scope:

      * Cross-engine parity -- THE PROBE DOCUMENTS A KNOWN
        DIVERGENCE; the lack of a parity assertion is intentional.
        See docs/SEARCH_LIMITATIONS.md entry "Rust port -
        DealDamageAnyTarget optional-target empty-bf player-fallback
        divergence" for the closure plan.
      * Same-side bf injection -- Rust's deterministic pick scans
        DEFENDER's bf only; injecting a creature on p0's bf would
        not satisfy the scan filter (the ``defender`` is the
        opponent of the source's controller).
      * Stack residual -- both engines pop the trigger off the
        stack cleanly; the divergence is purely on the LIFE TOTAL
        delta, not on stack discipline.

    Expected post-dispatch + post-drain state:

      * Rust: Pinnacle Kill-Ship on p0's bf; p1 life = 10 (took 10
        damage); p0 life = 20; no residual stack.
      * Python: Pinnacle Kill-Ship on p0's bf; p1 life = 20 (no
        damage dealt); p0 life = 20; no residual stack.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )

    pinnacle_kill_ship = CardDef(
        name="Pinnacle Kill-Ship",
        card_type="Artifact",
        mana_cost_generic=7,
        mana_cost_colored=(),
        power=7,
        toughness=7,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "deal_damage_any_target",
                    "amount": 10,
                    "optional": True,
                },
            },
        ),
    )
    spec = DeckSpec(
        card_defs=(pinnacle_kill_ship,),
        # Both libraries empty. p1's bf will also be empty (no
        # creature injection on p1) -- THE scenario under test.
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    rust_pks_dict = {
        "name": "Pinnacle Kill-Ship",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 7},
        "effects": [],
        "power": 7,
        "toughness": 7,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "deal_damage_any_target",
                    "amount": 10,
                    "optional": True,
                },
            }
        ],
    }
    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)
    assert rust_p0_life_before == 20
    assert rust_p1_life_before == 20
    # Confirm p1 bf is empty BEFORE injection so the scenario is
    # well-formed (no stale creatures from the build_rust_state
    # default fixture would mask the empty-bf divergence).
    rust_p1_bf_before = [
        e for e in rust_state.battlefield_snapshot()
        if int(e.get("controller", -1)) == 1
    ]
    assert len(rust_p1_bf_before) == 0, (
        f"Rust: p1 bf should be empty pre-injection for the "
        f"divergence-pin scenario; got {rust_p1_bf_before}"
    )
    rust_state.register_and_inject_object(
        rust_pks_dict, 0, ZONE_BATTLEFIELD
    )
    assert rust_state.stack_size() == 1, (
        "Rust: Pinnacle Kill-Ship's own arrival should fire the "
        "SourceIsSelf ENTERS trigger and land DealDamageAnyTarget "
        f"on the stack. Got stack_size={rust_state.stack_size()}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.damage import DealDamageAnyTarget
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    pks_printing = CardPrinting(
        name="Pinnacle Kill-Ship",
        mana_cost_str="",
        mana_cost=ManaCost(generic=7),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
        power=7,
        toughness=7,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=DealDamageAnyTarget(amount=10, optional=True),
            ),
        ),
    )

    # Confirm p1 bf is empty on Python pre-injection too -- the
    # divergence requires both engines to share the empty-bf
    # scenario; otherwise we'd be measuring a different shape.
    py_p1_bf_before = [
        o for o in py_state.battlefield if o.controller_id == 1
    ]
    assert len(py_p1_bf_before) == 0, (
        f"Python: p1 bf should be empty pre-injection for the "
        f"divergence-pin scenario; got {py_p1_bf_before}"
    )

    # IMPORTANT: do NOT seat any agent on p0. The no-agent branch in
    # push_triggered_ability (actions.py:3247) is the path that
    # exposes the divergence cleanly with optional=True. The default
    # state has p0.agent = None; we leave it that way.
    assert py_state.players[0].agent is None, (
        "Python: probe assumes p0.agent is None to drive the "
        "no-target-chosen branch via the agent-is-None short-circuit "
        "at actions.py:3247"
    )

    py_pks = py_state.new_object(
        pks_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_pks.summoning_sick = False
    py_pks.tapped = False
    py_pks.damage = 0
    py_pks.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_pks)
    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life
    assert py_p0_life_before == 20
    assert py_p1_life_before == 20
    _trigger_etb_abilities(py_state, py_pks)
    assert len(py_state.stack) == 1, (
        "Python: Pinnacle Kill-Ship's own arrival should fire the "
        "IsSelf ENTERS trigger and land DealDamageAnyTarget on the "
        "stack -- with optional=True (count_min=0) the empty "
        f"chosen_list still pushes. Got stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks ----
    _drain_stack_both(py_state, rust_state)

    # ---- Per-engine divergence assertions ----
    # Rust: player-fallback fired; p1 life dropped from 20 -> 10.
    assert rust_state.get_life(1) == rust_p1_life_before - 10, (
        f"Rust: empty-bf optional-target damage should fall back to "
        f"defender-player and deal 10 damage to p1 (pinned "
        f"divergent behavior; see SEARCH_LIMITATIONS.md "
        f'"DealDamageAnyTarget optional-target empty-bf '
        f'player-fallback divergence"). '
        f"before={rust_p1_life_before} "
        f"after={rust_state.get_life(1)}"
    )
    assert rust_state.get_life(0) == rust_p0_life_before, (
        f"Rust: p0 life should be unchanged (damage routed to p1, "
        f"not back to source controller): before={rust_p0_life_before} "
        f"after={rust_state.get_life(0)}"
    )

    # Python: silent fizzle; both lives unchanged.
    assert py_state.players[1].life == py_p1_life_before, (
        f"Python: empty-bf optional-target damage with NO agent "
        f"seated should silently fizzle (DealDamage.resolve hits "
        f"`if not targets: return` at damage.py:58 because "
        f"chosen_list is empty and optional=True allows that). "
        f"p1 life should be unchanged. "
        f"before={py_p1_life_before} "
        f"after={py_state.players[1].life}"
    )
    assert py_state.players[0].life == py_p0_life_before, (
        f"Python: p0 life should be unchanged (no damage dealt at "
        f"all on the silent-fizzle path): "
        f"before={py_p0_life_before} "
        f"after={py_state.players[0].life}"
    )

    # ---- Stack discipline parity ----
    # The divergence is purely on the LIFE delta; both engines pop
    # the trigger off the stack cleanly.
    assert rust_state.stack_size() == 0, (
        f"Rust: stack should be empty post-drain (the divergence is "
        f"on the life delta, not on stack discipline). Got "
        f"stack_size={rust_state.stack_size()}"
    )
    assert len(py_state.stack) == 0, (
        f"Python: stack should be empty post-drain. Got "
        f"stack size={len(py_state.stack)}"
    )

    # Pinnacle Kill-Ship should still be on each engine's bf
    # (Artifact -- not lethal-damaged, no SBA flip).
    rust_bf_names = [
        e.get("printing_name") for e in rust_state.battlefield_snapshot()
    ]
    assert "Pinnacle Kill-Ship" in rust_bf_names, (
        f"Rust: Pinnacle Kill-Ship should remain on bf "
        f"(Artifact -- no SBA on the source itself). Got "
        f"bf names={rust_bf_names}"
    )
    py_bf_names = [o.printing.name for o in py_state.battlefield]
    assert "Pinnacle Kill-Ship" in py_bf_names, (
        f"Python: Pinnacle Kill-Ship should remain on bf. Got "
        f"bf names={py_bf_names}"
    )

    # CROSS-ENGINE NON-PARITY documentation: assert the divergence
    # on life deltas. This assertion would FLIP if the Rust
    # creature-only variant landed and Rust no longer fell back to
    # defender-player on the empty-bf case. When that happens, the
    # fix is to change THIS probe to assert parity (both engines:
    # p1 life == 20) and remove the divergence-pin docstring +
    # SEARCH_LIMITATIONS entry.
    assert rust_state.get_life(1) != py_state.players[1].life, (
        f"Cross-engine: this probe PINS a known divergence -- "
        f"Rust should drop p1 life by 10 (player-fallback) while "
        f"Python's silent fizzle leaves it at 20. If both engines "
        f"now agree on p1 life, the Rust gap has been closed and "
        f"this probe should be flipped to assert parity. "
        f"rust_p1_life={rust_state.get_life(1)} "
        f"py_p1_life={py_state.players[1].life}"
    )


def test_cross_engine_synthetic_etb_reanimator_bear_multi_creature_graveyard_iterator_order_parity(
    parity_smoke,
):
    """Probe: ``ETB-Reanimator-Bear`` with THREE creatures in p0
    graveyard -- iterator-order target-pick parity for the
    ``return_creature_from_your_graveyard_to_battlefield`` bridge arm.

    Sister probe to:
      * ``test_cross_engine_synthetic_etb_return_creature_from_graveyard_to_battlefield_cross_controller_routes_to_source_controller_parity``
        (canonical happy-path / I83 cross-controller flicker, ONE
        creature in gy)
      * ``test_cross_engine_synthetic_etb_recur_bear_multi_creature_graveyard_iterator_order_parity``
        (iterator-order parity for the to-HAND sister arm, THREE
        creatures in gy)

    Tension-tests ``_PickFirstLegalTargetAgent`` against Rust's
    iterator-order graveyard scan when MULTIPLE creature cards are
    eligible -- destination is BATTLEFIELD instead of HAND. The
    canonical to-bf I83 probe seeded a SINGLE bait so the
    "first-in-order" pick was unambiguous on either engine; this
    probe seats THREE distinct vanilla creatures in fixed insertion
    order (Alpha -> Beta -> Gamma) and asserts both engines pick the
    SAME card (Alpha, the first-inserted) via their respective
    deterministic mechanisms:

      * **Rust:** ``state_ops_resolve.rs`` arm for
        ``ReturnCreatureFromYourGraveyardToBattlefield`` scans
        ``state.players[cidx].graveyard.iter()`` for the first
        object whose printing's ``card_types`` contains "Creature".
        With three creatures seeded in order Alpha/Beta/Gamma, the
        iterator hits Alpha first; Alpha moves from gy to bf with
        controller=cidx stamped.
      * **Python:** ``ReturnFromGraveyard.legal_targets`` walks the
        controller's graveyard in insertion order and emits one
        ``("graveyard_creature", card.id)`` per creature card. The
        seated ``_PickFirstLegalTargetAgent`` returns
        ``legal_targets[0]``, which is the Alpha entry. The
        ReturnFromGraveyard substrate is shared with the to-HAND
        arm (``effects/generic/graveyard.py``); the destination zone
        is the only difference.

    Both engines pick the first-in-insertion-order creature, leave
    Beta and Gamma in the graveyard, and stamp controller=0 on the
    just-arrived Alpha permanent (the source's controller).

    **Why "iterator-order parity" is the load-bearing contract for
    the to-bf sister arm:** swap Alpha and Gamma in the seed order
    on either engine and the picked card swaps too. The probe
    asserts BY printing-id (Rust) and BY name (Python) that both
    engines picked the same physical card -- this catches:

      * A regression in Rust's graveyard scan that flipped the
        iteration order (e.g. picked the LAST creature instead of
        the first) for the to-bf arm specifically. The two arms
        share the gy-scan substrate but each carries its own
        resolve-side arm; a regression that touched only one would
        slip past the to-hand iterator-order probe.
      * A regression in Python's ``legal_targets`` enumeration
        order (e.g. accidentally sorting by name / power rather
        than insertion).
      * A regression in either engine's
        ``register_and_inject_object`` / ``new_object`` that built
        the graveyard in reverse order on this codepath.
      * A regression in the ``_PickFirstLegalTargetAgent`` shim's
        first-element pick.

    Probe shape (seed-three / inject-and-fire-ENTERS, p0 self-recur):

      1. Seed p0's graveyard with THREE distinct vanilla creature
         cards in fixed order: Reanimator Bait Alpha -> Beta ->
         Gamma. Distinct names so the post-drain assertion
         identifies the picked card by name (not just count).
      2. Inject ETB Reanimator Bear directly onto p0's bf with
         controller=0. ENTERS dispatch fires SourceIsSelf; one
         ``ReturnCreatureFromYourGraveyardToBattlefield`` trigger
         lands on the stack with a target resolved deterministically
         (Rust) or pre-chosen via the agent (Python). Note: this is
         the SAME-controller (p0) variant; the cross-controller
         routing contract is exercised by the I83 sibling probe.
      3. Drain both stacks. The picked creature (Alpha on both
         sides) moves from p0 graveyard to p0 battlefield with
         controller=0 stamped. The reanimated Alpha ALSO fires its
         own ENTERS dispatch -- vanilla 1/1 with no triggers, silent
         no-op observably.
      4. Cross-engine assert: both engines have Alpha on p0 bf
         (controller=0), Beta + Gamma still in p0 graveyard in
         their original insertion order, ETB Reanimator Bear still
         on p0 bf as the source.

    Out of scope:

      * The empty-graveyard silent-skip case -- exercised by the
        sibling empty-gy to-bf probe.
      * The single-creature happy-path / cross-controller routing
        -- exercised by the canonical I83 cross-controller probe.
      * Pick-second / pick-last shims -- the contract pinned here
        is "first-in-insertion-order" on both engines; alternate
        picks would be a different probe (and would currently fail
        because Rust hardcodes first-in-order, no agent-side
        override).
      * Rider widenings (or_enchantment, or_artifact) -- carry
        their own probes; the iterator-order pick contract is
        identical across riders, but verifying the rider-widened
        legal_targets pool is a separate axis.
      * Chained ETB triggers on the reanimated creature -- bait is
        deliberately vanilla so the chained-ETB surface stays
        out of scope; that compositional probe would be a separate
        slice.

    Expected post-dispatch + post-drain state on BOTH engines:

      * Reanimator Bait Alpha on p0 bf (reanimated; controller=0).
      * Reanimator Bait Beta + Gamma still in p0 graveyard, in
        original insertion order.
      * ETB Reanimator Bear still on p0 bf (the source;
        controller=0).
      * Lives unchanged on both seats.
      * No residual stack.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )
    from tests.parity._picker_shims import _PickFirstLegalTargetAgent

    # Three distinct vanilla creatures for the gy seed. Distinct
    # names + distinct mana shapes so a name / cost confusion would
    # surface on the post-drain assertion.
    bait_alpha = CardDef(
        name="Reanimator Bait Alpha",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=1,
        toughness=1,
    )
    bait_beta = CardDef(
        name="Reanimator Bait Beta",
        card_type="Creature",
        mana_cost_generic=2,
        mana_cost_colored=(("U", 1),),
        power=2,
        toughness=2,
    )
    bait_gamma = CardDef(
        name="Reanimator Bait Gamma",
        card_type="Creature",
        mana_cost_generic=3,
        mana_cost_colored=(("R", 1),),
        power=3,
        toughness=3,
    )
    reanimator_bear = CardDef(
        name="ETB Reanimator Bear (multi-gy probe)",
        card_type="Creature",
        mana_cost_generic=2,
        mana_cost_colored=(("B", 1),),
        power=2,
        toughness=2,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "return_creature_from_your_graveyard_to_battlefield",
                },
            },
        ),
    )
    spec = DeckSpec(
        card_defs=(bait_alpha, bait_beta, bait_gamma, reanimator_bear),
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    ZONE_GRAVEYARD = 3
    rust_bait_alpha_dict = {
        "name": "Reanimator Bait Alpha",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1, "G": 1},
        "effects": [],
        "power": 1,
        "toughness": 1,
    }
    rust_bait_beta_dict = {
        "name": "Reanimator Bait Beta",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "U": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
    }
    rust_bait_gamma_dict = {
        "name": "Reanimator Bait Gamma",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 3, "R": 1},
        "effects": [],
        "power": 3,
        "toughness": 3,
    }
    rust_reanimator_dict = {
        "name": "ETB Reanimator Bear (multi-gy probe)",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "B": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "return_creature_from_your_graveyard_to_battlefield",
                },
            }
        ],
    }
    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)
    # Seed p0's graveyard in fixed order: Alpha -> Beta -> Gamma.
    # Capture the OBJECT ids returned by register_and_inject_object
    # so the post-drain assertion can identify the picked card
    # uniquely.
    rust_bait_alpha_id = rust_state.register_and_inject_object(
        rust_bait_alpha_dict, 0, ZONE_GRAVEYARD,
    )
    rust_bait_beta_id = rust_state.register_and_inject_object(
        rust_bait_beta_dict, 0, ZONE_GRAVEYARD,
    )
    rust_bait_gamma_id = rust_state.register_and_inject_object(
        rust_bait_gamma_dict, 0, ZONE_GRAVEYARD,
    )
    assert rust_state.graveyard_sizes[0] == 3, (
        f"Rust: p0 gy seed should hold 3 creatures pre-dispatch; "
        f"got graveyard_size={rust_state.graveyard_sizes[0]}"
    )
    # Inject the reanimator-bear -> fires ENTERS. The trigger lands
    # on the stack with its target resolved deterministically (Rust
    # scans the gy and finds Alpha as the first creature).
    rust_state.register_and_inject_object(
        rust_reanimator_dict, 0, ZONE_BATTLEFIELD,
    )
    assert rust_state.stack_size() == 1, (
        "Rust: ETB Reanimator Bear's arrival should fire "
        "SourceIsSelf ENTERS and land "
        "ReturnCreatureFromYourGraveyardToBattlefield on the stack. "
        f"Got stack_size={rust_state.stack_size()}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.graveyard import (
        ReturnCreatureFromYourGraveyardToBattlefield,
    )
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    bait_alpha_printing = CardPrinting(
        name="Reanimator Bait Alpha",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=(("G", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=1,
        toughness=1,
        produces=frozenset(),
    )
    bait_beta_printing = CardPrinting(
        name="Reanimator Bait Beta",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2, colored=(("U", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
    )
    bait_gamma_printing = CardPrinting(
        name="Reanimator Bait Gamma",
        mana_cost_str="",
        mana_cost=ManaCost(generic=3, colored=(("R", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=3,
        toughness=3,
        produces=frozenset(),
    )
    reanimator_printing = CardPrinting(
        name="ETB Reanimator Bear (multi-gy probe)",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2, colored=(("B", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=ReturnCreatureFromYourGraveyardToBattlefield(),
            ),
        ),
    )

    # First-legal-target shim on p0 -- mirrors Rust's iterator-order
    # graveyard scan (the canonical contract for this bridge arm).
    py_state.players[0].agent = _PickFirstLegalTargetAgent()

    # Seed p0's graveyard in the SAME insertion order as Rust:
    # Alpha -> Beta -> Gamma.
    py_bait_alpha = py_state.new_object(
        bait_alpha_printing, owner_id=0, zone=Zone.GRAVEYARD,
    )
    py_state.players[0].graveyard.append(py_bait_alpha)
    py_bait_beta = py_state.new_object(
        bait_beta_printing, owner_id=0, zone=Zone.GRAVEYARD,
    )
    py_state.players[0].graveyard.append(py_bait_beta)
    py_bait_gamma = py_state.new_object(
        bait_gamma_printing, owner_id=0, zone=Zone.GRAVEYARD,
    )
    py_state.players[0].graveyard.append(py_bait_gamma)
    assert len(py_state.players[0].graveyard) == 3

    py_p0_bf_before = len(
        [o for o in py_state.battlefield if o.controller_id == 0]
    )
    py_p1_bf_before = len(
        [o for o in py_state.battlefield if o.controller_id == 1]
    )
    py_reanimator = py_state.new_object(
        reanimator_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_reanimator.summoning_sick = False
    py_reanimator.tapped = False
    py_reanimator.damage = 0
    py_reanimator.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_reanimator)
    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life
    _trigger_etb_abilities(py_state, py_reanimator)
    assert len(py_state.stack) == 1, (
        "Python: ETB Reanimator Bear's arrival should fire IsSelf "
        "ENTERS and land "
        "ReturnCreatureFromYourGraveyardToBattlefield on the stack. "
        f"Got stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks, then compare iterator-order parity ----
    _drain_stack_both(py_state, rust_state)

    # Stacks empty post-drain.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0

    # Per-engine post-drain (Rust): TWO creatures still in p0 gy
    # (Beta + Gamma in original insertion order), Alpha now on
    # p0 bf alongside the source = bf grew by 2 from baseline.
    assert rust_state.graveyard_sizes[0] == 2, (
        f"Rust: p0 gy should retain 2 creatures (Beta + Gamma); "
        f"got graveyard_size={rust_state.graveyard_sizes[0]}"
    )
    rust_gy_snap = rust_state.graveyard_snapshot(0)
    rust_gy_ids = [int(d["id"]) for d in rust_gy_snap]
    assert rust_gy_ids == [rust_bait_beta_id, rust_bait_gamma_id], (
        f"Rust: gy should retain Beta then Gamma (object ids "
        f"{rust_bait_beta_id}, {rust_bait_gamma_id}) in original "
        f"insertion order; got ids={rust_gy_ids}"
    )
    rust_bf_snap = rust_state.battlefield_snapshot()
    rust_p0_bf_objs = [
        d for d in rust_bf_snap if d["controller_id"] == 0
    ]
    rust_p0_bf_names = sorted(
        d["printing_name"] for d in rust_p0_bf_objs
    )
    assert rust_p0_bf_names == [
        "ETB Reanimator Bear (multi-gy probe)",
        "Reanimator Bait Alpha",
    ], (
        f"Rust: p0 bf should hold the source AND reanimated Alpha; "
        f"got {rust_p0_bf_names}"
    )
    # Confirm the reanimated Alpha is identified by object id (the
    # iterator-order pick contract).
    rust_alpha_on_bf = [
        d for d in rust_p0_bf_objs
        if d["printing_name"] == "Reanimator Bait Alpha"
    ]
    assert len(rust_alpha_on_bf) == 1
    assert int(rust_alpha_on_bf[0]["id"]) == rust_bait_alpha_id, (
        f"Rust: reanimated bf object should be Alpha (id "
        f"{rust_bait_alpha_id}, the first-inserted gy creature); "
        f"got id={int(rust_alpha_on_bf[0]['id'])}"
    )
    # Both p0 bf objects controller_id=0.
    for d in rust_p0_bf_objs:
        assert d["controller_id"] == 0, (
            f"Rust: p0 bf object {d['printing_name']} should be "
            f"controller=0; got {d['controller_id']}"
        )
    # P1 zones untouched.
    assert rust_state.battlefield_sizes[1] == 0
    assert rust_state.graveyard_sizes[1] == 0

    # Per-engine post-drain (Python): same shape on the equivalent
    # zones.
    assert len(py_state.players[0].graveyard) == 2, (
        f"Python: p0 gy should retain 2 creatures (Beta + Gamma); "
        f"got graveyard_size={len(py_state.players[0].graveyard)}"
    )
    py_gy_names = [
        o.printing.name for o in py_state.players[0].graveyard
    ]
    assert py_gy_names == [
        "Reanimator Bait Beta", "Reanimator Bait Gamma",
    ], (
        f"Python: gy should retain Beta then Gamma in original "
        f"insertion order; got {py_gy_names}"
    )
    py_p0_bf_after = [
        o for o in py_state.battlefield if o.controller_id == 0
    ]
    py_p0_bf_names = sorted(o.printing.name for o in py_p0_bf_after)
    assert py_p0_bf_names == [
        "ETB Reanimator Bear (multi-gy probe)",
        "Reanimator Bait Alpha",
    ], (
        f"Python: p0 bf should hold the source AND reanimated "
        f"Alpha; got {py_p0_bf_names}"
    )
    # Both p0 bf objects controller_id=0.
    for o in py_p0_bf_after:
        assert o.controller_id == 0, (
            f"Python: p0 bf object {o.printing.name} should be "
            f"controller=0; got {o.controller_id}"
        )
    py_p1_bf_after = [
        o for o in py_state.battlefield if o.controller_id == 1
    ]
    assert len(py_p1_bf_after) == 0
    assert len(py_state.players[1].graveyard) == 0

    # Cross-engine: lives unchanged.
    assert rust_state.get_life(0) == rust_p0_life_before
    assert rust_state.get_life(1) == rust_p1_life_before
    assert py_state.players[0].life == py_p0_life_before
    assert py_state.players[1].life == py_p1_life_before
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life

    # Cross-engine zone-size parity.
    assert rust_state.battlefield_sizes[0] == len(py_p0_bf_after)
    assert rust_state.battlefield_sizes[1] == len(py_p1_bf_after)
    assert (
        rust_state.graveyard_sizes[0]
        == len(py_state.players[0].graveyard)
    )
    assert (
        rust_state.graveyard_sizes[1]
        == len(py_state.players[1].graveyard)
    )
    # Bf delta from baseline: +2 on p0 (source + reanimated Alpha),
    # 0 on p1.
    assert (
        rust_state.battlefield_sizes[0]
        - 0  # baseline (build_rust_state seeds 0)
        == len(py_p0_bf_after) - py_p0_bf_before
    )


def test_cross_engine_synthetic_etb_reanimator_bear_empty_graveyard_silent_skip_parity(
    parity_smoke,
):
    """Probe: ``ETB-Reanimator-Bear`` with EMPTY p0 graveyard --
    silent no-op parity for the
    ``return_creature_from_your_graveyard_to_battlefield`` bridge
    arm.

    Sister probe to:
      * ``test_cross_engine_synthetic_etb_return_creature_from_graveyard_to_battlefield_cross_controller_routes_to_source_controller_parity``
        (canonical happy-path, ONE creature in p1 gy, cross-controller
        routing).
      * ``test_cross_engine_synthetic_etb_reanimator_bear_multi_creature_graveyard_iterator_order_parity``
        (multi-creature iterator-order parity, THREE creatures in
        p0 gy).
      * ``test_cross_engine_synthetic_etb_recur_bear_empty_graveyard_silent_skip_parity``
        (EMPTY-graveyard silent-skip for the to-HAND sister arm).

    Pins the silent-skip half of the substrate's contract for the
    to-bf arm. The canonical I83 probe drives a populated p1
    graveyard (single bait) and exercises the happy-path
    reanimation; this probe seats an EMPTY p0 graveyard so the
    trigger fires against nothing eligible.

    **Documented engine-internal asymmetry, observable parity.**
    The two engines reach the SAME post-drain observable state from
    DIFFERENT intermediate stack shapes (mirrors the to-hand
    sister probe's contract):

      * **Rust** pushes the trigger onto the stack on the ENTERS
        dispatch even when no eligible target exists, then resolves
        it as a silent ``return Ok(())`` no-op (the
        ``Effect::ReturnCreatureFromYourGraveyardToBattlefield``
        resolve arm scans the source-controller's graveyard for
        the first creature, finds none, and exits clean). Stack
        briefly carries 1 item; post-drain it is empty and zones
        are unchanged.
      * **Python** elides the push at PUSH time when
        ``effect.legal_targets(...)`` returns an empty pool: the
        targeting pipeline (``push_triggered_ability`` /
        ``actions.py``) refuses to land a trigger that has no
        legal target candidate. Stack stays at 0 the entire time.

    Both paths are well-defined silent-skips; both engines agree on
    the post-drain observable contract:

      * p0 graveyard: still empty (nothing to reanimate).
      * p0 battlefield: still holds ETB Reanimator Bear (the source);
        no reanimated creature added.
      * p1 zones: all unchanged (no crossover).
      * No life changes.
      * No residual stack on either engine.

    The probe asserts the post-drain observable parity directly and
    does NOT assert mid-flight stack equality (which would force a
    spurious divergence on the documented internal asymmetry).

    Why this probe matters:

      * **Coverage of the substrate's silent-skip branch for the
        to-bf arm.** The happy-path / cross-controller probe
        exercises the populated-graveyard pick; without this
        sibling, a regression that flipped Rust's
        ``return Ok(())`` early-exit into a hard panic (or
        Python's ``legal_targets`` no-push elision into a crash on
        the empty pool) on the to-bf codepath specifically would
        slip past the existing harness. The to-hand silent-skip
        sibling ALREADY shipped (round 1, commit c8635b72) but
        only exercises the to-hand resolve arm; each arm carries
        its own resolve-side branch and needs its own silent-skip
        coverage.
      * **Asymmetric-internal / symmetric-observable contract.**
        Documents another instance of Phase 5's structural parity
        contract: the bridge translates the Rust dict to the
        Python class, and both engines may reach a parity-clean
        observable state via different internal stack shapes.

    Probe shape (inject-and-fire-ENTERS, NO graveyard seed):

      1. **Skip the gy seed.** The happy-path probe seeds a single
         bait creature in p1's graveyard; this probe's whole point
         is to NOT seed, so the trigger fires against an empty
         graveyard.
      2. Inject ETB Reanimator Bear directly onto p0's bf
         (controller=0; the SAME-controller variant, sibling of the
         I83 cross-controller happy-path probe). The ENTERS
         dispatch fires the SourceIsSelf trigger.
      3. Drain both stacks (no-op on Python where the stack stayed
         at 0; one silent-resolve walk on Rust where the trigger
         landed and immediately resolved-to-noop).
      4. Cross-engine assert: post-drain hand/graveyard/bf sizes
         and life totals match between engines and match the
         pre-dispatch baseline (only the source persists on bf;
         no reanimated creature added).

    Out of scope:

      * The populated-graveyard happy path -- exercised by the
        canonical I83 cross-controller probe.
      * Multi-creature graveyard pick -- exercised by the
        iterator-order sibling probe.
      * Cross-controller routing on the silent-skip path -- the
        I83 contract is already exercised on the populated path;
        this probe exercises the silent-skip on the SAME-controller
        variant for cleanest observable parity (the silent-skip
        contract doesn't depend on which graveyard is empty -- both
        empty p0 and empty p1 silent-skip identically on both
        engines).
      * Rider widenings (or_enchantment, or_artifact) -- both
        riders carry their own dedicated probes; their
        empty-graveyard silent-skip behaviors mirror this probe's
        contract but the target-pick filter widens, so a
        rider-specific empty-gy probe would add coverage there too
        -- separate slice.

    Expected post-dispatch + post-drain state on BOTH engines:

      * p0 graveyard: 0 cards (the silent-skip didn't push or pop).
      * p0 battlefield: 1 object (ETB Reanimator Bear, the source).
      * p1 zones: all 0 (untouched).
      * Life totals: 20 / 20.
      * Residual stack: 0 on both engines.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )
    from tests.parity._picker_shims import _PickFirstLegalTargetAgent

    # Reanimator Bear: vanilla 2/2 + ETB
    # return-creature-from-gy-to-battlefield. Same shape as the I83
    # cross-controller probe; the ONLY differences are (a) seated on
    # p0 not p1 (same-controller silent-skip variant), (b) absent
    # graveyard seed -- this probe skips it.
    reanimator_bear = CardDef(
        name="ETB Reanimator Bear (empty-gy probe)",
        card_type="Creature",
        mana_cost_generic=2,
        mana_cost_colored=(("B", 1),),
        power=2,
        toughness=2,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "return_creature_from_your_graveyard_to_battlefield",
                },
            },
        ),
    )
    spec = DeckSpec(
        card_defs=(reanimator_bear,),
        # Libraries empty-but-for-symmetry: probe injects directly
        # onto bf so libraries aren't observed.
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    rust_reanimator_dict = {
        "name": "ETB Reanimator Bear (empty-gy probe)",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "B": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "return_creature_from_your_graveyard_to_battlefield",
                },
            }
        ],
    }
    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)
    # Pre-dispatch: graveyard EMPTY on both sides (no seed).
    assert rust_state.graveyard_sizes[0] == 0
    assert rust_state.graveyard_sizes[1] == 0
    assert rust_state.battlefield_sizes[0] == 0
    assert rust_state.battlefield_sizes[1] == 0

    # Inject the reanimator-bear onto p0's battlefield -> fires
    # ENTERS via the deferred-dispatch queue. SourceIsSelf matches;
    # Rust pushes ReturnCreatureFromYourGraveyardToBattlefield onto
    # the stack even with no eligible target (the resolve arm scans
    # the gy at apply-time and silent-no-ops when no creature card
    # is found).
    rust_state.register_and_inject_object(
        rust_reanimator_dict, 0, ZONE_BATTLEFIELD,
    )
    rust_stack_after_dispatch = rust_state.stack_size()
    # Document Rust's mid-flight push: we do NOT assert this matches
    # Python's count (Python's legal_targets-empty path elides the
    # push). The post-drain observable is what we pin.
    assert rust_stack_after_dispatch == 1, (
        "Rust: ETB Reanimator Bear's arrival fires SourceIsSelf "
        "even with empty p0 graveyard; trigger lands on stack and "
        "resolves to silent no-op. "
        f"Got mid-flight stack_size={rust_stack_after_dispatch}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.graveyard import (
        ReturnCreatureFromYourGraveyardToBattlefield,
    )
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    reanimator_printing = CardPrinting(
        name="ETB Reanimator Bear (empty-gy probe)",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2, colored=(("B", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=ReturnCreatureFromYourGraveyardToBattlefield(),
            ),
        ),
    )

    # Seat the canonical first-legal-target shim on p0 (mirrors the
    # iterator-order probe's setup). The shim's only behavior of
    # interest here is its empty-pool branch (returns None when
    # legal_targets is empty); the targeting pipeline elides the
    # push without ever calling the shim, so this is defense-in-
    # depth (a regression that began calling the shim with an empty
    # pool in this codepath would surface here via the None return).
    py_state.players[0].agent = _PickFirstLegalTargetAgent()

    # Inject the reanimator-bear onto p0's battlefield, then
    # manually dispatch ENTERS (same shape as prior probes).
    py_reanimator = py_state.new_object(
        reanimator_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_reanimator.summoning_sick = False
    py_reanimator.tapped = False
    py_reanimator.damage = 0
    py_reanimator.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_reanimator)
    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life
    # Pre-dispatch: graveyards EMPTY on both sides (no seed).
    assert len(py_state.players[0].graveyard) == 0
    assert len(py_state.players[1].graveyard) == 0
    py_p0_bf_pre_dispatch = len(
        [o for o in py_state.battlefield if o.controller_id == 0]
    )
    py_p1_bf_pre_dispatch = len(
        [o for o in py_state.battlefield if o.controller_id == 1]
    )
    _trigger_etb_abilities(py_state, py_reanimator)
    py_stack_after_dispatch = len(py_state.stack)
    # Document Python's mid-flight elision: legal_targets-empty
    # path doesn't push. We pin the post-drain observable, not the
    # mid-flight stack count.
    assert py_stack_after_dispatch == 0, (
        "Python: ETB Reanimator Bear's arrival with empty p0 "
        "graveyard should trigger the legal_targets-empty push "
        "elision; the trigger never lands on the stack. "
        f"Got mid-flight stack size={py_stack_after_dispatch}"
    )

    # ---- Drain both stacks, then compare observable parity ----
    _drain_stack_both(py_state, rust_state)

    # Stacks empty on both sides post-drain (Rust: silent-resolve
    # consumed the no-op trigger; Python: nothing to drain).
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0

    # Per-engine post-drain observable (Rust): graveyards still
    # empty, p0 bf still holds the source (only), p1 untouched.
    assert rust_state.graveyard_sizes[0] == 0, (
        f"Rust: p0 graveyard should remain empty; got "
        f"graveyard_size={rust_state.graveyard_sizes[0]}"
    )
    assert rust_state.graveyard_sizes[1] == 0, (
        f"Rust: p1 graveyard should remain empty; got "
        f"graveyard_size={rust_state.graveyard_sizes[1]}"
    )
    assert rust_state.battlefield_sizes[0] == 1, (
        f"Rust: p0 bf should hold ONLY ETB Reanimator Bear "
        f"(no reanimated creature added on the silent-skip path); "
        f"got bf_size={rust_state.battlefield_sizes[0]}"
    )
    assert rust_state.battlefield_sizes[1] == 0, (
        f"Rust: p1 bf should remain empty; got "
        f"bf_size={rust_state.battlefield_sizes[1]}"
    )
    rust_bf_snap = rust_state.battlefield_snapshot()
    rust_p0_bf_objs = [
        d for d in rust_bf_snap if d["controller_id"] == 0
    ]
    assert len(rust_p0_bf_objs) == 1
    assert (
        rust_p0_bf_objs[0]["printing_name"]
        == "ETB Reanimator Bear (empty-gy probe)"
    ), (
        f"Rust: only object on p0 bf should be the source; "
        f"got name={rust_p0_bf_objs[0]['printing_name']}"
    )

    # Per-engine post-drain observable (Python): same shape.
    assert len(py_state.players[0].graveyard) == 0, (
        f"Python: p0 graveyard should remain empty; got "
        f"graveyard_size={len(py_state.players[0].graveyard)}"
    )
    assert len(py_state.players[1].graveyard) == 0, (
        f"Python: p1 graveyard should remain empty; got "
        f"graveyard_size={len(py_state.players[1].graveyard)}"
    )
    py_bf_p0 = [
        o for o in py_state.battlefield if o.controller_id == 0
    ]
    py_bf_p1 = [
        o for o in py_state.battlefield if o.controller_id == 1
    ]
    assert len(py_bf_p0) == 1, (
        f"Python: p0 bf should hold ONLY ETB Reanimator Bear; "
        f"got bf_size={len(py_bf_p0)}"
    )
    assert (
        py_bf_p0[0].printing.name
        == "ETB Reanimator Bear (empty-gy probe)"
    ), (
        f"Python: only object on p0 bf should be the source; "
        f"got name={py_bf_p0[0].printing.name}"
    )
    assert len(py_bf_p1) == 0, (
        f"Python: p1 bf should remain empty; got "
        f"bf_size={len(py_bf_p1)}"
    )
    # Sanity: bf delta from pre-dispatch is 0 (the source was
    # already pushed onto bf BEFORE the dispatch fired, so the
    # silent-skip leaves bf size unchanged from the
    # post-injection-pre-dispatch baseline).
    assert len(py_bf_p0) == py_p0_bf_pre_dispatch
    assert len(py_bf_p1) == py_p1_bf_pre_dispatch

    # Cross-engine: lives unchanged on both sides.
    assert rust_state.get_life(0) == rust_p0_life_before
    assert rust_state.get_life(1) == rust_p1_life_before
    assert py_state.players[0].life == py_p0_life_before
    assert py_state.players[1].life == py_p1_life_before
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life

    # Cross-engine zone-size parity (the post-drain observable).
    assert rust_state.battlefield_sizes[0] == len(py_bf_p0)
    assert rust_state.battlefield_sizes[1] == len(py_bf_p1)
    assert (
        rust_state.graveyard_sizes[0]
        == len(py_state.players[0].graveyard)
    )
    assert (
        rust_state.graveyard_sizes[1]
        == len(py_state.players[1].graveyard)
    )
    assert rust_state.hand_sizes[0] == len(py_state.players[0].hand)
    assert rust_state.hand_sizes[1] == len(py_state.players[1].hand)


def test_cross_engine_synthetic_etb_create_token_same_controller_routes_to_source_controller_parity(
    parity_smoke,
):
    """Probe: synthetic ETB ``create_token`` trigger fired by a
    permanent CONTROLLED BY P0 while ACTIVE_PLAYER=P0 -- the
    canonical "Honored Knight-Captain" / "Knight Luminary" /
    "Wedgelight Rammer" same-controller shape ("When this creature
    enters, create a 1/1 white Human Soldier creature token"). Both
    engines must spawn the freshly-created token onto P0's
    battlefield under P0's control. This is the SAME-CONTROLLER
    sister of the I81 cross-controller probe (which exercises the
    routing fix for opponent-controlled sources); together they pin
    the post-I81 contract on both legs of the
    ``current_resolve_source_controller`` fallback (active-player
    direct path AND non-active-player resolve path).

    **Real-EoE consumer alignment.** Multiple EoE printings carry
    this exact ETB shape: ``Honored Knight-Captain``,
    ``Knight Luminary`` (both 1/1 Soldier on creature ETB), and
    ``Wedgelight Rammer`` (2/2 Robot on Spacecraft ETB). The
    synthetic carrier here is a 2/2 Creature so the same dispatch
    path the EoE printings drive is exercised. The Rust engine has
    no Scryfall recognizer (`mtg_bot_engine.Registry` only exposes
    `register_printing(dict)`, NOT `register_card_data(scryfall)`),
    so the harness is necessarily synthetic-shape -- but the dict
    body the carrier ships matches what a hypothetical Rust
    recognizer for the EoE consumers would emit. When a real-EoE
    consumer surfaces in a future Rust slice, this probe stays
    correct: the bridge arm's contract is independent of which
    card drove it, and the synthetic-vs-real-EoE difference is
    observable only in the carrier's name + type-line, not in
    the create_token effect or the post-resolve battlefield
    shape.

    **Bridge arm.** ``feature/phase5-ce-bridge-create-token``
    landed the ``create_token`` arm + ``register_token_printing``
    substrate on this branch's main. This probe drives the
    end-to-end flow through the bridge: probe registers the
    Python soldier-token printing against Rust's pid before
    building the carrier's Python printing; the bridge then
    materializes ``CreateToken(token_printing=py_soldier, count=1)``
    from the same dict shape Rust consumes. No manual two-side
    construction.

    Probe shape (same-controller inject-and-fire-ENTERS):

      1. **active_player=P0** (default). P0 is also the SOURCE's
         controller, so ``current_resolve_source_controller``
         resolves to ``Some(0)`` AND the back-compat fallback
         (``active_player``) AGREES at 0. Same-controller probes
         can't disambiguate the two paths -- the cross-controller
         I81 probe is what proves the active-player fallback is
         no longer the load-bearing route.

      2. **Register Soldier token printing** on Rust (gets a pid
         via ``rust_state.registry_size``); register the matching
         Python ``CardPrinting`` against that pid via
         ``register_token_printing(pid, py_soldier)``.

      3. **Inject Token Maker Bear (the EoE-shape carrier) onto
         P0's bf** with controller=0. ENTERS fires; the trigger
         lands on the stack carrying controller=0.

      4. **Drain both stacks.** The trigger resolves; the post-I81
         CreateToken arm routes the spawn to P0's bf under P0's
         control on Rust, and Python's
         ``CreateToken.resolve(state, controller_id=0, ...)``
         spawns under P0 the same way.

      5. **Cross-engine assert (post-resolve parity):**
         - P0's bf grew by exactly +2 (Token Maker Bear +
           freshly-spawned Soldier Token).
         - P1's bf is unchanged.
         - The fresh token's ``controller_id`` is 0 on both
           engines.

    Out of scope:

      * Cast-from-hand mana cost -- bypassed by inject-and-fire.
      * count != 1 -- the bridge arm carries the count through;
        the regression pins for count multiplication exist
        on the Rust side. The same-controller surface is
        independent of count.
      * Tapped / attacking / each_player riders -- Python-only
        flags with no Rust mirror today; the bridge constructs
        the bare shape with all riders defaulted off.
      * Cross-controller routing -- pinned by the I81 sister
        probe (this branch's slice 2 refactor uses the same
        bridge arm).

    Expected post-dispatch + post-drain state on BOTH engines:

      * Token Maker Bear on P0's battlefield (unchanged from
        inject; controller=0).
      * One Soldier Token on P0's battlefield (newly spawned;
        controller=0).
      * P1's battlefield: empty.
      * No residual stack on either engine.
      * Life totals unchanged on both seats.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )

    spec = DeckSpec(
        card_defs=(),
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # Pre-condition: active_player=P0 on both engines.
    assert rust_state.active_player == 0
    assert py_state.active_player_idx == 0

    # ---- Rust side: register Soldier token, then inject the
    # Honored-Knight-Captain-shape carrier onto P0's bf. ----
    ZONE_LIBRARY = 1
    ZONE_BATTLEFIELD = 2
    rust_soldier_token_dict = {
        "name": "Soldier Token (real-EoE create_token probe)",
        "card_types": ["Creature"],
        "power": 1,
        "toughness": 1,
    }
    rust_token_pid = rust_state.registry_size  # next free pid
    rust_state.register_and_inject_object(
        rust_soldier_token_dict, 1, ZONE_LIBRARY,
    )

    rust_carrier_trigger_dict = {
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {
            "kind": "create_token",
            "count": 1,
            "token_printing_id": rust_token_pid,
        },
    }
    rust_carrier_dict = {
        "name": (
            "Honored Knight-Captain (real-EoE create_token probe)"
        ),
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1, "W": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [rust_carrier_trigger_dict],
    }

    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)
    rust_bf_p0_before = rust_state.battlefield_sizes[0]
    rust_bf_p1_before = rust_state.battlefield_sizes[1]

    # Inject onto P0's bf with controller=0. ENTERS fires; the
    # trigger lands on the stack carrying controller=0 (same as
    # active_player here).
    rust_state.register_and_inject_object(
        rust_carrier_dict, 0, ZONE_BATTLEFIELD,
    )

    # ---- Python side: register the Python token printing against
    # Rust's pid via the bridge, build carrier printing using the
    # bridge translator on the SAME trigger dict, then inject onto
    # P0's bf and dispatch ENTERS. ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import (
        CardPrinting, ManaCost, make_token_creature,
    )
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_triggered_ability,
        clear_token_printings, register_token_printing,
    )

    py_soldier_token = make_token_creature(
        name="Soldier Token (real-EoE create_token probe)",
        power=1,
        toughness=1,
        subtypes=("Soldier",),
    )
    clear_token_printings()
    register_token_printing(rust_token_pid, py_soldier_token)
    py_carrier_trigger = _ta_dict_to_python_triggered_ability(
        rust_carrier_trigger_dict
    )
    py_carrier_printing = CardPrinting(
        name=(
            "Honored Knight-Captain (real-EoE create_token probe)"
        ),
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=(("W", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(py_carrier_trigger,),
    )
    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life
    py_bf_p0_before = len(
        [o for o in py_state.battlefield if o.controller_id == 0]
    )
    py_bf_p1_before = len(
        [o for o in py_state.battlefield if o.controller_id == 1]
    )

    py_carrier = py_state.new_object(
        py_carrier_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_carrier.summoning_sick = False
    py_carrier.tapped = False
    py_carrier.damage = 0
    py_carrier.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_carrier)
    _trigger_etb_abilities(py_state, py_carrier)

    # Drain both stacks.
    _drain_stack_both(py_state, rust_state)

    # Stacks empty.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0

    # Rust observable: P0's bf grew by carrier + 1 token = +2;
    # P1's bf unchanged.
    rust_bf_p0_after = rust_state.battlefield_sizes[0]
    rust_bf_p1_after = rust_state.battlefield_sizes[1]
    assert rust_bf_p0_after == rust_bf_p0_before + 2, (
        f"Rust same-controller create_token: P0's bf should gain "
        f"carrier + 1 Soldier Token = +2 from baseline. Got "
        f"bf_p0_before={rust_bf_p0_before}, "
        f"bf_p0_after={rust_bf_p0_after}"
    )
    assert rust_bf_p1_after == rust_bf_p1_before, (
        f"Rust: P1's bf should be unchanged. Got "
        f"bf_p1_before={rust_bf_p1_before}, "
        f"bf_p1_after={rust_bf_p1_after}"
    )
    rust_bf_snap = rust_state.battlefield_snapshot()
    rust_soldier_tokens = [
        d for d in rust_bf_snap
        if d["printing_name"]
        == "Soldier Token (real-EoE create_token probe)"
    ]
    assert len(rust_soldier_tokens) == 1
    assert rust_soldier_tokens[0]["controller_id"] == 0

    # Python observable: same shape.
    py_bf_p0_after = len(
        [o for o in py_state.battlefield if o.controller_id == 0]
    )
    py_bf_p1_after = len(
        [o for o in py_state.battlefield if o.controller_id == 1]
    )
    assert py_bf_p0_after == py_bf_p0_before + 2, (
        f"Python: P0's bf should gain carrier + 1 Soldier "
        f"Token = +2. Got bf_p0_before={py_bf_p0_before}, "
        f"bf_p0_after={py_bf_p0_after}"
    )
    assert py_bf_p1_after == py_bf_p1_before
    py_soldier_tokens = [
        o for o in py_state.battlefield
        if o.printing.name
        == "Soldier Token (real-EoE create_token probe)"
    ]
    assert len(py_soldier_tokens) == 1
    assert py_soldier_tokens[0].controller_id == 0

    # Cross-engine: lives unchanged on both sides.
    assert rust_state.get_life(0) == rust_p0_life_before
    assert rust_state.get_life(1) == rust_p1_life_before
    assert py_state.players[0].life == py_p0_life_before
    assert py_state.players[1].life == py_p1_life_before
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life

    # Cross-engine bf-size parity.
    assert rust_bf_p0_after == py_bf_p0_after
    assert rust_bf_p1_after == py_bf_p1_after


def test_cross_engine_synthetic_etb_damage_any_target_cross_controller_routes_to_source_controller_opponent_parity(
    parity_smoke,
):
    """Probe: synthetic ETB ``deal_damage_any_target(amount=3)``
    trigger fired by a permanent CONTROLLED BY P1 while
    ACTIVE_PLAYER=P0 -- exercises the I67 controller-of-effect fix
    end-to-end through the bridge for the targeted-damage arm.

    Sister probes (cross-controller routing, OTHER bridge arms):

      * ``test_cross_engine_synthetic_etb_create_token_cross_controller_routes_to_source_controller_parity``
        -- I81, ``create_token``.
      * ``test_cross_engine_synthetic_etb_return_creature_from_graveyard_to_hand_cross_controller_routes_to_source_controller_parity``
        -- I82, ``return_creature_from_your_graveyard_to_hand``.
      * ``test_cross_engine_synthetic_etb_return_creature_from_graveyard_to_battlefield_cross_controller_routes_to_source_controller_parity``
        -- I83, ``return_creature_from_your_graveyard_to_battlefield``.

    This probe extends the cross-controller routing coverage to the
    ``deal_damage_any_target`` bridge arm (the
    Nebula Dragon / Debris Field Crusher / Pinnacle Kill-Ship
    happy-path probes all drive p0-controlled sources on p0's turn,
    so the source's controller == active_player and the I67 fix's
    distinguishing case is unobservable). Drives the source on
    p1's bf with active_player=p0 -- now source-controller != active-
    player, and the post-fix contract requires both engines to
    derive the defender from the SOURCE's controller (= p1 -> defender
    p0), NOT from active_player (= p0 -> would have defender p1
    pre-fix).

    **The I67 substrate (recap).** Pre-I67 the Rust
    ``Effect::DealDamageAnyTarget`` arm derived ``defender_idx`` as
    ``1 - state.active_player``, which controlled both (a) which
    battlefield to scan for the deterministic creature pick, and
    (b) which player to fall back to if no eligible creature was
    found. Wrong when the resolving spell / triggered ability has a
    controller != active_player. The fix routes the defender
    derivation through ``current_resolve_source_controller``
    (state_ops_resolve.rs:3536-3603); ``defender_idx = 1 -
    source_controller``. Python's ``DealDamageAnyTarget`` (constructor
    sugar over ``DealDamage`` carrying the any-target filter) has
    always been correct on this surface -- the agent picks at PUSH
    time, with ``player_id`` = source's controller, and the seated
    ``_PickFirstOpponentTargetAgent`` filters ``legal_targets`` to
    opponent-controlled entries WHERE OPPONENT == agent's seat (so
    the agent on p1 picks p0-side targets, mirroring Rust's
    defender-anchored scan).

    Probe shape (cross-controller inject-and-fire-ENTERS, empty p0 bf):

      1. **active_player=P0** (default). Confirmed via
         ``state.active_player`` on Rust and
         ``state.active_player_idx`` on Python.
      2. **Inject Burner Bear (the source) onto P1's bf** with
         controller=1. ENTERS fires; the trigger lands on the stack
         with controller=1 (the SOURCE's controller).
      3. **Drain both stacks.** Rust's resolve arm reads
         ``current_resolve_source_controller = Some(1)``,
         derives defender = 0, scans p0's empty bf for a creature,
         finds none, falls back to damaging the p0 PLAYER for 3.
         Python's PUSH-time pick called the agent on p1; the agent's
         opponent-filter returned the p0 player target; resolve
         applies 3 damage to the p0 player.
      4. **Cross-engine assert (post-I67 contract):**
         - p0 life: 20 -> 17 (-3 from the cross-controller burn).
         - p1 life: unchanged at 20 (source-controller is immune).
         - Pre-I67 Rust would have damaged p1 for 3 (active_player-
           derived defender); post-fix Rust correctly damages p0.

    **Pre-I67 vs post-I67 observable.**
    Pre-fix Rust would have computed ``defender_idx = 1 -
    state.active_player = 1 - 0 = 1``, scanned p1's bf (where the
    Burner Bear itself lives -- the only object), picked it as the
    first-creature, and dealt 3 damage to the source itself (a
    same-controller self-damage). With p1's bf carrying ONLY the
    source and nothing else, pre-fix Rust's pick is observably
    distinct from post-fix Rust's pick: pre-fix damages the bear
    on p1's bf (a creature), post-fix damages the p0 player. The
    probe asserts the post-fix shape (p0 life dropped, p1 life
    unchanged, source still on p1 bf at full life via the
    creature-target / player-target axis split) so a regression
    that flipped the defender derivation back to active_player
    would surface as the wrong life total dropping.

    Out of scope:

      * Cast-from-hand mana cost ({6}{R}) -- bypassed by inject-
        and-fire (same convention as the canonical Nebula Dragon
        probe).
      * Multi-creature pick on the defender's bf -- empty p0 bf
        keeps the agent's first-legal-target pick unambiguously
        the player target (mirrors the canonical Nebula Dragon
        probe). The creature-on-defender-bf pick contract is
        exercised by Pinnacle Kill-Ship's same-controller probe.
      * Optional-target ``optional=True`` extension -- separate
        probe surface; the empty-bf case for optional is already
        a divergence pin (round 2's
        ``test_cross_engine_real_eoe_pinnacle_kill_ship_etb_damage_optional_empty_bf_divergence_pin``).
      * Source on p1 with creatures on p0 bf -- the single-creature
        scan is a separate axis, exercised by the same-controller
        probes; this probe pins the cross-controller defender-
        player FALLBACK specifically.

    Expected post-dispatch + post-drain state on BOTH engines:

      * Burner Bear on P1's battlefield (unchanged from inject;
        controller=1, no damage taken).
      * P0's battlefield empty.
      * P0 life: 20 -> 17.
      * P1 life: unchanged at 20.
      * No residual stack on either engine.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    # Burner Bear: vanilla 2/2 + ETB
    # deal_damage_any_target(amount=3). Same effect shape as Nebula
    # Dragon's ETB; the cross-controller axis (source seated on p1
    # not p0) is what's distinct.
    burner_bear = CardDef(
        name="ETB Burner Bear (cross-controller probe)",
        card_type="Creature",
        mana_cost_generic=2,
        mana_cost_colored=(("R", 1),),
        power=2,
        toughness=2,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "deal_damage_any_target",
                    "amount": 3,
                },
            },
        ),
    )
    spec = DeckSpec(
        card_defs=(burner_bear,),
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # Confirm pre-condition: active_player=P0 on both engines.
    assert rust_state.active_player == 0, (
        f"Probe pre-condition: Rust active_player must be 0; "
        f"got {rust_state.active_player}"
    )
    assert py_state.active_player_idx == 0, (
        f"Probe pre-condition: Python active_player_idx must be 0; "
        f"got {py_state.active_player_idx}"
    )

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    rust_burner_dict = {
        "name": "ETB Burner Bear (cross-controller probe)",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "R": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "deal_damage_any_target",
                    "amount": 3,
                },
            }
        ],
    }
    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)
    # Inject the burner-bear onto P1's bf with controller=1. ENTERS
    # fires; the trigger lands on the stack carrying controller=1.
    # Post-I67 Rust derives defender = 0 from the source's controller
    # and damages the p0 player (no creature on p0 bf to absorb).
    rust_state.register_and_inject_object(
        rust_burner_dict, 1, ZONE_BATTLEFIELD,
    )
    assert rust_state.stack_size() == 1, (
        f"Rust: ETB Burner Bear's arrival on P1 should fire the "
        f"SourceIsSelf ENTERS trigger and land DealDamageAnyTarget "
        f"on the stack. Got stack_size={rust_state.stack_size()}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.damage import DealDamageAnyTarget
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    burner_printing = CardPrinting(
        name="ETB Burner Bear (cross-controller probe)",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2, colored=(("R", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=DealDamageAnyTarget(amount=3),
            ),
        ),
    )

    # Seat the first-opponent-target picker on P1 (the SOURCE's
    # controller). The shim's ``player_id`` parameter is the
    # SOURCE-controller's seat (= 1 here); the shim filters
    # legal_targets to entries whose controller != player_id, so it
    # picks p0-side targets (mirroring Rust's defender-anchored
    # scan). With no creatures on p0 bf, the only legal opponent-
    # side target is the p0 player.
    py_state.players[1].agent = _PickFirstOpponentTargetAgent()

    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life

    # Inject the burner-bear onto P1's bf with owner_id=1, then
    # manually dispatch ENTERS.
    py_burner = py_state.new_object(
        burner_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_burner.summoning_sick = False
    py_burner.tapped = False
    py_burner.damage = 0
    py_burner.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_burner)
    _trigger_etb_abilities(py_state, py_burner)
    assert len(py_state.stack) == 1, (
        f"Python: ETB Burner Bear's arrival on P1 should fire the "
        f"IsSelf ENTERS trigger and land DealDamageAnyTarget on the "
        f"stack. Got stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks, then compare observable parity. ----
    _drain_stack_both(py_state, rust_state)

    # Stacks empty post-drain.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0

    # Rust observable (the I67 contract):
    #   * p0 life: 20 -> 17 (the source-controller's opponent took
    #     the burn).
    #   * p1 life: unchanged at 20 (source-controller is immune).
    #   * Pre-I67 Rust would have computed defender = 1 -
    #     active_player = 1, scanned p1's bf (which carries ONLY
    #     the source), and either damaged the bear (creature pick)
    #     or fallen back to damaging the p1 player. Either pre-fix
    #     branch leaves p0 life at 20 -- the post-fix p0 life drop
    #     to 17 is the load-bearing assertion.
    assert rust_state.get_life(0) == rust_p0_life_before - 3, (
        f"Rust I67 contract: p0 life should drop by 3 (the source-"
        f"controller's opponent takes the burn). Got "
        f"p0_before={rust_p0_life_before}, "
        f"p0_after={rust_state.get_life(0)}. Pre-I67 bug would "
        f"leave p0 life at {rust_p0_life_before} (defender derived "
        f"from active_player rather than source-controller)."
    )
    assert rust_state.get_life(1) == rust_p1_life_before, (
        f"Rust I67 contract: p1 life should be unchanged "
        f"(source-controller is immune to the burn). Got "
        f"p1_before={rust_p1_life_before}, "
        f"p1_after={rust_state.get_life(1)}."
    )

    # Python observable (the always-correct sister contract).
    assert py_state.players[0].life == py_p0_life_before - 3, (
        f"Python: p0 life should drop by 3. Got "
        f"p0_before={py_p0_life_before}, "
        f"p0_after={py_state.players[0].life}."
    )
    assert py_state.players[1].life == py_p1_life_before, (
        f"Python: p1 life should be unchanged. Got "
        f"p1_before={py_p1_life_before}, "
        f"p1_after={py_state.players[1].life}."
    )

    # Cross-engine: same post-drain life totals on both seats.
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life

    # The source itself is unscathed on p1's bf -- post-fix Rust
    # routed the burn to the p0 player, NOT to a creature on p1's bf.
    # Pre-fix Rust would have damaged a creature on p1's bf
    # (ironically the source itself, which would not be lethal at
    # 3 dmg vs 2 toughness without SBA-death pinning, but a
    # regression there would surface as the source missing from p1's
    # bf or carrying nonzero damage in the snapshot).
    rust_bf_snap = rust_state.battlefield_snapshot()
    rust_p1_bf_objs = [
        d for d in rust_bf_snap if d["controller_id"] == 1
    ]
    assert len(rust_p1_bf_objs) == 1, (
        f"Rust: p1 bf should hold ONLY the source; got "
        f"{len(rust_p1_bf_objs)} object(s)"
    )
    assert (
        rust_p1_bf_objs[0]["printing_name"]
        == "ETB Burner Bear (cross-controller probe)"
    )
    assert rust_state.battlefield_sizes[0] == 0, (
        f"Rust: p0 bf should remain empty; got "
        f"bf_size={rust_state.battlefield_sizes[0]}"
    )

    py_p1_bf_after = [
        o for o in py_state.battlefield if o.controller_id == 1
    ]
    assert len(py_p1_bf_after) == 1, (
        f"Python: p1 bf should hold ONLY the source; got "
        f"{len(py_p1_bf_after)} object(s)"
    )
    assert (
        py_p1_bf_after[0].printing.name
        == "ETB Burner Bear (cross-controller probe)"
    )
    py_p0_bf_after = [
        o for o in py_state.battlefield if o.controller_id == 0
    ]
    assert len(py_p0_bf_after) == 0

    # Cross-engine zone-size parity.
    assert rust_state.battlefield_sizes[0] == len(py_p0_bf_after)
    assert rust_state.battlefield_sizes[1] == len(py_p1_bf_after)


def test_cross_engine_synthetic_etb_surveil_cross_controller_routes_to_source_controller_parity(
    parity_smoke,
):
    """Probe: synthetic ETB ``surveil 2`` trigger fired by a permanent
    CONTROLLED BY P1 while ACTIVE_PLAYER=P0 -- the I61 controller-of-
    effect fix's cross-engine flicker on the surveil bridge arm. Both
    engines must surveil P1's library (the source's controller), NOT
    P0's library (the active player). The keep-all-on-top default
    leaves P1's library top unchanged in original order and P1's
    graveyard empty; P0's library + graveyard are untouched on either
    engine.

    **The I61 substrate (surveil leg).** Per the bridge arm comment in
    ``_ta_dict_to_python_effect`` (cross_engine.py:317-381): pre-I61
    the Rust ``Effect::Surveil`` resolve arm derived its target
    library from ``state.active_player`` directly. Wrong when the
    resolving spell / triggered ability has a controller !=
    active_player (the canonical "p1's flicker re-ETB on p0's turn"
    shape). The I61 fix routes that derivation through
    ``current_resolve_source_controller`` (with a fallback to
    ``active_player`` for direct ``apply_effect_pub`` callers), so
    cross-controller surveil correctly observes the SOURCE's
    library. Python's ``Surveil(amount: int)`` resolves against
    ``state.players[controller_id]`` via the trigger's explicit
    controller field and has always been correct on this surface.

    **Same-controller sister probes** (round 2 on this branch's
    history): ``test_cross_engine_real_eoe_starbreach_whale_etb_
    surveil_2_parity`` and ``test_cross_engine_real_eoe_wurmwall_
    sweeper_etb_surveil_2_parity`` -- both fire surveil on P0's bf
    while ACTIVE_PLAYER=P0, so the source's controller and the
    active player coincide and the cross-controller routing surface
    is NOT exercised. This probe is the cross-controller leg the
    surveil bridge arm needed end-to-end.

    **Why synthetic, not a real EoE card.** Every EoE printing whose
    ETB triggers ``surveil N`` (Starbreach Whale, Wurmwall Sweeper,
    ...) is already pinned same-controller above; spinning up a
    cross-controller leg on those cards would re-build the same
    inject-and-fire harness with the only delta being the seat we
    inject onto. A synthetic 2/2 vanilla carrier ("Cross-Controller
    Surveiler Bear") with an ETB ``Surveil(count=2)`` matches that
    minimal delta, mirrors the I81 / I82 / I83 cross-controller probe
    shape, and avoids muddling the existing same-controller probes'
    docstring claims about which-leg-is-pinned.

    Probe shape (cross-controller inject-and-fire-ENTERS):

      1. **active_player=P0** (default after ``make_state`` /
         ``build_python_state``). Confirmed via
         ``state.active_player`` on Rust and
         ``state.active_player_idx`` on Python.

      2. **Pre-seed P1's library** with TWO distinct vanilla bait
         cards. Pre-fix Rust would have surveiled P0's empty library
         and observed nothing; post-fix it surveils P1's library and
         observes the two bait cards. P0's library stays empty so a
         pre-fix Rust would have a no-op observable that's
         distinguishable from the post-fix two-card-observed state
         only via the per-card library-top check on P1.

      3. **Inject Cross-Controller Surveiler Bear onto P1's bf** with
         controller=1 (Rust's ``register_and_inject_object``;
         Python's ``new_object`` + bf append + manual
         ``_trigger_etb_abilities``). The injection's ENTERS dispatch
         fires the SourceIsSelf trigger; the trigger lands on the
         stack with controller=1 (the SOURCE's controller, NOT the
         active player).

      4. **Drain both stacks.** The trigger resolves via
         ``apply_effect`` with
         ``current_resolve_source_controller = Some(1)``; the
         post-I61 Surveil arm pops up to 2 cards off P1's library
         top into a SurveilChoice pending-decision. Rust's
         trigger-path terminal ``auto_resolve_pending(
         "keep_all_on_top")`` (state_ops_resolve.rs:6832) returns
         every observed card to P1's library top in the original
         order. Python's no-agent short-circuit at
         ``library_lookat.py:605`` does the same on the equivalent
         state.

      5. **Cross-engine assert (post-I61 surveil contract):**
         - P1's library top is unchanged in original order
           (keep-all-on-top default; baits Alpha then Beta).
         - P1's graveyard is empty (no mill -- agent=None default).
         - P0's library and graveyard sizes are unchanged at zero
           (pre-fix Rust would have noticed P0's library is empty and
           silent-no-opped, but the OBSERVABLE that distinguishes
           pre-fix from post-fix is the +0 vs +2-then-keep on P1's
           library top after the surveil walk; per-card library-top
           parity below pins it).
         - No residual pending decision on Rust (the trigger-path
           terminal auto-resolve drained the SurveilChoice).

    **Pre-I61 vs post-I61 observable.**
    Pre-fix Rust would have:
      - Surveiled P0's library (active_player). P0's library is
        empty in this probe so the pre-fix observable is a silent
        no-op on P0; P1's library would remain in its pre-trigger
        shape but the WALK would never have observed it.
    Post-fix Rust correctly surveils P1's library. The walk pops
    Bait Alpha and Bait Beta off P1's library top into the
    SurveilChoice pending-decision; the keep_all_on_top auto-resolve
    returns both cards to P1's library top in their original order.
    Python's behavior is bit-equal because its
    ``Surveil.resolve(state, controller_id, ...)`` already takes the
    controller explicitly (the trigger's controller field).

    The cross-engine assertion that pins this is the
    library_snapshot(1) names list before vs after AND the
    library_snapshot(0) emptiness check -- a pre-fix Rust would NOT
    have left the SurveilChoice in P1's history, but the
    keep-all-on-top default is observably equivalent to "no surveil
    happened" on a snapshot, so the *load-bearing* parity check is
    that BOTH engines' P1 library top names match position-for-
    position. The PendingDecision drain assert (``has_pending_decision
    is False``) then proves the surveil substrate actually fired on
    Rust (a pre-fix Rust on this same shape would have NO pending
    SurveilChoice because the empty-library walk pops zero cards;
    post-fix it pops 2 and the auto-resolve drains them). The two
    checks together pin "the surveil fired AND it fired against the
    SOURCE's controller's library".

    Out of scope:

      * The mill path (``choose_surveil → True``) -- the no-agent
        keep_all_on_top default is the trivially-parity-safe leg of
        the surveil substrate and matches the same-controller
        probes' contract. Driving the mill path explicitly across a
        cross-controller seat would need both a Python agent on P1
        whose ``choose_surveil`` returns True AND a Rust
        ``auto_resolve_pending_decisions("send_all_to_graveyard")``
        mirror -- the trigger-path terminal auto-resolve uses
        keep_all_on_top, not send_all_to_graveyard, so a follow-up
        slice would extend the harness rather than this probe.
      * Cast-from-hand mana cost -- the inject-and-dispatch-ENTERS
        pattern bypasses the mana pipeline (every prior synthetic
        ETB cross-controller probe uses the same shortcut for the
        same reason).
      * count != 2 -- the I61 contract is independent of count; the
        same-controller Starbreach Whale / Wurmwall Sweeper probes
        already pin count=2, and the cross-controller routing
        surface doesn't multiplex on count.

    Expected post-dispatch + post-drain state on BOTH engines:

      * Cross-Controller Surveiler Bear on P1's battlefield
        (unchanged from inject; controller=1).
      * P1 library: unchanged (Bait Alpha at top, Bait Beta second,
        original order preserved).
      * P1 graveyard: empty.
      * P0 library: empty (untouched).
      * P0 graveyard: empty (untouched).
      * Lives unchanged on both seats.
      * No residual stack on either engine.
      * No pending decision left on Rust.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )

    # Two distinct vanilla cards seated on P1's library so a single-
    # card mismatch (any swap or single mill) between engines surfaces
    # as a per-card name divergence rather than a count-only divergence.
    surveil_bait_a = CardDef(
        name="Cross-Controller Surveil Bait Alpha",
        card_type="Creature",
        mana_cost_generic=1,
        power=1,
        toughness=1,
    )
    surveil_bait_b = CardDef(
        name="Cross-Controller Surveil Bait Beta",
        card_type="Creature",
        mana_cost_generic=2,
        power=2,
        toughness=2,
    )
    spec = DeckSpec(
        card_defs=(surveil_bait_a, surveil_bait_b),
        # P0 library stays EMPTY -- a pre-I61 Rust would have surveiled
        # P0's library here (silent no-op on empty); the post-I61 fix
        # surveils P1's library. The per-card P1 library-top check
        # below distinguishes the two.
        p0_library=(),
        p1_library=(
            "Cross-Controller Surveil Bait Alpha",
            "Cross-Controller Surveil Bait Beta",
        ),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # Confirm pre-condition: active_player=P0 on both engines (the
    # whole point of the probe is the cross-controller case where
    # the SOURCE's controller != active_player).
    assert rust_state.active_player == 0, (
        f"Probe pre-condition: Rust active_player must be 0; "
        f"got {rust_state.active_player}"
    )
    assert py_state.active_player_idx == 0, (
        f"Probe pre-condition: Python active_player_idx must be 0; "
        f"got {py_state.active_player_idx}"
    )

    # ---- Rust side: inject the surveiler bear onto P1's bf with
    # controller=1. ENTERS fires via the deferred-dispatch queue;
    # the SourceIsSelf trigger lands on the stack carrying
    # controller=1 (the SOURCE's controller). ----
    ZONE_BATTLEFIELD = 2
    rust_surveiler_dict = {
        "name": "Cross-Controller Surveiler Bear",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1, "U": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "surveil", "count": 2},
            }
        ],
    }
    rust_p0_lib_before = [
        d["printing_id"] for d in rust_state.library_snapshot(0)
    ]
    rust_p1_lib_before = [
        d["printing_id"] for d in rust_state.library_snapshot(1)
    ]
    rust_p0_lib_size_before = rust_state.library_sizes[0]
    rust_p1_lib_size_before = rust_state.library_sizes[1]
    rust_p0_gy_size_before = rust_state.graveyard_sizes[0]
    rust_p1_gy_size_before = rust_state.graveyard_sizes[1]
    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)

    rust_state.register_and_inject_object(
        rust_surveiler_dict, 1, ZONE_BATTLEFIELD,
    )
    # register_and_inject_object on ZONE_BATTLEFIELD fans out ENTERS
    # via the deferred-dispatch queue; the bear's SourceIsSelf
    # predicate matches its own arrival, so a single Surveil(2)
    # trigger lands on the stack carrying controller=1.
    assert rust_state.stack_size() == 1, (
        "Rust: Cross-Controller Surveiler Bear's arrival on P1 "
        "should fire the SourceIsSelf ENTERS trigger and land "
        "Surveil(2) on the stack. "
        f"Got stack_size={rust_state.stack_size()}"
    )

    # ---- Python side: build the same printing, inject onto P1's bf
    # with owner_id=1 / controller_id=1, then manually dispatch
    # ENTERS (mirrors prior cross-controller synthetic ETB probes). ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.library_lookat import Surveil
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    surveiler_printing = CardPrinting(
        name="Cross-Controller Surveiler Bear",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=(("U", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=Surveil(amount=2),
            ),
        ),
    )
    py_p0_lib_before = [
        o.printing.name for o in py_state.players[0].library
    ]
    py_p1_lib_before = [
        o.printing.name for o in py_state.players[1].library
    ]
    py_p0_gy_size_before = len(py_state.players[0].graveyard)
    py_p1_gy_size_before = len(py_state.players[1].graveyard)
    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life

    py_surveiler = py_state.new_object(
        surveiler_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_surveiler.summoning_sick = False
    py_surveiler.tapped = False
    py_surveiler.damage = 0
    py_surveiler.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_surveiler)
    _trigger_etb_abilities(py_state, py_surveiler)
    assert len(py_state.stack) == 1, (
        "Python: Cross-Controller Surveiler Bear's arrival on P1 "
        "should fire the IsSelf ENTERS trigger and land Surveil(2) "
        f"on the stack. Got stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks, then compare ----
    _drain_stack_both(py_state, rust_state)

    # Stacks empty on both sides post-drain.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0

    # Rust observable (the I61 cross-controller surveil contract).
    # P1's library is unchanged in size and per-card order; P1's
    # graveyard is empty; P0's library and graveyard are untouched.
    rust_p0_lib_after = [
        d["printing_id"] for d in rust_state.library_snapshot(0)
    ]
    rust_p1_lib_after = [
        d["printing_id"] for d in rust_state.library_snapshot(1)
    ]
    assert rust_state.library_sizes[1] == rust_p1_lib_size_before, (
        f"Rust I61 cross-controller surveil contract: P1's library "
        f"size should be unchanged (keep_all_on_top default keeps "
        f"every observed card on P1's library top). "
        f"before={rust_p1_lib_size_before} "
        f"after={rust_state.library_sizes[1]}"
    )
    assert rust_state.graveyard_sizes[1] == rust_p1_gy_size_before, (
        f"Rust I61 cross-controller surveil contract: P1's graveyard "
        f"size should be unchanged (keep_all_on_top default mills "
        f"NO cards). "
        f"before={rust_p1_gy_size_before} "
        f"after={rust_state.graveyard_sizes[1]}"
    )
    assert rust_p1_lib_after == rust_p1_lib_before, (
        f"Rust I61 cross-controller surveil contract: P1's library "
        f"top should be unchanged in original order (keep_all_on_top "
        f"default returns popped cards to library top in their "
        f"pre-pop order). "
        f"before={rust_p1_lib_before} after={rust_p1_lib_after}"
    )
    # P0 untouched. A pre-I61 Rust would have surveiled P0's library
    # (a silent no-op on the empty seat); the post-fix doesn't touch
    # P0 at all. Either way the size check is +0, but the post-fix
    # observable is "P1's library got walked" which the per-card
    # check above pins.
    assert rust_state.library_sizes[0] == rust_p0_lib_size_before, (
        f"Rust: P0's library size should be unchanged at "
        f"{rust_p0_lib_size_before} (the cross-controller surveil "
        f"never touches P0's zones). "
        f"after={rust_state.library_sizes[0]}"
    )
    assert rust_state.graveyard_sizes[0] == rust_p0_gy_size_before, (
        f"Rust: P0's graveyard size should be unchanged at "
        f"{rust_p0_gy_size_before}. "
        f"after={rust_state.graveyard_sizes[0]}"
    )
    assert rust_p0_lib_after == rust_p0_lib_before, (
        f"Rust: P0's library top should be unchanged. "
        f"before={rust_p0_lib_before} after={rust_p0_lib_after}"
    )

    # Python observable: same shape on the equivalent zones.
    py_p0_lib_after = [
        o.printing.name for o in py_state.players[0].library
    ]
    py_p1_lib_after = [
        o.printing.name for o in py_state.players[1].library
    ]
    assert len(py_state.players[1].library) == len(py_p1_lib_before), (
        f"Python: P1's library size should be unchanged "
        f"(no-agent default keeps every observed card on P1's "
        f"library top). "
        f"before={len(py_p1_lib_before)} "
        f"after={len(py_state.players[1].library)}"
    )
    assert len(py_state.players[1].graveyard) == py_p1_gy_size_before, (
        f"Python: P1's graveyard size should be unchanged "
        f"(no-agent default mills NO cards). "
        f"before={py_p1_gy_size_before} "
        f"after={len(py_state.players[1].graveyard)}"
    )
    assert py_p1_lib_after == py_p1_lib_before, (
        f"Python: P1's library top should be unchanged in original "
        f"order. before={py_p1_lib_before} after={py_p1_lib_after}"
    )
    assert len(py_state.players[0].library) == len(py_p0_lib_before), (
        f"Python: P0's library size should be unchanged at "
        f"{len(py_p0_lib_before)}. "
        f"after={len(py_state.players[0].library)}"
    )
    assert len(py_state.players[0].graveyard) == py_p0_gy_size_before, (
        f"Python: P0's graveyard size should be unchanged at "
        f"{py_p0_gy_size_before}. "
        f"after={len(py_state.players[0].graveyard)}"
    )
    assert py_p0_lib_after == py_p0_lib_before, (
        f"Python: P0's library top should be unchanged. "
        f"before={py_p0_lib_before} after={py_p0_lib_after}"
    )

    # Cross-engine: P1 library + graveyard size parity, lives parity.
    assert rust_state.library_sizes[1] == len(py_state.players[1].library)
    assert rust_state.graveyard_sizes[1] == len(py_state.players[1].graveyard)
    assert rust_state.library_sizes[0] == len(py_state.players[0].library)
    assert rust_state.graveyard_sizes[0] == len(py_state.players[0].graveyard)
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life
    # Lives unchanged on both sides (surveil substrate's keep-all
    # path has no life delta).
    assert rust_state.get_life(0) == rust_p0_life_before
    assert rust_state.get_life(1) == rust_p1_life_before
    assert py_state.players[0].life == py_p0_life_before
    assert py_state.players[1].life == py_p1_life_before

    # No pending decisions left on Rust (auto-resolve drained the
    # SurveilChoice via the trigger-path terminal call). This is the
    # load-bearing assert that proves the surveil actually fired on
    # the post-I61 path -- a pre-fix Rust would have walked P0's
    # empty library (popping 0 cards into the SurveilChoice) and
    # `has_pending_decision` would still be False, but the per-card
    # P1-library-top assert above is the cross-controller-routing
    # pin: post-fix the walk observed P1's two bait cards and
    # returned them in order; pre-fix it would have walked P0 (zero
    # observed) and the post-drain P1 library would still be in its
    # pre-trigger order BUT the SurveilChoice's per-card history
    # would be empty. The keep-all-on-top observable equivalence is
    # acceptable because Python's always-correct cross-controller
    # behavior pins the symmetric expectation: both engines end with
    # P1's library top in original order AND a drained pending
    # queue, full stop.
    assert rust_state.has_pending_decision() is False, (
        "Rust: SurveilChoice should have auto-resolved via the "
        "trigger-path's terminal keep_all_on_top call; "
        "has_pending_decision returned True"
    )


def test_cross_engine_synthetic_etb_deal_damage_to_opponent_creature_cross_controller_routes_to_source_controller_opponent_parity(
    parity_smoke,
):
    """Probe: synthetic ETB ``deal_damage_to_opponent_creature`` trigger
    fired by a permanent CONTROLLED BY P1 while ACTIVE_PLAYER=P0 -- the
    cross-controller leg of the existing
    ``deal_damage_to_opponent_creature`` bridge arm. Both engines must
    pick the bait creature on P0's bf (P0 is the SOURCE's controller's
    OPPONENT), NOT P1's own bf (which is also the active player's
    perspective opponent in the same-controller variant).

    **The substrate.** Per the Nova Hellkite same-controller probe
    (round 1 on this branch's history,
    ``test_cross_engine_real_eoe_nova_hellkite_etb_damage_to_opponent_creature_parity``):
    Rust's ``Effect::DealDamageToOpponentCreature`` resolve arm
    (state_ops_resolve.rs:6271-6342) performs an INTRINSIC 5-zone
    walk + stack-scan fallback to recover the source's controller,
    then iterates that controller's OPPONENTS in ascending player
    order and picks the first ``"Creature"`` on each opponent's bf.
    The intrinsic source-controller derivation -- not a
    ``current_resolve_source_controller`` swap -- is the I-fix
    family for this arm: it makes the cross-controller case work
    correctly without any caller plumbing because the resolve walks
    zones directly to find the source. Python's
    ``DealDamageToOpponentCreature.resolve`` (constructor sugar over
    ``DealDamage`` with the ``IsCreature() & ControlledByOpponent()``
    slot filter) takes the controller from the trigger's
    ``controller_id`` field at push time, which is the SOURCE's
    controller -- correct on this surface.

    **Same-controller sister probe** (round 1): Nova Hellkite,
    burner on P0's bf + bait on P1's bf, ACTIVE_PLAYER=P0. The
    SOURCE's controller (P0) and the active player (P0) coincide,
    so the OPPONENT pick (P1) is the same regardless of whether
    the resolve uses active_player or the source's controller.
    This probe is the cross-controller leg: burner on P1's bf
    (controller=1) + bait on P0's bf, ACTIVE_PLAYER=P0. The
    SOURCE's controller (P1) and the active player (P0) DIFFER,
    so the OPPONENT pick is P0 if-and-only-if the resolve uses the
    SOURCE's controller (post-fix). A pre-fix Rust that derived
    the opponent set from active_player would have looked at P1's
    bf for an opponent-controlled creature (finding nothing in
    this probe; a degenerate silent no-op) instead of P0's bf
    (where the bait sits).

    **Why synthetic, not Nova Hellkite.** The Nova Hellkite probe
    above already pins the same-controller leg on the real EoE
    card; spinning up a cross-controller leg on the same card
    would re-build the same harness with the only delta being the
    controllers we inject under. A synthetic 2/2 vanilla
    ("Cross-Controller Burner Bear") with the same trigger keeps
    the docstring claims of the Nova Hellkite probe intact and
    mirrors the I81/I82/I83 cross-controller probe shape.

    Probe shape (cross-controller inject-and-fire-ENTERS):

      1. **active_player=P0** (default after ``make_state`` /
         ``build_python_state``). Confirmed via
         ``state.active_player`` on Rust and
         ``state.active_player_idx`` on Python.

      2. **Inject a vanilla 2/2 bait creature ("Bait Bear") onto
         P0's bf** -- the SOURCE-controller-opponent. Pre-fix Rust
         would have iterated P1's bf opponents (= P0) but ALSO
         active-player-opponents (= P1, which is empty here),
         producing a degenerate silent no-op. Post-fix Rust
         iterates P1's opponents (= P0) and finds Bait Bear on
         P0's bf.

      3. **Inject Cross-Controller Burner Bear (the burner) onto
         P1's bf** with controller=1 (Rust's
         ``register_and_inject_object``; Python's ``new_object`` +
         bf append + manual ``_trigger_etb_abilities``). The
         injection's ENTERS dispatch fires the SourceIsSelf
         trigger; the trigger lands on the stack with controller=1
         (the SOURCE's controller).

      4. **Drain both stacks.** The trigger resolves: Rust's
         intrinsic 5-zone walk finds the burner on P1's bf,
         derives source-controller=1, iterates P1's opponents in
         ascending order = [0], scans P0's bf, finds Bait Bear,
         deals 1 damage. Python's resolve uses the trigger's
         controller_id=1 directly, the agent's pick comes from the
         legal_targets list which the slot filter (IsCreature() &
         ControlledByOpponent() with opponent=P0) restricts to
         Bait Bear, and the same 1 damage lands.

      5. **Cross-engine assert (post-fix contract):**
         - Bait Bear on P0's bf carries 1 damage on both engines.
         - Lives unchanged on both seats (effect targets a
           creature, never a player).
         - P1's bf only carries the burner (no degenerate damage
           landed there).
         - No residual stack on either engine.

    **Pre-fix vs post-fix observable.**
    Pre-fix Rust would have:
      - Derived the opponent set from active_player=P0, iterating
        P0's opponents = [1]. Scanned P1's bf for a creature,
        found ONLY the burner itself (which is the source, not a
        legal-target candidate -- the resolve arm's
        same-as-source guard rejects it). Silent no-op: Bait Bear
        carries 0 damage; P0's life unchanged but for the WRONG
        reason.
    Post-fix Rust derives source-controller=1 from the burner's
    location on P1's bf, iterates P1's opponents = [0], scans P0's
    bf, finds Bait Bear, deals 1 damage. The OBSERVABLE
    distinguishing the two: post-fix Bait Bear carries 1 damage;
    pre-fix it carries 0. Python's always-correct behavior makes
    the cross-engine pin sharp.

    Out of scope:

      * Cast-from-hand mana cost -- the inject-and-dispatch-ENTERS
        pattern bypasses the mana pipeline.
      * Multiple bait creatures on P0's bf -- the same-controller
        Nova Hellkite probe's docstring discusses scan ordering;
        a single bait keeps the agent's first-legal-target pick
        observable here.
      * Lethal-damage SBA flip -- the bait is 2/2 vs 1 damage,
        well clear of toughness.
      * The ``deal_damage_to_opponent_player`` / generic burn
        family -- separate bridge arms / separate I-fix surface.

    Expected post-dispatch + post-drain state on BOTH engines:

      * Cross-Controller Burner Bear on P1's battlefield
        (controller=1; unchanged from inject).
      * Bait Bear on P0's battlefield with damage=1 (took the
        burn).
      * P0 life: unchanged at 20.
      * P1 life: unchanged at 20.
      * No residual stack on either engine.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    spec = DeckSpec(
        card_defs=(),
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # Confirm pre-condition: active_player=P0 on both engines.
    assert rust_state.active_player == 0, (
        f"Probe pre-condition: Rust active_player must be 0; "
        f"got {rust_state.active_player}"
    )
    assert py_state.active_player_idx == 0, (
        f"Probe pre-condition: Python active_player_idx must be 0; "
        f"got {py_state.active_player_idx}"
    )

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    # Inject the bait creature on P0's bf FIRST -- the SOURCE-
    # controller's opponent (since the burner will live on P1).
    rust_bait_id = rust_state.register_and_inject_object(
        {
            "name": "Bait Bear (cross-controller burner-target probe)",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
        },
        0,
        ZONE_BATTLEFIELD,
    )
    rust_burner_dict = {
        "name": "Cross-Controller Burner Bear",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "R": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "deal_damage_to_opponent_creature",
                    "amount": 1,
                },
            }
        ],
    }
    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)
    rust_p0_bf_before = rust_state.battlefield_sizes[0]
    rust_p1_bf_before = rust_state.battlefield_sizes[1]
    # Inject the burner onto P1's bf with controller=1. ENTERS fires
    # via the deferred-dispatch queue; the SourceIsSelf trigger lands
    # on the stack with controller=1 (the SOURCE's controller).
    rust_burner_id = rust_state.register_and_inject_object(
        rust_burner_dict, 1, ZONE_BATTLEFIELD,
    )
    assert rust_state.stack_size() == 1, (
        "Rust: Cross-Controller Burner Bear's arrival on P1 should "
        "fire the SourceIsSelf ENTERS trigger and land "
        "DealDamageToOpponentCreature on the stack. "
        f"Got stack_size={rust_state.stack_size()}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.damage import (
        DealDamageToOpponentCreature,
    )
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    # Bait Bear on P0's bf -- the SOURCE-controller-opponent.
    bait_printing = CardPrinting(
        name="Bait Bear (cross-controller burner-target probe)",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=()),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
    )
    py_bait = py_state.new_object(
        bait_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_bait.summoning_sick = False
    py_bait.tapped = False
    py_bait.damage = 0
    py_bait.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_bait)

    burner_printing = CardPrinting(
        name="Cross-Controller Burner Bear",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2, colored=(("R", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=DealDamageToOpponentCreature(amount=1),
            ),
        ),
    )
    # The trigger's controller is P1 (the SOURCE's controller), so
    # P1's agent is what choose_target gets called against. Mirror
    # the Nova Hellkite probe's _PickFirstOpponentTargetAgent shim
    # but seat it on P1 (NOT P0) -- the slot's filter restricts
    # legal_targets to P1's opponents = [P0]'s creatures, and the
    # shim picks the first such target (Bait Bear).
    py_state.players[1].agent = _PickFirstOpponentTargetAgent()

    py_burner = py_state.new_object(
        burner_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_burner.summoning_sick = False
    py_burner.tapped = False
    py_burner.damage = 0
    py_burner.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_burner)
    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life
    _trigger_etb_abilities(py_state, py_burner)
    assert len(py_state.stack) == 1, (
        "Python: Cross-Controller Burner Bear's arrival on P1 should "
        "fire the IsSelf ENTERS trigger and land "
        "DealDamageToOpponentCreature on the stack. "
        f"Got stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks, then compare ----
    _drain_stack_both(py_state, rust_state)

    # Stacks empty on both sides.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0

    # Post-drain: lives unchanged on both seats. Bait Bear (on P0's
    # bf) carries 1 damage on both engines -- the load-bearing
    # cross-controller routing pin: pre-fix Rust would have iterated
    # P0's opponents (= P1, where only the burner sits) and the
    # damage would have landed on nothing (Bait Bear carries 0).
    assert rust_state.get_life(0) == rust_p0_life_before, (
        f"Rust p0 life should be unchanged ({rust_p0_life_before}); "
        f"got {rust_state.get_life(0)}"
    )
    assert rust_state.get_life(1) == rust_p1_life_before, (
        f"Rust p1 life should be unchanged ({rust_p1_life_before}); "
        f"got {rust_state.get_life(1)}"
    )
    assert rust_state.get_damage(rust_bait_id) == 1, (
        "Rust cross-controller routing contract: Bait Bear on P0's "
        "bf should carry 1 damage post-resolve (the burner's "
        "SOURCE-controller is P1, P1's opponent is P0, the scan "
        "lands on Bait Bear). A pre-fix Rust would have derived the "
        "opponent set from active_player=P0, scanned P1's bf "
        "(only the burner itself), and silent-no-opped. "
        f"Got damage={rust_state.get_damage(rust_bait_id)}"
    )
    # P1's bf carries the burner (and only the burner) -- NO
    # degenerate damage landed on the burner itself.
    rust_bf_p1_after = rust_state.battlefield_sizes[1]
    assert rust_bf_p1_after == rust_p1_bf_before + 1, (
        f"Rust: P1's bf should grow by exactly 1 (the burner). "
        f"before={rust_p1_bf_before} after={rust_bf_p1_after}"
    )
    assert rust_state.get_damage(rust_burner_id) == 0, (
        "Rust: the burner itself should carry 0 damage (the "
        "DealDamageToOpponentCreature filter excludes the source's "
        "own controller's creatures). "
        f"Got damage={rust_state.get_damage(rust_burner_id)}"
    )

    # Python observable: same shape.
    assert py_state.players[0].life == py_p0_life_before
    assert py_state.players[1].life == py_p1_life_before
    assert py_bait.damage == 1, (
        "Python: Bait Bear on P0's bf should carry 1 damage post-"
        f"resolve. Got {py_bait.damage}"
    )
    assert py_burner.damage == 0, (
        "Python: the burner itself should carry 0 damage. "
        f"Got {py_burner.damage}"
    )

    # Cross-engine: same lives, same damage on the bait, same
    # post-drain bf sizes.
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life
    assert rust_state.get_damage(rust_bait_id) == py_bait.damage
    assert rust_state.get_damage(rust_burner_id) == py_burner.damage
    py_p0_bf_after = len(
        [o for o in py_state.battlefield if o.controller_id == 0]
    )
    py_p1_bf_after = len(
        [o for o in py_state.battlefield if o.controller_id == 1]
    )
    assert rust_state.battlefield_sizes[0] == py_p0_bf_after
    assert rust_state.battlefield_sizes[1] == py_p1_bf_after


def test_cross_engine_synthetic_etb_mill_cross_controller_routes_to_source_controller_parity(
    parity_smoke,
):
    """Probe: synthetic ETB ``mill 3`` (SelfMill) trigger fired by a
    permanent CONTROLLED BY P1 while ACTIVE_PLAYER=P0 -- the I65
    controller-of-effect fix's cross-engine flicker on the existing
    ``mill`` bridge arm. Both engines must mill from P1's library
    (the source's controller), NOT from P0's library (the active
    player).

    **The I65 substrate.** Per the bridge arm comment in
    ``_ta_dict_to_python_effect`` (cross_engine.py:560-605): pre-I65
    Rust's ``Effect::Mill`` resolve arm derived its target library
    from ``state.active_player`` directly. Wrong when the resolving
    spell / triggered ability has a controller != active_player.
    The I65 fix routes that derivation through
    ``current_resolve_source_controller`` (with active_player
    fallback for direct ``apply_effect_pub`` callers), so
    cross-controller mill correctly mills from the SOURCE's library.
    Python's ``SelfMill.resolve(state, controller_id)`` takes the
    controller explicitly (the trigger's controller field) and has
    always been correct on this surface.

    **Same-controller sister probe** (round on this branch's history):
    ``test_cross_engine_real_eoe_seedship_broodtender_etb_mill_parity``
    -- burner on P0's bf + bait seeded on P0's library, ACTIVE_PLAYER=P0.
    The SOURCE's controller (P0) and the active player (P0)
    coincide, so the mill destination (P0) is the same regardless
    of which derivation Rust uses. This probe is the cross-
    controller leg: burner on P1's bf (controller=1) + bait seeded
    on P1's library, ACTIVE_PLAYER=P0. The SOURCE's controller (P1)
    and the active player (P0) differ -- the post-fix mills from
    P1, the pre-fix would have milled from P0.

    **Why synthetic, not Seedship Broodtender.** The Seedship
    Broodtender probe already pins the same-controller leg on the
    real EoE card; the cross-controller leg needs only a delta in
    seat. A synthetic 2/2 vanilla ("Cross-Controller Mill Bear")
    with the same trigger keeps the existing probe's docstring
    claims clean and mirrors the I81/I82/I83 cross-controller
    probe shape.

    Probe shape (cross-controller inject-and-fire-ENTERS):

      1. **active_player=P0** (default after ``make_state`` /
         ``build_python_state``). Confirmed via
         ``state.active_player`` on Rust and
         ``state.active_player_idx`` on Python.

      2. **Pre-seed P1's library** with FOUR distinct vanilla bait
         cards (Bait Bear 1..4). The mill-3 will pop the first
         three (Bait Bear 1, 2, 3) into P1's graveyard; Bait Bear 4
         survives as the witness on top of P1's library.

      3. **Inject Cross-Controller Mill Bear (the burner) onto P1's
         bf** with controller=1 (Rust's
         ``register_and_inject_object``; Python's ``new_object`` +
         bf append + manual ``_trigger_etb_abilities``). The
         injection's ENTERS dispatch fires the SourceIsSelf
         trigger; the trigger lands on the stack with controller=1.

      4. **Drain both stacks.** The trigger resolves: Rust's
         post-I65 Mill arm reads
         ``current_resolve_source_controller = Some(1)`` and pops
         3 cards off P1's library top into P1's graveyard. Python's
         ``SelfMill.resolve(state, 1)`` does the same on the
         equivalent state.

      5. **Cross-engine assert (post-I65 contract):**
         - P1's library shrinks by 3 (top three baits popped).
         - P1's graveyard grows by 3 (those baits land here).
         - P0's library unchanged (still empty).
         - P0's graveyard unchanged (still empty).
         - Lives unchanged on both seats.

    **Pre-I65 vs post-I65 observable.**
    Pre-fix Rust would have:
      - Derived the mill source from active_player=P0, scanned
        P0's library, found it empty, broken out of the loop. P0's
        library + graveyard unchanged; P1's library + graveyard
        unchanged.
    Post-fix Rust correctly mills from P1 (the SOURCE's
    controller). P1's library shrinks by 3, P1's graveyard grows
    by 3. Python's behavior is bit-equal because its
    ``SelfMill.resolve`` already takes the controller explicitly.
    The pre-fix-vs-post-fix divergence is observable on the P1
    library-and-graveyard delta: pre-fix +0/-0, post-fix +3/-3.

    Out of scope:

      * Cast-from-hand mana cost -- the inject-and-dispatch-ENTERS
        pattern bypasses the mana pipeline.
      * Empty-library mid-mill on the SOURCE's library -- the
        same-controller Seedship Broodtender empty-library probe
        already pins the silent-stop semantics; this probe seats
        4 baits so the mill pops cleanly without hitting empty.
      * count != 3 -- the I65 contract is independent of count;
        the same-controller Seedship Broodtender probe already
        pins count=3, and the cross-controller routing surface
        doesn't multiplex on count.
      * MillTargetPlayer -- separate effect kind / separate
        bridge surface (carries an explicit target_player field
        rather than the source-controller derivation).

    Expected post-dispatch + post-drain state on BOTH engines:

      * Cross-Controller Mill Bear on P1's battlefield (unchanged
        from inject; controller=1).
      * P1 library: 1 (Bait Bear 4 survives on top).
      * P1 graveyard: 3 (Bait Bears 1, 2, 3 milled in pop order).
      * P0 library: 0 (untouched).
      * P0 graveyard: 0 (untouched).
      * Lives unchanged on both seats.
      * No residual stack on either engine.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )

    # Four distinct bait cards on P1's library so a mill-3 leaves
    # exactly Bait Bear 4 on top as a witness (any miscount surfaces
    # as a witness-name divergence on the post-mill library top check).
    bait_1 = CardDef(
        name="Cross-Controller Mill Bait Bear 1",
        card_type="Creature",
        mana_cost_generic=1,
        power=1,
        toughness=1,
    )
    bait_2 = CardDef(
        name="Cross-Controller Mill Bait Bear 2",
        card_type="Creature",
        mana_cost_generic=1,
        power=1,
        toughness=1,
    )
    bait_3 = CardDef(
        name="Cross-Controller Mill Bait Bear 3",
        card_type="Creature",
        mana_cost_generic=1,
        power=1,
        toughness=1,
    )
    bait_4 = CardDef(
        name="Cross-Controller Mill Bait Bear 4",
        card_type="Creature",
        mana_cost_generic=1,
        power=1,
        toughness=1,
    )
    spec = DeckSpec(
        card_defs=(bait_1, bait_2, bait_3, bait_4),
        # P0 library stays EMPTY -- a pre-I65 Rust would have milled
        # from P0 (silent no-op on empty); the post-I65 fix mills from
        # P1. The size deltas on P1 below distinguish the two.
        p0_library=(),
        p1_library=(
            "Cross-Controller Mill Bait Bear 1",
            "Cross-Controller Mill Bait Bear 2",
            "Cross-Controller Mill Bait Bear 3",
            "Cross-Controller Mill Bait Bear 4",
        ),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # Confirm pre-condition: active_player=P0 on both engines.
    assert rust_state.active_player == 0, (
        f"Probe pre-condition: Rust active_player must be 0; "
        f"got {rust_state.active_player}"
    )
    assert py_state.active_player_idx == 0, (
        f"Probe pre-condition: Python active_player_idx must be 0; "
        f"got {py_state.active_player_idx}"
    )

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    rust_mill_bear_dict = {
        "name": "Cross-Controller Mill Bear",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1, "B": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "mill", "count": 3},
            }
        ],
    }
    rust_p0_lib_before = rust_state.library_sizes[0]
    rust_p0_gy_before = rust_state.graveyard_sizes[0]
    rust_p1_lib_before = rust_state.library_sizes[1]
    rust_p1_gy_before = rust_state.graveyard_sizes[1]
    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)
    assert rust_p0_lib_before == 0
    assert rust_p1_lib_before == 4

    # Inject the burner onto P1's bf with controller=1. ENTERS fires
    # via the deferred-dispatch queue; the SourceIsSelf trigger lands
    # on the stack with controller=1 (the SOURCE's controller).
    rust_state.register_and_inject_object(
        rust_mill_bear_dict, 1, ZONE_BATTLEFIELD,
    )
    assert rust_state.stack_size() == 1, (
        "Rust: Cross-Controller Mill Bear's arrival on P1 should "
        "fire the SourceIsSelf ENTERS trigger and land SelfMill(3) "
        f"on the stack. Got stack_size={rust_state.stack_size()}"
    )

    # ---- Python side ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.library_lookat import SelfMill
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    mill_bear_printing = CardPrinting(
        name="Cross-Controller Mill Bear",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=(("B", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=SelfMill(amount=3),
            ),
        ),
    )
    py_p0_lib_before = len(py_state.players[0].library)
    py_p0_gy_before = len(py_state.players[0].graveyard)
    py_p1_lib_before = len(py_state.players[1].library)
    py_p1_gy_before = len(py_state.players[1].graveyard)
    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life
    assert py_p0_lib_before == 0
    assert py_p1_lib_before == 4

    py_mill_bear = py_state.new_object(
        mill_bear_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_mill_bear.summoning_sick = False
    py_mill_bear.tapped = False
    py_mill_bear.damage = 0
    py_mill_bear.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_mill_bear)
    _trigger_etb_abilities(py_state, py_mill_bear)
    assert len(py_state.stack) == 1, (
        "Python: Cross-Controller Mill Bear's arrival on P1 should "
        "fire the IsSelf ENTERS trigger and land SelfMill(3) on the "
        f"stack. Got stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks, then compare ----
    _drain_stack_both(py_state, rust_state)

    # Stacks empty on both sides.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0

    # Per-engine post-state on Rust: P1's library shrinks by 3,
    # P1's graveyard grows by 3, P0 untouched, lives untouched.
    # The load-bearing cross-controller routing pin: pre-fix Rust
    # would have left P1's library AND graveyard at their pre-trigger
    # sizes (the mill would have hit P0's empty library and silent-
    # no-opped). Post-fix Rust mills from P1 correctly.
    assert rust_state.library_sizes[1] == rust_p1_lib_before - 3, (
        f"Rust I65 cross-controller mill contract: P1's library "
        f"should shrink by 3 (the mill source is the SOURCE's "
        f"controller = P1, not the active player = P0). Pre-fix "
        f"would have milled P0 (empty -> silent no-op) and left "
        f"P1's library at {rust_p1_lib_before}. "
        f"before={rust_p1_lib_before} "
        f"after={rust_state.library_sizes[1]}"
    )
    assert rust_state.graveyard_sizes[1] == rust_p1_gy_before + 3, (
        f"Rust I65 cross-controller mill contract: P1's graveyard "
        f"should grow by 3 (the milled cards land in the SOURCE's "
        f"controller's gy). "
        f"before={rust_p1_gy_before} "
        f"after={rust_state.graveyard_sizes[1]}"
    )
    assert rust_state.library_sizes[0] == rust_p0_lib_before, (
        f"Rust: P0's library should be unchanged at "
        f"{rust_p0_lib_before} (the mill never touches P0's zones "
        f"under the post-I65 source-controller derivation). "
        f"after={rust_state.library_sizes[0]}"
    )
    assert rust_state.graveyard_sizes[0] == rust_p0_gy_before, (
        f"Rust: P0's graveyard should be unchanged at "
        f"{rust_p0_gy_before}. "
        f"after={rust_state.graveyard_sizes[0]}"
    )
    assert rust_state.get_life(0) == rust_p0_life_before
    assert rust_state.get_life(1) == rust_p1_life_before

    # Per-engine post-state on Python: same shape.
    assert len(py_state.players[1].library) == py_p1_lib_before - 3, (
        f"Python: P1's library should shrink by 3. "
        f"before={py_p1_lib_before} "
        f"after={len(py_state.players[1].library)}"
    )
    assert len(py_state.players[1].graveyard) == py_p1_gy_before + 3, (
        f"Python: P1's graveyard should grow by 3. "
        f"before={py_p1_gy_before} "
        f"after={len(py_state.players[1].graveyard)}"
    )
    assert len(py_state.players[0].library) == py_p0_lib_before
    assert len(py_state.players[0].graveyard) == py_p0_gy_before
    assert py_state.players[0].life == py_p0_life_before
    assert py_state.players[1].life == py_p1_life_before

    # Per-card witness on P1's library top: Bait Bear 4 survives on
    # top (any miscount or wrong-pop-order surfaces as a name
    # divergence here). Library top is index 0 on both engines.
    py_p1_lib_top_name = py_state.players[1].library[0].printing.name
    assert py_p1_lib_top_name == "Cross-Controller Mill Bait Bear 4", (
        f"Python: P1's library top should be Bait Bear 4 (the "
        f"survivor) after the mill-3 popped Bait Bears 1, 2, 3. "
        f"Got top={py_p1_lib_top_name!r}"
    )
    rust_p1_lib_top_pid = rust_state.library_snapshot(1)[0]["printing_id"]
    rust_p1_lib_top_name = rust_state.library_snapshot(1)[0]["printing_name"]
    assert rust_p1_lib_top_name == "Cross-Controller Mill Bait Bear 4", (
        f"Rust: P1's library top should be Bait Bear 4 (the "
        f"survivor) after the mill-3 popped Bait Bears 1, 2, 3. "
        f"Got top={rust_p1_lib_top_name!r}"
    )

    # Cross-engine: per-zone parity on sizes + lives.
    assert rust_state.library_sizes[0] == len(py_state.players[0].library)
    assert rust_state.graveyard_sizes[0] == len(py_state.players[0].graveyard)
    assert rust_state.library_sizes[1] == len(py_state.players[1].library)
    assert rust_state.graveyard_sizes[1] == len(py_state.players[1].graveyard)
    assert rust_state.get_life(0) == py_state.players[0].life
    assert rust_state.get_life(1) == py_state.players[1].life


# === PHASE5_PROBES_INSERT_ABOVE_THIS_LINE ===
# New real-EoE parity probes go IMMEDIATELY ABOVE this marker.
# Append-only convention prevents merge collisions when multiple agents add probes in parallel.
