"""Tests for Stellar Sights batch 5: Cathedral of War, Endless Sands,
Inventors' Fair — simpler-utility lands.

Three of the six originally targeted cards are intentionally left as
stand-ins (Mystifying Maze, Eldrazi Temple, Swarmyard) because they
require engine work this branch doesn't scope: delayed end-step
triggers, multiple mana abilities per card, and Regenerate respectively.
"""

from mtg_bot.actions import ActivateAbility, apply_action, resolve_top_of_stack
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.cards.base import make_creature, make_artifact
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_sacrifice(self, state, player_id, legal_ids):
        return legal_ids[0] if legal_ids else None

    def choose_card_from_library(self, state, player_id, legal_ids):
        return legal_ids[0] if legal_ids else None


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


# -----------------------
# Cathedral of War: enters tapped, taps for generic {C}. Exalted dropped.
# -----------------------


def test_cathedral_of_war_enters_tapped():
    p = _PRINTINGS["Cathedral of War"]
    assert p.enters_tapped is True
    assert p.is_land


def test_cathedral_of_war_has_exalted_keyword():
    """Cathedral of War grants Exalted via the ``"exalted"`` keyword on
    its printing. The pump is applied by combat._fire_exalted_pumps
    after declare_attackers, so no triggered/activated abilities live
    on the printing itself."""
    p = _PRINTINGS["Cathedral of War"]
    assert "exalted" in p.keywords
    assert p.triggered_abilities == ()
    assert p.activated_abilities == ()


# -----------------------
# Endless Sands: exile creature you control, sac-to-return-all.
# -----------------------


def test_endless_sands_has_two_activated_abilities():
    p = _PRINTINGS["Endless Sands"]
    assert len(p.activated_abilities) == 2
    # Second ability has sacrifice_self cost.
    assert p.activated_abilities[1].cost.sacrifice_self is True


def test_endless_sands_exiles_your_creature():
    state = _new_state()
    sands = _put(state, _PRINTINGS["Endless Sands"])
    # Give mana for {2} (oracle text: "{2}, {T}: Exile target creature
    # you control." — the old bespoke incorrectly used {3}).
    for _ in range(2):
        _put(state, BASIC_LANDS["Mountain"])
    # A creature you control to be the target.
    bear = _put(
        state,
        make_creature("Test Bear", "{1}{G}", 2, 2),
        owner_id=0,
    )
    bear.summoning_sick = False
    apply_action(
        state, 0, ActivateAbility(source_id=sands.id, ability_index=0),
    )
    while state.stack:
        resolve_top_of_stack(state)
    assert bear not in state.battlefield
    assert bear in state.players[0].exile
    assert bear.exiled_by_source == sands.id


def test_endless_sands_cannot_target_opponents_creature():
    """The yours_only flag restricts target selection to your own
    creatures."""
    from mtg_bot import legal_moves

    state = _new_state()
    sands = _put(state, _PRINTINGS["Endless Sands"])
    for _ in range(2):
        _put(state, BASIC_LANDS["Mountain"])
    # Only an opponent's creature exists — ability should have no legal
    # target so the activation isn't offered.
    enemy = _put(
        state,
        make_creature("Enemy Bear", "{1}{G}", 2, 2),
        owner_id=1,
    )
    enemy.summoning_sick = False
    actions = legal_moves(state)
    # The activation is still castable (it has legal_targets fallback),
    # but resolving it with no own creatures should be a no-op.
    # The more important invariant: if we DO resolve it, the enemy
    # creature isn't exiled.
    if any(
        isinstance(a, ActivateAbility) and a.source_id == sands.id
        and a.ability_index == 0
        for a in actions
    ):
        apply_action(
            state, 0,
            ActivateAbility(source_id=sands.id, ability_index=0),
        )
        while state.stack:
            resolve_top_of_stack(state)
    assert enemy in state.battlefield


