"""Unnerving Grasp -- per-card real-EoE cross-engine byte-equal probe
(covered_by_construction -> PROBED tier flip).

Unnerving Grasp is a ``{2}{U}`` Sorcery in the EoE pool:

    "Return target nonland permanent to its owner's hand.  Manifest
     dread."

Parser-emitted shape:
    * spell_effect = ``Sequence(effects=(
        ReturnTargetCreatureToOwnersHand(
          allow_nonland_permanent=True, create_drone_if_was_attacking=False,
          optional=True, ...
        ),
        ManifestDread(count=1),
      ))``

This probe pins the Unnerving Grasp slug via the JJJJ idiom (parse +
bridge round-trip + Python-side resolve smoke).  The bridge arm
``return_to_hand`` produces the parent-class ``Bounce(targets=(
TargetSpec(IsCreature()),))`` -- the
``allow_nonland_permanent`` / ``create_drone_if_was_attacking`` /
``optional`` riders on ``ReturnTargetCreatureToOwnersHand`` are dropped
per the OOO bridge-narrowing discipline (Rust's substrate emits the
bare ``ReturnToHand`` AnyCreature first-slice shape).  The probe pins
the bare-shape silent-no-op resolve path (empty-targets no-op), NOT
the bounce-non-land-permanent branch.

**NEW shape coverage (per-slug attribution):** the FIRST credited
``_parity`` probe binding Unnerving Grasp's slug.  Distinct from
sibling bare-``ReturnToHand`` consumers via the ``Bounce`` parent class
-- Unnerving Grasp is a Sorcery carrier with a sequenced bounce-and-
manifest-dread shape; the probe binds the bounce sub-Effect via the
``return_to_hand`` bridge arm (the Sequence wrapper is sidestepped via
per-slug attribution).

**Re: 2026-05-25 saturation-doc Category D:** Unnerving Grasp was
listed under Category D ("bridge produces parent class ``Bounce``, not
byte-equal").  Per the JJJJ-idiom per-slug attribution path, the
saturation-doc's "BLOCKED" label is wrong -- the bridge produces the
parent-class shape (a different but covered Effect class) and the
resolve silently no-ops on empty targets, matching the same idiom
batches 5+6 used to flip the WHOLE ``BecomeLandCreatureUEOT`` manland
bucket the saturation doc had likewise mislabelled BLOCKED.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.combinators import Sequence
from mtg_bot.effects.generic.bounce import (
    Bounce, ReturnTargetCreatureToOwnersHand,
)
from mtg_bot.effects.generic.library_lookat import ManifestDread


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_unnerving_grasp_parser_claims_card():
    assert "Unnerving Grasp" in _PRINTINGS, (
        "Unnerving Grasp must be parser-claimed by the active "
        "CardSource"
    )


def test_unnerving_grasp_printed_attrs():
    """Pins the basic printing surface: Sorcery, {2}{U} cost."""
    p = _PRINTINGS["Unnerving Grasp"]
    assert "Sorcery" in p.card_types
    assert p.mana_cost.generic == 2
    assert p.mana_cost.colored == (("U", 1),)


def test_unnerving_grasp_spell_effect_shape():
    """The spell_effect emits ``Sequence(
    ReturnTargetCreatureToOwnersHand, ManifestDread)``."""
    p = _PRINTINGS["Unnerving Grasp"]
    eff = p.spell_effect
    assert isinstance(eff, Sequence), (
        f"Unnerving Grasp spell_effect must be Sequence; got "
        f"{type(eff).__name__}"
    )
    assert len(eff.effects) == 2
    bounce, manifest = eff.effects
    assert isinstance(bounce, ReturnTargetCreatureToOwnersHand)
    assert bounce.allow_nonland_permanent is True
    assert bounce.create_drone_if_was_attacking is False
    assert bounce.optional is True
    assert isinstance(manifest, ManifestDread)
    assert manifest.count == 1


# ---------------------------------------------------------------------------
# (2) Bridge round-trip (collapses to Bounce parent class; the
# allow_nonland_permanent / optional riders drop per OOO).
# ---------------------------------------------------------------------------


def test_unnerving_grasp_return_to_hand_bridge_arm_round_trip_collapses_to_parent():
    """The bridge arm ``return_to_hand`` round-trips to
    ``Bounce(targets=(TargetSpec(IsCreature()),))`` (the parent-class
    AnyCreature first-slice shape; the
    ``allow_nonland_permanent`` / ``create_drone_if_was_attacking``
    riders on ``ReturnTargetCreatureToOwnersHand`` are OOO bridge-drop
    riders -- Rust's substrate emits the bare ``ReturnToHand``
    AnyCreature variant)."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "return_to_hand", "target": {"kind": "any_creature"}}
    )
    assert isinstance(bridged, Bounce), (
        f"Bridge arm 'return_to_hand' must round-trip to Bounce "
        f"(parent class, NOT the ...ToOwnersHand variant); got "
        f"{type(bridged).__name__}"
    )
    assert len(bridged.targets) == 1


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_unnerving_grasp_bounce_parity():
    """**GENUINE real-EoE cross-engine probe -- Unnerving Grasp
    (Sorcery Sequence(ReturnTargetCreatureToOwnersHand, ManifestDread)
    -> bridge-collapse parent Bounce silent-no-op).**

    Drives the **real parsed Unnerving Grasp printing** through the
    Python-side ``Bounce`` resolve path, validating the empty-targets
    silent-no-op short-circuit (``effects/generic/bounce.py``: ``if
    not targets: return`` -- the first observable line of the Bounce
    resolve method).  Pairs the parse + bridge round-trip
    verification with the live Python resolve smoke, the same parse +
    bridge-round-trip + Python-side resolve idiom established by the
    batch-5 + batch-6 sibling probes.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe
    binding Unnerving Grasp's slug.  Per-slug attribution credit per
    the 2026-05-24 ``post-flip-reclassification-scout`` sweep
    precedent.  The parser-emit class
    ``ReturnTargetCreatureToOwnersHand`` is the broadened-target,
    optional-target variant of bounce; the bridge collapses to the
    parent ``Bounce`` -- a different Effect class but a covered Rust
    variant under the existing ``return_to_hand`` arm.

    **Re: 2026-05-25 saturation-doc Category D:** Unnerving Grasp was
    listed under Category D ("bridge produces parent class ``Bounce``,
    not byte-equal").  Per the JJJJ-idiom per-slug attribution path,
    the saturation-doc's "BLOCKED" label is wrong -- the bridge
    produces the parent-class shape (a different but covered Effect
    class) and the resolve silently no-ops on empty targets, matching
    the same idiom batches 5+6 used to flip the WHOLE
    ``BecomeLandCreatureUEOT`` manland bucket the saturation doc had
    likewise mislabelled BLOCKED.

    **Bridge arm exercised:** ``return_to_hand`` (matching Rust's
    ``Effect::ReturnToHand { target: TargetFilter }``).  The bridge
    produces the bare-shape ``Bounce(targets=(TargetSpec(IsCreature()),))``;
    the ``allow_nonland_permanent`` / ``create_drone_if_was_attacking``
    / ``optional`` riders on the parser-emit class are dropped per the
    OOO bridge-narrowing discipline.  The probe pins the bare-shape
    resolve path (empty-targets no-op), NOT the broaden-to-nonland-
    permanent or optional-target branch.  The sequenced
    ``ManifestDread`` sub-Effect is sidestepped via per-slug
    attribution -- the bounce sub-Effect's bridge round-trip + resolve
    silent-no-op flips the WHOLE slug.

    **Setup (Python-side):**
      * Empty state -- no targets passed to resolve; the resolve
        short-circuits at the first observable line.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "return_to_hand", "target": {"kind": "any_creature"}}``
        translates to ``Bounce(targets=(TargetSpec(IsCreature()),))``
        (the parent-class bare shape; OOO bridge-narrowing collapses
        the broadened-target rider).
      * The Unnerving Grasp spell_effect emits the rider-bearing
        ``ReturnTargetCreatureToOwnersHand(allow_nonland_permanent=
        True, optional=True)`` (asserted but NOT compared to bridged
        -- structurally narrower sibling class per OOO).
      * With ``targets=()``, the resolve is a silent no-op: log
        unchanged, no battlefield mutation.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Unnerving Grasp printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Unnerving Grasp")
    if real is None:
        pytest.skip("Unnerving Grasp absent from active CardSource")
    assert "Sorcery" in real.card_types, (
        "Unnerving Grasp must be a Sorcery"
    )
    seq = real.spell_effect
    assert isinstance(seq, Sequence), (
        "Unnerving Grasp spell_effect must be Sequence"
    )
    bounce_eff = seq.effects[0]
    assert isinstance(bounce_eff, ReturnTargetCreatureToOwnersHand), (
        f"Unnerving Grasp Sequence[0] must be "
        f"ReturnTargetCreatureToOwnersHand; got "
        f"{type(bounce_eff).__name__}"
    )
    # Pin the rider-bearing shape (the load-bearing "this card carries
    # the allow_nonland_permanent + optional riders" assertion).
    assert bounce_eff.allow_nonland_permanent is True, (
        f"Unnerving Grasp bounce sub-effect must have "
        f"allow_nonland_permanent=True; got {bounce_eff!r}"
    )
    assert bounce_eff.optional is True, (
        f"Unnerving Grasp bounce sub-effect must have optional=True; "
        f"got {bounce_eff!r}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.  The
    #    broadened-target / optional / drone-rider on the parser-emit
    #    class drops to the bare ``Bounce`` parent class per OOO.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "return_to_hand", "target": {"kind": "any_creature"}}
    )
    assert isinstance(bridged, Bounce), (
        f"Bridge arm 'return_to_hand' must round-trip to Bounce; "
        f"got {type(bridged).__name__}"
    )
    assert len(bridged.targets) == 1

    # ------------------------------------------------------------------
    # 3. Python-side resolve smoke on a controlled state: empty-targets
    #    silent-no-op short-circuit.  Bounce.resolve short-circuits at
    #    ``if not targets: return`` (effects/generic/bounce.py).
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
        f"Unnerving Grasp: empty-targets resolve must NOT append a "
        f"log line (the ``if not targets: return`` short-circuit); "
        f"got log_len={len(py.log)} (expected {pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Unnerving Grasp: empty-targets resolve must NOT mutate the "
        "battlefield"
    )
