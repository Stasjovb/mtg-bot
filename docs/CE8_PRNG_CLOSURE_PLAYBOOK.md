# CE8 PRNG-mismatch closure playbook

Pre-staged closure plan for **CE8** — the open shuffle-PRNG divergence
between Python's Mersenne Twister and Rust's xorshift64. The biggest
remaining architectural item per `docs/RUST_PARITY_PLAN.md` Decision 1.

Mirrors the structure of `docs/CE5_CE6_CE7_CLOSURE_PLAYBOOK.md` (shared
substrate proposal, per-CE plans, dependency notes, post-closure
verification, risk register). The value is having one place a slice
author can read top-to-bottom before opening a worktree.

**Status when this doc was written (2026-05-12):**

- CE8 is filed and OPEN in `docs/RUST_PARITY_GAPS.md` (entry at
  line 1690). Filed today as part of `feature/apply-pending-ce-filings`
  (merge `07850c50`).
- The xfail pin is
  `tests/test_parity_smoke_edge_cases.py::test_cross_engine_shuffle_seed_walks_clean`
  (line 401, strict-xfail). Companion symptom-present pin at line 427
  (`test_cross_engine_shuffle_seed_surfaces_library_divergence_for_multiple_seeds`).
- CE5 / CE6 / CE7 / CE9 / CE10 / CE11 are all CLOSED. CE9 is
  intentionally left unallocated for the next surfacing slice. Per the
  retro doc's "Honorable mentions": **RNG externalization gates CE8 +
  G19 + many search-library Effects** — closing CE8 is a substrate
  slice, not a one-Effect slice.

---

## Section 1: The gap

### Restatement

Python's `state.rng` is a `random.Random` (MT19937 Mersenne Twister).
Rust's shuffle path uses an inline `XorShift64` PRNG (see
`rust/src/state_ops_library.rs:47-86`, `state_ops_setup.rs:81-117`,
`state_ops_mulligan.rs:84-117` — three copies of the same xorshift64
struct). The same numeric seed produces permutation `P_py` on Python
and `P_rust` on Rust, where `P_py ≠ P_rust` except by birthday-style
accident.

**Where the divergence surfaces today.** Any cross-engine smoke spec
that sets a non-`None` `shuffle_seed` diverges at step 0 (before any
decision is applied) on `library_p0` and `library_p1`. The harness
sidesteps the problem in production by defaulting `shuffle_seed=None`
on every Phase-5 cross-engine spec; the parity-smoke spec is the only
test that currently exercises the divergence.

