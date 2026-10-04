"""Engine behavior of the second batch of PowerLSV cube lands claimed
through the line-composed land grammar: Sunken Ruins (filter mana),
the Channel lands (Boseiju, Who Endures / Otawara, Soaring City),
Starting Town, Multiversal Passage, Gemstone Mine and Restless
Vinestalk — plus the parser surfaces they introduced.
"""

from __future__ import annotations

import pytest

from mtg_bot.actions import (
    ActivateAbility,
    _play_land,
    apply_action,
    can_pay_cost,
    resolve_top_of_stack,
)
from mtg_bot.cards.base import make_basic_land, make_creature, parse_mana_cost
from mtg_bot.cards.parser.activated import _parse_activated_ability_line
from mtg_bot.cards.parser.effects import _parse_effect
from mtg_bot.cards.parser.land_builder import _build_land_printing
from mtg_bot.effects.object_predicates import IsCreature, IsLegendary
from mtg_bot.game import Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step
from tests.test_cube_land_mechanics import (
    ISLAND,
    PLAINS,
    _Agent,
    _put,
    _state,
    _zone,
    cube,  # noqa: F401  (module-scoped fixture)
)


FOREST = make_basic_land("Forest", "G")


# --- Sunken Ruins: filter mana -------------------------------------------


def test_sunken_ruins_filter(cube):
    from mtg_bot.effects.generic import AddOneOfManaCombinations

    ruins = cube["Sunken Ruins"]
    assert ruins.produces == frozenset({"C"})
    (flt,) = ruins.activated_abilities
    assert flt.is_mana_ability and flt.cost.tap_self
    assert flt.cost.mana.hybrid == (("B", "U"),)
    assert flt.effect == AddOneOfManaCombinations(
        options=((("U", 2),), (("U", 1), ("B", 1)), (("B", 2),)),
    )
    assert flt.effect.describe() == "add {U}{U}, {U}{B}, or {B}{B}"

    class Picker(_Agent):
        def choose_mode(self, state, player_id, mode_descriptions):
            assert mode_descriptions == ["{U}{U}", "{U}{B}", "{B}{B}"]
            return 1

    state = _state(agent=Picker())
    r = _put(state, ruins)
    _put(state, ISLAND)
    assert ActivateAbility(r.id, 0) in legal_actions(state, 0)
    apply_action(state, 0, ActivateAbility(r.id, 0))
    assert sorted(c.color for c in state.players[0].mana_pool) == ["B", "U"]


def test_mana_combination_choice_fallbacks():
    from mtg_bot.effects.generic import (
        AddNManaOfChosenColor,
        AddOneOfManaCombinations,
    )

    e = AddOneOfManaCombinations(options=((("U", 2),), (("B", 2),)))
    state = _state()
    state.players[0].agent = None
    e.resolve(state, 0)
    assert [c.color for c in state.players[0].mana_pool] == ["U", "U"]

    class Bad(_Agent):
        def choose_mode(self, state, player_id, mode_descriptions):
            return 9

    state = _state(agent=Bad())
    e.resolve(state, 0)
    assert [c.color for c in state.players[0].mana_pool] == ["U", "U"]
    # Single-symbol "or" lists stay with the chosen-color recognizer.
    assert isinstance(_parse_effect("add {W} or {U}"), AddNManaOfChosenColor)


# --- Channel lands: Boseiju, Otawara ---------------------------------------


def _legend(name="Legend"):
    return make_creature(name, "{1}", 2, 2, legendary=True)


def test_channel_lands_claimed(cube):
    from mtg_bot.effects.conditions import PerControlled

    for name, mana, color in (
        ("Boseiju, Who Endures", "{1}{G}", "G"),
        ("Otawara, Soaring City", "{3}{U}", "U"),
    ):
        p = cube[name]
        assert p.is_legendary and p.produces == frozenset({color})
        assert p.activated_abilities == ()
        (channel,) = p.hand_activated_abilities
        assert channel.cost.mana_str == mana and channel.cost.discard_self
        (rule,) = channel.cost_reductions
        assert rule.amount == 1
        assert rule.condition == PerControlled(IsCreature() & IsLegendary())


