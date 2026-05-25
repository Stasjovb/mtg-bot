Generated 2026-05-24 (post `cost-reduction-subsystem-decline-
revisit-p1`, merge `added6db`). **Design only — NO production /
`_SAFE_*` / Rust change in this slice; no gate run needed** (docs +
read-only scout against the live tree). This doc scopes the
cost-reduction substrate as a multi-round CAMPAIGN per the revisit's
recommendation, in the gold-standard format of
`docs/WARP_COST_PHASE1_DESIGN.md`. Every file:line below is verified
against the live tree at main `added6db`.

> **Relationship to `docs/COST_REDUCTION_PHASE1_DESIGN.md`.** That
> doc (round-63+) is a per-slice implement-ready *Phase-1 spec*
> written before the warp campaign had played out. **This doc
> supersedes it as the campaign-level entry point**: same Phase-1
> scope (sub-shape A — Gigastorm Titan + Lashwhip Predator), but
> explicitly framed as the warp-campaign-equivalent (Phase 1 / 1.5 /
> 2 / 3 sequencing, per-card cycle counts mirroring CH/MTL/AV
> precedent, and the multi-round campaign scope confirmed by the
> 2026-05-24 revisit). The per-section file:line specs (§3 of the
> existing doc) remain authoritative for the Rust-side
> implementation; this doc is the campaign-scoping entry point for
> future agents picking up cold. Where the two diverge, this doc's
> phase boundaries are canonical (the existing doc predates the
> warp 6-round empirical evidence).

# cost-reduction substrate Phase 1 — campaign scoping doc (sub-shape A: 2 cards / 24,908 17lands decks)

## 0. Executive summary

The cost-reduction subsystem at live HEAD `added6db` has **5 cards /
53,648 17lands decks single-gated, all GENUINELY-DEFERRED** (verified
by the `cost-reduction-subsystem-decline-revisit-p1` audit at
`docs/COST_REDUCTION_SUBSYSTEM_REVISIT_2026-05-24.md`). The revisit
confirmed **0 STALE-DEFERRED candidates, 0 PROBED flips**, and that
all three rescue hypotheses (adjacent Rust landing, lighter actual
gating, alternate admit predicate) are falsified. **The cost-reduction
substrate is the real bottleneck.**

This doc scopes the substrate's **Phase 1**: admit ONLY sub-shape A
(spell-local `CostReduction(amount, condition)` with boolean
conditions), narrowed to the 2 cards Gigastorm Titan + Lashwhip
Predator (24,908 17lands decks — 46% of the cost-reduction
single-gated decks, the largest self-contained slice). Phase 1
explicitly **defers** Fungal Colossus (variable-multiplier — Phase 2),
Uthros Psionicist + Sami Wildcat Captain (external cost reduction —
Phase 3).

Estimated campaign scope (per revisit §6, calibrated against the
warp_cost campaign which ran 6 rounds across Phase 1 / 1.5 / 2 / 3):
**~5 Rust cycles total for cost-reduction Phase 1** — 1 substrate
landing + 1 admit-predicate cycle + 1 per-card real-EoE probe cycle
each for Gigastorm Titan and Lashwhip Predator (mirroring the per-card
cycle counts the CH / MTL / AV multi-cycle closures executed today).

## 1. Background — why this substrate, why now

### 1.1 Revisit findings (the falsified rescue hypotheses)

`docs/COST_REDUCTION_SUBSYSTEM_REVISIT_2026-05-24.md` §1-§3 audited
the 5 single-gated cards against live HEAD and confirmed all three
rescue hypotheses are falsified:

- **(a) Has an adjacent landing shipped Rust cost-reduction support?**
  No — `grep "cost_reduction\|external_cost_reduction" rust/src/`
  returns 5 hits, **all in deferral-comment docstrings**, not in any
  production code path (`rust/src/state_ops_legal.rs:723,731,740,2260`
  + `rust/src/cards.rs:9668`). The Rust `CardPrinting` struct still
  has no `cost_reductions` field; `eff()` is still the identity
  wrapper; there is no `apply_cost_reductions` analogue anywhere.
- **(b) Is the cards' actual gating lighter than the inventory's §4
  characterization?** No — every one of the 5 cards is a vanilla
  creature shape whose ONLY non-trivial rider is the cost-reduction
  tuple (revisit §1 table). The cost-reduction rider IS the binding
  gate; no co-gate residue exists.
- **(c) Is there an already-shipped admit predicate that accepts?**
  No — all 8 live admit predicates in `trajectory.py` carry the
  explicit guard `if printing.cost_reductions or
  printing.external_cost_reductions: return False`
  (verified at 8 file:line refs in revisit §2). The guard is
  load-bearing; without it Python applies the reduction and Rust pays
  the full printed cost, producing a guaranteed mana-pool divergence
  on the bench-driven cast path.

### 1.2 Why the substrate scope is large

Per `docs/COST_REDUCTION_SUBSTRATE_PLAN.md` §3 + the revisit §6
honest-answer recommendation, the substrate requires four
components, each touching production code paths:

1. **CardDef cost-reduction representation** — the `(amount,
   condition_kind, condition_args)` tuple-of-triples codec, frozen,
   bridge-serializable. CardDef is a frozen dataclass; the encoding
   mirrors how `mana_cost_colored` and `triggered_abilities` are
   represented (tuples/dicts, not engine objects).
2. **Rust `CardPrinting.cost_reductions` field + `apply_cost_reductions_rust`
   helper + cast-pipeline hook** — the Rust analogue of Python's
   `apply_cost_reductions` (`src/mtg_bot/actions.py:406-438`). The
   single named insertion point already exists: `eff()` at
   `rust/src/state_ops_legal.rs:742` (Slice-1 mana-awareness's
   identity wrapper) — Phase 1 replaces the identity with a real
   evaluator at the cast site.
