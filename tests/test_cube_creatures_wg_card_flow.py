"""Cube W/G creatures: Bejeweled Warg (subtype target noun), Auriok
Salvagers, Formidable Speaker, Stoneforge Mystic, Loran of the Third
Path's draw ability."""

from __future__ import annotations

import pytest

from mtg_bot.actions import ActivateAbility, apply_action
from mtg_bot.cards.parser.card_flow_grammar import parse_card_descriptor
from mtg_bot.cards.parser.creature_wg_effects import parse_wg_effect
from mtg_bot.cards.parser.effects_ext import parse_target_noun_phrase
from mtg_bot.effects.combinators import IfYouDo, MayDo
from mtg_bot.effects.generic.card_flow import CardFilter
from mtg_bot.effects.generic.cube_creatures_wg import (
    PutCardFromHandOntoBattlefield,
    YouAndTargetOpponentEachDraw,
)
from mtg_bot.effects.generic.graveyard import ReturnFromGraveyard
from mtg_bot.effects.object_predicates import HasSubtype
from mtg_bot.game import Zone
from mtg_bot.alt_casting import permanent_matches_filter
from tests._wg_helpers import (
    add_lands,
    bear,
    cast_and_resolve,
    cube,
    drain,
    make_state,
    put,
)


def _activate(state, pid, obj, idx=0):
    apply_action(state, pid, ActivateAbility(source_id=obj.id, ability_index=idx))
    drain(state)


def test_subtype_target_nouns():
    pred = parse_target_noun_phrase("Wolf you control")
    assert pred is not None
    state = make_state()
    wolf = put(state, 0, bear("Wolf Pup", subtypes=("Wolf",)))
    other = put(state, 0, bear("Not A Wolf"))
    state.resolving_controller_id = 0
    assert pred.test(wolf, state) and not pred.test(other, state)
    assert isinstance(parse_target_noun_phrase("Equipment"), HasSubtype)
    assert parse_target_noun_phrase("wolf") is None


def test_bejeweled_warg_modes():
    pr = cube()["Bejeweled Warg"]
    trig = pr.triggered_abilities[0]
    modes = trig.effect.modes
    assert len(modes) == 2
    state = make_state()
    warg = put(state, 0, pr)
    state.resolving_source = warg
    assert ("creature", warg.id) in modes[0].legal_targets(state, 0)
    state.resolving_source = None


def test_card_descriptor_subtypes():
    f = parse_card_descriptor("an Equipment card")
    assert f == CardFilter(subtype="Equipment")
    assert f.has_quality and "Equipment" in f.describe()
    g = parse_card_descriptor("an Equipment card with mana value 2 or less")
    assert g.subtype == "Equipment" and g.max_mv == 2
    assert parse_card_descriptor("an Equipment Aura card") is None
    state = make_state()
    wolf = put(state, 0, bear("Wolf Pup", subtypes=("Wolf",)))
    assert permanent_matches_filter(state, wolf, CardFilter(subtype="Wolf"))
    assert not permanent_matches_filter(state, wolf, CardFilter(subtype="Cat"))


def test_auriok_salvagers_returns_cheap_artifact():
    pr = cube()["Auriok Salvagers"]
    eff = pr.activated_abilities[0].effect
    assert isinstance(eff, ReturnFromGraveyard) and eff.artifact and eff.max_mv == 1
    state = make_state()
    salv = put(state, 0, pr)
    add_lands(state, 0, "Plains", 2)
    cheap = put(state, 0, "Sol Ring", Zone.GRAVEYARD)
    put(state, 0, "Grim Monolith", Zone.GRAVEYARD)
    _activate(state, 0, salv)
    assert cheap in state.players[0].hand
    assert parse_wg_effect(
        "return target artifact card with mana value 0 or less from your "
        "graveyard to your hand"
    ) is None


def test_formidable_speaker_discard_to_tutor():
    pr = cube()["Formidable Speaker"]
    etb = pr.triggered_abilities[0].effect
    assert isinstance(etb, IfYouDo) and isinstance(etb.do_action, MayDo)
    state = make_state()
    speaker = put(state, 0, pr, Zone.HAND)
    add_lands(state, 0, "Forest", 3)
    junk = put(state, 0, "Forest", Zone.HAND)
    target = put(state, 0, "Llanowar Elves", Zone.LIBRARY)
    put(state, 0, "Forest", Zone.LIBRARY)
    cast_and_resolve(state, 0, speaker)
    p = state.players[0]
    assert junk in p.graveyard and target in p.hand


