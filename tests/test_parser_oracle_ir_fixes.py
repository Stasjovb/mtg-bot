"""Parser output (and the Python engine's play) for cube cards whose card
IR said something other than their Oracle text (mtg-zero
``docs/ir_defects.md`` entries 1, 2, 4, 12, 13, 15, 16, 17, 18).

Each test pins the printing the oracle-text parser builds for the card
(the data the card IR exports) and, where the fix changed or could have
changed the Python engine's behaviour, plays the card through it.
"""

from __future__ import annotations

from mtg_bot.actions import drain_stack, resolve_top_of_stack
from mtg_bot.cards.parser.land_builder import _try_build_tap_sac_utility_land
from mtg_bot.combat import resolve_combat_damage
from mtg_bot.effects.combinators import Sequence
from mtg_bot.effects.generic.become_type import BecomeLandCreatureUEOT
from mtg_bot.effects.generic.cube_creatures_rmc import OneOrMoreBatch
from mtg_bot.effects.generic.cube_walkers import IfCondition
from mtg_bot.effects.generic.layout_face_effects import (
    ControlOtherPermanentOfColor,
)
from mtg_bot.effects.generic.search import (
    SearchLibraryForGreenCreatureWithMVAtMostX,
)
from mtg_bot.effects.generic.spell_misc import CreateThisTurnTriggeredAbility
from mtg_bot.effects.generic.tokens import CreateToken
from mtg_bot.effects.predicates import And, Event, IsSelf
from mtg_bot.effects.vocab import ExilePlayDuration
from mtg_bot.game import StackItem, Zone, effective_colors, effective_subtypes
from mtg_bot.turn import move_off_battlefield, run_cleanup_step, sacrifice
from tests._spells_a_helpers import (
    ScriptedAgent,
    cast_and_resolve,
    cube,
    lands,
    new_game,
    put,
    to_hand,
    to_library,
)


def _conjuncts(pred) -> list:
    """The leaves of an ``And`` tree, left to right."""
    if isinstance(pred, And):
        return _conjuncts(pred.left) + _conjuncts(pred.right)
    return [pred]


# ---------------------------------------------------------------------------
# 1. Strip Mine: "{T}: Add {C}." was dropped
# ---------------------------------------------------------------------------


def test_strip_mine_taps_for_colorless():
    p = cube("Strip Mine")
    assert p.produces == frozenset({"C"})
    assert p.mana_only_from_produces
    assert len(p.activated_abilities) == 1
    aa = p.activated_abilities[0]
    assert aa.cost.tap_self and aa.cost.sacrifice_self
    assert type(aa.effect).__name__ == "DestroyTargetLand"


def test_tap_sac_utility_lands_keep_their_colorless_mana_line():
    """Every shape of the tap-and-sacrifice builder starts with
    "{T}: Add {C}." (Petrified Field, Dust Bowl, High Market, Scavenger
    Grounds outside the cube): each printing taps for {C}."""
    shapes = [
        ("Field", "", "{T}, Sacrifice this land: Return target land card "
         "from your graveyard to your hand."),
        ("Bowl", "", "{3}, {T}, Sacrifice a land: Destroy target nonbasic land."),
        ("Market", "", "{T}, Sacrifice a creature: You gain 1 life."),
        ("Grounds", "Desert", "{2}, {T}, Sacrifice a Desert: Exile all graveyards."),
    ]
    for name, sub, second in shapes:
        card = {"name": name, "type_line": f"Land — {sub}" if sub else "Land"}
        p = _try_build_tap_sac_utility_land(
            card, "{T}: Add {C}.\n" + second, (), (sub,) if sub else (),
        )
        assert p is not None, name
        assert p.produces == frozenset({"C"}), name
        assert p.mana_only_from_produces, name


def test_strip_mine_pays_for_a_spell():
    from mtg_bot.legal import legal_actions
    from mtg_bot.actions import CastSpell

    state = new_game()
    mine = put(state, "Strip Mine")
    ring = to_hand(state, "Sol Ring")
    bolt = to_hand(state, "Lightning Bolt")
    # {C} pays a generic cost, not a coloured one.
    assert CastSpell(bolt.id) not in legal_actions(state, 0)
    cast_and_resolve(state, 0, ring)
    assert ring in state.battlefield and mine.tapped


# ---------------------------------------------------------------------------
# 2. Celestial Colonnade, Creeping Tar Pit: colours and Elemental dropped
# ---------------------------------------------------------------------------


def _animate_effect(name: str) -> BecomeLandCreatureUEOT:
    return next(
        aa.effect for aa in cube(name).activated_abilities
        if isinstance(aa.effect, BecomeLandCreatureUEOT)
    )


def test_celestial_colonnade_becomes_a_white_and_blue_elemental():
    eff = _animate_effect("Celestial Colonnade")
    assert (eff.power, eff.toughness) == (4, 4)
    assert eff.set_colors == frozenset({"W", "U"})
    assert eff.granted_subtype == "Elemental"
    assert eff.granted_keywords == frozenset({"flying", "vigilance"})
    assert not eff.unblockable


def test_creeping_tar_pit_becomes_a_blue_and_black_elemental():
    eff = _animate_effect("Creeping Tar Pit")
    assert (eff.power, eff.toughness) == (3, 2)
    assert eff.set_colors == frozenset({"U", "B"})
    assert eff.granted_subtype == "Elemental"
    assert eff.unblockable


def test_animated_colonnade_is_white_blue_elemental_until_end_of_turn():
    state = new_game()
    land = put(state, "Celestial Colonnade")
    state.resolving_source = land
    try:
        _animate_effect("Celestial Colonnade").resolve(state, 0, ())
    finally:
        state.resolving_source = None
    assert effective_colors(state, land) == frozenset({"W", "U"})
    assert "Elemental" in effective_subtypes(state, land)
    run_cleanup_step(state)
    assert effective_colors(state, land) == frozenset()
    assert "Elemental" not in effective_subtypes(state, land)
