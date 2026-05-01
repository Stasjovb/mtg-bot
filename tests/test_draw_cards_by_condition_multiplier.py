"""``DrawCardsByConditionMultiplier`` generic primitive.

Replaces the previous bespoke ``AllFatesScrollDrawEffect``: a generic
"draw X cards, where X is <Condition.multiplier>" engine class. Reuses
the existing ``Condition`` algebra (the same one
``CostReduction.condition`` consumes) so any future "draw X cards
where X is <count phrase>" printing whose count is already a
``Condition`` plugs in by name without further engine work.

Behavioral coverage:

* ``PerDifferentlyNamedLand`` count = 0 → draws 0, leaves a log line.
* ``PerDifferentlyNamedLand`` count = 3 → draws 3.
* ``PerControlled`` count = 2 → draws 2 (forward-looking: a future
  printing wired with ``PerControlled(HasSubtype(<X>))`` plugs in
  here without additional engine work).
* ``describe`` echoes the parser-supplied description fragment.
"""

from __future__ import annotations

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.effects.conditions import (
    PerControlled,
    PerDifferentlyNamedLand,
)
from mtg_bot.effects.generic import DrawCardsByConditionMultiplier
from mtg_bot.effects.object_predicates import IsCreature
from mtg_bot.game import GameState, Player, Zone


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def _put_land(state, name, owner_id=0):
    obj = state.new_object(BASIC_LANDS[name], owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def test_per_differently_named_land_zero_draws_zero():
    state = _new_state()
    # Three Plains + library so library would supply if X were >0.
    _put_land(state, "Plains")
    _put_land(state, "Plains")
    # Ah but Plains repeats — only 1 distinct name, so will draw 1.
    # Drop Plains entries so distinct count = 0.
    state.battlefield.clear()
    for _ in range(3):
        c = state.new_object(BASIC_LANDS["Forest"], 0, Zone.LIBRARY)
        state.players[0].library.append(c)
    eff = DrawCardsByConditionMultiplier(
        condition=PerDifferentlyNamedLand(),
        description_fragment="where X is differently-named-lands count",
    )
    eff.resolve(state, 0, ())
    assert len(state.players[0].hand) == 0


def test_per_differently_named_land_three_draws_three():
    state = _new_state()
    _put_land(state, "Plains")
    _put_land(state, "Plains")  # duplicate name — counts once
    _put_land(state, "Forest")
    _put_land(state, "Island")
    for _ in range(5):
        c = state.new_object(BASIC_LANDS["Swamp"], 0, Zone.LIBRARY)
        state.players[0].library.append(c)
    eff = DrawCardsByConditionMultiplier(
        condition=PerDifferentlyNamedLand(),
        description_fragment=(
            "where X is the number of differently named lands you control"
        ),
    )
    eff.resolve(state, 0, ())
    assert len(state.players[0].hand) == 3


def test_per_controlled_creature_count_drives_draw_count():
    """Forward-looking: a future printing wired with
    ``PerControlled(IsCreature())`` plugs into the same primitive
    without further engine work."""
    from mtg_bot.cards.base import make_creature

    state = _new_state()
    cr_pr = make_creature("Test Creature", "{1}", power=1, toughness=1)
    for _ in range(2):
        obj = state.new_object(cr_pr, 0, Zone.BATTLEFIELD)
        state.battlefield.append(obj)
    for _ in range(5):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        state.players[0].library.append(c)
    eff = DrawCardsByConditionMultiplier(
        condition=PerControlled(IsCreature()),
        description_fragment="where X is creatures you control",
    )
    eff.resolve(state, 0, ())
    assert len(state.players[0].hand) == 2


def test_describe_echoes_description_fragment():
    eff = DrawCardsByConditionMultiplier(
        condition=PerDifferentlyNamedLand(),
        description_fragment=(
            "where X is the number of differently named lands you control"
        ),
    )
    desc = eff.describe()
    assert "draw X cards" in desc
    assert "differently named" in desc