def test_otawara_channel_bounces_and_legends_discount(cube):
    state = _state()
    ota = _zone(state, cube["Otawara, Soaring City"], "hand")
    target = _put(state, make_creature("Grunt", "{1}", 1, 1), player_id=1)
    for _ in range(3):
        _put(state, ISLAND)
    # {3}{U} with three Islands: unaffordable ...
    assert ActivateAbility(ota.id, 0) not in legal_actions(state, 0)
    # ... until a legendary creature makes it cost {2}{U}.
    _put(state, _legend())
    assert ActivateAbility(ota.id, 0) in legal_actions(state, 0)
    apply_action(state, 0, ActivateAbility(ota.id, 0))
    assert ota in state.players[0].graveyard
    resolve_top_of_stack(state)
    assert target in state.players[1].hand


def test_boseiju_channel_destroys_and_opponent_may_search(cube):
    state = _state()
    bos = _zone(state, cube["Boseiju, Who Endures"], "hand")
    _put(state, FOREST)
    _put(state, FOREST)
    opp_basic = _put(state, PLAINS, player_id=1)
    my_nonbasic = _put(state, cube["Tundra"])
    assert ActivateAbility(bos.id, 0) not in legal_actions(state, 0)
    tundra = _put(state, cube["Tundra"], player_id=1)
    fetched = _zone(state, cube["Plateau"], "library", player_id=1)
    apply_action(state, 0, ActivateAbility(bos.id, 0))
    (item,) = state.stack
    assert item.targets[0][1] == tundra.id
    resolve_top_of_stack(state)
    assert tundra not in state.battlefield
    assert opp_basic in state.battlefield and my_nonbasic in state.battlefield
    # "That player may search" — the opponent put Plateau onto the
    # battlefield under THEIR control.
    assert fetched in state.battlefield and fetched.controller_id == 1


def test_boseiju_fizzles_if_target_gone(cube):
    state = _state()
    bos = _zone(state, cube["Boseiju, Who Endures"], "hand")
    for _ in range(2):
        _put(state, FOREST)
    tundra = _put(state, cube["Tundra"], player_id=1)
    fetched = _zone(state, cube["Plateau"], "library", player_id=1)
    apply_action(state, 0, ActivateAbility(bos.id, 0))
    state.battlefield.remove(tundra)
    resolve_top_of_stack(state)
    assert fetched in state.players[1].library


def test_then_target_controller_resolves_edges():
    from mtg_bot.effects.combinators import ThenTargetControllerResolves
    from mtg_bot.effects.generic import Destroy, DrawCards
    from mtg_bot.effects.targets import TargetSpec

    e = ThenTargetControllerResolves(
        first=Destroy(targets=(TargetSpec(IsCreature()),)),
        then=DrawCards(amount=1),
    )
    assert e.requires_target() and e.target_count_range() == (1, 1)
    assert "that player" in e.describe()
    state = _state()
    e.resolve(state, 0, ())  # no targets: no-op
    grunt = _put(state, make_creature("Grunt", "{1}", 1, 1), player_id=1)
    drawn = _zone(state, PLAINS, "library", player_id=1)
    assert e.legal_targets(state, 0) == [("creature", grunt.id)]
    e.resolve(state, 0, (("creature", grunt.id),))
    assert grunt not in state.battlefield
    assert drawn in state.players[1].hand


