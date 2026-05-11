# `tests_rust/` — TDD harness for the Rust engine port

Purpose: drive the Rust engine port (`mtg_bot_engine` PyO3 extension)
test-first. Every Rust feature lands as a red→green→commit cycle:

1. Pick a behavior currently exercised by some test in `tests/` (or a
   small primitive needed for one).
2. Port the test into `tests_rust/`, target the Rust API instead of
   `mtg_bot.*` Python API. Watch it fail (RED).
3. Implement the underlying Rust functionality in `rust/src/state.rs`
   (or wherever it belongs). Re-run. Watch it pass (GREEN).
4. Commit on a feature branch. Move to the next test.

This directory is skipped wholesale if `mtg_bot_engine` isn't built
(see `conftest.py`). Run `maturin develop --release -m rust/Cargo.toml`
once and these tests run as part of the default `pytest` invocation.

## Layout

`tests_rust/` mirrors `tests/`. When porting a test from
`tests/test_clone.py`, the new file goes at `tests_rust/test_clone.py`
with the same test names where reasonable. Side-by-side filenames
make `git diff tests/test_X.py tests_rust/test_X.py` a useful
parity check.

## Conventions

- **Use the `engine` / `synthetic_state` / `empty_registry` fixtures**
  from `conftest.py` rather than re-importing in every test.
- **Don't re-test what `tests/test_rust_card_bridge.py` and
  `tests/test_rust_engine_smoke.py` already cover.** Those live in
  `tests/` because they predate the TDD harness; new feature tests
  go in `tests_rust/`.
- **One behavior per test.** TDD discipline — small enough that a
  failing test points at exactly one missing piece of Rust.
- **Document the port in the file's module docstring.** Reference
  the Python test it's based on (e.g. "Ported from `tests/test_clone.py`,
  shrunk to the engine-level subset").

## Out of scope

The Python test suite has 391 files (~7860 tests). Many are not
relevant to the Rust engine port and won't be ported:

- **NN / training / data-gen** (`tests/training/*`, `tests/test_nn_*`,
  most of `tests/search/*`) — Rust crate explicitly excludes these.
- **UI / Flask / vitest** (`tests/training_ui/*`, `tests/test_app*`,
  `tests-js/*`) — pure web layer.
- **CLI / runs DB / orchestration** (`tests/cli/*`,
  `tests/test_*_orchestration*`) — operator-facing, runs in Python.
- **Distributed / SSH / shard plumbing** — same.

The ports target engine-only files: `tests/test_clone.py`,
`tests/test_combat.py`, `tests/test_actions.py`, `tests/test_legal.py`,
`tests/test_counters.py`, the per-card behavior tests
(`tests/test_<card_name>.py`), etc. A precise inventory is built
incrementally as ports happen — don't try to predict the whole
boundary up front.

## Porting status

Tracked in this README so a glance at the file shows where the
port is. Append a row when you start a port; flip to `green` when
the test lands in a commit.

