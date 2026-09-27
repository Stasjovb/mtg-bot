"""Cube W/G creatures: linked exile (Skyclave Apparition), exile until an
opponent becomes the monarch (Palace Jailer) and flicker until the next
end step (Flickerwisp, Phelia)."""

from __future__ import annotations

from mtg_bot.cards.parser.creature_wg_effects import parse_wg_effect
from mtg_bot.cards.parser.creature_wg_lines import link_exile_abilities
from mtg_bot.designations import become_monarch
from mtg_bot.effects.generic.cube_creatures_wg import (
    ExiledCardOwnerCreatesManaValueToken,
    ExileTargetReturnAtNextEndStep,
    ExileUntilOpponentBecomesMonarch,
    LinkExiledCardsToSource,
    ReturnExiledCardToBattlefield,
    cards_exiled_with,
    release_exiled_until_opponent_monarch,
)
from mtg_bot.effects.generic.exile import Exile
from mtg_bot.effects.generic.keyword_actions import BecomeMonarch
from mtg_bot.game import Zone
from mtg_bot.turn import move_off_battlefield, sacrifice
from tests._wg_helpers import (
    add_lands,
    attack,
    bear,
    cast_and_resolve,
    cube,
    drain,
    end_step,
    make_state,
    put,
)


# ---------------------------------------------------------------------
# Skyclave Apparition
# ---------------------------------------------------------------------


def test_skyclave_printing_links_its_exile():
    pr = cube()["Skyclave Apparition"]
    etb, ltb = pr.triggered_abilities
    assert isinstance(etb.effect, LinkExiledCardsToSource)
    assert isinstance(etb.effect.inner, Exile)
    assert etb.effect.target_count_range() == (0, 1)
    assert etb.effect.targets == etb.effect.inner.targets
    assert isinstance(ltb.effect, ExiledCardOwnerCreatesManaValueToken)
    assert (ltb.effect.color, ltb.effect.subtype) == ("U", "Illusion")


def test_skyclave_exiles_then_owner_gets_illusion_when_it_leaves():
    state = make_state()
    sky = put(state, 0, "Skyclave Apparition", Zone.HAND)
    add_lands(state, 0, "Plains", 3)
    victim = put(state, 1, bear("Two Drop", "{1}{G}"))
    big = put(state, 1, bear("Five Drop", "{4}{G}", 5, 5))
    state.players[0].agent.scripts["target"] = [("creature", victim.id)]
    cast_and_resolve(state, 0, sky)
    assert victim in state.players[1].exile
    assert big in state.battlefield
    assert cards_exiled_with(state, sky) == [victim]
    sacrifice(state, sky)
    drain(state)
    tokens = [o for o in state.battlefield if o.printing.name == "Illusion"]
    assert len(tokens) == 1
    tok = tokens[0]
    assert tok.controller_id == 1 and tok.owner_id == 1
    assert (tok.printing.power, tok.printing.toughness) == (2, 2)
    assert tok.printing.color_indicator == frozenset({"U"})
    assert victim.exiled_with == ()


def test_skyclave_cannot_target_big_or_own_permanents():
    state = make_state()
    sky = put(state, 0, "Skyclave Apparition", Zone.HAND)
    add_lands(state, 0, "Plains", 3)
    put(state, 1, bear("Five Drop", "{4}{G}", 5, 5))
    mine = put(state, 0, bear("Mine", "{G}"))
    cast_and_resolve(state, 0, sky)
    assert mine in state.battlefield
    assert cards_exiled_with(state, sky) == []


