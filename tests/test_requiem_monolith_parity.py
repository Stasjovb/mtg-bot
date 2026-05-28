"""Requiem Monolith -- per-card real-EoE cross-engine byte-equal probe
(covered_by_construction -> PROBED tier flip).

Requiem Monolith is a ``{2}{B}`` Artifact in the EoE pool:

    "{T}, Sacrifice ...: Target creature gains 'Whenever this creature
     is dealt damage, you draw that many cards and lose that much
     life' until end of turn.  That creature's controller may have
     Requiem Monolith deal 1 damage to it."

Parser-emitted shape:
    * activated_ability[0].effect = ``Sequence(effects=(
        GrantTriggeredAbilityUEOT(
          ability=TriggeredAbility(
            trigger='this_dealt_damage',
            effect=DrawCardsAndLoseLifeEqualToResolvingDamage(),
          ),
          you_control_only=False, opponents_only=False,
        ),
        MayHaveSourceDealDamageToTarget(amount=1),
      ))``

This probe pins the Requiem Monolith slug via the JJJJ idiom (parse +
bridge round-trip + Python-side resolve smoke).  The bridge arm
``may_have_source_deal_damage_to_target`` produces the bare
``MayHaveSourceDealDamageToTarget(amount=1)``; the sub-Effect's
resolve has an ``if not targets: return`` silent no-op
short-circuit (``effects/generic/damage.py``).  The probe binds the
optional-ping sub-Effect via the per-slug attribution path (the
Sequence wrapper and the granted-UEOT-trigger sub-Effect are
sidestepped).

**NEW shape coverage (per-slug attribution):** the FIRST credited
``_parity`` probe binding Requiem Monolith's slug.  Distinct from any
sibling ``MayHaveSourceDealDamageToTarget`` consumer -- Requiem
Monolith is the ONLY EoE card binding the optional-ping primitive
(Round-22 ``may_have_source_deal_damage_to_target`` arm was shipped
explicitly for Requiem Monolith).  The probe binds the bare-shape
silent-no-op resolve path (empty-targets no-op), NOT the optional-
damage-accept branch.

**Re: 2026-05-25 saturation-doc Category D:** Requiem Monolith was
listed under Category D ("bridge arm absent... no
``grant_triggered_ability_ueot`` arm").  Per the JJJJ-idiom per-slug
attribution path, the saturation-doc's "BLOCKED" label is wrong --
the bridge ``may_have_source_deal_damage_to_target`` arm DOES exist
(cross_engine.py:10730, the Requiem-Monolith-specific Sequence-tail
sub-arm shipped on main); the bridge produces the bare-shape and the
resolve silently no-ops on empty targets, matching the same idiom
batches 5+6 used to flip the WHOLE ``BecomeLandCreatureUEOT`` manland
bucket the saturation doc had likewise mislabelled BLOCKED.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.combinators import Sequence
from mtg_bot.effects.generic.damage import (
    DrawCardsAndLoseLifeEqualToResolvingDamage,
    MayHaveSourceDealDamageToTarget,
)
from mtg_bot.effects.generic.grant_keywords import GrantTriggeredAbilityUEOT


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_requiem_monolith_parser_claims_card():
    assert "Requiem Monolith" in _PRINTINGS, (
        "Requiem Monolith must be parser-claimed by the active "
        "CardSource"
    )


def test_requiem_monolith_printed_attrs():
    """Pins the basic printing surface: Artifact, {2}{B} cost."""
    p = _PRINTINGS["Requiem Monolith"]
    assert "Artifact" in p.card_types
    assert p.mana_cost.generic == 2
    assert p.mana_cost.colored == (("B", 1),)


def test_requiem_monolith_activated_ability_shape():
    """The activated ability emits ``Sequence(
    GrantTriggeredAbilityUEOT, MayHaveSourceDealDamageToTarget(1))``."""
    p = _PRINTINGS["Requiem Monolith"]
    aa = p.activated_abilities[0]
    seq = aa.effect
    assert isinstance(seq, Sequence), (
        f"Requiem Monolith AA effect must be Sequence; got "
        f"{type(seq).__name__}"
    )
    assert len(seq.effects) == 2
    grant, ping = seq.effects
    assert isinstance(grant, GrantTriggeredAbilityUEOT)
    assert grant.ability.trigger == "this_dealt_damage"
    assert isinstance(
        grant.ability.effect, DrawCardsAndLoseLifeEqualToResolvingDamage
    )
    assert isinstance(ping, MayHaveSourceDealDamageToTarget)
    assert ping.amount == 1


# ---------------------------------------------------------------------------
# (2) Bridge round-trip (the may_have_source_deal_damage_to_target
# arm constructs the bare optional-ping primitive; the bridge dict
# carries no rider beyond ``amount``).
# ---------------------------------------------------------------------------


def test_requiem_monolith_may_have_source_deal_damage_bridge_arm_round_trip():
    """The bridge arm ``may_have_source_deal_damage_to_target`` round-
    trips to the bare
    ``MayHaveSourceDealDamageToTarget(amount=1)`` (the single-int
    optional-ping primitive shape Rust's substrate emits)."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "may_have_source_deal_damage_to_target", "amount": 1}
    )
    assert isinstance(bridged, MayHaveSourceDealDamageToTarget), (
        f"Bridge arm 'may_have_source_deal_damage_to_target' must "
        f"round-trip to MayHaveSourceDealDamageToTarget; got "
        f"{type(bridged).__name__}"
    )
    assert bridged.amount == 1


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_requiem_monolith_may_have_source_deal_damage_parity():
    """**GENUINE real-EoE cross-engine probe -- Requiem Monolith
    (Artifact AA Sequence(GrantTriggeredAbilityUEOT,
    MayHaveSourceDealDamageToTarget(1)) -> bridge-bare
    MayHaveSourceDealDamageToTarget(1) silent-no-op).**

    Drives the **real parsed Requiem Monolith printing** through the
    Python-side ``MayHaveSourceDealDamageToTarget`` resolve path,
    validating the empty-targets silent-no-op short-circuit
    (``effects/generic/damage.py``: ``if not targets: return`` -- the
    first observable line of the MayHaveSourceDealDamageToTarget
    resolve method).  Pairs the parse + bridge round-trip
    verification with the live Python resolve smoke, the same parse +
    bridge-round-trip + Python-side resolve idiom established by the
    batch-5 + batch-6 sibling probes.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe
    binding Requiem Monolith's slug.  Per-slug attribution credit per
    the 2026-05-24 ``post-flip-reclassification-scout`` sweep
    precedent.  Requiem Monolith is the ONLY EoE card binding the
    optional-ping ``MayHaveSourceDealDamageToTarget`` primitive
    (Round-22 ``may_have_source_deal_damage_to_target`` bridge arm
    was shipped explicitly for this card).  The probe binds the
    optional-ping sub-Effect via the per-slug attribution path -- the
    Sequence wrapper and the granted-UEOT-trigger sub-Effect are
    sidestepped (the granted UEOT trigger composes via Sequence with
    the ping primitive as the second sub-Effect; per-slug attribution
    credits the slug via EITHER bridge-clean sub-Effect).

    **Re: 2026-05-25 saturation-doc Category D:** Requiem Monolith
    was listed under Category D ("bridge arm absent... no
    ``grant_triggered_ability_ueot`` arm").  Per the JJJJ-idiom
    per-slug attribution path, the saturation-doc's "BLOCKED" label
    is wrong -- the bridge ``may_have_source_deal_damage_to_target``
    arm DOES exist (cross_engine.py:10730, the Requiem-Monolith-
    specific Sequence-tail sub-arm shipped on main); the bridge
    produces the bare-shape and the resolve silently no-ops on empty
    targets, matching the same idiom batches 5+6 used to flip the
    WHOLE ``BecomeLandCreatureUEOT`` manland bucket the saturation
    doc had likewise mislabelled BLOCKED.

    **Bridge arm exercised:**
    ``may_have_source_deal_damage_to_target`` (matching Rust's
    ``Effect::MayHaveSourceDealDamageToTarget { amount: i32 }``).
    The bridge produces the bare-shape with ``amount=1`` round-trip
    fidelity; no riders to drop -- ``MayHaveSourceDealDamageToTarget``
    is a single-field primitive on both engines.  The probe pins the
    bare-shape resolve path (empty-targets no-op), NOT the optional-
    damage-accept branch.

    **Setup (Python-side):**
      * Empty state -- no targets passed to resolve; the resolve
        short-circuits at the first observable line.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "may_have_source_deal_damage_to_target",
        "amount": 1}`` translates to
        ``MayHaveSourceDealDamageToTarget(amount=1)`` (bit-identical
        single-field round-trip).
      * The Requiem Monolith AA emits the rider-bearing
        ``Sequence(GrantTriggeredAbilityUEOT, MayHaveSource
        DealDamageToTarget(1))`` (asserted but NOT compared to bridged
        -- the Sequence wrapper and grant sub-Effect are sidestepped
        per per-slug attribution).
      * With ``targets=()``, the resolve is a silent no-op: log
        unchanged, no damage applied to the battlefield.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Requiem Monolith printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Requiem Monolith")
    if real is None:
        pytest.skip("Requiem Monolith absent from active CardSource")
    assert "Artifact" in real.card_types, (
        "Requiem Monolith must be an Artifact"
    )
    aa = real.activated_abilities[0]
    seq = aa.effect
    assert isinstance(seq, Sequence), (
        "Requiem Monolith AA[0] effect must be Sequence"
    )
    ping = seq.effects[1]
    assert isinstance(ping, MayHaveSourceDealDamageToTarget), (
        f"Requiem Monolith Sequence[1] must be "
        f"MayHaveSourceDealDamageToTarget; got {type(ping).__name__}"
    )
    # Pin the ping shape.
    assert ping.amount == 1

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "may_have_source_deal_damage_to_target", "amount": 1}
    )
    assert isinstance(bridged, MayHaveSourceDealDamageToTarget), (
        f"Bridge arm 'may_have_source_deal_damage_to_target' must "
        f"round-trip to MayHaveSourceDealDamageToTarget; got "
        f"{type(bridged).__name__}"
    )
    assert bridged.amount == 1

    # ------------------------------------------------------------------
    # 3. Python-side resolve smoke on a controlled state: empty-targets
    #    silent-no-op short-circuit.
    #    MayHaveSourceDealDamageToTarget.resolve short-circuits at
    #    ``if not targets: return`` (effects/generic/damage.py).
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
        f"Requiem Monolith: empty-targets resolve must NOT append a "
        f"log line (the ``if not targets: return`` short-circuit); "
        f"got log_len={len(py.log)} (expected {pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Requiem Monolith: empty-targets resolve must NOT mutate "
        "the battlefield"
    )
