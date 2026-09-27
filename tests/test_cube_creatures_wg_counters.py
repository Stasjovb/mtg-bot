"""Cube W/G creatures: keyword counters (Arwen, Leatherhead), counter
doubling (Bristly Bill, Scythecat Cub), reflexive "When you do"
triggers (Leatherhead, Guide of Souls)."""

from __future__ import annotations

from mtg_bot.actions import ActivateAbility, apply_action, put_into_battlefield
from mtg_bot.cards.parser.creature_wg_effects import parse_counter_list, parse_wg_effect
from mtg_bot.cards.parser.creature_wg_lines import parse_wg_creature_line
from mtg_bot.effects.generic.cube_creatures_wg import (
    DoublePlusOneCountersOnEach,
    GrantKeywordsUEOTAndPutCounters,
    PayEnergy,
    PutCounterDoublingOnSecondResolution,
    PutCountersOnTargetAndAddSubtype,
    ReflexiveWhenYouDo,
    RemoveACounterFromSelf,
)
from mtg_bot.game import (
    Zone,
    effective_keywords,
    effective_subtypes,
    named_counter_count,
)
from mtg_bot.turn import run_cleanup_step
from tests._wg_helpers import (
    add_lands,
    attack,
    bear,
    cast_and_resolve,
    cube,
    drain,
    make_state,
    put,
)


def _activate(state, pid, obj, idx=0):
    apply_action(state, pid, ActivateAbility(source_id=obj.id, ability_index=idx))
    drain(state)


def test_counter_list_grammar():
    assert parse_counter_list("a +1/+1 counter and a lifelink counter") == (
        ("+1/+1", 1), ("lifelink", 1),
    )
    assert parse_counter_list("two +1/+1 counters and a flying counter") == (
        ("+1/+1", 2), ("flying", 1),
    )
    assert parse_counter_list("3 +1/+1 counters") == (("+1/+1", 3),)
    assert parse_counter_list("a wombat counter") is None
    assert parse_counter_list("some counters") is None


def test_arwen_enters_indestructible_and_shares_counters():
    pr = cube()["Arwen, Mortal Queen"]
    assert pr.enters_with_named_counters == (("indestructible", 1),)
    state = make_state()
    arwen = put(state, 0, pr, Zone.HAND)
    add_lands(state, 0, "Forest", 2)
    add_lands(state, 0, "Plains", 2)
    cast_and_resolve(state, 0, arwen)
    assert "indestructible" in effective_keywords(state, arwen)
    ally = put(state, 0, bear("Ally"))
    state.players[0].agent.scripts["target"] = [("creature", ally.id)]
    _activate(state, 0, arwen)
    assert named_counter_count(arwen, "indestructible") == 0
    assert "indestructible" not in effective_keywords(state, arwen)
    kws = effective_keywords(state, ally)
    assert {"indestructible", "lifelink"} <= kws
    assert ally.plus_one_counters == 1 and arwen.plus_one_counters == 1
    assert "lifelink" in effective_keywords(state, arwen)
    run_cleanup_step(state)
    assert "indestructible" not in effective_keywords(state, ally)
    assert "lifelink" in effective_keywords(state, ally)
    eff = pr.activated_abilities[0].effect
    assert isinstance(eff, GrantKeywordsUEOTAndPutCounters)
    state.resolving_source = arwen
    assert ("creature", arwen.id) not in eff.legal_targets(state, 0)
    state.resolving_source = None
    eff.resolve(state, 0, ())  # no target, no source: nothing
    assert "counters" in eff.describe()


def test_enters_with_counters_line_rejects_unknown_kinds():
    card = {"name": "Z"}
    assert parse_wg_creature_line(
        "Z enters with a wombat counter on it.", card,
    ) is None


def test_bristly_bill_doubles_counters():
    pr = cube()["Bristly Bill, Spine Sower"]
    state = make_state()
    bill = put(state, 0, pr)
    a = put(state, 0, bear("A"))
    a.plus_one_counters = 2
    b = put(state, 0, bear("B"))
    theirs = put(state, 1, bear("Theirs"))
    theirs.plus_one_counters = 3
    add_lands(state, 0, "Forest", 5)
    idx = next(
        i for i, ab in enumerate(pr.activated_abilities)
        if isinstance(ab.effect, DoublePlusOneCountersOnEach)
    )
    _activate(state, 0, bill, idx)
    assert a.plus_one_counters == 4 and b.plus_one_counters == 0
    assert theirs.plus_one_counters == 3
    assert "double" in DoublePlusOneCountersOnEach().describe()


def test_bristly_bill_landfall_counter():
    state = make_state()
    put(state, 0, "Bristly Bill, Spine Sower")
    a = put(state, 0, bear("A"))
    state.players[0].agent.scripts["target"] = [("creature", a.id)]
    land = put(state, 0, "Forest", Zone.HAND)
    state.players[0].hand.remove(land)
    put_into_battlefield(state, land, 0)
    drain(state)
    assert a.plus_one_counters == 1


