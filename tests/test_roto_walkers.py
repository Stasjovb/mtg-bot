"""Vintage Roto P4 grammar (``cards/parser/roto_walkers.py``) and
engine effects (``effects/generic/roto_walkers.py``): behavioral tests
per card -- the claimed printing does what its oracle text says in a
game."""

from __future__ import annotations

from mtg_bot.actions import _activate_ability, drain_stack
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.cards.parser.roto_walkers import (
    parse_roto_effect,
    parse_roto_static_line,
)
from mtg_bot.effects.generic import MayExileThatCardFromYourGraveyard
from mtg_bot.effects.generic.card_flow import discard_card
from mtg_bot.effects.generic.roto_walkers import (
    ExileTopCardsToHandAtYourNextEndStep,
)
from mtg_bot.effects.predicates import Event
from mtg_bot.game import StackItem, Zone
from mtg_bot.simulate import run_step
from mtg_bot.turn import Step
from mtg_bot.cards.base import make_instant
from mtg_bot.effects.generic import DrawCards

from tests._roto_helpers import (
    ScriptedAgent,
    agent,
    arena,
    printing,
    put,
    to_graveyard,
    to_hand,
    to_library,
)


def _library(s, pid=0, n=3):
    return [to_library(s, BASIC_LANDS["Swamp"], pid) for _ in range(n)]


# ---------------------------------------------------------------------------
# Necropotence
# ---------------------------------------------------------------------------


def test_necropotence_parse_shape():
    p = printing("Necropotence")
    (static,) = p.static_abilities
    assert static.skips_your_draw_step
    (trig,) = p.triggered_abilities
    assert trig.event == Event.CARD_DISCARDED
    assert trig.effect == MayExileThatCardFromYourGraveyard(optional=False)
    assert trig.effect.describe() == "exile that card from your graveyard"
    (ability,) = p.activated_abilities
    assert ability.cost.pay_life == 1
    assert ability.effect == ExileTopCardsToHandAtYourNextEndStep(
        count=1, face_down=True,
    )


def test_necropotence_discard_exiles_without_asking():
    s = arena()
    put(s, printing("Necropotence"), 0)
    agent(s, 0).yes = False  # a "may" would be declined
    card = to_hand(s, BASIC_LANDS["Swamp"], 0)
    discard_card(s, s.players[0], card)
    drain_stack(s)
    assert card in s.players[0].exile


def test_necropotence_ignores_opponents_discards():
    s = arena()
    put(s, printing("Necropotence"), 0)
    card = to_hand(s, BASIC_LANDS["Swamp"], 1)
    discard_card(s, s.players[1], card)
    drain_stack(s)
    assert card in s.players[1].graveyard


def test_currency_converter_discard_exile_stays_optional():
    from mtg_bot.cards.parser.source import build_card_record

    from tests._cube_artifact_helpers import cube_card

    converter = build_card_record(cube_card("Currency Converter"))
    (trig,) = converter.triggered_abilities
    assert trig.effect == MayExileThatCardFromYourGraveyard()
    s = arena()
    put(s, converter, 0)
    agent(s, 0).yes = False
    card = to_hand(s, BASIC_LANDS["Swamp"], 0)
    discard_card(s, s.players[0], card)
    drain_stack(s)
    assert card in s.players[0].graveyard


def test_necropotence_pay_life_exiles_face_down_until_end_step():
    s = arena()
    necro = put(s, printing("Necropotence"), 0)
    top, *_ = _library(s)
    _activate_ability(s, 0, necro.id, 0)
    drain_stack(s)
    assert s.players[0].life == 19
    assert top in s.players[0].exile
    assert top.publicly_known_to == frozenset()
    # Necropotence leaving doesn't stop the delayed trigger.
    s.battlefield.remove(necro)
    run_step(s, Step.END)
    assert top in s.players[0].hand


def test_necropotence_activation_in_end_step_waits_a_turn():
    s = arena()
    necro = put(s, printing("Necropotence"), 0)
    s.step = Step.END
    top, *_ = _library(s)
    _activate_ability(s, 0, necro.id, 0)
    drain_stack(s)
    run_step(s, Step.END)  # the trigger point already passed this turn
    assert top in s.players[0].exile
    s.turn_number += 2
    run_step(s, Step.END)
    assert top in s.players[0].hand


def test_exile_top_to_hand_face_up_and_empty_library():
    s = arena()
    eff = ExileTopCardsToHandAtYourNextEndStep(count=2)
    a, b, c = _library(s)
    eff.resolve(s, 0, ())
    assert a in s.players[0].exile and b in s.players[0].exile
    assert 1 in a.publicly_known_to
    assert len(s.delayed_triggers) == 2
    # An empty library exiles what it can.
    ExileTopCardsToHandAtYourNextEndStep(count=3).resolve(s, 0, ())
    assert c in s.players[0].exile and s.players[0].library == []
    assert eff.describe().startswith("exile the top 2 cards of your library")
    assert "face down" in ExileTopCardsToHandAtYourNextEndStep(
        face_down=True,
    ).describe()


def test_roto_grammar_fallbacks_decline_unknown_shapes():
    assert parse_roto_static_line("Skip your untap step.") == ()
    assert parse_roto_effect("exile the top card of your library") is None
    eff = parse_roto_effect(
        "exile the top two cards of your library. Put them into your hand "
        "at the beginning of your next end step"
    )
    assert eff == ExileTopCardsToHandAtYourNextEndStep(count=2)


def test_roto_grammar_is_off_for_eoe_only_printings():
    from mtg_bot.cards.parser.creature_rmc_grammar import rmc_grammar_disabled

    with rmc_grammar_disabled():
        assert parse_roto_static_line("Skip your draw step.") == ()
        assert parse_roto_effect(
            "exile the top card of your library face down. Put that card "
            "into your hand at the beginning of your next end step"
        ) is None


# ---------------------------------------------------------------------------
# Planeswalker infrastructure: "-X" loyalty costs, Compleated
# ---------------------------------------------------------------------------

from mtg_bot.actions import CastSpell, apply_action  # noqa: E402
from mtg_bot.cards.base import make_artifact, make_creature  # noqa: E402
from mtg_bot.effects.generic.roto_walkers import (  # noqa: E402
    AnyGraveyardHasAtLeast,
    EachPlayerDiscards,
    MillTargetPlayerTimesX,
    PutUpToNCardsFromHandOntoBattlefield,
    SeparatePermanentsIntoPilesSacrificeChosen,
    apply_compleated,
    choose_and_pay_loyalty_x,
)
from mtg_bot.legal import legal_actions  # noqa: E402

_BEAR = make_creature("Bear", "{1}{G}", 2, 2)
_RED_BEAR = make_creature("Red Bear", "{R}", 2, 2)
_ROCK = make_artifact("Rock", "{3}")


def _walker(s, name, pid=0, loyalty=None):
    w = put(s, printing(name), pid)
    w.loyalty_counters = printing(name).loyalty if loyalty is None else loyalty
    return w


def _ability_index(walker, *, x=False, loyalty=None):
    for i, ab in enumerate(walker.printing.activated_abilities):
        if x and ab.cost.loyalty_x:
            return i
        if not x and ab.cost.loyalty == loyalty and not ab.cost.loyalty_x:
            return i
    raise AssertionError("no such ability")


def test_loyalty_x_choice_is_capped_by_loyalty():
    s = arena()
    jace = _walker(s, "Jace, the Perfected Mind", loyalty=4)
    agent(s, 0).x_value = 9
    assert choose_and_pay_loyalty_x(s, 0, jace) == 4
    assert jace.loyalty_counters == 0
    s.players[0].agent = None
    jace.loyalty_counters = 3
    assert choose_and_pay_loyalty_x(s, 0, jace) == 0
    assert jace.loyalty_counters == 3


