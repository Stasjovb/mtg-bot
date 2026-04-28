"""Tests for the beginning_of_upkeep trigger type and
ConditionalIfYouControlAtLeast combinator.

Also exercises Inventors' Fair's restored upkeep gain-life ability
(gated on 3+ artifacts).
"""

from mtg_bot.actions import drain_stack
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES, TOKEN_PRINTINGS
from mtg_bot.cards.base import make_artifact, make_creature
from mtg_bot.effects import (
    ConditionalIfYouControlAtLeast, GainLife, TriggeredAbility,
)
from mtg_bot.effects.predicates import YOU, Controlled, Event
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step, run_beginning_of_upkeep_triggers

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.UPKEEP
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


# -----------------------
# run_beginning_of_upkeep_triggers
# -----------------------


def test_beginning_of_upkeep_fires_for_active_player_only():
    """A permanent the non-active player controls does NOT fire its
    upkeep trigger during the active player's upkeep."""
    printing = make_artifact(
        "Test Upkeep Art", "{0}",
        triggered_abilities=(
            TriggeredAbility(
                event=Event.BEGINNING_OF_UPKEEP, predicate=Controlled(YOU),
                effect=GainLife(amount=5),
            ),
        ),
    )
    state = _new_state()
    _put(state, printing, owner_id=1)  # opponent's artifact
    starting_life = list(p.life for p in state.players)
    run_beginning_of_upkeep_triggers(state)
    # Neither player gained life — opponent's trigger didn't fire.
    assert [p.life for p in state.players] == starting_life


def test_beginning_of_upkeep_fires_for_active_player_permanents():
    printing = make_artifact(
        "Test Upkeep Art", "{0}",
        triggered_abilities=(
            TriggeredAbility(
                event=Event.BEGINNING_OF_UPKEEP, predicate=Controlled(YOU),
                effect=GainLife(amount=5),
            ),
        ),
    )
    state = _new_state()
    _put(state, printing, owner_id=0)
    run_beginning_of_upkeep_triggers(state)
    drain_stack(state)
    assert state.players[0].life == 25


# -----------------------
# ConditionalIfYouControlAtLeast
# -----------------------


def test_conditional_controls_n_artifacts_meets_threshold():
    state = _new_state()
    for _ in range(3):
        _put(state, make_artifact("Scrap", "{0}"))
    eff = ConditionalIfYouControlAtLeast(
        threshold=3, predicate="artifact", inner=GainLife(amount=7),
    )
    eff.resolve(state, 0, ())
    assert state.players[0].life == 27


def test_conditional_controls_n_artifacts_misses_threshold():
    state = _new_state()
    for _ in range(2):
        _put(state, make_artifact("Scrap", "{0}"))
    eff = ConditionalIfYouControlAtLeast(
        threshold=3, predicate="artifact", inner=GainLife(amount=7),
    )
    eff.resolve(state, 0, ())
    assert state.players[0].life == 20  # unchanged


def test_conditional_controls_n_creatures_counts_manlands_as_creatures():
    """When a manland is animated (temp_is_creature=True), it should
    count as a creature for the conditional."""
    state = _new_state()
    bear = _put(state, make_creature("Test Bear", "{1}{G}", 2, 2))
    # Land animated UEOT.
    land = _put(state, BASIC_LANDS["Forest"])
    land.temp_is_creature = True
    eff = ConditionalIfYouControlAtLeast(
        threshold=2, predicate="creature", inner=GainLife(amount=4),
    )
    eff.resolve(state, 0, ())
    assert state.players[0].life == 24


def test_conditional_controls_n_lands():
    state = _new_state()
    for _ in range(3):
        _put(state, BASIC_LANDS["Mountain"])
    eff = ConditionalIfYouControlAtLeast(
        threshold=3, predicate="land", inner=GainLife(amount=1),
    )
    eff.resolve(state, 0, ())
    assert state.players[0].life == 21


