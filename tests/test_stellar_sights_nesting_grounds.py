"""Tests for Nesting Grounds — dual-target move-a-counter ability.

Also exercises _activate_ability's multi-target selection loop
(refactored from single-target to mirror _cast_spell).
"""

from mtg_bot.actions import ActivateAbility, apply_action, resolve_top_of_stack
from mtg_bot.agents import Agent
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.cards.base import make_creature
from mtg_bot.effects import MovePlusOneCounterBetweenPermanentsYouControl
from mtg_bot.game import GameState, Player, Zone, add_plus_one_counters
from mtg_bot.turn import Step

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


class _PickByIdAgent(Agent):
    """Picks targets in a scripted order (list of ids). Loops through
    them as choose_target is called."""

    def __init__(self, preferred_ids: list[int]):
        self._preferred = list(preferred_ids)

    def choose_target(self, state, player_id, legal_targets):
        for pid in self._preferred:
            for t in legal_targets:
                if t[1] == pid:
                    self._preferred.remove(pid)
                    return t
        return legal_targets[0] if legal_targets else None


def _new_state(agent=None):
    if agent is None:
        agent = _PickFirstAgent()
    state = GameState()
    state.players.append(Player(id=0, agent=agent))
    state.players.append(Player(id=1, agent=agent))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


# -----------------------
# MovePlusOneCounterBetweenPermanentsYouControl direct tests
# -----------------------


def test_move_counter_moves_one_from_donor_to_recipient():
    state = _new_state()
    donor = _put(state, make_creature("Donor", "{G}", 1, 1))
    recipient = _put(state, make_creature("Recip", "{G}", 1, 1))
    add_plus_one_counters(state, donor, 3)
    MovePlusOneCounterBetweenPermanentsYouControl().resolve(
        state, 0,
        (("permanent", donor.id), ("permanent", recipient.id)),
    )
    assert donor.plus_one_counters == 2
    assert recipient.plus_one_counters == 1


def test_move_counter_fizzles_when_donor_has_none():
    state = _new_state()
    donor = _put(state, make_creature("Donor", "{G}", 1, 1))
    recipient = _put(state, make_creature("Recip", "{G}", 1, 1))
    MovePlusOneCounterBetweenPermanentsYouControl().resolve(
        state, 0,
        (("permanent", donor.id), ("permanent", recipient.id)),
    )
    assert donor.plus_one_counters == 0
    assert recipient.plus_one_counters == 0


def test_move_counter_self_targeting_is_noop():
    """If both picks are the same permanent, no counter moves."""
    state = _new_state()
    obj = _put(state, make_creature("Self", "{G}", 1, 1))
    add_plus_one_counters(state, obj, 2)
    MovePlusOneCounterBetweenPermanentsYouControl().resolve(
        state, 0, (("permanent", obj.id), ("permanent", obj.id)),
    )
    assert obj.plus_one_counters == 2


def test_move_counter_noop_when_fewer_than_two_targets():
    state = _new_state()
    obj = _put(state, make_creature("Lone", "{G}", 1, 1))
    add_plus_one_counters(state, obj, 1)
    MovePlusOneCounterBetweenPermanentsYouControl().resolve(
        state, 0, (("permanent", obj.id),),
    )
    assert obj.plus_one_counters == 1


def test_move_counter_target_count_range_is_two_two():
    eff = MovePlusOneCounterBetweenPermanentsYouControl()
    assert eff.target_count_range() == (2, 2)


def test_move_counter_legal_targets_only_your_permanents():
    state = _new_state()
    mine = _put(state, make_creature("Mine", "{G}", 1, 1))
    theirs = _put(state, make_creature("Theirs", "{G}", 1, 1), owner_id=1)
    legal = MovePlusOneCounterBetweenPermanentsYouControl().legal_targets(
        state, 0,
    )
    assert ("permanent", mine.id) in legal
    assert ("permanent", theirs.id) not in legal


def test_move_counter_describe():
    d = MovePlusOneCounterBetweenPermanentsYouControl().describe()
    assert "counter" in d.lower()
    assert "target" in d.lower()


# -----------------------
# Nesting Grounds end-to-end (multi-target activation through _activate_ability)
# -----------------------


def test_nesting_grounds_activation_moves_counter():
    """Activate Nesting Grounds with a donor (has counters) and a
    recipient — exercises the refactored multi-target selection in
    _activate_ability."""
    state = _new_state()
    _put(state, _PRINTINGS["Nesting Grounds"])
    _put(state, BASIC_LANDS["Mountain"])
    donor = _put(state, make_creature("Donor", "{G}", 1, 1))
    recipient = _put(state, make_creature("Recip", "{G}", 1, 1))
    add_plus_one_counters(state, donor, 2)
    # Agent targets in donor-then-recipient order.
    state.players[0].agent = _PickByIdAgent([donor.id, recipient.id])
    nesting = next(
        o for o in state.battlefield
        if o.printing.name == "Nesting Grounds"
    )
    apply_action(
        state, 0, ActivateAbility(source_id=nesting.id, ability_index=0),
    )
    while state.stack:
        resolve_top_of_stack(state)
    assert donor.plus_one_counters == 1
    assert recipient.plus_one_counters == 1


def test_nesting_grounds_is_sorcery_speed():
    p = _PRINTINGS["Nesting Grounds"]
    assert p.activated_abilities[0].sorcery_speed is True


def test_nesting_grounds_not_legal_at_instant_speed():
    """At non-main-phase or stack-nonempty, the sorcery-speed gate
    filters out the activation."""
    from mtg_bot import legal_moves

    state = _new_state()
    nesting = _put(state, _PRINTINGS["Nesting Grounds"])
    _put(state, BASIC_LANDS["Mountain"])
    # Switch step to combat damage — sorcery speed is filtered.
    state.step = Step.COMBAT_DAMAGE
    actions = legal_moves(state)
    assert not any(
        isinstance(a, ActivateAbility) and a.source_id == nesting.id
        for a in actions
    )


# -----------------------
# Progress marker
# -----------------------


