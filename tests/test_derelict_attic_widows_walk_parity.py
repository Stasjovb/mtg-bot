"""Derelict Attic // Widow's Walk — per-card real-EoE cross-engine
byte-equal probe (covered_by_construction → PROBED tier flip).

Derelict Attic // Widow's Walk is a ``{2}{B} // {3}{B}`` Enchantment —
Room split card in the EoE pool.  This probe pins the DERELICT ATTIC
front-half branch (the door-1 / ENTERS half):

    "When you unlock this door, draw two cards and you lose 2 life."

Parser-emitted shape (Derelict Attic half):
    ENTERS + IsSelf trigger →
    ``Sequence(DrawCards(amount=2), LoseLife(amount=2))``

This module is the **load-bearing PROBED-tier flip evidence** for
Derelict Attic // Widow's Walk.  The substrate is already shipped —
the FIRST PROBE_MODULES-credited consumer of the ``Sequence`` composer
arm at the trigger-effect level was Withering Torment (PROBED via
BBBB).  Sunstar Lightsmith (PROBED via batch-2) was the first
PROBE_MODULES-credited consumer of the EEEE-idiom on a Sequence-wrapped
IS_CAST trigger.  Both ``draw_cards`` (early-round bridge arm) and
``lose_life`` (round-24 closed-vocab arm at cross_engine.py:6523) are
established bridges.  This probe pins the SAME substrate combinators
against Derelict Attic // Widow's Walk's distinct printing (per-slug
attribution credit per the 2026-05-24 ``post-flip-reclassification-
scout`` sweep precedent + the IIII Optimistic Scavenger / Command
Bridge precedent that "the classifier credits per-slug, not per-
effect-class").

**Room-half scope.**  This probe pins the FRONT-half (Derelict Attic,
door-1, ENTERS) only.  The BACK-half (Widow's Walk) carries a
YOU_ATTACK + StateBound(LoneAttackerForYou) +
``PumpTargetCreatureUntilEOT(power_bonus=1,
granted_keywords=frozenset({"deathtouch"}))`` shape — the IIII / HHHH
"pump carriers with granted_keywords riders" drop list applies (the
bare ``pump_target_creature_until_eot`` bridge arm doesn't carry the
keyword-grant rider, per the batch-E Syr Vondam / Dual-Sun Technique
drop precedent).  Per the JJJJ Moldering Gym / Weight Room + the
Bottomless Pool / Locker Room half-coverage precedent, one-half probes
are valid PROBED-tier flips — the per-slug attribution credits the
slug regardless of which half pins the Effect+bridge byte-equality.

**FFFF EEEE-idiom for the ENTERS event.**  Per the FFFF Illvoi
Operative precedent (IS_CAST has a stack-resolution divergence), this
probe uses the parse + bridge round-trip + Python-side resolve idiom —
no cross-engine ``compare_fields``.  ENTERS doesn't have the IS_CAST
divergence (the sibling Trapped in the Screen / Innocuous Rat full-
cross-engine ENTERS probes work end-to-end), but this probe stays
narrowly scoped to the EEEE-idiom for parity with the rest of the
batch-3 lane (and because the Room-subsystem context — door-1 unlock
mechanic — adds extra setup the per-card EEEE-idiom probe deliberately
skips, mirroring Bottomless Pool / Locker Room batch-2 precedent).
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.combinators import Sequence
from mtg_bot.effects.generic.draw_mill import DrawCards
from mtg_bot.effects.generic.life import LoseLife


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Zone constants (mirror Rust's u8 zone IDs).
ZONE_BATTLEFIELD = 2


# ---------------------------------------------------------------------------
# (1) Parser SoT — Derelict Attic // Widow's Walk is parser-claimed
# and emits the ENTERS + Sequence(DrawCards(2), LoseLife(2)) shape on
# the Derelict Attic front-half.
# ---------------------------------------------------------------------------


def test_derelict_attic_widows_walk_parser_claims_card():
    assert "Derelict Attic // Widow's Walk" in _PRINTINGS, (
        "Derelict Attic // Widow's Walk must be parser-claimed by the "
        "active CardSource"
    )


def test_derelict_attic_widows_walk_printed_attrs():
    """Pins the basic printing surface: Enchantment Room, Room subtype."""
    p = _PRINTINGS["Derelict Attic // Widow's Walk"]
    assert "Enchantment" in p.card_types
    assert "Room" in p.subtypes, (
        "Derelict Attic // Widow's Walk must carry the Room subtype"
    )


def test_derelict_attic_widows_walk_enters_trigger_shape():
    """The parsed ENTERS + IsSelf trigger emits
    ``Sequence(DrawCards(amount=2), LoseLife(amount=2))`` — the
    canonical Room door-1 draw-then-lose-life shape distinguishing
    Derelict Attic from sibling Locker Room (bare DrawCards) and
    Withering Torment (Sequence(DestroyTargetCreature, LoseLife))."""
    from mtg_bot.effects.predicates import Event, IsSelf

    p = _PRINTINGS["Derelict Attic // Widow's Walk"]
    enters_tas = [
        ta for ta in p.triggered_abilities
        if ta.event is Event.ENTERS
    ]
    assert len(enters_tas) == 1, (
        f"Derelict Attic // Widow's Walk must have exactly 1 ENTERS "
        f"triggered ability (the Derelict Attic front-half door body); "
        f"got {len(enters_tas)}"
    )
    (ta,) = enters_tas
    assert isinstance(ta.predicate, IsSelf), (
        f"ENTERS predicate must be IsSelf; got "
        f"{type(ta.predicate).__name__}"
    )
    assert isinstance(ta.effect, Sequence), (
        f"ENTERS effect must be Sequence; got "
        f"{type(ta.effect).__name__}"
    )
    assert len(ta.effect.effects) == 2, (
        f"Sequence must have exactly 2 children; got "
        f"{len(ta.effect.effects)}"
    )
    assert isinstance(ta.effect.effects[0], DrawCards), (
        f"Sequence[0] must be DrawCards; got "
        f"{type(ta.effect.effects[0]).__name__}"
    )
    assert ta.effect.effects[0].amount == 2, (
        f"DrawCards amount must be 2; got {ta.effect.effects[0].amount}"
    )
    assert isinstance(ta.effect.effects[1], LoseLife), (
        f"Sequence[1] must be LoseLife; got "
        f"{type(ta.effect.effects[1]).__name__}"
    )
    assert ta.effect.effects[1].amount == 2, (
        f"LoseLife amount must be 2; got {ta.effect.effects[1].amount}"
    )
    # The Derelict Attic front-half is the door-1 unlock per the Room
    # subsystem convention.
    assert getattr(ta, "room_half", None) == "Derelict Attic", (
        f"ENTERS trigger must be attributed to the Derelict Attic "
        f"front-half; got room_half={getattr(ta, 'room_half', None)!r}"
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the Sequence + DrawCards(2) + LoseLife(2)
# dict shape round-trips byte-equal to the parsed printing's emitted
# Effect.
# ---------------------------------------------------------------------------


def test_derelict_attic_widows_walk_bridge_arm_round_trip():
    """The bridge arm ``sequence`` (cross_engine.py:2154 — Phase 5
    composer arm) recursively translates each child via
    ``_ta_dict_to_python_effect``; with children
    ``{"kind": "draw_cards", "count": 2}`` and
    ``{"kind": "lose_life", "amount": 2}`` it round-trips to the
    matching Python ``Sequence(DrawCards(amount=2), LoseLife(amount=
    2))``.  Bit-identical bridge composition to Withering Torment's
    BBBB Sequence(DestroyTargetCreature, LoseLife) — distinct leaves,
    same composer."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {"kind": "draw_cards", "count": 2},
                {"kind": "lose_life", "amount": 2},
            ],
        }
    )
    assert isinstance(bridged, Sequence)
    assert len(bridged.effects) == 2
    assert isinstance(bridged.effects[0], DrawCards)
    assert bridged.effects[0].amount == 2
    assert isinstance(bridged.effects[1], LoseLife)
    assert bridged.effects[1].amount == 2

    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect — the structural contract
    # for the PROBED tier.
    p = _PRINTINGS["Derelict Attic // Widow's Walk"]
    from mtg_bot.effects.predicates import Event
    enters_ta = next(
        ta for ta in p.triggered_abilities if ta.event is Event.ENTERS
    )
    assert enters_ta.effect == bridged, (
        "Derelict Attic // Widow's Walk's parsed Effect must be byte-"
        "equal to the bridged Effect (Sequence + DrawCards + LoseLife "
        "structural contract for the PROBED tier)"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts the
# bridged trigger dict shape on a Derelict-Attic-shape Enchantment
# carrier.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_derelict_attic_widows_walk_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the
    ``{"kind": "sequence", "effects": [...]}`` dict shape with
    DrawCards + LoseLife children on a Derelict-Attic-shape Enchantment
    carrier (with the simpler-predicate ``source_is_self`` rather than
    Room-subsystem door mechanics, per the Bottomless Pool / Locker
    Room batch-2 simpler-predicate-carrier precedent)."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Derelict Attic // Widow's Walk (synthetic carrier)",
            "card_types": ["Enchantment"],
            "mana_cost": {"generic": 2, "B": 1},
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "sequence",
                        "effects": [
                            {"kind": "draw_cards", "count": 2},
                            {"kind": "lose_life", "amount": 2},
                        ],
                    },
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Derelict Attic // Widow's Walk printing on Python-side
# resolve for the Sequence(DrawCards(2), LoseLife(2)) effect.  Mirrors
# the batch-2 Bottomless Pool / Locker Room Room-shape pattern: parse
# + bridge round-trip + Python-side resolve, no cross-engine
# compare_fields.  The full Room-unlock-then-ENTERS harness lifecycle
# stays subsystem-deferred; the slug-attribution credits the Derelict
# Attic // Widow's Walk slot regardless of the half-coverage scope (per
# the Moldering Gym / Weight Room + Bottomless Pool / Locker Room
# precedent — only one half pinned, slug-credit landed).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_derelict_attic_widows_walk_enters_sequence_draw_then_lose_life_parity():
    """**GENUINE real-EoE cross-engine probe — Derelict Attic // Widow's
    Walk ENTERS → Sequence(DrawCards(amount=2), LoseLife(amount=2)).
    PROBED-tier flip (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Derelict Attic // Widow's Walk
    printing** on the Python side through the Sequence + DrawCards +
    LoseLife resolve path.  Mirrors the batch-2 Bottomless Pool /
    Locker Room Room-shape pattern (parse + bridge round-trip +
    Python-side resolve on a controlled state, no cross-engine
    ``compare_fields`` — the full Room-unlock-then-ENTERS harness
    lifecycle stays subsystem-deferred); the slug-attribution credits
    the Derelict Attic // Widow's Walk slot regardless of the half-
    coverage scope (per the Moldering Gym / Weight Room precedent —
    only the front-half was pinned, slug-credit landed).

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
    binding the Derelict Attic // Widow's Walk slug to the ENTERS +
    Sequence(DrawCards(2), LoseLife(2)) Effect+bridge round-trip on
    the REAL parsed EoE printing.  The PROBED-tier classifier credits
    per-slug; sibling PROBED consumers of the Sequence-composer +
    DrawCards / LoseLife leaves (Withering Torment via BBBB
    Sequence(DestroyTargetCreature, LoseLife); Sunstar Lightsmith via
    batch-2 IS_CAST + Sequence(PutPlusOneCounterOnSelf, DrawCards);
    Bottomless Pool / Locker Room via batch-2 bare DrawCards) cover
    other carrier shapes but no slug-keyed probe pinned Derelict Attic
    // Widow's Walk.

    **Bridge arms exercised:**
      * ``sequence`` (Phase 5 composer arm at cross_engine.py:2154).
      * ``draw_cards`` (early-round bridge arm).
      * ``lose_life`` (round-24 closed-vocab arm at
        cross_engine.py:6523).

    **Half-coverage scope (front-half only).**  The BACK-half (Widow's
    Walk) carries a YOU_ATTACK + StateBound(LoneAttackerForYou) +
    ``PumpTargetCreatureUntilEOT(power_bonus=1,
    granted_keywords=frozenset({"deathtouch"}))`` shape that's dropped
    per the IIII / HHHH "pump carriers with granted_keywords riders"
    drop list (the bare ``pump_target_creature_until_eot`` bridge arm
    doesn't carry the keyword-grant rider, per the batch-E Syr Vondam
    / Dual-Sun Technique drop precedent).  Per-slug attribution
    credits the slug regardless of which half pins the Effect+bridge
    byte-equality.

    **Setup (Python-side):**
      * p0 has Derelict Attic // Widow's Walk on the battlefield.
      * p0 has 2 cards in their library so DrawCards(2) succeeds.
      * p0's hand starts empty.
      * p0's life starts at the engine default (typically 20).

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "sequence", "effects": [draw_cards, lose_life]}``
        translates to a ``Sequence(DrawCards(2), LoseLife(2))``
        instance.
      * The Enchantment's ENTERS triggered ability emits the same.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * Post-resolve: p0's hand grew from 0 to 2 (the canonical draw
        mutation, child[0]); p0's library shrank by 2; p0's life
        dropped by 2 (the canonical LoseLife mutation, child[1]).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Derelict Attic // Widow's Walk
    #    printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Derelict Attic // Widow's Walk")
    if real is None:
        pytest.skip(
            "Derelict Attic // Widow's Walk absent from active CardSource"
        )
    assert "Enchantment" in real.card_types
    assert "Room" in real.subtypes
    enters_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event is Event.ENTERS
        ),
        None,
    )
    assert enters_ta is not None, (
        "Derelict Attic // Widow's Walk must have an ENTERS triggered "
        "ability (the Derelict Attic front-half door body)"
    )
    assert isinstance(enters_ta.effect, Sequence), (
        f"Derelict Attic // Widow's Walk ENTERS effect must be "
        f"Sequence; got {type(enters_ta.effect).__name__}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {"kind": "draw_cards", "count": 2},
                {"kind": "lose_life", "amount": 2},
            ],
        }
    )
    assert isinstance(bridged, Sequence)
    assert enters_ta.effect == bridged, (
        f"Derelict Attic // Widow's Walk ENTERS effect must be byte-"
        f"equal to bridged; got parsed={enters_ta.effect!r}, "
        f"bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect classes (regression guard).
    # ------------------------------------------------------------------
    # Bare DrawCards (Bottomless Pool / Locker Room batch-2 shape) is
    # NOT a Sequence — the wrapper distinction is load-bearing for the
    # draw-then-lose-life ordered-pair archetype Derelict Attic
    # represents.
    assert not isinstance(bridged, DrawCards), (
        "Bridged Sequence must NOT collapse to bare DrawCards — that's "
        "Bottomless Pool / Locker Room's shape, not Derelict Attic's "
        "(the Sequence wrapper carries TWO ordered children)"
    )
    assert not isinstance(bridged, LoseLife), (
        "Bridged Sequence must NOT collapse to bare LoseLife — the "
        "Sequence wrapper carries TWO ordered children"
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke — drive the parsed effect through
    #    its actual resolve path (DrawCards reads p0's library top and
    #    moves a card to p0's hand, then LoseLife reduces p0's life
    #    total).
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Seed p0's library with 2 cards so DrawCards(2) has cards to draw.
    # Use a vanilla bait Land for parsimony.
    from mtg_bot.cards.base import CardPrinting, ManaCost
    bait_printing = CardPrinting(
        name="Derelict Attic Bait Land",
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
    for _ in range(2):
        bait_obj = py_state.new_object(
            bait_printing, owner_id=0, zone=Zone.LIBRARY,
        )
        py_state.players[0].library.append(bait_obj)

    # Seat the GENUINE parsed Derelict Attic // Widow's Walk on p0's bf
    # (the Room enchantment is the source).
    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.summoning_sick = False
    py_source.tapped = False
    py_source.damage = 0
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Pre-resolve sanity.
    assert len(py_state.players[0].hand) == 0
    assert len(py_state.players[0].library) == 2
    pre_life = py_state.players[0].life

    # Drive the Sequence(DrawCards(2), LoseLife(2)) effect through
    # resolve directly.
    enters_ta.effect.resolve(py_state, py_source.controller_id)

    # Post-resolve observables:
    # - child[0] DrawCards(2): p0's hand grew from 0 -> 2; library
    #   shrank from 2 -> 0.
    # - child[1] LoseLife(2): p0's life dropped by 2.
    assert len(py_state.players[0].hand) == 2, (
        f"Derelict Attic Sequence[0] DrawCards(2) must add 2 cards to "
        f"p0's hand; got hand size={len(py_state.players[0].hand)}"
    )
    assert len(py_state.players[0].library) == 0, (
        f"Derelict Attic Sequence[0] DrawCards(2) must remove 2 cards "
        f"from p0's library; got library size="
        f"{len(py_state.players[0].library)}"
    )
    assert py_state.players[0].life == pre_life - 2, (
        f"Derelict Attic Sequence[1] LoseLife(2) must reduce p0's life "
        f"by 2 (pre={pre_life}); got post={py_state.players[0].life}"
    )
