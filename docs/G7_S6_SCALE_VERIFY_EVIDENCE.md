# G7 Slice S6 — `rust_shadow` bake-in SCALE-VERIFY evidence (the penultimate G7 slice; NO new masking; S7 CE5-removal is LAST)

**This is the S6 scale-verify evidence — the definitive readout the
S7 (CE5-removal) go/no-go is gated on.** It is the EVIDENCE-GENERATION
artifact only; the GO/NO-GO decision itself is the USER's
(orchestrator-sequenced, out of scope of this lane). It mirrors the
`docs/C4_RESWEEP_EVIDENCE.md` / Round-77 convention. Cross-refs:
`docs/RUST_STACK_RESOLUTION_DESIGN.md` (the G7 owner doc — S6 section),
`docs/RUST_SPELL_STACK_SOURCE_ZONE_DESIGN.md` (S5a/S5b/S5c),
`docs/G7_MIDGAME_STATEEQ_VERIFY_FINDING.md` §5/§7,
`docs/C4_RESWEEP_EVIDENCE.md` (the original 0/300 @ `e87a6ebe`),
`docs/SOT_FLIP_CUTOVER_PLAN.md` §4 ledger row G7,
`docs/SEARCH_LIMITATIONS.md` G7 section.

## Headline (HONEST)

**The S5a/S5b/S5-triggers `hand_p0` atomic-cast axis AND the cycle-30
combat-blocker `LEGAL_SET_EQ` STAY CLOSED at scale (0/300 reappear);
the bake-in is STILL a faithful, NON-MASKING tripwire; and the
complete remaining frontier is an ENUMERATED FINITE set of 5 distinct,
pre-existing, already-tracked axes — NOT a structural or masking
problem.** `0 / 300` games run divergence-clean to terminal, BUT —
unlike the original C4 (`0/300 @ e87a6ebe`, where 238/300 were the
single dominant G7-atomic `hand_p0` axis) — **every** non-timeout
failure is now one of 5 finite, characterized, already-on-the-ledger
fix-lanes. The dominant axis has shifted from the (now-closed)
atomic-cast G7 to the **G5-family priority-port** axis (138/300). No
new G-series divergence, no masking, no `_DOCUMENTED_ACCEPTED_FIELDS`
carve-out (the frozenset is empty — pinned).

