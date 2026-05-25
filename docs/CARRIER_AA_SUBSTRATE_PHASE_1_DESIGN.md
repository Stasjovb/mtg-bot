Generated 2026-05-25 (post `cost-reduction-phase-3-cycle-1-substrate-
p1`, merge `8525d18e`). **Design only — NO production / `_SAFE_*` /
Rust change in this slice; no gate run beyond the 31/31
`tests/test_measure_pool_parity.py` baseline** (docs + read-only
scout against the live tree). This doc scopes the Carrier-AA
(activated-ability bridge admit for **non-token CardPrinting
carriers**) substrate as a multi-cycle CAMPAIGN per the saturation
report's highest-leverage DEFERRED row, in the gold-standard format
of `docs/COST_REDUCTION_SUBSTRATE_PHASE_1_DESIGN.md`. Every file:line
below is verified against the live tree at main `8525d18e`.

> **Relationship to `docs/COVERED_BY_CONSTRUCTION_PROBE_WRITING_SATURATION_2026-05-25.md`.**
> That doc closes the bare-bridge-clean Effect-class probe-writing
> lane after 13 batches and identifies Carrier-AA widening as the
> highest-leverage DEFERRED pivot (30 cards / 34,470 17lands decks,
> the largest still-blocked subsystem by aggregate deck count after
> the diffuse Effect-uncovered residue). This doc is the campaign-
> level entry point for that pivot.
>
> **Relationship to the token-AA bridge work** (round-52 + Cycle 3
> Eldrazi Scion). The token-side AA admit infrastructure — CardDef
> `token_activated_abilities` field + `_aa_dict_to_python_activation_cost`
> + `_aa_dict_to_python_activated_ability` + the Lander
> (`_token_with_safe_activated_ability_card_def`,
> `trajectory.py:3208-3337`) and Eldrazi Scion
> (`_token_creature_with_safe_mana_activated_ability_card_def`,
> `trajectory.py:3339-3491`) helpers — is the **non-token-Carrier-AA
> work's direct precedent.** The bridge dict-level
> (`_aa_dict_to_python_activated_ability`) ALREADY supports a
> non-token-AA round-trip; Carrier-AA Phase 1 is, structurally, the
> *non-token* counterpart that consumes the same dict-level bridge
> on a non-token-printing carrier. The codec is shared; only the
> admit predicate + CardDef wiring + the "bridge an authored
> CardPrinting" path differ.

# Carrier-AA substrate Phase 1 — campaign scoping doc (sub-shape A: bare single-`{T}`-cost, single-bridged-Effect Land carriers — pilot pair `Swarmyard` + `Deserted Temple`)

## 0. Executive summary

The **Carrier activated abilities** subsystem at live HEAD `8525d18e`
binds **30 cards / 34,470 17lands decks** (per
`docs/POOL_PARITY.md`'s BLOCKED-SG breakout table at line 452 +
`docs/SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY.md` §2 line 1043). All 30
are **multi-gated** — closing the Carrier-AA admit gate alone flips
**zero** of them, because every BLOCKED-SG carrier-AA card co-trips
at least one other gate (the `effect_uncovered` co-gate fires on 30
/ 30; the `nonsafe_triggered_ability` co-gate fires on 8 / 30; the
`station_spacecraft` co-gate fires on 1 / 30 — verified by the
scout walk in §2 below). **The Carrier-AA gate's `1gate` column
shows 0 single-gated decks today; deck-count leverage is realised
ONLY when a carrier's AA Effect simultaneously closes its
`effect_uncovered` co-gate** — i.e. the AA's emitted Effect must
ALSO be bridge-covered for the card to flip.

This doc scopes the substrate's **Phase 1**: admit ONLY the
narrowest sub-shape A — **bare single-`{T}`-cost,
non-mana-ability, single-bridged-Effect, no-rider non-token Land
carriers with no triggered/static abilities and no other carrier
features**. The pilot is the **`Swarmyard` + `Deserted Temple`**
pair (each is a single-AA `{T}: <effect>` Land with NO triggered /
NO static / NO co-gate beyond the AA Effect itself; each "decks(1g)
unlock" requires the AA Effect bridge to also land Phase 1, which
makes them a paired substrate + Effect-class slice rather than a
pure admit-only widen).

The pilot Effect classes (`RegenerateTargetCreature` and
`UntapTargetLand`) are NOT bridge-covered today (verified by
`measure_pool_parity.covered_python_class_set()` — both return
`False`); Phase 1 ports the substrate (Rust-side activated-ability
parse arm for a NON-token CardPrinting + bridge round-trip + admit
predicate) AND lands BOTH single-AA Effect classes in lockstep, so
both Land cards flip together. Subsequent phases (Phase 2 / 3 / N)
extend the admit predicate to: additional bare-`{T}` Effects
(Swarmyard's siblings on the remaining Lands list), `{T}, Sac:`
cost shape (Petrified Field / Mirrorpool / Ghost Vacuum), the
`<empty-cost>` Equipment-AA shape (Atomic Microsizer + Auxiliary
Boosters + Baseball Bat + Saw — co-gated `nonsafe_triggered_ability`
and so blocked behind a triggered-ability-shape widen as well),
the activate-only-once / tier_threshold / room_half /
spend_restriction riders, multi-AA carriers, and Creature carriers
(Sliver Overlord).

Estimated campaign scope (calibrated against the cost-reduction
campaign at `docs/COST_REDUCTION_SUBSTRATE_PHASE_1_DESIGN.md` §1.3:
~10 cycles across Phase 1 / 2 / 3 to close 5 cards / 53,648 decks):
**Carrier-AA Phase 1 = ~4 cycles**, covering the 2 pilot Lands;
**campaign total ~12-18 cycles across Phase 1 / 2 / 3 / N** to
close the 30-card / 34,470-deck row, comparable to (slightly
larger than) the cost-reduction campaign because Carrier-AA's
rider surface is *broader* (sorcery-speed timing, sacrifice / pay-
life / sacrifice-a-desert costs, multi-AA carriers, tier-threshold,
activate-only-once, room-half).

## 1. Background — why this substrate, why now

### 1.1 Saturation context (the falsified next-bare-bridge-clean lane)

`docs/COVERED_BY_CONSTRUCTION_PROBE_WRITING_SATURATION_2026-05-25.md`
documents the conclusion of the bare-bridge-clean Effect-class
probe-writing lane: batches 1-13 (2026-05-24 → 2026-05-25) flipped
62 cards `covered_by_construction → PROBED` under the per-slug
attribution + EEEE-idiom (parse + bridge round-trip + Python-side
resolve, no cross-engine `compare_fields`). After batch 13 (Plaza
of Heroes + Rust Harvester), the bare-bridge-clean candidate pool
is empty: the remaining 38 covered_by_construction cards each
carry a structural bridge-drop rider (categories A-H in the
saturation doc) that the EEEE-idiom cannot sidestep.

The saturation doc's §"Recommended next direction" identifies
Carrier-AA substrate widening as the highest-leverage pivot:

> | Subsystem | #cards | decks(tot) | 1gate | decks(1g) | Tractability |
> |---|---:|---:|---:|---:|---|
> | **Carrier activated abilities** | 30 | 34,470 | 0 | 0 | sprawling |
> | Non-safe triggered ability | 20 | 53,848 | 0 | 0 | diffuse |
> | Effect-uncovered | 45 | 76,035 | 0 | 0 | diffuse |
> | Station / Spacecraft | 8 | 41,281 | 1 | 5,938 | sprawling |
>
> Carrier-AA widening has structural unity: every BLOCKED-SG
> Carrier-AA card shares the same loader-admit-gate question (does
> the production deck loader's `_printing_is_bridge_*` predicate
> accept the AA list shape, or does it §2-decline on the
> activated-abilities non-emptiness check?). A single substrate
> widen here could unblock multiple slugs under a unified admit
> gate.

The 30-card row is **larger by aggregate deck count than every
other named-and-bounded substrate** still deferred (Station 41,281
is mostly multi-gated; cost-reduction-substrate 13,165 is 1 card
behind Phase-2/3 cycles already designed). The diffuse rows
(Non-safe triggered ability, Effect-uncovered) carry larger total
deck counts but are explicitly NOT single-substrate closures
(each is a per-card / per-event-shape tail).

### 1.2 Why "non-token Carrier-AA" specifically

The bridge already supports activated-ability round-trip for
**TOKEN** printings (round-52 N1 Phase-3 precursor, +`Eldrazi Scion`
Cycle 3 today). The dict-level codec at
`src/mtg_bot/parity/cross_engine.py:13768-13929`
(`_aa_dict_to_python_activation_cost` +
`_aa_dict_to_python_activated_ability`) is **shape-agnostic** — it
translates any Rust `parse_activated_ability`-shaped dict into a
Python `ActivatedAbility`, regardless of whether the carrier is a
token or a non-token CardPrinting. The blocker is one level up:

  * `CardDef` carries `token_activated_abilities: tuple[dict, ...]`
    (line 214) — a **token-only** field. There is no
    `activated_abilities` (or
    `carrier_activated_abilities`) field on CardDef for the non-
    token case.
  * `build_rust_state` emits `activated_abilities` into the Rust
    registry dict for token printings (via the token-seating path);
    it omits the key entirely for non-token CardDefs. Rust maps the
    absence to an empty Vec — i.e. the non-token printing arrives
    in Rust with NO activated abilities, period.
  * The loader's bridge-admit predicates (`_printing_is_bridge_simple_creature`
    at trajectory.py:4604-4711, `_printing_is_bridge_basic_land` at
    :7903-:8000, every sibling) carry the explicit
    `if printing.activated_abilities: return False` guard
    (verified at trajectory.py:4684, :4862, :5055, :7738, :7917,
    :7987, :8094, :8246, :8347, :8525, :8680, :8804, :8984, :9249,
    :9475 — 15 sites). Removing any one of those guards without the
    substrate would silently land a `printing.activated_abilities`
    tuple on Python while the Rust mirror has an empty Vec —
    guaranteed cross-engine divergence on the first AA-activation
    decision emit.

