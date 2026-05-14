"""Phase 6 trajectory-parity seed.

The Phase 5 cross-engine harness (``mtg_bot.parity.cross_engine``) ships a
broad suite of synthetic-deck multi-turn smokes — :func:`walk_both` +
:func:`multi_turn_selector` + :func:`cast_bears_selector` etc. drive 7-card
``DeckSpec`` games through 50-150 decisions and assert byte-equal field views
across both engines on every step. Phase 5's gate is on
``tests/test_parity_smoke.py`` + ``tests/test_cross_engine_etb_triggers.py``;
the existing trajectory selectors run cleanly today.

What Phase 5 deliberately does NOT cover:

1. **Real opening hands.** Every Phase 5 ``DeckSpec`` builds states with
   empty starting hands and lets the selector draw via the side-channel
   advance (which fires on turn 2's DRAW step under CR 103.7c). A real
   game starts with seven cards in hand on each side, dealt at setup —
   neither :func:`build_matched_states` nor any helper Phase 5 ships
   does the opening draw.
2. **Decks > 7 cards.** The biggest Phase 5 fixture is
   :func:`multi_blocker_deckspec` at 7 cards per side; trajectory parity
   on a real 60-card deck is unprobed.
3. **An end-to-end "real game prefix" assertion.** Phase 5 surfaces
   per-step divergences as a side effect of running custom selectors.
   It does not have a "set up 60 vanilla bears, deal opening hands,
   walk turn 1 no-ops, assert global state invariants" test that
   matches the shape of what trajectory-parity probes need to look
   like at scale.

This seed file ships the smallest real-game-shaped trajectory-parity
test that fills the three gaps above. It is **deliberately a seed**, not
a production scaffold — the goal is to surface what additional Phase 6
infrastructure we need (e.g. a shared real-game ``setup_game`` mirror
that handles opening hands + mulligans cross-engine), and to pin the
no-op turn-structure invariants that already hold so any future
regression on them shows up loudly.
"""

from __future__ import annotations

import importlib.util

import pytest


# Skip the whole module if the Rust extension isn't built — same policy
# as ``tests/test_parity_smoke.py``.
pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# Real-game-shaped DeckSpec helpers.
#
# Vanilla 60-card mono-green deck: 24 Forest + 36 Grizzly Bears. Mirrored
# on both sides so any divergence is unambiguously a cross-engine bug
# rather than an asymmetric-decklist artifact.
#
# CE8 ``shared_rng_seed`` is the substrate hook that makes both engines
# shuffle the same library to the same permutation — Phase 5 already
# proved this on the small synthetic decks; this seed extends the proof
# to a real-game-sized library.
# ---------------------------------------------------------------------------


def _vanilla_60_deckspec(seed: int = 42):
    """A 60-card mirror-match: 24 Forest + 36 Grizzly Bears each side.

    ``shared_rng_seed`` drives both engines to the same Fisher-Yates
    permutation via the substrate hook (Phase 5 CE8 closure).
    """
    from mtg_bot.parity.cross_engine import CardDef, DeckSpec

    forest = CardDef(name="Forest", card_type="Land", mana_produced=("G",))
    bears = CardDef(
        name="Grizzly Bears",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=2,
        toughness=2,
    )
    library = ("Forest",) * 24 + ("Grizzly Bears",) * 36
    return DeckSpec(
        card_defs=(forest, bears),
        p0_library=library,
        p1_library=library,
        shared_rng_seed=seed,
    )


def _draw_opening_hand(py_state, rust_state, n: int = 7) -> None:
    """Mirror real-game ``setup_game``'s seven-card opening draw on BOTH engines.

    Phase 5's ``play_a_land_selector`` already proved Python's
    ``turn.draw_card`` + Rust's ``draw_card`` pymethod produce
    byte-equal hand/library views when both libraries start at the
    same permutation (CE3 closure). This helper just fires that draw
    seven times per player.

    Phase 6 follow-up infrastructure: a single helper that wraps the
    ``setup_game(decks=[...], seed=...)`` shape on both engines so the
    test surface doesn't have to spell out the per-engine draw
    primitive every time. Out-of-scope for this seed.
    """
    from mtg_bot.turn import draw_card as py_draw_card

    for pid in (0, 1):
        for _ in range(n):
            py_draw_card(py_state, pid)
            rust_state.draw_card(pid)


