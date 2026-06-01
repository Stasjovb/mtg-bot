"""Cleanup-step hand-size limit primitive on ``GameState``.

Ports the hand-size enforcement logic from ``run_cleanup_step`` in
``src/mtg_bot/turn.py`` (lines 969-990 on `feature/rust-tdd-base-r6`):

    while len(ap.hand) > 7:
        card = ap.hand.pop()
        card.zone = Zone.GRAVEYARD
        ap.graveyard.append(card)

Real MTG rule (CR 514.1):

    "If the active player's hand contains more cards than their maximum
    hand size (normally seven), they discard enough cards to reduce
    their hand size to that number."

This slice composes round-4's ``discard`` (library slice) with round-2's
``PHASE_CLEANUP = 11`` (steps slice). The Rust API exposes a single
primitive ``enforce_hand_size_limit(player_id, max_hand_size)`` that the
caller invokes — a future slice can wire it into ``advance_phase`` so
it fires automatically when the active player enters cleanup.

**Scope decisions** (kept narrow for this slice):

- Default max hand size is 7 — encoded by the caller; the primitive
  takes ``max_hand_size`` explicitly so cards like Reliquary Tower (no
  maximum hand size) plug in by passing a sentinel later.
- Active-player only: the primitive takes ``player_id`` explicitly
  rather than reading ``state.active_player``. Whoever calls it picks.
- **Discard target choice is deterministic**: cards come off the END
  of the hand Vec (most recently drawn / pushed). Real MTG: the player
  chooses which cards to discard. This is a stepping-stone — once the
  search side has a discard-decision node, it picks. For now the
  primitive's deterministic choice is good enough for state-evolution
  parity tests and lets the cleanup step make forward progress in
  search rollouts.
- Discarded cards land in the same player's graveyard (CR 514.1 →
  "discard" → CR 701.8 → "owner's graveyard"; for synthetic states
  controller == owner so the same-player target is correct).
"""

from __future__ import annotations

import pytest


def test_hand_at_or_below_max_no_discard(synthetic_state):
    """Synthetic state seeds 7 cards in player 0's hand. Enforcing a
    max of 7 is a no-op — hand stays at 7, graveyard stays at 0."""
    assert synthetic_state.hand_sizes[0] == 7
    gy_before = synthetic_state.graveyard_sizes
    discarded = synthetic_state.enforce_hand_size_limit(0, 7)
    assert discarded == 0
    assert synthetic_state.hand_sizes[0] == 7
    assert synthetic_state.graveyard_sizes == gy_before


def test_hand_above_max_discards_to_max(synthetic_state):
    """Bring hand to 10 via three draws, enforce max=7, expect three
    discards and a hand size of exactly 7."""
    for _ in range(3):
        synthetic_state.draw_card(0)
    assert synthetic_state.hand_sizes[0] == 10

    discarded = synthetic_state.enforce_hand_size_limit(0, 7)
    assert discarded == 3
    assert synthetic_state.hand_sizes[0] == 7


def test_discarded_cards_go_to_graveyard(synthetic_state):
    """Same setup as above; the three discarded cards land in player
    0's graveyard. Player 1's graveyard is untouched."""
    for _ in range(3):
        synthetic_state.draw_card(0)
    gy_before = synthetic_state.graveyard_sizes
    synthetic_state.enforce_hand_size_limit(0, 7)
    assert synthetic_state.graveyard_sizes[0] == gy_before[0] + 3
    assert synthetic_state.graveyard_sizes[1] == gy_before[1]


def test_discard_count_returns_number_discarded(synthetic_state):
    """The return value is the count of cards moved hand -> graveyard."""
    for _ in range(3):
        synthetic_state.draw_card(0)
    assert synthetic_state.enforce_hand_size_limit(0, 7) == 3


def test_no_discard_returns_zero(synthetic_state):
    """No discard needed -> returns 0."""
    assert synthetic_state.enforce_hand_size_limit(0, 7) == 0
    # Even with a generous limit on a small hand:
    assert synthetic_state.enforce_hand_size_limit(0, 100) == 0


def test_max_hand_size_zero_discards_everything(synthetic_state):
    """``max_hand_size=0`` empties the hand (all 7 cards into
    graveyard)."""
    discarded = synthetic_state.enforce_hand_size_limit(0, 0)
    assert discarded == 7
    assert synthetic_state.hand_sizes[0] == 0
    assert synthetic_state.graveyard_sizes[0] == 7


