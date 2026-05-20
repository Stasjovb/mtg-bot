# Session synthesis — flip-ready GO/NO-GO artifact (2026-05-19 → 2026-05-20)

**One-doc-to-read** capturing where the SoT flip stands after a major
flip-prep campaign. Cites commits and docs; does not re-litigate them.

Repo HEAD this doc summarizes: **`de0aff68`** (`feature/sot-flip-cutover-plan-update` merge).

## Headline — three lines

1. **Path A (close all 3 broader-sweep axes pre-flip) is effectively
   complete in <1 cycle:** 2 of 3 closed on `origin/main` (`7a127e87`,
   regression-verified at `b5035028`); the 3rd is **closed in the
   local worktree** (`16c88726` on `feature/battlefield-axis-closure`)
   and waiting on a push + merge to land on `origin/main`.
2. **The remaining GO decision is Option P1 (flip immediately on the
   post-battlefield-closure merge) vs Option P2 (P1 + one extra
   `mtg_bot iterate` with the shadow-checker first).** Both options
   require Step 0 (a fresh C4 sweep against the actual flip commit).
   See `docs/SOT_FLIP_CUTOVER_PLAN.md` §8.5.
3. **Next 4 things, in order:** (1) land slice 15, (2) push + merge
   battlefield closure, (3) re-run the v11 sweep on the flip commit,
   (4) execute B3-S5 (atomic `decision_source = "python" → "rust"`).
   §5 below.

---

## §1 What this session shipped

Authoritative list (`git log --oneline origin/main cd330540..HEAD`,
filtered to `Merge feature/`):

| Merge SHA | Branch | One-line |
|---|---|---|
| `de0aff68` | `feature/sot-flip-cutover-plan-update` | Update SOT_FLIP_CUTOVER_PLAN.md §8 to reflect 2-of-3 axes closed + battlefield in flight; Path A near-complete; user GO calculus reduced to immediate-vs-one-more-iterate |
| `b5035028` | `feature/broader-archetype-sweep-300-359` | v10 post-closure regression-verify (298/300 PASS, 0 priority_player, 0 blocker, 2 battlefield); confirms `7a127e87` is regression-free; no new axes surfaced |
| `7a127e87` | `feature/priority-player-blocker-closure` | Close priority_player + blocker LEGAL_SET_EQ axes via ~30-LoC adapter guard in `rust_engine_adapter.py` (19/1500 cumulative residuals → 0; per `4b47b701` investigation) |
| `d99d85f3` | `feature/battlefield-axis-investigation` | Deep-trace of battlefield STATE_EQ residual axis (4 v9 repros); root cause + closure scope documented + regression pin filed |
| `f4314ea1` | `feature/broader-sweep-consolidated` | v5–v9 cross-slice summary doc + flip-readiness update (3 residual axes, 23/1500 cumulative, Path A vs Path B framing) |
| `fee5888d` | `feature/broader-archetype-sweep-240-299` | v9 scale-verify on archetypes 240-299 (290/300 PASS, 10 residuals); NEW battlefield STATE_EQ axis surfaced |
| `c2487640` | `feature/broader-archetype-sweep-180-239` | v8 scale-verify on archetypes 180-239 (291/300 PASS, 9 residuals); NEW blocker LEGAL_SET_EQ axis surfaced |
| `3b7809ed` | `feature/broader-archetype-sweep-120-179` | v7 scale-verify on archetypes 120-179 (299/300 PASS, 1 priority_player residual) |
| `820ba720` | `feature/broader-archetype-sweep` | v6 scale-verify on archetypes 60-119 (297/300 PASS, 3 priority_player residuals) |
| `4b47b701` | `feature/priority-player-investigation` | Deep-trace of priority_player STATE_EQ axis (15 cumulative); root cause + closure path documented + regression pin filed |

