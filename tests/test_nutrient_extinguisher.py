"""Tests for Nutrient Block + Extinguisher Battleship restorations."""

from mtg_bot.actions import (
    ActivateAbility,
    apply_action,
    drain_stack,
    put_into_battlefield,
    resolve_top_of_stack,
)
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.effects import DestroyTargetNoncreaturePermanent
from mtg_bot.game import GameState, Player, Zone, effective_keywords
from mtg_bot.turn import Step, destroy, sacrifice

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent or _PickFirstAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


# -----------------------
# Nutrient Block
# -----------------------


def test_nutrient_block_has_indestructible():
    state = _new_state()
    nb = state.new_object(
        _PRINTINGS["Nutrient Block"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(nb)
    kws = effective_keywords(state, nb)
    assert "indestructible" in kws


def test_nutrient_block_activation_gains_life_and_sacs():
    state = _new_state(_PickFirstAgent())
    state.step = Step.PRECOMBAT_MAIN
    p = state.players[0]
    nb = state.new_object(
        _PRINTINGS["Nutrient Block"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(nb)
    for _ in range(2):
        l = state.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(l)
    apply_action(state, 0, ActivateAbility(source_id=nb.id, ability_index=0))
    resolve_top_of_stack(state)
    assert p.life == 23
    # Sacrificed → graveyard.
    assert nb not in state.battlefield
    assert nb in p.graveyard


def test_nutrient_block_draws_on_leave_battlefield():
    """Sacrifice (or destroy) triggers leaves_battlefield → draw."""
    state = _new_state()
    p = state.players[0]
    nb = state.new_object(
        _PRINTINGS["Nutrient Block"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(nb)
    drawn = state.new_object(BASIC_LANDS["Forest"], 0, Zone.LIBRARY)
    p.library.append(drawn)
    sacrifice(state, nb)
    drain_stack(state)
    assert drawn in p.hand


def test_nutrient_block_destroy_fizzles_due_to_indestructible():
    state = _new_state()
    nb = state.new_object(
        _PRINTINGS["Nutrient Block"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(nb)
    result = destroy(state, nb)
    assert result is False
    assert nb in state.battlefield


# -----------------------
# Extinguisher Battleship
# -----------------------


def test_extinguisher_etb_destroys_noncreature_and_damages_each_creature():
    state = _new_state(_PickFirstAgent())
    p = state.players[0]
    # Opponent has a non-creature artifact and a creature.
    p1 = state.players[1]
    artifact = state.new_object(
        _PRINTINGS["Memorial Vault"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(artifact)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    # Put Extinguisher Battleship into play (triggering ETB).
    ship = state.new_object(
        _PRINTINGS["Extinguisher Battleship"], 0, Zone.HAND,
    )
    put_into_battlefield(state, ship, controller_id=0)
    # Resolve ETB trigger (the stack has it).
    while state.stack:
        resolve_top_of_stack(state)
    # Artifact destroyed.
    assert artifact not in state.battlefield
    # Bear took 4 damage.
    assert bear.damage == 4


def test_extinguisher_station_threshold_is_five():
    ship = _PRINTINGS["Extinguisher Battleship"]
    assert ship.station_threshold == 5


def test_destroy_target_noncreature_permanent_happy_path():
    state = _new_state()
    land = state.new_object(BASIC_LANDS["Forest"], 1, Zone.BATTLEFIELD)
    state.battlefield.append(land)
    DestroyTargetNoncreaturePermanent().resolve(
        state, 0, (("permanent", land.id),),
    )
    assert land not in state.battlefield


def test_destroy_target_noncreature_permanent_no_target_noop():
    state = _new_state()
    DestroyTargetNoncreaturePermanent().resolve(state, 0, ())


def test_destroy_target_noncreature_permanent_wrong_kind_noop():
    state = _new_state()
    DestroyTargetNoncreaturePermanent().resolve(state, 0, (("creature", 99),))


def test_destroy_target_noncreature_permanent_missing_obj_noop():
    state = _new_state()
    DestroyTargetNoncreaturePermanent().resolve(state, 0, (("permanent", 999),))


def test_destroy_target_noncreature_permanent_refuses_creatures():
    """The effect's legal targets exclude creatures; if somehow passed
    a creature id, it silently refuses to destroy."""
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    DestroyTargetNoncreaturePermanent().resolve(
        state, 0, (("permanent", bear.id),),
    )
    assert bear in state.battlefield


def test_destroy_target_noncreature_legal_targets_excludes_creatures():
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    land = state.new_object(BASIC_LANDS["Forest"], 1, Zone.BATTLEFIELD)
    state.battlefield.append(land)
    legal = DestroyTargetNoncreaturePermanent().legal_targets(state, 0)
    ids = {t[1] for t in legal}
    assert bear.id not in ids
    assert land.id in ids


def test_destroy_target_noncreature_describe():
    assert "noncreature" in DestroyTargetNoncreaturePermanent().describe()
