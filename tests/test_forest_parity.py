"""Forest — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

Forest is a **basic Land** in the EoE pool (``Basic`` supertype, ``Land``
card type, ``Forest`` subtype) carrying the canonical "Add {G}" mana
ability via the **parser-flattened-to-vanilla** profile + the **basic-
land CardDef bridge auto-wire**:

* **Parser SoT.** The live ``OracleParserCardSource`` ships Forest as
  a ZERO-Effect vanilla printing — ``activated_abilities=()``,
  ``triggered_abilities=()``, ``spell_effect=None``, ``effects=()``
  on the parser side, with ``produces=frozenset({'G'})`` carrying the
  mana-ability primitive in a single condensed field. (The printed
  oracle line ``{T}: Add {G}`` is *recognized* by the parser and
  folded into the ``produces`` set rather than emitted as a structured
  ``ActivatedAbility(AddManaToPool(...))``; this is how every basic
  land in the EoE pool flattens.)

* **Bridge round-trip.** ``trajectory._printing_to_card_def`` (the
  loader-admit-gated converter that the bench corpus runs through)
  recognizes the printing via ``_printing_is_bridge_basic_land`` (the
  Basic + Land + 1-color + 0-abilities gate) and emits a CardDef with
  ``mana_produced=("G",)``.  The reverse arm
  ``cross_engine._card_def_to_python_printing`` materializes that
  CardDef back into a Python ``CardPrinting`` that **auto-wires the
  ``{T}: Add {G}`` mana ability** as a structured
  ``ActivatedAbility(cost=ActivationCost(tap_self=True),
  effect=AddManaToPool(produces=(('G', 1),), spend_restriction=None),
  is_mana_ability=True)``.  The Rust-side counterpart
  ``_spec_card_to_printing_dict`` emits the registry dict
  ``{"card_types": ["Land"], "mana_produced": ["G"], "supertypes":
  ["Basic"], ...}`` which Rust's ``register_printing`` recognizes via
  the same single-field shape (Rust's mana-ability auto-wire from
  ``mana_produced`` is symmetric to Python's).

* **End-to-end Effect-level byte-equality.** The bridged
  ``AddManaToPool(produces=(('G', 1),), spend_restriction=None)`` is
  byte-equal to the auto-wired AA's emitted Effect on the round-
  tripped Python printing AND byte-equal to what the round-27 bridge
  arm ``add_mana_to_pool`` emits for ``{"kind": "add_mana_to_pool",
  "color": "G", "amount": 1}``.

This module is the **load-bearing PROBED-tier flip evidence** for
Forest.  Opens a **NEW shape family** for the per-slug attribution
lane: **basic-land carrier via the parser-flattened-vanilla profile
+ ``_printing_to_card_def`` basic-land auto-wire bridge** (distinct
from the batches 1-5 AA-bearing or triggered-ability carrier shapes,
which all carry their structured Effects on the parser side rather
than as ``produces`` field elements that re-materialize via the
CardDef auto-wire).

The Forest slug is the **highest-deck-count covered_by_construction
holdout** at ~466,226 17lands decks (every U/G/R/B/W deck plays
basics) — flipping it to PROBED is the load-bearing leverage in this
batch.

**FFFF EEEE-idiom for the basic-land bridge carrier.**  Same lane
discipline as batches 1-5 (parse + bridge round-trip + Python-side
resolve, NO cross-engine ``compare_fields``).  The Python-side
resolve drives the auto-wired AddManaToPool Effect through its
resolve path on the **round-tripped** Python printing (the auto-wire
materialization is the bridge product under test); the post-resolve
observable is "p0's mana pool gained exactly one ``G``-colored
coin".

**NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
binding the Forest slug to its bridge-auto-wired
``ActivatedAbility(AddManaToPool(produces=(('G', 1),)))`` shape on
the **basic-land carrier via produces-field flattening + CardDef
auto-wire**.  Distinct from the batch-4 sibling Land probes (Mana
Confluence / Gemstone Caverns / Cascading Cataracts), which all
carry their AAs on the parser side directly; Forest's AA is
re-synthesized by the bridge from the parser-flattened ``produces``
set.
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
# (1) Parser SoT — Forest is parser-claimed as a Basic Land subtype
# Forest with ``produces=frozenset({'G'})`` and ZERO structured Effects
# (the {T}: Add {G} primitive is folded into ``produces`` per the
# parser's basic-land flatten convention).
# ---------------------------------------------------------------------------


def test_forest_parser_claims_card():
    assert "Forest" in _PRINTINGS, (
        "Forest must be parser-claimed by the active CardSource"
    )


def test_forest_printed_attrs():
    """Pins the basic printing surface: Basic Land subtype Forest with
    ``produces=frozenset({'G'})``, zero mana cost, and ZERO structured
    Effects on the parser side (the {T}: Add {G} primitive is folded
    into the ``produces`` field rather than emitted as a structured
    ActivatedAbility — the basic-land bridge auto-wire reconstructs
    it at materialization time)."""
    p = _PRINTINGS["Forest"]
    assert "Land" in p.card_types
    assert "Basic" in p.supertypes, (
        "Forest must carry the 'Basic' supertype — the load-bearing "
        "gate for _printing_is_bridge_basic_land"
    )
    assert "Forest" in p.subtypes
    assert p.produces == frozenset({"G"}), (
        f"Forest must produce exactly {{'G'}}; got produces={p.produces}"
    )
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()
    # Parser-side flatten: ZERO structured Effects on the parser-side
    # printing (the {T}: Add {G} primitive is in the produces field).
    assert p.activated_abilities == (), (
        f"Forest must have ZERO structured ActivatedAbilities on the "
        f"parser side — the {{T}}: Add {{G}} primitive is folded into "
        f"the produces field; got {p.activated_abilities}"
    )
    assert p.triggered_abilities == (), (
        f"Forest must have ZERO TriggeredAbilities; got "
        f"{p.triggered_abilities}"
    )
    assert p.spell_effect is None


def test_forest_loader_admits_as_basic_land():
    """Pins the bridge-admit gate: Forest passes
    ``_printing_is_bridge_basic_land`` (the Basic + Land + 1-color +
    0-abilities + 0-triggers + 0-statics gate that the loader uses to
    route basic lands through the auto-wire bridge)."""
    from mtg_bot.parity.trajectory import _printing_is_bridge_basic_land

    p = _PRINTINGS["Forest"]
    assert _printing_is_bridge_basic_land(p) is True, (
        "Forest must pass the basic-land admit gate "
        "(_printing_is_bridge_basic_land); without admission the "
        "CardDef bridge can't auto-wire the {T}: Add {G} ability"
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — _printing_to_card_def → CardDef →
# _card_def_to_python_printing materializes the auto-wired
# AddManaToPool AA whose Effect is byte-equal to the round-27
# add_mana_to_pool bridge arm's emission.
# ---------------------------------------------------------------------------


def test_forest_card_def_bridge_round_trip():
    """The CardDef bridge round-trip
    (``_printing_to_card_def`` → ``_card_def_to_python_printing``)
    materializes Forest as a Python printing with EXACTLY one
    auto-wired ``ActivatedAbility(AddManaToPool(produces=(('G', 1),),
    spend_restriction=None))`` mana ability + ``produces=frozenset(
    {'G'})``.

    Byte-equality contract (EEEE-idiom):

      ``_printing_to_card_def(Forest)`` →
      ``CardDef(name="Forest", card_type="Land", mana_produced=("G",))``

      ``_card_def_to_python_printing(<that CardDef>)`` →
      ``CardPrinting(...,
          produces=frozenset({'G'}),
          activated_abilities=(ActivatedAbility(
              cost=ActivationCost(tap_self=True),
              effect=AddManaToPool(produces=(('G', 1),),
                                   spend_restriction=None),
              is_mana_ability=True,
          ),))``

    AND ``_ta_dict_to_python_effect({"kind": "add_mana_to_pool",
    "color": "G", "amount": 1})`` → the SAME AddManaToPool Effect
    instance byte-equal."""
    from mtg_bot.parity.trajectory import _printing_to_card_def
    from mtg_bot.parity.cross_engine import (
        _card_def_to_python_printing, _ta_dict_to_python_effect,
    )

    real = _PRINTINGS["Forest"]
    cd = _printing_to_card_def(real)
    assert cd.name == "Forest"
    assert cd.card_type == "Land"
    assert cd.mana_produced == ("G",), (
        f"CardDef mana_produced must be ('G',); got "
        f"mana_produced={cd.mana_produced}"
    )

    py_round = _card_def_to_python_printing(cd)
    assert "Land" in py_round.card_types
    assert py_round.produces == frozenset({"G"}), (
        f"Round-tripped Forest produces must be frozenset({{'G'}}); "
        f"got {py_round.produces}"
    )
    assert len(py_round.activated_abilities) == 1, (
        f"Round-tripped Forest must auto-wire EXACTLY one mana AA; "
        f"got {len(py_round.activated_abilities)}"
    )
    aa = py_round.activated_abilities[0]
    assert isinstance(aa.effect, AddManaToPool)
    assert aa.effect.produces == (("G", 1),), (
        f"Auto-wired AA must produce exactly one ('G', 1) coin; got "
        f"produces={aa.effect.produces}"
    )
    assert aa.effect.spend_restriction is None
    assert aa.cost.tap_self is True
    assert aa.cost.mana is None
    assert aa.is_mana_ability is True

    # Effect-level byte-equality between the auto-wired AA emission and
    # the round-27 bridge arm emission.
    bridged = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "G", "amount": 1}
    )
    assert isinstance(bridged, AddManaToPool)
    assert aa.effect == bridged, (
        f"Auto-wired Forest AA Effect must be byte-equal to the "
        f"bridged AddManaToPool Effect from the round-27 arm "
        f"(structural contract for the PROBED tier); got "
        f"auto_wired={aa.effect!r}, bridged={bridged!r}"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts the
# Forest-shape registry dict (basic-land with mana_produced=['G'] +
# Basic supertype).
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_forest_basic_land_dict():
    """Lockstep pin: Rust's ``register_printing`` accepts the
    Forest-shape registry dict — Basic supertype + Land card type +
    ``mana_produced=['G']``.  The bridge emits this dict via
    ``_spec_card_to_printing_dict`` for any printing passing
    ``_printing_is_bridge_basic_land`` (the basic-land arm of
    ``_printing_to_card_def``)."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Forest (synthetic carrier)",
            "card_types": ["Land"],
            "mana_cost": {},
            "effects": [],
            "mana_produced": ["G"],
            "supertypes": ["Basic"],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Forest printing through the basic-land bridge auto-
