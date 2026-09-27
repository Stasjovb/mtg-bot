"""Engine behaviour of the cube enchantment primitives
(``effects/generic/enchantment_mechanics.py``): Parallax Wave (fading,
linked exile), Underworld Breach (granted escape), Oath of Druids,
Animate Dead and Necromancy (reanimation Auras, cleanup-step delayed
sacrifice)."""

from __future__ import annotations

import pytest

from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    apply_action,
    resolve_top_of_stack,
)
from mtg_bot.alt_casting import escape_payable, escape_terms
from mtg_bot.cards.base import make_creature, make_instant, make_sorcery
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.effects.generic import DrawCards
from mtg_bot.effects.generic.enchantment_mechanics import (
    EachPlayerReturnsCardsExiledWithSource,
    ExileLinkedToSource,
    LinkedCreatureControllerSacrifices,
    OathRevealUntilCreature,
    ReanimateAndAttachSource,
    RemoveNamedCounterFromSelfOrSacrifice,
    enchanted_graveyard_card,
    permanent_has_type,
    run_delayed_cleanup_triggers,
    sacrifice_type_candidates,
)
from mtg_bot.game import Zone, effective_power, named_counter_count
from mtg_bot.legal import legal_actions
from mtg_bot.turn import (
    Step,
    move_off_battlefield,
    run_beginning_of_end_step_triggers,
    run_beginning_of_upkeep_triggers,
    run_cleanup_step,
    state_based_actions,
)
from tests._spells_b_helpers import ScriptedAgent, add, add_lands, make_state

BEAR = make_creature("Test Bear", "{1}{G}", 2, 2)
WURM = make_creature("Test Wurm", "{6}{G}", 6, 6)
DRAW = make_sorcery("Test Divination", "{2}{U}", DrawCards(amount=2))
FREE = make_instant("Test Freebie", "", DrawCards(amount=1))


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


def _cast_in(state, pid, printing):
    """Put ``printing`` onto the battlefield through the real resolve
    path (so enters triggers fire)."""
    from mtg_bot.actions import put_into_battlefield

    obj = state.new_object(printing, owner_id=pid, zone=Zone.HAND)
    put_into_battlefield(state, obj, pid)
    return obj


def _drain(state):
    while state.stack:
        resolve_top_of_stack(state)
        state_based_actions(state)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def test_sacrifice_type_helpers():
    state = make_state()
    bear = _obj(state, 0, BEAR)
    land = add(state, 0, "Forest", Zone.BATTLEFIELD)
    assert permanent_has_type(bear, "creature")
    assert not permanent_has_type(land, "artifact")
    assert sacrifice_type_candidates(state, 0, "creature") == [bear]
    assert sacrifice_type_candidates(state, 1, "creature") == []


# ---------------------------------------------------------------------------
# Parallax Wave
# ---------------------------------------------------------------------------


def test_parallax_wave_fading_and_linked_exile(cube):
    state = make_state()
    wave = _cast_in(state, 0, cube["Parallax Wave"])
    assert named_counter_count(wave, "fade") == 5
    bear = _obj(state, 1, BEAR)
    act = ActivateAbility(wave.id, 0)
    state.players[0].agent.scripts["target"] = [("creature", bear.id)]
    apply_action(state, 0, act)
    _drain(state)
    assert bear in state.players[1].exile
    assert bear.imprinted_on == (wave.id, wave.etb_timestamp)
    assert named_counter_count(wave, "fade") == 4
    # Leaving the battlefield does NOT auto-return (a trigger does).
    move_off_battlefield(state, wave, destination="graveyard")
    assert bear in state.players[1].exile and state.stack
    _drain(state)
    assert bear in state.battlefield and bear.controller_id == 1
    assert bear.imprinted_on is None


def test_parallax_wave_upkeep_counter_then_sacrifice(cube):
    state = make_state(step=Step.UPKEEP)
    wave = _cast_in(state, 0, cube["Parallax Wave"])
    run_beginning_of_upkeep_triggers(state)
    _drain(state)
    assert named_counter_count(wave, "fade") == 4
    from mtg_bot.game import set_named_counters

    set_named_counters(wave, "fade", 0)
    assert ActivateAbility(wave.id, 0) not in legal_actions(state, 0)
    run_beginning_of_upkeep_triggers(state)
    _drain(state)
    assert wave in state.players[0].graveyard


def test_fading_effect_noop_when_source_gone():
    state = make_state()
    eff = RemoveNamedCounterFromSelfOrSacrifice(kind="fade")
    eff.resolve(state, 0)
    assert "fade" in eff.describe()


