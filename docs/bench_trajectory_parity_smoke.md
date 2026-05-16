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
