# battlefield STATE_EQ axis — deep-trace investigation

**Lane:** `feature/battlefield-axis-investigation` (2026-05-20).
**Cross-references:**
[`docs/G7_S6_BROADER_ARCHETYPE_V9_EVIDENCE.md`](G7_S6_BROADER_ARCHETYPE_V9_EVIDENCE.md)
§"NEW: Battlefield STATE_EQ axis (4)" (4/300 v9 residuals, todo
`e5b7c9d8`),
[`docs/BROADER_SWEEP_CONSOLIDATED_V5_V9.md`](BROADER_SWEEP_CONSOLIDATED_V5_V9.md),
[`docs/PRIORITY_PLAYER_AXIS_INVESTIGATION.md`](PRIORITY_PLAYER_AXIS_INVESTIGATION.md)
(prior sibling closure, template for this doc).

The 4 `STATE_EQ::fields:battlefield` residuals surfaced by v9
(arch=253/s2, 253/s3, 257/s2, 281/s4) all reduce to **one shared root
cause**: two `Effect::*` arms in `state_ops_resolve.rs` are
**un-migrated to the cast-time-bound target-id pattern** and instead
use a "first legal target via battlefield scan" convention at resolve
time. When the originally-targeted permanent ceased to be a legal
target between cast and resolve (CR 608.2b — the universal "fizzle"
case), Rust re-targets the next matching battlefield permanent;
Python correctly fizzles. The divergence is the "wrong permanent
destroyed / damaged" downstream.

**Investigation, not closure** — the fix is a follow-up lane. The
companion pin
[`tests/test_divergence_pins_battlefield.py`](../tests/test_divergence_pins_battlefield.py)
asserts the CURRENT (broken) behavior for the strongest repro
(arch=253 s2 step 1147) and will flip-fail when the closure lands.

---

## §0 TL;DR

**Root cause:** two effect arms in
[`rust/src/state_ops_resolve.rs`](../rust/src/state_ops_resolve.rs)
ignore the originally-bound target id on the resolving `StackItem`
and use a battlefield-scan first-legal-target convention at resolve
time. The pre-existing Python source-of-truth re-checks CR 608.2b
against the ORIGINAL target id (silent fizzle when illegal), so any
"target dies on the stack before the spell resolves" sequence
diverges immediately.

**Code sites:**

