# Spacecraft Station substrate — Phase 4 design (The Eternity Elevator closure)

**Status:** DESIGN + Cycle 1 substrate landing. The C1 Rust slice ships
alongside this doc; the live admit FLIP lands at C2.

**Author:** Spacecraft Station Phase 4 lane, Worker B
(`feature/spacecraft-phase-4-eternity-elevator-closure-p2`),
2026-05-26.

**Predecessors:**

* Phase 1 — Galvanizing Sawship (Spacecraft substrate keystone:
  `CardPrinting.station_threshold` + `stationed_keywords` parse arm +
  `is_stationed` predicate + `Action::ActivateStation` resolver +
  `_printing_is_bridge_pure_station_spacecraft` admit predicate).
* Phase 2 — Lumen-Class Frigate (tier-gated layer-7 anthem static —
  `PowerToughnessBonus` reader fold + tier_threshold static gate).
* Phase 3A — Larval Scoutlander (ETB+IsSelf trigger,
  `OptionalSacLandOrLanderForBasicLandRamp`).
* Phase 3B — Sledge-Class Seedship (ATTACKS trigger,
  `OptionalPutCreatureFromHandOntoBattlefield`).
* Phase 3C — Synthesizer Labship + Entropic Battlecruiser + Infinite
  Guideline Station (BEGINNING_OF_COMBAT + WHENEVER_ATTACKS + ATTACKS
  triggers; tier-gated trigger predicate).
* Carrier-AA Phase 1 + 1.5a — non-token-AA bridge round-trip landing
  (`CardDef.activated_abilities` + `Effect::RegenerateTargetCreature` +
  `Effect::UntapTargetLand`; the Carrier-AA non-token-AA bridge that
  Spacecraft Phase 4 depends on per Spacecraft Phase 1 design doc
  §10.3).

**Companion docs:**
`docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_1_DESIGN.md` (parent
campaign-shape doc — Phase 4 deferral at §10.3);
`docs/CARRIER_AA_SUBSTRATE_PHASE_1_DESIGN.md` (Carrier-AA non-token-AA
bridge predecessor); `docs/CARRIER_AA_SUBSTRATE_PHASE_4_DESIGN.md` §3.2
(explicit "The Eternity Elevator deferred to Spacecraft Phase 4+"
clause).

---

## 0. Executive summary

**Phase 4** closes the LAST Spacecraft in the EoE pool — **The Eternity
Elevator** (`station_threshold=None`, multi-AA with a tier_threshold=20
gate) — completing the **8-card / ~41,281 17lands-deck Spacecraft
Station campaign**.

The card sits at the intersection of three substrate widens not covered
by Phases 1-3:

1. **`station_threshold=None`** — non-animating Spacecraft (the ONLY
   such card in the EoE pool). Phases 1-3 reject this shape; Phase 4
   admits it.
2. **Multi-AA with `tier_threshold > 0` on AA[1]** — Phases 1-3's
   admit set is zero-AA Spacecraft; Phase 4 widens to multi-AA where
   each AA must independently pass the Carrier-AA Phase 1 sub-shape-A
   predicate, lifting the `tier_threshold=0` AA-rider gate to admit
   `tier_threshold>=0` (and exercising the existing Rust
   `ActivatedAbility.tier_threshold` slot at the bridge).
