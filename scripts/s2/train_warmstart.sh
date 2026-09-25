#!/bin/bash
# Train the warm-start net on the heuristic-guided corpus in iterate_data_s2.
# Registers the next version in trained_weights_s2 (from random init) ONLY if
# it clears the held-out value gate (--min-holdout-value-quality, default:
# held-out value MSE < 1.0 = better than predicting 0; exit 3 otherwise).
#
#   scripts/s2/train_warmstart.sh                # last 6000 game shards (~7M rows, ~95 GB flat store)
#   S2_WS_FILES=4000 scripts/s2/train_warmstart.sh
#
# Then: ladder the new version vs heuristic/random, and if it is credible set
# trained_weights_s2/iterate_state.json current_best to it before resuming
# scripts/s2/run_distributed.sh.
set -euo pipefail
cd "/c/Users/Gregg Keithley/Documents/Claude/Projects/mtg-bot"
export PYTHONIOENCODING=utf-8 PYTHONPATH=src
FILES="${S2_WS_FILES:-6000}"
WORKERS="${S2_WS_WORKERS:-4}"
DROPOUT="${S2_WS_DROPOUT:-0.1}"
WD="${S2_WS_WD:-1e-4}"
EPOCHS="${S2_WS_EPOCHS:-20}"   # DataLoader workers; the memmap store is shared and --loader-timeout-sec guards stalls
export MTG_BOT_STRUCTURED_CACHE_DIR="${MTG_BOT_STRUCTURED_CACHE_DIR:-C:/Users/Gregg Keithley/mtg_bot_structured_cache}"
echo "[s2-ws] $(date -u +%FT%TZ) training on the most recent $FILES shards of iterate_data_s2 (free: $(df -h /c | tail -1 | awk '{print $4}'))"
.venv-py313/Scripts/python.exe -m mtg_bot.cli train \
  --data-dir iterate_data_s2 --registry-root trained_weights_s2 \
  --architecture structured --scalar-schema-version 2 \
  --action-encoding-version canonical_v2 \
  --epochs "$EPOCHS" --early-stop-patience 5 --lr "${S2_LR:-3e-4}" --dropout "$DROPOUT" --weight-decay "$WD" \
  --num-workers "$WORKERS" --window-recent-files "$FILES" \
  --progress-dir training_progress_s2 --seed 1 \
  --notes "warm start: heuristic self-play corpus (nodes 400 / samples 2), most recent $FILES shards; dropout $DROPOUT wd $WD lr ${S2_LR:-3e-4}"
rc=$?
echo "[s2-ws] $(date -u +%FT%TZ) train exited $rc (3 = rejected by the held-out value gate)"
exit $rc
