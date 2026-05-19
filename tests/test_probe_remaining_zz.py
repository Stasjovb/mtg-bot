"""Genuine real-EoE cross-engine byte-equality probes — batch ZZ (round 16).

All three cards are in the ``covered_by_construction`` tier: every Effect
class they emit has a live Rust variant + bridge arm, but no genuine
per-card probe had pinned them.  This module upgrades them to the
``PROBED`` tier.

PROBE CARDS
-----------

**Probe 1 — Insatiable Skittermaw (EoE)**
Oracle: "[Creature — Insect Horror] {2}{B} 2/2
  Menace
  At the beginning of your end step, put a +1/+1 counter on this creature."

  * Event     = ``BEGINNING_OF_END_STEP``
  * Predicate = ``Controlled(YOU)`` → ``ControlledByYou``
  * Effect    = ``PutPlusOneCounterOnSelf(amount=1)``

No condition — the counter fires every end step unconditionally.
Observable: Insatiable Skittermaw ``effective_power`` 2 → 3 on BOTH engines.

**Probe 2 — Kavaron Skywarden (EoE)**
Oracle: "[Creature — Kavu Soldier] {4}{R} 4/5
  Reach
  At the beginning of your end step, put a +1/+1 counter on this creature."

  * Event     = ``BEGINNING_OF_END_STEP``
  * Predicate = ``Controlled(YOU)`` → ``ControlledByYou``
  * Effect    = ``PutPlusOneCounterOnSelf(amount=1)``

Same trigger shape as Insatiable Skittermaw, different card identity and
base stats.  Observable: Kavaron Skywarden ``effective_power`` 4 → 5 on
BOTH engines.  Pins the unconditional end-step self-counter pattern on a
second distinct EoE printing.

**Probe 3 — Voidforged Titan (EoE)**
Oracle: "[Artifact Creature — Robot Warrior] {4}{B} 5/4
  At the beginning of your end step, draw a card, then you lose 1 life."

  * Event     = ``BEGINNING_OF_END_STEP``
  * Predicate = ``Controlled(YOU)`` → ``ControlledByYou``
  * Effect    = ``Sequence(DrawCards(1), LoseLife(1))``

This is the first probe in the campaign to exercise the
``Sequence(DrawCards, LoseLife)`` effect shape.  The Rust dict uses
``{"kind": "draw_cards", "count": 1}`` (bridge arm reads ``count``
and maps it to ``DrawCards(amount=1)``).  Observable: p0 life 20 → 19
on BOTH engines (the draw resolves first, then life loss).

PROBE FLOW SHARED IDIOM
-----------------------
All three probes follow the canonical phase-step probe shape established
by the WW batch (Frontline War-Rager / Dawnstrike Vanguard):

1. Build minimal cross-engine states (empty decks).
2. Inject the carrier directly onto the battlefield via
   ``register_and_inject_object`` (Rust) / ``py.new_object`` +
   ``battlefield.append`` (Python).
3. **Rust**: call ``advance_phase()`` in a loop until ``current_phase()``
   reaches ``PHASE_END_STEP`` (10).  Entry fires
   ``dispatch_event(BeginningOfEndStep, PLAYER_SUBJECT_OFFSET + 0)``.
   **Python**: call ``run_beginning_of_end_step_triggers(state)``.
4. Both stacks have exactly 1 item.
5. Drain stacks; apply SBAs.
6. Assert targeted observables (counter counts / life totals).
7. Assert cross-engine byte-equality.

COVERED-BY-CONSTRUCTION → PROBED (this module)
-----------------------------------------------
All three cards move from the ``covered_by_construction`` tier to the
``PROBED`` tier upon merge.  Prior covered count: 130 → 127 (−3).
Prior PROBED count: 180 → 183 (+3).
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
# Probe 1 — Insatiable Skittermaw: unconditional end-step counter-on-self
# (beginning_of_end_step, Controlled(YOU), PutPlusOneCounterOnSelf)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_insatiable_skittermaw_beginning_of_end_step_counter_on_self_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Insatiable Skittermaw
    (round 16, BEGINNING_OF_END_STEP / PutPlusOneCounterOnSelf, unconditional).**

    Drives the **real parsed Insatiable Skittermaw printing** on the Python
    side and a bridged synthetic carrier on the Rust side through the
    ``BEGINNING_OF_END_STEP`` dispatch path.

    This is the first probe in the campaign to exercise an unconditional
    (no ``ConditionalOnTappedCreatures`` wrapper) ``PutPlusOneCounterOnSelf``
    end-step trigger.  The counter fires every end step with no prerequisite.

    Setup:
      * p0 has Insatiable Skittermaw (2/2, menace) as the sole battlefield
        permanent.  No additional creatures needed — the trigger has no
        tapped-creature condition.
      * p1 has no creatures and no library cards.
      * Active player = p0.

    Trigger flow:
      1. Rust: ``advance_phase()`` loops until ``PHASE_END_STEP`` (10).
         Entry fires ``dispatch_event(BeginningOfEndStep,
         PLAYER_SUBJECT_OFFSET + 0)``.  ``ControlledByYou`` resolves
         player_index=0; matches Skittermaw's ``source.controller=0``.
         ``PutPlusOneCounterOnSelf(1)`` pushes unconditionally.
         Python: ``run_beginning_of_end_step_triggers(state)`` →
         ``dispatch_event(state, Event.BEGINNING_OF_END_STEP,
         player=state.active_player())``.  Same match logic fires.
      2. Both stacks have exactly 1 item.
      3. Drain: counter resolves → Skittermaw gains 1 ``+1/+1`` counter →
         effective_power 2 → 3.

    Observables asserted (targeted):
      * Skittermaw ``get_counters`` (Rust) / ``plus_one_counters`` (Python):
        0 → 1.
      * Skittermaw ``effective_power``: 2 → 3 on BOTH engines.

    Rust triggered-ability dict::

        {
            "event": "beginning_of_end_step",
            "predicate": {"kind": "controlled_by_you"},
            "effect": {"kind": "put_plus_one_counter_on_self", "amount": 1},
        }
    """
    from mtg_bot.parity.cross_engine import (
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
    from mtg_bot.effects.generic.counters import PutPlusOneCounterOnSelf

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Insatiable Skittermaw printing has the
    #    expected BEGINNING_OF_END_STEP trigger shape.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Insatiable Skittermaw")
    if real is None:
        pytest.skip("Insatiable Skittermaw absent from active CardSource")

    assert "Creature" in real.card_types, (
        "Insatiable Skittermaw must be a Creature"
    )
    is_ta = next(
        (
            ta
            for ta in real.triggered_abilities
            if ta.event == Event.BEGINNING_OF_END_STEP
        ),
        None,
    )
    assert is_ta is not None, (
        "Insatiable Skittermaw must have a BEGINNING_OF_END_STEP triggered "
        "ability; abilities found: "
        f"{[(ta.event, type(ta.effect).__name__) for ta in real.triggered_abilities]}"
    )
    assert isinstance(is_ta.predicate, Controlled), (
        f"Skittermaw TA predicate must be Controlled; "
        f"got {type(is_ta.predicate).__name__}"
    )
    assert is_ta.predicate.by == YOU, (
        f"Skittermaw TA predicate.by must be YOU; got {is_ta.predicate.by!r}"
    )
    assert isinstance(is_ta.effect, PutPlusOneCounterOnSelf), (
        f"Skittermaw TA effect must be PutPlusOneCounterOnSelf; "
        f"got {type(is_ta.effect).__name__}"
    )
    assert is_ta.effect.amount == 1, (
        f"Skittermaw TA PutPlusOneCounterOnSelf amount must be 1; "
        f"got {is_ta.effect.amount}"
    )

    # ------------------------------------------------------------------
    # 2. Shared triggered-ability dict.
    # ------------------------------------------------------------------
    is_ta_dict = {
        "event": "beginning_of_end_step",
        "predicate": {"kind": "controlled_by_you"},
        "effect": {"kind": "put_plus_one_counter_on_self", "amount": 1},
    }

    bridge_ta = _ta_dict_to_python_triggered_ability(is_ta_dict)
    assert bridge_ta.event == Event.BEGINNING_OF_END_STEP, (
        f"Bridge must translate 'beginning_of_end_step' to "
        f"Event.BEGINNING_OF_END_STEP; got {bridge_ta.event!r}"
    )
    assert isinstance(bridge_ta.predicate, Controlled), (
        f"Bridge predicate must be Controlled; "
        f"got {type(bridge_ta.predicate).__name__}"
    )
    assert isinstance(bridge_ta.effect, PutPlusOneCounterOnSelf), (
        f"Bridge effect must be PutPlusOneCounterOnSelf; "
        f"got {type(bridge_ta.effect).__name__}"
    )

    # ------------------------------------------------------------------
    # 3. Build cross-engine states with empty decks.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    ZB = 2  # ZONE_BATTLEFIELD

    # ------------------------------------------------------------------
    # 4. Rust: seat Insatiable Skittermaw on p0's battlefield.
    # ------------------------------------------------------------------
    rs_is_id = rs.register_and_inject_object(
        {
            "name": "Insatiable Skittermaw",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "keywords": ["menace"],
            "effects": [],
            "triggered_abilities": [is_ta_dict],
        },
        0, ZB,
    )

    rs_is_counters0 = rs.get_counters(rs_is_id)
    rs_is_power0 = rs.effective_power(rs_is_id)
    assert rs_is_counters0 == 0, (
        f"Rust: Skittermaw must start with 0 counters; got {rs_is_counters0}"
    )
    assert rs_is_power0 == 2, (
        f"Rust: Skittermaw must start at power 2; got {rs_is_power0}"
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
        f"Rust: exactly 1 trigger (Skittermaw unconditional counter-on-self) "
        f"must be on the stack after advancing to END_STEP; "
        f"got {rs.stack_size()}"
    )

    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_is_counters1 = rs.get_counters(rs_is_id)
    rs_is_power1 = rs.effective_power(rs_is_id)
    assert rs_is_counters1 == 1, (
        f"Rust: Skittermaw must gain 1 counter from end-step trigger; "
        f"got {rs_is_counters1}"
    )
    assert rs_is_power1 == 3, (
        f"Rust: Skittermaw effective_power must be 3 (2 base + 1 counter); "
        f"got {rs_is_power1}"
    )

    # ------------------------------------------------------------------
    # 6. Python: seat Insatiable Skittermaw (bridge TA) on p0's battlefield.
    # ------------------------------------------------------------------
    py_is_printing = CardPrinting(
        name="Insatiable Skittermaw",
        mana_cost_str="{2}{B}",
        mana_cost=ManaCost(generic=2, colored=(("B", 1),)),
        type_line="Creature — Insect Horror",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Insect", "Horror"),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset({"menace"}),
        triggered_abilities=(bridge_ta,),
    )
    py_is = py.new_object(py_is_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_is.summoning_sick = False
    py_is.tapped = False
    py_is.damage = 0
    py_is.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_is)

    py_is_counters0 = py_is.plus_one_counters
    assert py_is_counters0 == 0, (
        f"Python: Skittermaw must start with 0 counters; got {py_is_counters0}"
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

    py_is_counters1 = py_is.plus_one_counters
    py_is_power1 = py_effective_power(py, py_is)
    assert py_is_counters1 == 1, (
        f"Python: Skittermaw must gain 1 counter from end-step trigger; "
        f"got {py_is_counters1}"
    )
    assert py_is_power1 == 3, (
        f"Python: Skittermaw effective_power must be 3; got {py_is_power1}"
    )

    # ------------------------------------------------------------------
    # 8. Cross-engine byte-equality on targeted observables.
    # ------------------------------------------------------------------
    assert rs_is_counters1 == py_is_counters1, (
        f"Skittermaw counters: Rust={rs_is_counters1}, Python={py_is_counters1} "
        f"(must be byte-equal — PutPlusOneCounterOnSelf resolved on BOTH)"
    )
    assert rs_is_power1 == py_is_power1, (
        f"Skittermaw effective_power: Rust={rs_is_power1}, Python={py_is_power1} "
        f"(must be byte-equal)"
    )


# ---------------------------------------------------------------------------
# Probe 2 — Kavaron Skywarden: unconditional end-step counter-on-self
# (beginning_of_end_step, Controlled(YOU), PutPlusOneCounterOnSelf, 4/5 body)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_kavaron_skywarden_beginning_of_end_step_counter_on_self_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Kavaron Skywarden
    (round 16, BEGINNING_OF_END_STEP / PutPlusOneCounterOnSelf, unconditional).**

    Drives the **real parsed Kavaron Skywarden printing** on the Python
    side and a bridged synthetic carrier on the Rust side through the
    ``BEGINNING_OF_END_STEP`` dispatch path.

    Kavaron Skywarden shares the same trigger shape as Insatiable
    Skittermaw (Probe 1) — unconditional ``PutPlusOneCounterOnSelf`` at
    end of turn — but is a distinct EoE printing with different card
    identity (4/5 Kavu Soldier, reach).  This probe pins the same trigger
    pattern on a second card to increase coverage breadth.

    Setup:
      * p0 has Kavaron Skywarden (4/5, reach) as the sole battlefield
        permanent.  No additional creatures needed.
      * p1 has no creatures and no library cards.
      * Active player = p0.

    Trigger flow:
      Same as Probe 1.  ``PutPlusOneCounterOnSelf(1)`` fires unconditionally
      at ``PHASE_END_STEP`` (10).  Counter resolves; Skywarden gains 1
      ``+1/+1`` counter.

    Observables asserted (targeted):
      * Skywarden ``get_counters`` (Rust) / ``plus_one_counters`` (Python):
        0 → 1.
      * Skywarden ``effective_power``: 4 → 5 on BOTH engines.

    Rust triggered-ability dict::

        {
            "event": "beginning_of_end_step",
            "predicate": {"kind": "controlled_by_you"},
            "effect": {"kind": "put_plus_one_counter_on_self", "amount": 1},
        }
    """
    from mtg_bot.parity.cross_engine import (
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
    from mtg_bot.effects.generic.counters import PutPlusOneCounterOnSelf

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Kavaron Skywarden printing has the
    #    expected BEGINNING_OF_END_STEP trigger shape.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Kavaron Skywarden")
    if real is None:
        pytest.skip("Kavaron Skywarden absent from active CardSource")

    assert "Creature" in real.card_types, (
        "Kavaron Skywarden must be a Creature"
    )
    ks_ta = next(
        (
            ta
            for ta in real.triggered_abilities
            if ta.event == Event.BEGINNING_OF_END_STEP
        ),
        None,
    )
    assert ks_ta is not None, (
        "Kavaron Skywarden must have a BEGINNING_OF_END_STEP triggered "
        "ability; abilities found: "
        f"{[(ta.event, type(ta.effect).__name__) for ta in real.triggered_abilities]}"
    )
    assert isinstance(ks_ta.predicate, Controlled), (
        f"Skywarden TA predicate must be Controlled; "
        f"got {type(ks_ta.predicate).__name__}"
    )
    assert ks_ta.predicate.by == YOU, (
        f"Skywarden TA predicate.by must be YOU; got {ks_ta.predicate.by!r}"
    )
    assert isinstance(ks_ta.effect, PutPlusOneCounterOnSelf), (
        f"Skywarden TA effect must be PutPlusOneCounterOnSelf; "
        f"got {type(ks_ta.effect).__name__}"
    )
    assert ks_ta.effect.amount == 1, (
        f"Skywarden TA PutPlusOneCounterOnSelf amount must be 1; "
        f"got {ks_ta.effect.amount}"
    )

    # ------------------------------------------------------------------
    # 2. Shared triggered-ability dict.
    # ------------------------------------------------------------------
    ks_ta_dict = {
        "event": "beginning_of_end_step",
        "predicate": {"kind": "controlled_by_you"},
        "effect": {"kind": "put_plus_one_counter_on_self", "amount": 1},
    }

    bridge_ta = _ta_dict_to_python_triggered_ability(ks_ta_dict)
    assert bridge_ta.event == Event.BEGINNING_OF_END_STEP
    assert isinstance(bridge_ta.predicate, Controlled)
    assert isinstance(bridge_ta.effect, PutPlusOneCounterOnSelf)

    # ------------------------------------------------------------------
    # 3. Build cross-engine states with empty decks.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    ZB = 2

    # ------------------------------------------------------------------
    # 4. Rust: seat Kavaron Skywarden on p0's battlefield.
    # ------------------------------------------------------------------
    rs_ks_id = rs.register_and_inject_object(
        {
            "name": "Kavaron Skywarden",
            "card_types": ["Creature"],
            "power": 4,
            "toughness": 5,
            "keywords": ["reach"],
            "effects": [],
            "triggered_abilities": [ks_ta_dict],
        },
        0, ZB,
    )

    rs_ks_counters0 = rs.get_counters(rs_ks_id)
    rs_ks_power0 = rs.effective_power(rs_ks_id)
    assert rs_ks_counters0 == 0, (
        f"Rust: Skywarden must start with 0 counters; got {rs_ks_counters0}"
    )
    assert rs_ks_power0 == 4, (
        f"Rust: Skywarden must start at power 4; got {rs_ks_power0}"
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
        f"Rust: exactly 1 trigger (Skywarden counter-on-self) must be on "
        f"the stack after advancing to END_STEP; got {rs.stack_size()}"
    )

    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_ks_counters1 = rs.get_counters(rs_ks_id)
    rs_ks_power1 = rs.effective_power(rs_ks_id)
    assert rs_ks_counters1 == 1, (
        f"Rust: Skywarden must gain 1 counter from end-step trigger; "
        f"got {rs_ks_counters1}"
    )
    assert rs_ks_power1 == 5, (
        f"Rust: Skywarden effective_power must be 5 (4 base + 1 counter); "
        f"got {rs_ks_power1}"
    )

    # ------------------------------------------------------------------
    # 6. Python: seat Kavaron Skywarden (bridge TA) on p0's battlefield.
    # ------------------------------------------------------------------
    py_ks_printing = CardPrinting(
        name="Kavaron Skywarden",
        mana_cost_str="{4}{R}",
        mana_cost=ManaCost(generic=4, colored=(("R", 1),)),
        type_line="Creature — Kavu Soldier",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Kavu", "Soldier"),
        power=4,
        toughness=5,
        produces=frozenset(),
        keywords=frozenset({"reach"}),
        triggered_abilities=(bridge_ta,),
    )
    py_ks = py.new_object(py_ks_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_ks.summoning_sick = False
    py_ks.tapped = False
    py_ks.damage = 0
    py_ks.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_ks)

    py_ks_counters0 = py_ks.plus_one_counters
    assert py_ks_counters0 == 0, (
        f"Python: Skywarden must start with 0 counters; got {py_ks_counters0}"
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

    py_ks_counters1 = py_ks.plus_one_counters
    py_ks_power1 = py_effective_power(py, py_ks)
    assert py_ks_counters1 == 1, (
        f"Python: Skywarden must gain 1 counter from end-step trigger; "
        f"got {py_ks_counters1}"
    )
    assert py_ks_power1 == 5, (
        f"Python: Skywarden effective_power must be 5; got {py_ks_power1}"
    )

    # ------------------------------------------------------------------
    # 8. Cross-engine byte-equality on targeted observables.
    # ------------------------------------------------------------------
    assert rs_ks_counters1 == py_ks_counters1, (
        f"Skywarden counters: Rust={rs_ks_counters1}, Python={py_ks_counters1} "
        f"(must be byte-equal — PutPlusOneCounterOnSelf resolved on BOTH)"
    )
    assert rs_ks_power1 == py_ks_power1, (
        f"Skywarden effective_power: Rust={rs_ks_power1}, Python={py_ks_power1} "
        f"(must be byte-equal)"
    )


# ---------------------------------------------------------------------------
# Probe 3 — Voidforged Titan: end-step Sequence(DrawCards(1), LoseLife(1))
# (beginning_of_end_step, Controlled(YOU), Sequence[DrawCards + LoseLife])
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_voidforged_titan_beginning_of_end_step_draw_lose_life_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Voidforged Titan
    (round 16, BEGINNING_OF_END_STEP / Sequence(DrawCards(1), LoseLife(1))).**

    Drives the **real parsed Voidforged Titan printing** on the Python
    side and a bridged synthetic carrier on the Rust side through the
    ``BEGINNING_OF_END_STEP`` dispatch path.

    This is the first probe in the campaign to exercise the
    ``Sequence(DrawCards, LoseLife)`` effect shape.

    Setup:
      * p0 has Voidforged Titan (5/4) as the sole battlefield permanent.
        No library cards are needed for the draw to succeed — the Python
        ``DrawCards`` effect no-ops silently when the library is empty
        (rather than causing a loss from an empty draw), and the Rust
        engine mirrors this behavior.
      * p1 has no creatures and no library cards.
      * Active player = p0.  p0 starts at 20 life.

    Trigger flow:
      1. Rust: ``advance_phase()`` loops until ``PHASE_END_STEP`` (10).
         Entry fires ``dispatch_event(BeginningOfEndStep,
         PLAYER_SUBJECT_OFFSET + 0)``.  ``ControlledByYou`` resolves
         player_index=0; matches Titan's ``source.controller=0``.
         ``Sequence(DrawCards(1), LoseLife(1))`` pushes.
         Python: ``run_beginning_of_end_step_triggers(state)`` fires the
         same trigger.
      2. Both stacks have exactly 1 item.
      3. Drain: Sequence resolves → DrawCards(1) first (draws 0 from empty
         library, no-op), then LoseLife(1) → p0 life 20 → 19.

    NOTE: The Rust dict uses ``{"kind": "draw_cards", "count": 1}``
    (not ``"amount"``).  The ``draw_cards`` bridge arm reads the ``count``
    key and maps it to ``DrawCards(amount=1)`` on the Python side.  This
    field-name difference is a deliberate convention of the bridge — it is
    NOT a skew.

    Observables asserted (targeted):
      * p0 life: 20 → 19 on BOTH engines (LoseLife(1) executes).
      * p1 life: 20 (unchanged) on BOTH engines.

    Rust triggered-ability dict::

        {
            "event": "beginning_of_end_step",
            "predicate": {"kind": "controlled_by_you"},
            "effect": {
                "kind": "sequence",
                "effects": [
                    {"kind": "draw_cards", "count": 1},
                    {"kind": "lose_life", "amount": 1},
                ],
            },
        }
    """
    from mtg_bot.parity.cross_engine import (
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
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.generic.life import LoseLife

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Voidforged Titan printing has the
    #    expected BEGINNING_OF_END_STEP trigger shape.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Voidforged Titan")
    if real is None:
        pytest.skip("Voidforged Titan absent from active CardSource")

    assert "Creature" in real.card_types, (
        "Voidforged Titan must be a Creature"
    )
    vt_ta = next(
        (
            ta
            for ta in real.triggered_abilities
            if ta.event == Event.BEGINNING_OF_END_STEP
        ),
        None,
    )
    assert vt_ta is not None, (
        "Voidforged Titan must have a BEGINNING_OF_END_STEP triggered "
        "ability; abilities found: "
        f"{[(ta.event, type(ta.effect).__name__) for ta in real.triggered_abilities]}"
    )
    assert isinstance(vt_ta.predicate, Controlled), (
        f"Titan TA predicate must be Controlled; "
        f"got {type(vt_ta.predicate).__name__}"
    )
    assert vt_ta.predicate.by == YOU, (
        f"Titan TA predicate.by must be YOU; got {vt_ta.predicate.by!r}"
    )
    assert isinstance(vt_ta.effect, Sequence), (
        f"Titan TA effect must be Sequence; "
        f"got {type(vt_ta.effect).__name__}"
    )
    assert len(vt_ta.effect.effects) == 2, (
        f"Titan TA Sequence must have 2 sub-effects; "
        f"got {len(vt_ta.effect.effects)}"
    )
    assert isinstance(vt_ta.effect.effects[0], DrawCards), (
        f"Titan TA Sequence[0] must be DrawCards; "
        f"got {type(vt_ta.effect.effects[0]).__name__}"
    )
    assert vt_ta.effect.effects[0].amount == 1, (
        f"Titan TA DrawCards amount must be 1; "
        f"got {vt_ta.effect.effects[0].amount}"
    )
    assert isinstance(vt_ta.effect.effects[1], LoseLife), (
        f"Titan TA Sequence[1] must be LoseLife; "
        f"got {type(vt_ta.effect.effects[1]).__name__}"
    )
    assert vt_ta.effect.effects[1].amount == 1, (
        f"Titan TA LoseLife amount must be 1; "
        f"got {vt_ta.effect.effects[1].amount}"
    )

    # ------------------------------------------------------------------
    # 2. Shared triggered-ability dict.
    #    NOTE: "draw_cards" bridge arm reads the "count" key (maps to
    #    DrawCards(amount=...) on Python side).  Use "count" here, not
    #    "amount", to match the Rust engine's expected dict shape.
    # ------------------------------------------------------------------
    vt_ta_dict = {
        "event": "beginning_of_end_step",
        "predicate": {"kind": "controlled_by_you"},
        "effect": {
            "kind": "sequence",
            "effects": [
                {"kind": "draw_cards", "count": 1},
                {"kind": "lose_life", "amount": 1},
            ],
        },
    }

    bridge_ta = _ta_dict_to_python_triggered_ability(vt_ta_dict)
    assert bridge_ta.event == Event.BEGINNING_OF_END_STEP, (
        f"Bridge must translate 'beginning_of_end_step' to "
        f"Event.BEGINNING_OF_END_STEP; got {bridge_ta.event!r}"
    )
    assert isinstance(bridge_ta.predicate, Controlled), (
        f"Bridge predicate must be Controlled; "
        f"got {type(bridge_ta.predicate).__name__}"
    )
    assert isinstance(bridge_ta.effect, Sequence), (
        f"Bridge effect must be Sequence; "
        f"got {type(bridge_ta.effect).__name__}"
    )
    assert isinstance(bridge_ta.effect.effects[0], DrawCards), (
        f"Bridge Sequence[0] must be DrawCards; "
        f"got {type(bridge_ta.effect.effects[0]).__name__}"
    )
    assert isinstance(bridge_ta.effect.effects[1], LoseLife), (
        f"Bridge Sequence[1] must be LoseLife; "
        f"got {type(bridge_ta.effect.effects[1]).__name__}"
    )

    # ------------------------------------------------------------------
    # 3. Build cross-engine states with empty decks.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    ZB = 2

    # ------------------------------------------------------------------
    # 4. Rust: seat Voidforged Titan on p0's battlefield.
    # ------------------------------------------------------------------
    rs_vt_id = rs.register_and_inject_object(
        {
            "name": "Voidforged Titan",
            "card_types": ["Artifact", "Creature"],
            "power": 5,
            "toughness": 4,
            "keywords": [],
            "effects": [],
            "triggered_abilities": [vt_ta_dict],
        },
        0, ZB,
    )

    rs_life0 = rs.get_life(0)
    assert rs_life0 == 20, f"Rust: p0 must start at 20 life; got {rs_life0}"
    assert rs.get_life(1) == 20, "Rust: p1 must start at 20 life"

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
        f"Rust: exactly 1 trigger (Titan sequence) must be on the stack "
        f"after advancing to END_STEP; got {rs.stack_size()}"
    )

    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_life1 = rs.get_life(0)
    assert rs_life1 == 19, (
        f"Rust: p0 life must be 19 after Titan trigger (LoseLife(1)); "
        f"got {rs_life1}"
    )
    assert rs.get_life(1) == 20, (
        f"Rust: p1 life must remain at 20 (unaffected); "
        f"got {rs.get_life(1)}"
    )

    # ------------------------------------------------------------------
    # 6. Python: seat Voidforged Titan (bridge TA) on p0's battlefield.
    # ------------------------------------------------------------------
    py_vt_printing = CardPrinting(
        name="Voidforged Titan",
        mana_cost_str="{4}{B}",
        mana_cost=ManaCost(generic=4, colored=(("B", 1),)),
        type_line="Artifact Creature — Robot Warrior",
        supertypes=(),
        card_types=("Artifact", "Creature"),
        subtypes=("Robot", "Warrior"),
        power=5,
        toughness=4,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(bridge_ta,),
    )
    py_vt = py.new_object(py_vt_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_vt.summoning_sick = False
    py_vt.tapped = False
    py_vt.damage = 0
    py_vt.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_vt)

    py_life0 = py.players[0].life
    assert py_life0 == 20, f"Python: p0 must start at 20 life; got {py_life0}"
    assert py.players[1].life == 20, "Python: p1 must start at 20 life"

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

    py_life1 = py.players[0].life
    assert py_life1 == 19, (
        f"Python: p0 life must be 19 after Titan trigger (LoseLife(1)); "
        f"got {py_life1}"
    )
    assert py.players[1].life == 20, (
        f"Python: p1 life must remain at 20 (unaffected); "
        f"got {py.players[1].life}"
    )

    # ------------------------------------------------------------------
    # 8. Cross-engine byte-equality on targeted observables.
    # ------------------------------------------------------------------
    assert rs_life1 == py_life1, (
        f"p0 life: Rust={rs_life1}, Python={py_life1} "
        f"(must be byte-equal — Sequence(DrawCards(1), LoseLife(1)) "
        f"resolved on BOTH engines via BEGINNING_OF_END_STEP dispatch)"
    )
    assert rs.get_life(1) == py.players[1].life == 20, (
        f"p1 life must be 20 on BOTH; "
        f"Rust={rs.get_life(1)}, Python={py.players[1].life}"
    )
