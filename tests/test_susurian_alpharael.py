"""Tests for Susurian Voidborn + Alpharael Dreaming Acolyte."""

from mtg_bot.actions import drain_stack, put_into_battlefield, resolve_top_of_stack
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.effects import TargetOpponentLosesNYouGainN
from mtg_bot.game import GameState, Player, Zone, effective_keywords
from mtg_bot.turn import destroy, sacrifice
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_discard(self, state, player_id, hand_card_ids):
        return hand_card_ids[0]


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent or _PickFirstAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


# -----------------------
# TargetOpponentLosesNYouGainN
# -----------------------


def test_opponent_loses_you_gain():
    state = _new_state()
    TargetOpponentLosesNYouGainN(amount=1).resolve(
        state, 0, (("player", 1),),
    )
    assert state.players[0].life == 21
    assert state.players[1].life == 19


def test_opponent_loses_legal_targets_exclude_self():
    state = _new_state()
    legal = TargetOpponentLosesNYouGainN(amount=1).legal_targets(state, 0)
    ids = {t[1] for t in legal}
    assert 0 not in ids
    assert 1 in ids


def test_opponent_loses_no_target_noop():
    state = _new_state()
    TargetOpponentLosesNYouGainN(amount=1).resolve(state, 0, ())


def test_opponent_loses_wrong_kind_noop():
    state = _new_state()
    TargetOpponentLosesNYouGainN(amount=1).resolve(
        state, 0, (("creature", 0),),
    )


def test_opponent_loses_unknown_player_noop():
    state = _new_state()
    TargetOpponentLosesNYouGainN(amount=1).resolve(state, 0, (("player", 99),))


def test_opponent_loses_self_target_noop():
    """Defensive: self-target shouldn't mutate own life (legal_targets
    already excludes self but we double-check in resolve)."""
    state = _new_state()
    # Bypass legal_targets — directly pass self.
    TargetOpponentLosesNYouGainN(amount=3).resolve(state, 0, (("player", 0),))
    assert state.players[0].life == 20


def test_opponent_loses_describe():
    text = TargetOpponentLosesNYouGainN(amount=2).describe()
    assert "2" in text


# -----------------------
# Susurian Voidborn trigger
# -----------------------


def test_susurian_fires_when_other_creature_dies():
    state = _new_state(_PickFirstAgent())
    susurian = state.new_object(
        _PRINTINGS["Susurian Voidborn"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(susurian)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    destroy(state, bear)
    drain_stack(state)
    # Trigger fires: opponent loses 1, you gain 1.
    assert state.players[0].life == 21
    assert state.players[1].life == 19


def test_susurian_fires_on_its_own_death():
    """Susurian's trigger fires on 'this or another' — includes self."""
    state = _new_state(_PickFirstAgent())
    susurian = state.new_object(
        _PRINTINGS["Susurian Voidborn"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(susurian)
    destroy(state, susurian)
    drain_stack(state)
    assert state.players[0].life == 21
    assert state.players[1].life == 19


def test_susurian_does_not_fire_on_opponent_creature_death():
    state = _new_state()
    susurian = state.new_object(
        _PRINTINGS["Susurian Voidborn"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(susurian)
    opp_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(opp_bear)
    destroy(state, opp_bear)
    # Opponent's bear died, not under Susurian's controller's control
    # at the time, so trigger doesn't fire.
    assert state.players[0].life == 20


def test_susurian_also_fires_on_your_artifact_dying():
    from mtg_bot.cards import TOKEN_PRINTINGS
    state = _new_state(_PickFirstAgent())
    susurian = state.new_object(
        _PRINTINGS["Susurian Voidborn"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(susurian)
    # Robot token is an artifact (creature too). Sacrifice it.
    robot = state.new_object(TOKEN_PRINTINGS["Robot"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(robot)
    sacrifice(state, robot)
    drain_stack(state)
    assert state.players[0].life == 21


# -----------------------
# Alpharael Dreaming Acolyte
# -----------------------


def test_alpharael_etb_draws_two_then_discards_two():
    state = _new_state(_PickFirstAgent())
    p = state.players[0]
    for _ in range(4):
        c = state.new_object(BASIC_LANDS["Forest"], 0, Zone.LIBRARY)
        p.library.append(c)
    alpha = state.new_object(
        _PRINTINGS["Alpharael, Dreaming Acolyte"], 0, Zone.HAND,
    )
    # Simulate normal spell flow — alpha moves HAND → STACK → BATTLEFIELD
    # (put_into_battlefield doesn't remove from source zone itself).
    put_into_battlefield(state, alpha, controller_id=0)
    while state.stack:
        resolve_top_of_stack(state)
    # Starts with 0 in hand; drew 2, discarded 2 → 0 left.
    assert len(p.hand) == 0
    # Two cards in graveyard from the discard.
    assert len(p.graveyard) == 2


def test_alpharael_deathtouch_only_during_your_turn():
    state = _new_state()
    state.active_player_idx = 0
    alpha = state.new_object(
        _PRINTINGS["Alpharael, Dreaming Acolyte"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(alpha)
    # During your turn → deathtouch granted.
    assert "deathtouch" in effective_keywords(state, alpha)
    # Switch to opponent's turn.
    state.active_player_idx = 1
    assert "deathtouch" not in effective_keywords(state, alpha)


def test_alpharael_has_triggered_and_static_abilities_wired():
    a = _PRINTINGS["Alpharael, Dreaming Acolyte"]
    assert any(_matches_legacy_key(ab, "etb") for ab in a.triggered_abilities)
    assert len(a.static_abilities) == 1