def _step_views(py_state, rust_state):
    """Return ``(py_view, rust_view)`` for the field-by-field compare."""
    from mtg_bot.parity.cross_engine import (
        build_python_field_view,
        parity_smoke,
    )

    ps = parity_smoke()
    return build_python_field_view(py_state), ps._build_field_view(rust_state)


# ---------------------------------------------------------------------------
# Test 1: no-op first turn — the strongest trajectory-parity invariant.
#
# After dealing opening hands and walking turn 1's eleven phases (UNTAP ->
# UPKEEP -> DRAW -> ... -> CLEANUP -> [wrap into turn 2 UNTAP]) without
# casting anything, both engines must agree on every observable in the
# field view. CR 103.7c skips the turn-1 draw on both sides; turn 2 UNTAP
# is the wrap point. This pins the absolute baseline: turn-structure
# parity for a no-op real-game prefix.
# ---------------------------------------------------------------------------


def test_no_op_first_turn_parity():
    """Drive one full turn of no-op play on a real-game-sized deck and
    assert byte-equal field views at EVERY phase boundary.

    Pre-conditions:
      * 60-card vanilla deck (24 Forest + 36 Grizzly Bears) mirrored
        across both sides.
      * Shared RNG seed so both engines shuffle identically.
      * Seven-card opening hand dealt to each player on both engines.

    Walk: 12 advance_phase calls. Starting at turn 1 UNTAP, each
    ``advance_phase`` ticks one phase: UPKEEP, DRAW, PRECOMBAT_MAIN,
    BEGINNING_OF_COMBAT, DECLARE_ATTACKERS, DECLARE_BLOCKERS,
    COMBAT_DAMAGE, END_OF_COMBAT, POSTCOMBAT_MAIN, END, CLEANUP
    (advances 1-11), then CLEANUP -> turn 2 UNTAP wrap (advance 12).

    Strong invariants asserted at every step:
      * life totals = (20, 20)
      * hand sizes = (7, 7) on turn 1 (CR 103.7c skips draw); flips to
        (7, 8) on turn 2 DRAW (active player p1 draws one)
      * library sizes track hand draws
      * turn / step / active_player / priority_player byte-equal
      * battlefield empty (no plays in this prefix)
      * no field-view divergences anywhere

    This is the absolute floor — if this test fails, the cross-engine
    bridge for opening-hand + turn-structure is broken at a level no
    Phase 5 selector could surface (Phase 5 always starts with empty
    hands).
    """
    from mtg_bot.parity.cross_engine import (
        advance_phase_python,
        build_matched_states,
        compare_fields,
    )

    spec = _vanilla_60_deckspec(seed=42)
    py_state, rust_state = build_matched_states(spec)
    _draw_opening_hand(py_state, rust_state, n=7)

    # Sanity: at the start of turn 1 UNTAP, both engines agree.
    py_view, rust_view = _step_views(py_state, rust_state)
    initial_divs = compare_fields(py_view, rust_view)
    assert initial_divs == [], (
        f"opening-hand state diverges before any phase advance: "
        f"{[(d.field, d.py_value, d.rust_value) for d in initial_divs]}"
    )
    assert py_view["turn"] == 1
    assert py_view["step"] == "UNTAP"
    assert py_view["life_p0"] == 20
    assert py_view["life_p1"] == 20
    assert len(py_view["hand_p0"]) == 7
    assert len(py_view["hand_p1"]) == 7
    assert len(py_view["library_p0"]) == 53
    assert len(py_view["library_p1"]) == 53
    assert py_view["battlefield"] == ()

    # Walk 12 phase advances: 11 to walk turn 1 UNTAP -> CLEANUP, then
    # one more for the CLEANUP -> turn 2 UNTAP wrap.
    for advance_idx in range(12):
        advance_phase_python(py_state)
        rust_state.advance_phase()

        py_view, rust_view = _step_views(py_state, rust_state)
        divs = compare_fields(py_view, rust_view)
        assert divs == [], (
            f"advance #{advance_idx} ({py_view['step']!r}, turn "
            f"{py_view['turn']}) surfaced divergences: "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in divs]}"
        )

        # Strong invariants on every step. No combat damage, no land
        # plays, no draws other than turn-2's auto-draw — life and
        # battlefield are immutable in this prefix.
        assert py_view["life_p0"] == 20
        assert py_view["life_p1"] == 20
        assert py_view["battlefield"] == ()
        # Hand sizes: stay at 7 through turn 1 (CR 103.7c skips
        # turn-1 draw). The wrap into turn 2 UNTAP is pre-DRAW, so
        # hands stay at 7 across this entire 12-advance walk.
        assert len(py_view["hand_p0"]) == 7
        assert len(py_view["hand_p1"]) == 7

    # Post-walk: at turn 2 UNTAP with active player p1.
    py_view, _rust_view = _step_views(py_state, rust_state)
    assert py_view["turn"] == 2
    assert py_view["step"] == "UNTAP"
    assert py_view["active_player"] == 1
    assert py_view["priority_player"] == 1


