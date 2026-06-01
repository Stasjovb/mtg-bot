"""Rust resolve-arm pins for the Phase-5 ReplacementEffect-static
consumers wired on ``feature/replacement-rust-arms`` (2026-06-01):

  * **Loading Zone** — ``counter_placement_count_multiplier`` /
    ``doubled_plus_one_counter_delta`` folded into every +1/+1-counter-
    placement arm in ``rust/src/state_ops_resolve.rs``. A POSITIVE
    +1/+1 delta onto a creature-or-Spacecraft recipient is multiplied by
    every controller-matching ``would_place_counter × multiply_count``
    doubler; negatives (-1/-1) and out-of-scope recipients pass through.
  * **Starfield Vocalist** — ``entered_trigger_instance_multiplier``
    folded into the ``dispatch_event`` push loop for ``Event::Enters``
    firings ONLY. Each ENTERS firing under a controller carrying a
    ``triggered_ability_triggers + add_instances`` replacement is pushed
    N times (base 1 + sum of deltas).

These are the unit-level Rust pins; the full cross-engine byte-equal
probes live in ``tests/test_loading_zone_parity.py`` /
``tests/test_starfield_vocalist_parity.py``.
"""

from __future__ import annotations


ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2


# ---------------------------------------------------------------------------
# Card-dict fixtures.
# ---------------------------------------------------------------------------


def _loading_zone_dict(name="Loading Zone (synthetic)"):
    """A Loading-Zone-shape Enchantment carrying the
    ``would_place_counter × multiply_count(2)`` static replacement."""
    return {
        "name": name,
        "card_types": ["Enchantment"],
        "mana_cost": {"generic": 3, "G": 1},
        "static_replacements": [
            {
                "event": "would_place_counter",
                "transform_kind": "multiply_count",
                "transform_param": 2,
            },
        ],
    }


def _starfield_vocalist_dict(name="Starfield Vocalist (synthetic)"):
    """A Starfield-Vocalist-shape Creature carrying the
    ``triggered_ability_triggers + add_instances(1)`` static."""
    return {
        "name": name,
        "card_types": ["Creature"],
        "subtypes": ["Human", "Bard"],
        "power": 3,
        "toughness": 4,
        "mana_cost": {"generic": 3, "U": 1},
        "static_replacements": [
            {
                "event": "triggered_ability_triggers",
                "transform_kind": "add_instances",
                "transform_param": 1,
            },
        ],
    }


def _self_counter_bear(name="Counter Bear", amount=1):
    """A creature whose ETB puts ``amount`` +1/+1 counter(s) on itself."""
    return {
        "name": name,
        "card_types": ["Creature"],
        "subtypes": ["Bear"],
        "power": 2,
        "toughness": 2,
        "mana_cost": {"generic": 1},
        "effects": [],
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "put_plus_one_counter_on_self", "amount": amount},
            },
        ],
    }


def _etb_gain_life_creature(name="Triggerer", amount=3):
    """A creature whose ETB triggers a gain_life — an observable ENTERS
    trigger the Starfield Vocalist instance multiplier fans out."""
    return {
        "name": name,
        "card_types": ["Creature"],
        "subtypes": ["Bear"],
        "power": 2,
        "toughness": 2,
        "mana_cost": {"generic": 1},
        "effects": [],
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "gain_life", "amount": amount},
            },
        ],
    }


def _plain_creature(name="Plain", power=1, toughness=1, subtypes=None):
    return {
        "name": name,
        "card_types": ["Creature"],
        "subtypes": subtypes or [],
        "power": power,
        "toughness": toughness,
        "mana_cost": {"generic": 1},
    }


def _bf_counters(s, obj_id):
    return s.get_counters(obj_id)


# ===========================================================================
# Loading Zone — counter_placement_count_multiplier resolve arm.
# ===========================================================================


def test_loading_zone_doubles_self_counter_on_controlled_creature(engine):
    """**Resolve-arm pin.** Loading Zone on p0's bf; a p0 creature's ETB
    puts 1 +1/+1 counter on itself → the arm doubles it to 2."""
    s = engine.make_synthetic_state(0, 0, 0)
    s.register_and_inject_object(_loading_zone_dict(), 0, ZONE_BATTLEFIELD)
    bear = s.register_and_inject_object(_self_counter_bear(), 0, ZONE_BATTLEFIELD)
    while s.stack_size() > 0:
        s.resolve_top_of_stack()
    assert _bf_counters(s, bear) == 2


