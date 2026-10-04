"""Cube creatures (R / multicolor / colorless) bucket: Dash, Boast,
"when you cast this spell" triggers + Cascade, Escape's "escaped",
"can't block this turn", the impulse-exile family."""

from __future__ import annotations

from mtg_bot.actions import CastSpell, apply_action
from mtg_bot.cards.parser.creature_rmc_grammar import (
    parse_rmc_effect,
    parse_rmc_trigger_phrase,
)
from mtg_bot.combat import declare_attackers, eligible_blockers, resolve_combat_damage
from mtg_bot.effects.generic.cube_creatures_rmc import (
    CreaturesCantBlockThisTurn,
    ExileTopCardsWithPlayPermission,
    IsThisSpell,
    TargetCreatureCantBlockThisTurn,
    creature_cant_block,
)
from mtg_bot.effects.predicates import Event
from mtg_bot.game import Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import (
    Step,
    run_cleanup_step,
    run_delayed_end_step_triggers,
)
from tests._rmc_helpers import (
    activate,
    add,
    add_lands,
    can_activate,
    cast,
    make_state,
    printing,
    resolve_all,
)


# ---------------------------------------------------------------------------
# Dash — Ragavan, Nimble Pilferer
# ---------------------------------------------------------------------------


def test_ragavan_dash_haste_and_return_to_hand():
    rag = printing("Ragavan, Nimble Pilferer")
    assert rag.dash_cost_str == "{1}{R}"
    state = make_state()
    add_lands(state, 0, "Mountain", 2)
    card = add(state, 0, "Ragavan, Nimble Pilferer", Zone.HAND)
    actions = legal_actions(state, 0)
    assert CastSpell(card.id) in actions and CastSpell(card.id, use_dash=True) in actions
    cast(state, 0, card, use_dash=True)
    assert card in state.battlefield and card.dashed
    from mtg_bot.combat import eligible_attackers
    from mtg_bot.game import effective_keywords

    assert "haste" in effective_keywords(state, card)
    assert card in eligible_attackers(state, 0)
    assert "(dash)" in state.log[-3] or any("(dash)" in line for line in state.log)
    # End step: the delayed trigger returns it to hand.
    state.step = Step.END
    run_delayed_end_step_triggers(state)
    resolve_all(state)
    assert card in state.players[0].hand and not card.dashed


def test_normal_cast_is_not_dashed_and_blink_cancels_return():
    state = make_state()
    add_lands(state, 0, "Mountain", 3)
    card = add(state, 0, "Ragavan, Nimble Pilferer", Zone.HAND)
    cast(state, 0, card)
    assert not card.dashed and not state.delayed_triggers
    # Dash, then leave and come back: the delayed trigger does nothing.
    state = make_state()
    add_lands(state, 0, "Mountain", 3)
    card2 = add(state, 0, "Ragavan, Nimble Pilferer", Zone.HAND)
    cast(state, 0, card2, use_dash=True)
    from mtg_bot.actions import put_into_battlefield
    from mtg_bot.turn import move_off_battlefield

    move_off_battlefield(state, card2, destination="exile")
    state.players[0].exile.remove(card2)
    put_into_battlefield(state, card2, 0)
    resolve_all(state)
    state.step = Step.END
    run_delayed_end_step_triggers(state)
    resolve_all(state)
    assert card2 in state.battlefield


def test_ragavan_combat_damage_treasure_and_cast_opponents_card():
    state = make_state(step=Step.COMBAT_DAMAGE)
    rag = add(state, 0, "Ragavan, Nimble Pilferer")
    bolt = add(state, 1, "Lightning Bolt", Zone.LIBRARY)
    declare_attackers(state, [rag.id])
    resolve_all(state)
    resolve_combat_damage(state, 1)
    resolve_all(state)
    assert state.players[1].life == 18
    assert any(o.printing.name == "Treasure" for o in state.battlefield)
    assert bolt in state.players[1].exile
    perm = bolt.exile_play_permission
    assert perm.player_id == 0 and perm.cast_only
    # Cast it with the Treasure (instant: offered now).
    state.players[0].agent.scripts["target"] = [("player", 1)]
    assert CastSpell(bolt.id) in legal_actions(state, 0)
    apply_action(state, 0, CastSpell(bolt.id))
    resolve_all(state)
    assert state.players[1].life == 15
    assert bolt in state.players[1].graveyard  # owner's graveyard
    assert bolt.exile_play_permission is None


# ---------------------------------------------------------------------------
# Boast — Broadside Bombardiers
# ---------------------------------------------------------------------------