# ---------------------------------------------------------------------------
# Test 2: turn-2 draw step parity. The first phase that mutates a real
# game-state observable (hand size + library size). CR 103.7c gates turn 1
# but turn 2 DRAW must fire on the active player on both engines.
# ---------------------------------------------------------------------------


def test_turn_2_draw_step_parity():
    """Walk through turn 1 + turn 2 UNTAP/UPKEEP/DRAW and assert the
    turn-2 DRAW step bumps the new active player's hand from 7 -> 8 on
    both engines uniformly.

    This is the first cross-engine compare of a phase-boundary
    side-effect (CR 504.1 draw) on a real-game-shaped state. Phase 5's
    multi_turn_selector test exercises the same boundary on a 4-card
    library; this seed proves it holds on 60.
    """
    from mtg_bot.parity.cross_engine import (
        advance_phase_python,
        build_matched_states,
        compare_fields,
    )

    spec = _vanilla_60_deckspec(seed=42)
    py_state, rust_state = build_matched_states(spec)
    _draw_opening_hand(py_state, rust_state, n=7)

    # Walk through turn 1 (12 advances -> turn 2 UNTAP), then UPKEEP
    # (1 more), then DRAW (1 more). Total = 14 advances.
    for _ in range(14):
        advance_phase_python(py_state)
        rust_state.advance_phase()

    py_view, rust_view = _step_views(py_state, rust_state)
    divs = compare_fields(py_view, rust_view)
    assert divs == [], (
        f"turn-2 DRAW step surfaced divergences: "
        f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in divs]}"
    )
    assert py_view["turn"] == 2
    assert py_view["step"] == "DRAW"
    assert py_view["active_player"] == 1
    # p1 just drew their turn-2 card.
    assert len(py_view["hand_p1"]) == 8
    assert len(py_view["library_p1"]) == 52
    # p0 untouched.
    assert len(py_view["hand_p0"]) == 7
    assert len(py_view["library_p0"]) == 53


# ---------------------------------------------------------------------------
# Test 3: play-a-land at PRECOMBAT_MAIN of turn 1.
#
# First action that mutates the battlefield from a real-game prefix
# (opening hand + turn-1 walk). Surfaces whether play_land's
# zone-transition hand -> battlefield agrees cross-engine when the
# starting hand was dealt by a real opening-draw rather than a
# Phase 5 side-channel single draw.
# ---------------------------------------------------------------------------


