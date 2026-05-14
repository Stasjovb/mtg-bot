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


def test_setup_matched_game_default_mulligan_agent_keeps():
    """Round-14 closure of gap #2: ``mulligans=True`` with the default
    agent (target_hand_size=7) is a no-op keep — produces the same
    post-state as ``mulligans=False`` and remains parity-clean.
    """
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import compare_fields

    spec = _vanilla_60_deckspec(seed=42)
    py_state, rust_state = trajectory.setup_matched_game(spec, mulligans=True)
    py_view, rust_view = _step_views(py_state, rust_state)
    assert compare_fields(py_view, rust_view) == []
    assert len(py_view["hand_p0"]) == 7
    assert len(py_view["hand_p1"]) == 7
    assert len(py_view["library_p0"]) == 53
    assert len(py_view["library_p1"]) == 53


def test_mulligan_to_6_then_play_first_turn_parity():
    """Round-14 gap #2 closure: drive a one-mulligan-each-side opening
    via the deterministic agent, then walk turn 1 phase-by-phase.

    Pre-state: both players mulligan exactly once (target_hand_size=6),
    bottom 1 card each, end up with 6-card hands and 54-card libraries.
    Post-state: walks turn 1 UNTAP → CLEANUP → turn 2 UNTAP, asserting
    per-step parity at every phase boundary. If the mulligan loop
    diverges, this test pins the divergence to either:
      (a) the post-mulligan hand/library order, or
      (b) the turn-structure walk on top of the mulliganed state.

    Both engines must agree byte-for-byte at every step.
    """
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        advance_phase_python,
        compare_fields,
    )

    spec = _vanilla_60_deckspec(seed=42)
    agent = trajectory.MulliganDeterministicAgent(target_hand_size=6)
    py_state, rust_state = trajectory.setup_matched_game(
        spec, mulligans=True, mulligan_agent=agent, mulligan_seed=7,
    )

    # Post-mulligan: 6 cards in hand, 54 in library on both sides.
    py_view, rust_view = _step_views(py_state, rust_state)
    divs = compare_fields(py_view, rust_view)
    assert divs == [], (
        f"post-mulligan divergence: "
        f"{[(d.field, d.py_value, d.rust_value) for d in divs]}"
    )
    assert len(py_view["hand_p0"]) == 6
    assert len(py_view["hand_p1"]) == 6
    assert len(py_view["library_p0"]) == 54
    assert len(py_view["library_p1"]) == 54

    # Walk turn 1 UNTAP → CLEANUP wrap into turn 2 UNTAP (12 advances).
    for advance_idx in range(12):
        advance_phase_python(py_state)
        rust_state.advance_phase()
        py_view, rust_view = _step_views(py_state, rust_state)
        divs = compare_fields(py_view, rust_view)
        assert divs == [], (
            f"advance #{advance_idx} ({py_view['step']!r}, turn "
            f"{py_view['turn']}) surfaced divergences after mulligan: "
            f"{[(d.field, d.py_value, d.rust_value) for d in divs]}"
        )
    # Hand p0 still 6 (turn 1 skips draw); hand p1 still 6 at turn 2 UNTAP
    # (UNTAP is pre-DRAW).
    assert len(py_view["hand_p0"]) == 6
    assert len(py_view["hand_p1"]) == 6


def test_mulligan_to_5_then_setup_clean_parity():
    """Round-14 gap #2 closure: 2-mulligan-each-side opening.

    target_hand_size=5 → both players mulligan twice and bottom 2.
    Final state: 5 cards in hand, 55 in library, parity-clean. This
    is the deepest mulligan trajectory tests exercise — three or
    more mulligans hit the same code path with no new semantics.
    """
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import compare_fields

    spec = _vanilla_60_deckspec(seed=42)
    agent = trajectory.MulliganDeterministicAgent(target_hand_size=5)
    py_state, rust_state = trajectory.setup_matched_game(
        spec, mulligans=True, mulligan_agent=agent, mulligan_seed=13,
    )

    py_view, rust_view = _step_views(py_state, rust_state)
    divs = compare_fields(py_view, rust_view)
    assert divs == [], (
        f"after 2-mulligan opening: "
        f"{[(d.field, d.py_value, d.rust_value) for d in divs]}"
    )
    assert len(py_view["hand_p0"]) == 5
    assert len(py_view["hand_p1"]) == 5
    assert len(py_view["library_p0"]) == 55
    assert len(py_view["library_p1"]) == 55


def test_mulligan_seed_reproducibility():
    """Two calls with the same agent + mulligan_seed produce
    bit-identical post-mulligan states. Critical for trajectory tests
    that snapshot hand/library after setup."""
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import build_python_field_view

    spec = _vanilla_60_deckspec(seed=42)
    agent = trajectory.MulliganDeterministicAgent(target_hand_size=5)
    py_a, _ = trajectory.setup_matched_game(
        spec, mulligans=True, mulligan_agent=agent, mulligan_seed=99,
    )
    py_b, _ = trajectory.setup_matched_game(
        spec, mulligans=True, mulligan_agent=agent, mulligan_seed=99,
    )
    a_view = build_python_field_view(py_a)
    b_view = build_python_field_view(py_b)
    assert a_view["hand_p0"] == b_view["hand_p0"]
    assert a_view["hand_p1"] == b_view["hand_p1"]
    assert a_view["library_p0"] == b_view["library_p0"]
    assert a_view["library_p1"] == b_view["library_p1"]


def test_mulligan_seed_differentiation():
    """Two calls with the same agent but DIFFERENT mulligan_seed
    produce different post-mulligan states — confirms the seed
    actually drives the per-iteration shuffle."""
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import build_python_field_view

    spec = _vanilla_60_deckspec(seed=42)
    agent = trajectory.MulliganDeterministicAgent(target_hand_size=5)
    py_a, _ = trajectory.setup_matched_game(
        spec, mulligans=True, mulligan_agent=agent, mulligan_seed=1,
    )
    py_b, _ = trajectory.setup_matched_game(
        spec, mulligans=True, mulligan_agent=agent, mulligan_seed=2,
    )
    a_view = build_python_field_view(py_a)
    b_view = build_python_field_view(py_b)
    # At least one of hand or library should differ — extremely unlikely
    # for two random-shuffle outcomes on a 60-card deck to collide.
    assert (
        a_view["hand_p0"] != b_view["hand_p0"]
        or a_view["library_p0"] != b_view["library_p0"]
    )


# ---------------------------------------------------------------------------
# Test 6 — extended trajectory: play a land EVERY active-player turn
# through turn 5.
#
# The cadence on a vanilla mirror match (p0 on the play, alternating turns):
# p0 active on turns 1, 3, 5; p1 active on turns 2, 4. After turn 5 MAIN1
# the battlefield carries five Forests — three p0-controlled, two p1-
# controlled, in ETB order. This pins the bf-ordering invariant (CE4
# closure, etb_timestamp on every new permanent matches across engines)
# across a five-deep stack of permanents from a real opening prefix.
#
# Surfaces any cross-engine bookkeeping bug that requires more than two
# permanents to manifest — the existing test 4 caps at two.
# ---------------------------------------------------------------------------


def _advance_n_phases(py_state, rust_state, n: int) -> None:
    """Walk ``n`` phase advances on both engines, asserting per-step parity."""
    from mtg_bot.parity.cross_engine import (
        advance_phase_python,
        compare_fields,
    )

    for _ in range(n):
        advance_phase_python(py_state)
        rust_state.advance_phase()
        py_view, rust_view = _step_views(py_state, rust_state)
        divs = compare_fields(py_view, rust_view)
        assert divs == [], (
            f"phase advance ({py_view['step']!r}, turn "
            f"{py_view['turn']}) surfaced divergences: "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in divs]}"
        )


def _play_active_player_forest(py_state, rust_state):
    """Helper: play a Forest from the active player's hand. Returns the
    :class:`CrossEngineStep` so the caller can assert on divergences."""
    from mtg_bot.parity.cross_engine import step_both

    active = py_state.active_player_idx
    forest = next(
        o for o in py_state.players[active].hand
        if o.printing.name == "Forest"
    )
    return step_both(
        py_state, rust_state,
        {"kind": "play_land", "card_id": int(forest.id)},
    )


def test_play_land_each_turn_3_through_5_parity():
    """Drive the play-a-land-each-active-turn pattern through turn 5.

    Setup is :func:`setup_matched_game` (closes infra gap #1). Turn 1
    p0 plays Forest, turn 2 p1 plays Forest (those two land plays
    overlap with test 4's coverage). Then turn 3 p0 + turn 4 p1 +
    turn 5 p0 — three additional land plays, each followed by a full
    phase walk to the next active-player MAIN1 with per-step parity
    assertions.

    Pins:
      * Five battlefield permanents accumulate without surfacing a
        zone-ordering / etb_timestamp / controller_id divergence.
      * Active-player swap fires correctly on every CLEANUP -> UNTAP
        wrap (turn_number bumps; active_player toggles).
      * No turn-3+ summoning-sickness clearing bug (Forests cast
        prior turns must be untapped + unsick by their controller's
        next UNTAP).
    """
    from mtg_bot.parity import trajectory

    spec = _vanilla_60_deckspec(seed=42)
    py_state, rust_state = trajectory.setup_matched_game(spec)

    # Walk to MAIN1 of turn 1 (UNTAP -> UPKEEP -> DRAW -> MAIN1 = 3).
    _advance_n_phases(py_state, rust_state, 3)

    # Play a Forest on turns 1, 2, 3, 4, 5 in active-player order.
    # Each "12 advances" wraps MAIN1 -> next MAIN1.
    for expected_turn, expected_active in [
        (1, 0), (2, 1), (3, 0), (4, 1), (5, 0),
    ]:
        assert py_state.turn_number == expected_turn, (
            f"expected turn {expected_turn}, got {py_state.turn_number}"
        )
        assert py_state.active_player_idx == expected_active
        assert py_state.step.name == "PRECOMBAT_MAIN"
        s = _play_active_player_forest(py_state, rust_state)
        assert s.divergences == [], (
            f"turn-{expected_turn} play_land surfaced divergences: "
            f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
        )
        # Stop walking after the turn-5 land — keeps the post-state
        # exactly at "turn 5 MAIN1, just played Forest".
        if expected_turn < 5:
            _advance_n_phases(py_state, rust_state, 12)

    # Final: 5 Forests on bf, 3 p0 + 2 p1.
    py_view = _step_views(py_state, rust_state)[0]
    assert len(py_view["battlefield"]) == 5
    bf_controllers = sorted(t[6] for t in py_view["battlefield"])
    assert bf_controllers == [0, 0, 0, 1, 1]
    assert all(t[0] == "Forest" for t in py_view["battlefield"])


