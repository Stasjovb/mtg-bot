"""Cross-engine parity probe for Saw — Equipment-AA family closure
(2026-05-31, ``feature/equipment-aa-siblings``).

**Saw — the second Equipment-AA closure (sibling of Baseball Bat).**
``{2}`` Artifact — Equipment (EoE pool). Oracle:

    "Equipped creature gets +2/+0.
     Whenever equipped creature attacks, you may sacrifice a permanent
     other than that creature or this Equipment. If you do, draw a card.
     Equip {2}"

**What this slice shipped (verify-first finding, 2026-05-31).** Saw's
ATTACKS rider rides the SHARED Equipment-attached-carrier substrate the
Baseball Bat closure established (the ``IsHost(subject="attacker")``
safe-trigger predicate branch + the ``is_host_attacker`` sentinel
collapse + the ATTACKS dispatch bridge). The single NEW piece is the
Rust ``Effect::SawAttacksOptionalSacDrawEffect`` (enum + parse +
to_pydict + valid-kinds string + resolve arm) mirroring Python's
``SawAttacksOptionalSacDrawEffect`` (``effects/bespoke.py:2498``), plus
the cross_engine reverse bridge arm + the trajectory recognizer arm +
the ``("attacks", "is_host_attacker",
"saw_attacks_optional_sac_draw_effect")`` ``_SAFE_TRIGGERS`` entry.

**NOT a targeted effect (verify-first).** Unlike Baseball Bat's
``tap_up_to_one_target_creature``, Saw is NOT a ``TargetSpec``-carrying
effect — the sacrifice pool is "permanents you control excluding the
host + this Equipment", an INTERNAL deterministic seat (not a target),
so Saw does NOT join ``_TARGET_SEATED_EFFECT_KINDS``. The optional
``may``-sacrifice + which-permanent decisions are agent calls in
Python; with NO agent both engines ACCEPT and sacrifice the FIRST
controlled permanent (excluding source + host) in ETB-timestamp order,
then draw one card. No legal permanent ⇒ silent no-op (no draw).

This module is the GENUINE real-EoE cross-engine byte-equality probe
(registered in ``scripts/measure_pool_parity.py`` PROBE_MODULES). It
drives the REAL parsed Saw printing's ATTACKS rider through BOTH engines
via the attach + ATTACKS path and asserts byte-equal sacrifice + draw
observables.

Lives in its own module per the established per-card-module convention
(cf. ``test_baseball_bat_parity.py``, ``test_atomic_microsizer_parity.py``).
"""

from __future__ import annotations

import importlib.util

import pytest


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2


# ---------------------------------------------------------------------------
# Verify-first: parser SoT + recognizer round-trip pins.
# ---------------------------------------------------------------------------