def test_loading_zone_two_copies_quadruple(engine):
    """Two Loading Zones compose multiplicatively (×2 · ×2 = ×4),
    matching CR 614 + Python's per-replacement fold."""
    s = engine.make_synthetic_state(0, 0, 0)
    s.register_and_inject_object(_loading_zone_dict("LZ A"), 0, ZONE_BATTLEFIELD)
    s.register_and_inject_object(_loading_zone_dict("LZ B"), 0, ZONE_BATTLEFIELD)
    bear = s.register_and_inject_object(_self_counter_bear(), 0, ZONE_BATTLEFIELD)
    while s.stack_size() > 0:
        s.resolve_top_of_stack()
    assert _bf_counters(s, bear) == 4


def test_loading_zone_no_doubler_places_one(engine):
    """Negative control: no Loading Zone → the ETB places exactly 1."""
    s = engine.make_synthetic_state(0, 0, 0)
    bear = s.register_and_inject_object(_self_counter_bear(), 0, ZONE_BATTLEFIELD)
    while s.stack_size() > 0:
        s.resolve_top_of_stack()
    assert _bf_counters(s, bear) == 1


def test_loading_zone_keyed_on_recipient_controller_not_caster(engine):
    """The doubler keys on the RECIPIENT's controller. A Loading Zone
    controlled by p1 does NOT double counters landing on p0's creature."""
    s = engine.make_synthetic_state(0, 0, 0)
    # Loading Zone owned/controlled by p1.
    s.register_and_inject_object(_loading_zone_dict(), 1, ZONE_BATTLEFIELD)
    # p0's creature self-counters; recipient controller is p0 (no LZ).
    bear = s.register_and_inject_object(_self_counter_bear(), 0, ZONE_BATTLEFIELD)
    while s.stack_size() > 0:
        s.resolve_top_of_stack()
    assert _bf_counters(s, bear) == 1


# ===========================================================================
# Starfield Vocalist — entered_trigger_instance_multiplier resolve arm.
# ===========================================================================


def test_starfield_vocalist_doubles_enters_trigger_instances(engine):
    """**Resolve-arm pin.** Starfield Vocalist on p0's bf; a p0 creature
    with an ETB (gain_life) trigger enters → the trigger is pushed TWICE
    (one base + 1 extra instance)."""
    s = engine.make_synthetic_state(0, 0, 0)
    s.register_and_inject_object(_starfield_vocalist_dict(), 0, ZONE_BATTLEFIELD)
    s.register_and_inject_object(_etb_gain_life_creature(), 0, ZONE_BATTLEFIELD)
    assert s.stack_size() == 2


def test_starfield_vocalist_two_copies_triple_instances(engine):
    """Two Starfield Vocalists add instances additively (1 + 1 + 1 = 3),
    mirroring Python's ``etb_trigger_multiplier`` AddInstances fold."""
    s = engine.make_synthetic_state(0, 0, 0)
    s.register_and_inject_object(_starfield_vocalist_dict("SV A"), 0, ZONE_BATTLEFIELD)
    s.register_and_inject_object(_starfield_vocalist_dict("SV B"), 0, ZONE_BATTLEFIELD)
    s.register_and_inject_object(_etb_gain_life_creature(), 0, ZONE_BATTLEFIELD)
    assert s.stack_size() == 3


def test_starfield_vocalist_no_carrier_single_instance(engine):
    """Negative control: no Starfield Vocalist → the ETB pushes 1."""
    s = engine.make_synthetic_state(0, 0, 0)
    s.register_and_inject_object(_etb_gain_life_creature(), 0, ZONE_BATTLEFIELD)
    assert s.stack_size() == 1


def test_starfield_vocalist_keyed_on_source_controller(engine):
    """The instance multiplier keys on the firing source's controller. A
    Starfield Vocalist controlled by p1 does NOT multiply p0's creature's
    ENTERS trigger."""
    s = engine.make_synthetic_state(0, 0, 0)
    s.register_and_inject_object(_starfield_vocalist_dict(), 1, ZONE_BATTLEFIELD)
    s.register_and_inject_object(_etb_gain_life_creature(), 0, ZONE_BATTLEFIELD)
    assert s.stack_size() == 1