3. **`AddChargeCounterManaOfChosenColor`** — a NEW Effect class on
   AA[1] (`20+ | {T}: Add X mana of any one color, where X is the
   number of charge counters on The Eternity Elevator.`). The Effect's
   `X` is computed at resolve time from `source.charge_counters` (data
   already on Rust's `GameObject.charge_counters: i32`), delegating to
   the existing `AddNManaOfChosenColor` mint loop.

The card's other AA (AA[0] = `{T}: Add {C}{C}{C}.`) is a basic
`AddManaToPool` (already bridge-clean from the round-21 mana-ability
bridge slice); the only new Effect class is the AA[1] charge-counter
mana variant.

**Cycle plan** (4 cycles total):

* **C1 — Rust substrate landing (this cycle, ships with this doc):**
  New `Effect::AddChargeCounterManaOfChosenColor` Rust variant +
  parser + resolver + to_pydict arm + cross-engine bridge arms
  (forward + reverse). **The Eternity Elevator STAYS DECLINED at
  the admit gate post-C1** (the three Python-side admit gates all
  still reject the printing). **Pool-parity side-effect at C1:**
  Effect-level coverage rises — both AAs' Effect classes
  (`AddManaToPool` + the new `AddChargeCounterManaOfChosenColor`)
  now have live Rust variants, so the Effect-coverage instrument
  (`measure_pool_parity.classify_pool` via `effect_coverage.
  covered_python_class_set`) classifies the printing as
  `covered_by_construction` rather than BLOCKED. **BLOCKED-SG
  Spacecraft row drops 1 → 0 at C1** (the row was the
  Effect-uncovered axis); the Carrier-AA row count adjusts in
  lockstep. **The PROBED tier bump waits for C3** — covered_by_
  construction → PROBED requires the per-card real-EoE byte-equal
  probe. C4 is doc-only at that point (regen POOL_PARITY + worklog
  entries).
* **C2 — Python admit widen + AA-rider gate widen:** Lift
  `tier_threshold` AA-rider decline in `_aa_is_phase1_sub_shape_a`
  (or sibling helper) + widen `_python_aa_to_safe_dict` to round-trip
  the `tier_threshold` field on the Rust AA dict + new
  `_printing_is_bridge_phase_4_spacecraft_eternity_elevator`
  predicate admitting `station_threshold=None` + multi-AA + Spacecraft
  subtype + Artifact + Legendary supertype + new
  `_eternity_elevator_card_def` builder + admit-set bump.
* **C3 — Per-card real-EoE probe:** `tests/test_the_eternity_elevator_parity.py`
  driving the live printing through parse + bridge round-trip + Rust
  synthetic acceptance + end-to-end loader admit + Python-side resolve
  smoke covering Scenario A (charge_counters=0 — AA[1] tier-gated off)
  + Scenario B (charge_counters=20 — AA[1] tier-gated on, picks first
  color) + Scenario C (mana-ability bypass-stack semantics on both
  AAs).
* **C4 — Pool-parity regen + worklog + BLOCKED-SG row drop +
  Spacecraft 8/8 = FULL CAMPAIGN CLOSURE.** Register probe in
  `PROBE_MODULES`; regenerate `docs/POOL_PARITY.md`; Spacecraft
  BLOCKED-SG row 1 → 0; PROBED tier bumps.

C1 ships with this doc as the **substrate-only landing** — same
pattern as Carrier-AA Phase 4C C1 / 4D C1 / 4E C1.

---

## 1. Verify-first walk — The Eternity Elevator at HEAD `818b4c64`

### 1.1 Live oracle text + printing fields

Scryfall record (live `data/edge_of_eternities.json`):

```
"name": "The Eternity Elevator"
"mana_cost": "{5}"
"type_line": "Legendary Artifact — Spacecraft"
"oracle_text":
  "{T}: Add {C}{C}{C}.
   Station (Tap another creature you control: Put charge counters
     equal to its power on this Spacecraft. Station only as a
     sorcery.)
   20+ | {T}: Add X mana of any one color, where X is the number of
     charge counters on The Eternity Elevator."
```

### 1.2 Parser-emitted `CardPrinting` shape

Verified via Slice 7 of the unified Spacecraft grammar
(`src/mtg_bot/cards/parser/spacecraft_builder.py:110-340`):

* `name="The Eternity Elevator"`
* `mana_cost_str="{5}"` (parses to `ManaCost(generic=5)`)
* `card_types=("Artifact",)`
* `supertypes=("Legendary",)`
* `subtypes=("Spacecraft",)`
* `power=0`, `toughness=0` (non-animating default per
  `cards/base.py:1265-1270`)
* `station_threshold=None` (non-animating — never becomes a creature
  even at 20 counters)
* `stationed_keywords=frozenset()` (no keyword-tier line)
* `keywords=frozenset({"Station"})` (the Station mechanic itself)
* `activated_abilities=(`
   * AA[0]: `ActivatedAbility(cost=ActivationCost(tap_self=True),
     effect=AddManaToPool(produces=(("C", 3),)),
     is_mana_ability=True, tier_threshold=0)`
   * AA[1]: `ActivatedAbility(cost=ActivationCost(tap_self=True),
     effect=AddChargeCounterManaOfChosenColor(),
     is_mana_ability=True, tier_threshold=20)`
  `)`
* `static_abilities=()`, `triggered_abilities=()`
* `spell_effect=None`, `room_halves=()`, `loyalty=None`
* All `cost_reductions` / `warp_cost` / `kicker_cost` /
  `impending_cost` / `dynamic_pt_formula` / `ward_cost` / per Phase-1
  exclusion teeth — all default / empty.

### 1.3 Why all three Phase 1-3 + Carrier-AA admit predicates decline today

* **`_printing_is_bridge_pure_station_spacecraft`** (Phase 1) declines
  on `station_threshold is None` (`trajectory.py:9691-9692`).
* **`_printing_is_bridge_phase_2_static_anthem_spacecraft`** (Phase 2)
  declines on empty `static_abilities`.
* **`_printing_is_bridge_phase_3_trigger_spacecraft`** (Phase 3)
  declines on `station_threshold is None` (`trajectory.py:10274-10275`)
  AND empty `triggered_abilities`.
* **`_printing_is_bridge_simple_carrier_aa_artifact`** (Carrier-AA
  Phase 4A.2 Artifact sibling) declines on non-empty `subtypes`
  (`trajectory.py:9440-9441` — Spacecraft subtype). The Spacecraft
  Phase 4 admit predicate is therefore a NEW SIBLING, not a widen of
  the Carrier-AA Artifact admit.

### 1.4 Why AA[1] declines today

The `_aa_is_phase1_sub_shape_a` per-AA gate declines on:

* `tier_threshold > 0` (`trajectory.py:9293-9294`) — AA[1] carries
  `tier_threshold=20`. This is the **per-AA admit-rider widen** that
  Spacecraft Phase 4 C2 needs to lift (or a sibling helper).
* `type(aa.effect) not in _carrier_aa_phase_1_effect_classes()` —
  `AddChargeCounterManaOfChosenColor` is NOT in the current Phase 1
  Effect-class admit set. C2 adds the class.

The `_python_aa_to_safe_dict` bridge floor declines on:

* `tier_threshold` non-zero (`cross_engine.py:14990-14991`) — same
  reason. Bridge floor widen needed at C2.

### 1.5 What the Rust side already supports

* **`ActivatedAbility.tier_threshold: i32`** is already a parsed +
  round-trip-supported field (`cards.rs:17812-17828` parses;
  `cards.rs:11241` declares; CE20 follow-up Slice 3 landed it). No new
  Rust slot needed.
* **`GameObject.charge_counters: i32`** is already on every game
  object (`state.rs:63`). The new Effect resolver reads this field
  directly from the source object.
* **`CardPrinting.station_threshold: Option<i32>`** supports `None`
  via Option (`cards.rs:11950`). No new Rust slot needed.
* **`CardPrinting.supertypes`** supports `("Legendary",)`
  (round-30 substrate, `cards.rs:11404+`). No new Rust slot needed.
* **Mana-ability bypass-stack semantics** for AAs with
  `is_mana_ability=true` round-trip via `_python_aa_to_safe_dict`
  (round-21 mana-ability bridge + Phase 4E C2 widen at
  `cross_engine.py:14922 + 15619-15625`).

### 1.6 What the Rust side does NOT yet support — Phase 4 C1's scope

* **`Effect::AddChargeCounterManaOfChosenColor` variant** — does not
  exist. Cycle 1 lands it as a unit-variant struct with no fields.
* **`parse_effect` arm** for `kind == "add_charge_counter_mana_of_
  chosen_color"` — does not exist. Cycle 1 adds.
* **`apply_effect` arm** — does not exist. Cycle 1 adds (reads
  `source_obj_id`'s `charge_counters` from any zone, mints
  `charge_counters`-many coins of options[0]="W"; delegates to the
  same `push_coins` path `AddNManaOfChosenColor` uses).
* **`to_pydict` arm** — does not exist. Cycle 1 adds.
* **Cross-engine bridge arms** — `_ta_dict_to_python_effect` forward
  arm + `_python_aa_to_safe_dict` reverse arm — both missing. Cycle 1
  adds.

---

## 2. Out of scope (Phase 5 / N)

### 2.1 Non-deterministic color choice via agent

C1 resolves to **options[0]="W"** in Rust (deterministic, mirrors
`AddNManaOfChosenColor`'s first-slice fallback). Python's
`AddChargeCounterManaOfChosenColor` delegates to
`AddNManaOfChosenColor`'s resolve, which asks
`Agent.choose_mana_color` and falls back to options[0] if no agent is
seated. The decision-callback wiring for agent-driven color choice is
a separate cross-cutting slice (round-28 deterministic-mana-color
precedent); Phase 4 honors the same first-slice convention.

### 2.2 Animating-when-tier-reached scenario

The Eternity Elevator's `station_threshold=None` means it NEVER
animates — even at 20+ charge counters. The `is_stationed` predicate
returns False unconditionally (`game.py` + Rust mirror). No new
animation path needed.

### 2.3 Tier-gated AA legal-emit gate

The Rust `legal_decisions` AA emitter already gates AAs with
`tier_threshold > 0` behind a `charge_counters >= tier_threshold`
check (`state_ops_legal.rs:3328` per CE20 follow-up Slice 3). AA[1]
is therefore byte-equivalently legal-emit-gated; no new legal-emit
machinery needed.

### 2.4 Multi-AA admit widen beyond the keystone

Carrier-AA Phase 4A landed the multi-AA `_printing_is_bridge_simple_
carrier_aa_land/artifact` walk
(`trajectory.py:9387-9392 + 9473-9478`). Spacecraft Phase 4 C2's new
predicate `_printing_is_bridge_phase_4_spacecraft_eternity_elevator`
mirrors the same multi-AA per-AA walk pattern. No further widen.

---

## 3. Rust-side spec — Cycle 1 substrate landing

### 3.1 New Effect variant

In `rust/src/cards.rs::Effect` (alongside `AddNManaOfChosenColor`):

```rust
/// **Spacecraft Phase 4 Cycle 1 (2026-05-26).** Add X mana of a
/// single color chosen by the controller at resolution time, where
/// X is the source's `charge_counters`. Mirrors Python's
/// `AddChargeCounterManaOfChosenColor()` (unit dataclass — no
/// fields) at `mana.py:133` — The Eternity Elevator's
/// tier_threshold=20 AA[1] pilot.
///
/// **Resolve semantics.** Reads the source object's
/// `charge_counters: i32` from any zone (mirror of the source-
/// controller scan in `AddNManaOfChosenColor`). On
/// `charge_counters <= 0`, silent no-op (matches Python's
/// `if amount <= 0: return` at `mana.py:161-162`). Otherwise mints
/// `charge_counters` coins of `options[0]="W"` via the same
/// `push_coins` path. **First-slice deterministic color choice.**
///
/// **Unit variant.** No fields — the source-derived `amount` + the
/// implicit WUBRG default options.
AddChargeCounterManaOfChosenColor,
```

### 3.2 `parse_effect` arm

```rust
"add_charge_counter_mana_of_chosen_color" => {
    Ok(Effect::AddChargeCounterManaOfChosenColor)
}
```

### 3.3 `to_pydict` arm

```rust
Effect::AddChargeCounterManaOfChosenColor => {
    d.set_item("kind", "add_charge_counter_mana_of_chosen_color")?;
}
```

### 3.4 `apply_effect` arm (resolve)

In `rust/src/state_ops_resolve.rs::apply_effect`, alongside
`Effect::AddNManaOfChosenColor`:

```rust
Effect::AddChargeCounterManaOfChosenColor => {
    // Source-object scan: read `charge_counters` from whichever
    // zone the source sits in. Mirrors `AddNManaOfChosenColor`'s
    // source-controller scan but additionally reads the
    // charge_counters field.
    let mut src_controller: Option<u8> = None;
    let mut amount: i32 = 0;
    'outer: for player in &state.players {
        for zone in [
            &player.hand,
            &player.library,
            &player.battlefield,
            &player.graveyard,
            &player.exile,
        ] {
            if let Some(obj) = zone.iter().find(|o| o.id == source_obj_id) {
                src_controller = Some(obj.controller);
                amount = obj.charge_counters;
                break 'outer;
            }
        }
    }
    if src_controller.is_none() {
        if let Some(item) = state
            .stack
            .iter()
            .find(|i| i.source_obj_id == source_obj_id)
        {
            src_controller = Some(item.controller);
        }
    }
    // No source object visible — silent no-op (mirrors Python's
    // `if source is None: return` at `mana.py:158-159`).
    if amount <= 0 {
        return Ok(());
    }
    let controller_idx = match src_controller {
        Some(c) => c as usize,
        None => state.active_player as usize,
    };
    let amount_u8 = amount.min(u8::MAX as i32) as u8;
    let pool = &mut state.players[controller_idx].mana_pool;
    // First-slice deterministic color: options[0] = "W" (mirrors
    // AddNManaOfChosenColor's WUBRG default + first-color
    // fallback).
    pool.push_coins(b'W', amount_u8);
    pool.assert_count_sync();
}
```

---

## 4. Python bridge spec — Cycle 1 substrate landing

### 4.1 Reverse arm in `_ta_dict_to_python_effect`

```python
if kind == "add_charge_counter_mana_of_chosen_color":
    from mtg_bot.effects.generic.mana import (
        AddChargeCounterManaOfChosenColor,
    )
    return AddChargeCounterManaOfChosenColor()
```

### 4.2 Forward arm in `_python_aa_to_safe_dict`

```python
elif isinstance(effect, AddChargeCounterManaOfChosenColor):
    effect_dict = {
        "kind": "add_charge_counter_mana_of_chosen_color",
    }
```

(Plus the import of `AddChargeCounterManaOfChosenColor` from
`mtg_bot.effects.generic.mana`.)

### 4.3 Substrate-only invariant

**The Eternity Elevator STAYS DECLINED at admit gate post-C1.** The
Rust Effect variant + cross-engine bridge arms all land; the live
admit gate still declines the printing because (a)
`_aa_is_phase1_sub_shape_a` still declines `tier_threshold > 0` AND
(b) the Carrier-AA Effect-class admit set doesn't include
`AddChargeCounterManaOfChosenColor` AND (c) the
Spacecraft Phase 1-3 admit predicates all reject
`station_threshold=None` + non-empty `activated_abilities`. ALL THREE
widens ship C2 (per §1 cycle plan). The forward arm + Rust round-trip
both succeed at C1 — driven by synthetic unit pins.

---

## 5. Cycle plan summary

| Cycle | Owner | Deliverable |
|---:|---|---|
| 1 | Rust + bridge (this cycle) | New `Effect::AddChargeCounterManaOfChosenColor` Rust variant + parser + resolver + to_pydict + cross-engine forward/reverse arms. Substrate-only — Eternity Elevator stays DECLINED. |
| 2 | Python admit | `_python_aa_to_safe_dict` `tier_threshold` field round-trip + new `_printing_is_bridge_phase_4_spacecraft_eternity_elevator` predicate + `_eternity_elevator_card_def` builder + OR-chain admit registration. Eternity Elevator FLIPs DECLINED → ADMITTED at admit gate. |
| 3 | Bench | `tests/test_the_eternity_elevator_parity.py` real-EoE probe (parse SoT + bridge round-trip + Rust synthetic acceptance + end-to-end loader admit + Python-side resolve smoke). Register in `scripts/measure_pool_parity.py::PROBE_MODULES`. **Eternity Elevator: ADMITTED → PROBED.** |
| 4 | Doc | Regen `docs/POOL_PARITY.md`; Spacecraft BLOCKED-SG row 1 → 0; PROBED tier bumps; **Spacecraft 8/8 = FULL CAMPAIGN CLOSURE.** |

---

## 6. SEARCH_LIMITATIONS entries — to add at C1

1. **Rust `Effect::AddChargeCounterManaOfChosenColor` uses
   deterministic options[0]="W" color choice.** Location:
   `state_ops_resolve.rs::apply_effect`. Shortcut: agent's
   `choose_mana_color` callback is NOT consulted — the Rust resolver
   always mints colorless-coin-equivalent `W` coins. Why OK at C1:
   substrate-only — Eternity Elevator stays DECLINED at admit gate, so
   the resolver is exercised by synthetic unit pins only. Fix-scope:
   ~1 cycle to plumb a decision callback (round-28 precedent applies).
   Impact: 0 today (no live consumer); strength: future divergence
   between agent-chosen color and the deterministic `W` fallback at
   resolution time — at C2 FLIP the Python-side `Agent.choose_mana_
   color` may pick a different color, breaking byte-equality probes.
   The C3 real-EoE probe will exercise this — likely needs the
   decision callback before the probe can pass.

2. **Rust `Effect::AddChargeCounterManaOfChosenColor` reads
   `obj.charge_counters` synchronously at resolve time.** Location:
   `state_ops_resolve.rs::apply_effect`. Note: matches Python's
   `state.resolving_source.charge_counters` lookup at
   `mana.py:160`; both engines compute X at resolve time, not at AA-
   activation time. No divergence — documented for symmetry with the
   trigger-shape `tier_threshold` legal-emit gate at
   `state_ops_legal.rs:3328`. No fix needed.
