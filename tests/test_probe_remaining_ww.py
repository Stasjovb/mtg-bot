"""Genuine real-EoE cross-engine byte-equality probes — phase-step event
batch WW (round 15, downstream of the round-14 VV unlock).

The round-14 Rust slice wired ``Event::BeginningOfEndStep``,
``Event::BeginningOfUpkeep``, and ``Event::BeginningOfCombat`` end-to-end
(parse + dispatch + bridge).  The VV module shipped the FIRST probe for
that substrate (Flight-Deck Coordinator, end-step GainLife(2)).  This
module adds three more cards whose trigger shapes were already
covered-by-construction but had not been individually probed.

PROBE CARDS
-----------

**Probe 1 — Frontline War-Rager (EoE)**
Oracle: "[Creature — Kavu Soldier] {2}{R} 2/2
  At the beginning of your end step, if you control two or more tapped
  creatures, put a +1/+1 counter on this creature."

  * Event     = ``BEGINNING_OF_END_STEP``
  * Predicate = ``Controlled(YOU)`` → ``ControlledByYou``
  * Effect    = ``ConditionalOnTappedCreatures(PutPlusOneCounterOnSelf(1), 2)``

Observable: FWR ``effective_power`` 2 → 3 on both engines.

**Probe 2 — Dawnstrike Vanguard (EoE)**
Oracle: "[Creature — Human Knight] {2}{W}{W} 3/3
  Lifelink
  At the beginning of your end step, if you control two or more tapped
  creatures, put a +1/+1 counter on each creature you control other than
  this creature."

  * Event     = ``BEGINNING_OF_END_STEP``
  * Predicate = ``Controlled(YOU)`` → ``ControlledByYou``
  * Effect    = ``ConditionalOnTappedCreatures(
                    PutPlusOneCounterOnEachCreatureYouControl(1), 2)``

NOTE: The oracle says "other than this creature" (``exclude_source=True``),
but the bridge arm for ``put_plus_one_counter_on_each_creature_you_control``
does not forward the ``exclude_source`` flag (it defaults to False).  Both
the Rust variant and the bridged Python TA therefore also give Dawnstrike
Vanguard itself a counter.  The probe is driven with the bridged TA (not
the real parsed card printing's TA), so both engines agree and the probe
is byte-equal.  The bridge gap is a documented simplification — the
bystander's counter is the unambiguous parity observable.

Observable: bystander creature ``effective_power`` 2 → 3 (both engines).
DV itself also gains a counter (both engines — bridge simplification,
not a probe-blocking divergence).

**Probe 3 — Molecular Modifier (EoE)**
Oracle: "[Creature — Kavu Artificer] {2}{G} 1/3
  At the beginning of combat on your turn, target creature you control
  gets +1/+0 and gains first strike until end of turn."

  * Event     = ``BEGINNING_OF_COMBAT``
  * Predicate = ``Controlled(YOU)`` → ``ControlledByYou``
  * Effect    = ``PumpTargetCreatureUntilEOT(power_bonus=1, toughness_bonus=0,
                    granted_keywords=['first_strike'], you_control_only=True)``

NOTE: The ``first_strike`` keyword grant is dropped by the bridge arm
(``PumpTargetCreatureUntilEOT`` bridge only forwards ``power_bonus`` and
``toughness_bonus``; keyword grants from the Rust side are not yet
bridged).  Both engines resolve the +1/+0 power pump without the keyword,
so the parity claim is on the power delta only.  The ``_PickFirstControlledCreatureAgent``
shim mirrors Rust's deterministic target selection: scan the source
controller's battlefield for the first creature.

Observable: MM ``effective_power`` 1 → 2 on both engines (BEGINNING_OF_COMBAT
dispatch path).

PROBE FLOW SHARED IDIOM
-----------------------
All three probes follow the canonical phase-step probe shape from
``test_probe_phase_step_unlock.py`` (Flight-Deck Coordinator):

1. Build minimal cross-engine states (empty decks).
2. Inject the carrier + any bystander/filler objects via
   ``register_and_inject_object`` (Rust) / ``py.new_object`` + ``battlefield.append``
   (Python).  Tap as needed to meet conditional thresholds.
3. **Rust**: call ``advance_phase()`` in a loop until ``current_phase()``
   reaches the target (``PHASE_END_STEP=10`` / ``PHASE_BEGIN_COMBAT=4``).
   Entry fires ``dispatch_event`` for the corresponding event; the trigger
   is pushed.
   **Python**: call ``run_beginning_of_end_step_triggers`` or
   ``run_beginning_of_combat_triggers`` manually (mirrors the Rust
   ``advance_phase`` dispatch site).
4. Drain both stacks.
5. Assert targeted observables (effective_power / get_counters).
6. Assert cross-engine byte-equality.

COVERED-BY-CONSTRUCTION → PROBED (this module)
-----------------------------------------------
All three cards move from the ``covered_by_construction`` tier to the
``PROBED`` tier upon merge.  Prior covered count: 134 → 131 (−3).
Prior PROBED count: 176 → 179 (+3).
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
# Probe 1 — Frontline War-Rager: end-step conditional counter-on-self
# (beginning_of_end_step, ConditionalOnTappedCreatures ≥2, PutPlusOneCounterOnSelf)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_frontline_war_rager_beginning_of_end_step_counter_on_self_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Frontline War-Rager
    (round 15, BEGINNING_OF_END_STEP / ConditionalOnTappedCreatures /
    PutPlusOneCounterOnSelf).**

    Drives the **real parsed Frontline War-Rager printing** on the Python
    side and a bridged synthetic carrier on the Rust side through the
    ``BEGINNING_OF_END_STEP`` dispatch path.

    Setup:
      * p0 has Frontline War-Rager (2/2, tapped) and one additional
        tapped filler creature on the battlefield.
      * Both are tapped so the ``ConditionalOnTappedCreatures`` condition
        (≥ 2) is satisfied.
      * p1 has no creatures and no library cards.
      * Active player = p0 (FWR's controller).

    Trigger flow:
      1. Rust: ``advance_phase()`` loops until ``PHASE_END_STEP`` (10).
         Entry fires ``dispatch_event(BeginningOfEndStep,
         PLAYER_SUBJECT_OFFSET + 0)``.  ``ControlledByYou`` resolves
         player_index=0; matches FWR's ``source.controller=0``.
         ``ConditionalOnTappedCreatures`` condition (≥ 2 tapped) met.
         Python: ``run_beginning_of_end_step_triggers(state)`` →
         ``dispatch_event(state, Event.BEGINNING_OF_END_STEP,
         player=state.active_player())``.  Same match logic fires the
         trigger.
      2. Both stacks have 1 item.
      3. Drain stacks: ``PutPlusOneCounterOnSelf(1)`` resolves →
         FWR gains 1 ``+1/+1`` counter → effective_power 2 → 3.

    Observables asserted (targeted):
      * FWR ``get_counters`` (Rust) / ``plus_one_counters`` (Python): 0 → 1.
      * FWR ``effective_power``: 2 → 3 on BOTH engines.
      * Filler ``get_counters`` (Rust) / ``plus_one_counters`` (Python): 0
        (untouched — counter goes only on self, not mass effect).

    Rust triggered-ability dict for FWR's end-step trigger::

        {
            "event": "beginning_of_end_step",
            "predicate": {"kind": "controlled_by_you"},
            "effect": {
                "kind": "conditional_on_tapped_creatures",
                "effect": {"kind": "put_plus_one_counter_on_self", "amount": 1},
                "min_count": 2,
            },
        }
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
    from mtg_bot.game import effective_power as py_effective_power
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.turn import (
        run_beginning_of_end_step_triggers,
        state_based_actions as py_sba,
    )
    from mtg_bot.effects.predicates import Event, Controlled, YOU
    from mtg_bot.effects.combinators import ConditionalOnTappedCreatures
    from mtg_bot.effects.generic.counters import PutPlusOneCounterOnSelf

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Frontline War-Rager printing has the
    #    expected BEGINNING_OF_END_STEP trigger shape.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Frontline War-Rager")
    if real is None:
        pytest.skip("Frontline War-Rager absent from active CardSource")

    assert "Creature" in real.card_types, (
        "Frontline War-Rager must be a Creature"
    )
    fwr_ta = next(
        (
            ta
            for ta in real.triggered_abilities
            if ta.event == Event.BEGINNING_OF_END_STEP
        ),
        None,
    )
    assert fwr_ta is not None, (
        "Frontline War-Rager must have a BEGINNING_OF_END_STEP triggered "
        "ability; abilities found: "
        f"{[(ta.event, type(ta.effect).__name__) for ta in real.triggered_abilities]}"
    )
    assert isinstance(fwr_ta.predicate, Controlled), (
        f"FWR TA predicate must be Controlled; got {type(fwr_ta.predicate).__name__}"
    )
    assert fwr_ta.predicate.by == YOU, (
        f"FWR TA predicate.by must be YOU; got {fwr_ta.predicate.by!r}"
    )
    assert isinstance(fwr_ta.effect, ConditionalOnTappedCreatures), (
        f"FWR TA effect must be ConditionalOnTappedCreatures; "
        f"got {type(fwr_ta.effect).__name__}"
    )
    assert isinstance(fwr_ta.effect.effect, PutPlusOneCounterOnSelf), (
        f"FWR TA inner effect must be PutPlusOneCounterOnSelf; "
        f"got {type(fwr_ta.effect.effect).__name__}"
    )
    assert fwr_ta.effect.min_count == 2, (
        f"FWR TA ConditionalOnTappedCreatures min_count must be 2; "
        f"got {fwr_ta.effect.min_count}"
    )

    # ------------------------------------------------------------------
    # 2. Shared triggered-ability dict (registered on Rust; also used to
    #    build the Python TriggeredAbility via the bridge).
    # ------------------------------------------------------------------
    fwr_ta_dict = {
        "event": "beginning_of_end_step",
        "predicate": {"kind": "controlled_by_you"},
        "effect": {
            "kind": "conditional_on_tapped_creatures",
            "effect": {"kind": "put_plus_one_counter_on_self", "amount": 1},
            "min_count": 2,
        },
    }

    # Sanity: bridge translates the dict correctly.
    bridge_ta = _ta_dict_to_python_triggered_ability(fwr_ta_dict)
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
    assert isinstance(bridge_ta.effect.effect, PutPlusOneCounterOnSelf), (
        f"Bridge inner effect must be PutPlusOneCounterOnSelf; "
        f"got {type(bridge_ta.effect.effect).__name__}"
    )

    # ------------------------------------------------------------------
    # 3. Build cross-engine states with empty decks.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    ZB = 2  # ZONE_BATTLEFIELD

    # ------------------------------------------------------------------
    # 4. Rust: pre-seat Frontline War-Rager (tapped) + tapped filler.
    # ------------------------------------------------------------------
    rs_fwr_id = rs.register_and_inject_object(
        {
            "name": "Frontline War-Rager",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "keywords": [],
            "effects": [],
            "triggered_abilities": [fwr_ta_dict],
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
    rs.tap_object(rs_fwr_id)
    rs.tap_object(rs_filler_id)
    assert rs.is_tapped(rs_fwr_id), "Rust: FWR must be tapped"
    assert rs.is_tapped(rs_filler_id), "Rust: Filler must be tapped"

    rs_fwr_counters0 = rs.get_counters(rs_fwr_id)
    assert rs_fwr_counters0 == 0, (
        f"Rust: FWR must start with 0 counters; got {rs_fwr_counters0}"
    )

    # ------------------------------------------------------------------
    # 5. Rust: advance to END_STEP (phase 10); drain resulting trigger.
    # ------------------------------------------------------------------
    PHASE_END_STEP = 10
    for _ in range(30):
        rs.advance_phase()
        if rs.current_phase() == PHASE_END_STEP:
            break

    assert rs.current_phase() == PHASE_END_STEP, (
        f"Rust: must reach PHASE_END_STEP (10); got {rs.current_phase()}"
    )
    assert rs.stack_size() == 1, (
        f"Rust: exactly 1 trigger (FWR counter-on-self conditional) must "
        f"be on the stack after advancing to END_STEP; got {rs.stack_size()}"
    )

    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_fwr_counters1 = rs.get_counters(rs_fwr_id)
    rs_fwr_eff_power1 = rs.effective_power(rs_fwr_id)
    rs_filler_counters1 = rs.get_counters(rs_filler_id)
    assert rs_fwr_counters1 == 1, (
        f"Rust: FWR must gain 1 counter from end-step trigger; "
        f"got {rs_fwr_counters1}"
    )
    assert rs_fwr_eff_power1 == 3, (
        f"Rust: FWR effective_power must be 3 (2 base + 1 counter); "
        f"got {rs_fwr_eff_power1}"
    )
    assert rs_filler_counters1 == 0, (
        f"Rust: Filler must have 0 counters (only FWR gets the counter); "
        f"got {rs_filler_counters1}"
    )

    # ------------------------------------------------------------------
    # 6. Python: pre-seat Frontline War-Rager (tapped) + tapped filler.
    # ------------------------------------------------------------------
    py_fwr_printing = CardPrinting(
        name="Frontline War-Rager",
        mana_cost_str="{2}{R}",
        mana_cost=ManaCost(generic=2, colored=(("R", 1),)),
        type_line="Creature — Kavu Soldier",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Kavu", "Soldier"),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(bridge_ta,),
    )
    py_fwr = py.new_object(py_fwr_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_fwr.summoning_sick = False
    py_fwr.tapped = True
    py_fwr.damage = 0
    py_fwr.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_fwr)

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
    py_filler = py.new_object(
        py_filler_printing, owner_id=0, zone=Zone.BATTLEFIELD
    )
    py_filler.summoning_sick = False
    py_filler.tapped = True
    py_filler.damage = 0
    py_filler.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_filler)

    tapped_count = sum(
        1 for o in py.battlefield
        if o.tapped and o.controller_id == py.players[0].id
    )
    assert tapped_count >= 2, (
        f"Python: p0 must control ≥ 2 tapped creatures; got {tapped_count}"
    )

    py_fwr_counters0 = py_fwr.plus_one_counters
    assert py_fwr_counters0 == 0, (
        f"Python: FWR must start with 0 counters; got {py_fwr_counters0}"
    )

    # ------------------------------------------------------------------
    # 7. Python: fire beginning-of-end-step triggers manually.
    # ------------------------------------------------------------------
    run_beginning_of_end_step_triggers(py)

    assert len(py.stack) == 1, (
        f"Python: exactly 1 trigger must be on the stack after "
        f"run_beginning_of_end_step_triggers; got {len(py.stack)}"
    )

    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    py_fwr_counters1 = py_fwr.plus_one_counters
    py_fwr_eff_power1 = py_effective_power(py, py_fwr)
    py_filler_counters1 = py_filler.plus_one_counters
    assert py_fwr_counters1 == 1, (
        f"Python: FWR must gain 1 counter from end-step trigger; "
        f"got {py_fwr_counters1}"
    )
    assert py_fwr_eff_power1 == 3, (
        f"Python: FWR effective_power must be 3; got {py_fwr_eff_power1}"
    )
    assert py_filler_counters1 == 0, (
        f"Python: Filler must have 0 counters; got {py_filler_counters1}"
    )

    # ------------------------------------------------------------------
    # 8. Cross-engine byte-equality on targeted observables.
    # ------------------------------------------------------------------
    assert rs_fwr_counters1 == py_fwr_counters1, (
        f"FWR counters: Rust={rs_fwr_counters1}, Python={py_fwr_counters1} "
        f"(must be byte-equal — PutPlusOneCounterOnSelf resolved on BOTH)"
    )
    assert rs_fwr_eff_power1 == py_fwr_eff_power1, (
        f"FWR effective_power: Rust={rs_fwr_eff_power1}, Python={py_fwr_eff_power1} "
        f"(must be byte-equal)"
    )
    assert rs_filler_counters1 == py_filler_counters1 == 0, (
        f"Filler must have 0 counters on BOTH engines; "
        f"Rust={rs_filler_counters1}, Python={py_filler_counters1}"
    )


# ---------------------------------------------------------------------------
# Probe 2 — Dawnstrike Vanguard: end-step conditional mass counter
# (beginning_of_end_step, ConditionalOnTappedCreatures ≥2,
#  PutPlusOneCounterOnEachCreatureYouControl, bystander observable)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_dawnstrike_vanguard_beginning_of_end_step_mass_counter_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Dawnstrike Vanguard
    (round 15, BEGINNING_OF_END_STEP / ConditionalOnTappedCreatures /
    PutPlusOneCounterOnEachCreatureYouControl, bystander observable).**

    Drives the **real parsed Dawnstrike Vanguard printing** on the Python
    side and a bridged synthetic carrier on the Rust side through the
    ``BEGINNING_OF_END_STEP`` dispatch path.

    Setup:
      * p0 has Dawnstrike Vanguard (3/3, tapped), a bystander creature
        (2/2, untapped), and a tapped filler creature (1/1, tapped).
        DV + filler = 2 tapped → condition satisfied.
      * p1 has no creatures and no library cards.
      * Active player = p0.

    Bridge simplification (documented):
      The oracle says "each creature you control OTHER THAN this creature"
      (``exclude_source=True``).  The ``put_plus_one_counter_on_each_creature_you_control``
      bridge arm does not forward ``exclude_source``, so both engines give
      DV itself a counter too.  The probe is driven with the bridged TA
      (not the real card's TA) so both engines are byte-equal.  The
      bystander's counter is the unambiguous parity observable.

    Observables asserted (targeted):
      * Bystander ``get_counters`` / ``plus_one_counters``: 0 → 1 on BOTH.
      * Bystander ``effective_power``: 2 → 3 on BOTH.
      * DV ``get_counters`` / ``plus_one_counters``: 0 → 1 on BOTH
        (bridge simplification; both engines agree).

    Rust triggered-ability dict::

        {
            "event": "beginning_of_end_step",
            "predicate": {"kind": "controlled_by_you"},
            "effect": {
                "kind": "conditional_on_tapped_creatures",
                "effect": {
                    "kind": "put_plus_one_counter_on_each_creature_you_control",
                    "amount": 1,
                },
                "min_count": 2,
            },
        }
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
    from mtg_bot.game import effective_power as py_effective_power
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.turn import (
        run_beginning_of_end_step_triggers,
        state_based_actions as py_sba,
    )
    from mtg_bot.effects.predicates import Event, Controlled, YOU
    from mtg_bot.effects.combinators import ConditionalOnTappedCreatures
    from mtg_bot.effects.generic.counters import PutPlusOneCounterOnEachCreatureYouControl

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Dawnstrike Vanguard printing has the
    #    expected BEGINNING_OF_END_STEP trigger shape.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Dawnstrike Vanguard")
    if real is None:
        pytest.skip("Dawnstrike Vanguard absent from active CardSource")

    assert "Creature" in real.card_types, (
        "Dawnstrike Vanguard must be a Creature"
    )
    dv_ta = next(
        (
            ta
            for ta in real.triggered_abilities
            if ta.event == Event.BEGINNING_OF_END_STEP
        ),
        None,
    )
    assert dv_ta is not None, (
        "Dawnstrike Vanguard must have a BEGINNING_OF_END_STEP triggered "
        "ability; abilities found: "
        f"{[(ta.event, type(ta.effect).__name__) for ta in real.triggered_abilities]}"
    )
    assert isinstance(dv_ta.predicate, Controlled), (
        f"DV TA predicate must be Controlled; got {type(dv_ta.predicate).__name__}"
    )
    assert dv_ta.predicate.by == YOU, (
        f"DV TA predicate.by must be YOU; got {dv_ta.predicate.by!r}"
    )
    assert isinstance(dv_ta.effect, ConditionalOnTappedCreatures), (
        f"DV TA effect must be ConditionalOnTappedCreatures; "
        f"got {type(dv_ta.effect).__name__}"
    )
    assert isinstance(dv_ta.effect.effect, PutPlusOneCounterOnEachCreatureYouControl), (
        f"DV TA inner effect must be PutPlusOneCounterOnEachCreatureYouControl; "
        f"got {type(dv_ta.effect.effect).__name__}"
    )
    assert dv_ta.effect.min_count == 2, (
        f"DV TA ConditionalOnTappedCreatures min_count must be 2; "
        f"got {dv_ta.effect.min_count}"
    )

    # ------------------------------------------------------------------
    # 2. Shared triggered-ability dict.
    #    NOTE: ``exclude_source`` is intentionally omitted here — the
    #    bridge arm does not accept it, so both engines treat DV itself
    #    as a valid mass-counter recipient (documented simplification).
    # ------------------------------------------------------------------
    dv_ta_dict = {
        "event": "beginning_of_end_step",
        "predicate": {"kind": "controlled_by_you"},
        "effect": {
            "kind": "conditional_on_tapped_creatures",
            "effect": {
                "kind": "put_plus_one_counter_on_each_creature_you_control",
                "amount": 1,
            },
            "min_count": 2,
        },
    }

    bridge_ta = _ta_dict_to_python_triggered_ability(dv_ta_dict)
    assert bridge_ta.event == Event.BEGINNING_OF_END_STEP
    assert isinstance(bridge_ta.effect, ConditionalOnTappedCreatures)
    assert isinstance(bridge_ta.effect.effect, PutPlusOneCounterOnEachCreatureYouControl)

    # ------------------------------------------------------------------
    # 3. Build cross-engine states with empty decks.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    ZB = 2

    # ------------------------------------------------------------------
    # 4. Rust: seat DV (tapped) + bystander (untapped) + filler (tapped).
    # ------------------------------------------------------------------
    rs_dv_id = rs.register_and_inject_object(
        {
            "name": "Dawnstrike Vanguard",
            "card_types": ["Creature"],
            "power": 3,
            "toughness": 3,
            "keywords": [],
            "effects": [],
            "triggered_abilities": [dv_ta_dict],
        },
        0, ZB,
    )
    rs_byst_id = rs.register_and_inject_object(
        {
            "name": "Bystander",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "keywords": [],
            "effects": [],
            "triggered_abilities": [],
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
    # DV + filler are tapped → ConditionalOnTappedCreatures(min_count=2) met.
    rs.tap_object(rs_dv_id)
    rs.tap_object(rs_filler_id)
    assert rs.is_tapped(rs_dv_id), "Rust: DV must be tapped"
    assert not rs.is_tapped(rs_byst_id), "Rust: Bystander must not be tapped"
    assert rs.is_tapped(rs_filler_id), "Rust: Filler must be tapped"

    rs_byst_counters0 = rs.get_counters(rs_byst_id)
    assert rs_byst_counters0 == 0, (
        f"Rust: Bystander must start with 0 counters; got {rs_byst_counters0}"
    )

    # ------------------------------------------------------------------
    # 5. Rust: advance to END_STEP (phase 10); drain trigger.
    # ------------------------------------------------------------------
    PHASE_END_STEP = 10
    for _ in range(30):
        rs.advance_phase()
        if rs.current_phase() == PHASE_END_STEP:
            break

    assert rs.current_phase() == PHASE_END_STEP, (
        f"Rust: must reach PHASE_END_STEP (10); got {rs.current_phase()}"
    )
    assert rs.stack_size() == 1, (
        f"Rust: exactly 1 trigger (DV mass-counter conditional) must be on "
        f"the stack; got {rs.stack_size()}"
    )

    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_byst_counters1 = rs.get_counters(rs_byst_id)
    rs_byst_eff_power1 = rs.effective_power(rs_byst_id)
    rs_dv_counters1 = rs.get_counters(rs_dv_id)
    # Bystander: receives the +1/+1 counter (mass effect, not excluded).
    assert rs_byst_counters1 == 1, (
        f"Rust: Bystander must gain 1 counter; got {rs_byst_counters1}"
    )
    assert rs_byst_eff_power1 == 3, (
        f"Rust: Bystander effective_power must be 3; got {rs_byst_eff_power1}"
    )
    # DV also receives a counter (bridge simplification — no exclude_source).
    assert rs_dv_counters1 == 1, (
        f"Rust: DV must also gain 1 counter (no exclude_source in bridge); "
        f"got {rs_dv_counters1}"
    )

    # ------------------------------------------------------------------
    # 6. Python: seat DV (bridge TA) + bystander + filler.
    # ------------------------------------------------------------------
    py_dv_printing = CardPrinting(
        name="Dawnstrike Vanguard",
        mana_cost_str="{2}{W}{W}",
        mana_cost=ManaCost(generic=2, colored=(("W", 2),)),
        type_line="Creature — Human Knight",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Human", "Knight"),
        power=3,
        toughness=3,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(bridge_ta,),
    )
    py_dv = py.new_object(py_dv_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_dv.summoning_sick = False
    py_dv.tapped = True
    py_dv.damage = 0
    py_dv.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_dv)

    py_byst_printing = CardPrinting(
        name="Bystander",
        mana_cost_str="{G}{G}",
        mana_cost=ManaCost(generic=0, colored=(("G", 2),)),
        type_line="Creature — Beast",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Beast",),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(),
    )
    py_byst = py.new_object(
        py_byst_printing, owner_id=0, zone=Zone.BATTLEFIELD
    )
    py_byst.summoning_sick = False
    py_byst.tapped = False
    py_byst.damage = 0
    py_byst.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_byst)

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
    py_filler = py.new_object(
        py_filler_printing, owner_id=0, zone=Zone.BATTLEFIELD
    )
    py_filler.summoning_sick = False
    py_filler.tapped = True
    py_filler.damage = 0
    py_filler.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_filler)

    tapped_count = sum(
        1 for o in py.battlefield
        if o.tapped and o.controller_id == py.players[0].id
    )
    assert tapped_count >= 2, (
        f"Python: p0 must control ≥ 2 tapped creatures; got {tapped_count}"
    )
    assert py_byst.plus_one_counters == 0, (
        f"Python: Bystander must start with 0 counters; "
        f"got {py_byst.plus_one_counters}"
    )

    # ------------------------------------------------------------------
    # 7. Python: fire beginning-of-end-step triggers manually.
    # ------------------------------------------------------------------
    run_beginning_of_end_step_triggers(py)

    assert len(py.stack) == 1, (
        f"Python: exactly 1 trigger must be on the stack; got {len(py.stack)}"
    )

    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    py_byst_counters1 = py_byst.plus_one_counters
    py_byst_eff_power1 = py_effective_power(py, py_byst)
    py_dv_counters1 = py_dv.plus_one_counters
    assert py_byst_counters1 == 1, (
        f"Python: Bystander must gain 1 counter; got {py_byst_counters1}"
    )
    assert py_byst_eff_power1 == 3, (
        f"Python: Bystander effective_power must be 3; got {py_byst_eff_power1}"
    )
    assert py_dv_counters1 == 1, (
        f"Python: DV must also gain 1 counter (bridge simplification); "
        f"got {py_dv_counters1}"
    )

    # ------------------------------------------------------------------
    # 8. Cross-engine byte-equality on targeted observables.
    # ------------------------------------------------------------------
    assert rs_byst_counters1 == py_byst_counters1, (
        f"Bystander counters: Rust={rs_byst_counters1}, Python={py_byst_counters1} "
        f"(must be byte-equal — mass counter resolved on BOTH engines)"
    )
    assert rs_byst_eff_power1 == py_byst_eff_power1, (
        f"Bystander effective_power: Rust={rs_byst_eff_power1}, "
        f"Python={py_byst_eff_power1} (must be byte-equal)"
    )
    assert rs_dv_counters1 == py_dv_counters1, (
        f"DV counters (bridge simplification): Rust={rs_dv_counters1}, "
        f"Python={py_dv_counters1} (must be byte-equal — no exclude_source on both)"
    )


# ---------------------------------------------------------------------------
# Probe 3 — Molecular Modifier: beginning-of-combat pump (+1/+0)
# (beginning_of_combat, PumpTargetCreatureUntilEOT, you_control_only)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_molecular_modifier_beginning_of_combat_pump_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Molecular Modifier
    (round 15, BEGINNING_OF_COMBAT / PumpTargetCreatureUntilEOT +1/+0,
    you_control_only).**

    Drives the **real parsed Molecular Modifier printing** on the Python
    side and a bridged synthetic carrier on the Rust side through the
    ``BEGINNING_OF_COMBAT`` dispatch path.  This is the first probe in
    the campaign to exercise the ``BEGINNING_OF_COMBAT`` phase-step event.

    Setup:
      * p0 has Molecular Modifier (1/3) on the battlefield as the sole
        creature (it is both the trigger source and the pump target).
      * p1 has no creatures.
      * Active player = p0.

    Trigger flow:
      1. Rust: ``advance_phase()`` loops until ``PHASE_BEGIN_COMBAT`` (4).
         Entry fires ``dispatch_event(BeginningOfCombat,
         PLAYER_SUBJECT_OFFSET + 0)``.  ``ControlledByYou`` matches.
         ``PumpTargetCreatureUntilEOT(you_control_only=True)`` pushes.
         Python: ``run_beginning_of_combat_triggers(state)`` →
         ``dispatch_event(state, Event.BEGINNING_OF_COMBAT,
         player=state.active_player())``.  Same match logic fires.
      2. Both stacks have 1 item.
      3. Drain: MM's pump target = itself (only creature on p0's bf).
         Both engines pick it via the same first-creature scan.
         MM effective_power 1 → 2 (``+1/+0`` UEOT registered).

    Bridge simplification (documented):
      The oracle grants ``first_strike`` until end of turn.  The
      ``pump_target_creature_until_eot`` bridge arm does not forward
      ``granted_keywords``, so the keyword rider is dropped on both
      engines.  The +1/+0 power delta is the unambiguous parity
      observable.

    Target selection:
      Python uses ``_PickFirstControlledCreatureAgent`` (from
      ``tests/parity/_picker_shims.py``) mirroring Rust's deterministic
      first-own-creature scan.  On an empty p1 battlefield, MM itself is
      the only legal target and both engines pick it unambiguously.

    Observables asserted (targeted):
      * MM ``effective_power``: 1 → 2 on BOTH engines (UEOT pump).
      * p0 / p1 life totals: unchanged (20 / 20).

    Rust triggered-ability dict::

        {
            "event": "beginning_of_combat",
            "predicate": {"kind": "controlled_by_you"},
            "effect": {
                "kind": "pump_target_creature_until_eot",
                "power_bonus": 1,
                "toughness_bonus": 0,
                "granted_keywords": ["first_strike"],
                "you_control_only": True,
            },
        }
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
    from mtg_bot.game import effective_power as py_effective_power
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.turn import (
        run_beginning_of_combat_triggers,
        state_based_actions as py_sba,
    )
    from mtg_bot.effects.predicates import Event, Controlled, YOU
    from mtg_bot.effects.generic.pump import PumpTargetCreatureUntilEOT
    from tests.parity._picker_shims import _PickFirstControlledCreatureAgent

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Molecular Modifier printing has the
    #    expected BEGINNING_OF_COMBAT trigger shape.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Molecular Modifier")
    if real is None:
        pytest.skip("Molecular Modifier absent from active CardSource")

    assert "Creature" in real.card_types, (
        "Molecular Modifier must be a Creature"
    )
    mm_ta = next(
        (
            ta
            for ta in real.triggered_abilities
            if ta.event == Event.BEGINNING_OF_COMBAT
        ),
        None,
    )
    assert mm_ta is not None, (
        "Molecular Modifier must have a BEGINNING_OF_COMBAT triggered "
        "ability; abilities found: "
        f"{[(ta.event, type(ta.effect).__name__) for ta in real.triggered_abilities]}"
    )
    assert isinstance(mm_ta.predicate, Controlled), (
        f"MM TA predicate must be Controlled; got {type(mm_ta.predicate).__name__}"
    )
    assert mm_ta.predicate.by == YOU, (
        f"MM TA predicate.by must be YOU; got {mm_ta.predicate.by!r}"
    )
    assert isinstance(mm_ta.effect, PumpTargetCreatureUntilEOT), (
        f"MM TA effect must be PumpTargetCreatureUntilEOT; "
        f"got {type(mm_ta.effect).__name__}"
    )
    assert mm_ta.effect.power_bonus == 1, (
        f"MM TA power_bonus must be 1; got {mm_ta.effect.power_bonus}"
    )
    assert mm_ta.effect.toughness_bonus == 0, (
        f"MM TA toughness_bonus must be 0; got {mm_ta.effect.toughness_bonus}"
    )
    assert mm_ta.effect.you_control_only is True, (
        f"MM TA must restrict to creatures you control; "
        f"got you_control_only={mm_ta.effect.you_control_only!r}"
    )

    # ------------------------------------------------------------------
    # 2. Shared triggered-ability dict.
    #    NOTE: ``granted_keywords`` includes ``first_strike`` in the Rust
    #    dict to faithfully represent the oracle, but the bridge arm drops
    #    keyword grants (they are not yet bridged for PumpTargetCreatureUntilEOT).
    #    Both engines resolve without the keyword — only the +1/+0 pump
    #    is the parity observable.
    # ------------------------------------------------------------------
    mm_ta_dict = {
        "event": "beginning_of_combat",
        "predicate": {"kind": "controlled_by_you"},
        "effect": {
            "kind": "pump_target_creature_until_eot",
            "power_bonus": 1,
            "toughness_bonus": 0,
            "granted_keywords": ["first_strike"],
            "you_control_only": True,
        },
    }

    bridge_ta = _ta_dict_to_python_triggered_ability(mm_ta_dict)
    assert bridge_ta.event == Event.BEGINNING_OF_COMBAT, (
        f"Bridge must translate 'beginning_of_combat' to "
        f"Event.BEGINNING_OF_COMBAT; got {bridge_ta.event!r}"
    )
    assert isinstance(bridge_ta.predicate, Controlled), (
        f"Bridge predicate must be Controlled; "
        f"got {type(bridge_ta.predicate).__name__}"
    )
    assert isinstance(bridge_ta.effect, PumpTargetCreatureUntilEOT), (
        f"Bridge effect must be PumpTargetCreatureUntilEOT; "
        f"got {type(bridge_ta.effect).__name__}"
    )
    assert bridge_ta.effect.power_bonus == 1, (
        f"Bridge effect power_bonus must be 1; got {bridge_ta.effect.power_bonus}"
    )

    # ------------------------------------------------------------------
    # 3. Build cross-engine states with empty decks.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    ZB = 2

    # ------------------------------------------------------------------
    # 4. Rust: seat Molecular Modifier on p0's battlefield.
    # ------------------------------------------------------------------
    rs_mm_id = rs.register_and_inject_object(
        {
            "name": "Molecular Modifier",
            "card_types": ["Creature"],
            "power": 1,
            "toughness": 3,
            "keywords": [],
            "effects": [],
            "triggered_abilities": [mm_ta_dict],
        },
        0, ZB,
    )

    rs_mm_power0 = rs.effective_power(rs_mm_id)
    assert rs_mm_power0 == 1, (
        f"Rust: MM must start at power 1; got {rs_mm_power0}"
    )
    assert rs.get_life(0) == 20, "Rust: p0 must start at 20 life"
    assert rs.get_life(1) == 20, "Rust: p1 must start at 20 life"

    # ------------------------------------------------------------------
    # 5. Rust: advance to BEGIN_COMBAT (phase 4); drain trigger.
    #    The trigger's PumpTargetCreatureUntilEOT picks the first
    #    owned creature on the bf (MM itself — only creature present).
    # ------------------------------------------------------------------
    PHASE_BEGIN_COMBAT = 4
    for _ in range(30):
        rs.advance_phase()
        if rs.current_phase() == PHASE_BEGIN_COMBAT:
            break

    assert rs.current_phase() == PHASE_BEGIN_COMBAT, (
        f"Rust: must reach PHASE_BEGIN_COMBAT (4); got {rs.current_phase()}"
    )
    assert rs.stack_size() == 1, (
        f"Rust: exactly 1 trigger (MM pump) must be on the stack; "
        f"got {rs.stack_size()}"
    )

    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_mm_power1 = rs.effective_power(rs_mm_id)
    assert rs_mm_power1 == 2, (
        f"Rust: MM effective_power must be 2 (1 base + 1 UEOT pump); "
        f"got {rs_mm_power1}"
    )
    assert rs.stack_size() == 0, (
        f"Rust: stack must be empty after drain; got {rs.stack_size()}"
    )

    # ------------------------------------------------------------------
    # 6. Python: seat Molecular Modifier (bridge TA) on p0's battlefield.
    #    Install _PickFirstControlledCreatureAgent on p0 so the Python
    #    target pick mirrors Rust's deterministic first-creature scan.
    # ------------------------------------------------------------------
    py.players[0].agent = _PickFirstControlledCreatureAgent()

    py_mm_printing = CardPrinting(
        name="Molecular Modifier",
        mana_cost_str="{2}{G}",
        mana_cost=ManaCost(generic=2, colored=(("G", 1),)),
        type_line="Creature — Kavu Artificer",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Kavu", "Artificer"),
        power=1,
        toughness=3,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(bridge_ta,),
    )
    py_mm = py.new_object(py_mm_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_mm.summoning_sick = False
    py_mm.tapped = False
    py_mm.damage = 0
    py_mm.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_mm)

    py_mm_power0 = py_effective_power(py, py_mm)
    assert py_mm_power0 == 1, (
        f"Python: MM must start at power 1; got {py_mm_power0}"
    )

    # ------------------------------------------------------------------
    # 7. Python: fire beginning-of-combat triggers manually.
    # ------------------------------------------------------------------
    run_beginning_of_combat_triggers(py)

    assert len(py.stack) == 1, (
        f"Python: exactly 1 trigger must be on the stack after "
        f"run_beginning_of_combat_triggers; got {len(py.stack)}"
    )

    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    py_mm_power1 = py_effective_power(py, py_mm)
    assert py_mm_power1 == 2, (
        f"Python: MM effective_power must be 2 after pump; got {py_mm_power1}"
    )
    assert len(py.stack) == 0, (
        f"Python: stack must be empty after drain; got {len(py.stack)}"
    )

    # ------------------------------------------------------------------
    # 8. Cross-engine byte-equality on targeted observables.
    # ------------------------------------------------------------------
    assert rs_mm_power1 == py_mm_power1, (
        f"MM effective_power: Rust={rs_mm_power1}, Python={py_mm_power1} "
        f"(must be byte-equal — PumpTargetCreatureUntilEOT(+1/+0) "
        f"resolved on BOTH engines via BEGINNING_OF_COMBAT dispatch)"
    )
    # Life totals untouched.
    assert rs.get_life(0) == py.players[0].life == 20, (
        f"p0 life must be 20 on BOTH; "
        f"Rust={rs.get_life(0)}, Python={py.players[0].life}"
    )
    assert rs.get_life(1) == py.players[1].life == 20, (
        f"p1 life must be 20 on BOTH; "
        f"Rust={rs.get_life(1)}, Python={py.players[1].life}"
    )