**S7-readiness: the gap between here and a clean CE5-free C4 is
EXACTLY the enumerated finite frontier set below — each a tractable
fix-lane. There is NO structural / masking blocker. S7 (CE5 removal)
is gated only on closing this finite set (sequenced behind it), NOT
on a structural rework.** (The GO decision itself is the USER's.)

## Exact scope swept

| Field | Value |
|---|---|
| Engine `.pyd` / SoT commit | **`a9126b06`** (`resync: cycle 30 — G7 combat-blocker LEGAL_SET CLOSED + S5-triggers-verify CLEAN`; S1/S4/S5a/S5b/S5c/S5-triggers + R77-CFI1 + combat-blocker all landed) |
| Tooling commit (pure-Python verify, NO engine change) | `feature/g7-s6-bakein-scale-verify` off `main` @ `a9126b06` |
| Driver | `rust_shadow` (the role-swapped `ShadowCheckedRustAdapter`: Rust drives, Python shadow-checks lock-step; LEGAL_SET_EQ / CHOSEN_EQ / STATE_EQ / NO_RAISE; NO CE5, NO CE5-equivalent in the bake-in by design) |
| Grid | `--archetypes 0-59 --seeds 0,1,2,3,4` = **300 games** (the C4 round-76-class scale: 60 archetypes × 5 seeds — identical to `C4_RESWEEP_EVIDENCE.md`) |
| Deck source | `--decks 17lands` (real EoE production decks via `load_production_deck` + `production_deck_to_deckspec` — the bench's `setup_matched_game_from_real_decks` two-step expansion; NO synthetic decks) |
| Caps | `--max-turns 120` (step_both-path arg, inert under rust_shadow); `--shadow-max-steps 4000` (the rust_shadow decision-step upper bound) |
| Interpreter / env | shared canonical `.venv-py313`, `.pyd` already built on `main` @ `a9126b06` (**no rebuild — pure-Python tooling**; isolation self-check PASSED, see Gate) |
| Exact command | `PYTHONPATH=src .venv-py313/Scripts/python.exe scripts/bench_trajectory_parity.py --archetypes 0-59 --seeds 0,1,2,3,4 --max-turns 120 --driver rust_shadow --json-out s6_scale_verify.json --verbose` |
| Raw artifact | **`s6_scale_verify.json`** (committed alongside this doc) + `s6_scale_verify.log` |

**Scale rationale.** A 6-game timing probe (`--archetypes 0-2
--seeds 0,1`, `s6_timing_probe.json`) measured ~2.5 s/game; the full
300-game round-76-class grid completed in **1035.1 s wall** (~17 min,
per-game **3.45 s**). No scale-down needed — the full C4-class scale
ran single-run-feasible (the design-doc §4.4-risk-4 throughput
re-time: per-game rose from C4's 3.215 s to 3.45 s — the real
stack/priority resolution adds decision steps, as predicted; still a
single-run sweep, NOT a correctness concern).

## Result — full counts

| Outcome | Count | % |
|---|---:|---:|
| **PASS** | **0** | **0.0%** |
| **FAIL_DIVERGENCE** | **236** | 78.7% |
| **FAIL_EXCEPTION** | **21** | 7.0% |
| **FAIL_TIMEOUT** | **43** | 14.3% |
| **ARCHETYPE_FILTERED** | **0** | 0.0% |
| **total games** | **300** | |
| wall time | 1035.1 s | |
| per-game wall | 3.45 s | |

(The 21 FAIL_EXCEPTION are NOT loader/setup errors — they are the
**B1-axis frontier (Class A)**: a Rust-side raw `ValueError` from
`ActivateAbility` apply rejecting an ability Rust's own
`legal_decisions` emitted. The rust_shadow harness only converts a
*Python*-side apply raise to the NO_RAISE tripwire; a Rust-side raise
propagates raw — so this honest divergence is bucketed FAIL_EXCEPTION,
not FAIL_DIVERGENCE. Verified: every one classifies to Class A, zero
are loader/setup.)

## The closed axes STAY CLOSED — CLEAN (the load-bearing S6 question 1)

**Zero games (0 / 300) mention `hand_p0` or `('blocker', ...)` in the
divergence detail.** Verified by classifying every one of the 257
non-timeout failures (`scripts/scout_s6_classify.py`, the CLOSED-AXIS
REGRESSION GUARD section) and finding **zero** hits.

- The **`hand_p0` atomic-cast G7 axis** — the dominant **238/300**
  STATE_EQ `[('battlefield', …), ('stack', …)]` + caster `hand_pX`
  shape the ORIGINAL C4 re-sweep (`0/300 @ e87a6ebe`) tripped on, on
  essentially the FIRST `CastSpell` of every real-deck game — **does
  NOT reappear anywhere in the 300-game population.** S5a (the
  spell-stack source-zone re-homing, Option β) + S5b (codec/
  determinizer cross-source verify) + S5-triggers-verify genuinely
  closed it at scale, not just on the synthetic smoke deck. The
  non-warp creature cast now resolves in lockstep through the
  re-homed `stack_objects` source on both engines — confirmed: NOT
  ONE of the 5 surviving frontier classes is the closed atomic-cast
  shape.
- The **cycle-30 combat-blocker `LEGAL_SET_EQ`** (`('blocker', N,
  None)` Rust over-emission with zero attackers) — **does NOT
  reappear anywhere.** The `&& !self.attackers.is_empty()`
  no-attackers gate holds at scale.

## NO NEW MASKING — explicit verdict + how it was verified (the load-bearing S6 question 2)

**VERDICT: NO new masking. The bake-in is still a faithful,
discriminating, non-masking tripwire.** Verified THREE independent
ways:

1. **`_DOCUMENTED_ACCEPTED_FIELDS == frozenset()` (empty — pinned).**
   No field is carved out / accepted. A non-empty set here would be
   exactly the `_DOCUMENTED_ACCEPTED_FIELDS` false-green the design
   doc §3.4 forbids. Pinned by
   `tests/test_g7_s6_scale_verify.py::test_s6_no_new_masking_negative_controls_intact`
   (asserts the frozenset is empty).
2. **The negative controls FIRE LOUDLY.** All three tripwires
   (STATE_EQ / LEGAL_SET_EQ / NO_RAISE) demonstrably raise
   `ShadowDivergenceError` on an INJECTED divergence — the S6 pin
   re-asserts the STATE_EQ negative control at the S6 boundary, and
   the 3 pre-existing `test_rust_shadow_bakein.py` negative controls
   (`test_legal_set_eq_fires_on_injected_divergence`,
   `test_no_raise_fires_on_python_apply_raise`,
   `test_state_eq_fires_on_divergent_post_state`) are all GREEN at
   `a9126b06`. The tripwire is not a silent no-op.
3. **No silent passes — the 0 PASS is itself the proof.** The bake-in
   trips LOUDLY at EVERY frontier (every non-timeout game ends in a
   raised tripwire / Rust-side raise; the 43 FAIL_TIMEOUT are the
   degenerate land-only random walks that never assemble a castable
   spell — explicitly NOT clean PASSes and NOT a parity verdict, the
   same class as C4's 40/300). Not one game was silently green-lit
   while divergent. **Zero unclassified shapes** (the classifier's
   UNCLASSIFIED bucket is empty) — every divergence maps to a known
   axis; no axis was masked rather than fixed.

## The COMPLETE frontier inventory — 5 enumerated finite classes (S6 question 3)

Every one of the 257 non-timeout failures classifies to exactly one
of these 5 distinct, pre-existing, already-on-the-ledger axes. Each is
a tractable fix-lane. Priority-ordered by population weight:

### Class B — G5-family priority-port STATE_EQ — **138 / 300 (dominant)**

- **Shape:** `[STATE_EQ] … [('priority_player', X, Y)]` (Python=X,
  Rust=Y) on a `PassPriority()`, typically at a DECLARE_ATTACKERS /
  priority step.
- **Representative:** arch5/s0 step 367 (`('priority_player', 1, 0)`);
  arch0/s0 step 649 (`('priority_player', 0, 1)`); arch3/s0 step 300.
- **Class:** **G5-family** (the Rust-driver priority-port axis —
  `RustGameStateAdapter._reset_priority_to_active` / `_next_alive`
  region). The synthetic-deck G5 was closed by `86411a99`; this is
  the deeper production-deck manifestation the cycle-30 honest-stop
  pin already characterized (arch5/s0 step 367 — IDENTICAL).
- **Root-cause hypothesis:** the Rust-driver priority loop
  (`rust_engine_adapter.py:_run_priority_action`) resets / hands off
  priority at a CR-117.1c moment one player different from Python's
  `simulate.priority_loop` `_next_alive(active)` at the same
  decision, in a non-empty-stack or post-resolution window the
  synthetic deck never exercised (design-doc §4.4-risk-1: nested
  response windows / production-deck priority — new cross-engine
  surface). NOT a `hand_p0` regression (the spell-stack is fine; this
  is a pure priority-index divergence).
- **Fix-lane:** G5-family priority-port — extend the
  `RustGameStateAdapter` priority reset/handoff to byte-mirror
  Python's `_next_alive` in the production-deck non-empty-stack /
  response-window case (pure-Python adapter, the same shape as the
  `86411a99` G5 closure). **HIGHEST PRIORITY** (dominant + already
  pinned).

### Class C — warp-EMISSION / S4b — **44 / 300**

- **Shape:** `[STATE_EQ] … [('exile_pX', …), ('battlefield', …),
  ('stack', …)]` (or `library_pX` projections) where a **WARP
  creature** (Starbreach Whale `Warp {1}{U}`, Germinating Wurm
  `Warp {1}{G}`, Timeline Culler, …) is on Rust's **battlefield +
  warp-exile** while Python keeps it **on the stack** pending
  resolution.
- **Representative:** arch1/s1 step 169 (Starbreach Whale obj 81 —
  Rust bf+exile_p1, Python on stack); arch4/s0 step 192 (Germinating
  Wurm obj 12).
- **Class:** **warp-EMISSION / S4b** — the explicitly STILL-OPEN
  warp-cast legal-EMISSION / non-creature-permanent boundary axis
  (`SOT_FLIP §4` G7 row "S4b + warp-EMISSION remain distinct
  STILL-OPEN"; `G7_S4_VERIFY_FINDING.md` §4). The `library_pX`
  sub-variants (e.g. arch42/s4) are the SAME root cause manifesting
  in the warp "cast it from exile on a later turn" library
  recursion — NOT a distinct 6th class.
- **Root-cause hypothesis:** S4 closed the `cast_creature_warp`
  resolve SHAPE (proven byte-equal by `step_both`), but the
  warp-cast LEGAL-EMISSION + the warp creature's atomic-vs-stacked
  resolution under the role-swapped bake-in remained open — Rust's
  warp-cast still resolves the warp creature to bf (+ warp-exile
  rider) inside the apply, while Python stacks it. This is the S4
  twin of the S1 atomic-cast hole, scoped to the warp path.
- **Fix-lane:** S4b / warp-EMISSION — apply the S1 stack-push shape
  + the S5a stack-store re-homing to the `cast_creature_warp` path
  (Rust engine; the next owed warp slice). **2nd PRIORITY.**

### Class E — C1-family mana-source color on ActivateAbility — **31 / 300**

- **Shape:** `[STATE_EQ] [('mana_pool_pX', (…Python colors…),
  (…Rust colors…))]` on an `ActivateAbility` — the tapped mana
  source produces a DIFFERENT color in the two engines (e.g. Python
  `U:2` vs Rust `G:2`).
- **Representative:** arch1/s0 step 598
  (`ActivateAbility(source_id=120)`, Python `U:2` / Rust `G:2`).
- **Class:** **C1-family** (the Rust legal/apply mana-source
  selection vs Python's — a sibling of the C1 mana-awareness axis,
  `RUST_LEGAL_DECISIONS_MANA_AWARENESS_DESIGN.md`).
- **Root-cause hypothesis:** when an activated ability's cost is paid
  by tapping a multi-color-capable source (or selecting among
  several tappable sources), Rust's apply chooses a different color /
  source than Python's `auto_tap`/`tap_for_mana` order — the
  ability-activation analog of the G7_MIDGAME auto-tap-from-lands fix
  (which fixed the CAST path; the `ActivateAbility` pay site was
  intentionally left unchanged there — `G7_MIDGAME §3`).
- **Fix-lane:** C1-family — byte-mirror Python's mana-source/color
  selection order at the `ActivateAbility` pay site (Rust engine;
  the `pay_mana_cost_pub` path the G7_MIDGAME fix deferred). **3rd
  PRIORITY.**

### Class D — B1-keystone / C1 legal-set asymmetry — **23 / 300**

- **Shape:** `[LEGAL_SET_EQ] rust\py=["('cast_spell', N, False,
  False, False, False, None)"] py\rust=[]` — Rust's
  `legal_decisions` offers a PLAIN `CastSpell` (no warp/kick/free/
  impending) Python's raw `legal_actions` does not.
- **Representative:** arch7/s0 step 453 (`('cast_spell', 76, …)`);
  arch8/s3 step 695 (`('cast_spell', 75, …)`).
- **Class:** **B1-keystone / C1** — the EXACT secondary 22/300
  LEGAL_SET_EQ shape the original C4 re-sweep already identified
  (`C4_RESWEEP_EVIDENCE.md:126-147`): the C1
  `legal_decisions == legal_actions` mana/target/additional-cost
  asymmetry, the already-tracked keystone co-blocker
  (`SOT_FLIP §4` B1; Slice 1 mana DONE `f1f09bbb`, Slices 2/3 NOT
  landed). **NOT a new G-axis** — the expected residual of the
  already-open B1, INDEPENDENTLY RE-CONFIRMED at scale (23 ≈ the
  C4 22).
- **Fix-lane:** B1 / C1 Slices 2/3 (target-satisfiability /
  additional-cost) — its own lane
  (`RUST_LEGAL_DECISIONS_MANA_AWARENESS_DESIGN.md`); co-blocker of
  the flip GO per `SOT_FLIP §4`. **Co-evolves with the others.**

### Class A — B1-axis ActivateAbility affordability — **21 / 300**

- **Shape:** RAW `ValueError` "ActivateAbility: source N cost is
  unaffordable from controller's mana pool (mana_cost generic=2,
  …)" — Rust's `legal_decisions` OFFERS an `ActivateAbility` Rust's
  OWN `apply_action` then rejects (a Rust-internal
  legal-emit-vs-apply self-inconsistency).
- **Representative:** arch2/s1 step 318
  (`ActivateAbility(source_id=121, ability_index=0)`); arch0/s2 step
  276 (source 120).
- **Class:** **B1-axis analog** — the EXACT arch2/s1-step-318
  frontier the cycle-30 honest-stop pin
  (`test_g7_combat_blocker_legalset_closed_then_next_frontier_surfaced`)
  already characterized. The `ActivateAbility` emit site lacks the
  affordability gate B1 Slice 1 added to the 5 `CastSpell` sites
  (`can_pay_cost`).
- **Fix-lane:** B1-axis — add the `can_pay_cost`-equivalent
  affordability gate to the Rust `ActivateAbility` emission site
  (Rust engine; the `ActivateAbility` analog of B1 Slice 1). **4th
  PRIORITY** (lowest count; well-characterized).

### FAIL_TIMEOUT — 43 / 300 (NOT a parity verdict)

The 43 FAIL_TIMEOUT games hit the `--shadow-max-steps 4000` cap:
degenerate land-only random-walk mirrors where the uniform-random
driver never assembled a castable spell and the game never reached a
terminal — explicitly **NOT** clean PASSes and **NOT** a parity
verdict (the same degenerate class as C4's 40/300,
`C4_RESWEEP_EVIDENCE.md:79-87`; raising the cap can only convert
TIMEOUT → PASS/DIVERGENCE, never the reverse). Confirmed same class
(land-only archetypes 6/19/26/27/29/31 are 5/5 FAIL_TIMEOUT — the
known degenerate-deck cluster).

## S7-readiness assessment — GO (gated only on the finite frontier set)

**S7 (CE5 removal) is gated ONLY on closing the enumerated finite
frontier set above — there is NO structural / masking blocker.** The
honest read:

1. **The S5a hard prerequisite for S7 is satisfied AND holds at
   scale.** The `hand_p0` atomic-cast axis (the S7 linchpin per
   `RUST_SPELL_STACK_SOURCE_ZONE_DESIGN.md` Part 4) is closed and
   stays closed across all 300 production games — Rust and Python are
   BOTH "spell on stack, not in hand, awaiting priority passes" at
   every per-apply compare point for the non-warp creature cast. This
   is precisely the "green WITHOUT CE5" precondition; the bake-in
   (which has NO CE5 and NO CE5-equivalent) confirms the closed axis
   is genuinely closed, not CE5-masked.
2. **The gap is finite and enumerated, NOT structural.** Zero
   unclassified shapes; every divergence is one of 5 known,
   already-tracked fix-lanes (B/C/E/D/A above). This is exactly the
   design-doc S6 success criterion: "is the gap … EXACTLY the
   enumerated finite frontier set (each a tractable fix lane), or is
   there a structural/masking problem that blocks S7?" — **it is the
   finite set; there is no structural/masking problem.**
3. **NO new masking.** The bake-in tripwire is faithful (empty
   frozenset, negative controls fire, no silent passes). S7 deletes
   CE5; S6 proves the CE5-free bake-in surface is honest.
4. **Caveat (honest, NOT a blocker):** the original C4 evidence base
   (307/475 byte-equal + trajectory sweep) was generated WITH CE5 and
   is invalidated by S7 per the design-doc Part 3.2 — that re-proof
   is S7's job, not S6's. S6's job is to prove the bake-in surface is
   honest + the frontier is finite BEFORE the irreversible S7; that
   is done.

**Honest GO/NO-GO:** S7 is **GO-once-the-finite-frontier-set-closes**.
The remaining fix-lane sequence → S7 (priority-ordered):

`Class B (G5-family priority-port, dominant 138) → Class C
(warp-EMISSION/S4b, 44) → Class E (C1-family mana-source color, 31) →
Class A (B1-axis ActivateAbility affordability, 21) → Class D (B1/C1
Slices 2/3, 23 — co-evolves, its own lane) → S7 (CE5 removal +
CE5-free re-proof + fresh CE5-free C4 = the final flip gate).`

The flip GO requires BOTH the G7 chain (this set → S7 clean CE5-free
C4) AND B1 (Class D = C1 Slices 2/3) closed — they are co-blockers,
INDEPENDENTLY RE-CONFIRMED by S6 exactly as the original C4 and the
design-doc §4.2 predicted. The GO decision itself remains the USER's.

---

*Generated by the G7 S6 scale-verify lane
(`feature/g7-s6-bakein-scale-verify` off `main` @ `a9126b06`).
Verify-first confirmed the S6 scope against live
`RUST_STACK_RESOLUTION_DESIGN.md` (S6 section) +
`RUST_SPELL_STACK_SOURCE_ZONE_DESIGN.md` +
`G7_MIDGAME_STATEEQ_VERIFY_FINDING.md` §5/§7 +
`C4_RESWEEP_EVIDENCE.md` + `SOT_FLIP_CUTOVER_PLAN.md` §4 +
`rust_shadow.py` + `test_rust_shadow_bakein.py` before running the
sweep. Tooling: `--driver rust_shadow` on
`scripts/bench_trajectory_parity.py` +
`rust_shadow.drive_shadow_game_to_terminal` (unchanged from C4) +
`scripts/scout_s6_frontiers.py` / `scripts/scout_s6_classify.py`
(throwaway diagnostics) + `tests/test_g7_s6_scale_verify.py` (8 pins).
PURE-PYTHON VERIFY — zero `rust/src/` change, zero `src/` change, zero
`cross_engine.py`/`parity_smoke.py` change; the `.pyd` was NOT rebuilt
(isolation self-check: shared canonical `.venv-py313` `.pyd`
SHA256/size/mtime byte-identical before/after). 4-file core gate
**1536 UNMOVED**; `tests_rust` 30 failed / 2312 passed (byte-identical
to the `a9126b06` baseline — zero newly-failing);
`check_audit_coverage_staleness.py` exit 0. NOT merged / NOT pushed —
this lane ships zero Rust so NO `.pyd` rebuild / NO residue cadence /
NO cron resync is owed (the S5b/S5-triggers-verify zero-engine
pattern). The orchestrator owns any merge.*
