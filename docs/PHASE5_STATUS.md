# Phase 5 status & closure roadmap

Snapshot date: 2026-05-12 (afternoon-wave end; CE13-CE18 all closed,
G12 / G19 / G24 all closed, Effect-rng-threading shipped, defender-
only target arms rewritten, and seven single-keyword probes walked
clean across the bilateral combat backbone).

**Punchline.** **The cross-engine smoke is now byte-identical across
twelve combat surfaces** — cast resolve, multi-block, bilateral
combat, first-strike, double-strike (post-CE18), deathtouch + multi-
block damage assignment (post-CE14), trample + multi-block damage
assignment (post-CE15), lifelink, vigilance, haste, menace (post-
CE16), defender (post-CE17), indestructible, flying, and hexproof
(shared-gap parity). The double-strike spillover divergence (CE18)
closed late in the wave, so **zero open CE divergences remain — first
"all open CEs closed" state in the project**. CE8's external-RNG
substrate from the morning closed end-to-end today via the Effect-
rng-threading slice that put the rng on `GameState.rng` and threaded
it through `Effect::SearchLibraryForBasicLandTapped` — cross-engine
MT shuffle parity is byte-identical under a shared `random.Random`.
G19 closed in two stages (xorshift64 fallback + Effect-rng-threading);
G12 was audited and retired as already-effectively-closed; G24 (Paris
scry-on-keep) shipped a new `PendingDecision::ScryChoice` variant +
dispatcher. The Rust engine carries **80 `Effect` variants** covering
**75.7%** of per-card emissions on the EoE+stellar_sights+
special_guests_eoe+duskmourn pool. **Open CE count: 0. Open G-gap
count: 1 (G8 multi-kind counter map, no pool card asks the question).**
Phase 4a/4b are functionally complete (freq>=10 head: 13/14, freq 2-9:
52/53). The remaining work to a 1000-game cross-engine smoke is
bounded: a handful of additional probe extensions into the event-
driven surface (ETB triggers, activated abilities mid-combat,
counterspells, flash) plus the substrate prerequisites those probes
will surface.

---

## 1. Where we are

### Numbers

- **80 Rust `Effect` variants** in `rust/src/cards.rs` (unchanged from
  the morning snapshot — today's Effect work was variant-internal:
  G19's Fisher-Yates shuffle threaded through
  `Effect::SearchLibraryForBasicLandTapped`'s resolve arm, plus
  Effect-rng-threading routing the rng read through `state.rng_ref()`).
  Note: G24 added `PendingDecision::ScryChoice`, but that's a pending-
  decision variant, not an `Effect` variant.
- **74 / 228 Python Effect classes covered (32.5%)** — unchanged.
- **522 / 690 per-card emissions covered (75.7%)** — unchanged.
- **Frequency tiers** (`docs/RUST_EFFECT_COVERAGE.md`):
  - Freq >= 10 (head, 14 classes): **13 / 14 covered (92.9%)** —
    unchanged; `ModalChooseOne` still gated on the unmerged
    `feature/coverage-overrides` PR to flip to 14/14 via the
    override map.
  - Freq 2-9 (mid, 53 classes): **52 / 53 covered (98.1%)** —
    unchanged.
  - Freq 1 singletons (161 classes): **9 / 161 (5.6%)** — explicitly
    out of Phase 5/6 scope.
- **Rust test gate**: **1874 passing on main** (was 1814 at the
  end-of-day-yesterday snapshot; **+60 today** across the afternoon-
  wave CE closures, keyword probes, Effect-rng-threading pins,
  defender-only target arms regression tests, and G12 / G24 cross-
  engine pins).
- **Python test gate**: ~10255 passed / 10-12 skipped / 0-2 xfailed
  depending on slice (no remaining strict-xfails as of end-of-day —
  CE13 / CE17 / CE18 all retired their pre-closure pair-pins). One
  pre-existing red unrelated to Phase 5: `test_no_orphan_rust_variants`
  (3 orphans pending the unmerged `feature/coverage-overrides` PR).

