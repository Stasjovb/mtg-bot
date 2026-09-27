"""Cube W/G creatures: Seasoned Dungeoneer, Baloth Prime (stun counters,
land sacrifice trigger), Guerrilla Gorilla / Haywire Mite (spells-A
removal grammar)."""

from __future__ import annotations

from mtg_bot.actions import ActivateAbility, apply_action, put_into_battlefield
from mtg_bot.effects.generic.cube_creatures_wg import GrantKeywordsUEOTThenExplores
from mtg_bot.game import Zone, effective_keywords
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step, run_untap_step, sacrifice
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


def test_seasoned_dungeoneer_initiative_and_protection_explore():
    pr = cube()["Seasoned Dungeoneer"]
    state = make_state()
    for _ in range(3):
        put(state, 0, "Forest", Zone.LIBRARY)
    sd = put(state, 0, pr, Zone.HAND)
    add_lands(state, 0, "Plains", 4)
    cast_and_resolve(state, 0, sd)
    assert state.players[0].has_initiative
    warrior = put(state, 0, bear("Warrior", subtypes=("Human", "Warrior")))
    plain = put(state, 0, bear("Plain"))
    state.players[0].agent.scripts["target"] = [("creature", warrior.id)]
    attack(state, 0, [warrior.id, plain.id])
    assert "protection from creatures" in effective_keywords(state, warrior)
    # Explore: the top card was a land -> into the hand.
    assert any(c.printing.name == "Forest" for c in state.players[0].hand)
    eff = next(
        t.effect for t in pr.triggered_abilities
        if isinstance(t.effect, GrantKeywordsUEOTThenExplores)
    )
    state.resolving_source = sd
    legal = eff.legal_targets(state, 0)
    state.resolving_source = None
    assert ("creature", plain.id) not in legal
    eff.resolve(state, 0, ())
    assert "explores" in eff.describe()


def test_baloth_prime_stunned_then_land_sacrifice_untaps_and_makes_beast():
    pr = cube()["Baloth Prime"]
    assert pr.enters_tapped and pr.enters_with_named_counters == (("stun", 6),)
    state = make_state()
    baloth = put(state, 0, pr, Zone.HAND)
    add_lands(state, 0, "Forest", 4)
    cast_and_resolve(state, 0, baloth)
    assert baloth.tapped and baloth.stun_counters == 6
    land = put(state, 0, "Forest")
    sacrifice(state, land)
    drain(state)
    beasts = [o for o in state.battlefield if o.printing.name == "Beast"]
    assert len(beasts) == 1 and beasts[0].tapped
    assert beasts[0].printing.power == 4
    # "untap this creature" removes a stun counter instead.
    assert baloth.tapped and baloth.stun_counters == 5
    state.active_player_idx = 0
    run_untap_step(state)
    assert baloth.stun_counters == 4
    # Opponent's land sacrifices don't count.
    theirs = put(state, 1, "Forest")
    sacrifice(state, theirs)
    drain(state)
    assert sum(o.printing.name == "Beast" for o in state.battlefield) == 1


def test_baloth_prime_sac_land_ability_gains_life():
    pr = cube()["Baloth Prime"]
    state = make_state()
    baloth = put(state, 0, pr)
    lands = add_lands(state, 0, "Forest", 5)
    idx = next(
        i for i, ab in enumerate(pr.activated_abilities)
        if ab.cost.sacrifice_a_land
    )
    apply_action(state, 0, ActivateAbility(source_id=baloth.id, ability_index=idx))
    drain(state)
    assert state.players[0].life == 22
    # The land sacrifice also fed the Beast trigger.
    assert any(o.printing.name == "Beast" for o in state.battlefield)
    assert sum(1 for l in lands if l in state.battlefield) == 4


def test_guerrilla_gorilla_and_haywire_mite():
    state = make_state()
    gorilla = put(state, 0, "Guerrilla Gorilla")
    rock = put(state, 1, "Sol Ring")
    state.players[0].agent.scripts["target"] = [("permanent", rock.id)]
    act = ActivateAbility(source_id=gorilla.id, ability_index=0)
    state.step = Step.UPKEEP
    assert act not in legal_actions(state, 0)  # sorcery speed only
    state.step = Step.PRECOMBAT_MAIN
    apply_action(state, 0, act)
    drain(state)
    assert rock in state.players[1].graveyard
    mite = put(state, 0, "Haywire Mite")
    vault = put(state, 1, "Mana Vault")
    add_lands(state, 0, "Forest", 1)
    state.players[0].agent.scripts["target"] = [("permanent", vault.id)]
    apply_action(state, 0, ActivateAbility(source_id=mite.id, ability_index=0))
    drain(state)
    assert vault in state.players[1].exile
    assert state.players[0].life == 22  # Mite's dies trigger


