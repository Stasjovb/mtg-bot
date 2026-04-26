"""Tests for Sledge-Class Seedship's attacks trigger."""

from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import (
    BASIC_LANDS,
    EOE_CREATURES,
    EOE_SPELLS,
    SYNTHETIC_CREATURES,
)
from mtg_bot.actions import drain_stack
from mtg_bot.combat import declare_attackers
from mtg_bot.effects import OptionalPutCreatureFromHandOntoBattlefield
from mtg_bot.game import GameState, Player, Zone


class _TakeFirstAgent(Agent):
    def choose_card_from_library(self, state, player_id, option_ids):
        return option_ids[0] if option_ids else None


class _DeclineAgent(Agent):
    def choose_card_from_library(self, state, player_id, option_ids):
        return None


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent or _TakeFirstAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def test_optional_put_creature_picks_from_hand():
    state = _new_state(_TakeFirstAgent())
    p = state.players[0]
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.HAND,
    )
    p.hand.append(bear)
    OptionalPutCreatureFromHandOntoBattlefield().resolve(state, 0, ())
    assert bear in state.battlefield
    assert bear not in p.hand


def test_optional_put_creature_agent_decline_noop():
    state = _new_state(_DeclineAgent())
    p = state.players[0]
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.HAND,
    )
    p.hand.append(bear)
    OptionalPutCreatureFromHandOntoBattlefield().resolve(state, 0, ())
    assert bear in p.hand
    assert bear not in state.battlefield


def test_optional_put_creature_empty_hand_noop():
    state = _new_state()
    OptionalPutCreatureFromHandOntoBattlefield().resolve(state, 0, ())


def test_optional_put_creature_skips_non_creatures_in_hand():
    state = _new_state(_TakeFirstAgent())
    p = state.players[0]
    non_creature = state.new_object(BASIC_LANDS["Forest"], 0, Zone.HAND)
    p.hand.append(non_creature)
    OptionalPutCreatureFromHandOntoBattlefield().resolve(state, 0, ())
    # Lands in hand aren't creature cards — nothing put onto battlefield.
    assert non_creature in p.hand


def test_optional_put_creature_agent_picks_valid_id():
    state = _new_state(_TakeFirstAgent())
    p = state.players[0]
    # Two creatures + a land.
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.HAND,
    )
    p.hand.append(bear)
    spider = state.new_object(
        SYNTHETIC_CREATURES["Spider Sentinel"], 0, Zone.HAND,
    )
    p.hand.append(spider)
    forest = state.new_object(BASIC_LANDS["Forest"], 0, Zone.HAND)
    p.hand.append(forest)
    OptionalPutCreatureFromHandOntoBattlefield().resolve(state, 0, ())
    # _TakeFirstAgent picks the first option — which is bear (creature
    # options are filtered in order of appearance).
    assert bear in state.battlefield
    assert spider in p.hand


def test_optional_put_creature_describe():
    text = OptionalPutCreatureFromHandOntoBattlefield().describe()
    assert "creature card" in text
    assert "hand" in text


def test_sledge_class_attack_trigger_fires_when_attacking():
    """End-to-end: Sledge attacks → attempts to put a creature from hand."""
    state = _new_state(_TakeFirstAgent())
    p = state.players[0]
    sledge = state.new_object(
        EOE_CREATURES["Sledge-Class Seedship"], 0, Zone.BATTLEFIELD,
    )
    sledge.charge_counters = 7  # Stationed → creature
    sledge.summoning_sick = False
    state.battlefield.append(sledge)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.HAND,
    )
    p.hand.append(bear)
    declare_attackers(state, [sledge.id])
    drain_stack(state)
    # Attack trigger put the bear into play.
    assert bear in state.battlefield


def test_sledge_class_printing_has_attacks_trigger():
    s = EOE_CREATURES["Sledge-Class Seedship"]
    triggers = [ab for ab in s.triggered_abilities if ab.trigger == "attacks"]
    assert len(triggers) == 1
