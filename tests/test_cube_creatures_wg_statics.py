"""Cube W/G creatures: Thalia's tax, Questing Beast's combat statics and
planeswalker redirect, Elvish Spirit Guide's hand mana ability,
Worldspine Wurm's put-into-a-graveyard-from-anywhere trigger."""

from __future__ import annotations

from mtg_bot.actions import ActivateAbility, CastSpell, apply_action, apply_cost_reductions
from mtg_bot.cards.parser.creature_wg_lines import (
    parse_wg_creature_line,
    parse_wg_hand_ability_line,
)
from mtg_bot.combat import can_block
from mtg_bot.creature_statics_wg import (
    combat_damage_unpreventable,
    fire_graveyard_arrival_triggers,
    spell_cost_increase,
)
from mtg_bot.effects.generic.cube_creatures_wg import (
    DealCombatDamageAmountToTarget,
    ShuffleSourceIntoOwnersLibrary,
)
from mtg_bot.game import Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import sacrifice, state_based_actions
from tests._wg_helpers import (
    add_lands,
    attack,
    bear,
    cast_and_resolve,
    cube,
    drain,
    make_state,
    put,
)


# ---------------------------------------------------------------------
# Thalia
# ---------------------------------------------------------------------


def test_thalia_taxes_every_players_noncreature_spells():
    pr = cube()["Thalia, Guardian of Thraben"]
    assert "first strike" in pr.keywords
    state = make_state()
    put(state, 1, pr)
    bolt = cube()["Lightning Bolt"]
    elves = cube()["Llanowar Elves"]
    assert spell_cost_increase(state, bolt) == 1
    assert spell_cost_increase(state, elves) == 0
    assert apply_cost_reductions(bolt, state, 0, bolt.mana_cost).generic == 1
    card = put(state, 0, bolt, Zone.HAND)
    add_lands(state, 0, "Mountain", 1)
    assert CastSpell(card.id) not in legal_actions(state, 0)
    add_lands(state, 0, "Mountain", 1)
    assert CastSpell(card.id) in legal_actions(state, 0)
    state.players[0].agent.scripts["target"] = [("player", 1)]
    cast_and_resolve(state, 0, card)
    assert state.players[1].life == 17
    assert all(o.tapped for o in state.battlefield if o.printing.name == "Mountain")


def test_spells_cost_more_line_grammar():
    card = {"name": "X"}
    wg = parse_wg_creature_line("Artifact spells cost {2} more to cast.", card)
    (f, n), = wg.fields["spell_cost_increases"]
    assert n == 2 and f.any_types == ("Artifact",)
    assert parse_wg_creature_line("Wombat spells cost {1} more to cast.", card) is None


# ---------------------------------------------------------------------
# Questing Beast
# ---------------------------------------------------------------------


def test_questing_beast_block_restriction_and_keywords():
    pr = cube()["Questing Beast"]
    assert {"vigilance", "deathtouch", "haste"} <= pr.keywords
    state = make_state()
    qb = put(state, 0, pr)
    small = put(state, 1, bear("Small"))
    big = put(state, 1, bear("Big", "{2}{G}", 3, 3))
    assert not can_block(state, small, qb)
    assert can_block(state, big, qb)
    other = put(state, 0, bear("Other"))
    assert can_block(state, small, other)


def test_questing_beast_makes_your_creatures_damage_unpreventable():
    state = make_state()
    other = put(state, 0, bear("Other"))
    assert not combat_damage_unpreventable(state, other)
    put(state, 0, "Questing Beast")
    assert combat_damage_unpreventable(state, other)
    theirs = put(state, 1, bear("Theirs"))
    assert not combat_damage_unpreventable(state, theirs)
    state.prevent_combat_damage_this_turn = True
    attack(state, 0, [other.id])
    from mtg_bot.combat import resolve_combat_damage

    resolve_combat_damage(state, defending_player_id=1)
    assert state.players[1].life == 18


