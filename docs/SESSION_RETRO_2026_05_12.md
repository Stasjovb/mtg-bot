# Session retrospective — 2026-05-12

Mid-day synthesis of today's mtg-bot Rust-port + Phase 5 session.
Builds on yesterday's retro (`docs/SESSION_RETRO_2026_05_11.md`,
`2c8b6603`) and `docs/PHASE5_STATUS.md`. Mirrors the prior retro's
structure; detail lives in the linked playbooks + gap doc.

## 1. Headline

The cross-engine smoke walked from **107 clean steps (turn 9 PRECOMBAT_MAIN, single-attacker)**
to **226 clean decisions of bilateral combat** with both players
attacking on their own turns and resolving damage through multiple
exchanges. The big concrete milestone: **CE9 closed with a 1000/1000
clean multi-block combat smoke** on `multi_blocker_deckspec`
(`9633953e` + `cdd6ce00`), and the retaliation probe drove p0 and p1
through symmetric combat to surface **CE12** (winner_id sticky-vs-derived
in the BOTH-LOST transition, `d8ac7f89`). Two more CEs closed
(**CE9** combat blocker walk + **CE11** cross-player find-first, the
latter carrying in from yesterday's late session), one was pre-emptively
documented (**CE8 PRNG playbook**, `47b28fe2`), one Effect variant
landed (**DrawCardsEqualToResolvingCombatDamage**, `9710ffa2`), and
its production write site was wired (`f229cb37`, closing a
`SEARCH_LIMITATIONS.md` deferral). The probe-close-probe cadence held
all day: every probe extension surfaced exactly one new divergence;
every divergence either closed or pre-staged a closure plan.

## 2. Slices shipped on origin/main

Sort: newest-first. Impact = HIGH means closed a confirmed parity gap
or unblocked the next probe; MED = first-slice Effect / infra; LOW =
doc / cleanup.

| Commit | Slice | Shipped | Impact |
|---|---|---|---|
| `a578fe09` | Merge `feature/phase5-retaliation` | bilateral-combat probe; **surfaces CE12** | HIGH |
| `d8ac7f89` | `phase5-retaliation` | retaliation_selector (no `active_idx==0` gate); 226-decision clean bilateral walk; CE12 surface-pin (`tests/test_parity_smoke.py:2549`) | HIGH |
| `a9e0b9d2` | Merge `feature/ce8-playbook` | doc: CE8 PRNG-mismatch closure plan | HIGH (pre-stages next slice) |
| `47b28fe2` | `ce8-playbook` | `docs/CE8_PRNG_CLOSURE_PLAYBOOK.md` (697 lines, 11 sections) — Option A vs Option B (RECOMMENDED externalize via PyO3 `_randbelow` callback); 8 Rust RNG call sites + 8 Python counterparts enumerated; 1-2 slice scope; risk register | HIGH |
| `0d724757` | Merge `feature/combat-damage-write-site` | wire `resolving_combat_damage_amount` write; close SEARCH_LIMITATIONS deferral | HIGH |
| `f229cb37` | `combat-damage-write-site` | per-PlanEntry set/reset of `state.resolving_combat_damage_amount` in `apply_damage_pass` (Python parity at `combat.py:618,623` + `actions.py:2684,2699`); +5 combat tests inc. `cross_engine_draw_eq_starwinder`; new I32 invariant | HIGH |
| `90a015dc` | Merge `feature/ce9-blocker-bf-order` | **closes CE9** (combat blocker walk uses `bf_iter_etb_sorted`) | HIGH |
| `cdd6ce00` | `ce9-blocker-bf-order` (docs) | CE9 CLOSED notice + I31 invariant + xfail flip (`tests/test_parity_smoke.py` multi-block walk-clean) | HIGH |
| `9633953e` | `ce9-blocker-bf-order` (rust) | 2 iteration sites in `deal_combat_damage` flip from `self.blockers` push-order to bf-ETB order; SBA destroy clears per-object `damage`/`tapped`/`attached_to` on move-to-graveyard (`turn.move_off_battlefield` parity); **1000/1000 clean multi-block smoke**; +3 regression tests | HIGH |
| `7dd141a1` | Merge `feature/rust-effect-draw-eq-combat-damage` | Effect freq-2 closure | MED |
| `9710ffa2` | `rust-effect-draw-eq-combat-damage` | `Effect::DrawCardsEqualToResolvingCombatDamage` (Starwinder / Fear-of-Failed-Tests, 2 EoE cards); freq-2 tier now 52/53 (98.1%); 80 Rust variants; per-card coverage 75.7% | MED |
| `5382b9ab` | Merge `feature/cross-player-find-first` | **closes CE11** (cross-player find-first arms walk bf-ETB order; landed late 2026-05-11 UTC → today local) | HIGH |

**Total: 6 non-merge commits + 6 merge commits = 12 commits on
origin/main today.** Of those, **2 CE closures** (CE9 today; CE11
landed at the wrap of yesterday's session and is included here per
local-time framing), **1 CE surfaced + pinned** (CE12), **1 substrate
closure** (combat-damage write-site), **1 playbook pre-stage** (CE8),
and **1 Effect variant** (freq-2 last miss).

## 3. Open xfail / pending findings on main

### `tests/test_parity_smoke.py`

| Test | Reason | Closure path | Doc entry |
|---|---|---|---|
| `test_..._surfaces_ce12_winner_id_sticky_vs_derived` (strict-xfail, line 2549) | **CE12** — Python's `turn.py:1383-1393` SBA writer gated on `state.winner_id is None` (sticky); Rust's `state_ops_winloss.rs:225-235` getter live-derived from `has_lost`. In the BOTH-LOST transition Python keeps the prior sticky `0`, Rust switches to `None` | Option A: Python clears `winner_id` on alive=1→0 transition (engineering-correct: a draw has no winner). Option B: Rust grows a sticky shadow `winner_id_written` field | `RUST_PARITY_GAPS.md` CE12 (line 2174) |

The CE9 multi-block-walk-clean test flipped from strict-xfail to
expected-pass today (`cdd6ce00`); the companion symptom-pin for CE9
at step 196 was deleted per the closure-pair contract.

### `tests/test_parity_smoke_edge_cases.py`

| Test | Reason | Closure path | Doc entry |
|---|---|---|---|
| `test_cross_engine_shuffle_seed_walks_clean` (strict-xfail, line 388) | **CE8** — Python MT19937 vs Rust xorshift64; same seed → different permutation at step 0 | CE8 playbook landed today: Option B (externalize via PyO3 `_randbelow` callback) | `RUST_PARITY_GAPS.md` CE8 (line 1781); `docs/CE8_PRNG_CLOSURE_PLAYBOOK.md` |
| `test_cross_engine_shuffle_seed_surfaces_library_divergence_for_multiple_seeds` (companion symptom-pin) | Passes today; flips to failing (or gets deleted) when CE8 closes | same | same |

Yesterday's CE10 (`pure-derivation-is_over`) and the inline-`draw_card`
asymmetry both **closed** late yesterday (`feature/ce-pure-derivation-is-over`
and `feature/draw-card-inline-flag`) so the empty-library and
multi-turn-auto-draw xfails listed in yesterday's retro section 3 are
no longer open.

### `tests_rust/`

Pre-existing `test_no_orphan_rust_variants` red — 3 orphans pending
the unmerged `feature/coverage-overrides` PR (`2bcdd842`). Same status
as yesterday; user-gated.

## 4. CE entries — open vs closed (mid-day 2026-05-12)

| CE | Status | Site | Closure / surfacing commit |
|---|---|---|---|
| CE1 | CLOSED (r28) | `summoning_sick` default | pre-2026-05-11 |
| CE2 | CLOSED 2026-05-11 | `apply_action(PassPriority)` no-op | `87a2d662` |
| CE3 | CLOSED 2026-05-11 | library orientation (`lib[0]` = top) | `5a345f6d` |
| CE4 | CLOSED 2026-05-11 | `battlefield_snapshot` ETB-timestamp ordered | `d04cb3de` |
| CE5 | CLOSED 2026-05-11 | cast-vs-resolve harness-side `resolve_top_of_stack_python` mirror | late yesterday |
| CE6 | CLOSED 2026-05-11 | SBA victim collection (`bf_iter_etb_sorted` helper birth) | `cdb01fcd` |
| CE7 | CLOSED 2026-05-11 | inline-vs-pymethod asymmetry / SBA-order follow-ups | late yesterday |
| **CE8** | **OPEN** | `shuffle_deck` PRNG mismatch (MT vs xorshift64) | filed yesterday; **playbook landed today (`47b28fe2`); Slice 1 in flight** |
| CE9 | **CLOSED today** | combat blocker walk uses `bf_iter_etb_sorted`; SBA-destroy clears combat marks | `9633953e` + `cdd6ce00` (merge `90a015dc`) |
| CE10 | CLOSED 2026-05-11 | SBA-gated `is_over` / `winner_id` / `is_draw` surface accessors | late yesterday |
| CE11 | CLOSED today | cross-player find-first arms (`TapAnotherTargetCreature` + `UntapTargetOtherPermanent`) walk bf-ETB | `5382b9ab` |
| **CE12** | **OPEN — surfaced today** | `winner_id` accessor in BOTH-LOST: Python-sticky vs Rust-live-derived | surfaced `d8ac7f89`; pinned at `RUST_PARITY_GAPS.md:2174` |

**Net change vs yesterday's retro:** CE9 + CE11 closed; CE12 surfaced;
CE8 playbook pre-staged. Two CE open today (CE8, CE12) vs three open
at yesterday's wrap (CE8, CE12 didn't exist yet; CE10 and CE-draw-inline
closed overnight). One in-flight agent may file a new CE during the
pre-emptive ETB-iter fix.

