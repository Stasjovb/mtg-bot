"""Tests for EoE Spacecraft tiered triggered abilities.

Tier gating works off charge counters on the source: an ability with
``tier_threshold=N`` only fires when the source has at least N counters.
This mirrors ``StaticAbility.tier_threshold`` but for triggered abilities.
"""

from mtg_bot.actions import CastSpell, apply_action, drain_stack, resolve_top_of_stack
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import (
    BASIC_LANDS,
    EOE_CREATURES,
    EOE_SPELLS,
    SYNTHETIC_CREATURES,
    TOKEN_PRINTINGS,
)
from mtg_bot.combat import declare_attackers
from mtg_bot.effects import (
    DealDamageToTargetCreature,
    TargetArtifactBecomesCreatureUEOT,
    TriggeredAbility,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import (
    run_beginning_of_combat_triggers,
    should_fire_trigger,
)


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def test_triggered_ability_defaults_tier_threshold_to_zero():
    ab = TriggeredAbility(trigger="etb", effect=None)
    assert ab.tier_threshold == 0


def test_should_fire_trigger_respects_tier_threshold():
    """An ability with tier_threshold=3 fires only once the source has
    3+ charge counters."""
    state = _new_state()
    # Build a spacecraft-like object with 2 counters and a tier-3 ability.
    sc = state.new_object(
        EOE_CREATURES["Synthesizer Labship"], 0, Zone.BATTLEFIELD,
    )
    sc.charge_counters = 1  # below the 2+ tier
    state.battlefield.append(sc)
    # Pull the actual tiered ability off the printing.
    ability = sc.printing.triggered_abilities[0]
    assert ability.tier_threshold == 2
    assert should_fire_trigger(state, sc.id, 0, ability) is False
    sc.charge_counters = 2
    assert should_fire_trigger(state, sc.id, 0, ability) is True


def test_should_fire_trigger_no_source_returns_false():
    """Defensive: if the source id isn't on the battlefield, the tiered
    trigger doesn't fire."""
    state = _new_state()
    ability = TriggeredAbility(
        trigger="etb", effect=None, tier_threshold=5,
    )
    assert should_fire_trigger(state, source_id=999, ability_index=0, ability=ability) is False


def test_synthesizer_labship_combat_trigger_only_at_tier_2():
    """Synthesizer Labship's beginning-of-combat trigger is gated at 2+
    counters. Below threshold: no effect. At or above: target artifact
    becomes a 2/2 creature with flying UEOT (overriding base P/T)."""
    state = _new_state()
    state.active_player_idx = 0
    labship = state.new_object(
        EOE_CREATURES["Synthesizer Labship"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(labship)
    # Target artifact creature: use a Robot token (artifact creature).
    robot = state.new_object(
        TOKEN_PRINTINGS["Robot"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(robot)

    # Below threshold: no effect.
    labship.charge_counters = 1
    run_beginning_of_combat_triggers(state)
    drain_stack(state)
    assert robot.temp_base_pt_override is None
    assert "flying" not in robot.temp_keywords

    # At threshold: rider applies.
    labship.charge_counters = 2
    run_beginning_of_combat_triggers(state)
    drain_stack(state)
    assert robot.temp_is_creature is True
    assert robot.temp_base_pt_override == (2, 2)
    assert "flying" in robot.temp_keywords


def test_synthesizer_labship_excludes_self_from_targets():
    """The effect targets OTHER artifact permanents — Labship can't
    buff itself even once it's stationed into creature mode."""
    state = _new_state()
    state.active_player_idx = 0
    labship = state.new_object(
        EOE_CREATURES["Synthesizer Labship"], 0, Zone.BATTLEFIELD,
    )
    labship.charge_counters = 9  # stationed → is a creature + tier 2+ active
    state.battlefield.append(labship)
    # No other artifact permanents on the battlefield.
    effect = TargetArtifactBecomesCreatureUEOT(
        power=2, toughness=2,
        granted_keywords=frozenset({"flying"}),
    )
    state.resolving_source = labship
    try:
        legal = effect.legal_targets(state, 0)
    finally:
        state.resolving_source = None
    # Labship is an artifact (and a creature once stationed) but
    # self-targeting is disallowed → empty.
    assert legal == []


def test_synthesizer_labship_legal_target_excludes_opponent_artifacts():
    state = _new_state()
    labship = state.new_object(
        EOE_CREATURES["Synthesizer Labship"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(labship)
    # Opponent's Robot token — not legal.
    opp_robot = state.new_object(
        TOKEN_PRINTINGS["Robot"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(opp_robot)
    # Our Robot token — legal.
    my_robot = state.new_object(
        TOKEN_PRINTINGS["Robot"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(my_robot)
    effect = TargetArtifactBecomesCreatureUEOT(
        power=2, toughness=2,
        granted_keywords=frozenset({"flying"}),
    )
    state.resolving_source = labship
    try:
        legal = effect.legal_targets(state, 0)
    finally:
        state.resolving_source = None
    assert legal == [("permanent", my_robot.id)]


def test_target_artifact_becomes_creature_resolve_no_targets_noop():
    effect = TargetArtifactBecomesCreatureUEOT(
        power=2, toughness=2,
        granted_keywords=frozenset({"flying"}),
    )
    state = _new_state()
    # No crash, no battlefield mutation.
    effect.resolve(state, 0, ())


def test_target_artifact_becomes_creature_resolve_bad_kind_noop():
    """Defensive: resolving with a non-permanent kind is a silent no-op."""
    effect = TargetArtifactBecomesCreatureUEOT(power=1, toughness=1)
    state = _new_state()
    effect.resolve(state, 0, (("player", 0),))


def test_target_artifact_becomes_creature_resolve_missing_object_noop():
    """Defensive: target id not on battlefield is a silent no-op."""
    effect = TargetArtifactBecomesCreatureUEOT(power=1, toughness=1)
    state = _new_state()
    effect.resolve(state, 0, (("permanent", 999),))


def test_target_artifact_becomes_creature_describe():
    text = TargetArtifactBecomesCreatureUEOT(
        power=2, toughness=2,
        granted_keywords=frozenset({"flying"}),
    ).describe()
    assert "becomes" in text
    assert "2/2" in text
    assert "flying" in text
    text_no_kw = TargetArtifactBecomesCreatureUEOT(
        power=1, toughness=1,
    ).describe()
    assert "1/1" in text_no_kw


def test_dawnsire_attacks_trigger_only_at_tier_10():
    """Dawnsire's 10+ attacks trigger deals 100 damage to a target
    creature once it's at or above 10 charge counters."""
    state = _new_state()
    state.active_player_idx = 0
    dawnsire = state.new_object(
        EOE_SPELLS["Dawnsire, Sunstar Dreadnought"], 0, Zone.BATTLEFIELD,
    )
    dawnsire.charge_counters = 20  # stationed — is a creature
    dawnsire.summoning_sick = False
    state.battlefield.append(dawnsire)
    victim = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(victim)
    # First: tier below 10 (unusual since stationed is 20, but to isolate
    # the gate, set counters to 9 temporarily).
    dawnsire.charge_counters = 9
    declare_attackers(state, [dawnsire.id])
    drain_stack(state)
    # At 9 counters, the 10+ trigger shouldn't fire — victim untouched.
    assert victim.damage == 0
    assert victim in state.battlefield
    # Reset for the next attack.
    dawnsire.attacking = False
    # Clean up any damage marked on dawnsire from the first pass.
    dawnsire.damage = 0
    # At 10+: trigger fires, victim takes 100 damage (lethal); SBAs then
    # destroy the victim.
    dawnsire.charge_counters = 10
    declare_attackers(state, [dawnsire.id])
    drain_stack(state)
    assert victim not in state.battlefield
    assert victim in state.players[1].graveyard


def test_tier_threshold_attacks_fires_when_source_exactly_at_threshold():
    """Dawnsire with exactly 10 counters triggers — ≥ is correct."""
    state = _new_state()
    state.active_player_idx = 0
    dawnsire = state.new_object(
        EOE_SPELLS["Dawnsire, Sunstar Dreadnought"], 0, Zone.BATTLEFIELD,
    )
    dawnsire.charge_counters = 10
    dawnsire.summoning_sick = False
    state.battlefield.append(dawnsire)
    victim = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(victim)
    declare_attackers(state, [dawnsire.id])
    drain_stack(state)
    # 100 damage is lethal; SBAs immediately destroy the victim.
    assert victim not in state.battlefield
    assert victim in state.players[1].graveyard