3. **Rust `Condition` enum subset port** — the largest single piece.
   Phase 1 ports EXACTLY two boolean condition variants
   (`AnotherSpellCastThisTurn` + `OpponentsControlAtLeast(IsCreature,
   n)`); later phases extend the enum to variable multipliers
   (Phase 2) and externals/per-controlled (Phase 3). The full
   `Condition` grammar would require porting the predicate algebra
   (`AndCondition` / `OrCondition` / `NotCondition` /
   `ObjectPredicate` filter algebra) — explicitly out of Phase 1
   scope.
4. **Bidirectional bridge round-trip** —
   `build_rust_state.printing_dict` emit on the Python side;
   `_card_def_to_python_printing` reconstruction;
   `_printing_to_card_def` arm with the condition-class-to-wire-token
   mapping; `_filter_deck_to_bridge_supported` admit predicate.

Component (3) is the campaign-wide §2 reason
`static_abilities` and the cost-mechanic family (warp/Ward/kicker)
are all declined: conditional/layered/stateful evaluation. Phase 1
ports it minimally (2 variants, no algebra); subsequent phases grow
the enum incrementally.

### 1.3 Calibration against warp_cost

The warp_cost campaign (`docs/WARP_COST_PHASE1_DESIGN.md` +
`docs/WARP_COST_PHASE2_DESIGN.md` + the residue / safe-trigger /
Lander phases) ran 6 rounds across Phase 1 / 1.5 / 2 / 3 to fully
close 10 cards / 15,436 decks. cost-reduction is **comparable to or
larger** in scope per the revisit's honest-answer §6:

- Warp needed NO `Condition`-grammar port — a fixed alternative
  `ManaCost` field + a deterministic end-step exile.
- Cost-reduction's `Condition`-grammar port is the dominant cost
  driver. Even the minimal Phase 1 (2 variants) lands a new
  per-player `spells_cast_this_turn` state field threaded through
  fingerprint / clone / CoW, plus the enum-variant scaffolding for
  Phases 2/3 to extend.
- Cost-reduction has a SMALLER legal/action surface than warp
  (no new action, no end-step sweep, no exile-recast) but a LARGER
  state-field + condition-grammar surface.

The campaign-total estimate is **~5-7 Rust rounds across Phase 1 /
2 / 3** (Phase 1: 1-2 rounds + 2 admit-and-probe cycles per card =
~5 cycles; Phase 2 variable multiplier: ~2 cycles; Phase 3 externals
+ remaining conditions: ~2-3 cycles), comparable to the warp
campaign's 6.

## 2. Sub-shape A scope — exactly 2 cards, the boolean-condition spell-local subset

Verified live against `OracleParserCardSource` at main `added6db`
(per revisit §1 + `COST_REDUCTION_PHASE1_DESIGN.md` §1):

| Card | live parsed `cost_reductions` | mana_cost | 17lands decks | keywords | other riders | Phase |
|---|---|---|---:|---|---|---|
| **Gigastorm Titan** | `(CostReduction(amount=3, condition=AnotherSpellCastThisTurn()),)` | `{4}{U}` | 14,844 | (none) | NONE | **1** |
| **Lashwhip Predator** | `(CostReduction(amount=2, condition=OpponentsControlAtLeast(IsCreature(), 3)),)` | `{4}{G}{G}` | 10,064 | `reach` | NONE | **1** |

**Phase-1 deck total: 24,908 17lands decks** (= 14,844 + 10,064).
The two cards together unlock 46% of the cost-reduction single-gated
deck count (24,908 / 53,648).

Both cards' Phase-1 conditions satisfy the minimal-scope criteria:

- The rider is a `CostReduction(amount, condition)` on
  `printing.cost_reductions` (verified: `cards/base.py:308-322` for
  the dataclass, `cards/base.py:764` for the printing field).
- The condition is one of EXACTLY TWO boolean conditions with the
  default `multiplier()==1` (verified:
  `effects/conditions.py:235-244` `AnotherSpellCastThisTurn`,
  `effects/conditions.py:206-228`
  `OpponentsControlAtLeast`).
- `external_cost_reductions == ()`, `kicker_cost is None`,
  `impending_cost is None`, `warp_cost is None`, no static /
  triggered / activated abilities, no `spell_effect`, no `room_halves`,
  no loyalty, no station threshold, no dynamic-P/T formula, no ward.
- `reach` (Lashwhip Predator) is in `_SAFE_KEYWORDS` per
  `trajectory.py` so it is NOT a blocker.

The ONLY blocking feature on both Phase-1 cards is the
`cost_reductions` tuple. Strip it and each card is a pure
bridge-simple creature.

## 3. Out-of-scope (deferred to Phase 2+)

The following are explicitly **NOT** in Phase 1's scope. The Phase-1
filter guardrail
(`_printing_is_bridge_pure_cost_reduction_creature`, §6) positively
rejects each so they cannot reach the Phase-1 reduced-cost path:

### 3.1 External cost reductions (Phase 3)

The `ExternalCostReduction` dataclass (`cards/base.py:325-345`) and
the `_apply_external_cost_reductions` battlefield scan
(`actions.py:471+`) are explicitly Phase 3. Carriers:

- **Uthros Psionicist** (`ExternalCostReduction(amount=2,
  condition=NthSpellThisTurn(n=2))`, 14,767 decks) — every 2nd spell
  the controller casts each turn costs {2} less while Uthros is in
  play. Largest blast radius — fires on EVERY spell cast by the
  controller while Uthros is in play, not just Uthros's own cast.
- **Sami, Wildcat Captain** (`ExternalCostReduction(amount=1,
  condition=PerControlled(IsArtifact()))`, 808 decks) — affinity-like
  variable external. Also requires the `PerControlled` variable
  multiplier.

These need a Rust battlefield-scan analogue, the `NthSpellThisTurn`
condition variant (reuses Phase-1's new `spells_cast_this_turn`
state), and the `PerControlled` variable-multiplier path (Phase 2
prerequisite).

### 3.2 Variable-X multiplier conditions (Phase 2)

`PerDifferentlyNamedLand` and `PerControlled` override
`Condition.multiplier()` to return a state-derived count
(`effects/conditions.py:376-403,405-434`). Phase 2 lands the
`amount * multiplier` math + the Rust evaluator's variable path.
Carrier:

- **Fungal Colossus** (`CostReduction(amount=1,
  condition=PerDifferentlyNamedLand())`, 13,165 decks) — costs {X}
  less where X is the count of distinctly-named lands controlled.

### 3.3 Affinity-like generic predicate algebra (Phase 2+)

`OpponentsControlAtLeast` Phase 1 hard-codes the `IsCreature`
predicate token. The generic predicate algebra
(`OpponentsControlAtLeast(HasSubtype(...), ...)`,
`ControlPermanent(IsCreature() & HasCounter(...))`, etc.) is Phase 2+
and would require porting the `ObjectPredicate` filter algebra to
Rust.

### 3.4 Planeswalker-loyalty-cost reductions (out of substrate)

Planeswalker activated abilities can carry their own cost-reduction
riders via `ActivatedAbility.cost_reductions`
(referenced in `rust/src/cards.rs:9668`'s ActivatedAbility deferral
comment). These are explicitly **out of substrate** — they are a
parallel rider on a different cost-paying primitive (ability
activation, not spell cast) and would compose orthogonally with the
spell-cast cost-reduction substrate. No live cost-reduction-gated
planeswalker is in the 5-card single-gated set.

## 4. Rust-side spec — the new struct, enum, field, and hook

### 4.1 New `CardPrinting.cost_reductions: Vec<CostReduction>` field

**File:** `rust/src/cards.rs`. Add to `CardPrinting` (struct declared
at `cards.rs:9713`, last field `pub starting_loyalty: i32` at
`cards.rs:9885`):

```rust
    /// **cost-reduction substrate Phase 1.** Spell-local boolean-
    /// condition `CostReduction` riders (Gigastorm Titan, Lashwhip
    /// Predator). Empty Vec = no reduction (back-compat default —
    /// every pre-Phase-1 registry dict omits the `cost_reductions`
    /// key, which the parser maps to `Vec::new()`, identical to the
    /// `triggered_abilities` / `subtypes` Option-parse shape). The
    /// cast pipeline (`state_ops_cast.rs::cast_creature` at
    /// `:1054`, with the existing `eff()` seam at
    /// `state_ops_legal.rs:742` extended from identity to a real
    /// evaluator) reduces the paid `ManaCost` by each rule's
    /// `amount` whose `condition` holds. Mirrors Python's
    /// `CardPrinting.cost_reductions: tuple[CostReduction, ...]`
    /// at `src/mtg_bot/cards/base.py:764`.
    pub cost_reductions: Vec<CostReduction>,
```

### 4.2 New `CostReduction` Rust struct

**File:** `rust/src/cards.rs`. Add near `ActivatedAbility`
(`cards.rs:9672`):

```rust
/// A spell-local cost-reduction rule. Mirrors Python's
/// `CostReduction` dataclass at `src/mtg_bot/cards/base.py:308`
/// (`amount: int`, `condition: Condition`). **cost-reduction
/// substrate Phase 1.** `amount` is the unit generic reduction; for
/// Phase-1 boolean conditions the multiplier is implicitly 1
/// (Python: `Condition.multiplier` default
/// `effects/conditions.py:69-75`), so the reduction is exactly
/// `amount` generic when the condition holds. Phase 2 will add a
/// variable-multiplier path (`PerDifferentlyNamedLand`); Phase 3
/// will add an `ExternalCostReduction` sibling struct + the
/// battlefield-scan path.
#[derive(Clone, Debug)]
pub struct CostReduction {
    pub amount: i32,
    pub condition: Condition,
}
```

### 4.3 New `Condition` Rust enum (Phase 1 subset)

**File:** `rust/src/cards.rs`. The Phase-1 subset of Python's
structural `Condition` grammar from `effects/conditions.py`:

```rust
/// The Phase-1 boolean-condition subset of Python's structural
/// `Condition` grammar (`src/mtg_bot/effects/conditions.py`).
/// Phase 1 ports EXACTLY two variants — the only two sub-shape A
/// uses. The full `Condition`-grammar port (variable multipliers,
/// target-dependent, predicate algebra, And/Or/Not combinators) is
/// Phase 2+. This is the reason cost-reduction is strictly larger
/// than warp (warp needed NO condition grammar — see
/// `docs/WARP_COST_PHASE1_DESIGN.md` §0).
///
/// **Naming convention:** the Rust enum names mirror Python's class
/// names ONE-TO-ONE so the cross-engine bridge wire tokens
/// (`condition_kind` strings, §5.2) round-trip without ambiguity.
/// When Phase 2 adds `PerDifferentlyNamedLand`, the new variant is
/// `Condition::PerDifferentlyNamedLand` with the same name.
#[derive(Clone, Debug)]
pub enum Condition {
    /// Python `AnotherSpellCastThisTurn`
    /// (`effects/conditions.py:235-244`): the caster has cast >=1
    /// OTHER spell this turn. Reads the new per-player
    /// `spells_cast_this_turn` counter (§4.5) which counts
    /// strictly-previous casts (incremented AFTER cost-pay,
    /// mirroring Python — `NthSpellThisTurn` docstring
    /// `effects/conditions.py:248-262`).
    AnotherSpellCastThisTurn,
    /// Python `OpponentsControlAtLeast(IsCreature(), n)`
    /// (`effects/conditions.py:206-228`): some opponent(s) of the
    /// caster control, in total across all opponents, at least `n`
    /// permanents matching the creature predicate. Phase 1 hard-codes
    /// the `IsCreature` filter token (the only predicate sub-shape A
    /// uses); the generic predicate algebra is Phase 2+.
    OpponentsControlAtLeast { type_filter: TypeFilter, count: i32 },
}

/// The Phase-1 hard-coded predicate-token subset. Phase 1 carries
/// only `Creature` (Lashwhip Predator's `IsCreature` filter); Phase 2+
/// extends this enum to `Artifact`, `Enchantment`, etc. as the
/// predicate algebra port progresses. Kept as a separate enum (not a
/// string) so the Rust parser hard-errors on an unknown token at
/// registry build, matching the "silent no-op pipeline runs are
/// pipeline bugs" discipline (§6).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TypeFilter {
    Creature,
}
```

