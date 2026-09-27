"""Cube creatures (R / multicolor / colorless) bucket: per-card engine
behavior for the formula / discard / token / trigger shapes (batch 3)."""

from __future__ import annotations

from mtg_bot.actions import CastSpell, apply_action
from mtg_bot.cards.base import make_creature
from mtg_bot.cards.parser.creature_rmc_grammar import (
    parse_rmc_dynamic_pt_line,
    parse_rmc_effect,
    parse_rmc_trigger_phrase,
)
from mtg_bot.cards.tokens import TOKEN_PRINTINGS
from mtg_bot.combat import declare_attackers
from mtg_bot.effects.predicates import Event
from mtg_bot.game import Zone, effective_keywords, effective_power, effective_toughness, gain_life
from mtg_bot.legal import legal_actions
from mtg_bot.turn import (
    Step,
    run_beginning_of_upkeep_triggers,
    run_cleanup_step,
    tap_permanent,
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


def _token(state, pid, name):
    obj = state.new_object(TOKEN_PRINTINGS[name], owner_id=pid, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.battlefield.append(obj)
    return obj


def _named(state, pid):
    return [o.printing.name for o in state.battlefield if o.controller_id == pid]


# ---------------------------------------------------------------------------
# Bloodtithe Harvester
# ---------------------------------------------------------------------------


def test_bloodtithe_harvester():
    state = make_state()
    add_lands(state, 0, "Swamp", 1)
    add_lands(state, 0, "Mountain", 1)
    harvester = add(state, 0, "Bloodtithe Harvester", Zone.HAND)
    cast(state, 0, harvester)
    assert _named(state, 0).count("Blood") == 1
    _token(state, 0, "Blood")
    victim = add(state, 1, "Tersa Lightshatter")  # 3/3
    harvester.summoning_sick = False
    state.players[0].agent.scripts["target"] = [("creature", victim.id)]
    activate(state, 0, harvester)
    assert harvester in state.players[0].graveyard
    assert victim in state.players[1].graveyard  # -4/-4 on a 3/3
    # Sorcery speed only.
    state2 = make_state(step=Step.DECLARE_ATTACKERS)
    h2 = add(state2, 0, "Bloodtithe Harvester")
    add(state2, 1, "Walking Ballista")
    assert not can_activate(state2, 0, h2)


# ---------------------------------------------------------------------------
# Carnage Interpreter
# ---------------------------------------------------------------------------


def test_carnage_interpreter_discards_hand_investigates_and_grows():
    state = make_state()
    add_lands(state, 0, "Swamp", 3)
    card = add(state, 0, "Carnage Interpreter", Zone.HAND)
    for _ in range(3):
        add(state, 0, "Island", Zone.HAND)
    cast(state, 0, card)
    p0 = state.players[0]
    assert not p0.hand and len(p0.graveyard) == 3
    assert _named(state, 0).count("Clue") == 4
    assert effective_power(state, card) == 5 and effective_toughness(state, card) == 5
    assert "menace" in effective_keywords(state, card)
    add(state, 0, "Island", Zone.HAND)
    add(state, 0, "Island", Zone.HAND)
    assert effective_power(state, card) == 3
    assert "menace" not in effective_keywords(state, card)


# ---------------------------------------------------------------------------
# Generous Plunderer
# ---------------------------------------------------------------------------


def test_generous_plunderer_upkeep_treasures_and_attack_damage():
    state = make_state(step=Step.UPKEEP)
    plunderer = add(state, 0, "Generous Plunderer")
    run_beginning_of_upkeep_triggers(state)
    resolve_all(state)
    assert _named(state, 0).count("Treasure") == 1
    opp_treasures = [o for o in state.battlefield if o.controller_id == 1]
    assert len(opp_treasures) == 1 and opp_treasures[0].tapped
    # Declining creates nothing.
    state.players[0].agent.scripts["yes_no"] = [False]
    run_beginning_of_upkeep_triggers(state)
    resolve_all(state)
    assert _named(state, 0).count("Treasure") == 1
    # Attack: damage equal to the artifacts the defender controls.
    _token(state, 1, "Treasure")
    state.step = Step.DECLARE_ATTACKERS
    declare_attackers(state, [plunderer.id])
    resolve_all(state)
    assert state.players[1].life == 18


# ---------------------------------------------------------------------------
# Goblin Engineer
# ---------------------------------------------------------------------------


def test_goblin_engineer_entomb_and_reanimate_artifact():
    state = make_state()
    add_lands(state, 0, "Mountain", 3)
    engineer = add(state, 0, "Goblin Engineer", Zone.HAND)
    stone = add(state, 0, "The Mind Stone", Zone.LIBRARY)
    add(state, 0, "Island", Zone.LIBRARY)
    state.players[0].agent.scripts["library"] = [stone.id]
    cast(state, 0, engineer)
    assert stone in state.players[0].graveyard
    engineer.summoning_sick = False
    assert not can_activate(state, 0, engineer)  # no artifact to sacrifice
    fodder = _token(state, 0, "Treasure")
    state.players[0].agent.scripts["target"] = [("graveyard_card", stone.id)]
    activate(state, 0, engineer)
    assert stone in state.battlefield
    assert fodder not in state.battlefield


# ---------------------------------------------------------------------------
# Ivora, Insatiable Heir
# ---------------------------------------------------------------------------


def test_ivora_blood_tokens_and_discard_counters():
    state = make_state()
    add_lands(state, 0, "Mountain", 2)
    ivora = add(state, 0, "Ivora, Insatiable Heir", Zone.HAND)
    cast(state, 0, ivora)
    assert _named(state, 0).count("Blood") == 1
    add(state, 0, "Island", Zone.HAND)
    blood = next(o for o in state.battlefield if o.printing.name == "Blood")
    for land in state.battlefield:
        land.tapped = False
    activate(state, 0, blood)
    assert ivora.plus_one_counters == 1
    ivora.summoning_sick = False
    state.step = Step.COMBAT_DAMAGE
    declare_attackers(state, [ivora.id])
    from mtg_bot.combat import resolve_combat_damage

    resolve_combat_damage(state, 1)
    resolve_all(state)
    assert _named(state, 0).count("Blood") == 1


# ---------------------------------------------------------------------------
# Magda, Brazen Outlaw
# ---------------------------------------------------------------------------


def test_magda_dwarf_lord_treasures_and_tutor():
    dwarf = make_creature("Test Dwarf", "{R}", 1, 1, subtypes=("Dwarf",))
    state = make_state()
    magda = add(state, 0, "Magda, Brazen Outlaw")
    d = state.new_object(dwarf, 0, Zone.BATTLEFIELD)
    d.summoning_sick = False
    state.battlefield.append(d)
    assert effective_power(state, d) == 2 and effective_power(state, magda) == 2
    tap_permanent(state, d)
    tap_permanent(state, magda)
    resolve_all(state)
    assert _named(state, 0).count("Treasure") == 2
    assert not can_activate(state, 0, magda)
    for _ in range(3):
        _token(state, 0, "Treasure")
    lotus = add(state, 0, "Black Lotus", Zone.LIBRARY)
    state.players[0].agent.scripts["library"] = [lotus.id]
    activate(state, 0, magda)
    assert lotus in state.battlefield
    assert _named(state, 0).count("Treasure") == 0


# ---------------------------------------------------------------------------
# Otharri, Suns' Glory
# ---------------------------------------------------------------------------


def test_otharri_experience_rebels_and_graveyard_return():
    state = make_state(step=Step.DECLARE_ATTACKERS)
    otharri = add(state, 0, "Otharri, Suns' Glory")
    declare_attackers(state, [otharri.id])
    resolve_all(state)
    rebels = [o for o in state.battlefield if o.printing.name == "Rebel"]
    assert state.players[0].experience_counters == 1
    assert len(rebels) == 1 and rebels[0].tapped and rebels[0].attacking
    # Graveyard ability: tap an untapped Rebel.
    from mtg_bot.turn import move_off_battlefield

    move_off_battlefield(state, otharri, destination="graveyard")
    state.step = Step.PRECOMBAT_MAIN
    add_lands(state, 0, "Mountain", 2)
    add_lands(state, 0, "Plains", 2)
    assert not can_activate(state, 0, otharri)  # the Rebel is tapped
    rebels[0].tapped = False
    activate(state, 0, otharri)
    assert otharri in state.battlefield and otharri.tapped
    assert rebels[0].tapped


# ---------------------------------------------------------------------------
# Pyrogoyf
# ---------------------------------------------------------------------------


def test_pyrogoyf_pt_and_enters_damage():
    assert parse_rmc_dynamic_pt_line(
        "Barrowgoyf's power is equal to the number of card types among cards "
        "in all graveyards and its toughness is equal to that number plus 1."
    ) == "card_types_in_all_graveyards+1"
    assert parse_rmc_dynamic_pt_line("Nope.") is None
    state = make_state()
    add(state, 1, "Lightning Bolt", Zone.GRAVEYARD)
    add(state, 0, "Island", Zone.GRAVEYARD)
    add(state, 0, "Walking Ballista", Zone.GRAVEYARD)  # artifact creature
    add_lands(state, 0, "Mountain", 4)
    goyf = add(state, 0, "Pyrogoyf", Zone.HAND)
    state.players[0].agent.scripts["target"] = [("player", 1)]
    cast(state, 0, goyf)
    # instant, land, artifact, creature = 4
    assert effective_power(state, goyf) == 4 and effective_toughness(state, goyf) == 5
    assert state.players[1].life == 16


def test_self_or_another_subtype_trigger_phrase():
    ev, pred = parse_rmc_trigger_phrase(
        "this creature or another Lhurgoyf creature you control enters"
    )
    assert ev == Event.ENTERS
    assert parse_rmc_trigger_phrase("a Dwarf you control becomes tapped")[0] == Event.BECOMES_TAPPED


# ---------------------------------------------------------------------------
# Screaming Nemesis
# ---------------------------------------------------------------------------


def test_screaming_nemesis_redirects_damage_and_stops_lifegain():
    state = make_state()
    nemesis = add(state, 0, "Screaming Nemesis")
    add(state, 1, "Mountain")
    bolt = add(state, 1, "Lightning Bolt", Zone.HAND)
    state.active_player_idx = 1
    state.priority_player_idx = 1
    state.players[1].agent.scripts["target"] = [("creature", nemesis.id)]
    state.players[0].agent.scripts["target"] = [("player", 1)]
    apply_action(state, 1, CastSpell(bolt.id))
    resolve_all(state)
    assert nemesis in state.players[0].graveyard
    assert state.players[1].life == 17
    assert state.players[1].cant_gain_life
    assert gain_life(state, 1, 5) == 0 and state.players[1].life == 17
    # "any other target": the Nemesis itself is excluded.
    eff = printing("Screaming Nemesis").triggered_abilities[0].effect
    state.resolving_source = nemesis
    assert ("creature", nemesis.id) not in eff.legal_targets(state, 0)


# ---------------------------------------------------------------------------
# Seasoned Pyromancer
# ---------------------------------------------------------------------------


def test_seasoned_pyromancer_etb_tokens_per_nonland_discard():
    state = make_state()
    add_lands(state, 0, "Mountain", 3)
    pyro = add(state, 0, "Seasoned Pyromancer", Zone.HAND)
    bolt = add(state, 0, "Lightning Bolt", Zone.HAND)
    island = add(state, 0, "Island", Zone.HAND)
    for _ in range(3):
        add(state, 0, "Swamp", Zone.LIBRARY)
    state.players[0].agent.scripts["discard"] = [bolt.id, island.id]
    cast(state, 0, pyro)
    assert bolt in state.players[0].graveyard and island in state.players[0].graveyard
    assert len(state.players[0].hand) == 2
    assert _named(state, 0).count("Elemental") == 1


def test_seasoned_pyromancer_graveyard_ability():
    state = make_state()
    card = add(state, 0, "Seasoned Pyromancer", Zone.GRAVEYARD)
    assert not can_activate(state, 0, card)
    add_lands(state, 0, "Mountain", 5)
    activate(state, 0, card)
    assert card in state.players[0].exile
    assert _named(state, 0).count("Elemental") == 2


# ---------------------------------------------------------------------------
# Territorial Kavu
# ---------------------------------------------------------------------------


def test_territorial_kavu_domain_and_attack_modes():
    state = make_state(step=Step.DECLARE_ATTACKERS)
    kavu = add(state, 0, "Territorial Kavu")
    add(state, 0, "Mountain")
    add(state, 0, "Forest")
    add(state, 0, "Mountain")
    assert effective_power(state, kavu) == 2 and effective_toughness(state, kavu) == 2
    target = add(state, 1, "Lightning Bolt", Zone.GRAVEYARD)
    state.players[0].agent.scripts["mode"] = [1]
    state.players[0].agent.scripts["target"] = [("card_in_graveyard", target.id)]
    declare_attackers(state, [kavu.id])
    resolve_all(state)
    assert target in state.players[1].exile
    # Mode 0: discard a card, if you do, draw a card.
    add(state, 0, "Island", Zone.HAND)
    add(state, 0, "Swamp", Zone.LIBRARY)
    run_cleanup_step(state)
    kavu.attacking = False
    kavu.tapped = False
    state.players[0].agent.scripts["mode"] = [0]
    declare_attackers(state, [kavu.id])
    resolve_all(state)
    hand = state.players[0].hand
    assert [c.printing.name for c in hand] == ["Swamp"]


# ---------------------------------------------------------------------------
# Tersa Lightshatter
# ---------------------------------------------------------------------------


def test_tersa_lightshatter():
    state = make_state()
    add_lands(state, 0, "Mountain", 3)
    tersa = add(state, 0, "Tersa Lightshatter", Zone.HAND)
    for _ in range(3):
        add(state, 0, "Island", Zone.HAND)
    for _ in range(3):
        add(state, 0, "Swamp", Zone.LIBRARY)
    state.players[0].agent.scripts["x"] = [1]
    cast(state, 0, tersa)
    assert len(state.players[0].hand) == 3
    assert len(state.players[0].graveyard) == 1
    # Attack with fewer than 7 cards in graveyard: no trigger.
    state.step = Step.DECLARE_ATTACKERS
    declare_attackers(state, [tersa.id])
    resolve_all(state)
    assert not state.players[0].exile
    for _ in range(6):
        add(state, 0, "Swamp", Zone.GRAVEYARD)
    tersa.attacking = False
    tersa.tapped = False
    declare_attackers(state, [tersa.id])
    resolve_all(state)
    assert len(state.players[0].exile) == 1
    assert state.players[0].exile[0].exile_play_permission is not None


# ---------------------------------------------------------------------------
# Thor, God of Thunder
# ---------------------------------------------------------------------------


def test_thor_recasts_from_graveyard_and_burns_on_noncreature_spells():
    state = make_state()
    add_lands(state, 0, "Mountain", 6)
    bolt = add(state, 0, "Lightning Bolt", Zone.GRAVEYARD)
    add(state, 0, "Island", Zone.GRAVEYARD)
    thor = add(state, 0, "Thor, God of Thunder", Zone.HAND)
    state.players[0].agent.scripts["target"] = [("graveyard_card", bolt.id)]
    cast(state, 0, thor)
    assert bolt in state.players[0].exile
    perm = bolt.exile_play_permission
    assert perm.duration == "until_end_of_your_next_turn"
    # Casting the Bolt (noncreature, MV 1): Thor's trigger deals 1.
    state.players[0].agent.scripts["target"] = [("player", 1), ("player", 1)]
    apply_action(state, 0, CastSpell(bolt.id))
    resolve_all(state)
    assert state.players[1].life == 16
    assert parse_rmc_effect(
        "deals damage equal to that spell's mana value to any target"
    ).subject_slot == "spell"
