# Phase 5 status & closure roadmap

Snapshot date: 2026-05-13 (late-evening wave end; ETB-trigger substrate
matured through Slices 4-11 + LTB fan-out, CE20 activated-abilities
substrate matured through Slices 1-7 + Walker A/B/C, controller-of-effect
inventory cascaded I59 -> I66, real-EoE production-card probes A-J all
clean on the cross-engine smoke).

**Punchline.** **The cross-engine smoke now exercises real-EoE
production cards with full ETB-trigger semantics** — token creation,
predicate algebra (`Or` / `And` / `Not` / `Subject` / `SubjectHasSubtype`),
subtype filters, `ControlledByYou` scopes (positive AND negative arms),
once-per-turn ledger, and Boolean composition under `And`. Eight+
real-EoE production-card probes (Germinating Wurm, Quantum Riddler,
Eumidian Terrabotanist, Mechan Assembler, Tannuk Memorial Ensign,
Kav Landseeker, Weftstalker Ardent, Haliya Guided by Light, plus
Mechan + Kav FULL real oracles via the create_token bridge) all
walked parity-clean on first contact. **Open CE count: still 0**
(third consecutive session). **Open G-gap count: still 1** (G8
multi-kind counter map, low priority). The remaining work to a
1000-game cross-engine smoke is bounded: ~15 controller-of-effect
arms in the same surgical I59 pattern, a small handful of substrate
widenings (compound effects in the trigger bridge, target-bearing
trigger effects, DIES-event harness path — the last is in flight
in a concurrent agent), and the one-slice carryovers (`spell_warped`
setter, `LookAtTopNRevealOrCounter` rewire, ManifestDread count>1,
coverage-overrides PR).

---

## 1. Where we are

### Numbers

- **80+ Rust `Effect` variants** in `rust/src/cards.rs` (today's wave
  was overwhelmingly substrate-shape work: `Predicate` algebra
  widening, `Event` enum fan-out, `ActivatedAbility` cost-shape
  extensions, controller-of-effect reader migrations — not new
  effect arms). The headline shape additions: `Predicate::Or`,
  `Predicate::SubjectHasSubtype`, `Predicate::SubjectIsLand /
  SubjectIsArtifact / SubjectIsCreature / ControlledByYou`,
  `Event::Dies / Cast / Attacks / Blocks / LeavesBattlefield`,
  `CardPrinting.subtypes`, `CardPrinting.starting_loyalty`,
  `ActivationCost.sacrifice_self / sacrifice_another_creature_or_artifact
  / sacrifice_a_land / sacrifice_another_artifact / sacrifice_food
  / sacrifice_a_desert / loyalty / requires_target_creature_you_control`,
  `ActivatedAbility.tier_threshold`, `GameObject.charge_counters /
  loyalty_counters`, `GameState.current_resolve_source_controller /
  loyalty_activated_this_turn / pending_etb_dispatches`.
- **74 / 228 Python Effect classes covered (32.5%)** — unchanged.
- **522 / 690 per-card emissions covered (75.7%)** — unchanged.
- **Frequency tiers** (`docs/RUST_EFFECT_COVERAGE.md`):
  - Freq >= 10 (head, 14 classes): **13 / 14 covered (92.9%)** —
    unchanged; `ModalChooseOne` still gated on the unmerged
    `feature/coverage-overrides` PR.
  - Freq 2-9 (mid, 53 classes): **52 / 53 covered (98.1%)** —
    unchanged.
  - Freq 1 singletons (161 classes): **9 / 161 (5.6%)** — explicitly
    out of Phase 5/6 scope.
- **Rust test gate**: **~2180 passing on main** (was 1914 at the
  evening snapshot 24h ago; **+266 today** across the late-evening
  + early-morning waves). Cumulative test-count delta breaks down
  roughly as: ETB-trigger Slices 4-11 (~80 new across the
  predicate-algebra extension + Event::Dies / Cast / Attacks /
  Blocks / LeavesBattlefield + LTB fan-out arms), CE20 follow-up
  Slices 2-7 + Walker A/B/C (~120 new across sacrifice_self,
  Spacecraft tier, Equipment-equip, mana_produced bridge, walker
  loyalty + once-per-turn + starting_loyalty, targeted-sacrifice,
  subtype-filtered sacrifice), controller-of-effect inventory
  I59-I66 (~50 new across DrawCards, GainLife, PendingDecisions,
  DamageEachOpponent, DealDamage, Mill, Sacrifice), subtypes
  substrate Slice 1+2 (~18 new), Predicate::Or substrate (~8 new),
  create_token bridge + Probes I/J (~6 new).
