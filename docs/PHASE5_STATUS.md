# Phase 5 status & closure roadmap

Snapshot date: 2026-05-12 (end-of-day; CE8 fully closed via two slices,
CE9-CE12 closed, CE13 surfaced, bilateral combat probe walks 260
decisions clean).

**Punchline.** The biggest open architectural item shipped today — CE8
(PRNG mismatch / shuffle RNG externalization) is FULLY CLOSED across
all 8 gameplay shuffle sites via the PyO3 `_randbelow` callback
substrate, which simultaneously unblocks G19. CE9 (multi-block combat
blocker ordering) closed with a 1000/1000 clean multi-block smoke;
CE10/CE11/CE12 closed in single small slices; the retaliation probe
walks 260 decisions of bilateral combat clean. The Rust engine carries
**80 `Effect` variants** covering **75.7%** of per-card emissions on
the EoE+stellar_sights+special_guests_eoe+duskmourn pool. Only ONE
open CE divergence remains (CE13, a low-impact graveyard `summoning_sick`
field asymmetry) and one substrate item (G19) is now a one-line
Effect-arm edit on top of the external-RNG plumbing CE8 left in place.
Phase 4a/4b are functionally complete (freq>=10 head: 13/14, with the
remaining 1 case shipped under a renamed Rust variant; freq 2-9 mid:
52/53, 98.1%). The remaining work to a 1000-game cross-engine smoke
is now a handful of small slices plus a Phase 5 probe extension into
the next combat keyword surface (first-strike / deathtouch / trample /
lifelink / counterspells).

---

## 1. Where we are

### Numbers

- **80 Rust `Effect` variants** in `rust/src/cards.rs` (was 77 at
  2026-05-11 snapshot; +3 today including
  `DrawCardsEqualToResolvingCombatDamage`, plus 2 carried from late
  2026-05-11 — `OptionalManaCostThenEffect`,
  `ManifestDreadThenPutPlusOneCountersOnIt`).
- **74 / 228 Python Effect classes covered (32.5%)** by class count
  (was 31.1%).
- **522 / 690 per-card emissions covered (75.7%)** — the load-bearing
  weighted metric (was 74.8%).
- **Frequency tiers** (`docs/RUST_EFFECT_COVERAGE.md`):
  - Freq >= 10 (head, 14 classes): **13 / 14 covered (92.9%)** —
    only `ModalChooseOne` shows as "no", but Rust ships
    `Effect::ChooseOneMode` (1:1 functional match); the coverage
    table flips to 14/14 once the `feature/coverage-overrides` PR
    merges the override map.
  - Freq 2-9 (mid, 53 classes): **52 / 53 covered (98.1%)** — was
    49/53 at 2026-05-11 (`DrawCardsEqualToResolvingCombatDamage`
    closed the last freq-2 miss).
  - Freq 1 singletons (161 classes): **9 / 161 (5.6%)** — explicitly
    out of Phase 5/6 scope per `RUST_PARITY_PLAN.md` "Phasing" §3.
- **Rust test gate**: ~1814 passing on main (was 1693 at 2026-05-11
  start-of-session; +121 today across CE8 + CE9 + CE11 + CE12 + the
  combat-damage write-site + freq-2 closure + bf-iter resolve arms).
- **Python test gate**: 10127 passed / 12 skipped / 3 xfailed
  (CE13 strict-xfail + CE8 legacy-path companion symptom-pin + one
  pre-existing). One pre-existing red unrelated to Phase 5:
  `test_no_orphan_rust_variants` (3 orphans pending the unmerged
  `feature/coverage-overrides` PR).

### Parity plan status (`docs/RUST_PARITY_PLAN.md`)

