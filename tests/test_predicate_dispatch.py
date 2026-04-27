"""End-to-end tests for the predicate-trigger dispatcher.

Verifies that the engine fires predicate-path triggers (``event=`` /
``predicate=``) through the centralized ``dispatch_event`` function,
without affecting any of the existing string-key triggers.
"""

from __future__ import annotations

from mtg_bot.actions import _trigger_etb_abilities, dispatch_event
from mtg_bot.agents import RandomAgent
from mtg_bot.cards.base import (
    GainLife,
    TriggeredAbility,
    make_creature,
)
from mtg_bot.effects.predicates import (
    Always,
    Controlled,
    Event,
    IsLand,
    IsSelf,
    Never,
    YOU,
)
from mtg_bot.game import GameState, Player, Zone
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def _put_on_battlefield(state, printing, controller_id=0):
    obj = state.new_object(printing, controller_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


# ---------- Synthetic test printings ----------

def _self_etb_creature():
    """Synthetic creature with a predicate-style 'this enters → gain
    1 life' ability. Equivalent to the legacy
    ``trigger="etb", effect=GainLife(1)`` shape but on the new path.
    """
    return make_creature(
        "Test Self ETB", "{1}{W}", 1, 1,
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=GainLife(amount=1),
            ),
        ),
    )


def _landfall_creature():
    """Synthetic creature whose ability listens for any land you
    control entering — the predicate-style equivalent of
    ``trigger="landfall"``."""
    return make_creature(
        "Test Landfall Creature", "{2}{G}", 2, 2,
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsLand() & Controlled(by=YOU),
                effect=GainLife(amount=2),
            ),
        ),
    )


def _always_creature():
    return make_creature(
        "Test Always", "{1}", 1, 1,
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=Always(),
                effect=GainLife(amount=3),
            ),
        ),
    )


def _never_creature():
    return make_creature(
        "Test Never", "{1}", 1, 1,
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=Never(),
                effect=GainLife(amount=99),
            ),
        ),
    )


# ---------- Self-ETB via dispatcher ----------

def test_self_etb_predicate_fires_when_creature_enters():
    """A creature with ``event=ENTERS, predicate=IsSelf()`` should
    push its trigger when the creature enters the battlefield."""
    state = _new_state()
    creature = _put_on_battlefield(state, _self_etb_creature())
    _trigger_etb_abilities(state, creature)
    assert len(state.stack) == 1
    item = state.stack[0]
    assert item.source is creature
    assert item.ability.event is Event.ENTERS


def test_self_etb_predicate_does_not_fire_for_other_permanent_entering():
    """The IsSelf predicate ties the trigger to the source; another
    permanent entering must NOT fire it."""
    state = _new_state()
    a = _put_on_battlefield(state, _self_etb_creature())
    b = _put_on_battlefield(state, _self_etb_creature())
    # Reset stack from the ETBs that fired during placement-via-helper.
    state.stack.clear()
    # Now simulate ONLY ``a`` entering — ``b``'s IsSelf trigger
    # must not fire because the obj isn't ``b``.
    _trigger_etb_abilities(state, a)
    sources = [item.source for item in state.stack]
    assert a in sources
    assert b not in sources


# ---------- Landfall-style predicate ----------

def test_landfall_predicate_fires_for_land_you_control_entering():
    """A creature whose ability is ``IsLand() & Controlled(YOU)``
    fires when a land controlled by the same player enters."""
    state = _new_state()
    landfall_src = _put_on_battlefield(state, _landfall_creature())
    # Simulate a land entering. Use a synthetic basic-land printing.
    from mtg_bot.cards.lands import BASIC_LANDS
    forest = state.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(forest)
    state.stack.clear()  # reset any prior pushes
    _trigger_etb_abilities(state, forest)
    # The landfall creature's predicate should match (IsLand & Controlled YOU).
    sources = [item.source for item in state.stack]
    assert landfall_src in sources


