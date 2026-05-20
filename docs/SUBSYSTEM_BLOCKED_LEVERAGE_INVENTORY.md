# Subsystem-blocked tier — leverage inventory + closure sequence

A focused, current-snapshot **synthesis** of the BLOCKED-subsystem-gated
tier (147 cards, the dominant residual bucket on `docs/POOL_PARITY.md`
post-FFFF probe agent merge `25c0d410`). This doc is **not the
authoritative living roadmap** — `docs/SUBSYSTEM_ROADMAP.md` is that,
with its full cycle-by-cycle orchestrator history. This doc is the
short "what should I grind next, why, in what order" reference, written
because the FFFF agent's report ("honest exhaustion is now the dominant
signal — the remaining 95 covered cards are overwhelmingly blocked at
the subsystem layer") asked for exactly that.

**Snapshot HEAD:** `25c0d410` (post-FFFF probe agent merge,
post-Aura-substrate-Phase-1 LANDED — round 78).
**Source data:** `scripts/scout_r58_subsystem_attribution.py`
(re-runnable; the same attribution helper `measure_pool_parity` imports,
so this doc and `POOL_PARITY.md` cannot disagree on the count).
**Tier under analysis:** `BLOCKED — subsystem-gated / Effect-uncovered`
(147 cards). The other BLOCKED tiers (2 `genuinely_missing`,
2 `blocked_non_effect`) are catalogued elsewhere:
`docs/BLOCKED_GENUINELY_MISSING_INVENTORY.md`.

## 1. Headline (current state)

- **147 cards** are subsystem-gated; 71 single-gated (closing one gate
  flips them), 76 multi-gated (closing one gate is necessary but not
  sufficient).
- **16 distinct subsystem gates** are in the taxonomy (the scout's
  `_gates_for_loader_card`). Of those, 14 currently bind ≥1 card.
- A card may trip multiple gates; `#cards` does NOT sum to 147. The
  honest leverage column is `decks(1g)` — the cumulative 17lands
  deck-count of single-gated members of THIS gate (closing it alone
  flips them).
- The dominant non-named buckets (`Effect-uncovered`, `Non-safe
  triggered ability`) are **diffuse** — a per-card tail, not a single
  closure; counted here for honesty but explicitly NOT a substrate
  lever.

## 2. Subsystems by closure leverage

Three columns are independent: **count leverage** (`#cards`), **deck
leverage** (`decks(1g)`), **closure scope** (substrate cost based on
this session's calibration). The "Tractability" column is the
roadmap's existing classification (contained / medium / sprawling /
diffuse); the "Closure scope" column is this doc's per-substrate cost
estimate.

| Subsystem | #cards | 1gate | decks(1g) | Tractability | Closure scope | Status |
|---|---:|---:|---:|---|---|---|
| Aura-attachment substrate | 7 | 4 | 633 | sprawling | medium-large (Phase 1 LANDED; Phases 2-4 deferred) | Phase 1 SHIPPED round 78 |
| Static / layered abilities | 15 | 8 | 34,526 | sprawling | medium-large (layer-7 CDA + grants + Static frontier) | OPEN |
| Non-basic land substrate | 23 | 23 | 34,575 | medium | small-medium (5 cards realizable; 18 deferred behind sibling substrates) | partial (5 shipped round 60) |
| Cost-reduction substrate | 5 | 5 | 53,648 | medium | large (true Rust multi-round; Condition-grammar port) | DEFERRED |
| warp_cost (declined cost-mechanic) | 10 | 3 | 15,436 | medium | medium (Phase 1+1.5+2 SHIPPED rounds 67-cycle-7) | Phase 1/1.5/2 SHIPPED |
| Dynamic-P/T formula (layer 7 CDA) | 2 | 1 | 61 | medium | small-medium (1 ready, 1 multi-gated) | PARTIAL — substrate landed round-78, ward-rider still gates live Harmonious Grovestrider |
| Station / Spacecraft | 8 | 1 | 5,938 | sprawling | large (declared §2-decline) | DEFERRED |
| Carrier activated abilities | 30 | 0 | 0 | sprawling | sprawling (per-card; no single-gated members) | DEFERRED |
| BECOMES_TAPPED event | 2 | 0 | 0 | contained | small (event bridge) — but 0 single-gated | DEFERRED |
| Ward (declined cost-mechanic) | 1 | 0 | 0 | medium | medium — 0 single-gated | DEFERRED |
| Kicker / Impending cost | 1 | 0 | 0 | medium | medium — 0 single-gated | DEFERRED |
| Rooms / doors | 3 | 0 | 0 | sprawling | large — 0 single-gated, 0 decks | DEFERRED |
| Planeswalker loyalty | 1 | 0 | 0 | sprawling | large — 0 single-gated | DEFERRED |
| Effect-uncovered (diffuse tail) | 94 | 24 | 103,349 | diffuse | per-card (Tier-A lane EXHAUSTED; Tier-C target-seating CONCLUDED; spell-card-bridge admit set = 7 cards) | per-card lane |
| Non-safe triggered ability | 43 | 0 | 0 | diffuse | per-event-shape (no single-gated members) | DEFERRED |
| Unclassified (honest residual) | 2 | 2 | 12 | diffuse | per-card hand re-walk | OPEN |