### 4.4 The `apply_cost_reductions` hook at the cast-cost-resolution site

The cast-cost-resolution site is `cast_creature` at
`rust/src/state_ops_cast.rs:1054` (verified live).
`state_ops_legal.rs:742`'s `eff()` is the existing single named
insertion point (the "cost-reduction seam" comment) — Phase 1
extends it from identity to a real evaluator.

**The cast-side change** in `cast_creature`
(`state_ops_cast.rs:1054`): replace the `p.mana_cost.clone()` read
(currently the base-cost source) with a call to a new
`apply_cost_reductions_rust` helper that walks
`p.cost_reductions`, evaluates each `condition` against current
state, and returns a reduced `ManaCost`. The borrow discipline
matters — see `COST_REDUCTION_PHASE1_DESIGN.md` §3.4 for the
clone-first borrow-resolution pattern (clone `p.cost_reductions`
into a local `Vec` while the registry borrow is live, drop the
borrow, then evaluate without aliasing).

**The legal-side change** in `state_ops_legal.rs:742`: replace
`fn eff(cost: &crate::cards::ManaCost) -> &crate::cards::ManaCost {
cost }` with a real evaluator that takes the same state +
printing-id context the cast-side helper uses, so the
affordability probe at every CastSpell emit site sees the reduced
cost. The legal-side hook keeps Python's `_can_cast` parity
behavior on the cost-reduction admit surface.

**Helper spec** (the consolidated cost-reduction evaluator):

```rust
/// Rust analogue of Python's `actions.apply_cost_reductions`
/// (`src/mtg_bot/actions.py:406-438`) restricted to the Phase-1
/// boolean-condition subset. Returns `base` reduced by the sum of
/// matching `amount`s (generic only — `ManaCost::reduced` mirrors
/// Python's `ManaCost.reduced`, reducing the generic portion and
/// never the colored pips, `cards/base.py:299-305`). Phase 1 has
/// NO external scan (Phase 3) and NO variable multiplier (Phase 2)
/// — every Phase-1 condition contributes exactly `amount` when it
/// holds.
fn apply_cost_reductions_rust(
    rules: &[CostReduction],
    state: &GameState,
    caster_id: u8,
    base: ManaCost,
) -> ManaCost {
    let mut cost = base;
    for rule in rules {
        let holds = match &rule.condition {
            Condition::AnotherSpellCastThisTurn => {
                state.player_by_id(caster_id).spells_cast_this_turn >= 1
            }
            Condition::OpponentsControlAtLeast { type_filter, count } => {
                let n = *count;
                let mut found = 0i32;
                for obj in state.battlefield_iter() {
                    if obj.controller_id == caster_id { continue; }
                    let matches = match type_filter {
                        TypeFilter::Creature => obj_is_creature(obj, state),
                    };
                    if matches { found += 1; }
                    if found >= n { break; }
                }
                found >= n
            }
        };
        if holds {
            cost = cost.reduced(rule.amount);
        }
    }
    cost
}
```

### 4.5 New per-player `Player.spells_cast_this_turn` state

`AnotherSpellCastThisTurn` requires a per-player spell-count
counter Rust does not have today. Phase 1 adds:

- `pub spells_cast_this_turn: u32` on `Player`, default `0`.
- **MUST be threaded through fingerprint** (unlike `mulligan_count`
  which is not gameplay-relevant): two states differing only in
  spell-count produce different reductions, so the fingerprint
  must reflect the difference for parity tests to catch
  divergence.
- **Increment site:** `cast_creature`, AFTER `pay_mana_cost`
  commits the spend and BEFORE the priority/passes reset
  (`state_ops_cast.rs` post-pay, pre-tail). Mirrors Python's
  "increment AFTER cost is paid" ordering
  (`effects/conditions.py:248-262` `NthSpellThisTurn`
  docstring).
- **Reset site:** verify Python's exact reset site
  (`grep "spells_cast_this_turn = 0" src/mtg_bot/`) and match the
  Rust reset to fire at the bit-equivalent phase boundary. Do NOT
  assume warp's cleanup hook is the right one — the round-60-N1
  verified-live-signature discipline forbids analogy-based
  guesses.

### 4.6 Parse + to_pydict round-trip

**Parse** in `cards.rs::parse_printing`: add a `cost_reductions`
arm parallel to the existing `triggered_abilities` parse. The
condition arm dispatches on `condition_kind` string with a
hard-error on unknown tokens (the §2 Rust-side teeth):

```rust
let cost_reductions: Vec<CostReduction> =
    match dict.get_item("cost_reductions")? {
        Some(cr_any) => {
            let lst = cr_any.downcast::<PyList>().map_err(|_| {
                PyValueError::new_err("cost_reductions must be a list")
            })?;
            let mut out = Vec::with_capacity(lst.len());
            for item in lst.iter() {
                let d = item.downcast::<PyDict>()?;
                let amount: i32 =
                    d.get_item("amount")?.unwrap().extract()?;
                let kind: String =
                    d.get_item("condition_kind")?.unwrap().extract()?;
                let condition = match kind.as_str() {
                    "another_spell_cast_this_turn" =>
                        Condition::AnotherSpellCastThisTurn,
                    "opponents_control_at_least" => {
                        let args = d.get_item("condition_args")?.unwrap();
                        let tup = args.downcast::<PyTuple>()?;
                        let pred: String = tup.get_item(0)?.extract()?;
                        let type_filter = match pred.as_str() {
                            "creature" => TypeFilter::Creature,
                            other => return Err(PyValueError::new_err(
                                format!("Phase-1 only supports the \
                                         'creature' predicate; got {other:?}"
                            ))),
                        };
                        let count: i32 = tup.get_item(1)?.extract()?;
                        Condition::OpponentsControlAtLeast {
                            type_filter, count,
                        }
                    }
                    other => return Err(PyValueError::new_err(format!(
                        "Phase-1 cost-reduction does not support \
                         condition_kind {other:?} (Phase 2+)"))),
                };
                out.push(CostReduction { amount, condition });
            }
            out
        }
        None => Vec::new(),
    };
```

