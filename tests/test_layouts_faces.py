"""Cube layouts bucket: casting a card as another face -- split cards
(Life // Death, CR 709) and modal DFCs with a castable back face that
can also transform (Jennifer Walters // The Sensational She-Hulk)."""

from __future__ import annotations

from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    apply_action,
    drain_stack,
    move_spell_off_stack,
)
from mtg_bot.cards.parser.split_builder import _build_split_printing
from mtg_bot.effects.generic.layout_effects import (
    TransformSource,
    YourPermanentsBecomeCreaturesUEOT,
)
from mtg_bot.effects.generic.reanimation import ReturnCardFromGraveyardToBattlefield
from mtg_bot.effects.predicates import Event
from mtg_bot.game import Zone, effective_power, is_creature_now
from mtg_bot.layouts import castable_faces, face_named, find_face_card, transform_permanent
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step, move_off_battlefield, run_cleanup_step
from tests._spells_b_helpers import ScriptedAgent, add, add_lands, make_state, printing

LIFE_DEATH = "Life // Death"
JEN = "Jennifer Walters // The Sensational She-Hulk"


def _casts(state, pid, card):
    return [a for a in legal_actions(state, pid) if isinstance(a, CastSpell) and a.card_id == card.id]


# ---------------------------------------------------------------------------
# Split cards
# ---------------------------------------------------------------------------


def test_split_printing_shape():
    p = printing(LIFE_DEATH)
    assert p.mana_cost.total == 3 and p.spell_effect is None and p.is_sorcery
    life, death = p.split_faces
    assert life.name == "Life" and life.mana_cost_str == "{G}"
    assert life.spell_effect == YourPermanentsBecomeCreaturesUEOT(
        card_type="Land", power=1, toughness=1,
    )
    assert death.name == "Death" and death.mana_cost.total == 2
    assert isinstance(death.spell_effect, ReturnCardFromGraveyardToBattlefield)
    assert death.spell_effect.lose_life_equal_mv
    assert death.spell_effect.source == "target_your_graveyard"
    assert castable_faces(p) == (life, death)
    assert face_named(p, "Death") is death and face_named(p, "Nope") is None


def test_split_builder_rejects():
    inst = {"name": "A", "mana_cost": "{R}", "type_line": "Instant",
            "oracle_text": "Draw a card."}
    room = {"name": "R", "mana_cost": "{R}", "type_line": "Enchantment — Room",
            "oracle_text": "Draw a card."}
    bad = dict(inst, name="B", oracle_text="Frobnicate.")
    assert _build_split_printing({"layout": "normal"}) is None
    assert _build_split_printing({"layout": "split", "card_faces": [inst]}) is None
    assert _build_split_printing(
        {"name": "A // R", "layout": "split", "card_faces": [inst, room]}
    ) is None
    assert _build_split_printing(
        {"name": "A // B", "layout": "split", "card_faces": [inst, bad]}
    ) is None


def test_split_card_is_cast_as_a_half_only():
    state = make_state()
    card = add(state, 0, LIFE_DEATH, Zone.HAND)
    add_lands(state, 0, "Forest", 1)
    add_lands(state, 0, "Swamp", 2)
    # Death needs a creature card in the graveyard to target.
    casts = _casts(state, 0, card)
    assert casts == [CastSpell(card.id, cast_face="Life")]
    add(state, 0, "Lightning Bolt", Zone.GRAVEYARD)
    assert CastSpell(card.id, cast_face="Death") not in _casts(state, 0, card)


def test_cast_life_animates_lands_until_end_of_turn():
    state = make_state()
    card = add(state, 0, LIFE_DEATH, Zone.HAND)
    forests = add_lands(state, 0, "Forest", 2)
    opp_land = add(state, 1, "Swamp", Zone.BATTLEFIELD)
    apply_action(state, 0, CastSpell(card.id, cast_face="Life"))
    assert state.stack[-1].source.printing.name == "Life"
    drain_stack(state)
    assert card in state.players[0].graveyard and card.printing.name == LIFE_DEATH
    for f in forests:
        assert is_creature_now(f) and f.printing.is_land
        assert effective_power(state, f) == 1
    assert not is_creature_now(opp_land)
    run_cleanup_step(state)
    assert not any(is_creature_now(f) for f in forests)


def test_cast_death_reanimates_and_loses_life():
    state = make_state()
    card = add(state, 0, LIFE_DEATH, Zone.HAND)
    add_lands(state, 0, "Swamp", 2)
    ogre = add(state, 0, JEN, Zone.GRAVEYARD)
    casts = _casts(state, 0, card)
    assert CastSpell(card.id, cast_face="Death") in casts
    state.players[0].agent.scripts["target"] = [("graveyard_card", ogre.id)]
    apply_action(state, 0, CastSpell(card.id, cast_face="Death"))
    drain_stack(state)
    assert ogre in state.battlefield
    assert state.players[0].life == 18
    assert card.printing.name == LIFE_DEATH and card in state.players[0].graveyard


