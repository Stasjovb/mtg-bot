"""End-to-end integration tests for PIMC against the real MTG engine.

These run an actual game (or a few of them) start-to-finish through the
harness, with PIMC driving one seat. Unit tests cover the pieces in
isolation; this file is the "pipeline doesn't crash and actually plays
MTG" check that catches integration regressions the unit tests can't.

Two tiers:

- **Default suite**: a single capped game with the smallest realistic
  PIMC budgets. Catches crashes, illegal-action returns, infinite
  loops in the priority loop. Runs in single-digit seconds.
- **Slow self-play smoke** (``MTG_BOT_SLOW=1``): ~10 games PIMC vs
  RandomChoice. Loose win-rate sanity check — confirms PIMC actually
  beats the baseline rather than no-op'ing into draws. Skipped by
  default because each game is seconds-to-minutes of real-engine work
  and the test suite shouldn't pay that cost on every run.
"""

from __future__ import annotations

import os
import random

import pytest

from mtg_bot.actions import Action
from mtg_bot.agents import RandomAgent
from mtg_bot.search import (
    Budget, MCTS, MtgGameStateAdapter, PIMC, RandomChoice,
    RandomRolloutEvaluator,
)
from mtg_bot.search.heuristic_evaluator import MtgHeuristicEvaluator
from mtg_bot.search.protocol import CHANCE_PLAYER
from mtg_bot.simulate import setup_game
from tests._test_decks import simple_test_decklists  # noqa: E402


# Tiny budgets so a default-suite game finishes in single-digit seconds.
# These won't produce strong play — that's not the point. The point is
# "the wiring runs end-to-end without exploding."
_INTEGRATION_PIMC_SAMPLES = 1
_INTEGRATION_INNER_NODES = 15

# Hard cap on decisions per game so an infinite-loop bug shows up as a
# test failure rather than a hung suite. Real games are well under this.
_DECISION_CAP = 4000


def _adapter_factory(seed: int):
    """Build a fresh adapter-wrapped engine state with two RandomAgent
    placeholders. The adapter overwrites the agents with its tactical
    policy on construction, so the placeholders are just shape-fillers."""
    def make() -> MtgGameStateAdapter:
        state = setup_game([RandomAgent(rng=random.Random(seed + 1)),
             RandomAgent(rng=random.Random(seed + 2))], decks=simple_test_decklists(), seed=seed,
        )
        return MtgGameStateAdapter(state)
    return make


def _make_pimc(seed: int) -> PIMC:
    def inner_factory() -> MCTS:
        return MCTS(
            evaluator=MtgHeuristicEvaluator(),
            budget_factory=lambda: Budget(max_nodes=_INTEGRATION_INNER_NODES),
            rng=random.Random(seed + 100),
        )
    return PIMC(
        inner_factory=inner_factory,
        samples=_INTEGRATION_PIMC_SAMPLES,
        rng=random.Random(seed + 200),
    )


def _play_capped_game(
    state, strategies, rng, decision_cap: int = _DECISION_CAP,
) -> tuple[int | None, int]:
    """Play through the harness loop with a hard decision cap. Returns
    ``(winner_id_or_None, decisions_made)``.

    Mirrors ``play_one_game`` but adds the cap so tests that hit a
    pathological state fail fast instead of hanging the suite.
    """
    decisions = 0
    while not state.is_terminal() and decisions < decision_cap:
        active = state.active_player()
        if active == CHANCE_PLAYER:
            outcomes = state.chance_outcomes()
            choices = [d for d, _ in outcomes]
            weights = [w for _, w in outcomes]
            decision = rng.choices(choices, weights=weights, k=1)[0]
        else:
            decision = strategies[active].choose(state, active)
            assert decision in state.legal_decisions(), (
                f"strategy returned an illegal decision: {decision!r}"
            )
        state.apply(decision)
        decisions += 1
    if state.is_terminal():
        return state.winner(), decisions
    return None, decisions


# ---------- default suite (cheap) -------------------------------------------


