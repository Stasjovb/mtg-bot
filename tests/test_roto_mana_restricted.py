"""Vintage Roto P3: restricted mana and modal triggers on noncreature
permanents (The Mightstone and Weakstone)."""

from __future__ import annotations

from mtg_bot.actions import (
    CastSpell,
    _activate_ability,
    _coin_satisfies_context,
    apply_action,
    can_pay_cost,
    put_into_battlefield,
    resolve_top_of_stack,
)
from mtg_bot.cards.base import (
    ManaCost,
    make_artifact,
    make_creature,
    parse_mana_cost,
)
from mtg_bot.cards.parser.roto_mana import (
    extract_modal_trigger_blocks,
    parse_roto_mana_effect,
)
from mtg_bot.effects.combinators import ModalChooseOne
from mtg_bot.game import ManaCoin, Zone
from mtg_bot.legal import legal_actions

from tests._roto_helpers import arena, printing, put, to_hand, to_library

BEAR = make_creature("Bear", "{1}{G}", 2, 2)
GIANT = make_creature("Giant", "{4}", 5, 5)
ROCK = make_artifact("Rock", "{2}")
MIGHT = "The Mightstone and Weakstone"


def _enter(state, printing_, controller=0):
    obj = state.new_object(printing_, owner_id=controller, zone=Zone.STACK)
    put_into_battlefield(state, obj, controller)
    return obj


def test_mightstone_etb_is_a_modal_trigger():
    trig = printing(MIGHT).triggered_abilities[0]
    assert isinstance(trig.effect, ModalChooseOne)
    assert len(trig.effect.modes) == 2


def test_mightstone_etb_draw_mode():
    s = arena()
    for _ in range(3):
        to_library(s, BEAR, 0)
    s.players[0].agent.choose_mode = lambda state, pid, opts: 0
    _enter(s, printing(MIGHT), 0)
    resolve_top_of_stack(s)
    assert len(s.players[0].hand) == 2


def test_mightstone_etb_shrink_mode_kills_a_five_toughness_creature():
    from mtg_bot.turn import state_based_actions

    s = arena()
    giant = put(s, GIANT, 1)
    s.players[0].agent.choose_mode = lambda state, pid, opts: 1
    s.players[0].agent.targets = [("creature", giant.id)]
    _enter(s, printing(MIGHT), 0)
    resolve_top_of_stack(s)
    state_based_actions(s)
    assert giant not in s.battlefield


def _tap_mightstone(s):
    stone = put(s, printing(MIGHT), 0)
    _activate_ability(s, 0, stone.id, 0)
    return stone


def test_mightstone_mana_pays_for_artifact_spells_only():
    s = arena()
    _tap_mightstone(s)
    pool = s.players[0].mana_pool
    assert [c.color for c in pool] == ["C", "C"]
    assert all(c.spend_restriction == "not_nonartifact_spell" for c in pool)
    rock = to_hand(s, ROCK, 0)
    bear = to_hand(s, make_creature("Elk", "{2}", 2, 2), 0)
    acts = legal_actions(s, 0)
    assert CastSpell(rock.id) in acts
    assert CastSpell(bear.id) not in acts
    apply_action(s, 0, CastSpell(rock.id))
    assert s.players[0].mana_pool == []


def test_mightstone_mana_pays_for_activated_abilities():
    s = arena()
    _tap_mightstone(s)
    assert can_pay_cost(
        s, 0, parse_mana_cost("{2}"),
        spell_kind=frozenset({"spell", "activated_ability"}),
    )
    assert not can_pay_cost(s, 0, parse_mana_cost("{2}"))


def test_not_nonartifact_spell_coin_contexts():
    coin = ManaCoin(color="C", spend_restriction="not_nonartifact_spell")
    assert _coin_satisfies_context(coin, frozenset({"spell", "artifact_spell"}))
    assert _coin_satisfies_context(coin, "activated_ability")
    assert not _coin_satisfies_context(coin, "spell")
    # An unknown restriction tag is never satisfied.
    assert not _coin_satisfies_context(
        ManaCoin(color="C", spend_restriction="bogus"), "spell",
    )


def test_cant_be_spent_grammar_rejects_unknown_kinds():
    assert parse_roto_mana_effect(
        "add {C}. This mana can't be spent to cast creature spells"
    ) is None


