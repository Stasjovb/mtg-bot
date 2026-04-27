"""Pin: CR 601.2c target-selection rules.

Coverage:
- min-target enforcement at legal-actions: a 2-target spell needs
  at least 2 legal targets to be cast.
- per-slot kind enforcement at legal-actions: a "target friendly
  creature AND target opponent creature" spell needs both.
- "different targets" (CR 115.1b): the cast pipeline never picks
  the same target twice for distinct slots — already enforced via
  remaining.remove(), pinned here so a future refactor doesn't
  silently regress it.
- min_t coercion at cast time: an agent that returns None below
  min_t is forced to the first legal pool entry (CR 601.2c — you
  can't decline a required target if a legal one exists).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mtg_bot.actions import CastSpell, apply_action
from mtg_bot.agents import Agent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.cards.base import CardPrinting, parse_mana_cost
from mtg_bot.effects import Effect
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step


@dataclass(frozen=True)
class _TwoCreaturePings(Effect):
    """Synthetic 2-target effect: pings one damage at each chosen
    creature. Mirrors a "deal 1 damage to two different creatures"
    template — min_t=2, max_t=2, both slots are creatures."""

    def requires_target(self) -> bool:
        return True

    def target_count_range(self) -> tuple[int, int]:
        return (2, 2)

    def target_slot_kinds(self) -> tuple[str, ...]:
        return ("creature", "creature")

    def legal_targets(self, state, controller_id):
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature
        ]

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.effects.base import _apply_damage
        for t in targets:
            _apply_damage(state, t, 1)

    def describe(self):
        return "deal 1 damage to two different creatures"


@dataclass(frozen=True)
class _MyCreaturePlusOpp(Effect):
    """Synthetic mixed-slot effect: target friendly creature + target
    opponent creature. Uses target_slot_kinds for per-kind filtering."""

    def requires_target(self) -> bool:
        return True

    def target_count_range(self) -> tuple[int, int]:
        return (2, 2)

    def target_slot_kinds(self) -> tuple[str, ...]:
        return ("my_creature", "opp_creature")

    def legal_targets(self, state, controller_id):
        out = []
        for o in state.battlefield:
            if not o.printing.is_creature:
                continue
            kind = (
                "my_creature"
                if o.controller_id == controller_id
                else "opp_creature"
            )
            out.append((kind, o.id))
        return out

    def resolve(self, state, controller_id, targets=()):
        return

    def describe(self):
        return "target your creature, target opp creature"


def _spell(name, cost_str, effect):
    return CardPrinting(
        name=name, mana_cost_str=cost_str,
        mana_cost=parse_mana_cost(cost_str),
        type_line="Sorcery", supertypes=(),
        card_types=("Sorcery",), subtypes=(),
        spell_effect=effect,
    )


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


class _DeclineAfterFirstAgent(Agent):
    """Returns None on the second + subsequent target prompt — used
    to verify the cast pipeline force-picks below min_t instead of
    honoring the decline."""

    def __init__(self):
        self.calls = 0

    def choose_target(self, state, player_id, legal_targets):
        self.calls += 1
        if self.calls == 1:
            return legal_targets[0] if legal_targets else None
        return None  # decline second pick


def _new_state(p0_agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=p0_agent or _PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def _hand(state, printing, owner_id=0):
    p = state.players[owner_id]
    obj = state.new_object(printing, owner_id, Zone.HAND)
    p.hand.append(obj)
    return obj


def test_two_target_spell_unplayable_with_one_creature():
    """``min_t=2`` spell needs at least 2 legal creature targets to
    be castable — one creature on the battlefield isn't enough."""
    state = _new_state()
    _put(state, BASIC_LANDS["Mountain"], 0)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    spell = _hand(state, _spell("PingTwo", "{R}", _TwoCreaturePings()), 0)
    cast_acts = [
        a for a in legal_actions(state, 0)
        if isinstance(a, CastSpell) and a.card_id == spell.id
    ]
    assert cast_acts == []


def test_two_target_spell_playable_with_two_creatures():
    """Two creatures (any controller) → spell castable."""
    state = _new_state()
    _put(state, BASIC_LANDS["Mountain"], 0)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    spell = _hand(state, _spell("PingTwo", "{R}", _TwoCreaturePings()), 0)
    cast_acts = [
        a for a in legal_actions(state, 0)
        if isinstance(a, CastSpell) and a.card_id == spell.id
    ]
    assert len(cast_acts) == 1


def test_per_slot_kind_unplayable_without_friendly_creature():
    """A "target your creature + target opp creature" spell needs
    one of each. With only an opp creature, not castable."""
    state = _new_state()
    _put(state, BASIC_LANDS["Mountain"], 0)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    spell = _hand(state, _spell("MyAndOpp", "{R}", _MyCreaturePlusOpp()), 0)
    cast_acts = [
        a for a in legal_actions(state, 0)
        if isinstance(a, CastSpell) and a.card_id == spell.id
    ]
    assert cast_acts == []


def test_per_slot_kind_playable_with_one_each():
    """One friendly creature + one opp creature → castable."""
    state = _new_state()
    _put(state, BASIC_LANDS["Mountain"], 0)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    spell = _hand(state, _spell("MyAndOpp", "{R}", _MyCreaturePlusOpp()), 0)
    cast_acts = [
        a for a in legal_actions(state, 0)
        if isinstance(a, CastSpell) and a.card_id == spell.id
    ]
    assert len(cast_acts) == 1


def test_two_target_spell_picks_different_targets():
    """The cast pipeline removes each chosen target from the
    remaining pool so a 2-target spell never picks the same
    creature twice (CR 115.1b "different targets")."""
    state = _new_state()
    _put(state, BASIC_LANDS["Mountain"], 0)
    bear1 = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    bear2 = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    spell = _hand(state, _spell("PingTwo", "{R}", _TwoCreaturePings()), 0)
    apply_action(state, 0, CastSpell(spell.id))
    si = state.stack[-1]
    assert len(si.targets) == 2
    target_ids = [t[1] for t in si.targets]
    assert target_ids[0] != target_ids[1]
    assert set(target_ids) == {bear1.id, bear2.id}


def test_agent_declining_below_min_t_is_force_picked():
    """An agent returning None on the 2nd target prompt is coerced
    to the first legal pool entry — CR 601.2c says required targets
    can't be declined when legal ones exist."""
    agent = _DeclineAfterFirstAgent()
    state = _new_state(p0_agent=agent)
    _put(state, BASIC_LANDS["Mountain"], 0)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    spell = _hand(state, _spell("PingTwo", "{R}", _TwoCreaturePings()), 0)
    apply_action(state, 0, CastSpell(spell.id))
    # The cast went through with 2 distinct targets despite the
    # agent's None return on slot 1.
    si = state.stack[-1]
    assert len(si.targets) == 2
    assert agent.calls == 2  # both prompts fired


def test_per_slot_kind_with_only_two_friendly_unplayable_for_opp_slot():
    """Two friendly creatures + zero opp creatures → spell that
    needs one of each is NOT castable. Pin: kind-counts must match
    slot-counts, not just total count."""
    state = _new_state()
    _put(state, BASIC_LANDS["Mountain"], 0)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    spell = _hand(state, _spell("MyAndOpp", "{R}", _MyCreaturePlusOpp()), 0)
    cast_acts = [
        a for a in legal_actions(state, 0)
        if isinstance(a, CastSpell) and a.card_id == spell.id
    ]
    assert cast_acts == []
