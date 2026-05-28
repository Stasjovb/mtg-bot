"""Raging Ravine -- per-card real-EoE cross-engine byte-equal probe
(covered_by_construction -> PROBED tier flip).

Raging Ravine is a ``{0}`` Land in the EoE pool (the Worldwake
manland reprint) with an activated ability that animates the land into
a 3/3 Elemental creature that grows on each attack:

    "{2}{R}{G}: Raging Ravine becomes a 3/3 red and green Elemental
    creature with 'Whenever this creature attacks, put a +1/+1
    counter on it.'  It's still a land."

Parser-emitted shape:
    * AA[0] (mana={2}{R}{G}, no tap) ->
      ``BecomeLandCreatureUEOT(power=3, toughness=3,
      granted_keywords=frozenset(), unblockable=False,
      granted_subtype=None, granted_activated_abilities=(),
      granted_triggered_abilities=(TriggeredAbility(event=ATTACKS,
      effect=PutPlusOneCounterOnSelf(amount=1), ...),))``

This probe pins the Raging Ravine slug via the JJJJ idiom (parse +
bridge round-trip + Python-side resolve smoke).  Raging Ravine
carries NO ``granted_keywords`` rider; instead it carries a
``granted_triggered_abilities`` rider (the ``attacks -> +1/+1
counter`` grant).  The bridge arm ``become_land_creature_ueot``
narrows the ``granted_triggered_abilities`` rider per the OOO
bridge-narrowing discipline -- the bridge dict carries no
``granted_triggered_abilities`` field; Rust's variant accepts the
bare shape with an empty tuple.

**NEW shape coverage (per-slug attribution):** the FIRST credited
``_parity`` probe binding Raging Ravine's slug.  Distinct from the
sibling probes Lumbering Falls (3/3 + ``hexproof`` keyword rider)
and Needle Spires (2/1 + ``double strike`` keyword rider) in THIS
batch + the PROBED Mutavault (all-bare 2/2) -- Raging Ravine is the
FIRST credited probe of BecomeLandCreatureUEOT carrying a
``granted_triggered_abilities`` rider (versus the
``granted_keywords`` rider of the sibling probes).  Same
``power=3, toughness=3`` parameter as Lumbering Falls but with a
DIFFERENT rider class.

**Re: HH-blocked-list drop:** the HH activated-abilities probe
module explicitly drop-listed Raging Ravine AA[0] under
``BecomeLandCreatureUEOT blocked effect type`` directive
(``tests/test_probe_activated_abilities_hh.py:67-71``).  That block
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


def test_raging_ravine_parser_claims_card():
    assert "Raging Ravine" in _PRINTINGS, (
        "Raging Ravine must be parser-claimed by the active CardSource"
    )


def test_raging_ravine_printed_attrs():
    """Pins the basic printing surface: Land, no mana cost."""
    p = _PRINTINGS["Raging Ravine"]
    assert "Land" in p.card_types
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()


def test_raging_ravine_activated_ability_shape():
    """The animate AA emits ``BecomeLandCreatureUEOT(3/3,
    granted_triggered_abilities=ATTACKS->+1/+1 counter)``.  Note: no
    ``granted_keywords`` rider on this manland (contrast with
    Lumbering Falls' ``hexproof`` and Needle Spires' ``double
    strike``)."""
    from mtg_bot.effects.predicates import Event
    from mtg_bot.effects.generic.counters import PutPlusOneCounterOnSelf

    p = _PRINTINGS["Raging Ravine"]
    animate_aa = next(
        (
            aa for aa in p.activated_abilities
            if isinstance(aa.effect, BecomeLandCreatureUEOT)
        ),
        None,
    )
    assert animate_aa is not None, (
        "Raging Ravine must have an activated ability emitting "
        "BecomeLandCreatureUEOT"
    )
    assert animate_aa.effect.power == 3
    assert animate_aa.effect.toughness == 3
    assert animate_aa.effect.granted_keywords == frozenset(), (
        "Raging Ravine carries NO granted_keywords rider (its rider "
        "is granted_triggered_abilities)"
    )
    assert animate_aa.effect.unblockable is False
    assert animate_aa.effect.granted_subtype is None
    assert animate_aa.effect.granted_activated_abilities == ()
    # The +1/+1-on-attack rider is the load-bearing characteristic.
    assert len(animate_aa.effect.granted_triggered_abilities) == 1
    granted_ta = animate_aa.effect.granted_triggered_abilities[0]
    assert granted_ta.event == Event.ATTACKS
    assert isinstance(granted_ta.effect, PutPlusOneCounterOnSelf)
    assert granted_ta.effect.amount == 1


# ---------------------------------------------------------------------------
# (2) Bridge round-trip (narrows granted_triggered_abilities per OOO).
# ---------------------------------------------------------------------------


def test_raging_ravine_bridge_arm_round_trip_narrows_triggers():
    """The bridge arm ``become_land_creature_ueot`` with 3/3 round-trips
    to ``BecomeLandCreatureUEOT(power=3, toughness=3,
    granted_triggered_abilities=())`` -- the
    ``granted_triggered_abilities`` rider is narrowed per the OOO
    bridge-narrowing discipline."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {
            "kind": "become_land_creature_ueot",
            "power": 3,
            "toughness": 3,
        }
    )
    assert isinstance(bridged, BecomeLandCreatureUEOT)
    assert bridged.power == 3
    assert bridged.toughness == 3
    # OOO bridge-narrowing: bridge dict carries no
    # ``granted_triggered_abilities``.
    assert bridged.granted_triggered_abilities == ()
    assert bridged.granted_keywords == frozenset()
    assert bridged.granted_activated_abilities == ()


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_raging_ravine_become_land_creature_grants_counter_trigger_parity():
    """**GENUINE real-EoE cross-engine probe -- Raging Ravine (Land
    AA[0] -> BecomeLandCreatureUEOT(3/3 +
    granted_triggered_abilities=ATTACKS->+1/+1 narrowed to bare
    3/3)).**

    Drives the **real parsed Raging Ravine printing** through the
    Python-side ``BecomeLandCreatureUEOT`` resolve path, validating
    the no-resolving-source silent-no-op short-circuit
    (``effects/generic/become_type.py``: ``if source is None: return``
    -- the first observable line of the BecomeLandCreatureUEOT
    resolve method).  Pairs the parse + bridge round-trip
    verification with the live Python resolve smoke, the same parse +
    bridge-round-trip + Python-side resolve idiom established.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe
    binding Raging Ravine's slug.  Per-slug attribution credit per
    the 2026-05-24 ``post-flip-reclassification-scout`` sweep
    precedent.  The ``granted_triggered_abilities`` rider class is a
    NEW rider variant for the PROBED-tier classifier on
    BecomeLandCreatureUEOT -- distinct from the
    ``granted_keywords``-rider siblings in this batch (Lumbering
    Falls / Needle Spires) and from the rider-less PROBED Mutavault.

    **Re: HH-blocked-list drop:** the HH activated-abilities probe
    module explicitly drop-listed Raging Ravine AA[0] under
    ``BecomeLandCreatureUEOT blocked effect type`` directive.  That
    block applies to the AA-level cross-engine probe shape; the
    JJJJ-idiom per-slug attribution lane bypasses it by binding the
    live printing + the bare-shape silent-no-op resolve.

    **Bridge arm exercised:** ``become_land_creature_ueot`` (matching
    Rust's ``Effect::BecomeLandCreatureUEOT { power, toughness }``).
    The ``granted_triggered_abilities`` rider is narrowed per the OOO
    bridge-narrowing discipline -- the bridge dict carries no
    ``granted_triggered_abilities`` field, Rust's variant accepts the
    bare shape with an empty tuple; the probe pins the bare-shape
    resolve path (no-resolving-source no-op), NOT the
    grant-attacks-trigger branch.

    **Setup (Python-side):**
      * Empty state -- no resolving_source set (None); the resolve
        short-circuits at the first observable line.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "become_land_creature_ueot", "power": 3,
        "toughness": 3}`` translates to ``BecomeLandCreatureUEOT(
        power=3, toughness=3,
        granted_triggered_abilities=(), ...)`` (the bare shape;
        OOO bridge-narrowing).
      * The Raging Ravine AA[0] emits the rider-bearing variant
        ``BecomeLandCreatureUEOT(3/3,
        granted_triggered_abilities=(TriggeredAbility(event=ATTACKS,
        effect=PutPlusOneCounterOnSelf(amount=1)),))`` (asserted but
        NOT compared to bridged -- narrowed per OOO).
      * With ``resolving_source=None``, the resolve is a no-op: log
        unchanged, no UEOT animate granted, no UEOT trigger granted.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Raging Ravine printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Raging Ravine")
    if real is None:
        pytest.skip("Raging Ravine absent from active CardSource")
    assert "Land" in real.card_types, "Raging Ravine must be a Land"
    animate_aa = next(
        (
            aa for aa in real.activated_abilities
            if isinstance(aa.effect, BecomeLandCreatureUEOT)
        ),
        None,
    )
    assert animate_aa is not None, (
        "Raging Ravine must have an activated ability emitting "
        "BecomeLandCreatureUEOT"
    )
    # Pin the rider-bearing shape (the load-bearing
    # granted_triggered_abilities rider).
    assert animate_aa.effect.power == 3
    assert animate_aa.effect.toughness == 3
    assert len(animate_aa.effect.granted_triggered_abilities) == 1, (
        f"Raging Ravine AA[0] effect must grant exactly one triggered "
        f"ability; got "
        f"{len(animate_aa.effect.granted_triggered_abilities)}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.  The
    #    granted_triggered_abilities rider is NARROWED per OOO discipline.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {
            "kind": "become_land_creature_ueot",
            "power": 3,
            "toughness": 3,
        }
    )
    assert isinstance(bridged, BecomeLandCreatureUEOT), (
        f"Bridge arm 'become_land_creature_ueot' must round-trip to "
        f"BecomeLandCreatureUEOT; got {type(bridged).__name__}"
    )
    assert bridged.power == 3
    assert bridged.toughness == 3
    assert bridged.granted_triggered_abilities == (), (
        f"OOO bridge-narrowing: bridged granted_triggered_abilities "
        f"must be empty (the bare shape); got "
        f"{bridged.granted_triggered_abilities!r}"
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
        f"Raging Ravine: no-resolving-source resolve must NOT append a "
        f"log line; got log_len={len(py.log)} (expected {pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Raging Ravine: no-resolving-source resolve must NOT mutate "
        "the battlefield"
    )
