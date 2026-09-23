#!/bin/bash
# Run N iterations of the scalar-schema-v2 lineage through the unified
# distributed launcher (desktop worker daemon + Mac worker). One
# launcher invocation per iteration; target_iter is derived from the
# lineage's iterate_state.json so cycle ids stay coherent with the
# stage labels iterate itself generates.
#
# Prereqs (see docs/RUNNING_DISTRIBUTED.md):
#   - coordinator up:   Start-ScheduledTask MTGBotCoordinator   (:5099)
#   - desktop worker:   Start-ScheduledTask MTGBotWorkerLocal    (:5198)
#   - Mac worker:       launchd com.mtg-bot.worker, LAN 192.168.0.111:5198
set -euo pipefail
cd "/c/Users/Gregg Keithley/Documents/Claude/Projects/mtg-bot"
export PYTHONIOENCODING=utf-8 PYTHONPATH=src
N="${1:-1}"
CONFIG="${S2_CONFIG:-configs/launch/s2.toml}"
# NOTE: no --window-recent here: it means "the N most recently modified FILES"
# (cli/train.py) and the distributed path rehydrates one .npz per GAME, so
# --window-recent 3 trained cycle 2 on 3 games (7,278 rows). Full history instead.
# Preflight: the coordinator on :5099 must be the s2 one (started with
# --weights-root trained_weights_s2 ...), otherwise workers would fetch the
# OLD lineage's v1/v2 -- version labels repeat across lineages.
if ! curl -sf -m 10 http://100.115.252.110:5099/v2/weights/v1/metadata | grep -q '"scalar_schema_version": *2'; then
  echo "[s2-dist] ABORT: coordinator at :5099 is not serving trained_weights_s2 (start MTGBotCoordinatorS2, not MTGBotCoordinator)" >&2
  exit 2
fi
STATE=trained_weights_s2/iterate_state.json
for _ in $(seq 1 "$N"); do
  done_n=$(python -c "import json;print(json.load(open('$STATE'))['iterations_completed'])")
  target=$((done_n + 1))
  echo "[s2-dist] $(date -u +%FT%TZ) launching iteration $target"
  .venv-py313/Scripts/python.exe -m mtg_bot.cli iterate-distributed \
    --config "$CONFIG" --iter.target_iter "$target" \
    --registry-root trained_weights_s2 --progress-dir training_progress_s2 \
    --deck-pool data/17lands/eoe_decks.json.gz \
    --queue-url http://100.115.252.110:5099 \
    ${DRY_RUN:+--dry-run} \
    --data-dir iterate_data_s2 --scalar-schema-version 2 \
    --eval-games 300 --one-legal-keep-frac 0.2 \
    --early-stop-patience 5 --learning-rate 1e-3 --seed 1 \
    --per-game-timeout-sec 900
done
