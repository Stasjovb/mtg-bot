Generated 2026-05-25 (post `cost-reduction-phase-2-cycle-4-
sami-probe-p1`, merge `4b683928` — Phase 2 closure). **Design
only — NO production / `_SAFE_*` / Rust change in this slice; no
gate run beyond `tests/test_measure_pool_parity.py` 31/31** (docs +
read-only scout against the live tree). This doc scopes
cost-reduction substrate **Phase 3** in the campaign sequencing
the Phase 1 + Phase 2 design docs
(`docs/COST_REDUCTION_SUBSTRATE_PHASE_1_DESIGN.md` at `4b94f844`
and `docs/COST_REDUCTION_SUBSTRATE_PHASE_2_DESIGN.md` at
`f75dbf0e`) committed to. Every file:line below is verified
against the live tree at main `4b683928`.

> **Relationship to the Phase 1 + Phase 2 design docs.** Phase 1
> closed CLEAN across 4 cycles (`3683e62e` / `8593b0fb` /
> `1f13f092` / `6c4ee310`) admitting **Gigastorm Titan + Lashwhip
> Predator** (sub-shape A — spell-local boolean `CostReduction`).
> Phase 2 closed CLEAN across 4 cycles (`5fa32697` / `c370cee4` /
> `809d546c` / `4b683928`) admitting **Uthros Psionicist + Sami,
> Wildcat Captain** (sub-shapes B + C — `ExternalCostReduction`
> with `NthSpellThisTurn` + `PerControlled(IsArtifact())`). The
> two prior docs deferred **Fungal Colossus** (sub-shape D —
> spell-local variable-X `PerDifferentlyNamedLand`) to this
> Phase 3; the Phase 2 doc additionally deferred planeswalker-
> loyalty-cost reductions to Phase 4. **This doc takes over the
> campaign-scoping role for Phase 3** — narrowed to the ONE
> remaining single-gated cost-reduction card. Phase 3 closure
> drives the cost-reduction substrate's single-gated row to
> exactly zero and BLOCKED 56 → 55. The Phase 2 doc's §3.1 +
> §3.2 framing remain canonical and are restated here as Phase 3
> body + Phase 4 deferral.

# cost-reduction substrate Phase 3 — campaign scoping doc (sub-shape D: 1 card / 13,165 17lands decks)

## 0. Executive summary

Phase 2 closed today with **4 / 5 cost-reduction-single-gated
cards PROBED** (Gigastorm Titan + Lashwhip Predator from Phase 1
+ Uthros Psionicist + Sami, Wildcat Captain from Phase 2;
`3683e62e` / `8593b0fb` / `1f13f092` / `6c4ee310` / `5fa32697` /
`c370cee4` / `809d546c` / `4b683928`), unblocking 40,483 17lands
decks combined (76 % of the cost-reduction single-gated pool —
24,908 from Phase 1 + 15,575 from Phase 2). **Exactly 1 card
remains** behind a Phase-3 sub-shape gate — verified against the
live `docs/POOL_PARITY.md:437` row "Cost-reduction substrate | 1
| 1 | 0 | 13,165 | 13,165":

| Card | Sub-shape | Decks | Gate |
|---|---|---:|---|
| **Fungal Colossus** | D (spell-local variable-X `PerDifferentlyNamedLand`) | ~13,165 | this doc |

This doc scopes Phase 3: admit sub-shape D — the 1 card
**Fungal Colossus** (13,165 17lands decks — 100 % of the
cost-reduction REMAINING single-gated deck count and the entire
spell-local variable-multiplier slice). Phase 3 explicitly
**defers** planeswalker-loyalty-cost reductions (Phase 4 — out
of substrate; no live cost-reduction-gated planeswalker is in
the post-Phase-2 single-gated declined set).

Estimated campaign scope, calibrated against the Phase 1 closure
(4 cycles for 2 cards) and Phase 2 closure (4 cycles for 2
cards): **~3-4 Rust cycles total for cost-reduction Phase 3** —
1 substrate landing + 1 FLIP (admit-widen + bridge round-trip) +
1 per-card real-EoE probe cycle for Fungal Colossus + 1 optional
docs / SL / POOL_PARITY consolidation cycle. The per-card count
is lower than Phase 1 / Phase 2 because there is exactly **one**
carrier in sub-shape D — Phase 3 ships the smallest single-card
substrate-and-FLIP slice the campaign has produced.

**Phase 3 closure drives the cost-reduction substrate single-
gated row from 1 card to 0 cards, dropping BLOCKED from 56 to 55
and retiring the cost-reduction substrate entirely from the
single-gated rollup.**

## 1. Background — why this sub-shape, why now

### 1.1 Phase 1 + Phase 2 closure recap

Phase 1 closed CLEAN across 4 cycles (verified live `4b94f844..6c4ee310`):

- **C1 substrate** (`3683e62e`) — Rust `CardPrinting.cost_reductions:
  Vec<CostReduction>` field + `CostReduction` struct + `Condition`
  enum (2 variants: `AnotherSpellCastThisTurn`,
  `OpponentsControlAtLeast{TypeFilter::Creature, count}`) +
  `TypeFilter` enum (1 variant: `Creature`) + `parse_printing`
  cost_reductions arm + hard-error on unknown `condition_kind`.
- **C2 FLIP** (`8593b0fb`) — `apply_cost_reductions_rust(state,
  caster_idx, printing, base) -> ManaCost` at
  `rust/src/state_ops_legal.rs:764` wired into all 7 `CastSpell`
  affordability + cast-pay sites. CardDef `cost_reductions:
  tuple[tuple[int, str, tuple], ...]` field +
  `_spec_card_to_printing_dict` emit + `_card_def_to_python_printing`
  reverse arm. New admit predicate
  `_printing_is_bridge_pure_cost_reduction_creature` at
  `src/mtg_bot/parity/trajectory.py:4975`.
- **C3 Gigastorm probe** (`1f13f092`) + **C4 Lashwhip probe**
  (`6c4ee310`) — per-card real-EoE byte-equal probes.

Phase 2 closed CLEAN across 4 cycles (verified live `f75dbf0e..4b683928`):

- **C1 substrate** (`5fa32697`) — Rust `CardPrinting.
  external_cost_reductions: Vec<ExternalCostReduction>` field +
  `ExternalCostReduction` struct + `ExternalCondition` enum
  (2 variants: `NthSpellThisTurn{n}`, `PerControlled{type_filter}`) +
  `TypeFilter::Artifact` variant + `parse_printing`
  external_cost_reductions arm + extension to
  `apply_cost_reductions_rust` with the externals scan
  `apply_external_cost_reductions_rust`
  (`state_ops_legal.rs:897`).
- **C2 FLIP** (`c370cee4`) — CardDef
  `external_cost_reductions` field + bridge round-trip arms +
  **widened** `_printing_is_bridge_pure_cost_reduction_creature`
  (Option A — single named admit site for both Phase-1 and
  Phase-2 carriers).
- **C3 Uthros probe** (`809d546c`) + **C4 Sami probe**
  (`4b683928`) — per-card real-EoE byte-equal probes.

The Phase-1 + Phase-2 substrate is the foundation Phase 3 extends:

- The spell-local `Condition` enum at `rust/src/cards.rs:9845`
  currently has EXACTLY two variants (`AnotherSpellCastThisTurn`,
  `OpponentsControlAtLeast{type_filter, count}`). **Phase 3
  appends a third variant `PerDifferentlyNamedLand` to this
  enum** — the spell-local sibling of Phase-2's
  `ExternalCondition::PerControlled` variable-multiplier path.
- `apply_cost_reductions_rust` at
  `rust/src/state_ops_legal.rs:764` is `pub(crate)` and used at
  7 call sites. Phase 3 extends the helper's body's
  `match &rule.condition` arm with the new variant; the 7 call
  sites remain unchanged.
- `_printing_is_bridge_pure_cost_reduction_creature` at
  `trajectory.py:4975` is the single named admit predicate;
  Phase 3 widens `_cost_reduction_rule_is_phase1` (renaming to
  `_cost_reduction_rule_is_phase1_or_3` is optional — see §6) to
  accept the new variant on the spell-local side.
- `Player.spells_cast_this_turn` (Phase 1 inheritance) is
  **unused by Phase 3** — the new variant reads a different
  state slice (the caster's lands by name).

### 1.2 The post-Phase-2 declined inventory

Verified live against `OracleParserCardSource` at main `4b683928`
(per the post-Phase-2 admit-gate audit + the
`docs/POOL_PARITY.md:437` rollup):

| Card | live parsed shape | mana_cost | 17lands decks | other riders | Phase |
|---|---|---|---:|---|---|
| **Fungal Colossus** | `cost_reductions=(CostReduction(amount=1, condition=PerDifferentlyNamedLand()),)` | `{6}{G}` | ~13,165 | NONE (verified live below) | **3** |

**Phase-3 deck total: 13,165 17lands decks** (single-card
slice). Verified `OracleParserCardSource()
.get_printings()["Fungal Colossus"]` at main `4b683928` produces:

- `card_types=('Creature',)`
- `mana_cost_str='{6}{G}'`
- `power=5, toughness=5`
- `keywords=frozenset()` (no keywords)
- `cost_reductions=(CostReduction(amount=1,
  condition=PerDifferentlyNamedLand()),)`
- `external_cost_reductions=()`
- `triggered_abilities=()` / `activated_abilities=()` /
  `static_abilities=()`
- `spell_effect=None` / `warp_cost=None` / `kicker_cost=None` /
  `impending_cost=None` / `room_halves=()` / `loyalty=None` /
  `station_threshold=None` / `dynamic_pt_formula=None` /
  `ward_cost=None`

The ONLY blocking feature on Fungal Colossus is the spell-local
`cost_reductions` tuple whose condition is
`PerDifferentlyNamedLand()`. Strip it and Fungal is a pure
bridge-simple 5/5 vanilla creature for `{6}{G}` (NO keywords,
NO triggered/activated/static abilities, NO co-gating). This is
the same minimal-blocking-feature shape Phase 1 verified for
Gigastorm + Lashwhip and Phase 2 verified for Uthros + Sami.

### 1.3 Why D ships in its own phase (not folded into 1 or 2)

The Phase-1 + Phase-2 design docs both deferred sub-shape D to a
dedicated phase. Three structural reasons:

- **Spell-local, not external.** Fungal's rider lives on the
  spell's own `cost_reductions` (NOT
  `external_cost_reductions`). The substrate is the existing
  Phase-1 `Condition` enum and its spell-local evaluator at
  `apply_cost_reductions_rust:786-848` — NOT Phase-2's new
  `ExternalCondition` enum or the externals battlefield-scan
  loop at `apply_external_cost_reductions_rust:897-974`.
