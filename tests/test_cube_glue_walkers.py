"""Cube glue bucket: planeswalkers (Wrenn and Six, Chandra, Tamiyo, ...)
and the emblem-static substrate they need."""

from __future__ import annotations

from mtg_bot.actions import CastSpell, apply_action, resolve_top_of_stack
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.cards.base import make_creature, make_instant, make_sorcery
from mtg_bot.effects.base import StaticAbility, StaticScope
from mtg_bot.effects.generic import DealDamageAnyTarget, DrawCards
from mtg_bot.effects.generic.cube_glue import ReturnTargetGraveyardCardToHand
from mtg_bot.effects.generic.cube_walkers import CreateEmblemWithAbilities
from mtg_bot.game import effective_keywords, effective_power
from mtg_bot.legal import legal_actions
from mtg_bot.turn import destroy

from tests._cube_glue_helpers import (
    activate_loyalty,
    agent,
    arena,
    printing,
    put,
    put_walker,
    to_graveyard,
    to_hand,
)

_BOLT = make_instant("Bolt", "{R}", DealDamageAnyTarget(amount=3))
_DIVINATION = make_sorcery("Divination", "{2}{U}", DrawCards(amount=2))


# ---------------------------------------------------------------------------
# Emblem statics / printing grants (engine substrate)
# ---------------------------------------------------------------------------


def test_emblem_subtype_anthem_pumps_only_your_matching_creatures():
    s = arena()
    ninja = put(s, make_creature("Ninja", "{U}", 1, 1, subtypes=("Ninja",)), 0)
    bear = put(s, make_creature("Bear", "{G}", 2, 2), 0)
    their_ninja = put(
        s, make_creature("Ninja", "{U}", 1, 1, subtypes=("Ninja",)), 1,
    )
    CreateEmblemWithAbilities(static_abilities=(StaticAbility(
        scope=StaticScope.subtype_you_control("Ninja", other=False),
        power_bonus=1, toughness_bonus=1,
    ),)).resolve(s, 0)
    assert effective_power(s, ninja) == 2
    assert effective_power(s, bear) == 2
    assert effective_power(s, their_ninja) == 1


def test_emblem_card_type_keyword_anthem_reaches_noncreature_lands():
    s = arena()
    forest = put(s, BASIC_LANDS["Forest"], 0)
    their_forest = put(s, BASIC_LANDS["Forest"], 1)
    CreateEmblemWithAbilities(static_abilities=(StaticAbility(
        scope=StaticScope.card_type_you_control("Land"),
        granted_keywords=frozenset({"indestructible"}),
    ),)).resolve(s, 0)
    assert "indestructible" in effective_keywords(s, forest)
    assert "indestructible" not in effective_keywords(s, their_forest)
    destroy(s, forest)
    assert forest in s.battlefield
    destroy(s, their_forest)
    assert their_forest not in s.battlefield


def test_card_type_scope_creature_arm():
    s = arena()
    bear = put(s, make_creature("Bear", "{G}", 2, 2), 0)
    rock = put(s, BASIC_LANDS["Island"], 0)
    st = StaticAbility(scope=StaticScope.card_type_you_control("Creature"))
    assert st.applies_to(bear, bear, s)
    assert not st.applies_to(bear, rock, s)


# ---------------------------------------------------------------------------
# Wrenn and Six
# ---------------------------------------------------------------------------


def test_wrenn_and_six_claims_all_three_abilities():
    p = printing("Wrenn and Six")
    assert sorted(a.cost.loyalty for a in p.activated_abilities) == [-1, 1, 7]
    plus = next(a for a in p.activated_abilities if a.cost.loyalty == -1)
    assert isinstance(plus.effect, ReturnTargetGraveyardCardToHand)
    assert plus.effect.target_count_range() == (0, 1)


def test_wrenn_plus_one_returns_a_land_card_only():
    s = arena()
    w6 = put_walker(s, "Wrenn and Six")
    land = to_graveyard(s, BASIC_LANDS["Forest"], 0)
    bolt = to_graveyard(s, _BOLT, 0)
    eff = next(
        a.effect for a in w6.printing.activated_abilities
        if a.cost.loyalty == -1
    )
    assert eff.legal_targets(s, 0) == [("graveyard_card", land.id)]
    agent(s, 0).targets = [("graveyard_card", land.id)]
    activate_loyalty(s, 0, w6, +1)
    assert land in s.players[0].hand
    assert bolt in s.players[0].graveyard
    assert w6.loyalty_counters == 4


def test_wrenn_plus_one_with_no_land_still_activates():
    s = arena()
    w6 = put_walker(s, "Wrenn and Six")
    activate_loyalty(s, 0, w6, +1)
    assert w6.loyalty_counters == 4


def test_wrenn_minus_seven_emblem_grants_retrace_to_instants_and_sorceries():
    s = arena()
    w6 = put_walker(s, "Wrenn and Six")
    w6.loyalty_counters = 7
    activate_loyalty(s, 0, w6, -7)
    assert len(s.emblems) == 1
    div = to_graveyard(s, _DIVINATION, 0)
    creature = to_graveyard(s, make_creature("Bear", "{G}", 2, 2), 0)
    for _ in range(3):
        put(s, BASIC_LANDS["Island"], 0)
    # No land card in hand: no retrace.
    assert not any(
        isinstance(a, CastSpell) and a.card_id == div.id
        for a in legal_actions(s, 0)
    )
    land_card = to_hand(s, BASIC_LANDS["Forest"], 0)
    casts = [
        a for a in legal_actions(s, 0)
        if isinstance(a, CastSpell) and a.card_id in (div.id, creature.id)
    ]
    assert [a.card_id for a in casts] == [div.id]
    assert casts[0].graveyard_permission == "retrace"
    for _ in range(2):
        from tests._cube_glue_helpers import to_library

        to_library(s, BASIC_LANDS["Island"], 0)
    apply_action(s, 0, casts[0])
    assert land_card in s.players[0].graveyard
    resolve_top_of_stack(s)
    assert len(s.players[0].hand) == 2


