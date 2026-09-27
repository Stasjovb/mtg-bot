"""Predefined artifact tokens (Clue / Food / Map / Blood), investigate,
explore, and the ``Discard a card`` activation cost."""

from __future__ import annotations

import pytest

from mtg_bot import apply
from mtg_bot.actions import ActivateAbility, drain_stack
from mtg_bot.agents import Agent
from mtg_bot.cards import BASIC_LANDS, make_creature
from mtg_bot.cards.parser.activated import _parse_activated_ability_line
from mtg_bot.cards.parser.effects import _parse_effect
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.cards.tokens import TOKEN_PRINTINGS
from mtg_bot.effects.generic.keyword_actions import Explore, explore
from mtg_bot.effects.generic.tokens import CreateToken
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step


class _Agent(Agent):
    def __init__(self, yes=True):
        self.yes = yes

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_yes_no(self, state, player_id, prompt):
        return self.yes

    def choose_discard(self, state, player_id, hand_card_ids):
        return hand_card_ids[-1]


def _state(agent=None) -> GameState:
    state = GameState()
    state.players.append(Player(id=0, agent=agent or _Agent()))
    state.players.append(Player(id=1, agent=_Agent()))
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner, zone=Zone.BATTLEFIELD):
    obj = state.new_object(printing, owner, zone)
    obj.summoning_sick = False
    {
        Zone.HAND: state.players[owner].hand,
        Zone.LIBRARY: state.players[owner].library,
        Zone.BATTLEFIELD: state.battlefield,
    }[zone].append(obj)
    return obj


def _lands(state, n, name="Plains"):
    for _ in range(n):
        _put(state, BASIC_LANDS[name], 0)


def _activate(state, obj):
    idx = 0
    act = ActivateAbility(source_id=obj.id, ability_index=idx)
    assert act in legal_actions(state, 0)
    apply(state, act, player_id=0)
    drain_stack(state)


# ---------------------------------------------------------------- parser


@pytest.mark.parametrize(
    "phrase,count", [("investigate", 1), ("investigate twice", 2),
                     ("investigate four times", 4), ("investigate 3 times", 3)],
)
def test_investigate_creates_clues(phrase, count):
    eff = _parse_effect(phrase)
    assert isinstance(eff, CreateToken)
    assert eff.token_printing.name == "Clue" and eff.count == count


def test_explore_phrases_and_token_phrases():
    assert _parse_effect("this creature explores") == Explore()
    assert _parse_effect("target creature you control explores") == Explore(target=True)
    for name in ("Food", "Map", "Blood", "Clue"):
        eff = _parse_effect(f"create a {name} token")
        assert eff.token_printing is TOKEN_PRINTINGS[name]
    assert _parse_effect("it explores") is None


def test_discard_a_card_cost_piece_parses():
    ab = _parse_activated_ability_line("{1}, Discard a card: Draw a card.")
    assert ab is not None and ab.cost.discard_a_card
    assert _parse_activated_ability_line(
        "Discard a card, Discard a card: Draw a card."
    ) is None


def test_cube_cards_claimed():
    claimed = set(OracleParserCardSource(pool="cube").claimed_names)
    assert {"Thraben Inspector", "Generous Ent", "Sentinel of the Nameless City"} <= claimed


# ---------------------------------------------------------------- tokens


def test_clue_sacrifices_to_draw():
    state = _state()
    _lands(state, 2)
    top = _put(state, BASIC_LANDS["Island"], 0, Zone.LIBRARY)
    clue = _put(state, TOKEN_PRINTINGS["Clue"], 0)
    _activate(state, clue)
    assert top in state.players[0].hand and clue not in state.battlefield


def test_food_gains_three_life():
    state = _state()
    _lands(state, 2)
    food = _put(state, TOKEN_PRINTINGS["Food"], 0)
    _activate(state, food)
    assert state.players[0].life == 23


def test_blood_requires_and_pays_a_discard():
    state = _state()
    _lands(state, 1)
    blood = _put(state, TOKEN_PRINTINGS["Blood"], 0)
    assert not any(isinstance(a, ActivateAbility) for a in legal_actions(state, 0))
    junk = _put(state, BASIC_LANDS["Swamp"], 0, Zone.HAND)
    top = _put(state, BASIC_LANDS["Island"], 0, Zone.LIBRARY)
    _activate(state, blood)
    assert junk in state.players[0].graveyard
    assert top in state.players[0].hand


def test_map_explores_target_creature_at_sorcery_speed():
    state = _state()
    _lands(state, 1)
    bear = _put(state, make_creature("Bear", "{G}", 2, 2), 0)
    spell = _put(state, make_creature("Top Spell", "{3}", 3, 3), 0, Zone.LIBRARY)
    m = _put(state, TOKEN_PRINTINGS["Map"], 0)
    state.step = Step.END
    assert not any(isinstance(a, ActivateAbility) for a in legal_actions(state, 0))
    state.step = Step.PRECOMBAT_MAIN
    _activate(state, m)
    assert bear.plus_one_counters == 1
    assert spell in state.players[0].graveyard


# ---------------------------------------------------------------- explore


