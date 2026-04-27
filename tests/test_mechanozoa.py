"""Tests for Mechanozoa's ETB tap+stun and the shared
TapTargetOpponentPermanentAndStunIt effect."""

from mtg_bot.actions import put_into_battlefield, resolve_top_of_stack
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import EOE_CREATURES, SYNTHETIC_CREATURES
from mtg_bot.effects import TapTargetOpponentPermanentAndStunIt
from mtg_bot.game import GameState, Player, Zone
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent or _PickFirstAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


# -----------------------
# TapTargetOpponentPermanentAndStunIt effect-level
# -----------------------


def test_effect_requires_target_and_describe():
    e = TapTargetOpponentPermanentAndStunIt()
    assert e.requires_target() is True
    text = e.describe()
    assert "tap" in text and "stun" in text and "opponent" in text


def test_legal_targets_only_opponent_artifacts_and_creatures():
    state = _new_state()
    own_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(own_bear)
    enemy_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(enemy_bear)
    targets = TapTargetOpponentPermanentAndStunIt().legal_targets(state, 0)
    ids = {tid for _, tid in targets}
    assert enemy_bear.id in ids
    assert own_bear.id not in ids


def test_resolve_taps_untapped_opponent_creature_and_stuns():
    state = _new_state()
    enemy = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(enemy)
    assert enemy.tapped is False
    TapTargetOpponentPermanentAndStunIt().resolve(
        state, 0, (("permanent", enemy.id),),
    )
    assert enemy.tapped is True
    assert enemy.stun_counters == 1


def test_resolve_already_tapped_still_adds_stun():
    state = _new_state()
    enemy = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    enemy.tapped = True
    state.battlefield.append(enemy)
    TapTargetOpponentPermanentAndStunIt().resolve(
        state, 0, (("permanent", enemy.id),),
    )
    assert enemy.tapped is True
    assert enemy.stun_counters == 1


def test_resolve_no_target_is_noop():
    state = _new_state()
    TapTargetOpponentPermanentAndStunIt().resolve(state, 0, ())


def test_resolve_wrong_kind_is_noop():
    state = _new_state()
    TapTargetOpponentPermanentAndStunIt().resolve(
        state, 0, (("creature", 1),),
    )


def test_resolve_missing_id_is_noop():
    state = _new_state()
    TapTargetOpponentPermanentAndStunIt().resolve(
        state, 0, (("permanent", 99999),),
    )


# -----------------------
# Mechanozoa ETB integration
# -----------------------


def test_mechanozoa_etb_taps_and_stuns_opponent_creature():
    state = _new_state(_PickFirstAgent())
    enemy = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(enemy)
    zoa = state.new_object(EOE_CREATURES["Mechanozoa"], 0, Zone.HAND)
    state.players[0].hand.append(zoa)
    put_into_battlefield(state, zoa, controller_id=0)
    while state.stack:
        resolve_top_of_stack(state)
    assert enemy.tapped is True
    assert enemy.stun_counters == 1


def test_mechanozoa_printing_has_warp_and_etb_trigger():
    m = EOE_CREATURES["Mechanozoa"]
    assert m.warp_cost_str == "{2}{U}"
    triggers = {_legacy_or_inferred_key(ab) for ab in m.triggered_abilities}
    assert "etb" in triggers
