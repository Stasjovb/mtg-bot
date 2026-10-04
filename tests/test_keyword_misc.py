"""Ward—Pay N life, energy, Threshold, and the spell-type cast-trigger
conditions."""

from __future__ import annotations

from mtg_bot import apply
from mtg_bot.actions import ActivateAbility, CastSpell, drain_stack
from mtg_bot.agents import Agent
from mtg_bot.cards import BASIC_LANDS, make_creature
from mtg_bot.cards.base import ActivatedAbility, ActivationCost, DrawCards, make_instant
from mtg_bot.cards.parser.activated import _parse_activation_cost
from mtg_bot.cards.parser.effects import _parse_effect
from mtg_bot.cards.parser.printing_keywords import _parse_ward_pay_life_line
from mtg_bot.cards.parser.source import _build_printing
from mtg_bot.cards.parser.triggers import (
    _parse_intervening_if_phrase,
    _parse_triggered_ability_line,
)
from mtg_bot.effects.generic.destroy import DestroyTargetCreature
from mtg_bot.effects.generic.keyword_actions import GetEnergy
from mtg_bot.effects.object_predicates import HasCardType
from mtg_bot.effects.state_predicates import CardsInGraveyardAtLeast
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step


class _Agent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _state(p0_life=20) -> GameState:
    state = GameState()
    state.players.append(Player(id=0, life=p0_life, agent=_Agent()))
    state.players.append(Player(id=1, agent=_Agent()))
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner, zone=Zone.BATTLEFIELD):
    obj = state.new_object(printing, owner, zone)
    obj.summoning_sick = False
    {
        Zone.HAND: state.players[owner].hand,
        Zone.LIBRARY: state.players[owner].library,
        Zone.GRAVEYARD: state.players[owner].graveyard,
        Zone.BATTLEFIELD: state.battlefield,
    }[zone].append(obj)
    return obj


MURDER = make_instant("Test Murder", "{B}", DestroyTargetCreature())


# ---------------------------------------------------------------- ward—pay life


def _witch_card():
    return {
        "name": "Life Warded", "type_line": "Creature — Human Warlock",
        "mana_cost": "{2}{B}", "power": "3", "toughness": "2",
        "oracle_text": "Menace\nWard—Pay 3 life.", "layout": "normal",
    }


def test_ward_pay_life_parses_onto_creature():
    assert _parse_ward_pay_life_line("Ward—Pay 3 life.") == 3
    assert _parse_ward_pay_life_line("Ward—Pay X life.") is None
    printing = _build_printing(_witch_card())
    assert printing.ward_life_cost == 3 and "menace" in printing.keywords


def test_ward_pay_life_is_paid_by_the_opposing_caster():
    state = _state()
    _put(state, BASIC_LANDS["Swamp"], 0)
    witch = _put(state, _build_printing(_witch_card()), 1)
    murder = _put(state, MURDER, 0, Zone.HAND)
    apply(state, CastSpell(murder.id), player_id=0)
    drain_stack(state)
    assert state.players[0].life == 17
    assert witch not in state.battlefield


def test_ward_pay_life_counters_when_caster_cannot_pay():
    state = _state(p0_life=2)
    _put(state, BASIC_LANDS["Swamp"], 0)
    witch = _put(state, _build_printing(_witch_card()), 1)
    murder = _put(state, MURDER, 0, Zone.HAND)
    apply(state, CastSpell(murder.id), player_id=0)
    drain_stack(state)
    assert witch in state.battlefield
    assert state.players[0].life == 2


# ---------------------------------------------------------------- energy


def test_energy_phrases_and_cost_piece():
    assert _parse_effect("you get {E}{E}{E}") == GetEnergy(amount=3)
    seq = _parse_effect("you gain 1 life and get {E}")
    assert seq.effects[1] == GetEnergy(amount=1)
    assert _parse_activation_cost("Pay {E}{E}").pay_energy == 2
    assert _parse_activation_cost("Pay {E}, Pay {E}") is None
    assert GetEnergy(amount=2).describe() == "you get {E}{E}"


def test_energy_is_gained_and_spent():
    state = _state()
    GetEnergy(amount=1).resolve(state, 0, ())
    battery = make_creature(
        "Battery", "{1}", 1, 1,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(pay_energy=2), effect=DrawCards(amount=1),
            ),
        ),
    )
    obj = _put(state, battery, 0)
    _put(state, BASIC_LANDS["Island"], 0, Zone.LIBRARY)
    act = ActivateAbility(source_id=obj.id, ability_index=0)
    assert act not in legal_actions(state, 0)
    GetEnergy(amount=1).resolve(state, 0, ())
    assert act in legal_actions(state, 0)
    apply(state, act, player_id=0)
    drain_stack(state)
    assert state.players[0].energy == 0
    assert len(state.players[0].hand) == 1


# ---------------------------------------------------------------- threshold / cast triggers


def test_threshold_gate():
    pred = _parse_intervening_if_phrase("there are seven or more cards in your graveyard")
    assert pred.inner == CardsInGraveyardAtLeast(7)
    state = _state()
    for _ in range(6):
        _put(state, BASIC_LANDS["Swamp"], 0, Zone.GRAVEYARD)
    assert not pred.inner.test(state, 0)
    _put(state, BASIC_LANDS["Swamp"], 0, Zone.GRAVEYARD)
    assert pred.inner.test(state, 0)


