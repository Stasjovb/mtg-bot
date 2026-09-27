"""Cube spells-B casting substrate: flashback, delve, buyback,
additional sacrifice / pay-X-life costs, the "instead if" threshold
rider, and Phyrexian mana.

Engine pieces live in ``mtg_bot/alt_casting.py`` plus hooks in
``actions._cast_spell`` / ``legal.legal_actions``; parser pieces in
``cards/parser/spell_builder.py`` (casting-keyword lines, substrate
additional-cost preambles, ``_parse_instead_if_rider``).
"""

from __future__ import annotations

import pytest

from mtg_bot.actions import (
    CastSpell,
    apply_action,
    can_pay_cost,
    move_spell_off_stack,
    resolve_top_of_stack,
)
from mtg_bot.alt_casting import (
    additional_costs_payable,
    choose_pay_x_life,
    cost_plus,
    delve_affordability_cost,
    pay_additional_sacrifice,
    pay_delve,
    pay_x_life_upper_bound,
    permanent_matches_filter,
    sacrifice_cost_options,
)
from mtg_bot.cards import ManaCost, parse_mana_cost
from mtg_bot.cards.base import AddManaToPool
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.cards.parser.spell_builder import (
    _casting_keyword_fields,
    _detect_casting_substrate_fields,
    _parse_instead_if_condition,
    _parse_instead_if_rider,
    _substrate_additional_cost_fields,
)
from mtg_bot.effects.combinators import IfConditionElse
from mtg_bot.effects.conditions import CardsInYourGraveyardAtLeast
from mtg_bot.effects.generic.card_flow import CardFilter
from mtg_bot.game import StackItem, Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step
from tests._spells_b_helpers import (
    ScriptedAgent,
    add,
    add_lands,
    cast_and_resolve,
    make_state,
)


@pytest.fixture(scope="module")
def cube():
    return OracleParserCardSource(pool="cube").get_printings()


# ---------------------------------------------------------------------
# Parser: keyword lines, additional costs, instead-if rider
# ---------------------------------------------------------------------


def test_casting_keyword_fields():
    assert _casting_keyword_fields("Flashback {2}{R}") == {
        "flashback_cost": parse_mana_cost("{2}{R}"),
        "flashback_cost_str": "{2}{R}",
    }
    assert _casting_keyword_fields("Delve") == {"has_delve": True}
    assert _casting_keyword_fields("Buyback {2}") == {
        "buyback_cost": parse_mana_cost("{2}"), "buyback_cost_str": "{2}",
    }
    assert _casting_keyword_fields("Flashback") is None
    assert _casting_keyword_fields("Draw a card.") is None


def test_substrate_additional_cost_fields():
    assert _substrate_additional_cost_fields("pay X life") == {
        "additional_cost_pay_x_life": True,
    }
    assert _substrate_additional_cost_fields("sacrifice a green creature") == {
        "additional_cost_sacrifice_filter": CardFilter(
            any_types=("Creature",), color="G",
        ),
    }
    assert _substrate_additional_cost_fields("sacrifice a wizard") is None
    assert _substrate_additional_cost_fields("discard a card") is None


def test_detect_casting_substrate_fields_mixes_preamble_and_keywords():
    text = (
        "As an additional cost to cast this spell, sacrifice an artifact.\n"
        "Search your library for an artifact card, put that card onto the "
        "battlefield, then shuffle.\n"
        "Flashback {1}{U} (reminder)"
    )
    fields = _detect_casting_substrate_fields(text)
    assert fields["additional_cost_sacrifice_filter"] == CardFilter(
        any_types=("Artifact",),
    )
    assert fields["flashback_cost_str"] == "{1}{U}"
    # A whitelisted legacy body contributes no substrate field.
    assert _detect_casting_substrate_fields(
        "As an additional cost to cast this spell, sacrifice an artifact "
        "or creature.\nDraw a card."
    ) == {}
    # Convoke preamble is walked past.
    assert _detect_casting_substrate_fields(
        "Convoke (reminder)\nDelve\nDraw a card."
    ) == {"has_delve": True}


