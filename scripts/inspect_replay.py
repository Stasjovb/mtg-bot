"""Print a quick summary of a captured replay file.

Use case: you have a directory of replays from a training run and
want to triage which look interesting (long games, weird outcomes,
big eval swings) before opening them in the UI.

Usage::

    python scripts/inspect_replay.py replays/game_seed0_idx0042.json.gz

    # Show eval timeline (one line per snapshot — long output)
    python scripts/inspect_replay.py replays/game_seed0_idx0042.json.gz \\
        --eval-timeline
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mtg_bot.replay import load_replay  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "replay", type=Path,
        help="Path to a .json.gz replay file.",
    )
    parser.add_argument(
        "--eval-timeline", action="store_true",
        help=(
            "Print one row per snapshot showing turn / step / "
            "heuristic_eval(p0) / nn_eval(p0). Long for full games."
        ),
    )
    args = parser.parse_args()

    if not args.replay.is_file():
        sys.exit(f"replay not found: {args.replay}")

    replay = load_replay(args.replay)
    print(f"# {args.replay}")
    print(f"# format_version: {replay.format_version}")
    print(f"# snapshots: {len(replay.snapshots)}")

    if replay.metadata:
        print("# metadata:")
        for key in sorted(replay.metadata.keys()):
            print(f"#   {key}: {replay.metadata[key]}")

    if not replay.snapshots:
        return

    last = replay.snapshots[-1]
    print(
        f"# final state: turn={last.get('turn_number', '?')} "
        f"step={last.get('step', '?')} "
        f"is_over={last.get('is_over', '?')} "
        f"winner_id={last.get('winner_id', '?')} "
        f"is_draw={last.get('is_draw', '?')}"
    )

    # Per-side life trajectory: first vs last.
    first = replay.snapshots[0]
    p0_first = next((p["life"] for p in first.get("players", [])
                     if p.get("id") == 0), None)
    p1_first = next((p["life"] for p in first.get("players", [])
                     if p.get("id") == 1), None)
    p0_last = next((p["life"] for p in last.get("players", [])
                    if p.get("id") == 0), None)
    p1_last = next((p["life"] for p in last.get("players", [])
                    if p.get("id") == 1), None)
    if p0_first is not None and p0_last is not None:
        print(f"# P0 life: {p0_first} -> {p0_last}")
    if p1_first is not None and p1_last is not None:
        print(f"# P1 life: {p1_first} -> {p1_last}")

    # Eval value summary across the game.
    h_evals_p0 = []
    n_evals_p0 = []
    for snap in replay.snapshots:
        h = snap.get("heuristic_eval")
        if isinstance(h, dict) and h.get("p0") is not None:
            h_evals_p0.append(h["p0"])
        n = snap.get("nn_eval")
        if isinstance(n, dict) and n.get("p0") is not None:
            n_evals_p0.append(n["p0"])
    if h_evals_p0:
        print(
            f"# heuristic_eval(p0) range: min={min(h_evals_p0):+.3f} "
            f"max={max(h_evals_p0):+.3f}  start={h_evals_p0[0]:+.3f} "
            f"end={h_evals_p0[-1]:+.3f}"
        )
    if n_evals_p0:
        nn_label = next(
            (s["nn_eval"].get("version")
             for s in replay.snapshots
             if isinstance(s.get("nn_eval"), dict)),
            None,
        )
        print(
            f"# nn_eval({nn_label})(p0) range: "
            f"min={min(n_evals_p0):+.3f} "
            f"max={max(n_evals_p0):+.3f}  start={n_evals_p0[0]:+.3f} "
            f"end={n_evals_p0[-1]:+.3f}"
        )

    if args.eval_timeline:
        print()
        print(
            f"{'idx':>4}  {'turn':>4}  {'step':<22}  "
            f"{'h(p0)':>7}  {'n(p0)':>7}"
        )
        for idx, snap in enumerate(replay.snapshots):
            t = snap.get("turn_number", "?")
            s = snap.get("step", "?")
            h = snap.get("heuristic_eval", {})
            n = snap.get("nn_eval", {})
            h_p0 = h.get("p0") if isinstance(h, dict) else None
            n_p0 = n.get("p0") if isinstance(n, dict) else None
            h_str = f"{h_p0:+.3f}" if isinstance(h_p0, (int, float)) else "-"
            n_str = f"{n_p0:+.3f}" if isinstance(n_p0, (int, float)) else "-"
            print(f"{idx:>4}  {t:>4}  {str(s):<22}  {h_str:>7}  {n_str:>7}")


if __name__ == "__main__":
    main()
