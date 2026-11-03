"""Forgetful Fish in the web UI: format switch, decklist check, hidden bot
hand, and the human decisions Fish needs (mulligans, Brainstorm)."""

from __future__ import annotations

import html
import threading
import time

import pytest

from mtg_bot.actions import PassPriority
from mtg_bot.agents import RandomAgent
from mtg_bot.formats import FORGETFUL_FISH
from mtg_bot.formats.forgetful_fish import (
    default_decklist_path,
    default_decklist_text,
    placeholder_decklist_text,
)
from mtg_bot.interactive import InteractiveAgent, create_session
from mtg_bot.serialize import serialize_state
from mtg_bot.simulate import setup_game
from mtg_bot.ui import create_app, decklist_report

FISH_LIKE = ["Island"] * 40 + ["Brainstorm"] * 20 + ["Memory Lapse"] * 20


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


# ---------------------------------------------------------------------
# Saved decklist
# ---------------------------------------------------------------------

def test_saved_list_is_the_placeholder_until_a_real_list_exists(tmp_path):
    (tmp_path / "placeholder_decklist.txt").write_text("40 Island\n")
    assert default_decklist_path(tmp_path).name == "placeholder_decklist.txt"
    assert default_decklist_text(tmp_path) == "40 Island\n"
    (tmp_path / "decklist.txt").write_text("80 Island\n")
    assert default_decklist_path(tmp_path).name == "decklist.txt"
    assert default_decklist_text(tmp_path) == "80 Island\n"


def test_shipped_placeholder_is_a_playable_80_card_list():
    report = decklist_report(placeholder_decklist_text())
    assert report["total"] == 80
    assert report["unknown"] == []
    assert report["unreadable"] == []
    assert report["tutors"] == []


# ---------------------------------------------------------------------
# The website offers Forgetful Fish only (Standard is cut from the UI)
# ---------------------------------------------------------------------

def test_home_page_offers_forgetful_fish_only(client):
    page = client.get("/").get_data(as_text=True)
    assert "Standard (colors)" not in page
    assert "standard-only" not in page
    assert 'name="c1"' not in page and 'id="iplay-my-color"' not in page
    assert 'name="format" value="forgetful_fish"' in page
    assert 'id="iplay-format" value="forgetful_fish"' in page
    assert 'id="iplay-fish" class="fish-panel"' in page


# ---------------------------------------------------------------------
# /api/decklist/check
# ---------------------------------------------------------------------

def test_check_empty_list_returns_the_saved_list(client):
    r = client.post("/api/decklist/check", json={})
    assert r.status_code == 200
    data = r.get_json()
    assert data["is_default"] is True
    assert data["text"] == default_decklist_text()
    assert data["unreadable"] == [] and data["tutors"] == []


def test_check_can_load_the_placeholder(client):
    data = client.post(
        "/api/decklist/check", json={"which": "placeholder"},
    ).get_json()
    assert data["is_default"] is True
    assert data["text"] == placeholder_decklist_text()
    assert data["total"] == 80 and data["unknown"] == []


def test_saved_list_with_unplayable_cards_says_so(client):
    unknown = decklist_report(default_decklist_text())["unknown"]
    r = client.post("/api/interactive/new", json={"format": "forgetful_fish"})
    if unknown:
        assert r.status_code == 400
        body = html.unescape(r.get_data(as_text=True))
        assert "the saved list isn't playable yet" in body
        assert unknown[0] in body
    else:  # every card implemented: the saved list just plays
        assert r.status_code == 200


def test_watch_mode_rejects_an_unknown_list_choice(client):
    r = client.get("/api/play?format=forgetful_fish&list=mine")
    assert r.status_code == 400


def test_check_reports_unknown_unreadable_and_tutors(client):
    text = "36 island\n4 Demonic Tutor\n2 Not A Real Card\n0 Brainstorm\n"
    data = client.post(
        "/api/decklist/check", json={"decklist": text},
    ).get_json()
    assert data["is_default"] is False
    assert "text" not in data
    assert data["counts"] == {"Island": 36, "Demonic Tutor": 4}
    assert data["total"] == 40
    assert data["unknown"] == ["Not A Real Card"]
    assert data["unreadable"] == ["0 Brainstorm"]
    assert data["tutors"] == ["Demonic Tutor"]


