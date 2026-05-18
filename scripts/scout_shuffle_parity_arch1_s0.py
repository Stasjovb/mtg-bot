"""Verify-first scout for arch1/s0 (Class-E next-frontier) with the
b3f7c0a9 fix in place. Pin the step + tripwire + needle of whatever
surfaces next.
"""
from __future__ import annotations

import random

from mtg_bot.parity import trajectory
from mtg_bot.search.engine_adapter_factory import (
    build_shadow_checked_adapter,
)
from mtg_bot.search.rust_shadow import ShadowDivergenceError


def drive(arch: int, seed: int) -> None:
    names = trajectory.load_production_deck(archetype=arch)
    spec = trajectory.production_deck_to_deckspec(
        names, shared_rng_seed=seed
    )
    adapter = build_shadow_checked_adapter(spec)
    decision_rng = random.Random(seed)
    steps = 0
    raised: ShadowDivergenceError | None = None
    raw_exc: BaseException | None = None
    while not adapter.is_terminal() and steps < 4000:
        try:
            legal = adapter.legal_decisions()
        except ShadowDivergenceError as e:
            raised = e
            break
        if not legal:
            break
        choice = decision_rng.choice(legal)
        try:
            adapter.apply(choice)
        except ShadowDivergenceError as e:
            raised = e
            break
        except Exception as e:  # noqa: BLE001
            raw_exc = e
            break
        steps += 1
    print(f"arch{arch}/s{seed}: steps={steps}")
    print(f"  raised={raised}")
    print(f"  raw_exc={raw_exc}")
    if raised is not None:
        print(f"  tripwire={raised.tripwire}")
        print(f"  detail={str(raised)[:600]!r}")


if __name__ == "__main__":
    for arch, seed in ((1, 0), (2, 1), (5, 0), (7, 0), (1, 1)):
        drive(arch, seed)
        print()
