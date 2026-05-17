# Cross-engine parity handoff — CONTINUOUS-PIPELINE phase (round ~65)

**This is the canonical "read this first" doc for the current phase.**
It supersedes `docs/HANDOFF_2026_05_16.md` (that doc was written ~round
46, in the *synchronized-rounds* era — its invariants are still true and
are preserved below, but its operating model and backlog are stale). If
you are a scheduled routine or a fresh session re-orienting, read this
doc + the top ~12 entries of `hub/data/mtg_bot/worklog.json`, then act.

---

## 0. TL;DR for the impatient

- **Tracked parity: 298 / 475 EoE cards (62.7%) byte-equal at the
  Effect+bridge level**, 56 of them pinned by a genuine real-EoE
  cross-engine probe. This is a *measured, regenerable* number
  (`docs/POOL_PARITY.md`), not a proxy. It is NOT full-game-trajectory
  parity (see the caveat in §1).
- **Honest residue: 6 distinct genuine-Rust-Effect cards** + 2
  `blocked_non_effect` + 11 `closed`. The 169-card subsystem-gated tail
  is the real long-pole.
- **Operating model: a CONTINUOUS PIPELINE** — ≤5 concurrent background
  agents, ≤1 Rust at a time, agents **auto-merge when green** (no
  end-of-round barrier), orchestrator does post-merge cron-resync/fold
  and refills the pool.
- **The ready Rust queue is the Effect-uncovered Tier-A lane**, ordered:
  **Radiant Strike → Seedship Impact → Orbital Plunge → Depressurize →
  Focus Fire → Biosynthic Burst → Diplomatic Relations**
  (`docs/EFFECT_UNCOVERED_TIERA_MINISPECS.md`, all implement-ready,
  smallest-one-shot-first). Then warp_cost Phase 1, then Aura Phase 1,
  then cost-reduction Phase 1 (Phase-1 specs all written and ready).
- **The disjoint non-Rust lanes** run in parallel: bench-divergence
  sweep (gates new admits), the `_SAFE_TRIGGERS` creature-floor lever,
  scoping docs, residue re-walk cadence.
- **Live caveats** worth knowing before you touch git: stale worktree
  registrations skew the in-flight proxy *high* (safe-skip direction),
  recurring orphaned-working-tree cruft, the ~50% bench FAIL_TIMEOUT
  creature-floor drag, and Windows worktree-remove permission-denied
  (use `--force` + `prune`).

---

## 1. Current parity state (the honest numbers)

The authoritative metric lives in **`docs/POOL_PARITY.md`** (regenerated
by `scripts/measure_pool_parity.py`, cron-guarded). As of round ~62-65:

| Tier | Count | % of pool |
|---|---:|---:|
| PROBED byte-equal (genuine real-EoE probe) | 56 | 11.8% |
| Effect+bridge covered (not individually probed) | 242 | 50.9% |
| bridge-admitted & bench-exercised | 0 | 0.0% |
| BLOCKED — genuinely_missing (new-Rust-Effect ask) | 6 | 1.3% |
| BLOCKED — blocked_non_effect (non-Effect gate) | 2 | 0.4% |
| BLOCKED — subsystem-gated / Effect-uncovered | 169 | 35.6% |
| **Pool total** | **475** | **100%** |

**Headline: 298/475 (62.7%) byte-equal at the Effect+bridge level.**

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
all 20 entries re-confirmed honest, 0 stale).

- **6 genuinely_missing** = TRUE new-Rust-Effect asks, all multi-round
  subsystem-entangled (NOT clean single-card closures anymore — the
  rounds 47-60 single-card-closure cadence is *exhausted*):
  **Astelli Reclaimer, Command Bridge, Lightstall Inquisitor (×2 arms),
  Meltstrider's Resolve, Pain for All, Roving Actuator.** Each parses to
  a bespoke Python composite with no shipped Rust Effect half to lean on
  (unlike the closed Perigee/Seedship/Faller cards).
