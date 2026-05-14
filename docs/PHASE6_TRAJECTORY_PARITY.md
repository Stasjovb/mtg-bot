# Phase 6 — Full-game trajectory parity

This is the entry doc for the Phase 6 trajectory-parity workstream, the
follow-on to Phase 5's per-event ETB-trigger probes
(see `PHASE5_PARALLEL_AGENT_PLAYBOOK.md`). Phase 5 verified the
cross-engine bridge agrees on hand-rolled single-event probes; Phase 6
verifies the bridge agrees across **multi-turn real-game trajectories**
— opening hands, turn structure, zone movement, eventually combat.

## Seed scaffold (round-12)

The seed file is `tests/test_trajectory_parity.py`. It:

- Builds a 60-card mirror-match `DeckSpec` (24 Forest + 36 Grizzly Bears
  per side) using the existing `mtg_bot.parity.cross_engine.DeckSpec`
  with `shared_rng_seed=42` so both engines shuffle to the same
  permutation.
- Deals seven-card opening hands on both engines via a side-channel
  `_draw_opening_hand` helper that wraps Python's `turn.draw_card` and
  Rust's `state.draw_card` pymethod.
- Walks turn 1's eleven phases + the CLEANUP -> turn 2 UNTAP wrap using
  `cross_engine.advance_phase_python` (Phase 5's harness primitive) +
  `rust_state.advance_phase()`.
- Asserts byte-equal field views on every step plus strong invariants
  (life=20/20, hands=7/7 across turn 1, battlefield empty).
- Extends to turn-2 DRAW (hand 7 -> 8 on the new active player) and
  turn-2 PRECOMBAT_MAIN (play a Forest, assert two-permanent
  battlefield with correct controller_ids).

## Trajectory module + extended tests (round-13, this slice)

Closed by `feature/phase6-parity-trajectory-module`:

- **New module `mtg_bot.parity.trajectory`** ships
  `setup_matched_game(decks, seed, mulligans=False, opening_hand_size=7)`,
  the canonical `(decks, seed) -> (py_state, rust_state)` entrypoint that
  wraps `cross_engine.build_matched_states` plus the side-channel
  opening-draw mirror behind a single call. Closes infrastructure
  gap #1.
- **Test 5 in `tests/test_trajectory_parity.py`** drops its xfail and
  now positively asserts the helper exists, returns parity-clean
  states, and rejects `mulligans=True` until the follow-up slice lands.
- **New tests for turns 3-7**:
  - `test_play_land_each_turn_3_through_5_parity` — drives lands on
    turns 1, 2, 3, 4, 5; asserts per-step parity through five-deep bf.
  - `test_cast_creature_at_turn_5_parity` — earliest viable cast turn
    for the on-the-play side; tap two unsick Forests + cast Bears.
  - `test_attack_at_turn_7_parity` — declare Bears as attacker after
    summoning sickness clears at turn-7 UNTAP; empty declare_blockers.
  - `test_combat_damage_at_turn_7_parity` — Bears deals 2 unblocked,
    p1 life 20 -> 18 on both engines, post-damage SBA pass clean.
- **New unit-test module `tests/test_trajectory.py`** covers the
  `setup_matched_game` helper itself (seed-precedence, validation,
  mulligan-not-implemented gate, no-shuffle path).

All four extended trajectory tests pass without surfacing any new
cross-engine divergence; combat damage / declare-attackers / cast / land
plays are byte-equal across all 7 turns of the trajectory. Gate is
**346 passing** on Phase 5 + Phase 6 (was 332 + 1 xfail).

## Divergences surfaced

**None on the extended turn-1-through-7 trajectory.** A 60-card vanilla
mirror match drives:

- Opening hand setup (`setup_matched_game`).
- Turn 1 no-op walk + turn 2 land + turns 3-5 lands.
- Turn 5 cast Grizzly Bears (with two mana-ability activations).
- Turn 7 declare attackers + empty declare blockers + combat damage.

Every step's field-view compare is byte-equal. This extends round-12's
no-op-prefix finding: the cross-engine bridge is parity-clean across
the **real-game cast-and-attack flow** that Phase 5's selectors only
covered on synthetic 7-card decks. The CE3/CE4/CE5/CE8/CE10 closures
plus the existing `cast_bears_selector` / `combat_selector` per-step
discipline (mana-pool empty on phase exit, ETB-timestamp on every new
permanent, summoning-sick clear on UNTAP, post-damage SBA pass) compose
correctly under the real opening-prefix shape.

The Phase 5 surface is **stronger** than the Phase 6 trajectory tests
need it to be on the vanilla deck shape — Phase 5 already forced the
cast/attack/damage plumbing to converge. The trajectory tests' value is
thus in the **regression-pin** dimension: any future change to Rust's
`state_ops_setup` / `state_ops_steps` / `state_ops_combat` that breaks
the real-game flow will surface here even if the synthetic Phase 5
selectors keep passing.

## Mulligan parity (round-14, this slice)

Closed by `feature/phase6-mulligan-parity`:

- **`MulliganDeterministicAgent`** — frozen-dataclass agent that
  produces byte-identical mulligan/keep + bottom-pick decisions on
  both engines. Configured by `target_hand_size` (0..7); target=7
  is the default no-mulligan keep, target=N for N<7 means "mulligan
  exactly 7-N times then keep, bottom 7-N cards". Bottom strategy
  is `"first"` (positional, hand[:n]); the only currently-supported
  option, mirrors Rust's `bottom_cards_from_hand(n)` orientation.
- **`setup_matched_game(mulligans=True, mulligan_agent=..., mulligan_seed=...)`**
  — drops the `NotImplementedError`. Drives a deterministic London-
  mulligan loop on both engines using paired `random.Random(iter_seed)`
  instances per (player, mulls_taken) iteration. Each engine's
  in-mulligan Fisher-Yates consumes the same `_randbelow` sequence
  (MT determinism for identical seeds); post-shuffle libraries are
  bit-identical across engines.
- **Mulligan loop construction**: per-iteration uses Rust's
  `mulligan_to_n(7)` (shuffle+redraw, no bottom) plus a
  Python-side helper `_python_mulligan_iteration` that mirrors the
  same drain → shuffle → redraw shape consuming the shared rng.
  Final keep applies `bottom_cards_from_hand(n)` on Rust + the
  positional `_python_bottom_cards` on Python. Splitting shuffle
  from bottom mirrors Python's `simulate.setup_game` mulligan-loop
  shape; using `mulligan_atomic` would require progressively-larger
  bottom sets per intermediate iteration, which is meaningless
  because only the final iteration's bottom is preserved.
- **Test surface**: 5 new tests in `tests/test_trajectory_parity.py`
  — default-agent no-op keep, `target_hand_size=6` (one mull each
  side then walk turn 1), `target_hand_size=5` (two mulls each side),
  reproducibility (same seed → identical state), differentiation
  (different seed → different state). Plus 5 new defensive tests in
  `tests/test_trajectory.py` for the agent's validation surface.

## Divergences surfaced in round-14

Two real cross-engine quirks turned up while wiring this:

1. **Hand-drain order in mulligan**: Python's `simulate.setup_game`
   uses `p.hand.pop()` (LIFO — hand[6] returned first); Rust's
   `mulligan_atomic` / `mulligan_to_n` uses `hand.drain(..)` (FIFO —
   hand[0] returned first). Pre-shuffle library tail order would
   diverge if the parity helper used Python's LIFO drain. The
   round-14 helper uses FIFO to match Rust. The Python production
   `setup_game` is unchanged (its LIFO drain is fine because Python
   alone shuffles right after — only the cross-engine harness needs
   the orientation match).
2. **Per-instance flag reset on bottom**: Rust's
   `bottom_cards_from_hand` resets `tapped`, `summoning_sick`,
   `damage`, `counters`, `attached_to`, `exiled_with_source` on each
   bottomed object. Python's bottom step (in `simulate.setup_game`)
   does NOT — but on Python a hand card carries the GameObject default
   `summoning_sick=True`, which would persist into the library and
   surface as a per-object field divergence on the bottomed cards.
   The round-14 helper's `_python_bottom_cards` mirrors Rust's reset
   to keep the post-bottom field views byte-equal. The Python
   production `setup_game` is again unchanged.

Both quirks are *parity-harness specific*: production Python code
is correct on its own terms; the harness must mirror Rust's exact
choices to produce byte-equal field views, even where Python and
Rust each independently produce semantically-equivalent results.

## Infrastructure gaps blocking Phase 6 progress

1. ~~**No shared `setup_game` mirror.**~~ **CLOSED** by
   `feature/phase6-parity-trajectory-module` —
   `mtg_bot.parity.trajectory.setup_matched_game` is now the
   single entrypoint.
2. ~~**No mulligan parity.**~~ **CLOSED** by
   `feature/phase6-mulligan-parity` (round-14, this slice). See
   "Mulligan parity (round-14, this slice)" section above for the
   full ship summary. Residual API gaps that would unblock richer
   mulligan strategies (out of scope for this slice):
   - **Non-positional bottom strategies** would require either Rust
     hand-reordering (no API today — would need
     `reorder_hand(player_id, ids)`) or extending
     `bottom_cards_from_hand` to take explicit ids rather than count.
     Currently only `bottom_strategy="first"` is supported because
     it lines up trivially with Rust's positional default.
   - **State-conditional mulligan agents** (e.g., the heuristic
     `Agent.choose_mulligan` from `mtg_bot.mulligan`) need a way to
     read the post-shuffle hand on Rust before deciding. Today's
     deterministic agent sidesteps this by deciding solely on
     `mulls_taken`. A Rust-side `peek_hand(player_id) -> list[dict]`
     pymethod (or extending the existing `hand_snapshot`) plus a
     bridge that drives both engines with a single Python decision
     would close this. The round-14 deterministic agent is enough
     for trajectory tests; state-conditional agents are a follow-up
     when production-shape mulligan probes are needed.
3. **No real-game combat-decision selector.** Phase 5's
   `combat_selector` family drives synthetic 7-card decks; the
   round-13 trajectory tests drive real-game-sized combat manually
   (per-test inline declare/block scripts). Promoting the inline
   pattern into a `parity.trajectory.combat_selector` (selector that
   reads the active player's bf and emits attacker/blocker dicts
   automatically) would let trajectory tests share one combat
   driver instead of each test re-inlining the script. Not blocking
   per se, but increasingly an ergonomics tax as the trajectory
   suite grows.
4. ~~**Inconsistent action-dict vocabulary.**~~ **CLOSED** by
   `feature/phase6-action-dict-vocab` (round-15, this slice). See
   "Action-dict vocabulary normalization (round-15, this slice)"
   section below for the full ship summary.

## Action-dict vocabulary normalization (round-15, this slice)

Closed by `feature/phase6-action-dict-vocab`:

The action-dict id-key vocabulary is per-kind asymmetric — `card_id`
for `play_land` / `cast_spell` (and `turn_face_up` /
`unlock_room_half`); `source_id` for `activate_ability`;
`spacecraft_id` for `activate_station`. **The asymmetry is consistent
on both Python AND Rust** — Python's dataclass field names
(`PlayLand.card_id`, `ActivateAbility.source_id`, ...) match Rust's
enum variant fields (`Action::PlayLand { card_id }`,
`Action::ActivateAbility { source_id }`, ...). This is intentional
and captures real semantic distinction:

- `card_id` reads naturally for "the card in hand I'm playing /
  casting / flipping / unlocking".
- `source_id` reads naturally for "the permanent on the battlefield
  whose ability is firing" — could be a creature, an artifact, an
  enchantment, a land, never just "a card".

**Decision rationale: Option C (dual-honor + canonical builder
helper).** The brief offered three options:

- Option A (standardize on `card_id` everywhere): would force a
  Python dataclass field rename (`ActivateAbility.source_id` →
  `card_id`) AND a Rust enum field rename, with cascading
  search-loop + bridge changes. Loses the "permanent vs card"
  semantic. Big blast radius.
- Option B (standardize on `source_id` everywhere): same blast
  radius, opposite direction. Loses the "card I'm playing"
  semantic.
- **Option C (dual-honor + canonical builder)** — picked. The
  asymmetry is *correct* on both engines; the only real pain is
  programmatic builders memorizing the per-kind shape. A canonical
  builder helper + dual-honor on the Python bridge solves the
  ergonomic gap without touching either engine's data model. Zero
  Rust-side coupling cost (avoids conflict with parallel Rust
  slices).

Slice contents:

- **`_CANONICAL_ACTION_ID_KEY` table** in
  `mtg_bot.parity.cross_engine` — single source of truth for the
  per-kind canonical id-key vocabulary. Documents the mapping
  (play_land/cast_spell/turn_face_up/unlock_room_half →
  `card_id`; activate_ability → `source_id`; activate_station →
  `spacecraft_id`).
- **`_canonical_action_dict(kind, **kwargs)`** — programmatic-builder
  helper that accepts the GameObject id under the friendly alias
  `id` and routes it to the kind's canonical key. Validates kind
  membership; rejects no-id kinds passing `id`; rejects id-required
  kinds omitting `id`. Other kwargs pass through (e.g., kicker /
  warp / impending flags on cast_spell).
- **`_resolve_id_with_alias(action_dict, kind)`** — bridge-side
  resolver that reads the primary id honoring both the canonical
  key AND the cross-vocabulary alias (`source_id` on
  play_land/cast_spell, `card_id` on activate_ability).
- **`_dict_to_python_action`** updated to use
  `_resolve_id_with_alias` on play_land / cast_spell /
  activate_ability. Soft-deprecation transition aid: hand-rolled
  Python-side dicts that pick the "wrong" key still resolve. Rust
  stays strict (canonical key only) — documented in the function
  docstring. Always prefer `_canonical_action_dict` for dicts that
  cross both engines.
- **Test surface** (15 new tests):
  - `tests/test_parity_smoke.py` — 13 tests covering the builder's
    happy paths (play_land, cast_spell, activate_ability, no-id
    kinds), validation (unknown kinds, bad id pairings),
    dual-honor (alias acceptance for both directions,
    canonical-takes-precedence when both present, missing-id
    KeyError contract preserved), and a drift-detection test that
    pins the per-kind canonical-key table.
  - `tests/test_trajectory_parity.py` — 2 tests:
    - `test_activate_ability_trajectory_via_canonical_builder` —
      end-to-end real-game trajectory using
      `_canonical_action_dict` for every action (lands across
      turns 1/3/5, two Forest mana activations, cast Bears). Pins
      cross-engine parity on the builder-emitted dicts.
    - `test_activate_ability_trajectory_alias_dict_python_only` —
      Python-bridge-only contract: an alias-keyed activate_ability
      dict (`card_id` instead of `source_id`) still taps the
      Forest on the Python side. Documented to NOT cross the Rust
      boundary.

Gate: **379 passing** (was 364; +15 net). No divergences surfaced.

## Divergences surfaced in round-15

**None.** The activate_ability trajectory test runs cleanly across
the full real-game prefix (opening hand, three land plays, two
mana activations, cast Bears) with byte-equal field views on every
step. This extends the round-13 finding: the cross-engine bridge is
parity-clean on the activate_ability path the same way it is on
play_land / cast_spell / declare_attackers.

The trajectory test's value is two-fold:

1. **Builder regression-pin** — any future change to
   `_canonical_action_dict`'s per-kind routing (e.g., emitting
   `card_id` for `activate_ability` by mistake) would surface
   immediately as a Rust-side parse error since Rust is strict on
   the canonical key.
2. **Activate_ability trajectory regression-pin** — any future
   Rust-side change to the mana-ability primitive that breaks the
   Forest tap-for-mana flow surfaces here.

## Suggested next slice

Gap #1 + gap #2 + gap #4 are closed. The natural next slice is
gap #3 (the trajectory-side combat selector): promote the inline
declare/block scripts from the round-13/14/15 trajectory tests
into a `parity.trajectory.combat_selector` that reads the active
player's bf and emits attacker/blocker dicts automatically. Test
surface: re-write `test_attack_at_turn_7_parity` and
`test_combat_damage_at_turn_7_parity` to use the selector, then
add 1-2 new tests with multiple attackers / blockers to surface
any combat-step bookkeeping bugs that the inline-script versions
don't exercise (interleaved declare order, vigilance,
first-strike).

The Rust API gaps documented under gap #2's residuals
(non-positional bottom, state-conditional mulligan agents) are
candidate Rust slices for future rounds when production-shape
mulligan probes are needed.