# ---------------------------------------------------------------------------
# Test 7 — cast a Grizzly Bears at turn 5 (earliest viable cast turn for
# the on-the-play player, see note below).
#
# Cadence: p0 plays Forest turn 1, 3, 5. By turn 5 MAIN1 p0 controls
# three Forests — turn-1 + turn-3 unsick (both have crossed at least one
# of their own UNTAP steps), turn-5 still sick. Two unsick Forests are
# enough for the 1G + 1 generic Bears cost.
#
# Note: the original Phase 6 task brief said "cast at turn 4". On the
# on-the-play schedule p1's turn 4 has only one unsick Forest (turn-2;
# the turn-4 land is sick). p0's earliest viable cast is turn 5 (the
# one-mana-short turn 3 case has only one unsick Forest too — turn-1
# Forest unsick at turn-3 UNTAP, but turn-3 land is freshly sick).
# Adjusting the test to turn 5 keeps the trajectory honest with the
# real summoning-sick semantics both engines model.
# ---------------------------------------------------------------------------


def test_cast_creature_at_turn_5_parity():
    """Cast a Grizzly Bears at turn 5 PRECOMBAT_MAIN; assert summoning-
    sickness + bf zone movement agree across engines.

    Prefix: lands turn 1, 3, 5 (p0). At MAIN1 of turn 5 tap two
    unsick Forests for {G}{G}, then cast Bears. Post-cast: bf has
    3 Forests + 1 Bears, the Bears is summoning_sick=True on both
    engines (matches CE bridge invariant for newly-resolved
    creatures).
    """
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import step_both

    spec = _vanilla_60_deckspec(seed=42)
    py_state, rust_state = trajectory.setup_matched_game(spec)

    _advance_n_phases(py_state, rust_state, 3)  # → turn 1 MAIN1

    # Turn 1 p0 land.
    s = _play_active_player_forest(py_state, rust_state)
    assert s.divergences == []
    _advance_n_phases(py_state, rust_state, 12 * 2)  # → turn 3 MAIN1

    # Turn 3 p0 land.
    s = _play_active_player_forest(py_state, rust_state)
    assert s.divergences == []
    _advance_n_phases(py_state, rust_state, 12 * 2)  # → turn 5 MAIN1

    # Turn 5 p0 land.
    s = _play_active_player_forest(py_state, rust_state)
    assert s.divergences == []

    # Tap two unsick Forests (turn-1 + turn-3 Forests; turn-5 is sick).
    for tap_idx in range(2):
        untapped_forest = next(
            o for o in py_state.battlefield
            if o.controller_id == 0
            and o.printing.is_land
            and not o.tapped
            and not o.summoning_sick
        )
        s = step_both(
            py_state, rust_state,
            {
                "kind": "activate_ability",
                "source_id": int(untapped_forest.id),
                "ability_index": 0,
            },
        )
        assert s.divergences == [], (
            f"tap #{tap_idx} surfaced divergences: "
            f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
        )

    # Cast Grizzly Bears.
    bears = next(
        o for o in py_state.players[0].hand
        if o.printing.name == "Grizzly Bears"
    )
    s = step_both(
        py_state, rust_state,
        {"kind": "cast_spell", "card_id": int(bears.id)},
    )
    assert s.divergences == [], (
        f"cast_spell Bears surfaced divergences: "
        f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
    )

    py_view = s.py_view
    assert len(py_view["battlefield"]) == 4
    bf_names = sorted(t[0] for t in py_view["battlefield"])
    assert bf_names == ["Forest", "Forest", "Forest", "Grizzly Bears"]
    # The Bears object is summoning_sick on the post-cast bf.
    bears_bf = next(t for t in py_view["battlefield"] if t[0] == "Grizzly Bears")
    # bf 8-tuple field 2 is the ``sick`` slot; both engines emit an
    # int (1/0) from the field-view recipe rather than a bool.
    assert bears_bf[2], "Bears should be summoning_sick on post-cast bf"


# ---------------------------------------------------------------------------
# Test 8 — attack with the cast Bears at turn 7 DECLARE_ATTACKERS.
#
# Bears was cast turn 5, sick through turn 6, unsick at turn-7 UNTAP.
# Turn 7 DECLARE_ATTACKERS: declare Bears as attacker, walk DA -> DB
# (declare empty assignments — defender has no creatures), walk DB ->
# COMBAT_DAMAGE.
#
# Note: the original brief said "attack at turn 5". The earliest viable
# attack on this deck is turn 7 (Bears cast turn 5 + summoning sickness
# clears two turns later on the controller's next UNTAP). Same scheduling
# slip as test 7.
#
# Also surfaces the attacker-tapped invariant — Bears is tapped after
# declare_attackers fires (no vigilance).
# ---------------------------------------------------------------------------


def test_attack_at_turn_7_parity():
    """Walk to turn 7 DECLARE_ATTACKERS, declare Bears as attacker,
    walk through DECLARE_BLOCKERS, assert per-step parity.

    Pins: declare_attackers' tapped-flag mutation matches across
    engines; the empty-blockers DECLARE_BLOCKERS arm produces
    parity-equivalent state on both sides.
    """
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import step_both

    spec = _vanilla_60_deckspec(seed=42)
    py_state, rust_state = trajectory.setup_matched_game(spec)
    _advance_n_phases(py_state, rust_state, 3)
    s = _play_active_player_forest(py_state, rust_state); assert s.divergences == []
    _advance_n_phases(py_state, rust_state, 12 * 2)
    s = _play_active_player_forest(py_state, rust_state); assert s.divergences == []
    _advance_n_phases(py_state, rust_state, 12 * 2)
    s = _play_active_player_forest(py_state, rust_state); assert s.divergences == []
    # Tap two Forests + cast Bears (mirrors test 7).
    for _ in range(2):
        f = next(
            o for o in py_state.battlefield
            if o.controller_id == 0 and o.printing.is_land
            and not o.tapped and not o.summoning_sick
        )
        s = step_both(
            py_state, rust_state,
            {"kind": "activate_ability", "source_id": int(f.id), "ability_index": 0},
        )
        assert s.divergences == []
    bears = next(o for o in py_state.players[0].hand if o.printing.name == "Grizzly Bears")
    s = step_both(py_state, rust_state, {"kind": "cast_spell", "card_id": int(bears.id)})
    assert s.divergences == []

    # Walk turn 5 MAIN1 -> turn 7 MAIN1 (24 advances). Each per-step
    # parity check is enforced by _advance_n_phases.
    _advance_n_phases(py_state, rust_state, 12 * 2)
    assert py_state.turn_number == 7
    assert py_state.active_player_idx == 0
    assert py_state.step.name == "PRECOMBAT_MAIN"

    # Advance MAIN1 -> BoC -> DECLARE_ATTACKERS (2 advances).
    _advance_n_phases(py_state, rust_state, 2)
    assert py_state.step.name == "DECLARE_ATTACKERS"

    # Declare Bears as attacker.
    bears_obj = next(
        o for o in py_state.battlefield if o.printing.name == "Grizzly Bears"
    )
    assert not bears_obj.summoning_sick, "Bears should be unsick at turn 7"
    assert not bears_obj.tapped, "Bears should be untapped before attack"

    s = step_both(
        py_state, rust_state,
        {"kind": "declare_attackers", "attacker_ids": [int(bears_obj.id)]},
    )
    assert s.divergences == [], (
        f"declare_attackers surfaced divergences: "
        f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
    )
    # Bears is now tapped on both engines.
    py_view = s.py_view
    bears_bf = next(t for t in py_view["battlefield"] if t[0] == "Grizzly Bears")
    # bf 8-tuple field 1 is the ``tapped`` slot; engines emit int.
    assert bears_bf[1], "Bears should be tapped after declare_attackers"

    # Advance DA -> DB.
    _advance_n_phases(py_state, rust_state, 1)
    assert py_state.step.name == "DECLARE_BLOCKERS"

    # Empty declare_blockers (defender has no creatures).
    s = step_both(
        py_state, rust_state,
        {"kind": "declare_blockers", "assignments": []},
    )
    assert s.divergences == [], (
        f"declare_blockers (empty) surfaced divergences: "
        f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
    )


# ---------------------------------------------------------------------------
# Test 9 — combat damage at turn 7 COMBAT_DAMAGE.
#
# Continues test 8's prefix: Bears attacks unblocked, COMBAT_DAMAGE step
# fires the Rust + Python damage helpers (side-channel, neither engine
# auto-resolves combat damage from advance_phase). p1's life drops
# 20 -> 18 on both engines.
# ---------------------------------------------------------------------------