def test_questing_beast_redirects_combat_damage_to_a_planeswalker():
    state = make_state()
    qb = put(state, 0, "Questing Beast")
    jace = put(state, 1, "Jace, the Mind Sculptor")
    jace.loyalty_counters = 5
    attack(state, 0, [qb.id])
    from mtg_bot.combat import resolve_combat_damage

    resolve_combat_damage(state, defending_player_id=1)
    drain(state)
    assert state.players[1].life == 16
    assert jace.loyalty_counters == 1


def test_that_much_damage_edges():
    state = make_state()
    eff = DealCombatDamageAmountToTarget()
    state.resolving_combat_damage_amount = 0
    eff.resolve(state, 0, ())
    assert "that much" in eff.describe()
    assert eff.targets_from_event(state, {}) is None


# ---------------------------------------------------------------------
# Elvish Spirit Guide
# ---------------------------------------------------------------------


def test_elvish_spirit_guide_exiles_from_hand_for_green():
    pr = cube()["Elvish Spirit Guide"]
    (ab,) = pr.hand_activated_abilities
    assert ab.cost.exile_self and ab.is_mana_ability
    state = make_state()
    esg = put(state, 0, pr, Zone.HAND)
    act = ActivateAbility(source_id=esg.id, ability_index=0)
    assert act in legal_actions(state, 0)
    apply_action(state, 0, act)
    assert esg in state.players[0].exile
    assert [c.color for c in state.players[0].mana_pool] == ["G"]
    assert parse_wg_hand_ability_line("Exile this card from your hand: dance.") is None
    assert parse_wg_hand_ability_line("Draw a card.") is None


# ---------------------------------------------------------------------
# Worldspine Wurm
# ---------------------------------------------------------------------


def test_worldspine_wurm_discarded_shuffles_into_library():
    pr = cube()["Worldspine Wurm"]
    assert "trample" in pr.keywords
    (gy_trig,) = pr.graveyard_arrival_triggers
    assert isinstance(gy_trig.effect, ShuffleSourceIntoOwnersLibrary)
    state = make_state()
    wurm = put(state, 0, pr, Zone.GRAVEYARD)
    state_based_actions(state)
    assert wurm.graveyard_arrival_pending and len(state.stack) == 1
    # Already pending: no second trigger.
    assert not fire_graveyard_arrival_triggers(state)
    drain(state)
    assert wurm in state.players[0].library and not wurm.graveyard_arrival_pending


def test_worldspine_wurm_dies_into_three_wurms_and_shuffles():
    state = make_state()
    wurm = put(state, 0, "Worldspine Wurm")
    sacrifice(state, wurm)
    state_based_actions(state)
    drain(state)
    tokens = [o for o in state.battlefield if o.printing.is_token]
    assert len(tokens) == 3
    assert all("trample" in t.printing.keywords for t in tokens)
    assert wurm in state.players[0].library


def test_worldspine_trigger_after_leaving_graveyard_does_nothing():
    state = make_state()
    wurm = put(state, 0, "Worldspine Wurm", Zone.GRAVEYARD)
    state_based_actions(state)
    state.players[0].graveyard.remove(wurm)
    wurm.zone = Zone.EXILE
    state.players[0].exile.append(wurm)
    drain(state)
    assert wurm in state.players[0].exile and not wurm.graveyard_arrival_pending
    state.resolving_source = None
    ShuffleSourceIntoOwnersLibrary().resolve(state, 0)
    assert "shuffle" in ShuffleSourceIntoOwnersLibrary().describe()


def test_graveyard_arrival_line_needs_a_rearming_effect():
    card = {"name": "Big Wurm"}
    assert parse_wg_creature_line(
        "When Big Wurm is put into a graveyard from anywhere, draw a card.",
        card,
    ) is None
    assert parse_wg_creature_line(
        "When Big Wurm is put into a graveyard from anywhere, shuffle it "
        "into its owner's library.", card,
    ).fields["graveyard_arrival_triggers"]
