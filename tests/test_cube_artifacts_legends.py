"""PowerLSV cube: The One Ring, Coveted Jewel, Palantír of Orthanc and
The Mind Stone — plus player protection from everything, the
unblocked-attackers event, named-counter phrases, harness / ∞."""

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
from mtg_bot.cards.base import make_artifact
from mtg_bot.cards.parser.effects import _parse_effect
from mtg_bot.combat import (
    declare_attackers,
    declare_blockers,
    resolve_combat_damage,
)
from mtg_bot.effects.base import _apply_damage
from mtg_bot.effects.combinators import ConditionalIfCastFromHand
from mtg_bot.effects.generic import (
    DealDamageAnyTarget,
    DealDamageEachOpponent,
    DealDamageToControllerAndAddMana,
    DrawCardsPerCounterOnSource,
    FlickerUpToOneOtherTargetNonlandPermanentYouControl,
    GainProtectionFromEverythingUntilYourNextTurn,
    HarnessSelf,
    LoseLifePerCounterOnSource,
    PutChargeCountersOnSelf,
    PutNamedCountersOnSelf,
    TargetOpponentMayLetYouDrawElseMill,
    ThatPlayerDrawsAndGainsControlOfSource,
)
from mtg_bot.effects.object_predicates import IsHarnessed
from mtg_bot.effects.predicates import Event, Source
from mtg_bot.game import Zone, counter_count, drop_protected_players
from mtg_bot.turn import (
    Step,
    run_beginning_of_end_step_triggers,
    run_beginning_of_upkeep_triggers,
    run_untap_step,
)

from tests._cube_artifact_helpers import (
    agent,
    arena,
    build_ok,
    put,
    to_hand,
    to_library,
)


def _activate(state, obj, idx, pid=0):
    apply(state, ActivateAbility(source_id=obj.id, ability_index=idx), pid)


def _enter(state, printing, controller=0):
    obj = state.new_object(printing, owner_id=controller, zone=Zone.STACK)
    put_into_battlefield(state, obj, controller)
    return obj


# --- grammar --------------------------------------------------------------

@pytest.mark.parametrize("phrase,expected", [
    ("put a burden counter on this creature", PutNamedCountersOnSelf("burden", 1)),
    ("put two story counters on this artifact", PutNamedCountersOnSelf("story", 2)),
    ("put a charge counter on this artifact", PutChargeCountersOnSelf(amount=1)),
    (
        "draw a card for each burden counter on this creature",
        DrawCardsPerCounterOnSource("burden"),
    ),
    (
        "you lose 1 life for each burden counter on this creature",
        LoseLifePerCounterOnSource("burden", 1),
    ),
    (
        "you gain protection from everything until your next turn",
        GainProtectionFromEverythingUntilYourNextTurn(),
    ),
    ("harness this creature", HarnessSelf()),
])
def test_phrases(phrase, expected):
    assert _parse_effect(phrase) == expected


def test_one_ring_shape():
    ring = build_ok("The One Ring")
    etb, upkeep = ring.triggered_abilities
    assert etb.effect == ConditionalIfCastFromHand(
        inner_effect=GainProtectionFromEverythingUntilYourNextTurn()
    )
    assert upkeep.event == Event.BEGINNING_OF_UPKEEP
    assert "indestructible" in ring.keywords


def test_mind_stone_shape():
    stone = build_ok("The Mind Stone")
    assert stone.subtypes == ("Infinity", "Stone")
    (inf,) = stone.triggered_abilities
    assert inf.predicate.right == Source(IsHarnessed())


def test_infinity_line_must_be_a_trigger():
    from mtg_bot.cards.parser.artifact_builder import _build_artifact_printing
    assert _build_artifact_printing({
        "name": "Test Stone", "mana_cost": "{1}", "type_line": "Artifact",
        "oracle_text": "∞ — {T}: Draw a card.",
    }) is None


# --- The One Ring ---------------------------------------------------------

