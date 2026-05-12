# Rust Effect rng-consumption audit

Audit of every `Effect::Variant` resolve arm in
`rust/src/state_ops_resolve.rs` to identify which ones consume
randomness today and which ones need to be wired to the external_rng
substrate (`rust/src/external_rng.rs::next_below`) in future
Effect-rng-threading slices.

This doc is the per-Effect checklist that those follow-up slices
consume. It is informational — no code changes here.

Companion docs:
- [`docs/CE8_PRNG_CLOSURE_PLAYBOOK.md`](CE8_PRNG_CLOSURE_PLAYBOOK.md)
  — substrate design, the 8 gameplay-level shuffle pymethods already
  wired by CE8 (`state_ops_setup.rs` p0/p1 library shuffle,
  `state_ops_library.rs::shuffle_library_with_seed` +
  `search_library_and_move_to_hand` +
  `search_library_for_first_of_type_and_shuffle`,
  `state_ops_mulligan.rs::mulligan` + `mulligan_to_n` +
  mulligan-with-bottom).
- [`docs/SEARCH_LIMITATIONS.md`](SEARCH_LIMITATIONS.md) — entries 15
  and 16 (the G19 closure on `SearchLibraryForBasicLandTapped` and
  its deferred Effect-rng follow-up).

---

## Section 1: Summary

`rust/src/cards.rs:55` `enum Effect` declares **80** variants
today. **1** resolve arm consumes randomness today (the G19 closure
on `Effect::SearchLibraryForBasicLandTapped`, currently on the
xorshift64 fallback). **1** additional resolve arm
(`Effect::SearchLibraryForCard`) has a deliberately-deferred
post-search shuffle that will become rng-consuming the moment the
CR 701.19 / 701.22 "always shuffle after a library search" rule is
honored. The remaining **78** Effect arms are deterministic (target
picks, counter manipulation, zone moves, pending-decision packaging
for controller-driven choice) and do NOT need rng access.

So the future Effect-rng-threading slice has a very small surface:
1 arm to rewire today, 1 arm that gets wired the moment its
"deferred shuffle" gap closes, plus the `apply_effect` /
`apply_effect_pub` / `resolve_top_of_stack` /
`resolve_top_of_stack_pause` / `auto_resolve_pending_decisions`
signature plumbing carrying the rng down to them.

---

## Section 2: Effects that consume randomness today

Exactly one Effect arm today consumes randomness.

| # | Variant | Resolve arm | Current rng path | What rng drives | Follow-up scope estimate |
|---|---|---|---|---|---|
| E1 | `Effect::SearchLibraryForBasicLandTapped { count }` | `rust/src/state_ops_resolve.rs:1437` (xorshift64 Fisher-Yates at lines 1504-1540) | **xorshift64 internal** (inlined, no external rng access) | Post-search library shuffle per CR 701.19 / 701.22 — Fisher-Yates over the active player's full library | **~5-10 LOC at the arm site**, plus the plumbing work (Section 4) to thread `rng: Option<&Bound<'_, PyAny>>` from `resolve_top_of_stack` into `apply_effect` |

Detail on E1, quoting the arm-head comment (`state_ops_resolve.rs:1393-1409`):

```text
**Seed source — xorshift64 fallback only (Effect-rng
threading deferred).** CE8 wired all 8 pymethod-surface
shuffle sites to consume an optional `rng: &Bound<PyAny>`
kwarg, falling through to xorshift64 when `None`.
`Effect::SearchLibraryForBasicLandTapped` resolves inside
`apply_effect`, which does NOT yet thread an external rng
through (no `rng` param on `apply_effect`,
`resolve_top_of_stack`, or any of the dozens of intervening
call sites). Closing that threading is a separate slice;
for G19 we honor the CR 701.19 "always shuffle" invariant
via the legacy xorshift64 path.
```

The shuffle loop itself (`state_ops_resolve.rs:1520-1539`):

```rust
let mut x = seed;
for i in (1..n).rev() {
    x ^= x << 13;
    x ^= x >> 7;
    x ^= x << 17;
    let n_u64 = (i + 1) as u64;
    let bound = u64::MAX - (u64::MAX % n_u64);
    let mut r = x;
    while r >= bound {
        r ^= r << 13;
        r ^= r >> 7;
        r ^= r << 17;
        x = r;
    }
    let j = (r % n_u64) as usize;
    lib.swap(i, j);
}
```

Replacement target (mirrors the CE8 wiring in
`state_ops_library.rs::shuffle_library_with_seed`): use
`fisher_yates_shuffle_optional` or call `external_rng::next_below`
inline when `rng` is `Some`, fall back to xorshift64 when `None`.

### Deferred-shuffle Effect (will become rng-consuming when closed)

| # | Variant | Resolve arm | Today | Future rng consumption |
|---|---|---|---|---|
| E2 | `Effect::SearchLibraryForCard { filter_name, max_mv, may_fail }` | `rust/src/state_ops_resolve.rs:3139` (resolve site), with the explicit deferral comment at `state_ops_resolve.rs:3231` `// No shuffle (G19 deferral).` | **No rng consumed** — no shuffle | When CR 701.19 / 701.22 compliance is closed for this arm (same shape as the G19 closure on E1), it gains a post-search Fisher-Yates over the controller's library and joins the Effect-rng threading surface |

