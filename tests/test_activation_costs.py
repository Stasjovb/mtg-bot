"""Tests for new activation costs + target-filter effects."""

from mtg_bot.actions import ActivateAbility, _activate_ability, apply_action, resolve_top_of_stack
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import (
    BASIC_LANDS,
    EOE_CREATURES,
    EOE_SPELLS,
    SYNTHETIC_CREATURES,
)
from mtg_bot.effects import (
    ActivationCost,
    TapAnotherTargetCreature,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.legal import legal_actions


def _new_state_with_lands(num_plains: int = 0, num_forests: int = 0):
    state = GameState()
    p = Player(id=0, agent=RandomAgent())
    p2 = Player(id=1, agent=RandomAgent())
    state.players.append(p)
    state.players.append(p2)
    for _ in range(num_plains):
        pl = state.new_object(BASIC_LANDS["Plains"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(pl)
    for _ in range(num_forests):
        f = state.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(f)
    return state


# -----------------------
# TapAnotherTargetCreature
# -----------------------


def test_tap_another_target_creature_excludes_self():
    """Starport Security's tap-another activated ability can't target itself."""
    state = _new_state_with_lands()
    security = state.new_object(
        EOE_CREATURES["Starport Security"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(security)
    # Put another creature on the battlefield — the only legal target.
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    state.resolving_source = security
    effect = TapAnotherTargetCreature()
    legal = effect.legal_targets(state, 0)
    state.resolving_source = None
    ids = {t[1] for t in legal}
    assert bear.id in ids
    assert security.id not in ids


def test_tap_another_target_resolve_taps():
    state = _new_state_with_lands()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    effect = TapAnotherTargetCreature()
    assert not bear.tapped
    effect.resolve(state, 0, (("creature", bear.id),))
    assert bear.tapped


def test_tap_another_target_no_target_noop():
    state = _new_state_with_lands()
    effect = TapAnotherTargetCreature()
    effect.resolve(state, 0, ())


def test_tap_another_target_wrong_kind_noop():
    state = _new_state_with_lands()
    effect = TapAnotherTargetCreature()
    effect.resolve(state, 0, (("player", 0),))


def test_tap_another_target_missing_obj_noop():
    state = _new_state_with_lands()
    effect = TapAnotherTargetCreature()
    effect.resolve(state, 0, (("creature", 999),))


def test_tap_another_target_describe():
    assert "another" in TapAnotherTargetCreature().describe()


# -----------------------
# Starport Security full activation flow via legal_actions
# -----------------------


def test_starport_security_activation_only_legal_with_another_creature():
    """With only Starport Security on the battlefield, the tap-another
    activation isn't a legal action — there's no valid target."""
    state = _new_state_with_lands(num_plains=4)
    state.step = __import__("mtg_bot.turn", fromlist=["Step"]).Step.PRECOMBAT_MAIN
    security = state.new_object(
        EOE_CREATURES["Starport Security"], 0, Zone.BATTLEFIELD,
    )
    security.summoning_sick = False
    state.battlefield.append(security)
    actions = legal_actions(state, 0)
    act_abs = [a for a in actions if isinstance(a, ActivateAbility)]
    assert act_abs == []


def test_starport_security_activation_legal_with_another_creature():
    state = _new_state_with_lands(num_plains=4)
    state.step = __import__("mtg_bot.turn", fromlist=["Step"]).Step.PRECOMBAT_MAIN
    security = state.new_object(
        EOE_CREATURES["Starport Security"], 0, Zone.BATTLEFIELD,
    )
    security.summoning_sick = False
    state.battlefield.append(security)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    actions = legal_actions(state, 0)
    act_abs = [a for a in actions if isinstance(a, ActivateAbility)]
    assert len(act_abs) == 1
    # Activate and resolve.
    apply_action(state, 0, act_abs[0])
    resolve_top_of_stack(state)
    assert bear.tapped
    assert security.tapped


# -----------------------
# remove_plus_one_counter_from_your_creature cost
# -----------------------


def test_sunstar_chaplain_activation_requires_counter_creature():
    """Sunstar Chaplain's activated ability requires a +1/+1 counter on
    one of your creatures to pay the cost."""
    from mtg_bot.turn import Step
    state = _new_state_with_lands(num_plains=2)
    state.step = Step.PRECOMBAT_MAIN
    chaplain = state.new_object(
        EOE_CREATURES["Sunstar Chaplain"], 0, Zone.BATTLEFIELD,
    )
    chaplain.summoning_sick = False
    state.battlefield.append(chaplain)
    target = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(target)
    # No creature with +1/+1 counter → activation illegal.
    acts = [a for a in legal_actions(state, 0) if isinstance(a, ActivateAbility)]
    assert acts == []

    # Put a counter on our own creature — now legal.
    chaplain.plus_one_counters = 2
    acts = [a for a in legal_actions(state, 0) if isinstance(a, ActivateAbility)]
    assert len(acts) == 1
    # Activate: removes a +1/+1 counter from chaplain.
    apply_action(state, 0, acts[0])
    resolve_top_of_stack(state)
    assert chaplain.plus_one_counters == 1
    assert target.tapped


def test_activation_cost_describe_includes_remove_counter():
    c = ActivationCost(
        mana_str="{2}",
        remove_plus_one_counter_from_your_creature=True,
    )
    text = c.describe()
    assert "Remove a +1/+1 counter" in text


def test_remove_plus_one_counter_cost_picks_from_options_with_agent():
    """When multiple counter-bearing creatures exist, the agent picks."""
    from mtg_bot.agents import Agent
    from mtg_bot.turn import Step

    class PickFirstAgent(Agent):
        def choose_sacrifice(self, state, player_id, legal_object_ids):
            return legal_object_ids[0]

        def choose_target(self, state, player_id, legal_targets):
            return legal_targets[0] if legal_targets else None

    state = _new_state_with_lands(num_plains=2)
    state.players[0].agent = PickFirstAgent()
    state.step = Step.PRECOMBAT_MAIN
    chaplain = state.new_object(
        EOE_CREATURES["Sunstar Chaplain"], 0, Zone.BATTLEFIELD,
    )
    chaplain.summoning_sick = False
    chaplain.plus_one_counters = 3
    state.battlefield.append(chaplain)
    other = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    other.plus_one_counters = 2
    state.battlefield.append(other)
    target = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(target)
    acts = [a for a in legal_actions(state, 0) if isinstance(a, ActivateAbility)]
    assert acts
    apply_action(state, 0, acts[0])
    resolve_top_of_stack(state)
    # PickFirstAgent picks the first listed option; the chaplain is
    # first in the iteration order (appended first).
    assert chaplain.plus_one_counters == 2
    assert other.plus_one_counters == 2
    # Some permanent gets tapped (exact one depends on target pick).
    assert any(o.tapped for o in state.battlefield)