Invariants doc grew **I30** (cross-player find-first), **I31** (combat
damage assignment + SBA-clears-marks), **I32** (resolving_combat_damage
write site), **I33** (mass-effect resolve arms) — see
`RUST_PARITY_GAPS.md` lines 1409, 1445, 1515, 1574.

## 5. Top 3 priorities for the NEXT session

### Priority 1 — CE8 Slice 2 (gameplay shuffle sites + Python parity wiring)

**What.** Slice 1 (in flight as of writing) wires the PyO3 `_randbelow`
callback substrate + `setup` shuffle site per the playbook. Slice 2
takes the remaining ~6 gameplay shuffle sites (search-and-shuffle
tutors, library_lookat top-N-then-shuffle-remainder, mulligan deck
shuffle, bespoke shuffles) plus the Python-side wiring of
`state.rng._randbelow` as the SoT stream both engines consume.

**Pointers.** `docs/CE8_PRNG_CLOSURE_PLAYBOOK.md` Sections 5-7 (call
sites + threading plan); `rust/src/state_ops_library.rs:47-86`,
`state_ops_mulligan.rs:84-117`. Closes CE8 + G19 simultaneously per
playbook Section 9.

**Scope.** Medium (~100 LOC + test wiring).

**Why.** Highest-leverage open item: unblocks every cross-engine
probe past Phase 5 that touches shuffle (mulligan, tutor, Nexus-style
re-shuffle Effects). Substrate is paid down once and never again.
**Caveat:** depends on Slice 1 landing green; if Slice 1 hits a
PyO3-callback-overhead issue, fall back to Option A (Mersenne Twister
in Rust, `~50` LOC) per playbook Section 2.