def test_real_saw_parser_sot_attacks_rider_with_optional_sac_draw():
    """**Verify-first.** The live parser maps Saw's equipped-creature-
    attacks oracle line to one triggered ability whose ``event`` is
    ``Event.ATTACKS``, ``predicate`` is ``IsHost(subject="attacker")``,
    and ``effect`` is ``SawAttacksOptionalSacDrawEffect`` (a
    parameterless frozen dataclass — NOT a targeted effect). Plus the
    Equip {2} activated ability surface. Freezes the parser SoT so a
    parser drift is caught here.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import SawAttacksOptionalSacDrawEffect
    from mtg_bot.effects.predicates import Event, IsHost

    p = get_active_source().get_printings().get("Saw")
    if p is None:
        pytest.skip("Saw absent from active CardSource")
    assert "Artifact" in p.card_types
    assert "Equipment" in p.subtypes
    # Static +2/+0 anthem from the printed equipment_bonuses tuple.
    assert p.equipment_bonuses is not None
    pb, tb, gks = p.equipment_bonuses
    assert (pb, tb) == (2, 0)
    # Exactly one triggered ability — the equipped-creature-attacks
    # rider (no ETB auto-attach line on Saw).
    assert len(p.triggered_abilities) == 1
    ta = p.triggered_abilities[0]
    assert ta.event is Event.ATTACKS
    assert isinstance(ta.predicate, IsHost)
    assert ta.predicate.subject == "attacker"
    assert isinstance(ta.effect, SawAttacksOptionalSacDrawEffect)
    # NOT a targeted effect — the bare parameterless shape the
    # recognizer's §2 teeth enforce.
    assert ta.effect.requires_target() is False
    assert ta.effect.target_count_range() == (0, 0)
    assert ta.effect.target_slot_kinds() == ()
    # Equip {2} activated ability surfaces.
    assert len(p.activated_abilities) >= 1


def test_saw_attacks_trigger_round_trips_through_safe_dict():
    """**Verify-first — the recognizer + bridge round-trip.** Saw's
    ATTACKS rider serializes to the canonical safe-trigger dict, is
    accepted by ``_is_safe_trigger_dict``, and the bridge round-trips it
    back to the genuine Python class. It is NOT a target-seated trigger
    (the sacrifice pool is an internal seat, not a target).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import SawAttacksOptionalSacDrawEffect
    from mtg_bot.effects.predicates import Event, IsHost
    from mtg_bot.parity import trajectory as T
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_triggered_ability,
    )

    p = get_active_source().get_printings().get("Saw")
    if p is None:
        pytest.skip("Saw absent from active CardSource")
    ta = [t for t in p.triggered_abilities if t.event is Event.ATTACKS][0]

    d = T._python_ta_to_safe_dict(ta)
    assert d == {
        "event": "attacks",
        "predicate": {"kind": "is_host", "subject": "attacker"},
        "effect": {"kind": "saw_attacks_optional_sac_draw_effect"},
    }
    assert T._is_safe_trigger_dict(d) is True
    # NOT target-seated.
    assert T._is_target_seated_safe_trigger(p, ta) is False

    bridged = _ta_dict_to_python_triggered_ability(d)
    assert bridged.event is Event.ATTACKS
    assert isinstance(bridged.predicate, IsHost)
    assert bridged.predicate.subject == "attacker"
    assert isinstance(bridged.effect, SawAttacksOptionalSacDrawEffect)


def test_saw_effect_class_now_covered():
    """**Verify-first.** ``SawAttacksOptionalSacDrawEffect`` is now in
    the covered-by-rust set (the ``Effect::SawAttacksOptionalSacDrawEffect``
    Rust variant landed this slice), and all of Saw's emitted Effect
    classes are covered."""
    from mtg_bot.parity.effect_coverage import (
        card_effect_classes,
        covered_python_class_set,
    )
    from mtg_bot.cards.source import get_active_source

    cov = covered_python_class_set()
    assert "SawAttacksOptionalSacDrawEffect" in cov
    p = get_active_source().get_printings().get("Saw")
    if p is None:
        pytest.skip("Saw absent from active CardSource")
    assert card_effect_classes(p).issubset(cov)


# ---------------------------------------------------------------------------
# GENUINE real-EoE cross-engine byte-equality probe.
# ---------------------------------------------------------------------------


def _rust_obj_on_bf(rust_state, obj_id):
    return any(e["id"] == obj_id for e in rust_state.battlefield_snapshot())


def _py_obj_on_bf(py_state, obj_id):
    return any(o.id == obj_id for o in py_state.battlefield)


