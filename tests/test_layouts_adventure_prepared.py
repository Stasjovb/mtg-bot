"""Adventurer cards (CR 715: Brazen Borrower // Petty Theft, Embereth
Shieldbreaker // Battle Display) and the prepare mechanic (Emeritus of
Abundance // Regrowth) -- two different mechanics -- plus the rule that
an unmodeled multi-face card is never claimed as a silent vanilla."""

from __future__ import annotations

from mtg_bot.actions import (
    CastSpell,
    DeclareAttackers,
    StackItem,
    apply_action,
    drain_stack,
    move_spell_off_stack,
)
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.cards.parser.adventure_builder import (
    _build_adventure_printing,
    _build_prepare_printing,
)
from mtg_bot.cards.parser.layout_face_grammar import parse_face_intervening_if
from mtg_bot.cards.parser.source import _build_printing
from mtg_bot.combat import can_block
from mtg_bot.effects.generic.layout_face_effects import (
    SourceBecomesPrepared,
    YouControlAtLeast,
)
from mtg_bot.game import Zone
from mtg_bot.layouts import (
    become_prepared,
    castable_faces,
    is_adventure_cast,
    stop_being_prepared,
)
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step, move_off_battlefield, run_cleanup_step
from tests._spells_b_helpers import ScriptedAgent, add, add_lands, make_state, printing

BORROWER = "Brazen Borrower // Petty Theft"
SHIELD = "Embereth Shieldbreaker // Battle Display"
EMERITUS = "Emeritus of Abundance // Regrowth"


