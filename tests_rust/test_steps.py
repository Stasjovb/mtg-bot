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


# --- summoning sickness clear at untap step (CR 302.1) ----------------
#
# CR 302.1: a creature is "summoning sick" until its controller has
# controlled it continuously since the start of that controller's
# most recent turn. Equivalent operational rule: at the moment of
# the UNTAP step for the new active player, that player's permanents
# lose summoning sickness. Permanents on the OTHER player's side are
# not affected by this player's untap step (they'll lose sickness
# during their own controller's next untap step, if applicable).
#
# To produce a summoning-sick permanent without a setter primitive,
# we lean on the cast slice's ``cast_creature`` — which lands a
# creature on its caster's battlefield and stamps
# ``summoning_sick = true`` (matches Python's ``put_into_battlefield``
# default). Player 1's first hand object (id 77 with the synthetic
# state's default 10/7/50 layout) is a Llanowar Elves at cost {G};
# we top up player 1's pool with ``add_mana(1, "G", 1)`` and cast
# from player 1's hand to seat the test creature.

P1_FIRST_HAND_ID = 67 + 10  # 10 bf + 7 hand + 50 lib per side; p1 base = 67
P0_FIRST_HAND_ID = 10  # p0 hand starts after the 10 battlefield ids


def test_summoning_sick_cleared_at_untap_step_for_active_player(synthetic_state):
    """Cast a creature from player 1's hand — it lands on player 1's
    battlefield with summoning_sick=true. Set phase=CLEANUP with
    active=0; advance_phase wraps to UNTAP and flips active to 1; the
    untap step for player 1 should clear summoning sickness on every
    permanent player 1 controls (CR 302.1 equivalent operational rule)."""
    elf_id = P1_FIRST_HAND_ID
    synthetic_state.add_mana(1, "G", 1)
    assert synthetic_state.cast_creature(elf_id, 1) is True
    synthetic_state.resolve_top_of_stack()  # G7 S1: land it on the bf
    assert synthetic_state.is_summoning_sick(elf_id) is True
    synthetic_state.set_phase(PHASE_CLEANUP)
    assert synthetic_state.active_player == 0
    new_phase = synthetic_state.advance_phase()
    assert new_phase == PHASE_UNTAP
    assert synthetic_state.active_player == 1
    assert synthetic_state.is_summoning_sick(elf_id) is False, (
        "untap step for the new active player should have cleared "
        "summoning sickness on that player's permanents"
    )


def test_summoning_sick_not_cleared_for_other_player(synthetic_state):
    """Sickness clears only for the controller whose UNTAP step is
    firing — the inactive side's sick permanents stay sick. Cast
    from player 0 (active), set phase=CLEANUP, advance: active flips
    to player 1, player 1's untap fires, but player 0's sick creature
    is untouched."""
    elf_id = P0_FIRST_HAND_ID
    synthetic_state.add_mana(0, "G", 1)
    assert synthetic_state.cast_creature(elf_id, 0) is True
    synthetic_state.resolve_top_of_stack()  # G7 S1: land it on the bf
    assert synthetic_state.is_summoning_sick(elf_id) is True
    synthetic_state.set_phase(PHASE_CLEANUP)
    assert synthetic_state.active_player == 0
    synthetic_state.advance_phase()
    assert synthetic_state.active_player == 1
    # Player 0's creature is NOT the new active player's permanent;
    # the untap step that just fired only touched player 1's side.
    assert synthetic_state.is_summoning_sick(elf_id) is True, (
        "summoning sickness must only clear for the new active "
        "player; the off-side's sick permanent stays sick"
    )


def test_summoning_sick_cleared_only_at_untap_step_not_other_phases(
    synthetic_state,
):
    """The sickness clear happens at UNTAP entry, not on every phase
    advance. Cast a creature for player 0 (active), set phase=MAIN1,
    advance to BEGIN_COMBAT (which doesn't touch UNTAP, doesn't flip
    the active player) — sickness must remain."""
    elf_id = P0_FIRST_HAND_ID
    synthetic_state.add_mana(0, "G", 1)
    assert synthetic_state.cast_creature(elf_id, 0) is True
    synthetic_state.resolve_top_of_stack()  # G7 S1: land it on the bf
    assert synthetic_state.is_summoning_sick(elf_id) is True
    synthetic_state.set_phase(PHASE_MAIN1)
    new_phase = synthetic_state.advance_phase()
    assert new_phase == PHASE_BEGIN_COMBAT
    assert synthetic_state.active_player == 0
    # Phase didn't pass through UNTAP; sickness is unchanged.
    assert synthetic_state.is_summoning_sick(elf_id) is True


