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


def _untapped_lands(n: int) -> list[dict]:
    """Helper: produce ``n`` untapped basic lands for the player's
    battlefield. Used by tests that need the player to have enough
    mana for the recommend stub to consider a spell castable."""
    return [
        {"id": 1000 + i, "name": "Forest",
         "type_line": "Basic Land — Forest", "tapped": False}
        for i in range(n)
    ]


def test_spells_in_hand_appear_as_cast_at_sorcery_timing():
    snap = _base_snapshot(players=[
        {"id": 0, "hand": [
            {"id": 20, "name": "Goblin Runner", "type_line": "Creature",
             "mana_cost": "{R}", "scryfall_id": "def"},
        ], "lands_played_this_turn": 0,
         "battlefield": _untapped_lands(1)},
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
        ], "lands_played_this_turn": 0,
         "battlefield": _untapped_lands(1)},
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
            ], "lands_played_this_turn": 0,
             "battlefield": _untapped_lands(1)},
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
        ], "lands_played_this_turn": 0,
         "battlefield": _untapped_lands(1)},
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
        ], "lands_played_this_turn": 0,
         "battlefield": _untapped_lands(1)},
        {"id": 1, "hand": [], "lands_played_this_turn": 0},
    ])
    for rec in recommend_from_snapshot(snap, n=10)["recommendations"]:
        assert rec["score"] == 0.0


def test_spells_filtered_when_player_lacks_mana():
    """Turn 1 with no untapped mana: a 3-cost spell (e.g. Banishing
    Light at {2}{W}) must NOT be recommended — the stub had no mana
    check and the UI was offering illegal plays."""
    snap = _base_snapshot(players=[
        {"id": 0, "hand": [
            {"id": 30, "name": "Banishing Light", "type_line": "Enchantment",
             "mana_cost": "{2}{W}", "scryfall_id": "bl"},
        ], "lands_played_this_turn": 0,
         "battlefield": []},
        {"id": 1, "hand": [], "lands_played_this_turn": 0},
    ])
    recs = recommend_from_snapshot(snap, n=10)["recommendations"]
    assert not any(r["source_name"] == "Banishing Light" for r in recs)


def test_spells_allowed_when_enough_untapped_lands():
    """3 untapped lands → the 3-cost spell is castable."""
    snap = _base_snapshot(players=[
        {"id": 0, "hand": [
            {"id": 30, "name": "Banishing Light", "type_line": "Enchantment",
             "mana_cost": "{2}{W}", "scryfall_id": "bl"},
        ], "lands_played_this_turn": 1,
         "battlefield": _untapped_lands(3)},
        {"id": 1, "hand": [], "lands_played_this_turn": 0},
    ])
    recs = recommend_from_snapshot(snap, n=10)["recommendations"]
    assert any(r["source_name"] == "Banishing Light" for r in recs)


def test_tapped_lands_do_not_count_toward_available_mana():
    snap = _base_snapshot(players=[
        {"id": 0, "hand": [
            {"id": 30, "name": "Goblin Runner", "type_line": "Creature",
             "mana_cost": "{R}", "scryfall_id": "gr"},
        ], "lands_played_this_turn": 1,
         "battlefield": [
            {"id": 1000, "name": "Mountain",
             "type_line": "Basic Land — Mountain", "tapped": True},
         ]},
        {"id": 1, "hand": [], "lands_played_this_turn": 0},
    ])
    recs = recommend_from_snapshot(snap, n=10)["recommendations"]
    assert not any(r["action_type"] == "CastSpell" for r in recs)


def test_floating_mana_pool_counts_toward_available_mana():
    """Even with all lands tapped, mana already in the pool should
    let a spell with matching CMC be recommended."""
    snap = _base_snapshot(players=[
        {"id": 0, "hand": [
            {"id": 30, "name": "Goblin Runner", "type_line": "Creature",
             "mana_cost": "{R}", "scryfall_id": "gr"},
        ], "lands_played_this_turn": 1,
         "battlefield": [],
         "mana_pool": [{"color": "R", "spend_restriction": None}]},
        {"id": 1, "hand": [], "lands_played_this_turn": 0},
    ])
    recs = recommend_from_snapshot(snap, n=10)["recommendations"]
    assert any(r["source_name"] == "Goblin Runner" for r in recs)


