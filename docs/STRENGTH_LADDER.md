# Strength ladder (`mtg_bot ladder`)

**This file is the project's single absolute-strength table.** Every
other eval in the repo is relative ("new vs current champion" in the
`iterate` acceptance gate, `mtg_bot eval --new X --old Y`). Those tell
you whether a candidate beat its predecessor; they never tell you how
strong anything is on a fixed scale, and before this tool the
production NN lineage had never been played against the two fixed
yardsticks the project ships (`random`, `heuristic`). Paste ladder
results here as they are produced so there is exactly one place to
look.

## What it does

`mtg_bot ladder` is a **local** (`multiprocessing.Pool`, no
coordinator / worker daemons / runs.db) round-robin between any mix of:

- `random` — uniformly random legal decision (`RandomChoice`), the
  Elo anchor (fixed at 0).
- `heuristic` — PIMC with the default `HeuristicConfig()` evaluator at
  the ladder's `--nodes` / `--samples` (the same opponent
  `iterate._eval_match` falls back to when there is no old NN).
- any registered version label under `trained_weights/` (`v5`,
  `v13s`, ...). Architecture, trunk shape and action-encoding version
  come from the version's `metadata.json` via `Registry`, exactly as
  the acceptance gate threads them into `NNPimcConfig`; the
  `structured` architecture's trunk hparams are discovered from the
  sibling metadata file inside each worker.

Each pair plays `--games` seat-alternated games through the same
`run_match_parallel(alternate_seats=True)` path the gate uses, so seat
bias cancels. Every pair uses the same base `--seed`, i.e. the same
sequence of deck matchups (common random numbers across pairs).

Outputs (in `--out`, default `ladder_runs/<UTC timestamp>/`):

- `results.json` — config + every completed pair (`wins_a`, `wins_b`,
  `draws`, `timeouts`, `crashed`, `mean_decisions`, `wall_seconds`,
  `seed`). Written atomically after **each** pair, so a killed run
  loses at most the pair in flight. `--resume <dir>` skips pairs
  already there (in either orientation) and rebuilds the report.
- `ladder.md` — the Elo table with bootstrap 95% CIs, the pairwise
  win-rate matrix with Wilson 95% CIs, per-pair detail, and the config
  (nodes, samples, games, seed, git commit). Also printed to stdout.

## Running it

```bash
PYTHONPATH=src .venv-py313/Scripts/python.exe -m mtg_bot.cli ladder \
    --agents random heuristic v5 v13s \
    --games 500 --nodes 200 --samples 4 --workers 30 --seed 0
```

Useful flags:

| flag | meaning |
|---|---|
| `--agents A B ...` | participants (required unless `--resume`) |
| `--pairs all` / `--pairs a:b,c:d` | round robin (default) or explicit pairs |
| `--games N` | games per pair, seat-alternated (default 500) |
| `--nodes` / `--samples` | search depth, shared defaults from `mtg_bot.cli._common` (200 / 4) |
| `--workers N` | pool size (default `cpu_count - 2`) |
| `--seed S` | base seed (deck sampling + strategy RNGs) |
| `--per-game-timeout-sec` | default `3 * nodes` seconds, as every other subcommand |
| `--registry-root` | default `trained_weights` |
| `--out DIR` / `--resume DIR` | where results go / continue an earlier run |
| `--timeouts-as-draws` | see "Scoring" below |
| `--bootstrap-resamples` | Elo CI resamples (default 200) |

A quick sanity run (a minute or two):

```bash
... ladder --agents random heuristic v13s --games 4 --nodes 8 --samples 1 --workers 2
```

## Scoring

- **Default**: a timed-out or crashed game contributes no signal and
  is dropped from the denominator. This matches the acceptance gate
  (`MatchStats.win_rate`).
- **`--timeouts-as-draws`**: a timed-out game is scored 0.5 / 0.5. A
  wall-clock timeout cannot be attributed to either player, so there
  is deliberately no "timeouts as losses" mode. Crashed games are
  always excluded (engine bugs, not play).
- Draws (decision-cap games) are always 0.5 / 0.5.

Timeouts and crashes are still counted and shown in the matrix
(`t<N>` / `c<N>`) so a pair that lost half its games to timeouts is
visibly untrustworthy.

## Elo

