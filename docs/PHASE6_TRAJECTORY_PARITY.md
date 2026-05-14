# Phase 6 — Full-game trajectory parity

This is the entry doc for the Phase 6 trajectory-parity workstream, the
follow-on to Phase 5's per-event ETB-trigger probes
(see `PHASE5_PARALLEL_AGENT_PLAYBOOK.md`). Phase 5 verified the
cross-engine bridge agrees on hand-rolled single-event probes; Phase 6
verifies the bridge agrees across **multi-turn real-game trajectories**
— opening hands, turn structure, zone movement, eventually combat.

## Seed scaffold (this slice)

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

All four trajectory-parity tests pass against today's `main`. The
existing Phase 5 gate (`tests/test_parity_smoke.py` +
`tests/test_cross_engine_etb_triggers.py`, 323 passing) remains green.

## Divergences surfaced

**None on the no-op turn-structure prefix.** A 60-card mirror-match
walks turn 1, the CLEANUP wrap, turn 2 UNTAP/UPKEEP/DRAW, and turn-2
land drops without surfacing any new cross-engine divergence beyond
those already pinned by Phase 5. This is itself a finding — every
plausible novel turn-structure divergence on a real-game-shaped state
turns out to already be either (a) parity-clean by virtue of the
existing CE3/CE4/CE5/CE8/CE10 closures, or (b) quietly co-erroring on
both sides. The bridge is more parity-clean than the Phase-5-only
test surface implied.

## Infrastructure gaps blocking Phase 6 progress

1. **No shared `setup_game` mirror.** Python's `mtg_bot.simulate.setup_game`
   runs a real opening-draw + (optional) London-mulligan loop using
   `state.rng`; Rust's `make_state` takes pre-built decklist arrays and
   shuffles internally. The seed wires draws via a side-channel because
   no `parity.trajectory.setup_matched_game(decks, seed, mulligans=...)`
   helper exists. Test 5 in the seed file is xfail-tagged on this gap.
2. **No mulligan parity.** The seed bypasses London mulligans entirely.
   Closing this requires both a shared setup helper AND a cross-engine
   mulligan agent that produces deterministic mulligan/bottom decisions
   on both sides.
3. **No combat-decision selector.** Phase 5's `combat_selector` family
   drives synthetic 7-card decks; nothing today drives a real-game
   combat trajectory (opening-hand creature + multi-turn land drops +
   attack with summoning-sick clear) end-to-end.
4. **Inconsistent action-dict vocabulary.** `_dict_to_python_action`
   uses `card_id` for `play_land`/`cast_spell` but `source_id` for
   `activate_ability`. Real-game trajectory tests building actions
   programmatically have to know this per-kind.

## Suggested next slice

Build `parity.trajectory` as a sibling module to `parity.cross_engine`,
shipping `setup_matched_game(decks, seed, mulligans=...)` as the first
primitive. Once that exists, port the seed tests to use it and extend
them through turns 3-6 (cast a Bears, attack with Bears at turn 4).
