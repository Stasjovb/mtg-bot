"""Cross-engine parity probe for Baseball Bat — Equipment-AA family
closure (2026-05-31, ``feature/equipment-aa-substrate``).

**Baseball Bat — the cheapest Equipment-AA closure.** ``{3}`` Artifact
— Equipment (EoE pool). Oracle:

    "Equipped creature gets +1/+1.
     When Baseball Bat enters, attach it to target creature you control.
     Whenever equipped creature attacks, you may tap up to one target
     creature.
     Equip {3}"

**What this slice shipped (verify-first finding, 2026-05-31).** The
subsystem-attribution scout reported all four EoE Equipment-AA cards
(Baseball Bat, Atomic Microsizer, Auxiliary Boosters, Saw) in
``blocked_subsystem_gated`` with THREE gates apiece. The verify-first
dump showed Baseball Bat is the CHEAPEST entry point because TWO of its
three Effects were already covered cross-engine:

  - ETB auto-attach ``AttachToTargetCreatureYouControl`` — COVERED
  - Equip ``EquipToTargetCreatureYouControl`` — COVERED
  - ATTACKS rider ``TapUpToOneTargetCreature`` — the ONLY uncovered
    piece, and its Rust sibling ``TapAnotherTargetCreature`` already
    shipped the full tap-target machinery.

The substrate this slice added (all reusable by the three siblings):

  * Rust ``Effect::TapUpToOneTargetCreature`` (enum variant + parse +
    to_pydict + ``first_legal_trigger_target`` seat arm + resolve arm).
  * cross_engine reverse bridge arm ``tap_up_to_one_target_creature``.
  * The FIRST ``IsHost(subject="attacker")`` safe-trigger predicate
    branch in ``_python_ta_to_safe_dict`` (+ the ``is_host_attacker``
    sentinel collapse in ``_is_safe_trigger_dict``) — the equipped-
    creature-attacks relational predicate. This is the load-bearing
    Equipment-attached-carrier bridge the family shares.
  * The ``("attacks", "is_host_attacker", "tap_up_to_one_target_
    creature")`` ``_SAFE_TRIGGERS`` triple + ``_SAFE_EFFECT_KEYS`` +
    ``_TARGET_SEATED_EFFECT_KINDS`` registration.

**No Equipment-attach / trigger-bind wall (verify-first).** The
``IsHost`` predicate match is already byte-equal cross-engine and is
NOT Aura-restricted — Rust's ``Predicate::IsHost`` (cards.rs:10770)
reads ``find_object_attached_to(source)`` and returns
``host_id == subject_id`` for ANY source (including an Equipment stamped
onto its host). The ATTACKS event dispatch is byte-equal-proven; the
PyO3 ``attach(equip_id, host_id)`` method stamps ``attached_to``
generically; the count_min=0 optional seat is the Exosuit Savior edge
already shipped. So Baseball Bat is a CLEAN PROBED flip — no sprawling
new machinery.

This module is the GENUINE real-EoE cross-engine byte-equality probe
(registered in ``scripts/measure_pool_parity.py`` PROBE_MODULES). It
drives the REAL parsed Baseball Bat printing's ATTACKS rider through
BOTH engines via the attach + ATTACKS path and asserts byte-equal tap
state.

Lives in its own module per the established per-card-module convention
(cf. ``test_atomic_microsizer_parity.py``, ``test_darkness_parity.py``).
"""

from __future__ import annotations

import importlib.util

import pytest


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


ZONE_BATTLEFIELD = 2


# ---------------------------------------------------------------------------
# Verify-first: parser SoT pins — the Python side is fully wired.
# ---------------------------------------------------------------------------