def test_discard_cost_parses_from_hand_only():
    line = "{1}, Discard this card: Draw a card."
    assert _parse_activated_ability_line(line) is None
    a = _parse_activated_ability_line(line, from_hand=True)
    assert a.cost.discard_self and a.cost.mana_str == "{1}"
    assert "Discard this card" in a.cost.describe()
    # A card in hand can't also be tapped.
    assert _parse_activated_ability_line(
        "{T}, Discard this card: Draw a card.", from_hand=True,
    ) is None
    # Hand parsing requires the discard atom.
    assert _parse_activated_ability_line(
        "{1}: Draw a card.", from_hand=True,
    ) is None
    # Duplicate discard atoms are nonsense.
    assert _parse_activated_ability_line(
        "Discard this card, Discard this card: Draw a card.", from_hand=True,
    ) is None


def test_per_controlled_rider_unknown_noun_rejects():
    assert _parse_activated_ability_line(
        "{2}: Draw a card. This ability costs {1} less to activate for "
        "each frog you control."
    ) is None


def test_unknown_ability_word_line_falls_through():
    card = {
        "name": "X", "type_line": "Land",
        "oracle_text": "{T}: Add {G}.\nChannel — Frobnicate.",
    }
    assert _build_land_printing(card) is None


# --- Starting Town ----------------------------------------------------------


def test_starting_town(cube):
    from mtg_bot.effects.conditions import YourTurnOfGameAtMost
    from mtg_bot.turn import run_untap_step

    town = cube["Starting Town"]
    assert town.subtypes == ("Town",)
    assert town.enters_tapped_unless == YourTurnOfGameAtMost(3)
    assert town.produces == frozenset({"C"})
    (paid,) = town.activated_abilities
    assert paid.is_mana_ability and paid.cost.pay_life == 1

    state = _state()
    for turn in range(1, 5):
        run_untap_step(state)
        assert state.players[0].turns_started == turn
        card = _zone(state, town, "hand")
        _play_land(state, 0, card.id)
        assert card.tapped is (turn > 3)
    # On the opponent's turn it's never "your" turn.
    state = _state()
    run_untap_step(state)
    state.active_player_idx = 1
    card = _zone(state, town, "hand")
    _play_land(state, 0, card.id)
    assert card.tapped is True


@pytest.mark.parametrize(
    "phrase,n",
    [
        ("it's your first, second, or third turn of the game", 3),
        ("it's your first or second turn of the game", 2),
        ("it's your first turn of the game", 1),
        ("it's your second or third turn of the game", None),
        ("it's your first, third, or second turn of the game", None),
        ("it's the opponent's turn", None),
    ],
)
def test_early_turn_condition_grammar(phrase, n):
    from mtg_bot.cards.parser.land_lines import _parse_your_early_turn
    from mtg_bot.effects.conditions import YourTurnOfGameAtMost

    got = _parse_your_early_turn(phrase)
    assert got == (YourTurnOfGameAtMost(n) if n else None)


# --- Multiversal Passage ----------------------------------------------------


def test_multiversal_passage(cube):
    from mtg_bot.game import effective_land_produces, effective_subtypes

    passage = cube["Multiversal Passage"]
    assert passage.enters_choosing_basic_land_type
    assert passage.is_chosen_basic_land_type
    assert passage.shock_land_life_cost == 2
    assert passage.produces == frozenset()

    class Swampy(_Agent):
        def choose_mode(self, state, player_id, mode_descriptions):
            return mode_descriptions.index("Swamp")

        def choose_pay_shock_life(self, state, player_id, life_cost):
            return False

    state = _state(agent=Swampy())
    card = _zone(state, passage, "hand")
    _play_land(state, 0, card.id)
    assert card.chosen_basic_land_type == "Swamp"
    assert card.tapped is True and state.players[0].life == 20
    assert "Swamp" in effective_subtypes(state, card)
    assert effective_land_produces(state, card) == frozenset({"B"})
    assert can_pay_cost(state, 0, parse_mana_cost("{B}")) is False  # tapped
    card.tapped = False
    assert can_pay_cost(state, 0, parse_mana_cost("{B}"))
    # Off the battlefield the chosen type no longer applies.
    card.zone = Zone.GRAVEYARD
    assert "Swamp" not in effective_subtypes(state, card)


