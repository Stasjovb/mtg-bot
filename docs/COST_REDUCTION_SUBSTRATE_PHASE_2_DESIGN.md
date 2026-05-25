Generated 2026-05-25 (post `cost-reduction-phase-1-cycle-4-
lashwhip-probe-p1`, merge `6c4ee310` — Phase 1 closure). **Design
only — NO production / `_SAFE_*` / Rust change in this slice; no
gate run beyond `tests/test_measure_pool_parity.py` 31/31** (docs +
read-only scout against the live tree). This doc scopes
cost-reduction substrate **Phase 2** in the campaign sequencing the
Phase 1 design doc (`docs/COST_REDUCTION_SUBSTRATE_PHASE_1_DESIGN.md`
at `4b94f844`) committed to. Every file:line below is verified
against the live tree at main `6c4ee310`.

> **Relationship to `docs/COST_REDUCTION_SUBSTRATE_PHASE_1_DESIGN.md`.**
> That doc was the campaign-level entry point for the 4-cycle
> Phase 1 closure (sub-shape A — spell-local `CostReduction` with
> boolean conditions, Gigastorm Titan + Lashwhip Predator, 24,908
> 17lands decks). Phase 1 LANDED CLEAN today: C1 substrate
> (`3683e62e`), C2 FLIP (`8593b0fb`), C3 Gigastorm probe
> (`1f13f092`), C4 Lashwhip probe (`6c4ee310`). **This doc takes
> over the campaign-scoping role for Phase 2** — same overall
> sub-shape decomposition, narrowed to sub-shapes B + C
> (`ExternalCostReduction`-bearing carriers), explicitly deferring
> sub-shape D (Fungal's variable-X) to Phase 3 and planeswalker-
> loyalty-cost reductions to Phase 4. The Phase 1 doc's §3.1
> sequenced sub-shapes B + C as "Phase 3"; the post-closure
> reconciliation (this doc) **promotes them to Phase 2** on the
> grounds that (a) variable-X sub-shape D is the ONE remaining
> shape requiring a new variable-multiplier evaluation path in
> Rust, so it is naturally the largest leftover slice and is
> deferred to its own phase, and (b) the externals-scan + the
> two new `ExternalCondition` variants (`NthSpellThisTurn`,
> `PerControlled(IsArtifact())`) compose cleanly with the Phase-1
> substrate's existing `apply_cost_reductions_rust` hook. The
> Phase 1 doc's §3.4 planeswalker-loyalty-cost framing remains
> canonical and is restated here as Phase 4 (out of substrate).

# cost-reduction substrate Phase 2 — campaign scoping doc (sub-shapes B + C: 2 cards / 15,575 17lands decks)

## 0. Executive summary

Phase 1 closed today with **2 / 5 cost-reduction-single-gated cards
PROBED** (Gigastorm Titan + Lashwhip Predator — `3683e62e` /
`8593b0fb` / `1f13f092` / `6c4ee310`), unblocking 24,908 17lands
decks (46 % of the cost-reduction single-gated pool). Three cards
remain DECLINED behind the Phase-2/3 sub-shape gates — **3 cards /
28,740 decks per the post-C4 POOL_PARITY rollup**:

| Card | Sub-shape | Decks | Gate |
|---|---|---:|---|
| **Uthros Psionicist** | B (external + `NthSpellThisTurn(2)`) | ~14,767 | this doc |
| **Fungal Colossus** | D (variable-X `PerDifferentlyNamedLand`) | ~13,165 | **Phase 3** |
| **Sami, Wildcat Captain** | C (external + `PerControlled(IsArtifact())`) | ~808 | this doc |

This doc scopes Phase 2: admit sub-shapes B + C — the 2 cards
**Uthros Psionicist + Sami, Wildcat Captain** (15,575 17lands
decks combined — 54 % of the cost-reduction REMAINING single-gated
deck count and the largest self-contained `ExternalCostReduction`
slice). Phase 2 explicitly **defers** Fungal Colossus (variable-X
multiplier — Phase 3) and the planeswalker-loyalty-cost rider
(Phase 4 — out of substrate).

Estimated campaign scope, calibrated against the Phase 1 closure
(4 cycles for 2 cards on top of the substrate landing):
**~4 Rust cycles total for cost-reduction Phase 2** — 1 substrate
landing + 1 admit-predicate cycle + 1 per-card real-EoE probe
cycle each for Uthros Psionicist and Sami, Wildcat Captain (the
same per-card cycle count Phase 1 executed).

## 1. Background — why these sub-shapes, why now

### 1.1 Phase 1 closure recap

Phase 1 closed CLEAN across 4 cycles today:

- **C1 substrate** (`3683e62e`) — Rust `CardPrinting.cost_reductions:
  Vec<CostReduction>` field + `CostReduction` struct + `Condition`
  enum (2 variants: `AnotherSpellCastThisTurn`,
  `OpponentsControlAtLeast{TypeFilter::Creature, count}`) +
  `TypeFilter` enum (1 variant: `Creature`) + `parse_printing`
  arm + hard-error on unknown `condition_kind`. `eff()` stayed
  identity this cycle.
- **C2 FLIP** (`8593b0fb`) — `apply_cost_reductions_rust(state,
  caster_idx, printing, base) -> ManaCost` shipped at
  `rust/src/state_ops_legal.rs:764` and wired into all 6
  `CastSpell`-emission affordability probes (hand instant +
  hand sorcery on base mana_cost AND warp_cost, warp-from-
  graveyard, warp exile-recast, Lightstall surcharge) +
  `cast_creature`'s post-pay site. CardDef
  `cost_reductions: tuple[tuple[int, str, tuple], ...]` field +
  `_spec_card_to_printing_dict` emit +
  `_card_def_to_python_printing` reverse arm. New admit predicate
  `_printing_is_bridge_pure_cost_reduction_creature` at
  `src/mtg_bot/parity/trajectory.py:4940`. Both Phase-1 carriers
  flipped DECLINED → ADMITTED in a single cycle.
- **C3 Gigastorm probe** (`1f13f092`) — per-card real-EoE
  cross-engine byte-equal probe at
  `tests/test_probe_gigastorm_titan_real_eoe_cost_reduction.py`,
  6 pins (parser SoT, printing-surface attrs, admit
  classification, byte-equal both seats reduced + full cost,
  decline-set negative pin).
- **C4 Lashwhip probe** (`6c4ee310`) — sibling per-card probe
  for Lashwhip Predator, same 6-pin shape. **Phase 1 closure
  complete.**

The Phase 1 substrate is the foundation Phase 2 extends:

- `Player.spells_cast_this_turn: i32` is already a Rust state
  field (landed pre-Phase-1 as MMM Pin 1; `state.rs:1017`,
  fingerprint-threaded, incremented post-pay at every Rust cast
  primitive — `state_ops_cast.rs:1257 / :1537 / :1828 / :3253`).
  **Phase 2 inherits this without modification** — see §4.4.
- `apply_cost_reductions_rust` is `pub(crate)` and used at 7
  call sites (1 cast site, 6 legal-decision sites — verified by
  grep). Phase 2 extends the helper's body with the externals
  scan; the call sites stay the same.
- `_printing_is_bridge_pure_cost_reduction_creature` is the
  named admit-predicate site; Phase 2 either widens its guard or
  adds a sibling predicate (see §6 for the decision).

### 1.2 The post-C4 declined inventory

Verified live against `OracleParserCardSource` at main `6c4ee310`
(per the post-Phase-1 admit-gate audit + the SUBSYSTEM_BLOCKED
inventory rollup):

| Card | live parsed shape | mana_cost | 17lands decks | other riders | Phase |
|---|---|---|---:|---|---|
| **Uthros Psionicist** | `external_cost_reductions=(ExternalCostReduction(amount=2, condition=NthSpellThisTurn(n=2)),)` | (verified live) | ~14,767 | (verify creature-purity at C2) | **2** |
| **Sami, Wildcat Captain** | `external_cost_reductions=(ExternalCostReduction(amount=1, condition=PerControlled(IsArtifact())),)` | (verified live) | ~808 | (verify creature-purity at C2) | **2** |
| **Fungal Colossus** | `cost_reductions=(CostReduction(amount=1, condition=PerDifferentlyNamedLand()),)` | (verified live) | ~13,165 | (n/a) | **3** |

**Phase-2 deck total: 15,575 17lands decks** (= 14,767 + 808).
Sub-shape D's deferral (Fungal, 13,165 decks) is the principled
"variable-X needs its own substrate" deferral — see §3.1.

Both Phase-2 cards' shapes satisfy the minimal-scope criteria:

- The rider lives on `printing.external_cost_reductions` (NOT
  `printing.cost_reductions`) — the structural distinction
  between spell-local-self-reduction and battlefield-scan-of-
  other-permanents reductions; verified at
  `src/mtg_bot/cards/base.py:325-345` for the
  `ExternalCostReduction` dataclass + `:771` for the printing
  field.
- The conditions are EXACTLY two new structural variants:
  `NthSpellThisTurn(n)` (`effects/conditions.py:248-262`) and
  `PerControlled(filter)` with `filter == IsArtifact()`
  (`effects/conditions.py:405-434` + `object_predicates.py:132`).
- `cost_reductions == ()` on both (verified live — the externals
  rider lives ONLY on the granting permanent, not on its own
  spell-local list).
- No `kicker_cost`, `impending_cost`, `warp_cost`, no
  `room_halves`, no loyalty, no station threshold, no
  dynamic-P/T formula, no ward (verify at C2 against the live
  printing the same way Phase-1 verified Gigastorm + Lashwhip).

The ONLY blocking feature on both Phase-2 cards is the
`external_cost_reductions` tuple. Strip it and each card is a
pure bridge-simple creature.

### 1.3 Why B + C ship together (and D doesn't)

The Phase-1 design doc's §3.1 originally sequenced these three
cards across Phases 2 and 3. Post-closure, the principled split
is by **what new Rust evaluation path each sub-shape requires**:

- Sub-shape B (Uthros, `NthSpellThisTurn`) — new `ExternalCondition`
  variant + new `ExternalCostReduction` struct + new battlefield-
  scan loop in `apply_cost_reductions_rust`. The condition itself
  reads the EXISTING `Player.spells_cast_this_turn` counter
  (Phase-1 inherits the work; the SoT comparison is `==(n-1)`
  rather than `>=1`).
- Sub-shape C (Sami, `PerControlled(IsArtifact())`) — same struct
  + battlefield-scan loop as B + the SAME new `ExternalCondition`
  layer + a second `ExternalCondition::PerControlled` variant +
  a new `TypeFilter::Artifact` token. Crucially, the
  `PerControlled` evaluation is a `matches() && multiplier()`
  pair where `multiplier()` is a state-derived count (= count of
  the caster's artifact permanents). This is the FIRST variable-
  multiplier evaluation Rust will perform.
- Sub-shape D (Fungal, `PerDifferentlyNamedLand`) — same
  `multiplier` shape as C BUT evaluated on the spell's own
  `cost_reductions` (the spell-local list, not the externals
  list), AND the multiplier reads a SET-of-names accumulator
  (distinct names) rather than a count of permanents. Two
  orthogonal differences from C: (1) it lives on the spell-local
  side, so the host card is what reduces ITS OWN cost (no
  battlefield scan of other permanents), and (2) the multiplier
  is a `len(set(...))` over a string field, not a plain `count`
  over a filter. Sub-shape D is the cleanest single-card slice
  if folded into its own phase, and it does NOT depend on the
  externals substrate Phase 2 lands.

The decision to ship B + C together is structurally identical to
why Phase 1 shipped Gigastorm + Lashwhip together — both Phase-2
cards exercise the SAME new substrate (the externals scan +
`ExternalCondition` enum), and the second card's
`PerControlled` variable-multiplier rider adds a second variant
on top of the substrate without re-architecting the scan loop.

### 1.4 Calibration against Phase 1

The Phase-1 closure ran 4 cycles across the C1 substrate / C2
FLIP / C3 + C4 per-card probe cadence. Phase 2 is **comparable in
scope, slightly smaller on substrate width but slightly larger
on per-card surface**:

- **Smaller:** Phase 2 does NOT add a new per-player state field
  (`Player.spells_cast_this_turn` is already shipped — verified
  live `rust/src/state.rs:1017`). Phase 1's largest single risk
  was threading a new state field through fingerprint / clone /
  CoW; Phase 2 has zero of that risk.
- **Same:** Phase 2 adds 1 new Rust struct (`ExternalCostReduction`),
  1 new Rust enum (`ExternalCondition`), and 2 new variants
  (`NthSpellThisTurn`, `PerControlled`). The shape mirrors Phase 1's
  1-struct-1-enum-2-variant landing.
- **Larger:** Phase 2 adds a new evaluation **path** — the
  battlefield-scan of the caster's permanents for matching
  externals. The Phase 1 evaluator was spell-local; Phase 2's
  walks the controller's battlefield. The shape is identical to
  Python's `_apply_external_cost_reductions`
  (`actions.py:471-507`), which the Rust port mirrors.
- **Same:** the variable-multiplier path lands here (Sami's
  `PerControlled` `multiplier()` is a state-derived count). This
  is the FIRST `multiplier()` Rust evaluates non-trivially —
  Phase 1's two conditions both had implicit `multiplier()==1`.
  Phase 3 will reuse the variable-multiplier wiring for Fungal's
  `PerDifferentlyNamedLand`.

**The campaign-total estimate is unchanged from the Phase-1 doc's
§8** (~10 cycles across Phase 1 / 2 / 3): Phase 1 closed at 4
cycles (slightly under the ~5 estimate); Phase 2 is ~4 cycles
(per this doc); Phase 3 is ~2 cycles (Fungal alone, narrower
than Phase 2).

## 2. Sub-shapes B + C scope — exactly 2 cards, the externals-bearing subset

Verified live against `OracleParserCardSource` at main `6c4ee310`:

### 2.1 Sub-shape B — `NthSpellThisTurn` (Uthros Psionicist)

Live parsed shape:

```python
external_cost_reductions=(
    ExternalCostReduction(amount=2, condition=NthSpellThisTurn(n=2)),
)
```

Oracle line that gates the parser claim (per `cards/parser/cost_
reduction.py:174-176`):

```
The second spell you cast each turn costs {N} less to cast.
```

The `_EXTERNAL_COST_REDUCTION_LINES` parser table maps the
`{N}`-templated line to `NthSpellThisTurn(2)`. The amount `N`
is captured by the regex (Uthros: `N=2`).

`NthSpellThisTurn(n).matches(state, viewer_id)` (verified at
`effects/conditions.py:259-262`):

```python
return state.player_by_id(viewer_id).spells_cast_this_turn == (
    self.n - 1
)
```

That is, the condition fires when the caster is about to cast
their `n`-th spell of the turn — `spells_cast_this_turn` is
incremented AFTER pay (the same SoT ordering Phase 1's
`AnotherSpellCastThisTurn` reads). For Uthros with `n=2`,
the condition fires iff the caster has already cast exactly 1
spell this turn.

### 2.2 Sub-shape C — `PerControlled(IsArtifact())` (Sami, Wildcat Captain)

Live parsed shape:

```python
external_cost_reductions=(
    ExternalCostReduction(
        amount=1, condition=PerControlled(filter=IsArtifact()),
    ),
)
```

Oracle line that gates the parser claim (per `cards/parser/cost_
reduction.py:194-197`):

```
Spells you cast have affinity for artifacts.
```

The `_EXTERNAL_COST_REDUCTION_KEYWORD_LINES` parser table maps
the literal keyword-style line to `(amount=1, condition=
PerControlled(IsArtifact()))`. The implicit `{1}` per artifact
is folded into `amount=1`; the per-artifact scaling comes from
`PerControlled.multiplier`.

`PerControlled(filter).matches(state, viewer_id)` and
`PerControlled(filter).multiplier(state, viewer_id)` (verified
at `effects/conditions.py:418-434`):

- `matches` returns True iff the count is ≥ 1.
- `multiplier` returns the actual count of the viewer's
  permanents matching `filter`.

For Sami: `filter == IsArtifact()`. `IsArtifact.test(obj, state)`
(`object_predicates.py:131-138`) returns `"Artifact" in
obj.printing.card_types`. So the reduction is exactly
`amount * count_of_caster_artifacts` generic mana.

`apply_external_cost_reductions` invokes `multiplier(state,
caster_id)` whenever `matches` is true (`actions.py:497-499`) —
the unit `amount` is multiplied by the dynamic count at cast
time.

### 2.3 Combined scope

| Card | `external_cost_reductions` shape | mana_cost | 17lands decks |
|---|---|---|---:|
| Uthros Psionicist | `(ExternalCostReduction(amount=2, NthSpellThisTurn(2)),)` | (verify at C2) | ~14,767 |
| Sami, Wildcat Captain | `(ExternalCostReduction(amount=1, PerControlled(IsArtifact())),)` | (verify at C2) | ~808 |

**Phase-2 deck total: 15,575 17lands decks**.

Both cards' externals satisfy the minimal-scope criteria:

- The rider is on `printing.external_cost_reductions` (verified:
  `cards/base.py:771` for the printing field; the dataclass at
  `:325-345`).
- The condition is one of EXACTLY TWO new structural variants
  (the `NthSpellThisTurn(n)` boolean-with-int-arg variant
  Phase 1 deferred + the `PerControlled(filter)` variable-
  multiplier variant Phase 1 deferred).
- `cost_reductions == ()` on both (the rider is the external
  one; the host card carries no spell-local self-reduction).
- No other blocking feature on either card (verify at C2 the
  same way Phase 1 verified its pair — `keywords ⊆ _SAFE_KEYWORDS`,
  no triggered/activated/static abilities, no `spell_effect`,
  no `kicker_cost` / `impending_cost` / `warp_cost`, no
  `room_halves`, no loyalty, no `station_threshold`, no
  `dynamic_pt_formula`, no `ward_cost`).

The ONLY blocking feature on both Phase-2 cards is the
`external_cost_reductions` tuple. Strip it and each card is a
pure bridge-simple creature.

## 3. Out-of-scope (deferred to Phase 3+)

The following are explicitly **NOT** in Phase 2's scope. The
Phase-2 filter guardrail (§6) positively rejects each so they
cannot reach the Phase-2 reduced-cost path:

### 3.1 Sub-shape D — variable-X multiplier on spell-local (Phase 3, Fungal Colossus)

Live parsed shape: `cost_reductions=(CostReduction(amount=1,
condition=PerDifferentlyNamedLand()),)`. Two structural
differences from Phase 2:

- **Spell-local, not external.** Fungal's rider lives on the
  spell's own `cost_reductions` (the spell-local list Phase 1
  already partially supports). Phase 1 admitted only boolean-
  condition variants; Phase 3 must add a new `Condition` variant
  `Condition::PerDifferentlyNamedLand` to the Phase-1
  spell-local enum (NOT the Phase-2 `ExternalCondition` enum
  this doc adds).
- **Distinct-name multiplier.** `PerDifferentlyNamedLand.
  multiplier(state, viewer_id)` returns `len({name : name ∈
  battlefield ∩ lands controlled by viewer})` — a `len(set)`
  over a string field on the printing, not a count over a type
  filter. This is structurally different from `PerControlled`'s
  count: it requires de-duplicating by `printing.name`.

These are independent enough that Phase 3 ships them as its own
substrate (a third sub-shape's worth of substrate width), with
a dedicated probe. Estimated **~2 cycles for Phase 3** (1
substrate + admit-widen + 1 probe; Fungal is the only carrier).

### 3.2 Planeswalker-loyalty-cost reductions (Phase 4 — out of substrate)

Planeswalker activated abilities can carry their own cost-reduction
riders via `ActivatedAbility.cost_reductions` (referenced at
`rust/src/cards.rs:9672`'s ActivatedAbility deferral comment).
**Out of substrate** by the same reasoning the Phase-1 doc
§3.4 stated: loyalty-cost reductions are a parallel rider on a
different cost-paying primitive (ability activation, not spell
cast), composing orthogonally with the spell-cast cost-reduction
substrate this campaign is closing. No live cost-reduction-gated
planeswalker is in the post-Phase-1 single-gated declined set
(the 3 cards are all creatures or creatures-with-externals).
Phase 4 (if scoped at all) is a separate substrate slice.

### 3.3 Generic `ExternalCondition::*` algebra (Phase 3+)

Like Phase 1's narrow port of `Condition`, Phase 2 ports EXACTLY
the two `ExternalCondition` variants Uthros + Sami need
(`NthSpellThisTurn{n}`, `PerControlled{type_filter}`). The full
`Condition`-grammar surface (And/Or/Not combinators,
`ObjectPredicate` filter algebra beyond the new
`TypeFilter::Artifact`, target-dependent variants like
`TargetMatches`, the `DuringYourTurn` / `VoidActiveCondition` /
`AttackedWithThisTurn` family) is **not in scope**. Sub-shape D
(Phase 3) adds `Condition::PerDifferentlyNamedLand`; later
phases extend as needed.

### 3.4 Combining `CostReduction` + `ExternalCostReduction` into one struct

**Rejected** (see §10.3). Python treats them as semantically
distinct dataclasses (`cards/base.py:308` vs `:326`) with
distinct evaluation rules (spell-local list traversed once
during cast vs. battlefield scan over controller's permanents
each cast). Phase 2 mirrors the Python distinction; both Rust
structs are minimal and identical-shaped (`amount: i32`,
`condition: ...`), so the cost of having two structs is one
declaration's worth of code.

## 4. Rust-side spec — the new struct, enum, field, and hook extension

### 4.1 New `CardPrinting.external_cost_reductions: Vec<ExternalCostReduction>` field

**File:** `rust/src/cards.rs`. Append after the existing
`cost_reductions: Vec<CostReduction>` field (which lives at
`cards.rs:10538` per the Phase-1 substrate landing). Code
excerpt:

```rust
    /// **cost-reduction substrate Phase 2.** Static cost-reduction
    /// effects this permanent grants to OTHER spells the controller
    /// casts while this permanent is on the battlefield (Uthros
    /// Psionicist's "second spell" rider, Sami Wildcat Captain's
    /// "affinity for artifacts" rider). Empty Vec = no externals
    /// (back-compat default — every pre-Phase-2 registry dict
    /// omits the `external_cost_reductions` key, which the parser
    /// maps to `Vec::new()`, identical to the
    /// `cost_reductions` / `triggered_abilities` Option-parse
    /// shape). The cast pipeline's
    /// `apply_cost_reductions_rust` helper (extended in §4.3,
    /// `state_ops_legal.rs:764`) walks every permanent the caster
    /// controls and applies any matching externals on top of the
    /// spell's own spell-local `cost_reductions`. Mirrors Python's
    /// `CardPrinting.external_cost_reductions: tuple[External
    /// CostReduction, ...]` at `src/mtg_bot/cards/base.py:771`.
    pub external_cost_reductions: Vec<ExternalCostReduction>,
```

### 4.2 New `ExternalCostReduction` Rust struct + `ExternalCondition` enum

**File:** `rust/src/cards.rs`. Append near the Phase-1
`CostReduction` (`cards.rs:9800`) — the two structs are siblings
with identical layouts:

```rust
/// A static cost-reduction rule granted by a permanent on the
/// battlefield to OTHER spells the controller casts. Mirrors
/// Python's `ExternalCostReduction` dataclass at
/// `src/mtg_bot/cards/base.py:326` (`amount: int`,
/// `condition: Condition`). **cost-reduction substrate Phase 2.**
/// `amount` is the unit generic reduction; the externals
/// scan multiplies `amount` by the condition's `multiplier()`
/// (Phase 2: `PerControlled.multiplier` is the count of the
/// caster's matching permanents). Distinct from the spell-local
/// `CostReduction` (Phase 1) — externals fire whenever the
/// CONTROLLER casts ANY spell, not just the host card's own
/// cast. Phase 3 will add `Condition::PerDifferentlyNamedLand`
/// on the spell-local side; Phase 4 (if scoped) is loyalty-
/// cost reductions on `ActivatedAbility`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExternalCostReduction {
    pub amount: i32,
    pub condition: ExternalCondition,
}

/// The Phase-2 condition subset for externals. Ports EXACTLY two
/// variants — the only two sub-shape B/C uses. Phase 3 may extend
/// (or alternatively narrow further by routing variable-X over
/// the spell-local `Condition` enum instead).
///
/// **Why a separate enum from spell-local `Condition`?** Python
/// expresses both with the SAME `Condition` grammar (Uthros's
/// `NthSpellThisTurn` is a structural `Condition`; Sami's
/// `PerControlled` is a structural `Condition`). The Rust side
/// keeps them separate because: (a) Phase-1 `Condition` has
/// hard-coded `TypeFilter::Creature` and admits ONLY boolean
/// conditions — extending it in-place would require widening
/// `TypeFilter` and adding the variable-multiplier path,
/// changes that should be staged with their consumers; (b) the
/// externals scan reads `multiplier` non-trivially in Phase 2
/// (Sami), while the spell-local Phase-1 helper does not (the
/// Phase-1 default is `multiplier()==1`). Phase 3 may UNIFY the
/// enums when sub-shape D adds variable-X on the spell-local
/// side — at that point both sides will have a multiplier
/// path, and the two enums can collapse into one.
///
/// **Naming convention:** mirrors Python's class names ONE-TO-ONE
/// for cross-engine bridge wire tokens (`condition_kind` strings,
/// §5.2).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ExternalCondition {
    /// Python `NthSpellThisTurn(n)`
    /// (`effects/conditions.py:248-262`): the caster is about to
    /// cast their `n`-th spell of the turn — i.e.
    /// `Player.spells_cast_this_turn == n - 1` (the cast pipeline
    /// increments AFTER cost is paid, mirroring Python's
    /// pre-increment semantics). For Uthros Psionicist:
    /// `NthSpellThisTurn { n: 2 }`.
    NthSpellThisTurn { n: i32 },
    /// Python `PerControlled(filter)`
    /// (`effects/conditions.py:405-434`): count permanents the
    /// caster controls matching `filter`. `matches()` is True
    /// iff count ≥ 1; the externals scan multiplies `amount` by
    /// the count. Phase 2 hard-codes `TypeFilter::Artifact` (the
    /// only predicate sub-shape C uses); Phase 3+ extends.
    PerControlled { type_filter: TypeFilter },
}
```

### 4.3 Extend `TypeFilter` enum with the `Artifact` variant

**File:** `rust/src/cards.rs`. The Phase-1 `TypeFilter` enum at
`cards.rs:9815` currently has exactly one variant (`Creature`).
Phase 2 adds:

```rust
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TypeFilter {
    /// Python `IsCreature`: `obj.card_types.contains("Creature")`.
    Creature,
    /// **Phase 2.** Python `IsArtifact`
    /// (`object_predicates.py:131-138`):
    /// `obj.card_types.contains("Artifact")`. Used by Sami,
    /// Wildcat Captain's `PerControlled(IsArtifact())` external.
    Artifact,
}
```

The `TypeFilter` enum is intentionally NOT bifurcated by
spell-local vs external — both Phase-1's `OpponentsControlAtLeast`
and Phase-2's `PerControlled` consume the same enum. This is the
narrow grammar-sharing decision; the broader question of whether
`Condition` and `ExternalCondition` should unify is deferred to
Phase 3 (see §4.2 docstring).

### 4.4 Extend `apply_cost_reductions_rust` with the externals scan

The Phase-1 helper at `rust/src/state_ops_legal.rs:764` currently
walks `printing.cost_reductions` only. Phase 2 extends it with
the externals scan (mirroring Python's `apply_cost_reductions`
ordering at `actions.py:428-438`: externals BEFORE spell-local —
note Python applies externals first, then spell-local reductions
stack on top via successive `cost.reduced(...)` calls).

**Helper extension (the consolidated cost-reduction evaluator):**

```rust
#[inline]
pub(crate) fn apply_cost_reductions_rust(
    state: &crate::state::GameState,
    caster_idx: usize,
    printing: &crate::cards::CardPrinting,
    base: crate::cards::ManaCost,
) -> crate::cards::ManaCost {
    let mut cost = base;
    // **Phase 2.** Externals scan FIRST (mirror Python
    // `actions.apply_cost_reductions` ordering: external scan
    // applied before the spell's own `cost_reductions`).
    cost = apply_external_cost_reductions_rust(state, caster_idx, cost);
    // **Phase 1 (unchanged).** Spell-local boolean-condition
    // CostReduction evaluation — Empty-Vec short-circuits.
    if printing.cost_reductions.is_empty() {
        return cost;
    }
    for rule in printing.cost_reductions.iter() {
        let holds = match &rule.condition {
            crate::cards::Condition::AnotherSpellCastThisTurn => {
                state.players[caster_idx].spells_cast_this_turn >= 1
            }
            crate::cards::Condition::OpponentsControlAtLeast {
                type_filter, count,
            } => {
                // Phase-1 body, unchanged. See state_ops_legal.rs:788-825.
                /* ... */
                # 0 != 0 /* placeholder for excerpt */
            }
        };
        if holds && rule.amount > 0 {
            cost.generic = cost.generic.saturating_sub(rule.amount as u8);
        }
    }
    cost
}

/// **Phase 2.** Rust analogue of Python's
/// `_apply_external_cost_reductions` (`actions.py:471-507`).
/// Walks the caster's battlefield for permanents granting
/// external cost reductions and applies any whose
/// `ExternalCondition` matches. The reduction stacks (multiple
/// permanents with the same external sum together via successive
/// `cost.reduced(...)` calls — mirror of the Python loop).
///
/// **Variable-multiplier path.** Sami's `PerControlled` is the
/// first multiplier this engine evaluates non-trivially: the
/// returned amount is `external.amount *
/// count_of_caster_permanents_matching(type_filter)`. For
/// boolean Phase-2 variants (`NthSpellThisTurn`) the multiplier
/// is implicit `1`. Both paths compose through the same
/// `cost.generic = cost.generic.saturating_sub(amt)` reduction
/// (Python: `ManaCost.reduced`, `cards/base.py:298-305`).
fn apply_external_cost_reductions_rust(
    state: &crate::state::GameState,
    caster_idx: usize,
    mut cost: crate::cards::ManaCost,
) -> crate::cards::ManaCost {
    // Phased-out permanents do not grant externals (Python:
    // `actions.py:489-490`). Phased-out battlefield iteration
    // uses the same check the existing combat scan uses.
    for permanent in state.players[caster_idx].battlefield.iter() {
        if permanent.phased_out { continue; }
        let Some(pr) = state.registry.lookup(permanent.printing_id) else {
            continue;
        };
        for ext in pr.external_cost_reductions.iter() {
            let (holds, multiplier) = match &ext.condition {
                crate::cards::ExternalCondition::NthSpellThisTurn { n } => {
                    // Mirrors Python `NthSpellThisTurn.matches`
                    // (`effects/conditions.py:259-262`): True iff
                    // the caster is about to cast their n-th spell
                    // (post-increment ordering: spells_cast_this_turn
                    // == n-1). Multiplier is implicit 1.
                    let holds =
                        state.players[caster_idx].spells_cast_this_turn
                        == (n - 1);
                    (holds, 1i32)
                }
                crate::cards::ExternalCondition::PerControlled {
                    type_filter,
                } => {
                    // Mirrors Python `PerControlled.matches`
                    // (`effects/conditions.py:418-434`): count
                    // caster's permanents matching the filter;
                    // matches iff count >= 1; multiplier IS the
                    // count. The Phase-2 affinity path.
                    let mut count = 0i32;
                    for obj in state.players[caster_idx].battlefield.iter() {
                        let Some(opr) = state.registry.lookup(obj.printing_id)
                        else { continue; };
                        let matches = match type_filter {
                            crate::cards::TypeFilter::Creature => {
                                opr.card_types.iter().any(|t| t == "Creature")
                            }
                            crate::cards::TypeFilter::Artifact => {
                                opr.card_types.iter().any(|t| t == "Artifact")
                            }
                        };
                        if matches { count += 1; }
                    }
                    (count >= 1, count)
                }
            };
            if holds && ext.amount > 0 && multiplier > 0 {
                let amt = (ext.amount as i64) * (multiplier as i64);
                let amt_clamped = amt.min(u8::MAX as i64) as u8;
                cost.generic = cost.generic.saturating_sub(amt_clamped);
            }
        }
    }
    cost
}
```

The 7 existing call sites of `apply_cost_reductions_rust`
(verified via grep at `state_ops_cast.rs:1167` and
`state_ops_legal.rs:2414 / :2444 / :2633 / :2645 / :2733 /
:2797 / :2917`) keep their existing signatures — Phase 2
changes only the helper's body, not its surface.

### 4.5 `Player.spells_cast_this_turn` is already sufficient — no new state field

Verified live: `Player.spells_cast_this_turn: i32` exists at
`rust/src/state.rs:1017` (landed via MMM Pin 1 pre-Phase-1),
fingerprint-threaded (per its docstring at `:995-:1015`),
incremented at every Rust cast primitive
(`state_ops_cast.rs:1257`, `:1537`, `:1828`, `:3253` — all 4
sites already in production from the MMM landing) AFTER pay,
and reset at the cleanup step (per its docstring referencing
`turn.py:1105`'s Python-side reset).

Uthros's `NthSpellThisTurn(2)` reads `spells_cast_this_turn == 1`
(the post-increment SoT — see the `matches()` docstring at
`effects/conditions.py:259-262`). This is bit-for-bit the same
state field Phase 1's `AnotherSpellCastThisTurn` reads
(`>= 1`). **No new state field is required for Phase 2.**

### 4.6 No new artifact-count accessor needed

Verified: there is no existing `Player.artifacts_controlled_count`
accessor in Rust (a grep for `artifacts_controlled` /
`controlled_artifact_count` returns zero hits beyond the
`controlled_artifact_entered_this_turn` state-predicate from a
different landing). Phase 2 computes the count **dynamically
per-cast** by iterating
`state.players[caster_idx].battlefield` and counting matches
(§4.4 body) — the same shape Python's `PerControlled.multiplier`
uses (`effects/conditions.py:418-434`).

Adding a cached `Player.artifacts_controlled_count` accessor is
**rejected** for Phase 2 (see §10.4): the cache adds invalidation
surface (every artifact ETB / death / phasing / type-loss /
control-change would have to update it) and the dynamic scan is
O(battlefield-size) which is bounded by the same small-N the
Phase-1 `OpponentsControlAtLeast` scan iterates. The same
"start narrow" discipline Phase 1 used applies.

### 4.7 Parse + to_pydict round-trip

**Parse** in `cards.rs::parse_printing`: add an
`external_cost_reductions` arm parallel to the Phase-1
`cost_reductions` arm (`cards.rs:15226`). The condition arm
dispatches on `condition_kind` string with a hard-error on
unknown tokens (mirror of Phase 1's §2 Rust-side teeth):

```rust
let external_cost_reductions: Vec<ExternalCostReduction> =
    match dict.get_item("external_cost_reductions")? {
        Some(ecr_any) => {
            let lst = ecr_any.downcast::<PyList>().map_err(|_| {
                PyValueError::new_err(
                    "external_cost_reductions must be a list of dicts",
                )
            })?;
            let mut out = Vec::with_capacity(lst.len());
            for item in lst.iter() {
                let d = item.downcast::<PyDict>()?;
                let amount: i32 =
                    d.get_item("amount")?.unwrap().extract()?;
                let kind: String =
                    d.get_item("condition_kind")?.unwrap().extract()?;
                let condition = match kind.as_str() {
                    "nth_spell_this_turn" => {
                        let args = d.get_item("condition_args")?.unwrap();
                        let tup = args.downcast::<PyTuple>()?;
                        let n: i32 = tup.get_item(0)?.extract()?;
                        ExternalCondition::NthSpellThisTurn { n }
                    }
                    "per_controlled" => {
                        let args = d.get_item("condition_args")?.unwrap();
                        let tup = args.downcast::<PyTuple>()?;
                        let pred: String = tup.get_item(0)?.extract()?;
                        let type_filter = match pred.as_str() {
                            "artifact" => TypeFilter::Artifact,
                            "creature" => TypeFilter::Creature,
                            other => return Err(PyValueError::new_err(
                                format!(
                                    "Phase-2 external cost-reduction does \
                                     not support 'per_controlled' filter \
                                     {other:?} (Phase 3+)"
                                ),
                            )),
                        };
                        ExternalCondition::PerControlled { type_filter }
                    }
                    other => return Err(PyValueError::new_err(format!(
                        "Phase-2 external cost-reduction does not support \
                         condition_kind {other:?} (Phase 3+)"))),
                };
                out.push(ExternalCostReduction { amount, condition });
            }
            out
        }
        None => Vec::new(),
    };
```

**to_pydict** (the inverse): the existing
`printing_to_pydict`-style serializer (the
`cost_reductions`-shaped output Phase 1 added) emits a
sibling `external_cost_reductions` list-of-dicts for the bridge
round-trip.

## 5. Python bridge spec — round-trip the new field byte-equal

### 5.1 CardDef field

**File:** `src/mtg_bot/parity/cross_engine.py`, the `CardDef`
dataclass. Append after the Phase-1 `cost_reductions` field
(`cross_engine.py:597`):

```python
    # cost-reduction substrate (Phase 2). External cost reductions
    # granted by a permanent on the battlefield to OTHER spells the
    # controller casts (EoE — Uthros Psionicist's "second spell"
    # rider, Sami Wildcat Captain's "affinity for artifacts" rider).
    # Each entry is a frozen (amount: int, condition_kind: str,
    # condition_args: tuple) triple. Phase 2 supports EXACTLY two
    # condition_kinds:
    #   * "nth_spell_this_turn" — args = (n,)
    #   * "per_controlled"      — args = ("artifact",)   # Phase 2
    #                          OR args = ("creature",)   # already-
    #                          shipped TypeFilter::Creature; useful for
    #                          synthetic tests, no live carrier today
    # The filter guardrail (§6) positively rejects every other
    # condition kind, every variable-multiplier condition
    # (Phase 3: PerDifferentlyNamedLand), and any non-empty
    # cost_reductions whose condition isn't Phase-1-supported.
    # Empty tuple = no externals (back-compat default; every
    # pre-Phase-2 CardDef omits this).
    external_cost_reductions: tuple[tuple[int, str, tuple], ...] = ()
```

### 5.2 `_spec_card_to_printing_dict` registry-dict emit

**File:** `src/mtg_bot/parity/cross_engine.py`. After the
existing `if card.cost_reductions:` block (`cross_engine.py:
13598-13605`):

```python
if card.external_cost_reductions:
    printing_dict["external_cost_reductions"] = [
        {
            "amount": amount,
            "condition_kind": cond_kind,
            "condition_args": cond_args,
        }
        for (amount, cond_kind, cond_args) in (
            card.external_cost_reductions
        )
    ]
```

The wire tokens are stable bridge-side strings:
`"nth_spell_this_turn"` and `"per_controlled"`, mirroring
Phase 1's `"another_spell_cast_this_turn"` and
`"opponents_control_at_least"` convention. The
`condition_args` tuple uses lower-case `"artifact"` /
`"creature"` predicate tokens (matching the Phase-1 convention
for `"creature"`).

### 5.3 `_card_def_to_python_printing` reverse arm

Reconstructs the structural `ExternalCostReduction` from the
wire tokens. Append after the existing `cost_reductions =
()` arm (`cross_engine.py:14354-14384`):

```python
from mtg_bot.cards.base import ExternalCostReduction
from mtg_bot.effects.conditions import (
    NthSpellThisTurn, PerControlled,
)
from mtg_bot.effects.object_predicates import IsArtifact, IsCreature

external_cost_reductions: tuple[ExternalCostReduction, ...] = ()
if card.external_cost_reductions:
    rules = []
    for (amount, cond_kind, cond_args) in card.external_cost_reductions:
        if cond_kind == "nth_spell_this_turn":
            (n,) = cond_args
            cond = NthSpellThisTurn(n=int(n))
        elif cond_kind == "per_controlled":
            (pred_token,) = cond_args
            if pred_token == "artifact":
                cond = PerControlled(filter=IsArtifact())
            elif pred_token == "creature":
                cond = PerControlled(filter=IsCreature())
            else:
                raise ValueError(
                    f"Phase-2 external cost-reduction bridge: only "
                    f"'artifact'/'creature' predicate tokens are "
                    f"supported on per_controlled; got {pred_token!r}"
                )
        else:
            raise ValueError(
                f"Phase-2 external cost-reduction bridge: unsupported "
                f"condition_kind {cond_kind!r} (Phase 3+ adds "
                f"per_differently_named_land)"
            )
        rules.append(ExternalCostReduction(
            amount=int(amount), condition=cond,
        ))
    external_cost_reductions = tuple(rules)
```

and pass `external_cost_reductions=external_cost_reductions`
into the `CardPrinting(...)` call (sibling kwarg next to the
existing `cost_reductions=cost_reductions` at
`cross_engine.py:14519`). The `raise` on an unknown kind is the
bridge-side §2 teeth — matches the Rust hard-error in §4.7; both
sides fail loudly rather than silently dropping a Phase-3 rider.

### 5.4 Cross-engine bridge admit predicate

**File:** `src/mtg_bot/parity/trajectory.py`. The Phase-1 admit
predicate `_printing_is_bridge_pure_cost_reduction_creature`
(`trajectory.py:4940-5024`) currently REJECTS any printing with
`external_cost_reductions` non-empty (the §2 teeth at `:4986`).
Phase 2 has two options:

**Option A (widen the existing predicate):** drop the
`external_cost_reductions` reject and add a `for ext in
printing.external_cost_reductions: assert
_external_rule_is_phase2(ext)` admit-loop alongside the existing
`cost_reductions` admit-loop. The same predicate then admits
both Phase-1 and Phase-2 cards.

**Option B (new sibling predicate):** add a new disjunct
`_printing_is_bridge_pure_external_cost_reduction_creature` that
mirrors the Phase-1 predicate's structure but admits externals
+ requires `cost_reductions == ()`. Wire it into
`_filter_deck_to_bridge_supported` (`trajectory.py:11074`) as
an additional OR-clause.

**Recommendation: Option A.** Both Phase-2 cards have
`cost_reductions == ()` (verified live — the externals rider
lives ONLY on the granting permanent), so the widened predicate
admits the 2 Phase-2 cards AND the 2 Phase-1 cards through the
SAME named site. The Phase-1 carriers are unaffected — their
`external_cost_reductions == ()` makes the new admit-loop
vacuous, identical to current behavior. Phase 3 / Phase 4 may
fold in additional grammar via the same pattern. The single-
predicate path also has the simpler decline-set bench check
(one predicate, one assertion).

If Option A surfaces a concrete review concern at C2 (e.g. the
admit predicate becomes too long to reason about, or a
Phase-2 rider unexpectedly co-occurs with a Phase-1 rider on
some single card), C2 may fall back to Option B without
changing this doc's substrate / scan body specs.

**The widened predicate (Option A):**

```python
def _external_cost_reduction_rule_is_phase2(rule) -> bool:
    """True iff `rule` is one of the two `ExternalCondition`s
    Phase 2 ports. Any variable-multiplier on the spell-local
    side (Phase 3 sub-shape D) or unrecognized condition — False."""
    from mtg_bot.effects.conditions import (
        NthSpellThisTurn, PerControlled,
    )
    from mtg_bot.effects.object_predicates import IsArtifact, IsCreature
    c = rule.condition
    if isinstance(c, NthSpellThisTurn):
        return isinstance(c.n, int)
    if isinstance(c, PerControlled):
        return isinstance(c.filter, (IsArtifact, IsCreature))
    return False


def _printing_is_bridge_pure_cost_reduction_creature(printing) -> bool:
    """[Phase 1 + Phase 2 combined] ...
    See Phase 1 docstring for the §2 teeth and decline-set
    coverage. Phase 2 ADDS admit-coverage for
    external_cost_reductions matching
    _external_cost_reduction_rule_is_phase2; Fungal Colossus
    (PerDifferentlyNamedLand — Phase 3) is still rejected by
    _cost_reduction_rule_is_phase1.
    """
    if "Creature" not in printing.card_types:
        return False
    if printing.power is None or printing.toughness is None:
        return False
    # **Phase 1 spell-local admit (unchanged).**
    if printing.cost_reductions:
        for rule in printing.cost_reductions:
            if not _cost_reduction_rule_is_phase1(rule):
                return False
    # **Phase 2 externals admit (NEW).** Replaces the old
    # `if printing.external_cost_reductions: return False` guard.
    if printing.external_cost_reductions:
        for ext in printing.external_cost_reductions:
            if not _external_cost_reduction_rule_is_phase2(ext):
                return False
    # At least ONE rider must be present (otherwise the
    # bridge_simple_creature predicate handles it).
    if not printing.cost_reductions and not (
        printing.external_cost_reductions
    ):
        return False
    # **§2 exclusion set — unchanged from Phase 1.**
    # (keywords, triggered/activated/static, spell_effect,
    # warp/kicker/impending, room_halves, loyalty, station_
    # threshold, dynamic_pt_formula, ward — all rejected.)
    # [Phase-1 body preserved verbatim — see trajectory.py:4992-5023.]
    return True
```

### 5.5 The 8 sibling guards stay rejecting (Phase-3-onwards)

The 8 other admit predicates in `trajectory.py` that carry the
explicit guard `if printing.cost_reductions or
printing.external_cost_reductions: return False` (verified at
`:4696`, `:4876`, `:7696`, `:8487`, `:8650`, `:8760`, `:8954`,
`:9207`, `:9437` — note: 9 sites, the Phase-1 doc undercounted by
one) STAY in place. The widened
`_printing_is_bridge_pure_cost_reduction_creature` is the
SINGLE positive-allowlist gate; the negative guards on every
other predicate keep the bridge from admitting a cost-reduction-
gated card through some other code path.

## 6. Filter guardrail — admit only the Phase-2 externals shapes (Option A)

Reuse the Phase-1 predicate widened per §5.4 above. The §2
positive-allowlist guardrails:

- Admits `(IsCreature, External(NthSpellThisTurn(int))) ∪
  (IsCreature, External(PerControlled(IsArtifact ∪
  IsCreature)))` on top of the Phase-1
  `(IsCreature, Spell-local(AnotherSpellCastThisTurn ∪
  OpponentsControlAtLeast(Creature, int)))`.
- Rejects Fungal Colossus (`Spell-local(PerDifferently
  NamedLand)` — Phase 3): the existing
  `_cost_reduction_rule_is_phase1` returns False on the
  variable-X condition.
- Rejects any Phase-4 planeswalker (`loyalty != None` check).
- Rejects any future co-gated card via the
  `_printing_is_bridge_simple_creature` exclusion set.

**Decline-set carriers post-Phase-2:**
Fungal Colossus is the SOLE remaining declined cost-reduction
card. Phase 3 closes it.

## 7. Test plan

### 7.1 Substrate unit pins (Rust `#[test]` module)

1. `parse_printing` with `external_cost_reductions=[{"amount":2,
   "condition_kind":"nth_spell_this_turn", "condition_args":(2,)}]`
   → `printing.external_cost_reductions == [ExternalCostReduction{
   amount: 2, condition: NthSpellThisTurn{n:2}}]`. Absent key →
   empty Vec. Unknown `condition_kind` → `Err` (§2 teeth).
   Unknown `per_controlled` filter token → `Err`.
2. `apply_external_cost_reductions_rust` with
   `NthSpellThisTurn{n:2}`-bearing permanent owned by p0:
   `p0.spells_cast_this_turn == 0` → cost unchanged (off by one);
   `== 1` → reduction fires (`amount=2` generic); `== 2` → off
   again (post-increment for the 3rd spell). Ordering pin.
3. `apply_external_cost_reductions_rust` with
   `PerControlled{type_filter:Artifact}`-bearing permanent: 0
   artifacts → unchanged; 1 artifact → reduced by `amount`; 3
   artifacts → reduced by `amount * 3`. Mirror the dynamic-
   multiplier path.
4. `apply_external_cost_reductions_rust` phased-out skip:
   permanent with the rider phased out → no reduction.
5. `apply_external_cost_reductions_rust` controller scope: an
   opponent's permanent with the rider → ignored (the scan
   walks ONLY the caster's battlefield, not opponents'). Pin
   the per-controller scope explicitly — Phase-2's bug surface
   is the controller-mismatch case.
6. **Stacking pin:** a spell with BOTH a spell-local Phase-1
   `CostReduction(amount=3, AnotherSpellCastThisTurn)` AND a
   battlefield with Sami granting `PerControlled(Artifact)`
   while the caster controls 2 artifacts and has cast 1 prior
   spell → final cost = base - (3 spell-local) - (1*2 external)
   = base - 5 generic. Pin the multi-rule ordering (Python:
   externals first, then spell-local) matches.

### 7.2 Cross-engine bridge round-trip pins

7. A DeckSpec with a synthetic CardDef
   `external_cost_reductions=((2, "nth_spell_this_turn", (2,)),)`
   on a permanent that's already on p0's battlefield: cast a
   first spell on both engines → byte-equal full-cost state
   (`spells_cast_this_turn` was 0 pre-cast); cast a second
   spell → byte-equal reduced-cost state (`spells_cast_this_turn`
   was 1 pre-cast, reduction fires). Mana pool / zones /
   `spells_cast_this_turn` fingerprint byte-equal.
8. A synthetic CardDef
   `external_cost_reductions=((1, "per_controlled", ("artifact",)),)`
   on a permanent on p0's battlefield + 3 artifacts on p0:
   cast any spell via `step_both` → byte-equal reduced-cost
   state (reduction = 1 * 3 = 3 generic). With 0 artifacts:
   byte-equal full-cost state (multiplier 0 → no reduction
   because `count >= 1` gate fails — verify with Python's
   `PerControlled.matches` semantics).
9. Action-set invariance pin: both engines' `legal_actions`
   emit the SAME set (and positional order) of `CastSpell`
   dicts for a spell cast under externals as for an otherwise-
   identical vanilla spell — externals add NO action, same as
   Phase 1 (the key structural diff from warp).

### 7.3 Real-EoE per-card probes

A `tests/test_probe_uthros_psionicist_real_eoe_cost_reduction.py`
+ a sibling `tests/test_probe_sami_wildcat_captain_real_eoe_
cost_reduction.py` (modeled exactly on the Phase 1 probes
`test_probe_gigastorm_titan_real_eoe_cost_reduction.py` +
`test_probe_lashwhip_predator_real_eoe_cost_reduction.py` —
module-scope `_PRINTINGS` idiom, 6-pin shape), that drive the
**actual Uthros Psionicist / Sami, Wildcat Captain printing**
(resolved via the live `OracleParserCardSource`, NOT a synthetic
CardDef — the real-EoE-signal discipline) on **both** engines:

- **Uthros Psionicist probe:** assert byte-equal mirror through
  (a) Uthros in play, cast a first cheap spell on the caster's
  turn (full cost paid on both — `spells_cast_this_turn == 0`
  pre-cast), (b) cast a SECOND spell same turn (Uthros's {2}
  reduction applies on both — `spells_cast_this_turn == 1`
  pre-cast). The second path is the case that diverges
  pre-Phase-2.
- **Sami, Wildcat Captain probe:** assert byte-equal mirror
  through (a) Sami in play + 0 artifacts → full cost both, (b)
  Sami in play + 2 artifacts → reduced cost both (`{2}` less,
  multiplier 2). The artifact count is varied across two
  scripted-picker scenarios.

**Bench-strategy reduction-trigger coverage note:** as with
Phase 1's Gigastorm probe, the bench's `attack_all` strategy may
not naturally produce the "cast first spell then second"
sequence Uthros needs, nor the "play artifacts then cast spell"
sequence Sami needs. The probe MUST use a scripted picker (per
the Phase-1 precedent at the C3/C4 picker shim) that forces
each scenario so the *reduced-cost* path is actually exercised.
Both probes mirror the Phase-1 6-pin shape (parser SoT,
printing-surface attrs, admit classification, byte-equal both
seats reduced, byte-equal both seats full-cost, decline-set
negative pin).

### 7.4 Decline-set bench check (no-silent-auto-grow)

10. `_printing_is_bridge_pure_cost_reduction_creature(<live Fungal
    Colossus>)` is **`False`** under the Phase-2-widened rule
    (`PerDifferentlyNamedLand` is not Phase-2 — rejected by
    `_cost_reduction_rule_is_phase1`).
11. `(<live Uthros Psionicist>)` is **`True`** AND `(<live Sami,
    Wildcat Captain>)` is **`True`** (the C2 inversion of the
    Phase-1 decline pin — these were `False` post-Phase-1, now
    `True` post-Phase-2).
12. **Subsystem-attribution pin:** exactly 4 EoE printings pass
    `_printing_is_bridge_pure_cost_reduction_creature` post-
    Phase-2 (Gigastorm Titan + Lashwhip Predator from Phase 1
    + Uthros Psionicist + Sami, Wildcat Captain from Phase 2).
    The guardrail's positive set is exhaustive across both
    phases.
13. **Decline-set bench check** (the Archenemy's-Charm-style
    proxy): with the decline-set deck pool loaded, confirm the
    bench's loader-side filter EXCLUDES Fungal Colossus and
    ADMITS Uthros + Sami — Phase 2 admits +2 cards and 0
    additional decline-set spillover.
14. **No-silent-auto-grow pin** (the discipline behind
    "feedback_silent_noop_pipelines.md"): assert that an
    accidentally-Phase-3 rider on a synthetic CardDef (e.g.
    `external_cost_reductions=((1, "per_differently_named_land",
    ()),)`) raises `ValueError` from the Phase-2 reverse arm in
    `_card_def_to_python_printing` AND raises from the Rust
    `parse_printing`'s `external_cost_reductions` arm. Both
    sides fail loudly on a Phase-3 token — no silent drop.

## 8. Estimated cycle count

Per the Phase-1 closure precedent (1 substrate + 1 admit + 1
probe per card = ~4 cycles for 2 cards):

| Cycle | Owner | Deliverable |
|---:|---|---|
| 1 | Rust agent | Substrate landing: CardDef field + Rust struct/enum (`ExternalCostReduction`, `ExternalCondition`) + `TypeFilter::Artifact` variant + `parse_printing` arm + `apply_external_cost_reductions_rust` helper + `apply_cost_reductions_rust` extension (externals scan ordering). **Sole Rust slice this round** (`.pyd` race rule). Both Phase-2 carriers STAY DECLINED post-Cycle-1. |
| 2 | Python/bench agent | Bridge round-trip arms (`_spec_card_to_printing_dict` emit + `_card_def_to_python_printing` reverse arm) + widened `_printing_is_bridge_pure_cost_reduction_creature` admit predicate + the 9 unit + bridge pins (§7.1 + §7.2). **THE FLIP** — Uthros + Sami DECLINED → ADMITTED simultaneously. |
| 3 | Bench agent | Uthros Psionicist real-EoE probe (§7.3) + decline-set bench check on Fungal (§7.4 pins 10, 14). |
| 4 | Bench agent | Sami, Wildcat Captain real-EoE probe (§7.3) + 4-card subsystem-attribution pin (§7.4 pin 12) + decline-set positive pin (§7.4 pin 13). |

**Estimated total: ~4 cycles for Phase 2** — exactly the Phase-1
closure cadence. The substrate landing (cycle 1) has LOWER risk
than Phase 1's because no new state field is threaded through
fingerprint / clone / CoW (§4.5). The cast-side affordability-
probe wiring is also already in place — Phase 2 only extends
the helper's body, not its 7 call sites (§4.4).

**Subsequent phases (out of Phase 2 scope, scoped here for
campaign context):**

- **Phase 3 (Fungal Colossus, ~+13,165 decks):** ~2 cycles to
  add `Condition::PerDifferentlyNamedLand` variant +
  variable-multiplier evaluator path on the spell-local enum
  (the spell-local sibling of Phase-2's `PerControlled`) +
  probe. Phase 3 may also unify `Condition` and
  `ExternalCondition` (§4.2 docstring) — that decision is taken
  inside Phase 3, not here.
- **Phase 4 (planeswalker-loyalty-cost reductions, ~0 decks
  today):** out of substrate; only scoped if a future EoE card
  needs it.

**Campaign total: ~10 cycles across Phase 1 / 2 / 3** to close
all 5 cards / 53,648 decks — matching the Phase-1 doc's §8
estimate. Phase 1 came in at 4 cycles (vs ~5 estimate); Phase 2
projected at 4; Phase 3 projected at 2; total = 10.

## 9. SEARCH_LIMITATIONS.md entries (land WITH Phase 2 cycle 1)

Two entries (estimated; Phase 2 is structurally cleaner than
Phase 1 because it adds NO new state field):

1. **Cost-reduction Phase 2 supports only the two
   `ExternalCondition` variants; variable-X on spell-local +
   the full predicate algebra still deferred.** Location:
   `state_ops_legal.rs::apply_external_cost_reductions_rust` +
   `trajectory.py::_printing_is_bridge_pure_cost_reduction_
   creature`. Why OK: the filter guardrail positively rejects
   every non-Phase-2 shape on BOTH bridge sides; failure mode =
   a future probe admitting a Phase-3 card without the
   guardrail widening would see Python reduce and Rust hard-
   error at registry build (loud, not silent); fix-scope =
   Phase 3 + Phase 4; impact = +2 cards / +15,575 decks, 0
   strength cost.
2. **Rust `apply_external_cost_reductions_rust` recomputes the
   artifact count dynamically per-cast** (no cached
   `Player.artifacts_controlled_count` field). Location:
   `state_ops_legal.rs::apply_external_cost_reductions_rust`'s
   `PerControlled` arm. Shortcut: Rust iterates
   `state.players[caster_idx].battlefield` and counts matches
   each affordability probe + each cast, rather than caching
   the count. Why OK: battlefield sizes are bounded by the
   same small N the Phase-1 `OpponentsControlAtLeast` scan
   already iterates without issue; the cache adds invalidation
   surface across ETB / death / phasing / type-change / control-
   change. Failure mode: a future pathological battlefield with
   hundreds of artifacts would amortize the scan across every
   `CastSpell` affordability probe. Fix-scope: add a cached
   counter on `Player` IF observed perf shows it (precedent:
   `artifacts_entered_under_your_control_this_turn` at
   `state.rs:1077` is the cached counter shape if needed).
   Impact: 0 today (battlefield sizes ≤ 30 in observed games).

## 10. Rejected alternatives

### 10.1 Fold sub-shape D (Fungal's variable-X) into Phase 2

**Rejected.** Fungal's `PerDifferentlyNamedLand` is
structurally orthogonal to Phase 2 in TWO axes (§1.3): (a) it
lives on the spell-local `cost_reductions` (not the externals
list), so the substrate it needs is a NEW variant on the
Phase-1 `Condition` enum, not a new variant on Phase-2's
`ExternalCondition` enum; (b) its multiplier is a `len(set)`
over a string field, not a count over a type filter. Folding D
into Phase 2 would conflate two independent substrates and
violate the round-59 sub-shape-split discipline that drove
Phase 1's smallest-self-contained-slice cadence. Phase 3 ships
sub-shape D in 2 cycles cleanly.

### 10.2 Generic `ExternalCondition::*` algebra in Phase 2

**Rejected.** Mirroring Phase 1's discipline (§10.1 of the
Phase-1 doc), Phase 2 ports EXACTLY the two `ExternalCondition`
variants Uthros + Sami need. The full surface (And/Or/Not
combinators, target-dependent variants, `DuringYourTurn`,
`VoidActiveCondition`, etc.) is **strictly larger** than the
combined Phase-1+Phase-2 substrate and would block Phase 2
indefinitely. Each subsequent phase adds the minimum new
grammar its cards need.

### 10.3 Combine `CostReduction` + `ExternalCostReduction` into one struct

**Rejected.** Python keeps them as semantically distinct
dataclasses (`cards/base.py:308` vs `:326`) — same layout
(`amount`, `condition`) but distinct evaluation rules: spell-
local reductions evaluate against the spell's OWN
`cost_reductions` once during cost-pay; externals scan the
controller's battlefield each cast. Phase 2 mirrors the Python
distinction. The cost of having two structs is one declaration's
worth of code; the benefit is a 1:1 wire-token correspondence
with Python (`cost_reductions` ↔ `external_cost_reductions`)
that round-trips byte-equal without ambiguity. If Phase 3
demonstrates the two enums can collapse (§4.2 docstring), the
combine can land then with a single migration.

### 10.4 Cache `Player.artifacts_controlled_count` on `Player`

**Rejected for Phase 2.** A cached counter would have to update
on every artifact ETB / death / type-loss / control-change /
phasing-in/out — surface area we don't need for the 2-card
slice this phase admits. The dynamic scan (§4.4) is
O(battlefield-size) which is bounded by the same small N the
Phase-1 `OpponentsControlAtLeast` scan already iterates without
issue (logged at `state_ops_legal.rs:801-823`). The precedent
for caching (`artifacts_entered_under_your_control_this_turn`
at `state.rs:1077`) exists IF a future profile shows it
mattering; Phase 2 ships dynamic + an SL entry (§9 entry 2)
flagging the deferred caching.

### 10.5 Widen the existing 9 sibling `cost_reductions or
external_cost_reductions: return False` guards in Phase 2

**Rejected — the round-38-E5 anti-pattern.** Same reasoning as
the Phase-1 doc §10.4: deleting the 9 sibling guards would
admit Phase-2 + Phase-3 cards into the bench WITHOUT
the guardrail differentiating Phase-2-admitted from Phase-3-
deferred shapes, producing a silent guaranteed divergence on
Fungal Colossus (Python's cast pipeline reduces; Rust pays
full cost — mana-pool fingerprint mismatch on the first cast).
The widened `_printing_is_bridge_pure_cost_reduction_creature`
predicate (§5.4) is the SINGLE positive-allowlist gate; the 9
negative guards on every other predicate stay in place. The
substrate has to land before any admission is bridge-correct.

## 11. Acceptance / sign-off

Phase 2 is complete and ready to merge to `main` when:

1. All 14 pins (§7.1-§7.4) pass on the parity gate.
2. The Uthros Psionicist + Sami, Wildcat Captain real-EoE
   probes (§7.3) pass byte-equal through both the full-cost
   and reduced-cost paths on both engines.
3. The decline-set bench check confirms +2 cards admitted
   (Uthros, Sami), Fungal STILL declined, 0 spillover.
4. Both SEARCH_LIMITATIONS.md entries (§9) land alongside the
   substrate code.
5. `.pyd` rebuilt clean; the parity gate
   (`tests/test_parity_smoke.py + test_cross_engine_etb_triggers.py
   + test_trajectory_parity.py + test_trajectory.py +
   test_measure_pool_parity.py`) stays green.

## 12. Cross-references

- `docs/COST_REDUCTION_SUBSTRATE_PHASE_1_DESIGN.md` — the
  Phase-1 campaign scoping doc (merge `4b94f844`); §3.1 / §8 /
  §10 are this doc's direct predecessors.
- `docs/COST_REDUCTION_SUBSYSTEM_REVISIT_2026-05-24.md` — the
  2026-05-24 revisit that confirmed 5/5 GENUINELY-DEFERRED and
  recommended this campaign (merge `added6db`).
- `src/mtg_bot/cards/base.py:308-345` — the Python
  `CostReduction` (Phase 1) + `ExternalCostReduction` (Phase 2)
  dataclasses (live source of truth).
- `src/mtg_bot/cards/base.py:764-771` — `CardPrinting.
  cost_reductions` + `CardPrinting.external_cost_reductions`
  fields.
- `src/mtg_bot/effects/conditions.py:235-262` —
  `AnotherSpellCastThisTurn` (Phase 1) + `NthSpellThisTurn`
  (Phase 2) class definitions.
- `src/mtg_bot/effects/conditions.py:405-434` —
  `PerControlled` class definition (Phase 2's variable-
  multiplier carrier).
- `src/mtg_bot/effects/object_predicates.py:131-138` —
  `IsArtifact` predicate (Phase 2's `TypeFilter::Artifact`
  mirror).
- `src/mtg_bot/actions.py:406-507` — Python's
  `apply_cost_reductions` (Phase 1) +
  `_apply_external_cost_reductions` (Phase 2's reference
  implementation).
- `src/mtg_bot/cards/parser/cost_reduction.py:171-237` — the
  parser's recognizers for Uthros's `_EXTERNAL_COST_REDUCTION_
  LINES` + Sami's `_EXTERNAL_COST_REDUCTION_KEYWORD_LINES`.
- `rust/src/cards.rs:9788-9852` — Phase-1 `CostReduction` /
  `Condition` / `TypeFilter` declarations (Phase-2 extends).
- `rust/src/cards.rs:10538` — Phase-1 `CardPrinting.
  cost_reductions` field (Phase-2 adds sibling
  `external_cost_reductions`).
- `rust/src/cards.rs:15226-15419` — Phase-1
  `parse_printing` cost_reductions arm (Phase-2 adds sibling
  external_cost_reductions arm).
- `rust/src/state_ops_legal.rs:764-838` — Phase-1
  `apply_cost_reductions_rust` (Phase-2 extends with the
  externals scan + helper `apply_external_cost_reductions_rust`).
- `rust/src/state_ops_legal.rs:2414,2444,2633,2645,2733,2797,
  2917` — the 7 legal-decision call sites (Phase 2 unchanged).
- `rust/src/state_ops_cast.rs:1167` — the cast-side call site
  (Phase 2 unchanged).
- `rust/src/state.rs:995-1017` — `Player.spells_cast_this_turn`
  (already shipped; Phase 2 reuses without modification).
- `src/mtg_bot/parity/trajectory.py:4940-5024` — the Phase-1
  admit predicate `_printing_is_bridge_pure_cost_reduction_
  creature` (Phase 2 widens per §5.4 Option A).
- `src/mtg_bot/parity/cross_engine.py:597` — the Phase-1
  CardDef `cost_reductions` field (Phase 2 adds sibling
  `external_cost_reductions`).
- `src/mtg_bot/parity/cross_engine.py:13598-13605` — the
  Phase-1 `_spec_card_to_printing_dict` emit (Phase 2 adds
  sibling externals emit).
- `src/mtg_bot/parity/cross_engine.py:14354-14384` — the
  Phase-1 `_card_def_to_python_printing` reverse arm (Phase 2
  adds sibling externals reverse arm).
- `tests/test_probe_gigastorm_titan_real_eoe_cost_reduction.py`
  + `tests/test_probe_lashwhip_predator_real_eoe_cost_
  reduction.py` — the Phase-1 6-pin probe shape Phase-2 probes
  mirror.

## 13. Regenerating the enumeration

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
  scripts/scout_r60_cost_reduction_shapes.py
```

reproduces the post-Phase-1 cost-reduction declined set / per-
sub-shape rollup / parsed external/spell-local structure exactly
(verified by the round-60 scout + the 2026-05-24 revisit +
the post-Phase-1 POOL_PARITY rollup at `6c4ee310`: 3 declined,
3 single-gated, 0 multi-gated, 28,740 summed decks). The live
parsed `cost_reductions` / `external_cost_reductions` for the
3 declined cards (§1.2 table) are verifiable via
`OracleParserCardSource().get_printings()[<name>]`. All §4-§6
file:line refs verified against main `6c4ee310`.
