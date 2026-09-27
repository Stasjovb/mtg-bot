"""U/B cube creatures: Archon of Cruelty's target-opponent action list,
leaves-the-battlefield observers (Super Shredder), Squad / Offspring
token copies (Sicarian Infiltrator, Thundertrap Trainer), Magecraft's
cast-or-copy trigger and quoted token abilities (Sedgemoor Witch), and
multi-word ability-word prefixes."""

from __future__ import annotations

from mtg_bot.actions import (
    CastSpell,
    apply_action,
    drain_stack,
    push_spell_copy,
    put_into_battlefield,
)
from mtg_bot.cards.parser.cube_creatures_ub import (
    parse_ub_creature_line,
    parse_ub_effect,
    parse_ub_trigger_phrase,
)
from mtg_bot.cards.parser.effects import _parse_effect
from mtg_bot.cards.parser.keyword_actions import _synthesize_creature_token_effect
from mtg_bot.cards.parser.triggers import _strip_ability_word_prefix
from mtg_bot.creature_casting_ub import offer_creature_additional_costs
from mtg_bot.effects.combinators import Sequence
from mtg_bot.effects.generic.cube_creatures_ub import (
    CreateTokenCopiesOfSelf,
    TargetPlayerPerformsActions,
)
from mtg_bot.effects.predicates import Event
from mtg_bot.game import Zone
from tests._spells_b_helpers import PRINTINGS, ScriptedAgent, add, add_lands, make_state


def _names(zone):
    return [c.printing.name for c in zone]


# ---------------------------------------------------------------- Archon


def test_target_opponent_action_list_parses():
    eff = parse_ub_effect(
        "target opponent sacrifices a creature or planeswalker of their "
        "choice, discards a card, and loses 3 life"
    )
    assert isinstance(eff, TargetPlayerPerformsActions)
    assert [a[0] for a in eff.actions] == ["sacrifice", "discard", "lose_life"]
    assert "loses 3 life" in eff.describe()
    two = parse_ub_effect("target player discards two cards and loses 2 life")
    assert two.actions == (("discard", 2), ("lose_life", 2))
    assert not two.opponent_only
    assert parse_ub_effect("target opponent sacrifices a frobnicator") is None
    assert parse_ub_effect("target opponent loses 3 life and dances") is None


def test_you_subject_distributes_and_sentences_split():
    eff = parse_ub_effect("you draw a card and gain 3 life")
    assert isinstance(eff, Sequence) and len(eff.effects) == 2
    assert parse_ub_effect("you draw a card and frobnicate") is None
    both = _parse_effect(
        "target opponent loses 1 life and discards a card. You draw a card "
        "and gain 3 life"
    )
    assert isinstance(both, Sequence)
    assert parse_ub_effect(
        "target opponent loses 1 life and discards a card. Frobnicate"
    ) is None


def test_archon_etb_punishes_and_refills():
    agent1 = ScriptedAgent()
    state = make_state(agent1=agent1)
    victim = add(state, 1, "Dark Confidant", Zone.BATTLEFIELD)
    add(state, 1, "Island", Zone.HAND)
    add(state, 0, "Island", Zone.LIBRARY)
    archon = state.new_object(PRINTINGS["Archon of Cruelty"], 0, Zone.HAND)
    put_into_battlefield(state, archon, 0)
    drain_stack(state)
    p0, p1 = state.players
    assert victim not in state.battlefield
    assert p1.hand == [] and p1.life == 17
    assert _names(p0.hand) == ["Island"] and p0.life == 23
    # Nothing to sacrifice or discard: the life loss still happens.
    eff = PRINTINGS["Archon of Cruelty"].triggered_abilities[0].effect
    eff.effects[0].resolve(state, 0, (("player", 1),))
    assert p1.life == 14
    eff.effects[0].resolve(state, 0, ())
    assert eff.effects[0].legal_targets(state, 0) == [("player", 1)]


# ---------------------------------------------------------------- Super Shredder


def test_leaves_trigger_phrases():
    event, _ = parse_ub_trigger_phrase("another permanent leaves the battlefield")
    assert event is Event.LEAVES_BATTLEFIELD
    for phrase in (
        "a creature leaves the battlefield",
        "another nontoken creature you control leaves the battlefield",
        "an artifact leaves the battlefield",
        "a nonland permanent leaves the battlefield",
    ):
        assert parse_ub_trigger_phrase(phrase) is not None, phrase
    assert parse_ub_trigger_phrase("a frobnicator leaves the battlefield") is None


def test_super_shredder_grows_when_anything_else_leaves():
    from mtg_bot.turn import move_off_battlefield

    state = make_state()
    shredder = add(state, 0, "Super Shredder", Zone.BATTLEFIELD)
    other = add(state, 1, "Island", Zone.BATTLEFIELD)
    move_off_battlefield(state, other, "hand")
    drain_stack(state)
    assert shredder.plus_one_counters == 1
    move_off_battlefield(state, shredder, "graveyard")
    drain_stack(state)
    assert shredder.plus_one_counters == 1


