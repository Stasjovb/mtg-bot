"""Tests for the recommendation stub + contract."""

from __future__ import annotations

from mtg_bot.recommend import recommend_from_snapshot


def _base_snapshot(**overrides) -> dict:
    """Minimum snapshot shape the recommender expects. Override specific
    fields in tests."""
    snap = {
        "turn_number": 1,
        "active_player_idx": 0,
        "priority_player_idx": 0,
        "step": "precombat_main",
        "is_over": False,
        "stack": [],
        "players": [
            {"id": 0, "hand": [], "lands_played_this_turn": 0},
            {"id": 1, "hand": [], "lands_played_this_turn": 0},
        ],
    }
    snap.update(overrides)
    return snap


def test_result_shape_is_frozen_contract():
    """Result always has these top-level keys regardless of input."""
    result = recommend_from_snapshot(_base_snapshot())
    assert set(result.keys()) == {
        "priority_player_id",
        "recommendations",
        "engine",
        "engine_version",
    }
    assert result["engine"] == "stub"
    assert isinstance(result["engine_version"], str)


def test_each_recommendation_has_contract_fields():
    snap = _base_snapshot(players=[
        {"id": 0, "hand": [{
            "id": 10, "name": "Forest",
            "type_line": "Basic Land — Forest",
            "mana_cost": None, "scryfall_id": "abc",
        }], "lands_played_this_turn": 0},
        {"id": 1, "hand": [], "lands_played_this_turn": 0},
    ])
    for rec in recommend_from_snapshot(snap)["recommendations"]:
        for key in ("label", "score", "action_type", "source_id",
                    "source_name", "scryfall_id", "detail"):
            assert key in rec, f"recommendation missing {key!r}"


def test_pass_priority_is_always_included_when_game_is_live():
    result = recommend_from_snapshot(_base_snapshot())
    labels = [r["label"] for r in result["recommendations"]]
    assert "Pass priority" in labels


def test_no_recommendations_when_game_is_over():
    snap = _base_snapshot(is_over=True)
    result = recommend_from_snapshot(snap)
    assert result["recommendations"] == []


def test_lands_in_hand_appear_as_play_land_at_sorcery_timing():
    snap = _base_snapshot(players=[
        {"id": 0, "hand": [
            {"id": 10, "name": "Forest", "type_line": "Basic Land — Forest",
             "mana_cost": None, "scryfall_id": "abc"},
        ], "lands_played_this_turn": 0},
        {"id": 1, "hand": [], "lands_played_this_turn": 0},
    ])
    recs = recommend_from_snapshot(snap, n=10)["recommendations"]
    play = next(r for r in recs if r["action_type"] == "PlayLand")
    assert play["label"] == "Play Forest"
    assert play["source_id"] == 10
    assert play["scryfall_id"] == "abc"


def test_play_land_suppressed_if_already_played_one_this_turn():
    """Basic MTG rule the stub should know about — one land per turn."""
    snap = _base_snapshot(players=[
        {"id": 0, "hand": [
            {"id": 10, "name": "Forest", "type_line": "Basic Land — Forest",
             "mana_cost": None, "scryfall_id": "abc"},
        ], "lands_played_this_turn": 1},
        {"id": 1, "hand": [], "lands_played_this_turn": 0},
    ])
    recs = recommend_from_snapshot(snap, n=10)["recommendations"]
    assert not any(r["action_type"] == "PlayLand" for r in recs)


def test_spells_in_hand_appear_as_cast_at_sorcery_timing():
    snap = _base_snapshot(players=[
        {"id": 0, "hand": [
            {"id": 20, "name": "Goblin Runner", "type_line": "Creature",
             "mana_cost": "{R}", "scryfall_id": "def"},
        ], "lands_played_this_turn": 0},
        {"id": 1, "hand": [], "lands_played_this_turn": 0},
    ])
    recs = recommend_from_snapshot(snap, n=10)["recommendations"]
    cast = next(r for r in recs if r["action_type"] == "CastSpell")
    assert cast["label"] == "Cast Goblin Runner"
    assert cast["source_name"] == "Goblin Runner"
    assert cast["detail"] == "{R}"


def test_spells_suppressed_outside_sorcery_timing():
    snap = _base_snapshot(step="declare_attackers", players=[
        {"id": 0, "hand": [
            {"id": 20, "name": "Goblin Runner", "type_line": "Creature",
             "mana_cost": "{R}", "scryfall_id": "def"},
        ], "lands_played_this_turn": 0},
        {"id": 1, "hand": [], "lands_played_this_turn": 0},
    ])
    recs = recommend_from_snapshot(snap, n=10)["recommendations"]
    assert not any(r["action_type"] == "CastSpell" for r in recs)


def test_spells_suppressed_when_stack_is_nonempty():
    snap = _base_snapshot(
        stack=[{"name": "Something on stack"}],
        players=[
            {"id": 0, "hand": [
                {"id": 20, "name": "Goblin Runner", "type_line": "Creature",
                 "mana_cost": "{R}", "scryfall_id": "def"},
            ], "lands_played_this_turn": 0},
            {"id": 1, "hand": [], "lands_played_this_turn": 0},
        ],
    )
    recs = recommend_from_snapshot(snap, n=10)["recommendations"]
    assert not any(r["action_type"] == "CastSpell" for r in recs)


def test_n_limits_number_of_recommendations():
    snap = _base_snapshot(players=[
        {"id": 0, "hand": [
            {"id": i, "name": f"Card {i}", "type_line": "Creature",
             "mana_cost": "{1}", "scryfall_id": None}
            for i in range(10)
        ], "lands_played_this_turn": 0},
        {"id": 1, "hand": [], "lands_played_this_turn": 0},
    ])
    assert len(recommend_from_snapshot(snap, n=3)["recommendations"]) == 3
    assert len(recommend_from_snapshot(snap, n=5)["recommendations"]) == 5


def test_priority_player_id_reflects_the_snapshot():
    snap = _base_snapshot(priority_player_idx=1)
    assert recommend_from_snapshot(snap)["priority_player_id"] == 1


def test_stub_scores_are_all_zero_by_contract():
    """The stub doesn't evaluate — real engine replaces these. UI should
    still render the labels correctly even when every score is 0."""
    snap = _base_snapshot(players=[
        {"id": 0, "hand": [
            {"id": 20, "name": "Goblin Runner", "type_line": "Creature",
             "mana_cost": "{R}", "scryfall_id": "def"},
        ], "lands_played_this_turn": 0},
        {"id": 1, "hand": [], "lands_played_this_turn": 0},
    ])
    for rec in recommend_from_snapshot(snap, n=10)["recommendations"]:
        assert rec["score"] == 0.0