def test_conditional_unknown_predicate_returns_zero():
    """Defensive: an unknown predicate counts 0 and skips the effect."""
    state = _new_state()
    eff = ConditionalIfYouControlAtLeast(
        threshold=1, predicate="zzz", inner=GainLife(amount=10),
    )
    eff.resolve(state, 0, ())
    assert state.players[0].life == 20


def test_conditional_describe_mentions_threshold_and_predicate():
    eff = ConditionalIfYouControlAtLeast(
        threshold=3, predicate="artifact", inner=GainLife(amount=1),
    )
    d = eff.describe()
    assert "3" in d
    assert "artifact" in d


# -----------------------
# Inventors' Fair — end-to-end upkeep gain-life
# -----------------------


def test_inventors_fair_gains_life_with_three_artifacts():
    state = _new_state()
    _put(state, _PRINTINGS["Inventors' Fair"])
    # Add two more artifacts; Fair itself isn't an artifact, so we need
    # three more to hit the 3-artifact threshold.
    for _ in range(3):
        _put(state, make_artifact("Scrap", "{0}"))
    run_beginning_of_upkeep_triggers(state)
    drain_stack(state)
    assert state.players[0].life == 21


def test_inventors_fair_no_gain_below_artifact_threshold():
    state = _new_state()
    _put(state, _PRINTINGS["Inventors' Fair"])
    for _ in range(2):
        _put(state, make_artifact("Scrap", "{0}"))
    run_beginning_of_upkeep_triggers(state)
    assert state.players[0].life == 20


# -----------------------
# Thrumming Hivepool — regression under the new trigger wiring
# -----------------------


def test_hivepool_upkeep_trigger_fires_on_upkeep_step():
    state = _new_state()
    _put(state, _PRINTINGS["Thrumming Hivepool"])
    run_beginning_of_upkeep_triggers(state)
    drain_stack(state)
    slivers = [o for o in state.battlefield if o.printing.name == "Sliver"]
    assert len(slivers) == 2


# -----------------------
# Describe for TriggeredAbility
# -----------------------


def test_beginning_of_upkeep_targeted_trigger_fires_and_fizzles():
    """Exercise the targeted-effect branch of
    run_beginning_of_upkeep_triggers: a card with a beginning_of_upkeep
    trigger whose effect targets a creature. Fizzles if no legal target
    exists, resolves if there is one."""
    from mtg_bot.effects import PumpTargetCreatureUntilEOT
    from mtg_bot.agents import Agent

    class _PickFirstAgent(Agent):
        def choose_target(self, state, player_id, legal_targets):
            return legal_targets[0] if legal_targets else None

    printing = make_artifact(
        "Test Pumper", "{0}",
        triggered_abilities=(
            TriggeredAbility(
                event=Event.BEGINNING_OF_UPKEEP, predicate=Controlled(YOU),
                effect=PumpTargetCreatureUntilEOT(
                    power_bonus=1, toughness_bonus=1,
                ),
            ),
        ),
    )
    # Fizzle: no creatures on the battlefield.
    state = _new_state()
    state.players[0].agent = _PickFirstAgent()
    _put(state, printing, owner_id=0)
    run_beginning_of_upkeep_triggers(state)
    drain_stack(state)
    # Fizzle log entry exists.
    assert any(
        "fizzles" in line for line in state.log
    )

    # Happy path: one creature, trigger pumps it.
    state2 = _new_state()
    state2.players[0].agent = _PickFirstAgent()
    _put(state2, printing, owner_id=0)
    bear = _put(state2, make_creature("Test Bear", "{1}{G}", 2, 2))
    run_beginning_of_upkeep_triggers(state2)
    drain_stack(state2)
    assert bear.temp_power_bonus == 1


def test_triggered_ability_describe_covers_beginning_of_upkeep():
    ab = TriggeredAbility(
        trigger="beginning_of_upkeep", effect=GainLife(amount=1),
    )
    assert "beginning of your upkeep" in ab.describe().lower()
