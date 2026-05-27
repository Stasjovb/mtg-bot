# BLOCKED-tier tractability scout (2026-05-27)

**Lane:** `feature/blocked-tail-scout-2026-05-27`
(Worker F in the 2026-05-27 parallel-agent dispatch).

**Trigger.** Heavy substrate cadence since the 2026-05-24 rescout
(`02407af5`): Phase-4A Carrier-AA multi-AA admit substrate
(`a6fe7c9c`); Phase 4B/4C/4D/4E flips on Mirrorpool / Ghost Vacuum /
Keys to the House / All-Fates Scroll; Phase 4E `ManaPool.any` coin
substrate (`daecd399` + `82bbe5b5`); Spacecraft Phase 4 closure (8/8
PROBED); Phase-3C Carrier-AA Thespian's Stage closure
(`BecomesCopyOfTargetLand` added to Phase-1 Effect admit set);
Cost-reduction Phase 1+2+3 closure (5 carriers PROBED); Aura Phase
3+ closure (3 carriers PROBED); five probe-writing flips
(`7febcb65`).

BLOCKED-subsystem-gated tier dropped from **61 cards** (rescout
HEAD) to **33 cards** at HEAD `2131d24b` — a 46% reduction in 2.5
days. This scout's question: has the cheapest tractable closure cost
moved into 1-cycle range, and is there an auto-grow flip hiding in
the new admit gates?

## TL;DR

**No 1-cycle closures exist on the 33-card BLOCKED tail.** Every
card has at least one missing Rust Effect class OR multi-cycle
substrate (parser-side AA-text gap, Rooms/Doors state machinery,
delirium-condition dispatcher, Phase-5 ReplacementEffect static
substrate, X-mana CDA, clone substrate). The Phase-4 substrate wave
landed surgically — each admit predicate gates on a NARROW shape
that the remaining 33 cards do not match.

**No auto-grow flip hiding.** Walked the Phase-3 SELF-scope
conditional anthem and Phase-4 OTHER-scope DuringYourTurn anthem
predicates against the two static-only single-gated remnants
(Rampaging Soulrager, Wildfire Wickerfolk) — both need NEW
condition-tag dispatchers (`unlocked_doors_among_rooms_at_least`,
`delirium_active`) AND state-tracking substrate (door state,
graveyard card-type count). Not a 1-disjunct widen. Walked the
Carrier-AA Phase-1 Effect admit set against the 18 Carrier-AA
BLOCKED cards — every single one carries an Effect class NOT in
the admit set. No printing in current BLOCKED clears the Phase-4
admit gates on a free auto-grow.

**Significant drift surfaced.** 12 cards cited in the 2026-05-24
rescout's per-card walk are NO LONGER in BLOCKED (Weftwalking,
All-Fates Scroll, Lumen-Class Frigate, Codecracker Hound,
Memorial Team Leader, Anticausal Vestige, Swarmyard, Mystifying
Maze, Cryogen Relic, Nutrient Block, Broodguard Elite, Syr Vondam,
Cracked Skull, Cathedral of War, Mirrorpool — most flipped through
the Phase-4 wave, the cost_reduction closure, or the
probe-writing batch).

**Recommendation:** ship a **Meteor Crater single-card closure
(~2 cycles)** — the cheapest single-Effect-class port at HEAD. It
emits exactly ONE uncovered Effect (`AddOneManaOfChosenPermanent
Color`), composes with the Phase-4E `is_mana_ability=True` AA-rider
gate that just landed, and the Carrier-AA admit framework already
carries everything else (Phase-1 cost gate, Land-side bridge). The
substrate (color-fan-out from a controlled-permanent set) is
genuinely new BUT amortizes against **Reflecting Pool** (sibling
`AddOneManaFromControlledLandsProductions`) for a future +1 free
auto-grow. Alternative if Meteor Crater is rejected: pivot to the
declined-substrate revisit (Rooms / Static-replacement / clone),
mirroring the 2026-05-24 rescout's pivot recommendation.

## Live snapshot

Re-ran `scripts/scout_r58_subsystem_attribution.py` at HEAD
`2131d24b`:

```
# subsystem-gated attribution — 33 cards (pool-parity round-58 breakout)

subsystem                                  #cards  1gate  multi  tract
Non-basic land substrate                        2      2      0  medium
warp_cost (declined cost-mechanic)              3      0      3  medium
Kicker / Impending cost                         1      0      1  medium
Static / layered abilities                      7      2      5  sprawling
Rooms / doors                                   3      0      3  sprawling
Planeswalker loyalty                            1      0      1  sprawling
Carrier activated abilities                    18      0     18  sprawling
Unclassified (honest residual)                  1      1      0  diffuse
Non-safe triggered ability                     12      0     12  diffuse
Effect-uncovered                               25      0     25  diffuse
```