**to_pydict** (the inverse): the existing `printing_to_pydict`-style
serializer (mirror the `triggered_abilities` shape) emits the same
list-of-dicts structure for the bridge round-trip.

## 5. Python bridge spec — round-trip the new field byte-equal

### 5.1 CardDef field

**File:** `src/mtg_bot/parity/cross_engine.py`, the `CardDef`
dataclass (declared at `cross_engine.py:107`). Append after the
warp/spell-effect/aura fields, alongside other optional substrate
fields (same back-compat-default pattern as `subtypes` /
`supertypes` / `keywords`):

```python
    # cost-reduction substrate (Phase 1). Spell-local boolean-
    # condition `CostReduction` riders (EoE — Gigastorm Titan
    # {3}-less-if-cast-another-spell, Lashwhip Predator
    # {2}-less-if-opponents-control->=3-creatures). Each entry is a
    # frozen (amount: int, condition_kind: str, condition_args: tuple)
    # triple. Phase 1 supports EXACTLY two condition_kinds:
    #   * "another_spell_cast_this_turn" — args = ()
    #   * "opponents_control_at_least"    — args = ("creature", n)
    # The filter guardrail
    # `_printing_is_bridge_pure_cost_reduction_creature` positively
    # rejects every other condition kind, every variable-multiplier
    # condition (Phase 2: PerDifferentlyNamedLand), and any non-empty
    # external_cost_reductions (Phase 3) — so only these two shapes
    # ever reach this field in a Phase-1 deckspec. Empty tuple = no
    # reduction (back-compat default; every pre-Phase-1 CardDef omits
    # it). The tuple-of-triples shape (NOT a CostReduction object)
    # keeps CardDef frozen-hashable and matches the existing flat-
    # codec field convention (mirroring mana_cost_colored,
    # warp_cost_colored).
    cost_reductions: tuple[tuple[int, str, tuple], ...] = ()
```

### 5.2 `build_rust_state` registry-dict emit

**File:** `src/mtg_bot/parity/cross_engine.py`,
`build_rust_state.printing_dict`. After the existing optional-field
blocks (alongside `triggered_abilities` / `keywords` /
`supertypes`):

```python
if card.cost_reductions:
    printing_dict["cost_reductions"] = [
        {
            "amount": amount,
            "condition_kind": cond_kind,
            "condition_args": cond_args,
        }
        for (amount, cond_kind, cond_args) in card.cost_reductions
    ]
```

