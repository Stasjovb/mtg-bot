"""Genuine cross-engine probes — batch PPP downstream unlock
(10th Rust slice; closes PPP Pins 1+2+3).

The 10th Rust slice added Rust-parser arms + resolve arms for:

  * target_player_loses_life (PPP Pin 1) — Effect variant with `amount`
    field (default 1). Pre-fixed target via payload-target seat.
  * put_plus_one_counter_on_target_creature (PPP Pin 2) — Effect
    variant with `amount` field (default 1) + `attacking_only` bool
    (default false). Reads payload-target seat (Tier-C convention).
  * BEGINNING_OF_POSTCOMBAT_MAIN (PPP Pin 3) — Event variant +
    dispatch site at PHASE_MAIN2 entry in `advance_phase`.

Plus a Python-bridge `source_is_tapped` predicate arm (the "survivor"
predicate `Source(IsTapped())`), needed for the 5 BEGINNING_OF_
POSTCOMBAT_MAIN survivor cards' full TA dict round-trips.

PROBE CARDS
-----------

Probe 1 -- Drix Fatemaker (put_plus_one_counter_on_target_creature)
"When this creature enters, put a +1/+1 counter on target creature."

Event: ENTERS (Python: Event.ENTERS)
Effect: PutPlusOneCounterOnTargetCreature(amount=1, attacking_only=False)

The Rust parse arm now accepts the dict; the resolve arm reads the
payload-target seat. This probe verifies the Rust parse + Python
bridge round-trip without exception.

Probe 2 -- Cautious Survivor (BEGINNING_OF_POSTCOMBAT_MAIN +
GainLife). The card carries an event predicate
``And(And(Controlled(YOU), IsSelf), Source(IsTapped))``. Probe asserts
the Python bridge produces a TriggeredAbility with the wired event and
the predicate composition; Rust parse_triggered_ability accepts the
same dict shape.

Probe 3 -- Savior of the Small (BEGINNING_OF_POSTCOMBAT_MAIN +
ReturnCreatureFromYourGraveyardToHand). Same event/predicate shape as
Cautious Survivor, with a different effect (graveyard return).
"""

from __future__ import annotations

import importlib.util

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# Probe 1 -- Drix Fatemaker (put_plus_one_counter_on_target_creature, ENTERS)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_drix_fatemaker_put_plus_one_counter_on_target_creature_parity():
    """Genuine PPP-downstream probe — Drix Fatemaker
    put_plus_one_counter_on_target_creature parse arm.

    10th Rust slice: put_plus_one_counter_on_target_creature now parses
    AND resolves in Rust. The resolve arm reads
    current_resolve_payload_target_id (set at push time by
    first_legal_trigger_target).

    Verification:
      1. Drix Fatemaker exists in the EoE source with an ENTERS triggered
         ability carrying PutPlusOneCounterOnTargetCreature as its effect.
      2. Python bridge produces PutPlusOneCounterOnTargetCreature for the
         dict shape.
      3. Rust register_and_inject_object accepts the dict shape (parse arm
         wired) — no PyValueError.
      4. After injecting Drix + a target creature, the engine runs without
         exception.
    """
    import mtg_bot_engine
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCounterOnTargetCreature,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.effects.predicates import Event
    from mtg_bot.cards.source import get_active_source

    # 1. Drix Fatemaker exists with the expected ENTERS trigger.
    source = get_active_source()
    drix = source.get_printings().get("Drix Fatemaker")
    if drix is None:
        pytest.skip("Drix Fatemaker absent from active CardSource")
    enters_ta = next(
        (ta for ta in drix.triggered_abilities if ta.event == Event.ENTERS),
        None,
    )
    assert enters_ta is not None, (
        "Drix Fatemaker must have an ENTERS triggered ability."
    )
    assert isinstance(enters_ta.effect, PutPlusOneCounterOnTargetCreature), (
        f"Drix ENTERS effect should be PutPlusOneCounterOnTargetCreature; "
        f"got {type(enters_ta.effect).__name__!r}"
    )
    assert enters_ta.effect.amount == 1
    assert enters_ta.effect.attacking_only is False

    # 2. Python bridge produces the matching Effect from the dict.
    py_effect = _ta_dict_to_python_effect(
        {
            "kind": "put_plus_one_counter_on_target_creature",
            "amount": 1,
            "attacking_only": False,
        }
    )
    assert isinstance(py_effect, PutPlusOneCounterOnTargetCreature)
    assert py_effect.amount == 1
    assert py_effect.attacking_only is False

    # 3. Rust parse arm accepts the dict (no PyValueError).
    rs = mtg_bot_engine.make_synthetic_state()
    rs.register_and_inject_object(
        {
            "name": "Vanilla Bear (target)",
            "card_types": ["Creature"],
            "supertypes": [],
            "power": 2,
            "toughness": 2,
            "keywords": [],
            "effects": [],
            "triggered_abilities": [],
        },
        0,  # player 0
        2,  # ZONE_BATTLEFIELD
    )
    rs.register_and_inject_object(
        {
            "name": "Drix Fatemaker",
            "card_types": ["Creature"],
            "supertypes": ["Legendary"],
            "power": 2,
            "toughness": 3,
            "keywords": [],
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "put_plus_one_counter_on_target_creature",
                        "amount": 1,
                        "attacking_only": False,
                    },
                }
            ],
        },
        0,  # player 0
        2,  # ZONE_BATTLEFIELD
    )
    # No PyValueError = parse + push succeeded.

    # 4. Drain stack and confirm no crash.
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    bf_sizes = rs.battlefield_sizes
    assert bf_sizes[0] >= 2, (
        "After injecting Vanilla Bear + Drix Fatemaker, p0 should have "
        f">= 2 battlefield objects; got {bf_sizes[0]}"
    )


