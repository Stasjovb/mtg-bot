# Phase 5 status & closure roadmap

Snapshot date: 2026-05-12 (evening-wave end; CE19 + CE20 both closed,
ETB-trigger substrate Slices 1+2 landed, activated_abilities substrate
Slice 1 landed, five additional cross-engine probes walked clean —
counterspell, flash (pre-CE19 close), indestructible, defender-only
target arms regression, activated-abilities-mid-combat, cost-paying
activated abilities, and multi-keyword composition).

**Punchline.** **TWO new substrates landed in a single session** — ETB
triggers (Slices 1+2: Event / Predicate / TriggeredAbility /
dispatch_event + queue-based fan-out across all 11 bf-entry stamping
sites) and CE20's activated_abilities (CardPrinting.activated_abilities
Vec + cost-pay dispatch + per-ability emission gate). Both were
documented as multi-slice campaigns 24h ago; both got their
architectural ports today. Total LOC delta for the two substrates:
~1,700+ production + ~1,000+ tests. **Open CE count: still 0** — CE19
(flash + instant-speed legal_decisions) and CE20 (cost-paying activated
abilities) each surfaced and closed in the same session via probe →
substrate → closure-pin cadence. **Open G-gap count: still 1** (G8
multi-kind counter map, low priority — no pool card asks the question).
The cross-engine smoke now walks clean on every keyword surface tested
plus multi-keyword composition (LL+DT, FS+DT, T+LL). The remaining work
to a 1000-game cross-engine smoke is bounded: a handful of ETB-trigger
follow-up slices (Slice 3 in flight, Slices 4+ for predicate templates
and per-card variants), the activated_abilities follow-up slices
(Spacecraft / planeswalker / equipment / sacrifice), and the small
substrate stack already documented (spell_warped setter,
LookAtTopNRevealOrCounter rewire, ManifestDread count>1).

---

## 1. Where we are

### Numbers

- **80 Rust `Effect` variants** in `rust/src/cards.rs` (unchanged from
  the afternoon snapshot — today's substrate work was structural:
  ETB-trigger primitives + ActivatedAbility / ActivationCost structs
  + CardPrinting.activated_abilities + CardPrinting.triggered_abilities
  fields). Note: ETB triggers added a `StackItemKind` discriminant and
  `TriggerPayload` to `StackItem`; CE20 Slice 1 added the
  `ActivatedAbility` walk + `pool_can_cover` affordability helper +
  `pay_mana_cost_pub` cost-pay primitive. Neither is a new `Effect`
  variant.
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
- **Rust test gate**: **1914 passing on main** (was 1874 at the
  afternoon-wave snapshot; **+40 today** across the evening-wave:
  CE19 closure (+4 Rust regression tests), ETB-trigger Slice 1
  (+11 substrate-smoke tests), ETB-trigger Slice 2 (+14 per-RS-site +
  once-per-turn-ledger tests), CE20 Slice 1 (+12 substrate-smoke
  tests), plus assorted updates to pre-existing tests). Python's
  `tests/test_parity_smoke.py` extends to 141 passing on the
  parity-smoke side (counterspell + flash + activated-mid-combat +
  activated-cost + multi-keyword + ETB additions).
- **Python test gate**: ~10260+ passed / 10-12 skipped / 0-2 xfailed
  depending on slice. No remaining strict-xfails as of end-of-evening
  — CE19's pre-closure pair-pin retired with its closure; CE20's two
  load-bearing pre-closure shape-pins flipped to closure pins. One
  pre-existing red unrelated to Phase 5: `test_no_orphan_rust_variants`
  (3 orphans pending the unmerged `feature/coverage-overrides` PR).

### Parity plan status (`docs/RUST_PARITY_PLAN.md`)

| Phase | Status |
|---|---|
| 0 Engine primitives | done (r1-r19) |
| 1 Discovery + scaffold | done (r20) |
| 2 Externalize RNG + spec GameState API | done (CE8 substrate + Effect-rng-threading both shipped) |
| 3 Action types + legal_decisions | done (r22-r25) — plus tonight's flash + instant-speed window extension for CE19 closure |
| 4a Top-14 high-frequency Effects | done modulo coverage-overrides PR merge |
| 4b Mid-frequency Effects (next ~50) | done modulo 1 singleton (52/53 shipped) |
| **5 Per-step trajectory diff** | **substantially advanced — all CEs surfaced through CE20 are closed; cross-engine smoke walks clean on 12+ keyword/composition surfaces and 1000/1000 clean on multi-block** |
| 6 Scale to 1000 games | **partial — 1000/1000 clean multi-block combat smoke; 200/200 clean on every keyword surface + multi-keyword composition (LL+DT, FS+DT, T+LL)** |