def test_instead_if_rider():
    base = AddManaToPool(produces=(("B", 3),))
    rider = _parse_instead_if_rider(
        "Threshold — Add {B}{B}{B}{B}{B} instead if there are seven or more "
        "cards in your graveyard.", base, "Cabal Ritual",
    )
    assert rider == IfConditionElse(
        condition=CardsInYourGraveyardAtLeast(n=7),
        then_effect=AddManaToPool(produces=(("B", 5),)),
        else_effect=base,
    )
    assert _parse_instead_if_rider("Draw a card.", base, "X") is None
    assert _parse_instead_if_rider(
        "Add {B} instead if you control a Swamp.", base, "X",
    ) is None
    assert _parse_instead_if_rider(
        "Frobnicate instead if there are 3 or more cards in your graveyard.",
        base, "X",
    ) is None
    assert _parse_instead_if_condition(
        "there are 4 or more cards in your graveyard"
    ) == CardsInYourGraveyardAtLeast(n=4)
    assert _parse_instead_if_condition(
        "there are many or more cards in your graveyard"
    ) is None


def test_cube_printings_carry_substrate_fields(cube):
    assert cube["Faithless Looting"].flashback_cost_str == "{2}{R}"
    assert cube["Echo of Eons"].flashback_cost == parse_mana_cost("{2}{U}")
    assert cube["Treasure Cruise"].has_delve
    assert cube["Dig Through Time"].has_delve
    assert cube["Tinker"].additional_cost_sacrifice_filter == CardFilter(
        any_types=("Artifact",),
    )
    assert cube["Natural Order"].additional_cost_sacrifice_filter == CardFilter(
        any_types=("Creature",), color="G",
    )
    assert cube["Crop Rotation"].additional_cost_sacrifice_filter == CardFilter(
        any_types=("Land",),
    )
    assert isinstance(cube["Cabal Ritual"].spell_effect, IfConditionElse)


# ---------------------------------------------------------------------
# Flashback
# ---------------------------------------------------------------------


def _flashback_actions(state, pid=0):
    return [
        a for a in legal_actions(state, pid)
        if isinstance(a, CastSpell) and a.use_flashback
    ]


def test_faithless_looting_flashback_offered_and_exiles():
    state = make_state()
    for _ in range(4):
        add(state, 0, "Island", Zone.LIBRARY)
    looting = add(state, 0, "Faithless Looting", Zone.GRAVEYARD)
    add_lands(state, 0, "Mountain", 3)
    assert _flashback_actions(state) == [CastSpell(looting.id, use_flashback=True)]
    cast_and_resolve(state, 0, looting, use_flashback=True)
    p = state.players[0]
    assert looting in p.exile and looting.zone == Zone.EXILE
    assert looting not in p.graveyard
    assert not looting.cast_via_flashback
    assert len(p.graveyard) == 2  # the two discarded cards
    assert all(l.tapped for l in state.battlefield)


def test_flashback_not_offered_without_mana_or_off_timing():
    state = make_state()
    add(state, 0, "Faithless Looting", Zone.GRAVEYARD)
    add_lands(state, 0, "Mountain", 2)
    assert _flashback_actions(state) == []
    add_lands(state, 0, "Mountain", 1)
    state.step = Step.UPKEEP  # sorcery: not at instant speed
    assert _flashback_actions(state) == []


def test_countered_flashback_spell_is_exiled():
    state = make_state()
    card = add(state, 0, "Faithless Looting", Zone.STACK)
    card.cast_via_flashback = True
    state.stack.append(StackItem(source=card, controller_id=0, countered=True))
    resolve_top_of_stack(state)
    assert card in state.players[0].exile


def test_move_spell_off_stack_to_hand_reveals():
    state = make_state()
    card = add(state, 0, "Dark Ritual", Zone.STACK)
    move_spell_off_stack(state, card, destination="hand")
    assert card in state.players[0].hand
    assert card.publicly_known_to == frozenset({0, 1})