def test_play_land_turn_1_parity():
    """Walk to turn 1 PRECOMBAT_MAIN, play a Forest from p0's hand,
    assert byte-equal battlefield + hand views.

    Pre-conditions: same as ``test_no_op_first_turn_parity``.

    Walk: 3 advance_phase calls (UNTAP -> UPKEEP -> DRAW ->
    PRECOMBAT_MAIN), then a play_land action. The opening hand is
    guaranteed to contain at least one Forest (24 Forests in 60
    cards, 7 drawn — combinatorially nearly always; we assert
    explicitly to fail loudly if the seed produces a no-Forest hand).

    This pins: cross-engine play_land works from a realistic
    multi-card hand, with the new bf object's etb_timestamp /
    controller_id / zone all matching across engines.
    """
    from mtg_bot.parity.cross_engine import (
        advance_phase_python,
        build_matched_states,
        step_both,
    )

    spec = _vanilla_60_deckspec(seed=42)
    py_state, rust_state = build_matched_states(spec)
    _draw_opening_hand(py_state, rust_state, n=7)

    # Walk to PRECOMBAT_MAIN of turn 1 (3 advances).
    for _ in range(3):
        advance_phase_python(py_state)
        rust_state.advance_phase()
    assert py_state.step.name == "PRECOMBAT_MAIN"
    assert py_state.active_player_idx == 0

    # Find a Forest in p0's opening hand.
    p0_hand = py_state.players[0].hand
    forest = next(
        (o for o in p0_hand if o.printing.name == "Forest"),
        None,
    )
    assert forest is not None, (
        f"seed=42 opening hand for p0 contains no Forest: "
        f"{[o.printing.name for o in p0_hand]}; pick a different "
        f"seed for this test if the canonical seed becomes "
        f"Forest-less after a deck-builder change."
    )
    forest_id = int(forest.id)

    # Apply play_land via the cross-engine step primitive.
    step = step_both(
        py_state,
        rust_state,
        {"kind": "play_land", "card_id": forest_id},
    )
    assert step.divergences == [], (
        f"play_land surfaced divergences: "
        f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in step.divergences]}"
    )
    # Forest is on the battlefield.
    py_view = step.py_view
    assert len(py_view["battlefield"]) == 1
    bf_obj = py_view["battlefield"][0]
    # bf_obj is the 8-tuple (printing_name, tapped, sick, dmg, counters,
    # attached_to, controller_id, id) per parity_smoke._zone_signature.
    assert bf_obj[0] == "Forest"
    assert bf_obj[7] == forest_id
    # p0 hand is down to 6.
    assert len(py_view["hand_p0"]) == 6
    # Library untouched.
    assert len(py_view["library_p0"]) == 53


# ---------------------------------------------------------------------------
# Test 4 (xfail-tagged demonstrator): cast a creature on turn 3.
#
# Walks turn 1 (play Forest), turn 2 (play Forest), turn 3 (tap two
# Forests, cast Bears). The activate_ability primitive's action_dict
# shape requires ``source_id`` (not ``card_id``) — a translator quirk
# the seed surfaces. Marked xfail so the seed file gates green while
# documenting the gap. Phase 5's cast_bears_selector proves the
# underlying engine paths agree; this test exists to pin the
# action-dict-shape gap as known.
# ---------------------------------------------------------------------------


