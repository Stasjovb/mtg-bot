"""SBA: saga age (CR 704.5r in audit numbering / 704.5s in latest
CR). When a saga has lore counters greater than or equal to its
final chapter number, its controller sacrifices it.

Implementation scope: only the SBA gate. The chapter-triggered
abilities that fire when the lore counter advances, and the
turn-based action that adds a lore counter at precombat main, are
NOT modeled — tests poke ``obj.lore_counters`` directly.
"""

from __future__ import annotations

from mtg_bot.cards.base import CardPrinting, ManaCost
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step, state_based_actions


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=None))
    state.players.append(Player(id=1, agent=None))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def _make_saga(name: str, chapter_count: int = 3) -> CardPrinting:
    """Synthesize a minimal saga printing. Real sagas have chapter-
    numbered triggered abilities, but the SBA gate doesn't depend
    on them."""
    return CardPrinting(
        name=name,
        mana_cost_str="{2}{W}",
        mana_cost=ManaCost(generic=2, colored=(("W", 1),)),
        type_line="Enchantment — Saga",
        supertypes=(),
        card_types=("Enchantment",),
        subtypes=("Saga",),
        chapter_count=chapter_count,
    )


# ---------- Printing shape ----------


def test_saga_printing_is_saga():
    saga = _make_saga("Test Saga", chapter_count=3)
    assert saga.is_saga is True
    assert saga.chapter_count == 3


def test_non_saga_printing_is_not_saga():
    """A non-saga has chapter_count = 0 by default and is_saga
    returns False."""
    bear = CardPrinting(
        name="Test Bear",
        mana_cost_str="{1}{G}",
        mana_cost=ManaCost(generic=1, colored=(("G", 1),)),
        type_line="Creature — Bear",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Bear",),
        power=2, toughness=2,
    )
    assert bear.is_saga is False
    assert bear.chapter_count == 0


# ---------- SBA gate ----------


def test_saga_with_no_lore_counters_stays():
    """Fresh saga (0 lore counters) doesn't fire the SBA."""
    state = _new_state()
    saga = _put(state, _make_saga("Fresh Saga", chapter_count=3), 0)
    state_based_actions(state)
    assert saga in state.battlefield


def test_saga_with_lore_counters_below_chapter_count_stays():
    """Lore counters < chapter count: still in play."""
    state = _new_state()
    saga = _put(state, _make_saga("Mid Saga", chapter_count=3), 0)
    saga.lore_counters = 2
    state_based_actions(state)
    assert saga in state.battlefield


def test_saga_at_chapter_count_sacrificed():
    """Lore counters == chapter count: SBA sacrifices."""
    state = _new_state()
    saga = _put(state, _make_saga("Done Saga", chapter_count=3), 0)
    saga.lore_counters = 3
    state_based_actions(state)
    assert saga not in state.battlefield
    assert saga in state.players[0].graveyard


def test_saga_above_chapter_count_sacrificed():
    """Lore counters > chapter count (somehow): SBA still
    sacrifices."""
    state = _new_state()
    saga = _put(state, _make_saga("Over Saga", chapter_count=3), 0)
    saga.lore_counters = 5
    state_based_actions(state)
    assert saga not in state.battlefield


def test_saga_sba_works_for_two_chapter_saga():
    """Some sagas have only 2 chapters. Pin the comparison reads
    the printing's chapter_count, not a hardcoded value."""
    state = _new_state()
    saga = _put(state, _make_saga("Two-Chapter Saga", chapter_count=2), 0)
    saga.lore_counters = 2
    state_based_actions(state)
    assert saga not in state.battlefield


def test_two_sagas_one_player_one_under_one_at_only_one_sacrificed():
    """One saga at chapter count, another with fewer counters: only
    the first goes."""
    state = _new_state()
    s1 = _put(state, _make_saga("Done Saga", chapter_count=3), 0)
    s1.lore_counters = 3
    s2 = _put(state, _make_saga("Other Saga", chapter_count=4), 0)
    s2.lore_counters = 2
    state_based_actions(state)
    assert s1 not in state.battlefield
    assert s2 in state.battlefield


def test_non_saga_with_lore_counters_unaffected():
    """A non-saga with lore_counters set (pathological, but defends
    the gate) is unaffected by the saga SBA."""
    state = _new_state()
    bear = _put(state, CardPrinting(
        name="Test Bear",
        mana_cost_str="{1}{G}",
        mana_cost=ManaCost(generic=1, colored=(("G", 1),)),
        type_line="Creature — Bear",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Bear",),
        power=2, toughness=2,
    ), 0)
    bear.lore_counters = 99
    state_based_actions(state)
    assert bear in state.battlefield
