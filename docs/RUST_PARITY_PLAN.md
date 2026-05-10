# Rust-port parity plan

End goal: run 1000+ games on the Python engine and the Rust engine
with the same seeds + same decks, and assert byte-identical
`(state_hash, decision)` trajectories. This document is the punch
list to get there, grounded in measurements (not estimates) collected
in `docs/RUST_PARITY_MEASUREMENTS.md`.

## Headline numbers

- **228 distinct Python `Effect` classes** in the parsed pool (eoe +
  stellar_sights + special_guests_eoe + duskmourn = 475 printings).
  - 170 generic, 37 bespoke, 21 combinator/condition.
  - **14 classes appear ≥10 times** — the pareto.
  - **161 classes appear in exactly one card** — the long tail.
- **Rust currently exposes 16 `Effect` variants** (~7% by class
  count, but ~25-35% by card-frequency since the round-1-through-19
  variants targeted high-frequency effects).
- **6 `Action` subclasses observed** in one synthetic game: PassPriority
  (364), CastSpell (17), DeclareAttackers (16), PlayLand (10),
  ActivateAbility (8), DeclareBlockers (5). 4 more Action types exist
  in the codebase (`ActivateStation`, `TurnFaceUp`, `UnlockRoomHalf`,
  …) — EoE-specific mechanics, may or may not appear in real games.
- **16 in-engine RNG call sites**, all flowing through `state.rng`
  (Mersenne Twister via `random.Random`).
- **SBA order is literal** — 11 steps, fixed sequence, looped to
  quiescence with cap=50.
- **No APNAP trigger sort** — triggers go on the stack in
  battlefield-iteration × ability-index order. Single-controller queue
  makes APNAP moot in practice.
- **Layered continuous-effect cache** is small today — caches one
  boolean per source (`_source_layer6_wiped`), per-clone, 8
  invalidation sites.

## Strategic decisions to lock in *before* writing more code

### Decision 1 — RNG strategy

Two options:

**(a) Match Python's Mersenne Twister in Rust.** A correct MT
implementation is ~50 lines of Rust. Same seed → same stream. Pro: zero
caller-side coupling; Rust can be self-contained. Con: any subtle
ordering difference in *which* RNG draw fires first (e.g., we shuffle
lands before creatures in Python but creatures before lands in Rust)
silently desyncs the entire library order. Hard to debug.

**(b) Externalize RNG to the caller.** Rust's `apply_action`
takes an `rng: &mut dyn RngStream` parameter; every shuffle / random
choice consumes from it. The parity harness passes the SAME Python
`random.Random` into both engines, so any draw-order divergence
surfaces as a **stream-position desync** the harness can detect (and
both engines see the same draws regardless). Pro: turns determinism
order-of-operations bugs into loud, single-step desyncs. Con: every
RNG call site must be rewired to take an external RNG.

**Recommendation: (b).** Easier to debug, easier to test, treats
"draw order" as observable rather than implicit. The 16 call sites
are concentrated and all already go through `state.rng` — refactoring
to "external rng" is a one-time cost, then we never argue about MT
vs xorshift64 again. Round-4's xorshift64 in Rust slices stays for
slice-internal determinism (e.g., search-and-shuffle's seed) but the
**game-loop RNG is caller-owned**.

### Decision 2 — Drop-in vs side-by-side

The Rust GameState should be a **drop-in replacement** for Python's
GameState in the search loop. The agent (MCTS / ISMCTS / RandomBot)
is unchanged Python; it calls `state.legal_actions()`, gets back a
list of `Action` Python objects, calls `state.apply(action)`, and
asks `state.is_over()`. The Rust implementation owns the state +
rules; Python owns the search + NN + training. This matches
the architecture decision in `rust/README.md` and the round-19
Effect bridge work.

**The PyO3 surface to expose** (just the public methods Python
search calls; everything else is internal):

```python
class GameState:
    @classmethod
    def setup(cls, decks, agents, *, seed: int, rng: random.Random) -> GameState
    def clone(self) -> GameState
    def legal_actions(self, player_id: int) -> list[Action]
    def apply(self, player_id: int, action: Action) -> None  # mutates self
    def is_over(self) -> bool
    @property
    def is_draw(self) -> bool
    @property
    def winner_id(self) -> int | None
    @property
    def active_player_idx(self) -> int
    @property
    def priority_player_idx(self) -> int
    @property
    def step(self) -> Step  # or int constant
    @property
    def turn_number(self) -> int
    @property
    def players(self) -> list[Player]  # exposes hand/library/.../mana_pool
    @property
    def stack(self) -> list[StackItem]
```

Plus `Action` and `Player` proxy classes that look enough like
Python's to be drop-in. We do NOT expose every internal method
Python's GameState has — only the surface the search loop actually
calls.

### Decision 3 — Action class registry

The 10 Python `Action` subclasses become 10 Rust enum variants.
`apply` dispatches on the variant. `legal_actions` enumerates all
that are currently legal for the priority-holding player. Both must
match Python's emission order **exactly** (round-19 verified that
the bridge round-trips work for one Effect; this is the same idea
for Actions). Round 20+'s TDD slices target one Action type per
slice, with a parity test that runs the same legal_actions query on
both engines and asserts byte-identical lists.

### Decision 4 — Effect coverage strategy

228 Effect classes is too many to port one round at a time. Pareto:
the top 14 classes (≥10 cards each) cover 277 effect-emissions out
of ~700 total. The next 50 classes cover most of the remaining
emissions; the long-tail 161-singletons are individual cards.

