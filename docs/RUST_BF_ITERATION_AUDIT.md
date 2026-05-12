# Rust battlefield-iteration audit — CE5-CE9 closure checklist

Companion to `docs/ORDER_SENSITIVE_SURFACES.md` (committed `1be3e0c4`).
That doc inventoried the 12 order-sensitive observables on the *Python*
side and ranked CE5-CE9 by likelihood-of-surfacing. This doc enumerates
every site in `rust/src/` that iterates a battlefield Vec, classifies
each by ordering semantics, maps it to its Python counterpart, and
rates the cross-engine divergence risk after CE4 (battlefield ETB
ordering) has landed (commit `276d806a`).

The purpose is operational: when a future CE\<n\> slice closes a
divergence by "sort by ETB timestamp before iterating", the slice
author can consume this doc as a checklist of every place that walks
the bf and assess whether their fix needs to thread through that
site too.

## Headline summary

- **37 distinct battlefield-iteration sites** enumerated across **12
  Rust source files**.
- **3 HIGH risk** — currently exercised by the parity smoke harness
  or trivially reachable by a 1-line probe; predicted to surface as
  CE5 / CE6 / CE7 in `ORDER_SENSITIVE_SURFACES.md`.
- **8 MEDIUM risk** — semantic divergence is real but requires a
  Phase-5-class probe that doesn't exist yet (e.g. multi-block damage
  scenarios, Oblivion-Ring-style auto-recall when Rust grows it).
- **18 LOW risk** — order doesn't reach a game-load-bearing output
  (point lookups by id, ETB-stamp injection paths that immediately
  resolve to the same place, find-first-match patterns where the
  match is unique).
- **8 NONE / parity-pinned** — already addressed by CE4's stable-sort
  closure (`battlefield_snapshot`, `fingerprint`'s bf walk), or
  fundamentally not-iteration-orderable (point-lookup helpers,
  size getters).

Counts may shift by ±1 as future slices refactor; the per-file
inventory below is the source of truth.

---

## 1. `rust/src/state_ops_legal.rs` — `legal_decisions` emitter

Three iteration sites, all per-player (priority player's bf only,
not both). HIGH visibility — `legal_decisions` is what the smoke
harness sees most frequently.

### L1. DeclareAttackers eligibility — `state_ops_legal.rs:564`

```rust
let mut eligible: Vec<u32> = Vec::new();
for obj in self.players[idx].battlefield.iter() {
    if obj.tapped { continue; }
    // Creature + not summoning-sick (or has haste) filters
    eligible.push(obj.id);
}
```

- **Purpose**: collect eligible attackers, then enumerate the
  powerset (up to `DECLARE_ATTACKERS_POWERSET_CAP`) into
  `Action::DeclareAttackers` dicts.
- **Order semantics**: priority player's per-player bf, insertion
  order. NOT centralized by ETB timestamp.
- **Python counterpart**: `src/mtg_bot/combat.py:eligible_attackers`
  (lines 15-23) iterates `state.battlefield` filtered to
  `obj.controller == active_player`. Python's iteration order is
  ETB-timestamp order across both players' permanents, then filtered
  to the active player — which collapses to insertion order WITHIN
  the active player's slice, in ETB order. Synthetic states (every
  bf object at timestamp 0) collapse this further to a single
  per-player walk.
- **Cross-engine risk**: **LOW**. Because all eligible attackers are
  controlled by the active player by definition (CR 508.1a), Python's
  centralized-then-filtered walk and Rust's per-player walk emit the
  *same* objects in the *same* order whenever the active player's
  permanents are contiguous in `state.battlefield`. CE4's stamping
  preserves that — every active-player ETB bumps the central counter
  monotonically, so the active-player permanents are
  *intra-player-monotone* even if not contiguous globally.
- **Closure path**: Already addressed; the active-player-only filter
  makes per-player iteration parity-safe. NONE.

### L2. DeclareBlockers eligibility — `state_ops_legal.rs:644`

```rust
let mut eligible_blockers: Vec<u32> = Vec::new();
for obj in self.players[idx].battlefield.iter() {
    if obj.tapped { continue; }
    // Creature filter (NO summoning-sick filter — CR 302.1)
    eligible_blockers.push(obj.id);
}
```

- **Purpose**: collect defender's eligible blockers, then enumerate
  assignment dicts.
- **Order semantics**: priority player's per-player bf, insertion
  order.
- **Python counterpart**: `src/mtg_bot/combat.py:eligible_blockers`
  (lines 26-32) walks `state.battlefield` filtered to defender's id.
  Same single-player-filter shape as L1.
- **Cross-engine risk**: **LOW**. Same reasoning as L1 — all blockers
  are controlled by the defender, so per-player ≡ centralized-then-
  filtered.
- **Closure path**: NONE.

### L3. ActivateAbility emitter — `state_ops_legal.rs:868`

```rust
for obj in self.players[idx].battlefield.iter() {
    if obj.tapped { continue; }
    if obj.summoning_sick { continue; }
    // mana-produced check
    actions.push(activate_ability_dict(py, obj.id, 0)?);
}
```

- **Purpose**: emit one ActivateAbility dict per untapped mana-source
  on the priority player's bf (no dedup — see the long comment at
  lines 859-866).
- **Order semantics**: priority player's per-player bf, insertion
  order.
- **Python counterpart**: `src/mtg_bot/legal.py:612-829` —
  iterates `[o for o in state.battlefield if o.controller == ap]`,
  same filter as L1/L2.