def test_linked_exile_edge_cases(cube):
    state = make_state()
    wave = _cast_in(state, 0, cube["Parallax Wave"])
    from mtg_bot.cards.base import make_token_creature

    token = _obj(state, 1, make_token_creature("Spirit", 1, 1))
    eff = wave.printing.activated_abilities[0].effect
    assert isinstance(eff, ExileLinkedToSource)
    state.resolving_source = wave
    eff.resolve(state, 0, (("creature", token.id),))
    assert token not in state.battlefield and token.imprinted_on is None
    ret = EachPlayerReturnsCardsExiledWithSource()
    state.resolving_source = None
    ret.resolve(state, 0)  # no source -> no-op
    assert "exiled with" in ret.describe()


# ---------------------------------------------------------------------------
# Underworld Breach
# ---------------------------------------------------------------------------


def test_underworld_breach_grants_escape(cube):
    state = make_state()
    _obj(state, 0, cube["Underworld Breach"])
    draw = _obj(state, 0, DRAW, Zone.GRAVEYARD)
    fodder = [add(state, 0, "Forest", Zone.GRAVEYARD) for _ in range(3)]
    for _ in range(3):
        add(state, 0, "Island", Zone.LIBRARY)
    add_lands(state, 0, "Island", 3)
    assert escape_terms(state, 0, draw)[1] == 3
    assert escape_terms(state, 0, fodder[0]) is None  # lands can't escape
    act = CastSpell(draw.id, use_escape=True)
    assert act in legal_actions(state, 0)
    apply_action(state, 0, act)
    assert all(c in state.players[0].exile for c in fodder)
    _drain(state)
    assert len(state.players[0].hand) == 2
    assert draw in state.players[0].graveyard  # escape doesn't exile a sorcery


def test_breach_escape_limits(cube):
    state = make_state()
    draw = _obj(state, 0, DRAW, Zone.GRAVEYARD)
    free = _obj(state, 0, FREE, Zone.GRAVEYARD)
    for _ in range(3):
        add(state, 0, "Forest", Zone.GRAVEYARD)
    assert escape_terms(state, 0, draw) is None  # no Breach
    _obj(state, 1, cube["Underworld Breach"])
    assert escape_terms(state, 0, draw) is None  # opponent's Breach
    _obj(state, 0, cube["Underworld Breach"])
    assert escape_terms(state, 0, free) is None  # no mana cost
    assert escape_terms(state, 1, draw) is None  # not in P1's graveyard
    # Only two other cards: can't pay the exile part.
    state.players[0].graveyard[:] = [draw, state.players[0].graveyard[2]]
    assert not escape_payable(state, 0, draw)


def test_breach_sacrificed_at_every_end_step(cube):
    state = make_state(step=Step.END)
    state.active_player_idx = 1
    breach = _obj(state, 0, cube["Underworld Breach"])
    run_beginning_of_end_step_triggers(state)
    _drain(state)
    assert breach in state.players[0].graveyard


# ---------------------------------------------------------------------------
# Oath of Druids
# ---------------------------------------------------------------------------


def _oath_state(cube, *, opp_creatures=1, my_creatures=0, agent0=None):
    state = make_state(agent0=agent0, step=Step.UPKEEP)
    _obj(state, 1, cube["Oath of Druids"])  # opponent's Oath still triggers for P0
    for _ in range(opp_creatures):
        _obj(state, 1, BEAR)
    for _ in range(my_creatures):
        _obj(state, 0, BEAR)
    return state


def test_oath_reveals_until_creature(cube):
    state = _oath_state(cube)
    lib = state.players[0].library
    top = [add(state, 0, "Island", Zone.LIBRARY) for _ in range(2)]
    wurm = _obj(state, 0, WURM, Zone.LIBRARY)
    under = add(state, 0, "Island", Zone.LIBRARY)
    run_beginning_of_upkeep_triggers(state)
    assert state.stack and state.stack[-1].targets == (("player", 1),)
    _drain(state)
    assert wurm in state.battlefield and wurm.controller_id == 0
    assert all(c in state.players[0].graveyard for c in top)
    assert lib == [under]


def test_oath_no_trigger_without_fewer_creatures(cube):
    state = _oath_state(cube, opp_creatures=1, my_creatures=1)
    run_beginning_of_upkeep_triggers(state)
    assert not state.stack


