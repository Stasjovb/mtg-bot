# `bench_trajectory_parity.py` — first-run smoke report

Companion to `scripts/bench_trajectory_parity.py` (this slice). The
script's job is signal generation, not perfect runs — failures are the
deliverable. This report captures the smoke results from the first run
and names the divergence shapes that surfaced so the next round has a
concrete Rust-slice candidate list to chase.

## Canonical smoke (per the task brief)

Invocation:

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
    scripts/bench_trajectory_parity.py \
    --archetypes 0-5 --seeds 0-2 --max-turns 15 \
    --json-out /tmp/smoke.json --verbose
```

Aggregate (18 games — 6 archetypes × 3 seeds):

| Status                | Count |
|-----------------------|-------|
| PASS                  | 0     |
| FAIL_DIVERGENCE       | 5     |
| FAIL_TIMEOUT          | 13    |
| ARCHETYPE_FILTERED    | 0     |
| FAIL_EXCEPTION        | 0     |
| Wall time             | ~22s  |

Per-archetype breakdown:

| Arch | Status mix                          |
|------|-------------------------------------|
| 0    | FAIL_TIMEOUT=3                      |
| 1    | FAIL_TIMEOUT=3                      |
| 2    | FAIL_TIMEOUT=3                      |
| 3    | FAIL_TIMEOUT=3                      |
| 4    | FAIL_DIVERGENCE=3                   |
| 5    | FAIL_TIMEOUT=1, FAIL_DIVERGENCE=2   |

Archetypes 0–3 are mono-color or two-color decks whose creatures all
fall outside today's CardDef bridge filter — the post-filter library
collapses to "basic lands + Forest padding" with zero creatures, so
`attack_all` runs forever with no attackers and FAIL_TIMEOUT after 16
turns is the correct (and expected) signal. The bench tells us
"archetype 0–3 contributes no creature trajectory coverage" — which is
itself useful: extending the CardDef substrate to admit one of the
filter-dropped creatures from those archetypes would convert those
six games' worth of TIMEOUTs into real game runs.

Archetypes 4 and 5 carry **Icecave Crasher** and **Harmonious
Grovestrider** through the filter — both with landfall triggers — and
all five non-TIMEOUT games on those two archetypes surfaced real
cross-engine divergences.

## Divergence shapes surfaced

### 1. `play_land::stack` (3 / 5 = 60% of failures)

```
arch=4 seed=0  turn=12 action=23  kind=play_land  fields=[stack]
  py:   stack=((None, 0, 0, 0, 0, None, 1, None),)
  rust: stack=((None, 0, 0, 0, 0, None, 1,   70),)

arch=5 seed=1  turn=11 action=21  kind=play_land  fields=[stack]
  py:   stack=((None, 0, 0, 0, 0, None, 0, None),)
  rust: stack=((None, 0, 0, 0, 0, None, 0,    9),)

arch=5 seed=2  turn=11 action=21  kind=play_land  fields=[stack]
  py:   stack=((None, 0, 0, 0, 0, None, 0, None),)
  rust: stack=((None, 0, 0, 0, 0, None, 0,    9),)
```

Both engines push a stack entry on the `play_land` (the landfall
triggered ability from Icecave Crasher / Harmonious Grovestrider) but
the last tuple slot differs: Python emits `id=None`, Rust emits a real
object id. Same shape across all three games — likely a single bridge
gap in the stack-entry field-view recipe (Python's stack-object id
isn't getting normalized into the field-view's last slot the way
Rust's does).

**Next-round Rust-slice candidate**: investigate the stack
field-view recipe for triggered-ability entries (probably in
`parity_smoke._build_field_view` / `build_python_field_view` — the
8-tuple's last slot is the object id, and Python's triggered-ability
stack entry doesn't carry the same id provenance Rust's does).

### 2. `cast_spell::graveyard_p0,battlefield` (2 / 5 = 40% of failures)

```
arch=4 seed=1  turn=11 action=22  kind=cast_spell  fields=[graveyard_p0, battlefield]
  py:   graveyard_p0=(('Harmonious Grovestrider', 0, 1, 0, 0, None, 0, 9),)
        battlefield=... (Grovestrider NOT present)
  rust: graveyard_p0=()
        battlefield=... (Grovestrider on bf)

arch=4 seed=2  turn=11 action=22  kind=cast_spell  fields=[graveyard_p0, battlefield]
  (same shape — Grovestrider in py gy, on rust bf)
```

Casting Harmonious Grovestrider triggers a divergence where Python
moves the creature to graveyard but Rust keeps it on the battlefield.
The Grovestrider must be hitting a state-based-action / death trigger
on Python that doesn't fire on Rust (or vice-versa) — likely
interacting with its landfall scry trigger draining through Python's
stack but not Rust's, or an ETB trigger that kills the creature on one
engine. The previous landfall+pump (Icecave Crasher) and landfall+
gain_life (Eumidian Terrabotanist) trajectory probes both pass byte-
equal; Grovestrider must use a different `_SAFE_TRIGGERS` arm.

**Next-round Rust-slice candidate**: track down the Harmonious
Grovestrider trigger shape and either (a) tighten the `_SAFE_TRIGGERS`
allowlist to reject it until both engines model it identically, or
(b) extend whichever side is missing the matching primitive.

## Secondary smoke (creature-bearing archetypes, longer max-turns)

To surface signal from archetypes whose creatures DO survive the
filter, an expanded smoke ran with archetypes hand-picked from the
"has-creatures" set (13, 14, 15, 35, 49, 57) × seeds 0-2 × max-turns
40:

| Status            | Count |
|-------------------|-------|
| PASS              | 0     |
| FAIL_DIVERGENCE   | 17    |
| FAIL_TIMEOUT      | 1     |
| Wall time         | ~23s  |

Same two divergence shapes dominated (`play_land::stack` 13×,
`cast_spell::graveyard_p0,battlefield` 4×) — these are not arch-4/5-
specific quirks; they're real cross-engine bridge gaps that fire on
every landfall consumer in the production-deck loader's admit set.

## Action items (for the next slice)

1. Fix or document the **`play_land::stack`** divergence — Python's
   stack-entry id slot is `None` vs Rust's int id. Likely a one-line
   patch in `build_python_field_view`'s stack-entry recipe to mirror
   Rust's id-carrying behavior.
2. Diagnose the **Harmonious Grovestrider cast** divergence — figure
   out why the creature ends up in different zones across engines.
   Either tighten the CardDef filter to drop Grovestrider OR fix the
   underlying bridge gap.
3. Once (1) is fixed, re-run the bench: the
   `cast_spell::graveyard_p0,battlefield` shape may stop firing too if
   it cascades from the same stack-id mismatch.
4. Extending the CardDef bridge to admit at least one creature per
   archetype 0–3 would convert their FAIL_TIMEOUTs into real game
   signal — they're contributing no parity coverage today.

## Reproducibility

The bench is fully deterministic at a given (archetype, seed,
max_turns, combat_strategy, mulligans) tuple — the matched-state seed
threads through both engines' shared RNG. To reproduce any single
failing game:

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
    scripts/bench_trajectory_parity.py \
    --archetypes 4 --seeds 0 --max-turns 15 \
    --json-out /tmp/single.json --verbose
```

## Round 41 wider-sweep results

