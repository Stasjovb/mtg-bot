"""Vintage Roto P5: Veil of Summer -- draw if an opponent cast a blue or
black spell this turn, your spells can't be countered this turn, and
hexproof from blue and from black for you and your permanents."""

from __future__ import annotations

from mtg_bot.cards.parser.roto_board import parse_roto_board_effect
from mtg_bot.effects.generic.roto_board import (
    DrawIfOpponentCastColorThisTurn,
    YouAndPermanentsGainHexproofFromUEOT,
    YourSpellsCantBeCounteredThisTurn,
)
from mtg_bot.game import Zone
from mtg_bot.keyword_rules import can_be_targeted_by, filter_targetable
from mtg_bot.roto_board_statics import (
    player_hexproof_from_source,
    spell_colors_cast_this_turn,
    spells_uncounterable_now,
)
from mtg_bot.turn import run_cleanup_step

from tests._roto_p5_helpers import (
    cast,
    lands,
    make_state,
    place,
    printing,
    resolve_all,
    script,
    vanilla,
)


def test_grammar():
    assert parse_roto_board_effect(
        "draw a card if an opponent has cast a blue or black spell this turn"
    ) == DrawIfOpponentCastColorThisTurn(colors=frozenset({"U", "B"}), amount=1)
    assert parse_roto_board_effect(
        "draw two cards if an opponent has cast a red spell this turn"
    ).amount == 2
    assert parse_roto_board_effect(
        "spells you control can't be countered this turn"
    ) == YourSpellsCantBeCounteredThisTurn()
    assert parse_roto_board_effect(
        "you and permanents you control gain hexproof from white until end "
        "of turn"
    ) == YouAndPermanentsGainHexproofFromUEOT(qualities=frozenset({"white"}))
    eff = printing("Veil of Summer").spell_effect
    assert "draw 1" in eff.effects[0].describe()
    assert eff.effects[1].describe().startswith("spells you control")
    assert "hexproof from black and from blue" in eff.effects[2].describe()


def _opponent_casts(state, name, lands_name):
    state.active_player_idx = 1
    state.priority_player_idx = 1
    lands(state, 1, lands_name, 1)
    card = place(state, 1, name, Zone.HAND)
    script(state, 1, "target", ("player", 0))
    cast(state, 1, card)
    state.priority_player_idx = 0


def test_veil_draws_only_after_a_blue_or_black_spell():
    state = make_state()
    lands(state, 0, "Forest", 2)
    place(state, 0, "Island", Zone.LIBRARY)
    place(state, 0, "Island", Zone.LIBRARY)
    veil = place(state, 0, "Veil of Summer", Zone.HAND)
    cast(state, 0, veil)
    assert len(state.players[0].hand) == 0      # nobody cast anything
    _opponent_casts(state, "Dark Ritual", "Swamp")
    assert spell_colors_cast_this_turn(state, state.players[1]) == frozenset({"B"})
    veil2 = place(state, 0, "Veil of Summer", Zone.HAND)
    for land in state.battlefield:
        if land.controller_id == 0:
            land.tapped = False
    cast(state, 0, veil2)
    assert len(state.players[0].hand) == 1


def test_red_spell_does_not_count_and_the_record_is_per_turn():
    state = make_state()
    _opponent_casts(state, "Lightning Bolt", "Mountain")
    assert spell_colors_cast_this_turn(state, state.players[1]) == frozenset({"R"})
    lands(state, 0, "Forest", 1)
    place(state, 0, "Island", Zone.LIBRARY)
    cast(state, 0, place(state, 0, "Veil of Summer", Zone.HAND))
    assert len(state.players[0].hand) == 0
    state.turn_number += 1
    assert spell_colors_cast_this_turn(state, state.players[1]) == frozenset()


def test_veil_makes_your_spells_uncounterable_this_turn():
    state = make_state()
    lands(state, 0, "Forest", 1)
    cast(state, 0, place(state, 0, "Veil of Summer", Zone.HAND))
    assert spells_uncounterable_now(state, 0)
    assert not spells_uncounterable_now(state, 1)
    # A spell of player 0 on the stack is not a legal counter target.
    lands(state, 0, "Forest", 1)
    bear_card = place(state, 0, vanilla(2, 2, cost="{G}"), Zone.HAND)
    cast(state, 0, bear_card, resolve=False)
    counter = printing("Counterspell").spell_effect
    assert counter.legal_targets(state, 1) == []
    resolve_all(state)
    state.turn_number += 1
    assert not spells_uncounterable_now(state, 0)


def test_veil_hexproof_from_blue_and_black():
    state = make_state()
    lands(state, 0, "Forest", 1)
    bear = place(state, 0, vanilla(2, 2))
    cast(state, 0, place(state, 0, "Veil of Summer", Zone.HAND))
    blue_src = place(state, 1, vanilla(1, 1, name="Blue Thing", cost="{U}"))
    red_src = place(state, 1, vanilla(1, 1, name="Red Thing", cost="{R}"))
    assert not can_be_targeted_by(state, bear, blue_src, 1)
    assert can_be_targeted_by(state, bear, red_src, 1)
    assert can_be_targeted_by(state, bear, blue_src, 0)      # your own
    # The player too.
    assert player_hexproof_from_source(state, 0, blue_src, 1)
    assert not player_hexproof_from_source(state, 0, red_src, 1)
    assert not player_hexproof_from_source(state, 0, blue_src, 0)
    assert not player_hexproof_from_source(state, 0, None, 1)
    assert filter_targetable(state, [("player", 0)], blue_src, 1) == []
    assert filter_targetable(state, [("player", 0)], red_src, 1) == [("player", 0)]
    run_cleanup_step(state)
    state.turn_number += 1
    assert can_be_targeted_by(state, bear, blue_src, 1)
    assert not player_hexproof_from_source(state, 0, blue_src, 1)


def test_creatures_entering_after_veil_have_no_hexproof():
    state = make_state()
    lands(state, 0, "Forest", 1)
    cast(state, 0, place(state, 0, "Veil of Summer", Zone.HAND))
    late = place(state, 0, vanilla(2, 2, name="Late"))
    blue_src = place(state, 1, vanilla(1, 1, name="Blue Thing", cost="{U}"))
    assert can_be_targeted_by(state, late, blue_src, 1)


def test_red_removal_still_targets_after_veil():
    state = make_state()
    lands(state, 0, "Forest", 1)
    bear = place(state, 0, vanilla(2, 2))
    cast(state, 0, place(state, 0, "Veil of Summer", Zone.HAND))
    state.active_player_idx = 1
    state.priority_player_idx = 1
    lands(state, 1, "Mountain", 1)
    bolt = place(state, 1, "Lightning Bolt", Zone.HAND)
    script(state, 1, "target", ("creature", bear.id))
    cast(state, 1, bolt)                     # red: still allowed
    assert bear in state.players[0].graveyard
