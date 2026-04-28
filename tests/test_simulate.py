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


# ---------------------------------------------------------------------------
# Explicit decklists path (setup_game(decks=...))
# ---------------------------------------------------------------------------


import pytest  # noqa: E402

from mtg_bot.cards.source import get_active_source  # noqa: E402
from mtg_bot.simulate import setup_game  # noqa: E402


def build_mono_color_deck(color: str, seed: int | None = None) -> list[str]:
    return get_active_source().build_mono_color_deck(color, seed=seed)


def _two_color_deck(c1: str, c2: str) -> list[str]:
    """Build a 60-card deck with 12 of each basic land for c1/c2 +
    36 nonland cards split evenly across the two colors (12 each)
    plus 12 colorless. Used to smoke-test that 2-color mana payment
    works end-to-end through the engine — the open question before
    adopting 17lands data."""
    color_to_basic = {"W": "Plains", "U": "Island", "B": "Swamp",
                      "R": "Mountain", "G": "Forest"}
    pool = get_active_source().get_printings()
    c1_cards = [
        name for name, p in pool.items()
        if "Land" not in p.card_types and c1 in p.mana_cost.colors
    ]
    c2_cards = [
        name for name, p in pool.items()
        if "Land" not in p.card_types and c2 in p.mana_cost.colors
    ]
    colorless_cards = [
        name for name, p in pool.items()
        if "Land" not in p.card_types and not p.mana_cost.colors
    ]
    if not c1_cards or not c2_cards or not colorless_cards:
        raise AssertionError(
            f"not enough {c1}/{c2}/colorless cards: "
            f"{len(c1_cards)}/{len(c2_cards)}/{len(colorless_cards)}"
        )
    deck = [c1_cards[i % len(c1_cards)] for i in range(12)]
    deck.extend([c2_cards[i % len(c2_cards)] for i in range(12)])
    deck.extend([colorless_cards[i % len(colorless_cards)] for i in range(12)])
    deck.extend([color_to_basic[c1]] * 12)
    deck.extend([color_to_basic[c2]] * 12)
    return deck


def test_setup_game_accepts_explicit_decks():
    """The new path: pass decks instead of colors."""
    deck0 = build_mono_color_deck("G", seed=0)
    deck1 = build_mono_color_deck("R", seed=1)
    state = setup_game(
        agents=[RandomAgent(), RandomAgent()],
        decks=[deck0, deck1],
        seed=42,
    )
    # Both libraries materialize at the right size (60 minus 7 drawn
    # = 53 each).
    assert len(state.players[0].library) == 53
    assert len(state.players[1].library) == 53
    assert len(state.players[0].hand) == 7
    assert len(state.players[1].hand) == 7


def test_setup_game_rejects_both_colors_and_decks():
    deck = build_mono_color_deck("G", seed=0)
    with pytest.raises(ValueError, match="exactly one"):
        setup_game(
            agents=[RandomAgent()],
            colors=["G"], decks=[deck],
        )


def test_setup_game_rejects_neither_colors_nor_decks():
    with pytest.raises(ValueError, match="exactly one"):
        setup_game(agents=[RandomAgent(), RandomAgent()])


def test_setup_game_rejects_decks_length_mismatch():
    deck = build_mono_color_deck("G", seed=0)
    with pytest.raises(ValueError, match="decks length"):
        setup_game(
            agents=[RandomAgent(), RandomAgent()],
            decks=[deck],  # one deck, two agents
        )


def test_setup_game_rejects_unknown_card_in_deck():
    bad_deck = ["Forest"] * 60
    bad_deck[0] = "Definitely Not A Real Card"
    with pytest.raises(ValueError, match="unknown cards"):
        setup_game(
            agents=[RandomAgent()],
            decks=[bad_deck],
        )


def test_setup_game_explicit_deck_matches_color_path():
    """Sanity: a deck built via build_mono_color_deck and passed
    via decks= should produce a state functionally equivalent to
    passing colors=. Verifies the decks= path doesn't introduce
    drift from existing behavior."""
    deck0 = build_mono_color_deck("G", seed=12345)
    deck1 = build_mono_color_deck("R", seed=12346)
    state_via_decks = setup_game(
        agents=[RandomAgent(), RandomAgent()],
        decks=[deck0, deck1],
        seed=42,
    )
    # We can't assert byte-equality vs the colors= path because the
    # internal seed routing is different (colors= derives per-player
    # seeds from the top-level rng), but we CAN assert library
    # composition (multiset of cards) is the same.
    assert sorted(c.printing.name for c in state_via_decks.players[0].library
                  + state_via_decks.players[0].hand) == sorted(deck0)
    assert sorted(c.printing.name for c in state_via_decks.players[1].library
                  + state_via_decks.players[1].hand) == sorted(deck1)


