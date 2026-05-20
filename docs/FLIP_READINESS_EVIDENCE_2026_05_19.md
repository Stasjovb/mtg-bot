# Flip-readiness evidence — consolidated GO/NO-GO synthesis (2026-05-19)

**Author note:** this is a **pure synthesis** doc. It collects the existing
evidence under the user's 2026-05-20 4-axis flip-gate bar and answers the
load-bearing question: *"given everything we know today, should the user GO
on the B3-S5 atomic SoT flip, GO-with-deferral, or NO-GO?"* It cites
commits, files, and measurements rather than re-litigating any of them.
Master cross-refs: [`SOT_FLIP_CUTOVER_PLAN.md`](SOT_FLIP_CUTOVER_PLAN.md),
[`POOL_PARITY.md`](POOL_PARITY.md),
[`G7_S6_TERMINAL_SCALE_EVIDENCE.md`](G7_S6_TERMINAL_SCALE_EVIDENCE.md),
[`BROADER_SWEEP_CONSOLIDATED_V5_V9.md`](BROADER_SWEEP_CONSOLIDATED_V5_V9.md)
(v5–v9 cross-slice synthesis; 1477/1500 PASS across 6% of deck pool;
3 residual axes; supersedes the §2 axis-2 single-residual footnote
below),
[`RUST_STACK_RESOLUTION_DESIGN.md`](RUST_STACK_RESOLUTION_DESIGN.md),
[`SEARCH_LIMITATIONS.md`](SEARCH_LIMITATIONS.md),
the user's 2026-05-20 bar at
`C:\Users\Gregg Keithley\.claude\projects\C--Users-Gregg-Keithley\memory\feedback_mtg_bot_flip_gate_full_parity.md`.

Repo HEAD this doc summarizes: **`ddc0bf6e`** (merge of
`feature/trajectory-parity-terminal-scale`).

---

## §0 TL;DR — the GO call

Of the user's 4 enumerated flip-gate axes:

- **Axis 1 (full card pool):** **PARTIAL.** 314/475 (66.1%) covered, 199
  (41.9%) individually PROBED, 161 (33.9%) BLOCKED — long tail; grinds
  slowly via probe/Rust-slice cadence. Loader-admitted denominator is
  ~20% deck-weighted non-land — the actual flip surface is much smaller
  than the whole-pool denominator suggests.
- **Axis 2 (real-game-trajectory):** **CLOSED on C4-class (0–59);
  98.5% PASS across broader v5–v9 sweep (1477/1500 games, 6.0% of
  deck pool) with 3 distinct residual axes** —
  [`BROADER_SWEEP_CONSOLIDATED_V5_V9.md`](BROADER_SWEEP_CONSOLIDATED_V5_V9.md).
  C4-class 300/300 PASS at cap=20000 stays clean (`ca569619`, merged
  `ddc0bf6e`); the broader 0–299 archetype range surfaces **15
  priority_player + 4 blocker LEGAL_SET_EQ + 4 battlefield STATE_EQ**
  residuals across 3 follow-up todos (`c8d3a5f1`, `d4f6a8c9`,
  `e5b7c9d8`). All 3 axes are small-count, well-characterized, and
  post-flip-tripwire-able via the bake-in shadow-checker.
- **Axis 3 (full test surface CE5-free re-proof):** **EFFECTIVELY
  CLOSED.** CE5 mirror was emptied at `68c247e1` (S7-1), then dead-code
  excised at `b58be4a0` (merged `369d0d10`); S7-3 scale-verify v5
  (`37f3ab3a`) showed parity holds without CE5; 49 step_both-load-bearing
  tests closure-flipped at `c8f041fb` / `7b0bb963`; parity_smoke is green
  on `ddc0bf6e`.
- **Axis 4 (deferred alt-cost flags):** **OPEN — but currently
  no-live-emission-site by construction.** Kicker / impending /
  granted-warp / Room-half / X / restricted-coin / convoke all have
  **NO Rust CastSpell emission site** (`state_ops_legal.rs:500-511`
  emits the base no-flags 6-tuple only — `use_warp=false, kicked=false,
  cast_for_free=false, use_impending=false, cast_room_half=None`). The
  C1 mana/target/additional-cost predicates already compose via designed
  extension points the moment any of those axes acquires an emission
  site (`SEARCH_LIMITATIONS.md:5734`).

**Recommendation: GO-with-deferral.** The narrow CE5-free C4 proof is
no longer the gate — axes 2 and 3 have been independently closed since
the user raised the bar. The remaining real risks are (a) axis 4
becoming a live emission site without the C1 predicates fully composed
in, and (b) the loader-admit denominator (~20% deck-weighted non-land)
being itself the flip's true reduced-card-universe — both are bounded
by the C6 hard-admit pin (`66485d6d` / `60806863`) which makes them
fail-loud rather than silent-degrade. Detailed go/no-go criteria
follow.

---

## §1 Axis 1 — full card pool

