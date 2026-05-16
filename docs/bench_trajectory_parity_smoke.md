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
