"""Opening-hand actions (CR 103.6) and Gemstone Caverns: the parse, the
pre-game hook in ``simulate.setup_game`` (non-starting player only), and
the luck-counter-gated mana ability on both payment paths."""

from __future__ import annotations

import pytest

from mtg_bot.actions import ActivateAbility, apply_action, auto_tap_for_cost, can_pay_cost
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards.base import parse_mana_cost
from mtg_bot.cards.parser.opening_hand_lines import parse_opening_hand_line
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.effects.combinators import IfConditionElse
from mtg_bot.effects.conditions import SourceHasCounter
from mtg_bot.effects.generic.mana import AddManaToPool
from mtg_bot.game import (
    Zone,
    add_counters,
    counter_count,
    effective_land_produces,
)
from mtg_bot.legal import legal_actions
from mtg_bot.opening_hand import BeginGameOnBattlefield, apply_opening_hand_actions
from mtg_bot.simulate import setup_game
from tests._rmc_helpers import add, make_state

CAVERNS = "Gemstone Caverns"
CAVERNS_LINE = (
    "If this card is in your opening hand and you're not the starting "
    "player, you may begin the game with Gemstone Caverns on the battlefield "
    "with a luck counter on it. If you do, exile a card from your hand."
)


class _Recorder(Agent):
    """Keeps every hand; answers the opening-hand question from a script
    and exiles the last card offered."""

    def __init__(self, answers=()):
        self.answers = list(answers)
        self.prompts: list[str] = []
        self.discard_offers: list[list[int]] = []

    def choose_yes_no(self, state, player_id, prompt):
        self.prompts.append(prompt)
        return self.answers.pop(0) if self.answers else False

    def choose_discard(self, state, player_id, hand_card_ids):
        self.discard_offers.append(list(hand_card_ids))
        return hand_card_ids[-1]


# ------------------------------------------------------------------ parse


@pytest.mark.parametrize("pool", ["cube", "eoe"])
def test_gemstone_caverns_parse_shape(pool):
    p = OracleParserCardSource(pool=pool).get_printings()[CAVERNS]
    assert p.is_legendary and p.is_land
    assert p.opening_hand_action == BeginGameOnBattlefield(
        only_if_not_starting_player=True,
        counters=(("luck", 1),),
        exile_from_hand=1,
    )
    assert p.produces == frozenset({"C"})
    assert p.mana_only_from_produces
    assert p.produces_with_counter == ("luck", frozenset("WUBRG"))
    (ability,) = p.activated_abilities
    assert ability.is_mana_ability and ability.cost.tap_self
    assert ability.effect == IfConditionElse(
        condition=SourceHasCounter("luck"),
        then_effect=AddManaToPool(produces=(("any", 1),)),
        else_effect=AddManaToPool(produces=(("C", 1),)),
    )


def test_opening_hand_line_variants():
    assert parse_opening_hand_line(CAVERNS_LINE, CAVERNS) == BeginGameOnBattlefield(
        True, (("luck", 1),), 1,
    )
    leyline = (
        "If this card is in your opening hand, you may begin the game with "
        "it on the battlefield."
    )
    assert parse_opening_hand_line(leyline, "Leyline") == BeginGameOnBattlefield()
    assert parse_opening_hand_line(
        leyline.replace(".", ". If you do, exile two cards from your hand."),
        "Leyline",
    ) == BeginGameOnBattlefield(exile_from_hand=2)
    # Another card's name is not this card.
    assert parse_opening_hand_line(CAVERNS_LINE, "Other Land") is None
    assert parse_opening_hand_line("Flying", CAVERNS) is None


def test_describe():
    action = BeginGameOnBattlefield(counters=(("luck", 2),))
    assert action.describe("X") == (
        "begin the game with X on the battlefield with 2 luck counters on it"
    )
    assert BeginGameOnBattlefield().describe("X") == (
        "begin the game with X on the battlefield"
    )


def test_counter_gated_line_must_name_this_land():
    from mtg_bot.cards.parser.land_lines import _try_build_line_composed_land

    text = (
        "{T}: Add {C}. If Some Other Land has a luck counter on it, instead "
        "add one mana of any color."
    )
    card = {"name": "Mine", "type_line": "Land"}
    assert _try_build_line_composed_land(card, text, (), ("Land",), ()) is None
    twice = (
        "{T}: Add {C}. If this land has a luck counter on it, instead add one "
        "mana of any color.\n"
        "{T}: Add {C}. If this land has a luck counter on it, instead add one "
        "mana of any color."
    )
    assert _try_build_line_composed_land(card, twice, (), ("Land",), ()) is None
    two_hooks = f"{CAVERNS_LINE}\n{CAVERNS_LINE}"
    card = {"name": CAVERNS, "type_line": "Legendary Land"}
    assert _try_build_line_composed_land(
        card, two_hooks, ("Legendary",), ("Land",), (),
    ) is None
    # A colored base keeps the other free colors when the counter swaps in
    # any color.
    card = {"name": "Mine", "type_line": "Land"}
    p = _try_build_line_composed_land(
        card,
        "{T}: Add {W}.\n{T}: Add {G}. If this land has a luck counter on it, "
        "instead add one mana of any color.",
        (), ("Land",), (),
    )
    assert p.produces == frozenset({"W", "G"})
    assert p.produces_with_counter == ("luck", frozenset("WUBRG"))


# --------------------------------------------------------- setup_game hook


def _setup(agent0, agent1, *, starting=0, deck1=None, deck0=None, **kw):
    deck0 = deck0 or [CAVERNS] * 20
    deck1 = deck1 or [CAVERNS] * 20
    return setup_game(
        [agent0, agent1], decks=[deck0, deck1], seed=7,
        starting_player_idx=starting, **kw,
    )