- **2 blocked_non_effect** = Effects shipped, gated by a non-Effect path:
  **Dauntless Scrapbot** (Lander token-registration substrate) and
  **Tractor Beam** (Aura control-swap composition). NOT in the
  how-far-from-parity count — different lane.
- **11 closed** = historical reclassifications, kept for the cron's
  regression check (they MUST stay live + bridged; if one stops
  resolving, the closure prose went stale).

**"closed" precisely means:** the Effect arm shipped + bridged and the
card was reclassified out of the genuine-Effect ask. It does NOT mean
the full card is bench-admitted (it usually stays loader-gated on a
subsystem); it means the Effect-half is byte-equal-probeable and the
residue is now a *different* (non-Effect) lane.

The 169-card subsystem-gated tail is itemised by gating subsystem in
**`docs/SUBSYSTEM_ROADMAP.md`** (the data-driven "which subsystem next"
instrument — 79 single-gated + 90 multi-gated; closing a single-gated
subsystem flips its cards).

---

## 2. The CONTINUOUS-PIPELINE operating model

The campaign **no longer runs synchronized rounds** (the round-46
HANDOFF describes the old model). It is now a continuous pipeline:

- **≤5 concurrent background agents.** The orchestrator keeps the pool
  filled with disjoint slices; an agent finishing does not block the
  others — it just frees a slot the orchestrator refills.
- **≤1 Rust agent at any time** (the `.pyd`-race rule, unchanged from
  round 46). Rust slices serialize through
  `maturin develop --release -m rust/Cargo.toml`. Python / docs / bench
  slices parallelize freely. If a Rust slice is in flight, the next
  agent that wants Rust waits; non-Rust lanes proceed.
- **Agents auto-merge when green** — there is no end-of-round merge
  barrier. The agent runs the gate, rebases cleanly on `origin/main`,
  merges `--no-ff`, pushes immediately, cleans its worktree, deletes its
  branch. Push-immediately keeps sentinel-collision windows small (the
  round-24 validation still holds).

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
- `feature/cross-controller-*` and `feature/cross-engine-*` (probes)

Do **not** re-litigate this. Round-38 agent E5 and the round-54
fold-deferral are the cautionary precedents — citing the default rule
forces a manual orchestrator merge and stalls the pipeline.

### The orchestrator post-merge cron-resync / fold loop

After each merge lands on `main`, the orchestrator (not the slice agent)
runs the **post-merge cron resync**:

1. Rebuild the `.pyd` if the merge touched Rust, re-run the gate on
   `main`, record the new pass count.
2. Run the staleness cron (`scripts/check_audit_coverage_staleness.py`)
   — it diffs the sentinel inventory counts AND the per-entry residue
   claims (lexical + structural arms; see §2 STALENESS-SENTINEL below)
   and reports drift.
3. Apply the **cron-prescribed resync** as a `feature/fix-*`
   auto-merge micro-slice: bump the sentinel counts, regenerate
   `RUST_EFFECT_COVERAGE.md` / `POOL_PARITY.md`, re-stamp
   `verified_absent_at_commit` on still-genuinely-missing residue
   entries to the new HEAD (the cadence requirement — see below), fold
   any newly-closed/reclassified residue entries, sync
   `EOE_PROBE_READINESS_AUDIT.md` / `SUBSYSTEM_ROADMAP.md`.
4. Confirm `main` cron exits 0 "in-sync"; tooling tests green
   (~86 staleness/tooling tests).

The resync is part of the loop, not optional cleanup — a merge that
changes the Rust Effect enum or `_SAFE_*` allowlists makes the cron go
"needs-reverify" by design until the resync re-stamps it.

### Cron staleness machinery + STALENESS-SENTINEL

`docs/residue_worklist.json` is read by
`scripts/check_audit_coverage_staleness.py` (never-blocking — the
post-commit hook ignores its exit code; it is a *signal*, not a gate):

