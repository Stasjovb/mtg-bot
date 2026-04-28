"""Tests for Drill Too Deep — full two-mode oracle text.

Audit-found bug: the prior printing shipped only a Spacecraft-only
charge-counter mode plus destroy-target-artifact, with a comment
silently dropping the Planet half of the first mode. The Planet land
subtype IS modeled in this codebase (see ``make_planet_land``), so
restoring the full text just required generalizing the targeting filter
to ``Spacecraft or Planet you control``.

Covers:
- Mode 0 with a Spacecraft target.
- Mode 0 with a Planet land target.
- Mode 0 fizzling on an opponent-controlled Spacecraft.
- Mode 1 destroys an artifact.
- Modal target_count_range and legal_targets union.
- Effect-level no-op safety paths for the new effect class.
"""

from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import PLANET_LANDS, SYNTHETIC_CREATURES
from mtg_bot.cards.base import make_artifact, make_spacecraft
from mtg_bot.effects import (
    DestroyTargetArtifact,
    ModalChooseOne,
    PutChargeCountersOnTargetSpacecraftOrPlanetYouControl,
)
from mtg_bot.game import GameState, Player, Zone

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


_SPACECRAFT_PRINTING = make_spacecraft(
    "Test Spacecraft", "{2}",
    power=2, toughness=2, station_threshold=3,
)
_OTHER_ARTIFACT = make_artifact("Test Artifact", "{1}")


# -------------------------------------------------------------
# Mode 0 — five charge counters on a Spacecraft or Planet you control
# -------------------------------------------------------------


def test_drill_too_deep_mode_0_charges_spacecraft():
    state = _new_state(_ModeAgent(mode_idx=0))
    ship = state.new_object(_SPACECRAFT_PRINTING, 0, Zone.BATTLEFIELD)
    state.battlefield.append(ship)

    spell = _PRINTINGS["Drill Too Deep"]
    spell.spell_effect.resolve(state, 0, (("permanent", ship.id),))

    assert ship.charge_counters == 5