### Priority 2 — CE12 closure (winner_id sticky-vs-derived)

**What.** Pick Option A (Python clears `winner_id` on alive=1→0
transition — engineering-correct: a draw state has no winner) per
playbook guideline "slice-authors-prefer-A". Roughly: edit
`turn.py:1383-1393` to either re-derive on each SBA pass OR clear when
the alive-count transitions to 0.

**Pointers.** `RUST_PARITY_GAPS.md` CE12 (line 2174);
`tests/test_parity_smoke.py:2549` (strict-xfail to flip); worklog
`2026-05-12-phase5-retaliation` for the surfacing detail.

**Scope.** Small (~10-30 LOC Python edit + xfail flip + companion
symptom-pin removal per closure-pair contract).

**Why.** Cleanest small slice on main. Eliminates the last CE blocking
extended bilateral-combat probing; `replay_capture.py:325` reads
`state.winner_id` for reward signal so the sticky semantic actively
biases training data ("p0 wins" labels on positions that are actually
draws). Closing CE12 also unlocks longer multi-block probes (today's
walked 226 decisions before tripping; post-CE12 expects materially
further before the next surface).

### Priority 3 — Extend Phase 5 probe to the next surface (activated abilities mid-combat OR mass removal in combat)

**What.** After Priorities 1+2 land, extend the cross-engine smoke
beyond pure combat damage into either (a) activated abilities fired
during combat (instant-speed pump / removal targeting attackers) or
(b) mass removal in main phase that interacts with the combat
trigger emitter (next predicted CE after the trigger-emitter substrate
lands).

**Pointers.** Existing harness shape in
`src/mtg_bot/parity/cross_engine.py` (selectors); the retaliation
selector at `2026-05-12-phase5-retaliation` is the most recent template.

**Scope.** Medium (~100-200 LOC new selector + 1-2 probe tests).

**Why.** The probe-close cadence is the win. Every extension has
surfaced exactly one new divergence in one session, and each closes
within 1-2 slices. Holding the cadence is more valuable than
speculative closures (e.g. trigger-emitter substrate, `spell_warped_this_turn`)
that aren't pinned by any probe yet.

### Honorable mentions (deliberately not picked)

- **`spell_warped_this_turn` substrate**: deferred yesterday; requires
  warp-casting infrastructure that no current probe exercises. Big
  scope, small payoff today.
