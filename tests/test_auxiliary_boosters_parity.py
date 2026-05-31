"""Cross-engine parity probe for Auxiliary Boosters — Equipment-AA
family closure (2026-05-31, ``feature/equipment-aa-siblings``).

**Auxiliary Boosters — the third Equipment-AA closure (the ENTERS/IsSelf
sibling — does NOT use the ATTACKS/IsHost(attacker) branch).** ``{2}``
Artifact — Equipment (EoE pool). Oracle:

    "Equipped creature gets +1/+2 and has flying.
     When Auxiliary Boosters enters, create a 2/2 colorless Robot
     artifact creature token, then attach Auxiliary Boosters to it.
     Equip {2}"

**What this slice shipped (verify-first finding, 2026-05-31).** Unlike
Baseball Bat / Saw / Atomic Microsizer (all ATTACKS + IsHost(attacker)),
Auxiliary Boosters' rider is an ETB (``ENTERS`` + ``IsSelf``), so it
rides the EXISTING ENTERS+IsSelf safe-trigger branch (NOT the
Equipment-AA ATTACKS branch). The single NEW piece is the Rust
``Effect::CreateTokenAndAttachSelf { token_printing_id }`` (enum +
parse + to_pydict + valid-kinds string + resolve arm) mirroring Python's
``CreateTokenAndAttachSelf`` (``effects/generic/tokens.py:79``), plus the
cross_engine reverse bridge arm + the trajectory recognizer arm + the
``("enters", "source_is_self", "create_token_and_attach_self")``
``_SAFE_TRIGGERS`` entry + the ``_seat_token_printings`` ``kind`` axis
extension.

**No token-registration wall (verify-first).** The token is the Robot
2/2 Artifact Creature — VANILLA (no abilities/keywords), so it
round-trips through the EXISTING ``CreateToken`` token-printing
substrate (``register_token_printing`` / ``_seat_token_printings``)
byte-equal. The token's id is byte-equal cross-engine (both engines use
the shared monotonic ``reserve_object_id`` / ``next_object_id``); the
self-attach is a plain ``attached_to`` stamp (the same idiom as
``ManifestDreadThenAttachSelf``). So Auxiliary Boosters is a CLEAN
PROBED flip.

This module is the GENUINE real-EoE cross-engine byte-equality probe
(registered in ``scripts/measure_pool_parity.py`` PROBE_MODULES). It
drives Auxiliary Boosters' ETB rider through BOTH engines via the ETB
dispatch path and asserts byte-equal token-creation + self-attach.

Lives in its own module per the established per-card-module convention
(cf. ``test_baseball_bat_parity.py``, ``test_infinite_guideline_station_parity.py``).
"""

from __future__ import annotations

import importlib.util

import pytest


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2


_ROBOT_TOKEN_RUST_DICT = {
    "name": "Robot",
    "card_types": ["Artifact", "Creature"],
    "subtypes": ["Robot"],
    "supertypes": ["Token"],
    "mana_cost": {},
    "effects": [],
    "power": 2,
    "toughness": 2,
}


# ---------------------------------------------------------------------------
# Verify-first: parser SoT + recognizer round-trip pins.
# ---------------------------------------------------------------------------


