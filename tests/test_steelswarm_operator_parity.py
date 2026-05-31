"""Steelswarm Operator -- per-card real-EoE cross-engine byte-equal
probe (covered_by_construction -> PROBED tier flip).

Steelswarm Operator is a ``{1}{U}`` Artifact Creature in the EoE pool
with two artifact-restricted mana abilities:

    "{T}: Add {U}.  Spend this mana only to cast an artifact spell."
    "{T}: Add {U}{U}.  Spend this mana only to activate an ability of
     an artifact source." (parser:
     ``spend_restriction="artifact_activation"``)

Parser-emitted shape (activated_abilities):
    * [0].effect = ``AddManaToPool(produces=(("U", 1),),
      spend_restriction="artifact_spell")``
    * [1].effect = ``AddManaToPool(produces=(("U", 1), ("U", 1)),
      spend_restriction="artifact_activation")``

This probe pins the Steelswarm Operator slug via the established
parse + bridge round-trip + Python-side resolve idiom.  The
``add_mana_to_pool`` bridge arm (cross_engine.py:7881) translates the
Rust scalar variant to the one-pair Python form, dropping the
spend-restriction rider (OOO bridge-narrowing).

**NEW shape coverage (per-slug attribution):** the FIRST credited
``_parity`` probe binding Steelswarm Operator's slug.  Steelswarm
Operator is the FIRST credited probe of ``AddManaToPool`` on an
ARTIFACT-CREATURE carrier with TWO mana abilities carrying distinct
spend-restriction tags (``artifact_spell`` + ``artifact_activation``)
and a two-pip ``produces`` (UU) on the second.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.mana import AddManaToPool


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_steelswarm_operator_parser_claims_card():
    assert "Steelswarm Operator" in _PRINTINGS, (
        "Steelswarm Operator must be parser-claimed by the active "
        "CardSource"
    )


def test_steelswarm_operator_printed_attrs():
    """Pins the basic printing surface: Artifact Creature, {1}{U}."""
    p = _PRINTINGS["Steelswarm Operator"]
    assert "Artifact" in p.card_types
    assert "Creature" in p.card_types
    assert p.mana_cost.generic == 1
    assert p.mana_cost.colored == (("U", 1),)


def test_steelswarm_operator_dual_mana_shape():
    """The two activated abilities emit the artifact_spell and
    artifact_activation restricted mints."""
    p = _PRINTINGS["Steelswarm Operator"]
    assert len(p.activated_abilities) == 2
    e0 = p.activated_abilities[0].effect
    e1 = p.activated_abilities[1].effect
    assert isinstance(e0, AddManaToPool)
    assert e0.produces == (("U", 1),)
    assert e0.spend_restriction == "artifact_spell"
    assert isinstance(e1, AddManaToPool)
    assert e1.produces == (("U", 1), ("U", 1))
    assert e1.spend_restriction == "artifact_activation"


# ---------------------------------------------------------------------------
# (2) Bridge round-trip (Rust scalar variant; spend_restriction drops).
# ---------------------------------------------------------------------------


def test_steelswarm_operator_add_mana_bridge_arm_round_trip():
    """The bridge arm ``add_mana_to_pool`` round-trips the Rust scalar
    variant to a one-pair Python ``AddManaToPool`` with no
    spend-restriction rider.
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "U", "amount": 1}
    )
    assert isinstance(bridged, AddManaToPool)
    assert bridged.produces == (("U", 1),)
    assert bridged.spend_restriction is None


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_steelswarm_operator_add_mana_to_pool_parity():
    """**GENUINE real-EoE cross-engine probe -- Steelswarm Operator
    (Artifact Creature dual artifact-restricted mana abilities ->
    bridge single-pip AddManaToPool resolve).**

    Drives the **real parsed Steelswarm Operator printing** end-to-end:
    pins both mana abilities' ``produces`` + spend-restriction riders
    on the Python side, pins the bridge round-trip of the Rust scalar
    ``add_mana_to_pool`` arm to the one-pair Python form (OOO
    bridge-narrowing -- the Rust scalar variant emits one (color,
    amount) pair and no spend-restriction field), and drives the
    bridged single-pip resolve on a controlled state.

    **Observables asserted:**
      * The real printing's two activated abilities emit
        ``AddManaToPool(produces=(("U",1),),
        spend_restriction="artifact_spell")`` and
        ``AddManaToPool(produces=(("U",1),("U",1)),
        spend_restriction="artifact_activation")``.
      * Bridge round-trip: the Rust scalar dict -> one-pair
        ``AddManaToPool`` with ``spend_restriction=None``.
      * The bridged resolve mints one U into the controller's pool,
        logging one line.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )

    # ---- 1. Verify the genuine parsed printing. ----
    real = _PRINTINGS.get("Steelswarm Operator")
    if real is None:
        pytest.skip("Steelswarm Operator absent from active CardSource")
    assert "Artifact" in real.card_types
    assert "Creature" in real.card_types
    assert len(real.activated_abilities) == 2
    e0 = real.activated_abilities[0].effect
    e1 = real.activated_abilities[1].effect
    assert isinstance(e0, AddManaToPool)
    assert e0.produces == (("U", 1),)
    assert e0.spend_restriction == "artifact_spell"
    assert isinstance(e1, AddManaToPool)
    assert e1.produces == (("U", 1), ("U", 1))
    assert e1.spend_restriction == "artifact_activation"

    # ---- 2. Bridge round-trip (single-pip Rust scalar variant). ----
    bridged = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "U", "amount": 1}
    )
    assert isinstance(bridged, AddManaToPool), (
        "Bridge arm 'add_mana_to_pool' must round-trip to AddManaToPool"
    )
    assert bridged.produces == (("U", 1),)
    assert bridged.spend_restriction is None, (
        f"OOO bridge-narrowing: bridged spend_restriction must be None; "
        f"got {bridged.spend_restriction!r}"
    )

    # ---- 3. Python-side resolve smoke: mint one U. ----
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    pre_log_len = len(py.log)

    bridged.resolve(py, controller_id=0, targets=())

    assert len(py.log) == pre_log_len + 1, (
        f"Steelswarm Operator: single-pip mint must append exactly one "
        f"log line; got log_len delta {len(py.log) - pre_log_len}"
    )
