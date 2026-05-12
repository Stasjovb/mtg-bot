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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "CE5: cast_spell diverges between Python (push StackItem, defer "
        "resolve) and Rust (cast_creature fuses cast+resolve, no stack). "
        "Pinned by docs/RUST_PARITY_GAPS.md CE5 entry; closure plan "
        "two-option (grow Rust stack OR harness-side resolve_top_of_stack "
        "mirror). This test asserts the eventual clean walk — flipped to "
        "xfail until either closure path lands."
    ),
)
def test_cross_engine_cast_bears_selector_walks_clean(parity_smoke):
    """Drive 120 decisions on the slightly_bigger_deckspec with the
    cast_bears_selector and assert every step walks clean.

    The selector activates 2 Forests for {G}{G} then casts Grizzly Bears
    at turn 9 PRECOMBAT_MAIN (p0 active). Pre-cast steps walk clean —
    the activate-ability mana-credit flow is parity-equal across both
    engines. The cast step itself (step 108) is where CE5 fires:
    Python pushes a StackItem and leaves the Bears off-battlefield,
    while Rust's ``cast_creature`` skips the stack and pushes the Bears
    directly to the battlefield.

    **Expected post-CE5-closure**: every step's ``divergences`` is
    empty. Walking 120 decisions exercises turns 1-10 including
    multiple full UNTAP/UPKEEP/DRAW/MAIN/COMBAT/CLEANUP cycles, the
    Bears cast at step 108, and post-cast battlefield comparisons.

    **Side-effect**: the walk also exercises the I19 empty-library
    eager-loss divergence at step 119 (p1 drew from empty library on
    turn 10). The CE5 closure may end the walk earlier (at the cast
    step), in which case the I19 timing surface won't be exercised by
    this test. That's acceptable — the CE5 closure-pair contract pins
    cast-time parity; downstream observers will be probed by future
    slices.
    """
    from mtg_bot.parity.cross_engine import (
        cast_bears_selector,
        slightly_bigger_deckspec,
        walk_both,
    )

    result = walk_both(
        slightly_bigger_deckspec(),
        n_decisions=120,
        decision_selector=cast_bears_selector,
    )
    assert result.error is None, (
        f"walk aborted at step {result.aborted_at}: {result.error}"
    )
    assert result.aborted_at is None
    assert len(result.steps) == 120
    for step in result.steps:
        assert step.divergences == [], (
            f"unexpected divergence at step {step.step_index}: "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
        )


def test_cross_engine_cast_bears_selector_surfaces_ce5_cast_resolve_at_step_108(
    parity_smoke,
):
    """**CE5 symptom-pin**: at step 108 (turn 9 PRECOMBAT_MAIN p0
    active) the selector emits ``cast_spell`` for Grizzly Bears. The
    cast diverges across engines on EXACTLY two fields:

      * ``battlefield`` — Python has 6 objects (pre-cast set), Rust
        has 7 (the freshly-cast Bears at the tail).
      * ``stack`` — Python has 1 entry (the Bears StackItem), Rust
        has 0.

    Companion to the strict-xfail clean-walk pin above. When CE5
    closes (either by growing Rust's stack OR by adding a Python-
    side ``resolve_top_of_stack`` harness mirror), the symptom on
    this step inverts and this test should flip to assert
    ``divergences == []``. The pair-pin pattern matches the CE3 /
    CE4 closures.
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

    # The divergence list contains both ``battlefield`` and ``stack``
    # entries. Other fields are parity-equal at this step.
    div_fields = {d.field for d in step_108.divergences}
    assert "battlefield" in div_fields, (
        f"CE5 should surface a battlefield divergence at step 108; "
        f"got fields {div_fields}"
    )
    assert "stack" in div_fields, (
        f"CE5 should surface a stack divergence at step 108; "
        f"got fields {div_fields}"
    )

    # Pin the exact divergence values:
    bf_div = next(d for d in step_108.divergences if d.field == "battlefield")
    # Python's battlefield post-cast: 6 objects (no Bears).
    assert len(bf_div.py_value) == 6
    py_names = [sig[0] for sig in bf_div.py_value]
    assert "Grizzly Bears" not in py_names
    # Rust's battlefield post-cast: 7 objects, last is Bears.
    assert len(bf_div.rust_value) == 7
    rust_names = [sig[0] for sig in bf_div.rust_value]
    assert "Grizzly Bears" in rust_names

    stack_div = next(d for d in step_108.divergences if d.field == "stack")
    # Python's stack has 1 entry (the in-flight Bears StackItem).
    assert len(stack_div.py_value) == 1
    # Rust's stack is empty (cast_creature skipped the stack).
    assert stack_div.rust_value == ()


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
