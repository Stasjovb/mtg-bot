"""Cube spells-B: card-flow grammar + engine behavior.

Covers the parser recognizers in ``cards/parser/card_flow_grammar.py``
and the engine effects in ``effects/generic/card_flow.py``: targeted
draw / extra turn, random and revealed-hand discard, tutors (hand /
graveyard / top / battlefield), Brainstorm put-back, look-at-top-N
selection, Ponder reorder + optional shuffle, scry with a real bottom
decision, wheels, Upheaval, Reprieve, Time Spiral's self-exile, and
multi-pip / any-combination mana.
"""

from __future__ import annotations

import pytest

from mtg_bot.actions import CastSpell, apply_action, resolve_top_of_stack
from mtg_bot.cards.base import AddManaToPool, DrawCards, LoseLife, Sequence
from mtg_bot.cards.parser.card_flow_grammar import (
    parse_card_descriptor,
    parse_card_flow_effect,
    parse_permanent_descriptor,
)
from mtg_bot.cards.parser.effects import _parse_effect, _parse_spell_effect_phrase
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.effects.formulas import (
    Constant,
    CountControlledMatching,
    ResolvingX,
    Scaled,
)
from mtg_bot.effects.generic.card_flow import (
    ANY_CARD,
    CardFilter,
    EachPlayerDiscardsHand,
    EachPlayerShufflesZonesIntoLibrary,
    ExileThisSpell,
    LookAtTargetPlayersHand,
    LookAtTopCardsPutIntoHand,
    PutCardsFromHandOnTopOfLibrary,
    ReorderTopCards,
    ReturnAllPermanentsToOwnersHands,
    ReturnTargetSpellToOwnersHand,
    SearchLibrary,
    ShuffleYourLibrary,
    TargetPlayerDiscardsAtRandom,
    TargetPlayerDraws,
    TargetPlayerRevealsHandYouChooseDiscard,
    TargetPlayerTakesExtraTurn,
    UntapUpToNLands,
)
from mtg_bot.effects.generic.library_lookat import Scry
from mtg_bot.effects.object_predicates import IsLand
from mtg_bot.game import StackItem, Zone
from tests._spells_b_helpers import (
    PRINTINGS,
    ScriptedAgent,
    add,
    add_lands,
    cast_and_resolve,
    make_state,
)


@pytest.fixture(scope="module")
def cube_printings():
    return OracleParserCardSource(pool="cube").get_printings()


# ---------------------------------------------------------------------
# Card descriptor grammar
# ---------------------------------------------------------------------


@pytest.mark.parametrize("text,expected", [
    ("a card", ANY_CARD),
    ("an artifact card", CardFilter(any_types=("Artifact",))),
    ("an instant or sorcery card", CardFilter(any_types=("Instant", "Sorcery"))),
    ("a green creature card", CardFilter(any_types=("Creature",), color="G")),
    ("a noncreature, nonland card",
     CardFilter(excluded_types=("Creature", "Land"))),
    ("a nonland card with mana value 3 or less",
     CardFilter(excluded_types=("Land",), max_mv=3)),
    ("a legendary creature card",
     CardFilter(any_types=("Creature",), supertype="Legendary")),
    ("a permanent card", CardFilter(any_types=("Permanent",))),
])
def test_parse_card_descriptor(text, expected):
    assert parse_card_descriptor(text) == expected


@pytest.mark.parametrize("text", [
    "a card of your choice", "the card", "a wizard card", "a blue green card",
    "a creature or wizard card",
])
def test_parse_card_descriptor_rejects(text):
    assert parse_card_descriptor(text) is None


def test_parse_permanent_descriptor():
    assert parse_permanent_descriptor("a land") == CardFilter(any_types=("Land",))
    assert parse_permanent_descriptor("a green creature") == CardFilter(
        any_types=("Creature",), color="G",
    )
    assert parse_permanent_descriptor("a land card") is None
    assert parse_permanent_descriptor("a green") is None
    assert parse_permanent_descriptor("some land") is None


