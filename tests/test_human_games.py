"""Training rows from recorded games: a record replays to the same game, its
human decisions become rows (two per decision, one per viewer), and the rows
go into a shard the trainer reads."""

from __future__ import annotations

import json

import numpy as np
import pytest

from mtg_bot.agents import RandomAgent
from mtg_bot.game_records import RECORD_VERSION
from mtg_bot.interactive import InteractiveAgent, bot_rng
from mtg_bot.simulate import simulate_game
from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE
from mtg_bot.training.human_games import (
    ReplayMismatch,
    _outcome,
    records_to_shard,
    replay_record,
)

SEED = 11
MAX_TURNS = 20


def _first_answer(pending):
    kind = pending["type"]
    if kind == "choose_action":
        return {"idx": 0}
    if kind == "declare_attackers":
        return {"ids": []}
    if kind == "declare_blockers":
        return {"assignments": {}}
    if kind == "choose_yes_no":
        return {"yes": False}  # keep the hand
    raise AssertionError(f"the script has no answer for {kind}")


class _ScriptedPerson(InteractiveAgent):
    """A person who answers the first option, and writes each answer down the
    way a game record does."""

    def __init__(self, seat, log):
        super().__init__({})
        self._seat = seat
        self._log = log
        self._asks = 0

    def _ask(self, state, pending):
        self._asks += 1
        response = _first_answer(pending)
        self._log.append({
            "seat": self._seat, "seq": self._asks,
            "type": pending["type"], "response": response,
        })
        return response


@pytest.fixture(scope="module")
def played():
    """One game: a scripted person in seat 0 against the seeded bot."""
    log: list[dict] = []
    agents = [_ScriptedPerson(0, log), RandomAgent(rng=bot_rng(SEED))]
    state = simulate_game(
        agents=agents, colors=["G", "R"], seed=SEED, max_turns=MAX_TURNS,
        starting_player_idx=0,
    )
    record = {
        "version": RECORD_VERSION,
        "format": "standard", "seed": SEED, "max_turns": MAX_TURNS,
        "colors": ["G", "R"], "decks": None, "starting_player_idx": 0,
        "opponent": "bot", "human_seats": [0],
        "result": {"winner_id": state.winner_id}, "decisions": log,
    }
    return record


def test_replay_reproduces_the_game_and_keeps_two_rows_per_decision(played):
    rows, winner = replay_record(played, {})
    assert winner == played["result"]["winner_id"]
    assert len(played["decisions"]) > 0
    assert len(rows) == 2 * len(played["decisions"])
    assert {row["viewer"] for row in rows} == {0, 1}


def test_a_person_choice_is_a_one_hot_policy_row_for_their_own_view(played):
    rows, _ = replay_record(played, {})
    own = [r for r in rows if r["viewer"] == 0 and r["policy"].sum() > 0.5]
    assert own, "the person made at least one choice the policy can express"
    for row in own:
        assert row["policy"].shape == (ACTION_VOCAB_SIZE,)
        assert row["policy"].sum() == pytest.approx(1.0)
        assert row["mask"][int(np.argmax(row["policy"]))]
    for row in rows:
        if row["viewer"] == 1:
            assert row["policy"].sum() == 0.0


def test_a_record_that_does_not_match_the_engine_is_refused(played):
    tampered = {**played, "decisions": [
        {**played["decisions"][0], "seq": 99}, *played["decisions"][1:],
    ]}
    with pytest.raises(ReplayMismatch):
        replay_record(tampered, {})


def test_a_wrong_winner_in_the_record_is_refused(played):
    wrong = 1 - played["result"]["winner_id"] if played["result"]["winner_id"] is not None else 0
    with pytest.raises(ReplayMismatch):
        replay_record({**played, "result": {"winner_id": wrong}}, {})


def test_records_become_a_shard_the_trainer_can_read(played, tmp_path):
    record_path = tmp_path / "game.json"
    record_path.write_text(json.dumps(played), encoding="utf-8")
    out = tmp_path / "human.npz"
    count = records_to_shard([record_path], out, {})
    assert count == 2 * len(played["decisions"])
    with np.load(out) as shard:
        assert shard["features"].shape == (count, shard["features"].shape[1])
        assert shard["outcomes"].shape == (count,)
        assert shard["policy_targets"].shape == (count, ACTION_VOCAB_SIZE)
        assert shard["action_masks"].shape == (count, ACTION_VOCAB_SIZE)
        assert shard["structured_token_type"].shape[0] == count
        assert set(shard["game_ids"].tolist()) == {0}


def test_a_record_with_no_person_gives_nothing_to_learn(played, tmp_path):
    bot_only = {**played, "human_seats": [], "decisions": []}
    path = tmp_path / "bot.json"
    path.write_text(json.dumps(bot_only), encoding="utf-8")
    with pytest.raises(ValueError):
        records_to_shard([path], tmp_path / "none.npz", {})


def test_outcomes_are_from_each_viewers_side():
    assert _outcome(0, 0) == 1.0 and _outcome(0, 1) == -1.0
    assert _outcome(1, 0) == -1.0 and _outcome(1, 1) == 1.0
    assert _outcome(None, 0) == 0.0