def test_sorcery_speed_actions_suppressed_when_not_active_player():
    """If priority is with the non-active player during the active
    player's main phase, no sorcery-speed plays should be recommended.
    Banishing Light @ {2}{W}, P1 has plenty of mana, but P0 is the
    active player — P1 can only cast instants here."""
    snap = _base_snapshot(active_player_idx=0, priority_player_idx=1,
                          players=[
        {"id": 0, "hand": [], "lands_played_this_turn": 1,
         "battlefield": []},
        {"id": 1, "hand": [
            {"id": 30, "name": "Banishing Light", "type_line": "Enchantment",
             "mana_cost": "{2}{W}", "scryfall_id": "bl"},
        ], "lands_played_this_turn": 0,
         "battlefield": _untapped_lands(3)},
    ])
    recs = recommend_from_snapshot(snap, n=10)["recommendations"]
    assert not any(r["action_type"] == "CastSpell" for r in recs)
    assert not any(r["action_type"] == "PlayLand" for r in recs)


# ------------------------------------------------------------------------
# recommend_from_state — the real PIMC-driven path
# ------------------------------------------------------------------------


from mtg_bot.agents import RandomAgent  # noqa: E402
from mtg_bot.recommend import recommend_from_state  # noqa: E402
from mtg_bot.simulate import setup_game  # noqa: E402
from tests._test_decks import simple_test_decklists  # noqa: E402