Reconcile: 33 = 5 single-gated + 28 multi-gated. Sum of per-
subsystem `1gate` = 5.

Note on deck counts: the 17lands deck-pool `.json.gz` is gitignored
and ABSENT in both this worktree and the parent checkout. Every
deck count below is 0 from the scout's helper, NOT informative.
The scout's resort is per-card gate attribution; deck-count
leverage signals are unavailable this session.

## Per-card walk (all 33 cards)

For each BLOCKED card: gates set, missing Effect class(es), closure
shape, and a cycle-count estimate. Numbers reflect cycles assuming
~1 new Rust Effect variant + 1 admit-set widen + 1 cross-engine
probe per cycle (the unit shipped by today's CC/MTL/AV closures).

### Group 1 — Carrier-AA Effect ports (18 cards)

The largest single subsystem bucket. Each is structurally
DECLINED-at-Phase-4-admit-gate; every card emits at least one
Effect class outside the Phase-1 Effect set (currently 13 entries).
Closure shape is Phase-4-pattern: substrate cycle (Rust Effect
variant + bridge arm + Effect-class widen) + flip cycle (admit-set
widen + per-card real-EoE probe). Verified per-card missing-Effect
attribution via `measure_pool_parity.card_effect_classes` /
`covered_python_class_set` cross-check.

| Card | Missing Effect class(es) | #AAs | Carrier shape | Cycles |
|---|---|---:|---|---:|
| Ancient Tomb | `DealDamageToControllerAndAddMana` | 1 | Land, `{T}` mana-AA with damage rider | ~2-3 |
| Atomic Microsizer | `AtomicMicrosizerAttackEffect` | 1 | Artifact-Equipment, ATTACKS trigger | ~3 |
| Auxiliary Boosters | `CreateTokenAndAttachSelf` | 1 | Artifact-Equipment, ETB token+self-attach | ~3 |
| Baseball Bat | `TapUpToOneTargetCreature` | 1 | Artifact-Equipment, ETB attach + ATTACKS tap | ~3 |
| Blast Zone | `DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters` | 2 | Land with charge-counter substrate + bespoke wipe | ~4 |
| Contested War Zone | `ChangeControllerToCombatDamageSource` | 1 | Land, DEALS_COMBAT_DAMAGE control-change rider | ~3-4 |
| Grove of the Burnwillows | `GrantLifeToEachOpponent` (inside Sequence) | 2 | Land, `{T}` mana + 2nd mana-AA with life rider | ~2 |
| Haunted Screen | `BecomeType` (inside Sequence) | 3 | Artifact, 3 AAs including {7}+1+1 counters + becomes-Spirit | ~3-4 |
| Lavaclaw Reaches | `PumpSelfXPowerUEOT` (nested in `BecomeLandCreatureUEOT.granted_activated_abilities`) | 1 | Manland — `BecomeLandCreatureUEOT` with nested AA | ~4 |
| Lotus Field | `SacrificeNLandsYouControl` | 1 | Land, ETB sac + `{T}` color-choice mana-AA | ~3 |
| Meteor Crater | `AddOneManaOfChosenPermanentColor` | 1 | Land, `{T}` mana-AA with controlled-permanent-color fan-out | **~2** |
| Nesting Grounds | `MovePlusOneCounterBetweenPermanentsYouControl` | 1 | Land, `{1}{T}` counter-move bespoke | ~3 |
| Pinnacle Starcage | `CreateNTokensFromLastExileRecall`, `ExileAllMatchingUntilSourceLeaves`, `MoveEachExiledWithSourceToOwnersGraveyard` | 1 | Artifact, 3 missing effects + ETB exile substrate | ~5+ |
| Reflecting Pool | `AddOneManaFromControlledLandsProductions` | 1 | Land, `{T}` mana-AA with controlled-land-productions fan-out | **~2** |
| Robe of Stars | `PhaseOutEquippedCreature` | 2 | Artifact-Equipment, phasing substrate | ~4+ |
| Saw | `SawAttacksOptionalSacDrawEffect` | 1 | Artifact-Equipment, ATTACKS optional-sac+draw bespoke | ~3 |
| Sliver Overlord | `GainControlOfTargetSliverPermanently` | 2 | Legendary creature, search-Sliver + permanent-control-change | ~4 |
| Wandering Fumarole | `SwitchSourcePowerToughnessUEOT` (nested in `BecomeLandCreatureUEOT.granted_activated_abilities`) | 1 | Manland — `BecomeLandCreatureUEOT` with nested AA | ~4 |

**Sibling-amortization:** Meteor Crater + Reflecting Pool share a
color-fan-out mana-AA substrate (color-set differs: controlled-
permanent colors vs. controlled-land productions); closing one
ships ~70% of the other. Lavaclaw Reaches + Wandering Fumarole
both need the `BecomeLandCreatureUEOT` Manland substrate; closing
one ships ~80% of the other.

### Group 2 — Static / layered remnants (7 cards, 2 single-gated)

| Card | Gates | Static shape | Closure scope | Cycles |
|---|---|---|---|---:|
| Exalted Sunborn | warp+static | `ReplacementEffect(WOULD_CREATE_TOKEN, MultiplyCount(factor=2))` | Phase-5 ReplacementEffect static substrate (NEW family) | ~4 |
| Starfield Vocalist | warp+static | `ReplacementEffect(TRIGGERED_ABILITY_TRIGGERS, AddInstances(delta=1))` | Same family | ~4 |
| Loading Zone | warp+static | `ReplacementEffect(WOULD_PLACE_COUNTER, MultiplyCount(factor=2))` | Same family | ~4 |
| Green Sun's Zenith | effect-uncovered + static | Bespoke `SearchLibraryForGreenCreatureWithMVAtMostX` | X-mana search substrate | ~3-4 |
| Nexus of Fate | effect-uncovered + static | Bespoke `TakeExtraTurnAfterThisOne` | Extra-turn substrate (declined) | ~5+ |
| Rampaging Soulrager | static (single-gated) | `ContinuousModifier(layer=7, PT(+3/0))`, `scope='self'`, `condition=UnlockedDoorsAmongRoomsAtLeast(n=2)` | Phase-3 condition widen + Rooms-state dispatcher | ~3 |
| Wildfire Wickerfolk | static (single-gated) | 2 statics: layer-7 PT(+1/+1) + layer-6 GrantKeyword(trample), both `scope='self'`, `condition=DeliriumActive()` | Phase-3 condition widen + delirium-state dispatcher | ~3 |

**Phase-3 SELF-scope conditional anthem substrate has shipped** (3
recognized conditions: `control_permanent_is_artifact`,
`at_least_n_spells_cast_this_turn`,
`controlled_artifact_entered_this_turn` — verified at
`trajectory.py:11689`+ and `state_ops_combat.rs:495`+). Both
remnants match the layer-vocab/payload-vocab of the existing
substrate; only the CONDITION is novel. Both also are absent from
the EoE snapshot (Duskmourn cards) — 0 deck leverage. Net: NOT a
1-cycle widen because the condition needs new state-tracking too.

**Phase-4 OTHER-scope DuringYourTurn anthem (MTL substrate):**
Verify-first — no 1-card auto-grow today. The 3 warp+static
remnants (Exalted Sunborn, Starfield Vocalist, Loading Zone) all
emit `ReplacementEffect`, which the MTL Phase-4 admit predicate
rejects on the `replacement_effect is not None` gate. The MTL
substrate is surgical (Verified live pool admits EXACTLY ONE card
post-flip: Memorial Team Leader).

### Group 3 — Effect-uncovered / non-safe-trigger (cross-cutting)

The `effect_uncovered` (25) + `nonsafe_triggered_ability` (12) rows
are diffuse co-gates — Carrier-AA + Rooms cards above also trip
these. Effect-uncovered carriers without Carrier-AA gating:

* **Green Sun's Zenith** — `SearchLibraryForGreenCreatureWithMVAtMostX`;
  X-pip-cost substrate + new Effect (~3-4 cycles).
* **Nexus of Fate** — `TakeExtraTurnAfterThisOne` (extra-turn
  substrate broadly declined — search-state explosion).
* **Tezzeret, Cruel Captain** — planeswalker (declined) + ETB
  trigger `PutLoyaltyCounterOnSelf`.
* **Consult the Star Charts** — bespoke effect + Kicker (declined).

Each is 3+ cycles gated on a declined-substrate revisit; none clear
for a 1-cycle slice.

### Group 4 — Rooms / Doors (3 cards)

| Card | Effect | Cycles |
|---|---|---:|
| Charred Foyer // Warped Space | `ExileTopOfLibraryMayPlayThisTurn` | ~5 |
| Meat Locker // Drowned Diner | `TapAndStunUpToOneTargetCreature` | ~5 |
| Unholy Annex // Ritual Chamber | `ConditionalIfYouControlSubtype` | ~5 |

Rooms/Doors substrate is sprawling — full Rooms mechanic
(entering-Room triggers, CR-715 win-condition, per-half mana costs)
is multi-month. Phase 4D landed a minimal `door_states: Option<u8>`
slot for Keys to the House but the full Rooms gameplay substrate
remains deferred (per `c19a7928` Phase 4 design doc §3.11). Not
recommended.

### Group 5 — Non-basic land + Unclassified (3 single-gated)

* **Secluded Starforge** — listed as nonbasic-land-substrate
  single-gated, but the parsed printing is EMPTY (parser dropped 3
  AAs the live engine cannot represent). Real closure is parser-
  side AA-text recognition, NOT a nonbasic-land slice. Multi-cycle.
* **Echoing Deeps** — `optional_copy_land_from_graveyard=True`.
  Closure is the **clone substrate** (Phase 7+ deferred per
  `_printing_is_bridge_nonbasic_mana_land` honest-stop at
  `trajectory.py:8464`). Multi-cycle, declined.
* **Leyline of Mutation** — Enchantment, empty parsed printing
  (same parser-side gap). Per the inventory the residue worklist
  flags it for hand re-walk. Multi-cycle, NOT in EoE snapshot.

## Drift findings

15 cards cited in the 2026-05-24 rescout's per-card walk have
shipped and are NO LONGER in BLOCKED: Weftwalking (rescout
recommendation #1), All-Fates Scroll, Lumen-Class Frigate,
Codecracker Hound, Memorial Team Leader, Anticausal Vestige,
Swarmyard, Mystifying Maze, Cryogen Relic, Nutrient Block,
Broodguard Elite, Syr Vondam, Cracked Skull, Cathedral of War,
Mirrorpool. STILL BLOCKED from the rescout's list: Tezzeret /
Consult the Star Charts (declined subsystems), Starfield Vocalist
+ Exalted Sunborn + Loading Zone (ReplacementEffect statics),
Lavaclaw Reaches + Wandering Fumarole (Manland), Ancient Tomb.

The pool-parity headline (`docs/POOL_PARITY.md`) is in sync with
the residue worklist (0 violations); no silent drift in the
tier-classification.

## Why no 1-cycle closure exists today

For a 1-cycle flip ALL of must hold: (1) every Effect the card
emits is already Rust-covered, (2) the bridge admit predicate
passes/fails on a NARROW admit-side widen with no new substrate
behind it, (3) the card's subsystem is not §2-declined.

NO card in the current 33-card tail clears all three: all 18
Carrier-AA cards fail (1) — every one emits at least one Effect
not in `_carrier_aa_phase_1_effect_classes()`; both static-only
single-gated (Soulrager, Wickerfolk) fail (2) — new condition tag
+ state-tracking substrate needed; all 3 warp+static fail
(1)+(2) — `ReplacementEffect`-static outside MTL Phase-4 admit;
all 3 Rooms/Doors fail (3); Tezzeret + Consult + Nexus + Green
Sun's Zenith fail (3) on subsystem decline; Secluded Starforge +
Leyline of Mutation fail (1) on parser-side empty printings.

## Ranked top-3 candidates (post-walk)

Ranked by cycles-to-close + sibling-amortization, not deck count
(no leverage data in this scout). Tie-break favors substrates that
amortize to a future free auto-grow.

### #1 — Meteor Crater (~2 cycles)

* **Gates:** `effect_uncovered + carrier_activated_abilities`.
* **Resolve:** single AA `{T}: AddOneManaOfChosenPermanentColor`,
  `is_mana_ability=True`. No triggers, no statics.
* **C1 (substrate):** new `Effect::AddOneManaOfChosenPermanentColor`
  Rust unit variant + parse + `to_pydict` + resolve (build color
  set from `controller.battlefield` permanent-color union, agent
  picks one, mint 1 mana) + cross-engine bridge arm +
  `_carrier_aa_phase_1_effect_classes` widen 13 → 14.
* **C2 (flip):** admit-set pin bump + per-card real-EoE MINT+PAY
  byte-equal probe. The Phase-4E `is_mana_ability=True` AA-rider
  gate already landed (`daecd399`); no additional rider work.
* **Sibling discount:** **Reflecting Pool auto-grows on the same
  substrate** with a different color-set predicate (union of
  controlled-lands' `produces`). After Meteor Crater C1, Reflecting
  Pool needs only the sibling Effect variant + Effect-class admit
  widen + probe — ~1-1.5 cycles instead of 2.
* **Verify-first §2 teeth:** color set bounded to `{W,U,B,R,G}`
  (no `any` wildcard); deterministic agent-pick under no-agent
  harness uses the canonical ordinal — match Phase-4E "any" code-
  path's canonical-first choice as the precedent.
* **What this does NOT amortize:** Lavaclaw + Wandering Fumarole
  (Manland substrate, different Effect family); Ancient Tomb
  (damage rider + mana, not the chosen-color shape).

### #2 — Reflecting Pool (~2 cycles standalone, ~1.5 after Meteor Crater)

* **Gates:** `effect_uncovered + carrier_activated_abilities`.
* **Resolve:** single AA `{T}: AddOneManaFromControlledLandsProductions`,
  `is_mana_ability=True`.
* **Closure:** same shape as Meteor Crater but predicate union is
  `printing.produces` across `controller.battlefield` filtered to
  `card_types contains 'Land'`. Substrate composes ~80% with
  Meteor Crater's C1.
* **Recommendation:** ship as the immediate follow-on to #1 — the
  cheapest two-card sweep on the BLOCKED tail at HEAD.

### #3 — Grove of the Burnwillows (~2-3 cycles)

* **Gates:** `effect_uncovered + carrier_activated_abilities`.
* **Resolve:** AA[0] `{T}: AddManaToPool(C)` (Phase-4E-bridged).
  AA[1] `{T}: Sequence(AddNManaOfChosenColor(1, ('R','G')),
  GrantLifeToEachOpponent(1))`.
* **Closure:** (a) new Rust Effect `GrantLifeToEachOpponent`
  (walks opponents, adds N life each); (b) **the load-bearing
  piece** — Sequence-in-AA admit (Phase-1 Effect admit today is
  LEAF-only); (c) mechanical Phase-1 widen. The Sequence-in-AA
  substrate is novel; closing Grove ships a substrate that
  amortizes to any future Carrier-AA card with a multi-step AA
  resolve body. ~2-3 cycles depending on Sequence factor-out.

## What is NOT a candidate (honest-stops)

* **Lavaclaw / Wandering Fumarole** — Manland substrate
  (`BecomeLandCreatureUEOT` + nested AA + UEOT layer-7 P/T+ability
  application). ~4 cycles each; pair-amortizes.
* **Ancient Tomb** — `DealDamageToControllerAndAddMana` is the
  whole Effect, no sibling. ~2-3 cycles, no auto-grow.
* **Sliver Overlord** — permanent control-change AA (different
  surface from Aura `attached_grants_control`). ~4 cycles.
* **Pinnacle Starcage** — 3 missing Effects + exile-with-source
  state. ~5+ cycles.
* **Saw / Atomic Microsizer / Baseball Bat / Auxiliary Boosters**
  — Equipment-AA bridge + ATTACKS-trigger substrate; ~3 cycles
  each (Equipment-attached-host predicate + bespoke combat
  trigger).

## Free auto-grow flip — none surfaced

The dispatch flagged "Singularity Rupture's PROBED+1 lane" — a
narrow substrate that flipped a single card. Walked the three most
recent narrow substrates against current BLOCKED:

**Phase-4E `is_mana_ability=True` AA-rider gate + `ManaPool.any`
coin substrate** (`daecd399` + `82bbe5b5`): the AA-rider gate was
the LAST teeth for All-Fates Scroll; no other BLOCKED card is gated
SOLELY on `is_mana_ability=True` (every Carrier-AA mana-AA also
lacks the Effect-class admit). The "any" coin only matters for
`AddManaToPool(produces=('any',1))`; All-Fates Scroll was the only
EoE printing with this shape. **No free flip.**

**Phase-4A multi-AA admit substrate** (`a6fe7c9c`): admits per-AA
all-or-nothing iff every AA passes `_aa_is_phase1_sub_shape_a`.
The four Phase-4 carriers all closed in 4B-4E. Every remaining
multi-AA card in BLOCKED has at least one AA failing the Effect
gate (Robe of Stars `PhaseOutEquippedCreature`; Haunted Screen
`Sequence(...,BecomeType)`; Blast Zone `PutChargeCountersOnSelf` +
charge-counter-wipe; Grove of the Burnwillows AA[1] `Sequence`;
Lavaclaw / Wandering Fumarole `BecomeLandCreatureUEOT`). **No
free flip.**

**Phase-3 SELF-scope conditional anthem** at `trajectory.py:11689`+:
admits 3 conditions today; both remnants (Soulrager, Wickerfolk)
need new condition tags. **No free flip.**

## Recommended next Worker dispatch

**Default: Meteor Crater single-card closure (~2 cycles).**
Highest substrate-amortization-per-cycle on the BLOCKED tail at
HEAD. Composes cleanly with Phase-4E payment-time work (just
landed) and the Phase-4A multi-AA admit keystone. **Reflecting
Pool becomes a ~1.5-cycle free auto-grow** after Meteor Crater
C1 — treat Reflecting Pool as the immediate follow-on, or pair
both into a single Worker landing.

**Fallbacks:**

1. **Lavaclaw + Wandering Fumarole** under Manland substrate
   (`BecomeLandCreatureUEOT`). ~4 cycles + ~1.5 sibling. Heavier
   substrate, broader future amortization to Manland cards in
   subsequent sets.
2. **Declined-substrate revisit.** The 2026-05-24 rescout's
   primary recommendation (cost_reduction revisit) is now obsolete
   — that subsystem closed (`dbbc1a41`). Remaining: Rooms-full
   (3 cards), ReplacementEffect static (3 cards), Kicker (1),
   extra-turn (1). ReplacementEffect static is ~3-4 cycles per
   card but ships a Phase-5 family substrate.
3. **Soulrager OR Wickerfolk single-card slice.** Phase-3
   condition widen + state-tracking substrate. ~3 cycles, 0 deck
   leverage (Duskmourn cards, not in EoE snapshot).

**Honest-stop check.** Today's BLOCKED count is dominated by
genuine multi-cycle work (18 Carrier-AA Effect ports, 3 Rooms,
3 ReplacementEffect statics, 4 declined-subsystem-gated, 3
parser-side gaps). The 1-cycle closure surface is empty.

## Scope sanity

* This scout: docs-only. No engine, test, or script changes.
* Test gate verified: `pytest tests/test_measure_pool_parity.py
  --no-cov -q` → 32/32 pass at HEAD `2131d24b`.
* No silent drift between residue worklist and pool-parity tier
  counts (residue's `genuinely_missing` rows hard-pin to BLOCKED
  per the metric's design).

## Cross-references

* Pool parity headline: `docs/POOL_PARITY.md` (PROBED 408 /
  covered 34 / BLOCKED 33 / pool 475 at HEAD `2131d24b`).
* Live scout: `scripts/scout_r58_subsystem_attribution.py`
  (33-card snapshot; sums to 5 single-gated + 28 multi-gated).
* Phase-1 Carrier-AA Effect set: `trajectory.py:8953`+
  (`_carrier_aa_phase_1_effect_classes`).
* Phase-1 Carrier-AA AA admit: `trajectory.py:9258`+
  (`_aa_is_phase1_sub_shape_a`).
* Phase-3 SELF-scope conditional anthem: `trajectory.py:11689`+
  (`_static_ability_to_self_conditional_bonus`); Rust dispatcher
  at `state_ops_combat.rs:487`+ (`static_self_bonus_condition_
  matches`).
* Phase-4 OTHER-scope DuringYourTurn anthem: `trajectory.py:11915`+
  (`_static_ability_is_phase4_anthem_pt_conditional`) +
  `trajectory.py:12009`+
  (`_printing_is_bridge_static_anthem_pt_conditional_warp_creature`).
* Nonbasic-land substrate: `trajectory.py:8390`+
  (`_printing_is_bridge_nonbasic_mana_land`).
* Phase-4 design doc: `docs/CARRIER_AA_SUBSTRATE_PHASE_4_DESIGN.md`
  (4-sub-phase landing spec).
* Prior scouts: `docs/MULTI_GATED_TAIL_TRACTABILITY_SCOUT_2026-05-24.md`
  (morning, 64-card snapshot pre-Worker-B);
  `docs/MULTI_GATED_TAIL_TRACTABILITY_RESCOUT_2026-05-24.md`
  (rescout, 61-card snapshot post CH/MTL/AV).
* Inventory: `docs/SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY.md` (stale
  per-card lists; subsystem taxonomy + closure-plan rationales
  still authoritative).