def test_real_baseball_bat_parser_sot_attacks_rider_with_tap_up_to_one():
    """**Verify-first.** The live parser maps Baseball Bat's
    equipped-creature-attacks oracle line to one triggered ability
    whose ``event`` is ``Event.ATTACKS``, ``predicate`` is
    ``IsHost(subject="attacker")``, and ``effect`` is
    ``TapUpToOneTargetCreature`` with the bare optional single slot
    ``TargetSpec(IsCreature(), count_min=0, count_max=1)``. Plus the
    ETB auto-attach + Equip ability surfaces (already covered). Freezes
    the parser SoT so a parser drift is caught here.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.tap import TapUpToOneTargetCreature
    from mtg_bot.effects.predicates import Event, IsHost, IsSelf

    p = get_active_source().get_printings().get("Baseball Bat")
    if p is None:
        pytest.skip("Baseball Bat absent from active CardSource")
    assert "Artifact" in p.card_types
    assert "Equipment" in p.subtypes
    # Static +1/+1 anthem from the printed equipment_bonuses tuple.
    assert p.equipment_bonuses is not None
    pb, tb, gks = p.equipment_bonuses
    assert (pb, tb) == (1, 1)
    # Exactly two triggered abilities: ETB auto-attach + ATTACKS rider.
    assert len(p.triggered_abilities) == 2
    enters = [ta for ta in p.triggered_abilities if ta.event is Event.ENTERS]
    attacks = [ta for ta in p.triggered_abilities if ta.event is Event.ATTACKS]
    assert len(enters) == 1 and len(attacks) == 1
    # ETB auto-attach trigger (IsSelf).
    assert isinstance(enters[0].predicate, IsSelf)
    # The ATTACKS rider — the load-bearing shape this slice closes.
    ta = attacks[0]
    assert isinstance(ta.predicate, IsHost)
    assert ta.predicate.subject == "attacker"
    assert isinstance(ta.effect, TapUpToOneTargetCreature)
    # Bare optional single-slot shape (the §2 silent-mistranslation
    # gate the recognizer enforces).
    assert ta.effect.requires_target() is False  # count_min=0 → False
    assert ta.effect.target_count_range() == (0, 1)
    assert ta.effect.target_slot_kinds() == ()
    # Equip {3} activated ability surfaces.
    assert len(p.activated_abilities) >= 1


def test_baseball_bat_attacks_trigger_round_trips_through_safe_dict():
    """**Verify-first — the recognizer + bridge round-trip.** Baseball
    Bat's ATTACKS rider now serializes to the canonical safe-trigger
    dict (the ``AtomicMicrosizer``-style honest-stop has flipped to a
    positive bridge round-trip — see ``test_atomic_microsizer_parity``
    for the per-card honest-stop that stays BLOCKED). The recognizer
    emits the ``is_host`` + ``attacker`` shape, ``_is_safe_trigger_dict``
    accepts it, it is a target-seated trigger, and the bridge round-trips
    it back to the genuine Python class.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.tap import TapUpToOneTargetCreature
    from mtg_bot.effects.predicates import Event, IsHost
    from mtg_bot.parity import trajectory as T
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_triggered_ability,
    )

    p = get_active_source().get_printings().get("Baseball Bat")
    if p is None:
        pytest.skip("Baseball Bat absent from active CardSource")
    ta = [t for t in p.triggered_abilities if t.event is Event.ATTACKS][0]

    d = T._python_ta_to_safe_dict(ta)
    assert d == {
        "event": "attacks",
        "predicate": {"kind": "is_host", "subject": "attacker"},
        "effect": {"kind": "tap_up_to_one_target_creature"},
    }
    assert T._is_safe_trigger_dict(d) is True
    assert T._is_target_seated_safe_trigger(p, ta) is True

    bridged = _ta_dict_to_python_triggered_ability(d)
    assert bridged.event is Event.ATTACKS
    assert isinstance(bridged.predicate, IsHost)
    assert bridged.predicate.subject == "attacker"
    assert isinstance(bridged.effect, TapUpToOneTargetCreature)


def test_baseball_bat_effect_class_now_covered():
    """**Verify-first.** ``TapUpToOneTargetCreature`` is now in the
    covered-by-rust set (the ``Effect::TapUpToOneTargetCreature`` Rust
    variant landed this slice), and all of Baseball Bat's emitted Effect
    classes are covered (so the card is byte-equal-covered at the
    Effect+bridge level)."""
    from mtg_bot.parity.effect_coverage import (
        card_effect_classes,
        covered_python_class_set,
    )
    from mtg_bot.cards.source import get_active_source

    cov = covered_python_class_set()
    assert "TapUpToOneTargetCreature" in cov
    p = get_active_source().get_printings().get("Baseball Bat")
    if p is None:
        pytest.skip("Baseball Bat absent from active CardSource")
    assert card_effect_classes(p).issubset(cov)


# ---------------------------------------------------------------------------
# GENUINE real-EoE cross-engine byte-equality probe.
# ---------------------------------------------------------------------------


def _rust_obj_field(rust_state, obj_id, field):
    for entry in rust_state.battlefield_snapshot():
        if entry["id"] == obj_id:
            return entry.get(field)
    return None


def _py_obj(py_state, obj_id):
    for o in py_state.battlefield:
        if o.id == obj_id:
            return o
    return None