(The wire tokens are stable bridge-side strings, NOT Python class
names or Rust enum discriminants — a deliberate decoupling so
neither side's internal naming leaks across the bridge. Same
pattern as `triggered_abilities`' `"kind"` discriminator.)

### 5.3 `_card_def_to_python_printing` reverse arm

Reconstructs the structural `Condition` from the wire token:

```python
from mtg_bot.cards.base import CostReduction
from mtg_bot.effects.conditions import (
    AnotherSpellCastThisTurn, OpponentsControlAtLeast,
)
from mtg_bot.effects.object_predicates import IsCreature

cost_reductions: tuple[CostReduction, ...] = ()
if card.cost_reductions:
    rules = []
    for (amount, cond_kind, cond_args) in card.cost_reductions:
        if cond_kind == "another_spell_cast_this_turn":
            cond = AnotherSpellCastThisTurn()
        elif cond_kind == "opponents_control_at_least":
            pred_token, n = cond_args
            assert pred_token == "creature"  # Phase-1 invariant
            cond = OpponentsControlAtLeast(IsCreature(), n)
        else:
            raise ValueError(
                f"Phase-1 bridge: unsupported cost-reduction "
                f"condition_kind {cond_kind!r}"
            )
        rules.append(CostReduction(amount=amount, condition=cond))
    cost_reductions = tuple(rules)
```

and pass `cost_reductions=cost_reductions` into the
`CardPrinting(...)` call. The `raise` on an unknown kind is the
bridge-side §2 teeth — matches the Rust hard-error in §4.6; both
sides fail loudly rather than silently dropping a Phase-2 rider.

### 5.4 `_printing_to_card_def` arm extension (new disjunct)

**File:** `src/mtg_bot/parity/trajectory.py`. The bench-side bridge
admit predicate is the new disjunct
`_printing_is_bridge_pure_cost_reduction_creature` (§6 below); the
`_printing_to_card_def` arm sits BEFORE the `simple_creature` arm
so a cost-reduction creature routes to the cost-reduction-aware
CardDef (which carries the `cost_reductions` triples) rather than
the plain creature arm that would drop the rider. See
`COST_REDUCTION_PHASE1_DESIGN.md` §3.7 for the exact arm body
(stable, file:line-verified).

## 6. Filter guardrail — admit only the Phase-1 boolean-condition shape

**File:** `src/mtg_bot/parity/trajectory.py`. The §2 Class-1
positive-allowlist predicate, mirroring the round-60
`_printing_is_bridge_nonbasic_mana_land` /
`_printing_is_bridge_pure_warp_creature` precedents:

```python
def _cost_reduction_rule_is_phase1(rule) -> bool:
    """True iff `rule` is one of the two boolean conditions Phase 1
    ports. Any variable-multiplier (Phase 2) or non-IsCreature
    predicate (Phase 2+) — False (rejected)."""
    from mtg_bot.effects.conditions import (
        AnotherSpellCastThisTurn, OpponentsControlAtLeast,
    )
    from mtg_bot.effects.object_predicates import IsCreature
    c = rule.condition
    if isinstance(c, AnotherSpellCastThisTurn):
        return True
    if isinstance(c, OpponentsControlAtLeast):
        return isinstance(c.filter, IsCreature) and isinstance(c.n, int)
    return False


def _printing_is_bridge_pure_cost_reduction_creature(printing) -> bool:
    """True iff a CardPrinting is a PURE spell-local boolean-condition
    cost-reduction creature the Phase-1 cost-reduction substrate
    round-trips byte-equal across engines.

    Motivating set: Gigastorm Titan, Lashwhip Predator. The §2
    Class-1 guardrail: admits ONLY the boolean-condition spell-local
    profile and MUST reject Fungal Colossus (PerDifferentlyNamedLand
    — Phase 2), Uthros Psionicist + Sami (external_cost_reductions —
    Phase 3), and every multi-gated cost-reduction card.
    """
    if "Creature" not in printing.card_types:
        return False
    if printing.power is None or printing.toughness is None:
        return False
    if not printing.cost_reductions:
        return False
    if printing.external_cost_reductions:
        return False  # Uthros, Sami — Phase 3
    for rule in printing.cost_reductions:
        if not _cost_reduction_rule_is_phase1(rule):
            return False  # Fungal (PerDifferentlyNamedLand) — Phase 2
    # No OTHER blocking feature — same exclusion set as
    # _printing_is_bridge_simple_creature:
    if printing.keywords and not printing.keywords.issubset(_SAFE_KEYWORDS):
        return False
    if printing.triggered_abilities:
        for ta in printing.triggered_abilities:
            if _python_ta_to_safe_dict(ta) is None:
                return False
    if printing.activated_abilities:  return False
    if printing.static_abilities:     return False
    if printing.spell_effect is not None:  return False
    if printing.warp_cost or printing.kicker_cost or printing.impending_cost:
        return False
    if printing.room_halves:          return False
    if printing.loyalty is not None:  return False
    if printing.station_threshold:    return False
    if getattr(printing, "dynamic_pt_formula", None) is not None:
        return False
    if getattr(printing, "ward_cost", None) is not None:
        return False
    try:
        _parse_mana_cost_string(printing.mana_cost_str or "")
    except ValueError:
        return False
    return True
```

**Wire into `_filter_deck_to_bridge_supported`** (the OR-chain).
Both Phase-1 cards are bare `('Creature',)` (unlike the warp
Phase-1 pair which were Artifact Creature) — no Artifact-type-drop
caveat applies.

## 7. Test plan

### 7.1 Substrate unit pins (Rust `#[test]` module)

1. `parse_printing` with `cost_reductions=[{"amount":3,
   "condition_kind":"another_spell_cast_this_turn",
   "condition_args":()}]` → `printing.cost_reductions ==
   [CostReduction{amount:3, condition:AnotherSpellCastThisTurn}]`.
   Absent key → empty Vec. Unknown `condition_kind` → `Err` (Rust
   §2 teeth).
2. `apply_cost_reductions_rust` with
   `AnotherSpellCastThisTurn`-only rule: `spells_cast_this_turn==0`
   → cost unchanged; `==1` → generic reduced by `amount`, colored
   pips untouched.
3. `apply_cost_reductions_rust` with `OpponentsControlAtLeast{n:3,
   type_filter:Creature}`: 2 opponent creatures → unchanged; 3 →
   reduced; own creatures NOT counted.
4. `ManaCost::reduced(k)` parity pin: clamps generic at 0, never
   reduces colored pips (mirror Python `ManaCost.reduced`,
   `cards/base.py:299-305`).
5. **Ordering pin** (the load-bearing invariant): `CastSpell` of an
   `AnotherSpellCastThisTurn` creature as the caster's FIRST spell
   this turn pays FULL cost (reduction computed pre-increment); the
   permanent's controller's `spells_cast_this_turn == 1` post-cast;
   a SECOND `AnotherSpellCastThisTurn` creature cast same turn
   pays reduced cost.
6. Per-turn reset pin: advancing through the turn boundary resets
   every player's `spells_cast_this_turn` to 0 at the
   Python-matched phase.

### 7.2 Cross-engine bridge round-trip pins

7. A DeckSpec with a synthetic CardDef
   `cost_reductions=((3,"another_spell_cast_this_turn",()),)`:
   cast it as the first spell on both engines → byte-equal post-cast
   state (full cost both); cast a second copy → byte-equal (reduced
   cost both). Mana pool / zones / `spells_cast_this_turn`
   fingerprint byte-equal.
8. A synthetic CardDef
   `cost_reductions=((2,"opponents_control_at_least",("creature",3)),)`:
   with 3 opponent creatures present, cast via `step_both` →
   byte-equal reduced-cost state; with 2 → byte-equal full-cost
   state.
9. Action-set invariance pin: both engines' `legal_actions` emit
   the SAME set (and positional order) of `CastSpell` dicts for a
   cost-reduction creature as for an otherwise-identical vanilla
   creature — confirming cost-reduction adds NO action (the key
   structural diff vs warp).

### 7.3 Real-EoE per-card probes

A `tests/test_parity_smoke.py` probe (insert IMMEDIATELY ABOVE
the `# === PHASE5_PROBES_INSERT_ABOVE_THIS_LINE ===` sentinel)
that drives the **actual Gigastorm Titan / Lashwhip Predator
printing** (resolved via the live `OracleParserCardSource`, NOT a
synthetic CardDef — round-46 real-EoE-signal discipline) on
**both** engines through:

- **Gigastorm Titan probe:** assert byte-equal mirror through (a)
  cast as caster's FIRST spell that turn (full cost paid on both),
  (b) cast a cheap spell first then Gigastorm second (the {3}
  reduction applies on both). The second path is the exact case
  that diverges pre-Phase-1.
- **Lashwhip Predator probe:** assert byte-equal mirror through (a)
  cast with opponents controlling <3 creatures (full cost), (b)
  cast with opponents controlling >=3 (the {2} reduction applies).

**Bench-strategy reduction-trigger coverage note:** the bench's
`attack_all` strategy may not naturally produce the "cast cheap
spell first then Gigastorm" line. If so, the probe MUST use a
scripted picker (a `tests/parity/_picker_shims.py` helper) that
forces the cast-a-cheap-spell-then-the-titan sequence so the
*reduced-cost* path is actually exercised, not just the trivial
full-cost one. The implementing agent confirms which; the SL entry
(§9) is amended to note the bench-strategy coverage is probe-
driven, not organic.

### 7.4 Decline-set bench check

A negative-set bench check at the loader filter, parametrized over
the 3 declined cards + the Archenemy's-Charm-style 4,286-deck
decline-set proxy:

10. `_printing_is_bridge_pure_cost_reduction_creature(<live Fungal
    Colossus>)` is `False` (PerDifferentlyNamedLand is not Phase-1).
11. `(<live Uthros Psionicist>)` is `False` AND `(<live Sami,
    Wildcat Captain>)` is `False` (external_cost_reductions
    non-empty).
12. **Subsystem-attribution pin:** exactly 2 EoE printings pass
    `_printing_is_bridge_pure_cost_reduction_creature` (Gigastorm
    Titan, Lashwhip Predator) — the guardrail's positive set is
    exhaustive for Phase 1.
13. **Decline-set bench check (the Archenemy's-Charm-style 4,286-
    deck proxy):** with the decline-set deck pool loaded, confirm
    the bench's loader-side filter excludes the same set of cards
    it excludes today — i.e. Phase 1 admits +2 cards and 0
    additional decline-set spillover. This is the cost-reduction
    analogue of the round-60 non-basic-land decline-set parity
    check.

## 8. Estimated cycle count

Per the per-card multi-cycle precedent established by today's
CH / MTL / AV closures (1 substrate + 1 admit + 1 probe per card =
~3 cycles per card on top of the shared substrate landing):

| Cycle | Owner | Deliverable |
|---:|---|---|
| 1 | Rust agent | Substrate landing: CardDef field + Rust struct/enum/parse + `apply_cost_reductions_rust` + `Player.spells_cast_this_turn` (field + increment + reset + fingerprint thread) + the `eff()` extension. **Sole Rust slice this round** (`.pyd` race rule). |
| 2 | Python/bench agent | Bridge round-trip arms + `_printing_is_bridge_pure_cost_reduction_creature` admit predicate + the 9 unit + bridge pins (§7.1 + §7.2). |
| 3 | Bench agent | Gigastorm Titan real-EoE probe (§7.3) + decline-set bench check on Fungal/Uthros/Sami (§7.4 pins 10-12). |
| 4 | Bench agent | Lashwhip Predator real-EoE probe (§7.3) + 4,286-deck decline-set parity check (§7.4 pin 13). |
| 5 | Doc agent (rolling) | SEARCH_LIMITATIONS.md entries (§9) + per-cycle pool parity regen + Phase-1-complete worklog. |

**Estimated total: ~5 cycles for Phase 1**, mirroring the CH /
MTL / AV per-card cycle count for a substrate that lands 2 cards
behind a non-trivial Rust state-field addition. The substrate
landing (cycle 1) may spill to 2 if threading
`spells_cast_this_turn` through fingerprint / clone / CoW
surfaces unexpected interactions, or if Python's reset-site
verification forces a non-cleanup reset hook that doesn't yet
exist in the Rust phase machinery.

**Subsequent phases (out of Phase 1 scope, scoped here for
campaign context):**

- **Phase 2 (Fungal Colossus, ~+13,165 decks):** ~2 cycles to add
  `PerDifferentlyNamedLand` variant + `Condition.multiplier`-style
  variable-multiplier evaluator path + probe.
- **Phase 3 (Uthros + Sami, ~+15,575 decks):** ~3 cycles for the
  larger external-scan substrate (battlefield-scan analogue of
  `_apply_external_cost_reductions`) + `NthSpellThisTurn` variant +
  `PerControlled(IsArtifact())` + 2 probes + decline-set parity
  check.

**Campaign total: ~10 cycles across Phase 1 / 2 / 3** to close all
5 cards / 53,648 decks, comparable to or slightly larger than the
warp_cost campaign's 6 rounds (the size delta is exactly the
`Condition`-grammar port plus the externals-scan substrate, both
of which warp did not require).