### New substrate landings tonight

The evening wave's headline is two substrate ports that each were
catalogued as multi-slice campaigns at the afternoon snapshot:

- **ETB-trigger substrate Slice 1** (merge `8f0a7adf`, ~715 LOC
  production + ~459 tests). Added `Event` enum (Enters wired; Dies /
  Cast / Attacks / DealsDamage declared, parser raises on unwired
  events), `Predicate` algebra (Always / SourceIsSelf / SourceIsCreature
  / Not / And — minimum for the canonical IsSelf shape AND the
  Panharmonicon-shape probe), `TriggeredAbility { event, predicate,
  effect, once_per_turn }` struct, `CardPrinting.triggered_abilities:
  Vec<TriggeredAbility>` field, `StackItemKind` discriminant + new
  `TriggerPayload` on `StackItem`, `GameState.triggered_this_turn:
  HashSet<(u32, u32)>` ledger cleared at cleanup, `dispatch_event`
  walker over `bf_iter_etb_sorted` with `push_triggered_ability`
  emission, and trigger-resolution arm in `resolve_top_of_stack` /
  `_pause` that fires the effect via `apply_effect` and pops without
  routing the source. Wiring is one site: cast-resolve fires
  `dispatch_event(Event::Enters, source_id)` AFTER the legacy inline
  `etb_effects` loop AND AFTER popping the resolving spell.
- **ETB-trigger substrate Slice 2** (merge `e7b491f3`, ~440 LOC
  production + ~360 tests). Fanned out `dispatch_event(ENTERS)` to the
  remaining 11 bf-entry ETB-stamping sites (RS2-RS12 per the audit) via
  a deferred-dispatch queue: `GameState.pending_etb_dispatches: Vec<u32>`
  + `state_ops_resolve::drain_pending_etb_dispatches` helper that
  loops `mem::take` + `dispatch_event` until quiescent (handles
  re-entrant ETB chains). Pattern was load-bearing: a naive
  push-trigger-during-apply broke 14 counterspell tests because the
  resolver's pop drained the freshly-pushed trigger instead of the
  resolving slot — the queue resolves it by draining AFTER the
  resolving slot leaves the stack. Sites covered:
  `SearchLibraryForBasicLandTapped`, reanimation (single + mass),
  `CreateToken`, `CreateTokenCopyOfTargetCreatureYouControl`,
  `return_paired_exiles_for` (sig flipped to PyResult), test
  `register_and_inject_object` (bf-target only), `move_object` (sig
  flipped), `move_object_from_graveyard_to_battlefield`,
  `move_from_hand_to_battlefield` (covers play_land + cast_creature
  no-stack), `resolve_manifest_dread_to_battlefield`. 14 new
  regression tests in `tests_rust/test_triggers.py`. Invariant I47
  pins the queue substrate + per-RS-site coverage.
- **CE20 activated_abilities substrate Slice 1** (merge `f0fd4492`,
  ~556 LOC production + ~404 tests; closure pin + I48 doc add ~280
  more). Added `ActivationCost { mana: ManaCost, tap_self: bool }`
  + `ActivatedAbility { cost, effect, is_mana_ability }` structs +
  `CardPrinting.activated_abilities: Vec<ActivatedAbility>` field
  with parser default = empty Vec for back-compat. Rewrote
  `state_ops_actions.rs` ActivateAbility apply arm into a six-phase
  pipeline (locate → resolve shape → cost-pay precheck → pay mana
  → commit tap → dispatch effect), with `is_mana_ability=true`
  bypassing the stack (CR 605.3a) and `is_mana_ability=false`
  pushing a `StackItem::new_trigger`. Updated `state_ops_legal.rs`
  emission to walk BOTH paths: legacy `mana_produced` one-shot
  emission (back-compat) AND per-ability walk over
  `activated_abilities` with tap_self filtering + pool affordability
  via the new `pool_can_cover` helper. Invariant I48 pins the
  substrate. **Slice 1 is bounded** — the Spacecraft station-charge,
  planeswalker loyalty, equipment equip, sacrifice-as-cost,
  mana_produced bridge, and auto-tap-from-lands composer follow-ups
  are explicitly out of scope and queued for later slices.

