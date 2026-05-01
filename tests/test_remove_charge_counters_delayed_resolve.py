"""Resolve tests for ``RemoveChargeCountersFromSourceDelayed``.

Systems Override schedules this delayed effect against a Spacecraft to
revert the +10 charge-counter pump at the next end step. The existing
``test_gain_control.py`` builds a delayed entry and resolves it through
the stack, but the effect's defensive branches (no resolving_source,
source already left the battlefield) and the describe text aren't
exercised. These tests fill those gaps and also re-cover the happy
path explicitly via direct ``resolve()``."""

from __future__ import annotations

from mtg_bot.cards import SYNTHETIC_CREATURES, make_spacecraft
from mtg_bot.effects import RemoveChargeCountersFromSourceDelayed
from mtg_bot.game import GameState, Player, Zone


_TEST_SPACECRAFT = make_spacecraft(
    "Test Cruiser", "{4}", power=4, toughness=4, station_threshold=3,
)


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=None))
    state.players.append(Player(id=1, agent=None))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id=owner_id, zone=Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def test_resolve_decrements_charge_counters_when_source_present():
    """Happy path: resolving_source is on the battlefield, the delayed
    remove decrements its charge_counters by ``amount`` (clamped at 0)."""
    state = _new_state()
    sc = _put(state, _TEST_SPACECRAFT, owner_id=0)
    sc.charge_counters = 10
    state.resolving_source = sc

    RemoveChargeCountersFromSourceDelayed(amount=10).resolve(state, 0, ())

    assert sc.charge_counters == 0
    assert any(
        "remove 10 charge counters" in line for line in state.log
    )


def test_resolve_clamps_at_zero_when_amount_exceeds_counters():
    """Decrement clamps at 0 when ``amount`` exceeds current counters."""
    state = _new_state()
    sc = _put(state, _TEST_SPACECRAFT, owner_id=0)
    sc.charge_counters = 3
    state.resolving_source = sc

    RemoveChargeCountersFromSourceDelayed(amount=10).resolve(state, 0, ())

    assert sc.charge_counters == 0


def test_resolve_no_resolving_source_is_noop():
    """When ``state.resolving_source`` is None (e.g., the dispatcher
    didn't set it), the resolve bails silently — no log line."""
    state = _new_state()
    state.resolving_source = None

    RemoveChargeCountersFromSourceDelayed(amount=5).resolve(state, 0, ())

    assert not any(
        "remove" in line and "charge counters" in line for line in state.log
    )


def test_resolve_source_left_battlefield_is_noop():
    """The Spacecraft was scheduled but has since left the battlefield.
    The id-lookup against ``state.battlefield`` returns None and the
    resolve bails defensively without crashing."""
    state = _new_state()
    sc = _put(state, _TEST_SPACECRAFT, owner_id=0)
    sc.charge_counters = 10
    # state.resolving_source still points at the Spacecraft (the
    # delayed-trigger machinery preserves this), but the permanent
    # is no longer on the battlefield.
    state.resolving_source = sc
    state.battlefield.remove(sc)

    RemoveChargeCountersFromSourceDelayed(amount=10).resolve(state, 0, ())

    # Counters NOT mutated — the source isn't on the battlefield to
    # have its counter field updated.
    assert sc.charge_counters == 10
    assert not any(
        "remove" in line and "charge counters" in line for line in state.log
    )


def test_describe_text_mentions_charge_counters_and_amount():
    desc = RemoveChargeCountersFromSourceDelayed(amount=7).describe()
    assert "7" in desc
    assert "charge counters" in desc
