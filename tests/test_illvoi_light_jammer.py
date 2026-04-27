"""Card-level tests for Illvoi Light Jammer.

Oracle text:
  Flash
  When this Equipment enters, attach it to target creature you
  control. That creature gains hexproof until end of turn.
  Equipped creature gets +1/+2.
  Equip {3}

We model the ETB attach + UEOT hexproof grant via
``AttachToTargetCreatureYouControl(granted_keywords_ueot=…)`` and the
equipped +1/+2 buff via the standard equipment_bonuses pipeline. Equip
{3} is intentionally not modeled (no Equipment in the EoE pool wires
the Equip activated ability yet).
"""

from __future__ import annotations

from mtg_bot.cards import EOE_CREATURES, SYNTHETIC_CREATURES
from mtg_bot.effects import AttachToTargetCreatureYouControl
from mtg_bot.game import (
    Zone,
    effective_keywords,
    effective_power,
    effective_toughness,
)
from mtg_bot.turn import run_cleanup_step

from tests._rules_helpers import _arena


def _put_bear(state, owner_id):
    obj = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=owner_id,
        zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(obj)
    return obj


def _put_jammer(state, owner_id):
    obj = state.new_object(
        EOE_CREATURES["Illvoi Light Jammer"], owner_id=owner_id,
        zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(obj)
    return obj


def _resolve_etb(state, jammer, target_creature):
    etb = next(
        ab for ab in jammer.printing.triggered_abilities if ab.trigger == "etb"
    )
    state.resolving_source = jammer
    try:
        etb.effect.resolve(state, jammer.controller_id,
                           (("creature", target_creature.id),))
    finally:
        state.resolving_source = None


def test_etb_attaches_and_grants_hexproof_ueot():
    """ETB attaches the Equipment AND grants hexproof to that creature."""
    state = _arena()
    ally = _put_bear(state, owner_id=0)
    jammer = _put_jammer(state, owner_id=0)

    _resolve_etb(state, jammer, ally)

    # Attach succeeded.
    assert jammer.attached_to == ally.id
    # Hexproof was granted UEOT (via the layer-6 registry — Phase 2).
    assert "hexproof" in effective_keywords(state, ally)
    # Equipment bonus is also live (continuous, from equipment_bonuses).
    assert effective_power(state, ally) == 3  # 2 + 1
    assert effective_toughness(state, ally) == 4  # 2 + 2


def test_hexproof_visible_to_opponent_targeting_check():
    """An opponent's targeted effect sees hexproof on the equipped creature.

    The codebase's keyword pipeline (``effective_keywords``) is the single
    source of truth any future targeting-protection check would consult.
    Verify it reports hexproof regardless of which player's perspective is
    asking — i.e. the keyword is present in the shared game state, not
    scoped to the controller.
    """
    state = _arena()
    ally = _put_bear(state, owner_id=0)
    jammer = _put_jammer(state, owner_id=0)

    _resolve_etb(state, jammer, ally)

    # An opponent (P1) consulting the creature's keywords sees hexproof.
    kws = effective_keywords(state, ally)
    assert "hexproof" in kws


def test_hexproof_clears_at_cleanup():
    """The granted hexproof is until end of turn — cleared at cleanup."""
    state = _arena()
    ally = _put_bear(state, owner_id=0)
    jammer = _put_jammer(state, owner_id=0)

    _resolve_etb(state, jammer, ally)
    assert "hexproof" in effective_keywords(state, ally)

    run_cleanup_step(state)

    assert "hexproof" not in effective_keywords(state, ally)
    # Equipment is still attached after cleanup; attach is permanent.
    assert jammer.attached_to == ally.id
    # The continuous +1/+2 bonus survives cleanup (it's static, not UEOT).
    assert effective_power(state, ally) == 3
    assert effective_toughness(state, ally) == 4


def test_etb_no_legal_target_fizzles_no_hexproof_granted():
    """If there's no legal creature to attach to, no hexproof leaks out.

    Sanity check that the keyword grant is gated on the attach actually
    succeeding — not handed out as a side-effect of resolving with an
    invalid/absent target.
    """
    state = _arena()
    # No friendly creatures on board for jammer to attach to.
    jammer = _put_jammer(state, owner_id=0)
    enemy = _put_bear(state, owner_id=1)

    etb = next(
        ab for ab in jammer.printing.triggered_abilities if ab.trigger == "etb"
    )
    state.resolving_source = jammer
    try:
        # Pointing at an opponent's creature — the attach effect refuses
        # (target.controller_id != controller_id), so no hexproof either.
        etb.effect.resolve(state, 0, (("creature", enemy.id),))
    finally:
        state.resolving_source = None

    assert jammer.attached_to is None
    assert "hexproof" not in effective_keywords(state, enemy)


def test_attach_effect_default_no_keywords_granted():
    """AttachToTargetCreatureYouControl() with no kwargs grants nothing.

    Backward-compat check: peer Equipment cards (Meltstrider's Gear,
    Squire's Lightblade, etc.) instantiate the effect with no arguments
    and must keep working — no spurious keyword grants.
    """
    e = AttachToTargetCreatureYouControl()
    assert e.granted_keywords_ueot == frozenset()
    assert "hexproof" not in e.describe()

    e_hex = AttachToTargetCreatureYouControl(
        granted_keywords_ueot=frozenset({"hexproof"})
    )
    assert "hexproof" in e_hex.describe()