def test_one_ring_protection_prevents_damage_and_targeting():
    state = arena()
    _enter(state, build_ok("The One Ring"))
    drain_stack(state)
    me = state.players[0]
    assert me.protected_from_everything
    _apply_damage(state, ("player", 0), 5)
    assert me.life == 20
    DealDamageEachOpponent(amount=2).resolve(state, 1)
    assert me.life == 20
    DealDamageToControllerAndAddMana(damage=2).resolve(state, 0)
    assert me.life == 20
    assert drop_protected_players(
        state, [("player", 0), ("player", 1), ("creature", 7)]
    ) == [("player", 1), ("creature", 7)]
    # Opponent can't target the protected player with a burn ability.
    attacker = put(state, make_creature("Guy", "{R}", 3, 3), 1)
    state.active_player_idx = 1
    declare_attackers(state, [attacker.id])
    declare_blockers(state, {})
    resolve_combat_damage(state, defending_player_id=0)
    assert me.life == 20
    # Protection ends at the start of P0's next turn.
    state.active_player_idx = 0
    run_untap_step(state)
    assert not me.protected_from_everything


def test_protected_player_cannot_be_targeted_by_spells():
    from mtg_bot.actions import CastSpell
    from mtg_bot.cards.base import make_instant
    state = arena()
    state.players[1].protected_from_everything = True
    bolt = to_hand(state, make_instant("Test Bolt", "{0}", DealDamageAnyTarget(3)))
    agent(state).targets = [("player", 1)]
    apply(state, CastSpell(card_id=bolt.id), 0)
    assert ("player", 1) not in state.stack[-1].targets


def test_one_ring_burden_draws_and_upkeep_loss():
    state = arena()
    ring = put(state, build_ok("The One Ring"))
    for _ in range(5):
        to_library(state, BASIC_LANDS["Island"])
    _activate(state, ring, 0)
    resolve_top_of_stack(state)
    assert counter_count(ring, "burden") == 1
    assert len(state.players[0].hand) == 1
    ring.tapped = False
    _activate(state, ring, 0)
    resolve_top_of_stack(state)
    assert counter_count(ring, "burden") == 2
    assert len(state.players[0].hand) == 3
    state.step = Step.UPKEEP
    run_beginning_of_upkeep_triggers(state)
    drain_stack(state)
    assert state.players[0].life == 18


def test_counter_effect_edge_cases():
    state = arena()
    PutNamedCountersOnSelf("burden").resolve(state, 0)
    DrawCardsPerCounterOnSource("burden").resolve(state, 0)
    LoseLifePerCounterOnSource("burden").resolve(state, 0)
    assert state.players[0].life == 20
    for eff in (
        PutNamedCountersOnSelf("burden"),
        DrawCardsPerCounterOnSource("burden"),
        LoseLifePerCounterOnSource("burden"),
        GainProtectionFromEverythingUntilYourNextTurn(),
        HarnessSelf(),
        FlickerUpToOneOtherTargetNonlandPermanentYouControl(),
        TargetOpponentMayLetYouDrawElseMill(),
        ThatPlayerDrawsAndGainsControlOfSource(),
    ):
        assert eff.describe()


# --- Coveted Jewel --------------------------------------------------------

def test_coveted_jewel_etb_mana_and_theft():
    state = arena()
    for _ in range(6):
        to_library(state, BASIC_LANDS["Island"])
        to_library(state, BASIC_LANDS["Island"], owner=1)
    jewel = _enter(state, build_ok("Coveted Jewel"))
    drain_stack(state)
    assert len(state.players[0].hand) == 3
    agent(state).colors = ["G"]
    _activate(state, jewel, 0)
    assert sorted(c.color for c in state.players[0].mana_pool) == ["G"] * 3
    # Opponent attacks and isn't blocked: they draw 3 and take the Jewel.
    state.active_player_idx = 1
    attacker = put(state, make_creature("Thief", "{B}", 1, 1), 1)
    declare_attackers(state, [attacker.id])
    declare_blockers(state, {})
    drain_stack(state)
    assert jewel.controller_id == 1
    assert not jewel.tapped
    assert len(state.players[1].hand) == 3


