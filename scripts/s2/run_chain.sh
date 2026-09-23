#!/bin/bash
# Wait for the n100/s2 ladder to finish, then start the from-scratch
# scalar-schema-v2 iterate loop at the same depth (nodes 100, samples 2).
cd "/c/Users/Gregg Keithley/Documents/Claude/Projects/mtg-bot" || exit 1
echo "[chain] $(date -u +%FT%TZ) waiting for ladder_runs/prod_n100s2/ladder.md"
until [ -f ladder_runs/prod_n100s2/ladder.md ]; do sleep 60; done
echo "[chain] $(date -u +%FT%TZ) ladder done; starting iterate"
export PYTHONIOENCODING=utf-8 PYTHONPATH=src
exec .venv-py313/Scripts/python.exe -m mtg_bot.cli iterate \
  --bootstrap-version v1 --registry-root trained_weights_s2 \
  --data-dir iterate_data_s2 --progress-dir training_progress_s2 \
  --deck-pool data/17lands/eoe_decks.json.gz \
  --architecture structured --scalar-schema-version 2 \
  --n-iterations 6 --games-per-iteration 500 --nodes 100 --samples 2 \
  --workers 20 --epochs 20 --early-stop-patience 5 --learning-rate 1e-3 \
  --eval-games 300 --one-legal-keep-frac 0.2 --window-recent 3 --seed 1 \
  --per-game-timeout-sec 900 --shards-config ""