| Phase | Status |
|---|---|
| 0 Engine primitives | done (r1-r19) |
| 1 Discovery + scaffold | done (r20) |
| 2 Externalize RNG + spec GameState API | **done end-of-day 2026-05-12** (CE8 closure landed the external-RNG substrate + rewired all 8 shuffle sites via `external_rng::next_below`) |
| 3 Action types + legal_decisions | done (r22-r25) |
| 4a Top-14 high-frequency Effects | done modulo coverage-overrides PR merge (13/14 shipped, `ModalChooseOne` -> `Effect::ChooseOneMode` 1:1) |
| 4b Mid-frequency Effects (next ~50) | **done modulo 1 singleton** (52/53 shipped — was 49/53 yesterday) |
| **5 Per-step trajectory diff** | **in flight — all 12 prior CEs closed; CE13 surfaced + pinned; bilateral combat probe walks 260 decisions clean; mass-removal probe walks 168 decisions clean** |
| 6 Scale to 1000 games | **partial — 1000/1000 clean multi-block combat smoke on `multi_blocker_deckspec` post-CE9 closure** |

### Cross-engine divergences surfaced + closed today (2026-05-12)

The probe-close-probe cadence held all day. Closed CEs delta vs the
2026-05-11 snapshot (CE5 + CE6 + CE7 + CE10 closed late 2026-05-11):

- **CE8** (shuffle PRNG mismatch — Python MT19937 vs Rust xorshift64).
  CLOSED in 2 slices today:
  - Slice 1 (`4cc6d57a`, merge `0c594782`): new `rust/src/external_rng.rs`
    + PyO3 `_randbelow` callback + setup-shuffle rewire + cross-engine
    `shared_rng_seed` substrate in `parity/cross_engine.py`.
  - Slice 2 (`14e78d4a`, merge `832501a3`): remaining 6 gameplay
    shuffle sites in `state_ops_library.rs` (3 sites) +
    `state_ops_mulligan.rs` (3 sites) rewired through the same
    helper. Simultaneously unblocks **G19** (the closure is now a
    one-line Effect-arm edit at the `SearchLibraryForBasicLandTapped`
    resolve site).
- **CE9** (multi-block combat blocker walk: Rust used `self.blockers`
  push order, Python walks centralized `state.battlefield` filtered
  by `attacker.blocked_by`). CLOSED `9633953e` + `cdd6ce00` (merge
  `90a015dc`). 1000/1000 clean multi-block smoke on
  `multi_blocker_deckspec`. Secondary closure folded in:
  SBA-destroy now clears per-object `damage`/`tapped`/`attached_to`
  on move-to-graveyard (mirrors `turn.move_off_battlefield`).
- **CE10** (`is_over` / `winner_id` / `is_draw` pure-derivation
  asymmetry). CLOSED late 2026-05-11 via SBA-gated accessors on the
  Rust side.
- **CE11** (cross-player find-first arms — `TapAnotherTargetCreature`
  + `UntapTargetOtherPermanent`). CLOSED late 2026-05-11 via
  `bf_iter_etb_sorted` helper consumption.
- **CE12** (winner_id sticky-vs-derived in BOTH-LOST transition,
  surfaced today by the retaliation probe). CLOSED `882be26b` +
  `850bf3d0` (merge `33ba594d`). Rust `winner_id_sticky: Option<u8>`
  write-once shadow field mirrors Python's `turn.py:1383-1393` SBA
  write semantics. Retaliation probe now walks 260 decisions clean
  (was 226 at surface time).
- **CE13** (`summoning_sick` field clearing on leaves-battlefield
  via mass removal — Python preserves, Rust clears). SURFACED today
  by `feature/phase5-mass-removal` (`00944235`, merge `798a4e70`),
  pinned at `tests/test_parity_smoke.py::test_cross_engine_mass_removal_selector_surfaces_ce13_summoning_sick_on_ltb`
  (xfail-strict). LOW impact (graveyard-only field, CR 302.1
  battlefield-only state); closure direction is a 1-line Python or
  Rust edit. Closure agent in flight as of this writing.

Cross-engine deltas vs the 2026-05-11 snapshot:
- Open CE count: **1 (CE13) down from 4 in the prior snapshot** (CE4
  was in-flight at the time; CE5/CE6/CE7 were predicted; today
  CE5-CE12 are all closed and CE13 is the only new survivor).
- Open G count: **G8 + G12 + G19 + G24 = 4** (no net change in count,
  but G19 is now substrate-unblocked and a one-line slice — see §2).

### What's running cleanly end-of-day

- All single-color / two-color synthetic deckspecs through full
  multi-turn play with land drops + creature casts + combat.
