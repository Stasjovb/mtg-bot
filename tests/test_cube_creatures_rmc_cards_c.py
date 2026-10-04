"""Cube creatures (R / multicolor / colorless) bucket: per-card engine
behavior, batch 5 — Emrakul (cast trigger, protection from colored
spells, annihilator, put-into-graveyard-from-anywhere trigger), Alpha
Deathclaw (monstrosity), Robber of the Rich, Raffine (connive), Gut,
Zirda (activation cost reduction), Lurrus (graveyard casting), inert
outside-the-game lines (companion / background / draft)."""

from __future__ import annotations

from mtg_bot.actions import CastSpell, apply_action
from mtg_bot.cards.parser.creature_rmc_grammar import (
    parse_rmc_creature_line_post,
    parse_rmc_effect,
    parse_rmc_intervening_if,
)
from mtg_bot.combat import declare_attackers
from mtg_bot.effects.generic.cube_creatures_rmc import (
    PutIntoGraveyardFromAnywhere,
    activation_cost_reduction,
)
from mtg_bot.game import ManaCoin, Zone, effective_power
from mtg_bot.keyword_rules import can_be_targeted_by, is_protected_from
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step, move_off_battlefield, state_based_actions
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
# Emrakul, the Aeons Torn
# ---------------------------------------------------------------------------


def test_emrakul_cast_trigger_takes_an_extra_turn():
    state = make_state()
    add_lands(state, 0, "Plains", 15)
    emrakul = add(state, 0, "Emrakul, the Aeons Torn", Zone.HAND)
    apply_action(state, 0, CastSpell(emrakul.id))
    assert state.stack[-1].ability is not None  # the cast trigger on top
    resolve_all(state)
    assert emrakul in state.battlefield
    assert state.extra_turn_queue == [0]


def test_emrakul_protection_from_colored_spells_only():
    state = make_state()
    emrakul = add(state, 0, "Emrakul, the Aeons Torn")
    bolt = add(state, 1, "Lightning Bolt", Zone.HAND)
    bolt.zone = Zone.STACK
    assert not can_be_targeted_by(state, emrakul, bolt, 1)
    ballista = add(state, 1, "Walking Ballista")  # colorless permanent source
    assert not is_protected_from(state, emrakul, ballista)
    loot = add(state, 1, "Loot, the Pathfinder")  # colored permanent, not a spell
    assert not is_protected_from(state, emrakul, loot)


def test_emrakul_annihilator():
    state = make_state(step=Step.DECLARE_ATTACKERS)
    emrakul = add(state, 0, "Emrakul, the Aeons Torn")
    for _ in range(7):
        add(state, 1, "Mountain")
    declare_attackers(state, [emrakul.id])
    resolve_all(state)
    assert sum(1 for o in state.battlefield if o.controller_id == 1) == 1
    assert len(state.players[1].graveyard) == 6


def test_emrakul_graveyard_shuffle_from_anywhere():
    state = make_state()
    emrakul = add(state, 0, "Emrakul, the Aeons Torn")
    for _ in range(3):
        add(state, 0, "Island", Zone.GRAVEYARD)
    move_off_battlefield(state, emrakul, destination="graveyard")
    state_based_actions(state)
    assert state.stack and state.stack[-1].ability.predicate == PutIntoGraveyardFromAnywhere()
    resolve_all(state)
    p0 = state.players[0]
    assert not p0.graveyard and emrakul in p0.library and len(p0.library) == 4
    assert p0.graveyard_arrival_watch == ()
    # Milled / discarded: the sweep notices the new arrival once.
    from mtg_bot.effects.generic.cube_creatures_rmc import _discard_chosen

    p0.library.remove(emrakul)
    emrakul.zone = Zone.HAND
    p0.hand.append(emrakul)
    _discard_chosen(state, 0, 1)
    state_based_actions(state)
    state_based_actions(state)
    assert len(state.stack) == 1
    resolve_all(state)
    assert emrakul in p0.library


# ---------------------------------------------------------------------------
# Alpha Deathclaw (monstrosity)
# ---------------------------------------------------------------------------


