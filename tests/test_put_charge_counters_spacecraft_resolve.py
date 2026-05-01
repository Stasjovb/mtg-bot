"""Engine-resolve happy-path tests for
``PutChargeCountersOnTargetSpacecraftYouControl``.

Existing tests in ``test_rules_cards_misc.py`` cover the no-op /
defensive branches (no target, wrong kind, missing id), but no test
exercises the actual happy path that mutates ``charge_counters`` on
a Spacecraft. These tests cover the happy path, ``requires_target``,
``legal_targets`` filtering (Spacecraft-only, you-control-only), and
the describe text."""

from __future__ import annotations

from mtg_bot.cards import SYNTHETIC_CREATURES, make_spacecraft
from mtg_bot.effects import PutChargeCountersOnTargetSpacecraftYouControl
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step


_TEST_SPACECRAFT = make_spacecraft(
    "Test Cruiser", "{4}", power=4, toughness=4, station_threshold=3,
)


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=None))
    state.players.append(Player(id=1, agent=None))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id=owner_id, zone=Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def test_resolve_adds_charge_counters_to_target_spacecraft():
    """Happy path: a Spacecraft you control gets ``amount`` charge
    counters and the log records the new total."""
    state = _new_state()
    sc = _put(state, _TEST_SPACECRAFT, owner_id=0)
    assert sc.charge_counters == 0

    PutChargeCountersOnTargetSpacecraftYouControl(amount=5).resolve(
        state, 0, (("permanent", sc.id),),
    )

    assert sc.charge_counters == 5
    assert any(
        "5 charge counters" in line for line in state.log
    )


def test_resolve_default_amount_is_five():
    """Default ``amount`` per dataclass is 5 — verify the unparam'd
    constructor adds five counters."""
    state = _new_state()
    sc = _put(state, _TEST_SPACECRAFT, owner_id=0)

    PutChargeCountersOnTargetSpacecraftYouControl().resolve(
        state, 0, (("permanent", sc.id),),
    )

    assert sc.charge_counters == 5


def test_resolve_custom_amount_one_counter():
    """Distinct amount value flows through to the helper call."""
    state = _new_state()
    sc = _put(state, _TEST_SPACECRAFT, owner_id=0)

    PutChargeCountersOnTargetSpacecraftYouControl(amount=1).resolve(
        state, 0, (("permanent", sc.id),),
    )

    assert sc.charge_counters == 1


def test_requires_target_is_true():
    eff = PutChargeCountersOnTargetSpacecraftYouControl()
    assert eff.requires_target() is True


def test_legal_targets_excludes_non_spacecraft_and_opponent_controlled():
    """Filter: Spacecraft AND controlled by ``controller_id``."""
    state = _new_state()
    own_sc = _put(state, _TEST_SPACECRAFT, owner_id=0)
    opp_sc = _put(state, _TEST_SPACECRAFT, owner_id=1)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)

    legal = PutChargeCountersOnTargetSpacecraftYouControl().legal_targets(
        state, 0,
    )
    target_ids = {tid for _, tid in legal}
    assert own_sc.id in target_ids
    assert opp_sc.id not in target_ids
    assert bear.id not in target_ids


def test_resolve_non_spacecraft_target_is_noop():
    """Defensive recheck: a non-Spacecraft permanent slipping through
    targeting bails before mutating counters."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)

    PutChargeCountersOnTargetSpacecraftYouControl(amount=2).resolve(
        state, 0, (("permanent", bear.id),),
    )

    # Wild Bear has no charge_counters semantics; verify resolve bailed
    # without logging a charge-counter line.
    assert not any("charge counters" in line for line in state.log)


def test_describe_text_mentions_charge_counters():
    desc = PutChargeCountersOnTargetSpacecraftYouControl(amount=5).describe()
    assert "5 charge counters" in desc
    assert "Spacecraft" in desc