def test_only_discards_target_player(synthetic_state):
    """Bring both hands to 10; enforce on player 0 only — player 1's
    hand is unchanged."""
    for _ in range(3):
        synthetic_state.draw_card(0)
        synthetic_state.draw_card(1)
    assert synthetic_state.hand_sizes == [10, 10]

    synthetic_state.enforce_hand_size_limit(0, 7)
    assert synthetic_state.hand_sizes[0] == 7
    assert synthetic_state.hand_sizes[1] == 10
    # Player 1's graveyard untouched.
    assert synthetic_state.graveyard_sizes[1] == 0


def test_unknown_player_raises(synthetic_state):
    """Out-of-range player_id (only 0 / 1 are valid for two-player)
    raises ValueError rather than silently no-op'ing."""
    with pytest.raises(ValueError):
        synthetic_state.enforce_hand_size_limit(99, 7)


def test_negative_max_raises(synthetic_state):
    """A negative max_hand_size makes no sense (you can't reduce hand
    size below zero); raise rather than treat as max=0."""
    with pytest.raises(ValueError):
        synthetic_state.enforce_hand_size_limit(0, -1)


def test_clone_then_discard_does_not_affect_original(synthetic_state):
    """Load-bearing CoW canary: enforcing on a clone must not leak
    back into the source state. Both hand and graveyard are mutated,
    so this is the strictest CoW check in the slice."""
    for _ in range(3):
        synthetic_state.draw_card(0)
    cloned = synthetic_state.clone_once()
    hand_source_before = synthetic_state.hand_sizes
    gy_source_before = synthetic_state.graveyard_sizes

    discarded = cloned.enforce_hand_size_limit(0, 7)
    assert discarded == 3

    # Clone diverged.
    assert cloned.hand_sizes[0] == 7
    assert cloned.graveyard_sizes[0] == gy_source_before[0] + 3
    # Source untouched.
    assert synthetic_state.hand_sizes == hand_source_before
    assert synthetic_state.graveyard_sizes == gy_source_before


# --------------------------------------------------------------------------
# Round-8 cleanup-step composition primitive
# --------------------------------------------------------------------------
#
# `cleanup_step_for_active_player()` runs the two halves of CR 514 we model:
#
#   1. CR 514.1 — hand-size discard (max=7 hard-coded for active player)
#   2. CR 514.2 — clear all marked damage on the battlefield (BOTH players)
#
# Ordering: hand-size discard FIRST, then damage clearance. CR 514's
# numbered sub-rules execute in order — 514.1 runs before 514.2. This
# matches the source-of-truth `run_cleanup_step` in
# `src/mtg_bot/turn.py` (hand-size while-loop precedes the damage-clear
# loop) and matters for any future "discard triggers"-aware ordering.
#
# CR 514.3 ("until end of turn" effects expire) and CR 514.4 (no-trigger
# repeat cleanup step) are deferred — those compose with continuous-
# effect machinery / triggered-ability machinery the Rust engine does
# not yet have.
#
# Return shape: a Python dict ``{"discarded": N, "damage_cleared": M}``
# where M is the count of permanents whose damage marker was non-zero
# before the call (so a no-op cleanup returns zeros and a caller can
# log meaningful telemetry without re-walking battlefields).
#
# Same-file P0_FIRST_BATTLEFIELD_ID etc. are not in scope here, but the
# damage tests' synthetic-state id layout applies — first 10 ids on
# each player's battlefield (0..9 / 67..76).

P0_BATTLEFIELD_FIRST = 0
P1_BATTLEFIELD_FIRST = 67


def test_cleanup_step_no_op_at_initial_state(synthetic_state):
    """Fresh synthetic state has 7 cards in each hand and zero damage on
    every permanent. ``cleanup_step_for_active_player`` is a true no-op:
    returns the all-zero/false summary and leaves hand / graveyard /
    damage alone. (Round-27 added ``ueot_cleared`` for the CR 514.3
    UEOT-modifier expiration pass; later rounds added
    ``controller_overrides_cleared`` (control-changing UEOT expiry),
    ``prevent_all_combat_damage_drained`` (one-shot prevent-shield
    drain), and ``regeneration_shields_cleared`` (regen-shield clear) —
    all no-ops at initial state.)
    """
    assert synthetic_state.hand_sizes[0] == 7
    summary = synthetic_state.cleanup_step_for_active_player()
    assert summary == {
        "discarded": 0,
        "damage_cleared": 0,
        "ueot_cleared": 0,
        "controller_overrides_cleared": 0,
        "prevent_all_combat_damage_drained": False,
        "regeneration_shields_cleared": 0,
    }
    assert synthetic_state.hand_sizes[0] == 7
    assert synthetic_state.graveyard_sizes[0] == 0