def test_jace_minus_x_mills_three_times_x():
    s = arena()
    jace = _walker(s, "Jace, the Perfected Mind", loyalty=5)
    _library(s, pid=1, n=10)
    agent(s, 0).x_value = 2
    agent(s, 0).targets = [("player", 1)]
    _activate_ability(s, 0, jace.id, _ability_index(jace, x=True))
    assert jace.loyalty_counters == 3
    drain_stack(s)
    assert len(s.players[1].graveyard) == 6
    assert MillTargetPlayerTimesX(per_x=3).describe() == (
        "target player mills 3 times X cards"
    )
    assert MillTargetPlayerTimesX().describe() == "target player mills X cards"


def test_minus_x_ability_offered_even_at_zero_loyalty():
    s = arena()
    jace = _walker(s, "Jace, the Perfected Mind", loyalty=0)
    idx = _ability_index(jace, x=True)
    acts = legal_actions(s, 0)
    assert any(
        getattr(a, "source_id", None) == jace.id
        and getattr(a, "ability_index", None) == idx
        for a in acts
    )


def test_jace_parse_shape_and_compleated_keyword():
    p = printing("Jace, the Perfected Mind")
    assert "compleated" in p.keywords
    plus, minus2, minus_x = p.activated_abilities
    assert plus.cost.loyalty == -1 and plus.effect.power == -3
    assert plus.effect.target_count_range() == (0, 1)
    assert minus_x.cost.loyalty_x and minus_x.sorcery_speed
    assert minus_x.effect == MillTargetPlayerTimesX(per_x=3)
    first, branch = minus2.effect.effects
    assert branch.condition == AnyGraveyardHasAtLeast(n=20)


def test_jace_plus_one_shrinks_until_your_next_turn():
    from mtg_bot.game import effective_power

    s = arena()
    jace = _walker(s, "Jace, the Perfected Mind")
    bear = put(s, _BEAR, 1)
    agent(s, 0).targets = [("creature", bear.id)]
    _activate_ability(s, 0, jace.id, _ability_index(jace, loyalty=-1))
    drain_stack(s)
    assert jace.loyalty_counters == 6
    assert effective_power(s, bear) == -1
    s.expire_continuous_effects("cleanup")
    assert effective_power(s, bear) == -1  # survives the end of turn
    s.expire_continuous_effects("controller_untap", player_id=0)
    assert effective_power(s, bear) == 2


def test_jace_minus_two_draws_three_when_a_graveyard_is_big():
    s = arena()
    jace = _walker(s, "Jace, the Perfected Mind")
    _library(s, pid=0, n=5)
    _library(s, pid=1, n=5)
    for _ in range(18):
        s.players[1].graveyard.append(
            s.new_object(BASIC_LANDS["Swamp"], owner_id=1, zone=Zone.GRAVEYARD)
        )
    agent(s, 0).targets = [("player", 1)]
    _activate_ability(s, 0, jace.id, _ability_index(jace, loyalty=2))
    drain_stack(s)
    assert len(s.players[1].graveyard) == 21
    assert len(s.players[0].hand) == 3


def test_jace_minus_two_draws_one_otherwise():
    s = arena()
    jace = _walker(s, "Jace, the Perfected Mind")
    _library(s, pid=0, n=5)
    _library(s, pid=1, n=5)
    agent(s, 0).targets = [("player", 1)]
    _activate_ability(s, 0, jace.id, _ability_index(jace, loyalty=2))
    drain_stack(s)
    assert len(s.players[0].hand) == 1
    assert not AnyGraveyardHasAtLeast(n=20).matches(s, 0)


def _cast_jace(yes: bool, islands: int):
    s = arena()
    for _ in range(islands):
        put(s, BASIC_LANDS["Island"], 0)
    jace = to_hand(s, printing("Jace, the Perfected Mind"), 0)
    agent(s, 0).yes = yes
    apply_action(s, 0, CastSpell(jace.id))
    drain_stack(s)
    return s, jace


def test_compleated_paying_life_enters_with_two_fewer_loyalty():
    s, jace = _cast_jace(yes=True, islands=4)
    assert jace in s.battlefield
    assert s.players[0].life == 18
    assert jace.loyalty_counters == 3
    assert jace.phyrexian_life_pips == 0


def test_compleated_paying_mana_keeps_full_loyalty():
    s, jace = _cast_jace(yes=False, islands=4)
    assert s.players[0].life == 20
    assert jace.loyalty_counters == 5


def test_apply_compleated_ignores_noncompleated_permanents():
    s = arena()
    ugin = _walker(s, "Ugin, the Spirit Dragon")
    ugin.phyrexian_life_pips = 1
    apply_compleated(s, ugin)
    assert ugin.loyalty_counters == 7 and ugin.phyrexian_life_pips == 0


# ---------------------------------------------------------------------------
# Liliana of the Veil
# ---------------------------------------------------------------------------


def test_liliana_plus_one_each_player_discards():
    s = arena()
    lili = _walker(s, "Liliana of the Veil")
    mine = to_hand(s, BASIC_LANDS["Swamp"], 0)
    theirs = to_hand(s, BASIC_LANDS["Island"], 1)
    _activate_ability(s, 0, lili.id, _ability_index(lili, loyalty=-1))
    drain_stack(s)
    assert lili.loyalty_counters == 4
    assert mine in s.players[0].graveyard and theirs in s.players[1].graveyard
    assert EachPlayerDiscards(count=2).describe() == (
        "each player discards 2 cards"
    )


def test_each_player_discards_with_empty_hand_and_no_agent():
    s = arena()
    card = to_hand(s, BASIC_LANDS["Island"], 1)
    s.players[1].agent = None
    EachPlayerDiscards(count=2).resolve(s, 0, ())
    assert card in s.players[1].graveyard


def test_liliana_minus_six_piles():
    from dataclasses import dataclass as _dc

    @_dc
    class PileAgent(ScriptedAgent):
        answers: list = None

        def choose_yes_no(self, state, player_id, prompt):
            return self.answers.pop(0)

    s = arena()
    lili = _walker(s, "Liliana of the Veil", loyalty=6)
    a = put(s, _BEAR, 1)
    b = put(s, BASIC_LANDS["Island"], 1)
    c = put(s, _ROCK, 1)
    mine = put(s, _BEAR, 0)
    s.players[0].agent = PileAgent(answers=[True, False, False])
    s.players[0].agent.targets = [("player", 1)]

    @_dc
    class Chooser(ScriptedAgent):
        def choose_mode(self, state, player_id, mode_descriptions):
            self.seen = list(mode_descriptions)
            return 1  # sacrifice pile 2 (Island, Rock)

    s.players[1].agent = Chooser()
    _activate_ability(s, 0, lili.id, _ability_index(lili, loyalty=6))
    drain_stack(s)
    assert s.players[1].agent.seen == [
        "sacrifice pile 1: Bear", "sacrifice pile 2: Island, Rock",
    ]
    assert a in s.battlefield and mine in s.battlefield
    assert b not in s.battlefield and c not in s.battlefield
    assert "two piles" in SeparatePermanentsIntoPilesSacrificeChosen().describe()


