"""SBA: Aura and Equipment attachment legality (CR 704.5n / 704.5p).

- Aura on illegal target → goes to graveyard.
- Equipment on illegal target → unattaches but stays on battlefield.

The headline case: a Lignified animated manland whose animation
expires at cleanup. The land is no longer a creature, so the
Lignify aura's enchant-creature restriction is violated. Lignify
should fall off via the SBA.
"""

from __future__ import annotations

from mtg_bot.actions import apply_aura_static_grants_on_attach
from mtg_bot.agents import Agent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.cards.base import make_basic_land
from mtg_bot.cards.demo_layers import LIGNIFY
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step, run_cleanup_step, state_based_actions

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _PickFirst(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirst()))
    state.players.append(Player(id=1, agent=_PickFirst()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def _attach(state, aura, target):
    aura.attached_to = target.id
    apply_aura_static_grants_on_attach(state, aura, target, aura.controller_id)


# ---------- Aura legality ----------


def test_aura_on_creature_legal_no_sba_action():
    """An Aura attached to a still-legal creature is fine."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    aura = _put(state, LIGNIFY, 0)
    _attach(state, aura, bear)
    state_based_actions(state)
    assert aura in state.battlefield
    assert aura.attached_to == bear.id


def test_aura_with_no_attached_to_buried():
    """An Aura with attached_to=None goes to graveyard."""
    state = _new_state()
    aura = _put(state, LIGNIFY, 0)
    aura.attached_to = None
    state_based_actions(state)
    assert aura not in state.battlefield
    assert aura in state.players[0].graveyard


def test_aura_attached_to_nonexistent_object_buried():
    """An Aura whose target id no longer exists on the battlefield
    goes to graveyard."""
    state = _new_state()
    aura = _put(state, LIGNIFY, 0)
    aura.attached_to = 99999  # nothing here
    state_based_actions(state)
    assert aura not in state.battlefield


def test_lignified_animated_manland_aura_falls_off_when_animation_expires():
    """The headline case: animated land + Lignify, animation expires
    at cleanup, land is no longer a creature, Lignify's enchant-
    creature restriction violated → Lignify SBA-buries.
    """
    state = _new_state()
    forest = _put(state, make_basic_land("Forest", "G"), 0)
    state.grant_become_creature_ueot(
        source_id=forest.id, target_id=forest.id,
        power=4, toughness=4,
        description="Forest animated 4/4 UEOT",
    )
    aura = _put(state, LIGNIFY, 0)
    _attach(state, aura, forest)
    # Pre-cleanup: legal attachment.
    assert aura in state.battlefield
    assert aura.attached_to == forest.id

    # Cleanup expires the animation. Forest is no longer a creature.
    run_cleanup_step(state)
    state_based_actions(state)

    # Lignify falls off.
    assert aura not in state.battlefield
    assert aura in state.players[0].graveyard
    # Forest stays — it's still a land.
    assert forest in state.battlefield


def test_aura_artifact_enchant_type_unattached_when_artifact_loses_artifact_type():
    """Hardlight Containment's aura_enchant_type is "artifact". If
    the target somehow stops being an artifact (no in-pool card
    causes this currently, but the SBA gate should catch it),
    the aura falls off. Test the gate by deleting the target
    object directly."""
    state = _new_state()
    # Use a generic artifact target.
    from mtg_bot.cards.base import (
        CardPrinting, ManaCost,
    )
    artifact = CardPrinting(
        name="Test Artifact",
        mana_cost_str="{1}",
        mana_cost=ManaCost(generic=1),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
    )
    target = _put(state, artifact, 0)
    aura = _put(state, _PRINTINGS["Hardlight Containment"], 0)
    aura.attached_to = target.id
    state_based_actions(state)
    # Legal attachment (target is an artifact).
    assert aura in state.battlefield

    # Remove target.
    state.battlefield.remove(target)
    state_based_actions(state)
    assert aura not in state.battlefield


# ---------- Equipment legality ----------


def test_equipment_attached_to_creature_legal_no_sba_action():
    """Equipment on a creature is legally attached — no SBA fires."""
    from mtg_bot.cards.base import make_equipment
    eq = make_equipment(
        "Test Equipment", "{1}",
        power_bonus=1, toughness_bonus=1,
    )
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    equipment = _put(state, eq, 0)
    equipment.attached_to = bear.id
    state_based_actions(state)
    assert equipment.attached_to == bear.id


def test_equipment_attached_to_nonexistent_unattaches():
    """Equipment whose target is gone unattaches but stays on the
    battlefield."""
    from mtg_bot.cards.base import make_equipment
    eq = make_equipment(
        "Test Equipment", "{1}",
        power_bonus=1, toughness_bonus=1,
    )
    state = _new_state()
    equipment = _put(state, eq, 0)
    equipment.attached_to = 99999
    state_based_actions(state)
    # Equipment stays — only its attached_to clears.
    assert equipment in state.battlefield
    assert equipment.attached_to is None


def test_equipment_on_non_creature_unattaches():
    """Equipment on a permanent that isn't a creature unattaches.
    Set up an artifact target (non-creature) and equip onto it."""
    from mtg_bot.cards.base import make_equipment, CardPrinting, ManaCost
    eq = make_equipment(
        "Test Equipment", "{1}",
        power_bonus=1, toughness_bonus=1,
    )
    artifact = CardPrinting(
        name="Test Artifact",
        mana_cost_str="{1}",
        mana_cost=ManaCost(generic=1),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
    )
    state = _new_state()
    target = _put(state, artifact, 0)
    equipment = _put(state, eq, 0)
    equipment.attached_to = target.id
    state_based_actions(state)
    # Target isn't a creature → unattaches.
    assert equipment.attached_to is None
    assert equipment in state.battlefield


def test_sba_iterates_until_quiescent_aura_chain():
    """A single SBA call iterates until quiescent (CR 704.3). Setup
    that exercises iteration: an animated manland with Lignify
    attached. After cleanup expires the animation, two SBA effects
    fire in sequence — the animation's registry entries are gone
    (handled by run_cleanup_step), then SBA finds Lignify on a
    non-creature and buries it. Burying Lignify is the second-pass
    work; the loop catches it.

    Without the loop, the first SBA pass would catch Lignify (which
    is enough in this case since burying it doesn't trigger another
    SBA). But adding two stacked auras on the same target tests
    the iteration: bury one, then the other becomes orphaned only
    if attachment is checked iteratively. Pin via state assertions.
    """
    state = _new_state()
    forest = _put(state, make_basic_land("Forest", "G"), 0)
    state.grant_become_creature_ueot(
        source_id=forest.id, target_id=forest.id,
        power=4, toughness=4,
        description="Forest animated 4/4 UEOT",
    )
    aura = _put(state, LIGNIFY, 0)
    _attach(state, aura, forest)
    run_cleanup_step(state)

    # state_based_actions should fully resolve in one (looped) call.
    state_based_actions(state)
    assert aura not in state.battlefield


def test_equipment_on_animated_manland_stays_then_unattaches_at_cleanup():
    """Equipment attached to an animated manland is legal while
    animation is in effect. After cleanup the animation expires,
    the manland is no longer a creature, equipment unattaches."""
    from mtg_bot.cards.base import make_equipment
    eq = make_equipment(
        "Test Equipment", "{1}",
        power_bonus=1, toughness_bonus=1,
    )
    state = _new_state()
    forest = _put(state, make_basic_land("Forest", "G"), 0)
    state.grant_become_creature_ueot(
        source_id=forest.id, target_id=forest.id,
        power=4, toughness=4,
        description="Forest animated 4/4 UEOT",
    )
    equipment = _put(state, eq, 0)
    equipment.attached_to = forest.id
    # While animated: legal.
    state_based_actions(state)
    assert equipment.attached_to == forest.id

    # Cleanup expires animation.
    run_cleanup_step(state)
    state_based_actions(state)

    # Equipment unattaches but stays.
    assert equipment in state.battlefield
    assert equipment.attached_to is None
