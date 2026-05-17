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

## Round 56 — token-cease-to-exist SBA + Lander-cluster real-game validation (round-55/53 sister of round-50 Gravpack)

Round 56 N3 validates **in real full production-deck games** the two
in-test-only closures behind the round-55/53/54 work:

- Round-55 N2 closed the **Rust token-cease-to-exist SBA (CR 111.7)**:
  a sacrificed/bounced/exiled token now ceases to exist on Rust
  byte-matching Python. Combined with round-54's Python-side
  post-search-shuffle + summoning_sick fixes, the round-53 genuine
  Galactic-Wayfarer Lander-activation probe's CONTRACT 2 flipped from
  a precisely-narrowed `graveyard_p0` known-gap to
  `compare_fields() == []` — **the WHOLE Lander sac-activation is now
  byte-equal cross-engine *in-test***.
- Round-53 N1 Phase 3a admitted the **57,779-deck Lander cluster**
  (Galactic Wayfarer 33,469 ENTERS+Lander; Beamsaw Prospector 24,310
  DIES+Lander) and round-50 N1 Phase 4 admitted **Gravpack Monoist**
  (25,252 DIES+tapped-Robot).

**None of this had been validated in real full-game trajectories** —
only in-test single-game probes. This is the sister of round-50's
Gravpack real-game validation (which surfaced a latent registry bug
the in-test probe missed). **It surfaced the analogous bug.**

`.pyd` provenance: the installed `mtg_bot_engine.cp313` is the
orchestrator's post-round-55 build (mtime 14:37, after the round-55
Rust token-SBA merge `5bd56d4a` at 14:35); the round-53/55 genuine
`test_phase3a_genuine_real_eoe_galactic_wayfarer_lander_activation`
probe + 3 round-55 token-cease bridge pins PASS against it (they would
FAIL with a stale-r53 `.pyd` on `graveyard_p0`), so these sweeps
exercise the real round-55 Rust code. No Rust change / no rebuild this
slice (pure scout + bench + docs).

### Scout — all three carriers ADMITTED; 22 double-DIES archetypes

`scripts/scout_r56_token_sba_lander_archetypes.py` (loads the gz pool
ONCE — `load_production_deck` reloads it per call, fine for the bench's
one-deck-per-game use but catastrophic for a 220-archetype scan):

| Carrier | Trigger → token | admit | of 220 |
|---|---|---|---|
| Galactic Wayfarer (3/3) | ENTERS+IsSelf → Lander (w/ `{2},Sac:SearchLibraryForBasicLandTapped`) | **ADMITTED** | 62 |
| Beamsaw Prospector (2/1) | **DIES**+IsSelf → Lander | **ADMITTED** | 43 |
| Gravpack Monoist (2/1 flying) | **DIES**+IsSelf → tapped 2/2 Robot | **ADMITTED** | 37 |

All three already admitted by round-53 Phase-3a `_SAFE_TRIGGERS`
(`("dies","source_is_self","create_token")`,
`("enters",…,"create_token")`) + round-50 Phase-4
(`("dies",…,"create_token_tapped")`) + the recognizer DIES
`safe_effect_kinds = (surveil, gain_life, draw_cards, create_token,
create_token_tapped)`. **22 archetypes carry ≥2 distinct DIES
carriers** (37,73,122,123,152,153,169,174,197,201,…) — the prime
token-SBA exercisers.

### Sweep A — double-DIES exercisers (raw bench, NO per-game clear)

```
scripts/bench_trajectory_parity.py --archetypes \
  37,73,122,123,152,153,169,174,197,201 --seeds 0-5 --max-turns 24 \
  --json-out tmp/bench_r56_sweepA.json --verbose
```

| Status | Count |
|---|---|
| Total games | 60 |
| PASS | 19 |
| **FAIL_DIVERGENCE** | **0** |
| FAIL_TIMEOUT | 29 |
| ARCHETYPE_FILTERED | 0 |
| **FAIL_EXCEPTION** | **12** |
| Wall | 77.4s |

**0 FAIL_DIVERGENCE**, empty divergence-shape histogram. All 12
`FAIL_EXCEPTION` are **one deterministic `ValueError`**, confined to
archetypes 73 & 197 — exactly the only Sweep-A archetypes carrying
**BOTH** a Lander carrier **AND** the Robot carrier (Gravpack Monoist).

### CENTRAL FINDING — a NEW latent registry bug, real-card-exposed (round-50 pattern, distinct root cause)

```
ValueError: cross_engine.register_token_printing: pid=7 is already
registered to a DIFFERENT CardPrinting ('Robot'); refusing to
overwrite with 'Lander'. ...
```

Reproduced + isolated to a 12-line repro (exact bench order:
`[(37,s) for s in 0..5] + [(73,s) for s in 0..5]`, one process, no
clear):

- arch 37: card_defs union size 6 → `_seat_token_printings` assigns
  **Lander=pid 6, Robot=pid 7**; `register_token_printing` writes both
  into the module-global `_TOKEN_PRINTING_BY_PID`.
- arch 73: union size 7 → token base pid = 7 → seating wants
  **Lander=pid 7, Robot=pid 8**. But `_TOKEN_PRINTING_BY_PID[7]` still
  holds **Robot** from arch 37 (the map persists process-wide;
  `clear_token_printings()` is never called by the bench).
  `register_token_printing(7, Lander)` finds `existing=Robot` (a
  different `CardPrinting` object) → the identity-conflict guard
  (`existing is not py_printing`, `cross_engine.py:258`) raises.

**This is NOT the round-50/51 bug** (that was the **same** Robot token
re-registered at a shifting pid across seeds of **one** archetype;
round-51's shape-keyed `cached_token_printing` closed it — same Robot
object → identity-idempotent). The round-56 bug is **two DIFFERENT
token shapes (Lander vs Robot) colliding on the SAME pid across
DIFFERENT archetypes** in one bench process: the pid is a per-game
`card_defs`-union index that varies by archetype, while
`_TOKEN_PRINTING_BY_PID` is keyed by **pid** (not shape) and persists
process-wide. Round-51's cache (keyed by token *shape*) cannot help —
Lander and Robot are different shapes / different cached objects; the
collision is at the **pid key**, not object identity. Round-51's own
docstring scoped its fix to "two carriers printing the **same-named**
token" — the multi-distinct-token cross-archetype pid clash was out of
scope and is **real-card-exposed for the first time** here by round-53
Phase-3a (Lander admit) + round-50 Phase-4 (Robot admit) **co-occurring
in a real multi-archetype sweep**. In-test probes never expose it
(single archetype, single token shape, `clear_token_printings()`
fixture teardown) — **exactly the round-50 in-test-probe blind spot
the brief flagged**. This is the high-value find and the **round-57
fix slice** (substrate / N1 lane, sister of round-51 N1's fix).

Recommended round-57 fix: make `register_token_printing` / the
`_seat_token_printings` pid-assignment cross-game-safe for *multiple
distinct* tokens. Round-51's shape-keyed cache made same-shape repeats
idempotent; the round-57 sister fix must make the pid→printing map
tolerate the same pid being reused by a *different* token shape across
games (the conflicting-registration guard should key on the
(pid, current-game) tuple, OR `_seat_token_printings` should
`clear_token_printings()` at pass entry — the round-50-N3-considered
clear-at-entry option, now justified because round-51's
concurrently-seated-tokens-from-other-carriers concern is satisfied
within a single game's seating pass; OR overwrite-allow when the new
printing is itself a cached_token_printing for a different shape).
Small, well-scoped, owned by the substrate lane.

### Sweep A′ + B — byte-equality validation (per-game `clear_token_printings()`, the round-50-N3 workaround)

To separate the round-56 registry bug from the byte-equality question,
the same grids were driven via `bench.drive_one_game` with
`clear_token_printings()` between games:

| Sweep | Grid | Games | PASS | FAIL_DIV | TIMEOUT | EXC |
|---|---|---|---|---|---|---|
| A′ double-DIES | 37,73,122,123,152,153,169,174,197,201 ×s0-2 | 30 | 12 | **0** | 18 | **0** |
| A′ double-DIES | …same ×s0-5 (lifecycle) | 60 | 26 | **0** | 34 | **0** |
| B GW-heavy | 0,1,2,3,4,7,8,13,16,35 ×s0-5 | 60 | 35 | **0** | 25 | **0** |

**0 FAIL_DIVERGENCE / 0 FAIL_EXCEPTION** across all 150 per-game-clear
games. Once the round-56 registry bug is worked around, **every
Lander/Robot-carrier real production-deck game runs byte-equal across
both engines** — the round-53 Phase-3a admit + CONTRACT-1
token-entering guarantee holds in real games at scale (same pattern as
round-50/51's Gravpack per-game-clear validation).

### Lifecycle scan — does the round-55 token-SBA path actually FIRE in real games?

`scripts/scout_r56_token_lifecycle_scan.py` instruments the Python
state's battlefield + `state.log` (`turn.move_off_battlefield` appends
`"<name> token ceases to exist"` for **every** token bf-exit — the
exact event that triggers the round-55 Rust SBA on the other engine):

| Lifecycle (per-game-clear) | Sweep A′ 60 | Sweep B 60 |
|---|---|---|
| carrier reached battlefield | 42/60 | 44/60 |
| **token created** (Lander/Robot reached bf) | 3/60 | **44/60** |
| **token LEFT bf** (round-55 SBA fires) | **0/60** | **0/60** |
| token-SBA fired & DIVERGED | **0** | **0** |

Sweep B is decisive: the **Galactic Wayfarer Lander spawns on ETB in
every game where the carrier reaches the battlefield (44/44)** — the
token-*entering* path (round-53 CONTRACT 1) is exercised in real
production-deck games at high rate and stays **byte-equal
cross-engine, 0 divergence**. But the **token LEFT the battlefield in
0/120 games**: the bench never sac-activates the Lander (it only emits
`activate_ability` for tapping lands for mana — the SEARCH_LIMITATIONS
round-55 §2 note), and the DIES carriers (Beamsaw Prospector /
Gravpack Monoist) never die because the bridge-filtered creatureless
mirror can't kill them under `attack_all` (the round-50/51 finding-2
combat-model limitation). The 3 Sweep-A′ token-created games (arch 73
Galactic Wayfarer) ended PASS with the Lander **still on the
battlefield**.

### Validation verdict