def test_keen_eyed_curator_grows_with_four_exiled_card_types():
    from mtg_bot.effects.generic.cube_creatures_wg import (
        CardTypesAmongExiledWithSourceAtLeast,
        LinkExiledCardsToSource,
    )
    from mtg_bot.game import effective_power

    pr = cube()["Keen-Eyed Curator"]
    assert isinstance(pr.activated_abilities[0].effect, LinkExiledCardsToSource)
    state = make_state()
    cur = put(state, 0, pr)
    add_lands(state, 0, "Forest", 4)
    cards = [
        put(state, 1, n, Zone.GRAVEYARD)
        for n in ("Forest", "Lightning Bolt", "Llanowar Elves", "Sol Ring")
    ]
    agent = state.players[0].agent
    for i, card in enumerate(cards):
        agent.scripts["target"] = [("card_in_graveyard", card.id)]
        apply_action(state, 0, ActivateAbility(source_id=cur.id, ability_index=0))
        drain(state)
        if i < 3:
            assert effective_power(state, cur) == 3
    assert all(c in state.players[1].exile for c in cards)
    assert effective_power(state, cur) == 7
    assert "trample" in effective_keywords(state, cur)
    assert not CardTypesAmongExiledWithSourceAtLeast(4).matches(state, 0)


def test_adeline_power_and_attack_tokens():
    from mtg_bot.effects.generic.cube_creatures_wg import (
        CreateAttackingTokenForEachOpponent,
        PowerEqualsCount,
    )
    from mtg_bot.game import effective_power

    pr = cube()["Adeline, Resplendent Cathar"]
    assert isinstance(pr.dynamic_pt_formula, PowerEqualsCount)
    assert "vigilance" in pr.keywords
    state = make_state()
    adeline = put(state, 0, pr)
    assert effective_power(state, adeline) == 1
    other = put(state, 0, bear("Other"))
    put(state, 1, bear("Theirs"))
    assert effective_power(state, adeline) == 2
    attack(state, 0, [adeline.id, other.id])
    humans = [o for o in state.battlefield if o.printing.name == "Human"]
    assert len(humans) == 1
    assert humans[0].tapped and humans[0].attacking
    assert humans[0].printing.color_indicator == frozenset({"W"})
    assert effective_power(state, adeline) == 3
    eff = next(
        t.effect for t in pr.triggered_abilities
        if isinstance(t.effect, CreateAttackingTokenForEachOpponent)
    )
    assert "each opponent" in eff.describe()


def test_mole_man_moloid_tokens_mill_on_attack():
    pr = cube()["Mole Man, Moloid Master"]
    assert pr.grants_play_lands_from_graveyard
    state = make_state()
    put(state, 0, pr)
    for _ in range(2):
        put(state, 0, "Forest", Zone.LIBRARY)
    land = put(state, 0, "Forest", Zone.HAND)
    state.players[0].hand.remove(land)
    put_into_battlefield(state, land, 0)
    drain(state)
    moloids = [o for o in state.battlefield if o.printing.name == "Moloid"]
    assert len(moloids) == 1
    moloid = moloids[0]
    assert moloid.printing.subtypes == ("Minion",)
    moloid.summoning_sick = False
    attack(state, 0, [moloid.id])
    assert len(state.players[0].graveyard) == 1


def test_ursine_monstrosity_combat_trigger():
    from mtg_bot.designations import forced_attackers
    from mtg_bot.effects.generic.cube_creatures_wg import MillChooseOpponentAttackPump
    from mtg_bot.game import effective_power
    from mtg_bot.turn import run_beginning_of_combat_triggers

    pr = cube()["Ursine Monstrosity"]
    eff = pr.triggered_abilities[0].effect
    assert isinstance(eff, MillChooseOpponentAttackPump)
    state = make_state()
    ursine = put(state, 0, pr)
    put(state, 0, "Lightning Bolt", Zone.GRAVEYARD)
    put(state, 0, "Forest", Zone.LIBRARY)
    state.step = Step.BEGINNING_OF_COMBAT
    run_beginning_of_combat_triggers(state)
    drain(state)
    # Milled a land: instant + land = 2 card types.
    assert effective_power(state, ursine) == 5
    assert "indestructible" in effective_keywords(state, ursine)
    assert ursine.id in forced_attackers(state, 0)
    state.turn_number += 1
    assert ursine.id not in forced_attackers(state, 0)
    # Forced into the attack even if not declared.
    state.turn_number -= 1
    attack(state, 0, [])
    assert ursine.attacking
    assert "random" in eff.describe()