def test_countered_or_bounced_half_turns_back():
    state = make_state()
    card = add(state, 0, LIFE_DEATH, Zone.HAND)
    add_lands(state, 0, "Forest", 1)
    apply_action(state, 0, CastSpell(card.id, cast_face="Life"))
    item = state.stack.pop()
    move_spell_off_stack(state, item.source, destination="hand")
    assert card.printing.name == LIFE_DEATH and card in state.players[0].hand


def test_two_copies_offer_one_cast_per_face():
    state = make_state()
    a = add(state, 0, LIFE_DEATH, Zone.HAND)
    b = add(state, 0, LIFE_DEATH, Zone.HAND)
    add_lands(state, 0, "Forest", 1)
    casts = [x for x in legal_actions(state, 0) if isinstance(x, CastSpell)]
    assert len([c for c in casts if c.cast_face == "Life"]) == 1
    assert find_face_card(state, 0, b.id) is b
    assert find_face_card(state, 0, 999) is None
    assert a.printing.name == LIFE_DEATH


def test_face_casts_from_other_zones_are_found():
    state = make_state()
    card = add(state, 0, LIFE_DEATH, Zone.LIBRARY)
    exiled = add(state, 1, LIFE_DEATH, Zone.EXILE)
    assert find_face_card(state, 0, card.id) is card
    assert find_face_card(state, 0, exiled.id) is exiled
    # Neither is castable (no permission): no face casts offered.
    add_lands(state, 0, "Forest", 1)
    assert not [
        a for a in legal_actions(state, 0)
        if isinstance(a, CastSpell) and a.cast_face is not None
    ]


def test_no_priority_short_circuits():
    state = make_state()
    add(state, 0, LIFE_DEATH, Zone.HAND)
    state.priority_player_idx = 1
    assert len(legal_actions(state, 0)) == 1


# ---------------------------------------------------------------------------
# Modal DFC with a castable, transformable back face
# ---------------------------------------------------------------------------


def test_jennifer_shape():
    p = printing(JEN)
    back = p.mdfc_back_face
    assert back is p.transform_back_face
    assert back.name == "The Sensational She-Hulk" and back.mana_cost.total == 6
    (ab,) = p.activated_abilities
    assert ab.effect == TransformSource() and ab.sorcery_speed
    assert p.opponents_cant_cast_spells_during_your_turn
    (trig,) = back.triggered_abilities
    assert trig.event == Event.DEALT_DAMAGE and trig.once_per_turn


def test_cast_back_face_directly():
    state = make_state()
    card = add(state, 0, JEN, Zone.HAND)
    add_lands(state, 0, "Forest", 1)
    add_lands(state, 0, "Plains", 5)
    casts = _casts(state, 0, card)
    assert CastSpell(card.id) in casts
    assert CastSpell(card.id, cast_face="The Sensational She-Hulk") in casts
    apply_action(state, 0, CastSpell(card.id, cast_face="The Sensational She-Hulk"))
    drain_stack(state)
    assert card in state.battlefield and card.printing.name == "The Sensational She-Hulk"
    assert effective_power(state, card) == 6
    # Transforming an MDFC cast as its back face turns it to the front.
    assert transform_permanent(state, card)
    assert card.printing.name == JEN
    move_off_battlefield(state, card, destination="graveyard")
    assert card.printing.name == JEN


def test_jennifer_transform_ability():
    state = make_state()
    card = add(state, 0, JEN, Zone.BATTLEFIELD)
    add_lands(state, 0, "Forest", 1)
    add_lands(state, 0, "Plains", 5)
    apply_action(state, 0, ActivateAbility(source_id=card.id, ability_index=0))
    drain_stack(state)
    assert card.printing.name == "The Sensational She-Hulk"


def test_she_hulk_redirects_damage_once_per_turn():
    from mtg_bot.effects.base import _apply_damage

    agent = ScriptedAgent()
    state = make_state(agent0=agent)
    hulk = add(state, 0, JEN, Zone.BATTLEFIELD)
    transform_permanent(state, hulk)
    agent.scripts["target"] = [("player", 1), ("player", 1)]
    _apply_damage(state, ("creature", hulk.id), 3)
    drain_stack(state)
    assert state.players[1].life == 17
    _apply_damage(state, ("creature", hulk.id), 2)
    drain_stack(state)
    assert state.players[1].life == 17


def test_opponents_cant_cast_during_your_turn():
    state = make_state()
    add(state, 0, JEN, Zone.BATTLEFIELD)
    bolt = add(state, 1, "Lightning Bolt", Zone.HAND)
    add_lands(state, 1, "Mountain", 1)
    state.priority_player_idx = 1
    assert not _casts(state, 1, bolt)
