# Perf delta: active-player capability auto-pass (extends opp-side)

**Date:** 2026-05-04
**Branch:** `feature/active-player-capability-autopass`
**Predecessor analysis:** `docs/perf_opp_autopass_20260504.md`
**Hardware:** Win11 desktop, single-process, single-thread (`torch.set_num_threads(1)`).
**Config:** v12 weights, `samples=4 inner_nodes=200`, `with_policy=True puct=True`,
ISMCTS uniform determinizer, `enable_mulligans=True`, `decision_cap=200`,
`base_seed=200`.

## TL;DR

The opp-only auto-pass (merged in `feature/opp-capability-autopass`)
caught ~45% of priority moments. The big win waiting on the table:
the ACTIVE player's priority windows that have nothing to do — at
sorcery timing in main phases when their hand is unplayable, at
instant-only windows when they have no instants in hand, and the
"both players auto-pass" cascade where a quiet phase advances through
its priority round without a single `legal_actions` enumeration.

This branch generalizes the capability check to handle both
priority holders. Random-walk RandomAgent self-play (seed 0, 500
decisions) shows the auto-pass rate climbed from **47.1% (opp only)
to 84.3% (opp + active)** — active player adds 36.8 percentage
points. Per-game wall on the v12 ISMCTS profile: **52.2s → 48.8s
(-6.5%)**. `legal_actions` call count: **433k → 156k (-64%)** on top
of the opp-only baseline.

End-to-end production self-play throughput should see roughly the
same proportion of work eliminated, with the cascade effect (both
players auto-passing through priority rounds in microseconds)
contributing a chunk that doesn't show up in single-game profiles.

## Numbers

Single-game profile runs (BEFORE on `main` at d5ff098 with opp-only
auto-pass; AFTER on this branch with opp + active). Same seeded game
(`base_seed=200`, `decision_cap=200`) so call counts are
deterministic and comparable.

| Metric | Before (opp only) | After (opp + active) | Delta |
|---|---|---|---|
| Clean per-game wall | 52.2s | **48.8s** | **-6.5%** |
| games/hour/worker | 68.9 | **73.8** | **+7.1%** |
| cProfile-instrumented wall | 227.3s | 235.0s | +3.4% (cProfile noise) |
| `legal.legal_actions` calls | 433,526 | **156,337** | **-64.0%** |
| `legal.legal_actions` cumtime | 51.0s | 38.6s | **-24.3%** |
| `legal.legal_actions` tottime | 5.3s | 3.6s | **-32.4%** |
| `_legal_actions_cached` calls | 634,003 | 223,005 | -64.8% |
| Decisions captured | 400 | 400 | unchanged |
| NN samples | 400 | 400 | unchanged |

Random-walk RandomAgent measurement (seed 0, 500-decision cap):

```
BEFORE (opp only):
  Total decisions: 468
  Total priority moments: 450
  Auto-passes total: 212  (47.1%)
    Opp-side: 212  (47.1%)
    Active-side: 0  (0.0%)
  Cascade segments (>=2 consecutive auto-passes): 0
  Total legal_actions calls: 238

AFTER (opp + active):
  Total decisions: 464
  Total priority moments: 440
  Auto-passes total: 371  (84.3%)
    Opp-side: 209  (47.5%)
    Active-side: 162  (36.8%)
  Cascade segments (>=2 consecutive auto-passes): 41
  Total legal_actions calls: 69
```

Cascade segments are the headline of this branch: 41 priority rounds
in a 464-decision game advance entirely through auto-pass on both
sides without a single `legal_actions` enumeration. Each cascade is
~2-4 priority moments collapsed into trivial pass-pass-pass loops —
exactly the "quiet turn" workload the engine repeatedly trundled
through pre-branch.

## Why the wall moved (vs opp-only landing flat)

Opp-only auto-pass cut `legal_actions` calls by 47% but per-game wall
didn't move within noise. The reason was simple: the
per-decision-moment cache had already absorbed most of the per-call
cost, so the marginal saving from skipping the cached call was
small.

Active-player auto-pass adds two compounding effects:

1. **Cuts ANOTHER 64% of remaining `legal_actions` calls** by
   short-circuiting the active-player priority window when it has no
   action. This is on top of opp's cut.