def test_ursine_effect_edges():
    from mtg_bot.effects.generic.cube_creatures_wg import MillChooseOpponentAttackPump

    state = make_state()
    eff = MillChooseOpponentAttackPump(mill=1)
    eff.resolve(state, 0)  # empty library, no source: no crash
    state.players[1].has_lost = True
    ursine = put(state, 0, "Ursine Monstrosity")
    state.resolving_source = ursine
    eff.resolve(state, 0)
    assert ursine.must_attack_turn == -1  # no opponent to attack


def test_okoye_monarch_and_attack_bonus():
    from mtg_bot.effects.generic.cube_creatures_wg import (
        CounterThenWhenItAttacksMonarch,
        DefendingPlayerIsMonarch,
    )
    from mtg_bot.designations import become_monarch
    from mtg_bot.turn import run_beginning_of_combat_triggers

    pr = cube()["Okoye, Mighty and Adored"]
    state = make_state()
    okoye = put(state, 0, pr, Zone.HAND)
    add_lands(state, 0, "Forest", 2)
    add_lands(state, 0, "Plains", 2)
    cast_and_resolve(state, 0, okoye)
    assert state.players[0].is_monarch
    ally = put(state, 0, bear("Ally"))
    state.players[0].agent.scripts["target"] = [("creature", ally.id)]
    state.step = Step.BEGINNING_OF_COMBAT
    run_beginning_of_combat_triggers(state)
    drain(state)
    assert ally.plus_one_counters == 1
    # Attacking a non-monarch: no bonus.
    attack(state, 0, [ally.id])
    assert "double strike" not in effective_keywords(state, ally)
    ally.attacking = False
    ally.tapped = False
    become_monarch(state, 1)
    attack(state, 0, [ally.id])
    assert {"double strike", "trample"} <= effective_keywords(state, ally)
    eff = next(
        t.effect for t in pr.triggered_abilities
        if isinstance(t.effect, CounterThenWhenItAttacksMonarch)
    )
    eff.resolve(state, 0, ())
    assert "monarch" in eff.describe()
    assert not DefendingPlayerIsMonarch().matches(state, {}, okoye)


def test_backup_counters_and_keyword_grant():
    from mtg_bot.cards.parser.creature_wg_lines import parse_wg_creature_line
    from mtg_bot.effects.generic.cube_creatures_wg import (
        Backup,
        GrantKeywordsToObjectUEOT,
    )

    card = {
        "name": "Champion",
        "oracle_text": "Backup 1 (reminder.)\nDouble strike",
    }
    wg = parse_wg_creature_line("Backup 1", card)
    eff = wg.triggers[0].effect
    assert eff == Backup(n=1, keywords=frozenset({"double strike"}), targets=eff.targets)
    assert parse_wg_creature_line(
        "Backup 1", {"name": "C", "oracle_text": "Backup 1\nDraw a card."},
    ) is None
    assert parse_wg_creature_line("Backup 1", {"name": "C", "oracle_text": ""}) is None
    state = make_state()
    champ = put(state, 0, bear("Champion", "{2}{R}", 2, 1))
    ally = put(state, 0, bear("Ally"))
    state.resolving_source = champ
    eff.resolve(state, 0, (("creature", ally.id),))
    assert ally.plus_one_counters == 1
    assert "double strike" in effective_keywords(state, ally)
    eff.resolve(state, 0, (("creature", champ.id),))
    assert champ.plus_one_counters == 1  # itself: counters only
    eff.resolve(state, 0, ())
    state.resolving_source = None
    assert "backup" in eff.describe()
    GrantKeywordsToObjectUEOT(obj_id=999).resolve(state, 0)
    assert "gains" in GrantKeywordsToObjectUEOT().describe()