def test_modal_block_extraction_paths():
    text = "When this artifact enters, choose one —\n• Draw a card.\n• Bogus frobnicate."
    assert extract_modal_trigger_blocks(text, "X") is None
    plain = "{T}: Add {C}."
    assert extract_modal_trigger_blocks(plain, "X") == (plain, ())
    # A header with no bullet lines after it is left in place.
    lone = "When this artifact enters, choose one —"
    assert extract_modal_trigger_blocks(lone, "X") == (lone, ())


# ---------------------------------------------------------------------------
# Cavern of Souls
# ---------------------------------------------------------------------------


def _goblin(name="Goblin Raider", cost="{1}"):
    return make_creature(name, cost, 1, 1, subtypes=("Goblin", "Warrior"))


def _elf(name="Elf Scout", cost="{1}"):
    return make_creature(name, cost, 1, 1, subtypes=("Elf",))


def _cavern_in_play(chosen_index=0):
    from mtg_bot.actions import PlayLand

    s = arena()
    to_library(s, _goblin(), 0)
    to_library(s, _elf(), 0)
    to_library(s, ROCK, 0)  # noncreature types aren't offered
    s.players[0].agent.choose_mode = lambda state, pid, opts: chosen_index
    cavern = to_hand(s, printing("Cavern of Souls"), 0)
    apply_action(s, 0, PlayLand(cavern.id))
    return s, cavern


def _any_color_index(cavern):
    from mtg_bot.effects.generic.roto_mana import (
        AddAnyColorManaForChosenCreatureType,
    )

    return next(
        i for i, a in enumerate(cavern.printing.activated_abilities)
        if isinstance(a.effect, AddAnyColorManaForChosenCreatureType)
    )


def test_cavern_chooses_among_owned_creature_types_as_it_enters():
    from mtg_bot.effects.generic.roto_mana import creature_types_owned_by

    s, cavern = _cavern_in_play(chosen_index=1)
    assert creature_types_owned_by(s, 0) == ["Elf", "Goblin", "Warrior"]
    assert cavern.chosen_creature_type == "Goblin"
    assert cavern.printing.produces == frozenset({"C"})


def test_cavern_mana_casts_only_the_chosen_type_and_it_cant_be_countered():
    from mtg_bot.effects.generic.stack_control import CounterTargetSpell

    s, cavern = _cavern_in_play(chosen_index=1)  # Goblin
    _activate_ability(s, 0, cavern.id, _any_color_index(cavern))
    coin = s.players[0].mana_pool[0]
    assert coin.spend_restriction == "creature_type:Goblin"
    goblin = to_hand(s, _goblin(), 0)
    elf = to_hand(s, _elf(), 0)
    acts = legal_actions(s, 0)
    assert CastSpell(goblin.id) in acts
    assert CastSpell(elf.id) not in acts
    apply_action(s, 0, CastSpell(goblin.id))
    assert goblin.cast_uncounterable
    assert CounterTargetSpell().legal_targets(s, 1) == []


def test_cavern_mana_with_a_changeling_and_without_a_choice():
    from dataclasses import replace

    from mtg_bot.effects.generic.roto_mana import (
        creature_types_owned_by,
        roto_coin_satisfies,
        roto_spell_kinds,
    )

    s, cavern = _cavern_in_play(chosen_index=0)  # Elf
    shifter = to_hand(
        s, replace(_elf("Mutavault Kin"), keywords=frozenset({"changeling"})), 0,
    )
    kinds = roto_spell_kinds(shifter)
    assert kinds == frozenset({"creature_type:*"})
    coin = ManaCoin(color="any", spend_restriction="creature_type:Elf")
    assert roto_coin_satisfies(coin, kinds)
    # Nothing chosen (no creature card owned): the mana pays for nothing.
    none_coin = ManaCoin(color="any", spend_restriction="creature_type:")
    assert not roto_coin_satisfies(none_coin, kinds)
    assert roto_spell_kinds(to_hand(s, ROCK, 0)) == frozenset()
    empty = arena()
    assert creature_types_owned_by(empty, 0) == []


def test_cavern_with_no_creature_cards_records_no_type():
    from mtg_bot.actions import PlayLand

    s = arena()
    cavern = to_hand(s, printing("Cavern of Souls"), 0)
    apply_action(s, 0, PlayLand(cavern.id))
    assert cavern.chosen_creature_type is None
    _activate_ability(s, 0, cavern.id, _any_color_index(cavern))
    assert s.players[0].mana_pool[0].spend_restriction == "creature_type:"
