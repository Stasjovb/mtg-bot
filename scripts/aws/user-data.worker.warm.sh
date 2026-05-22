#!/bin/bash
# Thin worker bootstrap from a baked AMI (see runspec.worker.warm.json).
# The baked AMI already has Ubuntu 24.04 + python3.13 + rust + the
# mtg-bot repo cloned at /opt/mtg-bot + the venv + the .pyd built +
# the deck pool downloaded. This script just freshens the source +
# rebuilds .pyd if rust changed + starts the daemon with a
# per-instance tailnet identity.
#
# Time budget: typically ~90s (boot + tailscale reset + git pull +
# daemon start). The original heavy user-data was ~12-18 min.
set -uxo pipefail
exec > >(tee -a /var/log/mtg-bot-bootstrap.log) 2>&1
echo "=== mtg-bot worker WARM bootstrap START $(date -u) ==="

# Cost backstop: poweroff after 6h if no contact. Same envelope as
# the iter017/018 heavy user-data; intentionally longer than a
# single iter's expected duration so the watchdog only fires on
# genuine connection loss.
( sleep 21600; echo "WATCHDOG: 6h elapsed -> poweroff"; poweroff ) &

COORD="${MTG_BOT_COORDINATOR_URL:-http://100.115.252.110:5099}"
REPO=/opt/mtg-bot
# IMDSv2 token-based fetch. Ubuntu 24.04 AMIs created from instances with
# HttpTokens=required return 401 for IMDSv1 calls, so a tokenless curl
# silently yields an empty body. That bit us: the warm bootstrap built
# a tailscale hostname of "mtg-bot-aws-warm-" (trailing dash from empty
# IID), and `tailscale up` rejected it client-side as an invalid DNS
# label. Token flow works whether HttpTokens is required or optional.
IMDS_TOKEN=$(curl -fsS --max-time 5 -X PUT \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 300" \
  http://169.254.169.254/latest/api/token || echo "")
IID=$(curl -fsS --max-time 5 \
  -H "X-aws-ec2-metadata-token: $IMDS_TOKEN" \
  http://169.254.169.254/latest/meta-data/instance-id || echo "")
if [[ ! "$IID" =~ ^i-[0-9a-f]+$ ]]; then
  echo "ABORT: IMDS did not return a usable instance-id (got: '$IID')"
  exit 1
fi
HOSTNAME_TAG="${MTG_BOT_HOSTNAME_TAG:-mtg-bot-aws-warm}"

mark(){ echo "PHASE: $1 $(date -u +%H:%M:%S)"; echo "$1" > /var/run/mtg-bot-phase; }

# --- Tailscale: reset baked identity, auth as new node ---
# The AMI was baked while authed as "mtg-bot-aws-bake". To get a
# fresh tailnet identity per warm instance, we have to FULLY stop
# tailscaled, wipe its state directory, restart it, and re-auth
# with a per-instance hostname. ``--force-reauth`` is intentionally
# omitted because the state directory is already empty — a fresh
# auth, not a re-auth. ``sleep 2`` after restart is not enough on a
# c7i: the daemon needs ~5s to be ready to accept ``tailscale up``,
# and the interface needs ~5-15s after that to get an IP assigned.
mark tailscale-reset
systemctl stop tailscaled || true
rm -rf /var/lib/tailscale/* 2>/dev/null || true
systemctl start tailscaled

# Wait for tailscaled socket to be ready (CLI responds).
for i in $(seq 1 30); do
  tailscale status >/dev/null 2>&1 && break
  echo "waiting for tailscaled socket ($i/30)"
  sleep 1
done

mark tailscale-up
tailscale up --authkey='tskey-auth-ktPWfpxPu511CNTRL-PHx8tg2mpBdmimcVh9i6CdGaXDGjSDq9J' \
  --hostname="${HOSTNAME_TAG}-${IID}" --accept-dns=true --ssh
TS_UP_RC=$?
echo "tailscale up exit=$TS_UP_RC"

# Wait for IP assignment. ``tailscale ip -4`` returns empty until
# the control plane finishes the registration handshake and assigns
# a 100.x address; this can take 5-30s on a fresh node.
mark tailscale-ip-wait
TS_IP=""
for i in $(seq 1 60); do
  TS_IP=$(tailscale ip -4 2>/dev/null | head -1)
  if [ -n "$TS_IP" ] && [[ "$TS_IP" == 100.* ]]; then
    break
  fi
  echo "waiting for tailnet IP ($i/60), got: '$TS_IP'"
  sleep 2
done
if [ -z "$TS_IP" ] || [[ "$TS_IP" != 100.* ]]; then
  echo "ABORT: tailscale never assigned an IP (got: '$TS_IP')"
  exit 1
fi
echo "TAILNET IP: $TS_IP  hostname: ${HOSTNAME_TAG}-${IID}  instance: $IID"

# --- Code freshen: git pull if reachable; conditional Rust rebuild ---
mark git-pull
cd "$REPO" || { echo "ABORT: $REPO not present in AMI"; exit 1; }
BAKED_COMMIT=$(git rev-parse HEAD)
echo "AMI baked at commit: $BAKED_COMMIT"

# Try to pull from coordinator's repo.bundle (same source as the
# heavy user-data used at bake time). If unreachable / no new
# commits, the existing baked state is fine.
mark wait-coord
for i in $(seq 1 30); do
  curl -fsS --max-time 5 "$COORD/repo.bundle" -o /opt/mtg-bot-new.bundle && break || true
  echo "coord retry $i/30"
  sleep 4
done

if [ -s /opt/mtg-bot-new.bundle ]; then
  mark git-update
  # Fetch from bundle, fast-forward main to whatever the coord serves.
  git -C "$REPO" remote remove origin-bundle 2>/dev/null || true
  git -C "$REPO" remote add origin-bundle /opt/mtg-bot-new.bundle
  git -C "$REPO" fetch origin-bundle main
  git -C "$REPO" reset --hard origin-bundle/main
  NEW_COMMIT=$(git -C "$REPO" rev-parse HEAD)
  echo "Updated to commit: $NEW_COMMIT (was $BAKED_COMMIT)"
  # Maturin rebuild is intentionally skipped (2026-05-20): Rust bindings
  # are not on the production hot path yet and have been observed
  # crashing the subprocess pool on fresh builds. Workers run the baked
  # .pyd, accepting a stale Rust engine as long as the Python code
  # tolerates it. Re-enable by reverting this block once the bindings
  # stabilize.
  mark rust-skipped
  echo "Rust rebuild SKIPPED per project direction (bindings not yet production-ready); using baked .pyd from $BAKED_COMMIT"
else
  echo "Coordinator unreachable or empty bundle; running baked code at $BAKED_COMMIT"
fi

# --- Start daemon ---
# Note: CPU-only torch is already installed in the AMI (rebaked
# 2026-05-20 from ami-07bd7300ab2800515 to replace the CUDA build
# baked into the prior ami-0d95001ea4af182c9). The CUDA wheel
# SIGBUSed inside ``torch._preload_cuda_lib`` on CPU-only c7i.* hosts
# at spawn-subprocess import time, presenting as
# ``concurrent.futures.process.BrokenProcessPool`` at the parent.
# If a future bake regresses, set PYTHONFAULTHANDLER=1 below and
# expose /var/log via ``python -m http.server`` to recover the fault
# trace (the diagnostic scaffolding lived in this file 2026-05-20).
mark daemon
NCPU=$(nproc); NW=$(( NCPU>2 ? NCPU-2 : 1 ))
# AMI baked 2026-05-20 predates the [s3] extra (boto3). The
# worker_daemon imports boto3 lazily inside S3ArtifactUploader, so
# without it the daemon crashes before binding port 5198. Install
# it at boot time so the warm path keeps working until the AMI
# gets re-baked with boto3 in the venv.
.venv-py313/bin/python -m pip install --quiet boto3>=1.34 || \
  echo "WARN: boto3 install failed; S3 artifact upload will not work"
# AWS_DEFAULT_REGION pinned for boto3 -- without it the client
# init falls back to a multi-second IMDS region lookup, which made
# the daemon appear to hang for ~7 min on first /v2/heartbeat (the
# daemon's import-time uploader_from_uri() constructs boto3.client
# eagerly). Hardcoded to us-east-1 because the warm AMI lives
# there and the worker only ever runs on instances launched off
# that AMI. AWS_REGION is set too because some boto3 paths read
# that name instead.
nohup env PYTHONPATH=src AWS_DEFAULT_REGION=us-east-1 AWS_REGION=us-east-1 \
  .venv-py313/bin/python -m mtg_bot.worker_daemon \
  --host "$TS_IP" --port 5198 --n-workers "$NW" --worker-id "${HOSTNAME_TAG}-${IID}" \
  --deck-pool-path "$REPO/data/17lands/eoe_decks.json.gz" \
  --artifact-storage-uri "${MTG_BOT_ARTIFACT_STORAGE_URI:-s3://mtg-bot-artifacts-630589799985/launcher/}" \
  > /var/log/mtg-bot-daemon.log 2>&1 &

mark healthcheck
for i in $(seq 1 36); do
  if curl -fsS --max-time 5 "http://$TS_IP:5198/v2/heartbeat" | grep -q '"state"'; then
    echo "=== WORKER HEALTHY (warm boot) $(date -u) ==="
    mark READY
    exit 0
  fi
  sleep 5
done
echo "=== WORKER UNHEALTHY: daemon never answered /v2/heartbeat ==="
mark daemon-unhealthy
exit 1
