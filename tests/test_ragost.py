"""Tests for Ragost, Deft Gastronaut — static Food-and-sac-ability
grant, sacrifice-a-Food activated ability, and per-end-step
if-gained-life untap trigger."""

from mtg_bot import legal_moves
from mtg_bot.actions import ActivateAbility, apply_action, drain_stack
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import BASIC_LANDS, EOE_CREATURES, EOE_SPELLS, SYNTHETIC_CREATURES
from mtg_bot.effects import GainLife, IfGainedLifeThisTurnUntapSelf
from mtg_bot.game import (
    GameState, Player, Zone,
    effective_activated_abilities, effective_subtypes, gain_life,
)
from mtg_bot.turn import Step, run_beginning_of_end_step_triggers, run_cleanup_step


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_sacrifice(self, state, player_id, legal_ids):
        return legal_ids[0] if legal_ids else None


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


# -----------------------
# gain_life helper + life_gained_this_turn tracking
# -----------------------


def test_gain_life_tracks_amount_gained():
    state = _new_state()
    gain_life(state, 0, 3)
    assert state.players[0].life == 23
    assert state.players[0].life_gained_this_turn == 3


def test_gain_life_noop_on_non_positive():
    state = _new_state()
    gain_life(state, 0, 0)
    gain_life(state, 0, -5)
    assert state.players[0].life_gained_this_turn == 0


def test_cleanup_resets_life_gained_this_turn():
    state = _new_state()
    state.players[0].life_gained_this_turn = 5
    run_cleanup_step(state)
    assert state.players[0].life_gained_this_turn == 0


def test_gain_life_effect_routes_through_helper():
    state = _new_state()
    GainLife(amount=4).resolve(state, 0, ())
    assert state.players[0].life_gained_this_turn == 4


# -----------------------
# Static Food + ability grants
# -----------------------


def test_ragost_static_adds_food_subtype_to_your_artifacts():
    state = _new_state()
    _put(state, EOE_CREATURES["Ragost, Deft Gastronaut"])
    art = _put(state, EOE_SPELLS["Nutrient Block"])  # {1} artifact
    subs = effective_subtypes(state, art)
    assert "Food" in subs


def test_ragost_static_does_not_affect_opponents_artifacts():
    state = _new_state()
    _put(state, EOE_CREATURES["Ragost, Deft Gastronaut"])
    opp_art = _put(state, EOE_SPELLS["Nutrient Block"], owner_id=1)
    subs = effective_subtypes(state, opp_art)
    assert "Food" not in subs


def test_ragost_static_does_not_affect_non_artifacts():
    state = _new_state()
    _put(state, EOE_CREATURES["Ragost, Deft Gastronaut"])
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    subs = effective_subtypes(state, bear)
    assert "Food" not in subs


def test_ragost_static_grants_sac_for_3_life_ability():
    state = _new_state()
    _put(state, EOE_CREATURES["Ragost, Deft Gastronaut"])
    art = _put(state, EOE_SPELLS["Nutrient Block"])
    abilities = effective_activated_abilities(state, art)
    # Nutrient Block's printed ability PLUS Ragost's granted ability.
    assert len(abilities) == len(art.printing.activated_abilities) + 1


def test_ragost_removed_retracts_food_and_ability_grants():
    state = _new_state()
    ragost = _put(state, EOE_CREATURES["Ragost, Deft Gastronaut"])
    art = _put(state, EOE_SPELLS["Nutrient Block"])
    assert "Food" in effective_subtypes(state, art)
    state.battlefield.remove(ragost)
    assert "Food" not in effective_subtypes(state, art)


# -----------------------
# The granted "{2}, {T}, Sacrifice: gain 3 life" ability works
# -----------------------


def test_granted_food_ability_activatable_and_gains_life():
    state = _new_state()
    _put(state, EOE_CREATURES["Ragost, Deft Gastronaut"])
    art = _put(state, EOE_SPELLS["Nutrient Block"])
    # Mana for {2}.
    for _ in range(2):
        _put(state, BASIC_LANDS["Mountain"])
    # Nutrient Block already has its printed sac ability at index 0;
    # Ragost's granted ability is appended at the next index.
    granted_idx = len(art.printing.activated_abilities)
    life_before = state.players[0].life
    apply_action(
        state, 0,
        ActivateAbility(source_id=art.id, ability_index=granted_idx),
    )
    # Ragost grants activated abilities that are NOT mana abilities
    # (effect is GainLife, not AddManaToPool) — they go on the stack.
    # Resolve it.
    from mtg_bot.actions import resolve_top_of_stack
    while state.stack:
        resolve_top_of_stack(state)
    assert state.players[0].life == life_before + 3
    assert art not in state.battlefield
    assert state.players[0].life_gained_this_turn == 3


# -----------------------
# Ragost's activated ability: sac a Food, deal 3 to each opponent
# -----------------------