def test_scythecat_second_resolution_doubles():
    pr = cube()["Scythecat Cub"]
    assert "trample" in pr.keywords
    eff = pr.triggered_abilities[0].effect
    assert isinstance(eff, PutCounterDoublingOnSecondResolution)
    state = make_state()
    cub = put(state, 0, pr)
    agent = state.players[0].agent
    for _ in range(3):
        agent.scripts.setdefault("target", []).append(("creature", cub.id))
        land = put(state, 0, "Forest", Zone.HAND)
        state.players[0].hand.remove(land)
        put_into_battlefield(state, land, 0)
        drain(state)
    # 1st: +1 -> 1; 2nd: double -> 2; 3rd: +1 -> 3.
    assert cub.plus_one_counters == 3
    state.turn_number += 1
    agent.scripts["target"] = [("creature", cub.id)]
    land = put(state, 0, "Forest", Zone.HAND)
    state.players[0].hand.remove(land)
    put_into_battlefield(state, land, 0)
    drain(state)
    assert cub.plus_one_counters == 4  # new turn: first resolution again
    assert "second resolution" in eff.describe()
    eff.resolve(state, 0, ())  # no target


def test_leatherhead_hexproof_counter_and_reflexive_destroy():
    pr = cube()["Leatherhead, Swamp Stalker"]
    state = make_state()
    lh = put(state, 0, pr, Zone.HAND)
    add_lands(state, 0, "Forest", 4)
    cast_and_resolve(state, 0, lh)
    assert "hexproof" in effective_keywords(state, lh)
    lh.summoning_sick = False
    rock = put(state, 1, "Sol Ring")
    mine = put(state, 0, "Mana Vault")
    state.players[0].agent.scripts["target"] = [("permanent", rock.id)]
    attack(state, 0, [lh.id])
    from mtg_bot.combat import resolve_combat_damage

    resolve_combat_damage(state, defending_player_id=1)
    drain(state)
    assert rock in state.players[1].graveyard
    assert mine in state.battlefield
    assert "hexproof" not in effective_keywords(state, lh)


def test_reflexive_edges():
    state = make_state()
    lh = put(state, 0, "Leatherhead, Swamp Stalker")
    state.resolving_source = lh
    assert RemoveACounterFromSelf().resolve(state, 0) is False  # no counters
    lh.plus_one_counters = 1
    from mtg_bot.game import set_named_counters

    set_named_counters(lh, "hexproof", 1)
    state.players[0].agent.scripts["mode"] = [1]
    assert RemoveACounterFromSelf().resolve(state, 0) is True
    assert lh.plus_one_counters + named_counter_count(lh, "hexproof") == 1
    state.resolving_source = None
    assert RemoveACounterFromSelf().resolve(state, 0) is False
    assert "remove" in RemoveACounterFromSelf().describe()
    eff = next(
        t.effect for t in lh.printing.triggered_abilities
        if isinstance(t.effect, ReflexiveWhenYouDo)
    )
    assert eff.event_player_controls
    # Cost can't be paid -> nothing.
    state.resolving_source = lh
    lh.plus_one_counters = 0
    set_named_counters(lh, "hexproof", 0)
    assert eff.resolve(state, 0, (("player", 1),)) is False
    # Paid but no legal target.
    lh.plus_one_counters = 1
    assert eff.resolve(state, 0, (("player", 1),)) is True
    state.resolving_source = None
    assert "when you do" in eff.describe()
    assert PayEnergy(2).resolve(state, 0) is False
    assert "energy" in PayEnergy(2).describe()


def test_guide_of_souls_energy_and_angel():
    pr = cube()["Guide of Souls"]
    state = make_state()
    guide = put(state, 0, pr)
    p = state.players[0]
    for name in ("A", "B", "C"):
        c = put(state, 0, bear(name), Zone.HAND)
        p.hand.remove(c)
        put_into_battlefield(state, c, 0)
        drain(state)
    assert p.life == 23 and p.energy == 3
    attacker = next(o for o in state.battlefield if o.printing.name == "A")
    attacker.summoning_sick = False
    p.agent.scripts["target"] = [("creature", attacker.id)]
    attack(state, 0, [attacker.id])
    assert p.energy == 0
    assert attacker.plus_one_counters == 2 and attacker.flying_counters == 1
    assert "flying" in effective_keywords(state, attacker)
    assert "Angel" in effective_subtypes(state, attacker)
    # Guide leaving doesn't undo the type change.
    from mtg_bot.turn import sacrifice

    sacrifice(state, guide)
    assert "Angel" in effective_subtypes(state, attacker)
    eff = PutCountersOnTargetAndAddSubtype(subtype="Angel")
    eff.resolve(state, 0, ())
    assert "Angel" in eff.describe()
    assert parse_wg_effect(
        "put a wombat counter on target creature. It becomes an Angel in "
        "addition to its other types"
    ) is None
