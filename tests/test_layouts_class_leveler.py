"""Cube layouts bucket: Class enchantments (CR 716, Does Machines) and
levelers (CR 711, Hexdrinker)."""

from __future__ import annotations

from mtg_bot.actions import ActivateAbility, CastSpell, apply_action, drain_stack
from mtg_bot.cards.parser.class_builder import _build_class_printing
from mtg_bot.cards.parser.leveler_builder import _build_leveler_printing
from mtg_bot.effects.generic.layout_effects import (
    GainClassLevel,
    LevelCountersInRange,
    LevelerPT,
    ThenTargetBecomesCreatureIfNot,
)
from mtg_bot.game import (
    Zone,
    add_counters,
    effective_keywords,
    effective_power,
    effective_subtypes,
    effective_toughness,
    is_creature_now,
)
from mtg_bot.keyword_rules import protection_qualities
from mtg_bot.layouts import gain_class_level
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step, move_off_battlefield, run_beginning_of_combat_triggers
from tests._spells_b_helpers import ScriptedAgent, add, add_lands, make_state, printing

MACHINES = "Does Machines"
HEX = "Hexdrinker"


# ---------------------------------------------------------------------------
# Class
# ---------------------------------------------------------------------------


def test_class_shape():
    p = printing(MACHINES)
    assert p.class_level == 1 and len(p.class_levels) == 2
    (level_up,) = p.activated_abilities
    assert level_up.effect == GainClassLevel(level=2) and level_up.sorcery_speed
    assert level_up.cost.mana_str == "{1}{U}"
    two, three = p.class_levels
    assert two.class_level == 2 and three.class_level == 3
    assert [a.effect for a in two.activated_abilities] == [GainClassLevel(level=3)]
    assert three.activated_abilities == ()
    assert [t.trigger for t in two.triggered_abilities] == ["", "class_level_2"]
    assert isinstance(three.triggered_abilities[-1].effect, ThenTargetBecomesCreatureIfNot)


def test_class_builder_rejects():
    base = {"name": "C", "mana_cost": "{U}", "type_line": "Enchantment — Class"}
    assert _build_class_printing(dict(base, type_line="Enchantment")) is None
    assert _build_class_printing(dict(base, oracle_text="Draw a card.")) is None
    assert _build_class_printing(
        dict(base, oracle_text="{U}: Level 3\nWhen this Class enters, draw a card.")
    ) is None
    assert _build_class_printing(
        dict(base, oracle_text="{U}: Level 2\nFrobnicate.")
    ) is None
    assert _build_class_printing(
        dict(base, oracle_text="{U}: Level 2\nWhen this Class becomes level 2, frobnicate.")
    ) is None


def test_does_machines_levels_up():
    agent = ScriptedAgent()
    state = make_state(agent0=agent)
    machines = add(state, 0, MACHINES, Zone.HAND)
    for _ in range(4):
        add(state, 0, "Island", Zone.LIBRARY)
    add_lands(state, 0, "Island", 2)
    apply_action(state, 0, CastSpell(machines.id))
    drain_stack(state)
    # ETB: mill two, draw two, discard two.
    assert len(state.players[0].graveyard) == 4
    assert machines.printing.class_level == 1
    ring = add(state, 0, "Sol Ring", Zone.GRAVEYARD)
    pearl = add(state, 0, "Mox Pearl", Zone.GRAVEYARD)
    add_lands(state, 0, "Island", 2)
    assert ActivateAbility(source_id=machines.id, ability_index=0) in legal_actions(state, 0)
    agent.scripts["target"] = [("graveyard_artifact", ring.id), ("graveyard_artifact", pearl.id)]
    apply_action(state, 0, ActivateAbility(source_id=machines.id, ability_index=0))
    drain_stack(state)
    assert machines.printing.class_level == 2
    assert ring in state.players[0].hand and pearl in state.players[0].hand
    # Level 3.
    add_lands(state, 0, "Island", 5)
    apply_action(state, 0, ActivateAbility(source_id=machines.id, ability_index=0))
    drain_stack(state)
    assert machines.printing.class_level == 3
    # Level 3 combat trigger: a noncreature artifact becomes a 0/0 Robot
    # with three +1/+1 counters, permanently.
    ring_bf = add(state, 0, "Sol Ring", Zone.BATTLEFIELD)
    state.step = Step.BEGINNING_OF_COMBAT
    agent.scripts["target"] = [("permanent", ring_bf.id)]
    run_beginning_of_combat_triggers(state)
    drain_stack(state)
    assert is_creature_now(ring_bf) and "Robot" in effective_subtypes(state, ring_bf)
    assert effective_power(state, ring_bf) == 3 and effective_toughness(state, ring_bf) == 3
    # The animation is the artifact's own: it outlives the Class.
    move_off_battlefield(state, machines, destination="graveyard")
    assert machines.printing.class_level == 1
    assert is_creature_now(ring_bf)


