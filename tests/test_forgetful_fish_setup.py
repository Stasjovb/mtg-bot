"""Forgetful Fish game setup: one shared library + graveyard, kept shared
through clones; drawer ownership; free mulligans."""

from __future__ import annotations

import pytest

from mtg_bot.agents import RandomAgent
from mtg_bot.effects.generic.roto_mana import CardsNamedInAllGraveyards
from mtg_bot.formats import FORGETFUL_FISH, STANDARD
from mtg_bot.game import Zone
from mtg_bot.simulate import MAX_FREE_MULLIGANS, setup_game, simulate_game
from mtg_bot.turn import draw_card, state_based_actions

# Cards every default-pool test fixture has; 80 cards like a Fish deck.
FISH_LIKE = ["Island"] * 40 + ["Brainstorm"] * 20 + ["Memory Lapse"] * 20


def _fish(seed=0, agents=None, **kw):
    return setup_game(
        agents or [RandomAgent(), RandomAgent()], decks=[FISH_LIKE],
        seed=seed, game_format=FORGETFUL_FISH, **kw,
    )


def _all_cards(state):
    seen = {}
    for zone in (*state.distinct_libraries(), *state.distinct_graveyards()):
        for c in zone:
            seen[c.id] = c
    for p in state.players:
        for c in (*p.hand, *p.exile):
            seen[c.id] = c
    for c in state.battlefield:
        seen[c.id] = c
    for item in state.stack:
        seen[item.source.id] = item.source
    return seen


def _assert_shared(state):
    p0, p1 = state.players
    assert p0.library is p1.library
    assert p0.graveyard is p1.graveyard
    assert p0.exile is not p1.exile
    assert p0.hand is not p1.hand


def test_setup_shares_one_library_and_graveyard():
    state = _fish()
    _assert_shared(state)
    assert state.game_format is FORGETFUL_FISH
    assert len(state.players[0].library) == 80 - 14
    assert [len(p.hand) for p in state.players] == [7, 7]
    assert len(_all_cards(state)) == 80


def test_distinct_zones_list_a_shared_zone_once():
    state = _fish()
    assert state.distinct_libraries() == [state.players[0].library]
    assert state.distinct_graveyards() == [state.players[0].graveyard]
    assert state.distinct_libraries()[0] is state.players[1].library


def test_distinct_zones_in_a_standard_game_list_each_player():
    state = setup_game(
        [RandomAgent(), RandomAgent()],
        decks=[["Island"] * 40, ["Island"] * 40], seed=0,
    )
    assert state.game_format is STANDARD
    p0, p1 = state.players
    assert p0.library is not p1.library
    assert [id(z) for z in state.distinct_libraries()] == [
        id(p0.library), id(p1.library),
    ]
    assert [id(z) for z in state.distinct_graveyards()] == [
        id(p0.graveyard), id(p1.graveyard),
    ]


def test_distinct_zones_of_an_empty_shared_state():
    from mtg_bot.game import GameState

    state = GameState()
    state.game_format = FORGETFUL_FISH
    assert state.distinct_libraries() == []
    assert state.distinct_graveyards() == []


def test_shared_library_needs_exactly_one_decklist():
    with pytest.raises(ValueError, match="pass exactly one decklist, got 2"):
        setup_game(
            [RandomAgent(), RandomAgent()], decks=[FISH_LIKE, FISH_LIKE],
            seed=0, game_format=FORGETFUL_FISH,
        )


def test_standard_still_needs_one_decklist_per_agent():
    with pytest.raises(ValueError, match="decks length 1 != agents length 2"):
        setup_game([RandomAgent(), RandomAgent()], decks=[FISH_LIKE], seed=0)


def test_cards_in_hand_are_owned_by_their_holder():
    state = _fish()
    for p in state.players:
        for c in p.hand:
            assert (c.owner_id, c.controller_id) == (p.id, p.id)