def test_multiversal_passage_agent_fallbacks(cube):
    state = _state()
    state.players[0].agent = None  # no agent: first type, no payment
    card = _zone(state, cube["Multiversal Passage"], "hand")
    _play_land(state, 0, card.id)
    assert card.chosen_basic_land_type == "Plains"
    assert state.players[0].life == 20
    state = _state()  # _Agent pays the shock life
    card = _zone(state, cube["Multiversal Passage"], "hand")
    _play_land(state, 0, card.id)
    assert card.tapped is False and state.players[0].life == 18


def test_chosen_type_lines_must_pair():
    only_choose = {
        "name": "X", "type_line": "Land",
        "oracle_text": (
            "As this land enters, choose a basic land type. Then you may "
            "pay 2 life. If you don't, it enters tapped."
        ),
    }
    only_static = {
        "name": "Y", "type_line": "Land",
        "oracle_text": "This land is the chosen type.",
    }
    doubled = {
        "name": "Z", "type_line": "Land",
        "oracle_text": (
            only_choose["oracle_text"] + "\n" + only_choose["oracle_text"]
            + "\nThis land is the chosen type."
        ),
    }
    doubled_static = {
        "name": "W", "type_line": "Land",
        "oracle_text": (
            only_choose["oracle_text"]
            + "\nThis land is the chosen type.\nThis land is the chosen type."
        ),
    }
    for card in (only_choose, only_static, doubled, doubled_static):
        assert _build_land_printing(card) is None


# --- Gemstone Mine ------------------------------------------------------------


def test_gemstone_mine(cube):
    from mtg_bot.game import named_counter_count

    mine = cube["Gemstone Mine"]
    assert mine.enters_with_named_counters == (("mining", 3),)
    assert mine.produces == frozenset() and mine.mana_only_from_produces
    (ability,) = mine.activated_abilities
    assert ability.is_mana_ability
    assert ability.cost.remove_named_counter_from_self == "mining"
    assert "Remove a mining counter" in ability.cost.describe()

    state = _state()
    card = _zone(state, mine, "hand")
    _play_land(state, 0, card.id)
    assert named_counter_count(card, "mining") == 3
    for left in (2, 1):
        apply_action(state, 0, ActivateAbility(card.id, 0))
        assert named_counter_count(card, "mining") == left
        assert card in state.battlefield
        card.tapped = False
    apply_action(state, 0, ActivateAbility(card.id, 0))
    assert card not in state.battlefield
    assert card in state.players[0].graveyard
    assert [c.color for c in state.players[0].mana_pool] == ["any"] * 3


def test_named_counter_cost_gated_on_counters(cube):
    from mtg_bot.game import set_named_counters

    state = _state()
    card = _put(state, cube["Gemstone Mine"])
    assert ActivateAbility(card.id, 0) not in legal_actions(state, 0)
    set_named_counters(card, "mining", 1)
    assert ActivateAbility(card.id, 0) in legal_actions(state, 0)
    set_named_counters(card, "mining", 0)
    assert card.named_counters == ()


@pytest.mark.parametrize(
    "text",
    [
        "This land enters with three charge counters on it.\n{T}: Add {C}.",
        "This land enters with many mining counters on it.\n{T}: Add {C}.",
        "{T}, Remove a charge counter from this land: Add {C}.",
        "{T}, Remove a mining counter from this land, Remove an ore counter "
        "from this land: Add {C}.",
    ],
)
def test_dedicated_or_malformed_counter_lines_fall_through(text):
    card = {"name": "X", "type_line": "Land", "oracle_text": text}
    assert _build_land_printing(card) is None


