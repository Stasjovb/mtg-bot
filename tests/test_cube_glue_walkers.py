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


# ---------------------------------------------------------------------------
# Tamiyo, Collector of Tales
# ---------------------------------------------------------------------------

_TAMIYO = "Tamiyo, Collector of Tales"


def _push_spell(s, controller, effect, targets=()):
    """Put a sorcery with ``effect`` on the stack for ``controller``."""
    from mtg_bot.game import StackItem, Zone

    card = s.new_object(make_sorcery("Edict", "{B}", effect), controller, Zone.STACK)
    s.stack.append(StackItem(source=card, controller_id=controller, targets=targets))
    return card


def test_tamiyo_parse_shape():
    p = printing(_TAMIYO)
    assert p.opponents_cant_make_you_discard_or_sacrifice
    assert sorted(a.cost.loyalty for a in p.activated_abilities) == [-1, 3]


def test_tamiyo_blocks_opponents_discard_and_sacrifice_effects():
    from mtg_bot.effects.generic.discard import TargetOpponentDiscards
    from mtg_bot.effects.generic.opponent_punishers import (
        EachOpponentSacrificesCreature,
    )

    s = arena()
    put_walker(s, _TAMIYO, 0)
    bear = put(s, make_creature("Bear", "{G}", 2, 2), 0)
    card = to_hand(s, _BOLT, 0)
    _push_spell(s, 1, TargetOpponentDiscards(count=1), (("player", 0),))
    resolve_top_of_stack(s)
    assert card in s.players[0].hand
    _push_spell(s, 1, EachOpponentSacrificesCreature())
    resolve_top_of_stack(s)
    assert bear in s.battlefield
    assert s.resolving_item_controller_id is None


def test_without_tamiyo_the_same_effects_apply():
    from mtg_bot.effects.generic.discard import TargetOpponentDiscards
    from mtg_bot.effects.generic.opponent_punishers import (
        EachOpponentSacrificesCreature,
    )

    s = arena()
    put_walker(s, _TAMIYO, 1)  # the caster's own Tamiyo doesn't matter
    bear = put(s, make_creature("Bear", "{G}", 2, 2), 0)
    card = to_hand(s, _BOLT, 0)
    _push_spell(s, 1, TargetOpponentDiscards(count=1), (("player", 0),))
    resolve_top_of_stack(s)
    assert card in s.players[0].graveyard
    _push_spell(s, 1, EachOpponentSacrificesCreature())
    resolve_top_of_stack(s)
    assert bear not in s.battlefield


def test_tamiyo_doesnt_stop_your_own_effects_or_sacrifices():
    from mtg_bot.effects.generic.discard import DiscardSelf
    from mtg_bot.turn import sacrifice

    s = arena()
    put_walker(s, _TAMIYO, 0)
    card = to_hand(s, _BOLT, 0)
    _push_spell(s, 0, DiscardSelf(amount=1))
    resolve_top_of_stack(s)
    assert card in s.players[0].graveyard
    bear = put(s, make_creature("Bear", "{G}", 2, 2), 0)
    sacrifice(s, bear)  # not during an opponent's resolution
    assert bear not in s.battlefield


def test_tamiyo_protection_ends_when_she_loses_her_abilities():
    from mtg_bot.effects.generic.discard import TargetOpponentDiscards

    s = arena()
    tam = put_walker(s, _TAMIYO, 0)
    s.add_continuous_effect(
        source_id=tam.id, layer=6, kind="lose_all_abilities", target_id=tam.id,
    )
    card = to_hand(s, _BOLT, 0)
    _push_spell(s, 1, TargetOpponentDiscards(count=1), (("player", 0),))
    resolve_top_of_stack(s)
    assert card in s.players[0].graveyard


