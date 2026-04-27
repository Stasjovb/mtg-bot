"""Tests for Diplomatic Relations' two-target pump-and-fight rider.

The card reads:
    Target creature you control gets +1/+0 and gains vigilance until end
    of turn. It deals damage equal to its power to target creature an
    opponent controls.

The bespoke effect uses two distinct target kinds (``"my_creature"`` and
``"creature"``) so the flat target-pick pipeline can validate the two
slots independently. ``effective_power`` is sampled AFTER the +1/+0
applies, so a 2/2 deals 3 damage.
"""

from mtg_bot.actions import (
    CastSpell,
    apply_action,
    resolve_top_of_stack,
)
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import BASIC_LANDS, EOE_SPELLS, SYNTHETIC_CREATURES
from mtg_bot.effects import DiplomaticRelationsEffect
from mtg_bot.game import GameState, Player, Zone, effective_keywords
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step, run_cleanup_step


class _PickFirstAgent(Agent):
    """Returns the first legal target on every prompt."""

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_sacrifice(self, state, player_id, legal_object_ids):
        return legal_object_ids[0] if legal_object_ids else 0


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent or _PickFirstAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, controller_id, *, summoned=False):
    obj = state.new_object(printing, owner_id=controller_id, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = summoned
    state.battlefield.append(obj)
    return obj


# ---------------------------------------------------------------------
# happy path: pump applies AND fight rider deals post-pump damage
# ---------------------------------------------------------------------
def test_diplomatic_relations_pumps_and_deals_post_pump_damage():
    state = _new_state()
    p = state.players[0]
    for _ in range(3):
        _put(state, BASIC_LANDS["Forest"], 0)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)  # 2/2
    wurm = _put(state, SYNTHETIC_CREATURES["Great Wurm"], 1)  # 6/6
    spell = state.new_object(
        EOE_SPELLS["Diplomatic Relations"], 0, Zone.HAND
    )
    p.hand.append(spell)
    apply_action(state, 0, CastSpell(spell.id))
    # Two targets selected at cast time: my_creature + opp's creature.
    item = state.stack[-1]
    kinds = {k for (k, _) in item.targets}
    assert kinds == {"my_creature", "creature"}
    resolve_top_of_stack(state)
    # Bear is now 3/2 with vigilance UEOT.
    assert bear.temp_power_bonus == 1
    assert bear.temp_toughness_bonus == 0
    assert "vigilance" in effective_keywords(state, bear)
    # Wurm took 3 damage (post-pump bear power = 3).
    assert wurm.damage == 3


# ---------------------------------------------------------------------
# control: with no opponent's creature, the spell is uncastable
# ---------------------------------------------------------------------
def test_diplomatic_relations_uncastable_without_opponent_creature():
    state = _new_state()
    p = state.players[0]
    for _ in range(3):
        _put(state, BASIC_LANDS["Forest"], 0)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    # No opponent creature on the battlefield.
    spell = state.new_object(
        EOE_SPELLS["Diplomatic Relations"], 0, Zone.HAND
    )
    p.hand.append(spell)
    acts = legal_actions(state, 0)
    cast_acts = [
        a for a in acts
        if isinstance(a, CastSpell) and a.card_id == spell.id
    ]
    assert cast_acts == []


def test_diplomatic_relations_uncastable_without_friendly_creature():
    state = _new_state()
    p = state.players[0]
    for _ in range(3):
        _put(state, BASIC_LANDS["Forest"], 0)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    spell = state.new_object(
        EOE_SPELLS["Diplomatic Relations"], 0, Zone.HAND
    )
    p.hand.append(spell)
    acts = legal_actions(state, 0)
    cast_acts = [
        a for a in acts
        if isinstance(a, CastSpell) and a.card_id == spell.id
    ]
    assert cast_acts == []