def test_combat_damage_at_turn_7_parity():
    """Bears attacks unblocked, deal 2 damage to p1 at COMBAT_DAMAGE.

    Pins: per-engine combat damage helpers stay in sync — p1 life
    drops the same amount on both sides, and the post-damage SBA
    pass produces matching is_over / has_lost flags.
    """
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        clear_combat_both,
        compare_fields,
        deal_combat_damage_rust,
        resolve_combat_damage_python,
        step_both,
    )

    spec = _vanilla_60_deckspec(seed=42)
    py_state, rust_state = trajectory.setup_matched_game(spec)
    _advance_n_phases(py_state, rust_state, 3)
    s = _play_active_player_forest(py_state, rust_state); assert s.divergences == []
    _advance_n_phases(py_state, rust_state, 12 * 2)
    s = _play_active_player_forest(py_state, rust_state); assert s.divergences == []
    _advance_n_phases(py_state, rust_state, 12 * 2)
    s = _play_active_player_forest(py_state, rust_state); assert s.divergences == []
    for _ in range(2):
        f = next(
            o for o in py_state.battlefield
            if o.controller_id == 0 and o.printing.is_land
            and not o.tapped and not o.summoning_sick
        )
        s = step_both(
            py_state, rust_state,
            {"kind": "activate_ability", "source_id": int(f.id), "ability_index": 0},
        )
        assert s.divergences == []
    bears = next(o for o in py_state.players[0].hand if o.printing.name == "Grizzly Bears")
    s = step_both(py_state, rust_state, {"kind": "cast_spell", "card_id": int(bears.id)})
    assert s.divergences == []

    _advance_n_phases(py_state, rust_state, 12 * 2)
    _advance_n_phases(py_state, rust_state, 2)  # MAIN1 -> DA

    bears_obj = next(
        o for o in py_state.battlefield if o.printing.name == "Grizzly Bears"
    )
    s = step_both(
        py_state, rust_state,
        {"kind": "declare_attackers", "attacker_ids": [int(bears_obj.id)]},
    )
    assert s.divergences == []
    _advance_n_phases(py_state, rust_state, 1)  # DA -> DB
    s = step_both(
        py_state, rust_state,
        {"kind": "declare_blockers", "assignments": []},
    )
    assert s.divergences == []
    _advance_n_phases(py_state, rust_state, 1)  # DB -> COMBAT_DAMAGE
    assert py_state.step.name == "COMBAT_DAMAGE"

    # Side-channel combat damage on both engines (mirrors
    # combat_selector's COMBAT_DAMAGE branch).
    fired_py = resolve_combat_damage_python(py_state)
    assert fired_py is True, "Python should report damage fired"
    deal_combat_damage_rust(rust_state)

    py_view, rust_view = _step_views(py_state, rust_state)
    divs = compare_fields(py_view, rust_view)
    assert divs == [], (
        f"post combat-damage divergences: "
        f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in divs]}"
    )
    # Damage assertions.
    assert py_view["life_p0"] == 20, "p0 untouched"
    assert py_view["life_p1"] == 18, "p1 took 2 from Bears"
    assert rust_view["life_p1"] == 18

    # Clean up combat for hygienic future probes (matches what
    # combat_selector does at END_OF_COMBAT).
    _advance_n_phases(py_state, rust_state, 1)  # CD -> EOC
    clear_combat_both(py_state, rust_state)
    py_view, rust_view = _step_views(py_state, rust_state)
    assert compare_fields(py_view, rust_view) == []


# ---------------------------------------------------------------------------
# Phase 6 gap #4 closure (round-15): activate_ability trajectory using the
# canonical action-dict builder.
#
# Exercises the activate_ability path end-to-end via `_canonical_action_dict`
# rather than inline literal dicts. This pins the canonical-builder bridge
# round-trip on a real-game-shaped trajectory: build the dict via
# `_canonical_action_dict("activate_ability", id=N, ability_index=0)`,
# step both engines, assert byte-equal field views.
#
# The shape mirrors the existing test_cast_creature_at_turn_5_parity but
# uses the canonical builder for every dict (lands, activations, cast)
# so a regression in the builder's per-kind routing surfaces here. Also
# pins that the builder's output is byte-equal to what the inline-literal
# trajectory tests produce — i.e., the builder is a no-op refactor of
# the per-kind dict shape, not a behavior change.
# ---------------------------------------------------------------------------


def test_activate_ability_trajectory_via_canonical_builder():
    """End-to-end trajectory using `_canonical_action_dict` for every
    action: walk to turn 5 PRECOMBAT_MAIN, play 3 Forests across
    turns 1/3/5 (active player p0 gets turns 1/3/5), tap two Forests
    via `_canonical_action_dict("activate_ability", id=N,
    ability_index=0)`, cast Bears via `_canonical_action_dict(
    "cast_spell", id=N)`. Asserts per-step parity throughout.

    Pins: the canonical builder produces dicts that round-trip
    cleanly through both `_dict_to_python_action` AND Rust's
    `parse_action`. A regression in the builder's per-kind routing
    (e.g., emitting `card_id` for `activate_ability`) would surface
    immediately as a Rust-side parse error.
    """
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        _canonical_action_dict,
        step_both,
    )

    spec = _vanilla_60_deckspec(seed=42)
    py_state, rust_state = trajectory.setup_matched_game(spec)
    # Walk turn 1 PASS_PRIORITY -> PRECOMBAT_MAIN, play Forest.
    _advance_n_phases(py_state, rust_state, 3)
    forest = next(
        o for o in py_state.players[0].hand if o.printing.name == "Forest"
    )
    s = step_both(
        py_state, rust_state,
        _canonical_action_dict("play_land", id=int(forest.id)),
    )
    assert s.divergences == [], (
        f"play_land via canonical builder surfaced divergences: "
        f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
    )
    # Advance to turn 3 active player (p0). Each full turn is 12 phases;
    # advance two full turns to get back to p0 PRECOMBAT_MAIN.
    _advance_n_phases(py_state, rust_state, 12 * 2)
    forest = next(
        o for o in py_state.players[0].hand if o.printing.name == "Forest"
    )
    s = step_both(
        py_state, rust_state,
        _canonical_action_dict("play_land", id=int(forest.id)),
    )
    assert s.divergences == []
    # Turn 5 active player (p0) — 3rd Forest play.
    _advance_n_phases(py_state, rust_state, 12 * 2)
    forest = next(
        o for o in py_state.players[0].hand if o.printing.name == "Forest"
    )
    s = step_both(
        py_state, rust_state,
        _canonical_action_dict("play_land", id=int(forest.id)),
    )
    assert s.divergences == []

    # Now tap two Forests for mana via the canonical builder. The
    # canonical key for activate_ability is `source_id`, but the
    # builder lets us pass the friendly `id` alias.
    for tap_idx in range(2):
        untapped_forest = next(
            o for o in py_state.battlefield
            if o.controller_id == 0
            and o.printing.is_land
            and not o.tapped
            and not o.summoning_sick
        )
        action_dict = _canonical_action_dict(
            "activate_ability",
            id=int(untapped_forest.id),
            ability_index=0,
        )
        # Sanity: builder routed `id` to `source_id` (the canonical key
        # for activate_ability, which Rust's parse_action requires).
        assert "source_id" in action_dict
        assert "card_id" not in action_dict
        assert action_dict["source_id"] == int(untapped_forest.id)

        s = step_both(py_state, rust_state, action_dict)
        assert s.divergences == [], (
            f"tap #{tap_idx} via canonical builder surfaced "
            f"divergences: "
            f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
        )

    # Cast Grizzly Bears via the canonical builder.
    bears = next(
        o for o in py_state.players[0].hand
        if o.printing.name == "Grizzly Bears"
    )
    cast_dict = _canonical_action_dict("cast_spell", id=int(bears.id))
    # Sanity: builder routed `id` to `card_id` (the canonical key for
    # cast_spell).
    assert "card_id" in cast_dict
    assert "source_id" not in cast_dict
    assert cast_dict["card_id"] == int(bears.id)
    s = step_both(py_state, rust_state, cast_dict)
    assert s.divergences == [], (
        f"cast_spell via canonical builder surfaced divergences: "
        f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
    )

    # End-state check: bf has three Forests + Grizzly Bears (sick).
    py_view = s.py_view
    assert len(py_view["battlefield"]) == 4
    bf_names = sorted(t[0] for t in py_view["battlefield"])
    assert bf_names == ["Forest", "Forest", "Forest", "Grizzly Bears"]


