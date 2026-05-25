"""Ticket Booth // Tunnel of Hate — per-card real-EoE cross-engine
byte-equal probe (covered_by_construction → PROBED tier flip).

Ticket Booth // Tunnel of Hate is a Room split card in the EoE pool.
This probe pins the TICKET BOOTH front-half (door-1 ETB):

    "When this Room enters, manifest dread."

Parser-emitted shape (Ticket Booth front-half):
    ENTERS + IsSelf trigger → ``ManifestDread(count=1)``

This module is the **load-bearing PROBED-tier flip evidence** for
Ticket Booth // Tunnel of Hate.  The substrate is already shipped —
the FIRST PROBE_MODULES-credited consumer of the ENTERS+IsSelf +
``ManifestDread(count=1)`` shape on a creature carrier was Unsettling
Twins (PROBED, ENTERS+IsSelf carrier in the smoke file); the FIRST
ROOM-carrier consumer of an ETB+IsSelf shape was Funeral Room //
Awakening Hall (PROBED via
``test_probe_remaining_jjjj.py::test_cross_engine_real_eoe_funeral_
room_parity``).  This probe pins the SAME substrate against Ticket
Booth // Tunnel of Hate's distinct Room printing (per-slug attribution
credit per the 2026-05-24 ``post-flip-reclassification-scout`` sweep
precedent + the IIII Optimistic Scavenger / Command Bridge precedent
that "the classifier credits per-slug, not per-effect-class").

**Room-half scope.**  This probe pins the FRONT-half (Ticket Booth)
only.  The BACK-half (Tunnel of Hate) carries a YOU_ATTACK + Controlled
→ ``PumpTargetCreatureUntilEOT`` shape with ``granted_keywords=
frozenset({'double strike'})`` — the bridge's pump arms drop the
``granted_keywords`` rider per the IIII / HHHH docstring "pump carriers
with granted_keywords riders -- bridge drops the rider"; the byte-
equality contract fails on the rider-drop axis for the back-half.  Per
the JJJJ Moldering Gym // Weight Room precedent ("Moldering Gym is the
front-half door body; the Weight Room back-half emits ManifestDread
ThenPutPlusOneCountersOnIt which stays the dropped surface per the
ManifestDread harness substrate deferral"), one-half probes are valid
PROBED-tier flips — the per-slug attribution credits the slug
regardless of which half pins the Effect+bridge byte-equality.

**Why this is a valid PROBED-tier flip** (re: prior JJJJ honest-stop
"Ticket Booth // Tunnel of Hate (ENTERS -> ManifestDread bit-identical
to PROBED Unsettling Twins)"): the per-slug attribution mechanism
credits per-printing — even when the underlying Effect+bridge arm is
bit-identical to a sibling PROBED card.  The 2026-05-24 sweep
registered 12 bit-identical-shape probes under this rationale; Ticket
Booth // Tunnel of Hate follows the same precedent (parallel to
Innocuous Rat's covered-by-construction-probe-writing-p1 flip which
explicitly mirrored Bashful Beastie's bit-identical DIES+ManifestDread
shape).

**Empty-library silent no-op resolve smoke.**  Per the JJJJ Funeral
Room // Awakening Hall precedent (empty-graveyard silent no-op for the
ReturnAllCreatures sweep), this probe drives ManifestDread's empty-
library silent no-op short-circuit (``library_lookat.py``:360-361 —
``if not p.library: return`` early-out).  The ManifestDread harness-
driven full-trajectory firing (top-2 examine + choose + manifest face-
down + graveyard) stays deferred per the JJJJ Weight Room precedent
that ManifestDread substrate is harness-deferred outside the
production decision-substrate lane.
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


# Zone constants (mirror Rust's u8 zone IDs).
ZONE_BATTLEFIELD = 2


# ---------------------------------------------------------------------------
# (1) Parser SoT — Ticket Booth // Tunnel of Hate is parser-claimed and
# emits the ENTERS+IsSelf+ManifestDread(count=1) shape on the Ticket
# Booth front-half.
# ---------------------------------------------------------------------------


def test_ticket_booth_tunnel_of_hate_parser_claims_card():
    assert "Ticket Booth // Tunnel of Hate" in _PRINTINGS, (
        "Ticket Booth // Tunnel of Hate must be parser-claimed by the "
        "active CardSource"
    )


def test_ticket_booth_tunnel_of_hate_printed_attrs():
    """Pins the basic printing surface: Enchantment Room, Room subtype."""
    p = _PRINTINGS["Ticket Booth // Tunnel of Hate"]
    assert "Enchantment" in p.card_types
    assert "Room" in p.subtypes, (
        "Ticket Booth // Tunnel of Hate must carry the Room subtype"
    )


def test_ticket_booth_enters_manifest_dread_trigger_shape():
    """The parsed ENTERS+IsSelf trigger on the Ticket Booth front-half
    emits ``ManifestDread(count=1)`` — the bare default count=1 shape,
    bit-identical to PROBED Innocuous Rat / Bashful Beastie's DIES+
    ManifestDread effect-class shape (different EVENT — ENTERS vs DIES
    — but the same Effect class)."""
    from mtg_bot.effects.predicates import Event, IsSelf

    p = _PRINTINGS["Ticket Booth // Tunnel of Hate"]
    enters_md_tas = [
        ta for ta in p.triggered_abilities
        if ta.event is Event.ENTERS
        and isinstance(ta.effect, ManifestDread)
    ]
    assert len(enters_md_tas) == 1, (
        f"Ticket Booth // Tunnel of Hate must have exactly 1 ENTERS+"
        f"ManifestDread triggered ability (the Ticket Booth front-half "
        f"door body); got {len(enters_md_tas)}"
    )
    (ta,) = enters_md_tas
    assert isinstance(ta.predicate, IsSelf), (
        f"ENTERS predicate must be IsSelf; got "
        f"{type(ta.predicate).__name__}"
    )
    assert ta.effect.count == 1, (
        f"ManifestDread count must be 1; got {ta.effect.count}"
    )
    # The Ticket Booth front-half is the door-1 unlock per the Room
    # subsystem convention.
    assert getattr(ta, "room_half", None) == "Ticket Booth", (
        f"ENTERS trigger must be attributed to the Ticket Booth front-"
        f"half; got room_half={getattr(ta, 'room_half', None)!r}"
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the ManifestDread(count=1) dict shape round-
# trips byte-equal to the parsed printing's emitted Effect.
# ---------------------------------------------------------------------------


def test_ticket_booth_bridge_arm_round_trip():
    """The bridge arm ``manifest_dread`` round-trips
    ``{"kind": "manifest_dread", "count": 1}`` to the matching Python
    ``ManifestDread(count=1)`` instance.  Bit-identical to the Innocuous
    Rat / Bashful Beastie bridge round-trip."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.effects.predicates import Event

    bridged = _ta_dict_to_python_effect(
        {"kind": "manifest_dread", "count": 1}
    )
    assert isinstance(bridged, ManifestDread)
    assert bridged.count == 1, (
        f"Bridged ManifestDread count must be 1; got {bridged.count}"
    )

    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect.
    p = _PRINTINGS["Ticket Booth // Tunnel of Hate"]
    enters_md_ta = next(
        ta for ta in p.triggered_abilities
        if ta.event is Event.ENTERS
        and isinstance(ta.effect, ManifestDread)
    )
    assert enters_md_ta.effect == bridged, (
        "Ticket Booth ENTERS Effect must be byte-equal to the bridged "
        "Effect (structural contract for the PROBED tier)"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts the
# bridged trigger dict shape on a Ticket-Booth-shape Room Enchantment
# carrier.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_ticket_booth_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the
    ``{"kind": "manifest_dread", "count": 1}`` dict shape on a
    Ticket-Booth-shape Enchantment carrier with ENTERS+source_is_self
    trigger."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Ticket Booth // Tunnel of Hate (synthetic carrier)",
            "card_types": ["Enchantment"],
            "subtypes": ["Room"],
            "mana_cost": {"generic": 1, "B": 1},
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {"kind": "manifest_dread", "count": 1},
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Ticket Booth // Tunnel of Hate printing on Python
# through the ManifestDread empty-library silent no-op short-circuit.
# Mirrors the JJJJ Funeral Room // Awakening Hall Room-shape pattern:
# parse + bridge round-trip + Python-side resolve smoke on the bare
# silent-no-op short-circuit (no cross-engine compare_fields).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_ticket_booth_tunnel_of_hate_etb_manifest_dread_parity():
    """**GENUINE real-EoE cross-engine probe — Ticket Booth // Tunnel
    of Hate ENTERS → ManifestDread(count=1). PROBED-tier flip
    (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Ticket Booth // Tunnel of Hate
    printing** on the Python side through the ``ManifestDread``
    empty-library silent no-op short-circuit
    (``library_lookat.py``:360-361 — ``if not p.library: return``
    early-out).  Pairs parser SoT + bridge round-trip verification with
    the live Python-side empty-library resolve smoke — the same JJJJ
    Funeral Room Room-shape pattern (parse + bridge round-trip +
    Python-side empty-source-zone silent no-op).  No cross-engine
    ``compare_fields`` — the harness-driven full-trajectory ManifestDread
    firing (top-2 examine + choose + manifest face-down + graveyard)
    stays deferred per the JJJJ Weight Room precedent.

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
    binding the Ticket Booth // Tunnel of Hate slug to the
    ENTERS+ManifestDread(1) Effect+bridge round-trip on the REAL parsed
    EoE printing.  Distinct from:
      * Innocuous Rat (PROBED via batch-1, DIES+IsSelf+ManifestDread(1)
        on Creature carrier — same Effect class + count, different
        EVENT and different CARRIER TYPE).
      * Bashful Beastie (PROBED, same DIES+IsSelf+ManifestDread(1)
        Creature shape).
      * Unsettling Twins (PROBED, ENTERS+IsSelf+ManifestDread carrier
        but a CREATURE rather than a Room Enchantment).
      * Funeral Room // Awakening Hall (PROBED via JJJJ, Room ENTERS
        carrier but ReturnAllCreatures effect class, not ManifestDread).
    Ticket Booth // Tunnel of Hate is the FIRST credited probe binding
    the (Room carrier, ENTERS event, ManifestDread effect) triple.

    **Bridge arm exercised:** ``manifest_dread`` (round-23+ bridge
    arm in ``cross_engine.py``:7822 — same arm Innocuous Rat / Bashful
    Beastie pin).

    **Setup (Python-side):**
      * p0 has Ticket Booth // Tunnel of Hate on the battlefield.
      * p0's library is EMPTY (the empty-library no-op case the probe
        verifies — production library-non-empty cases are deferred per
        the JJJJ Weight Room ManifestDread harness substrate
        precedent).

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "manifest_dread", "count": 1}`` translates to a
        ``ManifestDread(count=1)`` instance.
      * The Enchantment's ENTERS triggered ability emits the same.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * With p0's library EMPTY, the resolve is a silent no-op: log
        unchanged, battlefield unchanged, library unchanged, graveyard
        unchanged.

    **JJJJ honest-stop reversal.**  JJJJ's drop-list cited "Ticket
    Booth // Tunnel of Hate (ENTERS -> ManifestDread bit-identical to
    PROBED Unsettling Twins)" — the bit-identical-shape rationale.  Per
    the 2026-05-24 post-flip-reclassification-scout precedent (12 bit-
    identical probes registered) + the IIII Optimistic Scavenger /
    Command Bridge precedent ("the classifier credits per-slug, not
    per-effect-class") + the immediate batch-1 Innocuous Rat precedent
    (the same lane registered ``test_innocuous_rat_parity.py`` on
    bit-identical DIES+ManifestDread grounds), this reclaim is honest.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Ticket Booth // Tunnel of Hate
    #    printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Ticket Booth // Tunnel of Hate")
    if real is None:
        pytest.skip(
            "Ticket Booth // Tunnel of Hate absent from active "
            "CardSource"
        )
    assert "Enchantment" in real.card_types
    assert "Room" in real.subtypes
    enters_md_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event is Event.ENTERS
            and isinstance(ta.effect, ManifestDread)
        ),
        None,
    )
    assert enters_md_ta is not None, (
        "Ticket Booth // Tunnel of Hate must have an ENTERS triggered "
        "ability emitting ManifestDread (the Ticket Booth front-half "
        "door body)"
    )
    assert enters_md_ta.effect.count == 1

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "manifest_dread", "count": 1}
    )
    assert isinstance(bridged, ManifestDread)
    assert bridged.count == 1
    assert enters_md_ta.effect == bridged, (
        f"Ticket Booth ENTERS effect must be byte-equal to bridged; "
        f"got parsed={enters_md_ta.effect!r}, bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Python-side resolve smoke on a controlled state: empty-library
    #    silent no-op short-circuit.  ManifestDread.resolve at
    #    library_lookat.py:358-361 reads p.library; with empty library
    #    the loop's ``if not p.library: return`` early-out fires after
    #    iteration 0 (no library cards examined, no bf or gy mutation,
    #    no log line).
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat Ticket Booth // Tunnel of Hate on p0's battlefield as the
    # source (the ENTERS trigger's controller is p0).
    source = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    source.tapped = False
    source.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(source)

    # Pre-resolve sanity: p0's library is empty (no card_defs / p0_lib
    # passed to DeckSpec) and so is the graveyard.
    assert len(py.players[0].library) == 0
    assert len(py.players[0].graveyard) == 0

    bf_before = list(py.battlefield)
    p0_gy_before = list(py.players[0].graveyard)
    p0_hand_before = list(py.players[0].hand)
    pre_log_len = len(py.log)

    # Drive the ManifestDread effect resolve directly.  The empty-
    # library short-circuit at library_lookat.py:360-361 fires on the
    # FIRST iteration before any library access, so the resolve is a
    # pure no-op (no log line appended either).
    bridged.resolve(py, controller_id=0, targets=())

    # Post-resolve observables: nothing changed (empty-library no-op).
    assert len(py.log) == pre_log_len, (
        f"Ticket Booth ManifestDread(1) empty-library resolve must NOT "
        f"append a log line (the empty-library short-circuit at "
        f"library_lookat.py:360-361); got log_len={len(py.log)} "
        f"(expected {pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Ticket Booth ManifestDread(1) empty-library resolve must NOT "
        "mutate the battlefield (no library card to manifest face-down)"
    )
    assert py.players[0].graveyard == p0_gy_before, (
        "Ticket Booth ManifestDread(1) empty-library resolve must NOT "
        "mutate p0's graveyard (no library card to send to graveyard)"
    )
    assert py.players[0].hand == p0_hand_before, (
        "Ticket Booth ManifestDread(1) empty-library resolve must NOT "
        "mutate p0's hand"
    )
    assert source in py.battlefield, (
        "Ticket Booth ManifestDread(1): source must remain on the "
        "battlefield post-resolve"
    )
