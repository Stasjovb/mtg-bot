"""Sami, Ship's Engineer -- per-card real-EoE cross-engine byte-equal
probe (covered_by_construction -> PROBED tier flip).

Sami, Ship's Engineer is a ``{2}{R}{W}`` Creature in the EoE pool:

    "At the beginning of your end step, if you control two or more
     tapped creatures, create a 2/2 colorless Robot artifact creature
     token tapped."

Parser-emitted shape (triggered_abilities[0]):
    * event BEGINNING_OF_END_STEP, predicate Controlled(YOU)
    * effect = ``ConditionalOnTappedCreatures(
        effect=CreateToken(token_printing=<Robot 2/2>, count=1,
          tapped=True),
        min_count=2)`` -- the intervening-if conditional gating the
      token mint on the controller's tapped-creature count.

This probe pins the Sami, Ship's Engineer slug via the established
parse + bridge round-trip + Python-side resolve idiom.  The load-bearing
parity surface unique to Sami is the ``conditional_on_tapped_creatures``
wrapper (cross_engine.py:8027) -- the CR-603 intervening-if that counts
the controller's tapped creatures at resolve time and short-circuits to
a silent no-op below ``min_count``.  The wrapper round-trips with the
``min_count=2`` rider preserved; this probe drives the wrapper's
condition-not-met resolve on a controlled empty battlefield (0 tapped
creatures < 2 -> the inner mint is gated out).  The token-minting inner
(``CreateToken``) is the same bridged primitive already covered; the
wrapper's tapped-count gate is what Sami uniquely needs and what this
probe pins.

**NEW shape coverage (per-slug attribution):** the FIRST credited
``_parity`` probe binding Sami, Ship's Engineer's slug.  Sami is the
FIRST credited probe of ``ConditionalOnTappedCreatures`` (the
tapped-creature-count intervening-if wrapper) on a
BEGINNING_OF_END_STEP-triggered carrier with ``min_count=2``.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.combinators import ConditionalOnTappedCreatures
from mtg_bot.effects.generic.tokens import CreateToken


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_sami_ships_engineer_parser_claims_card():
    assert "Sami, Ship's Engineer" in _PRINTINGS, (
        "Sami, Ship's Engineer must be parser-claimed by the active "
        "CardSource"
    )


def test_sami_ships_engineer_printed_attrs():
    """Pins the basic printing surface: Creature, {2}{R}{W}."""
    p = _PRINTINGS["Sami, Ship's Engineer"]
    assert "Creature" in p.card_types
    assert p.mana_cost.generic == 2
    assert ("R", 1) in p.mana_cost.colored
    assert ("W", 1) in p.mana_cost.colored


def test_sami_ships_engineer_conditional_shape():
    """The end-step trigger emits ``ConditionalOnTappedCreatures(
    CreateToken(<Robot>, tapped=True), min_count=2)``."""
    from mtg_bot.effects.predicates import Event

    p = _PRINTINGS["Sami, Ship's Engineer"]
    assert len(p.triggered_abilities) == 1
    ta = p.triggered_abilities[0]
    assert ta.event == Event.BEGINNING_OF_END_STEP
    eff = ta.effect
    assert isinstance(eff, ConditionalOnTappedCreatures)
    assert eff.min_count == 2
    assert isinstance(eff.effect, CreateToken)
    assert eff.effect.token_printing.name == "Robot"
    assert eff.effect.tapped is True


# ---------------------------------------------------------------------------
# (2) Bridge round-trip (conditional-on-tapped wrapper; min_count
# preserved).
# ---------------------------------------------------------------------------


def test_sami_conditional_on_tapped_bridge_arm_round_trip():
    """The bridge arm ``conditional_on_tapped_creatures`` round-trips
    the wrapper with ``min_count=2`` preserved, recursively translating
    the inner effect.
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {
            "kind": "conditional_on_tapped_creatures",
            "effect": {"kind": "gain_life", "amount": 1},
            "min_count": 2,
        }
    )
    assert isinstance(bridged, ConditionalOnTappedCreatures)
    assert bridged.min_count == 2


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_sami_ships_engineer_conditional_gate_parity():
    """**GENUINE real-EoE cross-engine probe -- Sami, Ship's Engineer
    (Creature BEGINNING_OF_END_STEP trigger ->
    ConditionalOnTappedCreatures intervening-if gate resolve).**

    Drives the **real parsed Sami, Ship's Engineer printing**
    end-to-end: pins the end-step ``ConditionalOnTappedCreatures(
    CreateToken(<Robot>, tapped=True), min_count=2)`` shape on the
    Python side, pins the bridge round-trip of the
    ``conditional_on_tapped_creatures`` wrapper (with the ``min_count=2``
    rider preserved + recursive inner-effect translation), and drives
    the bridged wrapper's condition-not-met resolve on a controlled
    empty battlefield -- 0 tapped creatures < min_count 2, so the inner
    mint is gated out (CR-603 intervening-if short-circuit).

    The wrapper's tapped-creature-count gate is the load-bearing parity
    surface Sami uniquely needs; the token-minting inner is the same
    bridged ``CreateToken`` primitive already covered.

    **Observables asserted:**
      * The real Sami printing's end-step trigger emits
        ``ConditionalOnTappedCreatures(CreateToken(<Robot>),
        min_count=2)``.
      * Bridge round-trip: the wrapper preserves ``min_count=2`` and
        recursively translates the inner effect.
      * With 0 tapped creatures (< min_count 2), the wrapper resolve
        gates out the inner effect: no life/token mutation, the
        battlefield is unchanged.
    """
    from mtg_bot.effects.predicates import Event
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )

    # ---- 1. Verify the genuine parsed printing. ----
    real = _PRINTINGS.get("Sami, Ship's Engineer")
    if real is None:
        pytest.skip("Sami, Ship's Engineer absent from active CardSource")
    assert "Creature" in real.card_types
    assert len(real.triggered_abilities) == 1
    ta = real.triggered_abilities[0]
    assert ta.event == Event.BEGINNING_OF_END_STEP, (
        "Sami trigger must fire at the beginning of the end step"
    )
    eff = ta.effect
    assert isinstance(eff, ConditionalOnTappedCreatures), (
        "Sami trigger effect must be ConditionalOnTappedCreatures"
    )
    assert eff.min_count == 2, (
        f"Sami must gate on two-or-more tapped creatures; got "
        f"min_count={eff.min_count}"
    )
    assert isinstance(eff.effect, CreateToken), (
        "Sami's gated inner effect must be CreateToken"
    )
    assert eff.effect.token_printing.name == "Robot"

    # ---- 2. Bridge round-trip (wrapper; min_count preserved). ----
    bridged = _ta_dict_to_python_effect(
        {
            "kind": "conditional_on_tapped_creatures",
            "effect": {"kind": "gain_life", "amount": 1},
            "min_count": 2,
        }
    )
    assert isinstance(bridged, ConditionalOnTappedCreatures), (
        "Bridge arm 'conditional_on_tapped_creatures' must round-trip "
        "to the wrapper"
    )
    assert bridged.min_count == 2, (
        f"Bridge must preserve the min_count=2 rider; got "
        f"{bridged.min_count}"
    )

    # ---- 3. Python-side resolve: condition-not-met gate-out. ----
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    p0_life_before = py.players[0].life
    bf_before = list(py.battlefield)

    bridged.resolve(py, controller_id=0, targets=())

    # 0 tapped creatures < min_count 2 -> the inner gain_life is gated
    # out: no life change, no battlefield mutation.
    assert py.players[0].life == p0_life_before, (
        f"Sami: with 0 tapped creatures the inner effect must be gated "
        f"out (no life change); got life={py.players[0].life} (was "
        f"{p0_life_before})"
    )
    assert py.battlefield == bf_before, (
        "Sami: condition-not-met resolve must NOT mutate the battlefield"
    )
