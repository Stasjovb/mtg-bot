"""Roto P1: Chancellor of the Annex (opening-hand reveal), Jeskai
Ascendancy, The Queen of Dale (recruit), Harsh Mentor (activation
trigger), Strict Proctor (countering entering-caused triggers)."""

from __future__ import annotations

from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    apply_action,
    put_into_battlefield,
    resolve_top_of_stack,
)
from mtg_bot.cards.base import make_creature
from mtg_bot.cards.parser.roto_stack import parse_roto_stack_effect, parse_roto_stack_line
from mtg_bot.effects.generic.roto_stack import (
    CastersFirstSpellOfTheGame,
    CounterTriggerUnlessPays,
    Recruit,
    RevealForFirstSpellTax,
)
from mtg_bot.game import Zone, effective_power
from mtg_bot.legal import legal_actions
from mtg_bot.opening_hand import apply_opening_hand_actions
from mtg_bot.roto_restrictions import fire_entering_trigger_watchers

from tests._roto_helpers import (
    agent,
    arena,
    printing,
    put,
    to_hand,
    to_library,
)


def _lands(state, name, n, pid=0):
    return [put(state, printing(name), pid) for _ in range(n)]


def _cast(state, pid, card, **kw):
    state.priority_player_idx = pid
    apply_action(state, pid, CastSpell(card.id, **kw))


def _drain(state):
    while state.stack:
        resolve_top_of_stack(state)


def _bolt(state, pid=1, target=("player", 0)):
    bolt = to_hand(state, printing("Lightning Bolt"), pid)
    _lands(state, "Mountain", 1, pid)
    agent(state, pid).targets = [target]
    _cast(state, pid, bolt)
    return bolt


# ---------------------------------------------------------------------
# Chancellor of the Annex
# ---------------------------------------------------------------------


def test_chancellor_reveal_taxes_each_opponents_first_spell():
    state = arena(active=1)
    chancellor = to_hand(state, printing("Chancellor of the Annex"), 0)
    apply_opening_hand_actions(state, 1)
    assert chancellor in state.players[0].hand  # revealed, not played
    assert len(state.emblems) == 1
    bolt = _bolt(state)
    _drain(state)
    assert bolt in state.players[1].graveyard
    assert state.players[0].life == 20  # countered: no spare {1}
    # Only the first spell of the game.
    _bolt(state)
    assert len(state.stack) == 1
    _drain(state)
    assert state.players[0].life == 17


def test_chancellor_reveal_declined_and_own_spells_untaxed():
    state = arena(active=0)
    to_hand(state, printing("Chancellor of the Annex"), 0)
    agent(state, 0).yes = False
    apply_opening_hand_actions(state, 0)
    assert not state.emblems
    action = printing("Chancellor of the Annex").opening_hand_action
    assert isinstance(action, RevealForFirstSpellTax)
    assert action.available_to(0, 1)
    assert "reveal" in action.describe("Chancellor of the Annex")
    assert not CastersFirstSpellOfTheGame().matches(state, {}, None)


def test_chancellor_on_the_battlefield_taxes_every_opponent_spell():
    state = arena(active=1)
    put(state, printing("Chancellor of the Annex"), 0)
    _lands(state, "Mountain", 1, 1)  # pays {1} once
    _bolt(state)
    _drain(state)
    assert state.players[0].life == 17
    _bolt(state)
    _drain(state)
    assert state.players[0].life == 17


# ---------------------------------------------------------------------
# Jeskai Ascendancy
# ---------------------------------------------------------------------


def test_jeskai_ascendancy_pumps_and_untaps():
    state = arena(active=0)
    put(state, printing("Jeskai Ascendancy"), 0)
    bear = put(state, make_creature("Bear", "{1}{G}", 2, 2), 0, tapped=True)
    agent(state, 0).yes = False  # decline the loot
    _bolt(state, pid=0, target=("player", 1))
    _drain(state)
    assert not bear.tapped
    assert effective_power(state, bear) == 3


# ---------------------------------------------------------------------
# The Queen of Dale
# ---------------------------------------------------------------------


def test_queen_of_dale_recruits_on_the_first_noncreature_spell():
    state = arena(active=1)
    put(state, printing("The Queen of Dale"), 0)
    to_library(state, printing("Brainstorm"), 0)
    _bolt(state)
    _drain(state)
    # Drew Brainstorm, discarded it (nonland) -> a Human Soldier.
    assert any(o.printing.name == "Human Soldier" for o in state.battlefield)
    assert state.players[0].graveyard[-1].printing.name == "Brainstorm"


def test_recruit_discarding_a_land_makes_no_token():
    state = arena()
    to_library(state, printing("Island"), 0)
    Recruit().resolve(state, 0, ())
    assert not any(o.printing.name == "Human Soldier" for o in state.battlefield)
    # Empty hand and library: nothing to discard.
    Recruit().resolve(state, 0, ())
    assert Recruit().describe() == "recruit"


# ---------------------------------------------------------------------
# Harsh Mentor
# ---------------------------------------------------------------------


def _activate_first(state, obj, pid):
    state.priority_player_idx = pid
    acts = [
        a for a in legal_actions(state, pid)
        if isinstance(a, ActivateAbility) and a.source_id == obj.id
    ]
    apply_action(state, pid, acts[0])


def test_harsh_mentor_punishes_non_mana_activations():
    state = arena(active=1)
    put(state, printing("Harsh Mentor"), 0)
    waste = put(state, printing("Wasteland"), 1)
    put(state, printing("Seat of the Synod"), 0)
    agent(state, 1).targets = []
    abilities = waste.printing.activated_abilities
    idx = next(i for i, a in enumerate(abilities) if not a.is_mana_ability)
    apply_action(state, 1, ActivateAbility(waste.id, idx))
    assert state.stack[-1].ability is not None
    _drain(state)
    assert state.players[1].life == 18


