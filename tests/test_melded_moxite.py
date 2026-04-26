"""Card-level tests for Melded Moxite.

Oracle: "When this artifact enters, you may discard a card. If you do,
draw two cards.
{3}, Sacrifice this artifact: Create a tapped 2/2 colorless Robot
artifact creature token."

The ETB "may" is gated through ``Agent.choose_yes_no``. If the
controller declines, neither the discard nor the dependent draw fires.
Empty hand also fizzles even on yes — there's no "a card" to discard,
so "if you do" is not satisfied and the draw is skipped.
"""

from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import BASIC_LANDS, EOE_CREATURES, SYNTHETIC_CREATURES
from mtg_bot.game import GameState, Player, Zone


class _YesAgent(Agent):
    """Always says yes to optional 'may' choices. Picks the first hand
    card on a discard prompt."""

    def choose_yes_no(self, state, player_id, prompt):
        return True

    def choose_discard(self, state, player_id, hand_ids):
        return hand_ids[0]


class _NoAgent(Agent):
    """Always says no to optional 'may' choices."""

    def choose_yes_no(self, state, player_id, prompt):
        return False

    def choose_discard(self, state, player_id, hand_ids):
        # Should never be called when choose_yes_no is False, but
        # provide a safe default.
        return hand_ids[0]


def _state_with_moxite(agent):
    """Build a state where P0 controls Melded Moxite and has agent
    seated. Returns ``(state, p0, moxite)``."""
    state = GameState()
    state.players.append(Player(id=0, agent=agent))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.active_player_idx = 0
    p0 = state.players[0]
    moxite = state.new_object(
        EOE_CREATURES["Melded Moxite"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(moxite)
    state.resolving_source = moxite
    return state, p0, moxite


def _stock_library(p, state, count=3, name="Plains"):
    for _ in range(count):
        c = state.new_object(BASIC_LANDS[name], p.id, Zone.LIBRARY)
        p.library.append(c)


def test_melded_moxite_etb_yes_with_card_in_hand_discards_one_draws_two():
    """Agent says yes with a card in hand — discard 1, draw 2.

    The dependent "If you do, draw two cards" fires because a card was
    actually discarded (the "if you do" clause is satisfied)."""
    state, p0, moxite = _state_with_moxite(_YesAgent())
    # One card in hand to discard.
    fodder = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.HAND)
    p0.hand.append(fodder)
    _stock_library(p0, state, count=3)
    library_before = list(p0.library)

    etb = next(
        ab for ab in moxite.printing.triggered_abilities
        if ab.trigger == "etb"
    )
    etb.effect.resolve(state, 0)

    # Hand: started with 1, discarded that 1, drew 2 = 2 cards now.
    assert len(p0.hand) == 2
    # The original hand card is in the graveyard (discarded).
    assert fodder in p0.graveyard
    assert fodder.zone == Zone.GRAVEYARD
    # Two cards drawn off the top of the library.
    assert p0.hand == library_before[:2]
    # Library shrank by 2.
    assert len(p0.library) == 1


def test_melded_moxite_etb_no_path_skips_discard_and_draw():
    """Agent says no — hand is untouched, no cards drawn, graveyard
    unchanged. The dependent draw does NOT fire because "If you do"
    is not satisfied."""
    state, p0, moxite = _state_with_moxite(_NoAgent())
    fodder = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.HAND)
    p0.hand.append(fodder)
    _stock_library(p0, state, count=3)
    library_before = list(p0.library)
    hand_before = list(p0.hand)

    etb = next(
        ab for ab in moxite.printing.triggered_abilities
        if ab.trigger == "etb"
    )
    etb.effect.resolve(state, 0)

    # Hand untouched.
    assert p0.hand == hand_before
    # Library untouched.
    assert p0.library == library_before
    # Nothing in graveyard from this trigger.
    assert p0.graveyard == []


def test_melded_moxite_etb_yes_with_empty_hand_skips_draw():
    """Empty-hand edge case. Even if the controller says yes, there's
    no "a card" to discard — "if you do" is not satisfied and the
    two-card draw does NOT fire. This is the critical difference from
    the prior unconditional implementation, which drew 2 from an empty
    hand."""
    state, p0, moxite = _state_with_moxite(_YesAgent())
    # Hand intentionally empty.
    assert p0.hand == []
    _stock_library(p0, state, count=3)
    library_before = list(p0.library)

    etb = next(
        ab for ab in moxite.printing.triggered_abilities
        if ab.trigger == "etb"
    )
    etb.effect.resolve(state, 0)

    # No draw fired — hand still empty.
    assert p0.hand == []
    # Library untouched.
    assert p0.library == library_before
    # Graveyard untouched (nothing was discarded).
    assert p0.graveyard == []


def test_melded_moxite_activated_ability_still_creates_robot_token():
    """Regression: the {3}, Sacrifice this artifact activated ability
    still creates exactly one tapped 2/2 colorless Robot artifact
    creature token after the ETB rewiring."""
    state, p0, moxite = _state_with_moxite(_YesAgent())

    act = moxite.printing.activated_abilities[0]
    assert act.cost.mana_str == "{3}"
    assert act.cost.sacrifice_self is True
    act.effect.resolve(state, 0)

    robots = [o for o in state.battlefield if o.printing.name == "Robot"]
    assert len(robots) == 1
    robot = robots[0]
    assert robot.tapped is True
    assert robot.printing.power == 2
    assert robot.printing.toughness == 2
    assert "Artifact" in robot.printing.card_types
    assert "Creature" in robot.printing.card_types