- **Sentinel count arm** (round-52): diffs the inventory sentinel
  counts (Rust Effect variant count — 112 at HEAD `e6f95002`; bridge-arm
  count; `_SAFE_TRIGGERS` / `_SAFE_KEYWORDS` / `safe_effect_keys`
  counts). A merge that adds an Effect/arm/safe-key bumps these; the
  resync re-stamps them.
- **Lexical arm** (round-54): FAILs if a `genuinely_missing` entry's
  `claimed_missing_effect` (resolved through `aliases`) actually exists
  as a live Rust variant + wired bridge arm.
- **Structural arm** (round-55, the Pulsar-catch): every
  `genuinely_missing` entry MUST carry a SHA-shaped
  `verified_absent_at_commit`; it goes stale (`residue_needs_reverify`)
  if **any commit after it touched `rust/src/cards.rs` or
  `src/mtg_bot/parity/cross_engine.py`** (the only two files that can
  ship/bridge an Effect — the exact Pulsar mechanism). Plus the
  non-lexical name-in-wired-arm catch (a card whose printed name appears
  in a live wired bridge arm whose kind resolves to a live variant is
  flagged regardless of lexical similarity), suppressible only by an
  audited per-arm `name_in_arm_ack`.
- **blocked_non_effect arm** (round-56): asserts every name in a
  `blocked_non_effect` entry's `shipped_variants` IS a live Rust
  variant (catches a silent regression to actually-missing) and that it
  records its `non_effect_blocker`.
- **Cross-entry consistency guard** (round-63): a card cannot hold
  contradictory statuses across entries.

> **STALENESS-SENTINEL discipline.** `cross_engine.py` has three
> append-above-only sentinels; insert your content **IMMEDIATELY ABOVE
> them, never below, never delete them**:
> - `# === PHASE5_BRIDGE_ARMS_INSERT_ABOVE_THIS_LINE ===` in
>   `_ta_dict_to_python_effect`
> - `# === PHASE5_BRIDGE_PIN_TESTS_INSERT_ABOVE_THIS_LINE ===` at EOF of
>   `tests/test_cross_engine_etb_triggers.py`
> - `# === PHASE5_PROBES_INSERT_ABOVE_THIS_LINE ===` at EOF of
>   `tests/test_parity_smoke.py`
> Most rebase conflicts in this campaign are resolved by a mechanical
> insert-above re-splice.

---

## 3. The PRIORITIZED ready backlog (actionable queue)

### Rust slot (≤1 at a time) — execute in this order

**Primary lane: Effect-uncovered Tier-A single-card closes**
(`docs/EFFECT_UNCOVERED_TIERA_MINISPECS.md` — every card has a
WARP_COST_PHASE1-grade implement-ready mini-spec; the Python class
already exists for all of them, only the Rust variant + parse/to_dict/
resolve + bridge arm + pins + genuine real-EoE probe are new). Ordered
**smallest-one-shot-first** (the continuous-pipeline criterion):

| # | Card | Decks | Why this slot | Est |
|--:|---|---:|---|---|
| 1 | **Radiant Strike** ★ | 17,744 | cheapest of all — `Sequence`+`GainLife` shell already live; only the inner typed-OR destroy filter is new | 1 rd |
| 2 | **Seedship Impact** ★ | 13,908 | Lander-rider; destroy + Lander leaf shipped, only the artifact-OR-enchantment filter + `mv≤2` rider new | 1 rd |
| 3 | **Orbital Plunge** ★ | 28,629 | Lander-rider; largest single deck-count clean drain; new = the excess-damage clamp + `excess>0` rider | 1 rd |
| 4 | **Depressurize** | 28,346 | first pure-bespoke composite, no new substrate (UEOT-debuff → if eff_power≤0 destroy) | 1 rd |
| 5 | **Focus Fire** | 23,211 | X-from-count family; new (creatures ∪ Spacecraft) set-union denominator + base offset; *verify the Rust attacking/blocking combat predicate first* | 1 rd |
| 6 | **Biosynthic Burst** | 22,799 | counter + 3-keyword-UEOT + untap composite, all primitives shipped | 1 rd |
| 7 | **Diplomatic Relations** | 29,818 | highest deck-count but LARGEST new surface (2-independent-target slot grammar) — last despite top decks | 1 rd |

