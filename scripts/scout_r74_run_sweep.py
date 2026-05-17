"""Round-74 post-spell-admit divergence-sweep driver.

Invokes the UNMODIFIED `bench_trajectory_parity.main()` (no production
/ harness / bench-script logic touched — this is an orchestration
wrapper that only passes argv, exactly the round-68/71 `tmp/bench_*`
sweep-driver precedent) once per (band, seed-offset) batch, at the
cap-120 default, over the stratified dense spell-carrier archetypes
the scout picked spanning the full 130k pool. Each band runs at a
DISTINCT seed offset so the 5 disjoint index windows × 5 disjoint
seed-offset pairs give a wide, fully disjoint grid where the 5
newly-bench-admitted spell cards are actually cast.

Writes per-batch JSON to tmp/bench_r74_<band>.json (gitignored) and a
roll-up to tmp/bench_r74_rollup.json.
"""

from __future__ import annotations

import json
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
_REPO = _HERE.parent  # the worktree root — holds the `tests` package
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
# The bench's spell-cast path lazily does
# `from tests.parity._picker_shims import _PickFirstLegalTargetAgent`
# (bench_trajectory_parity.py:270) ONLY when a bridge-admitted spell is
# about to be cast — the campaign-wide first-legal target convention.
# Under pytest the repo root is on sys.path so `tests` resolves; a
# STANDALONE bench invocation from a worktree has only `src` (the
# bench's own bootstrap), so EVERY spell-cast game throws
# ModuleNotFoundError('tests') → FAIL_EXCEPTION instead of exercising
# the cast. This is a HARNESS-INVOCATION gap, not an engine
# divergence: it is exactly why no prior standalone broad sweep ever
# actually cast the 5 newly-admitted spell cards. Putting the repo
# root on sys.path here (an orchestration WRAPPER, not a bench-script
# change — the round-68/71 tmp/bench_* sweep-driver precedent) makes
# the bench's existing spell-cast path reachable, byte-for-byte
# identical to how the pytest gate already drives it.
if _REPO.is_dir() and str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import bench_trajectory_parity as bench  # noqa: E402

TMP = _HERE.parent / "tmp"

# 5 disjoint index-band batches the scout picked (dense spell-carriers,
# all 5 spell cards represented in each band), each at a DISTINCT
# seed-offset pair → 5 disjoint windows × 5 disjoint seed offsets.
BATCHES = [
    # (band, archetypes-csv, seeds)
    ("lo",
     "2,35,70,111,160,196,216,249,268,296,330,357,384,531,553,578,"
     "720,815,1007,1126,1286,1590", "0-2"),
    ("mid1",
     "26000,26055,26098,26140,26158,26196,26255,26297,26319,26361,"
     "26418,26493,26518,26579,26695,26826,26947,26996,27151,27402,"
     "27916,28379,28711,29469,29703", "3-5"),
    ("mid2",
     "52001,52021,52059,52121,52150,52177,52229,52283,52329,52374,"
     "52402,52445,52463,52487,52518,52595,52646,52776,52859,53746,"
     "53831,54024", "6-8"),
    ("mid3",
     "78003,78034,78054,78097,78128,78170,78213,78230,78256,78306,"
     "78339,78388,78410,78452,78475,78586,78668,78760,78900,79213,"
     "79437,79560,79689,79920", "9-11"),
    ("hi",
     "104000,104035,104075,104091,104130,104147,104167,104201,"
     "104240,104271,104341,104380,104425,104465,104506,104591,"
     "104621,104676,104738,104813,104962,105070,105202,105340,"
     "105548,105730,106161", "12-14"),
]


def main() -> int:
    rollup = []
    for band, archs, seeds in BATCHES:
        out = TMP / f"bench_r74_{band}.json"
        sys.stderr.write(
            f"\n========== batch {band}: archs={archs[:60]}... "
            f"seeds={seeds} ==========\n"
        )
        sys.stderr.flush()
        rc = bench.main([
            "--archetypes", archs,
            "--seeds", seeds,
            # cap-120 DEFAULT — pass explicitly to be unambiguous; it is
            # the round-72 argparse default, no override.
            "--max-turns", "120",
            "--combat-strategy", "attack_all",
            "--mulligans", "0",
            "--json-out", str(out),
            "--verbose",
        ])
        if rc != 0:
            sys.stderr.write(f"[driver] batch {band} returned rc={rc}\n")
        payload = json.loads(out.read_text(encoding="utf-8"))
        s = payload["summary"]
        rollup.append({"band": band, "seeds": seeds, "summary": s})

    # Roll up.
    agg = {
        "total_games": 0, "passes": 0, "fail_divergence": 0,
        "fail_timeout": 0, "archetype_filtered": 0, "fail_exception": 0,
        "total_elapsed_seconds": 0.0,
    }
    div_shapes: dict[str, int] = {}
    for r in rollup:
        s = r["summary"]
        for k in agg:
            agg[k] += s.get(k, 0)
        for shape, cnt in s.get("divergence_shape_histogram", {}).items():
            div_shapes[shape] = div_shapes.get(shape, 0) + cnt
    (TMP / "bench_r74_rollup.json").write_text(
        json.dumps(
            {"batches": rollup, "aggregate": agg,
             "divergence_shapes": div_shapes},
            indent=2, default=str,
        ),
        encoding="utf-8",
    )
    sys.stdout.write("\n" + "=" * 60 + "\nROUND-74 ROLL-UP\n" + "=" * 60 + "\n")
    for r in rollup:
        s = r["summary"]
        sys.stdout.write(
            f"  {r['band']:<5} seeds={r['seeds']:<6} "
            f"games={s['total_games']:3d} PASS={s['passes']:3d} "
            f"DIV={s['fail_divergence']:2d} "
            f"TIMEOUT={s['fail_timeout']:3d} "
            f"FILT={s['archetype_filtered']:2d} "
            f"EXC={s['fail_exception']:2d}\n"
        )
    sys.stdout.write(
        f"\n  TOTAL games={agg['total_games']} PASS={agg['passes']} "
        f"DIV={agg['fail_divergence']} TIMEOUT={agg['fail_timeout']} "
        f"FILT={agg['archetype_filtered']} EXC={agg['fail_exception']} "
        f"wall={agg['total_elapsed_seconds']:.1f}s\n"
    )
    if div_shapes:
        sys.stdout.write("\n  DIVERGENCE SHAPES:\n")
        for shape, cnt in sorted(div_shapes.items(), key=lambda kv: -kv[1]):
            sys.stdout.write(f"    {cnt:4d}  {shape}\n")
    else:
        sys.stdout.write("\n  0 FAIL_DIVERGENCE across all batches\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
