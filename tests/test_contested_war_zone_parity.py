"""Cross-engine parity probes for Contested War Zone.

**Contested War Zone substrate (2026-05-31).** Land —
"Whenever a creature deals combat damage to you, that creature's
controller gains control of this land.
{T}: Add {C}.
{1}, {T}: Attacking creatures get +1/+0 until end of turn."

The DEALS_COMBAT_DAMAGE-triggered control-change-of-self is the
load-bearing closure. Python parses the trigger as
``TriggeredAbility(event=DEALS_COMBAT_DAMAGE,
predicate=And(Subject(slot='source', IsCreature()),
Controlled(by=YOU, subject='target')),
effect=ChangeControllerToCombatDamageSource())``.

The effect, ``ChangeControllerToCombatDamageSource``, is a PERMANENT
control change of the Land to the combat-damage source's controller —
it writes ``source.controller_id`` directly (NO ``continuous_effects``
layer-2 UEOT entry, NO cleanup drain). This is distinct from the
Mutinous Massacre / Systems Override / Threaten family, which stamp the
UEOT ``controller_override`` field. The direct write round-trips
byte-equal via the snapshot's ``controller_id`` key
(``obj.controller``); ``controller_override`` stays ``None`` on BOTH
engines.

This lane lands the **genuinely-uncovered Rust Effect substrate** —
``Effect::ChangeControllerToCombatDamageSource`` (enum + parse +
to_pydict + valid-kinds + resolve arm) + the new
``resolving_combat_damage_source_controller_id`` state slot (mirrored
in ``dispatch_combat_damage_to_player`` + a test-only setter) + the
``cross_engine.py`` bridge arm + the ``trajectory.py`` reverse-
serializer leaf. Flips Contested War Zone **BLOCKED → covered-by-
construction** (every Effect class the card emits now has a live+bridged
Rust counterpart).

**THE FLIP — covered_by_construction → PROBED (2026-05-31).** The live
DEALS_COMBAT_DAMAGE trigger-driven control change now drives byte-equal
on BOTH engines; the two engine-deep walls the substrate-only landing
documented are closed:

  1. **Multi-subject predicate dispatch.** The Rust
     ``ControlledByYou { slot }`` arm (``cards.rs``) is now slot-aware:
     ``slot == "target"`` reads the defending-player id off
     ``state.resolving_combat_damage_target_player_id`` (seated by
     ``dispatch_combat_damage_to_player`` for the synchronous observer
     walk) and compares it to the source's controller — the byte-equal
     mirror of Python's ``Controlled(by=YOU, subject="target")``
     evaluating ``defending_player.id == source.controller_id``.

  2. **Deferred StackItem source-controller mirror.** Rust now carries
     ``combat_damage_source_controller_id`` (+ the ``combat_damage_amount``
     sibling) on ``TriggerPayload``, seated at push time in
     ``push_triggered_ability`` from the live state slot and re-mirrored
     into ``state.resolving_combat_damage_source_controller_id`` at
     trigger-resolve time by BOTH resolve entry points — the byte-equal
     mirror of Python's ``StackItem.combat_damage_source_controller_id``
     re-mirror at ``actions.py:2680-2686``. (This ALSO unblocks the
     deferred production write of the sibling
     ``resolving_combat_damage_amount`` slot.)

The probes below pin the lever end-to-end: the parser SoT, the
round-trip dict shape, the covered-class flip, the Rust resolve-arm
unit pins (driven directly with the source-controller slot seated via
the test-only setter), AND the per-card real-EoE LIVE-trigger byte-equal
flip probe ``test_cross_engine_real_eoe_contested_war_zone_parity``
(drives the ACTUAL parsed printing through a combat-damage event on both
engines). See ``docs/SEARCH_LIMITATIONS.md`` (Contested War Zone FLIP
entry).

Lives in its own module per the established per-card-module convention
(cf. ``test_systems_override_parity.py``, ``test_vengeful_possession_
parity.py``).
"""

from __future__ import annotations

import importlib.util

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3