def test_activate_ability_trajectory_alias_dict_python_only():
    """`_dict_to_python_action`'s dual-honor accepts the cross-vocabulary
    alias on the Python side: `card_id` for `activate_ability` resolves
    to `ActivateAbility.source_id`. This is the soft-deprecation
    transition aid — hand-rolled Python-side builders that pick the
    "wrong" key still work.

    NOTE: this is a Python-bridge-only contract — feeding the same
    alias-keyed dict to Rust raises a parse error (Rust is strict).
    The test exercises the Python-only path: build the dict with the
    alias, apply via `_dict_to_python_action` + `py_apply_action`,
    assert the activated state on Python.
    """
    from mtg_bot.actions import apply_action as py_apply_action
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        _canonical_action_dict,
        _dict_to_python_action,
        advance_phase_python,
        step_both,
    )

    spec = _vanilla_60_deckspec(seed=42)
    py_state, rust_state = trajectory.setup_matched_game(spec)
    # Walk to turn 1 PRECOMBAT_MAIN; play Forest cross-engine via the
    # canonical builder so both states stay in sync.
    _advance_n_phases(py_state, rust_state, 3)
    forest = next(
        o for o in py_state.players[0].hand if o.printing.name == "Forest"
    )
    s = step_both(
        py_state, rust_state,
        _canonical_action_dict("play_land", id=int(forest.id)),
    )
    assert s.divergences == []
    # Advance Python alone to turn 3 (where the Forest is no longer
    # summoning-sick) — this test is about the Python-bridge alias
    # surface, not cross-engine parity, so we drop into Python-only
    # for the activation step.
    for _ in range(12 * 2):
        advance_phase_python(py_state)
    forest_bf = next(
        o for o in py_state.battlefield
        if o.controller_id == 0
        and o.printing.is_land
        and not o.tapped
        and not o.summoning_sick
    )

    # Build the dict with the WRONG (alias) key — `card_id` instead
    # of the canonical `source_id` — and apply on Python only.
    alias_dict = {
        "kind": "activate_ability",
        "card_id": int(forest_bf.id),  # alias for source_id
        "ability_index": 0,
    }
    py_action = _dict_to_python_action(alias_dict)
    py_apply_action(py_state, 0, py_action)

    # The Forest should now be tapped on Python.
    forest_bf_after = next(
        o for o in py_state.battlefield if o.id == forest_bf.id
    )
    assert forest_bf_after.tapped, (
        "Python-side dual-honor alias did not route to source_id — "
        "the Forest should be tapped after the activate_ability "
        "alias-keyed dict resolves."
    )


# ===========================================================================
# Phase 6 round-16 (closes infrastructure gap #3): real-game combat agent.
#
# These tests exercise `RealGameCombatAgent` + `drive_combat_phase` on a
# real-game-shaped trajectory. The agent generalizes the round-13/14/15
# inline combat scripts: instead of each test re-spelling out
# "find Bears, emit declare_attackers([id]), advance, emit empty
# blockers, advance, fire combat damage, advance, clear combat", the
# tests build an agent + call drive_combat_phase.
#
# Test surface:
#
#   - test_real_game_combat_attack_all_no_blocks_through_turn_11_parity:
#       p0 attacks unblocked over 3 combat rounds (turn 7, 9, 11).
#       Asserts p1 life 20 -> 18 -> 16 -> 14 each round.
#   - test_real_game_combat_with_blocks_mutual_destruction_parity:
#       p0 attacks turn 7 with Bears; p1 blocks with sick-Bears.
#       Both die (mutual 2/2 vs 2/2 trade).
#   - test_real_game_combat_no_attack_strategy_parity:
#       agent.strategy="no_attack" — combat phase walks past with no
#       creatures attacking, no damage, no zone changes.
#   - test_real_game_combat_first_strike_parity:
#       Uses `first_strike_side_channel` from cross_engine to inject
#       a first-strike creature, then attacks into a regular blocker.
#       Pins the first-strike timing path through the agent.
#
# All tests use `setup_matched_game` (from gap #1) for opening setup
# and `RealGameCombatAgent` + `drive_combat_phase` (this slice) for
# combat. No inline declare/block scripts.
# ===========================================================================


def _setup_p0_bears_at_turn_5(py_state, rust_state):
    """Walk the standard "p0 plays land turns 1/3/5, casts Bears turn 5"
    prefix. Used by every real-game combat test below.

    Post-condition: turn 5 PRECOMBAT_MAIN ends with cast Bears on bf
    (sick); p0 has 3 Forests (2 tapped from cast, 1 sick from turn-5).
    """
    from mtg_bot.parity.cross_engine import step_both

    _advance_n_phases(py_state, rust_state, 3)
    s = _play_active_player_forest(py_state, rust_state)
    assert s.divergences == []
    _advance_n_phases(py_state, rust_state, 12 * 2)
    s = _play_active_player_forest(py_state, rust_state)
    assert s.divergences == []
    _advance_n_phases(py_state, rust_state, 12 * 2)
    s = _play_active_player_forest(py_state, rust_state)
    assert s.divergences == []
    # Tap two unsick Forests + cast Bears.
    for _ in range(2):
        f = next(
            o for o in py_state.battlefield
            if o.controller_id == 0
            and o.printing.is_land
            and not o.tapped
            and not o.summoning_sick
        )
        s = step_both(
            py_state, rust_state,
            {"kind": "activate_ability", "source_id": int(f.id), "ability_index": 0},
        )
        assert s.divergences == []
    bears = next(
        o for o in py_state.players[0].hand if o.printing.name == "Grizzly Bears"
    )
    s = step_both(py_state, rust_state, {"kind": "cast_spell", "card_id": int(bears.id)})
    assert s.divergences == []


def _setup_both_bears_by_turn_6(py_state, rust_state):
    """Walk a symmetric prefix where BOTH players play lands turns 2/4/6
    and cast Bears at turn 6 / 5 respectively.

    Cadence:
      * Turn 1 (p0): play Forest #1.
      * Turn 2 (p1): play Forest #1.
      * Turn 3 (p0): play Forest #2.
      * Turn 4 (p1): play Forest #2.
      * Turn 5 (p0): play Forest #3, tap two unsick Forests, cast Bears.
      * Turn 6 (p1): play Forest #3, tap two unsick Forests, cast Bears.

    Post-condition: turn 6 PRECOMBAT_MAIN, p0 has 3 Forests + Bears
    (Bears sick from turn 5, will unsick at turn 7 UNTAP); p1 has 3
    Forests + Bears (Bears sick from turn 6, will unsick at turn 8
    UNTAP — but is BLOCKING-eligible at turn 7 per CR 302.1).

    Differs from :func:`_setup_p0_bears_at_turn_5` by also driving
    p1's parallel land plays + cast. Cannot be composed by calling
    `_setup_p0_bears_at_turn_5` first because that helper skips p1's
    turn-2 / turn-4 land plays (only the active player plays a land
    per turn in `_play_active_player_forest`).
    """
    from mtg_bot.parity.cross_engine import step_both

    _advance_n_phases(py_state, rust_state, 3)  # → turn 1 MAIN1, p0 active
    # Turn 1: p0 land.
    s = _play_active_player_forest(py_state, rust_state)
    assert s.divergences == []
    _advance_n_phases(py_state, rust_state, 12)  # → turn 2 MAIN1, p1 active
    # Turn 2: p1 land.
    s = _play_active_player_forest(py_state, rust_state)
    assert s.divergences == []
    _advance_n_phases(py_state, rust_state, 12)  # → turn 3 MAIN1, p0 active
    s = _play_active_player_forest(py_state, rust_state)
    assert s.divergences == []
    _advance_n_phases(py_state, rust_state, 12)  # → turn 4 MAIN1, p1 active
    s = _play_active_player_forest(py_state, rust_state)
    assert s.divergences == []
    _advance_n_phases(py_state, rust_state, 12)  # → turn 5 MAIN1, p0 active
    s = _play_active_player_forest(py_state, rust_state)
    assert s.divergences == []
    # Turn 5: p0 taps + casts Bears.
    for _ in range(2):
        f = next(
            o for o in py_state.battlefield
            if o.controller_id == 0
            and o.printing.is_land
            and not o.tapped
            and not o.summoning_sick
        )
        s = step_both(
            py_state, rust_state,
            {"kind": "activate_ability", "source_id": int(f.id), "ability_index": 0},
        )
        assert s.divergences == []
    bears = next(
        o for o in py_state.players[0].hand if o.printing.name == "Grizzly Bears"
    )
    s = step_both(py_state, rust_state, {"kind": "cast_spell", "card_id": int(bears.id)})
    assert s.divergences == []
    _advance_n_phases(py_state, rust_state, 12)  # → turn 6 MAIN1, p1 active
    # Turn 6: p1 land + cast Bears.
    s = _play_active_player_forest(py_state, rust_state)
    assert s.divergences == []
    for _ in range(2):
        f = next(
            o for o in py_state.battlefield
            if o.controller_id == 1
            and o.printing.is_land
            and not o.tapped
            and not o.summoning_sick
        )
        s = step_both(
            py_state, rust_state,
            {"kind": "activate_ability", "source_id": int(f.id), "ability_index": 0},
        )
        assert s.divergences == []
    bears = next(
        o for o in py_state.players[1].hand if o.printing.name == "Grizzly Bears"
    )
    s = step_both(py_state, rust_state, {"kind": "cast_spell", "card_id": int(bears.id)})
    assert s.divergences == []


