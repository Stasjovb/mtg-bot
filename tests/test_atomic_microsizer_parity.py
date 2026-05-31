"""Cross-engine parity probe for Atomic Microsizer — Equipment-AA family
closure (2026-05-31, `feature/equipment-aa-siblings`).

**Atomic Microsizer — the fourth Equipment-AA closure (sibling of
Baseball Bat / Saw / Auxiliary Boosters).** ``{U}`` Artifact —
Equipment (EoE pool, ~14 17lands decks). Oracle:

    "Equipped creature gets +1/+0.
     Whenever equipped creature attacks, choose up to one target
     creature. That creature can't be blocked this turn and has base
     power and toughness 1/1 until end of turn.
     Equip {2}"

**HONEST-STOP -> PROBED flip (2026-05-31).** The earlier
``feature/atomic-microsizer-cycle-1-p1`` slice landed this module as an
HONEST-STOP pin: the Python side was fully wired but no Rust
``Effect::AtomicMicrosizerAttackEffect`` existed, so the card stayed in
``blocked_subsystem_gated``. This slice lands the substrate and flips
the honest-stop pins into positive cross-engine probes:

  * Rust ``Effect::AtomicMicrosizerAttackEffect`` (enum variant + parse
    + to_pydict + valid-kinds string + ``first_legal_trigger_target``
    seat arm + compound-UEOT resolve arm). Rides the SHARED Tier-C
    push-time first-legal seat (same as Baseball Bat's
    ``TapUpToOneTargetCreature`` — bare ``IsCreature()`` filter,
    count_min=0 optional, target on EITHER bf).
  * cross_engine reverse bridge arm ``atomic_microsizer_attack_effect``.
  * The trajectory recognizer arm (the THIRD ``is_host_attacker``
    targeted-safe leaf) + the ``("attacks", "is_host_attacker",
    "atomic_microsizer_attack_effect")`` ``_SAFE_TRIGGERS`` entry +
    ``_SAFE_EFFECT_KEYS`` + ``_TARGET_SEATED_EFFECT_KINDS``.

**Compound-UEOT representation choice (verify-first, documented in
``docs/SEARCH_LIMITATIONS.md``).** The effect applies TWO continuous
effects to the seated target: "can't be blocked" + "base P/T 1/1
UEOT". Python writes a layer-6 ``cant_be_blocked`` registry entry
(``GrantUnblockable``) + a ``BecomeType(base_pt=(1,1))`` layer-7b
override; Rust pushes a UEOT ``GrantKeyword "unblockable"`` +
``SetBasePT 1/1``. The observables are EQUIVALENT:
``game.is_cant_be_blocked`` (Py) == ``has_keyword(id,"unblockable")``
(Rust) — both "this creature can't be blocked" — and
``effective_power``/``effective_toughness`` == (1,1) on both. The probe
compares these semantically-equal observables.

This module is the GENUINE real-EoE cross-engine byte-equality probe
(registered in ``scripts/measure_pool_parity.py`` PROBE_MODULES).

Lives in its own module per the established per-card-module convention
(cf. ``test_baseball_bat_parity.py``, ``test_saw_parity.py``).
"""

from __future__ import annotations

import importlib.util

import pytest


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


ZONE_BATTLEFIELD = 2


# ---------------------------------------------------------------------------
# Verify-first: parser SoT + recognizer round-trip pins.
# ---------------------------------------------------------------------------