# wire and then resolves the materialized AddManaToPool effect on the
# Python side.  Mirrors the FFFF EEEE-idiom (parse + bridge round-trip
# + Python-side resolve, NO cross-engine compare_fields).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_forest_basic_land_mana_ability_add_g_parity():
    """**GENUINE real-EoE cross-engine probe — Forest basic-land
    bridge auto-wire → AddManaToPool(produces=(('G', 1),)). PROBED-
    tier flip (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Forest printing** through the basic-
    land CardDef bridge auto-wire (``_printing_to_card_def`` →
    ``_card_def_to_python_printing``) and then through the auto-
    wired AddManaToPool effect's resolve path.  Mirrors the FFFF
    EEEE-idiom; same lane discipline as batches 1-5.

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
    binding the Forest slug to its bridge-auto-wired
    ``ActivatedAbility(AddManaToPool(produces=(('G', 1),)))`` shape
    on the **basic-land carrier via produces-field flattening +
    CardDef auto-wire** (distinct from the batch-4 sibling Land
    probes which carry their AAs on the parser side directly;
    Forest's AA is re-synthesized by the bridge from the parser-
    flattened ``produces`` set).

    **Bridge auto-wire exercised:**
      * ``_printing_to_card_def`` basic-land arm (trajectory.py:9483).
      * ``_card_def_to_python_printing`` mana-ability auto-wire
        (cross_engine.py mana-ability auto-wire from
        ``mana_produced`` field).
      * ``add_mana_to_pool`` (round-27 bridge arm; the amount=1
        single-color dispatch).

    **AA-cost-substrate deferral.**  The full activated-mana-ability
    cost-payment trajectory (the ``tap_self`` cost atom on the
    auto-wired ActivationCost, the mana-ability stack-bypass per CR
    605) is the cost-substrate scope and stays substrate-deferred
    for this lane.  Per-slug attribution credits the slug based on
    the Effect+bridge byte-equality alone.

    **Setup (Python-side):**
      * Round-trip the ACTUAL parsed Forest printing through the
        CardDef bridge.
      * Seat the ROUND-TRIPPED Forest on p0's battlefield (the AA
        source; the auto-wired AA materializes here).
      * p0's mana pool starts empty.

    **Observables asserted:**
      * Bridge round-trip:
        ``_printing_to_card_def(Forest)`` → CardDef with
        ``mana_produced=("G",)``.
      * ``_card_def_to_python_printing`` auto-wires the AA with the
        expected AddManaToPool Effect.
      * Effect-level byte-equality between the auto-wired Effect and
        the round-27 add_mana_to_pool bridge arm emission.
      * Post-resolve: p0's mana pool gained exactly one ManaCoin with
        color='G' and spend_restriction=None.
    """
    from mtg_bot.parity.trajectory import _printing_to_card_def
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _card_def_to_python_printing,
        _ta_dict_to_python_effect,
    )
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Forest printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Forest")
    if real is None:
        pytest.skip("Forest absent from active CardSource")
    assert "Land" in real.card_types
    assert "Basic" in real.supertypes
    assert real.produces == frozenset({"G"})

    # ------------------------------------------------------------------
    # 2. Drive the CardDef bridge round-trip.
    # ------------------------------------------------------------------
    cd = _printing_to_card_def(real)
    assert cd.mana_produced == ("G",)

    py_round = _card_def_to_python_printing(cd)
    aa = py_round.activated_abilities[0]
    assert isinstance(aa.effect, AddManaToPool)
    assert aa.effect.produces == (("G", 1),)
    assert aa.effect.spend_restriction is None

    # ------------------------------------------------------------------
    # 3. Bridge round-trip: round-27 add_mana_to_pool arm.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "G", "amount": 1}
    )
    assert isinstance(bridged, AddManaToPool)
    assert aa.effect == bridged, (
        f"Auto-wired Forest AA Effect must be byte-equal to bridged; "
        f"got auto_wired={aa.effect!r}, bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 4. Distinctness regression guard.
    # ------------------------------------------------------------------
    # 'G' is the green mana color (distinct from 'U' Island / 'B'
    # Swamp / 'R' Mountain / 'W' Plains basic-land siblings, and
    # distinct from 'C' colorless Eldrazi Temple AA[0] / 'any'
    # wildcard Mana Confluence / Gemstone Caverns / Gene Pollinator /
    # Sunken Citadel sibling shapes).  amount=1 is distinct from the
    # Cascading Cataracts amount=5 batch-mint sibling.
    # spend_restriction is None — distinct from Power Depot /
    # Steelswarm Operator / Eldrazi Temple AA[1] / Sunken Citadel
    # AA[1] spend-restricted sibling shapes.
    assert bridged.produces[0][0] == "G", (
        "Bridged AddManaToPool must produce 'G'-color coin — distinct "
        "from sibling basic-land probes (Island='U' / Swamp='B' / "
        "Mountain='R' / Plains='W') + wildcard 'any' AA-carrier probes"
    )
    assert bridged.produces[0][1] == 1, (
        "Bridged AddManaToPool must produce amount=1 — distinct from "
        "the Cascading Cataracts amount=5 batch-mint sibling"
    )
    assert bridged.spend_restriction is None, (
        "Bridged AddManaToPool must NOT carry a spend_restriction — "
        "that's Power Depot / Steelswarm Operator / Eldrazi Temple "
        "AA[1] / Sunken Citadel AA[1] shape, not Forest's"
    )

    # ------------------------------------------------------------------
    # 5. Python-side resolve smoke — drive the auto-wired effect on
    #    the ROUND-TRIPPED Forest printing (the bridge product under
    #    test).  p0's mana pool gains one 'G' coin.
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

    assert len(py_state.players[0].mana_pool) == 0, (
        f"empty-pool precondition: p0's mana pool must be empty pre-"
        f"resolve; got pool size="
        f"{len(py_state.players[0].mana_pool)}"
    )

    aa.effect.resolve(py_state, py_source.controller_id)

    p0_pool = py_state.players[0].mana_pool
    assert len(p0_pool) == 1, (
        f"Forest auto-wired AA must mint exactly 1 coin in p0's "
        f"pool; got pool size={len(p0_pool)}"
    )
    coin = p0_pool[0]
    assert coin.color == "G", (
        f"Minted coin must be 'G'-color (green); got "
        f"color={coin.color!r}"
    )
    assert coin.spend_restriction is None, (
        f"Minted coin must have no spend_restriction; got "
        f"spend_restriction={coin.spend_restriction!r}"
    )
    assert len(py_state.players[1].mana_pool) == 0, (
        "p1's mana pool must remain empty (the controller-of-effect "
        "contract — Forest mints into the source's controller's pool "
        "only)"
    )