| Claim | Verdict |
|---|---|
| Round-53 Phase-3a Lander carriers + round-50 Phase-4 Gravpack admitted & reach bf in real games | **VALIDATED** (carrier on bf 42–44/60; Galactic Wayfarer Lander spawns 44/44 where it ETBs) |
| Admit + **token-entering** byte-equal cross-engine in real games (round-53 CONTRACT 1) | **VALIDATED** — 0 FAIL_DIVERGENCE across 150 per-game-clear games incl. 44 real Lander-entering games; round-55-built `.pyd` |
| Round-55 **token-cease-to-exist SBA** byte-equal *fired* in a real full-game trajectory | **NOT EXERCISED** by the bench (token created but **never leaves bf** in 0/120 — bench never sac-activates the Lander; DIES carriers never die in the creatureless mirror). Remains pinned ONLY by round-53's synthetic-injection genuine in-test probe (which is GREEN against this `.pyd`). Same root cause as round-50 finding-2, one tier deeper. |
| New cross-engine divergence | **NONE** — 0 FAIL_DIVERGENCE everywhere the path can be reached |
| Latent bug surfaced | **YES — a NEW multi-distinct-token cross-archetype pid-collision in `register_token_printing` (round-57 fix)** — the round-50 sister-validation pattern, distinct root cause from round-50/51 |

Net: the **admit + token-entering** half of the round-53/50 Lander +
Gravpack work is now real-game-validated byte-equal at scale; the
**token-cease-to-exist SBA** byte-equality stays synthetic-pinned
(unreachable under the bench's strategy set, the round-42+ standing
combat-model limitation), and the validation surfaced one **new latent
registry bug** that is real-card-exposed and is the round-57 fix.

### §2-correct admit widen — NOT NEEDED this round (decided, not deferred)

N2-r55 recommended "widen the bench filter to admit token-bearing
DIES+IsSelf+CreateToken carriers now that token cease-to-exist is
byte-equal." **Investigation shows this widen is already in place** —
round-53 N1 Phase 3a (`("dies","source_is_self","create_token")` +
the `_token_with_safe_activated_ability_card_def` Lander recognizer)
and round-50 N1 Phase 4 (`("dies","source_is_self",
"create_token_tapped")`) already admit every DIES+IsSelf+CreateToken
carrier the §2 discipline allows (Beamsaw Prospector, Gravpack
Monoist); the recognizer's DIES `safe_effect_kinds` already carries
both `create_token` and `create_token_tapped` (trajectory.py:2702).
The scout confirms all three carriers ADMITTED on the round-53/55
worktree code with **no `_SAFE_*` change**. The round-53 §2 decline
ledger (Edge Rover `each_player`→Phase 5, Seedship Agrarian
`BECOMES_TAPPED`, Biomechan Engineer carrier-activated-ability,
Glacier Godmaw sibling-trigger, Sunstar Expansionist And-StateBound,
Biotech Specialist sibling, Bioengineered Future non-creature→Phase 2)
is unchanged — every one is still §2-correctly declined; admitting any
would be a silent mistranslation. **No widen made, none deferred — the
admit set is already §2-maximal.** No harness/`_SAFE_*` code touched →
no gate run needed (pure scout + bench + docs; baseline 1293 untouched).

### Gate

Docs + 2 `scripts/scout_*.py` diagnostics + `tmp/` JSON artifacts
only; no production / harness / `_SAFE_*` / bench-script code changed
(the `register_token_printing` cross-archetype bug is **reported**, not
fixed — round-57 substrate slice). Parity gate **not** re-run; nothing
in this slice is on the gate's path (baseline **1293** unchanged). No
Rust → no `maturin`.

### Forward picture for round 57

1. **Round-57 fix slice (substrate / N1 lane): multi-distinct-token
   cross-archetype-safe `register_token_printing` /
   `_seat_token_printings`.** This was a HARD blocker on raw
   multi-archetype bench coverage of *any* deck carrying ≥2 distinct
   token shapes (Lander + Robot) — not just the 73/197 pair; the bug
   triggered whenever a Lander-carrier archetype and a Robot-carrier
   archetype were swept in one process and their per-game union sizes
   differed by the right amount. Round-51's shape-keyed cache made
   same-shape repeats idempotent; the round-57 sister fix made the
   pid→printing map tolerate the same pid reused by a *different*
   token shape across games. Small, well-scoped, sister of round-51.

   **>> CLOSED — round-57 N1 (`feature/fix-token-pid-cross-shape-r57`,
   merge `825e2106`).** Chosen approach: round-56 N3's option (b) —
   `_seat_token_printings` calls a new
   `cross_engine._reset_token_printing_pid_map_for_seating_pass()` at
   pass entry, clearing ONLY the per-game `_TOKEN_PRINTING_BY_PID` map
   while deliberately preserving the round-51 shape-keyed
   `_TOKEN_PRINTING_CACHE_BY_KEY`. Justification on all three criteria:
   (i) round-51 same-shape cross-game identity-idempotence PRESERVED
   (the shape cache is untouched, so the same logical token still
   resolves to the SAME object every game — round-51's pins, extended,
   stay green); (ii) cross-shape collision FIXED (a stale prior-game
   pid→Robot entry is gone before this game registers pid→Lander —
   N3's exact `[(37,s) s0-5]+[(73,s) s0-5]` order goes
   6/12-then-`ValueError` pre-fix → **12/12 clean** post-fix); (iii)
   NO within-game silent mis-resolution (the seating pass writes the
   complete correct pid→printing map AND rewrites every carrier
   trigger's `token_printing_id` in the SAME pass from the SAME dict;
   the bridge runs only after, reading a self-consistent map; the
   identity-conflict guard in `register_token_printing` is UNCHANGED
   and still catches genuine probe collisions). Options (a)
   `(pid, current-game)` guard key (structural non-starter — the
   bridge has no game-identity token; runs before any state exists)
   and (c) different-shape overwrite-allow (weakens the
   probe-collision detector) were rejected. Pinned by 2 new r57 pins
   (unit + e2e cross-shape) + the round-57-extended r51 pins, all in
   `tests/test_trajectory.py`. See `docs/SEARCH_LIMITATIONS.md`
   "Cross-engine token-printing registry — two-axis safety". **Raw
   multi-archetype bench sweeps of decks carrying ≥2 distinct token
   shapes are now UNBLOCKED for round-58 N3 bench validation — the
   per-game `clear_token_printings()` workaround is no longer
   required** (the in-code pass-entry reset gives the same per-game
   isolation natively, so `bench_trajectory_parity.py`'s normal
   in-process multi-archetype loop is safe as-is).
2. **The token-cease-to-exist SBA real-game byte-equality stays
   synthetic-pinned** (round-53 genuine in-test probe) until either
   (a) the filter admits enough blockers for DIES carriers to trade in
   real combat (the round-42+ standing recommendation), or (b) a
   forced-removal / sac-activation harness path is added that can kill
   an evasive attacker OR drive the Lander's `{2},Sac` activation. The
   bench's strategy set structurally cannot reach it (round-50
   finding-2, one tier deeper — now confirmed for the Lander cluster
   too). No round-57 divergence-fix from this measurement — only the
   substrate-blocker fix.
3. **Phase 5** (`each_player` recognizer → Edge Rover, 15,271 decks)
   and **Phase 2** (non-creature Lander carriers → Bioengineered
   Future) remain the next §2-honest pool-delta levers, both unchanged
   by this validation.

---

## Round 58 (2026-05-16) — N3: token-cease-to-exist SBA real-game validation, raw multi-archetype unblock confirmed

The standing open question since round 55: the round-55 N2 Rust
token-cease-to-exist SBA (CR 111.7 — a token leaving the battlefield
ceases to exist) is byte-pinned by the round-53 genuine in-test probe
but has **never been validated in real production-deck games** (round
55/56: bench never sac-activates Landers, DIES carriers never die in
the creatureless mirror → token never leaves bf, 0/120; raw
multi-archetype sweeps were then blocked by the round-56 cross-shape
token-pid collision). Round-57 N1 closed the pid collision
(`feature/fix-token-pid-cross-shape-r57`, merge `825e2106`, SHA-fill
`443e1a22`). This round answers the question definitively on the
unblocked path.

### Raw multi-archetype is CONFIRMED UNBLOCKED (round-57 N1 fix verified)

The round-57 in-code per-game pid-map reset
(`_reset_token_printing_pid_map_for_seating_pass`) is verified to make
the per-game-`clear_token_printings()` workaround **genuinely no longer
required**. Run **directly through the un-modified
`bench_trajectory_parity.py` in-process multi-archetype loop** (no
workaround):

| Sweep | Grid | Games | PASS | FAIL_DIV | TIMEOUT | EXC |
|---|---|---|---|---|---|---|
| Round-56 collision repro pair | 37,73 ×s0-5 | 12 | 9 | **0** | 3 | **0** |
| Raw multi (20 double-token archetypes) | 18,36,37,39,63,64,73,88,91,97,122,123,137,139,152,153,169,170,174,201 ×s0-2 | 60 | 16 | **0** | 44 | **0** |

The exact round-56 collision-trigger order `[(37,s) s0-5]+[(73,s)
s0-5]` (Lander-carrier + Robot-carrier archetypes, distinct token
shapes, differing per-game union sizes) — which pre-fix raised the pid
`ValueError` at 6/12 games — now runs **12/12 clean, 0 FAIL_EXCEPTION**.
The 60-game raw multi-archetype sweep across 20 distinct
≥2-distinct-token-shape archetypes (Lander + Robot co-occurring) is
**0 FAIL_EXCEPTION, 0 FAIL_DIVERGENCE**. **Raw in-process
multi-archetype bench sweeps of decks carrying ≥2 distinct token
shapes are confirmed unblocked.** The per-game-clear workaround is
retired.

### Does the token-cease-to-exist SBA FIRE in real games?

`scripts/scout_r58_token_sba_strategy_probe.py` is the round-56
lifecycle scan generalized over the `--combat-strategy` axis (same
bench per-step primitives; Python source of truth for "did it fire",
the `_DivergenceError`/`AssertionError` gate for cross-engine
byte-equality). 240 games total across the prime double-DIES-carrier
archetypes:

| Lifecycle (raw, in-process, no workaround) | `attack_all` 120 | `attack_all_block_smallest` 120 |
|---|---|---|
| carrier reached battlefield | 84/120 | 84/120 |
| token created (Lander/Robot on bf) | 6/120 | 6/120 |
| **token LEFT bf (round-55 SBA fires)** | **0/120** | **0/120** |
| token-SBA fired & DIVERGED | **0** | **0** |

