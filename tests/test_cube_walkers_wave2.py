"""Second-wave tests for the cube planeswalker bucket: library / control
/ delayed-trigger / emblem primitives and the trigger-phrase fallbacks
(``effects_ext.parse_ext_trigger_phrase``)."""

from __future__ import annotations

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.cards.base import make_artifact, make_creature
from mtg_bot.cards.parser.effects import _parse_effect
from mtg_bot.cards.parser.effects_ext import (
    parse_ext_effect,
    parse_ext_trigger_phrase,
)
from mtg_bot.cards.parser.triggers import _parse_predicate_trigger_phrase
from mtg_bot.effects.combinators import Sequence
from mtg_bot.effects.generic import DrawCards
from mtg_bot.effects.generic.cube_walkers import (
    AtBeginningOfNextEndStep,
    CreateEmblemWithAbilities,
    ExileTargetPlayersLibraryThenShuffleHandIn,
    GainControlOfTargetPermanently,
    IsColorless,
    LookAtTopCardOfTargetPlayersLibraryMayBottom,
    PutCardsFromHandOnTopOfLibrary,
    PutTargetIntoOwnersLibraryNthFromTop,
    TargetPlayerDrawsThenDiscards,
    UntapUpToNPermanents,
)
from mtg_bot.effects.object_predicates import IsArtifact, IsCreature, IsLand
from mtg_bot.effects.predicates import Event
from mtg_bot.effects.targets import TargetSpec
from mtg_bot.game import GameState, Player, Zone


def _state():
    s = GameState()
    s.players += [Player(id=0), Player(id=1)]
    return s


def _bf(s, printing, pid):
    o = s.new_object(printing, pid, Zone.BATTLEFIELD)
    s.battlefield.append(o)
    return o


class _PickAgent(RandomAgent):
    def __init__(self, hand_picks=(), yes=True, perm_picks=()):
        super().__init__()
        self.hand_picks = list(hand_picks)
        self.perm_picks = list(perm_picks)
        self.yes = yes

    def choose_card_from_hand(self, state, player_id, option_ids):
        return self.hand_picks.pop(0) if self.hand_picks else None

    def choose_yes_no(self, state, player_id, prompt):
        return self.yes

    def choose_permanent_to_tap(self, state, player_id, legal_object_ids):
        return self.perm_picks.pop(0) if self.perm_picks else None

    def choose_discard(self, state, player_id, hand_card_ids):
        return hand_card_ids[0]


# ---------------------------------------------------------------------------
# Parse shapes
# ---------------------------------------------------------------------------


def test_brainstorm_shape_composes():
    eff = _parse_effect(
        "draw three cards, then put two cards from your hand on top of "
        "your library in any order"
    )
    assert eff == Sequence(effects=(
        DrawCards(amount=3), PutCardsFromHandOnTopOfLibrary(amount=2),
    ))


def test_target_player_draws_then_discards_and_gain_control_parse():
    assert _parse_effect(
        "target player draws two cards, then discards two cards"
    ) == TargetPlayerDrawsThenDiscards(draw=2, discard=2)
    gc = _parse_effect("gain control of target artifact")
    assert isinstance(gc, GainControlOfTargetPermanently)
    assert gc.targets[0].filter == IsArtifact()
    assert parse_ext_effect("gain control of target spell") is None


def test_delayed_end_step_untargeted_only():
    eff = _parse_effect(
        "at the beginning of the next end step, untap up to two lands"
    )
    assert eff == AtBeginningOfNextEndStep(
        inner=UntapUpToNPermanents(n=2, permanent_filter=IsLand()),
    )
    # A targeted delayed effect would need targets chosen when it
    # triggers -- declined.
    assert parse_ext_effect(
        "at the beginning of the next end step, destroy target creature"
    ) is None
    assert parse_ext_effect("untap up to two spells") is None


def test_tuck_nth_from_top_parse():
    eff = _parse_effect(
        "put target creature into its owner's library second from the top"
    )
    assert isinstance(eff, PutTargetIntoOwnersLibraryNthFromTop)
    assert eff.position == 2
    assert parse_ext_effect(
        "put target spell into its owner's library third from the top"
    ) is None