def test_card_filter_matches_and_describe():
    bolt_like = PRINTINGS["Dark Ritual"]
    assert CardFilter(any_types=("Instant",)).matches(bolt_like)
    assert not CardFilter(any_types=("Sorcery",)).matches(bolt_like)
    assert not CardFilter(excluded_types=("Instant",)).matches(bolt_like)
    assert CardFilter(max_mv=1).matches(bolt_like)
    assert not CardFilter(max_mv=0).matches(bolt_like)
    assert CardFilter(color="B").matches(bolt_like)
    assert not CardFilter(color="U").matches(bolt_like)
    assert not CardFilter(supertype="Legendary").matches(bolt_like)
    assert CardFilter(any_types=("Permanent",)).matches(PRINTINGS["Forest"])
    assert not CardFilter(any_types=("Permanent",)).matches(bolt_like)
    assert ANY_CARD.has_quality is False
    assert CardFilter(max_mv=2).has_quality
    assert CardFilter(
        any_types=("Creature",), excluded_types=("Land",), color="G",
        supertype="Legendary", max_mv=3,
    ).describe() == (
        "legendary green nonland creature card with mana value 3 or less"
    )


# ---------------------------------------------------------------------
# Recognizers -> Effect shape
# ---------------------------------------------------------------------


@pytest.mark.parametrize("phrase,expected", [
    ("target player draws three cards", TargetPlayerDraws(amount=3)),
    ("target player draws a card", TargetPlayerDraws(amount=1)),
    ("target player draws X cards", TargetPlayerDraws(amount=ResolvingX())),
    ("target player takes an extra turn after this one",
     TargetPlayerTakesExtraTurn()),
    ("target player discards two cards at random",
     TargetPlayerDiscardsAtRandom(amount=2)),
    ("target player discards X cards at random",
     TargetPlayerDiscardsAtRandom(amount=ResolvingX())),
    ("put two cards from your hand on top of your library in any order",
     PutCardsFromHandOnTopOfLibrary(amount=2)),
    ("look at the top three cards of your library, then put them back "
     "in any order", ReorderTopCards(count=3)),
    ("you may shuffle", ShuffleYourLibrary(optional=True)),
    ("shuffle", ShuffleYourLibrary(optional=False)),
    ("untap up to three lands", UntapUpToNLands(amount=3)),
    ("you untap up to six lands", UntapUpToNLands(amount=6)),
    ("return all permanents to their owners' hands",
     ReturnAllPermanentsToOwnersHands()),
    ("return target spell to its owner's hand", ReturnTargetSpellToOwnersHand()),
    ("scry 2", Scry(amount=2, bottom_choice=True)),
    ("exile this spell", ExileThisSpell()),
    ("look at target player's hand", LookAtTargetPlayersHand()),
    ("add {B}{B}{B}", AddManaToPool(produces=(("B", 3),))),
    ("add {U}{U}{R}", AddManaToPool(produces=(("U", 2), ("R", 1)))),
    ("add two mana in any combination of colors",
     AddManaToPool(produces=(("any", 2),))),
])
def test_card_flow_recognizers(phrase, expected):
    assert parse_card_flow_effect(phrase) == expected


@pytest.mark.parametrize("phrase", [
    "put X cards from your hand on top of your library in any order",
    "look at the top X cards of your library, then put them back in any order",
    "untap up to X lands",
    "add X mana in any combination of colors",
    "each player discards their hand, then draws X cards",
    "target player reveals their hand. You choose a wizard card from it. "
    "That player discards that card",
    "search your library for a wizard card, put it into your hand, then shuffle",
    "search your library for a wizard card, then shuffle and put that card on top",
    "look at the top five cards of your library. Put X of them into your "
    "hand and the rest on the bottom of your library in any order",
    "look at the top five cards of your library. You may put a wizard card "
    "from among them into your hand. Put the rest into your graveyard",
    "look at the top five cards of your library. Do something else",
    "look at the top X cards of your library, where X is your life total. "
    "Put one of them into your hand and the rest on the bottom of your "
    "library in a random order",
    "look at the top X cards of your library. Put one of them into your "
    "hand and the rest on the bottom of your library in a random order",
    "target player reveals their hand. You choose a nonland card from it. "
    "That player discards that card. Frobnicate the widget",
])
def test_card_flow_recognizers_reject(phrase):
    assert parse_card_flow_effect(phrase) is None


def test_reveal_hand_shapes():
    assert parse_card_flow_effect(
        "target opponent reveals their hand. You choose a noncreature, "
        "nonland card from it. That player discards that card"
    ) == TargetPlayerRevealsHandYouChooseDiscard(
        card_filter=CardFilter(excluded_types=("Creature", "Land")),
        opponent_only=True,
    )
    assert parse_card_flow_effect(
        "target player reveals their hand. You choose a nonland card from "
        "it with mana value 3 or less. That player discards that card"
    ) == TargetPlayerRevealsHandYouChooseDiscard(
        card_filter=CardFilter(excluded_types=("Land",), max_mv=3),
    )
    # Trailing sentence parsed recursively (Thoughtseize).
    assert parse_card_flow_effect(
        "target player reveals their hand. You choose a nonland card from "
        "it. That player discards that card. You lose 2 life"
    ) == Sequence(effects=(
        TargetPlayerRevealsHandYouChooseDiscard(
            card_filter=CardFilter(excluded_types=("Land",)),
        ),
        LoseLife(amount=2),
    ))