| ported test                       | source                  | status | branch / commit            |
|-----------------------------------|-------------------------|--------|----------------------------|
| tests_rust/test_tap.py            | tests/test_combat.py + game.py  | green  | feature/rust-tdd-tap       |
| tests_rust/test_zones.py          | tests/test_actions.py + game.py | green  | feature/rust-tdd-zones     |
| tests_rust/test_life.py           | tests/test_combat.py + game.py  | green  | feature/rust-tdd-life      |
| tests_rust/test_mana.py           | tests/test_mana.py + game.py                | green  | feature/rust-tdd-mana      |
| tests_rust/test_counters.py       | tests/test_counters.py + game.py            | green  | feature/rust-tdd-counters  |
| tests_rust/test_steps.py          | tests/test_beginning_of_upkeep.py + turn.py | green  | feature/rust-tdd-steps     |
| rust(bridge-ext): P/T + mana_produced | tests/test_rust_card_bridge.py + tests/test_rust_bridge_parity.py | green  | feature/rust-bridge-pt-mana |
| tests_rust/test_damage.py         | tests/test_combat.py + game.py              | green  | feature/rust-tdd-damage    |
| tests_rust/test_winloss.py        | tests/test_game.py + game.py                | green  | feature/rust-tdd-winloss   |
| tests_rust/test_cast.py           | tests/test_actions.py + game.py             | green  | feature/rust-tdd-cast      |
| tests_rust/test_library.py        | tests/test_actions.py + game.py             | green  | feature/rust-tdd-library   |
| tests_rust/test_priority.py       | tests/test_game.py + turn.py                | green  | feature/rust-tdd-priority  |
| tests_rust/test_combat.py         | tests/test_combat.py + combat.py            | green  | feature/rust-tdd-combat    |
| tests_rust/test_stack.py          | tests/test_game.py + game.py                | green  | feature/rust-tdd-stack     |
| tests_rust/test_sba.py            | tests/test_state_based_actions.py + game.py | green  | feature/rust-tdd-sba       |
| rust(cast-rewire): card_types-based detector | tests_rust/test_cast.py rewire              | green  | feature/rust-tdd-cast-rewire |
| tests_rust/test_cleanup.py        | tests/test_actions.py + turn.py             | green  | feature/rust-tdd-cleanup   |
| tests_rust/test_resolve.py        | tests/test_combat.py + game.py              | green  | feature/rust-tdd-resolve   |
| rust(combat-vigilance): keyword skip-tap | tests_rust/test_combat.py extend             | green  | feature/rust-tdd-vigilance |
| tests_rust/test_counterspell.py   | tests/test_counter_cancellation.py + game.py | green  | feature/rust-tdd-counterspell |
| rust(resolve-postmove): card_types-driven destination | tests_rust/test_resolve.py extend            | green  | feature/rust-tdd-postresolve |
| rust(combat-keywords): deathtouch+lifelink | tests_rust/test_combat.py extend            | green  | feature/rust-tdd-deathtouch-lifelink |
| rust(resolve-effects): DrawCards+GainLife dispatch | tests_rust/test_resolve.py extend           | green  | feature/rust-tdd-resolve-effects |
| rust(cleanup-compose): hand-size+damage-clear | tests_rust/test_cleanup.py extend           | green  | feature/rust-tdd-cleanup-compose |
| rust(combat-keywords): trample+first-strike | tests_rust/test_combat.py extend            | green  | feature/rust-tdd-trample-firststrike |
| rust(etb-triggers): on-resolve dispatch | tests_rust/test_resolve.py extend           | green  | feature/rust-tdd-etb |
| rust(priority-round-complete): pop+priority-reset | tests_rust/test_priority.py extend          | green  | feature/rust-tdd-priority-pass-resolve |
| rust(combat-keyword): haste | tests_rust/test_combat.py extend           | green  | feature/rust-tdd-haste |
| rust(resolve-effects-r10): ReturnToHand+Mill dispatch | tests_rust/test_resolve.py extend           | green  | feature/rust-tdd-resolve-bounce-mill |
| tests_rust/test_deck.py           | tests/_test_decks.py + game.py              | green  | feature/rust-tdd-deck |
| rust(combat-keywords): flying+reach | tests_rust/test_combat.py extend           | green  | feature/rust-tdd-flying-reach |
| rust(resolve-effects-r11): ExileTarget dispatch | tests_rust/test_resolve.py extend           | green  | feature/rust-tdd-exile |
| tests_rust/test_mulligan.py       | tests/test_actions.py + game.py             | green  | feature/rust-tdd-mulligan |
| rust(combat-keywords): menace+defender | tests_rust/test_combat.py extend           | green  | feature/rust-tdd-menace-defender |
| rust(resolve-effects-r12): TapTarget dispatch | tests_rust/test_resolve.py extend           | green  | feature/rust-tdd-tap-target |
| rust(sba-zero-toughness): CR 704.5f | tests_rust/test_sba.py extend           | green  | feature/rust-tdd-sba-zero-toughness |
| rust(combat-keyword): double-strike | tests_rust/test_combat.py extend           | green  | feature/rust-tdd-double-strike |
| rust(resolve-effects-r13): UntapTarget dispatch | tests_rust/test_resolve.py extend           | green  | feature/rust-tdd-untap-target |
| rust(sba-indestructible): CR 702.12 | tests_rust/test_sba.py extend           | green  | feature/rust-tdd-indestructible |
| rust(combat-keyword): skulk | tests_rust/test_combat.py extend | green | feature/rust-tdd-skulk |
| rust(resolve-effects-r14): Sacrifice dispatch | tests_rust/test_resolve.py extend           | green  | feature/rust-tdd-sacrifice |
| rust(zones-exile-aware): exile in find/move | tests_rust/test_zones.py extend | green | feature/rust-tdd-exile-aware-zones |
| rust(library-search): search_library_for_card | tests_rust/test_library.py extend | green | feature/rust-tdd-search-library |
| rust(steps-untap-summoning): clear sickness at untap | tests_rust/test_steps.py extend | green | feature/rust-tdd-untap-summoning |
| rust(damage-to-player): direct life mutation | tests_rust/test_damage.py extend | green | feature/rust-tdd-damage-to-player |
| rust(life-cost): pay_life_cost (CR 118.4) | tests_rust/test_life.py extend | green | feature/rust-tdd-life-cost |
| rust(combat-keywords-r15): trample+deathtouch (CR 702.19c) | tests_rust/test_combat.py extend | green | feature/rust-tdd-trample-deathtouch |
| rust(library-search-by-type): search_library_for_first_of_type | tests_rust/test_library.py extend | green | feature/rust-tdd-search-by-type |
| rust(resolve-effects-r15): AddCounters+DiscardCard dispatch | tests_rust/test_resolve.py extend | green | feature/rust-tdd-resolve-counters-discard |
| rust(sba-loop): apply_sbas_until_quiescent (CR 704.3) | tests_rust/test_sba.py extend | green | feature/rust-tdd-sba-loop |
| rust(mana-pay-cost): pay_mana_cost (CR 202.2) | tests_rust/test_mana.py extend | green | feature/rust-tdd-mana-pay-cost |
| rust(resolve-effects-r16): ScryN dispatch (CR 701.18) | tests_rust/test_resolve.py extend | green | feature/rust-tdd-resolve-scry |
| rust(stack-resolve-loop): process_stack_until_empty | tests_rust/test_stack.py extend | green | feature/rust-tdd-stack-resolve-loop |
| rust(sba-counter-toughness): SBA uses counter-modified effective toughness (CR 704.5f/g) | tests_rust/test_sba.py extend | green | feature/rust-tdd-counters-cancel |
| rust(library-search-and-shuffle): tutor-style search + always shuffle (CR 701.19) | tests_rust/test_library.py extend | green | feature/rust-tdd-search-and-shuffle |
| rust(mulligan-london): mulligan_to_n parameterized hand size (CR 103.4) | tests_rust/test_mulligan.py extend | green | feature/rust-tdd-mulligan-london |
| rust(cleanup-end-turn-wrap): end_turn_and_start_next composition primitive | tests_rust/test_cleanup.py extend | green | feature/rust-tdd-end-of-turn-wrap |
| rust(zones-reanimate): move_object_from_graveyard_to_battlefield primitive (CR 302.1 / 400.7) | tests_rust/test_zones.py extend | green | feature/rust-tdd-graveyard-reanimation |
| rust(counters-double): double_counters_for_player primitive (Doubling Season-style) | tests_rust/test_counters.py extend | green | feature/rust-tdd-counter-doubles |
| rust(resolve-effects-r17): DestroyTarget + DamageEachOpponent dispatch | tests_rust/test_resolve.py extend | green | feature/rust-tdd-resolve-destroy-aoe |
| rust(mana-empty-all): empty_all_mana_pools (CR 106.4) | tests_rust/test_mana.py extend | green | feature/rust-tdd-mana-empty-phase |
| rust(resolve-effects-r18): DamageEachCreature dispatch (CR 701.4) | tests_rust/test_resolve.py extend | green | feature/rust-tdd-resolve-damage-creatures |
| rust(zones-regrowth): move_object_from_graveyard_to_hand primitive (CR 400.7) | tests_rust/test_zones.py extend | green | feature/rust-tdd-graveyard-to-hand |
| rust(mulligan-bottoming): bottom_cards_from_hand primitive (CR 103.4) | tests_rust/test_mulligan.py extend | green | feature/rust-tdd-mulligan-bottoming |
| tests_rust/test_choices.py        | apply_effect duplication in cards.rs        | green  | feature/rust-tdd-choices |
| rust(resolve-effects-r19): CreateToken dispatch (CR 701.6) | tests_rust/test_resolve.py extend | green  | feature/rust-tdd-resolve-create-token |
| rust(combat-keyword): flash (CR 702.8) | tests_rust/test_cast.py extend | green  | feature/rust-tdd-flash |
| rust(counters-proliferate): proliferate primitive (CR 701.25) | tests_rust/test_counters.py extend | green  | feature/rust-tdd-counters-proliferate |
| rust(library-mill-target-player): mill_target_player primitive | tests_rust/test_library.py extend | green  | feature/rust-tdd-library-mill-target-player |
| rust(choices-extend): graveyard / keyword / tapped selectors | tests_rust/test_choices.py extend | green  | feature/rust-tdd-choices-extend |
| rust(bridge-outcome): is_over / is_draw / winner_id getters | tests_rust/test_winloss.py extend | green  | feature/rust-bridge-outcome |
| rust(bridge-zone-snapshots): hand/library/graveyard/exile/battlefield/mana_pool getters | tests_rust/test_snapshot.py | green  | feature/rust-bridge-zone-snapshots |
| rust(bridge-step-getter): step getter returns Python Step.name | tests_rust/test_steps.py extend | green  | feature/rust-bridge-step-getter |
| rust(bridge-priority-active-aliases): active_player_idx + priority_player_idx Python-property getters | tests_rust/test_priority.py extend | green  | feature/rust-bridge-priority-active-aliases |
| rust(bridge-stack-snapshot): stack_snapshot getter | tests_rust/test_stack.py extend | green  | feature/rust-bridge-stack-snapshot |
| rust(action-foundation): Action enum + apply_action(PassPriority) | tests_rust/test_actions.py | green  | feature/rust-action-foundation |
| rust(bridge-fingerprint): fingerprint() matching parity_smoke.py:hash_state | tests_rust/test_fingerprint.py | green  | feature/rust-bridge-fingerprint |
| rust(state-from-decklists): make_state pyfunction | tests_rust/test_setup.py | green  | feature/rust-state-from-decklists |
| rust(action-play-land): Action::PlayLand variant | tests_rust/test_actions.py extend | green  | feature/rust-action-play-land |
| rust(effect-add-mana-to-pool): Effect::AddManaToPool dispatch | tests_rust/test_resolve.py extend | green  | feature/rust-effect-add-mana-to-pool |
| rust(action-declare-attackers): Action::DeclareAttackers variant | tests_rust/test_actions.py extend | green  | feature/rust-action-declare-attackers |
| rust(effect-search-library-for-basic-land-tapped): basic land search + tapped enter | tests_rust/test_resolve.py extend | green  | feature/rust-effect-search-library-for-basic-land-tapped |
| rust(action-declare-blockers): Action::DeclareBlockers variant | tests_rust/test_actions.py extend | green  | feature/rust-action-declare-blockers |
| rust(action-activate-ability): Action::ActivateAbility variant | tests_rust/test_actions.py extend | green  | feature/rust-action-activate-ability |
| rust(effect-put-plus-one-counter-on-self): self-target counter (CR 122.6) | tests_rust/test_resolve.py extend | green  | feature/rust-effect-put-plus-one-counter-on-self |
| rust(setup-with-shuffle): optional seeded library shuffle in make_state | tests_rust/test_setup.py extend | green  | feature/rust-setup-with-shuffle |
| rust(effect-surveil): Surveil N dispatch (CR 701.42) | tests_rust/test_resolve.py extend | green  | feature/rust-effect-surveil |
| rust(legal-decisions-skeleton): legal_decisions(player_id) — PassPriority + PlayLand | tests_rust/test_legal.py | green  | feature/rust-legal-decisions-skeleton |
| rust(action-cast-spell): Action::CastSpell + 5 flags (semantics deferred) | tests_rust/test_actions.py extend | green  | feature/rust-action-cast-spell |
| rust(legal-decisions-cast-spell): legal_decisions emits CastSpell | tests_rust/test_legal.py extend | green  | feature/rust-legal-decisions-cast-spell |
| rust(effect-counter-target-spell): CounterTargetSpell dispatch (CR 701.5) | tests_rust/test_resolve.py extend | green  | feature/rust-effect-counter-target-spell |
| rust(effect-return-creature-from-graveyard): reanimate dispatch (CR 400.7) | tests_rust/test_resolve.py extend | green  | feature/rust-effect-return-creature-from-graveyard |
| rust(legal-decisions-declare-attackers): emit DeclareAttackers during combat | tests_rust/test_legal.py extend | green  | feature/rust-legal-decisions-declare-attackers |
| rust(action-turn-face-up): Action::TurnFaceUp variant (dispatch stubbed) | tests_rust/test_actions.py extend | green  | feature/rust-action-turn-face-up |
| rust(effect-discard-self): "you discard" dispatch (CR 701.8) | tests_rust/test_resolve.py extend | green  | feature/rust-effect-discard-self |
| rust(action-unlock-room-half): Action::UnlockRoomHalf variant (dispatch stubbed) | tests_rust/test_actions.py extend | green  | feature/rust-action-unlock-room-half |
| rust(legal-decisions-activate-ability): emit ActivateAbility for mana producers | tests_rust/test_legal.py extend | green  | feature/rust-legal-decisions-activate-ability |
| rust(action-activate-station): Action::ActivateStation variant (dispatch stubbed) | tests_rust/test_actions.py extend | green  | feature/rust-action-activate-station |
| rust(effect-each-opponent-loses-life): life-loss (CR 118.4) | tests_rust/test_resolve.py extend | green  | feature/rust-effect-each-opponent-loses-life |
| rust(legal-decisions-declare-blockers): emit DeclareBlockers during defender's combat | tests_rust/test_legal.py extend | green  | feature/rust-legal-decisions-declare-blockers |
| rust(effect-destroy-all-creatures): Wrath of God (CR 701.7 AOE) | tests_rust/test_resolve.py extend | green  | feature/rust-effect-destroy-all-creatures |
| rust(effect-destroy-target-non-land-permanent): non-land destroy (CR 701.7) | tests_rust/test_resolve.py extend | green  | feature/rust-effect-destroy-target-non-land-permanent |
| rust(activate-ability-mana-primitive): flip ActivateAbility stub to real (mana abilities) | tests_rust/test_actions.py extend | green  | feature/rust-activate-ability-mana-primitive |
| rust(effect-deal-damage-any-target): Lightning Bolt-style any-target damage (CR 701.4) | tests_rust/test_resolve.py extend | green  | feature/rust-effect-deal-damage-any-target |
| rust(effect-lose-life): controller loses life (CR 118.4) | tests_rust/test_resolve.py extend | green  | feature/rust-effect-lose-life |
| rust(effect-target-opponent-loses-life): targeted opponent life-loss (CR 118.4) | tests_rust/test_resolve.py extend | green  | feature/rust-effect-target-opponent-loses-life |
| rust(effect-mill-target-player): targeted mill (CR 701.13b) | tests_rust/test_resolve.py extend | green  | feature/rust-effect-mill-target-player |
| rust(effect-each-opponent-discards): each-opponent discard (CR 701.8) | tests_rust/test_resolve.py extend | green  | feature/rust-effect-each-opponent-discards |
| rust(effect-destroy-target-artifact): artifact-filter destroy (CR 701.7) | tests_rust/test_resolve.py extend | green  | feature/rust-effect-destroy-target-artifact |
| rust(effect-destroy-target-land): land-filter destroy (CR 701.7) | tests_rust/test_resolve.py extend | green  | feature/rust-effect-destroy-target-land |
| rust(gap-g6-activate-ability-summoning-sick): CR 302.1 gate in apply_action + legal_decisions | tests_rust/test_tap.py + test_legal.py extend | green  | feature/rust-gap-g6-activate-ability-summoning-sick |
| rust(gap-g14-advance-phase-auto-draw): CR 504.1 auto-draw on PHASE_DRAW entry with CR 103.7c first-turn skip | tests_rust/test_steps.py extend | green  | feature/rust-gap-g14-advance-phase-auto-draw |
| rust(gap-g10+g11): empty-library draw flags player, `apply_sbas` locks loss via sticky `has_lost` (CR 704.5b, CR 104.2) | tests_rust/test_library.py + test_winloss.py invert + extend | green  | feature/rust-gap-g10-draw-empty-deckout |
| rust(gap-g1g2-advance-phase-composition): CR 106.4 mana-empty on every phase exit + CR 514.1/514.2 cleanup-step on PHASE_CLEANUP entry | tests_rust/test_steps.py + test_cleanup.py + test_mana.py extend | green  | feature/rust-gap-g1g2-advance-phase-composition |
| rust(gap-g23-mulligan-cap): per-player `mulligan_count` field; `mulligan` / `mulligan_to_n` raise after 7 calls (CR 103.4 / Python `max_mulligans=7`) | tests_rust/test_mulligan.py extend | green  | feature/rust-gap-g23-mulligan-cap |
| rust(gap-g21g22-london-mulligan): atomic `mulligan_atomic(p, seed, bottom_card_ids)` folds shuffle + redraw-7 + bottom-N into one transaction (CR 103.4 London) | tests_rust/test_mulligan.py extend | green  | feature/rust-gap-g21g22-london-mulligan |
| rust(gap-g3+g4+g15-priority-composition-layer): `consecutive_passes` counter + `complete_step_via_priority_round` composer + CR 117.1a/1c/4 priority resets in advance_phase/cast_creature/apply_action | tests_rust/test_priority.py invert + extend, tests_rust/test_stack.py + test_steps.py extend | green  | feature/rust-priority-composition-layer |
| rust(decision-callback-surveil): G20 closure — `pending_decisions` queue + `submit_surveil_decision` dispatcher + `auto_resolve_pending_decisions` + `resolve_top_of_stack_pause`; Surveil arm short-circuits to a `PendingDecision::SurveilChoice` (CR 701.43) | tests_rust/test_pending_decisions.py | green  | feature/rust-decision-callback-surveil |
| rust(ueot-framework): per-object `UeotModifier` Vec on `GameObject`; `Effect::PumpSelfUntilEOT` arm; CR 514.3 cleanup-step expiration via `cleanup_step_for_active_player` + `advance_phase`; closes G7. `effective_power` / `effective_toughness` / `has_keyword` getters fold UEOT modifiers into combat + SBA. | tests_rust/test_ueot.py (new) + test_combat.py + test_cleanup.py extend | green  | feature/rust-ueot-framework |
| rust(ce1-summoning-sick-default): align `make_state` / `set_library_for_player` to Python's universal `summoning_sick=true` default; new `clear_summoning_sick_for_player` pymethod for test fixtures. Closes CE1 (r27 cross-engine divergence). Pinned digest `a1193453edec` → `411d5b757c22`. | tests_rust/test_setup.py + tests_rust/test_legal.py + tests/test_parity_smoke.py extend | green  | feature/rust-ce1-summoning-sick-default |
| rust(effect-pump-target-creature-ueot): `Effect::PumpTargetCreatureUntilEOT` — first-creature-on-source-controller's-battlefield pump via the r27 UeotModifier framework. Giant-Growth-shape spells (26 EoE cards, highest-frequency Python class not yet in Rust per r27 measurement). | tests_rust/test_ueot.py extend | green  | feature/rust-effect-pump-target-creature-ueot |