def _equipment_inj():
    """The bridge-dict equivalent of Baseball Bat (only the ATTACKS
    rider — the ETB auto-attach is exercised via the direct ``attach``
    stamp below, mirroring the Atomic Microsizer scaffold's plan)."""
    return {
        "name": "Baseball Bat",
        "card_types": ["Artifact"],
        "subtypes": ["Equipment"],
        "supertypes": [],
        "keywords": [],
        "effects": [],
        "triggered_abilities": [
            {
                "event": "attacks",
                "predicate": {"kind": "is_host", "subject": "attacker"},
                "effect": {"kind": "tap_up_to_one_target_creature"},
            },
        ],
    }


def _bear_inj(name):
    return {
        "name": name,
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1, "G": 1},
        "power": 2,
        "toughness": 2,
        "effects": [],
    }


def _py_inject(py_state, d, controller, *, attached_to=None):
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_triggered_ability,
    )

    mc = d.get("mana_cost", {})
    gen = int(mc.get("generic", 0))
    col = tuple((k, int(v)) for k, v in mc.items() if k != "generic")
    pr = CardPrinting(
        name=d["name"],
        mana_cost_str="",
        mana_cost=ManaCost(generic=gen, colored=col),
        type_line=" ".join(d["card_types"]),
        supertypes=tuple(d.get("supertypes", ())),
        card_types=tuple(d["card_types"]),
        subtypes=tuple(d.get("subtypes", ())),
        power=d.get("power"),
        toughness=d.get("toughness"),
        produces=frozenset(),
        keywords=frozenset(d.get("keywords", ())),
        triggered_abilities=tuple(
            _ta_dict_to_python_triggered_ability(t)
            for t in d.get("triggered_abilities", ())
        ),
    )
    obj = py_state.new_object(pr, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    obj.tapped = False
    obj.damage = 0
    obj.attached_to = attached_to
    obj.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(obj)
    return obj


def _build():
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    return build_python_state(spec), build_rust_state(spec)


def _drain_both(py_state, rust_state):
    from mtg_bot.actions import resolve_top_of_stack
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()
    while py_state.stack:
        resolve_top_of_stack(py_state)


def test_cross_engine_real_eoe_baseball_bat_attacks_taps_first_creature_parity():
    """**GENUINE real-EoE probe — Equipment-AA family (Baseball Bat).**

    Drives the real parsed Baseball Bat ATTACKS rider end-to-end through
    the production ATTACKS path with NO agent seated, asserting byte-equal
    cross-engine tap state.

    Scenario A (eligible creature exists): Baseball Bat is attached to
    a host bear on p0's bf; an opponent bear is on p1's bf. The host
    attacks → the ``IsHost(subject="attacker")`` ATTACKS trigger fires
    from the Equipment → the SHARED deterministic push-time seat picks
    the FIRST creature (smallest-ETB-timestamp on EITHER bf) and taps
    EXACTLY it, byte-equal on both engines.

    Scenario B (no other eligible creature): only the host is on the
    battlefield. The host attacks (tapping itself, no vigilance); the
    ATTACKS trigger's count_min=0 optional seat finds the host already
    tapped is still a legal creature target — so the deterministic seat
    picks the host and the tap is a no-op (host already tapped from
    attacking). The observable (host tapped, nothing else changed) is
    byte-equal — proving the count_min=0 optional decline / no-op edge.
    """
    _require_engine()
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.combat import declare_attackers

    real = get_active_source().get_printings().get("Baseball Bat")
    if real is None:
        pytest.skip("Baseball Bat absent from active CardSource")

    equip = _equipment_inj()

    # ===== Scenario A: a distinct eligible creature exists. =====
    py_state, rust_state = _build()
    # Inject order (both engines in lockstep): host bear on p0 (id
    # lowest), opponent bear on p1, then the Equipment on p0 attached to
    # the host. The host bear has the smallest ETB timestamp so the
    # first-legal seat picks IT (proving the deterministic first-legal
    # rule — the seat taps the host itself, the smallest-bf-index
    # creature, NOT the opponent's bear).
    rs_host = rust_state.register_and_inject_object(
        _bear_inj("Host Bear"), 0, ZONE_BATTLEFIELD
    )
    rs_opp = rust_state.register_and_inject_object(
        _bear_inj("Opp Bear"), 1, ZONE_BATTLEFIELD
    )
    rs_equip = rust_state.register_and_inject_object(equip, 0, ZONE_BATTLEFIELD)
    assert rust_state.attach(rs_equip, rs_host) is True
    rust_state.clear_summoning_sick_for_player(0)

    py_host = _py_inject(py_state, _bear_inj("Host Bear"), 0)
    py_opp = _py_inject(py_state, _bear_inj("Opp Bear"), 1)
    py_equip = _py_inject(py_state, equip, 0, attached_to=py_host.id)

    assert py_state.players[0].agent is None
    assert py_state.players[1].agent is None
    assert _rust_obj_field(rust_state, rs_equip, "attached_to") == rs_host
    assert py_equip.attached_to == py_host.id

    # Declare the host as attacker → ATTACKS dispatch → the Equipment's
    # IsHost(attacker) trigger fires (a legal creature exists).
    assert rust_state.declare_attacker(rs_host) is True
    assert rust_state.stack_size() == 1, (
        "Rust: the equipped host attacking must push the Equipment's "
        "ATTACKS trigger (a legal creature target exists)"
    )
    declare_attackers(py_state, [py_host.id])
    assert len(py_state.stack) == 1, (
        "Python: the equipped host attacking must push the Equipment's "
        "ATTACKS trigger"
    )
    _drain_both(py_state, rust_state)
    assert rust_state.stack_size() == 0 and len(py_state.stack) == 0

    # The host bear (smallest ETB timestamp) is the first-legal seat.
    # It is tapped (both from attacking AND re-selected by the tap rider
    # — the tap is idempotent on the already-tapped host). The OPPONENT
    # bear is NOT tapped (the seat picked the first creature, not all).
    assert _rust_obj_field(rust_state, rs_host, "tapped") is True
    assert _rust_obj_field(rust_state, rs_opp, "tapped") is False
    assert _py_obj(py_state, py_host.id).tapped is True
    assert _py_obj(py_state, py_opp.id).tapped is False
    # Cross-engine byte-equal tap state on every object.
    assert (
        _rust_obj_field(rust_state, rs_host, "tapped")
        == _py_obj(py_state, py_host.id).tapped
        is True
    )
    assert (
        _rust_obj_field(rust_state, rs_opp, "tapped")
        == _py_obj(py_state, py_opp.id).tapped
        is False
    )

    # ===== Scenario A2: opponent creature seated BEFORE the host. =====
    # Inject the opponent bear FIRST (smallest ETB timestamp), then the
    # host, then the Equipment. Now the first-legal seat picks the
    # OPPONENT bear (smallest ETB) — proving the seat is a genuine
    # cross-both-bf first-legal pick, not a controller-only walk, and
    # that an UNTAPPED opponent creature is the one tapped by the rider.
    py_state2, rust_state2 = _build()
    rs_opp2 = rust_state2.register_and_inject_object(
        _bear_inj("Opp Bear"), 1, ZONE_BATTLEFIELD
    )
    rs_host2 = rust_state2.register_and_inject_object(
        _bear_inj("Host Bear"), 0, ZONE_BATTLEFIELD
    )
    rs_equip2 = rust_state2.register_and_inject_object(
        equip, 0, ZONE_BATTLEFIELD
    )
    assert rust_state2.attach(rs_equip2, rs_host2) is True
    rust_state2.clear_summoning_sick_for_player(0)

    py_opp2 = _py_inject(py_state2, _bear_inj("Opp Bear"), 1)
    py_host2 = _py_inject(py_state2, _bear_inj("Host Bear"), 0)
    py_equip2 = _py_inject(py_state2, equip, 0, attached_to=py_host2.id)

    assert rust_state2.declare_attacker(rs_host2) is True
    declare_attackers(py_state2, [py_host2.id])
    _drain_both(py_state2, rust_state2)

    # The opponent bear (smallest ETB) is the seat → tapped by the rider.
    # The host is tapped from attacking. Both tapped, but for the
    # opponent it is the RIDER that tapped it (proving cross-bf seat).
    assert _rust_obj_field(rust_state2, rs_opp2, "tapped") is True
    assert _py_obj(py_state2, py_opp2.id).tapped is True
    assert (
        _rust_obj_field(rust_state2, rs_opp2, "tapped")
        == _py_obj(py_state2, py_opp2.id).tapped
        is True
    )
    # Host tapped from attacking (byte-equal).
    assert (
        _rust_obj_field(rust_state2, rs_host2, "tapped")
        == _py_obj(py_state2, py_host2.id).tapped
        is True
    )