def test_oath_decline_and_no_creature(cube):
    state = _oath_state(cube, agent0=ScriptedAgent(yes_no=[False]))
    card = add(state, 0, "Island", Zone.LIBRARY)
    run_beginning_of_upkeep_triggers(state)
    _drain(state)
    assert state.players[0].library == [card]
    state = _oath_state(cube)
    cards = [add(state, 0, "Island", Zone.LIBRARY) for _ in range(3)]
    run_beginning_of_upkeep_triggers(state)
    _drain(state)
    assert state.players[0].library == cards  # nothing moves


def test_oath_fizzles_when_target_no_longer_has_more(cube):
    state = _oath_state(cube)
    wurm = _obj(state, 0, WURM, Zone.LIBRARY)
    run_beginning_of_upkeep_triggers(state)
    _obj(state, 0, BEAR)  # now equal creature counts
    _drain(state)
    assert wurm in state.players[0].library
    eff = OathRevealUntilCreature()
    assert eff.requires_target() and "creature" in eff.describe()


# ---------------------------------------------------------------------------
# Animate Dead
# ---------------------------------------------------------------------------


def test_animate_dead_reanimates_and_links(cube):
    state = make_state()
    wurm = _obj(state, 1, WURM, Zone.GRAVEYARD)
    ad = _obj(state, 0, cube["Animate Dead"], Zone.HAND)
    add_lands(state, 0, "Swamp", 2)
    act = CastSpell(ad.id)
    assert act in legal_actions(state, 0)
    state.players[0].agent.scripts["target"] = [("graveyard_creature", wurm.id)]
    apply_action(state, 0, act)
    resolve_top_of_stack(state)  # the Aura enters enchanting the card
    assert ad in state.battlefield and ad.attached_to == wurm.id
    state_based_actions(state)
    assert ad in state.battlefield  # legal while enchanting a graveyard card
    _drain(state)
    assert wurm in state.battlefield and wurm.controller_id == 0
    assert ad.attached_to == wurm.id and ad.aura_enchant_override == "creature"
    assert effective_power(state, wurm) == 5
    # The Aura leaves -> that creature's controller sacrifices it.
    move_off_battlefield(state, ad, destination="graveyard")
    assert ad.aura_enchant_override is None
    _drain(state)
    assert wurm in state.players[1].graveyard


def test_animate_dead_buried_with_its_creature(cube):
    state = make_state()
    wurm = _obj(state, 0, WURM, Zone.GRAVEYARD)
    ad = _obj(state, 0, cube["Animate Dead"], Zone.HAND)
    add_lands(state, 0, "Swamp", 2)
    state.players[0].agent.scripts["target"] = [("graveyard_creature", wurm.id)]
    apply_action(state, 0, CastSpell(ad.id))
    _drain(state)
    move_off_battlefield(state, wurm, destination="graveyard")
    assert ad in state.players[0].graveyard
    _drain(state)  # leaves trigger finds its creature gone
    assert wurm in state.players[0].graveyard


def test_animate_dead_target_gone_before_resolution(cube):
    state = make_state()
    wurm = _obj(state, 0, WURM, Zone.GRAVEYARD)
    ad = _obj(state, 0, cube["Animate Dead"], Zone.HAND)
    add_lands(state, 0, "Swamp", 2)
    state.players[0].agent.scripts["target"] = [("graveyard_creature", wurm.id)]
    apply_action(state, 0, CastSpell(ad.id))
    state.players[0].graveyard.remove(wurm)
    state.players[0].exile.append(wurm)
    resolve_top_of_stack(state)
    assert ad in state.players[0].graveyard  # fizzled


def test_animate_dead_card_leaves_before_trigger(cube):
    state = make_state()
    wurm = _obj(state, 0, WURM, Zone.GRAVEYARD)
    ad = _obj(state, 0, cube["Animate Dead"], Zone.HAND)
    add_lands(state, 0, "Swamp", 2)
    state.players[0].agent.scripts["target"] = [("graveyard_creature", wurm.id)]
    apply_action(state, 0, CastSpell(ad.id))
    resolve_top_of_stack(state)
    state.players[0].graveyard.remove(wurm)
    state.players[0].exile.append(wurm)
    assert enchanted_graveyard_card(state, ad) is None
    state_based_actions(state)
    assert ad in state.players[0].graveyard
    _drain(state)
    assert wurm in state.players[0].exile


def test_reanimate_effect_edges(cube):
    state = make_state()
    ad = _obj(state, 0, cube["Animate Dead"])
    eff = ReanimateAndAttachSource()
    state.resolving_source = ad
    ad.attached_to = None
    eff.resolve(state, 0)  # nothing enchanted
    assert ad.attached_to is None
    assert eff.legal_targets(state, 0) == []
    nec = ReanimateAndAttachSource(from_target=True)
    nec.resolve(state, 0, ())  # no target
    assert "target creature card" in nec.describe()
    assert "enchanted creature card" in eff.describe()
    sac = LinkedCreatureControllerSacrifices()
    state.resolving_source = None
    sac.resolve(state, 0)
    assert "sacrifices" in sac.describe()


