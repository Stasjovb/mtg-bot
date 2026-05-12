# Session retrospective — 2026-05-11

Synthesis of today's mtg-bot Rust-port + Phase 5 session. Builds on
`docs/PHASE5_STATUS.md` (`5907b205`); does not duplicate it. The
underlying audits live in `docs/ORDER_SENSITIVE_SURFACES.md`
(`1be3e0c4`), `docs/RUST_BF_ITERATION_AUDIT.md` (`d1239fc3`), and
`docs/CE5_CE6_CE7_CLOSURE_PLAYBOOK.md` (`2a7221b1`).

## 1. Headline

The cross-engine smoke walked from **zero multi-turn decisions** to
**clean through turn 9 / step 107**, with CE5 surfacing on the very
next step (the cast). Four cross-engine divergences closed in one
session (CE1 carried in from r28; CE2 + CE3 + CE4 closed today); a
fifth (CE5: cast-vs-resolve) surfaced and was pinned strict-xfail. The
biggest concrete win was the **probe-close-probe cadence**: each
harness extension surfaced exactly one new divergence; each
divergence closed with a single feature-branch slice. Today shipped
**62 commits** (8 docs + ~26 Rust Effect slices + 4 CE closures + the
runs-db / training-UI subsystem work), put **77 Effect variants**
into Rust (covering **74.8%** of per-card emissions on the
EoE+adjacent pool), grew the Rust gate from **1536 -> 1693 passes
(+157)**, and pre-staged the CE5 / CE6 / CE7 closure playbook so the
next session can run the cadence cold.

## 2. Slices shipped on origin/main

Sort: newest-first. Impact = HIGH means it unblocked a probe or
closed a confirmed parity gap; MED = first-slice Effect variant or
infra; LOW = doc / cleanup.