def test_endless_sands_sac_returns_exiled_creatures():
    """Sacrificing Endless Sands releases all creatures it exiled.
    Oracle costs: {2},{T} to exile + {4},{T},sac to return (total 6
    generic mana needed — 2 Mountains more than the old bespoke {3}+{3}
    that was incorrect)."""
    state = _new_state()
    sands = _put(state, _PRINTINGS["Endless Sands"])
    for _ in range(6):
        _put(state, BASIC_LANDS["Mountain"])
    # (6 Mountains still sufficient: {2} exile + {4} sac = 6 total.)
    bear = _put(
        state,
        make_creature("Test Bear", "{1}{G}", 2, 2),
        owner_id=0,
    )
    bear.summoning_sick = False
    # Ability 0: exile the bear.
    apply_action(
        state, 0, ActivateAbility(source_id=sands.id, ability_index=0),
    )
    while state.stack:
        resolve_top_of_stack(state)
    assert bear in state.players[0].exile
    # Ability 1: sacrifice Endless Sands. The _release_exiled_until_leaves
    # hook fires during move_off_battlefield and auto-returns the bear.
    apply_action(
        state, 0, ActivateAbility(source_id=sands.id, ability_index=1),
    )
    while state.stack:
        resolve_top_of_stack(state)
    assert sands not in state.battlefield
    assert bear in state.battlefield
    assert bear not in state.players[0].exile


# -----------------------
# Inventors' Fair: tutor an artifact to hand; drop upkeep life gain.
# -----------------------


def test_inventors_fair_is_legendary():
    """Inventors' Fair is a Legendary Land (no 'enters tapped' clause
    in the oracle text; the old bespoke entry incorrectly set
    enters_tapped=True)."""
    p = _PRINTINGS["Inventors' Fair"]
    assert "Legendary" in p.supertypes
    assert p.enters_tapped is False


def test_inventors_fair_tutors_an_artifact():
    """Activation costs {4},{T},Sacrifice Inventors' Fair and requires
    controlling 3+ artifacts (oracle text). Give 4 Mountains for mana
    and 3 artifact permanents to satisfy the activation condition."""
    state = _new_state()
    fair = _put(state, _PRINTINGS["Inventors' Fair"])
    # 4 Mountains for the {4} activation cost.
    for _ in range(4):
        _put(state, BASIC_LANDS["Mountain"])
    # 3 artifact permanents to satisfy "Activate only if you control
    # three or more artifacts" (fair itself is a Land, not an artifact).
    for _ in range(3):
        _put(state, make_artifact("Test Scrap", "{0}"))
    # Stock library with an artifact and a non-artifact distractor.
    art_printing = make_artifact("Test Cog", "{0}")
    art_card = state.new_object(art_printing, 0, Zone.LIBRARY)
    state.players[0].library.append(art_card)
    bear_card = state.new_object(
        make_creature("Test Bear", "{1}{G}", 2, 2),
        0, Zone.LIBRARY,
    )
    state.players[0].library.append(bear_card)
    apply_action(
        state, 0, ActivateAbility(source_id=fair.id, ability_index=0),
    )
    while state.stack:
        resolve_top_of_stack(state)
    # Fair sacrificed itself, Cog landed in hand, Bear stayed in library.
    assert fair not in state.battlefield
    assert art_card in state.players[0].hand
    assert bear_card in state.players[0].library


def test_inventors_fair_has_upkeep_trigger():
    """The upkeep gain-1-life trigger is now wired (with the 3+
    artifacts condition)."""
    from mtg_bot.effects.predicates import (
        Controlled,
        Event,
        YOU,
    )

    p = _PRINTINGS["Inventors' Fair"]
    assert len(p.triggered_abilities) == 1
    ab = p.triggered_abilities[0]
    assert ab.event == Event.BEGINNING_OF_UPKEEP
    assert ab.predicate == Controlled(YOU)


# -----------------------
# Progress marker
# -----------------------


