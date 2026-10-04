"""Meddling Wizard -- the Vintage Roto group's custom conspiracy.

"(Start the game with this conspiracy face up in the command zone.)
At the beginning of each game, after mulligans, your opponent reveals
their hand to you."

The card has no Scryfall record; its record is hand-authored in
``data/cube_roto_custom.json`` from the draft sheet's text. Covered
here: the authored record and its parse, the reveal (once, after the
mulligans, only to the Wizard's controller, both ways when both players
have one, nothing without one), how the revealed knowledge is kept or
dropped as those cards move, and that search's hidden-information
handling (determinization and ISMCTS information sets) uses it.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from mtg_bot.agents import RandomAgent
from mtg_bot.cards.parser.conspiracy_builder import _build_conspiracy_printing
from mtg_bot.cards.parser.roto_keywords import parse_conspiracy_rule_line
from mtg_bot.cards.pools import load_pool_cards, pool_custom_cards
from mtg_bot.cards.source import get_active_source
from mtg_bot.conspiracies import (
    OpponentRevealsHandAfterMulligans,
    reveal_hands_after_mulligans,
)
from mtg_bot.game import Zone, hide_hand_moved_into_library
from mtg_bot.search import Budget, HeuristicsConfig, MtgGameStateAdapter
from mtg_bot.search import RandomRolloutEvaluator
from mtg_bot.search.determinize import determinize, viewer_knows
from mtg_bot.search.info_set import info_set_key
from mtg_bot.search.ismcts import ISMCTS
from mtg_bot.search.pimc import PIMC
from mtg_bot.simulate import setup_game
from tests._roto_helpers import printing, roto_card
from tests._roto_p6_helpers import PregameAgent
from tests._test_decks import simple_test_decklist

WIZARD = "Meddling Wizard"
REVEAL_LINE = (
    "At the beginning of each game, after mulligans, your opponent "
    "reveals their hand to you."
)
_REPO = Path(__file__).resolve().parents[1]


def _deck(color: str = "G", *, wizard: bool = False) -> list[str]:
    return ([WIZARD] if wizard else []) + simple_test_decklist(color)


def _game(*, p0_wizard=False, p1_wizard=False, agents=None, seed=5, **kw):
    agents = agents or [PregameAgent(), PregameAgent()]
    return setup_game(
        agents,
        decks=[_deck("G", wizard=p0_wizard), _deck("R", wizard=p1_wizard)],
        seed=seed, **kw,
    )


def _known_to(cards, viewer: int) -> list[bool]:
    return [viewer in c.publicly_known_to for c in cards]


# ------------------------------------------------------- authored record


def test_record_is_authored_from_the_draft_sheet():
    """The record carries the sheet's rules sentence verbatim (the
    reminder is the printed conspiracy reminder, which the parser strips)
    and says where it came from; it is not a Scryfall record."""
    rec = roto_card(WIZARD)
    assert rec["custom_card"] is True
    assert rec["type_line"] == "Conspiracy" and rec["mana_cost"] == ""
    assert rec["oracle_text"].split("\n") == [
        "(Start the game with this conspiracy face up in the command zone.)",
        REVEAL_LINE,
    ]
    sheet = json.loads(
        (_REPO / "data" / "cube_roto.sheet.json").read_text(encoding="utf-8")
    )
    (row,) = [r for r in sheet if r["name"] == WIZARD]
    assert row["scryfall_name"] is None
    assert row["row"] == rec["custom_source"]["sheet_row"]
    assert row["custom_text"] == rec["custom_source"]["custom_text"]
    # The sheet's rules sentence (after its own reminder) is the record's.
    assert row["custom_text"].split(" / ", 1)[1] == REVEAL_LINE


def test_every_authored_custom_is_a_sheet_custom():
    """``data/cube_roto_custom.json`` only holds cards the draft sheet
    names without a Scryfall record -- never a stand-in for a real card."""
    authored = json.loads(
        (_REPO / "data" / "cube_roto_custom.json").read_text(encoding="utf-8")
    )
    meta = json.loads(
        (_REPO / "data" / "cube_roto.meta.json").read_text(encoding="utf-8")
    )
    sheet_customs = {c["name"] for c in meta["custom_cards_without_scryfall"]}
    scryfall = {
        c["name"] for c in json.loads(
            (_REPO / "data" / "cube_roto.json").read_text(encoding="utf-8")
        )
    }
    for rec in authored:
        assert rec["custom_card"] is True
        assert rec["name"] in sheet_customs
        assert rec["name"] not in scryfall


def test_only_unauthored_customs_are_listed_apart():
    names = [c["name"] for c in pool_custom_cards("roto")]
    assert WIZARD not in names
    assert names == [
        "Quanitity Over Quality", "I've Made a Huge Mistake", "ANOTHER HEAD?!",
    ]
    assert WIZARD in {c["name"] for c in load_pool_cards("roto")}


# ----------------------------------------------------------------- parse


def test_parses_as_a_conspiracy_with_the_reveal_rule():
    p = printing(WIZARD)
    assert p.is_conspiracy and not p.is_permanent
    assert p.conspiracy_rules == (OpponentRevealsHandAfterMulligans(),)
    assert p.mana_cost.total == 0
    assert OpponentRevealsHandAfterMulligans().describe() == (
        "after mulligans, your opponent reveals their hand to you"
    )


def test_rule_line_grammar():
    assert parse_conspiracy_rule_line(REVEAL_LINE) == (
        OpponentRevealsHandAfterMulligans()
    )
    assert parse_conspiracy_rule_line("  " + REVEAL_LINE + " ") == (
        OpponentRevealsHandAfterMulligans()
    )
    # A different reveal (or timing) is not this rule.
    assert parse_conspiracy_rule_line(
        "At the beginning of each game, your opponent reveals their hand "
        "to you."
    ) is None
    assert parse_conspiracy_rule_line(
        REVEAL_LINE.replace("reveals their hand", "reveals a card")
    ) is None
    # Reminder text alone is still no rule.
    bare = dict(roto_card(WIZARD), oracle_text=(
        "(Start the game with this conspiracy face up in the command zone.)"
    ))
    assert _build_conspiracy_printing(bare) is None


def test_meddling_wizard_is_in_the_default_source():
    printings = get_active_source().get_printings()
    assert WIZARD in printings
    assert printings[WIZARD].conspiracy_rules == (
        OpponentRevealsHandAfterMulligans(),
    )


# ------------------------------------------------------------ the reveal


def test_reveals_the_opponents_hand_to_the_wizards_controller_only():
    state = _game(p0_wizard=True)
    p0, p1 = state.players
    (wiz,) = p0.conspiracies
    assert wiz.printing.name == WIZARD and wiz.zone is Zone.COMMAND
    assert len(p1.hand) == 7
    assert all(_known_to(p1.hand, 0))
    # Only the hand: P1's library stays hidden from P0.
    assert not any(_known_to(p1.library, 0))
    # P1 learns nothing about P0's hand.
    assert not any(_known_to(p0.hand, 1))
    reveals = [line for line in state.log if "reveals their hand" in line]
    assert len(reveals) == 1
    assert reveals[0].startswith(f"P1 reveals their hand to P0 ({WIZARD})")


def test_no_wizard_no_reveal():
    state = _game()
    for p in state.players:
        assert all(not c.publicly_known_to for c in p.hand)
    assert not any("reveals their hand" in line for line in state.log)


def test_both_players_with_a_wizard_each_see_the_other_hand():
    state = _game(p0_wizard=True, p1_wizard=True)
    p0, p1 = state.players
    assert all(_known_to(p1.hand, 0)) and all(_known_to(p0.hand, 1))
    # Nobody is "revealed to" about their own cards.
    assert not any(_known_to(p0.hand, 0)) and not any(_known_to(p1.hand, 1))
    reveals = [line for line in state.log if "reveals their hand" in line]
    assert len(reveals) == 2


class _WatchingAgent(PregameAgent):
    """Records, at each of P1's mulligan decisions and at the bottoming,
    whether P0 already knew any card of the hand being decided on."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.known_at_decision: list[bool] = []

    def choose_mulligan(self, state, player_id, hand, mulls_taken):
        self.known_at_decision.append(any(_known_to(hand, 0)))
        return super().choose_mulligan(state, player_id, hand, mulls_taken)

    def choose_bottom(self, state, player_id, hand, n):
        self.known_at_decision.append(any(_known_to(hand, 0)))
        return super().choose_bottom(state, player_id, hand, n)