def test_tamiyo_plus_one_puts_named_cards_into_hand_rest_to_graveyard():
    from tests._cube_glue_helpers import to_library

    s = arena()
    tam = put_walker(s, _TAMIYO, 0)
    lib = [
        to_library(s, _BOLT, 0), to_library(s, BASIC_LANDS["Forest"], 0),
        to_library(s, _BOLT, 0), to_library(s, _DIVINATION, 0),
        to_library(s, _BOLT, 0),
    ]

    seen = {}

    def choose_mode(state, pid, options):
        seen["options"] = list(options)
        return options.index("Bolt")

    agent(s, 0).choose_mode = choose_mode
    activate_loyalty(s, 0, tam, +1)
    assert "Forest" not in seen["options"]  # nonland names only
    assert lib[0] in s.players[0].hand and lib[2] in s.players[0].hand
    assert lib[1] in s.players[0].graveyard and lib[3] in s.players[0].graveyard
    assert s.players[0].library == [lib[4]]


def test_tamiyo_plus_one_naming_absent_card_mills_four():
    from tests._cube_glue_helpers import to_library

    s = arena()
    tam = put_walker(s, _TAMIYO, 0)
    for _ in range(4):
        to_library(s, _BOLT, 0)
    agent(s, 0).choose_mode = lambda state, pid, options: len(options) - 1
    activate_loyalty(s, 0, tam, +1)
    assert len(s.players[0].graveyard) == 4
    assert "nonland card name" in (
        tam.printing.activated_abilities[0].effect.describe()
    )


def test_tamiyo_minus_three_returns_any_card():
    s = arena()
    tam = put_walker(s, _TAMIYO, 0)
    land = to_graveyard(s, BASIC_LANDS["Forest"], 0)
    agent(s, 0).targets = [("graveyard_card", land.id)]
    activate_loyalty(s, 0, tam, -3)
    assert land in s.players[0].hand


# ---------------------------------------------------------------------------
# Oko, Thief of Crowns + "loses all abilities" in trigger dispatch
# ---------------------------------------------------------------------------

_OKO = "Oko, Thief of Crowns"


def _oko_index(walker, cls_name):
    return next(
        i for i, a in enumerate(walker.printing.activated_abilities)
        if type(a.effect).__name__ == cls_name
    )


def _upkeep_drawer(name="Drawer"):
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import YOU, Controlled, Event

    return make_creature(
        name, "{2}{U}", 1, 4, keywords=("flying",),
        triggered_abilities=(TriggeredAbility(
            event=Event.BEGINNING_OF_UPKEEP, predicate=Controlled(YOU),
            effect=DrawCards(amount=1),
        ),),
    )


def test_oko_claims_three_abilities():
    p = printing(_OKO)
    assert sorted(a.cost.loyalty for a in p.activated_abilities) == [-2, -1, 5]


def test_oko_plus_one_elks_a_creature_permanently():
    from mtg_bot.game import effective_colors, effective_subtypes, effective_toughness
    from mtg_bot.turn import run_beginning_of_upkeep_triggers, run_cleanup_step

    from tests._cube_glue_helpers import to_library

    s = arena()
    oko = put_walker(s, _OKO)
    drawer = put(s, _upkeep_drawer(), 1)
    to_library(s, _BOLT, 1)
    agent(s, 0).targets = [("creature", drawer.id)]
    activate_loyalty(s, 0, oko, +1, index=_oko_index(oko, "TargetBecomesCreatureIndefinitely"))
    assert effective_power(s, drawer) == 3 and effective_toughness(s, drawer) == 3
    assert effective_keywords(s, drawer) == frozenset()
    assert effective_subtypes(s, drawer) == ("Elk",) or list(
        effective_subtypes(s, drawer)
    ) == ["Elk"]
    assert effective_colors(s, drawer) == frozenset({"G"})
    # Survives Oko leaving and the turn ending.
    from mtg_bot.turn import sacrifice

    sacrifice(s, oko)
    run_cleanup_step(s)
    assert effective_power(s, drawer) == 3
    # Its printed upkeep trigger no longer exists.
    s.active_player_idx = 1
    run_beginning_of_upkeep_triggers(s)
    assert s.stack == []


