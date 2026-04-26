"""Tests for Syr Vondam, Sunstar Exemplar — another-creature-dies-or-exiled
observer trigger, the new ConditionalIfSourcePowerAtLeast effect, and
leaves-battlefield self-trigger gated on power."""

from mtg_bot.actions import drain_stack
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import EOE_CREATURES, SYNTHETIC_CREATURES
from mtg_bot.effects import (
    ConditionalIfSourcePowerAtLeast,
    DestroyTargetNonlandPermanent,
    DrawCards,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import destroy, move_off_battlefield


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent or _PickFirstAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


# -----------------------
# ConditionalIfSourcePowerAtLeast effect
# -----------------------


def test_conditional_power_gate_runs_when_power_meets_threshold():
    state = _new_state()
    src = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    src.plus_one_counters = 3  # 2 + 3 = 5 effective power
    state.battlefield.append(src)
    state.resolving_source = src
    p0 = state.players[0]
    for _ in range(2):
        c = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.LIBRARY)
        p0.library.append(c)
    try:
        ConditionalIfSourcePowerAtLeast(
            effect=DrawCards(amount=1), threshold=4,
        ).resolve(state, 0, ())
    finally:
        state.resolving_source = None
    assert len(p0.hand) == 1


def test_conditional_power_gate_skips_when_below_threshold():
    state = _new_state()
    src = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    # Wild Bear base power 2, no counters.
    state.battlefield.append(src)
    state.resolving_source = src
    p0 = state.players[0]
    c = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.LIBRARY)
    p0.library.append(c)
    try:
        ConditionalIfSourcePowerAtLeast(
            effect=DrawCards(amount=1), threshold=4,
        ).resolve(state, 0, ())
    finally:
        state.resolving_source = None
    assert len(p0.hand) == 0


def test_conditional_power_gate_no_source_is_noop():
    state = _new_state()
    # resolving_source is None — should log-and-return without crashing.
    ConditionalIfSourcePowerAtLeast(
        effect=DrawCards(amount=1), threshold=4,
    ).resolve(state, 0, ())


def test_conditional_power_gate_forwards_target_requirements():
    inner = DestroyTargetNonlandPermanent()
    gate = ConditionalIfSourcePowerAtLeast(effect=inner, threshold=4)
    assert gate.requires_target() is inner.requires_target()
    assert "4" in gate.describe() and "greater" in gate.describe()


# -----------------------
# Observer trigger: another creature dies
# -----------------------


def test_vondam_counts_allied_creature_dying():
    state = _new_state()
    vondam = state.new_object(
        EOE_CREATURES["Syr Vondam, Sunstar Exemplar"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(vondam)
    ally = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(ally)
    life_before = state.players[0].life
    destroy(state, ally)
    drain_stack(state)
    assert vondam.plus_one_counters == 1
    assert state.players[0].life == life_before + 1


def test_vondam_counts_allied_creature_exiled():
    state = _new_state()
    vondam = state.new_object(
        EOE_CREATURES["Syr Vondam, Sunstar Exemplar"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(vondam)
    ally = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(ally)
    life_before = state.players[0].life
    move_off_battlefield(state, ally, destination="exile")
    drain_stack(state)
    assert vondam.plus_one_counters == 1
    assert state.players[0].life == life_before + 1


def test_vondam_ignores_opponents_creature_dying():
    state = _new_state()
    vondam = state.new_object(
        EOE_CREATURES["Syr Vondam, Sunstar Exemplar"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(vondam)
    enemy = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(enemy)
    destroy(state, enemy)
    assert vondam.plus_one_counters == 0


def test_vondam_does_not_fire_on_own_death():
    state = _new_state()
    vondam = state.new_object(
        EOE_CREATURES["Syr Vondam, Sunstar Exemplar"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(vondam)
    destroy(state, vondam)
    # The "another" qualifier excludes self — no counter should land.
    assert vondam.plus_one_counters == 0


# -----------------------
# Self trigger: leaves-battlefield + power threshold
# -----------------------


def test_vondam_death_at_power_4_destroys_target_permanent():
    state = _new_state(_PickFirstAgent())
    vondam = state.new_object(
        EOE_CREATURES["Syr Vondam, Sunstar Exemplar"], 0, Zone.BATTLEFIELD,
    )
    vondam.plus_one_counters = 2  # 2 + 2 = 4 effective power
    state.battlefield.append(vondam)
    enemy = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(enemy)
    destroy(state, vondam)
    drain_stack(state)
    # Enemy bear should be gone (destroyed by Vondam's leaves trigger).
    assert enemy not in state.battlefield


def test_vondam_death_below_power_4_does_nothing():
    state = _new_state(_PickFirstAgent())
    vondam = state.new_object(
        EOE_CREATURES["Syr Vondam, Sunstar Exemplar"], 0, Zone.BATTLEFIELD,
    )
    # Base 2/2, no counters — power is 2, below threshold.
    state.battlefield.append(vondam)
    enemy = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(enemy)
    destroy(state, vondam)
    assert enemy in state.battlefield


def test_vondam_printing_metadata():
    v = EOE_CREATURES["Syr Vondam, Sunstar Exemplar"]
    triggers = {ab.trigger for ab in v.triggered_abilities}
    assert "another_creature_you_control_dies_or_exiled" in triggers
    assert "leaves_battlefield" in triggers
    assert "vigilance" in v.keywords
    assert "menace" in v.keywords
