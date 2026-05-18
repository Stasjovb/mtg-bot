# G7 mid-game STATE_EQ — verify-first finding + the auto-tap-from-lands engine fix

> **Status: CLOSED (the auto-tap frontier §2-4) + S1/S4
> spell-stack-source-zone CLOSED by S5a/S5b/S5c + the §5-predicted
> combat-blocker `LEGAL_SET_EQ` CLOSED by `fec5f14` (§7) + frontier
> (a) (`ActivateAbility` apply auto-tap, the §2-4 analog) CLOSED by
> `04d67d99` (§8) + honest-stop (a new distinct library-shuffle-order
> frontier pinned in §8; frontier (b) = S6 Class B arch5/s0 step 367
> `priority_player` VERIFY-FIRST RE-DIAGNOSED in §9 — a Rust-ENGINE
> slice, NOT an adapter-port slice; HONEST-STOP, STILL-OPEN).** Lane
> (this §8
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

## 9. Frontier (b) = S6 Class B (arch5/s0 step 367 `priority_player`) — VERIFY-FIRST RE-DIAGNOSED: a Rust-ENGINE slice, NOT an adapter-port slice (HONEST-STOP)

> **Status: HONEST-STOP — root cause is in `rust/src`, NOT the
> Rust-driver adapter port; this is a distinct Rust-engine slice
> (orchestrator-sequenced), explicitly NOT forced into the
> adapter-port lane.** Lane: `feature/g7-classb-priority-port` off
> `main` @ `3a963e0f`; pure-Python investigation, ZERO `rust/src` /
> `.pyd` / tracked-file change (the speculative adapter mirror was
> prototyped, verified NOT to close the trip, and reverted —
> `feedback_no_fallback_hybrids`; only throwaway `scripts/scout_classb_*`
> diagnostics committed). Frontier (b) = S6 Class B, the dominant
> 138/300 of the S6 scale-verify.

**The brief's framing (G5-family Rust-driver-ADAPTER priority-port —
the `86411a99` `_next_alive_idx` family mis-mirroring the Python SoT
on the production-deck path) is INVERTED by verify-first.** It is NOT
an adapter-port gap.

**RED-before (byte-exact at `3a963e0f`).** arch5/s0 step 367, a
`PassPriority()` at the BEGINNING_OF_COMBAT pass-round end (empty
stack, **`losers=[]`** — NOT a `_next_alive`/player-loss case at all,
unlike the synthetic-deck G5). Post-apply STATE_EQ
`('priority_player', 1, 0)` (Python=1, Rust=0): the empty-stack
step-end advances to DECLARE_ATTACKERS with an eligible attacker (obj
12 Icecave Crasher).

**Root cause (file:line both sides).** The **true SoT is
`simulate.py`** (`MtgGameStateAdapter` is itself a search-
reimplementation of it; the rust_shadow STATE_EQ compares against
`MtgGameStateAdapter`, which faithfully mirrors the SoT here):

- `simulate.run_step(DECLARE_ATTACKERS)` (`simulate.py:316-322`):
  `apply_action(DeclareAttackers)` does NOT touch
  `priority_player_idx`; only the subsequent `priority_loop`
  (`simulate.py:222-247`) sets `priority_idx = _next_alive(active)`
  (line 235/247) — and that fires at the FIRST DECLARE_ATTACKERS
  priority pass, AFTER the attacker decision. So at the
  `declare_attackers` decision moment + into `priority_loop` entry,
  `priority_player_idx` is the **CARRIED** value (=1, the prior
  BEGINNING_OF_COMBAT pass-round holder). Instrumented raw
  `simulate.py` on this exact deck/seed CONFIRMS
  `priority_player_idx=1` at `declare_attackers` + `priority_loop
  ENTER`.
- `MtgGameStateAdapter` mirrors the SoT: the combat-exposed
  `_enter_declare_attackers` / `_enter_declare_blockers`
  (`engine_adapter.py:1312-1316` / `:1358-1361`) set `_combat_phase`
  and RETURN WITHOUT `_enter_priority_for_current_step`;
  `priority_player_idx` stays carried through the whole factored-
  combat window (reset deferred to `_finalize_*_phase` `:1112` /
  `:1144`); `active_player()` (`:753-767`) overrides the
  decision-maker to active (attackers) / defender (blockers) while
  `priority_player_idx` stays carried.