# ---------------------------------------------------------------------------
# Necromancy
# ---------------------------------------------------------------------------


def test_necromancy_at_sorcery_speed_stays(cube):
    state = make_state()
    wurm = _obj(state, 1, WURM, Zone.GRAVEYARD)
    nec = _obj(state, 0, cube["Necromancy"], Zone.HAND)
    add_lands(state, 0, "Swamp", 3)
    state.players[0].agent.scripts["target"] = [("graveyard_creature", wurm.id)]
    apply_action(state, 0, CastSpell(nec.id))
    _drain(state)
    assert wurm in state.battlefield and wurm.controller_id == 0
    assert nec.attached_to == wurm.id and nec.aura_enchant_override == "creature"
    state_based_actions(state)
    assert nec in state.battlefield  # it is an Aura enchanting the creature
    run_cleanup_step(state)
    assert nec in state.battlefield and wurm in state.battlefield
    # Its creature leaves -> the (now) Aura is put into the graveyard.
    move_off_battlefield(state, wurm, destination="exile")
    assert nec in state.players[0].graveyard


def test_necromancy_at_instant_speed_sacrificed_at_cleanup(cube):
    state = make_state(step=Step.END)
    state.active_player_idx = 1
    state.priority_player_idx = 0
    wurm = _obj(state, 0, WURM, Zone.GRAVEYARD)
    nec = _obj(state, 0, cube["Necromancy"], Zone.HAND)
    add_lands(state, 0, "Swamp", 3)
    act = CastSpell(nec.id)
    assert act in legal_actions(state, 0)
    state.players[0].agent.scripts["target"] = [("graveyard_creature", wurm.id)]
    apply_action(state, 0, act)
    _drain(state)
    assert wurm in state.battlefield
    state.step = Step.CLEANUP
    run_cleanup_step(state)
    assert nec in state.players[0].graveyard
    assert wurm in state.players[0].graveyard
    assert state.delayed_triggers == [] and not state.stack


def test_cleanup_runner_skips_missing_sources():
    state = make_state()
    from mtg_bot.effects.generic.delayed_actions import SacrificeSourceDelayed

    state.delayed_triggers.append({
        "fire_at_turn": state.turn_number, "controller_id": 0,
        "source_id": 999, "effect": SacrificeSourceDelayed(),
        "step": "cleanup",
    })
    state.delayed_triggers.append({
        "fire_at_turn": state.turn_number + 5, "controller_id": 0,
        "source_id": 998, "effect": SacrificeSourceDelayed(),
        "step": "cleanup",
    })
    run_delayed_cleanup_triggers(state)
    assert len(state.delayed_triggers) == 1
    run_delayed_cleanup_triggers(make_state())  # nothing due


def test_flicker_return_edges_and_fizzle():
    from mtg_bot.effects.generic.enchantment_mechanics import (
        ExileTargetReturnAtNextEndStep,
        ReturnResolvingSourceFromExileUnderOwner,
    )
    from mtg_bot.effects.object_predicates import IsArtifact
    from mtg_bot.effects.targets import TargetSpec

    state = make_state()
    ret = ReturnResolvingSourceFromExileUnderOwner()
    ret.resolve(state, 0)  # no source
    bear = _obj(state, 1, BEAR, Zone.GRAVEYARD)
    state.resolving_source = bear
    ret.resolve(state, 0)  # not in exile any more -> stays put
    assert bear in state.players[1].graveyard
    assert "owner" in ret.describe()
    # A target that became illegal fizzles.
    live = _obj(state, 1, BEAR)
    eff = ExileTargetReturnAtNextEndStep(targets=(TargetSpec(filter=IsArtifact()),))
    eff.resolve(state, 0, (("creature", live.id),))
    assert live in state.battlefield and state.delayed_triggers == []


def test_reanimate_target_not_a_creature_card(cube):
    state = make_state()
    nec = _obj(state, 0, cube["Necromancy"])
    land = add(state, 1, "Forest", Zone.GRAVEYARD)
    state.resolving_source = nec
    ReanimateAndAttachSource(from_target=True).resolve(
        state, 0, (("graveyard_creature", land.id),),
    )
    assert land in state.players[1].graveyard and nec.attached_to is None
