"""Tests for Alpharael, Stonechosen — Ward-discard-random and
Void-gated half-life attack."""

from mtg_bot.actions import _cast_spell, resolve_top_of_stack
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import BASIC_LANDS, EOE_CREATURES, EOE_SPELLS, SYNTHETIC_CREATURES
from mtg_bot.combat import declare_attackers
from mtg_bot.effects import DefendingPlayerLosesHalfLifeRoundedUp
from mtg_bot.game import GameState, Player, Zone


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    return state


# -----------------------
# DefendingPlayerLosesHalfLifeRoundedUp effect
# -----------------------


def test_half_life_loss_rounds_up():
    state = _new_state()
    state.players[1].life = 19
    DefendingPlayerLosesHalfLifeRoundedUp().resolve(state, 0, ())
    # 19 / 2 rounded up = 10. 19 - 10 = 9.
    assert state.players[1].life == 9


def test_half_life_loss_rounds_up_even():
    state = _new_state()
    state.players[1].life = 20
    DefendingPlayerLosesHalfLifeRoundedUp().resolve(state, 0, ())
    assert state.players[1].life == 10


def test_half_life_loss_describe():
    d = DefendingPlayerLosesHalfLifeRoundedUp().describe()
    assert "half" in d and "rounded up" in d


# -----------------------
# Ward-discard-random at cast time
# -----------------------


def test_ward_discard_forces_caster_to_discard():
    state = _new_state()
    alpha = state.new_object(
        EOE_CREATURES["Alpharael, Stonechosen"], 1, Zone.BATTLEFIELD,
    )
    alpha.summoning_sick = False
    state.battlefield.append(alpha)
    # P0 has hand cards and wants to cast a removal spell targeting Alpha.
    for _ in range(4):
        m = state.new_object(BASIC_LANDS["Swamp"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(m)
    # Give P0 a few cards in hand so random discard has options.
    for _ in range(3):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.HAND)
        state.players[0].hand.append(c)
    # Cast Gravkill (exile target creature) at P1's Alpharael.
    grav = state.new_object(EOE_SPELLS["Gravkill"], 0, Zone.HAND)
    state.players[0].hand.append(grav)
    hand_before = len(state.players[0].hand)
    _cast_spell(state, 0, grav.id)
    # After casting: 1 less for the spell itself, +1 forced discard for Ward.
    assert len(state.players[0].hand) == hand_before - 2


def test_ward_discard_counters_spell_when_hand_empty():
    state = _new_state()
    alpha = state.new_object(
        EOE_CREATURES["Alpharael, Stonechosen"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(alpha)
    for _ in range(4):
        m = state.new_object(BASIC_LANDS["Swamp"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(m)
    grav = state.new_object(EOE_SPELLS["Gravkill"], 0, Zone.HAND)
    state.players[0].hand.append(grav)
    # Hand has only the spell being cast; removing it leaves empty, so
    # the Ward has no random target → spell should be countered.
    _cast_spell(state, 0, grav.id)
    # Alpharael still on battlefield — spell countered.
    assert alpha in state.battlefield


# -----------------------
# Void attack trigger
# -----------------------


def test_alpharael_attack_halves_life_when_void_active():
    state = _new_state()
    alpha = state.new_object(
        EOE_CREATURES["Alpharael, Stonechosen"], 0, Zone.BATTLEFIELD,
    )
    alpha.summoning_sick = False
    state.battlefield.append(alpha)
    # Force Void active: mark a permanent left battlefield this turn.
    state.permanent_left_battlefield_this_turn = True
    declare_attackers(state, [alpha.id])
    # P1 at 20 → loses 10 → at 10.
    assert state.players[1].life == 10


def test_alpharael_attack_does_nothing_when_void_inactive():
    state = _new_state()
    alpha = state.new_object(
        EOE_CREATURES["Alpharael, Stonechosen"], 0, Zone.BATTLEFIELD,
    )
    alpha.summoning_sick = False
    state.battlefield.append(alpha)
    # Void inactive (no permanent-left, no spell-warped).
    life_before = state.players[1].life
    declare_attackers(state, [alpha.id])
    assert state.players[1].life == life_before


def test_alpharael_printing_metadata():
    a = EOE_CREATURES["Alpharael, Stonechosen"]
    assert "Legendary" in a.supertypes
    assert a.ward_discard_random is True
    assert a.warp_cost_str == "{2}{B}"
    ab = a.triggered_abilities[0]
    assert ab.trigger == "attacks"
    assert ab.requires_void is True
