"""Behavioral tests for the decomposed Requiem Monolith activation.

The bespoke ``RequiemMonolithActivatedEffect`` and ``RequiemMonolith
DealtDamageEffect`` engine classes were retired when the activation
decomposed into a ``Sequence`` of two generic primitives:

  1. ``GrantTriggeredAbilityUEOT(ability=TriggeredAbility(trigger=
     "this_dealt_damage", effect=DrawCardsAndLoseLifeEqualToResolving
     Damage()))`` — grants the quoted "Whenever this creature is dealt
     damage, you draw that many cards and lose that much life." trigger
     UEOT to the chosen creature.
  2. ``MayHaveSourceDealDamageToTarget(amount=1)`` — offers the
     target's controller (NOT the activator) an optional 1-damage
     ping. On accept, the source deals 1 to the target which fires
     the granted trigger we just installed (1 draw + 1 life loss).

These tests resolve the parsed ``Sequence`` end-to-end for both the
accept-the-ping and decline-the-ping branches and confirm the granted
trigger persists on the target for the rest of the turn.
"""

from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.effects import (
    DrawCardsAndLoseLifeEqualToResolvingDamage,
    GrantTriggeredAbilityUEOT,
    MayHaveSourceDealDamageToTarget,
    Sequence,
    TriggeredAbility,
)
from mtg_bot.game import GameState, Player, Zone


_PRINTINGS = OracleParserCardSource().get_printings()


class _AcceptPing(Agent):
    """Always accepts the optional 1-damage ping (yes)."""

    def choose_yes_no(self, state, player_id, prompt):
        return True


class _DeclinePing(Agent):
    """Always declines the optional 1-damage ping (no)."""

    def choose_yes_no(self, state, player_id, prompt):
        return False


def _new_state(p1_agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=p1_agent or RandomAgent()))
    return state


def _put(state, printing, owner_id=0, source=False):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def _activation_effect():
    """The Sequence the parser produces for Requiem Monolith's
    activation body. Mirrors the decomposed shape verified by the
    parser test (``test_parser_artifact_requiem_monolith``)."""
    return Sequence(effects=(
        GrantTriggeredAbilityUEOT(
            ability=TriggeredAbility(
                trigger="this_dealt_damage",
                effect=DrawCardsAndLoseLifeEqualToResolvingDamage(),
            ),
        ),
        MayHaveSourceDealDamageToTarget(amount=1),
    ))


def test_accepted_ping_grants_trigger_pings_and_fires_rider():
    """Activate → grant trigger → controller accepts → 1 damage fires
    rider → 1 card drawn, 1 life lost."""
    state = _new_state(p1_agent=_AcceptPing())
    monolith = _put(state, _PRINTINGS["Requiem Monolith"], owner_id=0)
    state.resolving_source = monolith
    for _ in range(3):
        c = state.new_object(BASIC_LANDS["Plains"], 1, Zone.LIBRARY)
        state.players[1].library.append(c)
    enemy_bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    life_before = state.players[1].life
    _activation_effect().resolve(state, 0, (("creature", enemy_bear.id),))
    assert enemy_bear.damage == 1
    assert state.players[1].life == life_before - 1
    assert len(state.players[1].hand) == 1
    # The granted trigger is still on the creature for the rest of the turn.
    from mtg_bot.game import effective_triggered_abilities
    granted = [
        ab for ab in effective_triggered_abilities(state, enemy_bear)
        if ab not in enemy_bear.printing.triggered_abilities
    ]
    assert len(granted) == 1
    assert granted[0].trigger == "this_dealt_damage"


def test_declined_ping_grants_trigger_but_no_damage():
    """Activate → grant trigger → controller declines → no damage, no draw."""
    state = _new_state(p1_agent=_DeclinePing())
    monolith = _put(state, _PRINTINGS["Requiem Monolith"], owner_id=0)
    state.resolving_source = monolith
    for _ in range(3):
        c = state.new_object(BASIC_LANDS["Plains"], 1, Zone.LIBRARY)
        state.players[1].library.append(c)
    enemy_bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    life_before = state.players[1].life
    _activation_effect().resolve(state, 0, (("creature", enemy_bear.id),))
    assert enemy_bear.damage == 0
    assert state.players[1].life == life_before
    assert len(state.players[1].hand) == 0
    # Trigger granted regardless of the may-decision.
    from mtg_bot.game import effective_triggered_abilities
    granted = [
        ab for ab in effective_triggered_abilities(state, enemy_bear)
        if ab not in enemy_bear.printing.triggered_abilities
    ]
    assert len(granted) == 1