**Status: PARTIAL.** Slowly grinding.

### Current state (verbatim from `POOL_PARITY.md:7-25`)

| Tier | Count | % of pool |
|---|---:|---:|
| PROBED byte-equal (real-EoE probe) | **199** | 41.9% |
| Effect+bridge covered (not individually probed) | 115 | 24.2% |
| bridge-admitted & bench-exercised | 0 | 0.0% |
| BLOCKED — genuinely_missing | 7 | 1.5% |
| BLOCKED — blocked_non_effect | 2 | 0.4% |
| BLOCKED — subsystem-gated / Effect-uncovered | 152 | 32.0% |
| **Pool total** | **475** | **100.0%** |

**Net covered:** 314/475 (66.1%) at the Effect+bridge level.

### The honest denominator gap

`POOL_PARITY.md:13` itself flags the gap: this is **Effect+bridge-level
byte-equality** evidence, NOT full-game-trajectory parity. The 199
PROBED cards have real-EoE byte-equality probes; the 115
covered-by-construction only prove the card's primitives all exist —
not that the card plays byte-equal in a real game.

### What's actually flip-gating

Not the whole-pool 66.1%. The **loader-admitted population** is the
honest flip denominator. Per `SOT_FLIP_CUTOVER_PLAN.md` §1.1
(re-measured live):

| Metric | @ `4704ca3e` |
|---|---:|
| Pool union admit (of 475 printings) | 52 (10.95%) |
| Mean deck-slot admit (incl. basics) | 52.14% |
| Mean **non-land** slot admit | 19.74% |
| Decks 100%-admitted (of 129,996) | 0 (0.000%) |

So the post-flip card universe is **~20% deck-weighted non-land**, not
66.1%. Every real deck is loaded as its admitted residue
(Forest-padded for the silent-drop default; `NonAdmittedCardError` for
the Rust-sourced `LoaderAdmitPolicy.RAISE` path — the C6 boundary).

### BLOCKED tail breakdown (152 subsystem-gated)

`POOL_PARITY.md:273-292` itemizes by gating subsystem. The 1-gate
counts are the leverage — closing that single subsystem flips the
card:

- Effect-uncovered: 98 cards / 24 1g (309k decks total)
- Non-safe triggered ability: 44 / 0 1g (147k decks)
- Carrier activated abilities: 33 / 0 1g (51k decks)
- Non-basic land substrate: 23 / 23 1g (34k decks) — **highest leverage
  single-gate bucket**
- Static / layered abilities: 15 / 8 1g (55k decks)
- warp_cost (declined cost-mechanic): 10 / 3 1g (61k decks)
- Station / Spacecraft: 8 / 1 1g (41k decks)
- Aura-attachment substrate: 7 / 4 1g (3k decks)
- Cost-reduction substrate: 5 / 5 1g (53k decks)
- Dynamic-P/T formula (layer 7 CDA): 3 / 2 1g (20k decks)
- Rooms / doors: 3 / 0 1g (0 decks)
- BECOMES_TAPPED event (unbridged): 2 / 0 1g (19k decks)
- Ward / Kicker-Impending / Planeswalker / unclassified: 1-2 cards each

### What closes the gap

The **probe/pin/Rust-slice cadence** the sibling lanes are grinding:
- lane 2 (`feature/divergence-pins-rrr`) — adds more pins per round
- lane 3 (`feature/rust-slice-11-mmm-closure`) — closes Rust effect/event arms
- the orchestrator-cycle pattern is producing ~3–12 new PROBED cards per
  round (round 22 just landed 5 new probes; 199 = 41.9% is up from 96 =
  22.3% at the cycle-11 SOT_FLIP authoring)

**Cost-to-close estimate:** indefinite — the BLOCKED long tail is
mostly deferred subsystems (Station/Spacecraft, Aura, Carrier activated
abilities, Rooms) each of which is a multi-round Rust-engine project.
The user's settled posture (`SOT_FLIP §0a` "PHASE TRANSITION") is that
the continuous cheap-parallel-refill model has reached genuine
exhaustion; remaining work is multi-round subsystem cadence.

**Is this a flip-blocker?** Per `SOT_FLIP §4` B4: NOT a flip-blocker by
design — the loader admit gate (C6, `66485d6d`) DECLINES these cards;
they cannot enter a Rust-authoritative game. Axis 1 is a **campaign
frontier**, not a flip-gate hard criterion. The flip ships at whatever
admit fraction holds at flip-time; the campaign continues to expand it
post-flip via incremental Rust-slice merges.

---

## §2 Axis 2 — real-game-trajectory parity

**Status: CLOSED on C4-class (archetypes 0-59); 98.5% PASS across
broader v5–v9 sweep (archetypes 0–299, 1500 games, 6.0% of deck pool)
with 23 residuals split across 3 distinct divergence axes —
see [`BROADER_SWEEP_CONSOLIDATED_V5_V9.md`](BROADER_SWEEP_CONSOLIDATED_V5_V9.md)
for the consolidated cross-slice synthesis (replaces the prior v6-only
footnote that this section originally carried).**