**Verdict: the token-cease-to-exist SBA is STRUCTURALLY
UN-EXERCISABLE by the current bench combat model — and the limitation
is strategy-INDEPENDENT.** It is NOT real-game-validated; it remains
pinned ONLY by the round-53 genuine synthetic-injection in-test probe
(GREEN against the current `.pyd`). Do not fold the SEARCH_LIMITATIONS
in-test-pinned caveat to validated.

### Root cause — quantified, one tier deeper than round-56 stated

The round-56 doc attributed the non-firing to "bench never
sac-activates the Lander; DIES carriers never die in the creatureless
mirror." Round-58 instrumentation pins the **exact two-token
structural split**:

- **Lander** (Galactic Wayfarer ENTERS / Beamsaw Prospector DIES) is
  a `Token Artifact` — **NOT a creature** (P/T `None/None`). Its ONLY
  battlefield-exit is its `{2}, Sacrifice` activated ability. The
  bench emits `activate_ability` ONLY for mana-tapping lands, never a
  non-mana sac ability — under **any** combat strategy. A Lander
  **structurally cannot leave the battlefield** in a bench game;
  combat strategy is irrelevant to it. (The 6/120 token-created games
  are all Lander-on-bf, ending with the Lander still on bf — matches
  the round-56 Sweep-A′ observation.)
- **Robot** (Gravpack Monoist DIES) IS a `Token Artifact Creature`
  2/2 — it CAN die in combat. But it spawns only when Gravpack
  Monoist (2/1) **dies first** (a DIES trigger). Board-development
  trace (arch 37, all 6 seeds, `attack_all_block_smallest`): final
  boards are **24–27 permanents that are almost entirely lands**
  (Forest/Island/Swamp), ≤1–2 creatures ever in play, `block`-log
  lines 0–2 per game. The bridge-filtered mirror is so creature-sparse
  that the DIES carrier rarely reaches bf and essentially never trades
  (no opposing creatures to block / be blocked by). `token created`
  for the Robot path = **0/120** even with the defender-blocks
  strategy. This is the round-50/56 creatureless-mirror limitation,
  now confirmed one tier deeper AND proven strategy-independent (the
  defender-blocks strategy cannot help when there is nothing on the
  board to block).

### §2-correct admit/strategy tweak — EVALUATED, NOT a cheap unlock (decided, not deferred)

Slice §3 asked whether a minimal §2-correct admit-filter widen or a
bench-strategy tweak is the cheap unlock. **Empirically answered NO,
this round, not deferred speculatively:**

- **Strategy tweak (`attack_all_block_smallest`): tested, does NOT
  unlock.** 120 games under the defender-blocks strategy →
  still 0/120 token-LEFT-bf. Strategy cannot manufacture combat trades
  on a creatureless board, and is wholly irrelevant to the
  non-creature Lander.
- **Admit-filter widen: not the lever.** The carriers are ALREADY
  admitted (round-53 Phase-3a + round-50 Phase-4 — confirmed round 56,
  §2-maximal). The blocker is board sparsity + the Lander being a
  non-creature with only a sac-activated exit, neither of which an
  admit widen of the existing §2-correct shape classes addresses.
  Widening to non-§2 classes (e.g. carriers gated at
  `activated_abilities`, `BECOMES_TAPPED` — N1 is concurrently
  bridging the latter; not depended on here) would be a silent
  mistranslation and is correctly declined per the standing
  bridge-correctness discipline.

**No §2-correct tweak made — none is a cheap unlock; the precise
required unlock is specified below for a future deliberate slice.**

### The EXACT minimal unlock spec (for a future deliberate slice — not this one)

To fire the round-55 token-cease-to-exist SBA in a real bench game,
ONE of the following dedicated harness extensions is required (all are
larger than this Python/bench slice and out of scope here — a precise
deferral):

1. **Lander path — a sac-activation harness path.** Add an opt-in
   bench driver step that emits `activate_ability` for the Lander's
   `{2}, Sacrifice` ability when the controller has ≥2 open mana
   (deterministic, both engines via `step_both`). This is the ONLY
   way a Lander ever leaves the battlefield; it is the smallest,
   most-targeted unlock and exercises the SBA directly. Est. ~1
   focused slice (new bench step + a `RealGameCombatAgent`-sibling
   "activate sac abilities" toggle + cross-engine pin). Review-gated
   (touches the bench driver).
