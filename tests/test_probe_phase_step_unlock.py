"""Genuine real-EoE cross-engine byte-equality probe — phase-step events
(beginning_of_end_step / beginning_of_upkeep / beginning_of_combat)
unlock (round 14 Rust slice).

This module ships the first cross-engine probe for the
``BEGINNING_OF_END_STEP`` event family.  The unlock comes from:

1. Adding ``Event::BeginningOfEndStep``, ``Event::BeginningOfUpkeep``,
   and ``Event::BeginningOfCombat`` variants to the Rust ``Event`` enum
   (``rust/src/cards.rs``).
2. Adding parse arms for ``"beginning_of_end_step"``,
   ``"beginning_of_upkeep"``, and ``"beginning_of_combat"`` in
   ``parse_triggered_ability`` (``rust/src/cards.rs``).
3. Adding ``PLAYER_SUBJECT_OFFSET = 0x8000_0000`` as a sentinel to
   safely represent player-typed subjects in the ``subject_id: u32``
   API without colliding with game-object IDs (``rust/src/cards.rs``).
4. Extending ``Predicate::ControlledByYou.matches()`` to detect the
   sentinel range and resolve the player index directly, enabling
   "at the beginning of YOUR end step" predicate evaluation for
   phase-step events (``rust/src/cards.rs``).
5. Adding dispatch sites in ``advance_phase`` in
   ``rust/src/state_ops_steps.rs`` for the three new phases
   (``PHASE_UPKEEP``, ``PHASE_BEGIN_COMBAT``, ``PHASE_END_STEP``).
6. Adding all three new events to the ``dispatch_event`` allow-list in
   ``rust/src/state_ops_resolve.rs``.
7. Adding bridge arms for all three event strings in
   ``_ta_dict_to_python_triggered_ability``
   (``src/mtg_bot/parity/cross_engine.py``).

**Before this slice** the bridge raised::

    ValueError: cross_engine triggered_abilities bridge: event
    'beginning_of_end_step' is not yet wired

and the Rust parser raised::

    ValueError: unknown triggered_ability.event "beginning_of_end_step"

Both gaps are closed by this slice for all three phase-step events.

PROBE CARD — Flight-Deck Coordinator (EoE)
------------------------------------------
Oracle: "[Creature — Human Soldier] {2}{W} 3/3
  At the beginning of your end step, if you control two or more tapped
  creatures, you gain 2 life."

  * Event    = ``BEGINNING_OF_END_STEP``
  * Predicate = ``Controlled(YOU)`` → ``ControlledByYou``
  * Effect   = ``ConditionalOnTappedCreatures(GainLife(2), min_count=2)``

PROBE FLOW
----------
The probe seats Flight-Deck Coordinator (3/3, tapped) and a tapped
filler creature on p0's battlefield.  Both are tapped so the
``ConditionalOnTappedCreatures`` condition (≥ 2) is satisfied.

1. Rust: ``advance_phase()`` x N until phase = ``END_STEP`` (10).
   Entry fires ``dispatch_event(BeginningOfEndStep,
   PLAYER_SUBJECT_OFFSET + 0)``; ``ControlledByYou`` resolves
   player_index=0, matches ``source.controller=0`` for FDC → trigger
   pushed.
   Python: ``run_beginning_of_end_step_triggers(state)`` calls
   ``dispatch_event(state, Event.BEGINNING_OF_END_STEP,
   player=state.active_player())``; same ``Controlled(YOU)`` match
   logic fires the trigger.
2. Both stacks have 1 item (the FDC ``GainLife(2)`` conditional).
3. Resolve both stacks → ``ConditionalOnTappedCreatures`` evaluates
   tapped-creature count ≥ 2 → ``GainLife(2)`` fires → p0 life 20→22.
4. Observable: p0 life ``20 → 22`` on both engines.

CARDS STILL BLOCKED AFTER THIS SLICE
--------------------------------------
The round-14 slice wires the parse + dispatch + bridge for all three
phase-step events.  Cards with complex predicate or effect shapes that
are not yet representable in the Rust predicate/effect algebra remain
blocked:

* Triggers with ``ConditionalIfYouGainedLifeAtLeast`` (Haliya's draw
  rider), ``StateBound`` (Ragost's untap-self), ``VoidActive``
  (Voidforged Titan / Elegy Acolyte Void variants), ``AnyPlayerControlsNoCreatures``
  (Sothera) — these are effect/predicate shapes that need new
  Rust Effect / Effect::Conditional arms before they can probe.
* ``always`` predicate end-step cards (Ragost's untap-self is Always
  but needs IfGainedLifeThisTurnUntapSelf effect arm).
* Upkeep / combat phase cards: same bridge arms are live, but no EoE
  card with a simple-enough upkeep/combat effect exists in the probe
  lane today — deferred until the next probe batch finds one.

LL Pin 3 status: RENAMED to ``_FIXED_parity`` (assertions inverted to
verify the now-wired behavior; the gap is closed).
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
    """Load ``scripts/parity_smoke.py`` as a module."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location("parity_smoke", script_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Probe — Flight-Deck Coordinator: end step gain 2 life (2+ tapped creatures)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_flight_deck_coordinator_beginning_of_end_step_gain_life_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Flight-Deck Coordinator
    (round 14, first BEGINNING_OF_END_STEP probe).**

    Drives the **real parsed Flight-Deck Coordinator printing** on the
    Python side and a bridged synthetic carrier on the Rust side through
    the ``BEGINNING_OF_END_STEP`` dispatch path.

    Setup:
      * p0 has Flight-Deck Coordinator (3/3, tapped) and one additional
        tapped filler creature on the battlefield.
      * p1 has no creatures and no library cards.
      * Active player = p0 (FDC's controller).

    Trigger flow:
      1. Rust: ``advance_phase()`` loops until ``PHASE_END_STEP`` (10).
         Entry fires ``dispatch_event(BeginningOfEndStep,
         PLAYER_SUBJECT_OFFSET + 0)``. ``ControlledByYou`` resolves
         player_index=0; matches ``source.controller=0`` for FDC.
         ``ConditionalOnTappedCreatures`` condition (≥ 2 tapped) is met
         by FDC + Filler; trigger pushed.
         Python: ``run_beginning_of_end_step_triggers(state)`` →
         ``dispatch_event(state, Event.BEGINNING_OF_END_STEP,
         player=state.active_player())``. Same ``Controlled(YOU)``
         match; ``ConditionalOnTappedCreatures`` evaluates True.
      2. Both stacks have 1 item.
      3. Drain stacks: ``GainLife(2)`` resolves → p0 life 20 → 22.

    Observables asserted (targeted — life delta is the only effect):
      * p0 life: 20 → 22 on BOTH engines.
      * p1 life: 20 → 20 on both (untouched).

    Rust triggered-ability dict for FDC's end-step trigger::

        {
            "event": "beginning_of_end_step",
            "predicate": {"kind": "controlled_by_you"},
            "effect": {
                "kind": "conditional_on_tapped_creatures",
                "effect": {"kind": "gain_life", "amount": 2},
                "min_count": 2,
            },
        }

    Python-side bridge translates ``"beginning_of_end_step"`` →
    ``Event.BEGINNING_OF_END_STEP`` (no spelling skew — string values
    are identical). ``ControlledByYou`` predicate translates unchanged;
    ``ConditionalOnTappedCreatures`` translates via the existing
    ``"conditional_on_tapped_creatures"`` bridge arm.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef,
        DeckSpec,
        build_python_state,
        build_rust_state,
        _ta_dict_to_python_triggered_ability,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.turn import (
        run_beginning_of_end_step_triggers,
        state_based_actions as py_sba,
    )
    from mtg_bot.effects.predicates import Event, Controlled, YOU
    from mtg_bot.effects.combinators import ConditionalOnTappedCreatures
    from mtg_bot.effects.generic.life import GainLife

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Flight-Deck Coordinator printing has
    #    the expected BEGINNING_OF_END_STEP trigger shape.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Flight-Deck Coordinator")
    if real is None:
        pytest.skip("Flight-Deck Coordinator absent from active CardSource")

    assert "Creature" in real.card_types, (
        "Flight-Deck Coordinator must be a Creature"
    )
    fdc_ta = next(
        (
            ta
            for ta in real.triggered_abilities
            if ta.event == Event.BEGINNING_OF_END_STEP
        ),
        None,
    )
    assert fdc_ta is not None, (
        "Flight-Deck Coordinator must have a BEGINNING_OF_END_STEP "
        "triggered ability; abilities found: "
        f"{[(ta.event, type(ta.effect).__name__) for ta in real.triggered_abilities]}"
    )
    # Predicate shape: Controlled(YOU)
    assert isinstance(fdc_ta.predicate, Controlled), (
        f"FDC TA predicate must be Controlled; got {type(fdc_ta.predicate).__name__}"
    )
    assert fdc_ta.predicate.by == YOU, (
        f"FDC TA predicate.by must be YOU; got {fdc_ta.predicate.by!r}"
    )
    # Effect shape: ConditionalOnTappedCreatures wrapping GainLife(2)
    assert isinstance(fdc_ta.effect, ConditionalOnTappedCreatures), (
        f"FDC TA effect must be ConditionalOnTappedCreatures; "
        f"got {type(fdc_ta.effect).__name__}"
    )
    assert isinstance(fdc_ta.effect.effect, GainLife), (
        f"FDC TA inner effect must be GainLife; "
        f"got {type(fdc_ta.effect.effect).__name__}"
    )
    assert fdc_ta.effect.effect.amount == 2, (
        f"FDC TA GainLife amount must be 2; got {fdc_ta.effect.effect.amount}"
    )
    assert fdc_ta.effect.min_count == 2, (
        f"FDC TA ConditionalOnTappedCreatures min_count must be 2; "
        f"got {fdc_ta.effect.min_count}"
    )

    # ------------------------------------------------------------------
    # 2. Shared triggered-ability dict (registered on Rust; used to
    #    build the Python TriggeredAbility via the bridge).
    # ------------------------------------------------------------------
    fdc_ta_dict = {
        "event": "beginning_of_end_step",
        "predicate": {"kind": "controlled_by_you"},
        "effect": {
            "kind": "conditional_on_tapped_creatures",
            "effect": {"kind": "gain_life", "amount": 2},
            "min_count": 2,
        },
    }

    # Sanity: bridge translates the dict correctly.
    bridge_ta = _ta_dict_to_python_triggered_ability(fdc_ta_dict)
    assert bridge_ta.event == Event.BEGINNING_OF_END_STEP, (
        f"Bridge must translate 'beginning_of_end_step' to "
        f"Event.BEGINNING_OF_END_STEP; got {bridge_ta.event!r}"
    )
    assert isinstance(bridge_ta.predicate, Controlled), (
        f"Bridge predicate must be Controlled; "
        f"got {type(bridge_ta.predicate).__name__}"
    )
    assert isinstance(bridge_ta.effect, ConditionalOnTappedCreatures), (
        f"Bridge effect must be ConditionalOnTappedCreatures; "
        f"got {type(bridge_ta.effect).__name__}"
    )
    assert isinstance(bridge_ta.effect.effect, GainLife), (
        f"Bridge inner effect must be GainLife; "
        f"got {type(bridge_ta.effect.effect).__name__}"
    )

    # ------------------------------------------------------------------
    # 3. Build cross-engine states with empty decks.
    # ------------------------------------------------------------------
    spec = DeckSpec(
        card_defs=(),
        p0_library=(),
        p1_library=(),
    )
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    ZB = 2  # ZONE_BATTLEFIELD

    # ------------------------------------------------------------------
    # 4. Rust: pre-seat Flight-Deck Coordinator (tapped) + tapped filler
    #    on p0's battlefield.
    # ------------------------------------------------------------------
    rs_fdc_id = rs.register_and_inject_object(
        {
            "name": "Flight-Deck Coordinator",
            "card_types": ["Creature"],
            "power": 3,
            "toughness": 3,
            "keywords": [],
            "effects": [],
            "triggered_abilities": [fdc_ta_dict],
        },
        0, ZB,
    )
    rs_filler_id = rs.register_and_inject_object(
        {
            "name": "TappedFiller",
            "card_types": ["Creature"],
            "power": 1,
            "toughness": 1,
            "keywords": [],
            "effects": [],
            "triggered_abilities": [],
        },
        0, ZB,
    )
    # Tap both so ConditionalOnTappedCreatures condition is met.
    rs.tap_object(rs_fdc_id)
    rs.tap_object(rs_filler_id)
    assert rs.is_tapped(rs_fdc_id), "Rust: FDC must be tapped"
    assert rs.is_tapped(rs_filler_id), "Rust: Filler must be tapped"

    # Baseline Rust life totals.
    rs_p0_life0 = rs.get_life(0)
    rs_p1_life0 = rs.get_life(1)
    assert rs_p0_life0 == 20, f"Rust: p0 must start at 20 life; got {rs_p0_life0}"

    # ------------------------------------------------------------------
    # 5. Rust: advance to END_STEP (phase 10); drain resulting triggers.
    # ------------------------------------------------------------------
    PHASE_END_STEP = 10
    for _ in range(30):
        rs.advance_phase()
        if rs.current_phase() == PHASE_END_STEP:
            break

    assert rs.current_phase() == PHASE_END_STEP, (
        f"Rust: must reach PHASE_END_STEP (10); got {rs.current_phase()}"
    )

    # The FDC trigger should be on the stack (ConditionalOnTappedCreatures
    # fires if condition is met after the trigger resolves).
    assert rs.stack_size() == 1, (
        f"Rust: exactly 1 trigger (FDC gain_life conditional) must be on "
        f"the stack after advancing to END_STEP; got {rs.stack_size()}"
    )

    # Drain the trigger.
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_p0_life1 = rs.get_life(0)
    rs_p1_life1 = rs.get_life(1)
    assert rs_p0_life1 == rs_p0_life0 + 2, (
        f"Rust: p0 must gain 2 life from FDC end-step trigger; "
        f"life {rs_p0_life0} → {rs_p0_life1}"
    )
    assert rs_p1_life1 == rs_p1_life0, (
        f"Rust: p1 life must be unchanged; got {rs_p1_life1}"
    )

    # ------------------------------------------------------------------
    # 6. Python: pre-seat real FDC printing (using bridge TA) + tapped
    #    filler on p0's battlefield.
    # ------------------------------------------------------------------
    py_fdc_printing = CardPrinting(
        name="Flight-Deck Coordinator",
        mana_cost_str="{2}{W}",
        mana_cost=ManaCost(generic=2, colored=(("W", 1),)),
        type_line="Creature — Human Soldier",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Human", "Soldier"),
        power=3,
        toughness=3,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(bridge_ta,),
    )
    py_fdc = py.new_object(py_fdc_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_fdc.summoning_sick = False
    py_fdc.tapped = True   # tapped creature #1
    py_fdc.damage = 0
    py_fdc.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_fdc)

    py_filler_printing = CardPrinting(
        name="TappedFiller",
        mana_cost_str="{G}",
        mana_cost=ManaCost(generic=0, colored=(("G", 1),)),
        type_line="Creature — Beast",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Beast",),
        power=1,
        toughness=1,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(),
    )
    py_filler = py.new_object(py_filler_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_filler.summoning_sick = False
    py_filler.tapped = True   # tapped creature #2
    py_filler.damage = 0
    py_filler.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_filler)

    # Verify tapped-creature count.
    tapped_count = sum(
        1 for o in py.battlefield
        if o.tapped and o.controller_id == py.players[0].id
    )
    assert tapped_count >= 2, (
        f"Python: p0 must control ≥ 2 tapped creatures; got {tapped_count}"
    )

    # Baseline Python life totals.
    py_p0_life0 = py.players[0].life
    py_p1_life0 = py.players[1].life
    assert py_p0_life0 == 20, f"Python: p0 must start at 20 life; got {py_p0_life0}"

    # ------------------------------------------------------------------
    # 7. Python: fire beginning-of-end-step triggers manually (mirrors
    #    the Rust advance_phase dispatch site).
    # ------------------------------------------------------------------
    run_beginning_of_end_step_triggers(py)

    assert len(py.stack) == 1, (
        f"Python: exactly 1 trigger must be on the stack after "
        f"run_beginning_of_end_step_triggers; got {len(py.stack)}"
    )

    # Drain.
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    py_p0_life1 = py.players[0].life
    py_p1_life1 = py.players[1].life
    assert py_p0_life1 == py_p0_life0 + 2, (
        f"Python: p0 must gain 2 life from FDC end-step trigger; "
        f"life {py_p0_life0} → {py_p0_life1}"
    )
    assert py_p1_life1 == py_p1_life0, (
        f"Python: p1 life must be unchanged; got {py_p1_life1}"
    )

    # ------------------------------------------------------------------
    # 8. Cross-engine byte-equality on targeted observables.
    # ------------------------------------------------------------------
    assert rs_p0_life1 == py_p0_life1, (
        f"p0 life: Rust={rs_p0_life1}, Python={py_p0_life1} "
        f"(must be byte-equal — GainLife(2) resolved on BOTH engines)"
    )
    assert rs_p1_life1 == py_p1_life1, (
        f"p1 life: Rust={rs_p1_life1}, Python={py_p1_life1} "
        f"(must be byte-equal — untouched)"
    )
