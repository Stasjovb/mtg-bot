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


# ------------------------------------------------------------------------
# recommend_from_state — the real PIMC-driven path
# ------------------------------------------------------------------------


from mtg_bot.agents import RandomAgent  # noqa: E402
from mtg_bot.recommend import recommend_from_state  # noqa: E402
from mtg_bot.simulate import setup_game  # noqa: E402


def _live_state(seed: int = 7):
    """Build a real engine state at turn 1, ready for recommendations."""
    return setup_game(
        [RandomAgent(), RandomAgent()], ["G", "R"], seed=seed,
    )


def test_from_state_returns_pimc_engine_marker():
    state = _live_state()
    result = recommend_from_state(state, n=3)
    assert result["engine"] == "pimc"
    assert isinstance(result["engine_version"], str)


def test_from_state_result_shape_matches_contract():
    """Same top-level keys as recommend_from_snapshot, plus the same
    per-recommendation fields the UI renders against."""
    state = _live_state()
    result = recommend_from_state(state, n=5)
    assert set(result.keys()) == {
        "priority_player_id",
        "recommendations",
        "engine",
        "engine_version",
    }
    for rec in result["recommendations"]:
        for key in (
            "label", "score", "action_type", "source_id",
            "source_name", "scryfall_id", "detail",
        ):
            assert key in rec, f"missing {key!r}"


def test_from_state_returns_at_most_n_recommendations():
    state = _live_state()
    assert len(recommend_from_state(state, n=2)["recommendations"]) <= 2
    assert len(recommend_from_state(state, n=10)["recommendations"]) <= 10


def test_from_state_scores_sum_close_to_one_when_truncated_at_or_above_visit_count():
    """Score is each decision's share of total root visits. When n is
    >= the number of decisions PIMC ranked, the visible scores must
    sum to ~1.0 (modulo float)."""
    state = _live_state()
    result = recommend_from_state(state, n=50)
    recs = result["recommendations"]
    if not recs:
        return
    total = sum(r["score"] for r in recs)
    assert abs(total - 1.0) < 1e-6


def test_from_state_recommendations_are_sorted_by_score_descending():
    state = _live_state()
    recs = recommend_from_state(state, n=10)["recommendations"]
    if len(recs) <= 1:
        return
    scores = [r["score"] for r in recs]
    assert scores == sorted(scores, reverse=True)


def test_from_state_returns_empty_recommendations_when_game_is_over():
    state = _live_state()
    state.players[1].has_lost = True
    state.winner_id = 0
    assert state.is_over()
    result = recommend_from_state(state, n=3)
    assert result["recommendations"] == []
    assert result["engine"] == "pimc"


def test_from_state_does_not_mutate_caller_state():
    """The recommender clones internally; the caller's state must be
    byte-identical after the call (turn, step, hand contents, etc.)."""
    state = _live_state()
    pre_turn = state.turn_number
    pre_step = state.step
    pre_hand = [
        [c.id for c in p.hand] for p in state.players
    ]
    pre_library_lens = [len(p.library) for p in state.players]
    recommend_from_state(state, n=3)
    assert state.turn_number == pre_turn
    assert state.step == pre_step
    post_hand = [[c.id for c in p.hand] for p in state.players]
    post_library_lens = [len(p.library) for p in state.players]
    assert post_hand == pre_hand
    assert post_library_lens == pre_library_lens


def test_from_state_decision_translation_uses_name_to_id():
    """Direct unit test on the decision→rec translation: when a
    PlayLand or CastSpell action references a card whose name appears
    in name_to_id, the resulting recommendation carries that
    scryfall_id. Tested at the translator level rather than through
    PIMC because the latter depends on which decisions PIMC happens
    to expand at the given state."""
    from mtg_bot.actions import CastSpell, PlayLand
    from mtg_bot.recommend import _decision_to_rec

    state = _live_state()
    # Pick any card that's currently in P0's hand.
    sample = state.players[0].hand[0]
    name_to_id = {sample.printing.name: f"sid-{sample.printing.name}"}

    # PlayLand path.
    rec = _decision_to_rec(
        PlayLand(card_id=sample.id), state, name_to_id,
    )
    assert rec is not None
    assert rec["action_type"] == "PlayLand"
    assert rec["source_id"] == sample.id
    assert rec["source_name"] == sample.printing.name
    assert rec["scryfall_id"] == f"sid-{sample.printing.name}"

    # CastSpell path.
    rec = _decision_to_rec(
        CastSpell(card_id=sample.id), state, name_to_id,
    )
    assert rec is not None
    assert rec["action_type"] == "CastSpell"
    assert rec["scryfall_id"] == f"sid-{sample.printing.name}"

    # Unrelated card name → no scryfall id.
    rec = _decision_to_rec(
        PlayLand(card_id=sample.id), state, {"Other": "sid-other"},
    )
    assert rec["scryfall_id"] is None


def test_from_state_pass_priority_label_when_pass_is_legal():
    state = _live_state()
    recs = recommend_from_state(state, n=20)["recommendations"]
    # On a fresh upkeep, PassPriority is the only legal action — it
    # must show up labeled correctly.
    pass_recs = [
        r for r in recs if r["action_type"] == "PassPriority"
    ]
    assert pass_recs, "Pass priority recommendation expected"
    assert pass_recs[0]["label"] == "Pass priority"
    assert pass_recs[0]["source_id"] is None
    assert pass_recs[0]["source_name"] is None


def test_from_state_priority_player_id_matches_active_decision_maker():
    state = _live_state()
    result = recommend_from_state(state, n=3)
    # On turn 1 setup the active player is 0 and they hold priority.
    assert result["priority_player_id"] == 0
