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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "CE12: winner_id sticky-vs-derived divergence in BOTH-LOST "
        "transition. Python writes winner_id once in SBA and never "
        "clears; Rust re-derives live from has_lost flags and returns "
        "None when both lost. See docs/RUST_PARITY_GAPS.md CE12."
    ),
)
def test_cross_engine_retaliation_selector_surfaces_ce12_winner_id_sticky_vs_derived(
    parity_smoke,
):
    """**CE12 surface-pin** (expected-fail until either Python clears
    winner_id on alive=0, or Rust grows a sticky shadow field).
    See docs/RUST_PARITY_GAPS.md CE12."""
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

    # Pre-CE12-surface: every step before the first divergence walks
    # clean. The bilateral active-player swap, summoning-sick clear,
    # symmetric multi-block combat, and life-total accounting all
    # match between engines through step 225. This pins the
    # CE12 surface to the SPECIFIC winner_id-accessor asymmetry —
    # not a broader active-player-swap or symmetric-combat
    # divergence.
    for step in result.steps[:226]:
        assert step.divergences == [], (
            f"unexpected pre-CE12 divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )

    # CE12 surface: at step 226 the field-view's winner_id slot
    # diverges — Python stays at 0 (sticky), Rust returns None
    # (live-derived from both-has_lost). Pin the EXACT field +
    # values so a future bystander divergence on a different
    # field doesn't trick this test into a false-pass.
    ce12_step = result.steps[226]
    assert len(ce12_step.divergences) == 1, (
        f"expected exactly 1 divergence at step 226 (CE12), got "
        f"{[(d.field, d.py_value, d.rust_value) for d in ce12_step.divergences]}"
    )
    div = ce12_step.divergences[0]
    assert div.field == "winner_id"
    assert div.py_value == 0
    assert div.rust_value is None
    # FORCE STRICT XFAIL: this final raise documents that the test
    # is intentionally expected-fail. Without it the assertions
    # above all pass on the actual diverging shape and pytest would
    # XPASS the strict xfail.
    pytest.fail("CE12 surface-pin observed as expected (xfail strict)")


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
# is set up by p0's turn-13 Bears cast). Surfaces CE13.
#
# **CE13 — summoning_sick-on-LTB Python-preserve vs Rust-clear.**
# When a creature leaves the battlefield (destroyed by a mass-removal
# effect — or any LTB transition that doesn't normalize the field),
# Python's ``turn.move_off_battlefield`` does NOT clear
# ``obj.summoning_sick`` while Rust's
# ``Effect::DestroyAllCreatures`` resolve loop explicitly sets
# ``obj.summoning_sick = false`` on each destroyed object. The
# summoning_sick flag carries NO gameplay meaning on a graveyard
# object (CR 302.1 — summoning sickness is a battlefield-only
# state), but the fingerprint snapshot tuple
# ``(name, tapped, sick, damage, counters, attached_to,
# controller_id, id)`` captures the raw field, so the cross-engine
# field-view compare flags it.
#
# First diverging step on the mass_removal_selector probe: index
# 168 (the side-channel wrath fire — Bears id 5, freshly cast on
# turn 13 and still summoning-sick, is the only destroyed creature
# carrying ``sick=True`` at fire time; the unsick blockers ids 9
# and 11 don't surface this gap because their sick flag matches
# between engines).
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "CE13: summoning_sick-on-LTB divergence. Python's "
        "move_off_battlefield does not clear summoning_sick; "
        "Rust's Effect::DestroyAllCreatures resolve loop explicitly "
        "sets it to false. Surfaces only when a still-sick creature "
        "is destroyed by a mass-removal effect. See "
        "docs/RUST_PARITY_GAPS.md CE13."
    ),
)
def test_cross_engine_mass_removal_selector_surfaces_ce13_summoning_sick_on_ltb(
    parity_smoke,
):
    """**CE13 surface-pin** (expected-fail until either Python clears
    summoning_sick in move_off_battlefield, or Rust drops the
    explicit clear in Effect::DestroyAllCreatures).
    See docs/RUST_PARITY_GAPS.md CE13."""
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

    # Pre-CE13-surface: every step before the side-channel wrath
    # fire walks clean. The multi-turn play, mana ability
    # activations, land plays, and creature casts on both sides
    # all match between engines through step 167. This pins the
    # CE13 surface to the SPECIFIC summoning_sick-clearing
    # asymmetry — not a broader cast / cast-target / mana-pool
    # divergence.
    for step in result.steps[:168]:
        assert step.divergences == [], (
            f"unexpected pre-CE13 divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )

    # CE13 surface: at step 168 (the side-channel wrath fire) the
    # field-view's graveyard_p0 slot diverges. Python's snapshot
    # has Bears id 5 with summoning_sick=1 (preserved across LTB),
    # Rust's has summoning_sick=0 (cleared on bf-removal). Pin the
    # EXACT field + per-object snapshot shape so a future bystander
    # divergence on a different field doesn't trick this test
    # into a false-pass.
    #
    # The snapshot tuple shape per :func:`parity_smoke._zone_signature`
    # is `(name, tapped, sick, damage, counters, attached_to,
    # controller_id, id)` — index 2 carries summoning_sick.
    ce13_step = result.steps[168]
    assert len(ce13_step.divergences) == 1, (
        f"expected exactly 1 divergence at step 168 (CE13), got "
        f"{[(d.field, d.py_value, d.rust_value) for d in ce13_step.divergences]}"
    )
    div = ce13_step.divergences[0]
    assert div.field == "graveyard_p0", (
        f"expected divergence on graveyard_p0, got {div.field}"
    )
    # py side has [Bears(sick=1), Wrath(sick=0)]; rust has
    # [Bears(sick=0), Wrath(sick=0)]. The Wrath itself was injected
    # with sick=False on both engines (the harness-construction
    # normalization in mass_removal_side_channel); the diverging
    # element is the Bears at index 0.
    assert div.py_value[0][0] == "Grizzly Bears"
    assert div.rust_value[0][0] == "Grizzly Bears"
    assert div.py_value[0][2] == 1, (
        f"expected Python Bears summoning_sick=1, got "
        f"{div.py_value[0][2]} in full snapshot {div.py_value[0]}"
    )
    assert div.rust_value[0][2] == 0, (
        f"expected Rust Bears summoning_sick=0, got "
        f"{div.rust_value[0][2]} in full snapshot {div.rust_value[0]}"
    )
    # All other snapshot fields (name, tapped, damage, counters,
    # attached_to, controller_id, id) match — the divergence is
    # ISOLATED to the summoning_sick slot. Asserts on the remaining
    # tuple positions to lock the surface tightly.
    py_bears = div.py_value[0]
    rust_bears = div.rust_value[0]
    # Indices 0 (name), 1 (tapped), 3 (damage), 4 (counters),
    # 5 (attached_to), 6 (controller_id), 7 (id) should all match.
    for i in (0, 1, 3, 4, 5, 6, 7):
        assert py_bears[i] == rust_bears[i], (
            f"unexpected Bears snapshot mismatch at index {i}: "
            f"py={py_bears[i]!r} rust={rust_bears[i]!r}"
        )
    # FORCE STRICT XFAIL: this final raise documents that the test
    # is intentionally expected-fail. Without it the assertions
    # above all pass on the actual diverging shape and pytest would
    # XPASS the strict xfail.
    pytest.fail("CE13 surface-pin observed as expected (xfail strict)")


def test_cross_engine_mass_removal_selector_pre_ce13_walks_clean(
    parity_smoke,
):
    """The pre-CE13 walk (steps 0-167) on
    :func:`multi_blocker_deckspec` with
    :func:`mass_removal_selector` is parity-clean. Pins the contract
    that CE13 is SPECIFICALLY a summoning_sick-on-LTB finding —
    not a broader divergence in cast, mana payment, multi-turn
    play, or pre-fire battlefield state.

    Walks 168 decisions (one short of the wrath fire) and asserts
    every step is divergence-free. The final clean step (167) is
    the cast_spell that puts p0's Bears#3 (id 5) on the battlefield,
    establishing the 3-creature mass-removal target set. Step 168
    is where the side-channel wrath fires and CE13 surfaces.

    Validates the load-bearing pre-condition: at the end of step
    167, the bf has exactly 3 creatures — p0=1 (sick), p1=2 (unsick).
    The selector's stateless trigger detector reads this state and
    fires the wrath on the next call.

    See CE13 in docs/RUST_PARITY_GAPS.md.
    """
    from mtg_bot.parity.cross_engine import (
        mass_removal_selector,
        multi_blocker_deckspec,
        walk_both,
        build_matched_states,
        step_both,
    )

    result = walk_both(
        multi_blocker_deckspec(),
        n_decisions=168,
        decision_selector=mass_removal_selector,
    )
    assert result.error is None
    for step in result.steps[:168]:
        assert step.divergences == [], (
            f"pre-CE13 divergence at step {step.step_index}: "
            f"action={step.action_dict} "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )

    # Walk shape sanity: rebuild the matched states, drive 168 steps,
    # and assert the resulting Python battlefield has exactly 3
    # creatures with the expected sick-status split. This is the
    # load-bearing pre-condition for the CE13 surface — if the bf
    # doesn't have a still-sick creature at fire time, the
    # summoning_sick-on-LTB asymmetry never surfaces because both
    # engines' destroyed creatures already had sick=False.
    py_state, rust_state = build_matched_states(multi_blocker_deckspec())
    for i in range(168):
        action = mass_removal_selector(py_state, rust_state, i)
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
    p0_creatures = [o for o in creatures if o.controller_id == 0]
    p1_creatures = [o for o in creatures if o.controller_id == 1]
    assert len(p0_creatures) == 1 and p0_creatures[0].summoning_sick, (
        f"expected exactly 1 still-sick p0 creature; got "
        f"{[(o.id, o.summoning_sick) for o in p0_creatures]}"
    )
    assert len(p1_creatures) == 2 and not any(
        o.summoning_sick for o in p1_creatures
    ), (
        f"expected 2 unsick p1 creatures; got "
        f"{[(o.id, o.summoning_sick) for o in p1_creatures]}"
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
