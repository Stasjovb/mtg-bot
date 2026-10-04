"""The monarch, the initiative + Undercity, and goad
(``mtg_bot.designations``)."""

from __future__ import annotations

import pytest

from mtg_bot import apply
from mtg_bot.actions import DeclareAttackers
from mtg_bot.agents import Agent
from mtg_bot.cards import BASIC_LANDS, make_creature
from mtg_bot.cards.parser.effects import _parse_effect
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.cards.parser.triggers import _parse_intervening_if_phrase
from mtg_bot.designations import (
    UNDERCITY,
    become_monarch,
    clear_goad_for,
    forced_attackers,
    goad,
    initiative_id,
    monarch_id,
    on_beginning_of_end_step,
    on_beginning_of_upkeep,
    on_combat_damage_to_players,
    take_initiative,
    venture_into_undercity,
)
from mtg_bot.effects.generic.keyword_actions import BecomeMonarch, TakeInitiative
from mtg_bot.effects.state_predicates import CompletedADungeon, HasInitiative, IsMonarch
from mtg_bot.game import GameState, Player, Zone, effective_keywords
from mtg_bot.turn import (
    Step,
    run_beginning_of_end_step_triggers,
    run_beginning_of_upkeep_triggers,
    run_untap_step,
)

from tests._rules_helpers import _simulate_combat_step


class _Agent(Agent):
    def __init__(self, mode=0):
        self.mode = mode

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_mode(self, state, player_id, mode_descriptions):
        return self.mode

    def choose_card_from_library(self, state, player_id, option_ids):
        return option_ids[0] if option_ids else None

    def choose_yes_no(self, state, player_id, prompt):
        return True


def _state(mode=0) -> GameState:
    state = GameState()
    state.players.append(Player(id=0, agent=_Agent(mode)))
    state.players.append(Player(id=1, agent=_Agent(mode)))
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner, zone=Zone.BATTLEFIELD):
    obj = state.new_object(printing, owner, zone)
    obj.summoning_sick = False
    {
        Zone.HAND: state.players[owner].hand,
        Zone.LIBRARY: state.players[owner].library,
        Zone.BATTLEFIELD: state.battlefield,
    }[zone].append(obj)
    return obj


def _library(state, owner, n, printing=None):
    for _ in range(n):
        _put(state, printing or BASIC_LANDS["Plains"], owner, Zone.LIBRARY)


# ---------------------------------------------------------------- monarch


def test_monarch_draws_at_own_end_step_only():
    state = _state()
    _library(state, 0, 3)
    become_monarch(state, 0)
    assert monarch_id(state) == 0
    state.active_player_idx = 1
    run_beginning_of_end_step_triggers(state)
    assert len(state.players[0].hand) == 0
    state.active_player_idx = 0
    run_beginning_of_end_step_triggers(state)
    assert len(state.players[0].hand) == 1


def test_combat_damage_steals_the_monarch():
    state = _state()
    become_monarch(state, 1)
    attacker = _put(state, make_creature("Thief", "{R}", 2, 2), 0)
    _simulate_combat_step(state, [attacker.id])
    assert state.players[0].is_monarch and not state.players[1].is_monarch


def test_combat_damage_hook_ignores_zero_missing_and_self_damage():
    state = _state()
    become_monarch(state, 1)
    mine = _put(state, make_creature("Mine", "{R}", 2, 2), 1)
    on_combat_damage_to_players(state, [(mine.id, 1, 2), (999, 1, 2), (mine.id, 1, 0)])
    assert monarch_id(state) == 1


# ---------------------------------------------------------------- initiative


def test_take_initiative_ventures_into_secret_entrance():
    state = _state()
    forest = _put(state, BASIC_LANDS["Forest"], 0, Zone.LIBRARY)
    take_initiative(state, 0)
    assert initiative_id(state) == 0
    assert state.players[0].dungeon_room == "Secret Entrance"
    assert forest in state.players[0].hand


def test_upkeep_ventures_for_initiative_holder():
    state = _state()
    _library(state, 0, 5)
    take_initiative(state, 0)
    state.active_player_idx = 0
    bear = _put(state, make_creature("Bear", "{G}", 2, 2), 0)
    run_beginning_of_upkeep_triggers(state)
    # Exit 0 from Secret Entrance = Forge: two +1/+1 counters.
    assert state.players[0].dungeon_room == "Forge"
    assert bear.plus_one_counters == 2
    state.active_player_idx = 1
    on_beginning_of_upkeep(state)
    assert state.players[0].dungeon_room == "Forge"


