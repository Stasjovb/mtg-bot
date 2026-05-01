"""Granted activated/triggered abilities on animated manlands.

Audit-found bug: Lavaclaw Reaches, Wandering Fumarole, and Raging Ravine
each grant an activated/triggered ability that fires only while the land
is animated. Pre-fix these were silently dropped. Now wired via
``BecomeLandCreatureUEOT.granted_activated_abilities`` and
``granted_triggered_abilities`` — each composes
``ApplyEffect(GrantActivatedAbility(...), EndOfTurn())`` /
``ApplyEffect(GrantTriggeredAbility(...), EndOfTurn())`` so the grant
lives on a layer-6 registry entry that expires at cleanup.
"""

from mtg_bot.actions import (
    ActivateAbility, apply_action, resolve_top_of_stack,
)
from mtg_bot.agents import Agent
from mtg_bot.cards import BASIC_LANDS, parse_mana_cost
from mtg_bot.combat import declare_attackers
from mtg_bot.effects import (
    ActivatedAbility, ActivationCost, BecomeLandCreatureUEOT,
    PumpSelfXPowerUEOT, PutPlusOneCounterOnSelf,
    SwitchSourcePowerToughnessUEOT, TriggeredAbility,
)
from mtg_bot.game import (
    GameState, Player, Zone,
    effective_activated_abilities, effective_power, effective_toughness,
)
from mtg_bot.turn import Step, run_cleanup_step

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _Agent(Agent):
    """Picks max X and the first legal target."""

    def choose_x(self, state, player_id, card_name, upper_bound):
        return upper_bound

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_Agent()))
    state.players.append(Player(id=1, agent=_Agent()))
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
        _put(state, BASIC_LANDS["Mountain"])


def _animate(state, name, cost_str):
    """Activate the manland animation and resolve the stack."""
    land = _put(state, _PRINTINGS[name])
    _mana_for(state, cost_str)
    apply_action(
        state, 0, ActivateAbility(source_id=land.id, ability_index=0),
    )
    while state.stack:
        resolve_top_of_stack(state)
    return land


# -----------------------
# Lavaclaw Reaches: {X}: gets +X/+0 UEOT (granted while animated)
# -----------------------


def test_lavaclaw_grants_x_pump_while_animated():
    state = _new_state()
    land = _animate(state, "Lavaclaw Reaches", "{1}{B}{R}")
    abilities = effective_activated_abilities(state, land)
    # Printed (animate) + granted (X-pump) = 2 abilities.
    assert len(abilities) == 2
    assert isinstance(abilities[1].effect, PumpSelfXPowerUEOT)
    assert abilities[1].cost.mana.x_pips == 1


def test_lavaclaw_x_pump_actually_pumps_power():
    state = _new_state()
    land = _animate(state, "Lavaclaw Reaches", "{1}{B}{R}")
    # Drop 3 fresh Mountains. The agent picks max X. Lavaclaw itself
    # is a land that taps for {R} (mana abilities are immune to
    # summoning sickness even while it's animated as a creature), so
    # max X = 3 + 1 (Lavaclaw) = 4.
    _mana_for(state, "{3}")
    apply_action(
        state, 0, ActivateAbility(source_id=land.id, ability_index=1),
    )
    while state.stack:
        resolve_top_of_stack(state)
    # Base 2/2 + 4 power UEOT bonus.
    assert effective_power(state, land) == 6
    assert effective_toughness(state, land) == 2


def test_lavaclaw_granted_pump_clears_at_cleanup():
    state = _new_state()
    land = _animate(state, "Lavaclaw Reaches", "{1}{B}{R}")
    pre = effective_activated_abilities(state, land)
    granted_pre = [a for a in pre if a not in land.printing.activated_abilities]
    assert len(granted_pre) == 1
    run_cleanup_step(state)
    post = effective_activated_abilities(state, land)
    granted_post = [a for a in post if a not in land.printing.activated_abilities]
    assert granted_post == []
    from mtg_bot.game import is_creature_now
    assert not is_creature_now(land)


# -----------------------
# Wandering Fumarole: {0}: switch P/T UEOT (granted while animated)
# -----------------------


def test_wandering_fumarole_grants_switch_pt_ability():
    state = _new_state()
    land = _animate(state, "Wandering Fumarole", "{2}{U}{R}")
    abilities = effective_activated_abilities(state, land)
    assert len(abilities) == 2
    assert isinstance(abilities[1].effect, SwitchSourcePowerToughnessUEOT)
    # Free cost — no mana, no tap.
    assert abilities[1].cost.mana is None


