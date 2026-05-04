"""Inspect debug_hangs/*.txt files: list top-K frames per dump.

Usage::

    python scripts/analyze_hangs.py [dir]
"""
from __future__ import annotations

import sys
import re
from pathlib import Path
from collections import Counter


def analyze(dir_path: Path, top_k: int = 6) -> None:
    files = sorted(dir_path.glob("*.txt"))
    print(f"# {dir_path}: {len(files)} dumps")
    leaf_counter: Counter = Counter()
    deep_counter: Counter = Counter()
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        # extract frames of the FIRST thread (the inner game thread)
        first_thread_frames: list[str] = []
        in_first = False
        for line in text.splitlines():
            if line.startswith("Thread 0x"):
                if not in_first:
                    in_first = True
                    continue
                else:
                    break
            if line.startswith("Current thread"):
                break
            if in_first and line.strip().startswith("File "):
                first_thread_frames.append(line.strip())
        print(f"\n=== {f.name} ({len(first_thread_frames)} frames)")
        for L in first_thread_frames[:top_k]:
            short = re.sub(r".*\\src\\mtg_bot\\", "", L)
            short = re.sub(r".*\\site-packages\\", "site/", short)
            short = re.sub(r".*\\Lib\\", "lib/", short)
            print("  ", short)
        if first_thread_frames:
            leaf = first_thread_frames[0]
            leaf_counter[
                re.sub(r".*\\([^\"]+)\", line (\d+) in (\S+)", r"\1:\2 \3", leaf)
            ] += 1
        # Look for the engine_adapter / game.py / turn.py frame closest to the leaf
        for L in first_thread_frames:
            if (
                "src\\mtg_bot\\game" in L
                or "src\\mtg_bot\\turn" in L
                or "src\\mtg_bot\\actions" in L
                or "src\\mtg_bot\\effects" in L
                or "src\\mtg_bot\\cards\\base" in L
            ):
                deep_counter[
                    re.sub(r".*\\src\\mtg_bot\\(.+?)\", line (\d+) in (\S+)", r"\1:\2 \3", L)
                ] += 1
                break
    print("\n# Leaf frame distribution")
    for name, n in leaf_counter.most_common():
        print(f"  {n:3d}  {name}")
    print("\n# First mtg_bot/{game,turn,actions,effects,cards/base} frame distribution")
    for name, n in deep_counter.most_common():
        print(f"  {n:3d}  {name}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        analyze(Path(sys.argv[1]))
    else:
        # default: analyze all subdirs of debug_hangs
        root = Path("debug_hangs")
        for sub in sorted(root.iterdir()):
            if sub.is_dir():
                analyze(sub)
                print()
