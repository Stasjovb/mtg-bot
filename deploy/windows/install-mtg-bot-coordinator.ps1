<#
  install-mtg-bot-coordinator.ps1

  Registers a Windows Task Scheduler entry that launches the mtg-bot
  coordinator (`mtg_bot serve` on port 5099) at startup. The
  coordinator runs ONLY on the master machine — there is exactly one
  coordinator per cluster. Worker daemons run on every machine
  (master + remotes) via the separate `install-mtg-bot-worker.ps1`.

  Run from an elevated PowerShell prompt (the task runs as SYSTEM, so
  registration needs admin).

  Usage (example):

    .\install-mtg-bot-coordinator.ps1 `
      -RepoRoot "C:\Users\Gregg Keithley\Documents\Claude\Projects\mtg-bot" `
      -VenvPython "C:\Users\Gregg Keithley\Documents\Claude\Projects\mtg-bot\.venv-py313\Scripts\python.exe"

  Verify after install:

    Get-ScheduledTask -TaskName MTGBotCoordinator
    Get-ScheduledTaskInfo -TaskName MTGBotCoordinator

  Manually run / stop:

    Start-ScheduledTask -TaskName MTGBotCoordinator
    Stop-ScheduledTask -TaskName MTGBotCoordinator

  Uninstall:

    Unregister-ScheduledTask -TaskName MTGBotCoordinator -Confirm:$false
#>

param(
    [Parameter(Mandatory=$true)] [string] $RepoRoot,
    [Parameter(Mandatory=$true)] [string] $VenvPython,
    [int]    $Port = 5099,
    [string] $TaskName = "MTGBotCoordinator"
)

# Sanity-check paths so registration fails fast on typos.
if (-not (Test-Path $VenvPython)) {
    throw "Venv python not found at $VenvPython"
}
if (-not (Test-Path $RepoRoot)) {
    throw "Repo root not found at $RepoRoot"
}

function Quote-Arg($s) {
    # Wrap any value containing whitespace in double-quotes. The
    # ``-Argument`` parameter of ``New-ScheduledTaskAction`` is a
    # single concatenated command line, so a path that contains
    # spaces (e.g. ``C:\Users\Gregg Keithley\...``) splits into
    # multiple positional args inside the spawned python and
    # argparse errors out.
    if ("$s" -match "\s") { return '"' + $s + '"' }
    return "$s"
}

# The v2 endpoints (queue.db, /v2/stage/*, heartbeat poller) auto-
# activate when --queue-db-path defaults to
# <progress_dir>/coordinator_state/queue.db. We pass --repo-root
# explicitly so the queue.db ends up under the project's
# training_progress/ alongside runs.db, not somewhere relative to
# CWD when SYSTEM runs the task.
$Arguments = @(
    "-m", "mtg_bot.cli",
    "serve",
    "--port", "$Port",
    "--repo-root", (Quote-Arg $RepoRoot)
) -join " "

$Action = New-ScheduledTaskAction `
    -Execute $VenvPython `
    -Argument $Arguments `
    -WorkingDirectory $RepoRoot

$Trigger = New-ScheduledTaskTrigger -AtStartup

# Same restart-on-failure semantics as the worker daemon installer:
# up to 999 retries, 1 minute between each (Task Scheduler's minimum
# RestartInterval is PT1M; PT30S is rejected as out-of-range).
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1)

$Principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest

# (No PYTHONPATH here: the venv's editable install registered the
# mtg_bot package via ``pip install -e .``, so ``<venv>/python -m
# mtg_bot.cli serve`` resolves directly. ``$Action.Environment``
# isn't a property on the action object that
# ``New-ScheduledTaskAction`` returns; setting it raises.)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "MTG-Bot coordinator (port-5099 Flask: bundle/queue + v2 REST + heartbeat poller)" `
    -Force

Write-Host "Registered Task Scheduler entry '$TaskName'."
Write-Host "Run 'Start-ScheduledTask -TaskName $TaskName' to launch now,"
Write-Host "or reboot to let the At-Startup trigger fire."
Write-Host ""
Write-Host "Verify with: curl http://127.0.0.1:$Port/v2/healthz"