E2 is NOT a CE8 follow-up by itself — closing it is a separate
"SearchLibraryForCard post-search shuffle" slice. But once both
closures land, both arms consume the same Effect-rng substrate.

---

## Section 3: Effects that DON'T consume randomness

The remaining 78 Effect variants are all deterministic. The
categories below cover every variant.

### Damage / life manipulation (10)

`DealDamage`, `DamageEachOpponent`, `DamageEachCreature`,
`DealDamageAnyTarget`, `DealDamageEqualToSourcePowerAnyTarget`,
`DealDamageToOpponentCreature`, `GainLife`, `LoseLife`,
`EachOpponentLosesLife`, `TargetOpponentLosesLife`.

Pure i32 arithmetic on player.life or
GameObject.damage. No rng.

### Counter manipulation (10)

`AddCounters`, `PutPlusOneCounterOnSelf`,
`PutPlusOneCounterOnEachCreatureYouControl`,
`PutPlusOneCounterOnCreatureYouControl`,
`PutPlusOneCounterOnEachOfUpToNTargetCreatures`,
`PutChargeCountersOnSelf`,
`MoveSelfCountersToTargetCreatureYouControl`,
`PumpSelfUntilEOT`, `PumpTargetCreatureUntilEOT`,
`PumpCreaturesYouControlUntilEOT` (and the
`PumpCreaturesOpponentsControlUntilEOT`,
`PumpTargetArtifactOrCreatureUntilEOT`, `SetBasePTUntilEOT`,
`GrantKeywordToTargetCreatureUntilEOT` family — `i32
saturating_add` on the `counters` field or
`temp_pt_modifiers` Vec push. No rng.

### Zone moves — top-of-zone-or-deterministic-target (24)

`Mill`, `MillTargetPlayer`, `EachOpponentMillsCards`,
`DrawCards`, `DrawCardsEqualToResolvingCombatDamage`,
`ReturnToHand`, `ReturnCreatureFromYourGraveyardToHand`,
`ReturnCreatureFromYourGraveyardToBattlefield`,
`ReturnAllCreaturesFromYourGraveyardToBattlefield`,
`PutCardFromGraveyardOnBottomOfLibrary`, `ExileTarget`,
`Sacrifice`, `DestroyTarget`, `DestroyAllCreatures`,
`DestroyTargetNonlandPermanent`, `DestroyTargetArtifact`,
`DestroyTargetLand`, `DestroyEnchantedPermanent`,
`ExileTargetCreatureUntilSourceLeaves`,
`ExileOpponentsNonlandPermanentUntilLeaves`,
`DiscardSelf`, `DiscardCard`, `EachOpponentDiscards`,
`EachOpponentSacrificesCreature`.

All zone moves pick a deterministic Vec index — `lib.remove(0)`
(top of library), `hand.remove(0)` (deterministic first-slice "the
first card"), defender's `battlefield[0]`, etc. No rng even where
Python's counterpart calls `state.rng.choice(p.hand)` (e.g. random
discard) — the Rust first slice picks `hand[0]` and documents the
divergence as a deterministic shortcut. **If/when Rust grows
"random discard" arms, those become Effect-rng consumers** (see
the Python counterpart entries P2 in CE8 playbook §6).

### Pending-decision packaging (8)

`Surveil`, `ScryN`, `MayDo`, `ChooseOneMode`, `IfYouDo`,
`LookTopNPutOneInHandRestToGraveyard`,
`LookAtTopNRevealOrCounter`, `OptionalManaCostThenEffect`,
`OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary`.

These pop top-N cards / set up a stop point and push a
`PendingDecision` onto the queue. The randomness needed to make
choices (if any) comes from the controller's decision callback /
auto-resolve strategy — not from the Effect arm itself. The arms
themselves are deterministic.

Note: `Surveil` / `ScryN` could THEORETICALLY consume rng if a
future random-strategy auto-resolve picks a random card to bottom,
but today the strategies are `"keep_all_on_top"` /
`"send_all_to_graveyard"` (no rng).

### ManifestDread family (3)

`ManifestDread`, `ManifestDreadThenAttachSelf`,
`ManifestDreadThenPutPlusOneCountersOnIt`.

Pop top 2 cards, package into `PendingDecision::ManifestDreadChoice`.
Pure top-of-library access. Controller's downstream pick (which
card to manifest face-down, which to bottom) is decision-callback-
driven, not rng-driven.

