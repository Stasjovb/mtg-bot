"""Tests for Atomic Microsizer — equip + attacks unblockable + set 1/1
until end of turn, plus equipped_creature_attacks trigger plumbing."""

from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.actions import drain_stack
from mtg_bot.combat import declare_attackers, declare_blockers
from mtg_bot.effects import AtomicMicrosizerAttackEffect
from mtg_bot.game import (
    GameState, Player, Zone,
    effective_keywords, effective_power, effective_toughness,
)
from mtg_bot.turn import run_cleanup_step
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    state.active_player_idx = 0
    return state


def _put(state, printing, owner_id=0, attached_to=None):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    if attached_to is not None:
        obj.attached_to = attached_to
    state.battlefield.append(obj)
    return obj


# -----------------------
# Effect-level
# -----------------------


def test_effect_target_count_is_up_to_one():
    e = AtomicMicrosizerAttackEffect()
    assert e.requires_target()
    assert e.target_count_range() == (0, 1)


def test_effect_sets_unblockable_and_base_pt_1_1():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    AtomicMicrosizerAttackEffect().resolve(
        state, 0, (("creature", bear.id),),
    )
    assert "unblockable" in effective_keywords(state, bear)
    # effective P/T reflects the layer-7b set_base_pt registry entry
    # (base 1/1, no counters, no pumps).
    assert effective_power(state, bear) == 1
    assert effective_toughness(state, bear) == 1


def test_cleanup_clears_base_pt_and_unblockable():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    AtomicMicrosizerAttackEffect().resolve(
        state, 0, (("creature", bear.id),),
    )
    assert "unblockable" in effective_keywords(state, bear)
    assert effective_power(state, bear) == 1
    run_cleanup_step(state)
    assert "unblockable" not in effective_keywords(state, bear)
    # Registry entry expired; bear back to printed 2/2.
    assert effective_power(state, bear) == 2
    assert effective_toughness(state, bear) == 2


def test_effect_describe():
    d = AtomicMicrosizerAttackEffect().describe()
    assert "blocked" in d and "1/1" in d


# -----------------------
# Unblockable behavior
# -----------------------


def test_declare_blockers_skips_unblockable_attackers():
    state = _new_state()
    attacker = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    attacker.attacking = True
    state.add_continuous_effect(
        source_id=attacker.id, layer=6, kind="grant_keyword",
        target_id=attacker.id, params=("unblockable",),
        expires_at=None, description="test setup",
    )
    blocker = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    declare_blockers(state, {blocker.id: attacker.id})
    assert blocker.blocking is None
    assert blocker.id not in attacker.blocked_by


# -----------------------
# Equipment attacks trigger integration
# -----------------------


def test_equipment_attacks_trigger_fires():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    bear.summoning_sick = False
    microsizer = _put(
        state, _PRINTINGS["Atomic Microsizer"], owner_id=0,
        attached_to=bear.id,
    )
    # Opponent has a creature to target.
    enemy = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    declare_attackers(state, [bear.id])
    drain_stack(state)
    # PickFirst chooses first legal target — either bear or enemy.
    # Either way, the effect applies to exactly one of them: that one
    # has its base toughness set to 1 by the layer-7b registry entry
    # (the bear also has the equipment +1/+0 attack-pump on top, so
    # power-side asserts aren't a stable signal) and carries the
    # unblockable keyword via a layer-6 grant_keyword registry entry.
    affected = [
        o for o in [bear, enemy]
        if any(
            ce.layer == 7 and ce.sublayer == 1 and ce.kind == "set_base_pt"
            and ce.target_id == o.id and ce.params == (1, 1)
            for ce in state.continuous_effects
        )
    ]
    assert len(affected) == 1
    assert "unblockable" in effective_keywords(state, affected[0])


def test_microsizer_printing_has_attack_trigger():
    m = _PRINTINGS["Atomic Microsizer"]
    triggers = {_legacy_or_inferred_key(ab, m) for ab in m.triggered_abilities}
    # Oracle text prints only the equipped-creature-attacks trigger;
    # no ETB auto-attach line, so no ETB trigger on the parser output.
    assert triggers == {"equipped_creature_attacks"}
    # Printed +1/+0 bonus.
    assert m.equipment_bonuses[0] == 1
