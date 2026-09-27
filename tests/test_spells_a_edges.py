"""Edge and error paths of the cube spells-A grammar / engine modules."""

from __future__ import annotations

from mtg_bot.cards.parser.conditional_phrases import parse_instead_rider
from mtg_bot.cards.parser.counter_phrases import parse_counter
from mtg_bot.cards.parser.modal_spells import parse_multi_modal
from mtg_bot.cards.parser.removal_phrases import (
    parse_damage_to_target,
    parse_destroy_all,
    parse_targeted_removal,
)
from mtg_bot.cards.parser.spell_misc_phrases import parse_token_copy_of_target
from mtg_bot.cards.parser.target_phrases import (
    parse_card_phrase,
    parse_spell_phrase,
)
from mtg_bot.cards.spell_costs import (
    AdditionalCostOption,
    AlternativeCost,
    additional_costs_payable,
    alternative_cost_payable,
    pay_additional_cost_option,
    pay_alternative_cost_components,
)
from mtg_bot.effects.generic.cast_conditionals import AnOpponentDrawsCards
from mtg_bot.effects.generic.multi_modal import ChooseModes
from mtg_bot.effects.generic.spell_misc import CreateTokenCopyOfTargetPermanent
from mtg_bot.effects.generic.targeted_removal import RemoveTargetPermanents
from mtg_bot.effects.object_predicates import (
    IsArtifact, IsCreature, IsLand,
)
from mtg_bot.effects.value_predicates import (
    HasCardType,
    HasColor,
    HasManaValueAtMostColorsSpent,
)
from mtg_bot.game import Player

from tests._spells_a_helpers import (
    ScriptedAgent,
    cube,
    lands,
    new_game,
    put,
    to_hand,
    to_library,
)


def test_empty_phrases_reject():
    assert parse_counter("") is None
    assert parse_targeted_removal("") is None
    assert parse_destroy_all("") is None
    assert parse_damage_to_target("") is None


def test_instead_rider_with_new_target_needs_a_cast_time_condition():
    base = RemoveTargetPermanents(action="exile", target_filter=IsArtifact())
    assert parse_instead_rider(
        "exile target artifact or enchantment instead if there are four or "
        "more card types among cards in your graveyard",
        base,
    ) is None


def test_modal_rejects_non_bullet_mode_line():
    assert parse_multi_modal(
        ["Choose two —", "Draw a card.", "• Draw a card."], "X",
    ) is None


def test_token_copy_grammar_rejects():
    assert parse_token_copy_of_target(
        "create a token that's a copy of target wizard",
    ) is None


def test_card_and_spell_phrases():
    assert parse_card_phrase("card") == (True, None)
    assert parse_card_phrase("creature") == (False, None)
    ok, f = parse_card_phrase("noncreature, nonland card")
    assert ok and f == (~IsCreature()) & (~IsLand())
    ok, f = parse_card_phrase("blue card")
    assert ok and f == HasColor("U")
    ok, f = parse_card_phrase("red creature card")
    assert ok and f == IsCreature() & HasColor("R")
    assert parse_card_phrase("wizard card") == (False, None)
    assert parse_card_phrase("blue or  card") == (False, None)
    ok, f = parse_spell_phrase("nonblue creature spell")
    assert ok and f == IsCreature() & ~HasColor("U")


def test_alternative_cost_payability_edges():
    state = new_game()
    card = to_hand(state, "Force of Will")
    state.players[0].life = 0
    assert not alternative_cost_payable(
        state, 0, card, AlternativeCost(pay_life=1),
    )
    state.players[0].life = 20
    assert not alternative_cost_payable(
        state, 0, card, AlternativeCost(return_subtype="Island"),
    )
    assert not alternative_cost_payable(
        state, 0, card, AlternativeCost(sacrifice_subtype="Mountain"),
    )
    assert not alternative_cost_payable(
        state, 0, card, AlternativeCost(mana="{U}"),
    )


def test_alternative_cost_components_without_an_agent():
    state = new_game()
    state.players[0].agent = None
    card = to_hand(state, "Force of Will")
    pitch = to_hand(state, "Counterspell")
    island = put(state, "Island", controller=0)
    state.players[0].hand.remove(card)
    pay_alternative_cost_components(
        state, 0, card,
        AlternativeCost(exile_card_color="U", return_subtype="Island"),
    )
    assert pitch in state.players[0].exile
    assert island in state.players[0].hand