def test_piles_without_agents_or_targets():
    s = arena()
    a = put(s, _BEAR, 1)
    eff = SeparatePermanentsIntoPilesSacrificeChosen()
    eff.resolve(s, 0, ())  # no target: nothing happens
    assert a in s.battlefield
    for p in s.players:
        p.agent = None
    eff.resolve(s, 0, (("player", 1),))
    assert a not in s.battlefield  # everything in pile 1, pile 1 chosen
    s.players[1].has_lost = True
    eff.resolve(s, 0, (("player", 1),))


# ---------------------------------------------------------------------------
# Ugin, the Spirit Dragon
# ---------------------------------------------------------------------------


def test_ugin_minus_x_exiles_colored_permanents_up_to_x():
    s = arena()
    ugin = _walker(s, "Ugin, the Spirit Dragon")
    small = put(s, _RED_BEAR, 1)
    mid = put(s, _BEAR, 1)
    rock = put(s, _ROCK, 1)
    land = put(s, BASIC_LANDS["Island"], 1)
    agent(s, 0).x_value = 1
    _activate_ability(s, 0, ugin.id, _ability_index(ugin, x=True))
    drain_stack(s)
    assert ugin.loyalty_counters == 6
    assert small in s.players[1].exile
    assert mid in s.battlefield and rock in s.battlefield and land in s.battlefield


def test_ugin_minus_ten_gains_draws_and_deploys():
    s = arena()
    ugin = _walker(s, "Ugin, the Spirit Dragon", loyalty=10)
    for _ in range(7):
        to_library(s, _BEAR, 0)
    bolt_like = to_hand(s, make_instant("Shock", "{R}", DrawCards(amount=1)), 0)
    _activate_ability(s, 0, ugin.id, _ability_index(ugin, loyalty=10))
    drain_stack(s)
    assert s.players[0].life == 27
    # Every permanent card went in; the instant stayed.
    assert s.players[0].hand == [bolt_like]
    assert sum(o.printing.name == "Bear" for o in s.battlefield) == 7


def test_put_up_to_n_stops_when_declined():
    from mtg_bot.effects.generic.card_flow import CardFilter

    s = arena()
    to_hand(s, _BEAR, 0)
    agent(s, 0).library_pick = None
    eff = PutUpToNCardsFromHandOntoBattlefield(
        count=2, card_filter=CardFilter(any_types=("Permanent",)),
    )
    eff.resolve(s, 0, ())
    assert len(s.players[0].hand) == 1
    assert eff.describe() == (
        "put up to 2 permanent cards from your hand onto the battlefield"
    )


# ---------------------------------------------------------------------------
# Kiora, Behemoth Beckoner
# ---------------------------------------------------------------------------


def test_kiora_untaps_any_permanent():
    s = arena()
    kiora = _walker(s, "Kiora, Behemoth Beckoner")
    land = put(s, BASIC_LANDS["Forest"], 0, tapped=True)
    agent(s, 0).targets = [("permanent", land.id)]
    _activate_ability(s, 0, kiora.id, 0)
    drain_stack(s)
    assert not land.tapped and kiora.loyalty_counters == 6


# ---------------------------------------------------------------------------
# Sentence-composed loyalty bodies
# ---------------------------------------------------------------------------


def test_loyalty_body_sentences_compose_unless_anaphoric():
    from mtg_bot.cards.parser.roto_walkers import parse_roto_loyalty_body
    from mtg_bot.effects.combinators import Sequence

    eff = parse_roto_loyalty_body(
        "Scry 1. Saheeli Rai deals 1 damage to each opponent.", "Saheeli Rai",
    )
    assert isinstance(eff, Sequence) and len(eff.effects) == 2
    assert parse_roto_loyalty_body("Draw a card.", "X") is None
    assert parse_roto_loyalty_body(
        "Draw a card. It gains haste.", "X",
    ) is None
    assert parse_roto_loyalty_body(
        "Draw a card. Frobnicate the widget.", "X",
    ) is None
    # Two targeted sentences can't share one target choice.
    assert parse_roto_loyalty_body(
        "Target player draws a card. Target player draws a card.", "X",
    ) is None


def test_roto_walker_line_declines_unknown_shapes():
    from mtg_bot.cards.parser.roto_walkers import parse_roto_walker_line

    assert parse_roto_walker_line("Hexproof from everything", "X") is None
    assert parse_roto_walker_line("−X: Frobnicate X widgets.", "X") is None


# ---------------------------------------------------------------------------
# Phantasmal Image
# ---------------------------------------------------------------------------


def _cast(s, name_or_printing, pid=0, islands=2):
    pr = printing(name_or_printing) if isinstance(name_or_printing, str) else (
        name_or_printing
    )
    for _ in range(islands):
        put(s, BASIC_LANDS["Island"], pid)
    card = to_hand(s, pr, pid)
    apply_action(s, pid, CastSpell(card.id))
    drain_stack(s)
    return card


def test_phantasmal_image_parse_shape():
    p = printing("Phantasmal Image")
    assert p.enters_as_copy_types == ("Creature",)
    assert p.enters_as_copy_add_subtypes == ("Illusion",)
    (trig,) = p.enters_as_copy_add_triggers
    assert trig.event == Event.BECOMES_TARGET
    from mtg_bot.effects.generic import SacrificeSelf

    assert trig.effect == SacrificeSelf()


def test_phantasmal_image_copies_and_dies_when_targeted():
    from mtg_bot.effects.generic.cube_creatures_rmc import fire_becomes_target

    s = arena()
    bear = put(s, _BEAR, 1)
    agent(s, 0).targets = [("permanent", bear.id)]
    image = _cast(s, "Phantasmal Image")
    assert image in s.battlefield
    assert image.printing.name == "Bear"
    assert image.printing.subtypes[-1] == "Illusion"
    assert (image.printing.power, image.printing.toughness) == (2, 2)
    # The opponent targets it: the granted trigger sacrifices it.
    fire_becomes_target(s, (("creature", image.id),), bear, 1)
    drain_stack(s)
    assert image not in s.battlefield
    assert image in s.players[0].graveyard
    # Targeting the original does nothing to the original.
    fire_becomes_target(s, (("creature", bear.id),), bear, 0)
    drain_stack(s)
    assert bear in s.battlefield


def test_phantasmal_image_without_a_copy_is_a_0_0():
    from mtg_bot.turn import state_based_actions

    s = arena()
    agent(s, 0).targets = []
    image = _cast(s, "Phantasmal Image")
    state_based_actions(s)
    assert image not in s.battlefield


def test_copy_exception_grammar_variants():
    from mtg_bot.cards.parser.roto_walkers import (
        parse_copy_exception,
        parse_roto_trigger_phrase,
    )

    assert parse_copy_exception(
        "it's a Bird in addition to its other types and it has flying"
    ) == {
        "enters_as_copy_add_subtypes": ("Bird",),
        "enters_as_copy_add_keywords": frozenset({"flying"}),
    }
    assert parse_copy_exception(
        "it's a Bird in addition to its other types"
    ) == {"enters_as_copy_add_subtypes": ("Bird",)}
    assert parse_copy_exception("it isn't legendary") is None
    assert parse_copy_exception(
        "it's a Bird in addition to its other types and it has frobnication"
    ) is None
    assert parse_copy_exception(
        'it\'s a Bird in addition to its other types and it has "Frob."'
    ) is None
    assert parse_copy_exception(
        "it's a Bird in addition to its other types and it has "
        '"When this creature frobs, sacrifice it."'
    ) is None
    assert parse_roto_trigger_phrase("this creature frobs") is None