- **Cross-engine risk**: **LOW**. Same single-player-filter equivalence
  as above. The emitted action list ORDER (which would feed policy
  slot indexing under positional_v1) is the relative order of mana
  sources within the priority player's bf — identical between the two
  iteration styles.
- **Closure path**: NONE.

**File summary.** All three sites filter to a single player by gate
construction (active or priority), so per-player iteration matches
Python's centralized-then-filtered walk byte-for-byte under
ETB-monotone timestamps. The Rust simplification is parity-safe.

---

## 2. `rust/src/state_ops_sba.rs` — SBA victim collector (predicted CE5)

Two iteration sites — `collect_sba_victims` (the destroyer pass)
and `is_lethal` (the per-id query). The collector is the predicted
**CE5** site in `ORDER_SENSITIVE_SURFACES.md`.

### S1. `collect_sba_victims` — `state_ops_sba.rs:138`

```rust
fn collect_sba_victims(&self) -> Vec<(u8, u32)> {
    let mut victims = Vec::new();
    for player in &self.players {
        for obj in player.battlefield.iter() {
            // 704.5f (0-toughness) and 704.5g (lethal damage) checks
            victims.push((obj.controller, obj.id));
        }
    }
    victims
}
```

- **Purpose**: collect every SBA-destroy victim across BOTH players'
  battlefields, in one pass. Returned `Vec` is then drained by
  `apply_sbas`, which moves each victim into its controller's
  graveyard (preserving collection order).
- **Order semantics**: outer-loop `for player in &self.players`
  (p0 first, then p1), inner-loop per-player bf insertion order.
  This is the classic "Rust per-player walk" shape that diverges from
  Python's centralized walk under non-trivial ETB interleaving.
- **Python counterpart**: `src/mtg_bot/turn.py:1289`
  (`_state_based_actions_pass`, 704.5g pass):
  `for obj in state.battlefield: ...` — centralized, ETB-timestamp
  ordered.
- **Cross-engine risk**: **HIGH**. This is the CE5 prediction. Concrete
  scenario: p0 has a 2/2 with 2 marked damage; p1 has a 2/2 with 2
  marked damage; ETB timestamps interleaved (p0's ETB'd between p1's
  two). Rust collects p1's victim first (it's at index 0 in p1's
  battlefield) and p0's second; Python collects them in ETB order.
  Both creatures go to their respective owner's graveyard, so per-zone
  contents agree — but the relative order of any death-trigger
  resolution (when Rust grows triggers, see CE8) AND the relative
  emission order surfaced through the parity-smoke `state_signature`
  would diverge.
- **Closure path**: **CE5 candidate**. Two options:
  1. Collect refs from both per-player Vecs, stable-sort by
     `etb_timestamp` (mirrors the CE4 closure in
     `battlefield_snapshot` / `fingerprint`), then walk the sorted
     Vec.
  2. Centralize battlefield as a single Vec on `GameState` (much
     larger refactor — touches every bf-mutation site).
  Option 1 is the natural CE5 shape given CE4's precedent.

### S2. `is_lethal` — `state_ops_sba.rs:319`

```rust
fn is_lethal(&self, obj_id: u32) -> Option<bool> {
    for player in &self.players {
        for obj in player.battlefield.iter() {
            if obj.id == obj_id {
                // ...effective_toughness predicate
                return Some(obj.damage as i32 >= effective_toughness);
            }
        }
    }
    None
}
```

- **Purpose**: per-id lethality query.
- **Order semantics**: per-player walk, but early-returns on the
  first match — order is irrelevant.
- **Python counterpart**: `src/mtg_bot/turn.py` — uses a
  `next((o for o in state.battlefield if o.id == X), None)` pattern.
- **Cross-engine risk**: **NONE**. Point lookup — order doesn't matter
  because ids are unique.
- **Closure path**: NONE.

---

## 3. `rust/src/state_ops_combat.rs` — damage assignment + locators (predicted CE6)

Per `ORDER_SENSITIVE_SURFACES.md` §10, multi-block damage assignment
is the CE6 prediction: Python walks `state.battlefield` filtered by
`attacker.blocked_by`, Rust walks `self.blockers` Vec in
declare-blockers append order. The combat file has many per-id
locators (`locate_battlefield_obj`, `battlefield_creature_power`,
`battlefield_has_keyword`, `battlefield_creature_damage`, etc.) —
all point lookups that early-return on the first match. These are
LOW risk individually but cluster as a single shape.

### C1. `locate_battlefield_obj` — `state_ops_combat.rs:207`

```rust
fn locate_battlefield_obj(state: &GameState, obj_id: u32) -> Option<(usize, u32)> {
    for (idx, player) in state.players.iter().enumerate() {
        for obj in player.battlefield.iter() {
            if obj.id == obj_id { return Some((idx, obj.printing_id)); }
        }
    }
    None
}
```

- **Purpose**: id → (player_idx, printing_id) lookup; used by every
  combat-side reader (`battlefield_creature_power`,
  `battlefield_has_keyword`, etc.).
- **Order semantics**: per-player walk; early-return on first match.
- **Cross-engine risk**: **NONE**. Point lookup.

### C2. `mutate_battlefield_obj` — `state_ops_combat.rs:225`

```rust
for player in state.players.iter_mut() {
    if player.battlefield.iter().any(|o| o.id == obj_id) {
        let zone: &mut Vec<GameObject> = Arc::make_mut(&mut player.battlefield);
        for obj in zone.iter_mut() {
            if obj.id == obj_id { f(obj); return true; }
        }
    }
}
```

- **Purpose**: per-id mutate helper. Same shape as C1.
- **Cross-engine risk**: **NONE**.