### Token creation / copy (3)

`CreateToken`, `CreateTokenCopyOfTargetCreatureYouControl`.
Deterministic — produce N tokens from a fixed printing_id, or copy
a fixed target creature. No rng.

### Tap / untap / attach / equip / mana (10)

`TapTarget`, `UntapTarget`, `TapTargetArtifactOrCreature`,
`TapAnotherTargetCreature`, `TapEnchantedPermanent`,
`UntapTargetOtherPermanent`, `AttachToTargetCreatureYouControl`,
`EquipToTargetCreatureYouControl`, `AddManaToPool`,
`AddNManaOfChosenColor`, `BecomeLandCreatureUEOT`.

Pure boolean-flag flips / mana-pool i32 adds / type-line toggles.
Target selection is deterministic-first-slice. No rng.

### Counterspell + composition (5)

`CounterTargetSpell`, `Sequence`, `ConditionalIfVoid`,
`ConditionalOnTappedCreatures`, `OptionalSacArtifactForEffect`.

Counter walks the stack deterministically; the composition arms
recurse into their inner effect(s) via `apply_effect` — they
themselves don't consume rng. (If the inner effect is
`SearchLibraryForBasicLandTapped`, the inner arm consumes rng.)

---

## Section 4: Threading proposal

The CE8 substrate (`external_rng::next_below(rng: &Bound<'_,
PyAny>, n: usize) -> PyResult<usize>`) is ready; the gap is
plumbing an `Option<&Bound<'_, PyAny>>` (or owned `Option<PyObject>`)
from the Python pymethod surface down through:

- `GameState::resolve_top_of_stack<'py>(&mut self, py: Python<'py>)`
  — `rust/src/state_ops_resolve.rs:5346`
- `GameState::resolve_top_of_stack_pause<'py>(...)` —
  `state_ops_resolve.rs:5434`
- `apply_effect(state, effect, source_obj_id)` —
  `state_ops_resolve.rs:345` (private, in-module)
- `apply_effect_pub(state, effect, source_obj_id)` —
  `state_ops_resolve.rs:337` (cross-module re-export for
  `state_ops_decisions.rs`)
- `auto_resolve_pending(state, strategy)` —
  `state_ops_decisions.rs:130`
- `GameState::auto_resolve_pending_decisions(&mut self,
  strategy: &str)` — `state_ops_decisions.rs:1735` (pymethod
  surface)

### Option A: stash the rng on `GameState` (RECOMMENDED)

Add an `rng: Option<PyObject>` field to `GameState`. The Python
caller (cross-engine smoke harness) sets it once per game via a
new pymethod (`set_external_rng(rng: &Bound<PyAny>)`) before
invoking any apply / resolve method, and clears it at end-of-game.

Inside the Effect arms that need rng, read `state.rng_ref()` which
returns `Option<&Bound<'_, PyAny>>` bound to the current `Python`
token (helper allocates a `Bound` from the stashed `PyObject` via
`as_ref(py)` — same pattern as Python-owned objects already held
elsewhere in the engine).

