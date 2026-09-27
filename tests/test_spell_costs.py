"""Alternative costs, one-of additional costs, and resolution-time spell
conditionals for PowerLSV cube spells (``mtg_bot.cards.spell_costs``,
``mtg_bot.effects.generic.cast_conditionals``), end-to-end through the
real cast pipeline."""

from __future__ import annotations

import pytest

from mtg_bot.actions import CastSpell
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.cards.spell_costs import (
    AdditionalCostOption,
    AlternativeCost,
    additional_option_payable,
    select_alternative_cost,
    pay_additional_cost_option,
)
from mtg_bot.effects.combinators import IfConditionElse
from mtg_bot.effects.generic.cast_conditionals import (
    AnOpponentDrawsCards,
    PermanentLeftYourControlThisTurn,
    SpellWasKicked,
)
from mtg_bot.effects.generic.damage import DealDamage
from mtg_bot.effects.object_predicates import IsCreature
from mtg_bot.game import Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import run_cleanup_step

from tests._spells_a_helpers import (
    ScriptedAgent,
    cast,
    cast_and_resolve,
    cube,
    lands,
    new_game,
    put,
    resolve,
    to_hand,
    to_library,
)


def _casts(state, pid, card):
    return [
        a for a in legal_actions(state, pid)
        if isinstance(a, CastSpell) and a.card_id == card.id
    ]


def _bolt_on_stack(state, caster=1):
    lands(state, caster, "Mountain", 1)
    bolt = to_hand(state, "Lightning Bolt", owner=caster)
    cast(state, caster, bolt)
    state.priority_player_idx = 0
    return bolt


# ---------- Force of Will ----------


def test_force_of_will_castable_for_free_by_pitching_a_blue_card():
    state = new_game()
    bolt = _bolt_on_stack(state)
    fow = to_hand(state, "Force of Will")
    pitch = to_hand(state, "Counterspell")
    # The alternative cost rides the "cast without paying its mana
    # cost" action variant (shared with alt_casting's pitch costs).
    assert _casts(state, 0, fow) == [CastSpell(fow.id, cast_for_free=True)]
    cast(state, 0, fow, cast_for_free=True)
    assert state.stack[-1].alt_cost_paid
    assert state.players[0].life == 19
    assert pitch in state.players[0].exile
    resolve(state)
    assert state.stack[-1].countered
    resolve(state)
    assert bolt in state.players[1].graveyard


def test_force_of_will_needs_another_blue_card_or_mana():
    state = new_game()
    _bolt_on_stack(state)
    fow = to_hand(state, "Force of Will")
    to_hand(state, "Lightning Bolt")  # red: can't be pitched
    assert _casts(state, 0, fow) == []


def test_force_of_will_hard_cast_when_both_are_payable():
    state = new_game()
    _bolt_on_stack(state)
    lands(state, 0, "Island", 5)
    fow = to_hand(state, "Force of Will")
    pitch = to_hand(state, "Counterspell")
    assert set(_casts(state, 0, fow)) == {
        CastSpell(fow.id), CastSpell(fow.id, cast_for_free=True),
    }
    cast(state, 0, fow)
    assert not state.stack[-1].alt_cost_paid
    assert pitch in state.players[0].hand
    assert state.players[0].life == 20


def test_force_of_will_pitch_when_both_are_payable():
    state = new_game()
    _bolt_on_stack(state)
    islands = lands(state, 0, "Island", 5)
    fow = to_hand(state, "Force of Will")
    to_hand(state, "Counterspell")
    cast(state, 0, fow, cast_for_free=True)
    assert state.stack[-1].alt_cost_paid
    assert not any(i.tapped for i in islands)


# ---------- Force of Negation / Force of Vigor ----------


def test_force_of_negation_alt_cost_only_on_opponents_turn():
    state = new_game()
    fon = to_hand(state, "Force of Negation")
    to_hand(state, "Counterspell")
    _bolt_on_stack(state)
    state.active_player_idx = 0  # my turn: no free cast, no mana
    assert _casts(state, 0, fon) == []
    state.active_player_idx = 1
    assert _casts(state, 0, fon) == [CastSpell(fon.id, cast_for_free=True)]
    cast(state, 0, fon, cast_for_free=True)
    resolve(state)
    resolve(state)
    assert state.players[1].exile[-1].printing.name == "Lightning Bolt"