- **Variable-multiplier on the spell-local side.** Phase 1's
  two `Condition` variants both have implicit `multiplier()==1`
  (no scaling). Phase 2's `ExternalCondition::PerControlled`
  was the FIRST variable-multiplier this engine evaluates non-
  trivially, but only on the externals side. Phase 3 introduces
  variable-multiplier evaluation on the **spell-local** side
  for the first time — the existing
  `apply_cost_reductions_rust` body's `if holds &&
  rule.amount > 0` reduction step at
  `state_ops_legal.rs:849-857` needs a multiplier hook
  alongside the boolean-holds check.
- **`len(set)`-over-name semantic, not count-over-filter.**
  Phase-2's `PerControlled` multiplier is `count(permanents
  matching type_filter)` — a plain count over a `TypeFilter`
  enum. Phase 3's `PerDifferentlyNamedLand` multiplier is
  `len(set(p.printing.name for p in battlefield if
  p.controller_id == caster_id and p.printing.is_land))` — a
  `len(set)` accumulator over a printing-name string slice
  filtered by `is_land`, fundamentally different from
  `PerControlled`'s `count(filter)` shape. Sub-shape D needs a
  new evaluator arm, not a new `TypeFilter` variant.

Folding D into Phase 1 would have required landing the variable-
multiplier path on the spell-local side at C1 without a carrier
to motivate it; folding D into Phase 2 would have conflated the
spell-local + externals substrates and broken the round-59 sub-
shape-split discipline that drove the Phase 1 / 2 cadence. The
Phase-2 doc §3.1 explicitly framed D's deferral as "structurally
orthogonal to Phase 2 in TWO axes" — this doc closes that
deferral with its own minimal slice.

### 1.4 Calibration against Phase 1 + Phase 2

Phase 1 closed at 4 cycles (vs ~5 estimate); Phase 2 closed at 4
cycles (matching estimate). Phase 3 is **comparable in shape but
~half the per-card surface** because there is exactly one
carrier:

- **Smaller:** Phase 3 does NOT add a new struct / a new
  per-player state field / a new externals battlefield scan /
  a new `TypeFilter` variant. Phase 3 adds EXACTLY one
  `Condition` enum variant + one variable-multiplier hook in
  the existing spell-local evaluator.
- **Same:** Phase 3 needs a bridge round-trip arm (forward
  emit + reverse re-materialization) for the new
  `condition_kind` wire token + an admit-predicate widening
  for the new shape.
- **Smaller:** Phase 3 has 1 per-card probe vs Phase 1 / Phase
  2's 2 per-card probes. The substrate-and-FLIP cycle can ship
  alongside the probe in 3 cycles total, or split into 4 for
  cleaner per-cycle diff review (see §8).

The campaign-total estimate aligns with the Phase-1 + Phase-2
docs: Phase 1 = 4 cycles, Phase 2 = 4 cycles, Phase 3 = 3-4
cycles, **total = 11-12 cycles across the cost-reduction
substrate campaign**, slightly above the Phase-1 doc's ~10 estimate
but tracking the actual closure cadence.

## 2. Sub-shape D scope — exactly 1 card, the spell-local variable-X subset

Verified live against `OracleParserCardSource` at main `4b683928`:

### 2.1 Sub-shape D — `PerDifferentlyNamedLand` (Fungal Colossus)

Live parsed shape:

```python
cost_reductions=(
    CostReduction(amount=1, condition=PerDifferentlyNamedLand()),
)
```

Oracle line that gates the parser claim (per
`src/mtg_bot/cards/parser/cost_reduction.py:117-120`):

```
This spell costs {X} less to cast, where X is the number of
differently named lands you control.
```

The `_COST_REDUCTION_LINE_X_PER_DIFFERENTLY_NAMED_LAND` literal
in the parser table (`cost_reduction.py:117-120`) maps the
whole-rider line to `CostReduction(amount=1,
condition=PerDifferentlyNamedLand())`. The unit `amount=1`
combined with the multiplier returned by
`PerDifferentlyNamedLand.multiplier(state, viewer_id)` yields
the engine's `{X}` semantic (`amount * multiplier == 1 *
distinct_land_names`).

`PerDifferentlyNamedLand.matches(state, viewer_id)` and
`PerDifferentlyNamedLand.multiplier(state, viewer_id)` (verified
at `src/mtg_bot/effects/conditions.py:376-402`):

```python
def _names(self, state, viewer_id) -> set[str]:
    names: set[str] = set()
    for o in state.battlefield:
        if o.controller_id == viewer_id and o.printing.is_land:
            names.add(o.printing.name)
    return names

def matches(self, state, viewer_id, chosen_targets=None):
    return len(self._names(state, viewer_id)) >= 1

def multiplier(self, state, viewer_id, chosen_targets=None):
    return len(self._names(state, viewer_id))
