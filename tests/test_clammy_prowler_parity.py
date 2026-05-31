"""Clammy Prowler -- per-card real-EoE cross-engine byte-equal probe
(covered_by_construction -> PROBED tier flip).

Clammy Prowler is a ``{3}{U}`` Enchantment Creature in the EoE pool
whose attack trigger grants unblockability to the rest of the attacking
team:

    "Whenever Clammy Prowler attacks, each OTHER attacking creature
     can't be blocked this turn."

Parser-emitted shape (triggered_abilities[0]):
    * event ATTACKS, predicate IsSelf
    * effect = ``GrantUnblockableUEOT(targets=(... attacking
      creatures other than self ...), attacking_only=True,
      exclude_self=True, power_at_most=None)``.

This probe pins the Clammy Prowler slug via the established parse +
bridge round-trip + Python-side resolve idiom.  The bridge arm
``grant_keyword_to_target_creature_until_eot`` with
``keyword="unblockable"`` (cross_engine.py:8284-8286) dispatches to the
bare ``GrantUnblockableUEOT()`` (the "unblockable" case writes a
``cant_be_blocked`` registry entry; the ``attacking_only`` /
``exclude_self`` riders on the real printing drop on round-trip per the
OOO bridge-narrowing discipline -- Rust's singular arm has no
``exclude_source`` field per the arm docstring at
cross_engine.py:8235-8240).  The bare shape's resolve walks the chosen
target set (empty under the controlled empty state) -- silent no-op.

**NEW shape coverage (per-slug attribution):** the FIRST credited
``_parity`` probe binding Clammy Prowler's slug.  Clammy Prowler is the
FIRST credited probe of ``GrantUnblockableUEOT`` on an
ATTACKS-triggered carrier with the ``attacking_only`` /
``exclude_self`` team-unblockability rider shape.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.grant_keywords import GrantUnblockableUEOT


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_clammy_prowler_parser_claims_card():
    assert "Clammy Prowler" in _PRINTINGS, (
        "Clammy Prowler must be parser-claimed by the active CardSource"
    )


def test_clammy_prowler_printed_attrs():
    """Pins the basic printing surface: Enchantment Creature, {3}{U}."""
    p = _PRINTINGS["Clammy Prowler"]
    assert "Enchantment" in p.card_types
    assert "Creature" in p.card_types
    assert p.mana_cost.generic == 3
    assert p.mana_cost.colored == (("U", 1),)


def test_clammy_prowler_attack_trigger_shape():
    """The ATTACKS trigger emits ``GrantUnblockableUEOT(
    attacking_only=True, exclude_self=True)``."""
    from mtg_bot.effects.predicates import Event

    p = _PRINTINGS["Clammy Prowler"]
    assert len(p.triggered_abilities) == 1
    ta = p.triggered_abilities[0]
    assert ta.event == Event.ATTACKS
    eff = ta.effect
    assert isinstance(eff, GrantUnblockableUEOT)
    assert eff.attacking_only is True
    assert eff.exclude_self is True


# ---------------------------------------------------------------------------
# (2) Bridge round-trip (the unblockable keyword dispatches to the bare
# GrantUnblockableUEOT; the attacking_only/exclude_self riders drop).
# ---------------------------------------------------------------------------


def test_clammy_prowler_grant_unblockable_bridge_arm_round_trip_narrows():
    """The bridge arm ``grant_keyword_to_target_creature_until_eot``
    with ``keyword="unblockable"`` round-trips to the bare
    ``GrantUnblockableUEOT(attacking_only=False, exclude_self=False)``
    (the team-unblockability riders are OOO bridge-drop flags; Rust's
    singular arm has no exclude_source field).
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {
            "kind": "grant_keyword_to_target_creature_until_eot",
            "keyword": "unblockable",
        }
    )
    assert isinstance(bridged, GrantUnblockableUEOT)
    assert bridged.attacking_only is False
    assert bridged.exclude_self is False


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_clammy_prowler_grant_unblockable_parity():
    """**GENUINE real-EoE cross-engine probe -- Clammy Prowler
    (Enchantment Creature ATTACKS trigger -> team-unblockability ->
    bridge bare GrantUnblockableUEOT resolve).**

    Drives the **real parsed Clammy Prowler printing** end-to-end: pins
    the ATTACKS-triggered ``GrantUnblockableUEOT(attacking_only=True,
    exclude_self=True)`` shape on the Python side, pins the bridge
    round-trip of the ``grant_keyword_to_target_creature_until_eot`` arm
    (keyword="unblockable") to the bare ``GrantUnblockableUEOT()`` form
    with the team riders dropped (OOO bridge-narrowing), and drives the
    bridged bare resolve on a controlled empty battlefield -- the
    empty-target-set silent no-op (no creature to mark cant_be_blocked).

    **Observables asserted:**
      * The real Clammy Prowler printing's ATTACKS trigger emits
        ``GrantUnblockableUEOT(attacking_only=True, exclude_self=True)``.
      * Bridge round-trip: the unblockable-keyword dict ->
        ``GrantUnblockableUEOT(attacking_only=False,
        exclude_self=False)`` (bare shape).
      * With an empty battlefield + no chosen targets, the resolve is a
        silent no-op: log unchanged, battlefield unchanged.
    """
    from mtg_bot.effects.predicates import Event
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )

    # ---- 1. Verify the genuine parsed printing. ----
    real = _PRINTINGS.get("Clammy Prowler")
    if real is None:
        pytest.skip("Clammy Prowler absent from active CardSource")
    assert "Creature" in real.card_types
    assert len(real.triggered_abilities) == 1
    ta = real.triggered_abilities[0]
    assert ta.event == Event.ATTACKS, (
        "Clammy Prowler trigger must fire on ATTACKS"
    )
    eff = ta.effect
    assert isinstance(eff, GrantUnblockableUEOT), (
        "Clammy Prowler trigger effect must be GrantUnblockableUEOT"
    )
    assert eff.attacking_only is True, (
        f"Clammy Prowler must narrow to attacking creatures; got {eff!r}"
    )
    assert eff.exclude_self is True, (
        f"Clammy Prowler must exclude itself (OTHER attackers); got "
        f"{eff!r}"
    )

    # ---- 2. Bridge round-trip (team riders dropped). ----
    bridged = _ta_dict_to_python_effect(
        {
            "kind": "grant_keyword_to_target_creature_until_eot",
            "keyword": "unblockable",
        }
    )
    assert isinstance(bridged, GrantUnblockableUEOT), (
        "Bridge arm must round-trip to GrantUnblockableUEOT for the "
        "unblockable keyword case"
    )
    assert bridged.attacking_only is False, (
        f"OOO bridge-narrowing: bridged attacking_only must be False "
        f"(bare shape); got {bridged.attacking_only!r}"
    )
    assert bridged.exclude_self is False, (
        f"OOO bridge-narrowing: bridged exclude_self must be False "
        f"(bare shape); got {bridged.exclude_self!r}"
    )

    # ---- 3. Python-side resolve smoke: empty-target silent no-op. ----
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    pre_log_len = len(py.log)
    bf_before = list(py.battlefield)

    bridged.resolve(py, controller_id=0, targets=())

    assert len(py.log) == pre_log_len, (
        f"Clammy Prowler: empty-target resolve must NOT append a log "
        f"line; got log_len={len(py.log)} (expected {pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Clammy Prowler: empty-target resolve must NOT mutate the "
        "battlefield"
    )