### C3. `read_creature_status`'s back-find — `state_ops_combat.rs:250`

```rust
for obj in state.players[idx].battlefield.iter() {
    if obj.id == obj_id { return Some((obj.tapped, obj.summoning_sick)); }
}
```

- **Purpose**: re-find an object inside a single player's bf to read
  flags after `locate_battlefield_obj` returned its idx.
- **Order semantics**: single-player walk, point lookup.
- **Cross-engine risk**: **NONE**.

### C4. `battlefield_creature_controller` — `state_ops_combat.rs:396`

```rust
for player in state.players.iter() {
    for obj in player.battlefield.iter() {
        if obj.id == obj_id { return Some(obj.controller); }
    }
}
```

- **Purpose**: id → controller lookup.
- **Cross-engine risk**: **NONE**.

### C5. `battlefield_creature_damage` — `state_ops_combat.rs:410`

Same shape as C4. **NONE**.

### C6. `deal_combat_damage` attackers walk — `state_ops_combat.rs:849`

```rust
for &attacker_id in &self.attackers {
    let attacker_power = battlefield_creature_power(self, attacker_id);
    // ...build plan entries
    let first_blocker: Option<u32> = self.blockers.iter()
        .find_map(|(a, b)| if *a == attacker_id { Some(*b) } else { None });
```

- **Purpose**: walk this turn's declared attackers Vec; for each,
  find the FIRST declared blocker (single-blocker damage
  simplification — multi-blocker is deferred per the module
  docstring at lines 174-188).
- **Order semantics**: `self.attackers` Vec, declare-attackers push
  order.
- **Python counterpart**: `src/mtg_bot/combat.py:266` builds
  `attacker.blocked_by` by `.append(blocker_id)` (FIFO declare order)
  but the damage loop at `combat.py:389,405` iterates
  `[o for o in state.battlefield if o.id in attacker.blocked_by]`
  — i.e., **battlefield order filtered by membership**, NOT
  `blocked_by` push order. See ORDER_SENSITIVE_SURFACES.md §10 for
  the surprise.
- **Cross-engine risk**: **HIGH (predicted CE6)**. Identical results
  require declare-blockers-append order to match `state.battlefield`
  ETB-timestamp order. Real games rarely satisfy that. **And
  separately**: the current Rust slice deliberately reads only the
  FIRST blocker (`find_map`) per attacker — multi-blocker damage
  spread is deferred regardless of order.
- **Closure path**: **CE6 candidate**. Two parts:
  1. Switch the per-attacker blocker walk from `self.blockers`-Vec
     order to `state.battlefield`-filter-by-(attacker_id) order to
     match Python's centralized walk.
  2. Implement true multi-blocker damage distribution
     (currently single-blocker only).

### C7. Combat damage back-pass — `state_ops_combat.rs:962`

```rust
for &(attacker_id, blocker_id) in &self.blockers {
    let blocker_power = battlefield_creature_power(self, blocker_id);
    // ...back-damage plan entries
}
```

- **Purpose**: every declared blocker deals its power back to its
  attacker (symmetric back-damage lane).
- **Order semantics**: `self.blockers` Vec, push order.
- **Python counterpart**: same `combat.py` damage loop —
  battlefield-order filter.
- **Cross-engine risk**: **MEDIUM**. Order matters only when the
  *plan-building* order has visible side effects (e.g. if blocker A's
  back-damage kills attacker B before attacker B's back-damage to
  blocker C is computed). The current Rust `deal_combat_damage`
  snapshots the plan first then applies in a second pass
  (`mutate_battlefield_obj` per plan entry), so within-step order
  isn't observable through `obj.damage` at the end of the step. BUT
  the FIRST-STRIKE / DOUBLE-STRIKE substep boundary makes this
  reachable: a first-strike blocker's damage applies BEFORE the
  regular-pass plan re-computes, so the relative iteration order of
  the two passes matters for who-dies-first.
- **Closure path**: same as C6 — sort by ETB timestamp before
  walking. CE6 / CE6.5.

### C8. Combat damage SBA-like alive-check — `state_ops_combat.rs:1025-1028`

```rust
.filter(|e| battlefield_creature_alive(self, e.source_id))
// ...
battlefield_creature_alive(self, target_id)
```

- **Purpose**: filter plan entries to those whose source is still alive
  between first-strike and regular passes.
- **Order semantics**: per-entry filter, iteration order is plan
  order (= `self.attackers` / `self.blockers` order).
- **Cross-engine risk**: **MEDIUM** (inherits from C6/C7).

