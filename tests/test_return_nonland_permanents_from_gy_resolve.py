"""Engine-resolve tests for
``ReturnUpToNNonlandPermanentCardsFromGraveyardToHand``.

The parser-shape tests in ``test_parser_bespoke_spells3.py`` cover the
recognizer for Pull Through the Weft's first clause but no test exercises
the resolve path that walks ``targets`` and moves graveyard cards to the
controller's hand. These tests run the effect against synthetic graveyard
fixtures and verify happy-path returns plus the defensive branches (no
targets, wrong kind, missing card, deduped repeated ids)."""

from __future__ import annotations

from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.cards.base import make_creature
from mtg_bot.effects.generic import (
    ReturnUpToNNonlandPermanentCardsFromGraveyardToHand,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step


def _new_state():
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put_in_graveyard(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id=owner_id, zone=Zone.GRAVEYARD)
    state.players[owner_id].graveyard.append(obj)
    return obj


def test_resolve_returns_two_creature_cards_to_hand():
    state = _new_state()
    bear = _put_in_graveyard(state, SYNTHETIC_CREATURES["Wild Bear"])
    other = _put_in_graveyard(state, SYNTHETIC_CREATURES["Wild Bear"])
    pre_hand = len(state.players[0].hand)
    ReturnUpToNNonlandPermanentCardsFromGraveyardToHand(max_n=2).resolve(
        state, 0,
        (("graveyard_creature", bear.id), ("graveyard_creature", other.id)),
    )
    assert bear in state.players[0].hand
    assert other in state.players[0].hand
    assert bear.zone == Zone.HAND
    assert other.zone == Zone.HAND
    assert bear not in state.players[0].graveyard
    assert other not in state.players[0].graveyard
    assert len(state.players[0].hand) == pre_hand + 2


def test_resolve_no_targets_is_noop():
    state = _new_state()
    bear = _put_in_graveyard(state, SYNTHETIC_CREATURES["Wild Bear"])
    ReturnUpToNNonlandPermanentCardsFromGraveyardToHand().resolve(
        state, 0, (),
    )
    # Bear still in graveyard, hand still empty.
    assert bear in state.players[0].graveyard
    assert state.players[0].hand == []


def test_resolve_wrong_target_kind_is_skipped():
    state = _new_state()
    bear = _put_in_graveyard(state, SYNTHETIC_CREATURES["Wild Bear"])
    # Wrong kind ("creature" instead of "graveyard_creature") — the loop
    # skips it; no card is moved.
    ReturnUpToNNonlandPermanentCardsFromGraveyardToHand().resolve(
        state, 0, (("creature", bear.id),),
    )
    assert bear in state.players[0].graveyard
    assert bear not in state.players[0].hand


def test_resolve_dedupes_repeated_target_ids():
    """Two identical target tuples should only return one card."""
    state = _new_state()
    bear = _put_in_graveyard(state, SYNTHETIC_CREATURES["Wild Bear"])
    ReturnUpToNNonlandPermanentCardsFromGraveyardToHand().resolve(
        state, 0,
        (("graveyard_creature", bear.id), ("graveyard_creature", bear.id)),
    )
    # The card moves once; the second tuple hits the seen_ids dedupe.
    assert bear in state.players[0].hand
    assert bear not in state.players[0].graveyard


def test_resolve_missing_card_id_is_skipped():
    state = _new_state()
    bear = _put_in_graveyard(state, SYNTHETIC_CREATURES["Wild Bear"])
    # Bogus id alongside the real one — the bogus id silently skips.
    ReturnUpToNNonlandPermanentCardsFromGraveyardToHand().resolve(
        state, 0,
        (
            ("graveyard_creature", 999_999_999),
            ("graveyard_creature", bear.id),
        ),
    )
    assert bear in state.players[0].hand


def test_legal_targets_excludes_lands():
    """Lands in the graveyard are NOT legal targets; nonland permanents
    are."""
    state = _new_state()
    bear = _put_in_graveyard(state, SYNTHETIC_CREATURES["Wild Bear"])
    plains = _put_in_graveyard(state, BASIC_LANDS["Plains"])
    art = _put_in_graveyard(state, make_creature("Artifact Cre", "{1}", 1, 1))
    legal = ReturnUpToNNonlandPermanentCardsFromGraveyardToHand().legal_targets(
        state, 0,
    )
    target_ids = {tid for _, tid in legal}
    assert bear.id in target_ids
    assert art.id in target_ids
    assert plains.id not in target_ids


def test_target_count_range_uses_min_n_and_max_n():
    eff = ReturnUpToNNonlandPermanentCardsFromGraveyardToHand(min_n=1, max_n=3)
    assert eff.target_count_range() == (1, 3)


def test_describe_text():
    desc = ReturnUpToNNonlandPermanentCardsFromGraveyardToHand(max_n=2).describe()
    assert "up to 2" in desc
    assert "nonland permanent" in desc
    assert "graveyard" in desc


def test_requires_target_is_true():
    assert ReturnUpToNNonlandPermanentCardsFromGraveyardToHand().requires_target()
