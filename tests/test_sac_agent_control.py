"""Pin: ``Agent.choose_sac_for_mana`` controls which sac-for-mana
abilities fire during cost payment, and in what order. The engine
still skips activations that wouldn't help (matches the original
"only blow up Treasures when they're actually needed" gate)."""

from __future__ import annotations

from mtg_bot.actions import CastSpell, apply_action
from mtg_bot.agents import Agent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.cards.base import (
    ActivatedAbility, ActivationCost, CardPrinting, ManaCost,
    parse_mana_cost,
)
from mtg_bot.effects.generic import (
    AddManaToPool, DealDamageToTargetCreature,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step


def _treasure(produces_color: str, name_suffix: str = "") -> CardPrinting:
    return CardPrinting(
        name=f"Treasure-{produces_color}{name_suffix} (test)",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Token Artifact — Treasure",
        supertypes=("Token",),
        card_types=("Artifact",),
        subtypes=("Treasure",),
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(sacrifice_self=True),
                effect=AddManaToPool(produces=((produces_color, 1),)),
                is_mana_ability=True,
            ),
        ),
    )


_TREASURE_R = _treasure("R")
_TREASURE_C = _treasure("C")


def _instant(name: str, cost_str: str) -> CardPrinting:
    return CardPrinting(
        name=name, mana_cost_str=cost_str,
        mana_cost=parse_mana_cost(cost_str),
        type_line="Instant", supertypes=(),
        card_types=("Instant",), subtypes=(),
        spell_effect=DealDamageToTargetCreature(amount=1),
    )


class _BaseAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        for kind, tid in legal_targets:
            if kind == "creature":
                obj = next(
                    (o for o in state.battlefield if o.id == tid), None,
                )
                if obj is not None and obj.controller_id != player_id:
                    return (kind, tid)
        return legal_targets[0] if legal_targets else None


class _DeclineSacAgent(_BaseAgent):
    """Returns [] from choose_sac_for_mana — agent refuses to sac
    anything. The cast goes through with an unpaid cost (legality
    gate would normally prevent this; we drive apply_action directly
    to probe the helper)."""

    def __init__(self):
        self.sac_calls: list[list[tuple[int, tuple]]] = []

    def choose_sac_for_mana(
        self, state, player_id, candidates,
        remaining_generic, remaining_colored,
    ):
        self.sac_calls.append(list(candidates))
        return []


class _PreferRedAgent(_BaseAgent):
    """Returns sac sources in {R}-first order: any source whose
    produces includes "R" comes first."""

    def __init__(self):
        self.sac_calls: list[list[tuple[int, tuple]]] = []

    def choose_sac_for_mana(
        self, state, player_id, candidates,
        remaining_generic, remaining_colored,
    ):
        self.sac_calls.append(list(candidates))
        red_first = sorted(
            candidates,
            key=lambda c: 0 if any(col == "R" for col, _ in c[1]) else 1,
        )
        return [oid for oid, _ in red_first]


def _new_state(p0_agent: Agent):
    state = GameState()
    state.players.append(Player(id=0, agent=p0_agent))
    state.players.append(Player(id=1, agent=_BaseAgent()))
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


def test_agent_declining_skips_sac_entirely():
    """``choose_sac_for_mana`` returning [] means no sources fire,
    even when the cost can't otherwise be paid."""
    agent = _DeclineSacAgent()
    state = _new_state(agent)
    treasure = _put(state, _TREASURE_R, 0)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    bolt = _hand(state, _instant("Solo R", "{R}"), 0)
    apply_action(state, 0, CastSpell(bolt.id))
    # Agent was prompted with the candidate Treasure.
    assert len(agent.sac_calls) == 1
    assert len(agent.sac_calls[0]) == 1
    assert agent.sac_calls[0][0][0] == treasure.id
    # Treasure not sac'd.
    assert treasure in state.battlefield


def test_agent_red_preference_ordering_used():
    """Two Treasures (one R, one C); cost is {R}. The agent ranks R
    first, so the engine activates Treasure-R and stops without
    touching Treasure-C."""
    agent = _PreferRedAgent()
    state = _new_state(agent)
    t_red = _put(state, _TREASURE_R, 0)
    t_col = _put(state, _TREASURE_C, 0)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    bolt = _hand(state, _instant("Solo R", "{R}"), 0)
    apply_action(state, 0, CastSpell(bolt.id))
    # Treasure-R sac'd; Treasure-C alive.
    assert t_red not in state.battlefield
    assert t_col in state.battlefield


def test_agent_called_with_remaining_cost():
    """``choose_sac_for_mana`` receives the unpaid cost as
    (remaining_generic, remaining_colored) so a smarter agent could
    rank by what's actually needed."""

    captured: dict = {}

    class _CaptureAgent(_BaseAgent):
        def choose_sac_for_mana(
            self, state, player_id, candidates,
            remaining_generic, remaining_colored,
        ):
            captured["generic"] = remaining_generic
            captured["colored"] = list(remaining_colored)
            return [oid for oid, _ in candidates]

    state = _new_state(_CaptureAgent())
    _put(state, _TREASURE_R, 0)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    bolt = _hand(state, _instant("Solo R", "{R}"), 0)
    apply_action(state, 0, CastSpell(bolt.id))
    assert captured["generic"] == 0
    assert captured["colored"] == [("R", 1)]


def test_engine_skips_unhelpful_sources_even_if_agent_listed_them():
    """If the agent insists on sacrificing a Treasure-{C} for a
    {R}-only cost, the engine still skips it — sacrificing the
    wrong color doesn't help and Treasures shouldn't blow up
    uselessly."""

    class _WastefulAgent(_BaseAgent):
        def choose_sac_for_mana(
            self, state, player_id, candidates,
            remaining_generic, remaining_colored,
        ):
            return [oid for oid, _ in candidates]

    state = _new_state(_WastefulAgent())
    treasure = _put(state, _TREASURE_C, 0)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    bolt = _hand(state, _instant("Solo R", "{R}"), 0)
    apply_action(state, 0, CastSpell(bolt.id))
    # Treasure stayed put — engine vetoed the unhelpful sac.
    assert treasure in state.battlefield


def test_default_agent_behavior_unchanged():
    """The base Agent class returns every candidate in order — the
    engine still stops as soon as the cost is payable, so behavior
    is the same as the prior auto-greedy path."""
    state = _new_state(_BaseAgent())
    t1 = _put(state, _TREASURE_R, 0)
    t2 = _put(state, _TREASURE_R, 0, name_suffix="-2") if False else _put(state, _TREASURE_R, 0)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    bolt = _hand(state, _instant("Solo R", "{R}"), 0)
    apply_action(state, 0, CastSpell(bolt.id))
    # Exactly one Treasure sacrificed — the first one in engine order.
    on_field = [t for t in [t1, t2] if t in state.battlefield]
    assert len(on_field) == 1
