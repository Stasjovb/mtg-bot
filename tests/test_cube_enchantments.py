"""PowerLSV cube enchantment bucket: the line-composed builder
(``cards/parser/cube_enchantments.py``) and the engine behaviour of the
simpler cards (Goblin Bombardment, Squandered Resources, Sneak Attack,
Leyline Binding, Fastbond, Touch the Spirit Realm)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    PlayLand,
    apply_action,
    resolve_top_of_stack,
)
from mtg_bot.cards.base import make_artifact, make_creature, make_token_creature
from mtg_bot.cards.parser import cube_enchantments as ce
from mtg_bot.cards.parser.cube_enchantments import (
    ANY_NUMBER_OF_LAND_PLAYS,
    CUBE_ENCHANTMENT_NAMES,
    build_cube_enchantment,
)
from mtg_bot.cards.parser.enchantment_builder import (
    _build_enchantment_printing,
)
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.effects.conditions import PerBasicLandTypeAmongLandsYouControl
from mtg_bot.effects.generic.cheat_into_play import (
    PutCreatureFromHandHasteSacrificeAtNextEndStep,
)
from mtg_bot.effects.generic.enchantment_mechanics import (
    AddOneManaSacrificedLandCouldProduce,
    ExileTargetReturnAtNextEndStep,
    ExileTargetUntilSourceLeaves,
)
from mtg_bot.effects.generic.exile import ExileOpponentsNonlandPermanentUntilLeaves
from mtg_bot.effects.predicates import Event
from mtg_bot.effects.state_predicates import LandsPlayedThisTurnAtLeast
from mtg_bot.game import Zone, effective_keywords, effective_power
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step, run_delayed_end_step_triggers
from tests._cube_artifact_helpers import cube_card
from tests._spells_b_helpers import (
    ScriptedAgent,
    add,
    add_lands,
    make_state,
)

BEAR = make_creature("Test Bear", "{1}{G}", 2, 2)
OGRE = make_creature("Test Ogre", "{2}{R}", 3, 3)
RELIC = make_artifact("Test Relic", "{1}")


@pytest.fixture(scope="module")
def cube():
    return OracleParserCardSource(pool="cube").get_printings()


def _obj(state, pid, printing, zone=Zone.BATTLEFIELD):
    obj = state.new_object(printing, owner_id=pid, zone=zone)
    p = state.player_by_id(pid)
    if zone == Zone.BATTLEFIELD:
        obj.summoning_sick = False
        state.battlefield.append(obj)
    else:
        {Zone.HAND: p.hand, Zone.GRAVEYARD: p.graveyard,
         Zone.LIBRARY: p.library, Zone.EXILE: p.exile}[zone].append(obj)
    return obj


def _drain(state):
    while state.stack:
        resolve_top_of_stack(state)


# ---------------------------------------------------------------------------
# Builder / claims
# ---------------------------------------------------------------------------


def test_every_bucket_card_is_claimed(cube):
    for name in CUBE_ENCHANTMENT_NAMES:
        assert name in cube, name


def test_builder_gates():
    fastbond = cube_card("Fastbond")
    assert build_cube_enchantment(dict(fastbond, name="Not A Cube Card")) is None
    assert build_cube_enchantment(dict(fastbond, layout="saga")) is None
    assert build_cube_enchantment(
        dict(fastbond, type_line="Enchantment Creature — Spirit")
    ) is None
    assert build_cube_enchantment(
        dict(fastbond, oracle_text=fastbond["oracle_text"] + "\nFrobnicate.")
    ) is None
    # The Aura assembly path carries activated/static abilities too.
    card = dict(
        cube_card("Animate Dead"),
        oracle_text=(
            "Enchant creature card in a graveyard\n"
            "{1}: Draw a card.\nEnchanted creature gets -1/-0."
        ),
    )
    printing = build_cube_enchantment(card)
    assert printing.is_aura and len(printing.activated_abilities) == 1


def test_builder_blank_lines_and_keyword_merge(monkeypatch):
    monkeypatch.setattr(
        ce, "CUBE_ENCHANTMENT_NAMES", CUBE_ENCHANTMENT_NAMES | {"Frob"},
    )
    card = {
        "name": "Frob", "mana_cost": "{W}", "type_line": "Enchantment",
        "layout": "normal",
        "oracle_text": "Flash\n\nCreatures you control get +1/+1.",
    }
    printing = build_cube_enchantment(card)
    assert "flash" in printing.keywords
    assert printing.static_abilities


def test_shapes(cube):
    assert cube["Fastbond"].grants_additional_land_per_turn == (
        ANY_NUMBER_OF_LAND_PLAYS
    )
    (trig,) = cube["Fastbond"].triggered_abilities
    assert trig.event == Event.PLAYS_LAND
    lb = cube["Leyline Binding"]
    assert "flash" in lb.keywords
    assert lb.cost_reductions[0].condition == (
        PerBasicLandTypeAmongLandsYouControl()
    )
    assert isinstance(
        lb.triggered_abilities[0].effect,
        ExileOpponentsNonlandPermanentUntilLeaves,
    )
    (sneak,) = cube["Sneak Attack"].activated_abilities
    assert sneak.effect == PutCreatureFromHandHasteSacrificeAtNextEndStep()
    (sq,) = cube["Squandered Resources"].activated_abilities
    assert sq.cost.sacrifice_a_land and sq.is_mana_ability
    assert sq.effect == AddOneManaSacrificedLandCouldProduce()
    (gb,) = cube["Goblin Bombardment"].activated_abilities
    assert gb.cost.sacrifice_a_permanent_type == "creature"
    assert "Sacrifice a creature" in gb.cost.describe()
    touch = cube["Touch the Spirit Realm"]
    assert isinstance(
        touch.triggered_abilities[0].effect, ExileTargetUntilSourceLeaves,
    )
    (channel,) = touch.hand_activated_abilities
    assert channel.cost.discard_self
    assert isinstance(channel.effect, ExileTargetReturnAtNextEndStep)
    assert cube["Underworld Breach"].grants_graveyard_escape_exile_count == 3


def test_eoe_enchantment_paths_unchanged():
    # Legacy allowlisted EoE enchantments still claim through their own path.
    printings = OracleParserCardSource(pool="eoe").get_printings()
    assert "Banishing Light" in printings or "Seam Rip" in printings
    assert _build_enchantment_printing({"name": "X", "type_line": "Creature"}) is None


# ---------------------------------------------------------------------------
# Goblin Bombardment — "Sacrifice a creature" cost
# ---------------------------------------------------------------------------


def test_goblin_bombardment_sacrifices_a_creature_for_damage(cube):
    state = make_state()
    gb = _obj(state, 0, cube["Goblin Bombardment"])
    bear = _obj(state, 0, BEAR)
    act = ActivateAbility(gb.id, 0)
    assert act in legal_actions(state, 0)
    state.players[0].agent.scripts["target"] = [("player", 1)]
    apply_action(state, 0, act)
    assert bear in state.players[0].graveyard
    _drain(state)
    assert state.players[1].life == 19


def test_goblin_bombardment_needs_a_creature(cube):
    state = make_state()
    gb = _obj(state, 0, cube["Goblin Bombardment"])
    _obj(state, 1, BEAR)  # opponent's creature can't pay
    assert ActivateAbility(gb.id, 0) not in legal_actions(state, 0)


# ---------------------------------------------------------------------------
# Squandered Resources
# ---------------------------------------------------------------------------


def test_squandered_resources_adds_what_the_land_could_produce(cube):
    state = make_state(agent0=ScriptedAgent(color=["U"]))
    sq = _obj(state, 0, cube["Squandered Resources"])
    forest = add(state, 0, "Forest", Zone.BATTLEFIELD)
    apply_action(state, 0, ActivateAbility(sq.id, 0))
    assert forest in state.players[0].graveyard
    assert [c.color for c in state.players[0].mana_pool] == ["G"]
    # A dual: the controller picks one of its colors.
    tundra = add(state, 0, "Volcanic Island", Zone.BATTLEFIELD)
    apply_action(state, 0, ActivateAbility(sq.id, 0))
    assert tundra in state.players[0].graveyard
    assert sorted(c.color for c in state.players[0].mana_pool) == ["G", "U"]


def test_squandered_resources_colorless_and_barren_lands(cube):
    state = make_state()
    eff = AddOneManaSacrificedLandCouldProduce()
    eff.resolve(state, 0)  # nothing paid -> nothing
    assert state.players[0].mana_pool == []
    barren = add(state, 0, "Forest", Zone.GRAVEYARD)
    barren.printing = replace(barren.printing, produces=frozenset(),
                              subtypes=())
    state.resolving_cost_paid_objects = (barren,)
    eff.resolve(state, 0)
    assert state.players[0].mana_pool == []
    assert "could produce" in eff.describe()


# ---------------------------------------------------------------------------
# Sneak Attack
# ---------------------------------------------------------------------------


def test_sneak_attack_puts_hasty_creature_then_sacrifices(cube):
    state = make_state()
    sneak = _obj(state, 0, cube["Sneak Attack"])
    add_lands(state, 0, "Mountain", 1)
    ogre = _obj(state, 0, OGRE, Zone.HAND)
    apply_action(state, 0, ActivateAbility(sneak.id, 0))
    _drain(state)
    assert ogre in state.battlefield
    assert "haste" in effective_keywords(state, ogre)
    state.step = Step.END
    run_delayed_end_step_triggers(state)
    _drain(state)
    assert ogre in state.players[0].graveyard


# ---------------------------------------------------------------------------
# Leyline Binding — Domain cost reduction, flash, exile until it leaves
# ---------------------------------------------------------------------------


def test_domain_condition_counts_basic_land_types():
    state = make_state()
    cond = PerBasicLandTypeAmongLandsYouControl()
    assert not cond.matches(state, 0)
    add(state, 0, "Plains", Zone.BATTLEFIELD)
    add(state, 0, "Plains", Zone.BATTLEFIELD)
    add(state, 0, "Volcanic Island", Zone.BATTLEFIELD)
    add(state, 1, "Forest", Zone.BATTLEFIELD)
    assert cond.matches(state, 0)
    assert cond.multiplier(state, 0) == 3


def test_leyline_binding_cost_flash_and_exile(cube):
    state = make_state(step=Step.END)
    state.active_player_idx = 1
    state.priority_player_idx = 0
    target = _obj(state, 1, OGRE)
    binding = _obj(state, 0, cube["Leyline Binding"], Zone.HAND)
    # Three basic types among four lands: {5}{W} - 3 = {2}{W}.
    add(state, 0, "Plains", Zone.BATTLEFIELD)
    add(state, 0, "Volcanic Island", Zone.BATTLEFIELD)
    add(state, 0, "Plains", Zone.BATTLEFIELD)
    assert CastSpell(binding.id) in legal_actions(state, 0)
    apply_action(state, 0, CastSpell(binding.id))
    _drain(state)
    assert target in state.players[1].exile
    on_bf = next(o for o in state.battlefield if o.id == binding.id)
    from mtg_bot.turn import move_off_battlefield

    move_off_battlefield(state, on_bf, destination="graveyard")
    assert target in state.battlefield


def test_leyline_binding_unaffordable_without_domain(cube):
    state = make_state()
    binding = _obj(state, 0, cube["Leyline Binding"], Zone.HAND)
    add_lands(state, 0, "Plains", 3)
    assert CastSpell(binding.id) not in legal_actions(state, 0)


# ---------------------------------------------------------------------------
# Fastbond
# ---------------------------------------------------------------------------


def test_fastbond_extra_land_plays_and_damage(cube):
    state = make_state()
    _obj(state, 0, cube["Fastbond"])
    lands = [add(state, 0, "Forest", Zone.HAND) for _ in range(3)]
    apply_action(state, 0, PlayLand(lands[0].id))
    assert not state.stack  # first land: no trigger
    assert PlayLand(lands[1].id) in legal_actions(state, 0)
    apply_action(state, 0, PlayLand(lands[1].id))
    _drain(state)
    assert state.players[0].life == 19
    apply_action(state, 0, PlayLand(lands[2].id))
    _drain(state)
    assert state.players[0].life == 18


def test_fastbond_ignores_opponent_land_plays(cube):
    state = make_state()
    _obj(state, 1, cube["Fastbond"])
    for _ in range(2):
        land = add(state, 0, "Forest", Zone.HAND)
        state.players[0].lands_played_this_turn = 0
        apply_action(state, 0, PlayLand(land.id))
    assert not state.stack


def test_lands_played_predicate():
    state = make_state()
    pred = LandsPlayedThisTurnAtLeast(2)
    state.players[0].lands_played_this_turn = 1
    assert not pred.test(state, 0)
    state.players[0].lands_played_this_turn = 2
    assert pred.test(state, 0)


# ---------------------------------------------------------------------------
# Touch the Spirit Realm
# ---------------------------------------------------------------------------


def test_touch_the_spirit_realm_exiles_until_it_leaves(cube):
    state = make_state()
    relic = _obj(state, 1, RELIC)
    touch = _obj(state, 0, cube["Touch the Spirit Realm"], Zone.HAND)
    add_lands(state, 0, "Plains", 3)
    state.players[0].agent.scripts["target"] = [("permanent", relic.id)]
    apply_action(state, 0, CastSpell(touch.id))
    _drain(state)
    assert relic in state.players[1].exile
    assert relic.exiled_by_source == touch.id
    from mtg_bot.turn import move_off_battlefield

    move_off_battlefield(state, touch, destination="graveyard")
    assert relic in state.battlefield
    assert "until this permanent leaves" in (
        touch.printing.triggered_abilities[0].effect.describe()
    )


def test_touch_the_spirit_realm_up_to_one_and_source_gone(cube):
    state = make_state(agent0=ScriptedAgent(target=[None]))
    touch = _obj(state, 0, cube["Touch the Spirit Realm"], Zone.HAND)
    bear = _obj(state, 1, BEAR)
    add_lands(state, 0, "Plains", 3)
    apply_action(state, 0, CastSpell(touch.id))
    _drain(state)
    assert bear in state.battlefield  # chose no target
    # Source already gone at resolution: nothing is exiled.
    eff = touch.printing.triggered_abilities[0].effect
    state.resolving_source = None
    eff.resolve(state, 0, (("creature", bear.id),))
    assert bear in state.battlefield


def test_channel_flickers_until_next_end_step(cube):
    state = make_state()
    touch = _obj(state, 0, cube["Touch the Spirit Realm"], Zone.HAND)
    bear = _obj(state, 1, BEAR)
    add_lands(state, 0, "Plains", 2)
    act = ActivateAbility(touch.id, 0)
    assert act in legal_actions(state, 0)
    state.players[0].agent.scripts["target"] = [("creature", bear.id)]
    apply_action(state, 0, act)
    assert touch in state.players[0].graveyard
    _drain(state)
    assert bear in state.players[1].exile
    state.step = Step.END
    run_delayed_end_step_triggers(state)
    _drain(state)
    assert bear in state.battlefield and bear.controller_id == 1
    assert "next end step" in ExileTargetReturnAtNextEndStep().describe()


def test_channel_exiled_token_never_returns(cube):
    state = make_state()
    touch = _obj(state, 0, cube["Touch the Spirit Realm"], Zone.HAND)
    token = _obj(state, 1, make_token_creature("Spirit", 1, 1))
    assert token.printing.is_token
    add_lands(state, 0, "Plains", 2)
    state.players[0].agent.scripts["target"] = [("creature", token.id)]
    apply_action(state, 0, ActivateAbility(touch.id, 0))
    _drain(state)
    assert token not in state.battlefield
    assert state.delayed_triggers == []