def test_force_of_vigor_destroys_up_to_two_artifacts_for_free():
    state = new_game()
    state.active_player_idx = 1
    a = put(state, "Sol Ring", controller=1)
    b = put(state, "Mind Stone", controller=1)
    fov = to_hand(state, "Force of Vigor")
    to_hand(state, "Llanowar Elves")
    assert _casts(state, 0, fov) == [CastSpell(fov.id, cast_for_free=True)]
    cast_and_resolve(state, 0, fov, cast_for_free=True)
    assert a not in state.battlefield and b not in state.battlefield


# ---------- Daze / Snuff Out / Mine Collapse / Baleful Mastery ----------


def test_daze_returns_an_island_and_taxes_the_spell():
    state = new_game(agent1=ScriptedAgent(yes=False))
    _bolt_on_stack(state)
    island = put(state, "Island", controller=0)
    island.tapped = True
    daze = to_hand(state, "Daze")
    assert _casts(state, 0, daze) == [CastSpell(daze.id, cast_for_free=True)]
    cast(state, 0, daze, cast_for_free=True)
    assert island in state.players[0].hand
    resolve(state)
    assert state.stack[-1].countered


def test_snuff_out_requires_a_swamp_and_costs_four_life():
    state = new_game()
    elf = put(state, "Llanowar Elves", controller=1)
    snuff = to_hand(state, "Snuff Out")
    assert _casts(state, 0, snuff) == []
    swamp = put(state, "Swamp", controller=0)
    swamp.tapped = True
    assert _casts(state, 0, snuff) == [CastSpell(snuff.id, cast_for_free=True)]
    cast_and_resolve(state, 0, snuff, cast_for_free=True)
    assert state.players[0].life == 16
    assert elf in state.players[1].graveyard


def test_snuff_out_cannot_target_black_creatures():
    state = new_game()
    put(state, "Griselbrand", controller=1)
    assert cube("Snuff Out").spell_effect.legal_targets(state, 0) == []


def test_mine_collapse_sacrifices_a_mountain_on_your_turn_only():
    state = new_game()
    mountain = put(state, "Mountain", controller=0)
    mountain.tapped = True
    jace = put(state, "Jace, the Mind Sculptor", controller=1)
    mc = to_hand(state, "Mine Collapse")
    state.active_player_idx = 1
    state.priority_player_idx = 0
    assert _casts(state, 0, mc) == []
    state.active_player_idx = 0
    assert _casts(state, 0, mc) == [CastSpell(mc.id, cast_for_free=True)]
    cast_and_resolve(state, 0, mc, cast_for_free=True)
    assert mountain in state.players[0].graveyard
    assert jace in state.players[1].graveyard


def test_baleful_mastery_alt_cost_gives_opponent_a_card():
    state = new_game()
    lands(state, 0, "Swamp", 4)
    gris = put(state, "Griselbrand", controller=1)
    drawn = to_library(state, "Island", owner=1)
    cast_and_resolve(
        state, 0, to_hand(state, "Baleful Mastery"), cast_for_free=True,
    )
    assert gris in state.players[1].exile
    assert drawn in state.players[1].hand
    assert sum(1 for o in state.battlefield if o.tapped) == 2


def test_baleful_mastery_full_cost_gives_no_card():
    state = new_game()
    lands(state, 0, "Swamp", 4)
    gris = put(state, "Griselbrand", controller=1)
    drawn = to_library(state, "Island", owner=1)
    cast_and_resolve(state, 0, to_hand(state, "Baleful Mastery"))
    assert gris in state.players[1].exile
    assert drawn in state.players[1].library


# ---------- one-of additional costs ----------


def test_bitter_triumph_discard_or_pay_life():
    state = new_game(ScriptedAgent(mode=1))
    lands(state, 0, "Swamp", 2)
    elf = put(state, "Llanowar Elves", controller=1)
    keep = to_hand(state, "Island")
    cast_and_resolve(state, 0, to_hand(state, "Bitter Triumph"))
    assert state.players[0].life == 17
    assert keep in state.players[0].hand
    assert elf in state.players[1].graveyard


def test_bitter_triumph_discards_when_chosen():
    state = new_game(ScriptedAgent(mode=0))
    lands(state, 0, "Swamp", 2)
    put(state, "Llanowar Elves", controller=1)
    card = to_hand(state, "Island")
    cast_and_resolve(state, 0, to_hand(state, "Bitter Triumph"))
    assert card in state.players[0].graveyard
    assert state.players[0].life == 20