def test_harsh_mentor_ignores_mana_abilities_and_own_activations():
    state = arena(active=1)
    put(state, printing("Harsh Mentor"), 0)
    ring = put(state, printing("Sol Ring"), 1)
    _activate_first(state, ring, 1)
    assert not state.stack
    assert state.players[1].life == 20
    state.active_player_idx = 0
    waste = put(state, printing("Wasteland"), 0)
    put(state, printing("Seat of the Synod"), 1)
    abilities = waste.printing.activated_abilities
    idx = next(i for i, a in enumerate(abilities) if not a.is_mana_ability)
    apply_action(state, 0, ActivateAbility(waste.id, idx))
    _drain(state)
    assert state.players[0].life == 20


# ---------------------------------------------------------------------
# Strict Proctor
# ---------------------------------------------------------------------


def _enter(state, printing_obj, pid):
    card = to_hand(state, printing_obj, pid)
    state.players[pid].hand.remove(card)
    card.zone = Zone.STACK
    put_into_battlefield(state, card, pid)
    return card


def test_strict_proctor_counters_etb_triggers_unless_paid():
    state = arena(active=1)
    put(state, printing("Strict Proctor"), 0)
    to_library(state, printing("Mother of Runes"), 1)
    _enter(state, printing("Ranger-Captain of Eos"), 1)
    assert len(state.stack) == 2  # the ETB trigger and Proctor's trigger
    assert state.stack[-1].source.printing.name == "Strict Proctor"
    _drain(state)
    assert any("triggered ability is countered" in line for line in state.log)
    assert not state.players[1].hand  # no search happened


def test_strict_proctor_trigger_paid():
    state = arena(active=1)
    put(state, printing("Strict Proctor"), 0)
    to_library(state, printing("Mother of Runes"), 1)
    _lands(state, "Plains", 2, 1)
    _enter(state, printing("Ranger-Captain of Eos"), 1)
    _drain(state)
    assert [c.printing.name for c in state.players[1].hand] == ["Mother of Runes"]


def test_counter_trigger_edges():
    eff = CounterTriggerUnlessPays(unless_pays="{2}")
    state = arena()
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("stack", 4),))
    _bolt(state)
    eff.resolve(state, 0, (("stack", 0),))  # a spell, not an ability
    assert not state.stack[0].countered
    assert "unless its controller pays {2}" in eff.describe()
    assert CounterTriggerUnlessPays().describe() == "counter that ability"
    fire_entering_trigger_watchers(state, 0)  # no watchers: no-op


# ---------------------------------------------------------------------
# Grammar edges
# ---------------------------------------------------------------------


def test_misc_grammar_edges():
    card = {"name": "X"}
    assert parse_roto_stack_line(
        "Whenever an opponent activates an ability of a wombat on the "
        "battlefield, if it isn't a mana ability, this creature deals 2 "
        "damage to that player.", card,
    ) is None
    assert parse_roto_stack_effect(
        "creatures you control get +1/+1 until end of turn. Untap those creatures"
    ) is not None


# ---------------------------------------------------------------------
# Aven Interrupter
# ---------------------------------------------------------------------


def test_aven_interrupter_exiles_a_spell_which_becomes_plotted():
    from mtg_bot.turn import Step

    state = arena(active=1)
    bolt = _bolt(state)
    aven = to_hand(state, printing("Aven Interrupter"))
    _lands(state, "Plains", 3)
    agent(state, 0).targets = [("stack", 0)]
    _cast(state, 0, aven)
    _drain(state)
    assert bolt in state.players[1].exile
    assert bolt.plotted_turn == state.turn_number
    assert state.players[0].life == 20
    # The owner may cast it on a later turn, free, as a sorcery -- with
    # Aven's {2} tax on spells cast from exile.
    state.turn_number += 1
    state.active_player_idx = 1
    state.step = Step.PRECOMBAT_MAIN
    free = CastSpell(bolt.id, cast_for_free=True)
    for o in state.battlefield:
        if o.controller_id == 1:
            o.tapped = True
    assert free not in legal_actions(state, 1)
    _lands(state, "Mountain", 2, 1)
    state.priority_player_idx = 1
    assert free in legal_actions(state, 1)
    agent(state, 1).targets = [("player", 0)]
    apply_action(state, 1, free)
    assert sum(
        o.tapped for o in state.battlefield
        if o.controller_id == 1 and o.printing.name == "Mountain"
    ) == 3
    _drain(state)
    assert state.players[0].life == 17


def test_aven_interrupter_taxes_graveyard_casts_but_not_its_controller():
    from mtg_bot.creature_casting_ub import casting_origin
    from mtg_bot.creature_statics_wg import spell_cost_increase

    state = arena()
    put(state, printing("Aven Interrupter"), 0)
    bolt = printing("Lightning Bolt")
    assert spell_cost_increase(state, bolt, 1) == 0  # from hand
    with casting_origin(True, from_graveyard=True):
        assert spell_cost_increase(state, bolt, 1) == 2
        assert spell_cost_increase(state, bolt, 0) == 0
    with casting_origin(True, from_exile=True):
        assert spell_cost_increase(state, bolt, 1) == 2
    with casting_origin(True):  # top of library
        assert spell_cost_increase(state, bolt, 1) == 0


def test_exile_target_spell_plotted_edges():
    from mtg_bot.effects.generic.roto_stack import ExileTargetSpellPlotted

    eff = ExileTargetSpellPlotted()
    state = arena(active=1)
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("stack", 2),))
    eff.resolve(state, 0, (("player", 0),))
    assert "plotted" in eff.describe()
