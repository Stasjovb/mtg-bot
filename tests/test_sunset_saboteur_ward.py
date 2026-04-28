"""Tests for Sunset Saboteur's Ward—Discard a card (chosen).

The discard variant on this card is caster-chooses, distinct from the
random-discard variant on Alpharael, Stonechosen.
"""

from mtg_bot.actions import _cast_spell
from mtg_bot.agents import Agent
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.game import GameState, Player, Zone

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _PickFirstAgent(Agent):
    """Deterministic agent: always picks the first option for any
    decision the test exercises."""

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_discard(self, state, player_id, hand_card_ids):
        return hand_card_ids[0]


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    return state


def test_sunset_saboteur_ward_caster_chooses_discard():
    """Opponent targets Sunset Saboteur with a discardable hand → caster
    picks a card via choose_discard, the spell resolves."""
    state = _new_state()
    sab = state.new_object(
        _PRINTINGS["Sunset Saboteur"], 1, Zone.BATTLEFIELD,
    )
    sab.summoning_sick = False
    state.battlefield.append(sab)
    # Mana for Gravkill ({3}{B}).
    for _ in range(4):
        m = state.new_object(BASIC_LANDS["Swamp"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(m)
    # P0 has multiple hand cards so the choice matters.
    plains_a = state.new_object(BASIC_LANDS["Plains"], 0, Zone.HAND)
    plains_b = state.new_object(BASIC_LANDS["Plains"], 0, Zone.HAND)
    plains_c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.HAND)
    state.players[0].hand.extend([plains_a, plains_b, plains_c])
    grav = state.new_object(_PRINTINGS["Gravkill"], 0, Zone.HAND)
    state.players[0].hand.append(grav)
    hand_before = len(state.players[0].hand)
    _cast_spell(state, 0, grav.id)
    # Spell itself leaves hand (-1) and ward forces a chosen discard (-1).
    assert len(state.players[0].hand) == hand_before - 2


def test_sunset_saboteur_ward_counters_when_hand_empty():
    """Opponent has empty hand (after casting the spell) → cannot pay the
    Ward → spell countered, Saboteur stays on the battlefield."""
    state = _new_state()
    sab = state.new_object(
        _PRINTINGS["Sunset Saboteur"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(sab)
    for _ in range(4):
        m = state.new_object(BASIC_LANDS["Swamp"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(m)
    grav = state.new_object(_PRINTINGS["Gravkill"], 0, Zone.HAND)
    state.players[0].hand.append(grav)
    # Only the spell itself in hand → after putting it on stack, hand is
    # empty when Ward fires → countered.
    _cast_spell(state, 0, grav.id)
    assert sab in state.battlefield
    assert any(
        "countered by Sunset Saboteur's Ward" in entry for entry in state.log
    )


def test_sunset_saboteur_ward_removes_chosen_card_from_hand():
    """Verify that the ward removes the SPECIFIC card the agent picked
    (the first card, given _PickFirstAgent), not a random one."""
    state = _new_state()
    sab = state.new_object(
        _PRINTINGS["Sunset Saboteur"], 1, Zone.BATTLEFIELD,
    )
    sab.summoning_sick = False
    state.battlefield.append(sab)
    for _ in range(4):
        m = state.new_object(BASIC_LANDS["Swamp"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(m)
    # Distinct, identifiable hand cards. _PickFirstAgent should discard
    # whichever was first when ward fires; the spell itself is appended
    # last, so the first hand id is a Plains.
    first_card = state.new_object(BASIC_LANDS["Plains"], 0, Zone.HAND)
    second_card = state.new_object(BASIC_LANDS["Mountain"], 0, Zone.HAND)
    state.players[0].hand.extend([first_card, second_card])
    grav = state.new_object(_PRINTINGS["Gravkill"], 0, Zone.HAND)
    state.players[0].hand.append(grav)
    _cast_spell(state, 0, grav.id)
    # First card (Plains) was the agent's pick — should be in graveyard,
    # not in hand. Second card (Mountain) should still be in hand.
    hand_ids = [c.id for c in state.players[0].hand]
    grave_ids = [c.id for c in state.players[0].graveyard]
    assert first_card.id not in hand_ids
    assert first_card.id in grave_ids
    assert second_card.id in hand_ids


def test_sunset_saboteur_printing_metadata():
    """The printing exposes the new chosen-discard ward flag and Menace."""
    p = _PRINTINGS["Sunset Saboteur"]
    assert p.ward_discard_chosen is True
    assert p.ward_discard_random is False
    assert p.ward_cost is None
    assert "menace" in p.keywords