def test_real_atomic_microsizer_parser_sot_attack_trigger_with_microsizer_effect():
    """**Verify-first.** The live parser maps Atomic Microsizer's
    equipped-creature-attacks oracle line to one triggered ability
    whose ``event`` is ``Event.ATTACKS``, ``predicate`` is
    ``IsHost(subject="attacker")``, and ``effect`` is
    ``AtomicMicrosizerAttackEffect()`` — a parameterless frozen
    dataclass. Freezes the parser SoT so a parser drift is caught
    here, not silently downstream."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import AtomicMicrosizerAttackEffect
    from mtg_bot.effects.predicates import Event, IsHost

    p = get_active_source().get_printings().get("Atomic Microsizer")
    if p is None:
        pytest.skip("Atomic Microsizer absent from active CardSource")
    assert "Artifact" in p.card_types
    assert "Equipment" in p.subtypes
    # Static +1/+0 anthem from the printed equipment_bonuses tuple.
    assert p.equipment_bonuses is not None
    pb, tb, gks = p.equipment_bonuses
    assert (pb, tb) == (1, 0)
    assert gks == frozenset()
    # Exactly one triggered ability — the equipped-creature-attacks
    # trigger. Oracle text has no ETB auto-attach line.
    assert len(p.triggered_abilities) == 1
    ta = p.triggered_abilities[0]
    assert ta.event == Event.ATTACKS
    assert isinstance(ta.predicate, IsHost)
    assert ta.predicate.subject == "attacker"
    assert isinstance(ta.effect, AtomicMicrosizerAttackEffect)
    # Up-to-one optional target (count_min=0) — the §2 gate the
    # recognizer enforces.
    assert ta.effect.requires_target() is True
    assert ta.effect.target_count_range() == (0, 1)
    assert ta.effect.target_slot_kinds() == ()
    # Equip {2} activated ability surfaces as a single activated
    # ability entry on the printing.
    assert len(p.activated_abilities) >= 1


def test_atomic_microsizer_effect_target_count_is_up_to_one_creature():
    """**Verify-first.** ``AtomicMicrosizerAttackEffect.target_count_range
    `` is ``(0, 1)`` (choose up to one), ``requires_target`` is True,
    and ``legal_targets`` returns ALL battlefield creatures (not just
    controller-owned) — the bare-IsCreature cross-bf pool the SHARED
    Tier-C seat picks the first-legal from."""
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.effects.bespoke import AtomicMicrosizerAttackEffect
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.agents import RandomAgent

    e = AtomicMicrosizerAttackEffect()
    assert e.requires_target()
    assert e.target_count_range() == (0, 1)
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    p0_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(p0_bear)
    p1_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(p1_bear)
    legal = e.legal_targets(state, controller_id=0)
    legal_ids = {tid for (_kind, tid) in legal}
    assert p0_bear.id in legal_ids and p1_bear.id in legal_ids, (
        "AtomicMicrosizerAttackEffect.legal_targets must return creatures "
        "on BOTH players' battlefields — the bare-IsCreature cross-bf pool"
    )


def test_atomic_microsizer_attack_trigger_round_trips_through_safe_dict():
    """**Verify-first (FLIPPED from honest-stop).** Atomic Microsizer's
    ATTACKS rider now serializes to the canonical safe-trigger dict, is
    accepted by ``_is_safe_trigger_dict``, is a target-seated trigger,
    and the bridge round-trips it back to the genuine Python class."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import AtomicMicrosizerAttackEffect
    from mtg_bot.effects.predicates import Event, IsHost
    from mtg_bot.parity import trajectory as T
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_triggered_ability,
    )

    p = get_active_source().get_printings().get("Atomic Microsizer")
    if p is None:
        pytest.skip("Atomic Microsizer absent from active CardSource")
    [ta] = list(p.triggered_abilities)

    d = T._python_ta_to_safe_dict(ta)
    assert d == {
        "event": "attacks",
        "predicate": {"kind": "is_host", "subject": "attacker"},
        "effect": {"kind": "atomic_microsizer_attack_effect"},
    }
    assert T._is_safe_trigger_dict(d) is True
    assert T._is_target_seated_safe_trigger(p, ta) is True

    bridged = _ta_dict_to_python_triggered_ability(d)
    assert bridged.event is Event.ATTACKS
    assert isinstance(bridged.predicate, IsHost)
    assert bridged.predicate.subject == "attacker"
    assert isinstance(bridged.effect, AtomicMicrosizerAttackEffect)


def test_atomic_microsizer_effect_class_now_covered():
    """**Verify-first (FLIPPED from honest-stop).**
    ``AtomicMicrosizerAttackEffect`` is now in the covered-by-rust set
    (the ``Effect::AtomicMicrosizerAttackEffect`` Rust variant landed
    this slice), and all of Atomic Microsizer's emitted Effect classes
    are covered."""
    from mtg_bot.parity.effect_coverage import (
        card_effect_classes,
        covered_python_class_set,
    )
    from mtg_bot.cards.source import get_active_source

    cov = covered_python_class_set()
    assert "AtomicMicrosizerAttackEffect" in cov
    p = get_active_source().get_printings().get("Atomic Microsizer")
    if p is None:
        pytest.skip("Atomic Microsizer absent from active CardSource")
    assert card_effect_classes(p).issubset(cov)