```

That is: `matches` returns True iff the caster controls at least
1 land; `multiplier` returns the count of distinctly-named lands
the caster controls. **The set is keyed on `printing.name` (a
string field on `CardPrinting`), NOT on `printing_id`** — two
copies of `Forest` count as 1 toward the multiplier; one Forest
and one Mountain count as 2. This is the cleanest single-card
semantic distinction from Phase 2's `PerControlled` (which counts
permanents, not distinct names).

For Fungal Colossus with `amount=1`: the reduction is `1 *
distinct_land_names`. With 4 distinctly-named lands (e.g.
Forest + Mountain + Plains + Swamp) the reduction is `{4}` —
Fungal's printed cost is `{6}{G}`, the paid cost is `{2}{G}`
(generic clamped at 0 mirroring Phase 1 + Phase 2's reduction
semantics; colored pips and `x_pips` untouched per
`ManaCost.reduced` at `cards/base.py:299-305`).

### 2.2 Combined scope

| Card | `cost_reductions` shape | mana_cost | 17lands decks |
|---|---|---|---:|
| Fungal Colossus | `(CostReduction(amount=1, PerDifferentlyNamedLand()),)` | `{6}{G}` | ~13,165 |

**Phase-3 deck total: 13,165 17lands decks** (single card).

The rider satisfies the minimal-scope criteria:

- The rider is on `printing.cost_reductions` (verified live:
  `cards/base.py:764` for the printing field; the dataclass at
  `:308-322`).
- The condition is EXACTLY one new structural variant
  (`PerDifferentlyNamedLand` — Phase-1 + Phase-2 both deferred
  this).
- `external_cost_reductions == ()` (verified live — the
  spell-local rider is the only one; the Phase-2 externals
  substrate is unused by Fungal).
- No other blocking feature on the card (verified live in
  §1.2 — `keywords=frozenset()`, no triggered/activated/static
  abilities, no `spell_effect`, no `kicker_cost` /
  `impending_cost` / `warp_cost`, no `room_halves`, no loyalty,
  no `station_threshold`, no `dynamic_pt_formula`, no
  `ward_cost`).

The ONLY blocking feature on Fungal Colossus is the
`cost_reductions` tuple's `PerDifferentlyNamedLand()` condition.
Strip it and Fungal is a pure bridge-simple 5/5 vanilla creature.

### 2.3 Routing decision: spell-local `cost_reductions`, NOT externals

**Verified live: Fungal Colossus's rider lives on
`cost_reductions` (the spell-local list), NOT on
`external_cost_reductions`.** This is the canonical decision
this doc commits to, with two independent verifications:

1. The live `OracleParserCardSource().get_printings()
   ["Fungal Colossus"]` shape (§1.2 + §2.1) shows
   `cost_reductions=(CostReduction(...),)` and
   `external_cost_reductions=()`.
2. The parser routing in
   `src/mtg_bot/cards/parser/cost_reduction.py:264-267`
   constructs the `CostReduction` (spell-local) dataclass — not
   `ExternalCostReduction` — when the
   `_COST_REDUCTION_LINE_X_PER_DIFFERENTLY_NAMED_LAND` line
   matches.

The structural reason: Fungal's "This spell costs {X} less" line
reduces ITS OWN cost (the cost of the Fungal Colossus card being
cast), NOT some other spell the controller casts. That is the
defining distinction between the two dataclasses at
`cards/base.py:308-345`: `CostReduction` is "baked into the
spell being cast and reduces ITS own cost"; `ExternalCostReduction`
is "static cost-reduction granted by a permanent on the battlefield
to OTHER spells the controller casts". Fungal's rider is
self-referential — it reduces the cost of Fungal itself — so it
lives spell-local.

**Implication for the Rust port (§4):** Phase 3 adds the new
variant to the spell-local `Condition` enum at
`rust/src/cards.rs:9845`, NOT to the externals
`ExternalCondition` enum at `rust/src/cards.rs:9913`. The
evaluator extension lives in `apply_cost_reductions_rust`'s
spell-local match arm at `state_ops_legal.rs:786-848`, NOT in
`apply_external_cost_reductions_rust:897-974`.

## 3. Out-of-scope (deferred to Phase 4+)

The following are explicitly **NOT** in Phase 3's scope. The
Phase-3 filter guardrail (§6) positively rejects each so they
cannot reach the Phase-3 reduced-cost path:

### 3.1 Planeswalker-loyalty-cost reductions (Phase 4 — out of substrate)

Planeswalker activated abilities can carry their own cost-reduction
riders via `ActivatedAbility.cost_reductions` (referenced at
`rust/src/cards.rs:9941`'s `ActivatedAbility` Slice-1 deferral
comment). **Out of substrate** by the same reasoning the Phase-1
doc §3.4 stated and the Phase-2 doc §3.2 restated: loyalty-cost
reductions are a parallel rider on a different cost-paying
primitive (ability activation, not spell cast), composing
orthogonally with the spell-cast cost-reduction substrate this
campaign is closing. No live cost-reduction-gated planeswalker
is in the post-Phase-2 single-gated declined set — verified
against the `docs/POOL_PARITY.md:437` rollup (1 card, Fungal
Colossus, sub-shape D only; no planeswalker carrier exists).
Phase 4 (if scoped at all) is a separate substrate slice with
its own design doc; it does NOT block Phase 3 closure.

### 3.2 Combining Phase 1 + Phase 2 + Phase 3 into one mega-Condition enum

**Rejected** (see §10.1). Each phase's substrate scope drove its
own minimal `Condition`-grammar slice (Phase 1: 2 boolean
variants on spell-local `Condition`; Phase 2: 2 variants on a
new `ExternalCondition` enum + 1 new `TypeFilter` variant;
Phase 3: 1 variant on spell-local `Condition`). Folding the
three into a single mega-enum at Phase 3 would conflate three
independent substrates and violate the round-59 sub-shape-split
discipline that drove the Phase 1 / 2 / 3 cadence. The split
also matches Python's `Condition` vs `ExternalCondition`
dataclass distinction — see §10.1 for the full rejection. The
post-Phase-3 question of whether `Condition` and
`ExternalCondition` should unify (now that both have a variable-
multiplier path) is **deferred to a separate consolidation
slice** — that slice may land standalone or as a Phase-4
prologue, but is NOT in Phase 3 scope.

### 3.3 Generic `Condition::*` predicate algebra (post-Phase-3)

Like Phase 1's narrow port of `Condition` and Phase 2's narrow
port of `ExternalCondition`, Phase 3 ports EXACTLY the one
`PerDifferentlyNamedLand` variant Fungal needs. The full
`Condition`-grammar surface (`AndCondition` / `OrCondition` /
`NotCondition` combinators, `TargetMatches` / `ChosenTargets`-
dependent variants, the `DuringYourTurn` / `VoidActiveCondition` /
`AttackedWithThisTurn` family, the generic `ObjectPredicate`
filter algebra beyond `TypeFilter::Creature` /
`TypeFilter::Artifact`) is **not in scope**. There is no live
post-Phase-3 cost-reduction-gated carrier needing any of these;
they would be admitted on demand by future substrate phases for
other subsystems (e.g. continuous-effect gates, static-ability
predicates) and are not driven by the cost-reduction substrate
campaign.

### 3.4 Caching distinct-land-names on `Player`

**Rejected for Phase 3** (see §10.4). A cached counter / set
would have to update on every land ETB / death / type-loss /
control-change / phasing-in/out / name-change — surface area we
don't need for the 1-card slice this phase admits. The dynamic
scan (§4.4) is `O(battlefield-size)` to walk + `O(land-count)`
to insert into the `HashSet<&str>`, both bounded by the same
small N the Phase-1 / Phase-2 scans already iterate without
issue.

## 4. Rust-side spec — the new variant, evaluator extension, and bridge arms

### 4.1 Append `Condition::PerDifferentlyNamedLand` variant

**File:** `rust/src/cards.rs`. Append to the existing
`Condition` enum (declared at `cards.rs:9845`, currently 2
variants — `AnotherSpellCastThisTurn` + `OpponentsControlAtLeast{
type_filter, count}`). No new payload — the variant is unit-shape
(no fields), mirroring Python's `PerDifferentlyNamedLand` dataclass
at `effects/conditions.py:375-402` (which carries no fields beyond
the inherited `Condition` interface):

```rust
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Condition {
    AnotherSpellCastThisTurn,
    OpponentsControlAtLeast { type_filter: TypeFilter, count: i32 },
    /// **cost-reduction substrate Phase 3.** Python
    /// `PerDifferentlyNamedLand` (`effects/conditions.py:375-402`):
    /// the variable-multiplier condition Fungal Colossus uses for
    /// its "This spell costs {X} less to cast, where X is the
    /// number of differently named lands you control" rider.
    /// `matches()` returns True iff `len(distinct_land_names) >= 1`;
    /// `multiplier()` IS the distinct-land-name count.
    ///
    /// **Variable-multiplier on the spell-local side — the FIRST
    /// non-trivial multiplier in the spell-local `Condition` enum.**
    /// Phase 1 + Phase 2 both kept the spell-local enum at implicit
    /// `multiplier()==1` (boolean conditions only); Phase 3
    /// introduces the variable-multiplier hook here. The evaluator
    /// at `state_ops_legal.rs:849-857`'s reduction step is extended
    /// to multiply `rule.amount` by the per-variant multiplier
    /// (Phase 1 + Phase 2 variants implicit `1`; Phase 3 variant
    /// reads `distinct_land_names_count(state, caster_idx)`).
    ///
    /// **Why the spell-local enum, not `ExternalCondition`?**
    /// Verified live: Fungal's rider is on `printing.cost_reductions`
    /// (the spell-local list), not on
    /// `printing.external_cost_reductions`. The Python parser at
    /// `cards/parser/cost_reduction.py:264-267` constructs a
    /// `CostReduction` (spell-local) dataclass — NOT
    /// `ExternalCostReduction` — for Fungal's whole-rider line.
    /// Structural reason: Fungal's "{X} less" line reduces ITS OWN
    /// cost (the Fungal spell being cast), not some other spell.
    /// That is the defining distinction between the two dataclasses
    /// at `cards/base.py:308-345`.
    ///
    /// **No payload (unit variant).** Python's
    /// `PerDifferentlyNamedLand` carries no fields beyond the
    /// inherited `Condition` interface; the bridge wire token
    /// `"per_differently_named_land"` has `args = ()` (empty
    /// tuple), mirroring Phase 1's
    /// `"another_spell_cast_this_turn"` shape.
    PerDifferentlyNamedLand,
}
```

### 4.2 No new `TypeFilter` variant, no new state field, no new struct

Three explicit non-additions Phase 3 verifies against live code:

- **No new `TypeFilter` variant.** The new condition does NOT
  filter battlefield by card type — it filters by `is_land`
  (already a CardPrinting bool field per the live Python
  `cards/base.py` + the Rust mirror at `cards.rs` referenced
  in `Predicate::SubjectIsLand` at `cards.rs:16094` + many
  legality-side `pr.is_land` checks). The `TypeFilter` enum
  stays at its Phase-2 shape (`Creature`, `Artifact`).
- **No new state field.** Distinct-land-names is computed
  dynamically from
  `state.players[caster_idx].battlefield` + the per-permanent
  printing lookup (printing name string) — same shape Phase 2's
  `PerControlled` uses, with the `HashSet<&str>` accumulator
  replacing Phase 2's plain counter.
- **No new struct.** `CostReduction` (spell-local) at
  `cards.rs:9800` already carries `amount: i32` +
  `condition: Condition`; the existing struct admits the new
  variant verbatim. The two-struct distinction (Phase-1
  `CostReduction` vs Phase-2 `ExternalCostReduction`) remains
  unchanged — Phase 3 does NOT modify
  `ExternalCostReduction` / `ExternalCondition` at all.

The Phase-3 substrate is **strictly smaller than Phase 1 +
Phase 2**: 1 enum variant + 1 helper + 1 evaluator-arm extension.

### 4.3 New `unique_land_names_count` helper

**File:** `rust/src/state_ops_legal.rs` (alongside
`apply_cost_reductions_rust`). New small helper that computes
the distinct-land-name multiplier for the new variant:

```rust
/// **cost-reduction substrate Phase 3.** Computes the count of
/// distinctly-named lands the caster controls — the variable-X
/// multiplier for `Condition::PerDifferentlyNamedLand`. Mirror
/// of Python `PerDifferentlyNamedLand._names`
/// (`src/mtg_bot/effects/conditions.py:391-396`):
///
///     def _names(self, state, viewer_id) -> set[str]:
///         names: set[str] = set()
///         for o in state.battlefield:
///             if o.controller_id == viewer_id and o.printing.is_land:
///                 names.add(o.printing.name)
///         return names
///
/// Returns `len(self._names(state, viewer_id))` directly without
/// the set-allocation roundtrip when the Rust path can use a
/// `HashSet<&str>` borrowing the printing-name slice. The set is
/// keyed on `printing.name` (a string field on `CardPrinting`),
/// NOT on `printing_id` — two copies of `Forest` count as 1
/// toward the multiplier (the spec's "differently named"
/// distinction).
///
/// **Per-caster scope.** Walks
/// `state.players[caster_idx].battlefield` only (the externals
/// substrate sibling at `apply_external_cost_reductions_rust:903`
/// uses the same iteration shape). Opponents' lands are NOT
/// counted — the Python implementation's `o.controller_id ==
/// viewer_id` gate mirrors this; Rust's per-caster battlefield
/// iteration is equivalent (each player owns + controls their
/// own battlefield in the current engine — see
/// `state_ops_legal.rs:903`'s comment for the same shape).
///
/// **Cost.** O(battlefield-size) walk + O(land-count)
/// HashSet insertion. Bounded by the same small N the Phase-1
/// `OpponentsControlAtLeast` scan + Phase-2 `PerControlled`
/// scan already iterate without issue. See §10.4 for the
/// rejected-alternative caching analysis.
#[inline]
fn unique_land_names_count(
    state: &crate::state::GameState,
    caster_idx: usize,
) -> i32 {
    use std::collections::HashSet;
    let mut names: HashSet<&str> = HashSet::new();
    for permanent in state.players[caster_idx].battlefield.iter() {
        let Some(pr) = state.registry.lookup(permanent.printing_id)
        else {
            continue;
        };
        if !pr.is_land {
            continue;
        }
        names.insert(pr.name.as_ref());
    }
    names.len() as i32
}
```

### 4.4 Extend `apply_cost_reductions_rust`'s spell-local match arm

**File:** `rust/src/state_ops_legal.rs`. The spell-local
evaluator at `:786-848` currently dispatches on the 2-variant
Phase-1 `Condition` enum. Phase 3 appends a third arm. **Note
the multiplier path:** Phase 1 + Phase 2 both kept the spell-
local reduction step at `holds && rule.amount > 0` →
`saturating_sub(amount as u8)` — implicit `multiplier == 1`
because the two Phase-1 variants are booleans. Phase 3 introduces
the FIRST spell-local multiplier; the arm computes the
multiplier inside the match (returning a `(holds, multiplier)`
pair shape mirroring Phase 2's externals match at `:912-958`),
and the reduction step is extended to multiply.

Spec body (the consolidated change — replaces the existing
spell-local match + reduction step at `:786-857`):

```rust
for rule in printing.cost_reductions.iter() {
    // Mirror Phase 2's externals match shape at
    // state_ops_legal.rs:912-958 — return (holds, multiplier)
    // so the new variable-multiplier variant composes cleanly
    // with the existing implicit-1 boolean variants.
    let (holds, multiplier) = match &rule.condition {
        crate::cards::Condition::AnotherSpellCastThisTurn => {
            // Phase 1 (unchanged). Multiplier implicit 1.
            let holds = state.players[caster_idx]
                .spells_cast_this_turn
                >= 1;
            (holds, 1i32)
        }
        crate::cards::Condition::OpponentsControlAtLeast {
            type_filter,
            count,
        } => {
            // Phase 1 (unchanged). Multiplier implicit 1. The
            // existing 'opps loop body lives here verbatim;
            // see state_ops_legal.rs:803-846 for the live shape.
            let n = *count;
            let mut found = 0i32;
            'opps: for (other_idx, other) in state.players.iter().enumerate() {
                if other_idx == caster_idx {
                    continue;
                }
                for obj in other.battlefield.iter() {
                    let Some(pr) = state.registry.lookup(obj.printing_id) else {
                        continue;
                    };
                    let matches = match type_filter {
                        crate::cards::TypeFilter::Creature => {
                            pr.card_types.iter().any(|t| t == "Creature")
                        }
                        crate::cards::TypeFilter::Artifact => {
                            pr.card_types.iter().any(|t| t == "Artifact")
                        }
                    };
                    if matches {
                        found += 1;
                        if found >= n {
                            break 'opps;
                        }
                    }
                }
            }
            (found >= n, 1i32)
        }
        // **Phase 3 (NEW).** Variable-X multiplier on the
        // spell-local side — the FIRST non-trivial multiplier
        // this enum evaluates. Mirrors Python
        // `PerDifferentlyNamedLand.matches` (>= 1) +
        // `PerDifferentlyNamedLand.multiplier` (the count
        // itself) at `effects/conditions.py:398-402`.
        crate::cards::Condition::PerDifferentlyNamedLand => {
            let count = unique_land_names_count(state, caster_idx);
            (count >= 1, count)
        }
    };
    if holds && rule.amount > 0 && multiplier > 0 {
        // Mirror Python `ManaCost.reduced`
        // (`cards/base.py:291-305`): clamp generic at 0, leave
        // colored pips untouched, preserve x_pips (CR 601.2f).
        // Clamp the multiplied amount at u8::MAX before
        // saturating_sub so a pathological large multiplier
        // (e.g. 100+ distinctly-named lands) still drops
        // cost.generic to 0 cleanly instead of overflowing
        // the i32→u8 cast. Same clamp shape Phase-2's
        // externals scan uses at state_ops_legal.rs:967-969.
        let amt = (rule.amount as i64) * (multiplier as i64);
        let amt_clamped = amt.min(u8::MAX as i64) as u8;
        cost.generic = cost.generic.saturating_sub(amt_clamped);
    }
}
```

The 7 existing call sites of `apply_cost_reductions_rust` are
unchanged — same signature, same surface, body extended in place.

### 4.5 No change to the externals scan, the `ExternalCondition` enum, or the `TypeFilter` enum

Verified explicitly: Phase 3's variant lives on the spell-local
`Condition` enum at `cards.rs:9845`. Phase 3 does NOT touch:

- `ExternalCostReduction` (`cards.rs:9889`) — Phase-2 sibling
  struct, unchanged.
- `ExternalCondition` (`cards.rs:9913`) — Phase-2 enum,
  unchanged. The Phase-2 doc §4.2 docstring notes "Phase 3 may
  UNIFY the enums" — that consolidation is deferred to a
  separate slice (§3.2), NOT in Phase 3 scope.
- `TypeFilter` (`cards.rs:9815`) — Phase-1 + Phase-2 enum,
  unchanged (Phase 3's condition has no `TypeFilter` payload).
- `apply_external_cost_reductions_rust`
  (`state_ops_legal.rs:897`) — Phase-2 externals scan,
  unchanged. The Phase-3 reduction composes through the same
  `apply_cost_reductions_rust` entrypoint that already calls
  externals first (`:779-781`).
- `Player.spells_cast_this_turn` — Phase-1 inheritance, unused
  by Phase 3's new variant.

### 4.6 Parse + to_pydict round-trip

**Parse** in `cards.rs::parse_printing`: extend the existing
`cost_reductions` arm (at `cards.rs:15333`) with a third
`condition_kind` branch (mirror of the Phase-1
`"another_spell_cast_this_turn"` shape — empty-args, hard-error
on arg drift):

```rust
let condition = match kind.as_str() {
    "another_spell_cast_this_turn" => {
        // [Phase 1 body unchanged — see cards.rs:15373-15403.]
        Condition::AnotherSpellCastThisTurn
    }
    "opponents_control_at_least" => {
        // [Phase 1 body unchanged — see cards.rs:15404-15470.]
        // ...
    }
    // **Phase 3 (NEW).** Variant takes no args; an arg drift
    // is a hard `Err` (the §2 teeth — same shape Phase 1's
    // `another_spell_cast_this_turn` arm uses).
    "per_differently_named_land" => {
        if let Some(args_any) = d.get_item("condition_args")? {
            let tup = args_any.downcast::<PyTuple>().map_err(|_| {
                PyValueError::new_err(
                    "cost_reductions[i].condition_args must be a tuple",
                )
            })?;
            if tup.len() != 0 {
                return Err(PyValueError::new_err(format!(
                    "cost_reductions[i] with condition_kind \
                     'per_differently_named_land' takes 0 args; got {}",
                    tup.len(),
                )));
            }
        }
        Condition::PerDifferentlyNamedLand
    }
    other => {
        return Err(PyValueError::new_err(format!(
            "cost_reductions[i] does not support condition_kind \
             {other:?} (Phase 3+ may add more)"
        )))
    }
};
```

The Phase-1 unknown-kind hard-error message at
`cards.rs:15471-15479` is updated to drop the
`per_differently_named_land` mention from the "Phase 2+ adds" list
(it is now landed). The Phase-2
`external_cost_reductions` parse arm at `cards.rs:15507` is
**unchanged** — Phase 3 does NOT add a sibling externals
variant.

**to_pydict** (the inverse, if a serializer arm exists): the
existing `printing_to_pydict`-style serializer (the
`cost_reductions`-shaped output Phase 1 added at the Phase-1 C1
landing) emits the same list-of-dicts structure for the bridge
round-trip; the new wire-token `"per_differently_named_land"`
with `condition_args=()` is emitted by the symmetric arm.

## 5. Python bridge spec — round-trip the new variant byte-equal

### 5.1 No new CardDef field

The CardDef `cost_reductions: tuple[tuple[int, str, tuple], ...]`
field at `src/mtg_bot/parity/cross_engine.py:597` (Phase-1
landing) admits the new tuple-of-triples shape without any
field-level change — the wire token `"per_differently_named_land"`
with `args = ()` matches the existing
`(amount, condition_kind, condition_args)` triple shape. Phase 3
does NOT add a sibling CardDef field; the field's docstring at
`cross_engine.py:564-597` is updated to reflect the new
condition_kind being supported.

The docstring update (delta only — the field declaration itself
stays at `cross_engine.py:597`):

```python
# cost-reduction substrate — Phase 1 Cycle 2 (2026-05-24) +
# Phase 3 (2026-05-25). Spell-local boolean-condition
# ``CostReduction`` riders (Phase 1 — EoE Gigastorm Titan +
# Lashwhip Predator) PLUS the spell-local variable-X
# ``PerDifferentlyNamedLand`` rider (Phase 3 — EoE Fungal
# Colossus). Each entry is a frozen ``(amount: int,
# condition_kind: str, condition_args: tuple)`` triple. Phases
# 1 + 3 support EXACTLY three condition_kinds:
#
#   * ``"another_spell_cast_this_turn"`` — args = ()
#   * ``"opponents_control_at_least"``   — args = ("creature", n)
#   * ``"per_differently_named_land"``   — args = ()   # Phase 3
#
# The filter guardrail
# :func:`mtg_bot.parity.trajectory._printing_is_bridge_pure_cost_
# reduction_creature` (widened in Phase 3) positively admits all
# three. No variable-multiplier on the externals side
# (Phase 4-out-of-substrate carriers); any non-empty
# ``external_cost_reductions`` is handled by the sibling
# Phase-2 field on this same CardDef.
cost_reductions: tuple[tuple[int, str, tuple], ...] = ()
```

The Phase-2 `external_cost_reductions` field declaration at
`cross_engine.py:630` is **unchanged** by Phase 3.

### 5.2 `_spec_card_to_printing_dict` registry-dict emit

The existing emit block at `cross_engine.py:13631-13639` (the
Phase-1 landing) already serializes
`card.cost_reductions` as a list-of-dicts. **No change is
required** to the emit body itself; the new triple shape
`(amount, "per_differently_named_land", ())` flows through the
same `{"amount", "condition_kind", "condition_args"}` dict
build. The comment block at `cross_engine.py:13620-13630` is
updated to mention the new wire token alongside the Phase-1
ones; no code change.

### 5.3 `_card_def_to_python_printing` reverse arm extension

**File:** `src/mtg_bot/parity/cross_engine.py`. The existing
Phase-1 reverse arm at `cross_engine.py:14411-14440` dispatches
on the wire token and re-materializes the structural
`CostReduction(amount, condition)` dataclass. Phase 3 adds a
third elif branch:

```python
cost_reductions = ()
if card.cost_reductions:
    from mtg_bot.cards.base import CostReduction
    from mtg_bot.effects.conditions import (
        AnotherSpellCastThisTurn,
        OpponentsControlAtLeast,
        PerDifferentlyNamedLand,  # Phase 3 (NEW)
    )
    from mtg_bot.effects.object_predicates import IsCreature
    rules = []
    for (amount, cond_kind, cond_args) in card.cost_reductions:
        if cond_kind == "another_spell_cast_this_turn":
            cond = AnotherSpellCastThisTurn()
        elif cond_kind == "opponents_control_at_least":
            pred_token, n = cond_args
            if pred_token != "creature":
                raise ValueError(
                    f"Phase-1 cost-reduction bridge: only the "
                    f"'creature' predicate token is supported "
                    f"on opponents_control_at_least; got "
                    f"{pred_token!r}"
                )
            cond = OpponentsControlAtLeast(IsCreature(), int(n))
        # Phase 3 (NEW).
        elif cond_kind == "per_differently_named_land":
            if cond_args != ():
                raise ValueError(
                    f"Phase-3 cost-reduction bridge: "
                    f"per_differently_named_land takes 0 args; "
                    f"got {cond_args!r}"
                )
            cond = PerDifferentlyNamedLand()
        else:
            raise ValueError(
                f"cost-reduction bridge: unsupported "
                f"condition_kind {cond_kind!r} (post-Phase-3 "
                f"adds none; future phases may extend)"
            )
        rules.append(CostReduction(amount=int(amount), condition=cond))
    cost_reductions = tuple(rules)
