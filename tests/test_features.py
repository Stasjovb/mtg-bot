"""Tests for ``mtg_bot.features``.

Covers:
- Output shape + dtype contract.
- Determinism (same input → same output).
- Per-side block correctness for life / hand size / library / etc.
- Battlefield aggregation: creature counts, land counts, P/T sums,
  tapped/untapped, max threat.
- Keyword block: counts the right creatures with the right keywords.
- Global block: stack size, is_viewer_turn, step index.
- Viewer-relative invariant: swapping viewer swaps the per-side
  blocks but otherwise produces the same global section.
- Edge cases: empty board, terminal-ish states, no-opponent
  defensive path.
"""

from __future__ import annotations

import numpy as np

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.features import FEATURE_DIM, extract_features
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.simulate import setup_game
from mtg_bot.turn import STEP_ORDER, Step
from tests._test_decks import simple_test_decklists  # noqa: E402


def _empty_two_player_state() -> GameState:
    """Bare 2-player state with no cards anywhere — for unit tests
    that want to control exactly what's on the board."""
    state = GameState()
    state.players = [Player(id=0), Player(id=1)]
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    state.turn_number = 1
    return state


def _put_on_battlefield(state, name: str, controller_id: int):
    obj = state.new_object(
        SYNTHETIC_CREATURES[name], owner_id=controller_id,
        zone=Zone.BATTLEFIELD,
    )
    obj.summoning_sick = False
    state.battlefield.append(obj)
    return obj