def test_emblem_with_parseable_trigger_and_unparseable_body():
    eff = _parse_effect(
        'you get an emblem with "Whenever you draw a card, exile target '
        'permanent an opponent controls."'
    )
    assert isinstance(eff, CreateEmblemWithAbilities)
    assert eff.triggered_abilities[0].event == Event.DRAWS_CARD
    assert parse_ext_effect(
        'you get an emblem with "Instant and sorcery cards in your '
        'graveyard have retrace."'
    ) is None


def test_trigger_phrase_fallbacks():
    ev, _ = _parse_predicate_trigger_phrase("you draw a card")
    assert ev == Event.DRAWS_CARD
    for phrase in (
        "you cast a spell",
        "you cast a noncreature spell",
        "you cast a colorless spell",
        "you cast an instant or sorcery spell",
    ):
        ev, _pred = parse_ext_trigger_phrase(phrase)
        assert ev == Event.IS_CAST, phrase
    assert parse_ext_trigger_phrase("you cast a legendary spell") is None
    assert parse_ext_trigger_phrase("an opponent draws a card") is None


def test_cast_trigger_filters_match_spells():
    s = _state()
    src = s.new_object(make_artifact("Src", "{1}"), 0, Zone.BATTLEFIELD)
    rock = s.new_object(make_artifact("Rock", "{2}"), 0, Zone.STACK)
    bear = s.new_object(make_creature("Bear", "{1}{G}", 2, 2), 0, Zone.STACK)
    _, noncreature = parse_ext_trigger_phrase("you cast a noncreature spell")
    _, colorless = parse_ext_trigger_phrase("you cast a colorless spell")
    _, any_spell = parse_ext_trigger_phrase("you cast a spell")
    mine = {"controller": s.players[0]}
    theirs = {"controller": s.players[1]}
    assert noncreature.matches(s, {"spell": rock, **mine}, src)
    assert not noncreature.matches(s, {"spell": bear, **mine}, src)
    assert not noncreature.matches(s, {"spell": rock, **theirs}, src)
    assert colorless.matches(s, {"spell": rock, **mine}, src)
    assert not colorless.matches(s, {"spell": bear, **mine}, src)
    assert any_spell.matches(s, {"spell": bear, **mine}, src)


def test_noun_qualifier_on_type_list_is_declined():
    from mtg_bot.cards.parser.effects_ext import parse_target_noun_phrase

    assert parse_target_noun_phrase(
        "artifact, enchantment, or creature with flying"
    ) is None
    assert TargetPlayerDrawsThenDiscards().requires_target()


def test_is_colorless_rejects_players():
    s = _state()
    assert not IsColorless().test(s.players[0], s)


# ---------------------------------------------------------------------------
# Engine primitives
# ---------------------------------------------------------------------------


def test_put_cards_from_hand_on_top_pick_order():
    s = _state()
    p = s.player_by_id(0)
    a, b, c = (
        s.new_object(BASIC_LANDS[n], 0, Zone.HAND)
        for n in ("Forest", "Island", "Swamp")
    )
    p.hand.extend([a, b, c])
    p.agent = _PickAgent(hand_picks=[c.id, a.id])
    PutCardsFromHandOnTopOfLibrary(amount=2).resolve(s, 0)
    assert p.library[:2] == [a, c]
    assert p.hand == [b]
    # Fewer cards than requested: all go back; a decline takes the first.
    PutCardsFromHandOnTopOfLibrary(amount=3).resolve(s, 0)
    assert p.hand == [] and p.library[0] is b
    PutCardsFromHandOnTopOfLibrary(amount=1).resolve(s, 0)  # empty hand
    assert "in any order" in PutCardsFromHandOnTopOfLibrary().describe()


def test_put_cards_from_hand_without_agent_takes_first():
    s = _state()
    p = s.player_by_id(0)
    a = s.new_object(BASIC_LANDS["Forest"], 0, Zone.HAND)
    p.hand.append(a)
    PutCardsFromHandOnTopOfLibrary(amount=1).resolve(s, 0)
    assert p.library == [a]


