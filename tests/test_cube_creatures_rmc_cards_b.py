"""Cube creatures (R / multicolor / colorless) bucket: per-card engine
behavior, batch 4 — attack requirements, enters-tapped statics, reveal
effects, magecraft, fights + the damage-heal replacement, random
destruction, Figure of Destiny's level-ups, graveyard self-replacement,
Painter's Servant."""

from __future__ import annotations

from mtg_bot.actions import CastSpell, DeclareAttackers, apply_action, push_spell_copy
from mtg_bot.cards.parser.creature_rmc_grammar import (
    parse_rmc_creature_line_post,
    parse_rmc_effect,
    parse_rmc_trigger_phrase,
)
from mtg_bot.cards.tokens import TOKEN_PRINTINGS
from mtg_bot.combat import declare_attackers, declare_blockers, resolve_combat_damage
from mtg_bot.designations import forced_attackers
from mtg_bot.game import (
    Zone,
    effective_colors,
    effective_keywords,
    effective_power,
    effective_subtypes,
    effective_toughness,
)
from mtg_bot.turn import Step, move_off_battlefield, state_based_actions
from tests._rmc_helpers import (
    activate,
    add,
    add_lands,
    cast,
    make_state,
    printing,
    resolve_all,
)


# ---------------------------------------------------------------------------
# Dragon's Rage Channeler
# ---------------------------------------------------------------------------


def test_dragons_rage_channeler_delirium_static():
    state = make_state()
    drc = add(state, 0, "Dragon's Rage Channeler")
    assert effective_power(state, drc) == 1
    assert forced_attackers(state, 0) == []
    for name in ("Island", "Lightning Bolt", "Walking Ballista"):
        add(state, 0, name, Zone.GRAVEYARD)
    # land, instant, artifact, creature = 4 types
    assert effective_power(state, drc) == 3
    assert "flying" in effective_keywords(state, drc)
    assert forced_attackers(state, 0) == [drc.id]
    state.step = Step.DECLARE_ATTACKERS
    apply_action(state, 0, DeclareAttackers(attacker_ids=frozenset()))
    assert drc.attacking


# ---------------------------------------------------------------------------
# Spider-Woman, Stunning Savior
# ---------------------------------------------------------------------------


def test_spider_woman_opponents_artifacts_and_creatures_enter_tapped():
    state = make_state()
    add(state, 0, "Spider-Woman, Stunning Savior")
    add_lands(state, 1, "Mountain", 2)
    state.active_player_idx = 1
    state.priority_player_idx = 1
    rag = add(state, 1, "Ragavan, Nimble Pilferer", Zone.HAND)
    cast(state, 1, rag)
    assert rag.tapped
    # Its own controller's creatures enter untapped.
    state.active_player_idx = 0
    state.priority_player_idx = 0
    add_lands(state, 0, "Mountain", 1)
    mine = add(state, 0, "Ragavan, Nimble Pilferer", Zone.HAND)
    cast(state, 0, mine)
    assert not mine.tapped


# ---------------------------------------------------------------------------
# Painter's Servant
# ---------------------------------------------------------------------------


def test_painters_servant_paints_everything():
    pr = printing("Painter's Servant")
    assert pr.paints_all_objects_chosen_color_at_etb
    state = make_state()
    state.players[0].agent.scripts["color"] = ["U"]
    add_lands(state, 0, "Island", 2)
    servant = add(state, 0, "Painter's Servant", Zone.HAND)
    cast(state, 0, servant)
    bolt = add(state, 1, "Lightning Bolt", Zone.HAND)
    assert "U" in effective_colors(state, bolt) and "R" in effective_colors(state, bolt)
    # The choose-a-color line alone isn't claimable.
    from mtg_bot.cards.parser.creature_builder import _build_creature_printing

    card = {
        "name": "Test Chooser", "mana_cost": "{2}", "type_line": "Artifact Creature — Scarecrow",
        "power": "1", "toughness": "3",
        "oracle_text": "As this creature enters, choose a color.",
    }
    assert _build_creature_printing(card) is None


# ---------------------------------------------------------------------------
# Raph & Mikey, Troublemakers
# ---------------------------------------------------------------------------


