"""Tests for Lithobraking: create Lander + may-sac artifact → damage each creature."""

from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES, TOKEN_PRINTINGS
from mtg_bot.effects import (
    DealNDamageToEachCreature,
    OptionalSacArtifactForEffect,
)
from mtg_bot.game import GameState, Player, Zone

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _PickFirstAgent(Agent):
    def choose_sacrifice(self, state, player_id, legal_object_ids):
        return legal_object_ids[0]


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent or RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def test_deal_damage_to_each_creature_hits_every_creature():
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    opp = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(opp)
    DealNDamageToEachCreature(amount=2).resolve(state, 0, ())
    assert bear.damage == 2
    assert opp.damage == 2


def test_deal_damage_to_each_creature_skips_non_creatures():
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    land = state.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(land)
    DealNDamageToEachCreature(amount=2).resolve(state, 0, ())
    assert bear.damage == 2
    assert land.damage == 0


def test_optional_sac_artifact_runs_inner_when_artifact_exists():
    state = _new_state(_PickFirstAgent())
    artifact = state.new_object(
        TOKEN_PRINTINGS["Lander"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(artifact)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    effect = OptionalSacArtifactForEffect(
        inner_effect=DealNDamageToEachCreature(amount=2),
    )
    effect.resolve(state, 0, ())
    assert artifact not in state.battlefield
    assert bear.damage == 2


def test_optional_sac_artifact_noop_when_no_artifact():
    state = _new_state(_PickFirstAgent())
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    effect = OptionalSacArtifactForEffect(
        inner_effect=DealNDamageToEachCreature(amount=2),
    )
    effect.resolve(state, 0, ())
    # No artifact to sac → inner effect not run.
    assert bear.damage == 0


def test_optional_sac_artifact_describe():
    effect = OptionalSacArtifactForEffect(
        inner_effect=DealNDamageToEachCreature(amount=2),
    )
    text = effect.describe()
    assert "sacrifice an artifact" in text


def test_deal_damage_to_each_creature_describe():
    text = DealNDamageToEachCreature(amount=3).describe()
    assert "3 damage" in text


def test_lithobraking_card_full_flow():
    """End-to-end: Lithobraking resolves, creates Lander, sacrifices it
    (RandomAgent picks the Lander since it's the only artifact), deals
    2 damage to each creature."""
    state = _new_state(_PickFirstAgent())
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    lithobraking = _PRINTINGS["Lithobraking"]
    lithobraking.spell_effect.resolve(state, 0, ())
    # Bear took 2 damage.
    assert bear.damage == 2
    # Lander was created then sacrificed immediately.
    landers_on_bf = [
        o for o in state.battlefield
        if o.printing.name == "Lander" and o.controller_id == 0
    ]
    assert landers_on_bf == []


def test_optional_sac_artifact_no_agent_defaults_to_first():
    state = GameState()
    state.players.append(Player(id=0, agent=None))
    state.players.append(Player(id=1, agent=RandomAgent()))
    artifact = state.new_object(
        TOKEN_PRINTINGS["Lander"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(artifact)
    effect = OptionalSacArtifactForEffect(
        inner_effect=DealNDamageToEachCreature(amount=1),
    )
    effect.resolve(state, 0, ())
    assert artifact not in state.battlefield


# -----------------------
# choose_yes_no honored: "may" decision really gates the rider
# -----------------------


class _NoSacAgent(Agent):
    """Declines every yes/no decision."""

    def choose_yes_no(self, state, player_id, prompt):
        return False

    def choose_sacrifice(self, state, player_id, legal_object_ids):
        return legal_object_ids[0]


def test_optional_sac_artifact_honors_no_yes_no_decline():
    """Oracle: 'You may sacrifice an artifact.' The 'may' is real —
    when the controller's agent says no, the artifact stays and the
    inner effect doesn't fire."""
    state = _new_state(_NoSacAgent())
    artifact = state.new_object(
        TOKEN_PRINTINGS["Lander"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(artifact)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    effect = OptionalSacArtifactForEffect(
        inner_effect=DealNDamageToEachCreature(amount=2),
    )
    effect.resolve(state, 0, ())
    # Artifact intact, no damage dealt.
    assert artifact in state.battlefield
    assert bear.damage == 0


def test_lithobraking_decline_keeps_lander_and_skips_damage():
    """End-to-end: declining the optional sac on Lithobraking leaves
    the Lander (the just-created token) on the battlefield AND skips
    the deals-2-damage rider."""
    state = _new_state(_NoSacAgent())
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    lithobraking = _PRINTINGS["Lithobraking"]
    lithobraking.spell_effect.resolve(state, 0, ())
    # Bear is undamaged.
    assert bear.damage == 0
    # The Lander created by the first half of the spell stuck around.
    landers_on_bf = [
        o for o in state.battlefield
        if o.printing.name == "Lander" and o.controller_id == 0
    ]
    assert len(landers_on_bf) == 1