def test_instant_flashback_offered_at_instant_speed():
    import dataclasses

    state = make_state(step=Step.UPKEEP)
    ritual = add(state, 0, "Dark Ritual", Zone.GRAVEYARD)
    ritual.printing = dataclasses.replace(
        ritual.printing, flashback_cost=parse_mana_cost("{B}"),
        flashback_cost_str="{B}",
    )
    add_lands(state, 0, "Swamp", 1)
    assert _flashback_actions(state) == [CastSpell(ritual.id, use_flashback=True)]


def test_echo_of_eons_flashback_wheel():
    state = make_state()
    for pid in (0, 1):
        for _ in range(8):
            add(state, pid, "Island", Zone.LIBRARY)
    echo = add(state, 0, "Echo of Eons", Zone.GRAVEYARD)
    add_lands(state, 0, "Island", 3)
    cast_and_resolve(state, 0, echo, use_flashback=True)
    assert len(state.players[0].hand) == 7
    assert echo in state.players[0].exile


# ---------------------------------------------------------------------
# Delve
# ---------------------------------------------------------------------


def test_treasure_cruise_delve_legality_and_payment():
    agent = ScriptedAgent()
    state = make_state(agent0=agent)
    for _ in range(3):
        add(state, 0, "Island", Zone.LIBRARY)
    cruise = add(state, 0, "Treasure Cruise", Zone.HAND)
    add_lands(state, 0, "Island", 1)
    gy = [add(state, 0, "Swamp", Zone.GRAVEYARD) for _ in range(6)]
    # 1 land + 6 delve < 8: not castable.
    assert CastSpell(cruise.id) not in legal_actions(state, 0)
    add_lands(state, 0, "Island", 1)
    assert CastSpell(cruise.id) in legal_actions(state, 0)
    cast_and_resolve(state, 0, cruise)
    p = state.players[0]
    assert len(p.hand) == 3
    assert all(c in p.exile for c in gy)
    assert ("x", ("Treasure Cruise (delve)", 6)) in agent.calls


def test_pay_delve_prefers_non_flashback_and_respects_choice():
    agent = ScriptedAgent(x=[1])
    state = make_state(agent0=agent)
    card = add(state, 0, "Treasure Cruise", Zone.HAND)
    looting = add(state, 0, "Faithless Looting", Zone.GRAVEYARD)
    swamp = add(state, 0, "Swamp", Zone.GRAVEYARD)
    cost = pay_delve(state, 0, card, parse_mana_cost("{7}{U}"))
    assert cost == parse_mana_cost("{6}{U}")
    assert swamp in state.players[0].exile and looting in state.players[0].graveyard
    # Declining to delve (X=0) leaves the cost; no-delve card is a no-op.
    agent.scripts["x"] = [0]
    assert pay_delve(state, 0, card, parse_mana_cost("{7}{U}")) == parse_mana_cost("{7}{U}")
    ritual = add(state, 0, "Dark Ritual", Zone.HAND)
    assert pay_delve(state, 0, ritual, parse_mana_cost("{B}")) == parse_mana_cost("{B}")
    assert delve_affordability_cost(state, 0, ritual, parse_mana_cost("{2}")) == parse_mana_cost("{2}")
    # Nothing to delve / no generic: no prompt.
    state.players[0].graveyard.clear()
    assert pay_delve(state, 0, card, parse_mana_cost("{7}{U}")) == parse_mana_cost("{7}{U}")


# ---------------------------------------------------------------------
# Buyback
# ---------------------------------------------------------------------


def test_buyback_variant_and_return_to_hand():
    import dataclasses

    state = make_state()
    for _ in range(2):
        add(state, 0, "Island", Zone.LIBRARY)
    card = add(state, 0, "Ancestral Recall", Zone.HAND)
    card.printing = dataclasses.replace(
        card.printing, buyback_cost=parse_mana_cost("{2}"),
        buyback_cost_str="{2}",
    )
    add_lands(state, 0, "Island", 3)
    acts = legal_actions(state, 0)
    assert CastSpell(card.id) in acts
    assert CastSpell(card.id, use_buyback=True) in acts
    state.players[0].agent.scripts["target"] = [("player", 0)]
    cast_and_resolve(state, 0, card, use_buyback=True)
    assert card in state.players[0].hand
    assert all(l.tapped for l in state.battlefield)