Bradley-Terry maximum likelihood (Hunter's MM iteration) on the
logistic scale, `P(a beats b) = 1 / (1 + 10^((r_b - r_a) / 400))`,
draws as half a win each way. `random` is anchored at 0 (the first
listed agent if `random` is absent). One virtual draw per played pair
keeps an agent that never scores at a finite rating; at ladder game
counts the shift is well under a point. The 95% CI is a percentile
bootstrap: within each pair the scored games are resampled with
replacement, the fit is redone, and the 2.5 / 97.5 percentiles are
reported. If the pairing graph is disconnected the report says so —
ratings across components are not comparable.

Numbers are only comparable within one depth setting: an Elo measured
at `--nodes 8` is not the same scale as one at `--nodes 200`. Record
the config with every table below.

## Results

Paste each run's `ladder.md` Elo table + config here, newest first.

### 2026-09-25 -- v8, the heuristic warm-start net (nodes 100 / samples 2)

`ladder_runs/s2_v8/`, 200 games/pair. v8 = structured net trained on 6,000
heuristic-PIMC self-play games (nodes 400 / samples 2) with post-hoc value
calibration (see docs/SCALING_DIAGNOSTICS.md D4/D5).

| rank | agent | Elo | 95% CI | games | score |
|---:|---|---:|---|---:|---:|
| 1 | heuristic | +470 | [+397, +572] | 199 | 76.4% |
| 2 | **v8** | **+267** | [+213, +343] | 399 | 53.1% |
| 3 | random | +0 | -- | 200 | 17.5% |

Pairwise: heuristic vs v8 152-47 (v8 23.6%); random vs v8 35-165 (v8 82.5%).
For comparison the previous best NN (v5, self-play from random init) LOST
to random 68-132 and took 9/200 from the heuristic. Baseline from 09-23:
heuristic +407, v13s +30, random 0 (different game sample; Elo anchored
to random each run, so compare within a run).

### 2026-09-23 -- first absolute-strength table (nodes 100 / samples 2)

Commit `5c1bc306`, `ladder_runs/prod_n100s2/` (full report snapshot:
`docs/STRENGTH_LADDER_2026-09-23_n100s2.md`). 200 games/pair, seat
alternated, 20 workers, 900 s per-game timeout, seed 0. Depth is HALF
the production self-play budget (nodes 200 / samples 4 was attempted
first as `prod_2026-09-23/` but ~1 in 10 v13s games hit the 600 s
timeout, biasing the sample, so it was killed after the
random-vs-heuristic pair: 29-467).

| rank | agent | Elo | 95% CI | games | score |
|---:|---|---:|---|---:|---:|
| 1 | heuristic | +407 | [+342, +469] | 399 | 90.7% |
| 2 | v13s | +30 | [-12, +74] | 398 | 32.2% |
| 3 | random | +0 | [+0, +0] | 399 | 27.1% |

Pairwise (row's W-L): random vs heuristic 18-182; random vs v13s
90-109 (t1); heuristic vs v13s 19-180 (c1).

**Reading:** the production champion `v13s` (end of the
schema-1 lineage, ~7M training rows, ~4 months of training) is
statistically indistinguishable from random (CI includes 0) and loses
90% of games to the hand-written heuristic evaluator at equal search
budget. The whole pre-2026-09 lineage carried no measurable learning
signal; see the 2026-09-22 worklog entry for the root causes that
`feature/learning-fixes` addressed. Every future snapshot goes on this
ladder against the same three references.


Tool validation only (NOT a result): 2026-09-23, commit 779a87b4,
`--agents random heuristic v13s --games 4 --nodes 8 --samples 1
--workers 2` loaded all three participants (v13s = structured /
canonical_v2 via the registry) and played 12 games in ~20s with 0
timeouts / 0 crashes. At that depth the ordering is noise; a 16-game
`random` vs `heuristic` check at `--nodes 32` gave heuristic 12-4.

### 2026-09-25 -- v9, v10, v11: three always-promote AlphaZero cycles from v8 (nodes 100 / samples 2)

`ladder_runs/s2_v9/`, `s2_v10/`, `s2_v11/`, 200 games/pair each. Each cycle:
1,500 NN-PIMC self-play games driven by the previous version, trained on the
newest 6,000 shards (heuristic corpus displaced progressively), LR 3e-4,
always-promote. Cycles 7-8 (v9, v10) also contained ~40% games from the Mac
worker running pre-calibration code (quarantined afterwards); cycle 9 (v11)
is desktop-only and clean.

| version | Elo | 95% CI | vs heuristic | vs random | held-out value corr (calibrated) |
|---|---:|---|---|---|---:|
| v8 (warm start) | +267 | [+213, +343] | 47-152 (23.6%) | 165-35 (82.5%) | 0.35 |
| v9 | +199 | [+150, +262] | 45-154 (22.6%) | 152-48 (76.0%) | 0.29 |
| v10 | +185 | [+126, +239] | 49-151 (24.5%) | 149-51 (74.5%) | 0.26 |
| v11 | +150 | [+103, +199] | 36-164 (18.0%) | 141-59 (70.5%) | 0.30 |

Reading: monotone Elo decay as NN-play games replace heuristic games in the
window. v11's trainer early-stopped at epoch 6 with best = epoch 1, and its
calibrated corr (0.30) still does not beat the trivial life-differential
baseline (0.34) -- the value head learns nothing beyond "who is ahead on
life" from NN-play outcomes. Response: `current_best` reset to v8, the
3,345 NN-play shards from cycles 7-9 moved to `iterate_data_s2_nnplay_v8_v10/`,
and the schedule switched to `scripts/s2/run_mixed_cycles.sh` (1,500
heuristic games + 1,500 v8-driven NN games per cycle, gated promotion
`S2_ACCEPT=0.55`) so the window stays heuristic-majority.

### 2026-09-26 -- v12 (mixed cycle) and v13 (heuristic-only, 2x data)

| version | training window | Elo | vs heuristic | vs random | held-out value corr (calibrated / life-diff baseline) |
|---|---|---:|---|---|---:|
| v12 | 4,500 heuristic + 1,500 v8-driven NN games; rejected by the 55% arena vs v8 (136-161) | +181 | 45-153 (22.7%) | 148-52 (74.0%) | 0.316 / 0.336 |
| v13 | **12,207 heuristic games only** (no NN-play data), store on E: | +199 | **53-147 (26.5%)** | 152-48 (76.0%) | **0.323 / 0.299** |

v13 is the first net whose value head beats the trivial life-differential
baseline on held-out rows, and the best result vs heuristic so far -- but
its vs-random score is below v8's (165-35), and single 200-game pairs put
v8 and v13 well inside each other's CIs (the heuristic anchor itself
bounces +375..+470 across runs). Decisive comparison: one ladder run with
`v8:v13`, `heuristic:v8`, `heuristic:v13` at 300 games/pair
(`ladder_runs/s2_v8_vs_v13/`, results below when done).

**Head-to-head (2026-09-26, `ladder_runs/s2_v8_vs_v13/`, 300 games/pair, one run, heuristic anchored at 0):**

| pair | result |
|---|---|
| v8 vs v13 | 146-153-1 (dead even) |
| heuristic vs v8 | 237-61-1 (v8 20.5%) |
| heuristic vs v13 | 224-75-1 (v13 25.1%) |

Elo: heuristic 0, v13 -202 [-245, -167], v8 -219 [-260, -187]. Doubling the
imitation corpus (6k -> 12k games) bought ~+17 Elo, inside the CIs. v13 is
`current_best` (tie-break: better value head, better vs heuristic), but the
imitation route is at a plateau roughly 200 Elo below the teacher.

### 2026-09-26 -- D6 value-target A/B: v14 (outcome) vs v15 (search root value), same corpus

Both trained on the same 6,000 dense root-value heuristic games (batches
17-20; `docs/SCALING_DIAGNOSTICS.md` D6). Only `--value-target` differs.

| version | target | Elo | 95% CI | vs heuristic | vs random | held-out corr vs outcome |
|---|---|---:|---|---|---|---:|
| v14 | outcome | +267 | [+213, +335] | 49-151 (24.5%) | 165-35 (82.5%) | 0.333 |
| **v15** | **root** | **+378** | [+313, +472] | **86-112 (43.4%)** | **180-20 (90.0%)** | **0.449** |
| v16 | blend:0.5 | +320 | [+261, +398] | 74-125 (37.2%) | 173-27 (86.5%) | 0.397 |

(heuristic anchored at +462 / +423 / +411 in the three runs.) v15 is the first
net inside ~50 Elo of the teacher; every earlier version sat ~200 below.
Decisive head-to-head vs v13 (300 games/pair) in `ladder_runs/s2_v13_vs_v15/`.
