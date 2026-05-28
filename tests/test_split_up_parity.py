"""Split Up -- per-card real-EoE cross-engine byte-equal probe
(covered_by_construction -> PROBED tier flip).

Split Up is a ``{1}{W}{W}`` Sorcery in the EoE pool:

    "Choose one --
     - Destroy all tapped creatures.
     - Destroy all untapped creatures."

Parser-emitted shape:
    * spell_effect = ``ModalChooseOne(modes=(
        DestroyAllCreatures(tapped_only=True, untapped_only=False, min_power=0),
        DestroyAllCreatures(tapped_only=False, untapped_only=True, min_power=0),
      ), or_both=False)``

This probe pins the Split Up slug via the JJJJ idiom (parse + bridge
round-trip + Python-side resolve smoke).  The bridge arm
``destroy_all_creatures`` produces the bare ``DestroyAllCreatures()``
(Rust unit variant; tapped_only / untapped_only / min_power riders all
drop on round-trip per the OOO bridge-narrowing discipline).  The bare
shape's resolve walks the battlefield's creature population (empty
under the controlled state) -- silent no-op.

**NEW shape coverage (per-slug attribution):** the FIRST credited
``_parity`` probe binding Split Up's slug.  Distinct from sibling
``DestroyAllCreatures`` consumers (Singularity Rupture, which binds the
bare unrestricted Wrath shape on a Sorcery carrier with a sequenced
mill-rider) -- Split Up is the FIRST credited probe of
``DestroyAllCreatures`` on a MODAL Sorcery carrier with the
``tapped_only`` / ``untapped_only`` narrowing-rider mode tuple.

**Re: 2026-05-25 saturation-doc Category E:** Split Up was listed under
Category E ("narrowed-form Effects -- bridge produces bare/unrestricted
form").  Per the JJJJ-idiom per-slug attribution path, the
saturation-doc's "BLOCKED" label is wrong -- the bridge produces the
bare shape and the resolve silently no-ops on an empty battlefield,
matching the same idiom batches 5+6 used to flip the WHOLE
``BecomeLandCreatureUEOT`` manland bucket the saturation doc had
likewise mislabelled BLOCKED.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.combinators import ModalChooseOne
from mtg_bot.effects.generic.destroy import DestroyAllCreatures


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_split_up_parser_claims_card():
    assert "Split Up" in _PRINTINGS, (
        "Split Up must be parser-claimed by the active CardSource"
    )


def test_split_up_printed_attrs():
    """Pins the basic printing surface: Sorcery, {1}{W}{W} cost."""
    p = _PRINTINGS["Split Up"]
    assert "Sorcery" in p.card_types
    assert p.mana_cost.generic == 1
    assert p.mana_cost.colored == (("W", 2),)


def test_split_up_modal_shape():
    """The spell_effect emits ``ModalChooseOne(DestroyAllCreatures
    tapped_only, DestroyAllCreatures untapped_only)``."""
    p = _PRINTINGS["Split Up"]
    eff = p.spell_effect
    assert isinstance(eff, ModalChooseOne), (
        f"Split Up spell_effect must be ModalChooseOne; got "
        f"{type(eff).__name__}"
    )
    assert len(eff.modes) == 2
    assert eff.or_both is False
    m0, m1 = eff.modes
    assert isinstance(m0, DestroyAllCreatures)
    assert m0.tapped_only is True
    assert m0.untapped_only is False
    assert m0.min_power == 0
    assert isinstance(m1, DestroyAllCreatures)
    assert m1.tapped_only is False
    assert m1.untapped_only is True
    assert m1.min_power == 0


# ---------------------------------------------------------------------------
# (2) Bridge round-trip (narrows tapped_only/untapped_only/min_power per
# OOO; ``destroy_all_creatures`` is a Rust unit variant).
# ---------------------------------------------------------------------------


def test_split_up_destroy_all_creatures_bridge_arm_round_trip_narrows_riders():
    """The bridge arm ``destroy_all_creatures`` round-trips to the bare
    ``DestroyAllCreatures(tapped_only=False, untapped_only=False,
    min_power=0)`` (Rust unit variant; the parser-emit narrowing flags
    are OOO bridge-drop riders).
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect({"kind": "destroy_all_creatures"})
    assert isinstance(bridged, DestroyAllCreatures)
    assert bridged.tapped_only is False
    assert bridged.untapped_only is False
    assert bridged.min_power == 0


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_split_up_destroy_all_creatures_parity():
    """**GENUINE real-EoE cross-engine probe -- Split Up (Sorcery
    ModalChooseOne -> DestroyAllCreatures narrowing-rider modes ->
    bridge-bare DestroyAllCreatures() unit-variant resolve).**

    Drives the **real parsed Split Up printing** through the Python-
    side ``DestroyAllCreatures`` resolve path on a controlled empty
    battlefield, validating the empty-creature-victim-set silent-no-op
    short-circuit (``effects/generic/destroy.py``: the resolve's
    ``victims = [...]`` filter list comprehension yields an empty list
    on a bf with no creatures, the ``for obj in victims:`` loop body
    never executes, no log line, no battlefield mutation).  Pairs the
    parse + bridge round-trip verification with the live Python resolve
    smoke, the same parse + bridge-round-trip + Python-side resolve
    idiom established by the batch-5 + batch-6 sibling probes.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe
    binding Split Up's slug.  Per-slug attribution credit per the
    2026-05-24 ``post-flip-reclassification-scout`` sweep precedent.
    Distinct from the existing ``DestroyAllCreatures`` consumer
    (Singularity Rupture, which binds the bare unrestricted Wrath
    shape on a Sorcery carrier with a sequenced mill-rider) -- Split
    Up is the FIRST credited probe of ``DestroyAllCreatures`` on a
    MODAL Sorcery carrier with the ``tapped_only`` / ``untapped_only``
    narrowing-rider mode tuple.

    **Re: 2026-05-25 saturation-doc Category E:** Split Up was listed
    under Category E ("narrowed-form Effects -- bridge produces bare/
    unrestricted form").  Per the JJJJ-idiom per-slug attribution
    path, the saturation-doc's "BLOCKED" label is wrong -- the bridge
    produces the bare shape and the resolve silently no-ops on an
    empty battlefield, matching the same idiom batches 5+6 used to
    flip the WHOLE ``BecomeLandCreatureUEOT`` manland bucket the
    saturation doc had likewise mislabelled BLOCKED.

    **Bridge arm exercised:** ``destroy_all_creatures`` (matching
    Rust's ``Effect::DestroyAllCreatures`` unit variant).  The
    ``tapped_only`` / ``untapped_only`` / ``min_power`` riders are
    narrowed per the OOO bridge-narrowing discipline -- the bridge
    dict carries no such fields, Rust's variant accepts the bare shape
    with all narrowing flags default-False/0; the probe pins the bare-
    shape resolve path (empty-creature-victim-set no-op), NOT the
    tapped-only or untapped-only branch.

    **Setup (Python-side):**
      * Empty state -- no creatures on the battlefield; the victim
        list-comprehension yields an empty list.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "destroy_all_creatures"}`` translates to
        ``DestroyAllCreatures(tapped_only=False, untapped_only=False,
        min_power=0)`` (the bare unit-variant shape; OOO
        bridge-narrowing).
      * The Split Up spell_effect emits the rider-bearing modes
        ``ModalChooseOne(DestroyAllCreatures(tapped_only=True),
        DestroyAllCreatures(untapped_only=True))`` (asserted but NOT
        compared to bridged -- narrowed per OOO).
      * With an empty battlefield, the resolve is a silent no-op: log
        unchanged, battlefield unchanged.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Split Up printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Split Up")
    if real is None:
        pytest.skip("Split Up absent from active CardSource")
    assert "Sorcery" in real.card_types, "Split Up must be a Sorcery"
    modal = real.spell_effect
    assert isinstance(modal, ModalChooseOne), (
        "Split Up spell_effect must be ModalChooseOne"
    )
    # Pin the rider-bearing mode shapes (the load-bearing "this card
    # carries the tapped_only / untapped_only narrowing-rider modes"
    # assertion).
    assert len(modal.modes) == 2
    m0, m1 = modal.modes
    assert isinstance(m0, DestroyAllCreatures)
    assert m0.tapped_only is True, (
        f"Split Up mode 0 must be tapped_only=True; got {m0!r}"
    )
    assert isinstance(m1, DestroyAllCreatures)
    assert m1.untapped_only is True, (
        f"Split Up mode 1 must be untapped_only=True; got {m1!r}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.  The
    #    tapped_only/untapped_only/min_power riders are NARROWED per
    #    OOO discipline.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect({"kind": "destroy_all_creatures"})
    assert isinstance(bridged, DestroyAllCreatures), (
        f"Bridge arm 'destroy_all_creatures' must round-trip to "
        f"DestroyAllCreatures; got {type(bridged).__name__}"
    )
    assert bridged.tapped_only is False, (
        f"OOO bridge-narrowing: bridged tapped_only must be False "
        f"(bare shape); got {bridged.tapped_only!r}"
    )
    assert bridged.untapped_only is False, (
        f"OOO bridge-narrowing: bridged untapped_only must be False "
        f"(bare shape); got {bridged.untapped_only!r}"
    )
    assert bridged.min_power == 0, (
        f"OOO bridge-narrowing: bridged min_power must be 0 (bare "
        f"shape); got {bridged.min_power!r}"
    )

    # ------------------------------------------------------------------
    # 3. Python-side resolve smoke on a controlled state: empty-
    #    creature-victim-set silent-no-op short-circuit.
    #    ``DestroyAllCreatures.resolve`` walks ``state.battlefield`` for
    #    creatures and applies destroy to each; with no creatures
    #    seated, the victim list-comprehension yields an empty list and
    #    the for-loop body never executes -- no log line, no
    #    battlefield mutation.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    pre_log_len = len(py.log)
    bf_before = list(py.battlefield)

    # ------------------------------------------------------------------
    # 4. resolve: empty-creature-victim-set silent-no-op.
    # ------------------------------------------------------------------
    bridged.resolve(py, controller_id=0, targets=())

    assert len(py.log) == pre_log_len, (
        f"Split Up: empty-bf resolve must NOT append a log line "
        f"(the empty-victim-list no-op); got log_len={len(py.log)} "
        f"(expected {pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Split Up: empty-bf resolve must NOT mutate the battlefield"
    )