| Commit | Slice | Shipped | Impact |
|---|---|---|---|
| `00f55347` | docs(ce5) playbook divergence note | doc | LOW |
| `87ac8bd8` | parity cast_bears_selector | **probe — surfaces CE5** | HIGH |
| `1673e582` | rust(draw-card-inline-flag) | CE follow-up: closes draw_card inline-vs-pymethod asymmetry | HIGH |
| `e1989b8b` | docs(ce-closure-playbook) | CE5/CE6/CE7 closure plan | HIGH (unblocks next session cold) |
| `9513b961` | docs(rust-bf-iteration-audit) | enumerates 37 bf-iteration sites | HIGH |
| `c4dd5d5a` | test(parity-smoke) edge cases | probe — surfaces CE-pure-derivation-is_over + CE-shuffle-PRNG | HIGH |
| `d04cb3de` | rust(ce4-bf-etb-order) | **closes CE4** (battlefield ETB ordering) | HIGH |
| `8c018cee` | docs(order-semantics-audit) | enumerates 12 order-sensitive surfaces + ranks CE5-CE9 | HIGH |
| `d8409188` | docs(phase5-status) | Phase 5 status + closure roadmap | MED |
| `9bb91c4c` | parity multi_turn_selector | probe — surfaces CE4 | HIGH |
| `5a345f6d` | rust(ce3-library-pop) | **closes CE3** (library orientation) | HIGH |
| `72865ee7` | parity play_a_land_selector | probe — surfaces CE3 | HIGH |
| `a839fc07` | runs(client+serve) pid/host plumbing | infra | MED |
| `00df33e8` | runs(db) schema additions | infra (pid/host/training_history/last_progress_at/stop_requested) | MED |
| `869b1785` | watcher tests for db/rest read paths | infra | MED |
| `1d80c7ae` | watcher db+rest read transports | infra (eval_early_stop_watcher migration to runs.db) | MED |
| `b735831c` | training_ui force_kill edge tests | infra | LOW |
| `a4ec87f3` | parity slightly_bigger_deckspec | probe — clean walk after CE2 landed mid-flight | MED |
| `87a2d662` | rust ce2-pass-priority | **closes CE2** (PassPriority no-op) | HIGH |
| `6c7b506e` | training_ui Force Kill button + modal | infra | LOW |
| `428ee6f2` | training_ui POST `/api/runs/<id>/force_kill` | infra | LOW |
| `49edb15f` | rust(effect-manifest-attach) | Effect variant: ManifestDreadThenAttachSelf (3 EoE cards) | MED |
| `6e2ee538` | docs RUST_EFFECT_COVERAGE refresh | doc | LOW |
| `d5d84631` | rust(effect-become-land-creature-ueot) | Effect variant: manland animation (13 cards) | MED |
| `40117a29` | rust(effect-look-at-top-n-reveal-or-counter) | Effect variant: Living-Phone family | MED |
| `a1edd0c8` | rust(effect-damage-opp-creature) | Effect variant: DealDamageToOpponentCreature | MED |
| `de4a578c` | rust(effect-conditional-if-void) | Effect variant: ConditionalIfVoid (4 cards, void-tracking sites deferred) | MED |
| `e1a235d7` | rust(effect-manifest-dread) | Effect variant: ManifestDread first-slice (10 cards, face-down + count>1 deferred) | MED |
| `d2c610dd` | rust(effect-equip-to-target-creature) | Effect variant: CR 702.6 equip activation (14 cards) | MED |
| `c71d03be` | rust(effect-set-base-pt-ueot) | Effect variant: CR 613.4 layer 7b override | MED |
| `1c89ccdb` | training_ui mobile-responsive layout | infra | LOW |
| `187f4cd8` | rust(effect-return-all-creatures-grave-to-bf) | Effect variant: mass reanimation | MED |
| `d1b4efdb` | rust(effect-tap-another-target-creature) | Effect variant (predicted CE7 site) | MED |
| `8dc7e91c` | rust(effect-untap-target-other-permanent) | Effect variant (predicted CE7 site) | MED |
| `1ad069ad` | rust(effect-grant-keyword-target-ueot) | Effect variant: keyword-agnostic UEOT grant | MED |
| `8e6dc1a6` | rust(effect-each-opponent-sacrifices-creature) | Effect variant | MED |
| `5d0b61a6` | rust(effect-pump-target-artifact-or-creature) | Effect variant: broader-filter UEOT pump | MED |
| `95ba673f` | rust(effect-each-opponent-mills) | Effect variant | MED |
| `a29df33a` | rust(effect-if-you-do) | Effect variant: IfYouDo wrapper + IfYouDoChoice (5th decision-callback variant) | MED |
| `baaafdb6` | rust(effect-choose-one-mode) | Effect variant: ChooseOneMode + ChooseModeChoice (ModalChooseOne 1:1) | MED |
| `995e7cb3` | rust(effect-look-top-n-one-to-hand) | Effect variant: Commune-with-Evil family + PickCardFromExaminedChoice | MED |
| `aab3a685` | rust(decision-callback-may-do) | Effect variant: MayDo + MayDoChoice | MED |
| `040e7cd4` | rust(effect-exile-opps-nonland-until-leaves) | Effect variant: broader until-leaves | MED |
| `052ac1b5` | rust(until-leaves-foundation) | substrate: `exiled_with_source` + `return_paired_exiles_for` | MED |
| `0992daae` | rust(effect-tap-enchanted-permanent) | Effect variant: aura tap | MED |
| `ecbf415f` | rust(effect-destroy-enchanted-permanent) | Effect variant: aura destroy | MED |
| `c5c75f6a` | rust(effect-attach-to-target-creature) | Effect variant: attach foundation + ETB attach (5 cards) | MED |
| `74c89072` | rust Effect::OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary | Effect variant (r28, 2 cards) | MED |
| `c45e7b1f` | shm-eval-server chunking + deadlock fix | infra (PR #52) | MED |
| `e0df5b72` | rust(effect-optional-sac-artifact) | Effect variant: Lithobraking sac-for-rider | MED |
| `00da84ab` | rust(effect-create-token-copy) | Effect variant: Mirrorpool token copy | MED |
| `6ec77990` | rust(effect-put-charge-counters-on-self) | Effect variant: Blast-Zone shape | MED |
| `105926a1` | auto_device Mac CPU (PR #51) | infra: no MPS on Mac (1.9-15x slower than CPU) | MED |
| `8917cfdd` | rust(effect-plus1-up-to-n) | Effect variant | MED |
| `ce8720cd` | rust(effect-conditional-tapped-creatures) | Effect variant: intervening-if | MED |
| `53b06252` | rust(effect-tap-artifact-or-creature) | Effect variant: broader-filter tap | MED |
| `32a8bdd2` | rust(effect-deal-damage-eq-source-power) | Effect variant: power-scaling damage | MED |
| `273639f3` | rust(effect-move-self-counters) | Effect variant: Dockworker counter transfer | MED |
| `804d9f21` | auto_device MPS is_built() guard (PR #50) | infra | LOW |
| `74ea4656` | rust(effect-put-card-from-gy-bottom-library) | Effect variant: Chrome Companion shape | MED |
| `e36b6173` | rust(effect-pump-creatures-opponents-control-ueot) | Effect variant: debuff anthem | MED |
| `9f001886` | rust(effect-search-library-for-card) | Effect variant: generalized library tutor (9 cards) | MED |
| `63625823` | rust(effect-add-n-mana-chosen-color) | Effect variant: Lotus-Field shape | MED |
| `4fd760c1` | rust(effect-plus1-target-creature-you-control) | Effect variant: Rayblade-Trooper +1/+1 | MED |

**Total: 62 non-merge commits on origin/main.** Of those, **4 are CE
closures**, **5 are HIGH-impact probes / docs that unblocked the
next slice**, **~26 are first-slice Effect variants**, and the
remainder are infra (training-UI / runs-db / shm-eval / auto_device).

## 3. Open xfail / pending findings on main

### `tests/test_parity_smoke.py`

| Test | Reason | Closure path | Doc entry |
|---|---|---|---|
| `test_cross_engine_cast_bears_selector_walks_clean` (strict-xfail) | **CE5** — Rust `cast_creature` fuses cast+resolve; Python pushes StackItem and defers | (a) grow Rust stack-and-priority OR (b) harness-side `resolve_top_of_stack` mirror after each `cast_spell` | `RUST_PARITY_GAPS.md` CE5 (line 1085) |

Other xfails in this file are the CE1-CE4 companion symptom-pins
that were inverted in their closure pairs; nothing else open.

### `tests/test_parity_smoke_edge_cases.py`

| Test | Reason | Closure path | Doc entry |
|---|---|---|---|
| `test_cross_engine_empty_library_side_channel_draw_walks_clean` (strict-xfail) | **CE-pure-derivation-is_over** — Rust derives `is_over` eagerly from `has_lost ‖ attempted_draw_on_empty ‖ life<=0`; Python's `is_over` reads `winner_id` written only by SBA | (a) Python grows pure-derivation `is_over`, (b) harness fires SBAs between steps, OR (c) mark `is_over` / `winner_id` known-gap fields | informal in test docstring; **needs CE\<n\> entry** |
| `test_cross_engine_single_card_libraries_multi_turn_walks_clean` (strict-xfail) | Same CE-pure-derivation-is_over, surfaced via multi_turn auto-draw path after `feature/draw-card-inline-flag` closed the inline-vs-pymethod sub-finding (`1673e582`) | same as above | same |
| `test_cross_engine_shuffle_seed_walks_clean` (strict-xfail) | **CE-shuffle-prng-mismatch** — Python uses Mersenne Twister, Rust uses xorshift64; same seed -> different permutation | RNG externalization (RUST_PARITY_PLAN Decision 1, option b); also closes G19 | informal in test docstring; **needs CE\<n\> entry** |

### `tests_rust/`

Pre-existing `test_no_orphan_rust_variants` red — 3 orphans pending
the unmerged `feature/coverage-overrides` PR (`2bcdd842`). Not a
parity gap; orphan-map override merge flips it green.

## 4. CE entries — open vs closed

| CE | Status | Site | Closure / surfacing commit |
|---|---|---|---|
| CE1 | CLOSED (r28) | `summoning_sick` default on library/hand objects | pre-today |
| CE2 | CLOSED today | `apply_action(PassPriority)` no-op matching Python | `87a2d662` (merge `66291190`) |
| CE3 | CLOSED today | library orientation: `lib[0]` = top across every mutator | `5a345f6d` (merge `eb9ec57f`) |
| CE4 | CLOSED today | `battlefield_snapshot` ordered by `etb_timestamp` | `d04cb3de` (merge `276d806a`) |
| CE5 | **OPEN — surfaced today** | `cast_creature` fuses cast+resolve; no stack push | surfaced `87ac8bd8`; pinned in `RUST_PARITY_GAPS.md` line 1085 |
| CE6 | predicted, not yet surfaced | combat damage assignment (multi-block: Python walks battlefield-filter-by-`blocked_by`, Rust walks `self.blockers` push order) | needs combat in the probe — playbook §3 |
| CE7 | predicted, not yet surfaced | cross-player find-first arms (`TapAnotherTargetCreature` / `UntapTargetOtherPermanent`) | playbook §4 |
| CE8 | predicted, not yet surfaced | trigger emitter — when Rust grows `dispatch_event`, iteration order must mirror Python | playbook §5 (depends on CE5-SBA-collection landing first) |
| CE9 | predicted, low priority | `_play_land` `etb_timestamp` asymmetry (cosmetic until snapshot exposes the field) | playbook §5 |

**Informal findings from edge-case hardening that need formal CE
numbering** (kept out of `RUST_PARITY_GAPS.md` today to avoid
collision with the parallel CE4 closure agent editing the same
file). My recommendation:

| Proposed CE\<n\> | Finding | Source |
|---|---|---|
| **CE10** | `CE-pure-derivation-is_over` | `test_parity_smoke_edge_cases.py` lines 67-120; reinforced by `feature/draw-card-inline-flag` (`1673e582`) |
| **CE11** | `CE-draw_card-inline-vs-pymethod-asymmetry` (**CLOSED** today `1673e582`) — log it for completeness as a closed entry so the closure pair is preserved | worklog `2026-05-11-draw-card-inline-flag` |
| **CE12** | `CE-shuffle-prng-mismatch` | `test_parity_smoke_edge_cases.py` lines 392-454; also G19 |

Playbook caveat: the playbook (merged `2a7221b1`, pre-staged before
the cast-bears probe landed) predicted CE5 would be the SBA
victim-collection divergence. The cast-bears probe surfaced CE5 as
the cast-vs-resolve gap FIRST — see the `RUST_PARITY_GAPS.md`
"Note on playbook divergence" block (added in `00f55347`). The
playbook's planned "CE5 closure — SBA victim collection" should be
re-labeled CE6 when its slice runs; CE6 (damage) → CE7 and CE7
(target picks) → CE8 with corresponding bumps. The playbook's
`bf_iter_etb_sorted` helper proposal stays valid; only the numbering
shifts.

## 5. Top 3 priorities for the NEXT session

These are my picks; rationale follows each.

### Priority 1 — Close CE5 (cast-vs-resolve) via Option (b) harness-side mirror

**What.** Add a Python-side mirror after every `cast_spell` action
dict: call `resolve_top_of_stack(py_state)` so Python's stack drains
to match Rust's empty stack and the resolved permanent lands on
Python's bf. Mirrors the multi-turn slice's `advance_phase_python`
pattern (`src/mtg_bot/parity/cross_engine.py`).

**Pointers.** `docs/RUST_PARITY_GAPS.md` CE5 "Closeable" option 2
(lines 1166-1177); `src/mtg_bot/parity/cross_engine.py` for the
mirror; `tests/test_parity_smoke.py:1497-1554` for the strict-xfail
to flip and the symptom-pin to remove.

**Scope.** Small (~30 LoC harness mirror + flip strict-xfail to
xpass + remove companion symptom-pin per closure-pair contract).

**Why.** It's the smallest closure slice, follows the established
probe-close-probe cadence (CE1-CE4 each closed in one feature
branch), and unblocks the next probe (creature combat) which surfaces
CE6. Option (a) — grow Rust a real stack-and-priority surface — is
the long-term correct shape but is a Phase 7+ refactor; doing it
now would stall the probe cadence. **Judgment call**: I'm
recommending the harness-side mirror over the architectural fix
because the cadence is the win.

### Priority 2 — Close `CE-pure-derivation-is_over` (now blocks 2 tests)

**What.** Either teach the harness to fire `apply_sbas_until_quiescent`
on Python between steps (matches Rust's eager derivation), or
formally mark `is_over` / `winner_id` as known-gap fields the parity
field view ignores until both sides agree on derivation.

**Pointers.** `tests/test_parity_smoke_edge_cases.py:67-120` (the
empty-library variant) AND `:299-377` (the multi-turn auto-draw
variant — strict-xfailed today by `feature/draw-card-inline-flag`,
`1673e582`). Worklog entry `2026-05-11-draw-card-inline-flag` notes
this is now the open finding after the inline-vs-pymethod asymmetry
closed.

**Scope.** Small if the harness fires SBAs (~10 LoC walk-loop edit),
medium if you teach `parity/cross_engine.py` field-view normalizer
to skip `is_over` / `winner_id` under a known-gap flag (need to
preserve the symptom-pin shape).

**Why.** It's the single divergence pinning 2 xfailed tests; closing
it cleans up the edge-case suite and reveals what (if anything) hides
behind it. It's also the natural follow-up to today's
`feature/draw-card-inline-flag` slice which surfaced this finding as
the next open question.

### Priority 3 — File the informal CE findings as formal CE entries (CE10 / CE11 / CE12)

**What.** Edit `docs/RUST_PARITY_GAPS.md` to add 3 entries mirroring
the CE1-CE4 format: `CE10` (pure-derivation-is_over), `CE11` (the
now-CLOSED draw_card inline-vs-pymethod, for the closed-pair
record), `CE12` (shuffle-prng-mismatch / G19 cross-link).

**Pointers.** Same file. Each entry: short name, pinning test, Rust
today, CR / Python expected, parity impact, closeable plan.

**Scope.** Small (~30-60 lines doc-only).

**Why.** The cadence works because every divergence is enumerated in
one place; informal-in-test-docstring findings break the operator
workflow described at `RUST_PARITY_GAPS.md` lines 24-34 (smoke
diverges -> operator scans this doc -> known vs new). Three open
findings sit outside that workflow today.

### Honorable mentions (deliberately not picked)

- **CE6 closure (playbook section 3)**: not yet surfaced by any
  probe; closing it speculatively breaks the probe-close-probe rule
  ("the new code is right; parity failures find the bugs"). Wait
  until a combat-driving probe surfaces it.
- **RNG externalization / G19**: substrate-prep, gates CE12 closure
  and many search-library Effects. Too big for a single session if
  done right.
- **Void-tracking call sites for `ConditionalIfVoid`**: small but
  load-bearing-only-for-4-EoE-cards; lower visible payoff than the
  above three.
- **Extend cross-engine smoke to drive combat** (declares /
  blockers / damage): excellent next-probe target — would surface
  CE6 immediately — but Priority 1 (close CE5) must land first; the
  cast-bears probe currently aborts at step 108 so combat can't be
  reached.
- **Coverage-overrides PR merge** (`2bcdd842`): user-gated; one-line
  pre-existing red. Worth doing but the user's decision, not the
  agent's.

## 6. Lessons learned

**What worked.** The **probe-close-probe cadence** was the headline
win: every harness extension surfaced exactly one new divergence,
and every divergence closed with a single-slice feature branch. CE3
and CE4 each closed within ~30 minutes of being surfaced; CE5 was
pre-staged for the same shape. **Pre-staged audit + playbook docs**
(`ORDER_SENSITIVE_SURFACES.md` and `RUST_BF_ITERATION_AUDIT.md` and
`CE5_CE6_CE7_CLOSURE_PLAYBOOK.md`) added ~3 hours of synthesis work
but explicitly bought the next session the ability to start CE5/CE6/CE7
closure cold without re-deriving the file:line maps. **Auto-merge
cadence** on doc-only and small-slice work kept origin/main moving
without review-loop overhead; the only friction was the
coverage-overrides PR sitting unmerged all day.

**What hit friction.** **3-parallel Rust slices early in the day
produced merge thrash** (regex-mangled file content during one
auto-merge, `.pyd` clobbers between concurrent builds). The shift
mid-session to **"1 Rust slice + 2 non-Rust workers" (typically
docs + Python tests + training-UI)** was the right call and held for
the rest of the day. The strict no-go list in subsequent task briefs
(reserving specific files for the in-flight agent) was an additional
guard. The **coverage-overrides PR sitting unmerged** confused
several agents — `test_no_orphan_rust_variants` reported 3 reds that
looked like new gaps every time a worker re-ran the full Python gate;
the task brief had to flag it as out-of-scope each time. Merge the
PR or pin a more authoritative status doc next session.

## 7. Forward outlook

The Phase 5 status doc estimated "80-85% remaining" to a 1000-game
ready smoke. Today closed **3 of the 5 predicted CE divergences**
(CE2 / CE3 / CE4) plus 1 follow-up (`draw_card` inline-vs-pymethod),
surfaced 1 new (CE5) and pinned 2 informal findings
(`CE-pure-derivation-is_over`, `CE-shuffle-prng-mismatch`), and
walked the smoke from **0 multi-turn decisions to 107 clean steps
(turn 9 PRECOMBAT_MAIN)**. The playbook's CE5/CE6/CE7 closure recipe
is pre-staged with file:line maps so each closure is now a single
small/medium slice. Revising the estimate downward: **roughly
60-70% remaining to 1000-game ready**, with the remaining work
front-loaded into 3-5 CE closures (CE5-cast, CE10-is_over,
CE6-combat, CE7-targets, plus CE8-trigger-emitter) and 1 substrate
slice (RNG externalization for G19 + CE12). At today's velocity
(~3 CE closures + 1 probe extension per session) a reasonable bound
is **6-10 more sessions to 1000-game-ready**, contingent on the
combat / trigger surfaces not surprising us.
