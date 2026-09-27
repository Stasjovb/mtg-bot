"""Unit tests for ``mtg_bot.effects.generic.cube_walkers`` primitives —
describe strings, edge / fizzle branches, and the builder's guard
branches not reached by the card-level tests."""

from __future__ import annotations

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.cards.base import make_creature
from mtg_bot.cards.parser.planeswalker_builder import (
    _build_planeswalker_printing,
)
from mtg_bot.effects.generic import DrawCards
from mtg_bot.effects.generic.cube_walkers import (
    HasManaValueAtMost,
    IfCondition,
    LookTopNMayRevealMatchingToHandRestBottomRandom,
    MayCastSorceriesAsThoughFlashUntilYourNextTurn,
    PutPlusOneCounterOnEachCreatureYouControlThenGrantKeywords,
    PutPlusOneCountersOnTargetThenGrantKeywordsUEOT,
    SacrificeCreatureThenDamageEqualToItsPower,
    WinTheGame,
    YourLibraryHasNoCards,
)
from mtg_bot.effects.generic.destroy import Destroy
from mtg_bot.effects.object_predicates import IsCreature
from mtg_bot.effects.targets import TargetSpec
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.legal import _may_cast_sorceries_as_flash


def _state(agent=None):
    s = GameState()
    s.players.append(Player(id=0, agent=agent))
    s.players.append(Player(id=1, agent=agent))
    return s


def _bf(s, printing, pid):
    o = s.new_object(printing, pid, Zone.BATTLEFIELD)
    s.battlefield.append(o)
    return o


def test_describes():
    spec = TargetSpec(filter=IsCreature(), count_min=0)
    assert WinTheGame().describe() == "you win the game"
    assert "win the game" in IfCondition(
        YourLibraryHasNoCards(), WinTheGame(),
    ).describe()
    assert "flash" in MayCastSorceriesAsThoughFlashUntilYourNextTurn(
    ).describe()
    assert "a +1/+1 counter" in (
        PutPlusOneCountersOnTargetThenGrantKeywordsUEOT(targets=(spec,))
        .describe()
    )
    three = PutPlusOneCountersOnTargetThenGrantKeywordsUEOT(
        amount=3, targets=(spec,), granted_keywords=frozenset({"haste"}),
    ).describe()
    assert "3 +1/+1 counters" in three and "haste" in three
    each = PutPlusOneCounterOnEachCreatureYouControlThenGrantKeywords
    assert "your next turn" in each(
        granted_keywords=frozenset({"flying"}), until_your_next_turn=True,
    ).describe()
    assert "end of turn" in each(
        granted_keywords=frozenset({"flying"}),
    ).describe()
    assert "random order" in (
        LookTopNMayRevealMatchingToHandRestBottomRandom().describe()
    )
    sac = SacrificeCreatureThenDamageEqualToItsPower
    assert "Hamster" in sac(draw_if_subtype="Hamster").describe()
    assert "draw" not in sac().describe()


def test_if_condition_targets_delegate_and_skip_branch():
    inner = Destroy(targets=(TargetSpec(filter=IsCreature()),))
    eff = IfCondition(YourLibraryHasNoCards(), inner)
    s = _state()
    bear = _bf(s, make_creature("Bear", "{1}{G}", 2, 2), 1)
    assert eff.requires_target()
    assert eff.target_count_range() == (1, 1)
    assert eff.legal_targets(s, 0) == [("creature", bear.id)]
    s.player_by_id(0).library.append(
        s.new_object(BASIC_LANDS["Forest"], 0, Zone.LIBRARY),
    )
    assert eff.resolve(s, 0, (("creature", bear.id),)) is False
    assert bear in s.battlefield


def test_mana_value_at_most():
    s = _state()
    bear = _bf(s, make_creature("Bear", "{1}{G}", 2, 2), 0)
    assert HasManaValueAtMost(2).test(bear, s)
    assert not HasManaValueAtMost(1).test(bear, s)


def test_win_the_game_without_resolving_source():
    s = _state()
    WinTheGame().resolve(s, 1)
    assert s.winner_id == 1