def test_bone_shards_needs_a_creature_or_a_card_to_discard():
    state = new_game()
    lands(state, 0, "Swamp", 1)
    put(state, "Llanowar Elves", controller=1)
    shards = to_hand(state, "Bone Shards")
    assert _casts(state, 0, shards) == []
    mine = put(state, "Birds of Paradise", controller=0)
    assert _casts(state, 0, shards) == [CastSpell(shards.id)]
    cast_and_resolve(state, 0, shards)
    assert mine in state.players[0].graveyard


def test_vicious_rivalry_pays_x_life_and_sweeps_mv_x_or_less():
    state = new_game(ScriptedAgent(x=2))
    lands(state, 0, "Swamp", 2)
    lands(state, 0, "Forest", 2)
    elf = put(state, "Llanowar Elves", controller=1)
    ring = put(state, "Sol Ring", controller=1)
    gris = put(state, "Griselbrand", controller=1)
    cast_and_resolve(state, 0, to_hand(state, "Vicious Rivalry"))
    assert state.players[0].life == 18
    assert elf not in state.battlefield and ring not in state.battlefield
    assert gris in state.battlefield


def test_pay_x_life_never_pays_the_whole_life_total():
    state = new_game(ScriptedAgent())  # x=None -> max
    card = to_hand(state, "Vicious Rivalry")
    state.players[0].hand.remove(card)
    state.players[0].life = 5
    from mtg_bot.alt_casting import choose_pay_x_life

    assert card.printing.additional_cost_pay_x_life
    assert choose_pay_x_life(state, 0, card) == 4


def test_additional_cost_option_validation_and_describe():
    with pytest.raises(ValueError):
        AdditionalCostOption(kind="tap")
    assert AdditionalCostOption(kind="discard", amount=2).describe() == (
        "discard 2 cards"
    )
    sac = AdditionalCostOption(
        kind="sacrifice", permanent_filter=IsCreature(), label="creature",
    )
    assert sac.describe() == "sacrifice a creature"
    state = new_game()
    card = to_hand(state, "Bone Shards")
    assert not additional_option_payable(state, 0, card, sac)
    assert additional_option_payable(
        state, 0, card, AdditionalCostOption(kind="pay_life", amount=1),
    )


def test_alternative_cost_describe_and_no_agent_default():
    alt = AlternativeCost(
        mana="{1}{B}", pay_life=1, exile_card_color="U",
        return_subtype="Island", sacrifice_subtype="Mountain",
        turn="not_yours", requires_control_subtype="Swamp",
    )
    text = alt.describe()
    assert text.startswith("if it's not your turn, if you control a Swamp")
    assert "exile a blue card" in text and "sacrifice a Mountain" in text
    assert AlternativeCost(turn="yours", pay_life=2).describe() == (
        "if it's your turn, pay 2 life"
    )
    state = new_game()
    state.players[0].agent = None
    fow = to_hand(state, "Force of Will")
    to_hand(state, "Counterspell")
    assert select_alternative_cost(state, 0, fow) == 0
    state.players[0].hand.clear()
    state.players[0].hand.append(fow)
    assert select_alternative_cost(state, 0, fow) is None


# ---------- resolution-time conditionals ----------


def test_burst_lightning_kicked_deals_four():
    state = new_game(ScriptedAgent(prefer=[("player", 1)]))
    lands(state, 0, "Mountain", 5)
    burst = to_hand(state, "Burst Lightning")
    cast_and_resolve(state, 0, burst, kicked=True)
    assert state.players[1].life == 16
    burst2 = to_hand(state, "Burst Lightning")
    for o in state.battlefield:
        o.tapped = False
    cast_and_resolve(state, 0, burst2)
    assert state.players[1].life == 14


def test_unholy_heat_delirium_deals_six():
    state = new_game()
    lands(state, 0, "Mountain", 2)
    gris = put(state, "Griselbrand", controller=1)
    cast_and_resolve(state, 0, to_hand(state, "Unholy Heat"))
    assert gris.damage == 2
    for printing in (
        cube("Llanowar Elves"), BASIC_LANDS["Island"],
        cube("Lightning Bolt"), cube("Sol Ring"),
    ):
        card = state.new_object(printing, 0, Zone.GRAVEYARD)
        state.players[0].graveyard.append(card)
    cast_and_resolve(state, 0, to_hand(state, "Unholy Heat"))
    assert gris in state.players[1].graveyard


