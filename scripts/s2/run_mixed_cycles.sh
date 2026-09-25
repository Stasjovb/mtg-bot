#!/bin/bash
# Alternate a heuristic-guided corpus batch with an NN self-play cycle so the
# training window keeps a steady share of competent-play (heuristic) games.
#
# Why: held-out value corr fell v8 0.35 -> v9 0.29 -> v10 0.26 as NN-play
# games displaced the heuristic games in the 6,000-file window (2026-09-25).
#
#   scripts/s2/run_mixed_cycles.sh [n_cycles]
#   S2_HEUR_GAMES=1000   heuristic games generated before each NN cycle
#   (all run_distributed.sh / gen_heuristic_corpus.sh env knobs apply)
set -euo pipefail
cd "/c/Users/Gregg Keithley/Documents/Claude/Projects/mtg-bot"
N="${1:-1}"
HEUR="${S2_HEUR_GAMES:-1000}"
for _ in $(seq 1 "$N"); do
  echo "[s2-mixed] $(date -u +%FT%TZ) heuristic batch ($HEUR games)"
  S2_CONFIG="${S2_CORPUS_CONFIG:-configs/launch/s2_corpus.toml}" S2_GAMES_PER_BATCH="$HEUR" \
    scripts/s2/gen_heuristic_corpus.sh 1
  echo "[s2-mixed] $(date -u +%FT%TZ) NN cycle"
  scripts/s2/run_distributed.sh 1
done
