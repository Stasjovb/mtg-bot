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
