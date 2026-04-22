from mtg_bot.agents import RandomAgent
from mtg_bot.simulate import simulate_game


def test_random_game_terminates():
    state = simulate_game(seed=0, max_turns=200)
    assert state.is_over()


def test_winner_or_draw_is_set():
    state = simulate_game(seed=1, max_turns=200)
    assert (state.winner_id is not None) or state.is_draw


def test_many_seeds_all_terminate():
    terminated = 0
    for seed in range(10):
        state = simulate_game(seed=seed, max_turns=300)
        if state.is_over():
            terminated += 1
    assert terminated == 10


def test_winner_has_alive_opponent_dead():
    # If someone wins, the other player must have lost (or be dead)
    for seed in range(5):
        state = simulate_game(seed=seed, max_turns=300)
        if state.winner_id is not None:
            loser = next(p for p in state.players if p.id != state.winner_id)
            assert loser.has_lost


def test_deterministic_with_seed():
    a = simulate_game(seed=42, max_turns=300)
    b = simulate_game(seed=42, max_turns=300)
    assert a.winner_id == b.winner_id
    assert a.is_draw == b.is_draw
    assert a.turn_number == b.turn_number


def test_two_different_colors_play_each_other():
    state = simulate_game(
        agents=[RandomAgent(), RandomAgent()],
        colors=["W", "B"],
        seed=3,
        max_turns=300,
    )
    assert state.is_over()
