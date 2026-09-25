# Strength ladder

Scoring: timeouts and crashes excluded from the denominator (gate convention).
Elo: Bradley-Terry MLE, anchor `random` = 0, bootstrap 95% CI over 200 resamples.

## Elo

| rank | agent | Elo | 95% CI | games | score |
|---:|---|---:|---|---:|---:|
| 1 | heuristic | +470 | [+397, +572] | 199 | 76.4% |
| 2 | v8 | +267 | [+213, +343] | 399 | 53.1% |
| 3 | random | +0 | [+0, +0] | 200 | 17.5% |

## Pairwise results

Each cell: row's win rate vs column with Wilson 95% CI, then `W-L-D` from the row's perspective (`t`=timeouts, `c`=crashed, both excluded from W-L-D).

| | random | heuristic | v8 |
|---|---|---|---|
| **random** | — |  | 17.5% [13%, 23%]<br>35-165-0 |
| **heuristic** |  | — | 76.4% [70%, 82%]<br>152-47-0 t1 |
| **v8** | 82.5% [77%, 87%]<br>165-35-0 | 23.6% [18%, 30%]<br>47-152-0 t1 | — |

## Per-pair detail

| pair | requested | wins_a | wins_b | draws | timeouts | crashed | mean decisions | wall (s) | seed |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| heuristic vs v8 | 200 | 152 | 47 | 0 | 1 | 0 | 515 | 1335 | 0 |
| random vs v8 | 200 | 35 | 165 | 0 | 0 | 0 | 586 | 674 | 0 |

## Config

- `agents`: `['random', 'heuristic', 'v8']`
- `deck_pool`: `data\17lands\eoe_decks.json.gz`
- `games`: `200`
- `git_commit`: `5bb7524d`
- `nodes`: `100`
- `pairs`: `heuristic:v8,random:v8`
- `per_game_timeout_sec`: `900.0`
- `registry_root`: `trained_weights_s2`
- `samples`: `2`
- `seed`: `0`
- `started_at`: `2026-09-25T05:02:44+00:00`
- `timeouts_as_draws`: `False`
- `workers`: `16`