**Reconciliation:** 147 subsystem-gated = 71 single-gated + 76
multi-gated. `1gate` column sums to 71 across the 14 binding gates.
Same 147 the `POOL_PARITY.md` tier reports — the breakout partitions
the same set, this doc adds the per-subsystem leverage view.

## 3. The five highest-leverage *next* levers

Filtered to substrates that are **(a) named-and-bounded** (not the
diffuse Effect-uncovered / Non-safe-trigger tails), **(b) not already
fully closed**, and ranked by **decks(1g) ÷ remaining-closure-scope**.

### (1) Static / layered abilities — 8 single-gated, 34,526 decks, sprawling

The dominant **un-shipped** named substrate by single-gate deck count.
Includes Brightspear Zealot, Cloudsculpt Technician, Frenzied Baloth,
Gravblade Heavy, Mechan Shieldmate, Rampaging Soulrager, Tannuk
Steadfast Second, Wildfire Wickerfolk. The other 7 of the 15 are
multi-gated (Exalted Sunborn warp+static; Loading Zone warp+static;
Memorial Team Leader warp+static; Nexus of Fate effect-uncovered+
non-safe-trig+static; Starfield Vocalist warp+static; Lumen-Class
Frigate Station+static; Green Sun's Zenith effect-uncovered+static).

- **Why it's high leverage:** 34,526 decks (3rd-largest single-gate
  deck count of any named row, behind only cost-reduction-not-
  realizable 53,648 and the diffuse effect-uncovered 103,349).
