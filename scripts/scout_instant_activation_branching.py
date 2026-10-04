"""Scout: how instant-speed activations change search branching and cost.

Throwaway diagnostic (see CLAUDE.md "Throwaway investigation scripts").
Plays ``--games`` seeded games on a deck pool with the same agent in both
seats (``heuristic`` PIMC at a small fixed budget, or ``random``) through
the production game driver (``self_play._play_one_match_game``: the
search adapter with its default heuristics and the decision cap), and
reports per-game work:

* ``decisions`` -- decisions the driver applied;
* ``priority_calls`` -- ``legal_decisions`` calls at priority windows
  (search included), and how many of them the capability auto-pass
  short-circuited;
* ``branching`` -- mean legal-decision count at non-short-circuited
  priority windows, and the share of those that offered an
  ``ActivateAbility``;
* ``nodes`` -- search nodes (``search.eval_counters``);
* ``wall_s`` -- wall seconds.

Run it once per code version from the version's worktree, same seeds,
back to back (``docs/BENCHMARKING_FINDINGS.md``: compare ratios from one
window), e.g.::

    PYTHONPATH=src .venv-py313/Scripts/python.exe \
        scripts/scout_instant_activation_branching.py --games 20 --out a.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--games", type=int, default=20)
    ap.add_argument("--start-game", type=int, default=0,
                    help="first game index (resume a partial run)")
    ap.add_argument("--seed", type=int, default=7000)
    ap.add_argument("--agent", choices=("heuristic", "random"),
                    default="heuristic")
    ap.add_argument("--samples", type=int, default=1)
    ap.add_argument("--nodes", type=int, default=40)
    ap.add_argument("--decision-cap", type=int, default=3000)
    ap.add_argument("--deck-pool", type=Path,
                    default=Path("data/cube/power_lsv_decks.json.gz"))
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    from mtg_bot.actions import ActivateAbility
    from mtg_bot.decks import decks_from_json
    from mtg_bot.search import eval_counters
    from mtg_bot.search.engine_adapter import MtgGameStateAdapter
    from mtg_bot.cli.ladder import RandomConfig
    from mtg_bot.training import HeuristicConfig, PimcConfig
    from mtg_bot.training.self_play import _play_one_match_game

    tally = {"priority_calls": 0, "short_circuited": 0,
             "full_windows": 0, "full_legal": 0, "aa_windows": 0}
    real_legal = MtgGameStateAdapter.legal_decisions
    real_sc = MtgGameStateAdapter._can_short_circuit_to_pass

    def legal_decisions(self):
        out = real_legal(self)
        if self._combat_phase is None and not self._resolution_paused:
            tally["priority_calls"] += 1
            if len(out) > 1:
                tally["full_windows"] += 1
                tally["full_legal"] += len(out)
                if any(isinstance(d, ActivateAbility) for d in out):
                    tally["aa_windows"] += 1
        return out

    def short_circuit(self):
        r = real_sc(self)
        if r:
            tally["short_circuited"] += 1
        return r

    MtgGameStateAdapter.legal_decisions = legal_decisions
    MtgGameStateAdapter._can_short_circuit_to_pass = short_circuit

    if args.agent == "heuristic":
        factory = PimcConfig(
            samples=args.samples, inner_nodes=args.nodes,
            heuristic=HeuristicConfig(), batch_size=1,
        ).build
    else:
        factory = RandomConfig().build
    pool = decks_from_json(args.deck_pool)

    rows = []
    for g in range(args.start_game, args.start_game + args.games):
        for k in tally:
            tally[k] = 0
        eval_counters.reset()
        t0 = time.perf_counter()
        winner, decisions = _play_one_match_game(
            g, factory, factory, args.seed, args.decision_cap,
            deck_pool=pool,
        )
        wall = time.perf_counter() - t0
        c = eval_counters.snapshot()
        rows.append({
            "game": g, "winner": winner, "decisions": decisions,
            "wall_s": round(wall, 3), "nodes": c.nodes, **dict(tally),
        })
        print(json.dumps(rows[-1]), flush=True)

    def tot(k):
        return sum(r[k] for r in rows)

    summary = {
        "games": len(rows),
        "agent": args.agent, "samples": args.samples, "nodes_budget": args.nodes,
        "decisions_per_game": tot("decisions") / len(rows),
        "priority_calls_per_game": tot("priority_calls") / len(rows),
        "short_circuit_rate": tot("short_circuited") / max(1, tot("priority_calls")),
        "full_windows_per_game": tot("full_windows") / len(rows),
        "mean_branching_full_windows": tot("full_legal") / max(1, tot("full_windows")),
        "aa_window_share": tot("aa_windows") / max(1, tot("full_windows")),
        "search_nodes_per_game": tot("nodes") / len(rows),
        "wall_s_per_game": tot("wall_s") / len(rows),
        "wall_ms_per_search_node": 1000 * tot("wall_s") / max(1, tot("nodes")),
        "draws_or_capped": sum(1 for r in rows if r["winner"] is None),
    }
    print(json.dumps(summary, indent=1))
    if args.out is not None:
        args.out.write_text(json.dumps({"summary": summary, "games": rows},
                                       indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
