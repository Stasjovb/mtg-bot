#!/bin/bash
# Diagnostic 6 A/B (docs/SCALING_DIAGNOSTICS.md): three warm starts on the
# SAME dense root-value corpus, differing only in --value-target, each
# put on the ladder. Runs from the feature worktree (branch trainer) with
# the lineage state in the main checkout.
#
#   scripts/s2/run_value_target_ab.sh [wait_marker]
#   S2_AB_FILES     newest shards to train on (default 6000 = batches 17-20)
#   S2_AB_TARGETS   space-separated (default "outcome root blend:0.5")
#   S2_AB_CACHE     shared store dir (default E:/mtg_bot_structured_cache;
#                   the store is built once and reused by all three runs)
#
# The held-out gate is left at its default: a rejected run (exit 3) is
# NOT registered, so the version -> target mapping is logged per run
# rather than assumed.
set -uo pipefail
WT="$(cd "$(dirname "$0")/../.." && pwd)"
MAIN="/c/Users/Gregg Keithley/Documents/Claude/Projects/mtg-bot"
MAIN_WIN="C:/Users/Gregg Keithley/Documents/Claude/Projects/mtg-bot"
PY="$MAIN/.venv-py313/Scripts/python.exe"
FILES="${S2_AB_FILES:-6000}"
TARGETS="${S2_AB_TARGETS:-outcome root blend:0.5}"
export MTG_BOT_STRUCTURED_CACHE_DIR="${S2_AB_CACHE:-E:/mtg_bot_structured_cache}"
export PYTHONIOENCODING=utf-8
log() { echo "[s2-ab] $(date -u +%FT%TZ) $*"; }

if [ -n "${1:-}" ]; then
  log "waiting for marker '$1' in $MAIN/iterate_s2/rootvalue_corpus.log"
  until grep -q "$1" "$MAIN/iterate_s2/rootvalue_corpus.log"; do sleep 60; done
fi
cd "$WT"
export PYTHONPATH=src
log "worktree HEAD=$(git rev-parse --short HEAD); newest $FILES shards of iterate_data_s2; store $MTG_BOT_STRUCTURED_CACHE_DIR"
dense=$(ls "$MAIN/iterate_data_s2" | grep -c "s2_iter_0\(17\|18\|19\|20\)_self_play_heuristic")
log "dense root-value shards available: $dense"

newest_version() {
  ls -d "$MAIN/trained_weights_s2"/v[0-9]* | sed 's/.*v//' | sort -n | tail -1
}

for target in $TARGETS; do
  before=$(newest_version)
  log "=== training value_target=$target (registry newest before: v$before)"
  "$PY" -m mtg_bot.cli train \
    --data-dir "$MAIN_WIN/iterate_data_s2" --registry-root "$MAIN_WIN/trained_weights_s2" \
    --architecture structured --scalar-schema-version 2 \
    --action-encoding-version canonical_v2 \
    --epochs 20 --early-stop-patience 5 --lr 3e-4 --dropout 0.1 --weight-decay 1e-4 \
    --num-workers 4 --window-recent-files "$FILES" \
    --progress-dir "$MAIN_WIN/training_progress_s2" --seed 1 \
    --value-target "$target" \
    --notes "D6 A/B value_target=$target: dense root-value heuristic corpus (nodes 400 / samples 2), newest $FILES shards; dropout 0.1 wd 1e-4 lr 3e-4"
  rc=$?
  after=$(newest_version)
  if [ "$rc" = 0 ] && [ "$after" != "$before" ]; then
    log "value_target=$target -> registered v$after"
    echo "$target v$after" >> "$MAIN/iterate_s2/value_target_ab_versions.txt"
    ( cd "$MAIN" && scripts/s2/ladder_version.sh "v$after" ) && log "ladder done for v$after (value_target=$target)"
  else
    log "value_target=$target -> NOT registered (rc=$rc; 3 = held-out gate rejected)"
    echo "$target REJECTED rc=$rc" >> "$MAIN/iterate_s2/value_target_ab_versions.txt"
  fi
done
log "A/B chain done; mapping in $MAIN/iterate_s2/value_target_ab_versions.txt"
