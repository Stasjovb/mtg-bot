"""Battlefield STATE_EQ axis closure pin (todo ``e5b7c9d8``).

**FLIPPED FORM — closure landed.** Previously
``test_battlefield_divergence_is_surfaced`` asserted the CURRENT
(broken) behavior on the 4-game v9 residual set. The closure agent
migrated ``Effect::DestroyTargetArtifactOrTappedCreature`` and
``Effect::FocusFireEffect`` in ``rust/src/state_ops_resolve.rs`` to
the ``current_resolve_payload_target_id`` pattern (Seedship
Impact / Depressurize precedent — read the cast-time-bound target
id, fizzle silently when the target ceased between cast and resolve
per CR 608.2b).

**Root cause + closure recipe** (full write-up at
``docs/BATTLEFIELD_AXIS_INVESTIGATION.md``): the un-migrated arms
used a "first legal target via ``bf_iter_etb_sorted`` scan"
convention instead of consulting
``state.current_resolve_payload_target_id``. Python re-checks the
ORIGINAL target id (silent fizzle when illegal); pre-fix Rust
re-targeted, so when the original target died between cast and
resolve Rust hit the next matching permanent (a freshly-created
Lander token, or the next attacking creature). Post-fix: both arms
now read the bound payload-target, scan only for that id on either
bf, fizzle silently when the target left bf or no longer matches
the typed filter — byte-equal with Python.

- ``Effect::DestroyTargetArtifactOrTappedCreature``
  (``state_ops_resolve.rs:6182``) — Radiant Strike's destroy half.
- ``Effect::FocusFireEffect`` (``state_ops_resolve.rs:7162``) —
  Focus Fire's damage half.

**Affected residuals** (v9 4/300): closure regresses to 0
battlefield STATE_EQ residuals on the v9 slice.
"""

from __future__ import annotations

import random

import pytest


# The 2 strongest-signal repros from the 4 v9 battlefield STATE_EQ
# residuals (per ``docs/BATTLEFIELD_AXIS_INVESTIGATION.md`` §0, all
# 4 share the same root cause; pinning 2 is enough to assert the
# class is closed).
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
def test_battlefield_divergence_is_closed_FIXED_parity(
    archetype, seed, target_step, carrier_arm,
):
    """**Closure pin — asserts the battlefield STATE_EQ axis is
    closed.** The deterministic seed must drive past the pre-fix
    divergence step (``target_step``) without surfacing a
    ``STATE_EQ::fields:battlefield`` tripwire. If this test starts
    FAILING with a ShadowDivergenceError of the battlefield STATE_EQ
    shape, the closure has regressed.

    **Out-of-scope co-occurring axes.** The same play sequences also
    exercise the priority_player and blocker LEGAL_SET_EQ axes
    (closed by sibling lanes). Those are NOT regressed by this
    closure — the test allows divergences from OTHER axes to
    surface (they're closed by sibling lanes and out of this lane's
    scope) and only asserts the battlefield STATE_EQ axis is
    closed.
    """
    steps, err = _run_to_divergence(archetype, seed)
    if err is not None:
        is_battlefield_state_eq = (
            err.tripwire == "STATE_EQ"
            and "battlefield" in str(err)
        )
        assert not is_battlefield_state_eq, (
            f"arch={archetype} seed={seed} carrier={carrier_arm}: "
            f"battlefield STATE_EQ tripwire surfaced at step "
            f"{steps} (target_step={target_step}); the closure for "
            f"{carrier_arm} has regressed. Error: {err!s}"
        )