def test_buyback_not_offered_when_unaffordable_and_sorcery_variant():
    import dataclasses

    state = make_state()
    card = add(state, 0, "Wheel of Fortune", Zone.HAND)
    card.printing = dataclasses.replace(
        card.printing, buyback_cost=parse_mana_cost("{3}"),
        buyback_cost_str="{3}",
    )
    add_lands(state, 0, "Mountain", 3)
    acts = legal_actions(state, 0)
    assert CastSpell(card.id) in acts
    assert CastSpell(card.id, use_buyback=True) not in acts
    add_lands(state, 0, "Mountain", 3)
    assert CastSpell(card.id, use_buyback=True) in legal_actions(state, 0)


def test_cost_plus():
    assert cost_plus(parse_mana_cost("{1}{B}"), None) == parse_mana_cost("{1}{B}")
    assert cost_plus(
        parse_mana_cost("{1}{B}"), parse_mana_cost("{2}{B}{U/P}"),
    ) == ManaCost(generic=3, colored=(("B", 2),), phyrexian=("U",))


# ---------------------------------------------------------------------
# Additional costs
# ---------------------------------------------------------------------


def test_tinker_sacrifices_artifact_and_fetches_artifact(cube):
    tinker_filter = cube["Tinker"].additional_cost_sacrifice_filter
    state = make_state()
    lib_art = add(state, 0, "Expedition Map", Zone.LIBRARY)
    add(state, 0, "Island", Zone.LIBRARY)
    tinker = add(state, 0, "Tinker", Zone.HAND)
    add_lands(state, 0, "Island", 3)
    # No artifact to sacrifice: not castable.
    assert not additional_costs_payable(state, 0, tinker)
    assert CastSpell(tinker.id) not in legal_actions(state, 0)
    fodder = add(state, 0, "Expedition Map", Zone.BATTLEFIELD)
    assert sacrifice_cost_options(state, 0, tinker) == [fodder]
    assert permanent_matches_filter(state, fodder, tinker_filter)
    assert CastSpell(tinker.id) in legal_actions(state, 0)
    cast_and_resolve(state, 0, tinker)
    assert fodder in state.players[0].graveyard
    assert lib_art in state.battlefield


def test_natural_order_needs_green_creature(cube):
    state = make_state()
    no = add(state, 0, "Natural Order", Zone.HAND)
    add_lands(state, 0, "Forest", 4)
    assert not additional_costs_payable(state, 0, no)
    # A non-green creature doesn't qualify.
    state_filter = cube["Natural Order"].additional_cost_sacrifice_filter
    assert pay_additional_sacrifice(state, 0, no) is None
    ritual_card = add(state, 0, "Dark Ritual", Zone.HAND)
    assert sacrifice_cost_options(state, 0, ritual_card) == []
    forest = state.battlefield[0]
    assert not permanent_matches_filter(state, forest, state_filter)
    assert permanent_matches_filter(
        state, forest, CardFilter(any_types=("Permanent",), excluded_types=("Creature",)),
    )
    assert not permanent_matches_filter(
        state, forest, CardFilter(any_types=("Land",), max_mv=-1),
    )
    assert not permanent_matches_filter(
        state, forest, CardFilter(any_types=("Land",), supertype="Legendary"),
    )
    assert not permanent_matches_filter(
        state, forest, CardFilter(excluded_types=("Land",)),
    )


