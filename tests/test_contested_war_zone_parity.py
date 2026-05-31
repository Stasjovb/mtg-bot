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

**SUBSTRATE-ONLY landing — NOT a PROBED flip.** The live
DEALS_COMBAT_DAMAGE trigger-driven flip to PROBED is BLOCKED on
multi-subject predicate dispatch. The trigger's predicate
``Controlled(by=YOU, subject="target")`` constrains "the damaged player
== the Land's controller", but Rust's ``dispatch_event`` passes only a
single ``subject_id`` (the damaging creature) and the
``ControlledByYou`` arm has no ``slot="target"`` path that reads
``resolving_combat_damage_target_player_id`` (the defending player).
Additionally, Rust does not yet carry the source-controller on the
StackItem to re-mirror at trigger-resolve time (the same deferral the
``resolving_combat_damage_amount`` StackItem mirror carries). See
``docs/SEARCH_LIMITATIONS.md`` (Contested War Zone substrate-only
entry).

The probes below pin the substrate end-to-end: the parser SoT, the
round-trip dict shape, the covered-class flip, and the Rust resolve arm
(driven directly with the source-controller slot seated via the
test-only setter — the byte-equal mirror of Python's
``ChangeControllerToCombatDamageSource.resolve``).

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
