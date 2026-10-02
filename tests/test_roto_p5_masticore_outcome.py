"""Vintage Roto P5: Argentum Masticore (sacrifice unless you discard,
with a reflexive destroy keyed on the discarded card's mana value) and
Paradoxical Outcome (any number of targets; draw per card returned to
your hand)."""

from __future__ import annotations

from mtg_bot.cards.parser.roto_board import parse_roto_board_effect
from mtg_bot.effects.generic.roto_board import (
    ANY_NUMBER_OF_TARGETS,
    ReturnAnyNumberDrawPerOwned,
    SacrificeSourceUnlessDiscard,
)
from mtg_bot.game import Zone, effective_keywords
from mtg_bot.turn import Step, run_beginning_of_upkeep_triggers

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


def _upkeep(state, pid=0):
    state.active_player_idx = pid
    state.priority_player_idx = pid
    state.step = Step.UPKEEP
    run_beginning_of_upkeep_triggers(state)
    resolve_all(state)


def test_grammar():
    bare = parse_roto_board_effect("sacrifice this creature unless you discard a card")
    assert bare == SacrificeSourceUnlessDiscard()
    assert bare.describe() == "sacrifice this creature unless you discard a card"
    assert parse_roto_board_effect(
        "sacrifice this creature unless you discard a card. When you discard "
        "a card this way, destroy target gizmo with mana value less than or "
        "equal to the mana value of the discarded card"
    ) is None
    assert parse_roto_board_effect(
        "return any number of target gizmos you control to their owners' "
        "hands. Draw a card for each card returned to your hand this way"
    ) is None


def test_masticore_keywords():
    kws = printing("Argentum Masticore").keywords
    assert "first strike" in kws and "protection from multicolored" in kws


def test_masticore_discard_destroys_by_discarded_mana_value():
    state = make_state()
    master = place(state, 0, "Argentum Masticore")
    big = place(state, 0, vanilla(3, 3, name="Big Card", cost="{2}{G}"), Zone.HAND)
    two = place(state, 1, vanilla(2, 2, name="Two", cost="{1}{G}"))
    four = place(state, 1, vanilla(4, 4, name="Four", cost="{3}{G}"))
    mine = place(state, 0, vanilla(1, 1, name="Mine", cost="{G}"))
    land = place(state, 1, "Forest")
    script(state, 0, "discard", big.id)
    script(state, 0, "target", ("creature", two.id))
    _upkeep(state)
    assert big in state.players[0].graveyard
    assert master in state.battlefield
    assert two in state.players[1].graveyard
    assert four in state.battlefield and land in state.battlefield
    assert mine in state.battlefield
    assert "first strike" in effective_keywords(state, master)


def test_masticore_reflexive_only_offers_cheap_enough_opponent_permanents():
    state = make_state()
    place(state, 0, "Argentum Masticore")
    one = place(state, 0, vanilla(1, 1, name="One Drop", cost="{G}"), Zone.HAND)
    two = place(state, 1, vanilla(2, 2, name="Two", cost="{1}{G}"))
    script(state, 0, "discard", one.id)
    _upkeep(state)
    assert two in state.battlefield   # nothing at MV 1 or less to destroy


def test_masticore_declining_or_empty_hand_sacrifices_it():
    state = make_state()
    master = place(state, 0, "Argentum Masticore")
    _upkeep(state)                    # empty hand
    assert master in state.players[0].graveyard
    state2 = make_state()
    master2 = place(state2, 0, "Argentum Masticore")
    card = place(state2, 0, "Forest", Zone.HAND)
    script(state2, 0, "yes_no", False)
    _upkeep(state2)
    assert master2 in state2.players[0].graveyard
    assert card in state2.players[0].hand


def test_masticore_only_on_its_controllers_upkeep():
    state = make_state()
    master = place(state, 0, "Argentum Masticore")
    _upkeep(state, pid=1)
    assert master in state.battlefield


# ---------------------------------------------------------------------------
# Paradoxical Outcome
# ---------------------------------------------------------------------------


def test_paradoxical_outcome_returns_any_number_and_draws_per_own_card():
    state = make_state()
    lands(state, 0, "Island", 4)
    rock = place(state, 0, "Mox Pearl")
    bear = place(state, 0, vanilla(2, 2))
    stolen = place(state, 1, vanilla(2, 2, name="Stolen"))
    stolen.controller_id = 0          # controlled, owned by player 1
    land = place(state, 0, "Wasteland")
    for _ in range(3):
        place(state, 0, "Island", Zone.LIBRARY)
    outcome = place(state, 0, "Paradoxical Outcome", Zone.HAND)
    eff = outcome.printing.spell_effect
    assert isinstance(eff, ReturnAnyNumberDrawPerOwned)
    assert eff.target_count_range() == (0, ANY_NUMBER_OF_TARGETS)
    script(state, 0, "target", ("permanent", rock.id), ("creature", stolen.id),
           None)
    hand_before = len(state.players[0].hand)
    cast(state, 0, outcome)
    assert rock in state.players[0].hand
    assert stolen in state.players[1].hand
    assert bear in state.battlefield and land in state.battlefield
    # Outcome left the hand, Mox came back, one draw for the Mox only.
    assert len(state.players[0].hand) == hand_before - 1 + 1 + 1
    assert "draw a card for each" in eff.describe()


def test_paradoxical_outcome_with_no_targets_draws_nothing():
    state = make_state()
    lands(state, 0, "Island", 4)
    place(state, 0, "Island", Zone.LIBRARY)
    outcome = place(state, 0, "Paradoxical Outcome", Zone.HAND)
    script(state, 0, "target", None)
    cast(state, 0, outcome)
    assert len(state.players[0].library) == 1


def test_paradoxical_outcome_cannot_target_tokens_or_lands():
    from dataclasses import replace

    state = make_state()
    token = place(state, 0, replace(vanilla(1, 1, name="Token Guy"),
                                    supertypes=("Token",)))
    land = place(state, 0, "Forest")
    rock = place(state, 0, "Mox Pearl")
    eff = printing("Paradoxical Outcome").spell_effect
    legal = eff.legal_targets(state, 0)
    assert ("permanent", rock.id) in legal
    assert all(t[1] not in (token.id, land.id) for t in legal)
