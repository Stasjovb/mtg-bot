"""Tests for Requiem Monolith's full activated ability — grant a UEOT
"dealt damage" trigger to target creature, then offer that creature's
controller a may-deal-1-damage decision that, if accepted, fires the
fresh trigger for 1 draw + 1 life loss."""

from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import BASIC_LANDS, EOE_SPELLS, SYNTHETIC_CREATURES
from mtg_bot.effects import (
    RequiemMonolithActivatedEffect,
    RequiemMonolithDealtDamageEffect,
)
from mtg_bot.game import GameState, Player, Zone


class _AcceptDamage(Agent):
    """Always opts into the optional 1-damage ping (mode 0)."""

    def choose_mode(self, state, player_id, mode_descriptions):
        return 0


class _DeclineDamage(Agent):
    """Always declines the optional 1-damage ping (mode 1)."""

    def choose_mode(self, state, player_id, mode_descriptions):
        return 1


def _new_state(p1_agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=p1_agent or RandomAgent()))
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def test_accepted_ping_grants_trigger_pings_and_fires_rider():
    """Activate → grant trigger → controller accepts → 1 damage fires
    rider → 1 card drawn, 1 life lost."""
    state = _new_state(p1_agent=_AcceptDamage())
    for _ in range(3):
        c = state.new_object(BASIC_LANDS["Plains"], 1, Zone.LIBRARY)
        state.players[1].library.append(c)
    enemy_bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    life_before = state.players[1].life
    RequiemMonolithActivatedEffect().resolve(
        state, 0, (("creature", enemy_bear.id),),
    )
    assert enemy_bear.damage == 1
    assert state.players[1].life == life_before - 1
    assert len(state.players[1].hand) == 1
    # The granted trigger is still on the creature for the rest of the turn.
    from mtg_bot.game import effective_triggered_abilities
    granted = [
        ab for ab in effective_triggered_abilities(state, enemy_bear)
        if ab not in enemy_bear.printing.triggered_abilities
    ]
    assert len(granted) == 1
    assert granted[0].trigger == "this_dealt_damage"


def test_declined_ping_grants_trigger_but_no_damage():
    """Activate → grant trigger → controller declines → no damage, no draw."""
    state = _new_state(p1_agent=_DeclineDamage())
    for _ in range(3):
        c = state.new_object(BASIC_LANDS["Plains"], 1, Zone.LIBRARY)
        state.players[1].library.append(c)
    enemy_bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    life_before = state.players[1].life
    RequiemMonolithActivatedEffect().resolve(
        state, 0, (("creature", enemy_bear.id),),
    )
    assert enemy_bear.damage == 0
    assert state.players[1].life == life_before
    assert len(state.players[1].hand) == 0
    # Trigger granted regardless of the may-decision.
    from mtg_bot.game import effective_triggered_abilities
    granted = [
        ab for ab in effective_triggered_abilities(state, enemy_bear)
        if ab not in enemy_bear.printing.triggered_abilities
    ]
    assert len(granted) == 1


def test_effect_noop_no_target():
    state = _new_state()
    RequiemMonolithActivatedEffect().resolve(state, 0, ())


def test_effect_wrong_kind_noop():
    state = _new_state()
    RequiemMonolithActivatedEffect().resolve(state, 0, (("player", 0),))


def test_effect_target_left_battlefield():
    """If the target moved off the battlefield between targeting and
    resolve, the effect fizzles cleanly."""
    state = _new_state()
    RequiemMonolithActivatedEffect().resolve(
        state, 0, (("creature", 999),),
    )


def test_dealt_damage_rider_amount_zero_noop():
    """The rider effect bails out cleanly if the damage channel is 0."""
    state = _new_state()
    state.resolving_combat_damage_amount = 0
    RequiemMonolithDealtDamageEffect().resolve(state, 0, ())


def test_dealt_damage_rider_no_source_noop():
    """The rider effect bails out cleanly if no resolving_source is set."""
    state = _new_state()
    state.resolving_combat_damage_amount = 5
    state.resolving_source = None
    RequiemMonolithDealtDamageEffect().resolve(state, 0, ())


def test_effect_describe():
    d = RequiemMonolithActivatedEffect().describe()
    assert "target creature" in d
    assert "draw" in d


def test_dealt_damage_rider_describe():
    d = RequiemMonolithDealtDamageEffect().describe()
    assert "draw" in d


def test_requiem_printing_has_sorcery_speed_activated():
    m = EOE_SPELLS["Requiem Monolith"]
    assert len(m.activated_abilities) == 1
    a = m.activated_abilities[0]
    assert a.sorcery_speed
    assert a.cost.tap_self
