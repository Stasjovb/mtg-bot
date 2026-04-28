"""Tests for Tannuk, Memorial Ensign's landfall-damage + second-trigger
draw and the new ability_resolutions_this_turn tracking."""

from mtg_bot.actions import put_into_battlefield
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.effects import TannukEnsignLandfallEffect
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import run_cleanup_step
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.active_player_idx = 0
    return state


def _stock_library(state, player_id, n):
    p = state.players[player_id]
    for _ in range(n):
        c = state.new_object(BASIC_LANDS["Plains"], player_id, Zone.LIBRARY)
        p.library.append(c)


# -----------------------
# Effect-level
# -----------------------


def test_effect_damages_each_opponent():
    state = _new_state()
    tannuk = state.new_object(
        _PRINTINGS["Tannuk, Memorial Ensign"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(tannuk)
    state.resolving_source = tannuk
    p1_life_before = state.players[1].life
    try:
        TannukEnsignLandfallEffect().resolve(state, 0, ())
    finally:
        state.resolving_source = None
    assert state.players[1].life == p1_life_before - 1


def test_effect_describe():
    d = TannukEnsignLandfallEffect().describe()
    assert "Tannuk" in d and "second" in d


def test_effect_noop_no_source_still_deals_damage():
    """Even without a source, damage fires (the ability doesn't depend
    on source for the damage clause); only the per-source counter is
    skipped."""
    state = _new_state()
    TannukEnsignLandfallEffect().resolve(state, 0, ())
    assert state.players[1].life == state.players[1].starting_life - 1


# -----------------------
# Tannuk integration
# -----------------------


def _fire_landfall_for_tannuk(state, tannuk):
    """Directly fire Tannuk's landfall effect as the engine would."""
    state.resolving_source = tannuk
    try:
        TannukEnsignLandfallEffect().resolve(state, 0, ())
    finally:
        state.resolving_source = None


def test_first_landfall_no_draw_second_landfall_draws():
    state = _new_state()
    _stock_library(state, 0, 5)
    tannuk = state.new_object(
        _PRINTINGS["Tannuk, Memorial Ensign"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(tannuk)
    _fire_landfall_for_tannuk(state, tannuk)
    assert len(state.players[0].hand) == 0  # no draw yet
    _fire_landfall_for_tannuk(state, tannuk)
    assert len(state.players[0].hand) == 1  # 2nd resolution draws


def test_third_and_fourth_landfall_do_not_draw():
    state = _new_state()
    _stock_library(state, 0, 5)
    tannuk = state.new_object(
        _PRINTINGS["Tannuk, Memorial Ensign"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(tannuk)
    for _ in range(4):
        _fire_landfall_for_tannuk(state, tannuk)
    # Only the 2nd resolution draws — 1 total.
    assert len(state.players[0].hand) == 1
    # All 4 resolutions damaged opponent for 1 each = 4 total.
    assert state.players[1].life == state.players[1].starting_life - 4


def test_cleanup_resets_resolution_counter():
    state = _new_state()
    _stock_library(state, 0, 5)
    tannuk = state.new_object(
        _PRINTINGS["Tannuk, Memorial Ensign"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(tannuk)
    # Fire twice this turn (draws on 2nd).
    _fire_landfall_for_tannuk(state, tannuk)
    _fire_landfall_for_tannuk(state, tannuk)
    assert len(state.players[0].hand) == 1
    # Cleanup → next turn's first fire shouldn't count as 2nd.
    run_cleanup_step(state)
    _fire_landfall_for_tannuk(state, tannuk)
    assert len(state.players[0].hand) == 1  # still 1, no additional draw
    _fire_landfall_for_tannuk(state, tannuk)
    assert len(state.players[0].hand) == 2  # 2nd resolution this turn draws


def test_tannuk_printing_metadata():
    t = _PRINTINGS["Tannuk, Memorial Ensign"]
    assert "Legendary" in t.supertypes
    triggers = {_legacy_or_inferred_key(ab) for ab in t.triggered_abilities}
    assert "landfall" in triggers
