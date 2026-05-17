# EoE probe-readiness audit

**Data-driven survey of the Edge of Eternities card pool to identify
which cross-engine probes can land today, which are blocked by a
gap, and which gap unlocks the most cards.**

The Phase 5 probe lane has exhausted the simple-shape probe surface
(SourceIsSelf + Always-predicate + draw_cards / gain_life /
damage_each_opponent effects). Multiple in-flight slices extend the
cross-engine bridge with new effect arms and predicate variants.
This audit surveys `data/edge_of_eternities.json` (266 EoE
printings) to rank the gaps by **how many future probes each gap
unblocks**, so the next probe wave can attack the highest-yield gap
first.

---

## Current state (as of 2026-05-15, main `c62935d2`) — round-34 refresh

> **STALE — superseded by the round-35→48 batch refresh above.** This
> round-34 section's X-from-count narrative and BLOCKED-RUST-EFFECT
> headline were frozen at `c62935d2` and went stale (flagged rounds
> 47, 48); the round-49 batch refresh section at the top of the doc
> has the true current counts. Kept verbatim below for cross-round
> narrative continuity only.

Headline inventory measured directly off `main` at round-34 refresh
time (round 19 was 16 rounds + ~150 commits ago at `ec44f0d0`; the
audit was last numerically refreshed at `39d01c02`). Supersedes the
round-19 section below it, which is kept verbatim for cross-round
narrative context.

| Bucket | Round-19 | Round-34 | Delta |
| --- | --- | --- | --- |
| Bridge-arm `if kind ==` arms in `_ta_dict_to_python_effect` | 40 | **76+ effect arms** (+ 8 predicate arms + standing action/keyword arms) | +36 |
| Real-EoE probes (`test_cross_engine_real_eoe_*`) | 51 (refresh-time count incl. divergence pins as separate rows) | **50 distinct test functions** | ~ |
| Synthetic ETB probes (`test_cross_engine_synthetic_etb_*`) | 29 | **29** | 0 |
| Cross-controller-routing probes (subset of synthetic) | 21 | 21 | 0 |
| Divergence pins (subset of real-EoE) | 2 | **2** (Pinnacle Kill-Ship empty-bf, Susurian Dirgecraft token-first) | 0 |
| BLOCKED-BRIDGE-ARM (cards waiting only on a bridge arm) | ~12 | **0** | -12 (closed round 22-32) |
| BLOCKED-RUST-EFFECT residue (confirmed no Rust arm) | ~28 | **~21** | -7 (closed rounds 30-35) |

### Bridge-arm count notes

The bridge surface has expanded substantially since round 19:
attach/equip, stun-counter (`put_stun_counter_on_tapped_creature`,
`tap_target_opponent_permanent_and_stun_it`), `look_at_top_n_reveal_or_counter`,
`optional_sac_artifact_for_effect`, `search_library_for_basic_land_tapped`,
`search_library_for_card`, `look_top_n_put_one_in_hand_rest_to_graveyard`,
`put_plus_one_counter_on_each_of_up_to_n_target_creatures`, `may_do`,
`destroy_target_nonland_permanent`, `damage_each_creature`,
`destroy_all_creatures`, `each_opponent_loses_life`, `lose_life`,
`tap_enchanted_permanent`, `add_mana_to_pool`, `add_counters`,
`sacrifice`, `pump_self_until_eot`, `move_self_counters_to_target_creature_you_control`,
`pump_target_artifact_or_creature_until_eot`, `put_charge_counters_on_self`,
`draw_cards_equal_to_resolving_combat_damage`,
`deal_damage_equal_to_source_power_any_target`,
`become_land_creature_ueot`, `conditional_if_void`,
`conditional_on_tapped_creatures`, `choose_one_mode`,
`destroy_enchanted_permanent`, `grant_keyword_to_target_creature_until_eot`,
`destroy_target_land`, `return_all_creatures_from_your_graveyard_to_battlefield`,
`manifest_dread` (+ `manifest_dread_then_attach_self`,
`manifest_dread_then_put_plus_one_counters_on_it`),
`double_target_creatures_power_ueot` (round 31),
`deal_damage_to_opponent_creature_by_artifact_count` (round 32),
`put_plus_one_counters_on_self_per_other_creature_or_artifact` (round 33),
`surveil_x_equal_to_artifact_count` (round 34),
`deal_damage_to_opponent_creature_by_cards_in_hand` (round 35),
plus a tail of single-card arms.

### Round-19 → round-34 BLOCKED-RUST-EFFECT closures (per §2.6 walk)

The round-19 re-audit ended with 14 §2.6 residue entries left as
"truly BLOCKED-RUST-EFFECT (no Rust arm)". Walking that residue
against `rust/src/cards.rs::Effect` on `c62935d2`:

| Round-19 §2.6 residue entry | Cards | Rust substrate today | Status change |
| --- | --- | --- | --- |
| `TapTargetAndPutStunCounter` (Mechanozoa + Cryogen Relic activated half) | 2 | `Effect::PutStunCounterOnTappedCreature` at `cards.rs:1731` + `Effect::TapTargetOpponentPermanentAndStunIt` at `cards.rs:1747` (round 30, `2f2f79d0`); per-object `stun_counters` slot + CR 701.20 untap-step gate | **CLOSED round 30.** Both cards now BLOCKED-BRIDGE-ARM at most; bridge arms `put_stun_counter_on_tapped_creature` (cross_engine.py:2971) and `tap_target_opponent_permanent_and_stun_it` (cross_engine.py:3025) shipped concurrently. Cross-engine end-to-end probe deferred per substrate-only precedent. |
| `DoubleTargetPowerUntilEOT` (Mightform Harmonizer) | 1 | `Effect::DoubleTargetCreaturesPowerUEOT` at `cards.rs:886` (round 31, `90bc39ca`) | **CLOSED round 31.** Bridge arm `double_target_creatures_power_ueot` (cross_engine.py:5951). Real-EoE landfall probe still deferred (waits on `etb-subject-substrate` branch — Subject(IsLand) predicate). |
| `DealDamageToAnyTargetEqualToArtifactCount` (Warmaker Gunship) | 1 | `Effect::DealDamageToOpponentCreatureByArtifactCount` at `cards.rs:923` (round 32, `1583b7a2`) | **CLOSED round 32.** Bridge arm `deal_damage_to_opponent_creature_by_artifact_count` (cross_engine.py:6012). End-to-end deferred (Warmaker Gunship is a Spacecraft; needs create_token + Spacecraft predicate plumbing). First X-from-permanent-count denominator in Rust. |
| (NEW — Luxknight Breacher counters-per-other) | 1 | `Effect::PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact` at `cards.rs:1013` (round 33, `be6a5988`) | **CLOSED round 33.** Bridge arm `put_plus_one_counters_on_self_per_other_creature_or_artifact` (cross_engine.py:6383). End-to-end deferred — "enters with N counters" is modelled as an ETB trigger, end-to-end probe needs ENTERS-trigger event-dispatcher harness from `etb-subject-substrate`/`dies-event-harness`. |
| (NEW — Cerebral Download surveil-X-by-artifact-count) | 1 | `Effect::SurveilXEqualToArtifactCount` at `cards.rs:1066` (round 34, `515fb4be`) | **CLOSED round 34.** Bridge arm `surveil_x_equal_to_artifact_count` (cross_engine.py:6467). End-to-end deferred — Cerebral Download is an INSTANT (Sequence: surveil-X then draw-3); needs cast-spell driver harness. |
| (NEW — Roaring Furnace damage-by-cards-in-hand) | 1 | `Effect::DealDamageToOpponentCreatureByCardsInHand` at `cards.rs:970` (round 35, `c62935d2`) | **CLOSED round 35.** Bridge arm `deal_damage_to_opponent_creature_by_cards_in_hand` (cross_engine.py:6546). End-to-end deferred — Roaring Furnace is a Room (split-card variant); Room/door subsystem is review-gated. First X-from-cards-in-hand denominator; confirms X-from-count plumbing is bidirectionally extensible across both (substrate × denominator). |
| `CastFromExileWithCostHike` (Lightstall Inquisitor) | 1 | No Rust arm | **STILL BLOCKED.** |
| `SacUnlessYouTap` (Command Bridge) | 1 | No Rust arm | **STILL BLOCKED.** |
| `ReturnPermanentCardWithMVXorLessFromGY` (Astelli Reclaimer) | 1 | No mana-value-condition GY-return arm | **STILL BLOCKED.** |
| `PumpAndGrantDiesReturnTrigger` (Perigee Beckoner) | 1 | No nested-trigger-grant substrate | **STILL BLOCKED.** |
| `TwoMobileSubjects` (Monoist Circuit-Feeder) | 1 | ~~No simultaneous-two-target substrate~~ | ~~**STILL BLOCKED.**~~ **STALE — corrected round 54.** Closed round 51: `Effect::TwoSubjectPumpAndDebuffByArtifactCount` + bridge arm `two_subject_pump_and_debuff_by_artifact_count` + a genuine real-EoE byte-equal cross-engine probe (~14,727 decks). The plan-invented `TwoMobileSubjects` name resolves to the shipped variant. **NOT BLOCKED-RUST-EFFECT** → PROBED/CLOSED. (One of the 2 entries the round-54 full re-walk surfaced beyond the known r51/r53 three.) |
| `EachOpponentExilesFromHand` (Lightstall Inquisitor — same card as above) | 1 | No Rust arm | **STILL BLOCKED.** |
| `EnchantedDealsDamageThenPropagate` (Pain for All) | 1 | No self-replicating damage substrate | **STILL BLOCKED.** |
| `ExileEachOpponentGYAndCreateToken` (Dauntless Scrapbot) | 1 | No exile-each-graveyard substrate | **STILL BLOCKED.** |
| `Faller's Faithful` damage-this-turn (§2.7) | 1 | No damage-this-turn ledger | **STILL BLOCKED.** |
| Aura-shape `Fight` for Meltstrider's Resolve | 1 | No `Effect::EnchantedCreatureFightsTarget` (only bare bilateral) | **STILL BLOCKED.** See `SEARCH_LIMITATIONS.md` "FightTargetCreatureWithTargetCreature first-slice" entry. |
| `OptionalCreateTwoTokensOrSelfPump` (Terrapact Intimidator) | 1 | `Effect::MayDo` at `cards.rs:1850` substrated; per-token parameterization still pending | Partial — substrate exists; bridge `may_do` arm wired (cross_engine.py:1254). Reclassify to BLOCKED-BRIDGE-ARM with token-parameterization follow-up. |
| `Roving Actuator` void-style exile-then-cast-copy | 1 | `Effect::ConditionalIfVoid` substrated (round 29); cast-copy half still missing | Partial — trigger shell can lift; cast-copy effect is the residual gap. |
| `Famished Worldsire` look-X-and-put-lands-tapped | 1 | `Effect::DealDamageEqualToSourcePowerAnyTarget` (X-from-source-power pattern) + `Effect::SearchLibraryForBasicLandTapped` exist; specific composition missing | Partial — X-plumbing pattern unblocked; composition needs new Rust. |
| `Tractor Beam` TapEnchantedYouControlAndDontUntap | 1 | `Effect::TapEnchantedPermanent` at `cards.rs:1711` substrated (control-swap + don't-untap composition still missing) | Partial — bridge `tap_enchanted_permanent` wired (cross_engine.py:4612). |
| `Pulsar Squadron Ace` choice-trigger reveal-or-counter | 1 | `Effect::LookAtTopNRevealOrCounter` at `cards.rs:2423` substrated; sub-mode for Spacecraft revelation pending | Partial — bridge `look_at_top_n_reveal_or_counter` wired (cross_engine.py:3180). |
| `DestroyNoncreatureThenAOEDamage` (Extinguisher Battleship) | 1 | All components substrated (`DestroyTargetNonlandPermanent` at `cards.rs:635`, `DamageEachCreature` at `cards.rs:145`, `Sequence`); bridge arms wired (cross_engine.py:4158, 4262, 1184) | Reclassify to BLOCKED-BRIDGE-ARM (composition probe pending). |

### Updated BLOCKED-RUST-EFFECT residue (~21 cards)

> **STALE — corrected round 54.** The verbatim residue list below is
> the round-34 snapshot and is kept verbatim per the keep-verbatim
> convention, but **3 of its entries have since had their Effect arm
> shipped + bridged** and are NOT BLOCKED-RUST-EFFECT: `Monoist
> Circuit-Feeder` (→ `TwoSubjectPumpAndDebuffByArtifactCount`, closed
> round 51, real-EoE probe); `Mightform Harmonizer` (was already
> closed round 31 as `DoubleTargetCreaturesPowerUEOT` — it never
> belonged in the no-Rust-arm list; r53 fixed a latent bug + added a
> probe); and the Extinguisher Battleship effect-half (this section
> already reclassified Extinguisher to BLOCKED-BRIDGE-ARM in the
> intro paragraph below — its `DestroyTargetNoncreaturePermanent` +
> `DamageEachCreature` + `Sequence` arms all shipped + bridged round
> 52, so it is effect-closed, Station-subsystem-gated). The **true
> honest residue is ~13 distinct new-Rust-Effect asks / 13 distinct
> cards** — see the round-54 full programmatic re-walk section + table
> above and `docs/residue_worklist.json`.

Subtracting the round-30-through-35 closures (~7 cards: 2 stun, 1
double-power, 1 damage-by-artifact, 1 counters-per-other, 1
surveil-X-by-artifact, 1 damage-by-cards-in-hand) and the
half-substrated partials reclassified to BLOCKED-BRIDGE-ARM
(Terrapact Intimidator, Extinguisher Battleship) leaves the truly
no-Rust-arm residue at:

`Lightstall Inquisitor` (cast-from-exile-with-cost-hike + each-opp-exiles-from-hand — 1 card, 2 arms),
`Command Bridge` (sac-unless-you-tap — 1 card),
`Astelli Reclaimer` (MV-condition GY-return — 1 card),
`Perigee Beckoner` (pump-and-grant-dies-trigger — 1 card),
`Monoist Circuit-Feeder` (two-mobile-subjects — 1 card),
`Pain for All` (self-propagating damage — 1 card),
`Dauntless Scrapbot` (exile-each-opp-GY-and-create-token — 1 card),
`Faller's Faithful` (damage-this-turn ledger — 1 card),
`Meltstrider's Resolve` (Aura-shape Fight via `attached_to` — 1 card),
`Roving Actuator` (exile-then-cast-copy half — 1 card),
`Famished Worldsire` (look-X-then-put-lands-tapped composition — 1 card),
`Tractor Beam` (control-swap + don't-untap composition — 1 card),
`Pulsar Squadron Ace` (Spacecraft sub-mode of look-N-reveal-or-counter — 1 card),
plus the §2.6 single-card tail entries from `LandfallWithComplexEffect`
(Seedship Agrarian, Remnant Elemental — counter/pump landfall composers
that need new Rust arms), and any audit entries elsewhere this round
didn't enumerate. **Approximate residue: ~21 cards / ~14 distinct
new-Rust-arm asks.**

### Round-22 → round-32 BLOCKED-BRIDGE-ARM closure (count → 0)

The round-19 re-audit identified ~12 cards in the BLOCKED-BRIDGE-ARM
bucket (most reclassified from BLOCKED-RUST-EFFECT once their Rust
substrate was discovered). Rounds 22-32 closed every entry on that
list via per-arm bridge slices: `attach_to_target_creature_you_control`
(round 22), `equip_to_target_creature_you_control` (round 22),
`optional_sac_artifact_for_effect` (round 24),
`look_at_top_n_reveal_or_counter` (round 25),
`search_library_for_basic_land_tapped` (round 26),
`search_library_for_card` (round 29 via
`feature/bridge-search-library-for-card` merge),
`look_top_n_put_one_in_hand_rest_to_graveyard` (round 27),
`put_plus_one_counter_on_each_of_up_to_n_target_creatures` (round 27),
`tap_enchanted_permanent` + `add_counters` + `sacrifice` and the
broader long-tail of unit-variant arms across rounds 23-32.

**Current BLOCKED-BRIDGE-ARM count: 0.** Every effect with a Rust
substrate has a bridge arm. Cards still pending probes are pending
for one of three reasons: (a) the probe-slice work hasn't been
budgeted (still-eligible-to-ship today), (b) the probe needs a
review-gated branch (`etb-subject-substrate` for landfall/ANOTHER-X
predicates, `dies-event-harness` for DIES triggers, `cast-spell-driver`
for instant/sorcery cross-engine probes, Room/door subsystem for
Roaring Furnace), or (c) the card is in the BLOCKED-RUST-EFFECT
residue above.

### Recommendation (round-34 refresh)

The audit's structural assumption ("BLOCKED-BRIDGE-ARM is a queue;
BLOCKED-RUST-EFFECT needs new code") has stabilized. The remaining
backlog has two distinct shapes:

1. **Review-gated branches** (`etb-subject-substrate`,
   `dies-event-harness`, cast-spell driver harness, Room/door
   subsystem). Merging these unblocks the end-to-end cross-engine
   probes for the dynamic-X family (rounds 31-35), every landfall
   composer, and Cerebral Download / Roaring Furnace specifically.
2. **True new Rust** (~13-14 distinct unique arms left). Each
   shipped one round of work (rounds 28-35 averaged 1 arm/round);
   at sustained cadence the residue closes in 13-14 rounds.

The audit refresh cadence proposed in round 19 (cron diffing Rust
+ bridge arm counts vs audit tally) was not implemented; rounds
28-35 again each added shadow-substrate the prior text didn't
track. The cron remains the right intervention.

---

## Current state (as of 2026-05-16, main `8e584628`) — round-35→48 batch refresh

> **Round-51 mis-bucketing correction (content-correction, not a
> re-survey).** Round-50 N2's residue scoping
> (`docs/RESIDUE_CARD_PLANS.md`) walked each carried residue name
> against the *live* `Effect` enum + `_ta_dict_to_python_effect` arm
> inventory and found **2 of the carried BLOCKED-RUST-EFFECT names
> were never Rust-Effect-blocked** — their Effect arms shipped rounds
> ago and are bridge-wired:
> - **Mechanozoa** (~21,779 decks): exact ETB is
>   `Effect::TapTargetOpponentPermanentAndStunIt`, shipped **round-30**
>   (`cards.rs:2468` enum / `5037` parse / `7187` to_dict /
>   `state_ops_resolve.rs:7839` resolve) and bridge-wired round-30
>   (`cross_engine.py:3168` → `tap.py:217`). The §2.6 / §round-19 "no
>   StunCounter substrate in Rust — Confirmed" line is **STALE**
>   (predates round-30, never re-checked). Mechanozoa's only residual
>   blocker is the `warp_cost` keyword gating the *production-deck
>   loader admit* — a §2-declined cost-mechanic — **NOT the Effect
>   arm**. → reclassified to **BLOCKED-FILTER (warp_cost)**.
>   Round-51 N3 dropped a zero-Rust real-printing cross-engine probe
>   (`test_cross_engine_real_eoe_mechanozoa_etb_tap_target_opponent_permanent_and_stun_it_parity`,
>   byte-equal both engines) confirming the round-trip — no Rust
>   change, no `.pyd` rebuild.
> - **Warmaker Gunship** (~5,926 decks): ETB is exactly
>   `Effect::DealDamageToOpponentCreatureByArtifactCount`, shipped
>   **round-32** and bridge-wired (`cross_engine.py:6326`); a
>   round-32 deferred-EoE end-to-end probe already exists in
>   `test_parity_smoke.py`. The residual blocker is the
>   `Station` ability + `Spacecraft` artifact type, **not the Effect
>   arm**. → reclassified to **BLOCKED-Station-subsystem** (not an
>   Effect gap).
>
> Net: the carried ~17 BLOCKED-RUST-EFFECT names included these 2
> mis-bucketed entries; the round-51 figure was **~15 distinct asks,
> not ~17** — these 2 were never Rust-Effect-blocked, so the count did
> not "shrink", the bucket was over-counted. This is the **same
> staleness class the round-34 and round-49 refreshes flagged** (audit
> headline frozen while substrate shipped underneath it), and it
> strengthens the round-19 cron proposal.
>
> **STALE — corrected round 54: the round-51 "~15" was itself stale.**
> The full programmatic re-walk (round-54 section above) found 2 more
> stale entries — **Monoist Circuit-Feeder** (Effect closed round 51)
> and **Extinguisher Battleship** effect-half (closed round 52) — both
> still listed in the residue tables when this round-51 note was
> written. The **true honest residue is ~13 distinct new-Rust-Effect
> asks / 13 distinct cards** (round-51 −2 + round-54 −2 vs the carried
> ~17). The headline count line and the residue body below are
> corrected in place; the per-card bucket rows for Mechanozoa /
> Warmaker Gunship / Mightform Harmonizer / Monoist Circuit-Feeder /
> Extinguisher Battleship are corrected at their §round-19
> residue-table and §2.6 locations. Round 54 also extended the cron
> with a **per-entry residue check** (reads `docs/residue_worklist.json`)
> so this sub-class — a residue entry naming an Effect that actually
> exists — is now caught structurally, not by hand on the next
> refresh.

This section is the round-49 batch refresh covering rounds 35
through 48 (the round-34 headline section above was flagged stale
twice — rounds 47 and 48 — because its X-from-count narrative and
BLOCKED-RUST-EFFECT headline were frozen at round 34 while 13
substrate slices shipped on top of it). Methodology: a fresh
diff-walk of every `Merge feature/rust-*` / `feature/phase5-ce-bridge-*`
/ `feature/phase6-*` commit on `main` between `c62935d2` (round-35
HEAD) and `8e584628` (round-48 HEAD), cross-checked against the live
`rust/src/cards.rs::Effect` enum and `cross_engine._ta_dict_to_python_effect`
arm inventory measured directly off the worktree. Supersedes the
round-34 headline counts; the round-34 and round-19 sections are
kept verbatim below for cross-round narrative continuity.

### Headline inventory (measured off `8e584628`)

| Bucket | Round-34 | Round-48 (true) | Delta |
| --- | --- | --- | --- |
| Bridge-arm effect `kind ==` literals in `_ta_dict_to_python_effect` | 76+ | **106 distinct** | +30 |
| Rust `Effect::` enum variants (top-level) | (untracked) | **~104** | — |
| BLOCKED-RUST-EFFECT residue (truly no-Rust-arm asks) | ~21 cards / ~14 distinct asks | ~~**~15 distinct new-Rust-Effect asks** (round-51 corrected: was carried as ~17; Mechanozoa + Warmaker Gunship were never Rust-Effect-blocked)~~ **STALE — corrected round 54: the true honest count is ~13 distinct new-Rust-Effect asks / 13 distinct cards.** The round-51 "~15" was itself stale — Monoist Circuit-Feeder closed round 51 (`TwoSubjectPumpAndDebuffByArtifactCount`) and Extinguisher Battleship's effect-half closed round 52 (`DestroyTargetNoncreaturePermanent`+`DamageEachCreature`+`Sequence`); both were still listed in the residue tables. See the round-54 full programmatic re-walk section above for the reconciled per-entry worklist + `docs/residue_worklist.json`. | −4 over-count vs the carried ~17 (round-51 −2 + round-54 −2) |
| `_SAFE_KEYWORDS` (production-deck bridge filter) | 11 | **12** (+`reach`, round 45) | +1 |
| `_SAFE_TRIGGERS` triples | 3 (round-1 starter) | **15** | +12 |
| `SEARCH_LIMITATIONS.md` active entries | 28 | **27** (−1, round-37 supertypes-proxy close) | −1 |

### Round-52: staleness-sentinel block (the round-19 cron, implemented)

The round-19 cron proposal is now **implemented** rather than
re-validated for a fourth time.
`scripts/check_audit_coverage_staleness.py` derives the live
Rust-`Effect`-variant / bridge-`kind==`-arm / `_SAFE_TRIGGERS` /
`_SAFE_KEYWORDS` / `_SAFE_EFFECT_KEYS` inventory off the working tree
and diffs it against the machine-readable block below + the
auto-generated `RUST_EFFECT_COVERAGE.md` headline. It is wired into
`hooks/post-commit` as a main-only, never-blocking step (same
contract as the perf hook) and is runnable standalone / as a CI gate
(`python scripts/check_audit_coverage_staleness.py`, exit 1 on drift).

**On its first run the tool confirmed the headline table directly
above was ALREADY stale at `a1d4bcf7`** (round-51 HEAD): the
round-49-refresh prose froze at `8e584628` while rounds 49–51 shipped
substrate on top. The block below carries the *true current* counts
measured at `a1d4bcf7`; the round-48 prose column is left verbatim
for narrative continuity (per the doc's keep-verbatim convention) —
the block, not the prose, is the cron's source of truth from here on.
A refresh updates **this block** (and the prose if rewriting the
narrative); the cron then re-baselines automatically on the next
`main` merge.

<!-- STALENESS-SENTINEL:BEGIN -->
<!-- Machine-readable headline counts diffed by
     scripts/check_audit_coverage_staleness.py on every main commit.
     `key = value`, ints only, `#`/`<!--` lines ignored. Update these
     whenever the live inventory moves (a refresh edits this block);
     the cron reports drift until they match the working tree again.
     Measured at main f881e1cd (continuous-pipeline cycle 2 — 4
     Tier-A Effect-uncovered closes: Radiant Strike, Seedship
     Impact, Orbital Plunge, Depressurize). Counts MOVED
     +4/+4/0/0/0: rust_effect_variants 112->116
     (DestroyTargetArtifactOrTappedCreature, SeedshipImpactEffect,
     DealDamageToTargetCreatureWithExcessLanderRider,
     DepressurizeEffect); bridge_arms 114->118 (the four
     _ta_dict_to_python_effect kind arms). _SAFE_* UNCHANGED —
     Tier-A closes are Effect+bridge, not trigger/keyword
     allowlist moves. The 4 closes touched cards.rs/
     cross_engine.py -> cadence re-verify fired; the 7 still-
     genuinely-missing entries re-stamped
     verified_absent_at_commit=f881e1cd (the 4 shipped Effects
     are disjoint from all 7 residue Effect signatures —
     absence preserved, no close). Honest residue still 6
     distinct cards; Sothera-the-Supervoid flagged for the
     next residue re-walk cadence (genuinely_missing-shaped,
     2,108 decks, no planned substrate reaches it — NOT yet
     a worklist entry). Pool-parity 298/475 -> 302/475
     (62.7% -> 63.6%); PROBED 56 -> 60 (the 4 new genuine
     real-EoE Tier-A probes); Effect-uncovered Tier-A bucket
     drains 4 cards (31 -> 27). The full Instant/Sorcery of
     each stays loader-gated — no spell-card-bridge yet;
     Phase 1 is now ship-eligible, the dominant ~60k-deck
     Rust lever. -->
rust_effect_variants = 116
bridge_arms = 118
safe_triggers = 21
safe_keywords = 12
safe_effect_keys = 9
<!-- STALENESS-SENTINEL:END -->

**The BLOCKED-RUST-EFFECT headline did NOT move materially over
rounds 35–48 — and that is the central finding of this refresh.**
The round-34 residue's truly-no-Rust-arm asks (`Astelli Reclaimer`
MV-condition GY-return, `Command Bridge` sac-unless-tap, `Pain for
All` self-propagating damage, `Meltstrider's Resolve` Aura-shape
Fight, `Lightstall Inquisitor`, `Perigee Beckoner`, `Monoist
Circuit-Feeder`, `Dauntless Scrapbot`, `Faller's Faithful`, `Roving
Actuator` cast-copy half, `Famished Worldsire` composition, `Tractor
Beam` composition, `Pulsar Squadron Ace` Spacecraft sub-mode) were
each re-checked against the current `Effect` enum and **remain
unclosed** — none gained a matching Rust arm in rounds 35–48. The
~13–14 distinct-new-Rust-arm-ask figure is therefore the *true
current* count, not a stale carry-over: it genuinely did not shrink.

What rounds 35–48 actually shipped on the Rust lane was **not
residue closure** — it was **X-from-count matrix saturation**
(denominator-axis sweeps with 0–1 EoE consumers, shipped per the
round-27/31 round-trip-surface-coverage rule) plus one new
`CreateTokenEachPlayer` substrate. These add Rust surface and bridge
arms but do not subtract residue cards, because the cards they would
unblock are either (a) review-gated (Roaring Furnace = Room/door
subsystem; Cerebral Download = cast-spell driver) or (b)
token-registration-loader-gated, not Rust-blocked. The campaign's
center of gravity over rounds 35–48 moved from "drain the residue"
to "complete the primitive matrix"; the audit's prior framing
(residue is a shrinking queue) was the source of the staleness flags.

> **STALE — corrected round 54.** The round-48 paragraph immediately
> above asserts the round-34 residue list "remain unclosed — none
> gained a matching Rust arm" and explicitly names `Monoist
> Circuit-Feeder`, `Pulsar Squadron Ace`, `Famished Worldsire`, etc.
> Round 51 closed **Monoist Circuit-Feeder** (`Effect::TwoSubjectPumpAndDebuffByArtifactCount`
> + bridge + real-EoE byte-equal probe) and round 52 closed the
> **Extinguisher Battleship** effect-half (`Effect::DestroyTargetNoncreaturePermanent`
> + `Effect::DamageEachCreature` + `Sequence`, all bridge-wired). The
> "none gained a matching Rust arm" claim is therefore stale for those
> two entries (Mechanozoa/Warmaker/Mightform were the three already
> flagged before round 54; Monoist + Extinguisher are the **two
> additional stale entries the round-54 full programmatic re-walk
> surfaced**). See the round-54 re-walk section directly below for the
> reconciled per-entry worklist + the true honest headline count; the
> round-48 prose is kept verbatim per the keep-verbatim convention.

### Round-54: full programmatic BLOCKED-RUST-EFFECT residue re-walk + per-entry cron extension

The round-52 cron (`scripts/check_audit_coverage_staleness.py`)
structurally caught **count** drift (Rust-variant / bridge-arm /
`_SAFE_*` totals vs the STALENESS-SENTINEL block) but, by
construction, **could not catch a residue entry that names an Effect
which actually exists** — it diffs inventory sizes, not per-entry
residue claims. Rounds 51 and 53 hand-found 3 such confirmed-stale
entries (Mechanozoa r51, Warmaker Gunship r51, Mightform Harmonizer
r53). That is a *systemic* sub-class, and the audit was internally
self-contradictory because of it (e.g. round-19 §2.6 line ~80 records
Mightform's round-31 closure while lines ~586/598/984/1048 still say
"no Rust arm").

Round 54 did the systematic fix: a **full programmatic re-walk** of
every entry currently classed BLOCKED-RUST-EFFECT in this doc,
resolving each plan-invented/audit-named missing Effect against the
*live* `rust/src/cards.rs::Effect` enum (via
`measure_effect_coverage.collect_rust_effect_variants` — the same
parser the cron + coverage doc use) **and** the live
`_ta_dict_to_python_effect` bridge-arm inventory, with a
plan-name→real-variant alias-resolution pass (e.g. the plan's
`DoubleTargetPowerUntilEOT` resolves to the shipped
`DoubleTargetCreaturesPowerUEOT`; `TwoMobileSubjects` →
`TwoSubjectPumpAndDebuffByArtifactCount`;
`DestroyNoncreatureThenAOEDamage` → `DestroyTargetNoncreaturePermanent`).
The canonical machine-readable worklist this produced is
`docs/residue_worklist.json`; the cron now reads it and FAILs if any
`genuinely_missing` entry's claimed Effect actually resolves to a
live + bridged variant (the per-entry staleness arm — Deliverable B).

#### Re-walk summary table (entry → claimed-missing-Effect → live-status → new-classification)

| Card | Claimed-missing Effect (plan name) | Live status | New classification |
| --- | --- | --- | --- |
| **Mechanozoa** | `TapTargetAndPutStunCounter` | **shipped-as `TapTargetOpponentPermanentAndStunIt` (round 30) + bridged** | BLOCKED-FILTER (warp_cost) — *corrected r51, re-confirmed r54* |
| **Warmaker Gunship** | `DealDamageToAnyTargetEqualToArtifactCount` | **shipped-as `DealDamageToOpponentCreatureByArtifactCount` (round 32) + bridged** | BLOCKED-Station-subsystem — *corrected r51, re-confirmed r54* |
| **Mightform Harmonizer** | `DoubleTargetPowerUntilEOT` | **shipped-as `DoubleTargetCreaturesPowerUEOT` (round 31) + bridged** (r53 fixed a latent counter bug + added a real probe) | BLOCKED-FILTER/substrate (landfall Subject(IsLand) + warp) — *headline corrected r53; **§round-19/§2.6 locations reconciled r54*** |
| **Monoist Circuit-Feeder** | `TwoMobileSubjects` | **shipped-as `TwoSubjectPumpAndDebuffByArtifactCount` (round 51) + bridged + real-EoE byte-equal probe** | PROBED/CLOSED — **🆕 NEWLY found stale by the round-54 re-walk** (beyond the known 3) |
| **Extinguisher Battleship** | `DestroyNoncreatureThenAOEDamage` | **effect-half shipped round 52** (`DestroyTargetNoncreaturePermanent` + `DamageEachCreature` + `Sequence`, all bridge-wired) | BLOCKED-Station-subsystem (effect closed; card Station/Spacecraft loader-gated) — **🆕 NEWLY found stale by the round-54 re-walk** (beyond the known 3) |
| Lightstall Inquisitor (cast-from-exile) | `CastFromExileWithCostHike` | genuinely-missing | BLOCKED-RUST-EFFECT (stays) |
| Lightstall Inquisitor (each-opp-exiles) | `EachOpponentExilesFromHand` | genuinely-missing | BLOCKED-RUST-EFFECT (stays) |
| Command Bridge | `SacUnlessYouTap` | genuinely-missing | BLOCKED-RUST-EFFECT (stays) |
| Astelli Reclaimer | `ReturnPermanentCardWithMVXorLessFromGY` | genuinely-missing | BLOCKED-RUST-EFFECT (stays) |
| Perigee Beckoner | `PumpAndGrantDiesReturnTrigger` | genuinely-missing | BLOCKED-RUST-EFFECT (stays) |
| Pain for All | `EnchantedDealsDamageThenPropagate` | genuinely-missing | BLOCKED-RUST-EFFECT (stays) |
| Dauntless Scrapbot | `ExileEachOpponentGYAndCreateToken` | genuinely-missing | BLOCKED-RUST-EFFECT (stays) |
| Faller's Faithful | `DestroyTargetThenDrawIfUndamaged` | genuinely-missing | BLOCKED-RUST-EFFECT (stays) |
| Meltstrider's Resolve | `EnchantedCreatureFightsTarget` (Aura) | genuinely-missing (bare `Fight` shipped; Aura-shape not) | BLOCKED-RUST-EFFECT (stays) |
| Roving Actuator | `ExileGraveyardCastFromExile` (cast-copy half) | genuinely-missing (Void cond shipped; cast-copy half not) | BLOCKED-RUST-EFFECT (stays) |
| Famished Worldsire | `LookXAndPutLandsTapped` | genuinely-missing (X-by-power plumbing exists; composition not) | BLOCKED-RUST-EFFECT (stays) |
| Tractor Beam | `TapEnchantedYouControlAndDontUntap` | genuinely-missing (`TapEnchantedPermanent` shipped; control-swap+no-untap not) | BLOCKED-RUST-EFFECT (stays) |
| Pulsar Squadron Ace | `ChoiceTrigger` Spacecraft sub-mode | genuinely-missing (substrate `LookAtTopNRevealOrCounter` exists + bridged; the Spacecraft-reveal sub-mode param is a real missing arm — partial) | BLOCKED-RUST-EFFECT (stays, substrate-present partial) |
| Seedship Agrarian | `LandfallComplexEffectSeedship` (§2.6 tail) | genuinely-missing (distinct from Remnant-Elemental's compose-existing case) | BLOCKED-RUST-EFFECT (stays) |

#### True honest BLOCKED-RUST-EFFECT headline count

| | OLD (carried) | CORRECTED (round-54 re-walk) |
| --- | --- | --- |
| Carried BLOCKED-RUST-EFFECT residue names | ~17 (round-34 / round-19 / §2.6) | — |
| Round-51 correction (Mechanozoa + Warmaker out — Effect already shipped) | → ~15 | (already in the round-51 note) |
| **Round-54 re-walk: − Monoist Circuit-Feeder (closed r51) − Extinguisher Battleship effect-half (closed r52)** | | **→ ~13 distinct new-Rust-Effect asks / 13 distinct cards** |

The **true honest BLOCKED-RUST-EFFECT residue is ~13 distinct
new-Rust-Effect asks** (13 distinct cards; Lightstall Inquisitor
carries 2 of the arms): Lightstall Inquisitor, Command Bridge, Astelli
Reclaimer, Perigee Beckoner, Pain for All, Dauntless Scrapbot,
Faller's Faithful, Meltstrider's Resolve (Aura-shape Fight), Roving
Actuator (cast-copy half), Famished Worldsire (composition), Tractor
Beam (composition), Pulsar Squadron Ace (Spacecraft sub-mode),
Seedship Agrarian (landfall composer). The headline was **provably
inflated**: the round-52 "~15" was itself stale (Monoist closed r51,
Extinguisher effect closed r52) — the round-52 count-only cron grew
the Rust-variant total when those landed but, having no per-entry
residue check, never flagged that the residue *tables* still listed
them. Deliverable B closes that gap structurally.

The re-walk found **0 false-flag entries** the other direction: every
`genuinely_missing` row was re-verified to NOT resolve to any live
Rust variant — the remaining ~13 are genuinely Rust-blocked, not more
hidden stale carry-overs. This is an accurate worklist, not a
count-minimization.

> **⚠️ SUPERSEDED — round-54 post-merge orchestrator fold (corrected
> count: ~11, not ~13).** The "~13 / 0 false-flags" claim above was
> itself slightly over-stated. The re-walk **deferred two entries**
> (Famished Worldsire, Pulsar Squadron Ace) to "fold N2's live-verify
> at rebase" — a cross-agent fold no agent performed (N2 was told not
> to edit this file; N3 merged before N2). The orchestrator performed
> the fold (code-verified):
> - **Famished Worldsire → CLOSED** — N2 r54 shipped
>   `Effect::FamishedWorldsireLookTopXByPowerPutLandsTapped` + bridge
>   arm (`cross_engine.py:7870`) + genuine real-EoE probe.
> - **Pulsar Squadron Ace → STALE, reclassified out** — its Effect
>   *is* shipped: `Effect::LookAtTopNRevealOrCounter`
>   (`cards.rs:3302`, doc-comment names it) + `"spacecraft"` filter
>   (= the alleged "sub-mode") + bridge arm (`cross_engine.py:3467`),
>   round-28/29. **6th confirmed-stale entry.** It was NOT caught by
>   the re-walk's "0 false-flags" pass NOR by Deliverable B's
>   per-entry cron, because the plan-name
>   `ChoiceTriggerSpacecraftRevealOrCounter` does not lexically
>   alias-resolve to `LookAtTopNRevealOrCounter` — a **per-entry-cron
>   resolver gap** (round-55 hardening: the resolver must not depend
>   on lexical alias similarity; e.g. require a
>   `verified_absent_at_commit` SHA the cron re-checks). Pulsar's
>   only residual is verify-only (no genuine real-EoE Pulsar
>   cross-engine probe yet), **not** a new Rust Effect.
>
> **Corrected honest residue: ~11 distinct genuinely-Rust-blocked
> cards** (12 `genuinely_missing` rows, 8 `closed`). The
> machine-readable `docs/residue_worklist.json` is the source of
> truth and has been folded to match; the cron enforces it. The
> scattered prose "~13" mentions elsewhere in this doc are superseded
> by this note + the JSON (not individually re-edited, to avoid
> multi-location transcription error — same rationale the doc uses
> for its other staleness pointers).

Per-location reconciliation done this round: the Mightform Harmonizer
self-contradiction (round-19 §2.6 closure note vs the "no Rust arm"
rows at the round-19 residue table / §2.6 / the recurring-arm table)
is resolved in place below with `~~strike~~ **STALE — corrected round
54.**` markers mirroring the existing round-51/53 format; Monoist
Circuit-Feeder and Extinguisher Battleship get the same treatment at
their round-34-residue / round-19-residue / §2.6 locations.

### X-from-count primitive matrix — current 6-substrate × 6-denominator state

The X-from-count family is **6 apply-substrates × 6 count-denominators**.
Live state measured off the `Effect` enum on `8e584628` (round-48
HEAD; this batch section is bounded at round 48 by design). **Forward
note:** round-49 N2 (`feature/rust-gain-life-self-by-life-total-r49`,
merged `e0f4729d`) added `GainLifeEqualToYourLifeTotal`, moving the
`gain_life_self` row from 1/6 → **2/6** (artifact-count r45 +
life-total r49) — recorded here so the next refresh need not
re-discover it, but the table below stays at its r48 snapshot.

| Apply substrate \ Denominator | artifact_count | hand_size | lands_controlled | creatures_you_control | graveyard_size | life_total | Row |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **damage-to-opp-creature** | ✓ r32 | ✓ r35 | ✓ r36 | ✓ r37 | ✓ r46 | ✓ r47 | **6/6 SATURATED (as of r47)** |
| **each_opponent_loses_life** | ✓ r44 | — | — | — | — | ✓ r48 | **2/6 (as of r48)** |
| **surveil** | ✓ r34 | — | — | — | — | — | 1/6 |
| **mill** (mill_target_player) | — | — | — | — | — | ✓ r42 | 1/6 |
| **gain_life_self** | ✓ r45 | — | — | — | — | — | 1/6 |
| **counters_on_self** | ✓ r33* | — | — | — | — | — | ~1/6 |

\* `counters_on_self` is `Effect::PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact`
(round 33) — a "per other creature OR artifact" denominator, the
artifact-count-adjacent cell; the literal `artifact_count` column is
the closest single-axis label.

Backing Rust variants (one per ✓):
`DealDamageToOpponentCreatureBy{ArtifactCount,CardsInHand,LandsControlled,CreaturesYouControl,CardsInGraveyard,LifeTotal}`
(damage row, complete); `EachOpponentLosesLifeEqualToArtifactCount`
(r44) + `EachOpponentLosesLifeEqualToYourLifeTotal` (r48);
`SurveilXEqualToArtifactCount` (r34);
`MillTargetPlayerEqualToYourLifeTotal` (r42);
`GainLifeEqualToArtifactCount` (r45);
`PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact` (r33).

**Narrative correction vs round-34:** the round-34 text described
the matrix as "well-established, adding cells is mechanical" but
froze the substrate list at 6 substrates / damage-row-only
denominators. The true round-48 state is that the **damage-to-opp-creature
row is fully saturated** (all 6 denominators landed, rounds
32→47, one denominator per ~1-round slice on a strict bit-for-bit
sister-shape cadence) while the other five substrates remain
sparsely populated (each 1–2 denominator cells). The matrix's
remaining headroom is **the 28 empty cells** (6×6 = 36 total minus
6 saturated damage cells minus 2 each-opp-loses-life minus the four
single ✓ cells), each ~1 round of Rust work at the established
cadence; the damage row's saturation is the proof-of-concept that
the plumbing generalizes bidirectionally across BOTH axes.

### BLOCKED-RUST-EFFECT closures/changes, round 35→48 (per-round diff walk)

| Round | Merge | Rust substrate shipped | EoE consumer | Residue effect |
| --- | --- | --- | --- | --- |
| 35 | `c62935d2` | `DealDamageToOpponentCreatureByCardsInHand` | Roaring Furnace (Room — review-gated) | 0 (Room-gated, not residue) |
| 36 | `69968b14` | `DealDamageToOpponentCreatureByLandsControlled` | 0 EoE | 0 (round-trip-surface) |
| 36 | `0d459dd4` | Rust `Sequence(Surveil,DrawCards)` PendingDecision fix | Cerebral Download (xfail→pass) | bug fix, not residue |
| 37 | `7b302272` | `DealDamageToOpponentCreatureByCreaturesYouControl` | 0 EoE | 0 (round-trip-surface) |
| 37 | `22799c77` | Rust `IfYouDoChoice` PendingDecision sister fix | none (preventative) | bug fix, not residue |
| 37 | `39ba1fcc` | `SearchLibraryForBasicLandTapped` supertypes migration | (regression-pin) | SEARCH_LIMITATIONS 28→27 |
| 42 | `d2252337` | `MillTargetPlayerEqualToYourLifeTotal` | 0 EoE | 0 (round-trip-surface) |
| 43 | `76fc9cb2` | `CreateTokenEachPlayer` | DIES+CreateToken cluster (loader-gated) | reclassified, not residue −1 |
| 43 | `c41bf32d` | CE5 Rust drain mirror (Thawbringer) | harness fix | bench cluster 7→0 |
| 44 | `995c8ed0` | `EachOpponentLosesLifeEqualToArtifactCount` | 0 EoE | 0 (round-trip-surface) |
| 45 | `f645bada` | `GainLifeEqualToArtifactCount` | 0 EoE | 0 (round-trip-surface) |
| 46 | `3e650207` | `DealDamageToOpponentCreatureByCardsInGraveyard` | 0 EoE | 0 (completes damage row to 5/6) |
| 47 | `1589a42d` | `DealDamageToOpponentCreatureByLifeTotal` | 0 EoE | **0 — damage row 6/6 SATURATED** |
| 48 | `ca9013e8` | `EachOpponentLosesLifeEqualToYourLifeTotal` | 0 EoE | 0 (each-opp-loses-life → 2/6) |

Net: **13 Rust/harness slices, 0 residue-card closures.** Every
substrate slice was either a matrix-denominator sweep (0 EoE
consumers, shipped for round-trip surface coverage) or a
harness/bug fix. The residue stays at the round-34 figure because
the residue cards need *bespoke* new Rust shapes (self-propagating
damage, MV-condition GY-return, Aura-shape Fight, two-mobile-subject,
cast-from-exile-with-cost-hike) that no denominator sweep touches.

### Bridge-arm coverage changes (Phase 6 production-deck filter), round 35→48

The `cross_engine` effect-arm count grew 76→**106** distinct
`kind ==` literals (the round-34 "76+" was already an undercount;
the +30 reflects both genuinely-new arms and arms the round-34 prose
elided). On the production-deck **bridge-filter** side
(`parity/trajectory.py`), the round-35→48 extensions:

- **`_SAFE_KEYWORDS` 11→12**: `reach` added round 45 (`3b7e98ea`) —
  both engines model reach identically as a blocker-side
  flying-block gate-opener (Python `combat.can_block:70-72`; Rust
  `state_ops_combat::declare_blocker:738-744`). Admitted Remnant
  Elemental; 2/50 archetypes picked up ≥1 admit.
- **`_SAFE_TRIGGERS` 3→15** across rounds 36–48: round-36 landfall
  predicate sentinel + `gain_life` (Eumidian Terrabotanist, FIRST
  real-EoE production-deck admit); round-37 DDDD landfall+`pump_self_until_eot`
  (Icecave Crasher); round-42 ENTERS/DIES+`surveil` (Thawbringer);
  round-43 ATTACKS+`surveil`; round-44 ATTACKS+`draw_cards`/`gain_life`;
  round-47 DIES+`gain_life`/`draw_cards`; round-48 landfall+`mill`
  (Icetill Explorer) + ENTERS+`source_is_self`+`mill`. Net safe
  set: ENTERS×{draw_cards,gain_life,scry_n,surveil,mill} +
  DIES×{draw_cards,gain_life,surveil} + ATTACKS×{draw_cards,gain_life,surveil}
  + landfall×{gain_life,pump_self,draw_cards,mill}.
- **`_SAFE_EFFECT_KEYS`**: now 6 arms (`draw_cards`, `gain_life`,
  `scry_n`, `pump_self_until_eot`, `surveil`, `mill`) each with a
  strict allowed-payload-key whitelist gating silent rider drops.

Real-EoE creatures admitted to the production-deck loader by these
extensions: **Eumidian Terrabotanist** (r36), **Icecave Crasher**
(r37), **Thawbringer** / **Wary Watchdog** / **Wurmwall Sweeper**
(r42), **Remnant Elemental** (r45 reach), **Icetill Explorer**
(r48). The bench-visible conversion these produced is tracked in
`docs/bench_trajectory_parity_smoke.md` (round-48: +3
FAIL_TIMEOUT→PASS on arch 10/11/12, 0-divergence held across 90
games on the `landfall+mill` path's real-game first exposure).

### Bridge-correctness discipline held (round 42 → 48)

Every Phase 6 filter-extension slice since round 42 honored the §2
silent-mistranslation decline list. Confirmed-declined classes that
were NOT re-admitted over rounds 42–48: `activated_abilities`
(Seedship Broodtender stays dropped, round 48), `static_abilities`,
`warp_cost`, `ward_cost` + `dynamic_pt_formula` (Harmonious
Grovestrider stays dropped, round 39), `BECOMES_TAPPED` event,
`CreateToken` (token-registration-loader-gated), target-pick
effects (no targeting-agent in the loader), bespoke Effect classes
(Tannuk / Famished Worldsire / Terrapact Intimidator /
Possibility Technician). Round-49 N3's Part-A scan of the
timeout-dominant Sweep-A archetypes 13/14/15 found **zero remaining
bridge-safe creatures** — every filtered-out creature on those
three decks is blocked solely by a §2-declined class
(`PumpTargetCreatureUntilEOT` target-pick + `granted_keywords`
rider; `CreateToken`; `BECOMES_TAPPED`; `static_abilities`; bespoke
Effect; `dynamic_pt_formula`+`ward_cost`; `cost_reductions`),
confirming round-48's forecast that the cheap vanilla-creature
filter-admit headroom on the Sweep-A grid is exhausted and the
next bulk-conversion lever is the CreateToken / target-pick
*substrate* lane (round-49 N1 owns the token-registration
substrate).

### Recommendation (round-35→48 refresh)

1. **The X-from-count damage row is done (6/6).** No more
   damage-denominator slices remain; the next denominator sweeps
   should walk the OTHER five substrate rows
   (each_opponent_loses_life is 2/6; surveil / mill / gain_life_self
   / counters_on_self each ~1/6). 28 empty matrix cells, ~1 round
   each at the established sister-shape cadence.
2. **The ~13–14-distinct-new-Rust-arm residue is genuinely stuck**
   behind bespoke shapes, not denominator sweeps. Closing it needs
   targeted bespoke-substrate slices (self-propagating damage,
   MV-condition GY-return, Aura-shape Fight) OR the review-gated
   branches (Room/door, cast-spell driver, dies-event harness,
   etb-subject-substrate, token-registration substrate).
3. **The filter-admit lever's cheap headroom is exhausted on the
   Sweep-A grid** (round-49 N3 confirmed arch 13/14/15 have zero
   remaining bridge-safe creatures). Future filter admits need the
   token-registration / target-pick substrate; the campaign's
   bulk-conversion center of gravity is back on the Rust-substrate
   lane.
4. **The round-19 cron proposal is now twice-validated** (rounds
   34 and 49 both found multi-round shadow-substrate the audit text
   didn't track; the audit went stale and was flagged twice). A
   commit-hook that diffs `Effect`-variant + bridge-arm + `_SAFE_*`
   counts against the audit's last-recorded headline on every
   `main` merge would have caught the round-47/48 staleness
   automatically.

---

## Historical: round-19 refresh narrative (as-of `39d01c02`, 2026-05-14)

Kept verbatim for cross-round reference; the round-34 headline
section above supersedes the counts.



| Bucket | Count |
| --- | --- |
| **Total EoE printings with `enters`-event triggers** | **93** |
| Cross-engine ETB probe tests on main (`test_cross_engine_real_eoe_*` + `test_cross_engine_synthetic_etb_*`) | **80** |
| - Real-EoE probes (`test_cross_engine_real_eoe_*`) | 51 |
| - Synthetic ETB probes (`test_cross_engine_synthetic_etb_*`) | 29 |
| - Cross-controller routing probes (subset of the above, synthetic) | 21 |
| - Divergence pins (subset of real-EoE) | 2 (Pinnacle Kill-Ship empty-bf, Susurian Dirgecraft token-first) |
| Distinct real-EoE printings probed on main | **48** |
| Bridge-side effect arms wired in `_ta_dict_to_python_effect` | **40** |
| Cross-controller I-fix matrix coverage | 21 effect-arm routings (create_token, return-from-gy-to-hand, return-from-gy-to-battlefield, damage_any_target, surveil, deal_damage_to_opponent_creature, mill, each_opponent_discards, mill_target_player, create_robot_artifact_creature_token, surveil-mill-path, exile_target_creature_until_source_leaves, exile_opponents_nonland_permanent_until_leaves, destroy_target, exile_target, owner_puts_target_on_top_or_bottom, return_to_hand, each_opponent_sacrifices_creature, deal_damage, tap_target, discard_card) |

### Distinct real-EoE printings probed on main (48 total)

`alpharael_dreaming_acolyte`, `all_fates_stalker`,
`atmospheric_greenhouse`, `banishing_light`,
`bioengineered_future`, `biomechan_engineer`, `biotech_specialist`,
`blooming_stinger`, `cryogen_relic` (ETB half),
`debris_field_crusher`, `drix_fatemaker`, `dubious_delicacy`,
`eumidian_terrabotanist`, `fell_gravship`, `galactic_wayfarer`,
`germinating_wurm`, `glacier_godmaw`, `haliya_ascendant_cadet`,
`haliya_guided_by_light`, `hardlight_containment`,
`honored_knight_captain`, `interceptor_mechan`, `kav_landseeker`,
`knight_luminary`, `mechan_assembler`, `melded_moxite`,
`mouth_of_the_storm`, `nebula_dragon`, `nova_hellkite`,
`pinnacle_kill_ship`, `quantum_riddler`, `rayblade_trooper`,
`rescue_skiff`, `seam_rip`, `seedship_broodtender`,
`sinister_cryologist`, `starbreach_whale`, `susurian_dirgecraft`,
`tannuk_memorial_ensign`, `thawbringer` (ETB half),
`uthros_scanship`, `virus_beetle`, `wedgelight_rammer`,
`weftstalker_ardent`, `wurmwall_sweeper`. (+14 vs round-10 refresh.)

### Bridge effect-arms shipped in `_ta_dict_to_python_effect` (40 total)

In source order in `src/mtg_bot/parity/cross_engine.py`. **Bold**
marks arms that landed since the round-10 refresh (`ebb5c6ec` →
`39d01c02`):

`draw_cards`, `gain_life`, `damage_each_opponent`, `deal_damage`,
`deal_damage_any_target`, `surveil`, `discard_self`,
`each_opponent_discards`, `deal_damage_to_opponent_creature`,
`mill`, `pump_target_creature_until_eot`,
**`set_base_pt_until_eot`** (round 18),
**`fight_target_creature_with_target_creature`** (`feature/rust-fight-effect`),
`put_plus_one_counter_on_creature_you_control`,
`return_creature_from_your_graveyard_to_hand`,
`return_artifact_or_creature_from_your_graveyard_to_hand`,
`return_creature_or_spacecraft_from_your_graveyard_to_hand`,
**`return_enchantment_or_creature_from_your_graveyard_to_hand`**,
`sequence`, `if_you_do`,
`pump_creatures_opponents_control_until_eot`,
**`pump_creatures_opponents_control_until_caster_next_turn`**,
`each_opponent_sacrifices_creature`, `each_opponent_mills_cards`,
`put_plus_one_counter_on_each_creature_you_control`,
`return_creature_from_your_graveyard_to_battlefield`,
**`return_enchantment_or_creature_from_your_graveyard_to_battlefield`**,
`create_token`, `mill_target_player`,
`exile_target_creature_until_source_leaves`, `discard_card`,
`tap_target`, `destroy_target`, `exile_target`,
`exile_opponents_nonland_permanent_until_leaves`,
**`exile_opponents_nonland_permanent_with_max_mv_until_leaves`**,
**`grant_keywords_to_target_creature_until_eot`**, `return_to_hand`,
`owner_puts_target_artifact_or_creature_on_top_or_bottom_of_library`.

---

## ROUND-19 BLOCKED-RUST-EFFECT staleness re-audit (headline finding)

Following round-18's SetBasePT discovery (Rust substrate had
already landed; only the bridge arm was missing — agent II shipped
the bridge in 1 commit), this refresh walks the §2.6
BLOCKED-RUST-EFFECT 42-card inventory item-by-item against the
current `rust/src/cards.rs` Effect enum to find more arms whose
Rust substrate has silently landed since the audit was written.

### Headline finding

**4 §2.6 entries (covering ~7 cards) are
ALREADY-SUBSTRATED-ON-RUST and should be reclassified to either
PROBED or BLOCKED-BRIDGE-ARM.** Each cell could ship in 1-2 hours
of bridge-arm work rather than the 1-2 weeks of new Rust the
audit's §2.6 categorization implied.

| §2.6 entry | Rust substrate | Status change |
| --- | --- | --- |
| `SetBasePTUntilEOT` (Genemorph Imago — 1 card) | `Effect::SetBasePTUntilEOT` at `cards.rs:1851` | **SHIPPED** in round 18 (`feature/bridge-set-base-pt-until-eot`); has 1 synthetic ETB cross-engine probe + 7 translator pins + 5 Rust regression pins. **Move to PROBED** (synthetic ETB only — Genemorph-Imago landfall variant + conditional-threshold variant deferred per merge-commit notes; counts as bridge-arm-only follow-up). |
| `Fight` bare bilateral form (Meltstrider's Resolve — 1 card) | `Effect::FightTargetCreatureWithTargetCreature` at `cards.rs:842` | **SHIPPED** in `feature/rust-fight-effect`; bridge wired + 9 synthetic regression pins. **Move bare-form to PROBED**; Aura-shape (needs new `Effect::EnchantedCreatureFightsTarget` per SEARCH_LIMITATIONS.md) stays BLOCKED-RUST-EFFECT. |
| `OptionalDiscardThenDraw` / Melded Moxite shape (1 card) | `Effect::IfYouDo` at `cards.rs:1646` + `Effect::DiscardSelf` at `cards.rs:469` | **SHIPPED** — Melded Moxite has a real-EoE probe on main: `test_cross_engine_real_eoe_melded_moxite_etb_if_you_do_discard_draw_parity`. **Move to PROBED.** Audit double-counted under §2.4 + §2.6; only §2.4 was correct. |
| `AttachToTargetCreatureYouControl` / `EquipToTargetCreatureYouControl` (Auxiliary Boosters, Illvoi Light Jammer, Meltstrider's Gear, Squire's Lightblade — 4 cards) | `Effect::AttachToTargetCreatureYouControl` at `cards.rs:1425`; `Effect::EquipToTargetCreatureYouControl` at `cards.rs:1452` (both with parsers at `cards.rs:3677`/`3680`) | **MOVE TO BLOCKED-BRIDGE-ARM.** Both Rust unit-variant arms exist with parsers; bridge `_ta_dict_to_python_effect` does NOT wire `attach_to_target_creature_you_control` or `equip_to_target_creature_you_control`. Two ~30-LOC bridge-arm slices unblock all 4 cards. |

### Other §2.6 entries with partial Rust substrate

These are not as cleanly reclassifiable, but the audit's
"true new Rust code" framing overstates the work:

| §2.6 entry | Rust substrate | Bridge gap |
| --- | --- | --- |
| `OptionalSacrificeArtifactForCounterAndDraw` (Selfcraft Mechan — 1 card) | `Effect::OptionalSacArtifactForEffect { inner_effect }` at `cards.rs:1371` (parser at `cards.rs:3668`) | Wrapper substrated; inner counter+draw composes via existing `Effect::Sequence` over `PutPlusOneCounterOnSelf` + `DrawCards` (both already substrated + bridge-wired). **One bridge arm slice for the wrapper** unblocks Selfcraft Mechan. Move to BLOCKED-BRIDGE-ARM. |
| `ChoiceTrigger` / Pulsar Squadron Ace (1 card) | `Effect::LookAtTopNRevealOrCounter` at `cards.rs:2152` (parser at `cards.rs:4272`) | Rust arm exists with parser. Pulsar Squadron Ace's specific revelation-of-Spacecraft variant likely needs a sub-mode parameter, but the substrate dispatch + reveal-or-counter shape is already there. **Move to BLOCKED-BRIDGE-ARM** with sub-mode follow-up risk. |
| `OptionalCreateTwoTokensOrSelfPump` (Terrapact Intimidator — 1 card) | `Effect::MayDo { effect, prompt }` at `cards.rs:1579` (parser at `cards.rs:3742`) | Wrapper substrated; "create two tokens" sub-mode needs `CreateToken` parameterization for the specific token type. Bridge missing both `may_do` arm AND the create-token parameterization. **Halfway-substrated** — one bridge slice for `may_do` plus per-token parameterization. |
| `LandfallWithComplexEffect` (Glacier Godmaw, Mightform Harmonizer, Genemorph Imago, Seedship Agrarian, Remnant Elemental — 5 cards) | Predicate substrate (Subject family) ALREADY SHIPPED via `feature/etb-subject-substrate`; **Glacier Godmaw landfall lander-token PROBED on main** (`test_cross_engine_real_eoe_glacier_godmaw_etb_create_lander_artifact_token_leviathan_carrier_parity`) | Per-card effect arms differ: ~~Mightform Harmonizer needs new `Effect::DoubleTargetPowerUntilEOT` (true new Rust)~~ **STALE — corrected round 54: Mightform Harmonizer's effect arm shipped round 31 as `Effect::DoubleTargetCreaturesPowerUEOT` + bridged (r53 bug-fixed + probed); the `DoubleTargetPowerUntilEOT` name was plan-invented and conflated the real shipped variant. NOT true new Rust — Mightform is gated only by the landfall `Subject(IsLand)` predicate + `warp_cost`.** Genemorph Imago landfall = compose existing `SetBasePTUntilEOT` (round 18) with landfall predicate (bridge follow-up). Remnant Elemental = compose existing `PutPlusOneCounterOnSelf` + Subject predicate (bridge composition). Seedship Agrarian needs a new arm. **The only genuine new-Rust-arm ask in this bucket is Seedship Agrarian; the other 4 are predicate/bridge-composition.** |
| `Roving Actuator` void-style exile-then-cast-copy | `Effect::ConditionalIfVoid { then_effect, else_effect }` at `cards.rs:2045` (parser at `cards.rs:4203`) | Void condition substrated. Exile-then-cast-copy still needs new Rust. **Partial unblock** (the trigger shell can lift; the cast-copy effect is the residual gap). |
| `Famished Worldsire` look-X-and-put-lands-tapped | `Effect::DealDamageEqualToSourcePowerAnyTarget` at `cards.rs:1269` shows the X-from-source-power pattern exists; `Effect::SearchLibraryForBasicLandTapped { count }` at `cards.rs:217` exists for the lands-tapped half | Specific "look-X-then-put-lands-tapped" composition needs new Rust, but the X-plumbing pattern is unblocked. **Partial unblock.** |
| `Tractor Beam` TapEnchantedYouControlAndDontUntap | `Effect::TapEnchantedPermanent` at `cards.rs:1476` (parser at `cards.rs:3686`) | Tap-enchanted substrated. Control-swap + don't-untap composition still needs new Rust. **Partial unblock.** |
| `DestroyNoncreatureThenAOEDamage` (Extinguisher Battleship — 1 card) | `Effect::DestroyTargetNonlandPermanent` at `cards.rs:635`; `Effect::DamageEachCreature` at `cards.rs:145`; `Effect::Sequence` at `cards.rs:872` | All component arms substrated! Bridge has `sequence` already; missing `destroy_target_nonland_permanent` and `damage_each_creature` arms. **Could move to BLOCKED-BRIDGE-ARM** with two bridge-arm slices + one composition probe. (Conservatively kept in BLOCKED-RUST-EFFECT for now since the audit didn't enumerate the component arms; flagging for follow-up.) |
| `CreateLanderToken` parameterized family (13 cards in §2.6) | `Effect::CreateToken { count, token_printing_id }` at `cards.rs:154`; `Effect::CreateTokenCopyOfTargetCreatureYouControl` at `cards.rs:1355` | Create-token base SHIPPED + multiple lander-token printings already PROBED via per-card slices (Galactic Wayfarer, Bioengineered Future, Biomechan Engineer, Biotech Specialist, Glacier Godmaw, plus the Honored Knight-Captain / Knight Luminary / Wedgelight Rammer subset from §2.3). The remaining BLOCKED set in this row is much smaller than 13 — closer to **5 cards** for the unprobed token shapes (Auxiliary Boosters with attach, Dauntless Scrapbot with exile-each-gy, Infinite Guideline Station, Sunstar Expansionist, Terrapact Intimidator with may_do). |

### Truly BLOCKED-RUST-EFFECT residue (confirmed no Rust arm)

| §2.6 entry | Status |
| --- | --- |
| `TapTargetAndPutStunCounter` (Mechanozoa, Cryogen Relic activated half — 2 cards) | ~~No StunCounter substrate in Rust. Confirmed BLOCKED-RUST-EFFECT.~~ **STALE — corrected round 51.** Round-30 shipped `Effect::TapTargetOpponentPermanentAndStunIt` (`cards.rs:2468`) + bridge arm (`cross_engine.py:3168` → `tap.py:217`). **Mechanozoa is NOT BLOCKED-RUST-EFFECT** — its exact ETB is fully substrated + bridged on both engines (round-51 N3 real-printing cross-engine probe is byte-equal). Mechanozoa's only residual blocker is `warp_cost` gating the production-deck loader admit (§2-declined cost-mechanic) → **BLOCKED-FILTER (warp_cost)**, not an Effect gap. (Cryogen Relic's *activated-half* stun shape `put_stun_counter_on_tapped_creature` also shipped round-30 + bridged; its remaining gap is the activated-ability cross-engine harness, not the Effect.) |
| `DoubleTargetPowerUntilEOT` (Mightform Harmonizer — 1 card) | ~~No Rust arm. Confirmed.~~ **STALE — corrected round 53 (3rd confirmed-stale entry after Mechanozoa/Warmaker r51).** The arm shipped round 31 as `Effect::DoubleTargetCreaturesPowerUEOT` (`cards.rs:886`, `90bc39ca`) + bridge arm `double_target_creatures_power_ueot` (`cross_engine.py:5951`) — there was never a separate `DoubleTargetPowerUntilEOT` ask; the plan-invented name conflated it. **Mightform Harmonizer is NOT BLOCKED-RUST-EFFECT.** Round-53 N2 additionally found + fixed a real latent §2 bug in the shipped round-31 arm (Rust doubled *base* power via `read_battlefield_creature_power`; Python doubles *effective* power incl. +1/+1 counters — disagreed on a countered creature) and added a genuine real-EoE landfall+counter cross-engine probe (byte-equal post-fix; see `SEARCH_LIMITATIONS.md` round-53 entry). Residual blockers are the landfall `Predicate::Subject(IsLand)` substrate + `warp_cost` loader gate → **BLOCKED-FILTER/substrate**, not an Effect gap. The §round-19 / §2.6 "needs new Rust" framing for Mightform Harmonizer is correspondingly stale — **the round-54 full programmatic re-walk reconciled all such locations** (this row, §2.6 line `DoubleTargetPowerUntilEOT`, the §2.6 LandfallWithComplexEffect row, the round-34 closures table line ~80 which already recorded the round-31 closure) so the doc is no longer internally self-contradictory on Mightform. |
| `CastFromExileWithCostHike` (Lightstall Inquisitor — 1 card) | No Rust arm. Confirmed. |
| `SacUnlessYouTap` (Command Bridge — 1 card) | No Rust arm. Confirmed (first land-ETB in audit). |
| `ReturnPermanentCardWithMVXorLessFromGY` (Astelli Reclaimer — 1 card) | No mana-value-condition GY-return arm in Rust. Confirmed. |
| `DealDamageToAnyTargetEqualToArtifactCount` (Warmaker Gunship — 1 card) | ~~No X-from-artifact-count plumbing. ... Confirmed.~~ **STALE — corrected round 51.** Round-32 shipped `Effect::DealDamageToOpponentCreatureByArtifactCount` + bridge arm (`cross_engine.py:6326`); a round-32 deferred-EoE end-to-end probe (`test_cross_engine_real_eoe_warmaker_gunship_etb_damage_by_artifact_count_parity`) already exists. **Warmaker Gunship is NOT BLOCKED-RUST-EFFECT** — its ETB Effect arm is fully substrated + bridged. Its residual blocker is the `Station` ability + `Spacecraft` artifact type gating the production-deck loader admit → **BLOCKED-Station-subsystem**, not an Effect gap. |
| `PumpAndGrantDiesReturnTrigger` (Perigee Beckoner — 1 card) | No nested-trigger-grant substrate. Confirmed. |
| `TwoMobileSubjects` (Monoist Circuit-Feeder — 1 card) | ~~No simultaneous-two-target substrate. Confirmed.~~ **STALE — corrected round 54 (4th confirmed-stale entry after Mechanozoa/Warmaker r51, Mightform r53).** Closed round 51: `Effect::TwoSubjectPumpAndDebuffByArtifactCount` (`cards.rs`) + bridge arm `two_subject_pump_and_debuff_by_artifact_count` + a genuine real-EoE byte-equal cross-engine probe (~14,727 decks; the real printing parses to the agent-driven `PairedTargetPumpDebuffUEOT`, the deterministic sibling rides the dedicated variant). The plan-invented `TwoMobileSubjects` name resolves to the shipped variant. **Monoist Circuit-Feeder is NOT BLOCKED-RUST-EFFECT** → PROBED/CLOSED. |
| `EachOpponentExilesFromHand` (Lightstall Inquisitor — 1 card; same card as cast-from-exile entry above) | No Rust arm. Confirmed. |
| `EnchantedDealsDamageThenPropagate` (Pain for All — 1 card) | No self-replicating damage substrate. Confirmed. |
| `ExileEachOpponentGYAndCreateToken` (Dauntless Scrapbot — 1 card) | No exile-each-graveyard substrate. Confirmed. |
| `Faller's Faithful` (`damage-this-turn` tracking — §2.7) | No damage-this-turn ledger. Confirmed. |
| Aura-shape `Fight` for Meltstrider's Resolve | Needs `Effect::EnchantedCreatureFightsTarget` — Rust does NOT have it, only the bare bilateral form. Confirmed per `SEARCH_LIMITATIONS.md`. |

### Headline-impact summary (round-19 re-audit)

- **BLOCKED-RUST-EFFECT count: 42 → ~28** (reduction of ~14):
  - 3 cards moved to PROBED (`SetBasePTUntilEOT`, bare `Fight`,
    Melded Moxite — already had probes the audit didn't credit).
  - 4 cards moved to BLOCKED-BRIDGE-ARM (Auxiliary Boosters,
    Illvoi Light Jammer, Meltstrider's Gear, Squire's Lightblade —
    via `AttachTo`/`EquipTo` substrate).
  - 1 card moved to BLOCKED-BRIDGE-ARM (Selfcraft Mechan —
    `OptionalSacArtifactForEffect` substrate).
  - 1 card moved to BLOCKED-BRIDGE-ARM (Pulsar Squadron Ace —
    `LookAtTopNRevealOrCounter` substrate; sub-mode follow-up risk).
  - 1 card moved to PROBED (Glacier Godmaw — landfall create-token
    variant from §2.6's "LandfallWithComplexEffect" bucket).
  - The "DestroyNoncreatureThenAOEDamage" (Extinguisher Battleship)
    + Terrapact Intimidator entries flagged for follow-up
    (substrate exists; bridge composition pending).
- **BLOCKED-BRIDGE-ARM count: ~5 → ~12** (the 6 newly-reclassified
  entries above bring the bridge-arm-only backlog up — but this
  is the *cheap* backlog; each card ships in 1-2 hours of bridge-
  arm slice work).
- **PROBED on main: 34 → 48** (+14 distinct real-EoE printings vs
  prior refresh).

### Pattern + recommendation

The pattern matches round-18's SetBasePT finding precisely: the
audit's §2.6 buckets were measured at `a2755769` before substantial
Rust work landed (rust-tdd-base + rust-tdd-integrated branches
through r19, plus targeted slices like `feature/rust-fight-effect`
and the round-18 SetBasePT-bridge slice itself). Each subsequent
round of Rust effect work reduces the actually-blocking count
without the audit catching up.

**Recommendation: trigger the next audit refresh on Rust-side
merges into main, not on elapsed rounds.** A nightly cron diffing
`rust/src/cards.rs::Effect` arm count + `_ta_dict_to_python_effect`
arm count against the audit's tally would surface staleness
automatically. Without that, each Rust merge adds shadow-
substrate that misleads probe-slice planning into expecting Rust
work that's already done.

The §1 table and the per-card §2.x tables below remain the
as-of-`a2755769` historical inventory. Use the headline section
above for current totals; treat the legacy sections as
documentary context.

## Historical: round-10 refresh narrative (as-of `ebb5c6ec`, 2026-05-13)

Kept verbatim for cross-round reference; the round-19 headline
section above supersedes the counts. Use the round-19 section for
current planning.

**Headline-count delta vs the `a2755769` snapshot** (the §1 table
below):

- BLOCKED-BRIDGE-ARM: **27 -> ~5**. Of the 27 cards listed in
  §2.4, 17 have shipped real-EoE probes (Pinnacle Kill-Ship, Nova
  Hellkite, Virus Beetle, Seedship Broodtender, Starbreach Whale,
  Wurmwall Sweeper, Thawbringer-ETB, Sinister Cryologist, Dubious
  Delicacy, Atmospheric Greenhouse, Rayblade Trooper, Drix
  Fatemaker, Fell Gravship, Interceptor Mechan, Uthros Scanship,
  Melded Moxite, Susurian Dirgecraft); plus the 4 §2.3
  branch-unblock cards Honored Knight-Captain, Knight Luminary,
  Wedgelight Rammer also shipped. The remaining bridge-arm-only
  pending list is small: Mouth of the Storm (bridge arm shipped
  but Rust extended-duration variant blocks the real-EoE probe —
  see substrate-gap update below), Weftblade Enhancer (up-to-N
  targets), Blade of the Swarm (choose_one_mode + self-counter),
  Starfield Shepherd / The Seriema (search_library_for_card —
  in flight on `feature/phase5-ce-bridge-search-library`),
  Codecracker Hound (look-top-N), Larval Scoutlander
  (optional-sac + search-basic-land).
- BLOCKED-SUBSTRATE: **8 -> ~9**. Mouth of the Storm has been
  reclassified into this bucket (the synthetic
  `pump_creatures_opponents_control_until_eot` arm shipped, but
  the real-EoE consumer divergence vs the Rust trigger needs an
  extended-duration variant on the Rust side — round-4 finding).
  EachOpponentSacrificesCreature was unblocked once
  `each_opponent_sacrifices_creature` shipped + the
  Susurian-Dirgecraft `token-first` divergence pin captured the
  iterator-order divergence.
- BLOCKED-RUST-EFFECT: **42 -> 42** (steady). No Rust-side effect
  arms have landed in this cohort; the surface is unchanged. Two
  cards (Banishing Light, Hardlight Containment) shifted *out* of
  this bucket once round-9 agent Q discovered they map onto the
  already-shipped `exile_opponents_nonland_permanent_until_leaves`
  arm — correcting the audit's prior "EoE has no bare-shape
  printing" claim.
- SHIPPED probes (cross-engine ETB only): **8 real-EoE -> 34
  real-EoE (+26)**, plus a brand-new synthetic + cross-controller
  surface (29 + 21) totaling **68 cross-engine ETB probes** vs
  the original ~10.

Three review-gated branches called out in §4.1 of the original
audit (`feature/phase5-create-token-bridge`,
`feature/etb-subject-substrate`, `feature/dies-event-harness`)
are still unmerged on origin as of this refresh; create_token
itself has effectively shipped via the per-card slice route
(Honored Knight-Captain, Knight Luminary, Wedgelight Rammer all
landed on main without merging the master branch).

**New substrate gaps surfaced by recent rounds** (not in original §2.5):

- Mouth of the Storm needs a Rust extended-duration variant of
  `PumpCreaturesOpponentsControlUntilEOT` so the bridge arm's
  duration matches the trigger semantics on the real card (the
  synthetic probe established the bridge plumbing, the real-EoE
  probe surfaced the duration mismatch — round 4).
- Susurian Dirgecraft pinned an iterator-order divergence in
  `each_opponent_sacrifices_creature`: when an opponent controls
  both a token and a non-token creature, Rust prefers the token
  first while Python's chooser picks the non-token. Captured by
  `test_cross_engine_real_eoe_susurian_dirgecraft_etb_each_opp_sac_token_first_divergence_pin`.
- Pinnacle Kill-Ship pinned a divergence in
  `deal_damage_any_target` when the bridge picks up a Spacecraft
  source whose triggered effect is optional and the battlefield
  contains zero legal targets (Rust skips, Python emits a no-op
  damage event). Captured by
  `test_cross_engine_real_eoe_pinnacle_kill_ship_etb_damage_optional_empty_bf_divergence_pin`.

The §1 table and the per-card §2.x tables below are the
as-of-`a2755769` historical inventory. Use the table at the top of
this section for current totals; treat the legacy sections as
documentary context.

## Companion docs

- [`docs/RUST_ETB_TRIGGER_AUDIT.md`](RUST_ETB_TRIGGER_AUDIT.md) —
  Python-side audit of which printings carry ETB triggers (the
  superset this Rust audit measures against).
- [`docs/PHASE5_STATUS.md`](PHASE5_STATUS.md) — overall Phase 5
  status, including the already-landed probe slate.
- [`docs/RUST_EFFECT_COVERAGE.md`](RUST_EFFECT_COVERAGE.md) — current
  Rust `Effect` enum coverage of the EoE pool (Effect arms exist in
  Rust for many things that aren't yet wired in the cross-engine
  bridge — this audit measures the bridge gap, not the Rust gap).

---

## Section 1: Headline numbers

Filter: every EoE printing whose oracle text contains an
"enters"-event trigger — `When this ... enters`, `Whenever ... enters`
(self / another / any-subject), or `Landfall — Whenever a land you
control enters`. This is the superset of CE19-shape probe candidates:
the trigger fires on an `Enters` event with some predicate, then
runs an `Effect` whose Rust + Python arms must agree.

| Bucket | Count |
| --- | --- |
| **Total EoE printings with `enters`-event triggers** | **93** |
| Already probed (cross-engine real-EoE probe landed on `main`) | 10 |
| Already probed via unmerged review-gated branch | 2 |
| Probe-able **today** on `main` with zero new substrate | 1 (Pinnacle Kill-Ship — `damage_any_target` arm landed; Debris Field Crusher probed in af901bc9) |
| Blocked **only** by an unmerged review-gated branch | 6 |
| Blocked by a missing bridge-side effect arm (small extension) | 26 |
| Blocked by a missing predicate variant (small extension) | 0 unique (all subsume into effect gaps) |
| Blocked by missing substrate (multi-subject events / DIES / etc.) | 8 |
| Blocked by Rust-side missing Effect arm (true new code) | 42 |

**Update**: as of `5abe8958`, the parallel agent's
`damage_any_target` bridge arm + Nebula Dragon probe landed on
main. Counts above reflect Nebula Dragon moving from
"BLOCKED-BRIDGE-ARM" to "PROBED". The other two consumers of
`damage_any_target` (Debris Field Crusher, Pinnacle Kill-Ship) are
now probe-eligible today on main — the only remaining gate is a new
probe slice per card, not a substrate gate.

Notes on totals:

- "Already probed on main": Germinating Wurm, Quantum Riddler,
  Eumidian Terrabotanist, Tannuk Memorial Ensign, Kav Landseeker
  (subtype-only preview), Weftstalker Ardent, Haliya Guided by
  Light, Alpharael Dreaming Acolyte (draw 2). 8 cards. (One of these
  — Mechan Assembler — has a *preview* probe on main but is full-
  probed only on the create-token branch; counted in row 2.)
- "Already probed via unmerged branch": Mechan Assembler (full) on
  `feature/phase5-create-token-bridge`; Cryogen Relic (ETB half on
  main; LEAVES half on `feature/dies-event-harness`). 2 cards.
- The "0 today on main" line is the headline of this audit: every
  remaining unprobed enters-trigger card needs at least one piece
  of new substrate (effect bridge arm, predicate variant, multi-
  subject event, or a Rust Effect-enum extension). The bridge has
  hit a wall at draw_cards / gain_life / damage_each_opponent —
  every probe slice from here unblocks something.
- The 27 + 8 + 42 = 77 "blocked" total is the residue after
  subtracting the 16 probed/landing-via-unmerged-branch cards from
  the 93. Sums hold:
  93 = 8 (probed main) + 2 (probed branch) + 6 (branch-only block)
       + 27 (bridge-arm block) + 8 (substrate block)
       + 42 (Rust Effect-arm block).

---

## Section 2: Per-card inventory

Table columns:

- **Card**: name from `data/edge_of_eternities.json`.
- **Predicate**: closed-enum shape from
  `rust/src/cards.rs::Predicate` that the trigger needs. "Subject(...)"
  means the multi-subject substrate from
  `feature/etb-subject-substrate` is required (Predicate::Subject is
  not yet on main).
- **Effect**: closed-enum shape from
  `rust/src/cards.rs::Effect`. Bridge column shows whether
  `_ta_dict_to_python_effect` in `src/mtg_bot/parity/cross_engine.py`
  has the arm wired today.
- **Status**: PROBED / PROBED-BRANCH / BLOCKED-BRIDGE-ARM /
  BLOCKED-SUBSTRATE / BLOCKED-RUST-EFFECT.
- **Blocked by**: specific gap name.

### 2.1 Already probed (PROBED on main)

**Refresh note (2026-05-13):** this table captures the state at
`a2755769`. Since then 24 additional real-EoE cards have been
probed (see the inline `[SHIPPED]` annotations in §2.3 and §2.4
below). Full current list of distinct real-EoE printings probed
on main (34 total): alpharael_dreaming_acolyte,
atmospheric_greenhouse, banishing_light, cryogen_relic (ETB half),
debris_field_crusher, drix_fatemaker, dubious_delicacy,
eumidian_terrabotanist, fell_gravship, germinating_wurm,
haliya_guided_by_light, hardlight_containment, honored_knight_captain,
interceptor_mechan, kav_landseeker, knight_luminary, mechan_assembler,
melded_moxite, nebula_dragon, nova_hellkite, pinnacle_kill_ship,
quantum_riddler, rayblade_trooper, seedship_broodtender,
sinister_cryologist, starbreach_whale, susurian_dirgecraft,
tannuk_memorial_ensign, thawbringer (ETB half), uthros_scanship,
virus_beetle, wedgelight_rammer, weftstalker_ardent, wurmwall_sweeper.

| Card | Predicate | Effect | Probe lands |
| --- | --- | --- | --- |
| Germinating Wurm | SourceIsSelf | GainLife{2} | probe(phase5): Germinating Wurm |
| Quantum Riddler | SourceIsSelf | DrawCards{1} | probe(phase5): Quantum Riddler |
| Eumidian Terrabotanist | Subject(IsLand) AND ControlledByYou (landfall) | GainLife{1} | probe(phase5): Eumidian Terrabotanist landfall |
| Tannuk, Memorial Ensign | Subject(IsLand) AND ControlledByYou | DamageEachOpponent{1} | probe(phase5): Tannuk Memorial Ensign |
| Kav Landseeker (subtype only) | SourceIsSelf | (preview — full needs create_token) | probe(phase5): Kav Landseeker subtype preview |
| Weftstalker Ardent | Or(IsCreature, IsArtifact) AND ControlledByYou AND Not(SourceIsSelf) | DamageEachOpponent{1} | probe(phase5): Weftstalker Ardent |
| Haliya, Guided by Light | And(Or(IsCreature, IsArtifact), ControlledByYou) | GainLife{1} | probe(phase5): Haliya Guided by Light |
| Alpharael, Dreaming Acolyte | SourceIsSelf | DrawCards{2} | probe(phase5): Alpharael Dreaming Acolyte |
| Nebula Dragon | SourceIsSelf | DealDamageAnyTarget{3} | probe(phase5): Nebula Dragon ETB any-target burn (f258114f) |
| Debris Field Crusher | SourceIsSelf | DealDamageAnyTarget{3} | probe(phase5): Debris Field Crusher ETB any-target burn (5b6c184e) |
| Banishing Light | SourceIsSelf | ExileOpponentsNonlandPermanentUntilLeaves | probe(phase5): Banishing Light (cee80270) — first real-EoE consumer of the I80 arm; corrected the audit's "no bare-shape printing" claim |
| Hardlight Containment | SourceIsSelf | ExileOpponentsNonlandPermanentUntilLeaves (Aura) | probe(phase5): Hardlight Containment (d9246140) — second consumer; first Aura-subtype carrier |

### 2.2 Probed via unmerged review-gated branch (PROBED-BRANCH)

| Card | Predicate | Effect | Branch |
| --- | --- | --- | --- |
| Mechan Assembler | Subject(IsArtifact) AND ControlledByYou AND Not(SourceIsSelf) | CreateToken{1, 2/2 Robot} | feature/phase5-create-token-bridge |
| Cryogen Relic (ETB half) | SourceIsSelf | DrawCards{1} | (ETB half on main; LEAVES half on feature/dies-event-harness) |

### 2.3 Blocked only by an unmerged branch (BRANCH-UNBLOCK)

These cards' effects + predicates are all in-scope on existing
unmerged branches — merging the branches unlocks them with zero
additional substrate work.

| Card | Predicate | Effect | Blocked by |
| --- | --- | --- | --- |
| Honored Knight-Captain | SourceIsSelf | CreateToken{1, 1/1 W Soldier} | **[SHIPPED]** create_token arm landed via per-card slice (didn't need master branch merge) |
| Knight Luminary | SourceIsSelf | CreateToken{1, 1/1 W Soldier} | **[SHIPPED]** same arm, second consumer |
| Wedgelight Rammer | SourceIsSelf | CreateToken{1, 2/2 Robot} | **[SHIPPED]** Robot artifact-creature token shape |
| Galactic Wayfarer | SourceIsSelf | CreateToken{1, Lander} | create-token bridge branch (Lander shape pending) |
| Eusocial Engineering | Subject(IsLand) AND ControlledByYou | CreateToken{1, 2/2 Robot} | create-token + landfall (etb-subject-substrate already covers landfall predicate; full create_token already in branch) |
| Tezzeret, Cruel Captain | Subject(IsArtifact) AND ControlledByYou | (loyalty-counter ≈ AddCounters on self-source) | etb-subject-substrate AND a "counter on planeswalker" variant — only the predicate is review-gated; the counter-on-source variant needs a small arm extension (see §2.5) |

(Tezzeret straddles two gates; counted in §2.5 under the effect-arm
bucket since the predicate gate alone doesn't unblock it.)

### 2.4 Blocked by a missing **bridge** arm — effect already exists in Rust's `Effect` enum but `_ta_dict_to_python_effect` doesn't translate it (BLOCKED-BRIDGE-ARM)

These are the **lowest-cost** unlocks: one bridge arm extension per
gap, mirroring the existing `draw_cards` / `gain_life` /
`damage_each_opponent` shape. Each card listed needs its predicate to
also be wired (most use SourceIsSelf, which already works on main).

**Annotation legend (added 2026-05-13 refresh):** `[SHIPPED]` =
real-EoE probe landed on main; `[SHIPPED + DIVERGENCE PIN]` =
probe landed plus a paired divergence-pin test; `[SUBSTRATE]` =
bridge arm shipped but the real-EoE consumer surfaced a substrate
gap (see §2.5 update); `[IN FLIGHT]` = active worktree on origin.

| Card | Predicate (Rust shape) | Effect (Rust shape) | Blocked by bridge gap |
| --- | --- | --- | --- |
| Pinnacle Kill-Ship | SourceIsSelf | DealDamageAnyTarget{10} (single creature) | **[SHIPPED + DIVERGENCE PIN]** real-EoE probe + empty-bf divergence pin |
| Nova Hellkite | SourceIsSelf | DealDamageOpponentCreature{1} | **[SHIPPED]** damage-to-opponent-creature arm + probe |
| Virus Beetle | SourceIsSelf | EachOpponentDiscards{1} | **[SHIPPED]** each_opponent_discards arm + probe |
| Seedship Broodtender | SourceIsSelf | Mill{3} (self-controller) | **[SHIPPED]** mill arm + probe (incl. empty-library mid-mill variant) |
| Starbreach Whale | SourceIsSelf | Surveil{2} | **[SHIPPED]** surveil arm + probe (incl. mill-path variant) |
| Wurmwall Sweeper | SourceIsSelf | Surveil{2} | **[SHIPPED]** surveil arm + probe |
| Thawbringer (ETB half) | SourceIsSelf | Surveil{1} | **[SHIPPED]** surveil arm + probe (count=1 variant); LEAVES/DIES half still needs harness (§2.5) |
| Icetill Explorer (landfall) | Subject(IsLand) AND ControlledByYou | Mill{1} | mill bridge arm (subject-substrate branch covers predicate) |
| Sinister Cryologist | SourceIsSelf | PumpTargetCreatureUntilEOT{-3, 0} | **[SHIPPED]** pump-target-creature-until-eot arm + probe (asymmetric debuff variant) |
| Dubious Delicacy | SourceIsSelf | PumpTargetCreatureUntilEOT{-3, -3} | **[SHIPPED]** pump-target-creature-until-eot arm + probe (signed-toughness variant) |
| Mouth of the Storm | SourceIsSelf | PumpCreaturesOpponentsControlUntilEOT{-3, 0} | **[SUBSTRATE]** bridge arm shipped; real-EoE probe blocked on Rust extended-duration variant — see §2.5 update |
| Atmospheric Greenhouse | SourceIsSelf | PutPlusOneCounterOnEachCreatureYouControl{1} | **[SHIPPED]** mass-counter arm + probe |
| Rayblade Trooper (ETB half) | SourceIsSelf | PutPlusOneCounterOnCreatureYouControl{1} | **[SHIPPED]** counter-on-target-your-creature arm + probe |
| Drix Fatemaker | SourceIsSelf | PutPlusOneCounterOnCreatureYouControl{1} (any creature) | **[SHIPPED]** second consumer of the same arm |
| Weftblade Enhancer | SourceIsSelf | PutPlusOneCounterOnEachOfUpToNTargetCreatures{2} | up-to-N-counter-targets bridge arm |
| Blade of the Swarm | SourceIsSelf | ChooseOneMode{[PutPlusOneCountersOnSelf{2}, ...]} | choose-one-mode bridge arm (+ self-counter arm) |
| Starfield Shepherd | SourceIsSelf | SearchLibraryForCard{...} | **[IN FLIGHT]** `feature/phase5-ce-bridge-search-library` |
| The Seriema | SourceIsSelf | SearchLibraryForCard{legendary creature} | **[IN FLIGHT]** same branch |
| Fell Gravship | SourceIsSelf | Sequence{[Mill{3}, ReturnCreatureFromYourGraveyardToHand]} | **[SHIPPED]** sequence + mill + return-from-gy arms + probe |
| Interceptor Mechan | SourceIsSelf | ReturnCreatureFromYourGraveyardToHand | **[SHIPPED]** return-from-gy-to-hand arm + probe (artifact-or-creature subtype variant) |
| Uthros Scanship | SourceIsSelf | Sequence{[DrawCards{2}, DiscardSelf{1}]} | **[SHIPPED]** discard_self arm + probe (sequence draw-then-discard variant) |
| Codecracker Hound | SourceIsSelf | LookTopNPutOneInHandRestToGraveyard{2} | look-top-N-put-one-in-hand bridge arm |
| Larval Scoutlander | SourceIsSelf | OptionalSacArtifactForEffect{SearchLibraryForBasicLandTapped{2}} | optional-sac + search-basic-land bridge arms |
| Melded Moxite | SourceIsSelf | IfYouDo{cost=DiscardSelf, then=DrawCards{2}} | **[SHIPPED]** if-you-do + discard_self arms + probe |
| Astelli Reclaimer | SourceIsSelf | (return-noncreature-card-from-gy-with-MV≤X-to-bf) | new Rust arm; see §2.6 |
| Susurian Dirgecraft | SourceIsSelf | EachOpponentSacrificesCreature | **[SHIPPED + DIVERGENCE PIN]** each-opp-sac arm + probe + token-first divergence pin |

Effective bridge-arm gaps (group-by):

| Bridge-arm gap | Cards unblocked |
| --- | --- |
| `damage_any_target` (landed 5abe8958) | 1 remaining (Pinnacle Kill-Ship); Nebula Dragon + Debris Field Crusher already probed |
| `surveil` | 3 (Starbreach Whale, Wurmwall Sweeper, Thawbringer-ETB) |
| `mill` (controller-self) | 3 (Seedship Broodtender, Icetill Explorer, Fell Gravship-prefix) |
| `pump_target_creature_until_eot` | 2 (Sinister Cryologist, Dubious Delicacy) |
| `pump_creatures_opponents_control_until_eot` | 1 (Mouth of the Storm) |
| `put_plus_one_counter_on_creature_you_control` (target variant) | 3 (Rayblade Trooper, Drix Fatemaker, plus tail) |
| `put_plus_one_counter_on_each_creature_you_control` | 1 (Atmospheric Greenhouse) |
| `put_plus_one_counter_on_each_of_up_to_N_target_creatures` | 1 (Weftblade Enhancer) |
| `search_library_for_card` | 2 (Starfield Shepherd, The Seriema) |
| `return_creature_from_graveyard_to_hand` | 2 (Interceptor Mechan, Fell Gravship-suffix) |
| `discard_self` | 2 (Uthros Scanship, Melded Moxite — also `if_you_do`) |
| `each_opponent_discards` | 1 (Virus Beetle) |
| `each_opponent_sacrifices_creature` | 1 (Susurian Dirgecraft) |
| `look_top_n_put_one_in_hand_rest_to_graveyard` | 1 (Codecracker Hound) |
| `optional_sac_artifact_for_effect` + `search_library_for_basic_land_tapped` | 1 (Larval Scoutlander) |
| `if_you_do` | 1 (Melded Moxite) |
| `damage_to_opponent_creature` | 1 (Nova Hellkite) |
| `choose_one_mode` + `put_plus_one_counter_on_self` | 1 (Blade of the Swarm) |
| `sequence` (composer arm) | 2 (Fell Gravship, Uthros Scanship — but already counted under their constituent gaps) |

### 2.5 Blocked by missing substrate (BLOCKED-SUBSTRATE)

These cards need substrate that is **not** a one-line bridge arm —
either a new event type, multi-subject substrate, or a "this kind
of effect doesn't fit the current single-source-single-subject
dispatch shape".

| Card | Predicate / shape | Blocked by substrate gap |
| --- | --- | --- |
| Thawbringer (DIES half) | SourceIsSelf, on Dies | DIES-event harness branch (`feature/dies-event-harness`) — same gap as Cryogen Relic LEAVES half |
| Syr Vondam, the Lucent | event=Enters OR event=Attacks (combined trigger) | multi-event dispatcher (Enters + Attacks as one ability) — not in any branch today |
| Haliya, Ascendant Cadet | event=Enters OR event=Attacks | same multi-event-dispatcher gap |
| Possibility Technician | Subject(IsKavu) (OR) SourceIsSelf | "self OR subject-matches" disjunction — etb-subject-substrate covers the predicate algebra; effect (exile-top-of-library + cast-while-exiled) is its own new Rust arm |
| Tezzeret, Cruel Captain | Subject(IsArtifact) AND ControlledByYou | etb-subject-substrate covers predicate; effect "put loyalty counter on self" needs PW-counter substrate |
| Mm'menon, Uthros Exile | Subject(IsArtifact) AND ControlledByYou | etb-subject-substrate covers predicate; effect (counter-on-any-target-creature) needs free-target-choice plumbing |
| Oreplate Pangolin | Subject(IsArtifact) AND ControlledByYou AND Not(SourceIsSelf) | etb-subject-substrate covers predicate; effect (optional mana cost → +1/+1 counter on self) needs `OptionalManaCostThenEffect` bridge arm + self-counter substrate |
| Weapons Manufacturing | Subject(IsArtifact) AND ControlledByYou AND Not(IsToken) | predicate gap: `Not(IsToken)` — no `SubjectIsToken` predicate yet (token-aware predicates are a substrate gap) |

### 2.6 Blocked by missing **Rust Effect** arm (BLOCKED-RUST-EFFECT)

These cards reference an effect shape that has **no Rust Effect arm
today**. They are the highest-cost unlocks — each needs a Rust
arm + a bridge arm + a Python parity check. The list is roughly in
ascending order of arm complexity within the bucket.

Order-of-magnitude effects that recur across many cards:

| Recurring missing Rust arm | Cards | Notes |
| --- | --- | --- |
| `CreateLanderToken` (parameterized create-token: 2/2 Robot, 1/1 Soldier, Lander, Munitions, copy-of-target, multicolor-conditional) | 13 (Auxiliary Boosters, Bioengineered Future, Biomechan Engineer, Biotech Specialist, Dauntless Scrapbot, Glacier Godmaw, Infinite Guideline Station, Sunstar Expansionist, Terrapact Intimidator, Eusocial Engineering, plus tail) | create-token branch covers the base arm; this counts the cards whose create_token has parameters or conditional gates beyond the existing branch shape |
| `ExileTargetUntilSourceLeaves` | 5 (All-Fates Stalker, Banishing Light, Hardlight Containment, Pinnacle Starcage, Seam Rip) | Rust has `ExileTargetCreatureUntilSourceLeaves`; the Banishing-Light shape (any nonland permanent) and Pinnacle-Starcage shape (AOE-conditional) are siblings |
| `AttachSelfToTargetCreature` / `EquipToTargetCreatureYouControl` | 4 (Auxiliary Boosters, Illvoi Light Jammer, Meltstrider's Gear, Squire's Lightblade) | Rust has the unit-variant arms; bridge does not wire them |
| ~~`TapTargetAndPutStunCounter` (stun-counter substrate)~~ **CLOSED round-30 / corrected round-51** | ~~2 (Mechanozoa, Cryogen Relic activated half)~~ → **0 Effect-blocked** | ~~no stun-counter shape in Rust today~~ **STALE.** `Effect::TapTargetOpponentPermanentAndStunIt` (Mechanozoa) + `put_stun_counter_on_tapped_creature` (Cryogen Relic activated half) both shipped round-30 + bridged. Mechanozoa → **BLOCKED-FILTER (warp_cost)**, not Effect-blocked (round-51 real-printing CE probe byte-equal). NOT a BLOCKED-RUST-EFFECT row. |
| `LandfallWithComplexEffect` (landfall predicate + non-trivial effect) | 4 (Glacier Godmaw, Mightform Harmonizer, Genemorph Imago, Seedship Agrarian, Remnant Elemental) | predicate is in etb-subject-substrate; effect arms (mass-pump + vigilance/haste, ~~double-power-EOT~~, set-base-PT, +1/+1 counter on self via landfall) need new Rust arms. **STALE — corrected round 54:** the `double-power-EOT` effect arm is NOT missing — Mightform Harmonizer's effect shipped round 31 as `Effect::DoubleTargetCreaturesPowerUEOT` + bridged (r53 bug-fixed + probed); its only residual gates are the landfall `Subject(IsLand)` predicate + `warp_cost`. `Genemorph Imago`'s `SetBasePTUntilEOT` arm also already exists (round 18, `RUST_AHEAD_OF_POOL`); `Remnant Elemental` composes the already-shipped `PutPlusOneCounterOnSelf` + the landfall predicate (bridge composition, not a new Effect). The genuine new-Rust-arm in this bucket is **`Seedship Agrarian`'s landfall effect arm** only. |
| `SetBasePTUntilEOT` | 1 (Genemorph Imago) | Rust has `SetBasePTUntilEOT` arm; no bridge or trigger-driven wiring |
| `Fight` (creature-vs-creature) | 1 (Meltstrider's Resolve) | bare bilateral form shipped (`Effect::FightTargetCreatureWithTargetCreature` + bridge + `FightTargetCreatureWithTargetCreature` Python sibling); Aura-shape (Meltstrider's Resolve specifically — source fighter is the Aura's `attached_to` enchanted creature) is the deferred follow-up — needs new `Effect::EnchantedCreatureFightsTarget` Rust variant routing through `attached_to` end-to-end. See SEARCH_LIMITATIONS.md "Fight" entry |
| ~~`DoubleTargetPowerUntilEOT`~~ **CLOSED round-31 / corrected round 54** | ~~1 (Mightform Harmonizer)~~ → **0 Effect-blocked** | ~~no Rust arm~~ **STALE.** Shipped round 31 as `Effect::DoubleTargetCreaturesPowerUEOT` (`cards.rs:886`) + bridge arm `double_target_creatures_power_ueot` — the plan-invented `DoubleTargetPowerUntilEOT` name conflated the real shipped variant. r53 fixed a latent effective-vs-base power bug + added a real-EoE probe. Mightform Harmonizer → **BLOCKED-FILTER/substrate** (landfall `Subject(IsLand)` + `warp_cost`), NOT a BLOCKED-RUST-EFFECT row. |
| `OptionalDiscardThenDraw` (Melded Moxite-shape `if_you_do`) | 1 (Melded Moxite — also counted in §2.4) | Rust has `IfYouDo`; just needs bridge arm |
| `OptionalSacrificeArtifactForCounterAndDraw` (Selfcraft Mechan) | 1 (Selfcraft Mechan) | nested optional-sac + counter + draw; partly in Rust |
| `ExileGraveyardCastFromExile` (Roving Actuator void-style) | 1 (Roving Actuator) | needs `Void` trigger condition + exile-then-cast-copy substrate |
| `LookXAndPutLandsTapped` (Famished Worldsire) | 1 (Famished Worldsire) | X = source power; no Rust arm |
| `CastFromExileWithCostHike` (Lightstall Inquisitor) | 1 (Lightstall Inquisitor) | "each opponent exiles a card from their hand and may play it; +1 cost; lands enter tapped" — no Rust substrate |
| `SacUnlessYouTap` (Command Bridge) | 1 (Command Bridge) | "sacrifice it unless you tap an untapped permanent" — no Rust arm; first land-ETB in the audit |
| `ReturnPermanentCardWithMVXorLessFromGY` (Astelli Reclaimer) | 1 (Astelli Reclaimer) | needs mana-value-condition substrate on the GY-return arm |
| `ChoiceTrigger` (Pulsar Squadron Ace look-5-reveal-Spacecraft) | 1 (Pulsar Squadron Ace) | revelation + put-into-hand-OR-counter-on-self path |
| ~~`DealDamageToAnyTargetEqualToArtifactCount` (Warmaker Gunship)~~ **CLOSED round-32 / corrected round-51** | ~~1 (Warmaker Gunship)~~ → **0 Effect-blocked** | ~~X-from-artifact-count needs dynamic-X plumbing~~ **STALE.** `Effect::DealDamageToOpponentCreatureByArtifactCount` shipped round-32 + bridged + deferred-EoE probe exists. Warmaker Gunship → **BLOCKED-Station-subsystem** (Station ability + Spacecraft type), not Effect-blocked. NOT a BLOCKED-RUST-EFFECT row. |
| `PumpAndGrantDiesReturnTrigger` (Perigee Beckoner) | 1 (Perigee Beckoner) | grants a *new* DIES trigger on the target — needs nested-trigger substrate |
| ~~`TwoMobileSubjects` (Monoist Circuit-Feeder)~~ **CLOSED round-51 / corrected round 54** | ~~1 (Monoist Circuit-Feeder)~~ → **0 Effect-blocked** | ~~targets one of yours and one of theirs simultaneously~~ **STALE.** Shipped round 51 as `Effect::TwoSubjectPumpAndDebuffByArtifactCount` + bridge arm `two_subject_pump_and_debuff_by_artifact_count` + a genuine real-EoE byte-equal cross-engine probe (~14,727 decks). The plan-invented `TwoMobileSubjects` name resolves to the shipped variant. Monoist Circuit-Feeder → **PROBED/CLOSED**, NOT a BLOCKED-RUST-EFFECT row. (One of the 2 entries the round-54 full re-walk surfaced beyond the known r51/r53 three.) |
| `EachOpponentExilesFromHand` (Lightstall Inquisitor) | 1 | (also above) |
| `EnchantedDealsDamageThenPropagate` (Pain for All) | 1 (Pain for All) | self-replicating damage shape; no Rust arm |
| `TapEnchantedYouControlAndDontUntap` (Tractor Beam) | 1 (Tractor Beam) | tap + control-swap + don't-untap composition |
| ~~`DestroyNoncreatureThenAOEDamage` (Extinguisher Battleship)~~ **EFFECT CLOSED round-52 / corrected round 54** | ~~1 (Extinguisher Battleship)~~ → **0 Effect-blocked** | ~~sequence with mass-damage component~~ **STALE.** Effect-half shipped round 52: `Effect::DestroyTargetNoncreaturePermanent` (precise new variant — round-52 N2 corrected the r50/r51 plan's unsafe nonland≈noncreature approximation) composed via `Sequence` with the already-shipped `Effect::DamageEachCreature`; all three arms bridge-wired (`destroy_target_noncreature_permanent`, `damage_each_creature`, `sequence`). The ETB effect is fully substrated on both engines. Residual blocker is the `Station` ability + `Spacecraft` artifact type gating the full-card production-deck admit → **BLOCKED-Station-subsystem**, NOT a BLOCKED-RUST-EFFECT row. (The 2nd of the 2 entries the round-54 full re-walk surfaced beyond the known r51/r53 three.) |
| `OptionalCreateTwoTokensOrSelfPump` (Terrapact Intimidator) | 1 (Terrapact Intimidator) | opponent-decision substrate |
| `SacExceptIfTapped` (Command Bridge sibling, dup of above) | (Command Bridge) | (counted once) |
| `ExileEachOpponentGYAndCreateToken` (Dauntless Scrapbot) | 1 (Dauntless Scrapbot) | exile-each-graveyard substrate + create-token sequence |

(Total cards listed in §2.6: 42, matching the headline.)

### 2.7 Faller's Faithful is a special case

Reads "destroy up to one other target creature. If that creature
wasn't dealt damage this turn, its controller draws two cards." Rust
has `DestroyTarget`; the conditional-draw clause needs
`damage-this-turn` tracking which Rust does not maintain. Counted
once under §2.6's "tail" rather than its own row.

---

## Section 3: Ranked gap-unlock count

Sorted by **cards unblocked per gap** (highest first). The merge /
scope column tags whether the gap is review-gated (on an unmerged
branch), a tiny bridge extension, or true new substrate.

| Rank | Gap | Cards unblocked | Scope status |
| --- | --- | --- | --- |
| 1 | **create_token bridge** (the base arm, regardless of token shape) | **13** | Review-gated on `feature/phase5-create-token-bridge`. Merge unblocks Honored Knight-Captain, Knight Luminary, Wedgelight Rammer, Galactic Wayfarer, Eusocial Engineering, Bioengineered Future, Biomechan Engineer, Biotech Specialist, Glacier Godmaw, plus existing Mechan Assembler / Kav Landseeker / Sunstar Expansionist (already partially probed). |
| 2 | **Predicate::Subject substrate** (multi-subject events + Subject(slot,inner)) | **9** | Review-gated on `feature/etb-subject-substrate`. Merge unblocks the predicate side of: Tezzeret, Mm'menon, Oreplate Pangolin, Eusocial Engineering, Genemorph Imago, Mightform Harmonizer, Remnant Elemental, Icecave Crasher, Seedship Agrarian (their effects still need separate arms — predicate is the precondition). |
| 3 | **DIES-event harness** (Event::Dies dispatch + harness pymethod) | **2 today; 8-10 expected** | Review-gated on `feature/dies-event-harness`. Today: Thawbringer, Cryogen Relic (LEAVES half). The branch also opens DIES-trigger probes against any creature that resolves a DIES trigger — broader EoE pool has more DIES-trigger cards beyond ENTERS. |
| 4 | **surveil bridge arm** | **3** | Tiny extension (Rust arm exists at `cards.rs:274`; bridge arm is ~10 LOC). Unblocks Starbreach Whale, Wurmwall Sweeper, Thawbringer-ETB-half. |
| 5 | **damage_any_target bridge arm** | **1 remaining** (Nebula Dragon + Debris Field Crusher probed) | **Landed in 5abe8958.** Pinnacle Kill-Ship probe is the remaining drop-in (creature-only target variant). |
| 6 | **mill (controller-self) bridge arm** | **3** | Tiny extension. Rust `Effect::Mill` exists. Unblocks Seedship Broodtender + parts of Fell Gravship + Icetill Explorer. |
| 7 | **put_plus_one_counter_on_creature_you_control bridge arm** | **3** | Tiny extension. Rust arm at `cards.rs:815`. Unblocks Rayblade Trooper ETB, Drix Fatemaker, plus tail. |
| 8 | **return_creature_from_graveyard_to_hand bridge arm** | **2** | Tiny extension. Rust unit-variant arm exists at `cards.rs:782`. Unblocks Interceptor Mechan + Fell Gravship suffix. |
| 9 | **pump_target_creature_until_eot bridge arm** | **2** | Tiny extension. Rust arm at `cards.rs:713`. Unblocks Sinister Cryologist, Dubious Delicacy. |
| 10 | **search_library_for_card bridge arm** | **2** | Tiny extension. Rust arm at `cards.rs:874`. Unblocks Starfield Shepherd, The Seriema. |
| 11 | **discard_self bridge arm** | **2** | Tiny extension. Rust arm at `cards.rs:412`. Unblocks Uthros Scanship, Melded Moxite. |
| 12 | each_opponent_discards bridge arm | 1 | Tiny extension. Virus Beetle. |
| 13 | each_opponent_sacrifices_creature bridge arm | 1 | Tiny extension. Susurian Dirgecraft. |
| 14 | look_top_n_put_one_in_hand_rest_to_graveyard bridge arm | 1 | Tiny extension. Codecracker Hound. |
| 15 | put_plus_one_counter_on_each_creature_you_control bridge arm | 1 | Tiny extension. Atmospheric Greenhouse. |
| 16 | put_plus_one_counter_on_each_of_up_to_N_target_creatures bridge arm | 1 | Tiny extension. Weftblade Enhancer. |
| 17 | pump_creatures_opponents_control_until_eot bridge arm | 1 | Tiny extension. Mouth of the Storm. |
| 18 | damage_to_opponent_creature bridge arm | 1 | Tiny extension. Nova Hellkite. |
| 19 | choose_one_mode bridge arm (+ self-counter arm) | 1 | Composite. Blade of the Swarm. |
| 20 | if_you_do bridge arm (+ discard_self) | 1 | Composite. Melded Moxite. |
| 21 | optional_sac_artifact_for_effect bridge arm | 1 | Composite. Larval Scoutlander. |
| 22 | sequence composer bridge arm | 0 (subsumed) | Already implied by Fell Gravship + Uthros Scanship; the per-arm gap is what gates them. |
| 23 | multi-event dispatcher (Enters OR Attacks) | 2 | New substrate. Syr Vondam, Haliya Ascendant Cadet. |
| 24 | Not(IsToken) / SubjectIsToken predicate | 1 | New substrate. Weapons Manufacturing. |
| 25 | various truly-new Rust Effect arms (per-card-unique, see §2.6) | ~~~30~~ **~13 (round-54 corrected)** | True new code. Round-19 list (kept verbatim): Astelli Reclaimer, Astrolithic / Spacecraft destroy-noncreature-then-AOE, Pain for All, Tractor Beam, Pulsar Squadron Ace, Lightstall Inquisitor, Famished Worldsire, Roving Actuator, Warmaker Gunship, Perigee Beckoner, Monoist Circuit-Feeder, Faller's Faithful, Command Bridge, Terrapact Intimidator, Selfcraft Mechan, Extinguisher Battleship, Dauntless Scrapbot, Genemorph Imago, Mightform Harmonizer, Remnant Elemental, Icecave Crasher, Seedship Agrarian (effect half), plus tail. **STALE — corrected round 54:** the round-54 full programmatic re-walk found the true honest count is **~13 distinct new-Rust-Effect asks**. Already effect-shipped + bridged (NOT in the ~13): Warmaker Gunship (r32), Monoist Circuit-Feeder (r51), Extinguisher Battleship effect-half (r52), Mightform Harmonizer (r31), Genemorph Imago `SetBasePTUntilEOT` (r18), Selfcraft Mechan (`OptionalSacArtifactForEffect` bridged), Terrapact Intimidator (`MayDo` bridged). Remnant Elemental = bridge-composition (not new Effect). The honest ~13: Lightstall Inquisitor, Command Bridge, Astelli Reclaimer, Perigee Beckoner, Pain for All, Dauntless Scrapbot, Faller's Faithful, Meltstrider's Resolve (Aura Fight), Roving Actuator (cast-copy half), Famished Worldsire (composition), Tractor Beam (composition), Pulsar Squadron Ace (Spacecraft sub-mode), Seedship Agrarian (landfall composer). See the round-54 re-walk section + `docs/residue_worklist.json`. |

**Headline takeaway from §3:** the three highest-yield gaps —
create_token bridge (13), Predicate::Subject substrate (9), DIES
harness (2 immediate + future) — are **all already on unmerged
branches awaiting review**. Merging them is the single highest-
leverage move available. After the merge, the next-highest gaps
(surveil, damage_any_target, mill, +1/+1 counter on target creature)
are all small bridge extensions in the 5-10 LOC range.

---

## Section 4: Strategic recommendations

### 4.1 Highest unlock-per-LOC: merge the three review-gated branches

The single highest-leverage action is merging the three branches
that already exist:

1. **`feature/phase5-create-token-bridge`** — unlocks 13 ETB-trigger
   cards (highest-volume single gap in the audit). The base arm
   exists; the only friction is per-token-shape parameterization
   (1/1 Soldier, 2/2 Robot, Lander, Munitions, copy-of-target). The
   first 5-6 cards unlock with the base arm alone.
2. **`feature/etb-subject-substrate`** — unlocks 9 cards' predicate
   gates (most of which still need an effect arm, but the predicate
   is the precondition). Foundation for every "Whenever ANOTHER X
   enters / a creature enters / an artifact enters" trigger.
3. **`feature/dies-event-harness`** — unlocks 2 immediate cards
   (Thawbringer, Cryogen Relic LEAVES half) plus opens the broader
   DIES-trigger probe surface.

Total immediate unlock from merging all three: **22 EoE cards move
from blocked to probe-eligible**. The next probe wave can pull from
this slate sequentially.

### 4.2 Bridge extensions on top of existing substrate (small, follow-on)

After the merge, the next probe wave should attack the small bridge
extensions in roughly this order (descending count):

1. **surveil** — 3 cards (Starbreach Whale, Wurmwall Sweeper,
   Thawbringer-ETB-half). Rust arm exists at `cards.rs:274`.
2. **damage_any_target** — 3 cards (parallel agent already in flight).
3. **mill (controller-self)** — 3 cards. Rust arm exists.
4. **put_plus_one_counter_on_creature_you_control** — 3 cards. Rust
   arm exists.
5. **return_creature_from_graveyard_to_hand** — 2 cards. Rust arm
   exists.
6. **pump_target_creature_until_eot** — 2 cards. Rust arm exists.
7. **search_library_for_card** — 2 cards. Rust arm exists.
8. **discard_self** — 2 cards (combine with if_you_do for Melded
   Moxite). Rust arm exists.
9. The single-card bridge arms (Virus Beetle, Mouth of the Storm,
   Nova Hellkite, etc.) — each adds 1 card per ~10 LOC extension.

Total addressable from bridge extensions alone (assuming Rust arms
already exist and are correct): **~25 additional cards**, bringing
the cumulative count to ~47 probed EoE ETB-trigger cards (just over
half of the 93-card pool).

### 4.3 True new substrate (larger, after the small wave)

After 4.1 + 4.2, the residue is ~42 cards needing genuinely new
Rust Effect arms or new substrate (multi-event dispatcher, dynamic
X-from-board-state, opponent-decision plumbing, damage-this-turn
tracking, etc.). These are best attacked from a different angle:
either build the recurring shapes first (the
`ExileTargetUntilSourceLeaves` family hits 5 cards;
`AttachSelfToTargetCreature` hits 4; landfall-with-complex-effect
hits 4) or pick them card-by-card as the strategic value warrants.

The `create-token` branch's per-token-shape parameterization
(Lander, Munitions, 2/2 Robot variants) is technically true-new but
should be considered Tier 1.5 — once the base arm merges, each new
shape is roughly 1 day of work for 1-3 cards.

### 4.4 Avoid the high-ceremony shapes early

Cards with truly novel substrate needs (Roving Actuator's `Void`
condition + exile-then-cast-copy; Pulsar Squadron Ace's
revelation-with-fallback; Lightstall Inquisitor's
cast-from-exile-with-cost-hike; Pain for All's self-propagating
damage) each require multiple new substrate pieces. Defer until the
high-yield gaps are closed — the marginal probe count per LOC is
strictly worse here.

---

## Section 5: Specific probe slate (if the three branches merge)

If the user merges `feature/phase5-create-token-bridge`,
`feature/etb-subject-substrate`, and `feature/dies-event-harness`,
the next 10 probes (chosen by "smallest delta from existing probe
shapes" — each adds at most one effect-arm parameter beyond what
the branches already wired):

1. **Honored Knight-Captain** — SourceIsSelf + CreateToken{1, 1/1 W
   Soldier}. First "1/1 Soldier" token-shape probe; sibling to
   Mechan Assembler's 2/2 Robot.
2. **Knight Luminary** — same as Honored Knight-Captain (SourceIsSelf
   + 1/1 W Soldier); pins the "warp also creates the same trigger"
   path.
3. **Wedgelight Rammer** — SourceIsSelf + CreateToken{1, 2/2 Robot}.
   Spacecraft variant; pins that create_token fires from
   Spacecraft-typed sources.
4. **Galactic Wayfarer** — SourceIsSelf + CreateToken{1, Lander}.
   First Lander-token probe (Lander = artifact with embedded
   activated ability; pins create_token doesn't choke on Lander
   subtype).
5. **Bioengineered Future** — SourceIsSelf + CreateToken{1, Lander}
   on an Enchantment source. Pins create_token fires from
   Enchantment-typed sources (different source-type than
   Wedgelight Rammer).
6. **Eusocial Engineering** — Subject(IsLand) AND ControlledByYou +
   CreateToken{1, 2/2 Robot}. Landfall + create_token combo; pins
   the etb-subject-substrate × create_token interaction.
7. **Glacier Godmaw** — SourceIsSelf + CreateToken{1, Lander} **plus**
   landfall trigger sibling. Two triggers on one card; pins the
   "card carries multiple triggered abilities" path.
8. **Thawbringer (DIES-half only — the ETB half needs surveil
   bridge)** — SourceIsSelf on Dies + Surveil{1}. The first surveil
   probe doubles as the first DIES-harness consumer beyond the
   Susurian Voidborn one already on the branch.
9. **Cryogen Relic (LEAVES half)** — SourceIsSelf on LeavesBattlefield
   + DrawCards{1}. Completes the half-probed card from main;
   draw_cards arm already wired.
10. **Tezzeret, Cruel Captain** — Subject(IsArtifact) AND
    ControlledByYou + (loyalty-counter on planeswalker source).
    First planeswalker-trigger probe; needs PW-loyalty-counter
    bridge work but stays within etb-subject-substrate's predicate
    scope.

After this slate (10 probes), the next wave is the small-bridge-arm
tier from §4.2 — starting with surveil (3 cards) and damage_any_target
(3 cards) hitting in parallel agent lanes.

---

## Appendix A: Methodology

- Source data: `data/edge_of_eternities.json` (266 EoE printings,
  Scryfall format).
- ETB-trigger filter (regex on `oracle_text`):
  - `\bwhen\b.*?\benters\b`
  - `\bwhenever\b.*?\benters\b`
  - `\blandfall\b`
- Each card's oracle text was manually mapped to a
  `(predicate, effect)` tuple by inspecting the existing Python
  `TriggeredAbility` definitions in `src/mtg_bot/cards/parser/`
  and the Rust `Effect`/`Predicate` enums in `rust/src/cards.rs`.
- Gap classification is the conjunction of:
  - Bridge gap: `_ta_dict_to_python_effect` in
    `src/mtg_bot/parity/cross_engine.py` does not list the
    effect-kind string.
  - Rust gap: no matching arm in the `Effect` enum.
  - Predicate gap: no matching arm in the `Predicate` enum on main.
  - Substrate gap: the trigger requires multi-subject events,
    multi-event dispatch, DIES-harness, or any plumbing beyond a
    single-source-single-subject Enters event.
- "Already probed" was cross-referenced against the list provided
  in the audit brief (b2bd233e on origin/main, approximately) and
  against the `probe(phase5):` commit subjects on `main`.

## Appendix B: Cards not in this audit

The 266 - 93 = **173 EoE printings without an `enters`-event
trigger** are out of scope. They include vanilla creatures, on-cast
triggers, activated-ability-only cards, and triggers on other
events (attacks-only, deals-damage-only, dies-only without ETB
sibling, etc.). The dies-only and attacks-only triggers will get
their own audit when the DIES-event harness merges and the
Attacks-event probe lane opens — the same gap-analysis structure
applies, just with a different denominator.

---

End of audit.