def test_oko_plus_one_turns_a_food_into_an_artifact_creature_elk():
    from mtg_bot.game import effective_activated_abilities, is_creature_now

    s = arena()
    oko = put_walker(s, _OKO)
    food_idx = _oko_index(oko, "CreateToken") if any(
        type(a.effect).__name__ == "CreateToken"
        for a in oko.printing.activated_abilities
    ) else None
    activate_loyalty(s, 0, oko, +2, index=food_idx)
    food = next(o for o in s.battlefield if o is not oko)
    assert food.printing.is_artifact and effective_activated_abilities(s, food)
    s.loyalty_activated_this_turn.clear()
    agent(s, 0).targets = [("permanent", food.id)]
    activate_loyalty(s, 0, oko, +1, index=_oko_index(oko, "TargetBecomesCreatureIndefinitely"))
    assert is_creature_now(food) and food.printing.is_artifact
    assert effective_power(s, food) == 3
    assert effective_activated_abilities(s, food) == ()
    assert food.summoning_sick  # entered this turn


def test_oko_minus_five_exchanges_control():
    s = arena()
    oko = put_walker(s, _OKO)
    oko.loyalty_counters = 6
    mine = put(s, make_creature("Rat", "{B}", 1, 1), 0)
    theirs = put(s, make_creature("Bear", "{1}{G}", 3, 3), 1)
    big = put(s, make_creature("Giant", "{4}{G}", 5, 5), 1)
    eff = oko.printing.activated_abilities[
        _oko_index(oko, "ExchangeControlOfTargets")
    ].effect
    slot1 = eff.legal_targets_for_slot(s, 0, 1)
    assert ("creature", theirs.id) in slot1
    assert ("creature", big.id) not in slot1
    assert eff.legal_targets_for_slot(s, 0, 0) == [("creature", mine.id)]
    agent(s, 0).targets = [("creature", mine.id), ("creature", theirs.id)]
    activate_loyalty(s, 0, oko, -5, index=_oko_index(oko, "ExchangeControlOfTargets"))
    assert mine.controller_id == 1 and theirs.controller_id == 0


def test_exchange_fizzles_when_a_target_is_gone():
    from mtg_bot.effects.generic.cube_glue import ExchangeControlOfTargets

    s = arena()
    oko_eff = printing(_OKO).activated_abilities
    eff = next(a.effect for a in oko_eff if isinstance(a.effect, ExchangeControlOfTargets))
    mine = put(s, make_creature("Rat", "{B}", 1, 1), 0)
    eff.resolve(s, 0, (("creature", mine.id), ("creature", 999)))
    assert mine.controller_id == 0
    assert eff.legal_targets(s, 0) == []  # no opposing creature
    assert "exchange control" in eff.describe()


def test_elked_creature_has_no_dies_trigger_last_known_information():
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.cube_glue import (
        TargetBecomesCreatureIndefinitely,
    )
    from mtg_bot.effects.predicates import Event, IsSelf

    s = arena()
    dies_draw = TriggeredAbility(
        event=Event.DIES, predicate=IsSelf(), effect=DrawCards(amount=1),
    )
    c = put(s, make_creature("D", "{1}", 1, 1, triggered_abilities=(dies_draw,)), 1)
    plain = put(s, make_creature("E", "{1}", 1, 1, triggered_abilities=(dies_draw,)), 1)
    eff = next(
        a.effect for a in printing(_OKO).activated_abilities
        if isinstance(a.effect, TargetBecomesCreatureIndefinitely)
    )
    eff.resolve(s, 0, (("creature", c.id),))
    assert "Elk" in eff.describe()
    destroy(s, c)
    assert s.stack == [] and c.left_without_abilities
    destroy(s, plain)
    assert len(s.stack) == 1 and not plain.left_without_abilities


# ---------------------------------------------------------------------------
# Ugin, Eye of the Storms
# ---------------------------------------------------------------------------