def test_copy_rider_adds_keywords_to_the_copy():
    import dataclasses

    from mtg_bot.creature_casting_ub import apply_copy_on_entry
    from mtg_bot.game import Zone as _Z

    s = arena()
    bear = put(s, _BEAR, 1)
    clone_pr = dataclasses.replace(
        printing("Phantasmal Image"),
        enters_as_copy_add_keywords=frozenset({"flying"}),
    )
    clone = s.new_object(clone_pr, owner_id=0, zone=_Z.BATTLEFIELD)
    agent(s, 0).targets = [("permanent", bear.id)]
    apply_copy_on_entry(s, clone, 0)
    assert "flying" in clone.printing.keywords


# ---------------------------------------------------------------------------
# Gilded Drake
# ---------------------------------------------------------------------------


def test_gilded_drake_parse_shape():
    from mtg_bot.effects.generic.roto_walkers import (
        ExchangeControlOfSourceAndTarget,
    )

    (trig,) = printing("Gilded Drake").triggered_abilities
    assert isinstance(trig.effect, ExchangeControlOfSourceAndTarget)
    assert trig.effect.still_resolves_if_targets_illegal
    assert trig.effect.target_count_range() == (0, 1)
    assert "exchange control" in trig.effect.describe()


def test_gilded_drake_exchanges_with_an_opponents_creature():
    s = arena()
    bear = put(s, _BEAR, 1)
    agent(s, 0).targets = [("creature", bear.id)]
    drake = _cast(s, "Gilded Drake")
    assert drake in s.battlefield
    assert drake.controller_id == 1 and bear.controller_id == 0
    assert bear.summoning_sick


def test_gilded_drake_sacrificed_without_a_target():
    s = arena()
    drake = _cast(s, "Gilded Drake")
    assert drake not in s.battlefield
    assert drake in s.players[0].graveyard


def _drake_trigger(s, target_id):
    drake = put(s, printing("Gilded Drake"), 0)
    (trig,) = drake.printing.triggered_abilities
    s.stack.append(StackItem(
        source=drake, controller_id=0, ability=trig,
        targets=(("creature", target_id),),
    ))
    return drake


def test_gilded_drake_still_resolves_if_its_target_became_illegal():
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards.base import make_creature as _mc

    s = arena()
    shy = put(s, _mc("Shy Bear", "{1}{G}", 2, 2, keywords=frozenset({"hexproof"})), 1)
    drake = _drake_trigger(s, shy.id)
    resolve_top_of_stack(s)
    assert drake not in s.battlefield and shy.controller_id == 1


def test_gilded_drake_target_now_yours_means_sacrifice():
    from mtg_bot.actions import resolve_top_of_stack

    s = arena()
    bear = put(s, _BEAR, 1)
    drake = _drake_trigger(s, bear.id)
    bear.controller_id = 0
    resolve_top_of_stack(s)
    assert drake not in s.battlefield and bear.controller_id == 0


def test_exchange_without_source_on_battlefield_is_noop():
    from mtg_bot.effects.generic.roto_walkers import (
        ExchangeControlOfSourceAndTarget,
    )

    s = arena()
    ExchangeControlOfSourceAndTarget().resolve(s, 0, ())
    assert s.log == [] or "exchange" not in " ".join(s.log)


# ---------------------------------------------------------------------------
# Zealous Conscripts (threaten any permanent)
# ---------------------------------------------------------------------------


def test_zealous_conscripts_steals_any_permanent_until_end_of_turn():
    from mtg_bot.game import effective_keywords
    from mtg_bot.turn import run_cleanup_step

    s = arena()
    rock = put(s, _ROCK, 1, tapped=True)
    agent(s, 0).targets = [("permanent", rock.id)]
    _cast(s, "Zealous Conscripts", islands=5)
    assert rock.controller_id == 0 and not rock.tapped
    assert "haste" in effective_keywords(s, rock)
    run_cleanup_step(s)
    assert rock.controller_id == 1
    assert "haste" not in effective_keywords(s, rock)


def test_threaten_fizzles_on_an_illegal_target():
    from mtg_bot.effects.generic.roto_walkers import GainControlUntapHasteUEOT

    s = arena()
    eff = printing("Zealous Conscripts").triggered_abilities[0].effect
    assert isinstance(eff, GainControlUntapHasteUEOT)
    assert "gain control" in eff.describe()
    eff.resolve(s, 0, (("permanent", 999),))
    eff.resolve(s, 0, ())
    assert all("controls" not in line for line in s.log)


# ---------------------------------------------------------------------------
# Felidar Guardian / Ephemerate (flicker) and Rebound
# ---------------------------------------------------------------------------


def test_felidar_guardian_flickers_another_permanent_you_control():
    s = arena()
    rock = put(s, _ROCK, 0, tapped=True)
    rock.plus_one_counters = 2
    agent(s, 0).targets = [("permanent", rock.id)]
    guardian = _cast(s, "Felidar Guardian", islands=4)
    assert guardian in s.battlefield
    assert rock in s.battlefield and not rock.tapped
    assert rock.plus_one_counters == 0


def test_felidar_guardian_may_decline_and_cant_target_itself():
    s = arena()
    rock = put(s, _ROCK, 0, tapped=True)
    agent(s, 0).targets = [("permanent", rock.id)]
    agent(s, 0).yes = False
    _cast(s, "Felidar Guardian", islands=4)
    assert rock.tapped  # declined: not flickered
    eff = printing("Felidar Guardian").triggered_abilities[0].effect
    s2 = arena()
    g = put(s2, printing("Felidar Guardian"), 0)
    s2.resolving_source = g
    assert all(t[1] != g.id for t in eff.legal_targets(s2, 0))
    assert eff.describe().startswith("you may exile")


def test_flicker_token_ceases_to_exist():
    from mtg_bot.cards.base import make_creature as _mc
    from mtg_bot.effects.generic.roto_walkers import (
        ExileTargetThenReturnUnderOwnersControl,
    )

    s = arena()
    token_pr = _mc("Spirit", "", 1, 1)
    import dataclasses as _dc

    token_pr = _dc.replace(token_pr, supertypes=("Token",))
    tok = put(s, token_pr, 0)
    eff = printing("Ephemerate").spell_effect
    assert isinstance(eff, ExileTargetThenReturnUnderOwnersControl)
    eff.resolve(s, 0, (("creature", tok.id),))
    assert tok not in s.battlefield
    eff.resolve(s, 0, ())  # no target


def test_ephemerate_flickers_and_rebounds():
    from mtg_bot.simulate import run_step

    s = arena()
    bear = put(s, _BEAR, 0, tapped=True)
    agent(s, 0).targets = [("creature", bear.id)]
    eph = _cast(s, "Ephemerate", islands=1)
    assert not bear.tapped and bear in s.battlefield
    # Cast from hand: exiled with a rebound trigger, not in the graveyard.
    assert eph in s.players[0].exile
    (entry,) = s.delayed_triggers
    assert entry["own_upkeep"] and entry["step"] == "upkeep"
    # The opponent's upkeep doesn't fire it ...
    s.turn_number, s.active_player_idx = 2, 1
    run_step(s, Step.UPKEEP)
    assert eph in s.players[0].exile
    # ... its owner's next upkeep casts it again for free.
    s.turn_number, s.active_player_idx = 3, 0
    s.priority_player_idx = 0
    bear.tapped = True
    agent(s, 0).targets = [("creature", bear.id)]
    run_step(s, Step.UPKEEP)
    drain_stack(s)
    assert not bear.tapped
    # Cast from exile this time: it goes to the graveyard.
    assert eph in s.players[0].graveyard
    assert s.delayed_triggers == []


