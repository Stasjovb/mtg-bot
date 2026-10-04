"""PowerLSV cube mana rocks claimed by the artifact builder.

Covers the parse shape and in-engine behavior of: the Talisman cycle,
Black Lotus, Lion's Eye Diamond, Grim / Basalt Monolith, Mox Opal,
Relic of Sauron, Wizard's Rockets, Mana Crypt and Crucible of Worlds.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from mtg_bot import apply, legal_moves
from mtg_bot.actions import (
    ActivateAbility,
    PlayLand,
    _classify_sac_for_mana,
    put_into_battlefield,
    resolve_top_of_stack,
)
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.cards.base import ActivatedAbility, ActivationCost, parse_mana_cost
from mtg_bot.cards.parser.activated import (
    _is_mana_ability_effect,
    _parse_activated_ability_line,
)
from mtg_bot.cards.parser.effects import _parse_effect
from mtg_bot.cards.parser.printing_keywords import (
    _parse_doesnt_untap_line,
    _parse_enters_tapped_line,
)
from mtg_bot.effects.combinators import Sequence
from mtg_bot.effects.generic import (
    AddManaInAnyCombination,
    AddManaToPool,
    AddNManaOfChosenColor,
    DealDamageAnyTarget,
    DrawCards,
    FlipCoinIfLost,
    GainLife,
    SourceDealsDamageToController,
    UntapSelf,
)
from mtg_bot.effects.predicates import Controlled, Event, YOU
from mtg_bot.game import Zone
from mtg_bot.turn import Step, run_beginning_of_upkeep_triggers, run_untap_step

from tests._cube_artifact_helpers import (
    agent,
    arena,
    build_ok,
    pool_colors,
    put,
    to_graveyard,
    to_hand,
)


def _activate(state, obj, idx, pid=0):
    apply(state, ActivateAbility(source_id=obj.id, ability_index=idx), pid)


def _can_activate(state, obj, idx, pid=0):
    return ActivateAbility(source_id=obj.id, ability_index=idx) in legal_moves(
        state, pid
    )


# --- effect grammar -------------------------------------------------------

@pytest.mark.parametrize("phrase,expected", [
    ("add three mana of any one color", AddNManaOfChosenColor(amount=3)),
    ("add 2 mana of any one color", AddNManaOfChosenColor(amount=2)),
    (
        "add two mana in any combination of {U}, {B}, and/or {R}",
        AddManaInAnyCombination(amount=2, options=("U", "B", "R")),
    ),
    (
        "add two mana in any combination of {W} and/or {U}",
        AddManaInAnyCombination(amount=2, options=("W", "U")),
    ),
    (
        "add X mana in any combination of colors",
        AddManaInAnyCombination(amount_is_x=True),
    ),
    ("this artifact deals 1 damage to you", SourceDealsDamageToController(1)),
    ("it deals three damage to you", SourceDealsDamageToController(3)),
    ("untap this artifact", UntapSelf()),
    (
        "flip a coin. If you lose the flip, this artifact deals 3 damage "
        "to you",
        FlipCoinIfLost(on_loss=SourceDealsDamageToController(3)),
    ),
])
def test_effect_phrases(phrase, expected):
    assert _parse_effect(phrase) == expected


def test_flip_coin_with_unparseable_inner_rejects():
    assert _parse_effect("flip a coin. If you lose the flip, frobnicate") is None


def test_talisman_line_is_sequence_mana_ability():
    ability = _parse_activated_ability_line(
        "{T}: Add {W} or {U}. This artifact deals 1 damage to you."
    )
    assert ability == ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=Sequence(effects=(
            AddNManaOfChosenColor(amount=1, options=("W", "U")),
            SourceDealsDamageToController(amount=1),
        )),
        is_mana_ability=True,
    )


def test_mana_ability_detection_rejects_targeting_or_manaless_sequences():
    assert not _is_mana_ability_effect(
        Sequence(effects=(DrawCards(amount=1), GainLife(amount=1)))
    )
    assert not _is_mana_ability_effect(
        Sequence(effects=(
            AddManaToPool(produces=(("C", 1),)),
            DealDamageAnyTarget(amount=1),
        ))
    )


@pytest.mark.parametrize("line,expected", [
    ("This artifact enters tapped.", True),
    ("This creature enters tapped.", True),
    ("This land enters tapped.", False),
])
def test_enters_tapped_line(line, expected):
    assert _parse_enters_tapped_line(line) is expected


def test_doesnt_untap_line():
    assert _parse_doesnt_untap_line(
        "This artifact doesn't untap during your untap step."
    )
    assert not _parse_doesnt_untap_line("This artifact untaps.")


@pytest.mark.parametrize("line", [
    "{T}: Add {C}. Activate only as an instant. Activate only as an instant.",
    "{T}: Add {C}. Activate only during your turn. Activate only during "
    "your turn.",
    "{T}: Add {C}. Activate only if you control three or more artifacts. "
    "Activate only if you control two or more artifacts.",
    "Discard your hand, Discard your hand: Draw a card.",
])
def test_duplicate_riders_and_costs_reject(line):
    assert _parse_activated_ability_line(line) is None


def test_riders_lift_to_ability_fields():
    ability = _parse_activated_ability_line(
        "{1}, {T}: Draw a card. Activate only during your turn."
    )
    assert ability.activate_only_during_your_turn is True
    ability = _parse_activated_ability_line(
        "Metalcraft — {T}: Add one mana of any color. Activate only if you "
        "control 3 or more artifacts."
    )
    assert ability.cost.requires_own_artifact_count_at_least == 3
    assert ability.is_mana_ability


# --- builder shapes --------------------------------------------------------

@pytest.mark.parametrize("name,colors", [
    ("Talisman of Conviction", ("R", "W")),
    ("Talisman of Creativity", ("U", "R")),
    ("Talisman of Curiosity", ("G", "U")),
    ("Talisman of Dominance", ("U", "B")),
    ("Talisman of Indulgence", ("B", "R")),
    ("Talisman of Progress", ("W", "U")),
])
def test_talisman_shapes(name, colors):
    p = build_ok(name)
    assert p.activated_abilities == (
        ActivatedAbility(
            cost=ActivationCost(tap_self=True),
            effect=AddManaToPool(produces=(("C", 1),)),
            is_mana_ability=True,
        ),
        ActivatedAbility(
            cost=ActivationCost(tap_self=True),
            effect=Sequence(effects=(
                AddNManaOfChosenColor(amount=1, options=colors),
                SourceDealsDamageToController(amount=1),
            )),
            is_mana_ability=True,
        ),
    )


def test_black_lotus_and_led_shapes():
    lotus = build_ok("Black Lotus")
    assert lotus.activated_abilities == (
        ActivatedAbility(
            cost=ActivationCost(tap_self=True, sacrifice_self=True),
            effect=AddNManaOfChosenColor(amount=3),
            is_mana_ability=True,
        ),
    )
    led = build_ok("Lion's Eye Diamond")
    (ability,) = led.activated_abilities
    assert ability.cost == ActivationCost(discard_hand=True, sacrifice_self=True)
    assert ability.effect == AddNManaOfChosenColor(amount=3)
    assert ability.is_mana_ability and ability.activate_only_as_instant
    assert "Discard your hand" in ability.cost.describe()


def test_monolith_shapes():
    grim = build_ok("Grim Monolith")
    assert grim.doesnt_untap_during_untap_step
    assert grim.activated_abilities[0].effect == AddManaToPool(
        produces=(("C", 3),)
    )
    assert grim.activated_abilities[1] == ActivatedAbility(
        cost=ActivationCost(mana=parse_mana_cost("{4}"), mana_str="{4}"),
        effect=UntapSelf(),
    )
    basalt = build_ok("Basalt Monolith")
    assert basalt.activated_abilities[1].cost.mana_str == "{3}"


def test_mana_crypt_shape():
    crypt = build_ok("Mana Crypt")
    (trigger,) = crypt.triggered_abilities
    assert trigger.event == Event.BEGINNING_OF_UPKEEP
    assert trigger.predicate == Controlled(YOU)
    assert trigger.effect == FlipCoinIfLost(
        on_loss=SourceDealsDamageToController(amount=3)
    )


# --- engine behavior -------------------------------------------------------

def test_talisman_colored_ability_pings_controller():
    state = arena()
    talisman = put(state, build_ok("Talisman of Dominance"))
    agent(state).colors = ["B"]
    _activate(state, talisman, 1)
    assert pool_colors(state) == ["B"]
    assert state.players[0].life == 19
    assert talisman.tapped
    assert not state.stack  # mana ability: no stack


def test_talisman_colorless_ability_is_painless():
    state = arena()
    talisman = put(state, build_ok("Talisman of Progress"))
    _activate(state, talisman, 0)
    assert pool_colors(state) == ["C"]
    assert state.players[0].life == 20


def test_black_lotus_adds_three_of_one_color():
    state = arena()
    lotus = put(state, build_ok("Black Lotus"))
    agent(state).colors = ["G"]
    _activate(state, lotus, 0)
    assert pool_colors(state) == ["G", "G", "G"]
    assert lotus not in state.battlefield
    assert state.players[0].graveyard[-1].id == lotus.id


def test_lions_eye_diamond_discards_hand():
    state = arena()
    led = put(state, build_ok("Lion's Eye Diamond"))
    to_hand(state, BASIC_LANDS["Forest"])
    to_hand(state, BASIC_LANDS["Forest"])
    agent(state).colors = ["R"]
    assert _can_activate(state, led, 0)
    _activate(state, led, 0)
    assert state.players[0].hand == []
    assert len(state.players[0].graveyard) == 3  # two lands + LED
    assert all(c.zone == Zone.GRAVEYARD for c in state.players[0].graveyard)
    assert pool_colors(state) == ["R", "R", "R"]


def test_lions_eye_diamond_is_legal_with_empty_hand_and_not_sac_for_mana():
    state = arena()
    led = put(state, build_ok("Lion's Eye Diamond"))
    assert _can_activate(state, led, 0)
    assert _classify_sac_for_mana(state, led) == []


def test_instant_rider_excludes_add_mana_to_pool_from_sac_for_mana():
    state = arena()
    lotus = build_ok("Black Lotus")
    ability = replace(
        lotus.activated_abilities[0],
        effect=AddManaToPool(produces=(("any", 1),)),
    )
    obj = put(state, replace(lotus, activated_abilities=(ability,)))
    assert _classify_sac_for_mana(state, obj) != []
    instant = replace(ability, activate_only_as_instant=True)
    obj2 = put(state, replace(lotus, activated_abilities=(instant,)))
    assert _classify_sac_for_mana(state, obj2) == []


def test_during_your_turn_rider_gates_activation():
    state = arena(active=1)
    lotus = build_ok("Black Lotus")
    ability = replace(
        lotus.activated_abilities[0], activate_only_during_your_turn=True,
    )
    obj = put(state, replace(lotus, activated_abilities=(ability,)))
    state.priority_player_idx = 0  # P0 holds priority on P1's turn
    assert not _can_activate(state, obj, 0)
    state.active_player_idx = 0
    assert _can_activate(state, obj, 0)


def test_grim_monolith_stays_tapped_and_untaps_for_four():
    state = arena()
    grim = put(state, build_ok("Grim Monolith"))
    for _ in range(4):
        put(state, BASIC_LANDS["Swamp"])
    _activate(state, grim, 0)
    assert pool_colors(state) == ["C", "C", "C"]
    state.players[0].mana_pool.clear()
    run_untap_step(state)
    assert grim.tapped, "doesn't untap during its controller's untap step"
    assert _can_activate(state, grim, 1)
    _activate(state, grim, 1)
    resolve_top_of_stack(state)
    assert not grim.tapped


def test_untap_self_is_noop_when_untapped_or_gone():
    state = arena()
    grim = put(state, build_ok("Grim Monolith"))
    state.resolving_source = grim
    UntapSelf().resolve(state, 0)
    assert not grim.tapped
    state.battlefield.remove(grim)
    grim.tapped = True
    UntapSelf().resolve(state, 0)
    assert grim.tapped
    state.resolving_source = None
    UntapSelf().resolve(state, 0)
    assert UntapSelf().describe() == "untap this permanent"


def test_untap_step_untaps_other_permanents_normally():
    state = arena()
    grim = put(state, build_ok("Grim Monolith"))
    talisman = put(state, build_ok("Talisman of Progress"), tapped=True)
    run_untap_step(state)
    assert not talisman.tapped
    assert not grim.tapped  # an untapped monolith stays untapped


def test_mox_opal_needs_three_artifacts():
    state = arena()
    opal = put(state, build_ok("Mox Opal"))
    put(state, build_ok("Talisman of Progress"))
    assert not _can_activate(state, opal, 0)
    put(state, build_ok("Grim Monolith"))
    assert _can_activate(state, opal, 0)
    agent(state).colors = ["U"]
    _activate(state, opal, 0)
    assert len(state.players[0].mana_pool) == 1


def test_relic_of_sauron_two_mana_any_combination():
    state = arena()
    relic = put(state, build_ok("Relic of Sauron"))
    agent(state).colors = ["U", "R"]
    _activate(state, relic, 0)
    assert pool_colors(state) == ["R", "U"]


def test_relic_of_sauron_rejects_color_outside_options():
    state = arena()
    relic = put(state, build_ok("Relic of Sauron"))
    agent(state).colors = ["G", "W"]
    _activate(state, relic, 0)
    assert pool_colors(state) == ["U", "U"]


def test_any_combination_without_agent_and_zero_amount():
    state = arena()
    state.players[0].agent = None
    AddManaInAnyCombination(amount=2, options=("B", "R")).resolve(state, 0)
    assert pool_colors(state) == ["B", "B"]
    state.players[0].mana_pool.clear()
    AddManaInAnyCombination(amount_is_x=True).resolve(state, 0)
    assert pool_colors(state) == []
    assert "X mana" in AddManaInAnyCombination(amount_is_x=True).describe()


def test_wizards_rockets_enters_tapped_and_makes_x_mana():
    state = arena()
    rockets_printing = build_ok("Wizard's Rockets")
    assert rockets_printing.enters_tapped
    rockets = state.new_object(rockets_printing, owner_id=0, zone=Zone.STACK)
    put_into_battlefield(state, rockets, 0)
    assert rockets.tapped
    rockets.tapped = False
    for _ in range(2):
        put(state, BASIC_LANDS["Island"])
    agent(state).x_value = 2
    agent(state).colors = ["W", "G"]
    _activate(state, rockets, 0)
    assert pool_colors(state) == ["G", "W"]
    assert rockets not in state.battlefield
    assert state.resolving_x_value == 0


def test_mana_crypt_coin_flip_damage_is_seeded():
    losses = 0
    for seed in range(20):
        state = arena(seed=seed)
        put(state, build_ok("Mana Crypt"))
        state.step = Step.UPKEEP
        run_beginning_of_upkeep_triggers(state)
        assert len(state.stack) == 1
        resolve_top_of_stack(state)
        life = state.players[0].life
        assert life in (17, 20)
        losses += life == 17
    assert 0 < losses < 20


def test_mana_crypt_taps_for_two():
    state = arena()
    crypt = put(state, build_ok("Mana Crypt"))
    _activate(state, crypt, 0)
    assert pool_colors(state) == ["C", "C"]


def test_source_damage_to_controller_zero_is_noop():
    state = arena()
    SourceDealsDamageToController(amount=0).resolve(state, 0)
    assert state.players[0].life == 20
    assert "1 damage" in SourceDealsDamageToController(amount=1).describe()
    assert "coin" in FlipCoinIfLost(
        on_loss=SourceDealsDamageToController(1)
    ).describe()


def test_crucible_of_worlds_lets_you_play_lands_from_graveyard():
    state = arena()
    crucible = build_ok("Crucible of Worlds")
    assert crucible.grants_play_lands_from_graveyard
    put(state, crucible)
    land = to_graveyard(state, BASIC_LANDS["Mountain"])
    assert PlayLand(card_id=land.id) in legal_moves(state, 0)