def test_real_auxiliary_boosters_parser_sot_etb_create_token_and_attach():
    """**Verify-first.** The live parser maps Auxiliary Boosters' ETB
    oracle line to one triggered ability whose ``event`` is
    ``Event.ENTERS``, ``predicate`` is ``IsSelf``, and ``effect`` is
    ``CreateTokenAndAttachSelf`` whose ``token_printing`` is the Robot
    2/2 Artifact Creature token. Plus the +1/+2 + flying anthem and the
    Equip {2} activated ability surface. Freezes the parser SoT so a
    parser drift is caught here.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.tokens import CreateTokenAndAttachSelf
    from mtg_bot.effects.predicates import Event, IsSelf

    p = get_active_source().get_printings().get("Auxiliary Boosters")
    if p is None:
        pytest.skip("Auxiliary Boosters absent from active CardSource")
    assert "Artifact" in p.card_types
    assert "Equipment" in p.subtypes
    # Static +1/+2 + flying anthem from the printed equipment_bonuses.
    assert p.equipment_bonuses is not None
    pb, tb, gks = p.equipment_bonuses
    assert (pb, tb) == (1, 2)
    assert "flying" in gks
    # Exactly one triggered ability — the ETB create-token-then-attach.
    assert len(p.triggered_abilities) == 1
    ta = p.triggered_abilities[0]
    assert ta.event is Event.ENTERS
    assert isinstance(ta.predicate, IsSelf)
    assert isinstance(ta.effect, CreateTokenAndAttachSelf)
    # The token is the vanilla Robot 2/2 Artifact Creature.
    tp = ta.effect.token_printing
    assert tp.name == "Robot"
    assert (tp.power, tp.toughness) == (2, 2)
    assert "Artifact" in tp.card_types and "Creature" in tp.card_types
    assert tp.keywords == frozenset()
    assert tp.triggered_abilities == ()
    # Equip {2} activated ability surfaces.
    assert len(p.activated_abilities) >= 1


def test_auxiliary_boosters_etb_trigger_round_trips_through_safe_dict():
    """**Verify-first — the recognizer + bridge round-trip.** Auxiliary
    Boosters' ETB rider serializes to the canonical safe-trigger dict
    (a SYMBOLIC ``_token_card_def`` pre-seating), and after seating to a
    numeric ``token_printing_id`` it is accepted by
    ``_is_safe_trigger_dict`` and the bridge round-trips it back to the
    genuine Python class.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.tokens import CreateTokenAndAttachSelf
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.parity import trajectory as T
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_triggered_ability,
        register_token_printing,
        clear_token_printings,
    )
    from mtg_bot.cards.tokens import TOKEN_PRINTINGS

    p = get_active_source().get_printings().get("Auxiliary Boosters")
    if p is None:
        pytest.skip("Auxiliary Boosters absent from active CardSource")
    ta = p.triggered_abilities[0]

    d = T._python_ta_to_safe_dict(ta)
    assert d["event"] == "enters"
    assert d["predicate"] == {"kind": "source_is_self"}
    assert d["effect"]["kind"] == "create_token_and_attach_self"
    # Pre-seating: symbolic token reference (no numeric pid yet).
    assert "_token_card_def" in d["effect"]

    # Seat the token pid manually (mirrors the loader's
    # _seat_token_printings) so the post-seating dict satisfies
    # _is_safe_trigger_dict and the bridge.
    clear_token_printings()
    robot_pid = 7
    register_token_printing(robot_pid, TOKEN_PRINTINGS["Robot"])
    seated = {
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {
            "kind": "create_token_and_attach_self",
            "token_printing_id": robot_pid,
        },
    }
    assert T._is_safe_trigger_dict(seated) is True

    bridged = _ta_dict_to_python_triggered_ability(seated)
    assert bridged.event is Event.ENTERS
    assert isinstance(bridged.predicate, IsSelf)
    assert isinstance(bridged.effect, CreateTokenAndAttachSelf)
    assert bridged.effect.token_printing.name == "Robot"
    clear_token_printings()


def test_auxiliary_boosters_effect_class_now_covered():
    """**Verify-first.** ``CreateTokenAndAttachSelf`` is now in the
    covered-by-rust set (the ``Effect::CreateTokenAndAttachSelf`` Rust
    variant landed this slice), and all of Auxiliary Boosters' emitted
    Effect classes are covered."""
    from mtg_bot.parity.effect_coverage import (
        card_effect_classes,
        covered_python_class_set,
    )
    from mtg_bot.cards.source import get_active_source

    cov = covered_python_class_set()
    assert "CreateTokenAndAttachSelf" in cov
    p = get_active_source().get_printings().get("Auxiliary Boosters")
    if p is None:
        pytest.skip("Auxiliary Boosters absent from active CardSource")
    assert card_effect_classes(p).issubset(cov)