def test_clone_then_advance_to_untap_does_not_affect_original(synthetic_state):
    """CoW canary: a sick creature on the original survives the
    clone's CLEANUP -> UNTAP wrap. Mutating the clone (which clears
    sickness on player 1's permanents) must not bleed into the
    original's battlefield zone."""
    elf_id = P1_FIRST_HAND_ID
    synthetic_state.add_mana(1, "G", 1)
    assert synthetic_state.cast_creature(elf_id, 1) is True
    synthetic_state.resolve_top_of_stack()  # G7 S1: land it on the bf
    assert synthetic_state.is_summoning_sick(elf_id) is True
    cloned = synthetic_state.clone_once()
    cloned.set_phase(PHASE_CLEANUP)
    cloned.advance_phase()
    assert cloned.active_player == 1
    assert cloned.is_summoning_sick(elf_id) is False
    # Original is untouched: still on phase 0 (UNTAP), sickness intact.
    assert synthetic_state.is_summoning_sick(elf_id) is True


# --- `step` getter — Python-Step.name parity (round 22 Phase 2b) -------
#
# `scripts/parity_smoke.py:hash_state` reads `state.step.name` (with a
# fallback to `state.step` when it's already a string). Returning the
# `mtg_bot.turn.Step` enum's `.name` strings directly from Rust makes
# both engines hash-equivalent at the active-step axis.
#
# Mirror of the Rust-side mapping in
# `rust/src/state_ops_steps.rs:GameState::step`. Two deviations from
# the round-22 brief's best-guess mapping pinned here:
#
# 1. Python has NO ``FIRST_STRIKE_DAMAGE`` step — ``STEP_ORDER`` goes
#    ``DECLARE_BLOCKERS -> COMBAT_DAMAGE`` directly. PHASE_COMBAT_DAMAGE
#    maps to ``"COMBAT_DAMAGE"``, not the brief's
#    ``"FIRST_STRIKE_DAMAGE"``.
# 2. Python phase 10 is ``Step.END`` (``.name == "END"``), not
#    ``"POSTCOMBAT_MAIN"``. The brief skipped the ``END`` step entirely.
#
# Names below are the verified ``Step.name`` strings from
# ``src/mtg_bot/turn.py:Step``.

PHASE_NAME_BY_INDEX = {
    0: "UNTAP",
    1: "UPKEEP",
    2: "DRAW",
    3: "PRECOMBAT_MAIN",
    4: "BEGINNING_OF_COMBAT",
    5: "DECLARE_ATTACKERS",
    6: "DECLARE_BLOCKERS",
    7: "COMBAT_DAMAGE",
    8: "END_OF_COMBAT",
    9: "POSTCOMBAT_MAIN",
    10: "END",
    11: "CLEANUP",
}


def test_step_returns_untap_string_for_initial_synthetic_state(synthetic_state):
    """Fresh synthetic state lands at PHASE_UNTAP, so ``state.step``
    returns the Python ``Step.UNTAP.name`` string."""
    assert synthetic_state.current_phase() == PHASE_UNTAP
    assert synthetic_state.step == "UNTAP"


def test_step_tracks_set_phase_for_each_index(synthetic_state):
    """Walking every phase index via ``set_phase`` produces the
    matching ``Step.name`` string. Pins the full 12-entry mapping
    in one test."""
    for phase_index, expected_name in PHASE_NAME_BY_INDEX.items():
        synthetic_state.set_phase(phase_index)
        assert synthetic_state.step == expected_name, (
            f"phase {phase_index}: expected step name "
            f"{expected_name!r}, got {synthetic_state.step!r}"
        )


def test_step_reflects_advance_phase_progression(synthetic_state):
    """After ``advance_phase``, ``state.step`` reflects the new
    phase name. One lap through all 12 phases must produce the
    expected sequence of ``Step.name`` strings — same shape as
    ``test_advance_phase_rotates_through_all_twelve`` but on the
    string-name surface that ``hash_state`` consumes."""
    expected = [PHASE_NAME_BY_INDEX[i] for i in range(1, 12)]
    expected.append(PHASE_NAME_BY_INDEX[0])  # wrap CLEANUP -> UNTAP
    observed = []
    for _ in range(12):
        synthetic_state.advance_phase()
        observed.append(synthetic_state.step)
    assert observed == expected
    assert synthetic_state.step == "UNTAP"


def test_step_is_a_property_not_a_method(synthetic_state):
    """``state.step`` must be a property (no parens), matching the
    Python ``GameState.step`` attribute shape. Calling it as a
    method (``state.step()``) raises ``TypeError`` because the
    return value (a ``str``) isn't callable. Pins the property
    shape so the bridge doesn't silently regress to a method form
    that would break ``hash_state``'s ``getattr(state, "step",
    None)`` lookup chain."""
    # Property access returns the string directly.
    assert isinstance(synthetic_state.step, str)
    # Calling the string raises TypeError.
    with pytest.raises(TypeError):
        synthetic_state.step()