def test_ragost_sac_food_deals_3_to_each_opponent():
    state = _new_state()
    ragost = _put(state, EOE_CREATURES["Ragost, Deft Gastronaut"])
    ragost.summoning_sick = False
    # Grant artifact that becomes Food via Ragost's static.
    art = _put(state, EOE_SPELLS["Nutrient Block"])
    # Mana for {1}.
    _put(state, BASIC_LANDS["Mountain"])
    life_before = state.players[1].life
    apply_action(
        state, 0,
        ActivateAbility(source_id=ragost.id, ability_index=0),
    )
    from mtg_bot.actions import resolve_top_of_stack
    while state.stack:
        resolve_top_of_stack(state)
    # Art sacrificed; P1 took 3 damage.
    assert art not in state.battlefield
    assert state.players[1].life == life_before - 3
    # Ragost tapped as part of cost.
    assert ragost.tapped is True


def test_ragost_sac_food_not_legal_without_a_food():
    state = _new_state()
    ragost = _put(state, EOE_CREATURES["Ragost, Deft Gastronaut"])
    ragost.summoning_sick = False
    _put(state, BASIC_LANDS["Mountain"])
    # No artifacts to sac as Food → ability not legal.
    actions = legal_moves(state)
    assert not any(
        isinstance(a, ActivateAbility) and a.source_id == ragost.id
        for a in actions
    )


# -----------------------
# Beginning-of-each-end-step untap
# -----------------------


def test_ragost_untaps_at_own_end_step_if_gained_life():
    state = _new_state()
    ragost = _put(state, EOE_CREATURES["Ragost, Deft Gastronaut"])
    ragost.tapped = True
    state.players[0].life_gained_this_turn = 2
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)
    assert ragost.tapped is False


def test_ragost_stays_tapped_without_life_gain():
    state = _new_state()
    ragost = _put(state, EOE_CREATURES["Ragost, Deft Gastronaut"])
    ragost.tapped = True
    # No life gained.
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)
    assert ragost.tapped is True


def test_ragost_untaps_on_opponents_end_step_too():
    """'At the beginning of EACH end step' — fires on both players'
    end steps."""
    state = _new_state()
    ragost = _put(state, EOE_CREATURES["Ragost, Deft Gastronaut"])
    ragost.tapped = True
    state.players[0].life_gained_this_turn = 1
    # Switch active player to opponent's turn.
    state.active_player_idx = 1
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)
    assert ragost.tapped is False


def test_if_gained_life_untap_effect_noop_when_no_source():
    state = _new_state()
    IfGainedLifeThisTurnUntapSelf().resolve(state, 0, ())  # no crash


def test_gain_life_public_helper_reads_amount():
    state = _new_state()
    assert gain_life(state, 0, 5) == 5
    # Non-positive → 0.
    assert gain_life(state, 0, 0) == 0
    assert gain_life(state, 0, -2) == 0


def test_effective_subtypes_no_ragost_returns_printed_only():
    state = _new_state()
    art = _put(state, EOE_SPELLS["Nutrient Block"])
    assert effective_subtypes(state, art) == art.printing.subtypes


def test_effective_activated_abilities_no_ragost_returns_printed_only():
    state = _new_state()
    art = _put(state, EOE_SPELLS["Nutrient Block"])
    assert effective_activated_abilities(state, art) == art.printing.activated_abilities


def test_ragost_sac_food_legal_when_ragost_gives_food_subtype():
    """Confirm legality via Ragost's granted Food subtype on an
    artifact that's not printed as Food."""
    state = _new_state()
    ragost = _put(state, EOE_CREATURES["Ragost, Deft Gastronaut"])
    ragost.summoning_sick = False
    _put(state, BASIC_LANDS["Mountain"])
    # Printed-non-Food artifact now counts as Food.
    _put(state, EOE_SPELLS["Nutrient Block"])
    actions = legal_moves(state)
    assert any(
        isinstance(a, ActivateAbility) and a.source_id == ragost.id
        for a in actions
    )


def test_each_end_step_observer_does_not_duplicate_own_fire():
    """Ragost's beginning_of_each_end_step fires ONCE on the
    controller's own end step (regression against accidentally
    matching both branches)."""
    state = _new_state()
    ragost = _put(state, EOE_CREATURES["Ragost, Deft Gastronaut"])
    ragost.tapped = True
    state.players[0].life_gained_this_turn = 1
    # Count untaps via logs.
    log_before = len(state.log)
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)
    # Just one untap event for Ragost.
    untap_logs = [
        s for s in state.log[log_before:]
        if "Ragost" in s and "untap" in s.lower()
    ]
    assert len(untap_logs) == 1


def test_ragost_printing_metadata():
    r = EOE_CREATURES["Ragost, Deft Gastronaut"]
    assert "Legendary" in r.supertypes
    assert r.grants_food_to_your_artifacts is True
    assert r.grants_food_ability_to_your_artifacts is True
    assert len(r.activated_abilities) == 1
    cost = r.activated_abilities[0].cost
    assert cost.tap_self and cost.mana_str == "{1}" and cost.sacrifice_food
    triggers = {ab.trigger for ab in r.triggered_abilities}
    assert "beginning_of_each_end_step" in triggers