**Pros:**
- Zero changes to `apply_effect` / `apply_effect_pub` /
  `resolve_top_of_stack[_pause]` / `auto_resolve_pending` /
  `auto_resolve_pending_decisions` signatures. The hundred-plus
  call sites in the codebase keep working.
- Tests calling `apply_effect_pub` directly need no change.
- Setup / clear surface is one new pymethod — small, easy to
  document.

**Cons:**
- A `PyObject` field on `GameState` complicates clone semantics —
  `GameState::clone` must `clone_ref` the `Py<PyAny>` (cheap;
  refcount bump), and any deep-clone path needs the same. The
  existing `state.clone()` callers in MCTS and parity smoke would
  each need a quick audit.
- Mutability surface: writes to `state.rng` from Python aren't
  bit-equivalent across two `state.clone()` siblings — both would
  share the same `random.Random` instance and race over its
  internal Mersenne-Twister state. **For the cross-engine smoke
  use case this is fine** (one engine per game, one rng per game).
  For MCTS / search trees that fork a state, it's a sharp edge —
  set `state.rng = None` before forking, set it back on the
  selected branch.

### Option B: explicit signature parameter on every function

Add `rng: Option<&Bound<'_, PyAny>>` as a parameter to
`apply_effect`, `apply_effect_pub`, `resolve_top_of_stack[_pause]`,
`auto_resolve_pending`, `auto_resolve_pending_decisions`, plus
every test that calls these directly.

**Pros:**
- Explicit. Cannot accidentally "forget to set" the rng — the
  compiler ensures it's threaded everywhere.
- No clone-semantics surface — the rng is a borrow that lives only
  for the call.

**Cons:**
- Large signature churn: ~6 production-surface functions + every
  call site (~50-100 in tests, ~10-20 in production code). Each
  caller picks `None` or `Some(rng)`.
- The `&Bound<'_, PyAny>` lifetime tag propagates through
  `apply_effect` recursion (the `Sequence` /
  `OptionalSacArtifactForEffect` /
  `ConditionalIfVoid` / `MayDo` composition arms call
  `apply_effect(state, inner, source_obj_id)?` — they'd need to
  forward the rng too).
- Touches the test surface area called out in `SEARCH_LIMITATIONS`
  entry 16: `resolve_top_of_stack`, `resolve_top_of_stack_pause`,
  `apply_effect_pub`, `auto_resolve_pending_decisions`, plus
  every test surface.

### Option C: compromise — owned `Option<PyObject>` on `GameState`, with per-call setup/clear helper

Same as Option A but the Python harness explicitly bookends every
gameplay-shuffle-touching call with `state.set_external_rng(rng)` /
`state.clear_external_rng()`. The pymethod surface signature stays
unchanged.

**Pros:**
- Same call-site simplicity as Option A.
- Explicit setup/teardown reduces the "stale rng from a previous
  game" footgun.

**Cons:**
- More verbose at the harness call site than Option A.
- The set/clear pattern is fiddly when an Effect resolution chain
  spans multiple `apply_effect` calls (e.g. an ETB-triggered
  Effect that recursively resolves) — the rng has to stay set
  for the whole chain.

### Recommendation: Option A

The cross-engine smoke harness's natural shape is "one
`random.Random` per game, set once before play, used everywhere".
Option A models that directly. The clone-semantics surface is
small enough to audit in one pass; the existing CE8 pymethod
shuffles (setup / library / mulligan) already pattern-matched the
"optional rng, fall back to xorshift64" shape and Option A keeps
the same fallthrough convention transparent to callers that don't
care (cli / bench / production).

If MCTS clone safety surfaces a real bug, the migration to
Option C is one helper-method rename away.

---

## Section 5: Estimated slice scope per Effect

### E1 — `Effect::SearchLibraryForBasicLandTapped`

**Site:** `rust/src/state_ops_resolve.rs:1494-1540` — the inlined
xorshift64 Fisher-Yates block following the search loop.

