#!/bin/bash
# Durable backup of the scalar-schema-v2 lineage to S3 (the desktop's C: is
# ~92% full and holds the only copy of the corpus + weights).
#
#   scripts/s2/backup_to_s3.sh            # sync everything listed below
#   S3_PREFIX=s3://bucket/other scripts/s2/backup_to_s3.sh
#
# Uses the existing artifact bucket (us-east-1) and the desktop's
# mtg-bot-admin credentials (~/.aws). Idempotent: `aws s3 sync` only
# uploads new/changed files. Restore with the reverse sync, e.g.
#   aws s3 sync s3://mtg-bot-artifacts-630589799985/s2/iterate_data_s2 iterate_data_s2
set -euo pipefail
cd "/c/Users/Gregg Keithley/Documents/Claude/Projects/mtg-bot"
PREFIX="${S3_PREFIX:-s3://mtg-bot-artifacts-630589799985/s2}"
for d in iterate_data_s2 iterate_data_s2_v1corpus trained_weights_s2 training_progress_s2 ladder_runs replays_s2; do
  [ -d "$d" ] || continue
  echo "[s3-backup] $(date -u +%FT%TZ) $d -> $PREFIX/$d"
  aws s3 sync "$d" "$PREFIX/$d" --only-show-errors --exclude "*.tmp" --exclude "*.building-*"
done
echo "[s3-backup] done: $(aws s3 ls "$PREFIX/" | awk '{print $2}' | tr '\n' ' ')"
