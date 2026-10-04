"""Roto P6: Angel's Grace -- split second; "You can't lose the game this
turn and your opponents can't win the game this turn. Until end of turn,
damage that would reduce your life total to less than 1 reduces it to 1
instead." Every loss / win path the engine has is exercised."""

from __future__ import annotations

import pytest

from mtg_bot.actions import CastSpell, DeclareAttackers, apply_action, resolve_top_of_stack
from mtg_bot.cards.base import make_creature
from mtg_bot.cards.parser.roto_keywords import parse_p6_effect
from mtg_bot.cards.source import get_active_source
from mtg_bot.combat import resolve_combat_damage
from mtg_bot.effects.base import _apply_damage
from mtg_bot.effects.generic.roto_keywords import (
    CANT_LOSE_KIND,
    LIFE_FLOOR_KIND,
    OPPONENTS_CANT_WIN_KIND,
    PlayerRuleUntilEndOfTurn,
    TargetPlayerLosesTheGame,
    player_cant_lose,
    player_cant_win,
    split_second_on_stack,
)
from mtg_bot.turn import Step, draw_card, state_based_actions, win_the_game
from tests._roto_helpers import arena, printing, put, to_hand

GRACE = "Angel's Grace"


def _graced(active=0):
    s = arena(active=active)
    s.priority_player_idx = 0
    put(s, get_active_source().get_printings()["Plains"], 0)
    grace = to_hand(s, printing(GRACE), 0)
    apply_action(s, 0, CastSpell(grace.id))
    assert split_second_on_stack(s)
    resolve_top_of_stack(s)
    return s


def test_angels_grace_parse():
    p = printing(GRACE)
    assert p.is_instant and "split second" in p.keywords
    kinds = []

    def walk(eff):
        if isinstance(eff, PlayerRuleUntilEndOfTurn):
            kinds.append(eff.kind)
        for sub in getattr(eff, "effects", ()):
            walk(sub)

    walk(p.spell_effect)
    assert sorted(kinds) == sorted([CANT_LOSE_KIND, OPPONENTS_CANT_WIN_KIND, LIFE_FLOOR_KIND])
    assert parse_p6_effect("you can't lose the game this turn and frobnicate") is None
    assert PlayerRuleUntilEndOfTurn(LIFE_FLOOR_KIND).describe().startswith("until end of turn")
    with pytest.raises(ValueError):
        PlayerRuleUntilEndOfTurn("bogus").resolve(arena(), 0)


def test_damage_reduces_life_to_one_at_most():
    s = _graced()
    _apply_damage(s, ("player", 0), 25)
    assert s.players[0].life == 1
    # Combat damage too.
    s.active_player_idx = 1
    attacker = put(s, make_creature("Test Giant", "{5}", 30, 30), 1)
    s.step = Step.DECLARE_ATTACKERS
    apply_action(s, 1, DeclareAttackers(attacker_ids=frozenset({attacker.id})))
    s.step = Step.COMBAT_DAMAGE
    resolve_combat_damage(s, defending_player_id=0)
    assert s.players[0].life == 1
    # The opponent isn't protected.
    _apply_damage(s, ("player", 1), 25)
    assert s.players[1].life == -5


def test_cant_lose_this_turn_by_any_state_based_or_effect_path():
    s = _graced()
    p0 = s.players[0]
    p0.life = -3          # life loss isn't damage: no floor
    p0.poison_counters = 12
    state_based_actions(s)
    assert not p0.has_lost and s.winner_id is None
    p0.library.clear()
    draw_card(s, 0)
    assert not p0.has_lost
    TargetPlayerLosesTheGame().resolve(s, 1, (("player", 0),))
    assert not p0.has_lost


def test_opponents_cant_win_this_turn():
    s = _graced()
    assert player_cant_win(s, 1) and not player_cant_win(s, 0)
    win_the_game(s, 1, reason="test")
    assert s.winner_id is None and not s.players[0].has_lost
    # The caster can still win.
    win_the_game(s, 0, reason="test")
    assert s.winner_id == 0


def test_it_all_ends_at_cleanup():
    s = _graced()
    s.players[0].life = 0
    state_based_actions(s)
    assert not s.players[0].has_lost
    s.expire_continuous_effects("cleanup")
    assert not player_cant_lose(s, 0)
    state_based_actions(s)
    assert s.players[0].has_lost and s.winner_id == 1