2. **Robot path — a forced-removal / DIES harness OR a creature-dense
   admit floor.** Either (a) a forced-removal harness path that can
   destroy a carrier on demand (the round-42+ standing
   "DIES-event harness, review-gated" recommendation), or (b) widen
   the admit floor enough that the mirror develops real boards where a
   2/1 Gravpack Monoist trades in combat → Robot spawns → Robot trades
   → SBA fires. Path (b) depends on the much larger §2-honest
   pool-delta levers (Phase 5 `each_player`, Phase 2 non-creature
   carriers) bringing in enough creatures to make combat routine —
   indirect and unbounded. Path (a) is the cleaner targeted unlock,
   shared-shape with the Lander sac path (#1) — a single
   "harness-driven non-mana activation / forced bf-exit" slice could
   cover both.

Recommended round-59 deliberate slice (if the campaign wants the SBA
real-game-validated rather than synthetic-pinned): **option #1 — the
Lander sac-activation harness step.** It is the minimal, most-direct,
single-card-deterministic path; the Lander is admitted today and
spawns reliably (44/44 on Galactic Wayfarer ETB per round-56 Sweep B);
only the bf-exit emission is missing.

### Validation verdict

| Claim | Verdict |
|---|---|
| Raw in-process multi-archetype bench sweeps (≥2 distinct token shapes) unblocked by round-57 N1 fix | **CONFIRMED** — round-56 collision pair 37,73 ×s0-5 → 12/12 clean (was 6/12-then-ValueError pre-fix); 60-game 20-archetype raw sweep 0 FAIL_EXCEPTION / 0 FAIL_DIVERGENCE; per-game-clear workaround retired |
| Round-55 token-cease-to-exist SBA byte-equal *fired* in a real full-game trajectory | **STRUCTURALLY UN-EXERCISABLE** by the current bench combat model — strategy-INDEPENDENT (0/240 across `attack_all` + `attack_all_block_smallest`). Lander = non-creature, sac-exit-only, no bench `activate_ability` for it; Robot = needs a DIES carrier to trade on a near-creatureless board. NOT real-game-validated; stays round-53 synthetic-in-test-pinned. |
| §2-correct admit/strategy tweak as a cheap unlock | **NO** — strategy tweak tested (0/120), admit set already §2-maximal; neither addresses the structural cause. Precise harness-extension unlock spec specified above and deferred (a precise deferral is the correct outcome). |
| New cross-engine divergence | **NONE** — 0 FAIL_DIVERGENCE across all 312 games (12 + 60 bench + 240 lifecycle) |
| New latent bug surfaced | **NONE** |

Net: round-57 N1's token-pid fix is **real-game-confirmed** —
raw multi-archetype bench coverage of ≥2-distinct-token decks is
unblocked with no workaround. The round-55 token-cease-to-exist SBA
byte-equality stays **synthetic-pinned** (round-53 genuine in-test
probe); it is structurally un-exercisable by the bench's
combat+mana-only-activation model independent of combat strategy, and
the exact minimal unlock (a Lander sac-activation harness step) is
specified for a future review-gated deliberate slice.

### §2-correct admit widen — NOT NEEDED / NOT a lever this round

The admit set is unchanged and remains §2-maximal (round-53 Phase-3a +
round-50 Phase-4; the round-56 decline ledger is unchanged — every
declined carrier would be a silent mistranslation). No `_SAFE_*` /
harness / bench-script / production code touched. **N1 is concurrently
bridging `BECOMES_TAPPED`; this slice deliberately does NOT depend on
it.**

### Gate

Docs + 1 `scripts/scout_*.py` diagnostic
(`scout_r58_token_sba_strategy_probe.py`) + `tmp/bench_r58.json`
artifact only. **No production / harness / `_SAFE_*` / bench-script
code changed** — the bench was run un-modified; the new scout is a
pure diagnostic. Parity gate **not** re-run; nothing in this slice is
on the gate's path (baseline **1315** unchanged). No Rust → no
`maturin`.

### Forward picture for round 59

1. **Token-cease-to-exist SBA real-game validation is BLOCKED on a
   harness extension, not a bench/filter tweak.** The cheapest unlock
   is **option #1 above — a Lander `{2},Sac` activation harness step**
   (review-gated, ~1 slice). Until then the SBA stays correctly
   round-53 synthetic-in-test-pinned; do not represent it as
   real-game-validated.
2. **Raw multi-archetype is now a free coverage lever.** With the
   round-57 fix real-game-confirmed, future bench rounds can sweep
   arbitrary ≥2-distinct-token-shape archetype mixes in one process
   with no workaround — useful for surfacing other divergences as the
   admit set widens.
3. **Phase 5** (`each_player` → Edge Rover) and **Phase 2**
   (non-creature Lander carriers) remain the next §2-honest pool-delta
   levers; they would also indirectly help the Robot path (#2(b)) by
   making the mirror creature-dense enough for routine combat — but
   the targeted Lander sac harness (#1) is the direct,
   bounded route to real-game SBA validation.

## Round 59 (2026-05-16) — N3: token-cease-to-exist SBA REAL-GAME VALIDATED byte-equal (the round-58 N3 Lander sac-activation harness step, built + run)

The round-58 N3 deferral is now closed. The standing open question
since round 55 — *is the round-55 N2 Rust token-cease-to-exist SBA
(CR 111.7) byte-equal when it FIRES in a real production-deck game,
or is it only round-53-synthetic-in-test-pinned?* — is answered
**definitively: REAL-GAME VALIDATED, byte-equal, 0 divergence.**

### The harness step (round-58 N3's exact spec, built)

`scripts/bench_trajectory_parity.py::_try_activate_lander_sac` — a
**narrow, deterministic, default-off, review-gated** bench-driver
step:

- **Narrow.** Activates ONLY a `Lander` token's `ability_index=0`
  (the `{2},Sac:SearchLibraryForBasicLandTapped`). It is explicitly
  NOT a general "bench activates arbitrary abilities" change (that
  would alter bench combat/mana semantics broadly and is out of
  scope per round-58 N3 + the standing bridge-correctness
  discipline). It only fires when a Lander is on the active player's
  bf AND a basic land exists in library to search AND `{2}` is
  payable.
- **Default-off / opt-in.** Gated behind `--activate-lander-sac`
  (CLI) → `drive_one_game(activate_lander_sac=False)` default. With
  the flag off the step is a complete no-op; the bench / production
  self-play is **byte-for-byte unchanged**. It is a *validation*
  harness, not a behavior change to production self-play.
- **Same activation on BOTH engines (fair cross-engine
  comparison).** Mirrors the proven in-test probe
  `test_phase3a_genuine_real_eoe_galactic_wayfarer_lander_activation`
  exactly: (a) ONE shared `random.Random` threaded into both engines
  (`py_state.rng` + `rust_state.set_external_rng`) so the round-54
  post-search shuffle is byte-equal (SEARCH_LIMITATIONS #15 closure
  recipe), installed **lazily once per game** only when the first
  real Lander activation happens (Lander-free games are
  byte-for-byte unaffected); (b) `{2}` colorless seeded
  **symmetrically** into both mana pools (deterministic — not
  dependent on which lands auto-tap); (c) the activation driven via
  `step_both` (identical `{kind:activate_ability, source_id,
  ability_index:0}`, no target — the search is untargeted); (d) the
  Lander's ability is NOT a mana ability so it goes on the stack —
  BOTH stacks drained to the pre-activation floor
  (`resolve_top_of_stack_python`/`_rust`) and field views
  re-compared. Any cross-engine divergence raises `_DivergenceError`
  exactly like every other bench step.

### Validation sweep — the SBA now FIRES and is byte-equal

`scout_r59_lander_sac_lifecycle.py` (the round-58 lifecycle scout
re-pointed at the harness step; Python source of truth for "did the
SBA fire" via the `"Lander token ceases to exist"` log line, the
bench's `_DivergenceError` gate for cross-engine byte-equality).

Sweep: archetypes `18,36,37,39,63,64,73,88,91,97` × seeds `0-5` =
**60 games**, `attack_all`, max-turns 22, harness step ENABLED:

| Lifecycle (harness ON) | round-58 (no harness) | **round-59 (harness ON)** |
|---|---|---|
| carrier reached bf | 84/120 | 43/60 |
| token created | 6/120 | 6/60 |
| Lander sac activations | 0 | **6** |
| **token LEFT bf (round-55 SBA fires)** | **0/240** | **6/60** |
| **SBA fired & no divergence** | n/a | **6/6** |
| **ANY FAIL_DIVERGENCE** | **0** | **0** |

Production bench `bench_trajectory_parity.py --activate-lander-sac`
(archetypes `36,73` × seeds `0-5` = 12 games, the Lander-producing
grid — `tmp/bench_r59.json`): **0 FAIL_DIVERGENCE / 0
FAIL_EXCEPTION**. Default-off control (`73 × s1,2` WITHOUT the flag):
PASS, identical to pre-change (the no-op guarantee holds).

**Every Lander created (6/6) was sac-activated, LEFT the
battlefield, ceased to exist on BOTH engines (graveyard empty on
both — CR 111.7), and the whole post-sac field view was byte-equal
cross-engine.** The round-58 finding of token-LEFT-bf `0/240`
(structurally un-exercisable) is now token-LEFT-bf `6/6` on every
token-created game — the structural blocker is closed by the
specified harness step. Token *creation* stays seed-dependent (6/60
— matches round-58; the carrier's ETB/DIES trigger must actually
fire; the harness unlocks the token *exit*, it cannot manufacture
token *creation*).

### Verdict

| Claim | Verdict |
|---|---|
| Round-55 token-cease-to-exist SBA byte-equal *when fired in a real full-game trajectory* | **REAL-GAME VALIDATED** — 6/6 token-created games: Lander sac-activated → left bf → ceased to exist on both engines → whole field view byte-equal (0 FAIL_DIVERGENCE). The round-53 synthetic-in-test caveat in SEARCH_LIMITATIONS can be folded → **validated**. |
| Harness step scoped/gated correctly | **YES** — narrow (Lander sac ability only), default-off (`--activate-lander-sac`; no-op when off, no-Lander, or no basic to search), same activation both engines (shared-rng + symmetric `{2}` + `step_both` + post-resolve drain/compare). Default bench / production self-play byte-for-byte unchanged. |
| New cross-engine divergence | **NONE** — 0 FAIL_DIVERGENCE across all 72 games (60 lifecycle + 12 production-bench). |
| New latent bug surfaced | **NONE** — the first real-game exercise of the full sac→search→shuffle→token-cease path is clean (it had been pinned only synthetically; round-58 flagged a divergence here as "entirely possible"; none surfaced). |

### Gate

Baseline **1325** → **1326** (+1: `test_r59_lander_sac_harness_step
_byte_equal_and_default_off`, pinning no-Lander-no-op /
Lander-present-activates+token-leaves-bf+SBA-fires /
whole-field-view-byte-equal). Full gate
(`test_parity_smoke.py + test_cross_engine_etb_triggers.py +
test_trajectory_parity.py + test_trajectory.py`) **1326 passed, 0
fail**. No Rust → no `maturin`.

### Forward picture for round 60

1. **Token-cease-to-exist SBA real-game validation is DONE.** The
   round-55 SBA is now byte-equal-validated end-to-end through the
   real activation in real production-deck games — no longer a
   synthetic-in-test-only pin. The SEARCH_LIMITATIONS round-53/55
   "in-test-pinned" caveat folds to validated (orchestrator action).
2. **The Lander sac harness is a reusable validation lever.** Any
   future Lander-cluster cross-engine work (the 57,779-deck Galactic
   Wayfarer / Beamsaw Prospector cluster) can now real-game-exercise
   the full sac→search→shuffle→token-cease path via
   `--activate-lander-sac` — no synthetic injection needed.
3. **The Robot path remains the round-58 #2 deferral.** Gravpack
   Monoist's 2/2 Robot still needs a DIES carrier to trade on a
   near-creatureless mirror (round-50/56 limitation). The cleaner
   targeted unlock is the round-42+ standing "DIES-event /
   forced-removal harness, review-gated" — shared shape with this
   round's Lander sac harness. Phase 5 (`each_player` → Edge Rover) /
   Phase 2 (non-creature Lander carriers) remain the §2-honest
   pool-delta levers that would also indirectly creature-densify the
   mirror.

## Round 61 (2026-05-16) — N3: post-r57-admit-surface sweep — REAL cross-engine divergence found (2-color non-basic land mana-ability bridge mismatch; first exposed by the round-60 shocklands)

The round-58/59/60 work admitted a substantial new surface that had
**never been exercised at scale in real production-deck games**: the
round-60 **5 pay-life shocklands** (Breeding Pool / Watery Grave /
Stomping Ground / Godless Shrine / Sacred Foundry — +18,065 cumulative
17lands decks that previously collapsed to lands-light bridge sets,
now running real dual-color manabases), round-58/59 **Seedship
Agrarian** (whole card: BECOMES_TAPPED→Lander + landfall+1/+1), and
the round-60 **Perigee Beckoner** Effect half. This round ran the
highest-real-signal lever — a fresh production-deck bench divergence
sweep over that expanded surface. **It found a REAL cross-engine
divergence** (the round-50-Gravpack / r53-Mightform / r55-Pulsar /
r56-token-pid pattern: a newly-admitted code path running in real
games surfaces a genuine engine-to-engine bug).

### Scouted surface — which archetypes carry it, what the loader admits

`scripts/scout_r61_postadmit_surface.py` (carrier + bridge-admit
confirmation over the 129,996-deck 17lands pool):

| Surface | raw carrier archetypes | sampled admit | bench-relevant |
|---|---|---|---|
| 5 shocklands | **16,477** | 14/14 admit (arches 30/67/69 carry **2** shocklands → **2 dual-color lands** in the bridged deck) | YES — biggest delta; real dual manabase materializes |
| Seedship Agrarian | 14,078 | 14/14 admit | YES |
| Perigee Beckoner | 21,131 | **0/14 admit** | NO — full card stays loader-gated on `warp_cost` per SEARCH_LIMITATIONS (only the Effect half shipped). Expected/correct, NOT a sweep target. |

The shockland admit is real and material: pre-r60 these decks
bridge-collapsed to lands-light; post-r60 the bridged deckspec now
carries the 1-2 dual-color `mana_produced` lands (verified —
arch 30 Stomping Ground+Watery Grave, arch 69 Breeding Pool+Watery
Grave, etc.). This is the **first time a 2-color `mana_produced`
land reaches real bench play** (every basic is single-color).

### Sweeps + full result counts

| Sweep | Grid | Games | PASS | FAIL_DIV | TIMEOUT | EXC | FILTERED |
|---|---|---|---|---|---|---|---|
| A — shocklands | arch 30,37,43,46,54,57,58,61,62,63,67,69,86,88 ×s0-3 | 56 | 28 | **3** | 25 | 0 | 0 |
| B — Seedship Agrarian | arch 5,15,16,17,40,46,50,53,67,70,73,75,86,96 ×s0-3 | 56 | 24 | **1** | 31 | 0 | 0 |
| **Total** | | **112** | **52** | **4** | **56** | **0** | **0** |

`attack_all`, max-turns 22, mulligans off. `tmp/bench_r61_shockland.json`
+ `tmp/bench_r61_seedship.json`. Wall 71s + 72s (under the ~3-min cap).

### The divergence — captured precisely (the high-value find)

All **4 FAIL_DIVERGENCE have the IDENTICAL byte shape** —
`activate_ability` :: `mana_pool_pX`, Rust pool carries a **spurious
extra `('U', 1)`** that Python does not:

| Sweep | arch | seed | turn | a-idx | byte-diff |
|---|---|---|---|---|---|
| A | 37 | 3 | 9 | 17 | `mana_pool_p0` py=`('B',2),('U',0)…` rust=`('B',2),('U',1)…` |
| A | 46 | 0 | 8 | 15 | `mana_pool_p1` py=`('G',2),('U',0)…` rust=`('G',2),('U',1)…` |
| A | 69 | 0 | 10 | 19 | `mana_pool_p1` py=`('G',2),('U',0)…` rust=`('G',2),('U',1)…` |
| B | 46 | 0 | 8 | 15 | `mana_pool_p1` py=`('G',2),('U',0)…` rust=`('G',2),('U',1)…` |

(Sweep-B arch 46 is the **same game** as Sweep-A arch 46 — the
divergence is the Breeding Pool mana ability, NOT Seedship; arch 46
carries both. Seedship Agrarian itself produced **0**
Seedship-specific divergences — no BECOMES_TAPPED/landfall+counter
divergence — across all 56 Sweep-B games.)

Every divergent archetype runs a **2-color shockland that includes
`U`**: arch 37 = Watery Grave (B/U), arch 46 = Breeding Pool (G/U),
arch 69 = Breeding Pool (G/U) + Watery Grave (B/U). The spurious
mana is always the land's *second* color.

### Root cause — the two `mana_produced` mana-ability bridges DISAGREE for a multi-color land

Deterministic, no-game repro:
`scripts/scout_r61_shockland_mana_divergence.py` (synthesized
`CardDef(mana_produced=("B","U"))`):

- **Python** (`cross_engine._card_def_to_python_printing`,
  ~L8912-8920): builds **ONE `ActivatedAbility` per color** in
  `mana_produced`:
  - `ability_index=0` = `{T}: AddManaToPool(('B',1))`
  - `ability_index=1` = `{T}: AddManaToPool(('U',1))`
- **Rust** (`cards.rs::apply_mana_produced_bridge`, ~L6387-6436):
  builds **ONE synthesized ability** whose effect aggregates **ALL**
  colors. For ≥2 colors it wraps them in a **`Sequence`**:
  - `ability_index=0` = `{T}: Sequence(Add B, Add U)` — both colors
    in a single activation.

For a **single-color** land (every basic) both bridges produce one
ability that adds the one color — bit-equal, which is why this never
surfaced before round-60. For a **2-color** land they diverge: the
bench (and any consumer) taps a land via
`activate_ability(land_id, ability_index=0)`; Python adds **one**
color, Rust adds **BOTH** → Rust's pool gains the spurious second
color (the captured extra `U`).

This is a **REAL cross-engine divergence** (Rust ≠ Python), not a
shared CR-incompleteness — though it is *also* CR-incorrect on the
Rust side (a real dual land's mana ability adds **one chosen** color,
not all). The campaign-relevant defect is the engine-to-engine
disagreement; round-60's shockland admit is exactly the first
real-game exercise that exposed it (`SEARCH_LIMITATIONS.md`
shockland entry asserted byte-equality via 3 *static CardDef
compare* pins + 1 `attack_all` probe on arch 30 — arch 30's bridged
duals are Stomping Ground (R/G) + Watery Grave (B/U); the probe
evidently did not drive an `activate_ability(dual, 0)` deep enough to
hit it, so the pins were insufficient — they compared field views,
not the activated mana-ability effect shape).

### Verdict

| Claim | Verdict |
|---|---|
| Round-60 shockland admit produces a cross-engine divergence when exercised at scale | **YES — REAL FAIL_DIVERGENCE.** 4/112 games (3 distinct, arch 46 double-counted across sweeps). 2-color non-basic land mana-ability bridge mismatch: Python = one ability per color, Rust = one ability adding all colors (`Sequence`). `activate_ability(dual,0)` → Rust over-produces the 2nd color. Root cause pinned deterministically (`scout_r61_shockland_mana_divergence.py`). |
| Seedship Agrarian (r58/r59 whole card) byte-equal at scale | **VALIDATED CLEAN** — 0 Seedship-specific divergences across 56 Sweep-B games; the BECOMES_TAPPED→Lander + landfall+1/+1 surface holds at scale on real production decks. (The 1 Sweep-B FAIL is the orthogonal shockland bug on arch 46's Breeding Pool, not Seedship.) |
| Perigee Beckoner | NOT admitted by the loader (full card warp_cost-gated; only the Effect half shipped) — expected/correct, no bench exposure, validated as designed. |
| Shockland manabase expansion measurably changed game dynamics | **YES** — the bridged decks now carry real dual-color `mana_produced` lands (1-2 per deck) instead of lands-light collapse; this is precisely what reached the previously-untested 2-color mana-ability code path and surfaced the bug. |

### Round-62 fix recommendation (HIGH VALUE — Rust lane)

Make the two `mana_produced` mana-ability bridges build the **same
per-color ability shape**. The CR-correct shape is **one
`is_mana_ability` `ActivatedAbility` per distinct color** (the player
chooses which color when activating) — i.e. fix the **Rust** side
(`cards.rs::apply_mana_produced_bridge`) to emit one ability per
color (Python is already correct: `ActivateAbility(land,0)` = first
color, `…,1)` = second). This is a **Rust slice** (requires
`maturin develop --release` + `.pyd` rebuild) — out of scope for this
Python/bench round; serialized to the single Rust agent next round.
Pin: the deterministic `scout_r61_shockland_mana_divergence.py`
mechanism + a cross-engine `activate_ability(dual_land, 0)` /
`(…, 1)` byte-equal probe + a re-run of Sweep A (must go
0-FAIL_DIVERGENCE). Also widen the `SEARCH_LIMITATIONS.md` shockland
entry's pin set: the 3 static-CardDef-compare pins must be
supplemented by an **activated-mana-ability** cross-engine pin
(field-view compare alone missed this). NOTE: until the Rust fix
lands, the round-60 shockland admit is shipping a **latent
real-game cross-engine divergence** — flag forward; do not
represent the shockland surface as byte-equal-validated at scale.

### Gate

Pure docs + 2 `scripts/scout_*.py` diagnostics
(`scout_r61_postadmit_surface.py`, `scout_r61_shockland_mana_divergence.py`)
+ 2 `tmp/bench_r61_*.json` artifacts. **No production / harness /
`_SAFE_*` / bench-script code changed** — the bench was run
un-modified; the scouts are pure diagnostics. Parity gate **not**
re-run (nothing in this slice is on its path; baseline **1386**
unchanged). No Rust → no `maturin`. The divergence-fix is a
round-62 Rust-lane slice.

### Forward picture for round 62

1. **HIGH-VALUE Rust fix queued**: the 2-color non-basic land
   mana-ability bridge mismatch. `apply_mana_produced_bridge` must
   emit one `is_mana_ability` ability per color (matching Python +
   CR). Deterministically pinned (`scout_r61_shockland_mana_divergence.py`);
   re-run Sweep A as the regression gate. This is the round-50/53/55/56
   pattern — a newly-admitted code path's first real-game exercise
   found a genuine cross-engine bug.
2. **Seedship Agrarian validated clean at scale** — the r58/r59
   BECOMES_TAPPED + landfall+counter surface holds byte-equal on
   real production decks; no further validation needed there.
3. **The shockland surface is NOT yet byte-equal-validated** —
   correct it before representing it as such. After the round-62 Rust
   fix, a clean Sweep-A re-run closes it.
4. **Timeout note**: 56/112 games FAIL_TIMEOUT (creature-sparse
   bridged mirrors hitting max-turns=22 — the standing round-50/58
   creatureless-mirror limitation, unchanged; not a regression). The
   shockland admit deepened some games (more spells castable off real
   dual mana) but the lands-heavy 17lands-limited decks still stall on
   the creature floor — the §2-honest pool-delta levers (Phase 5
   `each_player`, Phase 2 non-creature carriers) remain the route to
   creature-dense mirrors.

## Round 62 (2026-05-16) — N3: BROAD full-admitted-surface divergence sweep — clean broad validation; only the known-r61 shockland shape recurs (non-deterministically), 0 NEW divergence

Where round-61 N3's sweep was deliberately scoped to the **newly-
admitted post-r57 surface** (shocklands / Seedship / Perigee) and found
the 2-color shockland mana-ability divergence (**Agent N1 is fixing
that specific Rust `apply_mana_produced_bridge` bug this round**),
round-62 N3 ran the complementary **BROAD** sweep across the *full*
admitted production-deck surface — many archetypes spanning every
admitted feature class, not just the recent admits — to surface any
*other* latent cross-engine divergence before subsystem work resumes.

### Scouted surface — the full admitted span

`scripts/scout_r62_broad_admit_surface.py` walked the 17lands pool in
10 evenly-spaced archetype-index windows (starts
`0,40,80,120,160,200,300,400,600,800`, 14 arches each), deep-loaded
each through the REAL production loader, and tallied admitted feature
classes. **108 sweepable archetypes** (index 0–812) exercising the
whole admitted surface:

| Admitted class | aggregate count (sampled) | carrier archetypes |
|---|---|---|
| keyword `trample` | 29 | broad |
| keyword `flying` | 23 | broad |
| keyword `deathtouch` | 19 | broad |
| keyword `defender` / `vigilance` / `reach` | 8 / 6 / 3 | broad |
| trigger `enters` (ETB) | 159 | 78 arches |
| trigger `dies` (DIES) | 78 | 64 arches |
| trigger `becomes_tapped` (r58 admit) | 20 | 20 arches (5,40,46,50,53,86,…) |
| 2-color `mana_produced` land (r60 shockland) | — | 22 arches (43,46,86,88,122,123,124,125,130,131,132,165,167,…) |
| vanilla creatures | 21 | 21 arches |

### Sweeps + full result counts (4 batches, ≤60 games each, HARD cap honored)

| Batch | Span / feature focus | Grid | Games | PASS | FAIL_DIV | TIMEOUT | EXC | FILTERED | Wall |
|---|---|---|---|---|---|---|---|---|---|
| A | low-index broad (vanilla + ETB/DIES + becomes_tapped) | arch 0,1,2,3,4,5,7,8,9,10,11,12,13,40,42 ×s0-3 | 60 | 35 | **0** | 25 | 0 | 0 | 76s |
| B | mid-index (dual-land + becomes_tapped + dies heavy) | arch 43,46,86,88,122,123,124,125,128,129,130,131,132,160,161 ×s0-3 | 60 | 26 | **6** | 28 | 0 | 0 | 76s |
| C | high-index keyword-rich (far from shockland carriers) | arch 200,201,203,300,304,307,400,403,409,600,602,802,804,809,811 ×s0-3 | 60 | 25 | **0** | 35 | 0 | 0 | 76s |
| D | dual-land + becomes_tapped carriers, seed offset 2-5 | arch 47,48,50,51,53,89,90,91,92,165,167,169,170,171,205 ×s2-5 | 60 | 15 | **0** | 45 | 0 | 0 | 76s |
| **Total** | full admitted surface, idx 0–811 | | **240** | **101** | **6** | **133** | **0** | **0** | |

`attack_all`, max-turns 22, mulligans off. JSONs
`tmp/bench_r62_batch{A,B,C,D}.json` (+ `_batchB_rerun`, `_divsubset`
triage artifacts). Every batch wall ≤76s, well under the ~3-min cap.

### Divergence triage — ALL 6 are the KNOWN round-61 shockland shape (N1-owned); 0 NEW

All 6 Batch-B FAIL_DIVERGENCE have the **identical** byte shape
`activate_ability::mana_pool_pX`, on archetypes carrying **exactly one
2-color shockland** (verified via `production_deck_to_deckspec`):

| arch | seed | turn | a-idx | bridged dual land |
|---|---|---|---|---|
| 46 | 0 | 8 | 15 | Breeding Pool (G/U) |
| 122 | 0 | 10 | 19 | Watery Grave (B/U) |
| 122 | 1 | 7 | 13 | Watery Grave (B/U) |
| 123 | 0 | 10 | 19 | Watery Grave (B/U) |
| 123 | 1 | 7 | 13 | Watery Grave (B/U) |
| 130 | 0 | 8 | 15 | Breeding Pool (G/U) |

This is the **KNOWN round-61 2-color shockland mana-ability shape** —
Python builds one `AddManaToPool` ability per color
(`idx0`=1st color, `idx1`=2nd), Rust's `apply_mana_produced_bridge`
builds one ability aggregating ALL colors (`Sequence`), so
`activate_ability(dual,0)` makes Rust over-produce the land's 2nd
color. Confirmed still-deterministic at the *bridge* level by re-running
the round-61 deterministic pin `scout_r61_shockland_mana_divergence.py`
(Python idx0=`Add B`, idx1=`Add U` for Watery Grave; Rust idx0=
`Sequence(Add B, Add U)`). **Classified `known-r61-N1-owned`; NOT
re-reported as a new find** — Agent N1 is fixing this exact Rust bug
this round. **Zero NEW (non-shockland) divergence shapes across all
240 games.** Zero FAIL_EXCEPTION.

### NEW datum (round-63-relevant): the bench-level surfacing is NON-DETERMINISTIC / order-dependent

A genuinely new observation about the *manifestation* (not a new bug —
the underlying defect is the r61 N1-owned one):

- Calling the bench's own `drive_one_game(arch, seed)` **in isolation**
  for each of the 6 divergent (arch,seed) pairs →
  **all 6 PASS** (`scout_r62_divergence_bytediff_capture.py`).
- Re-running the **identical Batch-B grid** (same archetypes, seeds,
  flags, single process) → **0 FAIL_DIVERGENCE** (those 6 → PASS;
  `tmp/bench_r62_batchB_rerun.json`).
- Running **only the divergent subset** `46,122,123,130 ×s0-1` in one
  process → **0 FAIL_DIVERGENCE / 8 PASS** (`tmp/bench_r62_divsubset.json`).
- The divergence only surfaces with the **full preceding
  archetype-ordering** in the same process.

Interpretation: the r61 shockland bug is real and deterministic at the
*bridge* level (`scout_r61_shockland_mana_divergence.py` always
reproduces). Its **bench-level surfacing is order/state-dependent** —
which `ability_index` the bench's land/cast driver ends up activating
(and whether the spurious 2nd color persists into the compared field
view) depends on accumulated cross-game state in the bench process, so
a full-game sweep flakes between FAIL_DIVERGENCE and PASS for the same
(arch,seed). **This directly informs the round-62 fix's regression
gate**: a Sweep-A/Sweep-B *re-run* alone is an unreliable gate (it can
flake green even with the bug present, as the Batch-B rerun did). The
**deterministic** `scout_r61_shockland_mana_divergence.py` bridge-shape
pin + a synthetic `activate_ability(dual_land, 0)` / `(…,1)` byte-equal
cross-engine probe are the reliable regression pins; the full-game
sweep is corroborating signal only.

### Verdict

| Claim | Verdict |
|---|---|
| Broad full-admitted-surface sweep surfaces a NEW latent cross-engine divergence | **NO — CLEAN BROAD VALIDATION.** 240 games across idx 0–811 / every admitted feature class (vanilla, flying/trample/deathtouch/defender/vigilance/reach, ETB/DIES/becomes_tapped triggers, basics+dual manabases). 0 NEW divergence shapes, 0 FAIL_EXCEPTION. |
| The only divergences are the known-r61 shockland shape | **YES.** All 6 FAIL_DIVERGENCE are the round-61 2-color shockland mana-ability shape on single-shockland carriers — `known-r61-N1-owned`, not re-reported. |
| Round-61 underlying shockland bug still real | **YES** — `scout_r61_shockland_mana_divergence.py` still deterministically reproduces the Python (per-color) vs Rust (`Sequence` aggregate) bridge mismatch. N1's fix this round is correctly targeted. |
| Seedship Agrarian / becomes_tapped surface clean at broader scale | **VALIDATED CLEAN** — becomes_tapped carriers (40,46,50,53,86,171,205,…) across Batches A/B/D produced 0 becomes_tapped-specific divergence; the r58/r59 surface holds on the broader span. |
| Bench divergence surfacing is deterministic | **NO (new datum)** — order/state-dependent within a process; same (arch,seed) flaps PASS↔FAIL_DIVERGENCE depending on preceding archetype-ordering. Round-62 fix gate must rely on the deterministic bridge pin, not a full-sweep re-run. |

### Gate

Pure docs + 2 `scripts/scout_*.py` diagnostics
(`scout_r62_broad_admit_surface.py`,
`scout_r62_divergence_bytediff_capture.py`) + 6 `tmp/bench_r62_*.json`
artifacts. **No production / harness / `_SAFE_*` / bench-script code
changed** — the bench was run un-modified; the scouts are pure
read-only diagnostics. Parity gate **not** re-run (nothing in this
slice is on its path; baseline **1386** unchanged). No Rust → no
`maturin`. The shockland divergence-fix remains the round-62 N1
Rust-lane slice (in progress concurrently).

### Forward picture for round 63

1. **The broad admitted surface is byte-equal-validated** (modulo the
   known-r61 shockland bug). 240 games across the full feature span
   surfaced no other latent divergence — the campaign's empirical
   pipeline is at a clean broad point. Signal generation continues via
   filter extensions / Rust substrate, not divergence chasing on the
   *current* admit set.
2. **N1's shockland fix gate (round-62/63):** after N1's
   `apply_mana_produced_bridge` per-color fix lands, gate it with the
   **deterministic** `scout_r61_shockland_mana_divergence.py` bridge
   pin + a synthetic `activate_ability(dual,0/1)` cross-engine
   byte-equal probe. A full-game Sweep-A/B re-run is corroborating
   only — it flakes (this round's Batch-B rerun went green with the
   bug still present); do NOT treat a clean sweep re-run as proof the
   bug is fixed.
3. **The shockland surface stays NOT-yet-byte-equal-validated** until
   N1's fix lands + the deterministic pin is green; the round-61
   forward note stands.
4. **Timeout note**: 133/240 FAIL_TIMEOUT (creature-sparse bridged
   mirrors at max-turns=22 — the standing round-50/58 limitation,
   unchanged; not a regression). The §2-honest pool-delta levers
   (Phase 5 `each_player`, Phase 2 non-creature carriers) remain the
   route to creature-dense mirrors and deeper-turn signal.

## Round 64 (2026-05-16) — N3: post-r62-fix BROAD full-admitted-surface divergence sweep — clean broad validation; round-62 shockland fix CONFIRMED HELD (0 recurrence), 0 NEW divergence

Round-61 N3 found the 2-color shockland mana-ability bridge
divergence; round-62 N1 **fixed** it (rewrote
`apply_mana_produced_bridge` to emit one `is_mana_ability`
`ActivatedAbility` per produced color, matching Python — see the
`SEARCH_LIMITATIONS.md` "✅ CLOSED round-62 (N1)" block). Round-62 N3
ran the broad sweep concurrently with N1's fix still in flight and
classified the 6 surviving FAIL_DIVERGENCE as `known-r61-N1-owned`
(plus the new datum that the bench-level surfacing is
non-deterministic / order-dependent — gate on the deterministic pins,
not flaky sweeps). Round-64 N3 ran the **post-fix** broad sweep over
the full admitted surface to (a) confirm the round-62 fix held at
both the deterministic and bench levels and (b) surface any *other*
latent cross-engine divergence on the current admit set.

### Round-62 shockland fix — CONFIRMED HELD (the regression check)

Per the round-62 non-determinism datum, the **deterministic pins are
the authoritative gate** (a full-game sweep re-run flakes green even
with the bug present). All 11 round-62 N1 regression pins re-run on
the current `.pyd` → **11 passed**:

- `tests/test_parity_smoke.py::test_r62_shockland_activate_ability_per_color_byte_equal_both_engines`
  (parametrized over all 5 shocklands — drives `activate_ability` for
  each color index on both engines, asserts byte-equal pool + exactly
  the k-th single color)
- `tests/test_parity_smoke.py::test_r62_shockland_activate_idx0_no_spurious_second_color_rust`
- 5 × `tests/test_cross_engine_etb_triggers.py::test_r62_rust_bridge_*`
  (single-color unchanged / two-color one-per-color-in-order /
  order-follows-input / three-color / explicit-abilities)

The deterministic shockland bridge shape is now correct on BOTH
engines (Python idx0=`Add B`/idx1=`Add U`; Rust now emits the same
per-color shape — `scout_r61_shockland_mana_divergence.py`'s Python
side shows `idx0=AddManaToPool(('B',1))`, `idx1=AddManaToPool(('U',1))`;
that scout's `.pyd` introspection path is a no-op on this build but
the 11 cross-engine pins drive `activate_ability` on Rust directly
and assert byte-equality — they are the reliable gate). **The
round-61 divergence is GONE; this is a fix-held confirmation, not a
regression.**

### Scouted surface — the full admitted span (unchanged from r62)

`scripts/scout_r62_broad_admit_surface.py` re-walked the 17lands pool
in 10 evenly-spaced archetype-index windows (starts
`0,40,80,120,160,200,300,400,600,800`, 14 arches each), deep-loaded
each through the REAL production loader: **108 sweepable archetypes**
(idx 0–812) exercising the whole admitted surface — keyword `trample`
29 / `flying` 23 / `deathtouch` 19 / `defender` 8 / `vigilance` 6 /
`reach` 3; trigger `enters` 159 (78 arches) / `dies` 78 (64 arches) /
`becomes_tapped` 20 (20 arches); 22 dual-land (shockland) carriers;
21 vanilla creatures. Admit surface unchanged since r62 (no new
filter extensions landed between r62 and r64 on the bench path).

### Sweeps + full result counts (3 batches, ≤60 games each, HARD cap honored)

| Batch | Span / feature focus | Grid | Games | PASS | FAIL_DIV | TIMEOUT | EXC | FILTERED |
|---|---|---|---|---|---|---|---|---|
| A | low-index broad (vanilla + ETB/DIES + becomes_tapped + dual 46) | arch 0,1,2,3,5,9,10,11,12,40,46,49,52,86,88 ×s0-3 | 60 | 31 | **0** | 29 | 0 | 0 |
| B | mid-index dual-land + dies + becomes_tapped heavy (r61/r62 shockland carriers 122,123,124,125,130,131,132) | arch 122,123,124,125,130,131,132,160,165,167,200,201,203,204,205 ×s1-4 | 60 | 27 | **0** | 33 | 0 | 0 |
| C | high-index keyword-rich + dual + becomes_tapped, far from low carriers | arch 300,304,307,400,403,409,600,602,604,802,804,805,808,809,811 ×s2-5 | 60 | 17 | **0** | 43 | 0 | 0 |
| **Total** | full admitted surface, idx 0–811, 3 disjoint seed offsets | | **180** | **75** | **0** | **105** | **0** | **0** |

Plus a targeted **single-process re-run of the exact round-61/62
divergent shockland carriers** `arch 37,46,69,122,123,130 ×s0-1`
(12 games) → **0 FAIL_DIVERGENCE** (11 PASS / 1 TIMEOUT). These are
the precise (arch) that produced the r61/r62 FAIL_DIVERGENCE; they
now run byte-equal.

`attack_all`, max-turns 22, mulligans off. JSONs
`tmp/bench_broad_batch{A,B,C}.json` + `tmp/bench_broad_r6162_carriers.json`.
Every batch wall ≤~3 min, under the cap.

### Divergence triage — ZERO divergence across all 192 games

**0 FAIL_DIVERGENCE / 0 FAIL_EXCEPTION across all 180 broad-sweep
games + the 12 targeted r61/r62-carrier re-run games (192 total).**
Batch B and the targeted re-run both heavily exercise the exact
2-color shockland carriers that produced the round-61 (arch
37/46/69) and round-62 (arch 46/122/123/130) FAIL_DIVERGENCE — every
one now PASSes. No new divergence shape on any other admitted feature
class (vanilla, flying/trample/deathtouch/defender/vigilance/reach,
ETB/DIES/becomes_tapped triggers, basics+dual manabases).

### Verdict

| Claim | Verdict |
|---|---|
| Round-62 shockland fix held (0 recurrence of the r61 2-color mana-ability divergence) | **YES — CONFIRMED HELD.** 11/11 round-62 N1 deterministic regression pins green on the current `.pyd` (the authoritative gate per the r62 non-determinism datum). The exact r61/r62 divergent shockland carriers (arch 37/46/69/122/123/130) re-run byte-equal in a single process (0 FAIL_DIVERGENCE / 11 PASS / 1 TIMEOUT). Batch-B's 7 dual-land carriers (122–132) → 0 divergence. No flake observed in either direction (the r62 non-determinism was the *bug present*; with the fix the path is correct, so it is stable). |
| Broad full-admitted-surface sweep surfaces a NEW latent cross-engine divergence | **NO — CLEAN BROAD VALIDATION.** 180 broad games + 12 targeted across idx 0–811 / every admitted feature class. 0 NEW divergence shapes, 0 FAIL_DIVERGENCE, 0 FAIL_EXCEPTION. |
| Seedship Agrarian / becomes_tapped surface clean at broad scale | **VALIDATED CLEAN** — becomes_tapped carriers (5,40,46,50,53,86,122,123,130,171,200,205,…) across Batches A/B/C produced 0 becomes_tapped-specific divergence; the r58/r59 surface continues to hold. |

### Gate

Pure docs + 0 new scout scripts (reused `scout_r62_broad_admit_surface.py`
and `scout_r61_shockland_mana_divergence.py` verbatim — both already
committed) + 4 `tmp/bench_broad_*.json` artifacts (gitignored). **No
production / harness / `_SAFE_*` / bench-script / scout code changed**
— the bench and the 11 round-62 regression pins were run un-modified.
Parity gate **not** re-run (nothing in this slice is on its path;
baseline unchanged). No Rust → no `maturin`. Per the slice spec
(pure docs + bench JSON, no scout added) **no gate run is needed**.

### Forward picture for round 65

1. **The round-62 shockland fix is fully validated** — deterministic
   pins green + bench-level 0-recurrence across the precise divergent
   carriers + the broad span. The shockland surface's
   *activated-mana-ability* path is byte-equal-validated at scale; the
   `SEARCH_LIMITATIONS.md` CLOSED-round-62 block stands confirmed.
   (The pay-life / tapped-entry *replacement* drop remains the
   separate, symmetric shared CR-incompleteness deferred to the
   Phase-3 `enters_tapped` substrate — unchanged, not a divergence.)
2. **The broad admitted surface is byte-equal-validated** — 192 games
   across the full feature span, 0 latent divergence. The campaign's
   empirical pipeline is at a clean broad point on the *current*
   admit set. Recurring broad sweeps now have a diminishing latent-bug
   yield on the unchanged admit set; the highest-signal lever shifts
   to **running the sweep right after each new filter extension /
   Rust substrate lands** (a new code path is what surfaces the next
   real bug — the round-50/53/55/56/61 pattern) rather than re-sweeping
   the same surface.
3. **Recommended next bench item**: gate the *next* admit-widening or
   Rust-substrate slice with an immediate post-merge broad sweep over
   the newly-admitted carriers (the r61-style scoped sweep), then a
   broad re-sweep. Until a new admit lands, a periodic broad sweep is
   confirmation-only (this round) — keep cadence but expect clean.
4. **Timeout note**: 105/180 FAIL_TIMEOUT (creature-sparse bridged
   mirrors at max-turns=22 — the standing round-50/58 limitation,
   unchanged; not a regression). The §2-honest pool-delta levers
   (Phase 5 `each_player`, Phase 2 non-creature carriers) remain the
   route to creature-dense mirrors and deeper-turn signal.

## Round 65 (2026-05-16) — N3: FAIL_TIMEOUT creature-floor — quantified drag distribution + data-driven lever recommendation

The standing ~50% FAIL_TIMEOUT floor (r56/r58/r61/r62/r63: e.g. r62
133/240) is the campaign's single biggest **non-divergence signal
drag** — every timed-out game yields zero trajectory-divergence
signal. Root cause established r47/r50/r58 (the CardDef bridge-admit
filter collapses each 17lands archetype to ~1-2 admitted creature
copies + ~58 lands → near-creatureless mirror → never reaches lethal →
max-turns cap). This round **quantifies the drag precisely** with
per-game instrumentation the plain bench doesn't capture, evaluates the
candidate levers §2-honestly, and recommends the single best one.

`scripts/scout_r64_timeout_creature_floor.py` reuses the bench's exact
per-step primitives (byte-identical trajectory to a real
`bench_trajectory_parity.py` run) + the REAL production loader, and
instruments per-game: admitted creature copies (post-filter, pre-pad —
exactly what the bench plays), raw distinct creatures dropped from,
turns played, creatures cast, attack-eligible turns, and a timeout
cause classification. Artifact `tmp/scout_r64_timeout_floor.json`.

### Sweep — round-62 Batch-A broad-surface grid (HARD ≤3-min cap honored)

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
    scripts/scout_r64_timeout_creature_floor.py \
    --archetypes 0,1,2,3,4,5,7,8,9,10,11,12,13,40,42 --seeds 0-3 \
    --max-turns 22 --json-out tmp/scout_r64_timeout_floor.json
```

60 games, **~78s wall** (well under the 3-min cap). 0 FAIL_DIVERGENCE,
0 FAIL_EXCEPTION — clean run, the instrumentation does not perturb
parity.

### The quantified drag distribution

| Status | Count | % |
|---|---:|---:|
| PASS | 35 | 58.3% |
| **FAIL_TIMEOUT** | **25** | **41.7%** |
| FAIL_DIVERGENCE | 0 | 0% |
| ARCHETYPE_FILTERED | 0 | 0% |
| FAIL_EXCEPTION | 0 | 0% |

**Timeout cause split** (of the 25 FAIL_TIMEOUT — the new datum vs r47):

| Cause | Count | % of timeouts |
|---|---:|---:|
| `cast_but_stalled` (≥1 creature cast + attacked, too small/slow to close 20 by the cap) | **16** | **64%** |
| `never_cast_creature` (0 creatures ever cast — lone carrier buried in ~58 lands, never drawn castable) | **9** | **36%** |

This **inverts the round-47 split** (r47: 62% no-cast / 38%
under-powered). The r48/r50 admit expansions (Icetill Explorer,
Gravpack Monoist) raised the floor: more decks now cast *something*,
but it remains too weak/slow — confirming the lever is **more creature
copies of a closing body**, not "any creature at all".

**Admitted-creature-copy distribution (all 60 games):** 16 games at
**1 copy**, 20 at **2 copies**, 16 at **3 copies**, 8 at **5 copies**.
Every archetype with ≥5 admitted copies (arch 2,3 — Galactic Wayfarer
+ Icetill Explorer + Tapestry Warden) went **4/4 PASS, 0 timeout**;
every 1-copy archetype (7,8,9,42) timed out ≥50%. The
PASS↔copy-count correlation is monotone and stark.

### The collapse, measured across the full broad surface

A pool-wide walk (36 archetypes spanning the full r62 broad admitted
surface, idx 0–800) measured the raw→admitted creature-copy collapse
and classified every dropped copy by its first-failing admit gate:

| Metric | Value |
|---|---:|
| Raw creature copies (36 decks) | 489 |
| **Admitted today** | **93 (19.0%)** |
| Dropped: **`unsafe_trigger`** | **255 (52% of all raw copies)** |
| Dropped: `activated_ability` | 69 |
| Dropped: `warp_cost` | 23 |
| Dropped: other/mana | 21 |
| Dropped: `static_ability` | 11 |
| Dropped: `unsafe_keyword` | 9 |
| Dropped: `dynamic_pt` | 8 |

**Only 19% of raw creature copies survive the admit gate, and the
single dominant drop reason — by a 3.7× margin over the next — is
`unsafe_trigger`** (a triggered ability outside `_SAFE_TRIGGERS`).
This is the precise mechanism of the creature-floor: it is
overwhelmingly a **`_SAFE_TRIGGERS` allowlist** coverage gap (HANDOFF
workstream 2), NOT a keyword/cost/dynamic-P/T gap (those are long-tail).

### Lever evaluation (§2-honest)

The 255 `unsafe_trigger` copies were further classified by
`(event, predicate, effect)` shape, restricted to creatures whose
**sole** failing gate is the trigger (all other gates pass — i.e. a
single `_SAFE_TRIGGERS` entry would flip them). The distribution is a
**diffuse long tail**, not a single dominant unlock:

| Lever | +creature-copies | TIMEOUT→PASS conversion | §2 bridge-correctness cost | Verdict |
|---|---|---|---|---|
| **A. New `_SAFE_TRIGGERS` entry: `ENTERS/IsSelf/PumpTargetCreatureUEOT`** (top shape, Blooming Stinger) | ~20 ability-instances pool-wide (the single biggest shape) | low — ~1 copy/archetype on a few archetypes | **DECLINE**: effect requires an agent target-pick at PUSH time; the production-deck loader seats no agent → silent mistranslation (the exact `deal_damage`/target-pick decline already in the `_SAFE_TRIGGERS` docstring). Not §2-correct. |
| **B. Other top trigger shapes** (`EachOpponentDiscards`, `DealDamageAnyTarget`, `OptionalSacArtifactForEffect`, `SetBasePTConditionalUntilEOT`, the bespoke composites) | each ≤10 instances; ~80 total across ~15 distinct shapes | low individually; ~15 separate slices to drain | **DECLINE each**: every one needs either an unseated agent (discard/target-pick), a new Rust substrate (`CreateLanderAndScheduleSacrifice`, `SetBasePT*`, the EFFECT_UNCOVERED_TRIAGE Tier-A/C bespoke composites), or a non-§2 gate (`warp_cost`, `activated_abilities`). No single small §2-correct widen exists. |
| **C. Phase 1 `create_token` (Lander/Robot creature carriers)** — **already shipped** (r49/r50; `ENTERS/IsSelf/create_token` IS a safe trigger) | already in the 93 — Galactic Wayfarer 3/3, Beamsaw Prospector 2/1, Thawbringer, etc. | already counted (it's why Galactic Wayfarer is the most-admitted creature, 11/15 archetypes) | n/a — already done; this is *why* the floor isn't worse. The remaining Lander carriers (Edge Rover DIES, Kav Landseeker `CreateLanderAndScheduleSacrifice`) are blocked on **Phase 5 / new Rust substrate**, not a `_SAFE_TRIGGERS` widen. |
| **D. Phase 5 (`each_player`→Edge Rover)** | Edge Rover 2/2 + ~6 each-player Lander carriers | medium — adds a 2/2 body to the ~15-deck Edge-Rover-bearing slice | §2-correct *if* Phase 3 (Lander-token activated-ability sub-substrate) lands first — Edge Rover's token is Lander (non-vanilla); `each_player` arm + Rust variant exist (r43) but the loader recognizer + auto-registration + Lander-token-ability round-trip do not. **Multi-round** (Phase 3 ≥1 Rust round + Phase 5 ≥1 round). |
| **E. Phase 2 (non-creature Lander carriers)** | small — most non-creature carriers also make Lander (gated on Phase 3) | low until Phase 3 | §2-correct but **lower leverage than D and same Phase-3 prerequisite** (TOKEN_PRINTING_SUBSTRATE §Phase 2: "real-card delta still small until Phase 3"). |
| **F. EFFECT_UNCOVERED_TRIAGE Tier-A single-card Rust lane** (Diplomatic Relations, Orbital Plunge, Depressurize, Focus Fire, …) | each: 1 card → +copies on its carrier archetypes | each ~1 round, ~+1-2 copies/archetype on the carriers | §2-correct per-card (genuine real-EoE probe); but these are mostly **instants/sorceries** (removal/pump spells), NOT creature bodies — they help the *spell* signal, not the creature-floor directly. The creature-bearing Tier-C subgroup (28 cards, `nonsafe_triggered_ability`-co-gated) is a two-lever close. |
| **G. `--require-creatures N` bench precondition** (r47 option 2) | 0 (no coverage added) | 0 — reclassifies, doesn't convert | §2-neutral (harness-only). Correctly relabels the 36% `never_cast`-population as "filtered, no signal possible" so FAIL_TIMEOUT becomes a truer coverage metric — but it does NOT convert any timeout to PASS/DIV. A reporting honesty improvement, not a drag fix. |

### Recommendation (single best lever, data-driven conversion-per-effort)

**There is no cheap single-slice §2-correct unlock. The creature-floor
is a structural multi-round substrate cost, and the highest
conversion-per-effort lever is the TOKEN_PRINTING_SUBSTRATE Phase 3
(Lander-token activated-ability sub-substrate) → Phase 5
(`each_player`→Edge Rover) sequence — a minimum of 2 Rust rounds**
(Phase 3 ≥1 round + Phase 5 1 round; TOKEN_PRINTING_SUBSTRATE §5/§Phase
5). Rationale, data-driven:

- The drag is 52%-attributable to `unsafe_trigger`, and the trigger
  tail is **diffuse** (no shape >20 instances; ~15+ distinct shapes,
  most needing an unseated agent or new Rust substrate). No
  `_SAFE_TRIGGERS` one-liner converts a meaningful fraction — every
  near-miss shape (lever A/B) is a documented §2 decline (agent
  target-pick / new substrate / non-§2 gate). **The cheap lever does
  not exist; this is established with data, not deferred
  speculatively.**
- The **creature** carriers most likely to densify the mirror are the
  Lander/Robot family — and Phase 1's `create_token` safe trigger
  already admits the *vanilla-token, bare-ENTERS/DIES* members
  (Galactic Wayfarer, Beamsaw Prospector — confirmed: they ARE the
  dominant admitted creatures today, which is why the floor sits at
  ~42% not ~70%). The **remaining** high-deck Lander creature carriers
  (Edge Rover 15,271 decks; the `CreateLanderAndScheduleSacrifice`
  cluster) are blocked on Phase 3's Lander-token-activated-ability
  round-trip, then Phase 5's `each_player` recognizer — the
  TOKEN_PRINTING_SUBSTRATE-documented "largest single EoE-pool-delta
  lever in the whole substrate" (§Phase 3). That is the route that
  adds the most creature *bodies* per Rust round.
- Phase 2 (E) is §2-correct but lower-leverage and shares the Phase-3
  prerequisite. The Tier-A single-card lane (F) is the right parallel
  Rust lane for *spell* signal but does not directly densify the
  creature mirror. `--require-creatures N` (G) is a worthwhile
  **reporting-honesty** add (it would correctly classify the 36%
  `never_cast` population out of FAIL_TIMEOUT) but converts nothing.

**Exact realistic round-count:** Phase 3 (Lander-token activated-
ability sub-substrate: CardDef `token_activated_abilities` field +
Rust token-printing thread + `SearchLibraryForBasicLandTapped`
agent-seating verification) = **≥1 Rust round** (TOKEN_PRINTING_
SUBSTRATE §5 estimates it the largest substrate phase; budget 1-2).
Phase 5 (`each_player` loader recognizer + auto-registration arm; Rust
variant + bridge arm already exist from r43) = **1 Rust round**, gated
on Phase 3. Net **2-3 Rust rounds** for the Edge-Rover-class creature
densification. This is the cheapest *real* lever; it is multi-round,
stated with the number per the slice brief.

### §2-correct tweak this slice — DECIDED NOT MADE (not deferred speculatively)

Slice §3 permits a minimal §2-correct `_SAFE_*`/filter tweak THIS
slice if low-risk and in-scope. **Empirically answered NO, with data:**
every trigger shape on the near-miss creatures (the 255-copy
`unsafe_trigger` tail) is a standing bridge-correctness decline —
`PumpTargetCreatureUEOT`/`DealDamageAnyTarget`/`EachOpponentDiscards`
need an agent the production-deck loader does not seat (silent
mistranslation — the exact decline already enumerated in the
`_SAFE_TRIGGERS` docstring); the Lander/composite shapes
(`CreateLanderAndScheduleSacrifice`, `SetBasePTConditionalUntilEOT`,
Tier-A composites) need NEW Rust substrate, not an allowlist edit.
Admitting any of them via a bare `_SAFE_TRIGGERS` widen would ship the
round-38-E5 count-chasing anti-pattern §2 exists to prevent. **No
tweak made — the precise required unlock (Phase 3→5, 2-3 Rust rounds)
is specified above; declining the unbridged shapes is the §2-correct
outcome.**

### Recommended next bench item

**`--require-creatures N` reporting-honesty harness add** (r47 option
2, lever G), a contained ~1 Python slice: a bench precondition that
marks an (archetype, seed) game `ARCHETYPE_FILTERED` instead of
`FAIL_TIMEOUT` when the post-filter deck carries `< N` admitted
creature copies (N≈3 from this round's data — the 1-copy archetypes
are the structural never-converters). It adds **zero coverage** but
makes the headline FAIL_TIMEOUT % a *truer* signal-coverage metric by
separating the ~36% structural-no-creature population from genuine
long-stalls — directly actionable for tracking the Phase-3/5
substrate's conversion effect when it lands. It is §2-neutral
(harness-only, no admit-set change), bounded, and the only
*single-slice* item this analysis surfaces. (The substrate levers D/E
and the Tier-A lane F are Rust-lane multi-round work, correctly
out-of-scope for a bench/docs slice.)

### Gate

Pure docs + 1 `scripts/scout_*.py` diagnostic
(`scout_r64_timeout_creature_floor.py`, read-only — reuses the bench's
own primitives, modifies no production/`_SAFE_*`/bench-script code) +
1 `tmp/scout_r64_timeout_floor.json` artifact. **No production /
harness / `_SAFE_*` / bench-script code changed.** Parity gate **not**
re-run; nothing in this slice is on its path (baseline **1397**
unchanged). No Rust → no `maturin`.
