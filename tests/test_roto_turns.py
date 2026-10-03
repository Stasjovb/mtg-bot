"""Vintage Roto P4 turn structure (``mtg_bot.roto_turns``): "Skip your
draw step." (Yawgmoth's Bargain, Necropotence), "your next end step"
delayed triggers -- exercised through BOTH turn loops
(``simulate.run_turn`` and the search adapter)."""

from __future__ import annotations

from dataclasses import dataclass

from mtg_bot.actions import (
    ActivateAbility,
    PassPriority,
    _activate_ability,
    drain_stack,
    resolve_top_of_stack,
)
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.cards.base import make_creature, make_instant
from mtg_bot.effects.generic import DrawCards
from mtg_bot.effects.generic.roto_walkers import (
    EndTheTurn,
    LoseTheGame,
    PutExiledSourceIntoOwnersHand,
    TakeExtraTurnWithEndStepTrigger,
)
from mtg_bot.game import StackItem, Zone
from mtg_bot.legal import legal_actions
from mtg_bot.roto_turns import (
    end_the_turn,
    schedule_at_your_next_end_step,
    skips_draw_step,
    turn_structure_next_step,
)
from mtg_bot.simulate import _advance_to_next_active_player, run_step, run_turn
from mtg_bot.turn import Step, next_step

from tests._roto_helpers import (
    ScriptedAgent,
    arena,
    printing,
    put,
    to_hand,
    to_library,
)


@dataclass
class PassAgent(ScriptedAgent):
    """Passes priority, never attacks or blocks."""

    def choose_action(self, state, player_id, legal):
        return PassPriority()

    def declare_attackers(self, state, player_id, eligible):
        return []

    def declare_blockers(self, state, player_id, eligible, attackers):
        return {}


def passing_arena(active: int = 0):
    s = arena(active=active)
    for p in s.players:
        p.agent = PassAgent()
    s.turn_number = 3
    for pid in (0, 1):
        for _ in range(5):
            to_library(s, BASIC_LANDS["Island"], pid)
    return s


# ---------------------------------------------------------------------------
# Skip your draw step
# ---------------------------------------------------------------------------


def test_bargain_parses_skip_draw_static_and_pay_life_draw():
    p = printing("Yawgmoth's Bargain")
    (static,) = p.static_abilities
    assert static.skips_your_draw_step
    (ability,) = p.activated_abilities
    assert ability.cost.pay_life == 1


def test_skips_draw_step_only_for_the_controller():
    s = passing_arena()
    assert not skips_draw_step(s, 0)
    put(s, printing("Yawgmoth's Bargain"), 0)
    assert skips_draw_step(s, 0)
    assert not skips_draw_step(s, 1)


def test_next_step_skips_draw_for_bargain_controller_only():
    s = passing_arena(active=0)
    put(s, printing("Yawgmoth's Bargain"), 0)
    assert next_step(s, Step.UPKEEP) == Step.PRECOMBAT_MAIN
    assert any("skips their draw step" in line for line in s.log)
    s.active_player_idx = 1
    assert next_step(s, Step.UPKEEP) == Step.DRAW
    # Only the upkeep -> draw transition is replaced.
    s.active_player_idx = 0
    assert turn_structure_next_step(s, Step.PRECOMBAT_MAIN) is None


def test_run_turn_bargain_controller_draws_nothing():
    s = passing_arena(active=0)
    s.step = Step.UNTAP
    put(s, printing("Yawgmoth's Bargain"), 0)
    run_turn(s)
    assert len(s.players[0].hand) == 0
    assert len(s.players[0].library) == 5


def test_run_turn_opponent_still_draws():
    s = passing_arena(active=1)
    s.step = Step.UNTAP
    put(s, printing("Yawgmoth's Bargain"), 0)
    run_turn(s)
    assert len(s.players[1].hand) == 1


def test_bargain_leaving_restores_the_draw():
    s = passing_arena(active=0)
    bargain = put(s, printing("Yawgmoth's Bargain"), 0)
    s.battlefield.remove(bargain)
    assert next_step(s, Step.UPKEEP) == Step.DRAW


