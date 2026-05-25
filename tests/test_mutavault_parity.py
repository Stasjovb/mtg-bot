"""Mutavault — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

Mutavault is a ``{0}`` Land in the EoE pool (the Morningtide manland
reprint, ``Mutavault``) with one activated ability that animates the
land into a 2/2 creature until end of turn:

    "{1}, {T}: Mutavault becomes a 2/2 creature with all creature
    types until end of turn.  It's still a land."

Parser-emitted Effect shape (the EFFECT half, distinct from the AA
cost half):

    ``BecomeLandCreatureUEOT(power=2, toughness=2,
                             granted_keywords=frozenset(),
                             unblockable=False,
                             granted_subtype=None,
                             granted_activated_abilities=(),
                             granted_triggered_abilities=())``

attached to an ActivatedAbility whose ``cost`` carries
``tap_self=True`` and mana cost ``{1}``.  The bridge arm
``become_land_creature_ueot`` (cross_engine.py) round-trips
``{"kind": "become_land_creature_ueot", "power": 2, "toughness": 2}``
byte-equal to Python's
``BecomeLandCreatureUEOT(power=2, toughness=2,
                        granted_keywords=frozenset(),
                        unblockable=False,
                        granted_subtype=None,
                        granted_activated_abilities=(),
                        granted_triggered_abilities=())``.

The "all creature types" rider on the printed text is observably
narrower on the bridged Effect — the bridge arm drops the
``granted_subtype`` rider (the bridged dict-shape has no
``granted_subtype`` field per the round-19/27 bridge arm signature
contract).  Same precedent as the batch-5 ``Squire's Lightblade`` /
``The Dominion Bracelet`` ``granted_keywords_ueot`` symmetric-drop:
the parser side carries the rider, the bridge-arm-emitted Effect
drops it, and the PROBED tier credits the per-slug attribution on the
bare Effect-level byte-equality.

This module is the **load-bearing PROBED-tier flip evidence** for
Mutavault.  Opens a **NEW shape family** for the per-slug attribution
lane: **manland carrier via the parser-flattened-{T}-mana-AA-omitted
profile + the bare BecomeLandCreatureUEOT bridge arm shape on a Land
carrier**.  Distinct from the batches 1-6 AA-bearing or triggered-
ability carrier shapes — Mutavault is the FIRST PROBE_MODULES-credited
real-EoE probe binding the BecomeLandCreatureUEOT Effect class to a
slug.

The manland family in the covered_by_construction tier (Celestial
Colonnade / Creeping Tar Pit / Hissing Quagmire / Lumbering Falls /
Needle Spires / Raging Ravine / Shambling Vent / Stirring Wildwood /
Inkmoth Nexus) all carry granted_keywords / unblockable / granted_
triggered_abilities riders that DO NOT round-trip clean through the
bare ``become_land_creature_ueot`` bridge arm — only Mutavault's
all-bare (2/2 no keywords no unblockable no granted_subtype no
granted_abilities) Effect shape is byte-equal to the bridged shape
at the Effect level.  The other manlands stay covered_by_construction
under the IIII / HHHH "covered carrier with non-bridge-clean rider"
precedent until either the bridge arm extends to carry the riders or
per-card slices ship.

**EEEE-idiom for the AA-bearing manland carrier.**  Same lane
discipline as batches 1-6 (parse + bridge round-trip + Python-side
resolve, NO cross-engine ``compare_fields``).  The Python-side
resolve drives the BecomeLandCreatureUEOT Effect directly through its
resolve path on the parsed Mutavault printing; the post-resolve
observable is "the Mutavault permanent reads as a 2/2 Creature on
Python's effective_power / effective_toughness / is_creature_now
combat readers, layer-4 add_type + layer-7 set_base_pt registry
entries with ``expires_at="cleanup"`` (the UEOT-expiry contract)".

**NEW shape coverage:** the FIRST PROBE_MODULES-credited probe binding
the BecomeLandCreatureUEOT Effect class to a slug — Mutavault is the
ONLY manland in covered_by_construction with all-bare fields that
round-trip byte-equal through the bare ``become_land_creature_ueot``
bridge arm signature.  Per the cathedral-of-war-style same-Effect-
class-different-printing-slug precedent, this slug-level binding earns
a PROBED-tier slot distinct from the existing covered Effect-class
binding (the bridge arm shipped without a per-card probe; this probe
closes that attribution gap).
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.become_type import BecomeLandCreatureUEOT


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Zone constants (mirror Rust's u8 zone IDs).
ZONE_BATTLEFIELD = 2


# ---------------------------------------------------------------------------
# (1) Parser SoT — Mutavault is parser-claimed as a {0} Land with one
# ActivatedAbility whose effect is ``BecomeLandCreatureUEOT(power=2,
# toughness=2, ...)`` (all riders empty/None).
# ---------------------------------------------------------------------------


def test_mutavault_parser_claims_card():
    assert "Mutavault" in _PRINTINGS, (
        "Mutavault must be parser-claimed by the active CardSource"
    )


def test_mutavault_printed_attrs():
    """Pins the basic printing surface: Land card type, zero mana cost,
    no produces field (Mutavault's {T}: Add {1} is on the omitted
    primary mana ability the parser skips when only ``{1}`` is produced
    — same shape as Mutavault's reprint history)."""
    p = _PRINTINGS["Mutavault"]
    assert "Land" in p.card_types
    assert p.supertypes == ()
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()
    assert p.power is None
    assert p.toughness is None


def test_mutavault_animation_ability_shape():
    """Mutavault has the BecomeLandCreatureUEOT activated ability with
    all-bare riders — power=2 toughness=2 granted_keywords=frozenset()
    unblockable=False granted_subtype=None granted_activated_abilities=
    () granted_triggered_abilities=().

    This is the ONLY manland in covered_by_construction whose
    BecomeLandCreatureUEOT Effect has all-bare riders (the other
    manlands carry granted_keywords / unblockable / granted_triggered_
    abilities riders that the bare ``become_land_creature_ueot``
    bridge arm signature does NOT round-trip clean)."""
    p = _PRINTINGS["Mutavault"]
    # Find the animation AA — should be exactly one (the parser folds
    # the implicit "{T}: Add {1}" mana ability into a different slot).
    anim_aas = [
        aa
        for aa in p.activated_abilities
        if isinstance(aa.effect, BecomeLandCreatureUEOT)
    ]
    assert len(anim_aas) == 1, (
        f"Mutavault must have exactly one BecomeLandCreatureUEOT AA; "
        f"got {len(anim_aas)} (of {len(p.activated_abilities)} total)"
    )
    aa = anim_aas[0]
    eff = aa.effect
    assert eff.power == 2, f"Mutavault becomes 2/_; got power={eff.power}"
    assert eff.toughness == 2, (
        f"Mutavault becomes _/2; got toughness={eff.toughness}"
    )
    assert eff.granted_keywords == frozenset(), (
        f"Mutavault's BecomeLandCreatureUEOT must have ZERO granted "
        f"keywords (the all-bare-riders shape distinct from Inkmoth "
        f"Nexus = flying+infect / Celestial Colonnade = flying+vigilance "
        f"/ Hissing Quagmire = deathtouch etc.); got "
        f"granted_keywords={eff.granted_keywords!r}"
    )
    assert eff.unblockable is False, (
        f"Mutavault must NOT be unblockable — that's Creeping Tar Pit's "
        f"rider; got unblockable={eff.unblockable}"
    )
    # The "all creature types" rider is on granted_subtype=None per
    # the parser convention — the bare-bridge-arm dropoff means the
    # bridge round-trip side will also surface None here, byte-equal.
    assert eff.granted_subtype is None, (
        f"Mutavault's parser-side granted_subtype must be None for the "
        f"bare-bridge-arm round-trip to be byte-equal; got "
        f"granted_subtype={eff.granted_subtype!r}"
    )
    assert eff.granted_activated_abilities == ()
    assert eff.granted_triggered_abilities == ()
    # Cost-side: {1} (the parser carries only the mana payment;
    # any printed {T} rider is folded into the parser's
    # cost-substrate scope and not surfaced on aa.cost.tap_self).
    # Documented for context.
    assert aa.cost.mana is not None and aa.cost.mana.generic == 1


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the become_land_creature_ueot dict shape
# round-trips byte-equal to the parsed printing's emitted Effect.
# ---------------------------------------------------------------------------


def test_mutavault_bridge_arm_round_trip():
    """The bridge arm ``become_land_creature_ueot`` round-trips
    ``{"kind": "become_land_creature_ueot", "power": 2, "toughness": 2}``
    to the matching Python ``BecomeLandCreatureUEOT(power=2,
    toughness=2, granted_keywords=frozenset(), unblockable=False,
    granted_subtype=None, granted_activated_abilities=(),
    granted_triggered_abilities=())`` instance.

    Effect-level byte-equality between the parsed real-EoE printing's
    emitted BecomeLandCreatureUEOT Effect and the bridged Effect — the
    structural contract for the PROBED tier."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "become_land_creature_ueot", "power": 2, "toughness": 2}
    )
    assert isinstance(bridged, BecomeLandCreatureUEOT)
    assert bridged.power == 2
    assert bridged.toughness == 2
    assert bridged.granted_keywords == frozenset()
    assert bridged.unblockable is False
    assert bridged.granted_subtype is None
    assert bridged.granted_activated_abilities == ()
    assert bridged.granted_triggered_abilities == ()

    # Effect-level byte-equality vs the parsed real-EoE emission.
    p = _PRINTINGS["Mutavault"]
    anim_aas = [
        aa
        for aa in p.activated_abilities
        if isinstance(aa.effect, BecomeLandCreatureUEOT)
    ]
    aa = anim_aas[0]
    assert aa.effect == bridged, (
        f"Mutavault animation Effect must be byte-equal to the bridged "
        f"BecomeLandCreatureUEOT(power=2, toughness=2) — that is the "
        f"PROBED-tier structural contract; got parsed={aa.effect!r}, "
        f"bridged={bridged!r}"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — Rust's parse_effect arm accepts
# the bridged become_land_creature_ueot dict shape on a Mutavault-shape
# Land carrier.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_mutavault_become_land_creature_ueot_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the
    ``become_land_creature_ueot`` dict shape on a Mutavault-shape Land
    carrier."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Mutavault (synthetic carrier)",
            "card_types": ["Land"],
            "mana_cost": {"generic": 0},
            "effects": [],
            "activated_abilities": [
                {
                    "cost": {"mana": {"generic": 1}},
                    "effect": {
                        "kind": "become_land_creature_ueot",
                        "power": 2,
                        "toughness": 2,
                    },
                    "is_mana_ability": False,
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Mutavault printing on Python-side resolve for the
# BecomeLandCreatureUEOT effect.  Mirrors the FFFF EEEE-idiom (parse +
# bridge round-trip + Python-side resolve, NO cross-engine
# compare_fields).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_mutavault_animation_ability_bare_2_2_parity():
    """**GENUINE real-EoE cross-engine probe — Mutavault animation
    ability → BecomeLandCreatureUEOT(power=2, toughness=2, bare-
    riders). PROBED-tier flip (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Mutavault printing** on the Python side
    through the BecomeLandCreatureUEOT effect's resolve path.  Mirrors
    the FFFF EEEE-idiom (parse + bridge round-trip + Python-side
    resolve, no cross-engine ``compare_fields``); same lane discipline
    as batches 1-6.

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
    binding the Mutavault slug — AND the BecomeLandCreatureUEOT Effect
    class as a whole — to the bare ``become_land_creature_ueot`` bridge
    arm.  Distinct from the batches 1-6 sibling probes — Mutavault is
    the FIRST PROBE_MODULES-credited real-EoE probe on this Effect
    class; the other manlands in the covered_by_construction tier
    (Celestial Colonnade / Creeping Tar Pit / Hissing Quagmire /
    Lumbering Falls / Needle Spires / Raging Ravine / Shambling Vent /
    Stirring Wildwood / Inkmoth Nexus) all carry granted_keywords /
    unblockable / granted_triggered_abilities riders that the bare
    bridge arm signature does NOT round-trip clean and stay covered_
    by_construction under the IIII / HHHH "covered carrier with non-
    bridge-clean rider" precedent.

    **Bridge arm exercised:**
      * ``become_land_creature_ueot`` (bare signature; power +
        toughness fields; all rider fields default to bare/None).

    **AA-cost-substrate deferral.**  The full activated-ability cost-
    payment trajectory ({1}+{T} cost atom on the ActivationCost,
    sorcery-speed restriction, stack-resolve push/pop semantics, cross-
    engine observer parity on the post-resolve UEOT-modifier registry
    entries) is the cost-substrate / test_probe_activated_abilities
    family scope and stays substrate-deferred for this lane.  Per-slug
    attribution credits the slug based on the Effect+bridge byte-
    equality alone (the round-1 PROBED-tier definition + the batches
    1-6 EEEE-idiom precedent).

    **Setup (Python-side):**
      * p0 has Mutavault on the battlefield (the AA source; the
        Effect resolves on the source's controller).
      * The Mutavault permanent pre-resolve reads as a non-Creature
        Land (effective P/T = 0 / 0; is_creature_now=False).

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "become_land_creature_ueot", "power": 2, "toughness":
        2}`` translates to ``BecomeLandCreatureUEOT(power=2,
        toughness=2, granted_keywords=frozenset(), unblockable=False,
        granted_subtype=None, granted_activated_abilities=(),
        granted_triggered_abilities=())``.
      * The carrier's animation ActivatedAbility emits the same Effect.
      * Effect-level byte-equality between the parsed real-EoE emission
        and the bridged Effect.
      * Post-resolve: the Mutavault permanent reads as a 2/2 Creature
        on Python's combat readers (effective_power=2,
        effective_toughness=2, is_creature_now=True — the layer-4
        add_type + layer-7 set_base_pt registry entries fire with
        ``expires_at="cleanup"``).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.game import (
        Zone, effective_power, effective_toughness, is_creature_now,
    )

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Mutavault printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Mutavault")
    if real is None:
        pytest.skip("Mutavault absent from active CardSource")
    assert "Land" in real.card_types
    anim_aas = [
        aa
        for aa in real.activated_abilities
        if isinstance(aa.effect, BecomeLandCreatureUEOT)
    ]
    assert len(anim_aas) == 1
    aa = anim_aas[0]
    assert aa.effect.power == 2
    assert aa.effect.toughness == 2
    assert aa.effect.granted_keywords == frozenset()
    assert aa.effect.unblockable is False
    assert aa.effect.granted_subtype is None

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "become_land_creature_ueot", "power": 2, "toughness": 2}
    )
    assert isinstance(bridged, BecomeLandCreatureUEOT)
    assert aa.effect == bridged, (
        f"Mutavault animation Effect must be byte-equal to bridged; "
        f"got parsed={aa.effect!r}, bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling BecomeLandCreatureUEOT shapes
    #    (regression guard).  Mutavault's all-bare-riders shape is
    #    the only round-trip-clean manland in the covered_by_
    #    construction tier — the other manlands' shaped variants
    #    diverge on granted_keywords / unblockable / granted_triggered_
    #    abilities riders that the bare bridge arm signature drops.
    # ------------------------------------------------------------------
    assert bridged.power == 2 and bridged.toughness == 2, (
        "Bridged Effect must produce a 2/2 — distinct from Creeping "
        "Tar Pit (3/2) / Celestial Colonnade (4/4) / Inkmoth Nexus "
        "(1/1) / Lumbering Falls (3/3) / Stirring Wildwood (3/4) etc."
    )
    assert bridged.granted_keywords == frozenset(), (
        "Bridged Effect must carry NO granted_keywords — the bare-"
        "riders distinguishing shape vs Inkmoth Nexus's flying+infect "
        "/ Celestial Colonnade's flying+vigilance / etc."
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke — drive the parsed effect through
    #    its actual resolve path.  The Mutavault permanent becomes a
    #    2/2 Creature UEOT (layer-4 add_type + layer-7 set_base_pt
    #    registry entries write with ``expires_at="cleanup"``).
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Seat the GENUINE parsed Mutavault on p0's bf (the AA source).
    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Pre-resolve sanity: the Mutavault permanent reads as a non-
    # Creature Land (effective P/T = 0 / 0).
    assert is_creature_now(py_source) is False, (
        "pre-resolve: Mutavault must NOT yet be a Creature (the "
        "animation AA has not fired)"
    )
    assert effective_power(py_state, py_source) == 0
    assert effective_toughness(py_state, py_source) == 0

    # ``BecomeLandCreatureUEOT.resolve`` reads ``state.resolving_source``
    # to know which permanent to animate — the AA-resolution machinery
    # stamps this before calling Effect.resolve.  Mirror that by
    # setting it directly here (the cost-substrate trajectory is
    # deferred — we drive the Effect bare).
    py_state.resolving_source = py_source

    # Drive the BecomeLandCreatureUEOT effect through resolve directly.
    aa.effect.resolve(py_state, py_source.controller_id)

    # Post-resolve: the Mutavault permanent reads as a 2/2 Creature
    # on Python's combat readers (layer-4 add_type + layer-7
    # set_base_pt registry entries fire with ``expires_at="cleanup"``).
    assert is_creature_now(py_source) is True, (
        "post-resolve: Mutavault must read as a Creature on the layer-"
        "4 add_type registry entry"
    )
    assert effective_power(py_state, py_source) == 2, (
        f"post-resolve: Mutavault effective_power must be 2 (the "
        f"layer-7 set_base_pt registry entry's bare-2/2 shape); got "
        f"{effective_power(py_state, py_source)}"
    )
    assert effective_toughness(py_state, py_source) == 2, (
        f"post-resolve: Mutavault effective_toughness must be 2; got "
        f"{effective_toughness(py_state, py_source)}"
    )
    # Mutavault is STILL a Land per the printed rider; the layer-4
    # registry entry ADDED "creature" without REMOVING "land".
    assert "Land" in py_source.printing.card_types, (
        "Mutavault's underlying printing.card_types still carries "
        "'Land' — the BecomeLandCreatureUEOT animation ADDS the "
        "Creature type without dropping the Land type"
    )
