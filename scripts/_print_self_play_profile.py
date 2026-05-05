"""Quick analyzer for a saved cProfile dump from
``scripts/profile_self_play_game.py``.

Re-runs the same category roll-up + top-N tables on a previously
saved ``.prof`` file. Useful when the profile was successfully
captured but the printing pass crashed (the latter happened during
the perf-analysis-deep run on a bare ASCII Windows codepage that
balked at the ~ character in the summary). Decoupling the analysis
phase from the recording phase means we never have to re-run a
60+s game just to format its numbers.

Usage::

    PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \\
        scripts/_print_self_play_profile.py path/to/file.prof
"""

from __future__ import annotations

import pstats
import sys
from io import StringIO
from pathlib import Path

# Make local source tree importable when run from the repo root
# without `pip install -e .`.
_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _format_call_stats(
    stats: pstats.Stats, label: str, name_substring: str,
) -> str:
    rows: list[tuple[str, int, float, float]] = []
    for func, (cc, nc, tt, ct, _) in stats.stats.items():
        filename, _, funcname = func
        full = f"{filename}:{funcname}"
        if name_substring in full or name_substring == funcname:
            rows.append((full, nc, tt, ct))
    if not rows:
        return f"  {label}: <no matches for {name_substring!r}>\n"
    total_calls = sum(r[1] for r in rows)
    total_tt = sum(r[2] for r in rows)
    total_ct = sum(r[3] for r in rows)
    return (
        f"  {label}: calls={total_calls:>10d}  "
        f"tottime={total_tt*1000:>10.1f}ms  "
        f"cumtime={total_ct*1000:>10.1f}ms\n"
    )


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: _print_self_play_profile.py <prof_path> [top]")
        sys.exit(2)
    prof_path = Path(sys.argv[1])
    top = int(sys.argv[2]) if len(sys.argv) >= 3 else 40

    print(f"# Profile dump: {prof_path}")

    print("\n" + "=" * 78)
    print(f"# Top {top} by cumtime")
    print("=" * 78)
    cum_io = StringIO()
    cum_stats = pstats.Stats(str(prof_path), stream=cum_io)
    cum_stats.sort_stats("cumulative").print_stats(top)
    print(cum_io.getvalue())

    print("\n" + "=" * 78)
    print(f"# Top {top} by tottime")
    print("=" * 78)
    tot_io = StringIO()
    tot_stats = pstats.Stats(str(prof_path), stream=tot_io)
    tot_stats.sort_stats("tottime").print_stats(top)
    print(tot_io.getvalue())

    print("\n" + "=" * 78)
    print("# Category roll-up (ms = milliseconds)")
    print("=" * 78)
    rollup_stats = pstats.Stats(str(prof_path))
    categories = [
        # ---- search-side ----
        ("ISMCTS.choose_with_visits",
         "ismcts.py:choose_with_visits"),
        ("ISMCTS._select_and_expand",
         "ismcts.py:_select_and_expand"),
        ("ISMCTS._evaluate_leaf",
         "ismcts.py:_evaluate_leaf"),
        ("ISMCTS._backprop",
         "ismcts.py:_backprop"),
        ("ISMCTS._fresh_determinization",
         "ismcts.py:_fresh_determinization"),
        ("ISMCTS._stamp_prior",
         "ismcts.py:_stamp_prior"),
        ("ISMCTS._grow_union_mask",
         "ismcts.py:_grow_union_mask"),
        # ---- determinize / clone / info_set ----
        ("determinize (root determinizer)",
         "determinize.py:determinize"),
        ("info_set_key",
         "info_set.py:info_set_key"),
        ("clone (engine GameState)",
         "game.py:clone"),
        ("clone (adapter)",
         "engine_adapter.py:clone"),
        # ---- engine work ----
        ("apply (adapter)",
         "engine_adapter.py:apply"),
        ("legal_decisions (adapter)",
         "engine_adapter.py:legal_decisions"),
        ("legal_actions (engine)",
         "legal.py:legal_actions"),
        # ---- NN ----
        ("NNEvaluator.__init__",
         "nn_evaluator.py:__init__"),
        ("NNEvaluator.evaluate_logits",
         "nn_evaluator.py:evaluate_logits"),
        ("NNEvaluator.batch_evaluate_logits",
         "nn_evaluator.py:batch_evaluate_logits"),
        ("NNEvaluator.batch_evaluate",
         "nn_evaluator.py:batch_evaluate"),
        ("NNEvaluator.batch_evaluate_with_policy",
         "nn_evaluator.py:batch_evaluate_with_policy"),
        ("torch.load",
         "torch/serialization.py:load"),
        ("torch forward (Module __call__)",
         "torch/nn/modules/module.py:_call_impl"),
        ("extract_features",
         "features.py:extract_features"),
        # ---- features / encoding / replay ----
        ("legal_action_mask",
         "action_encoding.py:legal_action_mask"),
        ("encode (action_encoding)",
         "action_encoding.py:encode"),
        ("ReplayRecorder.record",
         "replay_capture.py:record"),
        ("serialize_state",
         "serialize.py:serialize_state"),
        # ---- top-level ----
        ("_play_one_game_recording",
         "data_gen.py:_play_one_game_recording"),
        ("_generate_one_game_data",
         "data_gen.py:_generate_one_game_data"),
        ("setup_game",
         "simulate.py:setup_game"),
    ]
    for label, needle in categories:
        sys.stdout.write(_format_call_stats(rollup_stats, label, needle))


if __name__ == "__main__":
    main()
