"""Edge / error-path coverage for ``mtg_bot.interactive``.

The existing ``test_interactive.py`` covers the common decision
methods. This file fills the remaining gaps: the object-lookup
helpers' battlefield/stack/not-found branches, the
``_serialize_action`` activated-ability / station / free / kicked
flavors, the ``_ask`` timeout path, the validation / decline /
fallback branches of several ``choose_*`` methods, and
``_evict_oldest``.

Every test drives a real decision method to a concrete return value
(or asserts the specific raised exception); none are import-only or
assertion-free.
"""

from __future__ import annotations

import threading
import time

import pytest

from mtg_bot.actions import (
    ActivateAbility,
    ActivateStation,
    CastSpell,
)
from mtg_bot.agents import RandomAgent
from mtg_bot.interactive import (
    DECISION_TIMEOUT,
    InteractiveAgent,
    InteractiveSession,
    SessionTimeoutError,
    _bf_opt,
    _card_opt,
    _evict_oldest,
    _find_obj,
    _serialize_action,
    _SESSIONS,
    _SESSION_LIMIT,
)
from mtg_bot.simulate import setup_game
from tests._test_decks import simple_test_decklists


def _state(seed: int = 0):
    return setup_game(
        [RandomAgent(), RandomAgent()],
        decks=simple_test_decklists(), seed=seed,
    )


def _drive(agent: InteractiveAgent, method_name: str, args, response):
    """Call ``agent.<method_name>(*args)`` on a background thread,
    submit ``response``, and return the method's result."""
    out: list = []
    err: list = []

    def _go():
        try:
            out.append(getattr(agent, method_name)(*args))
        except Exception as exc:  # noqa: BLE001
            err.append(exc)

    t = threading.Thread(target=_go, daemon=True)
    t.start()
    # Wait until the agent is actually blocked on a pending decision.
    for _ in range(200):
        if agent.get_pending() is not None:
            break
        time.sleep(0.005)
    agent.submit_response(response)
    t.join(timeout=3)
    assert not t.is_alive(), f"{method_name} did not return"
    if err:
        raise err[0]
    return out[0]


# ---------------------------------------------------------------------
# _find_obj / _card_opt / _bf_opt lookup branches
# ---------------------------------------------------------------------


def test_find_obj_battlefield_and_stack_and_miss():
    s = _state()
    # battlefield branch
    bf_card = s.players[0].hand.pop()
    s.battlefield.append(bf_card)
    assert _find_obj(s, bf_card.id) is bf_card
    # not-found branch
    assert _find_obj(s, 123456789) is None


def test_find_obj_resolves_stack_source():
    """A spell/ability on the stack is reachable by its source id —
    the last fallback branch of _find_obj."""
    from mtg_bot.game import StackItem

    s = _state()
    card = s.players[0].hand.pop()
    s.stack.append(StackItem(source=card, controller_id=0))
    assert _find_obj(s, card.id) is card


def test_card_opt_missing_id_placeholder():
    s = _state()
    opt = _card_opt(s, 999999, {})
    assert opt == {"id": 999999, "name": "Card #999999", "scryfall_id": None}


def test_card_opt_resolves_name_and_scryfall_id():
    s = _state()
    card = s.players[0].hand[0]
    opt = _card_opt(s, card.id, {card.printing.name: "sid-1"})
    assert opt["name"] == card.printing.name
    assert opt["scryfall_id"] == "sid-1"


def test_bf_opt_missing_id_placeholder():
    s = _state()
    opt = _bf_opt(s, 888888, {})
    assert opt == {
        "id": 888888, "name": "Permanent #888888", "scryfall_id": None,
    }


def test_bf_opt_resolves_battlefield_card():
    s = _state()
    card = s.players[0].hand.pop()
    s.battlefield.append(card)
    opt = _bf_opt(s, card.id, {card.printing.name: "sid-bf"})
    assert opt["name"] == card.printing.name
    assert opt["scryfall_id"] == "sid-bf"


# ---------------------------------------------------------------------
# _serialize_action: free / kicked / activate / station branches
# ---------------------------------------------------------------------


def test_serialize_cast_free_suffix():
    s = _state()
    card = s.players[0].hand[0]
    r = _serialize_action(s, CastSpell(card_id=card.id, cast_for_free=True), {})
    assert "[Free]" in r["label"]
    assert r["cast_for_free"] is True