# ---------------------------------------------------------------------------
# GENUINE real-EoE cross-engine byte-equality probe.
# ---------------------------------------------------------------------------


def _saw_microsizer_inj():
    """The bridge-dict equivalent of Atomic Microsizer (only the ATTACKS
    rider — the Equip {2} AA is a §2-decline that doesn't gate the
    trigger admit)."""
    return {
        "name": "Atomic Microsizer",
        "card_types": ["Artifact"],
        "subtypes": ["Equipment"],
        "supertypes": [],
        "keywords": [],
        "effects": [],
        "triggered_abilities": [
            {
                "event": "attacks",
                "predicate": {"kind": "is_host", "subject": "attacker"},
                "effect": {"kind": "atomic_microsizer_attack_effect"},
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


def _py_inject_bf(py_state, d, controller, *, attached_to=None):
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


def _py_obj(py_state, obj_id):
    return next((o for o in py_state.battlefield if o.id == obj_id), None)


def test_cross_engine_real_eoe_atomic_microsizer_attack_trigger_parity():
    """**GENUINE real-EoE probe — Equipment-AA family (Atomic
    Microsizer).**

    Drives the real parsed Atomic Microsizer ATTACKS rider end-to-end
    through the production ATTACKS path with NO agent seated, asserting
    byte-equal cross-engine compound-UEOT state (can't-be-blocked +
    base-P/T-1/1) on the seated target.

    Scenario A2 (opponent creature seated FIRST → it is the seat):
    inject an opponent bear FIRST (smallest ETB), then the host bear,
    then the Atomic Microsizer attached to the host. The host attacks →
    the ``IsHost(subject="attacker")`` ATTACKS trigger fires → the
    SHARED deterministic push-time seat picks the FIRST creature
    (smallest-ETB on EITHER bf = the OPPONENT bear) and applies the
    compound UEOT to EXACTLY it, byte-equal on both engines (proving the
    cross-bf seat). The host (the attacker) is unchanged by the rider.
    """
    _require_engine()
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.combat import declare_attackers
    from mtg_bot.game import is_cant_be_blocked, effective_power, \
        effective_toughness

    real = get_active_source().get_printings().get("Atomic Microsizer")
    if real is None:
        pytest.skip("Atomic Microsizer absent from active CardSource")

    equip = _saw_microsizer_inj()

    py_state, rust_state = _build()
    # Inject the OPPONENT bear FIRST (smallest ETB → the seat), then the
    # host bear, then the Equipment attached to the host. The opponent
    # bear is the first-legal cross-bf seat — proving the rider hits an
    # UNTAPPED opponent creature, NOT a controller-only walk.
    rs_opp = rust_state.register_and_inject_object(
        _bear_inj("Opp Bear"), 1, ZONE_BATTLEFIELD
    )
    rs_host = rust_state.register_and_inject_object(
        _bear_inj("Host Bear"), 0, ZONE_BATTLEFIELD
    )
    rs_equip = rust_state.register_and_inject_object(
        equip, 0, ZONE_BATTLEFIELD
    )
    assert rust_state.attach(rs_equip, rs_host) is True
    rust_state.clear_summoning_sick_for_player(0)

    py_opp = _py_inject_bf(py_state, _bear_inj("Opp Bear"), 1)
    py_host = _py_inject_bf(py_state, _bear_inj("Host Bear"), 0)
    py_equip = _py_inject_bf(py_state, equip, 0, attached_to=py_host.id)

    assert py_state.players[0].agent is None
    assert py_state.players[1].agent is None

    assert rust_state.declare_attacker(rs_host) is True
    assert rust_state.stack_size() == 1, (
        "Rust: the equipped host attacking must push the Atomic "
        "Microsizer ATTACKS trigger (a legal creature target exists)"
    )
    declare_attackers(py_state, [py_host.id])
    assert len(py_state.stack) == 1, (
        "Python: the equipped host attacking must push the Atomic "
        "Microsizer ATTACKS trigger"
    )
    _drain_both(py_state, rust_state)
    assert rust_state.stack_size() == 0 and len(py_state.stack) == 0

    # The OPPONENT bear (smallest ETB → the seat) is the target.
    # Compound UEOT observables, byte-equal cross-engine:
    #   * can't-be-blocked: Python is_cant_be_blocked == Rust
    #     has_keyword("unblockable") (the equivalent representation).
    #   * base P/T 1/1: effective_power/toughness == (1,1) on both.
    assert rust_state.has_keyword(rs_opp, "unblockable") is True
    assert is_cant_be_blocked(py_state, _py_obj(py_state, py_opp.id)) is True
    assert rust_state.effective_power(rs_opp) == 1
    assert rust_state.effective_toughness(rs_opp) == 1
    assert effective_power(py_state, _py_obj(py_state, py_opp.id)) == 1
    assert effective_toughness(py_state, _py_obj(py_state, py_opp.id)) == 1
    # Cross-engine byte-equal on the meaning of each observable.
    assert (
        rust_state.has_keyword(rs_opp, "unblockable")
        == is_cant_be_blocked(py_state, _py_obj(py_state, py_opp.id))
        is True
    )
    assert (
        rust_state.effective_power(rs_opp)
        == effective_power(py_state, _py_obj(py_state, py_opp.id))
        == 1
    )
    assert (
        rust_state.effective_toughness(rs_opp)
        == effective_toughness(py_state, _py_obj(py_state, py_opp.id))
        == 1
    )

    # The host (the attacker) is NOT affected by the rider (the seat
    # picked the smaller-ETB opponent bear). Its base P/T is its printed
    # 2/2 (the +1/+0 equipment anthem is not modeled on these synthetic
    # bridge-dict equips — both engines see the same un-anthemed body,
    # so the host's effective P/T is byte-equal at the printed 2/2).
    assert rust_state.has_keyword(rs_host, "unblockable") is False
    assert is_cant_be_blocked(py_state, _py_obj(py_state, py_host.id)) is False
    assert (
        rust_state.effective_power(rs_host)
        == effective_power(py_state, _py_obj(py_state, py_host.id))
        == 2
    )
    assert (
        rust_state.effective_toughness(rs_host)
        == effective_toughness(py_state, _py_obj(py_state, py_host.id))
        == 2
    )


def test_cross_engine_real_eoe_atomic_microsizer_no_creature_optional_declines():
    """**GENUINE real-EoE probe — the count_min=0 optional decline edge.**

    With only the host on the battlefield (it IS a creature, so it is
    the first-legal seat), the host attacks → the rider picks the host
    itself and applies the compound UEOT to it. With NO creature at all
    (host removed), the optional declines and nothing changes. Here we
    pin the FIRST shape (host is the only creature → it is the seat):
    after attacking, the host is unblockable + base P/T 1/1, byte-equal
    on both engines — proving the seat picks the host when it is the
    only legal creature (the count_min=0 optional resolves to the host,
    NOT a fizzle-skip)."""
    _require_engine()
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.combat import declare_attackers
    from mtg_bot.game import is_cant_be_blocked, effective_power, \
        effective_toughness

    real = get_active_source().get_printings().get("Atomic Microsizer")
    if real is None:
        pytest.skip("Atomic Microsizer absent from active CardSource")

    equip = _saw_microsizer_inj()
    py_state, rust_state = _build()
    rs_host = rust_state.register_and_inject_object(
        _bear_inj("Host Bear"), 0, ZONE_BATTLEFIELD
    )
    rs_equip = rust_state.register_and_inject_object(
        equip, 0, ZONE_BATTLEFIELD
    )
    assert rust_state.attach(rs_equip, rs_host) is True
    rust_state.clear_summoning_sick_for_player(0)

    py_host = _py_inject_bf(py_state, _bear_inj("Host Bear"), 0)
    py_equip = _py_inject_bf(py_state, equip, 0, attached_to=py_host.id)

    assert rust_state.declare_attacker(rs_host) is True
    declare_attackers(py_state, [py_host.id])
    _drain_both(py_state, rust_state)

    # The host is the only creature → it is the first-legal seat → it
    # gets the compound UEOT (byte-equal observables on both engines).
    assert (
        rust_state.has_keyword(rs_host, "unblockable")
        == is_cant_be_blocked(py_state, _py_obj(py_state, py_host.id))
        is True
    )
    assert (
        rust_state.effective_power(rs_host)
        == effective_power(py_state, _py_obj(py_state, py_host.id))
        == 1
    )
    assert (
        rust_state.effective_toughness(rs_host)
        == effective_toughness(py_state, _py_obj(py_state, py_host.id))
        == 1
    )
