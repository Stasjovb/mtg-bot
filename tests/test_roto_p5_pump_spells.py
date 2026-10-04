"""Vintage Roto P5: pump / characteristic spells -- Scale Up (and its
Overload), Embiggen, Vines of Vastwood (can't be targeted by the
caster's opponents; kicker) and Berserk (cast timing, power doubling,
delayed destroy)."""

from __future__ import annotations

from mtg_bot.actions import CastSpell
from mtg_bot.cards.parser.roto_board import (
    claim_spell_lines,
    parse_roto_board_effect,
)
from mtg_bot.cards.parser.creature_rmc_grammar import rmc_grammar_disabled
from mtg_bot.combat import declare_attackers
from mtg_bot.effects.generic.roto_board import (
    BecomeColoredSubtypeBasePTUEOT,
    PumpPerTypeCountUEOT,
)
from mtg_bot.game import (
    Zone,
    effective_colors,
    effective_keywords,
    effective_power,
    effective_subtypes,
    effective_toughness,
)
from mtg_bot.keyword_rules import can_be_targeted_by
from mtg_bot.legal import legal_actions
from mtg_bot.roto_board_statics import CastOnlyBeforeStep
from mtg_bot.turn import Step, run_cleanup_step, run_delayed_end_step_triggers

from tests._roto_p5_helpers import (
    cast,
    lands,
    make_state,
    place,
    printing,
    resolve_all,
    script,
    vanilla,
)


def _pt(state, obj):
    return effective_power(state, obj), effective_toughness(state, obj)


def test_grammar_edges():
    assert parse_roto_board_effect(
        "until end of turn, target gizmo becomes a green Wurm with base power "
        "and toughness 6/4"
    ) is None
    assert parse_roto_board_effect(
        "until end of turn, target gizmo gets +1/+1 for each supertype, card "
        "type, and subtype it has"
    ) is None
    assert parse_roto_board_effect(
        "target gizmo can't be the target of spells or abilities your "
        "opponents control this turn"
    ) is None
    assert parse_roto_board_effect(
        "target creature gains gizmo and gets +X/+0 until end of turn, where "
        "X is its power. At the beginning of the next end step, destroy that "
        "creature if it attacked this turn"
    ) is None
    text, fields = claim_spell_lines(
        "Cast this spell only before the combat damage step.\nDraw a card."
    )
    assert text == "Draw a card."
    assert fields["board_rules"] == (CastOnlyBeforeStep(),)
    assert "combat damage step" in CastOnlyBeforeStep().describe()
    with rmc_grammar_disabled():
        assert claim_spell_lines("Cast this spell only before the end step.")[1] == {}


# ---------------------------------------------------------------------------
# Scale Up
# ---------------------------------------------------------------------------


def test_scale_up_makes_a_green_wurm_until_end_of_turn():
    state = make_state()
    lands(state, 0, "Forest", 1)
    bear = place(state, 0, vanilla(2, 2, name="Bear", cost="{U}", subtypes=("Bear",)))
    scale = place(state, 0, "Scale Up", Zone.HAND)
    cast(state, 0, scale)
    assert _pt(state, bear) == (6, 4)
    assert effective_subtypes(state, bear) == ("Wurm",)
    assert effective_colors(state, bear) == frozenset({"G"})
    run_cleanup_step(state)
    assert _pt(state, bear) == (2, 2)
    assert effective_subtypes(state, bear) == ("Bear",)


def test_scale_up_overload_hits_each_creature_you_control():
    state = make_state()
    lands(state, 0, "Forest", 6)
    a = place(state, 0, vanilla(1, 1, name="A"))
    b = place(state, 0, vanilla(3, 3, name="B"))
    theirs = place(state, 1, vanilla(2, 2, name="Theirs"))
    scale = place(state, 0, "Scale Up", Zone.HAND)
    cast(state, 0, scale, cast_for_free=True)
    assert _pt(state, a) == (6, 4) and _pt(state, b) == (6, 4)
    assert _pt(state, theirs) == (2, 2)
    eff = printing("Scale Up").spell_effect.then_effect
    assert isinstance(eff, BecomeColoredSubtypeBasePTUEOT)
    assert eff.describe().startswith("until end of turn, each")


def test_scale_up_fizzles_on_an_illegal_target():
    state = make_state()
    bear = place(state, 1, vanilla(2, 2))
    eff = printing("Scale Up").spell_effect.else_effect
    eff.resolve(state, 0, (("creature", bear.id),))   # not "you control"
    assert _pt(state, bear) == (2, 2)
    assert eff.describe().startswith("until end of turn, target")