def test_crop_rotation_sacrifices_land_for_land():
    state = make_state(agent0=ScriptedAgent())
    lib_land = add(state, 0, "Swamp", Zone.LIBRARY)
    crop = add(state, 0, "Crop Rotation", Zone.HAND)
    forest = add(state, 0, "Forest", Zone.BATTLEFIELD)
    extra = add(state, 0, "Forest", Zone.BATTLEFIELD)
    state.players[0].agent.scripts["sacrifice"] = [extra.id]
    cast_and_resolve(state, 0, crop)
    assert extra in state.players[0].graveyard
    assert forest in state.battlefield and forest.tapped
    assert lib_land in state.battlefield


def test_pay_x_life_bounds_and_choice():
    class _Capped:
        def useful_x_cap(self, state, controller_id):
            return 3

    class _Uncapped:
        def useful_x_cap(self, state, controller_id):
            return None

    import dataclasses

    state = make_state(agent0=ScriptedAgent(x=[99]))
    card = add(state, 0, "Dark Ritual", Zone.HAND)
    card.printing = dataclasses.replace(card.printing, spell_effect=_Capped())
    assert pay_x_life_upper_bound(state, 0, card) == 3
    assert choose_pay_x_life(state, 0, card) == 3  # clamped
    card.printing = dataclasses.replace(card.printing, spell_effect=_Uncapped())
    assert pay_x_life_upper_bound(state, 0, card) == 19
    state.players[0].agent = None
    assert choose_pay_x_life(state, 0, card) == 19


# ---------------------------------------------------------------------
# Threshold (Cabal Ritual)
# ---------------------------------------------------------------------


def test_cabal_ritual_threshold():
    state = make_state()
    ritual = add(state, 0, "Cabal Ritual", Zone.HAND)
    add_lands(state, 0, "Swamp", 2)
    cast_and_resolve(state, 0, ritual)
    assert len(state.players[0].mana_pool) == 3
    state = make_state()
    for _ in range(7):
        add(state, 0, "Island", Zone.GRAVEYARD)
    ritual = add(state, 0, "Cabal Ritual", Zone.HAND)
    add_lands(state, 0, "Swamp", 2)
    cast_and_resolve(state, 0, ritual)
    assert len(state.players[0].mana_pool) == 5


def test_if_condition_else_targeting_and_describe():
    from mtg_bot.effects.generic.card_flow import TargetPlayerDraws

    eff = IfConditionElse(
        condition=CardsInYourGraveyardAtLeast(n=1),
        then_effect=TargetPlayerDraws(1),
        else_effect=None,
    )
    state = make_state()
    assert eff.requires_target()
    assert eff.legal_targets(state, 0) == [("player", 0), ("player", 1)]
    assert eff.target_count_range() == (1, 1)
    assert eff.resolve(state, 0, (("player", 0),)) is None
    assert "if" in eff.describe()
    plain = IfConditionElse(
        condition=CardsInYourGraveyardAtLeast(n=1),
        then_effect=AddManaToPool(produces=(("B", 1),)),
        else_effect=AddManaToPool(produces=(("B", 2),)),
    )
    assert not plain.requires_target()
    assert plain.legal_targets(state, 0) == []
    assert plain.target_count_range() == (0, 0)
    assert "otherwise" in plain.describe()
    assert CardsInYourGraveyardAtLeast(n=0).matches(state, 99) is False


# ---------------------------------------------------------------------
# Phyrexian mana
# ---------------------------------------------------------------------


def test_parse_phyrexian_mana():
    c = parse_mana_cost("{1}{B/P}{B/P}")
    assert c.phyrexian == ("B", "B")
    assert c.total == 3
    assert c.colors == frozenset({"B"})
    assert c.reduced(1).phyrexian == ("B", "B")
    assert c.with_colored(["B"]) == ManaCost(generic=1, colored=(("B", 1),))


def test_phyrexian_affordable_with_life_or_mana():
    state = make_state()
    probe_cost = parse_mana_cost("{U/P}")
    assert can_pay_cost(state, 0, probe_cost)  # 2 life
    state.players[0].life = 1
    assert not can_pay_cost(state, 0, probe_cost)
    add_lands(state, 0, "Island", 1)
    assert can_pay_cost(state, 0, probe_cost)


