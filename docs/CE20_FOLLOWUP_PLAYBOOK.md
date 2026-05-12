# CE20 follow-up playbook

Pre-staged closure plan for the FOUR follow-up campaigns the CE20 Slice 1
substrate (`f0fd4492` merge) explicitly deferred, plus the TWO "bridge"
follow-ups the Slice 1 agent flagged in its report (`2026-05-12-ce20-activated-substrate`
worklog entry). Synthesises file:line work-item maps the way the CE5/CE6/CE7
playbook (`2a7221b1`) did — one place a slice author can read top-to-bottom
without re-deriving anything from the I48 invariant or the substrate commits.

This doc deliberately repeats the substrate shape — the value is having one
artifact a slice author opens, reads, and executes from.

**Status when this doc was written (2026-05-12, post-`18ca1527`):**

- CE20 Slice 1 substrate landed in `f0fd4492`. Three feature commits:
  `ade65c7f` (substrate + cost-pay dispatch + emission gate, ~556 LOC
  production), `36fe47af` (12 substrate smoke tests in
  `tests_rust/test_activated.py`, ~404 LOC), `2b924c23` (CE20 closure pin
  flip + I48 + retire-CE20 notice, ~280 LOC).
- I48 in `docs/RUST_PARITY_GAPS.md:3436-3525` is the invariant that pins
  the new substrate. It also enumerates the out-of-scope follow-up slices
  this playbook builds work items for.
- ETB-trigger Slice 3 (the predicate-path-vs-`etb_effects` retirement)
  is in flight; this playbook stays out of that surface entirely.

EoE pool counts (`data/edge_of_eternities.json`, 266 printings total) — the
campaigns below scale to:

| Campaign | EoE printings affected |
|---|---|
| Spacecraft station-charge | 28 (every `Artifact - Spacecraft` carries "station" text) |
| Planeswalker loyalty | 1 (Tezzeret, Cruel Captain — sole walker in EoE) |
| Equipment equip | 7 (Auxiliary Boosters, Squire's Lightblade, Atomic Microsizer, Illvoi Light Jammer, Hylderblade, Meltstrider's Gear, The Dominion Bracelet) |
| Sacrifice-as-cost | 35 (incl. 1 Food-as-cost) |
| Activated abilities total (`:` in oracle text) | 91 |

---

## Section 1: Substrate recap

### The shipped `ActivatedAbility` shape

`rust/src/cards.rs:2060-2105`. Two structs:

```rust
pub struct ActivationCost {
    pub mana: ManaCost,   // payable from controller's pool
    pub tap_self: bool,   // implicit {T} portion
}

pub struct ActivatedAbility {
    pub cost: ActivationCost,
    pub effect: Effect,
    pub is_mana_ability: bool,   // CR 605.1 — bypass stack when true
}
```

Plus `CardPrinting.activated_abilities: Vec<ActivatedAbility>` at
`rust/src/cards.rs:2195`, defaults to empty Vec when the registry dict omits
the key (parser at `cards.rs:3650-3666`). `parse_activation_cost` raises
loudly on unknown keys (`cards.rs:3730-3758`) so every follow-up below MUST
extend that match arm in lockstep with its dispatch primitive — silent drop
of a richer cost shape is the failure mode the loud-raise guards against.

### I48 + emission filter + cost-pay pipeline

Pinned at `docs/RUST_PARITY_GAPS.md:3436-3525`. The substrate has TWO emission
paths walked side-by-side in `state_ops_legal.rs:995-1054`:

1. **Legacy `mana_produced` path** (`legal.rs:1015-1020`) — single
   `ability_index=0` emission per `mana_produced.is_some()` source with the
   `is_creature && summoning_sick` gate (CR 302.1).
2. **New `activated_abilities` path** (`legal.rs:1038-1053`) — walks every
   entry's `cost.tap_self` (rejects tapped + sick creature) and pool-only
   affordability via `pool_can_cover` (`legal.rs:484-500`).

`ActivateAbility` apply dispatch is the six-phase pipeline at
`state_ops_actions.rs:440-700`:

1. **Phase 1** — locate source on a battlefield (either side).
2. **Phase 2** — resolve ability shape: new path if `ability_index <
   activated_abilities.len()`; legacy `mana_produced` fallback if
   `ability_index == 0` AND `mana_produced.is_some()`; else loud raise
   `"has no ability at index N"`.
3. **Phase 3** — cost-pay precheck: `tap_self` ⇒ source untapped + non-sick
   (CR 302.1).
4. **Phase 4** — `state_ops_cast::pay_mana_cost_pub(pool, cost)` (returns
   bool; commits on success).
5. **Phase 5** — commit `tap_self` (writes `obj.tapped = true` via
   `Arc::make_mut`).
6. **Phase 6** — dispatch effect: `is_mana_ability=true` calls
   `apply_effect_pub` (CR 605.3a, bypass stack); `is_mana_ability=false`
   pushes `StackItem::new_trigger(source_obj_id, controller, effect,
   ability_index)` (resolves on the next `resolve_top_of_stack`).

### What follow-up campaigns must inherit

The follow-up campaigns below ALL extend the SAME `ActivationCost` struct +
the SAME apply pipeline + the SAME emission filter. The pattern is:

1. Add a field on `ActivationCost`.
2. Extend `parse_activation_cost`'s allow-list (`cards.rs:3736-3744`).
3. Extend the Phase 3 precheck (apply, `actions.rs:602-621`).
4. Extend the Phase 4-5 commit (apply, `actions.rs:622-656`).
5. Extend the emission gate (`legal.rs:1038-1053`).
6. Write tests in `tests_rust/test_activated.py` (mirroring the 12 substrate
   tests' parser/apply/emission three-axis structure).

Cross-references throughout the rest of this doc to specific Slice 1 line
numbers refer to the current main checkout (post-`18ca1527`).

---

## Section 2: Spacecraft station-charge campaign

### Background

28 Spacecraft printings in EoE (`Artifact - Spacecraft`). Each is a vehicle-
adjacent shape carrying multiple activated abilities GATED on a `charge_counters`
threshold. Examples from `data/edge_of_eternities.json`:

- Lumen-Class Frigate
- Rescue Skiff
- The Seriema (Legendary)
- Wedgelight Rammer
- Specimen Freighter
- Synthesizer Labship
- Uthros Scanship
- Entropic Battlecruiser

Spacecraft printings in the EoE booster set carry tiered station abilities —
the printed oracle text uses `N+ | <effect>` headers where `N` is the charge-
counter tier threshold. The Eternity Elevator's `20+ | {T}: Add X mana of
any one color` ability is the headline test case (see Python's
`effects/base.py:485-492`).

### Cost shape

```rust
pub struct ActivationCost {
    pub mana: ManaCost,
    pub tap_self: bool,
    pub charge_counters: i32,   // NEW — pay-N-charge-counters cost
    // ... (other follow-up fields)
}

pub struct ActivatedAbility {
    pub cost: ActivationCost,
    pub effect: Effect,
    pub is_mana_ability: bool,
    pub tier_threshold: i32,    // NEW — usability gate, not a cost
}
```

Two distinct shapes — `cost.charge_counters` is a PAY (decremented on
activation), while `tier_threshold` is an EMISSION GATE (the ability is
inert until the source has ≥N counters). Python mirrors this split at
`effects/base.py:329-492` — `ActivationCost` has no `charge_counters`
field (Spacecraft stations don't PAY counters), but `ActivatedAbility`
carries `tier_threshold: int = 0` for the usability gate.

**Slice author decision point:** ship `tier_threshold` only (matches Python
exactly), unless a card EOE-side actually PAYS charge-counters as a cost.
A grep of the EoE pool's oracle text for "Pay [0-9]+ charge counter" returns
zero hits, so `cost.charge_counters` is probably out of scope for Slice 1
of this campaign — skip it and only ship `tier_threshold`.

### Rust GameObject hookup

`rust/src/state.rs:34-50` — `GameObject` has a single `counters: i32` field
today. That field is currently used as a +1/+1 counter slot (per G8 in the
multi-kind-counter open gap). Adding `charge_counters` as a distinct field
on `GameObject` is the load-bearing engine change. **DO NOT** overload the
existing `counters` field — G8 already flags the multi-kind ambiguity as
a separate issue; resolving it in lockstep with Spacecraft would balloon
the slice.

Suggested new field at `rust/src/state.rs:42-44`:
```rust
pub damage: i16,
pub counters: i32,           // +1/+1 counters (existing)
pub charge_counters: i32,    // NEW — Spacecraft station counters
```

### Closure plan

**`rust/src/cards.rs`:**

- Line 2060-2073 (`ActivationCost`): add `pub charge_counters: i32 = 0`
  ONLY if cost-pay is in scope. Default = 0 leaves every pre-Slice-1
  caller unchanged.
- Line 2086-2105 (`ActivatedAbility`): add `pub tier_threshold: i32` with
  default 0 via `Default` derive or explicit `match dict.get_item` default.
- Line 3730-3758 (`parse_activation_cost`): add `"charge_counters"` to the
  allow-list (only if cost-pay is in scope).
- Line 3698-3724 (`parse_activated_ability`): parse `tier_threshold`,
  default = 0 when key absent.

**`rust/src/state.rs`:**

- Line 42-44: add `pub charge_counters: i32` to `GameObject`.
- Every `GameObject` literal-construction site: add `charge_counters: 0`
  initializer. Grep for `GameObject {` to enumerate — the field is on the
  CE20 substrate's hard-coded Forest / Grizzly Bears / Llanowar Elves
  initializations (analogous to the `activated_abilities: Vec::new()` adds
  the Slice 1 substrate made at `state.rs:lines TBD`).

**`rust/src/state_ops_legal.rs:1038-1053`:**

- Add `tier_threshold` check: `if ability.tier_threshold > 0 &&
  obj.charge_counters < ability.tier_threshold { continue; }` BEFORE the
  `tap_self` and `pool_can_cover` checks. The order is load-bearing — a
  source below tier shouldn't even consider its mana / tap state.

**`rust/src/state_ops_actions.rs:602-656`:**

- Phase 3 precheck: re-read the source's `charge_counters` and reject with
  a loud raise if `charge_counters < tier_threshold` (paranoid double-
  check; the emission gate should already filter, but a direct apply caller
  bypasses emission).
- Phase 4: if `cost.charge_counters > 0` (cost-pay variant), decrement
  `obj.charge_counters` via `Arc::make_mut` AFTER the pool gate succeeds.

### Estimated slice scope

**Medium, 100-200 LOC** if only `tier_threshold` ships; **200-300 LOC** if
the charge-counter cost-pay shape also ships. Most of the LOC is field
plumbing on `GameObject` literal-construction sites (every test fixture
needs the new field initialized).

### Tests to write (`tests_rust/test_activated.py`)

1. `test_tier_gate_emission_below_threshold_skips` — Spacecraft with
   `tier_threshold=3`, source has `charge_counters=2`, source untapped,
   pool covers mana cost: emission filter MUST skip. No
   `ActivateAbility` dict in `legal_decisions` output.
2. `test_tier_gate_emission_at_or_above_threshold_emits` — same setup
   with `charge_counters=3` and `charge_counters=99`: emits in both
   cases (the gate is ≥, not ==).
3. `test_tier_gate_apply_direct_call_below_threshold_raises` — direct
   `apply_action(ActivateAbility(...))` with source below tier raises
   `ValueError("source ... below tier threshold ...")`. Paranoid-check
   the apply arm's redundant gate.
4. `test_charge_counter_cost_pay_decrements_on_activate` — only if
   cost-pay variant ships. Source has `charge_counters=5`, ability cost
   `charge_counters=3`: post-activation `charge_counters=2`.
5. `test_charge_counter_cost_pay_insufficient_raises` — source has
   `charge_counters=1`, ability cost `charge_counters=3`: apply raises.
6. `test_multi_tier_abilities_each_gate_independently` — Spacecraft with
   two `ActivatedAbility` entries at `tier_threshold=3` and
   `tier_threshold=10`; source at `charge_counters=5` emits only the
   first. (The Eternity Elevator-style multi-tier shape.)

### Risks (also flagged in §9)

- **G8 multi-kind counter open gap**: `GameObject.counters` is +1/+1 today.
  Adding `charge_counters` as a distinct field is the right move; do NOT
  overload. Cross-ref G8 in `docs/RUST_PARITY_GAPS.md`.
- Spacecraft ETB doesn't add charge counters automatically — they accrue
  through the station mechanic, which itself is a tap-creatures-as-cost
  ability. That ability is OUT OF SCOPE of this slice (it's a "tap multiple
  creatures" cost, which is yet another follow-up). Tests above assume
  charge counters are seeded directly on the test fixture.

---

## Section 3: Planeswalker loyalty campaign

### Background

Exactly ONE planeswalker in EoE: **Tezzeret, Cruel Captain**
(`data/edge_of_eternities.json`, sole `Legendary Planeswalker - Tezzeret`).
Three loyalty abilities (the standard +/0/- pattern). Other Phase 5
planeswalker-touching cards exist (e.g. cards that reference walkers via
typed abilities) but the only walker the activated-ability dispatch needs
to handle is Tezzeret.

The walker substrate is smaller than Spacecraft (one printing vs 28) but
carries MORE rules per CR 119.5 (damage redirect), CR 306 (planeswalker
state-based actions), and the loyalty-counter accounting itself.

### Cost shape

```rust
pub struct ActivationCost {
    pub mana: ManaCost,
    pub tap_self: bool,
    pub loyalty: i32,   // NEW — signed; positive = pay, negative = add
    // ...
}
```

Loyalty is signed: a `+2` ability has `loyalty: -2` (the COST is "ADD 2
counters", which Python encodes as a non-positive number, but a cleaner
shape is `loyalty: i32` where positive is "pay (remove) N" and negative is
"add |N|"). Tezzeret-specific values from the printed text TBD.

### Rust GameObject hookup

Same situation as charge counters — Rust's `GameObject.counters: i32` is the
existing +1/+1 slot. **Add `pub loyalty_counters: i32` as a NEW field at
`rust/src/state.rs:42-44`**, same pattern as Spacecraft's `charge_counters`.

### Closure plan

**`rust/src/cards.rs`:**

- Line 2060-2073: add `pub loyalty: i32` to `ActivationCost` (default 0).
- Line 3730-3758: extend `parse_activation_cost` allow-list with
  `"loyalty"`.

**`rust/src/state.rs`:**

- Line 42-44: add `pub loyalty_counters: i32` to `GameObject`.
- Every `GameObject` literal-construction site gets a `loyalty_counters: 0`
  initializer.

**`rust/src/state_ops_legal.rs:1038-1053`:**

- Add loyalty check BEFORE the `tap_self` and `pool_can_cover` checks:
  `if ability.cost.loyalty > 0 && obj.loyalty_counters < ability.cost.loyalty
  { continue; }`. Affordability for a positive cost (the "-N" ability) is
  "has at least N loyalty counters". A negative cost (the "+N" ability) is
  always affordable.

**`rust/src/state_ops_actions.rs:602-656`:**

- Phase 3 precheck: redundant loyalty check (same shape as emission gate).
- Phase 4 commit: `loyalty_counters -= cost.loyalty` (signed; adds for
  negative values, subtracts for positive).
- After commit, check if `loyalty_counters <= 0` and stage a SBA-driven
  removal via the existing `state_ops_sba.rs` pass (CR 704.5i — a
  planeswalker with 0 or less loyalty goes to its owner's graveyard).
  **Crucial**: don't move the walker inline; let the next SBA pass do it
  so other simultaneous effects can fire. Mirrors how the substrate's
  apply arm DOESN'T resolve the stack item it just pushed — same pattern.

**`rust/src/state_ops_sba.rs`** (existing):

- Add a planeswalker-zero-loyalty victim pass alongside the existing
  creature-lethal-damage pass. The walker's controller's graveyard
  receives it on the same tick. ~20-30 LOC addition.

**`rust/src/state_ops_combat.rs`** (CR 119.5 damage redirect — IF in scope):

- Combat damage redirect from a player to a planeswalker is the
  attacker-chooses option in CR 506.1 / 510.1. **Recommendation: defer
  damage-redirect to a separate slice** — it requires growing
  `DeclareAttackers` to allow targeting a planeswalker, which itself is
  a `legal_decisions` emission change. Cleanest split: Slice A ships the
  cost / loyalty-counter / SBA primitive; Slice B ships the combat-damage
  redirect. Each is small + testable independently.

### Estimated slice scope

**150-300 LOC** for the Slice A primitive (cost + counter + SBA). The
combat-damage redirect (Slice B) is another 100-200 LOC because it
threads through `legal_decisions` for DeclareAttackers.

### Tests to write

1. `test_loyalty_positive_cost_decrements` — walker at `loyalty_counters=5`,
   ability cost `loyalty=2`: post-activation `loyalty_counters=3`.
2. `test_loyalty_negative_cost_adds` — walker at `loyalty_counters=3`,
   ability cost `loyalty=-1` (a +1 ability): post-activation
   `loyalty_counters=4`.
3. `test_loyalty_ultimate_ability_drives_below_zero_then_sba_removes` —
   walker at `loyalty_counters=8`, ability cost `loyalty=10`: apply
   raises (insufficient). Then walker at `loyalty_counters=10`, ability
   cost `loyalty=10`: post-activation `loyalty_counters=0`, NEXT SBA
   pass moves walker to gy.
4. `test_loyalty_zero_loyalty_walker_dies_via_sba` — walker at
   `loyalty_counters=0` on bf, SBA pass moves it to gy.
5. `test_loyalty_emission_skips_when_below_positive_cost` — walker at
   `loyalty_counters=1`, ability cost `loyalty=3`: `legal_decisions` does
   NOT emit the ability.
6. `test_loyalty_only_one_activation_per_turn` — CR 606.3 says a player
   can activate at most one loyalty ability per turn per walker. NEEDS
   `triggered_this_turn`-style ledger; mirrors the substrate's existing
   `activate_only_once` deferral. Tag this test `@xfail` until the ledger
   lands. (Alternative: defer this test to Slice C.)
7. `test_combat_damage_redirected_to_walker_decrements_loyalty` — Slice B
   only. Attacker declares a walker as the attack target; combat damage
   resolution removes loyalty counters equal to the unblocked attacker's
   power.

### Risks (also flagged in §9)

- CR 119.5 damage redirect interacts with the CE14/CE15 multi-blocker
  closures' assignment walk. Defer combat-damage redirect to a follow-up
  slice (Slice B above) to keep blast radius small.
- CR 606.3 once-per-turn-per-walker is a NEW ledger surface; Slice 1 of
  the playbook recommends shipping it as a `@xfail` test and a separate
  Slice C.

---

## Section 4: Equipment equip campaign

### Background

7 Equipment printings in EoE (`Artifact - Equipment`):

- Auxiliary Boosters
- Squire's Lightblade
- Atomic Microsizer
- Illvoi Light Jammer
- Hylderblade
- Meltstrider's Gear
- The Dominion Bracelet (Legendary)

Each carries an "Equip {N}" activated ability — pay mana, target a creature
you control, attach the Equipment to it (CR 702.6). Equipment ETB is already
partially wired via `Effect::AttachToTargetCreatureYouControl` (Round-28
EoE Equipment-ETB at `rust/src/state_ops_resolve.rs:4184-4231`) and the
`Effect::EquipToTargetCreatureYouControl` variant at `state_ops_resolve.rs:4241`
(Round-29 Equip activated-ability resolution; semantics identical to attach
but distinct variant for diagnostic parity with Python).

**Foundation that exists**: `GameObject.attached_to: Option<u32>`
(`rust/src/state.rs:58`), the attach mutation at
`state_ops_resolve.rs:4184-4231`, and the
`Effect::EquipToTargetCreatureYouControl` variant. The new work is
TARGET PICKING (the substrate's `attach.rs` picks the first eligible
creature deterministically — for an activated ability that takes a chosen
target, the activator needs to PICK a target via a `Decision`).

### Cost shape

```rust
pub struct ActivationCost {
    pub mana: ManaCost,
    pub tap_self: bool,
    pub requires_target_creature_you_control: bool,   // NEW
    // ...
}
```

The `tap_self` field stays false (equip is mana-only as a cost). The new
field flags that the activated ability requires a target creature, which
flows into:

1. `legal_decisions` enumerates one `ActivateAbility(source_id,
   ability_index, target_creature_id)` per legal-target creature on the
   activator's bf (CR 702.6c — target a creature you control). Today the
   `ActivateAbility` action dict has NO target field; the dict shape grows.
2. `apply_action(ActivateAbility(...))` reads `target_creature_id` from the
   dict and threads it into the effect resolution.

### Closure plan

**`rust/src/cards.rs`:**

- Line 2060-2073: add `pub requires_target_creature_you_control: bool`
  (default false).
- Line 3730-3758: extend `parse_activation_cost` allow-list.

**`rust/src/state_ops_legal.rs`:**

- Line 462-473 (`activate_ability_dict`): grow the dict to support an
  optional `"target_creature_id"` key. Existing callers (legacy
  `mana_produced`, non-target activated abilities) pass `None`.
- Line 1038-1053: when `ability.cost.requires_target_creature_you_control`,
  walk the activator's battlefield for legal targets, emit one
  `ActivateAbility` dict per target. Sort by `etb_timestamp` via
  `bf_iter_etb_sorted` (the CE5/CE6/CE7 playbook's shared helper at
  `rust/src/bf_iter.rs`).
- Filter targets to non-Equipment creatures (CR 702.6c — attach to a
  creature; Equipment can't equip Equipment).

**`rust/src/state_ops_actions.rs:440-700`:**

- Action dict parser at `actions.rs:440-443`: read optional
  `target_creature_id`.
- Phase 1.5 (NEW): validate target is on the activator's bf, is a creature,
  and isn't the source itself. Raise on invalid target.
- Phase 6 dispatch: pass `target_creature_id` through to the effect resolution.
  For `Effect::EquipToTargetCreatureYouControl` the effect handler at
  `state_ops_resolve.rs:4241` already does the attach mutation; it needs
  to read the target from the StackItem payload rather than picking
  deterministically. Grow `TriggerPayload` (`state.rs:415-434`) to carry
  an optional `target_id`.

**`rust/src/state_ops_resolve.rs:4241-...`:**

- Use the payload's `target_id` (if present) instead of the first-eligible
  walk. Existing ETB-attach (`Effect::AttachToTargetCreatureYouControl`,
  line 4184) keeps the first-eligible walk because ETB doesn't take a
  target — only the activated equip does.

### Estimated slice scope

**200-400 LOC** — bulk is on the legal-emission target-fan-out and the
action-dict-with-target shape. The effect handler itself is already in
place.

### Tests to write

1. `test_equip_emits_one_action_per_legal_target` — Equipment on p0 bf,
   3 creatures on p0 bf: `legal_decisions` emits 3 ActivateAbility dicts
   (one per creature) plus 0 for the Equipment itself.
2. `test_equip_apply_attaches_to_chosen_target` — apply
   `ActivateAbility(equipment_id, 0, target_creature_id=N)`: equipment's
   `attached_to == N`.
3. `test_equip_apply_idempotent_to_same_target` — apply twice with same
   target: `attached_to == N` still, no error. Mana cost paid both times
   (the activation is still a valid game action).
4. `test_equip_retarget_moves_attachment` — apply once to N1, then apply
   again to N2: `attached_to == N2`.
5. `test_equip_invalid_target_raises` — target on opponent's bf, target
   isn't a creature, target is the source itself: each case raises.
6. `test_equip_no_legal_targets_emits_nothing` — Equipment on bf, no
   creatures on bf: no emission.
7. `test_equip_summoning_sick_creature_is_legal_target` — equip doesn't
   care about target's sickness (CR 702.6 — only the activator's creature
   needs to exist; sickness only gates the equipment itself if it had
   `tap_self`, which equip doesn't).

### Risks

- The action-dict shape grows. Every legacy `ActivateAbility(...)` test
  that constructs the dict by hand keeps working (optional key); but
  the cross-engine smoke harness's
  `src/mtg_bot/parity/cross_engine.py:activated_cost_side_channel` needs
  to learn the new key. The harness change is small (~20 LOC) but is the
  most likely place a slice author forgets to update.

---

## Section 5: Sacrifice-as-cost campaign

### Background

35 EoE printings carry a sacrifice-as-cost shape. Subset of these:

- **`sacrifice_self`**: Honored Knight-Captain (`{4}{W}{W}, Sacrifice this
  creature:` ... ), Illvoi Galeblade (`{2}, Sacrifice this creature: Draw
  a card.`), Cryogen Relic (`{1}{U}, Sacrifice this artifact: Put a stun
  counter ...`).
- **`sacrifice_another_creature_or_artifact`**: Umbral Collar Zealot
  (`Sacrifice another creature or artifact: Surveil 1.`).
- **`sacrifice_a_land`**: Dust Bowl-style (out of EoE in Python; the
  shape exists in `effects/base.py:388`).
- **`sacrifice_food`**: 1 EoE printing carries Food-as-cost.
- Other variants per Python `effects/base.py:340-388`:
  `sacrifice_another_artifact_or_land`, `sacrifice_another_artifact`,
  `sacrifice_a_desert`.

Lander tokens (an EoE mechanic — see Emergency Eject, Sunstar
Expansionist) carry their OWN `{2}, {T}, Sacrifice this token:` ability,
which is a `sacrifice_self` shape on a token printing. Slice 1 of this
campaign covers the token shape automatically because the cost lives on
the printing, and Rust's token-printing path is already wired.

### Cost shape

```rust
pub struct ActivationCost {
    pub mana: ManaCost,
    pub tap_self: bool,
    pub sacrifice: Option<SacrificeCost>,   // NEW
    // ...
}

pub enum SacrificeCost {
    SacrificeSelf,
    SacrificeAnotherCreature,           // legality: another creature on activator's bf
    SacrificeAnotherCreatureOrArtifact, // legality: another creature OR artifact on activator's bf
    SacrificeAnotherArtifactOrLand,
    SacrificeAnotherArtifact,
    SacrificeALand,
    SacrificeADesert,
    SacrificeFood,
}
```

Cleaner shape than 8 separate booleans on `ActivationCost`. The Python
side uses booleans because of its `frozen=True` dataclass shape; Rust can
use an enum + `Option` and translate from the dict's bool keys at parse time.

### Closure plan

**`rust/src/cards.rs`:**

- Line 2060-2073: add `pub sacrifice: Option<SacrificeCost>` to
  `ActivationCost`.
- New `pub enum SacrificeCost { ... }` near the `ActivationCost` struct.
- Line 3730-3758: extend `parse_activation_cost` allow-list with all 8
  sacrifice-related bool keys (matching Python's exact key names for
  cross-engine smoke parity). The parse logic: at most one of the 8
  keys may be true (or zero — `None`); enforce loudly.

**`rust/src/state_ops_legal.rs:1038-1053`:**

- Per-variant legal-target precheck. For `SacrificeSelf`: source must
  exist on bf (always true once located, so no extra check). For
  `SacrificeAnotherCreature`: at least one OTHER creature on the
  activator's bf — skip emission otherwise. For `SacrificeAnotherArtifact`,
  etc.: analogous walks.
- Targeted shapes (`SacrificeAnotherCreature` etc.) need the same
  target-fan-out treatment as Equipment equip (Section 4) — one
  emission per legal sac target. **Recommend deferring the targeted
  sac variants to Slice B**: ship `SacrificeSelf` first (zero target
  fan-out), then Slice B grows the target fan-out (which can share
  Equipment Slice's substrate).

**`rust/src/state_ops_actions.rs:440-700`:**

- Phase 3 precheck: legality of the sac target.
- Phase 4-5 (commit): move the sac'd object to its owner's graveyard via
  the existing `move_object` primitive at `state_ops_resolve.rs:786,851,...`
  (which already handles the LTB-flag void-tracking from CE13). **Sacrifice
  triggers LTB events** — the void-tracking flag handles this correctly
  per CE13 / I29 closure. No new wiring needed; the existing
  `move_object` call chain does the right thing.

### Estimated slice scope

**200-400 LOC** depending on how many sac variants ship in Slice 1.
Recommendation: Slice 1 = `SacrificeSelf` only (~150 LOC); Slice 2 =
all "sacrifice ANOTHER X" variants (rides on Equipment Section 4's
target-pick substrate; another ~150-250 LOC).

### Tests to write

1. `test_sacrifice_self_moves_source_to_graveyard` — source on p0 bf,
   apply with sac-self cost: source moves to p0 gy.
2. `test_sacrifice_self_consumes_mana_and_triggers_etb_or_ltb` — if the
   source has LTB effects, they fire (CR 603.6c) — confirm via the
   existing dispatch_event(LEAVES) path.
3. `test_sacrifice_another_creature_target_pick` — Slice B only. Source
   + 2 other creatures on p0 bf; apply with `target=N`: target moves
   to gy, source stays on bf.
4. `test_sacrifice_another_creature_no_targets_emission_blocked` — source
   on p0 bf with no other creatures: emission filter skips the ability.
5. `test_sacrifice_a_land_targets_lands_only` — Slice B; lands on bf,
   creatures on bf: emission emits one per land.
6. `test_sacrifice_food_targets_food_subtype_only` — Slice B; Food token
   in play: emission emits with food token id as target.
7. `test_sacrifice_failed_when_nothing_to_sacrifice` — `SacrificeAnotherCreature`
   when source is the only creature: apply raises, emission skips.

### Risks (also flagged in §9)

- CE13 / I29 LTB void-tracking interaction: the existing
  `mark_left_battlefield_if_nonland` helper at
  `state_ops_resolve.rs:4173` does the right thing when an object moves
  from bf to gy via sacrifice. Confirm in a regression test
  (`test_sacrifice_self_void_flag_stamped`).
- ETB-trigger Slice 3 (in flight) is bridging the predicate path to
  `etb_effects` retirement. The sacrifice campaign should NOT touch
  `triggered_abilities` / `etb_effects` paths; it's a cost-pay surface
  only. Stay disjoint.

---

## Section 6: Bridge `mana_produced` into `activated_abilities`

### Background

Pre-Slice-1, Rust's free-mana-ability hatch was
`CardPrinting.mana_produced: Option<Vec<String>>` at `cards.rs:2128`.
The CE20 Slice 1 substrate kept it as a SIDE-CHANNEL — the emission
filter at `legal.rs:1015-1020` walks `mana_produced.is_some()`
sources separately from the new `activated_abilities` Vec, and the apply
arm at `actions.rs:558-581` carries a `legacy_mana_symbols: Vec<String>`
fallback branch. This dual path is back-compat scaffolding; I48 calls
out the bridge as out-of-scope follow-up.

### Closure plan

**`rust/src/cards.rs::parse_printing` (`cards.rs:3667-3679`)**:

At parse time, when `mana_produced.is_some()`, synthesize ONE
`ActivatedAbility` entry per color in `mana_produced` and PREPEND it to
the `activated_abilities` Vec:

```rust
let mut activated_abilities: Vec<ActivatedAbility> = match dict.get_item(...) {
    Some(aa_any) => { /* existing parse */ }
    None => Vec::new(),
};

// Bridge: synthesize ActivatedAbility entries for mana_produced.
if let Some(symbols) = &mana_produced {
    let mut bridge_entries: Vec<ActivatedAbility> = Vec::new();
    // Build ONE entry that adds all the symbols at once (matches the
    // Slice 1 legacy path which adds all of mana_produced's symbols
    // on a single activation).
    bridge_entries.push(ActivatedAbility {
        cost: ActivationCost {
            mana: ManaCost::default(),  // free
            tap_self: true,             // implicit {T}
            // ...other follow-up defaults...
        },
        effect: Effect::AddManaToPool { symbols: symbols.clone() },
        is_mana_ability: true,
    });
    // Prepend so ability_index=0 still refers to the legacy mana ability
    // (back-compat with every test that calls
    // apply_action(ActivateAbility(forest_id, 0))).
    bridge_entries.append(&mut activated_abilities);
    activated_abilities = bridge_entries;
}
```

**`rust/src/state_ops_legal.rs:1015-1020`** — DELETE the legacy
`mana_produced.is_some()` one-shot emission. Every call now lands in the
new-path walk at line 1038-1053 with `ability_index=0` matching the
prepended bridge entry. (Caveat: dedup. The legal-emission walk MUST NOT
double-emit; deleting the legacy block + the bridge prepend leaves a
single emission per source.)

**`rust/src/state_ops_actions.rs:558-581`** — DELETE the
`is_legacy_mana_produced` branch + the `legacy_mana_symbols` field on
`ResolvedAbility`. The new-path branch at `actions.rs:547-557` handles
the bridged entry uniformly (it's just another `ActivatedAbility` with
`is_mana_ability: true`). Phase 6 dispatch now ALWAYS uses
`apply_effect_pub` for `is_mana_ability=true`, which means
`Effect::AddManaToPool` must already be a valid `Effect` variant. **Check
`rust/src/cards.rs` for the `Effect::AddManaToPool` variant**; if absent,
add it as the bridge's bonded effect.

### Estimated slice scope

**~50 LOC** of code change + ~30 LOC of regression test confirming the
bridge preserves Forest / Llanowar Elves / Birds-of-Paradise behavior bit-
equal pre- and post-bridge.

### Tests to write

1. `test_bridge_forest_emission_unchanged` — Forest on p0 bf,
   `legal_decisions` emits exactly ONE `ActivateAbility(forest_id, 0)`
   dict. (Pre-bridge: emitted by legacy block. Post-bridge: emitted by
   new-path walk on the synthesized entry. Same observable result.)
2. `test_bridge_forest_apply_unchanged` — apply
   `ActivateAbility(forest_id, 0)`: forest tapped, pool +1 G.
3. `test_bridge_grizzly_bears_with_no_mana_produced_unchanged` — no
   emission (defender mana ability doesn't apply).
4. `test_bridge_llanowar_elves_summoning_sick_unchanged` — Llanowar Elves
   with `summoning_sick=true`: no emission (the `tap_self && creature
   && sick` gate fires).
5. **Regression sweep**: every test under `tests_rust/test_activated.py`
   should still pass with zero modification. Run the full Rust gate
   pre- and post-bridge; any test that changes is a bug.

### Risks

- The bridge changes the SHAPE of `activated_abilities` for every
  mana-producing printing. Any code that walks `activated_abilities` and
  ASSUMES it was registry-supplied (vs synthesized) will break. Audit
  callers: `cards.rs::parse_printing`, `legal.rs::legal_decisions`,
  `actions.rs::ActivateAbility` apply arm — all three are in this
  playbook's scope and are explicitly migrated.
- Dedup: the legacy emission path + the new-path walk would double-emit
  if both fire. The closure plan above DELETES the legacy path; double-
  check no other consumer reads `mana_produced.is_some()` directly.

---

## Section 7: Auto-tap-from-lands composer

### Background

`state_ops_legal.rs::pool_can_cover` at `legal.rs:484-500` is pool-only
— it gates emission on whether the controller's CURRENT mana pool covers
the cost. Python's `legal.py::can_pay_cost` is broader: it composes
pool + tappable-land headroom (`can_pay_cost` checks lands that could be
tapped to produce the missing colors, then sums the resulting pool).

The cross-engine smoke harness works around this gap by pre-populating
the activator's mana pool before driving an `ActivateAbility` directly,
but it's a real divergence: at SORCERY-TIMING positions where Python
emits `ActivateAbility` with an empty pool (because untapped Forests
could pay), Rust's emission filter skips. I48 explicitly notes this as
"out of scope" follow-up.

### Closure plan

**`rust/src/state_ops_legal.rs`:**

Replace `pool_can_cover` with a broader `auto_tap_headroom_pool(state,
player_idx, cost)` helper that:

1. Starts with the controller's current pool.
2. Walks the controller's bf for untapped non-sick mana sources
   (`printing.mana_produced.is_some() && !obj.tapped && !(is_creature &&
   obj.summoning_sick)`).
3. Speculatively credits each source's outputs to a copy of the pool.
4. Returns true iff `pool_can_cover` on the SPECULATIVE pool covers the
   cost.

Key invariant: the auto-tap composer is EMISSION-SIDE only. The actual
apply arm at `actions.rs:632-647` STILL requires the controller to have
the mana already in their pool (auto-tap happens AHEAD of the
`ActivateAbility` action via `legal_decisions` emitting the right
`ActivateAbility(forest_id, 0)` actions first). This matches Python's
model: `can_pay_cost` is permissive in `legal_actions`; `_activate_ability`
is strict (relies on the player having tapped lands ahead of time).

**Optional polish**: emit a `tap_lands` synthetic action that bundles the
required taps + the activation in one Decision. Python does NOT do this
today, so DEFER to a future synthetic-action slice and stay parity-clean.

### Estimated slice scope

**~50 LOC** if the polish is deferred. The composer is a single new
function + one call-site swap (`pool_can_cover` → `auto_tap_headroom_pool`
at `legal.rs:1050`).

### Tests to write

1. `test_emission_with_empty_pool_plus_tappable_lands_emits` — empty pool,
   3 untapped Forests on p0 bf, Bear Caster needs `{1}{G}`: emission emits.
2. `test_emission_with_empty_pool_no_lands_does_not_emit` — empty pool,
   no lands: emission skips.
3. `test_emission_with_partial_pool_plus_lands_emits` — pool has `{G}`,
   2 untapped Forests, cost `{2}{G}`: emission emits (1 G in pool + 2 G
   headroom from lands covers 2 generic + 1 colored).
4. `test_emission_with_tapped_lands_excluded` — all Forests tapped:
   emission skips. (Tapped sources have no headroom.)
5. `test_emission_with_summoning_sick_creature_mana_source_excluded` —
   Llanowar Elves on bf, sick: not counted in headroom.
6. `test_apply_after_auto_tap_emission_still_requires_explicit_taps` —
   emission emits, but apply with empty pool still raises. Pins the
   "emission permissive, apply strict" contract.

### Risks

- The auto-tap composer must use `bf_iter_etb_sorted` for the tap-order
  walk (CE5 closure invariant I26). Otherwise multi-source headroom
  calculations diverge from Python's ordering. Cross-ref the CE5/CE6/CE7
  playbook's shared `bf_iter.rs` module.
- Cross-engine smoke pinning: the harness's
  `activated_cost_side_channel` pre-populates the pool to dodge the gap.
  Post-closure, the harness MAY exhibit different observable emission
  shapes — audit
  `tests/test_parity_smoke.py::test_cross_engine_activated_cost_test_d_python_underpays_silently`
  to confirm it still tests the right invariant.

---

## Section 8: Dependency graph + ordering recommendation

### Cross-campaign dependencies

```
                          +---------------------+
                          |  Substrate (CE20)   |
                          |  f0fd4492 LANDED    |
                          +----------+----------+
                                     |
        +----------+----------+------+------+----------+----------+
        |          |          |             |          |          |
        v          v          v             v          v          v
   Bridge      Auto-tap   Sacrifice    Spacecraft   Equipment   Walker
   mana_produced  headroom  (Section 5)  (Section 2) (Section 4) (Section 3)
   (Section 6)  (Section 7)
        |          |          |             |          |          |
        |          |          |             |          |          |
        +----------+----------+--+----------+----------+-+--------+
                                |                        |
                                v                        v
                       +----------------+      +-------------------+
                       |  Targeted sac  |      |  Walker damage    |
                       |  Slice 2       |      |  redirect (Slice B)|
                       | (needs target  |      | (needs DeclareAttackers
                       |  fan-out from  |      |  walker-target)   |
                       |  Equipment)    |      +-------------------+
                       +----------------+
```

### Recommended order

1. **Bridge `mana_produced`** (Section 6) — independent, ~50 LOC,
   pure cleanup. Eliminates the dual-path complexity that every
   subsequent campaign would otherwise have to keep in mind. Land first.

2. **Auto-tap headroom composer** (Section 7) — independent, ~50 LOC,
   converges emission with Python's `can_pay_cost`. Land second so every
   subsequent campaign's tests can use Python-faithful emission setups
   instead of pre-populating the pool.

3. **Sacrifice-as-cost (`SacrificeSelf` only)** (Section 5 Slice 1) —
   ~150 LOC. No target fan-out needed; rides on the existing
   `move_object` + CE13 void-flag plumbing. Most of the LOC is the
   `ActivationCost.sacrifice` field + `SacrificeCost` enum + parser
   extension + Phase 4 commit. Good warm-up for the more complex
   campaigns below.

4. **Spacecraft station-charge (tier_threshold only)** (Section 2) —
   100-200 LOC. The `GameObject.charge_counters` field add is mechanical
   but touches every `GameObject` literal-construction site. Most
   complex piece is the SBA / cleanup interaction (does the
   `effective_activated_abilities` filter need a runtime gate? Yes —
   per Python's `effects/base.py:620`).

5. **Equipment equip** (Section 4) — 200-400 LOC. The largest single
   campaign because it introduces TARGET PICKING in the
   `ActivateAbility` action dict shape. After this lands, the target-
   pick substrate is reusable by Sacrifice Slice 2 (targeted sac variants).

6. **Planeswalker loyalty (Slice A only)** (Section 3) — 150-300 LOC.
   Distinct counter-kind from Spacecraft (loyalty != charge != +1/+1),
   so the field plumbing is purely additive. Defer combat damage
   redirect (Slice B) and CR 606.3 once-per-turn-per-walker (Slice C) to
   separate follow-ups.

### Estimated total

**3-5 slices** if the recommended grouping holds:

- Slice 1: Bridge + Auto-tap (combined, ~100 LOC, doc-style cleanup).
- Slice 2: SacrificeSelf (~150 LOC).
- Slice 3: Spacecraft tier-gate (~100-200 LOC).
- Slice 4: Equipment equip (~200-400 LOC). Largest.
- Slice 5: Walker loyalty Slice A (~150-300 LOC). Distinct.

Total LOC range: **~700-1200 LOC production + ~500-800 LOC tests**, with
the campaign concentration on Slice 4 (Equipment).

Targeted sac variants + walker damage redirect + walker once-per-turn
ledger are NOT included in the count — they're follow-ups to Slices 2,
3, and 5 respectively, ridden by smaller subsequent slices once their
parent substrate lands.

---

## Section 9: Risk register

### Cross-campaign interactions

1. **G8 multi-kind counter open gap** (`docs/RUST_PARITY_GAPS.md`).
   `GameObject.counters: i32` is the +1/+1 slot today. Both Spacecraft
   (Section 2) and Walker (Section 3) need their OWN counter fields —
   `charge_counters` and `loyalty_counters` respectively. **Do not
   overload the existing field.** Risk: silent +1/+1-vs-charge conflation
   if either campaign tries to be clever. Mitigation: explicit new
   fields, enforced by tests that put +1/+1 counters AND charge counters
   on the same source and assert they're tracked independently.

2. **Planeswalker damage redirect (CR 119.5) interacts with combat damage
   (CE14/CE15 closures)**. Slice B of the Walker campaign
   (Section 3) touches `state_ops_combat.rs:849-1028` — the same region
   CE14 (deathtouch) and CE15 (trample) already closed. **Risk**: walker
   damage redirect could re-open the bf-iteration-order invariant pinned
   at I26 (bf-ETB stable-sort). **Mitigation**: use
   `bf_iter_etb_sorted` for any walker target walk; mirror the CE6
   closure's "Option A" pattern of sorting plan entries after build, not
   during build.

3. **Sacrifice costs interact with void-tracking LTB flag (CE13 / I29)**.
   `mark_left_battlefield_if_nonland` at `state_ops_resolve.rs:4173`
   already does the right thing when a sacrificed object moves bf→gy.
   **Risk**: if a future sac-as-cost path uses a different bf→gy
   primitive that bypasses the helper, the void flag wouldn't stamp,
   and CE13's regression tests would silently pass while the
   cross-engine smoke would diverge mid-game. **Mitigation**: every sac
   commit MUST route through `move_object` (which calls
   `mark_left_battlefield_if_nonland`); add a regression test that
   pins this contract (`test_sacrifice_self_void_flag_stamped`).

4. **ETB-trigger Slice 3 in flight**: bridges `etb_effects` into the
   predicate path. **Disjoint from this playbook's surface.** No CE20
   follow-up campaign touches `triggered_abilities` / `etb_effects`.
   The two efforts can land in any order.

5. **Cross-engine smoke harness pinning**:
   `src/mtg_bot/parity/cross_engine.py::activated_cost_side_channel`
   carries the substrate-only Bear Caster injection. **Risk**: as
   follow-up campaigns land, the harness's pre-populated pool
   workaround becomes obsolete; the harness should be migrated
   incrementally (one campaign per cross-engine smoke probe), not all
   at once. **Mitigation**: each follow-up slice author updates the
   harness inline with their slice + ships a Phase 5 probe that
   exercises the new shape.

### Slice-level risks

- **Bridge `mana_produced`** (Section 6): dedup of the legacy emission
  path. The closure plan DELETES the legacy block; double-check no
  consumer reads `mana_produced.is_some()` directly. Grep:
  `grep -n 'mana_produced.is_some' rust/src/`.
- **Auto-tap composer** (Section 7): must use `bf_iter_etb_sorted` for
  the tap-order walk (CE5 invariant I26). Walking p0-then-p1 instead of
  ETB-sorted would re-open a closed CE.
- **Spacecraft** (Section 2): `effective_activated_abilities` filter
  must run AT EMISSION TIME, not at apply time — a stale runtime gate
  would let a sub-tier ability appear in MCTS root statistics and skew
  PUCT priors. Test `test_tier_gate_emission_below_threshold_skips`
  pins this.
- **Equipment equip** (Section 4): the `ActivateAbility` action dict
  grows an optional `target_creature_id` key. Every existing call site
  must accept the optional key; the wire format change is the most
  likely place a subsequent slice's harness update gets missed.
- **Walker** (Section 3): SBA-driven removal at `loyalty_counters <= 0`
  must run on the SAME SBA pass as other simultaneous removals (CR
  704.5i). Do NOT remove inline at activation — pin via
  `test_loyalty_zero_loyalty_walker_dies_via_sba`.

---

## Section 10: Cross-cutting checklist for every slice author

Before opening a worktree for any follow-up campaign:

1. Read I48 at `docs/RUST_PARITY_GAPS.md:3436-3525` (the substrate
   invariant). Anything you change MUST keep I48's pins intact.
2. Read the CE20 Slice 1 substrate commit shape:
   - `ade65c7f` — substrate + cost-pay dispatch + emission gate.
   - `36fe47af` — 12 substrate smoke tests.
   - `2b924c23` — closure pin flip + I48 + retire CE20.
3. Read the CE5/CE6/CE7 closure playbook
   (`docs/CE5_CE6_CE7_CLOSURE_PLAYBOOK.md`, merge `2a7221b1`) for the
   `bf_iter_etb_sorted` helper signature — every bf-walk in your slice
   must consume it.
4. Pre-stage your test additions in `tests_rust/test_activated.py`
   following the substrate's parser/apply/emission three-axis structure.
5. Update the cross-engine smoke harness
   (`src/mtg_bot/parity/cross_engine.py:activated_cost_side_channel`)
   to inject your shape into both engines, and add a Phase 5 probe in
   `tests/test_parity_smoke.py` mirroring the existing
   `activated_cost_selector` pattern.
6. After your slice lands, append an I-entry to
   `docs/RUST_PARITY_GAPS.md` documenting the new invariant (the next
   number after I48 / the latest landed I) + cross-references to I48 and
   to any sibling I-entries your campaign touches.

End of playbook.
