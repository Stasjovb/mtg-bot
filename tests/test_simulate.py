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


# ------------------------------------------------------------------------
# on_snapshot callback
# ------------------------------------------------------------------------


def test_on_snapshot_fires_multiple_times_per_game():
    snapshots: list[int] = []
    simulate_game(
        seed=0, max_turns=200,
        on_snapshot=lambda s: snapshots.append(s.turn_number),
    )
    # Initial + every step of every turn + final. A typical random game is
    # well over 50 steps, so this is a loose lower bound.
    assert len(snapshots) > 10


def test_on_snapshot_first_call_is_turn_one_untap_not_yet_run():
    calls: list[dict] = []
    simulate_game(
        seed=0, max_turns=200,
        on_snapshot=lambda s: calls.append({
            "turn": s.turn_number,
            "step": s.step.value if s.step is not None else None,
        }),
    )
    assert calls[0]["turn"] == 1
    # setup leaves state.step set to UNTAP but no untap has run yet.
    assert calls[0]["step"] == "untap"


def test_on_snapshot_final_call_reflects_game_over_or_draw():
    calls: list[dict] = []
    state = simulate_game(
        seed=0, max_turns=200,
        on_snapshot=lambda s: calls.append({
            "over": s.is_over(),
            "draw": s.is_draw,
            "winner": s.winner_id,
        }),
    )
    assert calls[-1]["over"] or calls[-1]["draw"]
    assert calls[-1]["winner"] == state.winner_id
    assert calls[-1]["draw"] == state.is_draw


def test_on_snapshot_none_is_default_and_noop():
    # Regression: simulation without a callback must still work normally.
    state = simulate_game(seed=0, max_turns=200)
    assert state.is_over() or state.is_draw


def test_on_snapshot_called_with_monotonic_turn_numbers():
    turns: list[int] = []
    simulate_game(
        seed=0, max_turns=200,
        on_snapshot=lambda s: turns.append(s.turn_number),
    )
    # Turn number never decreases.
    assert all(b >= a for a, b in zip(turns, turns[1:]))


def test_snapshot_granularity_priority_produces_more_snapshots():
    step_count = []
    priority_count = []
    simulate_game(
        seed=0, max_turns=10,
        on_snapshot=lambda s: step_count.append(None),
        snapshot_granularity="step",
    )
    simulate_game(
        seed=0, max_turns=10,
        on_snapshot=lambda s: priority_count.append(None),
        snapshot_granularity="priority",
    )
    # Priority granularity is always strictly more — at minimum one
    # priority snapshot per applied action, and most turns have several.
    assert len(priority_count) > len(step_count)


def test_snapshot_granularity_priority_captures_nonempty_stack():
    """With priority granularity, at least one snapshot should observe the
    stack in a populated state (before resolution fires)."""
    saw_stack = [False]

    def capture(state):
        if state.stack:
            saw_stack[0] = True

    simulate_game(
        seed=0, max_turns=30,
        on_snapshot=capture,
        snapshot_granularity="priority",
    )
    assert saw_stack[0], "no priority snapshot ever observed a non-empty stack"


def test_snapshot_granularity_step_never_sees_nonempty_stack():
    """Regression guard for the default: end-of-step snapshots never observe
    a populated stack (priority has fully drained by the time we capture)."""
    saw_stack = [False]

    def capture(state):
        if state.stack:
            saw_stack[0] = True

    simulate_game(
        seed=0, max_turns=30,
        on_snapshot=capture,
        snapshot_granularity="step",
    )
    assert not saw_stack[0]


def test_snapshot_granularity_invalid_raises():
    import pytest
    with pytest.raises(ValueError, match="snapshot_granularity"):
        simulate_game(seed=0, max_turns=3, snapshot_granularity="bogus")  # type: ignore[arg-type]


def test_on_snapshot_sees_draw_for_max_turns_game():
    # max_turns=1 forces a draw; the final snapshot must observe it.
    final: dict = {}
    simulate_game(
        seed=0, max_turns=1,
        on_snapshot=lambda s: final.update({
            "draw": s.is_draw,
            "log_tail": s.log[-1] if s.log else None,
        }),
    )
    assert final["draw"] is True
    assert "draw: reached max 1 turns" == final["log_tail"]