def test_level_up_needs_the_previous_level():
    state = make_state()
    machines = add(state, 0, MACHINES, Zone.BATTLEFIELD)
    state.resolving_source = machines
    assert GainClassLevel(level=3).resolve(state, 0) is False
    state.resolving_source = None
    assert GainClassLevel(level=2).resolve(state, 0) is False
    assert not gain_class_level(state, machines, 1)
    assert not gain_class_level(state, machines, 4)
    assert "level 2" in GainClassLevel().describe()


def test_level_three_trigger_on_creature_artifact_only_counters():
    state = make_state()
    machines = add(state, 0, MACHINES, Zone.BATTLEFIELD)
    gain_class_level(state, machines, 2)
    gain_class_level(state, machines, 3)
    eff = machines.printing.triggered_abilities[-1].effect
    assert eff.requires_target() and eff.target_count_range() == (1, 1)
    assert "Robot" in eff.describe()
    assert eff.target_slot_kinds() == ()
    state.resolving_source = machines
    assert eff.legal_targets(state, 0) == []
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("permanent", 999),))


# ---------------------------------------------------------------------------
# Leveler
# ---------------------------------------------------------------------------


def test_leveler_shape():
    p = printing(HEX)
    assert (p.power, p.toughness) == (2, 1)
    (level_up,) = p.activated_abilities
    assert level_up.sorcery_speed and level_up.cost.mana_str == "{1}"
    assert p.dynamic_pt_formula == LevelerPT(ranges=((3, 7, 4, 4), (8, None, 6, 6)))
    conds = [s.condition for s in p.static_abilities]
    assert conds == [LevelCountersInRange(3, 7), LevelCountersInRange(8, None)]


def test_leveler_builder_rejects():
    base = {"name": "L", "mana_cost": "{G}", "type_line": "Creature — Snake",
            "power": "1", "toughness": "1", "layout": "leveler"}
    assert _build_leveler_printing(dict(base, layout="normal")) is None
    assert _build_leveler_printing(dict(base, oracle_text="LEVEL 1+\n2/2")) is None
    assert _build_leveler_printing(dict(base, oracle_text="Level up {1}")) is None
    assert _build_leveler_printing(dict(base, oracle_text="Level up {1}\nLEVEL 1+")) is None
    assert _build_leveler_printing(
        dict(base, oracle_text="Level up {1}\nLEVEL 1+\nbig")
    ) is None
    assert _build_leveler_printing(
        dict(base, oracle_text="Level up {1}\nLEVEL 1+\n2/2\nFrobnicate.")
    ) is None
    assert _build_leveler_printing(
        dict(base, oracle_text="Level up {1}\nFrobnicate.\nLEVEL 1+\n2/2")
    ) is None


def test_hexdrinker_levels():
    state = make_state()
    hexd = add(state, 0, HEX, Zone.BATTLEFIELD)
    add_lands(state, 0, "Forest", 3)
    assert (effective_power(state, hexd), effective_toughness(state, hexd)) == (2, 1)
    for _ in range(3):
        apply_action(state, 0, ActivateAbility(source_id=hexd.id, ability_index=0))
        drain_stack(state)
    assert (effective_power(state, hexd), effective_toughness(state, hexd)) == (4, 4)
    assert "instants" in protection_qualities(state, hexd)
    assert "everything" not in protection_qualities(state, hexd)
    # An instant can't target it; a creature's ability still can.
    from mtg_bot.keyword_rules import filter_targetable

    bolt = add(state, 1, "Lightning Bolt", Zone.HAND)
    assert filter_targetable(state, [("creature", hexd.id)], bolt, 1) == []
    ogre = add(state, 1, "Witch Enchanter // Witch-Blessed Meadow", Zone.BATTLEFIELD)
    assert filter_targetable(state, [("creature", hexd.id)], ogre, 1) == [
        ("creature", hexd.id)
    ]
    add_counters(state, hexd, "level", 5)
    assert (effective_power(state, hexd), effective_toughness(state, hexd)) == (6, 6)
    assert "protection from everything" in effective_keywords(state, hexd)
    assert "protection from instants" not in effective_keywords(state, hexd)


def test_level_counter_range_condition_is_source_only():
    assert LevelCountersInRange(1, 2).matches(None, 0) is False