def test_target_player_draws_then_discards():
    s = _state()
    opp = s.player_by_id(1)
    opp.agent = _PickAgent()
    opp.library.extend(
        s.new_object(BASIC_LANDS["Forest"], 1, Zone.LIBRARY) for _ in range(3)
    )
    eff = TargetPlayerDrawsThenDiscards(draw=2, discard=2)
    assert eff.legal_targets(s, 0) == [("player", 0), ("player", 1)]
    eff.resolve(s, 0, (("player", 1),))
    assert opp.hand == [] and len(opp.graveyard) == 2
    eff.resolve(s, 0, ())  # no target: no-op
    eff.resolve(s, 0, (("creature", 5),))  # not a player: no-op
    assert "draws 2" in eff.describe()


def test_gain_control_permanently_and_fizzle():
    eff = GainControlOfTargetPermanently(
        targets=(TargetSpec(filter=IsArtifact()),),
    )
    s = _state()
    rock = _bf(s, make_artifact("Rock", "{2}"), 1)
    bear = _bf(s, make_creature("Bear", "{1}{G}", 2, 2), 1)
    eff.resolve(s, 0, (("permanent", rock.id),))
    assert rock.controller_id == 0 and rock.summoning_sick
    eff.resolve(s, 0, (("permanent", rock.id),))  # already yours
    eff.resolve(s, 0, (("creature", bear.id),))  # illegal: fizzles
    assert bear.controller_id == 1
    eff.resolve(s, 0, ())
    assert "gain control" in eff.describe()


def test_look_top_of_target_player_edge_cases():
    eff = LookAtTopCardOfTargetPlayersLibraryMayBottom()
    s = _state()
    eff.resolve(s, 0, (("player", 1),))  # empty library: no-op
    lib = s.player_by_id(1).library
    lib.extend(
        s.new_object(BASIC_LANDS["Forest"], 1, Zone.LIBRARY) for _ in range(2)
    )
    top = lib[0]
    eff.resolve(s, 0, (("player", 1),))  # no agent: bottoms it
    assert lib[-1] is top
    s.player_by_id(1).has_lost = True
    eff.resolve(s, 0, (("player", 1),))  # left the game: no-op
    assert "bottom" in eff.describe()


def test_exile_library_shuffle_hand_describe_and_no_target():
    eff = ExileTargetPlayersLibraryThenShuffleHandIn()
    s = _state()
    eff.resolve(s, 0, ())
    assert eff.legal_targets(s, 0) == [("player", 0), ("player", 1)]
    assert "shuffles" in eff.describe()


def test_untap_up_to_n_and_decline():
    s = _state()
    lands = [_bf(s, BASIC_LANDS["Forest"], 0) for _ in range(3)]
    for land in lands:
        land.tapped = True
    s.player_by_id(0).agent = _PickAgent(perm_picks=[lands[2].id])
    UntapUpToNPermanents(n=2, permanent_filter=IsLand()).resolve(s, 0)
    assert [land.tapped for land in lands] == [True, True, False]
    # No agent: takes the first tapped ones.
    s2 = _state()
    l2 = [_bf(s2, BASIC_LANDS["Forest"], 0) for _ in range(2)]
    l2[0].tapped = True
    UntapUpToNPermanents(n=2).resolve(s2, 0)
    assert not l2[0].tapped
    UntapUpToNPermanents(n=1).resolve(s2, 0)  # nothing tapped
    assert "untap up to 2" in UntapUpToNPermanents(n=2).describe()


def test_delayed_end_step_without_source_and_describe():
    eff = AtBeginningOfNextEndStep(inner=DrawCards(amount=1))
    s = _state()
    assert eff.resolve(s, 0) is False
    assert "next end step" in eff.describe()


def test_tuck_fizzles_and_describe():
    eff = PutTargetIntoOwnersLibraryNthFromTop(
        position=3, targets=(TargetSpec(filter=IsCreature()),),
    )
    s = _state()
    eff.resolve(s, 0, ())
    eff.resolve(s, 0, (("creature", 99),))
    assert "3 from the top" in eff.describe()


def test_create_emblem_with_abilities_describe():
    s = _state()
    eff = CreateEmblemWithAbilities(name="probe emblem")
    eff.resolve(s, 1)
    assert s.emblems[0].controller_id == 1
    assert "probe emblem" in eff.describe()


