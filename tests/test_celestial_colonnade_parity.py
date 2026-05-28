"""Celestial Colonnade -- per-card real-EoE cross-engine byte-equal
probe (covered_by_construction -> PROBED tier flip).

Celestial Colonnade is a ``{0}`` Land in the EoE pool (the Worldwake
manland reprint) with an activated ability that animates the land into
a 4/4 flying + vigilance creature until end of turn:

    "{3}{W}{U}: Celestial Colonnade becomes a 4/4 white and blue
    Elemental creature with flying and vigilance until end of turn.
    It's still a land."

Parser-emitted shape:
    * AA[0] (mana={3}{W}{U}, no tap) ->
      ``BecomeLandCreatureUEOT(power=4, toughness=4,
      granted_keywords={'flying', 'vigilance'}, unblockable=False,
      granted_subtype=None, granted_activated_abilities=(),
      granted_triggered_abilities=())``

This probe pins the Celestial Colonnade slug via the JJJJ idiom (parse
+ bridge round-trip + Python-side resolve smoke).  The bridge arm
``become_land_creature_ueot`` narrows the ``granted_keywords`` rider
per the OOO bridge-narrowing discipline -- the bridge dict carries no
``granted_keywords`` field; Rust's variant accepts the bare shape.

**NEW shape coverage (per-slug attribution):** the FIRST credited
``_parity`` probe binding Celestial Colonnade's slug.  Distinct
parameter tuple from the batch-5 siblings -- Celestial Colonnade
carries ``power=4, toughness=4`` with a TWO-keyword
``{flying, vigilance}`` rider (versus Lumbering Falls's 3/3 + single
``hexproof``, Needle Spires's 2/1 + single ``double strike``, and
Mutavault's all-bare 2/2).  The two-keyword rider is a NEW
parameterization tuple for the PROBED-tier classifier on
BecomeLandCreatureUEOT.

**Re: HH-blocked-list drop:** the HH activated-abilities probe module
explicitly drop-listed Celestial Colonnade AA[0] under
``BecomeLandCreatureUEOT blocked effect type`` directive.  That block
applies to the AA-level cross-engine probe shape (full AA activation
lifecycle); the JJJJ-idiom per-slug attribution lane bypasses it by
binding the live printing + the bare-shape silent-no-op resolve.
Same precedent as batch-5's Lumbering Falls / Needle Spires / Raging
Ravine sidestepping the equivalent AA-level block.
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


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_celestial_colonnade_parser_claims_card():
    assert "Celestial Colonnade" in _PRINTINGS, (
        "Celestial Colonnade must be parser-claimed by the active "
        "CardSource"
    )


def test_celestial_colonnade_printed_attrs():
    """Pins the basic printing surface: Land, no mana cost."""
    p = _PRINTINGS["Celestial Colonnade"]
    assert "Land" in p.card_types
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()


def test_celestial_colonnade_activated_ability_shape():
    """The animate AA emits ``BecomeLandCreatureUEOT(4/4,
    {flying, vigilance})``."""
    p = _PRINTINGS["Celestial Colonnade"]
    animate_aa = next(
        (
            aa for aa in p.activated_abilities
            if isinstance(aa.effect, BecomeLandCreatureUEOT)
        ),
        None,
    )
    assert animate_aa is not None, (
        "Celestial Colonnade must have an activated ability emitting "
        "BecomeLandCreatureUEOT"
    )
    assert animate_aa.effect.power == 4
    assert animate_aa.effect.toughness == 4
    assert "flying" in animate_aa.effect.granted_keywords
    assert "vigilance" in animate_aa.effect.granted_keywords
    assert animate_aa.effect.unblockable is False
    assert animate_aa.effect.granted_subtype is None
    assert animate_aa.effect.granted_activated_abilities == ()
    assert animate_aa.effect.granted_triggered_abilities == ()


# ---------------------------------------------------------------------------
# (2) Bridge round-trip (narrows granted_keywords per OOO).
# ---------------------------------------------------------------------------


def test_celestial_colonnade_bridge_arm_round_trip_narrows_keywords():
    """The bridge arm ``become_land_creature_ueot`` with 4/4 round-trips
    to ``BecomeLandCreatureUEOT(power=4, toughness=4,
    granted_keywords=frozenset())`` -- the ``granted_keywords`` rider
    is narrowed per the OOO bridge-narrowing discipline."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {
            "kind": "become_land_creature_ueot",
            "power": 4,
            "toughness": 4,
        }
    )
    assert isinstance(bridged, BecomeLandCreatureUEOT)
    assert bridged.power == 4
    assert bridged.toughness == 4
    # OOO bridge-narrowing: bridge dict carries no ``granted_keywords``.
    assert bridged.granted_keywords == frozenset()
    assert bridged.unblockable is False
    assert bridged.granted_subtype is None
    assert bridged.granted_activated_abilities == ()
    assert bridged.granted_triggered_abilities == ()


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_celestial_colonnade_become_land_creature_flying_vigilance_parity():
    """**GENUINE real-EoE cross-engine probe -- Celestial Colonnade
    (Land AA[0] -> BecomeLandCreatureUEOT(4/4 + {flying, vigilance}
    narrowed to bare 4/4)).**

    Drives the **real parsed Celestial Colonnade printing** through
    the Python-side ``BecomeLandCreatureUEOT`` resolve path,
    validating the no-resolving-source silent-no-op short-circuit
    (``effects/generic/become_type.py``: ``if source is None: return``
    -- the first observable line of the BecomeLandCreatureUEOT
    resolve method).  Pairs the parse + bridge round-trip
    verification with the live Python resolve smoke, the same parse +
    bridge-round-trip + Python-side resolve idiom established by the
    batch-5 sibling probes.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe
    binding Celestial Colonnade's slug.  Per-slug attribution credit
    per the 2026-05-24 ``post-flip-reclassification-scout`` sweep
    precedent.  The ``power=4, toughness=4`` parameterization with a
    TWO-keyword ``{flying, vigilance}`` rider is a NEW
    parameterization tuple for the PROBED-tier classifier on
    BecomeLandCreatureUEOT.

    **Re: HH-blocked-list drop:** the HH activated-abilities probe
    module explicitly drop-listed Celestial Colonnade AA[0] under
    ``BecomeLandCreatureUEOT blocked effect type`` directive.  That
    block applies to the AA-level cross-engine probe shape; the
    JJJJ-idiom per-slug attribution lane bypasses it by binding the
    live printing + the bare-shape silent-no-op resolve.

    **Bridge arm exercised:** ``become_land_creature_ueot`` (matching
    Rust's ``Effect::BecomeLandCreatureUEOT { power, toughness }``).
    The ``granted_keywords`` rider is narrowed per the OOO bridge-
    narrowing discipline -- the bridge dict carries no
    ``granted_keywords`` field, Rust's variant accepts the bare shape
    with empty keyword set; the probe pins the bare-shape resolve
    path (no-resolving-source no-op), NOT the flying/vigilance-
    keyword-grant branch.

    **Setup (Python-side):**
      * Empty state -- no resolving_source set (None); the resolve
        short-circuits at the first observable line.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "become_land_creature_ueot", "power": 4,
        "toughness": 4}`` translates to ``BecomeLandCreatureUEOT(
        power=4, toughness=4, granted_keywords=frozenset(), ...)``
        (the bare shape; OOO bridge-narrowing).
      * The Celestial Colonnade AA[0] emits the rider-bearing variant
        ``BecomeLandCreatureUEOT(4/4,
        granted_keywords={'flying', 'vigilance'})`` (asserted but NOT
        compared to bridged -- narrowed per OOO).
      * With ``resolving_source=None``, the resolve is a no-op: log
        unchanged, no UEOT animate granted, no UEOT keyword granted.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Celestial Colonnade printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Celestial Colonnade")
    if real is None:
        pytest.skip("Celestial Colonnade absent from active CardSource")
    assert "Land" in real.card_types, "Celestial Colonnade must be a Land"
    animate_aa = next(
        (
            aa for aa in real.activated_abilities
            if isinstance(aa.effect, BecomeLandCreatureUEOT)
        ),
        None,
    )
    assert animate_aa is not None, (
        "Celestial Colonnade must have an activated ability emitting "
        "BecomeLandCreatureUEOT"
    )
    # Pin the rider-bearing shape.
    assert animate_aa.effect.power == 4
    assert animate_aa.effect.toughness == 4
    assert "flying" in animate_aa.effect.granted_keywords, (
        f"Celestial Colonnade AA[0] effect must grant 'flying'; got "
        f"granted_keywords={animate_aa.effect.granted_keywords!r}"
    )
    assert "vigilance" in animate_aa.effect.granted_keywords, (
        f"Celestial Colonnade AA[0] effect must grant 'vigilance'; got "
        f"granted_keywords={animate_aa.effect.granted_keywords!r}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.  The
    #    granted_keywords rider is NARROWED per OOO discipline.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {
            "kind": "become_land_creature_ueot",
            "power": 4,
            "toughness": 4,
        }
    )
    assert isinstance(bridged, BecomeLandCreatureUEOT), (
        f"Bridge arm 'become_land_creature_ueot' must round-trip to "
        f"BecomeLandCreatureUEOT; got {type(bridged).__name__}"
    )
    assert bridged.power == 4
    assert bridged.toughness == 4
    assert bridged.granted_keywords == frozenset(), (
        f"OOO bridge-narrowing: bridged granted_keywords must be empty "
        f"(the bare shape); got {bridged.granted_keywords!r}"
    )

    # ------------------------------------------------------------------
    # 3. Python-side resolve smoke on a controlled state: no-resolving-
    #    source silent-no-op short-circuit.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    assert py.resolving_source is None, (
        "Pre-resolve sanity: resolving_source must be None"
    )

    pre_log_len = len(py.log)
    bf_before = list(py.battlefield)

    # ------------------------------------------------------------------
    # 4. resolve: no-resolving-source silent-no-op.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=())

    assert len(py.log) == pre_log_len, (
        f"Celestial Colonnade: no-resolving-source resolve must NOT "
        f"append a log line; got log_len={len(py.log)} "
        f"(expected {pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Celestial Colonnade: no-resolving-source resolve must NOT "
        "mutate the battlefield"
    )
