"""U/B cube creatures that work the stack or strip abilities: Thassa's
Oracle (devotion, look-and-bottom, win), Displacer Kitten (flicker),
The Wondrous Wasp and Tishana's Tidebinder (lose all abilities while
the source remains; countering abilities), Ertai Resurrected ("choose
up to one" modes whose target's controller draws)."""

from __future__ import annotations

from mtg_bot.actions import (
    CastSpell,
    StackItem,
    apply_action,
    drain_stack,
    put_into_battlefield,
    resolve_top_of_stack,
)
from mtg_bot.cards.parser.cube_creatures_ub import parse_ub_effect
from mtg_bot.cards.parser.effects import _parse_effect
from mtg_bot.effects.combinators import ModalChooseOne, Sequence
from mtg_bot.effects.generic.cube_creatures_ub import (
    ChooseNoMode,
    CounterTargetStackObject,
    DevotionTo,
    FormulaCoversLibrary,
    LookTopNKeepUpToOneOnTopRestBottom,
    ThenItsControllerDraws,
    ThenTargetLosesAbilitiesWhileSourceRemains,
)
from mtg_bot.game import Zone
from mtg_bot.turn import move_off_battlefield
from tests._spells_b_helpers import PRINTINGS, ScriptedAgent, add, add_lands, make_state


def _names(zone):
    return [c.printing.name for c in zone]


# ---------------------------------------------------------------- Thassa's Oracle


def test_oracle_parses_to_look_then_win_check():
    eff = PRINTINGS["Thassa's Oracle"].triggered_abilities[0].effect
    assert isinstance(eff, Sequence)
    assert eff.effects[0] == LookTopNKeepUpToOneOnTopRestBottom(count=DevotionTo("U"))
    assert "random order" in eff.effects[0].describe()


def test_devotion_counts_colored_hybrid_and_phyrexian_pips():
    state = make_state()
    add(state, 0, "Thassa's Oracle", Zone.BATTLEFIELD)     # {U}{U}
    add(state, 0, "Snapcaster Mage", Zone.BATTLEFIELD)     # {1}{U}
    add(state, 1, "Snapcaster Mage", Zone.BATTLEFIELD)     # opponent's
    assert DevotionTo("U").value(state, 0) == 3
    assert DevotionTo("B").value(state, 0) == 0


def test_oracle_wins_with_a_small_library():
    state = make_state()
    add(state, 0, "Island", Zone.LIBRARY)
    add(state, 0, "Swamp", Zone.LIBRARY)
    oracle = state.new_object(PRINTINGS["Thassa's Oracle"], 0, Zone.HAND)
    put_into_battlefield(state, oracle, 0)
    drain_stack(state)
    assert state.winner_id == 0


def test_oracle_keeps_one_on_top_and_does_not_win_with_a_big_library():
    agent = ScriptedAgent()
    state = make_state(agent0=agent)
    for name in ("Island", "Swamp", "Forest", "Mountain", "Plains"):
        add(state, 0, name, Zone.LIBRARY)
    wanted = state.players[0].library[1]
    agent.scripts["library"] = [wanted.id]
    oracle = state.new_object(PRINTINGS["Thassa's Oracle"], 0, Zone.HAND)
    put_into_battlefield(state, oracle, 0)
    drain_stack(state)
    assert state.winner_id is None
    assert state.players[0].library[0] is wanted
    assert len(state.players[0].library) == 5
    assert not FormulaCoversLibrary(DevotionTo("U")).matches(state, 0)


def test_look_top_n_edge_cases():
    state = make_state(agent0=ScriptedAgent(library=[None]))
    LookTopNKeepUpToOneOnTopRestBottom(count=3).resolve(state, 0, ())
    add(state, 0, "Island", Zone.LIBRARY)
    add(state, 0, "Swamp", Zone.LIBRARY)
    LookTopNKeepUpToOneOnTopRestBottom(count=2).resolve(state, 0, ())
    assert len(state.players[0].library) == 2


# ---------------------------------------------------------------- Displacer Kitten


def test_kitten_flickers_on_noncreature_cast():
    eff = PRINTINGS["Displacer Kitten"].triggered_abilities[0].effect
    assert not eff.other
    assert "up to one target" in eff.describe()
    state = make_state()
    kitten = add(state, 0, "Displacer Kitten", Zone.BATTLEFIELD)
    ring = add(state, 0, "Sol Ring", Zone.BATTLEFIELD)
    ring.tapped = True
    add_lands(state, 0, "Mountain", 1)
    bolt = add(state, 0, "Lightning Bolt", Zone.HAND)
    agent = state.players[0].agent
    agent.scripts["target"] = [("player", 1), ("permanent", ring.id)]
    apply_action(state, 0, CastSpell(bolt.id))
    drain_stack(state)
    assert ring in state.battlefield and not ring.tapped
    assert kitten in state.battlefield


# ---------------------------------------------------------------- Wasp / Tidebinder