def test_may_have_source_deal_damage_no_target_noop():
    """``MayHaveSourceDealDamageToTarget`` no-ops cleanly with no target."""
    state = _new_state()
    state.resolving_source = _put(
        state, _PRINTINGS["Requiem Monolith"], owner_id=0,
    )
    MayHaveSourceDealDamageToTarget(amount=1).resolve(state, 0, ())


def test_may_have_source_deal_damage_wrong_kind_noop():
    """A non-creature target slot passes through without crashing."""
    state = _new_state()
    state.resolving_source = _put(
        state, _PRINTINGS["Requiem Monolith"], owner_id=0,
    )
    MayHaveSourceDealDamageToTarget(amount=1).resolve(
        state, 0, (("player", 0),),
    )


def test_may_have_source_deal_damage_target_left_battlefield():
    """If the target moved off the battlefield between targeting and
    resolve, the effect fizzles cleanly."""
    state = _new_state()
    state.resolving_source = _put(
        state, _PRINTINGS["Requiem Monolith"], owner_id=0,
    )
    MayHaveSourceDealDamageToTarget(amount=1).resolve(
        state, 0, (("creature", 999),),
    )


def test_may_have_source_deal_damage_no_source_noop():
    """No ``state.resolving_source`` → silent no-op."""
    state = _new_state()
    enemy_bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    MayHaveSourceDealDamageToTarget(amount=1).resolve(
        state, 0, (("creature", enemy_bear.id),),
    )
    assert enemy_bear.damage == 0


def test_may_have_source_deal_damage_target_controller_no_agent_noop():
    """Target controller has no agent → silent no-op (defensive)."""
    state = _new_state()
    state.players[1].agent = None
    state.resolving_source = _put(
        state, _PRINTINGS["Requiem Monolith"], owner_id=0,
    )
    enemy_bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    MayHaveSourceDealDamageToTarget(amount=1).resolve(
        state, 0, (("creature", enemy_bear.id),),
    )
    assert enemy_bear.damage == 0


def test_dealt_damage_rider_amount_zero_noop():
    """The rider effect bails out cleanly if the damage channel is 0."""
    state = _new_state()
    state.resolving_combat_damage_amount = 0
    DrawCardsAndLoseLifeEqualToResolvingDamage().resolve(state, 0, ())


def test_dealt_damage_rider_no_source_noop():
    """The rider effect bails out cleanly if no resolving_source is set."""
    state = _new_state()
    state.resolving_combat_damage_amount = 5
    state.resolving_source = None
    DrawCardsAndLoseLifeEqualToResolvingDamage().resolve(state, 0, ())


def test_may_have_source_deal_damage_describe():
    """``describe`` mentions the ping amount and the target controller's
    optional choice."""
    d = MayHaveSourceDealDamageToTarget(amount=1).describe()
    assert "1 damage" in d
    assert "may" in d


def test_dealt_damage_rider_describe():
    d = DrawCardsAndLoseLifeEqualToResolvingDamage().describe()
    assert "draw" in d
    assert "lose" in d


def test_requiem_printing_has_sorcery_speed_activated():
    m = _PRINTINGS["Requiem Monolith"]
    assert len(m.activated_abilities) == 1
    a = m.activated_abilities[0]
    assert a.sorcery_speed
    assert a.cost.tap_self


def test_requiem_printing_decomposes_to_sequence():
    """The activation effect is a ``Sequence`` of the two generic
    primitives (no bespoke single-class wrapper)."""
    m = _PRINTINGS["Requiem Monolith"]
    eff = m.activated_abilities[0].effect
    assert isinstance(eff, Sequence)
    assert len(eff.effects) == 2
    grant, ping = eff.effects
    assert isinstance(grant, GrantTriggeredAbilityUEOT)
    assert grant.ability is not None
    assert grant.ability.trigger == "this_dealt_damage"
    assert isinstance(
        grant.ability.effect, DrawCardsAndLoseLifeEqualToResolvingDamage
    )
    assert isinstance(ping, MayHaveSourceDealDamageToTarget)
    assert ping.amount == 1