def test_search_shapes():
    assert parse_card_flow_effect(
        "search your library for a card, put that card into your hand, "
        "then shuffle"
    ) == SearchLibrary(card_filter=ANY_CARD, destination="hand")
    assert parse_card_flow_effect(
        "search your library for a card, put that card into your "
        "graveyard, then shuffle"
    ) == SearchLibrary(card_filter=ANY_CARD, destination="graveyard")
    assert parse_card_flow_effect(
        "search your library for a green creature card, put it onto the "
        "battlefield, then shuffle"
    ) == SearchLibrary(
        card_filter=CardFilter(any_types=("Creature",), color="G"),
        destination="battlefield",
    )
    assert parse_card_flow_effect(
        "search your library for an instant or sorcery card, reveal it, "
        "then shuffle and put that card on top"
    ) == SearchLibrary(
        card_filter=CardFilter(any_types=("Instant", "Sorcery")),
        destination="top", reveal=True,
    )


def test_look_top_n_shapes():
    assert parse_card_flow_effect(
        "look at the top five cards of your library. Put two of them into "
        "your hand and the rest on the bottom of your library in any order"
    ) == LookAtTopCardsPutIntoHand(count=5, take=2)
    assert parse_card_flow_effect(
        "look at the top X cards of your library, where X is twice the "
        "number of lands you control. Put one of them into your hand and "
        "the rest on the bottom of your library in a random order"
    ) == LookAtTopCardsPutIntoHand(
        count=Scaled(inner=CountControlledMatching(IsLand()), factor=2),
        take=1, rest_random=True,
    )
    assert parse_card_flow_effect(
        "look at the top five cards of your library. You may reveal a "
        "creature or land card from among them and put it into your hand. "
        "Put the rest on the bottom of your library in a random order"
    ) == LookAtTopCardsPutIntoHand(
        count=5, take=1,
        take_filter=CardFilter(any_types=("Creature", "Land")),
        optional=True, reveal_taken=True, rest_random=True,
    )
    assert parse_card_flow_effect(
        "reveal the top four cards of your library. You may put a permanent "
        "card from among them into your hand. Put the rest into your "
        "graveyard. Draw a card"
    ) == Sequence(effects=(
        LookAtTopCardsPutIntoHand(
            count=4, take=1, take_filter=CardFilter(any_types=("Permanent",)),
            optional=True, reveal=True, rest_zone="graveyard",
        ),
        DrawCards(amount=1),
    ))
    assert parse_card_flow_effect(
        "look at the top three cards of your library. Put one of them into "
        "your hand and the rest into your graveyard"
    ) == LookAtTopCardsPutIntoHand(count=3, take=1, rest_zone="graveyard")


def test_wheel_shapes():
    from mtg_bot.cards.base import EachPlayerDraws

    assert parse_card_flow_effect(
        "each player discards their hand, then draws seven cards"
    ) == Sequence(effects=(EachPlayerDiscardsHand(), EachPlayerDraws(amount=7)))
    assert parse_card_flow_effect(
        "each player shuffles their hand and graveyard into their library, "
        "then draws seven cards"
    ) == Sequence(effects=(
        EachPlayerShufflesZonesIntoLibrary(zones=("hand", "graveyard")),
        EachPlayerDraws(amount=7),
    ))


def test_exile_self_name_normalization():
    assert _parse_spell_effect_phrase(
        "Exile Time Spiral.", "Time Spiral",
    ) == ExileThisSpell()


def test_card_flow_grammar_is_reachable_from_parse_effect():
    assert _parse_effect("target player draws three cards") == TargetPlayerDraws(3)


# ---------------------------------------------------------------------
# Claims (end-to-end via the cube parser source)
# ---------------------------------------------------------------------


