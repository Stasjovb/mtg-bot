"""Line-composed land grammar (``mtg_bot.cards.parser.land_lines``).

Covers the per-line recognizers (intrinsic-mana reminder, enters-tapped
[unless], Cycling, triggered lines, activated/mana lines) on the
PowerLSV cube lands they claim, the fall-through paths on hypothetical
printings, and the engine behavior the resulting printings drive:
conditional ETB tapping, surveil ETB, cycling from hand, and life-costed
automatic mana payment.
"""

from __future__ import annotations

import pytest

from mtg_bot.actions import (
    ActivateAbility,
    _activate_ability,
    _play_land,
    _untapped_lands,
    apply_action,
    auto_tap_for_cost,
    can_pay_cost,
    resolve_top_of_stack,
)
from mtg_bot.agents import RandomAgent
from mtg_bot.cards.base import (
    AddManaToPool,
    AddNManaOfChosenColor,
    DrawCards,
    ManaCost,
    PutPlusOneCounterOnEachCreatureYouControl,
    Surveil,
    make_basic_land,
    make_utility_land,
    parse_mana_cost,
)
from mtg_bot.cards.parser.land_builder import _build_land_printing
from mtg_bot.cards.parser.land_lines import _try_build_line_composed_land
from mtg_bot.cards.parser_source import OracleParserCardSource
from mtg_bot.effects.conditions import ControlPermanent, ControlsAtMost
from mtg_bot.effects.object_predicates import HasSubtype, IsBasic, IsLand
from mtg_bot.effects.predicates import Event, IsSelf
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step


@pytest.fixture(scope="module")
def cube() -> dict:
    return OracleParserCardSource(pool="cube").get_printings()


def _land(name: str, type_line: str, oracle: str) -> dict:
    return {"name": name, "type_line": type_line, "oracle_text": oracle}


class _Agent(RandomAgent):
    """RandomAgent with deterministic surveil / discard answers."""

    def __init__(self, *, surveil_to_graveyard: bool = False) -> None:
        super().__init__()
        self._surveil_to_graveyard = surveil_to_graveyard

    def choose_surveil(self, state, player_id, top_card_id):
        return self._surveil_to_graveyard


def _state(life: int = 20) -> GameState:
    state = GameState()
    state.players.append(Player(id=0, life=life, agent=_Agent()))
    state.players.append(Player(id=1, life=20, agent=_Agent()))
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state: GameState, printing, player_id: int = 0, *, tapped=False):
    obj = state.new_object(printing, player_id, Zone.BATTLEFIELD)
    obj.tapped = tapped
    obj.summoning_sick = False
    state.battlefield.append(obj)
    return obj


def _in_hand(state: GameState, printing, player_id: int = 0):
    obj = state.new_object(printing, player_id, Zone.HAND)
    state.players[player_id].hand.append(obj)
    return obj


def _in_library(state: GameState, printing, player_id: int = 0):
    obj = state.new_object(printing, player_id, Zone.LIBRARY)
    state.players[player_id].library.append(obj)
    return obj


PLAINS = make_basic_land("Plains", "W")
ISLAND = make_basic_land("Island", "U")
FOREST = make_basic_land("Forest", "G")


# --- original duals: intrinsic-mana reminder only --------------------------


@pytest.mark.parametrize(
    "name,subtypes,colors",
    [
        ("Badlands", ("Swamp", "Mountain"), {"B", "R"}),
        ("Bayou", ("Swamp", "Forest"), {"B", "G"}),
        ("Plateau", ("Mountain", "Plains"), {"R", "W"}),
        ("Savannah", ("Forest", "Plains"), {"G", "W"}),
        ("Scrubland", ("Plains", "Swamp"), {"W", "B"}),
        ("Taiga", ("Mountain", "Forest"), {"R", "G"}),
        ("Tropical Island", ("Forest", "Island"), {"G", "U"}),
        ("Tundra", ("Plains", "Island"), {"W", "U"}),
        ("Underground Sea", ("Island", "Swamp"), {"U", "B"}),
        ("Volcanic Island", ("Island", "Mountain"), {"U", "R"}),
    ],
)
def test_original_duals_claimed(cube, name, subtypes, colors):
    p = cube[name]
    assert p.subtypes == subtypes
    assert p.produces == frozenset(colors)
    assert p.mana_only_from_produces is True
    assert p.enters_tapped is False
    assert p.enters_tapped_unless is None
    assert p.activated_abilities == ()
    assert p.triggered_abilities == ()