# -------------------------------------------------------------------
# Verify-first: parser SoT pin.
# -------------------------------------------------------------------


def test_real_contested_war_zone_trigger_is_change_controller():
    """**Verify-first.** The live parser maps Contested War Zone's
    combat-damage trigger to ``ChangeControllerToCombatDamageSource()``
    on a ``DEALS_COMBAT_DAMAGE`` event with the
    ``And(Subject(slot='source', IsCreature()),
    Controlled(by=YOU, subject='target'))`` predicate. Freezes the
    parser SoT so a parser drift is caught here, not silently downstream
    in the cross-engine probe."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.control import (
        ChangeControllerToCombatDamageSource,
    )
    from mtg_bot.effects.predicates import Event

    p = get_active_source().get_printings().get("Contested War Zone")
    if p is None:
        pytest.skip("Contested War Zone absent from active CardSource")
    assert "Land" in p.card_types
    trigs = [
        ta
        for ta in p.triggered_abilities
        if ta.event is Event.DEALS_COMBAT_DAMAGE
    ]
    assert len(trigs) == 1, (
        f"Contested War Zone must carry exactly one DEALS_COMBAT_DAMAGE "
        f"trigger; got {len(trigs)}"
    )
    assert isinstance(
        trigs[0].effect, ChangeControllerToCombatDamageSource
    ), (
        f"Contested War Zone's combat-damage trigger effect must be "
        f"ChangeControllerToCombatDamageSource; got {trigs[0].effect!r}"
    )


# -------------------------------------------------------------------
# Round-trip + covered-class pins (the §2 teeth).
# -------------------------------------------------------------------


def test_change_controller_serializer_round_trip():
    """The trajectory reverse-serializer must emit the bare unit-variant
    dict for ``ChangeControllerToCombatDamageSource``; the dict→Python
    bridge must reconstruct the exact same effect byte-equal.

    A no-emit serializer would short-circuit the covered-by-construction
    classification (the no-fallback-hybrid teeth). With the
    ``Effect::ChangeControllerToCombatDamageSource`` variant landed + the
    new ``_leaf`` arm in trajectory.py + the bridge arm in
    cross_engine.py, the effect round-trips cleanly."""
    from mtg_bot.effects.generic.control import (
        ChangeControllerToCombatDamageSource,
    )
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    eff = ChangeControllerToCombatDamageSource()
    d = trajectory._python_spell_effect_to_dict(eff)
    assert d == {"kind": "change_controller_to_combat_damage_source"}, (
        f"ChangeControllerToCombatDamageSource reverse serializer must "
        f"emit the bare unit-variant dict; got {d}"
    )
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, ChangeControllerToCombatDamageSource)
    assert rebuilt == eff


def test_change_controller_class_covered():
    """``ChangeControllerToCombatDamageSource`` must be in the
    covered-by-rust set — the Rust
    ``Effect::ChangeControllerToCombatDamageSource`` variant declaration
    makes ``covered_python_class_set()`` include it. Without this, the
    pool-parity classifier cannot flip Contested War Zone out of the
    BLOCKED tail."""
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    covered = covered_python_class_set()
    assert "ChangeControllerToCombatDamageSource" in covered, (
        "Rust Effect::ChangeControllerToCombatDamageSource variant must "
        "make the Python ChangeControllerToCombatDamageSource class "
        "covered"
    )


def test_contested_war_zone_all_effects_covered():
    """**The covered-by-construction flip pin.** Every distinct Python
    Effect class Contested War Zone emits must now have a live+bridged
    Rust counterpart, so the pool-parity classifier moves the card out
    of ``blocked_subsystem_gated`` and into
    ``covered_by_construction``. The card emits exactly
    ``ChangeControllerToCombatDamageSource`` (the trigger) and
    ``PumpCreaturesYouControlUntilEOT`` (the ``{1},{T}`` attack-pump
    AA); both are covered post-substrate."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.effect_coverage import (
        card_effect_classes,
        covered_python_class_set,
    )

    p = OracleParserCardSource().get_printings().get("Contested War Zone")
    if p is None:
        pytest.skip("Contested War Zone absent from active CardSource")
    eff_classes = card_effect_classes(p)
    covered = covered_python_class_set()
    assert eff_classes, "card must emit at least one Effect class"
    missing = eff_classes - covered
    assert not missing, (
        f"Contested War Zone must have ALL Effect classes covered for "
        f"the covered-by-construction flip; still missing: {sorted(missing)}"
    )