# ---------------------------------------------------------------------------
# Probe 2 -- Cautious Survivor (BEGINNING_OF_POSTCOMBAT_MAIN + GainLife)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_cautious_survivor_beginning_of_postcombat_main_parity():
    """Genuine PPP-downstream probe — Cautious Survivor
    BEGINNING_OF_POSTCOMBAT_MAIN survival pattern.

    Predicate composition: ``And(And(Controlled(YOU), IsSelf),
    Source(IsTapped))`` — "if you control this AND this IS the source
    AND the source is tapped".

    10th Rust slice closures verified:
      * Python bridge produces a TriggeredAbility with the wired event
        and the full predicate composition (including the new
        source_is_tapped arm).
      * Rust parse_triggered_ability accepts the dict shape (no
        PyValueError).
    """
    import mtg_bot_engine
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.effects.predicates import (
        Event,
        Source,
        Controlled,
        And,
        IsSelf,
    )
    from mtg_bot.effects.object_predicates import IsTapped
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_triggered_ability,
    )
    from mtg_bot.cards.source import get_active_source

    # 1. Cautious Survivor exists with the expected BEGINNING_OF_POSTCOMBAT_MAIN
    #    trigger.
    source = get_active_source()
    cautious = source.get_printings().get("Cautious Survivor")
    if cautious is None:
        pytest.skip("Cautious Survivor absent from active CardSource")
    pcm_ta = next(
        (
            ta
            for ta in cautious.triggered_abilities
            if ta.event == Event.BEGINNING_OF_POSTCOMBAT_MAIN
        ),
        None,
    )
    assert pcm_ta is not None, (
        "Cautious Survivor must have a BEGINNING_OF_POSTCOMBAT_MAIN trigger."
    )
    assert isinstance(pcm_ta.effect, GainLife)
    assert pcm_ta.effect.amount == 2

    # 2. Python bridge produces the equivalent TriggeredAbility.
    ta_dict = {
        "event": "beginning_of_postcombat_main",
        "predicate": {
            "kind": "and",
            "left": {
                "kind": "and",
                "left": {"kind": "controlled_by_you"},
                "right": {"kind": "source_is_self"},
            },
            "right": {"kind": "source_is_tapped"},
        },
        "effect": {"kind": "gain_life", "amount": 2},
    }
    bridge_ta = _ta_dict_to_python_triggered_ability(ta_dict)
    assert bridge_ta.event == Event.BEGINNING_OF_POSTCOMBAT_MAIN
    assert isinstance(bridge_ta.effect, GainLife)
    assert bridge_ta.effect.amount == 2
    # Predicate composition includes Source(IsTapped()).
    pred = bridge_ta.predicate
    assert isinstance(pred, And), (
        f"Outer predicate should be And; got {type(pred).__name__!r}."
    )
    # Walk the And tree to find the Source(IsTapped) clause.
    found_source_tapped = False

    def _walk(p):
        nonlocal found_source_tapped
        if isinstance(p, And):
            _walk(p.left)
            _walk(p.right)
        elif isinstance(p, Source) and isinstance(p.inner, IsTapped):
            found_source_tapped = True

    _walk(pred)
    assert found_source_tapped, (
        "Bridge predicate should include Source(IsTapped()); "
        f"got: {pred!r}"
    )

    # 3. Rust parse arm accepts the dict.
    rs = mtg_bot_engine.make_synthetic_state()
    rs.register_and_inject_object(
        {
            "name": "Cautious Survivor",
            "card_types": ["Creature"],
            "supertypes": [],
            "power": 1,
            "toughness": 1,
            "keywords": [],
            "effects": [],
            "triggered_abilities": [ta_dict],
        },
        0,  # player 0
        2,  # ZONE_BATTLEFIELD
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    bf_sizes = rs.battlefield_sizes
    assert bf_sizes[0] >= 1, (
        "After injecting Cautious Survivor, p0 should have >= 1 battlefield "
        f"object; got {bf_sizes[0]}"
    )


# ---------------------------------------------------------------------------
# Probe 3 -- Savior of the Small (BEGINNING_OF_POSTCOMBAT_MAIN +
#            ReturnCreatureFromYourGraveyardToHand)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_savior_of_the_small_beginning_of_postcombat_main_parity():
    """Genuine PPP-downstream probe — Savior of the Small
    BEGINNING_OF_POSTCOMBAT_MAIN graveyard-return pattern.

    Same predicate composition as Cautious Survivor; different effect
    (graveyard return rather than life gain).
    """
    import mtg_bot_engine
    from mtg_bot.effects.generic.bounce import (
        ReturnCreatureFromYourGraveyardToHand,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_triggered_ability,
    )
    from mtg_bot.cards.source import get_active_source

    # 1. Savior of the Small exists with the expected trigger.
    source = get_active_source()
    savior = source.get_printings().get("Savior of the Small")
    if savior is None:
        pytest.skip("Savior of the Small absent from active CardSource")
    pcm_ta = next(
        (
            ta
            for ta in savior.triggered_abilities
            if ta.event == Event.BEGINNING_OF_POSTCOMBAT_MAIN
        ),
        None,
    )
    assert pcm_ta is not None
    assert isinstance(pcm_ta.effect, ReturnCreatureFromYourGraveyardToHand)

    # 2. Python bridge translates the full dict cleanly.
    ta_dict = {
        "event": "beginning_of_postcombat_main",
        "predicate": {
            "kind": "and",
            "left": {
                "kind": "and",
                "left": {"kind": "controlled_by_you"},
                "right": {"kind": "source_is_self"},
            },
            "right": {"kind": "source_is_tapped"},
        },
        "effect": {"kind": "return_creature_from_your_graveyard_to_hand"},
    }
    bridge_ta = _ta_dict_to_python_triggered_ability(ta_dict)
    assert bridge_ta.event == Event.BEGINNING_OF_POSTCOMBAT_MAIN
    assert isinstance(bridge_ta.effect, ReturnCreatureFromYourGraveyardToHand)

    # 3. Rust parse arm accepts the dict.
    rs = mtg_bot_engine.make_synthetic_state()
    rs.register_and_inject_object(
        {
            "name": "Savior of the Small",
            "card_types": ["Creature"],
            "supertypes": [],
            "power": 1,
            "toughness": 1,
            "keywords": [],
            "effects": [],
            "triggered_abilities": [ta_dict],
        },
        0,
        2,
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    bf_sizes = rs.battlefield_sizes
    assert bf_sizes[0] >= 1
