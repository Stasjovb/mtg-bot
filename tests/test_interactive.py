"""Tests for mtg_bot.interactive — InteractiveAgent, session management,
and the three /api/interactive/* Flask routes."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from mtg_bot.interactive import (
    InteractiveAgent,
    InteractiveSession,
    SessionTimeoutError,
    _find_obj,
    _serialize_action,
    create_session,
    get_session,
    _SESSIONS,
    _SESSIONS_LOCK,
)
from mtg_bot.actions import (
    ActivateAbility,
    ActivateStation,
    CastSpell,
    PassPriority,
    PlayLand,
)
from mtg_bot.ui import create_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(n2id=None):
    return InteractiveAgent(n2id or {})


def _respond_in_thread(agent, response, delay=0.01):
    """Submit a response from a background thread after a small delay."""
    def _go():
        import time
        time.sleep(delay)
        agent.submit_response(response)
    t = threading.Thread(target=_go, daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------------
# _serialize_action
# ---------------------------------------------------------------------------

class TestSerializeAction:
    def _minimal_state(self):
        """A mock state with an empty battlefield, stack, and players."""
        state = MagicMock()
        state.battlefield = []
        state.stack = []
        state.players = []
        return state

    def test_pass_priority(self):
        state = self._minimal_state()
        result = _serialize_action(state, PassPriority(), {})
        assert result["type"] == "pass"
        assert "Pass" in result["label"]

    def test_play_land(self):
        from mtg_bot.game import GameState, Zone
        from mtg_bot.simulate import setup_game
        from mtg_bot.agents import RandomAgent
        from mtg_bot.legal import legal_actions

        state = setup_game([RandomAgent(), RandomAgent()], colors=["G", "R"], seed=0)
        player = state.players[0]
        for obj in player.hand:
            if obj.printing.is_land:
                action = PlayLand(card_id=obj.id)
                result = _serialize_action(state, action, {})
                assert result["type"] == "play_land"
                assert obj.printing.name in result["label"]
                return
        pytest.skip("no land in hand at seed 0")

    def test_cast_spell(self):
        from mtg_bot.simulate import setup_game
        from mtg_bot.agents import RandomAgent

        state = setup_game([RandomAgent(), RandomAgent()], colors=["G", "R"], seed=0)
        for obj in state.players[0].hand:
            if not obj.printing.is_land:
                action = CastSpell(card_id=obj.id)
                result = _serialize_action(state, action, {})
                assert result["type"] == "cast_spell"
                assert "Cast" in result["label"]
                return
        pytest.skip("no non-land in hand at seed 0")

    def test_cast_spell_warp_suffix(self):
        from mtg_bot.simulate import setup_game
        from mtg_bot.agents import RandomAgent

        state = setup_game([RandomAgent(), RandomAgent()], colors=["G", "R"], seed=0)
        for obj in state.players[0].hand:
            if not obj.printing.is_land:
                action = CastSpell(card_id=obj.id, use_warp=True)
                result = _serialize_action(state, action, {})
                assert "[Warp]" in result["label"]
                return
        pytest.skip("no non-land in hand")

    def test_unknown_action(self):
        from mtg_bot.actions import Action
        from dataclasses import dataclass

        state = self._minimal_state()

        @dataclass(frozen=True)
        class Weird(Action):
            pass

        result = _serialize_action(state, Weird(), {})
        assert result["type"] == "unknown"


# ---------------------------------------------------------------------------
# InteractiveAgent — decision methods
# ---------------------------------------------------------------------------

class TestInteractiveAgent:
    """Each test starts the agent's blocking method in a thread, then
    submits a response from the main thread and asserts the return value."""

    def test_choose_action_pass(self):
        from mtg_bot.simulate import setup_game
        from mtg_bot.agents import RandomAgent

        state = setup_game([RandomAgent(), RandomAgent()], colors=["G", "R"], seed=0)
        legal = [PassPriority()]
        agent = _make_agent()
        result_holder = []
        t = threading.Thread(
            target=lambda: result_holder.append(agent.choose_action(state, 0, legal)),
            daemon=True,
        )
        t.start()
        # Give the agent time to block
        import time; time.sleep(0.05)
        pending = agent.get_pending()
        assert pending is not None
        assert pending["type"] == "choose_action"
        agent.submit_response({"idx": 0})
        t.join(timeout=2)
        assert not t.is_alive()
        assert isinstance(result_holder[0], PassPriority)

    def test_choose_action_out_of_range(self):
        from mtg_bot.simulate import setup_game
        from mtg_bot.agents import RandomAgent

        state = setup_game([RandomAgent(), RandomAgent()], colors=["G", "R"], seed=0)
        legal = [PassPriority()]
        agent = _make_agent()
        result_holder = []
        exc_holder = []

        def _run():
            try:
                result_holder.append(agent.choose_action(state, 0, legal))
            except Exception as e:
                exc_holder.append(e)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        import time; time.sleep(0.05)
        agent.submit_response({"idx": 99})
        t.join(timeout=2)
        assert exc_holder, "expected ValueError for out-of-range idx"

    def test_declare_attackers(self):
        from mtg_bot.simulate import setup_game
        from mtg_bot.agents import RandomAgent

        state = setup_game([RandomAgent(), RandomAgent()], colors=["G", "R"], seed=0)
        eligible = list(state.battlefield)[:1] if state.battlefield else []
        agent = _make_agent()
        result_holder = []
        t = threading.Thread(
            target=lambda: result_holder.append(
                agent.declare_attackers(state, 0, eligible)
            ),
            daemon=True,
        )
        t.start()
        import time; time.sleep(0.05)
        agent.submit_response({"ids": []})
        t.join(timeout=2)
        assert result_holder[0] == []

    def test_declare_blockers(self):
        from mtg_bot.simulate import setup_game
        from mtg_bot.agents import RandomAgent

        state = setup_game([RandomAgent(), RandomAgent()], colors=["G", "R"], seed=0)
        agent = _make_agent()
        result_holder = []
        t = threading.Thread(
            target=lambda: result_holder.append(
                agent.declare_blockers(state, 0, [], [])
            ),
            daemon=True,
        )
        t.start()
        import time; time.sleep(0.05)
        agent.submit_response({"assignments": {}})
        t.join(timeout=2)
        assert result_holder[0] == {}

    def test_choose_target_by_index(self):
        from mtg_bot.simulate import setup_game
        from mtg_bot.agents import RandomAgent

        state = setup_game([RandomAgent(), RandomAgent()], colors=["G", "R"], seed=0)
        legal_targets = [("player", 1)]
        agent = _make_agent()
        result_holder = []
        t = threading.Thread(
            target=lambda: result_holder.append(
                agent.choose_target(state, 0, legal_targets)
            ),
            daemon=True,
        )
        t.start()
        import time; time.sleep(0.05)
        agent.submit_response({"idx": 0})
        t.join(timeout=2)
        assert result_holder[0] == ("player", 1)

    def test_choose_target_empty_returns_none(self):
        from mtg_bot.simulate import setup_game
        from mtg_bot.agents import RandomAgent

        state = setup_game([RandomAgent(), RandomAgent()], colors=["G", "R"], seed=0)
        agent = _make_agent()
        result = agent.choose_target(state, 0, [])
        assert result is None

    def test_choose_discard(self):
        from mtg_bot.simulate import setup_game
        from mtg_bot.agents import RandomAgent

        state = setup_game([RandomAgent(), RandomAgent()], colors=["G", "R"], seed=0)
        hand_ids = [obj.id for obj in state.players[0].hand]
        if not hand_ids:
            pytest.skip("empty hand")
        agent = _make_agent()
        result_holder = []
        t = threading.Thread(
            target=lambda: result_holder.append(agent.choose_discard(state, 0, hand_ids)),
            daemon=True,
        )
        t.start()
        import time; time.sleep(0.05)
        agent.submit_response({"id": hand_ids[0]})
        t.join(timeout=2)
        assert result_holder[0] == hand_ids[0]

    def test_choose_surveil_keep(self):
        from mtg_bot.simulate import setup_game
        from mtg_bot.agents import RandomAgent

        state = setup_game([RandomAgent(), RandomAgent()], colors=["G", "R"], seed=0)
        top_id = state.players[0].library[0].id if state.players[0].library else 1
        agent = _make_agent()
        result_holder = []
        t = threading.Thread(
            target=lambda: result_holder.append(agent.choose_surveil(state, 0, top_id)),
            daemon=True,
        )
        t.start()
        import time; time.sleep(0.05)
        agent.submit_response({"mill": False})
        t.join(timeout=2)
        assert result_holder[0] is False

    def test_choose_mode(self):
        from mtg_bot.simulate import setup_game
        from mtg_bot.agents import RandomAgent

        state = setup_game([RandomAgent(), RandomAgent()], colors=["G", "R"], seed=0)
        agent = _make_agent()
        result_holder = []
        t = threading.Thread(
            target=lambda: result_holder.append(
                agent.choose_mode(state, 0, ["Mode A", "Mode B"])
            ),
            daemon=True,
        )
        t.start()
        import time; time.sleep(0.05)
        agent.submit_response({"idx": 1})
        t.join(timeout=2)
        assert result_holder[0] == 1

    def test_choose_modes_multi(self):
        from mtg_bot.simulate import setup_game
        from mtg_bot.agents import RandomAgent

        state = setup_game([RandomAgent(), RandomAgent()], colors=["G", "R"], seed=0)
        agent = _make_agent()
        result_holder = []
        t = threading.Thread(
            target=lambda: result_holder.append(
                agent.choose_modes(state, 0, ["A", "B", "C"])
            ),
            daemon=True,
        )
        t.start()
        import time; time.sleep(0.05)
        agent.submit_response({"indices": [0, 2]})
        t.join(timeout=2)
        assert result_holder[0] == [0, 2]

    def test_choose_pay_shock_life_yes(self):
        from mtg_bot.simulate import setup_game
        from mtg_bot.agents import RandomAgent

        state = setup_game([RandomAgent(), RandomAgent()], colors=["G", "R"], seed=0)
        agent = _make_agent()
        result_holder = []
        t = threading.Thread(
            target=lambda: result_holder.append(
                agent.choose_pay_shock_life(state, 0, 2)
            ),
            daemon=True,
        )
        t.start()
        import time; time.sleep(0.05)
        agent.submit_response({"yes": True})
        t.join(timeout=2)
        assert result_holder[0] is True

    def test_choose_x_clamped(self):
        from mtg_bot.simulate import setup_game
        from mtg_bot.agents import RandomAgent

        state = setup_game([RandomAgent(), RandomAgent()], colors=["G", "R"], seed=0)
        agent = _make_agent()
        result_holder = []
        t = threading.Thread(
            target=lambda: result_holder.append(
                agent.choose_x(state, 0, "Fireball", 5)
            ),
            daemon=True,
        )
        t.start()
        import time; time.sleep(0.05)
        agent.submit_response({"value": 99})  # over upper_bound → clamped to 5
        t.join(timeout=2)
        assert result_holder[0] == 5

    def test_choose_mana_color_valid(self):
        from mtg_bot.simulate import setup_game
        from mtg_bot.agents import RandomAgent

        state = setup_game([RandomAgent(), RandomAgent()], colors=["G", "R"], seed=0)
        agent = _make_agent()
        result_holder = []
        t = threading.Thread(
            target=lambda: result_holder.append(
                agent.choose_mana_color(state, 0, ["G", "R", "B"])
            ),
            daemon=True,
        )
        t.start()
        import time; time.sleep(0.05)
        agent.submit_response({"color": "R"})
        t.join(timeout=2)
        assert result_holder[0] == "R"

    def test_choose_mana_color_invalid_fallback(self):
        from mtg_bot.simulate import setup_game
        from mtg_bot.agents import RandomAgent

        state = setup_game([RandomAgent(), RandomAgent()], colors=["G", "R"], seed=0)
        agent = _make_agent()
        result_holder = []
        t = threading.Thread(
            target=lambda: result_holder.append(
                agent.choose_mana_color(state, 0, ["G", "R"])
            ),
            daemon=True,
        )
        t.start()
        import time; time.sleep(0.05)
        agent.submit_response({"color": "W"})  # not in options → fallback to G
        t.join(timeout=2)
        assert result_holder[0] == "G"

    def test_choose_yes_no(self):
        from mtg_bot.simulate import setup_game
        from mtg_bot.agents import RandomAgent

        state = setup_game([RandomAgent(), RandomAgent()], colors=["G", "R"], seed=0)
        agent = _make_agent()
        result_holder = []
        t = threading.Thread(
            target=lambda: result_holder.append(
                agent.choose_yes_no(state, 0, "Do something optional?")
            ),
            daemon=True,
        )
        t.start()
        import time; time.sleep(0.05)
        agent.submit_response({"yes": False})
        t.join(timeout=2)
        assert result_holder[0] is False

    def test_choose_devour_lands_empty(self):
        from mtg_bot.simulate import setup_game
        from mtg_bot.agents import RandomAgent

        state = setup_game([RandomAgent(), RandomAgent()], colors=["G", "R"], seed=0)
        agent = _make_agent()
        result_holder = []
        t = threading.Thread(
            target=lambda: result_holder.append(
                agent.choose_devour_lands(state, 0, [])
            ),
            daemon=True,
        )
        t.start()
        import time; time.sleep(0.05)
        agent.submit_response({"ids": []})
        t.join(timeout=2)
        assert result_holder[0] == []

    def test_choose_card_from_library_decline(self):
        from mtg_bot.simulate import setup_game
        from mtg_bot.agents import RandomAgent

        state = setup_game([RandomAgent(), RandomAgent()], colors=["G", "R"], seed=0)
        lib_ids = [obj.id for obj in state.players[0].library[:3]]
        agent = _make_agent()
        result_holder = []
        t = threading.Thread(
            target=lambda: result_holder.append(
                agent.choose_card_from_library(state, 0, lib_ids)
            ),
            daemon=True,
        )
        t.start()
        import time; time.sleep(0.05)
        agent.submit_response({"decline": True})
        t.join(timeout=2)
        assert result_holder[0] is None

    def test_choose_card_from_library_empty_returns_none(self):
        from mtg_bot.simulate import setup_game
        from mtg_bot.agents import RandomAgent

        state = setup_game([RandomAgent(), RandomAgent()], colors=["G", "R"], seed=0)
        agent = _make_agent()
        # Empty option list → immediately returns None without blocking
        result = agent.choose_card_from_library(state, 0, [])
        assert result is None

    def test_get_pending_returns_none_initially(self):
        agent = _make_agent()
        assert agent.get_pending() is None


# ---------------------------------------------------------------------------
# InteractiveSession thread-safety
# ---------------------------------------------------------------------------

class TestInteractiveSession:
    def _make_session(self):
        agent = _make_agent()
        t = threading.Thread(target=lambda: None, daemon=True)
        return InteractiveSession(
            session_id="test-abc",
            human_player_id=0,
            human_agent=agent,
            game_thread=t,
        )

    def test_update_and_get_snapshot(self):
        session = self._make_session()
        assert session.get_state()["snapshot"] is None
        session.update_snapshot({"turn_number": 3, "step": "draw"})
        state = session.get_state()
        assert state["snapshot"]["turn_number"] == 3

    def test_mark_over(self):
        session = self._make_session()
        assert not session.is_over
        session.mark_over({"winner_id": 1, "is_draw": False, "turn_number": 5})
        assert session.is_over
        state = session.get_state()
        assert state["result"]["winner_id"] == 1

    def test_human_player_id_in_state(self):
        session = self._make_session()
        assert session.get_state()["human_player_id"] == 0


# ---------------------------------------------------------------------------
# Flask routes — /api/interactive/*
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


class TestInteractiveRoutes:
    def test_new_game_returns_session_id(self, client):
        resp = client.post(
            "/api/interactive/new",
            json={"seed": 0, "c1": "G", "c2": "R", "human_player": 0},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "session_id" in data
        assert data["human_player_id"] == 0

    def test_new_game_bad_color(self, client):
        resp = client.post(
            "/api/interactive/new",
            json={"seed": 0, "c1": "X", "c2": "R", "human_player": 0},
        )
        assert resp.status_code == 400

    def test_new_game_bad_human_player(self, client):
        resp = client.post(
            "/api/interactive/new",
            json={"seed": 0, "c1": "G", "c2": "R", "human_player": 2},
        )
        assert resp.status_code == 400

    def test_state_returns_404_for_unknown(self, client):
        resp = client.get("/api/interactive/state/nonexistent")
        assert resp.status_code == 404

    def test_action_returns_404_for_unknown(self, client):
        resp = client.post(
            "/api/interactive/action/nonexistent",
            json={"response": {"idx": 0}},
        )
        assert resp.status_code == 404

    def test_action_missing_response_field(self, client):
        # Create a valid session first
        resp = client.post(
            "/api/interactive/new",
            json={"seed": 0, "c1": "G", "c2": "R", "human_player": 0},
        )
        session_id = resp.get_json()["session_id"]
        resp2 = client.post(
            f"/api/interactive/action/{session_id}",
            json={},  # missing 'response'
        )
        assert resp2.status_code == 400

    def test_state_returns_human_player_id(self, client):
        resp = client.post(
            "/api/interactive/new",
            json={"seed": 0, "c1": "G", "c2": "R", "human_player": 1},
        )
        session_id = resp.get_json()["session_id"]
        import time; time.sleep(0.1)  # let the game thread start
        resp2 = client.get(f"/api/interactive/state/{session_id}")
        assert resp2.status_code == 200
        data = resp2.get_json()
        assert data["human_player_id"] == 1

    def test_full_turn_cycle(self, client):
        """Start a game, poll state, submit actions until it's the bot's turn."""
        import time
        resp = client.post(
            "/api/interactive/new",
            json={"seed": 42, "c1": "R", "c2": "G", "human_player": 0,
                  "max_turns": 5},
        )
        assert resp.status_code == 200
        session_id = resp.get_json()["session_id"]

        # Poll until a pending decision appears or the game ends.
        # Allow up to 5 seconds for the game thread to reach the first decision.
        deadline = time.time() + 5
        last_state = None
        while time.time() < deadline:
            state_resp = client.get(f"/api/interactive/state/{session_id}")
            last_state = state_resp.get_json()
            if last_state.get("pending") or last_state.get("is_over"):
                break
            time.sleep(0.1)

        assert last_state is not None
        # Either the game ended (very short game) or we have a pending decision
        assert last_state.get("is_over") or last_state.get("pending") is not None

    def test_action_after_game_over_rejected(self, client):
        """Mark a session as over manually and verify the action endpoint rejects."""
        import time
        # Start a max_turns=1 game so it ends quickly
        resp = client.post(
            "/api/interactive/new",
            json={"seed": 0, "c1": "G", "c2": "R", "human_player": 0,
                  "max_turns": 1},
        )
        session_id = resp.get_json()["session_id"]

        # Poll until over
        deadline = time.time() + 8
        while time.time() < deadline:
            sr = client.get(f"/api/interactive/state/{session_id}").get_json()
            if sr.get("is_over"):
                break
            pending = sr.get("pending")
            if pending:
                # Pass priority to let the game proceed
                client.post(
                    f"/api/interactive/action/{session_id}",
                    json={"response": {"idx": 0}},
                )
            time.sleep(0.1)

        resp2 = client.post(
            f"/api/interactive/action/{session_id}",
            json={"response": {"idx": 0}},
        )
        assert resp2.status_code == 400