# ---------------------------------------------------------------------
# /api/interactive/new and /api/play
# ---------------------------------------------------------------------

def _wait_pending(client, sid, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        s = client.get(f"/api/interactive/state/{sid}").get_json()
        if s.get("pending") or s.get("is_over"):
            return s
        time.sleep(0.05)
    raise AssertionError("no pending decision")


def test_interactive_fish_game_hides_the_bot_hand(client):
    r = client.post("/api/interactive/new", json={
        "seed": 1, "human_player": 0, "format": "forgetful_fish",
        "decklist": placeholder_decklist_text(),
    })
    assert r.status_code == 200
    data = r.get_json()
    assert data["format"] == "forgetful_fish"
    s = _wait_pending(client, data["session_id"])
    # First decision: the human's own mulligan, with the hand listed.
    assert s["pending"]["type"] == "choose_yes_no"
    assert s["pending"]["prompt"].startswith("Mulligan this hand")
    snap = s["snapshot"]
    assert snap["game_format"] == "forgetful_fish"
    assert snap["shared_library"] and snap["shared_graveyard"]
    bot = snap["players"][1]
    assert bot["hand"] == [] and bot["hand_size"] == 7
    assert len(snap["players"][0]["hand"]) == 7


def test_interactive_can_show_the_bot_hand(client):
    data = client.post("/api/interactive/new", json={
        "seed": 1, "human_player": 0, "format": "forgetful_fish",
        "decklist": placeholder_decklist_text(),
        "show_bot_hand": True,
    }).get_json()
    s = _wait_pending(client, data["session_id"])
    assert len(s["snapshot"]["players"][1]["hand"]) == 7


def test_interactive_pasted_list_is_used(client):
    data = client.post("/api/interactive/new", json={
        "seed": 2, "human_player": 1, "format": "forgetful_fish",
        "decklist": "80 Island",
    }).get_json()
    s = _wait_pending(client, data["session_id"])
    names = {c["name"] for p in s["snapshot"]["players"] for c in p["hand"]}
    assert names == {"Island"}


@pytest.mark.parametrize("decklist, message", [
    ("76 Island\n4 Demonic Tutor", "tutors are not allowed: Demonic Tutor"),
    ("78 Island\n2 Nope Card", "unknown cards: Nope Card"),
    ("0 Island", "unreadable lines: 0 Island"),
    ("# only a comment", "the list is empty"),
])
def test_interactive_rejects_a_bad_list(client, decklist, message):
    r = client.post("/api/interactive/new", json={
        "format": "forgetful_fish", "decklist": decklist,
    })
    assert r.status_code == 400
    assert message in r.get_data(as_text=True)


def test_unknown_format_is_a_400(client):
    r = client.post("/api/interactive/new", json={"format": "vintage"})
    assert r.status_code == 400
    assert "unknown game format" in r.get_data(as_text=True)
    r = client.get("/api/play?format=vintage")
    assert r.status_code == 400


def test_standard_interactive_game_still_works(client):
    data = client.post("/api/interactive/new", json={
        "seed": 0, "human_player": 0,
    }).get_json()
    assert data["format"] == "standard"
    s = _wait_pending(client, data["session_id"])
    assert s["snapshot"]["game_format"] == "standard"
    assert s["snapshot"]["shared_library"] is False


def test_watch_mode_plays_a_fish_game(client):
    r = client.get("/api/play?format=forgetful_fish&list=placeholder&seed=4&max_turns=8")
    assert r.status_code == 200
    data = r.get_json()
    assert data["format"] == "forgetful_fish"
    snap = client.get(f"/api/snapshot/{data['game_id']}/0").get_json()
    assert snap["game_format"] == "forgetful_fish"
    assert snap["players"][0]["library_size"] == snap["players"][1]["library_size"]


# ---------------------------------------------------------------------
# InteractiveAgent decisions used by Fish
# ---------------------------------------------------------------------

def _answering(agent, response):
    """Answer ``agent``'s next question with ``response`` from a thread."""
    def run():
        for _ in range(400):
            if agent.get_pending() is not None:
                agent.submit_response(response)
                return
            time.sleep(0.01)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def _fish_state(agent):
    return setup_game(
        [agent, RandomAgent()], decks=[FISH_LIKE], seed=0,
        game_format=FORGETFUL_FISH, enable_mulligans=False,
    )


def test_choose_card_from_hand_pick_decline_and_empty():
    agent = InteractiveAgent({})
    state = _fish_state(agent)
    ids = [c.id for c in state.players[0].hand]
    _answering(agent, {"id": ids[2]})
    assert agent.choose_card_from_hand(state, 0, ids) == ids[2]
    _answering(agent, {"decline": True})
    assert agent.choose_card_from_hand(state, 0, ids) is None
    assert agent.choose_card_from_hand(state, 0, []) is None


def test_choose_card_from_hand_names_the_resolving_spell():
    agent = InteractiveAgent({})
    state = _fish_state(agent)
    state.resolving_spell = state.players[0].hand[0]
    ids = [c.id for c in state.players[0].hand]
    prompts = []

    def run():
        for _ in range(400):
            p = agent.get_pending()
            if p is not None:
                prompts.append(p["prompt"])
                agent.submit_response({"id": ids[0]})
                return
            time.sleep(0.01)

    threading.Thread(target=run, daemon=True).start()
    agent.choose_card_from_hand(state, 0, ids)
    name = state.players[0].hand[0].printing.name
    assert prompts == [f"{name}: choose a card from your hand"]


@pytest.mark.parametrize("deck, free", [
    (["Island"] * 80, True), (FISH_LIKE, None),
])
def test_choose_mulligan_says_whether_it_is_free(deck, free):
    agent = InteractiveAgent({})
    state = setup_game(
        [agent, RandomAgent()], decks=[deck], seed=0,
        game_format=FORGETFUL_FISH, enable_mulligans=False,
    )
    hand = list(state.players[0].hand)
    prompts = []

    def run():
        for _ in range(400):
            p = agent.get_pending()
            if p is not None:
                prompts.append(p["prompt"])
                agent.submit_response({"yes": True})
                return
            time.sleep(0.01)

    threading.Thread(target=run, daemon=True).start()
    assert agent.choose_mulligan(state, 0, hand, 0) is True
    is_free = FORGETFUL_FISH.is_free_mulligan(hand)
    if free is not None:
        assert is_free is free
    expected = "free" if is_free else "you would put 1 card(s) on the bottom"
    assert expected in prompts[0]
    assert hand[0].printing.name in prompts[0]


def test_choose_mulligan_is_not_free_after_a_regular_mulligan():
    # 7 lands would be free, but not after a regular mulligan.
    agent = InteractiveAgent({})
    state = setup_game(
        [agent, RandomAgent()], decks=[["Island"] * 80], seed=0,
        game_format=FORGETFUL_FISH, enable_mulligans=False,
    )
    hand = list(state.players[0].hand)
    prompts = []

    def run():
        for _ in range(400):
            p = agent.get_pending()
            if p is not None:
                prompts.append(p["prompt"])
                agent.submit_response({"yes": False})
                return
            time.sleep(0.01)

    threading.Thread(target=run, daemon=True).start()
    assert agent.choose_mulligan(state, 0, hand, 1) is False
    assert "7 lands; you would put 2 card(s) on the bottom" in prompts[0]


def _wait_agent_pending(agent, seq_after=0):
    end = time.time() + 5
    while time.time() < end:
        p = agent.get_pending()
        if p is not None and p["seq"] > seq_after:
            return p
        time.sleep(0.01)
    raise AssertionError("no pending decision")


def test_each_decision_carries_a_new_seq():
    agent = InteractiveAgent({})
    state = _fish_state(agent)
    results = []

    def run():
        results.append(agent.choose_action(state, 0, [PassPriority()]))
        results.append(agent.choose_action(state, 0, [PassPriority()]))

    threading.Thread(target=run, daemon=True).start()
    first = _wait_agent_pending(agent)
    assert agent.submit_response({"idx": 0}, seq=first["seq"]) is True
    second = _wait_agent_pending(agent, first["seq"])
    assert second["seq"] == first["seq"] + 1
    assert agent.submit_response({"idx": 0}, seq=second["seq"]) is True


def test_an_answer_to_an_earlier_decision_is_dropped():
    # The website crash: a second click on a just-played bounce land sent
    # its option index (1) to the next decision, whose only option was
    # "Pass priority" -> "choose_action idx 1 out of range 0..0".
    agent = InteractiveAgent({})
    state = _fish_state(agent)
    results = []
    threading.Thread(
        target=lambda: results.append(agent.choose_action(state, 0, [PassPriority()])),
        daemon=True,
    ).start()
    p = _wait_agent_pending(agent)
    assert agent.submit_response({"idx": 1}, seq=p["seq"] - 1) is False
    assert agent.get_pending()["seq"] == p["seq"]  # still waiting
    assert agent.submit_response({"idx": 0}, seq=p["seq"]) is True
    end = time.time() + 5
    while not results and time.time() < end:
        time.sleep(0.01)
    assert results == [PassPriority()]


def test_answer_without_seq_still_works_and_none_pending_rejects_seq():
    agent = InteractiveAgent({})
    assert agent.submit_response({"idx": 0}, seq=1) is False  # nothing pending
    assert agent.submit_response({"idx": 0}) is True


def test_action_endpoint_rejects_a_stale_answer(client):
    session = create_session(
        seed=0, colors=["U", "U"], human_player_id=0, n2id={},
        enrich_fn=serialize_state, max_turns=3, decks=[FISH_LIKE],
        game_format=FORGETFUL_FISH,
    )
    p = _wait_agent_pending(session.human_agent)  # the mulligan question
    url = f"/api/interactive/action/{session.session_id}"
    stale = client.post(url, json={"response": {"yes": True}, "seq": p["seq"] - 1})
    assert stale.status_code == 409 and stale.get_json()["stale"] is True
    assert session.human_agent.get_pending()["seq"] == p["seq"]
    ok = client.post(url, json={"response": {"yes": False}, "seq": p["seq"]})
    assert ok.status_code == 200


@pytest.mark.parametrize("returned", ["Island", "Izzet Boilerworks"])
def test_bounce_land_asks_which_land_to_return_not_to_sacrifice(returned):
    # "Return a land you control": any of them, the bounce land itself
    # included; the opponent's lands are not offered.
    from tests._fish_helpers import make_state, place, printing

    agent = InteractiveAgent({})
    state = make_state(agent0=agent)
    mine = {"Island": place(state, 0, "Island"),
            "Izzet Boilerworks": place(state, 0, "Izzet Boilerworks")}
    place(state, 1, "Island")
    effect = printing("Izzet Boilerworks").triggered_abilities[0].effect
    done = []
    threading.Thread(
        target=lambda: done.append(effect.resolve(state, 0)), daemon=True,
    ).start()
    p = _wait_agent_pending(agent)
    assert p["type"] == "choose_sacrifice"
    assert p["prompt"] == "Choose a land you control to return to your hand"
    assert {o["id"] for o in p["objects"]} == {o.id for o in mine.values()}
    agent.submit_response({"id": mine[returned].id}, seq=p["seq"])
    end = time.time() + 5
    while not done and time.time() < end:
        time.sleep(0.01)
    assert mine[returned] in state.player_by_id(0).hand
    assert mine[returned] not in state.battlefield
    other = next(o for n, o in mine.items() if n != returned)
    assert other in state.battlefield


def test_choose_bottom_validates_and_fills_picks():
    agent = InteractiveAgent({})
    state = _fish_state(agent)
    hand = list(state.players[0].hand)
    ids = [c.id for c in hand]
    _answering(agent, {"ids": [ids[1], ids[3]]})
    assert agent.choose_bottom(state, 0, hand, 2) == [ids[1], ids[3]]
    # Duplicates and foreign ids are dropped; missing picks come from the
    # end of the hand.
    _answering(agent, {"ids": [ids[0], ids[0], 999999]})
    assert agent.choose_bottom(state, 0, hand, 2) == [ids[0], ids[-1]]
    _answering(agent, {"ids": [ids[2], ids[4], ids[5]]})
    assert agent.choose_bottom(state, 0, hand, 2) == [ids[2], ids[4]]


def test_create_session_with_a_fish_decklist():
    session = create_session(
        seed=0, colors=["U", "U"], human_player_id=0, n2id={},
        enrich_fn=serialize_state, max_turns=5, decks=[FISH_LIKE],
        game_format=FORGETFUL_FISH,
    )
    end = time.time() + 10
    while session.human_agent.get_pending() is None and time.time() < end:
        time.sleep(0.05)
    snap = session.get_state()["snapshot"]
    assert snap["game_format"] == "forgetful_fish"
    p0, p1 = snap["players"]
    assert p0["library_size"] == p1["library_size"] == 66