def test_additional_cost_edges():
    state = new_game()
    bolt = to_hand(state, "Lightning Bolt")
    assert additional_costs_payable(state, 0, bolt)
    state.players[0].hand.remove(bolt)
    card = to_hand(state, "Bitter Triumph")
    state.players[0].hand.remove(card)
    state.players[0].life = 0
    # Neither arm payable (no other card, no life): nothing is paid.
    pay_additional_cost_option(state, 0, card)
    assert state.players[0].life == 0
    # Without an agent, the first payable arm (discard) is used.
    state.players[0].life = 20
    state.players[0].agent = None
    other = to_hand(state, "Island")
    pay_additional_cost_option(state, 0, card)
    assert other in state.players[0].graveyard


def test_an_opponent_draws_asks_with_several_opponents():
    agent = ScriptedAgent(prefer=[("player", 2)])
    state = new_game(agent)
    state.players.append(Player(id=2, agent=ScriptedAgent()))
    drawn = to_library(state, "Island", owner=2)
    AnOpponentDrawsCards(amount=1).resolve(state, 0)
    assert drawn in state.players[2].hand


def test_choose_modes_non_repeat_padding_and_spree_fallback():
    state = new_game(ScriptedAgent(modes=[0, 0]))
    lands(state, 0, "Island", 1)
    from mtg_bot.effects.generic.draw_mill import DrawCards

    eff = ChooseModes(
        modes=(DrawCards(1), DrawCards(2)), min_modes=2, max_modes=2,
    )
    card = to_hand(state, "Kolaghan's Command")
    assert eff.choose_at_cast(state, 0, card, card.printing.mana_cost) == (0, 1)
    spree = ChooseModes(
        modes=(DrawCards(1), DrawCards(2)), min_modes=1, max_modes=2,
        mode_mana_costs=("{5}", "{U}"),
    )
    state.players[0].agent = ScriptedAgent(modes=[0])
    from mtg_bot.cards.base import ManaCost

    assert spree.choose_at_cast(state, 0, card, ManaCost()) == (1,)
    # More required modes than distinct modes (no repeats): padding stops.
    greedy = ChooseModes(
        modes=(DrawCards(1), DrawCards(2)), min_modes=3, max_modes=3,
    )
    state.players[0].agent = ScriptedAgent(modes=[])
    assert greedy.choose_at_cast(state, 0, card, ManaCost()) == (0, 1)


def test_choose_modes_targets_without_agent_answer():
    state = new_game()
    state.players[0].agent = None
    eff = cube("Kolaghan's Command").spell_effect
    targets = eff.select_targets(state, 0, (3,))
    assert len(targets) == 1


def test_chain_copy_declined_copy_and_losing_payer():
    from mtg_bot.game import Zone

    state = new_game()
    lands(state, 1, "Mountain", 4)
    state.resolving_spell = state.new_object(
        cube("Chain Lightning"), 0, Zone.STACK,
    )
    eff = cube("Chain Lightning").spell_effect
    state.players[1].agent = ScriptedAgent(yes=[True, False])
    eff.resolve(state, 0, (("player", 1),))
    assert state.stack == []  # paid {R}{R}, then declined to copy
    assert state.players[1].life == 17
    # A payer who has already lost can't pay.
    elf = put(state, "Llanowar Elves", controller=1)
    state.players[1].has_lost = True
    eff.resolve(state, 0, (("creature", elf.id),))
    assert state.stack == []


def test_spell_misc_effects_ignore_bad_targets():
    state = new_game()
    CreateTokenCopyOfTargetPermanent(target_filter=IsArtifact()).resolve(
        state, 0, (("permanent", 77),),
    )
    assert "copy of target" in CreateTokenCopyOfTargetPermanent(
        target_filter=IsArtifact(), label="artifact",
    ).describe()


def test_value_predicates_reject_players():
    state = new_game()
    assert not HasCardType("Instant").test(state.players[0], state)
    assert not HasManaValueAtMostColorsSpent().test(state.players[0], state)
    ring = put(state, "Sol Ring", controller=1)
    assert not HasManaValueAtMostColorsSpent().test(ring, state)
