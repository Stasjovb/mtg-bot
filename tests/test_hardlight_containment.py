"""Tests for Hardlight Containment: Aura that enchants artifacts."""

from mtg_bot.actions import (
    CastSpell,
    apply_action,
    resolve_top_of_stack,
)
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import (
    BASIC_LANDS,
    EOE_SPELLS,
    SYNTHETIC_CREATURES,
    TOKEN_PRINTINGS,
)
from mtg_bot.effects import ExileTargetCreatureUntilSourceLeaves
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import destroy


def _new_state_with_plains(n: int = 2):
    state = GameState()
    p0 = Player(id=0, agent=RandomAgent())
    p1 = Player(id=1, agent=RandomAgent())
    state.players.append(p0)
    state.players.append(p1)
    for _ in range(n):
        pl = state.new_object(BASIC_LANDS["Plains"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(pl)
    return state


# -----------------------
# ExileTargetCreatureUntilSourceLeaves.opponents_only
# -----------------------


def test_exile_opponents_only_restricts_legal_targets_to_opponents():
    state = _new_state_with_plains()
    mine = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(mine)
    theirs = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(theirs)
    effect = ExileTargetCreatureUntilSourceLeaves(opponents_only=True)
    legal = effect.legal_targets(state, controller_id=0)
    ids = {t[1] for t in legal}
    assert theirs.id in ids
    assert mine.id not in ids


def test_exile_without_opponents_only_includes_self_creatures():
    state = _new_state_with_plains()
    mine = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(mine)
    effect = ExileTargetCreatureUntilSourceLeaves(opponents_only=False)
    legal = effect.legal_targets(state, controller_id=0)
    assert ("creature", mine.id) in legal


# -----------------------
# Hardlight Containment full cast flow
# -----------------------


def _drain_stack(state):
    while state.stack:
        resolve_top_of_stack(state)


def test_hardlight_containment_resolves_with_artifact_target():
    state = _new_state_with_plains(n=1)
    p0 = state.players[0]
    # Give P0 an artifact to enchant.
    robot = state.new_object(TOKEN_PRINTINGS["Robot"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(robot)
    # Opponent has a creature to exile.
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    aura_card = state.new_object(
        EOE_SPELLS["Hardlight Containment"], 0, Zone.HAND,
    )
    p0.hand.append(aura_card)
    apply_action(state, 0, CastSpell(aura_card.id))
    _drain_stack(state)
    # Aura is on the battlefield attached to the robot.
    assert aura_card in state.battlefield
    assert aura_card.attached_to == robot.id
    # Opponent's bear is exiled, tagged with the aura's id.
    assert bear not in state.battlefield
    assert bear.zone == Zone.EXILE
    assert bear.exiled_by_source == aura_card.id


def test_hardlight_containment_releases_exiled_when_leaves():
    """When the Aura leaves the battlefield, the exiled creature returns."""
    state = _new_state_with_plains(n=1)
    p0 = state.players[0]
    p1 = state.players[1]
    robot = state.new_object(TOKEN_PRINTINGS["Robot"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(robot)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    aura_card = state.new_object(
        EOE_SPELLS["Hardlight Containment"], 0, Zone.HAND,
    )
    p0.hand.append(aura_card)
    apply_action(state, 0, CastSpell(aura_card.id))
    _drain_stack(state)
    assert bear not in state.battlefield

    # Destroy the enchanted robot — aura falls off and goes to graveyard.
    destroy(state, robot)
    # Bear should return (release_exiled_until_leaves).
    assert bear in state.battlefield
    assert bear.controller_id == 1
    # Aura is in graveyard.
    assert aura_card in p0.graveyard


def test_hardlight_containment_fizzles_without_artifact_target():
    """If no artifact exists at cast time, the Aura can't find a
    target and doesn't go on the stack (or fizzles at resolution)."""
    state = _new_state_with_plains(n=1)
    # No artifact to enchant.
    p0 = state.players[0]
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    aura_card = state.new_object(
        EOE_SPELLS["Hardlight Containment"], 0, Zone.HAND,
    )
    p0.hand.append(aura_card)
    apply_action(state, 0, CastSpell(aura_card.id))
    _drain_stack(state)
    # Aura fizzles to graveyard because no legal enchant target.
    assert aura_card in p0.graveyard
    # The opponent's bear wasn't exiled (ETB never fired).
    assert bear in state.battlefield


def test_hardlight_containment_aura_enchant_type_wired():
    from mtg_bot.cards import EOE_SPELLS
    p = EOE_SPELLS["Hardlight Containment"]
    assert p.is_aura
    assert p.aura_enchant_type == "artifact"
