# Carrier-AA substrate — Phase 4 design

**Status:** DESIGN — docs-only scoping for the Phase 4 multi-AA wave.
No code change lands with this doc. The baseline parity gate
(`tests/test_measure_pool_parity.py`) was confirmed green (32/32) at
HEAD `dbbc1a41` (inventory refresh post-multi-substrate P1) prior to
writing this scope; no `.pyd` or test mutation accompanies the design
slice.

**Author:** Carrier-AA Phase 4 design lane, Worker B
(`feature/carrier-aa-substrate-phase-4-design-p1`), 2026-05-26.

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
* Phase 3A (Mystifying Maze) — `604de874` design + landing pair.
  `Effect::ExileTargetAttackingCreatureUntilEndStep` +
  `Effect::ReturnExiledPermanentToOwnerTapped` delayed-trigger
  PRODUCER substrate + attacking-creature target fan-out arm.
* Phase 3B (Scavenger Grounds) — landing on Phase-3 design.
  `Effect::ExileAllGraveyards` mass-zone-move + `sacrifice_a_desert`
  cost-bool gate widen.
* Phase 3C C1 (Thespian's Stage substrate) — `f5a2a1ce`.
  `GameObject.original_printing_id: Option<u32>` slot + per-zone-
  change reset + fingerprint serializer (in-flight; C2 admit-widen +
  FLIP under Worker A in parallel).

**Carrier-AA admit set at HEAD `dbbc1a41`:** **6 cards** — Swarmyard +
Deserted Temple + Petrified Field + Terrain Generator + Mystifying
Maze + Scavenger Grounds. (Thespian's Stage STAYS DECLINED at C1 —
flips on Worker A's C2 landing under Phase 3C.) BLOCKED-SG Carrier-AA
row at this design: **24 cards remaining**.

**Companion docs:** `docs/CARRIER_AA_SUBSTRATE_PHASE_1_DESIGN.md`
(parent campaign-shape doc — §2.1 30-card walk, §3 out-of-scope
matrix, §10.3 sibling-swap clause);
`docs/CARRIER_AA_SUBSTRATE_PHASE_1_5_DESIGN.md` (Phase 1.5a cost-gate
widen);
`docs/CARRIER_AA_SUBSTRATE_PHASE_2_DESIGN.md` (Phase 2a/2b
cost+Effect landing + §3.4 multi-AA Phase-4 deferral);
`docs/CARRIER_AA_SUBSTRATE_PHASE_3_DESIGN.md` (Phase 3A/3B/3C three-
sub-phase orthogonal-Effect-family widens). This Phase 4 doc inherits
their definitions; cross-references cite by section.

---

## 0. Executive summary

Phase 4 is a **four-sub-phase landing** that closes the multi-AA
Carrier-AA wave — the FIRST campaign Phase to admit carriers with
`len(printing.activated_abilities) > 1`. Phases 1-3 admitted a strict
single-AA gate (`len(aas) != 1: return False` at
`trajectory.py:9240`); Phase 4 widens that gate to multi-AA while
preserving the per-AA sub-shape-A admit predicate as the inner check.

**Cards in scope (4 cards, all with n_aa=2; verified live at HEAD
`dbbc1a41` — see §2.1):**

* **Mirrorpool** (Land; AA[0] = `{2}{C}, {T}, Sac:
  CopyTargetInstantOrSorceryYouControl` / AA[1] = `{4}{C}, {T}, Sac:
  CreateTokenCopyOfTargetCreatureYouControl`). **Two new Effect ports
  needed** — both copy effects, in DIFFERENT copy-machinery families
  per Phase 3C §2.4 (CR-707.2 spell-copy + CR-707.5 token-creature-
  copy). Mirrorpool is the heaviest sub-phase by Effect count.
* **Ghost Vacuum** (Artifact; AA[0] = `{T}:
  ExileTargetCardFromGraveyard` / AA[1] = `{6}, {T}, Sac:
  PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl`
  with sorcery_speed rider). **Two new Effect ports needed** — both
  exile-related but operating on different zones. Adds the
  `exiled_with_source` self-stamp produce-then-consume primitive
  (Ghost Vacuum exiles WITH itself as the source on AA[0]; AA[1]
  reads that pool back).
* **Keys to the House** (Artifact; AA[0] = `{1}, {T}, Sac:
  SearchLibraryForCard(filter_name="basic_land")` / AA[1] = `{3}, {T},
  Sac: LockOrUnlockDoorOfTargetRoomYouControl` with sorcery_speed
  rider). **One Effect already partially bridged (SearchLibraryForCard
  has a reverse arm + Rust resolve at
  `cards.rs:14965`/`cards.rs:18746`); one new Effect port + an
  `sorcery_speed` AA-rider widen on the bridge floor + the rooms/doors
  Effect surface.** Heaviest in rider count.
* **All-Fates Scroll** (Artifact; AA[0] = `{T}:
  AddManaToPool(produces=(("any", 1),))` mana-ability /
  AA[1] = `{7}, {T}, Sac: DrawCardsByConditionMultiplier(condition=
  PerDifferentlyNamedLand())`). **Adds the mana-ability admit + one
  new Effect port for the condition-multiplier draw effect.**
  Mana-ability admit is the substrate primitive Phase 4 needs for the
  multi-AA carriers whose first AA is "tap for mana".

**Phase 4 admit delta:** **+4 cards** (Mirrorpool + Ghost Vacuum +
Keys to the House + All-Fates Scroll). Each FLIP is independent —
sub-phases ship in their own paired-Rust-Python-probe cycle.

**Cycle estimate:** **~14-16 cycles total** across the four sub-
phases — Phase 4A (multi-AA admit substrate): 2 cycles (Python-only
predicate widen + sanity walk). Phase 4B (Mirrorpool): 5 cycles
(Rust spell-copy + Rust token-creature-copy + Python admit + 2
probe lines). Phase 4C (Ghost Vacuum): 3 cycles (Rust exile-from-
graveyard + Rust return-from-exile-pool + Python admit + sorcery-
speed AA-rider widen + probe). Phase 4D (Keys to the House): 3
cycles (rooms/doors Rust + Python admit + sorcery-speed widen + probe).
Phase 4E (All-Fates Scroll): 2-3 cycles (mana-ability AA-rider widen
on the bridge floor + Rust condition-multiplier Effect port + probe).

**Out-of-scope (Phase 5+):**
* Multi-AA carriers in the remaining residue (Haunted Screen — 3 AAs
  with `AddNManaOfChosenColor` + `activate_only_once` Sequence
  effect; The Eternity Elevator — `AddChargeCounterManaOfChosenColor`
  station-threshold-adjacent). **Phase 5+** per §3.2.
* AA-level riders beyond `sorcery_speed` + `is_mana_ability`
  (`activate_only_once`, `tier_threshold`, `room_half`,
  `cost_reductions`). **Phase N** per Phase 1 §3.5.
* X-pip mana costs (e.g. variable-X tutor / draw / damage effects).
  Stays Phase N.
* `pay_life` cost rider (used by Erratic Apparition / no-EoE Carrier-
  AA today). Stays Phase N.

**Substrate-leverage:** Phase 4 lands **four orthogonal substrates
that compositionally unlock the deeper multi-AA roadmap**:

* **Multi-AA admit predicate** (Phase 4A) — the keystone widen that
  every later multi-AA Phase inherits. Mirrors the token-AA Lander's
  all-or-nothing per-AA contract: the printing admits iff every AA
  in the tuple independently passes the per-AA sub-shape-A predicate.
* **CR-707.2 spell-copy substrate** (Phase 4B-1) — pushes a copy of a
  spell onto the stack with the activator as controller. Reused by
  any future "copy target spell" Effect port.
* **CR-707.5 token-creature-copy substrate** (Phase 4B-2) — allocates
  a new token GameObject whose printing is derived from a battlefield
  creature. Reuses Phase 3C's printing-registry push primitive.
  Future "create token copy of target X" Effect ports inherit.
* **`sorcery_speed` AA-rider widen** (Phase 4C/4D shared) — opens the
  Carrier-AA admit gate to AAs with `aa.sorcery_speed=True`, which
  is a printed-text "Activate only as a sorcery" restriction. Future
  multi-AA carriers gain this rider for free.
* **`is_mana_ability` AA-rider widen** (Phase 4E) — opens the Carrier-
  AA admit gate to AAs with `aa.is_mana_ability=True`. The bridge
  already supports `AddManaToPool` round-trip (per Phase 1 mana-
  ability auto-wire at `cross_engine.py:14252`); the widen lifts the
  current per-AA decline at `_python_aa_to_safe_dict:14699`.

---

## 1. Background — Phase 3 closure and the 24-card residue

Phase 1-3 closed six single-AA Land/Artifact carriers (Swarmyard +
Deserted Temple + Petrified Field + Terrain Generator + Mystifying
Maze + Scavenger Grounds). Phase 3C C2 (Thespian's Stage admit-widen
+ FLIP) is in flight under Worker A in parallel; once it lands, the
seventh single-AA admit lands and Phase 1-3's coverage closes.

The remaining 24 BLOCKED-SG Carrier-AA carriers split by `n_aa`:

| n_aa | Count | Notes |
|---:|---:|---|
| 1 | ~17 | Various rider clusters (mana-ability standalone, sorcery-speed standalone, station-threshold, X-pip, colored mana, room-half, pay_life, BecomeLandCreatureUEOT-with-rider, Creature carrier overlap, Equipment carrier overlap, etc.) — Phase N per Phase 1 §3.2-§3.9 + Phase 2 §3.2-§3.9. |
| 2 | ~6 | Mirrorpool + Ghost Vacuum + Keys to the House + All-Fates Scroll (THIS PHASE) + The Eternity Elevator + Haunted Screen (Phase 5+). |
| 3 | ~1 | Haunted Screen — Phase 5+ (3 AAs incl. one `activate_only_once`-gated Sequence effect). |

**Phase 4 lands the 4 multi-AA Carrier-AA cards with n_aa=2 whose
remaining substrate is tractable in one campaign Phase.** Haunted
Screen's `n_aa=3` + the `activate_only_once` + `Sequence` rider
combination is structurally heavier than the 4 in-scope cards;
deferring to Phase 5 keeps Phase 4's design compact. The Eternity
Elevator's `AddChargeCounterManaOfChosenColor` AA is station-
threshold-adjacent and bundles cleaner with the Spacecraft
substrate's Phase 4+ tail.

**Why one design doc, not four.** The four sub-phases ship 4 cards on
4 independent codepaths; the campaign-shape question — "what is the
Phase 4 admit delta" — has a single answer (+4 cards), and the out-
of-scope matrix + the rejected-alternatives ("bundle these into one
cycle" / "bundle two of them" / "defer the multi-AA admit primitive
to Phase 5") is identical across all four. Phase 3 split into A/B/C
sub-phases under one design doc on the same precedent.

---

## 2. Verify-first walk — the 4 candidate cards at HEAD `dbbc1a41`

The walk script (a one-off scout, not committed — design-lane verify-
first discipline) enumerated each of the 4 cards' `(card_types,
subtypes, n_aa, n_ta, n_sa, keywords)` and per-AA
`(cost.mana_str, cost-flags, effect-class, AA-riders)`.

### 2.1 Per-card details (verified live)

| Card | Type | n_aa | n_ta | n_sa | AA[0] cost | AA[0] Effect | AA[1] cost | AA[1] Effect |
|---|---|---:|---:|---:|---|---|---|---|
| **Mirrorpool** | Land | 2 | 0 | 0 | `{2}{C}, {T}, Sac` | `CopyTargetInstantOrSorceryYouControl` | `{4}{C}, {T}, Sac` | `CreateTokenCopyOfTargetCreatureYouControl(additional_subtype=None)` |
| **Ghost Vacuum** | Artifact | 2 | 0 | 0 | `{T}` | `ExileTargetCardFromGraveyard` | `{6}, {T}, Sac` (+ sorcery_speed) | `PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl(grant_flying_counter=True, grant_subtype_and_pt=('Spirit', 1, 1))` |
| **Keys to the House** | Artifact | 2 | 0 | 0 | `{1}, {T}, Sac` | `SearchLibraryForCard(filter_name='basic_land', max_mv=0, may_fail=True)` | `{3}, {T}, Sac` (+ sorcery_speed) | `LockOrUnlockDoorOfTargetRoomYouControl()` |
| **All-Fates Scroll** | Artifact | 2 | 0 | 0 | `{T}` (+ is_mana_ability) | `AddManaToPool(produces=(("any", 1),), spend_restriction=None)` | `{7}, {T}, Sac` | `DrawCardsByConditionMultiplier(condition=PerDifferentlyNamedLand(), description_fragment='where X is the number of differently named lands you control')` |

All four are NON-Land OR Land but with NO keyword / triggered /
static / spell_effect / warp_cost / kicker_cost / impending_cost /
room_halves / loyalty / cost_reductions / station_threshold /
dynamic_pt / ward_cost / `power`/`toughness` — every other guard in
`_printing_is_bridge_simple_carrier_aa_land` (Phase 1-3 land version
verified live) and its Artifact sibling guard pass clean.

**Critical structural observation: Mirrorpool's `{C}` IS COLORLESS-
GENERIC.** The parser folds `{C}` mana pips into `ManaCost.generic`,
NOT into `ManaCost.colored`. Verified live:
`Mirrorpool AA[0].cost.mana.generic=3, colored=()`. The existing
generic-only cost gate at `trajectory.py:9095` (`if cost.mana.colored:
return False`) admits Mirrorpool's `{2}{C}` cost as 3 generic. **NO
new cost-shape Rust changes needed for Mirrorpool's `{C}` pips.**

**Critical structural observation: 3 of the 4 cards are Artifact, NOT
Land.** Phase 1-3 admit predicate is
`_printing_is_bridge_simple_carrier_aa_land` (Land-only). Phase 4
needs a SIBLING admit predicate for the Artifact carriers OR a widen
of the existing predicate to admit Artifact card_type. The existing
admit teeth (`extra_card_types`, `keywords`, `triggered_abilities`,
etc.) apply unchanged; only the `"Land" not in printing.card_types`
guard at `trajectory.py:9201` needs widening — see §5.3.

### 2.2 Python Effect-class signatures (verified live)

* **`CopyTargetInstantOrSorceryYouControl`** at
  `src/mtg_bot/effects/generic/stack_control.py`. `requires_target()
  = True`. `legal_targets()` walks `state.stack` for `StackItem`
  entries that are Instant or Sorcery spells controlled by the
  activator. Resolves by pushing a copy of the spell onto the stack
  with the activator as the controller (CR 707.2 — copy of a spell;
  may NOT be cast, only resolves). The copy keeps the same targets
  as the original UNLESS the activator chooses new targets.
* **`CreateTokenCopyOfTargetCreatureYouControl`** at
  `src/mtg_bot/effects/generic/tokens.py`. `requires_target() = True`.
  `legal_targets()` walks `state.battlefield` for any Creature
  controlled by the activator. Resolves by:
  1. Snapshotting the target's printing.
  2. Deriving a new token printing via `dataclasses.replace`
     (carrying ETB-triggered / static abilities but NOT mana-cost or
     spell-side properties — CR 707.5 token-copy contract).
  3. Allocating a new GameObject with `is_token=True`, controller =
     activator, owner = activator.
  4. Pushing into the printing registry + appending to
     `state.battlefield`.
  5. Dispatching `Event::EntersBattlefield(token.id)`.
  The `additional_subtype` slot (default `None`) lets variant
  effects ("create a token copy of target creature; it gains
  Vigilance" / "...; it's also a Spirit") layer a subtype + bonus
  P/T onto the derived token. Mirrorpool AA[1]'s instance has
  `additional_subtype=None` — bare token copy, no rider.
* **`ExileTargetCardFromGraveyard`** at
  `src/mtg_bot/effects/generic/exile.py:~6006-6080`.
  `requires_target() = True`. `legal_targets()` walks every player's
  graveyard for any card. Resolves by moving the target from
  graveyard → exile. **Stamps `obj.exiled_with_source =
  source.id`** so a later "return cards exiled with this" effect can
  find them (Ghost Vacuum's AA[1] is the matching consumer).
* **`PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl`**
  at `src/mtg_bot/effects/generic/exile.py:~4285+`.
  `requires_target() = False` (the "each" makes it mass; the source
  itself drives the enumeration). `legal_targets()` returns the
  empty tuple — no fan-out. Resolves by walking every player's
  `exile` for GameObjects with `exiled_with_source == source.id AND
  printing.is_creature`. For each, move to activator's battlefield;
  if `grant_flying_counter=True`, stamp a flying counter; if
  `grant_subtype_and_pt=('Spirit', 1, 1)`, the token-side rider
  overlays a Spirit subtype + 1/1 base P/T. Ghost Vacuum's instance
  carries the full Spirit+1/1+flying rider on every returned card.
* **`SearchLibraryForCard`** at
  `src/mtg_bot/effects/generic/search.py:30-95`. `requires_target() =
  False` (the activator picks from their own library, agent-
  driven). Fields: `filter_name: str` (REQUIRED), `max_mv: int = 0`,
  `may_fail: bool = True`. The `filter_name="basic_land"` filter
  (Keys to the House) matches any printing whose
  `(card_types: ("Land",), supertypes: ("Basic",))`. Already
  bridge-supported per `cross_engine.py:5325` (forward) +
  `cross_engine.py:7693` (reverse for `add_mana_to_pool`'s arm —
  search arm is at the same dispatch). Rust resolve at
  `state_ops_resolve.rs` (variant exists; per round-21 bridge
  closure).
* **`LockOrUnlockDoorOfTargetRoomYouControl`** at
  `src/mtg_bot/effects/generic/misc.py`. **NEW SUBSTRATE.**
  `requires_target() = True`. `legal_targets()` walks
  `state.battlefield` for Room cards (`Room` subtype, with the half-
  Door state model) controlled by the activator. Resolves by
  toggling the locked/unlocked state of a chosen door half. Rooms/
  Doors substrate (per the broader Rooms/Doors tail in the inventory
  doc); **Rust side has no Rooms/Doors model today, see §4.3.**
* **`AddManaToPool`** at `src/mtg_bot/effects/generic/mana.py:30-80`.
  `requires_target() = False`. Fields: `produces:
  tuple[tuple[str, int], ...]` (color → count pairs) and
  `spend_restriction: str | None`. All-Fates Scroll's instance is
  `produces=(("any", 1),)` — one mana of any color, agent-chosen
  on resolve. Already bridge-supported per `cross_engine.py:7693`
  (reverse) + the mana-ability auto-wire at
  `cross_engine.py:14252` (forward — though for AA-list AAs, NOT
  for `aa.is_mana_ability=True`). Rust resolve at
  `cards.rs:12027` (`"add_mana_to_pool"` parse) + `cards.rs:18019`
  (to_pydict).
* **`DrawCardsByConditionMultiplier`** at
  `src/mtg_bot/effects/generic/draw_mill.py`. `requires_target() =
  False`. Fields: `condition: Condition` (e.g.
  `PerDifferentlyNamedLand()`), `description_fragment: str`.
  Resolves by counting `condition.count(state, activator)` and
  calling `state.draw_cards(activator, count)`. All-Fates Scroll
  uses the differently-named-land condition.

### 2.3 Rust substrate state (verified live at HEAD `dbbc1a41`)

| Primitive | File:line | Status |
|---|---|---|
| Multi-AA `CardDef.activated_abilities: Vec<ActivatedAbility>` | `rust/src/cards.rs` (Phase 1 substrate) | **EXISTS** (Phase 1 C1 substrate landed `Vec` from day one; the Python-side admit is the limiting factor, not the Rust side) |
| `ActivatedAbility.sorcery_speed: bool` | `rust/src/cards.rs` | **EXISTS** (parse arm + to_pydict arm already wired for triggered-ability + spell-effect sorcery-speed precedents; round-trips for AAs too — verify the parse arm reads `sorcery_speed` from the AA dict) |
| `ActivatedAbility.is_mana_ability: bool` | `rust/src/cards.rs` | **EXISTS** (round-21 mana-ability bridge auto-wire shipped a parse+to_pydict round-trip for the basic-land mana-ability slot at `cross_engine.py:14252`; verify the AA-list arm also accepts it) |
| `state_ops_actions.rs` cost-pay for AA[i] addressing | `rust/src/state_ops_actions.rs` | **EXISTS** (Phase 1 substrate addresses the AA by index in the `ActivateAbility` action's `ability_index` field; multi-AA fan-out at emit time is the only widen needed) |
| `state_ops_legal.rs::activate_ability_dict` emits one `ActivateAbility` action per AA per source | `rust/src/state_ops_legal.rs` | **EXISTS** (every code path that walks `def.activated_abilities` is already index-keyed) — multi-AA carriers fan out N actions per source, one per AA |
| `Effect::SearchLibraryForCard { filter_name, max_mv, may_fail }` | `rust/src/cards.rs:14965,18746` (per round-21 bridge closure) | **EXISTS** (filter_name="basic_land" already supported) |
| `Effect::AddManaToPool { color, count, ... }` | `rust/src/cards.rs:12027,18019` | **EXISTS** (round-21 mana-ability bridge slice; admits `produces=(("any", 1),)` shape via "any" color discriminator) |
| `Effect::CreateTokenCopyOfTargetCreatureYouControl` | `rust/src/cards.rs:13347,18791` | **PARTIAL — Rust parse + to_pydict + bridge reverse arm exist (per `cross_engine.py:7190`); the resolve arm and token-allocation site may need verification.** §4.1 audits. |
| `Effect::CopyTargetInstantOrSorceryYouControl` | `rust/src/state_ops_resolve.rs` | **DOES NOT EXIST** (Phase 4B-1 port — CR-707.2 spell-copy substrate. The most novel substrate of Phase 4.) |
| `Effect::ExileTargetCardFromGraveyard` | `rust/src/state_ops_resolve.rs` | **DOES NOT EXIST** (Phase 4C-1 port — note: this is the SINGLE-TARGET variant, distinct from `ExileAllGraveyards`'s zero-target shape; needs a per-player graveyard target fan-out arm — see §4.2) |
| `Effect::PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl` | `rust/src/state_ops_resolve.rs` | **DOES NOT EXIST** (Phase 4C-2 port; reads `exiled_with_source` slot — slot exists at `state.rs:122` per round-28 attach foundation; rider fields `grant_flying_counter` + `grant_subtype_and_pt` carry through the Effect payload) |
| `Effect::LockOrUnlockDoorOfTargetRoomYouControl` + Rooms/Doors `GameObject` model | `rust/src/state.rs` + `state_ops_resolve.rs` | **DOES NOT EXIST** (Phase 4D — the Rooms/Doors substrate is a Phase-4D-internal sub-substrate; carry the Door-half-locked state on the Room GameObject, port the toggle Effect) |
| `Effect::DrawCardsByConditionMultiplier { condition_tag, condition_args, ... }` | `rust/src/state_ops_resolve.rs` | **DOES NOT EXIST** (Phase 4E-2 port — uses the `(condition_tag, condition_args)` opaque-tuple codec already shipped for static-ability conditions per `cross_engine.py:14881`) |
| Multi-AA admit predicate widen (Python) | `src/mtg_bot/parity/trajectory.py:9240` (`if len(aas) != 1: return False`) | **DOES NOT EXIST** (Phase 4A widen — the keystone) |
| `sorcery_speed` AA-rider acceptance on bridge floor | `src/mtg_bot/parity/cross_engine.py:14701` (`if aa.sorcery_speed: return None`) | **DOES NOT EXIST** (Phase 4C/4D widen — the bridge floor currently rejects AAs with `sorcery_speed=True`; widen requires AA-side dict to carry `sorcery_speed: True` through Rust round-trip — Rust side already supports it for triggered abilities, verify AA arm) |
| `is_mana_ability` AA-rider acceptance on bridge floor | `src/mtg_bot/parity/cross_engine.py:14699` (`if aa.is_mana_ability: return None`) | **DOES NOT EXIST** (Phase 4E widen — same surface, different bool) |

**Cumulative substrate weight:**

* **Phase 4A (multi-AA admit):** Python-only — removes the
  `len(aas) != 1: return False` decline at `trajectory.py:9240`,
  replaces with a per-AA all-or-nothing walk. **NO Rust changes.**
  **NO new bridge arms.** Mirrors the token-AA Lander's all-or-
  nothing per-AA contract precedent (per Phase 2 §3.4 — "the safest
  contract is the latter, mirroring the token-AA Lander's all-or-
  nothing stance"). Required prerequisite for every later sub-phase.
* **Phase 4B (Mirrorpool):** 2 new Effect resolve arms
  (`CopyTargetInstantOrSorceryYouControl` — CR-707.2 spell-copy +
  `CreateTokenCopyOfTargetCreatureYouControl` may need resolve-arm
  audit; new Stack-push primitive for spell-copy + token allocation
  via printing-registry push). NO new state field — both copy
  effects use existing state slots (`state.stack` + printing
  registry).
* **Phase 4C (Ghost Vacuum):** 2 new Effect resolve arms
  (`ExileTargetCardFromGraveyard` + `PutEachCreatureCardExiledWith
  SourceOntoBattlefieldUnderYourControl`) + `sorcery_speed` AA-rider
  widen on the bridge floor + a new per-player-graveyard target fan-
  out arm in `state_ops_legal.rs::activate_ability_dict`.
* **Phase 4D (Keys to the House):** 1 new Effect resolve arm
  (`LockOrUnlockDoorOfTargetRoomYouControl`) + Rooms/Doors `GameObject`
  state model + Room-target fan-out arm in
  `state_ops_legal.rs::activate_ability_dict`. **NOTE:** the
  SearchLibraryForCard Effect (AA[0]) is already wired; ONLY the
  rooms/doors substrate is new at the Effect layer. **Heaviest
  state-surface change of Phase 4 — Rooms/Doors model has zero
  prior Rust footprint.**
* **Phase 4E (All-Fates Scroll):** 1 new Effect resolve arm
  (`DrawCardsByConditionMultiplier`) + `is_mana_ability` AA-rider
  widen on the bridge floor. **NOTE:** AddManaToPool (AA[0]) is
  already wired; the substrate-novel part is the
  condition-multiplier draw effect + the mana-ability AA-rider
  widen.

### 2.4 Co-bundling audit — multi-AA admit substrate keystone

Phase 4A's multi-AA admit-predicate widen is the **shared
prerequisite** for every Phase 4 sub-phase. Without it, no multi-AA
printing admits at all — sub-phases 4B-4E each need the multi-AA
gate as their first dependency.

| Sub-phase | Depends on Phase 4A? | Depends on other sub-phases? |
|---|---:|---|
| 4A (multi-AA admit) | (self) | NO |
| 4B (Mirrorpool) | YES | NO |
| 4C (Ghost Vacuum) | YES | NO |
| 4D (Keys to the House) | YES | NO |
| 4E (All-Fates Scroll) | YES | NO |

Phase 4A is the single shared prerequisite; B/C/D/E are mutually
independent. Phase 4A can land in cycle 1; subsequent sub-phases can
run in parallel on independent worker lanes.

### 2.5 Phase 4 sub-phase ordering

Sub-phases ordered by **substrate weight × cycle independence ×
substrate-reuse leverage**:

1. **Phase 4A first (multi-AA admit substrate)** — the keystone.
   Python-only, ~2 cycles, ZERO Rust. Every subsequent sub-phase
   depends on it. NOT a card-FLIP cycle — substrate-only landing.
2. **Phase 4E next (All-Fates Scroll)** — small. The Effect surface
   is one new variant (`DrawCardsByConditionMultiplier`); the
   AA-rider widen is the `is_mana_ability` flag (single-line bridge
   floor change). Lands first as substrate-validation: confirms the
   multi-AA admit gate from 4A admits a real card under the smallest
   possible additional substrate. **First FLIP of the wave.**
3. **Phase 4C next (Ghost Vacuum)** — two new Effects but share the
   `exiled_with_source` slot semantics (produce-then-consume).
   Sorcery-speed AA-rider widen is independent + reused by 4D.
4. **Phase 4D next (Keys to the House)** — Rooms/Doors substrate is
   the heaviest state-surface change of Phase 4, but the
   SearchLibraryForCard half is pre-wired; lands after 4C so the
   sorcery-speed AA-rider widen is already validated.
5. **Phase 4B last (Mirrorpool)** — heaviest by Effect count (two
   new copy effects in different copy-machinery families, one of
   which — CR-707.2 spell-copy — is the most novel substrate of
   Phase 4). Lands last so multi-AA + sorcery-speed + Rooms/Doors
   are all validated baselines.

Each sub-phase post-4A is **independent** — no admit set in 4C
depends on 4B's substrate, and no Rust slice in 4D depends on
either. The sequencing recommendation is engineering-discipline
ordering (smallest novel-substrate first to validate the campaign
shape), not a substrate-dependency ordering.

---

## 3. Out of scope (Phase 5 / N)

Phase 4 retains every Phase 1 + 1.5 + 2 + 3 out-of-scope clause
unchanged. Specifically out-of-scope of Phase 4:

### 3.1 Haunted Screen (n_aa=3, `activate_only_once` + `Sequence` effect)

Haunted Screen has 3 AAs (two `AddNManaOfChosenColor` of different
shapes + a third `activate_only_once`-gated `Sequence` effect that
chains two sub-effects). The `activate_only_once` AA-rider is
Phase N; the `Sequence` Effect class is a composite that wraps
multiple sub-effects and needs its own substrate widen. **Phase 5+**
once both riders + Sequence land. Co-bundling with Phase 4 would
add three orthogonal substrates to a single Phase doc, which the
Phase 3 "different orthogonal Effects each in their own sub-cycle"
precedent rejected.

### 3.2 The Eternity Elevator (Spacecraft, station-threshold-adjacent)

The Eternity Elevator has 2 AAs but its `AddChargeCounterManaOf
ChosenColor` AA[1] is structurally tied to the Spacecraft station-
threshold substrate. The card is the last remaining Spacecraft
carrier in the inventory's Spacecraft row. **Phase 5+** — bundles
cleaner with the Spacecraft Phase 4+ tail than with the Carrier-AA
multi-AA wave.

### 3.3 X-pip mana costs (Phase N)

Every Phase 1-3 cost-gate clause STAYS in Phase 4 — colored / hybrid /
X-pip mana costs decline. Note: Mirrorpool's `{C}` is colorless-
generic per the parser (folds into `ManaCost.generic`), NOT colored,
so it admits unchanged.

### 3.4 `pay_life` cost rider (Phase N)

Phase 4 keeps `cost.pay_life > 0: return False` at the cost-gate.
No Phase 4 carrier uses `pay_life`.

### 3.5 `activate_only_once` AA-rider (Phase N)

Phase 4 keeps `aa.activate_only_once: return None` at the bridge
floor. Haunted Screen's AA[2] uses this rider — Phase 5+.

### 3.6 `tier_threshold` / `room_half` / `cost_reductions` AA-riders (Phase N)

Phase 4 keeps every Phase 1-3 AA-rider decline at the bridge floor
except `sorcery_speed` (widened by 4C/4D) and `is_mana_ability`
(widened by 4E).

### 3.7 BecomeLandCreatureUEOT-with-rider / Equipment cluster / Sliver Overlord / Pinnacle Starcage (Phase N)

Phase 4 does NOT touch any of these. Per Phase 2 §3.3 / §3.7 / §3.8 +
Phase 3 §3.3.

### 3.8 Replacement-effect interactions on the new zone moves (Phase N)

Phase 4B (spell-copy → stack), 4C (graveyard → exile + exile → bf),
4D (room-half lock/unlock — non-zone-move), 4E (library → hand) each
touch a zone-move primitive or stack push. Replacement effects (CR
614) on those zone moves (e.g. "if a creature would enter the
battlefield, it enters tapped instead" — Frilled Mystic shape) are
NOT modeled in the minimum Phase 4 semantics. None of the EoE
printings in the affected pool fire such replacement effects on
these transitions in a way that breaks the per-card probes; this
mirrors Phase 3 §3.4's documented simplification.

### 3.9 Mirrorpool spell-copy: cross-controller copy targeting (Phase N)

Mirrorpool AA[0]'s text reads "Copy target instant or sorcery YOU
CONTROL" — the activator can only copy their own spells. The Python
`legal_targets()` walk enforces this. The Rust port mirrors the
"controlled by activator" filter exactly; copies of OPPONENTS' spells
(Twincast / Reverberate shape) are NOT modeled in Phase 4.

### 3.10 Mirrorpool token-copy: legendary supertype suppression (Phase N)

CR 707.5 specifies that token copies of permanents do NOT carry the
legendary supertype by default unless the printing-being-copied
specifies a token copy retaining legendary. Mirrorpool AA[1]'s
`CreateTokenCopyOfTargetCreatureYouControl` instance is the bare
shape — copies inherit the printing's name + types but the legendary-
supertype suppression for token copies is a CR-707.5 sub-rule. The
substrate models the bare token-copy contract; any printing-specific
legendary-suppression edge case is Phase N.

### 3.11 Rooms/Doors full state model (Phase 5+)

Phase 4D ports the MINIMUM Rooms/Doors substrate: a per-Room
Door-half-locked bool slot + the toggle Effect resolve. Other Rooms-
specific behaviors (entering-the-Room triggers, the "unlock both
halves wins" CR-715 win-condition, the per-half mana cost / sorcery-
speed Door-unlock priority) are NOT modeled. Keys to the House's
Effect is the toggle ONLY; full Rooms gameplay is Phase 5+.

---

## 4. Rust-side spec

Phase 4 ships **five new `Effect` variants** (CopyTarget
InstantOrSorcery + ExileTargetCardFromGraveyard + PutEachCreatureCardExiled
WithSourceOntoBattlefieldUnderYourControl + LockOrUnlockDoorOfTargetRoom
YouControl + DrawCardsByConditionMultiplier) plus an audit-confirm-or-port
arm for `CreateTokenCopyOfTargetCreatureYouControl` plus the Rooms/
Doors `GameObject` state model plus **three new target fan-out
arms** in `state_ops_legal.rs::activate_ability_dict` (graveyard-
single-target + stack-target + Room-target) plus a sorcery-speed AA
emit / parse audit (no new arm — verify existing).

Each sub-phase's slice is disjoint.

### 4.1 Phase 4B — Mirrorpool's two copy AAs (HEAVY)

#### 4.1.1 `Effect::CopyTargetInstantOrSorceryYouControl` (CR-707.2 spell-copy)

**Files:**
* `rust/src/cards.rs` — Effect enum + parse arm + to_pydict arm.
* `rust/src/state_ops_resolve.rs` — resolve arm.
* `rust/src/state_ops_legal.rs::activate_ability_dict` — new stack-
  target fan-out arm.

**Semantics — `CopyTargetInstantOrSorceryYouControl`** (CR 707.2 —
copy of a spell; resolves but never gets cast):

1. Target a `StackItem` such that:
   * `stack_item.controller_id == activator_controller_id`,
   * `stack_item.kind == Spell` (NOT activated/triggered),
   * `state.registry.get(stack_item.printing_id).is_instant ||
     .is_sorcery`.
2. On resolve:
   * If the target left the stack since activation, fizzle silently
     (CR 608.2b target-legality re-check).
   * Else allocate a new `StackItem` clone of the target:
     - SAME printing_id (no registry push needed — points at the
       original printing).
     - SAME targets as the original spell's stack entry (or
       activator-chosen new targets — Phase 4B-1 simplification:
       use the same targets, agent-chooses-new is Phase N).
     - SAME modes / X / kicker selections.
     - `controller_id = activator_controller_id`.
     - `is_copy = true` (new field on StackItem, mirrors Python's
       `StackItem.is_copy`; affects CR 707.10 — copies can't be
       countered by "counter target spell" with restrictions; but
       since "counter target spell" still counters them, this flag
       is mostly bookkeeping).
   * Push to top of stack via `state.stack.push(new_stack_item)`.
   * **DO NOT** dispatch `Event::SpellCast` — copies aren't cast.
   * Resolution proceeds normally via the existing stack-resolution
     machinery — the copy resolves like any other stack item.

**Phase 4B-1 Rust spec:**

```rust
// In Effect enum (cards.rs):
CopyTargetInstantOrSorceryYouControl,

// In parse_effect (cards.rs):
"copy_target_instant_or_sorcery_you_control" =>
    Effect::CopyTargetInstantOrSorceryYouControl,

// In to_pydict (cards.rs):
Effect::CopyTargetInstantOrSorceryYouControl => {
    py_dict.set_item(
        "kind", "copy_target_instant_or_sorcery_you_control",
    )?;
}

// In resolve dispatch (state_ops_resolve.rs): see semantics above.
```

**Target enumeration in `state_ops_legal.rs::activate_ability_dict`.**
New stack-target fan-out arm: for an AA whose Effect is
`CopyTargetInstantOrSorceryYouControl`, enumerate every stack item
matching `controller_id == activator AND (registry-fetch is_instant
OR is_sorcery)` and emit one `ActivateAbility` action per eligible
target. **Sibling of the existing battlefield-target fan-out at
`state_ops_legal.rs:3408-3505`, but reads `state.stack` instead of
`state.battlefield`.**

**StackItem.is_copy slot.** Phase 4B-1 may need a new `is_copy: bool`
field on `StackItem`. **Audit required:** check whether Rust's
`StackItem` already carries this slot (Python's `StackItem.is_copy`
has been in place since the spell-copy substrate was scoped). If
not, add the field with `default = false`; the fingerprint serializer
emits `false` as the default-state (zero-bytes-on-wire) so pre-
existing snapshots stay byte-identical.

#### 4.1.2 `Effect::CreateTokenCopyOfTargetCreatureYouControl` (audit)

**Files (audit + possibly resolve-arm port):**
* `rust/src/cards.rs:13347` (parse), `cards.rs:18791` (to_pydict) —
  EXISTS.
* `rust/src/state_ops_resolve.rs` — **AUDIT REQUIRED:** verify a
  resolve arm exists. Cross-engine bridge reverse arm exists at
  `cross_engine.py:7190`; the round-21+ Rust variant was wired for
  parse + to_pydict but the resolve arm may or may not have landed.
* `rust/src/state_ops_legal.rs::activate_ability_dict` — verify
  battlefield-Creature target fan-out arm exists for this Effect.

**Semantics (audit-confirmed):**

1. Target a battlefield `GameObject` with `printing.is_creature ==
   true` AND `controller_id == activator_controller_id`.
2. On resolve:
   * Fizzle silently if target left bf since activation (CR 608.2b).
   * Snapshot the target's printing.
   * Push a new `CardPrinting` into the registry derived from the
     target's: same name + card_types + subtypes + supertypes + base_pt
     + abilities (mana cost / spell-side fields are dropped per CR
     707.5).
   * Allocate a new `GameObject` with `is_token=true, owner =
     activator, controller = activator, printing_id = new_id`.
   * Push to `state.battlefield`, dispatch `Event::EntersBattlefield`.

**Phase 4B-2 Rust spec:** if the resolve arm exists, no new code; if
not, ports the resolve arm.

**Re-use of Phase 3C primitive.** Phase 3C ships the "push a new
CardPrinting derived from a battlefield permanent's printing into
the registry" primitive (the registry-push step). Phase 4B-2 reuses
this primitive directly. Per Phase 3 §2.4 + §9.4: Phase 3C left this
primitive Phase-4 reusable; Phase 4B-2 collects.

### 4.2 Phase 4C — Ghost Vacuum's two exile-pair AAs

#### 4.2.1 `Effect::ExileTargetCardFromGraveyard` (single-target)

**Files:**
* `rust/src/cards.rs` — Effect enum + parse arm + to_pydict arm.
* `rust/src/state_ops_resolve.rs` — resolve arm.
* `rust/src/state_ops_legal.rs::activate_ability_dict` — new
  per-player-graveyard single-target fan-out arm.

**Semantics — `ExileTargetCardFromGraveyard`:**

1. Target a `GameObject` with `obj.zone == ZONE_GRAVEYARD` (either
   player's graveyard — Ghost Vacuum can exile from any graveyard
   per its printed "target card from a graveyard").
2. On resolve:
   * Fizzle silently if target moved (CR 608.2b).
   * Move target from graveyard → exile (the SAME player's exile —
     the card's owner). Stamp `obj.zone = ZONE_EXILE`,
     `obj.exiled_with_source = Some(source.id)` (CR 400.7 + Phase
     3 §4.1 zone-move per-object reset), `obj.tapped = false`,
     etc. (the standard per-zone reset).

**Phase 4C-1 Rust spec:**

```rust
// In Effect enum (cards.rs):
ExileTargetCardFromGraveyard,

// In parse_effect (cards.rs):
"exile_target_card_from_graveyard" =>
    Effect::ExileTargetCardFromGraveyard,

// In to_pydict (cards.rs):
Effect::ExileTargetCardFromGraveyard => {
    py_dict.set_item("kind", "exile_target_card_from_graveyard")?;
}

// In resolve dispatch (state_ops_resolve.rs): see semantics above.
```

**Target enumeration in `state_ops_legal.rs::activate_ability_dict`.**
New fan-out arm: for an AA whose Effect is
`ExileTargetCardFromGraveyard`, enumerate every GameObject across
BOTH players' graveyards (any zone == GRAVEYARD object) and emit one
`ActivateAbility` action per eligible target. **Sibling of the
Phase-2a graveyard-target fan-out for
`ReturnTargetLandFromGraveyardToHand` (single-player graveyard
walk), but iterates BOTH players' graveyards.**

#### 4.2.2 `Effect::PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl`

**Files:**
* `rust/src/cards.rs` — Effect enum + parse arm + to_pydict arm.
* `rust/src/state_ops_resolve.rs` — resolve arm.

**Semantics:**

1. NO target (mass effect — the source itself drives enumeration).
2. On resolve:
   * Walk every player's `exile`. For every `GameObject` with
     `obj.exiled_with_source == Some(source.id) AND
     registry.get(obj.printing_id).is_creature`:
     - Move to `state.players[activator_idx].battlefield`.
     - Stamp `obj.controller = activator`,
       `obj.tapped = false`, `obj.summoning_sick = true`,
       `obj.exiled_with_source = None`, etc. (per-zone reset).
     - If the Effect's `grant_flying_counter=true`, stamp a flying
       counter (per the Spirit-rider semantics).
     - If the Effect's `grant_subtype_and_pt=Some(("Spirit", 1,
       1))`, layer a Spirit subtype + 1/1 base P/T via the
       continuous-effect machinery.
     - Dispatch `Event::EntersBattlefield(obj.id)` per CR 603.6a.

**Phase 4C-2 Rust spec:**

```rust
// In Effect enum (cards.rs):
PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl {
    grant_flying_counter: bool,
    grant_subtype_and_pt: Option<(String, i32, i32)>,
},

// In parse_effect (cards.rs):
"put_each_creature_card_exiled_with_source_onto_battlefield_under_your_control" => {
    let grant_flying_counter = dict.get_item("grant_flying_counter")?
        .map(|v| v.extract::<bool>())
        .transpose()?
        .unwrap_or(false);
    let grant_subtype_and_pt = dict.get_item("grant_subtype_and_pt")?
        .map(|v| {
            let tup: (String, i32, i32) = v.extract()?;
            Ok::<_, PyErr>(tup)
        })
        .transpose()?;
    Effect::PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl {
        grant_flying_counter, grant_subtype_and_pt,
    }
},

// In to_pydict (cards.rs):
Effect::PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl {
    grant_flying_counter, grant_subtype_and_pt,
} => {
    py_dict.set_item(
        "kind",
        "put_each_creature_card_exiled_with_source_onto_battlefield_under_your_control",
    )?;
    if *grant_flying_counter {
        py_dict.set_item("grant_flying_counter", true)?;
    }
    if let Some((subtype, p, t)) = grant_subtype_and_pt {
        py_dict.set_item(
            "grant_subtype_and_pt",
            (subtype, *p, *t),
        )?;
    }
}

// In resolve dispatch (state_ops_resolve.rs): see semantics above.
```

**No new state field** — `exiled_with_source: Option<u32>` already
exists on every `GameObject` per round-28 attach foundation
(`state.rs:122`). Phase 4C-1 stamps it (producer); 4C-2 reads it
(consumer).

**Target enumeration.** No new arm needed — the Effect has no
target. The existing else-arm in `state_ops_legal.rs::legal_decisions`
for no-target AAs fires unchanged.

### 4.3 Phase 4D — Keys to the House's Rooms/Doors substrate

**Files (heaviest state-surface change of Phase 4):**
* `rust/src/state.rs` — new `GameObject.door_states:
  Option<DoorStates>` slot (or equivalent — per-Room locked-bool
  bitmask on Room GameObjects).
* `rust/src/cards.rs` — Effect enum + parse arm + to_pydict arm
  for `LockOrUnlockDoorOfTargetRoomYouControl`.
* `rust/src/state_ops_resolve.rs` — resolve arm.
* `rust/src/state_ops_legal.rs::activate_ability_dict` — new Room-
  target fan-out arm.

**Semantics — `LockOrUnlockDoorOfTargetRoomYouControl`:**

1. Target a battlefield `GameObject` with the `Room` subtype AND
   `controller_id == activator_controller_id`. (Walks
   `state.battlefield` for room-typed permanents.)
2. On resolve:
   * Fizzle silently if target left bf (CR 608.2b).
   * Toggle the chosen door-half lock state via
     `target.door_states.toggle(half_idx)` — the half is agent-
     chosen at activation time (NOT a separate target slot; rides
     on the action-dict's `mode` / `door_half_idx` slot).
   * Dispatch `Event::DoorStateChanged` (Phase 5+ Rooms gameplay
     triggers); Phase 4D ships the bare toggle without event
     plumbing.

**Phase 4D Rust spec — Rooms/Doors state model:**

```rust
// In state.rs - new field on GameObject:
pub struct GameObject {
    // ... existing fields ...
    /// **Carrier-AA Phase 4D — Rooms/Doors locked-state slot.**
    /// `Some(states)` on Room printings (CR-715), `None` on
    /// every other GameObject. `states` is a bitmask of the
    /// per-Door-half locked bool (Phase 4D ships 2-bit width
    /// for the 2-half Room shape; extend if a future Room
    /// shape has >2 halves).
    ///
    /// Cleared (reset to `None`) on every zone change (CR
    /// 400.7 per-object state reset) — Door states are a
    /// battlefield-only concept.
    pub door_states: Option<u8>,
}

// In Effect enum (cards.rs):
LockOrUnlockDoorOfTargetRoomYouControl,

// In parse_effect (cards.rs):
"lock_or_unlock_door_of_target_room_you_control" =>
    Effect::LockOrUnlockDoorOfTargetRoomYouControl,

// In to_pydict (cards.rs):
Effect::LockOrUnlockDoorOfTargetRoomYouControl => {
    py_dict.set_item(
        "kind", "lock_or_unlock_door_of_target_room_you_control",
    )?;
}

// In resolve dispatch (state_ops_resolve.rs): see semantics above.
```

**Target enumeration in `state_ops_legal.rs::activate_ability_dict`.**
New Room-target fan-out arm: enumerate every battlefield GameObject
with `controller_id == activator AND registry.get(obj.printing_id)
.subtypes.contains("Room")` and emit one `ActivateAbility` action
per eligible target × per door-half (2× fan-out per Room).
**Sibling of the existing battlefield-target fan-out, with an
additional inner-loop over door halves.**

**Zone-change reset hookup.** The per-zone-change `obj.zone =
NEW_ZONE` sweep across `state_ops_actions.rs` MUST also clear
`door_states = None`. **Audit required**: every zone-change-stamp
call site in Rust. Same pattern as Phase 3C's `original_printing_id`
audit and Phase 1's `regeneration_shield` audit.

**SearchLibraryForCard (AA[0]) is pre-wired.** Per `cards.rs:14965`
(parse) + `cards.rs:18746` (to_pydict) + `cross_engine.py:5325`
(reverse) + Rust resolve. The filter_name="basic_land" filter is
already supported. **NO Rust changes needed for Keys to the House's
AA[0].** The Phase 4D Rust slice is purely the Rooms/Doors
substrate.

### 4.4 Phase 4E — All-Fates Scroll's mana-ability + condition-multiplier draw

#### 4.4.1 `Effect::AddManaToPool` (pre-wired)

Per `cards.rs:12027` (parse) + `cards.rs:18019` (to_pydict) +
`cross_engine.py:7697` (reverse) + Rust resolve. The
`produces=(("any", 1),)` shape (one mana of any color) is supported
via the "any" color discriminator. **NO Rust changes needed for
All-Fates Scroll's AA[0].**

#### 4.4.2 `Effect::DrawCardsByConditionMultiplier`

**Files:**
* `rust/src/cards.rs` — Effect enum + parse arm + to_pydict arm.
* `rust/src/state_ops_resolve.rs` — resolve arm.

**Semantics:**

1. NO target. On resolve:
   * Compute the multiplier via
     `static_self_bonus_condition_matches(condition_tag,
     condition_args, state, activator)` — the SAME `(tag, args)`
     opaque-tuple codec the static-ability layer shipped at round-81
     (per `cross_engine.py:14881`). The new condition tag
     `"per_differently_named_land"` would extend the dispatch table.
   * Call `state.draw_cards(activator_idx, count)` — existing
     primitive.

**Phase 4E-2 Rust spec:**

```rust
// In Effect enum (cards.rs):
DrawCardsByConditionMultiplier {
    condition_tag: String,
    condition_args: Vec<i32>,
    description_fragment: String,
},

// In parse_effect (cards.rs):
"draw_cards_by_condition_multiplier" => {
    let condition_tag = dict.get_item("condition_tag")?
        .ok_or_else(|| /* error */)?
        .extract::<String>()?;
    let condition_args = dict.get_item("condition_args")?
        .map(|v| v.extract::<Vec<i32>>())
        .transpose()?
        .unwrap_or_default();
    let description_fragment = dict.get_item("description_fragment")?
        .map(|v| v.extract::<String>())
        .transpose()?
        .unwrap_or_default();
    Effect::DrawCardsByConditionMultiplier {
        condition_tag, condition_args, description_fragment,
    }
}

// In to_pydict (cards.rs):
Effect::DrawCardsByConditionMultiplier {
    condition_tag, condition_args, description_fragment,
} => {
    py_dict.set_item("kind", "draw_cards_by_condition_multiplier")?;
    py_dict.set_item("condition_tag", condition_tag)?;
    if !condition_args.is_empty() {
        py_dict.set_item("condition_args", condition_args)?;
    }
    if !description_fragment.is_empty() {
        py_dict.set_item(
            "description_fragment", description_fragment,
        )?;
    }
}

// In resolve dispatch (state_ops_resolve.rs): see semantics above.
```

**New condition tag — `"per_differently_named_land"`.** Phase 4E-2
extends the static-ability condition dispatch table at
`state_ops_combat::static_self_bonus_condition_matches` (per
`cross_engine.py:14897-14917` for the existing tags) with a new
tag that counts `state.players[activator_idx].battlefield` for
GameObjects with `registry.get(obj.printing_id).is_land` and
returns the cardinality of the set of distinct `printing.name`
values. (Or equivalent — the condition computes a count, not a
boolean; the dispatcher returns the count directly.) **Audit
required**: the existing condition codec returns a BOOLEAN
(`condition_matches`); Phase 4E-2 may need a parallel
`condition_count(tag, args, state, activator) -> u32` dispatcher
that returns the count rather than a bool. Add this parallel
function rather than overloading the existing one.

### 4.5 No new cost-shape Rust changes across Phase 4

* Phase 4B's `{N}{C}, {T}, Sac:` cost is the existing
  `{N}, {T}, Sac:` cost shape (Phase 2a). `{C}` pips fold into
  generic — verified live for Mirrorpool.
* Phase 4C's `{T}` (AA[0]) + `{N}, {T}, Sac:` (AA[1]) are both in
  the Phase 1.5a + Phase 2a cost shapes.
* Phase 4D's `{N}, {T}, Sac:` (both AAs) is in the Phase 2a cost
  shape.
* Phase 4E's `{T}` (AA[0]) + `{N}, {T}, Sac:` (AA[1]) is the same
  pair as 4C's.

**All four sub-phases inherit fully-wired Rust cost shapes; the new
Rust slices are pure Effect ports + (4B) stack-target fan-out + (4C)
graveyard-single-target fan-out + (4D) Room-target fan-out + (4D)
Rooms/Doors GameObject state + (4E) condition-multiplier opaque-
tuple codec extension.**

### 4.6 AA-rider acceptance audit (Rust side — already supports)

**`sorcery_speed: bool` field on `ActivatedAbility`.** Per round-21+
the Rust ActivatedAbility struct already carries the field;
triggered-ability + spell-effect parse arms read it. The AA arm at
`parse_activated_ability` reads `dict.get_item("sorcery_speed")` —
verify the optional read defaults to `false` if absent. **AUDIT
REQUIRED — no spec text yet for the AA arm's behavior under a
`sorcery_speed=true` AA.** If the read is missing, add it as a 1-line
parse arm extension. The to_pydict arm mirrors.

**`is_mana_ability: bool` field on `ActivatedAbility`.** Same audit
shape. The Rust side has been able to round-trip mana-ability AAs
since the round-21 mana-ability bridge slice (basic-land auto-wire
at `cross_engine.py:14252`). Verify the AA list parse arm reads
the bool — likely already supported.

**`activate_only_once`, `tier_threshold`, `room_half`,
`cost_reductions`** — Phase 4 keeps these AA-riders Phase N. Rust
side may or may not support; not part of Phase 4 scope.

---

## 5. Python bridge spec

### 5.1 Effect-class gate widen across Phase 4

**File:** `src/mtg_bot/parity/trajectory.py`,
`_carrier_aa_phase_1_effect_classes` at line 8953. The accessor name
keeps the Phase-1 prefix for back-compat (per Phase 2 §5.2). Each
sub-phase appends per its Effect-class deliverable.

```python
def _carrier_aa_phase_1_effect_classes() -> "frozenset[type]":
    # Phase 4 widens the admit set to TWELVE Effect classes —
    # adds Mirrorpool's two copy effects, Ghost Vacuum's two
    # exile-pair effects, Keys to the House's two effects,
    # All-Fates Scroll's two effects. (Phase 3C C2 adds
    # BecomesCopyOfTargetLand; this list assumes that lands first.)
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
        ExileTargetCardFromGraveyard,
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    )
    from mtg_bot.effects.generic.become_type import (
        BecomesCopyOfTargetLand,
    )
    from mtg_bot.effects.generic.stack_control import (
        CopyTargetInstantOrSorceryYouControl,
    )
    from mtg_bot.effects.generic.tokens import (
        CreateTokenCopyOfTargetCreatureYouControl,
    )
    from mtg_bot.effects.generic.search import SearchLibraryForCard
    from mtg_bot.effects.generic.misc import (
        LockOrUnlockDoorOfTargetRoomYouControl,
    )
    from mtg_bot.effects.generic.mana import AddManaToPool
    from mtg_bot.effects.generic.draw_mill import (
        DrawCardsByConditionMultiplier,
    )
    return frozenset({
        # Phase 1-3:
        RegenerateTargetCreature,
        UntapTargetLand,
        ReturnTargetLandFromGraveyardToHand,
        PutBasicLandFromHandOntoBattlefieldTapped,
        ExileTargetAttackingCreatureUntilEndStep,
        ExileAllGraveyards,
        BecomesCopyOfTargetLand,
        # Phase 4B (Mirrorpool):
        CopyTargetInstantOrSorceryYouControl,
        CreateTokenCopyOfTargetCreatureYouControl,
        # Phase 4C (Ghost Vacuum):
        ExileTargetCardFromGraveyard,
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
        # Phase 4D (Keys to the House):
        SearchLibraryForCard,
        LockOrUnlockDoorOfTargetRoomYouControl,
        # Phase 4E (All-Fates Scroll):
        AddManaToPool,
        DrawCardsByConditionMultiplier,
    })
```

Each Phase-4 sub-phase appends ITS Effect classes in a separate
Python-only cycle; the frozenset grows by the deliverable count per
sub-phase.

### 5.2 Phase 4A — multi-AA admit predicate widen (the keystone)

**File:** `src/mtg_bot/parity/trajectory.py`,
`_printing_is_bridge_simple_carrier_aa_land` at line 9171 (and a
SIBLING `_printing_is_bridge_simple_carrier_aa_artifact` per §5.3).

**The widen:**

```python
# Phase 4A: multi-AA admit substrate — every AA must independently
# pass _aa_is_phase1_sub_shape_a. The all-or-nothing contract
# mirrors the token-AA Lander's per-AA all-admit-or-decline stance
# (per Phase 2 §3.4).
aas = tuple(printing.activated_abilities or ())
if len(aas) == 0:
    return False  # not a carrier
# Phase 4A widens from len(aas) != 1 to admit any positive count.
# Every AA must independently pass the sub-shape-A predicate.
for aa in aas:
    if not _aa_is_phase1_sub_shape_a(aa):
        return False
return True
```

**Critical contract preservation.** The widen is strictly additive on
the `len(aas)` axis; every per-AA gate (`_aa_is_phase1_sub_shape_a`)
stays bit-identical. A printing with 3 AAs whose AA[2] fails the
per-AA predicate still declines under the all-or-nothing contract
(per §2.4 of Phase 2's design rationale — the safest contract).

**Bridge floor update.** The `_python_aa_to_safe_dict` floor already
operates per-AA (it serializes ONE AA at a time, not a list). The
multi-AA admit calls it for each AA in turn (already the case for
the single-AA contract); no change to the floor itself for the multi-
AA widen.

**No silent auto-grow.** Phase 4A's widen INVERTS in-place the
existing decline-only-on-multi-AA pin (the Phase-1/1.5/2/3 walk
asserts admit set is `{Swarmyard, Deserted Temple, Petrified Field,
Terrain Generator, Mystifying Maze, Scavenger Grounds, Thespian's
Stage}`). Phase 4A alone does NOT add any card to the admit set —
all multi-AA Phase-4 carriers still decline at the per-AA Effect-
class teeth, the AA-rider teeth (sorcery_speed / is_mana_ability),
and (4D) the Rooms/Doors substrate teeth. Phase 4A's admit-set
delta: **+0 cards** (substrate-only landing). The +4 cards land via
4B/4C/4D/4E.

### 5.3 Phase 4A.2 — Artifact admit-predicate sibling

**File:** `src/mtg_bot/parity/trajectory.py` — new function
`_printing_is_bridge_simple_carrier_aa_artifact` (sibling of
`_printing_is_bridge_simple_carrier_aa_land`).

3 of the 4 Phase-4 cards are Artifact, not Land. The existing admit
predicate at `trajectory.py:9201` declines anything but Land. Phase
4A adds an Artifact-typed sibling predicate:

```python
def _printing_is_bridge_simple_carrier_aa_artifact(printing) -> bool:
    """Sibling of _printing_is_bridge_simple_carrier_aa_land for
    Carrier-AA Artifact carriers (Ghost Vacuum / Keys to the House /
    All-Fates Scroll pilot trio + future Artifact Carrier-AA carriers).

    Phase 4A.2 widen — opens the admit gate to single-card-type
    Artifact carriers with the same per-AA + bridge-floor gates as
    the Land sibling, plus the multi-AA widen of §5.2.

    Phase 4 admits NO Equipment subtype (Equipment cluster is Phase
    N per Phase 2 §3.3); admit predicate must reject any printing
    with non-empty subtypes that overlap with Equipment / Vehicle /
    other rider clusters.
    """
    if "Artifact" not in printing.card_types:
        return False
    extra_card_types = tuple(
        t for t in printing.card_types if t != "Artifact"
    )
    if extra_card_types:
        return False  # no Artifact-Creature overlap, no Spacecraft
    # Equipment / Vehicle / Spacecraft / Food / Treasure subtypes
    # are Phase N — strict empty-subtypes guard for Phase 4A.
    if printing.subtypes:
        return False
    # Same per-printing rider guards as the Land sibling:
    # ... (verbatim copy from _printing_is_bridge_simple_carrier_aa_land
    # body for the keyword / triggered / static / spell_effect /
    # warp_cost / kicker_cost / impending_cost / room_halves /
    # loyalty / cost_reductions / external_cost_reductions /
    # station_threshold / dynamic_pt_formula / ward_cost /
    # power / toughness guards) ...
    # Plus the §5.2 multi-AA widen for the per-AA walk.
    aas = tuple(printing.activated_abilities or ())
    if len(aas) == 0:
        return False
    for aa in aas:
        if not _aa_is_phase1_sub_shape_a(aa):
            return False
    return True
```

**Top-level admit dispatcher.** A new helper
`_printing_is_bridge_simple_carrier_aa_any` returns True iff the
printing is either a Land admit or an Artifact admit:

```python
def _printing_is_bridge_simple_carrier_aa_any(printing) -> bool:
    return (
        _printing_is_bridge_simple_carrier_aa_land(printing)
        or _printing_is_bridge_simple_carrier_aa_artifact(printing)
    )
```

The OR-chain at `_filter_deck_to_bridge_supported`
(`trajectory.py:11524` + `13444`) updates to call the new dispatcher.

### 5.4 Phase 4B — Mirrorpool's two copy effects + bridge arms

**File:** `src/mtg_bot/parity/cross_engine.py`.

`_python_aa_to_safe_dict` forward arm at line 14810+:

```python
elif isinstance(effect, CopyTargetInstantOrSorceryYouControl):
    effect_dict = {
        "kind": "copy_target_instant_or_sorcery_you_control",
    }
elif isinstance(effect, CreateTokenCopyOfTargetCreatureYouControl):
    # Mirrorpool AA[1] — bare-shape token copy
    # (additional_subtype=None on the live printing). The bridge
    # emits the additional_subtype field iff non-None.
    effect_dict = {
        "kind": "create_token_copy_of_target_creature_you_control",
    }
    if effect.additional_subtype is not None:
        effect_dict["additional_subtype"] = str(
            effect.additional_subtype,
        )
```

`_ta_dict_to_python_effect` reverse arm — the
`CreateTokenCopyOfTargetCreatureYouControl` arm at
`cross_engine.py:7190` EXISTS; add a sibling for
`CopyTargetInstantOrSorceryYouControl`:

```python
if kind == "copy_target_instant_or_sorcery_you_control":
    from mtg_bot.effects.generic.stack_control import (
        CopyTargetInstantOrSorceryYouControl,
    )
    return CopyTargetInstantOrSorceryYouControl()
```

The reverse arm for `CreateTokenCopyOfTargetCreatureYouControl`
EXISTS at `cross_engine.py:7190` — verify it accepts the optional
`additional_subtype` kwarg (round-trip stays byte-equal).

### 5.5 Phase 4C — Ghost Vacuum's two exile effects + bridge arms + sorcery_speed widen

`_python_aa_to_safe_dict` AA-rider gate widen at line 14701:

```python
# Phase 4C widen — sorcery_speed AA-rider admitted on the bridge
# floor. Was: `if aa.sorcery_speed: return None`.
if aa.sorcery_speed:
    # Phase 4C: admit sorcery_speed AA-rider. Emit the flag on the
    # AA dict so Rust's parse arm captures it.
    pass  # fall through to cost+effect serialization
# (the AA dict emitted below carries `"sorcery_speed": True` for
# Phase 4C AAs)
```

The AA dict emission at line 14875+ adds:

```python
result = {
    "cost": cost_dict,
    "effect": effect_dict,
}
if aa.sorcery_speed:
    result["sorcery_speed"] = True
return result
```

`_aa_dict_to_python_activated_ability` reverse — verify it accepts
`sorcery_speed: True` and threads it onto the constructed AA.

Effect-side arms:

```python
elif isinstance(effect, ExileTargetCardFromGraveyard):
    effect_dict = {"kind": "exile_target_card_from_graveyard"}
elif isinstance(
    effect,
    PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
):
    effect_dict = {
        "kind":
            "put_each_creature_card_exiled_with_source_"
            "onto_battlefield_under_your_control",
    }
    if effect.grant_flying_counter:
        effect_dict["grant_flying_counter"] = True
    if effect.grant_subtype_and_pt is not None:
        sub, p, t = effect.grant_subtype_and_pt
        effect_dict["grant_subtype_and_pt"] = [str(sub), int(p), int(t)]
```

Reverse arms in `_ta_dict_to_python_effect`:

```python
if kind == "exile_target_card_from_graveyard":
    from mtg_bot.effects.generic.exile import (
        ExileTargetCardFromGraveyard,
    )
    return ExileTargetCardFromGraveyard()
if kind == (
    "put_each_creature_card_exiled_with_source_"
    "onto_battlefield_under_your_control"
):
    from mtg_bot.effects.generic.exile import (
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    )
    grant_flying_counter = bool(d.get("grant_flying_counter", False))
    grant_subtype_and_pt = None
    if "grant_subtype_and_pt" in d:
        sub, p, t = d["grant_subtype_and_pt"]
        grant_subtype_and_pt = (str(sub), int(p), int(t))
    return PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl(
        grant_flying_counter=grant_flying_counter,
        grant_subtype_and_pt=grant_subtype_and_pt,
    )
```

### 5.6 Phase 4D — Keys to the House Rooms/Doors + SearchLibraryForCard widen

`_python_aa_to_safe_dict` forward arm:

```python
elif isinstance(effect, SearchLibraryForCard):
    # Already supported on the reverse side per cross_engine.py:5325;
    # add the forward arm for the AA-list emit.
    effect_dict = {
        "kind": "search_library_for_card",
        "filter_name": str(effect.filter_name),
    }
    if effect.max_mv:
        effect_dict["max_mv"] = int(effect.max_mv)
    if not effect.may_fail:
        # default is True; only emit when False (the more-restrictive
        # variant). Round-trip-safe — reverse arm defaults to True.
        effect_dict["may_fail"] = False
elif isinstance(effect, LockOrUnlockDoorOfTargetRoomYouControl):
    effect_dict = {
        "kind": "lock_or_unlock_door_of_target_room_you_control",
    }
```

Reverse arm for the new `LockOrUnlockDoorOfTargetRoomYouControl`
sibling:

```python
if kind == "lock_or_unlock_door_of_target_room_you_control":
    from mtg_bot.effects.generic.misc import (
        LockOrUnlockDoorOfTargetRoomYouControl,
    )
    return LockOrUnlockDoorOfTargetRoomYouControl()
```

`SearchLibraryForCard` reverse arm EXISTS at `cross_engine.py:5325`
— no change.

### 5.7 Phase 4E — All-Fates Scroll mana-ability + condition-multiplier draw

`_python_aa_to_safe_dict` AA-rider gate widen at line 14699:

```python
# Phase 4E widen — is_mana_ability AA-rider admitted on the bridge
# floor for the Carrier-AA admit set. Was: `if aa.is_mana_ability:
# return None`.
if aa.is_mana_ability:
    # Phase 4E: admit is_mana_ability AA-rider. Emit the flag on the
    # AA dict.
    pass  # fall through
```

AA dict emission:

```python
if aa.is_mana_ability:
    result["is_mana_ability"] = True
```

`AddManaToPool` reverse arm EXISTS at `cross_engine.py:7697`; add
its forward sibling:

```python
elif isinstance(effect, AddManaToPool):
    # Phase 4E forward arm — emit produces + optional
    # spend_restriction. The reverse arm at
    # cross_engine.py:7697 mirrors.
    produces_list = []
    for color, n in effect.produces:
        produces_list.append([str(color), int(n)])
    effect_dict = {
        "kind": "add_mana_to_pool",
        "produces": produces_list,
    }
    if effect.spend_restriction is not None:
        effect_dict["spend_restriction"] = str(
            effect.spend_restriction,
        )
```

`DrawCardsByConditionMultiplier` forward + reverse arms (NEW):

```python
elif isinstance(effect, DrawCardsByConditionMultiplier):
    # The condition is an opaque tagged tuple per the static-ability
    # codec at cross_engine.py:14881. Phase 4E-2 extends the dispatch
    # to include "per_differently_named_land".
    cond = effect.condition
    cond_tag, cond_args = _condition_to_tag_args(cond)
    effect_dict = {
        "kind": "draw_cards_by_condition_multiplier",
        "condition_tag": cond_tag,
    }
    if cond_args:
        effect_dict["condition_args"] = list(cond_args)
    if effect.description_fragment:
        effect_dict["description_fragment"] = str(
            effect.description_fragment,
        )

# Reverse:
if kind == "draw_cards_by_condition_multiplier":
    from mtg_bot.effects.generic.draw_mill import (
        DrawCardsByConditionMultiplier,
    )
    cond_tag = str(d["condition_tag"])
    cond_args = tuple(int(x) for x in d.get("condition_args", ()))
    description_fragment = str(d.get("description_fragment", ""))
    cond = _tag_args_to_condition(cond_tag, cond_args)
    return DrawCardsByConditionMultiplier(
        condition=cond,
        description_fragment=description_fragment,
    )
```

The `_condition_to_tag_args` / `_tag_args_to_condition` pair are
existing helpers per `cross_engine.py:14881`; Phase 4E-2 extends
their dispatch table with `"per_differently_named_land"`.

### 5.8 `_filter_deck_to_bridge_supported` OR-chain

Calls update to the new `_printing_is_bridge_simple_carrier_aa_any`
dispatcher in §5.3 (one-line replace at
`trajectory.py:11524,13444`).

### 5.9 Phase-1/1.5/2/3 invariant pin updates

The no-silent-auto-grow walk at the Phase-1+ unit test surface
(per Phase 3 §5.6) gets an inverted pin per sub-phase landing:

* **Phase 4A:** No card admits flip; the walk's expected admit set
  stays at the Phase 3 baseline. The pin asserts multi-AA Mirrorpool
  / Ghost Vacuum / Keys to the House / All-Fates Scroll STAY
  DECLINED post-4A on per-AA Effect-class teeth or AA-rider teeth.
* **Phase 4B (Mirrorpool):** Admit set grows by 1; pin renames
  + inverts the Mirrorpool clause.
* **Phase 4C (Ghost Vacuum):** Admit set grows by 1.
* **Phase 4D (Keys to the House):** Admit set grows by 1.
* **Phase 4E (All-Fates Scroll):** Admit set grows by 1.

---

## 6. Test plan

Each sub-phase ships:

* **Substrate unit pins** (Rust + Python — round-trip + admit-gate
  contract + decline-axis regression).
* **Decline-set regression** — the residue walk at Phase 3 close
  (24 cards → 24 - admit_delta after Phase 4 close).
* **Real-EoE per-card probe** — verifies the FLIP byte-equal on
  GENUINE EoE card pool data (cross-engine resolve trace).

### 6.1 Phase 4A substrate unit pins (Python-only — no Rust)

1. `test_carrier_aa_phase_4a_multi_aa_admit_predicate_widen_substrate`
   — verifies a 2-AA printing with two sub-shape-A AAs admits at
   the new gate (synthetic — Petrified Field x 2 copies on a
   printing, hypothetical). Decline regression: a 2-AA printing
   with AA[1] failing the per-AA gate (synthetic — Petrified Field
   + a `pay_life=1` AA) DECLINES.
2. `test_carrier_aa_phase_4a_artifact_admit_predicate_sibling`
   — verifies the Artifact sibling admits a synthetic Artifact
   printing with one sub-shape-A AA.
3. `test_carrier_aa_phase_4a_no_silent_auto_grow_admit_set_post_widen`
   — asserts the live admit set at Phase 4A close stays exactly the
   Phase 3 set (Swarmyard / Deserted Temple / Petrified Field /
   Terrain Generator / Mystifying Maze / Scavenger Grounds /
   Thespian's Stage). The widen alone admits no new live card.
4. `test_carrier_aa_phase_4a_decline_set_walk` — every multi-AA
   Phase-4 carrier (Mirrorpool / Ghost Vacuum / Keys to the House /
   All-Fates Scroll) STAYS DECLINED on Effect-class teeth post-4A.

### 6.2 Phase 4B substrate unit pins (Rust + Python)

5-8. Python: parser SoT pin + bridge round-trip + Mirrorpool stays-
declined-post-4B-C1 sentinel + admit-now-passes-post-4B-C2
inversion.

9-12. Rust: parse round-trip + to_pydict round-trip + resolve happy
path (spell-copy lands on stack with controller=activator) + resolve
silent-fizzle (target left stack).

13. Mirrorpool's two AAs round-trip independently in a 2-element
list through `_python_aa_to_safe_dict` ← `_aa_dict_to_python_
activated_ability`.

### 6.3 Phase 4C substrate unit pins (Rust + Python)

14-17. Python: parser SoT + bridge round-trip + Ghost-Vacuum-stays-
declined-post-4C-C1 + admit-now-passes inversion.

18-21. Rust: parse round-trip + to_pydict round-trip + resolve happy
path (exile from graveyard, stamps `exiled_with_source`) + resolve
silent-fizzle.

22. The PutEachCreatureCardExiled... mass-effect resolves correctly
when the exile pool is N>=2 cards (one Spirit-rider per returned
card).

23. The `sorcery_speed` AA-rider widen: a synthetic AA with
`sorcery_speed=True` admits at the new bridge floor; the AA dict
round-trips with the `"sorcery_speed": True` key.

### 6.4 Phase 4D substrate unit pins (Rust + Python)

24-26. Python: parser SoT + bridge round-trip + Keys-to-the-House
admit inversion.

27-29. Rust: parse round-trip for LockOrUnlockDoor + to_pydict + Rust
resolve toggles the door state.

30. Rooms/Doors GameObject state: a Room printing's `door_states`
slot round-trips through the Rust↔Python snapshot codec; zone-change
reset clears it to None.

31. SearchLibraryForCard for Keys's `filter_name="basic_land"` shape
admits + resolves on both engines (pre-wired; this is a
sanity pin).

### 6.5 Phase 4E substrate unit pins (Rust + Python)

32-34. Python: parser SoT + bridge round-trip + All-Fates Scroll
admit inversion.

35-37. Rust: parse round-trip for DrawCardsByConditionMultiplier +
to_pydict + Rust resolve counts the differently-named-Lands and
draws.

38. The `is_mana_ability` AA-rider widen: a synthetic AA with
`is_mana_ability=True` admits at the new bridge floor; round-trips.

39. AddManaToPool's `produces=(("any", 1),)` shape resolves to one
mana of agent-chosen color on both engines.

### 6.6 Decline-set regression — the 24 → 20-card walk

The 24-card BLOCKED-SG Carrier-AA residue at Phase 4 entry shrinks
to 20 at Phase 4 close (post-4B/C/D/E FLIP — assuming Phase 3C C2
landed Thespian's Stage; otherwise 25 → 21):

| Post-Phase | Card | Status delta |
|---|---|---|
| 4A | (none) | substrate-only |
| 4B | Mirrorpool | DECLINED → ADMITTED |
| 4C | Ghost Vacuum | DECLINED → ADMITTED |
| 4D | Keys to the House | DECLINED → ADMITTED |
| 4E | All-Fates Scroll | DECLINED → ADMITTED |

Each sub-phase ships ONE invert pin that flips the corresponding
declined-walk assertion to admit, sibling of the Phase 3
walk-inversion pattern.

### 6.7 Real-EoE per-card probes (one per sub-phase)

* **Phase 4B probe — Mirrorpool** — 6 lines: baseline (parse SoT
  claimed) + bridge round-trip + Rust synthetic acceptance + loader
  end-to-end admit + GENUINE real-EoE Mirrorpool AA[0] spell-copy
  on a live Lightning Bolt / Counterspell shape (cross-engine byte-
  equal resolve trace) + GENUINE real-EoE AA[1] token-copy of a
  live creature.
* **Phase 4C probe — Ghost Vacuum** — 6 lines: baseline + bridge +
  Rust synth + loader + GENUINE AA[0] exile-from-graveyard line
  + GENUINE AA[1] return-Spirits-from-self-exile-pool line.
* **Phase 4D probe — Keys to the House** — 5 lines: baseline + bridge
  + Rust synth + loader + GENUINE AA[0] basic-land tutor +
  GENUINE AA[1] door-toggle (synthetic Room target — no live EoE
  Room in the pool today; the synthetic-Room target is a documented
  SL entry).
* **Phase 4E probe — All-Fates Scroll** — 6 lines: baseline + bridge
  + Rust synth + loader + GENUINE AA[0] tap-add-any-mana + GENUINE
  AA[1] draw-X-by-differently-named-Lands.

### 6.8 Pool-parity row delta

At Phase 4 close:
* PROBED: 397 → 401 (+4)
* covered_by_construction: 39 → 39 (unchanged)
* BLOCKED: 39 → 35 (-4 — the 4 Carrier-AA multi-AA wave clears the
  residue row by exactly 4)
* BLOCKED-SG Carrier-AA: 24 → 20

Regen `scripts/measure_pool_parity.py` after every sub-phase landing
per the Phase 3 cadence.

### 6.9 Pre-existing parity gate

`tests/test_measure_pool_parity.py` 32/32 GREEN at Phase 4 entry
HEAD `dbbc1a41`. Stays 32/32 at each sub-phase close (the gate runs
per-sub-phase as a sanity check on the Rust + Python landing).

---

## 7. Estimated cycle count per sub-phase

### 7.1 Phase 4A (multi-AA admit substrate) — ~2 cycles

| Cycle | Owner | Deliverable |
|---:|---|---|
| 1 (4A-C1) | Python agent | **Phase 4A multi-AA admit + Artifact sibling:** widen `_printing_is_bridge_simple_carrier_aa_land` admit predicate (§5.2) + new sibling `_printing_is_bridge_simple_carrier_aa_artifact` + `_printing_is_bridge_simple_carrier_aa_any` dispatcher (§5.3) + `_filter_deck_to_bridge_supported` OR-chain update + 4 Phase-4A substrate unit pins (§6.1). Pool-parity regen (admit set unchanged — substrate-only). |
| 2 (4A-C2) | Python agent | **Phase 4A no-silent-auto-grow + decline-set walk inversion:** invert Phase-3 walk to assert Mirrorpool / Ghost Vacuum / Keys to the House / All-Fates Scroll all STAY DECLINED at Phase 4A close on Effect-class + AA-rider teeth. |

### 7.2 Phase 4B (Mirrorpool) — ~5 cycles

| Cycle | Owner | Deliverable |
|---:|---|---|
| 1 (4B-C1) | Rust agent | **Phase 4B Rust spell-copy substrate:** new `Effect::CopyTargetInstantOrSorceryYouControl` variant + parse / resolve / to_pydict arms + new stack-target fan-out arm in `state_ops_legal.rs::activate_ability_dict` + `StackItem.is_copy` audit + 5 Rust unit pins (§6.2 #9-13). |
| 2 (4B-C2) | Rust agent | **Phase 4B Rust token-creature-copy substrate audit:** verify or port `Effect::CreateTokenCopyOfTargetCreatureYouControl` resolve arm; reuses Phase 3C printing-registry-push primitive. |
| 3 (4B-C3) | Python/bridge agent | **Phase 4B admit + Mirrorpool FLIP:** Effect-class widen (`CopyTargetInstantOrSorceryYouControl` + `CreateTokenCopyOfTargetCreatureYouControl`) + 4 bridge arms (forward + reverse for each) + 4 Python unit pins (§6.2 #5-8) + Phase-4A no-silent-auto-grow walk inversion for Mirrorpool + pool-parity regen. |
| 4 (4B-C4) | Python agent | **Phase 4B real-EoE probe** — AA[0] spell-copy line (§6.7). |
| 5 (4B-C5) | Python agent | **Phase 4B real-EoE probe — AA[1] token-copy line** + SL entry. |

### 7.3 Phase 4C (Ghost Vacuum) — ~3 cycles

| Cycle | Owner | Deliverable |
|---:|---|---|
| 1 (4C-C1) | Rust agent | **Phase 4C Rust exile-pair substrate:** new `Effect::ExileTargetCardFromGraveyard` + `Effect::PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl` variants + parse / resolve / to_pydict arms + new per-player-graveyard single-target fan-out in `state_ops_legal.rs` + 4 Rust unit pins (§6.3 #18-22). |
| 2 (4C-C2) | Python/bridge agent | **Phase 4C admit + Ghost Vacuum FLIP + sorcery_speed AA-rider widen:** bridge-floor sorcery_speed widen (§5.5) + Effect-class widen + 4 bridge arms + 5 Python unit pins (§6.3 #14-17, #23) + walk inversion + pool-parity regen. |
| 3 (4C-C3) | Python agent | **Phase 4C real-EoE probe** (§6.7) + SL entry. |

### 7.4 Phase 4D (Keys to the House) — ~3 cycles

| Cycle | Owner | Deliverable |
|---:|---|---|
| 1 (4D-C1) | Rust agent | **Phase 4D Rust Rooms/Doors substrate:** new `GameObject.door_states: Option<u8>` slot + zone-change reset hookup + new `Effect::LockOrUnlockDoorOfTargetRoomYouControl` variant + parse / resolve / to_pydict arms + new Room-target fan-out in `state_ops_legal.rs` + 5 Rust unit pins (§6.4 #27-31). |
| 2 (4D-C2) | Python/bridge agent | **Phase 4D admit + Keys to the House FLIP:** SearchLibraryForCard forward-arm widen + LockOrUnlockDoor bridge arms + Effect-class widen (both AAs) + 3 Python unit pins (§6.4 #24-26) + sorcery_speed AA-rider widen on AA[1] (or reuse 4C's widen if 4C lands first) + walk inversion + pool-parity regen. |
| 3 (4D-C3) | Python agent | **Phase 4D real-EoE probe** (§6.7) + SL entry. |

### 7.5 Phase 4E (All-Fates Scroll) — ~2-3 cycles

| Cycle | Owner | Deliverable |
|---:|---|---|
| 1 (4E-C1) | Rust agent | **Phase 4E Rust DrawCardsByConditionMultiplier substrate:** new `Effect::DrawCardsByConditionMultiplier { condition_tag, condition_args, description_fragment }` variant + parse / resolve / to_pydict arms + new `"per_differently_named_land"` condition tag in the static-ability condition dispatch table + 3 Rust unit pins (§6.5 #35-37). |
| 2 (4E-C2) | Python/bridge agent | **Phase 4E admit + All-Fates Scroll FLIP + is_mana_ability AA-rider widen:** bridge-floor is_mana_ability widen (§5.7) + Effect-class widen (both AAs) + AddManaToPool forward-arm widen + DrawCardsByConditionMultiplier bridge arms + 5 Python unit pins (§6.5 #32-34, #38-39) + walk inversion + pool-parity regen. |
| 3 (4E-C3) | Python agent | **Phase 4E real-EoE probe** (§6.7) + SL entry. |

**Estimated total: ~14-16 cycles** (2 + 5 + 3 + 3 + 2-3).

**Cost drivers:**
* **Phase 4B (Mirrorpool) is the heaviest** — TWO new Rust Effect
  resolve arms, each in a different copy-machinery family (CR-707.2
  spell-copy is the most novel substrate of Phase 4; CR-707.5 token-
  creature-copy reuses Phase 3C's printing-registry-push primitive
  but may need its own resolve arm). Real-EoE probes need cross-
  engine spell-copy + token-copy lines that are byte-equal on a live
  EoE Lightning Bolt / live EoE creature pair.
* **Phase 4D (Rooms/Doors) is the heaviest state-surface change** —
  new `GameObject.door_states` slot + zone-change reset audit + new
  Effect resolve + Room-target fan-out. But the per-AA bridge arms
  + admit-side cycle cost is comparable to other sub-phases (state
  surface heavier than codepath count).
* **Phase 4A is the cheapest** — Python-only, no Rust. But it's the
  shared prerequisite, so it ships FIRST.
* **Phase 4C is moderate** — two new Rust Effects but they share
  `exiled_with_source` slot semantics (no new slot — just
  produce-then-consume).
* **Phase 4E is moderate** — one new Rust Effect using the
  pre-existing opaque-tuple condition codec; the bridge widen is
  the `is_mana_ability` AA-rider single-line.

---

## 8. SEARCH_LIMITATIONS.md entries (one per sub-phase)

* **Phase 4A SL entry** — "Phase 4A widens the Carrier-AA admit
  predicate from STRICT single-AA (`len(aas) != 1: return False`) to
  multi-AA all-or-nothing per-AA walk; adds an Artifact sibling
  predicate alongside the Land predicate. Substrate-only — no card
  admits flip; Phase 4B/C/D/E land the actual carrier admissions."

* **Phase 4B SL entry** — "Phase 4B ports `Effect::CopyTargetInstant
  OrSorceryYouControl` (CR-707.2 spell-copy — push of a copied
  StackItem with `is_copy=true`; copies' targets are inherited from
  the original, agent-choose-new-targets is Phase N) +
  `Effect::CreateTokenCopyOfTargetCreatureYouControl` (CR-707.5
  token-creature-copy; bare shape with `additional_subtype=None`;
  legendary-supertype suppression for token copies is Phase N per
  §3.10). Both AAs of Mirrorpool admit on the Effect-class + multi-AA
  widen alone; `{2}{C}` / `{4}{C}` cost shapes parse as generic 3 / 5
  (colorless pip folds into ManaCost.generic per the parser SoT)."

* **Phase 4C SL entry** — "Phase 4C ports `Effect::ExileTargetCardFrom
  Graveyard` (single-target across both players' graveyards; stamps
  `exiled_with_source = Some(source.id)` per round-28 attach
  precedent) + `Effect::PutEachCreatureCardExiledWithSourceOntoBattle
  fieldUnderYourControl` (zero-target mass-effect; reads the
  `exiled_with_source` stamp; carries `grant_flying_counter=True` +
  `grant_subtype_and_pt=('Spirit', 1, 1)` rider payload for the
  Spirit-1/1 with flying overlay). Widens the AA-rider gate to admit
  `sorcery_speed=True` AAs on the bridge floor."

* **Phase 4D SL entry** — "Phase 4D ports the minimum Rooms/Doors
  substrate: new `GameObject.door_states: Option<u8>` per-Room
  locked-bitmask slot (cleared on zone change per CR 400.7) +
  `Effect::LockOrUnlockDoorOfTargetRoomYouControl` toggle Effect +
  Room-target fan-out arm. Phase 4D does NOT model entering-a-Room
  triggers, the CR-715 win-condition, per-half mana costs, or other
  full-Rooms gameplay — Phase 5+ for those. Keys to the House's AA[0]
  uses the pre-wired SearchLibraryForCard(filter_name='basic_land')
  Rust resolve."

* **Phase 4E SL entry** — "Phase 4E ports `Effect::DrawCardsBy
  ConditionMultiplier` (zero-target; reads the multiplier via the
  opaque `(condition_tag, condition_args)` codec sibling of the
  static-ability condition codec; adds the `'per_differently_named_
  land'` condition tag). Widens the AA-rider gate to admit
  `is_mana_ability=True` AAs on the bridge floor. AddManaToPool's
  `produces=(('any', 1),)` shape (one mana of any color, agent-
  chosen on resolve) is pre-wired."

---

## 9. Rejected alternatives

### 9.1 Bundle all four sub-phases into one Phase 4 landing

**Rejected — four orthogonal Effect families.** Phase 4B's spell-copy
+ token-creature-copy substrate, Phase 4C's exile-pair substrate,
Phase 4D's Rooms/Doors substrate, and Phase 4E's condition-
multiplier-draw substrate share NO machinery beyond the Phase 4A
multi-AA admit primitive. Folding them into one cycle adds four Rust
slices in one `.pyd`-rebuild window, quadruples the cross-engine
surface verified at landing time, and conflates four independent
admit-gate inversions. Per Phase 2 §9.7 + Phase 3 §9.1, separate Rust
cycles preserve the `.pyd` race rule and audit clarity.

### 9.2 Defer Phase 4A's multi-AA admit substrate to a later Phase

**Rejected — Phase 4A is the keystone.** Without the multi-AA admit
widen, no Phase 4 carrier admits at all. Deferring 4A defers the
whole campaign. Phase 4A is small (Python-only, ~2 cycles) so the
prerequisite cost is the smallest of any sub-phase.

### 9.3 Bundle Phase 4B's two Mirrorpool effects with Phase 3C (copy-effect campaign)

**Rejected — different copy-machinery families per Phase 3 §2.4 +
§9.4 + §9.7.** Phase 3C's `BecomesCopyOfTargetLand` is CR-613
layer-1 object-copy (per-GameObject `original_printing_id` slot);
Mirrorpool AA[0]'s `CopyTargetInstantOrSorceryYouControl` is CR-707.2
spell-copy (push a new StackItem); Mirrorpool AA[1]'s
`CreateTokenCopyOfTargetCreatureYouControl` is CR-707.5 token-copy
(allocate a new token GameObject). These three families share NO
state slots or resolve helpers. Phase 3C left the printing-registry-
push primitive Phase-4-reusable (per §2.4); Phase 4B-2 collects via
the primitive composition, not via co-bundling.

### 9.4 Defer Phase 4D's Rooms/Doors substrate to a "full Rooms" Phase

**Rejected — Keys to the House's AA[1] needs the toggle Effect.**
The minimum Rooms/Doors substrate (per-Room locked-bitmask slot +
toggle Effect) is small enough to land in one Rust cycle. Deferring
to a "full Rooms" Phase (entering-Room triggers, CR-715 win-
condition, per-half mana costs) defers Keys to the House from Phase
4 to Phase N+ unnecessarily. Phase 4D ships the MINIMUM substrate
under an SL entry documenting the full-Rooms deferral.

### 9.5 Drop Phase 4D from Phase 4 and pursue 4B + 4C + 4E only

**Rejected — Phase 4 is the multi-AA campaign cluster.** Phase 4
sub-phases are bound by the multi-AA admit prerequisite, not by
Effect family. Dropping any sub-phase leaves the corresponding
carrier in BLOCKED-SG indefinitely. Phase 4D's Rooms/Doors substrate
is heavier than 4C / 4E but tractable as an independent 3-cycle sub-
phase; it ships in its own timeline alongside the others.

### 9.6 Build the Phase 4A multi-AA admit predicate WITHOUT the all-or-nothing per-AA contract (admit a printing if ANY AA passes)

**Rejected — partial-admit contract is unsafe.** A printing with N
AAs admitted under "any AA passes" emits N legal-actions on the
cross-engine bridge — but the bridge floor would have to silently
omit the AAs that don't round-trip, which means the action surface
on Python vs Rust would diverge (different N), which breaks the
parity gate. The all-or-nothing contract mirrors the token-AA
Lander's stance per Phase 2 §3.4 and is the only contract that
preserves cross-engine action-set byte-equality.

### 9.7 Pursue a single "AA-rider widen" Phase covering sorcery_speed + is_mana_ability + activate_only_once + tier_threshold + room_half + cost_reductions in one substrate

**Rejected — different AA-rider semantics + different scope cards.**
`sorcery_speed` is a CR-307.4 timing restriction (Phase 4C/4D);
`is_mana_ability` is a CR-605 sub-priority class (Phase 4E);
`activate_only_once` is a per-game once gate (Phase 5+ — Haunted
Screen); `tier_threshold` is a station-threshold gate (Phase N);
`room_half` is a Rooms-half-state gate (folds into Phase 4D Rooms
substrate). Each rider has different state surface + different
cross-engine semantics. Bundling them adds zero leverage. Phase 4
widens ONLY the riders the in-scope cards need.

### 9.8 Skip Phase 4 and pursue effect-uncovered drain (31-card multi-gated tail) directly

**Rejected — Phase 4 closes 4 cards on tractable substrate; effect-
uncovered is a 31-card per-card-bespoke campaign.** Phase 4 is a
substrate-leveraged Phase (4 cards on 4 substrate widens, each
substrate reusable Phase N+); effect-uncovered drain is a per-card
direct-port campaign with no substrate-reuse. The two campaigns
target different rows of the inventory and run in parallel; Phase 4
should not be skipped because it bottoms out the multi-AA leverage
frontier.

### 9.9 Re-include Haunted Screen / The Eternity Elevator in Phase 4

**Rejected — Haunted Screen and The Eternity Elevator each carry
additional substrate beyond Phase 4's scope.** Haunted Screen has
n_aa=3 + `activate_only_once` + `Sequence` Effect — three riders
each Phase-N. The Eternity Elevator has the `AddChargeCounter
ManaOfChosenColor` AA that's Spacecraft-substrate-adjacent (charge-
counter mana is a Spacecraft station-threshold concept) — bundles
cleaner with the Spacecraft Phase 4+ tail per §3.2.

