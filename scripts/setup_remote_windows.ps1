# Bootstrap a Windows 10/11 remote for distributed mtg-bot self-play.
#
# Run this on the Windows box AS ADMINISTRATOR. It:
#   1. Installs Python 3.13 via winget if missing.
#   2. Clones the mtg-bot repo (REPO_URL) to REPO_PATH if not present.
#   3. Creates .venv-py313, installs the package + CPU-only PyTorch
#      (workers don't use CUDA, so the GPU build is wasted disk).
#   4. Enables OpenSSH Server, opens the firewall, sets the service
#      to auto-start.
#   5. Sets up authorized_keys with the master's public key + the
#      Windows-specific ACL ceremony (silently rejected without it).
#   6. Prints the manual steps remaining (Tailscale install + login).
#
# Idempotent: re-running is safe and skips work that's already done.
#
# Variables filled in by ``scripts/serve_setup_scripts.py`` when this
# is fetched over HTTP from the master:
#   {{REPO_URL}}            → master's git remote
#   {{REPO_PATH}}           → default ``$env:USERPROFILE\Projects\mtg-bot``
#   {{MASTER_PUBKEY}}       → master's ssh-ed25519 public key
#   {{MASTER_TAILNET_NAME}} → for the printed "next steps"

#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"

# Resolve template variables (when fetched via curl) or env vars (when
# run directly).
if (-not $env:REPO_URL)            { $env:REPO_URL = "{{REPO_URL}}" }
if (-not $env:REPO_PATH)           { $env:REPO_PATH = "{{REPO_PATH}}" }
if (-not $env:MASTER_PUBKEY)       { $env:MASTER_PUBKEY = "{{MASTER_PUBKEY}}" }
if (-not $env:MASTER_TAILNET_NAME) { $env:MASTER_TAILNET_NAME = "{{MASTER_TAILNET_NAME}}" }

if ($env:REPO_URL -like "{{*}}") {
    Write-Error "REPO_URL not set. Fetch this script from the master's serve_setup_scripts.py, or set `$env:REPO_URL manually."
    exit 1
}

Write-Host "===================================================================="
Write-Host "mtg-bot remote setup (Windows)"
Write-Host "  REPO_URL  = $env:REPO_URL"
Write-Host "  REPO_PATH = $env:REPO_PATH"
Write-Host "===================================================================="

