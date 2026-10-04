"""Cube layouts bucket: Etali, Primal Conqueror // Etali, Primal Sickness
(exile-until free casts, a Phyrexian activation cost, poison from combat
damage) and Aang, Swift Savior // Aang and La, Ocean's Fury (airbend,
waterbend)."""

from __future__ import annotations

from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    StackItem,
    apply_action,
    drain_stack,
)
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.effects.generic.layout_face_effects import (
    Airbend,
    EachPlayerExilesUntilNonlandMayCastFree,
)
from mtg_bot.game import Zone
from mtg_bot.layouts import is_transformed, pay_waterbend, transform_permanent
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step, run_cleanup_step
from tests._spells_b_helpers import ScriptedAgent, add, add_lands, make_state, printing

ETALI = "Etali, Primal Conqueror // Etali, Primal Sickness"
AANG = "Aang, Swift Savior // Aang and La, Ocean's Fury"


def _creature(state, pid, name="Stalwart Knight"):
    obj = state.new_object(SYNTHETIC_CREATURES[name], pid, Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.battlefield.append(obj)
    return obj


# ---------------------------------------------------------------------------
# Etali
# ---------------------------------------------------------------------------


def test_etali_shape():
    p = printing(ETALI)
    (ab,) = p.activated_abilities
    assert ab.sorcery_speed and ab.cost.mana.phyrexian == ("G",)
    assert isinstance(p.triggered_abilities[0].effect, EachPlayerExilesUntilNonlandMayCastFree)
    back = p.transform_back_face
    assert back.face_colors == frozenset({"G", "R"}) and back.mana_cost.total == 7


def test_etali_etb_exiles_until_nonland_and_casts_free():
    agent = ScriptedAgent(yes_no=[True, False])
    state = make_state(agent0=agent)
    add(state, 0, "Island", Zone.LIBRARY)
    ring = add(state, 0, "Sol Ring", Zone.LIBRARY)
    add(state, 1, "Swamp", Zone.LIBRARY)
    opp_bolt = add(state, 1, "Lightning Bolt", Zone.LIBRARY)
    etali = add(state, 0, ETALI, Zone.BATTLEFIELD)
    state.resolving_source = etali
    agent.scripts["target"] = [("player", 1)]
    EachPlayerExilesUntilNonlandMayCastFree().resolve(state, 0)
    state.resolving_source = None
    # Sol Ring cast (yes), the opponent's Bolt declined (no).
    assert any(item.source is ring for item in state.stack)
    assert opp_bolt in state.players[1].exile
    assert len(state.players[0].exile) == 1  # the Island
    drain_stack(state)
    assert ring in state.battlefield and ring.controller_id == 0
    assert "for free" in EachPlayerExilesUntilNonlandMayCastFree().describe()


def test_etali_etb_with_empty_library():
    state = make_state()
    EachPlayerExilesUntilNonlandMayCastFree().resolve(state, 0)
    assert "exiles 0 card(s)" in "\n".join(state.log)


def test_etali_transform_pays_phyrexian_with_life():
    agent = ScriptedAgent(yes_no=[True])
    state = make_state(agent0=agent)
    etali = add(state, 0, ETALI, Zone.BATTLEFIELD)
    add_lands(state, 0, "Mountain", 9)
    acts = legal_actions(state, 0)
    assert ActivateAbility(source_id=etali.id, ability_index=0) in acts
    apply_action(state, 0, ActivateAbility(source_id=etali.id, ability_index=0))
    drain_stack(state)
    assert is_transformed(etali) and state.players[0].life == 18


def test_primal_sickness_poison():
    from mtg_bot.combat import resolve_combat_damage

    state = make_state()
    etali = add(state, 0, ETALI, Zone.BATTLEFIELD)
    etali.mdfc_front_printing = etali.printing
    etali.printing = etali.printing.transform_back_face
    etali.attacking = True
    state.step = Step.COMBAT_DAMAGE
    resolve_combat_damage(state, 1)
    drain_stack(state)
    assert state.players[1].poison_counters == 11 and state.players[1].life == 9


# ---------------------------------------------------------------------------
# Aang
# ---------------------------------------------------------------------------


def test_aang_airbends_creature_owner_recasts_for_two():
    agent = ScriptedAgent()
    state = make_state(agent0=agent)
    ogre = add(state, 1, "Witch Enchanter // Witch-Blessed Meadow", Zone.BATTLEFIELD)
    aang = add(state, 0, AANG, Zone.HAND)
    add_lands(state, 0, "Plains", 1)
    add_lands(state, 0, "Island", 2)
    agent.scripts["target"] = [("creature", ogre.id)]
    apply_action(state, 0, CastSpell(aang.id))
    drain_stack(state)
    assert ogre in state.players[1].exile
    perm = ogre.exile_play_permission
    assert perm.player_id == 1 and perm.alt_cost == "{2}"
    run_cleanup_step(state)
    assert ogre.exile_play_permission is not None  # while exiled
    add_lands(state, 1, "Swamp", 2)
    state.active_player_idx = 1
    state.priority_player_idx = 1
    assert CastSpell(ogre.id) in legal_actions(state, 1)
    apply_action(state, 1, CastSpell(ogre.id))
    drain_stack(state)
    assert ogre in state.battlefield and ogre.controller_id == 1


def test_airbend_a_spell_and_edge_cases():
    state = make_state()
    aang = add(state, 0, AANG, Zone.BATTLEFIELD)
    bolt = add(state, 1, "Lightning Bolt", Zone.STACK)
    state.stack.append(StackItem(source=bolt, controller_id=1))
    eff = Airbend()
    state.resolving_source = aang
    legal = eff.legal_targets(state, 0)
    assert ("stack", 0) in legal and ("creature", aang.id) not in legal
    assert eff.target_count_range() == (0, 1) and eff.requires_target()
    eff.resolve(state, 0, (("stack", 0),))
    assert bolt in state.players[1].exile and not state.stack
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("stack", 5),))
    eff.resolve(state, 0, (("creature", 999),))
    tok_ogre = _creature(state, 1)  # synthetic, not a token: exiled
    eff.resolve(state, 0, (("creature", tok_ogre.id),))
    assert tok_ogre in state.players[1].exile
    assert "airbend" in eff.describe()


