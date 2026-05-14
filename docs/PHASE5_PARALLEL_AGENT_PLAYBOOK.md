# Phase 5 Parallel-Agent Playbook

How two agents shipped Phase 5 cross-engine parity slices in parallel
across a 10-round arc without orchestrator merge bookkeeping. Use this
playbook to re-onboard future Phase 5 agents, or as a template for
analogous parallel-agent campaigns on other domains
(`feature/phase6-*`, `feature/rust-tdd-*`, future bridge work).

## 1. Overview

Phase 5 is the cross-engine ETB-trigger parity push: porting Rust
`Effect::*` variants to Python via `src/mtg_bot/parity/cross_engine.py`'s
`_ta_dict_to_python_effect` bridge, then pinning each arm with paired
real-EoE / synthetic ETB probes that exercise both engines side-by-side.

Cumulative across 10 rounds (2026-05-13/14):
- **59 slices** landed on main; gate **213 → 320** (+107 tests)
- **68 cross-engine ETB probes** (34 real-EoE + 29 synthetic + 21
  cross-controller; up from ~10 at round-1 entry)
- **18+ bridge arms** including: `sequence`, `if_you_do`, `create_token`,
  `mill_target_player`, `destroy_target`, `exile_target`,
  `return_to_hand`, `deal_damage`, `tap_target`, `discard_card`,
  `exile_target_creature_until_source_leaves`,
  `exile_opponents_nonland_permanent_until_leaves`,
  `owner_puts_target_artifact_or_creature_on_top_or_bottom_of_library`,
  `each_opponent_sacrifices_creature`, `each_opponent_mills_cards`,
  `pump_creatures_opponents_control_until_eot`,
  `put_plus_one_counter_on_each_creature_you_control`,
  `return_creature_from_your_graveyard_to_battlefield`
- **8 picker shims** hoisted to `tests/parity/_picker_shims.py`
- Cross-controller I-fix matrix spans 14+ lanes (I61, I65, I67, I70,
  I71, I74, I75, I76, I77, I78, I79, I80, I81, I82, I83 + several
  each-opponent / damage-to-opp closures)

## 2. The agent-side auto-merge protocol

Pre-authorized per
[`feedback_mtg_bot_merge_as_you_go.md`](../../.claude/projects/.../feedback_mtg_bot_merge_as_you_go.md)
**Cadence 2** — Phase 5 cross-engine bridge slices auto-merge to main
with `--no-ff`. Round 1 used "push and let orchestrator drain" and hit
O(N²) merge-conflict cost on the hot-lane sentinel region; round 2+
switched to agent-side rebase-before-push, which sequences merges
naturally.

Per-slice loop:

1. `git ls-remote --heads origin feature/<name>` — if non-empty, pick
   another name (race-free claim).
2. `git worktree add ../mtg-bot-worktrees/<name> -b feature/<name> main`
3. `cd ../mtg-bot-worktrees/<name> && git push -u origin feature/<name>`
   (push the empty branch immediately to lock the name on origin).
4. Build + commit + run the parity gate:
   `PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe -m pytest
   tests/test_parity_smoke.py tests/test_cross_engine_etb_triggers.py
   --no-cov -n 4`
5. `git fetch origin && git rebase origin/main` — resolve sentinel-marker
   conflicts mechanically (insert above the marker, never below; see §3).
6. `cd ../../mtg-bot && git pull --ff-only origin main &&
   git merge --no-ff feature/<name> -m "Merge feature/<name>: <summary>"`,
   re-gate, `git push origin main`.
7. On push race ("non-fast-forward"): in the worktree, `git reset --hard
   feature/<name>~`, re-pull, rebase, retry. Up to 3 retries observed.
8. `git worktree remove ../mtg-bot-worktrees/<name>`,
   `git branch -d feature/<name>`,
   `git push origin :refs/heads/<name>`.

Retry-rate measurements across rounds 2-10: 0% (round 8) to 83% (round 9).
Median ~17-33%. All retries resolved mechanically; zero silent drops,
zero orchestrator intervention.

## 3. Sentinel-marker convention

Three insert-above-only sentinels anchor the parallel-agent merge surface:

- `src/mtg_bot/parity/cross_engine.py` line ~2269 — inside
  `_ta_dict_to_python_effect`, immediately before the final `raise
  ValueError` on unknown kinds:
  `# === PHASE5_BRIDGE_ARMS_INSERT_ABOVE_THIS_LINE ===`
- `tests/test_cross_engine_etb_triggers.py` EOF — pin tests for new
  bridge arms: `# === PHASE5_BRIDGE_PIN_TESTS_INSERT_ABOVE_THIS_LINE ===`
- `tests/test_parity_smoke.py` EOF — real-EoE / cross-controller probes:
  `# === PHASE5_PROBES_INSERT_ABOVE_THIS_LINE ===`

**Insert above only.** Never below the marker. The `===` style is
deliberate — git's auto-merger sees the marker as a stable anchor and
both branches' insertions land above it, producing a single trivially-
resolvable conflict block (concat both, keep the marker last). Inserting
*below* the marker breaks this property — the next agent's diff anchors
against your insertion instead of the marker, and the conflict cascades.

