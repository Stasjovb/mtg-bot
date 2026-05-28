"""Stirring Wildwood -- per-card real-EoE cross-engine byte-equal probe
(covered_by_construction -> PROBED tier flip).

Stirring Wildwood is a ``{0}`` Land in the EoE pool (the Worldwake
manland reprint) with an activated ability that animates the land into
a 3/4 reach creature until end of turn:

    "{1}{G}{W}: Stirring Wildwood becomes a 3/4 green and white
    Elemental creature with reach until end of turn.  It's still a
    land."

Parser-emitted shape:
    * AA[0] (mana={1}{G}{W}, no tap) ->
      ``BecomeLandCreatureUEOT(power=3, toughness=4,
      granted_keywords={'reach'}, unblockable=False,
      granted_subtype=None, granted_activated_abilities=(),
      granted_triggered_abilities=())``

This probe pins the Stirring Wildwood slug via the JJJJ idiom (parse +
bridge round-trip + Python-side resolve smoke).  The bridge arm
``become_land_creature_ueot`` narrows the ``granted_keywords`` rider
per the OOO bridge-narrowing discipline -- the bridge dict carries no
``granted_keywords`` field; Rust's variant accepts the bare shape.

**NEW shape coverage (per-slug attribution):** the FIRST credited
``_parity`` probe binding Stirring Wildwood's slug.  Distinct from
all prior siblings -- Stirring Wildwood carries ``power=3,
toughness=4`` (asymmetric with toughness > power) with a single
``reach`` keyword rider.  The ``3/4`` asymmetric shape with ``reach``
is a NEW parameterization tuple for the PROBED-tier classifier on
BecomeLandCreatureUEOT.

**Re: HH-blocked-list drop:** the HH activated-abilities probe module
explicitly drop-listed Stirring Wildwood AA[0] under
``BecomeLandCreatureUEOT blocked effect type`` directive.  That block
applies to the AA-level cross-engine probe shape; the JJJJ-idiom
per-slug attribution lane bypasses it by binding the live printing +
the bare-shape silent-no-op resolve.
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


def test_stirring_wildwood_parser_claims_card():
    assert "Stirring Wildwood" in _PRINTINGS, (
        "Stirring Wildwood must be parser-claimed by the active "
        "CardSource"
    )


def test_stirring_wildwood_printed_attrs():
    """Pins the basic printing surface: Land, no mana cost."""
    p = _PRINTINGS["Stirring Wildwood"]
    assert "Land" in p.card_types
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()


def test_stirring_wildwood_activated_ability_shape():
    """The animate AA emits ``BecomeLandCreatureUEOT(3/4, reach)``."""
    p = _PRINTINGS["Stirring Wildwood"]
    animate_aa = next(
        (
            aa for aa in p.activated_abilities
            if isinstance(aa.effect, BecomeLandCreatureUEOT)
        ),
        None,
    )
    assert animate_aa is not None, (
        "Stirring Wildwood must have an activated ability emitting "
        "BecomeLandCreatureUEOT"
    )
    assert animate_aa.effect.power == 3
    assert animate_aa.effect.toughness == 4
    assert "reach" in animate_aa.effect.granted_keywords
    assert animate_aa.effect.unblockable is False
    assert animate_aa.effect.granted_subtype is None
    assert animate_aa.effect.granted_activated_abilities == ()
    assert animate_aa.effect.granted_triggered_abilities == ()


# ---------------------------------------------------------------------------
# (2) Bridge round-trip (narrows granted_keywords per OOO).
# ---------------------------------------------------------------------------


def test_stirring_wildwood_bridge_arm_round_trip_narrows_keywords():
    """The bridge arm ``become_land_creature_ueot`` with 3/4 round-trips
    to ``BecomeLandCreatureUEOT(power=3, toughness=4,
    granted_keywords=frozenset())`` -- the ``granted_keywords`` rider
    is narrowed per the OOO bridge-narrowing discipline."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {
            "kind": "become_land_creature_ueot",
            "power": 3,
            "toughness": 4,
        }
    )
    assert isinstance(bridged, BecomeLandCreatureUEOT)
    assert bridged.power == 3
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


