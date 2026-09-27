"""Engine behavior of PowerLSV cube lands claimed through the
line-composed land grammar: fetch lands, Karakas, Library of
Alexandria, Gaea's Cradle / Tolarian Academy, City of Traitors,
Wasteland, Mishra's Workshop — plus the parser surfaces they introduced
(``SearchLibraryForLandCardToBattlefield``, the ``return target <noun>
to its owner's hand`` bounce, ``Activate only if``, scaling mana,
``you play another land``, ``sacrifice this <type>``).
"""

from __future__ import annotations

import pytest

from mtg_bot.actions import (
    ActivateAbility,
    PlayLand,
    _activate_ability,
    _play_land,
    apply_action,
    can_pay_cost,
    resolve_top_of_stack,
)
from mtg_bot.agents import RandomAgent
from mtg_bot.cards.base import (
    DestroyTargetLand,
    DrawCards,
    make_basic_land,
    make_creature,
    parse_mana_cost,
)
from mtg_bot.cards.parser.activated import (
    _parse_activate_only_if_condition,
    _parse_activated_ability_line,
)
from mtg_bot.cards.parser.effects import _parse_effect
from mtg_bot.cards.parser.land_builder import _build_land_printing
from mtg_bot.cards.parser_source import OracleParserCardSource
from mtg_bot.effects.conditions import HandSizeExactly
from mtg_bot.effects.formulas import CountControlledMatching
from mtg_bot.effects.generic import (
    AddManaOfColorPerCount,
    Bounce,
    SacrificeSelf,
    SearchLibraryForBasicLandTapped,
    SearchLibraryForLandCardToBattlefield,
)
from mtg_bot.effects.object_predicates import (
    IsArtifact,
    IsCreature,
    IsLegendary,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step


@pytest.fixture(scope="module")
def cube() -> dict:
    return OracleParserCardSource(pool="cube").get_printings()


class _Agent(RandomAgent):
    """Deterministic picks: first library option / first target."""

    def __init__(self, *, decline_search: bool = False) -> None:
        super().__init__()
        self._decline = decline_search

    def choose_card_from_library(self, state, player_id, option_ids):
        if self._decline or not option_ids:
            return None
        return option_ids[0]

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_surveil(self, state, player_id, top_card_id):
        return False

    def choose_pay_shock_life(self, state, player_id, life_cost):
        return True


def _state(agent=None) -> GameState:
    state = GameState()
    state.players.append(Player(id=0, life=20, agent=agent or _Agent()))
    state.players.append(Player(id=1, life=20, agent=_Agent()))
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, player_id=0):
    obj = state.new_object(printing, player_id, Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.battlefield.append(obj)
    return obj


def _zone(state, printing, zone_name, player_id=0):
    zone = {"hand": Zone.HAND, "library": Zone.LIBRARY}[zone_name]
    obj = state.new_object(printing, player_id, zone)
    getattr(state.players[player_id], zone_name).append(obj)
    return obj


PLAINS = make_basic_land("Plains", "W")
MOUNTAIN = make_basic_land("Mountain", "R")
ISLAND = make_basic_land("Island", "U")


# --- fetch lands -----------------------------------------------------------


FETCHES = {
    "Arid Mesa": ("Mountain", "Plains"),
    "Bloodstained Mire": ("Swamp", "Mountain"),
    "Flooded Strand": ("Plains", "Island"),
    "Marsh Flats": ("Plains", "Swamp"),
    "Misty Rainforest": ("Forest", "Island"),
    "Polluted Delta": ("Island", "Swamp"),
    "Scalding Tarn": ("Island", "Mountain"),
    "Verdant Catacombs": ("Swamp", "Forest"),
    "Windswept Heath": ("Forest", "Plains"),
    "Wooded Foothills": ("Mountain", "Forest"),
}


@pytest.mark.parametrize("name", sorted(FETCHES))
def test_fetch_lands_claimed(cube, name):
    p = cube[name]
    assert p.produces == frozenset() and p.mana_only_from_produces
    (fetch,) = p.activated_abilities
    assert fetch.cost.tap_self and fetch.cost.sacrifice_self
    assert fetch.cost.pay_life == 1
    assert fetch.effect == SearchLibraryForLandCardToBattlefield(
        land_types=FETCHES[name],
    )


def test_prismatic_vista_claimed(cube):
    (fetch,) = cube["Prismatic Vista"].activated_abilities
    assert fetch.cost.pay_life == 1
    assert fetch.effect == SearchLibraryForLandCardToBattlefield(
        basic_only=True,
    )


def test_fetch_is_not_a_mana_source(cube):
    state = _state()
    _put(state, cube["Arid Mesa"])
    assert not can_pay_cost(state, 0, parse_mana_cost("{1}"))


def test_fetch_finds_typed_nonbasic_untapped(cube):
    state = _state()
    mesa = _put(state, cube["Arid Mesa"])
    island = _zone(state, ISLAND, "library")
    plateau = _zone(state, cube["Plateau"], "library")
    assert ActivateAbility(mesa.id, 0) in legal_actions(state, 0)
    apply_action(state, 0, ActivateAbility(mesa.id, 0))
    assert state.players[0].life == 19
    assert mesa not in state.battlefield
    resolve_top_of_stack(state)
    assert plateau in state.battlefield and plateau.tapped is False
    assert plateau.zone == Zone.BATTLEFIELD and not plateau.summoning_sick
    assert island in state.players[0].library
    assert state.players[0].lands_entered_this_turn == 1


def test_fetched_land_applies_its_own_entry_rules(cube):
    """A fetched surveil land enters tapped and its ENTERS trigger
    fires; a fetched shock land offers its life payment."""
    state = _state()
    strand = _put(state, cube["Flooded Strand"])
    archive = _zone(state, cube["Meticulous Archive"], "library")
    _zone(state, ISLAND, "library")
    apply_action(state, 0, ActivateAbility(strand.id, 0))
    resolve_top_of_stack(state)
    assert archive in state.battlefield and archive.tapped is True
    assert len(state.stack) == 1  # surveil trigger
    assert state.stack[-1].source is archive


def test_fetch_can_fail_to_find_and_still_shuffles(cube, monkeypatch):
    state = _state(agent=_Agent(decline_search=True))
    mesa = _put(state, cube["Arid Mesa"])
    plains = _zone(state, PLAINS, "library")
    shuffled = []
    import mtg_bot.game as game_mod

    real = game_mod.shuffle_library
    monkeypatch.setattr(
        game_mod, "shuffle_library",
        lambda st, pid: (shuffled.append(pid), real(st, pid)),
    )
    apply_action(state, 0, ActivateAbility(mesa.id, 0))
    resolve_top_of_stack(state)
    assert plains in state.players[0].library
    assert shuffled == [0]


def test_fetch_with_no_matching_card(cube):
    state = _state()
    mesa = _put(state, cube["Arid Mesa"])
    island = _zone(state, ISLAND, "library")
    apply_action(state, 0, ActivateAbility(mesa.id, 0))
    resolve_top_of_stack(state)
    assert island in state.players[0].library
    assert not any(o.printing.is_land for o in state.battlefield)


def test_prismatic_vista_finds_only_basics(cube):
    state = _state()
    vista = _put(state, cube["Prismatic Vista"])
    _zone(state, cube["Tundra"], "library")
    plains = _zone(state, PLAINS, "library")
    apply_action(state, 0, ActivateAbility(vista.id, 0))
    resolve_top_of_stack(state)
    assert plains in state.battlefield


def test_search_effect_describe_and_matching():
    e = SearchLibraryForLandCardToBattlefield(land_types=("Island", "Swamp"))
    assert "Island or Swamp card" in e.describe()
    assert "basic land card" in SearchLibraryForLandCardToBattlefield(
        basic_only=True, tapped=True,
    ).describe()
    assert "tapped" in SearchLibraryForLandCardToBattlefield(
        tapped=True,
    ).describe()
    # Non-lands never match even with a matching subtype string.
    assert not e._matches(make_creature("Island Bear", "{1}", 1, 1))
    assert SearchLibraryForLandCardToBattlefield()._matches(PLAINS)


@pytest.mark.parametrize(
    "phrase,expected",
    [
        (
            "search your library for a Mountain or Plains card, put it "
            "onto the battlefield, then shuffle",
            SearchLibraryForLandCardToBattlefield(
                land_types=("Mountain", "Plains"),
            ),
        ),
        (
            "search your library for an Island card, put it onto the "
            "battlefield tapped, then shuffle",
            SearchLibraryForLandCardToBattlefield(
                land_types=("Island",), tapped=True,
            ),
        ),
        (
            "search your library for a basic land card, put it onto the "
            "battlefield, then shuffle",
            SearchLibraryForLandCardToBattlefield(basic_only=True),
        ),
        (
            # The tapped basic-land surface keeps its older recognizer.
            "search your library for a basic land card, put it onto the "
            "battlefield tapped, then shuffle",
            SearchLibraryForBasicLandTapped(),
        ),
    ],
)
def test_land_search_phrase_grammar(phrase, expected):
    assert _parse_effect(phrase) == expected


def test_forced_tapped_search_enters_tapped():
    state = _state()
    obj = _zone(state, PLAINS, "library")
    state.resolving_source = None
    SearchLibraryForLandCardToBattlefield(tapped=True).resolve(state, 0)
    assert obj in state.battlefield and obj.tapped


# --- Karakas: bounce target legendary creature ----------------------------


def test_karakas_bounces_only_legendary_creatures(cube):
    karakas = cube["Karakas"]
    assert karakas.is_legendary and karakas.produces == frozenset({"W"})
    (bounce,) = karakas.activated_abilities
    assert isinstance(bounce.effect, Bounce)
    assert bounce.effect.targets[0].filter == IsCreature() & IsLegendary()

    state = _state()
    k = _put(state, karakas)
    grunt = _put(state, make_creature("Grunt", "{1}", 1, 1), player_id=1)
    assert ActivateAbility(k.id, 0) not in legal_actions(state, 0)
    legend = _put(
        state,
        make_creature("Legend", "{1}", 2, 2, legendary=True),
        player_id=1,
    )
    assert ActivateAbility(k.id, 0) in legal_actions(state, 0)
    apply_action(state, 0, ActivateAbility(k.id, 0))
    resolve_top_of_stack(state)
    assert legend in state.players[1].hand
    assert grunt in state.battlefield


def test_bounce_noun_grammar():
    e = _parse_effect(
        "return target artifact, creature, enchantment, or planeswalker "
        "to its owner's hand"
    )
    assert isinstance(e, Bounce)
    assert _parse_effect("return target frog to its owner's hand") is None


def test_is_legendary_predicate_on_players():
    assert IsLegendary().test(Player(id=0), None) is False


# --- Library of Alexandria: Activate only if -------------------------------


def test_library_of_alexandria_gate(cube):
    lib = cube["Library of Alexandria"]
    draw = next(a for a in lib.activated_abilities if not a.is_mana_ability)
    assert draw.effect == DrawCards(amount=1)
    assert draw.activate_only_if == HandSizeExactly(7)
    idx = lib.activated_abilities.index(draw)

    state = _state()
    obj = _put(state, lib)
    _zone(state, PLAINS, "library")
    for _ in range(6):
        _zone(state, ISLAND, "hand")
    assert ActivateAbility(obj.id, idx) not in legal_actions(state, 0)
    _activate_ability(state, 0, obj.id, idx)  # defensive refusal
    assert not obj.tapped and not state.stack
    _zone(state, ISLAND, "hand")
    assert ActivateAbility(obj.id, idx) in legal_actions(state, 0)
    apply_action(state, 0, ActivateAbility(obj.id, idx))
    resolve_top_of_stack(state)
    assert len(state.players[0].hand) == 8


@pytest.mark.parametrize(
    "phrase,expected",
    [
        ("you have exactly seven cards in hand", HandSizeExactly(7)),
        ("you have exactly one card in hand", HandSizeExactly(1)),
        ("you have exactly 3 cards in hand", HandSizeExactly(3)),
        ("you have exactly many cards in hand", None),
        ("the moon is full", None),
    ],
)
def test_activate_only_if_condition_grammar(phrase, expected):
    assert _parse_activate_only_if_condition(phrase) == expected


def test_unknown_activate_only_if_rider_rejects_line():
    assert _parse_activated_ability_line(
        "{T}: Draw a card. Activate only if the moon is full."
    ) is None


def test_hand_ability_respects_activate_only_if(cube):
    from dataclasses import replace

    base = cube["Ketria Triome"]
    (cycling,) = base.hand_activated_abilities
    gated = replace(
        base,
        name="Gated Triome",
        hand_activated_abilities=(
            replace(cycling, activate_only_if=HandSizeExactly(7)),
        ),
    )
    state = _state()
    card = _zone(state, gated, "hand")
    for _ in range(3):
        _put(state, ISLAND)
    assert ActivateAbility(card.id, 0) not in legal_actions(state, 0)
    _activate_ability(state, 0, card.id, 0)
    assert card in state.players[0].hand and not state.stack


# --- Gaea's Cradle / Tolarian Academy: scaling mana -------------------------


@pytest.mark.parametrize(
    "name,color,pred",
    [("Gaea's Cradle", "G", IsCreature()), ("Tolarian Academy", "U", IsArtifact())],
)
def test_scaling_mana_lands_claimed(cube, name, color, pred):
    p = cube[name]
    assert p.is_legendary and p.produces == frozenset()
    (mana,) = p.activated_abilities
    assert mana.is_mana_ability
    assert mana.effect == AddManaOfColorPerCount(
        color=color, amount=CountControlledMatching(pred),
    )


def test_gaeas_cradle_adds_per_creature(cube):
    state = _state()
    cradle = _put(state, cube["Gaea's Cradle"])
    assert not can_pay_cost(state, 0, parse_mana_cost("{1}"))
    bear = make_creature("Bear", "{1}{G}", 2, 2)
    _put(state, bear)
    _put(state, bear)
    _put(state, bear, player_id=1)  # opponent's creature doesn't count
    apply_action(state, 0, ActivateAbility(cradle.id, 0))
    pool = [c.color for c in state.players[0].mana_pool]
    assert pool == ["G", "G"]
    assert cradle.tapped and not state.stack
    assert "add {G} for each" in cradle.printing.activated_abilities[0].effect.describe()


# --- City of Traitors -------------------------------------------------------


def test_city_of_traitors(cube):
    city = cube["City of Traitors"]
    assert city.produces == frozenset({"C"})
    (trig,) = city.triggered_abilities
    assert trig.effect == SacrificeSelf()

    state = _state()
    card = _zone(state, city, "hand")
    _play_land(state, 0, card.id)
    assert not state.stack  # playing City itself doesn't trigger it
    state.players[0].lands_played_this_turn = 0
    opp_land = _zone(state, PLAINS, "hand", player_id=1)
    _play_land(state, 1, opp_land.id)
    assert not state.stack  # an opponent's land drop doesn't either
    other = _zone(state, PLAINS, "hand")
    _play_land(state, 0, other.id)
    assert len(state.stack) == 1
    resolve_top_of_stack(state)
    assert card not in state.battlefield
    assert card in state.players[0].graveyard


def test_city_of_traitors_mana_ability_adds_two(cube):
    state = _state()
    city = _put(state, cube["City of Traitors"])
    apply_action(state, 0, ActivateAbility(city.id, 0))
    assert [c.color for c in state.players[0].mana_pool] == ["C", "C"]


def test_sacrifice_this_permanent_phrase():
    assert _parse_effect("sacrifice this land") == SacrificeSelf()
    assert _parse_effect("sacrifice this frog") is None


# --- Wasteland / Mishra's Workshop -----------------------------------------


def test_wasteland_destroys_only_nonbasic(cube):
    waste = cube["Wasteland"]
    sac = next(a for a in waste.activated_abilities if not a.is_mana_ability)
    assert sac.effect == DestroyTargetLand(nonbasic_only=True)
    assert _parse_effect("destroy target land") == DestroyTargetLand()

    state = _state()
    w = _put(state, waste)
    plains = _put(state, PLAINS, player_id=1)
    idx = waste.activated_abilities.index(sac)
    legal_ids = {t[1] for t in sac.effect.legal_targets(state, 0)}
    assert plains.id not in legal_ids
    tundra = _put(state, cube["Tundra"], player_id=1)
    apply_action(state, 0, ActivateAbility(w.id, idx))
    # The sacrificed Wasteland is never its own target.
    assert state.stack[-1].targets[0][1] == tundra.id
    resolve_top_of_stack(state)
    assert tundra not in state.battlefield
    assert plains in state.battlefield


def test_mishras_workshop_restricted_to_artifact_spells(cube):
    shop = cube["Mishra's Workshop"]
    assert shop.produces == frozenset() and shop.mana_only_from_produces
    (mana,) = shop.activated_abilities
    assert mana.effect.spend_restriction == "artifact_spell"
    assert mana.effect.produces == (("C", 1), ("C", 1), ("C", 1))

    state = _state()
    w = _put(state, shop)
    assert not can_pay_cost(state, 0, parse_mana_cost("{1}"))
    apply_action(state, 0, ActivateAbility(w.id, 0))
    assert not can_pay_cost(state, 0, parse_mana_cost("{3}"))
    assert can_pay_cost(
        state, 0, parse_mana_cost("{3}"), spell_kind="artifact_spell",
    )
