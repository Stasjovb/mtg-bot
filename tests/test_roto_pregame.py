"""Roto P6 pregame lines: Chancellor of the Tangle's opening-hand reveal
(a delayed "first main phase of the game" mana trigger) and Serum
Powder's mulligan-window hand exchange -- the parse, and the behavior
through ``simulate.setup_game`` and the turn loop."""

from __future__ import annotations

from dataclasses import replace

import pytest

from mtg_bot.cards.parser.roto_keywords import (
    build_with_p6_lines,
    parse_pregame_line,
)
from mtg_bot.cards.parser.source import build_card_record
from mtg_bot.effects.generic.mana import AddManaToPool
from mtg_bot.game import Zone
from mtg_bot.opening_hand import (
    AFTER_KEEP,
    MULLIGAN_WINDOW,
    BeginGameOnBattlefield,
    ExchangeHandWhileMulliganing,
    RevealFromOpeningHand,
)
from mtg_bot.simulate import run_step, setup_game
from mtg_bot.turn import Step
from tests._cube_artifact_helpers import pool_colors
from tests._roto_helpers import printing, roto_card
from tests._roto_p6_helpers import PregameAgent, roto_source

CHANCELLOR = "Chancellor of the Tangle"
POWDER = "Serum Powder"
REVEAL_LINE = (
    "You may reveal this card from your opening hand. If you do, at the "
    "beginning of your first main phase of the game, add {G}."
)
POWDER_LINE = (
    "Any time you could mulligan and this card is in your hand, you may "
    "exile all the cards from your hand, then draw that many cards."
)


# ------------------------------------------------------------------ parse


def test_chancellor_of_the_tangle_parse():
    p = printing(CHANCELLOR)
    assert p.is_creature and (p.power, p.toughness) == (6, 7)
    assert p.keywords == frozenset({"reach", "vigilance"})
    assert p.opening_hand_action == RevealFromOpeningHand(
        AddManaToPool(produces=(("G", 1),))
    )
    assert p.opening_hand_action.timing == AFTER_KEEP


def test_serum_powder_parse():
    p = printing(POWDER)
    assert p.is_artifact
    assert p.opening_hand_action == ExchangeHandWhileMulliganing()
    assert p.opening_hand_action.timing == MULLIGAN_WINDOW
    (mana,) = p.activated_abilities
    assert mana.is_mana_ability


def test_pregame_line_grammar():
    assert parse_pregame_line(POWDER_LINE, "X") == ExchangeHandWhileMulliganing()
    assert parse_pregame_line(
        REVEAL_LINE.replace("add {G}", "draw a card"), "X"
    ).effect.__class__.__name__ == "DrawCards"
    # A targeted delayed effect has nobody to choose a target at setup.
    assert parse_pregame_line(
        REVEAL_LINE.replace("add {G}", "destroy target creature"), "X"
    ) is None
    assert parse_pregame_line(
        REVEAL_LINE.replace("add {G}", "frobnicate"), "X"
    ) is None
    assert parse_pregame_line("Flying", "X") is None


def test_two_pregame_lines_are_not_claimed():
    card = dict(roto_card(CHANCELLOR))
    card["oracle_text"] = f"{REVEAL_LINE}\n{POWDER_LINE}\nReach, vigilance"
    assert build_card_record(card) is None


def test_pregame_line_next_to_a_builder_owned_opening_hand_action():
    card = dict(roto_card(CHANCELLOR))

    def build(body):
        return replace(
            printing(CHANCELLOR), opening_hand_action=BeginGameOnBattlefield(),
        )

    assert build_with_p6_lines(card, build) is None


def test_lands_and_multiface_records_keep_their_lines():
    land = {"name": "L", "type_line": "Land", "oracle_text": POWDER_LINE}
    seen = []
    build_with_p6_lines(land, lambda c: seen.append(c) or None)
    assert seen[0]["oracle_text"] == POWDER_LINE


# ---------------------------------------------- Chancellor of the Tangle


def _game(deck0, deck1, a0, a1, *, starting=0, **kw):
    with roto_source(CHANCELLOR, POWDER):
        return setup_game(
            [a0, a1], decks=[deck0, deck1], seed=11,
            starting_player_idx=starting, **kw,
        )


def test_revealed_chancellor_adds_g_at_its_owners_first_main_phase():
    a0 = PregameAgent(yes_no=[True, False])
    state = _game(
        [CHANCELLOR] * 20, ["Island"] * 20, a0, PregameAgent(),
    )
    assert a0.prompts[0] == f"reveal {CHANCELLOR} from your opening hand"
    (entry,) = state.delayed_triggers
    revealed = next(c for c in state.players[0].hand if c.id == entry["source_id"])
    assert revealed.publicly_known_to == frozenset({0, 1})
    # Still in hand -- revealing isn't casting.
    assert revealed.zone is Zone.HAND
    run_step(state, Step.PRECOMBAT_MAIN)
    assert pool_colors(state, 0) == ["G"]
    assert state.delayed_triggers == []


