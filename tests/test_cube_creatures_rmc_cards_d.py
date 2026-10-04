"""Cube creatures (R / multicolor / colorless) bucket: per-card engine
behavior, batch 6 — "becomes the target" (Leovold, Nadu), real spell
copies gated on "if you cast it" (Lutri), Goblin Welder's swap, "one or
more" discard batches (Inti)."""

from __future__ import annotations

from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    apply_action,
    put_into_battlefield,
)
from mtg_bot.effects.generic.cube_creatures_rmc import (
    DiscardYourHand,
    _discard_chosen,
    fire_becomes_target,
)
from mtg_bot.game import Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step, draw_card
from tests._rmc_helpers import (
    activate,
    add,
    add_lands,
    can_activate,
    cast,
    make_state,
    printing,
    resolve_all,
)


# ---------------------------------------------------------------------------
# Leovold, Emissary of Trest
# ---------------------------------------------------------------------------


def test_leovold_draw_cap_and_targeted_draw():
    pr = printing("Leovold, Emissary of Trest")
    assert pr.opponents_cant_draw_more_than_one_card_each_turn
    state = make_state()
    leovold = add(state, 0, "Leovold, Emissary of Trest")
    for _ in range(4):
        add(state, 1, "Island", Zone.LIBRARY)
        add(state, 0, "Island", Zone.LIBRARY)
    draw_card(state, 1)
    draw_card(state, 1)
    assert len(state.players[1].hand) == 1
    # Opponent targets Leovold: Leovold's controller may draw.
    state.active_player_idx = 1
    state.priority_player_idx = 1
    add(state, 1, "Mountain")
    bolt = add(state, 1, "Lightning Bolt", Zone.HAND)
    state.players[1].agent.scripts["target"] = [("creature", leovold.id)]
    apply_action(state, 1, CastSpell(bolt.id))
    assert state.stack[-1].ability is not None  # the draw trigger
    resolve_all(state)
    assert len(state.players[0].hand) == 1
    # Targeting the opponent's own stuff / its own spells don't trigger.
    before = len(state.players[0].hand)
    fire_becomes_target(state, (("player", 1),), bolt, 1)
    fire_becomes_target(state, (("player", 0),), bolt, 0)
    fire_becomes_target(state, (("stack", 0), ("graveyard_card", 5)), bolt, 1)
    resolve_all(state)
    assert len(state.players[0].hand) == before


# ---------------------------------------------------------------------------
# Nadu, Winged Wisdom
# ---------------------------------------------------------------------------


def test_nadu_grants_a_twice_per_turn_target_trigger():
    state = make_state()
    add(state, 0, "Nadu, Winged Wisdom")
    creature = add(state, 0, "Orcish Lumberjack")
    lands = [add(state, 0, "Forest", Zone.LIBRARY) for _ in range(2)]
    bolt_card = add(state, 0, "Lightning Bolt", Zone.LIBRARY)
    state.players[0].library.remove(bolt_card)
    state.players[0].library.insert(1, bolt_card)
    for _ in range(3):
        fire_becomes_target(state, (("creature", creature.id),), creature, 1)
        resolve_all(state)
    # Two triggers this turn: Forest onto the battlefield, Bolt to hand.
    assert lands[0] in state.battlefield
    assert bolt_card in state.players[0].hand
    assert lands[1] in state.players[0].library
    from mtg_bot.turn import run_cleanup_step

    run_cleanup_step(state)
    fire_becomes_target(state, (("creature", creature.id),), creature, 1)
    resolve_all(state)
    assert lands[1] in state.battlefield


# ---------------------------------------------------------------------------
# Lutri, the Spellchaser
# ---------------------------------------------------------------------------


def test_lutri_copies_a_spell_only_when_cast():
    state = make_state()
    add_lands(state, 0, "Mountain", 1)
    add_lands(state, 0, "Island", 3)
    bolt = add(state, 0, "Lightning Bolt", Zone.HAND)
    lutri = add(state, 0, "Lutri, the Spellchaser", Zone.HAND)
    agent = state.players[0].agent
    agent.scripts["target"] = [("player", 1), ("stack_spell", bolt.id), ("player", 1)]
    apply_action(state, 0, CastSpell(bolt.id))
    apply_action(state, 0, CastSpell(lutri.id))  # flash, in response
    resolve_all(state)
    assert lutri in state.battlefield and lutri.entered_via_cast
    assert state.players[1].life == 14  # copy + original
    # Put onto the battlefield without casting: no trigger.
    state2 = make_state()
    other = state2.new_object(printing("Lutri, the Spellchaser"), 0, Zone.GRAVEYARD)
    put_into_battlefield(state2, other, 0)
    assert not state2.stack


# ---------------------------------------------------------------------------
# Goblin Welder
# ---------------------------------------------------------------------------


def test_goblin_welder_swaps_artifacts():
    state = make_state()
    welder = add(state, 0, "Goblin Welder")
    assert not can_activate(state, 0, welder)  # no artifact + graveyard artifact
    lotus = add(state, 1, "Black Lotus")
    stone = add(state, 1, "The Mind Stone", Zone.GRAVEYARD)
    my_art = add(state, 0, "Walking Ballista", Zone.GRAVEYARD)
    state.players[0].agent.scripts["target"] = [("permanent", lotus.id), ("graveyard_card", stone.id)]
    activate(state, 0, welder)
    assert stone in state.battlefield and stone.controller_id == 1
    assert lotus in state.players[1].graveyard
    assert my_art in state.players[0].graveyard
    # The second slot only offers the chosen artifact's controller's
    # graveyard.
    eff = welder.printing.activated_abilities[0].effect
    pool = eff.legal_targets_for_slot(state, 0, 1, chosen=(("permanent", stone.id),))
    assert ("graveyard_card", lotus.id) in pool and ("graveyard_card", my_art.id) not in pool
    assert eff.legal_targets_for_slot(state, 0, 1) == []
    eff.resolve(state, 0, (("permanent", stone.id),))  # one target: nothing


# ---------------------------------------------------------------------------
# Inti, Seneschal of the Sun
# ---------------------------------------------------------------------------


def test_inti_discard_batch_exiles_once():
    state = make_state()
    inti = add(state, 0, "Inti, Seneschal of the Sun")
    for _ in range(3):
        add(state, 0, "Island", Zone.HAND)
    top = add(state, 0, "Lightning Bolt", Zone.LIBRARY)
    add(state, 0, "Swamp", Zone.LIBRARY)
    DiscardYourHand().resolve(state, 0)
    assert len(state.stack) == 1  # three discards, one trigger
    resolve_all(state)
    assert top in state.players[0].exile
    assert top.exile_play_permission.duration == "until_your_next_end_step"
    # A later, separate discard triggers again.
    add(state, 0, "Island", Zone.HAND)
    _discard_chosen(state, 0, 1)
    assert len(state.stack) == 1
    assert inti in state.battlefield


def test_inti_attack_discard_reflexive_counter():
    state = make_state(step=Step.DECLARE_ATTACKERS)
    inti = add(state, 0, "Inti, Seneschal of the Sun")
    add(state, 0, "Island", Zone.HAND)
    add(state, 0, "Swamp", Zone.LIBRARY)
    state.players[0].agent.scripts["target"] = [("creature", inti.id)]
    from mtg_bot.combat import declare_attackers
    from mtg_bot.game import effective_keywords

    declare_attackers(state, [inti.id])
    resolve_all(state)
    assert inti.plus_one_counters == 1
    assert "trample" in effective_keywords(state, inti)
