# Per-zone breakdown of GameState.clone()

## Executive summary

Battlefield is the dominant remaining cost in `GameState.clone()`,
accounting for roughly **15–40% of clone wall time** depending on
permanent count (8 perms mid-game ≈ 14% / 3.6 µs; 23 perms late-game
≈ 39% / 11.8 µs). Hand is a distant second at ~10–18% in mid-game
when both players hold 4–5 cards (~3–5 µs) and falls to ~0% late once
hands are empty. Mana pool is effectively free (<1% — pools are empty
between priority steps in the simulator). **Recommendation: a CoW pass
on the battlefield is the only zone-level work likely to move the
needle.** Hand is a smaller win and harder to retrofit because the
cast pipeline mutates hand objects (`chosen_modes`, `x_value`,
`kicked`) inline; mana pool is not worth touching.

## Method

Bench script: `scripts/bench_clone_zones.py`. For each zone we
monkey-patch `GameState.clone` with a copy of the original body that
replaces the per-zone work with a share-by-reference assignment, time
1500 calls × 7 trials, and report the best-of-trial wall time per
clone. The zone delta is `baseline_best − skip_best`. Best-of is more
reliable than median under CPU contention (see caveats).

Profile: `scripts/profile_pimc_game.py --seed 42 --samples 4
--nodes 100 --top 25` for one full PIMC vs RandomChoice game,
`cProfile` with `cumulative` and `tottime` sorts.

## Bench numbers

Captured 2026-05-02 with the gen0 self-play run consuming ~30 cores
in the background. Numbers are best-of-7; treat them as upper bounds
on the steady-state per-clone cost. The median values were noisier
(15–40% trial-to-trial variance on contended runs).

### Mid-game (turn 9, bf=8, hand=[4,5], gy=[1,2], exile=[1,0])

| variant          | best µs/clone | median µs/clone |
| ---------------- | ------------: | --------------: |
| baseline         |          26.3 |            27.7 |
| skip_hand        |          22.5 |            22.9 |
| skip_battlefield |          22.5 |            23.7 |
| skip_mana_pool   |          26.9 |            28.0 |

Per-zone delta:

| zone        | µs   | % of baseline |
| ----------- | ---: | ------------: |
| hand        |  4.4 |          16.4 |
| battlefield |  3.6 |          13.8 |
| mana_pool   |  0.0 |           0.1 |

### Late-game (turn 18, bf=23, hand=[1,0], gy=[5,5], exile=[1,0])

| variant          | best µs/clone |
| ---------------- | ------------: |
| baseline         |          30.0 |
| skip_hand        |          30.1 |
| skip_battlefield |          18.2 |
| skip_mana_pool   |          30.2 |

Per-zone delta:

| zone        |   µs | % of baseline |
| ----------- | ---: | ------------: |
| hand        |  ~0  |          ~0   |
| battlefield | 11.8 |          39.4 |
| mana_pool   |  ~0  |          ~0   |

### Fat mid-game (turn 14, seed 42, bf=15, hand=[4,4], gy=[5,3])

| variant          | best µs/clone |
| ---------------- | ------------: |
| baseline         |          30.9 |
| skip_hand        |          27.6 |
| skip_battlefield |          22.6 |
| skip_mana_pool   |          30.4 |

Per-zone delta:

| zone        |   µs | % of baseline |
| ----------- | ---: | ------------: |
| hand        |  3.3 |          10.7 |
| battlefield |  8.3 |          26.9 |
| mana_pool   |  0.5 |           1.6 |

## Profile attributions (one PIMC game, seed 42)

26,052 `clone()` calls in 4.528s cumulative (~174 µs/clone — much
higher than the bench microbenchmark because real search clones
happen with stack items, more complex states, and tend to coincide
with `_fork_if_shared` triggering on the CoW zones).

Top clone-pipeline rows by `tottime`:

| function                               | ncalls    | tottime | tottime/call | calls/clone |
| -------------------------------------- | --------: | ------: | -----------: | ----------: |
| `_fork_if_shared` (game.py:170)        |     2,091 | 3.224 s |       1.5 ms |        0.08 |
| `clone()` body (game.py:2967, exclusive) |  26,052 | 1.569 s |        60 µs |           — |
| exec'd slot-cloners (`<string>:1`)     |   607,910 | 1.284 s |       2.1 µs |        23.3 |
| `clone_obj` closure (game.py:3015)     |   573,676 | 0.377 s |       0.7 µs |        22.0 |
| `_CowList.__init__` (game.py:164)      |   156,318 | 0.331 s |       2.1 µs |         6.0 |

Notes:

- `_fork_if_shared` is the **CoW fork tax**. It fires only when a
  rollout actually mutates a shared library/graveyard/exile zone, but
  when it does, it deep-clones every element on the OTHER members of
  the share group — so its 1.5 ms / fork dwarfs a clone (60 µs). Total
  3.2 s / 21.7 s game = ~15% of total search time. This is the cost
  side of the ledger CoW already paid for and net-wins on.
- The exec'd slot-cloners (`<string>:1`) cover every shallow clone
  for `GameObject`, `Player`, `ManaCoin`, `StackItem`. 23 calls/clone
  × 2.1 µs/call = ~49 µs of in-clone work. Most of that is battlefield
  + hand + cross-references through `clone_obj`.
- 6 `_CowList.__init__` calls per clone is exactly right: 3 zones × 2
  players. That overhead (~12.7 µs/clone, ~7%) is the price of CoW.
  Not worth optimizing without a structural change.

## Recommendation

### Battlefield → CoW (highest-priority follow-up)

The only zone with a clear, repeatable wall-clock win. 12 µs/clone
late-game = ~40% of clone cost; 4–8 µs mid-game = 14–27%.

**Design constraint**: battlefield permanents are mutated in place
during play (`tap`, `damage_marked`, `summoning_sick`, `attacking`,
`blocked_by`, counters, etc.). The `_CowList` invariant — fork on
write, mutator keeps originals — applies to **list mutations**, not
to mutations of the elements themselves. Today's CoW assumes the
elements are append-and-removed-but-not-mutated; for hand and
battlefield that doesn't hold.

A real battlefield-CoW design needs to either:

1. **Element-level CoW**: each `GameObject` participates in a
   share-group; a write on a permanent forks just that object out
   of its group. The cross-reference rewiring is straightforward
   because GameObject IDs are stable, but every mutator (50+ sites
   in `game.py`) needs a `_fork_if_shared(obj)` preamble. Big
   refactor; clear win.
2. **Snapshot-of-IDs**: store the battlefield as a tuple of IDs +
   a per-state object table. Clone just copies the tuple; mutation
   forks the table on first write. Simpler invariants but invasive
   change to the entire engine's permanent-access pattern.
3. **Lazy clone**: keep the list shape, but defer the per-element
   `_clone_game_object` work until the element is first read on
   the cloned side. Possible because most search rollouts only
   touch a small fraction of permanents, but the bookkeeping is
   subtle.

(1) is the most likely path — it composes with what's already in
place. Estimated win at typical mid-game (8–15 perms, 23 calls/clone
of slot-cloner ≈ 30% of which is battlefield): ~3–8 µs/clone, plus
amortized away for unmutated permanents in PIMC samples that diverge
quickly.

### Hand → not worth it on its own

3–5 µs/clone in mid-game, drops to ~0 late. Even if we recovered all
of it, ~10–15% of clone is a small absolute win compared to
battlefield.

**Design constraint**: the cast pipeline mutates hand-resident
GameObjects in place (`chosen_modes`, `x_value`, `kicked`,
`additional_cost_choice_id`) before moving them to the stack. A
share-by-reference clone breaks this — sibling clones would see
the cast in progress. To CoW the hand we'd need element-level CoW,
same as battlefield. **If we do option (1) above, hand falls out
for free** (the CoW machinery applies to all GameObjects regardless
of zone). That's the only realistic path to picking up the hand
delta.

### Mana pool → no

<1 µs/clone in mid-game, ~0 µs late. The pool is drained between
priority steps, so most clones see an empty pool. Don't bother.

## Caveats

- **CPU contention**: the gen0 self-play run was using ~30 cores
  during all bench captures. Median timings showed 15–40% variance
  trial-to-trial; best-of-trial timings showed ~5–10% variance.
  Reported numbers are best-of-7 and should be treated as upper
  bounds on the steady-state per-clone cost. Re-run after gen0
  finishes for tighter numbers if a perf sprint actually goes
  forward.
- The simulator-built mid/late states have empty mana pools because
  pools are emptied at end of priority/end of step. A bench fixture
  that artificially populates the pool would show a different
  picture, but search clones happen at priority boundaries with
  empty pools, so this matches reality.
- The microbench numbers (~26–31 µs/clone) are lower than the
  cProfile mean (~174 µs/clone) because (a) cProfile traces every
  function call and inflates wall time, (b) real search clones tend
  to fire `_fork_if_shared` on the CoW zones — those forks are
  attributed to a separate pstats row but are part of the
  per-rollout amortized cost. The bench numbers are the right ones
  for sizing a zone-level optimization; the profile numbers are the
  right ones for sizing the total search budget.
