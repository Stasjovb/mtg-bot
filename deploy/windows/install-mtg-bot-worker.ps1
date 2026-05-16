<#
  install-mtg-bot-worker.ps1

  Registers a Windows Task Scheduler entry that launches the mtg-bot
  worker daemon at startup and restarts it on failure with a 30s
  backoff. Run from an elevated PowerShell prompt (the task needs to
  run regardless of whether the user is logged in).

  Usage (example):

    .\install-mtg-bot-worker.ps1 `
      -TailnetIP "100.96.1.7" `
      -NWorkers 4 `
      -RepoRoot "C:\Users\gregg\projects\mtg-bot" `
      -VenvPython "C:\Users\gregg\projects\mtg-bot\.venv-py313\Scripts\python.exe"

  Verify after install:

    Get-ScheduledTask -TaskName MTGBotWorker
    Get-ScheduledTaskInfo -TaskName MTGBotWorker

  Manually run / stop:

    Start-ScheduledTask -TaskName MTGBotWorker
    Stop-ScheduledTask -TaskName MTGBotWorker

  Uninstall:

    Unregister-ScheduledTask -TaskName MTGBotWorker -Confirm:$false
#>

param(
    [Parameter(Mandatory=$true)] [string] $TailnetIP,
    [Parameter(Mandatory=$true)] [int]    $NWorkers,
    [Parameter(Mandatory=$true)] [string] $RepoRoot,
    [Parameter(Mandatory=$true)] [string] $VenvPython,
    [string] $TaskName = "MTGBotWorker",
    [string] $DeckPoolPath = "",
    [string] $WeightsCacheRoot = ""
)

if (-not $DeckPoolPath) {
    $DeckPoolPath = Join-Path $RepoRoot "data\17lands\eoe_decks.json.gz"
}
if (-not $WeightsCacheRoot) {
    $WeightsCacheRoot = Join-Path $RepoRoot "trained_weights"
}

# Sanity-check the venv python exists. Catch typos before registering
# a scheduled task that immediately fails on first run.
if (-not (Test-Path $VenvPython)) {
    throw "Venv python not found at $VenvPython"
}
if (-not (Test-Path $RepoRoot)) {
    throw "Repo root not found at $RepoRoot"
}

$Arguments = @(
    "-m", "mtg_bot.worker_daemon",
    "--host", $TailnetIP,
    "--port", "5198",
    "--n-workers", "$NWorkers",
    "--deck-pool-path", $DeckPoolPath,
    "--weights-cache-root", $WeightsCacheRoot
) -join " "

$Action = New-ScheduledTaskAction `
    -Execute $VenvPython `
    -Argument $Arguments `
    -WorkingDirectory $RepoRoot

$Trigger = New-ScheduledTaskTrigger -AtStartup

# Restart-on-failure semantics: up to 999 retries, 30s between each.
# Matches the systemd / launchd defaults in this repo so all three
# platforms behave the same way.
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Seconds 30)

# Run as SYSTEM so the task survives user logout / reboot. The mtg-bot
# venv needs to be readable by SYSTEM (it usually is — venvs live under
# the user profile but are world-readable by default).
$Principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest

# Set PYTHONPATH for the task via an environment variable in the
# action. Task Scheduler doesn't carry over the calling shell's env,
# so we set it here.
$Action.Environment = "PYTHONPATH=$(Join-Path $RepoRoot 'src')"

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "MTG-Bot worker daemon (distributed self-play / eval, REST)"

Write-Host "Registered Task Scheduler entry '$TaskName'."
Write-Host "Run 'Start-ScheduledTask -TaskName $TaskName' to launch now,"
Write-Host "or reboot to let the At-Startup trigger fire."