_CLAIMED = [
    "Ancestral Recall", "Brainstorm", "Dark Ritual", "Demonic Tutor",
    "Duress", "Enlightened Tutor", "Entomb", "Frantic Search",
    "Hymn to Tourach", "Imperial Seal", "Inquisition of Kozilek",
    "Manamorphose", "Mind Twist", "Mystical Tutor", "Ponder", "Preordain",
    "Reprieve", "Stock Up", "Thoughtseize", "Time Spiral", "Time Warp",
    "Timetwister", "Upheaval", "Vampiric Tutor", "Wheel of Fortune",
    "Worldly Tutor",
]


@pytest.mark.parametrize("name", _CLAIMED)
def test_card_is_claimed(cube_printings, name):
    assert name in cube_printings


def test_phyrexian_mana_spell_stays_unclaimed(cube_printings):
    # {U/P} has no life-payment path in the engine.
    assert "Gitaxian Probe" not in cube_printings


def test_claimed_shapes(cube_printings):
    assert cube_printings["Ancestral Recall"].spell_effect == TargetPlayerDraws(3)
    assert cube_printings["Dark Ritual"].spell_effect == AddManaToPool(
        produces=(("B", 3),),
    )
    assert cube_printings["Mind Twist"].spell_effect == (
        TargetPlayerDiscardsAtRandom(amount=ResolvingX())
    )
    assert cube_printings["Ponder"].spell_effect == Sequence(effects=(
        ReorderTopCards(count=3), ShuffleYourLibrary(optional=True),
        DrawCards(amount=1),
    ))
    assert cube_printings["Preordain"].spell_effect == Sequence(effects=(
        Scry(amount=2, bottom_choice=True), DrawCards(amount=1),
    ))
    assert cube_printings["Vampiric Tutor"].spell_effect == Sequence(effects=(
        SearchLibrary(card_filter=ANY_CARD, destination="top"),
        LoseLife(amount=2),
    ))


# ---------------------------------------------------------------------
# Engine behavior
# ---------------------------------------------------------------------


def _library(state, pid, names):
    return [add(state, pid, n, Zone.LIBRARY) for n in names]


def test_ancestral_recall_targets_either_player():
    state = make_state(agent0=ScriptedAgent(target=[("player", 1)]))
    _library(state, 1, ["Island"] * 4)
    card = add(state, 0, "Ancestral Recall", Zone.HAND)
    add_lands(state, 0, "Island", 1)
    cast_and_resolve(state, 0, card)
    assert len(state.players[1].hand) == 3
    assert card in state.players[0].graveyard
    eff = TargetPlayerDraws(amount=Constant(2))
    assert eff.legal_targets(state, 0) == [("player", 0), ("player", 1)]
    eff.resolve(state, 0, (("player", 1),))
    assert len(state.players[1].hand) == 4
    # No / non-player / lost-player target: no-op.
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("creature", 5),))
    state.players[1].has_lost = True
    eff.resolve(state, 0, (("player", 1),))
    assert len(state.players[1].hand) == 4
    assert "target player draws" in eff.describe()


def test_time_warp_queues_target_player():
    state = make_state()
    eff = TargetPlayerTakesExtraTurn()
    assert eff.requires_target()
    eff.resolve(state, 0, (("player", 1),))
    eff.resolve(state, 0, ())
    assert state.extra_turn_queue == [1]
    assert "extra turn" in eff.describe()


def test_hymn_discards_at_random_from_rng():
    state = make_state()
    for n in ("Island", "Swamp", "Forest"):
        add(state, 1, n, Zone.HAND)
    state.rng.seed(3)
    eff = TargetPlayerDiscardsAtRandom(amount=2)
    assert eff.legal_targets(state, 0) == [("player", 0), ("player", 1)]
    eff.resolve(state, 0, (("player", 1),))
    assert len(state.players[1].hand) == 1
    assert len(state.players[1].graveyard) == 2
    # Empty hand stops early; X amount reads resolving X.
    state.resolving_x_value = 5
    TargetPlayerDiscardsAtRandom(amount=ResolvingX()).resolve(
        state, 0, (("player", 1),),
    )
    assert state.players[1].hand == []
    TargetPlayerDiscardsAtRandom().resolve(state, 0, ())
    assert "at random" in TargetPlayerDiscardsAtRandom(amount=ResolvingX()).describe()


def test_mind_twist_cast_with_x():
    state = make_state(agent0=ScriptedAgent(target=[("player", 1)], x=[2]))
    for n in ("Island", "Swamp", "Forest"):
        add(state, 1, n, Zone.HAND)
    card = add(state, 0, "Mind Twist", Zone.HAND)
    add_lands(state, 0, "Swamp", 4)
    cast_and_resolve(state, 0, card)
    assert len(state.players[1].hand) == 1
    assert state.resolving_x_value == 0