```

The Phase-2 externals reverse arm at
`cross_engine.py:14458-14493` is **unchanged** by Phase 3.

The Phase-1 unknown-kind hard-error message at
`cross_engine.py:14433-14438` is updated to drop the
`per_differently_named_land` mention from the "Phase 2+ adds"
list (it is now landed).

### 5.4 Cross-engine bridge admit predicate widening

**File:** `src/mtg_bot/parity/trajectory.py`. The Phase-1 +
Phase-2 admit predicate `_printing_is_bridge_pure_cost_reduction_
creature` at `trajectory.py:4975-5060` currently REJECTS Fungal
Colossus via `_cost_reduction_rule_is_phase1` at
`trajectory.py:4903-4936` (which returns False for any non-
Phase-1 condition class). Phase 3 has two options, exactly
mirroring the Phase-2 doc's §5.4 Option A / Option B framing:

**Option A (widen the existing rule helper):** rename
`_cost_reduction_rule_is_phase1` to
`_cost_reduction_rule_is_phase1_or_3` (or keep the Phase-1 name
and just append the new `isinstance` arm) and accept
`PerDifferentlyNamedLand` alongside the existing
`AnotherSpellCastThisTurn` / `OpponentsControlAtLeast(IsCreature,
int)` admit set. The outer
`_printing_is_bridge_pure_cost_reduction_creature` predicate's
spell-local admit-loop at `trajectory.py:5024-5027` (currently
`for rule in printing.cost_reductions: if not
_cost_reduction_rule_is_phase1(rule): return False`) keeps the
same call shape, just dispatching to the widened rule helper.

**Option B (new sibling rule helper):** add
`_cost_reduction_rule_is_phase3` that admits only
`PerDifferentlyNamedLand`, and chain it as an OR in the admit
loop (`for rule in printing.cost_reductions: if not
(_cost_reduction_rule_is_phase1(rule) or
_cost_reduction_rule_is_phase3(rule)): return False`).

**Recommendation: Option A.** Phase 3 adds exactly one
`Condition` variant on the same spell-local enum Phase 1
already admits from. The widened helper stays a single named
site for "is this spell-local condition rule one the substrate
ports today?" — same simplicity-of-attribution reasoning that
drove Phase 2's Option A. The Phase-1 carriers (Gigastorm +
Lashwhip) and the Phase-3 carrier (Fungal) all admit through
the SAME helper; the decline-set bench check (§7.4) gets one
predicate, one assertion.

If Option A surfaces a concrete review concern at the FLIP cycle
(e.g. the helper's name becomes misleading or a Phase-3 rider
unexpectedly co-occurs with a Phase-1 rider on some future single
card), the FLIP may fall back to Option B without changing this
doc's substrate / evaluator-extension specs.

**The widened helper (Option A — rename + extend):**

```python
def _cost_reduction_rule_is_phase1_or_3(rule) -> bool:
    """True iff ``rule`` is one of the spell-local Condition
    variants the cost-reduction substrate ports across Phases 1 + 3.

    Phase 1 + Phase 3 carry EXACTLY 3 spell-local Condition variants:

      * :class:`AnotherSpellCastThisTurn` — no payload (Gigastorm
        Titan: ``CostReduction(amount=3,
        condition=AnotherSpellCastThisTurn())``).
      * :class:`OpponentsControlAtLeast` — restricted to the
        :class:`IsCreature` filter token + an int ``n`` (Lashwhip
        Predator: ``CostReduction(amount=2,
        condition=OpponentsControlAtLeast(IsCreature(), 3))``).
      * :class:`PerDifferentlyNamedLand` — no payload (Fungal
        Colossus: ``CostReduction(amount=1,
        condition=PerDifferentlyNamedLand())``).   # Phase 3 (NEW)

    The full ``Condition``-grammar surface (And/Or/Not combinators,
    target-dependent variants, the predicate algebra beyond
    ``IsCreature``) is out of scope. Phase 2's externals-condition
    sibling is :func:`_external_cost_reduction_rule_is_phase2`,
    unchanged here.
    """
    from mtg_bot.effects.conditions import (
        AnotherSpellCastThisTurn,
        OpponentsControlAtLeast,
        PerDifferentlyNamedLand,  # Phase 3 (NEW)
    )
    from mtg_bot.effects.object_predicates import IsCreature

    c = rule.condition
    if isinstance(c, AnotherSpellCastThisTurn):
        return True
    if isinstance(c, OpponentsControlAtLeast):
        return isinstance(c.filter, IsCreature) and isinstance(c.n, int)
    # Phase 3 (NEW). No payload — accept any
    # ``PerDifferentlyNamedLand`` instance.
    if isinstance(c, PerDifferentlyNamedLand):
        return True
    return False