---

## 10. Acceptance / sign-off (per sub-phase)

### 10.1 Phase 4A acceptance

1. The Phase 4A Python widen (§5.2 + §5.3) lands; no `.pyd` change.
2. The 4 Phase-4A substrate unit pins (§6.1) pass.
3. The decline-set walk at Phase 4A close stays at the Phase 3
   baseline (no card admits).
4. The parity gate `tests/test_measure_pool_parity.py` stays 32/32.
5. Pool-parity regen lands no row delta (substrate-only).

### 10.2 Phase 4B acceptance

1. The Phase 4B Rust substrate (§4.1.1 + §4.1.2) lands; the `.pyd`
   rebuilds clean.
2. The Phase 4B admit + Mirrorpool FLIP (§5.1, §5.4) lands; the 9
   Phase-4B unit pins (§6.2 #5-13) all pass.
3. The Phase 4B Mirrorpool real-EoE probe (§6.7 — both AA[0] spell-
   copy and AA[1] token-copy lines) passes byte-equal.
4. Pool-parity regen lands +1 card in PROBED tier; BLOCKED-SG
   Carrier-AA shrinks by 1.
5. SEARCH_LIMITATIONS.md gains the §8 Phase 4B entry.

### 10.3 Phase 4C acceptance

1. The Phase 4C Rust substrate (§4.2.1 + §4.2.2) lands; the `.pyd`
   rebuilds clean.
2. The Phase 4C admit + Ghost Vacuum FLIP (§5.1, §5.5) + sorcery_speed
   AA-rider widen lands; the 10 Phase-4C unit pins (§6.3 #14-23) all
   pass.
3. The Phase 4C Ghost Vacuum real-EoE probe (§6.7) passes byte-equal.
4. Pool-parity regen lands +1 card in PROBED tier; BLOCKED-SG
   Carrier-AA shrinks by 1.
5. SEARCH_LIMITATIONS.md gains the §8 Phase 4C entry.

### 10.4 Phase 4D acceptance

1. The Phase 4D Rust substrate (§4.3) lands; the `.pyd` rebuilds
   clean. Rooms/Doors GameObject slot snapshot codec round-trips.
2. The Phase 4D admit + Keys to the House FLIP (§5.1, §5.6) lands;
   the 8 Phase-4D unit pins (§6.4 #24-31) all pass.
3. The Phase 4D Keys to the House real-EoE probe (§6.7 — synthetic-
   Room target for AA[1] documented in SL entry) passes byte-equal.
4. Pool-parity regen lands +1 card in PROBED tier; BLOCKED-SG
   Carrier-AA shrinks by 1.
5. SEARCH_LIMITATIONS.md gains the §8 Phase 4D entry.

### 10.5 Phase 4E acceptance

1. The Phase 4E Rust substrate (§4.4) lands; the `.pyd` rebuilds
   clean.
2. The Phase 4E admit + All-Fates Scroll FLIP (§5.1, §5.7) +
   is_mana_ability AA-rider widen lands; the 8 Phase-4E unit pins
   (§6.5 #32-39) all pass.
3. The Phase 4E All-Fates Scroll real-EoE probe (§6.7) passes byte-
   equal.
4. Pool-parity regen lands +1 card in PROBED tier; BLOCKED-SG
   Carrier-AA shrinks by 1.
5. SEARCH_LIMITATIONS.md gains the §8 Phase 4E entry.

---

## 11. Cross-references

* `docs/CARRIER_AA_SUBSTRATE_PHASE_1_DESIGN.md` — parent campaign-
  shape doc; §2.1 30-card walk + §3 out-of-scope matrix +
  §10.3 sibling-swap clause.
* `docs/CARRIER_AA_SUBSTRATE_PHASE_1_5_DESIGN.md` — Phase 1.5a cost-
  gate widen.
* `docs/CARRIER_AA_SUBSTRATE_PHASE_2_DESIGN.md` — Phase 2 `{T}, Sac:`
  cost-gate widen + Effect ports + §3.4 multi-AA Phase 4 deferral
  + §3.5 AA-level riders + §9.6 "Pursue Mirrorpool/Ghost Vacuum/Keys
  to the House/All-Fates Scroll multi-AA in Phase 2" rejection.
* `docs/CARRIER_AA_SUBSTRATE_PHASE_3_DESIGN.md` — Phase 3A/B/C three-
  orthogonal-Effect-family widens + §2.4 co-bundling audit +
  §9.4 + §9.7 copy-effect-family separation + the printing-registry-
  push primitive Phase 4B-2 reuses.
* `src/mtg_bot/parity/trajectory.py:8953` — `_carrier_aa_phase_1_
  effect_classes` accessor (Phase 4 grows from 7 → 15 Effect
  classes).
* `src/mtg_bot/parity/trajectory.py:9000` — `_aa_is_phase1_sub_shape_a`
  per-AA predicate (Phase 4 leaves the cost gate UNCHANGED).
* `src/mtg_bot/parity/trajectory.py:9171` — `_printing_is_bridge_
  simple_carrier_aa_land` printing admit (Phase 4A widens
  `len(aas) != 1` decline; Phase 4A.2 adds Artifact sibling at a
  new line).
* `src/mtg_bot/parity/trajectory.py:9240` — the SINGLE-AA decline
  arm that Phase 4A widens.
* `src/mtg_bot/parity/cross_engine.py:14657` — `_python_aa_to_safe_dict`
  bridge floor (Phase 4C widens `sorcery_speed` decline at 14701;
  Phase 4E widens `is_mana_ability` decline at 14699; new Effect
  arms at 14810+).
* `src/mtg_bot/parity/cross_engine.py:14881` — `_static_self_bonus_
  condition_from_tag` opaque-tuple codec (Phase 4E-2 extends with
  `"per_differently_named_land"`).
* `src/mtg_bot/parity/cross_engine.py:5325` — `SearchLibraryForCard`
  reverse arm (Phase 4D uses; pre-wired).
* `src/mtg_bot/parity/cross_engine.py:7190` —
  `CreateTokenCopyOfTargetCreatureYouControl` reverse arm (Phase 4B
  uses; pre-wired — audit forward + resolve arms).
* `src/mtg_bot/parity/cross_engine.py:7697` — `AddManaToPool` reverse
  arm (Phase 4E uses; pre-wired — add forward arm).
* `rust/src/cards.rs:12027` — `add_mana_to_pool` Rust parse.
* `rust/src/cards.rs:13347` — `create_token_copy_of_target_creature_
  you_control` Rust parse.
* `rust/src/cards.rs:14965` — `search_library_for_card` Rust parse.
* `rust/src/state.rs:122` — `exiled_with_source: Option<u32>` (Phase
  4C reads).
* `docs/SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY.md` — the BLOCKED-SG
  Carrier-AA row this Phase shrinks 24 → 20.

---

## 12. Sequencing recommendation

**Recommended dispatch order** (the design lane's recommendation; the
user makes the final call):

1. **Phase 4A first** — the keystone. Python-only, ~2 cycles, ZERO
   `.pyd` rebuild. Lands first because every subsequent sub-phase
   depends on the multi-AA admit. Ship before any other Phase 4 sub-
   phase.
2. **Phase 4E next** — smallest novel-substrate Phase 4 card-FLIP.
   AddManaToPool is pre-wired; `DrawCardsByConditionMultiplier` is
   the only new Rust Effect; `is_mana_ability` AA-rider widen is a
   single-line bridge floor change. Validates the multi-AA admit
   from 4A under the smallest possible additional substrate.
3. **Phase 4C next** — moderate. Two new Rust Effects share the
   `exiled_with_source` slot semantics (produce-then-consume).
   `sorcery_speed` AA-rider widen is reused by 4D.
4. **Phase 4D next** — heaviest state-surface change (Rooms/Doors
   GameObject slot). But the SearchLibraryForCard half is pre-wired;
   lands after 4C so the `sorcery_speed` AA-rider widen is already
   validated.
5. **Phase 4B last** — heaviest by Effect count + most novel
   substrate (CR-707.2 spell-copy is the most novel substrate of
   Phase 4). Lands last so multi-AA + sorcery-speed + Rooms/Doors are
   all validated baselines before tackling spell-copy.

**Parallelism note.** Phase 4A's landing unblocks 4B/C/D/E in
parallel. The dispatch order above is the recommended sequential
order for a single-worker lane; a multi-worker lane can run 4B/C/D/E
in parallel after 4A lands. Conflict-free at the file level — 4B
touches stack-copy; 4C touches exile-pair; 4D touches Rooms/Doors;
4E touches condition-multiplier — but each touches the SAME bridge
floor (`_python_aa_to_safe_dict` Effect dispatch elif chain) so the
Python landing cycles serialize through one merge gate.

---

## 13. Verify-first walk reproduction

To regenerate the §2.1 per-card details + §2.3 Rust substrate audit
+ §2.2 Python Effect-class signatures + §6.6 pool-parity row delta
at a future HEAD, run a one-off scout that:

1. Loads the parser source via `OracleParserCardSource.get_printings()`.
2. Looks up each of the 4 cards by name.
3. Prints `(card_types, subtypes, supertypes, keywords, n_aa, n_ta,
   n_sa)` and for each AA `(cost.mana_str, cost.tap_self,
   cost.sacrifice_self, cost.sacrifice_a_desert, cost.pay_life,
   aa.sorcery_speed, aa.is_mana_ability, aa.activate_only_once,
   aa.tier_threshold, aa.room_half, type(aa.effect), repr(aa.effect)
   tail)`.
4. Drives `cross_engine._python_aa_to_safe_dict` on each AA to
   confirm round-trip status (currently `None` for all 4 cards' all
   AAs — the live bridge floor decline).
5. Greps `rust/src/cards.rs` + `rust/src/state_ops_resolve.rs` for
   each Effect's parse arm + resolve arm to confirm the §2.3 table's
   EXISTS / DOES NOT EXIST status.

The scout is **not committed** — design-lane verify-first discipline
keeps the audit table reproducible from the live tree, not from a
pinned snapshot.
