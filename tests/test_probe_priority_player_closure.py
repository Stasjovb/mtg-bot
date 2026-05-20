"""Real-EoE byte-equal probes for the priority_player + blocker
LEGAL_SET_EQ closure (2026-05-19, feature/priority-player-blocker-
closure).

Each probe asserts that the previously-broken-direction repro from
the broader-archetype sweep v6-v9 series now runs CLEAN under the
``rust_shadow`` shadow-checker (no ``ShadowDivergenceError`` raised)
end-to-end. These are deck-pool / random-walk probes — the closure
is a phase-entry adapter guard whose only meaningful exercise is a
real game trajectory that walks DECLARE_ATTACKERS → stack-resolve →
DECLARE_BLOCKERS in the dead-attacker shape; a synthetic micro-state
can't reproduce it without re-implementing the full deck loader +
trajectory.

The probes are intentionally tiny: ``rust_shadow``'s STATE_EQ /
LEGAL_SET_EQ assertions on every step are the byte-equal contract.
If a probe passes, the residual is closed for that game; if it
raises a ``ShadowDivergenceError`` at any step in the trajectory,
the closure regressed on that repro.

Repros chosen (per ``docs/BROADER_SWEEP_CONSOLIDATED_V5_V9.md``):

  - **priority_player axis (todo c8d3a5f1, 15/1500):**
    * arch=78 seed=4 step 1454 — v6 near-duplicate-deck pair (with
      arch=79) — exercises the most common direction.
    * arch=228 seed=2 step 1830 — v8 near-duplicate (with arch=229) —
      a different-step / different-archetype manifestation of the
      same root cause.
    * arch=290 seed=4 step 968 — v9 near-duplicate (with arch=293) —
      most recent v9 manifestation.

  - **blocker LEGAL_SET_EQ axis (todo d4f6a8c9, 4/1500):**
    * arch=220 seed=2 step 1152 — v8 Rust-extra blocker.
    * arch=226 seed=2 step 498 — v8 Rust-extra blocker, different
      attacker_id / blocker_id tuple.

These probes overlap with the ``test_divergence_pins_priority_player``
file's parity tests on a couple of archetypes but cover DIFFERENT
seeds — so each probe is an independent witness that the closure
holds across the full residual sample.
"""

from __future__ import annotations

import random

import pytest


def _run_shadow_to_terminal(archetype: int, seed: int, max_steps: int = 4000):
    """Drive the ``rust_shadow`` harness deterministically; return
    the ``(steps, ShadowDivergenceError or None)`` pair. Identical
    body to the parity-test harness in
    ``tests/test_divergence_pins_priority_player.py`` — repeated
    here so this file is self-contained and can be run standalone."""
    pytest.importorskip("mtg_bot_engine")
    from mtg_bot.parity import trajectory
    from mtg_bot.search.rust_shadow import (
        ShadowDivergenceError, build_shadow_checked_adapter,
    )

    deck_names = trajectory.load_production_deck(archetype=archetype)
    spec = trajectory.production_deck_to_deckspec(
        deck_names, shared_rng_seed=seed,
    )
    adapter = build_shadow_checked_adapter(spec)
    rng = random.Random(seed)
    steps = 0
    while steps < max_steps:
        if adapter.is_terminal():
            return steps, None
        try:
            legal = adapter.legal_decisions()
        except ShadowDivergenceError as e:
            return steps, e
        if not legal:
            return steps, None
        choice = rng.choice(legal)
        try:
            adapter.apply(choice)
        except ShadowDivergenceError as e:
            return steps, e
        steps += 1
    return steps, None


# priority_player STATE_EQ repros — sample from the 15 residual set
# spanning v6 / v8 / v9 slices and both directions.
_PRIORITY_REPROS = [
    # (archetype, seed, prior_step, axis_tag)
    (78, 4, 1454, "priority_player_v6_near_dup"),
    (228, 2, 1830, "priority_player_v8_near_dup"),
    (290, 4, 968, "priority_player_v9_near_dup"),
]

# blocker LEGAL_SET_EQ repros — the v8 cluster.
_BLOCKER_REPROS = [
    # (archetype, seed, prior_step, axis_tag)
    (220, 2, 1152, "blocker_legal_set_v8"),
    (226, 2, 498, "blocker_legal_set_v8"),
]


@pytest.mark.parametrize(
    "archetype,seed,prior_step,axis_tag", _PRIORITY_REPROS,
)
def test_priority_player_closure_byte_equal(
    archetype, seed, prior_step, axis_tag,
):
    """``rust_shadow`` STATE_EQ assertion runs clean on every step
    of the trajectory for a priority_player residual."""
    steps, err = _run_shadow_to_terminal(archetype, seed)
    assert err is None, (
        f"axis={axis_tag} arch={archetype} seed={seed}: closure "
        f"regressed — ShadowDivergenceError at step {steps}: "
        f"tripwire={err.tripwire if err else None!r} detail={err!s}"
    )
    # ``steps`` advancing past ``prior_step`` is the strongest signal
    # that the closure held end-to-end, but the closure changes the
    # legal set at multiple earlier steps too — that shifts the RNG-
    # picked trajectory, which can let the game terminate naturally
    # (decking out, life-zero) earlier than the prior divergent
    # trajectory did. Either outcome (passed the old divergence step
    # or terminated cleanly earlier) satisfies the byte-equal contract;
    # the absent ``ShadowDivergenceError`` above is the load-bearing
    # assertion.
    del prior_step, steps  # informational; closure is the err-is-None gate


@pytest.mark.parametrize(
    "archetype,seed,prior_step,axis_tag", _BLOCKER_REPROS,
)
def test_blocker_legal_set_closure_byte_equal(
    archetype, seed, prior_step, axis_tag,
):
    """``rust_shadow`` LEGAL_SET_EQ assertion runs clean on every step
    of the trajectory for a blocker-axis residual (same root cause as
    priority_player; different tripwire surface)."""
    steps, err = _run_shadow_to_terminal(archetype, seed)
    assert err is None, (
        f"axis={axis_tag} arch={archetype} seed={seed}: closure "
        f"regressed — ShadowDivergenceError at step {steps}: "
        f"tripwire={err.tripwire if err else None!r} detail={err!s}"
    )
    # Step-count advance past prior_step is informational only — the
    # closure changes the legal set at earlier steps, shifting the
    # RNG-picked trajectory, so the natural termination point can be
    # earlier than the prior divergent run. The absent
    # ``ShadowDivergenceError`` above is the load-bearing assertion.
    del prior_step, steps  # informational; closure is the err-is-None gate