def test_sorceries_as_flash_grant_without_source_and_scope():
    s = _state()
    MayCastSorceriesAsThoughFlashUntilYourNextTurn().resolve(s, 0)
    assert _may_cast_sorceries_as_flash(s, 0)
    assert not _may_cast_sorceries_as_flash(s, 1)
    s.expire_continuous_effects("controller_untap", player_id=0)
    assert not _may_cast_sorceries_as_flash(s, 0)


def test_counters_on_target_no_targets_is_noop():
    eff = PutPlusOneCountersOnTargetThenGrantKeywordsUEOT(
        targets=(TargetSpec(filter=IsCreature(), count_min=0),),
    )
    s = _state()
    bear = _bf(s, make_creature("Bear", "{1}{G}", 2, 2), 0)
    eff.resolve(s, 0, ())
    assert bear.plus_one_counters == 0


def test_counters_on_each_without_keywords():
    eff = PutPlusOneCounterOnEachCreatureYouControlThenGrantKeywords(
        amount=2,
    )
    s = _state()
    bear = _bf(s, make_creature("Bear", "{1}{G}", 2, 2), 0)
    eff.resolve(s, 0)
    assert bear.plus_one_counters == 2


def test_look_top_empty_library_and_no_agent():
    eff = LookTopNMayRevealMatchingToHandRestBottomRandom(n=2)
    s = _state()
    eff.resolve(s, 0)  # empty library: no-op
    assert s.player_by_id(0).hand == []
    lib = s.player_by_id(0).library
    lib.extend(
        s.new_object(BASIC_LANDS["Forest"], 0, Zone.LIBRARY)
        for _ in range(3)
    )
    eff.resolve(s, 0)  # no agent: takes the first (unfiltered) card
    assert len(s.player_by_id(0).hand) == 1
    assert len(lib) == 2


def test_sacrifice_reflexive_legal_targets_and_no_agent():
    eff = SacrificeCreatureThenDamageEqualToItsPower()
    s = _state()
    bear = _bf(s, make_creature("Bear", "{1}{G}", 2, 2), 0)
    legal = eff.legal_targets(s, 0)
    assert ("player", 1) in legal and ("creature", bear.id) in legal
    assert eff.resolve(s, 0, (("player", 1),)) is True
    assert s.player_by_id(1).life == 18
    assert bear not in s.battlefield


def test_sacrifice_zero_power_deals_no_damage():
    eff = SacrificeCreatureThenDamageEqualToItsPower(draw_if_subtype="Wall")
    s = _state(agent=RandomAgent())
    wall = _bf(s, make_creature("Wall", "{1}", 0, 4, subtypes=("Wall",)), 0)
    s.player_by_id(0).library.append(
        s.new_object(BASIC_LANDS["Forest"], 0, Zone.LIBRARY),
    )
    eff.resolve(s, 0, (("player", 1),))
    assert wall not in s.battlefield
    assert s.player_by_id(1).life == 20
    assert s.player_by_id(0).hand == []


def _card(oracle, **kw):
    base = {
        "name": "Probe, the Walker", "mana_cost": "{2}",
        "type_line": "Legendary Planeswalker — Probe", "loyalty": "3",
        "oracle_text": oracle,
    }
    base.update(kw)
    return base


def test_builder_guards():
    assert _build_planeswalker_printing(
        _card("+1: Draw a card.", type_line="Legendary Creature — Elf")
    ) is None
    assert _build_planeswalker_printing(
        _card("+1: Draw a card.", loyalty=None)
    ) is None
    assert _build_planeswalker_printing(
        _card("+1: Draw a card.", loyalty="X")
    ) is None
    # Blank lines are skipped.
    ok = _build_planeswalker_printing(_card("+1: Draw a card.\n\n"))
    assert ok is not None


def test_builder_compound_trigger_line():
    p = _build_planeswalker_printing(_card(
        "When Probe enters or dies, draw a card.\n+1: Draw a card."
    ))
    # "enters or dies" is a compound-condition trigger: two arms.
    assert p is not None
    assert len(p.triggered_abilities) == 2


def test_draw_cards_primitive_still_counts():
    s = _state()
    s.player_by_id(0).library.append(
        s.new_object(BASIC_LANDS["Forest"], 0, Zone.LIBRARY),
    )
    DrawCards(amount=1).resolve(s, 0)
    assert s.player_by_id(0).cards_drawn_this_turn == 1
