# Perf delta: per-decision-moment legal_actions cache

**Date:** 2026-05-04
**Branch:** `feature/legal-actions-iter-cache`
**Predecessor analysis:** `docs/perf_self_play_20260504.md`
**Hardware:** Win11 desktop, single-process, single-thread (`torch.set_num_threads(1)`).
**Config:** v12 weights, `samples=4 inner_nodes=200`, `with_policy=True puct=True`,
ISMCTS uniform determinizer, `enable_mulligans=True`, `decision_cap=200`,
`base_seed=200`.

## TL;DR

Caching `legal.legal_actions` once per priority moment on
``MtgGameStateAdapter`` cuts the per-game ``legal_actions`` call count
by **~38%** (1.34M → 828k) and the per-game wall by **~10-15%** at the
profile-budget settings used for the predecessor study. The cumtime
attributed to ``legal_actions`` itself drops by **~44%** (104s → 58s
on the cProfile-instrumented run).

The headline 25-35% per-game wall projection from the predecessor
analysis assumed every legal_actions call was redundant; in practice
the ISMCTS workload has a 60/40 split between unique-moment and
redundant-moment calls (roughly: each ISMCTS descent step makes 3-4
calls into the cache, of which 1 is the cold computation and 2-3 are
hits). The cache eliminates the hits, leaving the cold-compute floor
intact — that's the realized win.

NN forward count is unchanged (675 calls, same as before — the cache
sits below the search loop and doesn't change which states get
evaluated). Search-quality metrics (visit distributions, leaf values)
are unchanged: this is a pure micro-optimization.

## Numbers

Two clean games + one cProfile-instrumented game, base_seed=200,
decision_cap=200. Variance between game 0 and game 1 is high (~2x)
because the legal-set complexity tracks game length and the seeded
games end at different turn counts; absolute walls below should be
read against each other, not against the predecessor analysis's
single-game numbers.

| Metric | Before (main) | After (cache) | Delta |
|---|---|---|---|
| Clean per-game wall, mean (n=2) | 82.7 s | 73.7 s | **-10.9%** |
| Clean per-game wall, min | 55.6 s | 47.5 s | **-14.6%** |
| Clean per-game wall, max | 109.9 s | 100.0 s | **-9.0%** |
| cProfile-instrumented game wall | 210.7 s | 170.6 s | **-19.0%** |
| `legal.legal_actions` calls (cProfile run) | 1,343,172 | 828,324 | **-38.4%** |
| `legal.legal_actions` cumtime | 103.9 s | 58.3 s | **-43.9%** |
| `legal.legal_actions` tottime | 10.7 s | 6.5 s | **-39.0%** |
| `legal_decisions` (adapter) calls | 570,691 | 570,691 | 0 |
| `_grow_union_mask` calls | 570,291 | 570,291 | 0 |
| `legal_action_mask` calls | 570,491 | 570,491 | 0 |
| NN `batch_evaluate_logits` calls | 675 | 675 | 0 |

The three downstream callers (``legal_decisions``,
``_grow_union_mask``, ``legal_action_mask``) all called legal_actions
at the same per-call rate before; the cache shifts where the work
happens without changing *who* asks for it.

## What changed

`MtgGameStateAdapter` now memoizes `legal.legal_actions(self._state,
player_id)` for the current decision moment via two new private
attributes (`_legal_actions_cache_player`, `_legal_actions_cache_value`)
and a helper `_legal_actions_cached(player_id)`. The cache:

1. **One entry, keyed by player_id.** A second call for a different
   player misses and overwrites the entry. In practice the inner-loop
   pattern always queries the same active player, so this is fine.
2. **Invalidated at the top of `apply()`**. Every state-mutating
   dispatch branch in `apply` (resolution-pause routing, combat
   sub-decision routing, normal priority action, resolution-rollback-
   and-replay) flows through that one site. Centralizing invalidation
   there avoids needing to hook every mutator inside the engine.
3. **NOT inherited across clones.** ISMCTS `_fresh_determinization`
   mutates `engine_state` in place after cloning, which would silently
   stale a shared cache (e.g. for Mm'menon's library-top check). The
   clone starts empty; first call recomputes.
4. **Returned as the same list reference on cache hits.** Callers
   are read-only; `legal_decisions()` already wraps with `list(...)`
   before exposing the result through the search-protocol surface,
   so the existing copy-on-exit semantics are preserved.

`training/action_encoding.legal_action_mask` now routes through the
adapter's cache when given an adapter (via duck-typing on
`_legal_actions_cached`). Engine-state inputs fall back to the
direct legal_actions call — no caching available without an adapter.

## Cache-correctness invariants

`tests/search/test_engine_adapter_legal_cache.py` (13 tests, ~1.4s):

- Cache hit returns same underlying object; spy confirms one
  underlying enumeration.
- `apply()` invalidates; spy confirms the next call re-enumerates.
- Resolution-pause sub-decision path invalidates correctly (cast
  Bombard → pause → answer with target → priority-window legal set
  has been freshly computed).
- Clone has empty cache (covers the `_fresh_determinization` path).
- `legal_action_mask(adapter, viewer)` shares the cache —
  `legal_decisions` + `legal_action_mask` + `legal_decisions` is one
  underlying enumeration.
- `legal_action_mask(engine_state, viewer)` does NOT cache (no
  adapter context); two consecutive calls produce two enumerations.

## Hidden mutation paths considered

The cache only invalidates inside `apply()`. Mutations that bypass
`apply()` (anyone reaching through `adapter.engine_state` and writing
directly) would NOT invalidate, producing stale entries. The known
in-tree call sites that touch `engine_state`:

- `ISMCTS._fresh_determinization` mutates a fresh CLONE's
  `engine_state`. The clone has an empty cache by construction, so
  the post-determinization legal_actions is the first computation and
  is correct. Source adapter is untouched.
- `data_gen` and `self_play` `recorder.record(adapter.engine_state,
  ...)` are read-only — they snapshot for replay capture.
- `mtg_priors` / `pimc` use `engine_state` for read-only reasoning.
- `ismcts.observe_action` clones `engine_state` for the belief
  history — read-only on the source adapter.

No in-tree path mutates a *non-clone* adapter's engine_state outside
of `apply()`. Future code that needs to do so should call
`adapter._invalidate_legal_actions_cache()` after the mutation; this
is documented on the `engine_state` property's docstring.

## What's next

Per the predecessor analysis, the next two highest-payoff targets are:

1. **Reduce `_fork_if_shared` cost** (66s tottime / 27% of self-time).
   Independent of this cache change; orthogonal optimization.

2. **Cache `legal_action_mask` itself** alongside the legal-action
   list (same priority-moment key). The mask helper is the
   per-iteration `_grow_union_mask` caller; right now it still
   re-encodes every legal decision to bool slots even though the
   underlying legal set comes from the cache. An additional ~10-15%
   wall payoff is plausible.

## Reproducing this measurement

From the worktree:

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe -u \
    scripts/profile_self_play_game.py \
        --n-games-clean 2 --base-seed 200 --decision-cap 200 \
        --registry-root ../../mtg-bot/trained_weights \
        --deck-pool ../../mtg-bot/data/17lands/eoe_decks.json.gz
```

Compare against the same command run from the main checkout (which
sees the pre-cache code) for the BEFORE numbers.
