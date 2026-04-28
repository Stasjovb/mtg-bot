"""Tests for Pulsar Squadron Ace's look-at-top-5-reveal-or-counter ETB."""

from mtg_bot.actions import put_into_battlefield
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.effects import LookAtTopNRevealOrCounter
from mtg_bot.game import GameState, Player, Zone

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _TakeFirstAgent(Agent):
    def choose_card_from_library(self, state, player_id, option_ids):
        return option_ids[0] if option_ids else None

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


class _DeclineAgent(Agent):
    def choose_card_from_library(self, state, player_id, option_ids):
        return None

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent or RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def test_pulsar_ace_reveals_spacecraft_into_hand():
    state = _new_state(agent=_TakeFirstAgent())
    p = state.players[0]
    # Stack the library: 1 Spacecraft in top 5, rest non-spacecraft.
    ship = state.new_object(
        _PRINTINGS["Synthesizer Labship"], 0, Zone.LIBRARY,
    )
    p.library.append(ship)
    for _ in range(4):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        p.library.append(c)
    # Put the Ace on the battlefield to serve as resolving source.
    ace = state.new_object(
        _PRINTINGS["Pulsar Squadron Ace"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(ace)
    state.resolving_source = ace
    LookAtTopNRevealOrCounter(n=5, filter_name="spacecraft").resolve(
        state, 0, (),
    )
    state.resolving_source = None
    # Ship went to hand; Ace got no counter.
    assert ship in p.hand
    assert ace.plus_one_counters == 0
    # Library is now 4 cards long (5 examined, 1 revealed, 4 back).
    assert len(p.library) == 4


def test_pulsar_ace_counter_when_no_spacecraft_available():
    """Library has no Spacecraft. Ace gets a +1/+1 counter."""
    state = _new_state(agent=_TakeFirstAgent())
    p = state.players[0]
    for _ in range(5):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        p.library.append(c)
    ace = state.new_object(
        _PRINTINGS["Pulsar Squadron Ace"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(ace)
    state.resolving_source = ace
    LookAtTopNRevealOrCounter(n=5, filter_name="spacecraft").resolve(
        state, 0, (),
    )
    state.resolving_source = None
    assert ace.plus_one_counters == 1


def test_pulsar_ace_counter_when_agent_declines():
    """Library has a Spacecraft but the agent declines → still counter."""
    state = _new_state(agent=_DeclineAgent())
    p = state.players[0]
    ship = state.new_object(
        _PRINTINGS["Synthesizer Labship"], 0, Zone.LIBRARY,
    )
    p.library.append(ship)
    for _ in range(4):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        p.library.append(c)
    ace = state.new_object(
        _PRINTINGS["Pulsar Squadron Ace"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(ace)
    state.resolving_source = ace
    LookAtTopNRevealOrCounter(n=5, filter_name="spacecraft").resolve(
        state, 0, (),
    )
    state.resolving_source = None
    assert ship in p.library
    assert ace.plus_one_counters == 1


def test_pulsar_ace_small_library():
    """Fewer than n cards — examine what's there, work normally."""
    state = _new_state(agent=_TakeFirstAgent())
    p = state.players[0]
    # Only 2 cards: a Spacecraft and a land.
    ship = state.new_object(
        _PRINTINGS["Synthesizer Labship"], 0, Zone.LIBRARY,
    )
    p.library.append(ship)
    land = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
    p.library.append(land)
    ace = state.new_object(
        _PRINTINGS["Pulsar Squadron Ace"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(ace)
    state.resolving_source = ace
    LookAtTopNRevealOrCounter(n=5, filter_name="spacecraft").resolve(
        state, 0, (),
    )
    state.resolving_source = None
    assert ship in p.hand
    assert len(p.library) == 1


def test_pulsar_ace_filter_creature():
    """The effect accepts filter_name='creature' too."""
    state = _new_state(agent=_TakeFirstAgent())
    p = state.players[0]
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.LIBRARY,
    )
    p.library.append(bear)
    for _ in range(4):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        p.library.append(c)
    LookAtTopNRevealOrCounter(n=5, filter_name="creature").resolve(
        state, 0, (),
    )
    assert bear in p.hand


def test_pulsar_ace_filter_artifact():
    state = _new_state(agent=_TakeFirstAgent())
    p = state.players[0]
    artifact = state.new_object(
        _PRINTINGS["Memorial Vault"], 0, Zone.LIBRARY,
    )
    p.library.append(artifact)
    for _ in range(4):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        p.library.append(c)
    LookAtTopNRevealOrCounter(n=5, filter_name="artifact").resolve(
        state, 0, (),
    )
    assert artifact in p.hand


def test_pulsar_ace_unknown_filter_treats_as_no_match():
    state = _new_state(agent=_TakeFirstAgent())
    p = state.players[0]
    for _ in range(5):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        p.library.append(c)
    ace = state.new_object(
        _PRINTINGS["Pulsar Squadron Ace"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(ace)
    state.resolving_source = ace
    LookAtTopNRevealOrCounter(n=5, filter_name="nonsense").resolve(
        state, 0, (),
    )
    state.resolving_source = None
    # Unknown filter matches nothing → +1/+1 counter path.
    assert ace.plus_one_counters == 1


def test_pulsar_ace_describe():
    text = LookAtTopNRevealOrCounter(n=5, filter_name="spacecraft").describe()
    assert "top 5" in text
    assert "spacecraft" in text
