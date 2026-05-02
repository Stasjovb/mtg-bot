"""Tests for the layer-7c contribution path in
``mtg_bot.game._static_bonuses``.

PR D continuous-effects infrastructure: ``_static_bonuses`` walks
every active ``ContinuousModifier`` declared on a printing's static
abilities (via ``walk_continuous_modifiers``) and folds in any
``PowerToughnessBonus`` payloads at layer 7. Today no migrated
EoE / DSK card declares a layer-7 ``ContinuousModifier``, so the
walk is a no-op contributor on the production card pool — but
synthetic StaticAbility constructions exercise the path so future
anthem migrations can rely on it.

Covered:

- A ``ContinuousModifier(layer=7, payload=PowerToughnessBonus(p, t))``
  on a source's StaticAbility contributes ``(p, t)`` to a target's
  effective P/T when ``applies_to`` accepts the (source, target).
- Multiple sources stack additively in layer 7c.
- A wiped source (Lignify / Humility — layer-6 lose_all_abilities)
  does NOT contribute its layer-7 ``PowerToughnessBonus`` (CR 613.7
  layer-7 runs after layer 6, so the source's static doesn't exist
  by then). Mirrors the existing legacy-path Lignify discipline in
  ``_static_bonuses``.
- A ``ContinuousModifier`` whose layer ≠ 7 is ignored by the new
  contributor (it's reserved for other layers' walkers).
- The new path stacks ON TOP of the legacy
  ``StaticAbility.power_bonus`` field for cards in transition: a
  StaticAbility with both ``power_bonus=2`` AND
  ``continuous_effect=ContinuousModifier(layer=7,
  PowerToughnessBonus(3, 0))`` contributes both (5/0 total).
"""

from __future__ import annotations

import pytest

from mtg_bot.effects.base import StaticAbility, StaticScope
from mtg_bot.effects.modifiers import (
    AddSubtype,
    ContinuousModifier,
    GrantKeyword,
    PowerToughnessBonus,
)


def _two_creatures():
    """Two creatures controlled by P0; the first is the static-ability
    source, the second is the buffed target. ``effective_power`` and
    ``effective_toughness`` should pick up the ContinuousModifier on
    the source's printing if applies_to admits the target."""
    from dataclasses import replace
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players = [Player(id=0), Player(id=1)]
    return state


def _put_creature(state, name, owner_id, statics=()):
    """Create a creature on the battlefield with optional static
    abilities patched onto its printing (printings are dataclasses;
    use replace to non-destructively add static_abilities)."""
    from dataclasses import replace
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.game import Zone

    base = SYNTHETIC_CREATURES[name]
    if statics:
        base = replace(base, static_abilities=tuple(statics))
    obj = state.new_object(base, owner_id, Zone.BATTLEFIELD)
    obj.controller_id = owner_id
    state.battlefield.append(obj)
    return obj


def test_layer7_pt_bonus_contributes_via_continuous_modifier():
    from mtg_bot.game import effective_power, effective_toughness

    state = _two_creatures()
    anthem = _put_creature(
        state, "Wild Bear", 0,
        statics=(
            StaticAbility(
                scope=StaticScope.OTHER_CREATURES_YOU_CONTROL,
                continuous_effect=ContinuousModifier(
                    layer=7,
                    payload=PowerToughnessBonus(
                        power_bonus=1, toughness_bonus=2,
                    ),
                ),
            ),
        ),
    )
    target = _put_creature(state, "Wild Bear", 0)

    assert effective_power(state, target) == 2 + 1  # printed 2, +1
    assert effective_toughness(state, target) == 2 + 2  # printed 2, +2
    # The anthem itself is OTHER_CREATURES_YOU_CONTROL — applies_to
    # excludes the source; anthem's own P/T is unmodified.
    assert effective_power(state, anthem) == 2


