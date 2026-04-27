"""Tests for Mutinous Massacre: odd/even parity wrath + steal-all UEOT."""

from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import (
    BASIC_LANDS,
    EOE_SPELLS,
    SYNTHETIC_CREATURES,
)
from mtg_bot.effects import MutinousMassacreEffect
from mtg_bot.game import GameState, Player, Zone, effective_keywords
from mtg_bot.turn import run_cleanup_step


class _ChoosesOdd(Agent):
    def choose_mode(self, state, player_id, mode_descriptions):
        return 0  # "odd"


class _ChoosesEven(Agent):
    def choose_mode(self, state, player_id, mode_descriptions):
        return 1  # "even"


def _new_state(agent_mode):
    state = GameState()
    state.players.append(Player(id=0, agent=agent_mode))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def test_mutinous_massacre_odd_destroys_odd_mv_creatures():
    """Choosing odd destroys only odd-MV creatures. Even-MV survives
    and is stolen."""
    state = _new_state(_ChoosesOdd())
    # Wild Bear is {1}{G} = MV 2 (even). Spider Sentinel is {2}{G} = 3 (odd).
    # Forest Giant is {2}{G} = 3 (odd).
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    spider = state.new_object(
        SYNTHETIC_CREATURES["Spider Sentinel"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(spider)
    MutinousMassacreEffect().resolve(state, 0, ())
    # Spider (odd MV 3) destroyed; Bear (even MV 2) survives and gets stolen.
    assert spider not in state.battlefield
    assert bear in state.battlefield
    assert bear.controller_id == 0
    # Layer-2 control swap captures the original controller as the
    # baseline (used by ``move_off_battlefield`` and the cleanup
    # refresh to revert).
    assert bear.controller_id_before_any_aura_swap == 1
    assert "haste" in effective_keywords(state, bear)


def test_mutinous_massacre_even_destroys_even_mv_creatures():
    state = _new_state(_ChoosesEven())
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )  # MV 2 (even)
    state.battlefield.append(bear)
    spider = state.new_object(
        SYNTHETIC_CREATURES["Spider Sentinel"], 1, Zone.BATTLEFIELD,
    )  # MV 3 (odd)
    state.battlefield.append(spider)
    MutinousMassacreEffect().resolve(state, 0, ())
    assert bear not in state.battlefield
    assert spider in state.battlefield
    assert spider.controller_id == 0


def test_mutinous_massacre_reverts_on_cleanup():
    state = _new_state(_ChoosesOdd())
    state.active_player_idx = 0
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    MutinousMassacreEffect().resolve(state, 0, ())
    assert bear.controller_id == 0
    run_cleanup_step(state)
    assert bear.controller_id == 1
    assert bear.controller_id_before_any_aura_swap is None
    assert "haste" not in effective_keywords(state, bear)


def test_mutinous_massacre_untaps_stolen_creatures():
    state = _new_state(_ChoosesOdd())
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    bear.tapped = True
    state.battlefield.append(bear)
    MutinousMassacreEffect().resolve(state, 0, ())
    assert not bear.tapped


def test_mutinous_massacre_own_creatures_untap_and_haste():
    """Your own creatures aren't destroyed (they survive if parity
    mismatches) and still get untap + haste UEOT."""
    state = _new_state(_ChoosesOdd())
    my_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )  # MV 2 (even) — survives odd-parity wrath.
    my_bear.tapped = True
    state.battlefield.append(my_bear)
    MutinousMassacreEffect().resolve(state, 0, ())
    assert my_bear in state.battlefield
    assert not my_bear.tapped
    assert "haste" in effective_keywords(state, my_bear)
    # We already control it → no control-grant entry / baseline.
    assert my_bear.controller_id_before_any_aura_swap is None


def test_mutinous_massacre_agent_none_defaults_to_odd():
    """With no agent, choose_mode path is skipped; default pick=0 (odd)."""
    state = GameState()
    state.players.append(Player(id=0, agent=None))
    state.players.append(Player(id=1, agent=RandomAgent()))
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )  # MV 2 — even.
    state.battlefield.append(bear)
    spider = state.new_object(
        SYNTHETIC_CREATURES["Spider Sentinel"], 1, Zone.BATTLEFIELD,
    )  # MV 3 — odd.
    state.battlefield.append(spider)
    MutinousMassacreEffect().resolve(state, 0, ())
    # Default pick=0 (odd) destroys spider, bear survives.
    assert spider not in state.battlefield
    assert bear in state.battlefield


def test_mutinous_massacre_agent_pick_clamped():
    """Agent returns out-of-range value — clamped into [0,1]."""
    class _Weird(Agent):
        def choose_mode(self, state, player_id, mode_descriptions):
            return 99

    state = _new_state(_Weird())
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )  # MV 2 (even)
    state.battlefield.append(bear)
    MutinousMassacreEffect().resolve(state, 0, ())
    # Clamped to 1 (even) → bear destroyed.
    assert bear not in state.battlefield


def test_mutinous_massacre_describe():
    text = MutinousMassacreEffect().describe()
    assert "odd or even" in text
    assert "gain control" in text
    assert "haste" in text


def test_mutinous_massacre_card_printing():
    m = EOE_SPELLS["Mutinous Massacre"]
    assert isinstance(m.spell_effect, MutinousMassacreEffect)


def test_mutinous_massacre_zero_mv_is_even():
    """Zero mana value counts as even (as noted in the oracle text)."""
    state = _new_state(_ChoosesEven())
    from mtg_bot.cards import TOKEN_PRINTINGS
    # Robot token has MV 0 (tokens); treat as even.
    robot = state.new_object(
        TOKEN_PRINTINGS["Robot"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(robot)
    MutinousMassacreEffect().resolve(state, 0, ())
    # Even chosen → MV 0 token destroyed.
    assert robot not in state.battlefield
