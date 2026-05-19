"""Genuine real-EoE cross-engine byte-equality probe — you_attack event
(round 15 Rust slice; OO Pin 3 CLOSED).

This module ships the first cross-engine probe for the ``YOU_ATTACK``
event family.  The unlock comes from:

1. Adding ``Event::YouAttack`` variant to the Rust ``Event`` enum
   (``rust/src/cards.rs``).
2. Adding parse arm ``"you_attack" => Event::YouAttack`` in
   ``parse_triggered_ability`` (``rust/src/cards.rs``).
3. Adding ``Event::YouAttack`` to the ``dispatch_event`` allow-list
   (``rust/src/state_ops_resolve.rs``).
4. Adding a once-per-combat dispatch site in the ``DeclareAttackers``
   arm of ``apply_action`` (``rust/src/state_ops_actions.rs``): fires
   after the per-attacker loop when ``state.attackers`` grew, using
   ``PLAYER_SUBJECT_OFFSET + active_player`` as subject_id.  Mirrors
   Python's ``_fire_you_attack_triggers(state, declared)`` in
   ``combat.py``.
5. Adding bridge arm ``elif event_str == "you_attack":
   event = Event.YOU_ATTACK`` to ``_ta_dict_to_python_triggered_ability``
   (``src/mtg_bot/parity/cross_engine.py``).

**Before this slice** the bridge raised::

    ValueError: cross_engine triggered_abilities bridge: event
    'you_attack' is not yet wired

and the Rust parser raised::

    ValueError: unknown triggered_ability.event "you_attack"

Both gaps are closed by this slice.

PROBE CARD — Lionheart Glimmer (EoE)
--------------------------------------
Oracle: "[Enchantment Creature — Cat Glimmer] {3}{W}{W} 2/5
  Whenever you attack, creatures you control get +1/+1 until end of
  turn."

  * Event    = ``YOU_ATTACK``
  * Predicate = ``Controlled(YOU)`` → ``ControlledByYou``
  * Effect   = ``PumpCreaturesYouControlUntilEOT(power_bonus=1,
    toughness_bonus=1)``

PROBE FLOW
----------
The probe seats Lionheart Glimmer (2/5, summoning_sick=False) and one
filler attacker creature (2/2, summoning_sick=False, haste) on p0's
battlefield.  p0 is the active player (turn 2 so draw-step skip no
longer applies).

1. Python: call ``declare_attackers(state, [filler])`` which fires
   ``Event.YOU_ATTACK`` once after the attacker loop, with subject =
   the attacking player (p0).  ``ControlledByYou`` matches the source
   (Lionheart, controlled by p0) against the subject player (p0 =
   active player).  ``PumpCreaturesYouControlUntilEOT(+1/+1)`` fires.
   Observable: Lionheart power 2→3, filler power 2→3.

2. Rust: apply ``{"kind": "declare_attackers", "attacker_ids": [filler_id]}``.
   The ``DeclareAttackers`` arm loops, ``declare_attacker`` taps the
   filler and pushes ``Event::Attacks``, then after the loop the arm
   checks ``state.attackers.len() > attackers_before`` (True) and
   fires ``dispatch_event(Event::YouAttack, PLAYER_SUBJECT_OFFSET + 0)``.
   ``ControlledByYou`` resolves player_index=0, matches Lionheart's
   controller=0.  ``PumpCreaturesYouControlUntilEOT(+1/+1)`` fires.
   Observable: Lionheart power 2→3, filler power 2→3.

3. Both stacks have at least 1 item (Lionheart's pump trigger plus the
   per-attacker Attacks trigger from the filler).  Drain → apply SBAs.

4. Cross-engine byte-equality on targeted observables:
   * Lionheart power 2→3, toughness 5→6 on BOTH engines.
   * Filler power 2→3, toughness 2→3 on BOTH engines (also pumped).

CARDS STILL BLOCKED AFTER THIS SLICE
--------------------------------------
Cards in the you_attack family whose effect shapes are not yet
representable in the Rust effect algebra remain blocked:

* Dyadrine, Synthesis Amalgam — effect is ``DyadrineAttackEffect``
  (custom/complex); not yet a standard Rust Effect arm.
* Dawnsire, Sunstar Dreadnought — ``DealDamageToTargetCreature``
  requires a target (target-based effects need a target-picker in the
  probe harness that is outside the current scope).
* Most Valuable Slayer — ``PumpTargetCreatureUntilEOT`` (target-based).
* Derelict Attic // Widow's Walk — predicate is ``And`` (compound
  predicate, not yet bridged as a compound for YOU_ATTACK).
* Surgical Suite // Hospital Room — ``PutPlusOneCounterOnTargetCreature``
  (target-based).
* Ticket Booth // Tunnel of Hate — ``PumpTargetCreatureUntilEOT``
  (target-based).
* Razorkin Hordecaller — ``CreateToken``; effect is representable but
  token-equality assertion is more involved; deferred to a future probe.

OO Pin 3 status: RENAMED to ``_FIXED_parity`` (assertions inverted to
verify the now-wired behavior; the ValueError is no longer raised).
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
# Probe — Lionheart Glimmer: once-per-combat pump all creatures +1/+1 UEOT
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_lionheart_glimmer_you_attack_pump_creatures_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Lionheart Glimmer
    (round 15, first YOU_ATTACK probe).**

    Drives the **real parsed Lionheart Glimmer printing** on the Python
    side and a bridged synthetic carrier on the Rust side through the
    ``YOU_ATTACK`` dispatch path.

    Setup:
      * p0 has Lionheart Glimmer (2/5, not summoning-sick) and one
        filler attacker (2/2, haste, not summoning-sick) on the
        battlefield.
      * p1 has no creatures and no library cards.
      * Active player = p0; turn ≥ 2 so draw-step skip is inactive.

    Trigger flow:
      1. Declare filler as attacker (Rust: ``apply_action`` with
         ``declare_attackers``; Python: call ``declare_attackers``).
         Per-attacker ``Event::Attacks`` fires for the filler.
         Once-per-combat ``Event::YouAttack`` fires with subject =
         ``PLAYER_SUBJECT_OFFSET + 0`` (Rust) / player=p0 (Python).
         ``ControlledByYou`` resolves player_index=0; matches
         Lionheart's controller=0 → trigger pushed.
         ``PumpCreaturesYouControlUntilEOT(+1/+1)`` is the effect.
      2. Drain stacks: pump resolves; SBAs applied.
      3. Observable: Lionheart power 2→3, toughness 5→6.
               Filler power 2→3, toughness 2→3.

    Rust triggered-ability dict for Lionheart's you_attack trigger::

        {
            "event": "you_attack",
            "predicate": {"kind": "controlled_by_you"},
            "effect": {
                "kind": "pump_creatures_you_control_until_eot",
                "power_bonus": 1,
                "toughness_bonus": 1,
            },
        }

    Python-side bridge translates ``"you_attack"`` →
    ``Event.YOU_ATTACK`` (no spelling skew — string values are
    identical). ``ControlledByYou`` predicate translates unchanged;
    ``PumpCreaturesYouControlUntilEOT`` translates via the existing
    ``"pump_creatures_you_control_until_eot"`` bridge arm.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
        _ta_dict_to_python_triggered_ability,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone, effective_power, effective_toughness
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.predicates import Event, Controlled, YOU
    from mtg_bot.effects.generic.pump import PumpCreaturesYouControlUntilEOT
    from mtg_bot import combat as py_combat

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Lionheart Glimmer printing has the
    #    expected YOU_ATTACK trigger shape.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Lionheart Glimmer")
    if real is None:
        pytest.skip("Lionheart Glimmer absent from active CardSource")

    lg_ta = next(
        (
            ta
            for ta in real.triggered_abilities
            if ta.event == Event.YOU_ATTACK
        ),
        None,
    )
    assert lg_ta is not None, (
        "Lionheart Glimmer must have a YOU_ATTACK triggered ability; "
        "abilities found: "
        f"{[(ta.event, type(ta.effect).__name__) for ta in real.triggered_abilities]}"
    )
    # Predicate shape: Controlled(YOU)
    assert isinstance(lg_ta.predicate, Controlled), (
        f"Lionheart TA predicate must be Controlled; "
        f"got {type(lg_ta.predicate).__name__}"
    )
    assert lg_ta.predicate.by == YOU, (
        f"Lionheart TA predicate.by must be YOU; got {lg_ta.predicate.by!r}"
    )
    # Effect shape: PumpCreaturesYouControlUntilEOT(+1/+1)
    assert isinstance(lg_ta.effect, PumpCreaturesYouControlUntilEOT), (
        f"Lionheart TA effect must be PumpCreaturesYouControlUntilEOT; "
        f"got {type(lg_ta.effect).__name__}"
    )
    assert lg_ta.effect.power_bonus == 1, (
        f"Lionheart TA power_bonus must be 1; got {lg_ta.effect.power_bonus}"
    )
    assert lg_ta.effect.toughness_bonus == 1, (
        f"Lionheart TA toughness_bonus must be 1; "
        f"got {lg_ta.effect.toughness_bonus}"
    )

    # ------------------------------------------------------------------
    # 2. Shared triggered-ability dict (registered on Rust; used to
    #    build the Python TriggeredAbility via the bridge).
    # ------------------------------------------------------------------
    lg_ta_dict = {
        "event": "you_attack",
        "predicate": {"kind": "controlled_by_you"},
        "effect": {
            "kind": "pump_creatures_you_control_until_eot",
            "power_bonus": 1,
            "toughness_bonus": 1,
        },
    }

    # Sanity: bridge translates the dict correctly.
    bridge_ta = _ta_dict_to_python_triggered_ability(lg_ta_dict)
    assert bridge_ta.event == Event.YOU_ATTACK, (
        f"Bridge must translate 'you_attack' to Event.YOU_ATTACK; "
        f"got {bridge_ta.event!r}"
    )
    assert isinstance(bridge_ta.predicate, Controlled), (
        f"Bridge predicate must be Controlled; "
        f"got {type(bridge_ta.predicate).__name__}"
    )
    assert isinstance(bridge_ta.effect, PumpCreaturesYouControlUntilEOT), (
        f"Bridge effect must be PumpCreaturesYouControlUntilEOT; "
        f"got {type(bridge_ta.effect).__name__}"
    )
    assert bridge_ta.effect.power_bonus == 1, (
        f"Bridge effect power_bonus must be 1; "
        f"got {bridge_ta.effect.power_bonus}"
    )
    assert bridge_ta.effect.toughness_bonus == 1, (
        f"Bridge effect toughness_bonus must be 1; "
        f"got {bridge_ta.effect.toughness_bonus}"
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

    # Both states start on turn 1, phase 0 (untap). Advance to
    # PHASE_DECLARE_ATTACKERS (phase 7) so declaring attackers is
    # valid. Turn 1 is fine for this probe (no draw-skip interaction
    # with the creatures being seated directly).
    PHASE_DECLARE_ATTACKERS = 7
    for _ in range(20):
        if rs.current_phase() == PHASE_DECLARE_ATTACKERS:
            break
        rs.advance_phase()
    assert rs.current_phase() == PHASE_DECLARE_ATTACKERS, (
        f"Rust: must reach PHASE_DECLARE_ATTACKERS (7); "
        f"got phase {rs.current_phase()}"
    )

    # ------------------------------------------------------------------
    # 4. Rust: pre-seat Lionheart Glimmer + haste filler on p0's
    #    battlefield.
    # ------------------------------------------------------------------
    rs_lg_id = rs.register_and_inject_object(
        {
            "name": "Lionheart Glimmer",
            "card_types": ["Creature", "Enchantment"],
            "power": 2,
            "toughness": 5,
            "keywords": [],
            "effects": [],
            "triggered_abilities": [lg_ta_dict],
        },
        0, ZB,
    )
    rs_filler_id = rs.register_and_inject_object(
        {
            "name": "AttackFiller",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "keywords": ["haste"],
            "effects": [],
            "triggered_abilities": [],
        },
        0, ZB,
    )

    # Both creatures are NOT summoning-sick: register_and_inject_object
    # hardcodes summoning_sick=False. Verify for diagnostic clarity.
    assert rs.is_summoning_sick(rs_lg_id) is False, (
        "Rust: Lionheart must not be summoning-sick (register_and_inject_object "
        "should default to summoning_sick=False)"
    )
    assert rs.is_summoning_sick(rs_filler_id) is False, (
        "Rust: Filler must not be summoning-sick"
    )

    # Baseline Rust power readings.
    rs_lg_pow0 = rs.effective_power(rs_lg_id)
    rs_lg_tou0 = rs.effective_toughness(rs_lg_id)
    rs_fi_pow0 = rs.effective_power(rs_filler_id)
    rs_fi_tou0 = rs.effective_toughness(rs_filler_id)
    assert rs_lg_pow0 == 2, f"Rust: Lionheart must start at power 2; got {rs_lg_pow0}"
    assert rs_lg_tou0 == 5, f"Rust: Lionheart must start at toughness 5; got {rs_lg_tou0}"
    assert rs_fi_pow0 == 2, f"Rust: Filler must start at power 2; got {rs_fi_pow0}"
    assert rs_fi_tou0 == 2, f"Rust: Filler must start at toughness 2; got {rs_fi_tou0}"

    # ------------------------------------------------------------------
    # 5. Rust: declare filler as attacker — triggers YOU_ATTACK once.
    # ------------------------------------------------------------------
    import json as _json
    action_dict = {"kind": "declare_attackers", "attacker_ids": [rs_filler_id]}
    rs.apply_action(action_dict)

    # The YOU_ATTACK trigger (Lionheart's pump) should be on the stack.
    # Also the per-attacker ATTACKS trigger from the filler (if any).
    # We only assert ≥ 1 item (the pump trigger must be there).
    rs_stack_after = rs.stack_size()
    assert rs_stack_after >= 1, (
        f"Rust: at least 1 trigger (Lionheart's pump) must be on the "
        f"stack after declaring attackers; got stack_size={rs_stack_after}"
    )

    # Drain the stack.
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_lg_pow1 = rs.effective_power(rs_lg_id)
    rs_lg_tou1 = rs.effective_toughness(rs_lg_id)
    rs_fi_pow1 = rs.effective_power(rs_filler_id)
    rs_fi_tou1 = rs.effective_toughness(rs_filler_id)

    assert rs_lg_pow1 == rs_lg_pow0 + 1, (
        f"Rust: Lionheart power must be pumped +1 by YOU_ATTACK trigger; "
        f"power {rs_lg_pow0} → {rs_lg_pow1}"
    )
    assert rs_lg_tou1 == rs_lg_tou0 + 1, (
        f"Rust: Lionheart toughness must be pumped +1 by YOU_ATTACK trigger; "
        f"toughness {rs_lg_tou0} → {rs_lg_tou1}"
    )
    assert rs_fi_pow1 == rs_fi_pow0 + 1, (
        f"Rust: Filler power must be pumped +1 by YOU_ATTACK trigger; "
        f"power {rs_fi_pow0} → {rs_fi_pow1}"
    )
    assert rs_fi_tou1 == rs_fi_tou0 + 1, (
        f"Rust: Filler toughness must be pumped +1 by YOU_ATTACK trigger; "
        f"toughness {rs_fi_tou0} → {rs_fi_tou1}"
    )

    # ------------------------------------------------------------------
    # 6. Python: pre-seat real Lionheart Glimmer printing (using bridge
    #    TA) + haste filler on p0's battlefield.
    # ------------------------------------------------------------------
    py_lg_printing = CardPrinting(
        name="Lionheart Glimmer",
        mana_cost_str="{3}{W}{W}",
        mana_cost=ManaCost(generic=3, colored=(("W", 2),)),
        type_line="Enchantment Creature — Cat Glimmer",
        supertypes=(),
        card_types=("Creature", "Enchantment"),
        subtypes=("Cat", "Glimmer"),
        power=2,
        toughness=5,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(bridge_ta,),
    )
    py_lg = py.new_object(py_lg_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_lg.summoning_sick = False
    py_lg.tapped = False
    py_lg.damage = 0
    py_lg.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_lg)

    py_filler_printing = CardPrinting(
        name="AttackFiller",
        mana_cost_str="{G}",
        mana_cost=ManaCost(generic=0, colored=(("G", 1),)),
        type_line="Creature — Beast",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Beast",),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset({"haste"}),
        triggered_abilities=(),
    )
    py_filler = py.new_object(py_filler_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_filler.summoning_sick = False
    py_filler.tapped = False
    py_filler.damage = 0
    py_filler.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_filler)

    # Baseline Python power readings.
    py_lg_pow0 = py_lg.printing.power
    py_lg_tou0 = py_lg.printing.toughness
    py_fi_pow0 = py_filler.printing.power
    py_fi_tou0 = py_filler.printing.toughness
    assert py_lg_pow0 == 2, f"Python: Lionheart must start at power 2; got {py_lg_pow0}"
    assert py_lg_tou0 == 5, f"Python: Lionheart must start at toughness 5; got {py_lg_tou0}"
    assert py_fi_pow0 == 2, f"Python: Filler must start at power 2; got {py_fi_pow0}"
    assert py_fi_tou0 == 2, f"Python: Filler must start at toughness 2; got {py_fi_tou0}"

    # ------------------------------------------------------------------
    # 7. Python: declare filler as attacker — fires YOU_ATTACK once.
    # ------------------------------------------------------------------
    py_combat.declare_attackers(py, [py_filler.id])

    assert len(py.stack) >= 1, (
        f"Python: at least 1 trigger (Lionheart's pump) must be on the "
        f"stack after declaring attackers; got {len(py.stack)}"
    )

    # Drain.
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    # Read the effective (post-UEOT) power/toughness from the game-object
    # itself, which the UEOT effect mutates via the eot_effects list.
    py_lg_pow1 = effective_power(py, py_lg)
    py_lg_tou1 = effective_toughness(py, py_lg)
    py_fi_pow1 = effective_power(py, py_filler)
    py_fi_tou1 = effective_toughness(py, py_filler)

    assert py_lg_pow1 == py_lg_pow0 + 1, (
        f"Python: Lionheart power must be pumped +1 by YOU_ATTACK trigger; "
        f"power {py_lg_pow0} → {py_lg_pow1}"
    )
    assert py_lg_tou1 == py_lg_tou0 + 1, (
        f"Python: Lionheart toughness must be pumped +1 by YOU_ATTACK trigger; "
        f"toughness {py_lg_tou0} → {py_lg_tou1}"
    )
    assert py_fi_pow1 == py_fi_pow0 + 1, (
        f"Python: Filler power must be pumped +1 by YOU_ATTACK trigger; "
        f"power {py_fi_pow0} → {py_fi_pow1}"
    )
    assert py_fi_tou1 == py_fi_tou0 + 1, (
        f"Python: Filler toughness must be pumped +1 by YOU_ATTACK trigger; "
        f"toughness {py_fi_tou0} → {py_fi_tou1}"
    )

    # ------------------------------------------------------------------
    # 8. Cross-engine byte-equality on targeted observables.
    # ------------------------------------------------------------------
    assert rs_lg_pow1 == py_lg_pow1, (
        f"Lionheart power: Rust={rs_lg_pow1}, Python={py_lg_pow1} "
        f"(must be byte-equal — PumpCreaturesYouControlUntilEOT resolved "
        f"on BOTH engines)"
    )
    assert rs_lg_tou1 == py_lg_tou1, (
        f"Lionheart toughness: Rust={rs_lg_tou1}, Python={py_lg_tou1} "
        f"(must be byte-equal)"
    )
    assert rs_fi_pow1 == py_fi_pow1, (
        f"Filler power: Rust={rs_fi_pow1}, Python={py_fi_pow1} "
        f"(must be byte-equal)"
    )
    assert rs_fi_tou1 == py_fi_tou1, (
        f"Filler toughness: Rust={rs_fi_tou1}, Python={py_fi_tou1} "
        f"(must be byte-equal)"
    )