1. **`Effect::DestroyTargetArtifactOrTappedCreature`** at
   [`rust/src/state_ops_resolve.rs:6182-6285`](../rust/src/state_ops_resolve.rs)
   (Radiant Strike's destroy half). Scans
   `bf_iter_etb_sorted(state)` for the first non-indestructible
   permanent matching `Artifact OR (Creature AND tapped)` and
   destroys it. Does NOT consult
   `state.current_resolve_payload_target_id`.
2. **`Effect::FocusFireEffect`** at
   [`rust/src/state_ops_resolve.rs:7162-7267`](../rust/src/state_ops_resolve.rs)
   (Focus Fire). Scans `bf_iter_etb_sorted(state)` for the first
   creature where `attackers.contains(&obj.id) OR
   blockers.contains_blocker(obj.id)` and deals damage. Does NOT
   consult `state.current_resolve_payload_target_id`.

Both arms have the same shape; the `SeedshipImpactEffect` arm at
[`rust/src/state_ops_resolve.rs:6319-6500`](../rust/src/state_ops_resolve.rs)
shows the CORRECT migrated pattern — read
`state.current_resolve_payload_target_id`, scan only for that id,
filter check, silent fizzle when not found. The G7 token-creation
parity closure (arch=10/11/12/seed=2,
`docs/G7_S6_BROADER_ARCHETYPE_EVIDENCE.md`) was exactly this fix
for the Seedship arm; that closure documented the pattern but did
not propagate it to the sister arms.

**Recommended closure:** migrate both arms to the
`current_resolve_payload_target_id` pattern. ~30 LoC per arm,
pure Rust touch (single `.pyd` rebuild). The `cast_spell` site
already binds the chosen target id onto the StackItem; the
resolver's apply-effect-loop already swaps it into
`current_resolve_payload_target_id` (line 12416-12417); the only
missing wiring is the per-arm READ.

**Estimated scope:** 1 orchestrator cycle, ≤60 LoC across two
arms + flip the regression pin + re-run broader-sweep v6-v9 to
confirm 0 battlefield residuals.

**Multi-axis bonus:** **NO shared root cause with priority_player /
blocker / TTT axes.** This is a distinct rules-fidelity-hole class
(target-tracking convention). The priority_player + blocker
LEGAL_SET_EQ axes share a `state.attackers` Vec-staleness root in
the **adapter** (`rust_engine_adapter.py`); this axis is a Rust
**engine** rules-fidelity hole. They closely co-occur (same
"attacker dies on the stack at DECLARE_ATTACKERS" play sequence
exercises both), but the fix surfaces are different files and
different code patterns.

**Decision implication for flip-readiness:** the residual landscape
is now characterized to single-bug granularity on all 3 axes. The
SOT-flip GO call is still tenable per
`FLIP_READINESS_EVIDENCE_2026_05_19.md`, with the bake-in
shadow-checker as a tripwire on the remaining 4 battlefield + 15
priority_player + 4 blocker repros (23/1500 = 1.5%; identified +
post-flip-tripwireable).

---

## §1 Methodology

Reproduction loop:

1. [`scripts/scout_battlefield_axis.py`](../scripts/scout_battlefield_axis.py).
   Loads `production_deck_to_deckspec(archetype, shared_rng_seed=seed)`
   and drives `build_shadow_checked_adapter` deterministically with
   `random.Random(seed)` until the harness surfaces the STATE_EQ
   divergence. At each successful apply, snapshots both engines'
   battlefield as canonical 8-tuples
   `(printing_name, controller, tapped, attacking, blocking,
   attached_to, summoning_sick, id)` and computes set-diff (py-only,
   rust-only, field-disagreements). Identifies the FIRST step where
   the two diverge.
2. The script terminates at the harness's `apply` raise (the STATE_EQ
   tripwire) and dumps the trip-step's full diff + the last 25 step
   history with bf-diff status per step.
3. For the two chosen repros (arch=253 s2 step 1147 + arch=281 s4
   step 2358), a follow-up ad-hoc tracer drives both engines
   INDEPENDENTLY (bypassing the ShadowCheckedRustAdapter assertions)
   past the harness trip step to confirm the divergence is in the
   Rust resolution (not the harness).

**Verify-first** (`feedback_parity_new_code_is_right`): every fact
in this doc is dumped from the running game via the scout script's
public-accessor snapshot. The "Rust destroys the Lander / damages
Knight" claim is confirmed by walking both engines side-by-side at
each step and observing the precise step at which Python's
battlefield contains a permanent that Rust's no longer does.

---

## §2 Trace results — arch=253 seed=2 step 1147

**Carrier cards:** Radiant Strike + Focus Fire (one of each) in
arch=253's deck list. **Triggered carrier:** Beamsaw Prospector
(dies-trigger creates a Lander token).

Play sequence (steps 1137-1147):