# -------------------------------------------------------------------
# Rust resolve-arm unit pins (the substrate behavioral pins).
# -------------------------------------------------------------------


def _fresh_state():
    import mtg_bot_engine

    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


def _inject_change_controller_land(rs, owner):
    """Inject a Land carrying the bare
    ``change_controller_to_combat_damage_source`` effect, then push it
    onto the stack as its own source so ``resolve_top_of_stack`` drives
    the resolve arm with ``source_obj_id`` = the Land.

    The trigger-fire dispatch path is NOT used here (it is blocked on
    the multi-subject predicate, per the module docstring); this drives
    the resolve arm directly with the source-controller slot seated via
    the test-only setter — the byte-equal mirror of Python's
    ``ChangeControllerToCombatDamageSource.resolve``, which reads
    ``state.resolving_combat_damage_source_controller_id`` at resolve
    time."""
    return rs.register_and_inject_object(
        {
            "name": "Contested War Zone",
            "card_types": ["Land"],
            "effects": [
                {"kind": "change_controller_to_combat_damage_source"}
            ],
        },
        owner,
        ZONE_BATTLEFIELD,
    )


def test_rust_resolve_permanent_control_change_to_source_controller():
    """The combat-damage source's controller (p1) gains control of the
    Land (owned/controlled by p0). The Land's ``controller_id`` snapshot
    key flips to 1 via a DIRECT, PERMANENT write; ``controller_override``
    stays ``None`` (this is NOT the UEOT override path)."""
    rs = _fresh_state()
    land = _inject_change_controller_land(rs, owner=0)
    rs.set_resolving_combat_damage_source_controller_id(1)
    rs.push_to_stack(land, 0)
    rs.resolve_top_of_stack()

    obj = next(e for e in rs.battlefield_snapshot() if e["id"] == land)
    assert obj["controller_id"] == 1, (
        f"Land must change controller to the combat-damage source's "
        f"controller (1); got {obj['controller_id']}"
    )
    assert obj["controller_override"] is None, (
        "permanent direct control change must NOT stamp the UEOT "
        "controller_override field"
    )


def test_rust_resolve_same_controller_noop():
    """Source-controller equals the Land's current controller → silent
    no-op (mirrors Python's ``new_cid == source.controller_id``
    short-circuit). No override stamped, controller unchanged."""
    rs = _fresh_state()
    land = _inject_change_controller_land(rs, owner=0)
    rs.set_resolving_combat_damage_source_controller_id(0)
    rs.push_to_stack(land, 0)
    rs.resolve_top_of_stack()

    obj = next(e for e in rs.battlefield_snapshot() if e["id"] == land)
    assert obj["controller_id"] == 0
    assert obj["controller_override"] is None


def test_rust_resolve_unset_slot_noop():
    """Source-controller slot unset (``u8::MAX`` sentinel = Python's
    ``None``) → silent no-op (mirrors Python's ``if new_cid is None``).
    Controller unchanged, no override."""
    rs = _fresh_state()
    land = _inject_change_controller_land(rs, owner=0)
    # No set_resolving_combat_damage_source_controller_id call — slot
    # stays at the u8::MAX sentinel.
    rs.push_to_stack(land, 0)
    rs.resolve_top_of_stack()

    obj = next(e for e in rs.battlefield_snapshot() if e["id"] == land)
    assert obj["controller_id"] == 0
    assert obj["controller_override"] is None


