"""Cube spells-B: the Flashback card's granted flashback and Yawgmoth's
Will (play lands / cast spells from the graveyard + graveyard-to-exile
replacement)."""

from __future__ import annotations

import pytest

from mtg_bot.actions import CastSpell, PlayLand, apply_action, resolve_top_of_stack
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.effects.generic.card_flow import CardFilter, discard_card
from mtg_bot.effects.generic.graveyard_casting import (
    ExileInsteadOfGraveyardThisTurn,
    GrantFlashbackToTargetCardUEOT,
    MayPlayFromGraveyardThisTurn,
)
from mtg_bot.game import Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import (
    Step,
    apply_graveyard_exile_replacement,
    move_off_battlefield,
    run_cleanup_step,
    state_based_actions,
)
from tests._spells_b_helpers import (
    ScriptedAgent,
    add,
    add_lands,
    cast_and_resolve,
    make_state,
)


@pytest.fixture(scope="module")
def cube():
    return OracleParserCardSource(pool="cube").get_printings()


def test_printings(cube):
    assert cube["Flashback"].spell_effect == GrantFlashbackToTargetCardUEOT(
        card_filter=CardFilter(any_types=("Instant", "Sorcery")),
    )
    from mtg_bot.cards.base import Sequence

    assert cube["Yawgmoth's Will"].spell_effect == Sequence(effects=(
        MayPlayFromGraveyardThisTurn(), ExileInsteadOfGraveyardThisTurn(),
    ))


def test_flashback_card_grants_flashback_for_mana_cost():
    state = make_state()
    for _ in range(3):
        add(state, 0, "Island", Zone.LIBRARY)
    recall = add(state, 0, "Ancestral Recall", Zone.GRAVEYARD)
    add(state, 0, "Island", Zone.GRAVEYARD)  # not an instant/sorcery
    fb = add(state, 0, "Flashback", Zone.HAND)
    add_lands(state, 0, "Mountain", 1)
    add_lands(state, 0, "Island", 1)
    eff = fb.printing.spell_effect
    assert eff.legal_targets(state, 0) == [("graveyard_card", recall.id)]
    state.players[0].agent.scripts["target"] = [("graveyard_card", recall.id)]
    cast_and_resolve(state, 0, fb)
    assert recall.flashback_granted_until_eot
    assert CastSpell(recall.id, use_flashback=True) in legal_actions(state, 0)
    state.players[0].agent.scripts["target"] = [("player", 0)]
    cast_and_resolve(state, 0, recall, use_flashback=True)
    assert recall in state.players[0].exile
    assert not recall.flashback_granted_until_eot
    assert len(state.players[0].hand) == 3


def test_granted_flashback_expires_at_cleanup():
    state = make_state()
    recall = add(state, 0, "Ancestral Recall", Zone.GRAVEYARD)
    GrantFlashbackToTargetCardUEOT().resolve(state, 0, (("graveyard_card", recall.id),))
    assert recall.flashback_granted_until_eot
    # Clone first so the copy-on-write graveyard is shared at cleanup.
    clone = state.clone()
    run_cleanup_step(state)
    assert not state.players[0].graveyard[0].flashback_granted_until_eot
    assert clone.players[0].graveyard[0].flashback_granted_until_eot


def test_grant_flashback_edge_cases():
    state = make_state()
    eff = GrantFlashbackToTargetCardUEOT()
    assert eff.requires_target()
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("graveyard_card", 123),))
    assert "gains flashback" in eff.describe()


def _yw_state():
    state = make_state()
    for _ in range(3):
        add(state, 0, "Island", Zone.LIBRARY)
    return state


def test_yawgmoths_will_casts_and_plays_from_graveyard():
    state = _yw_state()
    ritual = add(state, 0, "Dark Ritual", Zone.GRAVEYARD)
    swamp = add(state, 0, "Swamp", Zone.GRAVEYARD)
    tutor = add(state, 0, "Demonic Tutor", Zone.GRAVEYARD)
    yw = add(state, 0, "Yawgmoth's Will", Zone.HAND)
    add_lands(state, 0, "Swamp", 3)
    cast_and_resolve(state, 0, yw)
    p = state.players[0]
    assert yw in p.exile  # replaced on its way to the graveyard
    assert p.may_play_from_graveyard_this_turn
    acts = legal_actions(state, 0)
    assert PlayLand(swamp.id) in acts
    assert CastSpell(ritual.id) not in acts  # no mana left yet
    apply_action(state, 0, PlayLand(swamp.id))
    assert CastSpell(ritual.id) in legal_actions(state, 0)
    cast_and_resolve(state, 0, ritual)
    assert ritual in p.exile
    assert CastSpell(tutor.id) in legal_actions(state, 0)


def test_yawgmoths_will_instant_at_instant_speed():
    state = _yw_state()
    state.players[0].may_play_from_graveyard_this_turn = True
    ritual = add(state, 0, "Dark Ritual", Zone.GRAVEYARD)
    tutor = add(state, 0, "Demonic Tutor", Zone.GRAVEYARD)
    add_lands(state, 0, "Swamp", 2)
    state.step = Step.UPKEEP
    acts = legal_actions(state, 0)
    assert CastSpell(ritual.id) in acts and CastSpell(tutor.id) not in acts


def test_exile_replacement_paths():
    state = make_state()
    p = state.players[0]
    old = add(state, 0, "Island", Zone.GRAVEYARD)
    ExileInsteadOfGraveyardThisTurn().resolve(state, 0)
    ExileInsteadOfGraveyardThisTurn().resolve(state, 0)  # idempotent
    assert p.graveyard_exile_snapshot == frozenset({old.id})
    # Dies -> exiled, no graveyard stop.
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(bear)
    move_off_battlefield(state, bear, destination="graveyard")
    assert bear in p.exile
    # Discard lands in the graveyard; the sweep exiles it.
    card = add(state, 0, "Swamp", Zone.HAND)
    discard_card(state, p, card)
    assert card in p.graveyard
    assert state_based_actions(state)
    assert card in p.exile and old in p.graveyard
    assert not apply_graveyard_exile_replacement(state)
    # Opponent unaffected.
    other = add(state, 1, "Swamp", Zone.HAND)
    discard_card(state, state.players[1], other)
    state_based_actions(state)
    assert other in state.players[1].graveyard
    run_cleanup_step(state)
    assert not p.graveyard_exile_replacement_this_turn
    assert "exile that card instead" in ExileInsteadOfGraveyardThisTurn().describe()
    assert "from your graveyard" in MayPlayFromGraveyardThisTurn().describe()