def test_skip_draw_step_via_search_adapter():
    from mtg_bot.search.engine_adapter import MtgGameStateAdapter

    s = passing_arena(active=0)
    s.step = Step.UPKEEP
    put(s, printing("Yawgmoth's Bargain"), 0)
    adapter = MtgGameStateAdapter(s, expose_combat_decisions=False)
    adapter._advance_to_next_step()
    assert adapter.engine_state.step == Step.PRECOMBAT_MAIN
    assert len(adapter.engine_state.players[0].hand) == 0


def test_bargain_pay_one_life_draws():
    s = passing_arena(active=0)
    bargain = put(s, printing("Yawgmoth's Bargain"), 0)
    _activate_ability(s, 0, bargain.id, 0)
    drain_stack(s)
    assert s.players[0].life == 19
    assert len(s.players[0].hand) == 1


# ---------------------------------------------------------------------------
# "At the beginning of your next end step"
# ---------------------------------------------------------------------------


def _exiled_card(s, pid=0):
    card = s.new_object(BASIC_LANDS["Island"], owner_id=pid, zone=Zone.EXILE)
    s.players[pid].exile.append(card)
    return card


def test_next_end_step_on_your_turn_fires_this_turn():
    s = passing_arena(active=0)
    card = _exiled_card(s)
    schedule_at_your_next_end_step(s, 0, card.id, PutExiledSourceIntoOwnersHand())
    (entry,) = s.delayed_triggers
    assert entry["fire_at_turn"] == 3 and entry["own_next_end_step"]
    run_step(s, Step.END)
    assert card in s.players[0].hand


def test_next_end_step_during_your_end_step_waits_for_next_own_turn():
    s = passing_arena(active=0)
    s.step = Step.END
    card = _exiled_card(s)
    schedule_at_your_next_end_step(s, 0, card.id, PutExiledSourceIntoOwnersHand())
    # The opponent's turn (4) doesn't fire it ...
    s.turn_number, s.active_player_idx = 4, 1
    run_step(s, Step.END)
    assert card in s.players[0].exile
    # ... and an intervening extra turn of the opponent doesn't lose it.
    s.turn_number = 5
    run_step(s, Step.END)
    assert card in s.players[0].exile
    s.turn_number, s.active_player_idx = 6, 0
    run_step(s, Step.END)
    assert card in s.players[0].hand
    assert s.delayed_triggers == []


def test_next_end_step_on_opponents_turn_is_your_following_turn():
    s = passing_arena(active=1)
    card = _exiled_card(s)
    schedule_at_your_next_end_step(s, 0, card.id, PutExiledSourceIntoOwnersHand())
    run_step(s, Step.END)
    assert card in s.players[0].exile
    s.turn_number, s.active_player_idx = 4, 0
    run_step(s, Step.END)
    assert card in s.players[0].hand


def test_put_exiled_source_into_hand_ignores_a_card_that_left_exile():
    s = passing_arena(active=0)
    card = _exiled_card(s)
    schedule_at_your_next_end_step(s, 0, card.id, PutExiledSourceIntoOwnersHand())
    s.players[0].exile.remove(card)
    card.zone = Zone.GRAVEYARD
    s.players[0].graveyard.append(card)
    run_step(s, Step.END)
    assert card in s.players[0].graveyard
    assert PutExiledSourceIntoOwnersHand().describe() == (
        "put that card into your hand"
    )


def test_put_exiled_source_into_hand_without_source_is_noop():
    s = passing_arena(active=0)
    PutExiledSourceIntoOwnersHand().resolve(s, 0, ())
    card = _exiled_card(s)
    s.players[0].exile.remove(card)  # zone says exile, list doesn't
    s.resolving_source = card
    PutExiledSourceIntoOwnersHand().resolve(s, 0, ())
    assert card not in s.players[0].hand


# ---------------------------------------------------------------------------
# End the turn (Sundial of the Infinite, Day's Undoing)
# ---------------------------------------------------------------------------

_OPT = make_instant("Opt Stand-in", "{U}", DrawCards(amount=1))


def _cast_on_stack(s, printing_, controller):
    card = s.new_object(printing_, owner_id=controller, zone=Zone.STACK)
    s.stack.append(StackItem(source=card, controller_id=controller))
    return card


