# Cross-engine parity handoff — CONTINUOUS-PIPELINE phase (cycle ~2, main `f2526960`)

**This is the canonical "read this first" doc for the current phase.**
It supersedes `docs/HANDOFF_2026_05_16.md` (that doc was written ~round
46, in the *synchronized-rounds* era — its invariants are still true and
are preserved below, but its operating model and backlog are stale). If
you are a scheduled routine or a fresh session re-orienting, read this
doc + the top ~2 entries of `hub/data/mtg_bot/worklog.json` (the
continuous-pipeline-cycle entries — the top entry's bullets are the
source of truth for what landed this cycle), then act.

---

## 0. TL;DR for the impatient

- **Current main HEAD: `f2526960`** (Tier-C Rung-1 implement-ready spec
  merge). **The pipeline gate is GREEN** — verify-against-`git log`: the
  latest code merges (Radiant Strike `0c795e8c`, Seedship `9f107160`)
  each passed the gate (1438 / 1449) before auto-merge; everything since
  is docs/bench (no gate regression possible).
- **Tracked parity: ~298 / 475 EoE cards (62.7%) byte-equal at the
  Effect+bridge level** (`docs/POOL_PARITY.md` — NOT yet regenerated
  for the two Tier-A Effect closes; the orchestrator resync owns that —
  see §3a). Each closed Tier-A card leaves the Effect-uncovered bucket.
  This is NOT full-game-trajectory parity (see §1 caveat).
- **Parity status (verify-against-git-log):** Effect-uncovered **Tier-A
  #1 Radiant Strike CLOSED** (`0c795e8c`) and **#2 Seedship Impact
  CLOSED** (`9f107160`) — Rust queue items 1-2 done, byte-equal with
  genuine real-EoE probes. The Rust agent is **draining the round-64
  queue**, continuing at **#3 Orbital Plunge** and onward.
- **Honest residue: 6 distinct genuine-Rust-Effect cards** + 2
  `blocked_non_effect` + 11 `closed` (unchanged by the Tier-A closes —
  those are pool-coverage drains, not residue entries). The 169-card
  subsystem-gated tail is the real long-pole.
- **Operating model: a CONTINUOUS PIPELINE** — ≤5 concurrent background
  agents, ≤1 Rust at a time, agents **auto-merge when green** (no
  end-of-round barrier), worktree-per-feature, orchestrator does
  post-merge cron-resync/fold and refills the pool. Unchanged.
- **The corrected leverage map (§3):** the cheap single-card Tier-A
  lane is **near-exhausted** (queue draining #3-7, then `_BATCH3` §4
  confirms the lane ends); the **Tier-C ladder is the next substrate**
  but **verify-first KEEPS trimming the optimistic estimates** — rung 1
  was corrected to **2 cards / 6,375 decks / bench delta +0** (was 4 /
  11,825), the ship verdict is **SPLIT**, and **Exosuit Savior is
  promoted** as the lowest-risk first close. warp Phase 2 = **Timeline
  Culler spec ready** (+1 card / +8,986 decks). **Aura is
  DEPRIORITIZED** (0 real-bench-deck leverage — a parity-distance-metric
  drain only). The **spell-card-bridge Phase-1 lever is approaching its
  3-5-Tier-A-close ship threshold (currently at 2)**. The **covered-set
  extraction precursor LANDED** (`326023b4`, hardened to 100% at
  `02bf16bf`).
- **The orchestrator OWES a consolidated post-merge cron resync (§3a)** —
  spanning the Rust Effect merges + a batched roadmap fold + the Sothera
  residue note, deferred until the Rust agent's queue run ends to avoid
  the .pyd-rebuild race. A docs/bench slice must NOT perform it.

---

## 1. Current parity state (the honest numbers)

The authoritative metric lives in **`docs/POOL_PARITY.md`** (regenerated
by `scripts/measure_pool_parity.py`, cron-guarded). The published table
is **stale-by-design** until the §3a resync — it does not yet credit the
two Tier-A Effect closes (Radiant Strike, Seedship Impact). The
last-published snapshot:

| Tier | Count | % of pool |
|---|---:|---:|
| PROBED byte-equal (genuine real-EoE probe) | 56 | 11.8% |
| Effect+bridge covered (not individually probed) | 242 | 50.9% |
| bridge-admitted & bench-exercised | 0 | 0.0% |
| BLOCKED — genuinely_missing (new-Rust-Effect ask) | 6 | 1.3% |
| BLOCKED — blocked_non_effect (non-Effect gate) | 2 | 0.4% |
| BLOCKED — subsystem-gated / Effect-uncovered | 169 | 35.6% |
| **Pool total** | **475** | **100%** |

**Headline: ~298/475 (62.7%) byte-equal at the Effect+bridge level**
(the two Tier-A closes each drain the Effect-uncovered bucket; the exact
post-resync number lands when §3a regenerates `POOL_PARITY.md`).

> **CAVEAT — what this measures vs. what it does NOT.** This is
> Effect+bridge-level byte-equality evidence, **NOT full-game-trajectory
> parity**. PROBED = byte-equality on a *controlled* cross-engine state
> (a real EoE printing driven end-to-end), not a full random multi-turn
> game. Covered-by-construction only proves the card's Effect primitives
> all exist + bridge. The bench tier is the empirical full-trajectory
> signal but is **capped ~22-25 turns** and only over the loader-admitted
> subset. No tier claims the whole pool is byte-equal in real full-game
> trajectories — that remains the campaign's open frontier.

### The honest residue (the load-bearing "how far from parity" count)

Tracked in **`docs/residue_worklist.json`** (machine-readable,
cron-guarded; round-63 N5 ran a clean full re-walk at HEAD `e6f95002`,
all 20 entries re-confirmed honest, 0 stale). The two Tier-A Effect
closes do **NOT** touch the residue count (they drain pool coverage, not
genuinely_missing entries). The residue entries are still stamped at
`ce207345` (pre-Radiant-Strike) — the §3a resync re-stamps them to the
new HEAD (the structural-arm cadence requirement).

- **6 genuinely_missing** = TRUE new-Rust-Effect asks, all multi-round
  subsystem-entangled (NOT clean single-card closures anymore — the
  rounds 47-60 single-card-closure cadence is *exhausted*):
  **Astelli Reclaimer, Command Bridge, Lightstall Inquisitor (×2 arms),
  Meltstrider's Resolve, Pain for All, Roving Actuator.**
- **2 blocked_non_effect** = Effects shipped, gated by a non-Effect path:
  **Dauntless Scrapbot** (Lander token-registration substrate) and
  **Tractor Beam** (Aura control-swap composition). Different lane.
- **11 closed** = historical reclassifications, kept for the cron's
  regression check (they MUST stay live + bridged).

The 169-card subsystem-gated tail is itemised by gating subsystem in
**`docs/SUBSYSTEM_ROADMAP.md`** (79 single-gated + 90 multi-gated).

---

## 2. The CONTINUOUS-PIPELINE operating model (unchanged)

The campaign **no longer runs synchronized rounds**:

- **≤5 concurrent background agents.** The orchestrator keeps the pool
  filled with disjoint slices; an agent finishing frees a slot.
- **≤1 Rust agent at any time** (the `.pyd`-race rule). Rust slices
  serialize through `maturin develop --release -m rust/Cargo.toml`.
  Python / docs / bench slices parallelize freely.
- **Agents auto-merge when green** — no end-of-round merge barrier. The
  agent runs the gate, rebases cleanly on `origin/main`, merges
  `--no-ff`, pushes immediately, cleans its worktree, deletes its
  branch.
- **Worktree-per-feature** — `git worktree add
  ../mtg-bot-worktrees/<branch> -b feature/<branch> main`; the main
  checkout stays read-only context.

### Auto-merge is PRE-AUTHORIZED — do NOT cite the default rule

The project `CLAUDE.md` has a default "do not merge to `main` yourself"
rule. **It does NOT apply to this campaign's pre-authorized branch
families.** Per `feedback_mtg_bot_merge_as_you_go.md` (Cadence 2),
auto-merge `--no-ff` is pre-authorized for:

- `feature/phase5-ce-bridge-*` (cross-engine bridge slices)
- `feature/rust-*` (Rust substrate slices)
- `feature/phase6-*` (Phase 6 trajectory parity slices)
- `feature/bench-trajectory-*` (bench script + docs)
- `feature/fix-*` (divergence fixes, resync micro-slices, docs)
- `feature/docs-*` (docs refreshes — this slice's family)
- `feature/cross-controller-*` and `feature/cross-engine-*` (probes)

Do **not** re-litigate this. Round-38 agent E5 and the round-54
fold-deferral are the cautionary precedents — citing the default rule
forces a manual orchestrator merge and stalls the pipeline.

### The orchestrator post-merge cron-resync / fold loop

After each merge lands on `main`, the orchestrator (not the slice agent)
runs the **post-merge cron resync**:

1. Rebuild the `.pyd` if the merge touched Rust, re-run the gate on
   `main`, record the new pass count.
2. Run the staleness cron (`scripts/check_audit_coverage_staleness.py`).
3. Apply the **cron-prescribed resync** as a `feature/fix-*`
   auto-merge micro-slice: bump the sentinel counts, regenerate
   `RUST_EFFECT_COVERAGE.md` / `POOL_PARITY.md`, re-stamp
   `verified_absent_at_commit` on still-genuinely-missing residue
   entries to the new HEAD, fold any newly-closed/reclassified residue
   entries, sync `EOE_PROBE_READINESS_AUDIT.md` /
   `SUBSYSTEM_ROADMAP.md`.
4. Confirm `main` cron exits 0 "in-sync"; tooling tests green.

The resync is part of the loop, not optional cleanup.

### Cron staleness machinery + STALENESS-SENTINEL

`docs/residue_worklist.json` is read by
`scripts/check_audit_coverage_staleness.py` (never-blocking — a
*signal*, not a gate):

- **Sentinel count arm** (round-52): diffs the inventory sentinel
  counts (Rust Effect variant count; bridge-arm count; `_SAFE_*`
  counts). The two Tier-A closes each add 1 Effect + 1 bridge arm
  (`rust_effect_variants` 112→114, `bridge_arms` +2) — the §3a resync
  re-stamps these.
- **Lexical arm** (round-54): FAILs if a `genuinely_missing` entry's
  `claimed_missing_effect` (via `aliases`) exists as a live variant.
- **Structural arm** (round-55, the Pulsar-catch): every
  `genuinely_missing` entry MUST carry a SHA-shaped
  `verified_absent_at_commit`; goes stale if **any commit after it
  touched `rust/src/cards.rs` or `src/mtg_bot/parity/cross_engine.py`**.
  The Radiant Strike + Seedship merges touched both files — the cron is
  intentionally "needs-reverify" until §3a re-stamps. Plus the
  name-in-wired-arm catch (suppressible only by `name_in_arm_ack`).
- **blocked_non_effect arm** (round-56) + **cross-entry consistency
  guard** (round-63).

> **STALENESS-SENTINEL discipline.** `cross_engine.py` has three
> append-above-only sentinels; insert content **IMMEDIATELY ABOVE
> them, never below, never delete them**:
> - `# === PHASE5_BRIDGE_ARMS_INSERT_ABOVE_THIS_LINE ===` in
>   `_ta_dict_to_python_effect`
> - `# === PHASE5_BRIDGE_PIN_TESTS_INSERT_ABOVE_THIS_LINE ===` at EOF of
>   `tests/test_cross_engine_etb_triggers.py`
> - `# === PHASE5_PROBES_INSERT_ABOVE_THIS_LINE ===` at EOF of
>   `tests/test_parity_smoke.py`
> Most rebase conflicts are resolved by a mechanical insert-above
> re-splice. (Seedship's rebase resolved one such SEARCH_LIMITATIONS
> conflict keeping both entries.)

---

## 3. The PRIORITIZED ready backlog (actionable queue)

### Rust slot (≤1 at a time) — execute in this order

**Primary lane: Effect-uncovered Tier-A single-card closes**
(`docs/EFFECT_UNCOVERED_TIERA_MINISPECS.md` + `_BATCH2` + `_BATCH3` —
every card has an implement-ready mini-spec; the Python class already
exists for all of them, only the Rust variant + parse/to_dict/resolve +
bridge arm + pins + genuine real-EoE probe are new). Ordered
**smallest-one-shot-first**. **#1-2 are DONE — start at #3:**

| # | Card | Decks | Status | Why this slot |
|--:|---|---:|---|---|
| 1 | ~~Radiant Strike~~ ★ | 17,744 | **CLOSED `0c795e8c`** | `Sequence`+`GainLife` shell live; typed-OR destroy filter shipped + probed |
| 2 | ~~Seedship Impact~~ ★ | 13,908 | **CLOSED `9f107160`** | Lander-rider; destroy + Lander-pid arm shipped + probed |
| 3 | **Orbital Plunge** ★ | 28,629 | **NEXT** | Lander-rider; largest single deck-count clean drain; new = the excess-damage clamp + `excess>0` rider |
| 4 | **Depressurize** | 28,346 | ready | first pure-bespoke composite, no new substrate (UEOT-debuff → if eff_power≤0 destroy) |
| 5 | **Focus Fire** | 23,211 | ready | X-from-count family; new (creatures ∪ Spacecraft) set-union denominator; *verify the Rust attacking/blocking combat predicate first* |
| 6 | **Biosynthic Burst** | 22,799 | ready | counter + 3-keyword-UEOT + untap composite, all primitives shipped |
| 7 | **Diplomatic Relations** | 29,818 | ready | highest deck-count but LARGEST new surface (2-independent-target slot grammar) — last despite top decks |

★ = covered-primitive / Lander-rider (lowest-risk Perigee-r60 shape).
Close Encounter was **dropped** from Tier-A (verify-first found it
subsystem-entangled → Tier-C). Batch-2 (B1-B6) and batch-3 (B7 Darkness
43 decks + B8 graveyard-multi-select substrate) follow #7; **`_BATCH3`
§4 confirms NO batch-4 single-card doc is warranted — the cheap
single-card Tier-A lane is exhausted once this queue drains.**

> **The shared spell-card-bridge lever is the multiplier.** None of the
> 7 is bench-admissible today — closing a Tier-A Effect drains the
> Effect-uncovered bucket and makes the card genuinely
> cross-engine-probeable, **but the bench-loader admit stays gated** on
> a separate, not-yet-built `_printing_is_bridge_spell` predicate + a
> `CardDef` spell shape. That shared lever is ~2 Rust+bridge rounds
> (incremental, NOT all-31-at-once — all 7 Tier-A are targeted; see
> `docs/SPELL_CARD_BRIDGE_PHASE1_DESIGN.md`). **Sequence it once 3-5
> Tier-A Effects are closed.** Currently at **2** (Radiant Strike +
> Seedship) — **the lever is approaching its ship threshold; the next
> 1-3 Tier-A closes trip it.** Its critical-path Python precursor LANDED
> (covered-set extraction `326023b4`, hardened to 100% coverage at
> `02bf16bf`, verified byte-identical through both paths).

**Then, the subsystem Phase specs (verify-first KEEPS trimming these):**

1. **warp_cost Phase 2** — `docs/WARP_COST_PHASE2_DESIGN.md`
   (implement-ready, verified live at `0c795e8c`). Phase 1
   (`9f3ef1d1`) + Phase 1.5 (`ce207345`) are REALIZED. Phase 2 admits
   **EXACTLY ONE card — Timeline Culler** (+1 card / **+8,986 17lands
   decks**); it is the only pool card with
   `warp_castable_from_graveyard=True` OR `warp_additional_life_cost>0`.
   ONE Rust slice (surgical guardrail widening — delete only the 2
   rider clauses, keep the predicate name — + 2 CardPrinting/CardDef
   fields + a life debit + graveyard fall-through inside the existing
   `cast_creature_warp`; 14-pin plan + 2-arm real-EoE probe). The 26
   other multi-gated warp cards stay correctly declined; the harness
   mirror needs NO change.
2. **Tier-C substrate ladder** — the next substrate after the Tier-A
   lane (`docs/EFFECT_UNCOVERED_TIERC_CLOSEST_TO_A.md` cohort = 28
   cards / 94,339 decks gated by `{effect_uncovered,
   nonsafe_triggered_ability}`; nearly every bespoke Effect-half is
   itself a clean Tier-A-shaped close — it is a ONE-substrate cohort
   (the `_SAFE_TRIGGERS` allowlist-extension lever × the per-card
   Effect cadence already running), NOT 28 independent asks).
   **`docs/EFFECT_UNCOVERED_TIERC_RUNG1_SPEC.md` is implement-ready and
   verify-first CORRECTED the ladder** (the load-bearing accuracy fix
   the routines MUST inherit instead of re-deriving the stale tag):
   - Rung 1 is **2 cards, NOT 4** — Sunset Saboteur (6,375 decks) +
     Arabella, Abandoned Doll (0 decks). **6,375 EoE decks, NOT
     11,825.** Dyadrine EXCLUDED (`Event.YOU_ATTACK` has zero Rust
     support — admitting silently drops the whole trigger; also
     `{X}{G}{W}` raises in `_parse_mana_cost_string`). Alpharael
     EXCLUDED (`And(IsSelf, StateBound(VoidActive()))`, not bare
     `IsSelf` — a rung-6-class new-safe-predicate close, not rung 1).
   - **Honest bench-admit delta = +0 17lands decks** (Arabella is
     0-deck; Sunset Saboteur's leaf is TARGETED → its bench lever is
     deferred to a target-seating sub-substrate). The pool-parity
     Effect-uncovered drain = -2 cards (cohort 28→26 on the pool axis).
   - **Ship verdict: SPLIT** — 2 disjoint lever-a Rust slices + an
     Arabella-only lever-b micro-slice (different §2 verdicts; bundling
     produces an incoherent SL note).
   - **PROMOTE Exosuit Savior** (rung 2, ENTERS, 12,480 decks, the
     cohort's single cleanest Effect-half close) as the first close —
     **HARD prerequisite: its slice MUST verify-first its own
     targeting axis** (the ladder's "✅ cleanest leaf" tag did NOT
     check `requires_target`).
   - **Forward flag:** the cohort's true high-leverage lever is a
     **TARGET-SEATING SUB-SUBSTRATE**, not any single rung — most
     deck-bearing cohort cards ride targeted/agent-hooked leaves.
3. **Aura-attachment Phase 1 — DEPRIORITIZED** (re-verified live at
   `024baaa0`, merge `5a5a1583`). **Near-zero realizable leverage:**
   Phases 1-3 flip **0 real-bench decks** (the Phase-1 guardrail admits
   exactly 1 card, Frantic Strength, which has 0 17lands decks; the
   high-count Auras — Cryoshatter 29,288 / Tractor Beam 16,285 /
   Meltstrider 15,259 / Pain for All 4,367 / Hardlight 2,122 — are each
   on a non-Aura primary substrate, NOT aura-attachment-gated). It is a
   **parity-distance-metric drain only**, ~6-9 Rust rounds full. Same
   honest-zero outcome as cost-reduction — **do NOT chase this; it is
   below the Tier-C ladder and warp Phase 2.**
4. **cost-reduction Phase 1** — `docs/COST_REDUCTION_PHASE1_DESIGN.md`,
   realizable-0 near-term; lowest priority of the subsystem specs.

### 3a. The orchestrator's OWED deferred work (consolidated resync)

**This is OWED, not lost.** The Rust agent's Radiant Strike + Seedship
merges each flagged that the orchestrator owes a post-merge cron resync,
and the warp/Tier-C/Aura docs slices flagged batched folds. To avoid the
`.pyd`-rebuild race with the in-flight Rust queue agent, **these are
deliberately CONSOLIDATED into ONE resync pass, deferred until the Rust
agent's round-64-queue run ends.** That single pass owes:

1. **The consolidated post-merge cron resync spanning the Rust Effect
   merges** — `0c795e8c` (Radiant Strike) + `9f107160` (Seedship
   Impact) + any later Tier-A closes the queue lands before the resync
   fires. Rebuild the `.pyd` on `main`, re-run the gate, run
   `scripts/check_audit_coverage_staleness.py`, bump the sentinel
   counts (`rust_effect_variants` 112→114+, `bridge_arms` +2+),
   regenerate `RUST_EFFECT_COVERAGE.md` / `POOL_PARITY.md` (credits the
   Tier-A Effect-uncovered drains), and **re-stamp every still-
   genuinely-missing residue entry's `verified_absent_at_commit` to the
   new HEAD** (currently `ce207345` — the structural-arm cadence
   requirement; the merges touched both `cards.rs` and
   `cross_engine.py`).
2. **The batched SUBSYSTEM_ROADMAP leverage-resequencing fold** — the
   Aura-DEPRIORITIZED verdict, the warp Phase 2 (Timeline Culler,
   +8,986) row, the Tier-C ladder rung-1 correction (2 cards / 6,375 /
   +0 bench / SPLIT / Exosuit Savior promoted), and the corrected
   realizable Tier-A/Tier-C split. The docs slices deliberately left
   the larger Tier-ladder re-sequencing to this fold to avoid
   Tier-C-agent collision.
3. **The Sothera-the-Supervoid residue-re-walk note** — flagged by the
   Tier-C closest-to-A triage: Sothera the Supervoid is an exile-link
   bookkeeping composite with a `genuinely_missing` shape that no
   planned substrate reaches; pick it up in the next full
   `docs/residue_worklist.json` re-walk (do it in this resync pass or
   queue it as the next residue re-walk).

**The orchestrator OWNS `docs/POOL_PARITY.md`,
`docs/residue_worklist.json`, `docs/SUBSYSTEM_ROADMAP.md`, and
`docs/EOE_PROBE_READINESS_AUDIT.md` for this pass.** A docs/bench slice
must NOT perform the resync or edit those four files — only describe the
owed work (as this section does).

### Disjoint non-Rust lanes (run concurrently, never block the Rust slot)

- **Bench-divergence sweep** (`scripts/bench_trajectory_parity.py`) —
  the empirical signal generator and the **gate on new admits**. The
  round-68 post-warp-1.5 broad sweep was **CLEAN** (0 NEW divergence /
  233 games / all 5 warp creatures, `02bbc710`); the round-67 targeted
  warp-CAST lifecycle scout was salvaged + re-validated 20/20
  byte-equal (`9babc16f`). Cap sweeps ~50-60 games / ≤3-min wall.
- **The `_SAFE_TRIGGERS` creature-floor lever** — the standing ~50%
  bench FAIL_TIMEOUT is a near-creatureless-mirror artifact; the
  dominant drop is `unsafe_trigger` (52% of all raw creature copies).
  No single cheap §2-correct unlock; the honest lever is incremental
  safe-trigger widening + the Tier-A spell lane.
- **CardDef bridge-filter extensions** (`_SAFE_KEYWORDS` /
  `_SAFE_TRIGGERS` in `src/mtg_bot/parity/trajectory.py`). Only admit
  feature classes BOTH engines model identically; decline
  silent-mistranslation paths. Documented declines:
  `activated_abilities`, `static_abilities`, `warp_cost` (Phase 1/1.5
  REALIZED; Phase 2 is the Timeline Culler widening),
  `dynamic_pt_formula`, `BECOMES_TAPPED` without a bridge arm,
  `PutPlusOneCounterOnSelf` compound triggers, Or-form landfall.
- **Scoping / Phase design docs** — refresh a spec when its live
  file:lines move (write specs against the LIVE parser/enum/bridge,
  verified — labels lie). This is the lane that keeps trimming the
  optimistic ladder estimates.
- **Residue re-walk cadence** — re-run the full
  `docs/residue_worklist.json` re-walk when the structural cron flags
  staleness or every ~6-8 Rust merges (last clean was `e6f95002`); the
  Sothera note (§3a.3) is the next item it picks up.

---

## 4. Live caveats (read before you touch git)

- **Stale worktree-registration pollution.** `git worktree list`
  accumulates registrations from deleted-on-disk worktrees, skewing the
  orchestrator's in-flight proxy HIGH (safe-skip direction). Run
  `git worktree prune` before trusting the count.
  *(2026-05-16 cleanup: a conservative per-item-verified sweep removed
  247 fully-merged + clean abandoned worktrees; registry went
  297 → ~48 — the residual is the live pipeline set + unmerged/dirty
  branches, all skip-verified.)*
- **Recurring orphaned-working-tree cruft.** A worktree dir hits a
  transient Windows file-lock during/after `worktree remove`, leaving
  an orphaned dir + stale registration. `git worktree prune` cleans the
  registration; the dir may need a manual delete.
- **Bench creature-floor ~50% TIMEOUT drag** (see §3). Expected, not a
  regression — r62 133/240, r65 25/60 ≈ 42%, r68 123/233 ≈ 53%. A
  timed-out game yields zero divergence signal but is NOT an engine
  failure; it is the near-creatureless filtered mirror never reaching
  lethal before the turn cap.
- **Windows worktree-remove permission-denied.** Use `git worktree
  remove --force <path>` then `git worktree prune`. Standard cleanup
  incantation — do not retry-loop the bare remove.

---

## 5. The two scheduled remote routines

Two durable scheduled routines re-orient autonomously and self-prioritize:

- A **+2h** routine and a **+7h** routine (the next fire is the **+7h
  ≈ 04:10** routine). Each reads **this doc**
  (`docs/HANDOFF_CONTINUOUS_PIPELINE.md`) + the top of
  `hub/data/mtg_bot/worklog.json`, picks the highest-priority disjoint
  slice not already in flight, and runs it through the
  continuous-pipeline protocol (auto-merge when green).
- They run with the **bridge env** (`PYTHONPATH=src` + the shared
  `.venv-py313`; `maturin develop --release` after any Rust change) and
  are **guarded** — they respect the ≤5-agent / ≤1-Rust constraints and
  the worktree-staleness safe-skip bias (§4), so a stale in-flight
  proxy makes them *under*-launch, never double-launch a Rust slot.

Because they self-prioritize off this doc, **keeping §3's queue order +
§3a's owed-work map accurate is the load-bearing reason this doc
exists.** A stale handoff makes them mis-prioritize — e.g. chase the
near-exhausted single-card lane past #7, re-derive an implement-ready
spec, re-derive the stale Tier-C rung-1 tag (4 cards / 11,825 instead of
the corrected 2 / 6,375), chase the DEPRIORITIZED Aura lane, or
duplicate the orchestrator's owed resync inside a slice and trip the
.pyd race.

---

## 6. Preserved invariants from the original handoff (still true)

These carry over verbatim from `docs/HANDOFF_2026_05_16.md`:

### Venv + gate command

```bash
# from the worktree (docs-only slices need NO gate run — state that):
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe -m pytest \
  tests/test_parity_smoke.py tests/test_cross_engine_etb_triggers.py \
  tests/test_trajectory_parity.py tests/test_trajectory.py --no-cov -n 4

# after Rust changes, rebuild the .pyd FIRST:
VIRTUAL_ENV=../../mtg-bot/.venv-py313 \
  ../../mtg-bot/.venv-py313/Scripts/python.exe -m maturin develop \
  --release -m rust/Cargo.toml
```

Windows-native is canonical; the WSL2 `~/projects/mtg-bot` checkout is
stale and on hold. The gate pass count grows monotonically (213 at
start → 1449 at the Seedship merge); a green gate is the merge
precondition for code slices. Docs-only slices need **no gate run**.

### Sentinel discipline

The three append-above-only sentinels in §2 (STALENESS-SENTINEL). Never
insert below, never delete; mechanical insert-above re-splice resolves
nearly all rebase conflicts.

### Auto-merge families

The pre-authorized `feature/*` branch families in §2. Do not cite the
project `CLAUDE.md` default don't-merge rule for them.

### Picker shims

Test helper agents live in `tests/parity/_picker_shims.py` — import from
there, don't redefine inline. Available: `_PickFirstOpponentTargetAgent`,
`_PickFirstOpponentTargetCreaturePreferredAgent`,
`_PickFirstControlledCreatureAgent`, `_PickFirstLegalTargetAgent`,
`_DiscardFirstAgent`, `_SacrificeFirstAgent`, `_SurveilSendAllAgent`,
`_PickBottomLibraryAgent`. Add new shims there if needed.

### The §2 / bridge-correctness discipline

Every Rust slice does a **§2 audit**: confirm the new arm is
bridge-correct (both engines compute it identically, deterministically),
decline silent-mistranslation paths, and write the honest Effect-half /
full-card split. When the new code and the old code disagree, **the new
code written against the source of truth (Python) is right** — fix
whichever side is wrong, do not mirror a quirk
(`feedback_parity_new_code_is_right.md`). Document any deliberate
divergence in `docs/SEARCH_LIMITATIONS.md` at the time it lands. (Both
Tier-A closes did this — Radiant Strike found+fixed a real test bug
new-code-is-right; Seedship documented a deliberate mini-spec
field-carrying deviation, the Lander pid the spec sketched as a
field-free unit.)

### Token-printing registry

`register_token_printing(pid, py_printing)` + `clear_token_printings()`
from `cross_engine.py` — used by token-creation probes. The
cross-shape / cross-archetype pid-collision class was fixed round-57.
(Seedship Impact's Lander arm carries a `token_printing_id` exactly
like `Effect::CreateToken`; the bridge drops the pid and mints
intrinsically from `TOKEN_PRINTINGS`.)

---

## 7. Key documents (in order)

1. **This doc** — orientation for the continuous-pipeline phase.
2. `hub/data/mtg_bot/worklog.json` — the top ~2 continuous-pipeline-
   cycle entries are the source of truth for what landed this cycle.
3. `docs/POOL_PARITY.md` — tracked parity headline (stale until §3a).
4. `docs/residue_worklist.json` — the honest 6 + blocked_non_effect +
   closed (machine-readable, cron-guarded).
5. `docs/SUBSYSTEM_ROADMAP.md` — the 169-card subsystem-gated tail
   (orchestrator owns the §3a re-sequencing fold).
6. `docs/EFFECT_UNCOVERED_TIERA_MINISPECS.md` (+ `_BATCH2`, `_BATCH3`)
   — the ready single-card Rust queue (§3 primary lane; #1-2 closed,
   start #3; `_BATCH3` §4 confirms the lane exhausts after this queue).
7. `docs/EFFECT_UNCOVERED_TIERC_CLOSEST_TO_A.md` +
   `docs/EFFECT_UNCOVERED_TIERC_RUNG1_SPEC.md` — the next substrate;
   rung 1 verify-first-corrected to 2 cards / 6,375 / +0 bench / SPLIT,
   Exosuit Savior promoted.
8. `docs/WARP_COST_PHASE2_DESIGN.md` — Timeline Culler, +1 card /
   +8,986 decks, ONE Rust slice, implement-ready.
   `docs/AURA_ATTACHMENT_PHASE1_DESIGN.md` — DEPRIORITIZED (0
   real-bench leverage). `docs/COST_REDUCTION_PHASE1_DESIGN.md` —
   realizable-0, lowest priority.
9. `docs/SPELL_CARD_BRIDGE_PHASE1_DESIGN.md` — the shared Tier-A
   bench-admit carrier lever (ship at 3-5 Tier-A closes; at 2;
   covered-set precursor `326023b4` LANDED + hardened `02bf16bf`).
10. `docs/bench_trajectory_parity_smoke.md` — bench history (latest:
    round-68 post-warp-1.5 broad sweep CLEAN + round-67 salvage).
11. `docs/HANDOFF_2026_05_16.md` — original round-46 handoff
    (invariants preserved here, backlog stale).
12. Project `CLAUDE.md` — overall conventions (its default
    don't-merge rule does NOT apply to the pre-authorized families).

## 8. Tone for the session

- Concise updates; auto-merge confidence (don't re-litigate the merge
  protocol).
- Specific divergence reports + leverage estimates when proposing
  slices.
- **Verify-first KEEPS trimming optimistic estimates** — when a ladder
  doc claims N cards / M decks, the live-resolve walk routinely finds a
  smaller honest number (rung 1: 4→2 cards, 11,825→6,375 decks, +0
  bench). Trust the verify-first-corrected number, not the original
  ladder tag.
- "Yes" usually means "launch the proposed slice as described."
- Keep §3's queue order + §3a's owed-work map accurate — the scheduled
  routines self-prioritize off them.

Good luck.