def test_waterbend_taps_helpers_to_transform():
    agent = ScriptedAgent(x=[8])
    state = make_state(agent0=agent)
    aang = add(state, 0, AANG, Zone.BATTLEFIELD)
    helpers = [_creature(state, 0) for _ in range(5)] + [
        add(state, 0, "Sol Ring", Zone.BATTLEFIELD) for _ in range(2)
    ]
    add_lands(state, 0, "Island", 1)
    act = ActivateAbility(source_id=aang.id, ability_index=0)
    assert act in legal_actions(state, 0)
    apply_action(state, 0, act)
    drain_stack(state)
    assert aang.printing.name == "Aang and La, Ocean's Fury"
    assert all(h.tapped for h in helpers) and aang.tapped


def test_waterbend_not_affordable_without_help():
    state = make_state()
    aang = add(state, 0, AANG, Zone.BATTLEFIELD)
    add_lands(state, 0, "Island", 3)
    assert ActivateAbility(source_id=aang.id, ability_index=0) not in legal_actions(state, 0)


def test_pay_waterbend_prefers_minimum_when_agent_declines():
    from mtg_bot.cards.base import ManaCost

    agent = ScriptedAgent(x=[0])
    state = make_state(agent0=agent)
    aang = add(state, 0, AANG, Zone.BATTLEFIELD)
    add_lands(state, 0, "Island", 7)
    rest = pay_waterbend(state, 0, aang, ManaCost(generic=8), frozenset({"spell"}))
    assert rest.generic == 7 and aang.tapped


def test_aang_and_la_counters_on_tapped_creatures():
    from mtg_bot.actions import DeclareAttackers

    state = make_state()
    aang = add(state, 0, AANG, Zone.BATTLEFIELD)
    transform_permanent(state, aang)
    tapped = _creature(state, 0)
    tapped.tapped = True
    untapped = _creature(state, 0)
    state.step = Step.DECLARE_ATTACKERS
    apply_action(state, 0, DeclareAttackers(attacker_ids=frozenset({aang.id})))
    drain_stack(state)
    assert aang.plus_one_counters == 1 and tapped.plus_one_counters == 1
    assert untapped.plus_one_counters == 0