def test_noncreature_cast_trigger_fires_only_for_noncreature_spells():
    ability = _parse_triggered_ability_line(
        "Whenever you cast a noncreature spell, you gain 1 life."
    )
    watcher = make_creature("Watcher", "{U}", 1, 1, triggered_abilities=(ability,))
    state = _state()
    _put(state, watcher, 0)
    for _ in range(3):
        _put(state, BASIC_LANDS["Swamp"], 0)
    _put(state, make_creature("Victim", "{G}", 1, 1), 1)
    murder = _put(state, MURDER, 0, Zone.HAND)
    apply(state, CastSpell(murder.id), player_id=0)
    drain_stack(state)
    assert state.players[0].life == 21
    bear = _put(state, make_creature("Bear", "{B}", 2, 2), 0, Zone.HAND)
    apply(state, CastSpell(bear.id), player_id=0)
    drain_stack(state)
    assert state.players[0].life == 21


def test_other_cast_conditions_parse():
    for line in (
        "Whenever you cast a creature spell, draw a card.",
        "Whenever you cast an instant or sorcery spell, draw a card.",
    ):
        assert _parse_triggered_ability_line(line) is not None


def test_has_card_type_predicate():
    state = _state()
    obj = _put(state, MURDER, 0, Zone.HAND)
    assert HasCardType("Instant").test(obj, state)
    assert not HasCardType("Creature").test(obj, state)
    assert not HasCardType("Instant").test(object(), state)


# ---------------------------------------------------------------- infect / shadow / battle cry / devoid / persist / ward-in-line


def test_new_keyword_lines_parse():
    from mtg_bot.cards.parser.keywords import _parse_keyword_line
    from mtg_bot.cards.parser.printing_keywords import _parse_keyword_line_with_ward

    assert _parse_keyword_line("Trample, infect, indestructible") == (
        "trample", "infect", "indestructible",
    )
    for line, kw in (("Shadow", "shadow"), ("Battle cry", "battle cry"),
                     ("Devoid", "devoid"), ("Persist", "persist")):
        assert _parse_keyword_line(line) == (kw,)
    assert _parse_keyword_line_with_ward("Flying, ward {1}") == (("flying",), "{1}")
    assert _parse_keyword_line_with_ward("Flying, ward—Pay 2 life") is None
    assert _parse_keyword_line_with_ward("Banding, ward {1}") is None


def test_keyword_line_with_ward_builds_ward_cost():
    printing = _build_printing({
        "name": "Warded Flier", "type_line": "Creature — Sphinx",
        "mana_cost": "{3}{U}", "power": "2", "toughness": "3",
        "oracle_text": "Flying, ward {1}", "layout": "normal",
    })
    assert "flying" in printing.keywords and printing.ward_cost_str == "{1}"


def test_shadow_blocking_rules():
    from mtg_bot.combat import can_block

    state = _state()
    shade = _put(state, make_creature("Shade", "{B}", 1, 1, keywords={"shadow"}), 0)
    shade2 = _put(state, make_creature("Shade2", "{B}", 1, 1, keywords={"shadow"}), 1)
    plain = _put(state, make_creature("Plain", "{G}", 1, 1), 1)
    assert not can_block(state, plain, shade)
    assert can_block(state, shade2, shade)
    assert not can_block(state, shade2, _put(state, make_creature("P0", "{G}", 1, 1), 0))


def test_battle_cry_pumps_other_attackers():
    from tests._rules_helpers import _simulate_combat_step

    state = _state()
    crier = _put(state, make_creature("Crier", "{R}", 1, 1, keywords={"battle cry"}), 0)
    buddy = _put(state, make_creature("Buddy", "{R}", 2, 2), 0)
    _simulate_combat_step(state, [crier.id, buddy.id])
    assert state.players[1].life == 20 - 1 - 3


def test_devoid_is_colorless():
    from mtg_bot.game import effective_colors

    state = _state()
    obj = _put(state, make_creature("Void", "{1}{B}", 1, 1, keywords={"devoid"}), 0)
    assert effective_colors(state, obj) == frozenset()


def test_persist_returns_once_with_a_minus_counter():
    from mtg_bot.turn import move_off_battlefield

    state = _state()
    primus = _put(state, make_creature("Primus", "{5}{G}", 6, 6, keywords={"persist"}), 0)
    move_off_battlefield(state, primus, destination="graveyard")
    drain_stack(state)
    assert primus in state.battlefield and primus.minus_one_counters == 1
    move_off_battlefield(state, primus, destination="graveyard")
    drain_stack(state)
    assert primus in state.players[0].graveyard


def test_persist_return_is_a_noop_if_card_left_graveyard():
    from mtg_bot.effects.generic.keyword_actions import ReturnPersistedCard

    state = _state()
    obj = _put(state, make_creature("Gone", "{1}", 1, 1), 0, Zone.HAND)
    state.resolving_source = obj
    ReturnPersistedCard().resolve(state, 0, ())
    state.resolving_source = None
    ReturnPersistedCard().resolve(state, 0, ())
    assert obj in state.players[0].hand
    assert "-1/-1" in ReturnPersistedCard().describe()


def test_infect_combat_damage_gives_poison():
    from tests._rules_helpers import _simulate_combat_step

    state = _state()
    atk = _put(state, make_creature("Infector", "{B}", 2, 2, keywords={"infect"}), 0)
    _simulate_combat_step(state, [atk.id])
    assert state.players[1].poison_counters == 2 and state.players[1].life == 20