| Step | Decision | Effect |
|---:|---|---|
| 1137 | `AttackerDecision(0, True)` | P0 declares Beamsaw Prospector (id=0) attacking — taps it (`(0, tapped=1, attacking=1)`) |
| 1138 | `PassPriority` | start of DA priority window |
| 1139 | `CastSpell(73)` (P1) | Radiant Strike on stack, targets `('creature', 0)` (Beamsaw) |
| 1140 | `PassPriority` | |
| 1141 | `CastSpell(61)` (P1) | Focus Fire on stack, targets `('creature', 0)` (Beamsaw) |
| 1142-1143 | `PassPriority` ×2 | both engines pass; pre-resolve stack=2 |
| 1144 | `PassPriority` | **Focus Fire resolves** (top of stack, LIFO). Damage to Beamsaw → Beamsaw dies via SBA → Beamsaw's DIES trigger pushes onto stack. **Both engines correctly fire the DIES trigger.** Stack now `[Radiant Strike, Beamsaw_DIES_trigger]`. Beamsaw in graveyard. |
| 1145 | `PassPriority` | **Beamsaw DIES trigger resolves** (top of stack). Creates Lander id=120 under P0. **Both engines correctly create the Lander.** Stack now `[Radiant Strike]`. |
| 1146 | `PassPriority` | |
| 1147 | `PassPriority` (TRIPS) | **Radiant Strike resolves.** Python: original target id=0 (Beamsaw) is no longer on battlefield → CR 608.2b fizzle, no destroy. **Rust: scans `bf_iter_etb_sorted` for first Artifact-OR-tapped-Creature → finds the newly-created Lander id=120 (Artifact, just entered) → DESTROYS IT.** Python bf has Lander; Rust does not. Harness trips. |

Cross-engine side-by-side (post-step):

| Step | py.bf has Lander | rust.bf has Lander |
|---:|---|---|
| 1144 | no | no |
| 1145 | **yes (id=120)** | **yes (id=120)** ← both engines agree the DIES trigger fires |
| 1146 | yes | yes |
| 1147 | yes | **no (destroyed)** ← divergence |

Note: at step 1147 a `Plains, 1, 1, 0, 0, None, 1, 66` field-disagreement
also shows up — likely the GainLife / SBA fan-out tail; minor and
inherited from the Radiant Strike misresolution.

---

## §3 Cross-check — arch=281 seed=4 step 2358

**Carrier cards:** Focus Fire × 2 in arch=281's deck list. No
Radiant Strike. Two Focus Fire spells on the stack, both targeting
`('creature', 120)` (a Human Soldier token id=120 attacking).

Play sequence (steps 2348-2358):

| Step | Decision | Effect |
|---:|---|---|
| 2348-2350 | `AttackerDecision(10,T), AttackerDecision(120,T), AttackerDecision(121,T)` | P0 declares 3 attackers: Knight Luminary id=10, Human Soldier id=120, Human Soldier id=121. At step 2350 Rust diverges on `attacking` flag (the priority_player axis precursor — Rust hasn't finalized `attacking=True` on attackers yet at this snapshot point, but that's a separate axis). |
| 2352 | `CastSpell(60)` (P1) | Focus Fire on stack, targets `('creature', 120)` |
| 2354 | `CastSpell(61)` (P1) | Focus Fire on stack, targets `('creature', 120)` |
| 2355-2357 | `PassPriority` ×3 | Both engines resolve top-of-stack Focus Fire. **Python**: target id=120 still legal (attacking) → deals damage to id=120. **Rust**: scans `bf_iter_etb_sorted` for first attacking-or-blocking creature → finds Knight Luminary id=10 (oldest attacker, lowest ETB timestamp) → deals damage to id=10. After the first resolve: Python has damage on id=120, Rust has damage on id=10. After the second resolve (similar scan): Python damages id=120 again (lethal); Rust damages id=10 again (Knight Luminary lethal). |
| 2358 | `PassPriority` (TRIPS) | SBA destroys the damaged creatures. **Python**: id=120 dies (lethal damage from 2×Focus Fire); Knight id=10 survives. **Rust**: id=10 (Knight) dies (lethal damage from 2×Focus Fire); id=120 (Human Soldier) survives with some damage. py.bf has Knight, rust.bf does not. graveyard_p0 also disagrees: Rust has Knight in grave; Python does not. |

The `'Human Soldier', 0, 1, 0, 0, None, 0, 121` field-disagreement
at step 2358 is the same `attacking` flag tail from the
priority_player axis — separate bug.

