"""Engine-resolve tests for ``AddOneManaOfChosenPermanentColor``.

The parser maps Meteor Crater's "{T}: Choose a color of a permanent you
control. Add one mana of that color." onto this generic class but no
test exercises the resolve path directly. These tests cover:

- Happy path with a single colored permanent (B in cost → only B offered).
- Multiple colored permanents → union exposed via choose_mana_color.
- Misbehaving agent returns out-of-set color → fallback to first sorted.
- No-agent code path → first sorted option mints.
- No colored permanents → defensive ``"C"`` colorless coin.
- Lands and colorless permanents contribute no colors.
- Opponent's permanents do NOT contribute to the controller's options.
- describe() text mentions the permanent-color rule."""

from __future__ import annotations

from mtg_bot.agents import Agent
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.cards.base import make_creature
from mtg_bot.effects import AddOneManaOfChosenPermanentColor
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step


class _RecordingAgent(Agent):
    """Captures ``options`` and returns a pre-programmed pick."""

    def __init__(self, pick: str | None = None):
        self.pick = pick
        self.last_options: list[str] | None = None

    def choose_mana_color(self, state, player_id, options):
        self.last_options = list(options)
        if self.pick is not None and self.pick in options:
            return self.pick
        return options[0]


class _MisbehavingAgent(Agent):
    """Always returns 'W' regardless of legality."""

    def choose_mana_color(self, state, player_id, options):
        return "W"


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent))
    state.players.append(Player(id=1, agent=None))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def test_resolve_single_black_creature_offers_only_black():
    """Black creature in play means the only legal option is B."""
    agent = _RecordingAgent()
    state = _new_state(agent=agent)
    _put(state, make_creature("Vampire", "{1}{B}", 2, 2))
    AddOneManaOfChosenPermanentColor().resolve(state, 0, ())
    assert agent.last_options == ["B"]
    assert len(state.players[0].mana_pool) == 1
    assert state.players[0].mana_pool[0].color == "B"


def test_resolve_multi_color_permanents_union_into_options():
    """Two creatures of different colors → options is the union."""
    agent = _RecordingAgent(pick="R")
    state = _new_state(agent=agent)
    _put(state, make_creature("Goblin", "{R}", 1, 1))
    _put(state, make_creature("Zealot", "{W}", 1, 2))
    AddOneManaOfChosenPermanentColor().resolve(state, 0, ())
    assert set(agent.last_options or []) == {"W", "R"}
    assert state.players[0].mana_pool[0].color == "R"


def test_resolve_misbehaving_agent_falls_back_to_first_sorted():
    """If the agent returns a color not in the offered set, the resolve
    quietly clamps to the first sorted option."""
    state = _new_state(agent=_MisbehavingAgent())
    # Sorted options will be ["B", "G"]; agent returns "W" (illegal).
    _put(state, make_creature("Vampire", "{B}", 1, 1))
    _put(state, make_creature("Beast", "{G}", 2, 2))
    AddOneManaOfChosenPermanentColor().resolve(state, 0, ())
    # Fallback picks "B" (first sorted).
    assert state.players[0].mana_pool[0].color == "B"


def test_resolve_with_no_agent_picks_first_sorted_option():
    """When the player has no agent attached, resolve takes the first
    sorted color without consulting an agent."""
    state = _new_state(agent=None)
    _put(state, make_creature("Bear", "{G}", 2, 2))
    _put(state, make_creature("Drake", "{U}", 2, 2))
    AddOneManaOfChosenPermanentColor().resolve(state, 0, ())
    # Sorted: ["G", "U"] → first is "G".
    assert state.players[0].mana_pool[0].color == "G"


def test_resolve_no_colored_permanents_falls_back_to_colorless():
    """Defensive: with only lands and colorless permanents, options is
    empty and the effect mints one colorless ({C}) coin."""

    class _ExplodingAgent(Agent):
        def choose_mana_color(self, state, player_id, options):
            raise AssertionError("agent must not be consulted")

    state = _new_state(agent=_ExplodingAgent())
    _put(state, BASIC_LANDS["Forest"])  # land: no colored cost
    _put(state, make_creature("Brass Brute", "{2}", 2, 2))  # colorless
    AddOneManaOfChosenPermanentColor().resolve(state, 0, ())
    pool = state.players[0].mana_pool
    assert len(pool) == 1
    assert pool[0].color == "C"


def test_resolve_opponent_permanents_do_not_contribute():
    """An opponent's colored permanent must NOT add its color to the
    controller's option set."""
    agent = _RecordingAgent()
    state = _new_state(agent=agent)
    # Opponent controls a red creature; we control nothing colored.
    opp_creature = state.new_object(
        make_creature("Goblin", "{R}", 1, 1), 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(opp_creature)
    AddOneManaOfChosenPermanentColor().resolve(state, 0, ())
    # No colored permanent for P0 → C fallback.
    assert state.players[0].mana_pool[0].color == "C"


def test_describe_text_mentions_permanent_color():
    desc = AddOneManaOfChosenPermanentColor().describe()
    assert "color" in desc
    assert "permanent you control" in desc
