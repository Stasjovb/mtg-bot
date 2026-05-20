"""Genuine real-EoE cross-engine byte-equality probes -- batch BBB downstream
(7th Rust slice; closes GGG Pins 1+2 + XX Pins 1+2 downstream gaps).

The 7th Rust slice added Rust-parser arms for:

  * state_bound / void_active / any_player_controls_no_creatures predicates
    (GGG Pin 1)
  * defending_player_loses_half_life_rounded_up effect (GGG Pin 2 / bridge)
  * conditional_if_you_gained_life_at_least effect (XX Pin 1)
  * conditional_if_source_power_at_least effect (XX Pin 2)
  * life_gained_this_turn tracking in Rust Player struct

PROBE CARDS
-----------

Probe 1 -- Sothera, the Supervoid (EoE)
"At the beginning of your end step, if a player controls no creatures,
draw a card."

Event: BEGINNING_OF_END_STEP
Predicate: And(controlled_by_you, state_bound(any_player_controls_no_creatures))
Effect: DrawCards(1)

CCC noted this as honest-exhaustion. The 7th Rust slice adds the arm.

Probe 2 -- Haliya, Guided by Light end-step arm (EoE)
"At the beginning of your end step, draw a card if you've gained 3 or
more life this turn."

Event: BEGINNING_OF_END_STEP
Predicate: controlled_by_you
Effect: ConditionalIfYouGainedLifeAtLeast(threshold=3, inner=DrawCards(1))

CCC noted this as honest-exhaustion. The 7th Rust slice adds the arm AND
wires life_gained_this_turn tracking in Rust's GainLife resolve arm +
cleanup reset.

Observable for both: p0 library_size decreases by 1 when the draw fires.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


@pytest.fixture(scope="module")
def parity_smoke():
    """Load scripts/parity_smoke.py as a module."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location("parity_smoke", script_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


def _inject_library_cards_python(py_state, n=3):
    """Add n dummy land cards to p0's library so draw has targets."""
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone

    plains_printing = CardPrinting(
        name="Plains",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Basic Land -- Plains",
        supertypes=("Basic",),
        card_types=("Land",),
        subtypes=("Plains",),
        power=None,
        toughness=None,
        produces=frozenset({"W"}),
        keywords=frozenset(),
        triggered_abilities=(),
    )
    for _ in range(n):
        obj = py_state.new_object(plains_printing, owner_id=0, zone=Zone.LIBRARY)
        py_state.players[0].library.append(obj)


def _inject_library_cards_rust(rs_state, n=3):
    """Add n dummy land cards to p0's library (zone=1) in Rust."""
    ZONE_LIBRARY = 1
    for _ in range(n):
        rs_state.register_and_inject_object(
            {
                "name": "Plains",
                "card_types": ["Land"],
                "supertypes": ["Basic"],
                "keywords": [],
                "effects": [],
                "triggered_abilities": [],
            },
            0, ZONE_LIBRARY,
        )


