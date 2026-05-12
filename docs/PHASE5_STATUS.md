# Phase 5 status & closure roadmap

Snapshot date: 2026-05-11 (post-CE3 closure, CE4 closure in flight).

**Punchline.** Phase 5's cross-engine smoke harness is up and shipping
findings on a tight probe-close-probe cadence: today closed CE1 + CE2
+ CE3 and surfaced CE4 (battlefield ordering), with a parallel slice
in flight to close it. The Rust engine carries 77 Effect variants
covering 74.8% of per-card emissions on the EoE+stellar_sights+
special_guests_eoe+duskmourn pool; the harness walks a 3-card-kind
deck cleanly through turn 2 for the first time and trips on a single
single-root-cause divergence at step 28. After CE4 lands, the next
probe (creature spell + tap-for-mana under multi-turn play) is
expected to surface CE5 immediately. The hard blockers to a 1000-game
cross-engine smoke are no longer Effect-coverage gaps — they are
substrate gaps (RNG externalization, face-down state, multi-kind
counters) that each gate a slice of decision script the harness
currently can't drive.

---

## 1. Where we are

### Numbers

- **77 Rust `Effect` variants** in `rust/src/cards.rs`.
- **71 / 228 Python Effect classes covered (31.1%)** by class count.
- **516 / 690 per-card emissions covered (74.8%)** — the load-bearing
  weighted metric.
- **Frequency tiers** (`docs/RUST_EFFECT_COVERAGE.md`):
  - Freq ≥ 10 (head, 14 classes): **13 / 14 covered (92.9%)** — only
    `ModalChooseOne` shows as "no" in the table, but Rust ships
    `Effect::ChooseOneMode` (1:1 functional match); the entry flips
    once the `feature/coverage-overrides` PR merges the override map.
  - Freq 2-9 (mid, 53 classes): **49 / 53 covered (92.5%)**.
  - Freq 1 singletons (161 classes): **9 / 161 (5.6%)** — explicitly
    out of Phase 5/6 scope per `RUST_PARITY_PLAN.md` "Phasing" §3.
- **Rust test gate**: 1693 passing (was 1536 at start of session;
  ~+157 today across 12 slices).
- **Python test gate**: 9974 passed / 12 skipped / 2 xfailed
  (CE4 multi-turn-clean-walk + one pre-existing). One pre-existing
  red unrelated to Phase 5: `test_no_orphan_rust_variants`
  (3 orphans pending the unmerged `feature/coverage-overrides` PR).

### Parity plan status (`docs/RUST_PARITY_PLAN.md`)

| Phase | Status |
|---|---|
| 0 Engine primitives | done (r1-r19) |
| 1 Discovery + scaffold | done (r20) |
| 2 Externalize RNG + spec GameState API | done (r21) |
| 3 Action types + legal_decisions | done (r22-r25) |
| 4a Top-14 high-frequency Effects | **done modulo orphan-map merge** (13/14 shipped, `ModalChooseOne` → `Effect::ChooseOneMode` gated on `feature/coverage-overrides`) |
| 4b Mid-frequency Effects (next ~50) | **done modulo 4 singletons** (49/53 shipped) |
| **5 Per-step trajectory diff** | **in progress — inaugural harness slice landed r27; 3 CE divergences surfaced + closed today, CE4 in flight** |
| 6 Scale to 1000 games | not started |

### Cross-engine divergence cadence (today)

Today closed **3 CE divergences** and surfaced **1 new** in the
probe-close-probe loop. Each surfaced from a harness extension; each
closed with a single-feature-branch slice.

- **CE1** (round-28): `summoning_sick` default — closed. Rust
  `make_state` now defaults `summoning_sick=true` on library/hand
  objects to match Python.
- **CE2** (round-28): `apply_action(PassPriority)` — closed. Rust's
  arm is now a TRUE no-op matching Python's `return` statement;
  priority management flows through the `pass_priority` primitive
  and `complete_step_via_priority_round` composer instead.
- **CE3** (today): library pop-orientation — closed. Rust now treats
  `lib[0]` as deck-top across every library mutator (draw, mill,
  surveil, search, manifest, etc., per the closure entry in
  `RUST_PARITY_GAPS.md`).
- **CE4** (today): battlefield ordering — Python centralizes
  `state.battlefield` in ETB-timestamp order; Rust's
  `state_ops_snapshot.rs::battlefield_snapshot` (line 179) flat-emits
  p0's then p1's per-player Vec. **Closure in flight** (parallel
  agent on `feature/ce4-bf-etb-order`). Plan: option (2) per the gap
  doc — stamp `etb_timestamp: u32` on each `GameObject`, sort
  `battlefield_snapshot`'s output by it.

### What's running cleanly