def test_reveal_is_after_the_mulligans():
    """P1 mulligans twice, then keeps and bottoms two: nothing is known
    while P1 decides, the reveal shows the kept five, and neither the
    earlier hands nor the bottomed cards (all in the library now)."""
    watcher = _WatchingAgent(mulligans=[True, True])
    state = _game(p0_wizard=True, agents=[PregameAgent(), watcher])
    p1 = state.players[1]
    # Two mulligans, the keep, the bottoming.
    assert watcher.known_at_decision == [False, False, False, False]
    assert len(p1.hand) == 5
    assert all(_known_to(p1.hand, 0))
    assert not any(_known_to(p1.library, 0))


def test_reveal_happens_once_per_game(monkeypatch):
    import mtg_bot.simulate as simulate

    calls = []
    real = simulate.reveal_hands_after_mulligans

    def spy(state, starting_idx):
        calls.append(starting_idx)
        real(state, starting_idx)

    monkeypatch.setattr(simulate, "reveal_hands_after_mulligans", spy)
    agents = [PregameAgent(mulligans=[True]), PregameAgent(mulligans=[True])]
    state = _game(p0_wizard=True, agents=agents)
    assert calls == [0]
    # Cards drawn later were never revealed.
    from mtg_bot.turn import draw_card

    p1 = state.players[1]
    draw_card(state, 1)
    assert 0 not in p1.hand[-1].publicly_known_to


