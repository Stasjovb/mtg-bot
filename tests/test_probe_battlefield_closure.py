"""Real-EoE byte-equal probes for the battlefield STATE_EQ axis
closure (todo ``e5b7c9d8``).

**What this pins.** The two un-migrated ``Effect::*`` arms in
``rust/src/state_ops_resolve.rs`` —
``DestroyTargetArtifactOrTappedCreature`` (Radiant Strike's destroy
half) and ``FocusFireEffect`` (Focus Fire's damage half) — were
migrated to the ``current_resolve_payload_target_id`` pattern
(SeedshipImpactEffect / DepressurizeEffect precedent). These probes
drive deterministic ShadowChecked adapter runs at the v9 residual
repros (arch=253 s2, arch=281 s4) and assert the previously-
diverging battlefield STATE_EQ tripwire is silent.

**Run-to-completion (or to a non-battlefield-STATE_EQ axis trip).**
The arch=253/281 play sequences also exercise the priority_player
and blocker LEGAL_SET_EQ axes (closed by sibling lanes). Those are
out of this lane's scope; this probe asserts ONLY that the
battlefield STATE_EQ axis is closed, allowing other-axis trips to
surface (or not, depending on the sibling lane's merge order).
"""

from __future__ import annotations

import random

import pytest


def _run_to_divergence(archetype: int, seed: int, max_steps: int = 5000):
    """Drive the ``rust_shadow`` harness deterministically; return
    the ``(steps, ShadowDivergenceError | None)`` pair."""
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


def test_radiant_strike_beamsaw_prospector_arch253_no_battlefield_state_eq():
    """**arch=253 seed=2 step 1147 — Radiant Strike + Beamsaw
    Prospector dies-trigger.**

    Pre-fix repro: P0 attacks with Beamsaw Prospector id=0 (tapped).
    P1 casts Radiant Strike on Beamsaw, then Focus Fire on Beamsaw.
    Focus Fire resolves first (LIFO top), kills Beamsaw, dies-
    trigger creates Lander id=120 (Artifact). Radiant Strike then
    resolves: Python re-checks bound target id=0 (Beamsaw), finds
    it in graveyard → fizzle. Rust pre-fix scanned bf, picked
    Lander (first Artifact) and destroyed it → divergence at step
    1147.

    Post-fix: Rust reads ``current_resolve_payload_target_id ==
    Some(0)``, scans for id=0 on bf, finds None → fizzle. Byte-
    equal with Python; no battlefield STATE_EQ tripwire.
    """
    steps, err = _run_to_divergence(253, 2)
    if err is not None:
        is_battlefield_state_eq = (
            err.tripwire == "STATE_EQ"
            and "battlefield" in str(err)
        )
        assert not is_battlefield_state_eq, (
            f"arch=253 seed=2 step {steps}: battlefield STATE_EQ "
            f"tripwire surfaced after the closure landed — the "
            f"Radiant Strike re-target bug is back. Error: {err!s}"
        )


def test_focus_fire_double_cast_arch281_no_battlefield_state_eq():
    """**arch=281 seed=4 step 2358 — Focus Fire double-cast on
    Human Soldier id=120 / Knight Luminary id=10.**

    Pre-fix repro: P0 declares 3 attackers (Knight Luminary id=10,
    Human Soldiers id=120 and id=121). P1 casts 2 Focus Fires each
    targeting id=120. Python resolves each Focus Fire against bound
    target id=120 → damages Human Soldier 120 → dies. Rust pre-fix
    scanned for first attacking-or-blocking creature in ETB order
    → picked Knight id=10 (oldest attacker) twice → Knight dies,
    id=120 survives → divergence at step 2358.

    Post-fix: Rust reads ``current_resolve_payload_target_id ==
    Some(120)``, scans for id=120 on bf, finds it (still
    attacking) → deals damage to id=120. Byte-equal with Python;
    no battlefield STATE_EQ tripwire.
    """
    steps, err = _run_to_divergence(281, 4)
    if err is not None:
        is_battlefield_state_eq = (
            err.tripwire == "STATE_EQ"
            and "battlefield" in str(err)
        )
        assert not is_battlefield_state_eq, (
            f"arch=281 seed=4 step {steps}: battlefield STATE_EQ "
            f"tripwire surfaced after the closure landed — the "
            f"Focus Fire re-target bug is back. Error: {err!s}"
        )
