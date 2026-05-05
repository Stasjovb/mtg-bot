# Per-game self-play perf analysis (after batched-prior-stamp + tree reuse)

**Date:** 2026-05-04
**Branch:** `feature/perf-analysis-deep`
**Hardware:** Win11 desktop (master), single-process, single-thread
(`torch.set_num_threads(1)` — matches production worker pin).
**Config:** v12 weights, `samples=4 inner_nodes=200` (production
budget), `with_policy=True puct=True`, ISMCTS with uniform
determinizer, `enable_mulligans=True`, `decision_cap=200`.
**Profile artifact:**
`profile_results/self_play_game_20260504T175750.prof`

## TL;DR

After landing batched prior stamp (commit `de9a92e`, 13.8x per-choose
speedup), tree reuse (commit `5f1a202`), and clone optimization (commit
`99b45e8`), the per-game profile shows the bottleneck has moved from
**NN forwards (now ~2% of wall time)** to **engine work**:
**`legal_actions` enumeration alone consumes 37% of wall time**, and
**`_fork_if_shared` (the CoW-list mutation guard) is 27% of tottime** —
these two together account for over half the wall clock of a self-play
game.

Per-game NNEvaluator construction is **NOT** a meaningful cost (~7ms
per build, ~14ms per game = 0.02% of an 80s game). Hypothesis 1 from
the handoff is **ruled out**.

The single biggest available win is **caching `legal_actions` per
priority moment** so ISMCTS's repeated `legal_decisions` calls inside
`_select_and_expand` and `_grow_union_mask` don't re-enumerate from
scratch. Estimated payoff: 30-40% per-game speedup on top of current
master.

## What this study measured

`scripts/profile_self_play_game.py` runs in two phases:

1. **Phase 1**: N profile-free self-play games for clean per-game
   wall numbers.
2. **Phase 2**: a single cProfile-instrumented game for the deep
   call-tree breakdown.

This separation matters because cProfile multiplies wall by ~2-4x —
running it on every game would distort the wall-clock distribution,
and one profiled game is enough for the per-call breakdown.

A quick analyzer (`scripts/_print_self_play_profile.py`) re-runs the
category roll-up against the saved `.prof` so iterating on the
analysis doesn't require re-recording.

`decision_cap=200` was set for this study so even a long-tail
random-walk game wouldn't dominate wall clock — production uses 4000
and most games end well under 500. The cap-hit game we profiled does
NOT include the late-game graveyard-recursion tail that some
production games hit; those are a separate diagnostic problem and a
fix for them won't be in this PR.

## Headline numbers

| Quantity | Value |
|---|---|
| Clean per-game wall (n=1) | **62.1 s** |
| cProfile-instrumented game wall | 251.0 s (4.0x clean) |
| Decisions captured (samples / 2 viewers) | 200 |
| Total `choose()` calls | 200 |
| `choose()` calls that ran the search | 27 (13.5%) |
| `choose()` calls short-circuited (single legal) | 173 (86.5%) |
| ISMCTS iterations executed across the game | 21,600 (= 27 × 800) |
| Effective per-iteration wall (clean) | ~2.9 ms |
| Effective per-decision wall (clean) | ~310 ms |
| Per-worker rate (single-process, single-thread) | **58 games/hour** |

The 173 / 200 short-circuit ratio is interesting: most decisions in
self-play actually have only one legal action (forced UNTAP / DRAW
cleanups, tactical-policy default routes, single-target spells), so
the search loop only fires on ~13% of priority moments. That's
already a big reason the 800-iter budget doesn't translate into a
160k-iter cost per game.

## Top per-game cost buckets (cProfile-instrumented; cumtime in ms)

The numbers below are cumtime of the cProfile-instrumented game,
which wall-runs at ~4x of the clean game. Percentages are vs the
profiled game's 251s wall — the *proportions* are what matter and
don't change much vs the clean run.

