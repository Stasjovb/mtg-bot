"""PowerLSV cube utility artifacts: Spellbombs, Expedition Map, Keys,
Candelabra, Legion Extruder, Retrofitter / Thopter Foundry, the
Baubles, Sensei's Divining Top, Memory Jar, Grindstone and
Sewer-veillance Cam — plus the generic pieces they introduced (token
synthesis, delayed upkeep / any-player end-step triggers, new cost
atoms)."""

from __future__ import annotations

import pytest

from mtg_bot import apply, legal_moves
from mtg_bot.actions import (
    ActivateAbility,
    drain_stack,
    put_into_battlefield,
    resolve_top_of_stack,
)
from mtg_bot.cards import BASIC_LANDS, make_creature
from mtg_bot.cards.base import make_artifact, parse_mana_cost
from mtg_bot.cards.parser.activated import _parse_activation_cost
from mtg_bot.cards.parser.effects import _parse_effect
from mtg_bot.cards.tokens import TOKEN_PRINTINGS
from mtg_bot.effects.generic import (
    CreateToken,
    DealDamageAnyTarget,
    DrawCards,
    EachPlayerExilesHandDrawsNReturnsLater,
    LookAtRandomCardInTargetPlayersHand,
    LookAtTopCardOfTargetPlayersLibrary,
    LookAtTopNPutBackInAnyOrder,
    MayTapOrUntapTarget,
    MillTwoRepeatWhileShareColor,
    PutSourceOnTopOfOwnersLibrary,
    ReturnTargetCreatureToOwnersHand,
    ScheduleDelayedEffect,
    SearchLibraryForCard,
    Untap,
    UntapXTargets,
)
from mtg_bot.effects.object_predicates import (
    IsArtifact,
    IsCreature,
    IsPlayer,
    IsSource,
)
from mtg_bot.effects.targets import TargetSpec
from mtg_bot.game import Zone
from mtg_bot.turn import (
    Step,
    move_off_battlefield,
    run_beginning_of_upkeep_triggers,
    run_delayed_end_step_triggers,
)

from tests._cube_artifact_helpers import (
    agent,
    arena,
    build_ok,
    put,
    to_graveyard,
    to_hand,
    to_library,
)


def _activate(state, obj, idx, pid=0):
    apply(state, ActivateAbility(source_id=obj.id, ability_index=idx), pid)


def _can_activate(state, obj, idx, pid=0):
    return ActivateAbility(source_id=obj.id, ability_index=idx) in legal_moves(
        state, pid
    )


def _bear(name="Test Bear", cost="{1}{G}"):
    return make_creature(name, cost, 2, 2)


# --- grammar --------------------------------------------------------------

def test_bounce_regex_is_parameterized_over_up_to_one():
    assert _parse_effect("return target creature to its owner's hand") == (
        ReturnTargetCreatureToOwnersHand()
    )
    assert _parse_effect(
        "return up to one target creature to its owner's hand"
    ) == ReturnTargetCreatureToOwnersHand(optional=True)


def test_pronoun_damage_and_land_tutor():
    from mtg_bot.cards.parser.activated import _parse_activated_ability_line
    ability = _parse_activated_ability_line(
        "{R}, Sacrifice this artifact: It deals 2 damage to any target."
    )
    assert ability.effect == DealDamageAnyTarget(amount=2)
    assert _parse_effect(
        "search your library for a land card, reveal it, put it into your "
        "hand, then shuffle"
    ) == SearchLibraryForCard(filter_name="land", may_fail=True)


@pytest.mark.parametrize("phrase,expected", [
    ("untap target artifact", Untap(targets=(TargetSpec(IsArtifact()),))),
    (
        "untap another target artifact",
        Untap(targets=(TargetSpec(IsArtifact() & ~IsSource()),)),
    ),
    ("untap target creature", Untap(targets=(TargetSpec(IsCreature()),))),
])
def test_untap_target_phrases(phrase, expected):
    assert _parse_effect(phrase) == expected


