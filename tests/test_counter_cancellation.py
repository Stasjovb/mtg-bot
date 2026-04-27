"""SBA: +1/+1 and -1/-1 counter cancellation (CR 704.5r in current
rules, labelled 704.5n in this codebase's audit).

When a permanent has both kinds of counters, N pairs are removed
where N is the smaller count. Cancellation runs in
``state_based_actions`` and the SBA loop re-evaluates downstream
rules (704.5f / 704.5g) on the post-cancellation P/T.
"""

from __future__ import annotations

from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.game import (
    GameState, Player, Zone, add_minus_one_counters,
    add_plus_one_counters, effective_power, effective_toughness,
)
from mtg_bot.turn import Step, state_based_actions


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=None))
    state.players.append(Player(id=1, agent=None))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


# ---------- counter accumulation ----------


def test_minus_one_counters_reduce_pt_before_cancellation():
    """A creature with only -1/-1 counters gets P/T reduced. -3/-0
    on a 2/2 Wild Bear isn't possible from -1/-1 alone (they're
    symmetric), but two -1/-1 counters reduce 2/2 → 0/0."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    add_minus_one_counters(state, bear, 2)
    assert effective_power(state, bear) == 0
    assert effective_toughness(state, bear) == 0


def test_plus_and_minus_counters_offset_via_pt_calc_pre_sba():
    """Before SBA cancellation, both counter sets coexist.
    ``effective_power`` / ``effective_toughness`` apply both signs."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    add_plus_one_counters(state, bear, 3)
    add_minus_one_counters(state, bear, 1)
    # Net: +2/+2. 2/2 + 2 = 4/4.
    assert effective_power(state, bear) == 4
    assert effective_toughness(state, bear) == 4


# ---------- SBA cancellation ----------


def test_sba_cancels_pairs_keeping_excess_plus_ones():
    """3 +1/+1 and 1 -1/-1 → 2 +1/+1 left after cancellation."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    add_plus_one_counters(state, bear, 3)
    add_minus_one_counters(state, bear, 1)
    state_based_actions(state)
    assert bear.plus_one_counters == 2
    assert bear.minus_one_counters == 0
    assert effective_power(state, bear) == 4


def test_sba_cancels_pairs_keeping_excess_minus_ones():
    """1 +1/+1 and 3 -1/-1 on a Great Wurm (6/6). Net -2 → 5/5
    after cancellation. 0 +1/+1, 2 -1/-1 left. Bear is alive
    because toughness 4 > 0."""
    state = _new_state()
    wurm = _put(state, SYNTHETIC_CREATURES["Great Wurm"], 0)
    add_plus_one_counters(state, wurm, 1)
    add_minus_one_counters(state, wurm, 3)
    state_based_actions(state)
    assert wurm in state.battlefield
    assert wurm.plus_one_counters == 0
    assert wurm.minus_one_counters == 2
    assert effective_toughness(state, wurm) == 4


def test_sba_cancels_equal_counts_to_zero():
    """Equal counts → both go to zero."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    add_plus_one_counters(state, bear, 2)
    add_minus_one_counters(state, bear, 2)
    state_based_actions(state)
    assert bear.plus_one_counters == 0
    assert bear.minus_one_counters == 0
    # Bear is back to its printed P/T.
    assert effective_power(state, bear) == 2
    assert effective_toughness(state, bear) == 2


def test_sba_cancellation_can_kill_via_lethal_toughness():
    """3 -1/-1 counters on a 2/2 Bear → toughness 0 → dies via
    704.5f. The SBA loop catches both passes: cancellation
    (no-op since no +1/+1), then toughness-≤0 death."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    add_minus_one_counters(state, bear, 3)
    state_based_actions(state)
    assert bear not in state.battlefield


def test_sba_cancellation_then_loop_finds_post_cancel_lethal():
    """1 +1/+1 and 4 -1/-1 → after cancellation, 0 +1/+1 / 3 -1/-1
    counters remain. Bear is 2-3 = -1 toughness → dies in the
    same SBA call (loop catches the post-cancellation 704.5f)."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    add_plus_one_counters(state, bear, 1)
    add_minus_one_counters(state, bear, 4)
    state_based_actions(state)
    assert bear not in state.battlefield


def test_sba_cancellation_saves_doomed_creature():
    """Reverse of the above: 4 +1/+1 and 1 -1/-1. Pre-cancel net
    is +3/+3 (2+3=5/5); post-cancel is +3/+3 (3 +1/+1 left). Either
    way bear lives. Pin that the order doesn't accidentally kill."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    add_plus_one_counters(state, bear, 4)
    add_minus_one_counters(state, bear, 1)
    state_based_actions(state)
    assert bear in state.battlefield
    assert bear.plus_one_counters == 3
    assert bear.minus_one_counters == 0
    assert effective_power(state, bear) == 5