Round 41 ran **two complementary sweeps** to surface the next batch of
divergence shapes. The first (this slice's small sweep) re-verified
arch 0-30 at seeds 0-2; the second salvaged round-40 worker G2's
abandoned-but-actually-complete wider sweep (arch 0-50 × seeds 0-5 ×
max-turns 20 — the brief reported it blocked at 113/306 but the
on-disk JSON shows all 306 games landed cleanly). Both runs are
included here because the G2 set is the higher-signal one (the
divergences in the production-deck loader admit set fire predominantly
at **seed=4**, which the small 0-2 sweep doesn't reach).

### Sweep A — small verification (this slice)

Invocation:

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
    scripts/bench_trajectory_parity.py \
    --archetypes 0-15 --seeds 0-2 --max-turns 18 \
    --json-out tmp/bench_r41.json --verbose
# and
    --archetypes 16-30 --seeds 0-2 --max-turns 20 \
    --json-out tmp/bench_r41_b.json --verbose
```

| Sweep | Games | PASS | FAIL_DIVERGENCE | FAIL_TIMEOUT | Wall |
|-------|-------|------|-----------------|--------------|------|
| A1 (0-15, s0-2, t18) | 48 | 1 | 0 | 47 | 62s |
| A2 (16-30, s0-2, t20) | 45 | 3 | 0 | 42 | 58s |

Sweep A surfaced **zero divergences** at seeds 0-2 — the known
landfall-triggered shapes from the round-37/38 smoke (`play_land::stack`,
`cast_spell::graveyard_p0,battlefield`) did not reproduce in this run.
Pure FAIL_TIMEOUT dominance at seeds 0-2 confirms the
"divergence-bearing trajectories live at higher seeds" observation
from round 39. Sweep A's value is negative-signal: confirms
seeds 0-2 are largely silent until max-turns crosses ~15 AND the
seed admits a divergence-bearing draw.

### Sweep B — salvaged G2 wider-sweep run

Invocation (per G2's recorded config):

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
    scripts/bench_trajectory_parity.py \
    --archetypes 0-50 --seeds 0-5 --max-turns 20 \
    --json-out /tmp/bench_wide.json --verbose
```

| Status            | Count |
|-------------------|-------|
| Total games       | 306   |
| PASS              | 10    |
| FAIL_DIVERGENCE   | 17    |
| FAIL_TIMEOUT      | 279   |
| Wall time         | 406s  |

### Top divergence shapes (Sweep B)

| Rank | Shape                                    | Count | NEW since round-38? |
|------|------------------------------------------|-------|---------------------|
| 1    | `cast_spell::life_p0,stack`              |   8   | **NEW**             |
| 2    | `cast_spell::stack`                      |   6   | **NEW**             |
| 3    | `cast_spell::life_p1,stack`              |   3   | **NEW**             |
| 4    | `play_land::stack`                       |   0   | (round-37 shape)    |
| 5    | `cast_spell::graveyard_p0,battlefield`   |   0   | (round-37 shape)    |

**All three shapes that fired are NEW** since the round-37/38 baseline.
The two old shapes did NOT reproduce at all in 306 games — likely
indicating those were fixed (or filtered) between round 38 and main
HEAD `53604a7c`, or they only fire at the earlier max-turns=15 the
round-37 smoke used.

### Divergence shape detail

**`cast_spell::stack` (6 games — archetypes 4, 5, 43, 49)**

```
py:   stack=()
rust: stack=((None, 0, 0, 0, 0, None, 0, 9),
             (None, 0, 0, 0, 0, None, 1, 70),
             (None, 0, 0, 0, 0, None, 0, 9),
             (None, 0, 0, 0, 0, None, 1, 70),
             (None, 0, 0, 0, 0, None, 0, 9))
```

Rust accumulates multiple triggered-ability stack entries that Python's
stack does not carry. The repeated `(0, 9)` / `(1, 70)` pairs look
like the same source-pair (likely Icecave Crasher + Harmonious
Grovestrider's landfall triggers from the round-37 admit set)
re-firing — Python may be auto-resolving and clearing the stack
between casts where Rust queues them.

**`cast_spell::life_p0,stack` (8 games — archetypes 13, 14, 15, 16, 17, 30, 35, 44)**

```
py:   life_p0=23, stack=()
rust: life_p0=20, stack=((None,0,0,0,0,None,0,0)x3)
```

Compound divergence: 3-point life delta on the active player AND
3 stack entries that didn't fire on Python. The 3-point life loss
correlates with the 3 missing stack entries — likely a life-loss
trigger (e.g. a "lose 1 life" upkeep / cast effect) that resolves
immediately + accumulates on Rust but no-ops on Python.

**`cast_spell::life_p1,stack` (3 games — archetypes 30, 35)**

```
py:   life_p1=21, stack=()
rust: life_p1=20, stack=((None,0,0,0,0,None,1,60),)
```

Same shape but on the non-active player — 1-point life delta + 1
stack entry. Almost certainly the same underlying bridge gap as
`life_p0,stack` but in the opponent-targeted variant.

### Per-archetype breakdown (Sweep B, archetypes that produced divergences)

| Arch | PASS | FAIL_DIV | FAIL_TIMEOUT |
|------|------|----------|--------------|
| 4    | 4    | 1        | 1            |
| 5    | 1    | 1        | 4            |
| 13   | 0    | 1        | 5            |
| 14   | 0    | 1        | 5            |
| 15   | 0    | 1        | 5            |
| 16   | 0    | 1        | 5            |
| 17   | 0    | 1        | 5            |
| 21   | 3    | 0        | 3            |
| 30   | 0    | 2        | 4            |
| 35   | 0    | 3        | 3            |
| 43   | 2    | 1        | 3            |
| 44   | 0    | 1        | 5            |
| 49   | 0    | 3        | 3            |

Archetypes 13-17 all produce the SAME divergence (`cast_spell::life_p0,stack`
at turn=16 action_index=32), which strongly suggests they share a
divergence-bearing card and the shape is deterministic given the
deck list. Round 42+ slice work should reproduce one of these
(e.g. arch=13 seed=4 max-turns=18) and trace the cast that produces
the 3-life / 3-stack-entry divergence.

### FAIL_TIMEOUT pattern

279 of 306 games (91%) are FAIL_TIMEOUT. Archetypes 0-3, 6-12, 18-20,
22-29, 31-34, 36-42, 45-48, 50 are uniformly 6/6 FAIL_TIMEOUT — every
seed runs to max-turns with neither engine winning. Per the round-37
smoke analysis, this is the CardDef bridge filter dropping all
creatures from these archetypes, leaving "basic lands + Forest
padding" — `attack_all` has nothing to attack with.

**Conversion opportunity:** extending the bridge filter to admit one
creature per timeout-dominant archetype would convert ~6 games each
into real trajectory probes — potentially 30-50 archetypes worth of
new divergence signal. Candidate next-slice work: enumerate the
creatures the filter rejects across archetypes 0-3, 6-12 and pick
the highest-value vocabulary additions (single-shape triggers like
plain ETB / vanilla creatures should be cheap to admit).

### New divergence-shape candidates for round 42+

1. **`cast_spell::stack` (rust-extra entries)** — six games, arch 4/5/43/49.
   The repeated `(0, 9)` / `(1, 70)` source pairs in Rust's stack
   suggest a multi-trigger-per-cast accumulation that Python is
   silently flushing. Diagnose whether Python's bridge is missing a
   trigger-enqueue path OR Rust is failing to resolve between casts.
2. **`cast_spell::life_p0,stack` (life delta + 3 stack entries)** —
   8 games concentrated on a 5-archetype cluster (13-17). Single
   bridge gap likely explains all 8 — reproduce arch=13 seed=4 and
   trace.
3. **`cast_spell::life_p1,stack` (opponent variant)** — should fix
   once the active-player variant is patched (same underlying
   mechanism, opposite controller).

The two **round-37 shapes did not reproduce** in 306 fresh games — a
re-run of the original failing seeds (arch=4 seed=0 max-turns=15) is
worth doing in round 42 to confirm whether `play_land::stack` and
`cast_spell::graveyard_p0,battlefield` are actually fixed on main
HEAD or just no longer firing at max-turns=20.

## Round 42 verification — round-41 cluster already closed by harness pre-cast floor

Round 42 picked up the round-41 H1 hypothesis that the
`cast_spell::life_p0,stack` (×8) cluster on arch 13-17 represented a
single bridge gap. Reproduction on current main (`add70c40` /
`439bd28a`) shows the cluster — and its sibling shapes — already at
zero divergences.

### Targeted reproducer (cluster's own seed/arch range)

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
    scripts/bench_trajectory_parity.py \
    --archetypes 13-17 --seeds 0-5 --max-turns 20 --verbose
```

| Status            | Count |
|-------------------|-------|
| Total games       | 30    |
| PASS              | 0     |
| FAIL_DIVERGENCE   | 0     |
| FAIL_TIMEOUT      | 30    |
| Wall time         | 38.1s |

All 30 games TIMEOUT cleanly (no creatures past the filter for
attack_all to swing); previously every arch 13-17 × seed 4 game in
round-41's Sweep B fired the `cast_spell::life_p0,stack` shape, so the
cluster's deterministic divergence has vanished.

### Wider re-run of Sweep B's full grid

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
    scripts/bench_trajectory_parity.py \
    --archetypes 0-50 --seeds 0-5 --max-turns 20 \
    --json-out tmp/bench_wide.json
```

| Status            | Sweep B (round 41) | Round 42 re-run |
|-------------------|--------------------|-----------------|
| Total games       | 306                | 306             |
| PASS              | 10                 | 16              |
| FAIL_DIVERGENCE   | 17                 | **0**           |
| FAIL_TIMEOUT      | 279                | 290             |
| Wall time         | 406s               | 399s            |

| Shape                                    | Sweep B | Round 42 |
|------------------------------------------|---------|----------|
| `cast_spell::life_p0,stack`              | 8       | **0**    |
| `cast_spell::stack`                      | 6       | **0**    |
| `cast_spell::life_p1,stack`              | 3       | **0**    |
| `play_land::stack`                       | 0       | 0        |
| `cast_spell::graveyard_p0,battlefield`   | 0       | 0        |

Zero divergences total across 306 games. The +6 PASS delta vs Sweep B
matches the games that previously fired one of the three closed shapes
and now run to a clean conclusion.

### Root cause attribution

The harness-only fix already on main —
**`5a24fe0f fix(parity): resolve_top_of_stack_python honors a pre-cast floor`**
(merged via `d2c95349`) — closed the entire cluster. That patch
changed `step_both`'s CE5 closure to drain Python's stack only down
to its pre-cast depth, leaving pre-existing landfall triggers in
place to match Rust's no-stack `cast_creature` observable.

Round-41 H1 was correct that all three shapes (`cast_spell::stack`,
`cast_spell::life_p0,stack`, `cast_spell::life_p1,stack`) shared a
common bridge mechanism — but the mechanism was the harness drain,
not a missing trigger pipeline on either engine side. The
`life_p0,stack` variant was a side effect of the same drain wiping
Python's persistent landfall-pump entries: once those entries went
missing, the matching life-loss trigger they would have resolved
into also went missing on Python while still resolving on Rust,
producing the compound `life_p0 + stack` divergence shape.

### Bench rerun result

- Cluster size before (round 41 Sweep B): 17 divergences total
  (8 life_p0,stack + 6 stack + 3 life_p1,stack).
- Cluster size after (round 42 verification on `439bd28a`): 0.
- New shapes surfaced: none — the cluster simply went silent.

### Next-round notes

- The two old `round-37` shapes (`play_land::stack`,
  `cast_spell::graveyard_p0,battlefield`) remain at 0 in round 42's
  306-game re-run — confirms they were fixed pre-round-41 and not
  just hiding behind a max-turns mismatch.
- Round 42+ slice budget for "chase the round-41 cluster" can be
  reallocated: the FAIL_TIMEOUT dominance (290/306 = 95%) is now the
  binding signal-coverage constraint. The CardDef filter extension
  work (I2's slice) is the highest-leverage path to surface new
  divergence shapes — admit more creatures and the new shapes will
  appear at seeds the current admit set never reaches.

## Round 43 — Thawbringer `cast_spell::stack` cluster fix (CE5 Rust mirror extension)

Round 43 closed the 7-divergence cluster that round-42 I2's CardDef
filter extension surfaced. All 7 incidents were
`cast_spell::stack` shape on Thawbringer-bearing archetypes
(0, 1, 10, 11, 12), all at T8 action 15 — the deterministic point
where p1 casts Thawbringer (id=77) for `{2}{G}`.

### Targeted reproducer (cluster's own arch+seed range)

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
    scripts/bench_trajectory_parity.py \
    --archetypes 0,1,10,11,12 --seeds 0-2 --max-turns 18 --verbose
```

| Status            | Pre-fix | Post-fix |
|-------------------|---------|----------|
| Total games       | 15      | 15       |
| PASS              | 0       | **7**    |
| FAIL_DIVERGENCE   | 7       | **0**    |
| FAIL_TIMEOUT      | 8       | 8        |

| Shape                                    | Pre-fix | Post-fix |
|------------------------------------------|---------|----------|
| `cast_spell::stack`                      | 7       | **0**    |

The 7 games that previously failed at T8 action 15 now run to a
clean `max_turns=18` conclusion.

### Wider sweep (round-41 Sweep B grid)

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
    scripts/bench_trajectory_parity.py \
    --archetypes 0-50 --seeds 0-5 --max-turns 20
```

| Status            | Round 42 | Round 43 |
|-------------------|----------|----------|
| Total games       | 306      | 306      |
| PASS              | 16       | **33**   |
| FAIL_DIVERGENCE   | 0        | 0        |
| FAIL_TIMEOUT      | 290      | 273      |

The +17 PASS delta over round 42 reflects the now-PASSing
Thawbringer-bearing games. No new divergence shapes appeared.

### Root cause attribution

Rust's `cast_creature` is no-stack for the cast itself, but the
`move_from_hand_to_battlefield` call inside it dispatches
`Event::Enters` via `state_ops_zones.rs::move_object`, which can
push a `StackItem::TriggeredAbility` for every ETB trigger the
printing declares. For Thawbringer ("when this creature enters,
surveil 1") that's exactly one ENTERS-trigger pushed per cast.
Rust's `cast_creature` does NOT run a priority loop, so that
trigger sits on Rust's stack indefinitely.

Python's `_cast_spell` → `resolve_top_of_stack` → ENTERS-fan-out
→ `resolve_top_of_stack` (drain the surveil trigger) → empty
stack, all driven by the harness CE5 `resolve_top_of_stack_python`
drain. Pre-fix the harness only drained Python, so Python ended at
floor while Rust still carried the surveil ENTERS trigger — the
divergence shape `stack(py=(), rust=((None,0,0,0,0,None,1,77),))`.

The fix: extend the CE5 closure with a sister
`resolve_top_of_stack_rust` primitive that drains Rust's stack
down to the same pre-cast floor as Python via
`rust_state.resolve_top_of_stack()`. Both engines now reach the
shared pre-cast floor before the post-step compare runs.

### Scope notes

- Harness-only change in `src/mtg_bot/parity/cross_engine.py`. No
  production Python touched, no production Rust touched.
- The fix generalizes beyond Thawbringer: any future
  CardDef-extension admit that pushes ENTERS-triggered abilities
  during `move_from_hand_to_battlefield` will land clean on the
  cross-engine bench without further harness work. The same drain
  also covers DIES-triggered surveil for Thawbringer when it dies
  in combat (the predicate-walk in `dispatch_event` handles DIES
  events the same way).

### Bench rerun result

- Cluster size before (round 42 narrow sweep): 7 divergences.
- Cluster size after (round 43): 0.
- Wider sweep (arch 0-50 × seeds 0-5): 0 divergences, +17 PASS
  delta vs round 42.
- New shapes surfaced: none.

## Round 45 small-batch verification

Round 45 ran a small-batch sweep against current main (`da8cc9e1`) to
re-verify cross-engine parity after the round-42/43/44 CardDef bridge
filter extensions (ENTERS surveil, DIES surveil, ATTACKS surveil,
ATTACKS draw_cards/gain_life). Round-40 G2 and round-44 K1 both timed
out on 306-game sweeps; this slice fits comfortably in agent budget
(~63 games / ~103s wall) and serves as a stable-point checkpoint
before round-46 work.

### Sweep configuration

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
    scripts/bench_trajectory_parity.py \
    --archetypes 0-20 --seeds 0-2 --max-turns 18 \
    --json-out tmp/bench_r45.json --verbose
```

### Aggregate

| Status            | Count |
|-------------------|-------|
| Total games       | 63    |
| PASS              | 8     |
| FAIL_DIVERGENCE   | **0** |
| FAIL_TIMEOUT      | 55    |
| ARCHETYPE_FILTERED | 0    |
| FAIL_EXCEPTION    | 0     |
| Wall time         | 102.88s |

### Divergence-shape histogram

**No divergences fired in 63 games.** No top-5 list to report. The
empirical pipeline is at a stable point — every round-37/38/41/42/43
divergence shape that previously chased remains at zero on current
main. The round-44 ATTACKS-trigger filter extension and Thawbringer
CE5 Rust drain mirror have not introduced regressions visible at
this sweep size.

### Per-archetype breakdown

| Arch | PASS | FAIL_TIMEOUT |
|------|------|--------------|
| 0    | 2    | 1            |
| 1    | 2    | 1            |
| 2    | 0    | 3            |
| 3    | 0    | 3            |
| 4    | 1    | 2            |
| 5    | 0    | 3            |
| 6    | 0    | 3            |
| 7    | 0    | 3            |
| 8    | 0    | 3            |
| 9    | 0    | 3            |
| 10   | 1    | 2            |
| 11   | 1    | 2            |
| 12   | 1    | 2            |
| 13   | 0    | 3            |
| 14   | 0    | 3            |
| 15   | 0    | 3            |
| 16   | 0    | 3            |
| 17   | 0    | 3            |
| 18   | 0    | 3            |
| 19   | 0    | 3            |
| 20   | 0    | 3            |

PASS counts are concentrated on archetypes 0,1,4,10,11,12 — the
Thawbringer-bearing cluster (arch 10/11/12 from round 43) and the
landfall-trigger cluster (arch 4 from round 37) all run cleanly to
PASS at seed=0/1, confirming the round-43 CE5 Rust drain mirror is
holding.

### New divergence-shape candidates for round 46+

**None surfaced.** With 0 divergences across 63 games at seeds 0-2 /
max-turns 18 covering archetypes 0-20, this slice contributes
**stable-point negative signal** rather than new chase candidates.

The binding constraint remains FAIL_TIMEOUT dominance (55/63 = 87%).
Round 46+ slice work to consider:

1. **Wider seed sweep** (seeds 0-5 × archetypes 0-20 × max-turns 20)
   — fits in ~6 min wall, would surface any divergence shapes that
   only fire at higher seeds (round-41 Sweep B observed
   divergence-bearing trajectories concentrated at seed=4).
2. **CardDef filter extension** — admit one creature per
   timeout-dominant archetype to convert FAIL_TIMEOUTs into real
   trajectory probes. Highest-leverage path for surfacing new
   divergence shapes.
3. **Re-target round-41 cluster archetypes (13-17)** at the wider
   seed range to confirm the round-42 harness pre-cast floor fix
   continues to hold past seed 2.

## Round 46 targeted-admittee verification

Round 46 ran a targeted bench against current main (`480fc4b4`) to
verify that the four recently-admitted creatures from rounds 36/37/42/45
(Eumidian Terrabotanist, Icecave Crasher, Thawbringer, Remnant
Elemental) introduce no new cross-engine divergences. The sweep
combined the higher-leverage seed-range (0-5) with `max-turns=22` to
expose deeper trajectory shapes than the round-45 stable-point
checkpoint reached.

### Admittee → archetype map (first 60 archetypes scanned)

| Admittee (round)               | Trigger shape                  | Archetypes carrying |
|--------------------------------|--------------------------------|---------------------|
| Thawbringer (r42)              | surveil ETB+DIES               | 0, 1, 10, 11, 12, 21, 30, 46 |
| Icecave Crasher (r37)          | landfall+pump_self             | 4, 5, 21, 43, 49, 51, 55, 57, 58 |
| Eumidian Terrabotanist (r36)   | landfall+gain_life             | 13, 14, 15, 16, 17, 30, 35, 44 |
| Remnant Elemental (r45)        | reach + landfall+pump_self     | 28, 48                  |

### Sweep A — primary targeted sweep

Invocation (10 archetypes × 6 seeds = 60 games):

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
    scripts/bench_trajectory_parity.py \
    --archetypes 0,1,4,5,10,11,12,13,14,15 --seeds 0-5 --max-turns 22 \
    --json-out tmp/bench_r46.json --verbose
```

| Status            | Count |
|-------------------|-------|
| Total games       | 60    |
| PASS              | 18    |
| FAIL_DIVERGENCE   | **0** |
| FAIL_TIMEOUT      | 42    |
| ARCHETYPE_FILTERED | 0    |
| FAIL_EXCEPTION    | 0     |
| Wall time         | 75.47s |

### Sweep B — Remnant Elemental supplement

Remnant Elemental's only round-0-to-59 carriers are arch 28 and arch 48;
those aren't in the Sweep A grid, so a follow-up covered them:

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
    scripts/bench_trajectory_parity.py \
    --archetypes 28,48 --seeds 0-5 --max-turns 22 \
    --json-out tmp/bench_r46_remnant.json --verbose
```

| Status            | Count |
|-------------------|-------|
| Total games       | 12    |
| PASS              | 0     |
| FAIL_DIVERGENCE   | **0** |
| FAIL_TIMEOUT      | 12    |
| Wall time         | 14.0s |

### Aggregate (Sweep A + Sweep B)

| Status            | Count |
|-------------------|-------|
| Total games       | 72    |
| PASS              | 18    |
| FAIL_DIVERGENCE   | **0** |
| FAIL_TIMEOUT      | 54    |
| Wall time         | 89.5s |

### Divergence-shape histogram

**No divergences fired across 72 games.** Top-5 list is empty — no new
shapes to chase. Every previously-tracked shape (round-37 `play_land::stack`,
`cast_spell::graveyard_p0,battlefield`; round-41 `cast_spell::stack`,
`cast_spell::life_p0,stack`, `cast_spell::life_p1,stack`; round-43
Thawbringer `cast_spell::stack` cluster) remains at zero.

### Per-archetype breakdown

| Arch | Carries                                | PASS | FAIL_TIMEOUT |
|------|----------------------------------------|------|--------------|
| 0    | Thawbringer                            | 3    | 3            |
| 1    | Thawbringer                            | 3    | 3            |
| 4    | Icecave Crasher                        | 5    | 1            |
| 5    | Icecave Crasher                        | 1    | 5            |
| 10   | Thawbringer                            | 2    | 4            |
| 11   | Thawbringer                            | 2    | 4            |
| 12   | Thawbringer                            | 2    | 4            |
| 13   | Eumidian Terrabotanist                 | 0    | 6            |
| 14   | Eumidian Terrabotanist                 | 0    | 6            |
| 15   | Eumidian Terrabotanist                 | 0    | 6            |
| 28   | Remnant Elemental                      | 0    | 6            |
| 48   | Remnant Elemental                      | 0    | 6            |

Thawbringer-bearing archetypes (0/1/10/11/12) and Icecave Crasher's
arch 4 produce real PASS games, confirming the round-43 CE5 Rust drain
mirror + round-37 landfall harness fix continue to hold under the
wider seed sweep and longer `max-turns=22`.

Eumidian Terrabotanist (arch 13/14/15) and Remnant Elemental
(arch 28/48) timeouts indicate the rest of those decks' creature
vocabulary still falls outside the CardDef bridge filter — `attack_all`
runs out of attackers and reaches the cap. Same FAIL_TIMEOUT pattern
the round-41/42 sweeps recorded; not a divergence, just zero coverage.

### Gate

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
    -m pytest tests/test_parity_smoke.py tests/test_cross_engine_etb_triggers.py \
    tests/test_trajectory_parity.py tests/test_trajectory.py --no-cov -n 4
```

1133 passed in 31.95s — no regressions from current `480fc4b4`.

### New divergence-shape candidates for round 47+

**None surfaced.** All four fresh admittees (rounds 36, 37, 42, 45)
land clean under seeds 0-5 / max-turns=22 at their carrier archetypes.
The pipeline is stable on the targeted admittee front.

Round 47+ slice work to consider:

1. **CardDef filter extension for Eumidian Terrabotanist / Remnant
   Elemental decks** — arch 13-17, 28, 48 still 100% FAIL_TIMEOUT
   because the admitted creature isn't enough to populate `attack_all`.
   Admitting one more creature per cluster would convert ~24 games
   into real trajectory probes.
2. **Wider archetype sweep** — extend to arch 0-50 × seeds 0-5 (~5 min
   wall) to surface any shape that requires both a wider deck-pool
   surface AND the longer max-turns this round adopted.
3. **Re-run round-37 reproducer** (arch 4 seed 0 max-turns 15) one
   more time to keep the historic regression-test pin alive — the
   original landfall shapes were last confirmed dead in round 42.

## Round 47 — stable-point re-verify + FAIL_TIMEOUT root-cause investigation

Round 47 re-ran the round-46 Sweep A grid against current main
(`22939a62`, post-handoff) as a comparable stable-point checkpoint, and
ran a dedicated instrumentation pass to validate or refute the standing
hypothesis (handoff "What to do next" / round-46 M3): *single-creature
archetypes can't sustain `attack_all`, so games never end and hit
max-turns → FAIL_TIMEOUT*.

### Sweep configuration (round-46 Sweep A shape, for comparability)

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
    scripts/bench_trajectory_parity.py \
    --archetypes 0,1,4,5,10,11,12,13,14,15 --seeds 0-5 --max-turns 22 \
    --json-out tmp/bench_r47.json --verbose
```

### Aggregate

| Status            | Round 46 (Sweep A) | Round 47 |
|-------------------|--------------------|----------|
| Total games       | 60                 | 60       |
| PASS              | 18                 | 18       |
| FAIL_DIVERGENCE   | **0**              | **0**    |
| FAIL_TIMEOUT      | 42                 | 42       |
| ARCHETYPE_FILTERED | 0                 | 0        |
| FAIL_EXCEPTION    | 0                  | 0        |
| Wall time         | 75.47s             | 78.34s   |

**Byte-identical to round 46** — same 18/0/42 split, same per-archetype
breakdown (0:3P/3T, 1:3P/3T, 4:5P/1T, 5:1P/5T, 10/11/12:2P/4T,
13/14/15:0P/6T). 0 FAIL_DIVERGENCE holds; the empirical pipeline is
stable across the round-46→47 boundary. No new divergence shapes
surfaced; the divergence histogram is empty.

### FAIL_TIMEOUT root-cause investigation — hypothesis **VALIDATED** (with refinement)

Instrumented the post-filter deck composition for the timeout-dominant
archetypes and traced a sample of TIMEOUT games end-to-end (casts,
attack-eligible turns, final life totals).

**Finding 1 — the post-filter deck has almost no creatures.** Each raw
40-card 17lands archetype carries 10–13 *distinct* creatures (12–14
creature cards), but the CardDef bridge filter
(`setup_matched_game_from_real_decks`) admits **only 1–2 of them** and
then pads the remaining ~58 slots of the 60-card deck with basic lands:

| Arch | Raw distinct creatures | Admitted creatures (name) | Lands in 60-card deck |
|------|------------------------|---------------------------|------------------------|
| 0    | 10                     | Thawbringer ×1            | 59                     |
| 5    | 12                     | Icecave Crasher ×1        | 59                     |
| 13   | 13                     | Hullcarver ×1, Eumidian Terrabotanist ×1 | 58 |
| 14   | 11                     | Eumidian Terrabotanist ×1 | 59                     |

**Finding 2 — two distinct timeout sub-mechanisms** (across all 42
TIMEOUT games in this sweep, every one hit the turn-22 cap exactly,
`turns_played=23`):

- **26/42 (62%): ZERO creatures ever cast.** With 1 creature buried in
  59 lands, the bench never draws it into a castable position before
  turn 22. No creature on the battlefield → no attacker → `attack_all`
  is a correct no-op → no damage → both players sit at 20/20 to the cap
  (e.g. arch 0 seed 2, arch 5 seed 0: final life `[20, 20]`, 0 casts,
  0 attack-eligible turns).
- **16/42 (38%): 1–2 creatures cast and attacking, but too small/slow
  to close 20 life in ≤22 turns.** Eumidian Terrabotanist is a 2/3;
  Thawbringer 4/2; Icecave Crasher 4/4 — all vanilla bodies. A single
  one cast around turn 6 and swinging every other turn deals ~14–18 by
  turn 22. Representative finals: arch 14 seed 0 `[4, 20]` (lone
  Terrabotanist attacked turns 8/10/.../22, ground p0 to 4 but ran out
  of turns); arch 13 seed 4 `[14, 8]`.

**Conclusion: the hypothesis is validated.** FAIL_TIMEOUT is *not* an
`attack_all` strategy defect and *not* a parity bug — `attack_all` is
correctly attacking with every eligible creature. The root cause is the
**CardDef bridge filter collapsing each archetype to a 1–2-creature,
~58-land deck**: most games have no creature to attack with, and the
rare games that do have a single small vanilla body that can't deal 20
before the cap. This is the same "zero creature coverage" pattern the
round-37/41/42/45/46 entries flagged qualitatively — round 47 quantifies
it (62% no-creature / 38% under-powered).

### Forward recommendation (NOT implemented this slice — docs-only)

The leverage path is **not** a different bench combat strategy
(`attack_all` is already optimal here — there's nothing more to swing
with) and **not** a max-turns bump (a lone 2/3 still can't close 20 in a
reasonable cap, and 22→40 turns multiplies wall time past the agent
budget). The binding constraint is the **filter admit set**. Concrete
options, highest-leverage first:

1. **CardDef bridge filter extension** (highest leverage, the standing
   round-42+ recommendation): admit 2–3 more vanilla/simple-trigger
   creatures per timeout-dominant archetype. Raising each deck from
   1–2 to ~6–8 creature copies would (a) make the no-cast 62% draw a
   creature in time and (b) give the cast games enough board to close
   before the cap — converting both timeout sub-populations into real
   trajectory probes. The raw-creature lists above (Biomechan Engineer,
   Galactic Wayfarer, Frenzied Baloth, Germinating Wurm, etc.) are the
   candidate vocabulary; vanilla/plain-ETB creatures are cheapest to
   admit per the round-2 bridge-correctness discipline.
2. **Optional bench-harness tweak (well-scoped, deferred):** add a
   `--require-creatures N` precondition that marks an (archetype, seed)
   game `ARCHETYPE_FILTERED` instead of `FAIL_TIMEOUT` when the
   post-filter deck has `< N` creature cards. This wouldn't add
   coverage, but it would *correctly classify* the 62% no-creature
   population as "filtered, no signal possible" rather than conflating
   it with genuine long-stall timeouts — making the FAIL_TIMEOUT count
   a truer signal-coverage metric. Left to a future slice since the
   brief scopes this round as investigation + docs only.
3. **Mulligan-to-creature opener (rejected):** forcing a mulligan until
   the opener contains the lone creature would distort the matched-state
   determinism the bench depends on and still wouldn't fix the
   under-powered-body sub-case. Not recommended.

### Gate

Docs-only slice (plus a `tmp/` JSON artifact and an ad-hoc instrumentation
script under `scripts/`); no production or harness behavior changed, so the
parity gate was not re-run. Round 46's gate (`1133 passed` on
`480fc4b4`) remains the last recorded baseline; nothing in this slice
touches code on the gate's path.

### New divergence-shape candidates for round 48+

**None surfaced.** 0 divergences across 60 games at the round-46 Sweep
A shape — stable-point negative signal. The round-47 contribution is
the **quantified FAIL_TIMEOUT root cause** (62% no-creature draw / 38%
under-powered body, both downstream of the 1–2-creature filter admit
set) and the prioritized forward recommendation: the CardDef filter
extension is the single highest-leverage lever, exactly as the
round-42/45/46 entries projected.

## Round 48 — post-expansion conversion measurement (Icetill Explorer admit)

Round 48 measures the bench-visible effect of round-48 N1's CardDef
bridge filter admit-set expansion (merge `8786788a`): the
`landfall+mill` leaf was admitted via the real EoE card **Icetill
Explorer**, raising Sweep-A archetypes **10/11/12 from 1→2 creature
copies each**. N1's own targeted sanity check (30 games) already showed
those three archetypes going 2→3 PASS with 0 FAIL_DIVERGENCE; this
slice runs the **identical round-46/47 Sweep A grid** for direct
comparability and quantifies the timeout→PASS conversion + checks
whether the newly-exercised `landfall+mill` code path surfaces any
cross-engine divergence (its real-game first exposure).

Round 48 also landed N2's Rust `EachOpponentLosesLifeEqualToYourLife
Total` substrate (merge `ca9013e8`) — no bench-visible effect (no EoE
consumer), so it does not figure in the conversion math.

Main HEAD at run: `8786788a` (N1 + N2 both merged this round).

### Sweep A — round-46/47 comparable grid

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
    scripts/bench_trajectory_parity.py \
    --archetypes 0,1,4,5,10,11,12,13,14,15 --seeds 0-5 --max-turns 22 \
    --json-out tmp/bench_r48.json --verbose
```

| Status            | Round 46 | Round 47 | Round 48 |
|-------------------|----------|----------|----------|
| Total games       | 60       | 60       | 60       |
| PASS              | 18       | 18       | **21**   |
| FAIL_DIVERGENCE   | **0**    | **0**    | **0**    |
| FAIL_TIMEOUT      | 42       | 42       | **39**   |
| ARCHETYPE_FILTERED | 0       | 0        | 0        |
| FAIL_EXCEPTION    | 0        | 0        | 0        |
| Wall time         | 75.47s   | 78.34s   | 76.32s   |

### Conversion delta — exactly 3 cells flipped, all on the expanded archetypes

A cell-by-cell diff of the round-47 JSON artifact (`tmp/bench_r47.json`)
vs round-48's (`tmp/bench_r48.json`) shows **exactly 3 differing cells,
all `FAIL_TIMEOUT → PASS`, all on the round-48-expanded archetypes at
seed 1**:

| Cell           | Round 47     | Round 48 |
|----------------|--------------|----------|
| arch=10 seed=1 | FAIL_TIMEOUT | **PASS** |
| arch=11 seed=1 | FAIL_TIMEOUT | **PASS** |
| arch=12 seed=1 | FAIL_TIMEOUT | **PASS** |

Every other one of the 60 cells is byte-identical to round 47. (Note:
the authoritative round-47 JSON shows arch 10/11/12 PASSing at seeds
**0 and 3** — the round-47 prose summary's "2P at seeds 0,1" was
imprecise; the artifact is the source of truth. Round 48 adds seed 1,
giving seeds 0/1/3 PASS.) Per-archetype conversion delta vs round 47:

| Arch | Carries (post-r48)              | R47 P/T | R48 P/T | Δ PASS |
|------|----------------------------------|---------|---------|--------|
| 0    | Thawbringer ×1                   | 3 / 3   | 3 / 3   | 0      |
| 1    | Thawbringer ×1                   | 3 / 3   | 3 / 3   | 0      |
| 4    | Icecave Crasher ×1               | 5 / 1   | 5 / 1   | 0      |
| 5    | Icecave Crasher ×1               | 1 / 5   | 1 / 5   | 0      |
| 10   | Thawbringer + **Icetill Expl. ×2** | 2 / 4 | **3 / 3** | **+1** |
| 11   | Thawbringer + **Icetill Expl. ×2** | 2 / 4 | **3 / 3** | **+1** |
| 12   | Thawbringer + **Icetill Expl. ×2** | 2 / 4 | **3 / 3** | **+1** |
| 13   | Eumidian Terrabotanist ×1        | 0 / 6   | 0 / 6   | 0      |
| 14   | Eumidian Terrabotanist ×1        | 0 / 6   | 0 / 6   | 0      |
| 15   | Eumidian Terrabotanist ×1        | 0 / 6   | 0 / 6   | 0      |

Total: **+3 FAIL_TIMEOUT → PASS, 0 regressions, 0 divergences.** The
conversion is exactly the predicted shape — the second Icetill Explorer
copy gives arch 10/11/12's seed-1 draw enough creature board to close
the game before the turn-22 cap, where the single-copy round-47 deck
ran out of attackers.

### Sweep B — expanded-archetype resolution (seeds 0–9)

To get extra resolution on the 3 expanded archetypes beyond seeds 0–5:

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
    scripts/bench_trajectory_parity.py \
    --archetypes 10,11,12 --seeds 0-9 --max-turns 22 \
    --json-out tmp/bench_r48_expanded.json --verbose
```

| Status            | Count |
|-------------------|-------|
| Total games       | 30    |
| PASS              | 9     |
| FAIL_DIVERGENCE   | **0** |
| FAIL_TIMEOUT      | 21    |
| Wall time         | 37.55s |

Per-archetype: 10/11/12 each 3 PASS / 7 FAIL_TIMEOUT (PASS at seeds
0/1/3; TIMEOUT at 2/4/5/6/7/8/9). Confirms the seed-1 conversion holds
and that seeds 6–9 (unreached by Sweep A) add no new divergence and no
further PASS — the 2-copy admit lifts exactly the one extra seed (1)
into the closeable band; the rest still lack enough creature board.

### Divergence-shape histogram

**No divergences fired across all 90 games (60 Sweep A + 30 Sweep B).**
The `landfall+mill` code path that round-48 N1's admit newly exercises
in real production-deck games ran clean on its first real exposure —
**0-divergence held**. This is the central result: the lever was
designed to surface a divergence if the new path mistranslated across
engines, and it did not. Every previously-tracked shape (round-37
`play_land::stack`, `cast_spell::graveyard_p0,battlefield`; round-41
`cast_spell::stack`, `cast_spell::life_p0,stack`,
`cast_spell::life_p1,stack`; round-43 Thawbringer `cast_spell::stack`)
remains at zero.

### Gate

Docs-only slice plus two `tmp/` JSON artifacts; no production, harness,
or bench-script behavior changed, so the parity gate was **not** re-run.
Round 48's pre-slice baseline (`8786788a`, **1185 passed**, orchestrator-
verified with the .pyd rebuilt after N1+N2 merged) remains the recorded
gate; nothing in this slice touches code on the gate's path.

### Remaining timeout population + forward recommendation

39/60 Sweep-A games (65%) still FAIL_TIMEOUT — the same root cause
round 47 quantified (1–2-creature decks padded with ~58 lands; most
games never draw a creature, the rest field a lone vanilla body that
can't close 20 before the cap). The Icetill Explorer admit converted
the 3 cells where a 2-copy deck just barely tips into closeable; it
does **not** touch the 36 remaining timeouts on archetypes that still
carry only 1 admitted creature (0/1/4/5 at their timeout seeds, all of
13/14/15).

**The filter-admit lever still has headroom but its character has
changed.** N1's round-48 scout flagged that the remaining filter
*rejects* are now dominated by **CreateToken / target-pick** features,
which need *substrate* work (Rust effect variants + bridge arms), not
a pure allowlist extension — i.e. the cheap "admit a vanilla creature"
extensions are largely exhausted on these specific Sweep-A archetypes.
The highest-leverage round-49+ paths, in order:

1. **Continue CardDef admits where a vanilla/plain-trigger creature
   still exists in a timeout-dominant archetype's raw list** (arch
   13/14/15 each carry 11–13 raw distinct creatures; only 1 admitted).
   Each new copy that tips a deck into the closeable band converts ~1
   timeout seed/archetype, exactly as the Icetill Explorer copy just
   did — but the per-admit yield is now ~1 game, not a cluster.
2. **CreateToken / target-pick substrate** (the Rust-lane work N1's
   scout points at) — unblocks the bigger remaining reject population
   but is multi-round substrate work, not a one-line filter admit.
3. **`--require-creatures N` bench-harness classification tweak**
   (round-47 deferred option 2): reclassify the no-creature-draw
   timeouts as `ARCHETYPE_FILTERED` so the FAIL_TIMEOUT count becomes a
   truer signal-coverage metric. Cosmetic for signal, not coverage.

Net for round 49: the filter-admit lever is **not exhausted** but its
cheap (vanilla-creature) headroom on the Sweep-A grid is thinning; the
remaining reject population is substrate-shaped per N1's flag, so the
campaign's center of gravity shifts back toward the Rust-substrate lane
(CreateToken / target-pick) for the next bulk-conversion step. No new
divergence-shape candidates surfaced — the `landfall+mill` path is
clean, so there is no round-49 fix slice from this measurement.

## Round 50 — Phase-4 real-game validation (Gravpack Monoist) + a round-49 substrate bug surfaced

Round 50 validates round-50 N1's token-substrate **Phase 4** (merge
`39f5f343` — `Effect::CreateTokenTapped` sister variant + loader
recognizer widen, flipping the real EoE card **Gravpack Monoist**
drop→admit, 25,252 of 129,996 17lands decks). N1's in-test probe
(`test_phase4_real_eoe_gravpack_monoist_tapped_token_byte_equal`)
already pins byte-equal tapped-token spawn in a single synthetic-
injection harness; this slice exercises the path in **real full-game
production-deck trajectories** for the first time. N2's `8695e6f0`
(docs-only residue plans) has no bench-visible effect.

Main HEAD at run: `39f5f343` (N1 + N2 both merged this round).

### Which archetypes carry Gravpack Monoist

`scripts/scout_r50_gravpack_archetypes.py` confirms the Phase-4 filter
now **ADMITS** Gravpack Monoist (`_printing_is_bridge_simple_creature
= True`; its DIES/IsSelf trigger recognizes as `create_token_tapped,
count=1`). Of the first 200 archetypes in the bench's
`load_production_deck` pool, **33 carry Gravpack Monoist** (~16.5%,
consistent with the 19%-of-decks figure). **ZERO of those 33 overlap
the standard Sweep-A grid (0,1,4,5,10–15)** — the standard grid never
exercises the path, so a targeted Gravpack-bearing sweep is mandatory.
(Note: Gravpack Monoist's *carrier* is a 2/1 flier "Human Scout"; the
2/2 Robot is its *token*. The task brief's "Creature — Robot, flying"
described the wrong half — immaterial to the result.)

### Sweep A — targeted Gravpack-Monoist grid

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
    scripts/bench_trajectory_parity.py \
    --archetypes 9,37,49,73,122,123,152,153,169,198 --seeds 0-5 \
    --max-turns 24 --json-out tmp/bench_r50_gravpack.json --verbose
```

(10 Gravpack-bearing archetypes — chosen for high copy counts
[37×3, 22/73/137/152/153/170/179×2] and multi-creature boards
[122/123/49/198 carry Icecave Crasher / Thawbringer / Eumidian
Terrabotanist alongside] so creatures can trade.)

| Status            | Count |
|-------------------|-------|
| Total games       | 60    |
| PASS              | 2     |
| FAIL_DIVERGENCE   | **0** |
| FAIL_TIMEOUT      | 2     |
| ARCHETYPE_FILTERED | 0    |
| **FAIL_EXCEPTION** | **56** |
| Wall time         | 73.4s |

### Sweep B — standard Sweep-A grid (round-48→50 comparability)

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
    scripts/bench_trajectory_parity.py \
    --archetypes 0,1,4,5,10,11,12,13,14,15 --seeds 0-5 \
    --max-turns 22 --json-out tmp/bench_r50_sweepA.json --verbose
```

| Status            | Round 48 | Round 50 |
|-------------------|----------|----------|
| Total games       | 60       | 60       |
| PASS              | 21       | **21**   |
| FAIL_DIVERGENCE   | **0**    | **0**    |
| FAIL_TIMEOUT      | 39       | **39**   |
| FAIL_EXCEPTION    | 0        | 0        |
| Wall time         | 76.3s    | 76.6s    |

**Byte-identical to round 48** — same 21/0/39 split, same per-archetype
breakdown (0:3P/3T, 1:3P/3T, 4:5P/1T, 5:1P/5T, 10/11/12:3P/3T,
13/14/15:0P/6T). The N1+N2 round-50 merges introduce **zero regression**
on the standard grid; timeout→PASS delta vs r48 is **0** (the Phase-4
lever doesn't touch any Sweep-A archetype, as the scout predicted).

### Central finding 1 — a real round-49 substrate bug, surfaced by Phase 4

The 56/60 `FAIL_EXCEPTION` on the Gravpack sweep is **one
deterministic error** repeated:

```
ValueError: cross_engine.register_token_printing: pid=N is already
registered to a DIFFERENT CardPrinting ('Robot'); refusing to
overwrite with 'Robot'. ... clear the registry via
clear_token_printings().
```

**Root cause** (pre-existing in round-49 N1's Phase-1 substrate, first
*exercised* by Phase 4's real-card admit):
`trajectory._seat_token_printings` (src/mtg_bot/parity/trajectory.py
~L3277-3279) calls `cross_engine.register_token_printing(pid,
py_printing)` once per `setup_matched_game_from_real_decks`
invocation but **never calls `clear_token_printings()` first**.
`_TOKEN_PRINTING_BY_PID` is a module-global in `cross_engine.py` that
persists across games. `_card_def_to_python_printing` builds a **fresh**
Robot `CardPrinting` per game, and the token's pid = its index in the
per-game `card_defs` union, which **varies by seed** (different opening
hands → different filtered libraries → different union ordering). So
game 2+ of any Gravpack-bearing archetype builds a new Robot printing,
collides with game 1's leftover registration, and the conflicting-
registration guard (`existing is not py_printing`, identity-based)
raises. The bench runs all games in one process → only the **first
game per archetype** registers cleanly (the 2 PASS + 2 TIMEOUT are
seed-0/first-seed games); every subsequent seed throws.

Minimal reproduction (same archetype 37, two seeds):
- seed 0: OK, registers `pid=5 → Robot`.
- seed 1, no clear: `ValueError` (pid=5, different Robot instance).
- seed 1, `clear_token_printings()` first: OK.

N1's in-test probe passes because it drives a **single** game in
isolation — exactly the gap the round-50 brief flagged ("the in-test
probe does not exercise real full-game production-deck trajectories").
This is **the round-51 fix slice**: make `_seat_token_printings`
cross-game-safe — either `clear_token_printings()` at pass entry, or
reuse a per-`(name, shape)` cached Python printing so repeat
registrations are identity-idempotent (the latter also keeps any
concurrently-seated tokens from other carriers intact). Small,
well-scoped, owned by the substrate (N1) lane.

### Central finding 2 — Phase-4 path stays byte-equal in real games (registry bug worked around), but the DIES→tapped-token resolve never *fires* in real bench games

To separate the substrate bug from the Phase-4 byte-equality question,
a follow-up drove the same 10 Gravpack archetypes with
`clear_token_printings()` between games (in-process, via
`bench_trajectory_parity.drive_one_game`):

| Sweep (per-game clear)         | Games | PASS | FAIL_DIV | FAIL_TIMEOUT | EXC |
|--------------------------------|-------|------|----------|--------------|-----|
| 10 arch × seeds 0-2            | 30    | 12   | **0**    | 18           | 0   |

**0 divergence** — once the round-49 registry bug is worked around,
every Gravpack-bearing real game runs byte-equal across both engines.
Gravpack Monoist is admitted and reaches the battlefield in **33 of 60**
games (a real drop→admit flip: pre-Phase-4 it was filtered out, those
decks collapsing to lands-only).

**However, an instrumented lifecycle scan (60 games, seeds 0-5) shows
Gravpack Monoist died in 0 of 60 games** (reached battlefield in 33,
in graveyard in 0), and **a Robot token spawned in 0 games**. Gravpack
Monoist is a 2/1 **flier**; the bridge-filtered mirror opponent is a
near-creatureless lands-padded deck with no fliers/reach to block it,
so under `attack_all` it attacks unblocked every turn and never dies.
No death → no DIES trigger → the `create_token_tapped` resolve arm is
never reached in a real production-deck trajectory.

**Verdict on the Phase-4 real-game validation:** the *admit* half of
Phase 4 is validated in real games (Gravpack Monoist enters the bench
decks, reaches the battlefield, and the rest of the trajectory stays
byte-equal across engines, 0 divergence). The *byte-equality of the
tapped-token spawn itself* is **NOT yet exercised by a real full-game
trajectory** — it remains pinned only by N1's synthetic-injection
in-test probe — because the deterministic `attack_all` bench can't
make an evasive 2/1 flier die in a creatureless mirror. This is the
same FAIL_TIMEOUT root cause round 47 quantified (1–2-creature decks
padded with ~58 lands) wearing a different hat: the lever admits the
card but the bench's combat model never produces the death that would
fire the trigger.

### Divergence-shape histogram

**No divergences across any sweep** (60 raw Gravpack [56 blocked by the
substrate bug before any trajectory ran, 4 ran clean], 60 Sweep-A, 30
per-game-clear Gravpack, 60 lifecycle-scan). Every previously-tracked
shape (round-37 `play_land::stack`, `cast_spell::graveyard_p0,
battlefield`; round-41 `cast_spell::stack`, `…life_p0,stack`,
`…life_p1,stack`; round-43 Thawbringer `cast_spell::stack`) remains
at zero. The Phase-4 `create_token_tapped` path produced **0 byte
divergences** everywhere it could be exercised.

### Gate

Docs + scout + `tmp/` JSON artifacts only; no production, harness, or
bench-script code changed (the `_seat_token_printings` bug is
*reported*, not fixed, here — round-51 N1 substrate slice). The
parity gate was **not** re-run; round-50's pre-slice baseline
(`39f5f343`, **1216 passed**, orchestrator-verified with the .pyd
rebuilt after N1+N2 merged) remains the recorded gate; nothing in this
slice touches code on the gate's path.

### Forward picture for round 51

1. **Round-51 fix slice (substrate lane / N1): cross-game-safe
   `_seat_token_printings`.** This is now a hard blocker on *any*
   real-game bench coverage of *any* token carrier (Phase 1's
   pre-positioned cluster + Phase 4's Gravpack), not just Gravpack —
   the bug is in the shared Phase-1 seating pass. Small fix
   (`clear_token_printings()` at pass entry, or identity-idempotent
   per-shape printing cache). Until it lands, every multi-game bench
   sweep that admits a token carrier is 1-clean-game-per-archetype
   then all-exception.
2. **The round-49 forward picture (Phase 3 Lander cluster is the next
   big lever) still holds** — Phase 3 (Galactic Wayfarer 33,469 /
   Beamsaw Prospector 24,310 / Edge Rover 15,271 / Biomechan Engineer
   / Glacier Godmaw, ~88k+ cumulative decks) remains the single
   largest remaining EoE-pool-delta lever and N1's recommended
   round-51 phase per `TOKEN_PRINTING_SUBSTRATE.md` §6. Round 50 adds
   one caveat: the Phase-3 admit will hit the **same**
   `_seat_token_printings` cross-game bug the moment a Lander carrier
   is admitted into a multi-game sweep, so the finding-1 fix should
   land **before or with** Phase 3 or its bench validation will be
   blocked identically.
3. **Bench combat-model limitation (documented, not new):** even with
   the substrate fix, the `attack_all` deterministic bench will not
   produce a Gravpack Monoist death in the creatureless filtered
   mirror, so real-game byte-equality of the *tapped-token spawn*
   stays unexercised until either (a) the filter admits enough
   blockers to trade (the round-42+ standing recommendation), or
   (b) a combat strategy / forced-removal harness path is added that
   can kill an evasive attacker. N1's synthetic in-test probe remains
   the byte-equality source of truth for the spawn itself; round 50
   confirms there is **no divergence** anywhere the path *can* be
   reached, so there is **no round-51 divergence-fix** from this
   measurement — only the substrate-blocker fix.

## Round 51 — cross-game-safe `_seat_token_printings` (round-50 finding 1 closed)

Round 51 N1 fixed the round-50-finding-1 substrate bug: the
`_seat_token_printings` cross-game token-registry conflict that made
every multi-game token-carrier sweep 56/60 `FAIL_EXCEPTION`. Fix
(merge to `origin/main`): `cross_engine.cached_token_printing` — an
identity-idempotent token-`CardPrinting` cache keyed by token SHAPE
(not pid), so the same logical token resolves to the SAME Python
object across every game/seed and `register_token_printing` never
hits the identity-based conflicting-registration guard. Chosen over
clear-at-pass-entry because the cache also preserves concurrently-
seated tokens from OTHER carriers (round-50 N3's stated reason).

### Before → after (same Gravpack-bearing grid shape)

| Status            | Round 50 (56/60-exc sweep) | Round 51 |
|-------------------|----------------------------|----------|
| Grid              | arch 9,37,49,73,122,123,152,153,169,198 × s0-5 (60) | arch 9,37,49,73,122 × s0-5 (**30**, ≤30-game cap) |
| PASS              | 2                          | 10       |
| FAIL_DIVERGENCE   | **0**                      | **0**    |
| FAIL_TIMEOUT      | 2                          | 20       |
| ARCHETYPE_FILTERED | 0                         | 0        |
| **FAIL_EXCEPTION** | **56**                    | **0**    |
| Wall time         | 73.4s                      | 37.9s    |

(Round-51 sweep scoped to 5 archetypes / 30 games to fit the agent's
≤30-game / <2-min hard cap; the per-archetype shape matches round 50's
on the overlapping archetypes. The relevant signal is the
`FAIL_EXCEPTION` column: **56 → 0**. The 56 round-50 exceptions were
all the single deterministic `register_token_printing` `ValueError`
on game 2+ of each archetype; round 51 has **zero**, every seed now
running cleanly through the cross-game registry.)

**`FAIL_TIMEOUT` is the unchanged, documented combat-model limitation
(round-50 finding 2), NOT a regression.** Gravpack Monoist is a 2/1
flier; the bridge-filtered creatureless mirror can't block it, so
under `attack_all` games run to max-turns instead of producing the
DIES that fires the trigger. The substrate-blocker fix removes the
exception wall *behind* which those games were never even reached;
the timeout ceiling above it is the same round-42+/round-50
single-creature-deck limitation. **0 `FAIL_DIVERGENCE`** everywhere
the path runs (consistent with round-50's per-game-clear validation:
once the registry bug is out of the way, every Gravpack-bearing real
game is byte-equal across engines).

### Gate

Parity gate **1216 → 1218** (+2: the two round-51 multi-game
regression pins in `tests/test_trajectory.py` —
`test_r51_seat_token_printings_cross_game_varying_pid_no_conflict`
[unit-level deterministic core] +
`test_r51_real_gravpack_archetype_multi_game_no_registry_conflict`
[end-to-end: 3 games of real archetype 37 across seeds 0/1/2 through
`setup_matched_game_from_real_decks` in one process, no registry clear
between games, asserting no `ValueError` + correct per-game bridge
resolution]). Both verified to FAIL with the exact round-50
`ValueError` when the fix is reverted, PASS with it. No Rust change →
no `.pyd` rebuild.

### Forward picture

The round-51 substrate-blocker is closed, so the round-49/50 forward
picture holds unblocked: **Phase 3** (Lander-token-activated-ability
sub-substrate — Galactic Wayfarer / Beamsaw Prospector / Edge Rover /
Biomechan Engineer / Glacier Godmaw, ~88k+ cumulative decks) is the
single largest remaining EoE-pool-delta lever and is now safe to
bench in multi-game sweeps the moment a Lander carrier is admitted
(the cross-game registry is no longer a blocker for ANY token
carrier). The bench combat-model limitation (an evasive flier never
dying in the creatureless filtered mirror, so the tapped-token spawn's
real-game byte-equality stays synthetic-pinned) is unchanged and
remains the round-42+ standing recommendation, independent of this
fix.