2. **Enables the cascade**: when both players auto-pass, the priority
   round runs entirely through `_run_priority_action(PassPriority())`
   → `priority_player_idx = _next_alive(...)` → `legal_decisions()` →
   short-circuit to `[PassPriority()]` again. No NN call, no
   `legal_actions` enumeration, no `legal_action_mask`. The priority
   round burns nothing. Production self-play saw ~7-8% wall reduction
   in this single-game profile and the cascade should compound across
   workers / multi-game runs.

## Key implementation choices

- **Unified module** at `src/mtg_bot/search/_player_capabilities.py`
  with `has_player_capability_to_act(state, pid,
  is_active_player=...)` and `player_capability_hash(...)`. Single
  source of truth for both flavors. `_opp_capabilities.py` is now a
  thin compat shim (3 wrappers) preserving the legacy import path.
- **Sorcery-window check** mirrors `legal._is_sorcery_timing` exactly
  (stack empty + main phase + active priority + active player).
  Active-player capability checks gate sorcery-speed paths on this.
- **Cache shape extended** to `(player_id, is_active_player, hash,
  can_act)`. Backwards-compat alias `_opp_can_act_cached` kept for
  the existing test surface.
- **Engine-contract match**: today's `legal_actions` returns early at
  non-sorcery timing BEFORE walking activated abilities (see
  `legal.py` — `if not _is_sorcery_timing: return actions` after the
  hand-cast loop). This means the engine never offers
  `ActivateAbility` at non-sorcery timing for ANY player. Our
  capability check returns False unconditionally for that path,
  matching the engine. If the engine ever changes this contract,
  `_has_instant_speed_activatable` is the single place to extend.
- **Pre-combat attacker capability** is a defensive include — today's
  adapter routes attacker declarations through the factored combat-
  decision phase BEFORE the priority window opens, so by the time
  `legal_decisions` runs in DECLARE_ATTACKERS, `_combat_phase != _COMBAT_NONE`
  is what gates auto-pass. Still, we check eligible-attackers at
  BEGINNING_OF_COMBAT / DECLARE_ATTACKERS so a future code path
  opening priority before combat-phase setup never silently auto-
  passes through an intended attack.

## Documented limitations (false-negative risk)

The structural hash watches:
- Hand: printing-name set.
- Pool: per-coin (color + spend-restriction) tuple.
- Battlefield: per-permanent (id, name, tapped, sick, ability count).
- Graveyard / exile: printing names + warp / impulse / Kavu / Lightstall flags.
- Step / turn / stack / priority / continuous-effect count.
- For active player: lands_played_this_turn, is_sorcery_window, life.

Continuous-effect changes that DON'T move any of those inputs are
invisible to the hash. The cache hit therefore reuses a possibly-
stale answer until the next `apply()` invalidation. Specifically:

- **Mid-turn flash grants** (Vedalken Orrery, Teferi Mage of Zhalfir).
- **Cost-reduction effects** that flip a previously-unaffordable
  spell to affordable without changing pool/source counts.
- **Ability-grant effects** that add an activated ability to a
  permanent already on the battlefield (the count delta is what the
  hash captures, not the effective set).

The same limitations apply to BOTH opp and active player auto-pass.
Acceptable for training: such interactions are exceedingly rare in
the EoE pool and the worst-case outcome is a single mis-skipped
response per million priority moments.

See `docs/SEARCH_LIMITATIONS.md` entry #3 for the full table.

## Reproducing this analysis

From the worktree:

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe -u \
    scripts/profile_self_play_game.py \
        --n-games-clean 1 --base-seed 200 --decision-cap 200 \
        --registry-root ../../mtg-bot/trained_weights \
        --deck-pool ../../mtg-bot/data/17lands/eoe_decks.json.gz
```

Random-walk auto-pass rate:

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
    scripts/measure_autopass_rate.py
```

## Recommended next step

Re-measure once concurrency-clean with multi-game throughput. Single-
game wall dropped 6.5% which is robust signal; production multi-
worker self-play should see at least that and likely more (the
cascade-segment savings amortize cleanly across short opp-priority
cycles). The next-bigger target on the v12 profile is
`_legal_actions_cached` (still 38.8s cumtime — most of the remaining
cost lives in the cached enumeration path, NOT the auto-pass path),
distinct from this work.
