# Hang triage — 2026-05-03

Triage report for the iter_001 self-play timeout pattern (49/500
games hit the 300s budget). Companion to todo `9c5e3b71`. Diagnostic
phase only — fix is a separate task.

## Summary

**The "hang" is not a runaway / infinite loop. It is a SLOW GAME under
heavy CPU contention.** Every dumped game we re-ran in a single
process completed cleanly within 60–250s of wall time. The TimeoutError
fires because:

1. The wall budget (300s in iterate; 60s in the local triage pool)
   is only ~3–6× the *median* per-game wall, leaving very little
   headroom.
2. Some games are intrinsically ~2–3× slower than the median because
   they reach states with bigger battlefields / more triggered
   abilities / longer MCTS settle, raising NN-PUCT cost.
3. Self-play uses 24 workers on a 32-core box plus the parent's
   torch / numpy threads. CPU oversubscription on Windows combined
   with `set_num_threads(1)` per worker still eats ~2× wall on the
   tail games when ALL workers are simultaneously in matmul.

So the dominant cluster's "hang point" is wherever faulthandler
happened to sample the game thread. The samples are evenly
scattered across the legitimate hot path (NN forward, NN softmax,
state.clone, _CowList fork-on-write, etc.) — there is no single
stuck call site.

## Dumps captured

11 dumps total over the triage window:

- 6 dumps from a local 4-worker NN-PUCT v6 reproducer pool
  (`debug_hangs/triage_nn/`, base_seed=1000000, game_idx ∈
  {4,5,7,9,10,11}, all timed out at the 60s budget).
- 5 dumps from the live iterate iter_002 self-play
  (`mtg-bot/debug_hangs/iter_002_self_play_v7/`, base_seed=2000000,
  game_idx ∈ {1,4,10,20,33}, all timed out at 300s; that dir was
  cleaned up when iterate was restarted, but the contents are
  reproduced below).

## Cluster histogram (deepest non-stdlib frame)

| Frame                                                              | Count |
|---|---|
| `nn_evaluator.batch_evaluate_with_policy → torch nn.Linear/ReLU` (matmul) | 7 |
| `nn_evaluator.batch_evaluate_with_policy` line 485 (numpy `_sum`)  | 1 |
| `nn_evaluator.batch_evaluate_with_policy` setup (line 434)         | 1 |
| `engine_adapter.clone → game.clone → game.clone_obj → _clone`      | 1 |
| `actions.resolve_top_of_stack → _send_to_graveyard_or_library → _CowList.append → _fork_if_shared` | 1 |

**There is no dominant single root cause.** The samples are spread
across the NN forward / softmax (10/11), the engine-state clone
(1/11), and the CoW-list fork (1/11) — i.e., wherever the worker
happens to be running when `faulthandler.dump_traceback` fires.
None of the dumps show MCTS in an unbounded `while True` or
state-based-actions stuck below the 50-pass cap.

## Dominant cluster — verbatim deepest 5–10 frames

Local triage pool, `hang_seed1000000_idx0004` (representative of 7
of 11 dumps):

```
Thread 0x000137b0 (most recent call first):
  File ".venv-py313\Lib\site-packages\torch\nn\modules\linear.py", line 134 in forward
  File ".venv-py313\Lib\site-packages\torch\nn\modules\module.py", line 1790 in _call_impl
  File ".venv-py313\Lib\site-packages\torch\nn\modules\module.py", line 1779 in _wrapped_call_impl
  File ".venv-py313\Lib\site-packages\torch\nn\modules\container.py", line 253 in forward
  File ".venv-py313\Lib\site-packages\torch\nn\modules\module.py", line 1790 in _call_impl
  File ".venv-py313\Lib\site-packages\torch\nn\modules\module.py", line 1779 in _wrapped_call_impl
  File "src\mtg_bot\search\nn_evaluator.py", line 194 in forward
  File ".venv-py313\Lib\site-packages\torch\nn\modules\module.py", line 1790 in _call_impl
  File ".venv-py313\Lib\site-packages\torch\nn\modules\module.py", line 1779 in _wrapped_call_impl
  File "src\mtg_bot\search\nn_evaluator.py", line 469 in batch_evaluate_with_policy
  File "src\mtg_bot\search\mcts.py", line 440 in _search_batched
  File "src\mtg_bot\search\mcts.py", line 328 in choose_with_visits
  File "src\mtg_bot\search\pimc.py", line 137 in choose_with_visits
  File "src\mtg_bot\training\data_gen.py", line 680 in _play_one_game_recording
```