# ---------------------------------------------------------------------------
# Embiggen
# ---------------------------------------------------------------------------


def test_embiggen_counts_supertypes_types_and_subtypes():
    state = make_state()
    lands(state, 0, "Forest", 1)
    legend = place(state, 0, vanilla(
        2, 2, name="Legend", legendary=True, artifact=True,
        subtypes=("Elf", "Druid"),
    ))
    embiggen = place(state, 0, "Embiggen", Zone.HAND)
    cast(state, 0, embiggen)
    # Legendary + Artifact Creature + Elf Druid = 5.
    assert _pt(state, legend) == (7, 7)
    assert PumpPerTypeCountUEOT.type_count(state, legend) == 5


def test_embiggen_cannot_target_a_brushwagg():
    state = make_state()
    wagg = place(state, 0, vanilla(2, 2, name="Wagg", subtypes=("Brushwagg",)))
    eff = printing("Embiggen").spell_effect
    assert ("creature", wagg.id) not in eff.legal_targets(state, 0)
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("creature", wagg.id),))
    assert _pt(state, wagg) == (2, 2)
    assert "for each supertype" in eff.describe()


# ---------------------------------------------------------------------------
# Vines of Vastwood
# ---------------------------------------------------------------------------


def test_vines_shields_from_the_casters_opponents_only():
    state = make_state()
    lands(state, 0, "Forest", 1)
    bear = place(state, 0, vanilla(2, 2))
    vines = place(state, 0, "Vines of Vastwood", Zone.HAND)
    cast(state, 0, vines)
    assert not can_be_targeted_by(state, bear, None, 1)
    assert can_be_targeted_by(state, bear, None, 0)
    assert _pt(state, bear) == (2, 2)
    run_cleanup_step(state)
    assert can_be_targeted_by(state, bear, None, 1)


def test_vines_on_an_opponents_creature_stops_its_controller():
    state = make_state()
    lands(state, 0, "Forest", 2)
    theirs = place(state, 1, vanilla(2, 2))
    vines = place(state, 0, "Vines of Vastwood", Zone.HAND)
    script(state, 0, "target", ("creature", theirs.id))
    cast(state, 0, vines, kicked=True)
    assert not can_be_targeted_by(state, theirs, None, 1)   # its controller
    assert can_be_targeted_by(state, theirs, None, 0)       # the caster
    assert _pt(state, theirs) == (6, 6)                     # kicked


def test_vines_kicked_pump_and_description():
    state = make_state()
    lands(state, 0, "Forest", 2)
    bear = place(state, 0, vanilla(2, 2))
    vines = place(state, 0, "Vines of Vastwood", Zone.HAND)
    cast(state, 0, vines, kicked=True)
    assert _pt(state, bear) == (6, 6)
    assert "if kicked" in vines.printing.spell_effect.describe()


# ---------------------------------------------------------------------------
# Berserk
# ---------------------------------------------------------------------------


def test_berserk_only_before_combat_damage():
    state = make_state()
    lands(state, 0, "Forest", 1)
    place(state, 0, vanilla(2, 2))
    berserk = place(state, 0, "Berserk", Zone.HAND)
    assert CastSpell(berserk.id) in legal_actions(state, 0)
    state.step = Step.END_OF_COMBAT
    assert CastSpell(berserk.id) not in legal_actions(state, 0)
    state.step = Step.DECLARE_BLOCKERS
    assert CastSpell(berserk.id) in legal_actions(state, 0)


def test_berserk_doubles_power_and_kills_an_attacker():
    state = make_state()
    lands(state, 0, "Forest", 1)
    bear = place(state, 0, vanilla(3, 2, name="Bear"))
    berserk = place(state, 0, "Berserk", Zone.HAND)
    cast(state, 0, berserk)
    assert _pt(state, bear) == (6, 2)
    assert "trample" in effective_keywords(state, bear)
    state.step = Step.DECLARE_ATTACKERS
    declare_attackers(state, [bear.id])
    state.step = Step.END
    run_delayed_end_step_triggers(state)
    resolve_all(state)
    assert bear in state.players[0].graveyard


def test_berserk_spares_a_creature_that_did_not_attack():
    state = make_state()
    lands(state, 0, "Forest", 1)
    bear = place(state, 0, vanilla(3, 2, name="Bear"))
    berserk = place(state, 0, "Berserk", Zone.HAND)
    cast(state, 0, berserk)
    state.step = Step.END
    run_delayed_end_step_triggers(state)
    resolve_all(state)
    assert bear in state.battlefield
    assert "didn't attack" in " ".join(state.log)
    assert "destroy it at the next end step" in berserk.printing.spell_effect.describe()