def test_thoughtseize_caster_picks_nonland_and_loses_life():
    state = make_state(agent0=ScriptedAgent(target=[("player", 1)]))
    add(state, 1, "Forest", Zone.HAND)
    ritual = add(state, 1, "Dark Ritual", Zone.HAND)
    brainstorm = add(state, 1, "Brainstorm", Zone.HAND)
    state.players[0].agent.scripts["opp_hand"] = [brainstorm.id]
    card = add(state, 0, "Thoughtseize", Zone.HAND)
    add_lands(state, 0, "Swamp", 1)
    cast_and_resolve(state, 0, card)
    assert brainstorm in state.players[1].graveyard
    assert ritual in state.players[1].hand
    assert state.players[0].life == 18
    # The Forest was never an option; every revealed card is known to P0.
    opts = [o for h, o in state.players[0].agent.calls if h == "opp_hand"][0]
    assert set(opts) == {ritual.id, brainstorm.id}
    assert all(0 in c.publicly_known_to for c in state.players[1].hand)


def test_reveal_discard_filters_and_edge_cases():
    state = make_state()
    add(state, 1, "Forest", Zone.HAND)
    tutor = add(state, 1, "Demonic Tutor", Zone.HAND)
    eff = TargetPlayerRevealsHandYouChooseDiscard(
        card_filter=CardFilter(excluded_types=("Creature", "Land")),
        opponent_only=True,
    )
    assert eff.legal_targets(state, 0) == [("player", 1)]
    # Caster without an agent falls back to the first option.
    state.players[0].agent = None
    eff.resolve(state, 0, (("player", 1),))
    assert tutor in state.players[1].graveyard
    # Nothing matching: no discard.
    eff.resolve(state, 0, (("player", 1),))
    assert len(state.players[1].hand) == 1
    eff.resolve(state, 0, ())
    assert "target opponent" in eff.describe()
    assert "target player" in TargetPlayerRevealsHandYouChooseDiscard().describe()


def test_duress_only_targets_opponents(cube_printings):
    state = make_state()
    eff = cube_printings["Duress"].spell_effect
    assert eff.legal_targets(state, 0) == [("player", 1)]


def test_demonic_tutor_to_hand():
    state = make_state()
    lib = _library(state, 0, ["Island", "Time Walk", "Swamp"])
    state.players[0].agent.scripts["library"] = [lib[1].id]
    card = add(state, 0, "Demonic Tutor", Zone.HAND)
    add_lands(state, 0, "Swamp", 2)
    cast_and_resolve(state, 0, card)
    assert lib[1] in state.players[0].hand
    assert lib[1].zone == Zone.HAND
    assert len(state.players[0].library) == 2


def test_unfiltered_search_cannot_fail_but_filtered_may():
    state = make_state(agent0=ScriptedAgent(library=[None, None]))
    lib = _library(state, 0, ["Island", "Swamp"])
    SearchLibrary(card_filter=ANY_CARD, destination="hand").resolve(state, 0)
    assert lib[0] in state.players[0].hand  # declined -> first option
    SearchLibrary(
        card_filter=CardFilter(any_types=("Land",)), destination="hand",
    ).resolve(state, 0)
    assert len(state.players[0].hand) == 1  # declined filtered search
    # Nothing matching: logs and shuffles.
    SearchLibrary(
        card_filter=CardFilter(any_types=("Artifact",)), destination="hand",
    ).resolve(state, 0)
    assert len(state.players[0].hand) == 1


def test_entomb_to_graveyard_and_battlefield_destination():
    state = make_state()
    lib = _library(state, 0, ["Island", "Forest"])
    SearchLibrary(card_filter=ANY_CARD, destination="graveyard").resolve(state, 0)
    assert lib[0] in state.players[0].graveyard
    SearchLibrary(
        card_filter=CardFilter(any_types=("Land",)), destination="battlefield",
    ).resolve(state, 0)
    assert lib[1] in state.battlefield
    assert lib[1].zone == Zone.BATTLEFIELD


def test_vampiric_and_mystical_put_on_top():
    state = make_state()
    lib = _library(state, 0, ["Island", "Swamp", "Brainstorm", "Forest"])
    state.players[0].agent.scripts["library"] = [lib[2].id]
    SearchLibrary(card_filter=ANY_CARD, destination="top").resolve(state, 0)
    assert state.players[0].library[0] is lib[2]
    assert lib[2].publicly_known_to == frozenset({0})
    SearchLibrary(
        card_filter=CardFilter(any_types=("Land",)), destination="top",
        reveal=True,
    ).resolve(state, 0)
    top = state.players[0].library[0]
    assert top.printing.is_land
    assert top.publicly_known_to == frozenset({0, 1})


