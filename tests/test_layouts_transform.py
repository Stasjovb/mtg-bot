"""Cube layouts bucket: transforming double-faced cards (CR 712 / 701.28)
and modal DFCs with a permanent front face.

Parse shape (front printing keyed by the full card name, back face on
``transform_back_face`` with the front's mana value and its own colors)
and engine behavior (``Transform ~`` activations, "transforms into"
triggers, zone changes restoring the front face, returning transformed).
"""

from __future__ import annotations

import pytest

from mtg_bot.actions import ActivateAbility, CastSpell, PlayLand, apply_action
from mtg_bot.cards.parser.dfc_builder import (
    _build_dfc_printing,
    build_face,
    face_record,
)
from mtg_bot.cards.parser.layout_grammar import (
    parse_layout_effect,
    parse_layout_trigger_phrase,
)
from mtg_bot.effects.generic.layout_effects import (
    ExileSourceThenReturnTransformed,
    TransformSource,
)
from mtg_bot.effects.predicates import Event, IsSelf
from mtg_bot.game import Zone, effective_colors, effective_keywords, effective_power
from mtg_bot.layouts import (
    front_face,
    is_transformed,
    put_onto_battlefield_transformed,
    transform_permanent,
)
from mtg_bot.legal import legal_actions
from mtg_bot.turn import move_off_battlefield
from tests._spells_b_helpers import ScriptedAgent, add, add_lands, make_state, printing

ODDITY = "Ulvenwald Oddity // Ulvenwald Behemoth"
CURTAINS = "Concealing Curtains // Revealing Eye"
WITCH = "Witch Enchanter // Witch-Blessed Meadow"


def _drain(state):
    from mtg_bot.actions import drain_stack

    drain_stack(state)


# ---------------------------------------------------------------------------
# Parse shape
# ---------------------------------------------------------------------------


def test_transform_printing_shape():
    p = printing(ODDITY)
    assert p.name == ODDITY and p.mana_cost_str == "{2}{G}{G}"
    assert p.keywords == frozenset({"trample", "haste"})
    (ab,) = p.activated_abilities
    assert ab.effect == TransformSource() and not ab.sorcery_speed
    back = p.transform_back_face
    assert back.name == "Ulvenwald Behemoth" and (back.power, back.toughness) == (8, 8)
    # CR 712.8e: the back face's mana value is the front face's.
    assert back.mana_cost == p.mana_cost and back.mana_cost_str == ""
    assert back.face_colors == frozenset({"G"})
    assert p.face_colors is None


def test_sorcery_speed_transform_and_transforms_into_trigger_shape():
    p = printing(CURTAINS)
    (ab,) = p.activated_abilities
    assert ab.effect == TransformSource() and ab.sorcery_speed
    (trig,) = p.transform_back_face.triggered_abilities
    assert trig.event == Event.TRANSFORMS and trig.predicate == IsSelf()
    eff = trig.effect
    assert eff.opponent_only and eff.optional and eff.then_draws == 1


def test_modal_dfc_creature_land_shape():
    p = printing(WITCH)
    assert p.is_creature and p.mdfc_back_face.is_land
    assert p.transform_back_face is None


def test_layout_grammar_phrases():
    assert parse_layout_effect("transform this creature") == TransformSource()
    assert parse_layout_effect("transform it") == TransformSource()
    assert parse_layout_effect(
        "exile this creature, then return him to the battlefield "
        "transformed under his owner's control"
    ) == ExileSourceThenReturnTransformed(under_owners_control=True)
    assert parse_layout_effect(
        "exile this saga, then return it to the battlefield transformed "
        "under your control"
    ) == ExileSourceThenReturnTransformed(under_owners_control=False)
    assert parse_layout_effect("frobnicate") is None
    assert parse_layout_trigger_phrase(
        "this creature transforms into this creature"
    ) == (Event.TRANSFORMS, IsSelf())
    assert parse_layout_trigger_phrase("frobnicate") is None


