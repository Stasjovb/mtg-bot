# G7 mid-game STATE_EQ — verify-first finding + the auto-tap-from-lands engine fix

> **Status: CLOSED (the auto-tap frontier §2-4) + S1/S4
> spell-stack-source-zone CLOSED by S5a/S5b/S5c + the §5-predicted
> combat-blocker `LEGAL_SET_EQ` CLOSED by `fec5f14` (§7) + frontier
> (a) (`ActivateAbility` apply auto-tap, the §2-4 analog) CLOSED by
> `04d67d99` (§8) + honest-stop (a new distinct library-shuffle-order
> frontier pinned in §8; frontier (b) arch5/s0 step 367
> `priority_player` STILL-OPEN, unchanged).** Lane (this §8
> addendum): `feature/fix-g7-frontier-a-activateability-affordability`
> off `main` @ `a9126b06`; the §7 addendum was
> `feature/fix-g7-combat-blocker-legalset` off `main` @ `24776ae0`;
> the original §2-6 lane was `feature/g7-midgame-stateeq` off `main` @
> `cf994e47`. This doc is the verify-first diagnosis + fix record for
> the post-S1/S4 mid-game STATE_EQ frontier the orchestrator's bake-in
> probe surfaced (arch2/s1 @ step 273; arch5/s0 @ step 322), its
> §5-predicted combat-blocker successor (§7), and §7's frontier (a)
> `ActivateAbility`-affordability successor (§8). Cross-refs:
> `docs/RUST_STACK_RESOLUTION_DESIGN.md` (the G7 owner doc),
> `docs/SEARCH_LIMITATIONS.md` G7 notes,
> `tests/test_rust_shadow_bakein.py::
> test_g7_activateability_affordability_closed_then_next_frontier_surfaced`
> (the current flipped closure pin).

## 1. The frontier (orchestrator probe)

Post-S1 (`5803aea7`) + S4 (`78e963c1`), the `rust_shadow` bake-in on
real 17lands production decks ran materially DEEPER than the original
C4 (which tripped at the first cast ~step 143). Two decks reproduced a
NEW mid-game STATE_EQ:

- `arch=2, seed=1` → STATE_EQ at step **273** (`Galactic Wayfarer`
  obj 9, `{2}{G}`)
- `arch=5, seed=0` → STATE_EQ at step **322** (`Icecave Crasher`
  obj 12)

Divergence shape: `hand_p0`, `mana_pool_p0`, `battlefield`, `stack`
all diverging.

## 2. Verify-first diagnosis — class (c), genuine engine bug

**Bisected** (instrumented `drive_shadow_game_to_terminal`): the
diverging step is a `CastSpell(card_id=9)` decision. Both engines
emit it in their legal set (LEGAL_SET_EQ passes — both account for
auto-tap headroom). After the apply:

- **Python** (`_cast_spell`): removed the spell from `p.hand`, spent
  mana, pushed a `StackItem` — the spell is on the stack.
- **Rust** (`apply_action` → `cast_creature`): a **complete silent
  no-op** — spell still in hand, mana NOT spent (`G:1` still
  floating), stack empty.

**Divergence direction CONFIRMED INVERTED from the orchestrator's
read:** Python casts the creature; Rust does NOT. (Verified against
`rust_shadow._assert_state_eq`'s `(field, py_value, rust_value)`
compare order.)

**Root cause (file:line).** The three stack-push cast primitives —
`cast_creature` / `cast_creature_warp` / `cast_spell_noncreature`
(`rust/src/state_ops_cast.rs`) — paid the cost STRICTLY from the
floating `mana_pool` via the local `pay_mana_cost`, returning
`Ok(false)` (a silent no-op) when the pool alone could not cover it.
The Rust legal emitter is **PERMISSIVE**: `auto_tap_headroom_pool`
(`state_ops_legal.rs:622`) / `can_pay_cost` (`state_ops_mana.rs:460`)
offer a `CastSpell` whenever floating pool **plus auto-tappable
lands** could pay — exactly Python's `can_pay_cost`
(`actions.py:336-403`). But Python's `_cast_spell` then ACTUALLY pays
via `auto_tap_for_cost` (`actions.py:919-986`, called at `:1662`):
consume floating pool first, then tap lands for the remainder. Rust's
apply path had **no auto-tap**. So a production-deck cast whose cost
needs land-tapping (pool alone short — here `{2}{G}` with `G:1`
floating + 2 untapped Forests) was emitted-legal then **silently
dropped** by apply. The documented Rust model is "permissive in
`legal`, strict in apply" (`state_ops_legal.rs:614-619`) — correct
for `ActivateAbility` (the random driver taps lands via separate
`ActivateAbility` decisions there) but **wrong for `CastSpell`**,
where Python's `_cast_spell` auto-taps atomically (there is no
separate decision).

