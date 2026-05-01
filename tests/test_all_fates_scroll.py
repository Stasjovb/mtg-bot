"""Tests for All-Fates Scroll's sac-draw activation, now wired through
the generic ``DrawCardsByConditionMultiplier`` engine class instead of
the previous bespoke ``AllFatesScrollDrawEffect``.

The body ``Draw X cards, where X is the number of differently named
lands you control.`` decomposes to:

  * ``PerDifferentlyNamedLand`` (the structural ``Condition`` whose
    ``multiplier`` returns the count of distinctly-named lands the
    viewer controls — same condition the spell-side cost-reduction
    grammar uses for Fungal Colossus's ``costs {X} less to cast``);
  * ``DrawCardsByConditionMultiplier(condition, description_fragment)``
    — generic engine class that reads ``condition.multiplier`` at
    resolve time and draws that many cards.

No card-specific engine wiring remains.
"""

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.effects.conditions import PerDifferentlyNamedLand
from mtg_bot.effects.generic import DrawCardsByConditionMultiplier
from mtg_bot.game import GameState, Player, Zone

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


_ALL_FATES_SCROLL_DRAW_EFFECT = DrawCardsByConditionMultiplier(
    condition=PerDifferentlyNamedLand(),
    description_fragment=(
        "where X is the number of differently named lands you control"
    ),
)


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def test_effect_draws_equal_to_distinct_land_names():
    state = _new_state()
    # 3 Plains, 2 Forests, 1 Island → 3 distinct names → draw 3.
    for _ in range(3):
        _put(state, BASIC_LANDS["Plains"])
    for _ in range(2):
        _put(state, BASIC_LANDS["Forest"])
    _put(state, BASIC_LANDS["Island"])
    for _ in range(5):
        c = state.new_object(BASIC_LANDS["Swamp"], 0, Zone.LIBRARY)
        state.players[0].library.append(c)
    _ALL_FATES_SCROLL_DRAW_EFFECT.resolve(state, 0, ())
    assert len(state.players[0].hand) == 3


def test_effect_draws_zero_when_no_lands():
    state = _new_state()
    for _ in range(3):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        state.players[0].library.append(c)
    _ALL_FATES_SCROLL_DRAW_EFFECT.resolve(state, 0, ())
    assert len(state.players[0].hand) == 0


def test_effect_describe():
    d = _ALL_FATES_SCROLL_DRAW_EFFECT.describe()
    assert "X cards" in d and "differently named" in d


def test_scroll_printing_has_two_activated_abilities():
    """Mana ability ({T}: Add any-color) + sac-for-draw ({7},{T},sac)."""
    s = _PRINTINGS["All-Fates Scroll"]
    assert len(s.activated_abilities) == 2
    mana_abil = next(
        a for a in s.activated_abilities if a.is_mana_ability
    )
    assert mana_abil.cost.tap_self
    draw_abil = next(
        a for a in s.activated_abilities if not a.is_mana_ability
    )
    assert draw_abil.cost.tap_self
    assert draw_abil.cost.sacrifice_self
    assert draw_abil.cost.mana_str == "{7}"
    assert isinstance(draw_abil.effect, DrawCardsByConditionMultiplier)