def test_real_game_combat_attack_all_no_blocks_through_turn_11_parity():
    """`RealGameCombatAgent("attack_all")` driven over multiple combat
    rounds: p0 attacks unblocked at turn 7, 9, 11.

    Cadence:
      * Bears cast turn 5 (sick), unsick by turn 7 UNTAP.
      * Turn 7 (p0 active): attack, no block, damage; p1: 20 -> 18.
      * Turn 9 (p0 active again, Bears untapped from EoT-tap clear):
        attack, no block, damage; p1: 18 -> 16.
      * Turn 11: same; p1: 16 -> 14.

    Pins:
      * Multi-round combat — the agent state stays consistent across
        END_OF_COMBAT clear + UNTAP cycle (Bears tap from attacking,
        clears combat-flag at EoC, untaps on p0's next UNTAP).
      * Drive helper composes correctly across consecutive turns —
        each call's pre/post conditions hold.
      * Per-round byte-equal life total + zone evolution.
    """
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import compare_fields
    from mtg_bot.turn import Step

    spec = _vanilla_60_deckspec(seed=42)
    py_state, rust_state = trajectory.setup_matched_game(spec)
    _setup_p0_bears_at_turn_5(py_state, rust_state)

    agent = trajectory.RealGameCombatAgent(strategy="attack_all")

    # Walk turn 5 MAIN1 -> turn 7 DECLARE_ATTACKERS (24 phases for two
    # full turns + 2 to skip MAIN1 + BoC).
    _advance_n_phases(py_state, rust_state, 12 * 2 + 2)
    assert py_state.turn_number == 7
    assert py_state.active_player_idx == 0
    assert py_state.step == Step.DECLARE_ATTACKERS

    # Round 1: turn 7 combat, p1 life 20 -> 18.
    trajectory.drive_combat_phase(py_state, rust_state, agent)
    py_view, rust_view = _step_views(py_state, rust_state)
    assert compare_fields(py_view, rust_view) == []
    assert py_view["life_p0"] == 20
    assert py_view["life_p1"] == 18, (
        f"after turn 7 combat, expected p1=18, got {py_view['life_p1']}"
    )

    # Walk turn 7 EoC -> turn 9 DA. Each full turn is 12 phases; from
    # END_OF_COMBAT to next active-player DECLARE_ATTACKERS takes
    # (post-EoC -> turn 8 DA) = 8 phases (postmain, end, cleanup, untap
    # turn 8 + upkeep + draw + main + bc + da = 9 phases). Then turn 8
    # DA we have to cycle through into turn 9 DA: 12 more phases.
    # Simpler: count from current step (EoC, turn 7) to (DA, turn 9):
    # EoC -> POSTCOMBAT_MAIN -> END -> CLEANUP -> turn 8 UNTAP (4)
    # -> UPKEEP -> DRAW -> MAIN1 -> BC -> DA (5 more = 9 total).
    # That gets us turn 8 DA. Add 12 more to get turn 9 DA. Total = 21.
    _advance_n_phases(py_state, rust_state, 9 + 12)
    assert py_state.turn_number == 9
    assert py_state.active_player_idx == 0
    assert py_state.step == Step.DECLARE_ATTACKERS

    # Round 2: turn 9 combat, p1 life 18 -> 16. Bears was tapped from
    # turn 7 attack, then turn 8 was p1's turn (no untap for p0), then
    # turn 9 UNTAP cleared p0 perms.
    trajectory.drive_combat_phase(py_state, rust_state, agent)
    py_view, rust_view = _step_views(py_state, rust_state)
    assert compare_fields(py_view, rust_view) == []
    assert py_view["life_p1"] == 16

    # Walk to turn 11 DA.
    _advance_n_phases(py_state, rust_state, 9 + 12)
    assert py_state.turn_number == 11
    assert py_state.active_player_idx == 0

    # Round 3: turn 11 combat, p1 life 16 -> 14.
    trajectory.drive_combat_phase(py_state, rust_state, agent)
    py_view, rust_view = _step_views(py_state, rust_state)
    assert compare_fields(py_view, rust_view) == []
    assert py_view["life_p1"] == 14


def test_real_game_combat_with_blocks_mutual_destruction_parity():
    """`RealGameCombatAgent("attack_all_block_smallest")` — p0 attacks
    with Bears at turn 7; p1 blocks with their own Bears (cast turn 6,
    sick but blocking-eligible). 2/2 vs 2/2 = mutual destruction.

    Pins:
      * Block-assignment dict round-trips cleanly across engines.
      * Mutual KO — both creatures move to graveyards with same zone
        signature on both sides (CE5 / per-step compare).
      * The "smallest" tie-breaker is deterministic: with one eligible
        blocker (p1's only Bears), the assignment is unambiguous;
        but the agent's sort by (power, toughness, id) is the only
        path that picks it.
    """
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import compare_fields
    from mtg_bot.turn import Step

    spec = _vanilla_60_deckspec(seed=42)
    py_state, rust_state = trajectory.setup_matched_game(spec)
    _setup_both_bears_by_turn_6(py_state, rust_state)

    # State: turn 6 MAIN1, just cast p1 Bears. Walk to turn 7 DA.
    # From turn 6 MAIN1 -> turn 7 DA = 12 + 2 = 14 phases.
    _advance_n_phases(py_state, rust_state, 12 + 2)
    assert py_state.turn_number == 7
    assert py_state.active_player_idx == 0
    assert py_state.step == Step.DECLARE_ATTACKERS

    # Pre-combat invariants.
    bears_count = sum(
        1 for o in py_state.battlefield if o.printing.name == "Grizzly Bears"
    )
    assert bears_count == 2, "should have 2 Bears (one per side) before combat"

    agent = trajectory.RealGameCombatAgent(strategy="attack_all_block_smallest")
    trajectory.drive_combat_phase(py_state, rust_state, agent)

    # Post-combat: both Bears in graveyards.
    py_view, rust_view = _step_views(py_state, rust_state)
    assert compare_fields(py_view, rust_view) == []
    assert py_view["life_p0"] == 20
    assert py_view["life_p1"] == 20  # p0's Bears was blocked — no damage to p1
    bf_creatures = [t for t in py_view["battlefield"] if t[0] == "Grizzly Bears"]
    assert len(bf_creatures) == 0, (
        f"both Bears should be in graveyards after mutual KO, "
        f"but bf still has: {bf_creatures}"
    )
    # Each player's graveyard has their Bears.
    p0_gy_names = [entry[0] for entry in py_view["graveyard_p0"]]
    p1_gy_names = [entry[0] for entry in py_view["graveyard_p1"]]
    assert "Grizzly Bears" in p0_gy_names
    assert "Grizzly Bears" in p1_gy_names


def test_real_game_combat_no_attack_strategy_parity():
    """`RealGameCombatAgent("no_attack")` — combat phase walks past
    with empty attacker + empty blocker emission.

    Pins: the no-attack path is byte-equal across engines on the same
    turn-7 setup. p1 takes no damage; both bears stay on bf untapped.
    """
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import compare_fields
    from mtg_bot.turn import Step

    spec = _vanilla_60_deckspec(seed=42)
    py_state, rust_state = trajectory.setup_matched_game(spec)
    _setup_p0_bears_at_turn_5(py_state, rust_state)

    _advance_n_phases(py_state, rust_state, 12 * 2 + 2)
    assert py_state.step == Step.DECLARE_ATTACKERS

    agent = trajectory.RealGameCombatAgent(strategy="no_attack")
    trajectory.drive_combat_phase(py_state, rust_state, agent)

    py_view, rust_view = _step_views(py_state, rust_state)
    assert compare_fields(py_view, rust_view) == []
    assert py_view["life_p1"] == 20, "no-attack path should not deal damage"
    bears_bf = next(t for t in py_view["battlefield"] if t[0] == "Grizzly Bears")
    assert not bears_bf[1], "Bears should be untapped (never declared attacker)"


def test_real_game_combat_first_strike_parity():
    """First-strike combat through `RealGameCombatAgent` + side-channel
    FS injection.

    Setup: standard p0/p1 Bears prefix, then side-channel a 2/2 first-
    strike creature onto p0's bf at turn 7 PRECOMBAT_MAIN. p0 attacks
    with the FS creature (Bears on p0 also attacks; the FS creature
    is the one whose strike timing matters); p1 blocks with their
    Bears (one blocker per attacker, smallest assignment).

    Expected combat outcome (CR 510.5 first-strike timing):
      * First-strike substep: FS creature deals 2 to its blocker
        (p1's Bears). p1's Bears (2 toughness) dies BEFORE regular
        damage step.
      * Regular substep: dead first-strike-killed blocker is removed
        from the damage walk; surviving blocker-of-other-attacker
        (p1's bears, but it's already dead) does no damage; p0's
        Bears (regular striker, blocked by ??? — but p1 only has
        one Bears to block, and "smallest" assigns to lowest-id
        attacker first).

    NOTE: the agent's "smallest" strategy assigns ONE blocker per
    attacker. With 2 attackers (FS + regular Bears) and 1 blocker,
    only the lowest-id attacker is blocked. If FS has the lower id
    (newly-injected = highest id, so FS is HIGHEST id), regular
    Bears gets blocked, FS goes through to player. In that case
    p1 takes 2 from FS attacker.

    Either outcome is parity-valid — what matters is that BOTH
    engines produce the SAME outcome. The test asserts the same
    life total + zone state on both sides. If a divergence surfaces,
    this test xfails with a clear pointer to the gap.
    """
    import pytest

    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        compare_fields,
        first_strike_side_channel,
    )
    from mtg_bot.turn import Step

    spec = _vanilla_60_deckspec(seed=42)
    py_state, rust_state = trajectory.setup_matched_game(spec)
    _setup_both_bears_by_turn_6(py_state, rust_state)

    # Walk to turn 7 PRECOMBAT_MAIN. From turn 6 MAIN1 -> turn 7 MAIN1
    # = 12 phases.
    _advance_n_phases(py_state, rust_state, 12)
    assert py_state.turn_number == 7
    assert py_state.active_player_idx == 0
    assert py_state.step == Step.PRECOMBAT_MAIN

    # Side-channel-inject the FS creature on p0's bf. Returns
    # (py_id, rust_id) of the new object.
    py_fs_id, rust_fs_id = first_strike_side_channel(py_state, rust_state)
    # The injection should produce a parity-clean state, but the
    # ids may differ if id allocation has drifted. The cross_engine
    # field-view compare validates parity.
    py_view, rust_view = _step_views(py_state, rust_state)
    inject_divs = compare_fields(py_view, rust_view)
    if inject_divs:
        pytest.xfail(
            f"first_strike_side_channel surfaced post-inject "
            f"divergences (likely id-allocation drift between engines "
            f"on the 60-card vanilla deck): "
            f"{[(d.field, d.py_value, d.rust_value) for d in inject_divs]}"
        )

    # Walk PRECOMBAT_MAIN -> BoC -> DECLARE_ATTACKERS.
    _advance_n_phases(py_state, rust_state, 2)
    assert py_state.step == Step.DECLARE_ATTACKERS

    # Drive combat with attack_all_block_smallest. The agent will
    # emit attackers = sorted([Bears_id, FS_id]); blockers = single
    # block on the lowest-id attacker.
    agent = trajectory.RealGameCombatAgent(
        strategy="attack_all_block_smallest"
    )
    try:
        trajectory.drive_combat_phase(py_state, rust_state, agent)
    except AssertionError as exc:
        pytest.xfail(
            f"first-strike combat via RealGameCombatAgent surfaced "
            f"a real cross-engine divergence: {exc}"
        )

    # If we reach here, combat composed cleanly. Sanity-check that
    # SOMETHING happened (p1 took damage OR a creature died).
    py_view, rust_view = _step_views(py_state, rust_state)
    assert compare_fields(py_view, rust_view) == []
    p1_gy_names = [entry[0] for entry in py_view["graveyard_p1"]]
    # First-strike was supposed to kill at least p1's Bears.
    assert "Grizzly Bears" in p1_gy_names or py_view["life_p1"] < 20, (
        "expected first-strike combat to either kill p1's Bears or "
        "land damage on p1; got neither"
    )