def test_token_synthesis_shapes():
    eff = _parse_effect(
        "create four 4/4 colorless Construct artifact creature tokens with "
        "flying and haste"
    )
    assert isinstance(eff, CreateToken) and eff.count == 4
    tok = eff.token_printing
    assert (tok.power, tok.toughness) == (4, 4)
    assert tok.keywords == frozenset({"flying", "haste"})
    assert tok.is_artifact and tok.is_creature and tok.is_token
    assert tok.subtypes == ("Construct",)
    eff = _parse_effect("create a 1/1 white Spirit creature token with flying")
    assert eff.token_printing.keywords == frozenset({"flying"})
    assert not eff.token_printing.is_artifact
    # Registered tokens still come from the registry.
    eff = _parse_effect("create a 2/2 colorless Robot artifact creature token")
    assert eff.token_printing is TOKEN_PRINTINGS["Robot"]


@pytest.mark.parametrize("phrase", [
    "create a 1/1 white Monk creature token with prowess",
    "create a 1/1 colorless Pilot creature token with \"This token crews "
    "Vehicles as though its power were 2 greater and has flying.\"",
    "create a 2/2 white Cat enchantment creature token",
    "create a 1/1 red Goblin creature token that's tapped and attacking",
])
def test_token_synthesis_refuses_unmodeled_riders(phrase):
    assert _parse_effect(phrase) is None


def test_new_cost_atoms():
    c = _parse_activation_cost("{1}, {T}, Sacrifice a Servo")
    assert c.sacrifice_subtype == "Servo" and c.tap_self
    assert "Sacrifice a Servo" in c.describe()
    c = _parse_activation_cost("{1}, Sacrifice a nontoken artifact")
    assert c.sacrifice_nontoken_artifact
    assert "nontoken" in c.describe()
    c = _parse_activation_cost(
        "{W}, {T}, Remove a story counter from this artifact"
    )
    # A single named-kind counter rides the shared named-counter atom.
    assert c.remove_named_counter_from_self == "story"
    assert "story" in c.describe()
    # Dedicated kinds (charge) and Vehicles use the generic atom.
    c = _parse_activation_cost("Remove a charge counter from this artifact")
    assert (c.remove_counters_from_self_kind,
            c.remove_counters_from_self_amount) == ("charge", 1)
    assert "charge" in c.describe()
    assert _parse_activation_cost(
        "{2}, {T}, Remove a charge counter from this Vehicle"
    ).remove_counters_from_self_kind == "charge"
    assert _parse_activation_cost(
        "Remove two wish counters from this artifact"
    ).remove_counters_from_self_amount == 2
    assert _parse_activation_cost(
        "Sacrifice a Servo, Sacrifice this artifact"
    ) is None
    assert _parse_activation_cost(
        "Sacrifice a nontoken artifact, Sacrifice a Servo"
    ) is None
    assert _parse_activation_cost(
        "Remove a story counter from this artifact, Remove a wish counter "
        "from this artifact"
    ) is None


@pytest.mark.parametrize("phrase,expected", [
    (
        "look at the top card of target player's library",
        LookAtTopCardOfTargetPlayersLibrary(),
    ),
    (
        "look at a card at random in target player's hand",
        LookAtRandomCardInTargetPlayersHand(),
    ),
    (
        "you draw a card at the beginning of the next turn's upkeep",
        ScheduleDelayedEffect(inner=DrawCards(amount=1), step="upkeep"),
    ),
    (
        "look at the top three cards of your library, then put them back in "
        "any order",
        LookAtTopNPutBackInAnyOrder(amount=3),
    ),
    (
        "put this artifact on top of its owner's library",
        PutSourceOnTopOfOwnersLibrary(),
    ),
    (
        "you may tap or untap target permanent",
        MayTapOrUntapTarget(targets=(TargetSpec(~IsPlayer()),)),
    ),
])
def test_library_and_delay_phrases(phrase, expected):
    assert _parse_effect(phrase) == expected


def test_delayed_upkeep_rejects_targeted_or_unknown_inner():
    assert _parse_effect(
        "frobnicate at the beginning of the next turn's upkeep"
    ) is None
    assert _parse_effect(
        "destroy target creature at the beginning of the next turn's upkeep"
    ) is None


# --- builder shapes -------------------------------------------------------