def test_landfall_predicate_does_not_fire_for_opponent_land():
    """A land controlled by the OPPONENT must not trigger the
    Controlled(YOU) predicate."""
    state = _new_state()
    landfall_src = _put_on_battlefield(state, _landfall_creature(), controller_id=0)
    from mtg_bot.cards.lands import BASIC_LANDS
    opp_forest = state.new_object(BASIC_LANDS["Forest"], 1, Zone.BATTLEFIELD)
    state.battlefield.append(opp_forest)
    state.stack.clear()
    _trigger_etb_abilities(state, opp_forest)
    sources = [item.source for item in state.stack]
    assert landfall_src not in sources


def test_landfall_predicate_does_not_fire_for_non_land_entering():
    """The IsLand predicate must reject a non-land entering."""
    state = _new_state()
    landfall_src = _put_on_battlefield(state, _landfall_creature())
    other = _put_on_battlefield(state, _self_etb_creature())  # creature
    state.stack.clear()
    _trigger_etb_abilities(state, other)
    sources = [item.source for item in state.stack]
    assert landfall_src not in sources


# ---------- Always / Never predicates ----------

def test_always_predicate_fires_for_every_enters():
    state = _new_state()
    always_src = _put_on_battlefield(state, _always_creature())
    second = _put_on_battlefield(state, _self_etb_creature())
    state.stack.clear()
    _trigger_etb_abilities(state, second)
    sources = [item.source for item in state.stack]
    assert always_src in sources


def test_never_predicate_does_not_fire():
    state = _new_state()
    never_src = _put_on_battlefield(state, _never_creature())
    other = _put_on_battlefield(state, _self_etb_creature())
    state.stack.clear()
    _trigger_etb_abilities(state, other)
    sources = [item.source for item in state.stack]
    assert never_src not in sources


# ---------- Coexistence with legacy string-key triggers ----------

def test_legacy_string_key_etb_does_not_fire_after_phase3_cleanup():
    """Phase 3 removed the legacy ``trigger="etb"`` string-match path
    from ``_trigger_etb_abilities``; only predicate-path abilities
    fire now. A leftover legacy-style ability has no firing path —
    every static card was migrated in phase 2 so this state isn't
    reachable from real cards, but the test pins the behavior."""
    legacy = make_creature(
        "Legacy ETB", "{W}", 1, 1,
        triggered_abilities=(
            TriggeredAbility(trigger="etb", effect=GainLife(amount=5)),
        ),
    )
    state = _new_state()
    obj = _put_on_battlefield(state, legacy)
    state.stack.clear()
    _trigger_etb_abilities(state, obj)
    assert state.stack == []


# ---------- dispatch_event direct call ----------

def test_dispatch_event_walks_battlefield_and_fires_predicate_triggers():
    """Calling ``dispatch_event`` directly fires every predicate-style
    ability whose event + predicate match — useful when the engine
    grows more event types in subsequent phases."""
    state = _new_state()
    landfall_src = _put_on_battlefield(state, _landfall_creature())
    self_etb = _put_on_battlefield(state, _self_etb_creature())
    state.stack.clear()
    # Manually dispatch ENTERS for ``self_etb`` — equivalent to it
    # having just entered.
    dispatch_event(state, Event.ENTERS, label="enters", obj=self_etb)
    sources = [item.source for item in state.stack]
    # Self-ETB on self_etb fires (IsSelf matches obj=self_etb).
    assert self_etb in sources
    # landfall_src does NOT fire because self_etb isn't a Land.
    assert landfall_src not in sources


def test_dispatch_event_skips_string_key_triggers():
    """The dispatcher only fires predicate-style triggers; string-key
    abilities are untouched (they fire via per-event ``_fire_*``
    paths)."""
    state = _new_state()
    legacy = make_creature(
        "Legacy", "{W}", 1, 1,
        triggered_abilities=(
            TriggeredAbility(trigger="etb", effect=GainLife(amount=5)),
        ),
    )
    obj = _put_on_battlefield(state, legacy)
    state.stack.clear()
    # Direct dispatch — string-key abilities are NOT fired.
    dispatch_event(state, Event.ENTERS, label="enters", obj=obj)
    assert state.stack == []
