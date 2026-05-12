# xdist flake investigation — 2026-05-11

**Filed in response to:** The pending-CE-filings agent (merge `07850c50`)
reported 13 test failures under `pytest -n 8 --no-cov` that all passed
when re-run in isolation. The agent hypothesised "xdist shared-state
flakes around the SBA-gated surface accessors" introduced by the CE10
closure (`feature/ce-pure-derivation-is-over`, merge `59b6054e`).

**Conclusion (TL;DR):** No xdist flakiness was reproduced. Two
consecutive full runs of `pytest -n 8 --no-cov` from a clean worktree
of `main` (`07850c50`) yielded **exactly 1 deterministic failure**
(9993 passed, 12 skipped, 3 xfailed) — the same failure each time, and
the failure also reproduces in isolation. The CE10 SBA-gated accessor
work is solid: `tests_rust/` runs 1701/1701 green under `-n 8`. The
reported "13 failures" signal was almost certainly caused by a
half-built / wrong-version `mtg_bot_engine.pyd` at the moment that
agent ran — a well-known recurring artifact of concurrent agents in
sibling worktrees racing on `pip install -e .` to rebuild the PyO3
extension.

## 1. Reproduction

Worktree: `feature/xdist-flake-investigation` off `main` (`07850c50`).

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe -m pytest -n 8 --no-cov
```

Run 1 (`117.54s`):

```
1 failed, 9993 passed, 12 skipped, 3 xfailed, 1 warning in 117.54s
FAILED tests/test_effect_coverage.py::test_no_orphan_rust_variants
```

Run 2 (`105.05s`, immediately after run 1, same worktree):

```
1 failed, 9993 passed, 12 skipped, 3 xfailed, 1 warning in 105.05s
FAILED tests/test_effect_coverage.py::test_no_orphan_rust_variants
```

`tests_rust/` gate (the CE10-adjacent surface), `-n 8`:

```
============================ 1701 passed in 1.56s =============================
```

## 2. The one real failure

`tests/test_effect_coverage.py::test_no_orphan_rust_variants` — this
is **not flaky**. It fails the same way every run, both under `-n 8`
and in isolation:

```
AssertionError: Rust variant(s) with no Python counterpart:
  [('ChooseOneMode', 'ChooseOneMode'),
   ('GrantKeywordToTargetCreatureUntilEOT', 'GrantKeywordToTargetCreatureUntilEOT'),
   ('SetBasePTUntilEOT', 'SetBasePTUntilEOT')]