def test_retrace_grant_is_owner_scoped():
    s = arena()
    w6 = put_walker(s, "Wrenn and Six", 1)
    w6.loyalty_counters = 7
    activate_loyalty(s, 1, w6, -7)
    div = to_graveyard(s, _DIVINATION, 0)
    to_hand(s, BASIC_LANDS["Forest"], 0)
    for _ in range(3):
        put(s, BASIC_LANDS["Island"], 0)
    assert not any(
        isinstance(a, CastSpell) and a.card_id == div.id
        for a in legal_actions(s, 0)
    )


def test_graveyard_return_effect_edges():
    s = arena()
    eff = ReturnTargetGraveyardCardToHand(optional=True)
    assert "up to one" in eff.describe()
    card = to_graveyard(s, _BOLT, 0)
    assert eff.legal_targets(s, 0) == [("graveyard_card", card.id)]
    eff.resolve(s, 0, (("creature", card.id), ("graveyard_card", 999)))
    assert card in s.players[0].graveyard


# ---------------------------------------------------------------------------
# Chandra, Torch of Defiance
# ---------------------------------------------------------------------------

_CHANDRA = "Chandra, Torch of Defiance"


def _chandra_plus_one_index(walker):
    from mtg_bot.effects.generic.cube_glue import ExileTopCardMayCastOtherwise

    return next(
        i for i, a in enumerate(walker.printing.activated_abilities)
        if isinstance(a.effect, ExileTopCardMayCastOtherwise)
    )


def test_chandra_claims_four_abilities():
    p = printing(_CHANDRA)
    assert sorted(a.cost.loyalty for a in p.activated_abilities) == [
        -1, -1, 3, 7,
    ]
    assert not any(a.is_mana_ability for a in p.activated_abilities)


def test_chandra_plus_one_casts_the_exiled_card():
    from tests._cube_glue_helpers import to_library

    s = arena()
    ch = put_walker(s, _CHANDRA)
    put(s, BASIC_LANDS["Mountain"], 0)
    bolt = to_library(s, _BOLT, 0)
    agent(s, 0).targets = [("player", 1)]
    activate_loyalty(s, 0, ch, +1, index=_chandra_plus_one_index(ch))
    assert s.players[1].life == 20  # cast, so no 2 damage
    assert s.stack and s.stack[-1].source is bolt
    resolve_top_of_stack(s)
    assert s.players[1].life == 17


def test_chandra_plus_one_declined_deals_two_and_keeps_card_exiled():
    from tests._cube_glue_helpers import to_library

    s = arena()
    ch = put_walker(s, _CHANDRA)
    put(s, BASIC_LANDS["Mountain"], 0)
    bolt = to_library(s, _BOLT, 0)
    agent(s, 0).yes = False
    activate_loyalty(s, 0, ch, +1, index=_chandra_plus_one_index(ch))
    assert s.players[1].life == 18
    assert bolt in s.players[0].exile
    assert bolt.exile_play_permission is None


def test_chandra_plus_one_land_or_empty_library_deals_two():
    from tests._cube_glue_helpers import to_library

    s = arena()
    ch = put_walker(s, _CHANDRA)
    to_library(s, BASIC_LANDS["Mountain"], 0)
    activate_loyalty(s, 0, ch, +1, index=_chandra_plus_one_index(ch))
    assert s.players[1].life == 18
    s2 = arena()
    ch2 = put_walker(s2, _CHANDRA)
    activate_loyalty(s2, 0, ch2, +1, index=_chandra_plus_one_index(ch2))
    assert s2.players[1].life == 18


def test_chandra_emblem_deals_five_whenever_you_cast_a_spell():
    s = arena()
    ch = put_walker(s, _CHANDRA)
    ch.loyalty_counters = 7
    activate_loyalty(s, 0, ch, -7)
    assert len(s.emblems) == 1
    put(s, BASIC_LANDS["Mountain"], 0)
    to_hand(s, _BOLT, 0)
    agent(s, 0).targets = [("player", 1), ("player", 1)]
    cast = next(a for a in legal_actions(s, 0) if isinstance(a, CastSpell))
    apply_action(s, 0, cast)
    assert len(s.stack) == 2  # the spell + the emblem trigger
    resolve_top_of_stack(s)
    assert s.players[1].life == 15


def test_mid_body_self_name_fallback_only_after_primary_parse():
    from mtg_bot.cards.parser.planeswalker_builder import _parse_loyalty_effect

    # Leading-subject bodies keep the established parse.
    assert _parse_loyalty_effect(
        "Chandra deals 4 damage to target creature.", _CHANDRA,
    ) is not None
    # No mid-body name and no parse: still None.
    assert _parse_loyalty_effect("Frobnicate the widget.", _CHANDRA) is None
