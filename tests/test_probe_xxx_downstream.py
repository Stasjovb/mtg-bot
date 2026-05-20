"""Genuine cross-engine probes -- batch XXX downstream unlock
(18th Rust slice; closes XXX Pin 2 -- Roving Actuator Void ETB).

**Slice 18 closure (XXX Pin 2 -- Roving Actuator Void ETB):**

Slice 18 added ``Effect::RovingActuatorETBEffect { max_mv: u8 }``
(single-field payload variant) to the Rust enum + parse + resolve
arms, plus the ``roving_actuator_etb`` bridge arm in
``cross_engine.py``.  The resolve arm mirrors Python's
``RovingActuatorETBEffect.resolve`` step-for-step: source-controller
resolution (CR 119.5 / 608.2); first-legal graveyard scan filtered
to ``(is_instant || is_sorcery) && mana_cost.total() <= max_mv``;
silent no-op on empty filter (``up to one``); remove the picked card
from gy, stamp ``zone=ZONE_EXILE``, push to controller's exile;
clone the exiled card's ``printing.effects`` and recursively
``apply_effect`` each child with the EXILED card's id as new source
(the copy resolves on the engine directly without going through the
stack -- intentional first-slice simplification matching Python's
bespoke.py:683-711 "doesn't go on the stack, can't be counterspelled"
comment).  The source-controller transient stays pinned through the
recursive call so DealDamage / DrawCards / GainLife arms attribute
correctly to the Roving Actuator's controller.

Probes added in slice 18:
  * ``test_xxx_probe_roving_actuator_etb_exiles_gy_spell_and_resolves_copy_real_eoe``
    -- Roving-Actuator-shape creature ETB exiles a synthetic
    instant from the controller's gy + the recursive apply_effect
    runs the spell_effect (deal damage) on the new source.
    Filtered cards (a sibling creature in gy) are skipped by the
    is_instant/is_sorcery gate.
  * ``test_xxx_probe_roving_actuator_empty_filter_no_op`` -- empty-
    filter no-op invariant (no legal gy target -> silent no-op,
    no zone transitions).
  * ``test_xxx_probe_roving_actuator_mv_filter_excludes_high_mv_spell``
    -- the MV<=max_mv filter excludes a sibling MV=3 sorcery while
    selecting the MV=1 instant.

1 EoE card directly parity-aligned by slice 18: Roving Actuator
(3,400 17lands decks per docs/RESIDUE_CARD_PLANS.md:96).
"""

from __future__ import annotations

import importlib.util

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