# ---------------------------------------------------------------- Squad / Offspring


def test_squad_and_offspring_lines():
    squad = parse_ub_creature_line("Squad {2}", "X")
    assert squad.fields["squad_cost_str"] == "{2}"
    assert squad.triggers[0].effect == CreateTokenCopiesOfSelf(per_squad_payment=True)
    off = parse_ub_creature_line("Offspring {4}", "X")
    assert off.triggers[0].effect == CreateTokenCopiesOfSelf(base_pt=(1, 1))
    assert parse_ub_creature_line("Squad {Q}", "X") is None
    assert "squad payment" in CreateTokenCopiesOfSelf(per_squad_payment=True).describe()
    assert "1/1" in CreateTokenCopiesOfSelf(base_pt=(1, 1)).describe()


def test_sicarian_infiltrator_squad_twice():
    agent = ScriptedAgent(x=[2])
    state = make_state(agent0=agent)
    add_lands(state, 0, "Island", 7)
    add(state, 0, "Island", Zone.LIBRARY)
    for _ in range(3):
        add(state, 0, "Island", Zone.LIBRARY)
    card = add(state, 0, "Sicarian Infiltrator", Zone.HAND)
    apply_action(state, 0, CastSpell(card.id))
    drain_stack(state)
    infiltrators = [
        o for o in state.battlefield if o.printing.name == "Sicarian Infiltrator"
    ]
    assert len(infiltrators) == 3
    assert sum(o.printing.is_token for o in infiltrators) == 2
    # Each copy's own "Benediction" ETB drew a card; tokens paid no squad.
    assert len(state.players[0].hand) == 3
    assert all(o.squad_paid_count == 0 for o in infiltrators if o.printing.is_token)


def test_squad_zero_payments_when_unaffordable():
    state = make_state()
    add_lands(state, 0, "Island", 3)
    card = add(state, 0, "Sicarian Infiltrator", Zone.HAND)
    apply_action(state, 0, CastSpell(card.id))
    drain_stack(state)
    assert [o.printing.name for o in state.battlefield].count(
        "Sicarian Infiltrator"
    ) == 1


def test_thundertrap_trainer_offspring_token_is_one_one():
    state = make_state()
    add_lands(state, 0, "Island", 6)
    for _ in range(8):
        add(state, 0, "Island", Zone.LIBRARY)
    card = add(state, 0, "Thundertrap Trainer", Zone.HAND)
    apply_action(state, 0, CastSpell(card.id))
    drain_stack(state)
    trainers = [o for o in state.battlefield if o.printing.name == "Thundertrap Trainer"]
    assert len(trainers) == 2
    token = next(o for o in trainers if o.printing.is_token)
    assert (token.printing.power, token.printing.toughness) == (1, 1)


def test_offspring_declined_and_reanimated_objects_pay_nothing():
    agent = ScriptedAgent(yes_no=[False])
    state = make_state(agent0=agent)
    add_lands(state, 0, "Island", 6)
    card = add(state, 0, "Thundertrap Trainer", Zone.HAND)
    cost = offer_creature_additional_costs(
        state, 0, card, card.printing.mana_cost,
    )
    assert cost == card.printing.mana_cost and not card.offspring_paid
    # A flag left on an object that enters some other way is cleared.
    card.offspring_paid = True
    state.players[0].hand.remove(card)
    put_into_battlefield(state, card, 0)
    assert not card.offspring_paid
    # No source: nothing is created.
    state.resolving_source = None
    CreateTokenCopiesOfSelf().resolve(state, 0, ())


# ---------------------------------------------------------------- Magecraft


def test_sedgemoor_witch_makes_pests_on_cast_and_copy():
    state = make_state()
    add(state, 0, "Sedgemoor Witch", Zone.BATTLEFIELD)
    add_lands(state, 0, "Mountain", 1)
    bolt = add(state, 0, "Lightning Bolt", Zone.HAND)
    apply_action(state, 0, CastSpell(bolt.id))
    push_spell_copy(state, PRINTINGS["Lightning Bolt"], 0, (("player", 1),))
    drain_stack(state)
    pests = [o for o in state.battlefield if o.printing.name == "Pest"]
    assert len(pests) == 2
    pest = pests[0]
    assert pest.printing.triggered_abilities[0].event is Event.DIES
    from mtg_bot.turn import move_off_battlefield

    life = state.players[0].life
    move_off_battlefield(state, pest, "graveyard")
    drain_stack(state)
    assert state.players[0].life == life + 1


def test_quoted_token_ability_must_parse():
    assert _synthesize_creature_token_effect(
        'create a 1/1 black Pest creature token with "Frobnicate."'
    ) is None


def test_multiword_ability_word_prefix():
    assert _strip_ability_word_prefix(
        "Benediction of the Omnissiah — When this creature enters, draw a card."
    ) == "When this creature enters, draw a card."
    assert _strip_ability_word_prefix(
        "Wasp's Sting — When this creature enters, draw a card."
    ) == "When this creature enters, draw a card."
