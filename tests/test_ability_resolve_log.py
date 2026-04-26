"""``resolve_top_of_stack`` logs the resolved kind correctly.

Pre-fix the log line said "triggered ability resolves" for both
TriggeredAbility AND ActivatedAbility stack items, since the ability
field on a StackItem can hold either type. This file pins the
post-fix behavior: activated abilities log as "activated ability
resolves", triggered abilities log as "triggered ability resolves".
"""

from mtg_bot.actions import (
    ActivateAbility, apply_action, drain_stack, resolve_top_of_stack,
)
from mtg_bot.agents import Agent
from mtg_bot.cards import (
    BASIC_LANDS, EOE_CREATURES, parse_mana_cost,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step


class _PickFirst(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_card_from_library(self, state, player_id, option_ids):
        return option_ids[0] if option_ids else None

    def choose_sacrifice(self, state, player_id, options):
        return options[0]


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirst()))
    state.players.append(Player(id=1, agent=_PickFirst()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def _mana_for(state, cost_str):
    cost = parse_mana_cost(cost_str)
    per_color = {"W": "Plains", "U": "Island", "B": "Swamp",
                 "R": "Mountain", "G": "Forest"}
    for color, count in cost.colored:
        for _ in range(count):
            _put(state, BASIC_LANDS[per_color[color]])
    for _ in range(cost.generic):
        _put(state, BASIC_LANDS["Plains"])


def test_activated_ability_logs_as_activated_when_resolving():
    """Honored Knight-Captain has the ``{4}{W}{W}, sac: tutor an
    Equipment`` activated ability. Activate it, drain the stack, and
    confirm the log line says 'activated' (not 'triggered')."""
    state = _new_state()
    captain = _put(state, EOE_CREATURES["Honored Knight-Captain"])
    captain.summoning_sick = False
    # Stock library with at least one Equipment to fetch.
    p = state.players[0]
    p.library.append(state.new_object(
        EOE_CREATURES["Auxiliary Boosters"], 0, Zone.LIBRARY,
    ))
    _mana_for(state, "{4}{W}{W}")
    apply_action(
        state, 0, ActivateAbility(source_id=captain.id, ability_index=0),
    )
    log_before = list(state.log)
    drain_stack(state)
    new_lines = state.log[len(log_before):]
    activated_lines = [
        line for line in new_lines if "activated ability resolves" in line
    ]
    triggered_lines = [
        line for line in new_lines if "triggered ability resolves" in line
    ]
    assert activated_lines, (
        f"expected 'activated ability resolves' line; got {new_lines}"
    )
    # The captain's activation IS what just resolved — and only ETB
    # triggers from the fetched Equipment should fire as triggered.
    assert any(
        "Honored Knight-Captain's activated ability resolves" in line
        for line in activated_lines
    )
    # Auxiliary Boosters' ETB (a triggered ability) is allowed to log
    # as triggered — that's the OTHER kind doing the right thing.
    if triggered_lines:
        assert all(
            "Auxiliary Boosters" in line for line in triggered_lines
        )


def test_triggered_ability_still_logs_as_triggered():
    """Drop a Honored Knight-Captain (its ETB creates a Soldier
    token via a TriggeredAbility). Force-fire ETB and verify the
    log uses 'triggered'."""
    from mtg_bot.actions import _trigger_etb_abilities

    state = _new_state()
    captain = _put(state, EOE_CREATURES["Honored Knight-Captain"])
    log_before = list(state.log)
    _trigger_etb_abilities(state, captain)
    drain_stack(state)
    new_lines = state.log[len(log_before):]
    triggered_lines = [
        line for line in new_lines
        if "Honored Knight-Captain's triggered ability resolves" in line
    ]
    assert triggered_lines, (
        f"expected captain's ETB to log as 'triggered'; got {new_lines}"
    )