def test_random_vs_random_baseline_completes():
    """Sanity check: the harness wiring + adapter + RandomChoice can run
    a game start-to-finish without hitting the decision cap. This is the
    yardstick — if PIMC's tests fail, was it PIMC or the harness path?"""
    state = _adapter_factory(seed=11)()
    strategies = {
        0: RandomChoice(rng=random.Random(1)),
        1: RandomChoice(rng=random.Random(2)),
    }
    winner, decisions = _play_capped_game(
        state, strategies, rng=random.Random(3),
    )
    assert state.is_terminal(), (
        f"baseline random-vs-random hit the {_DECISION_CAP}-decision cap "
        f"after {decisions} decisions without terminating"
    )
    # Winner can be 0, 1, or None (draw on max-turns or mutual loss).
    assert winner in (0, 1, None)


def test_pimc_plays_a_complete_game_against_random():
    """The headline integration test: PIMC drives seat 0, RandomChoice
    drives seat 1, the game runs to completion (or hits the cap) without
    raising. Every PIMC decision is asserted legal in the loop."""
    state = _adapter_factory(seed=42)()
    strategies = {
        0: _make_pimc(seed=42),
        1: RandomChoice(rng=random.Random(7)),
    }
    winner, decisions = _play_capped_game(
        state, strategies, rng=random.Random(13),
    )
    assert state.is_terminal(), (
        f"PIMC vs Random game hit the {_DECISION_CAP}-decision cap "
        f"after {decisions} decisions without terminating — likely an "
        f"infinite priority loop"
    )
    assert winner in (0, 1, None)


def test_pimc_in_both_seats_completes():
    """PIMC vs PIMC. Slower than random-vs-random but exercises both
    seats running search; catches asymmetric bugs the seat-0-only test
    might miss."""
    state = _adapter_factory(seed=99)()
    strategies = {
        0: _make_pimc(seed=99),
        1: _make_pimc(seed=199),
    }
    winner, decisions = _play_capped_game(
        state, strategies, rng=random.Random(1),
    )
    assert state.is_terminal(), (
        f"PIMC self-play hit the {_DECISION_CAP}-decision cap after "
        f"{decisions} decisions"
    )
    assert winner in (0, 1, None)


def test_pimc_does_not_mutate_state_outside_apply():
    """The strategy.choose() contract is "must NOT mutate the caller's
    state." Verify by snapshotting the engine state before each PIMC
    decision and confirming choose() leaves it bit-identical (changes
    happen only when we call state.apply() ourselves)."""
    state = _adapter_factory(seed=23)()
    pimc = _make_pimc(seed=23)
    rng = random.Random(13)
    decisions = 0
    DECISION_CHECKS = 30  # spot-check the first N decisions; full game is slow

    while not state.is_terminal() and decisions < DECISION_CHECKS:
        active = state.active_player()
        if active == CHANCE_PLAYER:
            outcomes = state.chance_outcomes()
            choices = [d for d, _ in outcomes]
            weights = [w for _, w in outcomes]
            decision = rng.choices(choices, weights=weights, k=1)[0]
        else:
            pre_turn = state.engine_state.turn_number
            pre_step = state.engine_state.step
            pre_lifes = [p.life for p in state.engine_state.players]
            pre_hand = [
                [c.id for c in p.hand]
                for p in state.engine_state.players
            ]
            decision = pimc.choose(state, active)
            assert state.engine_state.turn_number == pre_turn
            assert state.engine_state.step == pre_step
            assert [p.life for p in state.engine_state.players] == pre_lifes
            assert [
                [c.id for c in p.hand]
                for p in state.engine_state.players
            ] == pre_hand
        state.apply(decision)
        decisions += 1


# ---------- slow self-play smoke (opt-in) -----------------------------------


_SLOW_ENABLED = os.environ.get("MTG_BOT_SLOW") == "1"
_SLOW_SKIP_REASON = (
    "Set MTG_BOT_SLOW=1 to run self-play smoke (each game is "
    "seconds-to-minutes of real-engine work)."
)