def test_rebound_cast_declined_or_without_target_stays_exiled():
    from mtg_bot.effects.generic.roto_walkers import (
        MayCastExiledSourceFree,
        exile_with_rebound,
    )

    s = arena()
    card = s.new_object(printing("Ephemerate"), owner_id=0, zone=Zone.STACK)
    exile_with_rebound(s, card, 0)
    s.resolving_source = card
    # No creature to target: can't be cast.
    MayCastExiledSourceFree().resolve(s, 0, ())
    assert card in s.players[0].exile
    put(s, _BEAR, 0)
    agent(s, 0).yes = False
    MayCastExiledSourceFree().resolve(s, 0, ())
    assert card in s.players[0].exile and s.stack == []
    s.players[0].exile.remove(card)
    MayCastExiledSourceFree().resolve(s, 0, ())
    s.resolving_source = None
    MayCastExiledSourceFree().resolve(s, 0, ())
    assert "cast this card from exile" in MayCastExiledSourceFree().describe()


def test_ephemerate_parse_has_rebound():
    p = printing("Ephemerate")
    assert p.rebound
    from mtg_bot.cards.parser.roto_walkers import parse_roto_casting_keyword

    assert parse_roto_casting_keyword("Cascade") is None


# ---------------------------------------------------------------------------
# Nicol Bolas, God-Pharaoh
# ---------------------------------------------------------------------------


def test_bolas_plus_two_exiles_to_a_nonland_and_casts_it_free():
    from mtg_bot.actions import CastSpell as _Cast

    s = arena()
    bolas = _walker(s, "Nicol Bolas, God-Pharaoh")
    land1 = to_library(s, BASIC_LANDS["Island"], 1)
    spell = to_library(s, _RED_BEAR, 1)
    rest = to_library(s, BASIC_LANDS["Island"], 1)
    agent(s, 0).targets = [("player", 1)]
    _activate_ability(s, 0, bolas.id, _ability_index(bolas, loyalty=-2))
    drain_stack(s)
    assert land1 in s.players[1].exile and spell in s.players[1].exile
    assert rest in s.players[1].library
    perm = spell.exile_play_permission
    assert perm.player_id == 0 and perm.free and perm.cast_only
    acts = legal_actions(s, 0)
    assert any(isinstance(a, _Cast) and a.card_id == spell.id for a in acts)


def test_bolas_plus_two_on_an_all_land_library():
    from mtg_bot.effects.generic.roto_walkers import (
        TargetOpponentExilesUntilNonlandCastFree,
    )

    s = arena()
    to_library(s, BASIC_LANDS["Island"], 1)
    eff = TargetOpponentExilesUntilNonlandCastFree()
    assert eff.legal_targets(s, 0) == [("player", 1)]
    eff.resolve(s, 0, (("player", 1),))
    assert s.players[1].library == [] and len(s.players[1].exile) == 1
    eff.resolve(s, 0, ())
    assert "nonland" in eff.describe()


def test_bolas_plus_one_each_opponent_exiles_two_from_hand():
    from mtg_bot.effects.generic.roto_walkers import (
        EachOpponentExilesCardsFromHand,
    )

    s = arena()
    bolas = _walker(s, "Nicol Bolas, God-Pharaoh")
    a = to_hand(s, BASIC_LANDS["Island"], 1)
    b = to_hand(s, _BEAR, 1)
    c = to_hand(s, _ROCK, 1)
    mine = to_hand(s, _BEAR, 0)
    agent(s, 1).discards = [c.id, a.id]
    _activate_ability(s, 0, bolas.id, _ability_index(bolas, loyalty=-1))
    drain_stack(s)
    assert c in s.players[1].exile and a in s.players[1].exile
    assert b in s.players[1].hand and mine in s.players[0].hand
    s.players[1].agent = None
    EachOpponentExilesCardsFromHand(count=3).resolve(s, 0, ())
    assert s.players[1].hand == []
    assert EachOpponentExilesCardsFromHand(count=2).describe() == (
        "each opponent exiles 2 cards from their hand"
    )
    assert EachOpponentExilesCardsFromHand().describe().endswith(
        "a card from their hand"
    )


def test_bolas_minus_four_targets_only_opponents_things():
    s = arena()
    bolas = _walker(s, "Nicol Bolas, God-Pharaoh")
    theirs = put(s, _BEAR, 1)
    mine = put(s, _BEAR, 0)
    eff = bolas.printing.activated_abilities[2].effect
    s.resolving_source = bolas
    legal = eff.legal_targets(s, 0)
    s.resolving_source = None
    assert ("creature", theirs.id) in legal and ("player", 1) in legal
    assert ("creature", mine.id) not in legal and ("player", 0) not in legal
    agent(s, 0).targets = [("player", 1)]
    _activate_ability(s, 0, bolas.id, _ability_index(bolas, loyalty=4))
    drain_stack(s)
    assert s.players[1].life == 13


def test_bolas_minus_twelve_exiles_opponents_nonland_permanents():
    s = arena()
    bolas = _walker(s, "Nicol Bolas, God-Pharaoh", loyalty=12)
    theirs = put(s, _BEAR, 1)
    land = put(s, BASIC_LANDS["Island"], 1)
    mine = put(s, _BEAR, 0)
    _activate_ability(s, 0, bolas.id, _ability_index(bolas, loyalty=12))
    drain_stack(s)
    assert theirs in s.players[1].exile
    assert land in s.battlefield and mine in s.battlefield


def test_damage_to_target_list_declines_unknown_items():
    from mtg_bot.cards.parser.roto_walkers import parse_roto_effect

    assert parse_roto_effect(
        "deals 2 damage to target player, frobnicator, or creature"
    ) is None


# ---------------------------------------------------------------------------
# Enter the Infinite
# ---------------------------------------------------------------------------


def test_enter_the_infinite_draws_library_puts_one_back_no_max_hand():
    from mtg_bot.turn import run_cleanup_step

    s = arena()
    for _ in range(12):
        to_library(s, _BEAR, 0)
    agent(s, 0).hand_pick = "first"
    _cast_on_stack(s, printing("Enter the Infinite"), 0)
    drain_stack(s)
    assert len(s.players[0].hand) == 11 and len(s.players[0].library) == 1
    # No maximum hand size this turn ...
    run_cleanup_step(s)
    assert len(s.players[0].hand) == 11
    # ... until the controller's next turn begins.
    from mtg_bot.turn import run_untap_step

    s.active_player_idx = 0
    run_untap_step(s)
    assert s.emblems == []
    run_cleanup_step(s)
    assert len(s.players[0].hand) == 7


def _cast_on_stack(s, pr, controller):
    card = s.new_object(pr, owner_id=controller, zone=Zone.STACK)
    s.stack.append(StackItem(source=card, controller_id=controller))
    return card


def test_count_formula_effects():
    from mtg_bot.cards.parser.roto_walkers import parse_roto_effect
    from mtg_bot.effects.generic.roto_walkers import (
        CardsInYourZone,
        DrawCardsEqualTo,
        EachOpponentLosesLifeEqualTo,
    )

    s = arena()
    to_graveyard(s, _BEAR, 0)
    to_graveyard(s, _BEAR, 0)
    to_graveyard(s, BASIC_LANDS["Swamp"], 0)
    eff = parse_roto_effect(
        "each opponent loses life equal to the number of creature cards in "
        "your graveyard"
    )
    assert isinstance(eff, EachOpponentLosesLifeEqualTo)
    eff.resolve(s, 0, ())
    assert s.players[1].life == 18 and s.players[0].life == 20
    assert CardsInYourZone(zone="graveyard").value(s, 0) == 3
    assert "count" in eff.describe()
    draw = DrawCardsEqualTo(count=CardsInYourZone(zone="graveyard"))
    assert "count" in draw.describe()
    assert parse_roto_effect(
        "draw cards equal to the number of frobs in your library"
    ) is None
    assert parse_roto_effect(
        "draw cards equal to the number of frob cards in your library"
    ) is None