### Parity plan status (`docs/RUST_PARITY_PLAN.md`)

| Phase | Status |
|---|---|
| 0 Engine primitives | done (r1-r19) |
| 1 Discovery + scaffold | done (r20) |
| 2 Externalize RNG + spec GameState API | **done** (CE8 substrate + Effect-rng-threading both shipped; cross-engine MT shuffle parity byte-identical) |
| 3 Action types + legal_decisions | done (r22-r25) |
| 4a Top-14 high-frequency Effects | done modulo coverage-overrides PR merge |
| 4b Mid-frequency Effects (next ~50) | done modulo 1 singleton (52/53 shipped) |
| **5 Per-step trajectory diff** | **substantially advanced — all CEs surfaced through CE18 are closed; cross-engine smoke walks 200 decisions clean on 7+ keyword surfaces and 1000/1000 clean on multi-block** |
| 6 Scale to 1000 games | **partial — 1000/1000 clean multi-block combat smoke on `multi_blocker_deckspec`; 200/200 clean walks on retaliation + first-strike + lifelink + vigilance + haste + indestructible + flying + hexproof + defender (normal_only) + double-strike (post-CE18) surfaces** |

### Cross-engine divergences surfaced + closed in today's afternoon wave

The probe-close-probe cadence accelerated this afternoon. Delta vs
the 2026-05-12 end-of-day-yesterday snapshot (which had CE13 as the
lone open CE):

- **CE13** (`summoning_sick` cleared on Rust LTB; Python preserves).
  CLOSED via `feature/ce13-summoning-sick-ltb` (merge `ba097c70`).
  Rust now preserves the flag matching Python's
  `turn.move_off_battlefield`.
- **CE14** (deathtouch + multi-block damage assignment split — Python
  walks every blocker with need=1; Rust over-counted). CLOSED
  `b348994b` (merge `17bffc61`). Per-blocker need=1 assignment
  matches Python. Surfaced by the deathtouch probe (`c3ed2636`) and
  closed same-session.
- **CE15** (trample + multi-block damage assignment — Python walks
  every blocker with need-based assignment incl. trample excess
  routing; Rust short-circuited). CLOSED `e6dc6433` (merge
  `ecc44429`). Per-blocker need + trample excess matches Python.
- **CE16** (menace single-blocker apply-path divergence — Rust didn't
  post-validate block assignments). CLOSED `bbcacfae` (merge
  `5a45da9d`). `Action::DeclareBlockers` apply arm now post-validates
  via `is_legal_block_assignment` (silently drops illegal single-
  blocker menace assignments).
- **CE17** (legal_decisions emitted defender as attacker candidate
  even though apply-time gate correctly rejected). CLOSED `85841f5f`
  (merge `8e89ded3`). One-line filter in
  `state_ops_legal.rs`'s DeclareAttackers eligibility loop calls
  `battlefield_has_keyword(self, obj_id, "defender")` to short-
  circuit, mirroring the apply-time gate.
- **CE18** (double-strike attacker damages sole blocker to lethal in
  FS substep; Python redirects regular-pass damage to defender; Rust
  dropped). SURFACED + CLOSED same-day. Closure `77a53c36` (merge
  `7a26022f`) rewrites `deal_combat_damage` pass-2 filter as a
  `filter_map` that redirects to `DamageTarget::Player(defending_player)`
  when source-is-attacker AND alive-blocker-count==0. Phase 5
  convention overrode CR-correctness (Rust pre-closure was CR-
  correct; Python is over-permissive). Invariant I45 added.

### G-gaps closed today

- **G12** (mutual KO is two sequential `lose_life` calls, not one
  atomic symmetric Effect). CLOSED via `feature/g12-audit` (merge
  `2edebfd1`). The audit established that the underlying substrate
  gap is structurally still present, BUT the observable end-state IS
  the parity-load-bearing contract and matches bit-equal on both
  engines via `apply_sbas_until_quiescent`. Invariant I44 added
  pinning the cross-engine end-state contract.
