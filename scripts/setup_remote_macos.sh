#!/usr/bin/env bash
# Bootstrap a macOS remote for distributed mtg-bot self-play.
#
# Run this on the Mac (NOT on the master). It:
#   1. Installs Python 3.13 via Homebrew if missing.
#   2. Clones the mtg-bot repo (REPO_URL) to REPO_PATH if not present.
#   3. Creates .venv-py313, installs the package + native-ARM PyTorch.
#   4. Sets up ~/.ssh/authorized_keys with the master's public key
#      (MASTER_PUBKEY) and the right perms.
#   5. Prints the manual steps remaining (Remote Login, Tailscale).
#
# Idempotent: safe to re-run. ``set -e`` aborts on the first error.
#
# Variables filled in by ``scripts/serve_setup_scripts.py`` when this
# is fetched over HTTP from the master:
#   {{REPO_URL}}            → master's git remote
#   {{REPO_PATH}}           → default ``~/projects/mtg-bot``
#   {{MASTER_PUBKEY}}       → master's ssh-ed25519 public key
#   {{MASTER_TAILNET_NAME}} → for the printed "next steps"

set -euo pipefail

REPO_URL="${REPO_URL:-{{REPO_URL}}}"
REPO_PATH="${REPO_PATH:-{{REPO_PATH}}}"
MASTER_PUBKEY="${MASTER_PUBKEY:-{{MASTER_PUBKEY}}}"
MASTER_TAILNET_NAME="${MASTER_TAILNET_NAME:-{{MASTER_TAILNET_NAME}}}"

if [[ "$REPO_URL" == "{{"*"}}" ]]; then
    echo "ERROR: REPO_URL not set. Either fetch this script from the " \
         "master's serve_setup_scripts.py endpoint, or export REPO_URL=..." >&2
    exit 1
fi

echo "===================================================================="
echo "mtg-bot remote setup (macOS)"
echo "  REPO_URL  = $REPO_URL"
echo "  REPO_PATH = $REPO_PATH"
echo "===================================================================="

# --- 1. Python 3.13 --------------------------------------------------
if ! command -v python3.13 >/dev/null 2>&1; then
    if ! command -v brew >/dev/null 2>&1; then
        echo "ERROR: brew not found. Install Homebrew first:" >&2
        echo "  https://brew.sh" >&2
        exit 1
    fi
    echo "[setup] installing python@3.13 via Homebrew..."
    brew install python@3.13
fi
echo "[setup] python3.13: $(python3.13 --version)"

# --- 1b. GitHub CLI + auth ------------------------------------------
# GH CLI gives the cleanest auth flow for cloning private repos:
# ``gh auth login`` runs once interactively in the user's terminal
# (browser-based device-code flow), then ``gh auth setup-git`` wires
# git's credential helper so subsequent clones / pulls just work.
if ! command -v gh >/dev/null 2>&1; then
    if ! command -v brew >/dev/null 2>&1; then
        echo "ERROR: brew not found; can't install gh CLI." >&2
        exit 1
    fi
    echo "[setup] installing gh CLI via Homebrew..."
    brew install gh
fi
echo "[setup] gh: $(gh --version | head -1)"

if ! gh auth status >/dev/null 2>&1; then
    cat >&2 <<EOF

===========================================================
GitHub authentication required.

Run this in YOUR TERMINAL (needs a browser for the device-code flow):

    gh auth login
    # Choose: GitHub.com → HTTPS → "Login with a web browser"
    gh auth setup-git

Then re-run this setup script:

    curl -sSL http://{{MASTER_TAILNET_NAME}}:5099/setup_remote.sh | bash

===========================================================
EOF
    exit 1
fi
# Ensure git's credential helper is wired to gh (idempotent).
gh auth setup-git >/dev/null

# --- 2. Clone / pull the repo ---------------------------------------
if [[ ! -d "$REPO_PATH/.git" ]]; then
    mkdir -p "$(dirname "$REPO_PATH")"
    echo "[setup] cloning $REPO_URL → $REPO_PATH"
    git clone "$REPO_URL" "$REPO_PATH"
else
    echo "[setup] repo already at $REPO_PATH; pulling latest"
    git -C "$REPO_PATH" pull --ff-only
