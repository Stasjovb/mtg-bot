# Rust parallelization feasibility — can ≥2 Rust agents build/test concurrently?

**Status: VERIFIED feasibility investigation + design + verdict.**
Every claim below was checked against the live repo/tooling on
`main` `3e5bc6fe` (not inferred from labels). This doc answers the
single highest-leverage infra question in the current Rust-serial
phase: the campaign's parallelizable non-Rust frontier is largely
exhausted and throughput is gated on the SINGLE Rust agent
serializing through `maturin develop --release` (the `≤1-Rust`
rule). Relaxing it safely directly multiplies the campaign's true
bottleneck.

**This doc does NOT relax the `≤1-Rust` rule.** That is an
orchestrator decision on this evidence. This doc delivers the
verified mechanism analysis + the recommended protocol change +
an honest verdict + a quantified cost/benefit, and (companion
slice) a purely-additive, gated-green build-tooling helper that
does NOT alter the existing single-Rust path.

---

## 0. TL;DR

- **The race is EXACTLY ONE thing: the shared site-packages
  install step.** `maturin develop --release -m rust/Cargo.toml`
  builds a wheel then `pip install --force-reinstall`s it into the
  **single shared** `.venv-py313\Lib\site-packages\mtg_bot_engine\`.
  Two concurrent installs interleave pip's rename/extract on the
  *same* directory → corruption. **Empirically observed live**:
  even a *single* `maturin develop` left a `~01_bot_engine`
  orphan stub in shared site-packages because the running
  interpreter held the old `.pyd` (§2).
- **The cargo BUILD-dir race does NOT exist.** Each worktree is a
  full checkout with its **own** `rust/target/` (verified: 217 MB,
  separate path, `rust/target/` is gitignored, no
  `CARGO_TARGET_DIR` / `.cargo/config.toml` override). Two
  worktrees compiling concurrently write to **disjoint** target
  dirs. The shared `~/.cargo/registry` is concurrency-safe by
  cargo's own file locks. **So the only thing to isolate is the
  install, not the build.** (§2)
- **The cheap isolation works and is empirically validated.** A
  per-worktree `python -m venv --system-site-packages` venv:
  inherits the shared `torch`/`numpy` (no 3 GB re-download — the
  expensive cost vanishes), and a locally-installed
  `mtg_bot_engine` wheel **shadows** the shared one (local
  `site-packages` precedes inherited system paths in `sys.path`).
  Verified: an isolated venv ran a full gate file (230 passed)
  against the worktree's own engine, fully independent of the
  shared venv, both directions (§3, §4).
- **Verified incremental cost ≈ 15 s one-time per Rust worktree**:
  `venv --system-site-packages` (~6 s) + `pip install
  pytest-xdist` (~3 s, pure-python, NOT in the inherited
  Store user-site) + per-worktree engine-wheel install (~3 s).
  No torch re-download. The Rust build itself is unchanged
  (40 s clean / ~1 s incremental into the per-worktree
  `rust/target/`).
- **VERDICT: relaxing `≤1-Rust` to `≥2` is SAFE and worth it via
  the per-worktree isolated venv (Mechanism A).** It is strictly
  better than the build-serialization lock (Mechanism D) because
  the lock still serializes a 40 s-class critical section on every
  Rust slice and adds a cross-process filesystem-mutex failure
  mode, whereas the isolated venv removes the shared resource
  entirely (no mutex, no critical section, no residual race).
  Mechanism D is the recommended **fallback** if isolated-venv
  setup proves flaky in practice. **Recommendation: adopt
  Mechanism A; keep `≤1-Rust` as the conservative default until
  the helper (`scripts/setup_rust_worktree_venv.ps1`, companion
  slice) has been exercised on ≥2 real back-to-back Rust slices,
  then the orchestrator flips to `≤2-Rust`.**

---

## 1. What the gate/harness actually imports (verified)

The cross-engine harness and gate import a **compiled top-level
package** `mtg_bot_engine`, NOT a submodule of `mtg_bot`:

- Import sites (`grep mtg_bot_engine src/`): exactly three —
  `src/mtg_bot/parity/cross_engine.py` (`build_rust_state`,
  `import mtg_bot_engine` at :8905; `mtg_bot_engine.Registry()`,
  `mtg_bot_engine.make_state`), `src/mtg_bot/parity/trajectory.py`,
  `src/mtg_bot/parity/effect_coverage.py`. All do a bare
  `import mtg_bot_engine`.
- `import mtg_bot_engine` resolves to
  `.venv-py313\Lib\site-packages\mtg_bot_engine\__init__.py`
  (verified via `mtg_bot_engine.__file__`), whose body is
  `from .mtg_bot_engine import *` — the actual native artifact is
  `.venv-py313\Lib\site-packages\mtg_bot_engine\mtg_bot_engine.cp313-win_amd64.pyd`
  (1.5 MB) + a `mtg_bot_engine.pdb`.
- **Critical asymmetry vs. the pure-Python side.** The project's
  `PYTHONPATH=src` worktree convention isolates only `mtg_bot`
  (its `__editable__.mtg_bot-0.0.1.pth` points at the *main
  checkout's* `src`, and `PYTHONPATH=src` shadows that with the
  worktree `src`). **`mtg_bot_engine` is NOT under `src/`**
  (verified: `src/` contains only `mtg_bot` and `mtg_bot.egg-info`;
  there is no `src/mtg_bot_engine`). So **`PYTHONPATH=src` does
  NOT isolate the engine** — every worktree's gate run, no matter
  what `PYTHONPATH` is, resolves the *same* shared
  `site-packages/mtg_bot_engine`. This is the structural root of
  the `≤1-Rust` rule.
- The maturin project is `rust/pyproject.toml`
  (`build-backend = "maturin"`, `module-name = "mtg_bot_engine"`,
  `[lib] crate-type = ["cdylib"]`). `maturin develop` "installs
  the crate as module in the current virtualenv" — i.e. into the
  venv resolved from `VIRTUAL_ENV` (the gate command sets
  `VIRTUAL_ENV=.venv-py313`).

---

## 2. The EXACT race (verified live, both candidate races analyzed
distinctly)

### 2a. The install race — REAL (this is the whole `≤1-Rust` reason)

`maturin develop --release -m rust/Cargo.toml` does two phases:

1. **Build**: `cargo build --release` → a wheel in a fresh OS
   temp dir
   (`...\AppData\Local\Temp\.tmpXXXX\mtg_bot_engine-0.0.1-cp313-cp313-win_amd64.whl`).
2. **Install**: `pip --disable-pip-version-check install --no-deps
   --force-reinstall <that wheel>` into the **`VIRTUAL_ENV`**
   site-packages, then `Setting installed package as editable`.

The shared resource is **the single
`.venv-py313\Lib\site-packages\mtg_bot_engine\` directory**. Phase
2's `--force-reinstall` on Windows: pip renames the existing
`mtg_bot_engine` dir to a `~`-prefixed stub before unpacking the
new one. **Observed live in this investigation** (one timed
`maturin develop` run, no concurrency):

```
WARNING: Failed to remove contents in a temporary directory
'...\.venv-py313\Lib\site-packages\~01_bot_engine'.
You can safely remove it manually.
```

That orphan `~01_bot_engine` stub is the race made visible: pip
could not delete the old tree because **a process held the loaded
`.pyd`** (a concurrent gate run importing `mtg_bot_engine`, or even
the same interpreter). With ONE Rust agent this is a harmless
self-healing wart (the new `.pyd` still landed; I cleaned the stub
and confirmed `import mtg_bot_engine` works). With **TWO**
concurrent `maturin develop`s targeting the same site-packages,
their rename → unpack → editable-pth steps interleave on the same
path: one install's `--force-reinstall` deletes/renames the tree
the other is mid-unpack into → a half-written `.pyd`, a missing
`__init__.py`, or a `dist-info`/`RECORD` mismatch. A gate run
importing `mtg_bot_engine` during that window gets a corrupt or
stale extension. **This is the `.pyd`-race the handoff cites, and
it is real and verified.**

Compounding factor: a running gate process (xdist `-n 4` → 5
processes) holds the `.pyd` open; Windows refuses to unlink a
loaded DLL, so even serialized installs can leave the orphan stub
until the importing processes exit. Concurrency turns "leaves a
stub" into "corrupts the live tree."

### 2b. The cargo build-dir race — DOES NOT EXIST (verified)

Worktrees are **full checkouts**, each with its own
`rust/target/`:

- `mtg-bot-worktrees/rust-warp-phase1-r63/rust/target` exists,
  217 MB, a **distinct path** from
  `mtg-bot/rust/target` (verified separate dirs).
- `rust/target/` is gitignored (`.gitignore:96`).
- No `CARGO_TARGET_DIR` env, no `.cargo/config.toml` / `rust/.cargo/config.toml`
  redirecting the target dir (verified absent). Default cargo
  behavior = target dir is per-crate-checkout
  (`<checkout>/rust/target`).

So two worktrees running `cargo build` concurrently compile into
**disjoint** target directories — no `.cargo-lock` contention on
the build artifacts. The only shared cargo state is the global
`~/.cargo/registry` (index + cache + src), which **cargo itself
guards** with package-cache file locks and is designed for
concurrent multi-project use. **The build half is already
parallel-safe.** Isolation effort must target *only* the install
(§2a), not the build.

---

## 3. Candidate isolation mechanisms (each with a verified verdict
+ cost)

### Mechanism A — per-worktree isolated venv (`--system-site-packages`)  ★ RECOMMENDED

**Setup**: per Rust worktree, once:
`<shared-venv>\Scripts\python.exe -m venv _wt_venv
--system-site-packages` → `_wt_venv\Scripts\python.exe -m pip
install pytest-xdist` → build a wheel with `maturin build
--release -m rust/Cargo.toml -o _wt_wheels -i
_wt_venv\Scripts\python.exe` → `_wt_venv\Scripts\python.exe -m pip
install --no-deps --force-reinstall _wt_wheels\*.whl`. The gate
then runs as `PYTHONPATH=src _wt_venv\Scripts\python.exe -m pytest
... -n 4`. On each subsequent Rust edit: re-`maturin build -o
_wt_wheels` (~1 s incremental) + `pip install --no-deps
--force-reinstall` into `_wt_venv` (~3 s) — **never touches the
shared venv**.

**Why it isolates the `.pyd` fully (verified, both directions):**

- `--system-site-packages` venv inherits the base interpreter's
  site → `torch`, `numpy` resolve from the inherited system site
  (verified: `import torch` →
  `...PythonSoftwareFoundation.Python.3.13...\site-packages\torch`).
  **No 3 GB torch re-download** — this kills the only expensive
  part of a naive full per-worktree venv.
- A locally pip-installed `mtg_bot_engine` wheel lands in the
  venv's own `site-packages`, which sits at `sys.path` index 6 —
  **before** all inherited system paths (index 7+) (verified
  `sys.path` dump). So `import mtg_bot_engine` resolves to the
  **worktree's** engine, NOT the shared one (verified:
  `_wt_venv\...\site-packages\mtg_bot_engine\__init__.py`).
- The shared `.venv-py313` engine is **untouched** and still
  resolves to its own path (verified — bidirectional isolation).
- `PYTHONPATH=src` still does its existing job: `import mtg_bot` →
  worktree `src/mtg_bot` (verified). So `mtg_bot` (pure Python,
  the worktree's edits) AND `mtg_bot_engine` (the worktree's Rust
  build) are both correctly worktree-local.
- **End-to-end proof**: an isolated `--system-site-packages` venv
  (engine wheel installed, `xdist` NOT yet — see cost) ran
  `pytest tests/test_trajectory.py --no-cov` → **230 passed in
  43 s** against the worktree's own engine.

**Cost (verified, incremental — not estimated):**

| Step | Time | Shared? |
|---|---:|---|
| `python -m venv --system-site-packages _wt_venv` | ~6 s | no |
| `pip install pytest-xdist` (pure-py; NOT in inherited site) | ~3 s | no |
| `maturin build -o _wt_wheels` (incremental) | ~1 s | no |
| `pip install --no-deps engine wheel` into `_wt_venv` | ~3 s | no |
| **One-time per-worktree total** | **≈ 15 s** | **none** |
| Per-edit rebuild+reinstall thereafter | ≈ 4 s | none |
| (Clean Rust build, first time, into per-wt `rust/target`) | ≈ 40 s | none |

`_wt_venv` / `_wt_wheels` are worktree-local scratch — add to
`.gitignore` (the `.venv-*/` glob already covers `_wt_venv` if
named `.venv-wt`; recommend naming it `.venv-wt` to reuse the
existing ignore + the existing
`PYTHONPATH=src .venv-*/Scripts/python.exe` muscle memory).

**Verdict: FEASIBLE, cheapest, fully isolating, zero residual
race. RECOMMENDED.** The only correctness caveat is the
`sys.path` precedence (local site before inherited system) — which
is CPython venv default behavior and was verified, not assumed.

### Mechanism B — `maturin build -o <wheel>` + install into an isolated prefix

This is a strict subset of Mechanism A (A *is* "build a wheel +
install into an isolated venv"). Standalone (e.g. `pip install
--target <dir>` instead of a venv) is **worse**: `--target` dirs
don't get `sys.path` precedence without manual `PYTHONPATH`
surgery, and you'd still need torch/numpy/pytest reachable. No
advantage over A. **Verdict: dominated by A; not recommended
standalone.** (A already uses `maturin build -o`.)

### Mechanism C — per-worktree `CARGO_TARGET_DIR`

`CARGO_TARGET_DIR` (or default per-checkout `rust/target`)
de-conflicts the **build** dir. But §2b proved the build-dir race
**does not exist** (worktrees already have disjoint
`rust/target`). `CARGO_TARGET_DIR` is therefore a **no-op for the
real race** — it does nothing about the shared site-packages
install (§2a). **Verdict: addresses a non-problem; insufficient
alone. (Harmless to set explicitly for clarity, but not the
fix.)**

### Mechanism D — build-serialization filesystem lock (shrink the mutex)

A cross-process advisory lock (e.g. an exclusive
`.git/rust-build.lock` held only across `maturin develop`) so Rust
agents serialize **only** the build+install critical section, not
their whole multi-slice run. This shrinks the serialization
window from "one Rust agent end-to-end (hours)" to "one `maturin
develop` at a time (~40 s clean / ~5 s incremental)."

**Pros**: minimal protocol change; no per-worktree venv; keeps the
single shared venv (simpler mental model; the gate command in the
handoff is unchanged).

**Cons (the reason it's the fallback, not the pick):**

- Still serializes a 40 s-class section on **every** Rust slice's
  every rebuild, and Rust TDD slices rebuild many times — the
  serialized wall adds up.
- The §2a Windows-DLL-lock problem **persists**: if agent X holds
  the lock and installs while agent Y's gate (in the shared venv)
  has `mtg_bot_engine` imported across 5 xdist procs, pip still
  can't delete the loaded tree → the orphan-stub / corruption
  window is only *narrowed*, not *removed*. A correct lock must
  also quiesce all gate runs against the shared venv during an
  install — that effectively re-serializes testing too, eroding
  the benefit.
- New failure mode: stale lock after a crashed agent (needs a
  TTL/PID-liveness reaper — more orchestrator complexity).

**Verdict: FEASIBLE and a real improvement over `≤1-Rust`
end-to-end, but strictly inferior to A** because A *removes* the
shared resource (no lock, no critical section, no residual
DLL-lock window) whereas D only *shrinks* it and inherits the
Windows-loaded-DLL hazard. **Recommended only as the fallback** if
A's per-worktree venv setup proves operationally flaky.

---

## 4. Recommended orchestrator-protocol change (Mechanism A)

**Goal: allow `≤2` concurrent Rust agents (start conservative;
the structural argument generalizes to `≤N`, but 2 is the
prudent first step — it doubles the bottleneck for ~15 s/agent
setup).**

### 4.1 Per-Rust-agent isolation setup (added to the Rust slice
preamble)

After `git worktree add ... -b feature/rust-<slice> main`, before
any Rust edit:

```powershell
# from the worktree root; SHARED venv python bootstraps the isolated one
$shared = "..\..\mtg-bot\.venv-py313\Scripts\python.exe"
& $shared -m venv .venv-wt --system-site-packages
& .venv-wt\Scripts\python.exe -m pip install -q pytest-xdist
# build + install the worktree's OWN engine into .venv-wt only
& $shared -m maturin build --release -m rust\Cargo.toml `
    -o _wt_wheels -i .venv-wt\Scripts\python.exe
& .venv-wt\Scripts\python.exe -m pip install -q --no-deps `
    --force-reinstall (Get-ChildItem _wt_wheels\*.whl).FullName
