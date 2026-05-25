# Multi-gated tail tractability RESCOUT (2026-05-24, p1)

**Lane:** `feature/multi-gated-tail-tractability-rescout-2026-05-24-p1`
(Worker B in the second 2026-05-24 parallel-agent dispatch).

**Trigger.** Today's session, between the morning scout (`fdc3b8d6`,
`docs/MULTI_GATED_TAIL_TRACTABILITY_SCOUT_2026-05-24.md`) and this
rescout, landed substantial multi-cycle substrate:

  * **Codecracker Hound** — C1 parser fold `bd37cca0`
    (`reveal_chosen` kwarg + `LookAtTopTwoSplitHandGraveyard` → alias
    collapse), C2 admit widen `278992d7` (9th ENTERS+IsSelf
    safe-trigger leaf + Creature-side warp admit), C3 probe
    `6f99bf45` (per-card real-EoE byte-equal probe). **CLOSED →
    PROBED** (~22,144 decks).
  * **Memorial Team Leader** — C1 substrate `1d6f5cd3` (StaticAnthem
    extended with `power_bonus`/`toughness_bonus`/`condition_tag`/
    `condition_args` + DuringYourTurn dispatcher + reader fold), C2
    admit-widen `f94fa44d` (new `_printing_is_bridge_static_anthem_pt_
    conditional_warp_creature` predicate). **CLOSED → PROBED**
    (~6,229 decks).
  * **Anticausal Vestige** — C1 substrate `e148450a`
    (`Effect::AnticausalVestigeLeavesEffect` Rust unit variant), C2
    admit-widen `c32f07f9` (LEAVES_BATTLEFIELD 5th safe-trigger event
    + AV unit dispatch). **ADMITTED at warp arm; covered-by-
    construction** (Worker A's C3 probe in flight as of this rescout's
    write — flips the +1 PROBED row when it lands; ~6,900 decks).

Plus from prior sessions today: CC C2a 3-slot StackItem plumbing
(`78ebda90`), CC C2b admit `82ad3611`, WW C4 modal envelope
(`8e47c1bf`).

**Live snapshot (re-run of `scripts/scout_r58_subsystem_attribution.py`
+ the worktree-local per-card dumper `scripts/dump_blocked_tail_2026_05_
24_rescout.py`):** 61 BLOCKED-subsystem-gated cards (down from the
morning scout's 64; CH + MTL closed; AV stays covered-by-construction
pending C3 probe). Reconcile: 61 = 11 single-gated + 50 multi-gated.
Subsystem rows post-flips: warp_cost 3 (was 6; CH + MTL + AV all paid
the warp leg), Static / layered 8 (was 9; MTL flipped), Effect-
uncovered 46 (was 48). Carrier-AA still 30 (sprawling DEFERRED).

## TL;DR

**No 1-cycle closure surfaces above the morning scout's top 3.** The
morning scout already identified CH / MTL / AV as the cheapest
candidates (~2-3 cycles each); all three landed or are landing today,
and the **next-cheapest tier on the 61-card tail is a structural
multi-cycle step UP** — Phase-5-shape ReplacementEffect static substrate
(Starfield Vocalist / Exalted Sunborn / Loading Zone), a Phase-4
Spacecraft-tier-gated anthem composite (Lumen-Class Frigate, crosses
the §2-declined Station/Spacecraft substrate), or the diffuse 30-card
Carrier-AA tail (sprawling §2-DEFERRED per the inventory). **Each of
today's substrate landings was admitted on the narrowest possible
predicate** (verify-first checks in each commit confirm zero silent
auto-grows): CH C2 admits only CH (the new `LookTopN` leaf is gated on
`reveal_chosen=False` + safe-trigger ENTERS+IsSelf), MTL C2 admits
only MTL (the new predicate gates on `DuringYourTurn` AND `warp_cost`
AND scope `other_creatures_you_control` AND no riders), AV C2 admits
only AV (the new `LEAVES_BATTLEFIELD` safe-trigger leaf is gated on
the bespoke `anticausal_vestige_leaves_effect` unit dispatch — the 4
other LEAVES carriers in the pool all reject on the effect-set gate).
**The substrate landings are SURGICAL — they do not enable sibling
closures.**

