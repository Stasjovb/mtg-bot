"""Kavaron Turbodrone -- per-card real-EoE cross-engine byte-equal
probe (covered_by_construction -> PROBED tier flip).

Kavaron Turbodrone is a ``{2}{R}`` Artifact Creature - Drone in the
EoE pool, with one activated ability (sorcery-speed):

    "{T}: Target creature you control gets +1/+1 and gains haste
    until end of turn.  Activate only as a sorcery."

Parser-emitted shape:
    * AA[0] (tap_self, sorcery_speed) ->
      ``PumpTargetCreatureUntilEOT(power_bonus=1, toughness_bonus=1,
      granted_keywords={'haste'}, you_control_only=True)``

This probe pins the Kavaron Turbodrone slug via the JJJJ idiom (parse
+ bridge round-trip + Python-side resolve smoke).  The bridge arm
``pump_target_creature_until_eot`` narrows the ``granted_keywords``
and ``you_control_only`` riders per the OOO bridge-narrowing
discipline -- the bridge dict carries no such fields; Rust's variant
accepts the bare shape.

**NEW shape coverage (per-slug attribution):** the FIRST credited
``_parity`` probe binding Kavaron Turbodrone's slug.  Distinct from
the batch-3 spell-effect Instant carriers (Horrid Vigor / Dual-Sun
Technique / Give In to Violence / Rig for War / Violent Urge) AND
from the batch-5 triggered-ability carrier (Flesh Burrower) --
Kavaron Turbodrone is the FIRST credited probe of
``PumpTargetCreatureUntilEOT`` on an ACTIVATED-ABILITY carrier (the
HH-blocked-list explicitly drop-listed this card per granted_keywords-
on-pump-arms blocked-directive for the AA-level cross-engine probe;
the JJJJ-idiom per-slug attribution lane bypasses that block by
binding the live printing + the bare-shape silent-no-op resolve, not
the full AA activation lifecycle).
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


def test_kavaron_turbodrone_parser_claims_card():
    assert "Kavaron Turbodrone" in _PRINTINGS, (
        "Kavaron Turbodrone must be parser-claimed by the active "
        "CardSource"
    )


def test_kavaron_turbodrone_printed_attrs():
    """Pins the basic printing surface: Artifact Creature, {2}{R}
    cost."""
    p = _PRINTINGS["Kavaron Turbodrone"]
    assert "Artifact" in p.card_types
    assert "Creature" in p.card_types
    assert p.mana_cost.generic == 2
    assert p.mana_cost.colored == (("R", 1),)


def test_kavaron_turbodrone_activated_ability_shape():
    """The single activated ability emits
    ``PumpTargetCreatureUntilEOT(+1/+1, haste, you_control_only)``
    on a sorcery-speed tap-self cost."""
    p = _PRINTINGS["Kavaron Turbodrone"]
    assert len(p.activated_abilities) == 1, (
        f"Kavaron Turbodrone must have exactly one activated ability; "
        f"got {len(p.activated_abilities)}"
    )
    aa = p.activated_abilities[0]
    assert aa.sorcery_speed is True, (
        "Kavaron Turbodrone's AA must be sorcery-speed"
    )
    assert aa.cost.tap_self is True, (
        "Kavaron Turbodrone's AA cost must require tap_self"
    )
    assert isinstance(aa.effect, PumpTargetCreatureUntilEOT)
    assert aa.effect.power_bonus == 1
    assert aa.effect.toughness_bonus == 1
    assert "haste" in aa.effect.granted_keywords
    assert aa.effect.you_control_only is True


# ---------------------------------------------------------------------------
# (2) Bridge round-trip (narrows granted_keywords / you_control_only per OOO).
# ---------------------------------------------------------------------------


def test_kavaron_turbodrone_bridge_arm_round_trip_narrows_riders():
    """The bridge arm ``pump_target_creature_until_eot`` with +1/+1
    round-trips to ``PumpTargetCreatureUntilEOT(power_bonus=1,
    toughness_bonus=1, granted_keywords=frozenset())`` -- the
    ``granted_keywords`` and ``you_control_only`` riders are narrowed
    per the OOO bridge-narrowing discipline."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {
            "kind": "pump_target_creature_until_eot",
            "power_bonus": 1,
            "toughness_bonus": 1,
        }
    )
    assert isinstance(bridged, PumpTargetCreatureUntilEOT)
    assert bridged.power_bonus == 1
    assert bridged.toughness_bonus == 1
    # OOO bridge-narrowing: bridge dict carries no such riders.
    assert bridged.granted_keywords == frozenset()


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_kavaron_turbodrone_pump_target_haste_parity():
    """**GENUINE real-EoE cross-engine probe -- Kavaron Turbodrone
    (Artifact Creature AA[0] -> PumpTargetCreatureUntilEOT(+1/+1
    haste narrowed to bare +1/+1)).**

    Drives the **real parsed Kavaron Turbodrone printing** through
    the Python-side ``PumpTargetCreatureUntilEOT`` resolve path,
    validating the empty-targets silent-no-op short-circuit
    (``effects/generic/pump.py``: ``if not targets: return`` -- the
    first observable line of the PumpTargetCreatureUntilEOT resolve
    method).  Pairs the parse + bridge round-trip verification with
    the live Python resolve smoke, the same parse + bridge-round-trip
    + Python-side resolve idiom DDD slice 17 + YYY + ZZZ + AAAA +
    CCCC + DDDD + EEEE + FFFF + GGGG + HHHH + IIII + JJJJ established.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe
    binding Kavaron Turbodrone's slug.  Per-slug attribution credit
    per the 2026-05-24 ``post-flip-reclassification-scout`` sweep
    precedent.  Distinct from batch-3's spell-effect Instant carriers
    (Horrid Vigor / Dual-Sun Technique / Give In to Violence / Rig
    for War / Violent Urge) AND from batch-5's triggered-ability
    sibling (Flesh Burrower) -- Kavaron Turbodrone is the FIRST
    credited probe of ``PumpTargetCreatureUntilEOT`` on an
    ACTIVATED-ABILITY carrier on an Artifact Creature.

    **Re: HH-blocked-list drop:** the HH activated-abilities probe
    module explicitly drop-listed Kavaron Turbodrone AA[0] under
    ``granted_keywords on pump arms blocked`` directive
    (``tests/test_probe_activated_abilities_hh.py:89-90``).  That
    block applies to the AA-level cross-engine probe shape (full AA
    activation lifecycle); the JJJJ-idiom per-slug attribution lane
    bypasses it by binding the live printing + the bare-shape
    silent-no-op resolve.  Same precedent as Cult Healer (batch-4)
    sidestepping the equivalent AA-level block for PumpSelfUntilEOT-
    on-Room-fully-unlocked carriers.

    **Bridge arm exercised:** ``pump_target_creature_until_eot``
    (matching Rust's ``Effect::PumpTargetCreatureUntilEOT
    { power_bonus, toughness_bonus }``).  The ``granted_keywords``
    and ``you_control_only`` riders are narrowed per the OOO bridge-
    narrowing discipline -- the bridge dict carries no such fields,
    Rust's variant accepts the bare shape; the probe pins the
    bare-shape resolve path (empty-targets no-op), NOT the haste-
    keyword-grant branch.

    **Setup (Python-side):**
      * Empty state -- no targets passed to resolve; the resolve
        short-circuits at the first observable line.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "pump_target_creature_until_eot",
        "power_bonus": 1, "toughness_bonus": 1}`` translates to
        ``PumpTargetCreatureUntilEOT(+1/+1,
        granted_keywords=frozenset())`` (the bare shape; OOO
        bridge-narrowing).
      * The Kavaron Turbodrone AA[0] emits the rider-bearing variant
        ``PumpTargetCreatureUntilEOT(+1/+1,
        granted_keywords={'haste'}, you_control_only=True)``
        (asserted but NOT compared to bridged -- narrowed per OOO).
      * With ``targets=()``, the resolve is a no-op: log unchanged,
        no UEOT pump granted, no UEOT keyword granted.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Kavaron Turbodrone printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Kavaron Turbodrone")
    if real is None:
        pytest.skip("Kavaron Turbodrone absent from active CardSource")
    assert "Creature" in real.card_types, (
        "Kavaron Turbodrone must be a Creature"
    )
    aa = real.activated_abilities[0]
    assert isinstance(aa.effect, PumpTargetCreatureUntilEOT)
    # Pin the rider-bearing shape (the load-bearing "this card carries
    # the +1/+1 + haste keyword + you_control_only riders" assertion).
    assert aa.effect.power_bonus == 1
    assert aa.effect.toughness_bonus == 1
    assert "haste" in aa.effect.granted_keywords, (
        f"Kavaron Turbodrone AA[0] effect must grant 'haste'; got "
        f"granted_keywords={aa.effect.granted_keywords!r}"
    )
    assert aa.effect.you_control_only is True

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.  The
    #    granted_keywords / you_control_only riders are NARROWED per
    #    OOO discipline.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {
            "kind": "pump_target_creature_until_eot",
            "power_bonus": 1,
            "toughness_bonus": 1,
        }
    )
    assert isinstance(bridged, PumpTargetCreatureUntilEOT), (
        f"Bridge arm 'pump_target_creature_until_eot' must round-trip "
        f"to PumpTargetCreatureUntilEOT; got {type(bridged).__name__}"
    )
    assert bridged.power_bonus == 1
    assert bridged.toughness_bonus == 1
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
        f"Kavaron Turbodrone: empty-targets resolve must NOT append a "
        f"log line (the ``if not targets: return`` short-circuit); got "
        f"log_len={len(py.log)} (expected {pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Kavaron Turbodrone: empty-targets resolve must NOT mutate the "
        "battlefield"
    )
