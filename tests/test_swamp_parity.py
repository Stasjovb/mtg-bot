"""Swamp — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

Swamp is a **basic Land** in the EoE pool (``Basic`` supertype,
``Land`` card type, ``Swamp`` subtype) carrying the canonical "Add
{B}" mana ability via the **parser-flattened-to-vanilla** profile +
the **basic-land CardDef bridge auto-wire**.  Templates directly off
the batch-6 sibling ``test_forest_parity.py`` /
``test_island_parity.py`` — bit-identical at the basic-land bridge
level; the per-slug attribution distinction is the printing identity
(Swamp=B).

~434,410 17lands decks (every black-touching deck plays basics) —
load-bearing leverage in this batch.

**FFFF EEEE-idiom for the basic-land bridge carrier.**  Same lane
discipline as batches 1-5 (parse + bridge round-trip + Python-side
resolve, NO cross-engine ``compare_fields``).
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.mana import AddManaToPool


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Zone constants (mirror Rust's u8 zone IDs).
ZONE_BATTLEFIELD = 2


# ---------------------------------------------------------------------------
# (1) Parser SoT — Swamp is parser-claimed as a Basic Land subtype
# Swamp with ``produces=frozenset({'B'})`` and ZERO structured Effects.
# ---------------------------------------------------------------------------


def test_swamp_parser_claims_card():
    assert "Swamp" in _PRINTINGS, (
        "Swamp must be parser-claimed by the active CardSource"
    )


def test_swamp_printed_attrs():
    """Pins the basic printing surface: Basic Land subtype Swamp with
    ``produces=frozenset({'B'})``."""
    p = _PRINTINGS["Swamp"]
    assert "Land" in p.card_types
    assert "Basic" in p.supertypes
    assert "Swamp" in p.subtypes
    assert p.produces == frozenset({"B"})
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()
    assert p.activated_abilities == ()
    assert p.triggered_abilities == ()
    assert p.spell_effect is None


def test_swamp_loader_admits_as_basic_land():
    """Pins the bridge-admit gate."""
    from mtg_bot.parity.trajectory import _printing_is_bridge_basic_land

    p = _PRINTINGS["Swamp"]
    assert _printing_is_bridge_basic_land(p) is True


# ---------------------------------------------------------------------------
# (2) Bridge round-trip.
# ---------------------------------------------------------------------------


def test_swamp_card_def_bridge_round_trip():
    """The CardDef bridge round-trip materializes Swamp as a Python
    printing with the auto-wired ``ActivatedAbility(AddManaToPool(
    produces=(('B', 1),), spend_restriction=None))`` mana ability."""
    from mtg_bot.parity.trajectory import _printing_to_card_def
    from mtg_bot.parity.cross_engine import (
        _card_def_to_python_printing, _ta_dict_to_python_effect,
    )

    real = _PRINTINGS["Swamp"]
    cd = _printing_to_card_def(real)
    assert cd.name == "Swamp"
    assert cd.card_type == "Land"
    assert cd.mana_produced == ("B",)

    py_round = _card_def_to_python_printing(cd)
    assert py_round.produces == frozenset({"B"})
    assert len(py_round.activated_abilities) == 1
    aa = py_round.activated_abilities[0]
    assert isinstance(aa.effect, AddManaToPool)
    assert aa.effect.produces == (("B", 1),)
    assert aa.effect.spend_restriction is None
    assert aa.cost.tap_self is True
    assert aa.is_mana_ability is True

    bridged = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "B", "amount": 1}
    )
    assert isinstance(bridged, AddManaToPool)
    assert aa.effect == bridged


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_swamp_basic_land_dict():
    """Lockstep pin: Rust's ``register_printing`` accepts the Swamp-
    shape basic-land registry dict."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Swamp (synthetic carrier)",
            "card_types": ["Land"],
            "mana_cost": {},
            "effects": [],
            "mana_produced": ["B"],
            "supertypes": ["Basic"],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_swamp_basic_land_mana_ability_add_b_parity():
    """**GENUINE real-EoE cross-engine probe — Swamp basic-land bridge
    auto-wire → AddManaToPool(produces=(('B', 1),)). PROBED-tier
    flip (covered_by_construction → PROBED).**

    Sibling to the batch-6 Forest / Island probes — bit-identical
    bridge auto-wire mechanism, distinct color slot ``'B'``.  Per the
    cathedral-of-war-style same-Effect-class-different-printing-slug
    precedent, each basic-land color slot gets its own PROBED-tier
    slot.

    **Bridge auto-wire exercised:**
      * ``_printing_to_card_def`` basic-land arm.
      * ``_card_def_to_python_printing`` mana-ability auto-wire.
      * ``add_mana_to_pool`` (round-27 bridge arm; 'B' single-color
        dispatch).
    """
    from mtg_bot.parity.trajectory import _printing_to_card_def
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _card_def_to_python_printing,
        _ta_dict_to_python_effect,
    )
    from mtg_bot.game import Zone

    real = _PRINTINGS.get("Swamp")
    if real is None:
        pytest.skip("Swamp absent from active CardSource")
    assert "Land" in real.card_types
    assert "Basic" in real.supertypes
    assert real.produces == frozenset({"B"})

    cd = _printing_to_card_def(real)
    assert cd.mana_produced == ("B",)

    py_round = _card_def_to_python_printing(cd)
    aa = py_round.activated_abilities[0]
    assert isinstance(aa.effect, AddManaToPool)
    assert aa.effect.produces == (("B", 1),)
    assert aa.effect.spend_restriction is None

    bridged = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "B", "amount": 1}
    )
    assert isinstance(bridged, AddManaToPool)
    assert aa.effect == bridged

    # Distinctness regression guard.
    assert bridged.produces[0][0] == "B", (
        "Bridged AddManaToPool must produce 'B'-color coin — distinct "
        "from Forest='G' / Island='U' / Mountain='R' / Plains='W' "
        "basic-land siblings"
    )
    assert bridged.produces[0][1] == 1
    assert bridged.spend_restriction is None

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    py_source = py_state.new_object(
        py_round, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    assert len(py_state.players[0].mana_pool) == 0

    aa.effect.resolve(py_state, py_source.controller_id)

    p0_pool = py_state.players[0].mana_pool
    assert len(p0_pool) == 1
    coin = p0_pool[0]
    assert coin.color == "B", (
        f"Minted coin must be 'B'-color (black); got "
        f"color={coin.color!r}"
    )
    assert coin.spend_restriction is None
    assert len(py_state.players[1].mana_pool) == 0