def test_alpha_deathclaw_monstrosity_trigger():
    state = make_state()
    for land in ("Swamp", "Forest", "Mountain", "Mountain", "Mountain", "Mountain", "Mountain"):
        add(state, 0, land)
    victim = add(state, 1, "Walking Ballista")
    victim.plus_one_counters = 2
    other = add(state, 1, "Black Lotus")
    claw = add(state, 0, "Alpha Deathclaw")
    state.players[0].agent.scripts["target"] = [("creature", victim.id)]
    activate(state, 0, claw)
    assert claw.monstrous and claw.plus_one_counters == 4
    assert victim in state.players[1].graveyard
    # Already monstrous: nothing further.
    for land in state.battlefield:
        land.tapped = False
    activate(state, 0, claw)
    assert claw.plus_one_counters == 4 and other in state.battlefield
    move_off_battlefield(state, claw, destination="hand")
    assert not claw.monstrous


# ---------------------------------------------------------------------------
# Robber of the Rich
# ---------------------------------------------------------------------------


def test_robber_of_the_rich():
    assert parse_rmc_intervening_if("defending player has more cards in hand than you")
    assert parse_rmc_intervening_if("nothing") is None
    state = make_state(step=Step.DECLARE_ATTACKERS)
    robber = add(state, 0, "Robber of the Rich")
    top = add(state, 1, "Walking Ballista", Zone.LIBRARY)
    # Equal hands: no trigger.
    declare_attackers(state, [robber.id])
    resolve_all(state)
    assert top in state.players[1].library
    add(state, 1, "Island", Zone.HAND)
    robber.attacking = False
    robber.tapped = False
    declare_attackers(state, [robber.id])
    resolve_all(state)
    assert top in state.players[1].exile
    perm = top.exile_play_permission
    assert perm.any_color_mana and perm.requires_attacked_with_subtype == "Rogue"
    # Castable with any mana this turn (Robber is a Rogue that attacked).
    state.step = Step.POSTCOMBAT_MAIN
    state.players[0].mana_pool.append(ManaCoin(color="G"))
    assert CastSpell(top.id) in legal_actions(state, 0)
    # A later turn without a Rogue attack: not castable.
    state.players[0].attacked_this_turn.clear()
    assert CastSpell(top.id) not in legal_actions(state, 0)


# ---------------------------------------------------------------------------
# Raffine, Scheming Seer (connive)
# ---------------------------------------------------------------------------


def test_raffine_connives_by_attacker_count():
    state = make_state(step=Step.DECLARE_ATTACKERS)
    raffine = add(state, 0, "Raffine, Scheming Seer")
    buddy = add(state, 0, "Orcish Lumberjack")
    for name in ("Lightning Bolt", "Island"):
        add(state, 0, name, Zone.LIBRARY)
    state.players[0].agent.scripts["target"] = [("creature", buddy.id)]
    declare_attackers(state, [raffine.id, buddy.id])
    resolve_all(state)
    # Drew 2 (Bolt, Island) and discarded 2 (default: first ids) — one
    # nonland => one counter.
    assert len(state.players[0].graveyard) == 2
    nonland = sum(1 for c in state.players[0].graveyard if not c.printing.is_land)
    assert buddy.plus_one_counters == nonland


# ---------------------------------------------------------------------------
# Gut, True-Soul Zealot
# ---------------------------------------------------------------------------


def test_gut_sacrifices_for_an_attacking_skeleton():
    assert parse_rmc_creature_line_post("Choose a Background", "Gut") is not None
    state = make_state(step=Step.DECLARE_ATTACKERS)
    gut = add(state, 0, "Gut, True Soul Zealot")
    fodder = add(state, 0, "Black Lotus")
    declare_attackers(state, [gut.id])
    resolve_all(state)
    skel = [o for o in state.battlefield if o.printing.name == "Skeleton"]
    assert fodder in state.players[0].graveyard
    assert len(skel) == 1 and skel[0].attacking and skel[0].tapped
    assert "menace" in skel[0].printing.keywords
    # Declining keeps everything.
    state2 = make_state(step=Step.DECLARE_ATTACKERS)
    state2.players[0].agent.scripts["yes_no"] = [False]
    gut2 = add(state2, 0, gut.printing.name)
    lotus = add(state2, 0, "Black Lotus")
    declare_attackers(state2, [gut2.id])
    resolve_all(state2)
    assert lotus in state2.battlefield