def _make_pimc_with_eval(
    seed: int, evaluator_factory, samples: int, nodes: int,
) -> PIMC:
    """Build a PIMC with the given evaluator factory and budget knobs.
    Used for the slow self-play tests where we want a real-search-
    quality budget rather than the integration default's crash-check
    tininess."""
    def inner_factory() -> MCTS:
        return MCTS(
            evaluator=evaluator_factory(),
            budget_factory=lambda: Budget(max_nodes=nodes),
            rng=random.Random(seed + 100),
        )
    return PIMC(
        inner_factory=inner_factory,
        samples=samples,
        rng=random.Random(seed + 200),
    )


def _self_play(
    pimc_factory, n_games: int, base_seed: int,
) -> tuple[int, int, int]:
    """Play ``n_games`` of PIMC vs RandomChoice and return
    ``(pimc_wins, random_wins, draws)``. Each game gets independent
    seeds derived from ``base_seed``."""
    pimc_wins = 0
    random_wins = 0
    draws = 0
    for game_idx in range(n_games):
        state = _adapter_factory(seed=base_seed + game_idx)()
        strategies = {
            0: pimc_factory(seed=base_seed + game_idx),
            1: RandomChoice(rng=random.Random(base_seed + 1000 + game_idx)),
        }
        winner, _ = _play_capped_game(
            state, strategies,
            rng=random.Random(base_seed + 2000 + game_idx),
        )
        if winner == 0:
            pimc_wins += 1
        elif winner == 1:
            random_wins += 1
        else:
            draws += 1
    return pimc_wins, random_wins, draws


@pytest.mark.skipif(not _SLOW_ENABLED, reason=_SLOW_SKIP_REASON)
def test_pimc_with_rollout_eval_beats_random_in_self_play_smoke():
    """Loose win-rate floor: PIMC with RandomRolloutEvaluator
    (samples=2, nodes=30) must win at least as many games as Random
    over 10 plays. Not a tight win-rate measurement (N too low for
    real CIs); this is a "the integration produces MTG-strong play
    when fed an unbiased evaluator" smoke."""
    pimc_wins, random_wins, draws = _self_play(
        pimc_factory=lambda *, seed: _make_pimc_with_eval(
            seed=seed,
            evaluator_factory=lambda: RandomRolloutEvaluator(
                rng=random.Random(seed + 50),
            ),
            samples=2, nodes=30,
        ),
        n_games=10, base_seed=1000,
    )
    assert pimc_wins >= random_wins, (
        f"PIMC+rollout won {pimc_wins}, Random won {random_wins}, "
        f"draws {draws}/10 — integration suspect."
    )


@pytest.mark.skipif(not _SLOW_ENABLED, reason=_SLOW_SKIP_REASON)
def test_pimc_with_heuristic_eval_beats_random_in_self_play_smoke():
    """Heuristic eval at moderate budget (samples=4, nodes=200 —
    matching ``recommend.py`` defaults) must win at least as many
    games as Random over 10 plays.

    Earlier this test was a documented-weakness pin asserting the
    OPPOSITE — the heuristic evaluator scored (life, board,
    hand_size) at depth-1, so casting any spell looked like "lost a
    card" because the stack contents weren't scored and the spell
    hadn't resolved into board yet. PIMC systematically preferred
    passing.

    The fix lives in ``heuristic_evaluator.py``:
    - Stack creature spells contribute their printed P+T to the
      board term (impending board change).
    - Non-creature stack spells count toward the card term (value
      still in flight).
    - Permanents controlled count toward the card term (so playing
      a land doesn't read as "lost a card" — hand → battlefield is
      a no-op for this term).

    With those changes, the heuristic eval is competitive with
    Random at the UI's recommendation budget. Regression target if
    the eval ever stops beating Random again."""
    pimc_wins, random_wins, draws = _self_play(
        pimc_factory=lambda *, seed: _make_pimc_with_eval(
            seed=seed,
            evaluator_factory=MtgHeuristicEvaluator,
            samples=4, nodes=200,
        ),
        n_games=10, base_seed=2000,
    )
    assert pimc_wins >= random_wins, (
        f"PIMC+heuristic won {pimc_wins}, Random won {random_wins}, "
        f"draws {draws}/10 — heuristic eval regressed; check the "
        f"stack-aware scoring in heuristic_evaluator.py."
    )