def test_search_library_rejects_unknown_destination():
    with pytest.raises(ValueError):
        SearchLibrary(destination="exile")
    for dest in ("hand", "graveyard", "top", "battlefield"):
        assert "search your library" in SearchLibrary(destination=dest).describe()


def test_brainstorm_draws_three_puts_two_back():
    state = make_state()
    lib = _library(state, 0, ["Island", "Swamp", "Forest", "Mountain"])
    keep = add(state, 0, "Plains", Zone.HAND)
    card = add(state, 0, "Brainstorm", Zone.HAND)
    add_lands(state, 0, "Island", 1)
    state.players[0].agent.scripts["discard"] = [lib[0].id, keep.id]
    cast_and_resolve(state, 0, card)
    p = state.players[0]
    assert p.library[0] is keep and p.library[1] is lib[0]
    assert len(p.hand) == 2
    assert keep.publicly_known_to == frozenset({0})


def test_put_from_hand_on_top_edge_cases():
    state = make_state()
    state.players[0].agent = None
    c = add(state, 0, "Island", Zone.HAND)
    PutCardsFromHandOnTopOfLibrary(amount=2).resolve(state, 0)
    assert state.players[0].library == [c]
    assert "on top of your library" in PutCardsFromHandOnTopOfLibrary(2).describe()


def test_stock_up_takes_two_rest_on_bottom():
    state = make_state()
    lib = _library(
        state, 0, ["Island", "Swamp", "Forest", "Mountain", "Plains", "Time Walk"],
    )
    state.players[0].agent.scripts["library"] = [lib[3].id, lib[1].id]
    LookAtTopCardsPutIntoHand(count=5, take=2).resolve(state, 0)
    p = state.players[0]
    assert {c.id for c in p.hand} == {lib[3].id, lib[1].id}
    assert p.library == [lib[5], lib[0], lib[2], lib[4]]


def test_look_top_n_optional_filter_random_rest_and_graveyard():
    state = make_state(agent0=ScriptedAgent(library=[None]))
    lib = _library(state, 0, ["Island", "Dark Ritual", "Forest"])
    eff = LookAtTopCardsPutIntoHand(
        count=3, take=1, take_filter=CardFilter(any_types=("Land",)),
        optional=True, reveal=True, rest_zone="graveyard",
    )
    eff.resolve(state, 0)
    p = state.players[0]
    assert p.hand == []
    assert {c.id for c in p.graveyard} == {c.id for c in lib}
    assert all(c.publicly_known_to == frozenset({0, 1}) for c in lib)
    # Mandatory pick with a declining agent takes the first option;
    # reveal_taken reveals it; rest shuffled onto the bottom.
    state = make_state(agent0=ScriptedAgent(library=[None]))
    lib = _library(state, 0, ["Island", "Dark Ritual", "Forest", "Swamp"])
    state.rng.seed(1)
    LookAtTopCardsPutIntoHand(
        count=3, take=1, reveal_taken=True, rest_random=True,
    ).resolve(state, 0)
    p = state.players[0]
    assert p.hand == [lib[0]]
    assert lib[0].publicly_known_to == frozenset({0, 1})
    assert p.library[0] is lib[3]
    assert {c.id for c in p.library[1:]} == {lib[1].id, lib[2].id}
    # No matching card: nothing taken.
    state = make_state()
    _library(state, 0, ["Island"])
    LookAtTopCardsPutIntoHand(
        count=1, take=1, take_filter=CardFilter(any_types=("Artifact",)),
    ).resolve(state, 0)
    assert state.players[0].hand == []
    with pytest.raises(ValueError):
        LookAtTopCardsPutIntoHand(rest_zone="exile")
    assert "reveal the top" in LookAtTopCardsPutIntoHand(reveal=True).describe()
    assert "you may put" in LookAtTopCardsPutIntoHand(optional=True).describe()


def test_look_top_n_formula_count():
    state = make_state()
    add_lands(state, 0, "Swamp", 2)
    lib = _library(state, 0, ["Island"] * 6)
    LookAtTopCardsPutIntoHand(
        count=Scaled(inner=CountControlledMatching(IsLand()), factor=2),
        take=1,
    ).resolve(state, 0)
    p = state.players[0]
    assert p.hand == [lib[0]]
    assert p.library[:2] == lib[4:6]