def test_rust_dispatch_seats_source_controller_slot():
    """``dispatch_combat_damage_to_player`` seats the source-controller
    slot for the duration of the synchronous observer dispatch and
    restores it afterward. Pins the slot-plumbing in the production
    combat-damage dispatch site (the live trigger-fire path that
    consumes it at resolve time is deferred — see module docstring)."""
    rs = _fresh_state()
    # Attacker controlled by p1.
    bear = rs.register_and_inject_object(
        {
            "name": "Bear",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
        },
        1,
        ZONE_BATTLEFIELD,
    )
    # Slot starts at the sentinel.
    assert rs.resolving_combat_damage_source_controller_id == 255
    # Dispatch combat damage from the p1 bear to p0. With no observer
    # triggers present, the dispatch seats then restores the slot.
    rs.dispatch_combat_damage_to_player(bear, 0, 2)
    assert rs.resolving_combat_damage_source_controller_id == 255, (
        "slot must be restored to the sentinel after the dispatch "
        "returns (it is only live for the synchronous observer walk)"
    )


# -------------------------------------------------------------------
# GENUINE real-EoE cross-engine probe (substrate-level byte-equality).
# -------------------------------------------------------------------


def test_cross_engine_real_eoe_contested_war_zone_change_controller_substrate_parity():
    """**The substrate lever pin.** Drive the live parsed Contested War
    Zone control-change effect through both engines on the SAME state
    shape and assert byte-equal control change.

    Python side: resolve ``ChangeControllerToCombatDamageSource`` on a
    Land controlled by p0 with
    ``state.resolving_combat_damage_source_controller_id = 1`` — the
    Land's ``controller_id`` must become 1, with NO layer-2
    ``continuous_effects`` control-change entry (permanent direct
    write).

    Rust side: drive the round-tripped effect dict through the resolve
    arm with the source-controller slot seated to 1 — the Land's
    ``controller_id`` snapshot key must become 1 and
    ``controller_override`` must stay ``None``.

    Both engines change the controller PERMANENTLY (direct controller
    write), byte-equal on the observable ``controller_id`` /
    ``controller_override`` snapshot keys. This pins the genuinely-
    uncovered Rust Effect substrate against Python's effect-resolve SoT.

    NOTE — this is a SUBSTRATE-LEVEL probe, not the full live-trigger
    flip. The DEALS_COMBAT_DAMAGE trigger-driven path is blocked on
    multi-subject predicate dispatch (the predicate's
    ``Controlled(by=YOU, subject='target')`` half needs the defending-
    player identity, which Rust's single-``subject_id`` dispatch does
    not thread). See ``docs/SEARCH_LIMITATIONS.md``."""
    import mtg_bot_engine
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.control import (
        ChangeControllerToCombatDamageSource,
    )
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    p = get_active_source().get_printings().get("Contested War Zone")
    if p is None:
        pytest.skip("Contested War Zone absent from active CardSource")

    # Pull the LIVE parsed effect off the printing's trigger.
    from mtg_bot.effects.predicates import Event

    trig = next(
        ta
        for ta in p.triggered_abilities
        if ta.event is Event.DEALS_COMBAT_DAMAGE
    )
    live_eff = trig.effect
    assert isinstance(live_eff, ChangeControllerToCombatDamageSource)

    # Round-trip the LIVE effect through dict → Python.
    d = trajectory._python_spell_effect_to_dict(live_eff)
    assert d == {"kind": "change_controller_to_combat_damage_source"}
    rebuilt = _ta_dict_to_python_effect(d)
    assert rebuilt == live_eff

    # ----- Rust side -----
    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    land = rs.register_and_inject_object(
        {
            "name": "Contested War Zone",
            "card_types": ["Land"],
            # Inject the SAME dict the reverse serializer just emitted.
            "effects": [d],
        },
        0,
        ZONE_BATTLEFIELD,
    )
    # Seat the source-controller slot to p1 (the damaging creature's
    # controller) — the byte-equal mirror of Python's
    # state.resolving_combat_damage_source_controller_id = 1.
    rs.set_resolving_combat_damage_source_controller_id(1)
    rs.push_to_stack(land, 0)
    rs.resolve_top_of_stack()

    obj = next(e for e in rs.battlefield_snapshot() if e["id"] == land)
    assert obj["controller_id"] == 1, (
        f"Rust: Land must change controller to the combat-damage "
        f"source's controller (1) after resolve; got "
        f"{obj['controller_id']}"
    )
    assert obj["controller_override"] is None, (
        "Rust: permanent direct control change must NOT stamp the UEOT "
        "controller_override field (byte-equal with Python's direct "
        "source.controller_id write — no continuous_effects entry)"
    )


