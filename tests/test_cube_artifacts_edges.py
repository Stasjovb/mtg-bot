"""Edge-case coverage for the cube artifact-bucket primitives."""

from __future__ import annotations

from mtg_bot.cards import BASIC_LANDS, make_creature
from mtg_bot.cards.parser.effects import _parse_effect
from mtg_bot.effects.generic import (
    EachOpponentSacrificesN,
    LookAtTopCardOfTargetPlayersLibrary,
    MayExileThatCardFromYourGraveyard,
    ReturnExiledCardsAndDiscardHands,
    TargetOpponentMayLetYouDrawElseMill,
    UntapXTargets,
)
from mtg_bot.effects.object_predicates import IsLand
from mtg_bot.effects.targets import TargetSpec

from tests._cube_artifact_helpers import (
    agent,
    arena,
    build_ok,
    put,
    to_graveyard,
    to_library,
)


def test_untap_x_targets_skips_gone_and_filtered():
    state = arena()
    land = put(state, BASIC_LANDS["Island"], tapped=True)
    bear = put(state, make_creature("Bear", "{1}", 2, 2), tapped=True)
    eff = UntapXTargets(targets=(TargetSpec(IsLand(), 0, float("inf")),))
    eff.resolve(state, 0, (("permanent", 999), ("creature", bear.id),
                           ("permanent", land.id)))
    assert bear.tapped and not land.tapped


def test_look_at_top_card_forks_shared_library():
    state = arena()
    to_library(state, BASIC_LANDS["Island"], owner=1)
    clone = state.clone()
    LookAtTopCardOfTargetPlayersLibrary().resolve(clone, 0, (("player", 1),))
    assert 0 in clone.players[1].library[0].publicly_known_to
    # the sibling state's copy is unaffected
    assert 0 not in state.players[1].library[0].publicly_known_to


def test_return_exiled_skips_players_who_lost():
    state = arena()
    state.players[1].has_lost = True
    ReturnExiledCardsAndDiscardHands(card_ids=()).resolve(state, 0)


def test_each_opponent_sacrifices_non_creature_type():
    state = arena()
    lands = [put(state, BASIC_LANDS["Forest"], 1) for _ in range(3)]
    put(state, make_creature("Bear", "{1}", 2, 2), 1)
    state.players[1].agent = None
    EachOpponentSacrificesN(amount=2, card_type="Land").resolve(state, 0)
    assert sum(l in state.battlefield for l in lands) == 1


def test_palantir_mill_stops_on_empty_library():
    state = arena()
    pal = put(state, build_ok("Palantír of Orthanc"))
    pal.named_counters = (("influence", 5),)
    to_library(state, BASIC_LANDS["Island"])
    agent(state, 1).yes = False
    state.resolving_source = pal
    TargetOpponentMayLetYouDrawElseMill().resolve(state, 0, (("player", 1),))
    assert len(state.players[0].graveyard) == 1
    assert state.players[1].life == 20  # a land has mana value 0


def test_may_exile_that_card_rejects_non_graveyard_kind():
    state = arena()
    conv = put(state, build_ok("Currency Converter"))
    card = to_graveyard(state, BASIC_LANDS["Island"])
    state.resolving_source = conv
    MayExileThatCardFromYourGraveyard().resolve(state, 0, (("creature", card.id),))
    assert card in state.players[0].graveyard


def test_counter_condition_and_two_token_grammar_edges():
    assert _parse_effect(
        "if there are no charge counters on this Vehicle, frobnicate"
    ) is None
    # a token descriptor containing " and " still splits correctly
    eff = _parse_effect(
        "create a 1/1 colorless Thopter artifact creature token with flying "
        "and haste and a Treasure token"
    )
    assert eff is not None and len(eff.effects) == 2
    assert _parse_effect("create a Treasure token and a Wibble token") is None
