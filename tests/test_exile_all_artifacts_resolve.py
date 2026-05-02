"""Engine-resolve tests for ``ExileAllArtifactsWithManaValueAtMost``.

The parser tests in ``tests/test_parser_effects_batch12.py`` pin the
recognizer for "exile all artifacts with mana value N or less" (one of
Ruinous Rampage's modes), but no test resolves the effect directly to
verify the mass-exile sweep. The mode-pick goes through ``ModalChooseOne``
in the parent card, so the mode-1 path is rarely exercised end-to-end.

These tests exercise the resolve path against a synthetic battlefield:

- artifacts at MV ≤ cap are exiled;
- artifacts above cap stay;
- non-artifacts (creatures, lands, enchantments) are untouched;
- both controllers' artifacts are caught (untargeted mass effect);
- empty-battlefield no-op;
- describe text mentions the configured cap.
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    CardPrinting,
    ManaCost,
    parse_mana_cost,
)
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.effects.generic import ExileAllArtifactsWithManaValueAtMost
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step


def _new_state() -> GameState:
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _artifact(name: str, mana_cost_str: str) -> CardPrinting:
    """Synthesize a vanilla artifact printing with the given MV cost."""
    return CardPrinting(
        name=name,
        mana_cost_str=mana_cost_str,
        mana_cost=parse_mana_cost(mana_cost_str),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
    )


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def test_resolve_exiles_artifact_at_or_below_cap():
    state = _new_state()
    cheap = _put(state, _artifact("Cheap Artifact", "{1}"), owner_id=0)
    capped = _put(state, _artifact("Capped Artifact", "{3}"), owner_id=1)

    ExileAllArtifactsWithManaValueAtMost(max_mv=3).resolve(
        state, controller_id=0, targets=(),
    )
    assert cheap not in state.battlefield
    assert capped not in state.battlefield


def test_resolve_skips_artifact_above_cap():
    state = _new_state()
    big = _put(state, _artifact("Big Artifact", "{4}"), owner_id=0)
    ExileAllArtifactsWithManaValueAtMost(max_mv=3).resolve(state, 0)
    assert big in state.battlefield


def test_resolve_ignores_non_artifacts():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    plains = _put(state, BASIC_LANDS["Plains"], owner_id=0)
    ExileAllArtifactsWithManaValueAtMost(max_mv=5).resolve(state, 0)
    assert bear in state.battlefield
    assert plains in state.battlefield


def test_resolve_hits_both_controllers_artifacts():
    state = _new_state()
    own_art = _put(state, _artifact("Own", "{2}"), owner_id=0)
    opp_art = _put(state, _artifact("Opp", "{2}"), owner_id=1)
    ExileAllArtifactsWithManaValueAtMost(max_mv=2).resolve(state, 0)
    assert own_art not in state.battlefield
    assert opp_art not in state.battlefield


def test_resolve_empty_battlefield_is_noop():
    state = _new_state()
    ExileAllArtifactsWithManaValueAtMost(max_mv=3).resolve(state, 0)
    assert state.battlefield == []


def test_resolve_logs_each_exile():
    state = _new_state()
    _put(state, _artifact("LogMe", "{1}"), owner_id=0)
    ExileAllArtifactsWithManaValueAtMost(max_mv=3).resolve(state, 0)
    assert any(
        "LogMe" in line and "exiled" in line for line in state.log
    )


def test_describe_mentions_cap():
    text = ExileAllArtifactsWithManaValueAtMost(max_mv=3).describe()
    assert "3 or less" in text
    assert "exile" in text.lower()
    assert "artifact" in text.lower()


def test_resolve_zero_mv_artifact_caught_by_default_cap():
    """Lander tokens have MV 0 — they're caught by any positive max_mv."""
    state = _new_state()
    free_art = _put(state, _artifact("Free", ""), owner_id=0)
    assert free_art.printing.mana_cost.total == 0
    ExileAllArtifactsWithManaValueAtMost(max_mv=3).resolve(state, 0)
    assert free_art not in state.battlefield
