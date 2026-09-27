"""PowerLSV cube: Wishclaw Talisman, Portal to Phyrexia, Time Vault —
plus the compound-effect sentence-split fallback, the named
enters-with-counters recognizer and the turn-skip replacement."""

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
from mtg_bot.cards.parser.effects import _parse_effect
from mtg_bot.cards.parser.printing_keywords import (
    _parse_enters_with_named_counters_line,
    _parse_skip_turn_to_untap_line,
)
from mtg_bot.effects.combinators import Sequence
from mtg_bot.effects.generic import (
    DrawCards,
    EachOpponentSacrificesN,
    OpponentGainsControlOfSource,
    ReanimateTargetCreatureCardFromAGraveyard,
    TakeExtraTurnAfterThisOne,
)
from mtg_bot.game import Zone, counter_count, effective_subtypes
from mtg_bot.simulate import _advance_to_next_active_player
from mtg_bot.turn import Step, run_beginning_of_upkeep_triggers

from tests._cube_artifact_helpers import (
    agent,
    arena,
    build_ok,
    put,
    to_graveyard,
    to_library,
)


def _activate(state, obj, idx, pid=0):
    apply(state, ActivateAbility(source_id=obj.id, ability_index=idx), pid)


def _can_activate(state, obj, idx, pid=0):
    return ActivateAbility(source_id=obj.id, ability_index=idx) in legal_moves(
        state, pid
    )


def _enter(state, printing, controller=0):
    obj = state.new_object(printing, owner_id=controller, zone=Zone.STACK)
    put_into_battlefield(state, obj, controller)
    return obj


def _bear(name="Bear"):
    return make_creature(name, "{1}{G}", 2, 2)


# --- grammar --------------------------------------------------------------

def test_compound_sentence_fallback_when_then_split_fails():
    from mtg_bot.cards.parser.activated import _parse_activated_ability_line
    eff = _parse_activated_ability_line(
        "{1}: Search your library for a card, put it into your hand, then "
        "shuffle. An opponent gains control of this artifact."
    ).effect
    # The tutor half is the base card-flow grammar's unrevealed search.
    assert isinstance(eff, Sequence)
    assert type(eff.effects[0]).__name__ == "SearchLibrary"
    assert eff.effects[0].reveal is False
    assert eff.effects[1] == OpponentGainsControlOfSource()
    # still rejects when no split works
    assert _parse_activated_ability_line(
        "{1}: Frobnicate, then shuffle. Wibble."
    ) is None


@pytest.mark.parametrize("line,expected", [
    ("This artifact enters with three wish counters on it.", ("wish", 3)),
    ("This Vehicle enters with 2 charge counters on it.", ("charge", 2)),
    ("This artifact enters with a story counter on it.", ("story", 1)),
    ("This creature enters with three +1/+1 counters on it.", None),
])
def test_enters_with_named_counters_line(line, expected):
    assert _parse_enters_with_named_counters_line(line) == expected


def test_portal_and_wishclaw_shapes():
    portal = build_ok("Portal to Phyrexia")
    etb, upkeep = portal.triggered_abilities
    assert etb.effect == EachOpponentSacrificesN(amount=3, card_type="Creature")
    assert upkeep.effect == ReanimateTargetCreatureCardFromAGraveyard(
        add_subtype="Phyrexian"
    )
    assert _parse_effect(
        "put target creature card from a graveyard onto the battlefield "
        "under your control"
    ) == ReanimateTargetCreatureCardFromAGraveyard()
    assert _parse_effect(
        "each opponent sacrifices two lands of their choice"
    ) == EachOpponentSacrificesN(amount=2, card_type="Land")
    wish = build_ok("Wishclaw Talisman")
    assert wish.enters_with_named_counters == (("wish", 3),)
    (ability,) = wish.activated_abilities
    assert ability.activate_only_during_your_turn
    assert ability.cost.remove_named_counter_from_self == "wish"


def test_time_vault_shape():
    vault = build_ok("Time Vault")
    assert vault.enters_tapped
    assert vault.doesnt_untap_during_untap_step
    assert vault.may_skip_turn_to_untap
    (ability,) = vault.activated_abilities
    assert ability.effect == TakeExtraTurnAfterThisOne()
    assert not _parse_skip_turn_to_untap_line("Skip your turn.")


# --- Wishclaw Talisman ----------------------------------------------------

def test_wishclaw_tutors_and_changes_control():
    state = arena()
    wish = _enter(state, build_ok("Wishclaw Talisman"))
    assert counter_count(wish, "wish") == 3
    put(state, BASIC_LANDS["Swamp"])
    target = to_library(state, _bear("Wanted"))
    to_library(state, _bear("Other"))
    agent(state).library_pick = target.id
    _activate(state, wish, 0)
    assert counter_count(wish, "wish") == 2
    resolve_top_of_stack(state)
    assert target in state.players[0].hand
    assert 1 not in target.publicly_known_to  # no reveal
    assert wish.controller_id == 1
    # Now P1 controls it, but it's P0's turn: P1 can't activate it.
    wish.tapped = False
    state.priority_player_idx = 1
    put(state, BASIC_LANDS["Swamp"], 1)
    assert not _can_activate(state, wish, 0, pid=1)
    state.active_player_idx = 1
    assert _can_activate(state, wish, 0, pid=1)