**Recommendation: pivot off the multi-gated tail for the next
dispatch.** The lane's economics now look like: cheapest remaining
single-card closure is 2-3 cycles (`Weftwalking`, `Consult the Star
Charts`, `Tezzeret, Cruel Captain`); higher-leverage closures are
3-4+ cycles (Phase-5 ReplacementEffect substrate for warp+static
remnants, AV-like LEAVES bespoke unit variants for the 4 other
carriers, modal-envelope siblings for All-Fates Scroll). The
morning scout's pivot recommendation (X-value or
control-change-UEOT substrate families — both have demonstrated
amortization) still stands. **Default next dispatch: revisit the
remaining single-gated `cost_reduction` row (5 cards, ~53,648 decks)
or the X-value family per `SUBSYSTEM_ROADMAP.md`.**

## Re-walked per-card analysis vs. today's shipped substrates

For each remaining BLOCKED card with ≥1,000 17lands decks, walked the
parsed printing's `.resolve()` body + gate set against today's five
substrate landings (CH safe-trigger leaf, MTL Phase-4 anthem
predicate, AV LEAVES-event widen, CC C2b 3-slot grammar, WW C4 modal
envelope) to test sibling-closure tractability.

### Group A — Warp + StaticAbility (Replacement-effect) remnants

The morning scout listed these as #3 alongside MTL. Re-examined
post-MTL closure:

| Card | Decks | Shape (verified via live parser) | MTL substrate composes? |
|---|---:|---|---|
| Starfield Vocalist | 5,635 | `StaticAbility(scope=self, ReplacementEffect(TRIGGERED_ABILITY_TRIGGERS, AddInstances(delta=1)))` | **No.** MTL's Phase-4 admit is `ContinuousModifier(layer=7, PowerToughnessBonus)` only; Starfield Vocalist is a `ReplacementEffect`. The predicate's `continuous_effect is not None` AND `replacement_effect is None` gates reject. |
| Exalted Sunborn | 2,440 | `StaticAbility(scope=self, ReplacementEffect(WOULD_CREATE_TOKEN, MultiplyCount(factor=2)))` | **No.** Same as above; the gate vocabularies are disjoint. |
| Loading Zone | 828 | `StaticAbility(scope=self, ReplacementEffect(WOULD_PLACE_COUNTER, MultiplyCount(factor=2)))` | **No.** Same as above. |

**Sibling-closure cost:** Phase-5 substrate — new
`ReplacementEffect`-static admit family. Each `EventPattern.event`
vocabulary (`TRIGGERED_ABILITY_TRIGGERS`, `WOULD_CREATE_TOKEN`,
`WOULD_PLACE_COUNTER`) needs its own Rust dispatcher entry + bridge
arm + safe-set widen. Plus the `AddInstances` / `MultiplyCount`
transforms are not in the live class-coverage set. ~3-5 cycles per
card, no amortization across the three (different events).

### Group B — Carrier-AA tail with single missing-Effect class

The 30-card Carrier-AA row is sprawling DEFERRED per the inventory
(§2 — the live Carrier-AA bridge is token-only; real permanents need
a per-permanent bridge that does not exist). Today's WW C4 admit
ships only Eldrazi-Scion CREATURE TOKENS — every Carrier-AA card in
the live pool is a real permanent. **WW C4 does not compose with this
group at all** — the bridge gate is on
`_token_with_safe_activated_ability_card_def`, not on real
permanents.

Spot-checked the highest-leverage entries:

| Card | Decks | Missing Effect | Closure scope |
|---|---:|---|---|
| Lavaclaw Reaches | 1,103 | `PumpSelfXPowerUEOT` (nested under `BecomeLandCreatureUEOT.granted_activated_abilities`) | 4+ cycles — needs Manland substrate (`BecomeLandCreatureUEOT` + nested AA bridge for a real permanent). |
| Wandering Fumarole | 1,015 | `SwitchSourcePowerToughnessUEOT` (same manland nesting) | Same as above. |
| Swarmyard | 1,011 | `RegenerateTargetCreature` (subtype-restricted) | Regen substrate + subtype-filter gate on AA. ~3-4 cycles. |
| Ancient Tomb | 489 | `DealDamageToControllerAndAddMana` | Bespoke Effect + Carrier-AA real-permanent bridge. ~3-4 cycles. |
| Mystifying Maze | 454 | `ExileTargetAttackingCreatureUntilEndStep` | Bespoke + Carrier-AA. ~3-4 cycles. |

