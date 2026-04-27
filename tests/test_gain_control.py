"""Tests for gain-control-until-end-of-turn (Systems Override)."""

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import EOE_CREATURES, EOE_SPELLS, SYNTHETIC_CREATURES
from mtg_bot.effects import SystemsOverrideEffect
from mtg_bot.game import GameState, Player, Zone, effective_keywords
from mtg_bot.turn import run_cleanup_step, run_delayed_end_step_triggers


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def test_systems_override_gain_control_untap_haste():
    """Stealing an opponent's creature: control swaps, it untaps, gains haste."""
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    bear.tapped = True
    state.battlefield.append(bear)
    effect = SystemsOverrideEffect()
    effect.resolve(state, 0, (("permanent", bear.id),))
    assert bear.controller_id == 0
    assert bear.controller_id_before_any_aura_swap == 1
    assert not bear.tapped
    assert "haste" in effective_keywords(state, bear)


def test_systems_override_reverts_on_cleanup():
    state = _new_state()
    state.active_player_idx = 0
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    SystemsOverrideEffect().resolve(state, 0, (("permanent", bear.id),))
    assert bear.controller_id == 0
    run_cleanup_step(state)
    assert bear.controller_id == 1
    assert bear.controller_id_before_any_aura_swap is None
    # Haste registry grant also cleared.
    assert "haste" not in effective_keywords(state, bear)


def test_systems_override_spacecraft_charge_counters():
    """Systems Override on a Spacecraft adds 10 charge counters and
    schedules a delayed remove-10 at the next end step."""
    state = _new_state()
    state.active_player_idx = 0
    ship = state.new_object(
        EOE_CREATURES["Synthesizer Labship"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(ship)
    SystemsOverrideEffect().resolve(state, 0, (("permanent", ship.id),))
    assert ship.charge_counters == 10
    assert len(state.delayed_triggers) == 1
    entry = state.delayed_triggers[0]
    assert entry["action"] == "remove_charge_counters"
    assert entry["amount"] == 10
    # Fire the end step — counters go back to 0.
    run_delayed_end_step_triggers(state)
    assert ship.charge_counters == 0


def test_systems_override_non_spacecraft_no_counters():
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    SystemsOverrideEffect().resolve(state, 0, (("permanent", bear.id),))
    assert state.delayed_triggers == []


def test_systems_override_no_target_noop():
    state = _new_state()
    SystemsOverrideEffect().resolve(state, 0, ())


def test_systems_override_wrong_kind_noop():
    state = _new_state()
    SystemsOverrideEffect().resolve(state, 0, (("creature", 0),))


def test_systems_override_missing_target_noop():
    state = _new_state()
    SystemsOverrideEffect().resolve(state, 0, (("permanent", 999),))


def test_systems_override_describe():
    text = SystemsOverrideEffect().describe()
    assert "gain control" in text
    assert "haste" in text
    assert "ten charge counters" in text


def test_systems_override_legal_targets_include_all_artifacts_and_creatures():
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    ship = state.new_object(
        EOE_CREATURES["Synthesizer Labship"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(ship)
    legal = SystemsOverrideEffect().legal_targets(state, 0)
    ids = {t[1] for t in legal}
    assert bear.id in ids
    assert ship.id in ids


def test_systems_override_already_stolen_keeps_original_controller():
    """If the target already has a captured baseline (stolen
    earlier this turn), another Systems Override doesn't overwrite
    the baseline — we still revert to the true original owner on
    cleanup. Within layer 2 the most-recent control_change wins,
    so the second steal flips control to the new controller while
    the baseline stays at the original owner."""
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    # First steal by P0 from P1.
    SystemsOverrideEffect().resolve(state, 0, (("permanent", bear.id),))
    assert bear.controller_id_before_any_aura_swap == 1
    # Add P2.
    state.players.append(Player(id=2, agent=RandomAgent()))
    # Second steal by P2 — baseline should stay 1, not become 0.
    SystemsOverrideEffect().resolve(state, 2, (("permanent", bear.id),))
    assert bear.controller_id_before_any_aura_swap == 1
    assert bear.controller_id == 2


def test_systems_override_card_printing():
    s = EOE_SPELLS["Systems Override"]
    assert isinstance(s.spell_effect, SystemsOverrideEffect)
