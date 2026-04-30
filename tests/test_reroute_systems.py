"""Tests for Reroute Systems — full two-mode oracle text.

Audit-found bug: the prior printing simplified mode 0 to "target creature
gains indestructible UEOT" (dropped the artifact branch) and dropped the
"target *tapped* creature" restriction from mode 1. This module exercises
both restored modes plus the two supporting effects
(``PumpTargetArtifactOrCreatureUntilEOT`` and
``DealDamageToTargetTappedCreature``).
"""

from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import SYNTHETIC_CREATURES, TOKEN_PRINTINGS
from mtg_bot.effects import (
    DealDamageToTargetTappedCreature,
    ModalChooseOne,
    PumpTargetArtifactOrCreatureUntilEOT,
)
from mtg_bot.game import GameState, Player, Zone, effective_keywords

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _ModeAgent(Agent):
    """Test agent that picks a fixed mode and the first legal target."""

    def __init__(self, mode_idx: int):
        self.mode_idx = mode_idx

    def choose_mode(self, state, player_id, mode_descriptions):
        return self.mode_idx

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent or RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


# -------------------------------------------------------------
# Mode 0 — Target artifact or creature gains indestructible UEOT
# -------------------------------------------------------------


def test_reroute_systems_mode_0_grants_indestructible_to_creature():
    state = _new_state(_ModeAgent(mode_idx=0))
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)

    spell = _PRINTINGS["Reroute Systems"]
    # ``Effect._enumerate_for_filter`` tags creatures as ``"creature"``
    # under the unified Pump migration; a ``"permanent"`` tag for a
    # creature would no longer appear in the chosen mode's legal-
    # targets and the modal layer would silently fizzle it.
    spell.spell_effect.resolve(state, 0, (("creature", bear.id),))

    assert "indestructible" in effective_keywords(state, bear)


