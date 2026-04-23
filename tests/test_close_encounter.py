"""Tests for Close Encounter's additional-cost + power-based damage."""

from mtg_bot.actions import (
    CastSpell,
    apply_action,
    resolve_top_of_stack,
)
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import BASIC_LANDS, EOE_SPELLS, SYNTHETIC_CREATURES
from mtg_bot.effects import CloseEncounterEffect
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step


class _PickFirstAgent(Agent):
    def choose_sacrifice(self, state, player_id, legal_object_ids):
        return legal_object_ids[0]

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


class _ChooseOpponentCreatureAgent(Agent):
    """For Close Encounter: designates first owned creature (via
    choose_sacrifice) and targets first opponent creature (via
    choose_target)."""

    def choose_sacrifice(self, state, player_id, legal_object_ids):
        return legal_object_ids[0]

    def choose_target(self, state, player_id, legal_targets):
        for kind, tid in legal_targets:
            if kind == "creature":
                obj = next(
                    (o for o in state.battlefield if o.id == tid), None
                )
                if obj is not None and obj.controller_id != player_id:
                    return (kind, tid)
        return legal_targets[0] if legal_targets else None


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent or _PickFirstAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.step = Step.PRECOMBAT_MAIN
    return state


def test_close_encounter_unplayable_without_a_creature():
    """Without a creature you control, Close Encounter isn't castable —
    the additional cost (designate a creature) can't be paid."""
    state = _new_state()
    p = state.players[0]
    for _ in range(2):
        l = state.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(l)
    close = state.new_object(EOE_SPELLS["Close Encounter"], 0, Zone.HAND)
    p.hand.append(close)
    acts = legal_actions(state, 0)
    cast_acts = [
        a for a in acts
        if isinstance(a, CastSpell) and a.card_id == close.id
    ]
    assert cast_acts == []


def test_close_encounter_deals_damage_equal_to_chosen_creatures_power():
    state = _new_state(_ChooseOpponentCreatureAgent())
    p = state.players[0]
    # 2 Forests + a chosen-power creature (Great Wurm = 6/6).
    for _ in range(2):
        l = state.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(l)
    wurm = state.new_object(
        SYNTHETIC_CREATURES["Great Wurm"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(wurm)
    # Opponent has a creature to target.
    victim = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(victim)
    close = state.new_object(EOE_SPELLS["Close Encounter"], 0, Zone.HAND)
    p.hand.append(close)
    apply_action(state, 0, CastSpell(close.id))
    resolve_top_of_stack(state)
    # Great Wurm's power is 6, damage to Bear = 6.
    assert victim.damage == 6


def test_close_encounter_preserves_additional_cost_choice_across_stack():
    state = _new_state()
    p = state.players[0]
    for _ in range(2):
        l = state.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(l)
    wurm = state.new_object(
        SYNTHETIC_CREATURES["Great Wurm"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(wurm)
    victim = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(victim)
    close = state.new_object(EOE_SPELLS["Close Encounter"], 0, Zone.HAND)
    p.hand.append(close)
    apply_action(state, 0, CastSpell(close.id))
    item = state.stack[-1]
    assert item.additional_cost_choice_id == wurm.id


def test_close_encounter_resolving_choice_cleared_after_resolution():
    state = _new_state()
    p = state.players[0]
    for _ in range(2):
        l = state.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(l)
    wurm = state.new_object(
        SYNTHETIC_CREATURES["Great Wurm"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(wurm)
    victim = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(victim)
    close = state.new_object(EOE_SPELLS["Close Encounter"], 0, Zone.HAND)
    p.hand.append(close)
    apply_action(state, 0, CastSpell(close.id))
    resolve_top_of_stack(state)
    assert state.resolving_additional_cost_choice_id is None


def test_close_encounter_fallback_when_designated_creature_has_left():
    """If the designated creature left the battlefield before Close
    Encounter resolves, damage falls back to 0 (our simplified snapshot)."""
    state = _new_state()
    effect = CloseEncounterEffect()
    state.resolving_additional_cost_choice_id = 999  # bogus
    victim = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(victim)
    effect.resolve(state, 0, (("creature", victim.id),))
    assert victim.damage == 0


def test_close_encounter_no_target_noop():
    state = _new_state()
    effect = CloseEncounterEffect()
    state.resolving_additional_cost_choice_id = 5
    effect.resolve(state, 0, ())


def test_close_encounter_wrong_kind_noop():
    state = _new_state()
    effect = CloseEncounterEffect()
    state.resolving_additional_cost_choice_id = 5
    effect.resolve(state, 0, (("player", 0),))


def test_close_encounter_no_cost_choice_noop():
    state = _new_state()
    effect = CloseEncounterEffect()
    victim = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(victim)
    state.resolving_additional_cost_choice_id = None
    effect.resolve(state, 0, (("creature", victim.id),))
    assert victim.damage == 0


def test_close_encounter_legal_targets_include_all_creatures():
    state = _new_state()
    mine = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(mine)
    theirs = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(theirs)
    legal = CloseEncounterEffect().legal_targets(state, 0)
    ids = {t[1] for t in legal}
    assert mine.id in ids
    assert theirs.id in ids


def test_close_encounter_describe():
    text = CloseEncounterEffect().describe()
    assert "power" in text
    assert "target creature" in text
