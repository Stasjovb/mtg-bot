#!/bin/bash
# Run the DESKTOP worker daemon from a feature worktree (branch code)
# instead of the MTGBotWorkerLocal scheduled task (main checkout).
#
# Same flags as the scheduled task (2026-09-26), cwd = the worktree and
# PYTHONPATH=src so the branch's data_gen / runner are what play the
# games. Stops the scheduled task first (port 5198 is shared). To go
# back: `powershell Start-ScheduledTask MTGBotWorkerLocal` after
# killing this daemon (kill the PID printed below).
#
#   scripts/s2/run_worker_from_worktree.sh        # start
#   scripts/s2/run_worker_from_worktree.sh stop   # stop + restore task
set -euo pipefail
WT="$(cd "$(dirname "$0")/../.." && pwd)"
MAIN="/c/Users/Gregg Keithley/Documents/Claude/Projects/mtg-bot"
PY="$MAIN/.venv-py313/Scripts/python.exe"
LOG="$MAIN/iterate_s2/worker_from_worktree.log"
PIDFILE="$MAIN/iterate_s2/worker_from_worktree.pid"

if [ "${1:-}" = "stop" ]; then
  if [ -f "$PIDFILE" ]; then
    pid=$(cat "$PIDFILE")
    powershell -NoProfile -Command "Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue" || true
    rm -f "$PIDFILE"
    echo "[wt-worker] stopped pid $pid"
  fi
  powershell -NoProfile -Command "Start-ScheduledTask -TaskName MTGBotWorkerLocal"
  echo "[wt-worker] MTGBotWorkerLocal task restarted (main checkout)"
  exit 0
fi

powershell -NoProfile -Command "Stop-ScheduledTask -TaskName MTGBotWorkerLocal" >/dev/null || true
sleep 3
cd "$WT"
export PYTHONPATH=src
echo "[wt-worker] starting from $WT @ $(git rev-parse --short HEAD) ($(git rev-parse --abbrev-ref HEAD)); log $LOG"
nohup "$PY" -m mtg_bot.worker_daemon --host 100.115.252.110 --port 5198 --n-workers 16 \
  --deck-pool-path "C:\\Users\\Gregg Keithley\\Documents\\Claude\\Projects\\mtg-bot\\data\\17lands\\eoe_decks.json.gz" \
  --weights-cache-root "C:\\Users\\Gregg Keithley\\.mtg_bot_worker_weights" \
  --nn-device cuda \
  --artifact-storage-uri "file:///C:/Users/Gregg Keithley/mtg_bot_artifacts_s2" \
  > "$LOG" 2>&1 &
# $! is the MSYS pid of the nohup wrapper; record the Windows python pid.
sleep 8
wpid=$(wmic process where "name='python.exe' and commandline like '%mtg_bot.worker_daemon%'" get processid 2>/dev/null | grep -E '^[0-9]' | tr -d ' \r' | head -1)
echo "${wpid:-unknown}" > "$PIDFILE"
n=0; until curl -sf -m 3 http://100.115.252.110:5198/v2/heartbeat >/dev/null 2>&1 || [ $n -ge 45 ]; do sleep 2; n=$((n+1)); done
curl -s -m 5 http://100.115.252.110:5198/v2/heartbeat | "$PY" -c "import json,sys;d=json.load(sys.stdin);print('[wt-worker] up:',d['git_commit'],d['state'],'pid',open(r'$PIDFILE').read().strip())"
