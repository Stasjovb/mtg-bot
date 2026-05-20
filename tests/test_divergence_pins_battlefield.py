"""Divergence pin — the ``battlefield`` STATE_EQ axis (todo
``e5b7c9d8``) from the broader-archetype-sweep v9 cycle.

**Pin shape.** Each test asserts the CURRENT (broken) behavior at a
representative repro from the 4-game v9 residual set, so that when
the future closure agent lands the Rust-side effect-arm migration
the pin starts **failing the wrong way** and must be FLIPPED to its
closed form (``test_..._is_closed``) in the same commit — the G7
token-creation-parity closure-flip pattern (``7693c669`` /
``df4028a7``).

**Root cause** (full write-up at
``docs/BATTLEFIELD_AXIS_INVESTIGATION.md``): two effect-resolve arms
in `rust/src/state_ops_resolve.rs` are un-migrated to the
`current_resolve_payload_target_id` pattern and use a
"first-legal-target via `bf_iter_etb_sorted` scan" convention
instead. Python re-checks CR 608.2b against the ORIGINAL target id;
Rust re-targets, so when the original target dies between cast and
resolve Rust hits the next matching permanent (a freshly-created
Lander token, or the next attacking creature) and Python fizzles.

- `Effect::DestroyTargetArtifactOrTappedCreature`
  (`state_ops_resolve.rs:6182`) — Radiant Strike's destroy half.
- `Effect::FocusFireEffect` (`state_ops_resolve.rs:7162`) —
  Focus Fire's damage half.

**Closure recommendation** (NOT done here): migrate both arms to
the `current_resolve_payload_target_id` pattern. The
`Effect::SeedshipImpactEffect` arm at line 6319 is the canonical
migrated shape — read `state.current_resolve_payload_target_id`,
scan only for that id, filter-check, silent fizzle when not found.
Pure Rust touch (single `.pyd` rebuild). See
``docs/BATTLEFIELD_AXIS_INVESTIGATION.md`` §6 for the audit + fix
recipe.

**Affected residuals** (v9 4/300): the closure should regress to
0 battlefield STATE_EQ residuals on the v9 slice (and prevent the
class re-surfacing on v10+).
"""

from __future__ import annotations

import random

import pytest


# The strongest signal repro from the 4 v9 battlefield STATE_EQ
# residuals — arch=253 seed=2 step 1147. Carrier-card combination
# is the most diagnostic (Radiant Strike + Focus Fire + Beamsaw
# Prospector dies-trigger; tripped via the `Destroy
# TargetArtifactOrTappedCreature` arm picking the Lander token).
# A second repro covers `FocusFireEffect` (arch=281 s4).
# Per ``docs/BATTLEFIELD_AXIS_INVESTIGATION.md`` §0, all 4 share
# the same root cause; pinning 2 is enough to assert the class.
_PINNED_REPROS = [
    # (archetype, seed, target_step, carrier_arm)
    (253, 2, 1147, "DestroyTargetArtifactOrTappedCreature"),  # Radiant Strike re-target
    (281, 4, 2358, "FocusFireEffect"),                          # Focus Fire re-target
]


def _run_to_divergence(archetype: int, seed: int, max_steps: int = 5000):
    """Drive the ``rust_shadow`` harness deterministically; return
    the ``(steps, ShadowDivergenceError)`` pair or raise if no
    divergence surfaced before ``max_steps``."""
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


@pytest.mark.parametrize(
    "archetype,seed,target_step,carrier_arm", _PINNED_REPROS,
)
def test_battlefield_divergence_is_surfaced(
    archetype, seed, target_step, carrier_arm,
):
    """**Pin — currently failing in the broken direction.** When the
    fix lands (migrate ``Effect::DestroyTargetArtifactOrTappedCreature``
    and ``Effect::FocusFireEffect`` to the
    ``current_resolve_payload_target_id`` pattern), this test will
    start passing for the WRONG reason (no divergence raised) — the
    closure agent must FLIP it to
    ``test_battlefield_divergence_is_closed`` in the same commit.
    """
    steps, err = _run_to_divergence(archetype, seed)
    assert err is not None, (
        f"arch={archetype} seed={seed} carrier={carrier_arm}: "
        f"expected a ShadowDivergenceError at step ~={target_step}, "
        f"but the run either terminated cleanly or hit max_steps at "
        f"step {steps}. If this assertion now fails because the run "
        f"is divergence-clean, the battlefield axis closure has "
        f"landed — FLIP this pin to "
        f"``test_battlefield_divergence_is_closed`` (see "
        f"``docs/BATTLEFIELD_AXIS_INVESTIGATION.md``)."
    )
    assert err.tripwire == "STATE_EQ", (
        f"arch={archetype} seed={seed}: expected STATE_EQ tripwire "
        f"(the battlefield divergence shape), got "
        f"{err.tripwire!r}: {err!s}"
    )
    assert "battlefield" in str(err), (
        f"arch={archetype} seed={seed}: expected battlefield "
        f"field in STATE_EQ detail, got: {err!s}"
    )
    # Step alignment is informational — the deterministic seed
    # makes the divergence step stable across runs, but we don't
    # assert equality (a future engine-side change could shift the
    # step by a bounded amount without changing the axis; the field
    # is the load-bearing invariant). Logged via the assertion-
    # failure message ABOVE if the divergence vanishes.
