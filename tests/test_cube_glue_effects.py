"""Cube glue bucket: defensive paths and descriptions of
``effects/generic/cube_glue.py`` and ``cube_glue_statics.py``."""

from __future__ import annotations

from mtg_bot.cards.base import make_creature
from mtg_bot.effects.generic import DrawCards
from mtg_bot.effects.generic import cube_glue as g
from mtg_bot.effects.generic.stack_control import CounterTargetSpell
from mtg_bot.effects.object_predicates import IsCreature
from mtg_bot.effects.targets import TargetSpec

from tests._cube_glue_helpers import arena, printing, put

_SPEC = (TargetSpec(filter=IsCreature()),)


def _all_effects():
    return [
        g.ReturnCardsExiledWithSourceToOwnersHand(),
        g.RevealHandMayExileCardOrChosenCreatureUntilSourceLeaves(),
        g.ReturnTargetGraveyardCardToHand(),
        g.ExileTopCardMayCastOtherwise(otherwise=DrawCards(amount=1)),
        g.ExileTopCardMayCastOtherwise(),
        g.ChooseNameRevealTopPutNamedIntoHand(nonland=False),
        g.CounterThenDelayedManaEqualToMV(counter=CounterTargetSpell()),
        g.RemoveAllCountersAddManaPerCounter(),
        g.HideawayLookExileOneFaceDown(),
        g.PlayExiledCardFreeIfAnyLibraryAtMost(),
        g.TargetBecomesCreatureIndefinitely(targets=_SPEC),
        g.ExchangeControlOfTargets(targets=_SPEC + _SPEC),
        g.SearchAnyNumberExileCastFreeThisTurn(),
        g.PutCountersUntapItBecomesCreature(targets=_SPEC),
        g.SearchAnyNumberOntoBattlefield(tapped=True),
        g.SearchAnyNumberOntoBattlefield(),
        g.DrawPerOpponentWhoLostLifeThisTurn(),
        g.TapTargetPutStunCounters(targets=_SPEC),
        g.AdjustSourceLoyalty(delta=-2),
        g.CreateThenTheyGainKeywordsUEOT(
            create=DrawCards(amount=1), keywords=frozenset({"haste"}),
        ),
        g.ReturnChosenGraveyardCardToHand(),
        g.SourceDealsLoyaltyDamageToChosen(),
        g.GrantExtraLoyaltyActivationsThisTurn(count=2),
        g.AdditionalCombatPhaseAfterThisPhase(),
    ]


def test_every_effect_describes_itself():
    for eff in _all_effects():
        assert isinstance(eff.describe(), str) and eff.describe()


def test_sourceless_and_targetless_resolutions_are_noops():
    s = arena()
    bear = put(s, make_creature("Bear", "{1}{G}", 2, 2), 1)
    s.resolving_source = None
    for eff in (
        g.RemoveAllCountersAddManaPerCounter(),
        g.PlayExiledCardFreeIfAnyLibraryAtMost(),
        g.AdjustSourceLoyalty(delta=1),
        g.SourceDealsLoyaltyDamageToChosen(),
        g.GrantExtraLoyaltyActivationsThisTurn(),
        g.TargetBecomesCreatureIndefinitely(targets=_SPEC),
        g.PutCountersUntapItBecomesCreature(targets=_SPEC),
        g.TapTargetPutStunCounters(targets=_SPEC),
        g.ReturnChosenGraveyardCardToHand(),
    ):
        eff.resolve(s, 0, ())
    # A target that left the battlefield / became illegal.
    for eff in (
        g.TargetBecomesCreatureIndefinitely(targets=_SPEC),
        g.PutCountersUntapItBecomesCreature(targets=_SPEC),
        g.TapTargetPutStunCounters(targets=_SPEC),
    ):
        eff.resolve(s, 0, (("creature", 999),))
    assert not bear.tapped and bear.stun_counters == 0


def test_counter_then_mana_delegates_targeting():
    eff = g.CounterThenDelayedManaEqualToMV(counter=CounterTargetSpell())
    s = arena()
    assert eff.requires_target()
    assert eff.legal_targets(s, 0) == []


def test_loyalty_damage_needs_loyalty_and_extra_activations_stack():
    s = arena()
    walker = put(s, printing("Comet, Stellar Pup"), 0)
    walker.loyalty_counters = 0
    s.resolving_source = walker
    g.SourceDealsLoyaltyDamageToChosen().resolve(s, 0)
    assert s.players[1].life == 20
    walker.loyalty_counters = 2
    s.players[0].agent = None
    g.SourceDealsLoyaltyDamageToChosen().resolve(s, 0)
    assert s.players[1].life == 18  # no agent: an opponent
    g.GrantExtraLoyaltyActivationsThisTurn(count=1).resolve(s, 0)
    g.GrantExtraLoyaltyActivationsThisTurn(count=2).resolve(s, 0)
    assert walker.extra_loyalty_activations == (s.turn_number, 3)
    s.turn_number += 1
    g.GrantExtraLoyaltyActivationsThisTurn(count=1).resolve(s, 0)
    assert walker.extra_loyalty_activations == (s.turn_number, 1)


def test_creature_during_your_turn_guards():
    from mtg_bot.cube_glue_statics import animate_for_turn, on_enters_battlefield
    from mtg_bot.game import is_creature_now

    s = arena(active=0)
    bear = put(s, make_creature("Bear", "{1}{G}", 2, 2), 0)
    animate_for_turn(s, bear)  # no static: no-op
    on_enters_battlefield(s, bear)
    kaito = put(s, printing("Kaito, Bane of Nightmares"), 0)
    kaito.loyalty_counters = 0
    animate_for_turn(s, kaito)
    assert not is_creature_now(kaito)
    kaito.loyalty_counters = 4
    s.add_continuous_effect(
        source_id=kaito.id, layer=6, kind="lose_all_abilities",
        target_id=kaito.id,
    )
    animate_for_turn(s, kaito)
    assert not is_creature_now(kaito)
