"""Cube creatures (R / multicolor / colorless) bucket: composable cost
atoms, hand / graveyard-functioning abilities, Exhaust, exile play
permissions, "Spells you control can't be countered", granted
Ward—Pay N life, "search ... onto the battlefield tapped"."""

from __future__ import annotations

import pytest

from mtg_bot.actions import ActivateAbility, CastSpell, apply_action
from mtg_bot.cards.parser.activated import _parse_activation_cost
from mtg_bot.cards.parser.creature_rmc_grammar import (
    is_eoe_only_printing,
    parse_rmc_cost_piece,
    parse_rmc_creature_line_post,
    parse_rmc_creature_line_pre,
    parse_rmc_effect,
    rmc_grammar_disabled,
)
from mtg_bot.effects.generic.cube_creatures_rmc import (
    ExilePlayPermission,
    ExileSelfFromGraveyardCost,
    RemoveCountersFromSelfCost,
    SacrificePermanentsCost,
    TapUntappedPermanentsCost,
    UNTIL_END_OF_YOUR_NEXT_TURN,
    UNTIL_YOUR_NEXT_END_STEP,
    effective_ward_life_cost,
    exile_card,
    grant_exile_play,
)
from mtg_bot.effects.generic.mana import AddNManaOfChosenColor
from mtg_bot.effects.object_predicates import HasSubtype, IsArtifact
from mtg_bot.game import ManaCoin, Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step, run_cleanup_step
from tests._rmc_helpers import (
    ScriptedAgent,
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
# Grammar
# ---------------------------------------------------------------------------


def test_cost_atom_grammar():
    sac = parse_rmc_cost_piece("Sacrifice five Treasures")
    assert sac == SacrificePermanentsCost(
        permanent_filter=HasSubtype("Treasure"), count=5,
        label="five Treasures",
    )
    assert parse_rmc_cost_piece("Sacrifice an artifact") == SacrificePermanentsCost(
        permanent_filter=IsArtifact(), label="an artifact",
    )
    another = parse_rmc_cost_piece("Sacrifice another creature or artifact")
    assert another.another and another.label == "another creature or artifact"
    assert parse_rmc_cost_piece("Remove two +1/+1 counters from this creature") == (
        RemoveCountersFromSelfCost(count=2)
    )
    tap = parse_rmc_cost_piece("Tap an untapped Rebel you control")
    assert tap == TapUntappedPermanentsCost(
        permanent_filter=HasSubtype("Rebel"), label="an untapped Rebel you control",
    )
    assert parse_rmc_cost_piece("Exile this card from your graveyard") == (
        ExileSelfFromGraveyardCost()
    )
    # Unknown nouns / shapes decline.
    assert parse_rmc_cost_piece("Sacrifice a blue thing") is None
    assert parse_rmc_cost_piece("Tap two untapped green things you control") is None
    assert parse_rmc_cost_piece("Discard two cards") is None
    # "Sacrifice a/an <card type>" is the base grammar's
    # ``sacrifice_a_permanent_type`` field (tried first); counted
    # sacrifices fall through to the composable atom.
    assert _parse_activation_cost("{T}, Sacrifice an artifact").extra_costs == ()
    cost = _parse_activation_cost("{T}, Sacrifice two artifacts")
    assert cost.tap_self and cost.extra_costs == (
        SacrificePermanentsCost(permanent_filter=IsArtifact(), count=2, label="two artifacts"),
    )
    assert "Sacrifice two artifacts" in cost.describe()


def test_grammar_disabled_and_eoe_guard():
    with rmc_grammar_disabled():
        assert parse_rmc_cost_piece("Sacrifice a Forest") is None
        assert parse_rmc_effect("add three mana of any one color") is None
        assert parse_rmc_creature_line_pre("Exhaust — {T}: Draw a card.", "X") is None
        assert parse_rmc_creature_line_post("Spells you control can't be countered.", "X") is None
    # Intruding Soulrager (Duskmourn only) keeps its pre-bucket
    # unclaimed status; cube cards shared with the EoE dumps don't.
    assert is_eoe_only_printing("Intruding Soulrager")
    assert not is_eoe_only_printing("Screaming Nemesis")


def test_effect_grammar_shapes():
    assert parse_rmc_effect("add three mana of any one color") == AddNManaOfChosenColor(amount=3)
    assert parse_rmc_effect("this creature deals 1 damage to any target") is not None
    assert parse_rmc_effect("it deals 1 damage to any target") is None
    assert parse_rmc_effect("this creature fights nobody") is None
    assert parse_rmc_effect("something unknown") is None


def test_pre_line_rejections():
    # An Exhaust body that doesn't parse, or that functions from the
    # graveyard, is declined.
    assert parse_rmc_creature_line_pre("Exhaust — {T}: Frobnicate.", "X") is None
    assert parse_rmc_creature_line_pre(
        "Exhaust — {1}, Exile this card from your graveyard: Draw a card.", "X",
    ) is None
    assert parse_rmc_creature_line_pre("Exile this card from your hand: Frobnicate.", "X") is None
    # A graveyard-mentioning battlefield ability stays with the clause
    # dispatcher.
    assert parse_rmc_creature_line_pre(
        "{T}: Exile target card from a graveyard.", "X",
    ) is None
    grant_all = parse_rmc_creature_line_post('Creatures you control have "Ward—Pay 3 life."', "X")
    assert grant_all.statics[0].grants_ward_life_cost == 3
    assert parse_rmc_creature_line_post("Nothing here.", "X") is None


# ---------------------------------------------------------------------------
# Walking Ballista
# ---------------------------------------------------------------------------


def test_walking_ballista_x_counters_and_ping():
    state = make_state()
    add_lands(state, 0, "Mountain", 5)
    ballista = add(state, 0, "Walking Ballista", Zone.HAND)
    state.players[0].agent.scripts["x"] = [2]
    cast(state, 0, ballista)
    assert ballista in state.battlefield and ballista.plus_one_counters == 2
    # Remove a counter: 1 damage to the opponent.
    state.players[0].agent.scripts["target"] = [("player", 1)]
    activate(state, 0, ballista, idx=1)
    assert state.players[1].life == 19
    assert ballista.plus_one_counters == 1
    activate(state, 0, ballista, idx=1)
    assert ballista.plus_one_counters == 0
    # No counters left: not activatable; 0/0 dies to SBA.
    assert not can_activate(state, 0, ballista, idx=1)


# ---------------------------------------------------------------------------
# Simian Spirit Guide (hand ability) / Orcish Lumberjack (sac a Forest)
# ---------------------------------------------------------------------------


def test_simian_spirit_guide_exiles_from_hand_for_red_mana():
    guide_printing = printing("Simian Spirit Guide")
    assert len(guide_printing.hand_activated_abilities) == 1
    ability = guide_printing.hand_activated_abilities[0]
    assert ability.cost.exile_self and ability.is_mana_ability
    state = make_state(step=Step.COMBAT_DAMAGE if hasattr(Step, "COMBAT_DAMAGE") else Step.PRECOMBAT_MAIN)
    state.active_player_idx = 1  # opponent's turn: still activatable
    guide = add(state, 0, "Simian Spirit Guide", Zone.HAND)
    state.priority_player_idx = 0
    activate(state, 0, guide)
    assert guide in state.players[0].exile
    assert [c.color for c in state.players[0].mana_pool] == ["R"]


def test_orcish_lumberjack_sacrifices_a_forest():
    state = make_state()
    jack = add(state, 0, "Orcish Lumberjack")
    assert not can_activate(state, 0, jack)  # no Forest
    forest = add(state, 0, "Forest")
    state.players[0].agent.scripts["color"] = ["R", "G", "R"]
    activate(state, 0, jack)
    assert forest in state.players[0].graveyard and jack.tapped
    assert sorted(c.color for c in state.players[0].mana_pool) == ["G", "R", "R"]
    sick = add(state, 0, "Orcish Lumberjack", sick=True)
    add(state, 0, "Forest")
    assert not can_activate(state, 0, sick)


# ---------------------------------------------------------------------------
# Loot, the Pathfinder (Exhaust)
# ---------------------------------------------------------------------------


def test_loot_exhaust_abilities_each_once():
    loot_printing = printing("Loot, the Pathfinder")
    assert [a.exhaust for a in loot_printing.activated_abilities] == [True, True, True]
    assert loot_printing.activated_abilities[0].describe().startswith("Exhaust — ")
    state = make_state()
    loot = add(state, 0, "Loot, the Pathfinder")
    add_lands(state, 0, "Forest", 1)
    add_lands(state, 0, "Island", 1)
    add_lands(state, 0, "Mountain", 2)
    for _ in range(5):
        add(state, 0, "Island", Zone.LIBRARY)
    state.players[0].agent.scripts["color"] = ["U"]
    activate(state, 0, loot, idx=0)
    assert [c.color for c in state.players[0].mana_pool] == ["U", "U", "U"]
    assert not can_activate(state, 0, loot, idx=0)
    loot.tapped = False
    activate(state, 0, loot, idx=1)
    assert len(state.players[0].hand) == 3
    loot.tapped = False
    state.players[0].agent.scripts["target"] = [("player", 1)]
    activate(state, 0, loot, idx=2)
    assert state.players[1].life == 17
    loot.tapped = False
    assert not any(can_activate(state, 0, loot, idx=i) for i in range(3))
    # A new object (left and came back) may exhaust again.
    from mtg_bot.turn import move_off_battlefield

    move_off_battlefield(state, loot, destination="exile")
    assert loot.exhausted_abilities == frozenset()


# ---------------------------------------------------------------------------
# Hexing Squelcher
# ---------------------------------------------------------------------------


def test_hexing_squelcher_uncounterable_spells_and_granted_ward():
    sq = printing("Hexing Squelcher")
    assert sq.spell_is_uncounterable and sq.ward_life_cost == 2
    state = make_state()
    squelcher = add(state, 0, "Hexing Squelcher")
    bear = add(state, 0, "Orcish Lumberjack")
    assert effective_ward_life_cost(state, bear) == 2
    assert effective_ward_life_cost(state, squelcher) == 2  # "Other"
    # Opponent Bolts the Lumberjack: pays 2 life for ward.
    state.active_player_idx = 1
    state.priority_player_idx = 1
    add(state, 1, "Mountain")
    bolt = add(state, 1, "Lightning Bolt", Zone.HAND)
    state.players[1].agent.scripts["target"] = [("creature", bear.id)]
    apply_action(state, 1, CastSpell(bolt.id))
    assert state.players[1].life == 18
    resolve_all(state)
    assert bear not in state.battlefield
    # Spells P0 controls can't be countered.
    from mtg_bot.effects.generic.stack_control import CounterTargetSpell

    state.active_player_idx = 0
    add_lands(state, 0, "Mountain", 2)
    ballista = add(state, 0, "Walking Ballista", Zone.HAND)
    state.players[0].agent.scripts["x"] = [1]
    apply_action(state, 0, CastSpell(ballista.id))
    assert CounterTargetSpell().legal_targets(state, 1) == []


# ---------------------------------------------------------------------------
# Golos, Tireless Pilgrim
# ---------------------------------------------------------------------------


def test_golos_search_tapped_and_free_play_from_exile():
    state = make_state()
    add_lands(state, 0, "Plains", 5)
    golos = add(state, 0, "Golos, Tireless Pilgrim", Zone.HAND)
    swamp = add(state, 0, "Swamp", Zone.LIBRARY)
    add(state, 0, "Island", Zone.LIBRARY)
    state.players[0].agent.scripts["library"] = [swamp.id]
    cast(state, 0, golos)
    assert swamp in state.battlefield and swamp.tapped
    # Activation: exile the top three, play them free this turn.
    lib = state.players[0].library
    lib.clear()
    ballista = add(state, 0, "Walking Ballista", Zone.LIBRARY)
    island = add(state, 0, "Island", Zone.LIBRARY)
    add(state, 0, "Lightning Bolt", Zone.LIBRARY)
    for land in state.battlefield:
        land.tapped = False
    state.players[0].mana_pool.extend(
        ManaCoin(color=c) for c in ("W", "U", "B", "R", "G", "C", "C")
    )
    activate(state, 0, golos, idx=0)
    assert ballista in state.players[0].exile
    assert ballista.exile_play_permission.free
    actions = legal_actions(state, 0)
    assert CastSpell(ballista.id, cast_for_free=True) in actions
    from mtg_bot.actions import PlayLand

    assert PlayLand(island.id) in actions
    apply_action(state, 0, PlayLand(island.id))
    assert island in state.battlefield
    cast(state, 0, ballista, cast_for_free=True)
    # Cast for free: X is 0, so the 0/0 Ballista resolves then dies.
    assert ballista in state.players[0].graveyard
    assert "Walking Ballista resolves onto the battlefield" in state.log
    # The remaining permission (Lightning Bolt) ends at cleanup.
    bolt = state.players[0].exile[-1]
    assert bolt.exile_play_permission is not None
    run_cleanup_step(state)
    assert bolt.exile_play_permission is None


# ---------------------------------------------------------------------------
# Exile play permission bookkeeping
# ---------------------------------------------------------------------------


def test_permission_durations_and_opponent_exile():
    state = make_state()
    p0 = state.players[0]
    p0.turns_started = 3
    card = state.new_object(printing("Lightning Bolt"), owner_id=1, zone=Zone.LIBRARY)
    exile_card(state, card)
    assert card in state.players[1].exile
    grant_exile_play(state, card, 0, duration=UNTIL_YOUR_NEXT_END_STEP)
    add(state, 0, "Mountain")
    # P0 may cast the opponent's exiled card (instant: any priority).
    assert CastSpell(card.id) in legal_actions(state, 0)
    assert CastSpell(card.id) not in legal_actions(state, 1)
    # Opponent's turn cleanup: survives; P0's cleanup: expires.
    state.active_player_idx = 1
    run_cleanup_step(state)
    assert card.exile_play_permission is not None
    state.active_player_idx = 0
    run_cleanup_step(state)
    assert card.exile_play_permission is None

    perm = ExilePlayPermission(
        player_id=0, duration=UNTIL_END_OF_YOUR_NEXT_TURN, granted_player_turns=3,
    )
    card.exile_play_permission = perm
    run_cleanup_step(state)  # the granting turn itself
    assert card.exile_play_permission is perm
    p0.turns_started = 4
    run_cleanup_step(state)
    assert card.exile_play_permission is None


def test_face_down_exile_known_only_to_controller():
    state = make_state()
    card = state.new_object(printing("Lightning Bolt"), owner_id=0, zone=Zone.LIBRARY)
    exile_card(state, card, face_down_for=0)
    assert card.publicly_known_to == frozenset({0})


def test_any_color_mana_permission_cost():
    from mtg_bot.effects.generic.cube_creatures_rmc import exile_permission_cast_cost

    card = add(make_state(), 1, "Lightning Bolt", Zone.EXILE)
    perm = ExilePlayPermission(player_id=0, any_color_mana=True)
    cost = exile_permission_cast_cost(card, perm)
    assert cost.generic == 1 and cost.colored == ()


# ---------------------------------------------------------------------------
# Seasoned Pyromancer's graveyard ability
# ---------------------------------------------------------------------------


def test_graveyard_ability_exiles_itself_for_elementals():
    pyro = printing("Seasoned Pyromancer") if "Seasoned Pyromancer" in __import__(
        "tests._rmc_helpers", fromlist=["cube_printings"],
    ).cube_printings() else None
    if pyro is None:
        pytest.skip("Seasoned Pyromancer not claimed yet")
    state = make_state()
    card = add(state, 0, "Seasoned Pyromancer", Zone.GRAVEYARD)
    assert not can_activate(state, 0, card)  # no mana
    add_lands(state, 0, "Mountain", 5)
    activate(state, 0, card)
    assert card in state.players[0].exile
    elementals = [o for o in state.battlefield if o.printing.name == "Elemental"]
    assert len(elementals) == 2
