"""Engine-resolve tests for ``DestroyTargetNonlandPermanentWithLanderForController``.

Emergency Eject's two-sentence body ("Destroy target nonland permanent.
Its controller creates a Lander token.") has parser-shape coverage, and a
single indestructible-target test in ``test_rules_cards_misc.py`` exercises
the no-Lander branch. The happy path — destroy succeeds, target's FORMER
controller (NOT the activator) gets a Lander token — was uncovered.

These tests pin:

- the destroy + Lander pair on a vanilla creature;
- the FORMER-controller attribution (Lander goes to opponent when an
  opponent's creature is destroyed, not to the activator);
- the legal-target pool: every battlefield non-land, regardless of
  controller;
- defensive bails: no targets, wrong target kind, missing target id,
  land target.
"""

from __future__ import annotations

from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.effects.generic import (
    DestroyTargetNonlandPermanentWithLanderForController,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step


def _new_state() -> GameState:
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def test_resolve_destroys_creature_and_gives_lander_to_former_controller():
    """Activator (P0) targets P1's creature: P1 gets the Lander."""
    state = _new_state()
    enemy_bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)

    DestroyTargetNonlandPermanentWithLanderForController().resolve(
        state, controller_id=0,
        targets=(("permanent", enemy_bear.id),),
    )
    # Bear is gone.
    assert enemy_bear not in state.battlefield
    assert any(c.id == enemy_bear.id for c in state.players[1].graveyard)
    # Lander was created under P1 (the former controller).
    landers_p1 = [
        o for o in state.battlefield
        if o.printing.name == "Lander" and o.controller_id == 1
    ]
    assert len(landers_p1) == 1
    landers_p0 = [
        o for o in state.battlefield
        if o.printing.name == "Lander" and o.controller_id == 0
    ]
    assert landers_p0 == []


def test_resolve_destroys_own_creature_and_gives_self_lander():
    state = _new_state()
    own_bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    DestroyTargetNonlandPermanentWithLanderForController().resolve(
        state, 0, (("permanent", own_bear.id),),
    )
    assert own_bear not in state.battlefield
    landers = [o for o in state.battlefield if o.printing.name == "Lander"]
    assert len(landers) == 1
    assert landers[0].controller_id == 0


def test_resolve_no_targets_is_noop():
    state = _new_state()
    pre = list(state.battlefield)
    DestroyTargetNonlandPermanentWithLanderForController().resolve(
        state, 0, (),
    )
    assert list(state.battlefield) == pre


def test_resolve_wrong_target_kind_is_noop():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    DestroyTargetNonlandPermanentWithLanderForController().resolve(
        state, 0, (("creature", bear.id),),
    )
    # The class checks kind == "permanent"; a "creature" tuple bails.
    assert bear in state.battlefield


def test_resolve_missing_target_is_noop():
    state = _new_state()
    pre = list(state.battlefield)
    DestroyTargetNonlandPermanentWithLanderForController().resolve(
        state, 0, (("permanent", 999_999),),
    )
    assert list(state.battlefield) == pre


def test_legal_targets_excludes_lands_includes_both_players_permanents():
    state = _new_state()
    own_bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    enemy_bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    own_plains = _put(state, BASIC_LANDS["Plains"], owner_id=0)

    legal = (
        DestroyTargetNonlandPermanentWithLanderForController()
        .legal_targets(state, controller_id=0)
    )
    legal_ids = {tid for kind, tid in legal if kind == "permanent"}
    assert own_bear.id in legal_ids
    assert enemy_bear.id in legal_ids
    assert own_plains.id not in legal_ids


def test_describe_mentions_destroy_and_lander():
    text = DestroyTargetNonlandPermanentWithLanderForController().describe()
    assert "destroy" in text.lower()
    assert "Lander" in text


def test_requires_target_true():
    eff = DestroyTargetNonlandPermanentWithLanderForController()
    assert eff.requires_target() is True