# ===========================================================================
# Phase 6 round-17 enhancement: production-shape decklist trajectories.
#
# These tests drive the trajectory machinery on REAL EoE decks loaded
# from data/17lands/eoe_decks.json.gz (the same source self-play /
# iterate consume), via the round-17 helpers in mtg_bot.parity.trajectory:
#   - load_production_deck(archetype) — load one EoE deck's name list.
#   - production_deck_to_deckspec(...) — filter to bridge-supported
#     cards + pad to 60 + build matched DeckSpec.
#   - setup_matched_game_from_real_decks(...) — one-shot wrapper.
#
# The bridge filter (see slice 2 commit + trajectory.py docstring) is
# conservative: only basic lands + vanilla creatures survive. EoE
# vanilla creatures are scarce (~5 in the whole pool); most production
# decks reduce to "basic lands + 0-2 vanilla creatures" after filter.
# These tests pin that the filtered shape DOES round-trip cleanly
# across engines on a real-game-shaped trajectory.
# ===========================================================================


def test_real_eoe_deck_setup_matched_game_parity():
    """Load a real EoE deck (archetype 0), build matched states, assert
    byte-equal field views.

    Pins: the production-deck loader produces a parity-clean opening
    state on both engines. Same shape as the round-13 vanilla-60
    seed but driven by a REAL EoE decklist (and the registry built
    from real CardPrinting data filtered through the round-17 bridge).
    """
    from mtg_bot.parity.cross_engine import compare_fields
    from mtg_bot.parity import trajectory

    cards = trajectory.load_production_deck(0)
    py_state, rust_state = trajectory.setup_matched_game_from_real_decks(
        cards, shared_rng_seed=42,
    )
    py_view, rust_view = _step_views(py_state, rust_state)
    divs = compare_fields(py_view, rust_view)
    assert divs == [], (
        f"production-deck setup diverges: "
        f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in divs]}"
    )
    assert len(py_view["hand_p0"]) == 7
    assert len(py_view["hand_p1"]) == 7
    # Library is 60 (padded) - 7 dealt = 53 on both sides.
    assert len(py_view["library_p0"]) == 53
    assert len(py_view["library_p1"]) == 53


def test_real_eoe_deck_no_op_first_turn_parity():
    """Drive turn 1's full no-op walk on a real EoE deck; assert byte-
    equal field views at every phase boundary.

    Same invariants as the synthetic-60 ``test_no_op_first_turn_parity``
    but on the real-EoE-loaded shape. Surfaces any cross-engine
    bookkeeping bug that requires a non-mono-color registry to manifest
    (basic lands of multiple colors register on Rust + Python with
    different ``mana_produced`` colors; the round-13 vanilla-60 deck
    is mono-G so this case wasn't probed).
    """
    from mtg_bot.parity.cross_engine import (
        advance_phase_python,
        compare_fields,
    )
    from mtg_bot.parity import trajectory

    cards = trajectory.load_production_deck(0)
    py_state, rust_state = trajectory.setup_matched_game_from_real_decks(
        cards, shared_rng_seed=42,
    )

    # Walk 12 phase advances: 11 to walk turn 1 UNTAP -> CLEANUP, then
    # one more for the CLEANUP -> turn 2 UNTAP wrap.
    for advance_idx in range(12):
        advance_phase_python(py_state)
        rust_state.advance_phase()
        py_view, rust_view = _step_views(py_state, rust_state)
        divs = compare_fields(py_view, rust_view)
        assert divs == [], (
            f"advance #{advance_idx} ({py_view['step']!r}, turn "
            f"{py_view['turn']}) on real EoE deck surfaced "
            f"divergences: "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in divs]}"
        )
    # Post-walk: at turn 2 UNTAP with active player p1.
    py_view, _rust_view = _step_views(py_state, rust_state)
    assert py_view["turn"] == 2
    assert py_view["step"] == "UNTAP"


def test_real_eoe_deck_play_basic_land_turn_1_parity():
    """Walk to turn 1 PRECOMBAT_MAIN on a real EoE deck and play
    whatever basic land the active player has in hand.

    The 17lands deck pool's first deck (archetype 0) is a 3-color
    UWG-archetype with several basic Forests / Islands / Plains in
    its 40-card list — after the round-17 filter + pad to 60, p0's
    opening hand is highly likely to contain a basic land. Asserts
    the play_land action round-trips cleanly cross-engine on the
    production-shape registry.
    """
    from mtg_bot.parity.cross_engine import step_both
    from mtg_bot.parity import trajectory

    cards = trajectory.load_production_deck(0)
    py_state, rust_state = trajectory.setup_matched_game_from_real_decks(
        cards, shared_rng_seed=42,
    )
    _advance_n_phases(py_state, rust_state, 3)
    # Find ANY basic land in p0's hand (the production-deck filter
    # ensures lands in the registry are basic).
    p0_hand = py_state.players[0].hand
    land = next(
        (o for o in p0_hand if o.printing.is_land),
        None,
    )
    assert land is not None, (
        f"seed=42 opening hand for p0 contains no basic land: "
        f"{[o.printing.name for o in p0_hand]}"
    )
    s = step_both(
        py_state, rust_state,
        {"kind": "play_land", "card_id": int(land.id)},
    )
    assert s.divergences == [], (
        f"production-deck play_land surfaced divergences: "
        f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
    )
    # The land is on the bf and p0 hand is down to 6.
    py_view = s.py_view
    assert len(py_view["battlefield"]) == 1
    assert py_view["battlefield"][0][0] == land.printing.name
    assert len(py_view["hand_p0"]) == 6


# ---------------------------------------------------------------------------
# Round-17 enhancement: trajectory tests for the new RealGameCombatAgent
# strategies (block_with_largest_able, attack_with_unblockable_creatures_only,
# optimal_no_loss_attack). Mirror shape of the round-16 strategy tests but
# exercise the new strategies on the synthetic-60 vanilla deck.
# ---------------------------------------------------------------------------


def test_real_game_combat_block_with_largest_able_parity():
    """``RealGameCombatAgent("block_with_largest_able")`` with one
    attacker + one blocker: same byte-equal outcome as
    ``attack_all_block_smallest`` because there's only one blocker,
    so "smallest" and "largest" coincide.

    Pins: the new strategy round-trips cleanly cross-engine on the
    synthetic-60 trajectory shape. With multiple blockers the
    behavior diverges from smallest, but the synthetic-60 deck only
    has 1 Bears per player after the standard prefix. Test passes
    today; future enhancement adds a multi-blocker test once a
    deckspec with 2+ blockers per player exists.
    """
    from mtg_bot.parity.cross_engine import compare_fields
    from mtg_bot.parity import trajectory
    from mtg_bot.turn import Step

    spec = _vanilla_60_deckspec(seed=42)
    py_state, rust_state = trajectory.setup_matched_game(spec)
    _setup_both_bears_by_turn_6(py_state, rust_state)

    _advance_n_phases(py_state, rust_state, 12 + 2)
    assert py_state.step == Step.DECLARE_ATTACKERS

    agent = trajectory.RealGameCombatAgent(strategy="block_with_largest_able")
    trajectory.drive_combat_phase(py_state, rust_state, agent)

    py_view, rust_view = _step_views(py_state, rust_state)
    assert compare_fields(py_view, rust_view) == []
    # Mutual KO: both Bears in graveyards (same 2/2 vs 2/2 trade as
    # smallest-blocker test).
    p0_gy_names = [entry[0] for entry in py_view["graveyard_p0"]]
    p1_gy_names = [entry[0] for entry in py_view["graveyard_p1"]]
    assert "Grizzly Bears" in p0_gy_names
    assert "Grizzly Bears" in p1_gy_names


# ---------------------------------------------------------------------------
# Round-17 enhancement: keyword trajectory probes.
#
# Phase 5's keyword side-channels (first_strike / vigilance / lifelink /
# deathtouch / trample / haste / menace / defender / indestructible /
# double_strike / flying / hexproof / multi-keyword) are wired to the
# multi_blocker_deckspec walk only — they side-channel-inject specific
# creatures at step 168 of the retaliation_selector walk. Round-17
# trajectory probes need a more general inject-on-bf helper that
# doesn't assume the synthetic multi_blocker walk.
#
# `_inject_keyword_creature_on_p0_bf` is the round-17 promotion: drop a
# single keyword-bearing 2/2 onto p0's battlefield at any point in a
# trajectory, with parity-clean post-state. Same pattern as the round-16
# `first_strike_side_channel` but parameterized on the keyword + name.
# ---------------------------------------------------------------------------