def test_reroute_systems_mode_0_grants_indestructible_to_artifact():
    """The restored mode-0 branch — an artifact (Lander token) is a legal
    target. ``DestroyTargetArtifact`` should fizzle while indestructible
    is up."""
    from mtg_bot.effects import DestroyTargetArtifact

    state = _new_state(_ModeAgent(mode_idx=0))
    lander = state.new_object(
        TOKEN_PRINTINGS["Lander"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(lander)

    spell = _PRINTINGS["Reroute Systems"]
    spell.spell_effect.resolve(state, 0, (("permanent", lander.id),))

    assert "indestructible" in effective_keywords(state, lander)

    # And the keyword actually protects against destroy.
    DestroyTargetArtifact().resolve(
        state, 1, (("permanent", lander.id),),
    )
    assert lander in state.battlefield


def test_reroute_systems_mode_0_can_target_opponents_permanent():
    """No "you control" restriction — opponent's creature is a legal
    target too (matches printed oracle, which says "target artifact or
    creature" with no controller filter)."""
    state = _new_state(_ModeAgent(mode_idx=0))
    opp_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(opp_bear)

    spell = _PRINTINGS["Reroute Systems"]
    legal = spell.spell_effect.legal_targets(state, 0)
    assert ("creature", opp_bear.id) in legal

    spell.spell_effect.resolve(state, 0, (("creature", opp_bear.id),))
    assert "indestructible" in effective_keywords(state, opp_bear)


# -------------------------------------------------------------
# Mode 1 — Deals 2 damage to target tapped creature
# -------------------------------------------------------------


def test_reroute_systems_mode_1_damages_tapped_creature():
    state = _new_state(_ModeAgent(mode_idx=1))
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    bear.tapped = True
    state.battlefield.append(bear)

    spell = _PRINTINGS["Reroute Systems"]
    spell.spell_effect.resolve(state, 0, (("creature", bear.id),))

    assert bear.damage == 2


def test_reroute_systems_mode_1_untapped_creature_not_legal():
    """Mode 1's legal-targets pool is restricted to tapped creatures.
    An untapped creature must NOT appear among ``ModalChooseOne``'s
    legal targets when mode 1 is the only viable target source — the
    union here is mode 0 (any artifact/creature) UNION mode 1 (tapped
    creatures). Direct unit test on the mode-1 effect is the cleanest
    check."""
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    assert bear.tapped is False

    effect = DealDamageToTargetTappedCreature(amount=2)
    legal = effect.legal_targets(state, 0)
    assert ("creature", bear.id) not in legal


def test_reroute_systems_mode_1_fizzles_if_target_untaps_before_resolve():
    """Re-verification at resolution: if the target untapped between
    target-pick and damage application, the damage fizzles. Calling the
    effect directly (bypassing the modal-layer legality filter) is the
    cleanest way to exercise the at-resolution re-check."""
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    bear.tapped = False  # Untapped at resolve time.
    state.battlefield.append(bear)

    effect = DealDamageToTargetTappedCreature(amount=2)
    effect.resolve(state, 0, (("creature", bear.id),))

    assert bear.damage == 0
    assert any("no longer tapped" in m for m in state.log)


# -------------------------------------------------------------
# ModalChooseOne plumbing for Reroute Systems
# -------------------------------------------------------------


def test_reroute_systems_is_modal_with_two_modes():
    spell = _PRINTINGS["Reroute Systems"]
    effect = spell.spell_effect
    assert isinstance(effect, ModalChooseOne)
    assert len(effect.modes) == 2
    # Both modes are targeted, single-target — so range collapses to
    # exactly (1, 1).
    assert effect.requires_target() is True
    assert effect.target_count_range() == (1, 1)


def test_reroute_systems_legal_targets_unions_both_modes():
    """Mode 0 covers any artifact/creature; mode 1 only tapped
    creatures. The union must include the artifact (only mode 0 covers
    it) AND the tapped creature (both modes cover it)."""
    state = _new_state()
    lander = state.new_object(
        TOKEN_PRINTINGS["Lander"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(lander)
    tapped_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    tapped_bear.tapped = True
    state.battlefield.append(tapped_bear)

    spell = _PRINTINGS["Reroute Systems"]
    legal = spell.spell_effect.legal_targets(state, 0)
    assert ("permanent", lander.id) in legal
    assert ("creature", tapped_bear.id) in legal


# -------------------------------------------------------------
# Component effects — direct unit tests
# -------------------------------------------------------------


def test_pump_artifact_or_creature_legal_targets_filters_lands():
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    lander = state.new_object(
        TOKEN_PRINTINGS["Lander"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(lander)
    # A non-artifact/non-creature card in the graveyard is not on the
    # battlefield so it shouldn't appear, but verify lands wouldn't
    # appear either if they existed: easiest is to verify only the
    # artifact and creature show up.

    effect = PumpTargetArtifactOrCreatureUntilEOT(
        granted_keywords=frozenset({"indestructible"}),
    )
    legal = effect.legal_targets(state, 0)
    # Under the unified ``Pump`` migration, creatures get the
    # ``"creature"`` engine kind tag (Wild Bear) while non-creature
    # artifacts get ``"permanent"`` (Lander token).
    assert ("creature", bear.id) in legal
    assert ("permanent", lander.id) in legal
    assert len(legal) == 2


def test_pump_artifact_or_creature_no_targets_is_noop():
    state = _new_state()
    effect = PumpTargetArtifactOrCreatureUntilEOT(
        granted_keywords=frozenset({"indestructible"}),
    )
    effect.resolve(state, 0, ())
    # No crash, no log spam beyond call.


def test_pump_artifact_or_creature_wrong_kind_is_noop():
    state = _new_state()
    effect = PumpTargetArtifactOrCreatureUntilEOT(
        granted_keywords=frozenset({"indestructible"}),
    )
    effect.resolve(state, 0, (("creature", 42),))
    # No crash.


def test_pump_artifact_or_creature_missing_target_is_noop():
    state = _new_state()
    effect = PumpTargetArtifactOrCreatureUntilEOT(
        granted_keywords=frozenset({"indestructible"}),
    )
    effect.resolve(state, 0, (("permanent", 9999),))
    # No crash.


def test_pump_artifact_or_creature_with_power_bonus_describes_it():
    text = PumpTargetArtifactOrCreatureUntilEOT(
        power_bonus=1, toughness_bonus=2,
        granted_keywords=frozenset({"flying"}),
    ).describe()
    assert "+1/+2" in text
    assert "flying" in text


def test_pump_artifact_or_creature_keyword_only_describe():
    text = PumpTargetArtifactOrCreatureUntilEOT(
        granted_keywords=frozenset({"indestructible"}),
    ).describe()
    assert "indestructible" in text
    assert "artifact or creature" in text


def test_pump_artifact_or_creature_pump_only_describe():
    text = PumpTargetArtifactOrCreatureUntilEOT(
        power_bonus=2, toughness_bonus=2,
    ).describe()
    assert "+2/+2" in text


def test_deal_damage_target_tapped_creature_describe():
    text = DealDamageToTargetTappedCreature(amount=2).describe()
    assert "2" in text
    assert "tapped creature" in text


def test_deal_damage_target_tapped_creature_no_target_is_noop():
    state = _new_state()
    effect = DealDamageToTargetTappedCreature(amount=2)
    effect.resolve(state, 0, ())
    # No crash.


def test_deal_damage_target_tapped_creature_wrong_kind_is_noop():
    state = _new_state()
    effect = DealDamageToTargetTappedCreature(amount=2)
    effect.resolve(state, 0, (("permanent", 1),))
    # No crash.


def test_deal_damage_target_tapped_creature_missing_id_is_noop():
    state = _new_state()
    effect = DealDamageToTargetTappedCreature(amount=2)
    effect.resolve(state, 0, (("creature", 4242),))
    # No crash, no state change.