★ = covered-primitive / Lander-rider (lowest-risk Perigee-r60 shape).
Close Encounter was **dropped** from Tier-A (verify-first found it
subsystem-entangled: additional-cost-choice + warp_cost → Tier-C).

> **The shared spell-card-bridge lever is the multiplier.** None of the
> 7 is bench-admissible today — `CardDef.card_type` ∈ {Land, Creature};
> `_printing_is_bridge_simple_creature` rejects `spell_effect is not
> None`. Closing a Tier-A Effect drains the pool-parity Effect-uncovered
> bucket and makes the card genuinely cross-engine-probeable (via the
> synthetic-stack-resolve driver on the REAL printing — real EoE
> consumer, not a synthetic CardDef), **but the bench-loader admit stays
> gated** on a separate, not-yet-built `_printing_is_bridge_spell`
> predicate + a `CardDef` spell shape. That shared lever is ~1 Rust+
> bridge round and unlocks ALL ~31 Tier-A cards' bench admit at once
> (the Station-subsystem analogue for Warmaker/Extinguisher). **Sequence
> it once 3-5 Tier-A Effects are closed** (enough to make its first real
> bench consumers non-trivial). This is the Effect-half-vs-full-card
> split rounds 32/52 already shipped — the per-card slices close the
> Effect; the lever later flips the cards.

**Then, the subsystem Phase-1 specs (all implement-ready, written):**

1. **warp_cost Phase 1** — `docs/WARP_COST_PHASE1_DESIGN.md`. Exactly 2
   cards (Red Tiger Mechan + Bygone Colossus, pure fixed-cost warp,
   +6,450 decks); Timeline Culler deferred Phase 2. ~1-2 Rust rounds.
   The lightest cost-mechanic (fixed alternative `ManaCost` + a
   deterministic end-step exile, no `Condition`-grammar). **Confirmed
   first** of the cost-mechanics. *Note:* this may already be in flight
   or merged — check `git log` / the worklog before claiming it.
2. **Aura-attachment Phase 1** — `docs/AURA_ATTACHMENT_PHASE1_DESIGN.md`.
   The static P/T-or-keyword Aura sub-shape S1. Largest §2-declined
   substrate (~5-7 Rust rounds full; Phase 1 is the contained slice).
   Sequenced AFTER warp.
3. **cost-reduction Phase 1** — `docs/COST_REDUCTION_PHASE1_DESIGN.md`.
   Sub-shape A (the 2 spell-local boolean-condition cards). Reuses
   warp's Phase-1 Rust scaffolding — the implementing agent MUST
   re-verify warp's file:lines against the post-warp-merge tree. AFTER
   Aura.

### Disjoint non-Rust lanes (run concurrently, never block the Rust slot)

- **Bench-divergence sweep** (`scripts/bench_trajectory_parity.py`,
  results in `docs/bench_trajectory_parity_smoke.md`). This is the
  empirical signal generator and the **gate on new admits** — any
  filter widen / new admit must pass a post-admit broad sweep before it
  counts (round-61 N3 caught a real latent shockland mana-ability
  divergence exactly this way; round-62 fixed it). Cap sweeps ~50-60
  games / ≤3-min wall per agent (round-40/44 budget lesson).
- **The `_SAFE_TRIGGERS` creature-floor lever** (round-65 finding,
  `docs/bench_trajectory_parity_smoke.md` round-65 entry). The standing
  ~50% bench FAIL_TIMEOUT is a near-creatureless-mirror artifact;
  round-64/65 quantified it: only **19% of raw creature copies survive
  the admit gate, and the dominant drop (3.7× the next, 52% of all raw
  copies) is `unsafe_trigger`** — a triggered ability outside
  `_SAFE_TRIGGERS`. The creature-floor is overwhelmingly a
  `_SAFE_TRIGGERS` allowlist-coverage gap (lane 2 below), NOT keyword/
  cost/dynamic-P/T. There is no single cheap §2-correct unlock; the
  honest lever is incremental safe-trigger widening + the Tier-A spell
  lane. `--require-creatures N` is a reporting-honesty option (reclass
  the `never_cast` population out of FAIL_TIMEOUT) but converts nothing.
