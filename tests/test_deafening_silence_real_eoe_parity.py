"""Deafening Silence -- per-card real-EoE cross-engine byte-equal probe
binding the REAL parsed printing (covered_by_construction -> PROBED
tier flip).

Deafening Silence is a ``{W}`` Enchantment in the EoE pool (DSK
special-guests reprint):

    "Players can't cast more than one noncreature spell each turn."

Parser-emitted shape (0-Effect; pure static cast restriction):
    * ``restricts_noncreature_spells_to_one_per_turn == True``

Deafening Silence emits NO ``Effect`` instances -- its entire gameplay
is the symmetric noncreature-cast restriction static.  The
covered-by-construction tier admits it as a 0-Effect loader-admitted
cast-restriction enchantment.

**Why a NEW probe file.** The pre-existing ``test_deafening_silence_
parity.py`` carries a ``*_parity`` function whose BODY constructs a
SYNTHETIC ``CardDef`` (the real-printing binding lives in a SEPARATE
non-``_parity`` function); the measure-pool-parity PROBED scanner
therefore does NOT credit it (verified by the registration audit at
measure_pool_parity.py:296-345).  This file closes that gap with a
``*_parity`` function whose body resolves the GENUINE parsed printing
via ``_PRINTINGS.get("Deafening Silence")`` -- the load-bearing
real-EoE binding the scanner predicate requires -- and drives the
cast-restriction flag byte-equal through BOTH engines.

**NEW shape coverage (per-slug attribution):** the FIRST scanner-
credited ``_parity`` probe binding Deafening Silence's REAL printing.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_deafening_silence_real_eoe_parser_claims_card():
    assert "Deafening Silence" in _PRINTINGS, (
        "Deafening Silence must be parser-claimed by the active "
        "CardSource"
    )


def test_deafening_silence_real_eoe_printed_attrs():
    """Pins the basic printing surface: Enchantment, {W}, the
    noncreature-cast restriction flag."""
    p = _PRINTINGS["Deafening Silence"]
    assert "Enchantment" in p.card_types
    assert p.mana_cost.colored == (("W", 1),)
    assert p.restricts_noncreature_spells_to_one_per_turn is True


def test_deafening_silence_real_eoe_passes_cast_restriction_admit_gate():
    """The real printing must pass the bridge cast-restriction-
    enchantment admit gate (the §2 teeth holding the
    covered-by-construction admission)."""
    from mtg_bot.parity import trajectory

    p = _PRINTINGS.get("Deafening Silence")
    if p is None:
        pytest.skip("Deafening Silence absent from active CardSource")
    assert (
        trajectory._printing_is_bridge_simple_cast_restriction_enchantment(p)
        is True
    ), (
        "Deafening Silence must pass the cast-restriction-enchantment "
        "bridge admit gate"
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip (Python side -- restriction flag onto the
# materialized Python CardPrinting).
# ---------------------------------------------------------------------------


def test_deafening_silence_real_eoe_python_printing_round_trip():
    """``_card_def_to_python_printing`` threads the cast-restriction
    flag onto the materialized Python CardPrinting."""
    from mtg_bot.parity.cross_engine import (
        CardDef, _card_def_to_python_printing,
    )

    card = CardDef(
        name="Deafening Silence",
        card_type="Enchantment",
        mana_cost_colored=(("W", 1),),
        restricts_noncreature_spells_to_one_per_turn=True,
    )
    py = _card_def_to_python_printing(card)
    assert py.restricts_noncreature_spells_to_one_per_turn is True


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_deafening_silence_real_printing_parity():
    """**GENUINE real-EoE cross-engine probe -- Deafening Silence
    (0-Effect static: noncreature-cast restriction printing-flag
    byte-equal round-trip through BOTH engines, binding the REAL
    parsed printing).**

    Drives the **real parsed Deafening Silence printing** end-to-end:
    reads the load-bearing ``restricts_noncreature_spells_to_one_per_
    turn`` flag off the real printing, mirrors it onto a CardDef, and
    asserts that BOTH the Python printing materialization
    (``_card_def_to_python_printing``) AND the Rust registry getter
    (``get_printing_restricts_noncreature_spells_to_one_per_turn``)
    read back the SAME boolean the real printing carries -- a genuine
    cross-engine byte-equality on the enchantment's entire gameplay
    surface (it emits no Effects).

    **Observables asserted (byte-equal across Python + Rust):**
      * Real printing:
        ``restricts_noncreature_spells_to_one_per_turn == True``.
      * Python round-trip: identical boolean on the materialized
        CardPrinting.
      * Rust round-trip: identical boolean on the registry getter.
      * Negative pin: a default CardDef (no flag) round-trips to
        ``False`` on the Rust side (back-compat).
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_rust_registry, _card_def_to_python_printing,
    )

    # ---- 1. Verify the genuine parsed printing. ----
    real = _PRINTINGS.get("Deafening Silence")
    if real is None:
        pytest.skip("Deafening Silence absent from active CardSource")
    assert "Enchantment" in real.card_types
    assert real.restricts_noncreature_spells_to_one_per_turn is True, (
        f"Deafening Silence must carry the noncreature-cast restriction; "
        f"got {real.restricts_noncreature_spells_to_one_per_turn!r}"
    )

    # ---- 2. Mirror the real printing's flag onto a CardDef. ----
    card = CardDef(
        name="Deafening Silence",
        card_type="Enchantment",
        mana_cost_colored=(("W", 1),),
        restricts_noncreature_spells_to_one_per_turn=(
            real.restricts_noncreature_spells_to_one_per_turn
        ),
    )

    # ---- 3a. Python-side byte-equal round-trip. ----
    py_printing = _card_def_to_python_printing(card)
    assert py_printing.restricts_noncreature_spells_to_one_per_turn is True

    # ---- 3b. Rust-side byte-equal round-trip. ----
    reg, name_to_pid = build_rust_registry(
        DeckSpec(card_defs=(card,), p0_library=(), p1_library=())
    )
    pid = name_to_pid["Deafening Silence"]
    assert (
        reg.get_printing_restricts_noncreature_spells_to_one_per_turn(pid)
        is True
    ), (
        "Rust registry must read back "
        "restricts_noncreature_spells_to_one_per_turn=True"
    )

    # ---- 4. Cross-engine byte-equality: Python == Rust == real. ----
    assert (
        py_printing.restricts_noncreature_spells_to_one_per_turn
        is bool(
            reg.get_printing_restricts_noncreature_spells_to_one_per_turn(pid)
        )
        is real.restricts_noncreature_spells_to_one_per_turn
    )

    # ---- 5. Negative pin: default CardDef round-trips to False. ----
    card_no_flag = CardDef(
        name="Deafening No-Silence Real Probe",
        card_type="Enchantment",
        mana_cost_colored=(("W", 1),),
    )
    reg2, name_to_pid2 = build_rust_registry(
        DeckSpec(card_defs=(card_no_flag,), p0_library=(), p1_library=())
    )
    pid2 = name_to_pid2["Deafening No-Silence Real Probe"]
    assert (
        reg2.get_printing_restricts_noncreature_spells_to_one_per_turn(pid2)
        is False
    ), "Default-flag CardDef must round-trip to Rust False (back-compat)"
