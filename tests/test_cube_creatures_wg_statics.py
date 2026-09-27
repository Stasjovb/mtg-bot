"""Cube W/G creatures: Thalia's tax, Questing Beast's combat statics and
planeswalker redirect, Elvish Spirit Guide's hand mana ability,
Worldspine Wurm's put-into-a-graveyard-from-anywhere trigger."""

from __future__ import annotations

from mtg_bot.actions import ActivateAbility, CastSpell, apply_action, apply_cost_reductions
from mtg_bot.cards.parser.creature_wg_lines import (
    parse_wg_creature_line,
)
from mtg_bot.combat import can_block
from mtg_bot.creature_statics_wg import (
    combat_damage_unpreventable,
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


# ---------------------------------------------------------------------
# Worldspine Wurm
# ---------------------------------------------------------------------


def test_worldspine_wurm_discarded_shuffles_into_library():
    pr = cube()["Worldspine Wurm"]
    assert "trample" in pr.keywords
    assert pr.watched_in_graveyard
    assert any(
        isinstance(t.effect, ShuffleSourceIntoOwnersLibrary)
        for t in pr.triggered_abilities
    )
    state = make_state()
    wurm = put(state, 0, pr, Zone.GRAVEYARD)
    state_based_actions(state)
    assert len(state.stack) == 1
    # Same graveyard stay: no second trigger.
    state_based_actions(state)
    assert len(state.stack) == 1
    drain(state)
    assert wurm in state.players[0].library


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
    assert wurm in state.players[0].exile
    state.resolving_source = None
    ShuffleSourceIntoOwnersLibrary().resolve(state, 0)
    assert "shuffle" in ShuffleSourceIntoOwnersLibrary().describe()


# ---------------------------------------------------------------------
# Clarion Conqueror
# ---------------------------------------------------------------------


def test_clarion_conqueror_locks_artifact_creature_planeswalker_abilities():
    from mtg_bot.actions import ActivateAbility, _sac_for_mana_sources
    from mtg_bot.cards import TOKEN_PRINTINGS
    from mtg_bot.creature_statics_wg import activation_locked, filter_activation_locks

    pr = cube()["Clarion Conqueror"]
    assert pr.locks_activated_abilities_of == ("Artifact", "Creature", "Planeswalker")
    assert "flying" in pr.keywords
    state = make_state()
    elves = put(state, 0, "Llanowar Elves")
    ring = put(state, 0, "Sol Ring")
    treasure = put(state, 0, TOKEN_PRINTINGS["Treasure"])
    land = put(state, 0, "Forest")
    before = legal_actions(state, 0)
    assert ActivateAbility(source_id=elves.id, ability_index=0) in before
    assert _sac_for_mana_sources(state, 0)
    conq = put(state, 1, pr)
    after = legal_actions(state, 0)
    for obj in (elves, ring, treasure):
        assert activation_locked(state, obj)
        assert not any(
            isinstance(a, ActivateAbility) and a.source_id == obj.id for a in after
        )
    assert not activation_locked(state, land)
    assert _sac_for_mana_sources(state, 0) == []
    # Unlocked again once it leaves.
    sacrifice(state, conq)
    assert ActivateAbility(source_id=elves.id, ability_index=0) in legal_actions(state, 0)
    assert filter_activation_locks(state, ["x"]) == ["x"]


# ---------------------------------------------------------------------
# Containment Priest
# ---------------------------------------------------------------------


def test_containment_priest_exiles_uncast_creatures_only():
    from mtg_bot.actions import put_into_battlefield
    from mtg_bot.cards.base import make_token_creature

    pr = cube()["Containment Priest"]
    assert pr.exiles_uncast_nontoken_creatures_entering and "flash" in pr.keywords
    state = make_state()
    put(state, 0, pr)
    # Reanimated (not cast): exiled instead.
    dead = put(state, 1, bear("Dead"), Zone.GRAVEYARD)
    state.players[1].graveyard.remove(dead)
    put_into_battlefield(state, dead, 1)
    assert dead in state.players[1].exile and dead not in state.battlefield
    # Cast creatures enter normally.
    elves = put(state, 0, "Llanowar Elves", Zone.HAND)
    add_lands(state, 0, "Forest", 1)
    cast_and_resolve(state, 0, elves)
    assert elves in state.battlefield
    # Tokens and noncreatures are unaffected.
    tok = state.new_object(make_token_creature("Spirit", 1, 1), 0, Zone.BATTLEFIELD)
    put_into_battlefield(state, tok, 0)
    assert tok in state.battlefield
    land = put(state, 0, "Forest", Zone.HAND)
    state.players[0].hand.remove(land)
    put_into_battlefield(state, land, 0)
    assert land in state.battlefield


# ---------------------------------------------------------------------
# Delighted Halfling
# ---------------------------------------------------------------------


def test_delighted_halfling_mana_makes_legendary_spell_uncounterable():
    from mtg_bot.effects.generic.stack_control import CounterTargetSpell

    pr = cube()["Delighted Halfling"]
    mana_abs = [a for a in pr.activated_abilities if a.is_mana_ability]
    assert len(mana_abs) == 2
    restricted = next(a for a in mana_abs if a.effect.spend_restriction)
    assert restricted.effect.makes_spell_uncounterable
    state = make_state()
    halfling = put(state, 0, pr)
    idx = pr.activated_abilities.index(restricted)
    apply_action(state, 0, ActivateAbility(source_id=halfling.id, ability_index=idx))
    (coin,) = state.players[0].mana_pool
    assert coin.makes_spell_uncounterable and coin.spend_restriction == "legendary_spell"
    thalia = put(state, 0, "Thalia, Guardian of Thraben", Zone.HAND)
    add_lands(state, 0, "Plains", 1)
    apply_action(state, 0, CastSpell(thalia.id))
    item = state.stack[-1]
    assert thalia.cast_uncounterable
    assert CounterTargetSpell._is_uncounterable(state, item)
    drain(state)
    # A spell paid without that mana stays counterable.
    elves = put(state, 0, "Llanowar Elves", Zone.HAND)
    add_lands(state, 0, "Forest", 1)
    apply_action(state, 0, CastSpell(elves.id))
    assert not elves.cast_uncounterable
    assert not CounterTargetSpell._is_uncounterable(state, state.stack[-1])


# ---------------------------------------------------------------------
# Anointed Peacekeeper
# ---------------------------------------------------------------------


def test_anointed_peacekeeper_names_a_card_and_taxes_it():
    from mtg_bot.creature_statics_wg import ability_cost_increase

    pr = cube()["Anointed Peacekeeper"]
    assert pr.chooses_card_name_as_enters
    assert (pr.named_spell_cost_increase, pr.named_ability_cost_increase) == (2, 2)
    state = make_state()
    pk = put(state, 0, pr, Zone.HAND)
    add_lands(state, 0, "Plains", 3)
    bolt = put(state, 1, "Lightning Bolt", Zone.HAND)
    put(state, 1, "Brainstorm", Zone.HAND)
    # Names are offered sorted: Brainstorm, Lightning Bolt.
    state.players[0].agent.scripts["mode"] = [1]
    cast_and_resolve(state, 0, pk)
    assert pk.chosen_card_name == "Lightning Bolt"
    assert bolt.publicly_known_to  # the hand was looked at
    # Opponent's Bolt costs {2} more; the controller's own doesn't.
    assert apply_cost_reductions(bolt.printing, state, 1, bolt.printing.mana_cost).total == 3
    assert apply_cost_reductions(bolt.printing, state, 0, bolt.printing.mana_cost).total == 1
    state.active_player_idx = 1
    state.priority_player_idx = 1
    add_lands(state, 1, "Mountain", 2)
    assert CastSpell(bolt.id) not in legal_actions(state, 1)
    add_lands(state, 1, "Mountain", 1)
    assert CastSpell(bolt.id) in legal_actions(state, 1)


def test_peacekeeper_taxes_named_activated_abilities_not_mana_abilities():
    from mtg_bot.creature_statics_wg import ability_cost_increase

    state = make_state()
    pk = put(state, 0, "Anointed Peacekeeper")
    jace = put(state, 1, "Jace, the Mind Sculptor")
    jace.loyalty_counters = 3
    elves = put(state, 1, "Llanowar Elves")
    pk.chosen_card_name = "Jace, the Mind Sculptor"
    jace_ab = jace.printing.activated_abilities[0]
    assert ability_cost_increase(state, jace, jace_ab) == 2
    pk.chosen_card_name = "Llanowar Elves"
    assert ability_cost_increase(state, elves, elves.printing.activated_abilities[0]) == 0
    # A taxed loyalty ability needs {2}: not offered without mana.
    pk.chosen_card_name = "Jace, the Mind Sculptor"
    state.active_player_idx = 1
    state.priority_player_idx = 1
    acts = legal_actions(state, 1)
    assert not any(
        isinstance(a, ActivateAbility) and a.source_id == jace.id for a in acts
    )
    add_lands(state, 1, "Island", 2)
    acts = legal_actions(state, 1)
    act = next(
        a for a in acts if isinstance(a, ActivateAbility) and a.source_id == jace.id
    )
    apply_action(state, 1, act)
    assert all(
        o.tapped for o in state.battlefield
        if o.printing.name == "Island"
    )


def test_peacekeeper_with_empty_opponent_zones_names_nothing():
    from mtg_bot.creature_statics_wg import choose_card_name_as_enters

    state = make_state()
    pk = put(state, 0, "Anointed Peacekeeper")
    choose_card_name_as_enters(state, pk, 0)
    assert pk.chosen_card_name is None
    put(state, 1, "Brainstorm", Zone.GRAVEYARD)
    choose_card_name_as_enters(state, pk, 0)
    assert pk.chosen_card_name == "Brainstorm"


def test_thalia_taxes_free_casts_too():
    state = make_state()
    put(state, 1, "Thalia, Guardian of Thraben")
    fow = put(state, 0, "Force of Will", Zone.HAND)
    put(state, 0, "Brainstorm", Zone.HAND)  # blue card to pitch
    bolt = put(state, 1, "Lightning Bolt", Zone.HAND)
    add_lands(state, 1, "Mountain", 2)
    state.active_player_idx = 1
    state.priority_player_idx = 1
    state.players[1].agent.scripts["target"] = [("player", 0)]
    apply_action(state, 1, CastSpell(bolt.id))
    state.priority_player_idx = 0
    free = CastSpell(fow.id, cast_for_free=True)
    assert free not in legal_actions(state, 0)  # needs {1} for Thalia
    land = add_lands(state, 0, "Island", 1)[0]
    assert free in legal_actions(state, 0)
    apply_action(state, 0, free)
    assert land.tapped
    drain(state)
    # Countered; Force of Will's alternative cost paid 1 life.
    assert bolt in state.players[1].graveyard and state.players[0].life == 19
