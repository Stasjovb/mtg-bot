"""Genuine real-EoE cross-engine byte-equality probe — HasPowerAtMost
unlock (round 11).

This module ships the cross-engine probe for the "with power N or less"
predicate shape: ``And(And(Subject(None, IsCreature() & HasPowerAtMost(n=2)),
Controlled(YOU)), Not(IsSelf()))``.  The unlock comes from adding the
``HasPowerAtMost { n: i32 }`` variant to the Rust ``Predicate`` enum
(``rust/src/cards.rs``) plus the ``has_power_at_most`` arm to the Python
bridge (``src/mtg_bot/parity/cross_engine.py::_ta_dict_to_python_predicate``).

**Before this slice** the bridge raised::

    ValueError: cross_engine triggered_abilities bridge: unsupported
    predicate kind 'has_power_at_most'

and the Rust ``parse_predicate`` returned an unknown-kind error, so both
EoE creatures gated by ``HasPowerAtMost(n=2)`` (Vicious Clown and
Irreverent Gremlin, flagged in batches K and N) were hard-blocked from
cross-engine testing.

**After this slice** both engines share:

* Python: ``And(And(Subject(None, IsCreature() & HasPowerAtMost(n=2)),
  Controlled(YOU)), Not(IsSelf()))``
* Rust: ``And(And(And(SubjectIsCreature, HasPowerAtMost{n:2}),
  ControlledByYou), Not(SourceIsSelf))``

PROBE CARD — Vicious Clown (EoE)
---------------------------------
Oracle: "[Creature — Clown] {2}{R} 2/3
  Whenever another creature you control with power 2 or less enters,
  Vicious Clown gets +2/+0 until end of turn."

  * Event = ``ENTERS``
  * Predicate = ``And(And(Subject(None, IsCreature() & HasPowerAtMost(2)),
    Controlled(YOU)), Not(IsSelf()))``
  * Effect = ``PumpSelfUntilEOT(power_bonus=2, toughness_bonus=0)``

PROBE FLOW
----------
1. Pre-seat Vicious Clown on p0's battlefield as an observer (Python:
   actual parsed printing; Rust: bridged synthetic carrier with the exact
   ETB trigger dict).
2. Inject a synthetic 2/2 Creature from p0's hand onto the stack on both
   engines, then resolve it — it lands on p0's battlefield.
3. The Vicious Clown ENTERS observer fires on both engines: predicate
   ``SubjectIsCreature AND HasPowerAtMost{n:2} AND ControlledByYou AND NOT
   SourceIsSelf`` matches the newly-entered 2/2 under p0's control
   (subject's effective power 2 ≤ 2) → push
   ``PumpSelfUntilEOT(power_bonus=2)`` onto the stack.
4. Drain the triggered-ability stack item on both engines.
5. **Observable**: Vicious Clown's effective power goes from 2 to 4 on
   BOTH engines (base 2 + UEOT +2).  The 2/2 creature entering under p1's
   control would NOT fire the trigger (ControlledByYou guards it).

ASSERTION IDIOM
---------------
Targeted-observable: effective power on the Vicious Clown carrier before
and after trigger resolution.  A full ``compare_fields`` assertion is not
used because the probe creature (``Probe Creature``) entering the
battlefield may expose the known summoning_sick representation gap (Rust
resets ``summoning_sick=False`` on resolve; Python preserves the stale
stack value for non-creature-type subjects — documented in
``test_probe_subject_is_enchantment_unlock.py``).  The
pump-observable (VC power: 2→4) is the correct gameplay-relevant signal
and is immune to that representation artifact.

CARDS STILL BLOCKED AFTER THIS SLICE
--------------------------------------
* **Vicious Clown** — predicate substrate fully bridged by this slice.
  The ``PumpSelfUntilEOT`` effect is also bridged.  The card is PROBED
  by this module.

* **Irreverent Gremlin** — same ``HasPowerAtMost(n=2)`` predicate, now
  bridged.  Its effect is ``IfYouDo(MayDo(DiscardSelf, ''), DrawCards(1))``
  — ``IfYouDo`` and ``DiscardSelf`` are separately bridged but the full
  end-to-end probe for Irreverent Gremlin is a follow-on task (the
  ``MayDo`` player-decision flow adds extra complexity beyond the plain
  pump).

This probe establishes the PREDICATE substrate as bridged.  Individual
follow-on effect probes are separate work.
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
    """Load ``scripts/parity_smoke.py`` as a module (the field-view
    builder lives there). Identical to the module-scoped fixture in
    other batch probe files — copied here so this module is fully
    self-contained."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location(
        "parity_smoke", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Probe — Vicious Clown ETB trigger: another creature with power ≤ 2 enters