- **G19** (`SearchLibraryForBasicLandTapped` does not shuffle).
  CLOSED in two stages: morning's `feature/g19-search-shuffle`
  shipped the xorshift64 fallback Fisher-Yates; afternoon's
  `feature/effect-rng-threading` (merge `7b8de90e`) added
  `GameState.rng: Option<Py<PyAny>>` field + `set_external_rng`
  pymethod + threading through the resolve arm. Cross-engine MT
  shuffle parity is now byte-identical under a shared
  `random.Random`. Invariant I43 added.
- **G24** (no Paris scry-on-keep step after mulligan). CLOSED via
  `feature/g24-paris-scry-on-keep` (merge `1e2e546b`). New
  `PendingDecision::ScryChoice` variant + `keep_hand(player_id)`
  pymethod + `submit_scry_decision(keep_on_top: bool)` dispatcher +
  3 auto-resolve strategies (`scry_keep_top` / `scry_send_bottom` /
  default). 19 new pinning tests.

### Substrate items closed today

- **Defender-only target arms rewrite** (deferred from yesterday's
  bf-iter-resolve-arms slice). CLOSED via
  `feature/defender-only-target-arms` (merge `f53559d3`). Four arms
  (`DestroyTargetNonlandPermanent`, `DestroyTargetArtifact`,
  `DestroyTargetLand`, `TapTargetArtifactOrCreature`) now walk
  `bf_iter_etb_sorted` across both players matching Python's
  `TargetSpec` filter (no controller restriction). Invariant I39
  added. 12 new regression tests pin the closure direction.
- **Effect-rng-threading** (deferred since CE8 substrate landed).
  CLOSED via `feature/effect-rng-threading` (merge `7b8de90e`).
  Option A from `docs/RUST_EFFECT_RNG_AUDIT.md` §4 (per-state-stash,
  not per-call-signature parameter) shipped. Invariant I43 added.

### Phase 5 keyword probes that walked clean today (no novel CE)

Seven single-keyword probes extended the cross-engine smoke and
walked parity-clean for 200 decisions on the retaliation backbone:

- **vigilance** (CR 702.20) — merge `09ef4911`.
- **haste** (CR 702.10) — merge `79d8c43d`.
- **lifelink** (CR 702.15) — merge `34aaf8fd`.
- **first-strike** (CR 510.5) — merge from morning wave.
- **indestructible** (CR 702.12) — merge `a4b49c7e`.
- **hexproof** (CR 702.11) — merge `04c2f346` (shared-gap parity:
  neither engine enforces hexproof today; pinned at current
  behavior).
- **flying** (CR 702.9) — merge `b6080614`.

Plus four probes that surfaced + closed same-session:
deathtouch+multi-block (CE14), trample+multi-block (CE15), menace
(CE16), defender (CE17), and double-strike (CE18).

### Cross-engine deltas vs the 2026-05-12 end-of-day-yesterday snapshot

- **Open CE count: 0** (was 1: CE13). CE13-CE18 all closed today;
  CE18 surfaced + closed same-day. **First "all open CEs closed"
  state in the project.**
- **Open G-gap count: 1** (was 4: G8 + G12 + G19 + G24). G12 / G19 /
  G24 all closed today. G8 remains the lone surviving open G, low
  priority — no pool card asks the multi-kind-counter-stack
  divergence question. G5 / G9 / G13 / G16 / G17 / G18 are
  documented as parity invariants, not gaps (deliberate symmetric
  contracts or test-setup-only asymmetries).
- **Highest invariant: I45** (CE18 closure pin) — was I38 yesterday.
  Today added I39 (defender-only target arms), I40 (legal_decisions
  defender filter), I41 (external_rng substrate — renumbered from
  duplicate I34), I42 (post-search shuffle contract — renumbered
  from duplicate I35), I43 (GameState.rng lifecycle), I44 (mutual-
  KO end-state), I45 (double-strike spillover).