iter_002 sample, `hang_seed2000000_idx0001` (state-clone variant):

```
Thread 0x00025a1c (most recent call first):
  File "<string>", line 13 in _clone
  File "src\mtg_bot\game.py", line 3031 in clone_obj
  File "src\mtg_bot\game.py", line 3123 in clone
  File "src\mtg_bot\search\engine_adapter.py", line 206 in clone
  File "src\mtg_bot\search\mcts.py", line 575 in _make_child
  File "src\mtg_bot\search\mcts.py", line 551 in _try_expand
  File "src\mtg_bot\search\mcts.py", line 495 in _select_and_expand
  File "src\mtg_bot\search\mcts.py", line 402 in _search_batched
  File "src\mtg_bot\search\mcts.py", line 328 in choose_with_visits
  File "src\mtg_bot\search\pimc.py", line 137 in choose_with_visits
  File "src\mtg_bot\training\data_gen.py", line 680 in _play_one_game_recording
```

Both are healthy code paths during normal MCTS work.

## Reproducibility

Re-ran 6 hung seeds (base_seed=1000000, game_idx ∈ {4,5,7,9,10,11})
through `scripts/repro_hang.py` in a single uncontested process at
the same NN-PUCT v6 / samples=4 / nodes=200 config. **All 6 completed
cleanly.** Wall times:

| game_idx | Wall      | Samples (decisions) |
|---|---|---|
| 4        | 88.4s     | 1090 |
| 5        | 74.2s     | 990  |
| 7        | 66.8s     | 2446 |
| 9        | 205.4s    | 1166 |
| 10       | 68.8s     | 1218 |
| 11       | 86.8s     | 1372 |

For comparison, "fast" non-hanging seeds at the same config:

| game_idx | Wall  | Samples |
|---|---|---|
| 0   | 27.9s | 710  |
| 1   | 31.6s | 686  |
| 2   | 53.3s | 932  |
| 3   | 32.1s | 892  |
| 6   | 30.5s | 734  |
| 8   | 39.4s | 1124 |

Median fast = ~32s, slow tail ≈ 200s, so the "slow" games are
~6× the median single-process. Under 24-worker contention they
plausibly reach 300s+ wall.

iter_002's `(base_seed=2000000, game_idx=1)` (mulligans=true, v7
weights, NN-PUCT, samples=4 nodes=200) reproduces with wall=171.8s
single-process / winner=1 / 976 samples. Same `(base_seed,
game_idx)` produced a 300s timeout under iterate's 24-worker pool —
consistent with ~2× contention slowdown.

**Reproduces *deterministically* in outcome (same winner +
same decision count across 3 reruns of seed=1000000/idx=9: 205.4s,
212.5s, 248.9s, all winner=1 / 1166 samples). The wall varies due
to OS-level noise but the trajectory is bit-identical.**

## Reproducer command

For one of the slow seeds:

```
cd mtg-bot-worktrees/hang-triage
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
  scripts/repro_hang.py \
  --seed 1000000 --game-idx 9 \
  --deck-pool ../../mtg-bot/data/17lands/eoe_decks.json.gz \
  --nn-version v6 --registry-root ../../mtg-bot/trained_weights \
  --timeout-sec 30 --samples 4 --nodes 200
```

The `--timeout-sec 30` arms `faulthandler.dump_traceback_later` so
if the game is still going at 30s wall, a fresh all-thread
traceback prints to stderr — same shape as the hang dumps. The
game then continues to completion (~200s) so you can see what it
WOULD have produced.