@pytest.mark.parametrize(
    "mode,path",
    [
        (0, ["Secret Entrance", "Forge", "Trap!", "Archives", "Throne of the Dead Three"]),
        (1, ["Secret Entrance", "Lost Well", "Stash", "Catacombs", "Throne of the Dead Three"]),
    ],
)
def test_full_undercity_paths_complete_the_dungeon(mode, path):
    state = _state(mode)
    reanimated = make_creature("Reanimated", "{3}", 3, 3)
    _library(state, 0, 12, reanimated)
    _put(state, make_creature("Bear", "{G}", 2, 2), 0)
    rooms = []
    for _ in range(len(path)):
        venture_into_undercity(state, 0)
        rooms.append(state.players[0].dungeon_room)
    assert rooms[:-1] == path[:-1] and rooms[-1] is None
    assert state.players[0].dungeons_completed == 1
    creature = next(o for o in state.battlefield if o.printing.name == "Reanimated")
    assert creature.plus_one_counters == 3
    assert "hexproof" in effective_keywords(state, creature)
    if mode == 0:
        assert state.players[1].life == 15  # Trap!
    else:
        names = {o.printing.name for o in state.battlefield}
        assert {"Treasure", "Skeleton"} <= names
    # The next venture starts a new dungeon.
    venture_into_undercity(state, 0)
    assert state.players[0].dungeon_room == "Secret Entrance"


def test_arena_goads_and_goad_forces_attack_until_goaders_turn():
    state = _state(mode=1)  # Forge -> Arena
    state.players[0].dungeon_room = "Forge"
    theirs = _put(state, make_creature("Theirs", "{G}", 2, 2), 1)
    venture_into_undercity(state, 0)
    assert state.players[0].dungeon_room == "Arena"
    assert theirs.goaded_by == 0
    state.active_player_idx = 1
    assert forced_attackers(state, 1) == [theirs.id]
    state.step = Step.DECLARE_ATTACKERS
    apply(state, DeclareAttackers(attacker_ids=frozenset()), player_id=1)
    assert theirs.attacking
    state.active_player_idx = 0
    run_untap_step(state)
    assert theirs.goaded_by is None
    goad(state, theirs, 0)
    clear_goad_for(state, 1)
    assert theirs.goaded_by == 0


def test_throne_with_no_creature_just_shuffles():
    state = _state()
    _library(state, 0, 3)
    UNDERCITY["Throne of the Dead Three"].effect(state, 0)
    assert len(state.players[0].library) == 3


def test_combat_damage_takes_the_initiative_and_ventures():
    state = _state()
    _library(state, 0, 3)
    _library(state, 1, 3)
    take_initiative(state, 1)
    attacker = _put(state, make_creature("Raider", "{R}", 2, 2), 0)
    _simulate_combat_step(state, [attacker.id])
    assert initiative_id(state) == 0
    assert state.players[0].dungeon_room == "Secret Entrance"


# ---------------------------------------------------------------- parser / predicates


def test_parser_phrases_and_gates():
    assert _parse_effect("you become the monarch") == BecomeMonarch()
    assert _parse_effect("you take the initiative") == TakeInitiative()
    assert _parse_intervening_if_phrase("you have the initiative").inner == HasInitiative()
    assert _parse_intervening_if_phrase("you're the monarch").inner == IsMonarch()
    assert _parse_intervening_if_phrase("you've completed a dungeon").inner == CompletedADungeon()
    assert BecomeMonarch().describe() == "you become the monarch"
    assert TakeInitiative().describe() == "you take the initiative"


def test_state_predicates():
    state = _state()
    assert not IsMonarch().test(state, 0)
    assert not HasInitiative().test(state, 0)
    assert not CompletedADungeon().test(state, 0)
    state.players[0].dungeons_completed = 1
    assert CompletedADungeon().test(state, 0)


def test_passageway_seer_claims_and_its_end_step_trigger_fires():
    printings = OracleParserCardSource(pool="cube").get_printings()
    seer = printings["Passageway Seer"]
    state = _state()
    _library(state, 0, 5)
    obj = _put(state, seer, 0)
    BecomeMonarch().resolve(state, 0, ())
    TakeInitiative().resolve(state, 0, ())
    state.active_player_idx = 0
    from mtg_bot.actions import drain_stack

    run_beginning_of_end_step_triggers(state)
    drain_stack(state)
    assert obj.plus_one_counters == 1
    assert len(state.players[0].hand) >= 1  # monarch draw (+ Secret Entrance)
    on_beginning_of_end_step(state)