def test_gitaxian_probe_paid_with_life_by_choice():
    state = make_state(agent0=ScriptedAgent(target=[("player", 1)]))
    add(state, 0, "Island", Zone.LIBRARY)
    hidden = add(state, 1, "Swamp", Zone.HAND)
    probe = add(state, 0, "Gitaxian Probe", Zone.HAND)
    land = add(state, 0, "Island", Zone.BATTLEFIELD)
    cast_and_resolve(state, 0, probe)  # default yes -> pay life
    p0 = state.players[0]
    assert p0.life == 18
    assert not land.tapped
    assert len(p0.hand) == 1
    assert 0 in hidden.publicly_known_to


def test_phyrexian_pays_mana_when_declining_life():
    state = make_state(agent0=ScriptedAgent(target=[("player", 1)], yes_no=[False]))
    add(state, 0, "Island", Zone.LIBRARY)
    probe = add(state, 0, "Gitaxian Probe", Zone.HAND)
    land = add(state, 0, "Island", Zone.BATTLEFIELD)
    cast_and_resolve(state, 0, probe)
    assert state.players[0].life == 20
    assert land.tapped


def test_phyrexian_forced_mana_at_low_life():
    state = make_state(agent0=ScriptedAgent(target=[("player", 1)]))
    state.players[0].life = 1
    add(state, 0, "Island", Zone.LIBRARY)
    probe = add(state, 0, "Gitaxian Probe", Zone.HAND)
    land = add(state, 0, "Island", Zone.BATTLEFIELD)
    cast_and_resolve(state, 0, probe)
    assert state.players[0].life == 1
    assert land.tapped


def test_auto_tap_pays_unsettled_phyrexian_with_mana():
    from mtg_bot.actions import auto_tap_for_cost

    state = make_state()
    land = add(state, 0, "Island", Zone.BATTLEFIELD)
    tapped = auto_tap_for_cost(state, 0, parse_mana_cost("{U/P}"))
    assert tapped == [land]


def test_natural_order_sacrifices_green_creature_fetches_green_creature():
    from mtg_bot.cards import SYNTHETIC_CREATURES

    state = make_state()
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD)
    bear.summoning_sick = False
    state.battlefield.append(bear)
    red = state.new_object(SYNTHETIC_CREATURES["Stone Ogre"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(red)
    wurm = state.new_object(SYNTHETIC_CREATURES["Great Wurm"], 0, Zone.LIBRARY)
    state.players[0].library.append(wurm)
    no = add(state, 0, "Natural Order", Zone.HAND)
    add_lands(state, 0, "Forest", 4)
    assert sacrifice_cost_options(state, 0, no) == [bear]
    # Creature exclusion reads the layered creature check too.
    assert not permanent_matches_filter(
        state, bear, CardFilter(excluded_types=("Creature",)),
    )
    cast_and_resolve(state, 0, no)
    assert bear in state.players[0].graveyard
    assert wurm in state.battlefield


def test_lorien_revealed_islandcycling_from_hand(cube):
    from mtg_bot.actions import ActivateAbility

    lorien = next(p for n, p in cube.items() if n.startswith("L") and n.endswith("Revealed"))
    assert lorien.landcycling == ("Island", "{1}")
    (ability,) = lorien.hand_activated_abilities
    assert ability.cost.discard_self
    state = make_state()
    island = add(state, 0, "Island", Zone.LIBRARY)
    add(state, 0, "Swamp", Zone.LIBRARY)
    card = state.new_object(lorien, 0, Zone.HAND)
    state.players[0].hand.append(card)
    add_lands(state, 0, "Swamp", 1)
    act = ActivateAbility(card.id, 0)
    assert act in legal_actions(state, 0)
    apply_action(state, 0, act)
    resolve_top_of_stack(state)
    assert card in state.players[0].graveyard
    assert island in state.players[0].hand
    assert CardFilter(subtype="Island").describe() == "Island card"
