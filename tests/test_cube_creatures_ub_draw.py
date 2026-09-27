"""U/B cube creatures: draw observers ("whenever an opponent draws a
card"), the per-card draw replacement (Hullbreacher), Amass, and the
"When X and whenever Y" compound trigger (Orcish Bowmasters)."""

from __future__ import annotations

from functools import lru_cache

from mtg_bot.actions import drain_stack
from mtg_bot.agents import Agent
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.cards.base import make_creature
from mtg_bot.cards.parser.cube_creatures_ub import (
    UBLine,
    bind_event_player_anaphora,
    parse_ub_creature_line,
    parse_ub_effect,
    parse_ub_trigger_phrase,
)
from mtg_bot.cards.parser.effects import _parse_effect
from mtg_bot.cards.parser.source import _build_printing
from mtg_bot.cards.parser.triggers import _parse_triggered_ability_line
from mtg_bot.cards.pools import load_pool_cards
from mtg_bot.effects.generic.cube_creatures_ub import Amass, BindEventPlayer
from mtg_bot.effects.generic.life import GainLife, TargetPlayerLosesLife
from mtg_bot.effects.modifiers import InsteadForSourceController
from mtg_bot.effects.object_predicates import (
    DrawIsFirstInOwnDrawStep,
    HasDrawnNCardsThisTurn,
)
from mtg_bot.effects.predicates import Event
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step, draw_n_cards, run_draw_step


class _Agent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        # Aim damage at the opponent when a player is a legal target.
        for t in legal_targets:
            if t == ("player", 1 - player_id):
                return t
        return legal_targets[0] if legal_targets else None

    def choose_yes_no(self, state, player_id, prompt):
        return True


@lru_cache(maxsize=None)
def _cube(name):
    card = next(c for c in load_pool_cards("cube") if c["name"] == name)
    printing = _build_printing(card)
    assert printing is not None, name
    return printing


def _state() -> GameState:
    state = GameState()
    state.players.append(Player(id=0, agent=_Agent()))
    state.players.append(Player(id=1, agent=_Agent()))
    state.step = Step.PRECOMBAT_MAIN
    for p in state.players:
        for _ in range(10):
            _put(state, BASIC_LANDS["Island"], p.id, Zone.LIBRARY)
    return state


def _put(state, printing, owner, zone=Zone.BATTLEFIELD):
    obj = state.new_object(printing, owner, zone)
    obj.summoning_sick = False
    {
        Zone.HAND: state.players[owner].hand,
        Zone.LIBRARY: state.players[owner].library,
        Zone.GRAVEYARD: state.players[owner].graveyard,
        Zone.BATTLEFIELD: state.battlefield,
    }[zone].append(obj)
    return obj


# ---------------------------------------------------------------- grammar


def test_draw_trigger_phrases():
    event, pred = parse_ub_trigger_phrase("an opponent draws a card")
    assert event is Event.DRAWS_CARD
    assert parse_ub_trigger_phrase("a player draws a card") is not None
    assert parse_ub_trigger_phrase("you draw your second card each turn")
    assert parse_ub_trigger_phrase(
        "an opponent draws a card except the first one they draw in each "
        "of their draw steps"
    )
    assert parse_ub_trigger_phrase("an opponent casts a spell") is None


def test_they_anaphora_binds_only_on_draw_events():
    inner = TargetPlayerLosesLife(amount=2)
    bound = bind_event_player_anaphora(Event.DRAWS_CARD, inner)
    assert bound == BindEventPlayer(inner=inner)
    assert bind_event_player_anaphora(Event.DISCARDS_CARD, inner) is inner
    assert not bound.requires_target() and bound.legal_targets(None, 0) == []
    assert bound.targets_from_event(None, {}) == ()
    assert bound.describe() == inner.describe()


def test_amass_phrase():
    assert parse_ub_effect("amass Orcs 1") == Amass(subtype="Orc", amount=1)
    assert parse_ub_effect("amass Zombies 2") == Amass(subtype="Zombie", amount=2)
    assert parse_ub_effect("amass") is None
    assert Amass(subtype="Orc", amount=1).describe() == "amass Orcs 1"


def test_when_and_whenever_line_yields_two_arms():
    arms = _parse_triggered_ability_line(
        "When this creature enters and whenever an opponent draws a card, "
        "you gain 1 life."
    )
    assert [a.event for a in arms] == [Event.ENTERS, Event.DRAWS_CARD]
    assert all(a.effect == GainLife(amount=1) for a in arms)
    assert _parse_triggered_ability_line(
        "When this creature enters and whenever you frobnicate, you gain 1 life."
    ) is None
    assert _parse_triggered_ability_line(
        "When this creature enters and whenever an opponent draws a card, "
        "frobnicate."
    ) is None


def test_draw_replacement_line_shapes():
    out = parse_ub_creature_line(
        "If an opponent would draw a card except the first one they draw in "
        "each of their draw steps, instead you create a Treasure token.",
        "X",
    )
    assert isinstance(out, UBLine)
    rep = out.statics[0].replacement_effect
    assert rep.affects == "opponents"
    assert rep.event_pattern.event is Event.WOULD_DRAW_A_CARD
    assert isinstance(rep.transform, InsteadForSourceController)
    mine = parse_ub_creature_line(
        "If you would draw a card, instead you gain 1 life.", "X",
    )
    assert mine.statics[0].replacement_effect.affects == "you"
    assert mine.statics[0].replacement_effect.event_pattern.subject_filters == ()
    # Targeted substitutes aren't supported; unknown bodies decline.
    assert parse_ub_creature_line(
        "If you would draw a card, instead destroy target creature.", "X",
    ) is None
    assert parse_ub_creature_line(
        "If you would draw a card, instead frobnicate.", "X",
    ) is None