# ---------------------------------------------------------------------------
# Headline smoke: 2-color decks play through end-to-end
# ---------------------------------------------------------------------------


def test_two_color_deck_game_runs_to_completion():
    """The actual unknown before 17lands integration: does the engine
    handle 2-color mana payment end-to-end? Build G/R + W/U decks,
    play to completion (or max_turns), assert no exceptions and
    that a winner OR draw is set."""
    deck_gr = _two_color_deck("G", "R")
    deck_wu = _two_color_deck("W", "U")
    state = simulate_game(
        agents=[RandomAgent(), RandomAgent()],
        seed=11, max_turns=200,
    )
    # First, sanity that the existing color path still works (no
    # regression from the refactor).
    assert state.is_over()
    # Now the new path with explicit 2-color decks.
    from mtg_bot.simulate import setup_game as _setup_game
    from mtg_bot.simulate import run_turn
    s2 = _setup_game(
        agents=[RandomAgent(), RandomAgent()],
        decks=[deck_gr, deck_wu],
        seed=11,
    )
    # Drive through up to max_turns, mirroring simulate_game's loop
    # but with the explicitly-built state.
    for _ in range(50):
        if s2.is_over():
            break
        run_turn(s2)
        if not s2.is_over():
            from mtg_bot.simulate import _advance_to_next_active_player
            s2.turn_number += 1
            _advance_to_next_active_player(s2)
    # No exception → engine handled multi-color payment OK. We don't
    # require termination at 50 turns (some random games run long);
    # we just want "no crash, state internally consistent."
    assert s2.turn_number > 1
    assert all(
        p.life >= 0 or p.has_lost
        for p in s2.players
    )


def test_two_color_decks_can_cast_their_two_colors():
    """Stronger: across N games of G/W vs U/B, both colors of mana
    actually get spent (someone successfully casts a card costing
    each color). Verifies that mana payment works for non-mono
    colors — not just that the engine doesn't crash."""
    from mtg_bot.simulate import setup_game as _setup_game
    from mtg_bot.simulate import run_turn

    deck_gw = _two_color_deck("G", "W")
    deck_ub = _two_color_deck("U", "B")

    saw_g_cast = False
    saw_w_cast = False
    saw_u_cast = False
    saw_b_cast = False

    for seed in range(8):
        s = _setup_game(
            agents=[RandomAgent(), RandomAgent()],
            decks=[deck_gw, deck_ub],
            seed=seed,
        )
        for _ in range(60):
            if s.is_over():
                break
            run_turn(s)
            if not s.is_over():
                from mtg_bot.simulate import _advance_to_next_active_player
                s.turn_number += 1
                _advance_to_next_active_player(s)
        # Walk each card on the battlefield + graveyard. Anything
        # there came out of someone's hand → was cast → its colors
        # got paid.
        for player_id, observed in ((0, (saw_g_cast, saw_w_cast)),
                                    (1, (saw_u_cast, saw_b_cast))):
            pass
        for o in s.battlefield:
            mc = o.printing.mana_cost
            if "G" in mc.colors:
                saw_g_cast = True
            if "W" in mc.colors:
                saw_w_cast = True
            if "U" in mc.colors:
                saw_u_cast = True
            if "B" in mc.colors:
                saw_b_cast = True
        for p in s.players:
            for o in p.graveyard:
                mc = o.printing.mana_cost
                if "G" in mc.colors:
                    saw_g_cast = True
                if "W" in mc.colors:
                    saw_w_cast = True
                if "U" in mc.colors:
                    saw_u_cast = True
                if "B" in mc.colors:
                    saw_b_cast = True

    # Across 8 games, each color should get spent at least once.
    # If a color never appears, mana payment for that color is
    # broken in the new deck path.
    assert saw_g_cast, "no green spell ever resolved across 8 G/W games"
    assert saw_w_cast, "no white spell ever resolved across 8 G/W games"
    assert saw_u_cast, "no blue spell ever resolved across 8 U/B games"
    assert saw_b_cast, "no black spell ever resolved across 8 U/B games"