def test_drill_too_deep_mode_0_charges_planet_land():
    """Planet half of mode 0 — the bit the prior impl silently dropped.
    Planet is a Land subtype produced by ``make_planet_land``."""
    state = _new_state(_ModeAgent(mode_idx=0))
    planet = state.new_object(
        PLANET_LANDS["Adagia, Windswept Bastion"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(planet)
    assert "Planet" in planet.printing.subtypes

    spell = _PRINTINGS["Drill Too Deep"]
    spell.spell_effect.resolve(state, 0, (("permanent", planet.id),))

    assert planet.charge_counters == 5


def test_drill_too_deep_mode_0_legal_targets_excludes_opponent_permanents():
    """'You control' filter — opponent Spacecraft and Planet are not
    legal targets for mode 0."""
    state = _new_state()
    own_ship = state.new_object(_SPACECRAFT_PRINTING, 0, Zone.BATTLEFIELD)
    state.battlefield.append(own_ship)
    opp_ship = state.new_object(_SPACECRAFT_PRINTING, 1, Zone.BATTLEFIELD)
    state.battlefield.append(opp_ship)
    opp_planet = state.new_object(
        PLANET_LANDS["Adagia, Windswept Bastion"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(opp_planet)

    effect = PutChargeCountersOnTargetSpacecraftOrPlanetYouControl(amount=5)
    legal = effect.legal_targets(state, 0)
    assert ("permanent", own_ship.id) in legal
    assert ("permanent", opp_ship.id) not in legal
    assert ("permanent", opp_planet.id) not in legal


def test_drill_too_deep_mode_0_resolve_skips_opponent_permanent():
    """Even if a malformed target tuple sneaks through, resolve() must
    not pump an opponent's Planet."""
    state = _new_state()
    opp_planet = state.new_object(
        PLANET_LANDS["Adagia, Windswept Bastion"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(opp_planet)

    effect = PutChargeCountersOnTargetSpacecraftOrPlanetYouControl(amount=5)
    effect.resolve(state, 0, (("permanent", opp_planet.id),))
    assert opp_planet.charge_counters == 0


# -------------------------------------------------------------
# Mode 1 — Destroy target artifact
# -------------------------------------------------------------


def test_drill_too_deep_mode_1_destroys_artifact():
    state = _new_state(_ModeAgent(mode_idx=1))
    art = state.new_object(_OTHER_ARTIFACT, 1, Zone.BATTLEFIELD)
    state.battlefield.append(art)

    spell = _PRINTINGS["Drill Too Deep"]
    spell.spell_effect.resolve(state, 0, (("permanent", art.id),))

    assert art not in state.battlefield


# -------------------------------------------------------------
# ModalChooseOne plumbing
# -------------------------------------------------------------


def test_drill_too_deep_modal_target_count_range_is_one_to_one():
    spell = _PRINTINGS["Drill Too Deep"]
    effect = spell.spell_effect
    assert isinstance(effect, ModalChooseOne)
    assert effect.requires_target() is True
    # Both modes need exactly one target.
    assert effect.target_count_range() == (1, 1)


def test_drill_too_deep_modal_legal_targets_unions_both_pools():
    """ModalChooseOne.legal_targets returns the union across modes:
    own Spacecraft/Planet (mode 0) plus any artifact (mode 1)."""
    state = _new_state()
    own_ship = state.new_object(_SPACECRAFT_PRINTING, 0, Zone.BATTLEFIELD)
    state.battlefield.append(own_ship)
    own_planet = state.new_object(
        PLANET_LANDS["Adagia, Windswept Bastion"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(own_planet)
    opp_art = state.new_object(_OTHER_ARTIFACT, 1, Zone.BATTLEFIELD)
    state.battlefield.append(opp_art)

    spell = _PRINTINGS["Drill Too Deep"]
    legal = spell.spell_effect.legal_targets(state, 0)
    # Mode 0: own ship + own planet. Mode 1: any artifact (own ship is
    # an artifact too — Spacecraft is an artifact subtype).
    assert ("permanent", own_ship.id) in legal
    assert ("permanent", own_planet.id) in legal
    assert ("permanent", opp_art.id) in legal


# -------------------------------------------------------------
# Effect-class safety paths
# -------------------------------------------------------------


def test_charge_counters_spacecraft_or_planet_describe_mentions_planet():
    text = PutChargeCountersOnTargetSpacecraftOrPlanetYouControl(
        amount=5
    ).describe()
    assert "Spacecraft" in text
    assert "Planet" in text
    assert "5" in text


def test_charge_counters_spacecraft_or_planet_no_target_is_noop():
    state = _new_state()
    effect = PutChargeCountersOnTargetSpacecraftOrPlanetYouControl(amount=5)
    effect.resolve(state, 0, ())
    # No crash; nothing on the battlefield to mutate.


def test_charge_counters_spacecraft_or_planet_wrong_kind_is_noop():
    state = _new_state()
    effect = PutChargeCountersOnTargetSpacecraftOrPlanetYouControl(amount=5)
    effect.resolve(state, 0, (("creature", 1),))


def test_charge_counters_spacecraft_or_planet_missing_id_is_noop():
    state = _new_state()
    effect = PutChargeCountersOnTargetSpacecraftOrPlanetYouControl(amount=5)
    effect.resolve(state, 0, (("permanent", 99999),))


def test_charge_counters_spacecraft_or_planet_skips_non_qualifying():
    """A creature isn't a Spacecraft and isn't a Planet — resolve should
    silently no-op rather than charge it."""
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    effect = PutChargeCountersOnTargetSpacecraftOrPlanetYouControl(amount=5)
    effect.resolve(state, 0, (("permanent", bear.id),))
    assert bear.charge_counters == 0
