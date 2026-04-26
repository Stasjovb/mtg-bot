"""Tests for Stellar Sights batch 3: Reflecting Pool, Meteor Crater,
Power Depot — any-color mana variants."""

from mtg_bot.actions import ActivateAbility, apply_action
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import BASIC_LANDS, STELLAR_SIGHTS_LANDS
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step


class _RecordingColorAgent(Agent):
    """Captures the ``options`` list passed into ``choose_mana_color``
    and returns a pre-programmed pick. Lets the regression tests
    assert both the offered set AND the resulting coin."""

    def __init__(self, pick: str | None = None):
        self.pick = pick
        self.last_options: list[str] | None = None

    def choose_mana_color(self, state, player_id, options):
        self.last_options = list(options)
        if self.pick is not None and self.pick in options:
            return self.pick
        return options[0]


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent or RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def test_reflecting_pool_only_forest_offers_only_green():
    """With only a Forest in play (plus the Pool itself, which has
    empty produces), the Pool's choice set must be {G} only."""
    agent = _RecordingColorAgent()
    state = _new_state(agent=agent)
    _put(state, BASIC_LANDS["Forest"])
    rp = _put(state, STELLAR_SIGHTS_LANDS["Reflecting Pool"])
    apply_action(state, 0, ActivateAbility(source_id=rp.id, ability_index=0))
    assert agent.last_options == ["G"]
    assert len(state.players[0].mana_pool) == 1
    assert state.players[0].mana_pool[0].color == "G"


def test_reflecting_pool_island_and_swamp_offers_u_and_b():
    """Island + Swamp in play: options must be exactly {U, B}, never
    W/R/G. Agent picks U → coin is blue."""
    agent = _RecordingColorAgent(pick="U")
    state = _new_state(agent=agent)
    _put(state, BASIC_LANDS["Island"])
    _put(state, BASIC_LANDS["Swamp"])
    rp = _put(state, STELLAR_SIGHTS_LANDS["Reflecting Pool"])
    apply_action(state, 0, ActivateAbility(source_id=rp.id, ability_index=0))
    assert set(agent.last_options or []) == {"U", "B"}
    assert "W" not in (agent.last_options or [])
    assert "R" not in (agent.last_options or [])
    assert "G" not in (agent.last_options or [])
    assert state.players[0].mana_pool[0].color == "U"


def test_reflecting_pool_dual_color_land_unions_into_options():
    """A single dual-color land (Hissing Quagmire produces {B, G})
    must contribute both colors to the union."""
    agent = _RecordingColorAgent(pick="B")
    state = _new_state(agent=agent)
    _put(state, STELLAR_SIGHTS_LANDS["Hissing Quagmire"])
    rp = _put(state, STELLAR_SIGHTS_LANDS["Reflecting Pool"])
    apply_action(state, 0, ActivateAbility(source_id=rp.id, ability_index=0))
    assert set(agent.last_options or []) == {"B", "G"}
    assert state.players[0].mana_pool[0].color == "B"


def test_reflecting_pool_misbehaving_agent_falls_back_to_first_sorted():
    """Defensive path: if the agent returns a color not in the legal
    set, the effect must fall back to the first sorted legal option
    rather than mint an illegal coin."""
    from mtg_bot.effects import AddOneManaFromControlledLandsProductions

    class _MisbehavingAgent(Agent):
        def choose_mana_color(self, state, player_id, options):
            return "W"  # always W, regardless of options

    state = _new_state(agent=_MisbehavingAgent())
    _put(state, BASIC_LANDS["Forest"])
    _put(state, BASIC_LANDS["Island"])
    AddOneManaFromControlledLandsProductions().resolve(state, 0, ())
    # Sorted legal options were ["G", "U"] — W not in set → fallback
    # picks "G" (first sorted).
    assert state.players[0].mana_pool[0].color == "G"


def test_reflecting_pool_no_lands_falls_back_to_colorless():
    """Defensive: with no lands in play at all (Pool not staged
    either — bypassing the activation flow), resolving the effect
    directly mints a single {C} coin and never calls the agent."""
    from mtg_bot.effects import (
        AddOneManaFromControlledLandsProductions,
    )

    class _ExplodingAgent(Agent):
        def choose_mana_color(self, state, player_id, options):
            raise AssertionError("agent must not be consulted")

    state = _new_state(agent=_ExplodingAgent())
    AddOneManaFromControlledLandsProductions().resolve(state, 0, ())
    pool = state.players[0].mana_pool
    assert len(pool) == 1
    assert pool[0].color == "C"


def test_reflecting_pool_describe_mentions_lands_you_control():
    from mtg_bot.effects import AddOneManaFromControlledLandsProductions

    desc = AddOneManaFromControlledLandsProductions().describe()
    assert "land you control" in desc


def test_random_agent_choose_mana_color_returns_a_legal_option():
    """RandomAgent.choose_mana_color must return one of the offered
    options (sanity check that the Reflecting Pool plumbing works
    when the random baseline is the controller)."""
    import random
    agent = RandomAgent(rng=random.Random(0))
    state = _new_state()
    pick = agent.choose_mana_color(state, 0, ["U", "B", "G"])
    assert pick in {"U", "B", "G"}


def test_recording_agent_falls_back_to_first_when_pick_unavailable():
    """The test helper itself: if the requested ``pick`` isn't in the
    options list, it must fall back to the first option."""
    agent = _RecordingColorAgent(pick="W")
    state = _new_state()
    pick = agent.choose_mana_color(state, 0, ["U", "B"])
    assert pick == "U"
    assert agent.last_options == ["U", "B"]


def test_meteor_crater_taps_for_any_color():
    state = _new_state()
    mc = _put(state, STELLAR_SIGHTS_LANDS["Meteor Crater"])
    apply_action(state, 0, ActivateAbility(source_id=mc.id, ability_index=0))
    assert state.players[0].mana_pool[0].color == "any"


def test_power_depot_mana_is_artifact_restricted():
    state = _new_state()
    pd = _put(state, STELLAR_SIGHTS_LANDS["Power Depot"])
    apply_action(state, 0, ActivateAbility(source_id=pd.id, ability_index=0))
    coin = state.players[0].mana_pool[0]
    assert coin.color == "any"
    assert coin.spend_restriction == "artifact_spell"


def test_power_depot_is_artifact_land_and_enters_tapped():
    p = STELLAR_SIGHTS_LANDS["Power Depot"]
    assert p.is_artifact and p.is_land
    assert p.enters_tapped


def test_three_more_restored_no_longer_stand_ins():
    import pathlib
    src = pathlib.Path("src/mtg_bot/cards/stellar_sights.py").read_text(
        encoding="utf-8"
    )
    for name in ("Reflecting Pool", "Meteor Crater"):
        assert f'"{name}": make_colorless_land(' not in src