def test_cleanup_step_discards_to_seven(synthetic_state):
    """Three extra draws bring the active player's hand to 10. Cleanup
    discards 3 down to the 7-card limit; those 3 land in the active
    player's graveyard."""
    for _ in range(3):
        synthetic_state.draw_card(0)
    assert synthetic_state.hand_sizes[0] == 10
    gy_before = synthetic_state.graveyard_sizes

    summary = synthetic_state.cleanup_step_for_active_player()
    assert summary["discarded"] == 3
    assert summary["damage_cleared"] == 0
    assert synthetic_state.hand_sizes[0] == 7
    assert synthetic_state.graveyard_sizes[0] == gy_before[0] + 3


def test_cleanup_step_clears_marked_damage(synthetic_state):
    """One point of damage on a battlefield permanent. Cleanup zeros
    the marker and reports it in the summary."""
    obj = P0_BATTLEFIELD_FIRST
    synthetic_state.deal_damage(obj, 1)
    assert synthetic_state.get_damage(obj) == 1

    summary = synthetic_state.cleanup_step_for_active_player()
    assert summary["damage_cleared"] == 1
    assert synthetic_state.get_damage(obj) == 0


def test_cleanup_step_only_for_active_player(synthetic_state):
    """``cleanup_step_for_active_player`` only enforces the hand-size
    limit on the ACTIVE player. Stuff player 1's hand to 10, leave
    player 0 at 7, and confirm the call (active=0) does NOT touch
    player 1's hand or graveyard."""
    assert synthetic_state.active_player == 0
    for _ in range(3):
        synthetic_state.draw_card(1)
    assert synthetic_state.hand_sizes[1] == 10
    p1_gy_before = synthetic_state.graveyard_sizes[1]

    summary = synthetic_state.cleanup_step_for_active_player()
    assert summary["discarded"] == 0
    # Player 1's hand and graveyard untouched even though oversized.
    assert synthetic_state.hand_sizes[1] == 10
    assert synthetic_state.graveyard_sizes[1] == p1_gy_before


def test_cleanup_step_clears_damage_on_both_players_objects(synthetic_state):
    """CR 514.2 is wholesale: ALL marked damage clears at cleanup, not
    just the active player's. Damage on a player-1 permanent zeroes
    even when active_player is 0."""
    p0_obj = P0_BATTLEFIELD_FIRST
    p1_obj = P1_BATTLEFIELD_FIRST
    synthetic_state.deal_damage(p0_obj, 2)
    synthetic_state.deal_damage(p1_obj, 3)
    assert synthetic_state.get_damage(p0_obj) == 2
    assert synthetic_state.get_damage(p1_obj) == 3

    summary = synthetic_state.cleanup_step_for_active_player()
    assert summary["damage_cleared"] == 2
    assert synthetic_state.get_damage(p0_obj) == 0
    assert synthetic_state.get_damage(p1_obj) == 0


def test_cleanup_step_returns_summary(synthetic_state):
    """Combined: 3 discards + damage on 2 permanents -> summary reports
    both counts in the same call."""
    for _ in range(3):
        synthetic_state.draw_card(0)
    synthetic_state.deal_damage(P0_BATTLEFIELD_FIRST, 1)
    synthetic_state.deal_damage(P1_BATTLEFIELD_FIRST, 1)

    summary = synthetic_state.cleanup_step_for_active_player()
    assert isinstance(summary, dict)
    assert summary == {
        "discarded": 3,
        "damage_cleared": 2,
        "ueot_cleared": 0,
        "controller_overrides_cleared": 0,
        "prevent_all_combat_damage_drained": False,
        "regeneration_shields_cleared": 0,
    }
    assert synthetic_state.hand_sizes[0] == 7
    assert synthetic_state.get_damage(P0_BATTLEFIELD_FIRST) == 0
    assert synthetic_state.get_damage(P1_BATTLEFIELD_FIRST) == 0


def test_clone_then_cleanup_does_not_affect_original(synthetic_state):
    """**CoW canary for the composition primitive.** Both halves mutate
    state (hand/graveyard via Arc::make_mut on a player's zones, damage
    via Arc::make_mut on each battlefield Vec). Running cleanup on a
    clone must not leak into the source — same load-bearing assertion
    as the round-6 single-half canary, extended to the composition."""
    for _ in range(3):
        synthetic_state.draw_card(0)
    synthetic_state.deal_damage(P0_BATTLEFIELD_FIRST, 1)
    synthetic_state.deal_damage(P1_BATTLEFIELD_FIRST, 2)

    cloned = synthetic_state.clone_once()
    hand_source_before = synthetic_state.hand_sizes
    gy_source_before = synthetic_state.graveyard_sizes

    summary = cloned.cleanup_step_for_active_player()
    assert summary == {
        "discarded": 3,
        "damage_cleared": 2,
        "ueot_cleared": 0,
        "controller_overrides_cleared": 0,
        "prevent_all_combat_damage_drained": False,
        "regeneration_shields_cleared": 0,
    }

    # Clone diverged.
    assert cloned.hand_sizes[0] == 7
    assert cloned.graveyard_sizes[0] == gy_source_before[0] + 3
    assert cloned.get_damage(P0_BATTLEFIELD_FIRST) == 0
    assert cloned.get_damage(P1_BATTLEFIELD_FIRST) == 0

    # Source untouched — hand still 10, graveyard unchanged, damage
    # still on its permanents.
    assert synthetic_state.hand_sizes == hand_source_before
    assert synthetic_state.graveyard_sizes == gy_source_before
    assert synthetic_state.get_damage(P0_BATTLEFIELD_FIRST) == 1
    assert synthetic_state.get_damage(P1_BATTLEFIELD_FIRST) == 2