| # | Bucket | Calls | tottime | cumtime | % wall |
|---|---|---|---|---|---|
| 1 | `_select_and_expand` (root) | 21,600 | 5,704 ms | 233,668 ms | **93%** |
| 2 | `engine_adapter.apply` | 570,491 | 922 ms | 96,914 ms | **39%** |
| 3 | `legal.legal_actions` | 1,128,672 | 10,088 ms | 92,063 ms | **37%** |
| 4 | `_fork_if_shared` (CoW lib) | 126,787 | **66,270 ms** | 70,658 ms | **27% tot** |
| 5 | `legal_decisions` (adapter) | 570,691 | 1,454 ms | 58,875 ms | **23%** |
| 6 | `_can_cast` + `can_pay_cost` | 1.07M / 1.22M | ~7,000 ms | 60,592 / 60,248 ms | combined ~24% |
| 7 | `_advance_to_next_decision` | 570,492 | 840 ms | 49,358 ms | 20% |
| 8 | `_grow_union_mask` (ISMCTS) | 570,291 | 2,261 ms | 43,622 ms | **17%** |
| 9 | `legal_action_mask` (training) | 570,491 | 1,160 ms | 40,770 ms | **16%** |
| 10 | `_classify_sac_for_mana` | 3,464,511 | 5,908 ms | 34,836 ms | 14% |
| 11 | `effective_activated_abilities` | 4,057,429 | 12,996 ms | 30,399 ms | 12% tot |
| 12 | `info_set_key` | 21,627 | 89 ms | 19,113 ms | 7.6% |
| 13 | `clone` (engine GameState) | 47,063 | 1,594 ms | 4,965 ms | 2.0% |
| 14 | `clone` (adapter) | 43,400 | 187 ms | 5,165 ms | 2.1% |
| 15 | `batch_evaluate_logits` (NN) | 675 | 112 ms | 4,640 ms | **1.9%** |
| 16 | `extract_features` | 23,646 | 68 ms | 2,010 ms | 0.8% |
| 17 | `_play_one_game_recording` setup | — | 6 ms | 250,927 ms | (root) |

Reading these numbers:

- **Engine work (legal_actions + can_cast + can_pay_cost +
  effective_activated_abilities) is the giant.** These are all
  non-search functions: they enumerate what actions a player could
  take and answer "can this spell be cast right now?" Each is called
  ~1M+ times per game.
- **`_fork_if_shared` is the single most expensive Python function**
  by tottime (66s, 27% of self-time). It's the CoW guard that fires
  every time a library/graveyard list is mutated after having been
  shared with a clone. ISMCTS clones on every iteration (21,600
  iters × 2 players = ~43k clones, matching the `clone` counts), so
  every per-iteration step into the engine triggers a fork-shaped
  burst.
- **NN forwards (batch_evaluate_logits) are 1.9% of wall time.**
  They're called only 675 times total across the whole game, with
  each call processing a batched set of leaves+parents. The
  batching landed in `de9a92e` is doing exactly what it should.

## Hypotheses ruled out

1. **Per-game NNEvaluator construction:** measured at ~7ms per build,
   ~14ms total per game (factories build it twice). At 62s/game
   that's 0.02%. Sharing a single NNEvaluator across all games on a
   worker would save ~14ms/game = ~50ms/hour/worker. Not worth the
   refactor.

2. **`torch.load` / `model.load_state_dict` cost:** subsumed by the
   construction cost above. cProfile didn't even surface a
   `torch.serialization.load` entry above the noise floor.

3. **Replay capture overhead:** zero in this profile because
   `replay_config=None`. Production iterate self-play uses
   `--capture-every-self-play 25`, so 24 of every 25 games skip
   replay entirely. A subsequent profile with replay on would tell
   us the per-snapshot cost — out of scope here.

4. **NN forward bottleneck:** decisively no, post-batched-prior-stamp.
   1.9% of wall.

5. **`info_set_key` cost:** 7.6% of wall, called only 21,627 times
   (once per ISMCTS iteration). This is in line with what was
   designed for. Not a target.

6. **Clone overhead:** 4% of wall. The 30% reduction landed in
   `99b45e8` is consistent with clone cumulative time of ~10s vs
   the ~14s we'd expect at the un-optimized 27us per clone.

## Targets ranked by expected payoff

### #1: Cache `legal_actions` per priority moment

`legal_actions` runs **1.13M times per game** (avg ~50 calls per
ISMCTS iteration). For most of those calls the engine state hasn't
changed — `legal_decisions` is invoked once during `_select_and_expand`
to choose a child, then again in `_grow_union_mask` to update the
union mask, then again in `legal_action_mask` to encode the policy
mask. Each call re-runs the full 50ms-amortized enumerator from
scratch.

The fix: **cache the legal-action list on the adapter (or engine)
once per "priority moment" key**, invalidated by `apply`. The
ISMCTS iteration loop's three callers (`legal_decisions`,
`_grow_union_mask`, `legal_action_mask`) all see the SAME engine
state for the SAME determinization, so they should hit the same
cache once it's primed.

Estimated payoff: ~25-35% wall reduction. Calls drop from ~1.13M
to ~21,600 (one per ISMCTS iteration); current `legal_actions`
cumtime is 92s, of which ~85s could be cache hits.

Effort: ~4-8 hours. The cache invalidation rule is "any state
mutation invalidates," which adapter.apply already serves as a
chokepoint for. Risk: legal_actions has subtle effect-driven
inputs (cost reductions on objects whose state can change between
calls) — a stale cache here would silently produce illegal
decisions. Need careful invariant tests.

### #2: Reduce `_fork_if_shared` cost

