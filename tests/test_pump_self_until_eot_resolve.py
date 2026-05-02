"""Coverage chip-away: ``PumpSelfUntilEOT`` resolve paths.

The ``PumpSelfUntilEOT`` primitive (used by ``"This creature gets
+N/+M and gains KW until end of turn."`` activated bodies) routes its
self-target through ``state.resolving_source`` rather than the targeting
pipeline. Two resolve branches are independently gated:

1. **+P/+T branch** (lines 5013-5021): writes a layer-7 grant_pt_pump_ueot
   registry entry sourced by and targeting the source itself.
2. **granted_keywords branch** (lines 5022-5029): wraps a
   ``GrantKeywords`` in ``ApplyEffect(..., EndOfTurn())`` and resolves
   it against a self-target — the layer-6 ``grant_keyword`` registry
   entries land on the source.

Both branches independently no-op when ``state.resolving_source`` is
None (line 5012). This test pins the granted_keywords branch (the bare
+P/+T branch is exercised by parser-shape tests via the integration
path; the keyword-grant branch was untested at the resolve level).
"""

from __future__ import annotations

from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.effects.generic import PumpSelfUntilEOT
from mtg_bot.game import (
    GameState, Player, Zone, effective_keywords, effective_power,
    effective_toughness,
)


def _new_state() -> GameState:
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    return state


def _put_bear(state, owner_id=0):
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    return bear


def test_resolve_grants_pump_and_keyword_on_self():
    """+P/+T AND granted_keywords on the source: layer-7 P/T entry +
    layer-6 grant_keyword entry both target the source."""
    state = _new_state()
    bear = _put_bear(state)
    state.resolving_source = bear

    PumpSelfUntilEOT(
        power_bonus=2, toughness_bonus=2,
        granted_keywords=frozenset({"lifelink"}),
    ).resolve(state, controller_id=0)

    assert effective_power(state, bear) == 4  # 2 base + 2
    assert effective_toughness(state, bear) == 4
    assert "lifelink" in effective_keywords(state, bear)


def test_resolve_keyword_only_branch_uses_apply_effect():
    """Pure granted_keywords with zero +P/+T still walks the
    ApplyEffect/EndOfTurn keyword-grant branch and writes a layer-6
    grant_keyword registry entry on the source."""
    state = _new_state()
    bear = _put_bear(state)
    state.resolving_source = bear

    PumpSelfUntilEOT(
        granted_keywords=frozenset({"flying", "trample"}),
    ).resolve(state, controller_id=0)

    kws = effective_keywords(state, bear)
    assert "flying" in kws
    assert "trample" in kws
    # No +P/+T entry written — pure keyword grant.
    assert effective_power(state, bear) == 2
    assert effective_toughness(state, bear) == 2


def test_resolve_no_source_returns_silently():
    """Without ``state.resolving_source``, the effect early-returns
    before either branch fires."""
    state = _new_state()
    state.resolving_source = None
    initial_log_len = len(state.log)
    PumpSelfUntilEOT(
        power_bonus=1, toughness_bonus=1,
        granted_keywords=frozenset({"haste"}),
    ).resolve(state, controller_id=0)
    assert len(state.log) == initial_log_len
    # No registry entries written.
    assert state.continuous_effects == []


def test_describe_pure_pump_no_keyword_clause():
    """The describe surface omits the keyword phrase when granted_keywords
    is empty."""
    e = PumpSelfUntilEOT(power_bonus=1, toughness_bonus=1)
    assert e.describe() == "this gets +1/+1 until end of turn"
