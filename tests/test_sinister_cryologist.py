"""Tests for Sinister Cryologist's ETB -3/-0 debuff and the
opponents_only filter on PumpTargetCreatureUntilEOT."""

from mtg_bot.actions import put_into_battlefield, resolve_top_of_stack
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import EOE_CREATURES, SYNTHETIC_CREATURES
from mtg_bot.effects import PumpTargetCreatureUntilEOT
from mtg_bot.game import GameState, Player, Zone, effective_power
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
# opponents_only filter
# -----------------------


def test_opponents_only_filters_out_own_creatures():
    state = _new_state()
    mine = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(mine)
    theirs = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(theirs)
    targets = PumpTargetCreatureUntilEOT(
        power_bonus=-3, opponents_only=True,
    ).legal_targets(state, 0)
    ids = {tid for _, tid in targets}
    assert theirs.id in ids
    assert mine.id not in ids


def test_opponents_only_without_flag_allows_both():
    state = _new_state()
    mine = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(mine)
    theirs = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(theirs)
    targets = PumpTargetCreatureUntilEOT(power_bonus=1).legal_targets(
        state, 0,
    )
    ids = {tid for _, tid in targets}
    assert mine.id in ids and theirs.id in ids


def test_negative_pump_applies_additively():
    state = _new_state()
    enemy = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(enemy)
    PumpTargetCreatureUntilEOT(
        power_bonus=-3, opponents_only=True,
    ).resolve(state, 0, (("creature", enemy.id),))
    # Wild Bear is 2/2 → effective power 2 + (-3) = -1 before any
    # toughness-based clamping the engine may apply elsewhere; the
    # temp_power_bonus itself is -3.
    assert enemy.temp_power_bonus == -3


# -----------------------
# Sinister Cryologist ETB integration
# -----------------------


def test_cryologist_etb_debuffs_opponent_creature():
    state = _new_state(_PickFirstAgent())
    enemy = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(enemy)
    own = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(own)
    cryo = state.new_object(
        EOE_CREATURES["Sinister Cryologist"], 0, Zone.HAND,
    )
    state.players[0].hand.append(cryo)
    put_into_battlefield(state, cryo, controller_id=0)
    while state.stack:
        resolve_top_of_stack(state)
    # Only the opponent's bear should be debuffed.
    assert enemy.temp_power_bonus == -3
    assert own.temp_power_bonus == 0
    # Wild Bear was 2 power → now effective_power is -1.
    assert effective_power(state, enemy) == -1


def test_cryologist_printing_has_warp_and_etb_trigger():
    c = EOE_CREATURES["Sinister Cryologist"]
    assert c.warp_cost_str == "{U}"
    triggers = {_legacy_or_inferred_key(ab) for ab in c.triggered_abilities}
    assert "etb" in triggers