def _sundial(s, pid=0):
    sundial = put(s, printing("Sundial of the Infinite"), pid)
    for _ in range(2):
        put(s, BASIC_LANDS["Island"], pid)
    return sundial


def test_sundial_parse_shape():
    (ability,) = printing("Sundial of the Infinite").activated_abilities
    assert ability.effect == EndTheTurn()
    assert ability.cost.tap_self and ability.activate_only_during_your_turn
    assert EndTheTurn().describe() == "end the turn"


def test_sundial_ends_the_turn_exiling_the_stack():
    s = passing_arena(active=0)
    sundial = _sundial(s)
    opp_spell = _cast_on_stack(s, _OPT, 1)
    _activate_ability(s, 0, sundial.id, 0)
    resolve_top_of_stack(s)
    assert s.stack == []
    assert opp_spell in s.players[1].exile
    assert s.turn_ending
    # Nobody gets priority: only passing is legal.
    assert legal_actions(s, 0) == [PassPriority()]
    assert next_step(s, Step.PRECOMBAT_MAIN) == Step.CLEANUP
    assert not s.turn_ending


def test_sundial_only_during_your_turn():
    s = passing_arena(active=1)
    sundial = _sundial(s, 0)
    s.priority_player_idx = 0
    acts = [a for a in legal_actions(s, 0) if isinstance(a, ActivateAbility)]
    assert all(a.source_id != sundial.id for a in acts)
    s.active_player_idx = 0
    acts = [a for a in legal_actions(s, 0) if isinstance(a, ActivateAbility)]
    assert any(a.source_id == sundial.id for a in acts)


def test_end_the_turn_removes_creatures_from_combat_and_drops_copies():
    s = passing_arena(active=0)
    bear = put(s, make_creature("Bear", "{1}{G}", 2, 2), 0)
    bear.attacking = True
    copy = _cast_on_stack(s, _OPT, 1)
    copy.is_spell_copy = True
    end_the_turn(s)
    assert not bear.attacking
    assert copy not in s.players[1].exile


@dataclass
class SundialAgent(PassAgent):
    """Activates Sundial of the Infinite at its first chance."""

    def choose_action(self, state, player_id, legal):
        for a in legal:
            if isinstance(a, ActivateAbility):
                src = next(o for o in state.battlefield if o.id == a.source_id)
                if src.printing.name == "Sundial of the Infinite":
                    return a
        return PassPriority()


def test_run_turn_after_sundial_skips_to_cleanup():
    s = passing_arena(active=0)
    s.step = Step.UNTAP
    _sundial(s)
    s.players[0].agent = SundialAgent()
    steps: list = []
    run_turn(s, on_snapshot=lambda st: steps.append(st.step))
    # Activated abilities are offered whenever their controller has
    # priority (CR 117.1b), so Sundial is activated -- and resolves --
    # in the upkeep, its first window; the draw step, both main phases,
    # combat and the end step are skipped.
    assert steps == [Step.UNTAP, Step.UPKEEP, Step.CLEANUP]
    assert any("the turn is ended" in line for line in s.log)
    assert not s.turn_ending


def test_turn_ending_via_search_adapter():
    from mtg_bot.search.engine_adapter import MtgGameStateAdapter

    s = passing_arena(active=0)
    s.step = Step.PRECOMBAT_MAIN
    s.turn_ending = True
    adapter = MtgGameStateAdapter(s, expose_combat_decisions=False)
    assert adapter.legal_decisions() == [PassPriority()]
    adapter._advance_to_next_step()
    assert adapter.engine_state.step == Step.CLEANUP


def test_turn_ending_survives_clone():
    s = passing_arena()
    s.turn_ending = True
    assert s.clone().turn_ending


def test_days_undoing_on_your_turn_wheels_and_ends_the_turn():
    s = passing_arena(active=0)
    to_hand(s, BASIC_LANDS["Swamp"], 0)
    undoing = _cast_on_stack(s, printing("Day's Undoing"), 0)
    resolve_top_of_stack(s)
    assert len(s.players[0].hand) == 6 and len(s.players[1].hand) == 5
    assert undoing in s.players[0].exile
    assert s.turn_ending