def test_dfc_builder_rejects():
    assert _build_dfc_printing({"layout": "normal"}) is None
    assert _build_dfc_printing({"layout": "transform", "card_faces": []}) is None
    good = {"name": "A", "mana_cost": "{G}", "type_line": "Creature — Beast",
            "oracle_text": "", "power": "1", "toughness": "1", "colors": ["G"]}
    bad = dict(good, name="B", oracle_text="Frobnicate the widget.")
    assert _build_dfc_printing(
        {"name": "A // B", "layout": "transform", "card_faces": [bad, good]}
    ) is None
    assert _build_dfc_printing(
        {"name": "A // B", "layout": "transform", "card_faces": [good, bad]}
    ) is None
    # Modal DFC: an unbuildable back face (land or not) rejects.
    bad_land = {"name": "L", "type_line": "Land", "oracle_text": "{T}: Add {G}."}
    assert _build_dfc_printing(
        {"name": "A // L", "layout": "modal_dfc", "card_faces": [good, bad_land]}
    ) is None
    assert _build_dfc_printing(
        {"name": "A // B", "layout": "modal_dfc", "card_faces": [good, bad]}
    ) is None
    # Modal DFC with a spell front face: left to the spell builder.
    spell = {"name": "S", "mana_cost": "{G}", "type_line": "Sorcery",
             "oracle_text": "Draw a card."}
    assert _build_dfc_printing(
        {"name": "S // A", "layout": "modal_dfc", "card_faces": [spell, good]}
    ) is None
    # A plain modal DFC with a castable (non-transforming) back face.
    two = _build_dfc_printing(
        {"name": "A // B", "layout": "modal_dfc",
         "card_faces": [good, dict(good, name="B")]}
    )
    assert two.mdfc_back_face.name == "B" and two.transform_back_face is None
    assert face_record({"name": "X", "type_line": "Land"})["oracle_text"] == ""
    assert build_face(bad) is None


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def test_activated_transform_and_back_face_statics():
    state = make_state()
    oddity = add(state, 0, ODDITY, Zone.BATTLEFIELD)
    add_lands(state, 0, "Forest", 7)
    acts = legal_actions(state, 0)
    assert ActivateAbility(source_id=oddity.id, ability_index=0) in acts
    apply_action(state, 0, ActivateAbility(source_id=oddity.id, ability_index=0))
    _drain(state)
    assert is_transformed(oddity)
    assert oddity.printing.name == "Ulvenwald Behemoth"
    assert front_face(oddity).name == ODDITY
    assert effective_power(state, oddity) == 8
    assert effective_colors(state, oddity) == frozenset({"G"})
    assert "transforms into Ulvenwald Behemoth" in "\n".join(state.log)
    # Leaving the battlefield turns it front face up again.
    move_off_battlefield(state, oddity, destination="hand")
    assert oddity.printing.name == ODDITY and not is_transformed(oddity)


