"""Keyword-grant grammar (``parser.keyword_actions._parse_keyword_grant_effect``)
and the protection-of-choice grant effect."""

from __future__ import annotations

import pytest

from mtg_bot.agents import Agent
from mtg_bot.cards import make_creature
from mtg_bot.cards.parser.effects import _parse_effect
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.effects.generic.keyword_actions import GrantProtectionOfChoiceUEOT
from mtg_bot.effects.generic.pump import (
    PumpCreaturesYouControlUntilEOT,
    PumpTargetCreatureUntilEOT,
)
from mtg_bot.game import GameState, Player, Zone, effective_keywords
from mtg_bot.turn import Step, run_cleanup_step


class _Agent(Agent):
    def __init__(self, color="R"):
        self.color = color

    def choose_mana_color(self, state, player_id, options):
        return self.color


def _state(color="R") -> GameState:
    state = GameState()
    state.players.append(Player(id=0, agent=_Agent(color)))
    state.players.append(Player(id=1, agent=_Agent(color)))
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner):
    obj = state.new_object(printing, owner, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def test_target_creature_you_control_grant():
    eff = _parse_effect("target creature you control gains shroud until end of turn")
    assert eff == PumpTargetCreatureUntilEOT(
        granted_keywords=frozenset({"shroud"}), you_control_only=True,
    )
    assert _parse_effect(
        "target creature you control gains banding until end of turn"
    ) is None


@pytest.mark.parametrize(
    "phrase,kws,other,tokens",
    [
        ("creatures you control gain hexproof and indestructible until end of turn",
         {"hexproof", "indestructible"}, False, False),
        ("other creatures you control gain flying until end of turn", {"flying"}, True, False),
        ("creature tokens you control gain haste until end of turn", {"haste"}, False, True),
    ],
)
def test_group_grants(phrase, kws, other, tokens):
    eff = _parse_effect(phrase)
    assert isinstance(eff, PumpCreaturesYouControlUntilEOT)
    assert eff.granted_keywords == frozenset(kws)
    assert eff.exclude_source is other and eff.tokens_only is tokens


def test_group_grant_rejections():
    assert _parse_effect("other creature tokens you control gain haste until end of turn") is None
    assert _parse_effect("creatures you control gain banding until end of turn") is None


def test_tokens_only_group_grant_skips_nontokens():
    from mtg_bot.cards.base import make_token_creature

    state = _state()
    token = _put(state, make_token_creature("Servo", 1, 1, artifact=True), 0)
    card = _put(state, make_creature("Card", "{1}", 1, 1), 0)
    PumpCreaturesYouControlUntilEOT(
        granted_keywords=frozenset({"haste"}), tokens_only=True,
    ).resolve(state, 0, ())
    assert "haste" in effective_keywords(state, token)
    assert "haste" not in effective_keywords(state, card)


def test_protection_of_choice_parses_both_shapes():
    assert _parse_effect(
        "target creature you control gains protection from the color of "
        "your choice until end of turn"
    ) == GrantProtectionOfChoiceUEOT()
    assert _parse_effect(
        "another target creature you control gains protection from colorless "
        "or from the color of your choice until end of turn"
    ) == GrantProtectionOfChoiceUEOT(exclude_self=True, allow_colorless=True)


def test_protection_of_choice_grants_chosen_color_until_cleanup():
    state = _state(color="B")
    mom = _put(state, make_creature("Mom", "{W}", 1, 1), 0)
    bear = _put(state, make_creature("Bear", "{G}", 2, 2), 0)
    theirs = _put(state, make_creature("Theirs", "{G}", 2, 2), 1)
    eff = GrantProtectionOfChoiceUEOT(exclude_self=True, allow_colorless=True)
    state.resolving_source = mom
    legal = eff.legal_targets(state, 0)
    assert ("creature", bear.id) in legal
    assert ("creature", mom.id) not in legal
    assert ("creature", theirs.id) not in legal
    eff.resolve(state, 0, (("creature", bear.id),))
    state.resolving_source = None
    assert "protection from black" in effective_keywords(state, bear)
    state.active_player_idx = 0
    run_cleanup_step(state)
    assert "protection from black" not in effective_keywords(state, bear)


def test_protection_of_choice_colorless_and_edge_cases():
    state = _state(color="C")
    bear = _put(state, make_creature("Bear", "{G}", 2, 2), 0)
    eff = GrantProtectionOfChoiceUEOT(allow_colorless=True)
    eff.resolve(state, 0, (("creature", bear.id),))
    assert "protection from colorless" in effective_keywords(state, bear)
    # Colorless not allowed -> an out-of-options answer falls back to W.
    GrantProtectionOfChoiceUEOT().resolve(state, 0, (("creature", bear.id),))
    assert "protection from white" in effective_keywords(state, bear)
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("creature", 999),))
    assert "colorless or from" in eff.describe()
    assert GrantProtectionOfChoiceUEOT().describe().startswith("target creature")


def test_cube_cards_claimed():
    claimed = set(OracleParserCardSource(pool="cube").claimed_names)
    assert {
        "Mother of Runes", "Giver of Runes", "Sylvan Safekeeper",
        "Spectacular Spider-Man", "Ravenous Robots",
    } <= claimed
