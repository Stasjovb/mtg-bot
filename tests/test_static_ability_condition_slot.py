"""Tests for the ``StaticAbility.condition`` slot — PR C of the
modifier-grammar pillar.

The slot is purely additive: ``None`` (default) preserves the existing
per-field-gate behavior, a populated ``Condition`` is AND-ed with the
existing gates so a card declaring its activation condition
compositionally still respects any legacy boolean toggles. Future PRs
collapse the legacy gate fields by routing through synthesised
conditions on the way down.
"""

from __future__ import annotations

import pytest

from mtg_bot.effects.base import StaticAbility, StaticScope
from mtg_bot.effects.conditions import (
    ControlPermanent,
    DuringYourTurn,
    NotCondition,
)
from mtg_bot.effects.object_predicates import IsArtifact


def _arena():
    """Two-player state with a creature for each player and the
    active-player toggle parametrised at call sites."""
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players = [Player(id=0), Player(id=1)]
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    bear.controller_id = 0
    state.battlefield.append(bear)
    return state, bear


def test_condition_field_default_none():
    """The slot defaults to ``None``; existing card definitions keep
    working without parser-side changes."""
    sa = StaticAbility(scope=StaticScope.CREATURES_YOU_CONTROL)
    assert sa.condition is None
    assert sa.replacement_effect is None
    assert sa.continuous_effect is None


def test_condition_none_matches_legacy_always_on():
    """``condition=None`` is a no-op gate — applies_to mirrors the
    pre-PR-C path."""
    state, bear = _arena()
    state.active_player_idx = 0  # bear's turn
    sa = StaticAbility(
        scope=StaticScope.CREATURES_YOU_CONTROL,
        granted_keywords=frozenset({"flying"}),
    )
    assert sa.applies_to(bear, bear, state) is True


def test_condition_blocks_when_condition_false():
    """A populated condition AND-ed with the existing gates: when
    the condition evaluates False, ``applies_to`` returns False
    regardless of scope/per-field gates."""
    state, bear = _arena()
    state.active_player_idx = 1  # NOT bear-controller's turn
    sa = StaticAbility(
        scope=StaticScope.CREATURES_YOU_CONTROL,
        granted_keywords=frozenset({"flying"}),
        condition=DuringYourTurn(),
    )
    assert sa.applies_to(bear, bear, state) is False


def test_condition_passes_when_condition_true():
    """When the condition evaluates True and the per-field gates also
    pass, ``applies_to`` returns True."""
    state, bear = _arena()
    state.active_player_idx = 0  # bear-controller's turn
    sa = StaticAbility(
        scope=StaticScope.CREATURES_YOU_CONTROL,
        granted_keywords=frozenset({"flying"}),
        condition=DuringYourTurn(),
    )
    assert sa.applies_to(bear, bear, state) is True


def test_compound_condition_blocks_when_either_clause_false():
    """Two structural conditions combined with ``&`` gate the static
    on BOTH clauses being true; either clause failing blocks
    application."""
    state, bear = _arena()
    state.active_player_idx = 0
    # Turn clause passes (active turn) but artifact clause fails (no
    # artifact controlled).
    sa = StaticAbility(
        scope=StaticScope.CREATURES_YOU_CONTROL,
        condition=DuringYourTurn() & ControlPermanent(IsArtifact()),
    )
    assert sa.applies_to(bear, bear, state) is False


def test_condition_state_none_returns_false_when_condition_present():
    """An evaluated condition needs ``state`` to call ``matches``;
    when ``state`` is None and a condition is present, the gate
    short-circuits to False (consistent with the existing per-field
    gates' state-None handling)."""
    state, bear = _arena()
    sa = StaticAbility(
        scope=StaticScope.CREATURES_YOU_CONTROL,
        condition=DuringYourTurn(),
    )
    assert sa.applies_to(bear, bear, state=None) is False


