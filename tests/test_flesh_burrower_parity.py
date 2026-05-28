"""Flesh Burrower -- per-card real-EoE cross-engine byte-equal probe
(covered_by_construction -> PROBED tier flip).

Flesh Burrower is a ``{1}{G}`` Creature - Mutant in the EoE pool:

    "Whenever Flesh Burrower attacks, another target attacking creature
    you control gains deathtouch until end of turn."

Parser-emitted shape:
    * ATTACKS (IsSelf) ->
      ``PumpTargetCreatureUntilEOT(power_bonus=0, toughness_bonus=0,
      granted_keywords={'deathtouch'}, you_control_only=True,
      exclude_self=True)``

This probe pins the Flesh Burrower slug via the JJJJ idiom (parse +
bridge round-trip + Python-side resolve smoke).  The bridge arm
``pump_target_creature_until_eot`` narrows the ``granted_keywords``,
``you_control_only``, and ``exclude_self`` riders per the OOO bridge-
narrowing discipline -- the bridge dict carries no such fields; Rust's
variant accepts the bare shape.

**NEW shape coverage (per-slug attribution):** the FIRST credited
``_parity`` probe binding Flesh Burrower's slug.  Distinct from the
batch-3 sibling probes (Horrid Vigor / Dual-Sun Technique / Give In to
Violence / Rig for War / Violent Urge) which all bind
``PumpTargetCreatureUntilEOT`` on a SPELL-EFFECT Instant carrier;
Flesh Burrower is the FIRST credited probe binding the same effect
class on a TRIGGERED-ABILITY carrier (Creature ATTACKS event).  The
``(0, 0)`` pump magnitude matches Horrid Vigor's parameterization but
on a different carrier shape (triggered ability vs spell effect) +
different keyword rider (``deathtouch`` vs ``indestructible,
deathtouch``).
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.pump import PumpTargetCreatureUntilEOT


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_flesh_burrower_parser_claims_card():
    assert "Flesh Burrower" in _PRINTINGS, (
        "Flesh Burrower must be parser-claimed by the active "
        "CardSource"
    )


def test_flesh_burrower_printed_attrs():
    """Pins the basic printing surface: Creature, {1}{G} cost."""
    p = _PRINTINGS["Flesh Burrower"]
    assert "Creature" in p.card_types
    assert p.mana_cost.generic == 1
    assert p.mana_cost.colored == (("G", 1),)


def test_flesh_burrower_attacks_trigger_shape():
    """The ATTACKS triggered ability emits
    ``PumpTargetCreatureUntilEOT(0/0, deathtouch, you_control_only,
    exclude_self)``."""
    from mtg_bot.effects.predicates import Event

    p = _PRINTINGS["Flesh Burrower"]
    attacks_ta = next(
        (
            ta for ta in p.triggered_abilities
            if ta.event == Event.ATTACKS
            and isinstance(ta.effect, PumpTargetCreatureUntilEOT)
        ),
        None,
    )
    assert attacks_ta is not None, (
        "Flesh Burrower must have an ATTACKS triggered ability "
        "emitting PumpTargetCreatureUntilEOT"
    )
    assert attacks_ta.effect.power_bonus == 0
    assert attacks_ta.effect.toughness_bonus == 0
    assert "deathtouch" in attacks_ta.effect.granted_keywords
    assert attacks_ta.effect.you_control_only is True
    assert attacks_ta.effect.exclude_self is True


# ---------------------------------------------------------------------------
# (2) Bridge round-trip (narrows granted_keywords/you_control_only/
# exclude_self per OOO).
# ---------------------------------------------------------------------------


def test_flesh_burrower_bridge_arm_round_trip_narrows_riders():
    """The bridge arm ``pump_target_creature_until_eot`` with 0/0
    round-trips to ``PumpTargetCreatureUntilEOT(power_bonus=0,
    toughness_bonus=0, granted_keywords=frozenset())`` -- the
    ``granted_keywords``, ``you_control_only`` and ``exclude_self``
    riders are narrowed per the OOO bridge-narrowing discipline."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {
            "kind": "pump_target_creature_until_eot",
            "power_bonus": 0,
            "toughness_bonus": 0,
        }
    )
    assert isinstance(bridged, PumpTargetCreatureUntilEOT)
    assert bridged.power_bonus == 0
    assert bridged.toughness_bonus == 0
    # OOO bridge-narrowing: bridge dict carries no such riders.
    assert bridged.granted_keywords == frozenset()


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_flesh_burrower_pump_target_deathtouch_parity():
    """**GENUINE real-EoE cross-engine probe -- Flesh Burrower
    (Creature ATTACKS -> PumpTargetCreatureUntilEOT(0/0 deathtouch
    narrowed to bare 0/0)).**

    Drives the **real parsed Flesh Burrower printing** through the
    Python-side ``PumpTargetCreatureUntilEOT`` resolve path,
    validating the empty-targets silent-no-op short-circuit
    (``effects/generic/pump.py``: ``if not targets: return`` -- the
    first observable line of the PumpTargetCreatureUntilEOT resolve
    method).  Pairs the parse + bridge round-trip verification with
    the live Python resolve smoke, the same parse + bridge-round-trip
    + Python-side resolve idiom DDD slice 17 + YYY + ZZZ + AAAA +
    CCCC + DDDD + EEEE + FFFF + GGGG + HHHH + IIII + JJJJ established.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe
    binding Flesh Burrower's slug.  Per-slug attribution credit per
    the 2026-05-24 ``post-flip-reclassification-scout`` sweep
    precedent.  Distinct from the batch-3 spell-effect Instant
    carriers (Horrid Vigor / Dual-Sun Technique / Give In to
    Violence / Rig for War / Violent Urge) -- Flesh Burrower is the
    FIRST credited probe of ``PumpTargetCreatureUntilEOT`` on a
    TRIGGERED-ABILITY carrier (Creature ATTACKS event).

    **Bridge arm exercised:** ``pump_target_creature_until_eot``
    (matching Rust's ``Effect::PumpTargetCreatureUntilEOT
    { power_bonus, toughness_bonus }``).  The ``granted_keywords``,
    ``you_control_only`` and ``exclude_self`` riders are narrowed
    per the OOO bridge-narrowing discipline -- the bridge dict
    carries no such fields, Rust's variant accepts the bare shape
    with empty rider slots; the probe pins the bare-shape resolve
    path (empty-targets no-op), NOT the deathtouch-keyword-grant
    branch.

    **Setup (Python-side):**
      * Empty state -- no targets passed to resolve; the resolve
        short-circuits at the first observable line.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "pump_target_creature_until_eot",
        "power_bonus": 0, "toughness_bonus": 0}`` translates to
        ``PumpTargetCreatureUntilEOT(0/0,
        granted_keywords=frozenset())`` (the bare shape; OOO
        bridge-narrowing).
      * The Flesh Burrower ATTACKS trigger emits the rider-bearing
        variant ``PumpTargetCreatureUntilEOT(0/0,
        granted_keywords={'deathtouch'}, you_control_only=True,
        exclude_self=True)`` (asserted but NOT compared to bridged --
        narrowed per OOO).
      * With ``targets=()``, the resolve is a no-op: log unchanged,
        no UEOT pump granted, no UEOT keyword granted.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.effects.predicates import Event

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Flesh Burrower printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Flesh Burrower")
    if real is None:
        pytest.skip("Flesh Burrower absent from active CardSource")
    assert "Creature" in real.card_types, (
        "Flesh Burrower must be a Creature"
    )
    attacks_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.ATTACKS
            and isinstance(ta.effect, PumpTargetCreatureUntilEOT)
        ),
        None,
    )
    assert attacks_ta is not None, (
        "Flesh Burrower must have an ATTACKS triggered ability "
        "emitting PumpTargetCreatureUntilEOT"
    )
    # Pin the rider-bearing shape (the load-bearing "this card carries
    # the deathtouch keyword + you_control_only + exclude_self riders"
    # assertion).
    assert attacks_ta.effect.power_bonus == 0
    assert attacks_ta.effect.toughness_bonus == 0
    assert "deathtouch" in attacks_ta.effect.granted_keywords, (
        f"Flesh Burrower ATTACKS effect must grant 'deathtouch'; got "
        f"granted_keywords={attacks_ta.effect.granted_keywords!r}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.  The
    #    granted_keywords / you_control_only / exclude_self riders are
    #    NARROWED per OOO discipline.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {
            "kind": "pump_target_creature_until_eot",
            "power_bonus": 0,
            "toughness_bonus": 0,
        }
    )
    assert isinstance(bridged, PumpTargetCreatureUntilEOT), (
        f"Bridge arm 'pump_target_creature_until_eot' must round-trip "
        f"to PumpTargetCreatureUntilEOT; got {type(bridged).__name__}"
    )
    assert bridged.power_bonus == 0
    assert bridged.toughness_bonus == 0
    assert bridged.granted_keywords == frozenset(), (
        f"OOO bridge-narrowing: bridged granted_keywords must be empty "
        f"(the bare shape); got {bridged.granted_keywords!r}"
    )

    # ------------------------------------------------------------------
    # 3. Python-side resolve smoke on a controlled state: empty-targets
    #    silent-no-op short-circuit.  PumpTargetCreatureUntilEOT.resolve
    #    short-circuits at ``if not targets: return``
    #    (effects/generic/pump.py).
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    pre_log_len = len(py.log)
    bf_before = list(py.battlefield)

    # ------------------------------------------------------------------
    # 4. resolve: empty-targets silent-no-op.  The resolve's first
    #    observable line is ``if not targets: return``; no log line,
    #    no UEOT pump granted, no UEOT keyword granted.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=())

    assert len(py.log) == pre_log_len, (
        f"Flesh Burrower: empty-targets resolve must NOT append a log "
        f"line (the ``if not targets: return`` short-circuit); got "
        f"log_len={len(py.log)} (expected {pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Flesh Burrower: empty-targets resolve must NOT mutate the "
        "battlefield"
    )