## 9. SEARCH_LIMITATIONS.md entries (land WITH Phase 1 cycle 1)

Two entries (estimated; cost-reduction is "cleaner" than warp on
the SL surface):

1. **Cost-reduction Phase 1 supports only the two boolean
   conditions; variable-multiplier + external + the full
   `Condition` grammar deferred.** Location:
   `state_ops_cast.rs::apply_cost_reductions_rust` +
   `trajectory.py::_printing_is_bridge_pure_cost_reduction_creature`.
   Why OK: the filter guardrail positively rejects every
   non-Phase-1 shape on BOTH bridge sides; failure mode = a future
   probe admitting a Phase-2 card without the guardrail widening
   would see Python reduce and Rust hard-error at registry build
   (loud, not silent); fix-scope = Phase 2 + Phase 3; impact = +2
   cards / +24,908 decks, 0 strength cost.
2. **Rust `Player.spells_cast_this_turn` is a Phase-1 reduced
   subset of Python's spell-count tracking.** Location:
   `state.rs::Player.spells_cast_this_turn`. Shortcut: Rust adds a
   per-player counter incremented post-pay in `cast_creature` and
   reset at the Python-matched per-turn boundary, solely to drive
   `AnotherSpellCastThisTurn`; it counts only creature casts routed
   through `cast_creature` (the only cast primitive Rust has
   today). Why OK: both Phase-1 cards are creatures; the bench
   casts creatures via `cast_creature`; bit-equal with Python for
   the Phase-1 admitted set. Failure mode: a future deck mixing
   instants/sorceries that bump the count for an
   `AnotherSpellCastThisTurn` creature would undercount on Rust
   until a non-creature cast primitive exists. Fix-scope: increment
   from every Rust cast primitive once they exist. Impact: 0
   today.

## 10. Rejected alternatives

### 10.1 Port the full `Condition` grammar in Phase 1

