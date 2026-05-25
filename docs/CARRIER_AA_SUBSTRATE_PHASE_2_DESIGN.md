# Carrier-AA substrate — Phase 2 design

**Status:** DESIGN — docs-only scoping for the Phase 2 mixed cost-
shape + Effect-class widen. No code change lands with this doc.

**Author:** Carrier-AA Phase 2 design lane, Worker A
(`feature/carrier-aa-substrate-phase-2-design-p1`), 2026-05-25.

**Predecessors:**
* Phase 1 closed at C2 (`0cc08732`) — Rust substrate
  (`CardDef.activated_abilities` + `Effect::RegenerateTargetCreature`
  + `Effect::UntapTargetLand` + bridge codec) + Python admit gate at
  bare `{T}` cost shape. Swarmyard FLIP (DECLINED → ADMITTED).
* Phase 1 C3 (`da761ad1`) — SBA-time `regeneration_shield` consume +
  Swarmyard real-EoE byte-equal probe (`covered_by_construction` →
  PROBED).
* Phase 1.5a (`e0707d88`) — Python-only cost-gate widen from STRICT
  bare `{T}` to bare `{T}` OR `{N}, {T}` (generic-only mana). Deserted
  Temple FLIP at zero Rust cost (`UntapTargetLand` already in the
  Phase-1 admit set + bridge already routes generic mana). Phase-1.5a
  C2 pins inverted in-place + real-EoE probe.

**Companion docs:** `docs/CARRIER_AA_SUBSTRATE_PHASE_1_DESIGN.md`
(parent campaign-shape doc — §2.1 30-card walk, §3 out-of-scope
matrix, §10.3 sibling-swap clause); `docs/CARRIER_AA_SUBSTRATE_PHASE_1_5_DESIGN.md`
(Phase 1.5a cost-gate widen). This Phase 2 doc inherits their
definitions; cross-references below cite by section.

---

## 0. Executive summary

Phase 2 is a **two-sub-cycle landing** of the Carrier-AA substrate
that widens the admit gate on **both** axes the Phase 1.5 sibling-
swap analysis identified (Phase 1.5 §10.3):

* **Phase 2a — `{T}, Sac:` cost-shape widen + `ReturnTargetLandFromGraveyardToHand`
  Effect port.** Admits **Petrified Field** (`{T}, Sac: Return target
  land card from your graveyard to your hand`) — a Land carrier with
  no riders, single AA, no triggered/static abilities, the cleanest
  `{T}, Sac:` carrier in the 28-card row.
* **Phase 2b — `PutBasicLandFromHandOntoBattlefieldTapped` Effect
  port** (under the existing Phase 1.5 cost gate). Admits **Terrain
  Generator** (`{2}, {T}: You may put a basic land card from your hand
  onto the battlefield tapped`) — sibling-swap target from Phase 1.5
  §10.3, cost `{2}, {T}` already in the Phase-1.5 admit set, only
  needs the Effect port.

**Phase 2 admit delta:** **+2 cards** (Petrified Field + Terrain
Generator). Both honestly DECLINE at the Phase-1.5a HEAD; both admit
post-Phase-2.

**Cycle estimate:** **3-4 cycles total** (1 Rust substrate cycle + 1
admit/probe cycle per card + 1 cycle of cost-gate widen + pin
inversions, optionally split). Mirrors Phase 1's 4-cycle landing
(C1 Rust / C2 Python+probe-1 / C3 probe-2 / C4 pool-parity regen).

**Out-of-scope (Phase 3+):**
* **Mystifying Maze** (`{4}, {T}: ExileTargetAttackingCreatureUntilEndStep`)
  — Effect needs **delayed-trigger / EoT-return substrate** (the
  "until end of step, return to battlefield" rider is its own
  multi-card substrate; Phase 3+ candidate).
* **Thespian's Stage** (`{2}, {T}: BecomesCopyOfTargetLand`) — needs
  **copy-effect substrate** (CR-613 layer-1; multi-card payoff with
  Mirrorpool's `CopyTargetInstantOrSorceryYouControl`; explicitly
  deferred per Phase 1.5 §9.5).
* **Scavenger Grounds** (`{2}, {T}, Sac-a-Desert: ExileAllGraveyards`)
  — needs `sacrifice_a_desert` cost shape + `Land — Desert` subtype
  + `ExileAllGraveyards` Effect port (Phase 3 — three substrates in
  one card; the `sacrifice_a_desert` axis is small but the Effect
  port surface is moderate).
* **Multi-AA carriers** (10 cards — Mirrorpool, Ghost Vacuum, Keys to
  the House, All-Fates Scroll, Haunted Screen, etc.) — Phase 4+
  multi-AA admit predicate widen.
* **Sorcery-speed, mana-ability, tier-threshold, activate-only-once,
  triggered-ability-co-gated, BecomeLand-rider, Creature-carrier,
  Equipment-carrier shapes** — Phase N (each is its own substrate per
  Phase 1 §3).

**Substrate-leverage:** Phase 2 lands the **first non-`{T}`-only cost
shape** (`{T}, Sac:` — `sacrifice_self=True` on the cost) and the
**first Carrier-AA-driven Land-search Effect** (`PutBasicLandFromHandOntoBattlefieldTapped`),
each a structural primitive every later Phase reuses. The `{T}, Sac:`
cost shape compositionally unlocks the path to Mirrorpool / Ghost
Vacuum / Keys to the House / All-Fates Scroll AA[1] (each multi-AA
or sorcery-speed-gated — Phase 4+) — Phase 2 ports the cost gate so
each future card needs ONLY its Effect port + the rider widen, not
the cost gate.

---

## 1. Background — Phase 1 + 1.5 closure and the 28-card residue

Phase 1 + 1.5 shipped the Carrier-AA admit substrate at the narrowest
sub-shape A (single-AA, no-triggered/no-static, no-rider non-token
Land carrier with cost `{T}` OR `{N}, {T}` and Effect in the admit
set `{RegenerateTargetCreature, UntapTargetLand}`). Two cards passed:
**Swarmyard** (Phase 1 C2 `0cc08732`) and **Deserted Temple** (Phase
1.5a `e0707d88`). Both have real-EoE byte-equal probes (`tests/test_swarmyard_parity.py`
+ `tests/test_deserted_temple_parity.py`).

The Phase 1.5a admit gate at `trajectory.py::_aa_is_phase1_sub_shape_a:8479`
declines every other card in the 30-card BLOCKED-SG Carrier-AA row
(verified by the Phase 1.5a no-silent-auto-grow walk in the same C2
test module). The 28-card residue breaks into Phase 2 candidates +
Phase 3+ deferrals via the verify-first walk below.

---

## 2. Verify-first walk — the 28-card residue at HEAD `e0707d88`