def test_explore_land_goes_to_hand_without_counter():
    state = _state()
    bear = _put(state, make_creature("Bear", "{G}", 2, 2), 0)
    land = _put(state, BASIC_LANDS["Forest"], 0, Zone.LIBRARY)
    explore(state, 0, bear)
    assert land in state.players[0].hand and bear.plus_one_counters == 0


def test_explore_nonland_can_stay_on_top():
    state = _state(agent=_Agent(yes=False))
    bear = _put(state, make_creature("Bear", "{G}", 2, 2), 0)
    spell = _put(state, make_creature("Spell", "{1}", 1, 1), 0, Zone.LIBRARY)
    explore(state, 0, bear)
    assert state.players[0].library[0] is spell and bear.plus_one_counters == 1


def test_explore_empty_library_still_counters():
    state = _state()
    bear = _put(state, make_creature("Bear", "{G}", 2, 2), 0)
    explore(state, 0, bear)
    assert bear.plus_one_counters == 1


def test_self_explore_uses_resolving_source_and_target_edge_cases():
    state = _state()
    bear = _put(state, make_creature("Bear", "{G}", 2, 2), 0)
    state.resolving_source = bear
    Explore().resolve(state, 0, ())
    state.resolving_source = None
    assert bear.plus_one_counters == 1
    assert Explore().legal_targets(state, 0) == []
    assert Explore(target=True).legal_targets(state, 0) == [("creature", bear.id)]
    Explore(target=True).resolve(state, 0, ())
    Explore(target=True).resolve(state, 0, (("creature", 999),))
    assert bear.plus_one_counters == 1
    assert Explore().describe() == "this creature explores"
    assert "target" in Explore(target=True).describe()


# ---------------------------------------------------------------- synthesized creature tokens


@pytest.mark.parametrize(
    "phrase,name,count,pt,kws,colors,flags",
    [
        ("create three 5/5 green Wurm creature tokens with trample",
         "Wurm", 3, (5, 5), {"trample"}, {"G"}, (False, False)),
        ("create a 1/1 blue Faerie Dragon creature token with flying",
         "Faerie Dragon", 1, (1, 1), {"flying"}, {"U"}, (False, False)),
        ("create a 2/2 white and blue Bird creature token with flying, vigilance, and lifelink",
         "Bird", 1, (2, 2), {"flying", "vigilance", "lifelink"}, {"W", "U"}, (False, False)),
        ("create a 3/3 colorless Golem artifact creature token",
         "Golem", 1, (3, 3), set(), set(), (False, False)),
        ("create a tapped 4/4 green Beast creature token",
         "Beast", 1, (4, 4), set(), {"G"}, (True, False)),
        ("create a 4/1 black Skeleton creature token with menace that's tapped and attacking",
         "Skeleton", 1, (4, 1), {"menace"}, {"B"}, (True, True)),
        ("create 2 1/1 white Cat enchantment creature tokens",
         "Cat", 2, (1, 1), set(), {"W"}, (False, False)),
    ],
)
def test_synthesized_creature_tokens(phrase, name, count, pt, kws, colors, flags):
    eff = _parse_effect(phrase)
    assert isinstance(eff, CreateToken)
    tok = eff.token_printing
    assert tok.name == name and eff.count == count
    assert (tok.power, tok.toughness) == pt
    assert tok.keywords == frozenset(kws)
    assert tok.color_indicator == frozenset(colors)
    assert (eff.tapped, eff.attacking) == flags
    assert "Token" in tok.supertypes and tok.is_creature


@pytest.mark.parametrize(
    "phrase",
    [
        'create a 1/1 green Minion creature token named Moloid with "Whenever this token attacks, you may mill a card."',
        "create a 1/1 red Goblin creature token with banding",
        'create a 1/1 black Rat creature token with "This creature can\'t block."',
    ],
)
def test_synthesized_tokens_refuse_unmodeled_riders(phrase):
    assert _parse_effect(phrase) is None


def test_registered_token_still_wins_over_synthesis():
    eff = _parse_effect("create a 2/2 colorless Robot artifact creature token")
    assert eff.token_printing is TOKEN_PRINTINGS["Robot"]


def test_token_color_indicator_feeds_effective_colors():
    from mtg_bot.game import effective_colors

    state = _state()
    eff = _parse_effect("create a 1/1 white Spirit creature token with flying")
    eff.resolve(state, 0, ())
    spirit = next(o for o in state.battlefield if o.printing.name == "Spirit")
    assert effective_colors(state, spirit) == frozenset({"W"})


def test_scry_and_each_opponent_mills_phrases():
    from mtg_bot.effects.generic.draw_mill import EachOpponentMillsCards
    from mtg_bot.effects.generic.library_lookat import Scry

    # Parsed scry makes the real keep / bottom decision (bottom_choice).
    assert _parse_effect("scry 2") == Scry(amount=2, bottom_choice=True)
    assert _parse_effect("scry one") == Scry(amount=1, bottom_choice=True)
    assert _parse_effect("each opponent mills three cards") == EachOpponentMillsCards(amount=3)
    assert _parse_effect("each opponent mills a card") == EachOpponentMillsCards(amount=1)
    assert "Preordain" in OracleParserCardSource(pool="cube").claimed_names
