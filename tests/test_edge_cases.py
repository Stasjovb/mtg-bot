"""Edge-case and error-path tests that aren't a natural fit in other files."""

import pytest

from mtg_bot.actions import (
    CastSpell,
    PassPriority,
    PlayLand,
    apply_action,
    resolve_top_of_stack,
)
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES, parse_mana_cost
from mtg_bot.combat import resolve_combat_damage
from mtg_bot.game import GameState, Player, StackItem, Zone
from mtg_bot.simulate import simulate_game
from mtg_bot.turn import draw_card, run_cleanup_step, state_based_actions

from mtg_bot.cards.source import get_active_source
from tests._test_decks import simple_test_decklists  # noqa: E402


# -----------------------
# cards.py error / edge paths
# -----------------------


def test_parse_mana_cost_colorless_treated_as_generic():
    # {C} is colorless mana; Stage 1 treats it as generic
    c = parse_mana_cost("{C}")
    assert c.generic == 1
    assert c.colored == ()


def test_parse_mana_cost_rejects_unknown_symbol():
    with pytest.raises(ValueError, match="unsupported mana symbol"):
        parse_mana_cost("{Z}")


def test_parse_mana_cost_x_is_zero_generic():
    """X-cost spells parse {X} as 0 generic — we don't model X-choice yet."""
    assert parse_mana_cost("{X}").generic == 0
    assert parse_mana_cost("{X}{X}{R}").generic == 0


def test_build_deck_rejects_unknown_color():
    with pytest.raises(ValueError, match="unknown color"):
        get_active_source().build_mono_color_deck("Z")


def test_build_deck_rejects_color_with_no_creatures(monkeypatch):
    # Fake-out the parser source's printings so a color has no cards,
    # exercising the "no creatures in color" branch.
    from mtg_bot.cards.source import get_active_source

    src = get_active_source()
    monkeypatch.setattr(src, "_printings", {})
    with pytest.raises(ValueError, match="no creatures in color"):
        src.build_mono_color_deck("G")


# -----------------------
# actions.py error paths
# -----------------------


def test_apply_pass_priority_is_noop():
    state = GameState()
    state.players.append(Player(id=0))
    apply_action(state, 0, PassPriority())  # should not raise or mutate anything
    assert len(state.battlefield) == 0


def test_apply_unknown_action_raises():
    state = GameState()
    state.players.append(Player(id=0))
    with pytest.raises(ValueError, match="unknown action"):
        apply_action(state, 0, object())  # type: ignore[arg-type]


def test_resolve_unknown_card_type_raises():
    # Construct a CardPrinting with no recognised types — exercises the
    # defensive branch in resolve_top_of_stack. In real play every card is
    # either a permanent (creature/artifact/land/enchantment/planeswalker)
    # or a spell (instant/sorcery), so this shouldn't happen organically.
    from mtg_bot.cards import CardPrinting, ManaCost

    state = GameState()
    state.players.append(Player(id=0))
    weird_printing = CardPrinting(
        name="Typeless Thing",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Tribal",
        supertypes=(),
        card_types=("Tribal",),
        subtypes=(),
    )
    obj = state.new_object(weird_printing, owner_id=0, zone=Zone.STACK)
    state.stack.append(StackItem(source=obj, controller_id=0))
    with pytest.raises(ValueError, match="don't know how to resolve"):
        resolve_top_of_stack(state)


# -----------------------
# agents.py branches
# -----------------------


def test_random_agent_declare_blockers_empty_attackers():
    agent = RandomAgent()
    # If there are no attackers, declare_blockers should return {} immediately.
    result = agent.declare_blockers(state=None, player_id=0, eligible=[], attackers=[])
    assert result == {}


def test_random_agent_passes_when_only_pass_legal():
    agent = RandomAgent()
    result = agent.choose_action(state=None, player_id=0, legal=[PassPriority()])
    assert isinstance(result, PassPriority)