Net: **5 broader-sweep slices (v5–v9 series) + 2 deep-trace investigations
+ 1 consolidated cross-slice summary + 1 priority/blocker closure + 1
post-closure regression-verify (v10) + 1 cutover-plan §8 update** — 10
session-cohort merges, plus the orthogonal Rust slice 12/13/14 + probe
batch SSS/UUU/WWW + divergence pin RRR/TTT/VVV lanes (mentioned in the
git log but not part of the flip-prep cohort).

---

## §2 Residual axis status table

| # | Axis | State | Closure commit | Investigation doc | Pre-close cumulative | Post-close cumulative |
|---|---|---|---|---|---:|---:|
| 1 | `STATE_EQ::fields:priority_player` (G5-family long-tail) | **CLOSED on origin/main** | `7a127e87` (underlying `5b8608d1`) | [`PRIORITY_PLAYER_AXIS_INVESTIGATION.md`](PRIORITY_PLAYER_AXIS_INVESTIGATION.md) | **15/1500** | **0/1500** (v10 regress-verified 0/300 on NEW archetypes 300-359) |
| 2 | `LEGAL_SET_EQ::fields:blocker` (Rust-extra blocker) | **CLOSED on origin/main** — same root cause as axis 1, closed by the same merge | `7a127e87` | [`PRIORITY_PLAYER_AXIS_INVESTIGATION.md`](PRIORITY_PLAYER_AXIS_INVESTIGATION.md) | **4/1500** | **0/1500** (v10 regress-verified 0/300) |
| 3 | `STATE_EQ::fields:battlefield` (un-migrated Effect arms) | **CLOSED in local worktree; NOT on origin/main yet** — `feature/battlefield-axis-closure` at `16c88726` (closure commit `7db0590b` + doc updates `16c88726`); awaiting push + merge | (pending — `7db0590b`) | [`BATTLEFIELD_AXIS_INVESTIGATION.md`](BATTLEFIELD_AXIS_INVESTIGATION.md) | **6/1800** cumulative (v9: 4 + v10: 2) | **expected 0/1800** once landed + re-swept; not yet measured at the closure tip |

**Cumulative effective scale-PASS post-axis-1-and-2 closures (on
`origin/main` today) = 1794/1800 (99.67%)** — the 6 remaining are
all axis 3 (battlefield), all share the captured root cause, all are
fixed by the worktree-only closure waiting to land.

---

## §3 GO-decision recap — Option P1 vs Option P2

Per [`SOT_FLIP_CUTOVER_PLAN.md`](SOT_FLIP_CUTOVER_PLAN.md) §8.5.

**Option P1 — GO immediately on the post-battlefield-closure merge.**
Once `feature/battlefield-axis-closure` lands, all 3 broader-sweep
residual axes are closed at scale; cumulative is expected 0/1800
FAIL_DIVERGENCE. Operational requirements (per §8.4):

1. **Step 0** — re-run the C4 trajectory-parity bench
   (`scripts/bench_trajectory_parity.py`) against the actual
   flip-candidate commit. Recommended scale: ≥700 games / ≥7 archetype
   windows / ≥5 seed offsets (terminal-cap v5_terminal evidence at
   `ca569619`, 300 games at cap=20000, already exceeds this — a fresh
   sweep at the flip commit just pins no-regression).
2. **B3-S5** — atomic flip `decision_source = "python" → "rust"`. The
   shadow-checker stays active during bake-in.

**Option P2 — P1 + one extra `mtg_bot iterate` with the
shadow-checker active before B3-S5.** Catches any
production-distribution-but-not-bench divergence the C4 archetype
windows might miss. Cost: ~1 iterate run (hours, not days). Upside:
production-representative volume completing with zero shadow-divergence
is the original bake-in exit criterion.