- The Rust **engine** is the SoT-divergent side: (i)
  `state_ops_actions.rs:1444-1446` unconditionally
  `state.priority_player = state.active_player` after EVERY non-pass
  action (the round-27 G3+G4 post-arm CR-117.1c reset), and (ii)
  `state_ops_legal.rs:1199` `if self.priority_player != player_id {
  return [pass] }` gates ALL factored-combat emission on the queried
  player == Rust's `priority_player`. So Rust STRUCTURALLY requires
  `priority_player == active` during DECLARE_ATTACKERS — it never
  carries priority through the factored-combat window like the
  `simulate.py` SoT does.

**Why the Rust-driver adapter CANNOT reconcile this in-scope.** Per
`feedback_parity_new_code_is_right` the SoT (`simulate.py`) is the
correct side and `MtgGameStateAdapter`'s carried priority is
SoT-faithful; the Rust ENGINE is wrong. The adapter cannot keep
Rust's `priority_player` carried because the `state_ops_legal.rs:1199`
gate would then suppress the factored-combat emission (chicken-and-egg:
detecting the factored-combat window needs the emission, the emission
needs `priority == active`), and `state_ops_actions.rs:1446`
re-forces `priority=active` after every apply regardless of what the
adapter sets — both in `rust/src`. The only adapter-side "fixes" are
(a) touching `rust/src` (out of this lane) or (b) a masking
`_DOCUMENTED_ACCEPTED_FIELDS` carve-out the S6 evidence pins empty and
the brief forbids. A pure-Python `_combat_decision_maker` deferred-
priority adapter mirror was prototyped and **verified NOT to close the
step-367 trip** (the line-1199 gate blocks the factored-combat
detection), then reverted — confirming the root cause is the Rust
engine, not the port.

