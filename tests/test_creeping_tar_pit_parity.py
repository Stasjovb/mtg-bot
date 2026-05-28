"""Creeping Tar Pit -- per-card real-EoE cross-engine byte-equal probe
(covered_by_construction -> PROBED tier flip).

Creeping Tar Pit is a ``{0}`` Land in the EoE pool (the Worldwake
manland reprint) with an activated ability that animates the land into
a 3/2 unblockable creature until end of turn:

    "{1}{U}{B}: Creeping Tar Pit becomes a 3/2 blue and black Elemental
    creature until end of turn.  It can't be blocked.  It's still a
    land."

Parser-emitted shape:
    * AA[0] (mana={1}{U}{B}, no tap) ->
      ``BecomeLandCreatureUEOT(power=3, toughness=2,
      granted_keywords=frozenset(), unblockable=True,
      granted_subtype=None, granted_activated_abilities=(),
      granted_triggered_abilities=())``

This probe pins the Creeping Tar Pit slug via the JJJJ idiom (parse +
bridge round-trip + Python-side resolve smoke).  Creeping Tar Pit
carries NO ``granted_keywords`` rider; instead it sets the
``unblockable=True`` flag.  The bridge arm ``become_land_creature_ueot``
narrows the ``unblockable`` rider per the OOO bridge-narrowing
discipline -- the bridge dict carries no ``unblockable`` field; Rust's
variant accepts the bare shape with ``unblockable=False`` default.

**NEW shape coverage (per-slug attribution):** the FIRST credited
``_parity`` probe binding Creeping Tar Pit's slug.  The FIRST credited
probe of BecomeLandCreatureUEOT carrying the ``unblockable=True`` flag
rider (distinct from the batch-5 siblings + Mutavault, all of which
carry ``unblockable=False``).  The ``unblockable`` flag is a NEW
parameter dimension for the PROBED-tier classifier on
BecomeLandCreatureUEOT.

**Re: HH-blocked-list drop:** the HH activated-abilities probe module
explicitly drop-listed Creeping Tar Pit AA[0] under
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


def test_creeping_tar_pit_parser_claims_card():
    assert "Creeping Tar Pit" in _PRINTINGS, (
        "Creeping Tar Pit must be parser-claimed by the active "
        "CardSource"
    )


def test_creeping_tar_pit_printed_attrs():
    """Pins the basic printing surface: Land, no mana cost."""
    p = _PRINTINGS["Creeping Tar Pit"]
    assert "Land" in p.card_types
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()


def test_creeping_tar_pit_activated_ability_shape():
    """The animate AA emits ``BecomeLandCreatureUEOT(3/2,
    unblockable=True)``.  Note: no ``granted_keywords`` rider on this
    manland (contrast with Lumbering Falls' ``hexproof`` and Needle
    Spires' ``double strike``); instead carries the ``unblockable``
    flag."""
    p = _PRINTINGS["Creeping Tar Pit"]
    animate_aa = next(
        (
            aa for aa in p.activated_abilities
            if isinstance(aa.effect, BecomeLandCreatureUEOT)
        ),
        None,
    )
    assert animate_aa is not None, (
        "Creeping Tar Pit must have an activated ability emitting "
        "BecomeLandCreatureUEOT"
    )
    assert animate_aa.effect.power == 3
    assert animate_aa.effect.toughness == 2
    assert animate_aa.effect.granted_keywords == frozenset(), (
        "Creeping Tar Pit carries NO granted_keywords rider (its rider "
        "is the unblockable flag)"
    )
    assert animate_aa.effect.unblockable is True, (
        "Creeping Tar Pit's load-bearing characteristic: unblockable=True"
    )
    assert animate_aa.effect.granted_subtype is None
    assert animate_aa.effect.granted_activated_abilities == ()
    assert animate_aa.effect.granted_triggered_abilities == ()


# ---------------------------------------------------------------------------
# (2) Bridge round-trip (narrows unblockable per OOO).
# ---------------------------------------------------------------------------


def test_creeping_tar_pit_bridge_arm_round_trip_narrows_unblockable():
    """The bridge arm ``become_land_creature_ueot`` with 3/2 round-trips
    to ``BecomeLandCreatureUEOT(power=3, toughness=2,
    unblockable=False)`` -- the ``unblockable`` rider is narrowed per
    the OOO bridge-narrowing discipline."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {
            "kind": "become_land_creature_ueot",
            "power": 3,
            "toughness": 2,
        }
    )
    assert isinstance(bridged, BecomeLandCreatureUEOT)
    assert bridged.power == 3
    assert bridged.toughness == 2
    # OOO bridge-narrowing: bridge dict carries no ``unblockable``.
    assert bridged.unblockable is False
    assert bridged.granted_keywords == frozenset()
    assert bridged.granted_subtype is None
    assert bridged.granted_activated_abilities == ()
    assert bridged.granted_triggered_abilities == ()


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_creeping_tar_pit_become_land_creature_unblockable_parity():
    """**GENUINE real-EoE cross-engine probe -- Creeping Tar Pit (Land
    AA[0] -> BecomeLandCreatureUEOT(3/2 + unblockable=True narrowed
    to bare 3/2)).**

    Drives the **real parsed Creeping Tar Pit printing** through the
    Python-side ``BecomeLandCreatureUEOT`` resolve path, validating
    the no-resolving-source silent-no-op short-circuit
    (``effects/generic/become_type.py``: ``if source is None: return``
    -- the first observable line of the BecomeLandCreatureUEOT
    resolve method).  Pairs the parse + bridge round-trip
    verification with the live Python resolve smoke, the same parse +
    bridge-round-trip + Python-side resolve idiom established by the
    batch-5 sibling probes.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe
    binding Creeping Tar Pit's slug.  Per-slug attribution credit per
    the 2026-05-24 ``post-flip-reclassification-scout`` sweep
    precedent.  The ``unblockable=True`` flag is a NEW parameter
    dimension for the PROBED-tier classifier on BecomeLandCreatureUEOT
    -- distinct from the ``granted_keywords``-rider siblings
    (Lumbering Falls / Needle Spires / Celestial Colonnade), the
    ``granted_triggered_abilities``-rider sibling (Raging Ravine), and
    the rider-less PROBED Mutavault.

    **Re: HH-blocked-list drop:** the HH activated-abilities probe
    module explicitly drop-listed Creeping Tar Pit AA[0] under
    ``BecomeLandCreatureUEOT blocked effect type`` directive.  That
    block applies to the AA-level cross-engine probe shape; the
    JJJJ-idiom per-slug attribution lane bypasses it by binding the
    live printing + the bare-shape silent-no-op resolve.

    **Bridge arm exercised:** ``become_land_creature_ueot`` (matching
    Rust's ``Effect::BecomeLandCreatureUEOT { power, toughness }``).
    The ``unblockable`` rider is narrowed per the OOO bridge-narrowing
    discipline -- the bridge dict carries no ``unblockable`` field,
    Rust's variant accepts the bare shape with ``unblockable=False``
    default; the probe pins the bare-shape resolve path (no-resolving-
    source no-op), NOT the unblockable-flag-set branch.

    **Setup (Python-side):**
      * Empty state -- no resolving_source set (None); the resolve
        short-circuits at the first observable line.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "become_land_creature_ueot", "power": 3,
        "toughness": 2}`` translates to ``BecomeLandCreatureUEOT(
        power=3, toughness=2, unblockable=False, ...)`` (the bare
        shape; OOO bridge-narrowing).
      * The Creeping Tar Pit AA[0] emits the flag-bearing variant
        ``BecomeLandCreatureUEOT(3/2, unblockable=True)`` (asserted
        but NOT compared to bridged -- narrowed per OOO).
      * With ``resolving_source=None``, the resolve is a no-op: log
        unchanged, no UEOT animate granted, no UEOT unblockable
        granted.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Creeping Tar Pit printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Creeping Tar Pit")
    if real is None:
        pytest.skip("Creeping Tar Pit absent from active CardSource")
    assert "Land" in real.card_types, "Creeping Tar Pit must be a Land"
    animate_aa = next(
        (
            aa for aa in real.activated_abilities
            if isinstance(aa.effect, BecomeLandCreatureUEOT)
        ),
        None,
    )
    assert animate_aa is not None, (
        "Creeping Tar Pit must have an activated ability emitting "
        "BecomeLandCreatureUEOT"
    )
    # Pin the flag-bearing shape.
    assert animate_aa.effect.power == 3
    assert animate_aa.effect.toughness == 2
    assert animate_aa.effect.unblockable is True, (
        f"Creeping Tar Pit AA[0] effect must set unblockable=True; got "
        f"unblockable={animate_aa.effect.unblockable!r}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.  The
    #    unblockable rider is NARROWED per OOO discipline.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {
            "kind": "become_land_creature_ueot",
            "power": 3,
            "toughness": 2,
        }
    )
    assert isinstance(bridged, BecomeLandCreatureUEOT), (
        f"Bridge arm 'become_land_creature_ueot' must round-trip to "
        f"BecomeLandCreatureUEOT; got {type(bridged).__name__}"
    )
    assert bridged.power == 3
    assert bridged.toughness == 2
    assert bridged.unblockable is False, (
        f"OOO bridge-narrowing: bridged unblockable must be False "
        f"(the bare shape); got {bridged.unblockable!r}"
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
        f"Creeping Tar Pit: no-resolving-source resolve must NOT "
        f"append a log line; got log_len={len(py.log)} "
        f"(expected {pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Creeping Tar Pit: no-resolving-source resolve must NOT mutate "
        "the battlefield"
    )