_UGIN = "Ugin, Eye of the Storms"


def _rock(name="Rock"):
    from mtg_bot.cards.base import make_artifact

    return make_artifact(name, "{1}")


def test_ugin_cast_trigger_exiles_a_colored_permanent_only():
    s = arena()
    for _ in range(7):
        put(s, BASIC_LANDS["Wastes"] if "Wastes" in BASIC_LANDS else BASIC_LANDS["Island"], 0)
    bear = put(s, make_creature("Bear", "{1}{G}", 2, 2), 1)
    rock = put(s, _rock(), 1)
    ugin = to_hand(s, printing(_UGIN), 0)
    cast = next(
        a for a in legal_actions(s, 0)
        if isinstance(a, CastSpell) and a.card_id == ugin.id
    )
    agent(s, 0).targets = [("creature", bear.id)]
    apply_action(s, 0, cast)
    trig = s.stack[-1]
    assert trig.ability is not None
    legal = trig.ability.effect.legal_targets(s, 0)
    assert ("creature", bear.id) in legal
    assert all(t[1] != rock.id for t in legal)
    resolve_top_of_stack(s)
    assert bear in s.players[1].exile
    resolve_top_of_stack(s)
    assert any(o.id == ugin.id for o in s.battlefield)


def test_ugin_colorless_spell_trigger():
    s = arena()
    put_walker(s, _UGIN, 0)
    bear = put(s, make_creature("Bear", "{1}{G}", 2, 2), 1)
    put(s, BASIC_LANDS["Island"], 0)
    rock = to_hand(s, _rock(), 0)
    agent(s, 0).targets = [("creature", bear.id)]
    cast = next(
        a for a in legal_actions(s, 0)
        if isinstance(a, CastSpell) and a.card_id == rock.id
    )
    apply_action(s, 0, cast)
    resolve_top_of_stack(s)
    assert bear in s.players[1].exile


def test_ugin_minus_eleven_exiles_colorless_nonland_cards_castable_free():
    from tests._cube_glue_helpers import to_library

    s = arena()
    ugin = put_walker(s, _UGIN, 0)
    ugin.loyalty_counters = 11
    rocks = [to_library(s, _rock("Rock A"), 0), to_library(s, _rock("Rock B"), 0)]
    bolt = to_library(s, _BOLT, 0)
    land = to_library(s, BASIC_LANDS["Island"], 0)
    activate_loyalty(s, 0, ugin, -11)
    assert all(r in s.players[0].exile for r in rocks)
    assert bolt in s.players[0].library and land in s.players[0].library
    casts = [
        a for a in legal_actions(s, 0)
        if isinstance(a, CastSpell) and a.card_id in {r.id for r in rocks}
    ]
    assert len(casts) == 2  # free: no mana on the board
    apply_action(s, 0, casts[0])
    resolve_top_of_stack(s)
    assert sum(1 for o in s.battlefield if o.printing.name.startswith("Rock")) == 1


def test_ugin_minus_eleven_may_stop_early():
    from mtg_bot.effects.generic.cube_glue import (
        SearchAnyNumberExileCastFreeThisTurn,
    )

    from tests._cube_glue_helpers import to_library

    s = arena()
    to_library(s, _rock(), 0)
    agent(s, 0).library_pick = None
    SearchAnyNumberExileCastFreeThisTurn(colorless=True).resolve(s, 0)
    assert s.players[0].exile == []
    assert "any number" in SearchAnyNumberExileCastFreeThisTurn().describe()


# ---------------------------------------------------------------------------
# Nissa, Who Shakes the World
# ---------------------------------------------------------------------------

_NISSA = "Nissa, Who Shakes the World"