# --------------------------------------------------------------------------
# Round-17 end-of-turn wrap composition primitive
# --------------------------------------------------------------------------
#
# `end_turn_and_start_next()` is the higher-level composition that bundles:
#   1. round-8's `cleanup_step_for_active_player()`  (this same file)
#   2. round-2's `advance_phase()` from CLEANUP -> next turn's UNTAP
#      (which fires round-14's untap-step summoning-sick clear automatically)
#
# Implementation strategy — set phase to CLEANUP, run cleanup_step_for_active_player,
# then advance_phase ONCE so the wrap CLEANUP -> UNTAP fires turn_number bump,
# active_player swap, and the round-14 sickness-clear hook on the new active player.
#
# Cross-file note: `advance_phase` lives in `state_ops_steps.rs`. The round-16
# pattern routes the cross-file call through PyO3's `Bound<'_, Self>::call_method0`
# rather than copy-pasting the advance logic inline.
#
# `cleanup_step_for_active_player` sits in this same file (`state_ops_cleanup.rs`)
# so a direct `&mut self` call is allowed; using `call_method0` for it is also fine
# and keeps the dispatch shape uniform.

PHASE_UNTAP_CONST = 0


def test_end_turn_and_start_next_advances_to_next_turn(synthetic_state):
    """From a fresh synthetic state at PHASE_UNTAP, end_turn_and_start_next
    bumps the turn counter by 1, sets phase to UNTAP of the next turn, and
    leaves the engine in a state where the new active player can take their
    untap step. Independent of the starting phase."""
    starting_turn = synthetic_state.turn_number
    starting_active = synthetic_state.active_player
    synthetic_state.end_turn_and_start_next()
    assert synthetic_state.turn_number == starting_turn + 1
    assert synthetic_state.current_phase() == PHASE_UNTAP_CONST
    assert synthetic_state.active_player == 1 - starting_active


def test_end_turn_and_start_next_clears_hand_to_max(synthetic_state):
    """Cleanup step half: hand at 10 -> hand at 7 after end_turn, three
    cards land in the active player's graveyard."""
    for _ in range(3):
        synthetic_state.draw_card(0)
    assert synthetic_state.hand_sizes[0] == 10
    gy_before_p0 = synthetic_state.graveyard_sizes[0]
    synthetic_state.end_turn_and_start_next()
    # Active player at end_turn entry was 0, so cleanup discarded p0's hand.
    assert synthetic_state.hand_sizes[0] == 7
    assert synthetic_state.graveyard_sizes[0] == gy_before_p0 + 3


def test_end_turn_and_start_next_clears_damage(synthetic_state):
    """Cleanup-step damage half: marked damage on a permanent is zero
    after end_turn fires CR 514.2."""
    obj = P0_BATTLEFIELD_FIRST
    synthetic_state.deal_damage(obj, 2)
    assert synthetic_state.get_damage(obj) == 2
    synthetic_state.end_turn_and_start_next()
    assert synthetic_state.get_damage(obj) == 0


def test_end_turn_and_start_next_clears_summoning_sickness_for_new_active(
    synthetic_state,
):
    """The CLEANUP -> UNTAP wrap fires advance_phase's round-14 hook:
    summoning sickness clears on the NEW active player's permanents.
    Cast a creature for player 1 (who will become active after end_turn);
    after end_turn that creature is no longer summoning-sick."""
    # P1's first hand object id with the synthetic 10/7/50 layout.
    elf_id = 67 + 10
    synthetic_state.add_mana(1, "G", 1)
    assert synthetic_state.cast_creature(elf_id, 1) is True
    synthetic_state.resolve_top_of_stack()  # G7 S1: land it on the bf
    assert synthetic_state.is_summoning_sick(elf_id) is True
    assert synthetic_state.active_player == 0
    synthetic_state.end_turn_and_start_next()
    assert synthetic_state.active_player == 1
    assert synthetic_state.is_summoning_sick(elf_id) is False, (
        "the CLEANUP -> UNTAP wrap inside end_turn_and_start_next should "
        "have fired the round-14 summoning-sick clear on the new active "
        "player's permanents"
    )


