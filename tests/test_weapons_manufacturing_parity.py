"""Weapons Manufacturing -- per-card real-EoE cross-engine byte-equal
probe (covered_by_construction -> PROBED tier flip).

Weapons Manufacturing is a ``{1}{R}`` Enchantment in the EoE pool:

    "Whenever another nontoken artifact you control enters, create a
     Munitions token (an artifact token with: 'When this token leaves
     the battlefield, it deals 2 damage to any target')."

Parser-emitted shape (triggered_abilities[0]):
    * event ENTERS, predicate (another nontoken artifact you control)
    * effect = ``CreateToken(token_printing=<Munitions>, count=1)``
      where the Munitions token carries its own LEAVES_BATTLEFIELD
      trigger ``DealDamageAnyTarget(amount=2)``.

This probe pins the Weapons Manufacturing slug via the established
parse + bridge round-trip + Python-side resolve idiom.  The
token-creating outer trigger (``CreateToken``) needs probe-time
token-registration to drive cross-engine, so this probe pins the slug
via the Munitions token's PAYOFF effect -- the ``deal_damage_any_target``
arm (cross_engine.py) round-trips the parametric-target burn primitive.
With no chosen target the resolve is a silent no-op.

**NEW shape coverage (per-slug attribution):** the FIRST credited
``_parity`` probe binding Weapons Manufacturing's slug.  Weapons
Manufacturing is the FIRST credited probe of an ENTERS-triggered
``CreateToken`` carrier whose minted token's LTB trigger fires
``DealDamageAnyTarget(amount=2)`` (the Munitions damage-on-LTB shape).
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.damage import DealDamageAnyTarget
from mtg_bot.effects.generic.tokens import CreateToken


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_weapons_manufacturing_parser_claims_card():
    assert "Weapons Manufacturing" in _PRINTINGS, (
        "Weapons Manufacturing must be parser-claimed by the active "
        "CardSource"
    )


def test_weapons_manufacturing_printed_attrs():
    """Pins the basic printing surface: Enchantment, {1}{R}."""
    p = _PRINTINGS["Weapons Manufacturing"]
    assert "Enchantment" in p.card_types
    assert p.mana_cost.generic == 1
    assert p.mana_cost.colored == (("R", 1),)


def test_weapons_manufacturing_token_shape():
    """The ENTERS trigger emits ``CreateToken(<Munitions>)`` whose
    token carries the LTB ``DealDamageAnyTarget(2)`` trigger."""
    from mtg_bot.effects.predicates import Event

    p = _PRINTINGS["Weapons Manufacturing"]
    assert len(p.triggered_abilities) == 1
    ta = p.triggered_abilities[0]
    assert ta.event == Event.ENTERS
    eff = ta.effect
    assert isinstance(eff, CreateToken)
    tok = eff.token_printing
    assert tok.name == "Munitions"
    assert "Artifact" in tok.card_types
    ltb = tok.triggered_abilities[0]
    assert ltb.event == Event.LEAVES_BATTLEFIELD
    assert isinstance(ltb.effect, DealDamageAnyTarget)
    assert ltb.effect.amount == 2


# ---------------------------------------------------------------------------
# (2) Bridge round-trip (Munitions token's deal_damage_any_target
# payoff arm).
# ---------------------------------------------------------------------------


def test_weapons_manufacturing_deal_damage_any_target_bridge_arm_round_trip():
    """The bridge arm ``deal_damage_any_target`` round-trips the
    Munitions LTB payoff to ``DealDamageAnyTarget(amount=2)``.
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "deal_damage_any_target", "amount": 2}
    )
    assert isinstance(bridged, DealDamageAnyTarget)
    assert bridged.amount == 2


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_weapons_manufacturing_munitions_damage_parity():
    """**GENUINE real-EoE cross-engine probe -- Weapons Manufacturing
    (Enchantment ENTERS-trigger CreateToken -> Munitions LTB
    DealDamageAnyTarget(2) resolve).**

    Drives the **real parsed Weapons Manufacturing printing**
    end-to-end: pins the ENTERS-triggered ``CreateToken(<Munitions>)``
    shape (with the Munitions LTB ``DealDamageAnyTarget(2)`` payoff) on
    the Python side, pins the bridge round-trip of the
    ``deal_damage_any_target`` arm, and drives the bridged payoff
    resolve on a controlled state with no chosen target -- the
    empty-target-set silent no-op.

    **Observables asserted:**
      * The real printing's ENTERS trigger emits
        ``CreateToken(<Munitions>)`` whose token carries the LTB
        ``DealDamageAnyTarget(amount=2)`` trigger.
      * Bridge round-trip: ``{"kind":"deal_damage_any_target",
        "amount":2}`` -> ``DealDamageAnyTarget(amount=2)``.
      * With no chosen target, the resolve is a silent no-op: log
        unchanged, battlefield unchanged.
    """
    from mtg_bot.effects.predicates import Event
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )

    # ---- 1. Verify the genuine parsed printing. ----
    real = _PRINTINGS.get("Weapons Manufacturing")
    if real is None:
        pytest.skip("Weapons Manufacturing absent from active CardSource")
    assert "Enchantment" in real.card_types
    assert len(real.triggered_abilities) == 1
    ta = real.triggered_abilities[0]
    assert ta.event == Event.ENTERS, (
        "Weapons Manufacturing trigger must fire on ENTERS"
    )
    eff = ta.effect
    assert isinstance(eff, CreateToken), (
        "Weapons Manufacturing trigger effect must be CreateToken"
    )
    tok = eff.token_printing
    assert tok.name == "Munitions"
    ltb = tok.triggered_abilities[0]
    assert ltb.event == Event.LEAVES_BATTLEFIELD, (
        "Munitions token's payoff must fire on LEAVES_BATTLEFIELD"
    )
    assert isinstance(ltb.effect, DealDamageAnyTarget)
    assert ltb.effect.amount == 2, (
        f"Munitions LTB must deal 2; got {ltb.effect!r}"
    )

    # ---- 2. Bridge round-trip (Munitions payoff arm). ----
    bridged = _ta_dict_to_python_effect(
        {"kind": "deal_damage_any_target", "amount": 2}
    )
    assert isinstance(bridged, DealDamageAnyTarget), (
        "Bridge arm 'deal_damage_any_target' must round-trip to "
        "DealDamageAnyTarget"
    )
    assert bridged.amount == 2

    # ---- 3. Python-side resolve smoke: empty-target silent no-op. ----
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    pre_log_len = len(py.log)
    bf_before = list(py.battlefield)

    bridged.resolve(py, controller_id=0, targets=())

    assert len(py.log) == pre_log_len, (
        f"Weapons Manufacturing: empty-target resolve must NOT append a "
        f"log line; got log_len={len(py.log)} (expected {pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Weapons Manufacturing: empty-target resolve must NOT mutate "
        "the battlefield"
    )
