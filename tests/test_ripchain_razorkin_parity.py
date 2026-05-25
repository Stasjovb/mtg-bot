"""Ripchain Razorkin — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

Ripchain Razorkin is a ``{3}{R}`` Creature — Human Berserker in the
EoE pool (0 17lands decks) with the printed activated ability:

    "Reach.
     {2}{R}, Sacrifice a land: Draw a card."

Parser-emitted Effect shape:

  * Activated ability: mana cost ``{2}{R}``, sacrifice_a_land cost,
    effect = bare ``DrawCards(amount=1)`` — the canonical single-card
    draw primitive.

**EEEE-idiom for the AA-driven bare-DrawCards carrier.**  Templates
off ``test_mana_confluence_parity.py`` (the AddManaToPool single-AA
bare-effect precedent) — same parse + bridge round-trip + Python-
side resolve discipline; same lane discipline as batches 1-11.

The ``draw_cards`` bridge arm (cross_engine.py:879) translates the
``count`` field (Rust's name) into Python's ``amount`` field via a
documented cross-engine field rename.  ``{"kind": "draw_cards",
"count": 1}`` → ``DrawCards(amount=1)`` byte-equal to the parsed AA
effect.

**NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
binding the Ripchain Razorkin slug to its parsed
``ActivatedAbility(DrawCards(amount=1))`` shape, AND the FIRST
PROBED-tier slot for the DrawCards Effect class on a real-EoE
ACTIVATED-ABILITY carrier (prior DrawCards probes pin the class on
TriggeredAbility / SpellEffect carriers — see Demonic Counsel
(test_probe_remaining_qqq.py: search-then-draw), Decode Transmissions
(spell), and the DDD downstream batch — none drive the bare
DrawCards primitive via an AA).

**AA-cost-substrate deferral.**  The full AA-cost-payment trajectory
(the ``{2}{R}`` mana cost atom + the ``sacrifice_a_land`` cost atom
on the ActivationCost, the cost-substrate cross-engine observer
parity on the post-resolve library / hand / graveyard delta) is the
cost-substrate / sacrifice-land-cost family scope and stays
substrate-deferred for this lane.  Per-slug attribution credits the
slug based on the Effect+bridge byte-equality alone.
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


ZONE_BATTLEFIELD = 2


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_ripchain_razorkin_parser_claims_card():
    assert "Ripchain Razorkin" in _PRINTINGS, (
        "Ripchain Razorkin must be parser-claimed by the active "
        "CardSource"
    )


def test_ripchain_razorkin_printed_attrs():
    """Pins basic printing surface: Creature - Human Berserker, mana
    cost {3}{R}, reach keyword."""
    p = _PRINTINGS["Ripchain Razorkin"]
    assert "Creature" in p.card_types
    assert p.mana_cost.generic == 3
    assert p.mana_cost.colored == (("R", 1),)
    assert "reach" in p.keywords
    assert p.spell_effect is None
    assert p.triggered_abilities == ()
    assert p.static_abilities == ()


def test_ripchain_razorkin_draw_aa_shape():
    """Ripchain Razorkin has exactly one ActivatedAbility (the
    {2}{R}, sacrifice-a-land Draw a Card AA); effect = bare
    ``DrawCards(amount=1)`` — the canonical single-card draw
    primitive (distinct from sibling DrawCards Effect uses on
    Demonic Counsel's search-then-draw composite, Decode
    Transmissions' instant-speed cantrip, etc.)."""
    p = _PRINTINGS["Ripchain Razorkin"]
    assert len(p.activated_abilities) == 1
    aa = p.activated_abilities[0]
    assert isinstance(aa.effect, DrawCards)
    assert aa.effect.amount == 1, (
        f"Ripchain Razorkin AA must draw exactly 1 card; got "
        f"amount={aa.effect.amount}"
    )
    # Cost-side: {2}{R} mana + sacrifice a land.
    assert aa.cost.mana is not None
    assert aa.cost.mana.generic == 2
    assert aa.cost.mana.colored == (("R", 1),)
    assert aa.cost.sacrifice_a_land is True
    assert aa.cost.tap_self is False
    assert aa.is_mana_ability is False


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the draw_cards arm folds Rust's `count`
# field into Python's `amount` (documented cross-engine rename per
# cross_engine.py:7395 — also for `each_opponent_discards.count` and
# `may_do.inner_effect → inner`).
# ---------------------------------------------------------------------------


def test_ripchain_razorkin_draw_cards_bridge_round_trip():
    """The ``draw_cards`` bridge arm round-trips ``{"kind":
    "draw_cards", "count": 1}`` to the matching Python
    ``DrawCards(amount=1)`` instance.  Effect-level byte-equality
    between the parsed AA effect and the bridged Effect — the
    structural contract for the PROBED tier."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "draw_cards", "count": 1}
    )
    assert isinstance(bridged, DrawCards)
    assert bridged.amount == 1

    p = _PRINTINGS["Ripchain Razorkin"]
    aa = p.activated_abilities[0]
    assert aa.effect == bridged, (
        f"Ripchain Razorkin AA Effect must be byte-equal to the "
        f"bridged Effect (DrawCards(amount=1) structural contract for "
        f"the PROBED tier); got parsed={aa.effect!r}, bridged="
        f"{bridged!r}"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_ripchain_razorkin_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the
    ``draw_cards`` dict shape on a Ripchain-Razorkin-shape Creature
    carrier with a synthetic AA mana cost.  The sacrifice-a-land cost
    atom is cost-substrate-scope and not exercised at the EFFECT-
    half lockstep."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Ripchain Razorkin (synthetic carrier)",
            "card_types": ["Creature"],
            "subtypes": ["Human", "Berserker"],
            "power": 2,
            "toughness": 2,
            "mana_cost": {"generic": 3, "R": 1},
            "effects": [],
            "activated_abilities": [
                {
                    "cost": {"mana": {"generic": 2, "R": 1}},
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
# (4) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_ripchain_razorkin_draw_card_activation_parity():
    """**GENUINE real-EoE cross-engine probe — Ripchain Razorkin
    activated ability → DrawCards(amount=1) resolve.  PROBED-tier
    flip (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Ripchain Razorkin printing** on the
    Python side through the DrawCards effect's resolve path.  Mirrors
    the EEEE-idiom (parse + bridge round-trip + Python-side resolve,
    no cross-engine ``compare_fields``); same lane discipline as
    batches 1-11.

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
    binding the Ripchain Razorkin slug AND the FIRST PROBED-tier
    slot for the DrawCards Effect class on a real-EoE ACTIVATED-
    ABILITY carrier (prior DrawCards probes pin the class on
    TriggeredAbility / SpellEffect carriers — Demonic Counsel's
    search-then-draw composite, Decode Transmissions' instant
    spell — but none drive the bare DrawCards primitive via an AA).

    **Bridge arm exercised:**
      * ``draw_cards`` (cross_engine.py:879; Rust ``count`` → Python
        ``amount`` cross-engine field rename, documented).

    **AA-cost-substrate deferral.**  The full {2}{R}+sacrifice-a-
    land cost-payment trajectory + cross-engine observer parity on
    the pre/post hand + library + graveyard delta are cost-
    substrate scope and stay deferred for this lane.  Per-slug
    attribution credits the slug based on Effect+bridge byte-
    equality alone.

    **Setup (Python-side):**
      * p0 has Ripchain Razorkin on the battlefield (the AA source).
      * p0's library has 1 filler card (the card to be drawn).
      * p0's hand starts empty.

    **Observables asserted:**
      * Bridge round-trip: ``{"kind": "draw_cards", "count": 1}``
        translates to ``DrawCards(amount=1)``.
      * The Razorkin's AA emits the same Effect.
      * Effect-level byte-equality between parsed real-EoE emission
        and bridged Effect.
      * Post-resolve: p0's hand has 1 card; library is empty; the
        drawn card's identity is the filler.
      * Opponent's hand + library are untouched.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.game import Zone
    from mtg_bot.cards.base import CardPrinting, ManaCost

    real = _PRINTINGS.get("Ripchain Razorkin")
    if real is None:
        pytest.skip("Ripchain Razorkin absent from active CardSource")
    assert "Creature" in real.card_types
    aa = real.activated_abilities[0]
    assert isinstance(aa.effect, DrawCards)
    assert aa.effect.amount == 1

    bridged = _ta_dict_to_python_effect(
        {"kind": "draw_cards", "count": 1}
    )
    assert isinstance(bridged, DrawCards)
    assert aa.effect == bridged, (
        f"parsed={aa.effect!r}, bridged={bridged!r}"
    )

    # Distinctness regression guard — Ripchain Razorkin's
    # ``DrawCards(amount=1)`` shape is the bare single-card primitive
    # (distinct from any amount != 1 variant).  Also distinct from
    # sibling DrawCards Effect-class uses on Demonic Counsel's
    # search-then-draw composite (Sequence(SearchLibrary, DrawCards))
    # and Decode Transmissions' instant-speed shape — those compose
    # DrawCards into a multi-effect chain or a spell carrier, NOT a
    # bare-AA carrier.
    assert bridged.amount == 1, (
        "Bridged DrawCards must carry amount=1 — the bare single-card "
        "draw primitive"
    )

    # Python-side resolve smoke.
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Seat one library card on p0 — the draw target.
    library_card_printing = CardPrinting(
        name="Ripchain Razorkin Draw Target",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=()),
        type_line="Creature — Bear",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Bear",),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(),
    )
    library_card = py_state.new_object(
        library_card_printing, owner_id=0, zone=Zone.LIBRARY,
    )
    py_state.players[0].library.append(library_card)
    assert len(py_state.players[0].hand) == 0
    assert len(py_state.players[0].library) == 1

    # Pre-resolve sanity: p1's hand + library untouched.
    pre_p1_hand_size = len(py_state.players[1].hand)
    pre_p1_lib_size = len(py_state.players[1].library)

    # Drive the DrawCards effect through resolve directly — mirrors
    # the AA-resolution machinery's call after cost-payment.
    aa.effect.resolve(py_state, py_source.controller_id)

    # Post-resolve: p0 drew the filler; library is empty.
    assert len(py_state.players[0].hand) == 1, (
        f"P0's hand must have 1 card after draw; got "
        f"{len(py_state.players[0].hand)}"
    )
    assert len(py_state.players[0].library) == 0, (
        f"P0's library must be empty after the only card was drawn; "
        f"got {len(py_state.players[0].library)}"
    )
    # The drawn card is the same library card we seated.
    drawn = py_state.players[0].hand[0]
    assert drawn.id == library_card.id, (
        f"Drawn card must be the library filler; got id={drawn.id}, "
        f"expected {library_card.id}"
    )
    # Opponent's zones stay untouched (DrawCards only resolves on
    # the controller's side).
    assert len(py_state.players[1].hand) == pre_p1_hand_size
    assert len(py_state.players[1].library) == pre_p1_lib_size