**None compose with today's WW C4 token-only widen.**

### Group C — Modal / multi-mode envelope candidates

The morning scout's WW C4 envelope close is per-mode-binder ADMIT;
the BLOCKED tail does not contain a residual modal-spell card today
(the inventory's modal carriers — Singularity Rupture, Warping Wail,
Archenemy's Charm — all closed earlier in the session). `All-Fates
Scroll` is the closest modal-ish candidate, but it's
`ActivatedAbility`-side (an AA whose effect is
`DrawCardsByConditionMultiplier(PerDifferentlyNamedLand)`) — not a
modal spell. No WW-substrate amortization.

### Group D — ENTERS+IsSelf safe-trigger siblings (CH-shape)

CH's C2 widen admits a 9th leaf `look_top_n_put_one_in_hand_rest_to_
graveyard`. Could this admit any sibling ENTERS+IsSelf carrier in the
61-card tail?

| Card | Decks | ENTERS+IsSelf Effect | CH safe-leaf admits? |
|---|---:|---|---|
| Weftwalking | 3,680 | `ConditionalIfCastFromHand(Sequence(ShuffleZonesIntoLibrary, DrawCards))` | **No.** Two missing Effect classes (`ConditionalIfCastFromHand`, `ShuffleZonesIntoLibrary`); the conditional-cast-source wrap is a new Rust variant. Multi-cycle. |
| Auxiliary Boosters | 16,203 | `CreateTokenAndAttachSelf` (bespoke); + AA `EquipToTargetCreatureYouControl` | **No.** New bespoke Effect class + the Carrier-AA gate (DEFERRED). Multi-cycle. |
| Baseball Bat | 0 | `AttachToTargetCreatureYouControl` ENTERS + `TapUpToOneTargetCreature` ATTACKS + AA Equip | **No.** New Effect class + ATTACKS+IsHost predicate (different from CH's IsSelf), + Carrier-AA. 0 decks anyway. |
| Cracked Skull | 0 | `TargetOpponentLookHandMayDiscard` ENTERS + `DestroyEnchantedPermanent` DEALT_DAMAGE | **No.** Aura subsystem (DEFERRED); 0 decks. |
| Sporogenic Infection | 0 | `TargetOpponentSacrificesCreatureOtherThanEnchanted` + similar | **No.** Aura subsystem; 0 decks. |
| Lotus Field | 162 | `SacrificeNLandsYouControl` ENTERS + Manland-like AA `AddNManaOfChosenColor` | **No.** Two new Effect classes + Carrier-AA. Multi-cycle. |
| Blast Zone | 678 | `PutChargeCountersOnSelf` ENTERS + charge-mana AA + bespoke destroy AA | **No.** Charge-counter substrate + Carrier-AA + bespoke destroy. Multi-cycle. |
| Meat Locker // Drowned Diner | 0 | Room-half ENTERS triggers | **No.** Rooms substrate (DEFERRED). |

**CH's `LookTopN` leaf does not admit any sibling at HEAD** — every
other ENTERS+IsSelf carrier in the BLOCKED tail has a different
Effect class that is not in `_SAFE_EFFECT_KEYS`. (This was the design
intent — the leaf was deliberately gated on the bespoke
`look_top_n_put_one_in_hand_rest_to_graveyard` kind so admitting it
does not silently widen the safe-set; same surgical discipline AV C2
applied for `anticausal_vestige_leaves_effect`.)

### Group E — LEAVES_BATTLEFIELD siblings (AV-shape)

AV C2's commit message explicitly enumerates the 4 other
LEAVES_BATTLEFIELD carriers and confirms each rejects post-widen:

  * **Cryogen Relic** — carries `DrawCards` (not in
    `_SAFE_EFFECT_KEYS` LEAVES leaf set).
  * **Nutrient Block** — same `DrawCards` rejection.
  * **Broodguard Elite** — `MoveSelfCountersToTargetCreatureYouControl`
    (not safe).
  * **Syr Vondam** — `Sequence(ConditionalIfSourcePowerAtLeast)` (not
    safe) AND an And-predicate (not IsSelf).

**AV's LEAVES widen is genuinely AV-only** — verify-first per the
commit's §2 teeth. Closing any of these 4 siblings is a new
bespoke-Effect cycle each. None are in the live 61-card BLOCKED tail
anyway (all 4 are already in PROBED / covered tiers because their
gating is on OTHER substrates).

### Group F — Single-gated cards (11 cards)

All 11 single-gated entries are DEFERRED per the morning scout / the
inventory:

  * **5 cost_reduction** (Gigastorm Titan / Uthros Psionicist /
    Fungal Colossus / Lashwhip Predator / Sami, Wildcat Captain;
    ~53,648 decks) — DEFERRED (guaranteed cross-engine divergence —
    inventory §4).
  * **2 nonbasic_land** (Secluded Starforge / Echoing Deeps;
    ~7,688 decks) — DEFERRED (clone + activated-abilities substrates;
    inventory §3).
  * **1 station_spacecraft** (Galvanizing Sawship; 5,938 decks) —
    DEFERRED (§2-decline; inventory §6).
  * **2 static_layered** (Rampaging Soulrager / Wildfire Wickerfolk;
    0 decks each — EoE-snapshot-absent honest-stops; per the
    trajectory.py docstring at `_static_ability_to_self_conditional_
    bonus`).
  * **1 unclassified** (Leyline of Mutation; 0 decks; an Enchantment
    with no static/trig/act/spell_effect in the parsed printing — the
    `effect_uncovered` gate is on a hand-ability or similar surface
    not modelled today; 0-deck leverage so not worth a slice).

## Ranked top-5 candidates (closure-cost estimates, post-rescout)

Ranked by **decks ÷ cycles** with the sibling-discount analysis from
the per-group walks above applied. Same cost-rubric as the morning
scout: cycles × bespoke-Rust-variant count × admit-set-gate count.

### #1 — Weftwalking (3,680 decks, ~3 cycles)

* **Gates:** `effect_uncovered + nonsafe_triggered_ability`.
* **Resolve body:** `TriggeredAbility(event=ENTERS,
  predicate=IsSelf, effect=ConditionalIfCastFromHand(
  inner_effect=Sequence(ShuffleZonesIntoLibrary(zones=
  ('hand', 'graveyard')), DrawCards(amount=7))))`.
* **Closure scope:**
  * **C1:** New `Effect::ConditionalIfCastFromHand` Rust wrap
    variant + parse + to_pydict + resolve. The wrap is a generic
    `inner_effect` wrapper (mirror of today's
    `ConditionalIfSourcePowerAtLeast` shape on Syr Vondam) — could
    amortize across future cast-source-conditional cards.
  * **C2:** New `Effect::ShuffleZonesIntoLibrary` Rust unit variant
    (parameterized by zones tuple) + parse + to_pydict + resolve.
  * **C3:** Admit widen — 10th ENTERS+IsSelf safe-trigger leaf
    gated on the new `conditional_if_cast_from_hand` kind, sibling
    to CH C2's exact shape. Plus a per-card real-EoE byte-equal
    probe and the admit-set pin bump.
* **Sibling discount:** ENTERS+IsSelf safe-trigger admit slot is
  CH-paved (today's bd37cca0 + 278992d7 — the new leaf adds 1 line
  to `_SAFE_EFFECT_KEYS` + 1 to `_SAFE_TRIGGERS` + 1 elif arm in
  `_python_ta_to_safe_dict`). The two new Rust variants are
  genuinely-new substrate. **3 cycles realistic; could be 2 if a
  pre-existing `Sequence` arm covers the body shape.**

### #2 — Tezzeret, Cruel Captain (2,311 decks, ~3 cycles)

* **Gates:** `effect_uncovered + planeswalker_loyalty +
  nonsafe_triggered_ability`.
* **Resolve body:** `TriggeredAbility(event=ENTERS,
  predicate=And(And(IsArtifact(), Controlled(YOU)), Not(IsSelf)),
  effect=PutLoyaltyCounterOnSelf(amount=1))`.
* **Closure scope:** The PLANESWALKER row is DEFERRED in the
  inventory (sprawling — full planeswalker substrate is multi-month
  work). Tezzeret's `PutLoyaltyCounterOnSelf` is a 1-Effect variant
  add, but the predicate is `And(And(IsArtifact, Controlled),
  Not(IsSelf))` — three-conjunct, not the safe-trigger
  ENTERS+IsSelf shape — needs predicate-vocab widen too. **Multi-
  cycle (3+), gated on the planeswalker substrate decline-decision
  per the inventory.** Not recommended.

### #3 — Consult the Star Charts (6,090 decks, ~2 cycles)

* **Gates:** `effect_uncovered + kicker_impending_cost`.
* **Resolve body:** Spell with `ConsultTheStarChartsEffect`
  bespoke + Kicker/Impending cost path (multi-cost substrate).
* **Closure scope:** New bespoke Rust Effect variant + Kicker
  substrate. The Kicker row is DEFERRED per inventory §6 — full
  Kicker/Impending substrate has 6,090 decks of leverage but the
  closure crosses a sprawling cost-mechanic substrate that has not
  shipped any prior closure. **2 cycles if both substrates land
  cleanly; 3+ if Kicker requires more than a one-arm widen.** Not
  recommended without an inventory-level decision on the Kicker
  row.

### #4 — All-Fates Scroll (9,073 decks, ~3-4 cycles)

* **Gates:** `effect_uncovered + carrier_activated_abilities`.
* **Resolve body:** Two `ActivatedAbility` entries — a `{T}`
  mana-AA (already covered shape) + a `{7}, T, Sac` AA whose
  effect is `DrawCardsByConditionMultiplier(condition=
  PerDifferentlyNamedLand(), description_fragment=...)`.
* **Closure scope:** Carrier-AA row is sprawling DEFERRED — the
  live bridge is token-only. All-Fates Scroll is a real permanent
  (Artifact). Closing this requires building per-permanent
  Carrier-AA substrate + the bespoke `DrawCardsByConditionMultiplier`
  + `PerDifferentlyNamedLand` Effect variants. 3-4 cycles
  minimum, gated on inventory-level Carrier-AA decline-decision.
  Not recommended.

### #5 — Lumen-Class Frigate (5,712 decks, ~3-4 cycles)

* **Gates:** `station_spacecraft + static_abilities_layered`.
* **Resolve body:** `StaticAbility(scope=other_creatures_you_
  control, ContinuousModifier(layer=7, PowerToughnessBonus(p=1,
  t=1)), tier_threshold=2)`, `station_threshold=12`.
* **Closure scope:** Has the EXACT MTL Phase-4 anthem shape on
  the static, BUT (a) `condition=None` not `DuringYourTurn` —
  MTL predicate rejects on the condition gate, (b) `tier_threshold=
  2` — needs Spacecraft-charge-counter gate, (c) `station_threshold=
  12` — needs Spacecraft substrate (DEFERRED per inventory §6).
  Phase-4 anthem substrate amortizes ~70% of one cycle (the
  `power_bonus`/`toughness_bonus` reader fold + bridge); the
  Spacecraft substrate is a multi-cycle DEFERRED row. **3-4
  cycles, gated on Spacecraft decline-decision.** Not recommended.

## Why the rescout finds zero 1-cycle closures

Every one of today's five substrate landings was admitted on a
**deliberately narrow predicate**. Per their commit messages'
verify-first sections:

* CH C2: the `LookTopN` leaf is gated on
  `reveal_chosen=False + n>=0 + ENTERS + IsSelf +
  source_is_self`. The reveal_chosen gate is the §2 silent-
  mistranslation teeth — Rust never reveals, so admitting a
  `reveal_chosen=True` instance would diverge.
* MTL C2: the new predicate gates on `DuringYourTurn` condition
  + scope `{creatures_you_control, other_creatures_you_control}` +
  layer-7 `PowerToughnessBonus` + warp_cost + no riders + no
  triggered/activated abilities. The four other warp+static
  creatures (Exalted Sunborn / Quantum Riddler / Starfield
  Vocalist / Drix Fatemaker) each positively reject under the
  strict gate (verified in the commit's §2 cross-check).
* AV C2: the `LEAVES_BATTLEFIELD` event widen admits only
  `anticausal_vestige_leaves_effect` unit dispatch via
  `_SAFE_EFFECT_KEYS`. The 4 other LEAVES carriers all reject on
  the effect-key gate.
* CC C2b: the Phase-6 `(2, 3)` heterogeneous 3-slot admit is
  pinned to one specific slot-grammar shape — no other 3-slot
  card in the pool today.
* WW C4: per-mode binder admit + Eldrazi-Scion token AA. Both
  are token-only/modal-only — none of the 30 Carrier-AA cards or
  any non-modal carrier match.

The discipline is correct (it prevents silent fan-outs that would
ship known divergences) but the cost is: **today's substrates
shipped CH/MTL/AV and nothing else.** That is on-spec.

For a card to score 1-cycle on a SIBLING substrate, the card's
gating Effect classes and predicate shape must already be covered.
Per the per-card scan above, **no card in the 61-card BLOCKED tail
matches all of: covered Effect classes + safe-trigger predicate
slot + non-DEFERRED loader subsystem.** This is the same conclusion
as the morning scout's diffuseness check, refreshed against today's
narrower admit gates.

## Recommended next Worker A dispatch

Per the dispatch's §4 honest-stop protocol: **zero new 1-cycle
closures surfaced on the multi-gated tail.** The right move is to
pivot, mirroring the morning scout's recommendation. Three concrete
options ranked by expected leverage:

1. **Pivot to the cost_reduction subsystem decline-decision.** The
   single-gated row holds 5 cards (Gigastorm Titan / Uthros
   Psionicist / Fungal Colossus / Lashwhip Predator / Sami, Wildcat
   Captain) totalling ~53,648 decks — the largest single-subsystem
   leverage pool currently DEFERRED. The inventory §4 documents the
   "guaranteed cross-engine divergence" rationale; revisiting that
   decision (is the divergence truly guaranteed at the live engine
   HEAD, or has a substrate landed since the decline that softens
   it?) is the highest-leverage research dispatch.

2. **Pivot to X-value family substrate (per morning scout's option a).**
   The X-value substrate has demonstrated multi-card amortization
   in prior cycles (Pain for All, Zero Point Ballad, Devastating
   Onslaught are in flight); a fresh slice would land sibling
   closures cheaper than the multi-gated tail's individual cards.

3. **Pivot to control-change-UEOT substrate family (per morning
   scout's option a).** Same amortization profile;
   `ThreatenTargetCreatureUEOT` / `controller_override` are
   forbidden-territory substrate the morning scout flagged.

**Default recommendation:** **option 1 (cost_reduction decline
revisit)** — highest single-decision leverage, requires no new code
(starts as a docs-only inventory refresh + per-card divergence
re-audit at live HEAD), and surfaces the largest single
subsystem-leverage gap on the parity board.

If a single-card slice is preferred (continuing the today-pattern):
**Weftwalking (3,680 decks, ~3 cycles)** is the cheapest single-card
closure remaining; its C3 admit-widen is the same shape as today's CH
C2 (a 10th ENTERS+IsSelf safe-trigger leaf), and its two new Rust
Effect variants (`ConditionalIfCastFromHand` + `ShuffleZonesIntoLibrary`)
are each a single-day Cycle each.

## Scope sanity

Today's session shipped: 3 substrate flips on the multi-gated tail
(CH 22,144 decks, MTL 6,229 decks, AV 6,900 decks in flight) + the
Worker B probe-rename sweep (+9 PROBED via probe-module canonical
naming) + Worker B Cathedral of War probe (+1 PROBED). That is ~35,000
decks of new PROBED-tier evidence in a single session — well above
typical cadence. **The right move is to consolidate today's gains by
landing AV C3 (Worker A in flight), then pivoting to the
inventory-level decline-revisit.**

## Cross-references

* Live scout: `scripts/scout_r58_subsystem_attribution.py` (61-card
  snapshot; sums to 11 single-gated + 50 multi-gated).
* Per-card dump: `scripts/dump_blocked_tail_2026_05_24_rescout.py`
  (worktree-local rescout helper; ranked by deck count desc).
* Morning scout: `docs/MULTI_GATED_TAIL_TRACTABILITY_SCOUT_2026-05-
  24.md` (`fdc3b8d6`).
* Today's substrate landings: `bd37cca0` / `278992d7` / `6f99bf45`
  (CH), `1d6f5cd3` / `f94fa44d` (MTL), `e148450a` / `c32f07f9` (AV),
  `78ebda90` / `82ad3611` (CC), `8e47c1bf` (WW C4).
* Subsystem inventory: `docs/SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY.md`
  (§§3-6 — DEFERRED-row rationales).
* Pool parity: `docs/POOL_PARITY.md` (current headline: PROBED 315,
  covered 99, BLOCKED 61).