The walk script (a one-off scout `_scout_phase2.py`, not committed —
the design lane's verify-first discipline) enumerates each remaining
card's `(card_types, subtypes, n_aa, n_ta, n_sa, keywords,
station_threshold)` and every AA's `(cost.mana, cost-bool fields,
extras, AA-riders, effect-class)`. Reproducible at a future HEAD via
the Phase 1 §13 regeneration script seeded with the residue list.

### 2.1 Per-card categorization (sorted by AA-cost shape)

| # | Card | Type | n_aa | AA[0] cost | AA[0] Effect | Phase 2 status |
|---:|---|---|---:|---|---|---|
| 1 | **Petrified Field** | Land | 1 | `{T}, Sac:` | `ReturnTargetLandFromGraveyardToHand` | **Phase 2a admit** (cost-shape widen + Effect port) |
| 2 | **Terrain Generator** | Land | 1 | `{2}, {T}` | `PutBasicLandFromHandOntoBattlefieldTapped` | **Phase 2b admit** (Effect port only — cost already admitted) |
| 3 | Mystifying Maze | Land | 1 | `{4}, {T}` | `ExileTargetAttackingCreatureUntilEndStep` | Phase 3+ (EoT-return delayed-trigger substrate) |
| 4 | Thespian's Stage | Land | 1 | `{2}, {T}` | `BecomesCopyOfTargetLand` | Phase 3+ (copy-effect substrate; bundle with Mirrorpool AA[0]) |
| 5 | Scavenger Grounds | Land — Desert | 1 | `{2}, {T}, Sac-a-Desert:` | `ExileAllGraveyards` | Phase 3 (sacrifice_a_desert cost + Land—Desert subtype + Effect port) |
| 6 | Nesting Grounds | Land | 1 | `{1}, {T}` sorcery-speed | `MovePlusOneCounterBetweenPermanentsYouControl` | Phase N (sorcery_speed rider) |
| 7 | Contested War Zone | Land | 1 | `{1}, {T}` | `PumpCreaturesYouControlUntilEOT` | Phase N (TA=1 nonsafe trigger — `ChangeControllerToCombatDamageSource`) |
| 8 | Blast Zone | Land | 2 | `{T}` x_pips=2 | `PutChargeCountersOnSelf` | Phase N (X-pip cost + TA=1 + multi-AA) |
| 9 | Lavaclaw Reaches | Land | 1 | `{1}{B}{R}` (no tap) | `BecomeLandCreatureUEOT` | Phase N (BecomeLand-rider; colored cost + manland substrate) |
| 10 | Wandering Fumarole | Land | 1 | `{2}{R}{U}` (no tap) | `BecomeLandCreatureUEOT` | Phase N (BecomeLand-rider; same as Lavaclaw Reaches) |
| 11 | All-Fates Scroll | Artifact | 2 | `{T}` mana-ability | `AddManaToPool` | Phase N (mana-ability AA[0] + multi-AA) |
| 12 | Ancient Tomb | Land | 1 | `{T}` mana-ability | `DealDamageToControllerAndAddMana` | Phase N (mana-ability AA + Effect-port surface) |
| 13 | Atomic Microsizer | Artifact — Equipment | 1 | `{2}` (no tap) sorcery-speed | `EquipToTargetCreatureYouControl` | Phase N (sorcery_speed + Equipment + TA=1) |
| 14 | Auxiliary Boosters | Artifact — Equipment | 1 | `{3}` (no tap) sorcery-speed | `EquipToTargetCreatureYouControl` | Phase N (same as Atomic Microsizer) |
| 15 | Baseball Bat | Artifact — Equipment | 1 | `{3}` (no tap) sorcery-speed | `EquipToTargetCreatureYouControl` | Phase N (same; TA=2) |
| 16 | Saw | Artifact — Equipment | 1 | `{2}` (no tap) sorcery-speed | `EquipToTargetCreatureYouControl` | Phase N (same; TA=1) |
| 17 | Ghost Vacuum | Artifact | 2 | `{T}` / `{6}, {T}, Sac:` sorcery | `ExileTargetCardFromGraveyard` / `PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl` | Phase N (multi-AA + sorcery_speed + Effect ports) |
| 18 | Grove of the Burnwillows | Land | 2 | `{T}` mana-ability | `AddManaToPool` / `Sequence` | Phase N (mana-ability + multi-AA + Sequence Effect) |
| 19 | Haunted Screen | Artifact | 3 | `{T}` mana-ability ×2 + `{7}` activate-only-once | `AddNManaOfChosenColor` ×2 / `Sequence` | Phase N (mana-ability + activate_only_once + multi-AA + pay_life=1) |
| 20 | Keys to the House | Artifact | 2 | `{1}, {T}, Sac:` / `{3}, {T}, Sac:` sorcery | `SearchLibraryForCard` / `LockOrUnlockDoorOfTargetRoomYouControl` | Phase 4 (`{T}, Sac:` cost gate from Phase 2 unlocks AA[0] cost-shape; needs multi-AA + Search/Door Effect ports) |
| 21 | Lotus Field | Land — `hexproof` | 1 | `{T}` mana-ability | `AddNManaOfChosenColor` | Phase N (mana-ability + keyword + TA=1 ETB sacrifice) |
| 22 | Meteor Crater | Land | 1 | `{T}` mana-ability | `AddOneManaOfChosenPermanentColor` | Phase N (mana-ability + state-derived chosen-color) |
| 23 | Mirrorpool | Land | 2 | `{3}, {T}, Sac:` / `{5}, {T}, Sac:` | `CopyTargetInstantOrSorceryYouControl` / `CreateTokenCopyOfTargetCreatureYouControl` | Phase 4 (`{T}, Sac:` cost gate from Phase 2 unlocks; needs multi-AA + copy-effect substrate) |
| 24 | Pinnacle Starcage | Artifact | 1 | `{6}{W}{W}` (no tap) | `Sequence` | Phase N (colored cost + Sequence Effect + TA=1) |
| 25 | Reflecting Pool | Land | 1 | `{T}` mana-ability | `AddOneManaFromControlledLandsProductions` | Phase N (mana-ability + state-derived productions) |
| 26 | Robe of Stars | Artifact — Equipment | 2 | `{1}{W}` (no tap) / `{1}` sorcery | `PhaseOutEquippedCreature` / `EquipToTargetCreatureYouControl` | Phase N (Equipment + multi-AA + colored cost + phase-out Effect) |
| 27 | Sliver Overlord | Creature | 2 | `{3}` (no tap) | `SearchLibraryForCard` / `GainControlOfTargetSliverPermanently` | Phase N (Creature carrier + multi-AA + Effect ports) |
| 28 | The Eternity Elevator | Artifact — Spacecraft | 2 | `{T}` mana-ability + tier_threshold=20 | `AddManaToPool` / `AddChargeCounterManaOfChosenColor` | Phase N (Spacecraft + mana-ability + multi-AA + tier_threshold) |

### 2.2 Aggregate sub-shape statistics (28-card residue)

* **AA[0] cost-shape buckets:**
  * `{T}` bare or `{N}, {T}` (already in Phase 1.5 cost gate, declined on other axes): 11 cards (8 mana-ability; 3 with TA/rider).
  * `{N}, {T}, Sac:` shape (`sacrifice_self=True`): **3 cards** — Petrified Field (single-AA clean), Mirrorpool (multi-AA), Keys to the House (multi-AA).
  * `{N}, {T}, Sac-a-Desert:` (`sacrifice_a_desert=True`): **1 card** — Scavenger Grounds.
  * `{N}` no-tap-self (Equipment / sorcery / colored): 5 cards (Equipment cluster + Pinnacle Starcage + Sliver Overlord).
  * `{N}{C}{C}` colored no-tap-self (BecomeLand-rider): 2 cards (Lavaclaw / Wandering Fumarole).
  * `{T}` X-pips: 1 card (Blast Zone AA[0]).
  * Multi-AA cost mixing (one AA mana-ability + one AA non-mana-ability): 3 cards (All-Fates Scroll, Haunted Screen, The Eternity Elevator).

* **AA[0] Effect-class distribution among `{T}` / `{N}, {T}` /
  `{N}, {T}, Sac:` cost shapes** (the cost shapes Phase 2 can reach):
  * `ReturnTargetLandFromGraveyardToHand` — **1 card** (Petrified
    Field, single-AA, no riders, no TA/SA — **cleanest `{T}, Sac:`
    carrier**).
  * `PutBasicLandFromHandOntoBattlefieldTapped` — **1 card** (Terrain
    Generator, single-AA at `{2}, {T}`, no riders, no TA/SA — **cleanest
    `{N}, {T}` carrier with new Effect**).
  * `ExileTargetAttackingCreatureUntilEndStep` — 1 card (Mystifying
    Maze) — EoT-return delayed-trigger substrate is heavier than a
    single Phase-2 cycle; **Phase 3+ deferral**.
  * `BecomesCopyOfTargetLand` — 1 card (Thespian's Stage) — copy-effect
    substrate is multi-card (also unlocks Mirrorpool's
    `CopyTargetInstantOrSorceryYouControl` AA[0]); **Phase 3+ deferral**.
  * `ExileAllGraveyards` — 1 card (Scavenger Grounds, behind
    `sacrifice_a_desert` cost gate + `Land — Desert` subtype) —
    **Phase 3 deferral** (three small substrates in one card).
  * `MovePlusOneCounterBetweenPermanentsYouControl` — 1 card (Nesting
    Grounds, blocked on sorcery_speed rider) — **Phase N deferral**.
  * `PumpCreaturesYouControlUntilEOT` — 1 card (Contested War Zone),
    Effect IS bridge-covered (per Phase 1 doc §2.2), but TA=1 blocks
    the printing — **Phase N deferral** (triggered_abilities widen).

* **Sub-shape-A-eligible cards** (single-AA, no triggers, no statics,
  no keywords, no station, Land card type, no `BecomeLand` rider, no
  mana-ability, no sorcery-speed, no activate-only-once, no
  tier-threshold, no X-pips, no colored mana, no pay-life, no
  `requires_*`, no exotic sacrifice variants): **only Petrified Field +
  Terrain Generator + Mystifying Maze + Thespian's Stage + Scavenger
  Grounds** (5 candidates). Of those, only Petrified Field + Terrain
  Generator are achievable in a Phase 2 of comparable scope to Phase
  1 — Mystifying Maze / Thespian's Stage / Scavenger Grounds each
  carry their own substrate beyond a per-Effect port.

### 2.3 Phase 2 sub-shape selection — narrowest 1-2-cycle-feasible mixed widen

Phase 2 selects **two independent admit widens** corresponding to
the two cleanest residue cards:

* **Phase 2a — `{T}, Sac:` cost-shape widen + `ReturnTargetLandFromGraveyardToHand`
  Effect port.** Admits Petrified Field. Lands the FIRST non-`{T}`-only
  cost gate; ports the FIRST sacrifice-self-as-cost Effect class.
* **Phase 2b — `PutBasicLandFromHandOntoBattlefieldTapped` Effect
  port** (under the existing Phase 1.5 cost gate). Admits Terrain
  Generator. Pure Effect-class port; reuses every cost-gate primitive.

Each sub-cycle is independent — Phase 2a does NOT require Phase 2b
and vice versa. Two unblocked cards / two Rust Effect ports / one
Python cost-gate widen.

**Why not pursue Mystifying Maze / Thespian's Stage / Scavenger
Grounds in the same Phase 2 landing?**

* **Mystifying Maze.** The `ExileTargetAttackingCreatureUntilEndStep`
  effect carries an EoT-return rider — at the end of the *current
  step*, the exiled creature returns to the battlefield under its
  owner's control. The "delayed-trigger" / "until end of step"
  substrate is a separate multi-card substrate (also unlocks several
  Phase-N triggered-effect cards). Per Phase 1.5 doc §0 Mystifying
  Maze is explicitly DEFERRED.
* **Thespian's Stage.** Per Phase 1.5 doc §9.5: `BecomesCopyOfTargetLand`
  is CR-613 layer-1 copy effect — replacing the activator's printing-
  pointer on the battlefield with the target Land's printing-pointer.
  Needs a generic copy-effect substrate (per-`GameObject` `copy_of`
  pointer + resolve-time copy primitive + mana-ability re-wiring on
  the copied Land). Better to scope Thespian's Stage in a separate
  copy-effect substrate that also unlocks Mirrorpool AA[0]'s
  `CopyTargetInstantOrSorceryYouControl` (multi-card payoff). **Phase
  3+ deferral.**
* **Scavenger Grounds.** Three small substrates in one card:
  `sacrifice_a_desert` cost shape (Rust + Python cost-gate widen) +
  `Land — Desert` subtype admission (the Phase-1 admit predicate at
  `trajectory.py:8631` rejects any printing whose `card_types` carry
  an extra entry; here `subtypes=('Desert',)` is allowed because the
  guard checks `card_types`, not `subtypes` — verified in the scout
  walk; the existing token-AA Lander handles `subtypes` correctly,
  this is fine) + `ExileAllGraveyards` Effect port. Each is small but
  the cumulative surface is more than Phase 2a's single-axis widen.
  **Phase 3 deferral.**

**Phase 2 admit-set tiering — sequencing.** Phase 2a + Phase 2b are
ordered as:

1. **Phase 2a first** — it lands the `{T}, Sac:` cost gate, which is
   the higher-leverage primitive (every future Phase-N `{T}, Sac:`
   carrier — Mirrorpool, Ghost Vacuum AA[1], Keys to the House, All-
   Fates Scroll AA[1] — reuses the same cost gate). Phase 2b doesn't
   touch the cost gate.
2. **Phase 2b second** — pure Effect-class port under the existing
   Phase-1.5 cost gate; clean sibling-swap-style cycle.

Either order works; the recommendation is Phase 2a first (cost-gate
widen is the structural primitive).

---

## 3. Out of scope (Phase 3 / 4 / N)

Phase 2 retains every Phase 1 + Phase 1.5 out-of-scope clause
unchanged. The cost-shape widen to `{T}, Sac:` does NOT touch:

### 3.1 `sacrifice_a_desert` cost shape (Phase 3)

Scavenger Grounds is the only EoE Carrier-AA card carrying
`sacrifice_a_desert=True`. The cost field is already bridge-routable
(`_python_aa_to_safe_dict` already emits the key — see `cross_engine.py:14113`)
but the Phase-2 admit gate continues to decline it (separate cost-
bool decline arm). Closure adds the cost gate widen + admits Scavenger
Grounds with the `ExileAllGraveyards` Effect port and the
`Land — Desert` subtype admission.

### 3.2 Colored / hybrid / X-pip mana costs (Phase N)

Phase 2 stays generic-only on the mana axis (same as Phase 1.5a).
Colored adds CR 202.3 pip-matching; hybrid adds choose-color rider;
X adds X-pip declaration at activation. Each axis is its own admit-
gate widen with real-EoE probes; Phase 2 inherits the Phase-1.5a
decline arms unchanged. Candidates: Lavaclaw Reaches, Wandering
Fumarole, Pinnacle Starcage, Robe of Stars AA[0], Blast Zone AA[0]
(X-pip).

### 3.3 No-`tap_self` cost shapes (Phase N — Equipment cluster + Sliver Overlord + Pinnacle Starcage)

Phase 2 keeps `cost.tap_self=True` as a strict admit gate. Empty-cost
or no-tap-self carriers (Equipment cluster, Sliver Overlord, Pinnacle
Starcage) need the `tap_self=False` admit arm AND each carries
additional rider surface (sorcery_speed, triggered abilities,
Creature carriers, colored cost). **Phase N cluster.**

### 3.4 Multi-AA carriers (Phase 4)

10 of the 28 residue cards carry 2 or 3 AAs. Phase 2 keeps the
`len(printing.activated_abilities) == 1` admit gate. **Phase 4
widen** — the bridge codec round-trips an AA list, but the admit
predicate must verify each AA independently passes the per-AA sub-
shape gate (some AAs may be admit-eligible while siblings are not;
the printing-level admit must either accept all AAs or honest-stop
on any mismatched AA — the safest contract is the latter, mirroring
the token-AA Lander's all-or-nothing stance).

### 3.5 AA-level riders (Phase N)

Phase 2 keeps the `is_mana_ability=False`, `sorcery_speed=False`,
`activate_only_once=False`, `tier_threshold==0`, `room_half is None`,
`cost_reductions=()` admit gate. Each rider is its own substrate
(mana-ability ports the off-stack activation path; sorcery-speed
ports the timing-restriction; activate-only-once ports the per-
`GameObject` flag mirror; tier-threshold ports the Spacecraft station-
counter substrate dependency; room-half ports the Door-room half
substrate; cost-reductions interacts with the cost-reduction
campaign that already shipped its own Phase 1/2/3 substrates).

### 3.6 Triggered-ability-co-gated carriers (Phase N)

Phase 2 keeps `len(printing.triggered_abilities) == 0` as a strict
admit gate. **Phase N widen** — paired with a per-TA-class port for
each carrier whose TA the Carrier-AA admit gate would surface
(Contested War Zone's `ChangeControllerToCombatDamageSource`, the
Equipment-cluster's various bespoke triggers, Blast Zone AA[1]'s ETB
trigger, Lotus Field's ETB sacrifice trigger).

### 3.7 Creature carriers (Phase N)

Sliver Overlord — the only Creature carrier. Phase 2 keeps the
"Land single card_type" admit clause; widening to Creature is a
separate admit-predicate sibling
(`_printing_is_bridge_simple_carrier_aa_creature` — Phase 1 doc §3.6),
which Phase N closes.

### 3.8 BecomeLandCreatureUEOT-with-rider (Phase N — separate substrate)

Lavaclaw Reaches + Wandering Fumarole — Phase N's BecomeLand-rider
substrate (per Phase 1 doc §3.7), separate from Carrier-AA campaign.

### 3.9 Spacecraft / station-threshold (Phase N — separate substrate)

The Eternity Elevator — separate Spacecraft Station substrate (per
`docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_1_DESIGN.md`, Worker B's
parallel campaign).

---

## 4. Rust-side spec

Phase 2 ships **two new `Effect` variants** (one per sub-cycle) and
**zero new cost-shape Rust changes** (the `sacrifice_self` cost
component is ALREADY in `ActivationCost` per Lander's `{N}, Sac:` cost
shape; `parse_activation_cost` already parses the `sacrifice_self`
key; `state_ops_actions.rs:1190` already pays the sacrifice cost
during activation — verified in §4.4 below).

### 4.1 New `Effect::ReturnTargetLandFromGraveyardToHand` (Phase 2a)

**File:** `rust/src/cards.rs` — Effect enum + parse arm + to_pydict
arm. `rust/src/state_ops_resolve.rs` — resolve arm.

**Semantics (CR 701.3 — return target card from graveyard to its
owner's hand):** target a Land card in any graveyard (Petrified
Field's printed text reads "Return target land card from a graveyard
to its owner's hand" — both player's graveyards are legal targets);
move the targeted Land card from its current zone (GRAVEYARD) to the
owner's hand. No replacement effects. Resolves at top-of-stack.

**Phase 2a Rust spec:**

```rust
// In Effect enum (cards.rs):
ReturnTargetLandFromGraveyardToHand,

