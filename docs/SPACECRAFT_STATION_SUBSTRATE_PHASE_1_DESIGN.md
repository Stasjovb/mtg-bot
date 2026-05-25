Generated 2026-05-25 (post `cost-reduction-phase-3-cycle-3-fungal-
probe-p1`, merge `456108df`; parallel-with `carrier-aa-substrate-
phase-1-design-p1`). **Design only — NO production / `_SAFE_*` /
Rust change in this slice; no gate run beyond the 31/31
`tests/test_measure_pool_parity.py` baseline** (docs + read-only
scout against the live tree). This doc scopes the **Spacecraft
Station** substrate as a multi-cycle CAMPAIGN per the
2026-05-25 saturation report's #2 DEFERRED row (after Carrier-AA),
in the gold-standard format of
`docs/COST_REDUCTION_SUBSTRATE_PHASE_1_DESIGN.md` and
`docs/CARRIER_AA_SUBSTRATE_PHASE_1_DESIGN.md`. Every file:line
below is verified against the live tree at main `456108df`.

> **Relationship to `docs/COVERED_BY_CONSTRUCTION_PROBE_WRITING_SATURATION_2026-05-25.md`.**
> That doc closes the bare-bridge-clean Effect-class probe-writing
> lane after 13 batches and identifies the BLOCKED-SG subsystem
> table as the post-saturation pivot frontier. Spacecraft Station
> is the **#2 row by aggregate deck count** (8 cards /
> ~41,281 17lands decks cumulative) — strictly behind Carrier-AA's
> 30 / 34,470 only in card count, ahead in per-card density (5,160
> avg decks/card vs Carrier-AA's 1,149). It is the
> "second-highest-leverage DEFERRED lane" recommended for parallel
> scoping with the Carrier-AA campaign (this lane and Worker B's
> Carrier-AA Phase 1 C1 do not collide — different code regions).
>
> **Relationship to the 2026-05-24 tractability rescout**
> (`docs/MULTI_GATED_TAIL_TRACTABILITY_RESCOUT_2026-05-24.md`).
> The rescout's #5 carrier-of-interest was Lumen-Class Frigate
> ("~70% of one cycle off MTL Phase-4 PowerToughnessBonus reader
> fold + bridge"), which it explicitly flagged as
> blocked-behind-Spacecraft-substrate (`tier_threshold=2,
> station_threshold=12`). Phase 1 of this campaign UNBLOCKS
> Lumen-Class Frigate at the Spacecraft-substrate axis (Phase 2
> closes the Lumen-Class Frigate single carrier when the
> static-anthem PowerToughnessBonus reader + tier_threshold-gated
> static cycle lands).
>
> **Relationship to the partial Rust scaffolding already shipped.**
> Rust's `GameObject.charge_counters: i32`
> (`rust/src/state.rs:63`) and `ActivatedAbility.tier_threshold: i32`
> (`rust/src/cards.rs:10022`) are the "CE20 follow-up Slice 3"
> Spacecraft scaffolding that landed pre-Phase-1 to support
> targeted charge-counter Effect resolvers (e.g.,
> `Effect::PutChargeCountersOnTargetSpacecraftOrPlanetYouControl`
> at `rust/src/cards.rs:6711`) and `tier_threshold`-gated AA
> legality
> (`rust/src/state_ops_legal.rs:3328` +
> `rust/src/state_ops_actions.rs:996`). What is **NOT yet
> shipped** Rust-side: the Station ACTION itself (the
> `ActivateStation` decision, `_activate_station` resolver, +
> derived charge-counter-bump from crew power), the
> `station_threshold` / `stationed_keywords` printing fields,
> the type-line creature-flip and keyword-grant when stationed,
> and the bridge round-trip for any of these. Phase 1 lands those
> Rust pieces, on the narrowest possible carrier (Galvanizing
> Sawship).

# Spacecraft Station substrate Phase 1 — campaign scoping doc (sub-shape A: bare zero-ability Spacecraft carrier — pilot `Galvanizing Sawship`)

## 0. Executive summary

The **Spacecraft Station** subsystem at live HEAD `456108df` binds
**8 cards / ~41,281 17lands decks cumulative** (per
`docs/POOL_PARITY.md`'s BLOCKED-SG breakout table at line 448 +
`docs/SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY.md` §2 line 1042 +
2026-05-25 saturation report headline). Of those 8, **only
Galvanizing Sawship is single-gated** (5,938 17lands decks;
`docs/SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY.md` line 192,
attribution-snapshot table). The other 7 carry one or more
co-gates (verified by `scripts/scout_r58_subsystem_attribution.py`
run against live HEAD; per-card breakdown in §2 below).

This doc scopes the substrate's **Phase 1**: admit ONLY the
narrowest sub-shape A — **bare zero-ability Spacecraft carriers
with `station_threshold` set, NO static / triggered / activated
abilities, NO co-gates, NO riders other than the Station mechanic
itself**. The pilot is **Galvanizing Sawship** (5,938 17lands
decks — 14.4 % of the subsystem-cumulative 41,281, the largest
self-contained single-card slice and the ONLY single-gated card
in the row).

Phase 1 explicitly **defers**: Lumen-Class Frigate (Phase 2 —
static anthem co-gate, `tier_threshold=2`); the five
triggered-ability carriers Larval Scoutlander, Sledge-Class
Seedship, Synthesizer Labship, Entropic Battlecruiser, Infinite
Guideline Station (Phase 3 — each blocked behind a distinct
`effect_uncovered` Effect class AND
`nonsafe_triggered_ability` event-shape co-gate); and The
Eternity Elevator (Phase 4 — `tier_threshold=20`-gated AA on
a non-station Spacecraft, also `carrier_activated_abilities`
co-gated). Sub-shape A's 1-cycle-feasible reach is **exactly
Galvanizing Sawship** because every other Spacecraft in the
pool carries at least one additional ability shape Rust does
not yet handle.

Estimated campaign scope (calibrated against the cost-reduction
campaign at `docs/COST_REDUCTION_SUBSTRATE_PHASE_1_DESIGN.md` §1.3:
~10 cycles across Phase 1 / 2 / 3 to close 5 cards / 53,648 decks,
which actually shipped 2026-05-23..2026-05-25 in roughly that
budget): **Spacecraft Station Phase 1 = ~6 cycles** for the
substrate landing + Galvanizing Sawship probe; **campaign total
~16-22 cycles across Phase 1 / 2 / 3 / 4** to close the 8-card /
41,281-deck row, comparable to (slightly larger than) the
cost-reduction campaign because the Spacecraft substrate carries
a NEW player-decision (ActivateStation) the cost-reduction
substrate does not, AND each Phase-3 carrier closes a distinct
Effect class.

## 1. Background — why this substrate, why now

### 1.1 Saturation context

`docs/COVERED_BY_CONSTRUCTION_PROBE_WRITING_SATURATION_2026-05-25.md`
documents the conclusion of the bare-bridge-clean Effect-class
probe-writing lane (batches 1-13, 2026-05-24 → 2026-05-25, +62
PROBED) and identifies the BLOCKED-SG subsystem breakout table
as the post-saturation pivot frontier. Spacecraft Station ranks
**#2 by aggregate deck count** (8 / 41,281) after Carrier-AA
(30 / 34,470). The recommendation explicitly names Carrier-AA as
the #1 lane to scope; Spacecraft Station is the natural #2
parallel lane because:

* The two substrates touch **disjoint Rust regions**: Carrier-AA
  widens the activated-ability admit gate on non-token
  CardPrintings + adds bridge round-trip for a non-token AA list;
  Spacecraft Station adds the Station decision +
  `station_threshold` printing field + crewed-creature-flip layer.
  No file-level overlap, so the two scope docs and the two C1
  Rust slices can land in parallel (this lane scopes; Worker B's
  Carrier-AA Phase 1 C1 implements).
* Spacecraft has **higher per-card deck density** than Carrier-AA
  (5,160 vs 1,149 avg decks/card), so even Phase 1's 1-card
  pilot unlocks meaningful leverage (5,938 decks for Galvanizing
  Sawship alone — comparable to Cosmogoyf's round-84 closure at
  similar deck-leverage scale).
* The 2026-05-24 tractability rescout
  (`docs/MULTI_GATED_TAIL_TRACTABILITY_RESCOUT_2026-05-24.md` #5
  Lumen-Class Frigate finding) put the Spacecraft substrate
  directly on the path of the next-tractable static-anthem
  closure: Lumen-Class Frigate is ~70 % of one cycle off
  PowerToughnessBonus reader + bridge, BUT blocked behind the
  Spacecraft substrate at `tier_threshold=2, station_threshold=12`.
  Phase 1 of this campaign opens the substrate; Phase 2 lands
  Lumen-Class Frigate end-to-end. Without this campaign,
  Lumen-Class Frigate stays DEFERRED.

### 1.2 Why the substrate scope is large

Per a live walk of the 8 BLOCKED-SG members (§2 table), the
substrate requires the following components, each touching
production code paths:

1. **CardPrinting `station_threshold` + `stationed_keywords`
   field** — the Rust mirror of Python's
   `CardPrinting.station_threshold: int | None`
   (`src/mtg_bot/cards/base.py:564`) and
   `CardPrinting.stationed_keywords: frozenset[str]`
   (`src/mtg_bot/cards/base.py:565`). The Python field encodes
   "this is a Spacecraft, animates as a creature when
   `charge_counters >= station_threshold`, and at that point
   gains these keywords." `station_threshold=None` produces a
   Spacecraft that never animates (The Eternity Elevator —
   Phase 4 only).
2. **`Effect::ActivateStation`-style action + Rust resolver +
   legal-action emitter** — the Rust analogue of Python's
   `ActivateStation` action (`src/mtg_bot/actions.py:144`),
   `_activate_station` resolver (`src/mtg_bot/actions.py:2353`),
   and `legal_actions` station enumeration
   (`src/mtg_bot/legal.py:831`). The decision is
   **sorcery-speed-only** (current Python at `legal.py:838`),
   targets a Spacecraft the controller controls + a crew creature
   (untapped, not summoning-sick, not the Spacecraft itself, not
   itself a Spacecraft), taps the crew, adds
   `effective_power(crew)` charge counters to the Spacecraft.
   This is a wholly new action class for the Rust side.
3. **Stationed-creature flip + keyword grant in the layered
   pipeline** — the Rust analogue of Python's
   `is_stationed`/`is_creature_now` helpers
   (`src/mtg_bot/game.py:825,831`) and the `stationed_keywords`
   layer-6 fold (`src/mtg_bot/game.py:1167,1193`). When
   `obj.charge_counters >= obj.printing.station_threshold`, the
   Spacecraft "is a creature" for SBA / combat / activated-mana-
   ability-gating purposes, with the printed P/T showing through
   and the `stationed_keywords` set merged into effective
   keywords. Rust's layered fold lives in `state_ops_combat.rs`
   et al; this is the largest single piece of new Rust.
4. **Bidirectional bridge round-trip** —
   `build_rust_state.printing_dict` emit on the Python side;
   `_card_def_to_python_printing` reconstruction;
   `_printing_to_card_def` arm for `station_threshold` /
   `stationed_keywords`; `_filter_deck_to_bridge_supported`
   admit predicate
   (`_printing_is_bridge_pure_station_spacecraft`). Today the
   bridge has **zero translation for `station_threshold` or
   `stationed_keywords`** (confirmed by `grep` on
   `cross_engine.py` — no matches outside the existing
   targeted-Effect `PutChargeCountersOnTargetSpacecraftOrPlanet
   YouControl` arm, which never produces a Station decision and
   does not read the printing's `station_threshold`).

Component (3) is the campaign-wide §2 reason Spacecraft Station
+ Carrier-AA + Static-layered are all named §2-DEFERRED in the
inventory: conditional/layered/stateful evaluation. Phase 1
ports it minimally (P/T + keyword fold only when stationed; no
multi-Spacecraft compositional interactions, no condition
combinators); subsequent phases grow the fold incrementally.

### 1.3 Calibration against cost-reduction + Carrier-AA

The cost-reduction campaign (`docs/COST_REDUCTION_SUBSTRATE_PHASE_
1_DESIGN.md` Phase 1/2/3) shipped in ~10 rounds 2026-05-23..2026-
05-25 to close 5 cards / 53,648 decks; Carrier-AA's parallel-
authored doc estimates ~12-18 cycles for 30 cards / 34,470 decks.
Spacecraft Station is **comparable to or smaller** in Phase 1
scope:

- Spacecraft Phase 1 ships ONE pilot card (vs cost-reduction's
  pair) and lands a NEW player-decision (ActivateStation) that
  cost-reduction did not. Cost-reduction needed NO new action;
  Spacecraft needs ActivateStation + a per-state legal-action
  emitter on the Rust side.
- Spacecraft Phase 1's "creature-flip" layer mirrors the
  cost-reduction `Condition` grammar's complexity ceiling
  (single carrier, no composition), but lives in the **layered
  fold** rather than the cast-cost evaluator — a different
  Rust subsystem that already carries the `BecomeType`
  precedent
  (`Effect::BecomeLandCreatureUntilEOT` was the round-58
  precedent) but does NOT yet carry a CONDITIONAL flip (the
  Spacecraft is a creature ONLY WHEN
  `charge_counters >= threshold` — a runtime predicate over
  per-object state, not a UEOT layer entry).
- Spacecraft Phase 1 has a SMALLER bridge surface than
  cost-reduction (2 printing fields + 1 action vs the
  Condition-grammar tuple-of-triples) but a LARGER state-
  evaluation surface (every legal-action / SBA / combat pass
  that reads `is_creature` must consult `is_stationed`).

The campaign-total estimate is **~16-22 cycles across Phase 1 /
2 / 3 / 4**:

  - Phase 1 (Galvanizing Sawship, ~6 cycles): substrate landing
    (1-2) + admit + Python-side ActivateStation parity (1-2) +
    per-card real-EoE probe across the un-stationed / stationed-
    one-counter / stationed-at-threshold scenarios (2).
  - Phase 2 (Lumen-Class Frigate, ~2-3 cycles): static-anthem
    PowerToughnessBonus reader fold + `tier_threshold=2` gate
    + per-card real-EoE probe.
  - Phase 3 (5 triggered-ability carriers, ~6-10 cycles): 5
    distinct Effect-class Rust slices
    (`EachOpponentDiscardsOrLosesLife`,
    `OptionalSacLandOrLanderForBasicLandRamp`,
    `OptionalPutCreatureFromHandOntoBattlefield`,
    `TargetArtifactBecomesCreatureUEOT`,
    `CreateTokenPerMulticoloredPermanent` +
    `DrawCardPerMulticoloredPermanent` for the same carrier)
    + the `tier_threshold`-gated trigger-firing predicate
    (Synthesizer Labship's `tier_threshold=2`, Entropic
    Battlecruiser's mode-1 `tier_threshold=1`).
  - Phase 4 (The Eternity Elevator, ~2 cycles): `tier_threshold=
    20`-gated AA bridge admit + the `AddChargeCounterMana
    OfChosenColor` Effect class (a SECOND new Effect class on
    the same carrier — also `station_threshold=None`, the only
    non-animating Spacecraft).

## 2. Sub-shape A scope — exactly 1 card, the zero-ability Spacecraft carrier

Verified live against `OracleParserCardSource().get_printings()`
at main `456108df` (per the §1 scout run + the per-card audit
below):

| Card | `station_threshold` | `stationed_keywords` | mana_cost | P/T | 17lands decks | other shapes | Phase |
|---|---:|---|---|---|---:|---|---|
| **Galvanizing Sawship** | 3 | `{flying, haste}` | `{5}{R}` | 6/5 | 5,938 | NONE | **1** |
| Lumen-Class Frigate | 12 | `{flying, lifelink}` | `{1}{W}` | 3/5 | * | static-anthem `+1/+1` to other creatures at `tier_threshold=2` | 2 |
| Larval Scoutlander | 7 | `{flying}` | `{2}{G}` | 3/3 | * | trig `OptionalSacLandOrLanderForBasicLandRamp` | 3 |
| Sledge-Class Seedship | 7 | `{flying}` | `{2}{G}` | 4/5 | * | trig `OptionalPutCreatureFromHandOntoBattlefield` | 3 |
| Synthesizer Labship | 9 | `{flying, vigilance}` | `{U}` | 4/4 | * | trig `TargetArtifactBecomesCreatureUEOT` at `tier_threshold=2` | 3 |
| Entropic Battlecruiser | 8 | `{deathtouch, flying}` | `{3}{B}` | 3/10 | * | trig `EachOpponentDiscardsOrLosesLife` (tier=0) + `TargetPlayerLosesLife` (tier=1) | 3 |
| Infinite Guideline Station | 12 | `{flying}` | `{W}{U}{B}{R}{G}` | 7/15 | * | trig `CreateTokenPerMulticoloredPermanent` + `DrawCardPerMulticoloredPermanent` | 3 |
| The Eternity Elevator | **None** | `{}` | `{5}` | 0/0 | * | AA `AddManaToPool` (tier=0) + AA `AddChargeCounterManaOfChosenColor` (tier=20) | 4 |

*\*: The 7 multi-gated carriers' individual 17lands deck counts
sum to ~35,343 (= 41,281 − 5,938); per-card sub-totals are not
load-bearing for Phase 1 sequencing.*

**Phase-1 deck total: 5,938 17lands decks** (Galvanizing Sawship
alone). The single card carries 14.4 % of the subsystem's
cumulative deck count.

**Why Galvanizing Sawship is the only sub-shape A carrier.** Per
the live print walk, ZERO other Spacecraft has empty
`static_abilities + triggered_abilities + activated_abilities`.
Every other Spacecraft pulls in at LEAST one of:

* a co-gate-attributed Effect class
  (`effect_uncovered: True` per the subsystem attribution
  scout — verified for Entropic / Infinite Guideline /
  Larval / Sledge / Synthesizer / The Eternity Elevator);
* a static-anthem layer-7 PowerToughnessBonus rider
  (Lumen-Class Frigate; co-gate `static_abilities_layered`);
* a `tier_threshold` >0 ability that gates on
  `charge_counters` (Synthesizer Labship's trigger
  `tier_threshold=2`; Entropic Battlecruiser's mode-1
  `tier_threshold=1`; The Eternity Elevator's AA
  `tier_threshold=20`; Lumen-Class Frigate's static
  `tier_threshold=2`). Phase 1 does NOT model
  `tier_threshold`-gated triggered/static abilities at all;
  the trigger / static must FIRE conditionally on
  `charge_counters >= tier_threshold`, which is a layered fold
  precondition Phase 1 explicitly defers.

Galvanizing Sawship's "all empty" ability lists, combined with
its single-gated attribution (the only Spacecraft for which
`scout_r58_subsystem_attribution.py` reports `'gates':
['station_spacecraft'], 'multi_gated': False`), makes it the
narrowest 1-cycle-feasible carrier in the row.

Sub-shape A's positive criteria, all verified for Galvanizing
Sawship at live HEAD:

- The printing carries `station_threshold` set to a positive
  int + `stationed_keywords` non-empty (verified:
  `printings['Galvanizing Sawship'].station_threshold == 3`,
  `stationed_keywords == frozenset({'flying', 'haste'})`).
- `static_abilities == ()` AND `triggered_abilities == ()` AND
  `activated_abilities == ()` (verified by direct walk in §1).
- `spell_effect is None`, no `room_halves`, no `loyalty`, no
  `dynamic_pt_formula`, no `ward_cost`, no `cost_reductions`,
  no `external_cost_reductions`, no `warp_cost`, no
  `kicker_cost`, no `impending_cost`, no `keywords` baseline
  (the keywords come ONLY via `stationed_keywords`, which is
  the layered fold Phase 1 lands).
- Both `stationed_keywords` (`flying`, `haste`) are in
  `trajectory.py::_SAFE_KEYWORDS` — the Rust layered fold
  must grant exactly those keywords when stationed, and both
  are already first-class in the Rust combat / priority
  machinery (no new keyword Effect needed).

The ONLY blocking features on Galvanizing Sawship are the
`station_threshold` + `stationed_keywords` + Spacecraft
subtype fields and the absent ActivateStation action. Strip
them and the card is a vanilla 6/5 {5}{R} Artifact with no
abilities — already bridge-clean. Restore them and the
substrate must land.

## 3. Out-of-scope (deferred to Phase 2+)

The following are explicitly **NOT** in Phase 1's scope. The
Phase-1 filter guardrail
(`_printing_is_bridge_pure_station_spacecraft`, §6) positively
rejects each so they cannot reach the Phase-1 ActivateStation
path:

### 3.1 Static-ability Spacecraft carriers — Phase 2 (Lumen-Class Frigate)

Lumen-Class Frigate carries one `StaticAbility(scope=
other_creatures_you_control,
continuous_effect=ContinuousModifier(layer=7,
payload=PowerToughnessBonus(power_bonus=1, toughness_bonus=1)),
tier_threshold=2)` — i.e. "Other creatures you control get
+1/+1 while this Spacecraft has 2 or more charge counters."

Phase 2 requires:

- the static-anthem PowerToughnessBonus reader fold (the
  rescout's "70 % of one cycle off" pin — sits on top of MTL
  Phase-4 reader machinery);
- the `tier_threshold`-gated static predicate (the static
  fires only while `charge_counters >= tier_threshold`, which
  is a new layered-fold input Phase 1 explicitly defers).

5,938-deck count if attribution stays at the Spacecraft gate
when Phase 2 closes; multi-gated, so leverage is realized
**only** when both substrates land.

### 3.2 Triggered-ability Spacecraft carriers — Phase 3 (5 cards)

Each of Larval Scoutlander, Sledge-Class Seedship, Synthesizer
Labship, Entropic Battlecruiser, and Infinite Guideline Station
carries a triggered ability whose Effect class has no Rust
counterpart today (subsystem attribution: `effect_uncovered:
True` and `missing_effect_classes` populated). The Effect
classes that must land Rust-side, one per carrier:

- Larval Scoutlander → `OptionalSacLandOrLanderForBasicLandRamp`
- Sledge-Class Seedship → `OptionalPutCreatureFromHandOntoBattlefield`
- Synthesizer Labship → `TargetArtifactBecomesCreatureUEOT` (at
  `tier_threshold=2`)
- Entropic Battlecruiser → `EachOpponentDiscardsOrLosesLife`
  (tier=0) + `TargetPlayerLosesLife` (tier=1)
- Infinite Guideline Station → `CreateTokenPerMulticoloredPermanent`
  + `DrawCardPerMulticoloredPermanent`

Two of these (Synthesizer Labship's trigger; Entropic
Battlecruiser's mode-1) also require the
`tier_threshold`-gated trigger-firing predicate (the trigger
goes on the stack ONLY when `charge_counters >= tier_threshold`
at trigger-condition-check time, CR 603.4-style). That
sub-substrate is the same one Phase 2 lands for static
abilities; Phase 3's Synthesizer / Entropic carriers can
ride the Phase-2 substrate.

Each card is its own ~1-2 cycle slice (Effect class + bridge
arm + per-card real-EoE probe). Phase 3 also depends on
`nonsafe_triggered_ability` event-shape closures for each
trigger's `Event::ENTERS` / phase-transition shape — most
already covered by the existing Rust trigger dispatch
infrastructure, but each needs verification.

### 3.3 Activated-ability Spacecraft carriers — Phase 4 (The Eternity Elevator)

The Eternity Elevator is the **only Spacecraft with
`station_threshold=None`** (it never animates) and **the only
Spacecraft whose binding shape is an activated ability**. It
carries:

- AA `AddManaToPool` at `tier_threshold=0` (already bridge-
  clean Effect class — covered_by_construction precedent);
- AA `AddChargeCounterManaOfChosenColor` at
  `tier_threshold=20` (new Effect class — adds a charge
  counter to a permanent the player controls, which itself
  composes with the Spacecraft substrate if the target is a
  Spacecraft).

Phase 4 also depends on the Carrier-AA non-token
`activated_abilities` bridge round-trip (Worker B's parallel
campaign Phase 1+). Sequencing: after Carrier-AA Phase 1 + 2
land the non-token-AA admit predicate, Phase 4 here can
extend it for The Eternity Elevator with the new charge-
counter mana Effect class. The Eternity Elevator is also
attributed `carrier_activated_abilities` co-gate, confirming
this sequencing.

### 3.4 Multi-Spacecraft compositional interactions — out of substrate

The `grants_toughness_as_station_power_for_creatures_you_
control` flag on Tapestry Warden
(`src/mtg_bot/cards/base.py:944-950`) lets a stationed
creature use TOUGHNESS instead of POWER when adding charge
counters — a battlefield-scoped read of OTHER permanents
during ActivateStation cost-payment. Tapestry Warden is NOT
itself a Spacecraft and is NOT in the BLOCKED-SG 8-card row;
it is a co-mechanic the substrate must NOT silently mis-model.
Phase 1's `_activate_station` analogue ignores this flag (the
existing Python code at `actions.py:2393-2401` reads it on
every Station; Rust Phase 1 omits the read because no
Tapestry-Warden-style printing is in the Phase-1 admitted
set). The SL §9 entry pins this asymmetry; Phase 2+ admits
must NOT bring a Tapestry-Warden carrier into scope until
the read lands Rust-side.

### 3.5 Planets-with-Station — out of substrate

Per `src/mtg_bot/cards/base.py:1771` "Planets with Station
are functionally a non-creature Spacecraft", but no
BLOCKED-SG Planet currently carries a Station mechanic in
the EoE snapshot (the 5 Planet lands closed round-85 via
`_printing_is_bridge_simple_tapped_mana_land`). Phase 1 does
not need to address Planet-Station composition. Future
sets / DLCs may; flag as a sub-shape A* extension when /
if a Station-bearing Planet enters the pool.

## 4. Rust-side spec — the new fields, action, and resolver hooks

### 4.1 New `CardPrinting.station_threshold: Option<i32>` field

**File:** `rust/src/cards.rs`. Add to `CardPrinting` (struct
declared near `cards.rs:9713`, last field `pub starting_loyalty:
i32` at `cards.rs:9885` — verify-first walk pin: cost-reduction
Phase 1 appends `cost_reductions: Vec<CostReduction>` here, so
Station appends AFTER that):

```rust
    /// **Spacecraft Station substrate Phase 1.** Spacecraft
    /// printings carry this threshold (positive `i32`) and
    /// animate as artifact creatures when `obj.charge_counters
    /// >= station_threshold`. `None` (Rust: `Option::None`) =
    /// non-animating (The Eternity Elevator — Phase 4 only) or
    /// non-Spacecraft (every non-Spacecraft printing — back-
    /// compat default; parser maps a missing key to `None`).
    /// Mirrors Python's `CardPrinting.station_threshold: int |
    /// None` at `src/mtg_bot/cards/base.py:564`.
    pub station_threshold: Option<i32>,
    /// **Spacecraft Station substrate Phase 1.** Set of keyword
    /// strings the Spacecraft gains while stationed (`obj.
    /// charge_counters >= station_threshold`). Empty `Vec` = no
    /// extra keywords (the back-compat default — every pre-
    /// Phase-1 registry dict omits this key; parser maps to
    /// `Vec::new()`). Layered fold at the effective-keyword
    /// reader site (`state_ops_combat.rs::effective_keywords_for`
    /// or equivalent — verify-first walk pin: cost-reduction
    /// Phase 1 did not touch this path). Mirrors Python's
    /// `CardPrinting.stationed_keywords: frozenset[str]` at
    /// `src/mtg_bot/cards/base.py:565` + the layer-6 fold at
    /// `src/mtg_bot/game.py:1191-1193`.
    pub stationed_keywords: Vec<String>,
```

### 4.2 New `Action::ActivateStation` decision variant

**File:** `rust/src/actions.rs`. Add a new `Action` variant
mirroring Python's
`ActivateStation(spacecraft_id: int, crew_id: int)` dataclass
at `src/mtg_bot/actions.py:144-154`:

```rust
/// **Spacecraft Station substrate Phase 1.** Activate the
/// Station ability of a Spacecraft. Cost: tap `crew_id`
/// (another untapped, non-summoning-sick creature the player
/// controls). Effect: add charge counters to `spacecraft_id`
/// equal to the crew's effective power. Sorcery-speed only
/// (enforced by the legal-action emitter, mirroring Python's
/// `legal.py:831-852`). Mirrors Python's `ActivateStation`
/// dataclass at `src/mtg_bot/actions.py:144`.
ActivateStation {
    spacecraft_id: u32,
    crew_id: u32,
},
```

### 4.3 New legal-action emitter — sorcery-speed Station enumeration

**File:** `rust/src/state_ops_legal.rs`. Insert a new
emit-loop at the end of the priority-window legal-action
pass (mirroring Python's `legal.py:831-852` shape):

```rust
// **Spacecraft Station substrate Phase 1.** For each Spacecraft
// this player controls, emit (spacecraft_id, crew_id) pairs
// for every untapped non-summoning-sick creature they control
// (excluding the Spacecraft itself). Sorcery-speed only —
// gate on the same predicate as other special actions.
if is_sorcery_speed_legal_for(state, player_id) {
    let ships: Vec<&GameObject> = state.battlefield.iter()
        .filter(|o| o.controller == player_id
                  && is_spacecraft(o))
        .collect();
    if !ships.is_empty() {
        for ship in &ships {
            for crew in state.battlefield.iter() {
                if crew.controller != player_id { continue; }
                if !is_creature_now(crew) { continue; }
                if crew.tapped { continue; }
                if crew.summoning_sick { continue; }
                if crew.id == ship.id { continue; }
                actions.push(Action::ActivateStation {
                    spacecraft_id: ship.id,
                    crew_id: crew.id,
                });
            }
        }
    }
}
```

The `is_spacecraft(o)` predicate reads
`o.printing.subtypes.contains("Spacecraft")` (Phase 1 follows
the existing
`Effect::PutChargeCountersOnTargetSpacecraftOrPlanetYouControl`
filter precedent at `rust/src/state_ops_resolve.rs:1586-1594`,
which already iterates printings' `subtypes` for the
multi-type predicate).

### 4.4 New `apply_activate_station` resolver

**File:** `rust/src/state_ops_actions.rs` (mirrors the
`apply_ability_activation` site at `:996` that ALREADY reads
`obj.charge_counters < resolved.tier_threshold` — the Station
action lives in the same module as the ability-activation
machinery):

```rust
/// **Spacecraft Station substrate Phase 1.** Validate + apply
/// a Station activation. Silently no-ops on invalid inputs
/// (crew tapped / sick / same object / wrong-controller —
/// mirrors Python's `_activate_station` silent-validate
/// pattern at `src/mtg_bot/actions.py:2353-2407`).
///
/// Phase 1 does NOT honor the
/// `grants_toughness_as_station_power_for_creatures_you_control`
/// flag (Tapestry Warden's flag — Python at `actions.py:2393-
/// 2401` consults it). Phase 1 admits no Tapestry-Warden-
/// shape printing, so this asymmetry is bench-invisible; SL
/// §9 entry pins it as a Phase-2+ widen.
fn apply_activate_station(
    state: &mut GameState,
    player_id: u8,
    spacecraft_id: u32,
    crew_id: u32,
) -> () { /* ... validation chain + tap crew + add power-many
            charge counters to spacecraft. Mirrors Python
            exactly. */ }
```

### 4.5 New `is_stationed` / `is_creature_now` layered-fold helpers

**File:** `rust/src/state_ops_combat.rs` (or
`state_ops_layered.rs` — verify-first walk pin: confirm where
the existing `is_creature(obj)` predicate lives for SBA /
combat reads):

```rust
/// **Spacecraft Station substrate Phase 1.** True iff
/// `obj.printing.station_threshold.is_some() && obj.charge_
/// counters >= station_threshold`. Mirrors Python's
/// `is_stationed` at `src/mtg_bot/game.py:825-828`.
pub fn is_stationed(obj: &GameObject) -> bool {
    match obj.printing.station_threshold {
        Some(t) => obj.charge_counters >= t,
        None => false,
    }
}

/// **Spacecraft Station substrate Phase 1.** Extension of the
/// existing `is_creature` predicate to handle stationed
/// Spacecraft. Replaces every call site that reads `obj.
/// printing.is_creature` for SBA / combat / mana-ability-
/// gating reads (does NOT replace card-type reads for
/// graveyard-filter / search-library Effect predicates,
/// which still want printed `is_creature`). Mirrors Python's
/// `is_creature_now` at `src/mtg_bot/game.py:831`.
pub fn is_creature_now(obj: &GameObject) -> bool {
    if obj.printing.is_creature { return true; }
    if is_stationed(obj) { return true; }
    false  // Phase 1: no manland / type-grant overlay
}
```

The Rust side already has the `charge_counters` field and
the per-zone-reset to 0 (CR 400.7), so the per-object state
infrastructure is in place. Phase 1's new piece is the
**predicate fold** (`is_stationed`) and its consumption sites
(SBA "creature-with-0-tgh dies" pass; combat creature-
participation pass; effective-keywords reader).

### 4.6 Effective-keyword fold extension

**File:** `rust/src/state_ops_combat.rs` (or wherever
`effective_keywords_for(obj)` lives). Extend the keyword set
walk: when `is_stationed(obj)`, merge in
`obj.printing.stationed_keywords` BEFORE walking the layer-6
entries (mirroring Python's `game.py:1191-1193` shape, where
`stationed_keywords` joins the base set pre-layer-6).
Phase 1's pilot stationed-keyword set is `{flying, haste}`
— both already first-class in Rust's combat/priority
machinery.

### 4.7 P/T resolution under stationed-flip

The Spacecraft printing carries printed `power` / `toughness`
(Galvanizing Sawship: 6/5). When stationed, the layered-fold
P/T read should return the printed P/T (Phase 1 admits no
PowerToughnessBonus rider on the Spacecraft itself — that's
Phase 2, Lumen-Class Frigate). When NOT stationed, P/T reads
are irrelevant (the object is not a creature; SBA does not
ask for its toughness). Phase 1 only needs to ensure the
existing P/T reader returns `(printing.power, printing.
toughness)` for a stationed Spacecraft — no `+1/+1` counter
fold, no anthem fold, no formula.

## 5. Python bridge spec — bidirectional round-trip + admit predicate

### 5.1 Bridge dict shape (Python-side emit)

**File:** `src/mtg_bot/parity/cross_engine.py` (the
`build_rust_state.printing_dict` emit path). Add 2 new keys
to the printing dict, mirroring the cost-reduction Phase 1
`cost_reductions` precedent:

```python
# Spacecraft Station substrate Phase 1.
if printing.station_threshold is not None:
    printing_dict["station_threshold"] = int(printing.station_threshold)
if printing.stationed_keywords:
    printing_dict["stationed_keywords"] = sorted(printing.stationed_keywords)
```

Both keys are **omitted when default** (None / empty) for
back-compat — every pre-Phase-1 registry dict omits both,
which the Rust parser maps to `Option::None` / `Vec::new()`.

### 5.2 Rust parse arm

**File:** `rust/src/cards.rs` (the `printing_dict_to_card_
printing` parser, near the `cost_reductions` arm). Read
`station_threshold` as an optional non-negative `i32` (None
or positive); read `stationed_keywords` as a `Vec<String>`
filtered against the Rust safe-keyword set (Phase 1 admits
only keywords already first-class in Rust combat/priority).

### 5.3 Python-side reconstruction arm

**File:** `src/mtg_bot/parity/cross_engine.py` (the
`_card_def_to_python_printing` / `_printing_to_card_def`
helpers — verify-first walk pin: cost-reduction Phase 1
added a `cost_reductions` arm here; Spacecraft follows the
same shape).

```python
station_threshold = printing_dict.get("station_threshold")
stationed_keywords = frozenset(printing_dict.get("stationed_keywords", ()))
```

### 5.4 New admit predicate

**File:** `src/mtg_bot/parity/trajectory.py` (sibling to
`_printing_is_bridge_pure_cost_reduction_creature` and
`_printing_is_bridge_pure_warp_creature`):

```python
def _printing_is_bridge_pure_station_spacecraft(printing) -> bool:
    """True iff a CardPrinting is a Phase-1 bridge-supported
    Spacecraft — zero abilities, only the Station mechanic.

    Spacecraft Station substrate — Phase 1 (sub-shape A; spec
    at docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_1_DESIGN.md).
    Pilot: Galvanizing Sawship (station_threshold=3,
    stationed_keywords={flying, haste}, 6/5, {5}{R}, 5,938
    17lands decks).
    """
    if "Spacecraft" not in printing.subtypes:
        return False
    if printing.station_threshold is None:
        return False  # Phase 4 only (The Eternity Elevator)
    if printing.station_threshold <= 0:
        return False
    if printing.static_abilities:
        return False  # Phase 2 (Lumen-Class Frigate)
    if printing.triggered_abilities:
        return False  # Phase 3 (5 carriers)
    if printing.activated_abilities:
        return False  # Phase 4 (The Eternity Elevator)
    if printing.spell_effect is not None:
        return False
    if printing.room_halves:
        return False
    if printing.loyalty is not None:
        return False
    if printing.cost_reductions or printing.external_cost_reductions:
        return False
    if printing.warp_cost or printing.kicker_cost or printing.impending_cost:
        return False
    if getattr(printing, "dynamic_pt_formula", None) is not None:
        return False
    if getattr(printing, "ward_cost", None) is not None:
        return False
    if printing.keywords:
        return False  # Phase-1 carrier has empty baseline keywords
    if not printing.stationed_keywords:
        return False  # would defeat the substrate's leverage
    for kw in printing.stationed_keywords:
        if kw not in _SAFE_KEYWORDS:
            return False
    if printing.grants_toughness_as_station_power_for_creatures_you_control:
        return False  # Tapestry Warden flag — Phase-2+ widen
    try:
        _parse_mana_cost_string(printing.mana_cost_str or "")
    except ValueError:
        return False
    return True
```

### 5.5 Admit-predicate registration

The new predicate is registered as a parallel admit-disjunct
in the loader's filter (sibling to
`_printing_is_bridge_simple_creature`,
`_printing_is_bridge_pure_cost_reduction_creature`,
`_printing_is_bridge_pure_warp_creature`), per the §2 same-
loader-multiple-predicates pattern. The full filter is
`existing_predicate(printing) OR
_printing_is_bridge_pure_station_spacecraft(printing)`. The
positive Phase-1 admit set is **exactly Galvanizing Sawship**
(no other EoE printing matches every clause).

## 6. Test plan — substrate units + bridge round-trip + per-card real-EoE probes + no-silent-auto-grow

### 6.1 Substrate unit pins

1. Rust `is_stationed` predicate: with `station_threshold=3`
   and `charge_counters` ∈ {0, 1, 2}, returns False; with
   `charge_counters` ∈ {3, 4, 100}, returns True.
2. Rust `is_creature_now` predicate: for a stationed
   Spacecraft (Galvanizing Sawship with `charge_counters >= 3`),
   returns True; for the same printing un-stationed
   (`charge_counters == 0`), returns False; for a printed
   Creature, always returns True.
3. Rust `apply_activate_station` resolver: taps crew, adds
   `effective_power(crew)`-many charge counters to the
   Spacecraft. Invalid inputs (crew already tapped /
   summoning-sick / not own / same id as Spacecraft / Spacecraft
   not own) silent-noop.
4. Rust legal-action emitter: at sorcery speed with a
   stationed-eligible board, emits N×M ActivateStation actions
   where N = own Spacecraft count, M = own eligible-crew
   count; at instant speed, emits zero.
5. Rust effective-keywords fold: a stationed Spacecraft with
   `stationed_keywords={flying, haste}` reads `{flying, haste}`
   in `effective_keywords`; un-stationed, reads `{}`.
6. P/T read pin: a stationed Galvanizing Sawship reads
   `(6, 5)` via Rust's combat P/T reader; un-stationed, the
   reader path is not exercised (SBA does not query the P/T
   of a non-creature).

### 6.2 Cross-engine bridge round-trip pins

7. A DeckSpec with a synthetic CardDef
   `subtypes=("Spacecraft",), station_threshold=3,
   stationed_keywords=("flying", "haste"), power=6,
   toughness=5, mana_cost_str="{5}{R}"`: build Rust state via
   `build_rust_state` → fingerprint byte-equal across engines
   pre-ETB.
8. With the synthetic carrier on-battlefield, an
   ActivateStation decision routed through `step_both` →
   byte-equal post-action state (mana pools / charge counters
   / tap state / fingerprint all match).
9. After three Station activations push `charge_counters` to
   `>= station_threshold` on both engines, the post-state
   combat predicate (`is_creature_now`) reads True on both,
   and the next combat phase enumerates the stationed
   Spacecraft as a legal attacker (Galvanizing Sawship has
   `haste` while stationed — bypasses summoning-sickness on
   the **animation tick**, the same turn it becomes a
   creature).
10. Action-set invariance pin: both engines' `legal_actions`
    emit the SAME set (and positional order) of
    ActivateStation actions for the same board state.

### 6.3 Real-EoE per-card probe (Galvanizing Sawship)

A `tests/test_parity_smoke.py` probe (insert immediately
above the `# === PHASE5_PROBES_INSERT_ABOVE_THIS_LINE ===`
sentinel) that drives the **actual Galvanizing Sawship
printing** (resolved via the live `OracleParserCardSource`,
NOT a synthetic CardDef — round-46 real-EoE-signal
discipline) on **both** engines through three scenarios
across the charge-counter axis:

- **Scenario A — un-stationed (charge_counters=0):** cast
  Galvanizing Sawship + pass; assert byte-equal post-cast
  fingerprint (mana pool / zones / `charge_counters=0`);
  assert no ActivateStation actions emitted at instant
  speed; assert combat does not enumerate the Spacecraft as
  a legal attacker.
- **Scenario B — partial-station (charge_counters=1):** with
  Galvanizing Sawship on battlefield + one own untapped
  vanilla creature with power 1, drive ActivateStation
  (vanilla → Sawship); assert byte-equal post-action
  (`charge_counters=1`, crew tapped); assert combat still
  does not enumerate the Spacecraft as a legal attacker
  (`1 < station_threshold=3`).
- **Scenario C — fully-stationed (charge_counters=3):** with
  three Stations queued (or one with power-3 crew), drive
  the activations; assert byte-equal post-state
  (`charge_counters=3, is_creature_now=True`,
  `effective_keywords ⊇ {flying, haste}`); assert combat
  DOES enumerate the Spacecraft as a legal attacker; assert
  `haste` overrides what would otherwise be summoning-
  sickness for the just-animated stationed Spacecraft.

**Bench-strategy coverage note:** the bench's `attack_all`
strategy may not naturally produce the
"queue-three-ActivateStations-then-attack" line. The probe
MUST use a scripted picker (a `tests/parity/_picker_shims.
py` helper) that forces the activation sequence so each
scenario is actually exercised. The implementing agent
confirms; the SL entry (§9) pins this as probe-driven, not
organic.

### 6.4 Decline-set bench check (no-silent-auto-grow)

A negative-set bench check at the loader filter,
parametrized over the 7 deferred Spacecraft and a Tapestry-
Warden-style 0-deck proxy:

11. `_printing_is_bridge_pure_station_spacecraft(<live
    Lumen-Class Frigate>)` is `False` (carries
    `static_abilities`).
12. `(<live Larval Scoutlander>)`, `(<live Sledge-Class
    Seedship>)`, `(<live Synthesizer Labship>)`, `(<live
    Entropic Battlecruiser>)`, `(<live Infinite Guideline
    Station>)` all return `False` (each carries
    `triggered_abilities`).
13. `(<live The Eternity Elevator>)` returns `False`
    (`station_threshold is None` AND
    `activated_abilities` non-empty).
14. **Subsystem-attribution pin:** exactly 1 EoE printing
    passes `_printing_is_bridge_pure_station_spacecraft`
    (Galvanizing Sawship) — the guardrail's positive set is
    exhaustive for Phase 1.
15. **Decline-set bench check:** with the EoE deck pool
    loaded, confirm the bench's loader-side filter admits
    +1 card (Galvanizing Sawship) over the pre-Phase-1
    baseline, with 0 spillover into any of the 7 deferred
    Spacecraft. This is the Spacecraft analogue of the
    cost-reduction Phase 1 decline-set parity check.
16. **No-silent-auto-grow pin:** with a Tapestry-Warden
    carrier injected into a synthetic deck (a CardDef
    setting `grants_toughness_as_station_power_for_
    creatures_you_control=True`), confirm
    `_printing_is_bridge_pure_station_spacecraft` returns
    `False` for the Tapestry-Warden carrier AND that the
    Phase-1 admit set excludes it. This pins the §3.4
    asymmetry against accidental admission in a future
    bench-data refresh.

## 7. Estimated cycle count

Per the per-card multi-cycle precedent established by the
cost-reduction + warp_cost campaigns (1 substrate + 1 admit
+ probe-per-scenario per card):

| Cycle | Owner | Deliverable |
|---:|---|---|
| 1 | Rust agent | Substrate landing — Part A: `CardPrinting.station_threshold` + `stationed_keywords` fields + parse arm + `is_stationed` predicate + per-zone-reset verification. **Sole Rust slice of cycle 1** (`.pyd` race rule). |
| 2 | Rust agent | Substrate landing — Part B: `Action::ActivateStation` + `apply_activate_station` resolver + legal-action emitter + `is_creature_now` fold extension + effective-keywords-fold extension. **Sole Rust slice of cycle 2.** |
| 3 | Python/bench agent | Bridge round-trip arms (5.1-5.3) + `_printing_is_bridge_pure_station_spacecraft` admit predicate (5.4) + admit registration (5.5) + the 6 substrate unit pins (§6.1) + the 4 bridge round-trip pins (§6.2). |
| 4 | Bench agent | Galvanizing Sawship real-EoE probe Scenario A (un-stationed; §6.3) + Scenario B (partial-station; §6.3) + decline-set bench check on Lumen-Class Frigate + 5 trigger-bearing Spacecraft + The Eternity Elevator (§6.4 pins 11-13). |
| 5 | Bench agent | Galvanizing Sawship real-EoE probe Scenario C (fully-stationed + haste-attack pin; §6.3) + subsystem-attribution exhaustiveness pin (§6.4 pin 14) + EoE-deck-pool decline-set parity check (§6.4 pin 15) + Tapestry-Warden no-silent-auto-grow pin (§6.4 pin 16). |
| 6 | Doc agent (rolling) | SEARCH_LIMITATIONS.md entries (§9) + per-cycle pool parity regen + Phase-1-complete worklog + the BLOCKED-SG → PROBED transition pin for Galvanizing Sawship (subsystem-gated 56 → 55 / single-gated row drops Galvanizing Sawship). |

**Estimated total: ~6 cycles for Phase 1**, slightly larger
than the cost-reduction Phase 1's ~5 cycles because the
substrate landing splits across cycles 1 + 2 (field landing
vs action landing — both touch the same Rust files but
sequence cleanly across two `.pyd` rebuilds; the cost-
reduction Phase 1 substrate fit in one rebuild because it
added no new action). Cycle 1 may spill to 2 if threading
`station_threshold` through the printing parse + per-object
state machinery surfaces unexpected interactions; cycle 2
may spill to 3 if the effective-keywords / is_creature_now
fold needs more call-site rewrites than the substrate scout
identified.

**Subsequent phases (out of Phase 1 scope, scoped here for
campaign context):**

- **Phase 2 (Lumen-Class Frigate, ~2-3 cycles):** static-
  anthem PowerToughnessBonus reader fold + the
  `tier_threshold`-gated static predicate + admit widen +
  per-card real-EoE probe. The rescout pinned this as
  "~70 % of one cycle off MTL Phase-4 reader fold + bridge"
  but cited the Spacecraft substrate as the missing
  prerequisite — Phase 1 lands the prerequisite.
- **Phase 3 (5 trigger carriers, ~6-10 cycles):** 5 Effect-
  class Rust slices + 2 `tier_threshold`-gated trigger-
  firing predicates (Synthesizer Labship tier=2; Entropic
  Battlecruiser tier=1) + 5 admit widens + 5 per-card
  real-EoE probes. Each card is roughly 1-2 cycles
  (Effect + bridge arm + probe), with the Phase-2
  `tier_threshold` gate predicate amortized across two
  of them.
- **Phase 4 (The Eternity Elevator, ~2 cycles):** Carrier-
  AA non-token admit predicate widen (depends on Worker
  B's parallel Carrier-AA campaign Phase 1+) + new
  `AddChargeCounterManaOfChosenColor` Effect class +
  per-card real-EoE probe across the un-staged /
  tier_threshold=20-reached scenarios.

**Campaign total: ~16-22 cycles across Phase 1 / 2 / 3 / 4**
to close all 8 cards / 41,281 decks, comparable to or
slightly larger than the cost-reduction campaign's
~10-cycle 5-card / 53,648-deck close. The size delta is
the ActivateStation action + the layered-fold conditional
flip + 5 distinct Phase-3 Effect classes — none of which
cost-reduction needed.

## 8. SEARCH_LIMITATIONS.md entries (land WITH Phase 1 cycle 1+2)

Three entries (estimated):

1. **Spacecraft Phase 1 supports only the zero-ability
   Spacecraft carrier; static / triggered / activated
   abilities + tier_threshold-gating deferred.**
   Location: `state_ops_actions.rs::apply_activate_station`
   + `trajectory.py::_printing_is_bridge_pure_station_
   spacecraft`. Why OK: the filter guardrail positively
   rejects every non-Phase-1 shape on BOTH bridge sides;
   failure mode = a future probe admitting a Phase-2+ card
   without the guardrail widening would see Rust silently
   omit the static/triggered/activated machinery while
   Python applies it (mana / state divergence on the first
   such trigger / activation). Fix-scope = Phase 2 (Lumen-
   Class Frigate static) + Phase 3 (5 trigger carriers) +
   Phase 4 (The Eternity Elevator AA). Impact = +1 card /
   +5,938 decks Phase-1 yield; 0 strength cost.
2. **Rust `apply_activate_station` does NOT honor
   `grants_toughness_as_station_power_for_creatures_you_
   control` (Tapestry Warden's flag).** Location:
   `state_ops_actions.rs::apply_activate_station`. Shortcut:
   Rust uses `effective_power(crew)` as the charge-counter
   addend; Python's `actions.py:2393-2401` consults the
   battlefield-scan flag and switches to `effective_
   toughness` when any own permanent carries the flag AND
   the crew has toughness > power. Why OK: Phase 1's
   admit predicate positively rejects any Tapestry-
   Warden-style printing (the `_printing_is_bridge_pure_
   station_spacecraft.grants_toughness_as_station_power_
   for_creatures_you_control` guard at §5.4 — verified by
   probe pin §6.4-16). Failure mode: a future bench-data
   refresh that adds a Tapestry-Warden-shape printing
   without widening the admit predicate would silently
   diverge on the first such Station activation (Python
   adds toughness-counters; Rust adds power-counters).
   Fix-scope: ~1 cycle to add the battlefield-scan to
   Rust. Impact: 0 today (Tapestry Warden not in pool).
3. **Rust does NOT model `station_threshold=None` (non-
   animating Spacecraft).** Location: same admit + apply
   chain. Phase 1's admit predicate explicitly rejects
   `station_threshold is None`; The Eternity Elevator
   (the sole `None`-threshold Spacecraft) stays DEFERRED
   to Phase 4. Why OK: `Option<i32>` field already
   accommodates `None`; the resolver and is_stationed
   helper both handle `None` correctly (resolver allows
   activation but the Spacecraft never animates;
   `is_stationed` returns False). Phase 1 simply does
   not admit such a printing. Failure mode: a Phase-4
   admit widen without Carrier-AA's non-token-AA bridge
   landing first would crash at admit (the activated
   ability list would be empty post-bridge); fix-scope
   = Phase 4 depends on Carrier-AA Phase 1+; impact = 0
   today.

## 9. Rejected alternatives

### 9.1 Land all 8 Spacecraft in Phase 1

**Rejected.** Phase 1's smallest-self-contained-slice
discipline front-loads the minimum substrate that
demonstrably ships +1 card. The 7 deferred carriers each
require their own Phase 2+ slice (static-anthem reader for
Lumen; 5 distinct Effect classes for the trigger carriers;
Carrier-AA non-token bridge for The Eternity Elevator).
Each subsystem is independently a multi-cycle slice.
Bundling them inflates Phase 1 to a ~16-cycle behemoth
that blocks any progress on the Galvanizing Sawship signal
for the entire bundle's duration. Phase 1 ships 1 card in
~6 cycles; subsequent phases ship the rest.

### 9.2 Skip Phase 1 substrate, jump straight to Lumen-Class Frigate

**Rejected — Spacecraft substrate is the prerequisite.**
The rescout (`MULTI_GATED_TAIL_TRACTABILITY_RESCOUT_2026-
05-24.md` #5) pinned Lumen-Class Frigate at "~70 % of one
cycle off MTL Phase-4 reader fold + bridge", BUT crossed
"§2-DEFERRED Spacecraft substrate (tier_threshold=2,
station_threshold=12)". Without the Spacecraft substrate
landing, Lumen-Class Frigate's static-anthem rider can't be
gated on `charge_counters >= 2` (the static fires
unconditionally on the Rust side — guaranteed divergence
on every Lumen-Class Frigate game from turn 1) AND the
Lumen-Class Frigate object itself never animates as a
creature (P/T 3/5 never shows up in combat on Rust). The
single-card "static slice" without the substrate is a
strict liability — ship a guaranteed divergence to admit
1 card. Phase 1 here lands the substrate; Phase 2 closes
Lumen-Class Frigate cleanly on top.

### 9.3 Widen `_printing_is_bridge_simple_creature` to admit Spacecraft

**Rejected — the anti-pattern (round-38-E5 / count-
chasing).** Spacecraft printings carry `is_creature ==
False` printed-side (they're Artifacts), so they don't
flow through `_printing_is_bridge_simple_creature` today.
Even if widened, the predicate doesn't validate the
`station_threshold` or `stationed_keywords` invariants,
and admitting a Spacecraft to a bench that lacks the
ActivateStation machinery would mean: Python's
`legal_actions` emits ActivateStation while Rust's
emits zero — instant action-set divergence on every
relevant board state. The substrate has to land before
any admission is bridge-correct.

### 9.4 Implement ActivateStation as an Effect rather than an Action

**Rejected — Python's shape is the source of truth.**
Python models ActivateStation as a top-level Action
(`src/mtg_bot/actions.py:144`, sibling to `CastSpell` /
`ActivateAbility` / `PassPriority`), NOT as an Effect on
the stack. The decision is sorcery-speed, does not use
the stack (no trigger fires from a Station activation —
the charge-counter bump is direct), and is enumerated
by `legal_actions`. Modeling it as an Effect on the Rust
side would create a fundamental shape mismatch
(Python's action-set would include an ActivateStation
action while Rust's would not, OR Rust's stack would
emit a stack-item that Python doesn't); the bridge
round-trip would have no clean target. Phase 1 mirrors
Python's shape exactly: top-level Action variant +
direct resolver, no stack.

### 9.5 Use the existing `Effect::PutChargeCountersOnTargetSpacecraftOrPlanetYouControl` as the Station primitive

**Rejected — different binding semantics.** That Effect
(`rust/src/cards.rs:6711-6720`) is a TARGETED amount-N
charge-counter Effect resolved during stack resolution
— used by, e.g., a permanent's ETB trigger to put N
counters on any of the controller's Spacecraft. Station
is a STATIC CHOICE (controller picks a specific
spacecraft + crew at decision time) that adds counters
EQUAL TO THE CREW'S POWER (a per-object read, not a
fixed N). Reusing the targeted Effect would force a
no-target-selection / runtime-amount-derivation shape
that diverges from how every other Effect in the Rust
engine resolves. The clean solution is a new Action +
resolver; the existing targeted-charge-counter Effect
stays as it is (for the unrelated Drill Too Deep et al.
cards that use it).

## 10. Acceptance / sign-off

Phase 1 is complete and ready to merge to `main` when:

1. All 16 pins (§6.1-§6.4) pass on the parity gate.
2. The Galvanizing Sawship real-EoE probe (§6.3) passes
   byte-equal through all three scenarios (un-stationed /
   partial / fully-stationed-and-attacking) on both
   engines.
3. The decline-set bench check confirms +1 card admitted
   (Galvanizing Sawship), 0 spillover across the 7
   deferred Spacecraft.
4. The Tapestry-Warden no-silent-auto-grow pin (§6.4-16)
   confirms the substrate cannot accidentally accept a
   `grants_toughness_as_station_power` carrier.
5. All three SEARCH_LIMITATIONS.md entries (§8) land
   alongside the substrate code.
6. `.pyd` rebuilt clean; the parity gate
   (`tests/test_parity_smoke.py + test_cross_engine_etb_
   triggers.py + test_trajectory_parity.py +
   test_trajectory.py + test_measure_pool_parity.py`)
   stays green.
7. `scripts/scout_r58_subsystem_attribution.py` re-run:
   the `station_spacecraft` row's single-gated count
   drops from 1 → 0; pool BLOCKED-SG total drops 56 →
   55; PROBED total bumps +1.

## 11. Cross-references

- `docs/COVERED_BY_CONSTRUCTION_PROBE_WRITING_SATURATION_2026-05-25.md` —
  the 2026-05-25 saturation report that identified
  Spacecraft Station as the #2 DEFERRED row and motivated
  this campaign (`station_spacecraft | 8 | 41,281 |
  sprawling`).
- `docs/CARRIER_AA_SUBSTRATE_PHASE_1_DESIGN.md` — the
  parallel Carrier-AA scoping doc (worker-B's lane);
  format precedent + the parallel-substrate sequencing
  template this campaign mirrors.
- `docs/COST_REDUCTION_SUBSTRATE_PHASE_1_DESIGN.md` —
  the format precedent + the per-card / per-cycle
  budgeting calibration ground truth.
- `docs/MULTI_GATED_TAIL_TRACTABILITY_RESCOUT_2026-05-24.md` —
  the 2026-05-24 rescout that pinned Lumen-Class Frigate
  as Phase-2-feasible-once-Spacecraft-substrate-lands
  (entry #5).
- `docs/SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY.md` §2
  line 1042, §5 line 1972 — the Spacecraft row's
  authoritative leverage data (8 / 1 / 5,938 / DEFERRED).
- `docs/POOL_PARITY.md` line 448 — the BLOCKED-SG
  breakout table's Station/Spacecraft row.
- `src/mtg_bot/cards/base.py:560-565` — Python's
  `station_threshold` + `stationed_keywords` field
  definitions (live source of truth).
- `src/mtg_bot/cards/base.py:944-950` —
  `grants_toughness_as_station_power_for_creatures_you_control`
  field (Tapestry Warden's flag — the §3.4 asymmetry
  pin).
- `src/mtg_bot/cards/base.py:1244-1290` —
  `make_spacecraft` builder (the synthetic-test
  precedent for substrate unit pins §6.1).
- `src/mtg_bot/actions.py:144-154` — Python's
  `ActivateStation` action dataclass (the Rust port's
  shape source of truth).
- `src/mtg_bot/actions.py:2353-2407` — Python's
  `_activate_station` resolver (the Rust resolver's
  reference implementation; includes the Tapestry
  Warden read).
- `src/mtg_bot/legal.py:831-852` — Python's Station
  legal-action emitter (the Rust emitter's reference).
- `src/mtg_bot/game.py:825-828` — Python's
  `is_stationed` predicate.
- `src/mtg_bot/game.py:831-870` — Python's
  `is_creature_now` predicate (the layered-fold
  shape Phase 1 mirrors).
- `src/mtg_bot/game.py:1160-1199` — Python's
  effective-keywords fold including the
  `stationed_keywords` join (the §4.6 reference).
- `rust/src/state.rs:44-63` — Rust's existing
  `GameObject.charge_counters` field (the
  CE20 follow-up Slice 3 scaffolding Phase 1 builds on).
- `rust/src/cards.rs:9981-10022` — Rust's existing
  `ActivatedAbility.tier_threshold` field (the
  parallel charge-counter-gate scaffolding for
  Phase 2+ static/triggered tier-gating).
- `rust/src/state_ops_legal.rs:3316-3328` — the
  existing `tier_threshold` AA legality gate (the
  Phase-2+ trigger/static-gate machinery's nearest
  precedent).
- `rust/src/state_ops_actions.rs:996-1001` — the
  existing `tier_threshold` AA application-time gate.
- `rust/src/state_ops_resolve.rs:1561-1594` — the
  existing `Effect::PutChargeCountersOnTargetSpace
  craftOrPlanetYouControl` resolver's Spacecraft-OR-
  Planet filter (the precedent for §4.3's
  `is_spacecraft(o)` predicate read of `subtypes`).
- `rust/src/state_ops_resolve.rs:10173-10310` — the
  existing `Effect::AmblerEtbReplaceOptionalSpaceShip
  ConditionalChargeCounters` resolver's
  `obj.charge_counters += 10` site (the precedent for
  the Phase-1 resolver's saturating-add shape).
- `src/mtg_bot/parity/trajectory.py:4698, 8576` — the
  current `if printing.station_threshold: return False`
  guards across the 8 sibling admit predicates (the
  pre-Phase-1 substrate-decline pin Phase 1 widens).

## 12. Regenerating the enumeration

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
  scripts/scout_r58_subsystem_attribution.py
```

reproduces the 8-member Spacecraft row exactly (1 single-
gated Galvanizing Sawship, 7 multi-gated). The
per-card live parsed printings (§2 table) are verifiable
via `OracleParserCardSource().get_printings()[<name>]` —
walk `station_threshold`, `stationed_keywords`,
`static_abilities`, `triggered_abilities`, and
`activated_abilities`. All §4 / §5 file:line refs verified
against main `456108df`.
