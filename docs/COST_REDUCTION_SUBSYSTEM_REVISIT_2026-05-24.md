# Cost-reduction subsystem decline-decision revisit (2026-05-24)

Docs-only honest-stop audit confirming that the 5 single-gated
`cost_reduction` cards documented as DEFERRED in
`docs/SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY.md` §2 +
`docs/COST_REDUCTION_SUBSTRATE_PLAN.md` remain **genuinely
DEFERRED** at live HEAD `02407af5`. **Zero STALE-DEFERRED candidates
surfaced; zero PROBED flips landed in this lane.** The cost-reduction
substrate is the real bottleneck.

## 0. Why this doc exists

The morning multi-gated rescout (`02407af5` / `feature/multi-gated-
tail-tractability-rescout-2026-05-24-p1`) honest-stopped on the 61-
card BLOCKED multi-gated tail, finding 0 new 1-cycle closures, and
recommended pivoting to the **cost-reduction subsystem decline-
decision revisit** as the highest single-decision leverage on the
parity board (5 cards / ~53,648 17lands decks single-gated; per
`MULTI_GATED_TAIL_TRACTABILITY_RESCOUT_2026-05-24.md` §F + §C.1).

The hypothesis to test: has a substrate landed since the §2 decline
(round-60 N2, `COST_REDUCTION_SUBSTRATE_PLAN.md`) that *softens* the
"guaranteed cross-engine divergence" verdict — either by (a) the
Rust side shipping cost-reduction support as a side effect of some
adjacent landing (warp / dynamic-PT / static-anthem / aura / …);
(b) the cards' actual gating mechanic turning out to be lighter than
the inventory's §4 characterization; or (c) the cards being
admittable under a different already-shipped admit predicate.

**Verify-first, evidence-bound:** all three hypotheses are
**falsified** at live HEAD `02407af5`. See §1-§3 below. This is a
genuine GENUINELY-DEFERRED honest-stop, not a procedural one.

## 1. Per-card audit (live HEAD)

The 5 cards' `OracleParserCardSource` printings at live HEAD, with
**every other printing field** dumped to confirm the cost-reduction
rider is the **only** non-trivial rider on each:

| Card | Mana | P/T | Keywords | `cost_reductions` | `external_cost_reductions` | Other non-trivial riders |
|---|---|---|---|---|---|---|
| Gigastorm Titan | `{4}{U}` | (vanilla creature shape) | (none) | `(CostReduction(amount=3, cond=AnotherSpellCastThisTurn))` | `()` | **NONE** (no static / triggered / activated / spell_effect / warp / kicker / impending / station / room / ward / dynamic-PT / loyalty) |
| Uthros Psionicist | `{2}{U}` | (vanilla) | (none) | `()` | `(ExternalCostReduction(amount=2, cond=NthSpellThisTurn(n=2)))` | **NONE** |
| Fungal Colossus | `{6}{G}` | (vanilla) | (none) | `(CostReduction(amount=1, cond=PerDifferentlyNamedLand))` | `()` | **NONE** |
| Lashwhip Predator | `{4}{G}{G}` | 5/7 | `{reach}` | `(CostReduction(amount=2, cond=OpponentsControlAtLeast(IsCreature, n=3)))` | `()` | **NONE** (reach is in `_SAFE_KEYWORDS`; not a blocker) |
| Sami, Wildcat Captain | `{4}{R}{W}` | (vanilla) | (double strike + vigilance) | `()` | `(ExternalCostReduction(amount=1, cond=PerControlled(IsArtifact)))` | **NONE** (both keywords in `_SAFE_KEYWORDS`; not blockers) |

**Key finding:** every one of the 5 cards is a **vanilla creature
shape whose ONLY non-trivial rider is the cost-reduction tuple**.
Strip the `cost_reductions` / `external_cost_reductions` fields and
each card becomes a pure bridge-simple creature (Lashwhip + Sami
trivially through `_SAFE_KEYWORDS`). The inventory's §2 row
characterization is exactly right — the cost-reduction rider is
**the** binding gate, no co-gate residue, no hidden additional
substrate.

## 2. Live admit-predicate sweep (does ANY existing predicate accept?)

Ran each of the 5 printings against every live bridge-admit
predicate in `src/mtg_bot/parity/trajectory.py`:

* `_printing_is_bridge_simple_creature` (line 4398)
* `_printing_is_bridge_pure_warp_creature` (line 4530)
* `_printing_is_bridge_simple_aura` (line 7135)
* `_printing_is_bridge_simple_static_anthem_creature` (line 8004)
* `_printing_is_bridge_simple_uncounterable_creature` (line 8155)
* `_printing_is_bridge_simple_cast_restriction_enchantment` (line 8269)
* `_printing_is_bridge_simple_static_self_conditional_creature` (line 8517)
* `_printing_is_bridge_static_anthem_pt_conditional_warp_creature` (line 8708)

**Every one of the 8 predicates returns `False`** on every one of
the 5 cards. The cause is identical at every site: each predicate
carries the explicit guard

```python
if printing.cost_reductions or printing.external_cost_reductions:
    return False
```