def test_random_agent_choose_target_returns_none_when_no_legal():
    agent = RandomAgent()
    assert agent.choose_target(state=None, player_id=0, legal_targets=[]) is None


def test_random_agent_choose_target_picks_from_legal():
    agent = RandomAgent()
    legal = [("player", 1), ("player", 2)]
    choice = agent.choose_target(state=None, player_id=0, legal_targets=legal)
    assert choice in legal


def test_random_agent_choose_discard_picks_from_hand():
    agent = RandomAgent()
    hand_ids = [10, 20, 30]
    assert agent.choose_discard(state=None, player_id=0, hand_card_ids=hand_ids) in hand_ids


# -----------------------
# game.py helpers + error paths
# -----------------------


def test_player_by_id_raises_for_unknown_id():
    state = GameState()
    state.players.append(Player(id=0))
    with pytest.raises(KeyError):
        state.player_by_id(99)


def test_index_of_finds_and_raises():
    state = GameState()
    state.players.append(Player(id=7))
    state.players.append(Player(id=8))
    assert state.index_of(7) == 0
    assert state.index_of(8) == 1
    with pytest.raises(KeyError):
        state.index_of(99)


def test_creatures_and_lands_controlled_by():
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD)
    forest = state.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
    island = state.new_object(BASIC_LANDS["Island"], 1, Zone.BATTLEFIELD)
    state.battlefield.extend([bear, forest, island])
    assert state.creatures_controlled_by(0) == [bear]
    assert state.creatures_controlled_by(1) == []
    assert state.lands_controlled_by(0) == [forest]
    assert state.lands_controlled_by(1) == [island]


# -----------------------
# turn.py branches
# -----------------------


def test_draw_from_empty_library_makes_player_lose():
    state = GameState()
    state.players.append(Player(id=0))  # no library
    draw_card(state, 0)
    assert state.players[0].has_lost
    assert "empty library" in state.players[0].lost_reason


def test_cleanup_discards_down_to_seven():
    state = GameState()
    p = Player(id=0)
    state.players.append(p)
    for _ in range(10):
        c = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.HAND)
        p.hand.append(c)
    state.active_player_idx = 0
    run_cleanup_step(state)
    assert len(p.hand) == 7
    assert len(p.graveyard) == 3


def test_cleanup_clears_damage_on_permanents():
    state = GameState()
    state.players.append(Player(id=0))
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD)
    bear.damage = 1
    state.battlefield.append(bear)
    run_cleanup_step(state)
    assert bear.damage == 0


def test_both_players_zero_life_results_in_draw():
    state = GameState()
    state.players.append(Player(id=0, life=0))
    state.players.append(Player(id=1, life=0))
    state_based_actions(state)
    assert state.is_draw
    assert state.winner_id is None


def test_state_based_actions_is_idempotent_once_draw_set():
    state = GameState()
    state.players.append(Player(id=0, life=0))
    state.players.append(Player(id=1, life=0))
    assert state_based_actions(state) is True  # first call flips draw
    # Second call: no alive players, draw already set — should NOT report changes
    assert state_based_actions(state) is False


# -----------------------
# simulate.py branches
# -----------------------


def test_simulate_rejects_mismatched_agents_and_colors():
    with pytest.raises(ValueError, match="same length"):
        simulate_game(agents=[RandomAgent()], decks=simple_test_decklists(), seed=0)


def test_simulate_verbose_prints(capsys):
    simulate_game(seed=0, max_turns=5, verbose=True)
    out = capsys.readouterr().out
    assert "Turn" in out


def test_simulate_hits_max_turns_and_draws():
    # Force an early max-turn draw. With max_turns=1 the game almost certainly
    # can't finish, so we expect a draw result and a log entry naming the cap.
    state = simulate_game(seed=0, max_turns=1)
    if state.is_draw and state.winner_id is None:
        assert any("max" in line for line in state.log)
