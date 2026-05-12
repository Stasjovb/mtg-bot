# CE5 / CE6 / CE7 closure playbook

Pre-staged closure plan for the next three predicted cross-engine
divergences in the Rust port. Synthesises the file:line work-item maps
from `docs/ORDER_SENSITIVE_SURFACES.md` (the Python-side audit, merged
in `1be3e0c4`) and `docs/RUST_BF_ITERATION_AUDIT.md` (the Rust-side
companion, merged in `d1239fc3`) into a single checklist a future
closure-slice agent can execute without re-deriving anything from the
audits.

This doc deliberately repeats key facts from the audits — the value is
having one place a slice author can read top-to-bottom.

**Status when this doc was written (2026-05-11, post-d1239fc3):**

- CE1 / CE2 / CE3 / CE4 are CLOSED (see `RUST_PARITY_GAPS.md` and the
  CE4 merge commit `276d806a` for the reference closure pattern).
- The cast-creature probe is in flight; it is expected to surface CE5
  (the predicted highest-priority next divergence) when it lands.
- I26 in `RUST_PARITY_GAPS.md` pins the post-CE4 invariant: the
  battlefield-walking readers (`battlefield_snapshot`, fingerprint's
  bf slot) stable-sort by `etb_timestamp`. CE5/CE6/CE7 closures follow
  that same recipe.

---

## Section 1: Shared helper proposal — `bf_iter_etb_sorted`

### Signature

```rust
/// Centralized walk of all battlefield objects across BOTH players,
/// ordered by ETB timestamp (matching Python's `state.battlefield`
/// append-order). Stable-sort: ties (same `etb_timestamp` — possible
/// only when a state's bf was pre-populated without going through a
/// `reserve_etb_timestamp` call, e.g. synthetic-state fixtures) are
/// broken by the original p0-then-p1, insertion-order walk so
/// pre-CE4 pinned baselines stay bit-equal.
///
/// **Borrowing.** Returns a `Vec<&GameObject>` (NOT an `impl Iterator`)
/// because the underlying p0 + p1 `Arc<Vec<GameObject>>` zones live in
/// separate places on `GameState` and sorting requires a materialized
/// container. The cost is one Vec allocation per call (~16-32 elems
/// in realistic states); the audit's 37 iteration sites are all in
/// non-hot paths (SBA pass, Effect resolution, target selection).
///
/// **Read-only.** This helper does not expose a mutable form because
/// every mutating consumer (CE5's SBA destroy pass, CE7's
/// tap/untap target) needs to first IDENTIFY the target via this
/// read-only walk, then EXTRACT and MUTATE via the existing per-player
/// `Arc::make_mut` primitives. The collect-then-mutate idiom is the
/// CE4 precedent (`state_ops_sba.rs::apply_sbas` already does this).
pub(crate) fn bf_iter_etb_sorted(state: &GameState) -> Vec<&GameObject>;
```

### Recommended location

**New file: `rust/src/bf_iter.rs`** (preferred), exporting
`pub(crate) fn bf_iter_etb_sorted`.

Alternative: dropped into `rust/src/state_ops_snapshot.rs` as a
`pub(crate)` sibling of the `battlefield_snapshot` impl. The audit
suggests this in §4 R7 / "Closure dependencies" §3 of
`RUST_BF_ITERATION_AUDIT.md`:

> proposed: `state_ops_snapshot.rs` exposes a private
> `bf_iter_etb_sorted(state) -> impl Iterator<Item=&GameObject>` that
> both SN1, FP1, CE5-future, and CE7-future consume.

I recommend a new file (`bf_iter.rs`) over sticking it in
`state_ops_snapshot.rs` because:

1. It's logically distinct: `state_ops_snapshot.rs` exists to project
   `GameState` → Python dicts. The helper is a primitive of the
   *engine internals*; non-snapshot consumers (SBA, combat, resolve)
   shouldn't have to reach into a snapshot module.
2. CE5 + CE6 + CE7 + CE8 (when it lands) + the existing
   `state_ops_snapshot.rs::battlefield_snapshot` + the existing
   `state_ops_fingerprint.rs::fingerprint` will all consume it — that's
   six call sites across six different modules. A dedicated module
   keeps every consumer's import line consistent.
3. The audit explicitly notes the helper is "shared" — making it a
   peer module instead of nested-under-snapshot signals that.

### Implementation sketch

```rust
// rust/src/bf_iter.rs

use crate::state::{GameObject, GameState};

/// See the docstring on the public declaration for invariants.
pub(crate) fn bf_iter_etb_sorted(state: &GameState) -> Vec<&GameObject> {
    let mut refs: Vec<&GameObject> = Vec::with_capacity(
        state.players[0].battlefield.len()
            + state.players[1].battlefield.len(),
    );
    for player in &state.players {
        for obj in player.battlefield.iter() {
            refs.push(obj);
        }
    }
    // Stable sort: ties (synthetic-state fixtures with default-0
    // timestamps) preserve the p0-then-p1 walk, keeping pre-CE4
    // baselines bit-equal.
    refs.sort_by_key(|o| o.etb_timestamp);
    refs
}
```

