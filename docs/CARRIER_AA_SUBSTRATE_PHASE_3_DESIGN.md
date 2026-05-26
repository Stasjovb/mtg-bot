# Carrier-AA substrate — Phase 3 design

**Status:** DESIGN — docs-only scoping for the Phase 3 trio of
orthogonal Effect-family widens. No code change lands with this doc.
The baseline parity gate (`tests/test_measure_pool_parity.py`) was
confirmed green (32/32) at HEAD `03fdc3e6` (Phase 2b closure) prior
to writing this scope; no `.pyd` or test mutation accompanies the
design slice.

**Author:** Carrier-AA Phase 3 design lane, Worker B
(`feature/carrier-aa-substrate-phase-3-design-p1`), 2026-05-25.

**Predecessors:**
* Phase 1 (Swarmyard) C1-C4 — `4eed9554` + `226c9738` + `0cc08732` +
  `da761ad1`. Rust substrate (`CardDef.activated_abilities` +
  `Effect::RegenerateTargetCreature` + `Effect::UntapTargetLand` +
  bridge codec) + Python admit gate at bare `{T}` cost shape.
* Phase 1.5a (Deserted Temple) — `aabda1ee` + `e0707d88`. Python-only
  cost-gate widen from STRICT bare `{T}` to bare `{T}` OR `{N}, {T}`
  (generic-only mana).
* Phase 2a (Petrified Field) — `9fc70637` + `aca39437` + `8a31b12b`.
  `{T}, Sac:` cost-shape widen + `Effect::ReturnTargetLandFromGraveyardToHand`
  port + graveyard-target fan-out arm.
* Phase 2b (Terrain Generator) — `03fdc3e6`.
  `Effect::PutBasicLandFromHandOntoBattlefieldTapped` port under the
  existing Phase-1.5/2a cost gate (no cost-gate change).

**Carrier-AA admit set at Phase 2b close (HEAD `03fdc3e6`):**
4 cards — **Swarmyard** + **Deserted Temple** + **Petrified Field** +
**Terrain Generator**. BLOCKED-SG Carrier-AA row: 26 cards remaining.

**Companion docs:** `docs/CARRIER_AA_SUBSTRATE_PHASE_1_DESIGN.md`
(parent campaign-shape doc — §2.1 30-card walk, §3 out-of-scope
matrix, §10.3 sibling-swap clause);
`docs/CARRIER_AA_SUBSTRATE_PHASE_1_5_DESIGN.md` (Phase 1.5a cost-gate
widen + §9.5 copy-effect deferral); `docs/CARRIER_AA_SUBSTRATE_PHASE_2_DESIGN.md`
(Phase 2a/2b cost+Effect landing + §3 out-of-scope matrix recap).
This Phase 3 doc inherits their definitions; cross-references cite by
section.

---

## 0. Executive summary

Phase 3 is a **three-sub-phase landing** covering the three remaining
single-AA Land carriers in the Phase 2 §2.1 §"Phase 3+ deferral" row,
each of which is its OWN Effect family with NON-overlapping substrate
machinery:

* **Phase 3A — Mystifying Maze** (`{4}, {T}: ExileTargetAttackingCreatureUntilEndStep`).
  Delayed-trigger substrate: exile-until-end-of-step + delayed_triggers
  queue producer + return-from-exile-to-battlefield-tapped primitive.
  **Smallest of the three** — the `delayed_triggers` queue + end-of-
  step dispatch arm already exist in Rust (`state.rs:2335`,
  `state_ops_steps.rs:434`); the WarpExileSelf delayed-trigger
  precedent is fully wired. Phase 3A ports ONE new exile-effect arm,
  ONE new delayed-trigger producer arm, ONE new return-from-exile
  effect arm, and the existing `attackers: Vec<u32>` target enumeration.