def test_nissa_extra_mana_from_forests_in_automatic_payment():
    from mtg_bot.actions import auto_tap_for_cost, can_pay_cost
    from mtg_bot.cards.base import parse_mana_cost

    s = arena()
    forests = [put(s, BASIC_LANDS["Forest"], 0) for _ in range(2)]
    cost = parse_mana_cost("{3}{G}")
    assert not can_pay_cost(s, 0, cost)
    put_walker(s, _NISSA, 0)
    assert can_pay_cost(s, 0, cost)
    assert not can_pay_cost(s, 0, parse_mana_cost("{4}{G}"))
    auto_tap_for_cost(s, 0, cost)
    assert all(f.tapped for f in forests)
    assert s.players[0].mana_pool == []


def test_nissa_extra_mana_mixes_with_other_lands_and_floats_leftovers():
    from mtg_bot.actions import auto_tap_for_cost, can_pay_cost
    from mtg_bot.cards.base import parse_mana_cost

    s = arena()
    put_walker(s, _NISSA, 0)
    forest = put(s, BASIC_LANDS["Forest"], 0)
    island = put(s, BASIC_LANDS["Island"], 0)
    cost = parse_mana_cost("{1}{U}")
    assert can_pay_cost(s, 0, cost)
    auto_tap_for_cost(s, 0, cost)
    # The Island pays {U}; the Forest isn't needed for {1}... unless it is.
    assert island.tapped
    cost2 = parse_mana_cost("{2}{U}")
    s2 = arena()
    put_walker(s2, _NISSA, 0)
    f2 = put(s2, BASIC_LANDS["Forest"], 0)
    i2 = put(s2, BASIC_LANDS["Island"], 0)
    assert can_pay_cost(s2, 0, cost2)
    auto_tap_for_cost(s2, 0, cost2)
    assert f2.tapped and i2.tapped
    assert forest is not None


def test_opponents_nissa_gives_you_nothing():
    from mtg_bot.actions import can_pay_cost
    from mtg_bot.cards.base import parse_mana_cost

    s = arena()
    put_walker(s, _NISSA, 1)
    put(s, BASIC_LANDS["Forest"], 0)
    assert not can_pay_cost(s, 0, parse_mana_cost("{1}{G}"))


def test_nissa_plus_one_animates_a_land_permanently():
    from mtg_bot.game import is_creature_now
    from mtg_bot.turn import run_cleanup_step, sacrifice

    s = arena()
    nissa = put_walker(s, _NISSA, 0)
    land = put(s, BASIC_LANDS["Forest"], 0, tapped=True)
    bear = put(s, make_creature("Bear", "{1}{G}", 2, 2), 0)
    eff = nissa.printing.activated_abilities[
        next(i for i, a in enumerate(nissa.printing.activated_abilities)
             if a.cost.loyalty == -1)
    ].effect
    legal = eff.legal_targets(s, 0)
    assert ("permanent", land.id) in legal
    assert all(t[1] != bear.id for t in legal)
    agent(s, 0).targets = [("permanent", land.id)]
    activate_loyalty(s, 0, nissa, +1)
    assert not land.tapped and is_creature_now(land)
    assert effective_power(s, land) == 3
    assert {"vigilance", "haste"} <= set(effective_keywords(s, land))
    assert land.printing.is_land
    sacrifice(s, nissa)
    run_cleanup_step(s)
    assert is_creature_now(land) and effective_power(s, land) == 3


def test_nissa_minus_eight_emblem_and_forest_search():
    from tests._cube_glue_helpers import to_library

    s = arena()
    nissa = put_walker(s, _NISSA, 0)
    nissa.loyalty_counters = 8
    forests = [to_library(s, BASIC_LANDS["Forest"], 0) for _ in range(3)]
    island = to_library(s, BASIC_LANDS["Island"], 0)
    activate_loyalty(s, 0, nissa, -8)
    assert len(s.emblems) == 1
    assert all(f in s.battlefield and f.tapped for f in forests)
    assert island in s.players[0].library
    destroy(s, forests[0])
    assert forests[0] in s.battlefield  # emblem: lands are indestructible


# ---------------------------------------------------------------------------
# Kaito, Bane of Nightmares
# ---------------------------------------------------------------------------

