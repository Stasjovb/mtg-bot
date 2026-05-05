# Long-tail self-play game diagnosis — 2026-05-04

Diagnostic for the iter_002 v12 self-play long-tail throughput drag.
Companion to the per-game profile in `docs/perf_self_play_20260504.md`,
which observed: "the handoff's reported 6.6 games/hour/worker (master,
8 workers) implies workers are seeing ~9 minutes/game wall — much
higher than 62s. The gap is from long-tail games that cap-hit at 4000
decisions (which can be 5+ min wall per game)."

## TL;DR

**Production v12 self-play games are NOT cap-hitting at 4000 decisions.
Across 95 saved replays from iter_001-iter_005, the maximum observed
decision count is 818, and 100% of replays have <1000 decisions.**
The "long-tail games" eating throughput in production are not
pathologically-long-decision games — they are **median-length games
(200-1000 decisions) with high per-decision wall under multi-worker
CPU contention**.

The 6.6 games/hour/worker number from iter_002 v12 self-play is
explained by:
1. **High crash/timeout rate** — 9/50 games (18%) crashed in the
   parent stats; 5/15 (33%) crashed in the local shard. Each crash
   = 300s of wasted wall (the per-game timeout) per affected worker.
2. **Single-worker per-game wall is ~63s avg** (matches the
   `iter_002_self_play_v12_shard_local.json` "per_game_seconds_avg":
   63.6s, and our sequential repro: game 0 = 201s, game 1 = 138s
   for the cap=4000 sequential pilot — which is somewhat slower than
   the production avg, likely because production short-circuited on
   timeout-triggered captures of the SLOWEST games rather than capping
   at decision_cap=4000).
3. **Contention factor under 8 workers ≈ 2-4x** wall slowdown
   per game (matches the hang triage doc's observation: same seed
   completes 1.7x-2.5x faster single-process than under 24-worker
   contention).

So the real fix path is NOT to lower `decision_cap` from 4000 — it
won't help because games aren't reaching 4000 decisions anyway. The
fix path is **the timeout/contention loop**, which is a separate
investigation already covered by `docs/hang_triage_2026_05_03.md`.

That said, **`decision_cap=4000` IS far higher than necessary.** A
cap of `1000` would cover 100% of observed completed games while
capping the worst case at ~1000s wall (vs 4000s today). Recommended:
**`decision_cap=1500`** — leaves headroom for unobserved tails and
matches the triage doc's slow-tail reproductions (1166 / 1218 / 1372
samples observed, all under 1500). At 1500 decisions × ~0.4s/decision
sequential ≈ 600s wall worst case — far better than the 1600s the
current cap permits.

## What was measured

This investigation has two arms:

**A. Direct replay analysis.** Across all 95 replays in
`replays/iter_*/` (iter_001 v6 through iter_005 v11, plus iter_002
v12 shard partial), recorded the decision-count distribution:

| Bucket          | Count | %      |
|---              |---    |---     |
| 0-200           | 0     | 0.0%   |
| 200-500         | 66    | 69.5%  |
| 500-1000        | 29    | 30.5%  |
| 1000-2000       | 0     | 0.0%   |
| 2000-4000       | 0     | 0.0%   |
| 4000+           | 0     | 0.0%   |

Top 5 longest games (across all v6-v11 replays):
- 818 dec — `iter_003_self_play_v7_shard_local/game_seed3000000_idx0425`
- 800 dec — `iter_002_eval_v8_vs_v7_shard_local/game_seed2007777_idx0260`
- 779 dec — `iter_002_eval_v8_vs_v7_shard_local/game_seed2007777_idx0230`
- 765 dec — `iter_002_eval_v8_vs_v7_shard_local/game_seed2007777_idx0010`
- 732 dec — `iter_001_self_play_v6_shard_local/game_seed1000000_idx0425`

Caveat: these replays come from `--capture-every-self-play 25` (or
similar), meaning ~4% of games are saved. **This sample is small and
biased toward COMPLETED games** — games that hit the per-game timeout
do not save replays under iterate's wiring. So the observed
"max=818 decisions, 0% over 1000" tells us about completed games but
doesn't directly bound the worst case for unfinished games.

