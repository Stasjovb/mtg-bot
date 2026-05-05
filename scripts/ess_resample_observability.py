"""Drive a real game forward, accumulate diverse opponent moments,
and report how often the SIS resampler fires under the trained NN.

Useful as a smoke test for "is the ESS-based resample tripping at
all on a realistic moment stream", and as a diagnostic when tuning
``ess_resample_threshold``.
"""

from __future__ import annotations

import random
from pathlib import Path

from mtg_bot.agents import RandomAgent
from mtg_bot.search.belief import BeliefWeightedDeterminizer, PriorityMoment
from mtg_bot.search.engine_adapter import MtgGameStateAdapter
from mtg_bot.search.nn_evaluator import NNEvaluator
from mtg_bot.simulate import _default_deck_for_color as _default_deck, setup_game


def main() -> None:
    state = setup_game(
        [RandomAgent(), RandomAgent()], decks=[_default_deck("G", 11), _default_deck("R", 11)], seed=11,
    )
    weights = Path(__file__).resolve().parent.parent.parent / (
        "mtg-bot/trained_weights/v10/weights.pt"
    )
    if not weights.exists():
        weights = Path("../../mtg-bot/trained_weights/v10/weights.pt")
    evaluator = NNEvaluator(
        weights_path=weights,
        with_policy=True,
        hidden_sizes=(1024, 1024, 512),
    )
    sampler = BeliefWeightedDeterminizer(
        opponent_policy_evaluator=evaluator,
        played_history=[],
        m_candidates=16,
        min_opponent_moments=0,
        ess_resample_threshold=0.5,
    )

    # Drive the live state forward by picking the first legal
    # decision at each priority moment, capturing snapshots of
    # opponent (player 1) priority moments along the way.
    adapter = MtgGameStateAdapter(state)
    print("step,actor,opp_moments,ess,resample_count")
    step = 0
    rng = random.Random(2027)
    while not adapter.is_terminal() and step < 200:
        legal = adapter.legal_decisions()
        if not legal:
            break
        actor = adapter.active_player()
        decision = legal[0]
        # Capture a moment for the opponent's actions.
        if actor == 1:
            sampler.played_history = (
                *sampler.played_history,
                PriorityMoment(
                    state=adapter.engine_state.clone(),
                    decision=decision,
                    actor=actor,
                ),
            )
            sampler(
                adapter.engine_state.clone(), viewer_id=0, rng=rng,
                in_place=False,
            )
            opp_count = sum(
                1 for m in sampler.played_history if m.actor == 1
            )
            print(
                f"{step},{actor},{opp_count},"
                f"{sampler.last_ess:.2f},"
                f"{sampler.last_resample_count}"
            )
        adapter.apply(decision)
        step += 1
    print(
        f"FINAL: total_opp_moments={sum(1 for m in sampler.played_history if m.actor == 1)} "
        f"resamples={sampler.last_resample_count}"
    )


if __name__ == "__main__":
    main()