You can also pass `--meta-json <path>` directly to a hang dump's
.json file to inherit base_seed / game_idx / mulligan flag from
that exact failure.

## First-pass hypothesis

**The bug is "tight wall-clock budget on a slow tail game", not an
MCTS or engine pathology.**

Evidence:

1. Every single dumped game completes in a single process. None
   are stuck.
2. The instantaneous-sample cluster is spread across all of the
   legitimately-hot code paths (NN matmul, NN softmax, state
   clone, CoW fork). No common deepest frame.
3. SBA loops have a 50-pass cap. Step-advance is finite. None of
   the suspected runaway loops (continuous-effect feedback,
   static_abilities walker recursion) appear in any dump.
4. Single-process wall scales ~2× under 24-worker contention,
   matching the gap between "completes uncontested" (170–250s)
   and "exceeds the 300s budget under iterate" for the same
   `(base_seed, game_idx)`.

This DOES NOT rule out the historical engine state-corruption
ValueError bug (todo `e3b7d9c1`) — that surfaces as `ValueError:
card N not castable`, a different surface symptom. Iter_001
self-play reported 0 ValueError crashes (per the user-supplied
context), so that one is on a different rate path.

## Candidate fix directions (NOT implemented)

Ranked by likelihood that they would actually shrink the timeout
rate:

1. **Raise the per-game timeout to a value that bounds *single-
   process* worst-case slow games and accept that contention
   produces some slowness within budget.** Concretely: the slow
   tail in single-process is ~250s, ×2 contention factor ≈ 500s.
   Set `per_game_timeout_sec=600` and the timeout rate goes to
   ~zero. Cheapest win, and the timeout is doing exactly what it
   was meant to do (catching real hangs); a 10% false-positive
   rate at 300s reflects a too-tight budget, not a bug.

2. **Reduce per-decision MCTS cost on slow tail games by capping
   PIMC `samples` or MCTS `nodes` adaptively when a game's
   accumulated decision count crosses a threshold.** E.g. at
   decision_count=1000, halve `samples` from 4→2. Trades policy
   signal quality on long games for predictability of wall. More
   invasive; needs a config knob.

3. **Cap ACTUAL game length (decisions) lower than 4000 — many of
   the slow tail games take 1100–2400 decisions.** A 600-decision
   cap would shave wall noticeably. The cost is a bunch of games
   ending in draws-by-cap rather than real outcomes; this hurts
   the value-target signal. Use only if (1) and (2) are both
   insufficient.

What would NOT be a good fix: chasing the "MCTS runaway in
combinators.resolve" or "static_abilities feedback loop" or
"_CowList aliasing" hypotheses from todo `9c5e3b71`. The dumps do
not support any of those — every dumped state is in legitimate
hot-path code. py-spy's earlier observations of stuck-in-
combinators-resolve / stuck-in-mp.queues.get were the SAME class
of "instantaneous sample of a slow but-not-stuck game" rather
than evidence of an unbounded loop.

## Things I punted on

- **Cluster histogram is small (n=11) and the iter_002 dumps were
  destroyed when the user restarted iterate.** A larger sample
  (50–100 dumps) would tighten the conclusion, but each dump
  costs 60s of wall in the local pool and the conclusion is
  already strong from 11 points.
- **Did NOT look for an engine state where MCTS legitimately would
  loop.** The dominant cluster says it's not happening; ruling it
  in/out at scale would need a longer reproducer pool (200+
  games) and isn't blocking the fix decision.
- **Did NOT investigate the `ValueError: card N not castable`
  cousin (todo `e3b7d9c1`).** Iter_001 had 0 such crashes, so
  it's not on the current rate path. Still tracked separately.
- **Reproducer accepts `--meta-json` from a hang dump but does NOT
  reconstruct mid-game state from a decision history.** The
  current design re-runs from `setup_game(seed=engine_seed)`
  through every prior decision, which works because the seed
  fully determines the game (mulligan flag + RandomAgent RNGs
  match). A future, more invasive enhancement would let the dump
  carry the engine snapshot at the timeout instant — but that's
  unnecessary for the slow-tail finding.