def test_wishclaw_needs_a_wish_counter():
    state = arena()
    wish = put(state, build_ok("Wishclaw Talisman"))  # no counters placed
    put(state, BASIC_LANDS["Swamp"])
    assert not _can_activate(state, wish, 0)


def test_opponent_gains_control_edge_cases():
    state = arena()
    OpponentGainsControlOfSource().resolve(state, 0)  # no source
    src = put(state, build_ok("Wishclaw Talisman"))
    state.resolving_source = src
    state.players[1].has_lost = True
    OpponentGainsControlOfSource().resolve(state, 0)
    assert src.controller_id == 0
    assert OpponentGainsControlOfSource().describe()


def test_opponent_gains_control_multiplayer_choice():
    from mtg_bot.game import Player
    from tests._cube_artifact_helpers import ScriptedAgent
    state = arena()
    state.players.append(Player(id=2, agent=ScriptedAgent()))
    src = put(state, build_ok("Wishclaw Talisman"))
    state.resolving_source = src
    agent(state).choose_mode = lambda s, p, opts: 1
    OpponentGainsControlOfSource().resolve(state, 0)
    assert src.controller_id == 2


# --- Portal to Phyrexia ---------------------------------------------------

def test_portal_etb_each_opponent_sacrifices_three():
    state = arena()
    theirs = [put(state, _bear(f"B{i}"), 1) for i in range(4)]
    mine = put(state, _bear("Mine"), 0)
    _enter(state, build_ok("Portal to Phyrexia"))
    drain_stack(state)
    assert sum(o in state.battlefield for o in theirs) == 1
    assert mine in state.battlefield


def test_portal_etb_with_fewer_creatures_sacrifices_all():
    state = arena()
    theirs = [put(state, _bear(f"B{i}"), 1) for i in range(2)]
    _enter(state, build_ok("Portal to Phyrexia"))
    drain_stack(state)
    assert not any(o in state.battlefield for o in theirs)
    assert "creatures" in EachOpponentSacrificesN(3).describe()


def test_portal_upkeep_reanimates_as_phyrexian():
    state = arena()
    put(state, build_ok("Portal to Phyrexia"))
    dead = to_graveyard(state, _bear("Dead"), owner=1)
    agent(state).targets = [("graveyard_creature", dead.id)]
    state.step = Step.UPKEEP
    run_beginning_of_upkeep_triggers(state)
    drain_stack(state)
    assert dead in state.battlefield
    assert dead.controller_id == 0
    assert "Phyrexian" in effective_subtypes(state, dead)


def test_reanimate_edge_cases():
    state = arena()
    eff = ReanimateTargetCreatureCardFromAGraveyard()
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("creature", 1),))
    land = to_graveyard(state, BASIC_LANDS["Forest"])
    eff.resolve(state, 0, (("graveyard_creature", land.id),))
    assert land.zone == Zone.GRAVEYARD
    dead = to_graveyard(state, _bear())
    eff.resolve(state, 0, (("graveyard_creature", dead.id),))
    assert dead in state.battlefield
    assert "Phyrexian" in ReanimateTargetCreatureCardFromAGraveyard(
        "Phyrexian"
    ).describe()


# --- Time Vault -----------------------------------------------------------

def test_time_vault_skip_turn_untaps_it():
    state = arena()
    vault = put(state, build_ok("Time Vault"), tapped=True)
    state.active_player_idx = 1  # P1's turn is ending
    agent(state, 0).yes = True
    _advance_to_next_active_player(state)
    # P0 skipped their turn: P1 goes again and the vault is untapped.
    assert state.active_player_idx == 1
    assert not vault.tapped


def test_time_vault_decline_keeps_turn():
    state = arena()
    vault = put(state, build_ok("Time Vault"), tapped=True)
    state.active_player_idx = 1
    agent(state, 0).yes = False
    _advance_to_next_active_player(state)
    assert state.active_player_idx == 0
    assert vault.tapped


def test_time_vault_extra_turn_combo():
    state = arena()
    vault = put(state, build_ok("Time Vault"))
    _activate(state, vault, 0)
    resolve_top_of_stack(state)
    assert state.extra_turn_queue == [0]
    _advance_to_next_active_player(state)  # vault is tapped -> offered skip
    # Scripted agent says yes: the extra turn is skipped and the vault
    # untaps; the natural rotation continues to P1.
    assert not vault.tapped
    assert state.active_player_idx == 1


def test_skip_turn_ignores_untapped_or_agentless():
    state = arena()
    put(state, build_ok("Time Vault"))
    state.active_player_idx = 1
    _advance_to_next_active_player(state)
    assert state.active_player_idx == 0
    state2 = arena()
    put(state2, build_ok("Time Vault"), tapped=True)
    state2.players[0].agent = None
    state2.active_player_idx = 1
    _advance_to_next_active_player(state2)
    assert state2.active_player_idx == 0