def test_raph_and_mikey_reveal_until_creature_attacking():
    assert parse_rmc_trigger_phrase("this creature attack")[1] is not None
    state = make_state(step=Step.DECLARE_ATTACKERS)
    rm = add(state, 0, "Raph & Mikey, Troublemakers")
    island = add(state, 0, "Island", Zone.LIBRARY)
    golos = add(state, 0, "Tersa Lightshatter", Zone.LIBRARY)
    swamp = add(state, 0, "Swamp", Zone.LIBRARY)
    state.players[0].agent.scripts["x"] = [0]
    declare_attackers(state, [rm.id])
    resolve_all(state)
    assert golos in state.battlefield and golos.tapped and golos.attacking
    lib = state.players[0].library
    assert lib[0] is swamp and lib[1] is island
    resolve_combat_damage(state, 1)
    assert state.players[1].life == 20 - effective_power(state, rm) - 3


# ---------------------------------------------------------------------------
# Atraxa, Grand Unifier
# ---------------------------------------------------------------------------


def test_atraxa_takes_one_card_per_type():
    state = make_state()
    for name in (
        "Island", "Lightning Bolt", "Walking Ballista", "Golos, Tireless Pilgrim",
        "Swamp", "Black Lotus",
    ):
        add(state, 0, name, Zone.LIBRARY)
    for land in ("Plains", "Island", "Swamp", "Forest", "Mountain", "Mountain", "Mountain"):
        add(state, 0, land)
    atraxa = add(state, 0, "Atraxa, Grand Unifier", Zone.HAND)
    agent = state.players[0].agent
    # Artifact: Ballista (not Golos / Lotus); creature: Golos (Ballista
    # already taken); instant: Bolt; land: decline.
    ids = {c.printing.name: c.id for c in state.players[0].library}
    agent.scripts["library"] = [
        ids["Walking Ballista"], ids["Golos, Tireless Pilgrim"],
        ids["Lightning Bolt"], None,
    ]
    cast(state, 0, atraxa)
    names = sorted(c.printing.name for c in state.players[0].hand)
    assert names == ["Golos, Tireless Pilgrim", "Lightning Bolt", "Walking Ballista"]
    assert len(state.players[0].library) == 3


# ---------------------------------------------------------------------------
# Witherbloom Apprentice (magecraft: cast or copy)
# ---------------------------------------------------------------------------


def test_witherbloom_apprentice_cast_and_copy():
    state = make_state()
    add(state, 0, "Witherbloom Apprentice")
    add(state, 0, "Mountain")
    bolt = add(state, 0, "Lightning Bolt", Zone.HAND)
    state.players[0].agent.scripts["target"] = [("player", 1)]
    apply_action(state, 0, CastSpell(bolt.id))
    resolve_all(state)
    assert state.players[1].life == 16 and state.players[0].life == 21
    push_spell_copy(state, printing("Lightning Bolt"), 0, targets=(("player", 1),))
    resolve_all(state)
    assert state.players[1].life == 12 and state.players[0].life == 22
    # Creature spells don't trigger it; an opponent's copy doesn't either.
    push_spell_copy(state, printing("Lightning Bolt"), 1, targets=(("player", 0),))
    resolve_all(state)
    assert state.players[1].life == 12


# ---------------------------------------------------------------------------
# Wolverine, Fierce Fighter
# ---------------------------------------------------------------------------


def test_wolverine_fights_and_heals_prior_damage():
    state = make_state()
    add_lands(state, 0, "Mountain", 2)
    add_lands(state, 0, "Forest", 2)
    victim = add(state, 1, "Orcish Lumberjack")
    wolverine = add(state, 0, "Wolverine, Fierce Fighter", Zone.HAND)
    state.players[0].agent.scripts["target"] = [("creature", victim.id)]
    cast(state, 0, wolverine)
    assert victim in state.players[1].graveyard
    assert wolverine.damage == 1
    # New damage heals the earlier damage.
    from mtg_bot.effects.base import _apply_damage

    _apply_damage(state, ("creature", wolverine.id), 2)
    assert wolverine.damage == 2
    _apply_damage(state, ("creature", wolverine.id), 1)
    assert wolverine.damage == 1