**Post-CE5 refactor (housekeeping):** rewrite the two existing
stable-sort sites in `state_ops_snapshot.rs::battlefield_snapshot`
(line 189) and `state_ops_fingerprint.rs::fingerprint` (lines 316-327)
to call `bf_iter_etb_sorted` instead of inlining the collect-and-sort.
That's a 1-line replacement per site + import. NOT mandatory for the
CE5 closure itself — landing the helper and inlining-into-CE5 first is
fine; the snapshot/fingerprint refactor can be a follow-up.

### Consumers (post-closure)

| Consumer | Site | Status |
|---|---|---|
| `battlefield_snapshot` | `state_ops_snapshot.rs:189` | CE4-closed, inlined — refactor to call helper post-CE5 |
| `fingerprint` bf walk | `state_ops_fingerprint.rs:316-327` | CE4-closed, inlined — refactor to call helper post-CE5 |
| SBA victim collection | `state_ops_sba.rs:138` `collect_sba_victims` | **CE5 closure target** |
| Combat damage assignment | `state_ops_combat.rs:849, 962, 1025-1028` | **CE6 closure target** (see Section 3 for the indirection) |
| `TapAnotherTargetCreature` | `state_ops_resolve.rs:4555` | **CE7 closure target** |
| `UntapTargetOtherPermanent` | `state_ops_resolve.rs:4588` | **CE7 closure target** |
| Future trigger emitter | (gated on CE8 substrate) | inherits via CE5 closure |

---

## Section 2: CE5 closure plan — SBA victim collection

### Target site

**`rust/src/state_ops_sba.rs:136-186`** — `collect_sba_victims`:

```rust
fn collect_sba_victims(&self) -> Vec<(u8, u32)> {
    let mut victims = Vec::new();
    for player in &self.players {
        for obj in player.battlefield.iter() {
            // ...704.5f / 704.5g checks...
            if effective_toughness <= 0 { victims.push((obj.controller, obj.id)); continue; }
            if obj.damage as i32 >= effective_toughness { victims.push((obj.controller, obj.id)); }
        }
    }
    victims
}
```

Outer `for player in &self.players` (p0-then-p1) is the divergence
surface — Python walks the centralized `state.battlefield` (ETB-sorted)
at `src/mtg_bot/turn.py:1242`.

### Diff sketch

```rust
// rust/src/state_ops_sba.rs:136
fn collect_sba_victims(&self) -> Vec<(u8, u32)> {
    let mut victims = Vec::new();
    for obj in crate::bf_iter::bf_iter_etb_sorted(self) {
        let Some(printing) = self.registry.lookup(obj.printing_id) else { continue; };
        let Some(toughness) = printing.toughness else { continue; };
        if printing.keywords.iter().any(|k| k == "indestructible")
            || obj.ueot_has_keyword("indestructible") { continue; }
        let base_toughness = obj.ueot_base_pt_override()
            .map(|(_, t)| t)
            .unwrap_or(toughness as i32);
        let effective_toughness = base_toughness + obj.counters + obj.ueot_toughness_bonus();
        if effective_toughness <= 0 {
            victims.push((obj.controller, obj.id));
            continue;
        }
        if obj.damage as i32 >= effective_toughness {
            victims.push((obj.controller, obj.id));
        }
    }
    victims
}
```

Everything else — predicate logic, indestructible filter, UEOT folds —
stays bit-equal. **The only change is the outer iteration shape.**

### Python counterpart

`src/mtg_bot/turn.py:1242` — `_state_based_actions_pass`:

```python
for obj in state.battlefield:
    if not is_creature_now(obj):
        continue
    tough = effective_toughness(state, obj)
    kws = effective_keywords(state, obj)
    if tough <= 0:
        destroyed.append(obj)
    elif "indestructible" in kws:
        continue
    elif obj.damage >= tough or obj.marked_lethal:
        destroyed.append(obj)
```

Centralized list, ETB-monotone. Confirmed by grep — no per-player
SBA loop on the Python side.

### Pinned tests likely affected

**Likely zero test rewrites needed** for the rust gate, because every
existing `tests_rust/test_sba.py` test runs against
`make_synthetic_state` (every bf object at `etb_timestamp=0`), and the
stable-sort tie-break preserves the pre-CE5 p0-then-p1 walk order.
Specifically `test_apply_sbas_handles_multiple_lethal_creatures`
(line 141) and `test_apply_sbas_lethal_creature_on_p1_goes_to_p1_graveyard`
(line 189) both check *what* moves, not relative-order across players.