```

The outer `_printing_is_bridge_pure_cost_reduction_creature`
predicate at `trajectory.py:4975-5060` keeps its body intact —
only the call to `_cost_reduction_rule_is_phase1` at
`trajectory.py:5026` updates to
`_cost_reduction_rule_is_phase1_or_3`. The Phase-2
`_external_cost_reduction_rule_is_phase2` helper at
`trajectory.py:4939-4972` and the externals admit-loop at
`:5034-5037` are unchanged.

The docstring of the outer predicate
(`_printing_is_bridge_pure_cost_reduction_creature`) is updated
to drop Fungal Colossus from the "§2 teeth (must reject)" list
(it is now ADMITTED post-Phase-3), and to update the motivating
set to "Gigastorm Titan + Lashwhip Predator + Uthros Psionicist
+ Sami, Wildcat Captain + Fungal Colossus".

### 5.5 The 9 sibling guards stay rejecting (Phase-4-onwards)

The 9 sibling admit predicates in `trajectory.py` that carry the
explicit guard `if printing.cost_reductions or
printing.external_cost_reductions: return False` (per the
Phase-2 doc §5.5 line count) STAY in place. The widened
`_printing_is_bridge_pure_cost_reduction_creature` is the
SINGLE positive-allowlist gate; the negative guards on every
other predicate keep the bridge from admitting a cost-reduction-
gated card through some other code path. Phase 3 does NOT
modify these 9 sibling guards — they remain load-bearing for any
future cost-reduction phase (Phase 4 planeswalker-loyalty or
otherwise).

## 6. Filter guardrail — admit only the Phase-3 spell-local variable-X shape (Option A)

Reuse the widened helper per §5.4 above. The §2 positive-
allowlist guardrails:

- Admits `(IsCreature, Spell-local(PerDifferentlyNamedLand))` on
  top of the Phase-1 + Phase-2 admit set:
  `(IsCreature, Spell-local(AnotherSpellCastThisTurn ∪
  OpponentsControlAtLeast(Creature, int)))` ∪
  `(IsCreature, External(NthSpellThisTurn(int)) ∪
  External(PerControlled(IsArtifact ∪ IsCreature)))`.
- Rejects any future post-Phase-3 spell-local variant via the
  same `isinstance` discipline (`_cost_reduction_rule_is_phase1_or_3`
  returns False on an unknown condition class).
- Rejects any Phase-4 planeswalker (`loyalty != None` check in
  the outer predicate — unchanged from Phase 1 + Phase 2).
- Rejects any future co-gated card via the
  `_printing_is_bridge_simple_creature` exclusion set (unchanged
  exclusion set per the Phase 2 doc §5.4).

**Decline-set carriers post-Phase-3: NONE.** Fungal Colossus is
the SOLE remaining declined cost-reduction card pre-Phase-3
(per `docs/POOL_PARITY.md:437`); admitting it drives the cost-
reduction substrate single-gated row to zero. **No
cost-reduction-gated card remains declined post-Phase-3
closure.** BLOCKED 56 → 55.

## 7. Test plan

### 7.1 Substrate unit pins (Rust `#[test]` module)