def test_fatal_push_revolt_widens_to_mana_value_four():
    state = new_game()
    lands(state, 0, "Swamp", 2)
    kavu = put(state, "Flametongue Kavu", controller=1)  # MV 4
    cast_and_resolve(state, 0, to_hand(state, "Fatal Push"))
    assert kavu in state.battlefield  # MV 4 > 2, no revolt
    assert not state.players[0].permanent_left_battlefield_this_turn
    petal = put(state, "Lotus Petal", controller=0)
    from mtg_bot.turn import sacrifice

    sacrifice(state, petal)
    assert state.players[0].permanent_left_battlefield_this_turn
    cast_and_resolve(state, 0, to_hand(state, "Fatal Push"))
    assert kavu in state.players[1].graveyard


def test_revolt_flag_resets_at_cleanup():
    state = new_game()
    state.players[0].permanent_left_battlefield_this_turn = True
    run_cleanup_step(state)
    assert not state.players[0].permanent_left_battlefield_this_turn


def test_bounce_sets_revolt_for_controller():
    from mtg_bot.effects.generic.targets_helpers import _bounce_to_hand

    state = new_game()
    elf = put(state, "Llanowar Elves", controller=1)
    _bounce_to_hand(state, elf)
    assert state.players[1].permanent_left_battlefield_this_turn
    assert not state.players[0].permanent_left_battlefield_this_turn


def test_if_condition_else_targets_through_base_branch_and_describes():
    base = DealDamage(amount=1)
    eff = IfConditionElse(
        condition=SpellWasKicked(), then_effect=AnOpponentDrawsCards(),
    )
    state = new_game()
    assert not eff.requires_target()
    eff.resolve(state, 0)  # not kicked, no else branch: no-op
    assert "an opponent draws" in eff.describe()
    both = IfConditionElse(
        condition=PermanentLeftYourControlThisTurn(),
        then_effect=base, else_effect=base,
    )
    assert both.legal_targets(state, 0) == []
    assert "otherwise" in both.describe()


def test_an_opponent_draws_with_no_opponents_is_noop():
    state = new_game()
    state.players[1].has_lost = True
    AnOpponentDrawsCards(amount=2).resolve(state, 0)
    assert "draws" not in " ".join(state.log)
    assert AnOpponentDrawsCards(amount=2).describe() == (
        "an opponent draws 2 card(s)"
    )


# ---------- Teamwork (We Say Thee Nay!) ----------


def _bolt_for_nay(state):
    lands(state, 1, "Mountain", 3)
    bolt = to_hand(state, "Lightning Bolt", owner=1)
    cast(state, 1, bolt)
    return bolt


def test_we_say_thee_nay_with_teamwork_taxes_four():
    state = new_game(ScriptedAgent(yes=True), ScriptedAgent(yes=True))
    _bolt_for_nay(state)  # the opponent keeps {2} open, not {4}
    elves = [put(state, "Llanowar Elves", controller=0) for _ in range(2)]
    lands(state, 0, "Island", 2)
    nay = to_hand(state, "We Say Thee Nay!")
    assert nay.printing.teamwork_power == 2
    assert nay.printing.subtypes == ("Arcane",)
    cast(state, 0, nay)
    assert all(e.tapped for e in elves)
    resolve(state)
    assert state.stack[-1].countered


def test_we_say_thee_nay_without_teamwork_taxes_two():
    state = new_game(ScriptedAgent(yes=False), ScriptedAgent(yes=True))
    _bolt_for_nay(state)
    put(state, "Griselbrand", controller=0)
    lands(state, 0, "Island", 2)
    cast(state, 0, to_hand(state, "We Say Thee Nay!"))
    resolve(state)
    assert not state.stack[-1].countered  # opponent paid {2}


def test_teamwork_needs_enough_power():
    from mtg_bot.actions import _pay_teamwork

    state = new_game(ScriptedAgent(yes=True))
    put(state, "Llanowar Elves", controller=0)
    card = to_hand(state, "We Say Thee Nay!")
    assert _pay_teamwork(state, 0, card, 2) is False
    state.players[0].agent = None
    put(state, "Birds of Paradise", controller=0)
    put(state, "Elvish Mystic", controller=0)
    assert _pay_teamwork(state, 0, card, 2) is True


def test_teamwork_line_grammar():
    from mtg_bot.cards.parser.spell_cost_lines import parse_teamwork_line

    assert parse_teamwork_line("Teamwork 2 (As an additional cost ...)") == 2
    assert parse_teamwork_line("Teamwork") is None