def test_serialize_cast_kicked_suffix():
    s = _state()
    card = s.players[0].hand[0]
    r = _serialize_action(s, CastSpell(card_id=card.id, kicked=True), {})
    assert "[Kicked]" in r["label"]
    assert r["kicked"] is True


def test_serialize_cast_mana_cost_suffix():
    """When no flag is set, the suffix falls back to the printed mana
    cost string."""
    s = _state()
    card = next(
        c for c in s.players[0].hand if c.printing.mana_cost_str
    )
    r = _serialize_action(s, CastSpell(card_id=card.id), {})
    assert f"[{card.printing.mana_cost_str}]" in r["label"]


def test_serialize_activate_ability_on_battlefield():
    s = _state()
    card = s.players[0].hand.pop()
    s.battlefield.append(card)
    r = _serialize_action(
        s, ActivateAbility(source_id=card.id, ability_index=0),
        {card.printing.name: "sid-a"},
    )
    assert r["type"] == "activate"
    assert r["source_id"] == card.id
    assert r["name"] == card.printing.name
    assert r["scryfall_id"] == "sid-a"


def test_serialize_activate_ability_missing_source():
    s = _state()
    r = _serialize_action(
        s, ActivateAbility(source_id=777777, ability_index=3), {},
    )
    assert r["type"] == "activate"
    assert r["name"] == "Permanent #777777"
    assert "Ability 3" in r["label"]
    assert r["scryfall_id"] is None


def test_serialize_activate_station_missing_objects():
    s = _state()
    r = _serialize_action(
        s, ActivateStation(spacecraft_id=555111, crew_id=555222), {},
    )
    assert r["type"] == "station"
    assert "Spacecraft #555111" in r["label"]
    assert "Creature #555222" in r["label"]


# ---------------------------------------------------------------------
# _ask timeout
# ---------------------------------------------------------------------


def test_ask_times_out(monkeypatch):
    """When no response arrives within DECISION_TIMEOUT, _ask raises
    SessionTimeoutError and flips the timed_out flag. We patch the
    timeout to ~0 so the test is fast."""
    monkeypatch.setattr("mtg_bot.interactive.DECISION_TIMEOUT", 0.05)
    agent = InteractiveAgent({})
    s = _state()
    with pytest.raises(SessionTimeoutError):
        agent.choose_yes_no(s, 0, "proceed?")
    assert agent.timed_out is True


# ---------------------------------------------------------------------
# choose_* validation / decline / fallback branches
# ---------------------------------------------------------------------


def test_choose_target_player_and_stack_labels_then_decline():
    s = _state()
    agent = InteractiveAgent({})
    legal = [("player", 1), ("stack", 0)]
    # stack[0] absent -> "Stack item 0" label path; decline -> None
    result = _drive(
        agent, "choose_target", (s, 0, legal), {"decline": True},
    )
    assert result is None


def test_choose_target_index_out_of_range_raises():
    s = _state()
    agent = InteractiveAgent({})
    legal = [("player", 1)]
    with pytest.raises(ValueError, match="choose_target idx"):
        _drive(agent, "choose_target", (s, 0, legal), {"idx": 9})


def test_choose_target_permanent_label():
    s = _state()
    card = s.players[0].hand.pop()
    s.battlefield.append(card)
    agent = InteractiveAgent({})
    legal = [("permanent", card.id)]
    result = _drive(agent, "choose_target", (s, 0, legal), {"idx": 0})
    assert result == ("permanent", card.id)


def test_choose_mode_out_of_range_raises():
    s = _state()
    agent = InteractiveAgent({})
    with pytest.raises(ValueError, match="choose_mode idx"):
        _drive(agent, "choose_mode", (s, 0, ["a", "b"]), {"idx": 5})


def test_choose_modes_empty_indices_fallback():
    s = _state()
    agent = InteractiveAgent({})
    result = _drive(
        agent, "choose_modes", (s, 0, ["a", "b"]), {"indices": []},
    )
    assert result == [0]


def test_choose_card_from_opponent_hand():
    s = _state()
    opp_ids = [c.id for c in s.players[1].hand[:2]]
    agent = InteractiveAgent({})
    result = _drive(
        agent, "choose_card_from_opponent_hand", (s, 0, opp_ids),
        {"id": opp_ids[0]},
    )
    assert result == opp_ids[0]


