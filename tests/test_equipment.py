"""Tests for the Equip activated-ability subsystem (rule 702.6).

The Equip subsystem is wired through ``make_equipment(equip_cost=...)``,
which synthesizes a sorcery-speed activated ability whose effect
(``EquipToTargetCreatureYouControl``) re-attaches the source Equipment to
a target creature its controller controls. These tests cover the
activation gate, the cost shape, the re-attachment semantics, and the
falls-off-when-target-leaves invariant.
"""

import pytest

from mtg_bot import legal_moves
from mtg_bot.actions import (
    ActivateAbility, apply_action, resolve_top_of_stack,
)
from mtg_bot.agents import Agent
from mtg_bot.cards import (
    BASIC_LANDS, EOE_CREATURES, SYNTHETIC_CREATURES,
)
from mtg_bot.effects import (
    AttachToTargetCreatureYouControl, EquipToTargetCreatureYouControl,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step, move_off_battlefield


class _PickFirstAgent(Agent):
    name: str = "pick-first"

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state(active=0, step=Step.PRECOMBAT_MAIN):
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    state.active_player_idx = active
    state.priority_player_idx = active
    state.step = step
    return state


def _put(state, printing, owner_id=0, attached_to=None, summoning_sick=False):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    obj.summoning_sick = summoning_sick
    if attached_to is not None:
        obj.attached_to = attached_to
    state.battlefield.append(obj)
    return obj


# ---------------------------------------------------------------------------
# Card metadata: every Equipment ships its printed Equip cost.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "card_name, expected_cost",
    [
        ("Auxiliary Boosters", "{3}"),
        ("Hylderblade", "{4}"),
        ("Meltstrider's Gear", "{5}"),
        ("Squire's Lightblade", "{3}"),
        ("Illvoi Light Jammer", "{3}"),
    ],
)
def test_equipment_cards_ship_with_printed_equip_cost(card_name, expected_cost):
    """Each EoE Equipment card has an Equip activated ability whose mana cost
    matches the printed Equip {N} from oracle text."""
    eq = EOE_CREATURES[card_name]
    equip_abilities = [
        a for a in eq.activated_abilities
        if isinstance(a.effect, EquipToTargetCreatureYouControl)
    ]
    assert len(equip_abilities) == 1, (
        f"{card_name} should have exactly one Equip activated ability"
    )
    ab = equip_abilities[0]
    assert ab.cost.mana_str == expected_cost
    assert ab.sorcery_speed is True


# ---------------------------------------------------------------------------
# Activation gate.
# ---------------------------------------------------------------------------


def test_equip_activation_requires_sorcery_speed():
    """The Equip activated ability is sorcery-speed: it must NOT appear in
    legal_moves outside the active player's main phase with empty stack."""
    state = _new_state(active=0, step=Step.UPKEEP)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    eq = _put(state, EOE_CREATURES["Auxiliary Boosters"])
    # Plenty of mana to pay {3} so cost can't be the gating factor.
    for _ in range(5):
        _put(state, BASIC_LANDS["Forest"])
    moves = legal_moves(state, player_id=0)
    activations = [
        m for m in moves
        if isinstance(m, ActivateAbility) and m.source_id == eq.id
    ]
    assert activations == []
    # And during a main phase with empty stack, the same activation IS legal.
    state.step = Step.PRECOMBAT_MAIN
    moves = legal_moves(state, player_id=0)
    activations = [
        m for m in moves
        if isinstance(m, ActivateAbility) and m.source_id == eq.id
    ]
    assert len(activations) == 1


def test_equip_activation_costs_printed_mana():
    """Activating Equip {3} taps three lands (and only three)."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    eq = _put(state, EOE_CREATURES["Auxiliary Boosters"])
    lands = [_put(state, BASIC_LANDS["Forest"]) for _ in range(5)]
    apply_action(
        state, 0, ActivateAbility(source_id=eq.id, ability_index=0),
    )
    tapped_lands = [land for land in lands if land.tapped]
    assert len(tapped_lands) == 3
    # And ability is on the stack pending resolution.
    assert len(state.stack) == 1


# ---------------------------------------------------------------------------
# Re-attachment semantics.
# ---------------------------------------------------------------------------


def test_equip_moves_attachment_from_one_creature_to_another():
    """A second activation of Equip swaps the Equipment from creature A to
    creature B (rule 702.6c — re-attachment is the whole effect)."""
    state = _new_state()
    bear_a = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    bear_b = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    eq = _put(state, EOE_CREATURES["Squire's Lightblade"])
    eq.attached_to = bear_a.id  # initially equipped to A
    for _ in range(3):
        _put(state, BASIC_LANDS["Plains"])

    # An agent that always targets bear_b.
    class _PickB(Agent):
        name = "pick-b"

        def choose_target(self, state, player_id, legal_targets):
            for t in legal_targets:
                if t == ("creature", bear_b.id):
                    return t
            return legal_targets[0]

    state.players[0].agent = _PickB()

    apply_action(
        state, 0, ActivateAbility(source_id=eq.id, ability_index=0),
    )
    while state.stack:
        resolve_top_of_stack(state)
    assert eq.attached_to == bear_b.id
    # Equipment itself is still on the battlefield.
    assert eq in state.battlefield


def test_equipment_falls_off_when_attached_creature_leaves():
    """When the equipped creature leaves the battlefield, the Equipment
    stays put and its ``attached_to`` clears (it doesn't follow the
    creature to the graveyard like an Aura would)."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    eq = _put(state, EOE_CREATURES["Hylderblade"], attached_to=bear.id)
    move_off_battlefield(state, bear, destination="graveyard")
    assert eq in state.battlefield
    assert eq.attached_to is None


# ---------------------------------------------------------------------------
# Effect-level invariants — the new Effect class.
# ---------------------------------------------------------------------------


def test_equip_effect_inherits_attach_legality_filter():
    """The new ``EquipToTargetCreatureYouControl`` reuses the parent
    Attach effect's target machinery, so legal targets are creatures the
    activator controls — opponents' creatures never appear."""
    state = _new_state()
    my_bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    foe_bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    eq = _put(state, EOE_CREATURES["Meltstrider's Gear"])
    eff = EquipToTargetCreatureYouControl()
    state.resolving_source = eq
    try:
        legal = eff.legal_targets(state, controller_id=0)
    finally:
        state.resolving_source = None
    assert ("creature", my_bear.id) in legal
    assert ("creature", foe_bear.id) not in legal
    # Sanity: it's an Effect-class subclass of the ETB attach effect.
    assert isinstance(eff, AttachToTargetCreatureYouControl)
    assert eff.requires_target() is True
    assert "equip" in eff.describe().lower()


def test_equip_resolution_sets_attached_to():
    """Calling resolve directly (with state.resolving_source pointing at the
    Equipment) attaches the source to the chosen target."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    eq = _put(state, EOE_CREATURES["Illvoi Light Jammer"])
    state.resolving_source = eq
    try:
        EquipToTargetCreatureYouControl().resolve(
            state, 0, (("creature", bear.id),),
        )
    finally:
        state.resolving_source = None
    assert eq.attached_to == bear.id