def test_reveal_without_mulligans_enabled_still_happens():
    state = _game(p0_wizard=True, enable_mulligans=False)
    assert all(_known_to(state.players[1].hand, 0))


def test_reveal_precedes_opening_hand_actions():
    """The reveal is the first thing after the mulligans: a card the
    opponent then puts onto the battlefield from their opening hand
    (Gemstone Caverns) was revealed while in hand and is public after."""
    caverns = "Gemstone Caverns"
    agents = [PregameAgent(), PregameAgent(yes_no=[True])]
    state = setup_game(
        agents,
        decks=[_deck("G", wizard=True), [caverns] * 30],
        seed=3, starting_player_idx=0,
    )
    p1 = state.players[1]
    on_field = [o for o in state.battlefield if o.printing.name == caverns]
    assert on_field and on_field[0].controller_id == 1
    reveal_at = next(
        i for i, line in enumerate(state.log) if "reveals their hand" in line
    )
    begin_at = next(
        i for i, line in enumerate(state.log) if "begins the game with" in line
    )
    assert reveal_at < begin_at
    assert all(_known_to(p1.hand, 0))


def test_reveal_skips_a_player_who_has_lost():
    state = _game(p0_wizard=True)
    p1 = state.players[1]
    for c in p1.hand:
        c.publicly_known_to = frozenset()
    p1.has_lost = True
    reveal_hands_after_mulligans(state, 0)
    assert not any(_known_to(p1.hand, 0))


# ------------------------------------------- knowledge as the cards move


def _wizard_state():
    """P0 has the Wizard; P1's opening hand is known to P0."""
    state = _game(p0_wizard=True)
    assert all(_known_to(state.players[1].hand, 0))
    return state


def test_played_or_discarded_cards_are_public_and_the_rest_stay_known():
    from mtg_bot.actions import put_into_battlefield
    from mtg_bot.effects.generic import DiscardSelf

    state = _wizard_state()
    p1 = state.players[1]
    # Discarded (P1's agent discards the last card): the graveyard is public.
    discarded = p1.hand[-1]
    DiscardSelf().resolve(state, 1)
    assert discarded in p1.graveyard and viewer_knows(discarded, 0)
    # Played onto the battlefield: public too.
    played = p1.hand[0]
    p1.hand.remove(played)
    put_into_battlefield(state, played, 1)
    assert played in state.battlefield and viewer_knows(played, 0)
    # The cards still in hand stay known; a determinized world keeps all
    # of them where they are.
    assert p1.hand and all(_known_to(p1.hand, 0))
    world = determinize(state, 0, random.Random(3))
    assert _names(world.players[1].hand) == _names(p1.hand)


