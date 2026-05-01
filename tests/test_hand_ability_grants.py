"""Tests for ``HandCardFilter`` / ``HandAbilityGrant`` and the
battlefield-granted warp pipeline (Tannuk, Steadfast Second).

Coverage:
- ``HandCardFilter.matches`` for the disjunction-of-typed-predicates
  shape.
- ``effective_warp_cost`` returns the granted cost for matching hand
  cards when a ``hand_ability_grants`` permanent is on the battlefield.
- Innate warp wins over a battlefield grant (priority).
- ``legal_actions`` offers ``CastSpell(use_warp=True)`` for matching
  hand cards when the grantor is in play.
- The grant disappears when the grantor leaves the battlefield.
- Non-matching hand cards (wrong type / wrong color) don't get the
  warp option.
"""

from __future__ import annotations

from mtg_bot.actions import effective_warp_cost
from mtg_bot.cards.base import (
    CardPrinting,
    HandAbilityGrant,
    HandCardFilter,
    make_artifact,
    make_creature,
    parse_mana_cost,
)
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.game import GameObject, GameState, Player, Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step


# ---------------------------------------------------------------------------
# HandCardFilter.matches
# ---------------------------------------------------------------------------

def test_hand_card_filter_matches_artifact_only():
    f = HandCardFilter((("Artifact", None),))
    art = make_artifact("Plain Artifact", "{2}")
    creature = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    assert f.matches(art) is True
    assert f.matches(creature) is False


def test_hand_card_filter_matches_typed_with_color():
    # "red creature" — matches a creature with R in its mana cost.
    f = HandCardFilter((("Creature", "R"),))
    red_creature = make_creature("Goblin", "{R}", power=1, toughness=1)
    blue_creature = make_creature("Merfolk", "{U}", power=1, toughness=1)
    art = make_artifact("Plain Artifact", "{2}")
    assert f.matches(red_creature) is True
    assert f.matches(blue_creature) is False
    assert f.matches(art) is False  # not a creature


def test_hand_card_filter_matches_disjunction():
    # Tannuk's filter: artifact OR red-creature.
    f = HandCardFilter((("Artifact", None), ("Creature", "R")))
    art = make_artifact("Plain Artifact", "{2}")
    red_creature = make_creature("Goblin", "{R}", power=1, toughness=1)
    blue_creature = make_creature("Merfolk", "{U}", power=1, toughness=1)
    assert f.matches(art) is True
    assert f.matches(red_creature) is True
    # Blue creature: not an artifact, and not a red creature → fails both.
    assert f.matches(blue_creature) is False


# ---------------------------------------------------------------------------
# effective_warp_cost
# ---------------------------------------------------------------------------

