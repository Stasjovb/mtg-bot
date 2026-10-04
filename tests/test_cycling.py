"""Cycling / landcycling / typecycling (CR 702.29): parse shape, the
hand-ability split in the parser source, and engine activation from
hand at instant speed."""

from __future__ import annotations

import pytest

from mtg_bot import apply
from mtg_bot.actions import ActivateAbility, drain_stack
from mtg_bot.agents import Agent
from mtg_bot.cards import BASIC_LANDS, make_creature
from mtg_bot.cards.base import ActivatedAbility, ActivationCost, AddManaToPool, DrawCards
from mtg_bot.cards.parser.printing_keywords import _parse_cycling_line
from mtg_bot.cards.parser.source import (
    OracleParserCardSource,
    _split_hand_abilities,
    _with_hand_abilities,
)
from mtg_bot.effects.generic.search import SearchLibraryForCard
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step


class _Agent(Agent):
    def choose_card_from_library(self, state, player_id, option_ids):
        return option_ids[0] if option_ids else None

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _state(step=Step.PRECOMBAT_MAIN, active=0) -> GameState:
    state = GameState()
    state.players.append(Player(id=0, agent=_Agent()))
    state.players.append(Player(id=1, agent=_Agent()))
    state.step = step
    state.active_player_idx = active
    state.priority_player_idx = 0
    return state


def _put(state, printing, owner, zone):
    obj = state.new_object(printing, owner, zone)
    {
        Zone.HAND: state.players[owner].hand,
        Zone.LIBRARY: state.players[owner].library,
        Zone.BATTLEFIELD: state.battlefield,
    }[zone].append(obj)
    return obj


def _cycler(line: str, name="Cycler"):
    return make_creature(name, "{4}", 3, 3, hand_activated_abilities=(_parse_cycling_line(line),))


# ---------------------------------------------------------------- parser


def test_parse_bare_cycling_draws_a_card():
    ab = _parse_cycling_line("Cycling {2}")
    assert ab.cost.discard_self and ab.cost.mana_str == "{2}"
    assert ab.effect == DrawCards(amount=1)


@pytest.mark.parametrize(
    "line,filter_name,subtypes",
    [
        ("Islandcycling {1}", "subtype", ("Island",)),
        ("Wizardcycling {3}", "subtype", ("Wizard",)),
        ("Basic landcycling {1}{G}", "basic_land", ()),
    ],
)
def test_parse_search_cycling_variants(line, filter_name, subtypes):
    ab = _parse_cycling_line(line)
    assert ab.cost.discard_self
    assert isinstance(ab.effect, SearchLibraryForCard)
    assert ab.effect.filter_name == filter_name
    assert ab.effect.subtypes == subtypes


@pytest.mark.parametrize(
    "line", ["Cycling—Pay 2 life.", "cycling {2}", "Flying", "Cycling"],
)
def test_parse_cycling_rejects_other_lines(line):
    assert _parse_cycling_line(line) is None


def test_split_hand_abilities_peels_only_cycling_lines():
    card = {"name": "X", "oracle_text": "Flying\nCycling {2} (reminder)"}
    body, abilities = _split_hand_abilities(card)
    assert body["oracle_text"] == "Flying"
    assert len(abilities) == 1
    assert _split_hand_abilities({"name": "Y", "oracle_text": "Flying"}) == (
        {"name": "Y", "oracle_text": "Flying"}, (),
    )
    faced = {"name": "Z", "oracle_text": "Cycling {1}", "card_faces": [{}]}
    assert _split_hand_abilities(faced) == (faced, ())


def test_with_hand_abilities_fills_landcycling_for_basic_types_only():
    base = make_creature("B", "{2}", 2, 2)
    swamp = _with_hand_abilities(base, (_parse_cycling_line("Swampcycling {2}"),))
    assert swamp.landcycling == ("Swamp", "{2}")
    wizard = _with_hand_abilities(base, (_parse_cycling_line("Wizardcycling {2}"),))
    assert wizard.landcycling is None and len(wizard.hand_activated_abilities) == 1
    assert _with_hand_abilities(base, ()) is base


