#!/bin/bash
# AlphaZero cycle(s) for the s2 lineage launched from a FEATURE WORKTREE
# (branch code on the launcher/orchestrator/trainer), lineage state in
# the main checkout. Mirrors scripts/s2/run_distributed.sh but adds the
# D6 value target: self-play driven by current_best records the NN-PIMC
# root value per row, and training regresses it (--value-target root).
#
#   scripts/s2/run_cycle_from_worktree.sh [n_cycles]
#   S2_CONFIG          launch TOML (default configs/launch/s2.toml)
#   S2_VALUE_TARGET    outcome | root | blend:<w>   (default root)
#   S2_ACCEPT          arena acceptance threshold (default 0.55 = gated)
#   S2_WINDOW          --window-recent-files (default 6000)
#   S2_TRAIN_WORKERS   DataLoader workers (default 4)
#   S2_LR              (default 3e-4)   S2_SEED (default 1)
#   S2_LADDER          1 = ladder the newest version after each cycle (default 1)
#   S2_CACHE           store dir (default E:/mtg_bot_structured_cache)
set -uo pipefail
WT="$(cd "$(dirname "$0")/../.." && pwd)"
MAIN="/c/Users/Gregg Keithley/Documents/Claude/Projects/mtg-bot"
MAIN_WIN="C:/Users/Gregg Keithley/Documents/Claude/Projects/mtg-bot"
PY="$MAIN/.venv-py313/Scripts/python.exe"
cd "$WT"
export PYTHONPATH=src PYTHONIOENCODING=utf-8
export MTG_BOT_STRUCTURED_CACHE_DIR="${S2_CACHE:-E:/mtg_bot_structured_cache}"
N="${1:-1}"
CONFIG="${S2_CONFIG:-configs/launch/s2.toml}"
VT="${S2_VALUE_TARGET:-root}"
STATE="$MAIN_WIN/trained_weights_s2/iterate_state.json"   # Windows path: read by the Windows python
log() { echo "[s2-cycle] $(date -u +%FT%TZ) $*"; }

log "worktree=$WT HEAD=$(git rev-parse --short HEAD) value_target=$VT accept=${S2_ACCEPT:-0.55} window=${S2_WINDOW:-6000}"
if ! curl -sf -m 10 http://100.115.252.110:5099/v2/weights/v1/metadata | grep -q '"scalar_schema_version": *2'; then
  log "ABORT: coordinator at :5099 is not serving trained_weights_s2" >&2
  exit 2
fi
for _ in $(seq 1 "$N"); do
  done_n=$("$PY" -c "import json;print(json.load(open(r'$STATE'))['iterations_completed'])")
  best=$("$PY" -c "import json;print(json.load(open(r'$STATE'))['current_best'])")
  target=$((done_n + 1))
  log "launching iteration $target (self-play driven by $best)"
  "$PY" -m mtg_bot.cli iterate-distributed \
    --config "$CONFIG" --iter.target_iter "$target" \
    --registry-root "$MAIN_WIN/trained_weights_s2" --progress-dir "$MAIN_WIN/training_progress_s2" \
    --deck-pool "$MAIN_WIN/data/17lands/eoe_decks.json.gz" \
    --queue-url http://100.115.252.110:5099 \
    --data-dir "$MAIN_WIN/iterate_data_s2" --scalar-schema-version 2 \
    --eval-games 300 --one-legal-keep-frac 0.2 \
    --early-stop-patience 5 --learning-rate "${S2_LR:-3e-4}" --seed "${S2_SEED:-1}" \
    --acceptance-threshold "${S2_ACCEPT:-0.55}" \
    --value-target "$VT" \
    --per-game-timeout-sec 900 --train-num-workers "${S2_TRAIN_WORKERS:-4}" \
    --window-recent-files "${S2_WINDOW:-6000}"
  rc=$?
  log "iteration $target launcher exited rc=$rc"
  if [ "${S2_LADDER:-1}" = "1" ]; then
    newest=$(ls "$MAIN/trained_weights_s2" | grep -E '^v[0-9]+$' | sort -V | tail -1)
    if [ ! -f "$MAIN/ladder_runs/s2_${newest}/ladder.md" ]; then
      log "ladder: ${newest} vs heuristic/random"
      ( cd "$MAIN" && scripts/s2/ladder_version.sh "$newest" ) || log "ladder for ${newest} FAILED (continuing)"
    fi
  fi
done
log "done"