def test_link_is_per_incarnation():
    state = make_state()
    sky = put(state, 0, "Skyclave Apparition")
    other = put(state, 1, bear("Two Drop", "{1}{G}"))
    state.resolving_source = sky
    LinkExiledCardsToSource(Exile()).resolve(state, 0, ())
    move_off_battlefield(state, other, destination="exile")
    assert cards_exiled_with(state, sky) == []
    other.exiled_with = (sky.id, sky.etb_timestamp + 1)
    assert cards_exiled_with(state, sky) == []
    eff = ExiledCardOwnerCreatesManaValueToken()
    eff.resolve(state, 0)
    state.resolving_source = None
    eff.resolve(state, 0)
    assert "X/X" in eff.describe()
    assert LinkExiledCardsToSource(Exile()).describe().startswith("exile")
    assert LinkExiledCardsToSource(Exile()).target_slot_kinds() == ()
    assert not LinkExiledCardsToSource(Exile()).requires_target()


def test_link_exile_abilities_leaves_unlinked_cards_alone():
    from mtg_bot.effects.base import TriggeredAbility

    t = TriggeredAbility(effect=Exile())
    triggers = [t]
    link_exile_abilities(triggers, [], [])
    assert triggers == [t]


# ---------------------------------------------------------------------
# Palace Jailer
# ---------------------------------------------------------------------


def test_palace_jailer_shape():
    pr = cube()["Palace Jailer"]
    effects = [t.effect for t in pr.triggered_abilities]
    assert any(isinstance(e, BecomeMonarch) for e in effects)
    jail = next(e for e in effects if isinstance(e, ExileUntilOpponentBecomesMonarch))
    assert jail.targets[0].count_min == 1
    assert "monarch" in jail.describe()


def test_palace_jailer_exile_ends_when_an_opponent_becomes_monarch():
    state = make_state()
    jailer = put(state, 0, "Palace Jailer", Zone.HAND)
    add_lands(state, 0, "Plains", 4)
    victim = put(state, 1, bear("Victim"))
    victim.plus_one_counters = 2
    cast_and_resolve(state, 0, jailer)
    assert state.players[0].is_monarch
    assert victim in state.players[1].exile
    # The source leaving doesn't end the exile.
    sacrifice(state, jailer)
    assert victim in state.players[1].exile
    # Becoming the monarch again yourself doesn't either.
    become_monarch(state, 0)
    assert victim in state.players[1].exile
    become_monarch(state, 1)
    assert victim in state.battlefield
    assert victim.controller_id == 1 and victim.plus_one_counters == 0
    assert victim.exiled_until_opponent_monarch_of is None


def test_release_ignores_unmarked_and_own_monarchy():
    state = make_state()
    card = put(state, 1, bear("Plain Exile"), Zone.EXILE)
    marked = put(state, 1, bear("Marked"), Zone.EXILE)
    marked.exiled_until_opponent_monarch_of = 1
    release_exiled_until_opponent_monarch(state, 1)
    assert card in state.players[1].exile and marked in state.players[1].exile


def test_jailer_fizzles_on_illegal_target():
    state = make_state()
    victim = put(state, 1, bear("Victim"))
    eff = parse_wg_effect(
        "exile target creature an opponent controls until an opponent "
        "becomes the monarch"
    )
    move_off_battlefield(state, victim, destination="graveyard")
    eff.resolve(state, 0, (("creature", victim.id),))
    assert victim in state.players[1].graveyard


# ---------------------------------------------------------------------
# Flickerwisp / Phelia
# ---------------------------------------------------------------------


def test_flickerwisp_returns_card_at_next_end_step():
    pr = cube()["Flickerwisp"]
    flick = next(
        t.effect for t in pr.triggered_abilities
        if isinstance(t.effect, ExileTargetReturnAtNextEndStep)
    )
    assert not flick.counter_on_source_if_yours
    assert flick.targets[0].count_min == 1
    state = make_state()
    wisp = put(state, 0, "Flickerwisp", Zone.HAND)
    add_lands(state, 0, "Plains", 3)
    land = put(state, 1, "Forest")
    land.tapped = True
    state.players[0].agent.scripts["target"] = [("permanent", land.id)]
    cast_and_resolve(state, 0, wisp)
    assert land in state.players[1].exile
    end_step(state)
    assert land in state.battlefield and not land.tapped
    assert land.controller_id == 1