**Reproduces under `cross_engine.step_both`** (the 4-file CE5-bridged
path) **identically** — `step_both` also calls `rust_state.apply_
action(cast_spell)` with no pre-tap, and Rust silently no-ops while
Python casts (CE5 then drains Python's stack, leaving the
hand/mana/battlefield/stack divergence). So this is a **genuine Rust
engine bug, NOT a `rust_shadow` driver / lockstep bug** (it is not
class a/b). The 4-file core gate stays green only because its
scenarios pre-populate the Rust pool / use pool-payable casts.

## 3. The fix (engine — new-code-is-right)

`state_ops_cast.rs` grows a free fn `auto_tap_pay_for_cost(state,
idx, cost)` that **byte-mirrors Python `auto_tap_for_cost`**:

1. Each colored requirement, in Python's `ManaCost.colored`
   iteration order (alphabetical by symbol — **B, G, R, U, W**;
   `cards.parse_mana_cost` sorts the pairs), is paid from the
   matching floating-pool slot FIRST, then by tapping untapped
   controller lands that produce that color (battlefield order,
   `[:need]`).
2. Generic (`cost.generic`) is paid from the remaining floating
   pool (deterministic `C→W→U→B→R→G` drain), then by tapping the
   remaining untapped lands `[:generic_need]`.
3. Each tapped land sets `tapped = true` and fires
   `Event::BecomesTapped` via the SAME post-borrow inline dispatch
   `tap_for_mana` uses (`state_ops_mana.rs:369-393`) — Python routes
   every tapped land through `turn.tap_permanent` which fires
   `Event.BECOMES_TAPPED` (`actions.py:981-985`).

Plan-then-commit: the helper plans the full payment before mutating;
an over-permissive emit (genuinely unpayable) degrades to the same
honest `Ok(false)` no-mutation bail the old pool-only `pay_mana_cost`
produced (NOT a partial spend — `feedback_no_fallback_hybrids`).
**Lands-only** (Python's `auto_tap_for_cost` AND `can_pay_cost` both
source from `_untapped_lands`, lands only; the Rust legal-side
`auto_tap_headroom_pool` is broader — also counting non-sick mana
creatures — which is a DISTINCT C1 axis,
`RUST_LEGAL_DECISIONS_MANA_AWARENESS_DESIGN.md`, out of scope and not
exercised by these repros). All three cast pay sites route through
the helper. The `ActivateAbility` pool-only `pay_mana_cost_pub` path
is intentionally unchanged (separate axis; the random driver taps
lands via separate `ActivateAbility` decisions there).

**Files touched:** `rust/src/state_ops_cast.rs` ONLY (+ the
`tests/test_rust_shadow_bakein.py` pin + this doc + the SL note).
Per CFI-1 a `state_ops_*.rs` touch does NOT fire the `cards.rs`
residue cadence. **A `.pyd` rebuild on `main` is owed (orchestrator's
— this lane is HARD-STOPped after merge).**

## 4. Result — frontier CLOSED, byte-equal land payment

At the trip step, with the fix, the cast now **succeeds
byte-perfectly**:

- The auto-tapped **land set is IDENTICAL** to Python's
  (`{26,59,23}` Forests for arch2/s1).
- `mana_pool_p0`, `battlefield`, `stack` all now MATCH.
- The post-cast divergence collapses from **4 fields** (hand + mana +
  battlefield + stack) to **1 field** (`hand_p0`).