def test_shuffling_the_hand_away_forgets_it():
    from mtg_bot.effects.generic.card_flow import (
        EachPlayerShufflesZonesIntoLibrary,
    )

    state = _wizard_state()
    p1 = state.players[1]
    hand = list(p1.hand)
    EachPlayerShufflesZonesIntoLibrary(zones=("hand",)).resolve(state, 0)
    assert not p1.hand
    assert all(c.zone is Zone.LIBRARY for c in hand)
    assert not any(_known_to(hand, 0))


def test_jace_shuffling_target_hand_in_forgets_it():
    """Jace, the Mind Sculptor's -12 shuffles the target's hand into
    their library; the shuffle must forget what was known."""
    from mtg_bot.effects.generic.cube_walkers import (
        ExileTargetPlayersLibraryThenShuffleHandIn,
    )

    state = _wizard_state()
    p1 = state.players[1]
    hand = list(p1.hand)
    ExileTargetPlayersLibraryThenShuffleHandIn().resolve(
        state, 0, (("player", 1),),
    )
    assert sorted(c.id for c in p1.library) == sorted(c.id for c in hand)
    assert not any(_known_to(p1.library, 0))


def test_putting_cards_back_from_hand_forgets_the_whole_hand():
    """Brainstorm's put-back: P0 can't tell which of P1's cards went on
    top, so neither the moved cards nor the ones left in hand stay
    known."""
    from mtg_bot.effects.generic.cube_walkers import (
        PutCardsFromHandOnTopOfLibrary,
    )

    state = _wizard_state()
    p1 = state.players[1]
    hand = list(p1.hand)
    p1.agent = None  # mandatory picks fall back to the first card
    PutCardsFromHandOnTopOfLibrary(amount=2).resolve(state, 1)
    moved, kept = hand[:2], hand[2:]
    assert p1.library[:2] == list(reversed(moved))
    assert not any(_known_to(moved, 0))
    assert not any(_known_to(kept, 0))
    assert not any(_known_to(p1.hand, 0))


def test_scroll_rack_forgets_the_whole_hand():
    from mtg_bot.effects.generic.roto_zones import ScrollRackSwap

    from tests._cube_artifact_helpers import ScriptedAgent

    state = _wizard_state()
    p1 = state.players[1]
    hand = list(p1.hand)
    picks = [hand[0].id]

    class _Rack(ScriptedAgent):
        def choose_card_from_hand(self, st, pid, option_ids):
            return picks.pop(0) if picks else None

    p1.agent = _Rack()
    ScrollRackSwap().resolve(state, 1)
    assert p1.library[0] is hand[0]
    assert not any(_known_to(hand, 0))
    assert not any(_known_to(p1.hand, 0))


def test_hide_hand_moved_into_library_keeps_the_owners_own_knowledge():
    state = _wizard_state()
    p1 = state.players[1]
    moved = p1.hand[0]
    moved.publicly_known_to = frozenset({0, 1})
    p1.hand.remove(moved)
    moved.zone = Zone.LIBRARY
    p1.library.insert(0, moved)
    hide_hand_moved_into_library(state, 1, [moved])
    assert moved.publicly_known_to == frozenset({1})
    assert not any(_known_to(p1.hand, 0))


# ------------------------------------------------- search uses the reveal


def _names(cards):
    return [c.printing.name for c in cards]


def test_determinization_keeps_the_revealed_hand():
    state = _wizard_state()
    truth = _names(state.players[1].hand)
    worlds = [
        determinize(state, 0, random.Random(seed)) for seed in range(20)
    ]
    assert all(_names(w.players[1].hand) == truth for w in worlds)
    # The library is still sampled (its order is unknown to P0).
    lib_truth = _names(state.players[1].library)
    assert any(_names(w.players[1].library) != lib_truth for w in worlds)


def test_without_the_wizard_the_opponents_hand_is_sampled():
    state = _game()
    truth = _names(state.players[1].hand)
    worlds = [
        determinize(state, 0, random.Random(seed)) for seed in range(20)
    ]
    assert any(_names(w.players[1].hand) != truth for w in worlds)


