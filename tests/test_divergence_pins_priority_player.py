"""Divergence pin — the ``priority_player`` STATE_EQ axis (todo
``c8d3a5f1``) from the broader-archetype-sweep v6-v9 cycle.

**Pin shape.** Each test asserts the CURRENT (broken) behavior at one
representative repro from the 15-game cumulative residual set, so that
when the future closure agent lands the adapter fix the pin starts
**failing the wrong way** and must be FLIPPED to its closed form
(``test_..._is_closed``) in the same commit — the cycle-37 ``G4-lane
closure-flip pattern`` (``86411a99``).

**Root cause** (full write-up at
``docs/PRIORITY_PLAYER_AXIS_INVESTIGATION.md``): when an attacker
declared at DECLARE_ATTACKERS dies on the stack (combat-removal spell
resolves between the attack declaration and the step's empty-stack
pass-round end), the **Rust engine's ``state.attackers`` Vec retains
the dead attacker's id**. On the DECLARE_BLOCKERS phase entry,
``legal_decisions(defender)`` emits a ``blocker_decision`` referencing
the phantom attacker. The Rust adapter's
``_run_priority_action`` consults
``_combat_decision_maker()``, which sees the emitted
``blocker_decision`` and concludes the defender is the structural
decision-maker — **skipping the ``_reset_priority_to_active()`` call**
and leaving ``priority_player`` carried at the previous holder.
Python's source-of-truth ``_enter_declare_blockers`` keys off the
live ``battlefield`` (``[o for o in battlefield if o.attacking]``),
sees zero live attackers, applies empty ``DeclareBlockers``, and
enters the priority window — priority returns to active.

**Closure recommendation** (NOT done here): mirror Python's live-
attackers check in the Rust adapter — e.g. in
``_combat_decision_maker()`` (or a sibling adapter-side guard inside
the empty-stack pass-round branch of ``_run_priority_action``),
return ``None`` when ``phase == DECLARE_BLOCKERS`` AND no
``battlefield_snapshot()`` object has ``attacking=True``, so the
``_reset_priority_to_active()`` fires and priority returns to active
exactly like Python. Single ``rust_engine_adapter.py``-only change,
no ``.pyd`` rebuild.

**Affected residuals** (cumulative 15/1500 priority_player + 4/1500
blocker LEGAL_SET_EQ — same root cause, different tripwire surface):
the closure should regress to ≥99.74% PASS broader-sweep on v6-v9
(only the v9 battlefield STATE_EQ axis remains).
"""

from __future__ import annotations

import random

import pytest


# A representative subset of the 15 priority_player repros — one
# python-extra (1,0) and one rust-extra (0,1) plus the near-duplicate
# arch=276 seed=3 pair — to lock the bug across both directions and
# confirm the closure regresses both. The full 15 are listed in
# ``docs/BROADER_SWEEP_CONSOLIDATED_V5_V9.md`` §2.1.
_PINNED_REPROS = [
    # (archetype, seed, target_step, expected_direction)
    # direction = (py_priority, rust_priority) tuple at divergence.
    (276, 1, 857, (1, 0)),  # py-extra v9 repro
    (290, 3, 968, (1, 0)),  # py-extra v9 repro (sibling pair w/ arch=293)
    (114, 1, 772, (0, 1)),  # rust-extra v6 repro
]


def _run_to_divergence(archetype: int, seed: int, max_steps: int = 4000):
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
    "archetype,seed,target_step,direction", _PINNED_REPROS,
)
def test_priority_player_divergence_is_surfaced(
    archetype, seed, target_step, direction,
):
    """**Pin — currently failing in the broken direction.** When the
    fix lands, this test will start passing for the WRONG reason
    (no divergence raised) — the closure agent must FLIP it to
    ``test_priority_player_divergence_is_closed`` in the same commit.
    """
    steps, err = _run_to_divergence(archetype, seed)
    assert err is not None, (
        f"arch={archetype} seed={seed}: expected a "
        f"ShadowDivergenceError at step ≈{target_step}, but the run "
        f"either terminated cleanly or hit max_steps at step {steps}. "
        f"If this assertion now fails because the run is divergence-"
        f"clean, the priority_player axis closure has landed — FLIP "
        f"this pin to ``test_priority_player_divergence_is_closed`` "
        f"(see ``docs/PRIORITY_PLAYER_AXIS_INVESTIGATION.md``)."
    )
    assert err.tripwire == "STATE_EQ", (
        f"arch={archetype} seed={seed}: expected STATE_EQ tripwire "
        f"(the priority_player divergence shape), got "
        f"{err.tripwire!r}: {err!s}"
    )
    assert "priority_player" in str(err), (
        f"arch={archetype} seed={seed}: expected priority_player "
        f"field in STATE_EQ detail, got: {err!s}"
    )
    # Step alignment is informational — the deterministic seed makes
    # the divergence step stable across runs, but we don't assert
    # equality (a future engine-side change could shift the step by a
    # bounded amount without changing the axis; the field is the
    # load-bearing invariant). Logged via the assertion-failure
    # message ABOVE if the divergence vanishes.
    py_pri, rust_pri = direction
    expected_repr = f"('priority_player', {py_pri}, {rust_pri})"
    assert expected_repr in str(err), (
        f"arch={archetype} seed={seed}: expected divergence "
        f"direction {expected_repr} but err detail is: {err!s}"
    )