(see `trajectory.py:4490`, `:4670`, `:7289`, `:8080`, `:8243`,
`:8353`, `:8599`, `:8829`). The guard is **load-bearing** — without
it, Python would apply the reduction on cast and Rust (which has no
`apply_cost_reductions` analogue) would pay the full printed cost,
producing a guaranteed cross-engine mana-pool divergence. The guard
is the bench's defense against `COST_REDUCTION_SUBSTRATE_PLAN.md`
§2 Class 2 "silent guaranteed divergence."

**Verdict:** no live admit predicate accepts. Hypothesis (a) and (c)
falsified.

## 3. Rust substrate sweep (has anything cost-reduction-related shipped?)

`grep "cost_reduction\|external_cost_reduction" rust/src/` at live
HEAD returns 5 hits, all in **comments documenting the deferral**,
not in any production code path:

* `rust/src/state_ops_legal.rs:723` — docstring on `eff()`: "the
  Rust analog of Python's `_effective_cost` / `apply_cost_reductions`
  … the bridge declines cost-reduction cards
  (`docs/COST_REDUCTION_PHASE1_DESIGN.md` is 'realizable-0'). So
  `eff(c) = c` (identity) for every live CastSpell axis."
* `rust/src/state_ops_legal.rs:731` — same docstring: "Rust's
  `cards.rs` has NO `cost_reductions` / `external_cost_reductions`
  fields on the live bridge-admitted cast surface."
* `rust/src/state_ops_legal.rs:740` — pin reference: "Deliberate
  live-surface simplification, recorded in `SEARCH_LIMITATIONS.md`;
  a pin asserts the live admitted set carries no `cost_reductions`
  (the §3.5.4 regression tripwire)."
* `rust/src/state_ops_legal.rs:2260` — call-site comment at the
  cost-reduction seam: "Rust's `cards.rs` carries NO
  `cost_reductions`."
* `rust/src/cards.rs:9668` — `ActivatedAbility` docstring:
  "`cost_reductions`, `room_half`, `tier_threshold`, … are deferred
  to follow-up slices that bring their gates along."

The Rust `CardPrinting` struct still has **no** `cost_reductions`
or `external_cost_reductions` field at live HEAD; `eff()` is still
the identity wrapper; there is no `apply_cost_reductions` analogue
anywhere in `rust/src/`. No cost-reduction-relevant Rust substrate
has shipped since the round-60 N2 decline.

**Verdict:** hypothesis (b) falsified.

## 4. Cross-check against `SEARCH_LIMITATIONS.md`

