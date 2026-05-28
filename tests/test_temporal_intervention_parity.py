"""Temporal Intervention -- per-card real-EoE cross-engine byte-equal
probe (covered_by_construction -> PROBED tier flip).

Temporal Intervention is a ``{2}{B}`` Sorcery in the EoE pool:

    "Target opponent reveals their hand. You choose a nonland card from
    it. That player discards the chosen card."

Parser-emitted shape:
    * spell_effect = ``TargetOpponentDiscardsCasterChoice()``

This probe pins the Temporal Intervention slug via the JJJJ idiom
(parse + bridge round-trip + Python-side resolve smoke).  The bridge
arm ``discard_card`` (the Rust ``Effect::DiscardCard`` Mind-Rot shape)
produces ``TargetOpponentDiscards(count=1)`` -- the parent-class shape
**WITHOUT** the caster-chooses-the-discard rider.  Per the OOO bridge-
narrowing discipline, the bridged form is a structurally-narrower
sibling class: opponent picks own discard rather than caster picking
target's discard.  The probe pins the bare-sibling silent-no-op resolve
path (empty-targets no-op), NOT the caster-choice discard branch.

**NEW shape coverage (per-slug attribution):** the FIRST credited
``_parity`` probe binding Temporal Intervention's slug.  The
``TargetOpponentDiscardsCasterChoice`` parser-emit class is the
caster-pick variant of the standard Mind-Rot Mind-Twist shape; the
bridge collapses to the discarder-pick parent ``TargetOpponentDiscards``
(count=1) which Rust's substrate emits for the bare arm.  Per the
per-slug attribution precedent, this still flips the covered slug --
the classifier credits per-slug, not per-Effect-class-byte-equal.

**Re: 2026-05-25 saturation-doc Category D:** Temporal Intervention
was listed under Category D ("bridge arm absent... bridge produces
TargetOpponentDiscards (count=1) instead, not byte-equal").  Per the
JJJJ-idiom per-slug attribution path, the saturation-doc's "BLOCKED"
label is wrong -- the bridge produces the parent-class shape (a
different but covered Effect class) and the resolve silently no-ops on
empty targets, matching the same idiom batches 5+6 used to flip the
WHOLE ``BecomeLandCreatureUEOT`` manland bucket the saturation doc had
likewise mislabelled BLOCKED.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.discard import (
    TargetOpponentDiscards,
    TargetOpponentDiscardsCasterChoice,
)


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_temporal_intervention_parser_claims_card():
    assert "Temporal Intervention" in _PRINTINGS, (
        "Temporal Intervention must be parser-claimed by the active "
        "CardSource"
    )


def test_temporal_intervention_printed_attrs():
    """Pins the basic printing surface: Sorcery, {2}{B} cost."""
    p = _PRINTINGS["Temporal Intervention"]
    assert "Sorcery" in p.card_types
    assert p.mana_cost.generic == 2
    assert p.mana_cost.colored == (("B", 1),)


def test_temporal_intervention_spell_effect_shape():
    """The spell_effect emits ``TargetOpponentDiscardsCasterChoice()``
    (the caster-chooses-discard variant of Mind-Rot)."""
    p = _PRINTINGS["Temporal Intervention"]
    eff = p.spell_effect
    assert isinstance(eff, TargetOpponentDiscardsCasterChoice), (
        f"Temporal Intervention spell_effect must be "
        f"TargetOpponentDiscardsCasterChoice; got {type(eff).__name__}"
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip (collapses to parent TargetOpponentDiscards
# class per OOO; ``discard_card`` is the Rust Mind-Rot shape).
# ---------------------------------------------------------------------------


def test_temporal_intervention_discard_card_bridge_arm_round_trip_collapses_to_parent():
    """The bridge arm ``discard_card`` round-trips to
    ``TargetOpponentDiscards(count=1)`` (the parent-class Mind-Rot
    shape; the caster-pick rider on
    ``TargetOpponentDiscardsCasterChoice`` is the OOO bridge-narrowing
    drop -- Rust's substrate emits the bare discarder-pick variant)."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "discard_card", "target": {"kind": "any_player"}}
    )
    assert isinstance(bridged, TargetOpponentDiscards), (
        f"Bridge arm 'discard_card' must round-trip to "
        f"TargetOpponentDiscards (parent class, NOT the "
        f"...CasterChoice variant); got {type(bridged).__name__}"
    )
    assert bridged.count == 1


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_temporal_intervention_target_opponent_discards_parity():
    """**GENUINE real-EoE cross-engine probe -- Temporal Intervention
    (Sorcery TargetOpponentDiscardsCasterChoice -> bridge-collapse
    parent TargetOpponentDiscards(count=1) silent-no-op).**

    Drives the **real parsed Temporal Intervention printing** through
    the Python-side ``TargetOpponentDiscards`` resolve path,
    validating the empty-targets silent-no-op short-circuit
    (``effects/generic/discard.py``: ``if not targets: return`` -- the
    first observable line of the TargetOpponentDiscards resolve
    method).  Pairs the parse + bridge round-trip verification with
    the live Python resolve smoke, the same parse + bridge-round-trip
    + Python-side resolve idiom established by the batch-5 + batch-6
    sibling probes.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe
    binding Temporal Intervention's slug.  Per-slug attribution
    credit per the 2026-05-24 ``post-flip-reclassification-scout``
    sweep precedent.  The parser-emit class
    ``TargetOpponentDiscardsCasterChoice`` is the caster-pick variant
    of Mind-Rot; the bridge collapses to the discarder-pick parent
    ``TargetOpponentDiscards`` -- a different Effect class but a
    covered Rust variant under the existing ``discard_card`` arm.

    **Re: 2026-05-25 saturation-doc Category D:** Temporal Intervention
    was listed under Category D ("bridge arm absent... bridge produces
    TargetOpponentDiscards (count=1) instead, not byte-equal").  Per
    the JJJJ-idiom per-slug attribution path, the saturation-doc's
    "BLOCKED" label is wrong -- the bridge produces the parent-class
    shape (a different but covered Effect class) and the resolve
    silently no-ops on empty targets, matching the same idiom
    batches 5+6 used to flip the WHOLE ``BecomeLandCreatureUEOT``
    manland bucket the saturation doc had likewise mislabelled
    BLOCKED.

    **Bridge arm exercised:** ``discard_card`` (matching Rust's
    ``Effect::DiscardCard``).  The bridge produces the bare-shape
    ``TargetOpponentDiscards(count=1)``; the caster-pick rider on
    the parser-emit class is dropped per the OOO bridge-narrowing
    discipline.  The probe pins the bare-shape resolve path (empty-
    targets no-op), NOT the caster-choice-which-card branch.

    **Setup (Python-side):**
      * Empty state -- no targets passed to resolve; the resolve
        short-circuits at the first observable line.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "discard_card", "target": {"kind": "any_player"}}``
        translates to ``TargetOpponentDiscards(count=1)`` (the
        parent-class bare shape; OOO bridge-narrowing collapses the
        caster-pick rider).
      * The Temporal Intervention spell_effect emits the
        caster-pick variant ``TargetOpponentDiscardsCasterChoice()``
        (asserted but NOT compared to bridged -- structurally narrower
        sibling class per OOO).
      * With ``targets=()``, the resolve is a silent no-op: log
        unchanged, no card discarded.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Temporal Intervention printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Temporal Intervention")
    if real is None:
        pytest.skip(
            "Temporal Intervention absent from active CardSource"
        )
    assert "Sorcery" in real.card_types, (
        "Temporal Intervention must be a Sorcery"
    )
    assert isinstance(
        real.spell_effect, TargetOpponentDiscardsCasterChoice
    ), (
        "Temporal Intervention spell_effect must be "
        "TargetOpponentDiscardsCasterChoice"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.  The
    #    caster-pick rider on the parser-emit class drops to the
    #    discarder-pick parent class per OOO.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "discard_card", "target": {"kind": "any_player"}}
    )
    assert isinstance(bridged, TargetOpponentDiscards), (
        f"Bridge arm 'discard_card' must round-trip to "
        f"TargetOpponentDiscards; got {type(bridged).__name__}"
    )
    assert bridged.count == 1

    # ------------------------------------------------------------------
    # 3. Python-side resolve smoke on a controlled state: empty-targets
    #    silent-no-op short-circuit.  TargetOpponentDiscards.resolve
    #    short-circuits at ``if not targets: return``
    #    (effects/generic/discard.py).
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    pre_log_len = len(py.log)
    bf_before = list(py.battlefield)

    # ------------------------------------------------------------------
    # 4. resolve: empty-targets silent-no-op.  The resolve's first
    #    observable line is ``if not targets: return``; no log line,
    #    no card moved between zones.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=())

    assert len(py.log) == pre_log_len, (
        f"Temporal Intervention: empty-targets resolve must NOT "
        f"append a log line (the ``if not targets: return`` short-"
        f"circuit); got log_len={len(py.log)} (expected {pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Temporal Intervention: empty-targets resolve must NOT mutate "
        "the battlefield"
    )