def test_intrinsic_reminder_must_match_basic_types():
    card = _land("Wrong Dual", "Land — Plains Island", "({T}: Add {W} or {B}.)")
    assert _build_land_printing(card) is None


def test_intrinsic_reminder_requires_basic_types():
    card = _land("Typeless", "Land", "({T}: Add {W} or {U}.)")
    assert _build_land_printing(card) is None


def test_unrecognized_parenthetical_line_falls_through():
    card = _land("Odd", "Land", "(This is just reminder text.)")
    assert _build_land_printing(card) is None


def test_tundra_pays_either_color():
    state = _state()
    _put(state, _build_land_printing(
        _land("Tundra", "Land — Plains Island", "({T}: Add {W} or {U}.)")
    ))
    assert can_pay_cost(state, 0, parse_mana_cost("{U}"))
    assert can_pay_cost(state, 0, parse_mana_cost("{W}"))
    assert not can_pay_cost(state, 0, parse_mana_cost("{B}"))


# --- enters tapped / enters tapped unless ---------------------------------


FAST_LANDS = (
    "Blackcleave Cliffs", "Blooming Marsh", "Botanical Sanctum",
    "Concealed Courtyard", "Copperline Gorge", "Darkslick Shores",
    "Inspiring Vantage", "Razorverge Thicket", "Seachrome Coast",
    "Spirebluff Canal",
)


@pytest.mark.parametrize("name", FAST_LANDS)
def test_fast_lands_claimed(cube, name):
    p = cube[name]
    assert p.enters_tapped is False
    assert p.enters_tapped_unless == ControlsAtMost(IsLand(), 2)
    assert len(p.produces) == 2
    assert p.activated_abilities == ()


@pytest.mark.parametrize("others,expect_tapped", [(0, False), (2, False), (3, True)])
def test_fast_land_etb(cube, others, expect_tapped):
    state = _state()
    for _ in range(others):
        _put(state, PLAINS)
    _put(state, PLAINS, player_id=1)  # opponent's lands don't count
    card = _in_hand(state, cube["Seachrome Coast"])
    _play_land(state, 0, card.id)
    assert card.tapped is expect_tapped
    assert card in state.battlefield


def test_check_land_basic_condition(cube):
    temple = cube["Abandoned Air Temple"]
    assert temple.enters_tapped_unless == ControlPermanent(IsLand() & IsBasic())
    assert temple.produces == frozenset({"W"})
    (pump,) = temple.activated_abilities
    assert pump.cost.mana_str == "{3}{W}" and pump.cost.tap_self
    assert pump.effect == PutPlusOneCounterOnEachCreatureYouControl(amount=1)

    state = _state()
    _put(state, cube["Tundra"])  # nonbasic Plains: not a basic land
    card = _in_hand(state, temple)
    _play_land(state, 0, card.id)
    assert card.tapped is True

    state = _state()
    _put(state, ISLAND)
    card = _in_hand(state, temple)
    _play_land(state, 0, card.id)
    assert card.tapped is False


def test_check_land_subtype_condition_reads_effective_subtypes(cube):
    card = _land(
        "Hypothetical Check", "Land",
        "This land enters tapped unless you control a Mountain.\n"
        "{T}: Add {R}.",
    )
    p = _build_land_printing(card)
    assert p.enters_tapped_unless == ControlPermanent(HasSubtype("Mountain"))
    state = _state()
    _put(state, cube["Badlands"])  # Swamp Mountain dual counts
    obj = _in_hand(state, p)
    _play_land(state, 0, obj.id)
    assert obj.tapped is False