def test_ocelot_pride_end_step_cat_and_blessing_copies():
    from mtg_bot.creature_statics_wg import apply_ascend
    from mtg_bot.game import gain_life
    from mtg_bot.turn import run_beginning_of_end_step_triggers

    pr = cube()["Ocelot Pride"]
    assert {"first strike", "lifelink", "ascend"} <= pr.keywords
    state = make_state()
    put(state, 0, pr)
    state.step = Step.END
    run_beginning_of_end_step_triggers(state)
    drain(state)
    assert not any(o.printing.name == "Cat" for o in state.battlefield)
    gain_life(state, 0, 1)
    run_beginning_of_end_step_triggers(state)
    drain(state)
    cats = [o for o in state.battlefield if o.printing.name == "Cat"]
    assert len(cats) == 1
    # City's blessing: ten permanents.
    add_lands(state, 0, "Plains", 8)
    apply_ascend(state)
    assert state.players[0].has_citys_blessing
    run_beginning_of_end_step_triggers(state)
    drain(state)
    # A new Cat, then a copy of each token that entered this turn (2 Cats).
    assert sum(o.printing.name == "Cat" for o in state.battlefield) == 4


def test_ascend_needs_ten_permanents_and_an_ascend_source():
    from mtg_bot.creature_statics_wg import apply_ascend

    state = make_state()
    add_lands(state, 0, "Plains", 12)
    apply_ascend(state)
    assert not state.players[0].has_citys_blessing
    put(state, 1, "Ocelot Pride")
    apply_ascend(state)
    assert not state.players[1].has_citys_blessing


def test_elite_spellbinder_taxes_the_exiled_card():
    from mtg_bot.actions import CastSpell
    from mtg_bot.effects.generic.cube_creatures_wg import (
        LookAtHandExileNonlandOwnerMayPlayTaxed,
    )

    pr = cube()["Elite Spellbinder"]
    eff = next(
        t.effect for t in pr.triggered_abilities
        if isinstance(t.effect, LookAtHandExileNonlandOwnerMayPlayTaxed)
    )
    assert eff.surcharge == 2 and "flying" in pr.keywords
    state = make_state()
    sb = put(state, 0, pr, Zone.HAND)
    add_lands(state, 0, "Plains", 3)
    bolt = put(state, 1, "Lightning Bolt", Zone.HAND)
    put(state, 1, "Mountain", Zone.HAND)
    state.players[0].agent.scripts["target"] = [("player", 1)]
    cast_and_resolve(state, 0, sb)
    assert bolt in state.players[1].exile
    # Owner may cast it (sorcery timing, like Lightstall) for {R}+{2}.
    state.active_player_idx = 1
    state.priority_player_idx = 1
    add_lands(state, 1, "Mountain", 2)
    assert CastSpell(bolt.id) not in legal_actions(state, 1)
    add_lands(state, 1, "Mountain", 1)
    assert CastSpell(bolt.id) in legal_actions(state, 1)
    state.players[1].agent.scripts["target"] = [("player", 0)]
    cast_and_resolve(state, 1, bolt)
    assert state.players[0].life == 17
    assert all(
        o.tapped for o in state.battlefield
        if o.printing.name == "Mountain" and o.controller_id == 1
    )
    assert bolt.exile_cast_extra_surcharge == 0


def test_spellbinder_effect_edges():
    from mtg_bot.effects.generic.cube_creatures_wg import (
        LookAtHandExileNonlandOwnerMayPlayTaxed,
    )

    state = make_state()
    eff = LookAtHandExileNonlandOwnerMayPlayTaxed(surcharge=2)
    assert eff.requires_target() and eff.legal_targets(state, 0) == [("player", 1)]
    eff.resolve(state, 0, ())
    land = put(state, 1, "Forest", Zone.HAND)
    eff.resolve(state, 0, (("player", 1),))  # only a land: nothing
    assert land in state.players[1].hand
    put(state, 1, "Lightning Bolt", Zone.HAND)
    state.players[0].agent.scripts["yes_no"] = [False]
    eff.resolve(state, 0, (("player", 1),))
    assert not state.players[1].exile
    assert "{2}" in eff.describe()