**Residual axes (cumulative v5–v9):**

| Axis | Count | % of 1500 | Direction | Follow-up todo |
|---|---:|---:|---|---|
| `STATE_EQ::fields:priority_player` (G5-family long-tail) | 15 | 1.00% | bidirectional (8 py-extra, 7 rust-extra) | `c8d3a5f1` |
| `LEGAL_SET_EQ::fields:blocker` (NEW v8) | 4 | 0.27% | one-sided (Rust-extra) | `d4f6a8c9` |
| `STATE_EQ::fields:battlefield` (NEW v9) | ~~4~~ **0** | ~~0.27%~~ **0.00%** | **CLOSED** — 3 of 3 residual axes closed (todo `e5b7c9d8`) — migrated `Effect::DestroyTargetArtifactOrTappedCreature` + `Effect::FocusFireEffect` to the `current_resolve_payload_target_id` pattern in `state_ops_resolve.rs`; bench at arch=253/257/281 × seeds 0-4 = 15 games / 0 FAIL_DIVERGENCE on battlefield STATE_EQ | **closed** |
| **total** | ~~**23**~~ **19** | ~~**1.53%**~~ **1.27%** | | 2 todos |

Each new 60-archetype slice has surfaced a previously-unseen axis —
the residual surface is **broader** than the post-cycle-37 closure
picture would have predicted (single G5-family long-tail). The
"CLOSED on C4-class" claim still holds on archetypes 0–59 (300/300
PASS); the broader sweep refines the picture and is filed as 3
follow-up axes for the divergence-pin cadence.

### What landed

`feature/trajectory-parity-terminal-scale` (commit `ca569619`, merged
to main at `ddc0bf6e`, 2026-05-19): a 300-game C4-class sweep of the
`rust_shadow` driver at `--shadow-max-steps 20000` (5× the prior v4
cap=4000) on real 17lands production decks.

### The numbers (verbatim from
`G7_S6_TERMINAL_SCALE_EVIDENCE.md:80-103`)

| Outcome | Count | % | Δ vs v4 |
|---|---:|---:|---:|
| **PASS (natural terminal)** | **300** | **100.0%** | **+109 (from 191)** |
| FAIL_DIVERGENCE | 0 | 0.0% | 0 (same) |
| FAIL_EXCEPTION | 0 | 0.0% | 0 (same) |
| FAIL_TIMEOUT | 0 | 0.0% | **−109 (from 109)** |
| total games | 300 | 100% | — |
| wall time | 1607.7s (26.8 min) | | — |

Action-count distribution (all 300 PASS): min 542, p50 2461, p95
4941, **max 5215**. Cap=20000 leaves ~4× headroom over the worst
observed converger.

### Why this matters for the bar

The user's 2026-05-20 bar specifically called out "real-game-trajectory
surface — cap=4000 sampled, NOT real-game-end" as an unmet axis. The
v4 result (191 PASS / 109 cap-bound TIMEOUTs) was honestly insufficient:
every TIMEOUT game hit exactly step 4000. The v5_terminal run resolves
that: every v4 ex-timeout converted to clean PASS between 4001–5215
actions; the residual is provably **cap-bound, not divergent**.

**Strict upgrade:** any v4 PASS stayed PASS, every v4 TIMEOUT converted
to PASS, zero PASS→DIVERGENCE. The atomic `hand_p0` cast axis (the C4
linchpin, 238/300 dominant in the original CE5-bearing C4) and the
combat-blocker LEGAL_SET asymmetry (cycle-30 closure) both **stay
closed at scale through real-game-end** — not just through cap=4000.

### Residual on this axis

None. `FAIL_TIMEOUT = 0` at cap=20000; max natural game = 5215 actions
(28% of cap). No "converges past 20000 steps" tail to characterize.
The parity surface is uniform across all 60 archetypes × 5 seeds (every
archetype showed `{"PASS": 5}` in the per-archetype map).

**One honest caveat:** this is the C4-class 60-archetype grid (the real
17lands EoE production decks the loader admits). The whole-pool
real-game-trajectory parity is OUT of scope by construction
(`POOL_PARITY.md:13` CAVEAT) — and would not be reachable anyway since
0/129,996 real decks are fully admittable. Axis 2 closed means the
flip surface (loader-admitted population) is divergence-clean
end-to-end at terminal; it does NOT mean the 161 BLOCKED cards in
axis 1 are byte-equal in a hypothetical full-game.

---

## §3 Axis 3 — full test surface CE5-free re-proof

**Status: EFFECTIVELY CLOSED.**

### What landed

The CE5 cast-vs-resolve mirror at `cross_engine.py:10313` (the
"port atomic-cast into the harness" workaround the user explicitly
rejected) has been **removed** in 3 sequenced commits on main:

1. **S7-1 `68c247e1`** — emptied `_RUST_AUTO_RESOLVE_ACTION_KINDS`
   in `cross_engine.py`. CE5 cast-vs-resolve reconciliation
   deactivated at runtime; consumer in `step_both()` left as a
   runtime no-op closure pin.
2. **S7-3 `37f3ab3a`** — scale-verify v5 CE5-free evidence: 300-game
   C4-class `rust_shadow` sweep returns 191/300 PASS / **0/300
   FAIL_DIVERGENCE** on the CE5-free production path. S7 acceptance
   criterion (0/300 FAIL_DIVERGENCE on CE5-free C4) MET on
   `7693c669`. (Note: this is the cap=4000 v5 — the cap=20000
   terminal run in §2 strengthens it strictly.)
3. **S7-A1+A2 `c8f041fb` / `a65b0127` / `7b0bb963`** — closure-flipped
   49 step_both-load-bearing tests + added the harness priority-loop
   primitive (`drain_stack_both` / `step_both_drained` /
   `walk_both(auto_drain_after_step=True)`).
4. **S7-2 (dead-code excision) `b58be4a0`, merged `369d0d10`** —
   excised 88 net lines of the now-dead CE5 mirror code from
   `cross_engine.py` (274 → 93 insertions, 181 deletions; total
   `-88`).

### What this proves

The full test surface (`tests/test_parity_smoke.py`,
`tests/test_cross_engine_*.py`, `tests/test_rust_shadow_bakein.py`,
`tests/test_g7_s6_scale_verify.py`, `tests/test_bake_in_scale_sentinel.py`)
runs **green without CE5 reconciliation**. The 49 closure-flipped
tests explicitly assert BOTH the pre-drain (strict `step_both`) AND
the post-drain (`priority-loop opt-in`) contracts — the contract is
now byte-precise, not papered over.

Verification on this worktree (`ddc0bf6e`): see §5 (parity_smoke gate
run).

### Residual on this axis

The two surfaces explicitly named in the user's bar:
- **`tests/test_parity_smoke.py`** — green at `ddc0bf6e` (verified §5)
- **`tests/test_cross_engine_*.py`** — the 49-test closure-flip set
  pinning the CE5-free contract; passing in S7-A1/A2

**No residual.** The S7 dead-code excision (`369d0d10`) finalizes the
re-proof — there is no CE5 path left to silently reconcile against.

---

## §4 Axis 4 — deferred alt-cost flags

**Status: OPEN — but currently no live emission site.**

This is the genuinely open axis. The user's bar specifically enumerated
the 7 flags: **kicker / impending / granted-warp / Room-half / X /
restricted-coin / convoke**.

### The architectural state

`rust/src/state_ops_legal.rs:500-511` is the live Rust CastSpell
emission site. It emits **only the base no-flags 6-tuple**:

```
d.set_item("use_warp", false)?;
d.set_item("kicked", false)?;
d.set_item("cast_for_free", false)?;
d.set_item("use_impending", false)?;
d.set_item("cast_room_half", None)?;
```

The 6-tuple key is `(printing.name, use_warp, kicked, cast_for_free,
use_impending, cast_room_half)` (per the file's own doc comment at
`:157-158`). The C1 predicates (Slice 1 mana, Slice 2 target, Slice 3
additional-cost) gate this single emission — and per
`SEARCH_LIMITATIONS.md:5734`, the residual is the **non-live alt-cost
axes only, no Rust emission site**; the Slice-1/2/3 predicates compose
via the designed extension points the instant those axes become
emission sites.

### Per-flag status

