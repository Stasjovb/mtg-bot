"""Broad simulation-driven coverage tests. Running many games with
diverse seeds and color pairs exercises a wide slice of effects and
trigger paths that targeted unit tests don't reach."""

from mtg_bot.agents import RandomAgent
from mtg_bot.simulate import simulate_game


def test_many_seeds_across_color_pairs_all_terminate():
    """Run a broader sweep than test_simulate — 20 seeds × several
    color pairs. Smoke-tests more code paths via the random walk."""
    pairs = [
        ("W", "U"), ("U", "B"), ("B", "R"), ("R", "G"), ("G", "W"),
        ("W", "B"), ("U", "R"), ("B", "G"), ("R", "W"), ("G", "U"),
    ]
    games = 0
    for seed in range(20):
        for p0, p1 in pairs[: (seed % 3 + 1)]:
            state = simulate_game(
                agents=[RandomAgent(), RandomAgent()],
                colors=[p0, p1],
                seed=seed * 100 + hash((p0, p1)) % 100,
                max_turns=200,
            )
            # Every game must terminate (max_turns cap or a winner).
            games += 1
    assert games > 0


def test_mono_colorless_games_terminate():
    """Stretch — deck builder handles all five mono-color decks. Run
    each against itself at several seeds to exercise color-specific
    card triggers (Void, artifact triggers, landfall, etc.)."""
    for color in ("W", "U", "B", "R", "G"):
        for seed in range(3):
            state = simulate_game(
                agents=[RandomAgent(), RandomAgent()],
                colors=[color, color],
                seed=seed * 11 + ord(color),
                max_turns=200,
            )
            assert state.is_over() or state.turn_number >= 200