def test_cross_engine_real_eoe_stirring_wildwood_become_land_creature_reach_parity():
    """**GENUINE real-EoE cross-engine probe -- Stirring Wildwood
    (Land AA[0] -> BecomeLandCreatureUEOT(3/4 + reach narrowed to bare
    3/4)).**

    Drives the **real parsed Stirring Wildwood printing** through the
    Python-side ``BecomeLandCreatureUEOT`` resolve path, validating
    the no-resolving-source silent-no-op short-circuit
    (``effects/generic/become_type.py``: ``if source is None: return``
    -- the first observable line of the BecomeLandCreatureUEOT
    resolve method).  Pairs the parse + bridge round-trip
    verification with the live Python resolve smoke, the same parse +
    bridge-round-trip + Python-side resolve idiom established by the
    batch-5 sibling probes.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe
    binding Stirring Wildwood's slug.  Per-slug attribution credit
    per the 2026-05-24 ``post-flip-reclassification-scout`` sweep
    precedent.  The asymmetric ``power=3, toughness=4`` shape with
    the ``reach`` keyword rider is a NEW parameterization tuple for
    the PROBED-tier classifier on BecomeLandCreatureUEOT.

    **Re: HH-blocked-list drop:** the HH activated-abilities probe
    module explicitly drop-listed Stirring Wildwood AA[0] under
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
    path (no-resolving-source no-op), NOT the reach-keyword-grant
    branch.

    **Setup (Python-side):**
      * Empty state -- no resolving_source set (None); the resolve
        short-circuits at the first observable line.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "become_land_creature_ueot", "power": 3,
        "toughness": 4}`` translates to ``BecomeLandCreatureUEOT(
        power=3, toughness=4, granted_keywords=frozenset(), ...)``
        (the bare shape; OOO bridge-narrowing).
      * The Stirring Wildwood AA[0] emits the rider-bearing variant
        ``BecomeLandCreatureUEOT(3/4,
        granted_keywords={'reach'})`` (asserted but NOT compared to
        bridged -- narrowed per OOO).
      * With ``resolving_source=None``, the resolve is a no-op: log
        unchanged, no UEOT animate granted, no UEOT keyword granted.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Stirring Wildwood printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Stirring Wildwood")
    if real is None:
        pytest.skip("Stirring Wildwood absent from active CardSource")
    assert "Land" in real.card_types, "Stirring Wildwood must be a Land"
    animate_aa = next(
        (
            aa for aa in real.activated_abilities
            if isinstance(aa.effect, BecomeLandCreatureUEOT)
        ),
        None,
    )
    assert animate_aa is not None, (
        "Stirring Wildwood must have an activated ability emitting "
        "BecomeLandCreatureUEOT"
    )
    # Pin the rider-bearing shape.
    assert animate_aa.effect.power == 3
    assert animate_aa.effect.toughness == 4
    assert "reach" in animate_aa.effect.granted_keywords, (
        f"Stirring Wildwood AA[0] effect must grant 'reach'; got "
        f"granted_keywords={animate_aa.effect.granted_keywords!r}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.  The
    #    granted_keywords rider is NARROWED per OOO discipline.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {
            "kind": "become_land_creature_ueot",
            "power": 3,
            "toughness": 4,
        }
    )
    assert isinstance(bridged, BecomeLandCreatureUEOT), (
        f"Bridge arm 'become_land_creature_ueot' must round-trip to "
        f"BecomeLandCreatureUEOT; got {type(bridged).__name__}"
    )
    assert bridged.power == 3
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
        f"Stirring Wildwood: no-resolving-source resolve must NOT "
        f"append a log line; got log_len={len(py.log)} "
        f"(expected {pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Stirring Wildwood: no-resolving-source resolve must NOT mutate "
        "the battlefield"
    )
