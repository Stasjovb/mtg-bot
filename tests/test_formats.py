"""``mtg_bot.formats``: the GameFormat data and its helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mtg_bot.formats import (
    FORGETFUL_FISH,
    FORMATS,
    STANDARD,
    GameFormat,
    apply_hand_ownership,
    get_format,
)


def _card(is_land: bool, owner: int = 0):
    return SimpleNamespace(
        printing=SimpleNamespace(is_land=is_land),
        owner_id=owner, controller_id=owner,
    )


def _hand(n_lands: int, size: int = 7):
    return [_card(i < n_lands) for i in range(size)]


def test_standard_is_the_plain_game():
    assert STANDARD.name == "standard"
    assert not STANDARD.shared_library
    assert not STANDARD.shared_graveyard
    assert not STANDARD.shares_zones
    assert STANDARD.starting_life == 20
    assert not STANDARD.holder_owns_hand_cards
    assert STANDARD.free_mulligan_land_bounds is None


def test_forgetful_fish_shares_library_and_graveyard():
    assert FORGETFUL_FISH.shared_library
    assert FORGETFUL_FISH.shared_graveyard
    assert FORGETFUL_FISH.shares_zones
    assert FORGETFUL_FISH.holder_owns_hand_cards
    assert FORGETFUL_FISH.free_mulligan_land_bounds == (2, 5)
    assert FORGETFUL_FISH.starting_life == 20


def test_shares_zones_with_only_a_shared_graveyard():
    assert GameFormat(name="x", shared_graveyard=True).shares_zones


def test_get_format_by_name():
    assert get_format("standard") is STANDARD
    assert get_format("forgetful_fish") is FORGETFUL_FISH
    assert set(FORMATS) == {"standard", "forgetful_fish"}


def test_get_format_unknown_name_raises():
    with pytest.raises(ValueError, match="unknown game format 'nope'"):
        get_format("nope")


@pytest.mark.parametrize(
    "n_lands, free", [(0, True), (1, True), (2, False), (5, False),
                      (6, True), (7, True)],
)
def test_fish_free_mulligan_outside_two_to_five_lands(n_lands, free):
    assert FORGETFUL_FISH.is_free_mulligan(_hand(n_lands)) is free


@pytest.mark.parametrize("n_lands", [0, 1, 6, 7])
@pytest.mark.parametrize("regular", [1, 2])
def test_fish_free_mulligan_ends_after_a_regular_mulligan(n_lands, regular):
    # Wizards' Dandân rule: no free mulligan once a regular one was taken.
    assert FORGETFUL_FISH.is_free_mulligan(_hand(n_lands), regular) is False
    assert FORGETFUL_FISH.is_free_mulligan(_hand(n_lands), 0) is True


@pytest.mark.parametrize("n_lands", range(8))
def test_standard_mulligans_are_never_free(n_lands):
    assert STANDARD.is_free_mulligan(_hand(n_lands)) is False


def test_free_mulligan_of_an_empty_hand():
    # Zero lands < 2: free (setup never offers an empty hand, but the
    # rule itself is total).
    assert FORGETFUL_FISH.is_free_mulligan([]) is True


def _state(fmt, hands):
    return SimpleNamespace(
        game_format=fmt,
        players=[SimpleNamespace(id=i, hand=h) for i, h in enumerate(hands)],
    )


def test_apply_hand_ownership_gives_hand_cards_to_the_holder():
    a, b = _card(False, owner=0), _card(True, owner=0)
    state = _state(FORGETFUL_FISH, [[a], [b]])
    apply_hand_ownership(state)
    assert (a.owner_id, a.controller_id) == (0, 0)
    assert (b.owner_id, b.controller_id) == (1, 1)


def test_apply_hand_ownership_is_a_noop_in_standard():
    b = _card(True, owner=0)
    state = _state(STANDARD, [[], [b]])
    apply_hand_ownership(state)
    assert (b.owner_id, b.controller_id) == (0, 0)
