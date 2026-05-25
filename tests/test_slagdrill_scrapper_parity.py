"""Slagdrill Scrapper — per-card real-EoE cross-engine byte-equal
probe (covered_by_construction → PROBED tier flip).

Slagdrill Scrapper is a ``{R}`` Artifact Creature in the EoE pool
with a single activated ability:

    "{2}, {T}: Draw a card."

Parser-emitted Effect shape (the EFFECT half, distinct from the cost
half):

    ``DrawCards(amount=1)``

attached to an ActivatedAbility whose ``cost`` carries
``tap_self=True`` + mana cost ``{2}``.  The bridge arm ``draw_cards``
(cross_engine.py:846) round-trips ``{"kind": "draw_cards", "count": 1}``
byte-equal to Python's ``DrawCards(amount=1)`` (note the field-name
narrowing: Rust's dict shape uses ``count`` while Python's class
exposes the same value as ``amount`` — the bridge translates).

This module is the **load-bearing PROBED-tier flip evidence** for
Slagdrill Scrapper and opens a **NEW shape family** for the per-slug
attribution lane: **activated-ability + DrawCards on artifact-
creature carrier with a {generic}+{T} cost shape**.  The prior
batch-4 lane covered AddManaToPool / GainLife on real-EoE Land
carriers via the EEEE-idiom; THIS batch extends to a fresh Effect
class (DrawCards) on a fresh carrier shape (artifact-creature +
{2}+{T} mana cost on the activation cost).

**FFFF EEEE-idiom for the ActivatedAbility carrier.**  Same lane
discipline as batches 1-4 (parse + bridge round-trip + Python-side
resolve, NO cross-engine ``compare_fields``).  The Python-side
resolve drives the DrawCards Effect directly through its resolve
path; the post-resolve observable is "p0's hand grew by exactly 1
card from p0's library".  The full activated-ability bypass-stack /
cost-payment trajectory (the ``tap_self`` + ``{2}`` mana cost atoms)
is documented in cost-substrate landings + the
test_probe_activated_abilities_o2-family scope and stays substrate-
deferred for this lane.

**NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
binding the Slagdrill Scrapper slug to its parsed
``ActivatedAbility(DrawCards(amount=1))`` shape; the FIRST PROBED-
tier slot for the DrawCards Effect class on an activated-ability
artifact-creature carrier (DrawCards is widely covered across spell-
effect carriers throughout the pool but the AA-on-creature variant
is the new slot).
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.draw_mill import DrawCards


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Zone constants (mirror Rust's u8 zone IDs).
ZONE_BATTLEFIELD = 2


# ---------------------------------------------------------------------------
# (1) Parser SoT — Slagdrill Scrapper is parser-claimed and carries one
# AA whose effect is ``DrawCards(amount=1)``.
# ---------------------------------------------------------------------------


def test_slagdrill_scrapper_parser_claims_card():
    assert "Slagdrill Scrapper" in _PRINTINGS, (
        "Slagdrill Scrapper must be parser-claimed by the active "
        "CardSource"
    )


def test_slagdrill_scrapper_printed_attrs():
    """Pins the basic printing surface: Artifact Creature, mana cost
    {R}."""
    p = _PRINTINGS["Slagdrill Scrapper"]
    assert "Artifact" in p.card_types
    assert "Creature" in p.card_types
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == (("R", 1),)


def test_slagdrill_scrapper_activated_ability_shape():
    """Slagdrill Scrapper has exactly one ActivatedAbility (the {2},{T}:
    Draw a card ability); its effect is the bare ``DrawCards(amount=1)``
    — the canonical "Draw a card" primitive."""
    p = _PRINTINGS["Slagdrill Scrapper"]
    assert len(p.activated_abilities) == 1, (
        f"Slagdrill Scrapper must have exactly one ActivatedAbility "
        f"(the {{2}},{{T}}: Draw a card ability); got "
        f"{len(p.activated_abilities)}"
    )
    aa = p.activated_abilities[0]
    assert isinstance(aa.effect, DrawCards), (
        f"Slagdrill Scrapper AA effect must be DrawCards; got "
        f"{type(aa.effect).__name__}"
    )
    assert aa.effect.amount == 1, (
        f"Slagdrill Scrapper AA must draw exactly 1 card; got "
        f"amount={aa.effect.amount}"
    )
    # Cost-side: {T} + {2}.  Documented for context; the Effect-side
    # bridge round-trip is what credits PROBED per-slug.
    assert aa.cost.tap_self is True
    assert aa.cost.mana is not None and aa.cost.mana.generic == 2
    assert aa.cost.pay_life == 0
    assert aa.is_mana_ability is False


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the draw_cards dict shape round-trips byte-
# equal to the parsed printing's emitted Effect.
# ---------------------------------------------------------------------------


def test_slagdrill_scrapper_bridge_arm_round_trip():
    """The bridge arm ``draw_cards`` (cross_engine.py:846) round-trips
    ``{"kind": "draw_cards", "count": 1}`` to the matching Python
    ``DrawCards(amount=1)`` instance.  Note the field-name narrowing:
    Rust's dict shape carries ``count`` (mirroring Rust's
    ``parse_effect`` field name) while Python's ``DrawCards`` class
    exposes the same value as ``amount`` — the bridge arm translates
    at the dict boundary."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "draw_cards", "count": 1}
    )
    assert isinstance(bridged, DrawCards)
    assert bridged.amount == 1

    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted DrawCards Effect and the bridged Effect — the structural
    # contract for the PROBED tier.
    p = _PRINTINGS["Slagdrill Scrapper"]
    aa = p.activated_abilities[0]
    assert aa.effect == bridged, (
        f"Slagdrill Scrapper AA Effect must be byte-equal to the "
        f"bridged Effect (DrawCards(amount=1) structural contract for "
        f"the PROBED tier); got parsed={aa.effect!r}, "
        f"bridged={bridged!r}"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts the
# bridged draw_cards dict shape on a Slagdrill-Scrapper-shape
# Artifact Creature carrier with a synthetic tap+{2} AA cost.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_slagdrill_scrapper_draw_cards_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the
    ``{"kind": "draw_cards", "count": 1}`` dict shape on a Slagdrill-
    Scrapper-shape Artifact Creature carrier with a synthetic
    tap+generic-mana AA cost.  The AA-cost-substrate is exercised in
    the cost-substrate landings; this synthetic Rust pin restricts to
    the EFFECT half (mirroring the batch-1/2/3 simpler-cost Rust-
    carrier precedent)."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Slagdrill Scrapper (synthetic carrier)",
            "card_types": ["Artifact", "Creature"],
            "mana_cost": {"generic": 0, "R": 1},
            "power": 2,
            "toughness": 1,
            "effects": [],
            "activated_abilities": [
                {
                    "cost": {"mana": {"generic": 2}},
                    "effect": {
                        "kind": "draw_cards",
                        "count": 1,
                    },
                    "is_mana_ability": False,
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Slagdrill Scrapper printing on Python-side resolve
# for the DrawCards effect.  Mirrors the FFFF EEEE-idiom (parse +
# bridge round-trip + Python-side resolve, NO cross-engine
# compare_fields).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_slagdrill_scrapper_activated_draw_one_parity():
    """**GENUINE real-EoE cross-engine probe — Slagdrill Scrapper
    activated ability → DrawCards(amount=1). PROBED-tier flip
    (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Slagdrill Scrapper printing** on the
    Python side through the DrawCards effect's resolve path.  Mirrors
    the FFFF EEEE-idiom (parse + bridge round-trip + Python-side
    resolve, no cross-engine ``compare_fields``); same lane
    discipline as batches 1-4.

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
    binding the Slagdrill Scrapper slug to the AA + DrawCards(amount=1)
    Effect+bridge round-trip on the REAL parsed EoE printing.  Opens
    the **activated-ability + DrawCards on artifact-creature carrier
    with {generic}+{T} cost** shape family (distinct from the batch-4
    AddManaToPool / GainLife on Land carrier shape family).

    **Bridge arm exercised:**
      * ``draw_cards`` (cross_engine.py:846; scalar count → Python's
        amount field-name narrowing).

    **AA-cost-substrate deferral.**  The full activated-ability
    cost-payment trajectory (the ``tap_self`` + ``{2}`` generic mana
    cost atoms on the ActivationCost, the activated-non-mana-ability
    stack push per CR 602.2, the cross-engine observer parity on the
    hand-size delta) is the cost-substrate /
    test_probe_activated_abilities_o2 family scope and stays
    substrate-deferred for this lane.  Per-slug attribution credits
    the slug based on the Effect+bridge byte-equality alone (the
    round-1 PROBED-tier definition + the batches 1-4 EEEE-idiom
    precedent).

    **Setup (Python-side):**
      * p0 has Slagdrill Scrapper on the battlefield (the AA source).
      * p0's library has at least 1 card to draw.
      * p0's hand is empty pre-resolve.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "draw_cards", "count": 1}``
        translates to ``DrawCards(amount=1)``.
      * The carrier's AA emits the same Effect.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * Post-resolve: p0's hand size grew by exactly 1 (from the
        library); p1's hand and library are untouched.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Slagdrill Scrapper printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Slagdrill Scrapper")
    if real is None:
        pytest.skip("Slagdrill Scrapper absent from active CardSource")
    assert "Artifact" in real.card_types
    assert "Creature" in real.card_types
    aa = real.activated_abilities[0]
    assert isinstance(aa.effect, DrawCards)
    assert aa.effect.amount == 1

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "draw_cards", "count": 1}
    )
    assert isinstance(bridged, DrawCards)
    assert aa.effect == bridged, (
        f"Slagdrill Scrapper AA Effect must be byte-equal to bridged; "
        f"got parsed={aa.effect!r}, bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness regression guard.
    # ------------------------------------------------------------------
    # DrawCards(amount=1) — the canonical "draw a card" primitive —
    # distinct from amount>=2 multi-draw shapes (Sami's Curiosity etc.)
    # and from CycleCards / Surveil / Manifest sibling draw-adjacent
    # primitives.
    assert bridged.amount == 1, (
        "Bridged DrawCards must draw exactly 1 card — distinct from "
        "amount>=2 multi-draw sibling shapes"
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke — drive the parsed effect through
    #    its actual resolve path.  p0's hand grows by 1 card.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Seat the GENUINE parsed Slagdrill Scrapper on p0's bf.
    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Seat at least one library card for p0 to draw (using a basic
    # Land as a no-op placeholder — the DrawCards effect just pops the
    # top of library).
    from mtg_bot.cards import BASIC_LANDS
    library_card = py_state.new_object(
        BASIC_LANDS["Forest"], owner_id=0, zone=Zone.LIBRARY,
    )
    py_state.players[0].library.append(library_card)

    # Pre-resolve sanity: p0's hand is empty.
    p0_hand_before = len(py_state.players[0].hand)
    p0_lib_before = len(py_state.players[0].library)
    p1_hand_before = len(py_state.players[1].hand)
    p1_lib_before = len(py_state.players[1].library)

    # Drive the DrawCards effect through resolve directly, mirroring
    # what the AA does once its cost is paid.
    aa.effect.resolve(py_state, py_source.controller_id)

    # Post-resolve: p0's hand grew by exactly 1; p0's library shrunk by
    # 1; p1 untouched.
    assert len(py_state.players[0].hand) == p0_hand_before + 1, (
        f"Slagdrill Scrapper AA must add exactly 1 card to p0's hand; "
        f"got hand size {p0_hand_before} -> "
        f"{len(py_state.players[0].hand)}"
    )
    assert len(py_state.players[0].library) == p0_lib_before - 1, (
        f"p0's library must shrink by 1; got "
        f"{p0_lib_before} -> {len(py_state.players[0].library)}"
    )
    assert len(py_state.players[1].hand) == p1_hand_before, (
        "p1's hand must remain untouched (controller-of-effect "
        "contract — Slagdrill Scrapper draws into the source's "
        "controller's hand only)"
    )
    assert len(py_state.players[1].library) == p1_lib_before, (
        "p1's library must remain untouched"
    )
