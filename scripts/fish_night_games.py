"""Play Forgetful Fish games unattended (overnight) and log every result.

Rotates matchups between ``random`` and ``heuristic`` (the heuristic PIMC
bot ``mtg_bot ladder`` calls "heuristic") on a process pool, on the shared
library from ``data/forgetful_fish/`` (the real list once present, else the
placeholder). Each game -- or crash, with its traceback -- is one JSON line
in ``<out>/games.jsonl``; ``<out>/summary.json`` / ``summary.md`` are
rewritten as games finish. Stops at ``--until`` (or ``--max-games``).

    PYTHONPATH=src python scripts/fish_night_games.py \
        --out ../../fish-data/night-2026-11-02 --start-at 23:00 --until 07:00

Times are local wall-clock; an ``--until`` earlier than ``--start-at`` means
the next morning. Games still running at the deadline are abandoned.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import multiprocessing as mp
import random
import time
import traceback
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

MATCHUPS = (
    ("random", "random"),
    ("heuristic", "random"),
    ("random", "heuristic"),
    ("heuristic", "heuristic"),
)


def _keep_awake(on: bool) -> None:
    """Windows: ask the OS not to idle-sleep while games run (released on
    ``False`` or when the process exits). A no-op elsewhere."""
    try:
        import ctypes

        es_continuous, es_system_required = 0x80000000, 0x00000001
        flags = es_continuous | (es_system_required if on else 0)
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except (AttributeError, OSError):
        pass


def _next_time(hhmm: str, after: dt.datetime) -> dt.datetime:
    hour, minute = (int(x) for x in hhmm.split(":"))
    t = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return t if t > after else t + dt.timedelta(days=1)


def window(
    start_at: Optional[str], until: str, now: dt.datetime,
) -> tuple[dt.datetime, dt.datetime]:
    """``(start, end)`` local datetimes; no ``start_at`` = start now."""
    start = now if start_at is None else _next_time(start_at, now)
    if start_at is not None and start - dt.timedelta(days=1) <= now < _next_time(
        until, start - dt.timedelta(days=1),
    ):
        # Already inside today's window (e.g. launched at 01:00 for 23-07).
        start = now
    return start, _next_time(until, start)


def _factory(label: str, samples: int, nodes: int):
    if label == "random":
        from mtg_bot.cli.ladder import RandomConfig

        return RandomConfig().build
    from mtg_bot.training import HeuristicConfig, PimcConfig

    return PimcConfig(
        samples=samples, inner_nodes=nodes, heuristic=HeuristicConfig(),
    ).build


def play_one(job: dict[str, Any]) -> dict[str, Any]:
    """Play one Fish game; never raises (a crash is a result)."""
    from mtg_bot.agents import RandomAgent
    from mtg_bot.formats import FORGETFUL_FISH
    from mtg_bot.search.engine_adapter_factory import make_game_state_adapter
    from mtg_bot.search.heuristics_config import HeuristicsConfig
    from mtg_bot.simulate import setup_game
    from mtg_bot.training.self_play import _play_capped_game

    seed = job["seed"]
    a, b = job["matchup"]
    out: dict[str, Any] = {
        "game": job["game"], "seed": seed, "p0": a, "p1": b,
        "started": dt.datetime.now().isoformat(timespec="seconds"),
    }
    t0 = time.perf_counter()
    try:
        engine = setup_game(
            [RandomAgent(rng=random.Random(seed + 1)),
             RandomAgent(rng=random.Random(seed + 2))],
            decks=[job["library"]], seed=seed, game_format=FORGETFUL_FISH,
        )
        adapter = make_game_state_adapter(
            engine, expose_combat_decisions=True,
            heuristics=HeuristicsConfig.live_eval(),
        )
        strategies = {
            0: _factory(a, job["samples"], job["nodes"])(seed + 100),
            1: _factory(b, job["samples"], job["nodes"])(seed + 150),
        }
        winner, decisions = _play_capped_game(
            adapter, strategies, random.Random(seed + 99), job["decision_cap"],
        )
        state = adapter.engine_state
        p0, p1 = state.players
        out.update({
            "winner": winner, "decisions": decisions,
            "turns": state.turn_number,
            "life": [p0.life, p1.life],
            "lost_reason": [p0.lost_reason, p1.lost_reason],
            "library_left": len(p0.library),
            "shared_ok": p0.library is p1.library
            and p0.graveyard is p1.graveyard,
        })
    except Exception as exc:  # noqa: BLE001 -- a crash is data here
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["traceback"] = traceback.format_exc()
    out["seconds"] = round(time.perf_counter() - t0, 2)
    return out


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_matchup: dict[str, Counter] = defaultdict(Counter)
    errors: Counter = Counter()
    for r in rows:
        key = f"{r['p0']} vs {r['p1']}"
        c = by_matchup[key]
        c["games"] += 1
        if "error" in r:
            c["crashed"] += 1
            last = r["traceback"].strip().splitlines()[-1]
            errors[last[:200]] += 1
        elif r["winner"] is None:
            c["draws"] += 1
        else:
            c[f"p{r['winner']}_wins"] += 1
        c["seconds"] += r["seconds"]
        if r.get("shared_ok") is False:
            c["shared_zone_broken"] += 1
    return {
        "games": len(rows),
        "crashed": sum(1 for r in rows if "error" in r),
        "matchups": {k: dict(v) for k, v in by_matchup.items()},
        "errors": errors.most_common(25),
    }


def _write_summary(out_dir: Path, rows: list[dict[str, Any]], meta: dict) -> None:
    summary = {**meta, **summarize(rows)}
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8",
    )
    lines = [
        f"# Forgetful Fish night run ({meta['started']} - {meta['deadline']})",
        "",
        f"Library: {meta['decklist']} ({meta['library_size']} cards). "
        f"Games: {summary['games']}, crashed: {summary['crashed']}.",
        "",
        "| matchup | games | P0 wins | P1 wins | draws | crashed | avg s |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for k, c in summary["matchups"].items():
        avg = c.get("seconds", 0) / max(c["games"], 1)
        lines.append(
            f"| {k} | {c['games']} | {c.get('p0_wins', 0)} | "
            f"{c.get('p1_wins', 0)} | {c.get('draws', 0)} | "
            f"{c.get('crashed', 0)} | {avg:.1f} |"
        )
    if summary["errors"]:
        lines += ["", "## Crashes (last traceback line, count)", ""]
        lines += [f"- {n} x `{msg}`" for msg, n in summary["errors"]]
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--start-at", default=None, help="HH:MM local; default now")
    ap.add_argument("--until", default="07:00", help="HH:MM local")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--max-games", type=int, default=None)
    ap.add_argument("--samples", type=int, default=4)
    ap.add_argument("--nodes", type=int, default=200)
    ap.add_argument("--decision-cap", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=20261102)
    ap.add_argument(
        "--decklist", type=Path, default=None,
        help="shared library file (default: the saved Fish list)",
    )
    args = ap.parse_args(argv)

    from mtg_bot.cards.source import get_active_source
    from mtg_bot.formats.decklist import decklist_names
    from mtg_bot.formats.forgetful_fish import default_decklist_path

    decklist_path = args.decklist or default_decklist_path()
    library, unknown, unreadable = decklist_names(
        decklist_path.read_text(encoding="utf-8"),
        get_active_source().get_printings(),
    )
    if unknown or unreadable or not library:
        raise SystemExit(
            f"saved decklist is not playable: unknown={unknown} "
            f"unreadable={list(unreadable)}"
        )
    start, deadline = window(args.start_at, args.until, dt.datetime.now())
    args.out.mkdir(parents=True, exist_ok=True)
    meta = {
        "started": start.isoformat(timespec="minutes"),
        "deadline": deadline.isoformat(timespec="minutes"),
        "decklist": decklist_path.name,
        "library_size": len(library),
        "samples": args.samples, "nodes": args.nodes,
        "workers": args.workers, "seed": args.seed,
    }
    print(f"waiting until {start:%Y-%m-%d %H:%M}, playing until "
          f"{deadline:%Y-%m-%d %H:%M} -> {args.out}", flush=True)
    while dt.datetime.now() < start:
        time.sleep(min(60.0, (start - dt.datetime.now()).total_seconds()))
    _keep_awake(True)

    rows: list[dict[str, Any]] = []
    games_path = args.out / "games.jsonl"
    if games_path.exists():  # resume: keep counting after earlier games
        rows = [json.loads(line) for line in games_path.open(encoding="utf-8")]
    next_game = len(rows)

    def job(i: int) -> dict[str, Any]:
        return {
            "game": i, "seed": args.seed + 1000 * i,
            "matchup": MATCHUPS[i % len(MATCHUPS)], "library": library,
            "samples": args.samples, "nodes": args.nodes,
            "decision_cap": args.decision_cap,
        }

    ctx = mp.get_context("spawn")
    with ctx.Pool(args.workers) as pool, games_path.open(
        "a", encoding="utf-8",
    ) as out:
        pending = []

        def more_allowed() -> bool:
            if dt.datetime.now() >= deadline:
                return False
            return args.max_games is None or next_game < args.max_games

        while more_allowed() and len(pending) < 2 * args.workers:
            pending.append(pool.apply_async(play_one, (job(next_game),)))
            next_game += 1
        while pending and dt.datetime.now() < deadline:
            done = [p for p in pending if p.ready()]
            if not done:
                time.sleep(1.0)
                continue
            for p in done:
                pending.remove(p)
                row = p.get()
                rows.append(row)
                out.write(json.dumps(row) + "\n")
                out.flush()
                if more_allowed():
                    pending.append(pool.apply_async(play_one, (job(next_game),)))
                    next_game += 1
            _write_summary(args.out, rows, meta)
        pool.terminate()
    _keep_awake(False)
    _write_summary(args.out, rows, meta)
    print(f"done: {len(rows)} games -> {args.out / 'summary.md'}", flush=True)


if __name__ == "__main__":
    main()