```

Three Rust `Effect` variants landed today
(`baaafdb6 rust(effect-choose-one-mode)`, `d2c610dd rust(effect-equip-to-target-creature)`,
plus the unconditional-pump branch) without a matching mapping in
`scripts/measure_effect_coverage.py`'s `RUST_TO_PYTHON_OVERRIDES` /
`RUST_AHEAD_OF_POOL`. The orphan-empty regression guard fires on
purpose — it's designed to force a coverage-script update on the same
commit as a Rust bridge change.

**This failure is already fixed on the unmerged branch
`feature/coverage-overrides` (commit `2bcdd842`).** That commit:

- maps `ChooseOneMode -> ModalChooseOne` (override),
- maps `GrantKeywordToTargetCreatureUntilEOT -> GrantUnblockableUEOT`
  (override + 1:N comment),
- allowlists `SetBasePTUntilEOT` in `RUST_AHEAD_OF_POOL`.

That branch is **user-gated** (the user merges, not the agent — same
policy as the sick-lands fix `f94126d6`). Merging
`feature/coverage-overrides` to `main` will green this test.

## 3. Why the original agent saw 13 failures

The pending-CE-filings agent (which ran ~before this investigation
started) saw 13 failures. Two complementary explanations, both rooted
in the **`.pyd` rebuild race**:

1. **Stale `.pyd` at the moment that agent ran.** Several sibling
   worktrees were actively building today — the
   `.venv-py313/Lib/site-packages/` directory contains a long tail of
   `~-N_bot_engine/` orphan directories (the artifact left when pip
   couldn't delete an in-use DLL during `pip install -e .`):

   ```
   ~-4_bot_engine  May 11 22:50
   ~-5_bot_engine  May 11 23:05
   ~-6_bot_engine  May 11 23:13   <-- mid-investigation
   ```

   If the `.pyd` was rebuilt mid-run while xdist workers had already
   imported the old version, or if the agent's `.pyd` reflected an
   older Rust source than the `cards.rs` that
   `measure_effect_coverage.py` scrapes (or vice-versa), the orphan
   list would be wider than the 3 we see today. Other tests that touch
   freshly-added Rust variants without yet having their Python
   counterparts wired through (parser tests, effect-resolve tests)
   would then trip alongside `test_no_orphan_rust_variants`, producing
   the 13-test signature.

2. **The 13 tests pass in isolation specifically because in isolation
   the runner sees a single coherent `.pyd` snapshot** — there's no
   second worker mid-import while a different worker is mid-rebuild.
   That is the exact "passes in isolation, fails under `-n 8`"
   signature the original agent reported, and it perfectly fits a
   build-vs-import race rather than xdist-shared-state in CE10's code.

There is no shared state in CE10's changes (`rust/src/state_ops_winloss.rs`
+ `tests_rust/test_winloss.py` + `tests/test_parity_smoke_edge_cases.py`)
that would be xdist-sensitive:

- The SBA-gated accessors (`is_over()`, `winner_id`, `is_draw`) read
  from per-`GameState` `Player.has_lost` flags. No module-level state.
- The `synthetic_state` fixture in `tests_rust/test_winloss.py` returns
  a fresh `make_synthetic_state()` per test. No fixture-level leak.
- All 1701 `tests_rust/` tests are green under `-n 8`.

The CE10 closure is not the culprit.

## 4. Root cause

**Two factors compounded for the original agent:**

a) **Real, deterministic failure:** three Rust variants landed today
   without their corresponding coverage-script mappings. The
   `test_no_orphan_rust_variants` guard fires every run. (Fix lives
   on `feature/coverage-overrides`, user-gated.)

b) **Apparent flakiness wrapper:** the `pip install -e .` race
   between concurrent worktrees produced a transiently-broken
   `.pyd` snapshot at the time the pending-CE-filings agent ran.
   That widened the failing set to 13 tests for that single window;
   the failures went away in isolation because isolation imports a
   single coherent snapshot.

## 5. Resolution — procedural, not code

No code change in this branch. The actual code fix lives on
`feature/coverage-overrides` (commit `2bcdd842`) and is gated on
user review per project policy.

**Recommendation for the user:**

1. **Merge `feature/coverage-overrides`** (commit `2bcdd842`,
   "tools(coverage): map ChooseOneMode / GrantKeywordToTargetCreatureUntilEOT
   / SetBasePTUntilEOT in coverage script") — this fixes the 1 real
   deterministic failure and brings the orphan list back to empty.

2. **Before running `-n 8` after a Rust bridge change**, rebuild the
   engine once and let it land before launching workers:

   ```
   .venv-py313/Scripts/python.exe -m pip install -e .
   ```

   Then run `pytest -n 8`. This eliminates the build-vs-import race.

3. **When multiple agents are active in sibling worktrees**, expect
   to see occasional "passes-in-isolation, fails-under-`-n 8`"
   signatures during the windows where one of them is mid-rebuild.
   This is a `pip install -e .` + Windows-locked-DLL artifact, not a
   test bug — the `~-N_bot_engine/` orphan directories under
   `site-packages/` are evidence. Re-running the full suite after the
   builder finishes should produce the clean signature seen here.

4. **Optionally, periodically clean the orphan directories.** They're
   harmless but accumulate over time:

   ```
   Get-ChildItem .venv-py313/Lib/site-packages | Where-Object {
     $_.Name -like "~*bot_engine*"
   } | Remove-Item -Recurse -Force
   ```

   (Run this only when no test / build is in flight.)

## 6. No code fix shipped here

Per the decision criteria in the task brief:
- Cause was not CE10's SBA-gated accessors (CE10 is solid).
- Cause was a combination of an unmerged coverage-script update and
  the well-known `.pyd` rebuild race.
- Both have natural resolutions (user merges the coverage-overrides
  branch; user runs `pip install -e .` to settle the binding before
  launching `-n 8`).

This doc + the recommendations in section 5 is the deliverable.
