"""Conspiracy cards (CR 313) -- Power Play and Advantageous Proclamation.

The parse (conspiracy builder + rule grammar) and the pregame behavior in
``simulate.setup_game``: conspiracies start face up in the command zone,
never in the library; "You are the starting player" overrides the
caller's starting seat (random among several claimants); "Your minimum
deck size is reduced by five" moves the minimum the engine enforces when
one is in force."""

from __future__ import annotations

import pytest

from mtg_bot.cards.parser.conspiracy_builder import _build_conspiracy_printing
from mtg_bot.cards.parser.roto_keywords import number_word, parse_conspiracy_rule_line
from mtg_bot.conspiracies import (
    LIMITED_MINIMUM_DECK_SIZE,
    MinimumDeckSizeChange,
    YouAreTheStartingPlayer,
    minimum_deck_size,
)
from mtg_bot.game import Zone
from mtg_bot.simulate import setup_game
from tests._roto_helpers import printing, roto_card
from tests._roto_p6_helpers import PregameAgent, roto_source

POWER_PLAY = "Power Play"
PROCLAMATION = "Advantageous Proclamation"


# ------------------------------------------------------------------ parse


def test_power_play_parses_as_a_conspiracy():
    p = printing(POWER_PLAY)
    assert p.is_conspiracy and not p.is_permanent
    assert p.card_types == ("Conspiracy",)
    assert p.conspiracy_rules == (YouAreTheStartingPlayer(),)
    assert p.mana_cost.total == 0


def test_advantageous_proclamation_parses():
    p = printing(PROCLAMATION)
    assert p.is_conspiracy
    assert p.conspiracy_rules == (MinimumDeckSizeChange(-5),)


def test_rule_line_grammar():
    assert parse_conspiracy_rule_line(
        "Your minimum deck size is increased by 5."
    ) == MinimumDeckSizeChange(5)
    assert parse_conspiracy_rule_line(
        "Your minimum deck size is reduced by ten."
    ) == MinimumDeckSizeChange(-10)
    assert parse_conspiracy_rule_line(
        "Your minimum deck size is reduced by lots."
    ) is None
    assert parse_conspiracy_rule_line("Draw a card.") is None
    assert number_word("7") == 7 and number_word("Five") == 5
    assert number_word("lots") is None


def test_builder_rejects_unmodeled_conspiracies_and_other_types():
    base = dict(roto_card(POWER_PLAY))
    # Hidden agenda / draft-matters text: not a modeled rule.
    hidden = dict(base, oracle_text="Hidden agenda\nDraw a card.")
    assert _build_conspiracy_printing(hidden) is None
    # Reminder text alone is no rule.
    bare = dict(base, oracle_text="(Start the game with this conspiracy face up in the command zone.)")
    assert _build_conspiracy_printing(bare) is None
    assert _build_conspiracy_printing(dict(base, type_line="Artifact")) is None
    assert _build_conspiracy_printing(dict(base, card_faces=[{}, {}])) is None


def test_describe():
    assert YouAreTheStartingPlayer().describe() == "you are the starting player"
    assert MinimumDeckSizeChange(-5).describe() == (
        "your minimum deck size is reduced by 5"
    )
    assert MinimumDeckSizeChange(5).describe() == (
        "your minimum deck size is increased by 5"
    )


# --------------------------------------------------------- command zone


def _game(deck0, deck1, *, starting=0, seed=7, **kw):
    with roto_source(POWER_PLAY, PROCLAMATION):
        return setup_game(
            [PregameAgent(), PregameAgent()], decks=[deck0, deck1],
            seed=seed, starting_player_idx=starting, **kw,
        )