* **Phase 3B — Scavenger Grounds** (`{2}, {T}, Sac-a-Desert:
  ExileAllGraveyards`). Three small orthogonal substrates: the
  `sacrifice_a_desert` cost-bool gate widen (Python admit only — the
  Rust cost-pay + target fan-out are already wired per Phase 2 §4.4),
  the `Land — Desert` subtype admission (Python predicate — Rust
  doesn't check `subtypes` here), and a new `Effect::ExileAllGraveyards`
  port. **Smallest Effect port** of the three.
* **Phase 3C — Thespian's Stage** (`{2}, {T}: BecomesCopyOfTargetLand`).
  Copy-effect substrate (CR-613 layer-1): per-`GameObject` copy-of-
  printing pointer + resolve-time copy primitive + interaction with
  the mana-ability auto-wire of the copied Land + an `original_printing`
  snapshot field for re-copy retention. **HEAVIEST of the three** by a
  wide margin — needs a new `GameObject` field, a new printing-registry
  push at resolve time (or a new `printing_id_override` slot), and
  careful interaction with cleanup steps + zone changes (the copy
  must NOT survive Thespian's Stage leaving the battlefield, per CR
  613.6c). NO co-bundling with Mirrorpool (see §2.4 below).

**Phase 3 admit delta:** **+3 cards** (Mystifying Maze + Scavenger
Grounds + Thespian's Stage). Each FLIP is independent — Phase 3A's
admit does not depend on 3B's or 3C's; same for the others.

**Cycle estimate:** **~11 cycles total** across the three sub-phases —
Phase 3A: 3 cycles (Rust delayed-trigger producer + Python admit +
real-EoE probe). Phase 3B: 3 cycles (Rust `ExileAllGraveyards` port +
Python admit + Desert-subtype subtype-admission audit + real-EoE
probe). Phase 3C: 5 cycles (Rust copy-effect substrate + Python admit
+ re-copy / cleanup invariant pin set + real-EoE probe set + careful
LTB-clears-copy hookup).

**Out-of-scope (Phase 4+):**
* **Mirrorpool** (`{3}, {T}, Sac: CopyTargetInstantOrSorceryYouControl`
  / `{5}, {T}, Sac: CreateTokenCopyOfTargetCreatureYouControl`) — see
  §2.4. Mirrorpool's copy effects are CR-707.2 spell-copy and CR-707.5
  token-copy, NOT the CR-613 layer-1 object-copy substrate Thespian's
  Stage needs. Co-bundling at the substrate level is **structurally
  rejected** (different copy-machinery families). Also multi-AA +
  generic-cost-with-`Sac:` rider already in Phase 2's `{N}, {T}, Sac:`
  gate. **Phase 4** (multi-AA admit predicate + CR-707.2 spell-copy
  Effect port + CR-707.5 token-creature-copy Effect port).
* **Ghost Vacuum / Keys to the House / All-Fates Scroll / Haunted
  Screen / The Eternity Elevator** — multi-AA carriers + various
  rider surfaces (sorcery-speed, activate-only-once, tier-threshold,
  pay_life, station_threshold). **Phase 4+** per the Phase 2 §3.4
  multi-AA roadmap.
* **Mana-ability / sorcery-speed / Equipment / BecomeLand-rider /
  Creature-carrier / X-pip / colored-mana / activate-only-once /
  tier-threshold / room-half** rider clusters — **Phase N** per Phase
  1 §3.

**Substrate-leverage:** Phase 3 lands **three orthogonal substrates
that compositionally unlock Phase 4+**:
* The delayed_triggers PRODUCER arm in Rust (3A) is a generic
  primitive every future "exile-until-end-of-something" /
  "sacrifice-source-at-end-step" / "remove-counters-at-end-step" /
  "return-exiled-permanent-at-end-step" Effect inherits.
* The `Effect::ExileAllGraveyards` arm (3B) is a per-zone-mass-effect
  shape that future "destroy all creatures", "exile all artifacts",
  etc. mass-effect ports follow.
* The CR-613 layer-1 copy-of-permanent substrate (3C) is the layer
  primitive every future "this becomes a copy of target permanent"
  / "create token copy of target permanent" port inherits — Mirrorpool
  AA[1] (`CreateTokenCopyOfTargetCreatureYouControl`) reuses the
  copy-printing-registry primitive even though it doesn't share the
  per-`GameObject` `original_printing` slot.

---

## 1. Background — Phase 2 closure and the 26-card residue

Phase 2a + Phase 2b shipped the `{T}, Sac:` cost-shape widen
(Petrified Field) + the `PutBasicLandFromHandOntoBattlefieldTapped`
Effect port (Terrain Generator). The Phase 2 §2.1 28-card residue is
now 26 cards at HEAD `03fdc3e6`. The Phase 2 §"Phase 3+ deferral" row
called out:

> * **Mystifying Maze** — needs **delayed-trigger / EoT-return substrate**.
> * **Thespian's Stage** — needs **copy-effect substrate**.
> * **Scavenger Grounds** — needs `sacrifice_a_desert` cost shape +
>   `Land — Desert` subtype admission + `ExileAllGraveyards` Effect port.

These three were grouped as "Phase 3+ deferrals" because each carries
its own per-Effect-family substrate beyond the Phase 1-2 admit gate
machinery. Phase 3 lands those three substrates in three independent
sub-phases.

**Why one design doc, not three.** The three sub-phases ship 3 cards
on 3 independent codepaths; the campaign-shape question — "what is
the Phase 3 admit delta" — has a single answer (+3 cards), and the
out-of-scope matrix + the rejected-alternatives ("bundle these into
one cycle" / "bundle two of them" / "bundle with Mirrorpool") is
identical across all three. Phase 1.5 split into a/b sub-phases under
one design doc on the same precedent.

---

## 2. Verify-first walk — the 3 candidate cards at HEAD `03fdc3e6`

The walk script (a one-off scout `_scout_phase3.py`, not committed —
design-lane verify-first discipline) enumerated each of the 3 cards'
`(card_types, subtypes, n_aa, n_ta, n_sa, keywords)` and AA[0]'s
`(cost, effect-class, AA-riders)`. Reproducible at a future HEAD via
the Phase 2 §13 regeneration script seeded with the 3-card list.

### 2.1 Per-card details (verified live)

| Card | Type | n_aa | n_ta | AA[0] cost | AA[0] Effect | Substrate need |
|---|---|---:|---:|---|---|---|
| **Mystifying Maze** | Land | 1 | 0 | `{4}, {T}` | `ExileTargetAttackingCreatureUntilEndStep` | Delayed-trigger PRODUCER + exile + return-from-exile-tapped |
| **Scavenger Grounds** | Land — Desert | 1 | 0 | `{2}, {T}, Sac-a-Desert:` | `ExileAllGraveyards` | Cost-bool gate (Python only) + Desert subtype admission + Effect port |
| **Thespian's Stage** | Land | 1 | 0 | `{2}, {T}` | `BecomesCopyOfTargetLand` | CR-613 layer-1 copy substrate (per-`GameObject` slot + resolve-time copy + LTB-clears) |

All three are single-AA Land carriers with no triggered/static
abilities and no keywords — they pass every printing-level admit
guard of `_printing_is_bridge_simple_carrier_aa_land` UNCHANGED. The
Phase 3 widen is per-AA only (Effect-class admit + the Scavenger
Grounds cost-bool gate + the Scavenger Grounds subtype-admission
audit).

### 2.2 Python Effect-class signatures (verified live)

* **`ExileTargetAttackingCreatureUntilEndStep`** at
  `src/mtg_bot/effects/generic/exile.py:180-255`. `requires_target() = True`.
  `legal_targets()` walks `state.battlefield` for objects with
  `printing.is_creature AND attacking AND controller_id != activator`.
  Resolves by `move_off_battlefield(state, target, destination="exile")`
  then appends a dict to `state.delayed_triggers` with
  `{fire_at_turn: state.turn_number, controller_id: active_player.id,
  effect: ReturnExiledPermanentToOwnerTapped(exile_card_id=target.id),
  source_id: maze_source.id}`. The delayed trigger fires at the
  ACTIVE PLAYER's next end step (CR 603.7c — Maze is instant-speed on
  an opponent's combat, so "next end step" is the active player's
  own end step).

* **`ExileAllGraveyards`** at `exile.py:661-683`. `requires_target() = False`.
  Resolves by walking every `player.graveyard`, moving every card to
  the SAME player's `exile`. Logs `f"all graveyards exiled ({total}
  cards)"`. No target enumeration. No replacement-effect interactions
  in the minimum semantics.

* **`BecomesCopyOfTargetLand`** at
  `src/mtg_bot/effects/generic/become_type.py:246-312`.
  `requires_target() = True`. `legal_targets()` walks
  `state.battlefield` for any object with `printing.is_land`.
  Resolves by:
  1. Snapshotting `source.original_printing = source.printing` if
     `source.original_printing is None` (first-copy snapshot — Python
     `GameObject.original_printing: CardPrinting | None`).
  2. Building a fresh `CardPrinting` via `dataclasses.replace(
     target.printing, activated_abilities=tuple(target.printing.activated_abilities)
     + tuple(source.original_printing.activated_abilities))` — i.e.
     COPY the target's full printing AND APPEND the activator's own
     pre-copy activated abilities ("except it has this ability").
  3. Mutating `source.printing` to that fresh `CardPrinting`.

  Implementation notes: the source `original_printing` snapshot
  prevents accumulating "this ability" across repeated re-copies. The
  copy effect is CONTINUOUS — it persists until the source leaves
  play OR another copy effect overrides (CR 613.6c per-zone reset
  drops the `original_printing` slot via the standard zone-change
  reset).

### 2.3 Rust substrate state (verified live at HEAD `03fdc3e6`)

| Primitive | File:line | Status |
|---|---|---|
| `state.delayed_triggers: Vec<DelayedTrigger>` | `rust/src/state.rs:2335` | **EXISTS** (G7 Class-C delayed-trigger port, round-78; WarpExileSelf precedent) |
| `DelayedTrigger { fire_at_turn, controller_id, source_id, effect }` | `rust/src/cards.rs:8585-8615` | **EXISTS** (4-field shape generalized for non-warp producers) |
| `run_delayed_end_step_triggers` end-step dispatch | `rust/src/state_ops_steps.rs:434-540` | **EXISTS** (FIFO `push_triggered_ability` route; source-existence skip; CoW empty-Vec fast path) |
| `state.attackers: Vec<u32>` for combat-attacker target enumeration | `rust/src/state.rs:2252` | **EXISTS** |
| `Effect::ExileTargetCreatureUntilSourceLeaves` (CR-613-adjacent — until-leaves exile) | `rust/src/state_ops_resolve.rs` + state | **EXISTS** (round-28 attach foundation; `exiled_with_source: Option<u32>`) — DIFFERENT semantics from Maze's "until end of step" (Maze does NOT carry `exiled_with_source`, and the return fires unconditionally on EoT, not on source-leaves) |
| `ActivationCost.sacrifice_a_desert: bool` | `rust/src/cards.rs:9856` | **EXISTS** (CE20 follow-up, Lander precedent) |
| `parse_activation_cost` `sacrifice_a_desert` arm | `rust/src/cards.rs:16294-16298` | **EXISTS** |
| `state_ops_legal.rs` `sacrifice_a_desert` target fan-out + Desert-subtype lenient SELF-eligibility | `rust/src/state_ops_legal.rs:3462,3479,3522` | **EXISTS** (Lander cost-pay precedent) |
| `state_ops_actions.rs` `sacrifice_a_desert` cost-pay commit | `rust/src/state_ops_actions.rs:896,1120,1179` | **EXISTS** |
| `Effect::ExileAllGraveyards` resolve arm | `rust/src/state_ops_resolve.rs` | **DOES NOT EXIST** (Phase 3B port) |
| `Effect::ExileTargetAttackingCreatureUntilEndStep` resolve arm | `rust/src/state_ops_resolve.rs` | **DOES NOT EXIST** (Phase 3A port) |
| `Effect::ReturnExiledPermanentToOwnerTapped` (the delayed-trigger payload effect) | `rust/src/state_ops_resolve.rs` + `cards.rs:8612` | **DOES NOT EXIST** (Phase 3A port — the comment at `cards.rs:8612` explicitly lists it as a future producer's effect) |
| `Effect::BecomesCopyOfTargetLand` resolve arm | `rust/src/state_ops_resolve.rs` | **DOES NOT EXIST** (Phase 3C port — single new variant) |
| `GameObject.original_printing` / `printing_id_override` slot | `rust/src/state.rs:35-150` | **DOES NOT EXIST** (Phase 3C — new field; cleared on zone change per CR 400.7) |
| `Effect::CopyTargetInstantOrSorceryYouControl` (Mirrorpool AA[0]) | `rust/src/state_ops_resolve.rs` | **DOES NOT EXIST** — Phase 4+ (different machinery family per §2.4) |

**Cumulative substrate weight:**
* **Phase 3A:** 2 new Effect resolve arms (Maze's exile + the delayed-
  trigger payload's `ReturnExiledPermanentToOwnerTapped`) + 1 new
  delayed-trigger PRODUCER call site + an attacking-creature target
  fan-out arm in `state_ops_legal.rs::activate_ability_dict`. **NO
  new state field** (the `delayed_triggers` Vec is reused).
* **Phase 3B:** 1 new Effect resolve arm (`ExileAllGraveyards`). **NO
  new state field. NO new cost-shape Rust changes.** Pure Python
  admit widen + 1 Rust Effect port + 1 subtype-admission audit.
* **Phase 3C:** 1 new Effect resolve arm (`BecomesCopyOfTargetLand`)
  + 1 new `GameObject` field (`original_printing: Option<u32>` —
  printing-registry id, NOT a clone of the CardPrinting struct) +
  resolve-time printing-registry push for the copy + zone-change
  reset hook for the new field + ANY copy-related `effective_*`
  lookups (effective_subtypes, effective_card_types, effective_keywords,
  mana-ability registration on the copied Land — see §4.3 for the
  full audit).

### 2.4 Co-bundling audit — Thespian's Stage + Mirrorpool

The Phase 1.5 doc §9.5 used the user-facing framing "bundle Thespian's
Stage and Mirrorpool's copy AAs together in a future copy-effect
substrate" — that framing is the COVERED-BY-CONSTRUCTION saturation
report's pivot-shape, not a technical-implementation bundling. The
actual implementation substrates are ORTHOGONAL:

| Card | Effect class | Copy machinery family | Rust primitive | Substrate co-bundle? |
|---|---|---|---|---|
| Thespian's Stage | `BecomesCopyOfTargetLand` | CR-613 layer-1 object-copy (per-`GameObject` slot) | `GameObject.original_printing` + resolve-time printing mutation | — |
| Mirrorpool AA[0] | `CopyTargetInstantOrSorceryYouControl` | CR-707.2 spell-copy (on-stack copy of a spell) | New `StackItem` push with a copied spell ref | NO — different state surface |
| Mirrorpool AA[1] | `CreateTokenCopyOfTargetCreatureYouControl` | CR-707.5 token-creature-copy (create a new token mirroring a battlefield permanent's printing) | New token allocation + printing-registry push | PARTIAL — shares the "printing-registry push to copy a permanent's printing" primitive that 3C ports, but uses `CreateToken` shape on the resolve, not the per-`GameObject` `original_printing` slot |

**Conclusion: Mirrorpool does NOT co-bundle with Thespian's Stage at
the substrate level.** Mirrorpool's two effects are in two DIFFERENT
copy-machinery families (CR-707.2 vs CR-707.5), and Thespian's Stage
sits in a THIRD family (CR-613). Phase 4's multi-AA admit + Mirrorpool's
two Effect ports stay independent.

However, **Phase 3C lays the printing-registry copy primitive that
Mirrorpool AA[1]'s `CreateTokenCopyOfTargetCreatureYouControl` Effect
port can reuse** (the "push a new CardPrinting derived from a
battlefield permanent's printing into the registry" step). The
PER-`GameObject` `original_printing` slot stays Thespian's-Stage-
specific; the registry push primitive is Phase-4 reusable. See §9.4
for the rejection of bundling Mirrorpool into Phase 3.

### 2.5 Phase 3 sub-phase ordering

Sub-phases ordered by **substrate weight × cycle independence**:

1. **Phase 3A first (Mystifying Maze)** — middle substrate weight, but
   the delayed-trigger PRODUCER + return-from-exile-tapped pair are
   composition primitives every later sub-phase / phase reuses (Phase
   N "remove-counters-at-end-step" / "sacrifice-source-delayed" /
   any other delayed-trigger Effect). Lands the highest-leverage Rust
   primitive of Phase 3.
2. **Phase 3B second (Scavenger Grounds)** — smallest Effect port +
   smallest Python admit widen (cost-bool gate + Desert subtype
   audit). Cleanest cycle.
3. **Phase 3C last (Thespian's Stage)** — heaviest substrate; new
   `GameObject` field + resolve-time printing-registry mutation +
   zone-change reset hook + LTB-clears-copy hookup. Largest cross-
   engine surface — leave for last so Phase 3A + 3B's smaller cycles
   land first as substrate-stability validation.

Each sub-phase is **independent** — no admit set in 3B depends on
3A's substrate, and no Rust slice in 3C depends on either. The
sequencing recommendation is engineering-discipline ordering (smaller
substrates first to validate the campaign shape), not a substrate-
dependency ordering.

---

## 3. Out of scope (Phase 4 / N)

Phase 3 retains every Phase 1 + 1.5 + 2 out-of-scope clause unchanged.
Specifically out-of-scope of Phase 3:

### 3.1 Mirrorpool's two copy AAs (Phase 4)

Mirrorpool's `CopyTargetInstantOrSorceryYouControl` (CR-707.2 spell-
copy) and `CreateTokenCopyOfTargetCreatureYouControl` (CR-707.5
token-creature-copy) sit in DIFFERENT copy-machinery families than
Thespian's Stage's CR-613 layer-1 object-copy (per §2.4). Both
Mirrorpool effects also require the multi-AA admit-predicate widen
(Mirrorpool has n_aa=2). **Phase 4** — multi-AA admit predicate +
the two Mirrorpool Effect ports + the printing-registry-push
primitive that Phase 3C ships reusably.

### 3.2 Multi-AA carriers (Phase 4)

Ghost Vacuum / Keys to the House / All-Fates Scroll / Haunted Screen /
The Eternity Elevator — all multi-AA carriers in the 26-card residue.
**Phase 4** per Phase 2 §3.4.

### 3.3 Mana-ability / sorcery-speed / Equipment / BecomeLand / Creature-carrier / X-pip / colored-mana / activate-only-once / tier-threshold / room-half (Phase N)

Every rider cluster from Phase 1 §3.2-§3.9 + Phase 2 §3.2-§3.9
remains Phase N. Phase 3 does NOT touch any of these.

### 3.4 Replacement-effect interactions on graveyard-to-exile / battlefield-to-exile / exile-to-battlefield zone moves

Phase 3A's exile + return primitive + Phase 3B's mass-graveyard-exile
each touch a zone-move primitive. Replacement effects (CR 614) on
those zone moves (e.g. "if a creature would be put into a graveyard
from anywhere, exile it instead" — Rest in Peace shape) are NOT
modeled in the minimum Phase 3 semantics. None of the EoE printings
in the affected pool fire such replacement effects on these zone
transitions; this is a documented simplification (per Phase 2 §8 SL
entry shape).

### 3.5 `until end of step` vs `until end of turn` distinction (Phase N — bookkeeping cleanup)

CR 603.7c says "at the beginning of the next end step" — i.e. the
delayed trigger fires once, at the end step that occurs after the
ability resolves. Python's `ExileTargetAttackingCreatureUntilEndStep`
implements this via the `fire_at_turn: state.turn_number` shape,
which fires at the active player's NEXT end step in the same turn (or
the next turn's end step if Maze activated post-end-step of the same
turn — corner case that Python's existing code handles correctly).
Phase 3A's Rust mirror byte-equals this scheduling; the CR 603.7
"until end of step" exact-step semantics are inherited from the
existing WarpExileSelf delayed-trigger producer's same `fire_at_turn`
shape.

### 3.6 Copy effects beyond "becomes a copy of target Land" (Phase N — copy-effect substrate widen)

Thespian's Stage's specific Effect is `BecomesCopyOfTargetLand` —
"copy target LAND". Other copy-of-permanent printings (legendary
copies, planeswalker copies, creature-copy from Clone-shape spells)
need different target-filter predicates and may interact with their
own per-type semantics. Phase 3C ports the LAND-specific Effect; the
broader "this becomes a copy of target X" generalization stays
Phase N.

---

## 4. Rust-side spec

Phase 3 ships **four new `Effect` variants** plus **one new
`GameObject` field** plus **one new target-fan-out arm** in
`state_ops_legal.rs::activate_ability_dict`. Each sub-phase's slice
is disjoint.

### 4.1 Phase 3A — `Effect::ExileTargetAttackingCreatureUntilEndStep` + `Effect::ReturnExiledPermanentToOwnerTapped`

**Files:**
* `rust/src/cards.rs` — Effect enum + parse arm + to_pydict arm
  (TWO new variants).
* `rust/src/state_ops_resolve.rs` — resolve arms.
* `rust/src/state_ops_legal.rs::activate_ability_dict` — new
  attacking-creature target fan-out arm.

**Semantics — `ExileTargetAttackingCreatureUntilEndStep`** (CR 701.18
exile, CR 603.7 delayed-trigger production):

1. Target a creature that:
   * is on the battlefield (`zone == ZONE_BATTLEFIELD`),
   * is currently attacking (`state.attackers.contains(target.id)`),
   * is controlled by an opponent of the activator
     (`target.controller != activator_controller`).
2. On resolve:
   * If the target left the battlefield since activation, fizzle
     silently (CR 608.2b target-legality re-check).
   * Else exile the target via the standard bf-to-exile primitive
     (`move_off_battlefield(state, target, exile)` analog in Rust —
     update `obj.zone = ZONE_EXILE`, remove from `battlefield`, push
     onto `players[controller_id].exile`).
   * Schedule a delayed trigger:
     ```rust
     state.delayed_triggers.push(DelayedTrigger {
         fire_at_turn: state.turn_number,  // active player's next end step
         controller_id: state.active_player,
         source_id: maze_source_id,  // Maze itself (state.resolving_source)
         effect: Effect::ReturnExiledPermanentToOwnerTapped {
             exile_card_id: target.id,
         },
     });
     ```
   * Stamp the exiled object so the return primitive can find it
     by id (the existing `exiled_with_source` slot is wrong — that's
     for until-source-leaves shape; for Maze the return fires
     unconditionally on EoT regardless of whether Maze still exists).
     **No new state field** — the `exile_card_id` slot lives ON the
     `Effect::ReturnExiledPermanentToOwnerTapped` payload, which the
     `DelayedTrigger.effect` field already carries by value.

**Semantics — `ReturnExiledPermanentToOwnerTapped`** (CR 701.3 +
408.1 — return-to-battlefield-tapped):

1. Fired as a delayed trigger at the active player's end step (per
   `run_delayed_end_step_triggers`).
2. On resolve:
   * Walk both players' `exile` for the object with `id == exile_card_id`.
   * If not found, silently no-op (CR 603.6c — the object may have
     been moved by another effect; Python mirrors this).
   * Else move the object from exile to `players[obj.owner].battlefield`
     (note: OWNER, not controller — CR 110.2; the controller defaults
     to the owner on bf re-entry).
   * Stamp `obj.tapped = true`, `obj.zone = ZONE_BATTLEFIELD`,
     `obj.controller = obj.owner`, reset per-zone-change fields
     (CR 400.7), and dispatch `Event::EntersBattlefield(obj.id)` —
     ETB triggers (incl. landfall) fire on the return per CR 603.6a.

**Phase 3A Rust spec:**

```rust
// In Effect enum (cards.rs):
ExileTargetAttackingCreatureUntilEndStep,
ReturnExiledPermanentToOwnerTapped { exile_card_id: u32 },

// In parse_effect (cards.rs):
"exile_target_attacking_creature_until_end_step" =>
    Effect::ExileTargetAttackingCreatureUntilEndStep,
"return_exiled_permanent_to_owner_tapped" => {
    let id = dict.get_item("exile_card_id")?
        .ok_or_else(|| /* error */)?
        .extract::<u32>()?;
    Effect::ReturnExiledPermanentToOwnerTapped { exile_card_id: id }
}

// In to_pydict (cards.rs):
Effect::ExileTargetAttackingCreatureUntilEndStep => {
    py_dict.set_item(
        "kind",
        "exile_target_attacking_creature_until_end_step",
    )?;
}
Effect::ReturnExiledPermanentToOwnerTapped { exile_card_id } => {
    py_dict.set_item(
        "kind", "return_exiled_permanent_to_owner_tapped",
    )?;
    py_dict.set_item("exile_card_id", exile_card_id)?;
}

// In resolve dispatch (state_ops_resolve.rs): see semantics above.
```

**Target enumeration in `state_ops_legal.rs::activate_ability_dict`.**
New fan-out arm: for an AA whose Effect is
`ExileTargetAttackingCreatureUntilEndStep`, enumerate every battlefield
GameObject with `state.attackers.contains(obj.id) AND obj.controller
!= activator_controller AND obj.printing.is_creature_now` and emit
one `ActivateAbility` action per eligible target. **Mirror of the
sacrifice-target fan-out at `state_ops_legal.rs:3408-3505`**, reading
the `attackers` Vec instead of the player's battlefield + the
sacrifice-type filter.

**Combat-phase guard.** Maze's printed text says "target attacking
creature" — the `state.attackers` Vec is only populated during
combat phases (declare-attackers → end-of-combat). Outside combat,
the Vec is empty, the fan-out emits 0 targets, and the activation
is illegal (per CR 117.5 — an activated ability with NO legal target
cannot be activated). **No new state field; no new combat-phase
plumbing.**

### 4.2 Phase 3B — `Effect::ExileAllGraveyards`

**Files:**
* `rust/src/cards.rs` — Effect enum + parse arm + to_pydict arm.
* `rust/src/state_ops_resolve.rs` — resolve arm.

**Semantics:** zero-target mass effect. On resolve, walk every
`state.players[i].graveyard` (i ∈ {0, 1}), for every `GameObject`
in the graveyard, move it to that same player's `exile`. Stamp
`obj.zone = ZONE_EXILE`. Match Python's `exile.py:661-683` exactly.

**Phase 3B Rust spec:**

```rust
// In Effect enum (cards.rs):
ExileAllGraveyards,

// In parse_effect (cards.rs):
"exile_all_graveyards" => Effect::ExileAllGraveyards,

// In to_pydict (cards.rs):
Effect::ExileAllGraveyards => {
    py_dict.set_item("kind", "exile_all_graveyards")?;
}

// In resolve dispatch (state_ops_resolve.rs):
Effect::ExileAllGraveyards => {
    for player_idx in 0..2 {
        let player = &mut state.players[player_idx];
        let drained: Vec<GameObject> = player.graveyard.drain(..).collect();
        for mut obj in drained {
            obj.zone = ZONE_EXILE;
            // CR 400.7 — per-zone-change resets
            obj.tapped = false;
            obj.summoning_sick = false;
            obj.damage = 0;
            obj.counters = 0;
            obj.charge_counters = 0;
            obj.loyalty_counters = 0;
            obj.stun_counters = 0;
            obj.attached_to = None;
            obj.exiled_with_source = None;
            obj.regeneration_shield = false;
            player.exile.push(obj);
        }
    }
}
```

**Targeting model:** ZERO. No fan-out arm needed — the activator
emits a single `ActivateAbility` action with no target field. The
`{2}, {T}, Sac-a-Desert:` cost itself fans out over the activator's
Desert-subtype Lands (via the existing `state_ops_legal.rs:3522`
Desert-target fan-out, per the Lander precedent), but the EFFECT
has no target.

**Cost-side machinery — VERIFIED EXISTS at HEAD `03fdc3e6`:**

| Link | File:line | Status |
|---|---|---|
| `ActivationCost.sacrifice_a_desert: bool` | `cards.rs:9856` | EXISTS |
| `parse_activation_cost` `sacrifice_a_desert` arm | `cards.rs:16294-16298` | EXISTS |
| `state_ops_legal.rs` `sacrifice_a_desert` Desert-target fan-out | `state_ops_legal.rs:3522` | EXISTS (lenient SELF-eligibility: source IS eligible if it has Desert subtype, per Lander precedent) |
| `state_ops_actions.rs` `sacrifice_a_desert` cost-pay commit | `state_ops_actions.rs:1179` | EXISTS |
| `_python_aa_to_safe_dict` `sacrifice_a_desert` emit | `cross_engine.py:14113` (per Phase 2 §3.1) | EXISTS |

**Conclusion — Phase 3B's `{2}, {T}, Sac-a-Desert:` cost shape needs
ZERO Rust cost-side changes.** The Phase 3B Rust slice is a single
new `Effect::ExileAllGraveyards` variant + arms. **NO new state
field; NO new cost-shape machinery.**

### 4.3 Phase 3C — `Effect::BecomesCopyOfTargetLand` (HEAVY)

**Files:**
* `rust/src/cards.rs` — Effect enum + parse arm + to_pydict arm.
* `rust/src/state_ops_resolve.rs` — resolve arm.
* `rust/src/state.rs` — new `GameObject.original_printing_id:
  Option<u32>` slot + per-zone-change reset.
* `rust/src/state_ops_legal.rs::activate_ability_dict` — new Land-
  target fan-out arm.
* Various `effective_*` lookups (subtypes / card_types / keywords /
  power-toughness / mana-ability registration) — verify they read
  `printing_id` indirected through the registry consistently.

**Semantics — `BecomesCopyOfTargetLand`** (CR 613.6c — layer-1 copy
effect, persists until source leaves play OR another copy effect
overrides):

1. Target a battlefield `GameObject` with `printing.is_land == true`
   (any controller — Thespian's Stage can copy an opponent's Land per
   CR 109.3 / 613).
2. On resolve:
   * If the target left the battlefield since activation, fizzle
     silently (CR 608.2b).
   * If `source.original_printing_id is None`, snapshot:
     `source.original_printing_id = Some(source.printing_id)`.
   * Build a new `CardPrinting` derived from the target's:
     - Same name, card_types, subtypes, supertypes, mana_value,
       colors, base_pt (if any) as the target's printing.
     - `activated_abilities = target.activated_abilities ++
       source's_pre_copy_AAs` — the activator's pre-copy AAs are
       fetched from the printing-registry entry at
       `source.original_printing_id`'s `activated_abilities`.
   * Push the new printing into the registry via `state.push_printing(new_printing)`
     → get back a fresh `printing_id`.
   * Mutate `source.printing_id = new_printing_id`.

3. **Continuous effect** — the copy persists until the source leaves
   the battlefield. CR 400.7 zone-change reset clears
   `original_printing_id` to `None` on bf-leave (no implicit
   restoration of the pre-copy printing — Python's behavior: once
   Thespian's Stage leaves play, the object's `printing` slot is
   no longer relevant because the object is no longer a permanent
   under that printing).

**Phase 3C Rust spec:**

```rust
// In GameObject (state.rs):
pub struct GameObject {
    // ... existing fields ...
    /// **Carrier-AA Phase 3C — BecomesCopyOfTargetLand snapshot.**
    /// When a layer-1 copy effect (Thespian's Stage shape) mutates
    /// `printing_id` to a copy of a target's printing, the
    /// pre-copy printing-registry id is snapshotted here so re-copy
    /// activations re-derive "retained own abilities" from the
    /// original printing's `activated_abilities` rather than the
    /// already-mutated post-copy slot.
    ///
    /// Mirrors Python's `GameObject.original_printing:
    /// CardPrinting | None`. Cleared (reset to `None`) on every
    /// zone change (CR 400.7 per-object state reset) — the copy
    /// relationship is a battlefield-only concept.
    ///
    /// Fingerprint emits this slot as `Null` when `None`, so
    /// default-state pinned baselines stay byte-identical.
    pub original_printing_id: Option<u32>,
}

// In Effect enum (cards.rs):
BecomesCopyOfTargetLand,

// In parse_effect (cards.rs):
"becomes_copy_of_target_land" => Effect::BecomesCopyOfTargetLand,

// In to_pydict (cards.rs):
Effect::BecomesCopyOfTargetLand => {
    py_dict.set_item("kind", "becomes_copy_of_target_land")?;
}

// In resolve dispatch (state_ops_resolve.rs): see semantics above.
```

**Target enumeration in `state_ops_legal.rs::activate_ability_dict`.**
New fan-out arm: enumerate every battlefield `GameObject` with
`printing.is_land == true` (read via the printing registry as
`state.registry.get(obj.printing_id).is_land`). Both players'
battlefields. **Mirror of the existing Land-target fan-out for
`UntapTargetLand` at `state_ops_legal.rs::activate_ability_dict`'s
Phase-1 substrate (the existing UntapTargetLand fan-out is the
direct shape model).**

**Re-copy semantics.** Calling `BecomesCopyOfTargetLand` on a source
that already has `original_printing_id = Some(orig_id)`: the
"retained own abilities" snapshot is the ORIGINAL printing's AAs
(read from registry by `original_printing_id`), NOT the most-recent
post-copy slot. This prevents AA accumulation across multiple
copies (Python's invariant at `become_type.py:293-296`).

**Zone-change reset hookup.** The per-zone-change `obj.zone = NEW_ZONE`
sweep across `state_ops_actions.rs` (every bf-leave path) MUST
also clear `original_printing_id = None`. **Audit required**: every
zone-change-stamp call site in Rust (sacrifice, destroy, exile,
return-to-hand, return-to-library, mill, etc.). The same audit
pattern Phase 1 ran for `regeneration_shield`.

**Effective-* lookups.** Every "what's this object's effective
power/toughness/subtypes/card_types/mana-cost" call must read
`obj.printing_id` indirected through the printing registry — NOT
a cached pre-copy snapshot. **Audit required**: walk every
`effective_*` call site in `rust/src/state.rs` + `state_ops_*.rs`
+ `cards.rs` for assumptions that `printing_id` is invariant for
the object's lifetime. **Expected outcome**: every call already
reads the registry through `printing_id` because Rust never carried
a Python-style direct printing pointer on `GameObject`; the indirect-
through-registry path is the canonical mechanism. The audit
confirms this.

**Mana-ability auto-wire on the copied Land.** When Thespian's
Stage copies "Mountain" (or any basic / dual / utility Land), the
copied printing carries the mana-ability AA[0] of the target. The
mana-ability admit path at `state_ops_legal.rs::activate_ability_dict`
walks the printing's `activated_abilities` tuple — since the
mutated `printing.activated_abilities` now contains the target's
mana ability(ies), the activation is legal. **No new mana-ability
wiring is needed**; the copy is transparent through the existing
printing-driven activation machinery. (Phase 1 §5.7 mana-ability
admit is OUT-OF-SCOPE on the Carrier-AA admit predicate side, but
the COPIED Land's mana ability activates through the existing
non-Carrier-AA basic-land activation path, which is bridge-covered
ALREADY.)

**Cleanup-step interactions.** Layer-1 copy effects survive
cleanup (CR 514). The `original_printing_id` slot is NOT cleared
at cleanup; only zone change clears it. **No new cleanup-step
wiring is needed.**

### 4.4 No new cost-shape Rust changes across Phase 3

* Phase 3A's `{4}, {T}` cost is in the existing `{N}, {T}` cost gate
  (Phase 1.5a shape).
* Phase 3B's `{2}, {T}, Sac-a-Desert:` cost is the existing
  `{N}, {T}, Sac-a-Desert:` cost shape (Lander precedent, fully
  wired per §4.2's audit).
* Phase 3C's `{2}, {T}` cost is the existing `{N}, {T}` cost gate
  (Phase 1.5a shape).

**All three sub-phases inherit fully-wired Rust cost shapes; the new
Rust slices are pure Effect ports + (3A) target fan-out + (3C) state
field.**

---

## 5. Python bridge spec

### 5.1 Effect-class gate widen across Phase 3

**File:** `src/mtg_bot/parity/trajectory.py`,
`_carrier_aa_phase_1_effect_classes` at line 8465. The accessor name
keeps the Phase-1 prefix for back-compat (per Phase 2 §5.2). Each
sub-phase appends ONE Effect class.

```python
def _carrier_aa_phase_1_effect_classes() -> "frozenset[type]":
    # Phase 3 widens the admit set to SEVEN Effect classes — adds
    # ``ExileTargetAttackingCreatureUntilEndStep`` (Mystifying Maze),
    # ``ExileAllGraveyards`` (Scavenger Grounds), and
    # ``BecomesCopyOfTargetLand`` (Thespian's Stage).
    from mtg_bot.effects.generic.destroy import RegenerateTargetCreature
    from mtg_bot.effects.generic.tap import UntapTargetLand
    from mtg_bot.effects.generic.bounce import (
        ReturnTargetLandFromGraveyardToHand,
    )
    from mtg_bot.effects.generic.zone_moves import (
        PutBasicLandFromHandOntoBattlefieldTapped,
    )
    from mtg_bot.effects.generic.exile import (
        ExileTargetAttackingCreatureUntilEndStep,
        ExileAllGraveyards,
    )
    from mtg_bot.effects.generic.become_type import (
        BecomesCopyOfTargetLand,
    )
    return frozenset({
        RegenerateTargetCreature,
        UntapTargetLand,
        ReturnTargetLandFromGraveyardToHand,
        PutBasicLandFromHandOntoBattlefieldTapped,
        # Phase 3:
        ExileTargetAttackingCreatureUntilEndStep,
        ExileAllGraveyards,
        BecomesCopyOfTargetLand,
    })
```

Each Phase-3 sub-phase appends ITS Effect class in a separate
Python-only cycle; the frozenset grows by exactly 1 entry per
sub-phase.

### 5.2 Phase 3A — `ExileTargetAttackingCreatureUntilEndStep` + bridge arms

**File:** `src/mtg_bot/parity/cross_engine.py`.

The `_python_aa_to_safe_dict` forward arm at line 14031+ adds:

```python
elif isinstance(effect, ExileTargetAttackingCreatureUntilEndStep):
    effect_dict = {
        "kind": "exile_target_attacking_creature_until_end_step",
    }
```

(Note — `ExileTargetAttackingCreatureUntilEndStep` is NOT a subclass
of `Exile`; it's a sibling `Effect` subclass per `exile.py:180`. The
isinstance match on the SPECIFIC class is safe — no parent-class
catch.)

The `_ta_dict_to_python_effect` reverse arm at line 12360+ adds:

```python
if kind == "exile_target_attacking_creature_until_end_step":
    from mtg_bot.effects.generic.exile import (
        ExileTargetAttackingCreatureUntilEndStep,
    )
    return ExileTargetAttackingCreatureUntilEndStep()
```

**Delayed-trigger snapshot bridge.** The `delayed_triggers` Vec in
Rust carries `DelayedTrigger { fire_at_turn, controller_id,
source_id, effect: Effect }`. Python's `state.delayed_triggers:
list[dict]` carries the same shape (dict-keyed). The existing
`delayed_triggers_snapshot` method on Rust GameState
(`rust/src/state.rs:3268`) emits a list of dicts; the existing
`_ta_dict_to_python_effect` decoder must accept the new
`ReturnExiledPermanentToOwnerTapped` kind. The PRODUCER side emits
the Rust delayed-trigger entry from inside the
`ExileTargetAttackingCreatureUntilEndStep` resolve arm; the
SNAPSHOT side already routes the entry to Python via the existing
codec. **One new arm in `_ta_dict_to_python_effect`**:

```python
if kind == "return_exiled_permanent_to_owner_tapped":
    from mtg_bot.effects.generic.exile import (
        ReturnExiledPermanentToOwnerTapped,
    )
    return ReturnExiledPermanentToOwnerTapped(
        exile_card_id=int(d["exile_card_id"]),
    )
```

**`_python_aa_to_safe_dict` forward arm for `ReturnExiledPermanentToOwnerTapped`.**
The same forward arm is needed at the producer site (for the
DelayedTrigger entry's `effect` slot — Python writes a Python
`ReturnExiledPermanentToOwnerTapped` instance into its
`state.delayed_triggers` list; the bridge must serialize it):

```python
elif isinstance(effect, ReturnExiledPermanentToOwnerTapped):
    effect_dict = {
        "kind": "return_exiled_permanent_to_owner_tapped",
        "exile_card_id": int(effect.exile_card_id),
    }
```

### 5.3 Phase 3B — `ExileAllGraveyards` + bridge arms + Desert-subtype audit

**Cost gate widen.** `_aa_is_phase1_sub_shape_a` removes the strict
`sacrifice_a_desert` decline arm:

```python
# Cost gate — Phase 3B: bare {T} OR {N}, {T} OR
#     ({N}, {T}, Sac:) OR ({N}, {T}, Sac-a-Desert:)
#     (generic-only mana, optional sacrifice_self or
#     sacrifice_a_desert).
if cost.sacrifice_a_desert and cost.sacrifice_self:
    return False   # both at once stays declined (no carrier has it)
# (Existing sacrifice_self decline removed in Phase 2a; the
# sacrifice_a_desert decline arm is removed here.)
```

**Critical contract preservation.** The widen is strictly additive on
the `sacrifice_a_desert` axis; every OTHER cost-bool field stays at
the Phase-2a contract (`sacrifice_another_*` still declines, etc.).

**Effect-class widen** (per §5.1) adds `ExileAllGraveyards`.

**Forward arm in `_python_aa_to_safe_dict`:**

```python
elif isinstance(effect, ExileAllGraveyards):
    effect_dict = {"kind": "exile_all_graveyards"}
```

**Reverse arm in `_ta_dict_to_python_effect`:**

```python
if kind == "exile_all_graveyards":
    from mtg_bot.effects.generic.exile import ExileAllGraveyards
    return ExileAllGraveyards()
```

**Desert subtype admission audit.** Scavenger Grounds is the only EoE
Carrier-AA card whose `printing.subtypes` is non-empty
(`("Desert",)`). The existing `_printing_is_bridge_simple_carrier_aa_land`
at `trajectory.py:8631` does NOT check `subtypes` — only `card_types`
(per the Phase 1.5a §9.5 verification). **Verify-first audit**: walk
every guard in `_printing_is_bridge_simple_carrier_aa_land` and
confirm the Scavenger Grounds printing passes each unchanged. Expected
outcome: it does — the only subtype-aware filter is the cost-side
Desert eligibility, which is the cost-pay side (Rust already wired).
Python admit does NOT need a positive subtype check.

**Rust-side cross-engine audit.** The Rust mirror's
`activate_ability_dict::sacrifice_a_desert` fan-out (`state_ops_legal.rs:3522`)
uses the lenient SELF-eligibility rule (the source IS eligible if it
has Desert subtype) — Scavenger Grounds itself IS Land — Desert, so
the source is a valid sacrifice target. Confirms parity with Python's
behavior at the cost-pay step.

### 5.4 Phase 3C — `BecomesCopyOfTargetLand` + bridge arms

**Effect-class widen** (per §5.1) adds `BecomesCopyOfTargetLand`.

**Forward arm in `_python_aa_to_safe_dict`:**

```python
elif isinstance(effect, BecomesCopyOfTargetLand):
    effect_dict = {"kind": "becomes_copy_of_target_land"}
```

**Reverse arm in `_ta_dict_to_python_effect`:**

```python
if kind == "becomes_copy_of_target_land":
    from mtg_bot.effects.generic.become_type import (
        BecomesCopyOfTargetLand,
    )
    return BecomesCopyOfTargetLand()
```

**GameObject snapshot bridge.** The Rust `original_printing_id:
Option<u32>` slot must round-trip in the per-object fingerprint and
snapshot. Python's `GameObject.original_printing: CardPrinting | None`
holds a full CardPrinting reference; Rust's slot holds a printing-
registry ID. The snapshot codec must map between the two. **One new
slot in the GameObject snapshot dict** + reverse-decoder via the
printing-registry lookup (Rust's snapshot can emit the id directly;
Python's reverse decoder resolves the registry).

**`_printing_is_bridge_simple_carrier_aa_land` — no change.** The
copy semantics are RESOLVE-time, not admit-time. The printing-level
admit predicate stays bit-identical (per Phase 2 §5.5).

### 5.5 `_filter_deck_to_bridge_supported` OR-chain — no change

Phase 3 widens WITHIN the Carrier-AA Land disjunct; the chain shape
is unchanged (per Phase 2 §5.6).

### 5.6 Phase-1.5a / Phase-2 C2 invariant pin updates

The Phase-2 no-silent-auto-grow walk asserts Mystifying Maze /
Scavenger Grounds / Thespian's Stage STAY DECLINED on Effect-class
teeth. Phase 3 INVERTS those clauses in-place (one per sub-phase):

* Phase 3A: `test_carrier_aa_no_silent_auto_grow_swarmyard_plus_deserted_temple_plus_petrified_field_plus_terrain_generator`
  → `..._plus_mystifying_maze` (admit set 4 → 5).
* Phase 3B: same pin extended to `..._plus_scavenger_grounds` (5 → 6).
* Phase 3C: same pin extended to `..._plus_thespians_stage` (6 → 7).

Plus per-sub-phase per-card admit-flip pin inversions (the Phase 2
inversion convention):

* Phase 3A:
  * `test_aa_is_phase1_sub_shape_a_declines_mystifying_maze_effect`
    → `test_aa_is_phase1_sub_shape_a_admits_mystifying_maze_effect`.
  * `test_printing_is_bridge_simple_carrier_aa_land_declines_live_mystifying_maze`
    → `test_..._admits_live_mystifying_maze`.
  * `test_filter_deck_to_bridge_supported_declines_mystifying_maze`
    → `test_..._admits_mystifying_maze`.
* Phase 3B: parallel inversions for `_scavenger_grounds`.
* Phase 3C: parallel inversions for `_thespians_stage`.

Plus the Phase 2 `_no_silent_auto_grow_admit_set_*` pin's expected-list
extension per sub-phase landing.

---

## 6. Test plan

### 6.1 Phase 3A substrate unit pins (Rust + Python)

1. **`parse_printing` round-trip** for a synthetic non-token CardDef
   carrying `activated_abilities=[{"cost":{"tap_self":True,"mana":
   {"generic":4}},"effect":{"kind":"exile_target_attacking_creature_until_end_step"}}]`
   → produces the expected `ActivatedAbility`.
2. **`_aa_is_phase1_sub_shape_a` admits Mystifying Maze's synthetic
   shape.** Synthetic `{4}, {T}` cost +
   `ExileTargetAttackingCreatureUntilEndStep` Effect — predicate
   returns True.
3. **`_python_aa_to_safe_dict` round-trips Mystifying Maze's synthetic
   shape byte-equal** through `_aa_dict_to_python_activated_ability`.
4. **`_python_aa_to_safe_dict` + reverse-arm round-trip of a
   `ReturnExiledPermanentToOwnerTapped` instance** through the
   delayed-trigger codec (the producer-side serializer + the snapshot
   reverse-decoder). Pin asserts the `exile_card_id` slot round-trips
   exactly.
5. **`Effect::ExileTargetAttackingCreatureUntilEndStep` parse + resolve
   arms** (Rust `#[test]`): given a state with an attacking opponent
   creature, resolve exiles the target and pushes a `DelayedTrigger`
   onto the Vec.
6. **`Effect::ReturnExiledPermanentToOwnerTapped` parse + resolve
   arms** (Rust `#[test]`): given a state with an exiled object and
   the delayed trigger firing, the object moves to its owner's
   battlefield tapped + ETB dispatched.
7. **`state_ops_steps.rs::run_delayed_end_step_triggers` pushes the
   Maze-spawned delayed trigger onto the stack** at the active
   player's end step (regression — verifies the WarpExileSelf-shape
   producer machinery generalizes to the new effect class).
8. **Combat-phase guard pin** (Python + Rust): outside combat,
   activating Maze is illegal (no attackers; 0-target fan-out).
9. **Pseudo-target legality re-check pin**: if the targeted attacker
   leaves the battlefield between activation and resolve, the
   ExileTargetAttackingCreatureUntilEndStep effect fizzles silently
   and NO `DelayedTrigger` is pushed (matches Python's CR-608.2b
   silent fizzle).

### 6.2 Phase 3B substrate unit pins (Rust + Python)

10. **`parse_printing` round-trip** for a synthetic non-token CardDef
    carrying `activated_abilities=[{"cost":{"tap_self":True,"mana":
    {"generic":2},"sacrifice_a_desert":True},"effect":{"kind":"exile_all_graveyards"}}]`
    → produces the expected `ActivatedAbility`.
11. **`_aa_is_phase1_sub_shape_a` admits Scavenger Grounds's synthetic
    shape.**
12. **`_aa_is_phase1_sub_shape_a` continues to decline `sacrifice_self
    AND sacrifice_a_desert` simultaneously, and every other cost-bool
    field.** Regression pin — Phase 3B widens ONLY the
    `sacrifice_a_desert` axis (with `sacrifice_self=False` required).
13. **`_python_aa_to_safe_dict` round-trips Scavenger Grounds's
    synthetic shape byte-equal.**
14. **`Effect::ExileAllGraveyards` parse + resolve arms** (Rust
    `#[test]`): given a state with 3 cards in player[0].graveyard
    and 2 in player[1].graveyard, resolve produces a state with both
    graveyards empty and 3+2=5 cards across the two exile zones (3
    in player[0].exile + 2 in player[1].exile).
15. **Desert subtype admission audit pin**: `_printing_is_bridge_simple_carrier_aa_land`
    admits the live Scavenger Grounds printing (subtypes=("Desert",)
    must not trip any guard).
16. **Rust Desert SELF-eligibility regression pin**: activating
    Scavenger Grounds itself satisfies the `sacrifice_a_desert` cost
    (the source is its own valid sacrifice target via the lenient
    SELF-eligibility rule at `state_ops_legal.rs:3522`).

### 6.3 Phase 3C substrate unit pins (Rust + Python)

17. **`parse_printing` round-trip** for a synthetic non-token CardDef
    carrying `activated_abilities=[{"cost":{"tap_self":True,"mana":
    {"generic":2}},"effect":{"kind":"becomes_copy_of_target_land"}}]`
    → produces the expected `ActivatedAbility`.
18. **`_aa_is_phase1_sub_shape_a` admits Thespian's Stage's synthetic
    shape.**
19. **`_python_aa_to_safe_dict` round-trips Thespian's Stage's
    synthetic shape byte-equal.**
20. **`Effect::BecomesCopyOfTargetLand` parse + resolve arms** (Rust
    `#[test]`): given a state with Thespian's Stage on the
    battlefield AND a Mountain on the battlefield, activate the
    copy effect → Stage's `printing_id` mutates to a new registry
    entry derived from Mountain's printing + Stage's pre-copy AAs;
    `original_printing_id = Some(stage_original)`.
21. **Re-copy retention pin** (Rust + Python): a second activation
    targeting Forest re-copies; the new printing carries
    Forest's AAs + Stage's ORIGINAL AAs (not the post-Mountain-copy
    accumulated AAs). Verifies `original_printing_id` is sticky
    across re-copies.
22. **Zone-change clears `original_printing_id`** (Rust + Python):
    if Thespian's Stage is sacrificed / destroyed / bounced, the
    object's `original_printing_id` is cleared to None on zone-
    change reset (per CR 400.7). If the same object ID re-enters
    the battlefield (unusual but possible — bounce + replay), the
    copy effect does NOT auto-restore.
23. **Mana-ability auto-wire pin**: after Thespian's Stage copies a
    Mountain, activating the copied Mountain's `{T}: Add {R}`
    mana ability succeeds — the legal-actions emit walks the
    mutated `printing.activated_abilities` and finds the mana
    ability.
24. **`effective_*` lookup audit pin**: `effective_subtypes`,
    `effective_card_types`, `effective_keywords` for the post-copy
    object return the COPIED Land's attributes (e.g. Mountain
    subtype after copying a Mountain).

### 6.4 Decline-set regression — the 26 → 23-card walk

25. **Live-printing parametrized walk** over the 26-card Phase-2-
    residue (the Phase 2 §2.1 26 cards minus the Phase 3 admits),
    checking exactly the cards admitted at each Phase 3 sub-phase
    boundary. After all 3 sub-phases: 7 admitted cards (Phase 1+2's
    4 + Phase 3's 3); 23 declined. Same shape as Phase 2's no-silent-
    auto-grow walk.

26. **Subsystem-attribution pin**: exactly 7 EoE printings pass
    `_printing_is_bridge_simple_carrier_aa_land` (Swarmyard + Deserted
    Temple + Petrified Field + Terrain Generator + Mystifying Maze +
    Scavenger Grounds + Thespian's Stage) — the Phase-3 positive set
    is exhaustive over the live EoE pool.

27. **Phase 4+ deferral assertions** — every multi-AA card + every
    rider-cluster card stays declined (Mirrorpool + Ghost Vacuum +
    Keys to the House + Haunted Screen + The Eternity Elevator +
    Equipment cluster + every Phase-N card in the residue).

### 6.5 Real-EoE per-card probes (one per sub-phase)

28. **`tests/test_mystifying_maze_parity.py`** — real-EoE per-card
    probe (inserted at the
    `# === PHASE5_PROBES_INSERT_ABOVE_THIS_LINE ===` sentinel via
    `MODULE_FILE` symlink, batch-13 EEEE-idiom). Asserts byte-equal
    mirror through:
    * baseline (Mystifying Maze in play untapped, no attacker on the
      battlefield — activation illegal; state unchanged after passing
      priority);
    * exile-attacker line (opponent attacks with a 2/2; activate Maze
      `{4}, {T}: Exile target attacking creature`; 2/2 moves to
      opponent's exile zone, Maze taps, mana pays, delayed trigger
      enqueued, both engines byte-equal);
    * return-at-end-step line (continue play to end step; the delayed
      trigger fires, 2/2 returns to opponent's battlefield tapped,
      ETB / landfall (n/a for creature) events dispatch byte-equal).

29. **`tests/test_scavenger_grounds_parity.py`** — real-EoE per-card
    probe. Asserts byte-equal mirror through:
    * baseline (Scavenger Grounds in play untapped, both graveyards
      empty — activation legal but resolve no-ops; state unchanged);
    * exile-all-graveyards line (both players have N cards in
      graveyard each; activate `{2}, {T}, Sac-self: Exile all
      graveyards`; Scavenger Grounds moves to controller's exile
      (per the sac cost), both graveyards empty, both exile zones
      grow by N, byte-equal end state).

30. **`tests/test_thespians_stage_parity.py`** — real-EoE per-card
    probe. Asserts byte-equal mirror through:
    * baseline (Thespian's Stage in play untapped, no other Land on
      battlefield — activation illegal; no legal target);
    * copy-Mountain line (Mountain on opponent's bf; activate
      `{2}, {T}: Becomes copy of target Land` targeting Mountain;
      Stage's printing_id mutates, original_printing_id snapshots,
      effective_subtypes now includes "Mountain", subsequent
      `{T}: Add {R}` mana-ability activation succeeds, both engines
      byte-equal);
    * re-copy-Forest line (after copy-Mountain, activate again
      targeting Forest; Stage's printing now carries Forest's AAs +
      Stage's original AAs, NOT Mountain's accumulated AAs);
    * Stage-leaves-clears-copy line (sacrifice Stage post-copy; the
      object moves to graveyard; `original_printing_id` clears to None
      on zone-change reset — observable via fingerprint byte-equality
      on the graveyard re-entry).

### 6.6 Pool-parity row delta

31. **`tests/test_measure_pool_parity.py` regen** confirms +3 cards in
    PROBED tier (Mystifying Maze + Scavenger Grounds + Thespian's
    Stage) and -3 from the BLOCKED-SG Carrier-AA row (26 → 23 cards
    remaining). The PROBED-tier increment lands one card per sub-
    phase landing cycle.

### 6.7 Pre-existing parity gate

32. **Full sanity gate** (`tests/test_parity_smoke.py +
    test_cross_engine_etb_triggers.py + test_trajectory_parity.py +
    test_trajectory.py + test_measure_pool_parity.py`) stays green.
    The Phase-1 + Phase-1.5a + Phase-2 pins continue to pass (no
    regression on Swarmyard / Deserted Temple / Petrified Field /
    Terrain Generator admits).

---

## 7. Estimated cycle count per sub-phase

### 7.1 Phase 3A (Mystifying Maze) — ~3 cycles

| Cycle | Owner | Deliverable |
|---:|---|---|
| 1 (3A-C1) | Rust agent | **Phase 3A Rust substrate:** new `Effect::ExileTargetAttackingCreatureUntilEndStep` + `Effect::ReturnExiledPermanentToOwnerTapped` variants + parse / resolve / to_pydict arms + delayed-trigger PRODUCER call inside the Maze resolve arm + new attacking-creature target fan-out in `state_ops_legal.rs::activate_ability_dict` + the 5 Rust unit pins (§6.1 #5-9). Sole Rust slice this round. |
| 2 (3A-C2) | Python/bridge agent | **Phase 3A admit + Mystifying Maze FLIP:** Effect-class widen + 4 bridge arms (`_python_aa_to_safe_dict` x2 + `_ta_dict_to_python_effect` x2) + 4 Python unit pins (§6.1 #1-4) + Phase-2 no-silent-auto-grow walk inversion for Mystifying Maze + pool-parity regen. |
| 3 (3A-C3) | Python agent | **Phase 3A real-EoE probe** (§6.5 #28) + SL entry. |

### 7.2 Phase 3B (Scavenger Grounds) — ~3 cycles

| Cycle | Owner | Deliverable |
|---:|---|---|
| 1 (3B-C1) | Rust agent | **Phase 3B Rust substrate:** new `Effect::ExileAllGraveyards` variant + parse / resolve / to_pydict arms + the 2 Rust unit pins (§6.2 #14, #16). Sole Rust slice this round. |
| 2 (3B-C2) | Python/bridge agent | **Phase 3B admit + Scavenger Grounds FLIP:** Cost-gate widen (`_aa_is_phase1_sub_shape_a` removes `sacrifice_a_desert` decline) + Effect-class widen + 2 bridge arms + 4 Python unit pins (§6.2 #10-13) + Desert subtype audit (§6.2 #15) + Phase-2 walk inversion for Scavenger Grounds + pool-parity regen. |
| 3 (3B-C3) | Python agent | **Phase 3B real-EoE probe** (§6.5 #29) + SL entry. |

### 7.3 Phase 3C (Thespian's Stage) — ~5 cycles

| Cycle | Owner | Deliverable |
|---:|---|---|
| 1 (3C-C1) | Rust agent | **Phase 3C Rust state field:** new `GameObject.original_printing_id: Option<u32>` slot + per-zone-change reset hookup at every bf-leave site + fingerprint serializer arm + clone path + GameObject snapshot bridge to Python. No Effect changes this cycle. Sole Rust slice. |
| 2 (3C-C2) | Rust agent | **Phase 3C Rust Effect port:** new `Effect::BecomesCopyOfTargetLand` variant + parse / resolve / to_pydict arms + Land-target fan-out in `state_ops_legal.rs::activate_ability_dict` + re-copy snapshot logic + 4 Rust unit pins (§6.3 #20-23). Sole Rust slice. |
| 3 (3C-C3) | Python/bridge agent | **Phase 3C admit + Thespian's Stage FLIP:** Effect-class widen + 2 bridge arms + 3 Python unit pins (§6.3 #17-19) + `original_printing_id` GameObject snapshot codec arm + `effective_*` audit pin (§6.3 #24) + Phase-2 walk inversion for Thespian's Stage + pool-parity regen. |
| 4 (3C-C4) | Python agent | **Phase 3C real-EoE probe** (§6.5 #30) — first 3 baseline + copy-Mountain + re-copy-Forest lines. |
| 5 (3C-C5) | Python agent | **Phase 3C real-EoE probe — Stage-leaves-clears-copy line** (§6.5 #30 fourth line) + SL entry + decline-set walk close-out (§6.4 #25-27). |

**Estimated total: ~11 cycles** (3 + 3 + 5).

**Cost drivers:**
* Phase 3C-C1 (the new `GameObject` field + zone-change reset hookup
  audit + fingerprint arm) is the largest substrate slice — the
  `original_printing_id` field touches every bf-leave call site, the
  Rust clone path, the fingerprint serializer, and the Python
  snapshot bridge. The closest precedent is the Phase 1 C1
  `regeneration_shield` substrate (per `state.rs:147-149`), which was
  a single C1 cycle. 3C-C1 is comparable in shape but slightly
  heavier because `Option<u32>` carries a non-trivial Default and
  zone-change-reset audit semantics.
* Phase 3C-C2 (the Effect port + re-copy snapshot logic) is the
  second-largest. The `effective_*` audit (§4.3) lands here to
  confirm every lookup reads through the printing registry.
* Phase 3A-C1 (the delayed-trigger PRODUCER) is moderate — the
  WarpExileSelf precedent gives the producer-call shape directly;
  the new bit is the attacking-creature target fan-out and the
  return-from-exile-tapped Effect arm (which itself is a small
  zone-move primitive).
* Phase 3B-C1 is small — single Effect port, no targeting, no new
  state field.

---

## 8. SEARCH_LIMITATIONS.md entries (one per sub-phase)

* **Phase 3A SL entry** — "Phase 3A ports `Effect::ExileTarget
  AttackingCreatureUntilEndStep` + `Effect::ReturnExiledPermanentTo
  OwnerTapped`; delayed-trigger producer routes through
  `state.delayed_triggers` (WarpExileSelf precedent); return-to-bf
  is tapped + dispatches `Event::EntersBattlefield`; no replacement-
  effect interactions on the exile-to-bf return zone-move are
  modeled (none of the EoE printings carry replacements on this
  transition)."

* **Phase 3B SL entry** — "Phase 3B widens the cost gate to admit
  `sacrifice_a_desert` (no `sacrifice_self` + `sacrifice_a_desert`
  simultaneously) and ports `Effect::ExileAllGraveyards` at the
  minimum no-target mass-zone-move semantics; the Desert subtype
  admission walk on the Python admit predicate is positive-verified
  (Scavenger Grounds passes every guard at
  `_printing_is_bridge_simple_carrier_aa_land`; the predicate does
  not check `subtypes`). The Rust Desert SELF-eligibility rule from
  the Lander precedent applies — Scavenger Grounds itself is a valid
  sacrifice target for its own activation."

* **Phase 3C SL entry** — "Phase 3C ports the CR-613 layer-1 object-
  copy substrate for `Effect::BecomesCopyOfTargetLand`; new
  `GameObject.original_printing_id: Option<u32>` slot (Python's
  `original_printing: CardPrinting | None` mirror); resolve-time
  printing-registry push for the copy; per-zone-change reset
  clears `original_printing_id` (CR 400.7); re-copy retention via
  the snapshot slot. NOT modeled in this slice: other copy-effect
  shapes (creature-copy, planeswalker-copy, spell-copy, token-
  creature-copy via `CreateTokenCopyOfTargetCreatureYouControl`).
  Mirrorpool's two copy AAs sit in DIFFERENT copy-machinery families
  (CR-707.2 spell-copy + CR-707.5 token-creature-copy) and are
  Phase 4+ deferrals."

---

## 9. Rejected alternatives

### 9.1 Bundle all three sub-phases into one Phase 3 landing

**Rejected — three orthogonal Effect families.** Phase 3A's
delayed-trigger substrate, Phase 3B's mass-graveyard-exile substrate,
and Phase 3C's CR-613 layer-1 copy substrate share NO machinery.
Folding them into one cycle adds three Rust slices in one .pyd-
rebuild window, triples the cross-engine surface verified at landing
time, and conflates three independent admit-gate inversions. Per
Phase 2 §9.7, separate Rust cycles preserve the `.pyd` race rule
and audit clarity.

### 9.2 Bundle Phase 3A + 3B (both have an "exile" theme)

**Rejected — surface overlap is cosmetic, not structural.**
`ExileTargetAttackingCreatureUntilEndStep` produces a delayed trigger
that touches the return-from-exile-tapped primitive. `ExileAllGraveyards`
is a zero-target mass-zone-move with no delayed-trigger interaction.
The two share NO Rust state field, NO Effect-resolve helper, and NO
target fan-out arm. Bundling them adds zero leverage and conflates
the audit surface.

### 9.3 Bundle Phase 3A + 3C (both have a "target permanent" theme)

**Rejected — different target semantics.** Phase 3A's target is an
attacking creature an opponent controls; the legal-action emission
reads `state.attackers`. Phase 3C's target is any battlefield Land
(either player's). Different target predicates, different fan-out
arms in `state_ops_legal.rs`. The "target permanent" surface is
ambient — every Effect targeting a battlefield permanent shares
this — and is not a substrate-bundling axis.

### 9.4 Bundle Thespian's Stage (Phase 3C) with Mirrorpool (Phase 4)

**Rejected — different copy-machinery families.** Per §2.4,
Thespian's Stage's `BecomesCopyOfTargetLand` is CR-613 layer-1
object-copy; Mirrorpool AA[0]'s `CopyTargetInstantOrSorceryYouControl`
is CR-707.2 spell-copy; Mirrorpool AA[1]'s
`CreateTokenCopyOfTargetCreatureYouControl` is CR-707.5 token-
creature-copy. The three families do NOT share state slots or
resolve helpers. Mirrorpool also requires the multi-AA admit
predicate (Phase 4). Co-bundling Thespian's Stage with Mirrorpool
forces Phase 3C to wait on the multi-AA substrate, which is the
WRONG dependency order — Thespian's Stage is single-AA and
should land independently.

Phase 3C DOES leave a reusable primitive — the "push a new
CardPrinting derived from a battlefield permanent's printing into
the registry" step — that Mirrorpool AA[1]'s `CreateTokenCopyOf
TargetCreatureYouControl` Effect port can reuse in Phase 4. The
primitive composes; the substrate does NOT bundle.

### 9.5 Drop Phase 3C from Phase 3 and pursue Phase 3A + 3B only

**Rejected — Phase 3 is the natural cluster boundary for the three
single-AA Land carriers.** The Phase 2 §0 §"Phase 3+ deferral" row
named exactly Mystifying Maze + Thespian's Stage + Scavenger Grounds
as Phase 3 candidates; dropping Thespian's Stage from Phase 3
defers it to Phase 5+ behind Phase 4's multi-AA, which is the wrong
order. Phase 3C is heavy but tractable as a 5-cycle independent
sub-phase; it ships in its own timeline alongside Phase 3A + 3B.

### 9.6 Bundle Phase 3A's `ReturnExiledPermanentToOwnerTapped` arm with the existing `Effect::ExileTargetCreatureUntilSourceLeaves`

**Rejected — different return semantics.**
`ExileTargetCreatureUntilSourceLeaves` returns the exiled permanent
ON the source's bf-leave (using the `exiled_with_source` slot at
`state.rs:122`). Maze's delayed trigger fires UNCONDITIONALLY on
EoT, regardless of whether Maze still exists. The two semantics
cannot share the `exiled_with_source` slot — the `ReturnExiledPermanent
ToOwnerTapped` arm reads the exile_card_id from the DelayedTrigger
payload, not from the exiled object's slot.

### 9.7 Pursue a generic "copy-effect substrate" (cover both Thespian's Stage and Mirrorpool's two copy AAs) in one campaign

**Rejected — three different CR sections; one design doc would
overstuff.** CR-613 layer-1 (Phase 3C), CR-707.2 spell-copy (Phase 4),
CR-707.5 token-creature-copy (Phase 4) each have their own state
surface and resolve semantics. A single "copy-effect campaign" doc
would mix layer-1 / spell-copy / token-copy in one design at the
cost of clarity. The Phase 2 / Phase 3 / Phase 4 sequencing
strategy ports each family in its own substrate doc as the
respective card carrier admits land.

### 9.8 Skip Phase 3 and pursue Phase 4 (multi-AA) directly

**Rejected — multi-AA substrate is broader.** Phase 4 covers 5+
multi-AA Carrier-AA cards across multiple rider clusters (sorcery-
speed, activate-only-once, tier-threshold, pay_life, station_
threshold), each of which needs its own per-rider widen. Pursuing
Phase 4 before Phase 3 leaves three CLEAN single-AA carriers
declined for no machinery reason. Phase 3 closes those three first
because each is a tractable independent sub-phase; Phase 4's
multi-AA substrate widens AFTER.

---

## 10. Acceptance / sign-off (per sub-phase)

### 10.1 Phase 3A acceptance

1. The Phase 3A Rust substrate (§4.1) lands; the `.pyd` rebuilds clean.
2. The Phase 3A admit + Mystifying Maze FLIP (§5.1, §5.2) lands; the
   9 Phase-3A unit pins (§6.1 #1-9) all pass.
3. The Phase 3A Mystifying Maze real-EoE probe (§6.5 #28) passes
   byte-equal through baseline + exile-attacker + return-at-end-step
   lines.
4. Pool-parity regen lands +1 card in PROBED tier; BLOCKED-SG
   Carrier-AA shrinks 26 → 25.
5. The amended Phase 2 SL entry + the new Phase 3A SL entry land.
6. Full parity gate stays green (32/32).

### 10.2 Phase 3B acceptance

1. The Phase 3B Rust substrate (§4.2) lands; the `.pyd` rebuilds clean.
2. The Phase 3B admit + Scavenger Grounds FLIP (§5.1, §5.3) lands;
   the 7 Phase-3B unit pins (§6.2 #10-16) all pass.
3. The Phase 3B Scavenger Grounds real-EoE probe (§6.5 #29) passes
   byte-equal.
4. Pool-parity regen lands +1 card in PROBED tier; BLOCKED-SG
   Carrier-AA shrinks 25 → 24.
5. The new Phase 3B SL entry lands.
6. Full parity gate stays green.

### 10.3 Phase 3C acceptance

1. The Phase 3C Rust state field (§4.3 C1) lands; the `.pyd` rebuilds
   clean; the zone-change-reset audit passes (every bf-leave site
   clears `original_printing_id`).
2. The Phase 3C Rust Effect port (§4.3 C2) lands; the `.pyd` rebuilds.
3. The Phase 3C admit + Thespian's Stage FLIP (§5.1, §5.4) lands; the
   8 Phase-3C unit pins (§6.3 #17-24) all pass.
4. The Phase 3C Thespian's Stage real-EoE probe (§6.5 #30) passes
   byte-equal through baseline + copy-Mountain + re-copy-Forest +
   Stage-leaves-clears-copy lines.
5. Pool-parity regen lands +1 card in PROBED tier; BLOCKED-SG
   Carrier-AA shrinks 24 → 23.
6. The new Phase 3C SL entry lands.
7. The 26-card decline-set walk (§6.4 #25-27) confirms exactly the
   7-card admit set (Phase 1+2's 4 + Phase 3's 3); exhaustive over
   the live EoE pool.
8. Full parity gate stays green.

---

## 11. Cross-references

* `docs/CARRIER_AA_SUBSTRATE_PHASE_1_DESIGN.md` — parent campaign-
  shape doc + §10.3 sibling-swap clause + §3 out-of-scope matrix.
* `docs/CARRIER_AA_SUBSTRATE_PHASE_1_5_DESIGN.md` — Phase 1.5a cost-
  gate widen + §9.5 copy-effect deferral framing.
* `docs/CARRIER_AA_SUBSTRATE_PHASE_2_DESIGN.md` — Phase 2 §"Phase 3+
  deferral" row (Mystifying Maze + Thespian's Stage + Scavenger
  Grounds named); §3.1 `sacrifice_a_desert` deferral; §4.4 cost-side
  Rust audit (the sacrifice_a_desert plumbing confirmation).
* `src/mtg_bot/parity/trajectory.py:8420-8667` —
  `_aa_is_phase1_sub_shape_a` + `_printing_is_bridge_simple_carrier_aa_land`
  + `_carrier_aa_land_card_def` (the Phase-3 widen sites).
* `src/mtg_bot/parity/trajectory.py:8465` —
  `_carrier_aa_phase_1_effect_classes` (the Effect-set admit gate
  widened in §5.1).
* `src/mtg_bot/parity/cross_engine.py:14031-14166` —
  `_python_aa_to_safe_dict` (the AA serializer widened in §5.2,
  §5.3, §5.4 per sub-phase).
* `src/mtg_bot/parity/cross_engine.py:12360-12410` —
  `_ta_dict_to_python_effect` (the reverse-arm widened per
  sub-phase).
* `rust/src/cards.rs:8585-8615` — `DelayedTrigger` struct (Phase 3A
  reuses unchanged).
* `rust/src/state.rs:2335` — `state.delayed_triggers: Vec<DelayedTrigger>`
  (Phase 3A reuses unchanged).
* `rust/src/state_ops_steps.rs:434-540` — `run_delayed_end_step_triggers`
  (Phase 3A reuses unchanged; new effect kind handled via the
  `push_triggered_ability` arm).
* `rust/src/state.rs:2252` — `state.attackers: Vec<u32>` (Phase 3A
  reuses unchanged).
* `rust/src/cards.rs:9856` — `ActivationCost.sacrifice_a_desert`
  (Phase 3B reuses; Python admit gate adds the widen).
* `rust/src/state_ops_legal.rs:3522` — `sacrifice_a_desert` target
  fan-out + lenient SELF-eligibility (Phase 3B reuses unchanged).
* `rust/src/state_ops_actions.rs:1179` — `sacrifice_a_desert` cost-
  pay commit (Phase 3B reuses unchanged).
* `rust/src/state.rs:35-150` — `GameObject` struct (Phase 3C adds
  the new `original_printing_id` slot here).
* `src/mtg_bot/effects/generic/exile.py:180-255` — Python's
  `ExileTargetAttackingCreatureUntilEndStep` (Phase 3A mirror
  reference).
* `src/mtg_bot/effects/generic/exile.py:661-683` — Python's
  `ExileAllGraveyards` (Phase 3B mirror reference).
* `src/mtg_bot/effects/generic/become_type.py:246-312` — Python's
  `BecomesCopyOfTargetLand` (Phase 3C mirror reference).
* `src/mtg_bot/turn.py:773-849` — Python's
  `run_delayed_end_step_triggers` (Phase 3A end-step dispatch
  byte-equality reference).
* `tests/test_carrier_aa_phase_1_substrate_cycle_2.py` + Phase 1.5a /
  Phase 2 no-silent-auto-grow walks — pins inverted per sub-phase.

---

## 12. Sequencing recommendation

**Recommended sequencing for Phase 3 landing:**

1. **Ship Phase 3A (Mystifying Maze) first** — ~3 cycles. The
   delayed-trigger PRODUCER is the highest-leverage primitive of the
   three sub-phases; landing it first lets every future delayed-
   trigger Effect (Phase N producers) reuse the producer shape.
2. **Sanity-gate confirmation** at 3A close — 32/32 measure-pool-
   parity baseline with +1 card in PROBED (5 admitted).
3. **Ship Phase 3B (Scavenger Grounds) second** — ~3 cycles. Single
   small Effect port + small Python admit widen.
4. **Sanity-gate confirmation** at 3B close — +1 (6 admitted).
5. **Ship Phase 3C (Thespian's Stage) last** — ~5 cycles. The CR-613
   layer-1 copy substrate is the heaviest of the three; leaving it
   last lets the lighter sub-phases land first as substrate-
   stability validation.
6. **Final sanity-gate confirmation** at 3C close — +1 (7 admitted);
   BLOCKED-SG Carrier-AA shrinks 26 → 23.

**Next Carrier-AA campaign milestones after Phase 3:**

* **Phase 4 (multi-AA admit predicate)** — covers Mirrorpool + Ghost
  Vacuum + Keys to the House + All-Fates Scroll + Haunted Screen +
  The Eternity Elevator. Each is multi-AA + various rider clusters.
  Phase 4 lands the multi-AA admit gate widen + per-card Effect
  ports for the AAs that are still bridge-uncovered (CR-707.2
  spell-copy, CR-707.5 token-creature-copy, LockOrUnlockDoor,
  SearchLibraryForCard variants, ExileTargetCardFromGraveyard,
  PhaseOutEquippedCreature, etc.). ~10-15 cycles across multiple
  sub-phases.
* **Phase N (rider clusters)** — mana-ability / sorcery-speed /
  Equipment / BecomeLand / Creature-carrier / X-pip / colored-mana /
  activate-only-once / tier-threshold / room-half. Each is its own
  rider substrate. Most carriers in the 23-card post-Phase-3 residue
  sit in this Phase-N tail.

---

## 13. Verify-first walk reproduction

The §2.1 3-card walk was verified by a one-off walker (not committed —
`_scout_phase3.py` during the design lane) over the live
`OracleParserCardSource` at HEAD `03fdc3e6`, enumerating each card's
`(card_types, subtypes, n_aa, n_ta, n_sa, keywords)` and AA[0]'s
`(cost-bool fields, mana, Effect class)`. The §2.2 Python Effect-
class signatures were verified by reading the live module sources
(`exile.py:180-255`, `exile.py:661-683`, `become_type.py:246-312`).
The §2.3 Rust substrate state was verified via `grep` against
`rust/src/state.rs`, `cards.rs`, `state_ops_steps.rs`,
`state_ops_legal.rs`, `state_ops_actions.rs`, and
`state_ops_resolve.rs`.

```python
from mtg_bot.cards.parser.source import OracleParserCardSource
ps = OracleParserCardSource().get_printings()
phase3 = ["Mystifying Maze", "Scavenger Grounds", "Thespian's Stage"]
for name in phase3:
    p = ps[name]
    aa = p.activated_abilities[0]
    # walk: (card_types, subtypes, n_aa, n_ta, n_sa, keywords,
    #   cost.mana, every cost-bool field, effect class)
```

The full walker output was logged 2026-05-25 during this design
lane; the §2.1 + §2.2 + §2.3 tables are the canonical summary. To
regenerate at a future HEAD, re-run the walk via the Phase 2 §13
regeneration script seeded with the 3-card list.