def test_cube_printings_claim():
    for name in (
        "Sheoldred, the Apocalypse", "Faerie Mastermind",
        "Orcish Bowmasters", "Hullbreacher",
    ):
        assert _cube(name) is not None
    sheol = _cube("Sheoldred, the Apocalypse")
    opp = sheol.triggered_abilities[1]
    assert opp.event is Event.DRAWS_CARD
    assert opp.effect == BindEventPlayer(inner=TargetPlayerLosesLife(amount=2))


# ---------------------------------------------------------------- engine


def test_sheoldred_drains_opponent_draws_and_heals_yours():
    state = _state()
    _put(state, _cube("Sheoldred, the Apocalypse"), 0)
    draw_n_cards(state, 1, 2)
    drain_stack(state)
    assert state.players[1].life == 16
    draw_n_cards(state, 0, 1)
    drain_stack(state)
    assert state.players[0].life == 22


def test_faerie_mastermind_triggers_on_second_opponent_draw_only():
    state = _state()
    _put(state, _cube("Faerie Mastermind"), 0)
    draw_n_cards(state, 1, 1)
    drain_stack(state)
    assert len(state.players[0].hand) == 0
    draw_n_cards(state, 1, 1)
    drain_stack(state)
    assert len(state.players[0].hand) == 1
    draw_n_cards(state, 1, 1)
    drain_stack(state)
    assert len(state.players[0].hand) == 1
    # Its own controller's draws never count.
    draw_n_cards(state, 0, 2)
    drain_stack(state)
    assert len(state.players[0].hand) == 3


def test_bowmasters_skips_the_draw_step_draw_and_amasses():
    state = _state()
    bow = _put(state, _cube("Orcish Bowmasters"), 0)
    state.active_player_idx = 1
    state.step = Step.DRAW
    run_draw_step(state)
    assert not state.stack
    assert not state.players[1].draw_step_first_draw_pending
    draw_n_cards(state, 1, 1)
    assert len(state.stack) == 1
    drain_stack(state)
    armies = [o for o in state.battlefield if "Army" in o.printing.subtypes]
    assert len(armies) == 1 and armies[0].plus_one_counters == 1
    assert armies[0].printing.subtypes == ("Orc", "Army")
    assert state.players[1].life == 19
    assert bow in state.battlefield
    # A second trigger amasses onto the same Army.
    draw_n_cards(state, 1, 1)
    drain_stack(state)
    armies = [o for o in state.battlefield if "Army" in o.printing.subtypes]
    assert len(armies) == 1 and armies[0].plus_one_counters == 2


def test_amass_adds_the_subtype_to_an_existing_army():
    state = _state()
    other = make_creature("Zombie Army", "", 0, 0, subtypes=("Zombie", "Army"))
    army = _put(state, other, 0)
    Amass(subtype="Orc", amount=2).resolve(state, 0, ())
    assert army.plus_one_counters == 2
    assert "Orc" in army.printing.subtypes
    # Two Armies: the agent picks one.
    _put(state, other, 0)
    Amass(subtype="Orc", amount=1).resolve(state, 0, ())
    assert army.plus_one_counters == 3


def test_hullbreacher_replaces_all_but_the_draw_step_draw():
    state = _state()
    _put(state, _cube("Hullbreacher"), 0)
    state.active_player_idx = 1
    state.step = Step.DRAW
    run_draw_step(state)
    assert len(state.players[1].hand) == 1
    draw_n_cards(state, 1, 2)
    assert len(state.players[1].hand) == 1
    assert state.players[1].cards_drawn_this_turn == 1
    treasures = [o for o in state.battlefield if o.printing.name == "Treasure"]
    assert len(treasures) == 2 and all(t.controller_id == 0 for t in treasures)
    # Its controller's own draws are untouched.
    draw_n_cards(state, 0, 1)
    assert len(state.players[0].hand) == 1


def test_draw_predicates_read_the_player():
    p = Player(id=0)
    assert not DrawIsFirstInOwnDrawStep().test(p, None)
    p.drawing_first_in_draw_step = True
    assert DrawIsFirstInOwnDrawStep().test(p, None)
    p.cards_drawn_this_turn = 2
    assert HasDrawnNCardsThisTurn(2).test(p, None)
    assert not HasDrawnNCardsThisTurn(2).test(object(), None)


def test_bowmasters_etb_arm_pings_on_entry():
    state = _state()
    from mtg_bot.actions import put_into_battlefield

    bow = state.new_object(_cube("Orcish Bowmasters"), 0, Zone.HAND)
    put_into_battlefield(state, bow, 0)
    assert len(state.stack) == 1
    drain_stack(state)
    assert any("Army" in o.printing.subtypes for o in state.battlefield)


def test_draw_effect_parses_through_the_unified_grammar():
    # "this creature deals ..." falls back to the subject-less grammar.
    assert _parse_effect("this creature deals 1 damage to any target") is not None
    assert _parse_effect("this creature deals frobnicate") is None