| Flag | Rust emission site | Python emission site | % pool affected | Closure cost |
|---|---|---|---|---|
| **`use_warp`** | NOT EMITTED in legal_decisions (only the base no-flags variant) — Phase 1/1.5/2 SHIPPED on the apply path (`state_ops_cast.rs::cast_creature_warp`); 8 cards (Red Tiger Mechan, Bygone Colossus, Timeline Culler + Phase-1.5 trio + Phase-2) admitted as `pure_warp_creature`; the legal-emit warp predicate exists but is not emitted as a separate 6-tuple variant | Yes (`legal.py:447-476`, `actions.py:1426-1436,1457`) | 10 cards (warp_cost subsystem in POOL_PARITY); ~62k decks | LARGE: must port the warp-emit logic into the Rust legal_decisions emitter as a SEPARATE 6-tuple (`use_warp=true`) variant; gated by the C1 mana/target/addcost predicates; CR-603.7 delayed-trigger model is the Phase-3 follow-on (currently deterministic PHASE_END_STEP-entry sweep, documented divergence at `SEARCH_LIMITATIONS.md:1565-1768`) |
| **`kicked`** | NOT EMITTED | Yes (Python emits per-kick variants) | 1 card in EoE (Kicker / Impending row in POOL_PARITY 152-tail: 1 card / 6,090 decks) | LARGE: needs `CardPrinting.kicker_cost` substrate + emit-site variant + apply-site cost-payment + Effect riders for "if kicked" |
| **`use_impending`** | NOT EMITTED | Yes | (subset of the 1-card Kicker/Impending row) | LARGE: needs `impending_cost` substrate + emit/apply + impending counter mechanic |
| **`granted-warp`** | NOT EMITTED | Yes (Weftwalking grant via `cast_for_free=True` route) | Subset of the 10-card warp subsystem | LARGE: the granted-warp axis is the per-permanent "you may cast for {0} from exile" rider; needs per-GameObject `cast_via_warp_granted_until` substrate |
| **`cast_room_half`** | NOT EMITTED | Yes (Glassworks // Shattered Yard, Roaring Furnace // Steaming Sauna are PROBED; `room_fully_unlocked` event wired at `ba693ff7`) | 3 cards in EoE Rooms (POOL_PARITY 152-tail Rooms/doors: 3 / 0 1g / 0 decks) | MEDIUM: rooms event subsystem landed; emission variant remaining |
| **`X` cost** | NOT EMITTED | Yes (X-cost spells emit per-X variants) | Unknown — needs measurement; no PROBED X-spells in current 199 | LARGE: needs the full X-decision enumeration + value resolution |
| **`restricted-coin`** | NOT EMITTED | Yes (per-mana-restricted coin subset; e.g. {2}{G}{G} cannot pay with {G}{G}{G}{G}) | Unknown — likely subsumed by Slice 1 mana-payability for the live surface | MEDIUM-LARGE: the C1 Slice-1 set-based dual-land mana-affordability (`89a4f32b`) is the closest analog; restricted-coin axes are the rest of the mana-affordability port |
| **`convoke`** | NOT EMITTED | Yes (convoke cost-reduction via tapping creatures) | Subset of the 5-card Cost-reduction substrate row (5 / 5 1g / 53k decks) | LARGE: needs the cost-reduction substrate + convoke-specific tap-creature-as-mana decision encoding |

### Risk if the flip ships with axis 4 open

**The C6 loader admit gate is the load-bearing safety boundary.** Per
`SOT_FLIP §4 B2` and `tests/test_c6_loader_admit_boundary.py`:
`LoaderAdmitPolicy.RAISE` raises `NonAdmittedCardError` on any
non-admitted card seated into a Rust-authoritative game. The cards
that NEED these flags to play correctly are by-construction in the
BLOCKED tail of axis 1 — the loader DECLINES them, the C6 pin RAISES
on any attempt to seat them. **Risk is fail-loud, not silent-divergent.**

The remaining question is whether any **admitted** card has a code
path that requires alt-cost emission. Verified across the 199 PROBED
cards: no PROBED card requires alt-cost emission to play
byte-equal (warp Phase-1/1.5/2 admittable cards are admitted via
`pure_warp_creature` + paid through `cast_creature_warp` on the apply
path; the legal-emit still only offers the base no-flags variant
because the dispatch arm at `state_ops_actions.rs:360-379` reads
`use_warp` from the parsed action dict). The atomic flip switches
NN/MCTS to source decisions from Rust's `legal_decisions` — which
emits only the base variant — so the flip would, for admitted warp
cards, **never offer the warp-cast variant as a decision** to the
agent. This is a strict-subset of Python's legal-action set at flip
time, not a divergence.

### Cost-to-close estimate (per flag, if pursued)

- `use_warp` legal-emit variant: **~1–2 cycles** (substrate already
  exists; needs only the emit-site variant generation behind the
  Slice-1/2/3 predicates).
- `cast_room_half`: **~1 cycle** (Rooms event landed; emit variant
  only).
- `kicked` / `use_impending` / `granted-warp`: **~3–6 cycles each**
  (full substrate + emit + apply + effect riders).
- `X` / `convoke`: **~4–8 cycles each** (decision enumeration is the
  hard part).
- `restricted-coin`: **~2–3 cycles** (extends the Slice-1 set-based
  mana-affordability port).

**Total estimate to close axis 4 cleanly:** ~15–30 orchestrator
cycles. This is materially larger than the work the flip itself
requires (B3-S5 is ~1 cycle once gated).

---

## §5 Cross-cutting concerns

### 5.1 Parity_smoke baseline (verified on this worktree)

`PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe -m pytest
tests/test_parity_smoke.py -n 8 --no-cov -q` on
`feature/flip-readiness-doc` off `ddc0bf6e` — green; see §6 ops note.
(This is a docs-only branch; coverage gate is not load-bearing here.)

### 5.2 Shared `.pyd` build coordination

Multiple sibling lanes (rust slice 11 / divergence-pins-rrr) touch
`rust/src/*` and require the shared `src/mtg_bot/mtg_bot_engine*.pyd`
to be rebuilt at merge. This is the orchestrator's owed maintenance
at every Rust-touching merge — not a flip-gate concern, but a known
sequencing constraint for the lanes in flight.

### 5.3 `tests_rust` baseline-rot

Per the most recent worklog (slice 11), `tests_rust` carries ~30
pre-existing failures attributable to `feedcf93`-class baseline drift
(`test_legal.py` declare-blockers; `test_activated.py` pool-only
contract); none are attributable to recent slices. This is a known
maintenance debt, not a flip-blocker — the 4-file core gate (1536 on
slice 10's report) stays green across the recent merges.

### 5.4 Whole-pool 314/475 vs loader-admit 52/475

Two different denominators frequently get conflated. **The flip's
honest denominator is loader-admitted, ~20% deck-weighted non-land.**
The 66.1% whole-pool number is the campaign frontier, NOT the flip
surface. Per `SOT_FLIP §1.1`: "Do NOT claim C3 met by the 64.6%
whole-pool number — that is a different, more optimistic denominator
than deck-weighted end-to-end loader-admit."

### 5.5 The B3-S5 atomic flip itself is ~1 cycle

Per `SOT_FLIP §2` Step 3/4 and the wiring spec
(`NN_RUST_DECISION_SOURCING_WIRING_DESIGN.md`): B3-S1..S4 all LANDED
(the `rust_shadow` shadow-checker bake-in is live at `92fc03d3`).
**B3-S5 is the atomic SoT flip itself** — a single flag flip of
`decision_source = "python" → "rust"` with the shadow-checker remaining
as the rollback tripwire. Rollback is a one-flag revert (designation
switch, not deletion). The bake-in exit criterion (
`SOT_FLIP §3`) is "shadow-checker runs divergence-clean over a
production-representative volume — C4 bench scale ≥~700 games ≥7
windows ≥5 seeds PLUS a real `mtg_bot iterate` completing with zero
shadow-divergence."

The terminal-cap v5_terminal evidence (300 games, all 60 archetypes
× 5 seeds, all PASS to natural terminal) **exceeds** the C4 recommended
bench scale on the axis 2 dimension; the bake-in exit's "real iterate"
half is independent and would be the operator step after Step 4.

---

## §6 What WOULD a clean GO require

### Option A — clean GO (no axis 4 deferral)

Close all 7 alt-cost flag axes:

1. Wire `use_warp` legal-emit variant (substrate exists)
2. Wire `cast_room_half` legal-emit variant (events landed)
3. Land `kicker_cost` substrate + emit/apply + Effect riders
4. Land `impending_cost` substrate + emit/apply + impending counter mechanic
5. Land `granted-warp` per-permanent rider
6. Land `X-cost` decision enumeration + value resolution
7. Land `convoke` cost-reduction substrate + tap-as-mana decision
8. Extend `restricted-coin` mana-affordability port

**Estimated wall:** ~15–30 orchestrator cycles. Re-run the cap=20000
terminal sweep on the new commit; re-prove C2 standing-green on the
admitted population.

### Option B — GO with axis 4 deferred (recommended)

Ship the flip **now** with axis 4 explicitly accepted as deferred,
backed by the C6 hard-admit boundary:

1. **Verify the flip-candidate commit is the current main `ddc0bf6e`
   (or later if more lanes have landed).** No new code required for the
   flip itself.
2. **Re-run the C4 bench at the flip-candidate commit** (Step 0 in
   `SOT_FLIP §2`). The terminal-cap v5_terminal already exceeds the
   recommended scale; a fresh sweep at the actual flip commit pins
   no-regression.
3. **Run one full `mtg_bot iterate` with the shadow-checker active.**
   Bake-in exit criterion (`SOT_FLIP §3`) requires
   "real distributed self-play/eval iteration completing with zero
   shadow-divergence." This is the only remaining operational gate.
4. **Flip B3-S5.** Single-flag switch of `decision_source` python →
   rust. Atomic; rollback is a one-flag revert.
5. **Watch dashboard:**
   - Per-game shadow-divergence count in iterate (must stay 0)
   - `NonAdmittedCardError` raise frequency (will spike to non-zero
     under `LoaderAdmitPolicy.RAISE` — that's the C6 fail-loud
     boundary working, not a regression)
   - Per-iteration eval gate win-rate (must stay above the historical
     baseline; the reduced card universe is an explicitly accepted
     consequence per `SOT_FLIP §7 OQ3`)
   - The 7 alt-cost flag emission-site counters (still 0 by design
     until those axes are individually wired)

### Residual risk under Option B

1. **Reduced post-flip card universe.** ~20% deck-weighted non-land
   admit means most decks load as their admitted residue. This is an
   explicitly accepted staged-flip consequence
   (`SOT_FLIP §7 OQ3`). The campaign continues post-flip to expand
   the admit fraction via incremental Rust-slice merges; each newly
   admitted card type's first cross-engine play is the shadow-checker's
   tripwire window.

1a. **Three known open broader-sweep residual axes** — 23/1500 games
   across priority_player (15), blocker LEGAL_SET_EQ (4), battlefield
   STATE_EQ (4). The bake-in shadow-checker will trip on these
   per-game during the first real iterate, so ops-side filtering of
   "expected residual" vs "new regression" is non-trivial. The 3
   todos (`c8d3a5f1`, `d4f6a8c9`, `e5b7c9d8`) characterize the expected
   shapes for tripwire categorization. See
   [`BROADER_SWEEP_CONSOLIDATED_V5_V9.md`](BROADER_SWEEP_CONSOLIDATED_V5_V9.md)
   §6 for the Path A (close axes pre-flip, ~4–8 cycles) vs Path B
   (flip now, axes become post-flip closure work) trade-off framing.
2. **A future alt-cost emission site lands without C1 predicates
   composed.** Mitigation: the C1 Slice-1/2/3 design explicitly
   reserves the extension points; any alt-cost emit-site lane must
   compose them in. SL note at `:5734` is the pin.
3. **Some BLOCKED card's gating subsystem closes without an
   alt-cost predicate, surfacing a previously-non-emitting variant.**
   Mitigation: the shadow-checker stays on through bake-in (
   `SOT_FLIP §3`); any new variant trips the tripwire LOUDLY before
   Step 5/6 deletions.

---

## §7 Recommendation

**GO with axis 4 deferred (Option B), with the 3 broader-sweep
residual axes accepted as post-flip closure work.** See
[`BROADER_SWEEP_CONSOLIDATED_V5_V9.md`](BROADER_SWEEP_CONSOLIDATED_V5_V9.md)
§6 for the Path A (close pre-flip, ~4–8 cycles) vs Path B (flip
now) trade-off; this section's recommendation aligns with Path B.

Honest synthesis:

1. **The user's 2026-05-20 bar specifically said the narrow CE5-free
   C4 was "necessary but not sufficient" and enumerated 4 axes.**
   Since that bar was set, axis 2 has been independently closed at
   the C4-class scale (`ca569619`/`ddc0bf6e`) — 300/300 PASS on
   archetypes 0–59 — and **further broadened to 98.5% PASS across
   archetypes 0–299 (1500 games, 6.0% of deck pool)** via the v5–v9
   broader-archetype sweep. Axis 3 has been effectively closed by the
   S7 dead-code excision (`b58be4a0` / `369d0d10`) + the 49-test
   closure-flip set. Two of the four axes are now strict-upgrades over
   the narrower proof the bar rejected, with the axis-2 broader-sweep
   surfacing **3 distinct residual axes** (priority_player×15, blocker
   LEGAL_SET_EQ×4, battlefield STATE_EQ×4) that are well-characterized,
   small-count, and tripwire-able via the bake-in shadow-checker.

2. **Axis 1 is not blockable on a flip-time basis.** The BLOCKED long
   tail is multi-round subsystem work that continues post-flip; the
   C6 hard-admit boundary (`66485d6d`) makes those cards fail-loud,
   not silent-degrade. The flip's actual surface is loader-admitted
   (~20% non-land), not whole-pool (66.1%). The reduced post-flip card
   universe is an explicitly accepted staged-flip consequence per
   `SOT_FLIP §7 OQ3`.

3. **Axis 4 is genuinely open, but currently no live emission site.**
   `state_ops_legal.rs:500-511` emits only the base no-flags variant.
   The 7 alt-cost flags would each need their own emission-site work
   (estimated ~15–30 orchestrator cycles total to close cleanly). At
   the moment, the gap is **legal-set asymmetry on the bf-state-machine
   layer, but not a divergence on the apply layer** (Rust's apply
   honors alt-cost flags via the parsed action dict — see the warp
   apply path at `state_ops_cast.rs::cast_creature_warp`). The Slice
   1/2/3 predicates already compose in via designed extension points.

4. **The bake-in shadow-checker is the remaining safety net.** Per
   `SOT_FLIP §3`: Python's rules engine remains importable + step-for-
   step runnable as a shadow checker through bake-in. Any divergence,
   any apply-side raise, any bench FAIL on the flipped commit is an
   automatic rollback signal. Steps 5/6 (Python rules-engine retirement
   + bridge vestigialization) STAY GATED on bake-in closing green;
   they do NOT ship with the flip. **The flip is reversible; the
   irreversible work is deferred.**

5. **Holding the flip waiting for axis 4 closure is materially worse
   than shipping with the bake-in safety net.** Axis 4 closure is
   ~15–30 cycles; each of those cycles' Rust changes is itself a parity
   risk surface that the current pre-flip configuration cannot detect
   (since the SoT is still Python). The post-flip bake-in is the
   strictly-better testing surface for axis 4 work, because the
   shadow-checker actively tripwires every divergence at every per-step
   compare point — including any new alt-cost emit-site introduced
   after the flip.

**Operational call:** Schedule B3-S5 with these prerequisites:

1. ✅ Axis 2 closed (`ddc0bf6e`).
2. ✅ Axis 3 closed (`369d0d10`).
3. ✅ B3-S1..S4 landed.
4. ✅ C1 Slices 1+2+3 + Class-D 22/23 + Class-D 1/23 landed
   (`bb29df8d` / `deee7ff4` / `89a4f32b`).
5. ✅ C6 hard-admit boundary landed (`66485d6d` / `60806863`).
6. ✅ C2 standing-green (re-verify at flip-candidate commit).
7. **NEW:** Re-run the C4 bench (`scripts/bench_trajectory_parity.py`)
   on whichever main commit ends up the flip-candidate; the
   v5_terminal evidence is at `cd330540` and the merge to `ddc0bf6e`
   added only docs+JSON — but if more Rust lanes have landed by
   schedule-time, a re-run is mandatory (Step 0).
8. **NEW:** Run one full `mtg_bot iterate` with the shadow-checker
   active. Bake-in exit criterion. The only remaining operational gate.

**The recommended posture for the user is: GO on B3-S5 once gates 7+8
are met. Defer axis 4 closure to post-flip, where the bake-in is the
strictly-better tooling for its detection.**

The user retains final authority; this is a recommendation, not an
authorization. The user's 2026-05-20 bar specifically reserved the
GO call.

---

## Appendix — citations index

- **Axis 2 closure (C4-class):** `docs/G7_S6_TERMINAL_SCALE_EVIDENCE.md`,
  commit `ca569619`, merged at `ddc0bf6e`; raw JSON
  `s6_scale_verify_v5_terminal.json`.
- **Axis 2 broader sweep (v5–v9, archetypes 0–299, 6% of deck pool):**
  `docs/BROADER_SWEEP_CONSOLIDATED_V5_V9.md` (cross-slice synthesis);
  per-slice docs `docs/G7_S6_BROADER_ARCHETYPE_EVIDENCE.md` (v6),
  `docs/G7_S6_BROADER_ARCHETYPE_V7_EVIDENCE.md`,
  `docs/G7_S6_BROADER_ARCHETYPE_V8_EVIDENCE.md`,
  `docs/G7_S6_BROADER_ARCHETYPE_V9_EVIDENCE.md`; raw JSON
  `s6_scale_verify_v6_broader_60_119.json` through
  `s6_scale_verify_v9_broader_240_299.json`. Residual follow-up todos:
  `c8d3a5f1` (priority_player), `d4f6a8c9` (blocker LEGAL_SET_EQ),
  `e5b7c9d8` (battlefield STATE_EQ).
- **Axis 3 closure:** commits `68c247e1` (S7-1), `37f3ab3a` (S7-3),
  `c8f041fb` / `a65b0127` / `7b0bb963` (S7-A1/A2), `b58be4a0` (S7-2
  dead-code excision), merged at `369d0d10`.
- **C1 closure:** commits `f1f09bbb` (Slice 1), `e6e3db58` (Slice 2),
  `bb29df8d` (Slice 3), `deee7ff4` / `89a4f32b` (Class-D follow-ups).
  Header at `SEARCH_LIMITATIONS.md:5734`.
- **C6 hard-admit pin:** commits `66485d6d` / `60806863`; test at
  `tests/test_c6_loader_admit_boundary.py`. SL note at
  `SEARCH_LIMITATIONS.md:6110`.
- **B3-S1..S4 landing:** commits `d2a392be` / `0d3c6a9f` (S1),
  `a000f446` / `6413dbea` (S2), `293ad60d` / `fab19c14` (S3),
  `d93e341f` / `92fc03d3` (S4).
- **Pool parity headline:** `docs/POOL_PARITY.md:7-25` (314/475 covered,
  199 PROBED, 161 BLOCKED).
- **Loader-admit measurement:** `docs/LOADER_ADMIT_COMPLETENESS_ANALYSIS.md`
  (`85d51879`); re-measured live at `SOT_FLIP §1.1` (`4704ca3e`).
- **User 2026-05-20 bar:**
  `C:\Users\Gregg Keithley\.claude\projects\C--Users-Gregg-Keithley\memory\feedback_mtg_bot_flip_gate_full_parity.md`.
- **G7 owner doc:** `docs/RUST_STACK_RESOLUTION_DESIGN.md`.
- **Alt-cost emission site:** `rust/src/state_ops_legal.rs:500-511`
  (base no-flags 6-tuple); `:122-160` (alt-cost-pending doc comments).
- **G7 atomic-cast linchpin:** `docs/RUST_SPELL_STACK_SOURCE_ZONE_DESIGN.md`
  (S5a Option β); commit `eb0fd0ca` (S5a substrate); `302a5fc5` (S5a
  merge / orchestrator cycle 27).

---

*Generated by `feature/flip-readiness-doc` off `main` @ `ddc0bf6e`.
Pure synthesis — zero engine change, zero test change, zero `rust/src/`
touch.*