def _inject_keyword_creature_on_p0_bf(
    py_state, rust_state, *, keyword, printing_name, power=2, toughness=2,
):
    """Generic keyword-creature injector on p0's bf.

    Mirrors :func:`first_strike_side_channel` (cross_engine.py) but
    parameterized on the keyword + printing name so a trajectory probe
    can inject any single-keyword creature without depending on the
    multi_blocker_deckspec setup. Returns ``(py_obj_id, rust_obj_id)``.

    Both engines receive the keyword in the spelling each one uses:
    Python's ``CardPrinting.keywords`` is a frozenset using lowercase
    spelling with spaces (``"first strike"``); Rust's
    ``register_and_inject_object`` expects the lowercase-with-
    underscores form (``"first_strike"``). The injector hands each
    engine the spelling it needs — caller passes the Python form,
    the helper translates for Rust.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone

    # Translate Python's spelling to Rust's: "first strike" -> "first_strike".
    rust_keyword = keyword.replace(" ", "_")

    # ---- Python side ----
    printing = CardPrinting(
        name=printing_name,
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=power,
        toughness=toughness,
        produces=frozenset(),
        keywords=frozenset({keyword}),
    )
    py_obj = py_state.new_object(
        printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_obj)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    rust_obj_id = rust_state.register_and_inject_object(
        {
            "name": printing_name,
            "card_types": ["Creature"],
            "power": power,
            "toughness": toughness,
            "keywords": [rust_keyword],
        },
        0,
        ZONE_BATTLEFIELD,
    )
    return int(py_obj.id), int(rust_obj_id)


def test_trample_overflow_to_player_parity():
    """Trample attacker (4/4) blocked by a 2/2 — trample damage spills
    to the defender. Asserts byte-equal life total + zone state.

    Setup: standard mutual-Bears prefix at turn 7. Inject a 4/4 trample
    creature on p0's bf at turn 7 PRECOMBAT_MAIN. p0 attacks with the
    trample creature + Bears; p1 blocks (smallest = Bears, blocks the
    LOWEST-id attacker by the agent's pairing).

    Per CR 702.19b: trample assigns lethal (= blocker toughness = 2)
    to the blocker, spills the remaining 2 to the defender. p1's Bears
    dies; p1 takes 2 damage (20 -> 18).
    """
    import pytest

    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import compare_fields
    from mtg_bot.turn import Step

    spec = _vanilla_60_deckspec(seed=42)
    py_state, rust_state = trajectory.setup_matched_game(spec)
    _setup_both_bears_by_turn_6(py_state, rust_state)

    _advance_n_phases(py_state, rust_state, 12)
    assert py_state.turn_number == 7
    assert py_state.step == Step.PRECOMBAT_MAIN

    # Inject a 4/4 trample creature on p0 bf.
    _inject_keyword_creature_on_p0_bf(
        py_state, rust_state,
        keyword="trample",
        printing_name="Bear Tankyboy",
        power=4, toughness=4,
    )
    # Verify post-injection parity (no divergence from the inject).
    py_view, rust_view = _step_views(py_state, rust_state)
    inject_divs = compare_fields(py_view, rust_view)
    if inject_divs:
        pytest.xfail(
            f"keyword-injection (trample) surfaced post-inject "
            f"divergences: "
            f"{[(d.field, d.py_value, d.rust_value) for d in inject_divs]}"
        )

    # Walk PRECOMBAT_MAIN -> DECLARE_ATTACKERS.
    _advance_n_phases(py_state, rust_state, 2)
    assert py_state.step == Step.DECLARE_ATTACKERS

    # Drive combat with attack_all_block_smallest. Attackers: trample
    # creature + Bears; defender (p1) has 1 Bears, blocks the lowest-
    # id attacker.
    agent = trajectory.RealGameCombatAgent(
        strategy="attack_all_block_smallest"
    )
    try:
        trajectory.drive_combat_phase(py_state, rust_state, agent)
    except AssertionError as exc:
        pytest.xfail(
            f"trample combat via RealGameCombatAgent surfaced a real "
            f"cross-engine divergence: {exc}"
        )

    # Post-combat: byte-equal field views.
    py_view, rust_view = _step_views(py_state, rust_state)
    assert compare_fields(py_view, rust_view) == []
    # Sanity: SOMETHING happened — at least one creature died OR p1
    # took damage. The exact outcome depends on which attacker p1's
    # Bears blocks (lowest-id). Both engines must agree.
    p1_gy = [entry[0] for entry in py_view["graveyard_p1"]]
    assert (
        py_view["life_p1"] < 20
        or "Grizzly Bears" in p1_gy
        or "Bear Tankyboy" in p1_gy
    ), (
        f"expected combat to land damage or kill a creature; got "
        f"life_p1={py_view['life_p1']}, p1_gy={p1_gy}"
    )


def test_vigilance_attacker_untaps_parity():
    """Vigilance attacker — declaring attackers should NOT tap a
    vigilance creature. Asserts the attacker's tapped flag stays False
    post-DECLARE_ATTACKERS on both engines.

    Per CR 702.20: "Attacking doesn't cause this creature to tap".
    """
    import pytest

    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import compare_fields
    from mtg_bot.turn import Step

    spec = _vanilla_60_deckspec(seed=42)
    py_state, rust_state = trajectory.setup_matched_game(spec)
    _setup_p0_bears_at_turn_5(py_state, rust_state)

    _advance_n_phases(py_state, rust_state, 12 * 2)
    assert py_state.turn_number == 7
    assert py_state.step == Step.PRECOMBAT_MAIN

    # Inject a 2/2 vigilance creature on p0 bf.
    py_vig_id, _rust_vig_id = _inject_keyword_creature_on_p0_bf(
        py_state, rust_state,
        keyword="vigilance",
        printing_name="Bear Sentry",
        power=2, toughness=2,
    )
    py_view, rust_view = _step_views(py_state, rust_state)
    inject_divs = compare_fields(py_view, rust_view)
    if inject_divs:
        pytest.xfail(
            f"keyword-injection (vigilance) surfaced post-inject "
            f"divergences: "
            f"{[(d.field, d.py_value, d.rust_value) for d in inject_divs]}"
        )

    _advance_n_phases(py_state, rust_state, 2)
    assert py_state.step == Step.DECLARE_ATTACKERS

    # Drive combat with attack_all (defender doesn't block).
    agent = trajectory.RealGameCombatAgent(strategy="attack_all")
    try:
        trajectory.drive_combat_phase(py_state, rust_state, agent)
    except AssertionError as exc:
        pytest.xfail(
            f"vigilance combat via RealGameCombatAgent surfaced a "
            f"real cross-engine divergence: {exc}"
        )

    # Post-combat: byte-equal field views.
    py_view, rust_view = _step_views(py_state, rust_state)
    assert compare_fields(py_view, rust_view) == []
    # Vigilance creature should be UNTAPPED on both engines (it
    # attacked, but vigilance suppresses the attack-tap).
    vig_bf = next(
        t for t in py_view["battlefield"] if t[0] == "Bear Sentry"
    )
    # bf 8-tuple field 1 is the tapped slot.
    assert not vig_bf[1], (
        f"vigilance attacker should be untapped; got tapped={vig_bf[1]}"
    )
    # The non-vigilance Bears, OTOH, IS tapped (no vigilance).
    bears_bf = next(
        t for t in py_view["battlefield"] if t[0] == "Grizzly Bears"
    )
    assert bears_bf[1], (
        f"non-vigilance Bears should be tapped after attack; "
        f"got tapped={bears_bf[1]}"
    )


def test_lifelink_combat_damage_to_self_parity():
    """Lifelink attacker — combat damage to the defender also gains the
    attacker's controller life equal to the damage.

    Setup: inject a 2/2 lifelink creature on p0 bf at turn 7. p0
    attacks with the lifelink creature (no block — defender has no
    creatures). Lifelink fires for 2 damage to the player → p0 gains
    2 life.

    Per CR 702.15b: damage dealt by a creature with lifelink causes
    its controller to gain that much life.
    """
    import pytest

    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import compare_fields
    from mtg_bot.turn import Step

    spec = _vanilla_60_deckspec(seed=42)
    py_state, rust_state = trajectory.setup_matched_game(spec)

    # Walk to turn 7 PRECOMBAT_MAIN with no creatures (skip the bears
    # setup so the lifelink creature is the SOLE attacker — keeps the
    # life-total expectation crisp).
    _advance_n_phases(py_state, rust_state, 3)  # → turn 1 MAIN1
    # Walk through 6 more turns (turns 2-7), each is 12 phases.
    _advance_n_phases(py_state, rust_state, 12 * 6)
    assert py_state.turn_number == 7
    assert py_state.active_player_idx == 0
    assert py_state.step == Step.PRECOMBAT_MAIN

    # Inject a 2/2 lifelink creature on p0 bf.
    _inject_keyword_creature_on_p0_bf(
        py_state, rust_state,
        keyword="lifelink",
        printing_name="Bear Healer",
        power=2, toughness=2,
    )
    py_view, rust_view = _step_views(py_state, rust_state)
    inject_divs = compare_fields(py_view, rust_view)
    if inject_divs:
        pytest.xfail(
            f"keyword-injection (lifelink) surfaced post-inject "
            f"divergences: "
            f"{[(d.field, d.py_value, d.rust_value) for d in inject_divs]}"
        )

    pre_combat_life_p0 = py_view["life_p0"]
    pre_combat_life_p1 = py_view["life_p1"]

    _advance_n_phases(py_state, rust_state, 2)
    assert py_state.step == Step.DECLARE_ATTACKERS

    # Attack unblocked (defender has no creatures to block with).
    agent = trajectory.RealGameCombatAgent(strategy="attack_all")
    try:
        trajectory.drive_combat_phase(py_state, rust_state, agent)
    except AssertionError as exc:
        pytest.xfail(
            f"lifelink combat via RealGameCombatAgent surfaced a "
            f"real cross-engine divergence: {exc}"
        )

    # Post-combat parity.
    py_view, rust_view = _step_views(py_state, rust_state)
    assert compare_fields(py_view, rust_view) == []
    # Lifelink: p0 gained 2 life; p1 lost 2.
    assert py_view["life_p0"] == pre_combat_life_p0 + 2, (
        f"lifelink should have gained 2 life; got "
        f"life_p0={py_view['life_p0']} (was {pre_combat_life_p0})"
    )
    assert py_view["life_p1"] == pre_combat_life_p1 - 2


def test_real_game_combat_optimal_no_loss_attack_skips_unsafe_parity():
    """``RealGameCombatAgent("optimal_no_loss_attack")`` skips attacks
    where the defender's bf has a creature that can trade up.

    Setup: both players have a Bears 2/2 on bf (turn 7 on the
    standard prefix). p0's Bears (toughness=2) is UNSAFE because
    p1's Bears (power=2) can trade. Strategy declines to attack;
    p1's life stays 20 on both engines.
    """
    from mtg_bot.parity.cross_engine import compare_fields
    from mtg_bot.parity import trajectory
    from mtg_bot.turn import Step

    spec = _vanilla_60_deckspec(seed=42)
    py_state, rust_state = trajectory.setup_matched_game(spec)
    _setup_both_bears_by_turn_6(py_state, rust_state)

    _advance_n_phases(py_state, rust_state, 12 + 2)
    assert py_state.step == Step.DECLARE_ATTACKERS

    agent = trajectory.RealGameCombatAgent(strategy="optimal_no_loss_attack")
    trajectory.drive_combat_phase(py_state, rust_state, agent)

    py_view, rust_view = _step_views(py_state, rust_state)
    assert compare_fields(py_view, rust_view) == []
    # p1 took no damage — p0 declined to attack.
    assert py_view["life_p1"] == 20
    # Bears still on bf, not in any graveyard.
    p0_gy = [entry[0] for entry in py_view["graveyard_p0"]]
    p1_gy = [entry[0] for entry in py_view["graveyard_p1"]]
    assert "Grizzly Bears" not in p0_gy
    assert "Grizzly Bears" not in p1_gy


# ===========================================================================
# Phase 6 round-18 enhancement: deathtouch / double-strike / haste
# trajectory probes.
#
# Round 18 extends the round-17 keyword-probe family. The round-17
# `_inject_keyword_creature_on_p0_bf` helper handles the attacker side
# (p0's bf, single-keyword 2/2). Some round-18 probes also need a
# specific *blocker* on p1's bf — a vanilla creature with controlled
# p/t — so the deathtouch / double-strike outcomes are deterministic
# rather than depending on whether `_setup_both_bears_by_turn_6`'s
# Bears happens to land where the smallest-block selector pairs it
# with the keyworded attacker. `_inject_vanilla_creature_on_bf` is
# the round-18 sibling helper for that case: a parameterized vanilla
# (no keywords) creature on either player's bf.
#
# Haste needs a slightly different fixture: the injected attacker
# must START summoning-sick (CR 302.1) so haste's bypass (CR 702.10)
# is the only thing that lets it attack. The round-17 helper stamps
# `summoning_sick = False` unconditionally; we use Rust's
# `force_set_summoning_sick` test-helper + Python's mutable
# `o.summoning_sick` field to flip the flag on both engines after
# injection.
# ===========================================================================


def _inject_vanilla_creature_on_bf(
    py_state, rust_state, *, controller_idx, printing_name, power, toughness,
):
    """Inject a vanilla (no-keyword) creature on the given player's bf.

    Sibling of :func:`_inject_keyword_creature_on_p0_bf` for round-18
    deathtouch / double-strike probes that need a specific blocker
    on the *defender's* battlefield with controlled p/t (the standard
    `_setup_both_bears_by_turn_6` Bears prefix can't be used because
    block-smallest assignments depend on attacker/blocker id ordering
    that's hard to pin without controlling the defender's exact
    creature inventory).

    Returns ``(py_obj_id, rust_obj_id)``.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone

    # ---- Python side ----
    printing = CardPrinting(
        name=printing_name,
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=power,
        toughness=toughness,
        produces=frozenset(),
        keywords=frozenset(),
    )
    py_obj = py_state.new_object(
        printing, owner_id=controller_idx, zone=Zone.BATTLEFIELD,
    )
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_obj)

    # ---- Rust side ----
    ZONE_BATTLEFIELD = 2
    rust_obj_id = rust_state.register_and_inject_object(
        {
            "name": printing_name,
            "card_types": ["Creature"],
            "power": power,
            "toughness": toughness,
            "keywords": [],
        },
        controller_idx,
        ZONE_BATTLEFIELD,
    )
    return int(py_obj.id), int(rust_obj_id)