def test_broadside_bombardiers_boast():
    bomb_printing = printing("Broadside Bombardiers")
    ability = bomb_printing.activated_abilities[0]
    assert ability.boast and ability.describe().startswith("Boast — ")
    state = make_state()
    bomb = add(state, 0, "Broadside Bombardiers")
    fodder = add(state, 0, "Orcish Lumberjack")
    golos = add(state, 0, "Golos, Tireless Pilgrim")  # MV 5
    # Hasn't attacked: can't boast.
    assert not can_activate(state, 0, bomb)
    state.step = Step.DECLARE_ATTACKERS
    declare_attackers(state, [bomb.id])
    resolve_all(state)
    # Activated abilities are offered at sorcery timing in this engine
    # (SEARCH_LIMITATIONS): boast after combat.
    state.step = Step.POSTCOMBAT_MAIN
    assert can_activate(state, 0, bomb)
    state.players[0].agent.scripts["sacrifice"] = [golos.id]
    state.players[0].agent.scripts["target"] = [("player", 1)]
    activate(state, 0, bomb)
    assert golos in state.players[0].graveyard
    assert state.players[1].life == 13  # 2 + MV 5
    # Once each turn.
    assert not can_activate(state, 0, bomb)
    assert fodder in state.battlefield


# ---------------------------------------------------------------------------
# Cast triggers + Cascade — Bloodbraid Challenger
# ---------------------------------------------------------------------------


def test_this_spell_trigger_phrase_and_predicate():
    assert parse_rmc_trigger_phrase("you cast this spell") == (Event.IS_CAST, IsThisSpell())
    assert parse_rmc_trigger_phrase("something else") is None
    state = make_state()
    card = add(state, 0, "Bloodbraid Challenger", Zone.HAND)
    other = add(state, 0, "Ragavan, Nimble Pilferer")
    assert IsThisSpell().matches(state, {"spell": card}, card)
    assert not IsThisSpell().matches(state, {"spell": card}, other)


def test_bloodbraid_challenger_cascades_into_a_free_spell():
    state = make_state()
    add_lands(state, 0, "Mountain", 3)
    add_lands(state, 0, "Forest", 2)
    lib = state.players[0].library
    island = add(state, 0, "Island", Zone.LIBRARY)
    golos = add(state, 0, "Golos, Tireless Pilgrim", Zone.LIBRARY)  # MV 5: not < 5
    ballista = add(state, 0, "Walking Ballista", Zone.LIBRARY)  # MV 0 hit
    tail = add(state, 0, "Swamp", Zone.LIBRARY)
    card = add(state, 0, "Bloodbraid Challenger", Zone.HAND)
    apply_action(state, 0, CastSpell(card.id))
    # The cascade trigger is above the spell.
    assert len(state.stack) == 2 and state.stack[-1].ability is not None
    resolve_all(state)
    # Ballista was cast for free (X=0 -> dies), the rest went to the bottom.
    assert ballista in state.players[0].graveyard
    assert card in state.battlefield
    assert lib[0] is tail and {c.id for c in lib[1:]} == {island.id, golos.id}
    assert not state.players[0].exile


def test_cascade_declined_puts_everything_on_the_bottom():
    state = make_state()
    state.players[0].agent.scripts["yes_no"] = [False]
    add_lands(state, 0, "Mountain", 3)
    add_lands(state, 0, "Forest", 2)
    bolt = add(state, 0, "Lightning Bolt", Zone.LIBRARY)
    card = add(state, 0, "Bloodbraid Challenger", Zone.HAND)
    cast(state, 0, card)
    assert state.players[0].library == [bolt] and not state.players[0].exile


def test_bloodbraid_challenger_escapes_from_graveyard():
    state = make_state()
    add_lands(state, 0, "Mountain", 3)
    add_lands(state, 0, "Forest", 2)
    card = add(state, 0, "Bloodbraid Challenger", Zone.GRAVEYARD)
    for _ in range(3):
        add(state, 0, "Island", Zone.GRAVEYARD)
    assert CastSpell(card.id, use_escape=True) in legal_actions(state, 0)
    cast(state, 0, card, use_escape=True)
    assert card in state.battlefield and card.escaped
    assert len(state.players[0].exile) == 3


# ---------------------------------------------------------------------------
# Escape "escaped" — Uro / Phlage
# ---------------------------------------------------------------------------


def test_phlage_sacrificed_unless_escaped():
    state = make_state()
    add_lands(state, 0, "Mountain", 2)
    add_lands(state, 0, "Plains", 1)
    phlage = add(state, 0, "Phlage, Titan of Fire's Fury", Zone.HAND)
    state.players[0].agent.scripts["target"] = [("player", 1)]
    cast(state, 0, phlage)
    assert phlage in state.players[0].graveyard  # hard-cast: sacrificed
    assert state.players[1].life == 17 and state.players[0].life == 23
    # Escape it: stays.
    for land in state.battlefield:
        land.tapped = False
    add_lands(state, 0, "Mountain", 1)
    add_lands(state, 0, "Plains", 1)
    for _ in range(5):
        add(state, 0, "Island", Zone.GRAVEYARD)
    state.players[0].agent.scripts["target"] = [("player", 1)]
    cast(state, 0, phlage, use_escape=True)
    assert phlage in state.battlefield and phlage.escaped
    assert state.players[1].life == 14
    from mtg_bot.turn import move_off_battlefield

    move_off_battlefield(state, phlage, destination="hand")
    assert not phlage.escaped