# ---------------------------------------------------------------------------
# Nissa, Ascended Animist
# ---------------------------------------------------------------------------


def test_nissa_plus_one_token_is_her_loyalty():
    s = arena()
    nissa = _walker(s, "Nissa, Ascended Animist")
    _activate_ability(s, 0, nissa.id, _ability_index(nissa, loyalty=-1))
    drain_stack(s)
    (horror,) = [o for o in s.battlefield if o.printing.name == "Phyrexian Horror"]
    assert nissa.loyalty_counters == 8
    assert (horror.printing.power, horror.printing.toughness) == (8, 8)
    assert horror.printing.color_indicator == frozenset({"G"})


def test_nissa_minus_seven_pumps_per_forest_with_trample():
    from mtg_bot.game import effective_keywords, effective_power

    s = arena()
    nissa = _walker(s, "Nissa, Ascended Animist", loyalty=7)
    bear = put(s, _BEAR, 0)
    theirs = put(s, _BEAR, 1)
    for _ in range(3):
        put(s, BASIC_LANDS["Forest"], 0)
    put(s, BASIC_LANDS["Forest"], 1)
    _activate_ability(s, 0, nissa.id, _ability_index(nissa, loyalty=7))
    drain_stack(s)
    assert effective_power(s, bear) == 5
    assert "trample" in effective_keywords(s, bear)
    assert effective_power(s, theirs) == 2


def test_nissa_compleated_and_destroy():
    p = printing("Nissa, Ascended Animist")
    assert "compleated" in p.keywords
    assert p.mana_cost.phyrexian == ("G", "G")


# ---------------------------------------------------------------------------
# Dihada, Binder of Wills
# ---------------------------------------------------------------------------


def test_dihada_plus_two_legendary_keywords_until_your_next_turn():
    from mtg_bot.cards.base import make_creature as _mc
    from mtg_bot.game import effective_keywords

    s = arena()
    dihada = _walker(s, "Dihada, Binder of Wills")
    legend = put(s, _mc("Legend", "{1}{W}", 2, 2, legendary=True), 0)
    eff = dihada.printing.activated_abilities[0].effect
    plain = put(s, _BEAR, 0)
    s.resolving_source = dihada
    legal = eff.legal_targets(s, 0)
    s.resolving_source = None
    assert ("creature", legend.id) in legal and ("creature", plain.id) not in legal
    agent(s, 0).targets = [("creature", legend.id)]
    _activate_ability(s, 0, dihada.id, _ability_index(dihada, loyalty=-2))
    drain_stack(s)
    kws = effective_keywords(s, legend)
    assert {"vigilance", "lifelink", "indestructible"} <= kws
    s.expire_continuous_effects("cleanup")
    assert "lifelink" in effective_keywords(s, legend)
    s.expire_continuous_effects("controller_untap", player_id=0)
    assert "lifelink" not in effective_keywords(s, legend)
    assert "until your next turn" in eff.describe()


def test_dihada_minus_three_legendary_to_hand_rest_bin_treasures():
    from mtg_bot.cards.base import make_creature as _mc

    s = arena()
    dihada = _walker(s, "Dihada, Binder of Wills")
    legend = to_library(s, _mc("Legend", "{1}{W}", 2, 2, legendary=True), 0)
    others = [to_library(s, _BEAR, 0) for _ in range(3)]
    deep = to_library(s, _BEAR, 0)
    _activate_ability(s, 0, dihada.id, _ability_index(dihada, loyalty=3))
    drain_stack(s)
    assert legend in s.players[0].hand
    assert all(o in s.players[0].graveyard for o in others)
    assert deep in s.players[0].library
    treasures = [o for o in s.battlefield if o.printing.name == "Treasure"]
    assert len(treasures) == 3
    assert "Treasure" in dihada.printing.activated_abilities[1].effect.describe()


def test_dihada_minus_eleven_steals_everything_nonland():
    from mtg_bot.game import effective_keywords
    from mtg_bot.turn import run_cleanup_step

    s = arena()
    dihada = _walker(s, "Dihada, Binder of Wills", loyalty=11)
    theirs = put(s, _BEAR, 1, tapped=True)
    rock = put(s, _ROCK, 1, tapped=True)
    land = put(s, BASIC_LANDS["Plains"], 1, tapped=True)
    _activate_ability(s, 0, dihada.id, _ability_index(dihada, loyalty=11))
    drain_stack(s)
    assert theirs.controller_id == 0 and rock.controller_id == 0
    assert not theirs.tapped and "haste" in effective_keywords(s, theirs)
    assert land.controller_id == 1 and land.tapped
    run_cleanup_step(s)
    assert theirs.controller_id == 1
    assert "until end of turn" in (
        dihada.printing.activated_abilities[2].effect.describe()
    )


def test_each_opponent_may_scry():
    from mtg_bot.effects.generic.roto_walkers import EachOpponentMayScry

    s = arena()
    top = to_library(s, _BEAR, 1)
    to_library(s, _ROCK, 1)
    EachOpponentMayScry(amount=1).resolve(s, 0, ())
    assert s.players[1].library[0] is top  # ScriptedAgent keeps on top
    agent(s, 1).yes = False
    EachOpponentMayScry(amount=1).resolve(s, 0, ())
    assert EachOpponentMayScry().describe() == "each opponent may scry 1"


# ---------------------------------------------------------------------------
# Saheeli Rai
# ---------------------------------------------------------------------------


def test_saheeli_plus_one_scry_and_ping():
    s = arena()
    saheeli = _walker(s, "Saheeli Rai")
    _library(s, pid=0, n=2)
    _activate_ability(s, 0, saheeli.id, _ability_index(saheeli, loyalty=-1))
    drain_stack(s)
    assert s.players[1].life == 19 and saheeli.loyalty_counters == 4


def test_saheeli_minus_two_hasty_artifact_token_copy_exiled_at_end():
    from mtg_bot.game import effective_keywords

    s = arena()
    saheeli = _walker(s, "Saheeli Rai")
    bear = put(s, _BEAR, 0)
    agent(s, 0).targets = [("creature", bear.id)]
    _activate_ability(s, 0, saheeli.id, _ability_index(saheeli, loyalty=2))
    drain_stack(s)
    (token,) = [o for o in s.battlefield if o is not bear and o.printing.name == "Bear"]
    assert "Token" in token.printing.supertypes
    assert "Artifact" in token.printing.card_types
    assert "haste" in effective_keywords(s, token)
    run_step(s, Step.END)
    assert token not in s.battlefield and bear in s.battlefield


def test_saheeli_minus_seven_three_different_artifacts():
    s = arena()
    saheeli = _walker(s, "Saheeli Rai", loyalty=7)
    a1 = to_library(s, _ROCK, 0)
    a2 = to_library(s, _ROCK, 0)
    other = to_library(s, make_artifact("Pebble", "{1}"), 0)
    to_library(s, _BEAR, 0)
    _activate_ability(s, 0, saheeli.id, _ability_index(saheeli, loyalty=7))
    drain_stack(s)
    names = sorted(o.printing.name for o in s.battlefield if o.printing.is_artifact)
    assert names == ["Pebble", "Rock"]
    assert (a1 in s.battlefield) != (a2 in s.battlefield)
    assert other in s.battlefield
    assert "different names" in (
        saheeli.printing.activated_abilities[2].effect.describe()
    )


