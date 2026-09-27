"""Cube W/G creatures built on the R/multi/colorless bucket's cast and
graveyard substrate: Fanatic of Rhonas (Ferocious mana ability,
Eternalize), Sage of the Skies ("copy this spell"), Sowing Mycospawn
(Kicker + "if it was kicked" cast trigger), Surrak, Elusive Hunter
("a creature spell you control becomes the target")."""

from __future__ import annotations

from mtg_bot.actions import ActivateAbility, CastSpell, apply_action
from mtg_bot.cards.parser.activated import _parse_activated_ability_line
from mtg_bot.cards.parser.creature_wg_effects import (
    parse_wg_effect,
    parse_wg_intervening_if,
    parse_wg_trigger_phrase,
)
from mtg_bot.cards.parser.creature_wg_lines import parse_wg_creature_line
from mtg_bot.effects.generic.cube_creatures_wg import (
    CastAnotherSpellThisTurn,
    CopyThisSpell,
    CreateTokenCopyOfSource,
    ThisSpellWasKicked,
    eternalized_printing,
)
from mtg_bot.effects.generic.cube_creatures_rmc import fire_becomes_target
from mtg_bot.game import Zone, effective_colors
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step
from tests._wg_helpers import (
    add_lands,
    bear,
    cube,
    drain,
    make_state,
    put,
)


# ---------------------------------------------------------------------
# Fanatic of Rhonas
# ---------------------------------------------------------------------


def test_ferocious_rider_parses_to_the_power_gate():
    ab = _parse_activated_ability_line(
        "{T}: Add {G}{G}{G}{G}. Activate only if you control a creature with "
        "power four or greater."
    )
    assert ab.cost.requires_own_creature_power_at_least == 4 and ab.is_mana_ability
    # Only one power rider per line.
    assert _parse_activated_ability_line(
        "{T}: Add {G}. Activate only if you control a creature with power 4 "
        "or greater. Activate only if you control a creature with power 5 or "
        "greater."
    ) is None


def test_fanatic_of_rhonas_ferocious_mana_needs_a_big_creature():
    pr = cube()["Fanatic of Rhonas"]
    small, big = pr.activated_abilities
    assert big.cost.requires_own_creature_power_at_least == 4
    state = make_state()
    fan = put(state, 0, pr)
    state.priority_player_idx = 0
    ferocious = ActivateAbility(source_id=fan.id, ability_index=1)
    assert ActivateAbility(source_id=fan.id, ability_index=0) in legal_actions(state, 0)
    assert ferocious not in legal_actions(state, 0)
    put(state, 0, bear("Big", power=4, toughness=4))
    assert ferocious in legal_actions(state, 0)
    apply_action(state, 0, ferocious)
    assert [c.color for c in state.players[0].mana_pool] == ["G"] * 4


def test_fanatic_of_rhonas_eternalize_from_graveyard():
    pr = cube()["Fanatic of Rhonas"]
    (eternalize,) = pr.graveyard_activated_abilities
    assert eternalize.sorcery_speed and eternalize.cost.mana_str == "{2}{G}{G}"
    state = make_state()
    fan = put(state, 0, pr, Zone.GRAVEYARD)
    add_lands(state, 0, "Forest", 4)
    state.priority_player_idx = 0
    act = ActivateAbility(source_id=fan.id, ability_index=0)
    assert act in legal_actions(state, 0)
    state.step = Step.BEGINNING_OF_COMBAT
    assert act not in legal_actions(state, 0)  # only as a sorcery
    state.step = Step.PRECOMBAT_MAIN
    apply_action(state, 0, act)
    assert fan in state.players[0].exile
    drain(state)
    (tok,) = [o for o in state.battlefield if o.printing.is_token]
    assert (tok.printing.power, tok.printing.toughness) == (4, 4)
    assert tok.printing.subtypes == ("Zombie", "Snake", "Druid")
    assert tok.printing.mana_cost_str == "" and tok.printing.mana_cost.total == 0
    assert effective_colors(state, tok) == frozenset({"B"})
    assert "Zombie" in CreateTokenCopyOfSource(eternalize=True).describe()