def _caverns_on_battlefield(state, pid):
    return [
        o for o in state.battlefield
        if o.controller_id == pid and o.printing.name == CAVERNS
    ]


def test_only_the_non_starting_player_is_offered_it():
    a0, a1 = _Recorder([True]), _Recorder([True])
    state = _setup(a0, a1)
    assert a0.prompts == []  # the starting player is never asked
    assert a1.prompts[0].startswith("begin the game with Gemstone Caverns")
    (caverns,) = _caverns_on_battlefield(state, 1)
    assert counter_count(caverns, "luck") == 1
    assert _caverns_on_battlefield(state, 0) == []
    # "If you do, exile a card from your hand."
    assert len(state.players[1].exile) == 1
    assert len(state.players[1].hand) == 5
    assert state.active_player_idx == 0 and state.turn_number == 1


def test_starting_seat_one_flips_who_may_use_it():
    a0, a1 = _Recorder([True]), _Recorder([True])
    state = _setup(a0, a1, starting=1)
    assert a1.prompts == []
    assert len(_caverns_on_battlefield(state, 0)) == 1
    assert state.active_player_idx == 1 and state.priority_player_idx == 1


def test_declining_keeps_it_in_hand():
    a1 = _Recorder([False] * 7)
    state = _setup(_Recorder(), a1)
    assert len(a1.prompts) == 7  # each Caverns in the hand is offered
    assert _caverns_on_battlefield(state, 1) == []
    assert len(state.players[1].hand) == 7
    assert state.players[1].exile == []


def test_runs_without_mulligans_too_and_with_random_agents():
    import random

    state = _setup(
        RandomAgent(rng=random.Random(1)), RandomAgent(rng=random.Random(2)),
        enable_mulligans=False,
    )
    assert _caverns_on_battlefield(state, 0) == []
    # No opening-hand card: nobody is asked.
    a0, a1 = _Recorder(), _Recorder()
    _setup(a0, a1, deck0=["Island"] * 20, deck1=["Island"] * 20)
    assert a0.prompts == a1.prompts == []


def test_starting_player_out_of_range():
    with pytest.raises(ValueError, match="starting_player_idx"):
        _setup(_Recorder(), _Recorder(), starting=2)


def test_exile_with_an_empty_hand_and_a_bad_pick():
    state = make_state()
    p1 = state.players[1]
    p1.agent = _Recorder([True])
    caverns = add(state, 1, CAVERNS, Zone.HAND)
    apply_opening_hand_actions(state, 0)
    assert caverns in state.battlefield and p1.exile == []

    class _Bad(_Recorder):
        def choose_discard(self, state, player_id, hand_card_ids):
            return -1

    state = make_state()
    state.players[1].agent = _Bad([True])
    add(state, 1, CAVERNS, Zone.HAND)
    add(state, 1, "Island", Zone.HAND)
    with pytest.raises(ValueError, match="choose_discard"):
        apply_opening_hand_actions(state, 0)


def test_a_card_exiled_by_an_earlier_action_is_not_offered():
    state = make_state()
    agent = _Recorder([True, True])
    state.players[1].agent = agent
    first = add(state, 1, CAVERNS, Zone.HAND)
    second = add(state, 1, CAVERNS, Zone.HAND)
    apply_opening_hand_actions(state, 0)
    # The first one's rider exiled the second (the last card offered).
    assert first in state.battlefield and second in state.players[1].exile
    assert len(agent.prompts) == 1


# ------------------------------------------------------------------- mana


def _caverns_in_play(luck: bool):
    state = make_state()
    caverns = add(state, 0, CAVERNS)
    if luck:
        add_counters(state, caverns, "luck", 1)
    return state, caverns


def test_explicit_activation_without_luck_adds_colorless():
    state, caverns = _caverns_in_play(luck=False)
    action = ActivateAbility(source_id=caverns.id, ability_index=0)
    assert action in legal_actions(state, 0)
    apply_action(state, 0, action)
    assert [c.color for c in state.players[0].mana_pool] == ["C"]


def test_explicit_activation_with_luck_adds_any_color():
    state, caverns = _caverns_in_play(luck=True)
    apply_action(state, 0, ActivateAbility(source_id=caverns.id, ability_index=0))
    assert [c.color for c in state.players[0].mana_pool] == ["any"]


def test_automatic_payment_respects_the_counter():
    state, caverns = _caverns_in_play(luck=False)
    assert effective_land_produces(state, caverns) == frozenset({"C"})
    assert can_pay_cost(state, 0, parse_mana_cost("{1}"))
    assert not can_pay_cost(state, 0, parse_mana_cost("{W}"))
    state, caverns = _caverns_in_play(luck=True)
    assert effective_land_produces(state, caverns) == frozenset("WUBRG")
    assert can_pay_cost(state, 0, parse_mana_cost("{W}"))
    assert can_pay_cost(state, 0, parse_mana_cost("{G}"))
    tapped = auto_tap_for_cost(state, 0, parse_mana_cost("{B}"))
    assert tapped == [caverns] and caverns.tapped


def test_source_has_counter_condition():
    state, caverns = _caverns_in_play(luck=True)
    cond = SourceHasCounter("luck")
    assert not cond.matches(state, 0)  # nothing resolving
    state.resolving_source = caverns
    assert cond.matches(state, 0)
    assert not SourceHasCounter("mining").matches(state, 0)
    state.resolving_source = None
    assert cond.matches_for_source(state, caverns)