**Change:** Replace the inlined xorshift64 step + rejection-sample
loop with a closure that consumes `state.rng_ref()` when `Some`,
falls back to xorshift64 when `None`. Mirror of the CE8 wiring in
`state_ops_library.rs::shuffle_library_with_seed`. Estimated
**~5-10 LOC at the arm site** (the swap loop already factors
cleanly; only the `next_below(n)` source changes).

**Total slice scope** including plumbing:
- Add `rng: Option<PyObject>` field to `GameState` (+1 LOC in
  struct, +1 LOC in default) and a `rng_ref(&self, py: Python<'py>)
  -> Option<Bound<'py, PyAny>>` helper (+5 LOC).
- Add `set_external_rng` / `clear_external_rng` pymethods (+15 LOC
  for the pair).
- Audit `GameState::clone` semantics — clone the `PyObject` via
  `clone_ref` (+1 LOC, possibly already free if the Clone derive
  handles it correctly).
- Rewire the E1 arm to call `state.rng_ref(py)` (need to thread
  the `py: Python` token through `apply_effect`'s signature OR
  fetch it inline via `Python::with_gil` — adds **2-5 LOC** for
  the gil-token plumbing).
- Cross-engine smoke harness wiring (Python-side) — set rng on
  state at game start (+2 LOC).

**Estimated total: 25-40 LOC** for the full slice, mostly
plumbing. The actual rng consumption swap is trivial.

### E2 — `Effect::SearchLibraryForCard` (deferred-shuffle case)

Not in scope until the "always shuffle after search" gap on this
arm closes. When it does:
- Add the same Fisher-Yates block currently at lines 1494-1540 of
  the E1 arm.
- Wire it to `state.rng_ref(py)` from day 1 (saves a follow-up).
- Estimated **+10-15 LOC at the arm site**, no extra plumbing
  beyond what E1's closure already lands.

---

## Section 6: Cross-engine smoke implication

Once Effect-rng is threaded:

The cross-engine parity smoke (`src/mtg_bot/parity/cross_engine.py`)
already passes a shared `random.Random` into both engines for
setup / mulligan / library shuffles (post-CE8). Effect-resolve
shuffles — today only G19's `SearchLibraryForBasicLandTapped` post-
search shuffle — would then produce byte-identical permutations.

### Probes that would surface this

