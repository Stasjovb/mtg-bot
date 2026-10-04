"""Cube glue bucket: linked hand-exile (Tidehollow Sculler) and
"until ... leave the battlefield" hand-or-creature exile (Cloak and
Dagger, Entwined)."""

from __future__ import annotations

from mtg_bot.actions import put_into_battlefield, resolve_top_of_stack
from mtg_bot.cards.base import make_creature, make_instant
from mtg_bot.cards.parser.cube_glue_grammar import parse_glue_effect
from mtg_bot.effects.generic.cube_glue import (
    ReturnCardsExiledWithSourceToOwnersHand,
)
from mtg_bot.effects.generic import DealDamageAnyTarget
from mtg_bot.game import Zone
from mtg_bot.turn import sacrifice, state_based_actions

from tests._cube_glue_helpers import arena, printing, to_hand

_BOLT = make_instant("Bolt", "{R}", DealDamageAnyTarget(amount=3))


def _land():
    from mtg_bot.cards import BASIC_LANDS

    return BASIC_LANDS["Mountain"]


def _enter(s, name, pid=0):
    obj = s.new_object(printing(name), pid, Zone.HAND)
    put_into_battlefield(s, obj, controller_id=pid)
    return obj


def test_sculler_parse_shape():
    p = printing("Tidehollow Sculler")
    assert p.is_creature and p.is_artifact
    effects = [t.effect for t in p.triggered_abilities]
    assert type(effects[0]).__name__ == "LinkExiledCardsToSource"
    assert effects[0].inner.destination == "exile"
    assert isinstance(effects[1], ReturnCardsExiledWithSourceToOwnersHand)
    assert parse_glue_effect(
        "return the exiled cards to their owners' hands"
    ) is not None
    assert parse_glue_effect("return the exiled card to your hand") is None


def test_sculler_exiles_nonland_and_returns_it_when_it_leaves():
    s = arena()
    bolt = to_hand(s, _BOLT, 1)
    land = to_hand(s, _land(), 1)
    sculler = _enter(s, "Tidehollow Sculler")
    assert s.stack[-1].targets == (("player", 1),)
    resolve_top_of_stack(s)
    assert bolt in s.players[1].exile and bolt.zone == Zone.EXILE
    assert land in s.players[1].hand
    sacrifice(s, sculler)
    resolve_top_of_stack(s)
    state_based_actions(s)
    assert bolt in s.players[1].hand and bolt.zone == Zone.HAND
    assert bolt not in s.players[1].exile


def test_sculler_leaving_in_response_exiles_the_card_forever():
    s = arena()
    bolt = to_hand(s, _BOLT, 1)
    sculler = _enter(s, "Tidehollow Sculler")
    sacrifice(s, sculler)  # in response to the ETB trigger
    resolve_top_of_stack(s)  # leaves trigger: nothing exiled yet
    resolve_top_of_stack(s)  # ETB: exile the card
    assert bolt in s.players[1].exile
    # A new Sculler incarnation doesn't return the old one's card.
    sculler2 = s.players[0].graveyard[-1]
    s.players[0].graveyard.remove(sculler2)
    put_into_battlefield(s, sculler2, controller_id=0)
    resolve_top_of_stack(s)  # ETB with an empty (nonland) hand
    sacrifice(s, sculler2)
    resolve_top_of_stack(s)
    assert bolt in s.players[1].exile


def test_sculler_whiffs_on_all_land_hand():
    s = arena()
    land = to_hand(s, _land(), 1)
    sculler = _enter(s, "Tidehollow Sculler")
    resolve_top_of_stack(s)
    assert land in s.players[1].hand
    sacrifice(s, sculler)
    resolve_top_of_stack(s)
    assert land in s.players[1].hand


def test_return_exiled_effect_without_source_is_noop():
    s = arena()
    s.resolving_source = None
    ReturnCardsExiledWithSourceToOwnersHand().resolve(s, 0)
    assert "return the exiled card" in (
        ReturnCardsExiledWithSourceToOwnersHand().describe()
    )


def test_reveal_choose_exile_describe():
    eff = printing("Tidehollow Sculler").triggered_abilities[0].effect.inner
    assert "exile that card" in eff.describe()
    assert eff.links_exiled_cards
    assert make_creature  # imported for later tests


# ---------------------------------------------------------------------------
# Cloak and Dagger, Entwined
# ---------------------------------------------------------------------------

_CD = "Cloak and Dagger, Entwined"


def _bear(s, pid=1):
    from tests._cube_glue_helpers import put

    return put(s, make_creature("Bear", "{1}{G}", 2, 2), pid)


def test_plural_self_name_verbs_are_normalized():
    from mtg_bot.cards.parser.triggers import _substitute_self_name

    assert _substitute_self_name(
        "When Cloak and Dagger enter, x", _CD,
    ) == "When this creature enters, x"
    assert _substitute_self_name(
        "until Cloak and Dagger leave the battlefield", _CD,
    ) == "until this creature leaves the battlefield"


def test_cloak_and_dagger_parse_shape():
    p = printing(_CD)
    assert {"deathtouch", "lifelink"} <= set(p.keywords)
    eff = p.triggered_abilities[0].effect
    assert eff.target_slot_kinds() == ("player", "creature")
    assert eff.target_count_range() == (1, 2)


def test_cloak_and_dagger_exiles_hand_card_until_it_leaves():
    from tests._cube_glue_helpers import agent

    s = arena()
    bolt = to_hand(s, _BOLT, 1)
    bear = _bear(s)
    a = agent(s, 0)
    a.targets = [("player", 1), ("creature", bear.id)]
    a.library_pick = bolt.id
    cd = _enter(s, _CD)
    assert s.stack[-1].targets == (("player", 1), ("creature", bear.id))
    resolve_top_of_stack(s)
    assert bolt in s.players[1].exile
    assert bear in s.battlefield
    sacrifice(s, cd)
    assert bolt in s.players[1].hand


def test_cloak_and_dagger_exiles_the_chosen_creature_until_it_leaves():
    from tests._cube_glue_helpers import agent

    s = arena()
    to_hand(s, _BOLT, 1)
    bear = _bear(s)
    a = agent(s, 0)
    a.targets = [("player", 1), ("creature", bear.id)]
    a.library_pick = bear.id
    cd = _enter(s, _CD)
    resolve_top_of_stack(s)
    assert bear not in s.battlefield and bear in s.players[1].exile
    sacrifice(s, cd)
    assert any(o.id == bear.id for o in s.battlefield)


def test_cloak_and_dagger_may_decline_and_needs_its_source():
    from tests._cube_glue_helpers import agent

    s = arena()
    bolt = to_hand(s, _BOLT, 1)
    agent(s, 0).yes = False
    _enter(s, _CD)
    resolve_top_of_stack(s)
    assert bolt in s.players[1].hand
    # Source gone before resolution: nothing is exiled (CR 610.3c).
    s2 = arena()
    bolt2 = to_hand(s2, _BOLT, 1)
    cd2 = _enter(s2, _CD)
    sacrifice(s2, cd2)
    resolve_top_of_stack(s2)
    assert bolt2 in s2.players[1].hand


def test_cloak_and_dagger_with_no_options_does_nothing():
    s = arena()
    to_hand(s, _land(), 1)
    _enter(s, _CD)
    resolve_top_of_stack(s)
    assert s.players[1].exile == []
    eff = printing(_CD).triggered_abilities[0].effect
    assert "reveal their hand" in eff.describe()
    s.resolving_source = None
    eff.resolve(s, 0, ())  # no opponent target: no-op
