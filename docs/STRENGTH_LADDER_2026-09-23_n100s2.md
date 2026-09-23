# Strength ladder

Scoring: timeouts and crashes excluded from the denominator (gate convention).
Elo: Bradley-Terry MLE, anchor `random` = 0, bootstrap 95% CI over 200 resamples.

## Elo

| rank | agent | Elo | 95% CI | games | score |
|---:|---|---:|---|---:|---:|
| 1 | heuristic | +407 | [+342, +469] | 399 | 90.7% |
| 2 | v13s | +30 | [-12, +74] | 398 | 32.2% |
| 3 | random | +0 | [+0, +0] | 399 | 27.1% |

## Pairwise results

Each cell: row's win rate vs column with Wilson 95% CI, then `W-L-D` from the row's perspective (`t`=timeouts, `c`=crashed, both excluded from W-L-D).

| | random | heuristic | v13s |
|---|---|---|---|
| **random** | — | 9.0% [6%, 14%]<br>18-182-0 | 45.2% [38%, 52%]<br>90-109-0 t1 |
| **heuristic** | 91.0% [86%, 94%]<br>182-18-0 | — | 90.5% [86%, 94%]<br>180-19-0 c1 |
| **v13s** | 54.8% [48%, 62%]<br>109-90-0 t1 | 9.5% [6%, 14%]<br>19-180-0 c1 | — |

## Per-pair detail

| pair | requested | wins_a | wins_b | draws | timeouts | crashed | mean decisions | wall (s) | seed |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| random vs heuristic | 200 | 18 | 182 | 0 | 0 | 0 | 497 | 79 | 0 |
| random vs v13s | 200 | 90 | 109 | 0 | 1 | 0 | 643 | 3300 | 0 |
| heuristic vs v13s | 200 | 180 | 19 | 0 | 0 | 1 | 452 | 1116 | 0 |

## Config

- `agents`: `['random', 'heuristic', 'v13s']`
- `deck_pool`: `data\17lands\eoe_decks.json.gz`
- `games`: `200`
- `git_commit`: `5c1bc306`
- `nodes`: `100`
- `pairs`: `all`
- `per_game_timeout_sec`: `900.0`
- `registry_root`: `trained_weights`
- `samples`: `2`
- `seed`: `0`
- `started_at`: `2026-09-23T05:52:17+00:00`
- `timeouts_as_draws`: `False`
- `workers`: `20`
