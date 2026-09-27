"""Cube W/G creatures: graveyard play permissions (Six's retrace, Serra
Paragon) -- ``mtg_bot.graveyard_casting_wg``."""

from __future__ import annotations

from mtg_bot.actions import CastSpell, PlayLand, apply_action
from mtg_bot.effects.generic.cube_creatures_wg import (
    ExileSourceCardGainLife,
    MillThenMayPutLandIntoHand,
)
from mtg_bot.game import Zone
from mtg_bot.graveyard_casting_wg import (
    PARAGON,
    RETRACE,
    graveyard_cast_options,
    paragon_land_playable,
)
from mtg_bot.legal import legal_actions
from mtg_bot.turn import sacrifice
from tests._wg_helpers import (
    add_lands,
    attack,
    bear,
    cube,
    drain,
    make_state,
    put,
)


def test_six_attack_mills_and_returns_a_land():
    pr = cube()["Six"]
    assert "reach" in pr.keywords
    assert pr.grants_retrace_to_nonland_permanents_during_your_turn
    state = make_state()
    six = put(state, 0, pr)
    lib = [put(state, 0, n, Zone.LIBRARY) for n in ("Lightning Bolt", "Forest", "Island", "Swamp")]
    state.players[0].agent.scripts["library"] = [lib[1].id]
    attack(state, 0, [six.id])
    p = state.players[0]
    assert lib[1] in p.hand
    assert lib[0] in p.graveyard and lib[2] in p.graveyard
    assert p.library == [lib[3]]


def test_six_grants_retrace_during_your_turn_only():
    state = make_state()
    put(state, 0, "Six")
    elves = put(state, 0, "Llanowar Elves", Zone.GRAVEYARD)
    bolt = put(state, 0, "Lightning Bolt", Zone.GRAVEYARD)
    add_lands(state, 0, "Forest", 1)
    retrace = CastSpell(elves.id, graveyard_permission=RETRACE)
    assert retrace not in legal_actions(state, 0)  # no land card to discard
    land = put(state, 0, "Mountain", Zone.HAND)
    assert retrace in legal_actions(state, 0)
    assert all(c is not bolt for c, _ in graveyard_cast_options(state, 0))
    state.active_player_idx = 1
    assert graveyard_cast_options(state, 0) == []
    state.active_player_idx = 0
    apply_action(state, 0, retrace)
    drain(state)
    assert elves in state.battlefield
    assert land in state.players[0].graveyard


def test_serra_paragon_once_per_turn_land_or_cheap_permanent():
    pr = cube()["Serra Paragon"]
    assert pr.grants_once_per_turn_graveyard_play_mv == 3 and "flying" in pr.keywords
    state = make_state()
    paragon = put(state, 0, pr)
    gy_land = put(state, 0, "Forest", Zone.GRAVEYARD)
    elves = put(state, 0, "Llanowar Elves", Zone.GRAVEYARD)
    big = put(state, 0, "Vaultborn Tyrant", Zone.GRAVEYARD)
    add_lands(state, 0, "Forest", 1)
    actions = legal_actions(state, 0)
    assert PlayLand(gy_land.id) in actions
    assert CastSpell(elves.id, graveyard_permission=PARAGON) in actions
    assert not any(
        isinstance(a, CastSpell) and a.card_id == big.id for a in actions
    )
    apply_action(state, 0, CastSpell(elves.id, graveyard_permission=PARAGON))
    drain(state)
    assert elves in state.battlefield
    assert elves.leaves_to_graveyard_exile_gain_life == 2
    assert paragon.graveyard_permission_used_turn == state.turn_number
    assert not paragon_land_playable(state, 0)
    assert PlayLand(gy_land.id) not in legal_actions(state, 0)
    # Its rider: dies -> exiled, controller gains 2.
    sacrifice(state, elves)
    drain(state)
    assert elves in state.players[0].exile and state.players[0].life == 22
    # Next turn the permission is back; a land played with it gets the rider.
    state.turn_number += 1
    state.players[0].lands_played_this_turn = 0
    apply_action(state, 0, PlayLand(gy_land.id))
    assert gy_land in state.battlefield
    assert gy_land.leaves_to_graveyard_exile_gain_life == 2
    # Bounced instead of dying: the rider just ends.
    from mtg_bot.turn import move_off_battlefield

    move_off_battlefield(state, gy_land, destination="hand")
    assert gy_land.leaves_to_graveyard_exile_gain_life == 0


def test_unlimited_land_permission_doesnt_consume_paragon():
    state = make_state()
    paragon = put(state, 0, "Serra Paragon")
    put(state, 0, "Icetill Explorer")
    gy_land = put(state, 0, "Forest", Zone.GRAVEYARD)
    apply_action(state, 0, PlayLand(gy_land.id))
    assert gy_land in state.battlefield
    assert paragon.graveyard_permission_used_turn == -1
    assert gy_land.leaves_to_graveyard_exile_gain_life == 0


def test_graveyard_effect_edges():
    state = make_state()
    eff = MillThenMayPutLandIntoHand(n=2)
    eff.resolve(state, 0)  # empty library
    put(state, 0, "Forest", Zone.LIBRARY)
    state.players[0].agent.scripts["library"] = [None]
    eff.resolve(state, 0)
    assert len(state.players[0].graveyard) == 1
    assert "mill 2" in eff.describe()
    gain = ExileSourceCardGainLife(life=2)
    gain.resolve(state, 0)  # no source: still gains
    assert state.players[0].life == 22 and "2 life" in gain.describe()