def test_draw_gives_the_card_to_the_drawer():
    state = _fish()
    top = state.players[1].library[0]
    assert top.owner_id == 0  # library cards start owned by player 0
    draw_card(state, 1)
    assert top in state.players[1].hand
    assert (top.owner_id, top.controller_id) == (1, 1)


def test_draw_in_a_standard_game_keeps_the_owner():
    state = setup_game(
        [RandomAgent(), RandomAgent()],
        decks=[["Island"] * 40, ["Island"] * 40], seed=0,
    )
    top = state.players[1].library[0]
    draw_card(state, 1)
    assert top.owner_id == 1


def test_state_based_actions_reapply_hand_ownership():
    state = _fish()
    card = state.players[0].library.pop(0)
    card.zone = Zone.HAND
    state.players[1].hand.append(card)  # reached a hand without a draw
    assert card.owner_id == 0
    state_based_actions(state)
    assert (card.owner_id, card.controller_id) == (1, 1)


def test_owners_graveyard_is_the_shared_graveyard():
    state = _fish()
    card = state.players[1].hand.pop()
    card.zone = Zone.GRAVEYARD
    state.players[card.owner_id].graveyard.append(card)
    assert card in state.players[0].graveyard
    assert card in state.players[1].graveyard


def test_all_graveyards_count_sees_the_shared_graveyard_once():
    state = _fish()
    for p in state.players:
        card = next(c for c in p.hand if c.printing.name == "Island")
        p.hand.remove(card)
        card.zone = Zone.GRAVEYARD
        p.graveyard.append(card)
    assert CardsNamedInAllGraveyards("Island").value(state, 0) == 2


def test_clone_keeps_the_zones_shared_on_both_sides():
    state = _fish()
    clone = state.clone()
    _assert_shared(state)
    _assert_shared(clone)
    assert clone.game_format is FORGETFUL_FISH
    assert state.players[0].library is not clone.players[0].library
    assert len(_all_cards(clone)) == 80


def test_clone_mutation_does_not_leak_into_the_source():
    state = _fish()
    clone = state.clone()
    before = [c.id for c in state.players[0].library]
    draw_card(clone, 1)
    assert len(clone.players[0].library) == len(before) - 1
    assert [c.id for c in state.players[1].library] == before
    _assert_shared(state)
    _assert_shared(clone)


def test_source_mutation_does_not_leak_into_the_clone():
    state = _fish()
    clone = state.clone()
    before = [c.id for c in clone.players[0].library]
    draw_card(state, 0)
    assert [c.id for c in clone.players[1].library] == before
    top = clone.players[0].library[0]
    assert top.zone == Zone.LIBRARY


def test_clone_of_a_clone_and_sibling_clones_stay_shared():
    state = _fish()
    a = state.clone()
    b = state.clone()
    aa = a.clone()
    for s in (state, a, b, aa):
        _assert_shared(s)
    draw_card(b, 0)
    draw_card(aa, 1)
    for s in (state, a, b, aa):
        _assert_shared(s)
    assert len(state.players[0].library) == 66
    assert len(a.players[0].library) == 66
    assert len(b.players[0].library) == 65
    assert len(aa.players[0].library) == 65


def test_clone_of_plain_list_zones_realiases_the_source():
    # A state whose shared zones are still plain lists (never cloned):
    # cloning promotes player 0's list to a copy-on-write list, and the
    # other player must follow it.
    state = _fish()
    assert type(state.players[0].library) is list
    state.clone()
    _assert_shared(state)
    assert type(state.players[1].library) is not list


def test_determinize_keeps_sharing_and_the_unknown_pool():
    from collections import Counter

    from mtg_bot.search.determinize import determinize

    state = _fish(seed=5)
    det = determinize(state, viewer_id=0, rng=__import__("random").Random(1))
    _assert_shared(det)
    _assert_shared(state)
    # The viewer's own hand is known and untouched.
    assert [c.printing.name for c in det.players[0].hand] == [
        c.printing.name for c in state.players[0].hand
    ]

    def pool(s):
        return Counter(
            c.printing.name
            for c in (*s.players[1].hand, *s.players[0].library)
        )

    # The opponent's hand + the shared library hold the same cards,
    # possibly in different places; the source state is unchanged.
    assert pool(det) == pool(state)
    assert len(_all_cards(det)) == 80