# ---------------------------------------------------------------------
# control: vigilance grant clears at cleanup
# ---------------------------------------------------------------------
def test_diplomatic_relations_vigilance_clears_at_cleanup():
    state = _new_state()
    p = state.players[0]
    for _ in range(3):
        _put(state, BASIC_LANDS["Forest"], 0)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    _put(state, SYNTHETIC_CREATURES["Great Wurm"], 1)
    spell = state.new_object(
        EOE_SPELLS["Diplomatic Relations"], 0, Zone.HAND
    )
    p.hand.append(spell)
    apply_action(state, 0, CastSpell(spell.id))
    resolve_top_of_stack(state)
    assert "vigilance" in effective_keywords(state, bear)
    assert bear.temp_power_bonus == 1
    run_cleanup_step(state)
    assert "vigilance" not in effective_keywords(state, bear)
    assert bear.temp_power_bonus == 0


# ---------------------------------------------------------------------
# resolve-level edge cases (direct effect calls)
# ---------------------------------------------------------------------
def test_diplomatic_relations_legal_targets_split_kinds():
    state = _new_state()
    mine = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    theirs = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    legal = DiplomaticRelationsEffect().legal_targets(state, 0)
    assert ("my_creature", mine.id) in legal
    assert ("creature", theirs.id) in legal
    # No friendly creature appears under "creature" and no opp's appears
    # under "my_creature".
    assert ("creature", mine.id) not in legal
    assert ("my_creature", theirs.id) not in legal


def test_diplomatic_relations_resolve_skips_pump_if_target_left_battlefield():
    state = _new_state()
    theirs = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    # Pretend my_creature has left — pass a bogus id.
    DiplomaticRelationsEffect().resolve(
        state, 0,
        targets=(("my_creature", 9999), ("creature", theirs.id)),
    )
    # No pump was applied (no friendly creature on board) and no damage
    # dealt (we need a live source for the fight rider).
    assert theirs.damage == 0


def test_diplomatic_relations_resolve_no_targets_noop():
    state = _new_state()
    # Should not raise even with empty target tuple.
    DiplomaticRelationsEffect().resolve(state, 0, targets=())


def test_diplomatic_relations_resolve_skips_damage_if_opponent_creature_gone():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    DiplomaticRelationsEffect().resolve(
        state, 0,
        targets=(("my_creature", bear.id), ("creature", 9999)),
    )
    # Pump still applies (per MTG: each target is independently
    # validated; an illegal damage target just means no damage).
    assert bear.temp_power_bonus == 1
    assert "vigilance" in effective_keywords(state, bear)


def test_diplomatic_relations_skips_damage_if_opp_creature_changed_control():
    """If the opp's creature target is now controlled by the caster
    (e.g., a control-shift effect), the damage component is dropped —
    the rider only damages opponents' creatures."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    other = _put(state, SYNTHETIC_CREATURES["Great Wurm"], 0)
    # Give a "creature" kind target that's actually under our control.
    DiplomaticRelationsEffect().resolve(
        state, 0,
        targets=(("my_creature", bear.id), ("creature", other.id)),
    )
    assert bear.temp_power_bonus == 1
    assert other.damage == 0


def test_diplomatic_relations_skips_pump_if_friendly_changed_control():
    state = _new_state()
    # Bear created under p0 but now controlled by p1.
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    bear.controller_id = 1
    theirs = _put(state, SYNTHETIC_CREATURES["Great Wurm"], 1)
    DiplomaticRelationsEffect().resolve(
        state, 0,
        targets=(("my_creature", bear.id), ("creature", theirs.id)),
    )
    # No pump (target is no longer ours), and no damage (no live source).
    assert bear.temp_power_bonus == 0
    assert theirs.damage == 0


def test_diplomatic_relations_describe():
    text = DiplomaticRelationsEffect().describe()
    assert "vigilance" in text
    assert "+1/+0" in text
    assert "power" in text


def test_diplomatic_relations_target_count_range_is_two_two():
    assert DiplomaticRelationsEffect().target_count_range() == (2, 2)


def test_diplomatic_relations_legal_targets_empty_when_one_side_missing():
    state = _new_state()
    # Only my creature; no opp creature → empty legal list.
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    assert DiplomaticRelationsEffect().legal_targets(state, 0) == []
