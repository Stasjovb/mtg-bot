"""Coverage chip-away: ``MagicalHackTextChangeEffect`` invalid-choice fizzle.

Magical Hack's resolve body has a defensive fizzle path the existing
test suite doesn't exercise: the agent's ``choose_mana_color`` returned
a value that doesn't map to a basic land type via the W/U/B/R/G →
Plains/Island/Swamp/Mountain/Forest table (lines 9472-9475 in
generic.py). When that happens the substitution silently no-ops with a
log entry and no layer-3 ``replace_basic_land_type`` registry entry.

The existing ``test_magical_hack.py`` covers the happy path (rewrite a
Forest into a Mountain) and the no-basic-land-type fizzle. This test
fills the third defensive branch.
"""

from __future__ import annotations

from mtg_bot.agents import Agent
from mtg_bot.cards.base import make_basic_land
from mtg_bot.effects.generic import MagicalHackTextChangeEffect
from mtg_bot.game import GameState, Player, Zone


class _AgentPickingNonsenseColor(Agent):
    """Returns a value that isn't a recognized W/U/B/R/G letter, so the
    color → basic land type lookup yields None and the resolve fizzles
    on the defensive 'invalid new basic land type' branch."""

    def choose_mana_color(self, state, player_id, options):
        return "X"  # unknown color letter


def _new_state() -> GameState:
    state = GameState()
    state.players.append(
        Player(id=0, agent=_AgentPickingNonsenseColor()),
    )
    state.players.append(
        Player(id=1, agent=_AgentPickingNonsenseColor()),
    )
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def test_resolve_invalid_color_choice_fizzles():
    """A ``choose_mana_color`` returning a non-WUBRG letter triggers the
    'invalid new basic land type, fizzling' branch — no registry entry
    is written and a log line records the fizzle."""
    state = _new_state()
    forest = _put(state, make_basic_land("Forest", "G"))

    MagicalHackTextChangeEffect().resolve(
        state, controller_id=0, targets=(("permanent", forest.id),),
    )

    # No layer-3 replace_basic_land_type entry written.
    entries = [
        ce for ce in state.continuous_effects
        if ce.layer == 3 and ce.kind == "replace_basic_land_type"
    ]
    assert entries == []
    assert any(
        "invalid new basic land type" in line for line in state.log
    )


def test_resolve_no_targets_returns_silently():
    """An empty target tuple returns early — no log line written."""
    state = _new_state()
    initial_log_len = len(state.log)
    MagicalHackTextChangeEffect().resolve(
        state, controller_id=0, targets=(),
    )
    assert len(state.log) == initial_log_len


def test_resolve_target_off_battlefield_returns_silently():
    """A target id that isn't on the battlefield returns early."""
    state = _new_state()
    initial_log_len = len(state.log)
    MagicalHackTextChangeEffect().resolve(
        state, controller_id=0, targets=(("permanent", 999_999),),
    )
    assert len(state.log) == initial_log_len
