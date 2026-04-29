"""Tests for the seventh Duskmourn creature parser batch.

This batch claims a cluster of DSK creatures by adding bespoke ETB /
dies / Survival effect classes plus one new generic primitive.
"""

from __future__ import annotations

from mtg_bot.cards.parser.source import OracleParserCardSource


def _claimed_names() -> frozenset[str]:
    return frozenset(OracleParserCardSource().claimed_names)


# ---------- Boilerbilges Ripper ----------


def test_boilerbilges_ripper_claimed_by_parser():
    # Boilerbilges Ripper ``{4}{R}`` 4/4 Human Assassin. Single
    # printed oracle line: ``When this creature enters, you may
    # sacrifice another creature or enchantment. When you do, this
    # creature deals 2 damage to any target.`` Claims via the new
    # ``BoilerbilgesRipperETBEffect`` bespoke ETB trigger registered
    # in ``_BESPOKE_CREATURES``.
    assert "Boilerbilges Ripper" in _claimed_names()


def test_boilerbilges_ripper_carries_etb_trigger():
    # Belt-and-suspenders: the claimed printing must carry the
    # ``BoilerbilgesRipperETBEffect`` ETB trigger and the printed P/T,
    # not some near-miss substitute.
    from mtg_bot.effects import BoilerbilgesRipperETBEffect
    from mtg_bot.effects.predicates import Event
    src = OracleParserCardSource()
    br = src.get_printings()["Boilerbilges Ripper"]
    assert br.is_creature
    assert br.power == 4
    assert br.toughness == 4
    assert len(br.triggered_abilities) == 1
    trig = br.triggered_abilities[0]
    assert trig.event == Event.ENTERS
    assert trig.effect == BoilerbilgesRipperETBEffect()


def test_boilerbilges_ripper_etb_no_legal_sacrifice_skips_damage():
    # With no other creature or enchantment to sacrifice, the entire
    # reflexive rider is skipped — no sacrifice, no damage.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.effects import BoilerbilgesRipperETBEffect
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    src = OracleParserCardSource().get_printings()["Boilerbilges Ripper"]
    br = state.new_object(src, owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(br)
    state.resolving_source = br
    eff = BoilerbilgesRipperETBEffect()
    try:
        eff.resolve(
            state, controller_id=0, targets=(("player", 1),),
        )
    finally:
        state.resolving_source = None
    # P1 was the target but the rider didn't fire; life unchanged.
    assert state.players[1].life == 20


def test_boilerbilges_ripper_etb_describe():
    from mtg_bot.effects import BoilerbilgesRipperETBEffect
    eff = BoilerbilgesRipperETBEffect()
    assert eff.describe() == (
        "you may sacrifice another creature or enchantment; if you "
        "do, this creature deals 2 damage to any target"
    )


def test_boilerbilges_ripper_etb_legal_targets_include_creatures_and_players():
    # The legal-target pool mirrors ``DealDamageAnyTarget``: every
    # battlefield creature plus every non-eliminated player.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.effects import BoilerbilgesRipperETBEffect
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    eff = BoilerbilgesRipperETBEffect()
    legal = eff.legal_targets(state, controller_id=0)
    assert ("creature", bear.id) in legal
    assert ("player", 0) in legal
    assert ("player", 1) in legal


# ---------- Fanatic of the Harrowing ----------


def test_fanatic_of_the_harrowing_claimed_by_parser():
    # Fanatic of the Harrowing ``{3}{B}`` 2/2 Human Cleric. Single
    # printed oracle line: ``When this creature enters, each player
    # discards a card. If you discarded a card this way, draw a
    # card.`` Claims via the new ``FanaticOfTheHarrowingETBEffect``
    # bespoke ETB trigger.
    assert "Fanatic of the Harrowing" in _claimed_names()


def test_fanatic_of_the_harrowing_carries_etb_trigger():
    # Belt-and-suspenders: the claimed printing must carry the
    # ``FanaticOfTheHarrowingETBEffect`` ETB trigger.
    from mtg_bot.effects import FanaticOfTheHarrowingETBEffect
    from mtg_bot.effects.predicates import Event
    src = OracleParserCardSource()
    fh = src.get_printings()["Fanatic of the Harrowing"]
    assert fh.is_creature
    assert fh.power == 2
    assert fh.toughness == 2
    assert len(fh.triggered_abilities) == 1
    trig = fh.triggered_abilities[0]
    assert trig.event == Event.ENTERS
    assert trig.effect == FanaticOfTheHarrowingETBEffect()


def test_fanatic_etb_each_player_discards_then_controller_draws():
    # Each player discards a card; if the controller actually
    # discarded, they draw one. With a 2-player game and both players
    # holding cards, both discard one and the controller draws one.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import BASIC_LANDS
    from mtg_bot.effects import FanaticOfTheHarrowingETBEffect
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    p0, p1 = state.players
    p0_card = state.new_object(
        BASIC_LANDS["Plains"], owner_id=0, zone=Zone.HAND,
    )
    p0.hand.append(p0_card)
    p1_card = state.new_object(
        BASIC_LANDS["Forest"], owner_id=1, zone=Zone.HAND,
    )
    p1.hand.append(p1_card)
    drawn = state.new_object(
        BASIC_LANDS["Mountain"], owner_id=0, zone=Zone.LIBRARY,
    )
    p0.library.append(drawn)
    eff = FanaticOfTheHarrowingETBEffect()
    eff.resolve(state, controller_id=0)
    assert p0_card in p0.graveyard
    assert p1_card in p1.graveyard
    assert drawn in p0.hand


def test_fanatic_etb_controller_empty_hand_no_draw():
    # If the controller has no card to discard at resolve, the
    # ``you discarded a card this way`` gate is False and the
    # reflexive draw is skipped. The opponent still discards.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import BASIC_LANDS
    from mtg_bot.effects import FanaticOfTheHarrowingETBEffect
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    p0, p1 = state.players
    p1_card = state.new_object(
        BASIC_LANDS["Forest"], owner_id=1, zone=Zone.HAND,
    )
    p1.hand.append(p1_card)
    drawn = state.new_object(
        BASIC_LANDS["Mountain"], owner_id=0, zone=Zone.LIBRARY,
    )
    p0.library.append(drawn)
    eff = FanaticOfTheHarrowingETBEffect()
    eff.resolve(state, controller_id=0)
    assert p1_card in p1.graveyard
    assert drawn in p0.library
    assert drawn not in p0.hand


def test_fanatic_etb_describe():
    from mtg_bot.effects import FanaticOfTheHarrowingETBEffect
    eff = FanaticOfTheHarrowingETBEffect()
    assert eff.describe() == (
        "each player discards a card; if you discarded a card this "
        "way, draw a card"
    )
