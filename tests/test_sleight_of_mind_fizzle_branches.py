"""Coverage chip-away: ``SleightOfMindTextChangeEffect`` fizzle branches.

Sleight of Mind's resolve body has two defensive fizzle paths the happy-
path test in ``test_layered_edge_cases.py`` doesn't exercise:

1. **No single color word** (lines 9556-9560): the target has zero or
   multiple colors in its effective ``protection_from_color`` set.
   The substitution is unambiguous only when there's exactly one color
   to rewrite, so any other count fizzles silently with a log entry.
2. **Invalid new color choice** (lines 9567-9570): the agent's
   ``choose_mana_color`` returned a value that isn't in the legal-options
   list (defensive — a misbehaving agent can't write nonsense into the
   continuous-effects registry).

Both branches early-return without writing a layer-3
``replace_color_word`` registry entry; this test pins that contract.
"""

from __future__ import annotations

from mtg_bot.agents import Agent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.cards.demo_layers import WHITE_KNIGHT
from mtg_bot.effects.generic import SleightOfMindTextChangeEffect
from mtg_bot.game import GameState, Player, Zone


class _PickColor(Agent):
    def __init__(self, color: str):
        self._color = color

    def choose_mana_color(self, state, player_id, options):
        return self._color


def _new_state(agent: Agent | None = None) -> GameState:
    state = GameState()
    state.players.append(Player(id=0, agent=agent or _PickColor("U")))
    state.players.append(Player(id=1, agent=_PickColor("U")))
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def test_resolve_no_protection_color_fizzles():
    """A target with zero ``protection_from_color`` colors fizzles —
    no registry entry is written and a fizzle line is logged."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    SleightOfMindTextChangeEffect().resolve(
        state, controller_id=0, targets=(("permanent", bear.id),),
    )
    # No layer-3 replace_color_word entry written.
    color_word_entries = [
        ce for ce in state.continuous_effects
        if ce.kind == "replace_color_word" and ce.target_id == bear.id
    ]
    assert color_word_entries == []
    assert any("fizzles" in line for line in state.log)


def test_resolve_invalid_new_color_choice_fizzles():
    """The agent's ``choose_mana_color`` returns a value that isn't in
    the offered options (defensive against misbehaving agents) — the
    substitution fizzles."""
    # White Knight has protection from black. The legal pool is
    # {"W","U","R","G"} (excludes "B"). The agent returns "B" — the
    # excluded color — to force the invalid-choice fizzle.
    state = _new_state(agent=_PickColor("B"))
    knight = _put(state, WHITE_KNIGHT)
    SleightOfMindTextChangeEffect().resolve(
        state, controller_id=0, targets=(("permanent", knight.id),),
    )
    color_word_entries = [
        ce for ce in state.continuous_effects
        if ce.kind == "replace_color_word" and ce.target_id == knight.id
    ]
    assert color_word_entries == []
    assert any(
        "invalid new color choice" in line for line in state.log
    )


def test_resolve_no_targets_returns_silently():
    """Empty targets tuple returns early — no log line, no registry write."""
    state = _new_state()
    initial_log_len = len(state.log)
    SleightOfMindTextChangeEffect().resolve(
        state, controller_id=0, targets=(),
    )
    assert len(state.log) == initial_log_len


def test_resolve_target_off_battlefield_returns_silently():
    """A target id that isn't on the battlefield returns early."""
    state = _new_state()
    initial_log_len = len(state.log)
    SleightOfMindTextChangeEffect().resolve(
        state, controller_id=0, targets=(("permanent", 999_999),),
    )
    assert len(state.log) == initial_log_len