@pytest.mark.parametrize(
    "line",
    [
        "This land enters tapped unless you control twenty or fewer other lands.",
        "This land enters tapped unless you control a Wastes.",
        "This land enters tapped unless a moon is full.",
    ],
)
def test_unrecognized_enters_tapped_condition_falls_through(line):
    assert _build_land_printing(_land("X", "Land", line + "\n{T}: Add {W}.")) is None


@pytest.mark.parametrize(
    "text",
    [
        "This land enters tapped.\nThis land enters tapped.\n{T}: Add {W}.",
        "This land enters tapped.\n"
        "This land enters tapped unless you control a Plains.\n{T}: Add {W}.",
        "This land enters tapped unless you control a Plains.\n"
        "This land enters tapped.\n{T}: Add {W}.",
    ],
)
def test_duplicate_enters_tapped_lines_fall_through(text):
    assert _build_land_printing(_land("X", "Land", text)) is None


# --- surveil lands ---------------------------------------------------------


SURVEIL_LANDS = (
    "Commercial District", "Elegant Parlor", "Hedge Maze", "Lush Portico",
    "Meticulous Archive", "Raucous Theater", "Shadowy Backstreet",
    "Thundering Falls", "Undercity Sewers", "Underground Mortuary",
)


@pytest.mark.parametrize("name", SURVEIL_LANDS)
def test_surveil_lands_claimed(cube, name):
    p = cube[name]
    assert p.enters_tapped is True
    assert len(p.subtypes) == 2 and len(p.produces) == 2
    (trig,) = p.triggered_abilities
    assert trig.event == Event.ENTERS and trig.predicate == IsSelf()
    assert trig.effect == Surveil(amount=1)


@pytest.mark.parametrize("to_graveyard", [True, False])
def test_surveil_land_etb_surveils(cube, to_graveyard):
    state = _state()
    state.players[0].agent = _Agent(surveil_to_graveyard=to_graveyard)
    top = _in_library(state, PLAINS)
    card = _in_hand(state, cube["Meticulous Archive"])
    _play_land(state, 0, card.id)
    assert card.tapped is True
    assert len(state.stack) == 1
    resolve_top_of_stack(state)
    p = state.players[0]
    assert (top in p.graveyard) is to_graveyard
    assert (top in p.library) is not to_graveyard


def test_unparseable_trigger_line_falls_through():
    card = _land(
        "X", "Land",
        "When this land enters, frobnicate the widget.\n{T}: Add {W}.",
    )
    assert _build_land_printing(card) is None


# --- triomes: Cycling from hand -------------------------------------------


TRIOMES = (
    "Indatha Triome", "Jetmir's Garden", "Ketria Triome", "Raffine's Tower",
    "Raugrin Triome", "Savai Triome", "Spara's Headquarters",
    "Xander's Lounge", "Zagoth Triome", "Ziatora's Proving Ground",
)


@pytest.mark.parametrize("name", TRIOMES)
def test_triomes_claimed(cube, name):
    p = cube[name]
    assert p.enters_tapped is True
    assert len(p.subtypes) == 3 and len(p.produces) == 3
    (cycling,) = p.hand_activated_abilities
    assert cycling.cost.mana_str == "{3}"
    assert cycling.cost.discard_self is True
    assert cycling.cost.tap_self is False
    assert cycling.effect == DrawCards(amount=1)
    assert p.activated_abilities == ()


def test_cycling_offered_only_when_affordable(cube):
    state = _state()
    triome = _in_hand(state, cube["Ketria Triome"])
    _put(state, ISLAND)
    _put(state, ISLAND)
    assert ActivateAbility(triome.id, 0) not in legal_actions(state, 0)
    _put(state, ISLAND)
    assert ActivateAbility(triome.id, 0) in legal_actions(state, 0)


def test_cycling_dedups_same_name_copies(cube):
    state = _state()
    a = _in_hand(state, cube["Ketria Triome"])
    b = _in_hand(state, cube["Ketria Triome"])
    for _ in range(3):
        _put(state, ISLAND)
    acts = [
        x for x in legal_actions(state, 0) if isinstance(x, ActivateAbility)
    ]
    assert acts == [ActivateAbility(a.id, 0)]
    assert b.id not in {x.source_id for x in acts}