| rust(effect-sequence): Effect::Sequence { effects: Vec<Effect> } combinator with recursive apply — Python Sequence(effects=...) (54 EoE cards, highest-freq Python class). Nestable. | tests_rust/test_resolve.py extend | green  | feature/rust-effect-sequence |

| rust(effect-pump-creatures-you-control-ueot): Effect::PumpCreaturesYouControlUntilEOT — iterates source-controller's bf, pumps every creature via UeotModifier::PowerToughnessBonus (6 EoE anthem-shape cards). | tests_rust/test_ueot.py extend | green  | feature/rust-effect-pump-creatures-you-control-ueot |

| rust(effect-return-creature-gy-to-hand): Effect::ReturnCreatureFromYourGraveyardToHand — mirror of the existing graveyard-to-bf arm with destination=ZONE_HAND (3 EoE cards). | tests_rust/test_resolve.py extend | green  | feature/rust-effect-return-creature-graveyard-to-hand |

| rust(effect-plus1-each-creature): Effect::PutPlusOneCounterOnEachCreatureYouControl — anthem-shape per-creature +1/+1 counter add for source's controller (3 EoE cards, Atmospheric Greenhouse). | tests_rust/test_counters.py extend | green  | feature/rust-effect-plus1-each-creature |

| rust(effect-plus1-target-creature-you-control): Effect::PutPlusOneCounterOnCreatureYouControl — Rayblade-Trooper-shape single-target +1/+1 counter add (3 EoE cards). | tests_rust/test_counters.py extend | green  | feature/rust-effect-plus1-target-creature-you-control |

