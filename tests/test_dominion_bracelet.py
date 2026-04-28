"""Tests for The Dominion Bracelet — equipment-granted control-opponent
activated ability, exile-granting-equipment cost, X-reduction from
equipped power, and scheduled-agent-override mechanics."""

from mtg_bot import legal_moves
from mtg_bot.actions import (
    ActivateAbility, apply_action, _effective_ability_mana_cost,
    resolve_top_of_stack,
)
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import BASIC_LANDS, DOMINION_BRACELET_GRANTED_ABILITY, SYNTHETIC_CREATURES
from mtg_bot.effects import ControlTargetOpponentNextTurn
from mtg_bot.game import GameState, Player, Zone, effective_activated_abilities
from mtg_bot.turn import Step, run_cleanup_step, run_untap_step

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _PickFirstAgent(Agent):
    name: str = "pick-first"

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


def _put(state, printing, owner_id=0, attached_to=None):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    if attached_to is not None:
        obj.attached_to = attached_to
    state.battlefield.append(obj)
    return obj


# -----------------------
# Printing metadata
# -----------------------


def test_bracelet_printing_metadata():
    b = _PRINTINGS["The Dominion Bracelet"]
    assert "Legendary" in b.supertypes
    assert b.equipment_bonuses[:2] == (1, 1)
    assert b.grants_control_opponent_ability_when_equipped is True


def test_granted_ability_shape():
    a = DOMINION_BRACELET_GRANTED_ABILITY
    assert a.sorcery_speed is True
    assert a.cost.mana_str == "{15}"
    assert a.cost.exile_granting_equipment is True
    assert a.cost.mana_reduced_by_source_power is True
    assert isinstance(a.effect, ControlTargetOpponentNextTurn)


# -----------------------
# Equipment-granted ability appears on equipped creature
# -----------------------


def test_equipped_creature_gains_granted_ability():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    _put(state, _PRINTINGS["The Dominion Bracelet"], attached_to=bear.id)
    abilities = effective_activated_abilities(state, bear)
    # Wild Bear has no printed abilities; the Bracelet appends one.
    assert len(abilities) == 1
    assert abilities[0] is DOMINION_BRACELET_GRANTED_ABILITY


def test_unequipped_creature_does_not_gain_granted_ability():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    _put(state, _PRINTINGS["The Dominion Bracelet"])  # not attached
    abilities = effective_activated_abilities(state, bear)
    assert all(a is not DOMINION_BRACELET_GRANTED_ABILITY for a in abilities)


# -----------------------
# X-cost reduction from equipped power
# -----------------------


def test_x_reduction_from_equipped_power_cuts_generic():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])  # 2/2
    _put(state, _PRINTINGS["The Dominion Bracelet"], attached_to=bear.id)
    eff = _effective_ability_mana_cost(
        state, bear, DOMINION_BRACELET_GRANTED_ABILITY,
    )
    # Base {15} generic = 15; equipped Bear is 2/2, so +1 from bracelet
    # = effective power 3; 15 - 3 = 12.
    assert eff.generic == 12


def test_x_reduction_never_below_zero():
    state = _new_state()
    # Build a fake huge-power creature via counters so 15 - power < 0.
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    bear.plus_one_counters = 100
    _put(state, _PRINTINGS["The Dominion Bracelet"], attached_to=bear.id)
    eff = _effective_ability_mana_cost(
        state, bear, DOMINION_BRACELET_GRANTED_ABILITY,
    )
    assert eff.generic == 0


# -----------------------
# Legal-actions gating
# -----------------------


def test_ability_not_offered_at_instant_speed():
    state = _new_state()
    # Force instant-speed window (stack non-empty, opponent's priority).
    state.priority_player_idx = 1
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    bear.summoning_sick = False
    _put(state, _PRINTINGS["The Dominion Bracelet"], attached_to=bear.id)
    for _ in range(20):
        _put(state, BASIC_LANDS["Forest"])
    actions = legal_moves(state)
    # Ability is sorcery-speed — nothing offered when priority is
    # opponent's and stack is mid-activity. Ensure no ActivateAbility
    # for the bear.
    assert not any(
        isinstance(a, ActivateAbility) and a.source_id == bear.id
        for a in actions
    )


def test_ability_offered_at_sorcery_speed_when_payable():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])  # 2/2
    bear.summoning_sick = False
    _put(state, _PRINTINGS["The Dominion Bracelet"], attached_to=bear.id)
    # Need {15} - (2 printed + 1 bracelet) = {12} = 12 lands.
    for _ in range(12):
        _put(state, BASIC_LANDS["Forest"])
    actions = legal_moves(state)
    assert any(
        isinstance(a, ActivateAbility) and a.source_id == bear.id
        for a in actions
    )


def test_ability_not_offered_when_insufficient_mana():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    bear.summoning_sick = False
    _put(state, _PRINTINGS["The Dominion Bracelet"], attached_to=bear.id)
    # Only 5 lands; need 12 with Bear as source.
    for _ in range(5):
        _put(state, BASIC_LANDS["Forest"])
    actions = legal_moves(state)
    assert not any(
        isinstance(a, ActivateAbility) and a.source_id == bear.id
        for a in actions
    )


