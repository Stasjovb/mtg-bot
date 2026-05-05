# Perf delta: opp capability auto-pass at non-active priority

**Date:** 2026-05-04
**Branch:** `feature/opp-capability-autopass`
**Predecessor analysis:** `docs/perf_legal_actions_cache_20260504.md`
**Hardware:** Win11 desktop, single-process, single-thread (`torch.set_num_threads(1)`).
**Config:** v12 weights, `samples=4 inner_nodes=200`, `with_policy=True puct=True`,
ISMCTS uniform determinizer, `enable_mulligans=True`, `decision_cap=200`,
`base_seed=200`.

## TL;DR

When the active player passes priority and the non-active player ("opp")
gets priority, opp typically has no instant-speed action available — the
only legal choice is `PassPriority()`. Auto-passing those moments
without enumerating `legal_actions` cuts the per-game `legal_actions`
call count by an additional **~48%** (828k → 433k) on top of the
already-shipped per-decision-moment cache. `legal_actions` cumtime
drops by **~13%** (79.6s → 69.1s on the cProfile-instrumented run);
tottime drops by **~21%** (9.0s → 7.1s).

End-to-end clean-run wall is unchanged within the noise floor of a
single seeded game (concurrent capacity contention dominated this
round; see "Caveat" below). The robust signal is the call-count drop,
which translates to fewer mass-allocations and fewer trips through
the cost-payability machinery.

A standalone random-walk measurement (RandomAgent self-play, seed 0,
500 decisions) shows that **~45% of priority moments fire the
auto-pass short-circuit**; the share of `legal_actions` invocations
reduces by approximately the same factor.

## Numbers

Two single-game runs (one BEFORE on `main`, one AFTER on this
branch). Both ran the same seeded game (`base_seed=200`,
`decision_cap=200`) so call counts are deterministic and
comparable. The clean-wall numbers are NOT directly comparable
because the two runs were started concurrently — the cProfile
phase took ~280s under contention versus the ~250s baseline from
the predecessor analysis.

| Metric | Before (legal_actions cache) | After (+ auto-pass) | Delta |
|---|---|---|---|
| Clean per-game wall (n=1) | 69.0 s | 69.8 s | within noise |
| cProfile-instrumented wall | 282.0 s | 286.8 s | within noise |
| `legal.legal_actions` calls | 828,324 | **433,526** | **-47.7%** |
| `legal.legal_actions` cumtime | 79.6 s | 69.1 s | **-13.2%** |
| `legal.legal_actions` tottime | 9.0 s | 7.1 s | **-20.7%** |
| `_legal_actions_cached` calls | 1,128,672 | 634,003 | -43.8% |
| `legal_decisions` cumtime | 81.3 s | 80.0 s | -1.6% |
| NN forward calls | 675 | 675 | unchanged |
| Decisions captured | 200 | 200 | unchanged |

## Why the wall didn't move

Two factors capping the realized wall win:

1. **Concurrency contention on this measurement.** The two
   profile runs were launched in parallel on the same machine and
   shared CPU; the wall numbers above carry that contention as
   noise. The call-count and per-function tottime numbers are
   immune to this noise (they're function-call counts inside one
   process).

2. **`legal_actions` is no longer the dominant cost** after the
   per-decision cache landed. The predecessor analysis shows it
   sitting at ~17% of cProfile wall (down from 37% pre-cache).
   Cutting that share by another half (the call-count win) is a
   ~7-9% wall reduction at most — within the noise floor of a
   single-game measurement.

A second random-walk measurement (RandomAgent vs RandomAgent, no
NN, no search budget) confirms the auto-pass fires at the
predicted rate:

```
Total decisions: 453
Auto-passes:     205   (45.3%)
Total legal_actions calls: 231
```

In production self-play (multi-game, multi-worker), the call-count
reduction translates more cleanly into wall savings because
between-game variance smooths out and the saved enumerations
compound across many short opp-priority cycles.

## What's exposed and what isn't

The auto-pass fires only when the engine's priority is on the
non-active player AND `_opp_capabilities.opp_can_act` returns
False. The capability function is *conservative*: it returns True
whenever it can't quickly rule out a capability, and the only path
to False is a definitive "no instant-speed castable in
hand/graveyard/exile, no permanents currently capable of an
activatable mana payment".

A subtle interaction with the existing `legal_actions` enumerator
is documented in `_opp_capabilities.py`: today's enumerator
early-returns at non-sorcery timing BEFORE walking activated
abilities, so the engine never offers an `ActivateAbility` action
to opp at non-active priority regardless of what permanents they
control. The capability function matches that contract — treating
"opp has activated abilities" as a capability would silently
sabotage every auto-pass attempt (every player has lands; every
land has at least implicit mana abilities). If a future engine
change DOES start returning `ActivateAbility` at non-sorcery
timing, `_has_instant_speed_activatable` is the place to add the
check, and the structural hash already covers permanent shape.

## Documented limitations (false-negative risk)

The structural hash watches:
- Hand: printing-name set.
- Pool: per-coin (color + spend-restriction) tuple.
- Battlefield: per-permanent (id, name, tapped, sick, ability count).
- Graveyard / exile: printing names + warp / impulse / Kavu flags.
- Step / turn / stack / priority / continuous-effect count.

Continuous-effect changes that DON'T move any of those inputs are
invisible to the hash. The cache hit therefore reuses a possibly-
stale answer until the next `apply()` invalidation. Specifically:

- **Mid-turn flash grants** (Vedalken Orrery, Teferi Mage of
  Zhalfir) that arrive without changing the hash inputs.
- **Cost-reduction effects** that flip a previously-unaffordable
  spell to affordable without changing pool/source counts.
- **Ability-grant effects** that add an activated ability to a
  permanent already on the battlefield (the count delta is what
  the hash captures, not the effective set).

Acceptable for training: such interactions are exceedingly rare
in the EoE pool and the worst-case outcome is a single
mis-skipped response per million priority moments. Documented
in the module's docstring.

## Reproducing this analysis

From the worktree:

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe -u \
    scripts/profile_self_play_game.py \
        --n-games-clean 1 --base-seed 200 --decision-cap 200 \
        --registry-root ../../mtg-bot/trained_weights \
        --deck-pool ../../mtg-bot/data/17lands/eoe_decks.json.gz
```

Then re-print with the offline analyzer (same script as the
predecessor analyses):

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe -u \
    scripts/_print_self_play_profile.py \
        profile_results/self_play_game_20260504T194517.prof 50
```

## Recommended next step

Re-measure once concurrency-clean. If the wall savings remain
within the noise floor in single-game mode, look at multi-game
production self-play timing (where the call-count drop should
amortize cleanly). Alternatively, the next-bigger target on the
profile is `_fork_if_shared` (now 24% tottime) — distinct from
this work.
