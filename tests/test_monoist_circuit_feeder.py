"""Tests for Monoist Circuit-Feeder's dual-target ETB.

Oracle: "When this creature enters, until end of turn, target creature
you control gets +X/+0 and target creature an opponent controls gets
-0/-X, where X is the number of artifacts you control."

The "target creature you control AND target creature an opponent
controls" wording makes BOTH slots required (CR 601.2c). If either
slot can't be filled, the trigger doesn't go on the stack at all.
"""

from mtg_bot.actions import (
    apply_aura_static_grants_on_attach,  # noqa: F401  (import sanity)
    drain_stack, put_into_battlefield, resolve_top_of_stack,
)
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import EOE_CREATURES, EOE_SPELLS, SYNTHETIC_CREATURES
from mtg_bot.effects import MonoistCircuitFeederETBEffect
from mtg_bot.game import GameState, Player, Zone
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


# -----------------------
# Effect-level
# -----------------------


def test_effect_requires_target_and_describe():
    e = MonoistCircuitFeederETBEffect()
    assert e.requires_target()
    assert e.target_count_range() == (2, 2)
    d = e.describe()
    assert "+X/+0" in d and "-0/-X" in d


def test_legal_targets_returns_empty_when_no_own_creature():
    state = _new_state()
    # Just an opponent's creature — own slot has no candidate.
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    e = MonoistCircuitFeederETBEffect()
    assert e.legal_targets(state, 0) == []


def test_legal_targets_returns_empty_when_no_opponent_creature():
    state = _new_state()
    # Just a friendly creature — opponent slot has no candidate.
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    e = MonoistCircuitFeederETBEffect()
    assert e.legal_targets(state, 0) == []


def test_legal_targets_mixes_both_kinds_when_both_present():
    state = _new_state()
    own = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    opp = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    e = MonoistCircuitFeederETBEffect()
    legal = e.legal_targets(state, 0)
    kinds = {kind for kind, _ in legal}
    assert "my_creature" in kinds
    assert "creature" in kinds
    ids = {tid for _, tid in legal}
    assert own.id in ids
    assert opp.id in ids


def test_resolve_applies_both_pump_and_debuff():
    state = _new_state()
    m = _put(state, EOE_CREATURES["Monoist Circuit-Feeder"], owner_id=0)
    art = _put(state, EOE_SPELLS["Memorial Vault"], owner_id=0)  # X=2
    own = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    opp = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    state.resolving_source = m
    try:
        MonoistCircuitFeederETBEffect().resolve(
            state, 0, (("my_creature", own.id), ("creature", opp.id)),
        )
    finally:
        state.resolving_source = None
    assert own.temp_power_bonus == 2  # X = Monoist + Memorial Vault
    assert opp.temp_toughness_bonus == -2


# -----------------------
# Integration: the firing pipeline gates the trigger correctly
# -----------------------


def test_etb_fizzles_when_opponent_has_no_creatures():
    """The user-reported bug: P0 plays Monoist with no opponent
    creature on the battlefield. Per oracle the trigger requires
    BOTH targets (own + opponent). Pre-fix the effect partially
    resolved (pumped P0's creature anyway). Post-fix the trigger
    must not go on the stack at all — no half-effect leak."""
    state = _new_state()
    own = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    # P1 has NO creatures.
    monoist = state.new_object(
        EOE_CREATURES["Monoist Circuit-Feeder"], 0, Zone.HAND,
    )
    put_into_battlefield(state, monoist, controller_id=0)
    # Drain whatever may be on the stack (artifact-enters observers, etc.).
    drain_stack(state)
    # Friendly creature must NOT be pumped — the trigger fizzled.
    assert own.temp_power_bonus == 0
    # Monoist itself is still on the battlefield.
    assert monoist in state.battlefield


def test_etb_fizzles_when_controller_has_no_other_creatures():
    """Inverse scenario: P0 has only Monoist itself entering, no other
    creatures. Monoist is a creature, but the oracle says 'target
    creature you control' — Monoist itself IS a creature P0 controls,
    so it's a legal target for the own slot."""
    state = _new_state()
    opp = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    monoist = state.new_object(
        EOE_CREATURES["Monoist Circuit-Feeder"], 0, Zone.HAND,
    )
    put_into_battlefield(state, monoist, controller_id=0)
    drain_stack(state)
    # Monoist is on the battlefield → counts as a self-target candidate
    # → trigger fires. With X=1 (just Monoist), opp gets -0/-1.
    assert opp.temp_toughness_bonus == -1


def test_etb_fires_when_both_sides_have_creatures():
    """Smarter agent that picks the first option of an unseen target
    kind — mirrors how a sane targeting policy would split a
    two-required-slots trigger across the two distinct kinds."""

    class _OneOfEachKindAgent(Agent):
        def choose_target(self, state, player_id, legal_targets):
            seen = getattr(self, "_seen_kinds", set())
            for cand in legal_targets:
                if cand[0] not in seen:
                    seen.add(cand[0])
                    self._seen_kinds = seen
                    return cand
            return legal_targets[0] if legal_targets else None

    state = GameState()
    state.players.append(Player(id=0, agent=_OneOfEachKindAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    own = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    opp = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    monoist = state.new_object(
        EOE_CREATURES["Monoist Circuit-Feeder"], 0, Zone.HAND,
    )
    put_into_battlefield(state, monoist, controller_id=0)
    drain_stack(state)
    # X = 1 (just Monoist). Smart agent picks one my_creature and one
    # creature — both halves resolve.
    total_own_pump = (
        monoist.temp_power_bonus + own.temp_power_bonus
    )
    assert total_own_pump == 1
    assert opp.temp_toughness_bonus == -1


def test_monoist_printing_has_flying_and_etb():
    m = EOE_CREATURES["Monoist Circuit-Feeder"]
    assert "flying" in m.keywords
    assert m.is_artifact
    triggers = {_legacy_or_inferred_key(ab) for ab in m.triggered_abilities}
    assert "etb" in triggers
