"""Engine-resolve tests for ``EachOpponentMillsCards``.

This effect is the 2-player simplification of "defending player mills
N" attack triggers (Specimen Freighter). Parser-shape tests cover the
recognizer; this file exercises the resolve loop's branches:
controller is skipped, lost players are skipped, library-empty short-
circuits ``milled``, multiple opponents each log their own line, and
the describe text is shape-stable.
"""

from __future__ import annotations

from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.effects.generic import EachOpponentMillsCards
from mtg_bot.game import GameState, Player, Zone


def _new_state(n_players=2):
    state = GameState()
    for i in range(n_players):
        state.players.append(Player(id=i, agent=None))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    return state


def _stock_library(state, player_id, n):
    """Put ``n`` creature cards in ``player_id``'s library (top first)."""
    names = list(SYNTHETIC_CREATURES.keys())
    for i in range(n):
        obj = state.new_object(
            SYNTHETIC_CREATURES[names[i % len(names)]],
            owner_id=player_id, zone=Zone.LIBRARY,
        )
        state.players[player_id].library.append(obj)


def test_resolve_mills_one_opponent_default_amount_one():
    state = _new_state()
    _stock_library(state, 1, 5)
    EachOpponentMillsCards().resolve(state, 0, ())
    assert len(state.players[1].library) == 4
    assert len(state.players[1].graveyard) == 1
    # Cards moved to graveyard get Zone.GRAVEYARD.
    assert state.players[1].graveyard[0].zone == Zone.GRAVEYARD
    assert any("P1 mills 1 cards" in line for line in state.log)


def test_resolve_mills_multiple_cards_per_opponent():
    state = _new_state()
    _stock_library(state, 1, 7)
    EachOpponentMillsCards(amount=3).resolve(state, 0, ())
    assert len(state.players[1].library) == 4
    assert len(state.players[1].graveyard) == 3


def test_resolve_skips_controller():
    state = _new_state()
    _stock_library(state, 0, 5)
    _stock_library(state, 1, 5)
    EachOpponentMillsCards(amount=2).resolve(state, 0, ())
    # P0 (controller) untouched.
    assert len(state.players[0].library) == 5
    assert len(state.players[0].graveyard) == 0
    # P1 (opponent) milled.
    assert len(state.players[1].library) == 3
    assert len(state.players[1].graveyard) == 2


def test_resolve_skips_lost_players():
    state = _new_state(n_players=3)
    state.players[2].has_lost = True
    _stock_library(state, 1, 5)
    _stock_library(state, 2, 5)
    EachOpponentMillsCards(amount=2).resolve(state, 0, ())
    # P1 milled, P2 (lost) untouched.
    assert len(state.players[1].graveyard) == 2
    assert len(state.players[2].library) == 5
    assert len(state.players[2].graveyard) == 0


def test_resolve_clamps_when_library_runs_dry():
    """Asking to mill 10 with only 3 in the library mills exactly 3
    (the inner ``if not p.library: break`` branch fires)."""
    state = _new_state()
    _stock_library(state, 1, 3)
    EachOpponentMillsCards(amount=10).resolve(state, 0, ())
    assert state.players[1].library == []
    assert len(state.players[1].graveyard) == 3
    assert any("P1 mills 3 cards" in line for line in state.log)


def test_resolve_logs_zero_mills_for_empty_library_opponent():
    """Opponent with empty library still gets a log line at 0 mills —
    the loop body runs once (controller-skip + has_lost-skip don't
    apply) but the inner break fires immediately."""
    state = _new_state()
    EachOpponentMillsCards(amount=5).resolve(state, 0, ())
    assert any("P1 mills 0 cards" in line for line in state.log)


def test_resolve_each_opponent_logged_separately():
    state = _new_state(n_players=3)
    _stock_library(state, 1, 4)
    _stock_library(state, 2, 4)
    EachOpponentMillsCards(amount=2).resolve(state, 0, ())
    assert any("P1 mills 2 cards" in line for line in state.log)
    assert any("P2 mills 2 cards" in line for line in state.log)


def test_describe_text_includes_amount():
    desc = EachOpponentMillsCards(amount=4).describe()
    assert "4" in desc
    assert "mills" in desc.lower()
