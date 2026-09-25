#!/bin/bash
# Rank the value-head levers on a matched subset of iterate_data_s2.
#
# Produced the numbers in docs/SCALING_DIAGNOSTICS.md D5. Four arms,
# identical shards / seed / LR / batch, differing only in the lever:
#
#   base       dropout 0.1 wd 1e-4  value head on the shared trunk
#   blind      dropout 0.1 wd 1e-4  identity-blind value head
#   heavyreg   dropout 0.3 wd 1e-3  shared trunk
#   combined   dropout 0.3 wd 1e-3  identity-blind value head
#
# The value calibration is fit unconditionally now, so "base" doubles
# as the calibration-only arm: its raw-vs-calibrated columns are what
# calibration alone buys.
#
#   scripts/s2/value_head_sweep.sh                    # 1000 shards, 3 epochs
#   FILES=6000 EPOCHS=9 scripts/s2/value_head_sweep.sh
#
# Everything it writes lands OUTSIDE the repo under $EXP_ROOT, and it
# uses its OWN flat-store cache dir so it never disturbs a concurrent
# production warm-start run's cache.
set -uo pipefail
cd "$(dirname "$0")/../.."

FILES="${FILES:-1000}"
EPOCHS="${EPOCHS:-3}"
SEED="${SEED:-1}"
EXP_ROOT="${EXP_ROOT:-$HOME/mtg_bot_value_exp}"
DATA="${DATA:-iterate_data_s2}"
PY="${PY:-.venv-py313/Scripts/python.exe}"

export PYTHONIOENCODING=utf-8
export PYTHONPATH=src
export MTG_BOT_STRUCTURED_CACHE_DIR="${MTG_BOT_STRUCTURED_CACHE_DIR:-$HOME/mtg_bot_value_exp_cache}"
mkdir -p "$EXP_ROOT/prog"

run_arm() {
  local label="$1" dropout="$2" wd="$3" vhi="$4"
  mkdir -p "$EXP_ROOT/reg_$label"
  echo "[sweep] $(date -u +%FT%TZ) $label dropout=$dropout wd=$wd value_head_input=$vhi"
  "$PY" -m mtg_bot.cli train \
    --data-dir "$DATA" --registry-root "$EXP_ROOT/reg_$label" \
    --architecture structured --scalar-schema-version 2 \
    --action-encoding-version canonical_v2 \
    --epochs "$EPOCHS" --lr 3e-4 --dropout "$dropout" --weight-decay "$wd" \
    --value-head-input "$vhi" \
    --num-workers 2 --window-recent-files "$FILES" \
    --progress-dir "$EXP_ROOT/prog" --seed "$SEED" \
    --notes "value-head experiment $label"
  echo "[sweep] $(date -u +%FT%TZ) $label exited $? (3 = held-out value gate rejection)"
}

run_arm base     0.1 1e-4 trunk
run_arm blind    0.1 1e-4 trunk_no_printing
run_arm heavyreg 0.3 1e-3 trunk
run_arm combined 0.3 1e-3 trunk_no_printing
echo "[sweep] done; progress cards in $EXP_ROOT/prog"