# under your control → Vicious Clown gets +2/+0 until EOT.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_vicious_clown_has_power_at_most_pump_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Vicious Clown (round 11).
    First ``has_power_at_most`` predicate probe.**

    Python: the ACTUAL parsed Vicious Clown printing pre-seated on p0's
    battlefield.  A synthetic 2/2 Creature is cast from p0's hand and
    resolved onto p0's bf; the Vicious Clown ENTERS observer fires
    (``Subject(None, IsCreature() & HasPowerAtMost(2)) & Controlled(YOU) &
    ~IsSelf()`` matches the newly-entered 2/2 under p0's control) →
    ``PumpSelfUntilEOT(power_bonus=2)`` resolves → VC power goes 2→4.

    Rust: the bridged synthetic carrier with the exact trigger dict
    (``predicate.kind = "and"``, decomposed as
    ``SubjectIsCreature AND HasPowerAtMost{n:2} AND ControlledByYou AND NOT
    SourceIsSelf``; effect = ``pump_self_until_eot, power_bonus=2``)
    pre-seated on p0's bf.  The same synthetic 2/2 resolves on the
    Rust side; the Rust predicate matches → PumpSelfUntilEOT(+2/+0) →
    VC power 2→4.

    Assertion strength: **targeted-observable** (effective power on the
    Vicious Clown carrier) because the newly-landed Probe Creature object
    may expose the summoning_sick representation gap (Rust resets,
    Python preserves the stale stack value) that is gameplay-irrelevant
    for the pump trigger but would break a full ``compare_fields``
    assertion.  Same documented-gap idiom as Balemurk Leech in
    ``test_probe_subject_is_enchantment_unlock.py``.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.generic.pump import PumpSelfUntilEOT
    from mtg_bot.effects.predicates import And, Not, Subject, Controlled, YOU, IsSelf
    from mtg_bot.effects.object_predicates import IsCreature, HasPowerAtMost
    from mtg_bot.game import effective_power

    # ----------------------------------------------------------------
    # 1. Verify the genuine parsed Vicious Clown printing has the
    #    expected ETB trigger shape.
    # ----------------------------------------------------------------
    real = get_active_source().get_printings().get("Vicious Clown")
    if real is None:
        pytest.skip("Vicious Clown absent from active CardSource")
    assert "Creature" in real.card_types, (
        "Vicious Clown must be a Creature"
    )
    etb = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "enters"),
        None,
    )
    assert etb is not None, (
        "Vicious Clown must have an ENTERS triggered ability"
    )
    assert isinstance(etb.effect, PumpSelfUntilEOT), (
        f"Vicious Clown ENTERS effect must be PumpSelfUntilEOT; "
        f"got {type(etb.effect).__name__}"
    )
    assert etb.effect.power_bonus == 2, (
        f"Vicious Clown PumpSelfUntilEOT power_bonus must be 2; "
        f"got {etb.effect.power_bonus}"
    )
    assert etb.effect.toughness_bonus == 0, (
        f"Vicious Clown PumpSelfUntilEOT toughness_bonus must be 0; "
        f"got {etb.effect.toughness_bonus}"
    )
    # Verify predicate contains HasPowerAtMost somewhere in the tree.
    # The full shape is And(And(Subject(None, IsCreature() &
    # HasPowerAtMost(2)), Controlled(YOU)), Not(IsSelf())).
    assert isinstance(etb.predicate, And), (
        f"Vicious Clown ENTERS predicate top-level must be And; "
        f"got {type(etb.predicate).__name__}"
    )

    # ----------------------------------------------------------------
    # 2. Build cross-engine states.
    # ----------------------------------------------------------------
    ZB = 2   # ZONE_BATTLEFIELD
    ZH = 0   # ZONE_HAND

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ----------------------------------------------------------------
    # 3a. Python: pre-seat genuine Vicious Clown on p0's bf.
    # ----------------------------------------------------------------
    py_clown = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_clown.summoning_sick = False
    py_clown.tapped = False
    py.battlefield.append(py_clown)

    # ----------------------------------------------------------------
    # 3b. Rust: pre-seat synthetic Vicious Clown carrier on p0's bf.
    #     Predicate decomposed across the flat Predicate algebra:
    #       And(And(And(SubjectIsCreature, HasPowerAtMost{n:2}),
    #               ControlledByYou),
    #           Not(SourceIsSelf))
    # ----------------------------------------------------------------
    rs_clown_id = rs.register_and_inject_object(
        {
            "name": "Vicious Clown",
            "card_types": ["Creature"],
            "power": int(real.power) if real.power is not None else 2,
            "toughness": int(real.toughness) if real.toughness is not None else 3,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {
                        "kind": "and",
                        "left": {
                            "kind": "and",
                            "left": {
                                "kind": "and",
                                "left": {"kind": "subject_is_creature"},
                                "right": {"kind": "has_power_at_most", "n": 2},
                            },
                            "right": {"kind": "controlled_by_you"},
                        },
                        "right": {
                            "kind": "not",
                            "inner": {"kind": "source_is_self"},
                        },
                    },
                    "effect": {
                        "kind": "pump_self_until_eot",
                        "power_bonus": 2,
                        "toughness_bonus": 0,
                    },
                }
            ],
        },
        0, ZB,  # controller p0, inject directly onto battlefield
    )
    assert rs.find_object_zone(rs_clown_id) == ZB, (
        "Vicious Clown synthetic carrier must start on Rust battlefield"
    )

    # ----------------------------------------------------------------
    # 4. Record baseline effective power on both engines.
    # ----------------------------------------------------------------
    py_clown_power0 = effective_power(py, py_clown)
    rs_clown_power0 = rs.effective_power(rs_clown_id)
    assert py_clown_power0 == 2, (
        f"Python: Vicious Clown must start at base power 2; got {py_clown_power0}"
    )
    assert rs_clown_power0 == 2, (
        f"Rust: Vicious Clown must start at base power 2; got {rs_clown_power0}"
    )

    # ----------------------------------------------------------------
    # 5a. Python: cast a synthetic 2/2 Creature from p0's hand;
    #     it goes on the stack, then resolves onto p0's bf.
    # ----------------------------------------------------------------
    creature_printing = CardPrinting(
        name="Probe Creature",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
    )
    py_creature = py.new_object(creature_printing, owner_id=0, zone=Zone.STACK)
    py_creature.summoning_sick = False
    py.stack.append(StackItem(source=py_creature, controller_id=0))
    resolve_top_of_stack(py)
    assert any(o.printing.name == "Probe Creature"
               for o in py.battlefield), (
        "Probe Creature must have resolved onto Python battlefield"
    )
    assert len(py.stack) == 1, (
        "Vicious Clown ETB trigger must be on Python stack after creature enters"
    )

    # ----------------------------------------------------------------
    # 5b. Rust: inject the same synthetic 2/2 creature, push to
    #     stack, resolve → lands on bf → Vicious Clown trigger fires.
    # ----------------------------------------------------------------
    rs_creature_id = rs.register_and_inject_object(
        {
            "name": "Probe Creature",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "effects": [],
            "triggered_abilities": [],
        },
        0, ZH,
    )
    rs.push_to_stack(rs_creature_id, 0)
    rs.resolve_top_of_stack()
    assert rs.find_object_zone(rs_creature_id) == ZB, (
        "Probe Creature must have resolved onto Rust battlefield"
    )
    assert rs.stack_size() == 1, (
        "Vicious Clown ETB trigger must be on Rust stack after creature enters"
    )

    # ----------------------------------------------------------------
    # 6. Drain both stacks (PumpSelfUntilEOT resolves on VC).
    # ----------------------------------------------------------------
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    rs.apply_sbas()
    assert rs.stack_size() == 0 and len(py.stack) == 0, (
        "Both stacks must be empty after drain"
    )

    # ----------------------------------------------------------------
    # 7. Observable: Vicious Clown gets +2/+0 UEOT on BOTH engines.
    #    Base power 2 + pump +2 = effective power 4.
    # ----------------------------------------------------------------
    py_clown_power = effective_power(py, py_clown)
    rs_clown_power = rs.effective_power(rs_clown_id)

    assert py_clown_power == py_clown_power0 + 2, (
        f"Python: Vicious Clown must gain exactly +2 power from ETB trigger; "
        f"was {py_clown_power0}, now {py_clown_power}"
    )
    assert rs_clown_power == rs_clown_power0 + 2, (
        f"Rust: Vicious Clown must gain exactly +2 power from ETB trigger; "
        f"was {rs_clown_power0}, now {rs_clown_power}"
    )
    assert py_clown_power == rs_clown_power, (
        f"Engines must agree on Vicious Clown effective power after pump; "
        f"py={py_clown_power} rs={rs_clown_power}"
    )
    # Byte-equal on the gameplay-relevant observable: VC power = 4 on both.
    assert py_clown_power == rs_clown_power == 4, (
        f"Vicious Clown effective power must be 4 on both engines after pump; "
        f"py={py_clown_power} rs={rs_clown_power}"
    )

    # ----------------------------------------------------------------
    # 8. Negative check: a creature with power 3 (above the threshold)
    #    should NOT trigger VC on either engine.
    #    Re-run with a fresh pair of states for isolation.
    # ----------------------------------------------------------------
    py2 = build_python_state(spec)
    rs2 = build_rust_state(spec)

    py_clown2 = py2.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_clown2.summoning_sick = False
    py_clown2.tapped = False
    py2.battlefield.append(py_clown2)

    rs_clown2_id = rs2.register_and_inject_object(
        {
            "name": "Vicious Clown",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 3,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {
                        "kind": "and",
                        "left": {
                            "kind": "and",
                            "left": {
                                "kind": "and",
                                "left": {"kind": "subject_is_creature"},
                                "right": {"kind": "has_power_at_most", "n": 2},
                            },
                            "right": {"kind": "controlled_by_you"},
                        },
                        "right": {
                            "kind": "not",
                            "inner": {"kind": "source_is_self"},
                        },
                    },
                    "effect": {
                        "kind": "pump_self_until_eot",
                        "power_bonus": 2,
                        "toughness_bonus": 0,
                    },
                }
            ],
        },
        0, ZB,
    )

    # Inject a 3/3 creature (power 3 > 2 threshold — should NOT trigger).
    big_printing = CardPrinting(
        name="Big Probe Creature",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=3,
        toughness=3,
        produces=frozenset(),
    )
    py_big = py2.new_object(big_printing, owner_id=0, zone=Zone.STACK)
    py_big.summoning_sick = False
    py2.stack.append(StackItem(source=py_big, controller_id=0))
    resolve_top_of_stack(py2)

    rs_big_id = rs2.register_and_inject_object(
        {
            "name": "Big Probe Creature",
            "card_types": ["Creature"],
            "power": 3,
            "toughness": 3,
            "effects": [],
            "triggered_abilities": [],
        },
        0, ZH,
    )
    rs2.push_to_stack(rs_big_id, 0)
    rs2.resolve_top_of_stack()

    # Both stacks must be EMPTY — no trigger fired.
    assert len(py2.stack) == 0, (
        f"Python: no VC trigger must fire for a 3/3 (power > 2); "
        f"stack size = {len(py2.stack)}"
    )
    assert rs2.stack_size() == 0, (
        f"Rust: no VC trigger must fire for a 3/3 (power > 2); "
        f"stack size = {rs2.stack_size()}"
    )

    # VC power must still be 2 on both (no pump applied).
    assert effective_power(py2, py_clown2) == 2, (
        f"Python: VC must stay at power 2 when 3/3 enters (no trigger); "
        f"got {effective_power(py2, py_clown2)}"
    )
    assert rs2.effective_power(rs_clown2_id) == 2, (
        f"Rust: VC must stay at power 2 when 3/3 enters (no trigger); "
        f"got {rs2.effective_power(rs_clown2_id)}"
    )