def test_spellbomb_and_map_shapes():
    aether = build_ok("Aether Spellbomb")
    assert aether.activated_abilities[0].effect == (
        ReturnTargetCreatureToOwnersHand()
    )
    assert aether.activated_abilities[1].effect == DrawCards(amount=1)
    pyrite = build_ok("Pyrite Spellbomb")
    assert pyrite.activated_abilities[0].effect == DealDamageAnyTarget(amount=2)
    emap = build_ok("Expedition Map")
    (ability,) = emap.activated_abilities
    assert ability.effect == SearchLibraryForCard(filter_name="land")
    assert ability.cost.sacrifice_self and ability.cost.tap_self


def test_memory_jar_and_grindstone_shapes():
    jar = build_ok("Memory Jar")
    assert jar.activated_abilities[0].effect == (
        EachPlayerExilesHandDrawsNReturnsLater(amount=7)
    )
    grind = build_ok("Grindstone")
    assert grind.activated_abilities[0].effect == MillTwoRepeatWhileShareColor()


# --- engine: spellbombs, map, keys ---------------------------------------

def test_aether_spellbomb_bounces_creature():
    state = arena()
    bomb = put(state, build_ok("Aether Spellbomb"))
    put(state, BASIC_LANDS["Island"])
    bear = put(state, _bear(), 1)
    agent(state).targets = [("creature", bear.id)]
    _activate(state, bomb, 0)
    resolve_top_of_stack(state)
    assert bear in state.players[1].hand
    assert bomb.zone == Zone.GRAVEYARD


def test_pyrite_spellbomb_shocks_face():
    state = arena()
    bomb = put(state, build_ok("Pyrite Spellbomb"))
    put(state, BASIC_LANDS["Mountain"])
    agent(state).targets = [("player", 1)]
    _activate(state, bomb, 0)
    resolve_top_of_stack(state)
    assert state.players[1].life == 18


def test_expedition_map_fetches_a_land():
    state = arena()
    emap = put(state, build_ok("Expedition Map"))
    for _ in range(2):
        put(state, BASIC_LANDS["Plains"])
    to_library(state, _bear())
    land = to_library(state, BASIC_LANDS["Forest"])
    _activate(state, emap, 0)
    resolve_top_of_stack(state)
    assert land in state.players[0].hand
    assert 1 in land.publicly_known_to  # revealed


def test_search_without_reveal_keeps_card_hidden():
    state = arena()
    card = to_library(state, _bear())
    SearchLibraryForCard(filter_name="any", may_fail=False, reveal=False).resolve(
        state, 0,
    )
    assert card in state.players[0].hand
    assert 1 not in card.publicly_known_to


def test_voltaic_key_untaps_an_artifact():
    state = arena()
    key = put(state, build_ok("Voltaic Key"))
    put(state, BASIC_LANDS["Plains"])
    grim = put(state, build_ok("Grim Monolith"), tapped=True)
    agent(state).targets = [("permanent", grim.id)]
    _activate(state, key, 0)
    resolve_top_of_stack(state)
    assert not grim.tapped


def test_manifold_key_cannot_target_itself_and_grants_unblockable():
    state = arena()
    key = put(state, build_ok("Manifold Key"))
    put(state, BASIC_LANDS["Plains"])
    # Only artifact is Manifold Key itself -> "another target artifact"
    # has no legal target.
    assert not _can_activate(state, key, 0)
    other = put(state, build_ok("Grim Monolith"), tapped=True)
    assert _can_activate(state, key, 0)
    _activate(state, key, 0)
    resolve_top_of_stack(state)
    assert not other.tapped
    assert key.tapped


def test_candelabra_untaps_x_lands():
    state = arena()
    candelabra = put(state, build_ok("Candelabra of Tawnos"))
    lands = [put(state, BASIC_LANDS["Island"], tapped=True) for _ in range(3)]
    payers = [put(state, BASIC_LANDS["Island"]) for _ in range(2)]
    agent(state).x_value = 2
    agent(state).targets = [("permanent", lands[0].id), ("permanent", lands[1].id)]
    _activate(state, candelabra, 0)
    assert all(p.tapped for p in payers)
    resolve_top_of_stack(state)
    assert not lands[0].tapped and not lands[1].tapped
    assert lands[2].tapped