def test_cube_cycling_cards_claim_with_hand_abilities():
    printings = OracleParserCardSource(pool="cube").get_printings()
    unearth = printings["Unearth"]
    assert [a.effect for a in unearth.hand_activated_abilities] == [DrawCards(amount=1)]
    lorien = printings["Lórien Revealed"]
    assert lorien.hand_activated_abilities[0].effect.subtypes == ("Island",)
    assert printings["Oliphaunt"].landcycling == ("Mountain", "{1}")


# ---------------------------------------------------------------- engine


def test_cycling_is_offered_at_instant_speed_and_draws():
    state = _state(step=Step.END, active=1)
    for _ in range(2):
        _put(state, BASIC_LANDS["Island"], 0, Zone.BATTLEFIELD)
    top = _put(state, BASIC_LANDS["Forest"], 0, Zone.LIBRARY)
    cyc = _put(state, _cycler("Cycling {2}"), 0, Zone.HAND)
    act = ActivateAbility(source_id=cyc.id, ability_index=0)
    assert act in legal_actions(state, 0)
    apply(state, act, player_id=0)
    assert cyc in state.players[0].graveyard
    assert all(l.tapped for l in state.battlefield)
    drain_stack(state)
    assert top in state.players[0].hand


def test_cycling_not_offered_without_mana_and_deduped_across_copies():
    state = _state()
    a = _put(state, _cycler("Cycling {2}"), 0, Zone.HAND)
    _put(state, _cycler("Cycling {2}"), 0, Zone.HAND)
    assert not any(
        isinstance(x, ActivateAbility) for x in legal_actions(state, 0)
    )
    for _ in range(2):
        _put(state, BASIC_LANDS["Island"], 0, Zone.BATTLEFIELD)
    offered = [x for x in legal_actions(state, 0) if isinstance(x, ActivateAbility)]
    assert offered == [ActivateAbility(source_id=a.id, ability_index=0)]


def test_landcycling_fetches_matching_subtype_card():
    state = _state()
    _put(state, BASIC_LANDS["Island"], 0, Zone.BATTLEFIELD)
    _put(state, BASIC_LANDS["Forest"], 0, Zone.LIBRARY)
    island = _put(state, BASIC_LANDS["Island"], 0, Zone.LIBRARY)
    cyc = _put(state, _cycler("Islandcycling {1}"), 0, Zone.HAND)
    apply(state, ActivateAbility(source_id=cyc.id, ability_index=0), player_id=0)
    drain_stack(state)
    assert island in state.players[0].hand
    assert cyc in state.players[0].graveyard


def test_hand_ability_exile_cost_and_mana_ability_and_bad_index():
    """Generic hand-ability pipeline: an ``exile_self`` hand mana
    ability (Simian Spirit Guide shape) resolves immediately; a bad
    index is ignored."""
    guide = make_creature(
        "Guide", "{2}{R}", 2, 2,
        hand_activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(exile_self=True),
                effect=AddManaToPool(produces=(("R", 1),)),
                is_mana_ability=True,
            ),
        ),
    )
    state = _state()
    g = _put(state, guide, 0, Zone.HAND)
    apply(state, ActivateAbility(source_id=g.id, ability_index=5), player_id=0)
    assert g in state.players[0].hand
    apply(state, ActivateAbility(source_id=g.id, ability_index=0), player_id=0)
    assert g in state.players[0].exile
    assert len(state.players[0].mana_pool) == 1


def test_targeted_hand_ability_and_unpayable_activation():
    from mtg_bot.effects import DealDamageAnyTarget

    pinger = make_creature(
        "Pinger", "{R}", 1, 1,
        hand_activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=BASIC_LANDS["Mountain"].mana_cost.__class__(generic=1),
                    mana_str="{1}", discard_self=True,
                ),
                effect=DealDamageAnyTarget(amount=2),
            ),
        ),
    )
    state = _state()
    card = _put(state, pinger, 0, Zone.HAND)
    apply(state, ActivateAbility(source_id=card.id, ability_index=0), player_id=0)
    assert card in state.players[0].hand  # couldn't pay: nothing happened
    _put(state, BASIC_LANDS["Mountain"], 0, Zone.BATTLEFIELD)
    apply(state, ActivateAbility(source_id=card.id, ability_index=0), player_id=0)
    assert state.stack and state.stack[-1].targets