### Cross-engine divergences surfaced + closed this evening

Probe-close-probe cadence continued at speed. Two CEs surfaced and
closed same-session:

- **CE19** (Rust's `legal_decisions` ignored flash + instant-speed
  CastSpell window entirely; Python emitted CastSpell at p1's main
  with p0 priority for a Bear Flash in p0's hand). SURFACED via
  `feature/phase5-flash` (merge `9f6ff2ed`). CLOSED via
  `feature/ce19-flash-instant` (merge `82f0cad1`). The fix moved
  CastSpell emission ABOVE the sorcery-timing short-circuit and
  split it into two passes sharing a single seen_castspell HashSet:
  pass 1 (instant-speed) above the gate emits for `is_instant ||
  keywords.contains("flash")`, pass 2 (sorcery-speed) after PlayLand
  emits for non-Land non-Instant non-flash cards. CR backing: 117.1
  + 307.1 (instants) + 702.13a (flash) + 305.1 (lands special
  action) + 117.1c (sorcery timing). 4 new Rust regression tests
  pin the four corners of the timing × flash × type matrix.
  Invariant I46 added.
- **CE20** (Rust's `legal_decisions` and ActivateAbility dispatch
  ignored non-mana activated abilities entirely — cost-paying
  activated abilities had no representation in Rust's CardPrinting;
  Python emitted ActivateAbility for a Bear Caster's `{1}{G}, T:
  Draw a card`, Rust did not). SURFACED via
  `feature/phase5-activated-cost` (merge `8ad2cf94`). CLOSED via
  `feature/ce20-activated-substrate` (merge `f0fd4492`) — see the
  substrate landing notes above. Closure flipped 2 load-bearing
  cross-engine shape-pins from "Rust does NOT emit" to closure
  pins (`test_a_emission_parity_post_ce20_closure`,
  `test_c_apply_dispatch_parity_post_ce20_closure`); Test D kept as
  the subtler-axis pin (Python doesn't self-gate, Rust does, raise
  message updated to `unaffordable from controller's mana pool`).
  Invariant I48 added.

### Phase 5 probes that walked clean tonight (no novel CE)

Five additional probes extended the cross-engine smoke and walked
parity-clean:

- **counterspell** (CR 701.5) — merge `dee9cc72`. Two engines reach
  identical observable end-state via DIFFERENT mechanisms (Python
  flips `StackItem.countered=True`; Rust's `Effect::CounterTargetSpell`
  routes target to gy inline in the counter's own resolve loop).
- **activated-mid-combat** — merge `8d9e1d8f`. Both engines apply the
  same `_is_sorcery_timing` emission gate AND the same no-phase-gate
  dispatch arm AND I20 mana-pool-empty-on-phase-boundary; activated-
  ability-mid-combat axis composes parity-clean across all three
  substeps the brief targeted.
- **multi-keyword composition** (LL+DT, FS+DT, T+LL) — merge
  `04e7c910`. Three composition surfaces pinned: LL+DT — lifelink
  fires on the LITERAL damage event (not the deathtouch-upgraded
  mark); FS+DT — deathtouch-upgraded blocker dies in FS substep,
  CE18-closure alive-predicate drops back-damage in regular pass;
  T+LL — trample-spill-to-defender fires lifelink on both the
  blocker entry AND the spilled-to-defender entry. The eleven
  single-keyword surfaces + the multi-keyword composition surface
  are now all parity-clean.

Plus: **ETB-trigger probe via Slice 1's substrate-smoke** validated
the canonical IsSelf draw-on-cast-resolve shape AND the
Panharmonicon-shape probe (`SourceIsCreature AND NOT SourceIsSelf`
observing a vanilla bait creature's ETB and drawing). **Activated-cost
probe** surfaced CE20 which closed same-day via the substrate landing.

### Cross-engine deltas vs the 2026-05-12 afternoon-wave snapshot

- **Open CE count: 0** (sustained from afternoon). CE19 + CE20 each
  surfaced + closed same-day. No CE21+ has surfaced.
- **Open G-gap count: 1** (sustained from afternoon). G8 remains the
  lone surviving open G, low priority — no pool card asks the
  multi-kind-counter-stack divergence question.
- **Highest invariant: I48** (CE20 substrate) — was I45 at the
  afternoon snapshot. Today added I46 (CE19 flash gate), I47 (ETB
  substrate per-RS-site coverage), I48 (activated_abilities
  substrate).
- **New audit doc**: `docs/RUST_ETB_TRIGGER_AUDIT.md` (775 LOC,
  7 sections + appendix). Wrote the file:line map for every Python
  ETB dispatch site, every Rust ETB-stamping site (RS1-RS12), and
  the Slice 1 / Slice 2 / Slice 3+ plan that the evening's substrate
  ports executed against. Slice 1 and Slice 2 completion notices
  are folded inline.

### What's running cleanly end-of-evening

- All single-color / two-color synthetic deckspecs through full
  multi-turn play with land drops + creature casts + combat.
- `multi_blocker_deckspec` with `multi_block_combat_selector`:
  1000/1000 clean games.
- `multi_blocker_deckspec` with `retaliation_selector` (bilateral
  combat): 260+ decisions clean.
- `multi_blocker_deckspec` with each of eleven keyword side-channel
  selectors layered onto retaliation: 200/200 decisions clean.
- `multi_blocker_deckspec` with multi-keyword side-channel
  (LL+DT, FS+DT, T+LL composition): 200/200 decisions clean.
- `multi_blocker_deckspec` with counterspell + activated-mid-combat
  + activated-cost (post-CE20-closure) side-channels: clean.
- Cross-engine flash probe at p1's main with p0 priority: post-CE19,
  CastSpell emission set-equal across engines.
- ETB-trigger substrate: canonical IsSelf draw-on-cast-resolve +
  Panharmonicon-shape Witness Drone observing vanilla bait creature
  + once-per-turn ledger end-to-end (RS8 self-fire + RS10 suppressed
  + cleanup reset + RS10-after-cleanup re-fires).

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

**None.** CE1-CE20 all closed. CE21+ has not surfaced.

### Substrate deferrals still open

- **ETB-trigger Slice 3+** (in flight as of this writing in a
  concurrent agent on `rust/src/cards.rs` + `rust/src/state_ops_resolve.rs`
  + `src/mtg_bot/parity/cross_engine.py` + possibly
  `docs/RUST_PARITY_GAPS.md`). Slice 3 piece is the bridge from the
  legacy inline `etb_effects` hatch into the predicate path: synthesize
  `TriggeredAbility { event: Enters, predicate: SourceIsSelf, effect:
  ... }` per `etb_effects` entry at registry-load time, then retire
  the inline hatch in `resolve_top_of_stack` / `_pause`. Slices 4+
  cover per-predicate-template coverage for the ~10-15 distinct
  predicate templates in `src/mtg_bot/cards/parser/triggers.py:603-1266`
  (Subject+IsLand+Controlled, Subject+IsArtifact+Controlled+~IsSelf,
  HasSubtype('Kavu'), etc.) + smoke-harness `cross_engine.py:370-384`
  registry-dict wiring. Slice N adds Panharmonicon-shape
  `etb_trigger_multiplier`. Estimated 5-8 slices total (Slices 1+2 of
  that 5-8 landed today), 2-3 more sessions per the audit doc.
- **CE20 follow-up slices**. Slice 1 covers the cost-pay /
  emission / dispatch substrate for `tap_self` + mana cost. Each of
  the following lands with its dispatch primitive in lockstep:
  - Spacecraft station-charge (charge counters as cost,
    `tier_threshold` gate on `effective_activated_abilities`).
  - Planeswalker loyalty (counters-as-cost, distinct from mana;
    needs `pay_loyalty` cost primitive).
  - Equipment equip (specific cost shape + target).
  - Sacrifice-as-cost (`sacrifice_self`, `sacrifice_another_*`,
    `sacrifice_a_land`, `sacrifice_food`).
  - Tap-an-untapped-permanent-you-control (Gene Pollinator shape).
  - Activation-gate predicates (`requires_*` Bonders' Enclave).
  - Bridging legacy `mana_produced` into a synthesized
    `ActivatedAbility { is_mana_ability: true, cost: { tap_self:
    true }, effect: AddManaToPool(...) }` entry (retires the
    side-channel).
  - Auto-tap-from-lands composer to match Python's `can_pay_cost`
    headroom accounting on the Rust side.
- **`spell_warped_this_turn` flag setter**. Unchanged — the bool field
  lives on `GameState` but no Rust production call site flips it yet
  (`feature/warp-flag-substrate` documents the gap, merge `72264b63`).
  Without it, `Effect::ConditionalIfVoid` is shipped but not
  load-bearing for the 4 EoE Void cards. Fix scope: small (warp-cast
  cost path single-site). Priority: medium — only when a probe drives
  a Void card.
- **ManifestDread face-down state + count > 1 deferrals** (unchanged
  since 2026-05-11). Priority: medium-low.
- **`Effect::EquipToTargetCreatureYouControl` `granted_keywords_ueot`
  rider** (Atomic Microsizer family always passes empty frozenset).
  Unchanged. Will be revisited once equipment-cost activation lands
  (CE20 follow-up Slice).
- **`Effect::LookAtTopNRevealOrCounter` "random order" tail** —
  unblocked by Effect-rng-threading (state.rng is plumbed); a
  one-Effect-arm rewire follow-up.

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

Tonight's wave landed the two biggest substrate ports the afternoon
snapshot called out as multi-slice. The remaining work is now
predominantly bounded follow-ups on those substrates, plus the small
one-slice stack carried over from the afternoon.

Ordered by leverage:

1. **Finish the ETB-trigger campaign.** Slice 3 (in flight) bridges
   legacy `etb_effects` into the predicate path. Slices 4-N cover
   per-predicate-template coverage and the smoke-harness registry-dict
   wiring. Each Slice is small-to-medium scope (the audit estimates
   ~30-50 LOC + ~30-50 test LOC per predicate template); ~75% of the
   ETB-trigger campaign remains in those follow-ups. Once Slice 3
   lands, a deeper Panharmonicon-shape probe should surface a
   production EoE printing's ETB and exercise the predicate path
   end-to-end through the cross-engine smoke.

2. **Continue the CE20 follow-up slices as needed.** Slice 1 covers
   `{cost-mana, tap_self}` cost shapes for the draw-a-card-from-creature
   axis pinned today. Each follow-up below is a concrete, bounded
   slice — they land independently as production EoE printings flow
   through the cross-engine smoke:
   - Spacecraft station-charge (charge-counter cost + tier_threshold
     gate). Probably first up because EoE has Spacecraft printings.
   - Planeswalker loyalty (counters-as-cost + `pay_loyalty`).
   - Equipment equip (specific cost shape + target).
   - Sacrifice-as-cost (multiple variants).
   - Bridge legacy `mana_produced` into synthesized
     `ActivatedAbility` entries (retires the side-channel; structural
     unification rather than feature add).
   - Auto-tap-from-lands composer.

3. **Continue Phase 5 probes — event-driven surface deepening.** The
   keyword + counterspell + flash + activated-ability surfaces are
   well-exercised. Probe targets that will likely surface CE21+:
   - **ETB-trigger composition probes** (rides Slice 2's substrate;
     ETB-trigger Slice 3 bridge will further unlock this) — inject
     a creature with a "when ~ enters, draw a card" oracle text and
     verify both engines fire the trigger.
   - **Three-keyword combos** (vigilance + lifelink + trample on an
     attacker that survives combat; menace + first_strike + lifelink
     for a defensive single-blocker setup).
   - **Flash + counterspell interaction** — instant-speed flash creature
     gets counterspelled at off-active priority window. Exercises both
     the CE19-closure timing gate AND the counterspell mechanism.
   - **Modal spells** — `ModalChooseOne` / `Effect::ChooseOneMode`
     interaction with cross-engine smoke. Requires the coverage-
     overrides merge to land first to avoid orphan-test red.

4. **`spell_warped_this_turn` flag setter.** Unchanged. Single-site
   addition on the warp-cast cost path. Closes the Void-cards
   substrate gap.

5. **`LookAtTopNRevealOrCounter` "random order" tail.** Unchanged.
   One-Effect-arm rewire on the now-plumbed `state.rng`.

6. **ManifestDread face-down + count>1.** Unchanged scope. Priority
   medium-low.

7. **G8 multi-kind counter map.** Unchanged. Low priority until a
   pool card asks the divergence question.

8. **`feature/coverage-overrides` PR merge.** Unchanged. User-gated.
   Not blocking any closure.

**One-slice vs substrate-prep summary** (revised):

- One-slice closures remaining: `spell_warped` setter,
  `LookAtTopNRevealOrCounter` rewire, ManifestDread count>1,
  coverage-overrides merge.
- Medium scope: ETB-trigger Slice 3 (in flight), each ETB-trigger
  per-predicate-template Slice (4+), each CE20 follow-up Slice
  (Spacecraft / planeswalker / equipment / sacrifice / mana_produced
  bridge / auto-tap composer), ManifestDread face-down (substrate
  choice), G8 (multi-kind counter map).
- **No remaining cross-engine CE divergences for the second
  consecutive session.** CE21+ would have to come from a probe
  extension; current evidence suggests the keyword-on-printing
  surface + the static-ability-and-cost surface are exhausted, and
  the next CE will come from a deeper substrate axis (ETB
  composition with predicate templates, modal spells, or
  Spacecraft-specific cost shapes).

---

## 4. What "ready to test" means concretely

The plan doc's target is **1000-game cross-engine smoke clean**.
Tonight is a third inflection point on this estimate.

Estimate evolution:
- 2026-05-11 morning: **80-85% remaining** (pre-CE2 closure).
- 2026-05-11 mid-day: **60-70%** (post-CE3 + multi-turn walk).
- 2026-05-11 end-of-day retro: **60-70%** (CE5 surfaced).
- 2026-05-12 mid-day: **45-55%** (CE9 closed, CE11 closed, CE12
  surfaced).
- 2026-05-12 afternoon-wave: **20-30%** (CE13-CE18 all closed; G12 /
  G19 / G24 closed).
- **End-of-evening 2026-05-12: 15-25% remaining.**

**Rationale for 15-25%:**

1. **Zero open CE divergences, second consecutive session.** Every CE
   surfaced through CE20 is closed. CE19 + CE20 each surfaced and
   closed same-session, sustaining the probe → substrate → close
   cadence on a surface that 24h ago was documented as
   substrate-blocked (the ETB-trigger audit doc predicted CE19 as
   "Panharmonicon-shape, substrate-blocked, not one-slice"; tonight
   closed it AND landed the substrate).
2. **Two new substrates landed in a single session.** ETB triggers
   (Slices 1+2) and CE20 activated_abilities (Slice 1). The two
   substrates were the two largest unknowns at the afternoon snapshot;
   their landing materially compresses forward risk.
3. **Cross-engine smoke walks clean on every keyword surface + the
   multi-keyword composition surface.** Twelve+ single-keyword
   surfaces and three composition shapes (LL+DT, FS+DT, T+LL) all
   byte-identical.
4. **The substrate stack is small and well-defined.** ETB-trigger
   Slice 3 (in flight), ETB-trigger Slices 4+ (per-predicate-template),
   CE20 follow-up Slices (Spacecraft / planeswalker / equipment /
   sacrifice / bridge / auto-tap), `spell_warped` setter,
   `LookAtTopNRevealOrCounter` rewire, ManifestDread count>1,
   coverage-overrides PR. Every entry has a concrete shape and a
   bounded LOC estimate.
5. **Only G8 remains open** — and it's the hardest remaining gap
   (multi-kind counter map) but also the lowest priority (no pool
   card asks the question).
6. **The remaining risk is concentrated in two surfaces.** (a) The
   ETB-trigger Slices 4+ surface — Predicate templates for the
   ~10-15 distinct shapes in Python's trigger parser; each Slice
   could surface a CE in the predicate matching or the bf-iter
   ordering. (b) The CE20 follow-up surface — Spacecraft /
   planeswalker / equipment / sacrifice cost shapes each have their
   own dispatch primitive and could surface CEs at the cost-pay /
   emission edge.

**Velocity bound.** Tonight's evening wave closed 2 CEs + landed 3
substrate slices (ETB Slices 1+2, CE20 Slice 1) + 5 clean probes in
one session. The probe-close cadence is sustained; the substrate
ports are unusually high yield (the multi-slice campaigns the
afternoon snapshot called out are now 25-50% complete after a single
session). **Realistic projection: 2-4 more sessions to 1000-game-
ready**, depending on:

- How many CE21+ surfacings come from ETB-trigger production
  deployment (Slice 3 bridge will start exercising the predicate path
  against real EoE printings — that's where the audit-doc
  Panharmonicon-shape probe will actually fire).
- Whether CE20 follow-up Slices uncover their own architectural
  surprises (Spacecraft station-charge is a likely first surface
  given EoE has Spacecraft printings; charge-counter cost shape may
  surface a cost-pay primitive gap).
- Whether the cross-engine smoke surfaces new divergences once it's
  exercising production EoE printings (vs synthetic deckspec). The
  current probes inject targeted creatures into a synthetic deckspec;
  the real-deck-pool smoke is the next-largest unknown.

The main risks (revised down from the afternoon snapshot): (a) the
ETB-trigger Slice 4+ Predicate templates may surface a
layered-continuous-effect requirement for triggers that observe
keyword-granted permanents (e.g. "when a creature with flying enters"
gates on the layered flying-grant); (b) Spacecraft station-charge's
charge-counter cost may not compose cleanly with the I48 pool-only
affordability gate, surfacing a counter-cost primitive gap; (c) the
modal-spells probe (ModalChooseOne / ChooseOneMode) is still
untouched and likely to surface its own CE class.

---

## 5. Forward-looking items beyond Phase 5

Out of scope of Phase 5 and Phase 6 (unchanged):

- **The 161 singleton Effect classes** — explicitly excluded from
  the parity deck pool. The 1000-game smoke uses a "core-effects-
  only" pool by construction.
- **Layered continuous-effect cache** — Rust has no analog today.
  Per parity plan risks §3, missing layered logic for anthems /
  pump-UEOT / become-creature effects becomes a silent-wrong-answer
  source as those cards enter the pool. Layer 6 (lose all abilities)
  and Layer 7 (P/T) are the most common; Layer 1-5 rarer. UEOT
  modifiers get us partway but the full layer engine is Phase 7+.
  May get pulled forward if ETB-trigger Slice 4+ Predicate templates
  require observation of layered-granted keywords (e.g. a flying
  grant + a "when a creature with flying enters" trigger composition).
- **Full combat damage assignment edge cases** — current Rust covers
  basics + multi-block + deathtouch-no-trample (CE14) + trample-
  multi-block (CE15) + double-strike spillover (CE18) + the
  composition surfaces pinned tonight (LL+DT, FS+DT, T+LL). The
  probe surface for plain first-strike, vigilance, lifelink, haste,
  menace, defender, indestructible, flying, hexproof, and the three
  composition shapes is all clean. Real combat parity edge cases
  past today's surface — protection, shadow / fear / intimidate,
  banding (out of scope per pool), and multi-step trigger chains
  within combat damage — are Phase 7+.
- **Stack timing on multi-level trigger chains** — Slices 1+2 cover
  the simple cases (single-trigger fire-and-resolve, once-per-turn
  ledger gating, deferred-dispatch queue for re-entrant chains).
  Deep trigger-chain ordering across multiple layers of conditional
  triggers, plus the trigger emitter substrate for non-ETB events
  (Dies / Cast / Attacks / DealsDamage are declared in the enum but
  unwired) are next-largest known unknowns. The audit-doc estimate
  is 5-8 slices total for the full ETB-trigger campaign; Slices 1+2
  landed today.
- **Counterspell parity** — `Effect::CounterTargetSpell` is shipped;
  tonight's counterspell probe walked clean. Future surfaces:
  uncounterable spells, counter-target-spell-with-mana-cost-X (X is
  zero on the stack), and counter-target-then-do-something.

**Review queue**: `feature/coverage-overrides` PR (`2bcdd842`,
pushed 2026-05-11) remains unmerged. Required to flip
`test_no_orphan_rust_variants` green and have
`RUST_EFFECT_COVERAGE.md` read the 3 orphan-mapped variants
(`ChooseOneMode`, `GrantKeywordToTargetCreatureUntilEOT`,
`SetBasePTUntilEOT`) as covered. Not blocking any Phase 5 closure,
but it's the persistent pre-existing red on every Python gate.