def test_coveted_jewel_blocked_attack_does_not_trigger():
    state = arena()
    jewel = put(state, build_ok("Coveted Jewel"))
    state.active_player_idx = 1
    attacker = put(state, make_creature("Thief", "{B}", 1, 1), 1)
    blocker = put(state, make_creature("Wall", "{W}", 0, 4), 0)
    declare_attackers(state, [attacker.id])
    declare_blockers(state, {blocker.id: attacker.id})
    drain_stack(state)
    assert jewel.controller_id == 0


def test_own_unblocked_attack_does_not_trigger_own_jewel():
    state = arena()
    jewel = put(state, build_ok("Coveted Jewel"))
    guy = put(state, make_creature("Guy", "{R}", 2, 2), 0)
    declare_attackers(state, [guy.id])
    declare_blockers(state, {})
    drain_stack(state)
    assert jewel.controller_id == 0


def test_that_player_effect_edge_cases():
    state = arena()
    eff = ThatPlayerDrawsAndGainsControlOfSource()
    eff.resolve(state, 0, ())
    to_library(state, BASIC_LANDS["Island"], owner=1)
    eff.resolve(state, 0, (("player", 1),))  # no source: just draws
    assert len(state.players[1].hand) == 1


# --- Palantír of Orthanc --------------------------------------------------

def _palantir_setup(opp_says_yes):
    state = arena()
    pal = put(state, build_ok("Palantír of Orthanc"))
    for mv in ("{2}", "{3}", "{1}"):
        to_library(state, make_artifact(f"Rock{mv}", mv))
    agent(state, 1).yes = opp_says_yes
    agent(state).targets = [("player", 1)]
    state.step = Step.END
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)
    return state, pal


def test_palantir_opponent_lets_you_draw():
    state, pal = _palantir_setup(True)
    assert counter_count(pal, "influence") == 1
    assert len(state.players[0].hand) == 1
    assert state.players[1].life == 20


def test_palantir_opponent_refuses_mill_and_life_loss():
    state, pal = _palantir_setup(False)
    assert len(state.players[0].graveyard) == 1  # X = 1 influence counter
    assert state.players[1].life == 18  # first card has MV 2


def test_palantir_effect_edge_cases():
    state = arena()
    eff = TargetOpponentMayLetYouDrawElseMill()
    eff.resolve(state, 0, (("player", 0),))  # can't target yourself
    eff.resolve(state, 0, ())
    state.players[1].agent = None
    to_library(state, BASIC_LANDS["Island"])
    eff.resolve(state, 0, (("player", 1),))  # agentless opponent: draw
    assert len(state.players[0].hand) == 1


# --- The Mind Stone -------------------------------------------------------

def test_mind_stone_harness_enables_blink():
    state = arena()
    stone = put(state, build_ok("The Mind Stone"))
    guy = put(state, make_creature("Guy", "{W}", 2, 2))
    guy.plus_one_counters = 2
    state.step = Step.END
    run_beginning_of_end_step_triggers(state)
    assert not state.stack  # not harnessed yet
    for _ in range(6):
        put(state, BASIC_LANDS["Plains"])
    _activate(state, stone, 1)
    resolve_top_of_stack(state)
    assert stone.harnessed
    agent(state).targets = [("creature", guy.id)]
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)
    assert guy in state.battlefield
    assert guy.summoning_sick  # a new object


def test_flicker_edge_cases():
    state = arena()
    eff = FlickerUpToOneOtherTargetNonlandPermanentYouControl()
    eff.resolve(state, 0, ())
    tok = put(state, make_creature("Tok", "{0}", 1, 1))
    from dataclasses import replace
    token_printing = replace(tok.printing, supertypes=("Token",))
    token = put(state, token_printing)
    eff.resolve(state, 0, (("creature", token.id),))
    assert token not in state.battlefield
    theirs = put(state, make_creature("Theirs", "{0}", 1, 1), 1)
    eff.resolve(state, 0, (("creature", theirs.id),))  # not yours: illegal
    assert theirs in state.battlefield
    HarnessSelf().resolve(state, 0)  # no source: no-op