def test_figure_of_fable_levels_up():
    from mtg_bot.effects.generic.cube_creatures_wg import BecomeTypesWithBasePT
    from mtg_bot.game import effective_power, effective_subtypes, effective_toughness

    pr = cube()["Figure of Fable"]
    scout, soldier, avatar = (a.effect for a in pr.activated_abilities)
    assert isinstance(avatar, BecomeTypesWithBasePT)
    assert avatar.if_subtype == "Soldier" and avatar.keywords
    state = make_state()
    fig = put(state, 0, pr)
    add_lands(state, 0, "Forest", 6)
    add_lands(state, 0, "Plains", 6)

    def act(i):
        apply_action(state, 0, ActivateAbility(source_id=fig.id, ability_index=i))
        drain(state)

    act(1)  # not a Scout yet: nothing
    assert (effective_power(state, fig), effective_toughness(state, fig)) == (1, 1)
    act(0)
    assert effective_subtypes(state, fig) == ("Kithkin", "Scout")
    assert (effective_power(state, fig), effective_toughness(state, fig)) == (2, 3)
    act(1)
    assert effective_subtypes(state, fig) == ("Kithkin", "Soldier")
    assert (effective_power(state, fig), effective_toughness(state, fig)) == (4, 5)
    act(2)
    assert (effective_power(state, fig), effective_toughness(state, fig)) == (7, 8)
    assert "protection from each of your opponents" in effective_keywords(state, fig)
    assert "Avatar" in avatar.describe()
    state.resolving_source = None
    avatar.resolve(state, 0)


def test_lion_sash_grows_and_reconfigures():
    from mtg_bot.effects.generic.cube_creatures_wg import (
        ExileGraveyardCardCounterIfPermanent,
        ReconfigureAttach,
        ReconfigureUnattach,
    )
    from mtg_bot.game import effective_power, is_creature_now

    pr = cube()["Lion Sash"]
    assert pr.reconfigure_cost_str == "{2}"
    assert pr.equipment_bonus_per_own_counter == ("+1/+1", 1, 1)
    effects = [a.effect for a in pr.activated_abilities]
    exile_idx = next(
        i for i, e in enumerate(effects)
        if isinstance(e, ExileGraveyardCardCounterIfPermanent)
    )
    attach_idx = next(i for i, e in enumerate(effects) if isinstance(e, ReconfigureAttach))
    unattach_idx = next(i for i, e in enumerate(effects) if isinstance(e, ReconfigureUnattach))
    state = make_state()
    sash = put(state, 0, pr)
    add_lands(state, 0, "Plains", 6)
    perm = put(state, 1, "Llanowar Elves", Zone.GRAVEYARD)
    spell = put(state, 1, "Lightning Bolt", Zone.GRAVEYARD)
    agent = state.players[0].agent

    def act(i):
        apply_action(state, 0, ActivateAbility(source_id=sash.id, ability_index=i))
        drain(state)

    agent.scripts["target"] = [("card_in_graveyard", perm.id)]
    act(exile_idx)
    agent.scripts["target"] = [("card_in_graveyard", spell.id)]
    act(exile_idx)
    assert sash.plus_one_counters == 1  # only the permanent card counted
    assert perm in state.players[1].exile and spell in state.players[1].exile
    ally = put(state, 0, bear("Ally"))
    acts = legal_actions(state, 0)
    assert ActivateAbility(source_id=sash.id, ability_index=unattach_idx) not in acts
    agent.scripts["target"] = [("creature", ally.id)]
    act(attach_idx)
    assert sash.attached_to == ally.id and not is_creature_now(sash)
    assert effective_power(state, ally) == 3
    assert ActivateAbility(source_id=sash.id, ability_index=unattach_idx) in legal_actions(state, 0)
    act(unattach_idx)
    assert sash.attached_to is None and is_creature_now(sash)
    # Attached again; the host dying makes it a creature again.
    agent.scripts["target"] = [("creature", ally.id)]
    act(attach_idx)
    from mtg_bot.turn import sacrifice

    sacrifice(state, ally)
    assert sash.attached_to is None and is_creature_now(sash)
    state.resolving_source = sash
    assert ("creature", sash.id) not in ReconfigureAttach().legal_targets(state, 0)
    ReconfigureAttach().resolve(state, 0, (("creature", sash.id),))
    assert sash.attached_to is None
    ExileGraveyardCardCounterIfPermanent().resolve(state, 0, ())
    ReconfigureUnattach().resolve(state, 0)
    state.resolving_source = None
    for e in (ReconfigureAttach(), ReconfigureUnattach(), ExileGraveyardCardCounterIfPermanent()):
        assert e.describe()