# ---------------------------------------------------------------------------
# can't block — Aragorn / Headliner Scarlett
# ---------------------------------------------------------------------------


def test_cant_block_effects():
    assert parse_rmc_effect("up to one target creature can't block this turn") == (
        TargetCreatureCantBlockThisTurn(optional=True)
    )
    assert parse_rmc_effect("creatures can't block this turn") == CreaturesCantBlockThisTurn()
    state = make_state()
    a = add(state, 1, "Walking Ballista")
    b = add(state, 1, "Orcish Lumberjack")
    TargetCreatureCantBlockThisTurn().resolve(state, 0, (("creature", a.id),))
    assert creature_cant_block(state, a) and not creature_cant_block(state, b)
    assert eligible_blockers(state, 1) == [b]
    CreaturesCantBlockThisTurn(target_player=True).resolve(state, 0, (("player", 1),))
    late = add(state, 1, "Loot, the Pathfinder")
    assert eligible_blockers(state, 1) == []  # includes later arrivals
    assert CreaturesCantBlockThisTurn(target_player=True).legal_targets(state, 0) == [
        ("player", 0), ("player", 1),
    ]
    CreaturesCantBlockThisTurn(target_player=True).resolve(state, 0, ())  # no target: no-op
    run_cleanup_step(state)
    assert {o.id for o in eligible_blockers(state, 1)} == {a.id, b.id, late.id}


def test_aragorn_attack_trigger_monarch_branch():
    state = make_state(step=Step.DECLARE_ATTACKERS)
    aragorn = add(state, 0, "Aragorn, King of Gondor")
    blocker = add(state, 1, "Orcish Lumberjack")
    other = add(state, 1, "Walking Ballista")
    other.plus_one_counters = 2
    state.players[0].agent.scripts["target"] = [("creature", blocker.id)]
    declare_attackers(state, [aragorn.id])
    resolve_all(state)
    assert eligible_blockers(state, 1) == [other]  # not the monarch yet
    run_cleanup_step(state)
    state.players[0].is_monarch = True
    aragorn.attacking = False
    aragorn.tapped = False
    declare_attackers(state, [aragorn.id])
    state.players[0].agent.scripts["target"] = [("creature", blocker.id)]
    resolve_all(state)
    assert eligible_blockers(state, 1) == []


def test_headliner_scarlett_face_down_upkeep_impulse():
    state = make_state(step=Step.UPKEEP)
    scarlett = add(state, 0, "Headliner Scarlett")
    top = add(state, 0, "Lightning Bolt", Zone.LIBRARY)
    from mtg_bot.turn import run_beginning_of_upkeep_triggers

    run_beginning_of_upkeep_triggers(state)
    resolve_all(state)
    assert top in state.players[0].exile
    assert top.publicly_known_to == frozenset({0})
    assert top.exile_play_permission.player_id == 0
    assert scarlett in state.battlefield


# ---------------------------------------------------------------------------
# Impulse-exile grammar
# ---------------------------------------------------------------------------


def test_impulse_grammar_variants():
    eff = parse_rmc_effect(
        "exile the top card of your library. You may play that card until "
        "your next end step"
    )
    assert eff == ExileTopCardsWithPlayPermission(duration="until_your_next_end_step")
    # face-down needs the "look at" permission and vice versa.
    assert parse_rmc_effect(
        "exile the top card of your library face down. You may play that "
        "card this turn"
    ) is None
    assert parse_rmc_effect(
        "exile the top card of your library. You may look at and play that "
        "card this turn"
    ) is None
    assert parse_rmc_effect(
        "exile the top card of your library. You may do a dance"
    ) is None
    assert parse_rmc_effect(
        "exile the top card of your library. If you're bored, you may play "
        "that card this turn without paying its mana cost. Otherwise, you "
        "may play that card this turn"
    ) is None
    assert parse_rmc_effect(
        "exile a card at random from your graveyard. You may play that card "
        "until your next end step"
    ) is None
    assert parse_rmc_effect(
        "exile target Equipment, instant, or sorcery card from your "
        "graveyard. You may play that card this turn without paying its "
        "mana cost"
    ) is None
    assert parse_rmc_effect("if you're bored, draw a card") is None
    assert parse_rmc_effect("if you're the monarch, frobnicate") is None


def test_caves_of_chaos_free_only_after_completing_a_dungeon():
    state = make_state(step=Step.DECLARE_ATTACKERS)
    caves = add(state, 0, "Caves of Chaos Adventurer")
    first = add(state, 0, "Golos, Tireless Pilgrim", Zone.LIBRARY)
    declare_attackers(state, [caves.id])
    resolve_all(state)
    assert not first.exile_play_permission.free
    state.players[0].dungeons_completed = 1
    second = add(state, 0, "Walking Ballista", Zone.LIBRARY)
    caves.attacking = False
    caves.tapped = False
    declare_attackers(state, [caves.id])
    resolve_all(state)
    assert second.exile_play_permission.free