def test_replacement_effect_slot_holds_value():
    """The slot accepts a ``ReplacementEffect`` instance and exposes
    it for PR-D consumers to discover via the printing's
    ``static_abilities`` surface."""
    from mtg_bot.effects.modifiers import (
        EventPattern, MultiplyCount, ReplacementEffect,
    )
    from mtg_bot.effects.predicates import Event

    re = ReplacementEffect(
        event_pattern=EventPattern(event=Event.WOULD_CREATE_TOKEN),
        transform=MultiplyCount(2),
    )
    sa = StaticAbility(
        scope=StaticScope.SELF,
        replacement_effect=re,
    )
    assert sa.replacement_effect is re


def test_control_artifact_condition_blocks_when_no_artifact():
    """The artifact-gate static (formerly the ``requires_artifact_you_
    control`` boolean field) now rides on the structural
    ``ControlPermanent(IsArtifact())`` condition. Without an artifact on
    the controller's side of the battlefield, ``applies_to`` returns
    False — same semantics as the legacy field gate."""
    state, bear = _arena()
    state.active_player_idx = 0
    sa = StaticAbility(
        scope=StaticScope.SELF,
        power_bonus=1,
        condition=ControlPermanent(IsArtifact()),
    )
    # No artifact in play — condition fails, applies_to is False.
    assert sa.applies_to(bear, bear, state) is False


def test_control_artifact_condition_passes_when_artifact_present():
    """Mirror of the previous test: with an artifact on the controller's
    battlefield, the condition evaluates True and ``applies_to`` returns
    True."""
    from mtg_bot.cards.tokens import TOKEN_PRINTINGS
    from mtg_bot.game import Zone

    state, bear = _arena()
    state.active_player_idx = 0
    # Lander is a non-creature artifact token.
    lander = state.new_object(
        TOKEN_PRINTINGS["Lander"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(lander)
    sa = StaticAbility(
        scope=StaticScope.SELF,
        power_bonus=1,
        condition=ControlPermanent(IsArtifact()),
    )
    assert sa.applies_to(bear, bear, state) is True


def test_at_least_n_spells_cast_condition_blocks_below_threshold():
    """The spells-cast-this-turn gate (formerly the
    ``requires_spells_cast_this_turn`` integer field) now rides on the
    ``AtLeastNSpellsCastThisTurn`` Condition. Below the threshold,
    ``applies_to`` returns False — same semantics as the legacy field
    gate."""
    from mtg_bot.effects.conditions import AtLeastNSpellsCastThisTurn

    state, bear = _arena()
    state.active_player_idx = 0
    state.players[0].spells_cast_this_turn = 1  # below threshold of 2
    sa = StaticAbility(
        scope=StaticScope.SELF,
        power_bonus=2,
        condition=AtLeastNSpellsCastThisTurn(2),
    )
    assert sa.applies_to(bear, bear, state) is False


def test_at_least_n_spells_cast_condition_passes_at_threshold():
    """At or above the threshold, the condition evaluates True and
    ``applies_to`` returns True."""
    from mtg_bot.effects.conditions import AtLeastNSpellsCastThisTurn

    state, bear = _arena()
    state.active_player_idx = 0
    state.players[0].spells_cast_this_turn = 2  # at threshold
    sa = StaticAbility(
        scope=StaticScope.SELF,
        power_bonus=2,
        condition=AtLeastNSpellsCastThisTurn(2),
    )
    assert sa.applies_to(bear, bear, state) is True


def test_continuous_effect_slot_holds_value():
    """The slot accepts a ``ContinuousModifier`` instance and exposes
    it for the PR-D continuous-effect dispatcher to discover."""
    from mtg_bot.effects.modifiers import (
        ContinuousModifier, GrantKeyword,
    )

    ce = ContinuousModifier(
        layer=6,
        subject_filter=IsArtifact(),
        payload=GrantKeyword("haste"),
    )
    sa = StaticAbility(
        scope=StaticScope.CREATURES_YOU_CONTROL,
        continuous_effect=ce,
    )
    assert sa.continuous_effect is ce