def test_choose_x_clamped_to_upper_bound():
    s = _state()
    agent = InteractiveAgent({})
    # request 99 with upper bound 3 -> clamped to 3
    result = _drive(agent, "choose_x", (s, 0, "Fireball", 3), {"value": 99})
    assert result == 3
    # negative -> clamped to 0
    result2 = _drive(agent, "choose_x", (s, 0, "Fireball", 3), {"value": -4})
    assert result2 == 0


def test_choose_mana_color_invalid_falls_back_to_first():
    s = _state()
    agent = InteractiveAgent({})
    result = _drive(
        agent, "choose_mana_color", (s, 0, ["W", "U"]), {"color": "Z"},
    )
    assert result == "W"


def test_choose_devour_lands_returns_ids():
    s = _state()
    land = s.players[0].hand.pop()
    s.battlefield.append(land)
    agent = InteractiveAgent({})
    result = _drive(
        agent, "choose_devour_lands", (s, 0, [land.id]),
        {"ids": [land.id]},
    )
    assert result == [land.id]


def test_choose_convoke_creatures_returns_ids():
    s = _state()
    cre = s.players[0].hand.pop()
    s.battlefield.append(cre)
    agent = InteractiveAgent({})
    result = _drive(
        agent, "choose_convoke_creatures", (s, 0, [cre.id], 2, {}),
        {"ids": [cre.id]},
    )
    assert result == [cre.id]


def test_choose_sac_for_mana_returns_ids():
    s = _state()
    perm = s.players[0].hand.pop()
    s.battlefield.append(perm)
    agent = InteractiveAgent({})
    candidates = [(perm.id, "G")]
    result = _drive(
        agent, "choose_sac_for_mana", (s, 0, candidates, 1, {}),
        {"ids": [perm.id]},
    )
    assert result == [perm.id]


def test_choose_legend_keep_valid_and_invalid_fallback():
    s = _state()
    a = s.players[0].hand.pop()
    b = s.players[0].hand.pop()
    s.battlefield.extend([a, b])
    agent = InteractiveAgent({})
    legend_ids = [a.id, b.id]
    # valid pick
    result = _drive(
        agent, "choose_legend_keep", (s, 0, legend_ids), {"id": b.id},
    )
    assert result == b.id
    # invalid pick -> falls back to first
    result2 = _drive(
        agent, "choose_legend_keep", (s, 0, legend_ids),
        {"id": 999999},
    )
    assert result2 == a.id


def test_choose_pay_shock_life_default_false():
    s = _state()
    agent = InteractiveAgent({})
    result = _drive(
        agent, "choose_pay_shock_life", (s, 0, 2), {},
    )
    assert result is False


def test_choose_sacrifice_returns_chosen_id():
    s = _state()
    perm = s.players[0].hand.pop()
    s.battlefield.append(perm)
    agent = InteractiveAgent({})
    result = _drive(
        agent, "choose_sacrifice", (s, 0, [perm.id]), {"id": perm.id},
    )
    assert result == perm.id


def test_choose_card_from_library_accept_returns_id():
    s = _state()
    lib_ids = [c.id for c in s.players[0].library[:3]]
    agent = InteractiveAgent({})
    result = _drive(
        agent, "choose_card_from_library", (s, 0, lib_ids),
        {"id": lib_ids[1]},
    )
    assert result == lib_ids[1]


# ---------------------------------------------------------------------
# _evict_oldest
# ---------------------------------------------------------------------


def test_evict_oldest_trims_to_limit():
    """When the registry is at/over the cap, _evict_oldest drops the
    oldest entries until it's below the limit again."""
    saved = dict(_SESSIONS)
    try:
        _SESSIONS.clear()
        for i in range(_SESSION_LIMIT + 3):
            _SESSIONS[f"s{i}"] = InteractiveSession(
                session_id=f"s{i}",
                human_player_id=0,
                human_agent=InteractiveAgent({}),
                game_thread=threading.Thread(target=lambda: None),
            )
        assert len(_SESSIONS) == _SESSION_LIMIT + 3
        _evict_oldest()
        # _evict_oldest loops while len >= limit, so it stops at limit-1.
        assert len(_SESSIONS) == _SESSION_LIMIT - 1
        # Oldest insertions ("s0", "s1", ...) are the ones removed.
        assert "s0" not in _SESSIONS
    finally:
        _SESSIONS.clear()
        _SESSIONS.update(saved)


def test_decision_timeout_constant_is_reasonable():
    """Pinned sanity: the inactivity timeout is the documented 10 min."""
    assert DECISION_TIMEOUT == 600
