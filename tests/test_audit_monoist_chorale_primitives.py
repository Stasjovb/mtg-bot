"""Unit tests for the generic primitives + formula added in
audit-monoist-chorale.

These replace the per-card bespoke effect
``MonoistCircuitFeederETBEffect`` with reusable engine-level building
blocks:

- ``CountControlledMatching`` (formula) — number of permanents the
  controller controls satisfying an ``ObjectPredicate``. Used by
  Monoist's "where X is the number of artifacts you control" body
  via ``CountControlledMatching(IsArtifact())``.
- ``PairedTargetPumpDebuffUEOT`` (effect) — paired-target opposite-
  polarity UEOT pump/debuff with a shared X. Slot 0 is a friendly
  creature (kind ``"my_creature"``); slot 1 is an opponent's creature
  (kind ``"creature"``). Both slots required: ``legal_targets``
  returns ``[]`` when either side is empty so the firing path
  fizzles before the trigger goes on the stack.

The primitives are also exercised end-to-end through the parser-bound
card path in ``tests/test_monoist_circuit_feeder.py``; the unit tests
below pin the primitives' contract independent of any specific card so
future parameterizations or new card adopters can rely on the
documented shape.
"""

from __future__ import annotations

from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.effects import PairedTargetPumpDebuffUEOT
from mtg_bot.effects.formulas import Constant, CountControlledMatching
from mtg_bot.effects.object_predicates import IsArtifact, IsCreature
from mtg_bot.game import GameState, Player, Zone

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


# ---------- helpers ----------


def _new_state() -> GameState:
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    state.active_player_idx = 0
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


# =============================================================
# CountControlledMatching formula
# =============================================================


def test_count_controlled_matching_zero_when_no_battlefield():
    state = _new_state()
    f = CountControlledMatching(IsArtifact())
    assert f.value(state, controller_id=0) == 0


def test_count_controlled_matching_counts_only_controllers_artifacts():
    state = _new_state()
    # P0: two artifacts + a non-artifact creature.
    _put(state, _PRINTINGS["Memorial Vault"], owner_id=0)
    _put(state, _PRINTINGS["Memorial Vault"], owner_id=0)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    # P1: one artifact (should not count toward P0's view).
    _put(state, _PRINTINGS["Memorial Vault"], owner_id=1)
    assert (
        CountControlledMatching(IsArtifact()).value(state, controller_id=0)
        == 2
    )
    # Symmetric — P1's view sees one.
    assert (
        CountControlledMatching(IsArtifact()).value(state, controller_id=1)
        == 1
    )


def test_count_controlled_matching_composes_with_predicate_algebra():
    state = _new_state()
    _put(state, _PRINTINGS["Memorial Vault"], owner_id=0)  # artifact
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)  # creature
    # IsArtifact() | IsCreature() — both match → 2.
    f = CountControlledMatching(IsArtifact() | IsCreature())
    assert f.value(state, controller_id=0) == 2


# =============================================================
# PairedTargetPumpDebuffUEOT — effect contract
# =============================================================


def test_paired_target_pump_debuff_declares_two_required_targets():
    e = PairedTargetPumpDebuffUEOT(
        formula=Constant(amount=1),
        positive_power=1, positive_toughness=0,
        negative_power=0, negative_toughness=-1,
    )
    assert e.requires_target() is True
    assert e.target_count_range() == (2, 2)
    assert e.target_slot_kinds() == ("my_creature", "creature")


def test_paired_target_legal_targets_empty_when_no_friendly():
    state = _new_state()
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)  # opp only
    e = PairedTargetPumpDebuffUEOT(
        formula=Constant(amount=1),
        positive_power=1, positive_toughness=0,
        negative_power=0, negative_toughness=-1,
    )
    assert e.legal_targets(state, controller_id=0) == []


def test_paired_target_legal_targets_empty_when_no_opponent():
    state = _new_state()
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)  # mine only
    e = PairedTargetPumpDebuffUEOT(
        formula=Constant(amount=1),
        positive_power=1, positive_toughness=0,
        negative_power=0, negative_toughness=-1,
    )
    assert e.legal_targets(state, controller_id=0) == []


def test_paired_target_legal_targets_uses_per_slot_kinds():
    state = _new_state()
    own = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    opp = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    e = PairedTargetPumpDebuffUEOT(
        formula=Constant(amount=1),
        positive_power=1, positive_toughness=0,
        negative_power=0, negative_toughness=-1,
    )
    legal = e.legal_targets(state, controller_id=0)
    assert ("my_creature", own.id) in legal
    assert ("creature", opp.id) in legal


def test_paired_target_resolve_grants_signed_x_to_each_slot():
    state = _new_state()
    src = _put(state, _PRINTINGS["Memorial Vault"], owner_id=0)
    own = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    opp = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    state.resolving_source = src
    try:
        # X = 3 via constant; +1*3 / -1*3 polarities.
        e = PairedTargetPumpDebuffUEOT(
            formula=Constant(amount=3),
            positive_power=1, positive_toughness=0,
            negative_power=0, negative_toughness=-1,
        )
        e.resolve(
            state, controller_id=0,
            targets=(("my_creature", own.id), ("creature", opp.id)),
        )
    finally:
        state.resolving_source = None
    assert own.temp_power_bonus == 3
    assert own.temp_toughness_bonus == 0
    assert opp.temp_power_bonus == 0
    assert opp.temp_toughness_bonus == -3


def test_paired_target_resolve_skips_slot_no_longer_legal():
    """CR 608.2b: if a chosen target is no longer legal at resolution,
    that half skips silently and the OTHER half still resolves."""
    state = _new_state()
    src = _put(state, _PRINTINGS["Memorial Vault"], owner_id=0)
    own = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    opp = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    # Take ownership of opp before resolve — now it's a friendly creature
    # and fails the "an opponent controls" check at the negative slot.
    opp.controller_id = 0
    state.resolving_source = src
    try:
        e = PairedTargetPumpDebuffUEOT(
            formula=Constant(amount=2),
            positive_power=1, positive_toughness=0,
            negative_power=0, negative_toughness=-1,
        )
        e.resolve(
            state, controller_id=0,
            targets=(("my_creature", own.id), ("creature", opp.id)),
        )
    finally:
        state.resolving_source = None
    # Friendly slot resolved.
    assert own.temp_power_bonus == 2
    # Opp slot fizzled — no toughness debuff applied.
    assert opp.temp_toughness_bonus == 0


def test_paired_target_describe_renders_polarities():
    e = PairedTargetPumpDebuffUEOT(
        formula=Constant(amount=1),
        positive_power=2, positive_toughness=1,
        negative_power=-1, negative_toughness=-2,
    )
    d = e.describe()
    # The describe rendering uses signed delta multipliers.
    assert "+2X/+1X" in d
    assert "-1X/-2X" in d


def test_paired_target_resolve_no_op_without_formula():
    """A constructed primitive without a formula resolves as a no-op
    rather than raising — defensive against partial constructions
    in test fixtures and migrations. Production parser path always
    supplies a formula."""
    state = _new_state()
    own = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    opp = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    e = PairedTargetPumpDebuffUEOT(formula=None)
    e.resolve(
        state, controller_id=0,
        targets=(("my_creature", own.id), ("creature", opp.id)),
    )
    assert own.temp_power_bonus == 0
    assert opp.temp_toughness_bonus == 0