def test_end_turn_and_start_next_swaps_active_player(synthetic_state):
    """Active player flips from 0 to 1 after one end_turn."""
    assert synthetic_state.active_player == 0
    synthetic_state.end_turn_and_start_next()
    assert synthetic_state.active_player == 1


def test_end_turn_and_start_next_clone_isolation(synthetic_state):
    """**CoW canary for the composition primitive.** end_turn mutates
    phase, turn_number, active_player AND every CoW-tracked zone touched
    by cleanup_step_for_active_player (hand, graveyard, battlefield damage)
    AND any permanent untapped/desickened by the round-14 hook. Running
    end_turn on a clone must not bleed into the source."""
    for _ in range(3):
        synthetic_state.draw_card(0)
    synthetic_state.deal_damage(P0_BATTLEFIELD_FIRST, 1)
    synthetic_state.deal_damage(P1_BATTLEFIELD_FIRST, 2)

    cloned = synthetic_state.clone_once()
    src_turn = synthetic_state.turn_number
    src_phase = synthetic_state.current_phase()
    src_active = synthetic_state.active_player
    src_hand = synthetic_state.hand_sizes
    src_gy = synthetic_state.graveyard_sizes
    src_damage_p0 = synthetic_state.get_damage(P0_BATTLEFIELD_FIRST)
    src_damage_p1 = synthetic_state.get_damage(P1_BATTLEFIELD_FIRST)

    cloned.end_turn_and_start_next()

    # Clone diverged.
    assert cloned.turn_number == src_turn + 1
    assert cloned.current_phase() == PHASE_UNTAP_CONST
    assert cloned.active_player == 1 - src_active
    assert cloned.hand_sizes[0] == 7
    assert cloned.get_damage(P0_BATTLEFIELD_FIRST) == 0
    assert cloned.get_damage(P1_BATTLEFIELD_FIRST) == 0

    # Source untouched.
    assert synthetic_state.turn_number == src_turn
    assert synthetic_state.current_phase() == src_phase
    assert synthetic_state.active_player == src_active
    assert synthetic_state.hand_sizes == src_hand
    assert synthetic_state.graveyard_sizes == src_gy
    assert synthetic_state.get_damage(P0_BATTLEFIELD_FIRST) == src_damage_p0
    assert synthetic_state.get_damage(P1_BATTLEFIELD_FIRST) == src_damage_p1


# --------------------------------------------------------------------------
# CR 514 cross-feature edge-case coverage
# --------------------------------------------------------------------------
#
# These tests pin cross-primitive interactions between cleanup_step_for_
# active_player and the other engine primitives that compose with it —
# Effect dispatch (DealDamage / DealDamageAnyTarget / DamageEachCreature),
# the mana-pool slice (AddManaToPool), advance_phase, and fingerprint.
#
# Each test asks "does cleanup correctly observe / clear / preserve the
# state that some OTHER slice mutated"? The earlier tests in this file
# all stamp damage via the engine's raw `deal_damage` primitive; these
# go through the full stack -> resolve -> Effect-dispatch path so we
# catch any wiring gap between Effect arms and the cleanup sweep.
#
# Also documents two known gaps the Rust engine has today, locked in
# with explicit assertions so the gap is visible (rather than asserted
# away) and a future "close the gap" slice has a failing test waiting:
#
# - Mana pool is NOT emptied by cleanup_step_for_active_player /
#   end_turn_and_start_next (CR 106.4 — "When a phase or step ends,
#   each player's mana pool empties"). The empty_mana_pool primitive
#   exists; nothing wires it into the cleanup composition yet.
# - Hand-size enforcement does NOT auto-fire when advance_phase wraps
#   through CLEANUP. The active player must explicitly call
#   cleanup_step_for_active_player or end_turn_and_start_next.
#
# Both gaps are documented in the assertions below so they show up in
# the parity harness when (and only when) someone changes the behavior.


# Helper printings — match the existing test_resolve.py shape, kept
# inline here so this file stays self-contained.
_ZONE_HAND = 0
_ZONE_BATTLEFIELD = 2


def _bombard_any_creature_dict(amount):
    """A DealDamage{any_creature, amount} sorcery — picks the FIRST
    object on the defender's battlefield (smallest index)."""
    return {
        "name": "Edge Bombard",
        "card_types": ["Sorcery"],
        "mana_cost": {"R": 1, "generic": 2},
        "effects": [
            {
                "kind": "deal_damage",
                "amount": amount,
                "target": {"kind": "any_creature"},
            }
        ],
    }


