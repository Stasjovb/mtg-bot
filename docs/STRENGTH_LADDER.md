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

_(no production-depth runs recorded yet)_
