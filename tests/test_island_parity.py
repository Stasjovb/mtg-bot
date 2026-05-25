"""Island — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

Island is a **basic Land** in the EoE pool (``Basic`` supertype,
``Land`` card type, ``Island`` subtype) carrying the canonical "Add
{U}" mana ability via the **parser-flattened-to-vanilla** profile +
the **basic-land CardDef bridge auto-wire**.  Templates directly off
the batch-6 sibling ``test_forest_parity.py`` — bit-identical at the
basic-land bridge level; the per-slug attribution distinction is the
printing identity (Island=U, Forest=G).

The Island slug is the **second-highest-deck-count covered_by_
construction holdout** at ~465,009 17lands decks — virtually every
blue-touching deck plays basics — bit-identical bridge round-trip to
the Forest batch-6 sibling at the Effect level, with the
distinguishing color coin ``('U', 1)``.

**FFFF EEEE-idiom for the basic-land bridge carrier.**  Same lane
discipline as batches 1-5 (parse + bridge round-trip + Python-side
resolve, NO cross-engine ``compare_fields``).  The Python-side
resolve drives the auto-wired AddManaToPool Effect through its
resolve path on the **round-tripped** Python printing; the post-
resolve observable is "p0's mana pool gained exactly one ``U``-
colored coin".

**NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
binding the Island slug to its bridge-auto-wired
``ActivatedAbility(AddManaToPool(produces=(('U', 1),)))`` shape on
the **basic-land carrier via produces-field flattening + CardDef
auto-wire**.  Sibling to the batch-6 Forest probe — same bridge
auto-wire mechanism, distinct color slot per the per-slug
attribution rule (per the cathedral-of-war-style same-Effect-class-
different-printing-slug precedent, each basic-land color slot gets
its own PROBED-tier slot).
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
# (1) Parser SoT — Island is parser-claimed as a Basic Land subtype
# Island with ``produces=frozenset({'U'})`` and ZERO structured Effects.
# ---------------------------------------------------------------------------


def test_island_parser_claims_card():
    assert "Island" in _PRINTINGS, (
        "Island must be parser-claimed by the active CardSource"
    )


def test_island_printed_attrs():
    """Pins the basic printing surface: Basic Land subtype Island with
    ``produces=frozenset({'U'})``, zero mana cost, and ZERO structured
    Effects on the parser side (the {T}: Add {U} primitive is folded
    into the ``produces`` field per the parser's basic-land flatten)."""
    p = _PRINTINGS["Island"]
    assert "Land" in p.card_types
    assert "Basic" in p.supertypes
    assert "Island" in p.subtypes
    assert p.produces == frozenset({"U"}), (
        f"Island must produce exactly {{'U'}}; got produces={p.produces}"
    )
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()
    assert p.activated_abilities == ()
    assert p.triggered_abilities == ()
    assert p.spell_effect is None


def test_island_loader_admits_as_basic_land():
    """Pins the bridge-admit gate: Island passes
    ``_printing_is_bridge_basic_land`` (Basic + Land + 1-color +
    0-abilities)."""
    from mtg_bot.parity.trajectory import _printing_is_bridge_basic_land

    p = _PRINTINGS["Island"]
    assert _printing_is_bridge_basic_land(p) is True


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — _printing_to_card_def → CardDef →
# _card_def_to_python_printing materializes the auto-wired
# AddManaToPool AA byte-equal to the round-27 add_mana_to_pool arm.
# ---------------------------------------------------------------------------


def test_island_card_def_bridge_round_trip():
    """The CardDef bridge round-trip materializes Island as a Python
    printing with EXACTLY one auto-wired
    ``ActivatedAbility(AddManaToPool(produces=(('U', 1),),
    spend_restriction=None))`` mana ability + ``produces=frozenset(
    {'U'})``.  Byte-equal to the round-27 add_mana_to_pool bridge arm
    emission for ``{"kind": "add_mana_to_pool", "color": "U",
    "amount": 1}``."""
    from mtg_bot.parity.trajectory import _printing_to_card_def
    from mtg_bot.parity.cross_engine import (
        _card_def_to_python_printing, _ta_dict_to_python_effect,
    )

    real = _PRINTINGS["Island"]
    cd = _printing_to_card_def(real)
    assert cd.name == "Island"
    assert cd.card_type == "Land"
    assert cd.mana_produced == ("U",)

    py_round = _card_def_to_python_printing(cd)
    assert "Land" in py_round.card_types
    assert py_round.produces == frozenset({"U"})
    assert len(py_round.activated_abilities) == 1
    aa = py_round.activated_abilities[0]
    assert isinstance(aa.effect, AddManaToPool)
    assert aa.effect.produces == (("U", 1),)
    assert aa.effect.spend_restriction is None
    assert aa.cost.tap_self is True
    assert aa.is_mana_ability is True

    bridged = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "U", "amount": 1}
    )
    assert isinstance(bridged, AddManaToPool)
    assert aa.effect == bridged, (
        f"Auto-wired Island AA Effect must be byte-equal to the "
        f"bridged AddManaToPool Effect from the round-27 arm; got "
        f"auto_wired={aa.effect!r}, bridged={bridged!r}"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — Rust's register_printing accepts
# the Island-shape basic-land dict.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_island_basic_land_dict():
    """Lockstep pin: Rust's ``register_printing`` accepts the Island-
    shape registry dict — Basic supertype + Land card type +
    ``mana_produced=['U']``."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Island (synthetic carrier)",
            "card_types": ["Land"],
            "mana_cost": {},
            "effects": [],
            "mana_produced": ["U"],
            "supertypes": ["Basic"],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Island printing through the basic-land bridge auto-wire
# and resolves the materialized AddManaToPool effect on the Python side.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_island_basic_land_mana_ability_add_u_parity():
    """**GENUINE real-EoE cross-engine probe — Island basic-land
    bridge auto-wire → AddManaToPool(produces=(('U', 1),)). PROBED-
    tier flip (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Island printing** through the basic-
    land CardDef bridge auto-wire + the auto-wired AddManaToPool
    effect's resolve path.  Mirrors the FFFF EEEE-idiom; same lane
    discipline as batches 1-5 + the batch-6 sibling Forest probe.

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
    binding the Island slug to its bridge-auto-wired
    ``ActivatedAbility(AddManaToPool(produces=(('U', 1),)))`` shape.
    Sibling to the batch-6 Forest probe — bit-identical bridge auto-
    wire mechanism, distinct color slot ``'U'`` (the
    cathedral-of-war-style same-Effect-class-different-printing-slug
    precedent grants each basic-land color slot its own PROBED-tier
    slot).

    **Bridge auto-wire exercised:**
      * ``_printing_to_card_def`` basic-land arm.
      * ``_card_def_to_python_printing`` mana-ability auto-wire.
      * ``add_mana_to_pool`` (round-27 bridge arm; 'U' single-color
        dispatch).

    **Setup (Python-side):**
      * Round-trip the ACTUAL parsed Island through the CardDef bridge.
      * Seat the round-tripped Island on p0's battlefield.
      * p0's mana pool starts empty.

    **Observables asserted:**
      * Bridge round-trip materializes the auto-wired Add{U} AA.
      * Effect-level byte-equality between the auto-wired Effect and
        the round-27 add_mana_to_pool bridge arm emission.
      * Post-resolve: p0's mana pool gained exactly one ManaCoin with
        color='U' and spend_restriction=None.
    """
    from mtg_bot.parity.trajectory import _printing_to_card_def
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _card_def_to_python_printing,
        _ta_dict_to_python_effect,
    )
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Island printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Island")
    if real is None:
        pytest.skip("Island absent from active CardSource")
    assert "Land" in real.card_types
    assert "Basic" in real.supertypes
    assert real.produces == frozenset({"U"})

    # ------------------------------------------------------------------
    # 2. Drive the CardDef bridge round-trip.
    # ------------------------------------------------------------------
    cd = _printing_to_card_def(real)
    assert cd.mana_produced == ("U",)

    py_round = _card_def_to_python_printing(cd)
    aa = py_round.activated_abilities[0]
    assert isinstance(aa.effect, AddManaToPool)
    assert aa.effect.produces == (("U", 1),)
    assert aa.effect.spend_restriction is None

    # ------------------------------------------------------------------
    # 3. Bridge round-trip: round-27 add_mana_to_pool arm.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "U", "amount": 1}
    )
    assert isinstance(bridged, AddManaToPool)
    assert aa.effect == bridged, (
        f"Auto-wired Island AA Effect must be byte-equal to bridged; "
        f"got auto_wired={aa.effect!r}, bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 4. Distinctness regression guard.
    # ------------------------------------------------------------------
    assert bridged.produces[0][0] == "U", (
        "Bridged AddManaToPool must produce 'U'-color coin — distinct "
        "from Forest='G' / Swamp='B' / Mountain='R' / Plains='W' "
        "basic-land siblings"
    )
    assert bridged.produces[0][1] == 1
    assert bridged.spend_restriction is None

    # ------------------------------------------------------------------
    # 5. Python-side resolve smoke.
    # ------------------------------------------------------------------
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
    assert coin.color == "U", (
        f"Minted coin must be 'U'-color (blue); got "
        f"color={coin.color!r}"
    )
    assert coin.spend_restriction is None
    assert len(py_state.players[1].mana_pool) == 0