### What's running cleanly end-of-afternoon

- All single-color / two-color synthetic deckspecs through full
  multi-turn play with land drops + creature casts + combat.
- `multi_blocker_deckspec` with `multi_block_combat_selector`:
  1000/1000 clean games.
- `multi_blocker_deckspec` with `retaliation_selector` (bilateral
  combat): 260+ decisions clean.
- `multi_blocker_deckspec` with each of seven keyword side-channel
  selectors layered onto retaliation: 200/200 decisions clean.
- Cross-engine shuffle smoke with `shared_rng_seed`: byte-identical
  libraries across multiple seeds, including post-search shuffle
  inside `Effect::SearchLibraryForBasicLandTapped`.
- All four defender-only target arms: cross-player ETB-walk matches
  Python via `bf_iter_etb_sorted`.

---

## 2. What's left

### Open G-gaps in `RUST_PARITY_GAPS.md`

| Gap | Description | Status | Slice scope | Priority |
|---|---|---|---|---|
| **G8** | +1/+1 and -1/-1 counters stored as net `i32`, cancel at write-time not SBA | unchanged — needs multi-kind counter map; G9 bundles in the matching snapshot getter | medium | **low** (no pool card asks the divergence question) |

That's it for open gameplay-divergence gaps. The remaining G-entries
(G5 / G9 / G13 / G16 / G17 / G18) are parity invariants documented
under the `Confirmed gaps` heading for forward-debugging context, not
real divergences.

### Open CE-gaps

**None.** CE1-CE18 all closed.

### Substrate deferrals not closed today

- **`spell_warped_this_turn` flag setter**. The bool field lives on
  `GameState` but no Rust production call site flips it yet (see
  `feature/warp-flag-substrate` for the documented gap, merge
  `72264b63`). Without it, `Effect::ConditionalIfVoid` is shipped
  but not load-bearing for the 4 EoE Void cards. Fix scope: small
  (warp-cast cost path single-site). Priority: medium — only when
  a probe drives a Void card.
- **ManifestDread face-down state + count > 1 deferrals** (unchanged
  since 2026-05-11): face-down state needs either fingerprint
  baseline rebuild or sidecar field; count>1 is ~30 LoC. Priority:
  medium-low.
- **`Effect::EquipToTargetCreatureYouControl` `granted_keywords_ueot`
  rider** (Atomic Microsizer family always passes empty frozenset).
  Unchanged.
- **`Effect::LookAtTopNRevealOrCounter` "random order" tail** —
  unblocked by Effect-rng-threading (state.rng is now plumbed); a
  one-Effect-arm rewire follow-up.

### High-frequency Effects still missing

Per `RUST_EFFECT_COVERAGE.md`, the only remaining freq>=10 class is:

| Python class | Frequency | Status |
|---|---:|---|
| `ModalChooseOne` | 13 | functionally shipped as `Effect::ChooseOneMode`; gated on `feature/coverage-overrides` PR merge to flip the orphan-map entry |

The freq 2-9 tier is at **52/53 (98.1%)** — the one remaining class
is the lone freq-2 long-tail miss; not load-bearing for the current
cross-engine smoke.

### Singletons (freq 1)

Explicitly **out of Phase 5/6 scope** per `RUST_PARITY_PLAN.md`
"Phasing" §3 (161 classes, 5.6% covered).

---

## 3. Recommended closure sequence

Today's afternoon wave compressed the closure list dramatically. The
"one-slice closures" stack from yesterday is mostly drained — only
the `spell_warped` setter, ManifestDread count>1, the
`LookAtTopNRevealOrCounter` random-order rewire, and the coverage-
overrides PR remain as small slices.

Ordered by leverage:

1. **Continue Phase 5 probes — event-driven surface.** The keyword-
   on-printing surface is now well-exercised (12 surfaces clean).
   Next priorities for the probe-close-probe cadence:
   - **Counterspells** (CR 701.5) — distinct surface from keyword
     gates; would surface the counter-target-spell interaction with
     stack-targeting and uncounterable. The Rust port already has
     `Effect::CounterTargetSpell` (variant 22, freq 7), so substrate
     is in place; the probe just needs a deckspec + selector. (A
     concurrent agent is mid-flight on this probe as of this
     writing.)
   - **ETB triggers** — event-driven dispatch path, distinct from
     the static-keyword gates. Likely to surface CE19 in the trigger
     emitter / event ordering substrate.
   - **Activated abilities mid-combat** — priority-window interaction
     between combat damage and the stack.
   - **Flash** (CR 702.8) — instant-speed creature casts during
     combat; exercises the timing-restriction layer and the can-cast
     gate at non-main-phase steps.
   - **Modal spells** — `ModalChooseOne` / `Effect::ChooseOneMode`
     interaction with cross-engine smoke. Requires the coverage-
     overrides merge to land first to avoid orphan-test red.

2. **`spell_warped_this_turn` flag setter.** Single-site addition on
   the warp-cast cost path. Closes the Void-cards substrate gap.

3. **`LookAtTopNRevealOrCounter` "random order" tail.** One-Effect-
   arm rewire on the now-plumbed `state.rng`. Small slice.

4. **ManifestDread face-down + count>1.** Unchanged scope. Priority
   medium-low.

5. **G8 multi-kind counter map.** Unchanged. Low priority until a
   pool card asks the divergence question.

6. **`feature/coverage-overrides` PR merge.** User-gated. Flips
   `test_no_orphan_rust_variants` green and the coverage table reads
   the orphan-mapped variants (`ChooseOneMode`,
   `GrantKeywordToTargetCreatureUntilEOT`, `SetBasePTUntilEOT`) as
   covered. Not blocking any closure.

**One-slice vs substrate-prep summary** (revised):

- One-slice closures remaining: `spell_warped` setter,
  `LookAtTopNRevealOrCounter` rewire, ManifestDread count>1,
  coverage-overrides merge.
- Medium scope: ManifestDread face-down (substrate choice),
  G8 (multi-kind counter map).
- **No remaining cross-engine CE divergences** — the open-CE column
  is empty for the first time in the project. The next divergence
  will come from a probe extension into the event-driven surface.

---

## 4. What "ready to test" means concretely

The plan doc's target is **1000-game cross-engine smoke clean**.
Today is a second inflection point on this estimate.

Estimate evolution:
- 2026-05-11 morning: **80-85% remaining** (pre-CE2 closure).
- 2026-05-11 mid-day: **60-70%** (post-CE3 + multi-turn walk).
- 2026-05-11 end-of-day retro: **60-70%** (CE5 surfaced).
- 2026-05-12 mid-day: **45-55%** (CE9 closed with 1000/1000 multi-
  block, CE11 closed, CE12 surfaced).
- 2026-05-12 end-of-day-yesterday snapshot: **30-40%** (CE8 closed,
  CE13 lone open).
- **End-of-afternoon 2026-05-12: 20-30% remaining.**

**Rationale for 20-30%:**

1. **Zero open CE divergences.** Every CE surfaced through CE18 is
   closed. The cross-engine smoke now drives twelve combat surfaces
   to byte-identical state for 200+ decisions each. This is the
   first time in the project the "open CE" column has been empty.
2. **Cross-engine MT shuffle parity is byte-identical.** Effect-rng-
   threading shipped end-to-end; `Effect::SearchLibraryForBasicLandTapped`
   consumes the harness-supplied `random.Random` via
   `state.rng_ref()`. Multi-seed cross-engine smoke confirms byte-
   identical post-search libraries.
3. **Three of four open G-gaps closed.** G12 audited + retired, G19
   closed in two stages (xorshift fallback + MT-parity threading),
   G24 shipped Paris scry-on-keep with 19 pinning tests. Only G8
   remains, and it's low priority.
