"""Cube spells-B: modal double-faced spell // land cards (Sink into
Stupor // Soporific Springs, Shatterskull Smashing // Shatterskull, the
Hammer Pass) — cast the front, or play the back face as a land."""

from __future__ import annotations

import pytest

from mtg_bot.actions import CastSpell, PlayLand, apply_action, resolve_top_of_stack
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.cards.parser.spell_builder import (
    _build_mdfc_land_face,
    _build_mdfc_spell_printing,
)
from mtg_bot.effects.formulas import ResolvingX
from mtg_bot.effects.generic.card_flow import ReturnTargetSpellOrNonlandPermanentToHand
from mtg_bot.effects.generic.divided_damage import DealDamageDividedAmongTargets
from mtg_bot.game import StackItem, Zone, restore_mdfc_front
from mtg_bot.legal import legal_actions
from mtg_bot.turn import move_off_battlefield, state_based_actions
from tests._spells_b_helpers import ScriptedAgent, add, add_lands, make_state

SINK = "Sink into Stupor // Soporific Springs"
SMASH = "Shatterskull Smashing // Shatterskull, the Hammer Pass"


@pytest.fixture(scope="module")
def cube():
    return OracleParserCardSource(pool="cube").get_printings()


def _creature(state, pid, name):
    obj = state.new_object(SYNTHETIC_CREATURES[name], pid, Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.battlefield.append(obj)
    return obj


def test_mdfc_printings(cube):
    sink = cube[SINK]
    assert sink.is_instant and sink.mana_cost_str == "{1}{U}{U}"
    assert sink.spell_effect == ReturnTargetSpellOrNonlandPermanentToHand(opponent_only=True)
    back = sink.mdfc_back_face
    assert back.name == "Soporific Springs" and back.is_land
    assert back.produces == frozenset({"U"}) and back.shock_land_life_cost == 3
    smash = cube[SMASH]
    assert smash.spell_effect == DealDamageDividedAmongTargets(
        amount=ResolvingX(), max_targets=2, include_planeswalkers=True,
        double_if_x_at_least=6,
    )
    assert smash.mdfc_back_face.produces == frozenset({"R"})


def test_mdfc_builder_rejects_other_shapes():
    assert _build_mdfc_spell_printing({"name": "X", "card_faces": []}) is None
    assert _build_mdfc_land_face({"name": "L", "type_line": "Creature", "oracle_text": ""}) is None
    assert _build_mdfc_land_face({
        "name": "L", "type_line": "Land", "oracle_text": "{T}: Add {U}.",
    }) is None
    assert _build_mdfc_land_face({
        "name": "L", "type_line": "Land",
        "oracle_text": "This land enters tapped.\n{T}: Add {U}.",
    }) is None
    spell_face = {"name": "S", "mana_cost": "{U}", "type_line": "Instant",
                  "oracle_text": "Frobnicate."}
    land_face = {"name": "L", "type_line": "Land",
                 "oracle_text": "As this land enters, you may pay 3 life. If you don't, it enters tapped.\n{T}: Add {U}."}
    assert _build_mdfc_spell_printing({"name": "S // L", "card_faces": [spell_face, land_face]}) is None
    ok_face = dict(spell_face, oracle_text="Draw a card.")
    bad_land = dict(land_face, oracle_text="{T}: Add {U}.")
    assert _build_mdfc_spell_printing({"name": "S // L", "card_faces": [ok_face, bad_land]}) is None
    assert _build_mdfc_spell_printing(
        {"name": "S // L", "card_faces": [ok_face, land_face]}
    ).mdfc_back_face.name == "L"


def test_play_mdfc_as_land_pay_life_then_restore_front():
    state = make_state()
    card = add(state, 0, SINK, Zone.HAND)
    assert PlayLand(card.id) in legal_actions(state, 0)
    state.players[0].agent.scripts["yes_no"] = []
    apply_action(state, 0, PlayLand(card.id))
    assert card in state.battlefield
    assert card.printing.name == "Soporific Springs"
    assert card.mdfc_front_printing is not None
    move_off_battlefield(state, card, destination="hand")
    assert card.printing.name == SINK and card.mdfc_front_printing is None
    restore_mdfc_front(card)  # no-op when already front


def test_play_mdfc_land_shock_choice_decline_enters_tapped():
    class _NoPay(ScriptedAgent):
        def choose_pay_shock_life(self, state, player_id, life_cost):
            return False

    state = make_state(agent0=_NoPay())
    card = add(state, 0, SMASH, Zone.HAND)
    apply_action(state, 0, PlayLand(card.id))
    assert card.tapped and state.players[0].life == 20


def test_sink_into_stupor_bounces_spell_or_permanent():
    state = make_state()
    ogre = _creature(state, 1, "Stone Ogre")
    mine = _creature(state, 0, "Wild Bear")
    land = add(state, 1, "Swamp", Zone.BATTLEFIELD)
    spell = add(state, 1, "Dark Ritual", Zone.STACK)
    state.stack.append(StackItem(source=spell, controller_id=1))
    own_spell = add(state, 0, "Dark Ritual", Zone.STACK)
    state.stack.append(StackItem(source=own_spell, controller_id=0))
    eff = ReturnTargetSpellOrNonlandPermanentToHand(opponent_only=True)
    legal = eff.legal_targets(state, 0)
    assert ("stack", 0) in legal and ("stack", 1) not in legal
    assert ("creature", ogre.id) in legal
    assert all(t[1] not in (mine.id, land.id) for t in legal if t[0] != "stack")
    eff.resolve(state, 0, (("stack", 0),))
    assert spell in state.players[1].hand and len(state.stack) == 1
    eff.resolve(state, 0, (("creature", ogre.id),))
    assert ogre in state.players[1].hand
    # Illegal / stale targets are no-ops.
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("stack", 9),))
    eff.resolve(state, 0, (("creature", mine.id),))
    eff.resolve(state, 0, (("permanent", land.id),))
    state.stack[0].countered = True
    eff.resolve(state, 0, (("stack", 0),))
    assert mine in state.battlefield and land in state.battlefield
    assert "an opponent controls" in eff.describe()
    assert "an opponent" not in ReturnTargetSpellOrNonlandPermanentToHand(False).describe()