- **Long-tail freq-1 Effect variants**: explicitly out of Phase 5/6
  scope per `RUST_PARITY_PLAN.md` "Phasing" §3; poor ROI per emission
  at 5.6% coverage of 161 classes for ~3% of weighted emissions.
- **`feature/coverage-overrides` PR merge**: user-gated; same status
  as yesterday. One pre-existing red continues to show in every gate
  run.
- **Trigger-emitter substrate (CE8-precursor in yesterday's audit)**:
  was renumbered out; today's CE8 is the PRNG mismatch. Trigger
  emitter is still important but is a bigger scope and not yet
  pinned by any open probe — wait for it to surface.

## 6. Lessons learned

**What worked.**

- **Probe-close cadence continues to dominate.** CE9 surfaced
  2026-05-11 evening, closed mid-day 2026-05-12 with a 1000/1000
  clean multi-block smoke; CE12 surfaced today and is pre-staged for
  next session. Two more data points on the same shape.
- **`bf_iter_etb_sorted` helper paid dividends again** — third and
  fourth consumers landed today (CE9 in `deal_combat_damage`, CE11 in
  cross-player find-first arms via late-yesterday slice); the
  pre-emptive ETB-iter fix agent in flight is consuming it for a
  fifth site. The helper was originally CE6's investment; every CE
  closure since has either consumed it or extended its consumer list.
- **Playbook docs accelerated closures.** The CE5/CE6/CE7 playbook
  (`2a7221b1`) directly enabled CE6, CE9, and CE11 closures with the
  file:line maps pre-derived. Today's CE8 playbook (`47b28fe2`)
  spawned CE8 Slice 1 immediately. The doc-first pattern is paying
  ~3:1 leverage relative to time invested.
- **Abandoned-retaliation recovery was smooth.** The original
  retaliation agent's report truncated mid-output; the recovery
  agent rebased the in-flight commit cleanly onto the CE8-playbook
  merge that landed during the slice (`d092fd59` → `d8ac7f89`) with
  no progress lost. Worktree + branch-per-feature isolation paid off.

**What hit friction.**

- **`coverage-overrides` PR still unmerged.** One pre-existing red
  in `test_no_orphan_rust_variants` showed up in every gate run today
  (3 orphans: `ChooseOneMode`, `GrantKeywordToTargetCreatureUntilEOT`,
  `SetBasePTUntilEOT`). Same as yesterday; same workaround (task
  briefs flagged it as out-of-scope). Worth merging.
- **CE9 closure exposed a paired secondary divergence** (SBA destroy
  not clearing per-object `damage`/`tapped`/`attached_to`). Caught
  cleanly mid-slice but added ~30 minutes; future bf-iter closures
  should check the move-to-graveyard clear-set in parallel.
- **Two CEs surfaced in one day (CE9 + CE12) outpaced the closure
  cadence by one.** Not a problem yet — CE12 is small and pre-staged.
  If the cadence inverts (probe surfaces 2/session, closures
  1/session) for two more sessions, the open-CE backlog will grow.
  Watch the ratio.

## 7. Forward outlook

Yesterday's retro estimated **60-70% remaining** to a 1000-game-ready
cross-engine smoke. Today closed 2 more CEs (CE9 + CE11), surfaced 1
(CE12, small + pre-staged), and pre-staged the biggest remaining
architectural item (CE8 PRNG, ~1-2 slices). The cross-engine smoke
now walks bilateral combat to 226 decisions clean and multi-block
combat to **1000/1000 clean games** on the multi-blocker deckspec.
Revising downward: **roughly 45-55% remaining**, contingent on (a)
CE8 closing in the predicted 1-2 slices, (b) CE12 closing in the
predicted small slice, and (c) the next probe extension surfacing
its predicted divergence rather than a deeper-than-expected
substrate gap. At today's velocity (~2 CE closures + 1 substrate
plan + 1 probe per session) a reasonable bound is now **4-6 more
sessions to 1000-game-ready**, down from yesterday's 6-10 estimate.
The remaining work is now front-loaded into CE8 (substrate, biggest
single item), CE12 (small), one or two activated-ability/mass-removal
probes, and the trigger-emitter substrate when its probe surfaces it.

---

**If you only read one line of this doc, read this:** CE9 + CE11
closed (1000/1000 clean multi-block combat; bilateral combat probe
walks 226 decisions), CE12 surfaced + pinned (winner_id sticky-vs-derived,
small closure), and the CE8 PRNG playbook went live — next session
should start with CE8 Slice 2 + CE12 closure to keep the cadence.
