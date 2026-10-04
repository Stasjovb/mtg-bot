"""U/B cube creatures that cast spells mid-resolution or from outside
the hand: Black Widow (exile until nonland, counter or cast it with any
mana), Malcolm (loot, cast the discarded card free at 4 chorus
counters), Bilbo (outside-hand cost reduction; cast from the graveyard
on attack, exiling instants / sorceries afterwards)."""

from __future__ import annotations

from mtg_bot.actions import (
    CastSpell,
    apply_action,
    apply_cost_reductions,
    drain_stack,
    move_spell_off_stack,
)
from mtg_bot.cards.parser.cube_creatures_ub import _type_list_filter, parse_ub_effect
from mtg_bot.combat import declare_attackers
from mtg_bot.creature_casting_ub import (
    can_cast_now,
    cast_now,
    casting_origin,
)
from mtg_bot.effects.conditions import SpellCastFromOutsideHand
from mtg_bot.effects.generic.cube_creatures_ub import (
    ExileUntilNonlandThenCounterOrMayCastIt,
    LootThenMayCastDiscardedFreeIfCounters,
    MayCastSpellFromGraveyardNow,
)
from mtg_bot.game import Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step
from tests._spells_b_helpers import PRINTINGS, ScriptedAgent, add, add_lands, make_state


def _names(zone):
    return [c.printing.name for c in zone]


# ---------------------------------------------------------------- Black Widow


def test_black_widow_takes_the_counter_when_asked():
    state = make_state(agent0=ScriptedAgent(yes_no=[True]))
    widow = add(state, 0, "Black Widow, Super Spy", Zone.BATTLEFIELD)
    add(state, 1, "Island", Zone.LIBRARY)
    add(state, 1, "Dark Confidant", Zone.LIBRARY)
    add(state, 1, "Swamp", Zone.LIBRARY)
    state.resolving_source = widow
    ExileUntilNonlandThenCounterOrMayCastIt().resolve(state, 0, (("player", 1),))
    assert widow.plus_one_counters == 1
    assert _names(state.players[1].exile) == ["Island", "Dark Confidant"]
    assert all(c.exile_play_permission is None for c in state.players[1].exile)
    assert _names(state.players[1].library) == ["Swamp"]


def test_black_widow_may_cast_the_card_with_any_mana():
    state = make_state(agent0=ScriptedAgent(yes_no=[False]))
    widow = add(state, 0, "Black Widow, Super Spy", Zone.BATTLEFIELD)
    add(state, 1, "Dark Confidant", Zone.LIBRARY)
    state.resolving_source = widow
    ExileUntilNonlandThenCounterOrMayCastIt().resolve(state, 0, (("player", 1),))
    state.resolving_source = None
    (bob,) = state.players[1].exile
    perm = bob.exile_play_permission
    assert perm.player_id == 0 and perm.any_color_mana and perm.cast_only
    add_lands(state, 0, "Mountain", 2)       # no black mana needed
    assert CastSpell(bob.id) in legal_actions(state, 0)
    apply_action(state, 0, CastSpell(bob.id))
    drain_stack(state)
    assert bob in state.battlefield and bob.controller_id == 0
    assert "nonland" in ExileUntilNonlandThenCounterOrMayCastIt().describe()
    ExileUntilNonlandThenCounterOrMayCastIt().resolve(state, 0, ())


def test_black_widow_printing_parses():
    trig = PRINTINGS["Black Widow, Super Spy"].triggered_abilities[0]
    assert trig.effect == ExileUntilNonlandThenCounterOrMayCastIt()


# ---------------------------------------------------------------- Malcolm


def test_malcolm_body_parses():
    eff = PRINTINGS["Malcolm, Alluring Scoundrel"].triggered_abilities[0].effect
    assert eff.effects[1] == LootThenMayCastDiscardedFreeIfCounters("chorus", 4)
    assert "chorus" in eff.effects[1].describe()


def test_malcolm_loots_and_casts_free_at_four_counters():
    agent = ScriptedAgent()
    state = make_state(agent0=agent)
    malcolm = add(state, 0, "Malcolm, Alluring Scoundrel", Zone.BATTLEFIELD)
    malcolm.named_counters = (("chorus", 4),)
    bolt = add(state, 0, "Lightning Bolt", Zone.HAND)
    add(state, 0, "Island", Zone.LIBRARY)
    agent.scripts["discard"] = [bolt.id]
    agent.scripts["target"] = [("player", 1)]
    state.resolving_source = malcolm
    LootThenMayCastDiscardedFreeIfCounters().resolve(state, 0, ())
    state.resolving_source = None
    assert state.stack and state.stack[-1].source is bolt
    drain_stack(state)
    assert state.players[1].life == 17