def test_cycling_not_offered_outside_sorcery_window(cube):
    state = _state()
    triome = _in_hand(state, cube["Ketria Triome"])
    for _ in range(3):
        _put(state, ISLAND)
    state.step = Step.UPKEEP
    assert ActivateAbility(triome.id, 0) not in legal_actions(state, 0)


def test_cycling_pays_discards_and_draws(cube):
    state = _state()
    triome = _in_hand(state, cube["Ketria Triome"])
    drawn = _in_library(state, FOREST)
    lands = [_put(state, ISLAND) for _ in range(3)]
    apply_action(state, 0, ActivateAbility(triome.id, 0))
    p = state.players[0]
    assert triome in p.graveyard and triome not in p.hand
    assert triome.zone == Zone.GRAVEYARD
    assert all(land.tapped for land in lands)
    assert len(state.stack) == 1
    item = state.stack[-1]
    assert item.source is triome and item.cost_paid_objects == (triome,)
    resolve_top_of_stack(state)
    assert drawn in p.hand


def test_hand_ability_activation_ignores_bad_index_and_foreign_card(cube):
    state = _state()
    triome = _in_hand(state, cube["Ketria Triome"])
    for _ in range(3):
        _put(state, ISLAND)
    _activate_ability(state, 0, triome.id, 5)
    assert triome in state.players[0].hand and not state.stack
    # Not in the activator's hand: no-op.
    _activate_ability(state, 1, triome.id, 0)
    assert triome in state.players[0].hand and not state.stack


def test_hand_ability_with_target_and_no_mana_cost():
    """Hand abilities choose targets before the discard and may have no
    mana cost; an ability whose effect needs a missing target isn't
    offered."""
    from mtg_bot.cards.base import (
        ActivatedAbility, ActivationCost, DestroyTargetLand,
    )
    from dataclasses import replace

    ability = ActivatedAbility(
        cost=ActivationCost(discard_self=True),
        effect=DestroyTargetLand(),
    )
    printing = replace(
        make_utility_land("Hand Wrecker"),
        hand_activated_abilities=(ability,),
    )
    state = _state()
    card = _in_hand(state, printing)
    assert ActivateAbility(card.id, 0) not in legal_actions(state, 0)
    victim = _put(state, PLAINS, player_id=1)
    assert ActivateAbility(card.id, 0) in legal_actions(state, 0)
    apply_action(state, 0, ActivateAbility(card.id, 0))
    assert state.stack[-1].targets == (("land", victim.id),) or (
        state.stack[-1].targets and state.stack[-1].targets[0][1] == victim.id
    )
    resolve_top_of_stack(state)
    assert victim not in state.battlefield


# --- horizon lands: life-costed mana ---------------------------------------


HORIZON_LANDS = {
    "Fiery Islet": {"U", "R"},
    "Horizon Canopy": {"G", "W"},
    "Nurturing Peatland": {"B", "G"},
    "Sunbaked Canyon": {"R", "W"},
    "Waterlogged Grove": {"G", "U"},
}


@pytest.mark.parametrize("name", sorted(HORIZON_LANDS))
def test_horizon_lands_claimed(cube, name):
    p = cube[name]
    assert p.produces == frozenset(HORIZON_LANDS[name])
    assert p.produces_life_cost == 1
    (sac_draw,) = p.activated_abilities
    assert sac_draw.cost.mana_str == "{1}"
    assert sac_draw.cost.tap_self and sac_draw.cost.sacrifice_self
    assert sac_draw.effect == DrawCards(amount=1)


def test_horizon_land_auto_pay_charges_life(cube):
    state = _state()
    canopy = _put(state, cube["Horizon Canopy"])
    assert can_pay_cost(state, 0, parse_mana_cost("{G}"))
    tapped = auto_tap_for_cost(state, 0, parse_mana_cost("{G}"))
    assert tapped == [canopy]
    assert state.players[0].life == 19


def test_horizon_land_is_tapped_after_free_lands(cube):
    state = _state()
    canopy = _put(state, cube["Horizon Canopy"])
    forest = _put(state, FOREST)
    assert _untapped_lands(state, 0) == [forest, canopy]
    auto_tap_for_cost(state, 0, parse_mana_cost("{1}"))
    assert forest.tapped and not canopy.tapped
    assert state.players[0].life == 20