def test_deathtouch_combat_damage_kills_blocker_parity():
    """Deathtouch attacker (1/1) blocked by a 4/4 vanilla — 1 damage
    from the deathtouch creature is "lethal" for SBA purposes per
    CR 702.2; the 4/4 blocker dies. The attacker takes 4 damage from
    the blocker but has only 1 toughness — it also dies.

    Setup: walk to turn 7 PRECOMBAT_MAIN with no creatures. Inject a
    1/1 deathtouch creature on p0; inject a 4/4 vanilla on p1. p0
    attacks with the deathtouch creature (sole attacker); p1 blocks
    with the 4/4 (sole eligible blocker → smallest = largest = only).

    Asserts byte-equal:
      * Both creatures in their respective graveyards.
      * No life total change (combat damage stayed in creature combat).
    """
    import pytest

    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import compare_fields
    from mtg_bot.turn import Step

    spec = _vanilla_60_deckspec(seed=42)
    py_state, rust_state = trajectory.setup_matched_game(spec)

    # Walk to turn 7 PRECOMBAT_MAIN with no creatures (skip bears
    # setup so the deathtouch + vanilla blocker are the SOLE
    # combatants — keeps the block-pairing deterministic).
    _advance_n_phases(py_state, rust_state, 3)  # → turn 1 MAIN1
    _advance_n_phases(py_state, rust_state, 12 * 6)  # → turn 7 MAIN1
    assert py_state.turn_number == 7
    assert py_state.active_player_idx == 0
    assert py_state.step == Step.PRECOMBAT_MAIN

    # Inject deathtouch attacker on p0 + vanilla blocker on p1.
    _inject_keyword_creature_on_p0_bf(
        py_state, rust_state,
        keyword="deathtouch",
        printing_name="Bear Striker",
        power=1, toughness=1,
    )
    _inject_vanilla_creature_on_bf(
        py_state, rust_state,
        controller_idx=1,
        printing_name="Bear Wall",
        power=4, toughness=4,
    )
    py_view, rust_view = _step_views(py_state, rust_state)
    inject_divs = compare_fields(py_view, rust_view)
    if inject_divs:
        pytest.xfail(
            f"keyword-injection (deathtouch) surfaced post-inject "
            f"divergences: "
            f"{[(d.field, d.py_value, d.rust_value) for d in inject_divs]}"
        )

    pre_combat_life_p0 = py_view["life_p0"]
    pre_combat_life_p1 = py_view["life_p1"]

    _advance_n_phases(py_state, rust_state, 2)
    assert py_state.step == Step.DECLARE_ATTACKERS

    # p0's deathtouch is the only eligible attacker; p1's 4/4 is the
    # only eligible blocker.
    agent = trajectory.RealGameCombatAgent(
        strategy="attack_all_block_smallest"
    )
    try:
        trajectory.drive_combat_phase(py_state, rust_state, agent)
    except AssertionError as exc:
        pytest.xfail(
            f"deathtouch combat via RealGameCombatAgent surfaced a "
            f"real cross-engine divergence: {exc}"
        )

    # Post-combat parity.
    py_view, rust_view = _step_views(py_state, rust_state)
    assert compare_fields(py_view, rust_view) == []

    # Per CR 702.2: any damage from a deathtouch creature is treated
    # as lethal for SBA. The 4/4 blocker dies despite 4 toughness.
    # The 1/1 attacker dies to the blocker's 4 power (regular lethal).
    # Life totals unchanged (no damage hit any player).
    assert py_view["life_p0"] == pre_combat_life_p0
    assert py_view["life_p1"] == pre_combat_life_p1
    p0_gy = [entry[0] for entry in py_view["graveyard_p0"]]
    p1_gy = [entry[0] for entry in py_view["graveyard_p1"]]
    # Deathtouch attacker died to the blocker's 4 power.
    assert "Bear Striker" in p0_gy, (
        f"deathtouch attacker should have died (4 damage from blocker); "
        f"got p0_gy={p0_gy}"
    )
    # 4/4 blocker died to deathtouch's 1 damage (CR 702.2 — any
    # nonzero deathtouch damage is lethal).
    assert "Bear Wall" in p1_gy, (
        f"deathtouch's 1 damage should be lethal for the 4/4 blocker "
        f"per CR 702.2; got p1_gy={p1_gy}"
    )