// In parse_effect (cards.rs):
"return_target_land_from_graveyard_to_hand" =>
    Effect::ReturnTargetLandFromGraveyardToHand,

// In to_pydict (cards.rs):
Effect::ReturnTargetLandFromGraveyardToHand => {
    py_dict.set_item(
        "kind",
        "return_target_land_from_graveyard_to_hand",
    )?;
}

// In resolve dispatch (state_ops_resolve.rs):
Effect::ReturnTargetLandFromGraveyardToHand => {
    // Target is a GraveyardCard; resolve walks every player's
    // graveyard for the targeted card_id, moves it to that
    // player's hand.
    // ... see §4.1.1 for the resolve detail
}
```

#### 4.1.1 Resolve arm — target-search and zone-move

The targeting model is **graveyard-search by card_id**. The activator
declares a target during activation (via the existing target-
selection path the bridge already routes — `state_ops_legal.rs::activate_ability_dict`
emits an `ActivateAbility` action with the target's `id` field
encoding the card_id of the Land card in a graveyard).

The resolve arm:

1. Walks `state.players[0].graveyard` + `state.players[1].graveyard`.
2. Finds the `GameObject` whose `id == target_id`.
3. Validates: `card_types.contains("Land")` (CR-target legality
   re-check at resolve — if the target left the graveyard between
   activation and resolve, the ability fizzles silently per CR 608.2b).
4. Moves the `GameObject` from `graveyard[i].remove(j)` to
   `player.hand.push(obj)` where `player == obj.controller_id`
   (target's owner is its controller in the graveyard).
5. Stamps `obj.zone = ZONE_HAND`.

**No triggered events fire on the zone-move arm** in the minimum
Phase-2a port — Python's `ReturnTargetLandFromGraveyardToHand`
(via `ReturnFromGraveyard.resolve` at
`src/mtg_bot/effects/generic/bounce.py:50`) does the same minimal
zone-move (no LTB/ETB triggers in the graveyard→hand transition;
CR 603.6 ETB triggers fire on entering the *battlefield*, not the
hand). Confirmed by reading the Python resolve arm during the
verify-first walk.

#### 4.1.2 Target enumeration on legal-action emission

`state_ops_legal.rs::activate_ability_dict` already supports target
fan-out for `{T}, Sac:` activated abilities (see `state_ops_legal.rs:3408-3505`
— the sacrifice variants enumerate eligible-target permanents on the
activator's battlefield). For `ReturnTargetLandFromGraveyardToHand`,
the legal-action emission needs a NEW fan-out path: walk both
players' graveyards for Land cards, emit one `ActivateAbility` action
per eligible target. Implementation mirrors the existing
`sacrifice_a_land` target enumeration but reads `graveyard` instead
of `battlefield`. **One new fan-out arm in `activate_ability_dict`.**

### 4.2 New `Effect::PutBasicLandFromHandOntoBattlefieldTapped` (Phase 2b)

**File:** `rust/src/cards.rs` — Effect enum + parse arm + to_pydict
arm. `rust/src/state_ops_resolve.rs` — resolve arm.

**Semantics (Terrain Generator):** "You may put a basic land card
from your hand onto the battlefield tapped." Activator searches their
hand for a basic Land card, optionally puts one onto the battlefield
tapped. ETB and landfall triggers fire (per Python's
`fire_landfall_triggers` at `src/mtg_bot/effects/generic/zone_moves.py:394`).

**Phase 2b Rust spec:**

```rust
// In Effect enum (cards.rs):
PutBasicLandFromHandOntoBattlefieldTapped,

