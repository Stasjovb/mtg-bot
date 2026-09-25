#!/bin/bash
# Data-volume test for the imitation hypothesis (2026-09-25): every net trained
# with NN-play games in the window (v9-v12) came out weaker than v8, which was
# trained on 6,000 heuristic games only. So: quarantine the NN-play shards, add
# one more heuristic batch, warm-start a fresh net on ALL heuristic shards
# (~2x v8's data) with the training store on a big drive, then ladder it.
#
#   scripts/s2/run_heuristic_scaling.sh [wait_for_log_marker]
#   S2_SCALE_CACHE   store dir (default E:/mtg_bot_structured_cache)
#   S2_SCALE_GAMES   heuristic games to add first (default 1500; 0 = skip)
set -uo pipefail
cd "/c/Users/Gregg Keithley/Documents/Claude/Projects/mtg-bot"
CACHE="${S2_SCALE_CACHE:-E:/mtg_bot_structured_cache}"
GAMES="${S2_SCALE_GAMES:-1500}"
Q=iterate_data_s2_nnplay_mixed
mkdir -p "$Q"
log() { echo "[s2-scale] $(date -u +%FT%TZ) $*"; }
if [ -n "${1:-}" ]; then
  log "waiting for marker '$1' in iterate_s2/mixed_cycles_from_v8_resume.log"
  until grep -q "$1" iterate_s2/mixed_cycles_from_v8_resume.log; do sleep 30; done
fi
n=0; for f in $(ls iterate_data_s2 | grep -E "_self_play_v[0-9]+"); do mv "iterate_data_s2/$f" "$Q/"; n=$((n+1)); done
log "quarantined $n NN-play shards into $Q; heuristic shards now $(ls iterate_data_s2 | grep -c heuristic)"
if [ "$GAMES" -gt 0 ]; then
  log "heuristic batch ($GAMES games)"
  S2_CONFIG="${S2_CORPUS_CONFIG:-configs/launch/s2_corpus.toml}" S2_GAMES_PER_BATCH="$GAMES" scripts/s2/gen_heuristic_corpus.sh 1 || { log "corpus batch FAILED rc=$?"; exit 1; }
fi
log "heuristic-only warm start on $(ls iterate_data_s2 | grep -c heuristic) shards; store in $CACHE"
MTG_BOT_STRUCTURED_CACHE_DIR="$CACHE" S2_WS_FILES=20000 S2_WS_WORKERS="${S2_TRAIN_WORKERS:-4}" scripts/s2/train_warmstart.sh; rc=$?
log "warm start exit rc=$rc"
v=$(ls -d trained_weights_s2/v[0-9]* | sed 's/.*v//' | sort -n | tail -1)
log "newest version: v$v"
[ "$rc" = 0 ] && scripts/s2/ladder_version.sh "v$v" && log "ladder done for v$v"