def test_step_string_does_not_carry_dot_name_attribute(synthetic_state):
    """``hash_state`` in ``scripts/parity_smoke.py`` does
    ``getattr(state.step, "name", state.step)`` — so the Rust-side
    string MUST NOT carry a ``.name`` attribute that would shadow
    the fallback. Plain Python ``str`` doesn't carry ``.name``;
    this test pins the shape so a future refactor can't slip in a
    wrapper object whose ``.name`` returns something other than the
    value itself."""
    step = synthetic_state.step
    assert not hasattr(step, "name"), (
        "Rust-side `step` must be a plain str (no `.name` attr) so "
        "hash_state's getattr fallback collapses to the str-already "
        "branch."
    )


# ---------------------------------------------------------------------------
# Cross-feature edge cases — interactions between the step/phase machinery
# and the sibling slices (legal-decisions, fingerprint, snapshot, life,
# library, zones, tap, clone CoW).
#
# Each test asserts on a load-bearing invariant that crosses a slice boundary:
# if either side regresses, the assertion fires here even if the per-slice
# unit tests stay green. Style mirrors the per-slice tests above — module-
# level phase constants, ``synthetic_state`` fixture, prose docstrings naming
# the specific Python rule / CR clause being pinned.
# ---------------------------------------------------------------------------


def test_full_12_phase_lap_visits_each_step_name_exactly_once(synthetic_state):
    """One full lap through ``advance_phase`` from UNTAP yields each of the
    12 ``Step.name`` strings exactly once before wrapping. Cross-feature
    with the ``step`` getter — the integer phase index and the string
    name must stay in lockstep through every advance, so a follow-up
    slice can't accidentally rename one without renaming the other."""
    observed_names = []
    observed_phases = []
    for _ in range(12):
        synthetic_state.advance_phase()
        observed_phases.append(synthetic_state.current_phase())
        observed_names.append(synthetic_state.step)
    # 12 distinct names, no duplicates within a single lap.
    assert len(set(observed_names)) == 12
    # Each observed name agrees with the integer-phase mapping.
    for phase, name in zip(observed_phases, observed_names):
        assert PHASE_NAME_BY_INDEX[phase] == name


def test_advance_phase_draws_a_card_on_entering_draw_step(synthetic_state):
    """CR 504.1 — the active player draws one card on entering their
    draw step. ``advance_phase`` fires ``draw_card`` automatically
    when the new phase becomes PHASE_DRAW (gated by the CR 103.7c
    first-turn skip on ``turn_number == 1``). The synthetic-state
    harness seeds ``turn_number = 5`` so the gate is open by default:
    walking UNTAP -> UPKEEP -> DRAW should move one card from the top
    of the active player's library to their hand. Cross-feature with
    library + zones — the snapshot sizes flip in lockstep with the
    drawn card."""
    hand_before = len(synthetic_state.hand_snapshot(0))
    lib_before = len(synthetic_state.library_snapshot(0))
    # synthetic_state.active_player == 0 and turn_number == 5 (open
    # gate), so the auto-draw fires for player 0 on entry to DRAW.
    assert synthetic_state.active_player == 0
    assert synthetic_state.turn_number == 5
    synthetic_state.advance_phase()  # UPKEEP — no draw on this entry
    assert len(synthetic_state.hand_snapshot(0)) == hand_before
    assert len(synthetic_state.library_snapshot(0)) == lib_before
    synthetic_state.advance_phase()  # DRAW — auto-draw fires
    assert synthetic_state.current_phase() == PHASE_DRAW
    assert len(synthetic_state.hand_snapshot(0)) == hand_before + 1
    assert len(synthetic_state.library_snapshot(0)) == lib_before - 1


