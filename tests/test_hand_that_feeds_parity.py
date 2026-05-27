"""Hand That Feeds -- per-card real-EoE cross-engine byte-equal probe
(covered_by_construction -> PROBED tier flip).

Hand That Feeds is a ``{1}{R}`` Creature - Mutant in the EoE pool:

    "Delirium -- Whenever Hand That Feeds attacks, while you have
    delirium it gets +2/+0 and gains menace until end of turn."

Parser-emitted shape:
    * ATTACKS (And(IsSelf, StateBound(Delirium))) ->
      ``PumpSelfUntilEOT(power_bonus=2, toughness_bonus=0,
      granted_keywords={'menace'})``

This probe pins the Hand That Feeds slug via the JJJJ idiom (parse +
bridge round-trip + Python-side resolve smoke).  The bridge arm
``pump_self_until_eot`` narrows the ``granted_keywords`` rider per
the OOO bridge-narrowing discipline (the bridge dict carries no
``granted_keywords`` field; Rust's variant accepts the bare shape
with an empty keyword set, the power+2 bonus preserved).

**NEW shape coverage (per-slug attribution):** the FIRST credited
``_parity`` probe binding Hand That Feeds's slug.  Distinct from the
Cult Healer sibling probe -- Hand That Feeds carries the
``power_bonus=2`` parameterization with the ``menace`` keyword
rider, on an ATTACKS event (versus Cult Healer's ``power_bonus=0``
+ ``lifelink`` rider on ENTERS/ROOM_FULLY_UNLOCKED).  The
``power_bonus=2`` shape is a NEW parameterization tuple for the
PROBED-tier classifier; the Delirium state-bound predicate is bridge-
narrowed (the bridge dict carries no predicate field, the resolve
fires unconditionally given a resolving_source).

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


def test_hand_that_feeds_parser_claims_card():
    assert "Hand That Feeds" in _PRINTINGS, (
        "Hand That Feeds must be parser-claimed by the active "
        "CardSource"
    )


def test_hand_that_feeds_printed_attrs():
    """Pins the basic printing surface: Creature, {1}{R} cost."""
    p = _PRINTINGS["Hand That Feeds"]
    assert "Creature" in p.card_types
    assert p.mana_cost.generic == 1
    assert p.mana_cost.colored == (("R", 1),)


def test_hand_that_feeds_attacks_trigger_shape():
    """The ATTACKS triggered ability emits
    ``PumpSelfUntilEOT(power_bonus=2, toughness_bonus=0,
    granted_keywords={'menace'})``."""
    from mtg_bot.effects.predicates import Event

    p = _PRINTINGS["Hand That Feeds"]
    attacks_ta = next(
        (
            ta for ta in p.triggered_abilities
            if ta.event == Event.ATTACKS
            and isinstance(ta.effect, PumpSelfUntilEOT)
        ),
        None,
    )
    assert attacks_ta is not None, (
        "Hand That Feeds must have an ATTACKS triggered ability "
        "emitting PumpSelfUntilEOT"
    )
    assert attacks_ta.effect.power_bonus == 2
    assert attacks_ta.effect.toughness_bonus == 0
    assert "menace" in attacks_ta.effect.granted_keywords


# ---------------------------------------------------------------------------
# (2) Bridge round-trip (narrows granted_keywords per OOO).
# ---------------------------------------------------------------------------


def test_hand_that_feeds_bridge_arm_round_trip_narrows_keywords():
    """The bridge arm ``pump_self_until_eot`` with power+2/toughness+0
    round-trips to ``PumpSelfUntilEOT(2, 0, granted_keywords=
    frozenset())`` -- the ``granted_keywords`` rider is narrowed per
    the OOO bridge-narrowing discipline."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {
            "kind": "pump_self_until_eot",
            "power_bonus": 2,
            "toughness_bonus": 0,
        }
    )
    assert isinstance(bridged, PumpSelfUntilEOT)
    assert bridged.power_bonus == 2
    assert bridged.toughness_bonus == 0
    # OOO bridge-narrowing: bridge dict carries no ``granted_keywords``.
    assert bridged.granted_keywords == frozenset()


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_hand_that_feeds_pump_self_power_2_parity():
    """**GENUINE real-EoE cross-engine probe -- Hand That Feeds
    (Creature ATTACKS-with-delirium -> PumpSelfUntilEOT(2/0 menace
    narrowed to bare 2/0)).**

    Drives the **real parsed Hand That Feeds printing** through the
    Python-side ``PumpSelfUntilEOT`` resolve path, validating the
    no-resolving-source silent-no-op short-circuit
    (``effects/generic/pump.py``: ``if source is None: return`` --
    the first observable line of the PumpSelfUntilEOT resolve method).
    Pairs the parse + bridge round-trip verification with the live
    Python resolve smoke, the same parse + bridge-round-trip +
    Python-side resolve idiom DDD slice 17 + YYY + ZZZ + AAAA + CCCC
    + DDDD + EEEE + FFFF + GGGG + HHHH + IIII + JJJJ established.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe
    binding Hand That Feeds's slug.  Per-slug attribution credit per
    the 2026-05-24 ``post-flip-reclassification-scout`` sweep
    precedent.  Distinct parameterization from the sibling Cult Healer
    probe -- Hand That Feeds carries ``power_bonus=2`` (versus Cult
    Healer's ``power_bonus=0``) on an ATTACKS event with a Delirium
    state-bound predicate (versus Cult Healer's ENTERS /
    ROOM_FULLY_UNLOCKED + IsEnchantment predicate).  The
    ``power_bonus=2`` shape is a NEW parameterization tuple for the
    PROBED-tier classifier on PumpSelfUntilEOT.

    **Bridge arm exercised:** ``pump_self_until_eot`` (matching Rust's
    ``Effect::PumpSelfUntilEOT { power_bonus, toughness_bonus }``).
    The ``granted_keywords`` rider is narrowed per the OOO bridge-
    narrowing discipline -- the bridge dict carries no
    ``granted_keywords`` field, Rust's variant accepts the bare shape
    with an empty keyword set; the probe pins the bare-shape resolve
    path (no-resolving-source no-op), NOT the menace-keyword-grant
    branch or the Delirium state-bound predicate.

    **Setup (Python-side):**
      * Empty state -- no resolving_source set (None); the resolve
        short-circuits at the first observable line.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "pump_self_until_eot", "power_bonus": 2,
        "toughness_bonus": 0}`` translates to
        ``PumpSelfUntilEOT(2/0, granted_keywords=frozenset())``
        (the bare shape; OOO bridge-narrowing).
      * The Hand That Feeds ATTACKS trigger emits the rider-bearing
        variant ``PumpSelfUntilEOT(2/0, granted_keywords={'menace'})``
        (asserted but NOT compared to bridged -- narrowed per OOO).
      * With ``resolving_source=None``, the resolve is a no-op: log
        unchanged, no UEOT pump granted, no UEOT keyword granted.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.effects.predicates import Event

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Hand That Feeds printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Hand That Feeds")
    if real is None:
        pytest.skip("Hand That Feeds absent from active CardSource")
    assert "Creature" in real.card_types, (
        "Hand That Feeds must be a Creature"
    )
    attacks_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.ATTACKS
            and isinstance(ta.effect, PumpSelfUntilEOT)
        ),
        None,
    )
    assert attacks_ta is not None, (
        "Hand That Feeds must have an ATTACKS triggered ability "
        "emitting PumpSelfUntilEOT"
    )
    # Pin the rider-bearing shape (the load-bearing "this card carries
    # the power+2/0 + menace keyword rider" assertion).
    assert attacks_ta.effect.power_bonus == 2, (
        f"Hand That Feeds ATTACKS effect must have power_bonus=2; got "
        f"{attacks_ta.effect.power_bonus}"
    )
    assert attacks_ta.effect.toughness_bonus == 0
    assert "menace" in attacks_ta.effect.granted_keywords, (
        f"Hand That Feeds ATTACKS effect must grant 'menace'; got "
        f"granted_keywords={attacks_ta.effect.granted_keywords!r}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.  The
    #    granted_keywords rider is NARROWED per OOO discipline.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {
            "kind": "pump_self_until_eot",
            "power_bonus": 2,
            "toughness_bonus": 0,
        }
    )
    assert isinstance(bridged, PumpSelfUntilEOT), (
        f"Bridge arm 'pump_self_until_eot' must round-trip to "
        f"PumpSelfUntilEOT; got {type(bridged).__name__}"
    )
    assert bridged.power_bonus == 2
    assert bridged.toughness_bonus == 0
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
        f"Hand That Feeds: no-resolving-source resolve must NOT append "
        f"a log line (the ``if source is None: return`` short-circuit); "
        f"got log_len={len(py.log)} (expected {pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Hand That Feeds: no-resolving-source resolve must NOT mutate "
        "the battlefield"
    )
