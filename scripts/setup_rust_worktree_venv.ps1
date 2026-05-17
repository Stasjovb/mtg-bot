# setup_rust_worktree_venv.ps1 -- purely-additive, opt-in build-tooling
# helper for the Rust-parallelization protocol (Mechanism A in
# docs/RUST_PARALLELIZATION_FEASIBILITY.md).
#
# WHAT IT DOES (and ONLY this): from inside a Rust feature worktree,
# stand up a worktree-local, fully-isolated Python venv that
#   (1) inherits the shared interpreter's torch/numpy via
#       --system-site-packages (NO 3 GB re-download),
#   (2) carries pytest-xdist locally (NOT in the inherited site),
#   (3) installs THIS worktree's freshly-built mtg_bot_engine wheel
#       into its OWN site-packages, which shadows the shared engine.
# The gate then runs as:
#   $env:PYTHONPATH="src"; .venv-wt\Scripts\python.exe -m pytest ... -n 4
#
# WHAT IT DOES NOT DO: it never writes to the shared .venv-py313,
# never runs `maturin develop` (which installs into the shared venv),
# never touches rust/src/ or any production code, and is a complete
# no-op for the existing single-Rust path (which keeps using the
# shared .venv-py313 + `maturin develop`). Not using this script ==
# today's behavior, byte-identical. This is the ROLLBACK story: stop
# invoking it and nothing changed.
#
# It is INTENTIONALLY not wired into any orchestrator default. The
# `<=1-Rust` rule remains the conservative default until the
# orchestrator explicitly opts in per docs/RUST_PARALLELIZATION_FEASIBILITY.md
# section 5.
#
# Usage (from the Rust worktree root, after `git worktree add`):
#   powershell -ExecutionPolicy Bypass -File scripts\setup_rust_worktree_venv.ps1
#   # then gate with:
#   $env:PYTHONPATH="src"
#   .venv-wt\Scripts\python.exe -m pytest tests\test_parity_smoke.py `
#     tests\test_cross_engine_etb_triggers.py tests\test_trajectory_parity.py `
#     tests\test_trajectory.py --no-cov -n 4
#   # on each subsequent Rust edit, just re-run this script (it is
#   # idempotent: reuses .venv-wt, rebuilds the wheel incrementally,
#   # force-reinstalls only the engine into .venv-wt).
#
# Exit codes: 0 = isolated venv ready; non-zero = a step failed
# (message on stderr). Fails LOUDLY -- a silent partial setup would
# let a Rust slice gate against a stale/shared .pyd.

[CmdletBinding()]
param(
    # Path to the SHARED venv's python.exe (the bootstrap interpreter).
    # Default assumes the canonical worktree layout
    # (mtg-bot-worktrees/<branch> sibling of mtg-bot/).
    [string]$SharedPython = "..\..\mtg-bot\.venv-py313\Scripts\python.exe",
    # Worktree-local isolated venv dir. `.venv-wt` matches the
    # existing `.venv-*/` .gitignore glob, so it is ignored for free.
    [string]$VenvDir = ".venv-wt",
    # Worktree-local wheel output dir (gitignored below; also matches
    # nothing the suite imports).
    [string]$WheelDir = "_wt_wheels"
)

# NB: deliberately NOT `$ErrorActionPreference = "Stop"`. Several
# steps below probe with native python `-c "import X"` whose failure
# is EXPECTED and handled via $LASTEXITCODE. Under "Stop", PS 5.1
# wraps a native command's stderr in a terminating NativeCommandError
# and aborts the script before the handling branch runs. We check
# $LASTEXITCODE explicitly after every native call and Fail loudly
# ourselves, so the script still fails fast on real errors.
$ErrorActionPreference = "Continue"

function Fail($msg) {
    [Console]::Error.WriteLine("setup_rust_worktree_venv: $msg")
    exit 1
}

# Run a native python "-c" import probe, swallow its stderr, and
# return $true iff it imported cleanly. Never terminates the script.
function Test-Import($py, $module) {
    & $py -c "import $module" 2>$null 1>$null
    return ($LASTEXITCODE -eq 0)
}