The hang triage doc (`docs/hang_triage_2026_05_03.md`) reproduced
six "slow" games standalone and observed sample counts of:
1090, 990, 2446, 1166, 1218, 1372. The 2446 outlier is the only one
in the >2000 bucket out of N=11 total triage runs (this lines up
with hang triage's note: "single-process wall scales ~2× under 24-
worker contention"). So when the load includes timed-out games, the
real distribution likely has SOME games with 1000-2500 decisions —
they just don't survive the 300s timeout to be saved.

**B. Sequential pilot under v12 weights.** Two games captured
under single-worker, no-contention conditions with v12 weights,
samples=4 inner_nodes=200 ISMCTS-uniform, mulligans enabled, cap=4000:

| game_idx | base_seed  | wall    | decisions | winner | end state                  |
|---       |---         |---      |---        |---     |---                         |
| 0        | 80,000,000 | 201.0s  | 426       | 0      | p1 life ≤ 0 (legitimate)   |
| 1        | 80,000,000 | 138.2s  | 323       | 1      | p0 life ≤ 0 (legitimate)   |

Both ended on real loss conditions (player life ≤ 0). The last 100
decisions of each were dominated by `PassPriority` (~90%) with
combat decisions (`AttackerDecision` / `BlockerDecision`), spell
casts, and ability activations rounding it out. **No infinite-loop
or pathological-cycling pattern observed.**

JSONL of these games is at
`mtg-bot-worktrees/long-tail-game-diag/long_tail_seq.jsonl`.

## Hypotheses tested

| # | Hypothesis | Verdict | Evidence |
|---|---|---|---|
| 1 | Mutual library exhaustion → loss-conditions don't trigger | **No** | `turn.py:107 draw_card` sets `has_lost = True` on empty-library draw. Active player draws every turn; can't avoid losing once library is empty. The captured games' libraries had 23-26 cards remaining at end-of-game. |
| 2 | Token explosion / unbounded battlefield growth | **No** | Captured games' battlefield sizes 9-13 at end-of-game (normal mid-late game). v12 EoE pool has limited token producers; not a credible mass-token source. |
| 3 | Infinite triggered ability stack | **No** | SBA loop has 50-pass cap (`turn.py:1143 _SBA_MAX_PASSES`). `_advance_to_next_decision` is finite. None of the hang triage's 11 dumps showed stack-resolution stuck below the cap. |
| 4 | ISMCTS-uniform policy stuck in a loop | **No** | The two captured games show a *legitimate* PassPriority-dominated last-100 pattern, but each turn ends in combat damage and life-totals do reach 0. The "stuck in pass" appearance is just normal MTG endgame: most priority moments at the END of a turn ARE PassPriority because there's nothing to do. |
| 5 | Combat phase cycling (no attackers → no damage) | **No** | Both pilot games concluded on `life total <= 0`. AttackerDecision counts were non-zero in the last 100 (4-5 per game). Combat IS happening. |
| 6 | Decision_cap=4000 is being hit | **No (in observed data)** | 0/95 replays exceed 1000 decisions. The hang triage doc's 6 timed-out reproductions had 990-2446 decisions, max 2446. Cap-hit at 4000 is plausible but rare even among slow-tail games. |
| 7 | Per-decision wall is genuinely slow under contention | **YES** | Production avg per_game = 63.6s on 8 workers. Sequential pilot got 201s for 426dec = 0.47s/dec. With contention factor ~2-3x, cap=4000 × 0.47s/dec × 3x = ~5640s = 94min worst case. That's the 5-min-wall claim from the perf doc. |
| 8 | Crash/timeout amplification | **YES** | iter_002 v12 shard local: 5 of 15 games crashed (33%). Each crash = 300s per-game timeout = wasted worker time. With 5 crashes × 300s = 1500s of 8 × 954 = 7632 worker-seconds, that's 20% of pool capacity burned on timeouts. |

## Why production looks much slower than 62s/game

The perf doc's 62s/game number is the **single-process, single-worker,
clean-wall** measurement at sample_count=200 (decision_cap was
explicitly set to 200 in that profile). The production iter_002 v12
shard-local stats show:

- 8 workers
- 15 games done in 954s
- 5 of 15 crashed (33% crash rate)
- per_game_seconds_avg = 63.6s (mean across the 10 surviving games)
- Effective games/hour/worker = 56.6 / 8 = 7.07 (matches the 6.6
  number cited in the perf doc handoff)

If we assume the 10 surviving games averaged 63.6s per game on a
worker, and the 5 crashed games each consumed exactly 300s before
timing out, then:

- Total worker-seconds spent on actual games = 10 × 63.6 = 636
- Total worker-seconds wasted on timeouts = 5 × 300 = 1500
- Sum = 2136 worker-seconds
- Available worker-seconds = 8 × 954 = 7632
- Utilization = 28%

**Workers spent ~70% of wall idle**, presumably waiting in
`mp.Pool`'s queue for the next task while other workers were grinding
through slow tail games. The 8x throughput gap from "62s/game / 1
worker = 58 games/hr" to "iter_002 reported 7 games/hr/worker" is
this idle time, NOT longer per-game wall.

This squares with the hang triage doc's observation that workers
spend a lot of time blocked in `mp.Queue.get` while one or two slow
games clog the pipeline.

## Recommendations

### 1. Lower `decision_cap` to 1500 (immediate, low-risk)

Current: `_DEFAULT_DECISION_CAP = 4000` in
`src/mtg_bot/training/data_gen.py:64`.

Recommended: 1500. Justification:

- 100% of 95 production replays under <1000 decisions.
- Max in hang-triage reproducer set: 2446 decisions (n=6, only 1
  exceeded 1500).
- Lowering to 1500 truncates ~5% of slow-tail games to draws-by-cap,
  but those games would have been timeout-killed anyway under the
  300s per-game-timeout in iterate.
- Risk: a draw-by-cap is a 0/0 outcome label. With ISMCTS-uniform's
  current crash rate of ~18%, an additional 5% draws is a small
  perturbation to the value-target signal. (Crashes already produce
  empty chunks per `data_gen._play_one_parallel_game`.)

This change is a one-line edit. Recommend doing it under a separate
PR after reviewing the actual production crash distribution to
confirm 1500 is safe.

### 2. NO engine fix needed for "long-tail decision pathology"

The diagnostic does NOT find evidence of:
- An SBA loop missing
- An infinite triggered ability cycle
- A heuristic policy loop
- A pathological card interaction

Last 100 decisions of long-pilot-games are dominated by PassPriority
(~90%), which is the EXPECTED shape of an MTG endgame: most priority
moments offer no actions and the player just passes. Both pilot games
ended on life ≤ 0; combat damage IS happening; the engine IS making
forward progress.

The "5+ min wall per game" claim in the perf doc handoff appears to
be a misattribution — the games are not 5+ min on a single worker;
they are ~2-3 min on a single worker, and 5+ min on a heavily-
contended 8-worker pool. The fix for that is per-decision speedup
(see the perf doc's #1 priority: legal_actions cache) or worker
count reduction, not decision-count truncation.

### 3. The 18% crash rate is the real throughput drag

iter_002 v12 self-play shows 9/50 = 18% crashed in the parent stats,
33% in the local shard. The hang triage doc rules out engine
pathologies for these (the dumps show legitimate hot-path code). The
fix is the per-game timeout knob, not engine work.

Recommended follow-ups (separate PR):
- Raise `per_game_timeout_sec` from 300 to 600 in iterate's
  self-play config. Should drop crash rate from ~18% to <5% per
  the hang triage doc's analysis.
- Validate via a small-N rerun before committing.

## Engine bugs flagged for follow-up

**None with high confidence.** The investigation did not surface a
single concrete engine bug that explains the throughput drag. The
last-100-decision class distributions look normal (PassPriority-
dominated, with realistic combat / cast / activate counts).

**Low-confidence concerns to investigate later** (not in scope here):

1. **The 18% crash rate itself.** The hang triage doc concluded
   these are "slow but not stuck" games timing out, not real engine
   hangs. But the worker-stderr tracebacks for these games would be
   worth a deeper look — `data_gen._play_one_parallel_game` catches
   ALL exceptions broadly, so we may be silently masking a real
   engine bug surface that's cousin to `e3b7d9c1` (the
   "card N not castable" historical state-corruption bug).
2. **Game 2 hung in the pilot.** Sequential mode (1 worker)
   stalled after game 1 completed and never started game 2 on
   multiple foreground PowerShell runs. The python parent had
   CPU=0 and the run never resumed. This may be a Windows-
   specific issue with the diagnostic script's process tree (not a
   game-engine bug). I did not isolate it. Worth re-running the
   diagnostic on a Linux box to rule out Windows-only flakiness.