def test_horizon_land_unavailable_when_life_would_hit_zero(cube):
    state = _state(life=1)
    _put(state, cube["Horizon Canopy"])
    assert not can_pay_cost(state, 0, parse_mana_cost("{G}"))
    state = _state(life=2)
    _put(state, cube["Horizon Canopy"])
    _put(state, cube["Waterlogged Grove"])
    # Two life-costed lands but only one life to spare.
    assert can_pay_cost(state, 0, parse_mana_cost("{G}"))
    assert not can_pay_cost(state, 0, parse_mana_cost("{G}{G}"))


def test_horizon_land_life_cost_waived_under_type_rewrite(cube):
    """A layer-4 basic-land-type rewrite replaces the printed mana
    ability with a free intrinsic one — no life charge."""
    state = _state()
    canopy = _put(state, cube["Horizon Canopy"])
    state.add_continuous_effect(
        source_id=canopy.id, layer=4, kind="set_basic_land_subtype",
        target_id=canopy.id, params=("Mountain",),
    )
    auto_tap_for_cost(state, 0, parse_mana_cost("{1}"))
    assert canopy.tapped and state.players[0].life == 20


# --- mana folding rules ----------------------------------------------------


def test_mana_only_from_produces_land_without_mana_is_not_a_source():
    p = _build_land_printing(
        _land("Hypothetical Fetch", "Land",
              "{T}, Sacrifice this land: Draw a card.")
    )
    assert p.produces == frozenset() and p.mana_only_from_produces
    state = _state()
    _put(state, p)
    assert _untapped_lands(state, 0) == []
    assert not can_pay_cost(state, 0, parse_mana_cost("{1}"))


def test_legacy_land_without_produces_still_pays_generic():
    state = _state()
    _put(state, make_utility_land("Legacy Colorless"))
    assert can_pay_cost(state, 0, parse_mana_cost("{1}"))


def test_mixed_free_and_life_mana_keeps_life_ability_explicit():
    p = _build_land_printing(
        _land("Hypothetical Town", "Land",
              "{T}, Pay 1 life: Add {W} or {U}.\n{T}: Add {C}.")
    )
    assert p.produces == frozenset({"C"})
    assert p.produces_life_cost == 0
    (life,) = p.activated_abilities
    assert life.is_mana_ability and life.cost.pay_life == 1
    assert life.effect == AddNManaOfChosenColor(amount=1, options=("W", "U"))


def test_distinct_life_costs_stay_explicit():
    p = _build_land_printing(
        _land("Hypothetical Pricey", "Land",
              "{T}, Pay 1 life: Add {W}.\n{T}, Pay 2 life: Add {U}.")
    )
    assert p.produces == frozenset()
    assert len(p.activated_abilities) == 2


def test_multi_mana_tap_kept_explicit_and_listed_in_produces():
    p = _build_land_printing(
        _land("Hypothetical Sol Land", "Land", "{T}: Add {C}{C}.")
    )
    assert p.produces == frozenset({"C"})
    (ability,) = p.activated_abilities
    assert ability.is_mana_ability
    assert ability.effect == AddManaToPool(produces=(("C", 2),))


def test_restricted_mana_stays_explicit_only():
    p = _build_land_printing(
        _land("Hypothetical Shop", "Land",
              "{T}: Add {C}{C}{C}. Spend this mana only to cast artifact "
              "spells.")
    )
    assert p.produces == frozenset()
    (ability,) = p.activated_abilities
    assert ability.effect.spend_restriction is not None


# --- scope gates -----------------------------------------------------------


@pytest.mark.parametrize(
    "type_line",
    ["Artifact Land", "Snow Land", "Basic Land — Plains", "Creature — Elf"],
)
def test_non_plain_land_type_lines_fall_through(type_line):
    card = _land("X", type_line, "{T}: Add {W}.")
    from mtg_bot.cards.parser.type_line import _parse_type_line

    supertypes, card_types, subtypes = _parse_type_line(type_line)
    assert _try_build_line_composed_land(
        card, card["oracle_text"], supertypes, card_types, subtypes,
    ) is None