def test_named_counter_grammar_variants():
    from mtg_bot.cards.parser.land_lines import _try_build_line_composed_land
    from mtg_bot.effects.generic import SacrificeSelfIfNoNamedCounters

    card = {
        "name": "X", "type_line": "Land",
        "oracle_text": (
            "This land enters with a mining counter on it.\n"
            "This land enters with 2 ore counters on it.\n{T}: Add {C}."
        ),
    }
    p = _try_build_line_composed_land(
        card, card["oracle_text"], (), ("Land",), (),
    )
    assert p.enters_with_named_counters == (("mining", 1), ("ore", 2))
    assert "no ore counters" in SacrificeSelfIfNoNamedCounters("ore").describe()
    assert _parse_effect(
        "frobnicate. If there are no ore counters on this land, sacrifice it"
    ) is None


def test_sacrifice_if_no_counters_noop_off_battlefield():
    from mtg_bot.effects.generic import SacrificeSelfIfNoNamedCounters

    state = _state()
    obj = _zone(state, PLAINS, "hand")
    state.resolving_source = obj
    SacrificeSelfIfNoNamedCounters("mining").resolve(state, 0)
    assert obj in state.players[0].hand
    state.resolving_source = None
    SacrificeSelfIfNoNamedCounters("mining").resolve(state, 0)


# --- Restless Vinestalk ------------------------------------------------------


def test_restless_vinestalk(cube):
    from mtg_bot.combat import declare_attackers
    from mtg_bot.effects.generic import BecomeLandCreatureUEOT, SetBasePTUntilEOT
    from mtg_bot.game import (
        effective_colors, effective_power, effective_subtypes,
        effective_toughness, is_creature_now,
    )

    vine = cube["Restless Vinestalk"]
    assert vine.enters_tapped and vine.produces == frozenset({"G", "U"})
    (animate,) = vine.activated_abilities
    assert animate.effect == BecomeLandCreatureUEOT(
        power=5, toughness=5, granted_keywords=frozenset({"trample"}),
        granted_subtype="Plant", set_colors=frozenset({"G", "U"}),
    )
    (trig,) = vine.triggered_abilities
    assert trig.effect == SetBasePTUntilEOT(
        power=3, toughness=3, optional=True, exclude_self=True,
    )

    state = _state()
    v = _put(state, vine)
    for _ in range(5):
        _put(state, FOREST)
    bear = _put(state, make_creature("Bear", "{1}{G}", 2, 2))
    ogre = _put(state, make_creature("Ogre", "{1}{R}", 5, 5), player_id=1)
    apply_action(state, 0, ActivateAbility(v.id, 0))
    resolve_top_of_stack(state)
    assert is_creature_now(v)
    assert (effective_power(state, v), effective_toughness(state, v)) == (5, 5)
    assert "Plant" in effective_subtypes(state, v)
    assert effective_colors(state, v) == frozenset({"G", "U"})

    seen = []

    class PickOgre(_Agent):
        def choose_target(self, state, player_id, legal_targets):
            seen.extend(legal_targets)
            return ("creature", ogre.id)

    state.players[0].agent = PickOgre()
    state.step = Step.DECLARE_ATTACKERS
    declare_attackers(state, [v.id])
    assert ("creature", v.id) not in seen
    assert state.stack and state.stack[-1].targets == (("creature", ogre.id),)
    resolve_top_of_stack(state)
    assert effective_power(state, ogre) == 3
    assert effective_power(state, bear) == 2


def test_animated_land_phrase_grammar():
    from mtg_bot.effects.generic import BecomeLandCreatureUEOT

    e = _parse_effect(
        "until end of turn, this land becomes a 3/3 red Elemental creature. "
        "It's still a land"
    )
    assert e == BecomeLandCreatureUEOT(
        power=3, toughness=3, granted_subtype="Elemental",
        set_colors=frozenset({"R"}),
    )
    assert _parse_effect(
        "until end of turn, this land becomes a 3/3 red Elemental creature "
        "with banding. It's still a land"
    ) is None