def _bolt_any_target_dict(amount):
    """A DealDamageAnyTarget{amount} instant — Lightning Bolt-shaped.
    Picks the defender's first creature; falls back to player life
    if there is no creature."""
    return {
        "name": "Edge Bolt",
        "card_types": ["Instant"],
        "mana_cost": {"R": 1},
        "effects": [{"kind": "deal_damage_any_target", "amount": amount}],
    }


def _pyroclasm_dict(amount):
    """A DamageEachCreature{amount} sorcery — Pyroclasm-shaped.
    Marks `amount` damage on every creature on both battlefields."""
    return {
        "name": "Edge Pyroclasm",
        "card_types": ["Sorcery"],
        "mana_cost": {"R": 1, "generic": 1},
        "effects": [{"kind": "damage_each_creature", "amount": amount}],
    }


# The synthetic seed lays the first 5 bf objects per player as Forests
# (Land) and the next 5 as Grizzly Bears (Creature). DealDamage with
# `any_creature` targets the smallest-index OBJECT on the defender's
# battlefield (slice docstring); DealDamageAnyTarget filters for
# Creature first. Pin both ids here so the assertions are concrete.
P1_FIRST_OBJ_ID = 67       # First object on p1 bf (a Forest / Land)
P1_FIRST_CREATURE_ID = 72  # First Creature on p1 bf (a Grizzly Bears)
P0_CREATURE_IDS = (5, 6, 7, 8, 9)
P1_CREATURE_IDS = (72, 73, 74, 75, 76)


