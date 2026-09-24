#!/bin/bash
# Put one registered s2 version on the strength ladder vs heuristic + random
# (200 games/pair, nodes 100 / samples 2, 16 local workers; ~30-40 min).
#   scripts/s2/ladder_version.sh v8
set -euo pipefail
cd "/c/Users/Gregg Keithley/Documents/Claude/Projects/mtg-bot"
export PYTHONIOENCODING=utf-8 PYTHONPATH=src
V="${1:?version, e.g. v8}"
OUT="ladder_runs/s2_${V}"
[ -f "$OUT/ladder.md" ] && { echo "[ladder] $OUT/ladder.md already exists"; sed -n '/## Elo/,/## Pairwise/p' "$OUT/ladder.md"; exit 0; }
.venv-py313/Scripts/python.exe -m mtg_bot.cli ladder \
  --agents random heuristic "$V" --pairs "heuristic:${V},random:${V}" \
  --games "${S2_LADDER_GAMES:-200}" --nodes 100 --samples 2 --workers "${S2_LADDER_WORKERS:-16}" \
  --per-game-timeout-sec 900 --registry-root trained_weights_s2 \
  --deck-pool data/17lands/eoe_decks.json.gz --out "$OUT"
sed -n '/## Elo/,/## Pairwise/p' "$OUT/ladder.md"
