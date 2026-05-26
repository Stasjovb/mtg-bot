Generated 2026-05-25 (post `spacecraft-phase-2-cycle-3-scenarios-cd-p1`, main
`086f86fc`; parallel-with `carrier-aa-phase-3a-cycle-1-substrate-p1` in flight
on Worker B's lane). **Design only — NO production / `_SAFE_*` / Rust change
in this slice; no gate run beyond the 31/31 `tests/test_measure_pool_parity.py`
baseline** (docs + read-only scout against the live tree at main `086f86fc`).
This doc scopes the **Spacecraft Station Phase 3** sub-shape (the **5
trigger-bearing Spacecraft carriers** — Larval Scoutlander, Sledge-Class
Seedship, Synthesizer Labship, Entropic Battlecruiser, Infinite Guideline
Station) in the gold-standard format of
`docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_2_DESIGN.md` and
`docs/CARRIER_AA_SUBSTRATE_PHASE_3_DESIGN.md`. Every file:line below is
verified against the live tree at main `086f86fc`.

> **Relationship to `docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_1_DESIGN.md` +
> `docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_2_DESIGN.md`.** Phase 1
> (`ea9aa996` → `62e10ff9` → `e9a31c83` → `7e07400f`) shipped the
> Spacecraft Station substrate to sub-shape A (zero-ability Spacecraft
> carrier — Galvanizing Sawship). Phase 2 (`afccee65` → `8675b274` →
> `086f86fc`) shipped sub-shape B (zero-ability + single static-anthem
> Spacecraft — Lumen-Class Frigate) on top of the MTL Phase-4 anthem
> substrate plus one new `source_charge_counters_at_least` condition_tag
> dispatcher arm. Phase 3 here scopes the **next-narrowest sub-shape C**
> — the 5 trigger-bearing Spacecraft carriers that all carry a Spacecraft
> body PLUS one or two `TriggeredAbility`s whose Effect class Rust does
> not yet support (4 brand-new Effect ports plus 1 `EachOpponentDiscards`
> widen to mode-0). Phase 4 (The Eternity Elevator) stays deferred per
> Phase 1 §3.3 / Phase 2 §3.2.
>
> **Relationship to the Phase 2 `source_charge_counters_at_least`
> condition_tag dispatcher landed at `afccee65`.** Phase 2 wired the new
> condition_tag arm at `static_anthem_condition_matches`
> (`rust/src/state_ops_combat.rs:737-810`) with the signature widened to
> thread the SOURCE `GameObject` for `source.charge_counters` reads. The
> arm is **dispatcher-pattern reusable**: Phase 3 routes the
> trigger-firing-time charge-counter gate (Synthesizer Labship at
> `tier_threshold=2`; Entropic Battlecruiser at `tier_threshold=1` on
> the mode-1 line) through the SAME condition-tag pattern, transplanted
> from the static reader fold to the trigger dispatch site at
> `state_ops_resolve.rs:917-967`. The Phase-2 dispatcher arm itself is
> reused unchanged for the static-anthem axis; the Phase-3 trigger gate
> is a sibling check on the SAME `TriggeredAbility.tier_threshold` /
> `condition_args` slots Phase 2 introduced.
>
> **Relationship to the partial trigger-gating scaffolding already
> shipped Python-side.** Python's `turn.should_fire_trigger`
> (`src/mtg_bot/turn.py:436-480`) already gates `TriggeredAbility.tier_
> threshold > 0` against `source.charge_counters` at the trigger-firing
> chokepoint. **Python side is already in production.** Rust side has
> NO `tier_threshold` field on `TriggeredAbility` yet
> (`rust/src/cards.rs:9725-9748` — the slice 1 docstring notes
> "`requires_void`, `tier_threshold`, `room_half` from Python are
> omitted here — defaults of "always fire" suffice for the smoke probe;
> they land alongside their gates in Slice 3+"). Phase 3 ports the
> Rust-side `TriggeredAbility.tier_threshold: i32` field + the dispatch
> gate at `state_ops_resolve.rs:927-951`.
>
> **Relationship to the 5 Effect classes whose Python implementations
> already exist.** Each of the 5 Phase-3 carriers' Effect classes is
> defined Python-side at:
> * `OptionalSacLandOrLanderForBasicLandRamp` —
>   `src/mtg_bot/effects/combinators.py:699`
> * `OptionalPutCreatureFromHandOntoBattlefield` —
>   `src/mtg_bot/effects/combinators.py:205`
> * `TargetArtifactBecomesCreatureUEOT` —
>   `src/mtg_bot/effects/generic/become_type.py:36`
> * `EachOpponentDiscardsOrLosesLife` —
>   `src/mtg_bot/effects/generic/life.py:114`
> * `CreateTokenPerMulticoloredPermanent` —
>   `src/mtg_bot/effects/generic/tokens.py:122`
> * `DrawCardPerMulticoloredPermanent` —
>   `src/mtg_bot/effects/generic/draw_mill.py:120`
>
> Python-side resolve paths are live in production via the
> `OracleParserCardSource`; the bridge gap is symmetric — bridge encode +
> bridge decode + Rust `Effect::*` variant + Rust resolve arm. Of the 6
> Effect classes the 5 cards carry, only `Effect::TargetPlayerLosesLife`
> + `Effect::EachOpponentDiscards` are Rust-supported today (verified
> at `rust/src/cards.rs:1189` + `rust/src/cards.rs:1238`). The remaining
> 5 (`OptionalSacLand...`, `OptionalPutCreature...`, `TargetArtifactBec...`,
> `EachOpponentDiscardsOrLosesLife`, `CreateTokenPerMulticolored...`,
> `DrawCardPerMulticolored...`) need new Rust `Effect::*` variants.

# Spacecraft Station substrate Phase 3 — campaign scoping doc (sub-shape C: bare zero-ability + 1 or 2 triggered abilities Spacecraft carriers — 5-card multi-sub-phase campaign)

## 0. Executive summary

The **Spacecraft Station** subsystem at live HEAD `086f86fc` binds **6
cards remaining** (8 total per Phase 1; Galvanizing Sawship PROBED in
Phase 1, Lumen-Class Frigate PROBED in Phase 2) across the BLOCKED-SG
row. Of those 6, **exactly 5 — Larval Scoutlander, Sledge-Class
Seedship, Synthesizer Labship, Entropic Battlecruiser, Infinite Guideline
Station — pass the next-narrowest sub-shape filter** (sub-shape A +
1-or-2 `TriggeredAbility` riders, no static, no activated-other-than-
Station, no non-Spacecraft baseline keywords). The remaining card (The
Eternity Elevator) stays deferred — Phase 4 owns the
`station_threshold=None` + activated-ability shape per Phase 1 §3.3 /
Phase 2 §3.2.

This doc scopes the substrate's **Phase 3**: admit the
**trigger-bearing Spacecraft carriers** sub-shape — a Spacecraft with
the Station mechanic (Phase 1 + Phase 2 already support) PLUS one or
two `TriggeredAbility` entries whose Effect class is one of a closed
list of 5 newly-ported Effect families. Phase 3 ships across **three
sub-phases** (3A / 3B / 3C) selected by **per-Effect-class isolation
and Rust dispatch reuse**:

* **Phase 3A** — `Effect::OptionalSacLandOrLanderForBasicLandRamp`
  alone, on **Larval Scoutlander** (the simplest single-trigger
  Spacecraft; no `tier_threshold` complication; ETB-only event;
  reuses the existing Phase 1 +
  [`Effect::SearchLibraryForBasicLandTapped`](rust/src/state_ops_resolve.rs)
  +
  [`Effect::Sacrifice`](rust/src/state_ops_resolve.rs)
  resolve primitives the way Carrier-AA Phase 2b does).
* **Phase 3B** — `Effect::OptionalPutCreatureFromHandOntoBattlefield`
  alone, on **Sledge-Class Seedship** (the simplest single-trigger
  Spacecraft on the ATTACKS event; no `tier_threshold` complication;
  pure zone-move resolve primitive composes with existing ETB-queue
  pattern).
* **Phase 3C** — `TriggeredAbility.tier_threshold` Rust slot landing
  + `Effect::TargetArtifactBecomesCreatureUEOT` +
  `Effect::EachOpponentDiscardsOrLosesLife` widen of the existing
  `EachOpponentDiscards` + `Effect::CreateTokenPerMulticolored
  Permanent` + `Effect::DrawCardPerMulticoloredPermanent`. Lands all
  3 remaining Phase-3 carriers (Synthesizer Labship + Entropic
  Battlecruiser + Infinite Guideline Station) — each on its own
  per-card cycle so the no-silent-auto-grow regression remains
  card-narrow.

Phase 3 explicitly **defers**: The Eternity Elevator (Phase 4,
`station_threshold=None` + activated abilities; dependency on Worker
B's Carrier-AA non-token-AA bridge ongoing).

Estimated campaign scope: **Phase 3 = ~6-10 cycles total** (3A
~2 cycles + 3B ~2 cycles + 3C ~4-6 cycles spanning the
`TriggeredAbility.tier_threshold` substrate landing plus one
Effect-class slice per remaining card). +5 cards admitted (Larval
Scoutlander, Sledge-Class Seedship, Synthesizer Labship, Entropic
Battlecruiser, Infinite Guideline Station); 17lands deck-count unlock
not enumerable from the worker's context but Phase 1 §2 table line
noted that the 7 deferred carriers post-Phase-1 summed to ~35,343
cumulative; net of Lumen-Class Frigate's Phase-2 unlock, the
Phase-3 admit set claims the bulk of the residue, leaving only The
Eternity Elevator for Phase 4. Per-card subtotals are not load-bearing
for sequencing here; what matters is that Phase 3 closes the
*trigger* leg of the multi-gated Spacecraft tail.

## 1. Background — why this sub-shape, why now

### 1.1 Phase 1 + Phase 2 closure recap

**Phase 1** (commits `ea9aa996` → `62e10ff9` → `e9a31c83` → `7e07400f`,
2026-05-25) shipped: the `station_threshold` / `stationed_keywords`
Rust `CardPrinting` fields, the `Action::ActivateStation` resolver +
sorcery-speed legal-action emitter + `is_stationed_predicate` Rust
helper + effective-keyword fold, the `_printing_is_bridge_pure_station
_spacecraft` Python admit predicate, and the Galvanizing Sawship
per-card 3-scenario real-EoE byte-equal probe (un-stationed /
partial-station / fully-stationed-and-attacking).

**Phase 2** (commits `afccee65` → `8675b274` → `086f86fc`, 2026-05-25)
shipped: the new `source_charge_counters_at_least` `condition_tag`
arm on `static_anthem_condition_matches`
(`rust/src/state_ops_combat.rs:737-810`) with the signature widened
to thread the source `GameObject` for `source.charge_counters` reads,
the Rust parser whitelist widen at `rust/src/cards.rs:15191`, the
Python bridge rehydrator arm with `tier_threshold` thread-back to the
legacy `StaticAbility.tier_threshold` slot
(`src/mtg_bot/parity/cross_engine.py:14391-14460`), the
`_static_ability_is_phase_2_spacecraft_anthem` helper +
`_printing_is_bridge_phase_2_static_anthem_spacecraft` admit predicate
(both in `trajectory.py`), and the Lumen-Class Frigate per-card
4-scenario real-EoE byte-equal probe (Scenarios A/B/C/D across the
charge-counter axis plus a composed-shape + Tapestry-Warden flag-
carrier no-silent-auto-grow pin).

Post-Phase-2 pool-parity counts: BLOCKED-SG Station/Spacecraft row
8 → 7 → 6 (Phase 1 + Phase 2); PROBED total bumps +2;
covered_by_construction 39 → 40 (Phase 1) and stays at 39 (Phase 2 —
Lumen-Class Frigate is covered_by_construction this cycle, the
load-bearing per-card probe is the Phase 2 C3 Scenarios C+D pins
already PROBED). Both Phase-1's `_printing_is_bridge_pure_station_
spacecraft` and Phase-2's `_printing_is_bridge_phase_2_static_anthem_
spacecraft` predicates are in production via the `_filter_deck_to_
bridge_supported` OR-chain. The 5 Phase-3 carriers are positively
rejected by both Phase-1 and Phase-2 admit predicates on the
`if printing.triggered_abilities: return False` clause.

### 1.2 The 6 remaining Spacecraft — classification by ability type

A live walk against `OracleParserCardSource().get_printings()` at
main `086f86fc` (the same scout pattern Phase 1 §2 + Phase 2 §1.2
used, re-run post-Phase-2) reproduces the table unchanged for the 6
deferred carriers. Reclassified by **ability-type next-frontier**
(i.e. what blocks them BEYOND Phase 1's + Phase 2's substrate):

| Card | Spacecraft Sub-shape | `station_threshold` | Trigger family | Effect class | `tier_threshold` | Earliest Phase |
|---|---|---:|---|---|---:|---:|
| **Larval Scoutlander** | **C (single-trigger, ETB)** | 7 | ETB (self) | `OptionalSacLandOrLanderForBasicLandRamp(land_count=2)` | 0 (always-fire) | **3A** |
| **Sledge-Class Seedship** | **C (single-trigger, ATTACKS)** | 7 | ATTACKS (self) | `OptionalPutCreatureFromHandOntoBattlefield()` | 0 (always-fire) | **3B** |
| **Synthesizer Labship** | **C\* (single-trigger, tier-gated)** | 9 | BEGINNING_OF_COMBAT (you) | `TargetArtifactBecomesCreatureUEOT(power=2, toughness=2, granted_keywords={"flying"})` | 2 | **3C** |
| **Entropic Battlecruiser** | **C\*\* (two-trigger, one tier-gated)** | 8 | ATTACKS (self) + DISCARDS_CARD (opponent) | `EachOpponentDiscardsOrLosesLife(life_if_cant=3)` (mode-0, tier=0) + `TargetPlayerLosesLife(amount=3)` (mode-1, tier=1) | 0 / 1 | **3C** |
| **Infinite Guideline Station** | **C\*\* (two-trigger, untiered)** | 12 | ETB (self) + ATTACKS (self) | `CreateTokenPerMulticoloredPermanent(token_printing=Robot 2/2 tapped)` (ETB) + `DrawCardPerMulticoloredPermanent()` (ATTACKS) | 0 / 0 | **3C** |
| The Eternity Elevator | D (non-animating + activated) | **None** | — | (2× AA — `AddManaToPool` tier=0; `AddChargeCounterManaOfChosenColor` tier=20) | — | 4 |

**Sub-shape C is exactly 5 cards.** Each of the 5 cards' only
above-substrate ability is one or two `TriggeredAbility`s — no
non-Station activated abilities, no static abilities, no spell_effect,
no warp / kicker / impending costs. Live walk pin (verify-first, run
against main `086f86fc`, dispatch identical to Phase 2 §1.2's walk):

```
name='Larval Scoutlander'
subtypes=('Spacecraft',)
card_types=('Artifact',)
station_threshold=7
stationed_keywords=frozenset({'flying'})
power=3, toughness=3
mana_cost_str='{2}{G}'
triggered_abilities=(
    TriggeredAbility(
        event=Event.ENTERS,
        predicate=IsSelf(subject=None),
        tier_threshold=0,
        effect=OptionalSacLandOrLanderForBasicLandRamp(land_count=2),
    ),
)
static_abilities=()
activated_abilities=()
```

```
name='Sledge-Class Seedship'
subtypes=('Spacecraft',)
station_threshold=7
stationed_keywords=frozenset({'flying'})
power=4, toughness=5
mana_cost_str='{2}{G}'
triggered_abilities=(
    TriggeredAbility(
        event=Event.ATTACKS,
        predicate=IsSelf(subject=None),
        tier_threshold=0,
        effect=OptionalPutCreatureFromHandOntoBattlefield(),
    ),
)
static_abilities=()
activated_abilities=()
```

```
name='Synthesizer Labship'
subtypes=('Spacecraft',)
station_threshold=9
stationed_keywords=frozenset({'flying', 'vigilance'})
power=4, toughness=4
mana_cost_str='{U}'
triggered_abilities=(
    TriggeredAbility(
        event=Event.BEGINNING_OF_COMBAT,
        predicate=Controlled(by=YOU, subject=None),
        tier_threshold=2,
        effect=TargetArtifactBecomesCreatureUEOT(
            power=2, toughness=2,
            granted_keywords=frozenset({'flying'}),
        ),
    ),
)
static_abilities=()
activated_abilities=()
```

```
name='Entropic Battlecruiser'
subtypes=('Spacecraft',)
station_threshold=8
stationed_keywords=frozenset({'flying', 'deathtouch'})
power=3, toughness=10
mana_cost_str='{3}{B}'
triggered_abilities=(
    TriggeredAbility(
        event=Event.ATTACKS,
        predicate=IsSelf(subject=None),
        tier_threshold=0,
        effect=EachOpponentDiscardsOrLosesLife(life_if_cant=3),
    ),
    TriggeredAbility(
        event=Event.DISCARDS_CARD,
        predicate=Controlled(by=OPPONENT, subject=None),
        tier_threshold=1,
        effect=TargetPlayerLosesLife(amount=3),
    ),
)
static_abilities=()
activated_abilities=()
```

```
name='Infinite Guideline Station'
subtypes=('Spacecraft',)
station_threshold=12
stationed_keywords=frozenset({'flying'})
power=7, toughness=15
mana_cost_str='{W}{U}{B}{R}{G}'
triggered_abilities=(
    TriggeredAbility(
        event=Event.ENTERS,
        predicate=IsSelf(subject=None),
        tier_threshold=0,
        effect=CreateTokenPerMulticoloredPermanent(
            token_printing=<Robot 2/2 tapped>,
        ),
    ),
    TriggeredAbility(
        event=Event.ATTACKS,
        predicate=IsSelf(subject=None),
        tier_threshold=0,
        effect=DrawCardPerMulticoloredPermanent(),
    ),
)
static_abilities=()
activated_abilities=()
```

All five carriers ride the Phase 1 + Phase 2 substrate UNCHANGED on
their non-trigger axes — same `station_threshold` `Option<i32>`, same
`stationed_keywords` `Vec<String>`, same parse + admit + bridge round-
trip — and add a closed set of trigger families that fall into the
SAME `_VALID_SPACECRAFT_TIER_TRIGGER_EVENTS` table the
`spacecraft_builder.py:_VALID_SPACECRAFT_TIER_TRIGGER_EVENTS` claims
(verified at `src/mtg_bot/cards/parser/spacecraft_builder.py:250-258`).

### 1.3 Trigger family grouping

The 5 carriers' 7 total `TriggeredAbility` entries group into **4
trigger families** (each is an `Event` + a predicate scope):

| Trigger family | Cards | Event | Predicate scope | Dispatch site (Rust) | Dispatch site (Python) | `tier_threshold` |
|---|---|---|---|---|---|---:|
| **ETB self** | Larval Scoutlander (3A) + Infinite Guideline Station (3C) | `Event::Enters` | `Predicate::SourceIsSelf` | `state_ops_resolve.rs:917-967` (`dispatch_event(Event::Enters, ...)`) | `actions.py::dispatch_event` | 0 |
| **ATTACKS self** | Sledge-Class Seedship (3B) + Entropic Battlecruiser mode-0 (3C) + Infinite Guideline Station ATTACKS (3C) | `Event::Attacks` | `Predicate::SourceIsSelf` | `state_ops_combat.rs:1730` (per-attacker ATTACKS dispatch) | `combat._fire_attacks_triggers` | 0 |
| **BEGINNING_OF_COMBAT, your turn** | Synthesizer Labship (3C) | `Event::BeginningOfCombat` | `Predicate::ControlledByYou` | `advance_phase` step-event dispatch | `turn._fire_phase_step_triggers` | **2** |
| **DISCARDS_CARD, opponent** | Entropic Battlecruiser mode-1 (3C) | `Event::DiscardsCard` | `Predicate::ControlledByOpponent` | `state_ops_resolve.rs::dispatch_event` (per-card discard dispatch) | `turn.fire_opponent_discards_triggers` | **1** |

**Phase 3A** is exactly the single-card ETB-self family at
`tier_threshold=0` — no charge-counter complication, no multi-trigger
composition. **Phase 3B** is exactly the single-card ATTACKS-self
family at `tier_threshold=0` — same trigger-firing simplicity. **Phase
3C** lands the substrate work for `TriggeredAbility.tier_threshold`
(both Rust slot and trigger-firing-time gate dispatch), then admits
the 3 remaining carriers one at a time on per-Effect-class cycles.

The 4-trigger-family classification at §1.3 confirms the 5 carriers'
all-trigger-family events are **already Rust-wired** as `Event::*`
enum members (verified `rust/src/cards.rs:8734-9014`):
* `Event::Enters` — ETB dispatch live in production since Slice 1.
* `Event::Attacks` — Slice 7 wires this; per-attacker push site at
  `state_ops_combat.rs:1730`.
* `Event::BeginningOfCombat` — round-14 PHASE_STEP event bridge,
  fired by `advance_phase` when the new phase is `PHASE_BEGIN_COMBAT`.
* `Event::DiscardsCard` — MMM Pin 2 (11th Rust slice), per-card
  discard dispatch live.

**No new Rust `Event::*` variant is needed.** The Phase-3 substrate is
purely (a) the new `TriggeredAbility.tier_threshold: i32` field +
trigger-firing-time gate, (b) the 5 new `Effect::*` variants + their
resolve arms, and (c) the per-card admit-predicate widens.

### 1.4 Why the substrate scope is larger than Phase 2

Per the §1.2 walk, the substrate requires the following components —
each card adds **at most one new Effect-class slice**, and `Triggered
Ability.tier_threshold` lands once (in Phase 3C) and is then reused
unchanged across both tier-gated triggers (Synthesizer Labship,
Entropic Battlecruiser mode-1):

1. **`TriggeredAbility.tier_threshold` Rust slot + dispatch gate** —
   a new `pub tier_threshold: i32` field on the Rust
   `TriggeredAbility` struct (`rust/src/cards.rs:9725-9748`, sibling
   of `ActivatedAbility.tier_threshold` at
   `rust/src/cards.rs:10264`), parsed at
   `rust/src/cards.rs:15059-16634`, defaulting to 0 (always-fire). The
   trigger-firing-time gate at `state_ops_resolve.rs:927-951` adds a
   sibling check to the existing `ability.once_per_turn` walk:
   `if ability.tier_threshold > 0 && source.charge_counters <
   ability.tier_threshold { continue; }` — sibling of the Python gate
   at `turn.should_fire_trigger:469-473`. Phase 3C ports this once.
2. **5 new Rust `Effect::*` variants + resolve arms** — one per
   card-class slice. Each lands the `Effect::*` enum extension,
   the `parse_effect` arm, the `to_pydict` arm, the `apply_effect`
   resolve arm, plus the cross-engine bridge encode/decode arms. The
   only carry-over between cards is the `EachOpponentDiscardsOrLoses
   Life` widen, which composes with the existing
   `Effect::EachOpponentDiscards` resolve at
   `state_ops_resolve.rs:6673` (sibling pattern; see §4.2 below).
3. **5 per-card admit predicates / widens** — Phase 3 either lands
   ONE general `_printing_is_bridge_phase_3_trigger_spacecraft`
   predicate parametrized over the closed set of accepted Effect
   classes (preferred, see §5.4), OR 5 sibling predicates (rejected
   — bifurcates the no-silent-auto-grow walk). Either way each
   card's admit-gate FLIP is a separate cycle.

Components (1)-(2) are the new Rust substrate; (3) is the
bridge-widen / admit-route work each card needs. By comparison, Phase
2 added 0 new Action variants + 1 new dispatcher arm + 1 admit
sibling; Phase 3 adds 0 new Action variants + 1 new struct field +
trigger-firing gate + 5 new Effect resolve arms + 1 generalized admit
predicate.

### 1.5 Calibration against Phase 1 + Phase 2 + sibling phases

Phase 1 took 4 cycles to ship one card (Galvanizing Sawship). Phase 2
took 3 cycles to ship one card (Lumen-Class Frigate). Phase 3 ships
**5 cards** across **3 sub-phases** (~6-10 cycles total):

* **Phase 3A — Larval Scoutlander, ~2 cycles.** No new substrate;
  just 1 new Effect class + 1 admit-route + 1 probe.
* **Phase 3B — Sledge-Class Seedship, ~2 cycles.** No new substrate;
  just 1 new Effect class + 1 admit-route + 1 probe. Sibling-narrow
  precedent of Phase 3A.
* **Phase 3C — `TriggeredAbility.tier_threshold` substrate + 3
  cards (Synthesizer Labship + Entropic Battlecruiser + Infinite
  Guideline Station), ~4-6 cycles.**
  * Cycle 1 — Rust `TriggeredAbility.tier_threshold` slot landing +
    trigger-firing-time gate at `state_ops_resolve.rs` +
    `state_ops_combat.rs` (per-attacker ATTACKS dispatch site) +
    parser whitelist + bridge round-trip. Substrate-only; the 3 C3
    target cards STAY DECLINED post-Cycle-1.
  * Cycle 2 — `Effect::TargetArtifactBecomesCreatureUEOT` +
    Synthesizer Labship FLIP + probe.
  * Cycle 3 — `Effect::EachOpponentDiscardsOrLosesLife` widen +
    Entropic Battlecruiser FLIP + probe (both triggers in one cycle
    because the second trigger's effect class is the already-Rust-
    supported `TargetPlayerLosesLife`; only the mode-0 widen is new).
  * Cycle 4 — `Effect::CreateTokenPerMulticoloredPermanent` +
    `Effect::DrawCardPerMulticoloredPermanent` + Infinite Guideline
    Station FLIP + probe. Both triggers live in one cycle because
    the two Effect classes share the same "count multicolored
    permanents the active player controls" predicate primitive (the
    only delta is the per-Effect arm — token spawn vs draw).
  * **Total Phase 3C: ~4 cycles** if every per-card slice closes in
    one cycle each. Spill to ~6 cycles if Infinite Guideline Station's
    multi-effect composition or the `CreateTokenPerMulticolored
    Permanent` token-printing emit / consume axis surfaces a new
    bridge complication (the EoE Robot token is bridge-supported
    today, but the per-trigger emit count varies with the controller's
    multicolored-permanent count; verify-first walk at Cycle 4's
    first hour will lock the choice).

**Estimated total: ~6-10 cycles for Phase 3** (lower bound assumes
every per-card cycle closes in one slice; upper bound budgets a 2-cycle
spill across Phase 3C for any Effect-class composition complication).

## 2. Sub-shape C scope — 5 cards, the trigger-bearing Spacecraft carriers

Verified live against `OracleParserCardSource().get_printings()` at
main `086f86fc` (per the §1.2 walk + the per-card audit table inherited
from Phase 1 §2 + Phase 2 §2):

| Card | `station_threshold` | `stationed_keywords` | mana_cost | P/T | Triggers (count) | Effect classes new to Rust | tier_threshold(s) | Phase |
|---|---:|---|---|---|---:|---|---:|---|
| **Larval Scoutlander** | 7 | `{flying}` | `{2}{G}` | 3/3 | 1 (ETB) | `OptionalSacLandOrLanderForBasicLandRamp` | 0 | **3A** |
| **Sledge-Class Seedship** | 7 | `{flying}` | `{2}{G}` | 4/5 | 1 (ATTACKS) | `OptionalPutCreatureFromHandOntoBattlefield` | 0 | **3B** |
| **Synthesizer Labship** | 9 | `{flying, vigilance}` | `{U}` | 4/4 | 1 (BoC + tier=2) | `TargetArtifactBecomesCreatureUEOT` | **2** | **3C** |
| **Entropic Battlecruiser** | 8 | `{flying, deathtouch}` | `{3}{B}` | 3/10 | 2 (ATTACKS tier=0 + DISCARDS tier=1) | `EachOpponentDiscardsOrLosesLife` (mode-0; sibling-widen of existing `EachOpponentDiscards`) | 0 / **1** | **3C** |
| **Infinite Guideline Station** | 12 | `{flying}` | `{W}{U}{B}{R}{G}` | 7/15 | 2 (ETB tier=0 + ATTACKS tier=0) | `CreateTokenPerMulticoloredPermanent` + `DrawCardPerMulticoloredPermanent` | 0 / 0 | **3C** |

**Phase-3 admit total: 5 cards** (Larval Scoutlander, Sledge-Class
Seedship, Synthesizer Labship, Entropic Battlecruiser, Infinite
Guideline Station). The 1 deferred Spacecraft (The Eternity Elevator)
positively rejects via Phase 3's admit predicate's `station_threshold
is None` short-circuit.

**Why exactly these 5 are sub-shape C.** Per the live print walk, the
sub-shape C positive criteria, all verified for each card at live
HEAD:

- The printing carries `"Spacecraft" in subtypes`.
- `station_threshold` is set to a positive int (7-12 across the 5 cards).
- `stationed_keywords` non-empty, all entries in
  `trajectory.py::_SAFE_KEYWORDS` (`flying`, `vigilance`, `deathtouch`
  are all in the safe set verified at Phase 1 §2 + Phase 2 §2;
  Entropic Battlecruiser's `deathtouch` is Rust-first-class via the
  CR 702 keyword combat fold).
- `triggered_abilities` has 1 or 2 entries; every entry's `event` +
  `predicate` is in
  `_VALID_SPACECRAFT_TIER_TRIGGER_EVENTS` (see
  `spacecraft_builder.py:250-258` — `ENTERS+IsSelf`,
  `ATTACKS+IsSelf`, `DISCARDS_CARD+Controlled(OPPONENT)`,
  `YOU_ATTACK+Controlled(YOU)`, `BEGINNING_OF_COMBAT+Controlled(YOU)`).
- Every entry's `effect` is in the closed Phase-3 admit set
  (`OptionalSacLandOrLanderForBasicLandRamp`,
  `OptionalPutCreatureFromHandOntoBattlefield`,
  `TargetArtifactBecomesCreatureUEOT`,
  `EachOpponentDiscardsOrLosesLife`,
  `TargetPlayerLosesLife`,
  `CreateTokenPerMulticoloredPermanent`,
  `DrawCardPerMulticoloredPermanent`).
- `static_abilities == ()`, `activated_abilities == ()`,
  `spell_effect is None`, no `room_halves`, no `loyalty`, no
  `dynamic_pt_formula`, no `ward_cost`, no `cost_reductions`, no
  `external_cost_reductions`, no `warp_cost`, no `kicker_cost`, no
  `impending_cost`, no `keywords` baseline.
- `grants_toughness_as_station_power_for_creatures_you_control=False`
  (Tapestry-Warden asymmetry pin from Phase 1 §3.4 / Phase 2 §3.5
  stays positive-reject).

The ONLY blocking features on the 5 cards beyond the Phase-1 + Phase-2
substrate are: (a) the new Effect classes their triggers carry, and
(b) the `tier_threshold>=1` gate on 2 of the 7 trigger entries. Both
are addressable through the closed-list Effect-class admit predicate +
one new `TriggeredAbility.tier_threshold` Rust slot.

### 2.1 Per-card Phase + sub-shape selection rationale

* **Larval Scoutlander → Phase 3A** (single-trigger ETB, tier=0).
  The simplest possible trigger-bearing Spacecraft. Reuses the
  existing `Effect::SearchLibraryForBasicLandTapped` resolve +
  `Effect::Sacrifice` resolve primitives the way Carrier-AA Phase 2b
  already does. ETB dispatch is the most mature trigger family in
  Rust (production since Slice 1). NO new substrate beyond the new
  `Effect::OptionalSacLandOrLanderForBasicLandRamp` Effect variant.
* **Sledge-Class Seedship → Phase 3B** (single-trigger ATTACKS,
  tier=0). The simplest ATTACKS-trigger Spacecraft. The
  `Effect::OptionalPutCreatureFromHandOntoBattlefield` resolve
  composes the existing `Effect::Sacrifice` + `Effect::Reveal*` /
  hand-pick decision dispatch. ATTACKS dispatch is Rust-mature
  (Slice 7). NO new substrate beyond the new Effect variant.
* **Synthesizer Labship → Phase 3C** (tier-gated trigger; tier=2;
  BEGINNING_OF_COMBAT trigger). Pulls in the trigger-firing-time
  `tier_threshold` Rust slot AND a new Effect class
  (`TargetArtifactBecomesCreatureUEOT`). The substrate landing is
  pre-required.
* **Entropic Battlecruiser → Phase 3C** (composed two-trigger; one
  always-fires, one tier=1; DISCARDS_CARD trigger). Pulls in the
  same substrate as Synthesizer Labship. The Effect-class delta is
  the `EachOpponentDiscardsOrLosesLife` mode-0 widen of the
  Rust-supported `EachOpponentDiscards`.
* **Infinite Guideline Station → Phase 3C** (composed two-trigger,
  both tier=0; ETB + ATTACKS triggers; multi-colored permanent
  count). Pulls in TWO new Effect classes
  (`CreateTokenPerMulticoloredPermanent` +
  `DrawCardPerMulticoloredPermanent`) that share a common
  "multicolored-permanent-count" predicate primitive. The bookkeeping
  fit-out for the token-spawn arm reuses Robot 2/2's existing token
  printing bridge support (Phase 1 cross-ref).

The Phase 3A → 3B → 3C ordering is **strictly enforced** by the
`tier_threshold` Rust slot dependency at Phase 3C. Phase 3A + 3B may
run in parallel (no shared Rust slice; both add a single new
`Effect::*` variant on disjoint resolve sites). Phase 3C is sequential
internal to itself (substrate Cycle 1 must close before the per-card
FLIPs).

## 3. Out-of-scope (deferred to Phase 4)

### 3.1 Activated-ability Spacecraft carriers — Phase 4 (The Eternity Elevator)

The Eternity Elevator (Phase 1 §3.3 reference, Phase 2 §3.2 reference)
is `station_threshold=None` + 2× activated abilities; Phase 4 depends
on Worker B's parallel Carrier-AA Phase 1+ landing the non-token-AA
bridge round-trip + a new `AddChargeCounterManaOfChosenColor` Effect
class. Sequencing unchanged from Phase 1 + Phase 2.

### 3.2 Mixed-shape carriers — out of substrate (not in pool today)

A future Spacecraft that combined a static-anthem rider with a
triggered ability would compose Phase 2's static-anthem piece + a
Phase-3 trigger piece. The Phase 2 §3.3 composed-shape no-silent-
auto-grow pin (composed at Phase 2 Cycle 3 at `tests/test_lumen_
class_frigate_parity.py::test_phase_2_predicate_declines_synthetic_
composed_shape_spacecraft`) already pins Phase 2's admit predicate's
`triggered_abilities` short-circuit. Phase 3's admit predicate carries
the **sibling pin** — a synthetic composed-shape carrier with BOTH a
trigger AND a static is declined (Phase 3's
`if printing.static_abilities: return False` clause; see §5.4 below).
No EoE printing carries the composed shape today.

### 3.3 The Tapestry Warden asymmetry — unchanged from Phase 1 §3.4 / Phase 2 §3.5

Phase 3's admit predicate positively rejects
`grants_toughness_as_station_power_for_creatures_you_control=True`.
No EoE Spacecraft carries the flag; Tapestry Warden itself is not a
Spacecraft. Future-proof guard preserved from Phase 1 + 2.

### 3.4 The Eternity Elevator-shaped multi-AA Spacecraft + The Eternity Elevator-shaped non-animating Spacecraft

Both are Phase 4. Phase 3's admit predicate's `if printing.
activated_abilities: return False` clause + `if printing.station_
threshold is None: return False` clause positively rejects The
Eternity Elevator.

### 3.5 Tier-gated activated-ability Spacecraft carriers — unchanged from Phase 1 §3.3

Phase 4 only. The Phase-3 admit predicate's `if printing.activated_
abilities: return False` clause positively rejects any tier-gated AA
carrier (including The Eternity Elevator's `AddManaToPool` +
`AddChargeCounterManaOfChosenColor` activations).

### 3.6 Self-static-keyword grants ("stationed creature gets X") — engine-side substrate gap (Phase N)

`spacecraft_builder.py:60-71` documents the engine-side gap for
tier-gated SELF-scope static keyword grants — `StaticAbility.applies_to`
requires the target be a creature now, and every real EoE printing's
lower-tier keyword line falls below the Station threshold (i.e. while
the Spacecraft is still an artifact, not a creature), so a self-scoped
`StaticAbility` with `tier_threshold=N` would never fire correctly.
No EoE Spacecraft carries the multi-tier-keyword shape today; deferred
to a future engine-side widen of `stationed_keywords` to support
tier-keyed keyword sets.

## 4. Rust-side spec — the new `TriggeredAbility.tier_threshold` slot + 5 new `Effect::*` variants

### 4.1 Phase 3C Cycle 1 — `TriggeredAbility.tier_threshold` substrate

**File:** `rust/src/cards.rs` — extend `pub struct TriggeredAbility`
at line 9725-9748 with a new field:

```rust
pub struct TriggeredAbility {
    pub event: Event,
    pub predicate: Predicate,
    pub effect: Effect,
    pub once_per_turn: bool,
    // *** Phase 3C Cycle 1 new field ***
    /// EoE Spacecraft tier gate — source must have at least
    /// `tier_threshold` charge counters for this trigger to fire.
    /// Mirrors Python's `TriggeredAbility.tier_threshold: int = 0`
    /// (`src/mtg_bot/cards/base.py`). Default 0 = always fire
    /// (back-compat with every pre-Phase-3 trigger).
    pub tier_threshold: i32,
}
```

**File:** `rust/src/cards.rs` — extend the `parse_triggered_ability`
arm (line ~16634) to read the new key:

```rust
let tier_threshold = match dict.get_item("tier_threshold")? {
    None => 0,
    Some(v) => v.extract::<i32>().map_err(|_| {
        PyValueError::new_err(
            "triggered_ability.tier_threshold must be a non-negative int",
        )
    })?,
};
// validate non-negative; raise on negative

Ok(TriggeredAbility {
    event,
    predicate,
    effect,
    once_per_turn,
    tier_threshold,
})
```

**File:** `rust/src/cards.rs` — extend `to_pydict` (line ~15059) to
emit the new key only when `tier_threshold != 0` (back-compat: every
pre-Phase-3 trigger emits the field at its default 0, identical to
pre-substrate emit). Mirror the `condition_args` /
`station_threshold` back-compat emit pattern already in production.

**File:** `rust/src/state_ops_resolve.rs` — extend the trigger-firing-
time dispatch at line 927-951 with a sibling gate to
`ability.once_per_turn`:

```rust
for (ability_index, ability) in
    printing.triggered_abilities.iter().enumerate()
{
    if ability.event != event {
        continue;
    }
    if !ability.predicate.matches(state, *source_id, subject_id) {
        continue;
    }
    // Once-per-turn gate (unchanged from pre-Phase-3).
    if ability.once_per_turn
        && state.triggered_this_turn
            .contains(&(*source_id, ability_index as u32))
    {
        continue;
    }
    // *** Phase 3C Cycle 1 new gate ***
    if ability.tier_threshold > 0 {
        // Resolve the SOURCE GameObject (which is on bf) and
        // compare its charge_counters to the threshold. Mirrors
        // Python's `should_fire_trigger` at `turn.py:469-473`.
        let source_obj = state.battlefield.iter()
            .find(|o| o.id == *source_id);
        match source_obj {
            Some(s) if s.charge_counters >= ability.tier_threshold => {}
            _ => continue,
        }
    }
    firings.push((
        *source_id,
        *source_controller,
        ability_index as u32,
        ability.effect.clone(),
        ability.once_per_turn,
    ));
}
```

**File:** `rust/src/state_ops_combat.rs` — the per-attacker ATTACKS
trigger dispatch site at line 1730 routes through the same
`dispatch_event(Event::Attacks, ...)` chokepoint at
`state_ops_resolve.rs:917-967`, so the gate at §4.1 applies UNCHANGED
to the ATTACKS trigger firings. No sibling edit needed at the
ATTACKS site.

**File:** `rust/src/state_ops_steps.rs` — the BEGINNING_OF_COMBAT
phase-step dispatch routes through `dispatch_event(Event::Beginning
OfCombat, ...)`, again gated by §4.1. Same for `Event::DiscardsCard`
fires (Entropic Battlecruiser's mode-1 trigger).

### 4.2 Phase 3A — `Effect::OptionalSacLandOrLanderForBasicLandRamp`

**File:** `rust/src/cards.rs` — new `Effect::*` variant in the enum
at line ~1189 (sibling of `TargetPlayerLosesLife`). The Python
class signature at `effects/combinators.py:699` is:

```python
@dataclass(frozen=True)
class OptionalSacLandOrLanderForBasicLandRamp(Effect):
    """Sacrifice a Land or Lander you control: search your library
    for a basic land, put it onto the battlefield tapped, then
    shuffle. Optional."""
    land_count: int = 1  # Larval Scoutlander prints land_count=2
```

The Rust variant:

```rust
Effect::OptionalSacLandOrLanderForBasicLandRamp { land_count: i32 }
```

**Resolve arm:** sibling of the existing `Effect::SearchLibraryFor
BasicLandTapped` resolve at `state_ops_resolve.rs` (round-23 +
Carrier-AA Phase 2b extension at `03fdc3e6`). The resolve dispatch
follows the Phase 2b precedent:

1. Source-controller resolution (mirrors `EachOpponentDiscards`).
2. Optional decision-point dispatch — the controller chooses whether
   to fire the ramp. If declined, the Effect silently resolves with
   no further side effect. (Mirrors Python's `OptionalSacLandOrLander
   ForBasicLandRamp.resolve` decision dispatch.)
3. If fired: present a target-Land-or-Lander-you-control fan-out at
   `state_ops_legal.rs` (sibling of the Carrier-AA Phase 2a
   `ReturnTargetLandFromGraveyardToHand` fan-out at line 3408-3505;
   here the target pool is `state.battlefield` filtered for
   `(card_types.contains("Land") OR subtypes.contains("Lander"))
   AND controller == source_controller`).
4. Pre-commit validation: `target_id` is in the activator's
   battlefield + the targeted permanent's Land-or-Lander predicate
   holds. (Sibling of the `ReturnTargetLandFromGraveyardToHand`
   validation at `state_ops_actions.rs::is_return_land_from_gy_effect`
   apply-time branch.)
5. Sacrifice the target (sibling of `Effect::Sacrifice` resolve
   site).
6. Search the library for `land_count` basic Land cards, put each
   onto the battlefield tapped (sibling of `Effect::SearchLibraryFor
   BasicLandTapped` resolve site; loop `land_count` times).
7. Shuffle the library.

### 4.3 Phase 3B — `Effect::OptionalPutCreatureFromHandOntoBattlefield`

**File:** `rust/src/cards.rs` — new unit `Effect::*` variant at the
enum. The Python class signature at `effects/combinators.py:205` is:

```python
@dataclass(frozen=True)
class OptionalPutCreatureFromHandOntoBattlefield(Effect):
    """You may put a creature card from your hand onto the
    battlefield."""
```

The Rust variant: `Effect::OptionalPutCreatureFromHandOntoBattle
field` (unit; no riders).

**Resolve arm:** sibling of `Effect::PutBasicLandFromHandOntoBattle
fieldTapped` resolve at `state_ops_resolve.rs:22920` (Carrier-AA
Phase 2b at `03fdc3e6`). The resolve dispatch:

1. Source-controller resolution.
2. Optional decision-point dispatch — the controller chooses whether
   to fire the put-from-hand. If declined, silent no-op resolve.
3. If fired: target-from-hand fan-out at `state_ops_legal.rs`
   (sibling of the put-basic-land hand search; here the predicate
   widens to `card_types.contains("Creature")`).
4. Pre-commit validation: `target_id` is in the activator's hand +
   the targeted card's Creature predicate holds.
5. Reserve ETB timestamp; move hand → battlefield (NOT tapped — the
   put-from-hand convention is to enter UNTAPPED unless the printed
   text specifies otherwise; the Sledge-Class Seedship printed text
   is "put a creature card from your hand onto the battlefield"
   without a "tapped" rider). Compare Phase 2b's tapped emit.
6. `pending_etb_dispatches.push(entered_id)` — ETB queue per the
   established Phase 2b precedent at
   `state_ops_resolve.rs:15406`.

### 4.4 Phase 3C — `Effect::TargetArtifactBecomesCreatureUEOT`

**File:** `rust/src/cards.rs` — new variant.

```rust
Effect::TargetArtifactBecomesCreatureUEOT {
    power: i32,
    toughness: i32,
    granted_keywords: Vec<String>,
}
```

The Python class signature at `effects/generic/become_type.py:36`:

```python
@dataclass(frozen=True)
class TargetArtifactBecomesCreatureUEOT(Effect):
    power: int
    toughness: int
    granted_keywords: frozenset[str]
```

Synthesizer Labship emits `power=2, toughness=2, granted_keywords=
{"flying"}` per the §1.2 walk.

**Resolve arm:** sibling of `Effect::BecomesLandCreatureUEOT` resolve
+ the UEOT P/T-set substrate already wired (sibling pattern as
Carrier-AA Phase 3C `BecomesCopyOfTargetLand` per
`CARRIER_AA_SUBSTRATE_PHASE_3_DESIGN.md` §4.3). The resolve
dispatch:

1. Source-controller resolution.
2. Target-artifact-you-control fan-out at `state_ops_legal.rs`
   (sibling of the AA target-fan-out shape; target predicate:
   `card_types.contains("Artifact") AND controller == source_controller`).
3. Pre-commit validation.
4. Apply UEOT modifier (sibling of the existing `UEOT_PT_OVERRIDE`
   apply primitive at `state_ops_combat.rs`); the modifier is
   layer-7B "set P/T to N/N" + layer-6 "gains keywords <K>" combined
   per CR-613 layer-7 stacking. Cleanup-step drains the UEOT
   modifier per CR 514.2.

### 4.5 Phase 3C — `Effect::EachOpponentDiscardsOrLosesLife` widen of `EachOpponentDiscards`

**File:** `rust/src/cards.rs` — Phase 3C may either:

* (a) **Widen** the existing `Effect::EachOpponentDiscards { count }`
  variant into a richer enum carrying an `if_cant_lose_life: i32`
  rider — bumps the variant shape to `Effect::EachOpponentDiscards
  OrLosesLife { count: i32, life_if_cant: i32 }`, OR
* (b) **Add** a fresh sibling variant `Effect::EachOpponentDiscards
  OrLosesLife { count: i32, life_if_cant: i32 }` (the chosen path,
  to minimize blast radius on the existing 9 EoE production callers
  of `Effect::EachOpponentDiscards`).

**Phase 3 prefers (b).** Reasons:
1. The existing `Effect::EachOpponentDiscards` variant is referenced
   by 9 EoE production cards (`grep -c EachOpponentDiscards rust/src
   /state_ops_resolve.rs`); a shape widen would require an in-place
   default `life_if_cant=0` semantic for every legacy call site,
   raising the no-silent-auto-grow risk.
2. The two-variant split mirrors Python's two-class split
   (`EachOpponentDiscards` at `effects/generic/discard.py:132`,
   `EachOpponentDiscardsOrLosesLife` at `effects/generic/life.py:114`
   — distinct dataclasses, distinct resolve methods).
3. The bridge encode arm can route on the Python `isinstance(eff,
   EachOpponentDiscardsOrLosesLife)` branch independently of the
   existing `EachOpponentDiscards` arm.

**Resolve arm:** sibling of `Effect::EachOpponentDiscards` resolve
at `state_ops_resolve.rs:6623-6673`. The resolve dispatch:

1. Source-controller resolution.
2. For each opponent in APNAP order:
   a. If the opponent's hand is non-empty, dispatch a discard
      decision (sibling of the existing `EachOpponentDiscards`
      resolve site; player picks a card; move to graveyard; fire
      `Event::DiscardsCard` for that opponent + the discarded card).
   b. If the opponent's hand IS empty, the alternative branch fires:
      the opponent loses `life_if_cant` life. (Mirrors Python's
      `EachOpponentDiscardsOrLosesLife.resolve` — for each opponent,
      if `len(p.hand) == 0`: `p.life -= self.life_if_cant`; else
      `force_discard(p, 1)`.)
3. The mode-0 trigger entrypoint Entropic Battlecruiser carries.

### 4.6 Phase 3C — `Effect::CreateTokenPerMulticoloredPermanent`

**File:** `rust/src/cards.rs` — new variant carrying the token
printing dict (token Robot 2/2):

```rust
Effect::CreateTokenPerMulticoloredPermanent {
    token_printing_id: PrintingId,  // pre-registered token printing
    tapped: bool,                   // Infinite Guideline Station's
                                    // emit is `tapped=True`
}
```

The Python class signature at `effects/generic/tokens.py:122`
carries the full `CardPrinting` instance (sibling of the existing
`Effect::CreateToken` bridge arm). The Rust mirror uses the
registered `PrintingId` lookup pattern.

**Resolve arm:** sibling of `Effect::CreateToken` resolve. Source-
controller resolution; count multicolored permanents the source
controller controls (`state.battlefield.iter().filter(|o|
o.controller == source_controller AND printing(o).mana_cost.colors().
len() >= 2).count()`); spawn `N` tokens of the registered
`token_printing_id` (sibling of the existing `CreateToken` resolve
N-fold loop; sibling-extension pattern `CreateTokenEachPlayer` uses).

### 4.7 Phase 3C — `Effect::DrawCardPerMulticoloredPermanent`

**File:** `rust/src/cards.rs` — new unit variant.

The Python class signature at `effects/generic/draw_mill.py:120`
carries no riders. The Rust mirror: `Effect::DrawCardPerMulticolored
Permanent` (unit).

**Resolve arm:** sibling of `Effect::DrawCards`. Source-controller
resolution; count multicolored permanents the source controller
controls (REUSE the predicate primitive from §4.6 — sibling-narrow
precedent); draw `N` cards (sibling of the existing `DrawCards`
resolve loop).

### 4.8 No new event-dispatch site

The 4 trigger families' Rust dispatch sites are all
production-mature (per §1.3 table). The Phase 3 substrate adds NO
new `Event::*` variant; the trigger-firing-time `tier_threshold`
gate at §4.1 plugs into ALL four sites uniformly (the centralized
`dispatch_event` chokepoint at `state_ops_resolve.rs:917-967`).

### 4.9 Existing Rust components reused unchanged

* `CardPrinting.station_threshold` / `stationed_keywords` (Phase 1).
* `Action::ActivateStation` resolver + sorcery-speed legal-action
  emitter (Phase 1).
* `is_stationed_predicate` / `is_creature_now` / effective-keyword
  fold (Phase 1).
* `static_anthem_condition_matches` `source_charge_counters_at_least`
  dispatcher arm (Phase 2) — unchanged; the Phase-3 trigger-firing
  gate is a SIBLING check at the dispatch site, not a reuse of the
  static-fold helper. The two checks share the SAME
  `charge_counters >= threshold` semantics + the SAME parse / encode
  shape (`tier_threshold: i32`) on the printing field.

## 5. Python bridge spec — bidirectional round-trip + admit predicate widen

### 5.1 Bridge dict shape (Python-side emit)

**File:** `src/mtg_bot/parity/cross_engine.py` — extend the
existing `triggered_abilities` emit at line 13678-13680 (the
`printing_dict["triggered_abilities"] = [dict(ta) for ta in
card.triggered_abilities]` path):

For each new Effect class (§4.2-§4.7), add a new branch on the
isinstance(effect, *) dispatch in `_python_ta_to_safe_dict` (sibling
of `_python_aa_to_safe_dict` per Carrier-AA Phase 2b at
`03fdc3e6`). Each new branch emits the canonical `"kind"`
discriminator + the per-Effect payload (mirroring the existing
`each_opponent_discards` / `target_player_loses_life` / etc.
patterns from §1.2-bridge-walk).

**New `tier_threshold` thread-through.** Add a new
`"tier_threshold": int` key emit on every TriggeredAbility dict
whose `tier_threshold > 0` (back-compat: omit when 0, matching the
Rust default-emit pattern). Rust parses the absent key as 0
(`parse_triggered_ability`'s `match dict.get_item("tier_threshold")`
arm in §4.1).

### 5.2 Python-side reconstruction arm

**File:** `src/mtg_bot/parity/cross_engine.py` — extend
`_ta_dict_to_python_effect` (line ~12503) with 5 new arms (sibling-
narrow per the existing `each_opponent_discards` /
`target_player_loses_life` arms):

```python
if kind == "optional_sac_land_or_lander_for_basic_land_ramp":
    return OptionalSacLandOrLanderForBasicLandRamp(
        land_count=int(eff.get("land_count", 1)),
    )

if kind == "optional_put_creature_from_hand_onto_battlefield":
    return OptionalPutCreatureFromHandOntoBattlefield()

if kind == "target_artifact_becomes_creature_ueot":
    return TargetArtifactBecomesCreatureUEOT(
        power=int(eff["power"]),
        toughness=int(eff["toughness"]),
        granted_keywords=frozenset(eff.get("granted_keywords", [])),
    )

if kind == "each_opponent_discards_or_loses_life":
    return EachOpponentDiscardsOrLosesLife(
        life_if_cant=int(eff.get("life_if_cant", 1)),
    )

if kind == "create_token_per_multicolored_permanent":
    token_printing = _rehydrate_token_printing(eff["token_printing"])
    return CreateTokenPerMulticoloredPermanent(
        token_printing=token_printing,
    )

if kind == "draw_card_per_multicolored_permanent":
    return DrawCardPerMulticoloredPermanent()
```

**`tier_threshold` thread-through.** Extend
`_ta_dict_to_python_triggered_ability` (the sibling-shaped
constructor of a `TriggeredAbility` Python instance from a bridge
dict; lives near `_ta_dict_to_python_effect`) to read the
`tier_threshold` key from the bridge dict and thread it to the
`TriggeredAbility.tier_threshold` Python slot (sibling of the
Phase-2 `tier_threshold` thread-back through `StaticAbility`).

### 5.3 New admit predicate

**File:** `src/mtg_bot/parity/trajectory.py` (sibling of Phase 1's
`_printing_is_bridge_pure_station_spacecraft` and Phase 2's
`_printing_is_bridge_phase_2_static_anthem_spacecraft`):

```python
# Phase 3 — the closed list of admitted Effect classes per the
# 5-card admit set. Each entry is a runtime class; the predicate
# below uses isinstance() against this tuple.
_PHASE_3_SPACECRAFT_TRIGGER_EFFECT_CLASSES = (
    OptionalSacLandOrLanderForBasicLandRamp,          # Larval Scoutlander
    OptionalPutCreatureFromHandOntoBattlefield,       # Sledge-Class Seedship
    TargetArtifactBecomesCreatureUEOT,                # Synthesizer Labship
    EachOpponentDiscardsOrLosesLife,                  # Entropic Battlecruiser mode-0
    TargetPlayerLosesLife,                            # Entropic Battlecruiser mode-1 (already Rust-supported)
    CreateTokenPerMulticoloredPermanent,              # Infinite Guideline Station ETB
    DrawCardPerMulticoloredPermanent,                 # Infinite Guideline Station ATTACKS
)

_PHASE_3_SPACECRAFT_TRIGGER_EVENT_SHAPES = (
    (Event.ENTERS, IsSelf()),
    (Event.ATTACKS, IsSelf()),
    (Event.DISCARDS_CARD, Controlled(by=OPPONENT)),
    (Event.BEGINNING_OF_COMBAT, Controlled(YOU)),
)

def _triggered_ability_is_phase_3_spacecraft_admitted(trig) -> bool:
    """True iff `trig` is a Phase-3 bridge-admittable Spacecraft
    trigger.

    Positive gates:
    * `trig.predicate` + `trig.event` is in the closed
      `_PHASE_3_SPACECRAFT_TRIGGER_EVENT_SHAPES` table.
    * `isinstance(trig.effect, _PHASE_3_SPACECRAFT_TRIGGER_EFFECT_CLASSES)`.
    * `trig.tier_threshold >= 0` (back-compat default; the
      per-card admit set covers tier_threshold ∈ {0, 1, 2}).
    * `trig.once_per_turn=False` (no Phase-3 carrier sets it).
    """
    ev_pred = (trig.event, trig.predicate)
    if ev_pred not in _PHASE_3_SPACECRAFT_TRIGGER_EVENT_SHAPES:
        return False
    if not isinstance(trig.effect, _PHASE_3_SPACECRAFT_TRIGGER_EFFECT_CLASSES):
        return False
    if trig.tier_threshold < 0:
        return False
    if trig.once_per_turn:
        return False
    return True


def _printing_is_bridge_phase_3_trigger_spacecraft(
    printing,
) -> bool:
    """True iff a CardPrinting is a Phase-3 bridge-supported
    trigger-bearing Spacecraft — the Phase-1 sub-shape A clauses
    EXCEPT triggered_abilities is replaced with a positive 1-or-2
    `TriggeredAbility` allowlist via
    :func:`_triggered_ability_is_phase_3_spacecraft_admitted`.

    Spacecraft Station substrate — Phase 3 (sub-shape C; spec at
    docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_3_DESIGN.md). Cards:
    Larval Scoutlander, Sledge-Class Seedship, Synthesizer Labship,
    Entropic Battlecruiser, Infinite Guideline Station.
    """
    if "Spacecraft" not in printing.subtypes:
        return False
    if printing.station_threshold is None:
        return False  # Phase 4 only (The Eternity Elevator)
    if printing.station_threshold <= 0:
        return False
    if printing.static_abilities:
        return False  # Phase 2 (Lumen-Class Frigate)
    if printing.activated_abilities:
        return False  # Phase 4 (The Eternity Elevator)
    if not printing.triggered_abilities:
        return False  # Phase-1 path covers zero-trigger
    if len(printing.triggered_abilities) > 2:
        return False  # No EoE Spacecraft carries > 2 triggers; reject as no-silent-auto-grow
    for trig in printing.triggered_abilities:
        if not _triggered_ability_is_phase_3_spacecraft_admitted(trig):
            return False
    # Carry-through Phase 1 / Phase 2 shape clauses
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
        return False  # Phase-3 carrier has empty baseline keywords
    if not printing.stationed_keywords:
        return False
    for kw in printing.stationed_keywords:
        if kw not in _SAFE_KEYWORDS:
            return False
    if printing.grants_toughness_as_station_power_for_creatures_you_control:
        return False  # Tapestry Warden flag (positive-reject)
    try:
        _parse_mana_cost_string(printing.mana_cost_str or "")
    except ValueError:
        return False
    return True
```

### 5.4 Per-sub-phase Effect-class gate

The §5.3 predicate's Effect-class allowlist is intentionally **the
union of all 5 sub-phase 3A/3B/3C Effect classes**. To keep the
admit set narrow during a sub-phase landing, the per-sub-phase
admit gate gates on the **current sub-phase's Effect-class set**:

* **Phase 3A** — admit set `{Optional SacLandOrLanderForBasicLandRamp}`
  (Larval Scoutlander only).
* **Phase 3B** — admit set Phase-3A + `{Optional PutCreatureFrom
  HandOntoBattlefield}` (Larval Scoutlander + Sledge-Class
  Seedship).
* **Phase 3C** Cycle 2 — admit set Phase-3B +
  `{TargetArtifactBecomesCreatureUEOT}` + `tier_threshold=2`
  (Synthesizer Labship).
* **Phase 3C** Cycle 3 — Phase-3C-Cycle-2 +
  `{EachOpponentDiscardsOrLosesLife, TargetPlayerLosesLife}` +
  `tier_threshold=1` (Entropic Battlecruiser).
* **Phase 3C** Cycle 4 — Phase-3C-Cycle-3 +
  `{CreateTokenPerMulticoloredPermanent,
  DrawCardPerMulticoloredPermanent}` (Infinite Guideline Station).

The per-sub-phase per-Cycle Effect-class set is encoded as a
top-of-trajectory.py constant tuple
`_PHASE_3_<sub>_<cycle>_EFFECT_CLASSES` and the predicate composes
`isinstance(effect, <ENABLED-SET>)`. Each cycle's flip extends the
enabled set by one entry.

### 5.5 Admit-predicate registration

The new Phase-3 predicate is registered as a parallel admit-disjunct
in the loader's filter at `_filter_deck_to_bridge_supported`,
sibling to the Phase-1 and Phase-2 disjuncts:

```python
existing_predicate(printing) OR
_printing_is_bridge_pure_station_spacecraft(printing) OR              # Phase 1
_printing_is_bridge_phase_2_static_anthem_spacecraft(printing) OR     # Phase 2
_printing_is_bridge_phase_3_trigger_spacecraft(printing)              # Phase 3
```

Per-cycle, the positive Phase-3 admit set grows from 1 (Phase 3A) →
2 (Phase 3B) → 3 (Phase 3C Cycle 2) → 4 (Phase 3C Cycle 3) → 5
(Phase 3C Cycle 4).

## 6. Test plan — substrate units + bridge round-trip + per-card real-EoE probes + no-silent-auto-grow

### 6.1 Phase 3C Cycle 1 — `TriggeredAbility.tier_threshold` substrate unit pins (Rust + Python)

1. **Rust `TriggeredAbility.tier_threshold` parse round-trip:**
   the registry-build path round-trips
   `tier_threshold=0/1/2/12` through `parse_triggered_ability` /
   `to_pydict`. Missing key defaults to 0. Negative value raises.
2. **Rust trigger-firing-time gate (`tier_threshold>=1` closed):**
   synthetic Spacecraft with a `tier_threshold=2` trigger; with the
   source's `charge_counters=0` AND `=1`, the dispatch site at
   `state_ops_resolve.rs:927-951` does NOT push the trigger onto
   the stack. Verify via `state.stack` byte-equal on both sides
   (Python's `should_fire_trigger` at `turn.py:469-473` matches).
3. **Rust trigger-firing-time gate (`tier_threshold` open):**
   same synthetic carrier; with the source's `charge_counters>=2`,
   the dispatch site DOES push. Verify via `state.stack` byte-equal.
4. **Back-compat — `tier_threshold=0` triggers fire unchanged:**
   every pre-Phase-3 trigger (round-1's ETB triggers, every
   currently-PROBED Spacecraft Phase-1 carrier) emits
   `tier_threshold=0` and fires unchanged. Pin via a real-EoE
   non-Phase-3 carrier (e.g., Knight Luminary's ETB warp trigger)
   carrier under both engines on the trigger fire site.
5. **Bridge round-trip — `tier_threshold` thread-through:** a
   CardDef carrying a `TriggeredAbility` with
   `tier_threshold=2` round-trips through both
   `_python_ta_to_safe_dict` and `_ta_dict_to_python_triggered_
   ability` bit-identical to the parser SoT.
6. **No `Effect::*` widen this Cycle.** Cycle 1 is substrate-only;
   the 3 Phase 3C target cards STAY DECLINED at the admit gate
   post-Cycle-1 (substrate-only invariant pin per the Phase-1
   precedent at `tests/test_spacecraft_phase_1_substrate_cycle_1.py`).

### 6.2 Phase 3A — `Effect::OptionalSacLandOrLanderForBasicLandRamp` + Larval Scoutlander FLIP

7. **Rust Effect parse + round-trip + resolve pins** for the new
   variant (sibling of Carrier-AA Phase 2b's pin set; happy path
   + silent-fizzle-no-Land-or-Lander + non-Land-non-Lander filter
   + sacrifice + search-library byte-equal).
8. **Python admit predicate** — `_printing_is_bridge_phase_3_
   trigger_spacecraft(<live Larval Scoutlander>)` returns `True`.
   Every other live Spacecraft printing returns `False` per the
   §6.4 decline-set check.
9. **Per-card real-EoE probe (Larval Scoutlander)** —
   `tests/test_larval_scoutlander_parity.py` (registered in
   `scripts/measure_pool_parity.py::PROBE_MODULES`) drives the
   actual live printing through:
   - **Scenario A — Cast Larval Scoutlander into an empty
     battlefield + no Lands or Landers in play:** assert the ETB
     trigger queues + resolves; assert the optional-decline path
     produces byte-equal post-state to the no-fire baseline.
   - **Scenario B — Cast Larval Scoutlander into an empty
     battlefield + 1 Forest + 1 Lander token in play:** assert
     the controller's choice fan-out at `state_ops_legal.rs`
     produces a 2-target choice set; assert the optional-accept
     +sac-Forest path produces +2 basic-land-tapped on the bf
     (matching the live printing's `land_count=2`) + 1 fewer Forest
     + 1 more tapped basic Land; byte-equal post-state to Python.

### 6.3 Phase 3B — `Effect::OptionalPutCreatureFromHandOntoBattlefield` + Sledge-Class Seedship FLIP

10. **Rust Effect parse + round-trip + resolve pins** for the new
    variant (sibling of Phase 3A).
11. **Python admit predicate** — `_printing_is_bridge_phase_3_
    trigger_spacecraft(<live Sledge-Class Seedship>)` returns
    `True`. Larval Scoutlander STILL admits (Phase-3A
    non-regression).
12. **Per-card real-EoE probe (Sledge-Class Seedship)** —
    drives the actual live printing through:
    - **Scenario A — Sledge-Class Seedship on bf, no creatures in
      hand:** declare Seedship as attacker; assert the ATTACKS
      trigger queues + resolves; assert optional-decline path
      produces no-op; assert optional-accept-then-no-targets path
      silent-fizzles (no creature card in hand to put onto bf;
      mirrors Phase 3A's no-Land-or-Lander silent-fizzle line).
    - **Scenario B — Sledge-Class Seedship on bf + a Grizzly Bears
      in hand:** declare Seedship as attacker; assert
      optional-accept path puts Grizzly Bears onto bf untapped
      (NOT tapped, per the printed text); assert Grizzly Bears
      receives a fresh ETB timestamp + the
      `pending_etb_dispatches` queue fires its own ETB-trigger
      slot for the entering Grizzly Bears (Grizzly Bears has none;
      sibling pattern hand-load + zone-move).

### 6.4 Phase 3C — `TriggeredAbility.tier_threshold` substrate + 3-card FLIP

13. **Substrate-only invariant pin** — Synthesizer Labship,
    Entropic Battlecruiser, Infinite Guideline Station STAY
    DECLINED at the admit gate post-Cycle-1 (sibling of the
    Phase-1 + Phase-2 invariant pin pattern). After Cycle 2 FLIP,
    invert in-place to Synthesizer-Labship-now-admits-post-Cycle-2;
    Entropic Battlecruiser STAYS DECLINED until Cycle 3; Infinite
    Guideline Station STAYS DECLINED until Cycle 4.
14. **`Effect::TargetArtifactBecomesCreatureUEOT`** (Cycle 2 — for
    Synthesizer Labship). Rust + Python bridge + admit + per-card
    probe:
    - **Synthesizer Labship probe Scenario A — tier-gate-closed
      (charge=0/1):** assert the BEGINNING_OF_COMBAT trigger does
      NOT fire (Rust gate at §4.1; Python's
      `should_fire_trigger`); no UEOT artifact-to-creature
      transformation.
    - **Synthesizer Labship probe Scenario B — tier-gate-open
      (charge>=2) + 1 own artifact on bf:** assert the trigger
      fires; assert the target-fan-out is the activator's
      artifact pool; assert the artifact becomes a 2/2 flying
      creature UEOT; assert the layer-7B P/T set + layer-6 flying
      grant compose into the post-state byte-equal on both
      engines; assert the UEOT modifier drains at cleanup step.
15. **`Effect::EachOpponentDiscardsOrLosesLife` widen** (Cycle 3 —
    for Entropic Battlecruiser). Rust + Python bridge + admit +
    per-card probe:
    - **Entropic Battlecruiser probe Scenario A — ATTACKS-trigger
      (mode-0, tier=0):** declare Entropic Battlecruiser as
      attacker; assert the mode-0 trigger fires unconditionally;
      assert each opponent discards a card OR loses 3 life on
      empty-hand; byte-equal on both engines for the discard
      decision + life-loss alternative.
    - **Entropic Battlecruiser probe Scenario B —
      DISCARDS_CARD-trigger (mode-1, tier=1):** with
      `charge_counters>=1`, force an opponent discard (via the
      mode-0 from the same source OR via an external discard
      effect); assert the mode-1 trigger fires for each opponent
      discard (per-card dispatch); assert `TargetPlayerLosesLife
      (amount=3)` resolves with the discarding-player pre-wired
      target.
    - **Entropic Battlecruiser probe Scenario C — mode-1
      tier-gate-closed (charge=0):** force an opponent discard;
      assert the mode-1 trigger does NOT fire (sibling of pin
      6.1.2).
16. **`Effect::CreateTokenPerMulticoloredPermanent` +
    `Effect::DrawCardPerMulticoloredPermanent`** (Cycle 4 — for
    Infinite Guideline Station). Rust + Python bridge + admit +
    per-card probe:
    - **Infinite Guideline Station probe Scenario A — Cast +
      ETB:** with 0 multicolored permanents the controller
      controls, ETB trigger fires; resolve creates 0 tokens; pin
      the silent-fan-out semantics. With N multicolored permanents
      the controller controls (synthetic Boros Reckoner + Maelstrom
      Wanderer); ETB resolve creates N tokens of Robot 2/2 tapped.
    - **Infinite Guideline Station probe Scenario B — Stationed +
      ATTACKS:** at `charge_counters>=12` (Spacecraft now a
      creature), declare Infinite Guideline Station as attacker
      WITH 2 multicolored permanents the controller controls;
      assert the ATTACKS trigger fires + draws 2 cards; pin the
      MultiColored-count primitive byte-equal on both engines.

### 6.5 Bridge round-trip pins

17. **Synthetic Phase-3 carrier round-trip** (one per cycle):
    a DeckSpec with a synthetic CardDef carrying each cycle's
    target trigger shape: build Rust state via
    `build_rust_state` → fingerprint byte-equal across engines
    pre-trigger.
18. **Action-set invariance pin (per cycle):** both engines'
    `legal_actions` emit the SAME set (and positional order) of
    legal actions across the trigger-fire boundary; the action
    set does NOT diverge from the Phase-1 + Phase-2 axis on
    any pre-Phase-3 Action.

### 6.6 Decline-set bench check (no-silent-auto-grow)

19. **Per-cycle decline-set walk** — parametrized over the
    not-yet-admitted Phase-3 Spacecraft. Each cycle's flip
    INVERTS the cycle's target card's decline pin; the others
    STAY DECLINED. After Phase 3 Cycle 4 (final), the only
    Spacecraft remaining DECLINED is The Eternity Elevator.
20. **Subsystem-attribution pin (final):** exactly 5 EoE
    printings pass `_printing_is_bridge_phase_3_trigger_
    spacecraft` (Larval Scoutlander, Sledge-Class Seedship,
    Synthesizer Labship, Entropic Battlecruiser, Infinite
    Guideline Station) — the guardrail's positive set is
    exhaustive for Phase 3.
21. **Decline-set bench check** — with the EoE deck pool
    loaded, confirm the bench's loader-side filter admits +5
    cards (the Phase-3 admit set) over the Phase-2 post-PROBE
    baseline, with 0 spillover into The Eternity Elevator.
22. **No-silent-auto-grow pin (composed-shape):** with a
    synthetic Spacecraft carrying BOTH a Phase-2 static-anthem
    AND a Phase-3 trigger (composed shape per §3.2), confirm
    `_printing_is_bridge_phase_3_trigger_spacecraft` returns
    `False` (the predicate's `if printing.static_abilities:
    return False` clause). Pins the predicate against
    accidental admission of any future composed-shape
    printing.
23. **No-silent-auto-grow pin (extra Effect class):** a
    synthetic Spacecraft carrying a trigger whose Effect class
    is NOT in `_PHASE_3_SPACECRAFT_TRIGGER_EFFECT_CLASSES`
    (e.g., a raw `DrawCards(count=3)` trigger) is rejected.
24. **No-silent-auto-grow pin (extra trigger count):** a
    synthetic Spacecraft carrying 3+ triggers is rejected
    (the `len > 2` short-circuit; sibling of Phase 2's
    single-static gate).
25. **No-silent-auto-grow pin (Tapestry-Warden flag):**
    `_printing_is_bridge_phase_3_trigger_spacecraft` on a
    synthetic Spacecraft+trigger with
    `grants_toughness_as_station_power_for_creatures_you_
    control=True` returns `False`. Pins §3.3 asymmetry.

### 6.7 Phase 1 + Phase 2 + MTL substrate non-regression pins

26. **Memorial Team Leader (MTL) non-regression** — MTL's
    static-anthem under `DuringYourTurn` does NOT silently flip
    into the Phase-3 predicate (`"Spacecraft" not in subtypes`
    short-circuits first).
27. **Galvanizing Sawship (Phase 1 PROBED) non-regression** —
    Sawship STILL admits via Phase 1's `_printing_is_bridge_
    pure_station_spacecraft` disjunct; the Phase-3 predicate
    correctly returns `False` for Sawship (the `if not
    printing.triggered_abilities: return False` clause
    short-circuits, deferring to the Phase-1 arm).
28. **Lumen-Class Frigate (Phase 2 PROBED) non-regression** —
    Lumen STILL admits via Phase 2's `_printing_is_bridge_
    phase_2_static_anthem_spacecraft` disjunct; the Phase-3
    predicate correctly returns `False` for Lumen (the `if
    printing.static_abilities: return False` clause
    short-circuits).

## 7. Estimated cycle count per sub-phase

Per the per-card multi-cycle precedent established by Phase 1 (4
cycles for one card) + Phase 2 (3 cycles for one card) + Carrier-AA
Phase 3A (~3 cycles for one card via the Mystifying Maze 2-Effect
substrate landing precedent at `3de469a3`), Phase 3 budgets as
follows:

### 7.1 Phase 3A (Larval Scoutlander) — ~2 cycles

| Cycle | Owner | Deliverable |
|---:|---|---|
| 1 | Rust agent | Substrate landing: new `Effect::OptionalSacLandOrLanderForBasicLandRamp` variant in `cards.rs` + parse / `to_pydict` / resolve arms + target-fan-out at `state_ops_legal.rs` + apply-time validation at `state_ops_actions.rs` + Rust substrate unit pins (§6.2 #7). **Sole Rust slice of Cycle 1** (race rule against Worker B's parallel Carrier-AA Phase 3A C2). |
| 2 | Python/bench agent | Bridge round-trip arms + admit predicate `_printing_is_bridge_phase_3_trigger_spacecraft` + admit registration + Python substrate unit pins + Larval Scoutlander real-EoE probe Scenarios A & B (§6.2 #9) + decline-set bench check + Phase-1 + Phase-2 non-regression pins. Larval Scoutlander FLIP from DECLINED → ADMITTED. |

### 7.2 Phase 3B (Sledge-Class Seedship) — ~2 cycles

| Cycle | Owner | Deliverable |
|---:|---|---|
| 1 | Rust agent | Substrate landing: new `Effect::OptionalPutCreatureFromHandOntoBattlefield` unit variant in `cards.rs` + parse / `to_pydict` / resolve arms + target-from-hand fan-out at `state_ops_legal.rs` + apply-time validation at `state_ops_actions.rs` + Rust substrate unit pins (§6.3 #10). |
| 2 | Python/bench agent | Bridge round-trip arm widen + admit-predicate Effect-class set widen + Sledge-Class Seedship real-EoE probe Scenarios A & B (§6.3 #12). Sledge-Class Seedship FLIP. |

### 7.3 Phase 3C (Synthesizer Labship + Entropic Battlecruiser + Infinite Guideline Station) — ~4-6 cycles

| Cycle | Owner | Deliverable |
|---:|---|---|
| 1 | Rust agent | `TriggeredAbility.tier_threshold` Rust slot landing + trigger-firing-time gate at `state_ops_resolve.rs:927-951` + bridge round-trip rehydrator widen + Phase 3C Cycle 1 substrate unit pins (§6.1 #1-6). **Substrate-only invariant pin** — the 3 Phase 3C target cards STAY DECLINED. |
| 2 | Python+Rust agent | `Effect::TargetArtifactBecomesCreatureUEOT` variant + resolve + bridge arms + Synthesizer Labship real-EoE probe (§6.4 #14). Synthesizer Labship FLIP. |
| 3 | Python+Rust agent | `Effect::EachOpponentDiscardsOrLosesLife` sibling-variant + resolve + bridge arms + Entropic Battlecruiser real-EoE probe Scenarios A & B & C (§6.4 #15). Entropic Battlecruiser FLIP. |
| 4 | Python+Rust agent | `Effect::CreateTokenPerMulticoloredPermanent` + `Effect::DrawCardPerMulticoloredPermanent` variants + resolve + bridge arms + Infinite Guideline Station real-EoE probe Scenarios A & B (§6.4 #16). Infinite Guideline Station FLIP. Pool-parity regen + final SL entries. **PHASE 3 CLOSED.** |

**Phase 3C may spill to +2 cycles** if Infinite Guideline Station's
multi-effect composition or the `CreateTokenPerMulticoloredPermanent`
token-printing emit / consume axis surfaces a new bridge complication
(the EoE Robot 2/2 token is bridge-supported today, but the
per-trigger emit count varies with the controller's multicolored
permanent count — the count primitive itself is sibling-narrow but
may need a sibling helper at one of the two emit sites).

**Estimated total: ~6-10 cycles for Phase 3 across 3A/3B/3C**, +5
cards admitted. Phase 3 closes the trigger leg of the Spacecraft
multi-gated tail.

**Subsequent phases (unchanged from Phase 1 + Phase 2):**

- **Phase 4 (The Eternity Elevator, ~2 cycles):** depends on
  Worker B's parallel Carrier-AA campaign Phase 1+ landing the
  non-token-AA bridge round-trip + 1 new
  `AddChargeCounterManaOfChosenColor` Effect class + per-card
  real-EoE probe.

**Campaign total: ~8-12 cycles remaining across Phase 3 + Phase 4**
to close the 6-card residue.

## 8. SEARCH_LIMITATIONS.md entries (land WITH each Phase-3 sub-phase)

Five entries (one per Phase-3 sub-phase / cycle):

1. **Phase 3A — `OptionalSacLandOrLanderForBasicLandRamp` admit
   accepts only the bare ETB-trigger Spacecraft shape; composed
   multi-trigger / static / activated co-shapes deferred.**
   Location: `_printing_is_bridge_phase_3_trigger_spacecraft` +
   the Cycle 2 per-Effect-class admit-set narrowing. Why OK: the
   predicate positively rejects every non-Phase-3 shape; the
   no-silent-auto-grow pins (§6.6) guard against accidental
   admission. Failure mode: a future bench-data refresh adding a
   composed-shape printing — same class as Phase 2's pin 17.

2. **Phase 3B — `OptionalPutCreatureFromHandOntoBattlefield`
   silent-fizzle on empty-hand or no-creature-in-hand.** Same
   class as Phase 3A; the Effect class' resolve dispatch fires
   the optional-decision-point unconditionally, and a no-target
   line is silent fizzle (matches Python's resolve semantics).

3. **Phase 3C Cycle 1 — `TriggeredAbility.tier_threshold` gate
   reads `source.charge_counters` at the dispatch-time tap.**
   The Rust gate at `state_ops_resolve.rs:927-951` re-reads the
   source's `charge_counters` at each dispatch — sibling of the
   activated-ability `tier_threshold` gate at
   `state_ops_actions.rs:1315`. Failure mode: if a future event
   shape triggers BEFORE the dispatch-time tap of the source's
   `charge_counters`, the gate may close on a stale read. The
   §6.1 #2/#3 pins exercise the gate at the four current trigger
   families; new events would need an audit. Fix-scope: trivial
   (the dispatch site is the single chokepoint).

4. **Phase 3C Cycle 3 — Mode-0 `EachOpponentDiscardsOrLosesLife`
   alternative-life-loss branch fires regardless of opponent's
   choice when their hand is non-empty.** Per the printed text, the
   alternative branch fires "Each opponent discards a card. Each
   opponent who can't loses N life." — the "each opponent who can't"
   clause means the alternative is per-opponent and triggers only
   on the empty-hand opponents (not on hand-non-empty opponents who
   declined to discard via a player choice). Why OK: every EoE
   Discard effect is mandatory by default; there's no opponent-
   choice-to-decline path; the empty-hand condition is the only
   alternative-branch trigger.

5. **Phase 3C Cycle 4 — `CreateTokenPerMulticoloredPermanent`
   token-spawn count is sampled at trigger-resolve time, not at
   trigger-fire time.** Per the standard MTG trigger resolution
   pattern (CR 603.3), the trigger queues a stack object whose
   effect computes its count when the trigger RESOLVES, not when
   it fires. The Phase 3 resolve site counts multicolored
   permanents at resolve time. Same shape as `DrawCardPer
   MulticoloredPermanent`. Why OK: matches the Python resolve
   semantics; both Effect classes' resolve methods compute the
   count at `apply()`.

## 9. Rejected alternatives

### 9.1 Land Phase 3 as a single landing covering all 5 cards

**Rejected — bundle inflates Phase 3 to a ~10-cycle behemoth that
blocks the per-card signal for the entire bundle's duration.** Per
the Phase 1 + Phase 2 precedent (each shipped 1 card), each
Phase-3 sub-phase ships 1-3 cards on its own per-Effect-class
cycle. The Phase-3 sub-phase split (3A/3B/3C) gives each
Effect-class slice its own no-silent-auto-grow boundary.

### 9.2 Bundle Phase 3A + 3B (both are single-trigger zero-tier)

**Rejected — different trigger families + different Effect
classes.** Larval Scoutlander's `OptionalSacLandOrLanderForBasic
LandRamp` is a target-fan-out + sacrifice + library-search
composite; Sledge-Class Seedship's `OptionalPutCreatureFromHand
OntoBattlefield` is a hand-to-bf zone-move on the ATTACKS event.
The two effects share NO resolve primitive beyond the optional-
decision-point dispatch. Bundling forces a 2-card simultaneous
flip that doubles the no-silent-auto-grow risk; the 2-cycle
overhead per card is the discipline tax.

### 9.3 Land `TriggeredAbility.tier_threshold` Rust slot BEFORE Phase 3A/3B

**Rejected — Phase 3A + 3B do NOT need the slot.** Larval
Scoutlander + Sledge-Class Seedship both carry `tier_threshold=0`
triggers. Landing the slot upfront would inflate Phase 3A/3B
each by 1 cycle. The slot lands in Phase 3C Cycle 1 as a
substrate-only pin, ahead of Synthesizer Labship's Cycle 2 FLIP.

### 9.4 Reuse Phase 2's `source_charge_counters_at_least` condition_tag dispatcher arm at the trigger-firing site (instead of a new `TriggeredAbility.tier_threshold` slot)

**Rejected (after design-doc back-and-forth) — dispatcher-pattern
mismatch.** Phase 2's `source_charge_counters_at_least` arm is
a condition_tag for the static-anthem reader fold (the static
fires when condition holds). Phase 3 needs a `tier_threshold`
gate at the trigger-firing site — semantically equivalent, but
structurally a slot on the `TriggeredAbility` struct itself,
not a `condition_tag` on the trigger's Effect. The Python side
ALREADY uses `TriggeredAbility.tier_threshold` (not a Condition)
per `turn.py:469-473`; the Rust side mirrors. The Phase-2
condition_tag arm composes naturally with the static
`condition_tag` walk; bolting it onto triggers would require a
sibling `condition_tag` field on `TriggeredAbility` which would
NOT mirror the Python `tier_threshold` slot. The slot landing in
Phase 3C Cycle 1 is the cleaner mirror.

### 9.5 Widen Phase 1's `_printing_is_bridge_pure_station_spacecraft` to accept 1-2 triggers

**Rejected — Phase 1's admit shape is locked as zero-ability.**
Widening would re-open Phase 1's tests + the SL entry pinning
"Phase 1 supports only the zero-ability Spacecraft carrier"
(Phase 1 SL entry #1). The clean separation — Phase 1 =
zero-ability, Phase 2 = single-static, Phase 3 = 1-2 triggers —
preserves the per-cycle no-silent-auto-grow discipline. Each
phase has its own sibling predicate; the OR-chain composition
at `_filter_deck_to_bridge_supported` carries all three.

### 9.6 Bundle Phase 3 + Phase 4 (triggers + activations)

**Rejected — Phase 4 depends on Worker B's parallel Carrier-AA
campaign + a new Effect class (`AddChargeCounterManaOfChosen
Color`). Bundling would block Phase 3's 5 cards on Phase 4's
non-token-AA bridge dependency.

### 9.7 Land all 5 Effect classes in one Rust slice + flip all 5 cards in one Python slice

**Rejected — load-bearing per-card probe discipline.** Each
card's real-EoE probe is its own load-bearing observable. Landing
the FLIPs all at once forces 5 simultaneous probes, which inflates
the agent-cycle to a multi-thousand-LoC PR that no single agent
context can responsibly review. Per-card sub-phasing keeps the
probe load <100 LoC each + the rust resolve arm sibling-narrow.

### 9.8 Drop Phase 3C and pursue Phase 3A + 3B only

**Rejected — leaves 3 / 6 residue Spacecraft (Synthesizer
Labship, Entropic Battlecruiser, Infinite Guideline Station)
unconverted, which combined with The Eternity Elevator is most
of the remaining BLOCKED-SG row. Phase 3C is the largest
single-cycle leverage cluster remaining and the
`TriggeredAbility.tier_threshold` substrate from Cycle 1
unblocks every future tier-gated trigger card the EoE pool may
ship in a future bench-data refresh.

### 9.9 Re-classify Entropic Battlecruiser's mode-0 `EachOpponentDiscardsOrLosesLife` as a widen of `EachOpponentDiscards`

**Rejected — bridge-vs-parser drift.** The parser SoT at
`effects/generic/life.py:114` (verified §1.2) emits Entropic
Battlecruiser's mode-0 as a DISTINCT `EachOpponentDiscardsOr
LosesLife` dataclass (sibling of `EachOpponentDiscards` at
`effects/generic/discard.py:132`). Mirroring exactly minimizes
bridge-vs-parser drift; widening the existing Rust variant
would force a default `life_if_cant=0` semantics on every
legacy `EachOpponentDiscards` caller, raising no-silent-auto-
grow risk. See §4.5 for the full rationale.

## 10. Acceptance / sign-off (per sub-phase)

### 10.1 Phase 3A acceptance

1. All Phase 3A pins (§6.2 #7-9) pass on the parity gate.
2. The Larval Scoutlander real-EoE probe (§6.2 #9) passes byte-
   equal through both scenarios on both engines.
3. The decline-set bench check confirms +1 card admitted (Larval
   Scoutlander), 0 spillover.
4. The Phase-1 + Phase-2 non-regression pins (§6.7 #26-28) pass.
5. The Phase-3A SL entry (§8 #1) lands alongside the substrate.
6. `.pyd` rebuilt clean; the parity gate stays green at 32/32 +
   bumps by the per-probe count.

### 10.2 Phase 3B acceptance

1. All Phase 3B pins (§6.3 #10-12) pass + Phase 3A non-regression.
2. The Sledge-Class Seedship real-EoE probe (§6.3 #12) passes
   byte-equal through both scenarios.
3. The decline-set bench check confirms +1 card admitted
   (Sledge-Class Seedship), 0 spillover.

### 10.3 Phase 3C Cycle 1 acceptance (substrate-only)

1. All Phase 3C Cycle 1 substrate pins (§6.1 #1-6) pass.
2. The 3 Phase 3C target cards (Synthesizer Labship, Entropic
   Battlecruiser, Infinite Guideline Station) STAY DECLINED at
   the admit gate (substrate-only invariant pin).
3. Phase 3A + 3B + Phase 1 + Phase 2 non-regression pins pass.

### 10.4 Phase 3C Cycle 2 acceptance (Synthesizer Labship FLIP)

1. All Synthesizer Labship pins (§6.4 #13-14) pass.
2. Probe passes byte-equal through both scenarios A & B.
3. Phase 3A + 3B + 3C Cycle 1 non-regression pins pass.

### 10.5 Phase 3C Cycle 3 acceptance (Entropic Battlecruiser FLIP)

1. All Entropic Battlecruiser pins (§6.4 #15) pass.
2. Probe passes byte-equal through scenarios A & B & C.
3. Phase 3C Cycle 2 non-regression pin (Synthesizer Labship
   STILL admits) passes.

### 10.6 Phase 3C Cycle 4 acceptance (Infinite Guideline Station FLIP + PHASE 3 CLOSED)

1. All Infinite Guideline Station pins (§6.4 #16) pass.
2. Probe passes byte-equal through scenarios A & B.
3. The decline-set bench check confirms the final Phase 3 admit
   set = `{Larval Scoutlander, Sledge-Class Seedship,
   Synthesizer Labship, Entropic Battlecruiser, Infinite
   Guideline Station}` (5 cards).
4. `scripts/scout_r58_subsystem_attribution.py` re-run: the
   `station_spacecraft` row's BLOCKED-SG count drops from 6 → 1
   (only The Eternity Elevator remaining); pool BLOCKED-SG total
   drops by 5; PROBED total bumps +5.
5. All Phase 1 / Phase 2 / Phase 3A / 3B / 3C-cycle-{1,2,3}
   non-regression pins pass.

## 11. Cross-references

- `docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_1_DESIGN.md` — the
  Phase 1 design doc this Phase 3 extends; format precedent +
  the 7 deferred carriers' classification table inherited
  through Phase 2.
- `docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_2_DESIGN.md` — the
  Phase 2 design doc this Phase 3 extends; condition_tag
  dispatcher pattern precedent + the 6 deferred carriers'
  classification table.
- `docs/CARRIER_AA_SUBSTRATE_PHASE_3_DESIGN.md` — the parallel
  Carrier-AA Phase 3 multi-sub-phase scoping doc; format
  precedent + the parallel campaign sequencing template.
- `docs/COVERED_BY_CONSTRUCTION_PROBE_WRITING_SATURATION_
  2026-05-25.md` — the 2026-05-25 saturation report that
  motivated the BLOCKED-SG subsystem pivot.
- `docs/SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY.md` §2 line 1042 —
  Spacecraft Station leverage data.
- `src/mtg_bot/cards/parser/spacecraft_builder.py:250-258` —
  `_VALID_SPACECRAFT_TIER_TRIGGER_EVENTS` table the Phase-3
  predicate mirrors.
- `src/mtg_bot/cards/parser/spacecraft_builder.py:60-71` —
  engine-side gap for tier-gated SELF-scope static keyword
  grants (out of scope, §3.6).
- `src/mtg_bot/effects/combinators.py:205` —
  `OptionalPutCreatureFromHandOntoBattlefield` Python class.
- `src/mtg_bot/effects/combinators.py:699` —
  `OptionalSacLandOrLanderForBasicLandRamp` Python class.
- `src/mtg_bot/effects/generic/become_type.py:36` —
  `TargetArtifactBecomesCreatureUEOT` Python class.
- `src/mtg_bot/effects/generic/discard.py:132` —
  `EachOpponentDiscards` Python class (the existing Rust-
  supported sibling).
- `src/mtg_bot/effects/generic/draw_mill.py:120` —
  `DrawCardPerMulticoloredPermanent` Python class.
- `src/mtg_bot/effects/generic/life.py:80` —
  `TargetPlayerLosesLife` Python class (existing Rust-supported).
- `src/mtg_bot/effects/generic/life.py:114` —
  `EachOpponentDiscardsOrLosesLife` Python class.
- `src/mtg_bot/effects/generic/tokens.py:122` —
  `CreateTokenPerMulticoloredPermanent` Python class.
- `src/mtg_bot/turn.py:436-480` — Python's `should_fire_trigger`
  with the `tier_threshold` gate at line 469-473 (the Python
  parity reference for Phase 3C Cycle 1's Rust gate).
- `src/mtg_bot/cards/base.py:1259-1262` —
  Python's `TriggeredAbility.tier_threshold` field reference.
- `src/mtg_bot/parity/cross_engine.py:13678-13680` — the
  `triggered_abilities` emit pass (Phase 3 widens with the
  new Effect-class arms + `tier_threshold` thread-through).
- `src/mtg_bot/parity/cross_engine.py:12503` — the
  `_ta_dict_to_python_effect` reconstruction arm (Phase 3
  adds 5 new `kind` arms).
- `src/mtg_bot/parity/trajectory.py` — sibling admit
  predicates from Phase 1 + Phase 2.
- `rust/src/cards.rs:9725-9748` — Rust's `TriggeredAbility`
  struct (Phase 3C Cycle 1 adds `tier_threshold: i32`).
- `rust/src/cards.rs:8734-9014` — Rust's `Event` enum (every
  Phase-3 trigger family's event is already wired).
- `rust/src/cards.rs:10264` — Rust's
  `ActivatedAbility.tier_threshold: i32` (the sibling slot
  Phase 3C Cycle 1 mirrors for triggers).
- `rust/src/cards.rs:1189` — Rust's existing
  `Effect::TargetPlayerLosesLife` variant (used by Entropic
  Battlecruiser mode-1; reused unchanged).
- `rust/src/cards.rs:1238` — Rust's existing
  `Effect::EachOpponentDiscards` variant (sibling of Phase
  3C Cycle 3's new `EachOpponentDiscardsOrLosesLife`).
- `rust/src/state_ops_resolve.rs:917-967` — the centralized
  trigger-firing-time dispatch (Phase 3C Cycle 1 adds the
  `tier_threshold` gate here).
- `rust/src/state_ops_combat.rs:1730` — per-attacker ATTACKS
  trigger dispatch (routes through `dispatch_event`, so
  Phase 3 inherits the gate at §4.1 without an edit).
- `rust/src/state_ops_resolve.rs:6623-6673` — Rust's
  `Effect::EachOpponentDiscards` resolve site (the sibling
  Phase 3C Cycle 3 widens).
- `rust/src/state_ops_resolve.rs:22920` — Rust's
  `Effect::PutBasicLandFromHandOntoBattlefieldTapped` resolve
  site (the Phase 3B precedent for hand-to-bf zone-move +
  ETB queue).

## 12. Regenerating the enumeration

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
  scripts/scout_r58_subsystem_attribution.py
```

reproduces the 6-member Spacecraft BLOCKED-SG residue exactly
post-Phase-2 (0 single-gated; 6 multi-gated → 5 Phase-3-feasible +
1 Phase-4-deferred). The per-card live parsed printings (§1.2 +
§2 tables) are verifiable via
`OracleParserCardSource().get_printings()[<name>]` — walk
`station_threshold`, `stationed_keywords`, `triggered_abilities`,
`static_abilities`, `activated_abilities`, plus per-trigger
`event` / `predicate` / `tier_threshold` / `effect`. All §4 / §5
file:line refs verified against main `086f86fc`.

## 13. Sequencing recommendation

**Recommended dispatch order: 3A → 3B (parallel-safe) → 3C
Cycle 1 → 3C Cycle 2 → 3C Cycle 3 → 3C Cycle 4.**

* 3A + 3B are parallel-safe across two workers (no shared Rust
  slice; both add a single new `Effect::*` variant on disjoint
  resolve sites — both touch `cards.rs` enum + `state_ops_
  resolve.rs` but the resolve arms are sibling-narrow and the
  enum extensions never collide).
* 3C Cycle 1 (`TriggeredAbility.tier_threshold` substrate) must
  CLOSE before 3C Cycle 2-4 because Cycles 2-4 rely on the
  gate. The substrate IS the load-bearing slice; the 3 per-card
  cycles are each parallel-safe against each other AFTER
  Cycle 1 closes (different Effect-class enum entries, different
  resolve arms, different per-card probes).
* Phase 3C Cycle 4's Infinite Guideline Station closes Phase 3.
* Phase 4 (The Eternity Elevator) opens immediately after,
  pending Worker B's parallel Carrier-AA Phase 1+ non-token-AA
  bridge closure.

The recommended single-agent serial walk is 3A → 3B → 3C Cycle 1
→ 3C Cycle 2 → 3C Cycle 3 → 3C Cycle 4 (5 cards landed across
~6-10 cycles). The recommended two-worker parallel walk is
Worker A on 3A + 3C, Worker B on 3B (Worker A's Cycle 1 of 3C
substrate must land BEFORE Cycle 2/3/4; Worker B can
independently complete 3B in parallel with 3A's 2 cycles + 3C
Cycle 1).
