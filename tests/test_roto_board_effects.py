"""Edge cases of ``mtg_bot.effects.generic.roto_board`` (Vintage Roto P5
effects) not reached by the per-card tests: predicates on players, gone
sources and targets, declined choices, and descriptions."""

from __future__ import annotations

from mtg_bot.effects.generic import roto_board as rb
from mtg_bot.effects.object_predicates import IsCreature, IsLand
from mtg_bot.effects.targets import TargetSpec
from mtg_bot.effects.value_predicates import IsPermanent
from mtg_bot.game import Zone

from tests._roto_p5_helpers import (
    make_state,
    place,
    printing,
    script,
    vanilla,
)


def test_predicates_reject_players():
    state = make_state()
    player = state.players[0]
    assert not rb.IsLegendaryPermanent().test(player, state)
    assert not rb.LacksSubtype("Aura").test(player, state)
    assert not rb.HasManaValueAtLeast(1).test(player, state)


def test_damage_each_player_skips_players_who_lost():
    state = make_state()
    place(state, 1, "Wasteland")
    state.players[1].has_lost = True
    eff = rb.DamageEachPlayerPerControlled(per_filter=IsLand(), multiplier=3)
    eff.resolve(state, 0)
    assert state.players[1].life == 20
    assert "3 times the number" in eff.describe()


def test_lose_keyword_without_or_with_illegal_targets():
    state = make_state()
    bear = place(state, 0, vanilla(2, 2, keywords=frozenset({"flying"})))
    eff = rb.LoseKeywordUEOT(keyword="flying", targets=(TargetSpec(IsCreature()),))
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("creature", 999),))
    assert not state.continuous_effects
    land = place(state, 0, "Forest")
    eff.resolve(state, 0, (("permanent", land.id),))
    assert not state.continuous_effects
    assert bear in state.battlefield


def test_event_player_effects_without_event_player_or_source():
    state = make_state()
    eff = rb.EventPlayerActsPerSourceCounter(
        action="tap", kind="fade", permanent_filter=IsPermanent(),
    )
    assert eff.targets_from_event(state, {}) is None
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("player", 1),))     # no resolving source
    src = place(state, 0, "Tangle Wire")
    state.resolving_source = src
    eff.resolve(state, 0, (("player", 1),))     # no fade counters: nothing
    state.resolving_source = None


def test_pump_equipped_creature_with_a_gone_host():
    state = make_state()
    jitte = place(state, 0, "Umezawa's Jitte")
    jitte.attached_to = 999
    state.resolving_source = jitte
    rb.PumpEquippedCreatureUEOT(power_bonus=2, toughness_bonus=2).resolve(state, 0)
    state.resolving_source = None
    assert not state.continuous_effects


def test_event_subject_damage_with_the_creature_gone_for_good():
    state = make_state()
    state.resolving_event_subject_id = 999
    rb.EventSubjectDealsDamageToEachOpponent(amount=2).resolve(state, 0)
    assert state.players[1].life == 20
    assert rb.EventSubjectDealsDamageToEachOpponent(amount=2).describe() == (
        "it deals 2 damage to each opponent"
    )


def test_descriptions_and_shaping():
    hoof = rb.PumpEachYouControlByCountUEOT(
        permanent_filter=IsCreature(), count_filter=IsCreature(),
    )
    assert hoof.describe().startswith("creatures you control get +X/+X")
    might = printing("Might of Old Krosa").spell_effect
    assert might.targets == might.otherwise.targets
    assert rb.DestroySourceIfAttackedThisTurn().describe().startswith("destroy")
    thief = printing("Thief of Existence").triggered_abilities[0].effect
    assert thief.targets == thief.inner.targets
    assert thief.requires_target() == thief.inner.requires_target()
    assert rb.TargetOpponentDraws().requires_target()
    assert rb.TargetPlayerScriesXThenDraws().requires_target()
    assert not rb.ExileUpToXGraveyardCards().requires_target()
    vines = rb.UntargetableByOpponentsThisTurn(targets=(TargetSpec(IsCreature()),))
    assert "if kicked" not in vines.describe()


def test_aether_vial_without_source_or_agent():
    state = make_state()
    eff = rb.PutCreatureWithMVEqualToCountersFromHand()
    eff.resolve(state, 0)                        # no resolving source
    vial = place(state, 0, "Aether Vial")
    place(state, 0, vanilla(0, 1, cost=""), Zone.HAND)
    state.players[0].agent = None
    state.resolving_source = vial
    eff.resolve(state, 0)                        # no agent to choose
    state.resolving_source = None
    assert len(state.players[0].hand) == 1


def test_targeted_effects_ignore_illegal_targets():
    state = make_state()
    land = place(state, 0, "Forest")
    for eff in (
        rb.PumpPerTypeCountUEOT(targets=(TargetSpec(IsCreature()),)),
        rb.UntargetableByOpponentsThisTurn(targets=(TargetSpec(IsCreature()),)),
        rb.PowerPumpThenDestroyIfAttacked(targets=(TargetSpec(IsCreature()),)),
        rb.OwnerShufflesTargetThenDiscovers(targets=(TargetSpec(IsCreature()),)),
        rb.PumpThenCreateRoleAttached(targets=(TargetSpec(IsCreature()),)),
    ):
        eff.resolve(state, 0, ())
        eff.resolve(state, 0, (("permanent", land.id),))
    assert land in state.battlefield and not state.continuous_effects


def test_destroy_if_attacked_with_its_creature_gone():
    state = make_state()
    state.resolving_source = None
    rb.DestroySourceIfAttackedThisTurn().resolve(state, 0)
    bear = place(state, 0, vanilla(2, 2))
    state.battlefield.remove(bear)
    state.resolving_source = bear
    rb.DestroySourceIfAttackedThisTurn().resolve(state, 0)
    state.resolving_source = None


def test_masticore_declined_with_its_source_already_gone():
    state = make_state()
    card = place(state, 0, "Forest", Zone.HAND)
    script(state, 0, "yes_no", False)
    rb.SacrificeSourceUnlessDiscard().resolve(state, 0)
    assert card in state.players[0].hand


def test_exile_until_leaves_skips_objects_that_left_mid_sweep():
    state = make_state()
    lock = place(state, 0, "Temporary Lockdown")
    eff = lock.printing.triggered_abilities[0].effect
    state.resolving_source = lock
    eff.resolve(state, 0)                         # nothing to exile
    state.resolving_source = None
    assert lock in state.battlefield


def test_remove_counters_cost_stops_when_holders_run_out():
    state = make_state()
    cost = rb.RemoveCountersFromAmongPermanentsCost(kind="oil", count=3)
    assert not cost.payable(state, 0, None)
    cost.pay(state, 0, None)                     # nothing to remove
    assert "3 oil counter" in state.log[-1]


def test_exile_graveyard_cards_ignores_other_kinds():
    state = make_state()
    card = place(state, 1, "Forest", Zone.GRAVEYARD)
    rb.ExileUpToXGraveyardCards().resolve(state, 0, (("creature", card.id),))
    assert card in state.players[1].graveyard


def test_target_opponent_draws_skips_a_lost_opponent():
    state = make_state()
    place(state, 1, "Island", Zone.LIBRARY)
    state.players[1].has_lost = True
    rb.TargetOpponentDraws().resolve(state, 0, (("player", 1),))
    assert len(state.players[1].hand) == 0
