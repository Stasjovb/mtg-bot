"""Tiny harness for generating a structured-token training npz.

Runs ``generate_training_data`` with ``structured_tokens=True``
against a synthetic deck pool, then saves the result via
``save_dataset``. Used by the Step 1 Slice C smoke validation —
the real iterate orchestrator wiring for structured-token writes
is Slice G's domain.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mtg_bot.training import (  # noqa: E402
    PimcConfig,
    generate_training_data,
    random_choice_factory,
    save_dataset,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, required=True,
        help="Output .npz path.",
    )
    parser.add_argument("--n-games", type=int, default=4)
    parser.add_argument("--nodes", type=int, default=10)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    # Tiny PIMC config for fast smoke runs.
    pimc = PimcConfig(samples=1, inner_nodes=args.nodes)
    p0 = pimc.build
    p1 = random_choice_factory

    # Use the project's test deck pool — small and self-contained.
    sys.path.insert(0, str(_HERE.parent / "tests"))
    from _test_decks import simple_test_deck_pool  # noqa: E402
    pool = simple_test_deck_pool()

    print(
        f"# Generating {args.n_games} games with structured tokens; "
        f"nodes={args.nodes}"
    )
    result = generate_training_data(
        p0_factory=p0,
        p1_factory=p1,
        n_games=args.n_games,
        base_seed=args.seed,
        deck_pool=pool,
        with_policy=True,
        structured_tokens=True,
    )
    (
        features, outcomes, policy_targets, action_masks,
        tt, emb_ids, scalars, mask,
    ) = result
    print(
        f"# {features.shape[0]} samples; struct shape "
        f"{tt.shape} / {emb_ids.shape} / {scalars.shape} / {mask.shape}"
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    save_dataset(
        features, outcomes, args.out,
        policy_targets=policy_targets,
        action_masks=action_masks,
        structured_token_type=tt,
        structured_token_emb_ids=emb_ids,
        structured_token_scalars=scalars,
        structured_attention_mask=mask,
    )
    print(f"# Wrote {args.out}")


if __name__ == "__main__":
    main()