def test_eternalized_printing_keeps_a_single_zombie():
    zombie = bear("Walker", subtypes=("Zombie",))
    assert eternalized_printing(zombie).subtypes == ("Zombie",)


def test_eternalize_and_kicker_lines():
    card = {"name": "Thing", "type_line": "Creature — Thing"}
    assert parse_wg_creature_line("Eternalize {3}", card).fields[
        "graveyard_activated_abilities"
    ]
    assert parse_wg_creature_line("Kicker {1}{C}", card).fields["kicker_cost_str"] == "{1}{C}"
    assert parse_wg_creature_line("Eternalize", card) is None
    assert parse_wg_creature_line("Kicker", card) is None


# ---------------------------------------------------------------------
# Sage of the Skies
# ---------------------------------------------------------------------


def test_sage_of_the_skies_copies_itself_after_another_spell():
    pr = cube()["Sage of the Skies"]
    (trig,) = pr.triggered_abilities
    assert isinstance(trig.effect, CopyThisSpell)
    state = make_state()
    add_lands(state, 0, "Plains", 6)
    state.priority_player_idx = 0
    first = put(state, 0, pr, Zone.HAND)
    apply_action(state, 0, CastSpell(first.id))
    assert len(state.stack) == 1  # first spell this turn: no copy trigger
    drain(state)
    second = put(state, 0, pr, Zone.HAND)
    apply_action(state, 0, CastSpell(second.id))
    assert len(state.stack) == 2  # spell + copy trigger
    drain(state)
    sages = [o for o in state.battlefield if o.printing.name == "Sage of the Skies"]
    assert len(sages) == 3
    assert sum(o.printing.is_token for o in sages) == 1
    assert state.players[0].spells_cast_this_turn == 2  # the copy isn't cast


def test_copy_this_spell_without_the_spell_does_nothing():
    state = make_state()
    state.resolving_source = put(state, 0, bear())
    CopyThisSpell().resolve(state, 0)
    state.resolving_source = None
    CopyThisSpell().resolve(state, 0)
    assert not state.stack
    assert CopyThisSpell().describe() == "copy this spell"
    assert parse_wg_effect("copy this spell") == CopyThisSpell()


def test_copy_this_spell_copies_a_nonpermanent_spell_as_is():
    from mtg_bot.actions import StackItem

    state = make_state()
    bolt = state.new_object(cube()["Lightning Bolt"], owner_id=0, zone=Zone.STACK)
    state.stack.append(
        StackItem(source=bolt, controller_id=0, targets=(("player", 1),))
    )
    state.resolving_source = bolt
    CopyThisSpell().resolve(state, 0)
    state.resolving_source = None
    copy = state.stack[-1].source
    assert copy.is_spell_copy and not copy.printing.is_token
    assert state.stack[-1].targets == (("player", 1),)


def test_cast_another_spell_this_turn_predicate():
    state = make_state()
    src = put(state, 0, bear())
    pred = CastAnotherSpellThisTurn()
    assert not pred.matches(state, {}, src)
    state.players[0].spells_cast_this_turn = 1
    assert pred.matches(state, {}, src)
    assert not pred.matches(state, {}, object())  # no controller


# ---------------------------------------------------------------------
# Sowing Mycospawn
# ---------------------------------------------------------------------


def test_sowing_mycospawn_kicked_exiles_a_land():
    pr = cube()["Sowing Mycospawn"]
    assert pr.kicker_cost_str == "{1}{C}"
    fetch, kicked = pr.triggered_abilities
    assert isinstance(kicked.predicate.right, ThisSpellWasKicked)
    state = make_state()
    add_lands(state, 0, "Forest", 6)
    their_land = put(state, 1, "Island")
    forest = put(state, 0, "Forest", Zone.LIBRARY)
    state.priority_player_idx = 0
    myco = put(state, 0, pr, Zone.HAND)
    state.players[0].agent.scripts["target"] = [("permanent", their_land.id)]
    state.players[0].agent.scripts["library"] = [forest.id]
    apply_action(state, 0, CastSpell(myco.id, kicked=True))
    assert len(state.stack) == 3  # spell + both cast triggers
    drain(state)
    assert their_land in state.players[1].exile
    assert forest in state.battlefield and myco in state.battlefield