// In parse_effect (cards.rs):
"put_basic_land_from_hand_onto_battlefield_tapped" =>
    Effect::PutBasicLandFromHandOntoBattlefieldTapped,

// In to_pydict (cards.rs):
Effect::PutBasicLandFromHandOntoBattlefieldTapped => {
    py_dict.set_item(
        "kind",
        "put_basic_land_from_hand_onto_battlefield_tapped",
    )?;
}

// In resolve dispatch (state_ops_resolve.rs):
Effect::PutBasicLandFromHandOntoBattlefieldTapped => {
    // Walk activator's hand; first basic land found goes to bf
    // tapped. Python uses "first basic" greedy ordering — match it
    // for byte-equal determinism.
    // ... see §4.2.1 for resolve detail
}
```

#### 4.2.1 Resolve arm — hand-search and ETB

The resolve arm:

1. Walks `state.players[controller_idx].hand` in original order.
2. Finds the first `GameObject` whose printing has `Land` in
   `card_types` AND `Basic` in `supertypes`.
3. If none found, no-op (Petrified-Field-style silent fizzle —
   matches Python's `if basic is None: return` at
   `zone_moves.py:382`).
4. Removes the basic from `hand`, sets `obj.zone = ZONE_BATTLEFIELD`,
   `obj.tapped = true`, `obj.controller_id = controller_idx`, pushes
   onto `battlefield`.
5. **Dispatches ETB triggers** via the existing
   `dispatch_event(Event::EntersBattlefield, basic.id)` primitive
   (CE13 Slice 5). The `fire_landfall_triggers` call in Python is
   the landfall-trigger fan-out — Rust's `Event::EntersBattlefield`
   dispatch fans out both ETB and landfall (mirrors C1 substrate's
   ETB-Slice-5 wiring).

**Targeting model:** ZERO. This Effect carries no target — the
activator's hand-search is internal. The bridge's `activate_ability_dict`
emits a single `ActivateAbility` action with no target field, mirroring
the bare `{T}: Regenerate` shape Phase 1 already supports.

**Python ETB / landfall trigger byte-equality.** Both engines must
dispatch `Event::EntersBattlefield` in the same order — verified by
the existing ETB-Slice-5 substrate at C1. Landfall triggers on
basics (the most common landfall hook) fire via the same dispatch.

### 4.3 No cost-shape Rust changes

Verified live against `cards.rs` (HEAD `e0707d88`):

* `ActivationCost.sacrifice_self: bool` exists at line 9657.
* `parse_activation_cost` reads the `sacrifice_self` key at line 16131-16135.
* `state_ops_actions.rs:773` threads `sacrifice_self: ab.cost.sacrifice_self`
  through the resolved-action struct.
* `state_ops_actions.rs:1190-1224` commits the sacrifice-cost in Phase
  5b of activation, moving the source to the controller's graveyard,
  stamping the LTB void flag, queueing `Event::Leaves` for the
  pending-leaves drain.
* The Lander token-AA precedent already exercises this `sacrifice_self`
  cost-pay path (the Lander `{2}, Sac:` token).
* `_python_aa_to_safe_dict` (Python side, `cross_engine.py:14103`)
  already emits `cost_dict["sacrifice_self"] = True` if the AA's
  cost carries the flag.

**Conclusion — Phase 2a's `{T}, Sac:` cost shape needs ZERO Rust
parser / cost-pay changes.** The Phase-2a Rust slice is a single new
`Effect` variant + parse / resolve / to_pydict arms. The Phase-2b
Rust slice is the second `Effect` variant + arms.

### 4.4 Verify-first findings — Rust state-op support audit

The cost-shape `{T}, Sac:` is fully supported end-to-end on the Rust
side ahead of Phase 2 — verified by walking each link of the
activation pipeline:

| Link | File:line | Status |
|---|---|---|
| Parse `sacrifice_self` from registry dict | `cards.rs:16131-16135` | EXISTS (Lander precedent) |
| Emit `ActivateAbility` action with sacrifice target enumeration | `state_ops_legal.rs:3408-3505` | EXISTS (handles `sacrifice_another_*` / `sacrifice_a_land` / `sacrifice_food` / `sacrifice_a_desert`; `sacrifice_self` is the no-target self-sac case at `state_ops_legal.rs:3506-3520`) |
| Pay mana cost during activation | `state_ops_cast.rs:231` | EXISTS (`pay_mana_cost_pub`) |
| Tap self if `tap_self=True` | `state_ops_actions.rs:1150-1160` | EXISTS |
| Commit `sacrifice_self`: move source to graveyard, stamp LTB void, queue Leaves | `state_ops_actions.rs:1190-1224` | EXISTS (CE20 Slice 2) |
| Drain pending `Event::Leaves` post-cost-pay | `state_ops_actions.rs:1224` (pending_leaves drain) | EXISTS |
| Effect resolve dispatch | `state_ops_resolve.rs` | NEW (the two Phase-2 Effect arms) |

**Single new Rust state-op:** the two new Effect resolve arms (one
per sub-cycle). **NO new state field.** **NO new cost-shape
machinery.**

---

## 5. Python bridge spec

### 5.1 Cost-gate widen for Phase 2a

**File:** `src/mtg_bot/parity/trajectory.py`,
`_aa_is_phase1_sub_shape_a` at line 8479.

The current Phase-1.5a cost gate (line 8549):

```python
if cost.sacrifice_self:
    return False