def test_wasp_taps_and_strips_abilities_while_it_remains():
    eff = parse_ub_effect(
        "tap up to one target creature. It loses all abilities for as long "
        "as this creature remains on the battlefield"
    )
    assert isinstance(eff, ThenTargetLosesAbilitiesWhileSourceRemains)
    assert "loses all abilities" in eff.describe()
    assert parse_ub_effect(
        "draw a card. It loses all abilities for as long as this creature "
        "remains on the battlefield"
    ) is None
    state = make_state()
    frog = add(state, 1, "Psychic Frog", Zone.BATTLEFIELD)
    frog.tapped = False
    add(state, 1, "Troll of Khazad-dûm", Zone.BATTLEFIELD)
    state.players[0].agent.scripts["target"] = [("creature", frog.id)]
    wasp = state.new_object(PRINTINGS["The Wondrous Wasp"], 0, Zone.HAND)
    put_into_battlefield(state, wasp, 0)
    drain_stack(state)
    assert frog.tapped
    from mtg_bot.game import effective_activated_abilities

    assert effective_activated_abilities(state, frog) == ()
    move_off_battlefield(state, wasp, "graveyard")
    assert effective_activated_abilities(state, frog) != ()


def test_counter_stack_object_phrases():
    eff = _parse_effect("counter target spell, activated ability, or triggered ability")
    assert eff.kinds == ("spell", "activated", "triggered")
    tide = parse_ub_effect(
        "counter up to one target activated or triggered ability. If an ability "
        "of an artifact, creature, or planeswalker is countered this way, that "
        "permanent loses all abilities for as long as this creature remains on "
        "the battlefield"
    )
    assert tide.kinds == ("activated", "triggered") and tide.up_to_one
    assert tide.lose_abilities_while_source
    assert tide.target_count_range() == (0, 1)
    assert tide.describe() == (
        "counter up to one target activated ability or triggered ability"
    )


def test_tidebinder_counters_an_activated_ability_and_mutes_its_source():
    state = make_state()
    frog = add(state, 1, "Psychic Frog", Zone.BATTLEFIELD)
    ability = frog.printing.activated_abilities[0]
    state.stack.append(StackItem(source=frog, controller_id=1, ability=ability))
    tide = state.new_object(PRINTINGS["Tishana's Tidebinder"], 0, Zone.HAND)
    state.players[0].agent.scripts["target"] = [("stack", 0)]
    put_into_battlefield(state, tide, 0)
    resolve_top_of_stack(state)   # Tidebinder's trigger
    assert state.stack[0].countered
    resolve_top_of_stack(state)   # the countered ability does nothing
    assert frog.plus_one_counters == 0 and frog in state.battlefield
    from mtg_bot.game import effective_activated_abilities

    assert effective_activated_abilities(state, frog) == ()


def test_counter_skips_illegal_and_spells_can_be_countered():
    state = make_state()
    eff = CounterTargetStackObject()
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("stack", 5),))
    add_lands(state, 1, "Mountain", 1)
    bolt = add(state, 1, "Lightning Bolt", Zone.HAND)
    apply_action(state, 1, CastSpell(bolt.id))
    assert eff.legal_targets(state, 0) == [("stack", 0)]
    eff.resolve(state, 0, (("stack", 0),))
    drain_stack(state)
    assert state.players[0].life == 20
    assert _names(state.players[1].graveyard) == ["Lightning Bolt"]


# ---------------------------------------------------------------- Ertai


def test_ertai_modes_include_choosing_none():
    ertai = PRINTINGS["Ertai Resurrected"].triggered_abilities[0].effect
    assert isinstance(ertai, ModalChooseOne)
    assert isinstance(ertai.modes[0], ThenItsControllerDraws)
    assert ertai.modes[-1] == ChooseNoMode()
    assert ChooseNoMode().describe() == "choose no mode"
    ChooseNoMode().resolve(make_state(), 0, ())


def test_ertai_destroy_mode_draws_for_the_victims_controller():
    agent0 = ScriptedAgent(mode=[1])
    state = make_state(agent0=agent0)
    victim = add(state, 1, "Psychic Frog", Zone.BATTLEFIELD)
    add(state, 1, "Island", Zone.LIBRARY)
    agent0.scripts["target"] = [("creature", victim.id)]
    ertai = state.new_object(PRINTINGS["Ertai Resurrected"], 0, Zone.HAND)
    put_into_battlefield(state, ertai, 0)
    drain_stack(state)
    assert victim not in state.battlefield
    assert _names(state.players[1].hand) == ["Island"]
    assert ertai in state.battlefield


def test_then_its_controller_draws_needs_a_legal_target():
    eff = ThenItsControllerDraws(inner=CounterTargetStackObject())
    assert eff.target_count_range() == (1, 1)
    assert "its controller draws" in eff.describe()
    state = make_state()
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("stack", 0),))
    assert state.players[0].hand == [] and state.players[1].hand == []
    add_lands(state, 1, "Mountain", 1)
    add(state, 1, "Island", Zone.LIBRARY)
    bolt = add(state, 1, "Lightning Bolt", Zone.HAND)
    apply_action(state, 1, CastSpell(bolt.id))
    eff.resolve(state, 0, (("stack", 0),))
    assert _names(state.players[1].hand) == ["Island"]