`docs/SEARCH_LIMITATIONS.md:7316-7326` (the "identity-seam
sub-simplifications" section) carries the canonical pin:

> **`eff(c) = c`** (the cost-reduction seam, `state_ops_legal.rs`):
> Rust's `cards.rs` has no `cost_reductions` /
> `external_cost_reductions` on the live bridge-admitted cast
> surface (the bridge declines cost-reduction cards;
> `COST_REDUCTION_PHASE1` is realizable-0), so the effective cost
> IS the printed cost. The identity wrapper is the single named
> insertion point for a future cost-reduction slice (it does not
> re-touch the gate sites). A pin would over-prune ONLY if a
> cost-reduction card became bridge-admitted (then Python reduces +
> finds payable, Rust wouldn't) — mitigated by the bridge declining
> them today + the named seam.

The pin is **current and accurate** at live HEAD. The bridge-side
guard is the load-bearing defense; the Rust-side simplification is
deliberate and recorded.

## 5. Per-card verdict table

| # | Card | Decks | Verdict |
|---|---|---:|---|
| 1 | Gigastorm Titan | 14,844 | **GENUINELY-DEFERRED** — sub-shape A spell-local `CostReduction`; no Rust field; bench-always-cast path → guaranteed cast-time divergence |
| 2 | Uthros Psionicist | 14,767 | **GENUINELY-DEFERRED** — sub-shape B `ExternalCostReduction`; no Rust field; once in play, every 2nd spell each turn diverges (broader blast radius than A) |
| 3 | Fungal Colossus | 13,165 | **GENUINELY-DEFERRED** — sub-shape D variable-X `CostReduction`; no Rust field; variable self-reduction on cast |
| 4 | Lashwhip Predator | 10,064 | **GENUINELY-DEFERRED** — sub-shape A spell-local `CostReduction`; same as Gigastorm Titan; reach not a blocker |
| 5 | Sami, Wildcat Captain | 808 | **GENUINELY-DEFERRED** — sub-shape C affinity-like `PerControlled` external; no Rust field; per-artifact variable divergence on every spell while in play; double-strike + vigilance not blockers |
| | **TOTAL** | **53,648** | **5 / 5 GENUINELY-DEFERRED; 0 STALE-DEFERRED; 0 RECLASSIFY** |

No card surfaces as a stale closure-available candidate. No card
has a gating mechanic other than the documented cost-reduction
tuple. The inventory's §2 row + §4 substrate-decline characterization
remains correct.

## 6. Recommendation: ship the cost-reduction substrate next?

**Honest answer: NO, not as the next dispatch.** Three considerations
favor continuing to keep cost-reduction DEFERRED:

* **Substrate scope is the largest cost-mechanic family in the
  roadmap.** `COST_REDUCTION_SUBSTRATE_PLAN.md` §3 enumerates four
  required components: (1) a CardDef cost-reduction representation
  (the `(amount, condition)` tuples); (2) a Rust `CardPrinting`
  field + a Rust `apply_cost_reductions` analogue invoked on the
  Rust cast pipeline + a Rust battlefield scan for externals; (3) a
  **port of the structural `Condition` grammar** to Rust
  (`AnotherSpellCastThisTurn`, `OpponentsControlAtLeast`,
  `NthSpellThisTurn(2)`, `PerControlled(IsArtifact)`,
  `PerDifferentlyNamedLand`); (4) bidirectional bridge round-trip.
  Component (3) is the largest piece — it is the campaign-wide §2
  reason `static_abilities` and the cost-mechanic family
  (warp/Ward/kicker) are all declined: conditional/layered/stateful
  evaluation.

* **53,648 decks is large but the substrate is correspondingly
  large.** The decks/cycle ratio is hard to estimate precisely
  before the slice runs, but the substrate-plan §3 estimate is
  "multi-round Rust" — comparable to or larger than the warp_cost
  campaign (which took 6 rounds across Phase 1 / 1.5 / 2 / 3 to
  fully close). The cleaner near-term wins are diffuser per-card
  effect-uncovered slices (each ~3,000 decks/cycle per the rescout's
  §4 ranking row 4) that don't require a substrate flip.

* **No silent-divergence escape hatch.** Unlike round-39 Ward (which
  was symmetric-drop bit-equal under `attack_all`) or round-59
  shockland sub-shape A (parser flattens pay-life on both sides),
  cost-reduction has **no** strategy-neutral drop path. Every
  admission ships a real divergence on a path the bench harness
  exercises. There is no incremental "admit-with-pin" route — the
  substrate has to land before any admission is bridge-correct.

**Sub-recommendation:** if the parity board's BLOCKED leverage
continues to bottom out (the rescout already flagged the multi-gated
tail at 0 new 1-cycle closures, and this lane confirms the
cost-reduction tail at 0/5 admissible), the rational next move is
to **scope a minimal cost-reduction Phase 1** — sub-shape A only
(spell-local boolean conditions: Gigastorm Titan + Lashwhip
Predator, 24,908 decks). Phase 1 would land a Rust
`CardPrinting.cost_reductions` field, a Rust `apply_cost_reductions`
for the two boolean conditions `AnotherSpellCastThisTurn` +
`OpponentsControlAtLeast(IsCreature, n=3)`, and bridge round-trip
arms — deferring the variable-multiplier conditions (Fungal /
Sami / Uthros) to Phase 2. This is the same Phase 1 / 1.5 / 2
scaffolding precedent that worked for warp_cost. But that's a
multi-round campaign, not a 1-lane dispatch — propose it explicitly,
don't try to ship it under a single re-audit lane.

## 7. Cross-references

* `docs/SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY.md` — §2 row
  (Cost-reduction substrate: 5 / 5 / 53,648 / DEFERRED unchanged);
  §5 substrates explicitly off the top-5 (decline rationale);
  §3.5.4-equivalent pin reference at trajectory.py guard sites
* `docs/COST_REDUCTION_SUBSTRATE_PLAN.md` — round-60 N2 scoping
  doc; §1 per-card sub-shape table; §2 bridge-correctness audit;
  §3 substrate component scope
* `docs/COST_REDUCTION_PHASE1_DESIGN.md` — Phase 1 design (cited
  as "realizable-0" — current realizable yield)
* `docs/MULTI_GATED_TAIL_TRACTABILITY_RESCOUT_2026-05-24.md` —
  §F single-gated DEFERRED + §C.1 pivot recommendation that
  spawned this lane
* `docs/SEARCH_LIMITATIONS.md:7316-7326` — `eff(c) = c` identity-
  seam pin; `:4132-4242` non-basic-land precedent (contrast: that
  one had a symmetric-drop bit-equal escape, cost-reduction does
  not)
* `src/mtg_bot/parity/trajectory.py:4490` (+7 sibling sites) —
  the load-bearing bench-side guard
* `rust/src/state_ops_legal.rs:721-744` — the Rust-side `eff()`
  identity wrapper + named-seam comment
* `rust/src/cards.rs:9668` — Rust `ActivatedAbility` docstring
  deferral comment

## 8. Lane outcome

* **STALE-DEFERRED candidates surfaced:** 0
* **PROBED flips landed:** 0
* **GENUINELY-DEFERRED confirmed:** 5 (all 5 cards)
* **RECLASSIFY surfaced:** 0
* **Substrate hypothesis (a/b/c):** all three falsified at live HEAD
* **Deliverable:** this docs-only audit confirmation
* **Next-dispatch recommendation:** continue diffuser per-card
  closures from the rescout's §4 row 4 (effect-uncovered Tier-C
  drain) until BLOCKED leverage truly bottoms out; only then scope
  a cost-reduction Phase 1 sub-shape-A slice as a multi-round
  campaign (not a single-lane dispatch)