def test_empty_text_falls_through():
    assert _try_build_line_composed_land(
        _land("X", "Land", ""), "", (), ("Land",), (),
    ) is None


def test_unparseable_activated_line_falls_through():
    card = _land("X", "Land", "{T}: Add {W}.\n{T}: Frobnicate the widget.")
    assert _build_land_printing(card) is None


def test_legendary_land_keeps_supertype():
    p = _build_land_printing(
        _land("Hypothetical Legend", "Legendary Land", "{T}: Add {G}.")
    )
    assert p.is_legendary and p.produces == frozenset({"G"})
    assert p.type_line == "Legendary Land"


# --- helper edge cases -------------------------------------------------------


def test_simple_and_multi_mana_helpers():
    from mtg_bot.cards.parser.land_lines import (
        _multi_mana_kind,
        _simple_mana_colors,
    )

    assert _simple_mana_colors(
        AddManaToPool(produces=(("C", 1),), spend_restriction="artifact_spell")
    ) is None
    assert _simple_mana_colors(
        AddManaToPool(produces=(("W", 1), ("U", 1)))
    ) is None
    assert _simple_mana_colors(AddManaToPool(produces=(("any", 1),))) is None
    assert _simple_mana_colors(AddManaToPool(produces=(("G", 1),))) == {"G"}
    assert _simple_mana_colors(
        AddNManaOfChosenColor(amount=3, options=("W", "U"))
    ) is None
    assert _simple_mana_colors(DrawCards(amount=1)) is None
    assert _multi_mana_kind(DrawCards(amount=1)) is None
    assert _multi_mana_kind(
        AddManaToPool(produces=(("C", 2),), spend_restriction="x")
    ) is None
    assert _multi_mana_kind(AddManaToPool(produces=(("any", 2),))) is None
    assert _multi_mana_kind(AddManaToPool(produces=(("C", 1),))) is None
    assert _multi_mana_kind(AddManaToPool(produces=(("C", 3),))) == "C"


def test_choose_ability_targets_edges():
    from mtg_bot.actions import _choose_ability_targets
    from mtg_bot.cards.base import DestroyTargetLand

    state = _state()
    src = _put(state, PLAINS)
    # Untargeted effect / no legal target.
    assert _choose_ability_targets(state, 0, src, DrawCards(amount=1)) == ()
    assert _choose_ability_targets(
        state, 0, src, DestroyTargetLand(nonbasic_only=True),
    ) == ()
    victim = _put(state, ISLAND, player_id=1)
    # Agent declines -> nothing chosen; no agent -> first legal target.
    class Decline(_Agent):
        def choose_target(self, state, player_id, legal_targets):
            return None

    state.players[0].agent = Decline()
    assert _choose_ability_targets(state, 0, src, DestroyTargetLand()) == ()
    state.players[0].agent = None
    picked = _choose_ability_targets(state, 0, src, DestroyTargetLand())
    assert len(picked) == 1 and picked[0][1] in {src.id, victim.id}


def test_choose_ability_targets_slot_kinds_and_zero_max():
    from mtg_bot.actions import _choose_ability_targets
    from mtg_bot.effects.base import Effect

    class Odd(Effect):
        def requires_target(self):
            return True

        def legal_targets(self, state, controller_id):
            return [("permanent", 1)]

        def target_count_range(self):
            return (0, 0)

        def target_slot_kinds(self):
            return ("creature",)

    state = _state()
    src = _put(state, PLAINS)
    # max 0 is treated as 1; the only slot wants a creature -> empty pool.
    assert _choose_ability_targets(state, 0, src, Odd()) == ()


def test_scaling_mana_and_boseiju_nouns_are_closed():
    from mtg_bot.cards.parser.effects import _parse_effect

    assert _parse_effect("add {G} for each frog you control") is None
    assert _parse_effect(
        "destroy target creature an opponent controls. That player may "
        "search their library for a land card with a basic land type, put "
        "it onto the battlefield, then shuffle"
    ) is None
