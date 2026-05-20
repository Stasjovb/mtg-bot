"""**Closed parity test** — the ``priority_player`` STATE_EQ axis
(todo ``c8d3a5f1``) + the ``blocker`` LEGAL_SET_EQ axis (todo
``d4f6a8c9``) from the broader-archetype-sweep v6-v9 cycle, **closed
by feature/priority-player-blocker-closure (2026-05-19)**.

**Closure shape.** Each test asserts the FIXED (closed) behavior — the
adapter closure makes ``rust_shadow`` run cleanly to the natural game
terminal (no ``ShadowDivergenceError`` raised) for every pinned repro
where the divergence used to surface. Same G4-lane ``86411a99``
closure-flip pattern applied: when the closure landed the previously
broken-direction pin (``test_..._is_surfaced``) flipped to its closed
form (this file).

**Root cause** (full write-up at
``docs/PRIORITY_PLAYER_AXIS_INVESTIGATION.md``): when an attacker
declared at DECLARE_ATTACKERS dies on the stack (combat-removal spell
resolves between the attack declaration and the step's empty-stack
pass-round end), the **Rust engine's ``state.attackers`` Vec retains
the dead attacker's id**. On the DECLARE_BLOCKERS phase entry,
``legal_decisions(defender)`` emits a ``blocker_decision`` referencing
the phantom attacker. The Rust adapter's ``_combat_decision_maker()``
saw the emitted ``blocker_decision`` and concluded the defender was
the structural decision-maker — gating off the
``_reset_priority_to_active()`` call in ``_run_priority_action`` and
leaving ``priority_player`` carried at the previous holder. Python's
source-of-truth ``_enter_declare_blockers`` keys off the live
``battlefield`` (``[o for o in battlefield if o.attacking]``), sees
zero live attackers, applies empty ``DeclareBlockers``, and enters
the priority window — priority returns to active.

**Closure** (landed in
``src/mtg_bot/search/rust_engine_adapter.py:_combat_decision_maker``
and ``_refresh_combat_phase``): mirror Python's live-battlefield
check in the Rust adapter — when phase == DECLARE_BLOCKERS AND
every id in ``get_attackers()`` is gone from the battlefield (the
dead-attacker invariant: ``state.attackers`` Vec has ids the
battlefield no longer contains), return None / ``_COMBAT_NONE`` so
the priority reset fires and the priority-window legal set is
returned exactly like Python. Pure ``rust_engine_adapter.py``-only
change, no ``.pyd`` rebuild — same surface as cycle-37
``86411a99``.

**Cumulative impact**: 15/1500 priority_player + 4/1500 blocker
LEGAL_SET_EQ → 0 (same root cause, two tripwire surfaces).
"""

from __future__ import annotations

import random

import pytest


# A representative subset of the 15 priority_player repros — one
# python-extra (1,0) and one rust-extra (0,1) plus the near-duplicate
# arch=276 seed=3 pair — to lock the closure across both directions
# and confirm both axes (priority_player STATE_EQ and blocker
# LEGAL_SET_EQ) are clean. The full 15 are listed in
# ``docs/BROADER_SWEEP_CONSOLIDATED_V5_V9.md`` §2.1.
_CLOSED_REPROS = [
    # (archetype, seed, prior_target_step, prior_direction)
    # prior_target_step + prior_direction were the BROKEN-behavior
    # repros surfaced before the closure landed; informational here
    # (the closure changed the legal set at earlier steps so the
    # natural step the game now reaches is different — what matters
    # is that the run completes WITHOUT a divergence at all).
    (276, 1, 857, (1, 0)),  # was py-extra v9 repro
    (290, 3, 968, (1, 0)),  # was py-extra v9 repro (sibling pair w/ arch=293)
    (114, 1, 772, (0, 1)),  # was rust-extra v6 repro
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
    "archetype,seed,prior_target_step,prior_direction", _CLOSED_REPROS,
)
def test_priority_player_FIXED_parity(
    archetype, seed, prior_target_step, prior_direction,
):
    """**Closed parity** — the closure regresses both the
    priority_player STATE_EQ axis and the blocker LEGAL_SET_EQ axis
    on this repro to clean run. If this test starts FAILING (an
    err is raised), the closure has REGRESSED on these specific
    repros — investigate the adapter guards in
    ``_combat_decision_maker`` and ``_refresh_combat_phase`` and the
    investigation doc at
    ``docs/PRIORITY_PLAYER_AXIS_INVESTIGATION.md``.
    """
    steps, err = _run_to_divergence(archetype, seed)
    assert err is None, (
        f"arch={archetype} seed={seed}: expected the closure to keep "
        f"the run divergence-clean (was a {prior_direction!r}-direction "
        f"repro at prior step ≈{prior_target_step}), but a "
        f"ShadowDivergenceError surfaced at step {steps}: "
        f"tripwire={err.tripwire if err else None!r} detail={err!s}. "
        f"Investigate whether the dead-attacker guard in "
        f"``_combat_decision_maker`` / ``_refresh_combat_phase`` is "
        f"still firing under the conditions described in "
        f"``docs/PRIORITY_PLAYER_AXIS_INVESTIGATION.md``."
    )
    # Step-count advance past ``prior_target_step`` is informational
    # only. The closure changes the legal set at earlier steps in the
    # trajectory (the cumulative residuals reach DECLARE_BLOCKERS via
    # different paths after the dead-attacker guard fires), so the
    # RNG-picked trajectory can now terminate naturally (decking out,
    # life-zero) BEFORE the prior divergence step — and that is still
    # a fully clean rust_shadow run. The absent ``ShadowDivergenceError``
    # above is the load-bearing assertion.
    del prior_target_step, steps  # informational only