def test_each_revealed_chancellor_adds_g():
    a0 = PregameAgent(yes_no=[True, True])
    state = _game([CHANCELLOR] * 20, ["Island"] * 20, a0, PregameAgent())
    assert len(state.delayed_triggers) == 2
    run_step(state, Step.PRECOMBAT_MAIN)
    assert pool_colors(state, 0) == ["G", "G"]


def test_chancellor_on_the_draw_waits_for_its_owners_turn():
    a1 = PregameAgent(yes_no=[True])
    state = _game(["Island"] * 20, [CHANCELLOR] * 20, PregameAgent(), a1)
    run_step(state, Step.PRECOMBAT_MAIN)  # P0's first main phase
    assert pool_colors(state, 1) == []
    assert len(state.delayed_triggers) == 1
    state.active_player_idx = 1
    run_step(state, Step.PRECOMBAT_MAIN)
    assert pool_colors(state, 1) == ["G"]


def test_declined_chancellor_schedules_nothing():
    a0 = PregameAgent()  # answers no
    state = _game([CHANCELLOR] * 20, ["Island"] * 20, a0, PregameAgent())
    assert len(a0.prompts) == 7
    assert state.delayed_triggers == []


# ------------------------------------------------------------ Serum Powder


def test_serum_powder_exchanges_the_hand_once():
    a0 = PregameAgent(yes_no=[True])
    deck0 = [POWDER] * 7 + ["Island"] * 30
    state = _game(deck0, ["Island"] * 20, a0, PregameAgent())
    p0 = state.players[0]
    assert len(p0.exile) == 7 and len(p0.hand) == 7
    assert any(c.printing.name == POWDER for c in p0.exile)
    assert all(c.zone is Zone.EXILE for c in p0.exile)
    # Not a mulligan: nothing goes to the bottom on keep.
    assert len(p0.library) == 37 - 14
    # The new hand may hold another Powder: offered again, declined.
    assert len(a0.prompts) == 1 + any(
        c.printing.name == POWDER for c in p0.hand
    )


def test_serum_powder_alongside_mulligans():
    """Exchange, then mulligan the new hand, then keep at one mulligan."""
    a0 = PregameAgent(yes_no=[True], mulligans=[True])
    deck0 = [POWDER] + ["Island"] * 40
    with roto_source(POWDER):
        # Find a seed whose opening hand holds the Powder.
        for seed in range(50):
            state = setup_game(
                [PregameAgent(), PregameAgent()],
                decks=[deck0, ["Island"] * 20], seed=seed,
                enable_mulligans=False,
            )
            if any(c.printing.name == POWDER for c in state.players[0].hand):
                break
        else:  # pragma: no cover
            pytest.fail("no seed puts the Powder in the opening hand")
        state = setup_game(
            [a0, PregameAgent()], decks=[deck0, ["Island"] * 20], seed=seed,
        )
    p0 = state.players[0]
    assert len(p0.exile) == 7
    assert len(p0.hand) == 6  # one mulligan -> one card bottomed
    assert len(p0.library) == 41 - 7 - 6


def test_serum_powder_not_offered_without_a_mulligan_window():
    a0 = PregameAgent(yes_no=[True])
    state = _game(
        [POWDER] * 20, ["Island"] * 20, a0, PregameAgent(),
        enable_mulligans=False,
    )
    assert a0.prompts == []
    assert state.players[0].exile == []
    # Nor at a forced keep.
    a0 = PregameAgent(yes_no=[True])
    state = _game(
        [POWDER] * 20, ["Island"] * 20, a0, PregameAgent(), max_mulligans=0,
    )
    assert a0.prompts == []


def test_serum_powder_declined_keeps_the_hand():
    a0 = PregameAgent(yes_no=[False])
    state = _game([POWDER] * 20, ["Island"] * 20, a0, PregameAgent())
    assert len(a0.prompts) == 1
    assert state.players[0].exile == []
    assert len(state.players[0].hand) == 7


def test_serum_powder_repeated_until_the_library_runs_dry():
    """A yes-always player with only Powders exchanges until the library
    can't refill the hand; the loop terminates."""
    a0 = PregameAgent(yes_no=[True] * 10)
    state = _game([POWDER] * 14, ["Island"] * 20, a0, PregameAgent())
    p0 = state.players[0]
    assert len(p0.exile) == 14 and p0.hand == [] and p0.library == []