def test_shatterskull_smashing_cast_with_x():
    agent = ScriptedAgent(x=[3, 2])
    state = make_state(agent0=agent)
    ogre = _creature(state, 1, "Stone Ogre")
    gob = _creature(state, 1, "Raging Goblin")
    card = add(state, 0, SMASH, Zone.HAND)
    add_lands(state, 0, "Mountain", 5)
    agent.scripts["target"] = [("creature", ogre.id), ("creature", gob.id)]
    apply_action(state, 0, CastSpell(card.id))
    assert state.stack[-1].division == (2, 1)
    resolve_top_of_stack(state)
    state_based_actions(state)
    assert gob in state.players[1].graveyard and ogre.damage == 2


def test_bounce_helpers_restore_front_face():
    from mtg_bot.effects.generic.bounce import ReturnUpToNTargetCreaturesToOwnersHands
    from mtg_bot.effects.generic.targets_helpers import _bounce_to_hand

    state = make_state()
    card = add(state, 0, SINK, Zone.HAND)
    apply_action(state, 0, PlayLand(card.id))
    _bounce_to_hand(state, card)
    assert card.printing.name == SINK
    # The multi-bounce path restores too (land animated into a creature
    # isn't needed: call the helper path directly on the object).
    card2 = add(state, 0, SMASH, Zone.HAND)
    state.players[0].lands_played_this_turn = 0
    apply_action(state, 0, PlayLand(card2.id))
    card2.permanent_is_creature = True
    ReturnUpToNTargetCreaturesToOwnersHands(max_n=1).resolve(
        state, 0, (("creature", card2.id),),
    )
    assert card2.printing.name == SMASH