# --- 0. sanity: we must be in a worktree with rust/Cargo.toml ---
if (-not (Test-Path "rust\Cargo.toml")) {
    Fail "rust\Cargo.toml not found -- run this from the Rust worktree root."
}
$resolvedShared = (Resolve-Path $SharedPython -ErrorAction SilentlyContinue)
if ($null -eq $resolvedShared) {
    Fail "shared python not found at '$SharedPython' (pass -SharedPython to override)."
}
$resolvedShared = $resolvedShared.Path

# Guard: refuse to operate on the shared venv itself (this script is
# ONLY for worktree-local isolation; touching the shared venv is the
# exact race it exists to avoid).
$cwd = (Get-Location).Path
if ($resolvedShared -like "*\.venv-py313\*" -and $cwd -like "*\mtg-bot") {
    Fail "refusing to run in the main checkout -- this helper is worktree-only."
}

Write-Host "==> shared bootstrap python: $resolvedShared"

# --- 1. create/reuse the isolated --system-site-packages venv ---
if (Test-Path "$VenvDir\Scripts\python.exe") {
    Write-Host "==> reusing existing isolated venv: $VenvDir"
} else {
    Write-Host "==> creating isolated venv ($VenvDir, --system-site-packages)"
    & $resolvedShared -m venv $VenvDir --system-site-packages
    if ($LASTEXITCODE -ne 0) { Fail "venv creation failed." }
}
$wtPython = (Resolve-Path "$VenvDir\Scripts\python.exe").Path

# --- 2. ensure pytest-xdist locally (NOT in the inherited site) ---
if (-not (Test-Import $wtPython "xdist")) {
    Write-Host "==> installing pytest-xdist into the isolated venv"
    & $wtPython -m pip install -q pytest-xdist
    if ($LASTEXITCODE -ne 0) { Fail "pytest-xdist install failed." }
}

# --- 3. build THIS worktree's engine wheel (per-worktree rust/target;
#        incremental after the first build) ---
Write-Host "==> building worktree engine wheel (maturin build -o $WheelDir)"
if (Test-Path $WheelDir) { Remove-Item -Recurse -Force $WheelDir }
& $resolvedShared -m maturin build --release -m rust\Cargo.toml `
    -o $WheelDir -i $wtPython
if ($LASTEXITCODE -ne 0) { Fail "maturin build failed." }
$wheel = Get-ChildItem "$WheelDir\*.whl" | Select-Object -First 1
if ($null -eq $wheel) { Fail "no wheel produced in $WheelDir." }

# --- 4. install the engine into the ISOLATED venv only (force-reinstall
#        so re-runs pick up the new build; --no-deps so it never
#        touches torch/numpy, which come from the inherited site) ---
Write-Host "==> installing $($wheel.Name) into $VenvDir (isolated; shared venv untouched)"
& $wtPython -m pip install -q --no-deps --force-reinstall $wheel.FullName
if ($LASTEXITCODE -ne 0) { Fail "engine wheel install into isolated venv failed." }

# --- 5. verify the isolation actually holds (fail loudly if not) ---
$engineFile = (& $wtPython -c "import mtg_bot_engine; print(mtg_bot_engine.__file__)" 2>$null)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($engineFile)) {
    Fail "isolation check FAILED -- could not import mtg_bot_engine from the isolated venv."
}
$engineFile = $engineFile.Trim()
if ($engineFile -notlike "*$VenvDir*") {
    Fail "isolation check FAILED -- mtg_bot_engine resolved to '$engineFile' (expected inside $VenvDir). Do NOT gate with this venv."
}
$env:PYTHONPATH = "src"
& $wtPython -c "import mtg_bot, torch, numpy, xdist" 2>$null 1>$null
if ($LASTEXITCODE -ne 0) { Fail "post-setup import smoke (mtg_bot/torch/numpy/xdist) failed." }

$gatePy = Join-Path $VenvDir 'Scripts\python.exe'
Write-Host ""
Write-Host "==> isolated Rust worktree venv READY."
Write-Host ("    engine : " + $engineFile)
Write-Host ("    gate   : set PYTHONPATH=src, then run the 4-file gate with")
Write-Host ("             " + $gatePy)
Write-Host ("    see docs/RUST_PARALLELIZATION_FEASIBILITY.md section 4.2 for the exact gate command.")
exit 0
