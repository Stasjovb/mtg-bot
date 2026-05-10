"""Phase / step advancement primitives on the Rust ``GameState``.

Ported from Python's ``src/mtg_bot/turn.py`` (the ``STEP_ORDER`` tuple,
``run_untap_step``, ``run_cleanup_step``) and the simulation driver
that advances through them. The Python side carries a ``Step`` enum
and walks the global ``STEP_ORDER`` tuple; the Rust side keeps phase
as a raw ``u8`` field on ``GameState`` (already present) and the
constants are exposed in ``rust/src/state_ops_steps.rs``.

**Phase encoding (option a — 12 raw u8 constants).** Mirrors the
zones-slice convention rather than introducing a `Phase` enum on
``state.rs`` (which would conflict with sibling slices growing the
same file). Constants duplicated here for readability and as a
parity check against the Rust side.

**Cross-slice composition (load-bearing).** ``advance_phase`` calls
the tap-slice's ``untap_all_for_player`` directly when the new phase
is UNTAP, on the new active player. This is the integration test that
proves the parallel-TDD harness composes — two slices' methods
communicating via ``self`` on a shared ``GameState``.
"""

from __future__ import annotations

import pytest


# Mirror of rust/src/state_ops_steps.rs — order matches Python's
# src/mtg_bot/turn.py:STEP_ORDER (UNTAP / UPKEEP / DRAW /
# PRECOMBAT_MAIN / BEGINNING_OF_COMBAT / DECLARE_ATTACKERS /
# DECLARE_BLOCKERS / COMBAT_DAMAGE / END_OF_COMBAT / POSTCOMBAT_MAIN /
# END / CLEANUP).
PHASE_UNTAP = 0
PHASE_UPKEEP = 1
PHASE_DRAW = 2
PHASE_MAIN1 = 3
PHASE_BEGIN_COMBAT = 4
PHASE_DECLARE_ATTACKERS = 5
PHASE_DECLARE_BLOCKERS = 6
PHASE_COMBAT_DAMAGE = 7
PHASE_END_COMBAT = 8
PHASE_MAIN2 = 9
PHASE_END_STEP = 10
PHASE_CLEANUP = 11

PHASE_SEQUENCE = (
    PHASE_UNTAP,
    PHASE_UPKEEP,
    PHASE_DRAW,
    PHASE_MAIN1,
    PHASE_BEGIN_COMBAT,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
    PHASE_COMBAT_DAMAGE,
    PHASE_END_COMBAT,
    PHASE_MAIN2,
    PHASE_END_STEP,
    PHASE_CLEANUP,
)


def _bf_id_for(player_id):
    """Mirror of test_tap.py's _bf_ids: synthetic state default puts
    player 0's battlefield at ids 0..9 and player 1's at 67..76."""
    if player_id == 0:
        return 0
    return 67


def test_initial_phase_is_zero(synthetic_state):
    """Fresh synthetic state lands at PHASE_UNTAP with the seeded
    turn_number=5 from make_synthetic_state in state.rs."""
    assert synthetic_state.current_phase() == PHASE_UNTAP
    assert synthetic_state.turn_number == 5


def test_advance_phase_returns_new_phase(synthetic_state):
    """`advance_phase` returns the new phase after the tick."""
    assert synthetic_state.advance_phase() == PHASE_UPKEEP


def test_advance_phase_rotates_through_all_twelve(synthetic_state):
    """One full lap through the sequence ends back at UNTAP, with each
    intermediate return matching the constant ordering."""
    # 12 advances starting from UNTAP visit each successor in order;
    # the 12th wraps back to UNTAP (CLEANUP -> UNTAP).
    expected = list(PHASE_SEQUENCE[1:]) + [PHASE_UNTAP]
    observed = [synthetic_state.advance_phase() for _ in range(12)]
    assert observed == expected
    assert synthetic_state.current_phase() == PHASE_UNTAP


def test_advance_phase_from_cleanup_increments_turn_number(synthetic_state):
    """Wrapping CLEANUP -> UNTAP bumps the turn counter by 1 and
    swaps active_player."""
    synthetic_state.set_phase(PHASE_CLEANUP)
    starting_turn = synthetic_state.turn_number
    starting_active = synthetic_state.active_player
    new_phase = synthetic_state.advance_phase()
    assert new_phase == PHASE_UNTAP
    assert synthetic_state.turn_number == starting_turn + 1
    assert synthetic_state.active_player == 1 - starting_active


