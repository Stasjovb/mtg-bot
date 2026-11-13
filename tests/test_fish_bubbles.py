"""Forgetful Fish speech bubbles: a shared action (scry to the top or bottom,
reorder, shuffle) is recorded as its player's bubble at its own log line.
Other formats record none, and the bubbles of one step are the ones whose
log lines fall inside that step."""

from __future__ import annotations

from mtg_bot.effects.generic.card_flow import ShuffleYourLibrary
from mtg_bot.effects.generic.library_lookat import Scry, _scry_phrase
from mtg_bot.game import LogBuffer, Zone
from mtg_bot.interactive import InteractiveSession
from mtg_bot.serialize import serialize_state
from mtg_bot.ui import create_app

from tests._fish_helpers import make_state, place


class _ChooseBottom:
    """Agent stub: bottoms the cards named in ``ids``."""

    def __init__(self, ids):
        self.ids = set(ids)

    def choose_surveil(self, state, pid, card_id):
        return card_id in self.ids

    def choose_scry(self, state, pid, card_id):
        return card_id in self.ids


# ---------------------------------------------------------------------------
# The log buffer
# ---------------------------------------------------------------------------

def test_bubble_is_recorded_at_its_own_log_line():
    log = LogBuffer()
    log.bubbles_enabled = True
    log.append("first")
    log.append_with_bubble("P0 shuffles their library", 0, "shuffled")
    assert list(log) == ["first", "P0 shuffles their library"]
    assert log.bubbles == [(1, 0, "shuffled")]


def test_no_bubbles_when_off_or_silent():
    log = LogBuffer()
    log.append_with_bubble("off", 1, "shuffled")
    assert list(log) == ["off"] and log.bubbles == []
    log.bubbles_enabled = True
    log.enabled = False
    log.append_with_bubble("silent", 1, "shuffled")
    assert list(log) == ["off"] and log.bubbles == []


def test_scry_phrases():
    assert _scry_phrase(2, 0) == "scried to top"
    assert _scry_phrase(2, 2) == "scried to bottom"
    assert _scry_phrase(3, 1) == "scried 1 to bottom"


# ---------------------------------------------------------------------------
# The effects
# ---------------------------------------------------------------------------

def test_scry_with_a_card_bottomed_bubbles_the_count():
    state = make_state()
    state.log.bubbles_enabled = True
    top = [place(state, 0, "Island", Zone.LIBRARY) for _ in range(3)]
    state.players[0].agent = _ChooseBottom([top[0].id])
    line = len(state.log)
    Scry(amount=2, bottom_choice=True).resolve(state, 0)
    assert "1 to the bottom" in state.log[line]
    assert state.log.bubbles == [(line, 0, "scried 1 to bottom")]


def test_scry_keeping_everything_on_top_bubbles_top():
    state = make_state()
    state.log.bubbles_enabled = True
    for _ in range(2):
        place(state, 0, "Island", Zone.LIBRARY)
    line = len(state.log)
    Scry(amount=2).resolve(state, 0)
    assert "kept all on top" in state.log[line]
    assert state.log.bubbles == [(line, 0, "scried to top")]


def test_shuffle_bubbles_the_shuffling_player():
    state = make_state()
    state.log.bubbles_enabled = True
    place(state, 1, "Island", Zone.LIBRARY)
    line = len(state.log)
    ShuffleYourLibrary().resolve(state, 1)
    assert state.log.bubbles == [(line, 1, "shuffled")]


def test_standard_game_records_no_bubbles():
    state = make_state()
    state.log.bubbles_enabled = False
    for _ in range(2):
        place(state, 0, "Island", Zone.LIBRARY)
    Scry(amount=2).resolve(state, 0)
    ShuffleYourLibrary().resolve(state, 0)
    assert state.log.bubbles == []
    assert any("scries" in line for line in state.log)


# ---------------------------------------------------------------------------
# What the website sees
# ---------------------------------------------------------------------------

def test_serialized_state_lists_the_bubbles():
    state = make_state()
    state.log.bubbles_enabled = True
    place(state, 0, "Island", Zone.LIBRARY)
    line = len(state.log)
    ShuffleYourLibrary().resolve(state, 0)
    snap = serialize_state(state)
    assert snap["bubbles"] == [{"log_index": line, "player_id": 0, "text": "shuffled"}]


def test_interactive_snapshot_bubbles_only_the_latest_step():
    session = InteractiveSession(
        session_id="t", human_player_id=0, human_agent=None, game_thread=None,
    )
    bubble = {"log_index": 0, "player_id": 0, "text": "shuffled"}
    snap = {"log": ["P0 shuffles their library"], "bubbles": [bubble]}
    session.update_snapshot(snap)
    assert snap["bubbles_since_last"] == [bubble]
    # The same log length (a re-poll of this step) keeps the bubble.
    again = {"log": ["P0 shuffles their library"], "bubbles": [bubble]}
    session.update_snapshot(again)
    assert again["bubbles_since_last"] == [bubble]
    # A later step with no bubbles of its own shows none.
    later = {"log": ["P0 shuffles their library", "P1 passes"], "bubbles": [bubble]}
    session.update_snapshot(later)
    assert later["bubbles_since_last"] == []


def test_replay_steps_carry_the_bubbles_of_their_own_lines():
    client = create_app().test_client()
    data = client.get(
        "/api/play?format=forgetful_fish&list=placeholder&seed=4&max_turns=8",
    ).get_json()
    steps = 0
    while (r := client.get(f"/api/snapshot/{data['game_id']}/{steps}")).status_code == 200:
        snap = r.get_json()
        before = len(snap["log"]) - len(snap["log_since_last"])
        for b in snap["bubbles_since_last"]:
            assert before <= b["log_index"] < len(snap["log"])
        steps += 1
    assert steps > 0
