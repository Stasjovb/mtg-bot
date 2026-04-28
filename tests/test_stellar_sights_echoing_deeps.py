"""Tests for Echoing Deeps' optional-copy-from-graveyard ETB."""

from mtg_bot.actions import PlayLand, apply_action
from mtg_bot.agents import Agent
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _DeclineAgent(Agent):
    """Always declines optional graveyard-copy targets."""

    def choose_target(self, state, player_id, legal_targets):
        if legal_targets and legal_targets[0][0] == "graveyard_land_card":
            return None
        return legal_targets[0] if legal_targets else None


class _AcceptAgent(Agent):
    """Picks the first graveyard-land-card target it's offered."""

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state(agent_cls=_AcceptAgent):
    state = GameState()
    state.players.append(Player(id=0, agent=agent_cls()))
    state.players.append(Player(id=1, agent=agent_cls()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _stock_graveyard_land(state, player_id, printing):
    card = state.new_object(printing, player_id, Zone.GRAVEYARD)
    state.players[player_id].graveyard.append(card)
    return card


def _stock_hand_land(state, player_id, printing):
    card = state.new_object(printing, player_id, Zone.HAND)
    state.players[player_id].hand.append(card)
    return card


# -----------------------
# Metadata
# -----------------------


def test_echoing_deeps_is_cave_with_copy_flag():
    p = _PRINTINGS["Echoing Deeps"]
    assert "Cave" in p.subtypes
    assert p.optional_copy_land_from_graveyard is True


# -----------------------
# Copy-accept path
# -----------------------


def test_echoing_deeps_copies_graveyard_forest():
    state = _new_state(agent_cls=_AcceptAgent)
    _stock_graveyard_land(state, 0, BASIC_LANDS["Forest"])
    deeps_card = _stock_hand_land(
        state, 0, _PRINTINGS["Echoing Deeps"],
    )
    apply_action(state, 0, PlayLand(card_id=deeps_card.id))
    # Deeps is on the battlefield, tapped, and its printing mirrors
    # Forest + Cave.
    assert deeps_card in state.battlefield
    assert deeps_card.tapped is True
    assert "G" in deeps_card.printing.produces
    assert "Cave" in deeps_card.printing.subtypes


def test_echoing_deeps_copies_across_opponent_graveyard():
    """Oracle allows copying a land card in ANY graveyard, including
    an opponent's."""
    state = _new_state(agent_cls=_AcceptAgent)
    # P1's graveyard has a Mountain.
    _stock_graveyard_land(state, 1, BASIC_LANDS["Mountain"])
    deeps = _stock_hand_land(
        state, 0, _PRINTINGS["Echoing Deeps"],
    )
    apply_action(state, 0, PlayLand(card_id=deeps.id))
    assert "R" in deeps.printing.produces


def test_echoing_deeps_injects_cave_even_when_target_is_a_cave():
    """Idempotency: copying a land that's already a Cave doesn't
    duplicate the subtype."""
    state = _new_state(agent_cls=_AcceptAgent)
    # Use Sunken Citadel (also a Cave) as the copy target.
    _stock_graveyard_land(state, 0, _PRINTINGS["Sunken Citadel"])
    deeps = _stock_hand_land(
        state, 0, _PRINTINGS["Echoing Deeps"],
    )
    apply_action(state, 0, PlayLand(card_id=deeps.id))
    cave_count = sum(1 for s in deeps.printing.subtypes if s == "Cave")
    assert cave_count == 1


# -----------------------
# Copy-decline path
# -----------------------


def test_echoing_deeps_decline_enters_untapped_and_keeps_own_abilities():
    state = _new_state(agent_cls=_DeclineAgent)
    _stock_graveyard_land(state, 0, BASIC_LANDS["Forest"])
    deeps = _stock_hand_land(
        state, 0, _PRINTINGS["Echoing Deeps"],
    )
    apply_action(state, 0, PlayLand(card_id=deeps.id))
    assert deeps.tapped is False
    # Still the original Echoing Deeps (not a Forest).
    assert deeps.printing.name == "Echoing Deeps"
    assert "G" not in deeps.printing.produces


def test_echoing_deeps_no_graveyard_lands_enters_normally():
    state = _new_state(agent_cls=_AcceptAgent)
    # Graveyard has only non-land cards.
    deeps = _stock_hand_land(
        state, 0, _PRINTINGS["Echoing Deeps"],
    )
    apply_action(state, 0, PlayLand(card_id=deeps.id))
    assert deeps.printing.name == "Echoing Deeps"
    assert deeps.tapped is False


# -----------------------
# Progress marker
# -----------------------


def test_offer_echoing_deeps_copy_bad_kind_is_noop():
    """Defensive: agent returns a target with the wrong kind — helper
    returns without mutating the card."""
    from mtg_bot.actions import _offer_echoing_deeps_copy

    class _WrongKindAgent(Agent):
        def choose_target(self, state, player_id, legal_targets):
            return ("player", 0)  # deliberately wrong kind

    state = _new_state(agent_cls=_WrongKindAgent)
    _stock_graveyard_land(state, 0, BASIC_LANDS["Forest"])
    card = _stock_hand_land(
        state, 0, _PRINTINGS["Echoing Deeps"],
    )
    _offer_echoing_deeps_copy(state, 0, card)
    assert card.printing.name == "Echoing Deeps"
    assert card.tapped is False


def test_offer_echoing_deeps_copy_missing_target_is_noop():
    """Defensive: agent returns a target_id that isn't in any
    graveyard. Helper exits cleanly."""
    from mtg_bot.actions import _offer_echoing_deeps_copy

    class _GhostIdAgent(Agent):
        def choose_target(self, state, player_id, legal_targets):
            return ("graveyard_land_card", 99999)  # nonexistent id

    state = _new_state(agent_cls=_GhostIdAgent)
    _stock_graveyard_land(state, 0, BASIC_LANDS["Forest"])
    card = _stock_hand_land(
        state, 0, _PRINTINGS["Echoing Deeps"],
    )
    _offer_echoing_deeps_copy(state, 0, card)
    assert card.printing.name == "Echoing Deeps"


