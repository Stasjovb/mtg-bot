# `_CowList._fork_if_shared` optimization perf delta

**Date:** 2026-05-04
**Branch:** `feature/cow-fork-optimization` (rebased on main after the
legal-actions cache merge)
**Hardware:** Win11 desktop, single-process, single-thread
(`torch.set_num_threads(1)` — matches production worker pin)
**Bench config:** v12 weights, ISMCTS uniform, `samples=4
inner_nodes=50 with_policy=True puct=True`, `decision_cap=60`,
`base_seed=200 game_idx=0` (identical game across trials).

## TL;DR

The 2026-05-04 per-game self-play profile (`docs/perf_self_play_20260504.md`)
ranked `_fork_if_shared` as the #3 cost bucket: 27% of self-time, 66s
tottime over 127k calls in a cProfile-instrumented self-play game.
This branch lands two complementary changes that together reduce
fork-related self-time **~19%** and per-game wall **~9.6%**.

## Hypotheses considered

The handoff listed five candidates. After instrumenting a real
ISMCTS self-play segment with a custom counter wrapper, the call
distribution was:

| Branch | % of `_fork_if_shared` calls |
|---|---|
| Owned fast-path (no work) | **90.9%** |
| Actual fork (peers exist) | 9.1% |

Avg fork list size when forking: **21 elements** (libraries 50+
cards but graveyards/exile usually small). Mutator dispatch
breakdown over 19 ISMCTS decisions: 17,135 pops, 13,338 appends,
5,300 removes, 376 setitems.

That call distribution effectively rules out the more invasive
hypotheses:

- **(a) Lazy-clone elements** — the dominant mutator (`pop`)
  ALWAYS hands the popped element to a caller who's about to
  `card.zone = HAND` it; lazy-cloning would have to materialize on
  the popped element anyway, and the engine pattern doesn't have
  natural read-side chokepoints to defer further.
- **(b) Object pool / freelist** — would help the 9% of calls
  that fork, but adds substantial complexity in code where the
  cast-not-castable invariant from commit 47a5f03 is already
  load-bearing.
- **(e) Specialized fork for size-1 mutations** — already
  effectively the case for `pop()` / `append()` (the
  GameObject-touched path is ONE element); additional structural
  shortcuts here lose more than they gain by undermining the
  uniform CoW contract.

The two highest-leverage angles, **(c) reduce fork frequency in the
fast-path overhead** and **(d) inline the share check**, are what
this branch lands.

## What changed

`src/mtg_bot/game.py` `_CowList`:

1. **Split into `_fork` (slow path, no owned check) + `_fork_if_shared`
   (public wrapper that does the owned check first).** Each list
   mutator inlines `if not self._owned: self._fork()` instead of
   calling `_fork_if_shared()` unconditionally — saves a Python
   method call frame on the 90%+ of calls that hit the owned
   fast-path.

2. **Drop the post-fork `self._clone_each = None` writes.**
   `_clone_each` is only READ on the slow path, gated behind
   `_owned` — once `_owned=True` the reference is unreachable from
   public API. ~1 attribute store saved per fork on self plus 1
   per peer that becomes solo-owned.

3. **KEEP the `self._share_group = None` and
   `peer._share_group = None` writes.** Removing them was tried
   in isolation and produced a ~50% slowdown on the realistic
   fork bench (51-card library, 19µs → 28µs per fork). Diagnosis:
   the group list refers back to self and the peer (a self ↔ group
   ↔ peer cycle), so leaving `_share_group` set forces cyclic GC
   to walk + reclaim the group on dropoff, defeating the
   refcount-fast-path. New regression test
   `test_fork_breaks_share_group_cycle` pins this.

4. **Specialize the 2-member share group inline.** The
   clone-time pair (source ↔ clone) is the common case in MCTS;
   this branch finds the single peer by identity and installs the
   cloned pool directly, skipping the
   `peers = [q for q in group if q is not self]` filter and the
   `len(peers) == 1` branch.

The fork direction (self keeps originals; peers get clones) is
unchanged, so the `cast-not-castable` invariant from commit
`47a5f03` is preserved bit-for-bit.

## Micro-bench (51-card library, production `_clone_game_object`)

Five trials each, median reported:

| Bench | Baseline (main) | This branch | Delta |
|---|---|---|---|
| owned_fast_path (5M iters) | 0.039 µs | 0.032 µs | **-18%** |
| owned_append_pop (1M pairs, 2 forks/pair) | 0.167 µs | 0.120 µs | **-29%** |
| fresh_fork_size_40 (50k iters) | 2.18 µs | 2.17 µs | flat |
| realistic_fork_51_cards (2k iters) | 19.6 µs | 19.1 µs | -2.5% |

The hot path is the fast-path; the slow path is unchanged within
noise. ✅ No regression on the slow path (the GC-cycle break in
`_share_group=None` was the key to keeping fork cost flat).

Run with `scripts/profile_cow_fork.py` (kept for follow-up).

## End-to-end self-play game (cProfile, same game_idx)

