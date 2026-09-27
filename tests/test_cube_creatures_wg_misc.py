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