# --- 1. Python 3.13 -------------------------------------------------
$py313 = $null
try {
    $py313 = (& py -3.13 --version 2>$null)
} catch {}
if (-not $py313) {
    Write-Host "[setup] installing Python 3.13 via winget..."
    winget install --silent --accept-source-agreements --accept-package-agreements `
        --id Python.Python.3.13
    # Refresh PATH in current process so ``py`` resolves the new install.
    $env:Path = `
        [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + `
        [System.Environment]::GetEnvironmentVariable("Path", "User")
}
Write-Host "[setup] python: $(py -3.13 --version)"

# --- 2. git --------------------------------------------------------
try { & git --version | Out-Null } catch {
    Write-Host "[setup] installing git via winget..."
    winget install --silent --accept-source-agreements --accept-package-agreements `
        --id Git.Git
    $env:Path = `
        [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + `
        [System.Environment]::GetEnvironmentVariable("Path", "User")
}

# --- 3. Clone / pull the repo --------------------------------------
$repoPath = $env:REPO_PATH
if (-not (Test-Path "$repoPath\.git")) {
    $parent = Split-Path $repoPath
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    Write-Host "[setup] cloning $env:REPO_URL → $repoPath"
    git clone $env:REPO_URL $repoPath
} else {
    Write-Host "[setup] repo already at $repoPath; pulling"
    git -C $repoPath pull --ff-only
}
Set-Location $repoPath

# --- 4. venv + install ---------------------------------------------
if (-not (Test-Path ".venv-py313")) {
    Write-Host "[setup] creating .venv-py313"
    py -3.13 -m venv .venv-py313
}
$venvPy = "$repoPath\.venv-py313\Scripts\python.exe"
Write-Host "[setup] upgrading pip"
& $venvPy -m pip install --quiet --upgrade pip
Write-Host "[setup] pip install -e .[dev]"
& $venvPy -m pip install --quiet -e ".[dev]"
Write-Host "[setup] pip install torch (CPU-only, ~150 MB)"
& $venvPy -m pip install --quiet torch --index-url https://download.pytorch.org/whl/cpu

# --- 5. OpenSSH Server ---------------------------------------------
$ssh = Get-WindowsCapability -Online | Where-Object Name -like 'OpenSSH.Server*'
if ($ssh.State -ne 'Installed') {
    Write-Host "[setup] installing OpenSSH Server (optional feature)..."
    Add-WindowsCapability -Online -Name $ssh.Name | Out-Null
}
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic
if (-not (Get-NetFirewallRule -Name 'sshd' -ErrorAction SilentlyContinue)) {
    Write-Host "[setup] adding firewall rule for sshd..."
    New-NetFirewallRule -Name sshd -DisplayName 'OpenSSH Server' `
        -Enabled True -Direction Inbound -Protocol TCP `
        -Action Allow -LocalPort 22 | Out-Null
}

# --- 6. authorized_keys + ACL --------------------------------------
$sshDir = "$env:USERPROFILE\.ssh"
if (-not (Test-Path $sshDir)) {
    New-Item -ItemType Directory -Force -Path $sshDir | Out-Null
}
$authKeys = "$sshDir\authorized_keys"
if (-not (Test-Path $authKeys)) {
    New-Item -ItemType File -Force -Path $authKeys | Out-Null
}

if ($env:MASTER_PUBKEY -and ($env:MASTER_PUBKEY -notlike "{{*}}")) {
    $existing = Get-Content $authKeys -ErrorAction SilentlyContinue
    if ($existing -contains $env:MASTER_PUBKEY) {
        Write-Host "[setup] master pubkey already in authorized_keys"
    } else {
        Add-Content -Path $authKeys -Value $env:MASTER_PUBKEY
        Write-Host "[setup] appended master pubkey to authorized_keys"
    }
} else {
    Write-Warning "MASTER_PUBKEY not set — you'll need to add the master's ssh-ed25519 public key to $authKeys manually."
}

# Windows OpenSSH silently rejects authorized_keys files that aren't
# owned-by-you-only. icacls clears inheritance and grants the current
# user full control as the only ACE. (Without this the SSH login
# will quietly fall back to password auth and most users won't notice.)
icacls $authKeys /inheritance:r | Out-Null
icacls $authKeys /grant:r ("$env:USERNAME" + ":(F)") | Out-Null
Write-Host "[setup] authorized_keys permissions set"

# --- 7. Smoke test --------------------------------------------------
Write-Host "[setup] running distributed-self-play tests..."
$env:PYTHONPATH = "$repoPath\src"
& $venvPy -m pytest tests/training/test_distributed.py --no-cov -q

# --- 8. Remaining manual steps -------------------------------------
$hostname = $env:COMPUTERNAME
Write-Host ""
Write-Host "===================================================================="
Write-Host "Setup done. Manual steps remaining:"
Write-Host ""
Write-Host "1. Install + log in to Tailscale (browser auth flow):"
Write-Host "   https://tailscale.com/download/windows"
Write-Host ""
Write-Host "2. From the master, smoke-test SSH to this machine:"
Write-Host "   ssh $env:USERNAME@$hostname `"echo ok`""
Write-Host "   (use the Tailscale name once Tailscale is up)"
Write-Host ""
Write-Host "3. From the master, push bootstrap weights + decks:"
Write-Host "   python scripts/push_master_data.py ``"
Write-Host "     --host $hostname --user $env:USERNAME --repo-path $repoPath"
Write-Host ""
Write-Host "4. Add this shard to shards_config.json on the master:"
Write-Host "   {"
Write-Host "     ""host"": ""$hostname"","
Write-Host "     ""n_games"": 150,"
Write-Host "     ""user"": ""$env:USERNAME"","
Write-Host "     ""repo_path"": ""$($repoPath -replace '\\', '\\\\')"","
Write-Host "     ""venv_python"": "".venv-py313\\Scripts\\python.exe"""
Write-Host "   }"
Write-Host "===================================================================="