- **CardDef bridge-filter extensions** (`src/mtg_bot/parity/
  trajectory.py` `_SAFE_KEYWORDS` / `_SAFE_TRIGGERS`). Each safe widen
  admits more EoE archetypes → real bench signal. **Bridge-correctness
  discipline (CRITICAL, unchanged from round 42):** only admit feature
  classes BOTH engines model identically; decline silent-mistranslation
  paths. Documented declines: `activated_abilities`, `static_abilities`,
  `warp_cost`, `ward_cost`, `dynamic_pt_formula`, `BECOMES_TAPPED`
  without a bridge arm, `PutPlusOneCounterOnSelf` compound triggers,
  Or-form landfall. Do not break the pattern.
- **Scoping / Phase-1 design docs** — the remaining subsystem scoping
  is largely done; refresh a Phase-1 spec when its live file:lines move
  (the round-60 lesson: write specs against the LIVE parser/enum/bridge,
  verified — labels lie).
- **Residue re-walk cadence** — re-run the full
  `docs/residue_worklist.json` re-walk when the structural cron flags
  staleness or every ~6-8 Rust merges (round-63 N5 was the last clean
  one at `e6f95002`).

---

## 4. Live caveats (read before you touch git)

- **Stale worktree-registration pollution.** `git worktree list`
  accumulates registrations from worktrees that were deleted on disk but
  not pruned. This **skews the orchestrator's in-flight-agent proxy
  HIGH** — i.e. it over-counts active agents, which biases toward
  *safe-skip* (the orchestrator declines to launch into a slot it
  wrongly thinks is occupied). Safe direction, but run
  `git worktree prune` before trusting the count.
- **Recurring orphaned-working-tree cruft.** The same pattern recurs:
  a worktree dir hits a transient Windows file-lock during/after
  `worktree remove`, leaving an orphaned dir + a stale registration.
  `git worktree prune` cleans the registration; the dir may need a
  manual delete. Harmless to the merge, noisy in `git worktree list`.
- **Bench creature-floor ~50% TIMEOUT drag** (see §3). Expected, not a
  regression — every recent broad sweep reports it (r62 133/240, r65
  25/60 = ~42%). A timed-out game yields zero divergence signal but is
  NOT a failure of the engines; it is the near-creatureless filtered
  mirror never reaching lethal before the turn cap.
- **Windows worktree-remove permission-denied.** `git worktree remove`
  intermittently fails with a Windows permission error if any handle is
  still open. Use `git worktree remove --force <path>` then
  `git worktree prune`. This is the standard cleanup incantation for
  this campaign — do not retry-loop the bare remove.

---

## 5. The two scheduled remote routines

Two durable scheduled routines re-orient autonomously and self-prioritize:

- A **+2h** routine and a **+7h** routine. Each reads **this doc**
  (`docs/HANDOFF_CONTINUOUS_PIPELINE.md`) + the top of
  `hub/data/mtg_bot/worklog.json`, picks the highest-priority disjoint
  slice not already in flight, and runs it through the
  continuous-pipeline protocol (auto-merge when green).
- They run with the **bridge env** (`PYTHONPATH=src` + the shared
  `.venv-py313`; `maturin develop --release` after any Rust change) and
  are **guarded** — they respect the ≤5-agent / ≤1-Rust constraints and
  the worktree-staleness safe-skip bias (§4), so a stale in-flight proxy
  makes them *under*-launch, never double-launch a Rust slot.

Because they self-prioritize off this doc, **keeping §3's queue order
accurate is the load-bearing reason this doc exists.** A stale handoff
makes them mis-prioritize (e.g. chase the exhausted single-card lane, or
re-derive a spec that is already implement-ready).