def test_xxx_probe_roving_actuator_etb_exiles_gy_spell_and_resolves_copy_real_eoe():
    """**18th Rust slice XXX Pin 2 closure -- Roving Actuator Void
    ETB end-to-end byte-equal probe.**

    Drives the Rust engine's new
    ``Effect::RovingActuatorETBEffect { max_mv: 2 }`` arm end-to-end
    with a Roving-Actuator-shape creature ETBing on the controller's
    bf while a synthetic ``{R}`` instant (deals 2 damage to any
    target) sits in the controller's graveyard alongside a
    filtered-out gy creature.  Post-resolve invariant: the instant
    moves to exile, the recursive apply_effect runs DealDamage, and
    the gy creature stays where it is (filtered by the
    is_instant/is_sorcery gate).

    Roving Actuator (EoE, 3,400 17lands decks): ``{2}{B}`` Creature
    Construct with Void -- when this enters and Void is active,
    "Exile up to one target instant or sorcery card with mana value
    2 or less from your graveyard. Copy it. You may cast the copy
    without paying its mana cost."  Bespoke
    ``RovingActuatorETBEffect`` on Python
    (``effects/bespoke.py:630-718``); new
    ``Effect::RovingActuatorETBEffect { max_mv: u8 }`` on Rust
    (this slice).

    Pre-closure (the divergence XXX Pin 2 locked in): the printing's
    ETB body could not round-trip through the bridge -- Rust's
    Effect enum had no matching variant.  Post-closure: the Rust
    resolve arm mirrors Python step-for-step; the gy spell moves to
    exile + the copy's spell_effect resolves on the engine directly
    under the same first-legal-graveyard-scan target convention.

    Probe shape (Rust-side end-to-end + cross-engine bridge):
      1. Bridge round-trip:
         ``{"kind": "roving_actuator_etb", "max_mv": 2}`` translates
         to ``RovingActuatorETBEffect(max_mv=2)`` on Python.
      2. Rust-side full ETB cycle: inject a Roving-Actuator-shape
         creature on P0's bf with the new ``roving_actuator_etb``
         ETB trigger; pre-seed P0's graveyard with a ``{R}`` instant
         (deal 2 damage to any player) + a creature card (to verify
         the is_instant/is_sorcery gate).  Resolve the stack to
         completion.
      3. Post-resolve invariants on Rust:
            * The gy instant is gone from P0's graveyard.
            * The gy instant is now in P0's exile.
            * P1's life has dropped by 2 (the copy's DealDamage
              resolved through the recursive apply_effect path,
              with source-controller pinned to P0 so the defender
              = 1 - P0 = P1).
            * The Roving Actuator source is still on P0's bf
              (ETB does not relocate itself).
            * The gy creature is still in P0's graveyard (filtered
              out by !is_instant && !is_sorcery).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_rust_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.effects.bespoke import RovingActuatorETBEffect

    # ---- Bridge arm round-trip: Rust dict -> Python class. ---------
    bridged = _ta_dict_to_python_effect(
        {"kind": "roving_actuator_etb", "max_mv": 2}
    )
    assert isinstance(bridged, RovingActuatorETBEffect), (
        "XXX Pin 2 closure (slice 18): the cross_engine bridge arm "
        "should round-trip the Rust kind 'roving_actuator_etb' to a "
        f"Python RovingActuatorETBEffect instance; got {bridged!r}"
    )
    assert bridged.max_mv == 2, (
        "XXX Pin 2 closure: bridged effect should preserve max_mv=2; "
        f"got max_mv={bridged.max_mv}"
    )
    # Equality under frozen dataclass shape (same max_mv).
    assert bridged == RovingActuatorETBEffect(max_mv=2), (
        "XXX Pin 2 closure: bridged effect should equal a "
        "default-constructed RovingActuatorETBEffect(max_mv=2) "
        "(frozen-dataclass equality contract)."
    )

    # ---- Rust-side end-to-end: inject Actuator + gy spell. ---------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rust_state = build_rust_state(spec)
    ZONE_BATTLEFIELD = 2
    ZONE_GRAVEYARD = 3
    ZONE_EXILE = 5

    # Pre-seed P0's graveyard with a synthetic {R} instant that deals
    # 2 damage to any player.  mana_cost.total = 1 <= max_mv=2, so
    # legal target.  The DealDamage effect carries TargetFilter
    # AnyPlayer; the recursive apply_effect arm picks defender =
    # 1 - source_controller = 1 - 0 = 1, so P1 takes 2 damage.
    rust_gy_instant_id = rust_state.register_and_inject_object(
        {
            "name": "XXX Probe Synthetic Bolt (MV1 instant)",
            "card_types": ["Instant"],
            "mana_cost": {"R": 1},
            "effects": [
                {
                    "kind": "deal_damage",
                    "amount": 2,
                    "target": {"kind": "any_player"},
                },
            ],
            "triggered_abilities": [],
        },
        0, ZONE_GRAVEYARD,
    )
    # Also seed a creature card in gy (filtered out by the
    # !is_instant && !is_sorcery gate -- the first-legal scan
    # skips it).
    rust_gy_creature_id = rust_state.register_and_inject_object(
        {
            "name": "XXX Probe GY Creature (filtered out)",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1},
            "power": 1, "toughness": 1,
            "effects": [],
            "triggered_abilities": [],
        },
        0, ZONE_GRAVEYARD,
    )

    p1_life_before = rust_state.life_totals[1]

    # ---- Inject Roving-Actuator-shape creature on P0's bf, firing
    # its ETB trigger via the standard inject path.
    rust_actuator_id = rust_state.register_and_inject_object(
        {
            "name": "XXX Roving Actuator (probe)",
            "card_types": ["Creature"],
            "subtypes": ["Construct"],
            "mana_cost": {"generic": 2, "B": 1},
            "power": 2, "toughness": 2,
            "effects": [],
            "triggered_abilities": [{
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "roving_actuator_etb",
                    "max_mv": 2,
                },
            }],
        },
        0, ZONE_BATTLEFIELD,
    )

    # The ETB trigger should land on the stack.
    assert rust_state.stack_size() == 1, (
        "Rust XXX Pin 2 closure: Roving Actuator's arrival on P0's "
        "bf should fire its ENTERS trigger; got stack_size="
        f"{rust_state.stack_size()}"
    )

    # Drain the stack to completion.  The ETB trigger frame resolves
    # the RovingActuatorETBEffect arm: first-legal gy scan picks the
    # MV1 instant (the creature is filtered out by
    # !is_instant && !is_sorcery); the instant moves to exile;
    # the recursive apply_effect on DealDamage(amount=2,
    # AnyPlayer) targets P1 (defender = 1 - 0 = 1).
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()

    # ---- Post-resolve invariants. ----------------------------------
    # 1. The instant exited the graveyard.
    rust_p0_gy = rust_state.graveyard_snapshot(0)
    rust_p0_gy_names = {e["printing_name"] for e in rust_p0_gy}
    assert (
        "XXX Probe Synthetic Bolt (MV1 instant)" not in rust_p0_gy_names
    ), (
        "Rust XXX Pin 2 closure: the gy instant should be GONE from "
        "P0's graveyard (exiled by Roving Actuator's ETB); got "
        f"gy_p0={sorted(rust_p0_gy_names)!r}"
    )

    # 2. The instant landed in the exile zone.
    rust_p0_exile = rust_state.exile_snapshot(0)
    rust_p0_exile_names = {e["printing_name"] for e in rust_p0_exile}
    assert (
        "XXX Probe Synthetic Bolt (MV1 instant)" in rust_p0_exile_names
    ), (
        "Rust XXX Pin 2 closure: the gy instant should be in P0's "
        "exile post-ETB (Void exile-from-graveyard); got "
        f"exile_p0={sorted(rust_p0_exile_names)!r}"
    )

    # 3. The copy resolved: P1 took 2 damage.  This is the
    # "cast a copy" substrate working -- the recursive apply_effect
    # on DealDamage fired through the source-controller transient
    # so defender = 1 - source_controller(=P0) = P1.
    p1_life_after = rust_state.life_totals[1]
    assert p1_life_after == p1_life_before - 2, (
        "Rust XXX Pin 2 closure: the copy of the exiled instant "
        "should have resolved through the recursive apply_effect "
        "and dealt 2 damage to P1 (the defender, since the "
        "source-controller transient is pinned to P0 = the "
        f"Actuator's controller); got p1_life_before="
        f"{p1_life_before} p1_life_after={p1_life_after}"
    )

    # 4. The Roving Actuator source is still on P0's bf.
    rust_bf_all = rust_state.battlefield_snapshot()
    rust_p0_bf_names = {
        e["printing_name"] for e in rust_bf_all
        if e.get("controller_id") == 0
    }
    assert "XXX Roving Actuator (probe)" in rust_p0_bf_names, (
        "Rust XXX Pin 2 closure: the Roving Actuator source should "
        "remain on P0's bf post-ETB; got "
        f"bf_p0={sorted(rust_p0_bf_names)!r}"
    )

    # 5. The gy creature is still in the graveyard (filtered out).
    assert (
        "XXX Probe GY Creature (filtered out)" in rust_p0_gy_names
    ), (
        "Rust XXX Pin 2 closure: the gy creature should remain in "
        "P0's graveyard (filtered out by !is_instant && "
        f"!is_sorcery); got gy_p0={sorted(rust_p0_gy_names)!r}"
    )


def test_xxx_probe_roving_actuator_empty_filter_no_op():
    """**18th Rust slice XXX Pin 2 closure -- empty-filter no-op
    invariant.**

    The Python SoT (``RovingActuatorETBEffect.resolve``) silently
    no-ops when ``not targets`` (no legal gy target).  Rust's arm
    mirrors this: if the first-legal scan returns ``None``, the
    arm returns ``Ok(())`` without mutating any zone.

    Probe shape: inject Roving Actuator on a bf with only a
    filtered-out gy creature, resolve, assert nothing moved (no
    exile transition, no damage dealt).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_rust_state,
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rust_state = build_rust_state(spec)
    ZONE_BATTLEFIELD = 2
    ZONE_GRAVEYARD = 3

    # Only a creature in gy (filtered out -- no legal target).
    rust_state.register_and_inject_object(
        {
            "name": "XXX Empty-Filter GY Creature",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1},
            "power": 1, "toughness": 1,
            "effects": [],
            "triggered_abilities": [],
        },
        0, ZONE_GRAVEYARD,
    )

    p1_life_before = rust_state.life_totals[1]

    # Inject Roving Actuator; fires ETB.
    rust_state.register_and_inject_object(
        {
            "name": "XXX Roving Actuator (empty-filter probe)",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 2, "B": 1},
            "power": 2, "toughness": 2,
            "effects": [],
            "triggered_abilities": [{
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "roving_actuator_etb",
                    "max_mv": 2,
                },
            }],
        },
        0, ZONE_BATTLEFIELD,
    )

    # Drain stack -- ETB trigger resolves but the filter scan finds
    # no legal target, so it silently no-ops.
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()

    # Post-resolve: the gy creature should still be there (no zone
    # transitions on the no-op path).
    rust_p0_gy = rust_state.graveyard_snapshot(0)
    rust_p0_gy_names = {e["printing_name"] for e in rust_p0_gy}
    assert "XXX Empty-Filter GY Creature" in rust_p0_gy_names, (
        "Rust XXX Pin 2 closure: empty-filter no-op should leave "
        "the gy creature in P0's graveyard (no zone transitions); "
        f"got gy_p0={sorted(rust_p0_gy_names)!r}"
    )

    # Exile is empty (no zone transition happened).
    rust_p0_exile = rust_state.exile_snapshot(0)
    rust_p0_exile_names = {e["printing_name"] for e in rust_p0_exile}
    assert not rust_p0_exile_names, (
        "Rust XXX Pin 2 closure: empty-filter no-op should leave "
        "P0's exile empty (no zone transitions); got "
        f"exile_p0={sorted(rust_p0_exile_names)!r}"
    )

    # P1 life unchanged (no copy resolved).
    p1_life_after = rust_state.life_totals[1]
    assert p1_life_after == p1_life_before, (
        "Rust XXX Pin 2 closure: empty-filter no-op should leave "
        "P1's life unchanged (no copy resolved); got "
        f"p1_life_before={p1_life_before} p1_life_after={p1_life_after}"
    )