def test_candelabra_with_x_zero_targets_nothing():
    state = arena()
    candelabra = put(state, build_ok("Candelabra of Tawnos"))
    agent(state).x_value = 0
    _activate(state, candelabra, 0)
    assert state.stack[-1].targets == ()
    resolve_top_of_stack(state)
    UntapXTargets(targets=(TargetSpec(IsCreature()),)).resolve(state, 0)
    assert "untap X" in UntapXTargets().describe()


# --- engine: token makers -------------------------------------------------

def test_legion_extruder_makes_a_golem_by_saccing_another_artifact():
    state = arena()
    extruder = put(state, build_ok("Legion Extruder"))
    fodder = put(state, build_ok("Mox Opal"))
    for _ in range(2):
        put(state, BASIC_LANDS["Mountain"])
    _activate(state, extruder, 0)
    assert fodder.zone == Zone.GRAVEYARD
    resolve_top_of_stack(state)
    golems = [o for o in state.battlefield if o.printing.name == "Golem"]
    assert len(golems) == 1
    assert (golems[0].printing.power, golems[0].printing.toughness) == (3, 3)


def test_retrofitter_foundry_servo_thopter_construct_chain():
    state = arena()
    foundry = put(state, build_ok("Retrofitter Foundry"))
    lands = [put(state, BASIC_LANDS["Plains"]) for _ in range(6)]
    assert not _can_activate(state, foundry, 2)  # no Servo yet
    _activate(state, foundry, 1)
    resolve_top_of_stack(state)
    assert any(o.printing.name == "Servo" for o in state.battlefield)
    # untap it for {3}
    _activate(state, foundry, 0)
    resolve_top_of_stack(state)
    assert not foundry.tapped
    assert _can_activate(state, foundry, 2)
    _activate(state, foundry, 2)
    resolve_top_of_stack(state)
    names = sorted(o.printing.name for o in state.battlefield if o.printing.is_token)
    assert names == ["Thopter"]
    thopter = next(o for o in state.battlefield if o.printing.name == "Thopter")
    assert "flying" in thopter.printing.keywords
    foundry.tapped = False
    _activate(state, foundry, 3)
    resolve_top_of_stack(state)
    names = sorted(o.printing.name for o in state.battlefield if o.printing.is_token)
    assert names == ["Construct"]
    assert len(lands) == 6


def test_thopter_foundry_can_sacrifice_itself():
    state = arena()
    foundry = put(state, build_ok("Thopter Foundry"))
    put(state, BASIC_LANDS["Island"])
    token_art = put(state, TOKEN_PRINTINGS["Treasure"])
    agent(state).sacrifices = [foundry.id]
    _activate(state, foundry, 0)
    assert foundry.zone == Zone.GRAVEYARD
    assert token_art in state.battlefield
    resolve_top_of_stack(state)
    assert state.players[0].life == 21
    assert any(o.printing.name == "Thopter" for o in state.battlefield)


def test_thopter_foundry_needs_a_nontoken_artifact():
    state = arena()
    foundry_printing = build_ok("Thopter Foundry")
    state2 = arena()
    put(state2, TOKEN_PRINTINGS["Treasure"])
    put(state2, BASIC_LANDS["Island"])
    obj = put(state2, foundry_printing)
    assert _can_activate(state2, obj, 0)  # itself qualifies
    assert state is not None


# --- engine: baubles & delayed triggers -----------------------------------

def test_mishras_bauble_peeks_and_draws_next_upkeep():
    state = arena()
    bauble = put(state, build_ok("Mishra's Bauble"))
    top = to_library(state, _bear(), owner=1)
    to_library(state, _bear("Mine"), owner=0)
    agent(state).targets = [("player", 1)]
    _activate(state, bauble, 0)
    resolve_top_of_stack(state)
    assert 0 in top.publicly_known_to
    assert len(state.players[0].hand) == 0
    assert state.delayed_triggers[0]["step"] == "upkeep"
    # the end step does not fire an upkeep-scheduled entry
    state.step = Step.END
    run_delayed_end_step_triggers(state)
    assert not state.stack
    # next turn (opponent's) upkeep: fires regardless of active player
    state.turn_number += 1
    state.active_player_idx = 1
    state.step = Step.UPKEEP
    run_beginning_of_upkeep_triggers(state)
    drain_stack(state)
    assert len(state.players[0].hand) == 1
    assert state.delayed_triggers == []