## 5. The next distinct divergence (honest-stop — S5-region)

With the cast succeeding, the bake-in now surfaces the **S1/S4
spell-stack-source-zone divergence** — `hand_p0` ALONE:

- **Rust** keeps the cast spell's GameObject physically in the
  `hand` Vec with `zone=ZONE_HAND` while it is on the stack (so
  `take_source` / `find_source_printing_id` find it at resolve —
  `state_ops_resolve.rs:205-246`; this is the documented S1 design,
  `SEARCH_LIMITATIONS.md` G7-S1 note: *"card stays in hand, NO
  battlefield move"*).
- **Python**'s `_cast_spell` removes the card from `p.hand` and sets
  `card.zone=Zone.STACK` (`actions.py:1403`/`:1751`).

So `hand_p0` diverges (Rust's hand carries the stack-resident source
Python removed). This was **MASKED in the 4-file gate by CE5**
(`step_both` drains the stack after every `cast_spell` BEFORE the
compare, so the spell has resolved off-hand by compare time) and was
previously **unreachable in `rust_shadow`** because the no-auto-tap
bug failed the cast first.

**Diagnostic** (monkeypatched `_assert_state_eq` to ignore ONLY the
characterized `hand_p0` source-zone entry — characterization only,
NOT a shipped change): with the source-zone divergence hypothetically
resolved, arch2/s1 runs **273 → 281** and arch5/s0 runs **322 →
344**, then hits **LEGAL_SET_EQ** divergences (a C1-class legal-set
asymmetry / a combat-blocker emission) — clearly **S3/S5/C1-region**,
definitively out of this lane.

**Why honest-stop (not fixed here).** Re-homing the spell-stack
source zone requires touching `take_source` /
`find_source_printing_id` / `move_source_post_resolve` AND the
`hand_snapshot` surface — which is consumed by `rust_zone_view.py`
(the **codec slot source**), `rust_determinize.py`, `parity_smoke.py`
(the **4-file gate's field view**), and the legal emitter reads
`players[idx].hand.iter()` directly (3 sites) to emit `CastSpell`. A
high-blast-radius S1/S4 redesign that risks the 1532 baseline —
explicitly the S5-region work the brief scoped OUT ("Do NOT do
S5/S6/S7/S4b"). A precise honest-stop with the next divergence
pinned is the correct, disciplined outcome (S2/B1/S3/C4-G7
precedent); forcing the redesign here would be exactly the fragile
over-reach the brief warns against.

## 6. Follow-up (S5 / next slice owner)

The next owed slice for the non-warp-creature-deck frontier is the
**S1/S4 spell-stack-source-zone reconciliation**: make Rust remove
the cast spell from `hand` and place it stack-resident (re-home
`take_source` / `find_source_printing_id` / `move_source_post_
resolve` to a stack-source zone, and the `hand_snapshot` / codec-slot
/ legal-emit / determinizer surface accordingly), byte-mirroring
Python `card.zone = Zone.STACK` + `p.hand.remove(card)`
(`actions.py:1403`/`:1751`). Then the next frontier is the
LEGAL_SET_EQ axes the §5 diagnostic surfaced (C1/S3-region). This is
the S5-region successor; the G7 owner doc
(`RUST_STACK_RESOLUTION_DESIGN.md`) S5 section is the home for it.

> **SCOPED (the S5-region successor design now exists).** The
> spell-stack-source-zone re-homing is fully verify-first scoped in
> **`docs/RUST_SPELL_STACK_SOURCE_ZONE_DESIGN.md`**: every surface
> mapped with file:line, the decision (B — ONE irreducibly-atomic
> Rust core lane S5a, Option β stack-object store, + thin verify
> slices S5b/S5c), the CE5-must-hold-without-it analysis (S5a is the
> hard S7 prerequisite), the determinizer/codec-slot/v1-v2 implications
> (all fixed for free by the one hand-membership correction;
> v-chain-agnostic), and the baseline-rebase protocol S5a must ship
> with. That doc is the single owner for the next implementation lane.

## 7. The §5-predicted combat-blocker LEGAL_SET_EQ — CLOSED (todo `fec5f14`)

> **Status: CLOSED + honest-stop (two new distinct per-repro
> frontiers pinned).** Lane: `feature/fix-g7-combat-blocker-legalset`
> off `main` @ `24776ae0`. This closes the EXACT next divergence §5
> predicted ("then hits LEGAL_SET_EQ ... a combat-blocker emission ...
> clearly S3/S5/C1-region").

After S5a closed the `hand_p0` axis the bake-in ran arch2/s1
273→**312**, arch5/s0 322→**344** then tripped `LEGAL_SET_EQ`:
`rust\py=[('blocker', N, None)] py\rust=[]` (arch2/s1 N=9, arch5/s0
N=12 — Rust over-emits).

**Verify-first root cause (class (c), Rust legal-emission gap;
file:line both sides).** Drove both exact repros through the
role-swapped bake-in and inspected the divergent declare-blockers
decision. At the trip step: `step=DECLARE_BLOCKERS`, priority on the
off-active defender, empty stack, **`battlefield attacking ids=[]`**
(ZERO attackers), defender `eligible_blockers=[9]` / `[12]`,
`_combat_phase=None`. Python's `MtgGameStateAdapter.
_enter_declare_blockers` (`src/mtg_bot/search/engine_adapter.py:
1322-1329`) computes `attackers = [o for o in battlefield if
o.attacking]` and, EMPTY, takes `if not attackers:
self._enter_priority_for_current_step(); return` — it NEVER sets
`_combat_phase = _COMBAT_BLOCKERS`, so the rust_shadow combat-window
reference (`src/mtg_bot/search/rust_shadow.py:281-286` = the Python
adapter's `legal_decisions()`) emits NO `BlockerDecision`. Rust's
blocker-decision emitter (`rust/src/state_ops_legal.rs:1336-1339`)
gated ONLY on phase/priority/empty-stack + an eligible (untapped)
defender creature — it had **no no-attackers gate**, so it still
emitted `('blocker', head, None)`. This is the brief's
"dead-or-removed-attacker / no-legal-block gate Python enforces and
Rust's emitter omits".

**The fix (new-code-is-right toward the Python SoT).** Added the
byte-mirror no-attackers gate `&& !self.attackers.is_empty()` to the
Rust blocker-emission gate. Rust's canonical "is attacking" predicate
is `state.attackers` membership — documented by the `FocusFireEffect`
arm at `state_ops_legal.rs:789-790` (*"A creature is attacking iff
its id is in `state.attackers`"*); the byte-equal analog of Python's
`o.attacking`. **`rust/src/state_ops_legal.rs` ONLY** (+ the bake-in
pin flip + the SL note + the SOT_FLIP §4 row + this §7). 4-file core
gate **1536 UNMOVED**; `tests_rust` zero-newly-failing vs `24776ae0`
(30 ≡ 30, byte-identical set); `check_audit_coverage_staleness.py`
exit 0; isolation self-check PASSED (shared canonical `.pyd`
untouched). A `.pyd` rebuild on `main` is owed (orchestrator's).

**The pin flip (surfaced→closure-flip discipline).**
`test_g7_s5a_spellstack_zone_closed_then_blocker_legalset_surfaced` →
`test_g7_combat_blocker_legalset_closed_then_next_frontier_surfaced`:
asserts (1) the combat-blocker `LEGAL_SET_EQ` no longer fires at
312/344 (each run proceeds PAST the old boundary) and (2) the new
per-repro frontier surfaces LOUDLY at its freshly-characterized
boundary. Negative controls intact.

**The next distinct divergences (honest-stop — per-repro, surfaced,
NOT introduced; the fix only NARROWS Rust over-emission).**

- **arch2/s1 → step 318:** a RAW `ValueError` (NOT a
  `ShadowDivergenceError` tripwire — rust_shadow calls
  `self._rust.apply` raw BEFORE the NO_RAISE wrapper, so a Rust-side
  raise is not converted). Rust's `legal_decisions` offers
  `ActivateAbility(source_id=121, ability_index=0)` but Rust's own
  `apply_action` rejects it: *"source 121 cost is unaffordable from
  controller's mana pool (generic=2)"*. A **Rust-internal
  legal-emit-vs-apply self-inconsistency** on activated-ability
  mana-affordability. **→ CLOSED in §8 (frontier (a)). Verify-first
  INVERTED the "legal-emit lacks the gate; apply correctly rejects"
  read: the legal-emit gate already matches Python (pool + auto-tap
  headroom) and Python apply auto-taps and SUCCEEDS — the real bug is
  the §2-4 analog (Rust `ActivateAbility` apply was pool-only, no
  auto-tap). Fixed by routing apply through the §2-4
  `auto_tap_pay_for_cost` helper.**

- **arch5/s0 → step 367:** a `STATE_EQ` tripwire on
  `('priority_player', 1, 0)` (Python=1, Rust=0) on a
  `PassPriority()` at a DECLARE_ATTACKERS step — a distinct
  priority-player divergence (G5-family priority-port region, a
  deeper production-deck manifestation than the synthetic-deck G5
  the closure-flip earlier addressed).

Both are DISTINCT, pre-existing axes, pinned LOUD by the flipped
closure pin and filed as the next G7 follow-up (todo
`fec5f14`-successor / SOT_FLIP §4). NOT force-fixed in this lane
(`feedback_no_fallback_hybrids` honest-stop) — landing the sound
combat-blocker fix and pinning the unmasked frontiers precisely is
the correct disciplined outcome (the G4/G5/G6/S5a precedent).

## 8. Frontier (a) — `ActivateAbility` apply auto-tap — CLOSED (todo `04d67d99`)

> **Status: CLOSED + honest-stop (a new distinct library-shuffle-order
> frontier pinned).** Lane: `feature/fix-g7-frontier-a-
> activateability-affordability` off `main` @ `a9126b06`. This closes
> §7's frontier (a) (the arch2/s1 step-318 RAW `ValueError`). Frontier
> (b) (arch5/s0 step 367 `('priority_player',1,0)`) is UNCHANGED — a
> distinct STILL-OPEN follow-up, NOT touched here.

**Verify-first INVERTED the brief's hypothesis.** The brief framed (a)
as "the `ActivateAbility` legal-emit site lacks the affordability gate
and `apply_action` correctly refuses". Driving the exact arch2/s1
seed-1 repro to step 318 and inspecting BOTH engines:

- The offending decision is `ActivateAbility(source_id=121,
  ability_index=0)` — a **Lander** token (`Artifact`, `is_land=False`),
  ability 0 = `{2}`, sacrifice-self, search-a-basic-land (`tap_self=
  False`).
- Priority player is p1; pool p1 = `{U:1}`; p1's untapped non-sick
  controller battlefield has 2 Forests (67, 103) + a summoning-sick
  Forest (2). So pool + auto-tap headroom = `{U:1, G:2}` ⊇ `{2}`.
- **Rust's legal-emit gate already matches Python.** `state_ops_legal.
  rs:2105` uses `pool_can_cover(&auto_tap_headroom_pool(self, idx),
  &ability.cost.mana)` = the `can_pay_cost` shape
  (`state_ops_mana.rs:460`), byte-equal to Python's `legal.py:653`
  activated-ability predicate (`can_pay_cost(state, player_id,
  effective_mana, ...)` — pool + auto-tappable lands). Python's
  `legal_actions(state, 1)` ALSO offers `ActivateAbility(121,0)` here
  → `LEGAL_SET_EQ` passes (the pin reaches step 318 cleanly).
- **The real bug is the §2-4 analog for `ActivateAbility`.** Rust's
  `apply_action` `ActivateAbility` arm (`state_ops_actions.rs` Phase
  4) paid STRICTLY from the floating pool via `pay_mana_cost_pub` (no
  auto-tap) and raw-`ValueError`-rejected because `{U:1}` < `{2}`.
  Python's `_activate_ability` (`actions.py:1992-1995`) instead pays
  the ability mana via the **IDENTICAL** `auto_tap_for_cost` call
  `_cast_spell` makes (`actions.py:1662`) — Python apply auto-taps
  lands and SUCCEEDS (verify-first-confirmed: Python p1 pool
  `[U]`→`[]`, the activation lands). This is precisely the §2-3
  `CastSpell` "permissive in legal, strict in apply" inversion, just
  for `ActivateAbility` — the §2-4 doc explicitly deferred the
  `ActivateAbility` pool-only path as a "separate axis"; this lane is
  that axis.
- Narrowing the legal emitter (the brief's hypothesized scope) would
  have produced a WORSE divergence: `activate_ability` IS in
  `rust_shadow`'s `_SET_EQ_KINDS`, so a pool-only Rust legal set would
  `LEGAL_SET_EQ`-diverge from Python's headroom-based legal set at the
  same step 318. New-code-is-right toward the Python SoT
  (`feedback_parity_new_code_is_right`) requires the apply-side fix.

**The fix (engine — new-code-is-right toward Python).** The §2-4
`auto_tap_pay_for_cost` helper in `state_ops_cast.rs` (the lands-only,
plan-then-commit byte-mirror of Python's `auto_tap_for_cost`) is
promoted `pub(crate)`; the `ActivateAbility` apply Phase-4 mana-pay is
rerouted from `pay_mana_cost_pub` to `auto_tap_pay_for_cost(state,
controller_idx, &resolved.mana_cost)`. Apply now auto-taps the
controller's untapped lands for the ability cost exactly as Python's
`_activate_ability` does (the Lander, being an Artifact not a Land, is
excluded from the auto-tap land pool and sacrificed separately in
Phase 5b — byte-equal to Python's order). A genuinely-unpayable
over-emit still degrades to the SAME no-mutation `Ok(false)` →
raw-`ValueError` bail the old pool-only path produced (no fallback
hybrid; the strict `pay_mana_cost_pub` is retained
`#[allow(dead_code)]` with ZERO live callers — provably not a runtime
fallback). **Files:** `rust/src/state_ops_actions.rs` +
`rust/src/state_ops_cast.rs` (helper visibility) + the bake-in pin
flip + 2 `tests_rust` pins that encoded the now-superseded pool-only
contract (closure-flipped to the corrected auto-tap-succeeds shape via
the established I50 `_tap_all_default_p0_mana_sources` idiom) + the SL
note + SOT_FLIP §4 + this §8. `state_ops_legal.rs` was NOT touched
(verify-first proved the legal gate was already correct). Per CFI-1/S5c
a `state_ops_*.rs` touch does NOT fire the cron structural arm
(confirmed: `check_audit_coverage_staleness.py` exit 0). A `.pyd`
rebuild on `main` is owed (orchestrator's).

**Result — frontier (a) CLOSED, byte-equal land payment.** With the
fix the arch2/s1 `ActivateAbility(121,0)` now applies successfully
(auto-tapping a Forest exactly as Python does); the bake-in runs
**318 → 320**.

**The next distinct divergence (honest-stop — surfaced, NOT
introduced).** With (a) closed the arch2/s1 bake-in trips a NEW
distinct frontier at **step 320**: a `STATE_EQ` `ShadowDivergenceError`
on `('library_p1', ...)` — a **library-ORDERING divergence**. With the
Lander's "Search your library for a basic land card ... then
**shuffle**" ability now applying byte-equal on both engines, the
post-search **shuffle produces a different library ORDER** in Rust vs
Python (identical 50-card multiset; the per-engine shuffle RNG is not
lockstep). The step-320 boundary + the `STATE_EQ`/`library_p1` shape
are deterministic across runs; only the library *content order* varies
run-to-run (that variance IS the divergence). A NEW G7 frontier
(search-then-shuffle library-order parity) — DISTINCT from (a) (closed)
and from frontier (b) (arch5/s0 step 367 — UNCHANGED, still
STILL-OPEN). Pinned LOUD by the flipped closure pin
(`test_g7_activateability_affordability_closed_then_next_frontier_
surfaced`) and filed as the next G7 follow-up (todo / SOT_FLIP §4).
NOT force-fixed in this lane (`feedback_no_fallback_hybrids`
honest-stop) — landing the sound (a) fix and pinning the unmasked
library-shuffle-order frontier precisely is the correct disciplined
outcome (the G4/G5/G6/S5a/combat-blocker precedent).