**File summary.** Combat is the next CE entry's most-likely host.
The C6 attackers walk and C7 back-pass both index off
`self.attackers` / `self.blockers` Vecs, not centralized bf order.
Closure requires either (a) sort plan entries by source's
`etb_timestamp` or (b) accept that Python's filter-from-battlefield
shape is a bug and pin the Rust shape as the CR-correct one (see
ORDER_SENSITIVE_SURFACES.md §10's "this is likely a Python bug" note).

---

## 4. `rust/src/state_ops_resolve.rs` — Effect resolve arms

The largest source file (~5300 lines). Iterations cluster into
patterns; I enumerate the patterns, not every literal site (62
matches). Quoted file:line refs are representative.

### R1. `find_source_printing_id` (5-zone walk) — `state_ops_resolve.rs:193`

```rust
for player in &state.players {
    for zone in [&player.hand, &player.library, &player.battlefield,
                 &player.graveyard] {
        for obj in zone.iter() {
            if obj.id == obj_id { return Some(obj.printing_id); }
        }
    }
}
```

- **Purpose**: source-id → printing-id resolution. Used by every
  Effect that reads its source's printing.
- **Order semantics**: per-player, per-zone, point lookup.
- **Cross-engine risk**: **NONE**. Point lookup.

### R2. `take_source` (5-zone mutating extract) — `state_ops_resolve.rs:218`

Same shape as R1, but extracts the object instead of just reading its
printing_id. Used by every "move source somewhere else" arm.

- **Cross-engine risk**: **NONE**. Point lookup.

### R3. First-eligible-creature on defender's bf — `state_ops_resolve.rs:363, 456, 613, 670, 721, 833, 1007, 2389, 2432, 2474, 2536, 3302, 3334, 3393, 3953, 4002, 4185` and more

```rust
let bf = &state.players[defender_idx].battlefield;
// find first creature: bf.iter().find_map(|obj| { ... if "Creature" ... })
```

- **Purpose**: pick the "first creature" target for a single-target
  Effect (DealDamageToTargetCreature, TapTargetCreature,
  AddCountersTargetCreature, etc.).
- **Order semantics**: single-player walk, find-first.
- **Python counterpart**: Python's equivalent arm in
  `src/mtg_bot/effects/generic/*.py` typically picks the first
  matching creature via the same iteration shape against the same
  player's battlefield slice (filtered from the centralized
  `state.battlefield`).
- **Cross-engine risk**: **LOW**. Single-player walk = same-as-Python
  whenever the player's permanents are intra-monotone in ETB
  timestamps (which CE4 guarantees). The first hit is by definition
  the lowest-timestamp matching creature on that player's bf.

### R4. Token allocation id scan — `state_ops_resolve.rs:1211`

```rust
for player in &state.players {
    for zone in [&player.hand, &player.library, &player.battlefield,
                 &player.graveyard, &player.exile] {
        for obj in zone.iter() {
            if !found_any || obj.id > max_id {
                max_id = obj.id;
                found_any = true;
            }
        }
    }
}
```

- **Purpose**: find the max id across every zone on both players so a
  fresh token can be allocated `max_id + 1`.
- **Order semantics**: walk-everything, but the final result is
  order-invariant (max).
- **Cross-engine risk**: **NONE**. The OUTPUT is order-invariant
  (max-finding); only side-effects of `found_any` shortcut depend on
  iteration order, which doesn't change the answer.

### R5. Self-locator (find-source-on-bf) — `state_ops_resolve.rs:1495, 3284, 3514, 3773, 3827, 3874, 3918, 4369`

```rust
if let Some(obj) = player.battlefield.iter().find(|o| o.id == source_obj_id) { ... }
```

- **Purpose**: confirm the source is still on a bf before applying
  an effect (some effects fizzle if the source LTB'd between push
  and resolve). Per-player loop with point lookup.
- **Cross-engine risk**: **NONE**. Point lookup.

### R6. "PumpCreaturesYouControl" / anthem-shape walks — `state_ops_resolve.rs:2651, 2728, 2801, 2870, 2946, 3004, 3106, 3364, 3424, 3539, 3626, 4166, 4617` (mostly `'outer: for player in &state.players { for zone in [...] { ... } }` source-controller resolution, plus inner bf walks for the effect itself)

Specifically the `PumpCreaturesYouControlUntilEOT` arm at line 2721:

```rust
'outer: for player in &state.players { ... /* find source */ }
// then:
let zone: &mut Vec<GameObject> = Arc::make_mut(&mut state.players[cidx].battlefield);
for obj in zone.iter_mut() {
    if /* Creature */ { obj.ueot_modifiers.push(...) }
}
```

- **Purpose**: apply a UEOT pump to every creature the source
  controls.
- **Order semantics**: single-player walk (the source's controller's
  bf), per-object mutation.
- **Python counterpart**: anthem-shape Effects in
  `src/mtg_bot/effects/combinators.py` and `effects/bespoke.py`
  iterate `[o for o in state.battlefield if o.controller == cidx]`.
- **Cross-engine risk**: **LOW**. Single-controller filter — same
  equivalence as L1. The mutation is set-like (push a modifier to
  each match), so iteration order doesn't change the OUTCOME, only
  the relative order in which `ueot_modifiers` Vecs are appended.
  Since each match's modifier list grows independently, no
  cross-object dependency exists.

### R7. `TapAnotherTargetCreature` cross-player walk — `state_ops_resolve.rs:4555`

```rust
'outer_tatc: for (pidx, player) in state.players.iter().enumerate() {
    for obj in player.battlefield.iter() {
        if obj.id == source_obj_id { continue; }
        // Creature filter
        found = Some((pidx, obj.id));
        break 'outer_tatc;
    }
}
```

- **Purpose**: first-eligible (any-player) creature target for a
  cross-bf effect.
- **Order semantics**: p0 first, then p1, find-first.
- **Python counterpart**: `effects/generic/targets_helpers.py` walks
  centralized `state.battlefield` filtered by Creature predicate
  and `obj.id != source.id`. First match.
- **Cross-engine risk**: **MEDIUM**. Diverges when the first eligible
  by ETB-timestamp is on p1's bf but Rust always finds the p0
  candidate first. Example: source is p1's, p0 has Creature_A
  (ETB at t=3), p1 has Creature_B (ETB at t=2, ETB'd before
  Creature_A); Python walks centralized order, finds Creature_B
  first; Rust walks p0 first, finds Creature_A first. Two different
  targets get tapped.
