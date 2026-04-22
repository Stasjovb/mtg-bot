# Serve the MTG bot UI on 0.0.0.0 so tailnet peers (phone, laptop) can reach it.
#
# Usage (from the repo root):
#     powershell -ExecutionPolicy Bypass -File scripts\serve.ps1
# Optional:
#     scripts\serve.ps1 -Port 5001
#
# On the very first run the firewall rule step needs admin. If you launched
# PowerShell normally, that step is skipped with a warning — the server will
# still start, but tailnet peers won't be able to reach it until port $Port is
# allowed through Windows Defender Firewall. Re-run as admin once to fix.

param(
    [int]$Port = 5000
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Error "Virtual environment not found at $venvPython. Run 'python -m venv .venv' and 'pip install -e \".[dev]\"' first."
    exit 1
}

# -- Firewall rule (idempotent; needs admin to create the first time) ------
$ruleName = "MTG Bot UI (TCP $Port)"
$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if (-not $existing) {
    $isAdmin = ([Security.Principal.WindowsPrincipal] `
        [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
            [Security.Principal.WindowsBuiltInRole]::Administrator)
    if ($isAdmin) {
        Write-Host "Creating firewall rule '$ruleName' on Private+Domain profiles..."
        New-NetFirewallRule -DisplayName $ruleName `
            -Direction Inbound -LocalPort $Port -Protocol TCP `
            -Action Allow -Profile Private,Domain | Out-Null
    } else {
        Write-Warning "Not elevated — skipping firewall rule setup."
        Write-Warning "To enable tailnet access, run this script once from an elevated PowerShell,"
        Write-Warning "  or manually: New-NetFirewallRule -DisplayName '$ruleName' -Direction Inbound -LocalPort $Port -Protocol TCP -Action Allow -Profile Private,Domain"
    }
} else {
    Write-Host "Firewall rule '$ruleName' already present."
}

# -- Show Tailscale info -------------------------------------------------
try {
    $ip = (& tailscale ip -4 2>$null | Select-Object -First 1).Trim()
    if ($ip) {
        Write-Host ""
        Write-Host "Tailscale IP:  http://${ip}:${Port}" -ForegroundColor Green
        $hostname = (& tailscale status --self=true 2>$null | Select-Object -First 1)
        if ($hostname) {
            $tsName = ($hostname -split '\s+')[1]
            if ($tsName) {
                Write-Host "MagicDNS:      http://${tsName}:${Port}" -ForegroundColor Green
            }
        }
        Write-Host ""
    } else {
        Write-Warning "Tailscale is installed but no tailnet IP was returned. Is it logged in?"
    }
} catch {
    Write-Warning "tailscale CLI not found on PATH — install Tailscale or add it to PATH."
}

# -- Run the server ------------------------------------------------------
Write-Host "Starting server on 0.0.0.0:$Port (Ctrl+C to stop)..."
& $venvPython -m mtg_bot.ui --host 0.0.0.0 --port $Port