def test_layer7_pt_bonus_stacks_across_sources():
    from mtg_bot.game import effective_power, effective_toughness

    state = _two_creatures()
    for _ in range(3):
        _put_creature(
            state, "Wild Bear", 0,
            statics=(
                StaticAbility(
                    scope=StaticScope.OTHER_CREATURES_YOU_CONTROL,
                    continuous_effect=ContinuousModifier(
                        layer=7,
                        payload=PowerToughnessBonus(
                            power_bonus=1, toughness_bonus=0,
                        ),
                    ),
                ),
            ),
        )
    target = _put_creature(state, "Wild Bear", 0)
    # Three sources, each contributing +1/+0; target's effective
    # power is printed 2 + 3 = 5; toughness untouched at 2.
    assert effective_power(state, target) == 5
    assert effective_toughness(state, target) == 2


def test_layer7_pt_bonus_skipped_when_source_layer6_wiped():
    """A source with ``lose_all_abilities`` registry entry (Humility-
    style wipe) does NOT contribute its layer-7 PowerToughnessBonus.
    Mirrors the Lignify discipline in the legacy path — CR 613.7
    layer-7 runs after layer 6, so a wiped source's static doesn't
    exist by the time P/T is computed."""
    from mtg_bot.game import effective_power, effective_toughness

    state = _two_creatures()
    anthem = _put_creature(
        state, "Wild Bear", 0,
        statics=(
            StaticAbility(
                scope=StaticScope.OTHER_CREATURES_YOU_CONTROL,
                continuous_effect=ContinuousModifier(
                    layer=7,
                    payload=PowerToughnessBonus(
                        power_bonus=3, toughness_bonus=3,
                    ),
                ),
            ),
        ),
    )
    target = _put_creature(state, "Wild Bear", 0)
    assert effective_power(state, target) == 5  # +3 active

    # Apply Humility: a layer-6 lose_all_abilities entry on the
    # anthem's source. The walker's _source_layer6_wiped check
    # should now skip the bonus.
    state.add_continuous_effect(
        source_id=anthem.id,  # self-wipe for test simplicity
        layer=6,
        kind="lose_all_abilities",
        target_id=anthem.id,
        params=(),
        expires_at=None,
        description="test wipe",
    )
    assert effective_power(state, target) == 2  # +3 dropped
    assert effective_toughness(state, target) == 2


def test_layer7_walker_ignores_other_layers():
    """A ContinuousModifier at layer != 7 must NOT contribute via
    the new layer-7c walker — those layers belong to other
    consumers (e.g., effective_keywords for layer 6)."""
    from mtg_bot.game import effective_power

    state = _two_creatures()
    _put_creature(
        state, "Wild Bear", 0,
        statics=(
            StaticAbility(
                scope=StaticScope.OTHER_CREATURES_YOU_CONTROL,
                continuous_effect=ContinuousModifier(
                    layer=6,
                    payload=GrantKeyword("flying"),
                ),
            ),
        ),
    )
    target = _put_creature(state, "Wild Bear", 0)
    # Bear has no anthem-power-bonus path — only a layer-6 grant
    # which the layer-7 walker must skip.
    assert effective_power(state, target) == 2


def test_legacy_power_bonus_and_continuous_modifier_stack():
    """During the migration of anthems from per-StaticAbility
    ``power_bonus`` flags to ``ContinuousModifier`` declarations,
    a transitional StaticAbility might carry BOTH paths. Both must
    contribute additively so a half-migrated card never under-
    counts. After the migration is complete, the legacy field is
    typically zero on migrated cards; this test pins the additive
    semantics for the transition window."""
    from mtg_bot.game import effective_power, effective_toughness

    state = _two_creatures()
    _put_creature(
        state, "Wild Bear", 0,
        statics=(
            StaticAbility(
                scope=StaticScope.OTHER_CREATURES_YOU_CONTROL,
                power_bonus=2,
                toughness_bonus=0,
                continuous_effect=ContinuousModifier(
                    layer=7,
                    payload=PowerToughnessBonus(
                        power_bonus=3, toughness_bonus=0,
                    ),
                ),
            ),
        ),
    )
    target = _put_creature(state, "Wild Bear", 0)
    # 2 (printed) + 2 (legacy field) + 3 (continuous modifier) = 7.
    assert effective_power(state, target) == 7
    assert effective_toughness(state, target) == 2