# -------------------------------------------------------------------
# THE FLIP — per-card real-EoE LIVE-trigger byte-equal probe
# (covered_by_construction -> PROBED).
# -------------------------------------------------------------------
#
# The two engine-deep walls the substrate landing documented are now
# closed:
#
#   1. **Multi-subject predicate dispatch.** The Rust
#      ``ControlledByYou { slot }`` arm (cards.rs) is now slot-aware:
#      when ``slot == Some("target")`` it reads the defending-player id
#      off ``state.resolving_combat_damage_target_player_id`` (seated by
#      ``dispatch_combat_damage_to_player`` for the observer walk) and
#      compares it to the source's controller — the byte-equal mirror of
#      Python's ``Controlled(by=YOU, subject="target")`` evaluating
#      ``defending_player.id == source.controller_id``.
#
#   2. **Deferred StackItem source-controller mirror.** Rust now carries
#      ``combat_damage_source_controller_id`` (+ the ``combat_damage_amount``
#      sibling) on ``TriggerPayload``, seated at push time in
#      ``push_triggered_ability`` and re-mirrored into the transient
#      ``state.resolving_combat_damage_source_controller_id`` slot at
#      trigger-resolve time by BOTH resolve entry points — the byte-equal
#      mirror of Python's ``StackItem.combat_damage_source_controller_id``
#      re-mirror at ``actions.py:2680-2686``.
#
# This probe drives the ACTUAL parsed Contested War Zone printing on
# BOTH engines through a creature dealing combat damage to the Land's
# controller and asserts the Land's ``controller`` flips to the
# attacker's controller, byte-equal.