def test_back_face_anthem_applies_to_other_creatures():
    from mtg_bot.cards import SYNTHETIC_CREATURES

    state = make_state()
    oddity = add(state, 0, ODDITY, Zone.BATTLEFIELD)
    ogre = state.new_object(SYNTHETIC_CREATURES["Stone Ogre"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(ogre)
    base = effective_power(state, ogre)
    transform_permanent(state, oddity)
    assert effective_power(state, ogre) == base + 1
    assert {"trample", "haste"} <= effective_keywords(state, ogre)
    # Transforming again turns it back (the object is unchanged).
    oddity.damage = 1
    transform_permanent(state, oddity)
    assert oddity.printing.name == ODDITY and oddity.damage == 1
    assert effective_power(state, ogre) == base


def test_transforms_into_trigger_reveals_and_discards():
    agent = ScriptedAgent()
    state = make_state(agent0=agent)
    curtains = add(state, 0, CURTAINS, Zone.BATTLEFIELD)
    bolt = add(state, 1, "Lightning Bolt", Zone.HAND)
    add(state, 1, "Mountain", Zone.HAND)
    add(state, 1, "Island", Zone.LIBRARY)
    add_lands(state, 0, "Swamp", 3)
    apply_action(state, 0, ActivateAbility(source_id=curtains.id, ability_index=0))
    _drain(state)
    assert curtains.printing.name == "Revealing Eye"
    assert bolt in state.players[1].graveyard
    assert [c.printing.name for c in state.players[1].hand] == ["Mountain", "Island"]


def test_transforms_into_trigger_optional_decline():
    agent = ScriptedAgent(yes_no=[False])
    state = make_state(agent0=agent)
    curtains = add(state, 0, CURTAINS, Zone.BATTLEFIELD)
    bolt = add(state, 1, "Lightning Bolt", Zone.HAND)
    transform_permanent(state, curtains)
    _drain(state)
    assert bolt in state.players[1].hand


def test_sorcery_speed_transform_not_offered_at_instant_speed():
    from mtg_bot.turn import Step

    state = make_state(step=Step.BEGINNING_OF_COMBAT)
    curtains = add(state, 0, CURTAINS, Zone.BATTLEFIELD)
    add_lands(state, 0, "Swamp", 3)
    acts = legal_actions(state, 0)
    assert ActivateAbility(source_id=curtains.id, ability_index=0) not in acts


def test_transform_non_dfc_and_off_battlefield_is_noop():
    state = make_state()
    bear = add(state, 0, "Lightning Bolt", Zone.HAND)
    assert not transform_permanent(state, bear)
    ogre = add(state, 0, "Swamp", Zone.BATTLEFIELD)
    assert not transform_permanent(state, ogre)
    assert "can't transform" in state.log[-1]
    # A modal DFC played as its land face isn't a transforming face.
    witch = add(state, 0, WITCH, Zone.HAND)
    apply_action(state, 0, PlayLand(witch.id))
    assert witch.printing.name == "Witch-Blessed Meadow"
    assert not transform_permanent(state, witch)
    assert not is_transformed(witch)


def test_transform_source_effect_without_source_is_noop():
    state = make_state()
    assert TransformSource().resolve(state, 0) is False
    assert "transform" in TransformSource().describe()
    assert ExileSourceThenReturnTransformed().resolve(state, 0) is False
    assert "owner's" in ExileSourceThenReturnTransformed().describe()
    assert "your control" in ExileSourceThenReturnTransformed(False).describe()


def test_exile_and_return_transformed():
    state = make_state()
    oddity = add(state, 1, ODDITY, Zone.BATTLEFIELD)
    oddity.plus_one_counters = 2
    state.resolving_source = oddity
    # Controlled by P0 (stolen): returns under its owner's control.
    oddity.controller_id = 0
    assert ExileSourceThenReturnTransformed().resolve(state, 0)
    state.resolving_source = None
    assert oddity in state.battlefield and oddity.controller_id == 1
    assert is_transformed(oddity) and oddity.plus_one_counters == 0
    # Under "your control".
    state.resolving_source = oddity
    move_off_battlefield(state, oddity, destination="hand")
    state.players[1].hand.remove(oddity)
    oddity.zone = Zone.BATTLEFIELD
    state.battlefield.append(oddity)
    assert ExileSourceThenReturnTransformed(under_owners_control=False).resolve(state, 0)
    assert oddity.controller_id == 0


def test_exile_and_return_transformed_non_dfc_stays_exiled():
    state = make_state()
    swamp = add(state, 0, "Swamp", Zone.BATTLEFIELD)
    state.resolving_source = swamp
    assert not ExileSourceThenReturnTransformed().resolve(state, 0)
    assert swamp in state.players[0].exile
    card = add(state, 0, "Swamp", Zone.GRAVEYARD)
    assert not put_onto_battlefield_transformed(state, card, 0)


def test_modal_dfc_creature_front_cast_or_play_land():
    state = make_state()
    witch = add(state, 0, WITCH, Zone.HAND)
    add_lands(state, 0, "Plains", 4)
    acts = legal_actions(state, 0)
    assert PlayLand(witch.id) in acts and CastSpell(witch.id) in acts
    apply_action(state, 0, CastSpell(witch.id))
    _drain(state)
    assert witch in state.battlefield and witch.printing.name == WITCH
