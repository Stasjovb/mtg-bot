# Carrier-AA substrate — Phase 1.5 design

**Status:** DESIGN — docs-only scoping for the `{N}, {T}` cost-shape
widen. No code change lands with this doc.

**Author:** Carrier-AA Phase 1.5 design lane, Worker A
(`feature/carrier-aa-phase-1-5-design-p1`), 2026-05-25.

**Predecessor:** Phase 1 closed at C2 (`0cc08732`):
* C1 substrate `226c9738` — Rust `CardDef.activated_abilities` field
  + two new `Effect` variants (`RegenerateTargetCreature`,
  `UntapTargetLand`) + `GameObject.regeneration_shield` +
  cross-engine bridge arms + mutual-exclusion guard.
* C2 FLIP `0cc08732` — Python bridge `_python_aa_to_safe_dict` +
  admit predicate `_aa_is_phase1_sub_shape_a` +
  `_printing_is_bridge_simple_carrier_aa_land` admit gate +
  `_carrier_aa_land_card_def` builder wired into
  `_filter_deck_to_bridge_supported` OR-chain. Swarmyard DECLINED →
  ADMITTED. Deserted Temple stays DECLINED — **honest-stop** on the
  STRICT bare-`{T}` gate (its cost is `{1}, {T}`, not bare `{T}`).

**Companion docs:** `docs/CARRIER_AA_SUBSTRATE_PHASE_1_DESIGN.md`
(the campaign-shape predecessor — §2.1 30-card walk, §3 out-of-scope
matrix, §5 admit predicate, §10.3 sibling-swap clause). This Phase
1.5 doc inherits its definitions; cross-references below cite the
Phase 1 doc by section.

---

## 0. Executive summary

Phase 1.5 is a **sub-cycle** of the Carrier-AA substrate that widens
the per-AA cost gate from "STRICT bare `{T}` (`cost.mana is None`)"
to "`{N}, {T}` shape — `cost.mana` is generic-only (no colored, no
hybrid, no X-pips) + `tap_self=True`". The widen is **Python-only**;
Rust's `parse_activation_cost` already accepts the `mana` key and
`pay_mana_cost_pub` already routes generic mana for AAs (verified §3
below). No `.pyd` rebuild needed.