def test_days_undoing_on_opponents_turn_doesnt_end_it():
    s = passing_arena(active=1)
    undoing = _cast_on_stack(s, printing("Day's Undoing"), 0)
    resolve_top_of_stack(s)
    assert not s.turn_ending
    assert undoing in s.players[0].graveyard


# ---------------------------------------------------------------------------
# Final Fortune
# ---------------------------------------------------------------------------


def test_final_fortune_parse_shape():
    eff = printing("Final Fortune").spell_effect
    assert eff == TakeExtraTurnWithEndStepTrigger(inner=LoseTheGame())
    assert "that turn's end step, you lose the game" in eff.describe()


def _finish_turn(s):
    """Finish the current turn from its end step, then start the next."""
    for step in (Step.END, Step.CLEANUP):
        run_step(s, step)
    s.turn_number += 1
    _advance_to_next_active_player(s)
    s.step = Step.UNTAP


def _final_fortune(s):
    _cast_on_stack(s, printing("Final Fortune"), 0)
    resolve_top_of_stack(s)
    assert s.extra_turn_queue == [0]
    _finish_turn(s)


def test_final_fortune_takes_extra_turn_then_loses_at_its_end_step():
    s = passing_arena(active=0)
    _final_fortune(s)
    assert s.active_player_idx == 0 and s.turn_number == 4
    assert not s.players[0].has_lost  # not the casting turn's end step
    run_turn(s)
    assert s.players[0].has_lost
    assert s.winner_id == 1


def test_final_fortune_loss_dodged_by_ending_the_turn():
    s = passing_arena(active=0)
    _sundial(s)
    _final_fortune(s)
    s.players[0].agent = SundialAgent()
    run_turn(s)
    assert not s.players[0].has_lost and s.winner_id is None
    # The trigger belonged to that turn only.
    s.turn_number += 1
    _advance_to_next_active_player(s)
    s.step = Step.UNTAP
    s.players[0].agent = PassAgent()
    run_turn(s)
    assert not s.players[0].has_lost


def test_final_fortune_behind_an_earlier_extra_turn():
    s = passing_arena(active=0)
    s.extra_turn_queue.append(0)  # e.g. a Time Walk resolved first
    _cast_on_stack(s, printing("Final Fortune"), 0)
    resolve_top_of_stack(s)
    (entry,) = s.delayed_triggers
    assert entry["fire_at_turn"] == s.turn_number + 2


def test_extra_turn_trigger_without_a_source_still_queues():
    s = passing_arena(active=0)
    TakeExtraTurnWithEndStepTrigger(inner=LoseTheGame()).resolve(s, 0, ())
    assert s.extra_turn_queue == [0] and s.delayed_triggers == []


def test_lose_the_game_is_idempotent():
    s = passing_arena()
    LoseTheGame().resolve(s, 1, ())
    LoseTheGame().resolve(s, 1, ())
    assert s.players[1].has_lost
    assert LoseTheGame().describe() == "you lose the game"


# ---------------------------------------------------------------------------
# Outside the game: sideboards (user's decision, 2026-10-02) + Burning Wish
# ---------------------------------------------------------------------------


@dataclass
class ModeAgent(PassAgent):
    """Answers ``choose_mode`` with a fixed index (records the options)."""

    mode: int = 0
    seen: list = None

    def choose_mode(self, state, player_id, mode_descriptions):
        self.seen = list(mode_descriptions)
        return self.mode


def _setup(sideboards=None):
    from mtg_bot.simulate import setup_game

    decks = [["Island"] * 20, ["Island"] * 20]
    return setup_game(
        [PassAgent(), PassAgent()], decks=decks, seed=1,
        enable_mulligans=False, sideboards=sideboards,
    )


def test_setup_game_sideboards_default_empty():
    s = _setup()
    assert [p.sideboard for p in s.players] == [(), ()]


def test_setup_game_sideboards_are_printings_outside_the_game():
    s = _setup([["Demonic Tutor", "Time Walk", "Black Lotus"], []])
    names = [pr.name for pr in s.players[0].sideboard]
    assert names == ["Demonic Tutor", "Time Walk", "Black Lotus"]
    assert s.players[1].sideboard == ()
    # Not game objects: no zone holds them.
    assert all(
        o.printing.name == "Island"
        for p in s.players for o in (*p.library, *p.hand)
    )
    assert s.clone().players[0].sideboard == s.players[0].sideboard


