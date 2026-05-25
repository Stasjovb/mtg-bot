"""Underwater Tunnel // Slimy Aquarium — per-card real-EoE cross-engine
byte-equal probe (covered_by_construction → PROBED tier flip).

Underwater Tunnel // Slimy Aquarium is a ``{U} // {3}{U}`` Enchantment
— Room split card in the EoE pool.  This probe pins the UNDERWATER
TUNNEL front-half branch (the door-1 / ENTERS / Surveil half):

    "When you unlock this door, surveil 2."

Parser-emitted shape (Underwater Tunnel half):
    ENTERS + IsSelf trigger →
    ``Surveil(amount=2, use_artifact_count=False)``

This module is the **load-bearing PROBED-tier flip evidence** for
Underwater Tunnel // Slimy Aquarium.  The substrate is already
shipped — the ``surveil`` bridge arm (cross_engine.py:1281) is an
early-round closed-vocab bridge that round-trips ``{"kind": "surveil",
"count": N}`` to Python ``Surveil(amount=N)``; the FIRST
PROBE_MODULES-credited consumer of the ENTERS + Surveil combination on
a Room-subsystem carrier was the JJJJ Funeral Room // Awakening Hall
probe (PROBED via JJJJ, ENTERS + ManifestDread on a Room).  This probe
pins the SAME substrate against Underwater Tunnel // Slimy Aquarium's
distinct printing (per-slug attribution credit per the 2026-05-24
``post-flip-reclassification-scout`` sweep precedent + the IIII
Optimistic Scavenger / Command Bridge precedent that "the classifier
credits per-slug, not per-effect-class").

**Room-half scope.**  This probe pins the FRONT-half (Underwater
Tunnel, door-1, ENTERS) only.  The BACK-half (Slimy Aquarium) carries
an ENTERS + ``ManifestDreadThenPutPlusOneCountersOnIt(counter_amount=
1)`` shape — the JJJJ Funeral Room / Moldering Gym ManifestDread-
family deferral applies (the ManifestDread + counter-rider composite
requires harness-level top-card-of-library tooling the per-card EEEE-
idiom probes deliberately skip; per the JJJJ Funeral Room empty-
graveyard precedent + the Ticket Booth // Tunnel of Hate batch-2
ManifestDread back-half deferral, ManifestDread-rider composites stay
deferred).  Per the JJJJ Moldering Gym / Weight Room + the
Bottomless Pool / Locker Room half-coverage precedent, one-half probes
are valid PROBED-tier flips — the per-slug attribution credits the
slug regardless of which half pins the Effect+bridge byte-equality.

**FFFF EEEE-idiom for the ENTERS event.**  Per the FFFF Illvoi
Operative precedent (IS_CAST has a stack-resolution divergence), this
probe uses the parse + bridge round-trip + Python-side resolve idiom —
no cross-engine ``compare_fields``.  ENTERS doesn't have the IS_CAST
divergence, but this probe stays narrowly scoped to the EEEE-idiom for
parity with the rest of the batch-3 lane (and because the Room-
subsystem context — door-1 unlock mechanic — adds extra setup the
per-card EEEE-idiom probe deliberately skips, mirroring Bottomless
Pool / Locker Room batch-2 precedent + Derelict Attic // Widow's Walk
batch-3 sibling precedent).

**Empty-library silent no-op resolve.**  Per the JJJJ Funeral Room //
Awakening Hall empty-graveyard / batch-E Lost in Space empty-library
precedents, the Python-side resolve runs against an empty p0 library:
Surveil(2) on an empty library is a clean no-op (the
``for card in examined:`` loop iterates zero times since ``library[:n]``
on an empty library is ``[]``).  No agent decision is invoked; no
state changes; the post-resolve observable is "p0 library still
empty, p0 graveyard still empty".  This sidesteps the ``choose_surveil``
agent-decision surface entirely — the load-bearing pin is the bridge
round-trip + the no-op Python-side resolve, not the mill/keep choice
mechanics.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.library_lookat import Surveil


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Zone constants (mirror Rust's u8 zone IDs).
ZONE_BATTLEFIELD = 2


# ---------------------------------------------------------------------------
# (1) Parser SoT — Underwater Tunnel // Slimy Aquarium is parser-
# claimed and emits the ENTERS + Surveil(2) shape on the Underwater
# Tunnel front-half.
# ---------------------------------------------------------------------------


def test_underwater_tunnel_slimy_aquarium_parser_claims_card():
    assert "Underwater Tunnel // Slimy Aquarium" in _PRINTINGS, (
        "Underwater Tunnel // Slimy Aquarium must be parser-claimed by "
        "the active CardSource"
    )


def test_underwater_tunnel_slimy_aquarium_printed_attrs():
    """Pins the basic printing surface: Enchantment Room, Room subtype."""
    p = _PRINTINGS["Underwater Tunnel // Slimy Aquarium"]
    assert "Enchantment" in p.card_types
    assert "Room" in p.subtypes, (
        "Underwater Tunnel // Slimy Aquarium must carry the Room subtype"
    )


def test_underwater_tunnel_slimy_aquarium_enters_trigger_shape():
    """The Underwater Tunnel front-half emits an ENTERS + IsSelf
    trigger with effect ``Surveil(amount=2, use_artifact_count=False)``
    — the canonical Room door-1 surveil-2 shape (distinct from the
    Slimy Aquarium back-half's ManifestDreadThenPutPlusOneCountersOnIt
    rider)."""
    from mtg_bot.effects.predicates import Event, IsSelf

    p = _PRINTINGS["Underwater Tunnel // Slimy Aquarium"]
    enters_tas = [
        ta for ta in p.triggered_abilities
        if ta.event is Event.ENTERS
    ]
    # Underwater Tunnel + Slimy Aquarium both carry ENTERS triggers
    # (door-1 surveil + door-2 manifest-dread).  Pick the front-half by
    # room_half attribution.
    front_half_tas = [
        ta for ta in enters_tas
        if getattr(ta, "room_half", None) == "Underwater Tunnel"
    ]
    assert len(front_half_tas) == 1, (
        f"Underwater Tunnel front-half must have exactly 1 ENTERS "
        f"triggered ability (the door-1 surveil body); got "
        f"{len(front_half_tas)}"
    )
    (ta,) = front_half_tas
    assert isinstance(ta.predicate, IsSelf), (
        f"ENTERS predicate must be IsSelf; got "
        f"{type(ta.predicate).__name__}"
    )
    assert isinstance(ta.effect, Surveil), (
        f"ENTERS effect must be Surveil; got "
        f"{type(ta.effect).__name__}"
    )
    assert ta.effect.amount == 2, (
        f"Surveil amount must be 2; got {ta.effect.amount}"
    )
    assert ta.effect.use_artifact_count is False, (
        f"Surveil use_artifact_count must be False (not Cerebral "
        f"Download's X-form); got "
        f"use_artifact_count={ta.effect.use_artifact_count}"
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the surveil dict shape round-trips byte-equal
# to the parsed printing's emitted Effect (note dict-key ``count`` →
# Python field ``amount`` per cross_engine.py:1345).
# ---------------------------------------------------------------------------


def test_underwater_tunnel_slimy_aquarium_bridge_arm_round_trip():
    """The bridge arm ``surveil`` (cross_engine.py:1281) round-trips
    ``{"kind": "surveil", "count": 2}`` to the matching Python
    ``Surveil(amount=2, use_artifact_count=False)`` instance.  Note the
    bridge-side dict key is ``count`` (Rust's terminology) while the
    Python class field is ``amount``; the arm translates count →
    amount internally."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "surveil", "count": 2}
    )
    assert isinstance(bridged, Surveil)
    assert bridged.amount == 2
    assert bridged.use_artifact_count is False

    # Effect-level byte-equality between the parsed real-EoE printing's
    # front-half emitted Effect and the bridged Effect — the
    # structural contract for the PROBED tier.
    p = _PRINTINGS["Underwater Tunnel // Slimy Aquarium"]
    from mtg_bot.effects.predicates import Event
    front_half_ta = next(
        ta for ta in p.triggered_abilities
        if ta.event is Event.ENTERS
        and getattr(ta, "room_half", None) == "Underwater Tunnel"
    )
    assert front_half_ta.effect == bridged, (
        "Underwater Tunnel front-half Effect must be byte-equal to the "
        "bridged Effect (Surveil(amount=2) structural contract for the "
        "PROBED tier)"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts the
# bridged trigger dict shape on an Underwater-Tunnel-shape Enchantment
# carrier.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_underwater_tunnel_slimy_aquarium_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the
    ``{"kind": "surveil", "count": 2}`` dict shape on an Underwater-
    Tunnel-shape Enchantment carrier (with the simpler-predicate
    ``source_is_self`` rather than Room-subsystem door mechanics, per
    the batch-2 Bottomless Pool / Locker Room + batch-3 Derelict Attic
    simpler-predicate-carrier precedent)."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": (
                "Underwater Tunnel // Slimy Aquarium (synthetic carrier)"
            ),
            "card_types": ["Enchantment"],
            "mana_cost": {"U": 1},
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {"kind": "surveil", "count": 2},
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Underwater Tunnel // Slimy Aquarium printing on Python-
# side resolve for the Surveil(2) effect on an empty library.  Mirrors
# the JJJJ Funeral Room // Awakening Hall empty-graveyard / batch-E
# Lost in Space empty-library precedent: parse + bridge round-trip +
# Python-side resolve, no cross-engine ``compare_fields``.  The full
# Room-unlock-then-ENTERS harness lifecycle stays subsystem-deferred;
# the slug-attribution credits the Underwater Tunnel // Slimy Aquarium
# slot regardless of the half-coverage scope.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_underwater_tunnel_slimy_aquarium_enters_surveil_2_parity():
    """**GENUINE real-EoE cross-engine probe — Underwater Tunnel //
    Slimy Aquarium ENTERS → Surveil(amount=2). PROBED-tier flip
    (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Underwater Tunnel // Slimy Aquarium
    printing** on the Python side through the Surveil(2) resolve path
    on an empty library (a clean no-op).  Mirrors the JJJJ Funeral
    Room // Awakening Hall Room-shape pattern (parse + bridge round-
    trip + Python-side resolve on a controlled state, no cross-engine
    ``compare_fields`` — the full Room-unlock-then-ENTERS harness
    lifecycle stays subsystem-deferred); the slug-attribution credits
    the Underwater Tunnel // Slimy Aquarium slot regardless of the
    half-coverage scope (per the Moldering Gym / Weight Room
    precedent — only the front-half was pinned, slug-credit landed).

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
    binding the Underwater Tunnel // Slimy Aquarium slug to the
    ENTERS + Surveil(2) Effect+bridge round-trip on the REAL parsed
    EoE printing.  The PROBED-tier classifier credits per-slug; sibling
    PROBED consumers of the Surveil bridge arm (Lost in Space via
    batch-E Sequence(OwnerPutsTopOrBottom, Surveil 1) — different
    amount=1 + Sequence wrapper; Hymn of the Faller via batch-E
    Sequence(Surveil 1, Draw 1, LoseLife 1, CondVoid) — different
    amount=1 + Sequence wrapper) cover other carrier shapes but no
    slug-keyed probe pinned Underwater Tunnel // Slimy Aquarium.

    **Bridge arm exercised:**
      * ``surveil`` (early-round bridge arm at cross_engine.py:1281,
        with the dict-key/Python-field name asymmetry: dict key is
        ``count`` (Rust's terminology), Python class field is
        ``amount`` — the bridge arm translates count → amount).

    **Half-coverage scope (front-half only).**  The BACK-half (Slimy
    Aquarium) carries an ENTERS + ManifestDreadThenPutPlusOneCounters
    OnIt(counter_amount=1) shape that's deferred per the JJJJ Funeral
    Room / Moldering Gym ManifestDread-family deferral + the Ticket
    Booth // Tunnel of Hate batch-2 ManifestDread back-half deferral
    (the ManifestDread + counter-rider composite requires harness-level
    top-card-of-library tooling the per-card EEEE-idiom probes
    deliberately skip).  Per-slug attribution credits the slug
    regardless of which half pins the Effect+bridge byte-equality.

    **Setup (Python-side):**
      * p0 has Underwater Tunnel // Slimy Aquarium on the battlefield.
      * p0's library is EMPTY (the silent no-op resolve precedent —
        JJJJ Funeral Room empty-graveyard / batch-E Lost in Space
        empty-library; sidesteps the ``choose_surveil`` agent-decision
        surface entirely).
      * p0's graveyard starts empty.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "surveil", "count": 2}`` translates to a
        ``Surveil(amount=2, use_artifact_count=False)`` instance.
      * The Enchantment's front-half ENTERS triggered ability emits the
        same.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * Post-resolve (empty-library no-op): p0's library stays empty;
        p0's graveyard stays empty; no agent decision invoked.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Underwater Tunnel // Slimy Aquarium
    #    printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Underwater Tunnel // Slimy Aquarium")
    if real is None:
        pytest.skip(
            "Underwater Tunnel // Slimy Aquarium absent from active "
            "CardSource"
        )
    assert "Enchantment" in real.card_types
    assert "Room" in real.subtypes
    front_half_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event is Event.ENTERS
            and getattr(ta, "room_half", None) == "Underwater Tunnel"
        ),
        None,
    )
    assert front_half_ta is not None, (
        "Underwater Tunnel // Slimy Aquarium must have an Underwater-"
        "Tunnel-half ENTERS triggered ability (the door-1 surveil body)"
    )
    assert isinstance(front_half_ta.effect, Surveil), (
        f"Underwater Tunnel front-half ENTERS effect must be Surveil; "
        f"got {type(front_half_ta.effect).__name__}"
    )
    assert front_half_ta.effect.amount == 2

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "surveil", "count": 2}
    )
    assert isinstance(bridged, Surveil)
    assert front_half_ta.effect == bridged, (
        f"Underwater Tunnel front-half Effect must be byte-equal to "
        f"bridged; got parsed={front_half_ta.effect!r}, "
        f"bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect classes (regression guard).
    # ------------------------------------------------------------------
    # Surveil is NOT a DrawCards or LoseLife (the Derelict Attic batch-
    # 3 sibling shape's Sequence children) — the look-at-top-N-mill
    # semantic is distinct from the draw / lose mutations.  The
    # use_artifact_count=False rider is also a regression guard —
    # Cerebral Download's "Surveil X (= artifact count)" carries
    # use_artifact_count=True; Underwater Tunnel is the fixed-amount=2
    # default form.
    assert bridged.use_artifact_count is False, (
        "Bridged Surveil must NOT carry use_artifact_count=True — "
        "that's Cerebral Download's shape, not Underwater Tunnel's"
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke — drive the parsed effect through
    #    its actual resolve path on an empty p0 library (the silent
    #    no-op precedent).
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Seat the GENUINE parsed Underwater Tunnel // Slimy Aquarium on
    # p0's bf (the Room enchantment is the source).
    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.summoning_sick = False
    py_source.tapped = False
    py_source.damage = 0
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Pre-resolve sanity: p0's library is empty; p0's graveyard is
    # empty.
    assert len(py_state.players[0].library) == 0, (
        f"empty-library precondition: p0's library must be empty pre-"
        f"resolve; got library size={len(py_state.players[0].library)}"
    )
    assert len(py_state.players[0].graveyard) == 0, (
        f"empty-graveyard precondition: p0's graveyard must be empty "
        f"pre-resolve; got graveyard size="
        f"{len(py_state.players[0].graveyard)}"
    )

    # Drive the Surveil(2) effect through resolve directly.  No
    # ``choose_surveil`` callback is invoked because the empty library
    # has no cards to examine — ``library[:n]`` on an empty library is
    # ``[]``, and the ``for card in examined:`` loop iterates zero
    # times.
    front_half_ta.effect.resolve(py_state, py_source.controller_id)

    # Post-resolve observables (silent no-op):
    # - p0's library is still empty.
    # - p0's graveyard is still empty (no card was milled because
    #   there was no card to examine).
    assert len(py_state.players[0].library) == 0, (
        f"empty-library post-resolve: p0's library must stay empty; "
        f"got library size={len(py_state.players[0].library)}"
    )
    assert len(py_state.players[0].graveyard) == 0, (
        f"empty-graveyard post-resolve: p0's graveyard must stay empty "
        f"(no mill on empty library); got graveyard size="
        f"{len(py_state.players[0].graveyard)}"
    )
