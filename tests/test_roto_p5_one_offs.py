"""Vintage Roto P5: one-off mechanics -- Omnath, Locus of Creation
(resolution count this turn), Drop of Honey (least-power destroy and a
state trigger), Zoyowa's Justice (discover) and Monstrous Rage (Role
tokens and the Role uniqueness check)."""

from __future__ import annotations

from mtg_bot.actions import put_into_battlefield
from mtg_bot.cards.parser.roto_board import (
    parse_roto_board_effect,
    parse_roto_board_line,
)
from mtg_bot.effects.generic.roto_board import (
    ROLE_TOKENS,
    ByResolutionCountThisTurn,
    DealDamageToEachOpponentAndTheirPlaneswalkers,
    DestroyLeastPowerCreature,
    HasManaValueAtLeast,
    discover,
)
from mtg_bot.game import Zone, effective_keywords, effective_power, effective_toughness
from mtg_bot.roto_board_statics import NoCreaturesOnBattlefield, StateTrigger
from mtg_bot.turn import (
    Step,
    move_off_battlefield,
    run_beginning_of_upkeep_triggers,
    state_based_actions,
)

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


def test_grammar_edges():
    assert parse_roto_board_effect(
        "do a gizmo if this is the first time this ability has resolved this "
        "turn. If it's the second time, draw a card. If it's the third time, "
        "draw a card"
    ) is None
    assert parse_roto_board_effect(
        "the owner of target gizmo shuffles it into their library. Then that "
        "player discovers X, where X is its mana value"
    ) is None
    assert parse_roto_board_effect(
        "target creature gets +2/+0 until end of turn. Create a Gizmo Role "
        "token attached to it"
    ) is None
    assert parse_roto_board_effect(
        "target gizmo gets +2/+0 until end of turn. Create a Monster Role "
        "token attached to it"
    ) is None
    assert parse_roto_board_line(
        "When there are no creatures on the battlefield, do a gizmo.",
        {"name": "X"},
    ) is None
    regen = parse_roto_board_effect(
        "destroy the creature with the least power. If two or more creatures "
        "are tied for least power, you choose one of them"
    )
    assert regen == DestroyLeastPowerCreature(can_be_regenerated=True)
    assert "can't be regenerated" in DestroyLeastPowerCreature().describe()
    assert "first time" in printing(
        "Omnath, Locus of Creation"
    ).triggered_abilities[1].effect.describe()
    assert StateTrigger(
        condition=NoCreaturesOnBattlefield(),
        ability=printing("Drop of Honey").board_rules[0].ability,
    ).describe().startswith("When there are no creatures")


# ---------------------------------------------------------------------------
# Omnath
# ---------------------------------------------------------------------------


def _land_drop(state, pid=0):
    land = state.new_object(printing("Forest"), owner_id=pid, zone=Zone.HAND)
    put_into_battlefield(state, land, pid)
    resolve_all(state)
    return land


def test_omnath_counts_landfall_resolutions_each_turn():
    state = make_state()
    omnath = place(state, 0, "Omnath, Locus of Creation")
    walker = place(state, 1, vanilla(0, 0, name="Walker"))
    from dataclasses import replace

    walker.printing = replace(walker.printing, card_types=("Planeswalker",))
    walker.loyalty_counters = 5
    _land_drop(state)
    assert state.players[0].life == 24
    _land_drop(state)
    assert sorted(c.color for c in state.players[0].mana_pool) == ["G", "R", "U", "W"]
    _land_drop(state)
    assert state.players[1].life == 16
    assert walker.loyalty_counters == 1
    _land_drop(state)                      # fourth: nothing
    assert state.players[0].life == 24 and state.players[1].life == 16
    state.turn_number += 1
    _land_drop(state)                      # a new turn starts over
    assert state.players[0].life == 28
    assert omnath.ability_resolutions[2] == 1


def test_omnath_new_object_starts_over():
    state = make_state()
    omnath = place(state, 0, "Omnath, Locus of Creation")
    _land_drop(state)
    omnath.etb_timestamp += 100            # re-entered: a new object
    _land_drop(state)
    assert state.players[0].life == 28


def test_omnath_effect_without_source_is_noop():
    eff = printing("Omnath, Locus of Creation").triggered_abilities[1].effect
    assert isinstance(eff, ByResolutionCountThisTurn)
    state = make_state()
    eff.resolve(state, 0)
    assert DealDamageToEachOpponentAndTheirPlaneswalkers(4).describe().startswith(
        "deals 4 damage"
    )


# ---------------------------------------------------------------------------
# Drop of Honey
# ---------------------------------------------------------------------------


def _upkeep(state, pid=0):
    state.active_player_idx = pid
    state.priority_player_idx = pid
    state.step = Step.UPKEEP
    run_beginning_of_upkeep_triggers(state)
    resolve_all(state)


def test_drop_of_honey_kills_the_least_power_creature_without_regeneration():
    state = make_state()
    place(state, 0, "Drop of Honey")
    small = place(state, 1, vanilla(1, 4, name="Small"))
    big = place(state, 0, vanilla(3, 3, name="Big"))
    small.regeneration_shield = True
    _upkeep(state)
    assert small in state.players[1].graveyard
    assert big in state.battlefield