def _live_state(seed: int = 7):
    """Build a real engine state at turn 1, ready for recommendations."""
    return setup_game([RandomAgent(), RandomAgent()], decks=simple_test_decklists(), seed=seed,
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


# ---------------------------------------------------------------------
# _decision_to_rec: the activated-ability / station / combat /
# detail-string branches. These don't reliably surface through PIMC at
# a turn-1 state, so they're tested directly at the translator level —
# the same precedent as test_from_state_decision_translation_uses_name_to_id.
# ---------------------------------------------------------------------


def test_decision_to_rec_cast_spell_warp_and_kicker_detail():
    """CastSpell's optional detail subtitle concatenates mana cost,
    'warp', and 'kicker' bits with a separator."""
    from mtg_bot.actions import CastSpell
    from mtg_bot.recommend import _decision_to_rec

    state = _live_state()
    sample = state.players[0].hand[0]
    rec = _decision_to_rec(
        CastSpell(card_id=sample.id, use_warp=True, kicked=True),
        state, {},
    )
    assert rec is not None
    assert rec["action_type"] == "CastSpell"
    assert "warp" in rec["detail"]
    assert "kicker" in rec["detail"]


def test_decision_to_rec_activate_ability():
    from mtg_bot.actions import ActivateAbility
    from mtg_bot.recommend import _decision_to_rec

    state = _live_state()
    # Put a real card onto the battlefield so _find_card_by_id resolves.
    perm = state.players[0].hand[0]
    state.battlefield.append(perm)
    rec = _decision_to_rec(
        ActivateAbility(source_id=perm.id, ability_index=2),
        state, {perm.printing.name: "sid-x"},
    )
    assert rec["action_type"] == "ActivateAbility"
    assert rec["source_id"] == perm.id
    assert rec["source_name"] == perm.printing.name
    assert rec["scryfall_id"] == "sid-x"
    assert rec["detail"] == "ability 2"
    assert rec["label"] == f"Activate ability of {perm.printing.name}"


def test_decision_to_rec_activate_station():
    from mtg_bot.actions import ActivateStation
    from mtg_bot.recommend import _decision_to_rec

    state = _live_state()
    ship = state.players[0].hand[0]
    crew = state.players[0].hand[1]
    state.battlefield.extend([ship, crew])
    rec = _decision_to_rec(
        ActivateStation(spacecraft_id=ship.id, crew_id=crew.id),
        state, {ship.printing.name: "sid-ship"},
    )
    assert rec["action_type"] == "ActivateStation"
    assert rec["source_id"] == ship.id
    assert rec["source_name"] == ship.printing.name
    assert rec["scryfall_id"] == "sid-ship"
    assert crew.printing.name in rec["detail"]
    assert ship.printing.name in rec["label"]
    assert crew.printing.name in rec["label"]


def test_decision_to_rec_declare_attackers_plural_and_zero():
    from mtg_bot.actions import DeclareAttackers
    from mtg_bot.recommend import _decision_to_rec

    state = _live_state()
    rec0 = _decision_to_rec(DeclareAttackers(attacker_ids=[]), state, {})
    assert rec0["action_type"] == "DeclareAttackers"
    assert rec0["label"] == "Attack with no creatures"

    rec1 = _decision_to_rec(DeclareAttackers(attacker_ids=[1]), state, {})
    assert rec1["label"] == "Attack with 1 creature"

    rec2 = _decision_to_rec(DeclareAttackers(attacker_ids=[1, 2]), state, {})
    assert rec2["label"] == "Attack with 2 creatures"


def test_decision_to_rec_declare_blockers_plural_and_zero():
    from mtg_bot.actions import DeclareBlockers
    from mtg_bot.recommend import _decision_to_rec

    state = _live_state()
    rec0 = _decision_to_rec(DeclareBlockers(assignments={}), state, {})
    assert rec0["action_type"] == "DeclareBlockers"
    assert rec0["label"] == "Don't block"

    rec1 = _decision_to_rec(
        DeclareBlockers(assignments={1: [2]}), state, {},
    )
    assert rec1["label"] == "Assign 1 blocker"

    rec2 = _decision_to_rec(
        DeclareBlockers(assignments={1: [2], 3: [4]}), state, {},
    )
    assert rec2["label"] == "Assign 2 blockers"


def test_decision_to_rec_unknown_action_type_returns_none():
    """Unrecognized action types must translate to None so the caller
    filters them out (an unlabeled action never reaches the UI)."""
    from mtg_bot.recommend import _decision_to_rec

    class MysteryAction:
        pass

    state = _live_state()
    assert _decision_to_rec(MysteryAction(), state, {}) is None


def test_decision_to_rec_missing_card_falls_back_to_id_label():
    """When the referenced card id isn't on the board, the label
    fails soft with a #id placeholder rather than crashing."""
    from mtg_bot.actions import CastSpell, PlayLand
    from mtg_bot.recommend import _decision_to_rec, _find_card_by_id

    state = _live_state()
    assert _find_card_by_id(state, 987654321) is None
    rec = _decision_to_rec(PlayLand(card_id=987654321), state, {})
    assert rec["source_name"] == "#987654321"
    assert rec["label"] == "Play #987654321"
    rec2 = _decision_to_rec(CastSpell(card_id=987654321), state, {})
    assert rec2["source_name"] == "#987654321"


def test_find_card_by_id_resolves_battlefield_then_hand():
    from mtg_bot.recommend import _find_card_by_id

    state = _live_state()
    hand_card = state.players[0].hand[0]
    assert _find_card_by_id(state, hand_card.id) is hand_card

    bf_card = state.players[1].hand[0]
    state.battlefield.append(bf_card)
    assert _find_card_by_id(state, bf_card.id) is bf_card


def test_approx_cmc_handles_x_and_symbols():
    """_approx_cmc: empty/None cost is 0, X counts as 0, generic
    digits sum, every other pip counts as 1."""
    from mtg_bot.recommend import _approx_cmc

    assert _approx_cmc(None) == 0
    assert _approx_cmc("") == 0
    assert _approx_cmc("{X}{R}") == 1  # X->0, R->1
    assert _approx_cmc("{2}{W}{W}") == 4
    assert _approx_cmc("{10}") == 10