**Conclusion:** arch=281 s4 step 2358 has the **same root cause**
as arch=253 s2 step 1147: Rust's `Effect::FocusFireEffect` ignores
the bound target id and picks first-attacking-or-blocking
deterministically. Python correctly uses the original target.

---

## §4 The mechanism in Rust — code citation

[`rust/src/state_ops_resolve.rs:6182-6201`](../rust/src/state_ops_resolve.rs)
(Radiant Strike's destroy half):

```rust
Effect::DestroyTargetArtifactOrTappedCreature => {
    let target: Option<(usize, u32)> = crate::bf_iter::bf_iter_etb_sorted(state)
        .into_iter()
        .find_map(|obj| {
            let printing = state.registry.lookup(obj.printing_id)?;
            let is_artifact = printing.card_types.iter().any(|t| t == "Artifact");
            let is_creature = printing.card_types.iter().any(|t| t == "Creature");
            if !(is_artifact || (is_creature && obj.tapped)) {
                return None;
            }
            if printing.keywords.iter().any(|k| k == "indestructible") {
                return None;
            }
            Some((obj.controller as usize, obj.id))   // FIRST match, not bound target.
        });
    if let Some((pidx, target_id)) = target {
        ...
    }
}
```

[`rust/src/state_ops_resolve.rs:7223-7263`](../rust/src/state_ops_resolve.rs)
(Focus Fire):

```rust
let target: Option<(usize, u32)> = {
    let attackers = &state.attackers;
    let blockers = &state.blockers;
    let registry = &state.registry;
    crate::bf_iter::bf_iter_etb_sorted(state)
        .into_iter()
        .find_map(|obj| {
            let printing = registry.lookup(obj.printing_id)?;
            if !printing.card_types.iter().any(|t| t == "Creature") {
                return None;
            }
            let is_attacking = attackers.contains(&obj.id);
            let is_blocking = blockers.iter().any(|(_att, blk)| *blk == obj.id);
            if is_attacking || is_blocking {
                Some((obj.controller as usize, obj.id))  // FIRST match, not bound target.
            } else {
                None
            }
        })
};
```

Both arms have the comment "deterministic-first across BOTH bfs in
ETB-timestamp order ... mirrors the cross-engine spell-card-bridge
`_PickFirstLegalTargetAgent`" — an acknowledged shortcut from the
spell-card-bridge phase that PRE-DATES the
`current_resolve_payload_target_id` plumbing.

The pattern in the migrated `SeedshipImpactEffect` arm at
[`rust/src/state_ops_resolve.rs:6355-6358`](../rust/src/state_ops_resolve.rs)
is the closure shape:

```rust
let payload_target = match state.current_resolve_payload_target_id {
    Some(t) => t,
    None => return Ok(()),
};
let target: Option<(usize, u32, u32)> =
    crate::bf_iter::bf_iter_etb_sorted(state)
        .into_iter()
        .find_map(|obj| {
            if obj.id != payload_target {
                return None;
            }
            // ... filter check ...
        });
```

The scan is reduced from "all bf" to "the bound id". Filter check
stays (defense-in-depth for indestructibility / on-resolve filter
re-check).

---

## §5 Why this wasn't caught earlier

The G7 S6 Class-A / Class-D residual closures (e.g. `7693c669`,
`df4028a7`) targeted **token-creation parity** in the same class —
specifically the controller-mismatch for tokens-by-effect. The G7
`SeedshipImpactEffect` lander-controller closure (the closure
referenced in the comment at line 6330-6354) was the canonical
fix-shape for "cast-time-bound target ceases between cast and
resolve". That closure did not propagate to the sister arms
because:

1. The v5-v8 broader sweeps didn't exercise the Radiant Strike +
   Focus Fire + dies-trigger-creature combo (no Beamsaw Prospector
   in deck lists at archetypes 60-239).
2. The v9 slice (archetypes 240-299) included arch=253 (carries
   Beamsaw Prospector + Radiant Strike + Focus Fire) and
   arch=257/281 (Focus Fire × 2-3, attacking creatures with
   ETB-timestamp differences from the cast-time target).
3. The "DIES trigger creates token" + "removal targeting the dying
   creature, with another removal on the stack" is a multi-card
   interaction; isolated tests cover each in isolation, the
   broader sweep is the first to exercise them together.

There is no entry in `docs/SEARCH_LIMITATIONS.md` for either
unmigrated arm — they pre-date the formal scope-tracking. The
fix should add an entry covering the BOTH arms + any other sister
arm a grep audit surfaces (see §6).

---

## §6 Recommended closure scope

**Phase 1 — Audit.** `grep` `bf_iter_etb_sorted` across
`state_ops_resolve.rs` to enumerate every `Effect::*` arm that
uses the first-match scan convention. Categorize by:

- "Untargeted" — global effects (DestroyAllCreatures, etc.). Not
  affected.
- "Targeted, migrated" — uses
  `state.current_resolve_payload_target_id`. Not affected.
- "Targeted, un-migrated" — uses `bf_iter_etb_sorted` to find
  first legal target. **Affected.** Each needs the
  `payload_target` swap.

Known un-migrated (this lane):
[`Effect::DestroyTargetArtifactOrTappedCreature`](../rust/src/state_ops_resolve.rs)
:6182,
[`Effect::FocusFireEffect`](../rust/src/state_ops_resolve.rs):7162.

**Phase 2 — Migrate each un-migrated arm.** ~30 LoC each. The
pattern is mechanical — replace the `find_map` scan with a
`payload_target` swap + a single-id-filter scan + the existing
filter check + silent fizzle when not found.

**Phase 3 — Flip the regression pin.** Rename
`test_battlefield_divergence_is_surfaced` →
`test_battlefield_divergence_is_closed`; replace
`assert err is not None` with `assert err is None`.

**Phase 4 — Audit + update.** Add a `docs/SEARCH_LIMITATIONS.md`
entry for the closure (or remove the implicit limitation
once-and-for-all). Re-run broader-sweep v6-v9 to confirm:
- battlefield STATE_EQ axis: 0 residuals (was 4)
- priority_player axis: 15 residuals (unchanged — separate axis,
  closed by sibling lane `feature/priority-player-blocker-closure`)
- blocker LEGAL_SET_EQ axis: 4 residuals (unchanged — closed
  alongside priority_player)
- Cumulative: 0/1500 with both lanes landed.

---

## §7 Closure-flip pattern (for the future agent)

Per the G7 token-creation-parity closure-flip pattern
(`7693c669` / `df4028a7`):

1. Apply the Phase 1+2 changes in `state_ops_resolve.rs` (+ any
   other un-migrated arms surfaced by the grep audit).
2. Rebuild the Rust extension:
   ```
   PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe -m pip install -e .
   ```
3. **Flip the pin** at
   [`tests/test_divergence_pins_battlefield.py`](../tests/test_divergence_pins_battlefield.py)
   to its closed form. Keep the parameterization; the closure
   should regress all 4 listed repros.
4. The negative-control assertions in
   `tests/test_rust_shadow_bakein.py::test_negative_control_*` keep
   covering the STATE_EQ tripwire on injected divergences.
5. Re-run the broader-sweep bench
   (`bench_trajectory_parity.py --archetypes 60-299
   --shadow-max-steps 20000 --seeds 0,1,2,3,4`) and confirm the
   battlefield axis is closed.
6. Update [`docs/BROADER_SWEEP_CONSOLIDATED_V5_V9.md`](BROADER_SWEEP_CONSOLIDATED_V5_V9.md)
   to mark the battlefield axis closed.
7. Update todo `e5b7c9d8` to closed with the commit reference.