1. `parse_printing` with
   `cost_reductions=[{"amount":1,
   "condition_kind":"per_differently_named_land",
   "condition_args":()}]`
   → `printing.cost_reductions == [CostReduction{amount: 1,
   condition: Condition::PerDifferentlyNamedLand}]`. Absent
   `condition_args` key → ok (treated as `()`). Non-empty
   `condition_args` → `Err` (the §2 teeth — same arg-drift
   shape Phase 1's `another_spell_cast_this_turn` enforces).
2. `parse_printing`'s unknown-kind error message no longer
   mentions `per_differently_named_land` in the "Phase 3+
   adds" hint — the hint shifts to a forward-looking phase
   marker (or drops the per-phase suggestion entirely).
3. `unique_land_names_count` standalone:
   - 0 lands on the caster's battlefield → 0.
   - 1 Forest → 1.
   - 2 Forest (two copies) → 1 (set semantics — the spec's
     "differently named" distinction).
   - 1 Forest + 1 Mountain → 2.
   - 1 Forest + 1 Mountain + 1 Plains + 1 Swamp → 4.
   - Opponent's lands are NOT counted (per-caster scope pin).
   - Non-land permanents are NOT counted (the `pr.is_land`
     gate).
4. `apply_cost_reductions_rust` with a
   `PerDifferentlyNamedLand`-bearing printing:
   - 0 lands → cost unchanged (`matches` False, `multiplier`
     0, neither term reduces).
   - 1 distinctly-named land → cost.generic -= `amount * 1`.
   - 4 distinctly-named lands → cost.generic -= `amount * 4`,
     clamped at 0 (saturating_sub).
   - Pathological 200+ distinctly-named lands → cost.generic
     reaches 0 cleanly (the `u8::MAX` clamp on
     `amt = amount * multiplier`).
5. **Stacking pin (the Phase-2 sibling shape):** a spell with
   BOTH a Phase-1 `CostReduction(amount=3,
   AnotherSpellCastThisTurn)` AND a Phase-3
   `CostReduction(amount=1, PerDifferentlyNamedLand)` on the
   SAME printing: with `spells_cast_this_turn == 1` + 3
   distinctly-named lands controlled → final cost = base - 3
   (Phase-1 boolean) - (1 * 3 = 3 Phase-3 variable) = base - 6
   generic. Pin the multi-rule reduction stack composes.
6. **Stacking pin with externals:** a spell with a Phase-3
   spell-local `PerDifferentlyNamedLand` rider AND the caster
   has Sami in play + 2 artifacts AND has cast 1 prior spell
   AND controls 3 distinctly-named lands → externals fire first
   (1 * 2 = 2 from Sami's `PerControlled(Artifact)`; nothing
   from Uthros — no Uthros in play in this scenario), then
   spell-local fires (1 * 3 = 3 from
   `PerDifferentlyNamedLand`). Pin the externals-before-
   spell-local ordering composes through Phase 3.
7. **Borrow-discipline pin (the Phase-1 inheritance):** the
   `unique_land_names_count` helper takes
   `&crate::state::GameState` and walks
   `state.players[caster_idx].battlefield` borrowed; the
   `HashSet<&str>` borrows the printing-name slices from the
   registry lookup without cloning. Verify under Miri / under
   the normal Rust borrow check that no aliasing-with-mut
   surfaces — same clone-first-then-evaluate pattern Phase 1
   established at `COST_REDUCTION_PHASE1_DESIGN.md` §3.4.

### 7.2 Cross-engine bridge round-trip pins

8. A DeckSpec with a synthetic CardDef
   `cost_reductions=((1,"per_differently_named_land",()),)`:
   - Cast on both engines with 0 lands on the caster's
     battlefield → byte-equal full-cost state.
   - Cast on both engines with 4 distinctly-named lands on the
     caster's battlefield (Forest + Mountain + Plains +
     Swamp) → byte-equal reduced-cost state (generic -= 4).
   - Cast on both engines with 4 lands of the same name (4
     Forests) → byte-equal reduced-cost state (generic -= 1;
     the set semantics applied).
   Mana pool / zones byte-equal across all three scenarios.
