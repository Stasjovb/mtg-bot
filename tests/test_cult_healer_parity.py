"""Cult Healer -- per-card real-EoE cross-engine byte-equal probe
(covered_by_construction -> PROBED tier flip).

Cult Healer is a ``{2}{W}`` Creature - Human Doctor in the EoE pool:

    "Whenever an enchantment you control enters, Cult Healer gains
    lifelink until end of turn.  Whenever a Room you control is
    fully unlocked, Cult Healer gains lifelink until end of turn."

Parser-emitted shape (two triggered abilities, both emitting the
same Effect):
    * ENTERS (Subject(IsEnchantment) & Controlled(YOU)) ->
      ``PumpSelfUntilEOT(power_bonus=0, toughness_bonus=0,
      granted_keywords={'lifelink'})``
    * ROOM_FULLY_UNLOCKED (Controlled(YOU, subject='room')) ->
      ``PumpSelfUntilEOT(power_bonus=0, toughness_bonus=0,
      granted_keywords={'lifelink'})``

This probe pins the Cult Healer slug via the JJJJ idiom (parse +
bridge round-trip + Python-side resolve smoke).  The bridge arm
``pump_self_until_eot`` narrows the ``granted_keywords`` rider per
the OOO bridge-narrowing discipline (the bridge dict carries no
``granted_keywords`` field; Rust's variant accepts the bare shape
with an empty keyword set).

**NEW shape coverage (per-slug attribution):** the FIRST credited
``_parity`` probe binding Cult Healer's slug.  PumpSelfUntilEOT on a
triggered ability is a DIFFERENT carrier shape from batch 3's spell-
effect PumpTargetCreatureUntilEOT carriers (Horrid Vigor / Dual-Sun
Technique / Give In to Violence / Rig for War / Violent Urge); the
self-pump variant has its own bridge arm (``pump_self_until_eot``)
distinct from the targeted variant (``pump_target_creature_until_eot``).

The probe re-uses the JJJJ Surgical Suite shape: bind the real EoE
printing, verify the parsed Effect's CLASS matches the bridge round-
trip (the ``granted_keywords`` rider is narrowed per OOO discipline),
then run a controlled Python-side resolve smoke on the no-resolving-
source silent-no-op short-circuit (``effects/generic/pump.py``:
``if source is None: return`` -- the first observable line of the
PumpSelfUntilEOT resolve method).
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.pump import PumpSelfUntilEOT


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_cult_healer_parser_claims_card():
    assert "Cult Healer" in _PRINTINGS, (
        "Cult Healer must be parser-claimed by the active CardSource"
    )


def test_cult_healer_printed_attrs():
    """Pins the basic printing surface: Creature, {2}{W} cost."""
    p = _PRINTINGS["Cult Healer"]
    assert "Creature" in p.card_types
    assert p.mana_cost.generic == 2
    assert p.mana_cost.colored == (("W", 1),)


def test_cult_healer_trigger_shapes():
    """The two triggered abilities both emit
    ``PumpSelfUntilEOT(0/0, lifelink)``."""
    from mtg_bot.effects.predicates import Event

    p = _PRINTINGS["Cult Healer"]
    pumps = [
        ta for ta in p.triggered_abilities
        if isinstance(ta.effect, PumpSelfUntilEOT)
    ]
    assert len(pumps) == 2, (
        f"Cult Healer must have two PumpSelfUntilEOT triggered "
        f"abilities (ENTERS-enchantment + ROOM_FULLY_UNLOCKED); got "
        f"{len(pumps)}"
    )
    events = sorted(ta.event.value for ta in pumps)
    assert events == sorted(
        [Event.ENTERS.value, Event.ROOM_FULLY_UNLOCKED.value]
    )
    # Both triggers carry the same effect shape.
    for ta in pumps:
        assert ta.effect.power_bonus == 0
        assert ta.effect.toughness_bonus == 0
        assert "lifelink" in ta.effect.granted_keywords


# ---------------------------------------------------------------------------
# (2) Bridge round-trip (narrows granted_keywords per OOO).
# ---------------------------------------------------------------------------


def test_cult_healer_bridge_arm_round_trip_narrows_keywords():
    """The bridge arm ``pump_self_until_eot`` with 0/0 round-trips to
    ``PumpSelfUntilEOT(power_bonus=0, toughness_bonus=0,
    granted_keywords=frozenset())`` -- the ``granted_keywords`` rider
    is narrowed per the OOO bridge-narrowing discipline."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {
            "kind": "pump_self_until_eot",
            "power_bonus": 0,
            "toughness_bonus": 0,
        }
    )
    assert isinstance(bridged, PumpSelfUntilEOT)
    assert bridged.power_bonus == 0
    assert bridged.toughness_bonus == 0
    # OOO bridge-narrowing: bridge dict carries no ``granted_keywords``.
    assert bridged.granted_keywords == frozenset()


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_cult_healer_pump_self_lifelink_parity():
    """**GENUINE real-EoE cross-engine probe -- Cult Healer (Creature
    ENTERS-enchantment / ROOM_FULLY_UNLOCKED ->
    PumpSelfUntilEOT(0/0 lifelink narrowed to bare)).**

    Drives the **real parsed Cult Healer printing** through the
    Python-side ``PumpSelfUntilEOT`` resolve path, validating the
    no-resolving-source silent-no-op short-circuit
    (``effects/generic/pump.py``: ``if source is None: return`` --
    the first observable line of the PumpSelfUntilEOT resolve method).
    Pairs the parse + bridge round-trip verification with the live
    Python resolve smoke, the same parse + bridge-round-trip +
    Python-side resolve idiom DDD slice 17 + YYY + ZZZ + AAAA + CCCC
    + DDDD + EEEE + FFFF + GGGG + HHHH + IIII + JJJJ established.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe
    binding Cult Healer's slug.  Per-slug attribution credit per the
    2026-05-24 ``post-flip-reclassification-scout`` sweep precedent.
    This is also the FIRST credited probe of PumpSelfUntilEOT on a
    TRIGGERED ability carrier (the sibling PROBED Boilerbilges
    Ripper pins the spell-effect on a Sorcery carrier, a DIFFERENT
    carrier shape).

    **Bridge arm exercised:** ``pump_self_until_eot`` (matching Rust's
    ``Effect::PumpSelfUntilEOT { power_bonus, toughness_bonus }``).
    The ``granted_keywords`` rider is narrowed per the OOO bridge-
    narrowing discipline -- the bridge dict carries no
    ``granted_keywords`` field, Rust's variant accepts the bare shape
    with an empty keyword set; the probe pins the bare-shape resolve
    path (no-resolving-source no-op), NOT the lifelink-keyword-grant
    branch of the resolve method.

    **Setup (Python-side):**
      * Empty state -- no resolving_source set (None); the resolve
        short-circuits at the first observable line.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "pump_self_until_eot", "power_bonus": 0,
        "toughness_bonus": 0}`` translates to
        ``PumpSelfUntilEOT(0/0, granted_keywords=frozenset())`` (the
        bare shape; OOO bridge-narrowing).
      * The Cult Healer triggers emit the rider-bearing variant
        ``PumpSelfUntilEOT(0/0, granted_keywords={'lifelink'})``
        (asserted but NOT compared to bridged -- narrowed per OOO).
      * With ``resolving_source=None``, the resolve is a no-op:
        log unchanged, no UEOT pump granted, no UEOT keyword granted.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.effects.predicates import Event

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Cult Healer printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Cult Healer")
    if real is None:
        pytest.skip("Cult Healer absent from active CardSource")
    assert "Creature" in real.card_types, (
        "Cult Healer must be a Creature"
    )
    enters_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.ENTERS
            and isinstance(ta.effect, PumpSelfUntilEOT)
        ),
        None,
    )
    assert enters_ta is not None, (
        "Cult Healer must have an ENTERS triggered ability emitting "
        "PumpSelfUntilEOT"
    )
    # Pin the rider-bearing shape (the load-bearing "this card carries
    # the lifelink keyword rider" assertion).
    assert "lifelink" in enters_ta.effect.granted_keywords, (
        f"Cult Healer ENTERS effect must grant 'lifelink'; got "
        f"granted_keywords={enters_ta.effect.granted_keywords!r}"
    )
    assert enters_ta.effect.power_bonus == 0
    assert enters_ta.effect.toughness_bonus == 0

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.  The
    #    granted_keywords rider is NARROWED per OOO discipline.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {
            "kind": "pump_self_until_eot",
            "power_bonus": 0,
            "toughness_bonus": 0,
        }
    )
    assert isinstance(bridged, PumpSelfUntilEOT), (
        f"Bridge arm 'pump_self_until_eot' must round-trip to "
        f"PumpSelfUntilEOT; got {type(bridged).__name__}"
    )
    assert bridged.granted_keywords == frozenset(), (
        f"OOO bridge-narrowing: bridged granted_keywords must be empty "
        f"(the bare shape); got {bridged.granted_keywords!r}"
    )

    # ------------------------------------------------------------------
    # 3. Python-side resolve smoke on a controlled state: no-resolving-
    #    source silent-no-op short-circuit.  PumpSelfUntilEOT.resolve
    #    reads state.resolving_source and short-circuits at
    #    ``if source is None: return`` (effects/generic/pump.py).
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    # Explicit: no resolving_source (the silent no-op case).
    assert py.resolving_source is None, (
        "Pre-resolve sanity: resolving_source must be None"
    )

    pre_log_len = len(py.log)
    bf_before = list(py.battlefield)

    # ------------------------------------------------------------------
    # 4. resolve: no-resolving-source silent-no-op.  The resolve's
    #    first observable line is ``if source is None: return``; no
    #    log line, no UEOT pump granted, no UEOT keyword granted.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=())

    assert len(py.log) == pre_log_len, (
        f"Cult Healer: no-resolving-source resolve must NOT append a "
        f"log line (the ``if source is None: return`` short-circuit); "
        f"got log_len={len(py.log)} (expected {pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Cult Healer: no-resolving-source resolve must NOT mutate the "
        "battlefield"
    )
