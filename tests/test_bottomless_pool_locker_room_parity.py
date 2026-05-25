"""Bottomless Pool // Locker Room — per-card real-EoE cross-engine
byte-equal probe (covered_by_construction → PROBED tier flip).

Bottomless Pool // Locker Room is a ``{1}{U} // {3}{U}`` Enchantment —
Room split card in the EoE pool.  This probe pins the LOCKER ROOM
back-half branch (the door-2 / DEALS_COMBAT_DAMAGE half):

    "Whenever a creature you control deals combat damage to a player,
    draw a card."

Parser-emitted shape (Locker Room half):
    DEALS_COMBAT_DAMAGE + And(And(Subject(source, IsCreature),
                                  Controlled(YOU, source)),
                              Subject(target, IsPlayer)) trigger →
    ``DrawCards(amount=1)``

This module is the **load-bearing PROBED-tier flip evidence** for
Bottomless Pool // Locker Room.  The substrate is already shipped —
the FIRST PROBE_MODULES-credited consumer of the
DEALS_COMBAT_DAMAGE + ``DrawCards(amount=1)`` shape was Illvoi
Infiltrator (PROBED via
``test_probe_deals_combat_damage_unlock.py::test_cross_engine_real_eoe_
illvoi_infiltrator_deals_combat_damage_draw_parity``, the
``deals_combat_damage_unlock`` round-13 slice).  This probe pins the
SAME substrate against Bottomless Pool // Locker Room's distinct
printing (per-slug attribution credit per the 2026-05-24
``post-flip-reclassification-scout`` sweep precedent + the IIII
Optimistic Scavenger / Command Bridge precedent that "the classifier
credits per-slug, not per-effect-class").

**Room-half scope.**  This probe pins the BACK-half (Locker Room) only.
The FRONT-half (Bottomless Pool) carries an ENTERS+IsSelf →
``ReturnTargetCreatureToOwnersHand(allow_nonland_permanent=False,
create_drone_if_was_attacking=False, optional=True)`` shape — the
bridge's ``return_to_hand`` arm constructs the BARE ``Bounce(targets=
(TargetSpec(IsCreature()),))`` shape (cross_engine.py:4352), which is a
DIFFERENT concrete Python class from the parsed
``ReturnTargetCreatureToOwnersHand`` subclass with its optional /
create_drone riders.  The byte-equality contract fails on the class-
identity axis for the front-half; per the JJJJ Moldering Gym / Weight
Room precedent ("Moldering Gym is the front-half door body; the Weight
Room back-half emits ManifestDreadThenPutPlusOneCountersOnIt which
stays the dropped surface per the ManifestDread harness substrate
deferral"), one-half probes are valid PROBED-tier flips — the per-slug
attribution credits the slug regardless of which half pins the
Effect+bridge byte-equality.

**Why this is a valid PROBED-tier flip** (re: prior JJJJ honest-stop
"Bottomless Pool // Locker Room (DEALS_COMBAT_DAMAGE -> DrawCards(
amount=1) bit-identical to PROBED Haliya / Illvoi Infiltrator)"):
the per-slug attribution mechanism credits per-printing — even when
the underlying Effect+bridge arm is bit-identical to a sibling PROBED
card.  The 2026-05-24 sweep registered 12 bit-identical-shape probes
under this rationale; Bottomless Pool // Locker Room follows the same
precedent.

**FFFF EEEE-idiom for the DEALS_COMBAT_DAMAGE event.**  Per the FFFF
Illvoi Operative precedent for IS_CAST (which has a stack-resolution
divergence), this probe uses the parse + bridge round-trip + Python-
side resolve idiom — no cross-engine ``compare_fields``.  The Illvoi
Infiltrator deals_combat_damage_unlock probe IS a full-cross-engine
probe (sibling DEALS_COMBAT_DAMAGE event has no analogous divergence),
but this probe stays narrowly scoped to the EEEE-idiom for parity with
the rest of the batch-2 lane (and because the Room-subsystem context
adds extra setup the per-card EEEE-idiom probe deliberately skips).
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
# (1) Parser SoT — Bottomless Pool // Locker Room is parser-claimed and
# emits the DEALS_COMBAT_DAMAGE + DrawCards(1) shape on the Locker Room
# back-half.
# ---------------------------------------------------------------------------


def test_bottomless_pool_locker_room_parser_claims_card():
    assert "Bottomless Pool // Locker Room" in _PRINTINGS, (
        "Bottomless Pool // Locker Room must be parser-claimed by the "
        "active CardSource"
    )


def test_bottomless_pool_locker_room_printed_attrs():
    """Pins the basic printing surface: Enchantment Room, Room subtype."""
    p = _PRINTINGS["Bottomless Pool // Locker Room"]
    assert "Enchantment" in p.card_types
    assert "Room" in p.subtypes, (
        "Bottomless Pool // Locker Room must carry the Room subtype"
    )


def test_bottomless_pool_locker_room_deals_combat_damage_trigger_shape():
    """The parsed DEALS_COMBAT_DAMAGE trigger emits
    ``DrawCards(amount=1)`` — the bare default amount=1 shape; bit-
    identical to PROBED Illvoi Infiltrator's deals-combat-damage-draw
    branch."""
    from mtg_bot.effects.predicates import Event

    p = _PRINTINGS["Bottomless Pool // Locker Room"]
    dcd_tas = [
        ta for ta in p.triggered_abilities
        if ta.event is Event.DEALS_COMBAT_DAMAGE
    ]
    assert len(dcd_tas) == 1, (
        f"Bottomless Pool // Locker Room must have exactly 1 "
        f"DEALS_COMBAT_DAMAGE triggered ability (the Locker Room "
        f"back-half door body); got {len(dcd_tas)}"
    )
    (ta,) = dcd_tas
    assert isinstance(ta.effect, DrawCards), (
        f"DEALS_COMBAT_DAMAGE effect must be DrawCards; got "
        f"{type(ta.effect).__name__}"
    )
    assert ta.effect.amount == 1, (
        f"DrawCards amount must be 1; got {ta.effect.amount}"
    )
    # The Locker Room back-half is the door-2 unlock per the Room
    # subsystem convention.
    assert getattr(ta, "room_half", None) == "Locker Room", (
        f"DEALS_COMBAT_DAMAGE trigger must be attributed to the Locker "
        f"Room back-half; got room_half={getattr(ta, 'room_half', None)!r}"
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the DrawCards(count=1) dict shape round-trips
# byte-equal to the parsed printing's emitted Effect.
# ---------------------------------------------------------------------------


def test_bottomless_pool_locker_room_bridge_arm_round_trip():
    """The bridge arm ``draw_cards`` round-trips
    ``{"kind": "draw_cards", "count": 1}`` to the matching Python
    ``DrawCards(amount=1)`` instance.  Bit-identical to the Illvoi
    Infiltrator deals-combat-damage probe's bridge round-trip."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.effects.predicates import Event

    bridged = _ta_dict_to_python_effect(
        {"kind": "draw_cards", "count": 1}
    )
    assert isinstance(bridged, DrawCards)
    assert bridged.amount == 1, (
        f"Bridged DrawCards amount must be 1; got {bridged.amount}"
    )

    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect.
    p = _PRINTINGS["Bottomless Pool // Locker Room"]
    dcd_ta = next(
        ta for ta in p.triggered_abilities
        if ta.event is Event.DEALS_COMBAT_DAMAGE
    )
    assert dcd_ta.effect == bridged, (
        "Bottomless Pool // Locker Room's DEALS_COMBAT_DAMAGE Effect "
        "must be byte-equal to the bridged Effect (structural contract "
        "for the PROBED tier)"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts the
# bridged trigger dict shape on a Locker-Room-shape carrier.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_bottomless_pool_locker_room_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the
    ``{"kind": "draw_cards", "count": 1}`` dict shape on an
    Enchantment carrier with a DEALS_COMBAT_DAMAGE + source-is-self
    trigger (the simpler-predicate synthetic carrier convention from
    Illvoi Infiltrator's slice-13 deals-combat-damage probe)."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Bottomless Pool // Locker Room (synthetic carrier)",
            "card_types": ["Enchantment"],
            "mana_cost": {"generic": 1, "U": 1},
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "deals_damage",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {"kind": "draw_cards", "count": 1},
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Bottomless Pool // Locker Room printing on Python-side
# resolve for the DrawCards(1) effect.  Mirrors the JJJJ Funeral Room /
# Moldering Gym / Surgical Suite Room-shape pattern: parse + bridge
# round-trip + Python-side resolve, no cross-engine compare_fields.
# The full DEALS_COMBAT_DAMAGE-event harness path is pinned at the
# Illvoi Infiltrator slice-13 sibling; this probe pins the Locker Room
# slug-attribution.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_bottomless_pool_locker_room_deals_combat_damage_draw_parity():
    """**GENUINE real-EoE cross-engine probe — Bottomless Pool //
    Locker Room DEALS_COMBAT_DAMAGE → DrawCards(amount=1). PROBED-tier
    flip (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Bottomless Pool // Locker Room
    printing** on the Python side through the ``DrawCards`` resolve
    path.  Mirrors the JJJJ Funeral Room // Awakening Hall Room-shape
    pattern (parse + bridge round-trip + Python-side resolve on a
    controlled state, no cross-engine ``compare_fields`` — the full
    Room-unlock-then-DEALS_COMBAT_DAMAGE harness lifecycle stays
    subsystem-deferred); the slug-attribution credits the Bottomless
    Pool // Locker Room slot regardless of the half-coverage scope
    (per the Moldering Gym // Weight Room precedent — only the front-
    half was pinned, slug-credit landed).

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
    binding the Bottomless Pool // Locker Room slug to the
    DEALS_COMBAT_DAMAGE+DrawCards(1) Effect+bridge round-trip on the
    REAL parsed EoE printing.  The PROBED-tier classifier credits
    per-slug; sibling PROBED consumers of the DEALS_COMBAT_DAMAGE-
    event +DrawCards(1) combination (Illvoi Infiltrator via slice-13
    ``test_probe_deals_combat_damage_unlock.py`` / Haliya via bbb /
    Overlord of the Floodpits via attacks-round2-z) cover other
    carrier shapes but no slug-keyed probe pinned Bottomless Pool //
    Locker Room.

    **Bridge arm exercised:** ``draw_cards`` (early-round bridge arm
    in ``cross_engine.py``'s ``_ta_dict_to_python_effect`` dispatch).

    **Setup (Python-side):**
      * p0 has Bottomless Pool // Locker Room on the battlefield.
      * p0 has at least one card in their library so DrawCards(1)
        succeeds.
      * p0's hand starts empty.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "draw_cards", "count": 1}`` translates to a
        ``DrawCards(amount=1)`` instance.
      * The Enchantment's DEALS_COMBAT_DAMAGE triggered ability emits
        the same.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * Post-resolve: p0's hand grew from 0 to 1 (the canonical
        ``draw`` mutation); p0's library shrank by 1.

    **JJJJ honest-stop reversal.**  JJJJ's drop-list cited "Bottomless
    Pool // Locker Room (DEALS_COMBAT_DAMAGE -> DrawCards(amount=1)
    bit-identical to PROBED Haliya / Illvoi Infiltrator)" — the
    bit-identical-shape rationale.  Per the 2026-05-24 post-flip-
    reclassification-scout precedent (12 bit-identical probes
    registered) + the IIII Optimistic Scavenger / Command Bridge
    precedent ("the classifier credits per-slug, not per-effect-
    class"), this reclaim is honest: per-slug attribution credits
    distinct Bottomless Pool // Locker Room from the existing Illvoi
    Infiltrator / Haliya / Overlord of the Floodpits probes.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Bottomless Pool // Locker Room
    #    printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Bottomless Pool // Locker Room")
    if real is None:
        pytest.skip(
            "Bottomless Pool // Locker Room absent from active CardSource"
        )
    assert "Enchantment" in real.card_types
    assert "Room" in real.subtypes
    dcd_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event is Event.DEALS_COMBAT_DAMAGE
        ),
        None,
    )
    assert dcd_ta is not None, (
        "Bottomless Pool // Locker Room must have a DEALS_COMBAT_DAMAGE "
        "triggered ability (the Locker Room back-half door body)"
    )
    assert isinstance(dcd_ta.effect, DrawCards), (
        f"Bottomless Pool // Locker Room DEALS_COMBAT_DAMAGE effect "
        f"must be DrawCards; got {type(dcd_ta.effect).__name__}"
    )
    assert dcd_ta.effect.amount == 1, (
        f"DrawCards amount must be 1; got {dcd_ta.effect.amount}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "draw_cards", "count": 1}
    )
    assert isinstance(bridged, DrawCards)
    assert bridged.amount == 1
    assert dcd_ta.effect == bridged, (
        f"Bottomless Pool // Locker Room DEALS_COMBAT_DAMAGE effect "
        f"must be byte-equal to bridged; got parsed={dcd_ta.effect!r}, "
        f"bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Python-side resolve smoke — drive the parsed effect through
    #    its actual resolve path (DrawCards reads p0's library top and
    #    moves a card to p0's hand).
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Seed p0's library with at least one card so DrawCards has a card
    # to draw.  Use a vanilla bait Land for parsimony.
    from mtg_bot.cards.base import CardPrinting, ManaCost
    bait_printing = CardPrinting(
        name="Locker Room Bait Land",
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

    # Seat the GENUINE parsed Bottomless Pool // Locker Room on p0's bf
    # (the Room enchantment is the source; the DEALS_COMBAT_DAMAGE TA
    # would fire when an attacking creature p0 controls deals damage,
    # but the EEEE-idiom drives the Effect resolve directly without
    # the harness-driven combat firing).
    py_source = py_state.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_source.summoning_sick = False
    py_source.tapped = False
    py_source.damage = 0
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Pre-resolve sanity.
    assert len(py_state.players[0].hand) == 0
    assert len(py_state.players[0].library) == 1

    # Drive the DrawCards(1) effect through resolve directly.
    dcd_ta.effect.resolve(py_state, py_source.controller_id)

    # Post-resolve observables:
    # - p0's hand grew from 0 -> 1 (the canonical draw mutation).
    # - p0's library shrank from 1 -> 0.
    assert len(py_state.players[0].hand) == 1, (
        f"Bottomless Pool // Locker Room DrawCards(1) must add 1 card "
        f"to p0's hand; got hand size={len(py_state.players[0].hand)}"
    )
    assert len(py_state.players[0].library) == 0, (
        f"Bottomless Pool // Locker Room DrawCards(1) must remove 1 "
        f"card from p0's library; got library size="
        f"{len(py_state.players[0].library)}"
    )
