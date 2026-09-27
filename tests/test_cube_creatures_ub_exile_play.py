"""U/B cube creatures that let a player play exiled cards: the exile
play-permission substrate (``GameObject.may_play_by``), Ninjutsu and
Fallen Shinobi, Urza, Lord High Artificer, and Barrowgoyf's dynamic P/T
and mill-then-take trigger."""

from __future__ import annotations

from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    DeclareBlockers,
    PlayLand,
    apply_action,
    drain_stack,
    put_into_battlefield,
)
from mtg_bot.cards.parser.cube_creatures_ub import parse_ub_creature_line, parse_ub_effect
from mtg_bot.combat import declare_attackers, resolve_combat_damage
from mtg_bot.effects.generic.cube_creatures_ub import (
    MayMillDamageThenMayTakeCreature,
    PutSourceOntoBattlefieldTappedAndAttacking,
    ShuffleThenExileTopMayPlayFree,
    TargetPlayerExilesTopNYouMayPlayThem,
)
from mtg_bot.game import Zone, effective_power, effective_toughness
from mtg_bot.legal import legal_actions, permission_cost
from mtg_bot.turn import Step, run_cleanup_step
from tests._spells_b_helpers import PRINTINGS, ScriptedAgent, add, add_lands, make_state


def _names(zone):
    return [c.printing.name for c in zone]


# ---------------------------------------------------------------- permissions


def test_permission_lets_the_grantee_play_an_opponents_exiled_cards():
    state = make_state()
    TargetPlayerExilesTopNYouMayPlayThem(amount=2, free=True).resolve(
        state, 0, (("player", 1),),
    )
    assert state.players[1].exile == []
    add(state, 1, "Lightning Bolt", Zone.LIBRARY)
    add(state, 1, "Mountain", Zone.LIBRARY)
    TargetPlayerExilesTopNYouMayPlayThem(amount=2, free=True).resolve(
        state, 0, (("player", 1),),
    )
    bolt, mountain = state.players[1].exile
    assert bolt.may_play_by == 0 and mountain.may_play_free
    acts = legal_actions(state, 0)
    assert CastSpell(bolt.id, cast_for_free=True) in acts
    assert PlayLand(mountain.id) in acts
    assert not any(
        isinstance(a, CastSpell) and a.card_id == bolt.id
        for a in legal_actions(state, 1)
    )
    apply_action(state, 0, PlayLand(mountain.id))
    assert mountain in state.battlefield and mountain.controller_id == 0
    state.players[0].agent.scripts["target"] = [("player", 1)]
    apply_action(state, 0, CastSpell(bolt.id, cast_for_free=True))
    drain_stack(state)
    assert state.players[1].life == 17
    assert _names(state.players[1].graveyard) == ["Lightning Bolt"]


def test_permission_timing_cost_and_cleanup():
    state = make_state(step=Step.DECLARE_ATTACKERS)
    TargetPlayerExilesTopNYouMayPlayThem(amount=1).resolve(state, 0, ())
    add(state, 1, "Dark Confidant", Zone.LIBRARY)
    add(state, 1, "Island", Zone.LIBRARY)
    TargetPlayerExilesTopNYouMayPlayThem(amount=2).resolve(
        state, 0, (("player", 1),),
    )
    bob, island = state.players[1].exile
    # Not sorcery timing: neither the creature nor the land.
    assert not any(
        getattr(a, "card_id", None) in (bob.id, island.id)
        for a in legal_actions(state, 0)
    )
    state.step = Step.PRECOMBAT_MAIN
    assert CastSpell(bob.id) not in legal_actions(state, 0)   # no mana
    add_lands(state, 0, "Swamp", 2)
    assert CastSpell(bob.id) in legal_actions(state, 0)
    bob.may_play_any_mana = True
    assert permission_cost(bob).colored == ()
    state.step = Step.CLEANUP
    run_cleanup_step(state)
    assert bob.may_play_by is None and island.may_play_by is None
    assert "play them" in TargetPlayerExilesTopNYouMayPlayThem(amount=2).describe()


# ---------------------------------------------------------------- Ninjutsu


def test_ninjutsu_line_and_effect_shape():
    out = parse_ub_creature_line("Ninjutsu {2}{U}{B}", "X")
    ability = out.hand_abilities[0]
    assert ability.cost.return_unblocked_attacker
    assert "unblocked attacker" in ability.cost.describe()
    assert ability.effect == PutSourceOntoBattlefieldTappedAndAttacking()
    assert "tapped and attacking" in ability.effect.describe()
    assert parse_ub_creature_line("Ninjutsu {Q}", "X") is None