def test_ponder_reorders_and_may_shuffle():
    agent = ScriptedAgent(yes_no=[False])
    state = make_state(agent0=agent)
    lib = _library(state, 0, ["Island", "Swamp", "Forest", "Mountain"])
    agent.scripts["library"] = [lib[2].id, lib[0].id]
    ReorderTopCards(count=3).resolve(state, 0)
    p = state.players[0]
    assert p.library == [lib[2], lib[0], lib[1], lib[3]]
    ShuffleYourLibrary(optional=True).resolve(state, 0)
    assert p.library == [lib[2], lib[0], lib[1], lib[3]]
    state.rng.seed(7)
    ShuffleYourLibrary(optional=True).resolve(state, 0)  # default yes
    assert all(c.publicly_known_to == frozenset() for c in p.library)
    ShuffleYourLibrary().resolve(state, 0)
    assert ShuffleYourLibrary(optional=True).describe() == "you may shuffle"
    assert ShuffleYourLibrary().describe() == "shuffle"
    assert "back in any order" in ReorderTopCards().describe()


def test_ponder_full_cast():
    state = make_state(agent0=ScriptedAgent(yes_no=[False]))
    lib = _library(state, 0, ["Island", "Swamp", "Forest", "Mountain"])
    state.players[0].agent.scripts["library"] = [lib[1].id, lib[2].id]
    card = add(state, 0, "Ponder", Zone.HAND)
    add_lands(state, 0, "Island", 1)
    cast_and_resolve(state, 0, card)
    p = state.players[0]
    assert p.hand == [lib[1]]
    assert p.library == [lib[2], lib[0], lib[3]]


def test_preordain_scry_bottoms_chosen_cards():
    state = make_state(agent0=ScriptedAgent(surveil=[True, False]))
    lib = _library(state, 0, ["Island", "Swamp", "Forest"])
    card = add(state, 0, "Preordain", Zone.HAND)
    add_lands(state, 0, "Island", 1)
    cast_and_resolve(state, 0, card)
    p = state.players[0]
    assert p.hand == [lib[1]]
    assert p.library == [lib[2], lib[0]]


def test_scry_default_keeps_all_on_top():
    state = make_state()
    lib = _library(state, 0, ["Island", "Swamp"])
    Scry(amount=2).resolve(state, 0)
    assert state.players[0].library == lib
    Scry(amount=2, bottom_choice=True).resolve(state, 0)
    assert state.players[0].library == lib


def test_wheel_of_fortune():
    state = make_state()
    for pid in (0, 1):
        _library(state, pid, ["Island"] * 8)
        add(state, pid, "Swamp", Zone.HAND)
    card = add(state, 0, "Wheel of Fortune", Zone.HAND)
    add_lands(state, 0, "Mountain", 3)
    cast_and_resolve(state, 0, card)
    for pid in (0, 1):
        p = state.players[pid]
        assert len(p.hand) == 7
        assert any(c.printing.name == "Swamp" for c in p.graveyard)
    EachPlayerDiscardsHand().resolve(state, 0)
    assert "discards their hand" in EachPlayerDiscardsHand().describe()


def test_timetwister_shuffles_hand_and_graveyard_then_draws_seven():
    state = make_state()
    for pid in (0, 1):
        _library(state, pid, ["Island"] * 3)
        add(state, pid, "Swamp", Zone.HAND)
        add(state, pid, "Forest", Zone.GRAVEYARD)
    card = add(state, 0, "Timetwister", Zone.HAND)
    add_lands(state, 0, "Island", 3)
    cast_and_resolve(state, 0, card)
    p1 = state.players[1]
    assert len(p1.hand) == 5 and p1.graveyard == [] and p1.library == []
    p0 = state.players[0]
    # Timetwister itself hits the graveyard after the shuffle.
    assert [c.printing.name for c in p0.graveyard] == ["Timetwister"]
    assert "hand and graveyard" in EachPlayerShufflesZonesIntoLibrary().describe()
    state.players[1].has_lost = True
    EachPlayerShufflesZonesIntoLibrary(zones=("hand",)).resolve(state, 0)


