Generated 2026-05-25 (post `spacecraft-phase-1-cycle-4-sawship-
probe-p1`, main `7e07400f`; parallel-with `carrier-aa-phase-2b`
in flight on Worker B's lane). **Design only — NO production /
`_SAFE_*` / Rust change in this slice; no gate run beyond the
32/32 `tests/test_measure_pool_parity.py` baseline** (docs +
read-only scout against the live tree at main `7e07400f`). This
doc scopes the **Spacecraft Station Phase 2** sub-shape (Lumen-
Class Frigate — static-anthem carrier) in the gold-standard
format of `docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_1_DESIGN.md`.
Every file:line below is verified against the live tree at main
`7e07400f`.

> **Relationship to `docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_1_
> DESIGN.md`.** Phase 1 (`ea9aa996` → `62e10ff9` → `e9a31c83` →
> `7e07400f`) shipped the Spacecraft Station substrate to its
> sub-shape A target (zero-ability Spacecraft carriers; pilot
> Galvanizing Sawship — PROBED 2026-05-25, ~5,938 17lands decks).
> Phase 2 here scopes the next-narrowest sub-shape **B** (sub-
> shape A + a single static-anthem rider), naming **Lumen-Class
> Frigate** as the single Phase-2 admitted card. Phases 3 and 4
> (5 trigger carriers; The Eternity Elevator) stay deferred per
> the Phase 1 doc §3.2 / §3.3 sequencing.
>
> **Relationship to the Phase 4 anthem-substrate ALREADY landed
> for Memorial Team Leader Cycle 2 (`docs/SPACECRAFT_STATION_
> SUBSTRATE_PHASE_1_DESIGN.md` §11 cross-ref).** Memorial Team
> Leader's anthem substrate at `trajectory.py:9839-9930`
> (`_static_ability_is_phase4_anthem_pt_conditional`) +
> `cross_engine.py:13708-13750` (6-tuple `static_anthems` emit) +
> `cross_engine.py:14627-14687` (rehydrator) + `rust/src/state_
> ops_combat.rs:737-747` (`static_anthem_condition_matches`) +
> `rust/src/cards.rs:10872-10906` (`StaticAnthem` slot) is the
> MTL Phase-4 SUBSTRATE Phase 2 here reuses. The substrate
> already round-trips: `(scope, granted_keywords, power_bonus,
> toughness_bonus, condition_tag, condition_args)`. The
> Lumen-Class Frigate static fits the same shape EXCEPT for the
> condition gate: MTL uses `condition_tag="during_your_turn"`
> (viewer-only, no args); Lumen-Class Frigate needs a new
> tag (`source_charge_counters_at_least`, args = `(tier_
> threshold,)`) that reads the SOURCE's charge counters at
> condition-check time — a NEW condition shape (the only one in
> Phase 2's Rust slice). The reader-fold (`static_anthem_pt_
> bonus_for`) reuses unchanged.
>
> **Relationship to the 2026-05-24 tractability rescout**
> (`docs/MULTI_GATED_TAIL_TRACTABILITY_RESCOUT_2026-05-24.md`
> entry #5). The rescout pinned Lumen-Class Frigate at "~70 %
> of one cycle off MTL Phase-4 reader fold + bridge" but cited
> the Spacecraft substrate (`tier_threshold=2,
> station_threshold=12`) as the §2-DEFERRED prerequisite.
> Phase 1 above lands the Spacecraft substrate (the
> `station_threshold` / `stationed_keywords` axis); Phase 2
> here lands the `tier_threshold`-gated static-anthem axis on
> top of MTL Phase-4 substrate, AT WHICH POINT Lumen-Class
> Frigate closes end-to-end on the combined disjunct.
>
> **Relationship to the partial scaffolding already shipped
> Rust-side.** `ActivatedAbility.tier_threshold: i32` exists
> (`rust/src/cards.rs:9981-10022`) and is read by the AA
> legality gate (`rust/src/state_ops_legal.rs:3328`) + the AA
> apply-time gate (`rust/src/state_ops_actions.rs:996`).
> `StaticAbility` Rust-side has NO `tier_threshold` field
> yet — Phase 2 here either extends `StaticAnthem` with a
> `tier_threshold: i32` slot OR ports the gate through the
> condition_tag dispatcher (Phase 2 prefers the latter — see
> §4.1 below — because the existing 6-tuple bridge shape
> already round-trips `(condition_tag, condition_args)` and
> the dispatcher pattern is what unblocks Phase 3's trigger-
> firing `tier_threshold` gate too).

# Spacecraft Station substrate Phase 2 — campaign scoping doc (sub-shape B: bare zero-ability + single static-anthem Spacecraft carrier — pilot `Lumen-Class Frigate`)

## 0. Executive summary

The **Spacecraft Station** subsystem at live HEAD `7e07400f`
binds **7 cards remaining** (8 total per Phase 1; Galvanizing
Sawship PROBED in Phase 1) across the BLOCKED-SG row. Of those
7, **exactly 1 — Lumen-Class Frigate — passes the next-narrowest
sub-shape filter** (sub-shape A + a single static-anthem rider).
The other 6 stay DECLINED per Phase 1's classification:
Lumen-Class Frigate alone has *only* a static ability on top of
the Spacecraft substrate; every other deferred Spacecraft pulls
in at least one triggered-ability Effect class (Phase 3) or a
non-Station activated ability (Phase 4 — The Eternity Elevator).

This doc scopes the substrate's **Phase 2**: admit the
**static-only Spacecraft carrier** sub-shape — a Spacecraft with
the Station mechanic Phase 1 already supports PLUS exactly one
static ability whose shape matches the MTL Phase-4 anthem
substrate already in production, with the *single* new
substrate piece being a `tier_threshold`-style charge-counter
gate on the SOURCE object (a new `condition_tag` arm in the
existing anthem condition dispatcher). The pilot is
**Lumen-Class Frigate** (the sole sub-shape B carrier; verified
by §2's live walk of the 7 deferred Spacecraft printings).

Phase 2 explicitly **defers**: the 5 triggered-ability
Spacecraft carriers (Larval Scoutlander, Sledge-Class Seedship,
Synthesizer Labship, Entropic Battlecruiser, Infinite Guideline
Station — Phase 3) and The Eternity Elevator (Phase 4,
non-station + activated abilities + dependency on Worker B's
Carrier-AA non-token-AA bridge). Sub-shape B's 2-3-cycle reach
is **exactly Lumen-Class Frigate** because every other deferred
Spacecraft carries a non-static ability shape Rust does not yet
handle.

Estimated campaign scope: **Phase 2 = ~3 cycles** (Rust
substrate slice 1, Python bridge + admit + per-card real-EoE
probe 1-2 cycles). +1 card admitted (Lumen-Class Frigate);
17lands deck-count unlock not enumerable from the worker's
context but PHASE 1 (§2 table line `Lumen-Class Frigate | * |`)
already noted that the 7 deferred carriers sum to ~35,343
17lands decks cumulative (the residual 41,281 − 5,938
Sawship-PROBED). Per-card subtotals are not load-bearing for
sequencing here; what matters is that Phase 2 closes the
*static* leg of the multi-gated Spacecraft tail, leaving
the trigger / AA legs for Phases 3-4.

## 1. Background — why this sub-shape, why now

### 1.1 Phase 1 closure recap

Phase 1 (commits `ea9aa996` → `62e10ff9` → `e9a31c83` →
`7e07400f`, 2026-05-25) shipped:

* **Cycle 1 — `ea9aa996`** — Rust substrate Part A:
  `CardPrinting.station_threshold: Option<i32>` +
  `stationed_keywords: Vec<String>` + parse arms +
  `is_stationed_predicate` Rust helper.
* **Cycle 2 — `62e10ff9`** — Rust substrate Part B:
  `Action::ActivateStation` flipped from stub to real
  `apply_activate_station` resolver + sorcery-speed legal-
  action emitter + `is_creature_now` extension +
  effective-keyword fold (`battlefield_has_keyword` extension
  at `state_ops_combat.rs:1099-1140`).
* **Cycle 3 — `e9a31c83`** — Python bridge round-trip +
  `_printing_is_bridge_pure_station_spacecraft` admit
  predicate + OR-chain disjunct registration + Galvanizing
  Sawship admit-set FLIP.
* **Cycle 4 — `7e07400f`** — Galvanizing Sawship per-card
  real-EoE byte-equal probe across Scenarios A/B/C
  (un-stationed / partial-station / fully-stationed-and-
  attacking), THE PROBE.

Post-Phase-1 pool-parity counts: BLOCKED-SG Station/Spacecraft
row 8 → 7; PROBED total bumps +1; covered_by_construction 39 →
40. The `_printing_is_bridge_pure_station_spacecraft` predicate
(`trajectory.py`, sibling of `_pure_warp_creature` /
`_pure_cost_reduction_creature` / `_simple_carrier_aa_land`) is
in production and admits *exactly* Galvanizing Sawship; the
other 7 deferred Spacecraft are positively rejected per Phase 1
§5.4 clauses (the no-static / no-triggered / no-activated
guards).

### 1.2 The 7 remaining Spacecraft — classification by ability type

A live walk against `OracleParserCardSource().get_printings()`
at main `7e07400f` (the same scout pattern Phase 1 §2 used,
re-run after Phase 1 cycle 4) reproduces the Phase-1 §2 table
unchanged for the 7 deferred carriers. Reclassified by
**ability-type next-frontier** (i.e. what blocks them BEYOND
Phase 1's bare-Station substrate):

| Card | Spacecraft Sub-shape | Blocking ability shapes | Earliest Phase |
|---|---|---|---:|
| **Lumen-Class Frigate** | **B (static-only)** | 1× StaticAbility(scope=other_creatures_you_control, layer-7 P/T anthem +1/+1, **tier_threshold=2**) | **2** |
| Larval Scoutlander | C (single-trigger) | 1× Triggered `OptionalSacLandOrLanderForBasicLandRamp` | 3 |
| Sledge-Class Seedship | C (single-trigger) | 1× Triggered `OptionalPutCreatureFromHandOntoBattlefield` | 3 |
| Synthesizer Labship | C* (tier-gated trigger) | 1× Triggered `TargetArtifactBecomesCreatureUEOT` at **tier_threshold=2** | 3 |
| Entropic Battlecruiser | C* (mode + tier-gated trigger) | 2× Triggered `EachOpponentDiscardsOrLosesLife` (mode-0) + `TargetPlayerLosesLife` (mode-1, tier=1) | 3 |
| Infinite Guideline Station | C (multi-trigger) | 2× Triggered `CreateTokenPerMulticoloredPermanent` + `DrawCardPerMulticoloredPermanent` | 3 |
| The Eternity Elevator | D (non-animating + activated) | `station_threshold=None` + 2× AA (`AddManaToPool` tier=0; `AddChargeCounterManaOfChosenColor` tier=20) | 4 |

**Sub-shape B is exactly one card.** Lumen-Class Frigate is the
*sole* Spacecraft whose only above-substrate ability is a
single StaticAbility — no triggered abilities, no activated
abilities other than the Phase-1-substrate-supplied Station
action, no spell_effect, no warp / kicker / impending costs.
Live walk pin (verify-first, run against main `7e07400f`):

```
name='Lumen-Class Frigate'
subtypes=('Spacecraft',)
card_types=('Artifact',)              # not a Creature; Spacecraft animates via Station fold
station_threshold=12
stationed_keywords=frozenset({'flying', 'lifelink'})
power=3, toughness=5
mana_cost_str='{1}{W}'
keywords=frozenset()                   # empty baseline (anthem doesn't ride a keyword grant)
spell_effect=None
triggered_abilities=()
activated_abilities=()
static_abilities=(
    StaticAbility(
        scope='other_creatures_you_control',
        granted_keywords=frozenset(),
        power_bonus=0,                 # legacy P/T slot empty — payload rides ContinuousModifier
        toughness_bonus=0,
        tier_threshold=2,              # *** the new Phase-2 substrate piece ***
        room_half=None,
        grants_no_max_hand_size=False,
        grants_creature_spells_uncounterable=False,
        condition=None,                # *** NO Condition instance — gate IS tier_threshold ***
        replacement_effect=None,
        continuous_effect=ContinuousModifier(
            layer=7,
            payload=PowerToughnessBonus(power_bonus=1, toughness_bonus=1),
            subject_filter=None,
        ),
    ),
)
grants_toughness_as_station_power_for_creatures_you_control=False
```

The shape exactly matches MTL's Phase-4 anthem-PT-conditional
shape (`trajectory.py:9839-9930`) EXCEPT for two distinguishing
fields:

1. **`tier_threshold=2`** (MTL: 0). The static fires only while
   the source Spacecraft has `charge_counters >= 2`. This is the
   *single* new piece Phase 2 must port.
2. **`condition=None`** (MTL: `DuringYourTurn()`). Lumen-Class
   Frigate carries no time-of-turn rider; the only gate is
   `tier_threshold`.

Both differences are purely on the *condition gate* axis —
scope, granted_keywords, P/T payload, layer, subject_filter,
and every other StaticAbility slot match MTL's admit shape
verbatim. The MTL Phase-4 substrate's bridge round-trip + Rust
reader fold + dispatch table are reusable; what changes is one
new `condition_tag` arm.

### 1.3 Why the substrate scope is small (relative to Phase 1)

Per the §1.2 walk, the substrate requires the following
components — *every one of which has an existing precedent in
production*:

1. **Anthem-scope `tier_threshold` gate** — a new
   `condition_tag` arm `"source_charge_counters_at_least"`
   with `condition_args=(N,)` (`N = tier_threshold`). The MTL
   Phase-4 dispatch table at `state_ops_combat.rs:737-747`
   already routes on `condition_tag`; the new arm reads
   `source.charge_counters >= args[0]` rather than reading
   `state.active_player`. Sibling-narrow precedent.
2. **Spacecraft subtype carrier admit** — the MTL anthem
   substrate's admit predicate
   (`_printing_is_bridge_static_anthem_pt_conditional_warp_
   creature` at `trajectory.py:9933-10085`) gates on
   `"Creature" in card_types` and `warp_cost is not None`.
   Lumen-Class Frigate is `Artifact` printed (Spacecraft;
   `card_types=("Artifact",)`) and has no warp cost — the
   admit predicate has to be a NEW sibling
   (`_printing_is_bridge_phase_2_static_anthem_spacecraft`),
   not a widen of the warp-anthem predicate. The new sibling
   gates on `"Spacecraft" in subtypes` + `station_threshold >
   0` + the Phase-1 substrate's `_printing_is_bridge_pure_
   station_spacecraft` clauses EXCEPT for the static-abilities
   clause, which is replaced with a positive allowlist
   (`_static_ability_is_phase4_anthem_pt_conditional` extended
   to admit `tier_threshold >= 1`).
3. **Bridge dict carry-through** — the existing `static_
   anthems` 6-tuple at `cross_engine.py:13708-13750` already
   carries `(scope, granted_keywords, power_bonus, toughness_
   bonus, condition_tag, condition_args)`; Phase 2 emits the
   Lumen-Class Frigate static as `("other_creatures_you_
   control", (), 1, 1, "source_charge_counters_at_least",
   (2,))`. The encoder, the parser, the rehydrator
   (`_static_anthem_condition_from_tag` at
   `cross_engine.py:14351-14407`), and the Rust
   `StaticAnthem` slot all already exist; the rehydrator gets
   one new branch (`"source_charge_counters_at_least"` →
   a new `Condition` subclass OR a `tier_threshold` thread-
   through; see §5.3 below). No new tuple shape; the existing
   6-tuple is exhaustive.
4. **Reader-fold extension** —
   `static_anthem_pt_bonus_for` at
   `state_ops_combat.rs:769-810` already iterates anthems and
   short-circuits on `static_anthem_condition_matches`. The
   new `"source_charge_counters_at_least"` tag is a one-line
   match arm extension — no walk-shape change, no new fold.

Component (1) is the *single* new substrate piece. Components
(2)-(4) are admit-widen / bridge-route / dispatcher-arm work
that each fits in <1 cycle of agent time on the precedent of
prior Phase-flips (Petrified Field 2026-05-25; Memorial Team
Leader Cycle 2 2026-05-24; Deserted Temple 2026-05-25).

### 1.4 Calibration against Phase 1 + sibling phases

Phase 1 took 4 cycles (substrate Part A + Part B + bridge/admit
+ probe) to ship Galvanizing Sawship. Phase 2 is **strictly
smaller**:

* Phase 2 ships ZERO new Action variants (Phase 1 added
  `ActivateStation`). The static-anthem reader path is purely
  a reader-fold extension on the existing layer-7 walk.
* Phase 2 ships ONE new `condition_tag` arm (vs Phase 1's
  whole-cloth Station decision machinery). The dispatcher
  pattern at `state_ops_combat.rs:737-747` is sibling-narrow
  precedent; the bridge already carries `(condition_tag,
  condition_args)`.
* Phase 2 ships ONE admit-predicate sibling (the new sub-
  shape B predicate), parallel to Phase 1's
  `_printing_is_bridge_pure_station_spacecraft`. The admit
  rejects 6 of the 7 deferred Spacecraft on the no-triggered
  / no-activated clauses; only Lumen-Class Frigate passes.

The campaign-total estimate from Phase 1 §1.3 (~16-22 cycles
across Phase 1 / 2 / 3 / 4) had Phase 2 budgeted at 2-3 cycles.
Phase 2 lands at the lower bound of that range because the
MTL Phase-4 anthem substrate is fully reusable.

## 2. Sub-shape B scope — exactly 1 card, the static-only Spacecraft carrier

Verified live against `OracleParserCardSource().get_printings()`
at main `7e07400f` (per the §1.2 walk + the per-card audit
table inherited from Phase 1 §2):

| Card | `station_threshold` | `stationed_keywords` | mana_cost | P/T | static.tier_threshold | other shapes | Phase |
|---|---:|---|---|---|---:|---|---|
| **Lumen-Class Frigate** | 12 | `{flying, lifelink}` | `{1}{W}` | 3/5 | **2** | NONE (single static-anthem only) | **2** |
| Larval Scoutlander | 7 | `{flying}` | `{2}{G}` | 3/3 | — | trig `OptionalSacLandOrLanderForBasicLandRamp` | 3 |
| Sledge-Class Seedship | 7 | `{flying}` | `{2}{G}` | 4/5 | — | trig `OptionalPutCreatureFromHandOntoBattlefield` | 3 |
| Synthesizer Labship | 9 | `{flying, vigilance}` | `{U}` | 4/4 | 2 (trig) | trig `TargetArtifactBecomesCreatureUEOT` at `tier_threshold=2` | 3 |
| Entropic Battlecruiser | 8 | `{deathtouch, flying}` | `{3}{B}` | 3/10 | 0/1 (trig) | trig `EachOpponentDiscardsOrLosesLife` (tier=0) + `TargetPlayerLosesLife` (tier=1) | 3 |
| Infinite Guideline Station | 12 | `{flying}` | `{W}{U}{B}{R}{G}` | 7/15 | — | trig `CreateTokenPerMulticoloredPermanent` + `DrawCardPerMulticoloredPermanent` | 3 |
| The Eternity Elevator | **None** | `{}` | `{5}` | 0/0 | 20 (AA) | AA `AddManaToPool` (tier=0) + AA `AddChargeCounterManaOfChosenColor` (tier=20) | 4 |

**Phase-2 admit total: 1 card** (Lumen-Class Frigate). The 6
other deferred Spacecraft all carry at least one
**triggered** or **activated** ability — both positively
rejected by the sub-shape B admit predicate (§5.4 below).

**Why Lumen-Class Frigate is the only sub-shape B carrier.**
Per the live print walk, ZERO other deferred Spacecraft has
empty `triggered_abilities + activated_abilities` while
carrying a single static. Synthesizer Labship and Entropic
Battlecruiser also use `tier_threshold` but route through the
triggered-ability dispatch, not the static dispatch — those
are Phase 3 because the `nonsafe_triggered_ability` event-
shape gate plus a new Effect class is needed in addition to
the `tier_threshold` machinery Phase 2 ports.

Sub-shape B's positive criteria, all verified for Lumen-Class
Frigate at live HEAD:

- The printing carries `"Spacecraft" in subtypes`.
- `station_threshold` is set to a positive int (12) +
  `stationed_keywords` non-empty (`{flying, lifelink}`).
- `static_abilities` has exactly one entry; every other static
  slot at default per §1.2 walk.
- The single static is a layer-7 PowerToughnessBonus anthem
  under scope `other_creatures_you_control` with
  `tier_threshold >= 1` and `condition=None` (no rider beyond
  the tier gate).
- `triggered_abilities == () AND activated_abilities == ()`.
- `spell_effect is None`, no `room_halves`, no `loyalty`, no
  `dynamic_pt_formula`, no `ward_cost`, no `cost_reductions`,
  no `external_cost_reductions`, no `warp_cost`, no
  `kicker_cost`, no `impending_cost`, no `keywords` baseline.
- Both `stationed_keywords` (`flying`, `lifelink`) are in
  `trajectory.py::_SAFE_KEYWORDS` (Phase 1 verified `flying`
  + `haste`; `lifelink` is also first-class in Rust combat
  per the round-43 lifelink-keyword landing).
- `grants_toughness_as_station_power_for_creatures_you_
  control=False` (Tapestry-Warden asymmetry pin from Phase 1
  §3.4 stays positive-reject).

The ONLY blocking features on Lumen-Class Frigate beyond the
Phase-1 substrate are: (a) the single static-anthem
PowerToughnessBonus payload, and (b) its `tier_threshold=2`
gate. Both are addressable through the MTL Phase-4 anthem
substrate + one new `condition_tag` arm.

## 3. Out-of-scope (deferred to Phase 3+)

The following are explicitly **NOT** in Phase 2's scope. The
Phase-2 filter guardrail (`_printing_is_bridge_phase_2_static_
anthem_spacecraft`, §5.4) positively rejects each so they
cannot reach the Phase-2 admit path:

### 3.1 Triggered-ability Spacecraft carriers — Phase 3 (5 cards)

The 5 triggered-ability Spacecraft (Larval Scoutlander,
Sledge-Class Seedship, Synthesizer Labship, Entropic Battle-
cruiser, Infinite Guideline Station) each carry a triggered
ability whose Effect class has no Rust counterpart today
(per Phase 1 §3.2 reclassification). Phase 3 ports:

- Larval Scoutlander → `OptionalSacLandOrLanderForBasicLandRamp`
- Sledge-Class Seedship → `OptionalPutCreatureFromHandOntoBattlefield`
- Synthesizer Labship → `TargetArtifactBecomesCreatureUEOT`
  at `tier_threshold=2` (rides Phase 2's gate dispatch — see
  §3.4 below for the cross-phase amortization note)
- Entropic Battlecruiser → `EachOpponentDiscardsOrLosesLife`
  (tier=0, unconditional) + `TargetPlayerLosesLife` (tier=1)
- Infinite Guideline Station → `CreateTokenPerMulticoloredPermanent`
  + `DrawCardPerMulticoloredPermanent`

Each card is its own ~1-2 cycle slice (Effect class + bridge
arm + per-card real-EoE probe). Phase 3 sequencing TBD when
Phase 2 closes.

### 3.2 Activated-ability Spacecraft carriers — Phase 4 (The Eternity Elevator)

The Eternity Elevator (Phase 1 §3.3 reference) is
`station_threshold=None` + 2× activated abilities; Phase 4
depends on Worker B's parallel Carrier-AA Phase 1+ landing the
non-token-AA bridge round-trip. Sequencing unchanged from
Phase 1 §3.3.

### 3.3 Mixed-shape carriers — out of substrate (not in pool today)

A future Spacecraft that combined a static-anthem rider with
a triggered ability would compose Phase 2's static piece + a
Phase-3 Effect class. No such printing ships in the EoE pool
today (verified by the §2 walk). Phase 2's admit predicate
positively rejects any printing with non-empty
`triggered_abilities`, so a future composed-shape card stays
DECLINED on Phase 2's gate alone — no silent auto-grow risk.

### 3.4 `tier_threshold`-gated triggered abilities — cross-phase amortization note

Synthesizer Labship's trigger fires only while `charge_
counters >= 2` (its `tier_threshold=2`); Entropic Battle-
cruiser's mode-1 trigger fires only while `charge_counters
>= 1`. Phase 2's `source_charge_counters_at_least` condition
arm is the SAME predicate the trigger-firing site needs in
Phase 3 — the dispatcher pattern is reusable. Phase 2 lands
the static-side gate; Phase 3 routes the trigger-firing side
through the same condition_tag dispatch (or, if the static
gate ships as a new struct field on `StaticAnthem` rather
than as a condition_tag arm, Phase 3 will need a parallel
field on `TriggeredAbility`). The choice between the two
shapes is locked at §4.1 below — Phase 2 prefers the
condition_tag arm precisely because Phase 3 reuses it without
re-implementing.

### 3.5 The Tapestry Warden asymmetry — unchanged from Phase 1 §3.4

Phase 2's admit predicate positively rejects
`grants_toughness_as_station_power_for_creatures_you_control=
True`. No EoE Spacecraft carries the flag; Tapestry Warden
itself is not a Spacecraft. Future-proof guard preserved
from Phase 1.

## 4. Rust-side spec — the new condition_tag arm + reader-fold pass-through

### 4.1 New condition_tag arm: `"source_charge_counters_at_least"`

**File:** `rust/src/state_ops_combat.rs` —
`static_anthem_condition_matches` at line 737-747.

**Decision: route through condition_tag dispatch (not a new
StaticAnthem field).** Two alternatives considered:

1. **(Chosen)** Extend the dispatcher with a new arm
   `"source_charge_counters_at_least"` that reads
   `source.charge_counters >= condition_args[0]` and returns
   `bool`. The dispatcher's signature already takes the
   anthem struct (which has the args), but currently does
   NOT take the source object. **The signature widens to
   accept the SOURCE `GameObject` reference** (or the
   source.id + lookup) so the new arm can read
   `source.charge_counters`. Callers (`battlefield_has_
   keyword` at line 696, `static_anthem_pt_bonus_for` at
   line 803) already iterate `for source in source_player.
   battlefield` and thread `source.id` — the widen is a
   borrowed-arg pass-through, not a state-walk addition.
2. Add a `tier_threshold: i32` field to `StaticAnthem` and
   gate it in the reader fold directly. **Rejected** — the
   condition_tag dispatch is the existing extension point
   for new gating predicates; adding a parallel slot
   bifurcates the gate-walk (two checks instead of one) and
   doesn't compose with Phase 3's trigger-firing site, which
   would then need its own duplicated slot. The
   condition_tag arm is reused unchanged at Phase 3's
   trigger-firing gate.

The proposed (chosen) signature:

```rust
pub(crate) fn static_anthem_condition_matches(
    state: &GameState,
    viewer_idx: usize,
    source: &GameObject,          // *** NEW arg — source of anthem ***
    anthem: &crate::cards::StaticAnthem,
) -> bool {
    match anthem.condition_tag.as_str() {
        "" => true,
        "during_your_turn" => state.active_player as usize == viewer_idx,
        // *** Phase 2 (Spacecraft Phase 2, Lumen-Class Frigate) ***
        "source_charge_counters_at_least" => {
            let threshold = anthem.condition_args
                .get(0).copied().unwrap_or(0);
            source.charge_counters >= threshold
        }
        _ => false,
    }
}
```

Both call sites (`battlefield_has_keyword`, `static_anthem_
pt_bonus_for`) pass the source object through (they already
loop `for source in source_player.battlefield`). The
two-line patch at each call site threads `source` into the
new arg.

### 4.2 No new `StaticAnthem` field — bridge shape unchanged

The bridge 6-tuple `(scope, granted_keywords, power_bonus,
toughness_bonus, condition_tag, condition_args)` already
carries everything Phase 2 needs. The Rust `StaticAnthem`
struct at `rust/src/cards.rs:10872-10906` already has
`condition_tag: String` + `condition_args: Vec<i32>`. The
parser at `rust/src/cards.rs:15191-15199` already accepts the
6-tuple shape; the only widen there is the condition_tag
whitelist:

```rust
// rust/src/cards.rs:15191
// Currently:
if !condition_tag.is_empty()
    && condition_tag != "during_your_turn" {
    bail!("unknown anthem condition_tag: {condition_tag}");
}
// Phase 2 widen:
if !condition_tag.is_empty()
    && condition_tag != "during_your_turn"
    && condition_tag != "source_charge_counters_at_least" {
    bail!("unknown anthem condition_tag: {condition_tag}");
}
```

Pre-existing pre-substrate registry dicts (every pre-MTL
anthem carrier — Tannuk Steadfast Second; every pre-Phase-2
anthem carrier — MTL alone) emit condition_tag either as the
empty string or as `"during_your_turn"`; neither uses
`"source_charge_counters_at_least"` — bit-identical pre-
Phase-2 registry behavior preserved.

### 4.3 Reader-fold pass-through — `static_anthem_pt_bonus_for`

**File:** `rust/src/state_ops_combat.rs:769-810`. The walk
shape is unchanged; the only edit is the dispatcher call
gets the new `source` argument:

```rust
// Currently:
if !anthem.condition_tag.is_empty()
    && !static_anthem_condition_matches(
        state,
        target_controller_idx,
        anthem,
    ) { continue; }
// Phase 2:
if !anthem.condition_tag.is_empty()
    && !static_anthem_condition_matches(
        state,
        target_controller_idx,
        source,                    // *** NEW arg threaded ***
        anthem,
    ) { continue; }
```

Same edit at `battlefield_has_keyword` line 696.

### 4.4 No new is_creature_now / is_stationed / station mechanic changes

Phase 1 already shipped `is_creature_now` + `is_stationed_
predicate` + the `apply_activate_station` resolver +
sorcery-speed legal-action emitter + effective-keyword fold.
Phase 2 does NOT change any of these. Lumen-Class Frigate
animates as a 3/5 with lifelink + flying when stationed
(`charge_counters >= 12`); the substrate piece Phase 1 ported
handles the animation tick + keyword fold unchanged. Phase 2
adds ONLY the anthem-fire-while-source-has-≥2-counters gate.

### 4.5 P/T resolution under stationed-flip — unchanged

Phase 1 §4.7 covered the Spacecraft P/T read; Lumen-Class
Frigate's printed P/T (3/5) reads through the existing
reader fold when stationed. The static-anthem layer-7 P/T
contribution it RADIATES (+1/+1 to OTHER creatures the
controller controls) is what Phase 2 wires; this is folded
by `static_anthem_pt_bonus_for` on each OTHER creature, not
on the Spacecraft itself.

## 5. Python bridge spec — bidirectional round-trip + admit predicate

### 5.1 Bridge dict shape (Python-side emit)

**File:** `src/mtg_bot/parity/cross_engine.py` — the
`_spec_card_to_printing_dict` static_anthems emit at line
13692-13750.

**No new fields. No new tuple shapes.** The existing 6-tuple
shape carries Lumen-Class Frigate's anthem identically:

```python
# Lumen-Class Frigate emit (Phase 2):
# CardDef.static_anthems is a tuple of one 6-tuple entry:
(
    "other_creatures_you_control",   # scope
    (),                              # granted_keywords (empty — anthem is P/T-only)
    1,                               # power_bonus
    1,                               # toughness_bonus
    "source_charge_counters_at_least",  # condition_tag (NEW arm)
    (2,),                            # condition_args (tier_threshold)
)
```

The encoder at line 13708-13750 already serializes this to:

```json
{
    "scope": "other_creatures_you_control",
    "granted_keywords": [],
    "power_bonus": 1,
    "toughness_bonus": 1,
    "condition_tag": "source_charge_counters_at_least",
    "condition_args": [2]
}
```

No emit-arm change.

### 5.2 Rust parse arm widen

**File:** `rust/src/cards.rs:15191-15199`. As shown in §4.2
above, the whitelist check widens to accept the new
condition_tag.

### 5.3 Python-side reconstruction arm

**File:** `src/mtg_bot/parity/cross_engine.py` —
`_static_anthem_condition_from_tag` at line 14351-14407.

The rehydrator currently returns:
* `""` → `None` (unconditional)
* `"during_your_turn"` → `DuringYourTurn()`

Phase 2 adds one arm:

```python
# Phase 2 widen — Spacecraft Station Phase 2 (Lumen-Class Frigate):
if cond_tag == "source_charge_counters_at_least":
    if len(cond_args) != 1:
        raise ValueError(
            f"source_charge_counters_at_least takes one arg; "
            f"got {cond_args!r}"
        )
    # The rehydrator emits a Condition-like object whose `matches`
    # signature consumes the source for the charge-counter read.
    # Python's existing `Condition` ABC takes (state, viewer_id);
    # this Condition needs the SOURCE as well. Phase 2 mints a
    # new Condition subclass with a 3-arg matches signature, OR
    # threads the tier_threshold value back onto the StaticAbility's
    # legacy `tier_threshold` slot (the simpler shape — see §5.3a).
    from mtg_bot.effects.conditions import SourceChargeCountersAtLeast
    return SourceChargeCountersAtLeast(int(cond_args[0]))
```

#### 5.3a Alternative: thread `tier_threshold` back to the legacy slot

The parser SoT at the live tree emits Lumen-Class Frigate's
static with **`tier_threshold=2`** and **`condition=None`**
(verified §1.2 walk). The rehydrator could mirror the parser
exactly: emit a Python `StaticAbility` with `tier_threshold=
int(cond_args[0])` and `condition=None` rather than minting
a new `Condition` subclass. This preserves the existing
1:1 parity between the Phase 2-flipped printing and the live
parser printing (Python's anthem-walk in
`game.py::_static_bonuses` already reads `ability.tier_
threshold` for ability-gating — verify-first walk in §5.4
clauses confirms).

**Phase 2 prefers 5.3a (thread back to legacy slot).** Reasons:
1. The parser SoT is the truth-table; mirroring it minimizes
   bridge-vs-parser drift (the round-trip materialized
   printing reads byte-identical to a fresh parser parse).
2. No new Python `Condition` subclass needed — `tier_
   threshold` is an existing `StaticAbility` field
   (`cards/base.py:559` per Phase 1 doc cross-refs).
3. The Rust side STILL routes through the condition_tag
   dispatcher (§4.1) because the Rust `StaticAnthem` slot has
   `condition_tag: String + condition_args: Vec<i32>`, not a
   `tier_threshold: i32`. The bridge ENCODES tier_threshold
   AS a condition_tag arm, but Python reconstructs back to
   the legacy slot. Asymmetric but bridge-clean — same
   pattern the warp_cost substrate uses (Python carries
   `warp_cost: ManaCost`; the bridge dict carries
   `warp_cost_generic` + `warp_cost_colored` separately).

The rehydrator under 5.3a:

```python
# Phase 2 — Spacecraft Station Phase 2 — alternative (preferred):
# The condition_tag "source_charge_counters_at_least" rehydrates to
# a sentinel-None Condition; the tier_threshold int rides up to the
# StaticAbility's legacy `tier_threshold` slot (handled by the
# anthem-static rehydration site, NOT this helper). The helper
# returns None for this tag so the rehydrated StaticAbility's
# `condition` field is None — matching the parser SoT.
if cond_tag == "source_charge_counters_at_least":
    if len(cond_args) != 1:
        raise ValueError(...)
    return None  # tier_threshold threaded separately
```

The anthem-static rehydration site at
`cross_engine.py:14627-14687` then reads the condition_args
and threads them onto the rehydrated `StaticAbility`'s
`tier_threshold` field:

```python
# Phase 2 widen at cross_engine.py:14660-14687 (the
# `_card_def_to_python_printing` anthem rehydration loop):
cond = _static_anthem_condition_from_tag(condition_tag, condition_args)
# Phase 2 — Spacecraft Station Phase 2:
# Thread tier_threshold back to the legacy slot for the new
# condition_tag. The parser SoT emits `tier_threshold=N, condition=
# None` for Lumen-Class Frigate; mirror exactly.
extra_kwargs = {}
if condition_tag == "source_charge_counters_at_least":
    extra_kwargs["tier_threshold"] = int(condition_args[0])
if power_bonus or toughness_bonus:
    sa_list.append(
        StaticAbility(
            scope=scope,
            condition=cond,
            continuous_effect=ContinuousModifier(
                layer=7,
                payload=PowerToughnessBonus(
                    power_bonus=int(power_bonus),
                    toughness_bonus=int(toughness_bonus),
                ),
            ),
            **extra_kwargs,
        )
    )
```

### 5.4 New admit predicate

**File:** `src/mtg_bot/parity/trajectory.py` (sibling to
`_printing_is_bridge_pure_station_spacecraft` from Phase 1
and `_printing_is_bridge_static_anthem_pt_conditional_warp_
creature` from MTL Phase-4 cycle 2):

```python
def _static_ability_is_phase_2_spacecraft_anthem(ability) -> bool:
    """True iff `ability` is a Phase-2 bridge-admittable
    Spacecraft anthem static — an `other_creatures_you_control`
    or `creatures_you_control`-scope layer-7 PowerToughnessBonus
    gated by `tier_threshold >= 1` (charge-counter gate on the
    source) with no other rider.

    **Spacecraft Station substrate — Phase 2 (sub-shape B;
    Lumen-Class Frigate).** Mirrors the shape `parser/statics.py`
    emits for Lumen-Class Frigate's "While this Spacecraft has
    two or more charge counters, other creatures you control
    get +1/+1." line. The §2 teeth:

      * `scope` is `creatures_you_control` or
        `other_creatures_you_control`.
      * `tier_threshold >= 1` (Phase 2's load-bearing new gate).
      * `condition` is `None` (the parser does NOT compose a
        `DuringYourTurn`-style rider WITH `tier_threshold` for
        Lumen-Class Frigate; Phase 2 explicitly admits only the
        `tier_threshold`-only shape — composed shapes are a
        future widen).
      * `continuous_effect` is a layer-7
        `ContinuousModifier(PowerToughnessBonus(p, t))`.
      * `subject_filter` on the modifier is `None`.
      * `replacement_effect` is `None`.
      * `granted_keywords` empty (Phase 2 carriers don't ride a
        keyword grant — future widen).
      * `room_half is None`, `grants_no_max_hand_size=False`,
        `grants_creature_spells_uncounterable=False`.
      * The legacy `power_bonus`/`toughness_bonus` slot is empty
        (payload rides the ContinuousModifier).
    """
    from mtg_bot.cards.base import StaticScope
    from mtg_bot.effects.modifiers import (
        ContinuousModifier, PowerToughnessBonus,
    )

    if ability.scope not in (
        StaticScope.CREATURES_YOU_CONTROL,
        StaticScope.OTHER_CREATURES_YOU_CONTROL,
    ):
        return False
    if not ability.tier_threshold or ability.tier_threshold < 1:
        return False
    if ability.condition is not None:
        return False  # composed shapes deferred
    if ability.power_bonus or ability.toughness_bonus:
        return False
    if ability.granted_keywords:
        return False
    if ability.replacement_effect is not None:
        return False
    if ability.room_half is not None:
        return False
    if ability.grants_no_max_hand_size:
        return False
    if ability.grants_creature_spells_uncounterable:
        return False
    ce = ability.continuous_effect
    if ce is None or not isinstance(ce, ContinuousModifier):
        return False
    if ce.layer != 7:
        return False
    if not isinstance(ce.payload, PowerToughnessBonus):
        return False
    if getattr(ce, "subject_filter", None) is not None:
        return False
    return True


def _printing_is_bridge_phase_2_static_anthem_spacecraft(
    printing,
) -> bool:
    """True iff a CardPrinting is a Phase-2 bridge-supported
    static-anthem Spacecraft — the Phase-1 sub-shape A clauses
    EXCEPT static_abilities is replaced with a positive
    one-static allowlist via
    :func:`_static_ability_is_phase_2_spacecraft_anthem`.

    Spacecraft Station substrate — Phase 2 (sub-shape B; spec at
    docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_2_DESIGN.md). Pilot:
    Lumen-Class Frigate (station_threshold=12, stationed_keywords
    ={flying, lifelink}, 3/5, {1}{W}, one tier_threshold=2 anthem
    static +1/+1 to other creatures you control).
    """
    if "Spacecraft" not in printing.subtypes:
        return False
    if printing.station_threshold is None:
        return False  # Phase 4 only (The Eternity Elevator)
    if printing.station_threshold <= 0:
        return False
    if printing.triggered_abilities:
        return False  # Phase 3 (5 carriers)
    if printing.activated_abilities:
        return False  # Phase 4 (The Eternity Elevator)
    # Static abilities — POSITIVE allowlist of the Phase-2
    # Spacecraft-anthem shape. Empty static_abilities falls back
    # to the Phase-1 `_pure_station_spacecraft` arm (already
    # in production); this predicate specifically admits the
    # ONE-anthem shape.
    if not printing.static_abilities:
        return False  # Phase-1 path covers zero-static
    if len(printing.static_abilities) != 1:
        return False  # exactly one anthem (no composed multi-static)
    if not _static_ability_is_phase_2_spacecraft_anthem(
        printing.static_abilities[0]
    ):
        return False
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
        return False  # Phase-2 carrier has empty baseline keywords
    if not printing.stationed_keywords:
        return False
    for kw in printing.stationed_keywords:
        if kw not in _SAFE_KEYWORDS:
            return False
    if printing.grants_toughness_as_station_power_for_creatures_you_control:
        return False  # Tapestry Warden flag — Phase-3+ widen
    try:
        _parse_mana_cost_string(printing.mana_cost_str or "")
    except ValueError:
        return False
    return True
```

### 5.5 Admit-predicate registration

The new predicate is registered as a parallel admit-disjunct
in the loader's filter at
`_filter_deck_to_bridge_supported`, sibling to the Phase-1
disjunct `_printing_is_bridge_pure_station_spacecraft`. The
full filter becomes
`existing_predicate(printing) OR
_printing_is_bridge_pure_station_spacecraft(printing) OR
_printing_is_bridge_phase_2_static_anthem_spacecraft(printing)`.
The positive Phase-2 admit set is **exactly Lumen-Class
Frigate** (no other EoE printing matches every clause —
verified §6.4 below).

## 6. Test plan — substrate units + bridge round-trip + per-card real-EoE probes + no-silent-auto-grow

### 6.1 Substrate unit pins (Rust + Python)

1. **Rust dispatcher new arm:** `static_anthem_condition_
   matches` with `condition_tag="source_charge_counters_at_
   least", condition_args=vec![2]` against a synthetic
   source `GameObject` with `charge_counters` ∈ {0, 1}
   returns `false`; with `charge_counters` ∈ {2, 3, 100}
   returns `true`. Args list length-0 and length-2 raise
   (caller is expected to validate via the parser; the
   dispatcher reads `args[0]` directly).
2. **Rust reader-fold pass-through:** `static_anthem_pt_
   bonus_for` on a target creature where the source
   Spacecraft has `charge_counters < tier_threshold`
   returns `(0, 0)`; with `charge_counters >= tier_
   threshold` returns `(power_bonus, toughness_bonus)`.
3. **Rust `battlefield_has_keyword`:** identical gate
   behavior for keyword-bearing anthems (Phase 2 doesn't
   admit a keyword-anthem carrier, but the dispatcher arm
   composes consistently across both reader sites).
4. **Rust parse-arm:** the registry-build path
   round-trips `condition_tag="source_charge_counters_at_
   least", condition_args=[2]` through `parse_printing` /
   `to_pydict`. Unknown tag raises at parse time.
5. **Python admit predicate (`_printing_is_bridge_phase_
   2_static_anthem_spacecraft`):** returns `True` for the
   live Lumen-Class Frigate printing; returns `False` for
   every other live Spacecraft printing (the §6.4 decline-
   set check).
6. **Python rehydrator round-trip:** a CardDef carrying
   the 6-tuple `("other_creatures_you_control", (), 1, 1,
   "source_charge_counters_at_least", (2,))` materializes
   a `CardPrinting` whose single `StaticAbility` has
   `tier_threshold=2, condition=None, continuous_effect.
   payload=PowerToughnessBonus(1, 1)` — bit-identical to
   the live-parser SoT.

### 6.2 Cross-engine bridge round-trip pins

7. **Synthetic Phase-2 carrier round-trip:** a DeckSpec
   with a synthetic CardDef
   `subtypes=("Spacecraft",), station_threshold=3,
   stationed_keywords=("flying",), power=2, toughness=3,
   mana_cost_str="{2}{W}", static_anthems=(("other_
   creatures_you_control", (), 1, 1, "source_charge_
   counters_at_least", (2,)),)`: build Rust state via
   `build_rust_state` → fingerprint byte-equal across
   engines pre-ETB.
8. **Anthem activation across the gate:** with the
   synthetic Phase-2 carrier on battlefield AND an own
   vanilla 2/2 creature, drive ActivateStation twice
   (push `charge_counters` 0 → 1 → 2) through `step_
   both` → byte-equal post-state, AND the vanilla
   creature's combat-pass P/T reader returns `(2, 2)` at
   `charge_counters=1` (anthem gate closed) and `(3, 3)`
   at `charge_counters=2` (anthem gate open).
9. **Action-set invariance pin:** both engines'
   `legal_actions` emit the SAME set (and positional
   order) of ActivateStation actions across the gate
   boundary; the action set does NOT include any
   anthem-specific decision (anthems are static — no
   stack object).
10. **Stationed vs anthem composition:** at `charge_
    counters=12` (Lumen-Class Frigate's
    station_threshold), the Spacecraft itself is now a
    creature; the anthem applies to OTHER creatures the
    controller controls (NOT to the Spacecraft itself —
    `other_creatures_you_control` scope per §1.2 walk).
    Both engines' P/T reader on the Spacecraft returns
    `(3, 5)` (printed P/T, NOT `(4, 6)`); both engines'
    P/T reader on each other own creature returns
    `printed + (1, 1)`.

### 6.3 Real-EoE per-card probe (Lumen-Class Frigate)

A `tests/test_parity_smoke.py` probe (insert immediately
above the `# === SPACECRAFT_PHASE2_PROBES_INSERT_ABOVE_
THIS_LINE ===` sentinel — convention from Phase 1) that
drives the **actual Lumen-Class Frigate printing**
(resolved via the live `OracleParserCardSource`, NOT a
synthetic CardDef — round-46 real-EoE-signal discipline)
on **both** engines through four scenarios across the
charge-counter axis:

- **Scenario A — un-stationed (charge_counters=0):** cast
  Lumen-Class Frigate + pass; assert byte-equal post-cast
  fingerprint (mana pool / zones / `charge_counters=0`);
  assert anthem-gate closed (other creatures' P/T reads
  printed values); assert no ActivateStation actions
  emitted at instant speed.
- **Scenario B — anthem-gate-open, station-gate-closed
  (`charge_counters=2`):** with Lumen-Class Frigate on
  battlefield + two own untapped vanilla 1/1 creatures,
  drive ActivateStation twice (vanilla A → Sawship,
  vanilla B → Sawship — Phase 1's Sawship is irrelevant
  to the load-bearing assertion); push to `charge_
  counters=2`; assert byte-equal post-state +
  `charge_counters=2`; assert the OTHER own vanilla
  creature's effective P/T is now `(2, 2)` (printed
  `(1, 1)` + anthem `(1, 1)`); assert the Spacecraft
  itself is still NOT a creature (`12 > 2`); assert
  combat does not enumerate the Spacecraft as a legal
  attacker.
- **Scenario C — anthem-gate-closed-again (drop counters):**
  there is no Phase-2 mechanic in the EoE pool for
  REMOVING charge counters from a Spacecraft (the only
  charge-counter-add Effect is `PutChargeCountersOn
  TargetSpacecraftOrPlanetYouControl`; nothing removes).
  Scenario C is therefore replaced with a **start-of-
  next-turn pin**: confirm the anthem state SURVIVES
  the turn rollover (cleanup step, untap step) byte-
  equal on both engines; confirm the anthem state RESETS
  when the Spacecraft leaves the battlefield (CR 400.7
  per-zone-reset already wired Phase 1 cycle 1) — assert
  bouncing the Spacecraft to hand (synthetic bounce
  spell) drops every other creature's P/T back to
  printed.
- **Scenario D — anthem AND station gate open
  (`charge_counters=12+`):** with Lumen-Class Frigate
  stationed (12+ counters), assert the Spacecraft is now
  a 3/5 with flying + lifelink (Phase 1 station-flip
  + keyword fold); assert OTHER creatures still receive
  the +1/+1 anthem (the source's animation tick does not
  change anthem applicability — `other_creatures_you_
  control` scope); assert the Spacecraft itself does NOT
  receive the anthem (it is `other` to itself only when
  scope is `other_creatures_you_control`).

**Bench-strategy coverage note:** as with Phase 1's Sawship
probe, the bench's `attack_all` strategy may not naturally
produce the "queue-N-ActivateStations-then-test-anthem"
line. The probe MUST use a scripted picker
(`tests/parity/_picker_shims.py` helper extended) that
forces the activation sequence so each scenario is actually
exercised. The implementing agent confirms; the SL entry
(§8) pins this as probe-driven, not organic.

### 6.4 Decline-set bench check (no-silent-auto-grow)

A negative-set bench check at the loader filter,
parametrized over the 6 still-deferred Spacecraft (post-
Phase-2 admit) and the same Tapestry-Warden-style 0-deck
proxy from Phase 1:

11. `_printing_is_bridge_phase_2_static_anthem_
    spacecraft(<live Larval Scoutlander>)` returns `False`
    (carries `triggered_abilities`).
12. `(<live Sledge-Class Seedship>)`, `(<live Synthesizer
    Labship>)`, `(<live Entropic Battlecruiser>)`,
    `(<live Infinite Guideline Station>)` all return
    `False` (each carries `triggered_abilities`).
13. `(<live The Eternity Elevator>)` returns `False`
    (`station_threshold is None` AND `activated_abilities`
    non-empty).
14. **Subsystem-attribution pin:** exactly 1 EoE printing
    passes `_printing_is_bridge_phase_2_static_anthem_
    spacecraft` (Lumen-Class Frigate) — the guardrail's
    positive set is exhaustive for Phase 2.
15. **Decline-set bench check:** with the EoE deck pool
    loaded, confirm the bench's loader-side filter admits
    +1 card (Lumen-Class Frigate) over the Phase-1
    post-PROBE baseline, with 0 spillover into any of the
    6 still-deferred Spacecraft.
16. **No-silent-auto-grow pin:** with a Tapestry-Warden
    carrier injected into a synthetic deck (a CardDef
    setting `grants_toughness_as_station_power_for_
    creatures_you_control=True`) AND a static-anthem,
    confirm `_printing_is_bridge_phase_2_static_anthem_
    spacecraft` returns `False`. This pins the §3.5
    asymmetry against accidental admission in a future
    bench-data refresh.
17. **Composed-shape no-silent-auto-grow pin:** a
    synthetic Spacecraft carrying BOTH a Phase-2 anthem
    static AND a triggered ability (the future-composed
    shape from §3.3) is rejected by Phase 2's admit
    predicate. Pins the predicate against accidental
    admission of any future composed-shape printing
    before Phase 3 lands.

### 6.5 MTL substrate non-regression pin

18. **Memorial Team Leader does NOT silent-flip into the
    Phase-2 Spacecraft predicate.** MTL carries a static-
    anthem under `DuringYourTurn`, not `tier_threshold` —
    `_printing_is_bridge_phase_2_static_anthem_spacecraft`
    must positively reject it (`"Spacecraft" not in
    subtypes` short-circuits at the first clause).
19. **MTL's anthem fold STILL fires unchanged on the
    existing `_printing_is_bridge_static_anthem_pt_
    conditional_warp_creature` disjunct.** The cross-
    engine round-trip pins for MTL must remain byte-
    equal post-Phase-2 substrate landing (the new
    condition_tag arm widens the parser whitelist
    without re-routing MTL's existing tag).

## 7. Estimated cycle count

Per the per-card multi-cycle precedent established by Phase 1
(4 cycles for one card with a new Action variant + bridge
+ probe) and the lighter Lumen-Class Frigate scope (no new
Action, one dispatcher arm, one admit sibling):

| Cycle | Owner | Deliverable |
|---:|---|---|
| 1 | Rust agent | Substrate landing: new `source_charge_counters_at_least` condition_tag arm in `static_anthem_condition_matches` (signature widened to thread source `GameObject`) + caller-site pass-through at `battlefield_has_keyword` + `static_anthem_pt_bonus_for` + parser whitelist widen at `cards.rs:15191` + Rust substrate unit pins (§6.1.1-§6.1.4). **Sole Rust slice of cycle 1** (`.pyd` race rule against Worker B's parallel Carrier-AA Phase 2b). |
| 2 | Python/bench agent | Bridge round-trip rehydrator widen (§5.3, §5.3a) + `_static_ability_is_phase_2_spacecraft_anthem` + `_printing_is_bridge_phase_2_static_anthem_spacecraft` admit predicate (§5.4) + admit registration (§5.5) + Python substrate unit pins (§6.1.5-§6.1.6) + cross-engine bridge round-trip pins (§6.2 1-4) + Lumen-Class Frigate real-EoE probe Scenarios A & B (§6.3) + decline-set bench check (§6.4 pins 11-15) + MTL non-regression pin (§6.5 18-19) — Lumen-Class Frigate FLIP from DECLINED → ADMITTED. |
| 3 | Bench agent | Lumen-Class Frigate real-EoE probe Scenarios C & D (§6.3 — turn-rollover + bounce + anthem-and-station-both-open) + composed-shape no-silent-auto-grow pin (§6.4 pin 17) + Tapestry-Warden no-silent-auto-grow pin (§6.4 pin 16) + pool-parity regen + SL §8 entries. |

**Estimated total: ~3 cycles for Phase 2**, sitting at the
lower bound of the Phase-1 doc's "Phase 2 (Lumen-Class
Frigate, ~2-3 cycles)" estimate. Cycle 1 may spill to 2 if
the dispatcher signature widen surfaces unexpected
threading at `battlefield_has_keyword` (the call site
already iterates source; the widen is mechanical, but the
walk-shape may require a sibling helper at one of the two
sites). Cycle 2 may spill to 3 if the rehydrator's choice
between §5.3 (new Condition subclass) and §5.3a (thread
back to legacy slot) surfaces a parity divergence vs the
live parser — verify-first walk in the implementing
cycle's first hour will lock the choice.

**Subsequent phases (unchanged from Phase 1 §7 sequencing):**

- **Phase 3 (5 trigger carriers, ~6-10 cycles):** 5 distinct
  Effect-class Rust slices + 2 `tier_threshold`-gated
  trigger-firing predicates (the latter reusing Phase 2's
  condition_tag dispatch arm) + 5 admit widens + 5
  per-card real-EoE probes.
- **Phase 4 (The Eternity Elevator, ~2 cycles):**
  depends on Worker B's parallel Carrier-AA campaign
  Phase 1+ + 1 new `AddChargeCounterManaOfChosenColor`
  Effect class + per-card real-EoE probe.

**Campaign total: ~13-19 cycles remaining across Phase 2 /
3 / 4** to close the 7-card / ~35,343-deck residue, well
within Phase 1's `~16-22 cycles across Phase 1 / 2 / 3 / 4`
campaign estimate (Phase 1 closed in 4 cycles).

## 8. SEARCH_LIMITATIONS.md entries (land WITH Phase 2 cycle 1+2)

Two entries (estimated):

1. **Phase 2 Spacecraft admit accepts only single-static
   anthem-PT-with-`tier_threshold` shape; composed multi-
   static / keyword-anthem / non-`tier_threshold`-
   conditional shapes deferred.** Location:
   `_printing_is_bridge_phase_2_static_anthem_spacecraft`
   + `_static_ability_is_phase_2_spacecraft_anthem`. Why
   OK: the predicate positively rejects every non-Phase-2
   shape on BOTH bridge sides; no Spacecraft in the live
   pool carries a composed-shape today; the no-silent-
   auto-grow pin (§6.4 pin 17) guards against accidental
   admission of a future composed-shape printing. Failure
   mode: a future bench-data refresh adding a composed-
   shape printing without widening the admit predicate
   would silently mis-route through the Phase-1 zero-
   ability arm (which rejects on `static_abilities` —
   safe-decline) or get caught by the Phase-2 disjunct's
   single-static gate. Fix-scope: a sibling Phase-2.5
   predicate per future-composed-shape; impact = 0 today.
2. **Anthem-scope condition vocabulary expands ONLY by
   dispatcher arms — no whole-cloth Condition subclasses
   per arm.** Location: `static_anthem_condition_matches`
   + `_static_anthem_condition_from_tag`. Shortcut: the
   dispatcher reads `condition_tag` + `condition_args`,
   not a full Condition object; the rehydrator threads
   args back to the legacy `StaticAbility.tier_threshold`
   slot rather than minting a new `SourceChargeCounters
   AtLeast` Condition subclass. Why OK: the parser SoT
   for Lumen-Class Frigate emits `tier_threshold=2,
   condition=None`; mirroring exactly minimizes
   bridge-vs-parser drift. Failure mode: a future
   Phase-N carrier requires a condition shape with
   args >1 or non-int args, which the current `Vec<i32>`
   shape can't represent; fix-scope = a per-Phase
   condition_args schema widen, similar to how
   `triggered_abilities` carry a `"kind"` discriminator
   plus a payload dict. Impact: 0 today.

## 9. Rejected alternatives

### 9.1 Land Phase 2 as a wholesale rewrite of the anthem-condition system

**Rejected — single-card slice discipline.** Phase 2 lands
ONE new condition_tag arm + ONE new admit sibling. A
generalized "anthem condition framework" would inflate
scope without any single-card payoff beyond Lumen-Class
Frigate. The condition_tag dispatch pattern is already
extensible; Phase 2 uses it as designed.

### 9.2 Add `tier_threshold: i32` field to `StaticAnthem` instead of using condition_tag

**Rejected — bifurcates the gate-walk.** A separate field
would require TWO gate-checks in the reader fold (one for
condition_tag, one for tier_threshold), splitting the
extension point. The condition_tag arm composes naturally
with Phase 3's trigger-firing site (the same
`source_charge_counters_at_least` predicate). See §4.1
decision rationale for the full comparison.

### 9.3 Land Lumen-Class Frigate via a NEW Condition subclass `SourceChargeCountersAtLeast` rather than threading `tier_threshold` to the legacy slot

**Rejected — bridge-vs-parser drift.** The parser SoT emits
Lumen-Class Frigate's static with `tier_threshold=2,
condition=None` (verified §1.2 walk). Minting a new
Condition subclass on the bridge-rehydrated printing would
make the bridge round-trip's materialized `CardPrinting`
read `tier_threshold=0, condition=SourceChargeCounters
AtLeast(2)` — bit-different from the parser-fresh
printing on the same field. The §5.3a choice
(thread back to legacy slot) preserves parser parity. See
§5.3 / §5.3a discussion for the full rationale.

### 9.4 Bundle Phase 2 + Phase 3 (anthem + triggers)

**Rejected — Phase 3 is per-card 1-2 cycles × 5 cards.**
Bundling inflates Phase 2 to a ~10-cycle behemoth that
blocks the Lumen-Class Frigate signal for the entire
bundle's duration. Phase 2 ships 1 card in ~3 cycles;
Phase 3 ships the trigger carriers one at a time per
distinct Effect class.

### 9.5 Widen Phase 1's `_printing_is_bridge_pure_station_spacecraft` to accept a single anthem static

**Rejected — Phase 1's admit shape is locked as zero-
ability.** Widening would re-open Phase 1's tests + the
SL §9 entry pinning "Phase 1 supports only the zero-
ability Spacecraft carrier" (Phase 1 SL entry #1). The
clean separation — Phase 1 = zero-ability,
Phase 2 = single-static — preserves the per-cycle no-
silent-auto-grow discipline. Each phase has its own
sibling predicate; the OR-chain composition at
`_filter_deck_to_bridge_supported` carries both.

### 9.6 Re-classify Lumen-Class Frigate's static as a self-scope conditional rather than an anthem

**Rejected — scope is `other_creatures_you_control`, not
`SELF`.** The parser SoT (§1.2 walk) emits scope=
`other_creatures_you_control`; routing through
`_printing_is_bridge_simple_static_self_conditional_
creature` (Phase 3 of the static-abilities-layered
substrate at `trajectory.py:9742-9836`) would mis-classify
the scope axis. The clean shape is the anthem-side
predicate, which positively reads `other_creatures_you_
control` + `creatures_you_control` (the two scopes the
MTL Phase-4 substrate already handles).

## 10. Acceptance / sign-off

Phase 2 is complete and ready to merge to `main` when:

1. All 19 pins (§6.1-§6.5) pass on the parity gate.
2. The Lumen-Class Frigate real-EoE probe (§6.3) passes
   byte-equal through all four scenarios on both engines.
3. The decline-set bench check confirms +1 card admitted
   (Lumen-Class Frigate), 0 spillover across the 6 still-
   deferred Spacecraft.
4. The MTL non-regression pin (§6.5) confirms the
   condition_tag whitelist widen does not affect MTL's
   existing anthem path.
5. Both SL entries (§8) land alongside the substrate code.
6. `.pyd` rebuilt clean; the parity gate (`tests/test_
   parity_smoke.py + test_cross_engine_etb_triggers.py +
   test_trajectory_parity.py + test_trajectory.py +
   test_measure_pool_parity.py`) stays green at 32/32
   (and bumps to N+1 on the per-probe count).
7. `scripts/scout_r58_subsystem_attribution.py` re-run:
   the `station_spacecraft` row's BLOCKED-SG count drops
   from 7 → 6; pool BLOCKED-SG total drops by 1; PROBED
   total bumps +1.

## 11. Cross-references

- `docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_1_DESIGN.md` —
  the Phase 1 design doc this Phase 2 extends; format
  precedent + the 7 deferred carriers' classification
  table this Phase 2 inherits.
- `docs/CARRIER_AA_SUBSTRATE_PHASE_2_DESIGN.md` — the
  parallel Carrier-AA Phase 2 scoping doc (Worker B's
  lane in flight); format precedent + the parallel
  campaign sequencing template (Phase 2a + Phase 2b).
- `docs/COVERED_BY_CONSTRUCTION_PROBE_WRITING_SATURATION_
  2026-05-25.md` — the 2026-05-25 saturation report that
  motivated the BLOCKED-SG subsystem pivot the Spacecraft
  Station campaign is the #2 row of.
- `docs/MULTI_GATED_TAIL_TRACTABILITY_RESCOUT_2026-05-24.
  md` — entry #5 pins Lumen-Class Frigate as Phase-2-
  feasible-once-substrate-lands; this Phase 2 closes it.
- `docs/SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY.md` §2 line
  1042, §5 line 1115 — Lumen-Class Frigate's
  authoritative multi-gated leverage data
  (Station + static co-blockers).
- `src/mtg_bot/cards/base.py:559` — Python's
  `StaticAbility.tier_threshold: int` field (the legacy
  slot Phase 2 threads through per §5.3a).
- `src/mtg_bot/cards/base.py:564-565` — Python's
  `station_threshold` + `stationed_keywords` (Phase 1
  substrate, reused unchanged).
- `src/mtg_bot/parity/trajectory.py:9839-9930` — MTL
  Phase-4 anthem-PT-conditional admit helper (the format
  precedent for Phase 2's new admit helper).
- `src/mtg_bot/parity/trajectory.py:9933-10085` — MTL
  Phase-4 admit predicate (the format precedent for
  Phase 2's new admit predicate).
- `src/mtg_bot/parity/cross_engine.py:13692-13750` — the
  `static_anthems` 6-tuple emit (reused unchanged; Phase 2
  fills the existing `condition_tag` + `condition_args`
  fields with new values).
- `src/mtg_bot/parity/cross_engine.py:14351-14407` — the
  `_static_anthem_condition_from_tag` rehydrator (Phase 2
  adds one arm).
- `src/mtg_bot/parity/cross_engine.py:14627-14687` — the
  anthem-static rehydration loop (Phase 2 adds the
  `tier_threshold` thread-through per §5.3a).
- `rust/src/cards.rs:10872-10906` — Rust's `StaticAnthem`
  slot (reused unchanged; Phase 2 fills `condition_tag` /
  `condition_args` with new values).
- `rust/src/cards.rs:15191-15199` — Rust's parser
  whitelist (Phase 2 adds one entry).
- `rust/src/state_ops_combat.rs:737-747` — Rust's
  `static_anthem_condition_matches` dispatcher (Phase 2
  adds one arm + widens the signature).
- `rust/src/state_ops_combat.rs:769-810` — Rust's
  `static_anthem_pt_bonus_for` reader fold (Phase 2
  threads source through the dispatcher call).
- `rust/src/state_ops_combat.rs:660-710` — Rust's
  `battlefield_has_keyword` (sibling call site; same
  thread-through).

## 12. Regenerating the enumeration

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
  scripts/scout_r58_subsystem_attribution.py
```

reproduces the 7-member Spacecraft BLOCKED-SG residue
exactly (0 single-gated post-Phase-1; 7 multi-gated). The
per-card live parsed printings (§2 table) are verifiable
via `OracleParserCardSource().get_printings()[<name>]` —
walk `station_threshold`, `stationed_keywords`,
`static_abilities`, `triggered_abilities`,
`activated_abilities`. All §4 / §5 file:line refs verified
against main `7e07400f`.
