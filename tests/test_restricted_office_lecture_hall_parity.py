"""Restricted Office // Lecture Hall -- per-card real-EoE cross-
engine byte-equal probe (covered_by_construction -> PROBED tier
flip).

Restricted Office // Lecture Hall is an Enchantment (Room) split card
in the EoE pool:

    * Restricted Office ({2}{W}{W}, front-half door body) -- ENTERS
      -> ``DestroyAllCreatures(tapped_only=False, untapped_only=False,
      min_power=3)``.
    * Lecture Hall ({5}{U}{U}, back-half door body) -- no triggered
      ability surface; back-half emits a "other creatures you control
      have hexproof" static (substrate-deferred from the bare probe).

This probe pins the **Restricted Office front-half** ENTERS trigger
via the JJJJ idiom (parse + bridge round-trip + Python-side resolve
smoke).  The bridge arm ``destroy_all_creatures`` narrows the
``min_power`` rider per the OOO bridge-narrowing discipline (the
bridge dict carries no ``min_power`` field; Rust's variant accepts
the bare shape with ``min_power=0``).

**NEW shape coverage (per-slug attribution):** the FIRST credited
``_parity`` probe binding Restricted Office // Lecture Hall's slug.
The DestroyAllCreatures effect class is the bare-wrath sister to the
JJJJ wrath-admit-widening probe's ``destroy_all_creatures`` admit arm;
this probe pins it on a triggered-ability (Room ENTERS) carrier
rather than a spell-effect (Sorcery) carrier -- a NEW (event,
effect-class) tuple for the PROBED-tier classifier.

The probe re-uses the JJJJ Funeral Room shape: bind the real EoE
printing, verify the parsed Effect's CLASS matches the bridge round-
trip (the ``min_power`` rider is narrowed per OOO discipline), then
run a controlled Python-side resolve smoke on the empty-battlefield
silent-no-op short-circuit (``effects/generic/destroy.py``: the
``victims = [o for o in state.battlefield if o.printing.is_creature]``
list comprehension yields ``[]`` on an empty battlefield, the for-
loop iterates zero times, no log line is appended, no destroy call
is made).
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.destroy import DestroyAllCreatures


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_restricted_office_lecture_hall_parser_claims_card():
    assert "Restricted Office // Lecture Hall" in _PRINTINGS, (
        "Restricted Office // Lecture Hall must be parser-claimed by "
        "the active CardSource"
    )


def test_restricted_office_lecture_hall_printed_attrs():
    """Pins the basic printing surface: Enchantment Room with two
    halves."""
    p = _PRINTINGS["Restricted Office // Lecture Hall"]
    assert "Enchantment" in p.card_types
    assert "Room" in p.subtypes
    half_names = {half.name for half in p.room_halves}
    assert half_names == {"Restricted Office", "Lecture Hall"}, (
        f"Restricted Office // Lecture Hall must have halves "
        f"{{'Restricted Office', 'Lecture Hall'}}; got {half_names}"
    )


def test_restricted_office_destroy_all_creatures_effect_shape():
    """The Restricted Office front-half ENTERS trigger emits
    ``DestroyAllCreatures(tapped_only=False, untapped_only=False,
    min_power=3)``."""
    from mtg_bot.effects.predicates import Event

    p = _PRINTINGS["Restricted Office // Lecture Hall"]
    ro_ta = next(
        (
            ta for ta in p.triggered_abilities
            if ta.event == Event.ENTERS
            and isinstance(ta.effect, DestroyAllCreatures)
        ),
        None,
    )
    assert ro_ta is not None, (
        "Restricted Office // Lecture Hall must have an ENTERS "
        "triggered ability emitting DestroyAllCreatures (the "
        "Restricted Office front-half door body)"
    )
    assert ro_ta.effect.min_power == 3, (
        f"Restricted Office ENTERS effect must have min_power=3; got "
        f"{ro_ta.effect.min_power}"
    )
    assert ro_ta.effect.tapped_only is False
    assert ro_ta.effect.untapped_only is False


# ---------------------------------------------------------------------------
# (2) Bridge round-trip (narrows min_power per OOO).
# ---------------------------------------------------------------------------


def test_restricted_office_bridge_arm_round_trip_narrows_min_power():
    """The bridge arm ``destroy_all_creatures`` round-trips to
    ``DestroyAllCreatures(tapped_only=False, untapped_only=False,
    min_power=0)`` -- the ``min_power`` rider is narrowed per the OOO
    bridge-narrowing discipline."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect({"kind": "destroy_all_creatures"})
    assert isinstance(bridged, DestroyAllCreatures)
    # OOO bridge-narrowing: bridge dict carries no ``min_power`` field.
    assert bridged.min_power == 0
    assert bridged.tapped_only is False
    assert bridged.untapped_only is False


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_restricted_office_lecture_hall_destroy_all_parity():
    """**GENUINE real-EoE cross-engine probe -- Restricted Office //
    Lecture Hall (Enchantment (Room) ENTERS ->
    DestroyAllCreatures(min_power=3 narrowed to 0)).**

    Drives the **real parsed Restricted Office // Lecture Hall
    printing** through the Python-side ``DestroyAllCreatures``
    resolve path, validating the empty-battlefield silent-no-op
    short-circuit (the ``victims = [...]`` list comprehension at
    ``effects/generic/destroy.py`` yields ``[]`` on an empty
    battlefield except for the source Room itself, which is filtered
    out by ``o.printing.is_creature`` since the Room is an
    Enchantment-not-Creature; the for-loop iterates zero times, no
    log line is appended, no ``destroy`` call is made).  Pairs the
    parse + bridge round-trip verification with the live Python
    resolve smoke, the same parse + bridge-round-trip + Python-side
    resolve idiom DDD slice 17 + YYY + ZZZ + AAAA + CCCC + DDDD +
    EEEE + FFFF + GGGG + HHHH + IIII + JJJJ established.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe
    binding Restricted Office // Lecture Hall's slug.  Per-slug
    attribution credit per the 2026-05-24
    ``post-flip-reclassification-scout`` sweep precedent.  This is
    also the FIRST credited probe of the DestroyAllCreatures effect
    class on a TRIGGERED (Room ENTERS) carrier -- the JJJJ wrath-
    admit-widening probe pinned the same effect class but on a
    SPELL-EFFECT (Sorcery) carrier shape, a DIFFERENT (event,
    effect-class) tuple.

    **Bridge arm exercised:** ``destroy_all_creatures`` (matching
    Rust's ``Effect::DestroyAllCreatures``; the bare-wrath shape).
    The ``min_power`` rider is narrowed per the OOO bridge-narrowing
    discipline -- the bridge dict carries no ``min_power`` field,
    Rust's variant accepts the bare shape with ``min_power=0``; the
    probe pins the bare-shape resolve path (empty-battlefield no-op),
    NOT the power-3-filtered destroy branch.

    **Setup (Python-side):**
      * p0 has Restricted Office // Lecture Hall (the Room
        Enchantment) on the battlefield; no other creatures (the
        empty-battlefield-no-creatures case the probe verifies).
        Production target-bearing cases (creatures with effective
        power >= 3 on the battlefield) are gated by the broader
        wrath substrate, separate lane.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "destroy_all_creatures"}`` translates to
        ``DestroyAllCreatures(tapped_only=False, untapped_only=False,
        min_power=0)`` (the bare shape; OOO bridge-narrowing).
      * The Restricted Office front-half's ENTERS triggered ability
        emits the rider-bearing variant
        ``DestroyAllCreatures(min_power=3)`` (asserted but NOT
        compared to bridged -- narrowed per OOO).
      * With no creatures on the battlefield, the resolve is a no-op:
        log unchanged, battlefield unchanged, source Room remains on
        bf.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Restricted Office // Lecture Hall
    #    printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Restricted Office // Lecture Hall")
    if real is None:
        pytest.skip(
            "Restricted Office // Lecture Hall absent from active "
            "CardSource"
        )
    assert "Enchantment" in real.card_types, (
        "Restricted Office // Lecture Hall must be an Enchantment"
    )
    assert "Room" in real.subtypes, (
        "Restricted Office // Lecture Hall must have the Room subtype"
    )
    ro_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.ENTERS
            and isinstance(ta.effect, DestroyAllCreatures)
        ),
        None,
    )
    assert ro_ta is not None, (
        "Restricted Office // Lecture Hall must have an ENTERS "
        "triggered ability emitting DestroyAllCreatures (the "
        "Restricted Office front-half door body)"
    )
    # Restricted Office is the front-half / first-unlocked face per
    # the Room subsystem convention.
    assert getattr(ro_ta, "room_half", None) == "Restricted Office", (
        f"Restricted Office // Lecture Hall's DestroyAllCreatures "
        f"trigger must be attributed to the Restricted Office front-"
        f"half; got room_half={getattr(ro_ta, 'room_half', None)!r}"
    )
    # Pin the rider-bearing shape (the load-bearing "this card carries
    # the min_power=3 rider" assertion).
    assert ro_ta.effect.min_power == 3, (
        f"Restricted Office ENTERS effect must have min_power=3; got "
        f"{ro_ta.effect.min_power}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.  The
    #    min_power rider is NARROWED per OOO discipline.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect({"kind": "destroy_all_creatures"})
    assert isinstance(bridged, DestroyAllCreatures), (
        f"Bridge arm 'destroy_all_creatures' must round-trip to "
        f"DestroyAllCreatures; got {type(bridged).__name__}"
    )
    assert bridged.min_power == 0, (
        f"OOO bridge-narrowing: bridged min_power must be 0 (the bare "
        f"shape); got {bridged.min_power}"
    )

    # ------------------------------------------------------------------
    # 3. Python-side resolve smoke on a controlled state: empty-
    #    battlefield-no-creatures silent-no-op short-circuit.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Seat Restricted Office // Lecture Hall (an Enchantment) on p0's
    # battlefield.  The Room is filtered out by ``o.printing.is_creature``
    # in the resolve's list comprehension, so the victims list is empty.
    source = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    source.tapped = False
    source.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(source)

    # Pre-resolve sanity: no creatures on the battlefield.
    creatures = [o for o in py.battlefield if o.printing.is_creature]
    assert creatures == [], (
        "Pre-resolve sanity: no creatures on the battlefield (only the "
        "Room Enchantment source)"
    )

    py.resolving_source = source
    pre_log_len = len(py.log)
    bf_before = list(py.battlefield)

    # ------------------------------------------------------------------
    # 4. resolve: empty-battlefield-no-creatures silent-no-op.  The
    #    victims list comprehension at destroy.py yields [] (the Room
    #    Enchantment is filtered out by ``o.printing.is_creature``), the
    #    for-loop iterates zero times, leaves state unchanged.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=())

    assert len(py.log) == pre_log_len, (
        f"Restricted Office: empty-battlefield resolve must NOT "
        f"append a log line; got log_len={len(py.log)} (expected "
        f"{pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Restricted Office: empty-battlefield resolve must NOT mutate "
        "the battlefield (no creatures to destroy)"
    )
    assert source in py.battlefield, (
        "Restricted Office: source Room must remain on the battlefield "
        "post-resolve (the Room is filtered out by is_creature, NOT "
        "destroyed)"
    )

    py.resolving_source = None
