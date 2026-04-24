"""Tests for Blast Zone + Gemstone Caverns (last of the single-card
utility lands in this pass).

Blast Zone also exercises new engine infrastructure:
- X-cost activated abilities (``{X}{X},{T}: Put X charge counters on
  this land``).
- PutChargeCountersOnSelf (ETB + X-variant).
- DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters.
"""

from mtg_bot.actions import (
    ActivateAbility, apply_action, put_into_battlefield,
    resolve_top_of_stack,
)
from mtg_bot.agents import Agent
from mtg_bot.cards import BASIC_LANDS, STELLAR_SIGHTS_LANDS
from mtg_bot.cards.base import make_artifact, make_creature
from mtg_bot.effects import (
    DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters,
    PutChargeCountersOnSelf,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step


class _ChooseXAgent(Agent):
    """Always picks the upper-bound X (maximum the player can afford)."""

    def choose_x(self, state, player_id, card_name, upper_bound):
        return upper_bound

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state(agent_cls=_ChooseXAgent):
    state = GameState()
    state.players.append(Player(id=0, agent=agent_cls()))
    state.players.append(Player(id=1, agent=agent_cls()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


# -----------------------
# PutChargeCountersOnSelf primitive
# -----------------------


def test_put_charge_counters_on_self_fixed_amount():
    state = _new_state()
    land = _put(state, STELLAR_SIGHTS_LANDS["Blast Zone"])
    state.resolving_source = land
    try:
        PutChargeCountersOnSelf(amount=3).resolve(state, 0, ())
    finally:
        state.resolving_source = None
    assert land.charge_counters == 3


def test_put_charge_counters_on_self_amount_from_x():
    state = _new_state()
    land = _put(state, STELLAR_SIGHTS_LANDS["Blast Zone"])
    state.resolving_source = land
    state.resolving_x_value = 4
    try:
        PutChargeCountersOnSelf(amount_from_x=True).resolve(state, 0, ())
    finally:
        state.resolving_source = None
        state.resolving_x_value = 0
    assert land.charge_counters == 4


def test_put_charge_counters_on_self_no_source_is_noop():
    state = _new_state()
    PutChargeCountersOnSelf(amount=1).resolve(state, 0, ())  # no-op


def test_put_charge_counters_on_self_zero_is_noop():
    """PutChargeCountersOnSelf(amount=0) / with X=0 should no-op
    instead of spamming a 'gets 0 counters' log entry."""
    state = _new_state()
    land = _put(state, STELLAR_SIGHTS_LANDS["Blast Zone"])
    state.resolving_source = land
    try:
        PutChargeCountersOnSelf(amount=0).resolve(state, 0, ())
    finally:
        state.resolving_source = None
    assert land.charge_counters == 0


# -----------------------
# DestroyEachNonlandPermanentWithMV…
# -----------------------


def test_destroy_by_mv_hits_matching_nonland_only():
    state = _new_state()
    land = _put(state, STELLAR_SIGHTS_LANDS["Blast Zone"])
    land.charge_counters = 2
    # 2-MV artifact: destroyed.
    two = _put(state, make_artifact("Cog-2", "{2}"))
    # 3-MV artifact: spared.
    three = _put(state, make_artifact("Cog-3", "{3}"))
    # 2-MV land: spared (is a land).
    forest = _put(state, BASIC_LANDS["Forest"])
    state.resolving_source = land
    try:
        DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters(
        ).resolve(state, 0, ())
    finally:
        state.resolving_source = None
    assert two not in state.battlefield
    assert three in state.battlefield
    assert forest in state.battlefield


def test_destroy_by_mv_skips_indestructible():
    state = _new_state()
    land = _put(state, STELLAR_SIGHTS_LANDS["Blast Zone"])
    land.charge_counters = 2
    indestr = _put(
        state,
        make_creature(
            "Stoic", "{2}", 2, 2, keywords=frozenset({"indestructible"}),
        ),
    )
    state.resolving_source = land
    try:
        DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters(
        ).resolve(state, 0, ())
    finally:
        state.resolving_source = None
    assert indestr in state.battlefield


# -----------------------
# Blast Zone end-to-end
# -----------------------


def test_blast_zone_enters_with_one_charge_counter():
    state = _new_state()
    bz = state.new_object(
        STELLAR_SIGHTS_LANDS["Blast Zone"], 0, Zone.HAND,
    )
    put_into_battlefield(state, bz, 0)
    while state.stack:
        resolve_top_of_stack(state)
    assert bz.charge_counters == 1


def test_blast_zone_x_ability_adds_x_charge_counters():
    """Activating {X}{X},{T}: put X charge counters — with X=3 (chosen
    by the agent), the agent spends 6 generic, land taps, counters go
    from 1 to 4."""
    state = _new_state()
    bz = _put(state, STELLAR_SIGHTS_LANDS["Blast Zone"])
    bz.charge_counters = 1
    # 6 Mountains to pay {X}{X} with X=3.
    for _ in range(6):
        _put(state, BASIC_LANDS["Mountain"])
    apply_action(
        state, 0, ActivateAbility(source_id=bz.id, ability_index=0),
    )
    while state.stack:
        resolve_top_of_stack(state)
    assert bz.charge_counters == 4
    assert bz.tapped is True


def test_blast_zone_sac_ability_destroys_matching_mv_nonland():
    """Blast Zone enters with 1 counter, pumps to 3 via {X}{X}, then
    {3},{T},Sac fires and destroys every 3-MV nonland permanent."""
    state = _new_state()
    bz = _put(state, STELLAR_SIGHTS_LANDS["Blast Zone"])
    bz.charge_counters = 3
    # Mana for {3}.
    for _ in range(3):
        _put(state, BASIC_LANDS["Mountain"])
    target = _put(state, make_creature("Three", "{1}{G}{G}", 3, 3))
    # 3-MV with colored pips still has total MV 3.
    unrelated = _put(state, make_creature("One", "{G}", 1, 1))
    apply_action(
        state, 0, ActivateAbility(source_id=bz.id, ability_index=1),
    )
    while state.stack:
        resolve_top_of_stack(state)
    assert bz not in state.battlefield
    assert target not in state.battlefield
    assert unrelated in state.battlefield


def test_blast_zone_sac_with_zero_counters_destroys_zero_mv_nonland():
    """Edge case: with 0 charge counters, destroys 0-MV nonland
    permanents (mostly tokens and {0}-cost artifacts)."""
    state = _new_state()
    bz = _put(state, STELLAR_SIGHTS_LANDS["Blast Zone"])
    bz.charge_counters = 0
    for _ in range(3):
        _put(state, BASIC_LANDS["Mountain"])
    zero_cost = _put(state, make_artifact("Chrome Mox", "{0}"))
    nonzero = _put(state, make_artifact("Big Art", "{3}"))
    apply_action(
        state, 0, ActivateAbility(source_id=bz.id, ability_index=1),
    )
    while state.stack:
        resolve_top_of_stack(state)
    assert zero_cost not in state.battlefield
    assert nonzero in state.battlefield


# -----------------------
# Gemstone Caverns — simplified
# -----------------------


def test_gemstone_caverns_is_legendary():
    p = STELLAR_SIGHTS_LANDS["Gemstone Caverns"]
    assert "Legendary" in p.supertypes


def test_gemstone_caverns_taps_for_any_color():
    state = _new_state()
    gc = _put(state, STELLAR_SIGHTS_LANDS["Gemstone Caverns"])
    apply_action(
        state, 0, ActivateAbility(source_id=gc.id, ability_index=0),
    )
    pool = state.players[0].mana_pool
    assert len(pool) == 1
    assert pool[0].color == "any"


# -----------------------
# Progress marker
# -----------------------


def test_two_more_restored_no_longer_stand_ins():
    import pathlib
    src = pathlib.Path("src/mtg_bot/cards/stellar_sights.py").read_text(
        encoding="utf-8"
    )
    for name in ("Blast Zone", "Gemstone Caverns"):
        assert f'"{name}": make_colorless_land(' not in src, (
            f"{name} still a colorless-land stand-in"
        )