- **Cross-engine parity smoke**: **157 passing** (was 153 at
  evening snapshot, **+4 net new probes**: Probes D, E, F, G, H,
  I, J — covering real-EoE Mechan Assembler not-branch, Mechan
  once_per_turn, Tannuk DamageEachOpponent bridge, Weftstalker
  Or-substrate, Kav Landseeker HasSubtype, Haliya self-inclusive
  Or, plus the create_token bridge end-to-end on Mechan + Kav
  FULL real oracles).
- **ETB-trigger bridge tests**: **19 passing** (was 13 at evening
  snapshot, **+6**: create_token bridge arm pins covering
  happy-path, count default, missing-printings_by_pid raises,
  unknown-pid raises, Rust parser kind acceptance, end-to-end
  build_python_state wiring).
- **Python test gate**: ~10260+ passed (unchanged shape — Phase 5
  work this session was overwhelmingly Rust-side). No new
  strict-xfails. One pre-existing red unrelated to Phase 5:
  `test_no_orphan_rust_variants` (3 orphans pending the unmerged
  `feature/coverage-overrides` PR).

### Parity plan status (`docs/RUST_PARITY_PLAN.md`)

| Phase | Status |
|---|---|
| 0 Engine primitives | done (r1-r19) |
| 1 Discovery + scaffold | done (r20) |
| 2 Externalize RNG + spec GameState API | done (CE8 substrate + Effect-rng-threading both shipped) |
| 3 Action types + legal_decisions | done (r22-r25 + CE19 flash + instant-speed window extension) |
| 4a Top-14 high-frequency Effects | done modulo coverage-overrides PR merge |
| 4b Mid-frequency Effects (next ~50) | done modulo 1 singleton (52/53 shipped) |
| **5 Per-step trajectory diff** | **substantially advanced — all CEs surfaced through CE20 are closed; cross-engine smoke walks clean on 12+ keyword/composition surfaces + 8+ real-EoE production-card ETB probes; substrate matured through ETB Slices 1-11 + CE20 Slices 1-7 + Walker A/B/C + controller-of-effect inventory I59-I66** |
| 6 Scale to 1000 games | **partial — 1000/1000 clean multi-block combat smoke; 200/200 clean on every keyword surface + multi-keyword composition; 157/157 parity_smoke including all real-EoE ETB-trigger probes** |

### Late-evening substrate landings (compounded from evening snapshot)

The late-evening + early-morning waves shipped TWO multi-slice substrate
campaigns + a controller-of-effect inventory cascade + a real-EoE probe
parade. Each is a multi-merge campaign captured here at the level of the
substrate arc; per-slice details live in the per-merge `git log` body and
the corresponding `RUST_PARITY_GAPS.md` I-section.

**A. ETB-trigger substrate matured through Slices 4-11.** The evening
snapshot had Slices 1+2 landed; this wave extended the substrate
end-to-end:

- **Slice 4 — Predicate algebra widening**. Added `SubjectIsLand`,
  `SubjectIsArtifact`, `SubjectIsCreature`, `ControlledByYou`
  variants next to the Slice 1 atoms. Cross-engine bridge mirror in
  `_ta_dict_to_python_predicate`. 21 new tests.
- **Slice 5 — `Event::Dies` + dispatch on the SBA destroy site**
  (deferred queue, extra-observer for `SourceIsSelf`, 11 new tests).
- **Slice 6 — `Event::Cast` + dispatch on `cast_creature` site**
  (extra-observer for SourceIsSelf on the resolver pass, 8 new tests).
- **Slice 7 — `Event::Attacks` + dispatch on `declare_attacker`
  site** (per-attacker inline dispatch, 9 new tests).
- **Slice 8 — `Event::LeavesBattlefield` + dispatch on
  `move_object` / SBA destroy** (deferred queue, DIES+LEAVES
  dual-fire LIFO pin documenting the trigger-order contract, 9
  new tests).
- **Slice 9 — `Event::Blocks` + dispatch on `declare_blocker`
  site** (per-blocker inline dispatch symmetric to Slice 7;
  single-subject divergence from Python's multi-subject BLOCKS
  fan-out documented, 9 new tests).
- **Slice 10 — LTB fan-out to 13 Effect-arm bf-exit sites in
  `state_ops_resolve.rs`** + 1 sacrifice-cost path in
  `state_ops_actions.rs` (defer-past-pop drain pattern, 6 new
  tests).
- **Slice 11 — LTB fan-out on `DestroyAllCreatures` (Wrath)
  Effect arm** (closes 14th LTB-silent arm, 5 new tests).