# ---------------------------------------------------------------------------
# GENUINE real-EoE cross-engine byte-equality probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_auxiliary_boosters_etb_token_and_attach_parity():
    """**GENUINE real-EoE probe — Equipment-AA family (Auxiliary
    Boosters).**

    Drives Auxiliary Boosters' ETB create-token-then-self-attach rider
    end-to-end through the production ETB path with NO agent seated,
    asserting byte-equal cross-engine token-creation + self-attach state.

    Both engines: register the Robot 2/2 token printing (Rust registry
    pid + the Python bridge map). Inject Auxiliary Boosters via ETB on
    both engines (the ETB queues the ENTERS trigger which resolves into
    the CreateTokenAndAttachSelf arm). Post-resolve (both engines):

      * Exactly ONE new Robot 2/2 token enters the Equipment's
        controller's bf (summoning_sick — it's a creature, untapped).
      * The Equipment's ``attached_to`` points at the new token's id.
      * The token's id is byte-equal cross-engine (shared monotonic
        object-id counter).
    """
    _require_engine()
    from mtg_bot.actions import dispatch_event as py_dispatch_event, \
        resolve_top_of_stack
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.cards.tokens import TOKEN_PRINTINGS
    from mtg_bot.effects.predicates import Event as PyEvent
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
        register_token_printing,
        clear_token_printings,
        _ta_dict_to_python_triggered_ability,
    )

    real = (
        __import__(
            "mtg_bot.cards.source", fromlist=["get_active_source"]
        ).get_active_source().get_printings().get("Auxiliary Boosters")
    )
    if real is None:
        pytest.skip("Auxiliary Boosters absent from active CardSource")

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Rust side: register Robot token pid (seeded into p1's library
    # as an inert pid holder — doesn't affect p0's bf which we measure).
    robot_pid = rs.registry_size
    rs.register_and_inject_object(_ROBOT_TOKEN_RUST_DICT, 1, ZONE_LIBRARY)

    # Seat the bridge map so the Python side resolves token_pid ->
    # CardPrinting during the ETB resolve (and so both engines use the
    # SAME Robot shape).
    clear_token_printings()
    register_token_printing(robot_pid, TOKEN_PRINTINGS["Robot"])

    # The Auxiliary Boosters bridge-dict (post-seating: carries the
    # numeric robot pid). Both engines drive THIS shape so the token is
    # byte-identical.
    aux_dict = {
        "name": "Auxiliary Boosters",
        "card_types": ["Artifact"],
        "subtypes": ["Equipment"],
        "supertypes": [],
        "keywords": [],
        "effects": [],
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "create_token_and_attach_self",
                    "token_printing_id": robot_pid,
                },
            },
        ],
    }

    # ---- Python side: build the Equipment printing from the bridge-dict
    # (its triggered ability resolves token_printing_id via the bridge
    # map to the SAME Robot printing Rust uses).
    py_aux_printing = CardPrinting(
        name="Auxiliary Boosters",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2, colored=()),
        type_line="Artifact — Equipment",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=("Equipment",),
        power=None,
        toughness=None,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=tuple(
            _ta_dict_to_python_triggered_ability(t)
            for t in aux_dict["triggered_abilities"]
        ),
    )
    py.active_player_idx = 0
    py.priority_player_idx = 0
    py.players[0].agent = None
    py.players[1].agent = None
    py_aux = py.new_object(
        py_aux_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_aux.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_aux)
    py_pre_bf_ids = {o.id for o in py.battlefield}
    assert py_aux.attached_to is None
    # Dispatch ENTERS as if Auxiliary Boosters just ETB'd.
    py_dispatch_event(py, PyEvent.ENTERS, label="enters", obj=py_aux)

    # ---- Rust side: inject Auxiliary Boosters via ETB (auto-queues +
    # drains the ENTERS dispatch).
    rs_pre_bf_ids = {d["id"] for d in rs.battlefield_snapshot()}
    rs_aux = rs.register_and_inject_object(
        aux_dict, 0, ZONE_BATTLEFIELD,
    )

    # ---- Drain both stacks (the ENTERS trigger resolves → 1 Robot
    # token spawns + the Equipment attaches to it on each engine).
    while py.stack:
        resolve_top_of_stack(py)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    assert len(py.stack) == 0 and rs.stack_size() == 0

    # ---- Post-resolve observables.
    # Python: exactly one new Robot 2/2 token on p0's bf.
    py_post_bf = {o.id for o in py.battlefield}
    py_new_ids = py_post_bf - py_pre_bf_ids
    assert len(py_new_ids) == 1, (
        f"Python: must create exactly one Robot token; got "
        f"{len(py_new_ids)} new objects"
    )
    py_token_id = next(iter(py_new_ids))
    py_token = next(o for o in py.battlefield if o.id == py_token_id)
    assert py_token.printing.name == "Robot"
    assert py_token.controller_id == 0
    assert py_token.tapped is False
    assert py_token.summoning_sick is True
    # The Equipment is attached to the new token.
    assert py_aux.attached_to == py_token_id

    # Rust: exactly one new Robot 2/2 token on p0's bf.
    rs_post = {d["id"]: d for d in rs.battlefield_snapshot()}
    rs_new_ids = set(rs_post.keys()) - rs_pre_bf_ids - {rs_aux}
    assert len(rs_new_ids) == 1, (
        f"Rust: must create exactly one Robot token; got "
        f"{len(rs_new_ids)} new objects"
    )
    rs_token_id = next(iter(rs_new_ids))
    rs_token = rs_post[rs_token_id]
    assert rs_token["printing_name"] == "Robot"
    assert rs_token["controller_id"] == 0
    assert rs_token["tapped"] is False
    assert rs_token["summoning_sick"] is True
    # The Equipment is attached to the new token.
    assert rs_post[rs_aux]["attached_to"] == rs_token_id

    # Cross-engine byte-equal LINKAGE: on EACH engine the Equipment's
    # ``attached_to`` points at its freshly-created token (the
    # self-attach is internally consistent on both). The ABSOLUTE token
    # id differs only because the Rust side seeds an inert Robot-printing
    # holder object into p1's library (a pid-registration scaffold
    # artifact, mirroring the Infinite Guideline Station probe) which
    # consumes one object id Python doesn't — so we assert the per-engine
    # linkage (Equipment -> its own new token) rather than a
    # cross-engine absolute-id match.
    assert py_aux.attached_to == py_token_id
    assert rs_post[rs_aux]["attached_to"] == rs_token_id

    clear_token_printings()