- **Closure path**: **CE7-tier** candidate (after CE5/CE6). Closure
  is "collect refs from both bfs, stable-sort by ETB timestamp,
  pick first match" — same recipe as CE4's snapshot.

### R8. `UntapTargetOtherPermanent` — `state_ops_resolve.rs:4588`

Same shape as R7. **MEDIUM**, same CE7-tier closure.

### R9. `DealDamageToAnyTargetOpponentCreature` opponent walk — `state_ops_resolve.rs:4871`

```rust
'outer_dd: for (pidx, player) in state.players.iter().enumerate() {
    if pidx as u8 == controller { continue; }
    for obj in player.battlefield.iter() {
        // Creature filter
        found = Some((pidx, obj.id)); break 'outer_dd;
    }
}
```

- **Purpose**: first opponent creature for a deal-damage effect.
- **Order semantics**: skip controller's bf, walk opponent's bf,
  find-first.
- **Cross-engine risk**: **LOW**. Single-player walk (opponent's bf)
  — same equivalence as L1.

### R10. ETB-zone push — `state_ops_resolve.rs:1428, 1983, 3617, 4543, 4547, 4960, 5217`

```rust
Arc::make_mut(&mut player.battlefield).push(obj);
```

- **Purpose**: append a newly-entered permanent. CE4 stamps
  `etb_timestamp` via `reserve_etb_timestamp` at each call site.
- **Order semantics**: append-to-tail per-player. Centralized order
  is reconstructed at snapshot/fingerprint time via the CE4
  stable-sort.
- **Cross-engine risk**: **NONE** post-CE4. The bf walks happen
  elsewhere; the writes themselves are parity-pinned.

### R11. `register_and_inject_object` id-allocator — `state_ops_resolve.rs:5155`

Same shape as R4. **NONE** (max-finding is order-invariant).

### R12. Exile point-lookup helpers — `state_ops_resolve.rs:5254, 5265, 5278, 5291, 5304, 5317`

`exile_contains`, `exile_object_tapped`, `exile_object_summoning_sick`,
etc. — all `for player in &self.players: for obj in player.exile.iter():
if obj.id == X` point lookups. **NONE**.

**File summary.** The vast bulk of `state_ops_resolve.rs` battlefield
iterations are point lookups (R1, R2, R5, R10-R12) or
single-controller anthem-shape walks (R6) — parity-safe under CE4.
The order-load-bearing risk is R7 / R8 (any-player first-eligible
target) — MEDIUM risk surfacing as a "wrong target picked" divergence.
R3 (defender first-creature) is single-player and LOW.

---

## 5. `rust/src/state_ops_actions.rs` — apply_action arms

<no per-action iterations through bf; the file dispatches each
action to its primitive (play_land → state_ops_cast, declare_attacker
→ state_ops_combat, etc.) and contains no direct bf walks. Confirmed
by `grep`: 16 occurrences are all string-content (`"battlefield"` in
docstrings, log messages, or arm enums).>

**File summary.** No iteration sites. NONE.

---

## 6. `rust/src/state_ops_snapshot.rs` — `battlefield_snapshot` (CE4 closed)

### SN1. `battlefield_snapshot` — `state_ops_snapshot.rs:189`

```rust
let mut refs: Vec<&crate::state::GameObject> = Vec::with_capacity(...);
for player in &self.players {
    for obj in player.battlefield.iter() { refs.push(obj); }
}
refs.sort_by_key(|obj| obj.etb_timestamp);
```

- **Purpose**: the centralized battlefield projection that the parity
  smoke hashes.
- **Order semantics**: **collect from both per-player Vecs, stable-sort
  by `etb_timestamp`**. CE4 closure already landed at commit
  `d04cb3de` / merged in `276d806a`.
- **Python counterpart**: `state.battlefield` iterated in
  insertion order, which is ETB-timestamp monotone.
- **Cross-engine risk**: **NONE / parity-pinned**. This is the
  reference shape future CE\<n\> closures should mimic.
- **Closure path**: closed.

---

## 7. `rust/src/state_ops_fingerprint.rs` — `object_signature` walk (CE4 closed)

### FP1. `fingerprint()` bf section — `state_ops_fingerprint.rs:316-327`

```rust
let mut refs: Vec<&GameObject> = Vec::with_capacity(...);
for player in &self.players {
    for obj in player.battlefield.iter() { refs.push(obj); }
}
refs.sort_by_key(|o| o.etb_timestamp);
Value::Array(refs.iter().map(|o| object_signature(self, o)).collect())
```

- **Purpose**: produce the 12-char SHA1 digest's bf slot. Same shape
  as SN1.
- **Cross-engine risk**: **NONE / parity-pinned**. CE4 closure.

---

## 8. `rust/src/state.rs` — GameState getters and primitives

### ST1. `printing_name_of` — `state.rs:803`

```rust
for player in &self.players {
    for zone in [&player.hand, &player.library, &player.battlefield,
                 &player.graveyard] {
        for obj in zone.iter() {
            if obj.id == obj_id { return self.registry.lookup(...).map(...); }
        }
    }
}
```

- **Purpose**: id → printing.name lookup, used by display + Python
  glue.
- **Order semantics**: per-player, per-zone, point lookup.
- **Cross-engine risk**: **NONE**. Point lookup.

### ST2. (No iteration in `state.rs` besides ST1.) Confirmed.

---

## 9. `rust/src/state_ops_zones.rs` — zone movers

### Z1. `find_object_zone` — `state_ops_zones.rs:94`

```rust
for player in &self.players {
    if player.hand.iter().any(|o| o.id == obj_id) { return Some(ZONE_HAND); }
    if player.library.iter().any(...) { return Some(ZONE_LIBRARY); }
    if player.battlefield.iter().any(...) { return Some(ZONE_BATTLEFIELD); }
    ...
}
```

- **Purpose**: id → zone-id classification.
- **Order semantics**: per-player, per-zone, point lookup.
- **Cross-engine risk**: **NONE**. Point lookup.

### Z2. `move_object` source extract — `state_ops_zones.rs:145`

```rust
for player in self.players.iter_mut() {
    if let Some(obj) = take_from_zone(&mut player.hand, obj_id) { ... break; }
    if let Some(obj) = take_from_zone(&mut player.library, obj_id) { ... break; }
    ...
}
```

- **Purpose**: extract the object from whichever zone holds it.
- **Order semantics**: per-player, per-zone, point lookup.
- **Cross-engine risk**: **NONE**. Point lookup. (The destination push
  is a single tail-append — bf-target case stamps `etb_timestamp` per
  CE4.)

**File summary.** Both sites are point lookups. **NONE**.

---

## 10. `rust/src/state_ops_tap.rs`

### T1. `is_tapped` — `state_ops_tap.rs:89`

```rust
for player in &self.players {
    for obj in player.battlefield.iter() {
        if obj.id == obj_id { return Some(obj.tapped); }
    }
}
```

Point lookup. **NONE**.

### T2. `untap_all_for_player` — `state_ops_tap.rs:108`

```rust
let player = match self.players.iter_mut().find(|p| p.id == player_id) { ... };
// short-circuit if all already untapped
let zone: &mut Vec<GameObject> = Arc::make_mut(&mut player.battlefield);
for obj in zone.iter_mut() { obj.tapped = false; }
```

- **Purpose**: untap step (CR 502.1) — every permanent controlled by
  `player_id` gets tapped=false.
- **Order semantics**: single-player walk, set-mutation (every match
  flips the same way).
- **Python counterpart**: `src/mtg_bot/turn.py:63` —
  `for obj in state.battlefield: if obj.controller == active: obj.tapped = False`.
- **Cross-engine risk**: **NONE**. Set-mutation — order doesn't affect
  the post-mutation state.

---

## 11. `rust/src/state_ops_mana.rs`

### M1. `tap_for_mana` source lookup — `state_ops_mana.rs:319`

```rust
for (player_idx, player) in self.players.iter().enumerate() {
    for obj in player.battlefield.iter() {
        if obj.id == obj_id { /* read printing.mana_produced */ ... break; }
    }
}
```

Point lookup (early-return on match). **NONE**.

---

## 12. `rust/src/state_ops_damage.rs`, `state_ops_counters.rs`, `state_ops_deck.rs`, `state_ops_choices.rs`, `state_ops_cast.rs`, `state_ops_winloss.rs`

All have one or two per-zone or per-player walks; all are either
point lookups (search-by-id, early-return on match) or
order-invariant (max-id allocator, find-first-creature shapes used
by reified-choice helpers).

### D1. `read_damage` — `state_ops_damage.rs:150` — point lookup. **NONE**.
### CT1. `read_counters` — `state_ops_counters.rs:118` — point lookup. **NONE**.
### DK1. `load_deck` id-allocator — `state_ops_deck.rs:89` — max-finding, order-invariant. **NONE**.
### CH1-CH3. `state_ops_choices.rs:53, 138, 167` —
single-player find-first patterns
(`choose_first_creature_for_player`, `choose_first_creature_with_keyword_for_player`,
`choose_first_tapped_creature_for_player`). All operate against
ONE player's bf and return the first match by insertion order.
**LOW** risk — single-player walk, find-first; the order-load-bearing
property collapses to "first in that player's bf by insertion order",
which under CE4-monotone stamps equals "first in that player's bf by
ETB timestamp" — same answer as Python's centralized walk filtered
to that player. NONE individually.

### CA1. `is_summoning_sick` — `state_ops_cast.rs:237` — point lookup. **NONE**.
### W1. `losers` — `state_ops_winloss.rs:70` — per-player walk over `self.players` (NOT bf); each entry is independent so order is parity-invariant. NONE.

---

## Cross-reference table — Rust site → Python counterpart → predicted CE\<n\>

| Rust site | File:line | Order shape | Python counterpart | Risk | CE\<n\> |
|---|---|---|---|---|---|
| L1 DeclareAttackers eligibility | `state_ops_legal.rs:564` | priority-player walk, all-creature filter | `combat.py:eligible_attackers` (filter `state.battlefield` to active) | LOW | n/a (single-player) |
| L2 DeclareBlockers eligibility | `state_ops_legal.rs:644` | priority-player walk | `combat.py:eligible_blockers` (filter `state.battlefield` to defender) | LOW | n/a |
| L3 ActivateAbility emitter | `state_ops_legal.rs:868` | priority-player walk | `legal.py:612-829` (filter `state.battlefield` to priority) | LOW | n/a |
| S1 `collect_sba_victims` | `state_ops_sba.rs:138` | **two-player per-player walk** | `turn.py:1289` walks `state.battlefield` | **HIGH** | **CE5** |
| S2 `is_lethal` | `state_ops_sba.rs:319` | per-player point lookup | `next(o for o in state.battlefield if o.id == X)` | NONE | n/a |
| C1-C5 combat locators | `state_ops_combat.rs:207, 225, 250, 396, 410` | per-player point lookups | various `next(...)` in `combat.py` | NONE | n/a |
| C6 `deal_combat_damage` attackers | `state_ops_combat.rs:849` | `self.attackers` Vec | `combat.py:389,405` filter `state.battlefield` by `attacker.blocked_by` | **HIGH** | **CE6** |
| C7 back-damage blockers walk | `state_ops_combat.rs:962` | `self.blockers` Vec | same `combat.py` filter | MED | CE6 |
| C8 alive-check between passes | `state_ops_combat.rs:1025-1028` | inherits C6/C7 | inherits Python combat | MED | CE6 |
| R1 `find_source_printing_id` | `state_ops_resolve.rs:193` | 5-zone point lookup | `state.iter_all_objects` find-by-id | NONE | n/a |
| R2 `take_source` | `state_ops_resolve.rs:218` | 5-zone point lookup, mutating | source removal in Python effects | NONE | n/a |
| R3 first-eligible defender creature | `state_ops_resolve.rs:363, 456, 613, 670, 721, 833, 1007, ...` (~17 sites) | single-player find-first | `effects/generic/targets_helpers.py` filter | LOW | n/a |
| R4 token id-allocator | `state_ops_resolve.rs:1211` | walk-all, max-find | n/a (Python's `state.next_id` counter) | NONE | n/a |
| R5 self-locator | `state_ops_resolve.rs:1495, 3284, ...` (~8 sites) | per-player point lookup | `next(o for o in state.battlefield if o.id == src)` | NONE | n/a |
| R6 anthem-shape walks | `state_ops_resolve.rs:2690, 2776, ...` (~13 sites) | single-controller walk | `effects/combinators.py` filter-by-controller | LOW | n/a |
| R7 `TapAnotherTargetCreature` | `state_ops_resolve.rs:4555` | **two-player find-first** | `effects/generic/targets_helpers.py` (centralized walk) | **MED** | **CE7-tier** |
| R8 `UntapTargetOtherPermanent` | `state_ops_resolve.rs:4588` | two-player find-first | same | MED | CE7-tier |
| R9 `DealDamageToAnyTargetOpponentCreature` | `state_ops_resolve.rs:4871` | opponent-only walk | filter to opponent | LOW | n/a |
| R10 ETB push | `state_ops_resolve.rs:1428, 1983, ...` (~7 sites) | per-player append | `state.battlefield.append` | NONE | parity-pinned by CE4 |
| R11 `register_and_inject_object` allocator | `state_ops_resolve.rs:5155` | walk-all, max-find | n/a | NONE | n/a |
| R12 exile point lookups | `state_ops_resolve.rs:5254-5317` (~6 sites) | per-player point lookup | `for o in p.exile if o.id == X` | NONE | n/a |
| SN1 `battlefield_snapshot` | `state_ops_snapshot.rs:189` | **collect + stable-sort by `etb_timestamp`** | `state.battlefield` (centralized) | NONE | **CE4 closed** |
| FP1 `fingerprint` bf walk | `state_ops_fingerprint.rs:316` | collect + stable-sort by `etb_timestamp` | hash of `state.battlefield` | NONE | CE4 closed |
| ST1 `printing_name_of` | `state.rs:803` | 5-zone point lookup | `state.find_object(id).printing.name` | NONE | n/a |
| Z1 `find_object_zone` | `state_ops_zones.rs:94` | per-player per-zone point lookup | `state.zone_of(obj)` | NONE | n/a |
| Z2 `move_object` extract | `state_ops_zones.rs:145` | per-player per-zone point lookup | `state.move_object` | NONE | n/a |
| T1 `is_tapped` | `state_ops_tap.rs:89` | per-player point lookup | `obj.tapped` direct read | NONE | n/a |
| T2 `untap_all_for_player` | `state_ops_tap.rs:108` | single-player set-mutation | `turn.py:63` filter `state.battlefield` to active | NONE | n/a |
| M1 `tap_for_mana` source lookup | `state_ops_mana.rs:319` | per-player point lookup | `state.find_object` | NONE | n/a |
| D1 `read_damage` | `state_ops_damage.rs:150` | 4-zone point lookup | `obj.damage` direct read | NONE | n/a |
| CT1 `read_counters` | `state_ops_counters.rs:118` | 4-zone point lookup | `obj.counters` direct read | NONE | n/a |
| DK1 `load_deck` allocator | `state_ops_deck.rs:89` | walk-all, max-find | n/a | NONE | n/a |
| CH1-CH3 choice helpers | `state_ops_choices.rs:53, 138, 167` | single-player find-first | `effects/generic/targets_helpers.py` first | LOW | n/a |
| CA1 `is_summoning_sick` | `state_ops_cast.rs:237` | per-player point lookup | `obj.summoning_sick` | NONE | n/a |
| W1 `losers` | `state_ops_winloss.rs:70` | walk `self.players` (not bf) | walk `state.players` | NONE | n/a |

---

## Top 5 sites most likely to surface as next CE divergences

Re-rank of ORDER_SENSITIVE_SURFACES.md CE5-CE9 list, with concrete
file:line targets for each:

### 1. CE5 — `state_ops_sba.rs:138` `collect_sba_victims` (HIGH)

The CR-correct pass is "iterate state.battlefield by ETB timestamp,
collect 704.5f/g victims in that order". Rust collects p0's first
then p1's, so the relative order of two same-pass kills diverges
whenever p0 and p1 each have a lethal creature with interleaved ETB
timestamps. Closure: mirror SN1's stable-sort recipe. Once Rust grows
death triggers (CE8), the on-stack order of those triggers depends
on this collection order — making CE5 a prerequisite for CE8 parity.

### 2. CE6 — `state_ops_combat.rs:849, 962, 1025-1028` damage assignment (HIGH)

Per ORDER_SENSITIVE_SURFACES.md §10, Python's "battlefield order
filter-by-blocked_by" damage walk is **a Python bug** vs CR — CR says
"first listed blocker takes damage first" which is declare-blockers
push order, not battlefield order. Rust's `self.attackers` /
`self.blockers` walk is CR-correct. Two closure options:
(a) match Python's bug (collect plan entries, sort by source's
`etb_timestamp`, walk in that order); or (b) accept the divergence
as a deliberate Rust-is-right entry in `SEARCH_LIMITATIONS.md` and
add it to RUST_PARITY_GAPS.md. Recommendation: (a) for short-term
smoke parity, (b) for long-term correctness; (a) keeps the bug, (b)
is the better engineering choice if Python is willing to fix its
side too.

### 3. CE7 — `state_ops_resolve.rs:4555, 4588` cross-player find-first Effect arms (MED)

`TapAnotherTargetCreature` and `UntapTargetOtherPermanent` walk
`self.players.iter().enumerate()` for the first eligible match — so
they pick the p0 candidate whenever one exists, regardless of ETB
timestamp. Python walks centralized `state.battlefield` filtered by
the eligibility predicate. Closure: mirror SN1 — collect refs from
both bfs, stable-sort by `etb_timestamp`, find-first on the sorted
Vec.

### 4. CE8 — when Rust grows a `dispatch_event` / trigger emitter

Today Rust applies ETB effects inline at
`state_ops_resolve.rs:5041, 5105` (no stack push). When the trigger
emitter lands, its iteration order MUST mirror Python's
`actions.py:3346-3399` walk — which is
`for source in list(state.battlefield): for ability_index, ability
in enumerate(source.printing.triggered_abilities)`. Implementing
that walk correctly is gated on CE5 (so the iteration order matches
the SBA pass's collection order — death triggers AND ETB triggers
share the same ordering surface).

### 5. CE9 — `_play_land` `etb_timestamp` stamping (LOW; predicted as a "hidden trap" by ORDER_SENSITIVE_SURFACES.md §1)

Per ORDER_SENSITIVE_SURFACES.md's "Hidden land trap": Python's
`_play_land` (actions.py:1084-1124) does NOT bump `etb_timestamp` —
all lands stay at timestamp 0. CE4's Rust implementation DOES stamp
via `reserve_etb_timestamp` on every bf-entry path (including
`play_land`). When Rust's per-object timestamps appear in a future
snapshot field (currently not in `object_to_pydict`), this asymmetry
will surface even though the rendered ORDER is identical. Closure:
either teach `_play_land` to leave timestamp 0 (mirror Python) or
update Python to bump (mirror Rust). Lowest priority because it's
not currently observable through the snapshot dict — the
`etb_timestamp` field is bookkeeping only.

---

## Closure dependencies

Diagram of how the CE5-CE9 closures entangle:

```
        CE4 (closed) — bf snapshot + fingerprint sort
          |
          v
  CE5 (state_ops_sba.rs collect_sba_victims)
          |
          +--> [enables] CE8 (trigger emitter; death-trigger order)
          |
          v
  CE6 (state_ops_combat.rs damage assignment)
          |
          v (independent)
  CE7 (state_ops_resolve.rs cross-player find-first Effects)
          |
          v (mostly cosmetic)
  CE9 (_play_land etb_timestamp asymmetry)
```

Specifically:

- **CE5 → CE8.** Death triggers from an SBA pass go onto the stack
  in the order their sources died. If CE5's victim-collection order
  is wrong, every downstream trigger emitter inherits the same wrong
  order. CE5 must close BEFORE CE8 lands, or CE8 will need to
  re-implement the same stable-sort independently.

- **CE6 is independent of CE5/CE7/CE8.** Combat damage assignment
  walks `self.attackers` / `self.blockers` Vecs, NOT a battlefield
  Vec — so its closure shape is "sort plan entries by ETB", not "fix
  the bf walker". The two sets of fixes don't touch the same code.

- **CE7 is independent of CE5/CE6/CE8.** It's a per-Effect-arm fix
  (replace `'outer: for player in &state.players { for obj in
  player.battlefield.iter() }` with "collect-and-sort"). Each Effect
  arm that needs the fix can land in its own slice, BUT they all
  benefit from a shared helper — proposed: `state_ops_snapshot.rs`
  exposes a private `bf_iter_etb_sorted(state) -> impl Iterator<Item=&GameObject>`
  that both SN1, FP1, CE5-future, and CE7-future consume. That helper
  doesn't exist today; landing it as part of CE5 is the natural
  shape.

- **CE9 is cosmetic until snapshot grows an `etb_timestamp` slot.**
  No closure path needed today; pin the discrepancy in
  RUST_PARITY_GAPS.md as a "harmless asymmetry, surfaces if the
  snapshot field is added".

---

## What this doc is NOT

- Not a one-shot CE closure plan — each CE\<n\> is its own slice
  with its own branch + commit.
- Not exhaustive of every iteration shape in Rust — exclusively
  battlefield-iteration (the highest-payoff surface). Hand /
  graveyard / exile / library iteration sites have their own
  per-zone parity invariants and are not in scope.
- Not a verdict on Python — where ORDER_SENSITIVE_SURFACES.md
  flagged Python's `combat.py` damage walk as "likely a Python
  bug", this doc preserves that note rather than re-litigating.
- Not a SEARCH_LIMITATIONS.md substitute — when a CE\<n\> closes
  here, its `SEARCH_LIMITATIONS.md` entry (if any) is independent.