def _tannuk_state_with_artifact_in_hand():
    """Helper: state with Tannuk on the battlefield (player 0) and a
    plain artifact in player 0's hand. Returns (state, hand_card)."""
    parser = OracleParserCardSource()
    tannuk_pr = parser.get_printings()["Tannuk, Steadfast Second"]
    tannuk = GameObject(
        id=1, printing=tannuk_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    art_pr = make_artifact("Plain Artifact", "{4}")
    art = GameObject(
        id=2, printing=art_pr, owner_id=0, controller_id=0,
        zone=Zone.HAND,
    )
    p0 = Player(id=0)
    p0.hand = [art]
    state = GameState(players=[p0, Player(id=1)], battlefield=[tannuk])
    return state, art


def test_effective_warp_cost_uses_battlefield_grant():
    state, art = _tannuk_state_with_artifact_in_hand()
    result = effective_warp_cost(state, 0, art)
    assert result is not None
    cost, cost_str = result
    assert cost_str == "{2}{R}"
    assert cost == parse_mana_cost("{2}{R}")


def test_effective_warp_cost_skips_non_matching_card():
    state, _ = _tannuk_state_with_artifact_in_hand()
    # Add a blue non-creature non-artifact to player 0's hand.
    blue_pr = make_creature("Merfolk", "{U}", power=1, toughness=1)
    blue = GameObject(
        id=3, printing=blue_pr, owner_id=0, controller_id=0,
        zone=Zone.HAND,
    )
    state.players[0].hand.append(blue)
    assert effective_warp_cost(state, 0, blue) is None


def test_effective_warp_cost_innate_warp_wins():
    # A card with an innate warp_cost should keep its innate cost even
    # when a battlefield grant would also apply (current priority).
    parser = OracleParserCardSource()
    tannuk_pr = parser.get_printings()["Tannuk, Steadfast Second"]
    tannuk = GameObject(
        id=1, printing=tannuk_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    # A red creature with its own innate warp cost — Tannuk's filter
    # would also match (red creature), but innate wins.
    innate_warp_pr = make_creature(
        "Warp Goblin", "{1}{R}", power=2, toughness=2, warp="{B}",
    )
    card = GameObject(
        id=2, printing=innate_warp_pr, owner_id=0, controller_id=0,
        zone=Zone.HAND,
    )
    p0 = Player(id=0)
    p0.hand = [card]
    state = GameState(players=[p0, Player(id=1)], battlefield=[tannuk])
    result = effective_warp_cost(state, 0, card)
    assert result is not None
    _cost, cost_str = result
    assert cost_str == "{B}"


def test_effective_warp_cost_no_grant_returns_none():
    # No Tannuk on battlefield, no innate warp → no warp available.
    art_pr = make_artifact("Plain Artifact", "{4}")
    art = GameObject(
        id=2, printing=art_pr, owner_id=0, controller_id=0,
        zone=Zone.HAND,
    )
    p0 = Player(id=0)
    p0.hand = [art]
    state = GameState(players=[p0, Player(id=1)])
    assert effective_warp_cost(state, 0, art) is None


# ---------------------------------------------------------------------------
# legal_actions integration
# ---------------------------------------------------------------------------

def _add_red_lands(state, player_id, count):
    """Helper: add ``count`` Mountains to the battlefield under
    ``player_id``'s control. Used to make warp costs payable."""
    from mtg_bot.cards.base import make_basic_land
    mountain_pr = make_basic_land("Mountain", "R")
    next_id = max([o.id for o in state.battlefield] or [0]) + 1
    for i in range(count):
        state.battlefield.append(GameObject(
            id=next_id + i, printing=mountain_pr,
            owner_id=player_id, controller_id=player_id,
            zone=Zone.BATTLEFIELD,
        ))


def test_legal_actions_offers_warp_cast_for_matching_hand_card():
    state, art = _tannuk_state_with_artifact_in_hand()
    # Make {2}{R} payable: 3 Mountains.
    _add_red_lands(state, 0, 3)
    # Set the active player to 0 and put us in main phase so
    # sorcery-speed casts are offered.
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    # Reset is so legal_actions sees the controller as active.
    actions = legal_actions(state, 0)
    from mtg_bot.actions import CastSpell
    warp_casts = [
        a for a in actions
        if isinstance(a, CastSpell)
        and a.card_id == art.id
        and a.use_warp is True
    ]
    assert len(warp_casts) == 1, (
        f"expected 1 warp-cast action for Plain Artifact via Tannuk's "
        f"grant; got {len(warp_casts)}: {actions}"
    )


def test_legal_actions_omits_warp_when_grantor_absent():
    # Same setup but Tannuk is NOT on the battlefield.
    art_pr = make_artifact("Plain Artifact", "{4}")
    art = GameObject(
        id=2, printing=art_pr, owner_id=0, controller_id=0,
        zone=Zone.HAND,
    )
    p0 = Player(id=0)
    p0.hand = [art]
    state = GameState(players=[p0, Player(id=1)])
    _add_red_lands(state, 0, 3)
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    actions = legal_actions(state, 0)
    from mtg_bot.actions import CastSpell
    warp_casts = [
        a for a in actions
        if isinstance(a, CastSpell)
        and a.card_id == art.id
        and a.use_warp is True
    ]
    assert warp_casts == [], (
        "no warp-cast should be offered without a Tannuk-style grantor"
    )


def test_legal_actions_omits_warp_for_non_matching_hand_card():
    state, _ = _tannuk_state_with_artifact_in_hand()
    # Add a blue creature to hand — Tannuk's filter doesn't match.
    blue_pr = make_creature("Merfolk", "{U}", power=1, toughness=1)
    blue = GameObject(
        id=3, printing=blue_pr, owner_id=0, controller_id=0,
        zone=Zone.HAND,
    )
    state.players[0].hand.append(blue)
    _add_red_lands(state, 0, 3)
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    actions = legal_actions(state, 0)
    from mtg_bot.actions import CastSpell
    warp_casts = [
        a for a in actions
        if isinstance(a, CastSpell)
        and a.card_id == blue.id
        and a.use_warp is True
    ]
    assert warp_casts == [], (
        "blue non-creature shouldn't get warp-cast option from Tannuk"
    )