class _MulliganScript(RandomAgent):
    """Mulligans the first ``n`` offers, then keeps."""

    def __init__(self, n):
        super().__init__()
        self.n = n
        self.offers = []

    def choose_mulligan(self, state, player_id, hand, mulls_taken):
        self.offers.append(mulls_taken)
        return len(self.offers) <= self.n


def test_free_mulligan_bottoms_nothing():
    # All lands: every hand has 7 > 5 lands, so each mulligan is free.
    agent = _MulliganScript(2)
    keeper = _MulliganScript(0)
    state = setup_game(
        [agent, keeper], decks=[["Island"] * 80], seed=0,
        game_format=FORGETFUL_FISH,
    )
    assert agent.offers == [0, 0, 0]
    assert keeper.offers == [0]
    assert len(state.players[0].hand) == 7
    assert len(state.players[0].library) == 80 - 14
    assert any("takes a free mulligan" in line for line in state.log)


class _RecordingMulligan(RandomAgent):
    """Mulligans the first ``n`` offers, recording each offered hand's
    land count and ``mulls_taken``."""

    def __init__(self, n):
        super().__init__()
        self.n = n
        self.offers = []

    def choose_mulligan(self, state, player_id, hand, mulls_taken):
        lands = sum(c.printing.is_land for c in hand)
        self.offers.append((lands, mulls_taken))
        return len(self.offers) <= self.n


@pytest.mark.parametrize("seed", range(6))
def test_only_hands_with_two_to_five_lands_cost_a_card(seed):
    agent = _RecordingMulligan(3)
    state = setup_game(
        [agent, RandomAgent()], decks=[FISH_LIKE], seed=seed,
        game_format=FORGETFUL_FISH,
    )
    paid = 0
    for (lands, mulls_taken), (_, next_mulls) in zip(
        agent.offers, agent.offers[1:],
    ):
        assert mulls_taken == paid
        if 2 <= lands <= 5:
            paid += 1  # a London mulligan: one more card to bottom
        assert next_mulls == paid
    assert len(state.players[0].hand) == 7 - paid


def test_standard_mulligan_is_never_free():
    agent = _MulliganScript(1)
    state = setup_game(
        [agent, RandomAgent()], decks=[["Island"] * 40, ["Island"] * 40],
        seed=0,
    )
    assert agent.offers == [0, 1]
    assert len(state.players[0].hand) == 6


def test_free_mulligans_are_capped_so_setup_ends():
    agent = _MulliganScript(10**6)  # always mulligans
    state = setup_game(
        [agent, _MulliganScript(0)], decks=[["Island"] * 80], seed=0,
        game_format=FORGETFUL_FISH, max_mulligans=2,
    )
    # MAX_FREE_MULLIGANS free ones, then 2 paid (the cap forces a keep).
    assert agent.offers == [0] * (MAX_FREE_MULLIGANS + 1) + [1]
    assert len(state.players[0].hand) == 5


@pytest.mark.parametrize("seed", range(4))
def test_full_fish_game_keeps_zones_shared_and_cards_conserved(seed):
    state = simulate_game(
        decks=[FISH_LIKE], seed=seed, game_format=FORGETFUL_FISH,
        max_turns=60,
    )
    _assert_shared(state)
    assert len(_all_cards(state)) == 80


def test_simulate_game_fish_takes_named_agents():
    state = simulate_game(
        agents=[RandomAgent(), RandomAgent()], decks=[FISH_LIKE], seed=3,
        game_format=FORGETFUL_FISH, max_turns=30,
    )
    _assert_shared(state)