```

Phase 2a removes the strict `sacrifice_self` decline. The widened
cost gate admits `sacrifice_self=True` in addition to the existing
bare `{T}` / `{N}, {T}` shape:

```python
# Cost gate — Phase 2a: bare {T} OR {N}, {T} OR ({N}, {T}, Sac:)
#   (generic-only mana, optional sacrifice_self).
if not cost.tap_self:
    return False
if cost.mana is not None:
    if cost.mana.colored:
        return False
    if cost.mana.hybrid:
        return False
    if cost.mana.x_pips:
        return False
    if cost.mana.generic <= 0:
        return False
# Phase 2a admits sacrifice_self=True under cost-gate widen. Phase
# 2/3+ still declines other sacrifice variants on the same cost.
# (No early decline on sacrifice_self anymore.)
if cost.exile_self:
    return False
if cost.tap_permanent_you_control:
    return False
# ... every other cost-bool gate stays bit-identical (sacrifice_a_desert,
#     sacrifice_another_*, etc. still decline)
```

**Critical §2 contract preservation.** The widen is strictly additive
on the `sacrifice_self` axis; every other cost-bool field stays at
the Phase-1.5a contract. `sacrifice_a_desert` stays Phase 3; the
`sacrifice_another_*` family stays Phase N.

### 5.2 Effect-class gate widen for Phase 2a + 2b

**File:** `src/mtg_bot/parity/trajectory.py`,
`_carrier_aa_phase_1_effect_classes` at line 8465. The accessor name
keeps the Phase-1 prefix for back-compat (the function is the single
source of truth for the Carrier-AA admit-effect set, not specifically
Phase 1; mirrors the cost-reduction substrate's
`_cost_reduction_rule_is_phase1_or_3` widened-helper naming).

```python
def _carrier_aa_phase_1_effect_classes() -> "frozenset[type]":
    # Phase 2 widens the admit set to FOUR Effect classes — adds
    # ``ReturnTargetLandFromGraveyardToHand`` (Petrified Field) and
    # ``PutBasicLandFromHandOntoBattlefieldTapped`` (Terrain
    # Generator). Phase 3/4/N extends as each Effect class lands
    # cross-engine.
    from mtg_bot.effects.generic.destroy import RegenerateTargetCreature
    from mtg_bot.effects.generic.tap import UntapTargetLand
    from mtg_bot.effects.generic.bounce import (
        ReturnTargetLandFromGraveyardToHand,
    )
    from mtg_bot.effects.generic.zone_moves import (
        PutBasicLandFromHandOntoBattlefieldTapped,
    )
    return frozenset({
        RegenerateTargetCreature,
        UntapTargetLand,
        ReturnTargetLandFromGraveyardToHand,
        PutBasicLandFromHandOntoBattlefieldTapped,
    })
```

### 5.3 `_python_aa_to_safe_dict` Effect-dispatch widen

**File:** `src/mtg_bot/parity/cross_engine.py`,
`_python_aa_to_safe_dict` at line 14031.

The existing builder (lines 14140-14162) already handles
`RegenerateTargetCreature` + `UntapTargetLand`. Phase 2 adds two new
isinstance arms:

```python
elif isinstance(effect, ReturnTargetLandFromGraveyardToHand):
    effect_dict = {"kind": "return_target_land_from_graveyard_to_hand"}
elif isinstance(effect, PutBasicLandFromHandOntoBattlefieldTapped):
    effect_dict = {
        "kind": "put_basic_land_from_hand_onto_battlefield_tapped",
    }
```

Note: `ReturnTargetLandFromGraveyardToHand` is a subclass of
`ReturnFromGraveyard` (a base dataclass at `bounce.py:50`). The
isinstance match must be on the SPECIFIC subclass — not on
`ReturnFromGraveyard` — to avoid silently widening admission to other
`ReturnFromGraveyard` siblings (e.g.
`ReturnUpToNNonlandPermanentCardsFromYourGraveyardToHand` at
`bounce.py:425`). The Phase-2 admit gate is specifically the
target-land single-card variant.

### 5.4 `_ta_dict_to_python_effect` reverse-arm widen

**File:** `src/mtg_bot/parity/cross_engine.py`. The forward arm in
§5.3 has a matching reverse arm — Rust's dict-kind discriminator maps
back to the Python Effect subclass. Two new arms:

```python
if kind == "return_target_land_from_graveyard_to_hand":
    from mtg_bot.effects.generic.bounce import (
        ReturnTargetLandFromGraveyardToHand,
    )
    return ReturnTargetLandFromGraveyardToHand()
if kind == "put_basic_land_from_hand_onto_battlefield_tapped":
    from mtg_bot.effects.generic.zone_moves import (
        PutBasicLandFromHandOntoBattlefieldTapped,
    )
    return PutBasicLandFromHandOntoBattlefieldTapped()