def test_drop_of_honey_tie_is_the_controllers_choice():
    state = make_state()
    place(state, 0, "Drop of Honey")
    a = place(state, 1, vanilla(2, 2, name="A"))
    b = place(state, 1, vanilla(2, 2, name="B"))
    script(state, 0, "target", ("creature", b.id))
    _upkeep(state)
    assert b in state.players[1].graveyard and a in state.battlefield


def test_drop_of_honey_sacrifices_itself_when_no_creatures_remain():
    state = make_state()
    honey = place(state, 0, "Drop of Honey")
    last = place(state, 1, vanilla(1, 1, name="Last"))
    _upkeep(state)
    assert last in state.players[1].graveyard
    # The state trigger fired as the last creature died.
    assert honey in state.players[0].graveyard


def test_drop_of_honey_state_trigger_not_retriggered_while_pending():
    state = make_state()
    honey = place(state, 0, "Drop of Honey")
    state_based_actions(state)
    assert len(state.stack) == 1
    state_based_actions(state)
    assert len(state.stack) == 1           # still on the stack: no retrigger
    resolve_all(state)
    assert honey in state.players[0].graveyard


def test_drop_of_honey_with_no_creatures_destroys_nothing():
    state = make_state()
    DestroyLeastPowerCreature().resolve(state, 0)
    assert not state.players[0].graveyard


# ---------------------------------------------------------------------------
# Zoyowa's Justice / discover
# ---------------------------------------------------------------------------


def test_zoyowas_justice_owner_shuffles_and_discovers():
    state = make_state()
    lands(state, 0, "Mountain", 2)
    big = place(state, 1, vanilla(3, 3, name="Big", cost="{2}{G}"))
    place(state, 1, "Forest", Zone.LIBRARY)
    justice = place(state, 0, "Zoyowa's Justice", Zone.HAND)
    script(state, 1, "yes_no", False)       # the owner discovers: keeps it
    script(state, 0, "target", ("creature", big.id))
    cast(state, 0, justice)
    assert big not in state.battlefield
    opp = state.players[1]
    # Discover 3: the first nonland card with mana value 3 or less is
    # Big itself (shuffled in); declined, so it goes to hand.
    assert big in opp.hand
    assert all(c.printing.is_land for c in opp.library)


def test_discover_casts_the_hit_for_free_and_bottoms_the_rest():
    state = make_state()
    for name in ("Forest", "Island"):
        place(state, 0, name, Zone.LIBRARY)
    bolt = place(state, 0, "Lightning Bolt", Zone.LIBRARY)
    place(state, 0, "Mountain", Zone.LIBRARY)
    script(state, 0, "target", ("player", 1))
    discover(state, 0, 1)
    resolve_all(state)
    assert state.players[1].life == 17
    assert bolt in state.players[0].graveyard
    assert [c.printing.name for c in state.players[0].library][0] == "Mountain"
    assert len(state.players[0].library) == 3


def test_discover_finds_nothing():
    state = make_state()
    place(state, 0, "Forest", Zone.LIBRARY)
    discover(state, 0, 0)
    assert len(state.players[0].library) == 1


def test_zoyowa_needs_mana_value_one_or_more():
    state = make_state()
    token = place(state, 1, vanilla(1, 1, name="Zero", cost=""))
    eff = printing("Zoyowa's Justice").spell_effect
    assert ("creature", token.id) not in eff.legal_targets(state, 0)
    assert not HasManaValueAtLeast(1).test(state.players[0], state)
    eff.resolve(state, 0, (("creature", token.id),))
    assert token in state.battlefield
    eff.resolve(state, 0, ())
    assert "discovers X" in eff.describe()


# ---------------------------------------------------------------------------
# Monstrous Rage / Roles
# ---------------------------------------------------------------------------


def test_monstrous_rage_pumps_and_attaches_a_monster_role():
    state = make_state()
    lands(state, 0, "Mountain", 1)
    bear = place(state, 0, vanilla(2, 2))
    rage = place(state, 0, "Monstrous Rage", Zone.HAND)
    cast(state, 0, rage)
    role = next(o for o in state.battlefield if o.printing.name == "Monster Role")
    assert role.attached_to == bear.id
    assert (effective_power(state, bear), effective_toughness(state, bear)) == (5, 3)
    assert "trample" in effective_keywords(state, bear)
    move_off_battlefield(state, bear)
    assert role not in state.battlefield


def test_role_uniqueness_keeps_the_newest():
    state = make_state()
    lands(state, 0, "Mountain", 2)
    bear = place(state, 0, vanilla(2, 2))
    for _ in range(2):
        rage = place(state, 0, "Monstrous Rage", Zone.HAND)
        cast(state, 0, rage)
    roles = [o for o in state.battlefield if o.printing.name == "Monster Role"]
    assert len(roles) == 1
    assert ROLE_TOKENS["Monster"].is_token
    assert "Role token" in printing("Monstrous Rage").spell_effect.describe()


def test_monstrous_rage_fizzles_without_a_legal_target():
    state = make_state()
    eff = printing("Monstrous Rage").spell_effect
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("creature", 404),))
    assert not state.battlefield