**The two options are NOT mutually exclusive.** P2 is operational
hygiene on top of P1. The honest read: **P1+P2 is the recommended
posture**; the dashed-line trade-off ("flip without iterate" vs "flip
after one more iterate") is a small one-iterate delta, not the ~4–8
cycle delta that Path A vs Path B was originally framing.

**Exact commit to flip on:** TBD — depends on which sibling lanes land
between now and the flip. Earliest candidate is the merge of
`feature/battlefield-axis-closure` to `origin/main` (currently
`16c88726` locally). Slice 15 (`feature/rust-slice-15-vvv-pin-1`) is
orthogonal and does not gate the flip; if it lands first the flip
commit just stacks on top.

---

## §4 What's NOT closed — honest residuals

- **Battlefield closure is committed locally but not pushed.** The
  worktree at `mtg-bot-worktrees/battlefield-axis-closure` is at
  `16c88726` (closure `7db0590b` + docs `16c88726`); not on origin or
  on `origin/main`. Until pushed + merged, the §8 doc still calls
  this lane "IN FLIGHT". Per §6 below this is the second step in the
  GO sequence.
- **Axis 4 (deferred alt-cost flags)** remains OPEN per
  [`FLIP_READINESS_EVIDENCE_2026_05_19.md`](FLIP_READINESS_EVIDENCE_2026_05_19.md)
  §0 — kicker / impending / granted-warp / Room-half / X /
  restricted-coin / convoke have **NO Rust CastSpell emission site**
  today (`state_ops_legal.rs:500-511` emits the base no-flags
  6-tuple). The C1 mana/target/additional-cost predicates compose via
  designed extension points the moment any axis-4 dimension acquires
  an emission site. This is "no live emission site by construction"
  — bounded by the C6 hard-admit pin (fail-loud, not silent-degrade).
  This is NOT a flip-blocker today.
- **Cumulative 1794/1800 is effective, not measured end-to-end at the
  flip tip.** It's arithmetic from "1796/1800 pre-battlefield-closure
  + axis-3 fix collapses the battlefield 6 to ~0". A true measurement
  requires the battlefield closure to land and then a fresh v5–v10
  re-sweep at the post-closure tip. The v10 sweep (`b5035028`)
  measured 298/300 directly for the NEW 300-359 archetypes; the older
  0-299 numbers are inherited from v5-v9 (the priority+blocker
  closure was regress-verified by the 40-game
  `bench_trajectory_parity.py` repro cluster, not by re-running v5-v9
  individually).
- **Axis 1 (full card pool) — the 161 BLOCKED cards.** Per
  [`POOL_PARITY.md`](POOL_PARITY.md), 161/475 (33.9%) of the EoE pool
  is BLOCKED long-tail; this is PARTIAL on the user's 2026-05-20
  4-axis bar and grinds slowly via the probe/Rust-slice cadence. The
  session's TTT (slice 14) + RRR (slice 13) + slice 12 closures
  unblocked a small handful (Lost in Space + 3 zone-change-reset
  cards via slice 13; some Lander-summoning_sick cards via slice 14
  — exact deltas in the per-slice PR worklogs). The exact updated
  BLOCKED count needs a `POOL_PARITY.md` refresh; the doc as written
  may slightly overstate. **This does not block the flip** — the
  loader-admit denominator (~20% deck-weighted non-land) is the true
  flip surface, not the raw 475.
- **Slice 15 (`feature/rust-slice-15-vvv-pin-1`) is in flight in a
  sibling lane.** Orthogonal to the 3 broader-sweep axes; its merge
  does not gate the flip but may co-arrive with the battlefield merge.
- **88 sibling worktrees exist under `mtg-bot-worktrees/`.** Per the
  earlier cleanup agent's report, ~16 of those were merged-but-dirty
  (no removal after merge — they're stale). The 4 still doing
  flip-prep work right now are
  `session-flip-ready-synthesis` (this one),
  `battlefield-axis-closure` (closure committed, not pushed),
  `broader-archetype-sweep-360-419` (v11 sweep, at `de0aff68` — the
  orchestrator-shell process the task brief mentions), and
  `rust-slice-15-vvv-pin-1` (orthogonal slice).

---

## §5 The next 4 things in order

1. **Land slice 15** — `feature/rust-slice-15-vvv-pin-1` (5 Survivor
   postcombat-main cards, SourceIsSelf trigger gating). Orthogonal to
   the flip; lands when its lane completes.
2. **Push + merge battlefield closure** — `feature/battlefield-axis-closure`
   at local `16c88726`. After merge, the 6/1800 axis-3 residual
   should collapse to 0; this is the GO-ready commit candidate per
   §3.
3. **Run v11 sweep on the flip commit** — currently running in the
   orchestrator shell (`broader-archetype-sweep-360-419` worktree at
   `de0aff68`). Confirms (a) no regression from the priority+blocker
   closure on a new archetype slice (360-419), and (b) the
   battlefield closure regress-verifies once it lands. The expected
   outcome is 0 priority_player + 0 blocker; the battlefield expected
   outcome depends on whether v11 runs against pre- or
   post-battlefield-closure HEAD.
4. **Execute Option P1 or P2** — atomic flag flip
   (`decision_source = "python" → "rust"`, B3-S5) on the
   post-battlefield-closure commit:
   - **P1 (flip-now):** verify C4 re-sweep on the flip commit is
     green; flip the flag.
   - **P2 (one-iterate-first):** run one `mtg_bot iterate` with
     shadow-checker active; on zero shadow-divergence, flip.

The C4 re-sweep step (per
[`FLIP_READINESS_EVIDENCE_2026_05_19.md`](FLIP_READINESS_EVIDENCE_2026_05_19.md)
§6) is implicit in step 3 — v11 IS the C4-class sweep if run at
appropriate scale (≥300 games / ≥60 archetypes / ≥5 seeds).

---

## §6 If you only have 5 minutes — read these

In priority order:

1. **This doc, §3 + §5** — the GO/NO-GO summary + the operational
   sequence. Three pages.
2. **[`SOT_FLIP_CUTOVER_PLAN.md`](SOT_FLIP_CUTOVER_PLAN.md) §8** — the
   authoritative current state, including §8.4 (GO-ready commit
   identification), §8.5 (Option P1 vs P2 framing), and §8.6 (honest
   caveats). One section, ~150 lines.

If a third doc is needed:
[`FLIP_READINESS_EVIDENCE_2026_05_19.md`](FLIP_READINESS_EVIDENCE_2026_05_19.md)
§0 (4-axis bar TL;DR) — the broader flip-gate axis-by-axis state
that frames why axes 2 + 3 closing is the GO unblock, with axes 1 +
4 understood-and-bounded.

---

## Cross-refs

- [`docs/SOT_FLIP_CUTOVER_PLAN.md`](SOT_FLIP_CUTOVER_PLAN.md) §8 — current state, authoritative
- [`docs/FLIP_READINESS_EVIDENCE_2026_05_19.md`](FLIP_READINESS_EVIDENCE_2026_05_19.md) — prior synthesis
- [`docs/BROADER_SWEEP_CONSOLIDATED_V5_V9.md`](BROADER_SWEEP_CONSOLIDATED_V5_V9.md) — cross-slice summary
- [`docs/PRIORITY_PLAYER_AXIS_INVESTIGATION.md`](PRIORITY_PLAYER_AXIS_INVESTIGATION.md) — axes 1+2 root cause + closure
- [`docs/BATTLEFIELD_AXIS_INVESTIGATION.md`](BATTLEFIELD_AXIS_INVESTIGATION.md) — axis 3 root cause + closure scope
- [`docs/G7_S6_BROADER_ARCHETYPE_V10_EVIDENCE.md`](G7_S6_BROADER_ARCHETYPE_V10_EVIDENCE.md) — post-closure regression-verify
- Closure commit (axes 1+2): `7a127e87` (underlying `5b8608d1`)
- Regression-verify commit: `b5035028` (v10, archetypes 300-359)
- Plan-update commit: `de0aff68` (§8 reflects the new state)
- Battlefield closure (local, not yet on origin): worktree
  `mtg-bot-worktrees/battlefield-axis-closure` at `16c88726`
- Follow-up todos at `C:\Users\Gregg Keithley\hub\data\mtg_bot\todos.json`:
  `c8d3a5f1` (priority_player — completed), `d4f6a8c9` (blocker —
  completed), `e5b7c9d8` (battlefield — completed when local closure
  was committed; needs to land on origin)