Plus the **etb_effects -> triggered_abilities bridge** (Slice 3
substrate from the prior wave): legacy `etb_effects: Vec<Effect>`
now bridges to `triggered_abilities` at parse time + `cross_engine.py`
`printing_dict` wires `triggered_abilities` through. Invariant I49.

**B. CE20 activated-abilities substrate matured through Slices 2-7 +
Walker A/B/C.** The evening snapshot had Slice 1 landed; this wave
shipped the full follow-up campaign:

- **Slice 2 — `ActivationCost.sacrifice_self: bool`** + dispatch
  (mana -> tap -> sacrifice -> effect). I52 closure.
- **Slice 3 — Spacecraft `tier_threshold` gate** on
  `ActivatedAbility` + `GameObject.charge_counters` tracker. I53
  closure.
- **Slice 4 — Equipment-equip `ActivateAbility` target-pick
  substrate** (`requires_target_creature_you_control` cost flag +
  StackItem payload-target threading). I54 closure.
- **Slice 5 (A) — Walker loyalty signed cost** + counter slot +
  emission gate + Phase 3b/5d apply pipeline + SBA pass at
  loyalty <= 0. I56 closure.
- **Slice 5 (C) — Walker loyalty once-per-turn ledger** per
  CR 606.3 (`loyalty_activated_this_turn: HashSet<(u8, u32)>`).
  I57 closure.
- **Walker starting_loyalty ETB seeding** (`CardPrinting.starting_loyalty:
  i32` + `seed_starting_loyalty_for_etb` helper wired at 4 bf-entry
  call sites). I58 closure.
- **Slice 6 — Targeted-sacrifice cost variants** (`sacrifice_another_creature_or_artifact`,
  `sacrifice_a_land`, `sacrifice_another_artifact` on
  `ActivationCost`). I55 closure.
- **Slice 7 — Subtype-filtered sacrifice variants**
  (`sacrifice_food`, `sacrifice_a_desert`; rides the
  `CardPrinting.subtypes` substrate). I62 closure.
- **Legacy `mana_produced` -> `ActivatedAbility` bridge** (parse-time
  synthesis into `ActivatedAbility { is_mana_ability: true, cost:
  { tap_self: true }, effect: AddManaToPool(...) }`; legacy
  emission + apply branches retired). I51 closure.
- **Auto-tap-from-lands composer in emission affordability** via
  `auto_tap_headroom_pool`. I50 closure.

**C. Controller-of-effect inventory cascaded I59 -> I66.** The pattern
landed at I59 (DrawCards) and propagated as a surgical one-arm-at-a-time
inventory:

- **I59** — `Effect::DrawCards` (introduced the
  `state.current_resolve_source_controller: Option<u8>` transient
  slot + `apply_effect_pub_with_controller` helper variant + 4
  swap sites in the stack resolver).
- **I60** — `Effect::GainLife` (reuses I59 slot).
- **I61** — Pending-decision push sites + dispatchers (`MayDo`,
  `IfYouDo`, `ChooseOneMode`, `Surveil`, `LookTopN`,
  `ManifestDread`, `OptionalManaCost`, `LookAtTopN`; 8 push-site
  arms + 11 dispatcher sites; `apply_effect_pub_with_controller`
  becomes live with 11 real callers; `#[allow(dead_code)]`
  retired).
- **I62** — `ActivationCost.sacrifice_food / sacrifice_a_desert`
  (subtype-filtered sacrifice variants, see B above).
- **I63** — `Effect::DamageEachOpponent` (defender = `1 - controller`).
- **I64** — `Effect::DealDamage` (defender = `1 - source_controller`
  via the same slot; both `AnyPlayer` and `AnyCreature` match arms
  routed uniformly).
- **I65** — `Effect::Mill` self-mill (milling player from
  `current_resolve_source_controller`).
- **I66** — `Effect::Sacrifice` you-sacrifice (sacrificing player
  from `current_resolve_source_controller`).

**D. Subtypes + predicate-algebra widening substrate.** Two
back-to-back lanes landed early in the wave:

- **`CardPrinting.subtypes: Vec<String>`** field + parser + getter
  + three direct-construction fixture sites filled (Forest / Bears /
  Elves) + `cross_engine.py` passthrough + 8 new tests. Slice 1.
- **`Predicate::SubjectHasSubtype(String)`** consumer (mirrors
  Python's `Subject(None, HasSubtype('Kavu'))` from
  `triggers.py:1198`). 10 new tests. Slice 2.
- **`Predicate::Or(Box<Predicate>, Box<Predicate>)`** — the last
  missing Boolean connective in the trigger predicate algebra
  (mirrors `Predicate::And` exactly). 8 new tests. Unblocked
  Weftstalker + Haliya probes.