# -----------------------
# Full activation: exile bracelet + schedule override
# -----------------------


def test_activation_exiles_bracelet_and_schedules_override():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    bear.summoning_sick = False
    bracelet = _put(
        state, _PRINTINGS["The Dominion Bracelet"], attached_to=bear.id,
    )
    for _ in range(12):
        _put(state, BASIC_LANDS["Forest"])
    # Find the ability index on the bear.
    abilities = effective_activated_abilities(state, bear)
    idx = next(
        i for i, a in enumerate(abilities)
        if a is DOMINION_BRACELET_GRANTED_ABILITY
    )
    apply_action(state, 0, ActivateAbility(source_id=bear.id, ability_index=idx))
    while state.stack:
        resolve_top_of_stack(state)
    # Bracelet exiled; target opponent (P1) has override scheduled.
    assert bracelet in state.players[0].exile
    assert state.players[1].scheduled_agent_override is state.players[0].agent
    assert state.players[1].scheduled_agent_override_by == 0


# -----------------------
# Agent override apply/revert
# -----------------------


def test_untap_step_installs_scheduled_override():
    state = _new_state()
    # Make P1 the active player (i.e. opponent's turn has started).
    state.active_player_idx = 1
    original_p1_agent = state.players[1].agent
    state.players[1].scheduled_agent_override = state.players[0].agent
    state.players[1].scheduled_agent_override_by = 0
    run_untap_step(state)
    # P1 is now controlled by P0's agent; P1's original agent saved.
    assert state.players[1].agent is state.players[0].agent
    assert state.players[1].agent_override_saved is original_p1_agent


def test_cleanup_reverts_override():
    state = _new_state()
    state.active_player_idx = 1
    original_p1_agent = state.players[1].agent
    # Simulate override already installed.
    state.players[1].agent_override_saved = original_p1_agent
    state.players[1].agent = state.players[0].agent
    run_cleanup_step(state)
    assert state.players[1].agent is original_p1_agent
    assert state.players[1].agent_override_saved is None


# -----------------------
# Effect-level
# -----------------------


def test_effect_legal_targets_opponents_only():
    state = _new_state()
    targets = ControlTargetOpponentNextTurn().legal_targets(state, 0)
    assert targets == [("player", 1)]


def test_effect_no_target_is_noop():
    state = _new_state()
    ControlTargetOpponentNextTurn().resolve(state, 0, ())
    assert state.players[1].scheduled_agent_override is None


def test_effect_wrong_kind_is_noop():
    state = _new_state()
    ControlTargetOpponentNextTurn().resolve(state, 0, (("creature", 1),))
    assert state.players[1].scheduled_agent_override is None


def test_effect_describe():
    d = ControlTargetOpponentNextTurn().describe()
    assert "control" in d and "opponent" in d


# -----------------------
# Exile-granting-equipment cost cannot be paid without the bracelet
# -----------------------


def test_effective_ability_cost_no_reduction_with_zero_power():
    """Cost reduction clamps correctly when source power is 0 or less."""
    from mtg_bot.cards import make_creature
    state = _new_state()
    zero = make_creature("Zero Power", "{G}", 0, 3)
    host = state.new_object(zero, 0, Zone.BATTLEFIELD)
    state.battlefield.append(host)
    _put(state, _PRINTINGS["The Dominion Bracelet"], attached_to=host.id)
    eff = _effective_ability_mana_cost(
        state, host, DOMINION_BRACELET_GRANTED_ABILITY,
    )
    # Equipment bonus +1 → effective power 1 → cost 15 - 1 = 14.
    assert eff.generic == 14


def test_describe_mentions_exile_and_x_reduction():
    cost = DOMINION_BRACELET_GRANTED_ABILITY.cost
    d = cost.describe()
    assert "Exile this equipment" in d
    assert "{X} less" in d


def test_untap_without_scheduled_override_is_noop():
    state = _new_state()
    # No scheduled override.
    original = state.players[0].agent
    run_untap_step(state)
    assert state.players[0].agent is original
    assert state.players[0].agent_override_saved is None


def test_ability_not_offered_when_bracelet_not_attached():
    """After the bracelet is exiled, the equipped creature no longer
    has the ability (because it's granted by the equipment, which is
    gone). This is the MTG "ability fails" failsafe."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    bear.summoning_sick = False
    # Exile the bracelet straight to exile — no attachment.
    br = state.new_object(
        _PRINTINGS["The Dominion Bracelet"], 0, Zone.EXILE,
    )
    state.players[0].exile.append(br)
    for _ in range(15):
        _put(state, BASIC_LANDS["Forest"])
    actions = legal_moves(state)
    assert not any(
        isinstance(a, ActivateAbility) and a.source_id == bear.id
        for a in actions
    )