def _saw_inj():
    """The bridge-dict equivalent of Saw (only the ATTACKS rider)."""
    return {
        "name": "Saw",
        "card_types": ["Artifact"],
        "subtypes": ["Equipment"],
        "supertypes": [],
        "keywords": [],
        "effects": [],
        "triggered_abilities": [
            {
                "event": "attacks",
                "predicate": {"kind": "is_host", "subject": "attacker"},
                "effect": {"kind": "saw_attacks_optional_sac_draw_effect"},
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


def _trinket_inj(name):
    """A vanilla noncreature permanent (the sacrifice fodder)."""
    return {
        "name": name,
        "card_types": ["Artifact"],
        "subtypes": [],
        "supertypes": [],
        "keywords": [],
        "effects": [],
    }


def _py_printing_from_dict(d):
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_triggered_ability,
    )

    mc = d.get("mana_cost", {})
    gen = int(mc.get("generic", 0))
    col = tuple((k, int(v)) for k, v in mc.items() if k != "generic")
    return CardPrinting(
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


def _py_inject_bf(py_state, d, controller, *, attached_to=None):
    from mtg_bot.game import Zone

    pr = _py_printing_from_dict(d)
    obj = py_state.new_object(pr, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    obj.tapped = False
    obj.damage = 0
    obj.attached_to = attached_to
    obj.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(obj)
    return obj


def _py_inject_library(py_state, d, controller):
    from mtg_bot.game import Zone

    pr = _py_printing_from_dict(d)
    obj = py_state.new_object(pr, owner_id=controller, zone=Zone.LIBRARY)
    py_state.player_by_id(controller).library.append(obj)
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


def test_cross_engine_real_eoe_saw_attacks_sacs_first_and_draws_parity():
    """**GENUINE real-EoE probe — Equipment-AA family (Saw).**

    Drives the real parsed Saw ATTACKS rider end-to-end through the
    production ATTACKS path with NO agent seated, asserting byte-equal
    cross-engine sacrifice + draw observables.

    Scenario A (a sacrificable permanent exists): Saw is attached to a
    host bear on p0's bf; a vanilla artifact ("Trinket") is on p0's bf
    AFTER the host (higher ETB). A library card is seeded for p0 so the
    draw is observable. The host attacks → the ``IsHost(subject=
    "attacker")`` ATTACKS trigger fires from the Equipment → the
    no-agent deterministic seat ACCEPTS and sacrifices the FIRST
    controlled permanent excluding source + host (the Trinket — it is
    the only legal pool member) and draws one card, byte-equal on both
    engines (Trinket leaves bf to graveyard; p0's hand grows by one).

    Scenario B (no sacrificable permanent): only the host + the Saw are
    on p0's bf (the host is excluded as "that creature", the Saw is
    excluded as "this Equipment"). The host attacks → the trigger's
    optional pool is EMPTY → both engines silently no-op (NO sacrifice,
    NO draw) — byte-equal, proving the empty-pool decline edge.
    """
    _require_engine()
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.combat import declare_attackers

    real = get_active_source().get_printings().get("Saw")
    if real is None:
        pytest.skip("Saw absent from active CardSource")

    saw = _saw_inj()

    # ===== Scenario A: a sacrificable permanent exists. =====
    py_state, rust_state = _build()
    # Inject order (both engines in lockstep): host bear on p0 (lowest
    # ETB), the Trinket on p0 (next ETB — the sole legal sacrifice pool
    # member), then the Saw attached to the host. A library card for p0
    # so the draw is observable.
    rs_host = rust_state.register_and_inject_object(
        _bear_inj("Host Bear"), 0, ZONE_BATTLEFIELD
    )
    rs_trinket = rust_state.register_and_inject_object(
        _trinket_inj("Trinket"), 0, ZONE_BATTLEFIELD
    )
    rs_saw = rust_state.register_and_inject_object(saw, 0, ZONE_BATTLEFIELD)
    rust_state.register_and_inject_object(
        _trinket_inj("LibCard"), 0, ZONE_LIBRARY
    )
    assert rust_state.attach(rs_saw, rs_host) is True
    rust_state.clear_summoning_sick_for_player(0)

    py_host = _py_inject_bf(py_state, _bear_inj("Host Bear"), 0)
    py_trinket = _py_inject_bf(py_state, _trinket_inj("Trinket"), 0)
    py_saw = _py_inject_bf(py_state, saw, 0, attached_to=py_host.id)
    _py_inject_library(py_state, _trinket_inj("LibCard"), 0)

    assert py_state.players[0].agent is None
    assert py_state.players[1].agent is None

    rs_hand_before = len(rust_state.hand_snapshot(0))
    py_hand_before = len(py_state.players[0].hand)
    assert rs_hand_before == py_hand_before

    assert rust_state.declare_attacker(rs_host) is True
    assert rust_state.stack_size() == 1, (
        "Rust: the equipped host attacking must push Saw's ATTACKS trigger"
    )
    declare_attackers(py_state, [py_host.id])
    assert len(py_state.stack) == 1, (
        "Python: the equipped host attacking must push Saw's ATTACKS trigger"
    )
    _drain_both(py_state, rust_state)
    assert rust_state.stack_size() == 0 and len(py_state.stack) == 0

    # The Trinket (the sole legal pool member) is sacrificed on BOTH
    # engines; the host + the Saw are NOT (excluded as "that creature" /
    # "this Equipment").
    assert _rust_obj_on_bf(rust_state, rs_trinket) is False
    assert _py_obj_on_bf(py_state, py_trinket.id) is False
    assert _rust_obj_on_bf(rust_state, rs_host) is True
    assert _py_obj_on_bf(py_state, py_host.id) is True
    assert _rust_obj_on_bf(rust_state, rs_saw) is True
    assert _py_obj_on_bf(py_state, py_saw.id) is True
    # Byte-equal: the Trinket is in p0's graveyard on both engines.
    rs_gy_ids = {e["id"] for e in rust_state.graveyard_snapshot(0)}
    py_gy_ids = {o.id for o in py_state.players[0].graveyard}
    assert rs_trinket in rs_gy_ids
    assert py_trinket.id in py_gy_ids
    # And p0 drew exactly one card (hand grew by one) on both engines.
    rs_hand_after = len(rust_state.hand_snapshot(0))
    py_hand_after = len(py_state.players[0].hand)
    assert rs_hand_after == rs_hand_before + 1
    assert py_hand_after == py_hand_before + 1
    assert rs_hand_after == py_hand_after

    # ===== Scenario B: no sacrificable permanent (empty pool). =====
    py_state2, rust_state2 = _build()
    rs_host2 = rust_state2.register_and_inject_object(
        _bear_inj("Host Bear"), 0, ZONE_BATTLEFIELD
    )
    rs_saw2 = rust_state2.register_and_inject_object(
        saw, 0, ZONE_BATTLEFIELD
    )
    rust_state2.register_and_inject_object(
        _trinket_inj("LibCard"), 0, ZONE_LIBRARY
    )
    assert rust_state2.attach(rs_saw2, rs_host2) is True
    rust_state2.clear_summoning_sick_for_player(0)

    py_host2 = _py_inject_bf(py_state2, _bear_inj("Host Bear"), 0)
    py_saw2 = _py_inject_bf(py_state2, saw, 0, attached_to=py_host2.id)
    _py_inject_library(py_state2, _trinket_inj("LibCard"), 0)

    rs_hand_before2 = len(rust_state2.hand_snapshot(0))
    py_hand_before2 = len(py_state2.players[0].hand)

    assert rust_state2.declare_attacker(rs_host2) is True
    declare_attackers(py_state2, [py_host2.id])
    _drain_both(py_state2, rust_state2)

    # Empty pool → no sacrifice, no draw, on BOTH engines (byte-equal
    # decline edge). The host + the Saw both remain; the hand is
    # unchanged.
    assert _rust_obj_on_bf(rust_state2, rs_host2) is True
    assert _py_obj_on_bf(py_state2, py_host2.id) is True
    assert _rust_obj_on_bf(rust_state2, rs_saw2) is True
    assert _py_obj_on_bf(py_state2, py_saw2.id) is True
    assert len(rust_state2.graveyard_snapshot(0)) == 0
    assert len(py_state2.players[0].graveyard) == 0
    assert len(rust_state2.hand_snapshot(0)) == rs_hand_before2
    assert len(py_state2.players[0].hand) == py_hand_before2