def test_only_cards_still_known_are_pinned_after_a_draw():
    from mtg_bot.turn import draw_card

    state = _wizard_state()
    p1 = state.players[1]
    revealed = list(p1.hand)
    draw_card(state, 1)
    fresh = p1.hand[-1]
    assert fresh not in revealed
    worlds = [determinize(state, 0, random.Random(s)) for s in range(30)]
    for w in worlds:
        by_id = {c.id: c for c in w.players[1].hand}
        for c in revealed:
            assert by_id[c.id].printing.name == c.printing.name
    # The drawn card is unknown: some world gives it another identity.
    assert any(
        {c.id: c for c in w.players[1].hand}[fresh.id].printing.name
        != fresh.printing.name
        for w in worlds
    )


def _swap_hand_with_library(state, pid):
    """A god-view state P0 can't tell apart without the reveal: one of
    P1's hand cards trades identity with a different library card."""
    clone = state.clone()
    p = clone.players[pid]
    h = p.hand[0]
    other = next(c for c in p.library if c.printing.name != h.printing.name)
    h.printing, other.printing = other.printing, h.printing
    return clone


def test_information_set_distinguishes_revealed_hands():
    with_wizard = _wizard_state()
    swapped = _swap_hand_with_library(with_wizard, 1)
    assert info_set_key(with_wizard, 0) != info_set_key(swapped, 0)
    without = _game()
    swapped = _swap_hand_with_library(without, 1)
    assert info_set_key(without, 0) == info_set_key(swapped, 0)


def _adapter_at_decision_of(state, pid):
    adapter = MtgGameStateAdapter(state, heuristics=HeuristicsConfig.disabled())
    for _ in range(200):
        if adapter.is_terminal():
            break
        legal = adapter.legal_decisions()
        if adapter.active_player() == pid and len(legal) > 1:
            return adapter
        adapter.apply(legal[0])
    pytest.fail(f"no multi-action decision for P{pid}")


def _recording(store):
    def det(engine_state, viewer_id, rng, *, in_place=False):
        world = determinize(engine_state, viewer_id, rng, in_place=in_place)
        store.append((viewer_id, world.players[1 - viewer_id].hand))
        return world

    return det


def _revealed_still_in_hand(state, viewer):
    opp = state.players[1 - viewer]
    return {c.id: c.printing.name for c in opp.hand
            if viewer in c.publicly_known_to}


def test_ismcts_searches_worlds_with_the_revealed_hand():
    state = _game(p0_wizard=True, agents=[RandomAgent(), RandomAgent()])
    adapter = _adapter_at_decision_of(state, 0)
    known = _revealed_still_in_hand(adapter.engine_state, 0)
    assert known, "the revealed cards are still in P1's hand"
    worlds = []
    ismcts = ISMCTS(
        evaluator=RandomRolloutEvaluator(rng=random.Random(0)),
        budget_factory=lambda: Budget(max_nodes=12),
        rng=random.Random(1), determinize_fn=_recording(worlds), puct=False,
    )
    ismcts.choose_with_visits(adapter, 0)
    assert len(worlds) == 12
    for viewer, hand in worlds:
        assert viewer == 0
        by_id = {c.id: c.printing.name for c in hand}
        assert all(by_id[i] == name for i, name in known.items())


def test_pimc_searches_worlds_with_the_revealed_hand():
    from mtg_bot.search import MCTS

    state = _game(p0_wizard=True, agents=[RandomAgent(), RandomAgent()])
    adapter = _adapter_at_decision_of(state, 0)
    known = _revealed_still_in_hand(adapter.engine_state, 0)
    worlds = []
    pimc = PIMC(
        inner_factory=lambda: MCTS(
            evaluator=RandomRolloutEvaluator(rng=random.Random(0)),
            budget_factory=lambda: Budget(max_nodes=4),
        ),
        samples=4, rng=random.Random(2), determinize_fn=_recording(worlds),
    )
    pimc.choose_with_visits(adapter, 0)
    assert len(worlds) == 4
    for _, hand in worlds:
        by_id = {c.id: c.printing.name for c in hand}
        assert all(by_id[i] == name for i, name in known.items())