**Headline admit:** **Deserted Temple** (`{1}, {T}: Untap target
land`) admits IMMEDIATELY on the cost-gate widen — its Effect
`UntapTargetLand` is ALREADY in the Phase-1 admit set (shipped by
C1's Rust port). Zero new Effect-class ports are required for the
Phase-1.5a admit.

**Sibling-swap clause (Phase 1 doc §10.3) candidates** (each needs
its own per-Effect port, scoped as sub-slices here):
* **Terrain Generator** — `{2}, {T}: PutBasicLandFromHandOntoBattlefieldTapped`
  (+1 card; small Effect port — search-hand + ETB-tapped primitive).
* **Thespian's Stage** — `{2}, {T}: BecomesCopyOfTargetLand`
  (+1 card; copy-effect / layer-interaction port — material cost,
  candidate for **deferral to Phase 2+** if Cycle 2 lands without).
* **Mystifying Maze** — `{4}, {T}: ExileTargetAttackingCreatureUntilEndStep`
  (+1 card; exile + EoT-return delayed-trigger port — material cost,
  candidate for **deferral to Phase 2+**).

**Out of Phase 1.5 explicitly:** Nesting Grounds (`{1}, {T}`
sorcery-speed — sorcery-speed rider is Phase N per Phase 1 §3.4),
Lavaclaw Reaches / Wandering Fumarole (`{N}{C}{C}` cost — colored
mana + `BecomeLandCreatureUEOT` rider, Phase N per §3.7), Petrified
Field (`{T}, Sac:` — Phase 2 per §3.1), Scavenger Grounds (Land —
Desert, `{T}, Sac-a-Desert:` — Phase 2 per §3.1).

**Phase-1.5 expected admit-set delta** (the §2.1 30-card row, at
this HEAD):
* **Phase 1.5a (cost-gate widen only):** +1 card (Deserted Temple).
* **Phase 1.5b (+ Terrain Generator Effect port):** +1 card (+1
  total = +2 from Phase 1 baseline).
* **Phase 1.5c (+ Thespian's Stage Effect port; if not deferred):**
  +1 card (+1 total = +3 from Phase 1 baseline).
* **Mystifying Maze** explicitly deferred (EoT-return-rider port is
  larger than a Phase-1.5 cycle should carry).

**Phase 1.5 deck-leverage (17lands):** Per Phase 1 doc §2.1 the
per-card 17lands counts read 0 in the worktree-local pool walk; the
aggregate 34,470-deck row is the source of truth and the Phase-1.5
slice is a small fraction of that row. The headline leverage is
**substrate continuity** — proves the Carrier-AA admit gate
generalizes beyond bare `{T}`, paving the Phase-2 `{T}, Sac:` and
Phase-3 `<empty-cost>` widens that follow the same shape.

**Estimated cycle count: 1-2 cycles total** (vs Phase 1's 4 cycles).
See §7.

---

## 1. Background — Phase 1 closure recap and the honest-stop

Phase 1 shipped the non-token Carrier-AA admit substrate at sub-
shape A — bare `{T}`-cost single-bridged-Effect Land carrier (Phase
1 doc §2.3). The STRICT cost gate at
`trajectory.py::_aa_is_phase1_sub_shape_a:8515` is:

```python
if cost.mana is not None:
    return False
```

This admits Swarmyard (`{T}: Regenerate target creature`) and
declines Deserted Temple (`{1}, {T}: Untap target land`) honestly.
The decline is positive — the admit gate's STRICT contract is what
keeps the §2 silent-mistranslation surface flat. The C2 docstring at
`trajectory.py:8586-8590` explicitly anticipates this Phase 1.5:

> Deserted Temple HONESTLY DECLINES here (cost ``{1}, {T}``, not
> bare ``{T}``) — the STRICT cost-shape gate is the contract.
> Deserted Temple stays in ``covered_by_construction`` until Phase
> 1.5 widens the cost-shape to ``{N}, {T}`` OR a sibling-swap
> brings in Terrain Generator / Thespian's Stage at bare ``{T}``.

The Phase 1 C2 pin
`test_aa_is_phase1_sub_shape_a_declines_deserted_temple_1T_cost` +
`test_filter_deck_to_bridge_supported_declines_deserted_temple`
guard the honest-stop. Phase 1.5 INVERTS these pins — Deserted Temple
DECLINED → ADMITTED at the cost-gate widen (mirror of C2's
Swarmyard FLIP).

---

## 2. Scope: widen the cost gate from bare `{T}` to `{N}, {T}`

### 2.1 The one-line widen

The Phase-1 cost gate
(`trajectory.py::_aa_is_phase1_sub_shape_a:8515`):

```python
if cost.mana is not None:
    return False
```

The Phase-1.5 cost gate widens to:

```python
if cost.mana is not None:
    if cost.mana.colored:
        return False
    if cost.mana.hybrid:
        return False
    if cost.mana.x_pips:
        return False
    if cost.mana.generic <= 0:
        return False
```

That is, `cost.mana` may be either `None` (bare `{T}`) OR a
`ManaCost` with ONLY a positive `generic` field set (no `colored`
list entries, no `hybrid` list entries, no X-pips). Equivalent to
"the activation cost adds `{N}` generic mana to the existing `{T}`
implicit cost, for any `N ≥ 1`".

### 2.2 What is NOT widened (admit predicate stays one disjunct)

The Phase-1.5 widen is **cost-gate-only**. The rest of
`_aa_is_phase1_sub_shape_a` stays unchanged — every other cost
field, every AA-level rider, the Effect-class gate. The printing-
level admit predicate
`_printing_is_bridge_simple_carrier_aa_land` is **unchanged** (every
printing-level rider still rejects). The
`_filter_deck_to_bridge_supported` OR-chain wiring is **unchanged**.
Phase 1.5 is the minimal cost-gate widen — one disjunct (the
Carrier-AA Land disjunct) widens in place.

### 2.3 Per-card admit delta (verify-first walk, 2026-05-25)

The complete per-card walk over the §2.1 30-card BLOCKED-SG row,
holding every gate except the cost-mana check constant (verify-first
output captured §13 below). The cards that PASS the widened cost
gate AND every other gate (with the Effect-class gate held
unchanged at `{RegenerateTargetCreature, UntapTargetLand}`):

| Card | AA cost | AA effect | Effect-class admit set | Phase 1.5 status |
|---|---|---|---|---|
| **Deserted Temple** | `{1}, {T}` | `UntapTargetLand` | **ALREADY in Phase 1 set** | **Phase 1.5a — admits with cost-gate widen alone, ZERO new Effect ports** |
| **Terrain Generator** | `{2}, {T}` | `PutBasicLandFromHandOntoBattlefieldTapped` | Phase 1.5b — port required | **Phase 1.5b candidate** (+1 Effect port) |
| **Thespian's Stage** | `{2}, {T}` | `BecomesCopyOfTargetLand` | Phase 1.5c — port required | **Phase 1.5c candidate** (+1 Effect port; HIGH complexity — copy-effect / layer interaction; LIKELY DEFERRED to Phase 2+) |
| **Mystifying Maze** | `{4}, {T}` | `ExileTargetAttackingCreatureUntilEndStep` | Phase 2+ — port required | **DEFERRED** (EoT-return delayed-trigger rider — Phase 2+ cost) |

Cards that PASS the cost-gate widen but FAIL elsewhere (each is
documented for the §3 out-of-scope matrix):

| Card | AA cost | Why it still declines |
|---|---|---|
| Nesting Grounds | `{1}, {T}` | AA `sorcery_speed=True` — Phase N per §3.4 |
| Lavaclaw Reaches | `{1}{B}{R}` | `cost.mana.colored` non-empty (no `tap_self`); `BecomeLandCreatureUEOT` rider — Phase N per §3.7 |
| Wandering Fumarole | `{2}{U}{R}` | same as Lavaclaw; Phase N per §3.7 |
| Petrified Field | `{T}, Sac:` | `cost.sacrifice_self=True` — Phase 2 per §3.1 |
| Scavenger Grounds | `{T}, Sac-a-Desert:` | `cost.sacrifice_a_desert=True` — Phase 2 per §3.1 |
| Ancient Tomb | `{T}` | `is_mana_ability=True` — Phase N per §3.3 |
| Meteor Crater | `{T}` | `is_mana_ability=True` — Phase N per §3.3 |
| Reflecting Pool | `{T}` | `is_mana_ability=True` — Phase N per §3.3 |

**Verify-first conclusion:** the cost-gate widen alone admits
**+1 card** (Deserted Temple); each sibling Effect-class port admits
exactly one more card. The 30-card row's admit delta is bounded
above by +4 (Deserted Temple + Terrain Generator + Thespian's Stage
+ Mystifying Maze) — every other card has a rider beyond
`{N}, {T}`-cost that would need an independent Phase-2+/Phase-N
substrate-extension to close.

### 2.4 Phase 1.5 admit-set tiering — sequencing

Phase 1.5a — **cost-gate widen only**:
* Widen `_aa_is_phase1_sub_shape_a`'s cost gate per §2.1.
* Invert the C2 Deserted Temple decline pins to admit pins.
* Real-EoE probe Deserted Temple (`tests/test_deserted_temple_parity.py`,
  inserted at the standard sentinel).
* Effect set unchanged: `{RegenerateTargetCreature, UntapTargetLand}`.

This is the **minimum demonstrable Phase 1.5 unit** — proves the
cost-gate widen is bridge-correct using an existing-ported Effect.

Phase 1.5b — **+ Terrain Generator Effect port**:
* Add `PutBasicLandFromHandOntoBattlefieldTapped` to the Rust
  `Effect` enum + parse / resolve / to_pydict arms (Phase 1 doc
  §4.2 shape).
* Extend `_python_aa_to_safe_dict`'s effect-dispatch + the Effect-
  class gate `_carrier_aa_phase_1_effect_classes()` to include the
  new class.
* Real-EoE probe Terrain Generator.

Phase 1.5c — **+ Thespian's Stage Effect port** (CONDITIONAL):
* `BecomesCopyOfTargetLand` is a CR-613 layer-1 copy-effect — it
  needs the Rust mirror to compute a copy of the target Land's
  printing dict on resolve, replacing the activator's
  Land-printing-pointer (or equivalent state-mirror primitive). The
  layer-interaction cost is material; recommend **DEFERRING this
  sub-slice to Phase 2+** until a generic copy-effect substrate is
  scoped (the same substrate would unblock Mirrorpool's `{T}, Sac:
  CopyTargetInstantOrSorceryYouControl` AA[0]).

**Sequencing recommendation:** ship Phase 1.5a as a single cycle.
Phase 1.5b is a small follow-up cycle if Terrain Generator's Effect
port is in-budget; Phase 1.5c is a separate substrate (deferred).

---

## 3. Out-of-scope (Phase 2 / 3 / N)

Phase 1.5 retains every Phase 1 out-of-scope clause unchanged
(Phase 1 doc §3.1-§3.7). The cost-gate widen does NOT touch:

* **`{T}, Sac:` shape** (Phase 1 §3.1) — `cost.sacrifice_self=True`
  remains a decline. Petrified Field, Mirrorpool, Ghost Vacuum,
  Keys to the House, All-Fates Scroll AA[1] stay in Phase 2.
* **`<empty-cost>` sorcery-speed Equipment cluster** (§3.2) —
  Atomic Microsizer, Auxiliary Boosters, Baseball Bat, Saw, Robe of
  Stars, Sliver Overlord stay in Phase 3.
* **Mana-ability AAs** (§3.3) — `is_mana_ability=True` remains a
  decline. Ancient Tomb, All-Fates Scroll AA[0], Grove of the
  Burnwillows, Haunted Screen, Lotus Field, Meteor Crater,
  Reflecting Pool, The Eternity Elevator stay in Phase N.
* **Tier-threshold / activate-only-once / room-half** (§3.4) — every
  Phase-N rider stays a decline. **Nesting Grounds** (sorcery-speed
  on a `{1}, {T}` cost) is decline-by-rider, not decline-by-cost,
  so the Phase-1.5 cost-gate widen does NOT admit it. Stays Phase N.
* **Multi-AA carriers** (§3.5) — `len(printing.activated_abilities)
  != 1` remains a decline. 10 cards stay in Phase 2+.
* **Creature carriers** (§3.6) — Sliver Overlord stays Phase N.
* **BecomeLandCreatureUEOT-with-rider** (§3.7) — Lavaclaw Reaches,
  Wandering Fumarole stay Phase N (also blocked by `tap_self=False`
  + colored-mana on the cost; even the Phase 1.5 cost-gate widen
  doesn't reach them — they need the BecomeLand substrate AND a
  separate colored-mana cost-gate widen).

**Also explicitly out of Phase 1.5:**

* **Colored-mana cost shapes** (`{B}{R}, {T}` / hybrid / X). Phase
  1.5 admits ONLY pure-generic `{N}` mana cost. Colored / hybrid /
  X is **Phase 2** (per §3.7 land manland cards bring the X case
  too — Lavaclaw Reaches's `{X}{B}{R}: pump` is a granted AA, not
  the carrier AA, but the cost-shape Phase-2 widen ports the
  colored-mana cost-gate independently from the BecomeLand rider).
* **Mana-cost-with-conditions** (`{N}, {T}, Pay-life:` etc.). Phase
  1.5 ONLY widens the `cost.mana` field; every other `cost.*` bool
  stays a decline. Mixed-rider costs stay Phase 2+.
* **Multi-tap AAs** (tap multiple permanents you control as cost).
  Phase 1.5 keeps `cost.tap_permanent_you_control=False` as a
  decline. Tap-a-permanent-you-control costs are Phase N.

---

## 4. Rust-side spec — likely NO Rust changes

**Verify-first finding (live tree, main `245823d9`):**

* `rust/src/cards.rs::ActivationCost` already carries the `mana:
  ManaCost` field (line 9624; Slice 1 minimal field set per the
  pre-existing token-AA Bear-Caster substrate `{1}{G}, T: Draw a
  card`).
* `rust/src/cards.rs::parse_activation_cost` (line 15971) already
  reads the `mana` key from the registry dict (line 16001-16006):
  if present, deserializes via `parse_mana_cost` into `cost.mana`;
  if absent, `cost.mana` defaults to the all-zero `ManaCost`
  (semantically "free / no mana required").
* The unknown-key check at line 15977-15999 already whitelists
  `mana` (line 15978). No parser change is needed for Phase 1.5.
* `rust/src/state_ops_legal.rs::activate_ability_dict` (line 603,
  per the AA-activation emission walk documented at line 287-342)
  already pays the cost via `pay_mana_cost_pub`
  (`state_ops_cast.rs:231`) and taps the source for `tap_self`.
* The pool-can-cover affordability check
  (`state_ops_legal.rs:309-311`,
  `state_ops_decisions.rs::can_pay_mana_cost_internal:46`) already
  routes generic mana for AAs identically to spell casts (mirrors
  `pay_mana_cost`'s validation phase).
* The Rust `Effect::UntapTargetLand` variant + its parse / resolve
  / to_pydict arms shipped at C1 (`226c9738`). No new variant
  needed for the Phase 1.5a admit (Deserted Temple's Effect is
  already covered).

**Conclusion — Phase 1.5a needs ZERO Rust changes.** The `.pyd` race
rule does not apply; the Phase 1.5a Rust slice is empty.

**Phase 1.5b** (if pursued — Terrain Generator) DOES need a Rust
slice: new `Effect::PutBasicLandFromHandOntoBattlefieldTapped`
variant + parse / resolve / to_pydict arms (sibling of the C1
variants per Phase 1 doc §4.2). The resolve arm must search the
activator's hand for a basic-Land card, put it onto the battlefield
tapped, and shuffle the library (CR 701.16-style search). The Python
reference is `effects/generic/land.py`'s
`PutBasicLandFromHandOntoBattlefieldTapped` class.

**Phase 1.5c** (Thespian's Stage, DEFERRED) needs the copy-effect
substrate — much larger than a per-Effect port.

---

## 5. Python spec — the cost-gate widen

### 5.1 `_aa_is_phase1_sub_shape_a` cost-gate widen

**File:** `src/mtg_bot/parity/trajectory.py`, lines 8513-8518.

**Before** (Phase 1):

```python
# Cost gate.
cost = aa.cost
if cost.mana is not None:
    return False
if not cost.tap_self:
    return False
```

**After** (Phase 1.5):

```python
# Cost gate — Phase 1.5: bare {T} OR {N}, {T} (generic-only mana).
cost = aa.cost
if not cost.tap_self:
    return False
if cost.mana is not None:
    # Phase 1.5 admits generic-only mana costs ({N}, {T} shape).
    # Colored / hybrid / X-pip mana costs are Phase 2+.
    if cost.mana.colored:
        return False
    if cost.mana.hybrid:
        return False
    if cost.mana.x_pips:
        return False
    if cost.mana.generic <= 0:
        # Should not happen — a ManaCost with all-zero fields would
        # be `None`, not an empty ManaCost — but defend in depth.
        return False
```

The docstring updates to reflect the new "bare `{T}` OR `{N}, {T}`"
shape; the comment about Deserted Temple (lines 8482-8484) is
removed (Deserted Temple now admits).

**Critical §2 contract preservation:** every other cost-field gate
(sacrifice_*, pay_life, requires_*, etc.) stays bit-identical. The
widen is **strictly additive** on the cost-mana axis; no other
field's contract loosens.

### 5.2 `_python_aa_to_safe_dict` — no change needed

**File:** `src/mtg_bot/parity/cross_engine.py`, lines 14091-14100.

The safe-dict builder already serializes generic-mana costs into
the Rust-shape dict (verified at lines 14093-14100). It also
already emits colored / hybrid keys, BUT those code paths are
unreachable post-widen because
`_aa_is_phase1_sub_shape_a` rejects every AA with `colored` /
`hybrid` / `x_pips` populated before reaching the safe-dict builder.
The §2 contract is preserved by the admit predicate, not the
safe-dict builder.

**Defense-in-depth check:** the existing builder emits the `mana`
dict whenever `cost.mana is not None`, regardless of which color
fields are populated. The bridge's `parse_activation_cost`
round-trip catches any unrider-admitted shape — but the admit
predicate already declines those, so no path lights up.

### 5.3 `_printing_is_bridge_simple_carrier_aa_land` — no change

The printing-level admit predicate stays bit-identical. The Phase
1.5 widen is per-AA only; the printing-level riders
(keywords, triggered_abilities, static_abilities, spell_effect,
warp_cost, kicker_cost, room_halves, loyalty, cost_reductions,
station_threshold, dynamic_pt_formula, ward_cost, extra card_types,
power/toughness, n_aa != 1) all retain their current contracts.

### 5.4 `_filter_deck_to_bridge_supported` OR-chain — no change

The Carrier-AA Land disjunct stays in its current position in the
OR-chain (after every existing Land disjunct, per Phase 1 doc §5.4).
Phase 1.5 widens within the disjunct; the chain shape is unchanged.

### 5.5 Effect-class gate — no change for Phase 1.5a

`_carrier_aa_phase_1_effect_classes()` stays
`{RegenerateTargetCreature, UntapTargetLand}` for Phase 1.5a.
Phase 1.5b extends to `{..., PutBasicLandFromHandOntoBattlefieldTapped}`
and updates the corresponding gate AND the
`_python_aa_to_safe_dict` effect-dispatch dict in lockstep (per
Phase 1 doc §5.3 in lockstep convention).

### 5.6 C2 invariant pin inversions

**File:** `tests/test_carrier_aa_phase_1_substrate_cycle_2.py`.

The Phase-1 C2 pins that guard Deserted Temple's honest-stop INVERT
in Phase 1.5a:

* `test_aa_is_phase1_sub_shape_a_declines_deserted_temple_1T_cost`
  → `test_aa_is_phase1_5_sub_shape_a_admits_deserted_temple_1T_cost`
  (synthetic ActivatedAbility with `{1}, {T}` cost + `UntapTargetLand`
  effect now PASSES the admit predicate).
* `test_printing_is_bridge_simple_carrier_aa_land_declines_live_deserted_temple`
  → `test_printing_is_bridge_simple_carrier_aa_land_admits_live_deserted_temple`
  (live Deserted Temple printing now passes
  `_printing_is_bridge_simple_carrier_aa_land`).
* `test_filter_deck_to_bridge_supported_declines_deserted_temple`
  → `test_filter_deck_to_bridge_supported_admits_deserted_temple`
  (loader admits Deserted Temple end-to-end).

Each inversion mirrors the C2 Swarmyard FLIP — the test docstrings
update to reference Phase 1.5 instead of Phase 1's honest-stop.

---

## 6. Test plan

### 6.1 Phase 1.5a unit pins

1. **`_aa_is_phase1_sub_shape_a` admits Deserted Temple's synthetic
   shape.** Build a synthetic `ActivatedAbility(cost=ActivationCost(
   tap_self=True, mana=ManaCost(generic=1)), effect=UntapTargetLand())`
   — predicate returns True.
2. **`_aa_is_phase1_sub_shape_a` declines colored-mana cost shapes.**
   Synthetic AA with `cost=ActivationCost(tap_self=True,
   mana=ManaCost(generic=0, colored=(('R', 1),)))` — returns False.
3. **`_aa_is_phase1_sub_shape_a` declines hybrid-mana cost shapes.**
   Synthetic AA with `mana=ManaCost(hybrid=(('R', 'G', 1),))` —
   returns False.
4. **`_aa_is_phase1_sub_shape_a` declines X-cost shapes.** Synthetic
   AA with `mana=ManaCost(x_pips=1)` — returns False.
5. **`_aa_is_phase1_sub_shape_a` continues to decline bare `{T}` +
   any AA-rider** (regression — Phase 1's rider gates still bite
   under Phase 1.5).
6. **`_aa_is_phase1_sub_shape_a` continues to decline `{T}, Sac:`**
   (`cost.sacrifice_self=True` still declines under Phase 1.5).
7. **`_python_aa_to_safe_dict` round-trips Deserted Temple's
   synthetic shape.** Build the synthetic AA from pin 1, feed through
   `_python_aa_to_safe_dict` → `_aa_dict_to_python_activated_ability`
   round-trips byte-equal.

### 6.2 Decline-set regression — the 30-card walk

8. **Live-printing parametrized walk** over the 30-card Carrier-AA
   row, checking exactly the cards listed in §2.3 admit (Swarmyard +
   Deserted Temple) AND every other card declines with the
   documented reason. Same shape as the existing C2 walk pin
   (`test_carrier_aa_phase_1_substrate_cycle_2.py:298`).

9. **Subsystem-attribution pin:** exactly 2 EoE printings pass
   `_printing_is_bridge_simple_carrier_aa_land` (Swarmyard + Deserted
   Temple) — the Phase-1.5a positive set is exhaustive over the live
   EoE pool.

### 6.3 Real-EoE Deserted Temple parity probe

10. **`tests/test_deserted_temple_parity.py`** — real-EoE per-card
    probe (inserted at the
    `# === PHASE5_PROBES_INSERT_ABOVE_THIS_LINE ===` sentinel via
    `MODULE_FILE` symlink, batch-13 EEEE-idiom convention). Asserts
    byte-equal mirror through:
    * baseline (Deserted Temple in play untapped, controller has
      `{1}` floating, no target tapped land — state unchanged after
      passing priority);
    * untap-a-tapped-Forest line (controller activates `{1}, {T}:
      Untap target land` targeting a tapped Forest — the Forest's
      `tapped` bit flips false on both engines, Deserted Temple's
      `tapped` bit flips true on both engines, `{1}` is consumed
      from the floating pool on both engines, mana-pool state is
      byte-equal post-resolve).
    Uses a scripted picker shim (`tests/parity/_picker_shims.py`)
    forcing the AA activation — same convention as Phase 1's
    Swarmyard probe (Phase 1 doc §7.3).

### 6.4 Pool-parity row delta

11. **`tests/test_measure_pool_parity.py` regen** confirms +1 card
    in PROBED tier (Deserted Temple) and -1 card from the BLOCKED-SG
    Carrier-AA row; aggregate row breakdown shifts to (29 cards
    remaining in the BLOCKED-SG Carrier-AA row).

### 6.5 Phase 1.5b additional pins (CONDITIONAL — if Terrain Generator ships)

12. Synthetic AA pin for `PutBasicLandFromHandOntoBattlefieldTapped`
    + the `{2}, {T}` cost shape — admit predicate returns True.
13. Live Terrain Generator passes
    `_printing_is_bridge_simple_carrier_aa_land`.
14. Real-EoE probe `tests/test_terrain_generator_parity.py` —
    activate `{2}, {T}: search-and-put-basic-land-tapped`, assert
    library shuffles deterministically and the basic Land enters
    tapped on both engines, byte-equal.

### 6.6 Pre-existing parity gate

15. **`tests/test_parity_smoke.py + test_cross_engine_etb_triggers.py
    + test_trajectory_parity.py + test_trajectory.py +
    test_measure_pool_parity.py`** all stay green — no Phase-1 pin
    regression. The C1 pins continue to pass (no Rust change in
    Phase 1.5a means the Rust-side substrate stays bit-identical).

---

## 7. Estimated cycle count

Phase 1.5 is a **sub-cycle** — much smaller than Phase 1's 4-cycle
landing.

| Cycle | Owner | Deliverable |
|---:|---|---|
| 1 | Python/bridge agent | Phase 1.5a: cost-gate widen in `_aa_is_phase1_sub_shape_a` + C2 decline-pin inversions + the 7 unit pins (§6.1) + the 30-card decline walk regression (§6.2) + Deserted Temple real-EoE probe (§6.3) + pool-parity regen (§6.4). **No Rust slice.** |
| 2 (optional, CONDITIONAL) | Rust + Python agent | Phase 1.5b: Rust `Effect::PutBasicLandFromHandOntoBattlefieldTapped` variant (parse / resolve / to_pydict arms) + Python `_python_aa_to_safe_dict` effect-dispatch arm + admit-set widen + the 3 additional pins (§6.5) + Terrain Generator real-EoE probe. **One Rust slice — gated on `.pyd` race coordination.** |

**Estimated total: 1-2 cycles for Phase 1.5.** Phase 1.5a is the
minimum unit (always ships); Phase 1.5b is a small follow-up
conditional on the Terrain Generator Effect port being in-budget.
Phase 1.5c (Thespian's Stage / copy-effects) is **deferred to a
separate copy-effect substrate** that would also unblock Mirrorpool
AA[0].

**Cost driver:** Phase 1.5a is dominated by the test-pin authoring
(7 unit pins + the decline-set parametrize + 1 real-EoE probe);
the production code change is ~10 lines of cost-gate widen +
docstring update.

---

## 8. SEARCH_LIMITATIONS.md entries (with Phase 1.5 cycle 1)

Two entries (the Phase 1 entries 1-3 stay; Phase 1.5 amends and
adds one):

* **Amend Phase 1 SL entry 1** ("Carrier-AA Phase 1 admits only
  the bare `{T}:` single-AA single-bridged-Effect non-token Land
  sub-shape"). The Phase-1.5 amendment widens the cost-shape clause:
  "bare `{T}:` OR `{N}, {T}:` (generic-only mana, no colored /
  hybrid / X-pip) single-AA single-bridged-Effect non-token Land
  sub-shape; colored-mana / hybrid / X-cost shapes deferred to
  Phase 2; `{T}, Sac:`, mana-ability, sorcery-speed,
  activate-only-once, tier-threshold, room-half, multi-AA, Creature-
  carrier shapes still deferred." Failure mode and fix-scope
  unchanged.

* **New Phase 1.5 SL entry** (only if Phase 1.5b ships): "Phase 1.5b
  ports `PutBasicLandFromHandOntoBattlefieldTapped` Effect at the
  minimum resolution semantics; library-shuffle determinism is
  byte-equal on both engines via the existing PRNG seam." Same
  shape as Phase 1's SL entry 2.

---

## 9. Rejected alternatives

### 9.1 Skip Phase 1.5, jump straight to Phase 2

**Rejected — Phase 1.5 is the bridge proof.** Phase 1 closed at +1
card (Swarmyard); Phase 2's `{T}, Sac:` widen carries `sacrifice_self
=True`'s LTB-routing semantics + 5 candidate cards' worth of new
Effect ports (Petrified Field's `ReturnTargetLandFromGraveyardToHand`,
Mirrorpool's two Copy effects, Ghost Vacuum's exile, Keys to the
House's library-search, All-Fates Scroll AA[1]'s draw-by-multiplier).
Phase 1.5 isolates the cost-gate widen on the cleanest axis (pure-
generic mana) so any §2 silent-mistranslation surfaces in Phase 1.5
before Phase 2 stacks additional rider surface on top. **The
generic-mana cost-gate widen is a structural primitive every later
Phase reuses.**

### 9.2 Widen cost gate to include colored / hybrid / X in Phase 1.5

**Rejected — broader rider surface.** Colored mana adds the
pip-matching requirements (CR 202.3) which both engines must route
identically; hybrid adds the choose-color rider; X adds the X-pip
declaration at activation time. Each is its own admit-gate widen
with its own real-EoE probe surface. Phase 1.5 stays generic-only
to keep the per-cycle landing small and the §2 contract narrow.

### 9.3 Defer Deserted Temple to Phase 2 and pilot Terrain Generator first

**Rejected — Deserted Temple is the zero-cost pilot.** Deserted
Temple's Effect (`UntapTargetLand`) is ALREADY in Phase 1's admit
set (shipped at C1). Admitting Deserted Temple in Phase 1.5a
requires ZERO new Effect ports — it's the minimum-cost
demonstration that the cost-gate widen is bridge-correct. Piloting
Terrain Generator first would conflate "cost-gate widen works" with
"Effect-class port works" in the same cycle; piloting Deserted
Temple first isolates the cost-gate widen. Terrain Generator (and
any later siblings) ride the proven-correct cost-gate widen.

### 9.4 Land Phase 1.5b in the same cycle as Phase 1.5a

**Rejected — separation of concerns.** Phase 1.5a is a Python-only
change (no `.pyd` rebuild, no Rust race with parallel workers).
Phase 1.5b requires a Rust slice (new `Effect` variant). Folding
both into one cycle adds the Rust-rebuild cost to the Python-only
gate-widen lane and increases the cross-engine surface that has to
be verified at landing time. Two cycles separates the concerns
cleanly and keeps the `.pyd` race rule honest.

### 9.5 Pilot Thespian's Stage instead of (or in addition to) Terrain Generator

**Rejected — copy-effect cost.** `BecomesCopyOfTargetLand` is a
CR-613 layer-1 copy effect — replacing the activator's printing-
pointer on the battlefield with the target Land's printing-pointer.
The Rust mirror needs a per-`GameObject` "copy-of" pointer +
resolve-time copy primitive + interaction with the existing
mana-ability auto-wire (the copied Land's mana abilities must
register). This is its own substrate, not a per-Effect port.
Deferring Thespian's Stage to a copy-effect substrate that also
unblocks Mirrorpool AA[0]'s copy-target-instant-or-sorcery (Phase 2
candidate) gives a multi-card payoff for that substrate; bundling
it with Phase 1.5b gives a single-card payoff for the same Rust
cost. **Better to scope Thespian's Stage and Mirrorpool's copy AAs
together in a future copy-effect substrate.**

---

## 10. Acceptance / sign-off

Phase 1.5 is complete and ready to merge to `main` when:

1. The cost-gate widen pins (§6.1) all pass (7 pins).
2. The 30-card decline-set walk (§6.2) confirms exactly Swarmyard +
   Deserted Temple admit and 28 cards decline with documented
   reasons.
3. The Deserted Temple real-EoE probe (§6.3) passes byte-equal on
   both engines through baseline + untap-a-tapped-Forest line.
4. Pool-parity regen (§6.4) lands +1 card in PROBED tier (Deserted
   Temple); BLOCKED-SG Carrier-AA row shrinks from 29 to 28.
5. The amended SL entry (§8) lands alongside the code change.
6. The full parity gate (`tests/test_parity_smoke.py +
   test_cross_engine_etb_triggers.py + test_trajectory_parity.py +
   test_trajectory.py + test_measure_pool_parity.py`) stays green
   (31/31 on the measure-pool-parity module specifically).

Phase 1.5b (CONDITIONAL) adds:

7. The Rust `Effect::PutBasicLandFromHandOntoBattlefieldTapped`
   substrate lands; the .pyd rebuilds clean.
8. The 3 Phase-1.5b additional pins (§6.5) all pass.
9. The Terrain Generator real-EoE probe passes byte-equal.
10. Pool-parity regen lands +1 additional card (Terrain Generator)
    in PROBED tier.

---

## 11. Cross-references

* `docs/CARRIER_AA_SUBSTRATE_PHASE_1_DESIGN.md` — the parent
  campaign-shape doc. §2.1 30-card walk + §2.3 sub-shape selection
  + §3 out-of-scope matrix + §5 admit predicate + §10.3 sibling-swap
  clause + §13 enumeration regen script. Phase 1.5 inherits all of
  these.
* `src/mtg_bot/parity/trajectory.py:8474-8635` —
  `_aa_is_phase1_sub_shape_a` + `_printing_is_bridge_simple_carrier_aa_land`
  + `_carrier_aa_land_card_def` (the one-line widen site at line
  8515).
* `src/mtg_bot/parity/cross_engine.py:14031-14150` —
  `_python_aa_to_safe_dict` (already serializes generic mana, no
  change needed).
* `rust/src/cards.rs:9614-9784` — `ActivationCost` struct (already
  carries `mana: ManaCost`, no change needed).
* `rust/src/cards.rs:15958-16060` — `parse_activation_cost` (already
  parses the `mana` key, no change needed).
* `rust/src/state_ops_legal.rs:287-342` — AA-activation emission walk
  (already pays mana cost via `pay_mana_cost_pub`, no change needed).
* `rust/src/state_ops_cast.rs:231` — `pay_mana_cost_pub` (re-export
  for the AA-activation site; routes generic-only mana identically
  to spell costs).
* `tests/test_carrier_aa_phase_1_substrate_cycle_2.py:224-407` — the
  C2 invariant pins guarding Deserted Temple's honest-stop (the
  inversion targets for Phase 1.5a).
* `src/mtg_bot/effects/base.py:368-442` — Python's `ActivationCost`
  + `ManaCost` dataclasses (the cost-component shape the widen
  reads).
* `src/mtg_bot/effects/generic/tap.py:178` — Python's
  `UntapTargetLand` (Deserted Temple's Effect — already ported to
  Rust at C1).
* `src/mtg_bot/effects/generic/land.py` —
  `PutBasicLandFromHandOntoBattlefieldTapped` (Phase 1.5b candidate;
  unported to Rust).

---

## 12. Sequencing recommendation

**Recommended sequencing for Phase 1.5 landing:**

1. **Ship Phase 1.5a as a single Python-only cycle.** No `.pyd`
   rebuild — parallel work with any Rust-side worker (e.g.
   Worker B's Carrier-AA Phase 1 C3 Swarmyard probe + SBA-consume
   Rust slice) is race-free.
2. **Pause for parity-gate confirmation** at 1.5a landing — the
   31/31 measure-pool-parity baseline holds with +1 card in PROBED
   tier.
3. **Phase 1.5b (Terrain Generator) — conditional.** Schedule a
   small Rust slice if `PutBasicLandFromHandOntoBattlefieldTapped`'s
   Effect-class port is in-budget. Coordinate the `.pyd` rebuild
   under the standard substrate-landing convention (one Rust slice
   per cycle).
4. **Defer Phase 1.5c (Thespian's Stage) and Mystifying Maze**
   pending a separate copy-effect substrate scoping doc OR a
   delayed-trigger / EoT-return substrate scoping doc (each is its
   own multi-card payoff).
5. **Next Carrier-AA campaign milestone after Phase 1.5:** Phase 2
   `{T}, Sac:` widen (Phase 1 doc §3.1, 5 candidate cards) — the
   Phase 1.5 cost-gate widen + the Phase-2 cost-sacrifice-self
   widen compose into the `{N}, {T}, Sac:` admit predicate that
   covers most cost-shape combinations.

---

## 13. Verify-first walk reproduction

The §2.3 admit-delta table was verified by a one-off walker
(not committed) over the live `OracleParserCardSource` at HEAD
`245823d9`, holding every gate of
`_aa_is_phase1_sub_shape_a` constant EXCEPT the cost-mana check
(widened per §2.1). The walker:

```python
from mtg_bot.cards.parser.source import OracleParserCardSource
ps = OracleParserCardSource().get_printings()
carriers = [
    # Phase 1 doc §2.1 30-card list:
    "All-Fates Scroll", "Ancient Tomb", "Atomic Microsizer",
    "Auxiliary Boosters", "Baseball Bat", "Blast Zone",
    "Contested War Zone", "Deserted Temple", "Ghost Vacuum",
    "Grove of the Burnwillows", "Haunted Screen",
    "Keys to the House", "Lavaclaw Reaches", "Lotus Field",
    "Meteor Crater", "Mirrorpool", "Mystifying Maze",
    "Nesting Grounds", "Petrified Field", "Pinnacle Starcage",
    "Reflecting Pool", "Robe of Stars", "Saw",
    "Scavenger Grounds", "Sliver Overlord", "Swarmyard",
    "Terrain Generator", "Thespian's Stage",
    "The Eternity Elevator", "Wandering Fumarole",
]
for name in carriers:
    p = ps[name]
    # ... walk per §2.3 widened-cost-gate logic, log results ...
```

The full walker output was logged 2026-05-25 during this design
lane; the §2.3 table is the canonical summary. To regenerate at a
future HEAD, re-run the walk (the Phase 1 doc §13 regeneration
script is the parent reference).