| rust(effect-add-n-mana-chosen-color): Effect::AddNManaOfChosenColor — Lotus-Field-shape mint-N-of-one-color with first-slice deterministic options[0] pick (4 EoE cards). | tests_rust/test_mana.py extend | green  | feature/rust-effect-add-n-mana-chosen-color |

| rust(effect-search-library-for-card): Effect::SearchLibraryForCard — generalized tutor with filter_name dispatch (basic_land, basic_X, creature_small, artifact). Deferred: Legendary/subtype filters (no Rust supertypes/subtypes). 9 EoE cards. | tests_rust/test_library.py extend | green  | feature/rust-effect-search-library-for-card |

| rust(effect-pump-creatures-opponents-control-ueot): Effect::PumpCreaturesOpponentsControlUntilEOT — debuff-anthem mirror of PumpCreaturesYouControlUntilEOT, hits opponent's bf creatures (2 EoE cards). | tests_rust/test_ueot.py extend | green  | feature/rust-effect-pump-creatures-opponents-control-ueot |

| rust(effect-put-card-from-gy-bottom-library): Effect::PutCardFromGraveyardOnBottomOfLibrary — Chrome-Companion-shape graveyard-to-library-bottom move (2 EoE cards). | tests_rust/test_zones.py extend | green  | feature/rust-effect-put-card-from-gy-bottom-library |

