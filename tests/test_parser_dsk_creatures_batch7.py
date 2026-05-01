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
    from mtg_bot.effects.predicates import (
        Event,
    )
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


class _BoilerbilgesAgent:
    """Deterministic agent for Boilerbilges-Ripper resolve tests:
    answers ``yes/no`` from ``accept_sac`` and always picks the first
    sac candidate."""

    def __init__(self, accept_sac: bool):
        self.accept_sac = accept_sac

    def choose_yes_no(self, state, controller_id, prompt):
        return self.accept_sac

    def choose_sacrifice(self, state, controller_id, ids):
        return ids[0]

    def choose_target(self, state, controller_id, options):
        return options[0] if options else None

    def choose_mode(self, state, controller_id, descriptions):
        return 0

    def choose_modes(self, state, controller_id, descriptions):
        return [0]

    def choose_card_from_library(self, state, controller_id, ids):
        return ids[0] if ids else None


def test_boilerbilges_ripper_etb_decline_keeps_sac_target_and_skips_damage():
    # Agent declines the optional sacrifice → no permanent leaves the
    # battlefield, no damage applied to the target opponent.
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.effects import BoilerbilgesRipperETBEffect
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=_BoilerbilgesAgent(accept_sac=False)))
    state.players.append(Player(id=1, agent=_BoilerbilgesAgent(accept_sac=False)))
    src = OracleParserCardSource().get_printings()["Boilerbilges Ripper"]
    br = state.new_object(src, owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(br)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    state.resolving_source = br
    try:
        BoilerbilgesRipperETBEffect().resolve(
            state, controller_id=0, targets=(("player", 1),),
        )
    finally:
        state.resolving_source = None
    # Sacrifice candidate stayed.
    assert bear in state.battlefield
    # Target opponent took no damage.
    assert state.players[1].life == 20


def test_boilerbilges_ripper_etb_accept_sacrifices_and_damages_target():
    # Agent accepts the sacrifice → the chosen creature is sacrificed,
    # and the rider deals 2 damage to the chosen any-target.
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.effects import BoilerbilgesRipperETBEffect
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=_BoilerbilgesAgent(accept_sac=True)))
    state.players.append(Player(id=1, agent=_BoilerbilgesAgent(accept_sac=True)))
    src = OracleParserCardSource().get_printings()["Boilerbilges Ripper"]
    br = state.new_object(src, owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(br)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    state.resolving_source = br
    try:
        BoilerbilgesRipperETBEffect().resolve(
            state, controller_id=0, targets=(("player", 1),),
        )
    finally:
        state.resolving_source = None
    # Sacrifice candidate left the battlefield.
    assert bear not in state.battlefield
    # Target opponent took 2 damage.
    assert state.players[1].life == 18


def test_boilerbilges_ripper_etb_accept_but_no_targets_skips_damage():
    # Agent accepts the sacrifice but the rider has no any-target tuple
    # to damage — the sacrifice still happens, the damage clause is a
    # no-op (the "if not targets: return" guard before _apply_damage).
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.effects import BoilerbilgesRipperETBEffect
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=_BoilerbilgesAgent(accept_sac=True)))
    state.players.append(Player(id=1, agent=_BoilerbilgesAgent(accept_sac=True)))
    src = OracleParserCardSource().get_printings()["Boilerbilges Ripper"]
    br = state.new_object(src, owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(br)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    state.resolving_source = br
    try:
        BoilerbilgesRipperETBEffect().resolve(
            state, controller_id=0, targets=(),
        )
    finally:
        state.resolving_source = None
    assert bear not in state.battlefield
    # No target → no damage applied to anyone.
    assert state.players[0].life == 20
    assert state.players[1].life == 20


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
    from mtg_bot.effects.predicates import (
        Event,
    )
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


# ---------- Infernal Phantom (+ DealDamageEqualToSourcePowerAnyTarget) ----------


def test_infernal_phantom_claimed_by_parser():
    # Infernal Phantom ``{3}{R}`` 2/3 Spirit. Two oracle lines:
    # ``Eerie — Whenever an enchantment you control enters and
    # whenever you fully unlock a Room, this creature gets +2/+0
    # until end of turn.`` and ``When this creature dies, it deals
    # damage equal to its power to any target.`` Claims via the
    # existing Eerie ability-word trigger plumbing for the first line
    # plus the new ``DealDamageEqualToSourcePowerAnyTarget`` generic
    # primitive for the second.
    assert "Infernal Phantom" in _claimed_names()


def test_infernal_phantom_carries_dies_damage_effect():
    # The claimed printing must wire the
    # ``DealDamageEqualToSourcePowerAnyTarget`` effect on a DIES
    # trigger. The Eerie pair (ENTERS + ROOM_FULLY_UNLOCKED) plus the
    # DIES trigger gives 3 total triggered abilities on the printing.
    from mtg_bot.effects import DealDamageEqualToSourcePowerAnyTarget
    from mtg_bot.effects.predicates import (
        Event,
    )
    src = OracleParserCardSource()
    ip = src.get_printings()["Infernal Phantom"]
    dies_triggers = [
        t for t in ip.triggered_abilities if t.event == Event.DIES
    ]
    assert len(dies_triggers) == 1
    assert dies_triggers[0].effect == (
        DealDamageEqualToSourcePowerAnyTarget()
    )


def test_deal_damage_equal_source_power_legal_targets_includes_creatures_and_players():
    # Legal-target pool for the new primitive is creatures on the
    # battlefield (gated through ``is_creature_now`` so impending
    # Overlords aren't valid creature targets) plus non-eliminated
    # players. Mirrors ``DealDamageAnyTarget`` exactly.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.effects import DealDamageEqualToSourcePowerAnyTarget
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    eff = DealDamageEqualToSourcePowerAnyTarget()
    legal = eff.legal_targets(state, controller_id=0)
    assert ("creature", bear.id) in legal
    assert ("player", 0) in legal
    assert ("player", 1) in legal


def test_deal_damage_equal_source_power_resolves_to_source_power():
    # At resolve time the primitive reads ``state.resolving_source``'s
    # effective power and routes that integer through ``_apply_damage``
    # against the chosen target. We seed the resolving source with a
    # printed power of 3 and verify a target creature takes 3 damage.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects import DealDamageEqualToSourcePowerAnyTarget
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    src = state.new_object(
        make_creature("Source", "{2}{R}", 3, 3),
        owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(src)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    state.resolving_source = src
    eff = DealDamageEqualToSourcePowerAnyTarget()
    try:
        eff.resolve(state, controller_id=0, targets=(("creature", bear.id),))
    finally:
        state.resolving_source = None
    assert bear.damage == 3


def test_deal_damage_equal_source_power_zero_power_no_op():
    # CR 119.5: when the amount of damage that would be dealt is 0 or
    # less, no damage is dealt. A source with effective power 0 fires
    # the trigger but the damage routing is skipped.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects import DealDamageEqualToSourcePowerAnyTarget
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    src = state.new_object(
        make_creature("Source", "{R}", 0, 1),
        owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(src)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    state.resolving_source = src
    eff = DealDamageEqualToSourcePowerAnyTarget()
    try:
        eff.resolve(state, controller_id=0, targets=(("creature", bear.id),))
    finally:
        state.resolving_source = None
    assert bear.damage == 0


def test_deal_damage_equal_source_power_describe():
    # The describe output names the source-power dependency so log
    # messages distinguish this primitive from the literal-amount
    # ``DealDamageAnyTarget`` sibling.
    from mtg_bot.effects import DealDamageEqualToSourcePowerAnyTarget
    eff = DealDamageEqualToSourcePowerAnyTarget()
    assert eff.describe() == (
        "deals damage equal to this creature's power to any target"
    )


def test_parse_deal_damage_equal_source_power_phrase():
    # End-to-end through the effect-phrase parser. The body
    # ``it deals damage equal to its power to any target`` round-trips
    # through ``_normalize_creature_effect_phrase`` (which strips the
    # ``it `` source-subject prefix) and matches the new
    # ``_DEAL_DAMAGE_EQUAL_TO_SOURCE_POWER_ANY_TARGET`` regex.
    from mtg_bot.cards.parser.effects import _parse_effect_phrase
    from mtg_bot.effects import DealDamageEqualToSourcePowerAnyTarget
    parsed = _parse_effect_phrase(
        "it deals damage equal to its power to any target"
    )
    assert parsed == DealDamageEqualToSourcePowerAnyTarget()


# ---------- House Cartographer ----------


def test_house_cartographer_claimed_by_parser():
    # House Cartographer ``{1}{G}`` 2/2 Human Scout Survivor. Single
    # oracle line: ``Survival — At the beginning of your second main
    # phase, if this creature is tapped, reveal cards from the top of
    # your library until you reveal a land card. Put that card into
    # your hand and the rest on the bottom of your library in a
    # random order.`` Claims via the new
    # ``HouseCartographerSurvivalEffect`` bespoke trigger.
    assert "House Cartographer" in _claimed_names()


def test_house_cartographer_carries_survival_trigger():
    # Belt-and-suspenders: the claimed printing must wire the
    # ``HouseCartographerSurvivalEffect`` on a
    # ``BEGINNING_OF_POSTCOMBAT_MAIN`` trigger with the standard
    # Survival predicate (controller-gate AND IsSelf AND IsTapped).
    from mtg_bot.effects import HouseCartographerSurvivalEffect
    from mtg_bot.effects.predicates import (
        Event,
    )
    src = OracleParserCardSource()
    hc = src.get_printings()["House Cartographer"]
    assert hc.is_creature
    assert hc.power == 2
    assert hc.toughness == 2
    assert len(hc.triggered_abilities) == 1
    trig = hc.triggered_abilities[0]
    assert trig.event == Event.BEGINNING_OF_POSTCOMBAT_MAIN
    assert trig.effect == HouseCartographerSurvivalEffect()


def test_house_cartographer_reveals_first_land_to_hand():
    # Library top-down: [Bear (non-land), Plains (LAND), Bear].
    # The library walk pops the Bear (not land), keeps it for "the
    # rest", then pops the Plains (land), stops. Plains goes to hand;
    # the Bear (and any further non-lands not popped) go to the bottom
    # in random order.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
    from mtg_bot.effects import HouseCartographerSurvivalEffect
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    p = state.players[0]
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.LIBRARY,
    )
    p.library.append(bear)
    plains = state.new_object(
        BASIC_LANDS["Plains"], owner_id=0, zone=Zone.LIBRARY,
    )
    p.library.append(plains)
    bear2 = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.LIBRARY,
    )
    p.library.append(bear2)
    eff = HouseCartographerSurvivalEffect()
    eff.resolve(state, controller_id=0)
    # The Plains landed in hand.
    assert plains in p.hand
    # The first Bear went back to the library bottom; Bear2 stayed in
    # the library at its original position (not popped).
    assert bear in p.library
    assert bear2 in p.library


def test_house_cartographer_no_land_in_library_no_hand_change():
    # When the library has no land cards at all, every revealed card
    # is non-land. They all go to the bottom in random order; the
    # hand stays empty.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.effects import HouseCartographerSurvivalEffect
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    p = state.players[0]
    for _ in range(3):
        c = state.new_object(
            SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.LIBRARY,
        )
        p.library.append(c)
    eff = HouseCartographerSurvivalEffect()
    eff.resolve(state, controller_id=0)
    assert len(p.hand) == 0
    assert len(p.library) == 3


def test_house_cartographer_empty_library_no_op():
    # An empty library walks zero iterations and silently no-ops.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.effects import HouseCartographerSurvivalEffect
    from mtg_bot.game import GameState, Player

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    p = state.players[0]
    assert not p.library
    eff = HouseCartographerSurvivalEffect()
    eff.resolve(state, controller_id=0)
    assert len(p.hand) == 0
    assert len(p.library) == 0


def test_house_cartographer_describe():
    from mtg_bot.effects import HouseCartographerSurvivalEffect
    eff = HouseCartographerSurvivalEffect()
    assert eff.describe() == (
        "reveal cards from the top of your library until you reveal "
        "a land card; put that card into your hand and the rest on "
        "the bottom of your library in a random order"
    )