def test_wandering_fumarole_switch_actually_swaps_pt():
    state = _new_state()
    land = _animate(state, "Wandering Fumarole", "{2}{U}{R}")
    # Pre-swap: 1/4.
    assert effective_power(state, land) == 1
    assert effective_toughness(state, land) == 4
    apply_action(
        state, 0, ActivateAbility(source_id=land.id, ability_index=1),
    )
    while state.stack:
        resolve_top_of_stack(state)
    # Post-swap: 4/1.
    assert effective_power(state, land) == 4
    assert effective_toughness(state, land) == 1


def test_wandering_fumarole_swap_toggles_back():
    state = _new_state()
    land = _animate(state, "Wandering Fumarole", "{2}{U}{R}")
    for _ in range(2):
        apply_action(
            state, 0, ActivateAbility(source_id=land.id, ability_index=1),
        )
        while state.stack:
            resolve_top_of_stack(state)
    # Two swaps -> back to 1/4.
    assert effective_power(state, land) == 1
    assert effective_toughness(state, land) == 4


# -----------------------
# Raging Ravine: triggered "+1/+1 counter on attack" (granted while animated)
# -----------------------


def test_raging_ravine_grants_attacks_trigger():
    from mtg_bot.effects.predicates import (
        Event,
        IsSelf,
    )
    from mtg_bot.game import effective_triggered_abilities

    state = _new_state()
    land = _animate(state, "Raging Ravine", "{2}{R}{G}")
    granted = [
        ab for ab in effective_triggered_abilities(state, land)
        if ab not in land.printing.triggered_abilities
    ]
    assert len(granted) == 1
    trig = granted[0]
    assert trig.event == Event.ATTACKS
    assert trig.predicate == IsSelf()
    assert isinstance(trig.effect, PutPlusOneCounterOnSelf)


def test_raging_ravine_attack_puts_counter():
    from mtg_bot.actions import drain_stack

    state = _new_state()
    land = _animate(state, "Raging Ravine", "{2}{R}{G}")
    # Manlands enter as creatures fresh — they're summoning-sick on the
    # turn they animate per real MTG rules, but our minimal manland
    # smoke tests force-untap by clearing summoning_sick. Same here.
    land.summoning_sick = False
    assert land.plus_one_counters == 0
    state.step = Step.DECLARE_ATTACKERS
    declare_attackers(state, [land.id])
    drain_stack(state)
    assert land.plus_one_counters == 1
    # Effective P/T reflects the counter: base 3/3 + 1/+1 = 4/4.
    assert effective_power(state, land) == 4
    assert effective_toughness(state, land) == 4


def test_raging_ravine_trigger_clears_at_cleanup():
    from mtg_bot.game import effective_triggered_abilities

    state = _new_state()
    land = _animate(state, "Raging Ravine", "{2}{R}{G}")
    pre = [
        ab for ab in effective_triggered_abilities(state, land)
        if ab not in land.printing.triggered_abilities
    ]
    assert pre  # granted trigger present pre-cleanup
    run_cleanup_step(state)
    post = [
        ab for ab in effective_triggered_abilities(state, land)
        if ab not in land.printing.triggered_abilities
    ]
    assert post == []


# -----------------------
# Engine plumbing
# -----------------------


def test_become_land_creature_appends_granted_abilities():
    """Direct invocation of BecomeLandCreatureUEOT with both granted
    fields writes layer-6 ``grant_*`` registry entries (Phase 2)."""
    from mtg_bot.game import (
        effective_activated_abilities, effective_triggered_abilities,
    )

    state = _new_state()
    land = _put(state, BASIC_LANDS["Forest"])
    sample_act = ActivatedAbility(
        cost=ActivationCost(),
        effect=SwitchSourcePowerToughnessUEOT(),
    )
    from mtg_bot.effects.predicates import (
        Event,
        IsSelf,
    )
    sample_trig = TriggeredAbility(
        event=Event.ATTACKS, predicate=IsSelf(),
        effect=PutPlusOneCounterOnSelf(amount=1),
    )
    state.resolving_source = land
    try:
        BecomeLandCreatureUEOT(
            power=2, toughness=2,
            granted_activated_abilities=(sample_act,),
            granted_triggered_abilities=(sample_trig,),
        ).resolve(state, 0, ())
    finally:
        state.resolving_source = None
    assert sample_act in effective_activated_abilities(state, land)
    assert sample_trig in effective_triggered_abilities(state, land)