**Where the divergence will surface once we get past Phase 5.** Every
in-engine shuffle: mulligan deck shuffle, search-and-shuffle tutors
(CR 701.18), library shuffles from Effects (e.g. Nexus of Fate,
Green Sun's Zenith), the shuffle path in `library_lookat`'s look-at-
top-N-then-shuffle-remainder. Today's spec uses `shuffle_seed=None`
because we haven't probed any of these flows cross-engine yet; once
the cast-vs-resolve slice closure cadence reaches mulligan / tutor /
shuffle-effect probes, the gap blocks every one of them.

### Pinning tests + file:line

| Pin | File:line | Shape |
|---|---|---|
| Strict-xfail clean-walk pin | `tests/test_parity_smoke_edge_cases.py:401` | Asserts `library_p0` / `library_p1` are NOT in `result.initial_divergences` (today fails — strict-xfail). Flips to xpass when CE8 closes. |
| Symptom-present companion | `tests/test_parity_smoke_edge_cases.py:427` | Asserts `library_p0` IS in `result.initial_divergences` for seeds 1, 7, 42, 100. Today passes. Flips to failing (or gets deleted) when CE8 closes per the closure-pair contract. |

### CR backing

CR 103.4 / 701.20 mandate that the library is randomized; the CR is
silent on WHICH PRNG the engine uses. The parity reference is "Python's
Mersenne Twister output for any given seed" because the cross-engine
smoke contract pins **Python as the observable source of truth** (per
`RUST_PARITY_PLAN.md` Decision 1). The closure recommendation flips
that: instead of Python being the SoT for the bit-permutation, the
harness becomes the SoT for the RNG stream consumed by both engines.

---

## Section 2: Option A — Match MT in Rust

### Sketch

Port MT19937 into Rust (existing crate `rand_mt` or a vendored impl;
~50 lines per the plan doc). Route every `shuffle_deck` site through
it. Bit-for-bit identical stream to Python's `random.Random` when
seeded identically.

### Implementation cost

**~50 lines of Rust per the plan doc.** Concrete touch list:

- New module `rust/src/mt19937.rs` (vendored impl + `next_u64` /
  `next_usize_below` API mirroring the existing `XorShift64` struct).
- Replace `XorShift64::new(seed)` with `Mt19937::new(seed)` at the
  three call sites: `state_ops_library.rs:150, 263, 482-ish`
  (`shuffle_library_with_seed`, `search_library_and_move_to_hand`,
  `search_library_for_first_of_type_and_shuffle`).
- Replace `XorShift64::new(seed)` in `state_ops_setup.rs:283-285`
  (`fisher_yates_shuffle` for p0 + p1 library at `make_state` time).
- Replace `XorShift64::new(seed)` in `state_ops_mulligan.rs:96-117`
  (mulligan shuffle path).
- Delete the three inline `XorShift64` struct copies (or keep them
  for slice-internal determinism — see Section 8).

### Critical subtlety: Python's `random.Random.shuffle` is NOT a
Fisher-Yates over `next_u64`. It's a Fisher-Yates over `_randbelow`
which uses rejection sampling. To get bit-identical permutations you
need to match Python's `_randbelow_with_getrandbits` rejection-sampling
algorithm exactly. This is doable but is the load-bearing part of the
port — naive `next_u64() % i` would mis-match Python's `random.shuffle`
because Python's rejection-sampling skip-on-bias differs from a naive
modulo.

### Pros

- Zero caller-side coupling. Rust stays self-contained — Python search
  / agents / harness don't need to know about Rust's RNG.
- The existing `shuffle_seed: u64` PyO3 surface stays unchanged.

### Cons

- **Subtle ordering bugs.** Any difference in DRAW ORDER between Python
  and Rust silently desyncs the stream. Example: if Python shuffles p0's
  library THEN p1's library while Rust shuffles p1 THEN p0, both engines
  consume the same draws but in a different order — final permutations
  differ even though the PRNG is identical. The current `state_ops_setup.rs`
  shuffles p0 first using `seed`, then p1 using `seed * P1_SEED_MULTIPLIER`,
  which DOES match the harness's current shape at
  `src/mtg_bot/parity/cross_engine.py:502-503` — but only because the
  harness was hand-aligned to mirror the Rust convention. Mid-game
  shuffles (tutor resolves, Nexus reshuffles) have no such per-call
  alignment; any draw-order divergence between the engines silently
  produces wrong permutations.
- **Hard to debug.** When the streams desync, the failure mode is "two
  big shuffled libraries that look correct in isolation but don't
  match" — there's no single-step diagnostic.
- **Doesn't close G19.** The
  `SearchLibraryForBasicLandTapped`-without-shuffle gap is structurally
  similar (Python shuffles, Rust doesn't) and needs the same
  RNG-stream substrate to close in a principled way.
- Ties Rust to a specific Python implementation detail. If Python ever
  swaps `random.Random` for a different PRNG (PEP 605 / 3.13+ talks),
  Rust would have to follow.

---

## Section 3: Option B — Externalize RNG to caller (RECOMMENDED per plan)

### Sketch

Every Rust gameplay-RNG-consuming method takes an `rng` parameter that
wraps a Python `random.Random` instance via PyO3. The parity harness
passes the SAME Python `random.Random` into BOTH engines. Any
draw-order divergence surfaces as a stream-position desync the harness
can detect.

### PyO3 binding shape

Rust accepts an `rng: &Bound<'_, PyAny>` parameter on each gameplay-
RNG method. To consume a single random draw, Rust calls back into
Python:

```rust
fn rng_next_below(rng: &Bound<'_, PyAny>, n: usize) -> PyResult<usize> {
    // Mirrors random.Random._randbelow signature.
    let v = rng.call_method1("_randbelow", (n,))?;
    v.extract::<usize>()
}
```

Two callback options:

1. **`_randbelow(n)`** — Python's internal Fisher-Yates primitive.
   Matches `random.shuffle`'s draw shape exactly. Underscore-prefixed
   (semi-private) but stable since Python 3.x.
2. **`random()` → float, then `int(r * n)`** — public API but
   does NOT match `random.shuffle`'s draws (which use `_randbelow`
   for rejection-sampling parity). Use this only if we don't need
   per-draw equivalence to Python's `random.shuffle` and the harness
   does its OWN Fisher-Yates on top of the shared stream.

**Recommend `_randbelow`.** Stable interface, exact match for Python's
own `shuffle` semantics, and (critically) matches what an agent calling
`state.rng.shuffle(p.library)` would consume from the stream. The
underscore-prefix is a Python-internal stability convention, not a
versioning hazard — `random.py`'s `_randbelow` has been stable since
Python 3.0.

There are no existing PyO3 random-binding patterns in the project
today; this slice introduces the first one.

### Internal-only RNG stays as-is

Per `RUST_PARITY_PLAN.md` Decision 1:

> Round-4's xorshift64 in Rust slices stays for slice-internal
> determinism (e.g., search-and-shuffle's seed) but the **game-loop
> RNG is caller-owned**.

So the three inline `XorShift64` structs in `state_ops_library.rs`,
`state_ops_setup.rs`, `state_ops_mulligan.rs` are **not** all deleted —
only the gameplay-facing shuffle paths get rewired. The
search-and-shuffle slice's internal seed mixing stays on xorshift64
because no Python counterpart consumes those draws.

### Pros

- **Turns determinism order-of-operations bugs into loud, single-step
  desyncs.** When Python and Rust consume the SAME RNG instance and
  produce different observable state, the harness can flag exactly
  which draw was consumed in which order. The failure mode is
  diagnostic, not silent.
- **Closes G19 for free.** The SearchLibraryForBasicLandTapped Rust arm
  consumes from the same external stream, so once the substrate is in
  place, fixing G19 is one Effect-arm edit.
- Decouples engines from PRNG choice. If Python ever swaps `random.Random`
  for a different impl, Rust doesn't care — Rust only consumes from
  whatever stream the caller hands in.
- Architecturally correct shape per the plan doc.

### Cons

- **Every RNG call site must be rewired.** 16-ish gameplay sites
  (audit in Sections 5 and 6).
- **PyO3 callback overhead per draw.** A 60-card library shuffle is 60
  callbacks Python→Rust→Python; each callback has GIL acquisition +
  attribute lookup + integer marshal cost. Realistic estimate:
  ~1-2 µs per draw, ~60 µs per library shuffle. Bench post-closure;
  may need a batched-draw API if hot.
- New mandatory positional parameter on every gameplay-RNG method —
  every existing call site in tests / production needs an `rng=`
  argument added.

---

## Section 4: Recommended path

**Pick Option B.** Plan recommends it; the 16 RNG call sites are
concentrated (every gameplay-RNG site flows through `state.rng` on
Python and through one of three inline xorshifts on Rust); the desync-
as-diagnostic property is load-bearing for the cadence ahead (the next
several Phase-5 probes will all exercise shuffles).

### Sub-decisions

| Sub-decision | Choice | Rationale |
|---|---|---|
| PyO3 callback shape | `rng.call_method1("_randbelow", (n,))` returning `usize` | Matches Python's `random.shuffle`'s draw shape exactly; stable since Py 3.0. |
| RNG-parameter type | `rng: &Bound<'_, PyAny>` on every gameplay-RNG `#[pymethods]` method | The minimum PyO3 surface — accept anything that has `_randbelow`. Concrete in tests can pass `random.Random(seed)` directly. |
| Internal-only RNG | Slice-internal xorshift stays | Plan-mandated; the search-and-shuffle seed-derivation has no Python counterpart. |
| p1-shuffle seed multiplier (`P1_SEED_MULTIPLIER`) | RETIRE on the externalized paths | Once both engines consume from the SAME `rng`, the per-player magic constant in `state_ops_setup.rs:79` becomes obsolete; the harness controls draw order. Keep the constant for now (back-compat with non-cross-engine callers that still pass `shuffle_seed: u64`), schedule retirement once the integer-seed path is no longer needed. |
| Backward compat | Keep `shuffle_seed: Option<u64>` on `make_state` for non-cross-engine callers; add `rng: Option<&PyAny>` alongside it | Production Rust callers (the cli / bench paths) don't need the rewire today; tests / cross-engine specs use the new param. Allows incremental rollout. |

---

## Section 5: Concrete RNG call sites in Rust (audit)

Grep result (`grep -rn "xorshift\|XorShift\|next_u64\|next_usize_below\|fisher_yates" rust/src/`) yields the following inventory. Each entry: file:line, purpose, Python counterpart, slice action.

| # | Rust file:line | Purpose | Python counterpart | Rewire this slice? |
|---|---|---|---|---|
| R1 | `state_ops_setup.rs:283` | `fisher_yates_shuffle(p0_library, seed)` at `make_state` time | `simulate.py:138` / harness `cross_engine.py:502` | **Yes** — gameplay setup shuffle |
| R2 | `state_ops_setup.rs:285` | `fisher_yates_shuffle(p1_library, p1_seed)` at `make_state` time | `simulate.py:138` / harness `cross_engine.py:503` | **Yes** — gameplay setup shuffle (drops `P1_SEED_MULTIPLIER` on the rng-path) |
| R3 | `state_ops_library.rs:150` | `shuffle_library_with_seed` — gameplay library shuffle | `game.py:820` `shuffle_library` (calls `state.rng.shuffle(p.library)`) | **Yes** — gameplay |
| R4 | `state_ops_library.rs:263` | `search_library_and_move_to_hand` post-search shuffle (CR 701.18) | `effects/generic/search.py` shuffle paths (lines 96, 108, 119, 217, 233, 274, 285, 293) | **Yes** — gameplay |
| R5 | `state_ops_library.rs:482-ish` | `search_library_for_first_of_type_and_shuffle` post-search shuffle | same as R4 family | **Yes** — gameplay |
| R6 | `state_ops_mulligan.rs:129` | `mulligan(player_id, seed)` — mulligan reshuffle | `actions.py` mulligan paths → `shuffle_library(state, p.id)` | **Yes** — gameplay |
| R7 | `state_ops_mulligan.rs:215` | `mulligan_to_n` — variant entry | same as R6 | **Yes** — gameplay |
| R8 | `state_ops_mulligan.rs:433` | mulligan-with-bottom variant | same as R6 | **Yes** — gameplay |
| (internal) | xorshift seed-derivation in search-and-shuffle slice's PendingDecision pipeline | slice-internal determinism only | none (no Python counterpart) | **No** — stays xorshift per plan |

**Total: 8 gameplay-RNG Rust sites to rewire** (the three inline
`XorShift64` struct copies stay in source until the
search-and-shuffle slice's internal usage is migrated, which is a
follow-up housekeeping pass).

Note: the plan doc's headline figure of "16 RNG call sites" counts
both Rust and Python sites; the **Rust-side count is 8**, the
Python-side count is also ~8 (Section 6) — they sum to the plan's 16.

---

## Section 6: Concrete RNG call sites in Python (counterparts)

Grep result (`grep -rn "state\.rng\|rng\.shuffle\|rng\.choice\|rng\.randrange\|rng\.random" src/mtg_bot/`) yields the following inventory limited to **engine gameplay** sites. (Agent-side `self.rng` in `agents.py` and `search/*` is search-side, not gameplay — those don't need cross-engine matching because the Rust side has no agent.)

| # | Python file:line | Purpose | Rust counterpart | Slice rewires? |
|---|---|---|---|---|
| P1 | `game.py:820` `shuffle_library` | Canonical library shuffle helper — every library shuffle in production goes through this | R3 `shuffle_library_with_seed` | **Yes** — gameplay |
| P2 | `actions.py:1840` `card = state.rng.choice(p.hand)` | Random discard from hand (Ward-style random discard) | (no Rust arm today; future Effect) | **Yes** — gameplay; if/when the Effect lands in Rust, it consumes the shared rng |
| P3 | `simulate.py:130` `state.rng.seed(seed)` + downstream `random.Random(seed)` in `simulate.py:131` for the setup shuffle | Setup deck shuffle in synthetic-game simulator | R1 / R2 setup shuffles | **Yes** — gameplay setup |
| P4 | `simulate.py:138, 166, 484` `rng.shuffle(p.library)` | Setup deck shuffle, mid-sim re-shuffle | R1 / R2 / R3 | **Yes** |
| P5 | `effects/bespoke.py:1202` `state.rng.shuffle(remaining)` | Bespoke effect shuffle (a "shuffle remainder back" pattern in look-at flows) | (no Rust arm yet) | **Yes** when ported |
| P6 | `effects/bespoke.py:2718` `state.rng.shuffle(revealed)` | Bespoke effect shuffle (cascade-style ordering) | (no Rust arm yet) | **Yes** when ported |
| P7 | `effects/generic/library_lookat.py:136` `state.rng.shuffle(remaining_examined)` | Look-at-top-N then shuffle the remainder back | (Rust today has `scry` + `apply_scry`; the shuffle-remainder path isn't ported) | **Yes** when ported |
| P8 | `effects/generic/search.py:96, 108, 119, 217, 233, 274, 285, 293` (all via `shuffle_library(state, controller_id)`) | Tutor-style search-and-shuffle (CR 701.18) | R4 / R5 | **Yes** — gameplay |
| P9 | `effects/bespoke.py:139` `shuffle_library(state, controller_id)` | Self-shuffle dropper (Nexus of Fate, Green Sun's Zenith) | (no Rust arm yet for these bespoke spells) | **Yes** when ported |
| P10 | `effects/generic/zone_moves.py:361` `shuffle_library(state, controller_id)` | Generic zone-move-into-library + shuffle | (no Rust arm yet) | **Yes** when ported |

**Total: ~10 gameplay-RNG Python sites** (some are wrappers around
`shuffle_library` which itself is one consumer of `state.rng`; the
substantive count is the call sites of `shuffle_library` + the direct
`state.rng.*` callsites, which sum to ~8 unique gameplay paths
matching the plan's "8 engine-side shuffle paths" figure).

The agent-side `self.rng` usages in `agents.py` (lines 392-510) are
NOT gameplay sites — they live in the search-side `RandomAgent` and
have no Rust counterpart (Rust has no agent; the agent stays Python).
These don't need rewiring.

---

## Section 7: Threading plan

### Step 1: PyO3 surface — add `rng` parameter

Update every gameplay-RNG `#[pymethods]` method on `GameState` to
accept an optional `rng: Option<&Bound<'_, PyAny>>` parameter:

```rust
fn shuffle_library_with_seed(
    &mut self,
    player_id: u8,
    seed: u64,
    rng: Option<&Bound<'_, PyAny>>,  // NEW
) -> PyResult<()> { ... }
```

When `rng` is `Some(_)`, Rust consumes from the external stream via
`_randbelow` callbacks. When `rng` is `None`, Rust falls back to the
existing xorshift64 (backward compat). Production callers that don't
care about cross-engine parity (cli / bench) pass `rng=None`; cross-
engine smoke specs pass `rng=Some(shared_random_random_instance)`.

Methods to update (from Section 5):

- `shuffle_library_with_seed`
- `search_library_and_move_to_hand`
- `search_library_for_first_of_type_and_shuffle`
- `mulligan`, `mulligan_to_n`, mulligan-with-bottom variant
- `make_state` (drops the per-player `seed * P1_SEED_MULTIPLIER`
  derivation when `rng is Some` — the rng owns draw order)

### Step 2: Rewire each call site to consume from the threaded `rng`

```rust
let mut next_below = |n: usize| -> PyResult<usize> {
    match rng {
        Some(r) => r.call_method1("_randbelow", (n,))?.extract::<usize>(),
        None => Ok(xorshift.next_usize_below(n)),
    }
};
// Fisher-Yates loop unchanged:
for i in (1..n).rev() {
    let j = next_below(i + 1)?;
    lib.swap(i, j);
}
```

The control flow is identical; only the `next_below` source changes.

### Step 3: Update the parity harness

`src/mtg_bot/parity/cross_engine.py` — current shape (lines 492-503):

```python
if spec.shuffle_seed is not None:
    random.Random(spec.shuffle_seed).shuffle(p0.library)
    random.Random(spec.shuffle_seed * 6364136223846793005 & ...).shuffle(p1.library)
```

becomes:

```python
if spec.shuffle_seed is not None:
    shared_rng = random.Random(spec.shuffle_seed)
    shared_rng.shuffle(p0.library)
    shared_rng.shuffle(p1.library)
    # Rust side gets the SAME instance:
    rust_state = make_state(..., rng=shared_rng)
```

Both engines consume from the same `random.Random` instance in the same
order. Python's `shuffle` consumes N-1 draws for an N-card library;
Rust's Fisher-Yates loop consumes the same N-1 draws in the same
order (because both are Fisher-Yates over `_randbelow`).

### Step 4: Cross-engine smoke tests

Add tests to `tests/test_parity_smoke_edge_cases.py`:

- `test_cross_engine_mulligan_walks_clean` — set up a state where both
  players mulligan once; assert post-mulligan libraries match.
- `test_cross_engine_search_and_shuffle_walks_clean` — resolve a tutor
  effect that shuffles; assert post-shuffle library matches.
- `test_cross_engine_per_card_library_order_matches` — for any shuffle
  scenario, assert per-card library order matches across engines
  (not just hash equality — per-card so a bug isolates to ONE swap).

---

## Section 8: Existing rust slices that already use external RNG

Per the plan doc:

> Round-4's xorshift64 in Rust slices stays for slice-internal
> determinism (e.g., search-and-shuffle's seed) but the **game-loop
> RNG is caller-owned**.

### Round 21+ "externalized RNG threading on existing slices"

Git history search (`git log --oneline --all | grep -i rng`) found
**one** dedicated commit:

- `6a5950ca` "Route in-engine RNG through state.rng for
  search-reproducibility" — Python-side. Routes any in-engine random
  call through `state.rng` so a search-reproducibility seed propagates.
  This is the Python-side substrate that the Rust side mirrors.

The "externalized RNG threading on existing slices" mentioned in
`RUST_PARITY_PLAN.md` Phase 2 (round 21) refers to the round-21 Phase
2a/2b bridge work (`fb71ad40` round 21, `829fb050` round 22). Those
merged the `state_ops_snapshot.rs` stub and zone-snapshot slices that
gave the PyO3 surface the shape needed to thread an external rng
parameter through. They did NOT yet thread the rng parameter — that's
this slice. The substrate (PyO3 surface, `Bound<'_, PyAny>` patterns,
`Arc::make_mut` zone mutation) is in place.

### Where Rust's xorshift64 stays after CE8

Three inline `XorShift64` structs exist today, all identical:

- `rust/src/state_ops_library.rs:47-86`
- `rust/src/state_ops_setup.rs:81-117`
- `rust/src/state_ops_mulligan.rs:84-117`

**Post-CE8 disposition:**

| Site | Disposition |
|---|---|
| `state_ops_library.rs` xorshift | RETAIN as the `rng=None` fallback. Production cli/bench callers continue using it. |
| `state_ops_setup.rs` xorshift | RETAIN as the `rng=None` fallback. |
| `state_ops_mulligan.rs` xorshift | RETAIN as the `rng=None` fallback. |
| Search-and-shuffle internal seed mixing (slice-internal determinism, no Python counterpart) | STAYS on xorshift forever — no parity contract. |

Consolidating the three duplicate `XorShift64` structs into a single
`rust/src/rng_internal.rs` module is a housekeeping follow-up; NOT
required for CE8 closure. The duplication is intentional today (each
slice ported its own copy to avoid cross-module dependency creep).

---

## Section 9: Pinned tests that will shift

### Direct pins

| Pin | File:line | Disposition |
|---|---|---|
| `test_cross_engine_shuffle_seed_walks_clean` | `tests/test_parity_smoke_edge_cases.py:401` | **strict-xfail flips to xpass.** Remove the `@pytest.mark.xfail(strict=True, ...)` marker. |
| `test_cross_engine_shuffle_seed_surfaces_library_divergence_for_multiple_seeds` | `tests/test_parity_smoke_edge_cases.py:427` | **starts failing.** Remove or invert per the closure-pair contract (the test name itself flags that the symptom is intentional pre-closure). |

### Indirect pins (existing rust-side shuffle tests)

These tests pin specific xorshift64 permutation outcomes. They may
shift, or may continue to pass under `rng=None`:

| Test family | File | Risk |
|---|---|---|
| Library shuffle determinism | `tests_rust/test_library.py` (shuffle-with-seed pins) | Low — `rng=None` path keeps xorshift, baseline stays. Verify by running gate post-slice. |
| Mulligan shuffle outcomes | `tests_rust/test_mulligan.py` | Low — same reason. |
| Setup shuffle | `tests_rust/test_setup.py` (the `EXPECTED_MAKE_STATE_CANONICAL_DEFAULT_FP` digest at `411d5b757c22`) | None — the default fixture uses `shuffle_seed=None`, no shuffle happens. |
| `tests/test_parity_smoke.py` synthetic digest pins | none today are shuffle-driven | None |

The slice author should run the full `tests_rust/` gate after the
PyO3-surface change but BEFORE wiring the harness. Every pin should
still pass under `rng=None` because the xorshift path is unchanged.
If any pin shifts, the slice has a parameter-handling bug, not a
genuine baseline shift.

### Cross-engine smoke baselines

Once CE8 closes:

- Probes that today pass with `shuffle_seed=None` continue passing
  (no shuffle, no change).
- Probes that need a shuffle (mulligan, tutor) currently CAN'T BE
  WRITTEN because the divergence blocks them. Post-CE8, those probes
  become writable. Each new probe is a new test, not a baseline shift.

### Mitigation strategy

- Use deterministic `random.Random(seed)` fixtures in new tests so the
  expected permutation is pinned by Python's MT (which is the spec).
- For Rust-only tests that pin xorshift permutations, KEEP the
  `rng=None` calling convention so the pins stay valid.
- For cross-engine tests that need a specific permutation, build the
  expected library by running Python's `random.Random(seed).shuffle`
  inline in the test; assert Rust's `library_snapshot` matches.

---

## Section 10: Estimated slice scope

### Headline numbers

- **8 Rust gameplay-RNG call sites to rewire** (Section 5).
- **~8 Python gameplay-RNG paths** that the harness needs to align
  (Section 6) — most are already shared via `shuffle_library` helper.
- **2 pinned tests** that flip (Section 9).
- **3-5 new cross-engine smoke tests** that become writable post-
  closure (mulligan, tutor, library-shuffle Effect).
- **1 new PyO3 binding pattern** (`_randbelow` callback into Python).

### Per the plan doc

> "one-time cost, then we never argue about MT vs xorshift64 again."

The substrate (PyO3 surface, `Bound<'_, PyAny>` plumbing, Arc-zone
mutation) is in place — Phase 2 (rounds 21-22) landed it for the
non-rng PyO3 surface. CE8 extends that pattern to one more parameter.

### Estimate

**1-2 slices.**

- **Slice 1 (substrate + setup-shuffle):** Add `rng: Option<&PyAny>`
  to `make_state` + `shuffle_library_with_seed`; rewire those two
  paths; update harness; flip the strict-xfail; remove the
  companion symptom-pin. **~150-200 lines changed** (PyO3 surface,
  fallback plumbing, harness update, two test pin flips, two new
  smoke tests).
- **Slice 2 (gameplay shuffles):** Rewire the other 6 gameplay sites
  (mulligan x3, search-and-shuffle x2, library-shuffle helper x1).
  **~100 lines changed.** Each site is a near-copy of slice 1's
  pattern.

The two slices are independently shippable — slice 1 closes the filed
CE8 (the strict-xfail flips); slice 2 makes the substrate available
to the gameplay shuffle paths that don't currently have cross-engine
probes but will need them once the cadence reaches them.

Probably one big slice for the threading + a follow-up for any
baseline shifts that surface — matches the playbook prompt's
estimate.

---

## Section 11: Risk register

### Risk 1: A missed site that still consumes the old internal RNG continues to diverge

**Risk.** The audit enumerates 8 Rust gameplay-RNG sites, but a new
Effect added between this playbook and CE8's landing could introduce
a 9th. CE8's slice would not catch it.

**Likelihood:** medium — the cast-creature probe cadence is actively
adding Effect arms; ManifestDread / Optional-Mana-Cost-Then-Effect
landed just yesterday. A new shuffle-consuming Effect could land
between now and the CE8 slice.

**Mitigation.** Before CE8 closure lands, grep
`rust/src/` for `XorShift64::new\|fisher_yates_shuffle` and confirm
the count matches the 8 sites in Section 5 (after dedupe of the three
struct copies). Any new site needs to be added to the rewire list.
Run a cross-engine smoke that exercises EVERY shuffle path
(mulligan + search-and-shuffle + library-shuffle Effect + setup
shuffle) so a missed site surfaces as a clear divergence.

### Risk 2: PyO3 binding callback overhead

**Risk.** Every `_randbelow` callback round-trips Rust→Python→Rust
through GIL acquisition + attribute lookup + integer marshal. A
60-card library shuffle is 60 callbacks. Realistic estimate
~1-2 µs / draw → ~60-120 µs / library shuffle. Multiplied across
mulligans + tutors + Effect shuffles per game, could be measurable.

**Likelihood:** low for cross-engine smoke (the smoke is the only path
that uses `rng=Some(...)` — production stays on xorshift64). Medium if
a future codepath needs Python-MT-matching shuffles outside the
smoke.

**Mitigation.**

1. Production callers pass `rng=None`; the cost is paid only in the
   harness, where wall-time isn't a hot constraint.
2. If the harness gets slow, add a batched-draw API: Rust calls
   `rng.call_method1("_batch_randbelow", (vec_of_bounds,))` that
   returns a Vec<usize> in one round-trip. Python-side helper wraps
   `_randbelow` in a loop. Drops callback count by ~10x.
3. Bench post-closure with `scripts/bench_clone.py` and the
   cross-engine smoke wall-time; only optimize if measured slow.

### Risk 3: Pinned-test baseline shifts cascade

**Risk.** A change to RNG draw order shifts one fingerprint baseline,
which cascades into every test that builds on the affected state.

**Likelihood:** very low. The production path stays on `rng=None`
xorshift; every pinned fingerprint test uses synthetic-state
fixtures with `shuffle_seed=None`. The two known shifting pins are
the strict-xfail + its companion (Section 9), both of which are
expected and required.

**Mitigation.** Run the full `tests_rust/` gate post-slice. Any
unexpected pin shift is a parameter-handling bug (the new `rng`
parameter is being passed where it shouldn't be), not a baseline
shift. Audit `Option<&PyAny>` defaults at every PyO3 method signature
and confirm `rng=None` is the default everywhere production callers
hit.

### Risk 4: Python's `_randbelow` semi-private API instability

**Risk.** `random.Random._randbelow` is underscore-prefixed and could
theoretically change shape across Python versions (though it has been
stable since Py 3.0).

**Likelihood:** very low. The CPython source for `_randbelow_with_getrandbits`
has had two minor refactors since Py 3.0 (commit cba9a44f8a, commit
2f0d8b7b3a) but the SIGNATURE `_randbelow(self, n: int) -> int` has
been bit-stable. Even the algorithm is unchanged — only docstrings
and inlining shifted.

**Mitigation.** Add a CI smoke that constructs a `random.Random(42)`,
calls `_randbelow(60)` 1000 times, and asserts the resulting sequence
hashes to a known value. Flag if a Python upgrade ever shifts the
hash. If it ever does, vendor a 30-line `python_random_compat.py`
that reproduces Py 3.13's `_randbelow` deterministically.

### Risk 5: Draw-order divergence post-closure

**Risk.** Even after externalizing the RNG, if Python and Rust consume
draws in different ORDERS, the streams still desync.

**Likelihood:** medium — this is exactly the failure mode Option B is
designed to make LOUD. The risk is post-closure that we have an order
divergence; the mitigation is that the harness DETECTS it because the
draws are now shared.

**Mitigation.** The architecture is the mitigation: any draw-order
divergence surfaces as a stream-position desync at the first divergent
draw, instead of being silently absorbed into "different shuffled
libraries". When this happens post-closure, the diagnostic is:
"Python consumed `_randbelow(60)` at step K, Rust consumed
`_randbelow(45)` at step K — the streams diverged at draw K because
the two engines shuffled different-length zones in different orders."
That's a one-step fix (align the order on whichever engine is wrong).

### Risk 6: G19 (SearchLibraryForBasicLandTapped no-shuffle) coupling

**Risk.** G19 and CE8 share the RNG-externalization substrate. If CE8
lands without simultaneously closing G19's Rust-side missing-shuffle,
G19 stays open as a follow-up.

**Likelihood:** certain — G19 is its own slice. The retro doc and
CE8's entry both note the coupling.

**Mitigation.** Treat G19 as the natural slice 2 (or slice 3) of the
CE8 closure family. Once the substrate lands, G19 is a one-Effect-arm
edit (`SearchLibraryForBasicLandTapped`'s Rust arm calls the new
`shuffle_library_with_rng` after the search). File a separate todo
referencing CE8 as the unblocker.

### Risk 7: Backward-compat for production cli/bench callers

**Risk.** Adding `rng: Option<&PyAny>` to `make_state` breaks the
cli's bench scripts (`mtg_bot bench clone` etc) which call
`make_state` with positional args.

**Likelihood:** low — Python's PyO3-side signature already uses
keyword args (`make_state(decks=..., shuffle_seed=...)`); adding
`rng=None` as another optional kwarg is non-breaking. But
double-check the `make_state` call sites in `src/mtg_bot/cli/` and
in test fixtures.

**Mitigation.** Grep `make_state(` across the project before
landing the PyO3 surface change. Confirm every call site is
kwarg-style. If any positional caller exists, fix it to kwargs in
the same slice.

---

## Appendix: file:line cheat sheet

| Anchor | File:line |
|---|---|
| CE8 entry in parity gaps | `docs/RUST_PARITY_GAPS.md:1690` |
| Strict-xfail pin | `tests/test_parity_smoke_edge_cases.py:401` |
| Companion symptom-present pin | `tests/test_parity_smoke_edge_cases.py:427` |
| Plan doc Decision 1 | `docs/RUST_PARITY_PLAN.md:37` |
| Rust xorshift64 in library | `rust/src/state_ops_library.rs:47-86` |
| Rust xorshift64 in setup | `rust/src/state_ops_setup.rs:81-117` |
| Rust xorshift64 in mulligan | `rust/src/state_ops_mulligan.rs:84-117` |
| `P1_SEED_MULTIPLIER` magic | `rust/src/state_ops_setup.rs:79` |
| Python shuffle helper | `src/mtg_bot/game.py:810-822` |
| Python harness shuffle setup | `src/mtg_bot/parity/cross_engine.py:492-503` |
| Python tutor shuffle paths | `src/mtg_bot/effects/generic/search.py:96, 108, 119, 217, 233, 274, 285, 293` |
| Rust gameplay-RNG entry sites | `state_ops_library.rs:135, 228, 404`; `state_ops_setup.rs:283-285`; `state_ops_mulligan.rs:129, 215, 433` |
| Round-21 PyO3 surface substrate | merge `fb71ad40` (zone-snapshot bridge), merge `829fb050` (round 22 bridge expansion) |
| Python-side RNG threading precedent | commit `6a5950ca` "Route in-engine RNG through state.rng" |
| Closure-pair contract | mirrors CE5-CE7 / CE9 / CE10 / CE11: flip strict-xfail to expected-pass + remove companion symptom-pin + add an I-section invariant in `RUST_PARITY_GAPS.md` |