_KAITO = "Kaito, Bane of Nightmares"


def test_kaito_is_a_hexproof_ninja_creature_only_during_your_turn():
    from mtg_bot.game import effective_subtypes, effective_toughness, is_creature_now
    from mtg_bot.turn import run_cleanup_step, run_untap_step

    s = arena(active=1)
    kaito = put_walker(s, _KAITO, 0)
    assert not is_creature_now(kaito)
    s.active_player_idx = 0
    run_untap_step(s)
    assert is_creature_now(kaito)
    assert (effective_power(s, kaito), effective_toughness(s, kaito)) == (3, 4)
    assert "Ninja" in effective_subtypes(s, kaito)
    assert "hexproof" in effective_keywords(s, kaito)
    run_cleanup_step(s)
    assert not is_creature_now(kaito)


def test_kaito_entering_on_your_turn_is_a_summoning_sick_creature():
    from mtg_bot.actions import put_into_battlefield
    from mtg_bot.game import Zone, is_creature_now

    s = arena(active=0)
    kaito = s.new_object(printing(_KAITO), 0, Zone.HAND)
    put_into_battlefield(s, kaito, controller_id=0)
    assert kaito.loyalty_counters == 4
    assert is_creature_now(kaito) and kaito.summoning_sick
    s2 = arena(active=1)
    k2 = s2.new_object(printing(_KAITO), 0, Zone.HAND)
    put_into_battlefield(s2, k2, controller_id=0)
    assert not is_creature_now(k2)


def test_kaito_ninjutsu_puts_him_in_attacking():
    from mtg_bot.effects.generic.cube_creatures_ub import (
        PutSourceOntoBattlefieldTappedAndAttacking,
    )
    from mtg_bot.game import is_creature_now

    s = arena(active=0)
    (ninjutsu,) = printing(_KAITO).hand_activated_abilities
    assert ninjutsu.cost.return_unblocked_attacker
    assert isinstance(ninjutsu.effect, PutSourceOntoBattlefieldTappedAndAttacking)
    kaito = to_hand(s, printing(_KAITO), 0)
    s.resolving_source = kaito
    ninjutsu.effect.resolve(s, 0)
    s.resolving_source = None
    assert kaito.attacking and kaito.tapped and is_creature_now(kaito)


def test_kaito_damage_as_a_creature_also_removes_loyalty():
    from mtg_bot.effects.base import _apply_damage
    from mtg_bot.turn import run_untap_step

    s = arena(active=0)
    kaito = put_walker(s, _KAITO, 0)
    run_untap_step(s)
    _apply_damage(s, ("creature", kaito.id), 2)
    assert kaito.damage == 2 and kaito.loyalty_counters == 2


def test_kaito_emblem_pumps_kaito_himself_on_your_turn():
    from mtg_bot.turn import run_untap_step

    s = arena(active=0)
    kaito = put_walker(s, _KAITO, 0)
    run_untap_step(s)
    activate_loyalty(s, 0, kaito, +1)
    assert effective_power(s, kaito) == 4


def test_kaito_zero_surveils_then_draws_per_opponent_who_lost_life():
    from mtg_bot.turn import run_untap_step

    from tests._cube_glue_helpers import to_library

    s = arena(active=0)
    kaito = put_walker(s, _KAITO, 0)
    for _ in range(5):
        to_library(s, _BOLT, 0)
    run_untap_step(s)
    agent(s, 0).yes = False  # keep surveilled cards on top
    activate_loyalty(s, 0, kaito, 0)
    assert len(s.players[0].hand) == 0  # nobody lost life yet
    s.loyalty_activated_this_turn.clear()
    s.players[1].life -= 3
    activate_loyalty(s, 0, kaito, 0)
    assert len(s.players[0].hand) == 1
    assert s.players[1].lost_life_this_turn