def test_fallen_shinobi_ninjas_in_and_steals_cards():
    agent0 = ScriptedAgent()
    state = make_state(agent0=agent0, step=Step.DECLARE_ATTACKERS)
    bob = add(state, 0, "Dark Confidant", Zone.BATTLEFIELD)
    add_lands(state, 0, "Island", 2)
    add_lands(state, 0, "Swamp", 2)
    shinobi = add(state, 0, "Fallen Shinobi", Zone.HAND)
    add(state, 1, "Lightning Bolt", Zone.LIBRARY)
    add(state, 1, "Mountain", Zone.LIBRARY)
    act = ActivateAbility(source_id=shinobi.id, ability_index=0)
    assert act not in legal_actions(state, 0)   # no unblocked attacker yet
    declare_attackers(state, [bob.id])
    state.step = Step.DECLARE_BLOCKERS
    apply_action(state, 1, DeclareBlockers(assignments=()))
    state.priority_player_idx = 0
    assert act in legal_actions(state, 0)
    apply_action(state, 0, act)
    drain_stack(state)
    assert bob in state.players[0].hand
    assert shinobi in state.battlefield and shinobi.attacking and shinobi.tapped
    state.step = Step.COMBAT_DAMAGE
    resolve_combat_damage(state, 1)
    drain_stack(state)
    assert state.players[1].life == 15
    exiled = state.players[1].exile
    assert {c.printing.name for c in exiled} == {"Lightning Bolt", "Mountain"}
    assert all(c.may_play_by == 0 and c.may_play_free for c in exiled)


def test_ninja_effect_needs_the_card_in_hand():
    state = make_state()
    state.resolving_source = None
    PutSourceOntoBattlefieldTappedAndAttacking().resolve(state, 0, ())
    card = add(state, 0, "Fallen Shinobi", Zone.GRAVEYARD)
    state.resolving_source = card
    PutSourceOntoBattlefieldTappedAndAttacking().resolve(state, 0, ())
    assert card not in state.battlefield


# ---------------------------------------------------------------- Urza


def test_urza_construct_grows_with_artifacts():
    state = make_state()
    urza = state.new_object(PRINTINGS["Urza, Lord High Artificer"], 0, Zone.HAND)
    put_into_battlefield(state, urza, 0)
    drain_stack(state)
    construct = next(o for o in state.battlefield if o.printing.name == "Construct")
    assert effective_power(state, construct) == 1
    add(state, 0, "Sol Ring", Zone.BATTLEFIELD)
    assert effective_toughness(state, construct) == 2


def test_urza_taps_artifacts_for_blue_and_impulses_for_free():
    state = make_state()
    urza = add(state, 0, "Urza, Lord High Artificer", Zone.BATTLEFIELD)
    mana_ability = urza.printing.activated_abilities[0]
    assert mana_ability.cost.describe() == "Tap an untapped artifact you control"
    tap_act = ActivateAbility(source_id=urza.id, ability_index=0)
    add_lands(state, 0, "Island", 1)
    assert tap_act not in legal_actions(state, 0)   # a land isn't an artifact
    ring = add(state, 0, "Sol Ring", Zone.BATTLEFIELD)
    assert tap_act in legal_actions(state, 0)
    apply_action(state, 0, tap_act)
    assert ring.tapped
    assert [c.color for c in state.players[0].mana_pool] == ["U"]
    add(state, 0, "Mountain", Zone.LIBRARY)
    ShuffleThenExileTopMayPlayFree().resolve(state, 0, ())
    (land,) = state.players[0].exile
    assert land.may_play_by == 0 and land.may_play_free
    assert "shuffle" in ShuffleThenExileTopMayPlayFree().describe()
    ShuffleThenExileTopMayPlayFree().resolve(state, 0, ())   # empty library


# ---------------------------------------------------------------- Barrowgoyf


def test_barrowgoyf_counts_card_types_in_all_graveyards():
    state = make_state()
    goyf = add(state, 0, "Barrowgoyf", Zone.BATTLEFIELD)
    assert (effective_power(state, goyf), effective_toughness(state, goyf)) == (0, 1)
    add(state, 0, "Lightning Bolt", Zone.GRAVEYARD)
    add(state, 1, "Island", Zone.GRAVEYARD)
    add(state, 1, "Kappa Cannoneer", Zone.GRAVEYARD)   # artifact creature
    assert (effective_power(state, goyf), effective_toughness(state, goyf)) == (4, 5)


def test_barrowgoyf_mills_the_damage_and_takes_a_creature():
    assert parse_ub_effect(
        "you may mill that many cards. If you do, you may put a creature "
        "card from among them into your hand"
    ) == MayMillDamageThenMayTakeCreature()
    state = make_state()
    for name in ("Island", "Dark Confidant", "Swamp"):
        add(state, 0, name, Zone.LIBRARY)
    state.resolving_combat_damage_amount = 3
    MayMillDamageThenMayTakeCreature().resolve(state, 0, ())
    assert _names(state.players[0].hand) == ["Dark Confidant"]
    assert _names(state.players[0].graveyard) == ["Island", "Swamp"]
    assert "mill that many" in MayMillDamageThenMayTakeCreature().describe()


def test_barrowgoyf_may_decline_and_needs_damage():
    state = make_state(agent0=ScriptedAgent(yes_no=[False]))
    add(state, 0, "Island", Zone.LIBRARY)
    state.resolving_combat_damage_amount = 0
    MayMillDamageThenMayTakeCreature().resolve(state, 0, ())
    state.resolving_combat_damage_amount = 2
    MayMillDamageThenMayTakeCreature().resolve(state, 0, ())
    assert len(state.players[0].library) == 1
    # Milled nothing creature-y: no pick.
    MayMillDamageThenMayTakeCreature().resolve(state, 0, ())
    assert state.players[0].hand == []
