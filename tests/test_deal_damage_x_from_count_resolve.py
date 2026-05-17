"""Engine-resolve tests for the X-from-count damage sister classes.

``DealDamageToOpponentCreatureBy{LandsControlled,CreaturesYouControl,
CardsInGraveyard,LifeTotal}`` share a resolve substrate: empty-target
no-op, slot-target-no-longer-legal no-op, denominator<=0 no-op, else
apply damage = the denominator. Random self-play / parity smoke
exercises these only indirectly (and only the happy path), so the
no-op guards and the per-class denominator computation were
uncovered.

Also covers ``FightTargetCreatureWithTargetCreature``'s
missing-fighter silent fizzle (CR 701.12c) and the ``DealDamage``
unified primitive's defensive ``SlotRef`` / non-``TargetSpec`` slot
skips, which the recognizer never produces today.

Each test asserts the concrete post-resolve damage / no-op, not just
"it ran".
"""

from __future__ import annotations

from mtg_bot.cards import SYNTHETIC_CREATURES, make_basic_land
from mtg_bot.effects.generic.damage import (
    DealDamage,
    DealDamageToOpponentCreatureByCardsInGraveyard,
    DealDamageToOpponentCreatureByCreaturesYouControl,
    DealDamageToOpponentCreatureByLandsControlled,
    DealDamageToOpponentCreatureByLifeTotal,
    FightTargetCreatureWithTargetCreature,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step

_BEAR = SYNTHETIC_CREATURES["Wild Bear"]  # 2/2
_FOREST = make_basic_land("Forest", "G")


def _new_state() -> GameState:
    state = GameState()
    state.players.append(Player(id=0, life=20))
    state.players.append(Player(id=1, life=20))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


# ---------------------------------------------------------------------
# DealDamageToOpponentCreatureByLandsControlled
# ---------------------------------------------------------------------


def test_lands_controlled_damage_equals_land_count():
    state = _new_state()
    _put(state, _FOREST, owner_id=0)
    _put(state, _FOREST, owner_id=0)
    _put(state, _FOREST, owner_id=0)
    enemy = _put(state, _BEAR, owner_id=1)
    DealDamageToOpponentCreatureByLandsControlled().resolve(
        state, 0, (("creature", enemy.id),),
    )
    assert enemy.damage == 3


def test_lands_controlled_empty_targets_is_noop():
    state = _new_state()
    _put(state, _FOREST, owner_id=0)
    DealDamageToOpponentCreatureByLandsControlled().resolve(state, 0, ())
    # No exception, nothing applied — assert the log stayed empty.
    assert state.log == []


def test_lands_controlled_zero_lands_is_noop():
    state = _new_state()
    enemy = _put(state, _BEAR, owner_id=1)
    DealDamageToOpponentCreatureByLandsControlled().resolve(
        state, 0, (("creature", enemy.id),),
    )
    assert enemy.damage == 0


def test_lands_controlled_illegal_target_is_noop():
    """Target is the controller's OWN creature → fails the
    IsCreature() & ControlledByOpponent() slot filter → no damage."""
    state = _new_state()
    _put(state, _FOREST, owner_id=0)
    own = _put(state, _BEAR, owner_id=0)
    DealDamageToOpponentCreatureByLandsControlled().resolve(
        state, 0, (("creature", own.id),),
    )
    assert own.damage == 0


def test_lands_controlled_describe():
    assert "lands you control" in (
        DealDamageToOpponentCreatureByLandsControlled().describe()
    )


# ---------------------------------------------------------------------
# DealDamageToOpponentCreatureByCreaturesYouControl
# ---------------------------------------------------------------------


def test_creatures_controlled_damage_equals_creature_count():
    state = _new_state()
    _put(state, _BEAR, owner_id=0)
    _put(state, _BEAR, owner_id=0)
    enemy = _put(state, _BEAR, owner_id=1)
    DealDamageToOpponentCreatureByCreaturesYouControl().resolve(
        state, 0, (("creature", enemy.id),),
    )
    # 2 own creatures (the enemy is opponent-controlled, excluded).
    assert enemy.damage == 2


def test_creatures_controlled_zero_is_noop():
    state = _new_state()
    enemy = _put(state, _BEAR, owner_id=1)
    # Controller has no creatures of their own.
    DealDamageToOpponentCreatureByCreaturesYouControl().resolve(
        state, 0, (("creature", enemy.id),),
    )
    assert enemy.damage == 0


def test_creatures_controlled_empty_targets_is_noop():
    state = _new_state()
    _put(state, _BEAR, owner_id=0)
    DealDamageToOpponentCreatureByCreaturesYouControl().resolve(
        state, 0, (),
    )
    assert state.log == []


def test_creatures_controlled_describe():
    assert "creatures you control" in (
        DealDamageToOpponentCreatureByCreaturesYouControl().describe()
    )


# ---------------------------------------------------------------------
# DealDamageToOpponentCreatureByCardsInGraveyard
# ---------------------------------------------------------------------


def test_graveyard_damage_equals_gy_size():
    state = _new_state()
    enemy = _put(state, _BEAR, owner_id=1)
    # Put 4 cards in controller's graveyard.
    for _ in range(4):
        gy_obj = state.new_object(_BEAR, 0, Zone.GRAVEYARD)
        state.players[0].graveyard.append(gy_obj)
    DealDamageToOpponentCreatureByCardsInGraveyard().resolve(
        state, 0, (("creature", enemy.id),),
    )
    assert enemy.damage == 4


def test_graveyard_empty_gy_is_noop():
    state = _new_state()
    enemy = _put(state, _BEAR, owner_id=1)
    DealDamageToOpponentCreatureByCardsInGraveyard().resolve(
        state, 0, (("creature", enemy.id),),
    )
    assert enemy.damage == 0


def test_graveyard_empty_targets_is_noop():
    state = _new_state()
    DealDamageToOpponentCreatureByCardsInGraveyard().resolve(state, 0, ())
    assert state.log == []


def test_graveyard_illegal_target_is_noop():
    state = _new_state()
    own = _put(state, _BEAR, owner_id=0)
    state.players[0].graveyard.append(
        state.new_object(_BEAR, 0, Zone.GRAVEYARD)
    )
    DealDamageToOpponentCreatureByCardsInGraveyard().resolve(
        state, 0, (("creature", own.id),),
    )
    assert own.damage == 0


def test_graveyard_describe():
    assert "graveyard" in (
        DealDamageToOpponentCreatureByCardsInGraveyard().describe()
    )


# ---------------------------------------------------------------------
# DealDamageToOpponentCreatureByLifeTotal
# ---------------------------------------------------------------------


def test_life_total_damage_equals_controller_life():
    state = _new_state()
    state.players[0].life = 7
    enemy = _put(state, _BEAR, owner_id=1)
    DealDamageToOpponentCreatureByLifeTotal().resolve(
        state, 0, (("creature", enemy.id),),
    )
    assert enemy.damage == 7


def test_life_total_nonpositive_life_clamps_to_noop():
    state = _new_state()
    state.players[0].life = -3  # arbitrary lose-life-past-zero scenario
    enemy = _put(state, _BEAR, owner_id=1)
    DealDamageToOpponentCreatureByLifeTotal().resolve(
        state, 0, (("creature", enemy.id),),
    )
    assert enemy.damage == 0


def test_life_total_empty_targets_is_noop():
    state = _new_state()
    DealDamageToOpponentCreatureByLifeTotal().resolve(state, 0, ())
    assert state.log == []


def test_life_total_illegal_target_is_noop():
    state = _new_state()
    state.players[0].life = 9
    own = _put(state, _BEAR, owner_id=0)
    DealDamageToOpponentCreatureByLifeTotal().resolve(
        state, 0, (("creature", own.id),),
    )
    assert own.damage == 0


def test_life_total_describe():
    assert "life total" in (
        DealDamageToOpponentCreatureByLifeTotal().describe()
    )


# ---------------------------------------------------------------------
# FightTargetCreatureWithTargetCreature — missing-fighter fizzle
# ---------------------------------------------------------------------


def test_fight_missing_opponent_fighter_is_silent_fizzle():
    """CR 701.12c: a missing fighter on either side = silent fizzle.
    Caster has a creature, opponent has none → no damage, no fight log."""
    state = _new_state()
    mine = _put(state, _BEAR, owner_id=0)
    FightTargetCreatureWithTargetCreature().resolve(state, 0, ())
    assert mine.damage == 0
    assert not any("fights" in line for line in state.log)


def test_fight_missing_caster_fighter_is_silent_fizzle():
    state = _new_state()
    enemy = _put(state, _BEAR, owner_id=1)
    FightTargetCreatureWithTargetCreature().resolve(state, 0, ())
    assert enemy.damage == 0
    assert not any("fights" in line for line in state.log)


def test_fight_both_present_deals_mutual_damage():
    state = _new_state()
    mine = _put(state, _BEAR, owner_id=0)   # 2/2
    enemy = _put(state, _BEAR, owner_id=1)  # 2/2
    FightTargetCreatureWithTargetCreature().resolve(state, 0, ())
    assert mine.damage == 2
    assert enemy.damage == 2
    assert any("fights" in line for line in state.log)


def test_fight_describe():
    assert "fights" in FightTargetCreatureWithTargetCreature().describe()


# ---------------------------------------------------------------------
# DealDamage unified primitive — defensive slot skips
# ---------------------------------------------------------------------


def test_deal_damage_slotref_slot_is_skipped():
    """A ``SlotRef`` back-reference isn't in the targets tuple under
    PR #3; the resolve loop defensively `continue`s past it without
    applying damage."""
    from mtg_bot.effects.targets import SlotRef

    state = _new_state()
    enemy = _put(state, _BEAR, owner_id=1)
    eff = DealDamage(amount=3, targets=(SlotRef(0),))
    eff.resolve(state, 0, (("creature", enemy.id),))
    assert enemy.damage == 0


def test_deal_damage_non_targetspec_slot_is_skipped():
    """A slot that is neither SlotRef nor TargetSpec is also skipped
    defensively (no crash, no damage)."""
    state = _new_state()
    enemy = _put(state, _BEAR, owner_id=1)
    eff = DealDamage(amount=5, targets=("not-a-spec",))
    eff.resolve(state, 0, (("creature", enemy.id),))
    assert enemy.damage == 0


def test_deal_damage_empty_targets_is_noop():
    state = _new_state()
    DealDamage(amount=4).resolve(state, 0, ())
    assert state.log == []
