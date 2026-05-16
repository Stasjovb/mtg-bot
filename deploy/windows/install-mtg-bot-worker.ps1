<#
  install-mtg-bot-worker.ps1

  Registers a Windows Task Scheduler entry that launches the mtg-bot
  worker daemon at startup and restarts it on failure with a 30s
  backoff. Run from an elevated PowerShell prompt (the task needs to
  run regardless of whether the user is logged in).

  Default principal: the **current user** with stored credentials —
  you'll be prompted once for your password, which Task Scheduler
  stores encrypted. This is required when the venv's base Python
  lives somewhere SYSTEM can't read (Microsoft Store Python under
  ``C:\Users\...\WindowsApps\``, or any per-user python.org install
  whose ACLs exclude SYSTEM). Pass ``-RunAsSystem`` if your base
  Python is system-wide (e.g. ``C:\Python313\`` from a python.org
  "Install for all users" install) and you'd rather the task run
  as ``NT AUTHORITY\SYSTEM``.

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
    [string] $WeightsCacheRoot = "",
    [switch] $RunAsSystem
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

function Quote-Arg($s) {
    # Wrap any value containing whitespace in double-quotes. The
    # ``-Argument`` parameter of ``New-ScheduledTaskAction`` is a
    # single concatenated command line, so a path that contains
    # spaces (e.g. ``C:\Users\Gregg Keithley\...``) splits into
    # multiple positional args inside the spawned python and
    # argparse errors out. The whole installer ran a few minutes
    # ago on a path with spaces and the SYSTEM-launched process
    # crashed instantly with no listener bound.
    if ("$s" -match "\s") { return '"' + $s + '"' }
    return "$s"
}

$Arguments = @(
    "-m", "mtg_bot.worker_daemon",
    "--host", $TailnetIP,
    "--port", "5198",
    "--n-workers", "$NWorkers",
    "--deck-pool-path", (Quote-Arg $DeckPoolPath),
    "--weights-cache-root", (Quote-Arg $WeightsCacheRoot)
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
    -RestartInterval (New-TimeSpan -Minutes 1)

# (No PYTHONPATH here: the venv's editable install registered the
# mtg_bot package on the venv's site-packages via `pip install -e .`,
# so `<venv>/python -m mtg_bot.worker_daemon` resolves the package
# directly. ``$Action.Environment`` is not a property on the action
# object that ``New-ScheduledTaskAction`` returns anyway — setting
# it raises.)

if ($RunAsSystem) {
    # Run as SYSTEM. Only works when the venv's base Python lives
    # somewhere SYSTEM can both READ and EXECUTE. Microsoft Store
    # Python (under ``C:\Users\...\WindowsApps\``) and per-user
    # python.org installs DO NOT meet this — the venv launcher will
    # fail to spawn the base interpreter with
    # "The file cannot be accessed by the system." Use the default
    # (current-user principal with stored creds) in those cases.
    $Principal = New-ScheduledTaskPrincipal `
        -UserId "SYSTEM" `
        -LogonType ServiceAccount `
        -RunLevel Highest

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Principal $Principal `
        -Description "MTG-Bot worker daemon (distributed self-play / eval, REST)" `
        -Force
} else {
    # Run as the current user. Task Scheduler stores the credentials
    # encrypted with LogonType=Password, so the task fires at
    # ``-AtStartup`` even when no one is logged in. This is the only
    # principal that works when the venv's base Python is per-user
    # (Store Python under WindowsApps, or python.org "Install for me
    # only"); SYSTEM literally cannot execute those binaries.
    $userName = "$env:USERDOMAIN\$env:USERNAME"
    $cred = Get-Credential -UserName $userName -Message "Password for $userName (task runs as this user, reboot-survivable)"
    if (-not $cred) { throw "No credentials supplied; aborting registration." }
    $plain = $cred.GetNetworkCredential().Password

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -User $userName `
        -Password $plain `
        -RunLevel Highest `
        -Description "MTG-Bot worker daemon (distributed self-play / eval, REST)" `
        -Force
}

Write-Host "Registered Task Scheduler entry '$TaskName'."
Write-Host "Run 'Start-ScheduledTask -TaskName $TaskName' to launch now,"
Write-Host "or reboot to let the At-Startup trigger fire."