def test_setup_game_sideboards_validated():
    import pytest

    with pytest.raises(ValueError, match="sideboards length"):
        _setup([["Time Walk"]])
    with pytest.raises(ValueError, match="unknown cards"):
        _setup([["Not A Real Card"], []])


def test_take_from_outside_the_game():
    import pytest

    from mtg_bot.roto_turns import take_from_outside_the_game

    s = _setup([["Time Walk", "Time Walk"], []])
    walk = s.players[0].sideboard[0]
    card = take_from_outside_the_game(s, 0, walk)
    assert card in s.players[0].hand and card.owner_id == 0
    assert card.zone == Zone.HAND
    assert len(s.players[0].sideboard) == 1
    assert 1 in card.publicly_known_to
    with pytest.raises(ValueError, match="owns no Time Walk"):
        take_from_outside_the_game(s, 1, walk)


def _wish_arena(sideboard_names, mode=0):
    from mtg_bot.cards.source import get_active_source

    s = passing_arena(active=0)
    printings = get_active_source().get_printings()
    s.players[0].sideboard = tuple(printings[n] for n in sideboard_names)
    s.players[0].agent = ModeAgent(mode=mode)
    return s


def test_burning_wish_parse_shape():
    from mtg_bot.effects.generic.card_flow import ExileThisSpell
    from mtg_bot.effects.generic.roto_walkers import (
        PutCardFromOutsideTheGameIntoHand,
    )

    eff = printing("Burning Wish").spell_effect
    wish, exile_self = eff.effects
    assert isinstance(wish, PutCardFromOutsideTheGameIntoHand)
    assert wish.card_filter.any_types == ("Sorcery",)
    assert isinstance(exile_self, ExileThisSpell)
    assert wish.describe() == (
        "you may reveal a sorcery card you own from outside the game and "
        "put it into your hand"
    )


def test_burning_wish_fetches_a_sorcery_and_exiles_itself():
    s = _wish_arena(["Lightning Bolt", "Time Walk", "Demonic Tutor"], mode=1)
    wish = _cast_on_stack(s, printing("Burning Wish"), 0)
    resolve_top_of_stack(s)
    agent0 = s.players[0].agent
    # Only sorceries are offered, sorted, plus "nothing".
    assert agent0.seen == [
        "reveal Demonic Tutor", "reveal Time Walk", "reveal nothing",
    ]
    (fetched,) = s.players[0].hand
    assert fetched.printing.name == "Time Walk"
    assert [pr.name for pr in s.players[0].sideboard] == [
        "Lightning Bolt", "Demonic Tutor",
    ]
    assert wish in s.players[0].exile and wish not in s.players[0].graveyard


def test_burning_wish_may_reveal_nothing():
    s = _wish_arena(["Time Walk"], mode=1)
    _cast_on_stack(s, printing("Burning Wish"), 0)
    resolve_top_of_stack(s)
    assert s.players[0].hand == []
    assert len(s.players[0].sideboard) == 1


def test_burning_wish_with_no_sorcery_outside_the_game():
    s = _wish_arena(["Lightning Bolt"])
    wish = _cast_on_stack(s, printing("Burning Wish"), 0)
    resolve_top_of_stack(s)
    assert s.players[0].hand == [] and s.players[0].agent.seen is None
    assert wish in s.players[0].exile


def test_wish_without_filter_or_agent():
    from mtg_bot.effects.generic.roto_walkers import (
        PutCardFromOutsideTheGameIntoHand,
    )

    s = _wish_arena(["Lightning Bolt"])
    eff = PutCardFromOutsideTheGameIntoHand()
    assert "a card you own" in eff.describe()
    s.players[0].agent = None
    eff.resolve(s, 0, ())
    assert s.players[0].hand == []
    s.players[0].agent = ModeAgent(mode=0)
    eff.resolve(s, 0, ())
    assert [c.printing.name for c in s.players[0].hand] == ["Lightning Bolt"]
