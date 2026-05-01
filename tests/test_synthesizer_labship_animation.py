"""Synthesizer Labship's 2+ tier rider — the proper "becomes a
creature" version.

Audit-found bug: pre-fix the rider was simplified to "+2/+2 + flying
UEOT to a target artifact creature", restricting the target to
already-creature artifacts (since the engine couldn't animate non-
creature artifacts). The proper oracle reads "up to one OTHER target
artifact you control becomes an artifact creature with base P/T 2/2
and gains flying until end of turn" — applicable to non-creature
artifacts too. This file pins that fixed behavior end-to-end via the
manland animation primitives (temp_is_creature +
temp_base_pt_override + temp_keywords).
"""

from mtg_bot.actions import drain_stack
from mtg_bot.agents import Agent
from mtg_bot.cards import TOKEN_PRINTINGS
from mtg_bot.effects import TargetArtifactBecomesCreatureUEOT
from mtg_bot.game import (
    GameState, Player, Zone,
    effective_keywords, effective_power, effective_toughness,
    is_creature_now,
)
from mtg_bot.turn import Step, run_beginning_of_combat_triggers, run_cleanup_step

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _PickFirst(Agent):
    """Picks the first legal target — deterministic for the trigger."""

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirst()))
    state.players.append(Player(id=1, agent=_PickFirst()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.BEGINNING_OF_COMBAT
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


# -----------------------
# Non-creature artifact → creature
# -----------------------


def test_lander_becomes_2_2_flying_creature_ueot():
    """A Lander token is a non-creature artifact. Synthesizer
    Labship's tier-2 trigger should turn it into a 2/2 flying
    artifact creature UEOT."""
    state = _new_state()
    labship = _put(state, _PRINTINGS["Synthesizer Labship"])
    labship.charge_counters = 2
    lander = _put(state, TOKEN_PRINTINGS["Lander"])
    # Pre-state: Lander is not a creature.
    assert lander.printing.is_creature is False
    assert is_creature_now(lander) is False
    assert "flying" not in effective_keywords(state, lander)

    run_beginning_of_combat_triggers(state)
    drain_stack(state)

    # Post-state: Lander is now a 2/2 flying creature UEOT.
    assert is_creature_now(lander)
    assert effective_power(state, lander) == 2
    assert effective_toughness(state, lander) == 2
    assert "flying" in effective_keywords(state, lander)


def test_animation_clears_at_cleanup():
    state = _new_state()
    labship = _put(state, _PRINTINGS["Synthesizer Labship"])
    labship.charge_counters = 2
    lander = _put(state, TOKEN_PRINTINGS["Lander"])
    run_beginning_of_combat_triggers(state)
    drain_stack(state)
    assert is_creature_now(lander)

    run_cleanup_step(state)
    assert not is_creature_now(lander)
    assert "flying" not in effective_keywords(state, lander)


# -----------------------
# Already-creature artifact: base P/T overridden (can shrink)
# -----------------------


def test_already_creature_artifact_base_pt_overridden():
    """A stationed Spacecraft (artifact creature with high P/T) targeted
    by Labship's rider has its base P/T set to 2/2 — a shrink, matching
    oracle. This is the layered-effects part the simplified version
    couldn't model."""
    state = _new_state()
    labship = _put(state, _PRINTINGS["Synthesizer Labship"])
    labship.charge_counters = 2
    # Drop another stationed Spacecraft as the target. Sledge-Class
    # Seedship is a 4/5 Spacecraft; station it at 7+ so it's an
    # artifact creature.
    other_sc = _put(state, _PRINTINGS["Sledge-Class Seedship"])
    other_sc.charge_counters = 7  # stationed → creature mode
    assert is_creature_now(other_sc)
    assert effective_power(state, other_sc) == 4
    assert effective_toughness(state, other_sc) == 5

    run_beginning_of_combat_triggers(state)
    drain_stack(state)

    # Base P/T overridden to 2/2 — the shrink is real.
    assert effective_power(state, other_sc) == 2
    assert effective_toughness(state, other_sc) == 2
    assert "flying" in effective_keywords(state, other_sc)


# -----------------------
# Below-threshold: no animation
# -----------------------


def test_below_tier_threshold_no_animation():
    state = _new_state()
    labship = _put(state, _PRINTINGS["Synthesizer Labship"])
    labship.charge_counters = 1  # below the 2+ tier
    lander = _put(state, TOKEN_PRINTINGS["Lander"])

    run_beginning_of_combat_triggers(state)
    drain_stack(state)

    assert not is_creature_now(lander)
    assert "flying" not in effective_keywords(state, lander)


# -----------------------
# Self-exclusion (regression)
# -----------------------


def test_labship_cannot_target_itself():
    """Labship's stationed-creature mode (9+ counters) makes it an
    artifact creature, but the rider says "OTHER target artifact" — so
    legal_targets must exclude self. With no other artifact on the
    battlefield, legal_targets returns empty."""
    state = _new_state()
    labship = _put(state, _PRINTINGS["Synthesizer Labship"])
    labship.charge_counters = 9  # stationed; tier 2+ active
    effect = TargetArtifactBecomesCreatureUEOT(
        power=2, toughness=2, granted_keywords=frozenset({"flying"}),
    )
    state.resolving_source = labship
    try:
        legal = effect.legal_targets(state, 0)
    finally:
        state.resolving_source = None
    assert legal == []