def test_xxx_probe_roving_actuator_mv_filter_excludes_high_mv_spell():
    """**18th Rust slice XXX Pin 2 closure -- MV<=max_mv filter
    invariant.**

    The Python SoT filters graveyard cards by ``mana_cost.total <=
    self.max_mv`` (effects/bespoke.py:658).  Rust mirrors via the
    sum of all colored + generic in ``mana_cost``.  This probe
    seats a high-MV (3) sorcery + a low-MV (1) instant in the gy;
    the first-legal scan must pick the instant (skipping the
    high-MV sorcery as an MV-filter test).

    Note on insertion order: ``register_and_inject_object`` pushes
    onto the gy in insertion order, so the high-MV sorcery (seated
    first) sits at gy[0] and the low-MV instant at gy[1].  The
    Rust first-legal scan walks gy in insertion order; the high-MV
    sorcery is REJECTED by the MV filter (3 > 2), then the low-MV
    instant is picked.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_rust_state,
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rust_state = build_rust_state(spec)
    ZONE_BATTLEFIELD = 2
    ZONE_GRAVEYARD = 3

    # High-MV (3) sorcery -- rejected by max_mv=2 filter.
    rust_state.register_and_inject_object(
        {
            "name": "XXX Probe HighMV Sorcery (MV3, filtered)",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 2, "B": 1},
            "effects": [
                {
                    "kind": "deal_damage",
                    "amount": 5,  # large enough to be unmistakable
                    "target": {"kind": "any_player"},
                },
            ],
            "triggered_abilities": [],
        },
        0, ZONE_GRAVEYARD,
    )
    # Low-MV (1) instant -- picked.
    rust_state.register_and_inject_object(
        {
            "name": "XXX Probe LowMV Instant (MV1, picked)",
            "card_types": ["Instant"],
            "mana_cost": {"R": 1},
            "effects": [
                {
                    "kind": "deal_damage",
                    "amount": 2,
                    "target": {"kind": "any_player"},
                },
            ],
            "triggered_abilities": [],
        },
        0, ZONE_GRAVEYARD,
    )

    p1_life_before = rust_state.life_totals[1]

    # Inject Roving Actuator; fires ETB.
    rust_state.register_and_inject_object(
        {
            "name": "XXX Roving Actuator (MV-filter probe)",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 2, "B": 1},
            "power": 2, "toughness": 2,
            "effects": [],
            "triggered_abilities": [{
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "roving_actuator_etb",
                    "max_mv": 2,
                },
            }],
        },
        0, ZONE_BATTLEFIELD,
    )

    # Drain stack.
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()

    # Post-resolve: the low-MV instant is in exile (picked), the
    # high-MV sorcery is still in graveyard (rejected by MV
    # filter), and P1's life dropped by exactly 2 (the low-MV
    # instant's damage), NOT 5 (which would mean the high-MV
    # sorcery was incorrectly picked).
    rust_p0_gy = rust_state.graveyard_snapshot(0)
    rust_p0_gy_names = {e["printing_name"] for e in rust_p0_gy}
    rust_p0_exile = rust_state.exile_snapshot(0)
    rust_p0_exile_names = {e["printing_name"] for e in rust_p0_exile}

    assert (
        "XXX Probe HighMV Sorcery (MV3, filtered)" in rust_p0_gy_names
    ), (
        "Rust XXX Pin 2 closure: the MV3 sorcery should remain in "
        "P0's graveyard (rejected by MV<=2 filter); got "
        f"gy_p0={sorted(rust_p0_gy_names)!r}"
    )
    assert (
        "XXX Probe LowMV Instant (MV1, picked)" in rust_p0_exile_names
    ), (
        "Rust XXX Pin 2 closure: the MV1 instant should be in P0's "
        "exile (picked by first-legal scan post-MV filter); got "
        f"exile_p0={sorted(rust_p0_exile_names)!r}"
    )
    p1_life_after = rust_state.life_totals[1]
    assert p1_life_after == p1_life_before - 2, (
        "Rust XXX Pin 2 closure: P1 should have taken EXACTLY 2 "
        "damage (the low-MV instant's payload), not 5 (which would "
        "indicate the high-MV sorcery was incorrectly picked); "
        f"got p1_life_before={p1_life_before} "
        f"p1_life_after={p1_life_after}"
    )