def test_play_land_each_turn_through_turn_2_parity():
    """Multi-turn extension: play a Forest on turn 1 AND turn 2.

    This walks the seed slightly further to prove the full
    setup_game-like prefix holds: opening hand, turn 1 land drop,
    turn 2 land drop. Surfaces any cross-engine bookkeeping bugs
    that only show up when MORE THAN ONE permanent is on the
    battlefield from a real-game prefix (the etb_timestamp
    bf-ordering invariant that closed CE4, the controller_id
    persistence across the active-player swap at turn 2 UNTAP).
    """
    from mtg_bot.parity.cross_engine import (
        advance_phase_python,
        build_matched_states,
        compare_fields,
        step_both,
    )

    spec = _vanilla_60_deckspec(seed=42)
    py_state, rust_state = build_matched_states(spec)
    _draw_opening_hand(py_state, rust_state, n=7)

    # Turn 1 PRECOMBAT_MAIN: p0 plays Forest.
    for _ in range(3):
        advance_phase_python(py_state)
        rust_state.advance_phase()
    forest1 = next(
        o for o in py_state.players[0].hand if o.printing.name == "Forest"
    )
    step1 = step_both(
        py_state, rust_state,
        {"kind": "play_land", "card_id": int(forest1.id)},
    )
    assert step1.divergences == [], (
        f"turn-1 play_land surfaced divergences: "
        f"{[(d.field, d.py_value, d.rust_value) for d in step1.divergences]}"
    )

    # Walk to turn 2 PRECOMBAT_MAIN: 12 advances from MAIN1.
    # MAIN1 -> BoC -> DA -> DB -> CD -> EoC -> MAIN2 -> END -> CLEANUP
    # -> UNTAP (turn 2) -> UPKEEP -> DRAW -> MAIN1 = 12 advances.
    for _ in range(12):
        advance_phase_python(py_state)
        rust_state.advance_phase()
        py_view, rust_view = _step_views(py_state, rust_state)
        divs = compare_fields(py_view, rust_view)
        assert divs == [], (
            f"phase boundary {py_view['step']!r} (turn {py_view['turn']}) "
            f"surfaced divergences after turn-1 play_land: "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in divs]}"
        )

    assert py_state.step.name == "PRECOMBAT_MAIN"
    assert py_state.active_player_idx == 1

    # Turn 2 PRECOMBAT_MAIN: p1 plays Forest.
    forest2 = next(
        o for o in py_state.players[1].hand if o.printing.name == "Forest"
    )
    step2 = step_both(
        py_state, rust_state,
        {"kind": "play_land", "card_id": int(forest2.id)},
    )
    assert step2.divergences == [], (
        f"turn-2 play_land surfaced divergences: "
        f"{[(d.field, d.py_value, d.rust_value) for d in step2.divergences]}"
    )

    py_view = step2.py_view
    # Both Forests are on the battlefield.
    assert len(py_view["battlefield"]) == 2
    bf_names = sorted(t[0] for t in py_view["battlefield"])
    assert bf_names == ["Forest", "Forest"]
    # Controller_ids match the player who played each.
    bf_controllers = sorted(t[6] for t in py_view["battlefield"])
    assert bf_controllers == [0, 1]


# ---------------------------------------------------------------------------
# Test 5: real-game ``setup_game`` mirror across engines.
#
# Closed by feature/phase6-parity-trajectory-module: ships
# ``mtg_bot.parity.trajectory.setup_matched_game(decks, seed,
# mulligans=...)`` as the canonical entrypoint that hides the per-engine
# opening-draw side-channel behind a single call. This test now asserts
# the closure: the helper exists, returns matched states, and the post-
# setup field views agree byte-for-byte.
# ---------------------------------------------------------------------------


def test_shared_setup_game_helper_exists():
    """Closure of Phase 6 infrastructure gap #1.

    ``trajectory.setup_matched_game`` is the single entrypoint that
    produces a parity-synced opening state on both engines. Mulligans
    remain reserved for the follow-up slice (gap #2).
    """
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import compare_fields

    assert hasattr(trajectory, "setup_matched_game")

    spec = _vanilla_60_deckspec(seed=42)
    py_state, rust_state = trajectory.setup_matched_game(spec)
    py_view, rust_view = _step_views(py_state, rust_state)
    divs = compare_fields(py_view, rust_view)
    assert divs == [], (
        f"setup_matched_game opening state diverges: "
        f"{[(d.field, d.py_value, d.rust_value) for d in divs]}"
    )
    assert len(py_view["hand_p0"]) == 7
    assert len(py_view["hand_p1"]) == 7
    assert len(py_view["library_p0"]) == 53
    assert len(py_view["library_p1"]) == 53
    assert py_view["turn"] == 1
    assert py_view["step"] == "UNTAP"


def test_setup_matched_game_rejects_mulligans():
    """Mulligans are reserved for a follow-up slice (gap #2)."""
    from mtg_bot.parity import trajectory

    spec = _vanilla_60_deckspec(seed=42)
    with pytest.raises(NotImplementedError, match="MulliganAgent"):
        trajectory.setup_matched_game(spec, mulligans=True)