- `tiny_synthetic_deckspec` (Forest + Bears, single-color, no
  shuffle, no play) — 50+ PassPriority decisions, fully clean since
  CE1 + CE2 closed.
- `slightly_bigger_deckspec` (Forest + Mountain + Bears, two-color,
  asymmetric 4-card libraries) — 200 PassPriority decisions, fully
  clean.
- `play_a_land_selector` on the tiny + slightly_bigger specs — 50
  decisions with a side-channel draw + land-drop, fully clean since
  CE3 closed.
- `multi_turn_selector` on slightly_bigger — clean for 28 decisions
  (full Turn 1 untap → cleanup with the CR 103.7c first-turn
  draw-skip, the CR 504.1 turn-2 DRAW step firing for p1, the CLEANUP
  → UNTAP wrap with turn bump + active-player swap + priority reset
  per CR 117.1a, full Turn 2 combat-phase advance with no creatures,
  Turn 2 MAIN1 land drop for p1), trips on step 28 = CE4.

---

## 2. What's left

### Open G-gaps in `RUST_PARITY_GAPS.md`

These are Rust-internal divergences from CR / Python documented as
"Confirmed gaps" (not the cross-engine CE-prefixed entries).

| Gap | Description | What blocks closure | Slice scope | Priority |
|---|---|---|---|---|
| **G8** | `+1/+1` and `-1/-1` counters stored as net `i32`, cancel at write-time not SBA | needs multi-kind counter map; per-object scalar must become a `HashMap<CounterKind, i32>` | medium — multi-site read API update + new SBA cancel-pair pass | **low** — observable only on cards that ask "how many +1/+1 counters" (none in current pool; not surfaced by current smoke) |
| **G12** | Mutual KO is two sequential `lose_life` calls, not one atomic symmetric Effect | symmetric-Effect machinery doesn't exist | small — `Effect::PlayersLoseLifeBothAtOnce` arm | **low** — observable end-state (`is_draw`) already matches |
| **G19** | `SearchLibraryForBasicLandTapped` does not shuffle | pending RNG externalization (RUST_PARITY_PLAN §"Decision 1" — recommended option b) | medium — refactor the resolve arm to accept an external RNG, change every search-Effect site | **medium-high** — visible the moment a probe casts a card that searches; blocks any decision script that fetches a land |
| **G24** | No scry-on-keep step after mulligan-to-7 (Paris rule) | pending Paris-rule decision-callback slice | small once pending-decisions substrate is reused — `PendingDecision::ScryOnKeep` variant + `mulligan_atomic` hook | **low** — visible only if the parity harness drives mulligan loops; current smoke does not |

(No CE entries open — CE1-CE3 closed today; CE4 closure in flight as
of writing.)

### Substrate deferrals from today's slices

These are first-slice scope cuts that landed via documented
`SEARCH_LIMITATIONS.md` entries rather than full closures. Each is
load-bearing once a probe drives the affected card path.