def test_time_spiral_exiles_itself_and_untaps_lands():
    state = make_state()
    _library(state, 0, ["Island"] * 7)
    _library(state, 1, ["Island"] * 7)
    card = add(state, 0, "Time Spiral", Zone.HAND)
    lands = add_lands(state, 0, "Island", 6)
    cast_and_resolve(state, 0, card)
    p0 = state.players[0]
    assert card in p0.exile and card.zone == Zone.EXILE
    assert card not in p0.graveyard and card not in p0.library
    assert all(not l.tapped for l in lands)
    assert len(p0.hand) == 7


def test_exile_this_spell_outside_resolution_is_noop():
    state = make_state()
    ExileThisSpell().resolve(state, 0)
    assert ExileThisSpell().describe() == "exile this spell"


def test_frantic_search_untaps_own_lands_multicolor_first():
    state = make_state()
    _library(state, 0, ["Island"] * 2)
    add(state, 0, "Swamp", Zone.HAND)
    add(state, 0, "Forest", Zone.HAND)
    card = add(state, 0, "Frantic Search", Zone.HAND)
    lands = add_lands(state, 0, "Island", 6)
    lands[0].tapped = lands[1].tapped = True
    opp_land = add(state, 1, "Island", Zone.BATTLEFIELD)
    opp_land.tapped = True
    cast_and_resolve(state, 0, card)
    # 2 pre-tapped + 3 for the cost = 5 tapped; three come back.
    assert sum(1 for l in lands if not l.tapped) == 4
    assert opp_land.tapped
    assert "untap up to 3 lands" == UntapUpToNLands(3).describe()


def test_upheaval_returns_everything_and_tokens_vanish():
    state = make_state()
    land0 = add(state, 0, "Island", Zone.BATTLEFIELD)
    land1 = add(state, 1, "Swamp", Zone.BATTLEFIELD)
    land1.plus_one_counters = 2
    ReturnAllPermanentsToOwnersHands().resolve(state, 0)
    assert state.battlefield == []
    assert land0 in state.players[0].hand and land1 in state.players[1].hand
    assert land1.plus_one_counters == 0
    assert land1.publicly_known_to == frozenset({0, 1})
    assert "owners' hands" in ReturnAllPermanentsToOwnersHands().describe()


def test_reprieve_returns_target_spell_and_draws():
    state = make_state()
    _library(state, 0, ["Island"])
    target = add(state, 1, "Demonic Tutor", Zone.STACK)
    target.zone = Zone.STACK
    state.stack.append(StackItem(source=target, controller_id=1))
    card = add(state, 0, "Reprieve", Zone.HAND)
    add_lands(state, 0, "Plains", 2)
    apply_action(state, 0, CastSpell(card.id))
    assert state.stack[-1].targets == (("stack", 0),)
    resolve_top_of_stack(state)
    assert target in state.players[1].hand
    assert state.stack == []
    assert len(state.players[0].hand) == 1


def test_return_target_spell_edge_cases():
    state = make_state()
    eff = ReturnTargetSpellToOwnersHand()
    assert eff.requires_target()
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("stack", 3),))
    eff.resolve(state, 0, (("creature", 0),))
    spell = add(state, 1, "Demonic Tutor", Zone.STACK)
    state.stack.append(StackItem(source=spell, controller_id=1, countered=True))
    assert eff.legal_targets(state, 0) == []
    eff.resolve(state, 0, (("stack", 0),))
    assert len(state.stack) == 1
    assert "target spell" in eff.describe()


def test_dark_ritual_adds_black_mana():
    state = make_state()
    card = add(state, 0, "Dark Ritual", Zone.HAND)
    add_lands(state, 0, "Swamp", 1)
    cast_and_resolve(state, 0, card)
    assert [c.color for c in state.players[0].mana_pool] == ["B", "B", "B"]


def test_manamorphose_adds_two_any_and_draws():
    state = make_state()
    _library(state, 0, ["Island"])
    card = add(state, 0, "Manamorphose", Zone.HAND)
    add_lands(state, 0, "Mountain", 2)
    cast_and_resolve(state, 0, card)
    p = state.players[0]
    assert [c.color for c in p.mana_pool] == ["any", "any"]
    assert len(p.hand) == 1


def test_look_at_target_players_hand():
    state = make_state()
    c = add(state, 1, "Island", Zone.HAND)
    eff = LookAtTargetPlayersHand()
    assert eff.requires_target()
    assert eff.legal_targets(state, 0) == [("player", 0), ("player", 1)]
    eff.resolve(state, 0, (("player", 1),))
    eff.resolve(state, 0, ())
    assert c.publicly_known_to == frozenset({0})
    assert eff.describe() == "look at target player's hand"