**Round-9 retry-rate spike (83%, 5 retries / 6 slices)** — both agents
shipped 6 pure-probe slices into the same `PHASE5_PROBES_INSERT_ABOVE_
THIS_LINE` region in parallel; with 6 concurrent merges, almost every
slice hit a sentinel collision. All 5 retries resolved mechanically via
`git reset --hard origin/main` + insert-above. Round 10 dropped back to
20% naturally because work spread across cross_engine.py + audit doc +
probes (different sentinel regions).

The spike is **mostly-okay** — mechanical recovery is cheap (~1 min per
retry). Worth investing in sub-region sentinels only if pure-probe rounds
become the steady state AND the bridge-only single-leaf lane is still
producing volume. As of round 10, that lane is essentially exhausted (~2
clean candidates remain), so sub-region sentinels would over-engineer the
tail; if Phase 6 or a wider EoE probe push restarts pure-probe cadence,
revisit.

## 4. Picker-shim pattern

`tests/parity/_picker_shims.py` is the shared module of `Agent`
subclasses that mirror Rust's deterministic at-resolve target/discard
picks for cross-engine probes. **Import; do not redefine.**

Current shims:
`_PickFirstOpponentTargetAgent`,
`_PickFirstOpponentTargetCreaturePreferredAgent`,
`_PickFirstControlledCreatureAgent`,
`_PickFirstLegalTargetAgent`,
`_SacrificeFirstAgent`,
`_DiscardFirstAgent`,
`_SurveilSendAllAgent`,
`_PickBottomLibraryAgent`.

Add a new shim only when no existing shim's `choose_*` semantics match
Rust's deterministic behavior for the new arm. When two probes need
slightly different logic, **disambiguate by name** rather than collapsing
— see `_PickFirstOpponentTargetCreaturePreferredAgent` (creatures-over-
players) vs the plain `_PickFirstOpponentTargetAgent`. The hoist sweeps
in round 1 (5 shims) and round 3 (3 inline composer-shim cleanups)
established the pattern; later rounds hoisted opportunistically (round 6
added `_PickBottomLibraryAgent`).

## 5. Token-printing registry

Round 3 added `register_token_printing(pid, py_printing)` and
`clear_token_printings()` substrate to `cross_engine.py` to resolve
Rust's `token_printing_id: u32` to a matching Python `CardPrinting`.
Use it for any probe whose Rust effect is `Effect::CreateToken {
token_printing_id, ... }` (or composed arm that resolves through
create_token). Missing-registration raises `KeyError`; conflicting-pid
raises `ValueError`.

Before round 3, the I81 cross-controller probe did manual two-side
token construction. Don't do that anymore — register the token printing
once per probe and let `_ta_dict_to_python_effect` resolve it through
the bridge. This keeps both engines reading from a single source of
truth (the same dict the Rust effect serializes to).

## 6. Slice claim protocol

Two-step race-free claim:

1. `git ls-remote --heads origin feature/<name>` — if non-empty, the
   name is taken; pick another.
2. `git worktree add` then `git push -u origin feature/<name>` *before*
   doing any work. The empty branch on origin reserves the name.

This prevents two agents picking the same slice and racing each other's
work into a double-commit. The `git ls-remote` check alone is
insufficient — it's a TOCTOU race between check and push.

## 7. Anti-patterns (do NOT do)

- **Do not auto-merge non-Phase-5 branches.** Cadence-2 authorization is
  scoped to `feature/phase5-ce-bridge-*` (and the playbook/sentinel/
  shim-hoist refactors that support them). Other feature branches
  re-default to "push for review, wait for approval".
- **Do not skip the rebase-before-push step.** Pushing without rebasing
  on `origin/main` produces a non-fast-forward merge surface that
  serializes through orchestrator-side resolution (the round-1 failure
  mode). Always rebase, then merge to local main, then push.
- **Do not insert content below sentinels.** See §3 — anchor breaks,
  conflicts cascade.
- **Do not update worklog/todos from agents.** That's the orchestrator's
  job. Agents ship slices; orchestrator records them.
- **Do not modify Rust code from a Phase 5 ce-bridge slice.** Rust
  substrate work is out of scope for Cadence 2. If a probe needs new
  Rust substrate (a new `Effect::*` variant, a wider `parse_target_filter`
  shape), file it as a follow-up and ship a divergence-pin probe instead.

## 8. When to use this playbook

- **Re-onboarding future Phase 5 agents** — if the bridge-only lane
  reopens (new EoE set drop, new audit-doc refresh surfacing more
  drop-in candidates, Rust substrate work unblocks
  BLOCKED-BRIDGE-ARM cards), this is the reference cadence.
- **Analogous parallel-agent campaigns on other domains** — Phase 6
  trajectory parity, a Rust effect-coverage push, a wholesale
  refactor with many per-arm slices. The sentinel + auto-merge +
  shared-shim pattern transfers directly; just install the relevant
  insert-above markers and pre-authorize the auto-merge cadence in
  a feedback memory.