def _make_turn1_state(engine):
    """Build a fresh ``GameState`` via ``make_state`` — that helper
    seeds ``turn_number = 1`` directly (versus the synthetic-state
    fixture which seeds turn 5). Use this to exercise the CR 103.7c
    first-turn skip gate.

    Builds a small two-card registry (Forest + Grizzly Bears) and
    gives each player a 3-card library + a 1-card hand so the
    hand_snapshot / library_snapshot deltas have somewhere to land.
    """
    reg = engine.Registry()
    forest = {
        "name": "Forest",
        "card_types": ["Land"],
        "mana_cost": {},
        "effects": [],
        "mana_produced": ["G"],
    }
    bears = {
        "name": "Grizzly Bears",
        "card_types": ["Creature"],
        "mana_cost": {"G": 1, "generic": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
    }
    reg.register_printing(forest)
    reg.register_printing(bears)
    return engine.make_state(
        reg,
        [0, 0, 1],  # p0 library
        [0, 0, 1],  # p1 library
        p0_hand_printing_ids=[1],
        p1_hand_printing_ids=[1],
    )


def test_advance_phase_first_turn_active_player_skips_draw_step(engine):
    """CR 103.7c — in a two-player game, the player who plays first
    skips the draw step of their first turn. Python's ``simulate.py``
    gates this on ``state.turn_number != 1`` alone (on turn 1 the
    active player IS the starting player because ``turn_number`` only
    ticks past 1 after the first turn ends), and the Rust mirror in
    ``state_ops_steps.rs::advance_phase`` uses the same gate.

    Build a fresh state via ``make_state`` (which seeds
    ``turn_number = 1``), walk UNTAP -> UPKEEP -> DRAW, and assert
    that the active player's hand / library sizes are unchanged on
    entry to DRAW — the gate fires."""
    state = _make_turn1_state(engine)
    assert state.turn_number == 1
    assert state.active_player == 0
    assert state.current_phase() == PHASE_UNTAP
    hand_before = len(state.hand_snapshot(0))
    lib_before = len(state.library_snapshot(0))
    state.advance_phase()  # UPKEEP — no draw on this entry
    state.advance_phase()  # DRAW — gate closed at turn 1, no auto-draw
    assert state.current_phase() == PHASE_DRAW
    assert len(state.hand_snapshot(0)) == hand_before
    assert len(state.library_snapshot(0)) == lib_before


def test_advance_phase_p1_first_draw_step_does_draw_card(synthetic_state):
    """Companion to the first-turn-skip test. On turn 2 (or any
    turn != 1) the non-starting player's draw step DOES fire the
    auto-draw — confirms the gate is purely on ``turn_number != 1``,
    not on which seat is active. Walks the synthetic state's
    turn-5 seed up one full turn (12 advances, which bumps
    turn_number to 6 and flips active_player to 1), then advances
    UPKEEP -> DRAW for player 1 and asserts the auto-draw fired."""
    # Walk one full turn so active_player flips 0 -> 1 and
    # turn_number 5 -> 6 (still != 1, gate stays open).
    for _ in range(12):
        synthetic_state.advance_phase()
    assert synthetic_state.active_player == 1
    assert synthetic_state.turn_number == 6
    assert synthetic_state.current_phase() == PHASE_UNTAP
    hand_before = len(synthetic_state.hand_snapshot(1))
    lib_before = len(synthetic_state.library_snapshot(1))
    synthetic_state.advance_phase()  # UPKEEP — no draw on this entry
    assert len(synthetic_state.hand_snapshot(1)) == hand_before
    assert len(synthetic_state.library_snapshot(1)) == lib_before
    synthetic_state.advance_phase()  # DRAW — auto-draw fires for p1
    assert synthetic_state.current_phase() == PHASE_DRAW
    assert len(synthetic_state.hand_snapshot(1)) == hand_before + 1
    assert len(synthetic_state.library_snapshot(1)) == lib_before - 1


def test_main1_phase_emits_cast_spell_in_legal_decisions(synthetic_state):
    """Cross-feature with legal-decisions: PHASE_MAIN1 is sorcery timing,
    so the synthetic seed's 7 Llanowar Elves in p0's hand emit (after
    dedup by printing name) exactly one ``cast_spell`` action. The
    default UNTAP phase emits only ``pass_priority``; the
    ``set_phase(MAIN1)`` flip flips the sorcery-timing gate."""
    synthetic_state.set_phase(PHASE_MAIN1)
    actions = synthetic_state.legal_decisions(0)
    kinds = [a["kind"] for a in actions]
    assert "cast_spell" in kinds
    assert kinds.count("cast_spell") == 1
    assert kinds[0] == "pass_priority"


def test_combat_phases_gate_declare_attackers_emission(synthetic_state):
    """Cross-feature with legal-decisions: ``DeclareAttackers`` only
    emits during PHASE_DECLARE_ATTACKERS, even when the synthetic
    seed's 5 Grizzly Bears would otherwise be eligible. Walks every
    phase and asserts the emission is gated correctly — UNTAP / UPKEEP
    / DRAW / MAIN1 / BEGIN_COMBAT / DECLARE_BLOCKERS / ... / CLEANUP
    must NOT emit a ``declare_attackers`` dict (mirrors Python
    ``legal.py``'s phase guard)."""
    for phase in PHASE_SEQUENCE:
        synthetic_state.set_phase(phase)
        kinds = {a["kind"] for a in synthetic_state.legal_decisions(0)}
        if phase == PHASE_DECLARE_ATTACKERS:
            assert "declare_attackers" in kinds, (
                f"phase {phase} (DECLARE_ATTACKERS) should emit "
                f"declare_attackers; got {sorted(kinds)}"
            )
        else:
            assert "declare_attackers" not in kinds, (
                f"phase {phase} should NOT emit declare_attackers; "
                f"got {sorted(kinds)}"
            )


def test_phase_advance_preserves_life_totals(synthetic_state):
    """Cross-feature with the life slice: walking a full lap through
    all 12 phases (including the CLEANUP -> UNTAP wrap that swaps
    active_player) does NOT touch ``life_totals``. Pins the today-shape
    where ``advance_phase`` is scoped to phase / step / turn / active
    player + the per-controller untap + summoning-sickness sweep —
    nothing else. A future "lose-life-on-loss" or "lifegain-trigger-
    on-upkeep" wiring will have to update this test."""
    assert synthetic_state.life_totals == [20, 20]
    synthetic_state.set_life(0, 13)
    synthetic_state.set_life(1, 7)
    for _ in range(12):
        synthetic_state.advance_phase()
    # Full lap done — life totals unchanged.
    assert synthetic_state.get_life(0) == 13
    assert synthetic_state.get_life(1) == 7
    assert synthetic_state.life_totals == [13, 7]


def test_phase_advance_preserves_zone_sizes_except_for_auto_draw_and_cleanup_discard(
    synthetic_state,
):
    """Cross-feature with the zones / cleanup slices: a full lap
    through all 12 phases is zone-neutral on p1 but shifts one card
    on p0 — the active player throughout the DRAW step and the
    active player at CLEANUP entry.

    During the lap (active_player=0 the entire time until the very
    final CLEANUP -> UNTAP wrap):

    1. PHASE_DRAW entry fires the G14 CR 504.1 auto-draw — p0's
       library -> hand by 1.
    2. PHASE_CLEANUP entry fires the G1+G2 hook
       ``cleanup_step_for_active_player_inline``. p0's hand starts
       the lap at 7 (default) and grew to 8 from the auto-draw, so
       CR 514.1 discards 1 card (hand -> graveyard, +1).
    3. The CLEANUP -> UNTAP wrap on the final advance flips active
       to p1; p1's zones were untouched throughout.

    Net per-zone delta on p0:
    - hand:      7 -> 8 (draw) -> 7 (discard)         = 0
    - library:  50 -> 49 (draw)                       = -1
    - graveyard: 0 -> 1 (cleanup discard)             = +1

    p1's hand / library / graveyard are unchanged because p1 was
    never the active player at any DRAW or CLEANUP entry. Battlefield
    on both sides is untouched — the per-controller untap sweep
    mutates tapped-flags in place rather than moving objects."""
    p0_hand_before = len(synthetic_state.hand_snapshot(0))
    p0_lib_before = len(synthetic_state.library_snapshot(0))
    p0_grave_before = len(synthetic_state.graveyard_snapshot(0))
    p1_hand_before = len(synthetic_state.hand_snapshot(1))
    p1_lib_before = len(synthetic_state.library_snapshot(1))
    p1_grave_before = len(synthetic_state.graveyard_snapshot(1))
    bf_before = len(synthetic_state.battlefield_snapshot())
    # One full lap (12 advances). PHASE_DRAW + PHASE_CLEANUP each
    # fire exactly once with active_player == 0 (the seed's value).
    for _ in range(12):
        synthetic_state.advance_phase()
    # p0: auto-draw (+1 to hand, -1 to library) followed by cleanup
    # discard (-1 to hand, +1 to graveyard) — net zero on hand,
    # -1 on library, +1 on graveyard.
    assert (
        len(synthetic_state.hand_snapshot(0)) == p0_hand_before
    ), "active player's hand should be back to start (auto-draw +1, cleanup discard -1)"
    assert (
        len(synthetic_state.library_snapshot(0)) == p0_lib_before - 1
    ), "active player's library should shrink by 1 (auto-draw at PHASE_DRAW)"
    assert (
        len(synthetic_state.graveyard_snapshot(0)) == p0_grave_before + 1
    ), "active player's graveyard should grow by 1 (cleanup discard at PHASE_CLEANUP)"
    # The off-side (p1) was never the active player during the lap
    # (active flips from 0 -> 1 only at the very END of the lap via
    # the CLEANUP -> UNTAP wrap, after p1's DRAW + CLEANUP steps have
    # been visited as the OFF-side), so p1's zones are untouched.
    assert len(synthetic_state.hand_snapshot(1)) == p1_hand_before
    assert len(synthetic_state.library_snapshot(1)) == p1_lib_before
    assert len(synthetic_state.graveyard_snapshot(1)) == p1_grave_before
    # Battlefield untouched on both sides.
    assert len(synthetic_state.battlefield_snapshot()) == bf_before


def test_fingerprint_changes_on_every_phase_advance(synthetic_state):
    """Cross-feature with the fingerprint slice: the digest folds in
    ``state.step`` (via ``hash_state``'s parts list — see the
    test_fingerprint module docstring). Therefore each unique phase
    in a single lap produces a unique fingerprint. Pins the
    phase-sensitivity of the parity hash so a refactor that drops
    ``step`` from the parts list trips this assertion."""
    fingerprints = [synthetic_state.fingerprint()]
    for _ in range(11):
        synthetic_state.advance_phase()
        fingerprints.append(synthetic_state.fingerprint())
    # 12 distinct fingerprints, one per phase in the lap.
    assert len(set(fingerprints)) == 12, (
        f"expected 12 unique fingerprints across the 12-phase lap, "
        f"got {len(set(fingerprints))} ({fingerprints})"
    )


def test_clone_advance_phase_does_not_mutate_original(synthetic_state):
    """CoW canary on ``advance_phase``: a clone walked through a full
    lap (including the CLEANUP -> UNTAP wrap that bumps turn_number
    and flips active_player) leaves the original's step / phase /
    turn / active_player untouched. Pins the Arc-shared zone
    isolation specifically across the phase machinery — the untap
    sweep inside ``advance_phase`` calls ``Arc::make_mut`` on the new
    active player's battlefield, which is exactly the kind of mutation
    that historically leaked across clone boundaries."""
    orig_phase = synthetic_state.current_phase()
    orig_step = synthetic_state.step
    orig_turn = synthetic_state.turn_number
    orig_active = synthetic_state.active_player
    cloned = synthetic_state.clone_once()
    # Walk the clone through a full lap.
    for _ in range(12):
        cloned.advance_phase()
    # The clone bumped turn_number (CLEANUP -> UNTAP wraps once in 12
    # advances), swapped active_player, and returned to UNTAP.
    assert cloned.current_phase() == PHASE_UNTAP
    assert cloned.turn_number == orig_turn + 1
    assert cloned.active_player == 1 - orig_active
    # The original is untouched on every axis.
    assert synthetic_state.current_phase() == orig_phase
    assert synthetic_state.step == orig_step
    assert synthetic_state.turn_number == orig_turn
    assert synthetic_state.active_player == orig_active


def test_advance_phase_keeps_priority_player_in_sync_with_active(
    synthetic_state,
):
    """Round-27 G15 closure (priority × steps — CR 117.1a).

    ``advance_phase``'s CLEANUP -> UNTAP wrap flips ``active_player``
    AND resets ``priority_player`` to the new active player.
    Mirrors Python's `simulate.py:212-213` which sets
    `state.priority_player_idx = 0` at the start of turn 1 (the same
    rule generalized for either seat). The within-turn advances
    (other 11 of 12 in a lap) do NOT touch priority — only the wrap.

    Seed priority to a NON-active player (0 — but synthetic starts
    with active=0, so 0 is also the active seed) — hand it instead
    to player 1 BEFORE the wrap so the post-wrap reset to the NEW
    active (which becomes 1) is observable as the "stays at 1"
    side-effect even though the path went through a reset write."""
    # The seed already has active=0. Set priority to 0 (active) so
    # the post-wrap reset to NEW-active=1 is visibly a delta.
    synthetic_state.give_priority_to(0)
    assert synthetic_state.get_priority_player() == 0
    synthetic_state.set_phase(PHASE_CLEANUP)
    synthetic_state.advance_phase()  # CLEANUP -> UNTAP, active flips
    assert synthetic_state.active_player == 1
    # Priority reset to the NEW active player (1) on the wrap.
    assert synthetic_state.get_priority_player() == 1
    assert synthetic_state.get_priority_player() == synthetic_state.active_player


def test_set_phase_does_not_fire_untap_sweep(synthetic_state):
    """Cross-feature with the tap slice: ``set_phase`` is raw state
    assignment — it does NOT trigger the untap sweep, even when the
    target is PHASE_UNTAP. Only ``advance_phase`` composes the untap
    side-effect. Pin this asymmetry so a future refactor that
    consolidates the two entrypoints has to update both the Rust
    docstring and this test together."""
    p0_obj = _bf_id_for(0)
    assert synthetic_state.tap_object(p0_obj) is True
    assert synthetic_state.is_tapped(p0_obj) is True
    # Already in PHASE_UNTAP; re-assigning via set_phase must NOT
    # untap p0's permanent.
    synthetic_state.set_phase(PHASE_UNTAP)
    assert synthetic_state.is_tapped(p0_obj) is True
    # Same story when we land on UNTAP from a different phase via
    # set_phase (no wrap path triggered).
    synthetic_state.set_phase(PHASE_MAIN1)
    synthetic_state.set_phase(PHASE_UNTAP)
    assert synthetic_state.is_tapped(p0_obj) is True


# --- G1 + G2 closure: advance_phase fully composes phase-boundary -----
# side effects (CR 106.4 mana empty + CR 514.1 hand-size discard +
# CR 514.2 damage clear). Pinned as additional invariants alongside
# the inverted G1 / G2 pinning tests in test_mana.py / test_cleanup.py.


def test_advance_phase_empties_both_mana_pools_on_every_tick(synthetic_state):
    """CR 106.4 — "When a phase or step ends, each player's mana pool
    empties." ``advance_phase`` empties BOTH players' pools on every
    tick, not just the active player's. Pins the both-sides scope so
    a future refactor that narrows the hook to just the active side
    surfaces here."""
    synthetic_state.add_mana(0, "G", 3)
    synthetic_state.add_mana(1, "R", 2)
    assert synthetic_state.get_mana_pool(0)["G"] == 3
    assert synthetic_state.get_mana_pool(1)["R"] == 2
    synthetic_state.advance_phase()
    # Both players' pools emptied — not just the active side.
    assert synthetic_state.get_mana_pool(0) == {
        "W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0,
    }
    assert synthetic_state.get_mana_pool(1) == {
        "W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0,
    }


def test_advance_phase_empties_mana_pool_across_every_phase_in_lap(
    synthetic_state,
):
    """CR 106.4 fires on every phase boundary, not just at cleanup.
    Walk a full lap and stage mana before each tick — every tick
    leaves both pools empty. Pins the "every phase end" scope so a
    future refactor that scopes the hook to cleanup only surfaces
    here."""
    for _ in range(12):
        synthetic_state.add_mana(0, "G", 1)
        synthetic_state.add_mana(1, "R", 1)
        assert synthetic_state.get_mana_pool(0)["G"] == 1
        assert synthetic_state.get_mana_pool(1)["R"] == 1
        synthetic_state.advance_phase()
        assert synthetic_state.get_mana_pool(0)["G"] == 0
        assert synthetic_state.get_mana_pool(1)["R"] == 0


def test_advance_phase_into_cleanup_fires_hand_size_discard(synthetic_state):
    """CR 514.1 — entering PHASE_CLEANUP triggers the hand-size
    discard for the active player. Stuff p0's hand past 7, walk
    straight to CLEANUP via ``set_phase(END_STEP) + advance_phase``,
    and assert the hand is at 7 and the graveyard absorbed the
    overflow. Pins the entry-side hook on the CLEANUP transition."""
    for _ in range(3):
        synthetic_state.draw_card(0)
    assert synthetic_state.hand_sizes[0] == 10
    gy_before = synthetic_state.graveyard_sizes[0]
    synthetic_state.set_phase(PHASE_END_STEP)
    synthetic_state.advance_phase()  # END_STEP -> CLEANUP fires hook
    assert synthetic_state.current_phase() == PHASE_CLEANUP
    assert synthetic_state.hand_sizes[0] == 7
    assert synthetic_state.graveyard_sizes[0] == gy_before + 3


def test_advance_phase_into_cleanup_fires_damage_clear(synthetic_state):
    """CR 514.2 — entering PHASE_CLEANUP zeros marked damage on EVERY
    permanent on every battlefield. Stamp damage on permanents on
    both sides, advance into CLEANUP, and assert both sides come up
    clean. Pins the both-battlefields scope of the damage half of
    the cleanup hook."""
    p0_obj = _bf_id_for(0)
    p1_obj = _bf_id_for(1)
    synthetic_state.deal_damage(p0_obj, 3)
    synthetic_state.deal_damage(p1_obj, 5)
    assert synthetic_state.get_damage(p0_obj) == 3
    assert synthetic_state.get_damage(p1_obj) == 5
    synthetic_state.set_phase(PHASE_END_STEP)
    synthetic_state.advance_phase()  # END_STEP -> CLEANUP fires hook
    assert synthetic_state.current_phase() == PHASE_CLEANUP
    assert synthetic_state.get_damage(p0_obj) == 0
    assert synthetic_state.get_damage(p1_obj) == 0


def test_advance_phase_cleanup_hook_targets_old_active_player(
    synthetic_state,
):
    """The CR 514.1 hand-size discard fires on the OLD active player
    — the one whose turn is ending — because the cleanup hook runs
    on ENTRY to CLEANUP, before the CLEANUP -> UNTAP wrap flips
    active. Stuff p0's hand to 10 with active=0, walk into CLEANUP,
    and assert p0 took the discard (not p1)."""
    for _ in range(3):
        synthetic_state.draw_card(0)
    # Also stuff p1 to over-7 to make the assertion observable: if
    # the hook accidentally targeted the NEW active player (p1),
    # we'd see p1's hand at 7 and p0's at 10. We want the opposite.
    for _ in range(3):
        synthetic_state.draw_card(1)
    assert synthetic_state.hand_sizes == [10, 10]
    assert synthetic_state.active_player == 0
    synthetic_state.set_phase(PHASE_END_STEP)
    synthetic_state.advance_phase()  # END_STEP -> CLEANUP
    # p0 (the active player at entry to CLEANUP) took the discard;
    # p1 (the inactive side) kept their stuffed hand.
    assert synthetic_state.hand_sizes[0] == 7
    assert synthetic_state.hand_sizes[1] == 10


def test_advance_phase_cleanup_hook_idempotent_when_hand_at_max(
    synthetic_state,
):
    """When the active player's hand is already at exactly 7, the
    cleanup hook does NOT discard. Pins the at-threshold behavior
    so a future off-by-one in the inline mirror surfaces here."""
    assert synthetic_state.hand_sizes[0] == 7
    gy_before = synthetic_state.graveyard_sizes[0]
    synthetic_state.set_phase(PHASE_END_STEP)
    synthetic_state.advance_phase()  # END_STEP -> CLEANUP
    assert synthetic_state.hand_sizes[0] == 7
    assert synthetic_state.graveyard_sizes[0] == gy_before


def test_clone_advance_phase_into_cleanup_does_not_affect_original(
    synthetic_state,
):
    """CoW canary on the G1+G2 hooks — both the cleanup-step
    discard / damage-clear and the mana-empty must operate on the
    clone's zones without bleeding into the original. Stage damage +
    mana + a stuffed hand on the source, clone, walk the clone into
    CLEANUP, and verify the original's state survived."""
    for _ in range(3):
        synthetic_state.draw_card(0)
    synthetic_state.add_mana(0, "G", 3)
    p0_obj = _bf_id_for(0)
    synthetic_state.deal_damage(p0_obj, 4)
    cloned = synthetic_state.clone_once()
    cloned.set_phase(PHASE_END_STEP)
    cloned.advance_phase()
    # Clone took the cleanup hook: hand discarded to 7, damage cleared,
    # mana pool emptied (the latter from the CR 106.4 mana-empty hook
    # firing on the END_STEP -> CLEANUP transition).
    assert cloned.hand_sizes[0] == 7
    assert cloned.get_damage(p0_obj) == 0
    assert cloned.get_mana_pool(0)["G"] == 0
    # Original is untouched on every axis.
    assert synthetic_state.hand_sizes[0] == 10
    assert synthetic_state.get_damage(p0_obj) == 4
    assert synthetic_state.get_mana_pool(0)["G"] == 3


def test_advance_phase_auto_draw_on_empty_library_flags_attempted_draw(engine):
    """CR 704.5b / I19 closure — when ``advance_phase`` fires the
    CR 504.1 auto-draw on entry to PHASE_DRAW and the active player's
    library is empty, the inline auto-draw path flips
    ``Player.attempted_draw_on_empty`` to ``true``. Prior to this slice
    the inline mirror was a silent no-op on empty, so a player who
    decked out via the DRAW step (the common case — auto-draw at start
    of turn) was un-flagged on Rust side, even though the pymethod
    ``draw_card`` and ``Effect::DrawCards`` arms both flagged.

    The observable is ``state.losers()`` (which reads the cause-signal
    directly so the loss is eager — no SBA pass required) and the
    derived ``is_game_over`` / ``winner_id`` predicates. Mirrors the
    test style of ``tests_rust/test_library.py::
    test_drawcards_from_empty_library_marks_player_for_loss_on_next_sba``
    but exercises the inline auto-draw path instead of the pymethod /
    Effect::DrawCards paths.
    """
    # ``make_synthetic_state`` seeds turn_number=5 (gate open for the
    # CR 103.7c first-turn skip), active_player=0, phase=UNTAP. Set
    # both libraries to 0 so p0's auto-draw on PHASE_DRAW entry hits
    # an empty pop — p1's empty library is harmless because p1 is not
    # the active player.
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=0
    )
    assert state.active_player == 0
    assert state.turn_number == 5
    assert state.current_phase() == PHASE_UNTAP
    assert state.library_sizes[0] == 0
    # Before the auto-draw fires p0 is NOT a loser — empty library
    # alone doesn't trigger the loss; only an attempted draw does
    # (CR 704.5b is about the attempt, not the size). p1 is also
    # not flagged for the same reason.
    assert list(state.losers()) == []
    assert state.is_game_over() is False
    state.advance_phase()  # UNTAP -> UPKEEP: no draw hook.
    assert list(state.losers()) == []
    state.advance_phase()  # UPKEEP -> DRAW: the inline auto-draw fires.
    assert state.current_phase() == PHASE_DRAW
    # The empty-library inline pop flipped attempted_draw_on_empty
    # on the ACTIVE player (p0) only; losers() reads the cause-signal
    # directly so p0 is a loser eagerly, BEFORE any SBA pass runs.
    # p1's empty library was never popped (not the active player), so
    # p1 is not flagged.
    assert list(state.losers()) == [0]
    assert state.winner() == 1  # eager (cause-flag-driven)
    assert state.is_game_over() is True  # eager
    # Post-CE10 (CE-pure-derivation-is_over): the SBA-gated surface
    # (winner_id getter) stays stale until apply_sbas commits the loss.
    assert state.winner_id is None
    # apply_sbas transitions the cause-signal into the sticky has_lost;
    # the loss is now permanent. Return count stays 0 — player-loss
    # is a separate SBA category from creature destruction.
    assert state.apply_sbas() == 0
    assert list(state.losers()) == [0]
    # Post-SBA: surface flips to match.
    assert state.winner_id == 1