Any cross-engine smoke deck spec that:
1. Has a card whose Effect includes
   `SearchLibraryForBasicLandTapped` (the Cultivate /
   Rampant-Growth-style "search for a basic land, put it onto the
   battlefield tapped, then shuffle" pattern), AND
2. Plays that card before drawing the rest of its library.

would, post-threading, show the `library_p0` / `library_p1` fields
match across engines after the search resolves. Today (xorshift64
fallback) those fields diverge — see SEARCH_LIMITATIONS entry 16,
"every cross-engine smoke run that exercises a basic-land tutor
will see the post-search library_p* fields diverge".

Smoke deckspec coverage: any deck whose card pool grep'd for
`SearchLibraryForBasicLandTapped` in
`rust/src/cards.rs` shows up (round-23 effect-coverage slice
landed the variant — the EoE pool exercise count is tracked in
the same slice's notes).

### Other Effects that surface this once they close

When E2 (`SearchLibraryForCard`) closes its deferred shuffle,
every tutor effect in the smoke deckspec — Diabolic Tutor,
Demonic Tutor, etc. — would also produce byte-identical post-
search libraries. That's the same E2 closure described in
Section 5.

---

## Appendix: Effect variants quick-reference

`rust/src/cards.rs:55` declares 80 Effect variants. By rng-class:

| rng class | count | variants |
|---|---|---|
| Consumes rng today | 1 | `SearchLibraryForBasicLandTapped` (E1) |
| Deferred shuffle (will consume) | 1 | `SearchLibraryForCard` (E2) |
| Deterministic — no rng | 78 | every other variant (see Section 3 categories) |

Lookup table (variant → resolve arm line in
`rust/src/state_ops_resolve.rs`):

| Variant | Line |
|---|---|
| `DealDamage` | 351 |
| `DrawCards` | 404 |
| `GainLife` | 427 |
| `ReturnToHand` | 449 |
| `Mill` | 507 |
| `MillTargetPlayer` | 555 |
| `ExileTarget` | 615 |
| `TapTarget` | 679 |
| `UntapTarget` | 730 |
| `Sacrifice` | 783 |
| `AddCounters` | 849 |
| `DiscardCard` | 903 |
| `ScryN` | 969 |
| `DestroyTarget` | 1023 |
| `DamageEachOpponent` | 1094 |
| `DamageEachCreature` | 1154 |
| `CreateToken` | 1227 |
| `AddManaToPool` | 1336 |
| **`SearchLibraryForBasicLandTapped`** | **1437 (rng — E1)** |
| `PutPlusOneCounterOnSelf` | 1585 |
| `Surveil` | 1673 |
| `CounterTargetSpell` | 1760 |
| `DiscardSelf` | 1934 |
| `ReturnCreatureFromYourGraveyardToHand` | 2014 |
| `ReturnCreatureFromYourGraveyardToBattlefield` | 2047 |
| `EachOpponentLosesLife` | 2130 |
| `LoseLife` | 2204 |
| `TargetOpponentLosesLife` | 2279 |
| `EachOpponentDiscards` | 2374 |
| `DestroyAllCreatures` | 2455 |
| `DestroyTargetNonlandPermanent` | 2512 |
| `DestroyTargetArtifact` | 2559 |
| `DestroyTargetLand` | 2607 |
| `DealDamageAnyTarget` | 2666 |
| `PumpSelfUntilEOT` | 2735 |
| `PumpTargetCreatureUntilEOT` | 2780 |
| `Sequence` | 2850 |
| `PumpCreaturesYouControlUntilEOT` | 2863 |
| `PutPlusOneCounterOnEachCreatureYouControl` | 2932 |
| `PutPlusOneCounterOnCreatureYouControl` | 3001 |
| `AddNManaOfChosenColor` | 3071 |
| **`SearchLibraryForCard`** | **3139 (deferred — E2)** |
| `PumpCreaturesOpponentsControlUntilEOT` | 3239 |
| `PutCardFromGraveyardOnBottomOfLibrary` | 3308 |
| `MoveSelfCountersToTargetCreatureYouControl` | 3340 |
| `DealDamageEqualToSourcePowerAnyTarget` | 3420 |
| `TapTargetArtifactOrCreature` | 3478 |
| `ConditionalOnTappedCreatures` | 3508 |
| `PutPlusOneCounterOnEachOfUpToNTargetCreatures` | 3565 |
| `PutChargeCountersOnSelf` | 3647 |
| `CreateTokenCopyOfTargetCreatureYouControl` | 3683 |
| `OptionalSacArtifactForEffect` | 3770 |
| `OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary` | 3857 |
| `AttachToTargetCreatureYouControl` | 3921 |
| `EquipToTargetCreatureYouControl` | 3978 |
| `DestroyEnchantedPermanent` | 4025 |
| `TapEnchantedPermanent` | 4075 |
| `ExileTargetCreatureUntilSourceLeaves` | 4110 |
| `ExileOpponentsNonlandPermanentUntilLeaves` | 4163 |
| `MayDo` | 4225 |
| `LookTopNPutOneInHandRestToGraveyard` | 4248 |
| `ChooseOneMode` | 4287 |
| `IfYouDo` | 4306 |
| `PumpTargetArtifactOrCreatureUntilEOT` | 4328 |
| `SetBasePTUntilEOT` | 4404 |
| `ManifestDread` | 4473 |
| `ManifestDreadThenAttachSelf` | 4527 |
| `ManifestDreadThenPutPlusOneCountersOnIt` | 4597 |
| `LookAtTopNRevealOrCounter` | 4648 |
| `BecomeLandCreatureUEOT` | 4695 |
| `ReturnAllCreaturesFromYourGraveyardToBattlefield` | 4731 |
| `TapAnotherTargetCreature` | 4798 |
| `UntapTargetOtherPermanent` | 4826 |
| `GrantKeywordToTargetCreatureUntilEOT` | 4865 |
| `EachOpponentSacrificesCreature` | 4913 |
| `EachOpponentMillsCards` | 4986 |
| `ConditionalIfVoid` | 5048 |
| `DealDamageToOpponentCreature` | 5085 |
| `OptionalManaCostThenEffect` | 5175 |
| `DrawCardsEqualToResolvingCombatDamage` | 5203 |