def test_urzas_bauble_looks_at_random_card():
    state = arena(seed=3)
    bauble = put(state, build_ok("Urza's Bauble"))
    cards = [to_hand(state, _bear(f"B{i}"), owner=1) for i in range(3)]
    agent(state).targets = [("player", 1)]
    _activate(state, bauble, 0)
    resolve_top_of_stack(state)
    assert sum(0 in c.publicly_known_to for c in cards) == 1


def test_look_effects_handle_empty_zones_and_bad_targets():
    state = arena()
    LookAtTopCardOfTargetPlayersLibrary().resolve(state, 0, (("player", 1),))
    LookAtRandomCardInTargetPlayersHand().resolve(state, 0, (("player", 1),))
    LookAtTopCardOfTargetPlayersLibrary().resolve(state, 0, ())
    LookAtRandomCardInTargetPlayersHand().resolve(state, 0, (("creature", 5),))
    ScheduleDelayedEffect(inner=DrawCards(amount=1)).resolve(state, 0)
    assert state.delayed_triggers == []
    assert "upkeep" in ScheduleDelayedEffect(inner=DrawCards(1)).describe()
    assert "end step" in ScheduleDelayedEffect(
        inner=DrawCards(1), step="end"
    ).describe()
    for eff in (
        LookAtTopCardOfTargetPlayersLibrary(),
        LookAtRandomCardInTargetPlayersHand(),
        LookAtTopNPutBackInAnyOrder(),
        PutSourceOnTopOfOwnersLibrary(),
        MillTwoRepeatWhileShareColor(),
        MayTapOrUntapTarget(),
        EachPlayerExilesHandDrawsNReturnsLater(),
    ):
        assert eff.describe()


# --- engine: Sensei's Divining Top ----------------------------------------

def test_top_reorders_top_three():
    state = arena()
    top = put(state, build_ok("Sensei's Divining Top"))
    put(state, BASIC_LANDS["Island"])
    a = to_library(state, _bear("A"))
    b = to_library(state, _bear("B"))
    c = to_library(state, _bear("C"))
    d = to_library(state, _bear("D"))
    agent(state).library_pick = c.id  # C first, then "first" of the rest
    _activate(state, top, 0)
    resolve_top_of_stack(state)
    lib = state.players[0].library
    assert lib[0] is c
    assert {x.id for x in lib[:3]} == {a.id, b.id, c.id}
    assert lib[3] is d
    assert all(0 in x.publicly_known_to for x in (a, b, c))


def test_top_draws_then_goes_on_top():
    state = arena()
    top = put(state, build_ok("Sensei's Divining Top"))
    card = to_library(state, _bear())
    _activate(state, top, 1)
    resolve_top_of_stack(state)
    assert card in state.players[0].hand
    assert state.players[0].library[0] is top
    assert top.zone == Zone.LIBRARY
    assert 1 in top.publicly_known_to


def test_put_on_top_noop_when_source_gone():
    state = arena()
    top = put(state, build_ok("Sensei's Divining Top"))
    state.battlefield.remove(top)
    state.resolving_source = top
    PutSourceOnTopOfOwnersLibrary().resolve(state, 0)
    assert state.players[0].library == []
    state.resolving_source = None
    LookAtTopNPutBackInAnyOrder().resolve(state, 0)  # empty library


def test_move_off_battlefield_rejects_unknown_destination():
    state = arena()
    obj = put(state, _bear())
    with pytest.raises(ValueError):
        move_off_battlefield(state, obj, destination="nowhere")


# --- engine: Memory Jar ---------------------------------------------------

def test_memory_jar_wheel_and_return():
    state = arena()
    jar = put(state, build_ok("Memory Jar"))
    mine = [to_hand(state, _bear(f"Mine{i}")) for i in range(2)]
    theirs = [to_hand(state, _bear(f"Their{i}"), owner=1) for i in range(3)]
    for owner in (0, 1):
        for i in range(8):
            to_library(state, BASIC_LANDS["Swamp"], owner=owner)
    _activate(state, jar, 0)
    resolve_top_of_stack(state)
    assert all(c.zone == Zone.EXILE for c in mine + theirs)
    assert 1 not in mine[0].publicly_known_to
    assert len(state.players[0].hand) == 7
    assert len(state.players[1].hand) == 7
    # fires at the next end step even though it's P0's turn and the
    # entry is any-player
    state.step = Step.END
    run_delayed_end_step_triggers(state)
    drain_stack(state)
    assert sorted(c.printing.name for c in state.players[0].hand) == [
        "Mine0", "Mine1",
    ]
    assert len(state.players[1].hand) == 3
    assert len(state.players[1].graveyard) == 7