def test_advance_phase_from_cleanup_fires_untap_step_on_new_active_player(
    synthetic_state,
):
    """Cross-slice composition: wrapping into UNTAP fires the tap-slice's
    untap-all sweep on the NEW active player. Tap a permanent on player
    1's battlefield, fast-forward to CLEANUP with active_player=0,
    advance — the swap to active_player=1 should automatically untap
    player 1's permanent."""
    p1_obj = _bf_id_for(1)
    assert synthetic_state.tap_object(p1_obj) is True
    assert synthetic_state.is_tapped(p1_obj) is True
    synthetic_state.set_phase(PHASE_CLEANUP)
    assert synthetic_state.active_player == 0
    new_phase = synthetic_state.advance_phase()
    assert new_phase == PHASE_UNTAP
    assert synthetic_state.active_player == 1
    assert synthetic_state.is_tapped(p1_obj) is False, (
        "untap step should have fired automatically for the new "
        "active player"
    )


def test_untap_step_does_not_untap_other_players_permanents(synthetic_state):
    """The untap step is per-controller. Tap a permanent on the
    inactive player's side, advance through the wrap — only the new
    active player's permanents come up untapped, the off-side stays
    tapped."""
    p0_obj = _bf_id_for(0)
    assert synthetic_state.tap_object(p0_obj) is True
    synthetic_state.set_phase(PHASE_CLEANUP)
    assert synthetic_state.active_player == 0
    synthetic_state.advance_phase()
    # active_player flipped to 1; the untap step fired for p1, p0's
    # tapped permanent stays tapped.
    assert synthetic_state.active_player == 1
    assert synthetic_state.is_tapped(p0_obj) is True


def test_is_main_phase_true_for_main1_and_main2(synthetic_state):
    """`is_main_phase` true for PHASE_MAIN1 and PHASE_MAIN2, false
    elsewhere (a representative non-main check)."""
    synthetic_state.set_phase(PHASE_MAIN1)
    assert synthetic_state.is_main_phase() is True
    synthetic_state.set_phase(PHASE_BEGIN_COMBAT)
    assert synthetic_state.is_main_phase() is False
    synthetic_state.set_phase(PHASE_MAIN2)
    assert synthetic_state.is_main_phase() is True


def test_is_combat_phase_true_for_combat_phases(synthetic_state):
    """`is_combat_phase` true for the five combat steps (4..=8)
    inclusive, false for everything else."""
    combat_phases = {
        PHASE_BEGIN_COMBAT,
        PHASE_DECLARE_ATTACKERS,
        PHASE_DECLARE_BLOCKERS,
        PHASE_COMBAT_DAMAGE,
        PHASE_END_COMBAT,
    }
    for phase in PHASE_SEQUENCE:
        synthetic_state.set_phase(phase)
        expected = phase in combat_phases
        assert synthetic_state.is_combat_phase() is expected, (
            f"phase {phase}: expected is_combat_phase={expected}, got "
            f"{synthetic_state.is_combat_phase()}"
        )


def test_clone_preserves_phase_and_advances_independently(synthetic_state):
    """Clone CoW: cloning at MAIN1, advancing the clone twice (to
    DECLARE_ATTACKERS), the original stays at MAIN1."""
    synthetic_state.set_phase(PHASE_MAIN1)
    cloned = synthetic_state.clone_once()
    assert cloned.current_phase() == PHASE_MAIN1
    cloned.advance_phase()  # -> BEGIN_COMBAT
    cloned.advance_phase()  # -> DECLARE_ATTACKERS
    assert cloned.current_phase() == PHASE_DECLARE_ATTACKERS
    assert synthetic_state.current_phase() == PHASE_MAIN1


def test_set_phase_validates_range(synthetic_state):
    """set_phase rejects out-of-range values rather than silently
    corrupting state."""
    with pytest.raises(ValueError):
        synthetic_state.set_phase(12)
    with pytest.raises(ValueError):
        synthetic_state.set_phase(255)
    # State unchanged after the rejected calls.
    assert synthetic_state.current_phase() == PHASE_UNTAP