---

## 6. Preserved invariants from the original handoff (still true)

These carry over verbatim from `docs/HANDOFF_2026_05_16.md` — they did
not change with the pipeline switch:

### Venv + gate command

```bash
# from the worktree:
PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe -m pytest \
  tests/test_parity_smoke.py tests/test_cross_engine_etb_triggers.py \
  tests/test_trajectory_parity.py tests/test_trajectory.py --no-cov -n 4

# after Rust changes, rebuild the .pyd FIRST:
VIRTUAL_ENV=../../mtg-bot/.venv-py313 \
  ../../mtg-bot/.venv-py313/Scripts/python.exe -m maturin develop \
  --release -m rust/Cargo.toml
```

Windows-native is canonical; the WSL2 `~/projects/mtg-bot` checkout is
stale and on hold. The gate pass count grows monotonically with the
campaign (213 at start → 1397 at round 62); a green gate is the merge
precondition for code slices. (Docs-only slices — like this one — need
**no gate run**; state that in the slice report.)

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
full-card split (the Effect closes + is genuinely probed; the full card
may stay loader-gated on a separate lever — state this in the SL-style
commit note + the residue fold). When the new code and the old code
disagree, **the new code written against the source of truth (Python) is
right** — fix whichever side is wrong, do not mirror a quirk
(`feedback_parity_new_code_is_right.md`). Document any deliberate
divergence in `docs/SEARCH_LIMITATIONS.md` at the time it lands.

### Token-printing registry

`register_token_printing(pid, py_printing)` + `clear_token_printings()`
from `cross_engine.py` — used by token-creation probes to resolve Rust's
`token_printing_id: u32` to a Python `CardPrinting`. The cross-shape /
cross-archetype pid-collision class was fixed round-57 (`_seat_token_
printings` clears only the per-game map at pass entry, preserving the
round-51 shape-keyed cache).

---

## 7. Key documents (in order)

1. **This doc** — orientation for the continuous-pipeline phase.
2. `hub/data/mtg_bot/worklog.json` — per-round narrative; the top ~12
   entries cover rounds ~54-65 (real-card pivot, pool-parity metric,
   subsystem inflection, shockland fix, the scoping/Phase-1 specs, the
   continuous-pipeline switch).
3. `docs/POOL_PARITY.md` — the tracked parity headline (regenerable).
4. `docs/residue_worklist.json` — the honest 6 + blocked_non_effect +
   closed (machine-readable, cron-guarded).
5. `docs/SUBSYSTEM_ROADMAP.md` — the 169-card subsystem-gated tail by
   gating subsystem + leverage.
6. `docs/EFFECT_UNCOVERED_TIERA_MINISPECS.md` — the ready single-card
   Rust queue (the §3 primary lane).
7. `docs/WARP_COST_PHASE1_DESIGN.md` /
   `docs/AURA_ATTACHMENT_PHASE1_DESIGN.md` /
   `docs/COST_REDUCTION_PHASE1_DESIGN.md` — the subsystem Phase-1 specs.
8. `docs/bench_trajectory_parity_smoke.md` — bench results history;
   latest is the round-65 creature-floor quantification.
9. `docs/HANDOFF_2026_05_16.md` — the original round-46 handoff
   (synchronized-rounds era; invariants preserved here, backlog stale).
10. `docs/PHASE5_PARALLEL_AGENT_PLAYBOOK.md` /
    `docs/PHASE6_TRAJECTORY_PARITY.md` — the canonical playbook +
    Phase 6 scaffold.
11. Project `CLAUDE.md` — overall conventions (but see §2: its
    default don't-merge rule does NOT apply to the pre-authorized
    families).

## 8. Tone for the session

- Concise updates; auto-merge confidence (don't re-litigate the merge
  protocol).
- Specific divergence reports + leverage estimates when proposing slices.
- "Yes" usually means "launch the proposed slice as described."
- Keep §3's queue order accurate — the scheduled routines self-prioritize
  off it.

Good luck.