**Conclusion + fix scope (a Rust-engine lane, orchestrator-
sequenced).** Class B is RE-CLASSIFIED: NOT a G5-family
adapter-port slice — a **Rust-engine `CastSpell`/priority-model
slice**. The Rust engine's "`priority_player == active` during/after
non-pass actions" model (`state_ops_actions.rs:1444-1446` + the
`state_ops_legal.rs:1199` combat-emit priority gate) diverges from the
`simulate.py` SoT which keeps `priority_player_idx` carried through
the factored-combat decision window. Fix scope = a Rust-engine slice:
make the Rust DECLARE_ATTACKERS/DECLARE_BLOCKERS factored-combat
decision NOT force `priority_player=active` (mirror `simulate.py`'s
"priority stays carried until the DECLARE_ATTACKERS priority loop's
first pass"), or relax the line-1199 combat-emit gate to key on
active/defender (not `priority_player`) while keeping `priority_player`
carried. Sequenced by the orchestrator as a Rust slice — NOT this
adapter-port lane (the brief's explicit STOP condition). The bake-in
pin's arch5/s0 row is UNCHANGED (it still correctly asserts Class B
surfaces at step 367 — RED-before byte-identical at `3a963e0f`); the
arch2/s1 row (shuffle-order `b3f7c0a9`) is UNCHANGED. 4-file core gate
**1536 UNMOVED**; `tests_rust` zero-newly-failing vs `3a963e0f`; cron
exit 0; isolation self-check PASSED (shared canonical `.pyd`
byte-identical before/after — zero `rust/src` ⇒ NO `.pyd` rebuild
owed). NOT merged / NOT pushed.

## 9.1 Class B cycle-35 — the Rust-ENGINE option-β change is PROVEN-CORRECT but the residual blocker is the OUT-OF-LANE Rust-driver ADAPTER (HONEST-STOP, ZERO committed engine)

> **Status: HONEST-STOP — the engine sub-part is verify-first
> PROVEN correct + non-regressing, but it closes 0/138 alone and the
> residual blocker is `rust_engine_adapter.py` (the brief's explicit
> out-of-lane prohibition + STOP condition). ZERO committed
> `rust/src`/`.pyd`/tracked-file change — exactly the cycle-33
> discipline.** Lane: `feature/g7-classb-engine` off `main` @
> `430f3b39`; worktree-isolated `.venv-py313`; only throwaway
> `scripts/scout_classb_{pathtrace,combinedproof,scalecompare}.py`
> + this finding/SL/SOT_FLIP doc update committed.

**RED-before (byte-exact at `430f3b39`).** Reproduced identically to
§9: arch5/s0 step 367, `PassPriority()` at the BEGINNING_OF_COMBAT
pass-round end (empty stack, `losers=[]`). Post-apply STATE_EQ
`('priority_player', 1, 0)` — Python carries `priority_player_idx=1`,
Rust forces `0`. Pre-apply both `pri=1 act=0`; post-apply Python
`step=DECLARE_ATTACKERS pri=1`, Rust `phase=5 pri=0`.

**Verify-first PINPOINTED the immediate force (instrumented
`_reset_priority_to_active`/`_advance_to_next_decision`/
`_run_priority_action` wrappers — `scout_classb_pathtrace.py`).** At
step 367 the `_run_priority_action(PassPriority)` empty-stack
pass-round-end branch (`rust_engine_adapter.py:456-473`) does
`advance_phase()` (phase 4→5, BEGINNING_OF_COMBAT→DECLARE_ATTACKERS)
then **`_reset_priority_to_active()` (`rust_engine_adapter.py:473`)**
which fires `pri 1→0`. Rust's own `advance_phase` does NOT reset
priority on this transition (only the CLEANUP→UNTAP wrap does,
`state_ops_steps.rs:523`); `state_ops_actions.rs:1444-1446` is guarded
`if !is_pass_priority` (does NOT fire on a PassPriority).
**Conclusion: the IMMEDIATE `priority_player=0` force is
`rust_engine_adapter.py:473` — NOT in `rust/src`.** The Python
`MtgGameStateAdapter._run_priority_action` empty-stack branch
(`engine_adapter.py:969-971`) does ONLY `_advance_to_next_step()` —
NO priority reset — deferring it to `_enter_step` →
`_enter_priority_for_current_step`, which the combat-exposed
`_enter_declare_attackers` SKIPS (returns without it). The Rust-driver
port added the eager `:473` reset; that eager reset is the divergent
code, and it is in the FORBIDDEN `rust_engine_adapter.py`.

**The chosen engine fix = option β, `state_ops_legal.rs` only**
(byte-faithful to the Python adapter's structural decision-maker):
move the DECLARE_ATTACKERS / DECLARE_BLOCKERS factored-combat emission
ABOVE the line-1199 priority gate (turning the early `return` into a
relocated `is_priority_holder` gate that fences only the genuine
priority-window emission — PlayLand/CastSpell/ActivateAbility/sorcery
block, byte-identical to the old predicate), and key the blocker gate
on the **structural defender** `player_id == 1 - active_player`
(Rust's own canonical defender, `state_ops_combat.rs:941` /
`state_ops_choices.rs:104`; byte-equal to Python's
`_combat_defender_id = _next_alive((active+1)%n)` in the
loader-admitted no-loss 2-player model) instead of the
`priority_player != active_player` proxy (which only held because the
adapter forced `priority==active`). The attacker gate already keys on
`active_player == player_id` (= Python `active_player()` returning
`active_player_idx` during `_COMBAT_ATTACKERS`). Option α alone is
INSUFFICIENT (verified): it would need the SAME line-1199 relaxation
to break the chicken-and-egg, so β is the minimal, byte-faithful,
smallest-blast-radius shape.

**Verify-first PROOF the engine change is correct (the decisive
`scout_classb_combinedproof.py` run, change ACTUALLY built into the
worktree wheel).** With the option-β engine change BUILT IN **plus**
a throwaway monkeypatch that defers the adapter's
`_reset_priority_to_active` for factored-combat steps (the
hypothetical coordinated `rust_engine_adapter.py` change Python's
`_enter_declare_*` already embodies by returning without
`_enter_priority_for_current_step`): **step 367 CLOSES** — the run
proceeds PAST it (no `('priority_player',1,0)` trip) and surfaces a
NEW distinct divergence at **step 368: `STATE_EQ active_player
divergence: rust=1 python=0`** (Python combat decision-maker = active
= 0 via `MtgGameStateAdapter.active_player()`'s `_COMBAT_ATTACKERS`
override; Rust `RustGameStateAdapter.active_player()`
(`rust_engine_adapter.py:543-550`) returns `_priority_pid()` = the
now-carried priority = 1). So closing Class B requires BOTH (a) the
`rust/src` line-1199 option-β relaxation (this lane — proven correct)
AND (b) a coordinated `rust_engine_adapter.py` change: defer
`_reset_priority_to_active` for factored-combat steps (`:473`) AND
make `active_player()` return the combat decision-maker
(active/defender) instead of `_priority_pid()` during factored combat
(`:543-550`). Part (b) is the brief's explicit out-of-lane
prohibition + STOP condition.

**Why the engine change is SOUND but NOT landed (HONEST PROGRESS, no
forced partial).** Built into the worktree wheel and exercised:
`tests_rust` 30 failed / 2312 passed = **zero-newly-failing,
zero-newly-passing vs `430f3b39`** (byte-identical `feedcf93`
baseline-rot set); bake-in suite **16 green** (the arch5/s0 + arch2/s1
pin rows UNCHANGED — Class B still surfaces at 367, correctly NOT
flipped); a 60-game C4-class scale sweep
(`scout_classb_scalecompare.py`, 12 arch × 5 seeds, pristine wheel vs
changed wheel) is **behavior-neutral**: identical status distribution
(`TIMEOUT 33 / FAIL_DIVERGENCE 27` ≡ `33 / 27`), **58/60 games
byte-identical**, the only 2 deltas are SAME-step / SAME-tripwire /
SAME-field (`library_pX` STATE_EQ @211/@286) shifts of WHICH card in
the **already-filed `b3f7c0a9` library-SHUFFLE-ORDER frontier**
surfaces (the run-to-run shuffle variance that pin explicitly
documents — NOT a new divergence, NOT a boundary shift, NOT a closed-
axis regression; the arch2/s1 row is NOT touched). The change is the
**correct, necessary, non-regressing engine half** of a 2-part fix —
but on its own it **closes 0/138, moves NO pin, flips NO closure**,
and the residual blocker (`rust_engine_adapter.py:473` + `:543-550`)
is explicitly out of this lane. Landing a no-closure `rust/src` change
that owes a `.pyd` rebuild + cron resync + `state_ops_legal.rs` lane
serialization for ZERO progress is exactly the forced-partial /
incomplete-half the brief and HONEST PROGRESS reject. Therefore: the
engine change is **reverted to pristine** (the worktree `rust/src` is
byte-pristine; the proven-correct diff is preserved verbatim below as
the orchestrator's hand-off artifact for the coordinated
engine+adapter Class-B slice), exactly the cycle-33 ZERO-engine
honest-stop discipline.

**The proven-correct engine diff (orchestrator hand-off artifact —
NOT committed as engine; apply alongside the coordinated
`rust_engine_adapter.py` `:473`/`:543-550` change).** `git apply`
against `rust/src/state_ops_legal.rs` @ `430f3b39`:

1. Replace the line-1197-1201 `if self.priority_player != player_id {
   return Ok(actions); }` early-return with `let is_priority_holder =
   self.priority_player == player_id;` (factored-combat blocks below
   run BEFORE the gate; emission keyed on the structural
   decision-maker, NOT priority).
2. The DECLARE_BLOCKERS gate `self.priority_player !=
   self.active_player` → `player_id == 1 - self.active_player` (the
   structural defender; byte-equal to Python's
   `_next_alive((active+1)%n)` defender in the no-loss 2-player
   model).
3. Insert `if !is_priority_holder { return Ok(actions); }`
   immediately BEFORE the sorcery-timing block (the relocated former
   line-1199 early return — byte-identical priority-window-emission
   semantics; only the factored-combat blocks now emit independent of
   `priority_player`).

(+79 / -12 in `state_ops_legal.rs`, comments included. Touches NOTHING
else.)

**Re-characterized Class B count: 0/138 closed by this lane**
(HONEST — the engine half alone closes none; the dominant 138/300
arch5/s0-step-367 `('priority_player',1,0)` STATE_EQ is UNMOVED). The
bake-in pin's arch5/s0 row STAYS surfaced (NOT flipped — Class B is
NOT closed); the arch2/s1 row is UNTOUCHED (the `b3f7c0a9` lane owns
it). The next frontier behind Class B is **arch5/s0 step 368
`STATE_EQ active_player divergence: rust=1 python=0`** (characterized
above; it is gated behind the coordinated engine+adapter Class-B fix
landing, so it is documented here — NOT pinnable as a surfaced
boundary while step 367 still trips first).

**Conclusion + RE-SCOPE.** Class B is a **coordinated Rust-engine +
Rust-driver-adapter slice**, NOT an engine-only slice: the necessary
`state_ops_legal.rs` option-β engine change (proven correct here) MUST
land together with the `rust_engine_adapter.py:473` deferred-priority
+ `:543-550` combat-decision-maker `active_player()` change. The brief
scoped this lane as engine-only and forbade `rust_engine_adapter.py`;
per the brief's explicit STOP condition this lane HONEST-STOPS with
ZERO committed engine. Gate: 4-file core **1536 UNMOVED** (zero
Python/test/`parity_smoke.py`); `tests_rust` 30 failed / 2312 passed =
zero-newly-failing vs `430f3b39` (byte-identical); bake-in suite 16
green (arch5/s0 + arch2/s1 rows UNCHANGED); all prior G7 closure pins
green; `check_audit_coverage_staleness.py` exit 0; isolation
self-check PASSED (shared canonical `.pyd` SHA256/size/mtime
byte-identical before/after — worktree-isolated builds only, zero
committed `rust/src` ⇒ orchestrator owes NO `.pyd` rebuild). NOT
merged / NOT pushed.

## 9.2 Class B cycle-37 — the coordinated engine+adapter slice LANDED (Class-B priority axis CLOSED; next frontier @369 surfaced)

> **Status: LANDED on `feature/g7-classb-priority-port-fix` off
> `main` @ `dc22ebc4`.** The coordinated Rust-engine + Rust-driver-
> adapter slice the §9.1 hand-off artifact pre-staged was applied
> verbatim, built into a worktree-local `.venv-py313`, gates were
> run cleanly, and the bake-in arch5/s0 pin was flipped from
> surfaced-at-367 to surfaced-at-369. Shared canonical `.pyd`
> SHA256/size/mtime byte-identical before/after — orchestrator owns
> the merge + canonical resync.

**Engine half (option-β, `rust/src/state_ops_legal.rs` only,
+95/-13).** Applied as documented in §9.1 step (1)/(2)/(3): relocate
the line-1199 priority gate to a flag `is_priority_holder`, run the
factored-combat DECLARE_ATTACKERS/DECLARE_BLOCKERS emission ABOVE the
gate keyed on the structural decision-maker (attackers:
`active_player == player_id`; blockers: `player_id == 1 -
active_player`, Rust's canonical defender), and re-apply the
byte-identical priority-window early return
`if !is_priority_holder { return Ok(actions); }` immediately BEFORE
the sorcery-timing / instant-speed CastSpell / PlayLand /
ActivateAbility block (fences ONLY the genuine priority-window
emission, byte-identical to the old predicate).

**Adapter half (coordinated, `src/mtg_bot/search/rust_engine_adapter.py`,
+155/-14).** Three structural changes:

1. `_run_priority_action` PassPriority empty-stack pass-round-end
   branch (line ~473): defer `_reset_priority_to_active()` when the
   just-advanced step is a factored-combat window with a pending
   factored decision for the structural decision-maker — exactly the
   Python `_enter_declare_*` / `simulate.py` SoT contract (priority
   stays carried; the priority-loop's first pass after the attacker
   decision resets it).
2. `active_player()`: return the combat decision-maker
   (`_combat_decision_maker()`) during factored-combat windows;
   priority holder otherwise. Byte-mirrors Python's
   `MtgGameStateAdapter.active_player()` `_COMBAT_*` overrides.
3. `legal_decisions()`: query Rust with `active_player()` (the
   decision-maker), not `_priority_pid()` directly. Strip the
   structural `PassPriority` from the factored-combat set
   (Python's adapter `legal_decisions()` returns ONLY the factored
   pairs during the combat window — `engine_adapter.py:808-828`).
   New helper `_combat_decision_maker()` resolves the
   factored-combat decision-maker structurally (phase ∈ {DA, DB}
   AND Rust emits a factored decision for the structural
   decision-maker; else `None` = not a factored-combat window).

**Test pins flipped.** `tests/test_g7_s6_scale_verify.py`'s
arch5/s0 Class-B row flipped from `(367, STATE_EQ,
('priority_player',1,0))` to the next-frontier-surfaced
`(369, LEGAL_SET_EQ, py\rust=["('pass',)"])` row;
`tests/test_rust_shadow_bakein.py`'s arch5/s0 bake-in row flipped
the same way (boundary `344 → 367`, `STATE_EQ` →
`LEGAL_SET_EQ`). The new frontier @369 is the
**pre-existing G1 stateless-Rust `attack=False` re-emission gap**
(Rust `apply_action(AttackerDecision, attack=false)` is a deliberate
no-op and the `RustGameStateAdapter` does not port Python's
provider-side `_pending_attackers.pop(0)` + `_finalize_attacker_phase`
accumulation — the B3-S3 sibling slice the G1 design defers),
unmasked — NOT introduced — by closing 367.

**Verify-first proof (this commit, byte-identical to §9.1
combinedproof but with the adapter half ACTUALLY landed, not
monkeypatched).** Pre-fix `scout_classb_arch5s0.py 5 0 365`:
trips at step 367 STATE_EQ `('priority_player',1,0)`. Post-fix
(same scout): proceeds through step 367 (`PassPriority` post-apply
Py `pri=1` Rust `pri=1` — matches Python SoT), through step 368
(`AttackerDecision attacker_id=12 attack=False`), surfaces at step
369 `LEGAL_SET trip @ step 369` `LEGAL_SET_EQ rust\py=["('attacker',
12, False)", "('attacker', 12, True)"] py\rust=["('pass',)"]
(active_player=0)` — the exact signature the bake-in pin now expects.

**Gate (4-file core / `tests_rust` / audit / bake-in / isolation):**

- 4-file core gate: **1536 PASSED** (`test_parity_smoke +
  test_cross_engine_etb_triggers + test_trajectory_parity +
  test_trajectory`) — UNMOVED, exactly baseline.
- `tests_rust`: **30 failed / 2312 passed BYTE-IDENTICAL** to
  pristine `dc22ebc4` (captured by stashing my diff, rebuilding,
  diffing the failure-set sorted list — `diff` returns empty).
  Zero newly-failing, zero newly-passing — the feedcf93-baseline
  factored-combat/observer reds are untouched.
- `tests/test_g7_s6_scale_verify.py`: **6 passed / 2 failed** — the
  2 fails are PRE-EXISTING at pristine `dc22ebc4` (arch2/s1
  B1-axis boundary `318 → 320`, NOT a Class B row; verified by
  pristine rebuild). Same 2 fails on the pristine wheel.
- `tests/test_rust_shadow_bakein.py`: **17/17 green** (the
  17-pin Class-D-closure-included set the brief tracks; the new
  arch5/s0 step-369 pin asserts the next-frontier-surfaced
  state, replacing the old step-367 surfaced state).
- `python scripts/check_audit_coverage_staleness.py` exit **0**.
- Isolation self-check: shared canonical `.pyd` at
  `C:\Users\Gregg Keithley\Documents\Claude\Projects\mtg-bot\.venv-py313\Lib\site-packages\mtg_bot_engine\mtg_bot_engine.cp313-win_amd64.pyd`
  SHA256 `BEB897AC88E4876AAEA61E8909DEC26C6EDB98E39B332F1395E54A4C77A34EB8`
  size 1501696 mtime `05/18/2026 05:40:12` **byte-identical
  before/after** my worktree-local maturin develop --release.
  Orchestrator owns the canonical `.pyd` resync after merge.

**Honest count.** Class B priority axis CLOSED for arch5/s0
(the dominant 138/300 manifestation). The next frontier @369
(the G1 stateless-Rust attack=False re-emission / B3-S3
provider-accumulation port) is DISTINCT, PRE-EXISTING (zero
provider accumulation at `dc22ebc4`), and unmasked — NOT
introduced — by closing 367 (arch5/s0 simply never reached a
factored `attack=False` before, blocked at 344/367). Filed as
the next G7 follow-up.

**NOT merged / NOT pushed.** Branch
`feature/g7-classb-priority-port-fix` off `main @ dc22ebc4`;
orchestrator owns merge + canonical `.pyd` resync + lane
serialization.

## 9.3 G7 @369 G1 stateless-Rust attack=False re-emission / B3-S3 provider-accumulation port LANDED (todo `a92e7d4f`)

> **Status: LANDED on `feature/g7-g1-stateless-attacker-decision-port`
> off `main` @ `89a4f32b`.** The B3-S3 sibling slice the G1
> stateless-Rust design explicitly deferred has been ported: the
> `RustGameStateAdapter` now byte-mirrors Python
> `MtgGameStateAdapter._apply_attacker_decision` /
> `_finalize_attacker_phase` (and the blocker counterparts).
> Multi-seed pins flipped: arch5/s0 @369 → CLOSED (next-frontier
> @504 combat-damage/SBA divergence surfaced); arch7/s0 @757 →
> CLOSED (next-frontier @808 priority + tapped-state STATE_EQ
> surfaced); arch30/s1 @321 → CLOSED (next-frontier @431 life-total
> STATE_EQ surfaced). Shared canonical `.pyd` SHA256/size/mtime
> byte-identical before/after — orchestrator owns the merge.

**Verify-first reproduction (pre-fix).** The brief's premise — that
Rust `apply_action(AttackerDecision, attack=false)` is a deliberate
no-op (`state_ops_actions.rs:1357-1384`) and the
`RustGameStateAdapter` does not port Python's provider-side
`_pending_attackers.pop(0)` + `_finalize_attacker_phase` accumulation
(`engine_adapter.py:1080-1108`) — was confirmed via
`scripts/scout_classb_arch5s0.py 5 0 365`:
- Step 368 (pre-apply): Both engines in DECLARE_ATTACKERS combat
  window. `AttackerDecision(attacker_id=12, attack=False)` is applied.
- Rust apply: NO-OP (the `false` branch).
- Step 369 (post-apply): Python's adapter has popped `_pending_attackers[0]
  = 12`, queue empty → `_finalize_attacker_phase` runs → priority
  window opens → `legal_decisions()` returns `[PassPriority()]`. Rust
  still has obj 12 untapped + eligible → emits factored
  `[('attacker',12,True), ('attacker',12,False)]` pair again. The
  `rust_shadow` LEGAL_SET_EQ check trips: `rust\py=
  ["('attacker',12,False)", "('attacker',12,True)"] py\rust=
  ["('pass',)"]`.

Same signature multi-seed:
- arch7/s0 @757: `('attacker', 120, False)` re-emission (Knight Luminary).
- arch30/s1 @321: `('attacker', 80, False)` re-emission (Thawbringer).

**Fix (`rust_engine_adapter.py`, the bridge — zero Rust diff).**
Faithful mirror of the Python SoT:

1. **`_compute_eligible_attackers(player_id)` /
   `_compute_eligible_blockers(player_id)`** — Python-side
   re-computation of Rust's eligibility predicate
   (`state_ops_legal.rs:1308-1343`) using `battlefield_snapshot()` +
   the `printing_resolver`. Byte-equal to Rust's filter (controller +
   not tapped + Creature + not summoning-sick OR has haste + not
   defender). UEOT-granted-defender is documented as out-of-scope on
   the loader-admitted EoE surface (zero such cards; would require a
   Rust pymethod if/when one lands).

2. **`_refresh_combat_phase` — initialize-on-entry only.** Pre-port
   the queue was re-derived to `[atk_heads[0]]` (just the
   `min(eligible)` Rust emits) on every `legal_decisions()` call —
   correct only because `attack=True` taps the creature so Rust's
   `min(eligible)` advanced naturally; `attack=False` broke this
   (creature stays eligible, head doesn't advance, queue
   re-derived to same id forever). Post-port: on the transition
   `_combat_phase: None → ATTACKERS/BLOCKERS` the queue is sized
   to the FULL sorted eligible-id list (mirroring Python
   `_enter_declare_attackers`'s
   `self._pending_attackers = sorted(o.id for o in eligible)`,
   `engine_adapter.py:1315`). Within the same window subsequent
   calls leave the in-flight queue alone — only `apply` pop /
   `finalize` mutates it.

3. **`_run_priority_action` — pop on apply, finalize on empty.**
   The `AttackerDecision` / `BlockerDecision` arm now pops
   `_pending_attackers[0]` / `_pending_blockers[0]` after the Rust
   `apply_action` dispatch (mirroring Python's
   `_apply_attacker_decision`'s `_pending_attackers.pop(0)` at
   `engine_adapter.py:1097`). On an empty queue, calls the
   freshly-ported `_finalize_attacker_phase` /
   `_finalize_blocker_phase` (mirror of
   `engine_adapter.py:1101-1144` minus the
   `apply_action(DeclareAttackers/Blockers)` — Rust already
   accumulated via per-decision `declare_attacker` /
   `declare_blocker` primitives). Out-of-order
   `AttackerDecision`/`BlockerDecision` raises (loud-fail per
   `feedback_silent_noop_pipelines`).

4. **`_finalized_combat_window: (turn, phase)`** — a marker
   capturing the moment `_finalize_*_phase` ran. Within the SAME
   (turn, phase) `_refresh_combat_phase` and
   `_combat_decision_maker` treat the window as "done", suppressing
   factored re-emission while Rust is structurally still in
   DECLARE_ATTACKERS / DECLARE_BLOCKERS (a declined attacker stays
   eligible → Rust still emits a factored pair, but Python's
   adapter has moved on; the marker keeps both adapters in
   lockstep). When the (turn, phase) tag advances — natural step
   progression or turn rollover — the marker becomes stale and the
   adapter is free to enter the next factored window.

5. **`legal_decisions` — synthesize from queue head, filter
   post-finalize.** Inside an in-flight factored-combat window, the
   emitted legal set is exactly the factored option pair for
   `_pending_attackers[0]` / `_pending_blockers[0]` (NOT Rust's
   `min(eligible)` head). Post-finalize, factored dicts are
   filtered OUT — only the priority-window set passes through.
   This is the byte-equal Python adapter shape: factored options
   only during the window, priority-window set elsewhere
   (`engine_adapter.py:808-828`).

**Test pins flipped.**
- `tests/test_rust_shadow_bakein.py`:
  - `test_g7_activateability_affordability_closed_then_next_frontier_surfaced`'s
    arch5/s0 row: `(367, 369, "LEGAL_SET_EQ", "py\\rust=[\"('pass',)\"]")`
    → `(369, 504, "STATE_EQ", "('graveyard_p0'")`. Loop cap
    400 → 4000.
  - `test_g7_classd_castset_seqwrap_targets_closed_then_next_frontier`
    (arch7/s0): `(453, 757, "LEGAL_SET_EQ", "('attacker', 120, False)")`
    → `(757, 808, "STATE_EQ", "('priority_player', 0, 1)")`.
  - `test_g7_classd_1of23_thawbringer_mana_affordability_closed_then_next_frontier`
    (arch30/s1): `(111, 321, "LEGAL_SET_EQ", "('attacker', 80, False)")`
    → `(321, 431, "STATE_EQ", "('life_p0', 16, 20)")`.
- `tests/test_g7_s6_scale_verify.py`: Class-B row (arch5/s0) +
  Class-D row (arch7/s0) flipped identically.

**Next frontiers surfaced (filed as follow-up todos).** Three
DISTINCT new G-axes unmasked by the @369 closure:
- arch5/s0 @504: combat-damage outcome / SBA divergence (Python killed
  Crasher (id 12) + Seedship Agrarian (id 83) via lethal damage;
  Rust kept them on battlefield).
- arch7/s0 @808: priority + tapped-state STATE_EQ (Knight Luminary
  tapped=0 py vs tapped=1 rust; priority_player 0 vs 1).
- arch30/s1 @431: life-total STATE_EQ (`life_p0` 16 py vs 20 rust;
  4-life delta consistent with combat-damage outcome).

All three are NEW G-axes distinct from @369/@757/@321 and from prior
closures; PRE-EXISTING (zero combat-damage parity on the bake-in
surface before this slice opened the gate); unmasked — NOT introduced
— by the present closure. Each filed as its own follow-up todo.

**Gate (4-file core / `tests_rust` / audit / bake-in / isolation):**

- 4-file core gate: **1536 PASSED** UNMOVED.
- `tests_rust`: **30 failed / 2312 passed BYTE-IDENTICAL** to
  pristine `89a4f32b` (the feedcf93 baseline reds untouched —
  `Compare-Object` returns empty against main's failure set).
  Zero newly-failing.
- `tests/test_g7_s6_scale_verify.py`: 6 pass / 2 PRE-EXISTING fails
  (arch2/s1 @318 raw → @320 STATE_EQ — the b3f7c0a9
  library-shuffle-order baseline-rot byte-identical to main; NOT
  this lane).
- `tests/test_rust_shadow_bakein.py`: **20/20 green** with all
  three multi-seed @369/@757/@321 pins flipped to
  closure+next-frontier-surfaced.
- `python scripts/check_audit_coverage_staleness.py` exit **0**
  (no Rust touch → structural arm did not fire).
- Isolation self-check: shared canonical `.pyd` at
  `mtg-bot\.venv-py313\Lib\site-packages\mtg_bot_engine\mtg_bot_engine.cp313-win_amd64.pyd`
  SHA256 `A47C1232C33E61BBD87B28717C916CBD3759E332ED6F913157E0B8DE461D2AB2`
  size 1523712 mtime `05/18/2026 11:03:29 AM` **byte-identical
  before/after** the worktree-isolated `.venv-py313` builds.
  This slice ships **ZERO Rust diff** → no `.pyd` rebuild owed,
  no canonical resync owed at merge.

**NOT merged / NOT pushed.** Branch
`feature/g7-g1-stateless-attacker-decision-port` off `main @
89a4f32b`; orchestrator owns merge.