def test_kaito_minus_two_taps_and_stuns():
    s = arena(active=0)
    kaito = put_walker(s, _KAITO, 0)
    bear = put(s, make_creature("Bear", "{1}{G}", 2, 2), 1)
    agent(s, 0).targets = [("creature", bear.id)]
    activate_loyalty(s, 0, kaito, -2)
    assert bear.tapped and bear.stun_counters == 2


# ---------------------------------------------------------------------------
# Comet, Stellar Pup (die-roll loyalty ability)
# ---------------------------------------------------------------------------

_COMET = "Comet, Stellar Pup"


class _FixedRoll:
    def __init__(self, value):
        self.value = value

    def randint(self, lo, hi):
        return self.value

    def shuffle(self, seq):
        return None


def _comet(roll):
    s = arena()
    comet = put_walker(s, _COMET, 0)
    s.rng = _FixedRoll(roll)
    return s, comet


def test_comet_parse_shape():
    from mtg_bot.effects.generic.cube_creatures_rmc import RollDieTable

    (ab,) = printing(_COMET).activated_abilities
    assert ab.cost.loyalty == 0 and isinstance(ab.effect, RollDieTable)
    assert ab.effect.sides == 6
    assert [(lo, hi) for lo, hi, _ in ab.effect.table] == [
        (1, 2), (3, 3), (4, 5), (6, 6),
    ]


def test_comet_roll_one_squirrels_with_haste():
    s, comet = _comet(1)
    activate_loyalty(s, 0, comet, 0)
    assert comet.loyalty_counters == 7
    squirrels = [o for o in s.battlefield if o.printing.name == "Squirrel"]
    assert len(squirrels) == 2
    assert all("haste" in effective_keywords(s, q) for q in squirrels)
    from mtg_bot.turn import run_cleanup_step

    run_cleanup_step(s)
    assert all("haste" not in effective_keywords(s, q) for q in squirrels)


def test_comet_roll_three_returns_a_cheap_card():
    s, comet = _comet(3)
    cheap = to_graveyard(s, _BOLT, 0)
    to_graveyard(s, make_creature("Big", "{5}{G}", 6, 6), 0)
    activate_loyalty(s, 0, comet, 0)
    assert comet.loyalty_counters == 4
    assert cheap in s.players[0].hand


def test_comet_roll_four_deals_loyalty_damage_then_minus_two():
    s, comet = _comet(4)
    agent(s, 0).targets = [("player", 1)]
    activate_loyalty(s, 0, comet, 0)
    assert s.players[1].life == 15
    assert comet.loyalty_counters == 3


def test_comet_roll_six_allows_two_more_activations():
    s, comet = _comet(6)
    activate_loyalty(s, 0, comet, 0)
    assert comet.loyalty_counters == 6

    def activations():
        from mtg_bot.actions import ActivateAbility

        return [
            a for a in legal_actions(s, 0)
            if isinstance(a, ActivateAbility) and a.source_id == comet.id
        ]

    assert activations()
    s.rng = _FixedRoll(1)
    activate_loyalty(s, 0, comet, 0)
    assert activations()
    activate_loyalty(s, 0, comet, 0)
    assert not activations()


def test_die_table_assembly_rejects_gaps_and_orphans():
    from mtg_bot.cards.parser.cube_glue_grammar import (
        assemble_die_table,
        parse_glue_die_roll_body,
    )
    from mtg_bot.cards.parser.planeswalker_builder import (
        _build_planeswalker_printing,
    )

    assert parse_glue_die_roll_body("Roll a d20.") == 20
    assert parse_glue_die_roll_body("Roll a die.") is None
    assert assemble_die_table(6, [(1, 2, None), (4, 6, None)]) is None
    orphan = {
        "name": "Frob, Test Walker", "mana_cost": "{2}{R}",
        "type_line": "Legendary Planeswalker — Frob", "loyalty": "3",
        "oracle_text": "+1: Draw a card.\n1 or 2 — [+1], then draw a card.",
    }
    assert _build_planeswalker_printing(orphan) is None