- **`CardDef.extra_card_types` + `CardDef.supertypes`** substrate
  extensions on the Python side, enabling the `create_token`
  bridge to faithfully reproduce Robot (Artifact+Creature) +
  Lander (Artifact-only) token shapes.

**E. `create_token` bridge arm + Probe I/J real-oracle probes.**
The `_ta_dict_to_python_effect` translator now mirrors Rust's
`Effect::CreateToken` parser. Required a two-pass `build_python_state`
construction (first pass empty triggers so `printings_by_pid` is
fully populated; second pass `dataclass.replace` with materialized
triggers via the bridge). 6 new bridge-translation pins. Two
real-EoE probes lit up: **Mechan Assembler FULL real oracle**
(replaces Probe E's GainLife stand-in with the REAL create_token
effect — Predicate::Not + once_per_turn ledger + CreateToken
together on real-EoE-printed text; first cross-engine probe whose
effect materializes a permanent rather than bumping life/counters)
and **Kav Landseeker FULL real ETB** (closes the deferred half
from Probe H — pure Artifact Lander token, no Creature card_type,
no P/T). Bridge arm coverage now wide enough for the dominant EoE
ETB-token shapes (Robot + Lander).

### Cross-engine divergences surfaced + closed this wave

**None.** Third consecutive session with zero open CE divergences.
The 9-probe real-EoE production-card parade (Germinating Wurm,
Quantum Riddler, Eumidian Terrabotanist, Mechan Assembler not-branch,
Mechan once_per_turn, Tannuk DamageEachOpponent, Weftstalker Or,
Kav Landseeker HasSubtype, Haliya self-inclusive Or, Mechan FULL
oracle, Kav FULL ETB) all walked parity-clean on the first try.
The probe-close-substrate cadence didn't surface a single CE21+;
the substrate from the evening wave plus the controller-of-effect
inventory closures are absorbing every production-card surface
the probes have driven at.

### Cross-engine deltas vs the 2026-05-12 evening-wave snapshot

- **Open CE count: 0** (sustained, third consecutive session). No
  CE21+ has surfaced despite 8+ real-EoE production-card probes.
- **Open G-gap count: 1** (G8 multi-kind counter map, unchanged
  priority).
- **Highest invariant: I66** (Sacrifice controller-of-effect) — was
  I48 at the evening snapshot. Today added I49 (etb_effects ->
  triggered_abilities bridge), I50 (auto_tap_headroom_pool), I51
  (mana_produced bridge), I52 (sacrifice_self), I53 (Spacecraft
  tier_threshold), I54 (Equipment-equip), I55 (targeted-sacrifice),
  I56 (Walker loyalty signed cost), I57 (once-per-turn-per-walker
  ledger), I58 (starting_loyalty ETB seed), I59 (DrawCards
  controller), I60 (GainLife controller), I61 (pending-decision
  controllers), I62 (subtype-filtered sacrifice), I63
  (DamageEachOpponent controller), I64 (DealDamage controller),
  I65 (Mill controller), I66 (Sacrifice controller).
- **New invariants beyond the I-series**: `Predicate::Or`,
  `Predicate::SubjectHasSubtype`, `Event::Attacks / Blocks /
  LeavesBattlefield` enum widenings, `CardPrinting.subtypes`,
  `CardPrinting.starting_loyalty`, `GameObject.charge_counters /
  loyalty_counters`, `GameState.loyalty_activated_this_turn /
  current_resolve_source_controller / pending_etb_dispatches`,
  `CardDef.extra_card_types / supertypes`. These ship as
  substrate fields each pinned by their own test surface.

### What's running cleanly end-of-wave

- All single-color / two-color synthetic deckspecs through full
  multi-turn play with land drops + creature casts + combat.
- `multi_blocker_deckspec` with `multi_block_combat_selector`:
  1000/1000 clean games.
- `multi_blocker_deckspec` with retaliation + all eleven
  single-keyword side-channels + the three multi-keyword
  composition shapes (LL+DT, FS+DT, T+LL): 200/200 clean.
- `multi_blocker_deckspec` with counterspell + activated-mid-combat
  + activated-cost: clean.
- Cross-engine flash + instant-speed legal_decisions parity
  (post-CE19): set-equal across engines.
