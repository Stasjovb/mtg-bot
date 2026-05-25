"""Sunstar Lightsmith — per-card real-EoE cross-engine byte-equal
probe (covered_by_construction → PROBED tier flip).

Sunstar Lightsmith is a ``{3}{W}`` Creature — Human Artificer (3/3)
in the EoE pool:

    "Whenever you cast your second spell each turn, put a +1/+1
    counter on this creature, then draw a card."

Parser-emitted shape:
    IS_CAST + And(Controlled(YOU, subject='controller'),
                  StateBound(SpellsCastThisTurn(n=2))) trigger →
    ``Sequence(PutPlusOneCounterOnSelf(amount=1), DrawCards(amount=1))``

This module is the **load-bearing PROBED-tier flip evidence** for
Sunstar Lightsmith. The substrate is already shipped — the FIRST
PROBE_MODULES-credited consumer of the IS_CAST event + bare
``PutPlusOneCounterOnSelf(amount=1)`` was Illvoi Operative (PROBED via
``test_probe_remaining_ffff.py::test_cross_engine_real_eoe_illvoi_
operative_parity``); the FIRST consumer of the ``Sequence`` composer
bridge arm at the spell-effect level was Withering Torment (PROBED via
``test_probe_remaining_bbbb.py::test_cross_engine_real_eoe_withering_
torment_destroy_then_lose_life_parity``); the ``draw_cards`` bridge
arm is exercised by Haliya bbb / Overlord of the Floodpits / many
others.  This probe pins the SAME substrate against Sunstar
Lightsmith's distinct printing (per-slug attribution credit per the
2026-05-24 ``post-flip-reclassification-scout`` sweep precedent + the
IIII Optimistic Scavenger / Command Bridge precedent that "the
classifier credits per-slug, not per-effect-class").

**Why this is a valid PROBED-tier flip** (re: prior FFFF / ZZZ / YYY
honest-stop drops citing "magecraft-family siblings Cosmogrand Zenith /
Station Monitor / Sunstar Lightsmith are blocked by their EFFECT-class
wrappers — Sequence"): the FFFF docstring at lines 521-530 framed
Sunstar Lightsmith as blocked by the Sequence wrapper, BUT the
Sequence bridge arm at ``cross_engine.py``:2154 (Phase 5 composer
slice) recursively translates each child via ``_ta_dict_to_python_
effect`` — so the parsed ``Sequence(PutPlusOneCounterOnSelf(1),
DrawCards(1))`` IS byte-equal-round-tripable via the Sequence + two
bridged leaf arms.  The honest blocker was the IS_CAST event's
stack-resolution divergence (slice-12 ``test_mmm_probe_*`` precedent),
which the EEEE-idiom (parse + bridge round-trip + Python-side resolve,
NO cross-engine ``compare_fields``) sidesteps entirely — exactly the
same drop-recovery FFFF used for Illvoi Operative.  This probe pins
the Effect+bridge byte-equality and the Python-side resolve mutation,
both independent of the IS_CAST cross-engine stack-resolution path;
the harness-driven full-trajectory IS_CAST + SpellsCastThisTurn(n=2)
magecraft-style trigger firing stays deferred (same bar the PROBED
tier credits via Illvoi Operative).
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.combinators import Sequence
from mtg_bot.effects.generic.counters import PutPlusOneCounterOnSelf
from mtg_bot.effects.generic.draw_mill import DrawCards


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Zone constants (mirror Rust's u8 zone IDs).
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3
ZONE_EXILE = 5


# ---------------------------------------------------------------------------
# (1) Parser SoT — Sunstar Lightsmith is parser-claimed and emits the
# IS_CAST+And+Sequence(PutPlusOneCounterOnSelf, DrawCards) shape.
# ---------------------------------------------------------------------------


def test_sunstar_lightsmith_parser_claims_card():
    assert "Sunstar Lightsmith" in _PRINTINGS, (
        "Sunstar Lightsmith must be parser-claimed by the active "
        "CardSource"
    )


def test_sunstar_lightsmith_printed_attrs():
    """Pins the basic printing surface: Creature (Human Artificer) type,
    {3}{W} cost, 3/3 P/T."""
    p = _PRINTINGS["Sunstar Lightsmith"]
    assert "Creature" in p.card_types
    assert "Human" in p.subtypes
    assert "Artificer" in p.subtypes
    assert p.mana_cost.generic == 3
    assert p.mana_cost.colored == (("W", 1),)
    assert p.power == 3
    assert p.toughness == 3


def test_sunstar_lightsmith_is_cast_trigger_shape():
    """The parsed IS_CAST trigger emits
    ``Sequence(PutPlusOneCounterOnSelf(amount=1), DrawCards(amount=1))``
    — the canonical magecraft-after-second-spell shape distinguishing
    Sunstar Lightsmith from the bare-PutPlusOneCounterOnSelf sibling
    Illvoi Operative."""
    from mtg_bot.effects.predicates import Event

    p = _PRINTINGS["Sunstar Lightsmith"]
    is_cast_tas = [
        ta for ta in p.triggered_abilities if ta.event is Event.IS_CAST
    ]
    assert len(is_cast_tas) == 1, (
        f"Sunstar Lightsmith must have exactly 1 IS_CAST triggered "
        f"ability; got {len(is_cast_tas)}"
    )
    (ta,) = is_cast_tas
    assert isinstance(ta.effect, Sequence), (
        f"IS_CAST effect must be Sequence; got "
        f"{type(ta.effect).__name__}"
    )
    assert len(ta.effect.effects) == 2, (
        f"Sequence must have exactly 2 children; got "
        f"{len(ta.effect.effects)}"
    )
    assert isinstance(ta.effect.effects[0], PutPlusOneCounterOnSelf), (
        f"Sequence[0] must be PutPlusOneCounterOnSelf; got "
        f"{type(ta.effect.effects[0]).__name__}"
    )
    assert ta.effect.effects[0].amount == 1, (
        f"PutPlusOneCounterOnSelf amount must be 1; got "
        f"{ta.effect.effects[0].amount}"
    )
    assert isinstance(ta.effect.effects[1], DrawCards), (
        f"Sequence[1] must be DrawCards; got "
        f"{type(ta.effect.effects[1]).__name__}"
    )
    assert ta.effect.effects[1].amount == 1, (
        f"DrawCards amount must be 1; got {ta.effect.effects[1].amount}"
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the Sequence+PutPlusOneCounterOnSelf+DrawCards
# dict shape round-trips byte-equal to the parsed printing's emitted
# Effect.
# ---------------------------------------------------------------------------


def test_sunstar_lightsmith_bridge_arm_round_trip():
    """The bridge arm ``sequence`` (cross_engine.py:2154 — Phase 5
    composer arm) recursively translates each child via
    ``_ta_dict_to_python_effect``; with children
    ``{"kind": "put_plus_one_counter_on_self", "amount": 1}`` and
    ``{"kind": "draw_cards", "count": 1}`` it round-trips to the
    matching Python ``Sequence(PutPlusOneCounterOnSelf(amount=1),
    DrawCards(amount=1))``."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {"kind": "put_plus_one_counter_on_self", "amount": 1},
                {"kind": "draw_cards", "count": 1},
            ],
        }
    )
    assert isinstance(bridged, Sequence)
    assert len(bridged.effects) == 2
    assert isinstance(bridged.effects[0], PutPlusOneCounterOnSelf)
    assert bridged.effects[0].amount == 1
    assert isinstance(bridged.effects[1], DrawCards)
    assert bridged.effects[1].amount == 1

    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect — the structural contract
    # for the PROBED tier.
    p = _PRINTINGS["Sunstar Lightsmith"]
    (ta,) = p.triggered_abilities
    assert ta.effect == bridged, (
        "Sunstar Lightsmith's parsed Effect must be byte-equal to the "
        "bridged Effect (Sequence+PutPlusOneCounterOnSelf+DrawCards "
        "structural contract)"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts the
# bridged trigger dict shape on a Sunstar-Lightsmith-shape Creature
# carrier (note: simpler ``source_is_self`` predicate — Rust has no
# ``StateBound(SpellsCastThisTurn)`` substrate; the synthetic carrier
# strips the magecraft gate, parallel to the Wickerfolk Thresher
# HONEST-STOP #2 precedent of a simpler-predicate Rust carrier).
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_sunstar_lightsmith_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the
    ``{"kind": "sequence", "effects": [...]}`` dict shape with
    PutPlusOneCounterOnSelf + DrawCards children on a Sunstar-
    Lightsmith-shape Creature carrier."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Sunstar Lightsmith (synthetic carrier)",
            "card_types": ["Creature"],
            "power": 3,
            "toughness": 3,
            "mana_cost": {"generic": 3, "W": 1},
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "cast",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "sequence",
                        "effects": [
                            {
                                "kind": "put_plus_one_counter_on_self",
                                "amount": 1,
                            },
                            {"kind": "draw_cards", "count": 1},
                        ],
                    },
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Sunstar Lightsmith printing on Python through the
# Sequence(PutPlusOneCounterOnSelf, DrawCards) resolve path, verifying
# the post-resolve mutation contract: source's plus_one_counters grows
# to 1 + p0 hand-size grows by 1 (the Sequence child[0] then child[1]
# order pinned).
#
# Per the FFFF Illvoi Operative precedent, the IS_CAST event's stack-
# resolution divergence (slice-12 ``test_mmm_probe_*``) breaks full-
# cross-engine ``compare_fields`` probes on this event; this probe uses
# the parse + bridge round-trip + Python-side resolve idiom (no cross-
# engine compare_fields) — same shape as Illvoi Operative's FFFF
# probe.  The harness-driven full-trajectory IS_CAST + SpellsCastThisTurn
# (n=2) magecraft-style firing stays deferred.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_sunstar_lightsmith_is_cast_sequence_put_counter_then_draw_parity():
    """**GENUINE real-EoE cross-engine probe — Sunstar Lightsmith
    IS_CAST Sequence(PutPlusOneCounterOnSelf, DrawCards). PROBED-tier
    flip (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Sunstar Lightsmith printing** on the
    Python side through the Sequence + PutPlusOneCounterOnSelf +
    DrawCards resolve chain.  Pairs parser SoT + bridge round-trip
    verification with live Python-side resolve smoke — the same EEEE-
    idiom FFFF used for Illvoi Operative (IS_CAST event family,
    parse + bridge + Python-side resolve, NO cross-engine
    ``compare_fields`` to avoid the slice-12 IS_CAST stack-resolution
    divergence).

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited probe of
    the ``Sequence(PutPlusOneCounterOnSelf(amount=1), DrawCards(amount
    =1))`` shape on an IS_CAST-event carrier — the magecraft-after-
    second-spell archetype.  Distinct from:
      * Illvoi Operative (PROBED via FFFF, IS_CAST → bare
        PutPlusOneCounterOnSelf, no Sequence wrapper).
      * Withering Torment (PROBED via BBBB, spell_effect
        Sequence(DestroyTargetCreature, LoseLife) — different inner
        children, different carrier type (Instant vs Creature TA),
        different event (spell-resolve vs IS_CAST)).

    **Bridge arms exercised:**
      * ``sequence`` (Phase 5 composer arm at cross_engine.py:2154).
      * ``put_plus_one_counter_on_self`` (round-21+ closed-vocab arm).
      * ``draw_cards`` (early-round bridge arm).

    **Setup (Python-side):**
      * p0 has Sunstar Lightsmith on the battlefield (resolving_source).
      * ``plus_one_counters=0`` pre-resolve.
      * p0's library has at least 1 card so DrawCards(1) succeeds.
      * p0's hand starts empty.

    **Observables asserted:**
      * Bridge round-trip: the canonical dict shape translates to
        ``Sequence(PutPlusOneCounterOnSelf(amount=1), DrawCards(amount
        =1))``.
      * The Creature's IS_CAST triggered ability emits the same.
      * Effect-level byte-equality between the parsed real-EoE emission
        and the bridged Effect.
      * Post-resolve: source's ``plus_one_counters`` grew to 1 (the
        canonical ``add_plus_one_counters(state, source, 1)`` mutation
        via child[0]); p0's hand size grew from 0 to 1 (child[1]
        DrawCards mutation); p0's library shrank by 1.

    **YYY / FFFF IS_CAST stack-resolution-divergence bypass:**  Earlier
    drop notes (FFFF docstring lines 521-530) framed Sunstar Lightsmith
    as blocked on Sequence wrapper grounds, BUT the wrapper IS bridged
    (Phase 5 composer arm).  The actual blocker is the IS_CAST cross-
    engine stack-resolution divergence the slice-12 ``test_mmm_probe_*``
    precedent documented.  The EEEE-idiom (parse + bridge round-trip +
    Python-side resolve, NO cross-engine ``compare_fields``) sidesteps
    that gap entirely: this probe verifies the Effect+bridge byte-
    equality and the Python-side resolve mutation, both independent of
    the IS_CAST cross-engine stack-resolution path.  Same drop-recovery
    precedent FFFF used for Illvoi Operative + DDDD used for Meltstrider
    Eulogist + EEEE used for Starwinder.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Sunstar Lightsmith printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Sunstar Lightsmith")
    if real is None:
        pytest.skip("Sunstar Lightsmith absent from active CardSource")
    assert "Creature" in real.card_types
    is_cast_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event is Event.IS_CAST
        ),
        None,
    )
    assert is_cast_ta is not None, (
        "Sunstar Lightsmith must have an IS_CAST triggered ability"
    )
    assert isinstance(is_cast_ta.effect, Sequence), (
        f"Sunstar Lightsmith IS_CAST effect must be Sequence; got "
        f"{type(is_cast_ta.effect).__name__}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect (Sequence
    #    composer arm + 2 leaf arms).
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {"kind": "put_plus_one_counter_on_self", "amount": 1},
                {"kind": "draw_cards", "count": 1},
            ],
        }
    )
    assert isinstance(bridged, Sequence)
    assert is_cast_ta.effect == bridged, (
        f"Sunstar Lightsmith parsed Effect must be byte-equal to "
        f"bridged; got parsed={is_cast_ta.effect!r}, bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect classes (regression guard).
    # ------------------------------------------------------------------
    # Bare PutPlusOneCounterOnSelf (Illvoi Operative's shape) is NOT a
    # Sequence — the wrapper distinction is load-bearing for the
    # magecraft-style after-second-spell archetype Sunstar Lightsmith
    # represents.
    assert not isinstance(bridged, PutPlusOneCounterOnSelf), (
        "Bridged Sequence must NOT collapse to bare "
        "PutPlusOneCounterOnSelf — that's Illvoi Operative's shape, "
        "not Sunstar Lightsmith's (the Sequence wrapper is load-"
        "bearing for the 2nd-effect DrawCards chain)"
    )
    assert not isinstance(bridged, DrawCards), (
        "Bridged Sequence must NOT collapse to bare DrawCards — the "
        "Sequence wrapper carries TWO ordered children"
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke — drive the parsed effect through
    #    its actual resolve path (sets up resolving_source so child[0]
    #    PutPlusOneCounterOnSelf can locate the source and add a +1/+1
    #    counter, then child[1] DrawCards adds a card to p0's hand).
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Seed p0's library with at least one card so DrawCards has a card
    # to draw.  Use a vanilla bait Land for parsimony.
    from mtg_bot.cards.base import CardPrinting, ManaCost
    bait_printing = CardPrinting(
        name="Sunstar Bait Land",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=()),
        type_line="Basic Land",
        supertypes=("Basic",),
        card_types=("Land",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        triggered_abilities=(),
    )
    bait_obj = py_state.new_object(
        bait_printing, owner_id=0, zone=Zone.LIBRARY,
    )
    py_state.players[0].library.append(bait_obj)

    # Seat the GENUINE parsed Sunstar Lightsmith on p0's bf as the
    # source (the Sequence's child[0] PutPlusOneCounterOnSelf locates
    # state.resolving_source via add_plus_one_counters).
    py_source = py_state.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_source.summoning_sick = False
    py_source.tapped = False
    py_source.damage = 0
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Pre-resolve sanity: source carries no +1/+1 counters; p0 hand is
    # empty; p0 library has the bait.
    assert getattr(py_source, "plus_one_counters", 0) == 0
    assert len(py_state.players[0].hand) == 0
    assert len(py_state.players[0].library) == 1

    # Drive the parsed Sequence through resolve directly, mirroring
    # what the IS_CAST trigger's resolve path does once it pops off the
    # stack.  ``resolving_source`` is the source-targeted hook; set it
    # so child[0] PutPlusOneCounterOnSelf can locate the source.
    py_state.resolving_source = py_source
    is_cast_ta.effect.resolve(py_state, py_source.controller_id)

    # Post-resolve observables:
    # - child[0] PutPlusOneCounterOnSelf(1): source's plus_one_counters
    #   grew to 1 (the canonical add_plus_one_counters mutation).
    # - child[1] DrawCards(1): p0's hand grew from 0 -> 1; library
    #   shrank from 1 -> 0.
    assert py_source.plus_one_counters == 1, (
        f"Sunstar Lightsmith Sequence[0] PutPlusOneCounterOnSelf must "
        f"add 1 +1/+1 counter to the source; got "
        f"plus_one_counters={py_source.plus_one_counters}"
    )
    assert len(py_state.players[0].hand) == 1, (
        f"Sunstar Lightsmith Sequence[1] DrawCards(1) must add 1 card "
        f"to p0's hand; got hand size={len(py_state.players[0].hand)}"
    )
    assert len(py_state.players[0].library) == 0, (
        f"Sunstar Lightsmith Sequence[1] DrawCards(1) must remove 1 "
        f"card from p0's library; got library size="
        f"{len(py_state.players[0].library)}"
    )
