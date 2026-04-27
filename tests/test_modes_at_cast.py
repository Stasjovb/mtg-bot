"""Pin: modal-spell mode selection happens at cast time (CR 601.2e),
not at resolve time. The cast pipeline asks the agent for the mode
BEFORE total cost is determined and BEFORE target selection, then
caches the pick on the StackItem. ModalChooseOne.resolve replays
that pick via state.resolving_modes instead of prompting again.

Why this matters:
- Cost-sensitive mode picks (e.g. "Choose one — ... costs {1} more
  if you choose X") need the chosen mode visible to
  apply_cost_reductions at 601.2f.
- Target-selection at 601.2c-d should run against the CHOSEN mode's
  legal targets, not the union over all modes — so an agent that
  picks Mode 0 can't surface Mode 1's targets in the prompt.
- The agent's choose_mode is called exactly once per cast.
"""

from __future__ import annotations

from mtg_bot.actions import (
    CastSpell, apply_action, resolve_top_of_stack,
)
from mtg_bot.agents import Agent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.cards.base import CardPrinting, parse_mana_cost
from mtg_bot.effects import (
    DealDamageToTargetCreature, DealDamageToTargetOpponent,
    DrawCards, ModalChooseOne,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step


class _RecordingAgent(Agent):
    """Records every choose_mode / choose_target call so tests can
    pin what got asked when (and confirm choose_mode is called only
    once per cast)."""

    def __init__(self, mode_idx: int = 0):
        self.mode_idx = mode_idx
        self.mode_calls: list[list[str]] = []
        self.target_calls: list[list[tuple[str, int]]] = []

    def choose_mode(self, state, player_id, mode_descriptions):
        self.mode_calls.append(list(mode_descriptions))
        return self.mode_idx

    def choose_modes(self, state, player_id, mode_descriptions):
        self.mode_calls.append(list(mode_descriptions))
        return [self.mode_idx]

    def choose_target(self, state, player_id, legal_targets):
        self.target_calls.append(list(legal_targets))
        # Prefer opponent-controlled targets so the test assertions
        # don't accidentally hit the caster's own creatures.
        for kind, tid in legal_targets:
            if kind == "creature":
                obj = next(
                    (o for o in state.battlefield if o.id == tid), None,
                )
                if obj is not None and obj.controller_id != player_id:
                    return (kind, tid)
        return legal_targets[0] if legal_targets else None


def _new_state(agent: Agent):
    state = GameState()
    state.players.append(Player(id=0, agent=agent))
    state.players.append(Player(id=1, agent=_RecordingAgent()))
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


def _modal_spell(name: str, cost_str: str, *modes) -> CardPrinting:
    return CardPrinting(
        name=name, mana_cost_str=cost_str,
        mana_cost=parse_mana_cost(cost_str),
        type_line="Sorcery", supertypes=(),
        card_types=("Sorcery",), subtypes=(),
        spell_effect=ModalChooseOne(modes=tuple(modes)),
    )


def test_choose_mode_called_exactly_once_at_cast_time():
    """Casting a modal spell prompts choose_mode once during the cast
    pipeline. The same prompt does NOT fire again at resolution."""
    agent = _RecordingAgent(mode_idx=0)
    state = _new_state(agent)
    for _ in range(2):
        _put(state, BASIC_LANDS["Mountain"], 0)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    spell = _hand(state, _modal_spell(
        "Choose Mode", "{1}{R}",
        DealDamageToTargetCreature(amount=2),
        DrawCards(amount=1),
    ), 0)
    apply_action(state, 0, CastSpell(spell.id))
    # choose_mode fired during cast.
    assert len(agent.mode_calls) == 1
    resolve_top_of_stack(state)
    # No second prompt at resolution.
    assert len(agent.mode_calls) == 1


def test_target_selection_uses_chosen_mode_only():
    """Mode 0 deals damage to a creature; Mode 1 deals damage to a
    player. With Mode 0 chosen, the target prompt must offer ONLY
    creature targets (Mode 1's player targets are filtered out)."""
    agent = _RecordingAgent(mode_idx=0)
    state = _new_state(agent)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    spell = _hand(state, _modal_spell(
        "Choose Bolt Type", "{R}",
        DealDamageToTargetCreature(amount=2),
        DealDamageToTargetOpponent(amount=2),
    ), 0)
    _put(state, BASIC_LANDS["Mountain"], 0)
    apply_action(state, 0, CastSpell(spell.id))
    # The prompt(s) the agent saw must contain only "creature" kinds.
    assert agent.target_calls
    for call in agent.target_calls:
        for kind, _tid in call:
            assert kind == "creature", (
                f"target prompt under Mode 0 saw {kind!r} — Mode 1's "
                "player target leaked into the union pool"
            )


def test_target_selection_uses_player_pool_when_mode_1_picked():
    """Same modal spell, Mode 1 chosen → only opponent targets show
    up in the prompt."""
    agent = _RecordingAgent(mode_idx=1)
    state = _new_state(agent)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    spell = _hand(state, _modal_spell(
        "Choose Bolt Type", "{R}",
        DealDamageToTargetCreature(amount=2),
        DealDamageToTargetOpponent(amount=2),
    ), 0)
    _put(state, BASIC_LANDS["Mountain"], 0)
    apply_action(state, 0, CastSpell(spell.id))
    assert agent.target_calls
    for call in agent.target_calls:
        for kind, _tid in call:
            assert kind == "player", (
                f"target prompt under Mode 1 saw {kind!r} — Mode 0's "
                "creature target leaked into the union pool"
            )


def test_chosen_modes_persisted_on_stack_item():
    """The cast-time mode pick is stored on the StackItem so the
    resolving effect can read it via state.resolving_modes (no
    re-prompt)."""
    agent = _RecordingAgent(mode_idx=1)
    state = _new_state(agent)
    _put(state, BASIC_LANDS["Mountain"], 0)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    spell = _hand(state, _modal_spell(
        "Two Modes", "{R}",
        DealDamageToTargetCreature(amount=1),
        DrawCards(amount=1),
    ), 0)
    apply_action(state, 0, CastSpell(spell.id))
    assert state.stack
    assert state.stack[-1].chosen_modes == (1,)


def test_resolves_chosen_mode_without_reprompting():
    """End-to-end: modal spell with Mode 1 = "draw a card" picked at
    cast. Hand-card count grows by 1 at resolution; choose_mode
    isn't called a second time."""
    agent = _RecordingAgent(mode_idx=1)
    state = _new_state(agent)
    p = state.players[0]
    # Library has a card to draw.
    p.library.append(state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.LIBRARY,
    ))
    _put(state, BASIC_LANDS["Mountain"], 0)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    spell = _hand(state, _modal_spell(
        "Burn or Draw", "{R}",
        DealDamageToTargetCreature(amount=1),
        DrawCards(amount=1),
    ), 0)
    hand_before = len(p.hand)  # includes the spell itself
    apply_action(state, 0, CastSpell(spell.id))
    # Spell left the hand → -1.
    assert len(p.hand) == hand_before - 1
    resolve_top_of_stack(state)
    # Drew a card → +1.
    assert len(p.hand) == hand_before
    # choose_mode called exactly once total.
    assert len(agent.mode_calls) == 1


def test_resolving_modes_cleared_after_resolution():
    """state.resolving_modes is scoped to a single resolution and
    cleared in the finally block."""
    agent = _RecordingAgent(mode_idx=0)
    state = _new_state(agent)
    _put(state, BASIC_LANDS["Mountain"], 0)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    spell = _hand(state, _modal_spell(
        "Modal", "{R}",
        DealDamageToTargetCreature(amount=1),
        DrawCards(amount=1),
    ), 0)
    apply_action(state, 0, CastSpell(spell.id))
    resolve_top_of_stack(state)
    assert state.resolving_modes == ()
