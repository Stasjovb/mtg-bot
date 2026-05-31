"""Duskmourn's Domination -- per-card real-EoE cross-engine byte-equal
probe (covered_by_construction -> PROBED tier flip).

Duskmourn's Domination is a ``{4}{U}{U}`` Aura Enchantment in the EoE
pool:

    "Enchant creature.  You control enchanted creature.  Enchanted
     creature loses all abilities."

Parser-emitted shape (0-Effect; pure attach-grant aura flags):
    * ``aura_enchant_type == "creature"``
    * ``attached_grants_control == True``  (control-magic static grant)
    * ``attached_grants_lose_all_abilities == True``

Duskmourn's Domination emits NO ``Effect`` instances -- its entire
gameplay is the layer-system attach-grant static the Aura applies to
its host on attach.  The covered-by-construction tier admits it as a
0-Effect loader-admitted Aura; this probe flips it to PROBED via a
GENUINE cross-engine byte-equal round-trip of the load-bearing
attach-grant printing flags through BOTH engines' registry/printing
materialization.

This probe pins the Duskmourn's Domination slug via the printing-flag
round-trip idiom (the same shape the Deafening Silence cast-restriction
probe uses for its 0-Effect static).  A CardDef mirroring the real
printing's aura-grant flags round-trips: Python's
``_card_def_to_python_printing`` and Rust's registry getters
(``get_printing_aura_grants_control`` /
``get_printing_aura_grants_lose_abilities`` /
``get_printing_aura_enchant_type``) both read back the SAME booleans the
real parsed printing carries.

**NEW shape coverage (per-slug attribution):** the FIRST credited
``_parity`` probe binding Duskmourn's Domination's slug.  It is the
FIRST credited probe of an Aura carrying BOTH the control-magic
(``attached_grants_control``) AND lose-all-abilities
(``attached_grants_lose_all_abilities``) attach-grant statics together.
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


def test_duskmourns_domination_parser_claims_card():
    assert "Duskmourn's Domination" in _PRINTINGS, (
        "Duskmourn's Domination must be parser-claimed by the active "
        "CardSource"
    )


def test_duskmourns_domination_printed_attrs():
    """Pins the basic printing surface: Aura Enchantment, {4}{U}{U},
    enchant creature, control + lose-abilities attach grants."""
    p = _PRINTINGS["Duskmourn's Domination"]
    assert "Enchantment" in p.card_types
    assert p.mana_cost.generic == 4
    assert p.mana_cost.colored == (("U", 2),)
    assert p.aura_enchant_type == "creature"
    assert p.attached_grants_control is True
    assert p.attached_grants_lose_all_abilities is True


def test_duskmourns_domination_passes_simple_aura_admit_gate():
    """The real printing must pass the bridge simple-aura admit gate
    (the §2 teeth that hold the covered-by-construction admission)."""
    from mtg_bot.parity import trajectory

    p = _PRINTINGS.get("Duskmourn's Domination")
    if p is None:
        pytest.skip("Duskmourn's Domination absent from active CardSource")
    assert trajectory._printing_is_bridge_simple_aura(p) is True, (
        "Duskmourn's Domination must pass the simple-aura bridge admit "
        "gate"
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip (Python side -- attach-grant flags onto the
# materialized Python CardPrinting).
# ---------------------------------------------------------------------------


def test_duskmourns_domination_python_printing_round_trip():
    """``_card_def_to_python_printing`` threads the aura-grant flags
    onto the materialized Python CardPrinting."""
    from mtg_bot.parity.cross_engine import (
        CardDef, _card_def_to_python_printing,
    )

    card = CardDef(
        name="Duskmourn's Domination",
        card_type="Enchantment",
        mana_cost_generic=4,
        mana_cost_colored=(("U", 2),),
        is_aura=True,
        aura_enchant_type="creature",
        aura_grants_control=True,
        aura_grants_lose_abilities=True,
    )
    py = _card_def_to_python_printing(card)
    assert py.attached_grants_control is True
    assert py.attached_grants_lose_all_abilities is True
    assert py.aura_enchant_type == "creature"


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_duskmourns_domination_attach_grant_parity():
    """**GENUINE real-EoE cross-engine probe -- Duskmourn's Domination
    (0-Effect Aura: control-magic + lose-all-abilities attach-grant
    printing-flag byte-equal round-trip through BOTH engines).**

    Drives the **real parsed Duskmourn's Domination printing**
    end-to-end: reads the load-bearing attach-grant flags off the real
    printing, mirrors them onto a CardDef, and asserts that BOTH the
    Python printing materialization
    (``_card_def_to_python_printing``) AND the Rust registry getters
    (``get_printing_aura_grants_control`` /
    ``get_printing_aura_grants_lose_abilities`` /
    ``get_printing_aura_enchant_type`` / ``get_printing_is_aura``) read
    back the SAME booleans the real printing carries -- a genuine
    cross-engine byte-equality on the Aura's entire gameplay surface
    (it emits no Effects).

    **Observables asserted (byte-equal across Python + Rust):**
      * Real printing: ``attached_grants_control == True``,
        ``attached_grants_lose_all_abilities == True``,
        ``aura_enchant_type == "creature"``.
      * Python round-trip: identical booleans on the materialized
        CardPrinting.
      * Rust round-trip: identical booleans on the registry getters,
        plus ``get_printing_is_aura == True``.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_rust_registry, _card_def_to_python_printing,
    )

    # ---- 1. Verify the genuine parsed printing. ----
    real = _PRINTINGS.get("Duskmourn's Domination")
    if real is None:
        pytest.skip("Duskmourn's Domination absent from active CardSource")
    assert "Enchantment" in real.card_types
    assert real.attached_grants_control is True, (
        f"Duskmourn's Domination must grant control of its host; got "
        f"{real.attached_grants_control!r}"
    )
    assert real.attached_grants_lose_all_abilities is True, (
        f"Duskmourn's Domination must strip its host's abilities; got "
        f"{real.attached_grants_lose_all_abilities!r}"
    )
    assert real.aura_enchant_type == "creature", (
        f"Duskmourn's Domination must enchant creatures; got "
        f"{real.aura_enchant_type!r}"
    )

    # ---- 2. Mirror the real printing's flags onto a CardDef. ----
    card = CardDef(
        name="Duskmourn's Domination",
        card_type="Enchantment",
        mana_cost_generic=4,
        mana_cost_colored=(("U", 2),),
        is_aura=True,
        aura_enchant_type=real.aura_enchant_type,
        aura_grants_control=real.attached_grants_control,
        aura_grants_lose_abilities=real.attached_grants_lose_all_abilities,
    )

    # ---- 3a. Python-side byte-equal round-trip. ----
    py_printing = _card_def_to_python_printing(card)
    assert py_printing.attached_grants_control is True
    assert py_printing.attached_grants_lose_all_abilities is True
    assert py_printing.aura_enchant_type == "creature"

    # ---- 3b. Rust-side byte-equal round-trip. ----
    reg, name_to_pid = build_rust_registry(
        DeckSpec(card_defs=(card,), p0_library=(), p1_library=())
    )
    pid = name_to_pid["Duskmourn's Domination"]
    assert reg.get_printing_is_aura(pid) is True, (
        "Rust registry must mark Duskmourn's Domination as an Aura"
    )
    assert reg.get_printing_aura_grants_control(pid) is True, (
        "Rust registry must read back attached_grants_control=True"
    )
    assert reg.get_printing_aura_grants_lose_abilities(pid) is True, (
        "Rust registry must read back attached_grants_lose_abilities=True"
    )
    assert reg.get_printing_aura_enchant_type(pid) == "creature", (
        "Rust registry must read back aura_enchant_type='creature'"
    )

    # ---- 4. Cross-engine byte-equality: Python == Rust == real. ----
    assert (
        py_printing.attached_grants_control
        is bool(reg.get_printing_aura_grants_control(pid))
        is real.attached_grants_control
    )
    assert (
        py_printing.attached_grants_lose_all_abilities
        is bool(reg.get_printing_aura_grants_lose_abilities(pid))
        is real.attached_grants_lose_all_abilities
    )
    assert (
        py_printing.aura_enchant_type
        == reg.get_printing_aura_enchant_type(pid)
        == real.aura_enchant_type
    )
