#!/bin/bash
# Heuristic corpus batch launched from a FEATURE WORKTREE (branch code),
# with all lineage state (data, registry, progress) still living in the
# main checkout so the coordinator keeps serving one lineage.
#
# Why this exists (2026-09-26): the dense-value-target experiment needs
# the recorder on feature/root-value-targets while main stays untouched
# pending review. The launcher's stale-worker guard compares worker
# commits to *this* checkout's HEAD, so every worker must run the same
# branch commit (Mac: `git checkout feature/<name>` + kickstart; desktop:
# scripts/s2/run_worker_from_worktree.sh).
#
#   scripts/s2/gen_corpus_from_worktree.sh [n_batches]
#   S2_CONFIG           launch TOML (default configs/launch/s2_corpus.toml)
#   S2_GAMES_PER_BATCH  games per batch (default 1500)
#   S2_SEED             (default 1)
#   S2_NODES / S2_SAMPLES  search depth override (default: the TOML's, 400 / 2)
#   S2_TIMEOUT          per-game timeout seconds (default 900; raise for deep search)
set -euo pipefail
WT="$(cd "$(dirname "$0")/../.." && pwd)"
MAIN="/c/Users/Gregg Keithley/Documents/Claude/Projects/mtg-bot"
MAIN_WIN="C:/Users/Gregg Keithley/Documents/Claude/Projects/mtg-bot"
cd "$WT"
export PYTHONPATH=src
# AWS fleet launches read the Tailscale auth key from the launcher env;
# keep it in a private file outside the repo (never in the TOML / git).
KEYF="$HOME/.mtg_bot/tailscale_authkey"
if [ -z "${MTG_BOT_TAILSCALE_AUTHKEY:-}" ] && [ -s "$KEYF" ]; then export MTG_BOT_TAILSCALE_AUTHKEY="$(tr -d '
' < "$KEYF")"; fi
PY="$MAIN/.venv-py313/Scripts/python.exe"
N="${1:-1}"
CONFIG="${S2_CONFIG:-configs/launch/s2_corpus.toml}"
GAMES="${S2_GAMES_PER_BATCH:-1500}"
SEED="${S2_SEED:-1}"
DATA_DIR="$MAIN_WIN/iterate_data_s2"

echo "[s2-wt] worktree=$WT HEAD=$(git rev-parse --short HEAD) branch=$(git rev-parse --abbrev-ref HEAD)"
if ! curl -sf -m 10 http://100.115.252.110:5099/v2/weights/v1/metadata \
    | grep -q '"scalar_schema_version": *2'; then
  echo "[s2-wt] ABORT: coordinator at :5099 is not serving trained_weights_s2" >&2
  exit 2
fi

next_batch() {
  "$PY" - "$MAIN_WIN/iterate_data_s2" "$MAIN_WIN/trained_weights_s2/iterate_state.json" <<'PY'
import json, re, sys
from pathlib import Path
data_dir, state_path = Path(sys.argv[1]), Path(sys.argv[2])
base = int(json.load(open(state_path))["iterations_completed"])
pat = re.compile(r"s2_iter_(\d+)_self_play_heuristic")
seen = [int(m.group(1)) for p in data_dir.glob("s2_iter_*heuristic*")
        for m in [pat.match(p.name)] if m]
print(max(seen + [base]) + 1)
PY
}

for _ in $(seq 1 "$N"); do
  target=$(next_batch)
  echo "[s2-wt] $(date -u +%FT%TZ) launching heuristic corpus batch $target ($GAMES games) from $(git rev-parse --short HEAD)"
  "$PY" -m mtg_bot.cli iterate-distributed \
    --config "$CONFIG" --iter.target_iter "$target" \
    --iter.games_per_iteration "$GAMES" \
    --registry-root "$MAIN_WIN/trained_weights_s2" \
    --progress-dir "$MAIN_WIN/training_progress_s2" \
    --deck-pool "$MAIN_WIN/data/17lands/eoe_decks.json.gz" \
    --queue-url http://100.115.252.110:5099 \
    --data-dir "$DATA_DIR" --scalar-schema-version 2 \
    --self-play-evaluator heuristic --corpus-only \
    --corpus-batch "$target" \
    ${S2_NODES:+--iter.nodes "$S2_NODES"} ${S2_SAMPLES:+--iter.samples "$S2_SAMPLES"} \
    --per-game-timeout-sec "${S2_TIMEOUT:-900}" --seed "$SEED"
done
echo "[s2-wt] $(date -u +%FT%TZ) done"