def test_conspiracy_starts_face_up_in_the_command_zone():
    state = _game(["Island"] * 20, [POWER_PLAY] + ["Island"] * 20)
    p1 = state.players[1]
    (pp,) = p1.conspiracies
    assert pp.printing.name == POWER_PLAY
    assert pp.zone is Zone.COMMAND and pp.owner_id == 1
    zones = p1.library + p1.hand + p1.graveyard + p1.exile
    assert all(c.printing.name != POWER_PLAY for c in zones)
    # Not part of the deck: 20 Islands, 7 in hand.
    assert len(p1.library) + len(p1.hand) == 20
    assert state.players[0].conspiracies == ()
    assert any("face up in the command zone" in line for line in state.log)


def test_command_zone_survives_clone():
    state = _game(["Island"] * 20, [POWER_PLAY] + ["Island"] * 20)
    clone = state.clone()
    assert clone.players[1].conspiracies == state.players[1].conspiracies


# ------------------------------------------------------- starting player


def test_power_play_makes_its_owner_the_starting_player():
    state = _game(["Island"] * 20, [POWER_PLAY] + ["Island"] * 20, starting=0)
    assert state.active_player_idx == 1 and state.priority_player_idx == 1
    state = _game([POWER_PLAY] + ["Island"] * 20, ["Island"] * 20, starting=1)
    assert state.active_player_idx == 0


def test_without_power_play_the_callers_seat_stands():
    state = _game([PROCLAMATION] + ["Island"] * 20, ["Island"] * 20, starting=1)
    assert state.active_player_idx == 1


def test_two_power_plays_choose_at_random():
    deck = [POWER_PLAY] + ["Island"] * 20
    starters = {
        _game(deck, deck, seed=seed).active_player_idx for seed in range(12)
    }
    assert starters == {0, 1}
    # Deterministic in the seed.
    assert (
        _game(deck, deck, seed=3).active_player_idx
        == _game(deck, deck, seed=3).active_player_idx
    )


def test_power_play_starter_gets_opening_hand_actions_right():
    """Gemstone Caverns is offered to the non-starting player -- the one
    Power Play didn't make the starter."""
    caverns = "Gemstone Caverns"
    a0 = PregameAgent(yes_no=[True])
    a1 = PregameAgent(yes_no=[True])
    with roto_source(POWER_PLAY):
        state = setup_game(
            [a0, a1],
            decks=[[caverns] * 20, [POWER_PLAY] + [caverns] * 20],
            seed=7, starting_player_idx=0,
        )
    assert state.active_player_idx == 1
    assert a1.prompts == []  # P1 starts: never offered
    assert a0.prompts and a0.prompts[0].startswith("begin the game with")


# ------------------------------------------------------ minimum deck size


def test_minimum_deck_size_reduced_by_five():
    thirty_five = ["Island"] * 35
    state = _game(
        [PROCLAMATION] + thirty_five, ["Island"] * 40,
        minimum_deck_size=LIMITED_MINIMUM_DECK_SIZE,
    )
    assert minimum_deck_size(state.players[0], 40) == 35
    assert minimum_deck_size(state.players[1], 40) == 40


def test_deck_below_the_adjusted_minimum_is_rejected():
    with pytest.raises(ValueError, match="minimum deck size is 35"):
        _game(
            [PROCLAMATION] + ["Island"] * 34, ["Island"] * 40,
            minimum_deck_size=40,
        )
    # Without the conspiracy, 35 cards is short of 40.
    with pytest.raises(ValueError, match="minimum deck size is 40"):
        _game(["Island"] * 35, ["Island"] * 40, minimum_deck_size=40)


def test_conspiracies_do_not_count_toward_deck_size():
    with pytest.raises(ValueError, match="has 39 cards"):
        _game(
            [POWER_PLAY] + ["Island"] * 39, ["Island"] * 40,
            minimum_deck_size=40,
        )


def test_no_minimum_checks_nothing():
    state = _game(["Island"] * 10, ["Island"] * 10)
    assert len(state.players[0].hand) == 7


def test_minimum_never_negative():
    class _P:
        conspiracies = ()

    assert minimum_deck_size(_P(), 0) == 0