def test_formidable_speaker_untaps_another_permanent():
    state = make_state()
    speaker = put(state, 0, "Formidable Speaker")
    land = put(state, 0, "Forest")
    add_lands(state, 0, "Forest", 1)
    land.tapped = True
    state.players[0].agent.scripts["target"] = [("permanent", land.id)]
    _activate(state, 0, speaker)
    assert not land.tapped and speaker.tapped


def test_stoneforge_tutors_and_puts_equipment():
    pr = cube()["Stoneforge Mystic"]
    state = make_state()
    sfm = put(state, 0, pr, Zone.HAND)
    add_lands(state, 0, "Plains", 4)
    put(state, 0, "Llanowar Elves", Zone.LIBRARY)
    equip = put(state, 0, "Skullclamp", Zone.LIBRARY)
    cast_and_resolve(state, 0, sfm)
    p = state.players[0]
    assert equip in p.hand
    sfm.summoning_sick = False
    for land in state.battlefield:
        land.tapped = False
    _activate(state, 0, sfm)
    assert equip in state.battlefield
    eff = pr.activated_abilities[0].effect
    assert isinstance(eff, MayDo)
    assert isinstance(eff.inner, PutCardFromHandOntoBattlefield)


def test_put_from_hand_edges():
    state = make_state()
    eff = PutCardFromHandOntoBattlefield(card_filter=CardFilter(subtype="Equipment"))
    assert eff.resolve(state, 0) is False  # nothing matching
    card = put(state, 0, "Skullclamp", Zone.HAND)
    state.players[0].agent.scripts["library"] = [None]
    assert eff.resolve(state, 0) is False  # declined
    forced = PutCardFromHandOntoBattlefield(
        card_filter=CardFilter(subtype="Equipment"), optional=False, tapped=True,
    )
    state.players[0].agent.scripts["library"] = [None]
    assert forced.resolve(state, 0) is True
    assert card in state.battlefield and card.tapped
    assert "you may put" in eff.describe()
    assert parse_wg_effect(
        "put a creature card from your hand onto the battlefield tapped"
    ).tapped


def test_loran_you_and_target_opponent_draw():
    pr = cube()["Loran of the Third Path"]
    ab = pr.activated_abilities[0]
    assert ab.cost.tap_self and isinstance(ab.effect, YouAndTargetOpponentEachDraw)
    state = make_state()
    loran = put(state, 0, pr)
    for pid in (0, 1):
        put(state, pid, "Forest", Zone.LIBRARY)
    _activate(state, 0, loran)
    assert len(state.players[0].hand) == 1 and len(state.players[1].hand) == 1
    assert ab.effect.legal_targets(state, 0) == [("player", 1)]
    ab.effect.resolve(state, 0, ())
    assert "each draw" in ab.effect.describe()
    assert parse_wg_effect("you and target opponent each draw two cards").amount == 2
    assert parse_wg_effect("you and target opponent each draw 3 cards").amount == 3


def test_loran_etb_destroys_up_to_one_artifact_or_enchantment():
    state = make_state()
    loran = put(state, 0, "Loran of the Third Path", Zone.HAND)
    add_lands(state, 0, "Plains", 3)
    rock = put(state, 1, "Sol Ring")
    cast_and_resolve(state, 0, loran)
    assert rock in state.players[1].graveyard


def test_epithet_self_name_substitution():
    from mtg_bot.cards.parser.triggers import _substitute_self_name

    name = "Loran of the Third Path"
    assert _substitute_self_name("When Loran enters, draw.", name) == (
        "When this creature enters, draw."
    )
    # Another "<X> of ..." card name stays intact.
    assert _substitute_self_name(
        "Loran of Somewhere else", "Loran of the Third Path",
    ) == "Loran of Somewhere else"


def test_eoe_pinned_printing_keeps_pre_bucket_grammar():
    from mtg_bot.cards.parser.creature_wg_effects import (
        EOE_PINNED_NAMES,
        wg_grammar_disabled,
        wg_grammar_pinned_off,
    )
    from mtg_bot.cards.parser.source import OracleParserCardSource

    assert "Kona, Rescue Beastie" in EOE_PINNED_NAMES
    assert "Kona, Rescue Beastie" not in OracleParserCardSource(pool="eoe").claimed_names
    with wg_grammar_pinned_off("Kona, Rescue Beastie"):
        assert wg_grammar_disabled()
        assert parse_wg_effect(
            "put a creature card from your hand onto the battlefield"
        ) is None
    assert not wg_grammar_disabled()