def test_token_copy_without_legal_target_does_nothing():
    s = arena()
    eff = printing("Saheeli Rai").activated_abilities[1].effect
    bear = put(s, _BEAR, 1)
    eff.resolve(s, 0, (("creature", bear.id),))  # not yours: illegal
    eff.resolve(s, 0, ())
    assert len(s.battlefield) == 1
    assert "copy" in eff.describe()


# ---------------------------------------------------------------------------
# Kaya, Intangible Slayer
# ---------------------------------------------------------------------------


def test_kaya_minus_three_exiles_and_makes_a_spirit_copy():
    from mtg_bot.game import effective_colors, effective_keywords

    s = arena()
    kaya = _walker(s, "Kaya, Intangible Slayer")
    bear = put(s, _BEAR, 1)
    agent(s, 0).targets = [("creature", bear.id)]
    _activate_ability(s, 0, kaya.id, _ability_index(kaya, loyalty=3))
    drain_stack(s)
    assert bear in s.players[1].exile
    (spirit,) = [o for o in s.battlefield if o.printing.name == "Bear"]
    assert spirit.controller_id == 0
    assert (spirit.printing.power, spirit.printing.toughness) == (1, 1)
    assert "Spirit" in spirit.printing.subtypes
    assert effective_colors(s, spirit) == frozenset({"W"})
    assert "flying" in effective_keywords(s, spirit)


def test_kaya_minus_three_on_an_aura_makes_no_token():
    from mtg_bot.cards.base import make_aura

    s = arena()
    kaya = _walker(s, "Kaya, Intangible Slayer")
    aura = put(s, make_aura("Pacifism Stand-in", "{1}{W}"), 1)
    agent(s, 0).targets = [("permanent", aura.id)]
    _activate_ability(s, 0, kaya.id, _ability_index(kaya, loyalty=3))
    drain_stack(s)
    assert aura in s.players[1].exile
    assert [o for o in s.battlefield if o is not kaya] == []
    eff = kaya.printing.activated_abilities[2].effect
    eff.resolve(s, 0, ())
    eff.resolve(s, 0, (("creature", 999),))
    assert "Aura" in eff.describe()


def test_kaya_zero_draws_two_and_opponent_may_scry():
    s = arena()
    kaya = _walker(s, "Kaya, Intangible Slayer")
    _library(s, pid=0, n=3)
    _library(s, pid=1, n=2)
    _activate_ability(s, 0, kaya.id, _ability_index(kaya, loyalty=0))
    drain_stack(s)
    assert len(s.players[0].hand) == 2


def test_token_copy_exception_grammar_declines():
    from mtg_bot.cards.parser.roto_walkers import parse_roto_effect

    assert parse_roto_effect(
        "create a token that's a copy of target creature you control, except "
        "it's a 1/1 frob in addition to its other types"
    ) is None
    assert parse_roto_effect(
        "create a token that's a copy of target creature you control, except "
        "it's a Spirit with frobbing in addition to its other types"
    ) is None
    assert parse_roto_effect(
        "create a token that's a copy of target creature you control, except "
        "it isn't legendary"
    ) is None
    assert parse_roto_effect(
        "exile target frob. If it wasn't an Aura, create a token that's a "
        "copy of it, except it's an artifact in addition to its other types"
    ) is None
    assert parse_roto_effect(
        "search your library for up to two frob cards with different names, "
        "put them onto the battlefield, then shuffle"
    ) is None


# ---------------------------------------------------------------------------
# Emrakul, the Promised End
# ---------------------------------------------------------------------------


def test_emrakul_costs_one_less_per_card_type_in_graveyard():
    from mtg_bot.actions import apply_cost_reductions
    from mtg_bot.effects.generic.roto_walkers import PerCardTypeInYourGraveyard

    s = arena()
    emrakul = printing("Emrakul, the Promised End")
    assert apply_cost_reductions(emrakul, s, 0, emrakul.mana_cost).total == 13
    to_graveyard(s, _BEAR, 0)
    to_graveyard(s, BASIC_LANDS["Swamp"], 0)
    to_graveyard(s, make_instant("Shock", "{R}", DrawCards(amount=1)), 0)
    to_graveyard(s, _BEAR, 1)  # the opponent's graveyard doesn't count
    assert apply_cost_reductions(emrakul, s, 0, emrakul.mana_cost).total == 10
    assert PerCardTypeInYourGraveyard().multiplier(s, 0) == 3
    assert PerCardTypeInYourGraveyard().matches(s, 1)


def test_emrakul_cast_trigger_controls_their_next_turn_then_extra_turn():
    from mtg_bot.turn import run_cleanup_step, run_untap_step

    s = arena()
    (trig,) = printing("Emrakul, the Promised End").triggered_abilities
    eff = trig.effect
    assert eff.legal_targets(s, 0) == [("player", 1)]
    p0_agent, p1_agent = s.players[0].agent, s.players[1].agent
    eff.resolve(s, 0, (("player", 1),))
    assert s.players[1].extra_turn_after_controlled_turn
    # Their next turn: P0's agent decides for P1.
    s.active_player_idx = 1
    run_untap_step(s)
    assert s.players[1].agent is p0_agent
    run_cleanup_step(s)
    assert s.players[1].agent is p1_agent
    # After that turn, that player takes an extra turn.
    assert s.extra_turn_queue == [1]
    assert not s.players[1].extra_turn_after_controlled_turn
    assert "extra turn" in eff.describe()


def test_control_opponent_next_turn_edge_cases():
    from mtg_bot.effects.generic.roto_walkers import (
        ControlTargetOpponentDuringNextTurn,
        extra_turn_after_controlled_turn,
    )

    s = arena()
    eff = ControlTargetOpponentDuringNextTurn()
    eff.resolve(s, 0, ())
    s.players[1].has_lost = True
    eff.resolve(s, 0, (("player", 1),))
    assert s.players[1].scheduled_agent_override is None
    extra_turn_after_controlled_turn(s, s.players[1])
    assert s.extra_turn_queue == []
    assert "extra turn" not in eff.describe()


# ---------------------------------------------------------------------------
# Chain of Vapor
# ---------------------------------------------------------------------------


def test_chain_of_vapor_bounces_and_offers_a_land_for_a_copy():
    from mtg_bot.actions import resolve_top_of_stack

    s = arena()
    bear = put(s, _BEAR, 1)
    land = put(s, BASIC_LANDS["Island"], 1)
    mine = put(s, _ROCK, 0)
    vapor = _cast_on_stack(s, printing("Chain of Vapor"), 0)
    s.stack[-1].targets = (("creature", bear.id),)
    agent(s, 1).targets = [("permanent", mine.id)]
    resolve_top_of_stack(s)
    assert bear in s.players[1].hand
    assert land not in s.battlefield  # sacrificed for the copy
    (copy_item,) = s.stack
    assert copy_item.controller_id == 1 and copy_item.source.is_spell_copy
    assert copy_item.targets == (("permanent", mine.id),)
    resolve_top_of_stack(s)
    assert mine in s.players[0].hand
    assert vapor in s.players[0].graveyard


def test_chain_of_vapor_declined_or_without_lands():
    from mtg_bot.actions import resolve_top_of_stack

    s = arena()
    bear = put(s, _BEAR, 1)
    _cast_on_stack(s, printing("Chain of Vapor"), 0)
    s.stack[-1].targets = (("creature", bear.id),)
    resolve_top_of_stack(s)  # no lands: no copy
    assert bear in s.players[1].hand and s.stack == []
    s2 = arena()
    bear2 = put(s2, _BEAR, 1)
    put(s2, BASIC_LANDS["Island"], 1)
    agent(s2, 1).yes = False
    _cast_on_stack(s2, printing("Chain of Vapor"), 0)
    s2.stack[-1].targets = (("creature", bear2.id),)
    resolve_top_of_stack(s2)
    assert s2.stack == [] and len(s2.battlefield) == 1
    eff = printing("Chain of Vapor").spell_effect
    eff.resolve(s2, 0, ())
    eff.resolve(s2, 0, (("creature", 999),))
    assert "copy this spell" in eff.describe()