fi
cd "$REPO_PATH"

# --- 3. venv + install ----------------------------------------------
# Homebrew's python@3.13 occasionally ships an ensurepip that fails
# on first venv creation (network / sandbox quirks). When that
# happens, fall back to ``--without-pip`` and bootstrap pip via the
# canonical get-pip.py — the resulting venv is identical.
if [[ ! -d ".venv-py313" ]]; then
    echo "[setup] creating .venv-py313"
    if ! python3.13 -m venv .venv-py313 2>&1; then
        echo "[setup] venv with ensurepip failed; falling back to" \
             "--without-pip + get-pip.py bootstrap..."
        # Wipe any partial venv from the failed attempt — get-pip.py
        # would otherwise refuse to install over a half-initialized
        # tree.
        rm -rf .venv-py313
        python3.13 -m venv --without-pip .venv-py313
        curl -sSL https://bootstrap.pypa.io/get-pip.py \
            | .venv-py313/bin/python3
    fi
fi
# If the user's previous attempt left a venv with no pip (most likely
# cause: ``--without-pip`` succeeded but bootstrap got interrupted),
# install pip now before we try to use it.
if [[ ! -x ".venv-py313/bin/pip" ]]; then
    echo "[setup] venv has no pip; bootstrapping via get-pip.py..."
    curl -sSL https://bootstrap.pypa.io/get-pip.py \
        | .venv-py313/bin/python3
fi
echo "[setup] upgrading pip"
.venv-py313/bin/pip install --quiet --upgrade pip
echo "[setup] pip install -e .[dev]"
.venv-py313/bin/pip install --quiet -e ".[dev]"
echo "[setup] pip install torch (native ARM wheel)"
.venv-py313/bin/pip install --quiet torch

# --- 4. authorized_keys ---------------------------------------------
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
AUTHKEYS="$HOME/.ssh/authorized_keys"
touch "$AUTHKEYS"
chmod 600 "$AUTHKEYS"
if [[ -n "$MASTER_PUBKEY" && "$MASTER_PUBKEY" != "{{"*"}}" ]]; then
    if grep -qF "$MASTER_PUBKEY" "$AUTHKEYS"; then
        echo "[setup] master pubkey already in authorized_keys"
    else
        echo "$MASTER_PUBKEY" >> "$AUTHKEYS"
        echo "[setup] appended master pubkey to authorized_keys"
    fi
else
    echo "[setup] WARNING: MASTER_PUBKEY not set — you'll need to add the" \
         "master's ssh-ed25519 public key to $AUTHKEYS manually."
fi

# --- 5. Smoke test ---------------------------------------------------
echo "[setup] running distributed-self-play tests..."
PYTHONPATH=src .venv-py313/bin/python -m pytest \
    tests/training/test_distributed.py --no-cov -q

# --- 6. Remaining manual steps --------------------------------------
LOCAL_HOSTNAME="$(scutil --get LocalHostName 2>/dev/null || hostname -s)"

echo ""
echo "===================================================================="
echo "Setup done. Manual steps remaining:"
echo ""
echo "1. Enable Remote Login:"
echo "   System Settings → General → Sharing → Remote Login: ON"
echo ""
echo "2. Install + log in to Tailscale (if not already):"
echo "   brew install --cask tailscale"
echo "   open /Applications/Tailscale.app"
echo "   (browser auth flow)"
echo ""
echo "3. From the master, smoke-test SSH to this machine:"
echo "   ssh $USER@$LOCAL_HOSTNAME 'echo ok'"
echo "   (or use the Tailscale name once Tailscale is up)"
echo ""
echo "4. From the master, push bootstrap weights + decks:"
echo "   python scripts/push_master_data.py \\"
echo "     --host $LOCAL_HOSTNAME --user $USER --repo-path $REPO_PATH"
echo ""
echo "5. Add this shard to shards_config.json on the master:"
cat <<EOF
   {
     "host": "$LOCAL_HOSTNAME",
     "n_games": 150,
     "user": "$USER",
     "repo_path": "$REPO_PATH",
     "venv_python": ".venv-py313/bin/python"
   }
EOF
echo "===================================================================="
