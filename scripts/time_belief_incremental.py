"""Standalone cold-call timing for BeliefWeightedDeterminizer.

Grow the played_history one moment at a time and time each cold call.
Reports a cumulative-time series so we can compare before/after the
SIS persistent-particles refactor (Tier 2.5).
"""

from __future__ import annotations

import random
import time
from pathlib import Path

from mtg_bot.actions import PassPriority
from mtg_bot.agents import RandomAgent
from mtg_bot.search.belief import BeliefWeightedDeterminizer, PriorityMoment
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
        m_candidates=8,
        min_opponent_moments=0,
    )

    total = 0.0
    print(
        "moments,cumulative_ms,this_call_ms,ess,resample_count,scored_len"
    )
    for i in range(50):
        sampler.played_history = (
            *sampler.played_history,
            PriorityMoment(
                state=state.clone(), decision=PassPriority(), actor=1,
            ),
        )
        t0 = time.perf_counter()
        sampler(
            state.clone(), viewer_id=0,
            rng=random.Random(i), in_place=False,
        )
        elapsed = time.perf_counter() - t0
        total += elapsed
        scored_len = (
            sampler._particles_state[3]
            if sampler._particles_state is not None else 0
        )
        print(
            f"{i + 1},{total * 1000:.1f},{elapsed * 1000:.2f},"
            f"{sampler.last_ess:.2f},"
            f"{sampler.last_resample_count},{scored_len}"
        )


if __name__ == "__main__":
    main()