```

(These return field-free `__init__` instances — no constructor args
needed; Petrified Field's effect is the bare zero-arg shape, and
Terrain Generator's is similarly zero-arg.)

### 5.5 `_printing_is_bridge_simple_carrier_aa_land` — no change

The printing-level admit predicate stays bit-identical. The Phase 2
widen is per-AA only (cost gate + Effect set); the printing-level
riders (keywords, triggered_abilities, static_abilities, spell_effect,
warp/kicker/impending, room_halves, loyalty, cost_reductions,
station_threshold, dynamic_pt_formula, ward_cost, extra card_types,
power/toughness, n_aa != 1) all retain their current contracts.

### 5.6 `_filter_deck_to_bridge_supported` OR-chain — no change

The Carrier-AA Land disjunct stays in its current position in the
OR-chain (after every existing Land disjunct, per Phase 1 doc §5.4).
Phase 2 widens within the disjunct; the chain shape is unchanged.

### 5.7 Phase-1.5a C2 invariant pin updates

**File:** `tests/test_carrier_aa_phase_1_substrate_cycle_2.py` +
`tests/test_carrier_aa_phase_1_5_substrate.py` (the pin module that
ships with Phase 1.5a).

The Phase-1.5a no-silent-auto-grow walk asserts Terrain Generator /
Thespian's Stage / Mystifying Maze STAY DECLINED on Effect-class
teeth. Phase 2 INVERTS the **Terrain Generator** clause (Effect ports
and admits) but keeps Thespian's Stage / Mystifying Maze declined.

The Phase-1.5a cost-axis regression pin asserts `{T}, Sac:` declines
— Phase 2a INVERTS that pin (Petrified Field admits at Phase 2a). The
inverted pins:

* `test_aa_is_phase1_sub_shape_a_declines_petrified_field_T_sac_cost`
  → `test_aa_is_phase2_sub_shape_a_admits_petrified_field_T_sac_cost`
* `test_printing_is_bridge_simple_carrier_aa_land_declines_live_petrified_field`
  → `test_printing_is_bridge_simple_carrier_aa_land_admits_live_petrified_field`
* `test_filter_deck_to_bridge_supported_declines_petrified_field`
  → `test_filter_deck_to_bridge_supported_admits_petrified_field`
* (Phase 2b analog for Terrain Generator — `test_..._declines_terrain_generator_effect`
  → `test_..._admits_terrain_generator_effect`.)

Mirror of the Phase 1.5a inversion convention (which itself mirrored
the Phase 1 C2 Swarmyard FLIP).

---

## 6. Test plan

### 6.1 Phase 2a substrate unit pins (Rust + Python)

1. **`parse_printing` round-trip** for a synthetic non-token CardDef
   carrying `activated_abilities=[{"cost":{"tap_self":True,"sacrifice_self":True},"effect":{"kind":"return_target_land_from_graveyard_to_hand"}}]`
   → produces an `ActivatedAbility(cost=ActivationCost(tap_self=True,
   sacrifice_self=True), effect=ReturnTargetLandFromGraveyardToHand())`.
2. **`_aa_is_phase1_sub_shape_a` admits Petrified Field's synthetic
   shape.** Synthetic AA with `{T}, Sac:` cost + `ReturnTargetLandFromGraveyardToHand`
   effect — predicate returns True. Same shape decline-table-driven
   pin for every other Phase 2+ rider (still declines).
3. **`_aa_is_phase1_sub_shape_a` continues to decline `sacrifice_a_desert`,
   `sacrifice_another_*`, every other cost-bool field.** Regression
   pin — Phase 2a widens ONLY the `sacrifice_self` axis.
4. **`_python_aa_to_safe_dict` round-trips Petrified Field's synthetic
   shape byte-equal** through `_aa_dict_to_python_activated_ability`.
5. **`Effect::ReturnTargetLandFromGraveyardToHand` parse arm** (Rust
   `#[test]`): the registry dict `{"effect":{"kind":"return_target_land_from_graveyard_to_hand"}}`
   parses to the expected Effect variant.
6. **`Effect::ReturnTargetLandFromGraveyardToHand` resolve arm** (Rust
   `#[test]`): given a state with a Land card in player[0].graveyard,
   resolve targeting that card moves it to player[0].hand; the source
   already left the bf via the cost path; byte-equal end state.

### 6.2 Phase 2b substrate unit pins (Rust + Python)

7. **`parse_printing` round-trip** for a synthetic non-token CardDef
   carrying `activated_abilities=[{"cost":{"tap_self":True,"mana":{"generic":2}},"effect":{"kind":"put_basic_land_from_hand_onto_battlefield_tapped"}}]`
   → produces the expected ActivatedAbility.
8. **`_aa_is_phase1_sub_shape_a` admits Terrain Generator's synthetic
   shape.**
9. **`_python_aa_to_safe_dict` round-trips Terrain Generator's
   synthetic shape byte-equal.**
10. **`Effect::PutBasicLandFromHandOntoBattlefieldTapped` parse +
    resolve arms** (Rust `#[test]`): given a state with one basic
    Forest in hand, resolve produces a state with the Forest on the
    battlefield tapped + ETB / landfall events dispatched.

### 6.3 Decline-set regression — the 28-card walk

11. **Live-printing parametrized walk** over the 28-card Carrier-AA
    residue, checking exactly the cards in §2.1 admit at Phase 2a +
    2b (4 cards total: Swarmyard + Deserted Temple + Petrified Field +
    Terrain Generator) AND every other card declines with the
    documented reason. Same shape as Phase 1.5a's no-silent-auto-grow
    walk.

12. **Subsystem-attribution pin:** exactly 4 EoE printings pass
    `_printing_is_bridge_simple_carrier_aa_land` (Swarmyard + Deserted
    Temple + Petrified Field + Terrain Generator) — the Phase-2
    positive set is exhaustive over the live EoE pool.

13. **Phase 3+ deferral assertions** — Mystifying Maze / Thespian's
    Stage / Scavenger Grounds stay declined on Effect-class teeth
    (the Phase-2 admit set is exactly 4, not the 5-or-more that a
    silent auto-grow would land).

### 6.4 Real-EoE per-card probes

14. **`tests/test_petrified_field_parity.py`** — real-EoE per-card
    probe (inserted at the
    `# === PHASE5_PROBES_INSERT_ABOVE_THIS_LINE ===` sentinel via
    `MODULE_FILE` symlink, batch-13 EEEE-idiom). Asserts byte-equal
    mirror through:
    * baseline (Petrified Field in play untapped, controller has no
      target Land in graveyard — state unchanged after passing
      priority);
    * return-a-Forest line (controller has a Forest in graveyard +
      Petrified Field untapped; activates `{T}, Sac: Return target
      land`; Petrified Field moves to graveyard, Forest moves to
      hand, end state byte-equal on both engines).
    Uses a scripted picker shim (`tests/parity/_picker_shims.py`)
    forcing the AA activation — same convention as Phase 1's
    Swarmyard / Deserted Temple probes.

15. **`tests/test_terrain_generator_parity.py`** — real-EoE per-card
    probe. Asserts byte-equal mirror through:
    * baseline (Terrain Generator in play untapped, hand has no basic
      Land — activation fizzles silently, state unchanged);
    * land-search-and-ETB line (Terrain Generator untapped + a basic
      Forest in hand + `{2}` floating mana; activate `{2}, {T}:
      Put basic land from hand tapped`; Terrain Generator taps, mana
      pays, Forest enters battlefield tapped, ETB/landfall events
      dispatch byte-equal on both engines).

### 6.5 Pool-parity row delta

16. **`tests/test_measure_pool_parity.py` regen** confirms +2 cards in
    PROBED tier (Petrified Field + Terrain Generator from Phase 2;
    bare admit alone for Phase 2 is +2; +2 from C3/C4 per-card probes
    flip to PROBED) and -2 cards from the BLOCKED-SG Carrier-AA row
    (28 → 26 cards remaining).

### 6.6 Pre-existing parity gate

17. **Full sanity gate** (`tests/test_parity_smoke.py +
    test_cross_engine_etb_triggers.py + test_trajectory_parity.py +
    test_trajectory.py + test_measure_pool_parity.py`) stays green.
    The Phase-1 + Phase-1.5a pins continue to pass (no regression on
    Swarmyard / Deserted Temple admits).

---

## 7. Estimated cycle count

Phase 2 is a **3-4 cycle landing**, mirroring Phase 1's C1 / C2 / C3 /
C4 cadence:

| Cycle | Owner | Deliverable |
|---:|---|---|
| 1 (C1) | Rust agent | **Phase 2a Rust substrate:** new `Effect::ReturnTargetLandFromGraveyardToHand` variant + parse / resolve / to_pydict arms + the new graveyard-Land target fan-out arm in `state_ops_legal.rs::activate_ability_dict` + the 2 Rust unit pins (§6.1 #5-6). **Sole Rust slice this round** (`.pyd` race rule). |
| 2 (C2) | Python/bridge agent | **Phase 2a admit + Petrified Field FLIP:** Python cost-gate widen (`_aa_is_phase1_sub_shape_a` removes `sacrifice_self` decline) + `_carrier_aa_phase_1_effect_classes` widen + `_python_aa_to_safe_dict` + `_ta_dict_to_python_effect` arms + the 4 Python unit pins (§6.1 #1-4) + C2 pin inversions for Petrified Field + Phase-1.5a no-silent-auto-grow walk inverts the Petrified Field clause + Petrified Field real-EoE probe (§6.4 #14) + pool-parity regen. |
| 3 (C3) | Rust agent | **Phase 2b Rust substrate:** new `Effect::PutBasicLandFromHandOntoBattlefieldTapped` variant + parse / resolve / to_pydict arms (the activated AA carries no target — no new fan-out arm needed) + the 1 Rust unit pin (§6.2 #10). Sole Rust slice this round. |
| 4 (C4) | Python/bridge agent | **Phase 2b admit + Terrain Generator FLIP:** `_carrier_aa_phase_1_effect_classes` widen (add the Phase-2b Effect class) + `_python_aa_to_safe_dict` + `_ta_dict_to_python_effect` arms + the 3 Python unit pins (§6.2 #7-9) + Phase-1.5a no-silent-auto-grow walk inverts the Terrain Generator clause + Terrain Generator real-EoE probe (§6.4 #15) + pool-parity regen + SL entry amendments (§8). |

**Estimated total: 4 cycles for Phase 2** (Phase 2a in C1+C2, Phase
2b in C3+C4). Could collapse to 3 cycles if the Phase 2b Effect port
+ admit lands in a single mixed C3 (Rust + Python both light), but
the `.pyd` race rule preference is one Rust slice per cycle. **Light
preference: keep the 4-cycle cadence for clean Rust/Python
separation.**

**Cost driver:** Phase 2a Cycle 1 (the Rust substrate) — the new
target-fan-out arm in `state_ops_legal.rs::activate_ability_dict` is
the largest new code surface (graveyard-walk per-eligible-target
enumeration, mirror of the existing sacrifice-target fan-out at
`state_ops_legal.rs:3408-3505`). Phase 2b's Effect port is lighter
(no new target-fan-out — it's a no-target effect).

---

## 8. SEARCH_LIMITATIONS.md entries

Phase 2 amends the Phase 1.5 SL entry and adds two new entries:

* **Amend Phase 1.5 SL entry 1** — widen the cost-shape clause:
  "bare `{T}:` OR `{N}, {T}:` OR `{N}, {T}, Sac:` (generic-only mana,
  no colored / hybrid / X-pip; tap_self required; sacrifice_self
  optional) single-AA single-bridged-Effect non-token Land sub-shape;
  colored-mana / hybrid / X-cost shapes deferred to Phase N;
  `sacrifice_a_desert`, mana-ability, sorcery-speed, activate-only-once,
  tier-threshold, room-half, multi-AA, Creature-carrier shapes still
  deferred." Failure mode and fix-scope unchanged.

* **New Phase 2 SL entry 1** — "Phase 2a ports the `Effect::ReturnTargetLandFromGraveyardToHand`
  variant at the minimum graveyard→hand zone-move semantics; CR-608.2b
  resolution-time target-legality re-check is honored; no replacement-
  effect interactions modeled (CR 614 — none of the EoE printings
  trigger replacement effects on graveyard→hand transitions)." Same
  shape as Phase 1's SL entry 2.

* **New Phase 2 SL entry 2** — "Phase 2b ports the `Effect::PutBasicLandFromHandOntoBattlefieldTapped`
  variant at the minimum first-basic-in-hand greedy semantics ('may'
  always yes when a basic is in hand — matches Python's behavior at
  `effects/generic/zone_moves.py:382`); ETB / landfall trigger
  dispatch via `Event::EntersBattlefield` is byte-equal across
  engines." Same shape.

---

## 9. Rejected alternatives

### 9.1 Phase 2 widens cost gate AND ports 3-4 new Effects in one landing

**Rejected — too broad for a single Phase.** Cycling 3-4 new Effect
ports (Petrified Field + Terrain Generator + Mystifying Maze +
Thespian's Stage) into a single Phase 2 mixes axes that have
independent cost surfaces (Mystifying Maze's EoT-return is its own
substrate; Thespian's Stage needs the copy-effect substrate). Per
Phase 1 §10.3's sibling-swap clause, each Effect class deserves its
own per-Effect port cycle — Phase 2 ports the two CLEANEST Effects
(no rider surface beyond the cost gate widen).

### 9.2 Pursue Scavenger Grounds in Phase 2 instead of Terrain Generator

**Rejected — three small substrates in one card.** Scavenger Grounds
needs `sacrifice_a_desert` cost gate (axis-independent of
`sacrifice_self`) + `Land — Desert` subtype admission (Phase 1 admit
predicate doesn't reject `subtypes`, but the Phase-2 admit-test
walks must positively verify the subtype doesn't trip a sibling
guard) + `ExileAllGraveyards` Effect port (moderate — walks both
players' graveyards and exiles every card). Terrain Generator needs
ONE substrate (its Effect port). The lower-friction Phase 2b pilot is
Terrain Generator; Scavenger Grounds rides a future Phase 3 cycle.

### 9.3 Defer the `{T}, Sac:` cost gate to Phase 3 and pursue Effect-only Phase 2 (Terrain Generator alone)

**Rejected — `{T}, Sac:` is the higher-leverage primitive.** Phase 2
mixes cost-gate widen + Effect ports specifically because the
`{T}, Sac:` cost gate compositionally unlocks the path to Mirrorpool /
Ghost Vacuum / Keys to the House / All-Fates Scroll AA[1] (multi-AA
or sorcery-speed-gated, Phase 4+ — but each will need ONLY its
Effect port + the multi-AA rider widen, not the cost gate). Landing
the cost gate in Phase 2 (via Petrified Field — the cleanest single-
AA `{T}, Sac:` carrier) means every later phase reuses the proven-
correct cost-gate machinery. Effect-only Phase 2 would leave the
cost gate as a Phase 3+ blocker that 4 multi-AA cards (Mirrorpool +
Ghost Vacuum + Keys to the House + All-Fates Scroll) all need.

### 9.4 Bundle Thespian's Stage into Phase 2 (copy-effect substrate)

**Rejected — copy-effect cost.** Per Phase 1.5 doc §9.5:
`BecomesCopyOfTargetLand` is a CR-613 layer-1 copy effect. The Rust
mirror needs a per-`GameObject` `copy_of` pointer + resolve-time copy
primitive + interaction with the mana-ability auto-wire (the copied
Land's mana abilities must register). This is its own substrate, not
a per-Effect port. Bundle with Mirrorpool's
`CopyTargetInstantOrSorceryYouControl` (Phase 4+ multi-AA) for
multi-card payoff in a separate copy-effect substrate doc.

### 9.5 Bundle Mystifying Maze into Phase 2 (EoT-return delayed-trigger)

**Rejected — EoT-return rider is its own substrate.**
`ExileTargetAttackingCreatureUntilEndStep` carries a delayed-trigger
rider: "at end of the current step, return the exiled creature to the
battlefield under its owner's control" (CR 603.7). The substrate
needs a `delayed_triggers` queue per turn + an end-of-step dispatch
arm + the return-from-exile-to-battlefield zone-move primitive. This
is a multi-card substrate (Mystifying Maze is one card; future EoT-
return printings will reuse the same machinery). Bundle in a separate
delayed-trigger substrate doc; **Phase 3+ deferral.**

### 9.6 Pursue Mirrorpool / Ghost Vacuum / Keys to the House / All-Fates Scroll multi-AA in Phase 2

**Rejected — multi-AA admit predicate is its own substrate (Phase 4).**
The bridge codec round-trips an AA list, but the printing-level admit
predicate must verify each AA independently passes the per-AA sub-
shape gate. The safest contract is all-or-nothing (every AA must
admit) — mirrors the token-AA Lander's stance. Phase 4's multi-AA
substrate handles the multi-AA admit predicate widen + multi-AA pin
plumbing across the bridge + per-AA target-fan-out coordination.

### 9.7 Land Phase 2a + Phase 2b in the same cycle as a single mixed substrate

**Rejected — `.pyd` race rule and separation of concerns.** Phase 2a
ships the `{T}, Sac:` cost-gate widen + `ReturnTargetLandFromGraveyardToHand`
Effect; Phase 2b ships the `PutBasicLandFromHandOntoBattlefieldTapped`
Effect. Each Effect is its own Rust slice (parse / resolve / to_pydict
arms). Folding both into one cycle adds two Rust slices in one
.pyd-rebuild window, doubles the cross-engine surface verified at
landing time, and conflates the cost-gate widen (Phase 2a-only
concern) with the Effect-port widen (Phase 2b-only concern). Two
separate Rust cycles preserves the `.pyd` race rule and keeps the
admit-gate inversions audited cleanly.

---

## 10. Acceptance / sign-off

Phase 2 is complete and ready to merge to `main` when:

1. The Phase 2a Rust substrate (§4.1) lands; the `.pyd` rebuilds clean.
2. The Phase 2a admit + Petrified Field FLIP (§5.1, §5.2, §5.3, §5.4)
   lands; the 6 Phase-2a unit pins (§6.1 #1-6) all pass.
3. The Phase 2a Petrified Field real-EoE probe (§6.4 #14) passes
   byte-equal on both engines through baseline + return-a-Forest line.
4. The Phase 2b Rust substrate (§4.2) lands; the `.pyd` rebuilds clean.
5. The Phase 2b admit + Terrain Generator FLIP (§5.2, §5.3, §5.4)
   lands; the 4 Phase-2b unit pins (§6.2 #7-10) all pass.
6. The Phase 2b Terrain Generator real-EoE probe (§6.4 #15) passes
   byte-equal through baseline + land-search-and-ETB line.
7. The 28-card decline-set walk (§6.3 #11-13) confirms exactly the
   4-card admit set (Swarmyard + Deserted Temple + Petrified Field +
   Terrain Generator) — exhaustive over the live EoE pool.
8. Pool-parity regen (§6.5 #16) lands +2 cards in PROBED tier; BLOCKED-
   SG Carrier-AA row shrinks from 28 to 26.
9. The amended Phase 1.5 SL entry + the 2 new Phase 2 SL entries
   (§8) land alongside the code change.
10. The full parity gate (§6.6 #17) stays green (31/31 on the
    measure-pool-parity module specifically).

---

## 11. Cross-references

* `docs/CARRIER_AA_SUBSTRATE_PHASE_1_DESIGN.md` — the parent campaign-
  shape doc. §2.1 30-card walk + §2.3 sub-shape selection + §3 out-
  of-scope matrix + §5 admit predicate + §10.3 sibling-swap clause.
* `docs/CARRIER_AA_SUBSTRATE_PHASE_1_5_DESIGN.md` — Phase 1.5a cost-
  gate widen + the §10.3 sibling-swap analysis identifying Terrain
  Generator / Thespian's Stage / Mystifying Maze as candidates.
* `src/mtg_bot/parity/trajectory.py:8420-8667` —
  `_aa_is_phase1_sub_shape_a` + `_printing_is_bridge_simple_carrier_aa_land`
  + `_carrier_aa_land_card_def` (the Phase-2 widen sites).
* `src/mtg_bot/parity/trajectory.py:8465` —
  `_carrier_aa_phase_1_effect_classes` (the Effect-set admit gate
  widened in §5.2).
* `src/mtg_bot/parity/cross_engine.py:14031-14166` —
  `_python_aa_to_safe_dict` (the AA serializer widened in §5.3).
* `src/mtg_bot/parity/cross_engine.py:12360-12410` —
  `_ta_dict_to_python_effect` (the AA effect-class reverse-arm
  widened in §5.4).
* `rust/src/cards.rs:9614-9784` — `ActivationCost` struct (already
  carries `sacrifice_self: bool`, no change needed).
* `rust/src/cards.rs:16131-16135` — `parse_activation_cost`
  `sacrifice_self` arm (no change needed).
* `rust/src/state_ops_actions.rs:1190-1224` — sacrifice_self cost-pay
  commit in Phase 5b of activation (CE20 precedent).
* `rust/src/state_ops_legal.rs:3408-3505` — sacrifice-target fan-out
  arms (Phase 2a's graveyard-target fan-out mirrors this).
* `src/mtg_bot/effects/generic/bounce.py:467-484` — Python's
  `ReturnTargetLandFromGraveyardToHand` (Petrified Field's effect —
  the Rust port mirror).
* `src/mtg_bot/effects/generic/zone_moves.py:359-400` — Python's
  `PutBasicLandFromHandOntoBattlefieldTapped` (Terrain Generator's
  effect — the Rust port mirror).
* `tests/test_carrier_aa_phase_1_substrate_cycle_2.py` + Phase 1.5a's
  no-silent-auto-grow walk — pins inverted in §5.7.

---

## 12. Sequencing recommendation

**Recommended sequencing for Phase 2 landing:**

1. **Ship Phase 2a Cycle 1 (Rust substrate)** — Worker A or whoever
   has the Rust agent. Single `Effect::ReturnTargetLandFromGraveyardToHand`
   variant + the new graveyard-target fan-out arm in
   `state_ops_legal.rs`. `.pyd` rebuild required; coordinate with
   any parallel Rust work.
2. **Ship Phase 2a Cycle 2 (Python admit + Petrified Field FLIP)** —
   Python-only. Cost-gate widen + Effect-set widen + bridge arms +
   pin inversions + the real-EoE probe.
3. **Sanity-gate confirmation** at 2a landing — the 31/31 measure-
   pool-parity baseline holds with +1 card in PROBED tier (3 admitted:
   Swarmyard + Deserted Temple + Petrified Field).
4. **Ship Phase 2b Cycle 3 (Rust substrate)** — single
   `Effect::PutBasicLandFromHandOntoBattlefieldTapped` variant + parse
   / resolve / to_pydict arms. `.pyd` rebuild required.
5. **Ship Phase 2b Cycle 4 (Python admit + Terrain Generator FLIP)** —
   Python-only. Effect-set widen + bridge arms + pin inversions + the
   real-EoE probe + pool-parity regen + SL entries.
6. **Final sanity-gate confirmation** at 2b landing — the 31/31
   measure-pool-parity baseline holds with +2 total cards (4
   admitted: Swarmyard + Deserted Temple + Petrified Field + Terrain
   Generator).

**Next Carrier-AA campaign milestones after Phase 2:**

* **Phase 3 (Scavenger Grounds)** — `sacrifice_a_desert` cost gate +
  `Land — Desert` subtype admission + `ExileAllGraveyards` Effect
  port. One card unlock; small substrate; clean per-cycle.
* **Phase 3+ / 4 (Multi-AA + copy-effect + EoT-return)** — Mirrorpool
  + Thespian's Stage + Mystifying Maze. Each is its own multi-card
  substrate (multi-AA admit predicate, copy-effect substrate,
  delayed-trigger / EoT-return substrate). Each takes 3-5 cycles.
* **Phase N (mana-ability, sorcery-speed, Equipment cluster, BecomeLand-
  rider, Spacecraft, Creature carrier, activate-only-once, tier-
  threshold)** — each is its own rider substrate per Phase 1 §3. Most
  carriers in the 28-card residue stay in this Phase-N tail.

---

## 13. Verify-first walk reproduction

The §2.1 28-card residue table was verified by a one-off walker
(not committed — `_scout_phase2.py` during the design lane) over the
live `OracleParserCardSource` at HEAD `e0707d88`, enumerating each
card's `(card_types, subtypes, n_aa, n_ta, n_sa, keywords,
station_threshold)` and every AA's `(cost.mana, cost-bool fields,
extras, AA-riders, effect-class)`. The walker reproduces from the
Phase 1 doc §13 regeneration script seeded with the 28-card residue
list (Phase 1 §2.1 minus Swarmyard + Deserted Temple), or by reading
`subsystem_attribution()` from
`scripts/scout_r58_subsystem_attribution.py` and filtering to the
Carrier-AA subsystem.

```python
from mtg_bot.cards.parser.source import OracleParserCardSource
ps = OracleParserCardSource().get_printings()
residue = [
    # Phase 1 §2.1 30-card list MINUS Swarmyard + Deserted Temple
    # (Phase 1 + Phase 1.5a admit set).
    "All-Fates Scroll", "Ancient Tomb", "Atomic Microsizer",
    "Auxiliary Boosters", "Baseball Bat", "Blast Zone",
    "Contested War Zone", "Ghost Vacuum",
    "Grove of the Burnwillows", "Haunted Screen",
    "Keys to the House", "Lavaclaw Reaches", "Lotus Field",
    "Meteor Crater", "Mirrorpool", "Mystifying Maze",
    "Nesting Grounds", "Petrified Field", "Pinnacle Starcage",
    "Reflecting Pool", "Robe of Stars", "Saw",
    "Scavenger Grounds", "Sliver Overlord",
    "Terrain Generator", "The Eternity Elevator",
    "Thespian's Stage", "Wandering Fumarole",
]
for name in residue:
    p = ps[name]
    # ... walk per §2.1 per-card categorization, log results ...
```

The full walker output was logged 2026-05-25 during this design
lane; the §2.1 table is the canonical summary. To regenerate at a
future HEAD, re-run the walk (the Phase 1 doc §13 regeneration
script is the parent reference).