- **Closure scope:** medium-large. Per-card layer-7 / layer-6 grants
  and static-ability arms; Rust already has the layer machinery
  (proven by Auras Phase 1's STEP-5 layer-7/-6 grants), so this is
  per-card grant arms riding the same machinery — not a new
  substrate-from-scratch.
- **Sequencing note:** the 8 single-gated cards are mostly
  static-pump / static-keyword carriers; close them in order of
  decks. NOT a single Rust round — each is its own Effect+bridge
  close + a probe, ~1 cycle per card.

### (2) Aura-attachment substrate — 4 single-gated, 633 decks (S1+S3); Phase 1 LANDED

Phase 1 of `docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md` SHIPPED round 78
(`STEPs 1+2+3+4+5+6+7` end-to-end through both engines for static
P/T-or-keyword Auras). **Live admit delta of Phase 1 is ZERO** (every
shipping S1 carrier — Frantic Strength, Shardmage's Rescue — carries
the non-`_SAFE_KEYWORDS` `flash` keyword that the predicate documents
as decline). The substrate landed; the leverage hasn't fired yet.

- **Phase 2 (S2 control-changing — Duskmourn's Domination + the
  Tractor Beam residue):** ~2-3 Rust rounds. Picks up `attached_-
  grants_control` + `attached_grants_lose_all_abilities` layer-2
  paths. **Net single-gate deck unlock = 0 within the subsystem-tier
  Aura row** (Duskmourn 0 decks); Tractor Beam (residue tier) flips
  to byte-equal. Cross-tier residue closure, not pool-parity-leverage.
- **Phase 3 (S4 triggered Auras — Chorale of the Void, Cracked Skull,
  Sporogenic Infection + the Pain for All residue):** ~2-3 Rust
  rounds. Net deck unlock at the Aura tier = +2,783 (Chorale alone;
  Cracked / Sporogenic 0); Pain for All (residue tier) flips. The
  3 cards are MULTI-gated (effect_uncovered + nonsafe_trig + Aura),
  so closing Aura alone doesn't flip them — needs co-closure with
  Phase 3 of the per-card Effect-uncovered lane.
- **Phase 4 (S3 replacement-effect Aura — Moonlit Meditation):**
  largest single-gated leverage in the Aura row (633 decks
  single-gate), but requires a token-replacement-effect substrate
  that is downstream of token-printing (`docs/TOKEN_PRINTING_-
  SUBSTRATE.md`).

The Aura row's *full subsystem unlock* (all 4 phases) lands roughly
3,416 cumulative decks across all 7 subsystem-tier Aura cards +
collapses 2 residue cards (Pain for All, Tractor Beam) + flips
Meltstrider's Resolve full-game byte-equal. **Pool-leverage per Rust
round is low** by raw deck count, but it is the **only path** to those
3 residue cards; substrate is the rationale, not the leverage. Cross-
ref: `docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md` §1 sub-shapes,
`docs/AURA_ATTACHMENT_PHASE1_DESIGN.md` for the just-landed
Phase 1 design.

### (3) Dynamic-P/T formula (layer-7 CDA) — 1 single-gated, 61 decks — **SUBSTRATE LANDED ROUND-78**

Smallest-by-decks named substrate but smallest scope. Single-gated
member is Harmonious Grovestrider (61 decks); multi-gated Cosmogoyf
adds CDA-with-effect-uncovered-rider.

**Round-78 substrate-extension landed**: `dynamic_pt_formula` (a new
optional `Option<String>` / `Optional[str]` field) now round-trips
through the CardDef bridge in BOTH directions; Rust's
`state_ops_combat::dynamic_base_pt_pub` dispatches on the formula
key string in lockstep with Python's `game._dynamic_base_pt`. The
`harmonious_grovestrider` arm computes P = T = lands controlled by
the formula creature's controller (CR 208.2 / layer-7b CDA) on both
engines, byte-equal. Real-EoE probe at
`test_parity_smoke.py::test_cross_engine_real_eoe_harmonious_grovestrider_dynamic_pt_parity`
pins the 0-land / 3-controlled-land / +2-opponent-land cases.

**Remaining gate (orthogonal substrate)**: the real EoE Harmonious
Grovestrider printing ALSO carries Ward {2}. The
`_printing_is_bridge_simple_creature` ward_cost gate still rejects
it; the ward-substrate slice is a separate closure target. A
synthetic Grovestrider CardDef without the ward rider admits
cleanly post-round-78. The 61 decks worth of leverage will flip
when the ward-substrate slice lands.

Sibling formulas (`cosmogoyf` / `emissary_escort`) carry different
per-formula shapes and are honest-stopped Rust-side (unknown key →
`None`); they stay on the drop-at-filter path until per-card slices
flip each in lockstep. Each is a ~1-2 cycle slice on the same
substrate (extend the Rust dispatch table arm + thread the formula
key through the bridge admit predicate); they were not part of the
round-78 closure scope.

### (4) Non-basic land substrate — 18 cards remaining, ~16,510 decks (deferred)

Partial closure shipped round 60 (5 pay-life shocklands, +18,065
decks admitted as untapped duals — the round-39-Ward-precedent
simplification). **Remaining 18 are deferred behind sibling
substrates:** real tapped-entry divergence Rust doesn't track,
activated-ability lands, clone lands, Station-bearing lands. NOT
a near-term cheap win — closing the remainder requires the activated-
ability-on-lands substrate (carrier_activated_abilities row, 30
cards, 0 single-gated). Listed for completeness; **do not sequence
in the next 5**.

### (5) Effect-uncovered diffuse tail — per-card lane, 24 single-gated, 103,349 decks

Not a single substrate; the per-card Effect-uncovered closures land
1 card at a time via a new `Effect::` variant + parse + bridge +
probe. **The cheap Tier-A single-card lane is EXHAUSTED**
(`SUBSYSTEM_ROADMAP.md` cycle 6: Radiant Strike, Seedship Impact,
Orbital Plunge, Depressurize, Biosynthic Burst, Focus Fire all
shipped). Remaining single-gated members are Tier-C-ish (combat-
shape divergence, larger Rust requirements per card) or have a
non-trivial Rust shape (`Archenemy's Charm`, `Beyond the Quiet`,
`Devastating Onslaught`, `Singularity Rupture`, etc.).
**Per-card cost: 1-3 cycles each; pool-flip per cycle: 1 card +
its deck count.** Cumulative reach is the largest of any single
row but the cadence is **incremental**, not "close-the-substrate".

## 4. Recommended closure sequence (top 5)

Sorted by **decks(1g) ÷ cycles-remaining** and tempered by
**unblocks-multiple-residue** (Aura substrate ranked higher than its
raw leverage because of cross-tier residue payoff):

| # | Lever | Decks(1g) | Cycles | Decks/cycle | Cross-tier? |
|---|---|---:|---:|---:|---|
| 1 | **Static / layered abilities — close Brightspear Zealot + Frenzied Baloth + Mechan Shieldmate** | ~34,526 (8 cards, ~4-6 cycles) | 4-6 | ~6,000 | no |
| 2 | **Dynamic-P/T formula — Harmonious Grovestrider** | 61 | 1-2 | ~40 | no |
| 3 | **Aura substrate Phase 2 (S2 — Duskmourn's Domination)** | 0 within tier | 2-3 | 0 (substrate move) | YES — flips Tractor Beam (residue) |
| 4 | **Aura substrate Phase 3 (S4 — Chorale of the Void)** | 2,783 (multi-gated, needs co-Effect-uncovered) | 2-3 + per-card Effect | ~700 | YES — flips Pain for All (residue) |
| 5 | **Effect-uncovered per-card lane drain — next 3-5 cheap single-gated cards** | varies (~5-15k cumulative) | 3-5 | ~3,000 | no |

**Sequencing rationale:**

- **Static abilities is the #1 named lever NOW** because Aura Phase
  1's deck delta was 0 and the cheap Effect-uncovered Tier-A lane
  exhausted. 8 single-gated cards riding existing layer machinery is
  the highest-deck-count cheap-per-cycle remaining named substrate.
- **Dynamic-P/T** is a cheap-and-fast secondary drain (1 card, ~1
  cycle); not pool-moving on its own but cleanly drains 1 from the
  tier.
- **Aura Phase 2 + Phase 3** are deferred to AFTER the Static
  drain only because their POOL_PARITY-row leverage is low — they
  matter strategically (residue tier closure) and the Phase 1
  substrate is already paid for, so each subsequent phase is
  cheaper than its substrate-from-scratch cost suggests.
- **Effect-uncovered per-card lane** continues in parallel; it's
  not a substrate, it's an ongoing per-card drain that the FFFF
  probe agent already established is dominated by honest exhaustion.

## 5. Substrates explicitly OFF the top-5

- **Cost-reduction substrate (5 cards, 53,648 single-gate decks).**
  Highest single-gate deck count of any named row, but
  `docs/COST_REDUCTION_SUBSTRATE_PLAN.md` documents the bridge-correct
  realizable yield is **0 in any near-term clean slice** — admitting
  any of the 5 ships a guaranteed inter-engine divergence (Rust defers
  `cost_reductions`; the drop is asymmetric and fires on the cast
  pipeline the bench always drives). True large multi-round Rust
  substrate. Keep deferred per cycle 5-7 sequencing notes.
- **Station / Spacecraft (8 cards, 5,938 decks).** Documented
  §2-decline; large substrate. Deferred.
- **Carrier activated abilities (30 cards, 0 single-gated, 0
  single-gate decks).** All multi-gated — closing this gate alone
  flips zero cards. Per-card frontier, not a substrate.
- **Rooms / doors, Planeswalker loyalty, Ward, Kicker, BECOMES_TAPPED.**
  All have 0 single-gated members; closing the gate alone flips
  zero cards.
- **Non-basic land substrate remainder (18 cards).** Behind
  sibling substrates (Station/activated/clone); not a clean slice.
- **Unclassified (2 cards — Deafening Silence, Leyline of Mutation).**
  Owe a hand re-walk per `SUBSYSTEM_ROADMAP.md`; flagged for the
  next residue cadence, not a sequencing lever.

## 6. Cross-references

- **`docs/SUBSYSTEM_ROADMAP.md`** — the authoritative living roadmap
  + full cycle-by-cycle orchestrator history (2090 lines as of
  this snapshot). Every claim in this doc traces back to a row in
  the roadmap's leverage table + a cycle-N fold entry. This doc is
  the static snapshot; the roadmap is the moving record.
- **`docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md`** — the 4-phase Aura
  substrate plan that lever (2) cites.
- **`docs/AURA_ATTACHMENT_PHASE1_DESIGN.md`** — the just-landed
  Phase 1 implementation design.
- **`docs/BLOCKED_GENUINELY_MISSING_INVENTORY.md`** — the residue
  tier (2 cards: Lightstall Inquisitor, Pain for All); read together
  with this doc to see how Aura Phase 2/3 lever (3-4) closes
  cross-tier (Pain for All flips when Aura S4 ships).
- **`docs/POOL_PARITY.md`** — the headline tier table; this doc
  partitions its `subsystem-gated` row.
- **`docs/residue_worklist.json`** — the per-card residue source of
  truth (2 genuinely_missing, 2 blocked_non_effect, 17 closed).
- **`docs/COST_REDUCTION_SUBSTRATE_PLAN.md`,
  `docs/WARP_COST_SUBSTRATE_PLAN.md`,
  `docs/NONBASIC_LAND_SUBSTRATE_PLAN.md`** — the §2 verify-first
  scoping audits referenced in lever (4-5) and §5 deferred items.

## 7. Caveats

- **Effect+bridge ≠ full-game-trajectory parity.** Same headline
  caveat as `docs/POOL_PARITY.md` — closing all 14 binding subsystems
  does not by itself ship whole-pool full-game byte-equality (the
  campaign's open frontier per the `LOADER_ADMIT_COMPLETENESS_ANALYSIS`
  cycle-7 finding: 48/475 = 10.1% admit, 0/129,996 decks fully
  admittable today).
- **Scope estimates are calibrated from this session's cycles 1-15+**
  (see `SUBSYSTEM_ROADMAP.md` cycle folds): small-medium 1-2 cycles
  per single-card Effect close; medium 3-5 cycles per
  bounded-substrate slice; large 6+ cycles for a new persistent
  GameObject/GameState subsystem. Re-estimate at each closure.
- **Deck counts** are 17lands EoE archetype-build appearances out
  of ~129,996. Sums across cards over-count decks containing
  multiple gated cards; the single-gate `decks(1g)` column is the
  honest leverage signal.
- **The scout is the source of truth.** Re-run
  `PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe
  scripts/scout_r58_subsystem_attribution.py` to refresh; if this
  doc and the scout disagree, the scout wins, refresh this doc.