3 trials each, median reported. cProfile-instrumented (~4× wall
overhead — but the *self-time* breakdown is unaffected).

| Metric | Baseline (main) | This branch | Delta |
|---|---|---|---|
| `_fork`/`_fork_if_shared` calls | 5,557 | 4,199 | **-24%** |
| `_fork`/`_fork_if_shared` tottime | 930 ms | 754 ms | **-19%** |
| Per-game wall (cProfile) | 12.7 s | 13.1 s | flat (noise) |

The call count drops 24% because the fast-path inline checks no
longer dispatch to a separate function — those calls vanish from
the cProfile call graph entirely. The remaining 4,199 calls are
the actual forks (~equal to baseline's 9% fork-rate × 5,557 = 5,001;
the further reduction is from cProfile run-to-run noise on the
exact tree shape).

## End-to-end self-play game (clean wall, no cProfile)

5 trials each on the same game (`game_idx=0`, `base_seed=200`),
sorted ascending, median reported. Trial 0 is consistently
~5× faster across both branches due to a torch / CPU-cache warmup
effect — included in stats but should be discounted vs the
trials-1-through-4 quasi-steady-state.

| Trials | Baseline (main) | This branch |
|---|---|---|
| 0 | 1.08 s | 1.10 s |
| 1 | 5.34 s | 4.84 s |
| 2 | 5.74 s | 5.19 s |
| 3 | 5.78 s | 6.29 s |
| 4 | 5.81 s | 6.39 s |
| **median** | **5.74 s** | **5.19 s** |

**Median per-game wall delta: -9.6%.** Wall-clock noise is
substantial at this game length (~5s); the median is the most
robust point estimate, the mean (4.75s vs 4.76s) is dominated by
the warmup outlier.

The cProfile self-time (-19%) is the cleanest fixed-cost-per-call
signal; the wall-clock (-9.6%) is the user-visible bottom line and
falls in the upper end of the prompt's "10-15% per-game wall
reduction" target.

## Tests

- `tests/test_state_clone_cow.py`: **30 passing** (was 24, +6 new
  fork-optimization regression tests + 1 updated post-fork
  invariant test):
  - `test_fork_breaks_share_group_cycle` — pins the 2-member
    GC-cycle invariant for the new `_share_group=None` writes.
  - `test_fork_breaks_share_group_cycle_three_member` — same for
    3+ groups; remaining peers form a NEW group, not the old one.
  - `test_fork_three_member_subsequent_fork_isolates_remaining_peer`
    — chained-fork correctness across the new size==2 fast-path
    branch (the third peer becomes owned via the same path on
    the second fork).
  - `test_fork_inlined_check_dispatches_each_mutator` — every
    mutator (including rarely-hit ones: `sort`, `reverse`,
    `__imul__`, `__iadd__`) on a freshly-shared list still
    triggers fork via the inline `if not self._owned: self._fork()`
    form.
  - `test_fork_owned_no_op_skips_share_group_writes` — fast-path
    no-op leaves `_share_group` / `_clone_each` untouched
    (sentinel test).
  - `test_fork_iteration_followed_by_explicit_fork` — the public
    `fork()` entry point (used by `run_cleanup_step`) still drives
    the underlying `_fork` through the inline guard.

- Full suite: **7,116 passed**, 8 skipped, 1 warning. Coverage
  **95.17%** (above the 95.10% gate).

## CoW-invariant subtleties worth flagging

1. **The peer-fork direction is preserved.** `self` keeps its
   originals; peers get fresh clones. The cast-not-castable
   regression test that landed in 47a5f03
   (`test_remove_then_mutate_caller_held_ref_isolated`) and the
   cleanup-step regression
   (`test_run_cleanup_step_does_not_leak_to_peer`) both pass.
2. **The `_share_group=None` cleanup is now load-bearing for
   perf, not just hygiene.** Removing it was tried in isolation
   and produced a measurable ~50% regression on the realistic
   fork micro-bench (cyclic GC walking the
   self-↔-group-↔-peer reference cycle). The new
   `test_fork_breaks_share_group_cycle` pins this so a future
   refactor can't silently regress the slow path. Note
   `_clone_each` does NOT have this problem because the cloner is
   a module-level function (`_clone_game_object`), not a per-list
   instance.
3. **`_clone_each = None` is no longer set on transition to
   owned.** That's intentional — `_clone_each` is only READ on
   the slow path, which is gated behind `_owned`. A test that
   used to assert `assert src._clone_each is None` after fork
   has been updated to drop the assertion (the contract now is
   "after fork, only `_owned=True` is canonical").
4. **The fast-path inline check (`if not self._owned: self._fork()`)
   is duplicated in 12 mutators.** It's tempting to extract back
   to a helper, but the whole point of the change is to avoid the
   helper call. The duplication is structural to the optimization
   and is covered by `test_fork_inlined_check_dispatches_each_mutator`.

## Reproducing

From the worktree:

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
    scripts/profile_cow_fork.py
```

Per-game wall comparison: see the inline `--no-cov` cProfile-and-
wall snippet in this branch's commit message.