def test_sowing_mycospawn_unkicked_only_fetches():
    state = make_state()
    add_lands(state, 0, "Forest", 4)
    put(state, 1, "Island")
    state.priority_player_idx = 0
    myco = put(state, 0, "Sowing Mycospawn", Zone.HAND)
    apply_action(state, 0, CastSpell(myco.id))
    assert len(state.stack) == 2  # spell + the search trigger
    drain(state)
    assert not state.players[1].exile


def test_this_spell_was_kicked_needs_the_spell_on_the_stack():
    state = make_state()
    assert not ThisSpellWasKicked().matches(state, {}, put(state, 0, bear()))


def test_cast_trigger_intervening_ifs():
    assert parse_wg_intervening_if("it was kicked") == ThisSpellWasKicked()
    assert parse_wg_intervening_if(
        "you've cast another spell this turn"
    ) == CastAnotherSpellThisTurn()
    assert parse_wg_intervening_if("you're the monarch") is None


# ---------------------------------------------------------------------
# Surrak, Elusive Hunter
# ---------------------------------------------------------------------


def _surrak_state():
    state = make_state()
    surrak = put(state, 0, "Surrak, Elusive Hunter")
    for i in range(5):
        put(state, 0, "Forest", Zone.LIBRARY)
    return state, surrak


def test_surrak_draws_when_an_opponent_targets_your_creature():
    pr = cube()["Surrak, Elusive Hunter"]
    assert pr.spell_is_uncounterable and "trample" in pr.keywords
    state, surrak = _surrak_state()
    bolt = put(state, 1, "Lightning Bolt", Zone.HAND)
    add_lands(state, 1, "Mountain", 1)
    state.active_player_idx = 1
    state.priority_player_idx = 1
    state.players[1].agent.scripts["target"] = [("creature", surrak.id)]
    apply_action(state, 1, CastSpell(bolt.id))
    drain(state)
    assert len(state.players[0].hand) == 1


def test_surrak_draws_when_an_opponent_targets_your_creature_spell():
    state, surrak = _surrak_state()
    add_lands(state, 0, "Forest", 2)
    state.priority_player_idx = 0
    spell = put(state, 0, bear(), Zone.HAND)
    apply_action(state, 0, CastSpell(spell.id))
    counter = put(state, 1, "Counterspell", Zone.HAND)
    add_lands(state, 1, "Island", 2)
    state.priority_player_idx = 1
    state.players[1].agent.scripts["target"] = [("stack", 0)]
    apply_action(state, 1, CastSpell(counter.id))
    assert len(state.stack) == 3  # bear, Counterspell, Surrak's trigger
    drain(state)
    assert [c.printing.name for c in state.players[0].hand] == ["Forest"]


def test_surrak_ignores_own_targets_players_and_noncreature_spells():
    state, surrak = _surrak_state()
    # Your own spell targeting your creature: no draw.
    fire_becomes_target(state, (("creature", surrak.id),), surrak, 0)
    # An opponent targeting you (a player): no draw.
    fire_becomes_target(state, (("player", 0),), surrak, 1)
    assert not state.stack
    # An opponent targeting your noncreature spell on the stack.
    from mtg_bot.actions import StackItem

    bolt = state.new_object(cube()["Lightning Bolt"], owner_id=0, zone=Zone.STACK)
    bolt.controller_id = 0
    state.stack.append(StackItem(source=bolt, controller_id=0, targets=()))
    fire_becomes_target(state, (("stack_spell", bolt.id),), surrak, 1)
    assert len(state.stack) == 1
    # A stale / ability target: nothing.
    fire_becomes_target(state, (("stack", 7), ("stack_spell", 999)), surrak, 1)
    assert len(state.stack) == 1


def test_surrak_trigger_phrase_shape():
    event, _ = parse_wg_trigger_phrase(
        "a creature you control or a creature spell you control becomes the "
        "target of a spell or ability an opponent controls"
    )
    assert event.value == "becomes_target"