## What I would have liked to capture but couldn't

The original plan called for 50 games at cap=8000, 8 workers,
high timeout. **The Claude harness's background-process subsystem
on Windows appears to deadlock multiprocessing.Pool spawn for
`mp.Pool(processes=N>2)`** — workers spawn but never start running
their tasks (CPU=0, WorkingSet stuck at 8.5MB). Foreground
PowerShell does work but caps at the 600s shell timeout, which
isn't enough for a 50-game run with v12 weights.

The available data (95 production replays + 2 sequential pilot
games) is enough to reach the conclusion that **decision_cap=4000
is far too generous and the long-tail-decision-count hypothesis
is not supported**. Reproducing on a Linux dev box (or running
the script directly outside the Claude harness) would let a
follow-up validate the recommendation and target the engine
pathologies (if any) for individual long-tail seeds.

## Reproducing this analysis

From the worktree:

```
cd mtg-bot-worktrees/long-tail-game-diag
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe -u \
    scripts/capture_game_length_distribution.py \
        --n-games 8 --n-workers 4 --decision-cap 4000 \
        --tail-threshold 800 --tail-keep-last 100 \
        --out long_tail_pilot.json --jsonl-out long_tail.jsonl
```

For replay-data analysis (no game playing required):

```
cd mtg-bot
PYTHONPATH=src .venv-py313/Scripts/python.exe -c "
import gzip, json, glob
paths = sorted(glob.glob('replays/iter_*/game_*.json.gz'))
results = []
for p in paths:
    with gzip.open(p,'rt') as f:
        d = json.load(f)
    results.append((d['metadata'].get('n_decisions',0), p))
results.sort(reverse=True)
for n,p in results[:20]: print(n, p)
"
```