# ---------------------------------------------------------------------------
# Probe 1 -- Sothera, the Supervoid: StateBound(AnyPlayerControlsNoCreatures)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_sothera_supervoid_end_step_any_player_no_creatures_draw_parity(
    parity_smoke,
):
    """Genuine real-EoE probe -- Sothera, the Supervoid end-step draw.

    7th Rust slice: state_bound(any_player_controls_no_creatures) predicate
    now parses in Rust. Both engines draw 1 card when p1 controls no creatures.

    Observable: p0 library_sizes decreases by 1 on BOTH engines (draw fires).
    Rust: library_sizes[0] before - library_sizes[0] after == 1.
    Python: len(p0.library) before - len(p0.library) after == 1.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
        _ta_dict_to_python_triggered_ability,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.predicates import Event, StateBound
    from mtg_bot.effects.state_predicates import AnyPlayerControlsNoCreatures
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.turn import (
        run_beginning_of_end_step_triggers,
        state_based_actions as py_sba,
    )
    from mtg_bot.actions import resolve_top_of_stack, put_into_battlefield
    from mtg_bot.game import Zone

    # 1. Verify real Sothera has an end-step triggered ability.
    real = get_active_source().get_printings().get("Sothera, the Supervoid")
    if real is None:
        pytest.skip("Sothera, the Supervoid absent from active CardSource")

    s_eos_ta = next(
        (ta for ta in real.triggered_abilities
         if ta.event == Event.BEGINNING_OF_END_STEP),
        None,
    )
    assert s_eos_ta is not None, (
        "Sothera must have a BEGINNING_OF_END_STEP triggered ability"
    )

    # 2. Shared TA dict.
    sothera_ta_dict = {
        "event": "beginning_of_end_step",
        "predicate": {
            "kind": "and",
            "left": {"kind": "controlled_by_you"},
            "right": {
                "kind": "state_bound",
                "inner": {"kind": "any_player_controls_no_creatures"},
            },
        },
        "effect": {"kind": "draw_cards", "count": 1},
    }

    bridge_ta = _ta_dict_to_python_triggered_ability(sothera_ta_dict)
    assert bridge_ta.event == Event.BEGINNING_OF_END_STEP
    assert isinstance(bridge_ta.effect, DrawCards)

    # 3. Build states. Library cards give the draw something to draw.
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    ZB = 2  # ZONE_BATTLEFIELD

    # Add 3 library cards for p0.
    _inject_library_cards_python(py, n=3)
    _inject_library_cards_rust(rs, n=3)
    # Drain any inject noise (none expected for library zone).
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    # 4. Rust: seat Sothera on p0's battlefield.
    rs.register_and_inject_object(
        {
            "name": "Sothera, the Supervoid",
            "card_types": ["Creature"],
            "supertypes": ["Legendary"],
            "power": 5,
            "toughness": 5,
            "keywords": ["flying"],
            "effects": [],
            "triggered_abilities": [sothera_ta_dict],
        },
        0, ZB,
    )
    # Drain any self-ETB noise (Sothera has no ETB ability in our dict).
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_lib0_before = rs.library_sizes[0]
    assert rs_lib0_before == 3, (
        f"Rust: p0 must have 3 library cards before EOS; got {rs_lib0_before}"
    )

    # 5. Rust: advance to END_STEP (phase 10).
    PHASE_END_STEP = 10
    for _ in range(30):
        rs.advance_phase()
        if rs.current_phase() == PHASE_END_STEP:
            break

    assert rs.current_phase() == PHASE_END_STEP, (
        f"Rust: must reach PHASE_END_STEP; got {rs.current_phase()}"
    )
    # Sothera's trigger fires: p1 has no creatures.
    assert rs.stack_size() == 1, (
        f"Rust: exactly 1 trigger (Sothera EOS draw) expected (p1 has no "
        f"creatures); got {rs.stack_size()}"
    )

    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_lib0_after = rs.library_sizes[0]
    assert rs_lib0_after == 2, (
        f"Rust: p0 library must decrease by 1 (draw 1 card via Sothera EOS); "
        f"got {rs_lib0_after}"
    )

    # 6. Python: seat Sothera directly on battlefield.
    py_sothera_printing = CardPrinting(
        name="Sothera, the Supervoid",
        mana_cost_str="{4}{U}{B}",
        mana_cost=ManaCost(generic=4, colored=(("U", 1), ("B", 1))),
        type_line="Legendary Creature -- Eldrazi",
        supertypes=("Legendary",),
        card_types=("Creature",),
        subtypes=("Eldrazi",),
        power=5,
        toughness=5,
        produces=frozenset(),
        keywords=frozenset({"flying"}),
        triggered_abilities=(bridge_ta,),
    )
    py_sothera = py.new_object(py_sothera_printing, owner_id=0, zone=Zone.HAND)
    py.players[0].hand.append(py_sothera)
    put_into_battlefield(py, py_sothera, controller_id=0)
    # Remove ghost hand reference (put_into_battlefield changes zone but not list).
    py.players[0].hand.remove(py_sothera)
    # Drain any ETB noise.
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    py_lib0_before = len(py.players[0].library)
    assert py_lib0_before == 3, (
        f"Python: p0 must have 3 library cards before EOS; got {py_lib0_before}"
    )

    # Fire end-step triggers. p1 has no creatures -> predicate true.
    run_beginning_of_end_step_triggers(py)

    assert len(py.stack) == 1, (
        f"Python: exactly 1 trigger (Sothera EOS draw) expected; "
        f"got {len(py.stack)}"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    py_lib0_after = len(py.players[0].library)
    assert py_lib0_after == 2, (
        f"Python: p0 library must decrease by 1 (draw 1 card via Sothera EOS); "
        f"got {py_lib0_after}"
    )

    # 7. Cross-engine byte-equality.
    assert rs_lib0_after == py_lib0_after == 2, (
        f"p0 library after EOS: Rust={rs_lib0_after}, Python={py_lib0_after} "
        f"(must be 2 on BOTH -- DrawCards(1) via StateBound("
        f"AnyPlayerControlsNoCreatures))"
    )


# ---------------------------------------------------------------------------
# Probe 2 -- Haliya end-step ConditionalIfYouGainedLifeAtLeast(3, DrawCards(1))
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_haliya_end_step_conditional_life_gained_draw_parity(
    parity_smoke,
):
    """Genuine real-EoE probe -- Haliya end-step conditional draw.

    7th Rust slice: conditional_if_you_gained_life_at_least now parses in
    Rust AND life_gained_this_turn is tracked.

    Scenario: gain 3 life this turn (via Haliya's ETB observer firing 3x)
    then fire end-step. Gate passes (3 >= 3) -> draw 1 card on BOTH engines.

    Observable: p0 library_sizes decreases by 1 (library 3 -> 2) on BOTH.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
        _ta_dict_to_python_triggered_ability,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.predicates import Event, Controlled, YOU
    from mtg_bot.effects.combinators import ConditionalIfYouGainedLifeAtLeast
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.turn import (
        run_beginning_of_end_step_triggers,
        state_based_actions as py_sba,
    )
    from mtg_bot.actions import resolve_top_of_stack, put_into_battlefield
    from mtg_bot.game import Zone
    from mtg_bot.cards import SYNTHETIC_CREATURES

    # 1. Verify real Haliya has end-step ConditionalIfYouGainedLifeAtLeast.
    real = get_active_source().get_printings().get("Haliya, Guided by Light")
    if real is None:
        pytest.skip("Haliya, Guided by Light absent from active CardSource")

    h_eos_ta = next(
        (ta for ta in real.triggered_abilities
         if ta.event == Event.BEGINNING_OF_END_STEP),
        None,
    )
    assert h_eos_ta is not None, "Haliya must have a BEGINNING_OF_END_STEP TA"
    assert isinstance(h_eos_ta.effect, ConditionalIfYouGainedLifeAtLeast), (
        f"Haliya EOS effect must be ConditionalIfYouGainedLifeAtLeast; "
        f"got {type(h_eos_ta.effect).__name__}"
    )
    assert h_eos_ta.effect.threshold == 3

    # 2. Shared TA dicts.
    h_eos_ta_dict = {
        "event": "beginning_of_end_step",
        "predicate": {"kind": "controlled_by_you"},
        "effect": {
            "kind": "conditional_if_you_gained_life_at_least",
            "threshold": 3,
            "inner": {"kind": "draw_cards", "count": 1},
        },
    }
    h_etb_ta_dict = {
        "event": "enters",
        "predicate": {
            "kind": "and",
            "left": {
                "kind": "or",
                "left": {"kind": "subject_is_creature"},
                "right": {"kind": "subject_is_artifact"},
            },
            "right": {"kind": "controlled_by_you"},
        },
        "effect": {"kind": "gain_life", "amount": 1},
    }

    bridge_eos_ta = _ta_dict_to_python_triggered_ability(h_eos_ta_dict)
    bridge_etb_ta = _ta_dict_to_python_triggered_ability(h_etb_ta_dict)

    assert isinstance(bridge_eos_ta.effect, ConditionalIfYouGainedLifeAtLeast)
    assert bridge_eos_ta.effect.threshold == 3
    assert isinstance(bridge_eos_ta.effect.inner, DrawCards)

    # 3. Build states. Library cards for draw.
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    ZB = 2  # ZONE_BATTLEFIELD

    # Add 5 library cards for p0.
    _inject_library_cards_python(py, n=5)
    _inject_library_cards_rust(rs, n=5)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    # 4. Rust: inject Haliya with ETB + EOS abilities.
    rs.register_and_inject_object(
        {
            "name": "Haliya, Guided by Light",
            "card_types": ["Creature"],
            "supertypes": ["Legendary"],
            "power": 3,
            "toughness": 3,
            "keywords": [],
            "effects": [],
            "triggered_abilities": [h_etb_ta_dict, h_eos_ta_dict],
        },
        0, ZB,
    )

    # Haliya self-ETB fires GainLife(1) (+1 life).
    assert rs.stack_size() == 1
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.get_life(0) == 21

    # Inject 2 bears -> Haliya's ETB fires 2 more times (+2 life, total=3).
    for bear_name in ("Wild Bear", "Forest Bear"):
        rs.register_and_inject_object(
            {
                "name": bear_name,
                "card_types": ["Creature"],
                "power": 2,
                "toughness": 2,
                "keywords": [],
                "effects": [],
                "triggered_abilities": [],
            },
            0, ZB,
        )
        assert rs.stack_size() == 1
        while rs.stack_size() > 0:
            rs.resolve_top_of_stack()
        rs.apply_sbas()

    assert rs.get_life(0) == 23, (
        f"Rust: p0 must be at 23 after 3 GainLife(1); got {rs.get_life(0)}"
    )

    rs_lib0_before = rs.library_sizes[0]
    assert rs_lib0_before == 5

    # 5. Rust: advance to END_STEP.
    PHASE_END_STEP = 10
    for _ in range(30):
        rs.advance_phase()
        if rs.current_phase() == PHASE_END_STEP:
            break

    assert rs.current_phase() == PHASE_END_STEP
    # EOS trigger fires; life_gained_this_turn=3 >= threshold=3 -> draw.
    assert rs.stack_size() == 1, (
        f"Rust: 1 trigger (Haliya EOS conditional draw) expected; "
        f"got {rs.stack_size()}"
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_lib0_after = rs.library_sizes[0]
    assert rs_lib0_after == 4, (
        f"Rust: p0 library must decrease by 1 (ConditionalIfYouGainedLifeAtLeast(3) "
        f"gate passes, draw 1); got {rs_lib0_after}"
    )

    # 6. Python: inject Haliya + 2 bears; fire EOS triggers.
    py_haliya_printing = CardPrinting(
        name="Haliya, Guided by Light",
        mana_cost_str="{2}{W}",
        mana_cost=ManaCost(generic=2, colored=(("W", 1),)),
        type_line="Legendary Creature -- Human Soldier",
        supertypes=("Legendary",),
        card_types=("Creature",),
        subtypes=("Human", "Soldier"),
        power=3,
        toughness=3,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(bridge_etb_ta, bridge_eos_ta),
    )
    py_haliya = py.new_object(py_haliya_printing, owner_id=0, zone=Zone.HAND)
    py.players[0].hand.append(py_haliya)
    put_into_battlefield(py, py_haliya, controller_id=0)
    py.players[0].hand.remove(py_haliya)  # Remove ghost hand reference.

    assert len(py.stack) == 1
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    assert py.players[0].life == 21, (
        f"Python: p0 must be at 21 after Haliya self-ETB; "
        f"got {py.players[0].life}"
    )

    for _ in range(2):
        py_bear = py.new_object(
            SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.HAND
        )
        py.players[0].hand.append(py_bear)
        put_into_battlefield(py, py_bear, controller_id=0)
        py.players[0].hand.remove(py_bear)  # Remove ghost.
        assert len(py.stack) == 1
        while py.stack:
            resolve_top_of_stack(py)
        py_sba(py)

    assert py.players[0].life == 23, (
        f"Python: p0 must be at 23 after 3 GainLife(1); "
        f"got {py.players[0].life}"
    )
    assert py.players[0].life_gained_this_turn == 3, (
        f"Python: life_gained_this_turn must be 3; "
        f"got {py.players[0].life_gained_this_turn}"
    )

    py_lib0_before = len(py.players[0].library)
    assert py_lib0_before == 5

    run_beginning_of_end_step_triggers(py)
    assert len(py.stack) == 1, (
        f"Python: 1 trigger (Haliya EOS conditional draw) expected; "
        f"got {len(py.stack)}"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    py_lib0_after = len(py.players[0].library)
    assert py_lib0_after == 4, (
        f"Python: p0 library must decrease by 1 (conditional draw fires); "
        f"got {py_lib0_after}"
    )

    # 7. Cross-engine byte-equality.
    assert rs_lib0_after == py_lib0_after == 4, (
        f"p0 library after EOS: Rust={rs_lib0_after}, Python={py_lib0_after} "
        f"(must be 4 on BOTH -- ConditionalIfYouGainedLifeAtLeast(3) "
        f"gate passes after 3 x GainLife(1))"
    )
    assert rs.get_life(0) == py.players[0].life == 23, (
        f"p0 life: Rust={rs.get_life(0)}, Python={py.players[0].life} "
        f"(must be 23 on BOTH)"
    )