- **ManifestDread face-down state** (`SEARCH_LIMITATIONS.md` §
  "Rust port — `Effect::ManifestDread` face-down state + count > 1
  deferred"). Manifested permanents land on the battlefield with
  their original printing visible — CR 701.34 / 707.2 say face-down
  2/2 vanilla. Fix scope: medium (a) `face_down: bool` on
  `GameObject` + bake into effective-P/T / effective-keyword /
  effective-types readers + fingerprint baseline rebuild, OR
  (b) face-down placeholder printing + `manifested_from_printing_id`
  sidecar. Priority: **medium** when ManifestDread cards become
  common in trained decks.
- **ManifestDread count > 1** (same entry). Slimy Aquarium /
  Weight Room / Valgavoth's Onslaught raise `ValueError` at resolve
  time today. Fix scope: small (~30 LoC — loop the resolve arm
  `count` times OR carry `remaining_iters: u32` on the PendingDecision).
  Priority: **low** (handful of cards in EoE).
- **ConditionalIfVoid void-tracking call sites**. The
  `permanent_left_battlefield_this_turn` and `spell_warped_this_turn`
  bool fields landed on `GameState` but no Rust production call site
  flips them yet — the predicate always evaluates to false and the
  else-branch always fires. Fix scope: small per call-site, but
  multiple sites needed: LTB-tracking at every zone-change site
  that targets battlefield→graveyard / exile / hand / library;
  warp-tracking on the cast pathway. Priority: **medium** — without
  these, `Effect::ConditionalIfVoid` is shipped but not load-bearing
  for any real card path until the production engine flips the flags.
- **`Effect::EquipToTargetCreatureYouControl` first-slice drops the
  `granted_keywords_ueot` rider** (Atomic Microsizer family always
  passes empty frozenset). No equip-cost mana payment — separate from
  the Effect-resolve layer; non-mana activated-ability dispatch will
  route here when it lands.
- **`Effect::LookAtTopNRevealOrCounter` "random order" tail
  simplifies to deterministic popped-order** — real MTG asks for
  random; deferred pending RNG externalization (related to G19).
- **`Effect::IfYouDo` first-slice "looter" shape** — general
  do_actions that can signal failure (e.g. `SacrificeACreature`
  returning False on empty bf) deferred; would require `apply_effect`
  to return `Result<bool>` so the arm can branch on do_action's
  success.

### Other items already in `SEARCH_LIMITATIONS.md`

Pre-Phase 5 items that still apply and would gate parts of a
1000-game smoke once the probe walks into them:

- §1 Combat damage assignment is ordered (outdated CR).
- §15 SearchLibraryForBasicLandTapped: no shuffle + supertypes-proxy
  filter (= G19).
- Rust-port `legal_decisions` ActivateAbility approximated to mana
  producers — any activated-ability beyond `{T}: add {mana}` is
  out-of-scope for `legal_decisions`. A probe that drives an
  activated equip cost will not see the equip Action in Rust's
  legal_decisions list.

### High-frequency Effects still missing

Per `RUST_EFFECT_COVERAGE.md` "High-frequency Python classes NOT yet
in Rust", the only remaining ≥10-frequency class is:

| Python class | Frequency | Status |
|---|---:|---|
| `ModalChooseOne` | 13 | functionally shipped as `Effect::ChooseOneMode`; gated on `feature/coverage-overrides` PR merge to flip orphan-map entry |

So freq ≥ 10 is **functionally complete** for the EoE+adjacent
pool. The next-best ports are all freq 2-9.

### Mid-frequency (2-9 tier) remaining gaps

Per the freq 2-9 table, 4 of 53 classes remain unported. None are
load-bearing for the current cross-engine smoke (which uses tiny
core-only deckspecs); they only become priority once the parity deck
pool grows past Forest / Mountain / Bears / a small handful of
spells. The cadence of the last two days suggests 2-3 of these can
ship per session as substrate-reuse slices on the existing
PendingDecision / UeotModifier scaffolding.

---

## 3. Recommended closure sequence

Ordered by "what unblocks the next probe slice the most", preserving
the probe-close-probe cadence that's been highly productive.

1. **CE4 closure** (in flight, parallel agent). **Single-slice closure.**
   Adds `etb_timestamp: u32` to `GameObject`, stamps it on every
   ETB site (`move_from_hand_to_battlefield`, `state_ops_resolve.rs`
   ETB pathways, `register_and_inject_object`), sorts
   `battlefield_snapshot`'s output by it. **Unblocks**: multi-turn
   smoke past step 28; lets the next probe extend either decision
   script (creature spell + tap-for-mana) or deck (3rd card kind +
   non-basic-land).

2. **Next probe slice: creature spell + tap-for-mana under
   multi_turn_selector.** Extends `multi_turn_selector` to detect
   when a Land is tappable on the active player's main + cast a
   creature spell (Grizzly Bears) when sufficient mana is available.
   **Unblocks**: surfaces the next CE divergence — predicted in the
   2026-05-11 multi-turn worklog as "likely CE5 around tap-for-mana
   parity or summoning-sick timing under multi-turn play". **Slice
   scope**: small — adds a new selector helper + 2-3 tests; no
   substrate changes. The whole point is to *find* the next gap, not
   close one.

3. **G19 closure (SearchLibraryForBasicLandTapped shuffle).**
   Substrate prep: pull the RNG out of `state.rng` into an external
   `&mut dyn RngStream` parameter on `apply_effect` per
   RUST_PARITY_PLAN Decision 1 option (b). Today this only matters
   when a probe casts a search-the-library card — but it's a
   widening blocker: any closure of a high-frequency
   library-searching card depends on it. **Slice scope**: medium —
   16 RNG call sites today (per parity plan headline), but they're
   concentrated. **Closes**: G19 + the LookAtTopNRevealOrCounter
   "random order" first-slice deferral.

4. **Void-tracking production call sites.** Flip
   `permanent_left_battlefield_this_turn` on every Rust
   zone-change-from-battlefield site (destroy, sacrifice, exile,
   bounce, return-to-hand). Flip `spell_warped_this_turn` on the
   warp-cast cost path once it lands (not yet in Rust). **Slice
   scope**: small per call-site, ~5-8 sites total. **Closes**:
   makes `Effect::ConditionalIfVoid` load-bearing for the 4 EoE
   "Void —" cards (Decode Transmissions / Hymn of the Faller
   family). Without this, those cards always fall through to the
   else-branch in Rust, silently diverging from Python.

5. **`feature/coverage-overrides` PR merge.** Not a code slice — it
   merges the orphan-map override table so
   `test_no_orphan_rust_variants` flips green and `ModalChooseOne`
   reads as covered. **Unblocks**: a clean coverage table and one
   less pre-existing red on every gate. Already on review.

6. **ManifestDread face-down + count>1 closure.** Two follow-up
   slices, both deferred today. Face-down is medium-scope
   (fingerprint baseline rebuild OR sidecar field with CR 400.7
   reset semantics); count>1 is ~30 LoC. **Priority**: medium-low
   — only the 10 ManifestDread EoE cards see this, and the
   strategic bias washes out in self-play.

7. **G24 Paris-scry-on-keep slice.** Reuses the PendingDecision
   substrate. **Slice scope**: small. **Priority**: low — only fires
   if the harness drives mulligan loops.

8. **G8 + G12** — both low priority. G8 only surfaces on cards that
   ask "how many +1/+1 counters" (none currently in the pool); G12
   is observably parity-equal at end-state today.

**One-slice vs substrate-prep summary**:

- One-slice closures: CE4, G24, void-tracking, ManifestDread count>1,
  coverage-overrides merge.
- Substrate-prep needed: G19 (RNG externalization), ManifestDread
  face-down (either fingerprint rebuild or sidecar field with reset
  semantics), G8 (multi-kind counter map).

---

## 4. What "ready to test" means concretely

The plan doc's target is **1000-game cross-engine smoke clean**. To
get there from here, the harness needs (in rough dependency order):

1. CE4 closed (multi-turn unblocked) — **1 slice in flight today**.
2. A non-trivial decision-script selector that drives at least one
   creature cast + combat + damage — **1-2 probe slices**, each
   likely surfacing CE5, CE6.
3. Each CE divergence surfaced gets a closure slice — **N slices
   where N = the count of CE entries the harness surfaces between
   here and 1000-game clean**. Based on the rate-of-discovery in
   today's slices (3 surfaced + 3 closed in 1 session), and the fact
   that the harness is still on a 3-card-kind deck, a reasonable
   rough estimate is **5-15 more CE divergences** before the
   harness can drive a generic EoE deck cleanly.
4. RNG externalization (G19) — **1 substrate slice**, but it's
   load-bearing for any probe that touches search.
5. Then scale: extend the deck pool from
   `slightly_bigger_deckspec` to a core-effects-only EoE subset (the
   plan's "core deck pool" — top-14 effects + vanilla creatures +
   lands), and run the harness on N seeds.

**Today's velocity**: 12 slices in one session covering 9 new
Effect variants, 1 deck-spec expansion, 2 decision-script extensions,
and 3 CE closures. If each future slice closes one gap OR extends the
harness by one increment, a rough order-of-magnitude estimate is
**40-80 slices to 1000-game ready** — call it **2-4 weeks of
sessions at today's pace**, contingent on RNG externalization
landing cleanly and no architectural surprises in combat or
trigger-stack timing (parity plan risks §3 and §4 + §5).

This is a rough-order-of-magnitude estimate; the value is in
recognizing that the remaining work is bounded and on a known
curve, not infinite.

---

## 5. Forward-looking items beyond Phase 5

Out of scope of Phase 5 and Phase 6:

- **The 161 singleton Effect classes** — explicitly excluded from
  the parity deck pool per RUST_PARITY_PLAN.md "Phasing" §3. These
  are entire card behaviors, not generic effects; each is its own
  port problem. The 1000-game smoke uses a "core-effects-only" pool
  that excludes them by construction.
- **Layered continuous-effect cache** — Rust has no analog today.
  Per parity plan risks §3, missing layered logic for anthems / pump
  UEOT / become-creature effects becomes a silent-wrong-answer
  source as those cards enter the pool. Layer 6 (lose all abilities)
  and Layer 7 (P/T) are the most common; Layer 1-5 rarer. UEOT
  modifiers (I23) get us partway but the full layer engine is
  Phase 7+.
- **Full combat damage assignment** — current Rust covers basics
  (rounds 5/8/9/10/13/15) but Python combat is 800+ lines with
  first-strike + double-strike + deathtouch + lifelink + trample
  interactions that may not be byte-identical. Real combat parity
  is Phase 7+.
- **Stack timing on multi-level trigger chains** — round 9 ETB
  covers simple cases; deep trigger-chain ordering may need
  careful Rust-side replay tests. Phase 7+.

**Review queue**: `feature/coverage-overrides` PR sits unmerged
(2bcdd842, pushed 2026-05-11). Required to flip
`test_no_orphan_rust_variants` green and have
`RUST_EFFECT_COVERAGE.md` correctly report `ModalChooseOne` as
covered via the `ChooseOneMode → ModalChooseOne` rename in
`scripts/measure_effect_coverage.py::RUST_TO_PYTHON_OVERRIDES`. Not
blocking any Phase 5 closure work, but it's the one persistent
pre-existing red on every Python gate.