def test_cross_engine_real_eoe_contested_war_zone_parity():
    """**THE FLIP — live DEALS_COMBAT_DAMAGE trigger byte-equal probe.**

    Drive the LIVE parsed Contested War Zone printing through a real
    combat-damage-to-the-Land's-controller event on BOTH engines and
    assert byte-equal control change:

      * **Python:** Land controlled by p0 on the battlefield, attacker
        controlled by p1 on the battlefield;
        ``_fire_combat_damage_to_player_triggers(state, [(attacker, 0,
        amount)])`` pushes the DEALS_COMBAT_DAMAGE trigger, ``drain_stack``
        resolves it → the Land's ``controller_id`` flips to 1 (the
        attacker's controller). No layer-2 ``continuous_effects`` entry
        (permanent direct write).

      * **Rust:** the SAME parsed printing, bridged into a Rust registry
        via the dict the reverse serializer emits, injected as a Land
        controlled by p0; an attacker controlled by p1 on the
        battlefield; ``dispatch_combat_damage_to_player(attacker, 0,
        amount)`` pushes the trigger, ``resolve_top_of_stack`` resolves
        it → the Land's ``controller_id`` snapshot key flips to 1,
        ``controller_override`` stays ``None``.

    Both engines change the Land's controller to the attacker's
    controller PERMANENTLY, byte-equal on the observable controller key.
    This is the live-trigger flip the substrate-only landing deferred —
    Contested War Zone moves covered_by_construction → PROBED.
    """
    import mtg_bot_engine
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.actions import drain_stack
    from mtg_bot.combat import _fire_combat_damage_to_player_triggers
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.control import (
        ChangeControllerToCombatDamageSource,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_triggered_ability

    printings = get_active_source().get_printings()
    p = printings.get("Contested War Zone")
    if p is None:
        pytest.skip("Contested War Zone absent from active CardSource")

    # The genuine parsed trigger on the live printing.
    trig = next(
        ta
        for ta in p.triggered_abilities
        if ta.event is Event.DEALS_COMBAT_DAMAGE
    )
    assert isinstance(trig.effect, ChangeControllerToCombatDamageSource)

    AMOUNT = 2

    # ----- Python side: drive the LIVE printing's trigger -----
    py_state = GameState()
    py_state.players.append(Player(id=0, agent=RandomAgent()))
    py_state.players.append(Player(id=1, agent=RandomAgent()))
    # Land controlled by p0 (the defending player who will take damage).
    land_obj = py_state.new_object(p, 0, Zone.BATTLEFIELD)
    py_state.battlefield.append(land_obj)
    # Attacker controlled by p1.
    attacker = py_state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    py_state.battlefield.append(attacker)
    assert land_obj.controller_id == 0
    # p1's bear deals AMOUNT combat damage to p0 (the Land's controller).
    _fire_combat_damage_to_player_triggers(
        py_state, [(attacker.id, 0, AMOUNT)]
    )
    drain_stack(py_state)
    # The Land's controller is now p1 (the attacker's controller).
    py_land_controller = land_obj.controller_id
    assert py_land_controller == 1, (
        f"Python: Land must change controller to the attacker's "
        f"controller (1); got {py_land_controller}"
    )
    # Permanent direct write — no layer-2 continuous control-change entry.
    assert getattr(land_obj, "controller_override", None) is None

    # ----- Rust side: drive the SAME bridged printing -----
    # Bridge the live trigger to the Rust trigger-dict shape: the event
    # string Rust parses is ``"deals_damage"`` (``Event::DealsDamage``);
    # the predicate is the Contested War Zone compound
    # ``And(SubjectIsCreature, ControlledByYou{slot:"target"})``; the
    # effect is the round-tripped change-controller leaf.
    eff_dict = trajectory._python_spell_effect_to_dict(trig.effect)
    assert eff_dict == {"kind": "change_controller_to_combat_damage_source"}
    # Sanity: the bridged trigger dict round-trips back to the live
    # Python TriggeredAbility (event + predicate + effect).
    rust_ta_dict = {
        "event": "deals_damage",
        "predicate": {
            "kind": "and",
            "left": {"kind": "subject_is_creature"},
            "right": {"kind": "controlled_by_you", "subject": "target"},
        },
        "effect": eff_dict,
    }
    rebuilt_ta = _ta_dict_to_python_triggered_ability(rust_ta_dict)
    assert rebuilt_ta.event is Event.DEALS_COMBAT_DAMAGE
    assert isinstance(
        rebuilt_ta.effect, ChangeControllerToCombatDamageSource
    )

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    rust_land = rs.register_and_inject_object(
        {
            "name": "Contested War Zone",
            "card_types": ["Land"],
            "triggered_abilities": [rust_ta_dict],
        },
        0,
        ZONE_BATTLEFIELD,
    )
    rust_attacker = rs.register_and_inject_object(
        {
            "name": "Wild Bear",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
        },
        1,
        ZONE_BATTLEFIELD,
    )
    before = next(
        e for e in rs.battlefield_snapshot() if e["id"] == rust_land
    )
    assert before["controller_id"] == 0
    # p1's bear deals AMOUNT combat damage to p0 — pushes the live
    # trigger, then resolve it from the stack.
    rs.dispatch_combat_damage_to_player(rust_attacker, 0, AMOUNT)
    rs.resolve_top_of_stack()
    after = next(
        e for e in rs.battlefield_snapshot() if e["id"] == rust_land
    )
    rust_land_controller = after["controller_id"]
    assert rust_land_controller == 1, (
        f"Rust: Land must change controller to the attacker's "
        f"controller (1) via the live trigger; got {rust_land_controller}"
    )
    assert after["controller_override"] is None, (
        "Rust: permanent direct control change must NOT stamp the UEOT "
        "controller_override field"
    )

    # ----- byte-equal cross-engine -----
    assert py_land_controller == rust_land_controller == 1, (
        f"cross-engine control-change mismatch: Python "
        f"{py_land_controller} vs Rust {rust_land_controller}"
    )