# ---------------------------------------------------------------------------
# Sin, Spira's Punishment
# ---------------------------------------------------------------------------


def test_sin_exiles_random_permanent_cards_and_repeats_on_lands():
    import random as _random

    s = arena()
    s.rng = _random.Random(3)
    land = to_graveyard(s, BASIC_LANDS["Forest"], 0)
    bear = to_graveyard(s, _BEAR, 0)
    instant = to_graveyard(s, make_instant("Shock", "{R}", DrawCards(amount=1)), 0)
    eff = printing("Sin, Spira's Punishment").triggered_abilities[0].effect
    eff.resolve(s, 0, ())
    tokens = [o for o in s.battlefield if "Token" in o.printing.supertypes]
    names = sorted(o.printing.name for o in tokens)
    assert all(o.tapped for o in tokens)
    # Either the Bear came first (one token) or the Forest first (then
    # the process repeated onto the Bear).
    assert names in (["Bear"], ["Bear", "Forest"])
    assert bear in s.players[0].exile and instant in s.players[0].graveyard
    assert (land in s.players[0].exile) == ("Forest" in names)
    assert "random" in eff.describe()


def test_sin_with_only_lands_keeps_going_until_none_left():
    s = arena()
    for _ in range(3):
        to_graveyard(s, BASIC_LANDS["Forest"], 0)
    eff = printing("Sin, Spira's Punishment").triggered_abilities[0].effect
    eff.resolve(s, 0, ())
    assert len([o for o in s.battlefield if o.printing.name == "Forest"]) == 3
    assert s.players[0].graveyard == []


# ---------------------------------------------------------------------------
# Chandra, Hope's Beacon
# ---------------------------------------------------------------------------

from mtg_bot.effects.generic.life import GainLife  # noqa: E402

_GROWTH = make_instant("Growth Stand-in", "{R}", GainLife(amount=2))


def test_chandra_copies_the_first_instant_or_sorcery_each_turn():
    s = arena()
    _walker(s, "Chandra, Hope's Beacon")
    for _ in range(2):
        put(s, BASIC_LANDS["Mountain"], 0)
    first = to_hand(s, _GROWTH, 0)
    second = to_hand(s, _GROWTH, 0)
    apply_action(s, 0, CastSpell(first.id))
    # The copy trigger sits above the spell.
    assert s.stack[-1].ability is not None
    drain_stack(s)
    assert s.players[0].life == 24  # the spell and its copy
    apply_action(s, 0, CastSpell(second.id))
    assert s.stack[-1].ability is None  # once each turn
    drain_stack(s)
    assert s.players[0].life == 26


def test_copy_triggering_spell_when_the_spell_is_gone():
    from mtg_bot.effects.generic.roto_walkers import CopyTriggeringSpell

    s = arena()
    s.resolving_event_subject_id = 12345
    CopyTriggeringSpell().resolve(s, 0, ())
    assert s.stack == [] and "gone" in s.log[-1]
    assert CopyTriggeringSpell().event_subject_id({}) == -1
    assert "copy that spell" in CopyTriggeringSpell().describe()


def test_chandra_plus_one_may_cast_one_instant_or_sorcery_from_among_them():
    from mtg_bot.actions import CastSpell as _Cast
    from mtg_bot.effects.generic.cube_creatures_rmc import (
        expire_exile_play_permissions,
    )

    s = arena()
    chandra = _walker(s, "Chandra, Hope's Beacon")
    for _ in range(2):
        put(s, BASIC_LANDS["Mountain"], 0)
    a = to_library(s, _GROWTH, 0)
    b = to_library(s, _GROWTH, 0)
    bear = to_library(s, _BEAR, 0)
    for _ in range(3):
        to_library(s, BASIC_LANDS["Mountain"], 0)
    _activate_ability(s, 0, chandra.id, _ability_index(chandra, loyalty=-1))
    drain_stack(s)
    assert len(s.players[0].exile) == 5 and len(s.players[0].library) == 1
    assert bear.exile_play_permission is None
    casts = {x.card_id for x in legal_actions(s, 0) if isinstance(x, _Cast)}
    assert {a.id, b.id} <= casts
    apply_action(s, 0, _Cast(a.id))
    drain_stack(s)
    casts = {x.card_id for x in legal_actions(s, 0) if isinstance(x, _Cast)}
    assert b.id not in casts  # one spell from among them
    # The permission outlives this turn's cleanup ...
    eff = chandra.printing.activated_abilities[1].effect
    assert "from among them" in eff.describe()


def test_chandra_minus_x_hits_up_to_two_targets():
    s = arena()
    chandra = _walker(s, "Chandra, Hope's Beacon", loyalty=5)
    bear = put(s, _BEAR, 1)
    agent(s, 0).x_value = 3
    agent(s, 0).targets = [("player", 1), ("creature", bear.id)]
    _activate_ability(s, 0, chandra.id, _ability_index(chandra, x=True))
    drain_stack(s)
    assert chandra.loyalty_counters == 2
    assert s.players[1].life == 17 and bear not in s.battlefield


def test_exile_top_cast_one_with_a_short_library():
    from mtg_bot.effects.generic.card_flow import CardFilter
    from mtg_bot.effects.generic.roto_walkers import (
        ExileTopMayCastOneFromAmongUntilEndOfNextTurn,
    )

    s = arena()
    to_library(s, _GROWTH, 0)
    ExileTopMayCastOneFromAmongUntilEndOfNextTurn(
        count=3, card_filter=CardFilter(any_types=("Instant",)),
    ).resolve(s, 0, ())
    (card,) = s.players[0].exile
    assert card.exile_play_permission.group_ids == (card.id,)


# ---------------------------------------------------------------------------
# Professor Dellian Fel
# ---------------------------------------------------------------------------


def test_dellian_fel_emblem_drains_on_every_life_gain():
    from mtg_bot.game import gain_life

    s = arena()
    fel = _walker(s, "Professor Dellian Fel", loyalty=6)
    agent(s, 0).targets = [("player", 1)]
    _activate_ability(s, 0, fel.id, _ability_index(fel, loyalty=6))
    drain_stack(s)
    assert len(s.emblems) == 1
    gain_life(s, 0, 4)
    drain_stack(s)
    assert s.players[1].life == 16 and s.players[0].life == 24
    # The opponent gaining life doesn't trigger it.
    gain_life(s, 1, 2)
    drain_stack(s)
    assert s.players[1].life == 18


def test_life_gain_event_without_listeners_and_zero_amount():
    from mtg_bot.effects.generic.roto_walkers import (
        TargetOpponentLosesThatMuchLife,
    )
    from mtg_bot.game import gain_life

    s = arena()
    gain_life(s, 0, 3)
    assert s.stack == [] and s.players[0].life == 23
    eff = TargetOpponentLosesThatMuchLife()
    assert eff.legal_targets(s, 0) == [("player", 1)]
    eff.resolve(s, 0, (("player", 1),))
    assert s.players[1].life == 20 and "no amount" in s.log[-1]
    eff.resolve(s, 0, ())
    assert eff.describe() == "target opponent loses that much life"