def test_flickerwisp_cannot_target_itself_and_tokens_dont_return():
    state = make_state()
    wisp = put(state, 0, "Flickerwisp")
    eff = next(
        t.effect for t in wisp.printing.triggered_abilities
        if isinstance(t.effect, ExileTargetReturnAtNextEndStep)
    )
    from mtg_bot.cards.base import make_token_creature

    tok = put(state, 1, make_token_creature("Spirit", 1, 1, subtypes=("Spirit",)))
    state.resolving_source = wisp
    legal = eff.legal_targets(state, 0)
    assert ("creature", wisp.id) not in legal
    assert ("creature", tok.id) in legal
    eff.resolve(state, 0, (("creature", tok.id),))
    state.resolving_source = None
    assert state.delayed_triggers == []
    assert "next end step" in eff.describe()


def test_phelia_flickers_on_attack_and_grows_for_own_permanent():
    pr = cube()["Phelia, Exuberant Shepherd"]
    assert "flash" in pr.keywords
    flick = pr.triggered_abilities[0].effect
    assert flick.counter_on_source_if_yours and flick.targets[0].count_min == 0
    state = make_state()
    phelia = put(state, 0, pr)
    mine = put(state, 0, bear("Mine"))
    mine.plus_one_counters = 1
    state.players[0].agent.scripts["target"] = [("creature", mine.id)]
    attack(state, 0, [phelia.id])
    assert mine in state.players[0].exile
    end_step(state)
    assert mine in state.battlefield and mine.plus_one_counters == 0
    assert phelia.plus_one_counters == 1


def test_phelia_no_counter_for_opponents_permanent_or_missing_phelia():
    state = make_state()
    phelia = put(state, 0, "Phelia, Exuberant Shepherd")
    theirs = put(state, 1, bear("Theirs"), Zone.EXILE)
    ReturnExiledCardToBattlefield(card_id=theirs.id, counter_on_id=phelia.id).resolve(
        state, 0,
    )
    assert theirs in state.battlefield and phelia.plus_one_counters == 0
    mine = put(state, 0, bear("Mine"), Zone.EXILE)
    ReturnExiledCardToBattlefield(card_id=mine.id, counter_on_id=999).resolve(state, 0)
    assert mine in state.battlefield
    # Card already gone: nothing happens.
    ReturnExiledCardToBattlefield(card_id=12345).resolve(state, 0)
    assert "return" in ReturnExiledCardToBattlefield().describe()


def test_flicker_fizzles_when_target_gone():
    state = make_state()
    wisp = put(state, 0, "Flickerwisp")
    other = put(state, 1, bear("Other"))
    eff = parse_wg_effect(
        "exile another target permanent. Return that card to the battlefield "
        "under its owner's control at the beginning of the next end step"
    )
    sacrifice(state, other)
    state.resolving_source = wisp
    eff.resolve(state, 0, (("creature", other.id),))
    state.resolving_source = None
    assert state.delayed_triggers == []


def test_wg_effect_grammar_rejects_unknown_nouns():
    assert parse_wg_effect(
        "exile target wombat until an opponent becomes the monarch"
    ) is None
    assert parse_wg_effect(
        "exile another target wombat. Return that card to the battlefield "
        "under its owner's control at the beginning of the next end step"
    ) is None
    assert parse_wg_effect("do a little dance") is None


def test_removal_grammar_other_target_excludes_source():
    from mtg_bot.cards.parser.removal_phrases import parse_targeted_removal
    from mtg_bot.effects.object_predicates import IsSource

    eff = parse_targeted_removal("destroy another target creature")
    assert eff.target_filter.right == ~IsSource()
    eff = parse_targeted_removal(
        "exile up to one other target creature. That creature's controller "
        "gains life equal to its power"
    )
    assert eff.count_min == 0 and eff.rider is not None