The cross-engine smoke harness will gain a new clean-pass case once
the cast-creature probe sets up a state where p0 and p1 each have a
lethal-damaged creature with **non-trivial ETB interleaving** (i.e. p1's
creature ETB'd between two p0 ETB events). Pre-CE5 that surfaces as a
divergence; post-CE5 it walks clean.

**New regression tests to add** (mirror CE3/CE4 closure pattern):

- `tests_rust/test_sba.py::test_apply_sbas_victim_collection_etb_order`
  — build a state via `register_and_inject_object` with interleaved
  ETB timestamps (p0 ETB'd a creature, then p1 ETB'd, then p0 again);
  damage all three lethally; assert
  `collect_sba_victims` returns them in ETB order (not p0-then-p1).
- `tests_rust/test_sba.py::test_apply_sbas_graveyard_order_under_etb_interleave`
  — same setup; assert each player's graveyard receives its dead
  creatures in the relative ETB order they died (not p0-batch then
  p1-batch).

### Fingerprint baselines

**Should NOT shift** for any pinned synthetic-state digest (every
synthetic-state bf object has `etb_timestamp=0`, the stable-sort
tie-break preserves the pre-CE5 walk, and the per-player graveyards
are independent — order WITHIN one player's graveyard stays the same
as pre-CE5 because the relative order of that player's deaths is
preserved).

**May shift** for ETB-driven flows in the cross-engine smoke harness
(but those aren't pinned by hash; they're checked field-by-field via
`parity/cross_engine.py`'s field view normalizer). The smoke's
expected-clean behavior is a downstream PASS, not a hash match.

### Expected outcome

Cross-engine smoke scenarios where both players have lethal creatures
in the same SBA pass — and ETB timestamps interleave across players —
should now agree on:

1. The relative order of the destruction log entries.
2. The relative order of any death-trigger pushes onto the stack
   (gated on CE8 landing).
3. Per-graveyard contents (already matched pre-CE5; this is
   restated for clarity).

### Estimated slice scope

**Small.** One function rewrite + new `bf_iter.rs` module + two new
regression tests. The CE5 slice's bulk is the shared helper; the
SBA-side change is ~10 lines.

---

## Section 3: CE6 closure plan — damage assignment

### Target sites

Three iteration sites in `rust/src/state_ops_combat.rs`:

- **`state_ops_combat.rs:849`** — attackers walk:
  ```rust
  for &attacker_id in &self.attackers { ... }
  ```
  Iterates `self.attackers` Vec in declare-attackers push order.
- **`state_ops_combat.rs:962`** — back-damage blockers walk:
  ```rust
  for &(attacker_id, blocker_id) in &self.blockers { ... }
  ```
  Iterates `self.blockers` Vec in declare-blockers push order.
- **`state_ops_combat.rs:1025-1028`** — alive-check filter between
  first-strike and regular passes. Inherits iteration order from the
  pass-1 plan, which itself derives from 849 + 962.

### IMPORTANT REVISION TO THE AUDITS' PREDICTIONS

`RUST_BF_ITERATION_AUDIT.md` and `ORDER_SENSITIVE_SURFACES.md` both
flag that **Python's damage walk is likely a Python BUG**: per CR
510.1d, "the active player chooses the damage assignment order", which
is declare-order. Python's
`combat.py:389, 405` uses
`[o for o in state.battlefield if o.id in attacker.blocked_by]` —
filter-by-membership in battlefield-order, NOT `blocked_by` push order.
Rust's `self.blockers` walk is the CR-correct shape.

**This is real and load-bearing for the CE6 closure plan.** A closure
slice author has TWO viable options:

#### Option A (audit recommendation, short-term smoke parity)

Sort the per-attacker damage-plan entries by their source's
`etb_timestamp` before applying. Concretely:

1. In `deal_combat_damage`, **after** the plan is built (line 944-ish),
   stable-sort `plan` by the plan-entry's source's `etb_timestamp`
   (which requires reading it back via the bf — the helper would be
   something like `etb_ts_of(state, source_id) -> u32`).
2. For the per-attacker blocker walk (line 865-868), replace the
   `self.blockers.iter().find_map(...)` with a walk that iterates
   `bf_iter_etb_sorted(state)`, filters to objects whose id is in the
   `blocked_by` set for this attacker, and takes the first match.
3. For the back-damage blockers walk (line 962), iterate
   `bf_iter_etb_sorted(state)` filtered to ids appearing in
   `self.blockers`.

This MATCHES Python's bug for short-term smoke parity.

#### Option B (long-term correctness)

Keep Rust's `self.blockers`-push-order walk. Document the divergence
in `SEARCH_LIMITATIONS.md` (likely §1, which already covers
"combat damage assignment is ordered") and add an I-entry in
`RUST_PARITY_GAPS.md` declaring Rust right, Python wrong. Also fix
Python's `combat.py:389,405` to walk `attacker.blocked_by` in push
order. This is the engineering-correct choice but requires a parallel
Python-side fix, which is bigger than a single CE-closure slice.

**Slice author recommendation: Option A** for the CE6 slice itself,
to keep the probe-close-probe cadence tight. File a separate todo for
fixing Python's combat walk and flipping to Option B in a later
session.

### Python counterpart

`src/mtg_bot/combat.py:379-405`:

```python
for attacker in state.battlefield:
    if not attacker.attacking:
        continue
    # ...
    blockers = [o for o in state.battlefield if o.id in attacker.blocked_by]
    # ...
```

Outer attacker walk: `state.battlefield` (ETB-ordered, filtered to
`obj.attacking`). Inner blocker walk: `state.battlefield` filtered by
membership in `attacker.blocked_by`. Both walks are battlefield-order,
not declare-order.

### Pinned tests likely affected

**Likely affected:** `tests_rust/test_combat.py` damage assignment
tests that exercise multi-blocker scenarios. The exact list depends
on the slice author's audit; the search is for any test that:

1. Declares 2+ blockers against a single attacker in a non-ETB order, AND
2. Asserts a specific blocker takes damage first (e.g. via post-combat
   `obj.damage` field on a specific blocker id).

Most existing combat tests set up via `make_synthetic_state` where all
bf objects have `etb_timestamp=0` — the stable-sort tie-break is
p0-then-p1 + insertion-order, so any test that doesn't `register_and_inject_object`
or otherwise drive ETB stamping will be unaffected. The slice author
should run the rust gate after their plan-sort change and assess
fallout file-by-file.

**New regression tests to add:**

- `tests_rust/test_combat.py::test_multi_block_damage_assignment_walks_etb_order_when_blockers_declared_out_of_order`
  — declare 3 blockers in REVERSE bf order, assert per-blocker
  `obj.damage` post-combat-damage matches the ETB-order walk
  (lowest-timestamp blocker takes damage first).
- `tests_rust/test_combat.py::test_first_strike_alive_check_uses_etb_order`
  — verify the alive-check at 1025-1028 inherits the new ordering
  correctly (a first-strike attacker should kill blockers in ETB-order,
  and the alive-check for pass 2 should agree).

### Fingerprint baselines

**Likely DO shift** — but only in cross-engine smoke flows where
combat damage actually fires under non-trivial ETB interleaves. Pinned
synthetic-state fingerprint baselines (where every bf object has
`etb_timestamp=0`) preserve the pre-CE6 order via stable-sort tie-break,
so those stay bit-equal.

The slice author should:

1. After landing the plan-sort change, run the full rust gate (`pytest
   -n 8 --no-cov`) and confirm no pinned digests shift.
2. For any digest that DOES shift, audit whether the shift is the
   expected one (ETB-order vs declare-order) by hand-tracing the
   smoke's setup. Update the pin only if hand-trace confirms the new
   digest is the CR-correct shape.
3. Per `RUST_PARITY_GAPS.md` §I26's lessons-learned: keep the `etb_timestamp`
   OUT of the per-object 8-tuple. The damage-mark field IS in the
   8-tuple (it's `damage`), so a divergence in per-blocker damage WILL
   surface in the digest — that's expected and load-bearing.

### Expected outcome

Multi-block scenarios where blockers were declared in non-ETB order
should now assign damage in the same per-blocker amounts as Python.

### Estimated slice scope

**Medium.** Three iteration sites, each with non-trivial control flow
(the trample / deathtouch / first-strike paths all flow through these
sites). The plan-build code at lines 849-957 is large; the slice author
should sort the plan AFTER it's built rather than reshaping the
plan-build itself, to minimize blast radius.

Roughly: 50-100 lines changed across `state_ops_combat.rs` + 2-4 new
tests + careful review of existing `tests_rust/test_combat.py` for
order-sensitive assertions.

---

## Section 4: CE7 closure plan — cross-player find-first arms

### Target sites

Two arms in `rust/src/state_ops_resolve.rs`:

- **`state_ops_resolve.rs:4553-4582`** — `Effect::TapAnotherTargetCreature`:
  ```rust
  'outer_tatc: for (pidx, player) in state.players.iter().enumerate() {
      for obj in player.battlefield.iter() {
          if obj.id == source_obj_id { continue; }
          // ...Creature filter
          found = Some((pidx, obj.id));
          break 'outer_tatc;
      }
  }
  ```
- **`state_ops_resolve.rs:4583-4607`** — `Effect::UntapTargetOtherPermanent`:
  ```rust
  'outer: for (pidx, player) in state.players.iter().enumerate() {
      for obj in player.battlefield.iter() {
          if obj.id != source_obj_id && obj.tapped {
              found = Some((pidx, obj.id));
              break 'outer;
          }
      }
  }
  ```

Both walk p0's bf first then p1's, picking the first eligible. p0
permanents always win ties when both players have an eligible target.

### IMPORTANT FINDING ON PYTHON'S BEHAVIOR

`UntapTargetOtherPermanent` is defined at
`src/mtg_bot/effects/generic/tap.py:346-386`. Its `legal_targets`
returns:

```python
return [
    ("permanent", o.id)
    for o in state.battlefield
    if o.id != source_id and o.tapped
]
```

This is a centralized `state.battlefield` walk (ETB-ordered post-CE4)
filtered by `(o.id != source_id) and o.tapped`. The list is then
handed to the controller's agent via `p.agent.choose_target(...)` (see
`actions.py:1178`-ish dispatch path), which by default for the
random-agent / NN-eval / smoke harness will pick the **first**
candidate in the list.

So Python's behavior **IS** "first match in ETB order across both
battlefields". The audit's CE7 prediction is correct: Rust's p0-first
walk picks a different target whenever a p1 permanent has a lower ETB
timestamp than the first p0 candidate.

`TapAnotherTargetCreature` is implemented as `Tap` with a target spec
of `(IsCreature() & ~IsSource(),)` (`tap.py:277-295`); the underlying
`Tap` class's `legal_targets` walks `state.battlefield` filtered by the
predicate, same shape as `UntapTargetOtherPermanent`. Confirmed.

**No need for a different tie-break than CE5.** Both engines pick by
"first in ETB order" — exactly what `bf_iter_etb_sorted` produces.

### Diff sketch

For `Effect::TapAnotherTargetCreature`:

```rust
Effect::TapAnotherTargetCreature => {
    let mut found: Option<(usize, u32)> = None;
    for obj in crate::bf_iter::bf_iter_etb_sorted(state) {
        if obj.id == source_obj_id { continue; }
        let Some(printing) = state.registry.printings.get(obj.printing_id as usize) else { continue; };
        if !printing.card_types.iter().any(|t| t == "Creature") { continue; }
        found = Some((obj.controller as usize, obj.id));
        break;
    }
    if let Some((pidx, target_id)) = found {
        let zone: &mut Vec<GameObject> =
            Arc::make_mut(&mut state.players[pidx].battlefield);
        for obj in zone.iter_mut() {
            if obj.id == target_id {
                obj.tapped = true;
                break;
            }
        }
    }
}
```

Symmetric change for `Effect::UntapTargetOtherPermanent` (lines
4583-4607).

Net: the `'outer_tatc` / `'outer` labeled loop + nested per-player
walk collapses to a single `for obj in bf_iter_etb_sorted(state)` walk.
`pidx` is read off `obj.controller` rather than from the outer loop's
`enumerate` index.

### Python counterpart

- `src/mtg_bot/effects/generic/tap.py:346-364` (`UntapTargetOtherPermanent.legal_targets`).
- `src/mtg_bot/effects/generic/tap.py:277-295` (`TapAnotherTargetCreature` via base `Tap` class's targeting pipeline).

Both walk `state.battlefield` (centralized, ETB-ordered) filtered by
their respective predicates.

### Pinned tests likely affected

**Likely zero existing test breakage** for the rust gate, because:

1. The audit's hit-list of Effect arms (R3 single-player walks — 17
   sites) is unchanged by CE7. Those are single-controller filters that
   stay correct under per-player iteration.
2. Existing `tests_rust/test_resolve.py` tests for `TapAnotherTargetCreature`
   / `UntapTargetOtherPermanent` are likely constructed against
   single-player synthetic states (the target is found on the
   source-controller's bf), where the per-player walk and the
   `bf_iter_etb_sorted` walk return the same first match.

**New regression tests to add:**

- `tests_rust/test_resolve.py::test_tap_another_target_creature_picks_etb_first_across_players`
  — build a state where p1's creature has lower `etb_timestamp` than
  p0's, then resolve `TapAnotherTargetCreature` (source on either
  player). Assert p1's creature is tapped (not p0's).
- `tests_rust/test_resolve.py::test_untap_target_other_permanent_picks_etb_first_across_players`
  — symmetric scenario for the untap arm.

### Fingerprint baselines

**Should NOT shift** for any pinned synthetic-state digest (`etb_timestamp=0`
ties → p0-then-p1 walk preserved). May shift for cross-engine smoke
fingerprints once a probe drives a `TapAnotherTargetCreature` /
`UntapTargetOtherPermanent` resolution with interleaved ETB timestamps
— that's the load-bearing shift and should match Python post-CE7.

### Estimated slice scope

**Small.** Two Effect-arm rewrites (~30 lines each) + two new tests.
Shares the `bf_iter_etb_sorted` helper introduced by CE5. If CE5
hasn't landed when CE7's slice runs, the slice can either land the
helper as part of CE7 (same shape; lower-risk single-file refactor) or
wait. The helper is at-most a 30-line file — landing it twice (once in
CE5, once in CE7) would be inefficient but not catastrophic.

---

## Section 5: Dependency graph

Reproduced from `RUST_BF_ITERATION_AUDIT.md`'s "Closure dependencies"
section, with annotations from this playbook's deeper read:

```
        CE4 (closed) — bf snapshot + fingerprint sort by etb_timestamp
          |
          v
  CE5 (state_ops_sba.rs::collect_sba_victims)
          |
          +--> [enables] CE8 (trigger emitter; death-trigger order)
          |
          +--> [introduces] bf_iter_etb_sorted shared helper
                  ^
                  |
                  +--- CE7 (cross-player find-first arms) consumes
                  |
                  +--- CE6 (combat damage assignment) ALSO consumes,
                       though via a different idiom (sort plan entries
                       by source's etb_timestamp rather than walking
                       bf_iter directly — see Section 3)
          v
  CE6 (state_ops_combat.rs damage assignment)
  CE7 (state_ops_resolve.rs cross-player find-first Effects)
  (CE6 and CE7 are mutually independent)
          |
          v (mostly cosmetic)
  CE9 (_play_land etb_timestamp asymmetry; not gameplay-load-bearing)
```

### CE5 → CE8 dependency

**Audit-confirmed and elaborated.** Death triggers from an SBA pass
go onto the stack in the order their sources died. If CE5's
victim-collection order is wrong (p0-first instead of ETB-sorted), then
when Rust grows a trigger emitter, every death-trigger push inherits
the wrong order from `collect_sba_victims`'s return Vec.

**Practical consequence for the slice ordering:** CE5 MUST close
before CE8 substrate work begins. The CE8 slice author needs CE5's
shared helper to walk the bf in ETB order at trigger-emission time
(same shape as Python's `actions.py:3346-3399` dispatcher's
`for source in list(state.battlefield)`).

### CE6 is independent of CE5/CE7/CE8

**Audit-confirmed.** Combat damage assignment walks `self.attackers`
/ `self.blockers` Vecs, NOT a battlefield Vec. The closure shape is
"sort plan entries by source's `etb_timestamp`" (or "rewrite to walk
`bf_iter_etb_sorted` filtered by membership"). Either way, the fix
touches `state_ops_combat.rs` only — no overlap with CE5 / CE7.

### CE7 is independent of CE5/CE6/CE8

**Audit-confirmed.** Each Effect arm that needs the fix is independent;
both share the helper but the helper itself can land standalone (CE5
introduces it; CE7 consumes it).

### Other inter-CE dependencies found during this audit

None new. The audits' two-doc treatment was thorough; this playbook
adds detail but no surprise dependencies.

### Suggested ordering

**CE5 → CE6 → CE7 → CE8** (then later: CE9 if observable).

Rationale:

1. **CE5 first** because it (a) introduces the shared helper, (b) is
   the smallest slice, and (c) is the highest-priority predicted
   divergence per `ORDER_SENSITIVE_SURFACES.md`'s ranked list.
2. **CE6 next** because combat divergences are the most common
   probe-class once `multi_turn_selector` starts driving creatures into
   combat. The next round of probes after CE5 closes is likely to
   surface CE6 immediately. Closing CE6 unblocks every multi-block
   combat scenario.
3. **CE7 next** because it's small, the predicate is correct (no
   "Python is wrong" wrinkle like CE6's), and it reduces the
   audit's MEDIUM-risk Effect-arm count to zero.
4. **CE8 last** of the predicted set, because the substrate (the
   trigger emitter itself) doesn't exist in Rust yet — that's a bigger
   slice than CE5/CE6/CE7 combined and benefits from having CE5's
   helper already in place.

---

## Section 6: Post-closure verification checklist

For each closure slice (CE5, then CE6, then CE7), the slice author
should:

### After CE5

- [ ] Run `pytest tests_rust/ -n 8 --no-cov` — confirm 1693+ tests
      pass.
- [ ] Run cross-engine smoke at N=200 on `slightly_bigger_deckspec`
      via the cast-creature probe selector (once that lands):
      `mtg_bot bench cross-engine --decisions 200 --seed 42` (or
      whatever the smoke harness invocation is post-cast-creature).
- [ ] Confirm the smoke test that was flagging CE5 as a strict-xfail
      flips to expected-pass.
- [ ] Remove the symptom-pin companion test per the closure-pair
      contract (mirror CE3/CE4 pattern).
- [ ] Update `docs/RUST_PARITY_GAPS.md`: replace the CE5 entry with a
      `~~CE5.~~ CLOSED: ...` notice mirroring CE2/CE3/CE4's format.
      Add a new I-section invariant if appropriate (e.g. I27 "SBA
      victim collection walks battlefield in ETB-timestamp order via
      shared `bf_iter_etb_sorted` helper").
- [ ] Re-run full Python gate: `pytest -n 8 --no-cov` — confirm no
      new reds.
- [ ] Spot-check pinned fingerprint baselines in
      `tests_rust/test_fingerprint.py` (~30+ pins) — none should
      shift. If one does, hand-trace to confirm the shift is the
      expected ETB-order one and update the pin.

### After CE6

- [ ] Run `pytest tests_rust/ -n 8 --no-cov`. Special attention to
      `tests_rust/test_combat.py` (~150 tests) — flag any test whose
      assertion order changed.
- [ ] Run cross-engine smoke at N=200 with the combat probe
      selector (once it lands).
- [ ] Confirm any strict-xfail flagging CE6 (e.g.
      `test_cross_engine_*_surfaces_ce6_*`) flips to expected-pass.
- [ ] Remove its symptom-pin companion.
- [ ] Update `docs/RUST_PARITY_GAPS.md`: CE6 entry replaced with
      CLOSED notice. Choose Option A (match Python's bug) or Option
      B (Rust right, Python wrong) per Section 3 — if Option B,
      document the Python-side fix as a separate todo and add an
      explicit I-section invariant pinning Rust's CR-correct behavior.
- [ ] Add `SEARCH_LIMITATIONS.md` entry if Option A is chosen,
      noting "Rust mirrors Python's combat.py battlefield-order
      damage walk rather than CR 510.1d's declare-order — pending
      Python-side fix".
- [ ] **Fingerprint baselines that pin combat-damage-resulting states
      MAY need to shift.** Audit: any `tests_rust/test_fingerprint.py`
      test that builds a multi-block scenario via
      `register_and_inject_object` interleaved across players. Hand-trace
      the expected new digest, update the pin.

### After CE7

- [ ] Run `pytest tests_rust/ -n 8 --no-cov`. Light touch — CE7's
      blast radius is two Effect arms.
- [ ] Run cross-engine smoke when a probe drives
      `TapAnotherTargetCreature` / `UntapTargetOtherPermanent`
      (likely requires Starport Security or Nanoform Sentinel in the
      deck pool).
- [ ] Confirm any strict-xfail flagging CE7 flips to expected-pass;
      remove symptom-pin.
- [ ] Update `docs/RUST_PARITY_GAPS.md`: CE7 entry replaced with
      CLOSED notice.

### Fingerprint baselines summary

Pinned fingerprint baselines to review across all three closures
(non-exhaustive — slice author should grep
`EXPECTED_*_FP` constants):

- `tests_rust/test_setup.py::EXPECTED_MAKE_STATE_CANONICAL_DEFAULT_FP`
  (currently `411d5b757c22` post-CE1; should stay).
- `tests_rust/test_fingerprint.py` synthetic-state digests (~30+
  pins; should all stay because `make_synthetic_state` keeps every
  bf object at `etb_timestamp=0` and the stable-sort tie-break
  preserves p0-then-p1 order).
- `tests_rust/test_snapshot.py` snapshot digests — same logic.
- Anything in `tests/test_parity_smoke.py` that's a digest pin
  (mostly NOT digest-pinned; the smoke checks field-by-field via the
  parity field view).

### Update `RUST_PARITY_GAPS.md` on each closure

Each closed CE moves from a CE-tagged "Confirmed gaps" entry to a
`~~CEn.~~ CLOSED: <one-line summary>` notice in the CE section, with
a 3-5 paragraph body mirroring the CE2/CE3/CE4 patterns. The body
should call out: closure slice's feature branch name, key
implementation file(s), any test rewrites, any fingerprint baseline
shifts (with the old + new digest), and the strict-xfail that flipped
to expected-pass.

---

## Section 7: Risk register

### Risk 1: Fingerprint baseline cascades

**Risk.** A change in CE6's per-blocker damage iteration shifts one
fingerprint baseline, but the shift cascades — a state's digest
depending on the per-blocker-damage state cascades into every test
that builds on that state.

**Likelihood:** medium for CE6, low for CE5/CE7 (synthetic-state
tie-break preserves pre-closure walks).

**Mitigation.** For each closure slice, run the full rust gate
*before* updating any pinned digest. Audit each failure to confirm
the shift is the expected ETB-order one. Update pins ONE AT A TIME,
running the gate between each, so a wrong update doesn't get masked
by subsequent updates.

### Risk 2: Undiscovered iteration site missed by the audits

**Risk.** `RUST_BF_ITERATION_AUDIT.md` enumerated 37 sites, but a new
Effect added between the audit's commit (`d1239fc3`) and the closure
slice could introduce a 38th. CE5's helper would not be consumed there
without an explicit refactor.

**Likelihood:** low — between the audit's commit and CE5's likely
landing, the only in-flight slice is the cast-creature probe, which
doesn't add Effect arms.

**Mitigation.** Before CE5 closure lands, grep
`for player in &.*players` and `for obj in player\.battlefield` across
`rust/src/`. If the count exceeds 37, audit the new sites against the
classification table in `RUST_BF_ITERATION_AUDIT.md`.

### Risk 3: Perf regression from the sort

**Risk.** Every consumer of `bf_iter_etb_sorted` allocates a Vec and
runs a sort. The audit's six predicted consumers (CE5, CE6, CE7, plus
snapshot + fingerprint, plus future CE8) could in principle hit a hot
path that becomes O(N log N) per call.

**Likelihood:** very low — battlefield sizes in realistic states are
small (typically <20 objects; pathological is <100). N log N at N=20
is ~50 comparisons, negligible vs the per-call work each consumer
already does.

**Mitigation.** Run `scripts/bench_clone.py` and the
`scripts/bench_per_game_wall.py` benchmarks before + after CE5. If
either shows >2% regression vs the pre-CE5 baseline, the slice author
should investigate (likely culprit: a hot consumer that should cache
the sorted Vec — `state_ops_snapshot.rs::battlefield_snapshot` is
called once per smoke step, so caching is feasible if needed).
Realistically expect zero measurable change.

### Risk 4: Python's combat bug forces hard choice in CE6

**Risk.** Section 3's Option A (match Python's bug) vs Option B (Rust
right, fix Python) is a real engineering decision. Option A keeps the
cross-engine smoke happy but bakes in a CR-incorrect behavior. Option
B is the right long-term choice but doubles the CE6 slice scope.

**Likelihood:** unavoidable — the audits flagged it explicitly.

**Mitigation.** Recommendation: Option A for the CE6 slice itself,
plus a follow-up `RUST_PARITY_GAPS.md` todo to fix Python's combat
walk in a separate slice. Document the decision in CE6's closure
notice and `SEARCH_LIMITATIONS.md`. Re-evaluate at Phase 6 / 7 when
the combat layer gets a full audit.

### Risk 5: Test rewrites cascade in CE6

**Risk.** Existing `tests_rust/test_combat.py` tests may pin
per-blocker damage outcomes that assumed declare-order iteration.
Rewriting those tests to assume ETB-order could break Python-side
parity tests if the harness expects the OLD Rust behavior.

**Likelihood:** low (the cross-engine parity tests are the most
recent and use the field view normalizer, not digest pins), but
non-zero.

**Mitigation.** Before rewriting any combat test, grep the parity
field view normalizer in `src/mtg_bot/parity/cross_engine.py` for any
combat-specific normalization. If it normalizes blocker order, the
test rewrite is safe. If it doesn't, audit the test's assertion to
confirm whether it's pinning a Rust-only invariant or a
cross-engine-parity invariant.

### Risk 6: CE9 (`_play_land` etb_timestamp asymmetry) surfaces unexpectedly

**Risk.** `ORDER_SENSITIVE_SURFACES.md` §1's "Hidden land trap" notes
that Rust's CE4 implementation bumps `etb_timestamp` on every bf-entry
including `play_land`, but Python's `_play_land` (actions.py:1084-1124)
never bumps the timestamp — Python lands all stay at timestamp 0. The
relative *order* of lands in `state.battlefield` is preserved by the
list's insertion order on the Python side; on the Rust side, the
strictly-monotonic timestamps preserve it via sort.

**Likelihood:** none until the snapshot dict surfaces `etb_timestamp`
as a field — which it currently does NOT (`etb_timestamp` is sort-key-only,
per I26).

**Mitigation.** Keep `etb_timestamp` out of `object_to_pydict` in
`state_ops_snapshot.rs`. If a future probe needs to surface the field,
EITHER fix Python's `_play_land` to bump `state.next_timestamp` (small
slice) OR add a CE9 entry to `RUST_PARITY_GAPS.md` for the asymmetry.

---

## Appendix: file:line cheat sheet

Quick reference for the slice author. Every path is relative to the
repo root.

| Action | File:line |
|---|---|
| CE5 site | `rust/src/state_ops_sba.rs:136-186` |
| CE5 Python ref | `src/mtg_bot/turn.py:1242` |
| CE6 site (attacker walk) | `rust/src/state_ops_combat.rs:849` |
| CE6 site (back-damage walk) | `rust/src/state_ops_combat.rs:962` |
| CE6 site (alive filter) | `rust/src/state_ops_combat.rs:1025-1028` |
| CE6 Python ref | `src/mtg_bot/combat.py:379, 389, 405` |
| CE7 site (TapAnother) | `rust/src/state_ops_resolve.rs:4553-4582` |
| CE7 site (UntapOther) | `rust/src/state_ops_resolve.rs:4583-4607` |
| CE7 Python ref (Untap) | `src/mtg_bot/effects/generic/tap.py:346-386` |
| CE7 Python ref (TapAnother) | `src/mtg_bot/effects/generic/tap.py:277-295` |
| CE4 closure (reference pattern) | merge `276d806a`, feature `d04cb3de` |
| CE4 helper precedent | `rust/src/state.rs::reserve_etb_timestamp` (lines 186-202 post-CE4) |
| Existing stable-sort sites | `state_ops_snapshot.rs:189`, `state_ops_fingerprint.rs:316-327` |
| Proposed helper location | new file `rust/src/bf_iter.rs` |
| I26 (post-CE4 invariant) | `docs/RUST_PARITY_GAPS.md` |
| Closure-pair contract | mirrors CE3/CE4: flip strict-xfail to expected-pass + remove companion symptom-pin |