def _put_land_on_battlefield(state, name: str, controller_id: int):
    obj = state.new_object(
        BASIC_LANDS[name], owner_id=controller_id,
        zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(obj)
    return obj


# ---------- shape + dtype ----------------------------------------------------


def test_output_has_correct_shape_and_dtype():
    state = _empty_two_player_state()
    features = extract_features(state, viewer_id=0)
    assert features.shape == (FEATURE_DIM,)
    assert features.dtype == np.float32


def test_feature_dim_is_finite_and_reasonable():
    """Sanity check that FEATURE_DIM is in the expected ballpark.
    We documented ~50 features; bumping past 100 unintentionally
    would mean we lost track."""
    assert 30 <= FEATURE_DIM <= 100


# ---------- determinism ------------------------------------------------------


def test_extract_is_deterministic():
    state = setup_game([RandomAgent(), RandomAgent()], decks=simple_test_decklists(), seed=42,
    )
    a = extract_features(state, viewer_id=0)
    b = extract_features(state, viewer_id=0)
    np.testing.assert_array_equal(a, b)


def test_extract_does_not_mutate_state():
    state = setup_game([RandomAgent(), RandomAgent()], decks=simple_test_decklists(), seed=7,
    )
    pre_hand = [
        [c.id for c in p.hand] for p in state.players
    ]
    pre_step = state.step
    extract_features(state, viewer_id=0)
    post_hand = [
        [c.id for c in p.hand] for p in state.players
    ]
    assert post_hand == pre_hand
    assert state.step == pre_step


# ---------- per-side block: basic counts ------------------------------------


def test_life_recorded_in_per_side_block():
    state = _empty_two_player_state()
    state.players[0].life = 17
    state.players[1].life = 4
    features = extract_features(state, viewer_id=0)
    # Viewer block (start=0) → life is the FIRST feature.
    assert features[0] == 17
    # Opponent block starts at 16 (= per-side block size).
    assert features[16] == 4


def test_swapping_viewer_swaps_per_side_blocks():
    state = _empty_two_player_state()
    state.players[0].life = 12
    state.players[1].life = 8
    features_p0 = extract_features(state, viewer_id=0)
    features_p1 = extract_features(state, viewer_id=1)
    # Viewer block of P1 == opponent block of P0.
    assert features_p1[0] == features_p0[16]
    assert features_p1[16] == features_p0[0]


def test_hand_library_graveyard_exile_sizes_recorded():
    state = _empty_two_player_state()
    p = state.players[0]
    p.hand = [
        state.new_object(BASIC_LANDS["Plains"], 0, Zone.HAND)
        for _ in range(5)
    ]
    p.library = [
        state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        for _ in range(40)
    ]
    p.graveyard = [
        state.new_object(BASIC_LANDS["Plains"], 0, Zone.GRAVEYARD)
        for _ in range(3)
    ]
    p.exile = [
        state.new_object(BASIC_LANDS["Plains"], 0, Zone.EXILE)
        for _ in range(2)
    ]
    features = extract_features(state, viewer_id=0)
    # Viewer block: hand_size at index 2, library at 3, gy at 4, exile at 5.
    assert features[2] == 5
    assert features[3] == 40
    assert features[4] == 3
    assert features[5] == 2


def test_poison_counters_recorded():
    state = _empty_two_player_state()
    state.players[0].poison_counters = 7
    features = extract_features(state, viewer_id=0)
    # Index 1 = poison.
    assert features[1] == 7


# ---------- per-side block: battlefield aggregation -------------------------


def test_creature_count_and_pt_aggregation():
    state = _empty_two_player_state()
    # Battlefield Recruit is a 1/2 vanilla. Trained Soldier is a 2/2.
    _put_on_battlefield(state, "Battlefield Recruit", 0)  # 1/2
    _put_on_battlefield(state, "Trained Soldier", 0)  # 2/2
    features = extract_features(state, viewer_id=0)
    # Index 8 = num_creatures in viewer block.
    assert features[8] == 2
    # Index 10 = total_power = 1+2; 11 = total_toughness = 2+2.
    assert features[10] == 3
    assert features[11] == 4
    # Index 12 = max_threat_pt (single biggest P+T sum) = max(3, 4) = 4.
    assert features[12] == 4


def test_land_counts_and_untapped_subset():
    state = _empty_two_player_state()
    forest = _put_land_on_battlefield(state, "Forest", 0)
    plains = _put_land_on_battlefield(state, "Plains", 0)
    plains.tapped = True
    features = extract_features(state, viewer_id=0)
    # Index 6 = num_lands, 7 = num_untapped_lands.
    assert features[6] == 2
    assert features[7] == 1
    # Index 13 = num_tapped_permanents (the tapped Plains).
    assert features[13] == 1


def test_other_permanents_distinct_from_lands_and_creatures():
    state = _empty_two_player_state()
    _put_land_on_battlefield(state, "Forest", 0)
    _put_on_battlefield(state, "Battlefield Recruit", 0)
    features = extract_features(state, viewer_id=0)
    # No artifacts/enchantments → other_permanents (index 9) is 0.
    assert features[9] == 0


def test_battlefield_aggregation_respects_controller():
    """Creatures controlled by the opponent shouldn't count toward
    viewer's totals."""
    state = _empty_two_player_state()
    _put_on_battlefield(state, "Battlefield Recruit", 1)  # opponent's
    features = extract_features(state, viewer_id=0)
    # Viewer's creature count should be 0.
    assert features[8] == 0
    # Opponent's creature count (start at 16, +8) should be 1.
    assert features[16 + 8] == 1


# ---------- keyword block ----------------------------------------------------


def test_keyword_block_counts_creatures_with_each_keyword():
    """Build a state with creatures we know have known keywords and
    verify the keyword block reflects them."""
    state = _empty_two_player_state()
    # Pick any synthetic creature to verify zero-keyword case first.
    _put_on_battlefield(state, "Battlefield Recruit", 0)
    features = extract_features(state, viewer_id=0)
    # Viewer keyword block starts at 32 (16 + 16). Battlefield Recruit
    # has no relevant evergreen keywords, so all 8 keyword features
    # should be 0 for the viewer.
    for i in range(8):
        assert features[32 + i] == 0


def test_keyword_block_picks_up_added_keywords():
    """Force-add keywords via the GrantKeywords registry-backed UEOT
    path and verify the count increments. This sidesteps needing a
    specific card with the keyword in our test fixtures."""
    from mtg_bot.effects import ApplyEffect, EndOfTurn, GrantKeywords

    state = _empty_two_player_state()
    obj = _put_on_battlefield(state, "Battlefield Recruit", 0)
    ApplyEffect(
        inner=GrantKeywords(keywords=frozenset({"flying", "trample"})),
        ends_at=EndOfTurn(),
    ).resolve(state, 0, (("permanent", obj.id),))
    features = extract_features(state, viewer_id=0)
    # Viewer keyword block: flying = offset 0, trample = offset 5.
    assert features[32 + 0] == 1  # flying
    assert features[32 + 5] == 1  # trample
    # Other keywords still 0.
    assert features[32 + 1] == 0  # first strike


# ---------- global block -----------------------------------------------------


def test_global_stack_size():
    state = _empty_two_player_state()
    features = extract_features(state, viewer_id=0)
    # Global block starts at 48; stack_size is global offset 0.
    assert features[48] == 0
    # Push a fake stack item-equivalent count by fiddling state.stack —
    # the feature just reads len(state.stack), no need for a real one.
    from mtg_bot.game import StackItem
    obj = _put_on_battlefield(state, "Battlefield Recruit", 0)
    state.stack.append(StackItem(source=obj, controller_id=0))
    features = extract_features(state, viewer_id=0)
    assert features[48] == 1


def test_global_is_viewer_turn():
    state = _empty_two_player_state()
    state.active_player_idx = 0
    # Viewer 0 → it's their turn → 1.0.
    features = extract_features(state, viewer_id=0)
    assert features[49] == 1.0
    # Viewer 1 → opponent's turn → 0.0.
    features = extract_features(state, viewer_id=1)
    assert features[49] == 0.0


def test_global_step_index_is_step_ordinal():
    state = _empty_two_player_state()
    state.step = Step.POSTCOMBAT_MAIN
    features = extract_features(state, viewer_id=0)
    expected = STEP_ORDER.index(Step.POSTCOMBAT_MAIN)
    assert features[50] == expected


# ---------- per-turn counters -----------------------------------------------


def test_lands_played_and_spells_cast_this_turn():
    state = _empty_two_player_state()
    state.players[0].lands_played_this_turn = 1
    state.players[0].spells_cast_this_turn = 3
    features = extract_features(state, viewer_id=0)
    # Viewer block: lands_played at 14, spells_cast at 15.
    assert features[14] == 1
    assert features[15] == 3


# ---------- defensive --------------------------------------------------------


def test_singleton_player_returns_zero_features():
    """Defensive path: 1-player state shouldn't crash, just return
    zero features (we don't need MTG to be 1-player)."""
    state = GameState()
    state.players = [Player(id=0)]
    state.step = Step.PRECOMBAT_MAIN
    features = extract_features(state, viewer_id=0)
    np.testing.assert_array_equal(features, np.zeros(FEATURE_DIM, dtype=np.float32))


def test_runs_on_real_setup_game_state():
    """Smoke check on a real engine state (drawn, libraries set up,
    everything wired). No specific assertions — just confirms there's
    no crash on the realistic shape."""
    state = setup_game([RandomAgent(), RandomAgent()], decks=simple_test_decklists(), seed=42,
    )
    features = extract_features(state, viewer_id=0)
    assert features.shape == (FEATURE_DIM,)
    assert np.all(np.isfinite(features))


# ---------- seat-id leakage / mirror symmetry --------------------------------
#
# Self-play has a strong seat-0 win bias (engine-structural — going first
# matters). The value head trains on per-viewer outcome labels, so if the
# feature vector contains anything that lets the model identify "I am the
# player at index 0", it can shortcut to predicting wins from seat id rather
# than learning real position evaluation. These tests pin the symmetry
# property: features must be a function of (state-from-viewer's-perspective)
# only, with no residual signal that distinguishes "I'm seated at index 0"
# from "I'm seated at index 1".


def _populate_side(state, controller_id, *, life, hand, library, graveyard,
                   exile, poison, lands, tapped_lands, creatures,
                   lands_played, spells_cast):
    """Stuff the player at ``controller_id`` and their side of the
    battlefield with the requested counts. Used to build asymmetric
    states + their mirrors."""
    p = state.player_by_id(controller_id)
    p.life = life
    p.poison_counters = poison
    p.lands_played_this_turn = lands_played
    p.spells_cast_this_turn = spells_cast
    p.hand = [
        state.new_object(BASIC_LANDS["Plains"], controller_id, Zone.HAND)
        for _ in range(hand)
    ]
    p.library = [
        state.new_object(BASIC_LANDS["Plains"], controller_id, Zone.LIBRARY)
        for _ in range(library)
    ]
    p.graveyard = [
        state.new_object(BASIC_LANDS["Plains"], controller_id, Zone.GRAVEYARD)
        for _ in range(graveyard)
    ]
    p.exile = [
        state.new_object(BASIC_LANDS["Plains"], controller_id, Zone.EXILE)
        for _ in range(exile)
    ]
    for _ in range(lands):
        _put_land_on_battlefield(state, "Forest", controller_id)
    for i in range(tapped_lands):
        land = _put_land_on_battlefield(state, "Plains", controller_id)
        land.tapped = True
    for name in creatures:
        _put_on_battlefield(state, name, controller_id)


def _build_asymmetric_state(seat0_config, seat1_config, *, active_idx, step):
    """Build a 2-player state where seat 0 / seat 1 are configured per
    the supplied dicts. Returns the GameState."""
    state = _empty_two_player_state()
    state.active_player_idx = active_idx
    state.priority_player_idx = active_idx
    state.step = step
    _populate_side(state, 0, **seat0_config)
    _populate_side(state, 1, **seat1_config)
    return state


def test_self_swap_viewer_blocks_swap_no_global_drift():
    """Single state, swap viewer: viewer/opponent blocks must trade,
    keyword blocks must trade, global block must reflect viewer-relative
    fields correctly."""
    cfg_a = dict(
        life=15, hand=4, library=37, graveyard=2, exile=1, poison=0,
        lands=3, tapped_lands=1, creatures=["Battlefield Recruit"],
        lands_played=1, spells_cast=2,
    )
    cfg_b = dict(
        life=18, hand=6, library=39, graveyard=0, exile=3, poison=2,
        lands=2, tapped_lands=2, creatures=["Trained Soldier", "Trained Soldier"],
        lands_played=0, spells_cast=1,
    )
    state = _build_asymmetric_state(
        cfg_a, cfg_b, active_idx=0, step=Step.PRECOMBAT_MAIN,
    )
    f0 = extract_features(state, viewer_id=0)
    f1 = extract_features(state, viewer_id=1)

    # Per-side blocks: viewer/opponent halves swap.
    np.testing.assert_array_equal(f0[0:16], f1[16:32])
    np.testing.assert_array_equal(f0[16:32], f1[0:16])
    # Keyword blocks (32..48): viewer/opponent halves swap.
    np.testing.assert_array_equal(f0[32:40], f1[40:48])
    np.testing.assert_array_equal(f0[40:48], f1[32:40])
    # Global block: stack_size and step_index are global (must match);
    # is_viewer_turn flips when we swap viewer (active is seat 0).
    assert f0[48] == f1[48]  # stack size — global
    assert f0[49] == 1.0 and f1[49] == 0.0  # is_viewer_turn flips
    assert f0[50] == f1[50]  # step ordinal — global


def test_features_are_invariant_under_seat_swap():
    """The killer test for seat-id leakage: build state S_A where
    seat 0 has config X and seat 1 has config Y; build mirror state
    S_B where seat 0 has config Y and seat 1 has config X (and the
    active player is mirrored too). Then for every viewer:

        extract_features(S_A, viewer=0) == extract_features(S_B, viewer=1)
        extract_features(S_A, viewer=1) == extract_features(S_B, viewer=0)

    If these differ, the feature extractor leaks seat identity —
    something in the pipeline depends on player-index, not on the
    state-from-the-viewer's-perspective."""
    cfg_x = dict(
        life=11, hand=5, library=35, graveyard=4, exile=0, poison=1,
        lands=4, tapped_lands=2,
        creatures=["Battlefield Recruit", "Trained Soldier"],
        lands_played=1, spells_cast=3,
    )
    cfg_y = dict(
        life=19, hand=2, library=40, graveyard=1, exile=2, poison=0,
        lands=1, tapped_lands=3,
        creatures=["Trained Soldier"],
        lands_played=0, spells_cast=0,
    )

    # S_A: seat 0 = X, seat 1 = Y, active = seat 0 (the player with X).
    state_a = _build_asymmetric_state(
        cfg_x, cfg_y, active_idx=0, step=Step.PRECOMBAT_MAIN,
    )
    # S_B: mirror — seat 0 = Y, seat 1 = X, active = seat 1 (still the
    # player with X, who is now in seat 1). The two states are
    # logically identical, only the seat assignment differs.
    state_b = _build_asymmetric_state(
        cfg_y, cfg_x, active_idx=1, step=Step.PRECOMBAT_MAIN,
    )

    # Player-with-config-X sees the same world in both states.
    f_x_in_a = extract_features(state_a, viewer_id=0)  # X is at seat 0 in A
    f_x_in_b = extract_features(state_b, viewer_id=1)  # X is at seat 1 in B
    np.testing.assert_array_equal(f_x_in_a, f_x_in_b)

    # Player-with-config-Y sees the same world in both states.
    f_y_in_a = extract_features(state_a, viewer_id=1)  # Y is at seat 1 in A
    f_y_in_b = extract_features(state_b, viewer_id=0)  # Y is at seat 0 in B
    np.testing.assert_array_equal(f_y_in_a, f_y_in_b)


def test_seat_swap_invariant_with_priority_distinct_from_active():
    """Stack present + priority not on the active player: still must
    be seat-swap invariant. The current feature schema doesn't expose
    priority at all — this test pins that a future addition has to
    keep that property (or pay it back in the symmetry guard)."""
    cfg_x = dict(
        life=14, hand=3, library=36, graveyard=2, exile=1, poison=0,
        lands=2, tapped_lands=1, creatures=["Battlefield Recruit"],
        lands_played=1, spells_cast=1,
    )
    cfg_y = dict(
        life=10, hand=4, library=38, graveyard=0, exile=0, poison=3,
        lands=3, tapped_lands=0, creatures=["Trained Soldier"],
        lands_played=0, spells_cast=2,
    )
    state_a = _build_asymmetric_state(
        cfg_x, cfg_y, active_idx=0, step=Step.PRECOMBAT_MAIN,
    )
    # X is active (seat 0); priority on Y (seat 1) — opponent-priority case.
    state_a.priority_player_idx = 1

    state_b = _build_asymmetric_state(
        cfg_y, cfg_x, active_idx=1, step=Step.PRECOMBAT_MAIN,
    )
    # Mirror: X is still active; X is now at seat 1; priority on Y at seat 0.
    state_b.priority_player_idx = 0

    # Push a fake item on each stack so the global stack_size feature is
    # exercised non-trivially (and identically in both mirrors).
    from mtg_bot.game import StackItem

    obj_a = state_a.battlefield[0]
    state_a.stack.append(StackItem(source=obj_a, controller_id=obj_a.controller_id))
    obj_b = state_b.battlefield[0]
    state_b.stack.append(StackItem(source=obj_b, controller_id=obj_b.controller_id))

    np.testing.assert_array_equal(
        extract_features(state_a, viewer_id=0),
        extract_features(state_b, viewer_id=1),
    )
    np.testing.assert_array_equal(
        extract_features(state_a, viewer_id=1),
        extract_features(state_b, viewer_id=0),
    )


def test_seat_swap_invariant_on_real_setup_game():
    """End-to-end seat-swap invariance on an engine-built state: take
    a ``setup_game`` result, build its mirror by re-seating the two
    players (swap the ``state.players`` list and flip the active /
    priority indices accordingly). Player ids stay the same, so
    ``controller_id`` references on every battlefield object stay
    valid — only the list-position changes. Each viewer must see
    identical features in the mirrored state."""
    state_a = setup_game([RandomAgent(), RandomAgent()], decks=simple_test_decklists(), seed=123,
    )

    import copy

    state_b = copy.deepcopy(state_a)
    # Re-seat: swap the two players in the list. Their ids stay the
    # same, so all controller_id / owner_id references on battlefield
    # objects remain valid. The "seat" is purely the list-index.
    state_b.players = state_b.players[::-1]
    # active_player_idx is a list-index, so it must flip to point at
    # the same player it pointed at before the re-seat.
    state_b.active_player_idx = 1 - state_a.active_player_idx
    state_b.priority_player_idx = 1 - state_a.priority_player_idx

    # Each viewer must see identical features regardless of where they
    # sit in the list. If anything in extract_features depends on the
    # list-index of a player rather than on ids / controller-relative
    # info, this fails.
    np.testing.assert_array_equal(
        extract_features(state_a, viewer_id=0),
        extract_features(state_b, viewer_id=0),
    )
    np.testing.assert_array_equal(
        extract_features(state_a, viewer_id=1),
        extract_features(state_b, viewer_id=1),
    )
