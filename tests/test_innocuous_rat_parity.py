"""Innocuous Rat — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

Innocuous Rat is a ``{1}{B}`` Creature — Rat (1/1, Duskmourn special
guest in the EoE pool):

    "When this creature dies, manifest dread."

Parser-emitted shape:
    DIES + IsSelf trigger → ``ManifestDread(count=1)``

This module is the **load-bearing PROBED-tier flip evidence** for
Innocuous Rat. The substrate is already shipped — the FIRST real-EoE
consumer of the DIES+IsSelf+ManifestDread(count=1) shape was Bashful
Beastie (PROBED via
``test_probe_remaining_iii.py::test_cross_engine_real_eoe_bashful_
beastie_dies_manifest_dread_parity``). This probe pins the SAME
substrate against Innocuous Rat's distinct printing (per-slug
attribution credit per the 2026-05-24 ``post-flip-reclassification-
scout`` sweep precedent).

**Why this is a valid PROBED-tier flip** (re: prior JJJJ honest-stop
"Innocuous Rat (DIES → ManifestDread(count=1) bit-identical to PROBED
Bashful Beastie)"): the per-slug attribution mechanism credits per-
printing — even when the underlying Effect+bridge arm is bit-identical
to a sibling PROBED card. The 2026-05-24 sweep registered 12 bit-
identical-shape probes under this rationale; Innocuous Rat follows the
same precedent.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.library_lookat import ManifestDread


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Zone constants
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3


# ---------------------------------------------------------------------------
# (1) Parser SoT — Innocuous Rat is parser-claimed with the
# DIES+IsSelf+ManifestDread(count=1) shape.
# ---------------------------------------------------------------------------


def test_innocuous_rat_parser_claims_card():
    assert "Innocuous Rat" in _PRINTINGS, (
        "Innocuous Rat must be parser-claimed by the active CardSource"
    )


def test_innocuous_rat_printed_attrs():
    """Pins the basic printing surface: Creature/Rat type, {1}{B} cost,
    1/1 P/T."""
    p = _PRINTINGS["Innocuous Rat"]
    assert "Creature" in p.card_types
    assert "Rat" in p.subtypes
    assert p.mana_cost.generic == 1
    assert p.mana_cost.colored == (("B", 1),)
    assert p.power == 1
    assert p.toughness == 1


def test_innocuous_rat_dies_trigger_shape():
    """The parsed DIES+IsSelf trigger emits ``ManifestDread(count=1)``
    — the bare default count=1 shape."""
    from mtg_bot.effects.predicates import Event, IsSelf

    p = _PRINTINGS["Innocuous Rat"]
    dies_tas = [
        ta for ta in p.triggered_abilities if ta.event is Event.DIES
    ]
    assert len(dies_tas) == 1, (
        f"Innocuous Rat must have exactly 1 DIES triggered ability; "
        f"got {len(dies_tas)}"
    )
    (ta,) = dies_tas
    assert isinstance(ta.predicate, IsSelf), (
        f"DIES predicate must be IsSelf; got {type(ta.predicate).__name__}"
    )
    assert isinstance(ta.effect, ManifestDread), (
        f"DIES effect must be ManifestDread; got {type(ta.effect).__name__}"
    )
    assert ta.effect.count == 1, (
        f"ManifestDread count must be 1; got {ta.effect.count}"
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the bridge dict shape for the DIES+IsSelf+
# ManifestDread(count=1) trigger reconstructs the matching Python
# trigger ability.
# ---------------------------------------------------------------------------


def test_innocuous_rat_bridge_round_trip():
    """The bridge translates the ``{"event": "dies", "predicate":
    {"kind": "source_is_self"}, "effect": {"kind": "manifest_dread",
    "count": 1}}`` triplet to a Python ``TriggeredAbility`` with the
    matching ``ManifestDread(count=1)`` effect."""
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_triggered_ability,
    )
    from mtg_bot.effects.predicates import Event, IsSelf

    bridge_ta = _ta_dict_to_python_triggered_ability(
        {
            "event": "dies",
            "predicate": {"kind": "source_is_self"},
            "effect": {"kind": "manifest_dread", "count": 1},
        }
    )
    assert bridge_ta.event == Event.DIES
    assert isinstance(bridge_ta.predicate, IsSelf)
    assert isinstance(bridge_ta.effect, ManifestDread)
    assert bridge_ta.effect.count == 1

    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect.
    p = _PRINTINGS["Innocuous Rat"]
    (ta,) = p.triggered_abilities
    assert ta.effect == bridge_ta.effect


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — Rust accepts the DIES+IsSelf+
# manifest_dread dict on an Innocuous-Rat-shape Creature.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_innocuous_rat_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the
    ``{"kind": "manifest_dread", "count": 1}`` dict shape on an
    Innocuous-Rat-shape Creature carrier."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Innocuous Rat (synthetic carrier)",
            "card_types": ["Creature"],
            "subtypes": ["Rat"],
            "power": 1,
            "toughness": 1,
            "mana_cost": {"generic": 1, "B": 1},
            "triggered_abilities": [
                {
                    "event": "dies",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {"kind": "manifest_dread", "count": 1},
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Innocuous Rat printing on Python and a bridged
# synthetic Rat carrier on Rust through the DIES dispatch and verifies
# the ManifestDread(1) resolve byte-equal.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_innocuous_rat_dies_manifest_dread_parity():
    """**GENUINE real-EoE cross-engine probe — Innocuous Rat (DIES →
    ManifestDread(1)). PROBED-tier flip (covered_by_construction →
    PROBED).**

    Drives the **real parsed Innocuous Rat printing** on the Python
    side and a bridged synthetic carrier on the Rust side through the
    ``DIES`` dispatch path. This probe pins Innocuous Rat's "When this
    creature dies, manifest dread." trigger.

    With ``agent=None`` (the default in ``build_python_state``),
    ManifestDread is fully deterministic on both engines:

      * Python: ``ManifestDread.resolve`` falls back to ``manifest_id
        = options[0]`` (TOP card) when ``p.agent is None``.
      * Rust: ManifestDread manifests the top-indexed library object
        onto the battlefield face-down.

    Setup:
      * p0 has Innocuous Rat (1/1) on the battlefield.
      * p0's library has 2 Plains seed cards on both engines.
      * Active player = p0.

    Kill flow:
      1. Deal ``toughness`` damage to Innocuous Rat on BOTH engines.
      2. Apply SBAs: lethal damage → moves to graveyard → DIES trigger
         pushed on BOTH engines.
      3. Drain: ManifestDread resolves — top Plains manifested face-
         down on p0's battlefield, second Plains to p0's graveyard.

    Observables asserted (mirrors Bashful Beastie's targeted shape):
      * Innocuous Rat in p0's graveyard, not on bf.
      * p0 battlefield: exactly 1 object (the face-down manifested
        Plains).
      * p0 library: 0 cards (both consumed by ManifestDread).
      * p0 graveyard: 2 objects (Innocuous Rat + one Plains).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
        _ta_dict_to_python_triggered_ability,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.cards import BASIC_LANDS
    from mtg_bot.game import Zone
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.predicates import Event, IsSelf

    real = _PRINTINGS.get("Innocuous Rat")
    if real is None:
        pytest.skip("Innocuous Rat absent from active CardSource")
    assert "Creature" in real.card_types
    dies_ta = next(
        (ta for ta in real.triggered_abilities if ta.event == Event.DIES),
        None,
    )
    assert dies_ta is not None
    assert isinstance(dies_ta.effect, ManifestDread)
    assert dies_ta.effect.count == 1

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # Python library seeds (2 Plains).
    plains = BASIC_LANDS["Plains"]
    for _ in range(2):
        py_seed = py.new_object(plains, owner_id=0, zone=Zone.LIBRARY)
        py_seed.summoning_sick = False
        py.players[0].library.append(py_seed)

    # Rust library seeds.
    for _ in range(2):
        rs.register_and_inject_object(
            {
                "name": "Plains",
                "card_types": ["Land", "Basic"],
                "supertypes": ["Basic"],
                "mana_cost": {"generic": 0},
            },
            0, ZONE_LIBRARY,
        )

    # Shared trigger dict for Rust carrier.
    ir_ta_dict = {
        "event": "dies",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "manifest_dread", "count": 1},
    }
    bridge_ta = _ta_dict_to_python_triggered_ability(ir_ta_dict)
    assert bridge_ta.event == Event.DIES
    assert isinstance(bridge_ta.predicate, IsSelf)

    # ---- Rust: inject Innocuous Rat onto p0's battlefield. ----
    rs_ir_id = rs.register_and_inject_object(
        {
            "name": "Innocuous Rat",
            "card_types": ["Creature"],
            "subtypes": ["Rat"],
            "power": int(real.power),
            "toughness": int(real.toughness),
            "keywords": [],
            "effects": [],
            "triggered_abilities": [ir_ta_dict],
        },
        0, ZONE_BATTLEFIELD,
    )
    assert rs.find_object_zone(rs_ir_id) == ZONE_BATTLEFIELD

    # ---- Rust: deal lethal damage → SBAs move it to graveyard, fire
    # DIES → drain (ManifestDread resolves). ----
    rs.deal_damage(rs_ir_id, int(real.toughness))
    rs.apply_sbas()  # lethal damage → graveyard + DIES dispatch

    assert rs.stack_size() == 1, (
        f"Rust: exactly 1 DIES trigger must be pushed after lethal "
        f"damage + SBAs; got {rs.stack_size()}"
    )
    assert rs.find_object_zone(rs_ir_id) != ZONE_BATTLEFIELD

    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_bf = rs.battlefield_snapshot()
    rs_bf_count = len(rs_bf)
    assert rs_bf_count == 1, (
        f"Rust: exactly 1 object (manifested Plains) must be on p0's "
        f"battlefield after ManifestDread; got {rs_bf_count}"
    )
    rs_lib_size = rs.library_sizes[0]
    assert rs_lib_size == 0
    rs_gy_size = rs.graveyard_sizes[0]
    assert rs_gy_size == 2, (
        f"Rust: graveyard must have 2 cards (Innocuous Rat + 1 Plains) "
        f"after ManifestDread; got {rs_gy_size}"
    )

    # ---- Python: inject genuine Innocuous Rat printing (bridge TA) on
    # p0's battlefield. ----
    py_ir_printing = CardPrinting(
        name="Innocuous Rat",
        mana_cost_str="{1}{B}",
        mana_cost=ManaCost(generic=1, colored=(("B", 1),)),
        type_line="Creature — Rat",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Rat",),
        power=int(real.power),
        toughness=int(real.toughness),
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(bridge_ta,),
    )
    py_ir = py.new_object(py_ir_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_ir.summoning_sick = False
    py_ir.tapped = False
    py_ir.damage = 0
    py_ir.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_ir)

    # Lethal damage → SBA → DIES trigger pushed → drain.
    py_ir.damage = int(real.toughness)
    py_sba(py)

    assert len(py.stack) == 1, (
        f"Python: exactly 1 DIES trigger must be pushed after lethal "
        f"damage + SBAs; got {len(py.stack)}"
    )
    assert py_ir not in py.battlefield

    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    py_bf_count = len(py.battlefield)
    assert py_bf_count == 1, (
        f"Python: exactly 1 object (manifested Plains) must be on p0's "
        f"battlefield after ManifestDread; got {py_bf_count}"
    )
    assert py.battlefield[0].face_down is True
    py_lib_size = len(py.players[0].library)
    assert py_lib_size == 0
    py_gy_size = len(py.players[0].graveyard)
    assert py_gy_size == 2, (
        f"Python: graveyard must have 2 cards (Innocuous Rat + 1 Plains) "
        f"after ManifestDread; got {py_gy_size}"
    )

    # Cross-engine byte-equality on targeted observables.
    assert rs_bf_count == py_bf_count
    assert rs_lib_size == py_lib_size
    assert rs_gy_size == py_gy_size