def _creature(state, pid, name="Stalwart Knight"):
    obj = state.new_object(SYNTHETIC_CREATURES[name], pid, Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.battlefield.append(obj)
    return obj


# ---------------------------------------------------------------------------
# Parse shape
# ---------------------------------------------------------------------------


def test_adventure_shapes():
    p = printing(BORROWER)
    assert p.mana_cost_str == "{1}{U}{U}" and p.mana_cost.total == 3
    assert p.keywords == frozenset({"flash", "flying"})
    assert p.can_only_block_creatures_with_flying
    assert p.adventure_face.name == "Petty Theft" and p.adventure_face.is_instant
    assert castable_faces(p) == (p.adventure_face,)
    s = printing(SHIELD)
    assert s.mana_cost_str == "{1}{R}" and s.adventure_face.is_sorcery
    assert s.adventure_face.spell_effect is not None


def test_prepare_shape():
    p = printing(EMERITUS)
    assert p.mana_cost_str == "{2}{G}" and p.is_creature
    assert p.enters_prepared and p.keywords == frozenset({"vigilance"})
    assert p.prepare_spell.name == "Regrowth" and p.adventure_face is None
    assert castable_faces(p) == ()  # only ever cast as the creature
    (trig,) = p.triggered_abilities
    assert trig.effect == SourceBecomesPrepared()


def test_builders_reject_and_no_silent_vanilla():
    creature = {"name": "C", "mana_cost": "{G}", "type_line": "Creature — Elf",
                "power": "1", "toughness": "1", "oracle_text": ""}
    spell = {"name": "S", "mana_cost": "{G}", "type_line": "Sorcery — Adventure",
             "oracle_text": "Draw a card."}
    bad = dict(spell, oracle_text="Frobnicate.")
    card = {"name": "C // S", "layout": "adventure", "card_faces": [creature, spell],
            "type_line": "Creature — Elf // Sorcery — Adventure",
            "mana_cost": "{G} // {G}", "power": "1", "toughness": "1"}
    assert _build_adventure_printing(card).adventure_face.name == "S"
    assert _build_adventure_printing(dict(card, layout="normal")) is None
    assert _build_adventure_printing(dict(card, card_faces=[creature])) is None
    assert _build_adventure_printing(dict(card, card_faces=[spell, creature])) is None
    # An unparsed face: the whole card is unclaimed -- never a vanilla
    # creature built from the face-less top-level record.
    broken = dict(card, card_faces=[creature, bad])
    assert _build_adventure_printing(broken) is None
    assert _build_printing(broken) is None
    # Not an Adventure subtype.
    plain = dict(card, card_faces=[creature, dict(spell, type_line="Sorcery")])
    assert _build_adventure_printing(plain) is None
    prep = dict(card, layout="prepare", card_faces=[creature, dict(spell, type_line="Sorcery")])
    assert _build_prepare_printing(prep).prepare_spell.name == "S"
    assert _build_prepare_printing(card) is None
    # An unknown multi-face layout is never claimed.
    assert _build_printing(dict(card, layout="flip")) is None


# ---------------------------------------------------------------------------
# Adventure
# ---------------------------------------------------------------------------


def test_petty_theft_adventure_then_creature_from_exile():
    agent = ScriptedAgent()
    state = make_state(agent0=agent)
    borrower = add(state, 0, BORROWER, Zone.HAND)
    ogre = _creature(state, 1)
    add_lands(state, 0, "Island", 5)
    state.step = Step.BEGINNING_OF_COMBAT  # instant speed
    casts = [a for a in legal_actions(state, 0) if isinstance(a, CastSpell)]
    assert CastSpell(borrower.id, cast_face="Petty Theft") in casts
    assert CastSpell(borrower.id) in casts  # flash creature
    agent.scripts["target"] = [("creature", ogre.id)]
    apply_action(state, 0, CastSpell(borrower.id, cast_face="Petty Theft"))
    assert is_adventure_cast(state.stack[-1].source)
    drain_stack(state)
    assert ogre in state.players[1].hand
    assert borrower in state.players[0].exile and borrower.printing.name == BORROWER
    perm = borrower.exile_play_permission
    assert perm.primary_only and perm.player_id == 0
    run_cleanup_step(state)
    # Only the creature may be cast from exile (not Petty Theft again).
    casts = [a for a in legal_actions(state, 0) if isinstance(a, CastSpell)
             and a.card_id == borrower.id]
    assert casts == [CastSpell(borrower.id)]
    apply_action(state, 0, CastSpell(borrower.id))
    drain_stack(state)
    assert borrower in state.battlefield and borrower.printing.name == BORROWER


def test_countered_adventure_goes_to_graveyard():
    state = make_state()
    card = add(state, 0, SHIELD, Zone.HAND)
    add(state, 1, "Sol Ring", Zone.BATTLEFIELD)
    add_lands(state, 0, "Mountain", 1)
    apply_action(state, 0, CastSpell(card.id, cast_face="Battle Display"))
    item = state.stack.pop()
    move_spell_off_stack(state, item.source)  # countered
    assert card in state.players[0].graveyard and card.printing.name == SHIELD
    assert card.exile_play_permission is None


def test_battle_display_destroys_artifact_then_knight_later():
    state = make_state()
    card = add(state, 0, SHIELD, Zone.HAND)
    ring = add(state, 1, "Sol Ring", Zone.BATTLEFIELD)
    add_lands(state, 0, "Mountain", 3)
    state.players[0].agent.scripts["target"] = [("permanent", ring.id)]
    apply_action(state, 0, CastSpell(card.id, cast_face="Battle Display"))
    drain_stack(state)
    assert ring in state.players[1].graveyard and card in state.players[0].exile
    apply_action(state, 0, CastSpell(card.id))
    drain_stack(state)
    assert card in state.battlefield


def test_adventure_copy_ceases_to_exist():
    state = make_state()
    card = add(state, 0, SHIELD, Zone.STACK)
    card.is_spell_copy = True
    card.mdfc_front_printing = card.printing
    card.printing = card.printing.adventure_face
    state.stack.append(StackItem(source=card, controller_id=0))
    drain_stack(state)
    assert card not in state.players[0].exile


def test_borrower_blocks_only_fliers():
    state = make_state()
    borrower = add(state, 0, BORROWER, Zone.BATTLEFIELD)
    ground = _creature(state, 1)
    flier = _creature(state, 1, "Sky Sentinel")
    ground.attacking = flier.attacking = True
    assert not can_block(state, borrower, ground)
    assert can_block(state, borrower, flier)


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


def _regrowth_copy(state, pid):
    return next(
        (c for c in state.players[pid].exile if c.printing.name == "Regrowth"), None,
    )


def test_emeritus_enters_prepared_and_casts_regrowth_copy():
    agent = ScriptedAgent()
    state = make_state(agent0=agent)
    emeritus = add(state, 0, EMERITUS, Zone.HAND)
    bolt = add(state, 0, "Lightning Bolt", Zone.GRAVEYARD)
    add_lands(state, 0, "Forest", 5)
    casts = [a for a in legal_actions(state, 0) if isinstance(a, CastSpell)
             and a.card_id == emeritus.id]
    assert casts == [CastSpell(emeritus.id)]  # never cast as Regrowth
    apply_action(state, 0, CastSpell(emeritus.id))
    drain_stack(state)
    copy = _regrowth_copy(state, 0)
    assert copy is not None and emeritus.prepared_copy_id == copy.id
    assert CastSpell(copy.id) in legal_actions(state, 0)
    agent.scripts["target"] = [("graveyard_card", bolt.id)]
    apply_action(state, 0, CastSpell(copy.id))
    assert emeritus.prepared_copy_id == -1  # stops being prepared as cast
    drain_stack(state)
    assert bolt in state.players[0].hand
    assert copy not in state.players[0].exile and copy not in state.players[0].graveyard
    # Can't be prepared twice; re-preparing after casting works.
    assert become_prepared(state, emeritus)
    assert not become_prepared(state, emeritus)


def test_leaving_the_battlefield_removes_the_copy():
    state = make_state()
    emeritus = add(state, 0, EMERITUS, Zone.BATTLEFIELD)
    assert become_prepared(state, emeritus)
    assert _regrowth_copy(state, 0) is not None
    move_off_battlefield(state, emeritus, destination="graveyard")
    assert _regrowth_copy(state, 0) is None and emeritus.prepared_copy_id == -1
    stop_being_prepared(state, emeritus)  # not prepared: nothing happens
    # A creature without a prepare spell can't become prepared.
    ogre = _creature(state, 0)
    assert not become_prepared(state, ogre)


def test_attack_with_eight_lands_prepares_again():
    state = make_state()
    emeritus = add(state, 0, EMERITUS, Zone.BATTLEFIELD)
    add_lands(state, 0, "Forest", 7)
    state.step = Step.DECLARE_ATTACKERS
    apply_action(state, 0, DeclareAttackers(attacker_ids=frozenset({emeritus.id})))
    drain_stack(state)
    assert emeritus.prepared_copy_id == -1  # only seven lands
    emeritus.attacking = False
    emeritus.tapped = False
    add_lands(state, 0, "Forest", 1)
    apply_action(state, 0, DeclareAttackers(attacker_ids=frozenset({emeritus.id})))
    drain_stack(state)
    assert emeritus.prepared_copy_id >= 0


def test_prepare_primitives():
    state = make_state()
    SourceBecomesPrepared().resolve(state, 0)
    assert "prepared" in SourceBecomesPrepared().describe()
    from mtg_bot.effects.predicates import StateBound

    assert parse_face_intervening_if("you control two or more creatures") == (
        StateBound(YouControlAtLeast(n=2, card_type="Creature"))
    )
    assert parse_face_intervening_if("the moon is full") is None
    _creature(state, 0)
    assert not YouControlAtLeast(n=2, card_type="Creature").test(state, 0)
    _creature(state, 0)
    assert YouControlAtLeast(n=2, card_type="Creature").test(state, 0)
