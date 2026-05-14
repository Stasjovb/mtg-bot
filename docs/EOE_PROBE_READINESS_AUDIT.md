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

## Current state (as of 2026-05-14, main `39d01c02`) — round-19 refresh

Headline inventory measured directly off `main` at round-19 refresh
time. Supersedes both the round-10 refresh (was at `ebb5c6ec`) and
the §1 table below (last recomputed at `a2755769`, now ~22 slices
and 9 rounds ago).

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
| `LandfallWithComplexEffect` (Glacier Godmaw, Mightform Harmonizer, Genemorph Imago, Seedship Agrarian, Remnant Elemental — 5 cards) | Predicate substrate (Subject family) ALREADY SHIPPED via `feature/etb-subject-substrate`; **Glacier Godmaw landfall lander-token PROBED on main** (`test_cross_engine_real_eoe_glacier_godmaw_etb_create_lander_artifact_token_leviathan_carrier_parity`) | Per-card effect arms differ: Mightform Harmonizer needs new `Effect::DoubleTargetPowerUntilEOT` (true new Rust). Genemorph Imago landfall = compose existing `SetBasePTUntilEOT` (round 18) with landfall predicate (bridge follow-up). Remnant Elemental = compose existing `PutPlusOneCounterOnSelf` + Subject predicate (bridge composition). Seedship Agrarian needs a new arm. **2 of 5 are bridge-only**, 1 PROBED, 2 still need true new Rust. |
| `Roving Actuator` void-style exile-then-cast-copy | `Effect::ConditionalIfVoid { then_effect, else_effect }` at `cards.rs:2045` (parser at `cards.rs:4203`) | Void condition substrated. Exile-then-cast-copy still needs new Rust. **Partial unblock** (the trigger shell can lift; the cast-copy effect is the residual gap). |
| `Famished Worldsire` look-X-and-put-lands-tapped | `Effect::DealDamageEqualToSourcePowerAnyTarget` at `cards.rs:1269` shows the X-from-source-power pattern exists; `Effect::SearchLibraryForBasicLandTapped { count }` at `cards.rs:217` exists for the lands-tapped half | Specific "look-X-then-put-lands-tapped" composition needs new Rust, but the X-plumbing pattern is unblocked. **Partial unblock.** |
| `Tractor Beam` TapEnchantedYouControlAndDontUntap | `Effect::TapEnchantedPermanent` at `cards.rs:1476` (parser at `cards.rs:3686`) | Tap-enchanted substrated. Control-swap + don't-untap composition still needs new Rust. **Partial unblock.** |
| `DestroyNoncreatureThenAOEDamage` (Extinguisher Battleship — 1 card) | `Effect::DestroyTargetNonlandPermanent` at `cards.rs:635`; `Effect::DamageEachCreature` at `cards.rs:145`; `Effect::Sequence` at `cards.rs:872` | All component arms substrated! Bridge has `sequence` already; missing `destroy_target_nonland_permanent` and `damage_each_creature` arms. **Could move to BLOCKED-BRIDGE-ARM** with two bridge-arm slices + one composition probe. (Conservatively kept in BLOCKED-RUST-EFFECT for now since the audit didn't enumerate the component arms; flagging for follow-up.) |
| `CreateLanderToken` parameterized family (13 cards in §2.6) | `Effect::CreateToken { count, token_printing_id }` at `cards.rs:154`; `Effect::CreateTokenCopyOfTargetCreatureYouControl` at `cards.rs:1355` | Create-token base SHIPPED + multiple lander-token printings already PROBED via per-card slices (Galactic Wayfarer, Bioengineered Future, Biomechan Engineer, Biotech Specialist, Glacier Godmaw, plus the Honored Knight-Captain / Knight Luminary / Wedgelight Rammer subset from §2.3). The remaining BLOCKED set in this row is much smaller than 13 — closer to **5 cards** for the unprobed token shapes (Auxiliary Boosters with attach, Dauntless Scrapbot with exile-each-gy, Infinite Guideline Station, Sunstar Expansionist, Terrapact Intimidator with may_do). |

### Truly BLOCKED-RUST-EFFECT residue (confirmed no Rust arm)

| §2.6 entry | Status |
| --- | --- |
| `TapTargetAndPutStunCounter` (Mechanozoa, Cryogen Relic activated half — 2 cards) | No StunCounter substrate in Rust. Confirmed BLOCKED-RUST-EFFECT. |
| `DoubleTargetPowerUntilEOT` (Mightform Harmonizer — 1 card) | No Rust arm. Confirmed. |
| `CastFromExileWithCostHike` (Lightstall Inquisitor — 1 card) | No Rust arm. Confirmed. |
| `SacUnlessYouTap` (Command Bridge — 1 card) | No Rust arm. Confirmed (first land-ETB in audit). |
| `ReturnPermanentCardWithMVXorLessFromGY` (Astelli Reclaimer — 1 card) | No mana-value-condition GY-return arm in Rust. Confirmed. |
| `DealDamageToAnyTargetEqualToArtifactCount` (Warmaker Gunship — 1 card) | No X-from-artifact-count plumbing. Adjacent `DealDamageEqualToSourcePowerAnyTarget` exists (different denominator) but artifact-count specifically needs its own arm. Confirmed. |
| `PumpAndGrantDiesReturnTrigger` (Perigee Beckoner — 1 card) | No nested-trigger-grant substrate. Confirmed. |
| `TwoMobileSubjects` (Monoist Circuit-Feeder — 1 card) | No simultaneous-two-target substrate. Confirmed. |
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
| `TapTargetAndPutStunCounter` (stun-counter substrate) | 2 (Mechanozoa, Cryogen Relic activated half) | no stun-counter shape in Rust today |
| `LandfallWithComplexEffect` (landfall predicate + non-trivial effect) | 4 (Glacier Godmaw, Mightform Harmonizer, Genemorph Imago, Seedship Agrarian, Remnant Elemental) | predicate is in etb-subject-substrate; effect arms (mass-pump + vigilance/haste, double-power-EOT, set-base-PT, +1/+1 counter on self via landfall) need new Rust arms |
| `SetBasePTUntilEOT` | 1 (Genemorph Imago) | Rust has `SetBasePTUntilEOT` arm; no bridge or trigger-driven wiring |
| `Fight` (creature-vs-creature) | 1 (Meltstrider's Resolve) | bare bilateral form shipped (`Effect::FightTargetCreatureWithTargetCreature` + bridge + `FightTargetCreatureWithTargetCreature` Python sibling); Aura-shape (Meltstrider's Resolve specifically — source fighter is the Aura's `attached_to` enchanted creature) is the deferred follow-up — needs new `Effect::EnchantedCreatureFightsTarget` Rust variant routing through `attached_to` end-to-end. See SEARCH_LIMITATIONS.md "Fight" entry |
| `DoubleTargetPowerUntilEOT` | 1 (Mightform Harmonizer) | no Rust arm |
| `OptionalDiscardThenDraw` (Melded Moxite-shape `if_you_do`) | 1 (Melded Moxite — also counted in §2.4) | Rust has `IfYouDo`; just needs bridge arm |
| `OptionalSacrificeArtifactForCounterAndDraw` (Selfcraft Mechan) | 1 (Selfcraft Mechan) | nested optional-sac + counter + draw; partly in Rust |
| `ExileGraveyardCastFromExile` (Roving Actuator void-style) | 1 (Roving Actuator) | needs `Void` trigger condition + exile-then-cast-copy substrate |
| `LookXAndPutLandsTapped` (Famished Worldsire) | 1 (Famished Worldsire) | X = source power; no Rust arm |
| `CastFromExileWithCostHike` (Lightstall Inquisitor) | 1 (Lightstall Inquisitor) | "each opponent exiles a card from their hand and may play it; +1 cost; lands enter tapped" — no Rust substrate |
| `SacUnlessYouTap` (Command Bridge) | 1 (Command Bridge) | "sacrifice it unless you tap an untapped permanent" — no Rust arm; first land-ETB in the audit |
| `ReturnPermanentCardWithMVXorLessFromGY` (Astelli Reclaimer) | 1 (Astelli Reclaimer) | needs mana-value-condition substrate on the GY-return arm |
| `ChoiceTrigger` (Pulsar Squadron Ace look-5-reveal-Spacecraft) | 1 (Pulsar Squadron Ace) | revelation + put-into-hand-OR-counter-on-self path |
| `DealDamageToAnyTargetEqualToArtifactCount` (Warmaker Gunship) | 1 (Warmaker Gunship) | X-from-artifact-count needs dynamic-X plumbing |
| `PumpAndGrantDiesReturnTrigger` (Perigee Beckoner) | 1 (Perigee Beckoner) | grants a *new* DIES trigger on the target — needs nested-trigger substrate |
| `TwoMobileSubjects` (Monoist Circuit-Feeder) | 1 (Monoist Circuit-Feeder) | targets one of yours and one of theirs simultaneously |
| `EachOpponentExilesFromHand` (Lightstall Inquisitor) | 1 | (also above) |
| `EnchantedDealsDamageThenPropagate` (Pain for All) | 1 (Pain for All) | self-replicating damage shape; no Rust arm |
| `TapEnchantedYouControlAndDontUntap` (Tractor Beam) | 1 (Tractor Beam) | tap + control-swap + don't-untap composition |
| `DestroyNoncreatureThenAOEDamage` (Extinguisher Battleship) | 1 (Extinguisher Battleship) | sequence with mass-damage component |
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
| 25 | various truly-new Rust Effect arms (per-card-unique, see §2.6) | ~30 | True new code. Spread across Astelli Reclaimer, Astrolithic / Spacecraft destroy-noncreature-then-AOE, Pain for All, Tractor Beam, Pulsar Squadron Ace, Lightstall Inquisitor, Famished Worldsire, Roving Actuator, Warmaker Gunship, Perigee Beckoner, Monoist Circuit-Feeder, Faller's Faithful, Command Bridge, Terrapact Intimidator, Selfcraft Mechan, Extinguisher Battleship, Dauntless Scrapbot, Genemorph Imago, Mightform Harmonizer, Remnant Elemental, Icecave Crasher, Seedship Agrarian (effect half), plus tail. |

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
