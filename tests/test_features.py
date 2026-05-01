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
    state = setup_game(
        [RandomAgent(), RandomAgent()], ["G", "R"], seed=42,
    )
    a = extract_features(state, viewer_id=0)
    b = extract_features(state, viewer_id=0)
    np.testing.assert_array_equal(a, b)


def test_extract_does_not_mutate_state():
    state = setup_game(
        [RandomAgent(), RandomAgent()], ["G", "R"], seed=7,
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
    state = setup_game(
        [RandomAgent(), RandomAgent()], ["G", "R"], seed=42,
    )
    features = extract_features(state, viewer_id=0)
    assert features.shape == (FEATURE_DIM,)
    assert np.all(np.isfinite(features))