- `multi_blocker_deckspec` with `multi_block_combat_selector`:
  **1000/1000 clean games** (CE9 closure).
- `multi_blocker_deckspec` with `retaliation_selector` (bilateral
  combat — both players attack on their own turns): **260 decisions
  clean** (CE12 closure).
- `mass_removal_selector`: 168 decisions clean (trips on CE13
  field-snapshot divergence at step 168 — the wrath fire itself).
- Shuffle-seed cross-engine smoke with `shared_rng_seed` (CE8 Slice
  1 substrate): byte-equal libraries across multiple seeds.

---

## 2. What's left

### Open G-gaps in `RUST_PARITY_GAPS.md`

| Gap | Description | Status post-CE8 | Slice scope | Priority |
|---|---|---|---|---|
| **G8** | +1/+1 and -1/-1 counters stored as net `i32`, cancel at write-time not SBA | unchanged — needs multi-kind counter map | medium | **low** (no pool cards ask the divergence question) |
| **G12** | Mutual KO is two sequential `lose_life` calls, not one atomic symmetric Effect | unchanged | small | **low** (observable end-state already matches) |
| **G19** | `SearchLibraryForBasicLandTapped` does not shuffle | **substrate now in place** — CE8 Slice 2 left the external-RNG plumbing wired into every shuffle pymethod. Closure is now a one-line Effect-arm edit calling `fisher_yates_shuffle_optional` post-search. | **small** (was medium) | **medium-high** — single-Effect-arm slice, biggest leverage of the open G items |
| **G24** | No scry-on-keep step after mulligan-to-7 (Paris rule) | unchanged | small (reuses PendingDecision substrate) | **low** (harness does not drive mulligan loops today) |

### Open CE-gaps

| CE | Description | Status | Closure scope |
|---|---|---|---|
| **CE13** | `summoning_sick` cleared on Rust LTB (DestroyAllCreatures); Python preserves the flag into graveyard | surfaced today; impact LOW (graveyard-only field, CR 302.1 has no semantics for it); strict-xfail pinned | 1-line edit, Python or Rust side; closure agent in flight |

### Substrate deferrals from prior slices (not closed today)

These continue to apply; today's CE closures did not touch them:

- **Defender-only target arms rewrite** (per the `bf-iter-resolve-arms`
  agent's documented follow-up — `2026-05-12-bf-iter-resolve-arms`
  worklog). The Destroy/Tap target arms for non-attached single-target
  forms (`DestroyTargetNonlandPermanent`, `DestroyTargetArtifact`,
  `DestroyTargetLand`, `TapTargetArtifactOrCreature` — ~6 sites) have
  a SEMANTIC divergence vs Python: Python's `TargetSpec` filter walks
  centralized bf across both players via ETB tie-break; Rust's target
  picker takes defender's first match. Pre-emptive ETB-iter agent's
  scope explicitly EXCLUDED these — they're a target-resolution
  rewrite, not an ETB tie-break. Fix scope: medium (Rust target picker
  widens to `bf_iter_etb_sorted` + filter; may shift first-slice
  deterministic baselines and need fingerprint rebake on dependent
  tests).
- **`spell_warped_this_turn` flag setter**. The bool field landed on
  `GameState` but no Rust production call site flips it yet (deferred
  from 2026-05-11). Without it, `Effect::ConditionalIfVoid` is shipped
  but not load-bearing for the 4 EoE Void cards. Fix scope: small
  (warp-cast cost path single-site). Priority: medium — only when a
  probe drives a Void card.
- **ManifestDread face-down state + count > 1 deferrals** (unchanged
  since 2026-05-11): face-down state needs either fingerprint
  baseline rebuild or sidecar field; count>1 is ~30 LoC. Priority:
  medium-low.
- **`Effect::EquipToTargetCreatureYouControl` `granted_keywords_ueot`
  rider** (Atomic Microsizer family always passes empty frozenset).
  Unchanged.
- **`Effect::LookAtTopNRevealOrCounter` "random order" tail** — now
  unblocked by CE8 substrate (external RNG is wired). One-Effect-arm
  rewire follow-up.

### High-frequency Effects still missing

Per `RUST_EFFECT_COVERAGE.md`, the only remaining freq>=10 class is:

| Python class | Frequency | Status |
|---|---:|---|
| `ModalChooseOne` | 13 | functionally shipped as `Effect::ChooseOneMode`; gated on `feature/coverage-overrides` PR merge to flip the orphan-map entry |

So freq >= 10 is **functionally complete**. The freq 2-9 tier is at
**52/53 (98.1%)** — the one remaining class is the lone freq-2 long-
tail miss; not load-bearing for the current cross-engine smoke.

### Singletons (freq 1)

Explicitly **out of Phase 5/6 scope** per `RUST_PARITY_PLAN.md`
"Phasing" §3 (161 classes, 5.6% covered). The 1000-game smoke uses a
"core-effects-only" pool that excludes them by construction.

---

## 3. Recommended closure sequence

Ordered by leverage. Today materially shortened this list by closing
the biggest substrate item (CE8 + G19 substrate) and the largest open
CE batch (CE5-CE12 all closed). The remaining items are mostly
one-slice closures plus the next probe extension.

1. **G19 closure (SearchLibraryForBasicLandTapped shuffle).** Now a
   one-line Effect-arm edit calling `fisher_yates_shuffle_optional`
   in the resolve arm; the external-RNG plumbing CE8 Slice 2 left
   behind makes this a 30-minute slice. **Closes**: G19 + the
   `LookAtTopNRevealOrCounter` "random order" first-slice deferral.

2. **Defender-only target arms rewrite.** The `DestroyTargetNonlandPermanent`
   / `DestroyTargetArtifact` / `DestroyTargetLand` /
   `TapTargetArtifactOrCreature` family widens from defender-only
   first-match to centralized `bf_iter_etb_sorted` + filter to match
   Python's `TargetSpec`. **Slice scope**: medium (semantic shift may
   rebase first-slice deterministic baselines on dependent tests).
   **Closes**: a documented follow-up from the bf-iter-resolve-arms
   slice (`2026-05-12-bf-iter-resolve-arms` worklog).

3. **`spell_warped_this_turn` flag setter.** Single-site addition on
   the warp-cast cost path. **Closes**: makes `Effect::ConditionalIfVoid`
   load-bearing for the 4 EoE Void cards.

4. **Continue Phase 5 probes — next combat keyword surface.** The
   probe-close-probe cadence is the win. Next surfaces to drive in
   priority order:
   - First-strike / double-strike (priority probe agent is in flight
     as of writing).
   - Deathtouch + trample assignment edge cases.
   - Lifelink interactions with simultaneous combat damage.
   - Counterspells (would need a Rust counter-target primitive — net
     new substrate, but likely small).
   Each probe is expected to surface one CE divergence; each closes
   in a small slice on top of the now-rich substrate.

5. **CE13 closure.** 1-line edit (Python's `turn.move_off_battlefield`
   adds the `obj.summoning_sick = False` clear, OR Rust's
   `Effect::DestroyAllCreatures` drops the clear). Impact LOW —
   noise-only divergence on a graveyard field — but pinning it
   removes the only open CE entry. Closure agent already in flight.

6. **ManifestDread face-down + count>1.** Unchanged scope. Priority
   medium-low.

7. **G24 Paris-scry-on-keep.** Unchanged. Priority low.

8. **G8 + G12.** Unchanged. Both low priority.

9. **`feature/coverage-overrides` PR merge.** User-gated. Flips
   `test_no_orphan_rust_variants` green and the coverage table reads
   the orphan-mapped variants correctly. Not blocking any closure.

**One-slice vs substrate-prep summary** (revised):

- One-slice closures: G19, CE13, `spell_warped` setter, ManifestDread
  count>1, coverage-overrides merge.
- Medium scope: defender-only target arms (semantic shift),
  ManifestDread face-down (substrate choice), G8 (multi-kind counter
  map).
- **No remaining substrate-prep blockers** — CE8 closure today
  retired the biggest one. RNG externalization is the prerequisite
  for G19 and the `LookAtTopNRevealOrCounter` deferral, and it is
  now in place.

---

## 4. What "ready to test" means concretely

The plan doc's target is **1000-game cross-engine smoke clean**.
Today is the inflection point on this estimate — CE8 was the largest
remaining architectural item and it closed in two slices.

