"""Card-level test pinning Swarmyard's regenerate target filter to
Skystinger — the in-pool Insect Warrior that the leading comment in
``stellar_sights.py`` once incorrectly described as having no legal
target in the EoE pool.

Covers:

1. ``RegenerateTargetCreature`` accepts Skystinger as a legal target
   on the battlefield, and rejects creatures whose subtypes do not
   intersect ``allowed_subtypes``.
2. End-to-end activation: with a Skystinger on the battlefield about
   to die from lethal damage, activating Swarmyard's regenerate
   ability puts a regeneration shield on Skystinger, and the
   following state-based-actions pass replaces the destruction with
   the regenerate replacement (damage cleared, tap, removed from
   combat, shield consumed).
3. The filter rejects a creature whose subtypes are disjoint with the
   allowed set even if it is otherwise a valid creature on the
   battlefield.
"""

from mtg_bot.actions import (
    ActivateAbility, apply_action, resolve_top_of_stack,
)
from mtg_bot.agents import Agent
from mtg_bot.cards import BASIC_LANDS, STELLAR_SIGHTS_LANDS
from mtg_bot.cards.base import make_creature
from mtg_bot.cards.eoe_creatures import EOE_CREATURES
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step, state_based_actions


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def test_skystinger_has_insect_subtype():
    """Sanity check: Skystinger's printing carries the Insect subtype.
    If this regresses, the rest of the file is meaningless."""
    sky = EOE_CREATURES["Skystinger"]
    assert "Insect" in sky.subtypes


def test_swarmyard_filter_accepts_skystinger():
    """Swarmyard's regenerate ability lists Skystinger as a legal
    target via its allowed_subtypes filter (Insect ∈ {Rat, Spider,
    Squirrel, Insect, Snake})."""
    state = _new_state()
    _put(state, STELLAR_SIGHTS_LANDS["Swarmyard"])
    sky = _put(state, EOE_CREATURES["Skystinger"])

    eff = STELLAR_SIGHTS_LANDS[
        "Swarmyard"
    ].activated_abilities[0].effect
    legal = eff.legal_targets(state, 0)
    assert ("creature", sky.id) in legal


def test_swarmyard_filter_rejects_creature_without_allowed_subtype():
    """A creature whose subtypes don't intersect the allowed set is
    excluded from legal_targets even though it's a creature on the
    battlefield."""
    state = _new_state()
    _put(state, STELLAR_SIGHTS_LANDS["Swarmyard"])
    sky = _put(state, EOE_CREATURES["Skystinger"])
    plain = _put(state, make_creature("Plain Bear", "{1}{G}", 2, 2))

    eff = STELLAR_SIGHTS_LANDS[
        "Swarmyard"
    ].activated_abilities[0].effect
    legal = eff.legal_targets(state, 0)
    ids = {t[1] for t in legal}
    assert sky.id in ids
    assert plain.id not in ids


def test_swarmyard_activation_saves_skystinger_from_lethal_damage():
    """End-to-end: Skystinger has lethal damage marked, controller
    activates Swarmyard targeting it. After the ability resolves and
    state-based actions check, Skystinger survives — damage cleared,
    creature tapped, shield consumed."""
    state = _new_state()
    swarm = _put(state, STELLAR_SIGHTS_LANDS["Swarmyard"])
    _put(state, BASIC_LANDS["Mountain"])  # untapped {1} mana source
    sky = _put(state, EOE_CREATURES["Skystinger"])
    # Skystinger is a 3/3 — 5 damage is lethal.
    sky.damage = 5
    sky.attacking = True

    apply_action(
        state, 0, ActivateAbility(source_id=swarm.id, ability_index=0),
    )
    # Drain the stack: regenerate ability resolves and sets the shield.
    while state.stack:
        resolve_top_of_stack(state)

    # Shield is set pre-SBA.
    assert sky.regeneration_shield is True
    # Swarmyard is now tapped (cost paid).
    assert swarm.tapped is True

    # State-based actions: shield triggers, replacing destruction.
    state_based_actions(state)
    assert sky in state.battlefield
    assert sky.damage == 0
    assert sky.tapped is True
    assert sky.attacking is False
    # Shield consumed.
    assert sky.regeneration_shield is False