4. **The substrate stack is small.** `spell_warped` setter,
   `LookAtTopNRevealOrCounter` rewire, ManifestDread count>1, and
   coverage-overrides PR are the only remaining named follow-ups.
5. **Defender-only target arms rewrite is in.** Yesterday's
   documented `bf-iter-resolve-arms` follow-up shipped; four arms
   now walk `bf_iter_etb_sorted` across both players matching
   Python's `TargetSpec` filter.
6. **The remaining risk is concentrated in the event-driven surface
   (ETB triggers, activated abilities mid-combat, flash, counter-
   spells).** No pre-emptive audit yet, so the probe-close cadence
   will drive their discovery. Each surface probe will likely
   surface 1-2 CE divergences (mirroring today's keyword-probe
   rate); each closes in a small-to-medium slice.

**Velocity bound.** Today's afternoon wave closed 6 CEs + 3 G-gaps +
2 substrate items + landed 6 clean keyword probes + 1 surface-then-
close (CE18) in a single session. That rate is unusually high —
sustaining it would put 1000-game-ready inside the next session. A
more realistic projection accounting for substrate discovery (trigger
emitter, layered effects for granted-keywords parity) is **3-5 more
sessions to 1000-game-ready**, with the keyword surface essentially
complete and remaining work biased toward event-driven dispatch and
substrate-prep.

The main risks: (a) the trigger-emitter substrate may need a Phase
7-shaped surface (`Effect`-emitted events as first-class actions on
the stack) that materially expands scope; (b) flash + priority-
window interactions could surface a layered-continuous-effect gap
that triggers a Phase 7+ refactor mid-Phase-5; (c) the ManifestDread
face-down deferral becomes load-bearing when a probe drives a
manifest-dread card.

---

## 5. Forward-looking items beyond Phase 5

Out of scope of Phase 5 and Phase 6 (unchanged):

- **The 161 singleton Effect classes** — explicitly excluded from
  the parity deck pool. The 1000-game smoke uses a "core-effects-
  only" pool by construction.
- **Layered continuous-effect cache** — Rust has no analog today.
  Per parity plan risks §3, missing layered logic for anthems /
  pump-UEOT / become-creature effects becomes a silent-wrong-answer
  source as those cards enter the pool. Layer 6 (lose all abilities)
  and Layer 7 (P/T) are the most common; Layer 1-5 rarer. UEOT
  modifiers get us partway but the full layer engine is Phase 7+.
- **Full combat damage assignment edge cases** — current Rust covers
  basics + multi-block + deathtouch-no-trample (CE14) + trample-
  multi-block (CE15) + double-strike spillover (CE18). The probe
  surface for plain first-strike, vigilance, lifelink, haste,
  menace, defender, indestructible, flying, hexproof is all clean.
  Real combat parity edge cases past today's surface — protection,
  shadow / fear / intimidate, banding (out of scope per pool), and
  multi-step trigger chains within combat damage — are Phase 7+.
- **Stack timing on multi-level trigger chains** — round 9 ETB
  covers simple cases. Deep trigger-chain ordering and the trigger
  emitter substrate are the next-largest known unknowns. Phase 7+.
- **Counterspell parity** — `Effect::CounterTargetSpell` (variant
  22) is shipped; the cross-engine probe extension into counter-
  target interactions is in the recommended next-slice queue. Likely
  to surface a CE19 in the stack-targeting / can-be-countered
  gating layer.

**Review queue**: `feature/coverage-overrides` PR (`2bcdd842`,
pushed 2026-05-11) remains unmerged. Required to flip
`test_no_orphan_rust_variants` green and have
`RUST_EFFECT_COVERAGE.md` read the 3 orphan-mapped variants
(`ChooseOneMode`, `GrantKeywordToTargetCreatureUntilEOT`,
`SetBasePTUntilEOT`) as covered. Not blocking any Phase 5 closure,
but it's the persistent pre-existing red on every Python gate.