- ETB-trigger substrate end-to-end on production EoE cards:
  - **Germinating Wurm**: `SourceIsSelf` + `GainLife(2)`.
  - **Quantum Riddler**: `SourceIsSelf` + `DrawCards(1)`.
  - **Eumidian Terrabotanist**: `Subject(IsLand) AND
    ControlledByYou` + `GainLife(1)` (Landfall — first SUBJECT-vs-
    SOURCE probe).
  - **Mechan Assembler (not-branch)**: `Subject(IsArtifact) AND
    ControlledByYou AND Not(IsSelf)` + `GainLife(1)`.
  - **Mechan Assembler (once_per_turn)**: same predicate +
    `once_per_turn=True` ledger end-to-end.
  - **Mechan Assembler FULL real oracle**: same predicate +
    `CreateToken(Robot)` (first materializing-permanent probe).
  - **Tannuk Memorial Ensign**: `Subject(IsLand) AND
    ControlledByYou` + `DamageEachOpponent(1)` (first bridge
    extension beyond DrawCards/GainLife).
  - **Weftstalker Ardent**: `And(And(Or(IsCreature, IsArtifact),
    ControlledByYou), Not(IsSelf))` + `DamageEachOpponent(1)`
    (first real-card consumer of `Predicate::Or`).
  - **Kav Landseeker (Or substrate prep)**: `Subject(HasSubtype('Kavu'))
    AND ControlledByYou` + `GainLife(1)` (first real-card consumer
    of `Predicate::SubjectHasSubtype`).
  - **Kav Landseeker FULL real ETB**: `SourceIsSelf` +
    `CreateToken(Lander)` (pure Artifact token shape).
  - **Haliya Guided by Light**: `And(Or(SubjectIsCreature,
    SubjectIsArtifact), ControlledByYou)` + `GainLife(1)`
    (self-inclusive Or — no outer `Not(IsSelf)` gate; pins
    ControlledByYou's negative arm on the Or-substrate path).

---

## 2. What's left

### Open G-gaps in `RUST_PARITY_GAPS.md`

| Gap | Description | Status | Slice scope | Priority |
|---|---|---|---|---|
| **G8** | +1/+1 and -1/-1 counters stored as net `i32`, cancel at write-time not SBA | unchanged — needs multi-kind counter map; G9 bundles in the matching snapshot getter | medium | **low** (no pool card asks the divergence question) |

That's it for open gameplay-divergence gaps. The remaining G-entries
(G5 / G9 / G13 / G16 / G17 / G18) are parity invariants documented
under the `Confirmed gaps` heading for forward-debugging context, not
real divergences.

### Open CE-gaps

**None.** CE1-CE20 all closed; third consecutive session with no
CE21+ surfacing despite 8+ real-EoE production-card probes.

### Substrate deferrals still open

The substrate stack is now small and well-bounded:

- **Controller-of-effect inventory remainder** (~15 arms). The
  I59 transient-slot pattern is now load-bearing for I60 / I61 / I63 /
  I64 / I65 / I66. Remaining arms in `state_ops_resolve.rs` that still
  read `state.active_player` for "you"-keyed semantics:
  `DealDamageAnyTarget`, `DealDamageEqualToSourcePowerAnyTarget`,
  `DealDamageEachCreature`, `DealDamageToOpponentCreature`,
  `PumpCreaturesYouControl*` variants, search-zone resolvers
  (`SearchLibraryForBasicLandTapped`, `SearchLibraryForCreatureCard`,
  etc.), `CreateToken` (latent — see worklog forward note), and a
  handful of other "your"-keyed arms. Each is the same one-line
  reader migration + 4-6 test regression block + I-section doc add —
  surgical, predictable, no architectural surprises expected.
  Estimate: ~15 small slices.
- **Compound effects in the trigger bridge** (Gap A from the
  Susurian Voidborn forward note). Today's `_ta_dict_to_python_effect`
  returns one Effect; widening to Sequence-style compound effects
  (e.g. `{"kind": "sequence", "effects": [...]}`) is a substrate
  slice in itself. Blocks Voidborn's "target opponent loses 1 life
  AND you gain 1 life" composed effect, Auxiliary Boosters'
  "create token + attach self" Equipment shape, and any future
  multi-effect-per-trigger card.
- **Target-bearing trigger effects** (Gap B from the Voidborn
  forward note). Python's `TargetOpponentLosesLife.resolve` requires
  a non-empty `targets` tuple picked at trigger-push time by
  `controller.agent.choose_target` (actions.py:3249); none of
  today's parity_smoke harness probes use agent-driven target
  selection. Rust's arm auto-picks at resolve-time so works
  trivially. Needs harness-side substrate to drive a synthetic agent
  for target picks on the Python side.
- **DIES-event harness path** (Gap C from the Voidborn forward
  note). `register_and_inject_object` only fires `Event::Enters`
  (`state_ops_resolve.rs:6589` — `entered_id` is None for non-bf
  injects; only bf-injects fan out the ENTERS dispatch). To fire
  `Event::DIES` we'd need either a `register_inject_then_destroy`
  helper, or a public `kill_object_and_dispatch_dies` surface. **In
  flight** in a concurrent agent (substrate addition on `state.rs` /
  `state_ops_resolve.rs` + bridge). Unblocks every dies-trigger
  probe in EoE (Susurian Voidborn, Tannuk's necrogen rider, etc.).
- **ETB-trigger Slices 4+ per-card variant coverage**. The
  predicate-algebra widening this wave covered the canonical shapes
  (`IsLand`, `IsArtifact`, `IsCreature`, `ControlledByYou`,
  `HasSubtype`, `Or`, `Not`, `And`). The audit-doc remaining
  templates include `IsLand+Controlled+~IsSelf`,
  `HasSubtype('Kavu')+ControlledByYou`, etc. — most are already
  reachable via current atoms; new templates surface as new probes
  exercise them.
- **`spell_warped_this_turn` flag setter**. Unchanged — the bool
  field lives on `GameState` but no Rust production call site flips
  it yet. Without it, `Effect::ConditionalIfVoid` is shipped but
  not load-bearing for the 4 EoE Void cards. Fix scope: small
  (warp-cast cost path single-site). Priority: medium — only when
  a probe drives a Void card.
- **ManifestDread face-down state + count > 1 deferrals**.
  Priority: medium-low.
- **`Effect::EquipToTargetCreatureYouControl` `granted_keywords_ueot`
  rider** (Atomic Microsizer family always passes empty frozenset).
  Will be revisited once a concrete Equipment-equip probe demands it.
- **`Effect::LookAtTopNRevealOrCounter` "random order" tail** —
  unblocked by Effect-rng-threading (state.rng is plumbed); a
  one-Effect-arm rewire follow-up.
- **CE20 follow-up tail**: sorcery-speed gate (CR 605.1a),
  compound `sacrifice_another_artifact_or_land`, room_half /
  sieged-saga shapes, multi-target sacrifice, Ragost's static
  Layer-4 "artifacts are Foods" conferral (needs effective_subtypes
  pass). All small, each lands as a real-card probe demands it.
- **Token-creation bridge extensions** (forward note from the
  create_token bridge worklog): `tapped` flag on `CreateToken`
  parser (Gravpack Monoist's "TAPPED 2/2 Robot"); compound
  `create_token_and_attach_self` for Auxiliary Boosters'
  Equipment-attach-to-own-token; cross-controller controller-of-effect
  on CreateToken (currently `state.active_player`).
- **Delayed-trigger ledgering** (Tannuk's "second-time-this-turn"
  rider, Kav's "sacrifice-at-next-end-step"). Same shape as the
  once-per-turn ledger but counted/scheduled rather than binary.
  Unblocks Tannuk's FULL oracle and any "second/third/Nth time
  this turn" card.

### High-frequency Effects still missing

Per `RUST_EFFECT_COVERAGE.md`, the only remaining freq>=10 class is:

| Python class | Frequency | Status |
|---|---:|---|
| `ModalChooseOne` | 13 | functionally shipped as `Effect::ChooseOneMode`; gated on `feature/coverage-overrides` PR merge to flip the orphan-map entry |

The freq 2-9 tier is at **52/53 (98.1%)** — the one remaining class
is the lone freq-2 long-tail miss; not load-bearing for the current
cross-engine smoke.

### Singletons (freq 1)

Explicitly **out of Phase 5/6 scope** per `RUST_PARITY_PLAN.md`
"Phasing" §3 (161 classes, 5.6% covered).

---

## 3. Recommended closure sequence

The wave landed the two biggest substrate ports the evening snapshot
flagged + drained ~8 controller-of-effect arms from the I59 inventory.
The remaining work is now overwhelmingly the I59-pattern controller
cleanup + a small handful of bridge/harness substrate widenings.

Ordered by leverage:

1. **Drain the controller-of-effect inventory remainder** (~15 arms).
   Each is the same surgical pattern: ~1 line in the Effect arm
   (`let x = state.current_resolve_source_controller.unwrap_or(state.active_player);`),
   ~4-6 regression tests, ~1 I-section invariant. Predictable
   blast radius, predictable cadence. The cluster (I59 / I60 / I63 /
   I64 / I65 / I66) is now the canonical pattern; future workers
   pattern-match cleanly. Highest leverage now — closes the entire
   active_player-keyed family before any future cross-controller
   probe surfaces a divergence.

2. **DIES-event harness path** (in flight). Unblocks Susurian
   Voidborn and every other dies-trigger probe in EoE. Pre-stamps
   the substrate for a likely-fruitful probe lane (the EoE pool
   has ~20 dies-trigger cards untouched).

3. **Compound effects in the trigger bridge** (Sequence-style
   `_ta_dict_to_python_effect` widening). Unblocks Voidborn's
   composed effect + Auxiliary Boosters' Equipment-attach shape +
   future multi-effect-per-trigger cards. Modest substrate scope.

4. **Target-bearing trigger effects** (synthetic agent for
   target-pick on Python side). Unblocks any probe whose Python
   `Effect::resolve` requires `targets` tuple at trigger-push time.

5. **CreateToken `tapped` flag + cross-controller controller-of-effect**.
   Two small bridge widenings. Unblock Gravpack Monoist's "TAPPED
   2/2 Robot" and any opponent's-ETB-token-resolves-on-your-turn
   parity case.

6. **Phase 5 probes — production-card surface deepening**. The
   probe surface is now rich enough to support targeted
   substrate-pre-stamping. Probe targets that will likely surface
   CE21+ (if any remain to surface):
   - **Dies-trigger probes** once DIES-event harness lands (Susurian
     Voidborn, Tannuk's necrogen rider, etc.).
   - **Auxiliary Boosters** real oracle once compound-effect
     bridge lands (Equipment + create_token + attach_self).
   - **Possibility Technician** ('this creature or another Kavu
     you control enters, exile top of library') — needs
     `Or(SourceIsSelf, And(SubjectHasSubtype('Kavu'),
     ControlledByYou))` + `exile_top_of_library` effect.
   - **Spacecraft probes** — exercises the I53 charge-counter +
     tier_threshold substrate on a real production printing.
   - **Modal spells** — `ModalChooseOne` / `Effect::ChooseOneMode`
     interaction with cross-engine smoke. Requires the
     coverage-overrides merge to land first to avoid orphan-test
     red.

7. **`spell_warped_this_turn` flag setter.** Single-site addition
   on the warp-cast cost path. Closes the Void-cards substrate gap.

8. **`LookAtTopNRevealOrCounter` "random order" tail.**
   One-Effect-arm rewire on the now-plumbed `state.rng`.

9. **ManifestDread face-down + count>1.** Substrate choice.
   Priority medium-low.

10. **G8 multi-kind counter map.** Low priority until a pool card
    asks the divergence question.

11. **`feature/coverage-overrides` PR merge.** User-gated. Not
    blocking any closure.

---

## 4. What "ready to test" means concretely

The plan doc's target is **1000-game cross-engine smoke clean**.
This wave is the **fourth inflection point** on this estimate.

Estimate evolution:
- 2026-05-11 morning: **80-85% remaining** (pre-CE2 closure).
- 2026-05-11 mid-day: **60-70%** (post-CE3 + multi-turn walk).
- 2026-05-11 end-of-day retro: **60-70%** (CE5 surfaced).
- 2026-05-12 mid-day: **45-55%** (CE9 + CE11 closed, CE12 surfaced).
- 2026-05-12 afternoon-wave: **20-30%** (CE13-CE18 all closed; G12 /
  G19 / G24 closed).
- 2026-05-12 evening: **15-25% remaining**.
- **End-of-late-evening 2026-05-13: 10-20% remaining.**

**Rationale for 10-20%:**

1. **Two major substrates landed end-to-end + load-bearing.** ETB-trigger
   substrate Slices 4-11 (predicate algebra, Event enum fan-out, LTB
   fan-out, etb_effects -> triggered_abilities bridge) AND CE20
   activated-abilities substrate Slices 2-7 + Walker A/B/C (sacrifice_self,
   Spacecraft tier, Equipment-equip, mana_produced bridge, walker
   loyalty + once-per-turn + starting_loyalty, targeted-sacrifice,
   subtype-filtered sacrifice). Both substrates were the two biggest
   unknowns 48h ago; both are now end-to-end with real-EoE probes
   walking parity-clean.
2. **8+ real-EoE production-card probes all clean.** Germinating
   Wurm, Quantum Riddler, Eumidian Terrabotanist, Mechan Assembler
   (3 probe variants — not-branch, once_per_turn, FULL oracle with
   real CreateToken), Tannuk Memorial Ensign, Weftstalker Ardent,
   Kav Landseeker (HasSubtype + FULL ETB), Haliya Guided by Light.
   The substrate is validating against PRODUCTION card data, not
   synthetic deckspecs. This is the strongest signal in the wave.
3. **Zero open CE divergences, third consecutive session.** Despite
   the production-card probe parade, no CE21+ has surfaced. The
   substrate from the evening + late-evening waves is absorbing
   every shape the probes drive at.
4. **Only ~15 controller-of-effect arms remaining**, same surgical
   I59 pattern across all of them. Each is ~1 line + ~4-6 tests +
   ~1 invariant. Total slice count ~15; cadence is now
   pattern-matched, not exploratory.
5. **Only G8 remains open** — the hardest remaining gap but also
   the lowest priority (no pool card asks the question).
6. **The remaining risk is concentrated in three small substrate
   widenings**: (a) compound effects in the trigger bridge, (b)
   target-bearing trigger effects (harness-side synthetic agent),
   (c) DIES-event harness path (in flight). All three are bounded
   scope, none architectural surprises.

**Velocity bound.** Today's late-evening + early-morning wave drained
~8 controller-of-effect arms (I59 -> I66), shipped ETB Slices 4-11 +
CE20 Slices 2-7 + Walker A/B/C, and merged 8+ real-EoE probes — in
~24h of autonomous parallel-lane work. The cadence is sustained and
predictable.

**Realistic projection: 2-3 more sessions to 1000-game-ready**,
depending on:

- Whether new EoE-specific probes surface unexpected divergences
  once compound-effect / target-bearing-trigger / delayed-trigger
  substrates land (Susurian Voidborn, Auxiliary Boosters, etc.).
- Whether the controller-of-effect inventory drain (~15 arms)
  surfaces any non-pattern-matching arm (unlikely — the cluster
  I59 / I60 / I63 / I64 / I65 / I66 all fit the same shape).
- Whether the real-deck-pool 1000-game smoke (vs synthetic deckspec
  + targeted-probe injection) surfaces a new CE class once it's
  exercising production cards end-to-end. The current probes inject
  targeted cards into a synthetic frame; the real-deck-pool smoke
  is the next-largest unknown.

The main risks (revised down from the evening snapshot): (a) the
compound-effect trigger bridge widening may surface a parser-side
shape mismatch on Python's multi-effect Susurian Voidborn case;
(b) the DIES-event harness landing may surface ordering edge cases
(DIES+LEAVES dual-fire LIFO is pinned at the synthetic-test level
but hasn't been exercised on a real-card cross-engine probe yet);
(c) the real-deck-pool 1000-game smoke is the largest remaining
unknown — it's where any unprobed CE class would surface.

---

## 5. Forward-looking items beyond Phase 5

Out of scope of Phase 5 and Phase 6 (unchanged):

- **The 161 singleton Effect classes** — explicitly excluded from
  the parity deck pool. The 1000-game smoke uses a "core-effects-
  only" pool by construction.
- **Layered continuous-effect cache** — Rust has no analog today.
  May get pulled forward if future Predicate-template probes require
  observation of layered-granted keywords (e.g. a flying grant +
  a "when a creature with flying enters" trigger composition).
  Ragost's static "artifacts are Foods" Layer-4 conferral is also
  a candidate (needs effective_subtypes pass merging static-conferred
  subtypes with printed subtypes).
- **Full combat damage assignment edge cases** — current Rust covers
  basics + multi-block + deathtouch-no-trample + trample-multi-block +
  double-strike spillover + LL+DT / FS+DT / T+LL compositions. The
  probe surface is clean. Real combat edge cases past today's
  surface — protection, shadow / fear / intimidate, banding (out
  of scope per pool), and multi-step trigger chains within combat
  damage — are Phase 7+.
- **Stack timing on multi-level trigger chains** — Slices 1-11
  cover the simple cases plus LTB fan-out + DIES+LEAVES dual-fire
  LIFO + once-per-turn ledger gating + deferred-dispatch queue.
  Deep trigger-chain ordering across multiple layers of conditional
  triggers, plus delayed-trigger ledgering (Tannuk's second-time-
  this-turn, Kav's sacrifice-at-next-end-step), are
  next-largest known unknowns. Tannuk's delayed-trigger rider
  is the canonical first consumer once that substrate lands.
- **Token-creation replacement effects** (Anointed-Procession-shape
  doubling) — latent on synthetic CE-bridge probes; parity contract
  unchanged when present.
- **Counterspell parity** — `Effect::CounterTargetSpell` shipped
  + cross-engine probe walks clean. Future surfaces: uncounterable
  spells, counter-target-spell-with-mana-cost-X (X is zero on the
  stack), and counter-target-then-do-something.

**Review queue**: `feature/coverage-overrides` PR (`2bcdd842`,
pushed 2026-05-11) remains unmerged. Required to flip
`test_no_orphan_rust_variants` green and have
`RUST_EFFECT_COVERAGE.md` read the 3 orphan-mapped variants
(`ChooseOneMode`, `GrantKeywordToTargetCreatureUntilEOT`,
`SetBasePTUntilEOT`) as covered. Not blocking any Phase 5 closure,
but it's the persistent pre-existing red on every Python gate.