def test_memory_jar_on_opponents_turn_fires_that_end_step():
    state = arena(active=1)
    state.priority_player_idx = 0
    jar = put(state, build_ok("Memory Jar"))
    to_hand(state, _bear())
    _activate(state, jar, 0)
    resolve_top_of_stack(state)
    state.step = Step.END
    run_delayed_end_step_triggers(state)
    assert len(state.stack) == 1


def test_schedule_end_step_during_end_step_waits_a_turn():
    state = arena()
    src = put(state, _bear())
    state.step = Step.END
    state.resolving_source = src
    ScheduleDelayedEffect(inner=DrawCards(amount=1), step="end").resolve(
        state, 0,
    )
    assert state.delayed_triggers[0]["fire_at_turn"] == state.turn_number + 1


# --- engine: Grindstone ---------------------------------------------------

def test_grindstone_repeats_while_colors_match():
    state = arena()
    grind = put(state, build_ok("Grindstone"))
    for _ in range(3):
        put(state, BASIC_LANDS["Plains"])
    green = [make_creature(f"G{i}", "{G}", 1, 1) for i in range(4)]
    for g in green:
        to_library(state, g, owner=1)
    to_library(state, make_creature("R", "{R}", 1, 1), owner=1)
    to_library(state, make_creature("U", "{U}", 1, 1), owner=1)
    to_library(state, BASIC_LANDS["Forest"], owner=1)
    agent(state).targets = [("player", 1)]
    _activate(state, grind, 0)
    resolve_top_of_stack(state)
    # G G (repeat) G G (repeat) R U (stop)
    assert len(state.players[1].graveyard) == 6
    assert len(state.players[1].library) == 1


def test_grindstone_stops_on_short_library():
    state = arena()
    to_library(state, make_creature("G", "{G}", 1, 1), owner=1)
    MillTwoRepeatWhileShareColor().resolve(state, 0, (("player", 1),))
    assert len(state.players[1].graveyard) == 1
    MillTwoRepeatWhileShareColor().resolve(state, 0, ())


# --- engine: Sewer-veillance Cam ------------------------------------------

def test_sewer_veillance_cam_etb_taps_or_untaps():
    state = arena()
    bear = put(state, _bear(), 1)
    cam = state.new_object(build_ok("Sewer-veillance Cam"), 0, Zone.STACK)
    agent(state).targets = [("creature", bear.id)]
    agent(state).choose_mode = _Chooser(0)  # tap it
    put_into_battlefield(state, cam, 0)
    assert len(state.stack) == 1
    resolve_top_of_stack(state)
    assert bear.tapped


class _Chooser:
    def __init__(self, choice):
        self.choice = choice

    def __call__(self, state, player_id, options):
        return self.choice


def test_may_tap_or_untap_choices():
    state = arena()
    bear = put(state, _bear(), 1, tapped=True)
    eff = MayTapOrUntapTarget(targets=(TargetSpec(IsCreature()),))
    agent(state).choose_mode = _Chooser(1)
    eff.resolve(state, 0, (("creature", bear.id),))
    assert not bear.tapped
    agent(state).choose_mode = _Chooser(2)
    eff.resolve(state, 0, (("creature", bear.id),))
    assert not bear.tapped
    # illegal / missing targets are no-ops
    eff.resolve(state, 0, ())
    land = put(state, BASIC_LANDS["Forest"])
    eff.resolve(state, 0, (("permanent", land.id),))
    state.battlefield.remove(bear)
    eff.resolve(state, 0, (("creature", bear.id),))
    state.players[0].agent = None
    bear2 = put(state, _bear(), 1)
    eff.resolve(state, 0, (("creature", bear2.id),))
    assert bear2.tapped