def test_wolverine_combat_damage_from_two_blockers_is_one_event():
    state = make_state(step=Step.DECLARE_ATTACKERS)
    wolverine = add(state, 0, "Wolverine, Fierce Fighter")
    wolverine.damage = 3
    b1 = add(state, 1, "Tersa Lightshatter")
    b2 = add(state, 1, "Ragavan, Nimble Pilferer")
    declare_attackers(state, [wolverine.id])
    declare_blockers(state, {b1.id: wolverine.id, b2.id: wolverine.id})
    state.players[0].agent.scripts["target"] = []
    resolve_combat_damage(state, 1)
    # 3 (Tersa) + 1 (Ragavan) this step; the old 3 damage was healed once.
    assert wolverine.damage == effective_power(state, b1) + effective_power(state, b2)


# ---------------------------------------------------------------------------
# Chaos Defiler
# ---------------------------------------------------------------------------


def test_chaos_defiler_destroys_chosen_permanent():
    state = make_state()
    add_lands(state, 0, "Mountain", 3)
    add_lands(state, 0, "Swamp", 2)
    rag = add(state, 1, "Ragavan, Nimble Pilferer")
    lotus = add(state, 1, "Black Lotus")
    state.players[0].agent.scripts["sacrifice"] = [lotus.id]
    defiler = add(state, 0, "Chaos Defiler", Zone.HAND)
    cast(state, 0, defiler)
    assert lotus in state.players[1].graveyard and rag in state.battlefield
    # Dies: again.
    move_off_battlefield(state, defiler, destination="graveyard")
    resolve_all(state)
    assert rag in state.players[1].graveyard


# ---------------------------------------------------------------------------
# Figure of Destiny
# ---------------------------------------------------------------------------


def test_figure_of_destiny_levels_up():
    eff = parse_rmc_effect(
        "if this creature is a Warrior, it becomes a Kithkin Spirit Warrior "
        "Avatar with base power and toughness 8/8, flying, and first strike"
    )
    assert eff.requires_subtype == "Warrior" and eff.keywords == frozenset({"flying", "first strike"})
    state = make_state()
    fig = add(state, 0, "Figure of Destiny")
    add_lands(state, 0, "Mountain", 10)
    # The 4/4 step does nothing while it isn't a Spirit.
    activate(state, 0, fig, idx=1)
    assert effective_power(state, fig) == 1
    activate(state, 0, fig, idx=0)
    assert effective_power(state, fig) == 2 and "Spirit" in effective_subtypes(state, fig)
    activate(state, 0, fig, idx=1)
    assert effective_power(state, fig) == 4 and "Warrior" in effective_subtypes(state, fig)
    for land in state.battlefield:
        land.tapped = False
    activate(state, 0, fig, idx=2)
    assert effective_power(state, fig) == 8 and effective_toughness(state, fig) == 8
    assert {"flying", "first strike"} <= effective_keywords(state, fig)


# ---------------------------------------------------------------------------
# Blightsteel Colossus
# ---------------------------------------------------------------------------


def test_blightsteel_shuffles_into_library_from_anywhere():
    assert parse_rmc_creature_line_post(
        "If Blightsteel Colossus would be put into a graveyard from anywhere, "
        "reveal Blightsteel Colossus and shuffle it into its owner's library "
        "instead.", "Blightsteel Colossus",
    ).statics
    state = make_state()
    colossus = add(state, 0, "Blightsteel Colossus")
    move_off_battlefield(state, colossus, destination="graveyard")
    assert colossus in state.players[0].library
    assert not state.players[0].graveyard
    # Discarded: caught by the state-based sweep.
    card = add(state, 0, "Blightsteel Colossus", Zone.HAND)
    from mtg_bot.effects.generic.cube_creatures_rmc import _discard_chosen

    _discard_chosen(state, 0, 1)
    assert card in state.players[0].graveyard
    state_based_actions(state)
    assert card in state.players[0].library
    # Ordinary cards stay in the graveyard.
    bolt = add(state, 0, "Lightning Bolt", Zone.GRAVEYARD)
    state_based_actions(state)
    assert bolt in state.players[0].graveyard