**Rejected.** Phase 1's smallest-self-contained-slice discipline
(round-59 sub-shape-split precedent) front-loads the minimum
substrate that demonstrably ships +2 cards. The full `Condition`
grammar (And/Or/Not combinators, `ObjectPredicate` filter algebra,
target-dependent `ChosenTargets` parameter, variable multipliers,
externals battlefield scan) is **strictly larger than the entire
warp campaign** and would block Phase 1 indefinitely. Each
subsequent phase adds the minimum new grammar its cards need
(Phase 2: variable multiplier; Phase 3: externals + `NthSpellThisTurn`
+ `PerControlled`).

### 10.2 Ship `external_cost_reductions` in Phase 1

**Rejected.** Externals require a Rust battlefield-scan analogue of
`_apply_external_cost_reductions`
(`src/mtg_bot/actions.py:471+`) — a fundamentally different
evaluation shape (scan permanents OTHER than the cast spell's
source). It is a strict superset of Phase 1's spell-local
evaluator and is sequenced last because Uthros/Sami's blast radius
is broader (every spell the controller casts while the permanent
is in play, not just the gated card's own cast). Phase 3's later
sequencing reflects the §2 "smallest first" discipline.

### 10.3 Reduce planeswalker-loyalty-cost rider in Phase 1

**Rejected — out of substrate.** Planeswalker activated abilities
can carry `ActivatedAbility.cost_reductions` riders (referenced
in `rust/src/cards.rs:9668`'s deferral comment), but no live
cost-reduction-gated planeswalker is in the 5-card single-gated
set. Loyalty-cost reductions compose orthogonally with the
spell-cast cost-reduction substrate (different cost-paying
primitive) and would be a separate substrate slice if/when
admitted. Including them in Phase 1 would conflate two
independent substrates.

### 10.4 Widen the existing `_printing_is_bridge_simple_creature` filter

**Rejected — the anti-pattern (round-38-E5 / count-chasing).**
Deleting the `if printing.cost_reductions or
printing.external_cost_reductions: return False` guard at the 8
sibling sites would admit all 5 cards into the bench WITHOUT the
substrate, immediately shipping a guaranteed divergence: Python's
cast pipeline reduces the cost; Rust pays the full
`p.mana_cost` — mana-pool / floating-mana fingerprint mismatch on
the FIRST cast of the card. Worse than warp (no symmetric-bit-
equality, no targeting-conditional escape hatch — the reduction
fires on the always-driven cast pipeline). This is the §2 Class-2
"silent guaranteed divergence" the revisit confirmed at live HEAD.
**The substrate has to land before any admission is bridge-
correct.**

## 11. Acceptance / sign-off

Phase 1 is complete and ready to merge to `main` when:

1. All 13 pins (§7.1-§7.4) pass on the parity gate.
2. The Gigastorm Titan + Lashwhip Predator real-EoE probes
   (§7.3) pass byte-equal through both the full-cost and
   reduced-cost paths on both engines.
3. The decline-set bench check confirms +2 cards admitted, 0
   spillover.
4. Both SEARCH_LIMITATIONS.md entries (§9) land alongside the
   substrate code.
5. `.pyd` rebuilt clean; the parity gate
   (`tests/test_parity_smoke.py + test_cross_engine_etb_triggers.py
   + test_trajectory_parity.py + test_trajectory.py +
   test_measure_pool_parity.py`) stays green.

## 12. Cross-references

- `docs/COST_REDUCTION_SUBSYSTEM_REVISIT_2026-05-24.md` — the
  2026-05-24 revisit that confirmed 5/5 GENUINELY-DEFERRED and
  recommended this campaign (merge `added6db`).
- `docs/COST_REDUCTION_SUBSTRATE_PLAN.md` — the round-60 N2
  original scoping doc (sub-shape decomposition, decline rationale).
- `docs/COST_REDUCTION_PHASE1_DESIGN.md` — the round-63+
  per-slice implement-ready spec (§3 file:line specs remain
  authoritative for the Rust-side implementation; this doc
  supersedes its campaign-level framing).
- `docs/WARP_COST_PHASE1_DESIGN.md` — format precedent + the
  warp-campaign sequencing template this campaign mirrors.
- `docs/WARP_COST_PHASE2_DESIGN.md` — the rider-extension
  sequencing precedent (Phase 1 minimal → Phase 2 +riders).
- `docs/SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY.md` §2 — the
  cost-reduction row (5 / 5 / 53,648 / DEFERRED).
- `docs/SEARCH_LIMITATIONS.md:7316-7326` — the `eff(c) = c`
  identity-seam pin (the single named insertion point Phase 1
  extends).
- `src/mtg_bot/cards/base.py:308-345` — the Python `CostReduction`
  / `ExternalCostReduction` dataclasses (live source of truth).
- `src/mtg_bot/effects/conditions.py:47-434` — the structural
  `Condition` grammar (the full surface Phase 1 ports a 2-variant
  subset of).
- `src/mtg_bot/actions.py:406-468` — Python's
  `apply_cost_reductions` + `_evaluate_cost_reduction` (the
  Rust-side evaluator's reference implementation).
- `rust/src/state_ops_legal.rs:721-744` — the existing `eff()`
  cost-reduction seam (Phase 1's single named insertion point).
- `rust/src/state_ops_cast.rs:1054` — `cast_creature` (the
  cast-cost-resolution site).
- `rust/src/cards.rs:9672,9713,9885` — `ActivatedAbility` /
  `CardPrinting` struct declarations + last `starting_loyalty`
  field (where the new `cost_reductions` field appends).

## 13. Regenerating the enumeration

```
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
  scripts/scout_r60_cost_reduction_shapes.py
```

reproduces the 5-card single-gated set / per-sub-shape rollup /
parsed cost-reduction structure exactly (verified by both the
round-60 scout and the 2026-05-24 revisit: 5 members, 5
single-gated, 0 multi-gated, 53,648 summed). The live parsed
`cost_reductions` / `external_cost_reductions` for the 5 cards
(§2 table) are verifiable via
`OracleParserCardSource().get_printings()[<name>]`. All §4-§6
file:line refs verified against main `added6db`.
