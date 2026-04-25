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
        state = setup_game(
            [RandomAgent(rng=random.Random(seed + 1)),
             RandomAgent(rng=random.Random(seed + 2))],
            ["G", "R"], seed=seed,
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


def _make_pimc_with_rollout_eval(seed: int) -> PIMC:
    """PIMC with RandomRolloutEvaluator (plays out to terminal) instead
    of the heuristic evaluator. Slower per node but produces useful
    signal at modest budgets — the heuristic evaluator scores
    positions at depth-1 *before* the spell on the stack resolves,
    which makes casting look like "lost a card" until the search
    expands deep enough to see the resolution. Documented weakness;
    fixable by scoring the stack contents too, or by always using a
    rollout evaluator. For the integration test we sidestep it.
    """
    def inner_factory() -> MCTS:
        return MCTS(
            evaluator=RandomRolloutEvaluator(
                rng=random.Random(seed + 50),
            ),
            budget_factory=lambda: Budget(max_nodes=30),
            rng=random.Random(seed + 100),
        )
    return PIMC(
        inner_factory=inner_factory,
        samples=2,
        rng=random.Random(seed + 200),
    )


@pytest.mark.skipif(not _SLOW_ENABLED, reason=_SLOW_SKIP_REASON)
def test_pimc_with_rollout_eval_beats_random_in_self_play_smoke():
    """Loose win-rate floor: across N games, PIMC must win at least as
    much as Random. Uses RandomRolloutEvaluator with samples=2 +
    nodes=30 — small but enough for the eval to see past spell
    resolution into the actual resulting board state.

    Not a real win-rate measurement (N is too low for tight CIs);
    this is a "PIMC actually plays MTG and beats the trivial baseline"
    smoke. If this regresses below 50%, integration is suspect."""
    n_games = 10
    pimc_wins = 0
    random_wins = 0
    draws = 0
    for game_idx in range(n_games):
        state = _adapter_factory(seed=1000 + game_idx)()
        strategies = {
            0: _make_pimc_with_rollout_eval(seed=1000 + game_idx),
            1: RandomChoice(rng=random.Random(2000 + game_idx)),
        }
        winner, _ = _play_capped_game(
            state, strategies, rng=random.Random(3000 + game_idx),
        )
        if winner == 0:
            pimc_wins += 1
        elif winner == 1:
            random_wins += 1
        else:
            draws += 1
    assert pimc_wins >= random_wins, (
        f"PIMC won {pimc_wins}, Random won {random_wins}, draws {draws} "
        f"out of {n_games} — PIMC isn't beating Random with rollout "
        f"eval, integration is suspect."
    )


@pytest.mark.skipif(not _SLOW_ENABLED, reason=_SLOW_SKIP_REASON)
def test_pimc_with_heuristic_eval_loses_to_random_documented_weakness():
    """Documents the known heuristic-evaluator weakness so a future
    fix has a regression target.

    ``MtgHeuristicEvaluator`` scores ``(life, board, hand_size)``. At
    depth-1 in the search tree, the active player has just cast a
    spell — so the spell is on the stack, NOT on the battlefield, and
    one card has left their hand. The eval reads this as "card
    advantage went down, board didn't change → cast was bad." MCTS at
    low budget never expands deep enough to see the spell resolve, so
    the heuristic systematically prefers passing.

    When we add a stack-aware term to the evaluator (or replace it
    with a model that scores potential resolutions), this test should
    flip its expectation to "PIMC beats Random" and the rollout-eval
    test above can stay as a baseline. Until then, this test pins the
    weakness in place."""
    n_games = 5
    pimc_wins = 0
    random_wins = 0
    for game_idx in range(n_games):
        state = _adapter_factory(seed=2000 + game_idx)()
        strategies = {
            0: _make_pimc(seed=2000 + game_idx),  # heuristic eval
            1: RandomChoice(rng=random.Random(3000 + game_idx)),
        }
        winner, _ = _play_capped_game(
            state, strategies, rng=random.Random(4000 + game_idx),
        )
        if winner == 0:
            pimc_wins += 1
        elif winner == 1:
            random_wins += 1
    # The current weak heuristic loses badly; pin the expectation so
    # an evaluator improvement triggers a visible test update.
    assert pimc_wins < random_wins, (
        f"PIMC with heuristic eval beat Random ({pimc_wins} vs "
        f"{random_wins}) — the documented weakness may have been "
        f"fixed; flip this test's expectation and consider deleting "
        f"the documentation comment."
    )