def test_spell_target_binding_edge_cases():
    from mtg_bot.effects.generic.cube_walkers import (
        GainControlOfTriggeringSpellTargets,
        IsPermanent,
        SpellTargetsMatching,
    )
    from mtg_bot.game import StackItem

    s = _state()
    rock = _bf(s, make_artifact("Rock", "{2}"), 1)
    mine = _bf(s, make_artifact("Mine", "{2}"), 0)
    spell = s.new_object(make_artifact("Spell", "{1}"), 0, Zone.STACK)
    pred = SpellTargetsMatching(IsPermanent())
    assert not pred.test(spell, s)  # not on the stack
    s.stack.append(StackItem(
        source=spell, controller_id=0,
        targets=(("player", 1), ("permanent", 999), ("permanent", rock.id),
                 ("permanent", mine.id)),
    ))
    assert pred.test(spell, s)
    eff = GainControlOfTriggeringSpellTargets(IsPermanent())
    bound = eff.targets_from_event(s, {"spell": spell})
    assert bound == (("permanent", rock.id), ("permanent", mine.id))
    assert eff.targets_from_event(s, {}) == ()
    s.battlefield.remove(mine)
    eff.resolve(s, 0, bound + (("permanent", mine.id),))
    assert rock.controller_id == 0
    eff.resolve(s, 0, (("permanent", rock.id),))  # already yours: no-op
    assert "targeted permanents" in eff.describe()


def test_karn_shapes_parse():
    from mtg_bot.effects.generic.cube_walkers import (
        PutCardYouOwnWithCounterFromExileIntoHand,
        RevealTopNOpponentChoosesOneRestExiledWithCounter,
    )
    assert _parse_effect(
        "reveal the top two cards of your library. An opponent chooses "
        "one of them. Put that card into your hand and exile the other "
        "with a silver counter on it"
    ) == RevealTopNOpponentChoosesOneRestExiledWithCounter(
        n=2, counter="silver",
    )
    assert _parse_effect(
        "put a card you own with a silver counter on it from exile into "
        "your hand"
    ) == PutCardYouOwnWithCounterFromExileIntoHand(counter="silver")
    tok = _parse_effect(
        'create a 0/0 colorless Construct artifact creature token with '
        '"This token gets +1/+1 for each artifact you control."'
    )
    anthem = tok.token_printing.static_abilities[0]
    assert anthem.bonus_per_condition_count
    assert (anthem.power_bonus, anthem.toughness_bonus) == (1, 1)
    assert parse_ext_effect(
        'create a 0/0 colorless Construct artifact creature token with '
        '"This token gets +1/+1 for each spell you control."'
    ) is None
    assert "silver" in RevealTopNOpponentChoosesOneRestExiledWithCounter(
    ).describe()
    assert "exile" in PutCardYouOwnWithCounterFromExileIntoHand().describe()


def test_karn_plus_one_without_opponent_agent_takes_first():
    from mtg_bot.effects.generic.cube_walkers import (
        RevealTopNOpponentChoosesOneRestExiledWithCounter,
    )
    s = _state()
    p = s.player_by_id(0)
    lib = [s.new_object(BASIC_LANDS["Forest"], 0, Zone.LIBRARY)
           for _ in range(2)]
    p.library.extend(lib)
    RevealTopNOpponentChoosesOneRestExiledWithCounter().resolve(s, 0)
    assert p.hand == [lib[0]] and p.exile == [lib[1]]


def test_draws_card_event_fires_once_per_card():
    from mtg_bot.cards.base import make_emblem
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import YOU, Controlled
    from mtg_bot.turn import draw_n_cards

    s = _state()
    trig = TriggeredAbility(
        event=Event.DRAWS_CARD, predicate=Controlled(YOU),
        effect=DrawCards(amount=0),
    )
    emblem = s.new_object(
        make_emblem("probe", triggered_abilities=(trig,)), 0, Zone.COMMAND,
    )
    s.emblems.append(emblem)
    s.player_by_id(0).library.extend(
        s.new_object(BASIC_LANDS["Forest"], 0, Zone.LIBRARY) for _ in range(3)
    )
    draw_n_cards(s, 0, 3)
    assert len(s.stack) == 3
