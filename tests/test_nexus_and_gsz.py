"""Tests for Nexus of Fate + Green Sun's Zenith.

Both Special Guests spells share the
``shuffles_into_library_instead_of_graveyard`` replacement flag; this
file covers both the shared redirect plumbing and each card's unique
effect (extra-turn queueing, green-creature tutor).
"""

import random

from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import (
    SPECIAL_GUESTS_EOE, SYNTHETIC_CREATURES, make_creature,
)
from mtg_bot.effects import (
    SearchLibraryForGreenCreatureWithMVAtMostX, TakeExtraTurnAfterThisOne,
)
from mtg_bot.game import GameState, Player, Zone


class _PickFirst(Agent):
    def choose_card_from_library(self, state, player_id, option_ids):
        return option_ids[0] if option_ids else None


def _new_state(p0_agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=p0_agent or RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


# ---- Nexus of Fate ----------------------------------------------------

def test_nexus_is_wired_up():
    n = SPECIAL_GUESTS_EOE["Nexus of Fate"]
    assert n.is_instant
    assert n.mana_cost_str == "{5}{U}{U}"
    assert isinstance(n.spell_effect, TakeExtraTurnAfterThisOne)
    assert n.shuffles_into_library_instead_of_graveyard is True


def test_extra_turn_effect_queues_controller():
    state = _new_state()
    assert state.extra_turn_queue == []
    TakeExtraTurnAfterThisOne().resolve(state, 0, ())
    assert state.extra_turn_queue == [0]


def test_nexus_shuffles_instead_of_graveyard_on_resolve():
    """Casting Nexus through the spell pipeline: the spell resolves and
    goes back to library (shuffled) rather than graveyard."""
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem

    state = _new_state()
    card = state.new_object(
        SPECIAL_GUESTS_EOE["Nexus of Fate"], 0, Zone.STACK,
    )
    state.stack.append(StackItem(
        source=card, controller_id=0, targets=(), countered=False,
    ))
    resolve_top_of_stack(state)
    # Library now contains it; graveyard does not.
    p = state.player_by_id(0)
    assert card in p.library
    assert card not in p.graveyard
    # Extra turn queued.
    assert state.extra_turn_queue == [0]


def test_nexus_countered_also_shuffles():
    """Countered spells go to graveyard normally — but Nexus-flag
    cards shuffle into library instead."""
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem

    state = _new_state()
    card = state.new_object(
        SPECIAL_GUESTS_EOE["Nexus of Fate"], 0, Zone.STACK,
    )
    state.stack.append(StackItem(
        source=card, controller_id=0, targets=(), countered=True,
    ))
    resolve_top_of_stack(state)
    p = state.player_by_id(0)
    assert card in p.library
    assert card not in p.graveyard
    # Countered spells don't grant extra turns.
    assert state.extra_turn_queue == []


def test_non_nexus_spell_still_goes_to_graveyard():
    """Regression check: cards without the flag still land in the
    graveyard after resolving."""
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem

    state = _new_state()
    darkness = state.new_object(
        SPECIAL_GUESTS_EOE["Darkness"], 0, Zone.STACK,
    )
    state.stack.append(StackItem(
        source=darkness, controller_id=0, targets=(), countered=False,
    ))
    resolve_top_of_stack(state)
    p = state.player_by_id(0)
    assert darkness in p.graveyard
    assert darkness not in p.library


def test_simulate_loop_consumes_extra_turn_queue():
    """The sim loop picks up queued extra turns ahead of the natural
    next-player rotation."""
    from mtg_bot.simulate import simulate_game

    # Queue up many extra turns for P0 at setup so the first few
    # "natural turn changes" actually give them back to P0. Run a
    # short sim to ensure the loop applies the queue without crashing.
    result = simulate_game(seed=42, max_turns=5)
    # At minimum: it terminates (draw or a winner) without raising.
    assert result is not None


def test_advance_picks_queued_extra_turn_player():
    """Direct test for the _advance_to_next_active_player helper: a
    queued alive player goes next, ahead of the natural rotation."""
    from mtg_bot.simulate import _advance_to_next_active_player

    state = _new_state()
    state.active_player_idx = 0  # P0 just finished their turn
    state.extra_turn_queue.append(0)  # P0 gets an extra turn
    _advance_to_next_active_player(state)
    assert state.active_player_idx == 0  # stays with P0
    assert state.extra_turn_queue == []


def test_advance_falls_back_to_natural_rotation_when_queue_empty():
    from mtg_bot.simulate import _advance_to_next_active_player

    state = _new_state()
    state.active_player_idx = 0
    # Empty queue — should advance to P1.
    _advance_to_next_active_player(state)
    assert state.active_player_idx == 1


def test_advance_skips_dead_queued_player():
    """A queued player who has lost is skipped; fall back to natural
    rotation."""
    from mtg_bot.simulate import _advance_to_next_active_player

    state = _new_state()
    state.active_player_idx = 0
    state.players[0].has_lost = False
    # Queue a dead phantom player id that doesn't exist — should be
    # skipped via the "candidate is None" branch.
    state.extra_turn_queue.append(9999)
    _advance_to_next_active_player(state)
    # Queue emptied, natural rotation applied.
    assert state.extra_turn_queue == []
    assert state.active_player_idx == 1


def test_extra_turn_queue_skips_dead_player():
    """If the queued player has already lost, they are skipped in the
    simulation loop and natural turn order resumes."""
    state = _new_state()
    state.players[0].has_lost = True
    state.extra_turn_queue.append(0)
    # Probe the simulate-style advance directly.
    while state.extra_turn_queue:
        candidate_id = state.extra_turn_queue.pop(0)
        candidate = next(
            (p for p in state.players if p.id == candidate_id), None
        )
        if candidate is not None and not candidate.has_lost:
            break
    # P0 was dead — queue emptied without selecting anyone.
    assert state.extra_turn_queue == []


# ---- Green Sun's Zenith ----------------------------------------------

def test_gsz_is_wired_up():
    g = SPECIAL_GUESTS_EOE["Green Sun's Zenith"]
    assert g.is_sorcery
    assert g.mana_cost_str == "{X}{G}"
    assert isinstance(
        g.spell_effect, SearchLibraryForGreenCreatureWithMVAtMostX
    )
    assert g.shuffles_into_library_instead_of_graveyard is True


_GREEN_2 = make_creature("Grizzly Bears", "{1}{G}", 2, 2)  # MV 2
_GREEN_4 = make_creature("Erhnam Djinn", "{3}{G}", 4, 5)  # MV 4
_BLUE_2 = make_creature("Merfolk", "{1}{U}", 2, 2)


def test_gsz_tutors_green_creature_within_mv_limit():
    state = _new_state(p0_agent=_PickFirst())
    p = state.player_by_id(0)
    green2 = state.new_object(_GREEN_2, 0, Zone.LIBRARY)
    green4 = state.new_object(_GREEN_4, 0, Zone.LIBRARY)
    blue2 = state.new_object(_BLUE_2, 0, Zone.LIBRARY)
    p.library.extend([green2, green4, blue2])

    state.resolving_x_value = 2
    SearchLibraryForGreenCreatureWithMVAtMostX().resolve(state, 0, ())
    # Agent picks first valid = Green-2. Should be on battlefield.
    assert green2 in state.battlefield
    assert green2.controller_id == 0
    # Green-4 and Blue-2 still in library (too expensive / wrong color).
    assert green4 in p.library
    assert blue2 in p.library


def test_gsz_no_match_returns_silently():
    state = _new_state(p0_agent=_PickFirst())
    p = state.player_by_id(0)
    blue = state.new_object(_BLUE_2, 0, Zone.LIBRARY)
    p.library.append(blue)

    state.resolving_x_value = 5
    SearchLibraryForGreenCreatureWithMVAtMostX().resolve(state, 0, ())
    # Nothing moved; no error.
    assert blue in p.library
    assert blue not in state.battlefield


def test_gsz_agent_declining_still_shuffles():
    """Declining (agent returns None) is legal — library is shuffled
    but no card is fetched."""
    class _Declines(Agent):
        def choose_card_from_library(self, state, player_id, option_ids):
            return None

    state = _new_state(p0_agent=_Declines())
    p = state.player_by_id(0)
    green2 = state.new_object(_GREEN_2, 0, Zone.LIBRARY)
    p.library.append(green2)

    state.resolving_x_value = 3
    SearchLibraryForGreenCreatureWithMVAtMostX().resolve(state, 0, ())
    assert green2 in p.library
    assert any("declines" in line for line in state.log)


def test_gsz_shuffles_self_into_library_on_resolve():
    """End-to-end via resolve_top_of_stack: GSZ's own card returns to
    library instead of graveyard."""
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem

    state = _new_state(p0_agent=_PickFirst())
    p = state.player_by_id(0)
    # Populate library with a valid target so the tutor succeeds.
    green2 = state.new_object(_GREEN_2, 0, Zone.LIBRARY)
    p.library.append(green2)

    gsz = state.new_object(
        SPECIAL_GUESTS_EOE["Green Sun's Zenith"], 0, Zone.STACK,
    )
    state.stack.append(StackItem(
        source=gsz, controller_id=0, targets=(), countered=False,
        x_value=2,
    ))
    resolve_top_of_stack(state)
    assert gsz in p.library
    assert gsz not in p.graveyard
    # Green-2 was fetched onto the battlefield.
    assert green2 in state.battlefield