9. Action-set invariance pin: both engines' `legal_actions`
   emit the SAME set (and positional order) of `CastSpell`
   dicts for a `PerDifferentlyNamedLand` spell as for an
   otherwise-identical vanilla spell — Phase 3 adds NO action,
   same as Phase 1 + Phase 2 (the key structural diff vs
   warp_cost's exile-recast action).
10. **Reverse-arm hard-error pin** (the §2 teeth):
    `_card_def_to_python_printing` raises `ValueError` if a
    triple shaped
    `(1, "per_differently_named_land", ("creature",))` (non-
    empty args on a unit-shape variant) is fed to the arm.
    Mirrors the Rust parse_printing hard-error.
11. **Forward-arm wire-token stability pin:** a Python-side
    `CostReduction(amount=1,
    condition=PerDifferentlyNamedLand())` round-trips through
    `_spec_card_to_printing_dict` to the exact triple
    `(1, "per_differently_named_land", ())` (no field-order
    drift, no implicit-default leakage).

### 7.3 Real-EoE per-card probe

A `tests/test_probe_fungal_colossus_real_eoe_cost_reduction.py`
(modeled exactly on the Phase 1 probes at
`tests/test_probe_gigastorm_titan_real_eoe_cost_reduction.py` +
`tests/test_probe_lashwhip_predator_real_eoe_cost_reduction.py`
and the Phase 2 probes at
`tests/test_probe_uthros_psionicist_real_eoe_cost_reduction.py`
+ `tests/test_probe_sami_wildcat_captain_real_eoe_cost_
reduction.py` — module-scope `_PRINTINGS` idiom, 6-pin shape),
that drives the **actual Fungal Colossus printing** (resolved
via the live `OracleParserCardSource`, NOT a synthetic CardDef
— the real-EoE-signal discipline) on **both** engines:

- **Fungal Colossus probe:** assert byte-equal mirror through
  (a) cast with 0 lands controlled (Fungal cast from hand on
  turn 1 — full cost both, `{6}{G}`), (b) cast with 4
  distinctly-named lands controlled (Fungal cast from hand
  late game — `{4}` reduction applies on both, paid cost
  `{2}{G}`), (c) cast with 4 lands of the same name (4
  Forests) → `{1}` reduction (multiplier 1, the set
  semantics) applies on both, paid cost `{5}{G}`.
- The 6-pin shape: parser SoT (`_PRINTINGS["Fungal Colossus"]`
  shape matches §1.2 / §2.1), printing-surface attrs (the
  vanilla 5/5 verifications), admit classification
  (`_printing_is_bridge_pure_cost_reduction_creature` returns
  True post-Phase-3), byte-equal both seats full-cost (0
  lands), byte-equal both seats reduced (4 distinctly-named
  lands), and a decline-set negative-pin sibling (verifying
  the Phase-1 + Phase-2 carriers continue to admit).

**Bench-strategy reduction-trigger coverage note:** as with
Phase 1 / Phase 2 probes, the bench's default `attack_all`
strategy may not naturally produce the "cast Fungal late with 4
distinctly-named lands" sequence. The probe MUST use a
scripted picker (per the Phase-1 + Phase-2 precedent at the
picker-shim path) that forces each scenario so the *reduced-
cost* path is actually exercised, not just the trivial
full-cost one.

### 7.4 Decline-set bench check (no-silent-auto-grow)

12. `_printing_is_bridge_pure_cost_reduction_creature(<live Fungal
    Colossus>)` is **`True`** under the Phase-3-widened rule
    (was `False` post-Phase-2 — the inversion is the FLIP
    cycle's load-bearing pin).
13. **Subsystem-attribution pin:** exactly 5 EoE printings pass
    `_printing_is_bridge_pure_cost_reduction_creature` post-
    Phase-3 (Gigastorm Titan + Lashwhip Predator from Phase 1
    + Uthros Psionicist + Sami, Wildcat Captain from Phase 2
    + Fungal Colossus from Phase 3). The guardrail's positive
    set is exhaustive across all three phases.
14. **Subsystem-attribution drop-to-zero pin:** with the
    decline-set deck pool loaded post-Phase-3, the
    cost-reduction substrate single-gated count in the
    `POOL_PARITY.md`-style rollup is **0 cards / 0 decks**.
    The cost-reduction substrate retires from the single-gated
    list entirely; BLOCKED drops 56 → 55.
15. **No-silent-auto-grow pin** (the discipline behind
    "feedback_silent_noop_pipelines.md"): assert that an
    accidentally-post-Phase-3 condition_kind on a synthetic
    CardDef (e.g. `cost_reductions=((1,
    "and_combinator", ((...,),(...,)),),)` — an
    `AndCondition` token that doesn't exist post-Phase-3)
    raises `ValueError` from the bridge reverse arm in
    `_card_def_to_python_printing` AND raises from the Rust
    `parse_printing`'s `cost_reductions` arm. Both sides fail
    loudly on a future-phase token — no silent drop.
16. **No-other-Phase-3-carrier pin:** with the live EoE pool
    loaded, count printings whose `cost_reductions` contains
    EXACTLY a `PerDifferentlyNamedLand` rider; assert the
    count is **exactly 1** (Fungal Colossus). This is the
    Phase-3 specific instance of the no-silent-auto-grow check
    — verifying no second EoE card secretly carries the new
    shape post-flip.

## 8. Estimated cycle count

Per the Phase-1 closure (4 cycles for 2 cards) + Phase-2 closure
(4 cycles for 2 cards) precedent, scaled down for the 1-card
slice this phase admits:

| Cycle | Owner | Deliverable |
|---:|---|---|
| 1 | Rust agent | Substrate landing: `Condition::PerDifferentlyNamedLand` variant + `unique_land_names_count` helper + `apply_cost_reductions_rust` body extension (spell-local match arm + variable-multiplier reduction step) + `parse_printing` cost_reductions arm extension. **Sole Rust slice this round** (`.pyd` race rule). Fungal Colossus STAYS DECLINED post-Cycle-1 (admit predicate untouched). |
| 2 | Python/bench agent | **THE FLIP** — Bridge reverse-arm extension (`_card_def_to_python_printing`'s `per_differently_named_land` elif branch) + widened `_cost_reduction_rule_is_phase1_or_3` admit helper (Option A) + the unit + bridge pins (§7.1 + §7.2). Fungal Colossus DECLINED → ADMITTED at the bridge admit gate. |
| 3 | Bench agent | Fungal Colossus real-EoE probe (§7.3) + decline-set bench check (§7.4 pins 12-16) + drop-to-zero subsystem-attribution pin. |
| 4 (optional) | Doc agent (rolling) | `SEARCH_LIMITATIONS.md` entries (§9) + per-cycle `POOL_PARITY.md` regen + Phase-3-complete worklog. May fold into cycle 3 if the diff stays small. |

**Estimated total: ~3-4 cycles for Phase 3** — slightly under
the Phase-1 / Phase-2 4-cycle cadence because there is exactly
one carrier and one probe. Cycle 3 + Cycle 4 may merge cleanly;
the per-cycle split is optional. The substrate landing (Cycle
1) has LOWER risk than Phase 1 + Phase 2 because no new state
field is threaded, no new struct is introduced, no new
`TypeFilter` variant lands, and the externals scan is
unchanged.

**Subsequent phases (out of Phase 3 scope, scoped here for
campaign context):**

- **Phase 4 (planeswalker-loyalty-cost reductions, ~0 decks
  today):** out of substrate; only scoped if a future
  cost-reduction-gated planeswalker card surfaces. The
  Phase-2 doc §3.2 + this doc's §3.1 both restate the
  out-of-substrate reasoning.
- **Post-Phase-3 consolidation slice (optional):** unify
  `Condition` + `ExternalCondition` enums now that both have a
  variable-multiplier path (Phase 3's spell-local
  `PerDifferentlyNamedLand` + Phase 2's externals
  `PerControlled`). Per the Phase 2 doc §4.2 docstring, this
  unification is deferred to its own slice — NOT in Phase 3
  scope, and a no-functional-change refactor when it lands.

**Campaign total: ~11-12 cycles across Phase 1 / 2 / 3** to
close all 5 cards / 53,648 decks. Phase 1 closed at 4 cycles;
Phase 2 closed at 4 cycles; Phase 3 projected at 3-4 cycles;
total = 11-12 cycles. **The cost-reduction substrate retires
from the single-gated rollup at Phase 3 closure**;
campaign-end.

## 9. SEARCH_LIMITATIONS.md entries (land WITH Phase 3 cycle 1)

One entry (Phase 3 is structurally cleaner than Phase 1 +
Phase 2 because it adds NO new state field, NO new struct, NO
new `TypeFilter` variant):

1. **Cost-reduction Phase 3 supports only one new spell-local
   condition variant (`PerDifferentlyNamedLand`); the full
   spell-local + externals `Condition`-grammar surface remains
   substrate-narrow.** Location:
   `state_ops_legal.rs::apply_cost_reductions_rust`'s
   `Condition::PerDifferentlyNamedLand` match arm +
   `trajectory.py::_cost_reduction_rule_is_phase1_or_3`. Why
   OK: the filter guardrail positively rejects every
   post-Phase-3 shape on BOTH bridge sides; failure mode = a
   future probe admitting a post-Phase-3 card without the
   guardrail widening would see Python reduce and Rust
   hard-error at registry build (loud, not silent — both
   sides have §2 teeth on unknown `condition_kind`); fix-scope
   = future phase if a carrier surfaces (none in live EoE
   pool post-Phase-3); impact = +1 card / +13,165 decks, 0
   strength cost.

The Phase-2 doc §9 entry 2 (the dynamic artifact-count scan,
no `Player.artifacts_controlled_count` cache) has a Phase-3
sibling — the dynamic distinct-land-name scan, no
`Player.distinct_land_names` cache — that is folded into the
Phase-2 entry's failure-mode / fix-scope narrative rather than
duplicated as a third standalone entry. The shape is identical
(per-cast battlefield walk; bounded N; cache rejected pending a
profile that shows it mattering).

## 10. Rejected alternatives

### 10.1 Combining Phase 1 + Phase 2 + Phase 3 into one mega-Condition enum

**Rejected.** Each phase's substrate scope drove its own
minimal grammar slice on its own enum:

- Phase 1 ported 2 boolean variants on the spell-local
  `Condition` enum (`AnotherSpellCastThisTurn`,
  `OpponentsControlAtLeast`) + 1 `TypeFilter` variant
  (`Creature`).
- Phase 2 ported 2 variants on a NEW `ExternalCondition` enum
  (`NthSpellThisTurn`, `PerControlled`) + 1 new `TypeFilter`
  variant (`Artifact`).
- Phase 3 ports 1 variant on the spell-local `Condition` enum
  (`PerDifferentlyNamedLand`) — NOT on `ExternalCondition`,
  and NOT a new `TypeFilter` variant.

Folding the three into a single mega-enum at Phase 3 would
conflate three independent substrates (the spell-local +
externals split is structurally load-bearing on the Python side
— `CostReduction` vs `ExternalCostReduction` are distinct
dataclasses with distinct evaluation rules per
`cards/base.py:308-345`) and violate the round-59 sub-shape-
split discipline. The post-Phase-3 consolidation question
(should `Condition` and `ExternalCondition` merge now that both
have a variable-multiplier path?) is deferred to a separate
no-functional-change refactor slice (§3.2). That slice may land
standalone or as a Phase-4 prologue, but it is NOT a Phase-3
deliverable — Phase 3's minimum scope is exactly one
`Condition` enum variant.

### 10.2 Folding planeswalker-loyalty-cost reductions into Phase 3

**Rejected — orthogonal substrate.** Planeswalker activated
abilities can carry their own cost-reduction riders via
`ActivatedAbility.cost_reductions` (referenced at
`rust/src/cards.rs:9941`'s `ActivatedAbility` Slice-1 deferral
comment + at the live `cards.rs:9668`'s parallel comment). The
Phase-1 doc §3.4 and Phase-2 doc §3.2 both explicitly framed
loyalty-cost as "out of substrate" — they are a parallel rider
on a different cost-paying primitive (ability activation, not
spell cast), composing orthogonally with the spell-cast
cost-reduction substrate. No live cost-reduction-gated
planeswalker is in the post-Phase-2 single-gated declined set
(verified against `docs/POOL_PARITY.md:437`: 1 card, Fungal
Colossus, sub-shape D only). Folding Phase 4 into Phase 3
would conflate two substrates AND admit a Phase-4-deferred
shape behind Phase 3's `Condition` enum — both unnecessary for
the cost-reduction substrate's campaign closure. Phase 4 (if
ever scoped) is a separate substrate slice with its own design
doc; it is NOT a Phase-3 deliverable.

### 10.3 Re-routing `PerDifferentlyNamedLand` through the externals `ExternalCondition` enum

**Rejected.** Verified live (§2.3): Fungal Colossus's rider
lives on `printing.cost_reductions` (the spell-local list), not
`printing.external_cost_reductions`. The Python parser at
`cards/parser/cost_reduction.py:264-267` constructs the
`CostReduction` (spell-local) dataclass for Fungal's whole-
rider line. Re-routing the variant through
`ExternalCondition` would require the Python side to either
(a) move the live `PerDifferentlyNamedLand` constructor to a
new `ExternalCostReduction` dataclass — a non-local Python
refactor with no observable benefit, OR (b) build a Rust-only
deviation from Python's structural representation, breaking
the cross-engine bridge's 1:1 wire-token correspondence the
Phase-1 + Phase-2 substrate established. Phase 3 mirrors the
Python distinction strictly — spell-local rider → spell-local
`Condition` enum, externals rider → `ExternalCondition` enum.

### 10.4 Cache distinct-land-names on `Player`

**Rejected for Phase 3.** A cached set / counter
(`Player.distinct_land_names: HashSet<Arc<str>>` or
`Player.distinct_land_names_count: u32`) would have to update on
every land ETB / death / type-loss / control-change / phasing-
in/out / name-change — surface area we don't need for the
1-card slice this phase admits. The dynamic scan (§4.3) is
`O(battlefield-size)` to walk + `O(land-count)` HashSet
insertions, both bounded by the same small N the Phase-1
`OpponentsControlAtLeast` scan + Phase-2 `PerControlled` scan
already iterate without issue. The precedent for caching
(`artifacts_entered_under_your_control_this_turn` at
`state.rs:1077`) exists IF a future profile shows it mattering;
Phase 3 ships dynamic + the SL entry (§9) flagging the
deferred caching alongside Phase 2's identical-shape deferral.

### 10.5 Widen the existing 9 sibling `cost_reductions or
external_cost_reductions: return False` guards in Phase 3

**Rejected — the round-38-E5 anti-pattern.** Same reasoning as
the Phase-1 doc §10.4 and the Phase-2 doc §10.5: deleting the
9 sibling guards would admit Fungal Colossus into the bench
WITHOUT the guardrail differentiating the now-Phase-3-admitted
variant from a future post-Phase-3 variant, producing a silent
guaranteed divergence on any future cost-reduction shape (e.g.
a future `AndCondition` combinator carrier — Python's cast
pipeline would evaluate the combinator; Rust's parser would
hard-error or, worse, silently drop the rider). The widened
`_printing_is_bridge_pure_cost_reduction_creature` predicate
(§5.4) is the SINGLE positive-allowlist gate; the 9 negative
guards on every other predicate stay in place. The substrate
has to land before any admission is bridge-correct.

## 11. Acceptance / sign-off

Phase 3 is complete and ready to merge to `main` when:

1. All 16 pins (§7.1 — §7.4) pass on the parity gate.
2. The Fungal Colossus real-EoE probe (§7.3) passes byte-equal
   through both the full-cost and reduced-cost paths (and the
   set-semantics same-name-lands edge case) on both engines.
3. The decline-set bench check confirms +1 card admitted
   (Fungal Colossus), 0 spillover, **and the cost-reduction
   substrate single-gated count drops to ZERO** (§7.4 pin 14).
4. The single SEARCH_LIMITATIONS.md entry (§9) lands alongside
   the substrate code.
5. `.pyd` rebuilt clean; the parity gate
   (`tests/test_parity_smoke.py + test_cross_engine_etb_triggers.py
   + test_trajectory_parity.py + test_trajectory.py +
   test_measure_pool_parity.py`) stays green; 31/31 on
   `test_measure_pool_parity.py`.
6. `docs/POOL_PARITY.md`'s BLOCKED row drops 56 → 55; the
   cost-reduction substrate row is removed from the
   single-gated section (or shows `1gate=0`).

## 12. Cross-references

- `docs/COST_REDUCTION_SUBSTRATE_PHASE_1_DESIGN.md` — the
  Phase-1 campaign scoping doc (merge `4b94f844`); §3.1 / §8 /
  §10 are this doc's direct grandparent.
- `docs/COST_REDUCTION_SUBSTRATE_PHASE_2_DESIGN.md` — the
  Phase-2 campaign scoping doc (merge `f75dbf0e`); §3.1 / §4.2
  / §8 / §10 are this doc's direct parent (the
  Phase-3-deferral framing).
- `docs/COST_REDUCTION_SUBSYSTEM_REVISIT_2026-05-24.md` — the
  2026-05-24 revisit that confirmed 5/5 GENUINELY-DEFERRED and
  recommended this campaign (merge `added6db`).
- `docs/POOL_PARITY.md:437` — the live post-Phase-2
  cost-reduction substrate row: 1 card, 1 single-gated,
  13,165 decks (Fungal Colossus only).
- `src/mtg_bot/cards/base.py:308-345` — Python `CostReduction`
  (Phase 1) + `ExternalCostReduction` (Phase 2) dataclasses
  (live source of truth — Fungal Colossus's rider lives on
  `CostReduction` per the parser at
  `parser/cost_reduction.py:264-267`).
- `src/mtg_bot/cards/base.py:764-771` — `CardPrinting.
  cost_reductions` + `CardPrinting.external_cost_reductions`
  fields.
- `src/mtg_bot/effects/conditions.py:375-402` —
  `PerDifferentlyNamedLand` class definition (Phase 3's
  variable-multiplier carrier on the spell-local side; the SoT
  for the `_names` set-semantic).
- `src/mtg_bot/effects/conditions.py:405-434` —
  `PerControlled` class definition (Phase 2's variable-
  multiplier carrier on the externals side; the structural
  precedent Phase 3 mirrors on the spell-local side).
- `src/mtg_bot/cards/parser/cost_reduction.py:117-120,
  264-267` — the
  `_COST_REDUCTION_LINE_X_PER_DIFFERENTLY_NAMED_LAND` literal +
  the parser arm constructing
  `CostReduction(amount=1, condition=PerDifferentlyNamedLand())`
  for Fungal Colossus.
- `src/mtg_bot/actions.py:406-468` — Python's
  `apply_cost_reductions` + `_evaluate_cost_reduction` (the
  spell-local evaluator's reference implementation; Phase 3
  mirrors its `amount * multiplier` step on the Rust side).
- `rust/src/cards.rs:9800-9803` — Phase-1 `CostReduction`
  struct (Phase-3 inherits, no change).
- `rust/src/cards.rs:9815-9828` — Phase-1 + Phase-2
  `TypeFilter` enum (Phase-3 inherits, no change).
- `rust/src/cards.rs:9845-9862` — Phase-1 `Condition` enum
  (Phase-3 appends `PerDifferentlyNamedLand` as a third
  variant).
- `rust/src/cards.rs:9889-9931` — Phase-2 `ExternalCostReduction`
  struct + `ExternalCondition` enum (Phase-3 inherits, no
  change — sibling structures unaffected).
- `rust/src/cards.rs:10617` — Phase-1 `CardPrinting.
  cost_reductions` field (Phase-3 inherits, no change).
- `rust/src/cards.rs:10645` — Phase-2 `CardPrinting.
  external_cost_reductions` field (Phase-3 inherits, no
  change).
- `rust/src/cards.rs:15333-15486` — Phase-1 `parse_printing`
  cost_reductions arm (Phase-3 appends a third
  `condition_kind` branch for `per_differently_named_land`).
- `rust/src/state_ops_legal.rs:764-860` — Phase-1 +
  Phase-2 `apply_cost_reductions_rust` (Phase-3 extends the
  spell-local match arm with the new variant +
  `(holds, multiplier)`-pair shape).
- `rust/src/state_ops_legal.rs:897-974` — Phase-2
  `apply_external_cost_reductions_rust` (Phase-3 inherits, no
  change).
- `rust/src/state_ops_legal.rs:2414,2444,2633,2645,2733,2797,
  2917` — the 7 legal-decision call sites (Phase 3
  unchanged).
- `rust/src/state_ops_cast.rs:1167` — the cast-side call site
  (Phase 3 unchanged).
- `src/mtg_bot/parity/trajectory.py:4903-4936` — Phase-1
  `_cost_reduction_rule_is_phase1` helper (Phase 3 widens to
  `_cost_reduction_rule_is_phase1_or_3` per §5.4 Option A).
- `src/mtg_bot/parity/trajectory.py:4939-4972` — Phase-2
  `_external_cost_reduction_rule_is_phase2` helper (Phase 3
  inherits, no change).
- `src/mtg_bot/parity/trajectory.py:4975-5060` — Phase-1 +
  Phase-2 `_printing_is_bridge_pure_cost_reduction_creature`
  outer admit predicate (Phase 3 updates the call to the
  widened spell-local rule helper; outer body unchanged).
- `src/mtg_bot/parity/cross_engine.py:597` — Phase-1 + Phase-2
  CardDef `cost_reductions` field (Phase 3 docstring update
  only; field shape unchanged — the
  `(amount, condition_kind, condition_args)` triple admits
  the new wire token without field-level change).
- `src/mtg_bot/parity/cross_engine.py:630` — Phase-2 CardDef
  `external_cost_reductions` field (Phase 3 inherits, no
  change).
- `src/mtg_bot/parity/cross_engine.py:13631-13639` — Phase-1
  emit block (Phase 3 inherits, no change; comment update
  only).
- `src/mtg_bot/parity/cross_engine.py:14411-14440` — Phase-1
  reverse arm (Phase 3 appends a third elif for
  `per_differently_named_land`).
- `tests/test_probe_gigastorm_titan_real_eoe_cost_reduction.py`
  + `tests/test_probe_lashwhip_predator_real_eoe_cost_
  reduction.py` — Phase-1 probes; the 6-pin shape Phase-3
  probe mirrors.
- `tests/test_probe_uthros_psionicist_real_eoe_cost_reduction.py`
  + `tests/test_probe_sami_wildcat_captain_real_eoe_cost_
  reduction.py` — Phase-2 probes; sibling 6-pin shape Phase-3
  probe mirrors.

## 13. Regenerating the enumeration

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
  scripts/scout_r60_cost_reduction_shapes.py
```

reproduces the post-Phase-2 cost-reduction declined set / per-
sub-shape rollup / parsed spell-local/external structure exactly
(verified by the post-Phase-1 / post-Phase-2 POOL_PARITY
rollups at `6c4ee310` / `4b683928`: 1 declined, 1 single-gated,
0 multi-gated, 13,165 summed decks). The live parsed
`cost_reductions` / `external_cost_reductions` for Fungal
Colossus (§1.2 + §2.1 tables) are verifiable via
`OracleParserCardSource().get_printings()["Fungal Colossus"]`
(see §1.2 for the live-verified shape at main `4b683928`). All
§4-§6 file:line refs verified against main `4b683928`.