Estimate evolution:
- 2026-05-11 morning: **80-85% remaining** (pre-CE2 closure).
- 2026-05-11 mid-day: **60-70%** (post-CE3 + multi-turn walk).
- 2026-05-11 end-of-day retro: **60-70%** (CE5 surfaced + 3 CEs
  pre-staged for next session).
- 2026-05-12 mid-day retro: **45-55%** (CE9 closed with 1000/1000
  clean multi-block, CE11 closed, CE12 surfaced + small).
- **End-of-day 2026-05-12: 30-40% remaining.**

**Rationale for 30-40%:**

1. CE8 (the biggest open architectural item) shipped — both slices
   merged to main + 17 tests_rust + 7 cross-engine smoke regression
   tests pin the closure. The cross-engine harness can now drive a
   shuffle-seeded scenario without a divergence at step 0.
2. CE9 closed with 1000/1000 clean multi-block combat — the first
   1000-game-clean signal in the project, on a real-content deck spec
   (multi_blocker_deckspec, not Forest + Bears synthetic).
3. CE10/CE11/CE12 all closed; the retaliation probe walks 260
   decisions of bilateral combat with summoning-sick clears + active-
   player swaps + multi-block damage + sticky winner accounting all
   matching Python.
4. Only CE13 remains open and it's LOW-impact + 1-line closure.
5. G19 went from "medium scope, requires substrate" to "30-minute
   one-line edit".
6. The remaining CE risks are concentrated in combat keywords
   (first-strike, deathtouch, trample, lifelink) and the trigger
   emitter substrate — areas with NO pre-emptive audit yet, so the
   probe-close cadence will drive their discovery.

**Velocity bound.** At today's rate (~3-4 CE / substrate closures per
session + 1-2 probe extensions), and assuming each new combat-keyword
surface yields ~1 CE divergence (mirror of today's rate), a reasonable
end-state estimate is **3-5 more sessions to 1000-game-ready**, down
from yesterday's 4-6 estimate. The main risks: (a) trigger-emitter
substrate is bigger than expected (currently no audit), and (b)
combat keyword interactions surface a layered-continuous-effect gap
that triggers a Phase 7+ refactor mid-Phase-5.

The remaining work is bounded, on a known curve, and now front-loaded
into single-slice closures plus probe extensions rather than substrate
rewrites.

---

## 5. Forward-looking items beyond Phase 5

Out of scope of Phase 5 and Phase 6 (unchanged from 2026-05-11):

- **The 161 singleton Effect classes** — explicitly excluded from
  the parity deck pool. The 1000-game smoke uses a "core-effects-only"
  pool by construction.
- **Layered continuous-effect cache** — Rust has no analog today.
  Per parity plan risks §3, missing layered logic for anthems /
  pump-UEOT / become-creature effects becomes a silent-wrong-answer
  source as those cards enter the pool. Layer 6 (lose all abilities)
  and Layer 7 (P/T) are the most common; Layer 1-5 rarer. UEOT
  modifiers get us partway but the full layer engine is Phase 7+.
- **Full combat damage assignment edge cases** — current Rust covers
  basics + multi-block (post-CE9). Real combat parity with first-
  strike, double-strike, deathtouch (damage-assignment-order edge
  cases), trample (excess-damage routing), and lifelink (simultaneous
  with combat damage on triggered abilities) are Phase 5 probe targets
  but the deep parity work (e.g. byte-identical 800-line Python
  combat-damage step) is Phase 7+.
- **Stack timing on multi-level trigger chains** — round 9 ETB
  covers simple cases; deep trigger-chain ordering may need careful
  Rust-side replay tests when the trigger emitter substrate lands.
  Phase 7+.

**Review queue**: `feature/coverage-overrides` PR (`2bcdd842`,
pushed 2026-05-11) remains unmerged. Required to flip
`test_no_orphan_rust_variants` green and have `RUST_EFFECT_COVERAGE.md`
read the 3 orphan-mapped variants (`ChooseOneMode`,
`GrantKeywordToTargetCreatureUntilEOT`, `SetBasePTUntilEOT`) as
covered. Not blocking any Phase 5 closure, but it's the persistent
pre-existing red on every Python gate.
