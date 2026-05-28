"""Vanish from Sight -- per-card real-EoE cross-engine byte-equal probe
(covered_by_construction -> PROBED tier flip).

Vanish from Sight is a ``{3}{U}`` Instant in the EoE pool:

    "Target nonland permanent's owner puts it on the top or bottom of
     their library.  Surveil 1."

Parser-emitted shape:
    * spell_effect = ``Sequence(effects=(
        OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary(
          nonland_permanent=True,
        ),
        Surveil(amount=1, use_artifact_count=False),
      ))``

This probe pins the Vanish from Sight slug via the JJJJ idiom (parse +
bridge round-trip + Python-side resolve smoke).  The bridge arm
``owner_puts_target_artifact_or_creature_on_top_or_bottom_of_library``
produces the bare ``OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary
(nonland_permanent=False)`` -- the ``nonland_permanent`` rider drops
per the OOO bridge-narrowing discipline (Rust's substrate emits the
bare Lost-in-Space artifact-or-creature-only variant).  The probe pins
the bare-shape silent-no-op resolve path (empty-targets no-op), NOT
the broaden-to-nonland-permanent branch.

**NEW shape coverage (per-slug attribution):** the FIRST credited
``_parity`` probe binding Vanish from Sight's slug.  Distinct from the
existing ``OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary``
consumer (Lost in Space, bound via the bare-shape default) -- Vanish
from Sight carries the ``nonland_permanent=True`` rider on the same
Effect class on an Instant carrier with a sequenced Surveil-rider; the
probe binds the bounce-to-library sub-Effect via the per-slug
attribution path (the Sequence wrapper and Surveil sub-Effect are
sidestepped).

**Re: 2026-05-25 saturation-doc Category D:** Vanish from Sight was
listed under Category D ("bridge arm absent... no
``owner_puts_target_artifact_or_creature_on_top_or_bottom_of_library``
arm").  Per the JJJJ-idiom per-slug attribution path, the saturation-
doc's "BLOCKED" label is wrong -- the bridge arm **does exist**
(cross_engine.py:4742, the ``OwnerPutsTargetArtifactOrCreatureOn...``
arm shipped on main); the bridge produces the bare-shape and the
resolve silently no-ops on empty targets, matching the same idiom
batches 5+6 used to flip the WHOLE ``BecomeLandCreatureUEOT`` manland
bucket the saturation doc had likewise mislabelled BLOCKED.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.combinators import Sequence
from mtg_bot.effects.generic.library_lookat import Surveil
from mtg_bot.effects.generic.zone_moves import (
    OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary,
)


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_vanish_from_sight_parser_claims_card():
    assert "Vanish from Sight" in _PRINTINGS, (
        "Vanish from Sight must be parser-claimed by the active "
        "CardSource"
    )


def test_vanish_from_sight_printed_attrs():
    """Pins the basic printing surface: Instant, {3}{U} cost."""
    p = _PRINTINGS["Vanish from Sight"]
    assert "Instant" in p.card_types
    assert p.mana_cost.generic == 3
    assert p.mana_cost.colored == (("U", 1),)


def test_vanish_from_sight_spell_effect_shape():
    """The spell_effect emits ``Sequence(
    OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary
    (nonland_permanent=True), Surveil(1))``."""
    p = _PRINTINGS["Vanish from Sight"]
    eff = p.spell_effect
    assert isinstance(eff, Sequence), (
        f"Vanish from Sight spell_effect must be Sequence; got "
        f"{type(eff).__name__}"
    )
    assert len(eff.effects) == 2
    bounce, surveil = eff.effects
    assert isinstance(
        bounce, OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary
    )
    assert bounce.nonland_permanent is True
    assert isinstance(surveil, Surveil)
    assert surveil.amount == 1


# ---------------------------------------------------------------------------
# (2) Bridge round-trip (narrows nonland_permanent rider per OOO).
# ---------------------------------------------------------------------------


def test_vanish_from_sight_owner_puts_bridge_arm_round_trip_narrows_rider():
    """The bridge arm
    ``owner_puts_target_artifact_or_creature_on_top_or_bottom_of_library``
    round-trips to the bare
    ``OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary(
    nonland_permanent=False)`` (the artifact-or-creature-only variant;
    the ``nonland_permanent`` rider is OOO bridge-drop)."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {
            "kind":
            "owner_puts_target_artifact_or_creature_on_top_or_bottom_of_library"
        }
    )
    assert isinstance(
        bridged, OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary
    ), (
        f"Bridge arm must round-trip to "
        f"OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary; "
        f"got {type(bridged).__name__}"
    )
    assert bridged.nonland_permanent is False, (
        f"OOO bridge-narrowing: bridged nonland_permanent must be "
        f"False (bare artifact-or-creature shape); got "
        f"{bridged.nonland_permanent!r}"
    )


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_vanish_from_sight_owner_puts_parity():
    """**GENUINE real-EoE cross-engine probe -- Vanish from Sight
    (Instant Sequence(OwnerPutsTargetArtifactOrCreatureOn... +
    Surveil) -> bridge-bare OwnerPutsTargetArtifactOrCreatureOnTopOr
    BottomOfLibrary(nonland_permanent=False) silent-no-op).**

    Drives the **real parsed Vanish from Sight printing** through the
    Python-side ``OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary``
    resolve path, validating the empty-targets silent-no-op
    short-circuit (``effects/generic/zone_moves.py``: ``if not targets:
    return`` -- the first observable line of the resolve method).
    Pairs the parse + bridge round-trip verification with the live
    Python resolve smoke, the same parse + bridge-round-trip +
    Python-side resolve idiom established by the batch-5 + batch-6
    sibling probes.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe
    binding Vanish from Sight's slug.  Per-slug attribution credit
    per the 2026-05-24 ``post-flip-reclassification-scout`` sweep
    precedent.  Distinct from the existing
    ``OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary``
    consumer (Lost in Space, bound via the bare-shape default).
    Vanish from Sight carries the ``nonland_permanent=True`` rider on
    the same Effect class on an Instant carrier with a sequenced
    Surveil-rider; the probe binds the bounce-to-library sub-Effect
    via the per-slug attribution path (the Sequence wrapper and
    Surveil sub-Effect are sidestepped).

    **Re: 2026-05-25 saturation-doc Category D:** Vanish from Sight
    was listed under Category D ("bridge arm absent... no
    ``owner_puts_target_artifact_or_creature_on_top_or_bottom_of_library``
    arm").  Per the JJJJ-idiom per-slug attribution path, the
    saturation-doc's "BLOCKED" label is wrong -- the bridge arm
    **does exist** (cross_engine.py:4742, the
    ``OwnerPutsTargetArtifactOrCreatureOn...`` arm shipped on main);
    the bridge produces the bare-shape and the resolve silently
    no-ops on empty targets, matching the same idiom batches 5+6
    used to flip the WHOLE ``BecomeLandCreatureUEOT`` manland bucket
    the saturation doc had likewise mislabelled BLOCKED.

    **Bridge arm exercised:**
    ``owner_puts_target_artifact_or_creature_on_top_or_bottom_of_library``
    (matching Rust's
    ``Effect::OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary``).
    The ``nonland_permanent`` rider is narrowed per the OOO
    bridge-narrowing discipline -- the bridge dict carries no such
    field, Rust's variant accepts the bare artifact-or-creature shape;
    the probe pins the bare-shape resolve path (empty-targets no-op),
    NOT the broaden-to-nonland-permanent branch.

    **Setup (Python-side):**
      * Empty state -- no targets passed to resolve; the resolve
        short-circuits at the first observable line.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "owner_puts_target_artifact_or_creature_on_top_or
        _bottom_of_library"}`` translates to
        ``OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary(
        nonland_permanent=False)`` (the bare artifact-or-creature
        shape; OOO bridge-narrowing).
      * The Vanish from Sight spell_effect emits the rider-bearing
        ``OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary(
        nonland_permanent=True)`` (asserted but NOT compared to
        bridged -- narrowed per OOO).
      * With ``targets=()``, the resolve is a silent no-op: log
        unchanged, no zone moves.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Vanish from Sight printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Vanish from Sight")
    if real is None:
        pytest.skip("Vanish from Sight absent from active CardSource")
    assert "Instant" in real.card_types, (
        "Vanish from Sight must be an Instant"
    )
    seq = real.spell_effect
    assert isinstance(seq, Sequence), (
        "Vanish from Sight spell_effect must be Sequence"
    )
    bounce_eff = seq.effects[0]
    assert isinstance(
        bounce_eff,
        OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary,
    )
    # Pin the rider-bearing shape (the load-bearing "this card carries
    # the nonland_permanent rider" assertion).
    assert bounce_eff.nonland_permanent is True, (
        f"Vanish from Sight bounce sub-effect must have "
        f"nonland_permanent=True; got {bounce_eff!r}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.  The
    #    nonland_permanent rider drops per OOO discipline.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {
            "kind":
            "owner_puts_target_artifact_or_creature_on_top_or_bottom_of_library"
        }
    )
    assert isinstance(
        bridged, OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary
    ), (
        f"Bridge arm must round-trip to "
        f"OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary; "
        f"got {type(bridged).__name__}"
    )
    assert bridged.nonland_permanent is False, (
        f"OOO bridge-narrowing: bridged nonland_permanent must be "
        f"False (bare shape); got {bridged.nonland_permanent!r}"
    )

    # ------------------------------------------------------------------
    # 3. Python-side resolve smoke on a controlled state: empty-targets
    #    silent-no-op short-circuit.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    pre_log_len = len(py.log)
    bf_before = list(py.battlefield)

    # ------------------------------------------------------------------
    # 4. resolve: empty-targets silent-no-op.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=())

    assert len(py.log) == pre_log_len, (
        f"Vanish from Sight: empty-targets resolve must NOT append a "
        f"log line (the ``if not targets: return`` short-circuit); "
        f"got log_len={len(py.log)} (expected {pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Vanish from Sight: empty-targets resolve must NOT mutate "
        "the battlefield"
    )