| rust(effect-move-self-counters): Effect::MoveSelfCountersToTargetCreatureYouControl — Dockworker-Drone-shape counter transfer (2 EoE cards). | tests_rust/test_counters.py extend | green  | feature/rust-effect-move-self-counters |

| rust(effect-deal-damage-eq-source-power): Effect::DealDamageEqualToSourcePowerAnyTarget — Mishra's-Bauble-shape power-scaling damage (2 EoE cards). | tests_rust/test_resolve.py extend | green  | feature/rust-effect-deal-damage-eq-source-power |

| rust(effect-tap-artifact-or-creature): Effect::TapTargetArtifactOrCreature — broader-filter tap variant (defender's first artifact OR creature; 2 EoE cards). | tests_rust/test_tap.py extend | green  | feature/rust-effect-tap-artifact-or-creature |

| rust(effect-conditional-tapped-creatures): Effect::ConditionalOnTappedCreatures — Flight-Deck-Coordinator-shape intervening-if (6 EoE cards). Recursive nested effect via Box<Effect>. | tests_rust/test_resolve.py extend | green  | feature/rust-effect-conditional-tapped-creatures |

| rust(effect-plus1-up-to-n): Effect::PutPlusOneCounterOnEachOfUpToNTargetCreatures — Weftblade-Enhancer-shape multi-target counter add (2 EoE cards). | tests_rust/test_counters.py extend | green  | feature/rust-effect-plus1-up-to-n |

| rust(effect-put-charge-counters-on-self): Effect::PutChargeCountersOnSelf — Blast-Zone-shape charge counters routed to single counters scalar (G8 multi-kind map future) (2 EoE cards). | tests_rust/test_counters.py extend | green  | feature/rust-effect-put-charge-counters-on-self |

| rust(effect-create-token-copy): Effect::CreateTokenCopyOfTargetCreatureYouControl — Mirrorpool-shape spawn new GameObject with target's printing_id (2 EoE cards; subtype injection deferred). | tests_rust/test_zones.py extend | green  | feature/rust-effect-create-token-copy |

| rust(effect-optional-sac-artifact): Effect::OptionalSacArtifactForEffect — Lithobraking-shape 'may sac for effect' with first-slice deterministic-yes (2 EoE cards). | tests_rust/test_resolve.py extend | green  | feature/rust-effect-optional-sac-artifact |

| rust(effect-destroy-enchanted-permanent): Effect::DestroyEnchantedPermanent — Cryoshatter-shape; reads source's attached_to, destroys the host (4 EoE cards). | tests_rust/test_resolve.py extend | green  | feature/rust-effect-destroy-enchanted-permanent |

| rust(effect-tap-enchanted-permanent): Effect::TapEnchantedPermanent — taps source's `attached_to` host; idempotent (2 EoE cards). | tests_rust/test_tap.py extend | green  | feature/rust-effect-tap-enchanted-permanent |

| rust(until-leaves-foundation): new `exiled_with_source: Option<u32>` field on GameObject + `return_paired_exiles_for(source_id)` pymethod + Effect::ExileTargetCreatureUntilSourceLeaves (All-Fates-Stalker shape, 3 EoE cards). Manual return hook; auto-fire-on-bf-leave is follow-up. | tests_rust/test_zones.py extend | green  | feature/rust-until-leaves-foundation |

| rust(effect-exile-opps-nonland-until-leaves): Effect::ExileOpponentsNonlandPermanentUntilLeaves — Hardlight-Containment-shape; broader filter on the r28 until-leaves foundation (4 EoE cards). | tests_rust/test_zones.py extend | green  | feature/rust-effect-exile-opps-nonland-until-leaves |

| rust(decision-callback-may-do): PendingDecision::MayDoChoice variant + submit_may_do_decision pymethod + auto-resolve strategies (default / may_do_yes / may_do_no) + Effect::MayDo wrapper — "you may [inner]" pattern, generalizes the r27 Surveil substrate to a second variant. | tests_rust/test_pending_decisions.py extend | green  | feature/rust-decision-callback-may-do |

| rust(effect-look-top-n-one-to-hand): PendingDecision::PickCardFromExaminedChoice variant + submit_pick_card_decision pymethod + auto-resolve strategies (pick_top, default) + Effect::LookTopNPutOneInHandRestToGraveyard wrapper — Commune-with-Evil-shape (4 EoE cards); validates the multi-variant substrate generalizes to its third variant. | tests_rust/test_pending_decisions.py extend | green  | feature/rust-effect-look-top-n-one-to-hand |

| rust(effect-choose-one-mode): PendingDecision::ChooseModeChoice (4th variant) + submit_choose_mode_decision pymethod + auto-resolve 'choose_mode_0' + Effect::ChooseOneMode { modes: Vec<Effect> } — Python's ModalChooseOne first-slice (resolve-time pick only; 13 EoE cards target family). | tests_rust/test_pending_decisions.py extend | green  | feature/rust-effect-choose-one-mode |

| rust(effect-if-you-do): PendingDecision::IfYouDoChoice (5th variant) + submit_if_you_do_decision pymethod + auto-resolve 'if_you_do_yes' / 'if_you_do_no' + Effect::IfYouDo { do_action, then_action } — Python's IfYouDo combinator first-slice ("looter"-style IfYouDo(MayDo(X), Y); 7+ EoE cards target family). | tests_rust/test_pending_decisions.py extend | green  | feature/rust-effect-if-you-do |

## Build invocation reminder

```
VIRTUAL_ENV="C:/Users/Gregg Keithley/Documents/Claude/Projects/mtg-bot/.venv-py313" \
  "C:/Users/Gregg Keithley/Documents/Claude/Projects/mtg-bot/.venv-py313/Scripts/maturin.exe" \
  develop --release -m rust/Cargo.toml
```

Run only the Rust harness:
```
PYTHONPATH=src "C:/Users/Gregg Keithley/Documents/Claude/Projects/mtg-bot/.venv-py313/Scripts/python.exe" \
  -m pytest tests_rust/ -v --no-cov
```

Full gate (must stay green before commit):
```
PYTHONPATH=src "C:/Users/Gregg Keithley/Documents/Claude/Projects/mtg-bot/.venv-py313/Scripts/python.exe" \
  -m pytest -n 8 --no-cov
```