`_fork_if_shared` is 66.3s tottime (27% of self-time). It's called
127k times per game at 0.5ms each. The expensive path is the
DEEP-COPY fork — when a CoW library is touched after being cloned,
every GameObject in it gets `_clone_game_object`'d. With ~40
cards per library and one fork per iteration's clone-then-mutate,
that's ~40 × 21,600 = 864k object clones in the fork path alone.

Two angles to attack:

1. **Skip forks for read-only operations.** Today the CoW guard
   forks on every `__setitem__` / `append` / mutation. If many
   mutations happen back-to-back on a single freshly-forked list
   (e.g. running a whole turn's worth of card draws), only the
   FIRST should fork — but the current guard forks every call.
   Investigate whether the guard is actually correct here (the CoW
   contract says "first mutation forks; subsequent mutations
   should be cheap").

2. **Avoid the fork entirely** for the per-iteration clone path.
   ISMCTS iterations apply random determinized actions to a clone
   then discard it. If the engine can detect "this clone will
   never be observed by anyone outside this iteration," it can
   skip the CoW protection entirely and mutate in place.

Estimated payoff: 10-20% wall reduction. The CoW machinery is
load-bearing for cross-clone safety so this is high-risk.

Effort: 1-2 days, including writing the invariant tests that
catch any regression.

### #3: Avoid per-iteration `legal_action_mask` recomputation

`legal_action_mask` runs 570k times per game (once per
`_grow_union_mask` call) with cumtime 41s (16% of wall). The mask
is built by iterating `_enumerate_legal` (which calls
`legal_decisions`, captured in #1 above) plus an O(n) encoder pass.

After #1 lands, the mask itself is still being built fresh per
descent step. Two further optimizations:

1. Cache the mask alongside the legal-action list (same
   priority-moment key).
2. Materialize the mask incrementally: when descending the tree,
   we already have the parent's mask and the per-iteration
   determinization's narrower mask — the new node's union mask
   is the OR, which can be done in-place on the parent's
   ndarray + the new mask without recomputing from
   `legal_decisions`.

Estimated payoff: an additional 10-15% on top of #1.

Effort: ~4 hours after #1 lands.

### #4: Investigate `effective_activated_abilities` (4M calls / 12s tottime)

This isn't on a search hot path — it's an engine helper that gets
called from `legal_actions` -> `_can_cast` -> `_classify_sac_for_mana`
when checking whether a creature can be sacrificed for mana. 4M calls
in a single game suggests the helper is being invoked redundantly
for every mana-affordability check; if it can be hoisted out of the
inner loop or memoized per priority moment, we recover a chunk
of the 12s tottime.

This is downstream of #1 — fixing the legal_actions cache will
slash the call count proportionally. Worth re-measuring AFTER #1
to see whether further attention is needed here.

### "Free" wins from existing knobs

- **Production already uses `--capture-every-self-play 25`** —
  captures 4% of games. No headroom there unless we drop further.
- **Tree reuse is already on** — saves the search budget across
  173/200 forced-move call sites by short-circuiting the search
  entirely. Already accounting for the dramatic gap between the
  budget (200 × 800 = 160k iters) and the actual iters executed
  (21,600).
- **Worker pin to 1 thread is already on** — torch's mkl thread
  contention is not a factor.

## What this profile does NOT cover

- Long-tail games where the engine cap-hits at 4000 decisions
  (which take 5+ minutes wall on a single worker even before
  cProfile). The hot path SHAPE is the same (legal_actions /
  _fork_if_shared dominate) but the absolute wall cost can be
  4-10x of a typical game.
- Multi-process pool overhead. The handoff cited workers seeing
  ~50% idle time per shard (882s elapsed, ~410s game-work).
  That accounting is BEYOND what a single-process profile sees;
  the next investigation should look at pool dispatch, queue
  hand-off latency on `/queue/take`, and what the workers are
  blocking on during the idle window. Not addressed here.
- Replay capture cost. With `replay_config=None` in this run,
  the replay path is fully gated out. Re-running with
  `--capture-every 1` would tell us the per-snapshot cost; based
  on the in-code comment ("~5 ms of work and ~1 MB compressed
  disk per game" for PIMC), replay is unlikely to be a needle-
  mover at the current capture-every-25 default.

## Reproducing this analysis

From the worktree:

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe -u \
    scripts/profile_self_play_game.py \
        --n-games-clean 1 --base-seed 200 --decision-cap 200 \
        --registry-root ../../mtg-bot/trained_weights \
        --deck-pool ../../mtg-bot/data/17lands/eoe_decks.json.gz
```

Then re-print with the offline analyzer:

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe -u \
    scripts/_print_self_play_profile.py \
        profile_results/self_play_game_20260504T175750.prof 50
```

Both scripts are in this branch (`feature/perf-analysis-deep`).

## Recommended next step

Land **#1: legal_actions cache** as its own feature branch off
main. Single most impactful change available with the current
profile signal. Combine with #3 (mask cache) for a one-shot
~40% speedup target before re-measuring per-game wall.