So Carrier-AA Phase 1 has three substrates to land in lockstep:

1. **CardDef field for non-token carriers** — analog of
   `token_activated_abilities` for the non-token case (per §5.1).
2. **Bridge round-trip + admit predicate** — analog of
   `_token_with_safe_activated_ability_card_def` /
   `_token_creature_with_safe_mana_activated_ability_card_def`,
   but for a non-token `CardPrinting` (per §5.2-§6).
3. **One or more Rust Effect variants + bridge arms** for the
   AA effect classes the pilot cards emit. (Per §4.4; the
   Swarmyard + Deserted Temple pilot pair needs
   `RegenerateTargetCreature` + `UntapTargetLand` ported in
   lockstep.)

### 1.3 Calibration against cost-reduction

The cost-reduction campaign (`docs/COST_REDUCTION_SUBSTRATE_PHASE_1_DESIGN.md`)
runs ~10 cycles across Phase 1 / 2 / 3 to close 5 cards / 53,648
decks. Carrier-AA is **larger** in scope on three axes:

* **Card count:** 30 vs 5 (6× by card count, ~0.64× by aggregate
  deck count). The per-card decks(tot) is lower individually but
  the total is broader.
* **Rider surface:** cost-reduction's per-rule rider is bounded
  (the `Condition` grammar; 2 variants in Phase 1, ~2 more in
  Phase 2/3 each). Carrier-AA has a richer rider surface — the
  `ActivatedAbility` dataclass alone carries 7 rider fields
  (`sorcery_speed`, `is_mana_ability`, `cost_reductions`,
  `room_half`, `tier_threshold`, `activate_only_once`, plus
  `ActivationCost`'s ~16 cost-component bool fields). The 30-card
  walk in §2 enumerates ~7 distinct cost-shape combinations and
  ~22 distinct Effect classes on AA[0] alone.
* **Effect dependency:** every Phase-1 Carrier-AA card needs its
  AA's emitted Effect to *also* be bridge-covered. The 30-card
  walk in §2 finds only 3 of 22 distinct AA[0] Effect classes are
  bridge-covered today (`PumpCreaturesYouControlUntilEOT`,
  `EquipToTargetCreatureYouControl`, `BecomeLandCreatureUEOT`); the
  remaining 19 each require an Effect-class port to ship at the
  same time as the Carrier-AA admit. Cost-reduction had no Effect
  dependency.

The campaign-total estimate is **~12-18 cycles across Phase 1 /
2 / 3 / N**, comparable to ~1.5-2× cost-reduction. The size delta
is exactly the per-Effect port (each carrier whose AA Effect is
uncovered ships behind a 1-cycle Effect substrate cycle).

## 2. Sub-shape selection — verify-first walk of the 30-card BLOCKED-SG row

Verified live against `OracleParserCardSource` at main `8525d18e`
(walk script logged in §13 for reproducibility; results below are
the 30-card per-printing breakdown by card type / number of AAs /
AA[0] cost shape / AA[0] Effect class / co-gates beyond Carrier-AA
itself).

### 2.1 Per-card breakdown (sorted by 17lands decks)

The 17lands deck counts for these 30 cards individually read 0 in
the worktree-local pool walk (the gitignored
`data/17lands/eoe_decks.json.gz` is absent in worktrees), but the
saturation report's aggregate-row figure of 34,470 decks is the
source of truth (it was computed against the live pool on the main
checkout the morning of 2026-05-25). The per-card walk below
gives card structure + co-gate composition; deck-count leverage
is realized at the aggregate row level.

| # | Card | type | n_aa | AA[0] cost | AA[0] Effect | co-gates beyond AA |
|---:|---|---|---:|---|---|---|
|  1 | All-Fates Scroll      | Artifact          | 2 | `{T}` | `AddManaToPool` (mana-ability) | effect_uncovered (AA[1]'s `DrawCardsByConditionMultiplier`) |
|  2 | Ancient Tomb          | Land              | 1 | `{T}` | `DealDamageToControllerAndAddMana` (mana-ability) | effect_uncovered |
|  3 | **Atomic Microsizer** | Artifact-Equipment| 1 | `<empty>` sorcery-speed | `EquipToTargetCreatureYouControl` | effect_uncovered (trigger), nonsafe_triggered_ability |
|  4 | **Auxiliary Boosters**| Artifact-Equipment| 1 | `<empty>` sorcery-speed | `EquipToTargetCreatureYouControl` | effect_uncovered (trigger), nonsafe_triggered_ability |
|  5 | **Baseball Bat**      | Artifact-Equipment| 1 | `<empty>` sorcery-speed | `EquipToTargetCreatureYouControl` | effect_uncovered (×2 triggers), nonsafe_triggered_ability |
|  6 | Blast Zone            | Land              | 2 | `{T}` | `PutChargeCountersOnSelf` | effect_uncovered (AA[1]'s `DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters`), nonsafe_triggered_ability |
|  7 | Contested War Zone    | Land              | 1 | `{T}` | `PumpCreaturesYouControlUntilEOT` | effect_uncovered (the trigger `ChangeControllerToCombatDamageSource`), nonsafe_triggered_ability |
|  8 | **Deserted Temple**   | Land              | 1 | `{T}` | `UntapTargetLand` | effect_uncovered (AA[0] only) |
|  9 | Ghost Vacuum          | Artifact          | 2 | `{T}` | `ExileTargetCardFromGraveyard` | effect_uncovered (AA[0] + AA[1]) |
| 10 | Grove of the Burnwillows | Land           | 2 | `{T}` mana-ability | `AddManaToPool` | effect_uncovered (AA[1]'s `Sequence`) |
| 11 | Haunted Screen        | Artifact          | 3 | `{T}` mana-ability | `AddNManaOfChosenColor` | effect_uncovered (AA[1]'s pay_life + AA[2]'s activate_only_once `Sequence`) |
| 12 | Keys to the House     | Artifact          | 2 | `{T}, Sac` | `SearchLibraryForCard` | effect_uncovered (AA[0] + AA[1]'s `LockOrUnlockDoorOfTargetRoomYouControl`) |
| 13 | Lavaclaw Reaches      | Land              | 1 | `<cost-mana>` | `BecomeLandCreatureUEOT` (with `granted_activated_abilities` rider — pump `{X}`) | effect_uncovered (the granted AA's `PumpSelfXPowerUEOT`) |
| 14 | Lotus Field           | Land              | 1 | `{T}` mana-ability | `AddNManaOfChosenColor` | effect_uncovered (ETB trigger `SacrificeNLandsYouControl`), nonsafe_triggered_ability |
| 15 | Meteor Crater         | Land              | 1 | `{T}` mana-ability | `AddOneManaOfChosenPermanentColor` | effect_uncovered (state-derived chosen-color) |
| 16 | Mirrorpool            | Land              | 2 | `{T}, Sac` | `CopyTargetInstantOrSorceryYouControl` | effect_uncovered (AA[0] + AA[1]'s `CreateTokenCopyOfTargetCreatureYouControl`) |
| 17 | Mystifying Maze       | Land              | 1 | `{T}` | `ExileTargetAttackingCreatureUntilEndStep` | effect_uncovered (the EoT-return rider) |
| 18 | Nesting Grounds       | Land              | 1 | `{T}` sorcery-speed | `MovePlusOneCounterBetweenPermanentsYouControl` | effect_uncovered |
| 19 | Petrified Field       | Land              | 1 | `{T}, Sac` | `ReturnTargetLandFromGraveyardToHand` | effect_uncovered |
| 20 | Pinnacle Starcage     | Artifact          | 1 | `<empty>` | `Sequence` | effect_uncovered, nonsafe_triggered_ability |
| 21 | Reflecting Pool       | Land              | 1 | `{T}` mana-ability | `AddOneManaFromControlledLandsProductions` | effect_uncovered (state-derived) |
| 22 | Robe of Stars         | Artifact-Equipment| 2 | `<empty>` sorcery-speed | `PhaseOutEquippedCreature` | effect_uncovered (AA[0] + AA[1]'s `EquipToTargetCreatureYouControl` is covered but AA[0] isn't) |
| 23 | **Saw**               | Artifact-Equipment| 1 | `<empty>` sorcery-speed | `EquipToTargetCreatureYouControl` | effect_uncovered (trigger), nonsafe_triggered_ability |
| 24 | Scavenger Grounds     | Land-Desert       | 1 | `{T}, Sac-a-Desert` | `ExileAllGraveyards` | effect_uncovered |
| 25 | Sliver Overlord       | Legendary Creature| 2 | `<empty>` | `SearchLibraryForCard` | effect_uncovered (AA[0] + AA[1]'s `GainControlOfTargetSliverPermanently`) |
| 26 | **Swarmyard**         | Land              | 1 | `{T}` | `RegenerateTargetCreature` | effect_uncovered (AA[0] only) |
| 27 | Terrain Generator     | Land              | 1 | `{T}` | `PutBasicLandFromHandOntoBattlefieldTapped` | effect_uncovered |
| 28 | The Eternity Elevator | Legendary Artifact-Spacecraft | 2 | `{T}` mana-ability | `AddManaToPool` | effect_uncovered (AA[1]'s tier_threshold=20 `AddChargeCounterManaOfChosenColor`), station_spacecraft |
| 29 | Thespian's Stage      | Land              | 1 | `{T}` | `BecomesCopyOfTargetLand` | effect_uncovered |
| 30 | Wandering Fumarole    | Land              | 1 | `<cost-mana>` | `BecomeLandCreatureUEOT` (with `granted_activated_abilities` rider — power/toughness switch) | effect_uncovered (the granted AA's `SwitchSourcePowerToughnessUEOT`) |

### 2.2 Aggregate sub-shape statistics

* **1-AA carriers: 20.** Multi-AA carriers: 10.
* **Card-type buckets:** Land 18, Artifact 11, Creature 1.
* **Co-gate distribution:** every card co-trips `effect_uncovered`
  (30 / 30); 8 / 30 also trip `nonsafe_triggered_ability`; 1 / 30
  also trips `station_spacecraft` (The Eternity Elevator).
* **AA[0] cost-shape buckets (across all 30 × n_aa = 41 abilities):**
  `tap_self=True` alone: 19. `<empty-cost>`: 12. `tap_self+sacrifice_self`: 8.
  `tap_self+pay_life=1`: 1 (Haunted Screen AA[1]). `tap_self+sacrifice_a_desert`: 1 (Scavenger Grounds).
* **AA[0] Effect-class bridge coverage** (via
  `measure_pool_parity.covered_python_class_set()`): only 3 of the
  22 distinct Effect classes on AA[0] are bridge-covered today —
  `PumpCreaturesYouControlUntilEOT` (1 card: Contested War Zone),
  `EquipToTargetCreatureYouControl` (4 cards: Atomic Microsizer,
  Auxiliary Boosters, Baseball Bat, Saw), `BecomeLandCreatureUEOT`
  (2 cards: Lavaclaw Reaches, Wandering Fumarole — but both carry
  HH-blocked `granted_activated_abilities` riders).
* **Riders on the AA struct itself:** `is_mana_ability=True` (10),
  `sorcery_speed=True` (8), `activate_only_once=True` (1 — Haunted
  Screen AA[2]), `tier_threshold>0` (1 — The Eternity Elevator
  AA[1]).

### 2.3 Phase-1 sub-shape selection — the narrowest 1-cycle-feasible slice

The narrowest tractable sub-shape A satisfies ALL of:

1. **1 activated ability** (multi-AA carriers are Phase 2+).
2. **`{T}`-only cost** (`tap_self=True`, `mana=None`,
   `sacrifice_self=False`, every other `ActivationCost` bool field
   `False`). `<empty-cost>` (free-activation) is Phase 2+ because
   it touches the Equipment + Sliver-Overlord cluster which co-
   tripping `nonsafe_triggered_ability` means closing the AA alone
   doesn't flip them. `{T}, Sac:` adds a second rider surface
   (Phase 2+).
3. **NO `is_mana_ability`, NO `sorcery_speed`, NO
   `activate_only_once`, NO `tier_threshold`, NO `room_half`, NO
   `cost_reductions`** on the `ActivatedAbility` struct. The
   mana-ability path interacts with Rust's stack-bypass logic;
   sorcery-speed adds a timing-restriction rider both engines
   must honor identically; the others are Phase-2+ riders.
4. **NO triggered_abilities, NO static_abilities, NO spell_effect,
   NO warp/kicker/impending, NO room_halves, NO loyalty, NO
   cost_reductions, NO station_threshold, NO dynamic_pt_formula,
   NO ward_cost** on the carrier (same exclusion set as
   `_printing_is_bridge_simple_creature`).
5. **Carrier card-type is Land** (no creature P/T to round-trip,
   no equipment-attached state, no Spacecraft station counters).
6. **The single Effect class is `RegenerateTargetCreature` OR
   `UntapTargetLand`** — the two Land carrier Effect classes
   among the 30 cards that satisfy (1)-(5) exactly. (`BecomeLandCreatureUEOT`
   is excluded because the only two Carrier-AA cards with that
   Effect — Lavaclaw Reaches, Wandering Fumarole — both carry
   `granted_activated_abilities` riders on the BecomeLand effect,
   which are HH-blocked per the saturation report's category A.)

This narrows the pilot pool to exactly **two cards** — **Swarmyard**
and **Deserted Temple** — both single-AA `{T}: <bridge-covered-
Effect-class>` Lands with no triggers, no statics, no co-gate
beyond the AA Effect itself (which Phase 1 ports in lockstep so
the `effect_uncovered` co-gate dissolves at the same admit-widen
landing).

**Phase-1 deck total: low** (the per-card walk shows 0 decks each
in the worktree-local pool; the aggregate 34,470-deck row is split
across the full 30-card population). The "high-leverage" claim for
this campaign is the **substrate landing** — Phase 1 ports the
non-token Carrier-AA bridge + 2 Effect-class ports, which unlocks
the remaining 28 BLOCKED-SG cards behind incremental Phase 2 / 3 /
N rider-extension cycles (e.g. Phase 2 = `{T}, Sac:` cost shape +
the Petrified Field / Mirrorpool / Ghost Vacuum trio; Phase 3 =
`<empty-cost>` sorcery-speed Equipment cluster + the 4 sibling
Equipments which also need the `nonsafe_triggered_ability` widen
to co-resolve; Phase N = mana-ability / tier-threshold / activate-
only-once / multi-AA / Creature-carrier riders).

## 3. Out-of-scope (deferred to Phase 2 / 3 / N)

The following are explicitly **NOT** in Phase 1's scope. The
Phase-1 filter guardrail
(`_printing_is_bridge_simple_carrier_aa_land`, §6) positively
rejects each so they cannot reach the Phase-1 admit path:

### 3.1 `{T}, Sac:` cost shape (Phase 2)

Adds `sacrifice_self=True` to the cost shape (the existing
Lander/Eldrazi-Scion precedent already supports `sacrifice_self`
on the *token* side, so the cost-shape codec is paid; widening the
non-token admit predicate is the Phase-2 cost). Carriers:
**Petrified Field** (`{T}, Sac: ReturnTargetLandFromGraveyardToHand`),
**Mirrorpool AA[0]/AA[1]** (`{T}, Sac: CopyTargetInstantOrSorceryYouControl`
/ `CreateTokenCopyOfTargetCreatureYouControl`), **Ghost Vacuum AA[1]**
(`{T}, Sac: PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl`),
**Keys to the House** (both AAs `{T}, Sac:`), **All-Fates Scroll
AA[1]** (`{T}, Sac:` for `DrawCardsByConditionMultiplier`).

### 3.2 `<empty-cost>` sorcery-speed Equipment cluster (Phase 3)

The 4 Equipment Carrier-AA cards (**Atomic Microsizer**,
**Auxiliary Boosters**, **Baseball Bat**, **Saw**) plus Robe of
Stars share `<empty-cost>` + `sorcery_speed=True` +
`EquipToTargetCreatureYouControl`. The Effect is bridge-covered,
but each carrier also trips `nonsafe_triggered_ability` (a custom
bespoke-trigger class — `AtomicMicrosizerAttackEffect`,
`CreateTokenAndAttachSelf`, `AttachToTargetCreatureYouControl`,
`SawAttacksOptionalSacDrawEffect`). Closure requires the Phase-3
admit widen + a `nonsafe_triggered_ability` per-shape closure for
each card (each is a separate per-card trigger slice). Sliver
Overlord similarly carries `<empty-cost>` + `SearchLibraryForCard` /
`GainControlOfTargetSliverPermanently`, but on a Creature carrier
— another rider surface (Phase N).

### 3.3 Mana-ability AAs (Phase N)

`is_mana_ability=True` short-circuits the stack at activation —
Rust already auto-wires basic-land mana abilities, and the
Lander/Eldrazi-Scion precedent ports `is_mana_ability=True` via
the dict bridge. Widening the *non-token* admit predicate to
admit `is_mana_ability=True` AAs is its own rider surface (the
admit predicate must verify both engines route the activation
identically; an off-stack activation in one engine and on-stack
in the other is a §2 silent divergence). Carriers:
**Ancient Tomb**, **All-Fates Scroll AA[0]**, **Grove of the
Burnwillows**, **Haunted Screen** (3 AAs all mana-ability),
**Lotus Field**, **Meteor Crater**, **Reflecting Pool**,
**The Eternity Elevator** (both AAs mana-ability, tier_threshold).

### 3.4 Tier-threshold / activate-only-once / room-half riders (Phase N)

**The Eternity Elevator AA[1]** carries `tier_threshold=20`; the
Spacecraft station-counter substrate is itself §2-DEFERRED, so
this Carrier is co-gated `station_spacecraft` and would need both
substrates to land. **Haunted Screen AA[2]** carries
`activate_only_once=True` — the latched-flag semantics need a
per-`GameObject` flag mirror on the Rust side. No Phase-1 carrier
carries `room_half`, but the rider exists on the
`ActivatedAbility` dataclass (`effects/base.py:485`) and is
explicitly Phase-N.

### 3.5 Multi-AA carriers (Phase 2+)

10 of the 30 cards carry 2 or 3 AAs. The bridge codec round-trips
a *list* of AAs, so multi-AA is a Phase-2+ widen of the admit
predicate (each AA must independently pass the per-AA sub-shape
gate). Phase 1 admits only single-AA carriers to keep the §2
silent-mistranslation surface minimal.

### 3.6 Creature carriers (Phase N)

**Sliver Overlord** is the only Creature carrier in the 30. The
Creature body carries P/T + subtype gating that interacts with
the layered-abilities substrate and the Phase-1 sub-shape's
"no creature body" simplification. Phase N admits Creature
carriers under a separate admit predicate sibling
(`_printing_is_bridge_simple_carrier_aa_creature`, modeled after
`_token_creature_with_safe_mana_activated_ability_card_def`).

### 3.7 BecomeLandCreatureUEOT with rider (Phase N — covered by separate substrate)

**Lavaclaw Reaches** and **Wandering Fumarole** are creature-land
manland carriers whose AA `BecomeLandCreatureUEOT` effect carries
a `granted_activated_abilities` rider (Lavaclaw's `{X}: pump`,
Wandering's switch P/T). This is the BLOCKED rider category A
per the saturation doc (`BecomeLandCreatureUEOT` listed as a
blocked Effect class in the HH-module skip list at
`tests/test_probe_activated_abilities_hh.py:67-71`). Closure
requires the BecomeLandCreatureUEOT rider substrate
(`granted_keywords` / `granted_subtype` /
`granted_activated_abilities` / `granted_triggered_abilities` /
`unblockable` round-trip) — a separate substrate, deferred.

## 4. Rust-side spec — the new field, parse arm, and resolve arm

### 4.1 Reuse of the existing token-AA parse machinery

**The Rust side already parses activated abilities for token
printings** — the round-52 N1 substrate landed
`parse_activated_ability` + `parse_activation_cost` (consumed via
`register_printing`'s `activated_abilities` registry key). For
Phase 1, the **non-token** carrier reuses the SAME parse machinery
unchanged; the new wiring is:

1. **Confirm `register_printing` already accepts an
   `activated_abilities` key on a NON-token CardPrinting registry
   dict**, OR add the key threading if absent. (Verify-first
   discipline: Phase-1 implementor walks
   `rust/src/cards.rs::register_printing` to confirm the key is
   accepted on a non-Token printing; if it is, NO Rust-side
   parser change is needed for the cost-shape `{T}` subset.)
2. **Confirm `cast_spell` / activation pipeline on non-token
   permanents resolves AAs identically to the token-AA path** (the
   `effective_activated_abilities` filter at Python's
   `effects/base.py` reads the same `room_half` / `tier_threshold`
   / `activate_only_once` gates regardless of source kind).

### 4.2 New Effect variants — `RegenerateTargetCreature` + `UntapTargetLand`

These two Effect classes are the Phase-1 pilot's Rust-side cost.
Each lands as a new variant on Rust's `Effect` enum (per
`rust/src/cards.rs` Effect grammar) plus a parse arm in
`parse_effect` plus a resolve arm in `state_ops_resolve.rs` (the
existing per-Effect dispatch) plus a `to_pydict` arm for the
bridge round-trip.

#### 4.2.1 `RegenerateTargetCreature`

**Semantics (CR 701.15 — regenerate is a replacement effect "the
next time SOURCE would be destroyed this turn, instead remove all
damage marked on it, tap it, and remove it from combat").**
Implementing regenerate fully would require the
replacement-effects engine + the `combat_state` tap-and-remove
primitive on Rust. **For Phase 1 the resolve arm is the minimal
honest mirror**: pin a per-`GameObject` `pending_regeneration: u8`
counter on the target creature, decremented at the same SBA pass
Python decrements its mirror. The replacement check at "would be
destroyed" walks the counter. If the implementor finds this
out-of-Phase-1 scope, **the alternative is to swap the pilot
Effect to a fully-resolved-immediately sibling** (e.g.
`UntapTargetLand` alone + a different second Effect with no
replacement semantics — TBD by the implementing agent).

**Python reference:** `src/mtg_bot/effects/generic/regenerate.py`
(walked at file open for the implementor's per-Effect Rust port).

#### 4.2.2 `UntapTargetLand`

**Semantics:** target a `Land` permanent under any controller;
toggle its `tapped: false`. Resolves immediately at top-of-stack
under the existing Effect-resolve dispatch. **Phase 1 admits ONLY
the `Land` target subtype** — broader untap predicates
(`UntapTargetPermanent`, `UntapTargetCreature`) are Phase-N
generalizations.

**Python reference:** `src/mtg_bot/effects/generic/tap_untap.py`.

### 4.3 No new state field

Unlike cost-reduction Phase 1 (which added
`Player.spells_cast_this_turn`), Carrier-AA Phase 1 needs NO new
per-player / per-game state. The two pilot Effects resolve
immediately; activation routes through the existing AA-activation
primitive on both engines.

### 4.4 Bridge `to_pydict` arm

Each new Effect variant's `to_pydict` arm emits the dict shape
Python's `_ta_dict_to_python_effect` already supports (mirroring
the existing AA Effect dispatch table — same convention as the
token-AA Lander shape):

```rust
// RegenerateTargetCreature
PyDict::new(py).set_item("kind", "regenerate_target_creature")?;

// UntapTargetLand
PyDict::new(py).set_item("kind", "untap_target_land")?;
```

The Python-side `_ta_dict_to_python_effect` arm grows two new
`kind` discriminators returning the Python `RegenerateTargetCreature()`
/ `UntapTargetLand()` instances respectively. NO target-selection
state crosses the bridge for either (both are agent-driven; the
target selection is per-engine).

## 5. Python bridge spec — round-trip the AA-list field byte-equal

### 5.1 CardDef field — `activated_abilities` for the non-token case

**File:** `src/mtg_bot/parity/cross_engine.py`, the `CardDef`
dataclass (declared at `cross_engine.py:107`). Append after the
`token_activated_abilities` field (line 214):

```python
    # Carrier-AA substrate (Phase 1). Non-token CardPrinting carriers
    # with one bridge-correct activated ability (EoE — pilot pair
    # Swarmyard ``{T}: Regenerate target creature`` and Deserted
    # Temple ``{T}: Untap target land``). Each entry is the SAME
    # parse_activated_ability-shaped dict
    # ``token_activated_abilities`` carries (line 214), bridged by the
    # SAME ``_aa_dict_to_python_activated_ability`` codec
    # (``cross_engine.py:13852``). The split into TWO fields
    # (``token_activated_abilities`` for token printings vs.
    # ``activated_abilities`` here for non-token carriers) keeps the
    # token-AA admit gate's §2 contract intact — the token path's
    # Lander / Eldrazi Scion helpers (``trajectory.py:3208,3339``)
    # decline silently on the non-token shape, and vice versa. Empty
    # tuple = no carrier AA (back-compat default — every pre-Phase-1
    # CardDef omits it). The Phase-1 filter guardrail
    # ``_printing_is_bridge_simple_carrier_aa_land`` (§6) positively
    # rejects every shape outside the §2.3 sub-shape so only the
    # narrow Phase-1 admit reaches this field.
    activated_abilities: tuple[dict, ...] = ()
```

### 5.2 `build_rust_state` registry-dict emit

**File:** `src/mtg_bot/parity/cross_engine.py`,
`build_rust_state.printing_dict`. Two places:

1. The `token_activated_abilities` block already exists. Phase 1
   adds a parallel block that emits `activated_abilities` for the
   NON-token CardDef (`card.activated_abilities`, NOT
   `card.token_activated_abilities`):

```python
if card.activated_abilities and not card.is_token_printing:
    printing_dict["activated_abilities"] = [
        dict(aa_dict) for aa_dict in card.activated_abilities
    ]
```

2. **Critical §2 invariant:** the token-AA block must
   continue to emit ONLY for token printings, AND the non-token-AA
   block must continue to emit ONLY for non-token printings. The
   guard is the existing `card.is_token_printing` field (or
   equivalent — verified by the implementor against the live
   CardDef shape). A printing emitting BOTH would silently double-
   register on the Rust side.

### 5.3 `_card_def_to_python_printing` reverse arm

Reconstructs the `CardPrinting.activated_abilities` tuple from the
CardDef's `activated_abilities` list (each dict round-trips via
the existing `_aa_dict_to_python_activated_ability` codec):

```python
from mtg_bot.cards.base import CardPrinting
# ... existing reconstruction code ...
activated_abilities: tuple[ActivatedAbility, ...] = ()
if card.activated_abilities:
    activated_abilities = tuple(
        _aa_dict_to_python_activated_ability(aa_dict)
        for aa_dict in card.activated_abilities
    )
# pass activated_abilities=activated_abilities into CardPrinting(...)
```

### 5.4 `_printing_to_card_def` arm — admit-gated

**File:** `src/mtg_bot/parity/trajectory.py`. The new disjunct
`_printing_is_bridge_simple_carrier_aa_land` (§6) is wired into
`_filter_deck_to_bridge_supported` BEFORE `_printing_is_bridge_basic_land`
so a carrier-AA Land routes to the Carrier-AA-aware CardDef. The
`_printing_to_card_def` arm produces:

```python
def _carrier_aa_land_card_def(printing) -> Optional["CardDef"]:
    """Build a CardDef from a Phase-1-admitted non-token Carrier-AA
    Land. The admit predicate :func:`_printing_is_bridge_simple_carrier_aa_land`
    is the §2 guardrail; this function trusts the guardrail and
    serializes the single AA into the bridge dict shape."""
    if not _printing_is_bridge_simple_carrier_aa_land(printing):
        return None
    aa = printing.activated_abilities[0]
    aa_dict = _python_aa_to_safe_dict(aa)  # NEW — sibling of _python_ta_to_safe_dict
    if aa_dict is None:
        return None  # §2 honest decline
    from mtg_bot.parity.cross_engine import CardDef
    return CardDef(
        name=printing.name,
        card_type="Land",
        supertypes=tuple(printing.supertypes or ()),
        subtypes=tuple(printing.subtypes or ()),
        keywords=tuple(),  # Phase 1 admits NO keywords
        activated_abilities=(aa_dict,),
    )
```

The new helper `_python_aa_to_safe_dict` is the Python-side
inverse of `_aa_dict_to_python_activated_ability` (mirrors the
existing `_python_ta_to_safe_dict` pattern for triggers); it
walks an `ActivatedAbility` and returns the Rust-parse-shaped dict
OR `None` if any rider falls outside the Phase-1 admit set.

## 6. Filter guardrail — admit only the Phase-1 sub-shape A

**File:** `src/mtg_bot/parity/trajectory.py`. The §2 Class-1
positive-allowlist predicate, mirroring the round-60
`_printing_is_bridge_nonbasic_mana_land` /
`_printing_is_bridge_pure_warp_creature` /
`_printing_is_bridge_pure_cost_reduction_creature` precedents:

```python
# Phase-1 admitted AA[0] Effect classes. Pilot pair (Swarmyard,
# Deserted Temple) ships the two Land carrier Effects: regenerate
# and untap-target-land. Phase-2/3/N extends this set as each
# Effect class lands cross-engine.
_CARRIER_AA_PHASE_1_EFFECT_CLASSES: frozenset[type] = frozenset({
    # filled in by the implementor at landing time — placeholder
    # names match the live Python class objects:
    # RegenerateTargetCreature, UntapTargetLand
})


def _aa_is_phase1_sub_shape_a(aa) -> bool:
    """True iff `aa` is one of the two boolean conditions Phase 1
    ports. Any Phase-2+ rider — False (rejected)."""
    from mtg_bot.effects.base import ActivatedAbility
    if not isinstance(aa, ActivatedAbility):
        return False
    # §2 STRICT cost gate: exactly tap_self, nothing else. Mirrors
    # the Eldrazi Scion / Lander helpers' per-bool exclusion list.
    cost = aa.cost
    if cost.mana is not None:
        return False
    if not cost.tap_self:
        return False
    for _extra in (
        "sacrifice_self", "untap_self", "exile_self",
        "tap_permanent_you_control",
        "exile_artifact_from_graveyard",
        "sacrifice_another_creature_or_artifact",
        "sacrifice_another_artifact_or_land",
        "sacrifice_another_artifact",
        "sacrifice_food",
        "sacrifice_a_land",
        "sacrifice_a_desert",
        "remove_plus_one_counter_from_your_creature",
        "exile_granting_equipment",
        "mana_reduced_by_source_power",
    ):
        if getattr(cost, _extra, False):
            return False
    if cost.pay_life or cost.discard_count or cost.exile_cards_from_graveyard_count:
        return False
    if cost.requires_own_creature_power_at_least or cost.requires_own_artifact_count_at_least:
        return False
    if cost.requires_control_of_subtype:
        return False
    # §2 STRICT AA-rider gate: no Phase-2+ AA-level riders.
    if aa.is_mana_ability:
        return False
    if aa.sorcery_speed:
        return False
    if aa.cost_reductions:
        return False
    if aa.room_half is not None:
        return False
    if aa.tier_threshold:
        return False
    if aa.activate_only_once:
        return False
    # §2 STRICT Effect-class gate: Phase-1 admitted set only.
    if type(aa.effect) not in _CARRIER_AA_PHASE_1_EFFECT_CLASSES:
        return False
    return True


def _printing_is_bridge_simple_carrier_aa_land(printing) -> bool:
    """True iff a CardPrinting is a PURE single-`{T}`-cost,
    single-bridged-Effect, no-rider non-token Land carrier whose
    AA the Phase-1 Carrier-AA substrate round-trips byte-equal.

    Motivating set: Swarmyard, Deserted Temple. The §2 Class-1
    guardrail: admits ONLY the bare `{T}: <Phase-1-Effect>` Land
    profile and MUST reject every multi-AA, every `{T}, Sac:`
    carrier, every `<empty-cost>` carrier, every mana-ability,
    every sorcery-speed, every triggered-ability-co-gated carrier,
    every Creature carrier, every Equipment carrier, every
    `BecomeLandCreatureUEOT`-with-rider carrier — sub-shapes
    deferred to Phase 2 / 3 / N.
    """
    if "Land" not in printing.card_types:
        return False
    # Phase 1 admits only single-typed Land (no Land — Desert,
    # no Legendary Land — Scavenger Grounds is Land — Desert
    # which is §3.7 honest-decline at the type rider).
    extra_card_types = tuple(t for t in printing.card_types if t != "Land")
    if extra_card_types:
        return False
    if printing.power is not None or printing.toughness is not None:
        return False
    # §2 carrier exclusion set — every Phase-2+ rider, every other
    # subsystem.
    if printing.keywords:
        return False
    if printing.triggered_abilities:
        return False
    if printing.static_abilities:
        return False
    if printing.spell_effect is not None:
        return False
    if printing.warp_cost or printing.kicker_cost or printing.impending_cost:
        return False
    if printing.room_halves:
        return False
    if printing.loyalty is not None:
        return False
    if printing.cost_reductions or printing.external_cost_reductions:
        return False
    if printing.station_threshold:
        return False
    if getattr(printing, "dynamic_pt_formula", None) is not None:
        return False
    if getattr(printing, "ward_cost", None) is not None:
        return False
    # §2 STRICT AA gate: EXACTLY one AA, sub-shape A.
    aas = tuple(printing.activated_abilities or ())
    if len(aas) != 1:
        return False
    if not _aa_is_phase1_sub_shape_a(aas[0]):
        return False
    return True
```

**Wire into `_filter_deck_to_bridge_supported`** (the OR-chain).
The disjunct sits AFTER `_printing_is_bridge_basic_land` and AFTER
the existing non-basic-land disjunct, so a printing falls through
to `_printing_is_bridge_simple_carrier_aa_land` only if the
preceding land disjuncts decline.

## 7. Test plan

### 7.1 Substrate unit pins (Rust `#[test]` + Python `pytest`)

1. `parse_printing` with non-token CardDef carrying
   `activated_abilities=[{"cost":{"tap_self":True},"effect":{"kind":"regenerate_target_creature"}}]`
   → `printing.activated_abilities == [ActivatedAbility(...)]`
   with the regenerate effect, tap_self cost, no riders. Absent
   key → empty Vec / tuple.
2. `parse_activated_ability` round-trip pin: the cost dict
   `{"tap_self": True}` (NO mana, NO sacrifice_self) round-trips
   byte-equal through `_aa_dict_to_python_activation_cost`.
   `pay_life`, `discard_count`, and every Phase-2+ cost field —
   Rust hard-errors via the existing `unknown` check at
   `cross_engine.py:13794-13805`.
3. `_aa_is_phase1_sub_shape_a(aa)` accepts the pilot pair's exact
   shapes and REJECTS every Phase-2+ deviation (table-driven test
   over the 30 Carrier-AA cards: only Swarmyard + Deserted Temple
   pass; every other card rejects).
4. **`_python_aa_to_safe_dict`** unit pin: an `ActivatedAbility`
   constructed from the pilot pair round-trips through
   `_python_aa_to_safe_dict` → `_aa_dict_to_python_activated_ability`
   byte-equal.

### 7.2 Cross-engine bridge round-trip pins

5. Synthetic CardDef carrying the regenerate AA: build_rust_state
   → registry dict carries `activated_abilities` key; bench's
   AA-activation path emits the same `ActivateAbility` action on
   both engines; resolve → byte-equal post-state (regenerate
   counter set / cleared identically on both engines).
6. Synthetic CardDef carrying the untap AA: build_rust_state
   → registry dict carries `activated_abilities` key; both
   engines emit the same target enumeration on a board with N
   tapped lands; resolve → byte-equal post-state.
7. Action-set invariance pin: both engines emit the SAME set
   (and positional order) of `ActivateAbility` decisions for a
   Phase-1 carrier on its controller's priority pass at the
   bench-driven fixture.

### 7.3 Real-EoE per-card probes

A `tests/test_swarmyard_parity.py` + `tests/test_deserted_temple_parity.py`
pair (each inserted IMMEDIATELY ABOVE the
`# === PHASE5_PROBES_INSERT_ABOVE_THIS_LINE ===` sentinel in
`tests/test_parity_smoke.py` via `MODULE_FILE` symlink, per the
batch-13 EEEE-idiom convention) that drives the **actual
Swarmyard / Deserted Temple printing** (resolved via the live
`OracleParserCardSource`, NOT a synthetic CardDef — round-46
real-EoE-signal discipline) on **both** engines through:

* **Swarmyard probe:** assert byte-equal mirror through (a)
  baseline (carrier in play, no creature being regenerated —
  state unchanged), (b) regenerate-the-attacking-creature line
  (controller activates `{T}: Regenerate target creature`
  targeting an attacker that takes lethal — the `pending_regeneration`
  counter must be bit-identical on both engines, and the
  subsequent SBA pass must skip the destroy on both engines).
* **Deserted Temple probe:** assert byte-equal mirror through (a)
  baseline (carrier in play, no target untapped — state
  unchanged), (b) untap-a-tapped-Forest line (controller
  activates `{T}: Untap target land` targeting a tapped Forest —
  the Forest's `tapped` bit flips on both engines, the carrier's
  `tapped` bit flips ON, and the mana pool / floating mana state
  is byte-equal post-resolve).

**Bench-strategy AA-activation coverage note:** the bench's
`attack_all` strategy does not naturally activate AAs. The
probes MUST use a scripted picker (a `tests/parity/_picker_shims.py`
helper) that forces the `{T}: <Phase-1-Effect>` activation
sequence so the substrate is actually exercised, not just admitted
without any decision driving it. The implementing agent confirms
the picker shim is in place; the SL entry (§9) is amended to note
the bench-strategy coverage is probe-driven, not organic.

### 7.4 Decline-set bench check

A negative-set bench check at the loader filter, parametrized
over the 30 BLOCKED-SG Carrier-AA cards:

8. `_printing_is_bridge_simple_carrier_aa_land(<live Swarmyard>)`
   and `(<live Deserted Temple>)` are `True` (the Phase-1 admit
   positive set is exactly these 2).
9. `_printing_is_bridge_simple_carrier_aa_land(<every other
   BLOCKED-SG Carrier-AA card from §2.1>)` is `False` (28 cards;
   exhaustive decline-set parametrize). Each false-case is
   asserted with the SPECIFIC reason: multi-AA / non-Land /
   `{T}, Sac:` / `<empty-cost>` / mana-ability / sorcery-speed
   / triggered / Equipment-subtype / Spacecraft / Effect-class
   not in Phase-1 set. (The reason-strings are documentation
   for the Phase-2/3/N follow-ups.)
10. **Subsystem-attribution pin:** exactly 2 EoE printings pass
    `_printing_is_bridge_simple_carrier_aa_land` (Swarmyard,
    Deserted Temple) — the guardrail's positive set is exhaustive
    for Phase 1.
11. **Decline-set parity check (the 4,286-deck Archenemy's-Charm-
    style proxy + the 30-card BLOCKED-SG Carrier-AA proxy):**
    with the decline-set deck pool loaded, confirm the bench's
    loader-side filter excludes the same set of cards it excludes
    today — i.e. Phase 1 admits +2 cards and 0 additional
    decline-set spillover.

## 8. Estimated cycle count

Per the per-card multi-cycle precedent established by today's
CH / MTL / AV closures (1 substrate + 1 admit + 1 probe per card =
~3 cycles per card on top of the shared substrate landing):

| Cycle | Owner | Deliverable |
|---:|---|---|
| 1 | Rust agent | Substrate landing: CardDef `activated_abilities` field + non-token build_rust_state emit block + the two new Rust Effect variants (`RegenerateTargetCreature` + `UntapTargetLand`) with parse / resolve / to_pydict arms + the `_python_aa_to_safe_dict` helper. **Sole Rust slice this round** (`.pyd` race rule). |
| 2 | Python/bridge agent | `_card_def_to_python_printing` non-token-AA arm + `_ta_dict_to_python_effect` two new kind discriminators + `_printing_is_bridge_simple_carrier_aa_land` admit predicate + `_carrier_aa_land_card_def` builder + the 7 unit + bridge pins (§7.1 + §7.2). |
| 3 | Bench agent | Swarmyard real-EoE probe (§7.3) + decline-set bench check pins 8-10 (§7.4) + picker shim for forced activation. |
| 4 | Bench agent | Deserted Temple real-EoE probe (§7.3) + 4,286-deck decline-set parity check pin 11 (§7.4) + per-cycle pool parity regen + SEARCH_LIMITATIONS.md entries (§9). |

**Estimated total: ~4 cycles for Phase 1**, lighter than the
cost-reduction Phase 1's ~5 cycles because Carrier-AA Phase 1
adds NO new per-player state field (cost-reduction added
`spells_cast_this_turn`); the cost driver is the 2 Effect-class
ports (Regenerate's pending-regen counter is non-trivial — if the
implementor finds that out-of-Phase-1 scope, swap to a fully-
resolved-immediately sibling Effect or split Cycle 1 into 1a /
1b).

**Subsequent phases (out of Phase 1 scope, scoped here for
campaign context):**

* **Phase 2 (`{T}, Sac:` cost shape, ~5 cards):** ~3-4 cycles
  to widen the admit predicate to `sacrifice_self=True` carriers
  + port the Effects Petrified Field / Mirrorpool / Ghost
  Vacuum / Keys to the House / All-Fates Scroll need. Lands the
  Phase-2 cost-shape widen on the same admit predicate.
* **Phase 3 (`<empty-cost>` sorcery-speed Equipment cluster,
  ~5 cards):** ~5-6 cycles. The Equipment carriers each also
  trip `nonsafe_triggered_ability`, so Phase 3 is paired with a
  per-card trigger slice for each (4 Equipment slices + Robe of
  Stars's PhaseOutEquippedCreature port). Lands the
  `_printing_is_bridge_simple_carrier_aa_equipment` sibling
  admit predicate.
* **Phase N (mana-ability / tier-threshold / activate-only-once /
  multi-AA / Creature-carrier / BecomeLandCreatureUEOT-rider,
  ~18 cards):** ~4-6 cycles per rider class. The mana-ability
  widen (~8 cards) is the largest single Phase-N slice; the
  multi-AA widen unblocks Ghost Vacuum / All-Fates Scroll /
  Keys to the House / Mirrorpool / Haunted Screen / Sliver
  Overlord / etc. once each carrier's AAs each pass the per-AA
  sub-shape gate.

**Campaign total: ~12-18 cycles across Phase 1 / 2 / 3 / N** to
close all 30 cards / 34,470 decks, comparable to (slightly larger
than) the cost-reduction campaign's ~10 cycles. The size delta is
exactly the per-Effect port surface and the broader rider
matrix.

## 9. SEARCH_LIMITATIONS.md entries (land WITH Phase 1 cycle 1)

Three entries (estimated; Carrier-AA's rider surface is broader
than cost-reduction):

1. **Carrier-AA Phase 1 admits only the bare `{T}:` single-AA
   single-bridged-Effect non-token Land sub-shape; `{T}, Sac:`,
   `<empty-cost>`, mana-ability, sorcery-speed,
   activate-only-once, tier-threshold, room-half, multi-AA, and
   Creature-carrier shapes are deferred.** Location:
   `trajectory.py::_printing_is_bridge_simple_carrier_aa_land` +
   `trajectory.py::_aa_is_phase1_sub_shape_a`. Why OK: the
   filter guardrail positively rejects every non-Phase-1 shape;
   failure mode = a future admit-widen without a guardrail
   update would land a §2 silent divergence at the first
   AA-activation decision emit. Fix-scope = Phase 2 + Phase 3 +
   Phase N (per §3); impact = +2 cards / low decks(1g) realized
   leverage, 0 strength cost.
2. **Phase 1 ports two new Rust Effect variants
   (`RegenerateTargetCreature`, `UntapTargetLand`) at the minimum
   resolution semantics; replacement-effects engine integration
   for full CR 701.15 regenerate is deferred.** Location:
   `rust/src/state_ops_resolve.rs::regenerate_target_creature` +
   `state_ops_resolve.rs::untap_target_land`. Shortcut: regenerate
   resolves to a `pending_regeneration: u8` counter on the
   target's `GameObject`; the SBA-time replacement check walks
   the counter and decrements identically on both engines. Why
   OK: Python's regenerate.py uses the same per-object counter,
   so the bit-equal contract holds for the Swarmyard probe's
   straight-attack-with-regenerate line. Failure mode: a future
   card that triggers regenerate via a complex replacement-chain
   interaction (e.g. "would be destroyed by lethal damage twice
   in one turn") could diverge if the counter saturates
   differently. Fix-scope: replacement-effects engine port
   (separate, large substrate). Impact: 0 today (no Phase-1
   card triggers the chain).
3. **Carrier-AA bench-strategy coverage is probe-driven, not
   organic.** Location:
   `tests/test_swarmyard_parity.py` + `test_deserted_temple_parity.py`.
   Shortcut: the bench's `attack_all` strategy never activates
   carrier AAs; the per-card probes drive a scripted picker shim
   forcing the activation sequence. Why OK: same EEEE-idiom
   coverage discipline the batch-1-13 lane established; the
   probe is a real-EoE byte-equal pin even though the bench
   never reaches the AA-activation path organically. Failure
   mode: a future strategy that activates the AA could surface a
   bench-time divergence the probe-only coverage misses.
   Fix-scope: bench strategy widening (deferred per
   `docs/BENCH_STRATEGY_FRONTIER.md` if it exists; otherwise a
   separate slice). Impact: 0 today.

## 10. Rejected alternatives

### 10.1 Widen the existing `token_activated_abilities` field to also carry non-token AAs

**Rejected — silent §2 contract drift.** Folding non-token
Carrier-AAs into `token_activated_abilities` would make the
`_token_with_safe_activated_ability_card_def` /
`_token_creature_with_safe_mana_activated_ability_card_def` admit
helpers' §2 strict contracts (token-only, declines non-token
shape) ambiguous — any future change to either helper risks
silently widening or narrowing the other. The two-field split
mirrors the Lander vs. vanilla token split (round-49 N1
precedent) — each helper §2-strictly admits ONE carrier kind
and declines every other, so a bug in either path can't silently
mistranslate the other.

### 10.2 Land the Carrier-AA admit predicate as a generic widen of `_printing_is_bridge_simple_creature` / `_printing_is_bridge_basic_land`

**Rejected — the anti-pattern (round-38-E5 / count-chasing).**
Removing the `if printing.activated_abilities: return False`
guards at the 15 sibling sites would admit all 30 Carrier-AA
cards into the bench WITHOUT the substrate, immediately shipping
a guaranteed divergence: Python's loader hands a populated
`printing.activated_abilities` tuple to the bench; Rust's
mirror has an empty Vec — first-AA-activation decision emit
diverges on every Carrier-AA card. Same shape as the
cost-reduction Phase-1 rejected alternative §10.4. **The
substrate has to land before any admission is bridge-correct.**

### 10.3 Pilot a smaller Effect-class set (e.g. only `UntapTargetLand`)

**Rejected — pilot pair is the minimum demonstrably-shippable
unit.** Phase 1 needs at least two cards in the admit set to
prove the substrate generalizes (a single-card admit could be a
bespoke one-off; two cards demonstrate the per-AA sub-shape gate
is reusable). If the implementor finds `RegenerateTargetCreature`
too expensive in Cycle 1, the alternative is to swap the second
pilot to a different bare-`{T}:` Land Effect — e.g.
`PutBasicLandFromHandOntoBattlefieldTapped` (Terrain Generator)
or `BecomesCopyOfTargetLand` (Thespian's Stage) — each also
needs an Effect-class port but each has its own implementation
cost. The pair must come from §2.1's narrow shape; the implementor
documents the swap if regenerate is deferred to Phase 2.

### 10.4 Pilot a Creature carrier (e.g. Sliver Overlord)

**Rejected — broader rider surface.** A Creature carrier adds
P/T + layered-abilities interactions. Phase 1 pilot is Land-only
(no P/T, no layered abilities, no subtypes beyond the bare
`Land` type) to minimize the §2 silent-mistranslation surface;
Creature-carrier admit predicate is Phase N (see §3.6).

### 10.5 Skip Carrier-AA, pursue Effect-uncovered instead

**Rejected — Effect-uncovered is diffuse.** The Effect-uncovered
row (45 cards / 76,035 decks) is the largest in the BLOCKED-SG
tail by aggregate deck count, but per the saturation doc's
recommendation table it is explicitly DIFFUSE — no single closure
unblocks multiple cards. Carrier-AA's structural unity (single
admit-predicate widen could close 30 cards under the §2 sub-
shape gate as Phase 1 / 2 / 3 / N progress) makes it the higher-
leverage substrate-shape next pivot. The Effect-uncovered tail
continues to be addressed per-card via the existing per-Effect
probe lane.

## 11. Acceptance / sign-off

Phase 1 is complete and ready to merge to `main` when:

1. All 11 pins (§7.1-§7.4) pass on the parity gate.
2. The Swarmyard + Deserted Temple real-EoE probes (§7.3) pass
   byte-equal through both the baseline and AA-activated paths on
   both engines.
3. The decline-set bench check confirms +2 cards admitted, 0
   spillover across the 30-card Carrier-AA row.
4. All three SEARCH_LIMITATIONS.md entries (§9) land alongside
   the substrate code.
5. `.pyd` rebuilt clean; the parity gate
   (`tests/test_parity_smoke.py + test_cross_engine_etb_triggers.py
   + test_trajectory_parity.py + test_trajectory.py +
   test_measure_pool_parity.py`) stays green.
6. Pool-parity regen lands +2 cards in the PROBED tier (and -2
   from BLOCKED-SG Carrier-AA per the per-slug attribution
   precedent — Swarmyard + Deserted Temple flip 478/56 → 380/54
   on the headline, leaving 28 Carrier-AA cards as the Phase-2
   pivot).

## 12. Cross-references

* `docs/COVERED_BY_CONSTRUCTION_PROBE_WRITING_SATURATION_2026-05-25.md`
  — the saturation report that identifies Carrier-AA widening
  as the highest-leverage pivot.
* `docs/COST_REDUCTION_SUBSTRATE_PHASE_1_DESIGN.md` — the
  format precedent + Phase-1/2/3 sequencing template this
  campaign mirrors.
* `docs/POOL_PARITY.md` §"BLOCKED — subsystem-gated /
  Effect-uncovered (56)" line 452 — the Carrier-AA row (30 /
  0 / 30 / 34,470 / 0 / sprawling).
* `docs/SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY.md` §2 line 1043 +
  §5 line 1974 — the Carrier activated abilities row
  characterization (30 / 0 single-gated / "all multi-gated —
  closing this gate alone flips zero cards" — the structural
  unity of the row).
* `docs/TOKEN_PRINTING_SUBSTRATE.md` §6/§7 — the round-49 / 52
  / Eldrazi-Scion cycle-3 token-AA precedent. The §2 strict-
  silent-mistranslation discipline reused by Carrier-AA.
* `src/mtg_bot/parity/cross_engine.py:107` — CardDef declaration.
* `src/mtg_bot/parity/cross_engine.py:181-214` — the
  `token_activated_abilities` field + its substrate (the
  token-side sibling Phase 1 widens for the non-token case).
* `src/mtg_bot/parity/cross_engine.py:13768-13929` — the
  shape-agnostic `_aa_dict_to_python_activation_cost` +
  `_aa_dict_to_python_activated_ability` codec Phase 1 consumes
  unchanged.
* `src/mtg_bot/parity/trajectory.py:3208-3337` —
  `_token_with_safe_activated_ability_card_def` (Lander).
* `src/mtg_bot/parity/trajectory.py:3339-3491` —
  `_token_creature_with_safe_mana_activated_ability_card_def`
  (Eldrazi Scion, landed today 2026-05-25 in the warping-wail
  Cycle-3 substrate).
* `src/mtg_bot/parity/trajectory.py:4604-4711` —
  `_printing_is_bridge_simple_creature` (the simple-creature
  admit predicate with the `if printing.activated_abilities:
  return False` guard at :4684 — one of 15 sibling sites).
* `src/mtg_bot/effects/base.py:447-505` — Python's
  `ActivatedAbility` dataclass (the rider matrix Phase 1's
  guardrail enforces).
* `src/mtg_bot/effects/base.py:368-442` — Python's
  `ActivationCost` dataclass (the cost-component bool fields
  Phase 1's guardrail rejects beyond `tap_self`).

## 13. Regenerating the per-card enumeration

The §2.1 30-card walk is reproducible via a throwaway scout
(not checked in — written and removed during the design lane).
The walker reads `subsystem_attribution()` from
`scripts/scout_r58_subsystem_attribution.py`, filters to the
Carrier-AA gate, then walks each printing's
`activated_abilities[*]` for `(cost-bool-fields, effect-class,
AA-riders)`. To regenerate at a future HEAD, write a one-off
script that:

```python
import scripts.scout_r58_subsystem_attribution as scout
attr = scout.subsystem_attribution()
carrier_members = attr["by_subsystem"][scout.SUB_ACTIVATED]
from mtg_bot.cards.parser.source import OracleParserCardSource
ps = OracleParserCardSource().get_printings()
for name in sorted(carrier_members):
    p = ps[name]
    aa = p.activated_abilities[0]
    # ... emit (name, card_types, n_aa, AA[0].cost bools,
    # AA[0].effect class, AA-level riders) ...
```

The aggregate stats (1-AA: 20, multi-AA: 10; card-type buckets;
co-gate distribution; AA-cost-shape buckets; Effect-class
bridge-coverage check) are the verify-first inputs for the §2.3
sub-shape selection. The 30-card breakdown table in §2.1 is the
ground truth at main `8525d18e`; subsequent HEADs may shift the
breakdown as adjacent Effect-class ports land (e.g. a future
`UntapTargetLand` port outside this campaign would change the
"bridge-covered AA[0] Effect" count from 3 to 4, but would NOT
expand the Phase-1 admit set — that's locked to the §2.3
narrow sub-shape).