# ---------------------------------------------------------------------------
# Zirda, the Dawnwaker
# ---------------------------------------------------------------------------


def test_zirda_reduces_activation_costs_but_not_below_one():
    state = make_state()
    add(state, 0, "Zirda, the Dawnwaker")
    ballista = add(state, 0, "Walking Ballista")
    ab = ballista.printing.activated_abilities[0]  # {4}: +1/+1 counter
    from mtg_bot.actions import _effective_ability_mana_cost

    assert _effective_ability_mana_cost(state, ballista, ab).generic == 2
    zirda = next(o for o in state.battlefield if o.printing.name == "Zirda, the Dawnwaker")
    cant_block = zirda.printing.activated_abilities[0]  # {1}, {T}
    assert _effective_ability_mana_cost(state, zirda, cant_block).total == 1
    # Mana abilities aren't reduced.
    lotus = add(state, 0, "Black Lotus")
    mana_ab = lotus.printing.activated_abilities[0]
    assert activation_cost_reduction(state, 0, mana_ab, mana_ab.cost.mana) == mana_ab.cost.mana
    # The opponent's abilities aren't reduced.
    other = add(state, 1, "Walking Ballista")
    assert _effective_ability_mana_cost(state, other, ab).generic == 4
    # Zirda's own ability: target creature can't block this turn.
    add_lands(state, 0, "Mountain", 1)
    victim = add(state, 1, "Orcish Lumberjack")
    state.players[0].agent.scripts["target"] = [("creature", victim.id)]
    activate(state, 0, zirda, idx=0)
    from mtg_bot.combat import eligible_blockers

    assert victim not in eligible_blockers(state, 1)


# ---------------------------------------------------------------------------
# Lurrus of the Dream-Den
# ---------------------------------------------------------------------------


def test_lurrus_casts_one_cheap_permanent_from_graveyard_each_turn():
    state = make_state()
    add(state, 0, "Lurrus of the Dream-Den")
    add_lands(state, 0, "Mountain", 3)
    rag = add(state, 0, "Ragavan, Nimble Pilferer", Zone.GRAVEYARD)
    jack = add(state, 0, "Orcish Lumberjack", Zone.GRAVEYARD)
    golos = add(state, 0, "Golos, Tireless Pilgrim", Zone.GRAVEYARD)  # MV 5
    bolt = add(state, 0, "Lightning Bolt", Zone.GRAVEYARD)  # not a permanent
    actions = legal_actions(state, 0)
    assert CastSpell(rag.id) in actions and CastSpell(jack.id) in actions
    assert CastSpell(golos.id) not in actions and CastSpell(bolt.id) not in actions
    cast(state, 0, rag)
    assert rag in state.battlefield
    assert CastSpell(jack.id) not in legal_actions(state, 0)  # once per turn
    # Not during the opponent's turn.
    state.turn_number += 1
    state.active_player_idx = 1
    assert CastSpell(jack.id) not in legal_actions(state, 0)


# ---------------------------------------------------------------------------
# Outside-the-game lines
# ---------------------------------------------------------------------------


def test_outside_the_game_lines_are_inert():
    for line in (
        "Companion — Each permanent card in your starting deck has mana value 2 or less.",
        "Choose a Background",
        "Draft this card face up.",
    ):
        rmc = parse_rmc_creature_line_post(line, "X")
        assert rmc is not None and not (rmc.triggers or rmc.statics or rmc.activated)
    librarian = printing("Cogwork Librarian")
    assert not librarian.triggered_abilities and not librarian.static_abilities
    assert (librarian.power, librarian.toughness) == (3, 3)


def test_batch5_effect_grammar():
    assert parse_rmc_effect("sacrifice another creature or an artifact").another
    assert parse_rmc_effect("sacrifice a blue thing") is None
    assert parse_rmc_effect("monstrosity 3").count == 3
    assert parse_rmc_creature_line_post("Flying, annihilator 2, frobnicate", "X") is None