**Phasing**:

1. **Top 14 first** — round 21-25, ~3 Effect variants per round
   (current pace = 1-3 Effect variants per round). After this,
   the most-frequent cards work end-to-end.
2. **Bespoke long-tail** — many bespoke effects are entire card
   behaviors that don't decompose into oracle-text recognizers
   (per memory `feedback_oracle_text_fidelity.md`). For parity
   purposes, the bespoke cards can either (a) be ported one-by-one
   as Rust dispatch arms, or (b) excluded from the parity deck
   pool initially. Recommend (b) for the first parity smokes:
   build a "core deck pool" that uses only the top-14 effects + a
   small set of vanilla creatures + lands. Pure-oracle cards. Add
   bespokes after parity is locked on the core pool.
3. **Long tail (161 singletons)** — only after parity is locked on
   smaller pools. Each singleton card may need its own Rust dispatch
   arm; that's not a TDD-slice problem, it's a card-by-card problem.

### Decision 5 — Determinism audit cadence

After every new Action type or Effect variant lands, **re-run
`scripts/parity_smoke.py`** to confirm no determinism regression. The
smoke script is the regression gate. Initially it fails at step 1
(Rust side is stub); the failure mode evolves from "stubs everywhere"
to "diverged at decision 47" to "all 1000 games match" as we make
progress. The diagnostic value is in the *first divergence index* — it
points exactly at the spot to fix.

## Phasing (rough — adjust as we learn)

| Phase | Goal | Rounds est. | Output |
|---|---|---|---|
| **Phase 0** ✓ | Engine primitives | rounds 1-19 (done) | 19 Effect variants, ~676 Rust tests |
| **Phase 1** ✓ (this round) | Discovery + scaffold | round 20 | RUST_PARITY_PLAN.md, parity_smoke.py |
| **Phase 2** | Externalize RNG + spec GameState API | round 21 | external-RNG threading on existing slices, PyO3 surface for setup/clone/is_over |
| **Phase 3** | Action types + legal_decisions enumerator | rounds 22-25 | 6 most-common Actions, legal_decisions parity tests on synthetic states |
| **Phase 4a** | Top-14 high-frequency Effects | rounds 26-30 | covers most card emissions |
| **Phase 4b** | Mid-frequency Effects (next ~50) | rounds 31-35 | covers most card-instances |
| **Phase 5** | Per-step trajectory diff on 1 game | round 36 | parity_smoke.py passes on 1 game |
| **Phase 6** | Scale to 1000 games | round 37+ | the goal |

Long-tail bespoke effects + sagas + planeswalkers + battles are
outside Phase 6 scope. The 1000-game parity smoke uses a
"core-effects-only" deck pool that excludes them.

## Risks, in priority order

1. **Bespoke effects (37 classes, 1 card each)** — these are entire
   card behaviors. Excluding them from the parity pool is the only
   tractable answer for this milestone. Re-include after.
2. **Targeting choice within an Action** — when a CastSpell with
   AnyCreature target has multiple legal targets, Python and Rust
   must pick the *same* one. Our Rust slices today pick "defender's
   first creature" deterministically (round 6 conv). Need to verify
   Python uses the same convention OR plumb an explicit choice
   callback through Rust to delegate to the agent.
3. **Layered continuous-effect cache** — Rust has no analog today.
   When we port anthems / pump UEOT / become-creature effects,
   missing layered logic = silent wrong answers. Layer 6 (lose all
   abilities) and Layer 7 (P/T) are the most common; Layer 1-5 are
   rarer.
4. **Combat damage assignment** — round 5 + 8 + 9 + 10 + 13 + 15
   in Rust covers the basics, but the Python combat code is 800+
   lines and includes nuances like "first-strike + double-strike
   interleaving with deathtouch lifelink trample reach skulk
   menace defender vigilance flying haste indestructible". Some
   may not be byte-identical yet. Flag as Phase 5 work.
5. **Stack timing on triggered abilities** — when an effect resolves
   AND triggers other abilities AND those triggers each have effects
   that trigger further: ordering is fragile. Round 9's ETB slice
   handles the simple case (single ETB); deeper trigger chains may
   need careful Rust-side replay tests.

## How parity_smoke.py works

See `scripts/parity_smoke.py` (added in this round). The TL;DR:

```
$ python scripts/parity_smoke.py --seed 42 --decks G_R_synthetic --n-games 1
[python] game 1: 420 decisions, p1 wins, trajectory_hash=abc123...
[rust]   game 1: NotImplementedError at setup (Rust GameState bridge not built yet)
PARITY: FAIL — first divergence at: setup
```

After Phase 2:
```
[rust]   game 1: NotImplementedError at decision 0 (legal_actions not implemented)
PARITY: FAIL — first divergence at: legal_actions(0)
```

After Phase 3:
```
[rust]   game 1: 420 decisions, p1 wins, trajectory_hash=abc123...
PARITY: PASS — game 1 (420 decisions match)
```

The divergence-index diagnostic is the value. We don't need 1000
games to find the next bug; we need 1 game to find the first one.

## What this plan is NOT

- Not committing to a timeline. Parity is the goal; cadence depends on
  what each round surfaces.
- Not freezing the architecture. If Phase 5 surfaces a determinism gap
  the structure can't accommodate, we revisit the plan.
- Not blocking other work. The Python engine + training pipeline
  continue to evolve in parallel; the Rust engine just chases. We may
  need to occasionally re-snap measurements (re-run
  `scripts/parity_discovery_*.py`) when the Python pool changes.