def test_malcolm_below_threshold_just_loots():
    state = make_state()
    malcolm = add(state, 0, "Malcolm, Alluring Scoundrel", Zone.BATTLEFIELD)
    malcolm.named_counters = (("chorus", 3),)
    add(state, 0, "Island", Zone.LIBRARY)
    state.resolving_source = malcolm
    LootThenMayCastDiscardedFreeIfCounters().resolve(state, 0, ())
    assert _names(state.players[0].graveyard) == ["Island"]
    assert not state.stack
    # Empty library and hand: nothing to discard.
    state.players[0].graveyard.clear()
    LootThenMayCastDiscardedFreeIfCounters().resolve(state, 0, ())


def test_malcolm_combat_trigger_counts_up():
    state = make_state(step=Step.DECLARE_ATTACKERS)
    malcolm = add(state, 0, "Malcolm, Alluring Scoundrel", Zone.BATTLEFIELD)
    add(state, 0, "Island", Zone.LIBRARY)
    declare_attackers(state, [malcolm.id])
    from mtg_bot.combat import resolve_combat_damage

    resolve_combat_damage(state, 1)
    drain_stack(state)
    from mtg_bot.game import named_counter_count

    assert named_counter_count(malcolm, "chorus") == 1
    assert _names(state.players[0].graveyard) == ["Island"]


# ---------------------------------------------------------------- cast_now


def test_cast_now_zones_and_checks():
    state = make_state()
    land = add(state, 0, "Island", Zone.GRAVEYARD)
    assert not can_cast_now(state, 0, land, free=True)
    hand_card = add(state, 0, "Lightning Bolt", Zone.HAND)
    assert not cast_now(state, 0, hand_card, free=True)
    ring = add(state, 0, "Sol Ring", Zone.GRAVEYARD)
    assert not can_cast_now(state, 0, ring, free=False)
    assert can_cast_now(state, 0, ring, free=True)
    other = add(state, 1, "Sol Ring", Zone.EXILE)
    assert cast_now(state, 0, other, free=True)
    drain_stack(state)
    assert other in state.battlefield and other.controller_id == 0


# ---------------------------------------------------------------- Bilbo


def test_bilbo_discounts_spells_cast_from_outside_the_hand():
    bilbo = PRINTINGS["Bilbo, Thief in the Night"]
    (ext,) = bilbo.external_cost_reductions
    assert ext.condition == SpellCastFromOutsideHand()
    state = make_state()
    add(state, 0, "Bilbo, Thief in the Night", Zone.BATTLEFIELD)
    cost = PRINTINGS["Sol Ring"].mana_cost
    assert apply_cost_reductions(PRINTINGS["Sol Ring"], state, 0, cost).generic == 1
    with casting_origin(True):
        assert apply_cost_reductions(PRINTINGS["Sol Ring"], state, 0, cost).generic == 0


def test_bilbo_attack_casts_from_graveyard_and_exiles_sorceries():
    assert _type_list_filter("artifact, instant, or sorcery").any_types == (
        "Artifact", "Instant", "Sorcery",
    )
    assert _type_list_filter("artifact") is None
    eff = parse_ub_effect(
        "you may cast an artifact, instant, or sorcery spell from your "
        "graveyard. If an instant or sorcery spell cast this way would be "
        "put into your graveyard, exile it instead"
    )
    assert isinstance(eff, MayCastSpellFromGraveyardNow)
    assert "graveyard" in eff.describe()
    state = make_state(step=Step.DECLARE_ATTACKERS)
    bilbo = add(state, 0, "Bilbo, Thief in the Night", Zone.BATTLEFIELD)
    bolt = add(state, 0, "Lightning Bolt", Zone.GRAVEYARD)
    add_lands(state, 0, "Mountain", 1)
    state.players[0].agent.scripts["target"] = [("player", 1)]
    declare_attackers(state, [bilbo.id])
    drain_stack(state)
    assert state.players[1].life == 17
    assert bolt in state.players[0].exile
    assert bolt.exile_if_put_into_graveyard_from_stack is False


def test_bilbo_trigger_with_nothing_castable_or_declined():
    eff = MayCastSpellFromGraveyardNow(
        card_filter=_type_list_filter("artifact, instant, or sorcery"),
    )
    state = make_state(agent0=ScriptedAgent(library=[None]))
    eff.resolve(state, 0, ())
    ring = add(state, 0, "Sol Ring", Zone.GRAVEYARD)
    add_lands(state, 0, "Island", 1)
    eff.resolve(state, 0, ())   # declined
    assert ring in state.players[0].graveyard


def test_exile_instead_flag_is_skipped_for_hand_returns():
    state = make_state()
    card = add(state, 0, "Lightning Bolt", Zone.HAND)
    state.players[0].hand.remove(card)
    card.exile_if_put_into_graveyard_from_stack = True
    move_spell_off_stack(state, card, destination="hand")
    assert card in state.players[0].hand
    assert not card.exile_if_put_into_graveyard_from_stack