```

A purely-additive helper script (`scripts/setup_rust_worktree_venv.ps1`,
companion slice) wraps exactly this — it touches **nothing
shared**, is opt-in, and the existing single-Rust path (shared
`.venv-py313` + `maturin develop`) keeps working byte-identically
when the helper is not used.

### 4.2 Gate against the right `.pyd`

The Rust slice's gate command changes **only** the interpreter
path — from the shared
`..\..\mtg-bot\.venv-py313\Scripts\python.exe` to the worktree's
`.venv-wt\Scripts\python.exe`:

```powershell
$env:PYTHONPATH = "src"
& .venv-wt\Scripts\python.exe -m pytest `
  tests\test_parity_smoke.py tests\test_cross_engine_etb_triggers.py `
  tests\test_trajectory_parity.py tests\test_trajectory.py --no-cov -n 4
```

`PYTHONPATH=src` → worktree `mtg_bot`; `.venv-wt` →
worktree-local `mtg_bot_engine`. **Non-Rust slices are
unchanged** — they keep using the shared `.venv-py313` (no engine
edits, no isolation needed).

### 4.3 Merges still serialize on `main` (unchanged)

Parallelizing the *build* does not change the merge protocol.
Each Rust agent still: rebase cleanly on `origin/main`, run the
gate (now in its isolated venv) green, `merge --no-ff`, push.
Two Rust agents merging close in time is the existing git
fast-forward/rebase contention, already handled by the
rebase-before-merge step. **The orchestrator's post-merge
cron-resync still serializes** (it rebuilds the `.pyd` on `main`
in the shared venv — that is a single orchestrator action, not a
slice action, and is already deferred/consolidated).

### 4.4 Residual races after Mechanism A

- **Shared `~/.cargo/registry`**: cargo-guarded, concurrency-safe
  by design. Not a race.
- **Disjoint `rust/target` per worktree**: no race (§2b).
- **Isolated `.venv-wt` per worktree**: no shared write target —
  no race.
- **The shared `.venv-py313`**: now written **only** by the
  orchestrator's serialized post-merge resync and by non-Rust
  slices that never run `maturin` — no concurrent-`maturin`
  writer → **the §2a race is structurally eliminated** for the
  parallel Rust agents.
- **One real residual**: the `main` checkout's shared
  `.venv-py313` engine can be *stale* relative to a just-merged
  Rust change until the orchestrator's post-merge resync rebuilds
  it. This is **identical to today's behavior** (the resync is
  already deferred/consolidated under `≤1-Rust`) — not a new
  race, and non-Rust slices already tolerate it (they test
  Python, the engine API is stable across a slice).

### 4.5 Rollback

Mechanism A is opt-in per slice. Rollback = "orchestrator stops
dispatching a 2nd Rust agent; Rust slices drop the `.venv-wt`
preamble and use the shared `.venv-py313` + `maturin develop` as
before." Zero code to revert (the helper script is additive and
unused on rollback). The `≤1-Rust` rule is the safe default the
whole time until the orchestrator explicitly flips to `≤2`.

---

## 5. Verdict + quantified cost/benefit

**Is relaxing `≤1-Rust` to `≥2` SAFE and worth the complexity?
YES — via Mechanism A (per-worktree `--system-site-packages` venv
+ per-worktree engine wheel).** It is the pragmatic win *and* the
correct one: it does not merely shrink the mutex (Mechanism D), it
**removes the shared resource** so there is no mutex, no critical
section, and no residual Windows-loaded-DLL corruption window for
the parallel Rust agents.

**Quantified throughput gain.** The current bottleneck is the
serial Rust queue (R74-2, I23, legal_decisions Slice 1, Tier-C
target-seating, future Effect closes). With `≤1-Rust`, queue
wall = Σ(slice durations). With `≤2-Rust` via Mechanism A, two
independent Rust slices proceed concurrently (disjoint
`rust/target`, disjoint `.venv-wt`, disjoint `cargo` builds);
queue wall ≈ Σ/2 for the parallelizable subset (slices touching
disjoint `rust/src/` regions — the `multiple-pymethods` split in
`Cargo.toml` is *explicitly there* to let parallel Rust slices
grow methods on `GameState` without block conflicts, so the Rust
backlog is substantially parallelizable). **Expected effect:
~1.7–2× throughput on the campaign's true bottleneck** (not a
clean 2× because merges still serialize on `main` and some Rust
slices are sequenced-dependent, e.g. the Tier-C shared
`first_legal_trigger_target` micro-slice gating its 2 per-card
slices).

**Cost.** ~15 s one-time isolated-venv setup per Rust worktree
(verified, no torch re-download) + ~4 s per rebuild + one
additive ~40-line helper script to maintain + the orchestrator
learning to dispatch a 2nd Rust agent and use the `.venv-wt`
interpreter in the gate. **The setup cost is ~0.1% of a typical
multi-hour Rust slice. The maintenance cost is one small opt-in
script.** Cost/benefit is strongly favorable: ≈15 s/slice to
roughly halve the campaign's dominant serial wall.

**Is `≤1-Rust` genuinely the right call / must the bottleneck be
accepted? NO** — the `≤1-Rust` rule is a *correct response to a
real race*, but the race is narrower than the rule. The rule
serializes Rust agents *end-to-end* to protect a *shared
site-packages install*; Mechanism A isolates that install per
worktree at trivial cost, so the end-to-end serialization is
**over-broad** and can be safely relaxed. The bottleneck does
**not** have to be accepted.

**Recommended sequencing for the orchestrator (decision is
yours, on this evidence):**

1. Land the additive helper `scripts/setup_rust_worktree_venv.ps1`
   (companion slice — purely additive, gated-green, single-Rust
   path unchanged).
2. Keep `≤1-Rust` as the default for the **next** Rust slice but
   have that slice *use* the helper (dogfood the isolated venv on
   one real slice; confirm gate-green in `.venv-wt`).
3. If the dogfood slice is clean, flip the orchestrator to
   `≤2-Rust` and dispatch the next two disjoint Rust slices
   concurrently, each with its own `.venv-wt`.
4. If isolated-venv setup proves operationally flaky on Windows
   (e.g. `--system-site-packages` precedence surprises on a
   future Python/venv upgrade), fall back to Mechanism D
   (build-serialization lock) — still better than `≤1-Rust`
   end-to-end, just inferior to A.

---

## 6. Verification log (what was actually run, on `main`
`3e5bc6fe`)

- `grep mtg_bot_engine src/` → 3 import sites; all bare
  `import mtg_bot_engine`. `mtg_bot_engine.__file__` →
  shared-venv site-packages. `src/` has no `mtg_bot_engine` →
  `PYTHONPATH=src` cannot isolate it.
- `rust/pyproject.toml` = maturin backend, `module-name =
  mtg_bot_engine`, `crate-type = ["cdylib"]`.
- Timed `maturin develop --release -m rust/Cargo.toml` in a fresh
  worktree with per-worktree `CARGO_TARGET_DIR`: **40 s** clean;
  the run **emitted the live `~01_bot_engine` orphan-stub
  warning** in shared site-packages (the race, observed without
  concurrency); cleaned the stub, `import mtg_bot_engine` OK.
- Worktree `rust/target` = 217 MB, distinct path from main's; no
  `CARGO_TARGET_DIR` / `.cargo/config.toml`; `rust/target/`
  gitignored → disjoint per-worktree build dirs (build race
  absent).
- `maturin build --release -o _wt_wheels -i <python>`: **1 s**
  incremental (reused the per-worktree `rust/target`); wrote the
  wheel to a per-worktree dir, touched nothing shared.
- `python -m venv _wt_venv --system-site-packages` (~6 s) +
  `pip install --no-deps <engine wheel>` (~3 s): isolated venv
  resolved its **own** `mtg_bot_engine` (verified `__file__`);
  shared venv engine unchanged (bidirectional isolation).
- `sys.path` of the `--system-site-packages` venv: local
  `site-packages` at index 6, inherited system at 7+ → local
  engine shadows the shared one (verified). `import torch` in
  that venv resolved from the **inherited** system site (no
  re-download).
- `PYTHONPATH=src _wt_venv\Scripts\python.exe -m pytest
  tests/test_trajectory.py --no-cov` → **230 passed in 43 s**
  against the worktree's isolated engine.
- `xdist` is NOT in the inherited Store user-site →
  `pip install pytest-xdist` (~3 s, pure-py) is the only extra
  per-worktree dep for the `-n 4` gate.
- All test scratch (`_wt_venv*`, `_wt_wheels`, `rust/target`)
  removed; worktree clean.

### 6a. Companion helper end-to-end validation

The additive helper `scripts/setup_rust_worktree_venv.ps1`
(Mechanism A, opt-in, touches nothing shared) was run
end-to-end in this docs worktree:

- `setup_rust_worktree_venv.ps1` from a clean state: created
  `.venv-wt` (`--system-site-packages`), installed
  `pytest-xdist`, did a **clean** Rust compile (34.5 s) into the
  per-worktree `rust/target`, built+installed the engine wheel
  into `.venv-wt` only, and its built-in isolation check
  confirmed `mtg_bot_engine` resolved to
  `...\docs-rust-parallelization-feasibility\.venv-wt\Lib\site-packages\mtg_bot_engine\__init__.py`.
  Exit 0; total 49 s clean.
- The **full 4-file gate** then ran against that isolated venv:
  **`1518 passed in 152 s` (0 fail)** — byte-identical to the
  `main` green count (`1518`). Proves the isolated venv is a
  fully-functional, gate-equivalent environment.
- After the run, `import mtg_bot_engine` from the **shared**
  `.venv-py313` still resolved to its own untouched path
  (`...\mtg-bot\.venv-py313\Lib\site-packages\mtg_bot_engine\__init__.py`)
  — the helper provably never wrote to the shared venv, so the
  existing single-Rust path is byte-identical with or without
  the helper. Rollback guarantee, verified.

The helper is intentionally NOT wired into any orchestrator
default — `≤1-Rust` stays the conservative default until the
orchestrator opts in per §5.

(Investigation slice — docs-only + companion additive helper.
Does NOT relax `≤1-Rust`; that is the orchestrator's call on
this evidence. Does NOT touch `rust/src/`, production code,
`docs/POOL_PARITY.md`, `docs/residue_worklist.json`,
`docs/SUBSYSTEM_ROADMAP.md`, `docs/EOE_PROBE_READINESS_AUDIT.md`,
the protected `test_audit_safe_trigger_*` tests, or
sibling-owned modules.)