def test_cleanup_clears_damage_stamped_via_effect_deal_damage(synthetic_state):
    """Cross-feature: Effect::DealDamage dispatches through the stack
    and marks damage on the defender's first battlefield object;
    cleanup observes that mark and zeroes it. Validates that the
    cleanup primitive doesn't only see damage stamped via the raw
    deal_damage primitive — it picks up damage written by the full
    resolve-time dispatch path too."""
    spell_id = synthetic_state.register_and_inject_object(
        _bombard_any_creature_dict(amount=2), 0, _ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.get_damage(P1_FIRST_OBJ_ID) == 2

    summary = synthetic_state.cleanup_step_for_active_player()
    assert summary["damage_cleared"] == 1
    assert synthetic_state.get_damage(P1_FIRST_OBJ_ID) == 0


def test_cleanup_clears_damage_stamped_via_deal_damage_any_target(
    synthetic_state,
):
    """Cross-feature: Effect::DealDamageAnyTarget (Lightning Bolt
    shape) marks 3 damage on the defender's first Creature; cleanup
    clears it the same way the simpler DealDamage path clears.
    Pins that the variant's damage-write feeds the same per-object
    marker the cleanup sweep walks."""
    spell_id = synthetic_state.register_and_inject_object(
        _bolt_any_target_dict(amount=3), 0, _ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.get_damage(P1_FIRST_CREATURE_ID) == 3

    summary = synthetic_state.cleanup_step_for_active_player()
    assert summary["damage_cleared"] == 1
    assert synthetic_state.get_damage(P1_FIRST_CREATURE_ID) == 0


def test_cleanup_clears_damage_stamped_via_damage_each_creature(
    synthetic_state,
):
    """Cross-feature: Effect::DamageEachCreature marks `amount` on
    EVERY creature on both battlefields (5 + 5 = 10 in the synthetic
    seed); cleanup reports `damage_cleared == 10` and zeroes them
    all. The largest cross-feature damage-clear case in this file —
    exercises the cleanup sweep's both-players battlefield walk."""
    spell_id = synthetic_state.register_and_inject_object(
        _pyroclasm_dict(amount=2), 0, _ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()
    for cid in P0_CREATURE_IDS + P1_CREATURE_IDS:
        assert synthetic_state.get_damage(cid) == 2

    summary = synthetic_state.cleanup_step_for_active_player()
    assert summary["damage_cleared"] == 10
    for cid in P0_CREATURE_IDS + P1_CREATURE_IDS:
        assert synthetic_state.get_damage(cid) == 0


def test_cleanup_step_does_not_empty_mana_pool_at_primitive_layer(
    synthetic_state,
):
    """**Layering pin.** The ``cleanup_step_for_active_player``
    primitive is scoped to CR 514.1 (hand-size discard) + CR 514.2
    (damage clear). The CR 106.4 "phase or step ends, each player's
    mana pool empties" rule is OWNED by the phase machinery
    (``advance_phase``), NOT by this lower-level primitive — callers
    that invoke the cleanup primitive directly (e.g. tests building
    up state piece by piece) get the discard + damage clear but the
    mana pool survives.

    This is a deliberate layering decision: ``advance_phase`` empties
    pools on every phase boundary (see the entry composition in
    ``state_ops_steps.rs::advance_phase``), so a caller walking
    ``advance_phase`` through CLEANUP DOES see pools empty — the
    side-effect rides on the phase tick, not on the cleanup primitive
    call. The companion test
    ``test_advance_phase_through_cleanup_empties_mana_pool`` covers
    the phase-machinery path."""
    synthetic_state.add_mana(0, "G", 3)
    synthetic_state.add_mana(1, "R", 2)
    synthetic_state.cleanup_step_for_active_player()
    # Pool survives because the primitive is layered below the
    # CR 106.4 hook; that hook fires inside ``advance_phase``, not
    # inside the cleanup primitive.
    assert synthetic_state.get_mana_pool(0)["G"] == 3
    assert synthetic_state.get_mana_pool(1)["R"] == 2


def test_end_turn_and_start_next_empties_mana_pool(
    synthetic_state,
):
    """CR 106.4 closure — ``end_turn_and_start_next`` composes
    cleanup_step + ``advance_phase``; the ``advance_phase`` lap through
    CLEANUP -> UNTAP empties both players' mana pools (and in fact a
    single advance_phase call empties them, since the CR 106.4 hook
    fires on every phase exit). Pins the closed gap so a future
    refactor that detaches ``advance_phase`` from the mana-empty hook
    surfaces here."""
    synthetic_state.add_mana(0, "G", 3)
    synthetic_state.add_mana(1, "R", 2)
    synthetic_state.end_turn_and_start_next()
    # Pools emptied at the phase boundary inside the wrap.
    assert synthetic_state.get_mana_pool(0)["G"] == 0
    assert synthetic_state.get_mana_pool(1)["R"] == 0


def test_advance_phase_through_cleanup_enforces_hand_size(
    synthetic_state,
):
    """CR 514.1 closure — ``advance_phase`` walking through
    PHASE_CLEANUP auto-fires the hand-size discard on the active
    player. Stuff p0's hand to 10, walk ``advance_phase`` until the
    turn wraps, and assert p0's hand is at 7 on the new turn.

    During the lap:
    - p0's hand starts at 10
    - ``advance_phase`` entry to PHASE_DRAW fires the G14 auto-draw
      (CR 504.1), bumping the hand to 11
    - ``advance_phase`` entry to PHASE_CLEANUP fires
      ``cleanup_step_for_active_player_inline`` (CR 514.1 +
      CR 514.2), discarding 4 cards to land at 7
    - the CLEANUP -> UNTAP wrap on the final advance flips active to
      p1 (whose hand was untouched throughout, at 7)

    Pins the closed gap so a future refactor that detaches
    ``advance_phase`` from the cleanup-step hook surfaces here."""
    for _ in range(3):
        synthetic_state.draw_card(0)
    assert synthetic_state.hand_sizes[0] == 10
    starting_turn = synthetic_state.turn_number

    # Advance until we wrap to a new turn (phase resets to 0).
    for _ in range(20):
        prev_phase = synthetic_state.current_phase()
        synthetic_state.advance_phase()
        if synthetic_state.current_phase() == 0 and prev_phase != 0:
            break
    assert synthetic_state.turn_number == starting_turn + 1
    # CR 514.1 fired on entry to CLEANUP and discarded down to 7.
    # The G14 auto-draw earlier in the lap raised the hand to 11
    # before the discard pulled it back to 7 — net change from
    # the starting 10 is -3 (= +1 auto-draw - 4 cleanup-discards).
    assert synthetic_state.hand_sizes[0] == 7


def test_cleanup_is_idempotent_when_already_clean(synthetic_state):
    """Calling ``cleanup_step_for_active_player`` twice in a row is
    safe — the second call is a true no-op when nothing changed
    between calls. Pins that the cleanup sweep's damage-counter loop
    doesn't double-count and the hand-size enforcer doesn't re-trigger
    on an already-clean hand."""
    synthetic_state.deal_damage(P0_BATTLEFIELD_FIRST, 3)
    first = synthetic_state.cleanup_step_for_active_player()
    assert first == {
        "discarded": 0,
        "damage_cleared": 1,
        "ueot_cleared": 0,
        "controller_overrides_cleared": 0,
        "prevent_all_combat_damage_drained": False,
        "regeneration_shields_cleared": 0,
    }
    second = synthetic_state.cleanup_step_for_active_player()
    # Second call sees nothing to clean: no damage, hand still <= 7.
    assert second == {
        "discarded": 0,
        "damage_cleared": 0,
        "ueot_cleared": 0,
        "controller_overrides_cleared": 0,
        "prevent_all_combat_damage_drained": False,
        "regeneration_shields_cleared": 0,
    }
    # State is identical to first-call post-state.
    assert synthetic_state.get_damage(P0_BATTLEFIELD_FIRST) == 0
    assert synthetic_state.hand_sizes[0] == 7


def test_cleanup_on_clone_does_not_clear_originals_effect_damage(
    synthetic_state,
):
    """**CoW canary across Effect dispatch + cleanup.** Stamp damage
    via the full Effect::DamageEachCreature path on the source state;
    clone; cleanup the clone. The original's marked damage must
    survive untouched, even though the same battlefield Vec sat
    under both states a moment ago. Composes the round-3 Effect
    dispatch CoW guarantee with the round-8 cleanup CoW guarantee."""
    spell_id = synthetic_state.register_and_inject_object(
        _pyroclasm_dict(amount=2), 0, _ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()
    # Every creature now at damage=2 on the source.
    for cid in P0_CREATURE_IDS + P1_CREATURE_IDS:
        assert synthetic_state.get_damage(cid) == 2

    cloned = synthetic_state.clone_once()
    summary = cloned.cleanup_step_for_active_player()
    assert summary["damage_cleared"] == 10

    # Clone is clean.
    for cid in P0_CREATURE_IDS + P1_CREATURE_IDS:
        assert cloned.get_damage(cid) == 0
    # Source untouched — damage stamps survive the clone's cleanup.
    for cid in P0_CREATURE_IDS + P1_CREATURE_IDS:
        assert synthetic_state.get_damage(cid) == 2


def test_cleanup_changes_fingerprint_iff_state_changed(synthetic_state):
    """Fingerprint cross-feature: cleanup that finds work to do
    mutates state and the fingerprint changes; cleanup on an already-
    clean state is a true no-op and the fingerprint is byte-identical
    before and after. Pins that the cleanup primitive doesn't have a
    hidden side-effect (mutation that doesn't feed the fingerprint
    digest, or vice versa)."""
    # Dirty cleanup: damage stamp on a permanent.
    synthetic_state.deal_damage(P0_BATTLEFIELD_FIRST, 2)
    fp_dirty = synthetic_state.fingerprint()
    synthetic_state.cleanup_step_for_active_player()
    fp_clean = synthetic_state.fingerprint()
    assert fp_dirty != fp_clean, (
        "cleanup that zeroes a non-zero damage marker must change the "
        "fingerprint — damage is part of the per-object signature"
    )

    # Re-running cleanup on the now-clean state is fingerprint-stable.
    fp_before_idempotent = synthetic_state.fingerprint()
    synthetic_state.cleanup_step_for_active_player()
    fp_after_idempotent = synthetic_state.fingerprint()
    assert fp_before_idempotent == fp_after_idempotent


def test_cleanup_alone_does_not_move_objects_between_zones(synthetic_state):
    """Inverse-completeness check (already covered indirectly in the
    zones cross-primitive file). When cleanup has nothing to do —
    hand at 7, no damage anywhere — it must NOT silently shuffle
    objects between zones. Snapshot every zone's contents before
    and after and confirm bit-identical equality.

    Specifically pinning the no-zone-move guarantee on the cleanup
    primitive itself, so a regression that e.g. moves cards out of
    hand during cleanup-with-no-discard would surface here rather
    than only in the higher-level end_turn_and_start_next tests."""
    hand_before = synthetic_state.hand_snapshot(0)
    lib_before = synthetic_state.library_snapshot(0)
    gy_before = synthetic_state.graveyard_snapshot(0)
    bf_before = synthetic_state.battlefield_snapshot()
    sizes_before = (
        synthetic_state.hand_sizes,
        synthetic_state.battlefield_sizes,
        synthetic_state.library_sizes,
        synthetic_state.graveyard_sizes,
    )

    summary = synthetic_state.cleanup_step_for_active_player()
    assert summary == {
        "discarded": 0,
        "damage_cleared": 0,
        "ueot_cleared": 0,
        "controller_overrides_cleared": 0,
        "prevent_all_combat_damage_drained": False,
        "regeneration_shields_cleared": 0,
    }

    assert synthetic_state.hand_snapshot(0) == hand_before
    assert synthetic_state.library_snapshot(0) == lib_before
    assert synthetic_state.graveyard_snapshot(0) == gy_before
    assert synthetic_state.battlefield_snapshot() == bf_before
    assert (
        synthetic_state.hand_sizes,
        synthetic_state.battlefield_sizes,
        synthetic_state.library_sizes,
        synthetic_state.graveyard_sizes,
    ) == sizes_before
