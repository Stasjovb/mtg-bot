"""Tests for ``MtgHeuristicEvaluator``."""

from __future__ import annotations

import pytest

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.game import Zone
from mtg_bot.search import MtgGameStateAdapter
from mtg_bot.search.heuristic_evaluator import MtgHeuristicEvaluator
from mtg_bot.simulate import setup_game


def _adapter(seed: int = 42) -> MtgGameStateAdapter:
    state = setup_game(
        [RandomAgent(), RandomAgent()], ["G", "R"], seed=seed,
    )
    return MtgGameStateAdapter(state)


def _put_creature(state, name: str, controller_id: int):
    obj = state.new_object(
        SYNTHETIC_CREATURES[name], owner_id=controller_id,
        zone=Zone.BATTLEFIELD,
    )
    obj.summoning_sick = False
    state.battlefield.append(obj)
    return obj


# =====================================================================
# Construction / weights
# =====================================================================

def test_default_weights_normalize():
    evaluator = MtgHeuristicEvaluator()
    total = (
        evaluator.life_weight
        + evaluator.board_weight
        + evaluator.card_weight
    )
    assert abs(total - 1.0) < 1e-9


def test_custom_weights_renormalized():
    evaluator = MtgHeuristicEvaluator(
        life_weight=2.0, board_weight=2.0, card_weight=1.0,
    )
    total = (
        evaluator.life_weight
        + evaluator.board_weight
        + evaluator.card_weight
    )
    assert abs(total - 1.0) < 1e-9
    assert evaluator.life_weight == evaluator.board_weight
    assert evaluator.card_weight < evaluator.life_weight


def test_zero_weights_rejected():
    with pytest.raises(ValueError):
        MtgHeuristicEvaluator(
            life_weight=0, board_weight=0, card_weight=0,
        )


# =====================================================================
# Score range
# =====================================================================

def test_evaluator_returns_value_in_unit_interval():
    """Whatever the position, score must be in [-1, 1]."""
    adapter = _adapter()
    evaluator = MtgHeuristicEvaluator()
    for player_id in (0, 1):
        v = evaluator.evaluate(adapter, player_id)
        assert -1.0 <= v <= 1.0


def test_terminal_short_circuits_to_winner_signal():
    """The base ``Evaluator`` short-circuits terminal states. Verify
    via the public evaluate() method."""
    adapter = _adapter()
    adapter.engine_state.winner_id = 0
    evaluator = MtgHeuristicEvaluator()
    assert evaluator.evaluate(adapter, player_id=0) == 1.0
    assert evaluator.evaluate(adapter, player_id=1) == -1.0


# =====================================================================
# Component sensitivity
# =====================================================================

def test_higher_life_yields_higher_score():
    adapter = _adapter()
    engine = adapter.engine_state
    # P0 is way ahead on life.
    engine.players[0].life = 30
    engine.players[1].life = 5
    evaluator = MtgHeuristicEvaluator()
    assert evaluator.evaluate(adapter, player_id=0) > 0
    assert evaluator.evaluate(adapter, player_id=1) < 0


def test_lower_life_yields_lower_score():
    adapter = _adapter()
    engine = adapter.engine_state
    engine.players[0].life = 5
    engine.players[1].life = 20
    evaluator = MtgHeuristicEvaluator()
    assert evaluator.evaluate(adapter, player_id=0) < 0
    # Symmetry: opponent's score is the negation (zero-sum).
    assert evaluator.evaluate(adapter, player_id=1) > 0


def test_bigger_board_yields_higher_score():
    """All else equal, controlling more creatures wins more."""
    adapter = _adapter()
    engine = adapter.engine_state
    # Equalize life and hand size; only board differs.
    engine.players[0].life = engine.players[1].life
    while len(engine.players[0].hand) > len(engine.players[1].hand):
        engine.players[0].hand.pop()
    while len(engine.players[1].hand) > len(engine.players[0].hand):
        engine.players[1].hand.pop()
    # Five 3/3s for P0; nothing for P1.
    for _ in range(5):
        _put_creature(engine, "Forest Giant", 0)
    evaluator = MtgHeuristicEvaluator()
    assert evaluator.evaluate(adapter, player_id=0) > 0
    assert evaluator.evaluate(adapter, player_id=1) < 0


def test_more_cards_in_hand_yields_higher_score():
    adapter = _adapter()
    engine = adapter.engine_state
    # Equalize life and board; only hand differs.
    engine.players[0].life = engine.players[1].life
    # P0 keeps full hand, P1 has 0 cards.
    engine.players[1].hand.clear()
    evaluator = MtgHeuristicEvaluator()
    assert evaluator.evaluate(adapter, player_id=0) > 0


# =====================================================================
# Symmetry (zero-sum)
# =====================================================================

def test_score_is_approximately_zero_sum():
    """In a 2-player position, P0's score should equal -P1's score
    (perfectly when no clamping happens; bounded by |1| otherwise)."""
    adapter = _adapter()
    engine = adapter.engine_state
    engine.players[0].life = 18
    engine.players[1].life = 14
    evaluator = MtgHeuristicEvaluator()
    s0 = evaluator.evaluate(adapter, player_id=0)
    s1 = evaluator.evaluate(adapter, player_id=1)
    assert abs(s0 + s1) < 1e-9


def test_balanced_position_scores_near_zero():
    """An equal-life, no-board, equal-hand position should score
    very close to 0 from either player's perspective."""
    adapter = _adapter()
    engine = adapter.engine_state
    engine.players[0].life = 20
    engine.players[1].life = 20
    # Match hand sizes.
    while len(engine.players[0].hand) > len(engine.players[1].hand):
        engine.players[0].hand.pop()
    while len(engine.players[1].hand) > len(engine.players[0].hand):
        engine.players[1].hand.pop()
    evaluator = MtgHeuristicEvaluator()
    score = evaluator.evaluate(adapter, player_id=0)
    assert abs(score) < 1e-9


# =====================================================================
# Adapter passthrough
# =====================================================================

def test_evaluator_works_with_raw_engine_state():
    """Falls through to the engine state when given one directly
    (no adapter), for testing convenience."""
    adapter = _adapter()
    engine = adapter.engine_state
    engine.players[0].life = 20
    engine.players[1].life = 10
    evaluator = MtgHeuristicEvaluator()
    # Pass the engine state directly.
    score = evaluator._evaluate_nonterminal(engine, player_id=0)
    assert score > 0


# =====================================================================
# Stack-aware scoring
# =====================================================================


def _put_creature_spell_on_stack(state, name: str, controller_id: int):
    """Put a creature spell on the stack as if cast from hand. Mirrors
    what _cast_spell does at the engine level: object's zone becomes
    STACK and a StackItem is appended."""
    from mtg_bot.game import StackItem
    obj = state.new_object(
        SYNTHETIC_CREATURES[name], owner_id=controller_id,
        zone=Zone.STACK,
    )
    item = StackItem(source=obj, controller_id=controller_id, ability=None)
    state.stack.append(item)
    return item


def test_creature_spell_on_stack_adds_to_board_score():
    """Casting a creature should not penalize the eval — the spell on
    the stack should contribute its printed P+T as future board."""
    adapter = _adapter()
    engine = adapter.engine_state
    evaluator = MtgHeuristicEvaluator()
    base = evaluator._evaluate_nonterminal(engine, player_id=0)
    # Add a creature spell to P0's stack. Battlefield Recruit is a
    # 2/2 vanilla creature in SYNTHETIC_CREATURES.
    _put_creature_spell_on_stack(engine, "Battlefield Recruit", 0)
    after = evaluator._evaluate_nonterminal(engine, player_id=0)
    assert after > base, (
        "creature spell on stack should raise the active player's "
        f"board score (was {base}, now {after})"
    )


def test_countered_creature_spell_does_not_score():
    """A countered creature spell will resolve as no-op; eval should
    not credit it."""
    adapter = _adapter()
    engine = adapter.engine_state
    evaluator = MtgHeuristicEvaluator()
    base = evaluator._evaluate_nonterminal(engine, player_id=0)
    item = _put_creature_spell_on_stack(engine, "Battlefield Recruit", 0)
    item.countered = True
    after = evaluator._evaluate_nonterminal(engine, player_id=0)
    assert after == base, (
        "countered creature spell shouldn't change the score "
        f"(base={base}, after={after})"
    )


def test_opponent_creature_spell_on_stack_lowers_score():
    """Symmetric: opponent's creature spell on stack should decrease
    the asked-for player's relative score."""
    adapter = _adapter()
    engine = adapter.engine_state
    evaluator = MtgHeuristicEvaluator()
    base = evaluator._evaluate_nonterminal(engine, player_id=0)
    _put_creature_spell_on_stack(engine, "Battlefield Recruit", 1)
    after = evaluator._evaluate_nonterminal(engine, player_id=0)
    assert after < base, (
        "opponent creature spell on stack should lower the asked-for "
        f"player's score (was {base}, now {after})"
    )


def test_non_creature_spell_on_stack_counts_as_card():
    """A non-creature spell on the stack should be counted in card
    advantage (since the value hasn't been spent yet) instead of
    contributing to board. So casting it produces no net penalty:
    hand goes down by 1, stack count goes up by 1."""
    from mtg_bot.cards import EOE_SPELLS
    from mtg_bot.game import StackItem
    adapter = _adapter()
    engine = adapter.engine_state
    evaluator = MtgHeuristicEvaluator()

    # Find any non-creature spell in the EoE spell registry.
    non_creature_name = next(
        name for name, p in EOE_SPELLS.items()
        if not p.is_creature and not p.is_land
    )
    # Pre-state: the spell is in P0's hand.
    spell_obj = engine.new_object(
        EOE_SPELLS[non_creature_name], owner_id=0, zone=Zone.HAND,
    )
    engine.players[0].hand.append(spell_obj)
    pre_score = evaluator._evaluate_nonterminal(engine, player_id=0)
    pre_card_count = evaluator._card_count(engine, 0)

    # Simulate casting it: move from hand to stack.
    engine.players[0].hand.remove(spell_obj)
    spell_obj.zone = Zone.STACK
    engine.stack.append(
        StackItem(source=spell_obj, controller_id=0, ability=None)
    )

    post_score = evaluator._evaluate_nonterminal(engine, player_id=0)
    post_card_count = evaluator._card_count(engine, 0)
    # Card count unchanged: hand -1, stack +1.
    assert post_card_count == pre_card_count
    # Score essentially unchanged (small drift OK from clamping math).
    assert abs(post_score - pre_score) < 1e-9


def test_creature_spell_replaces_card_advantage_with_board(  # noqa: E501
):
    """Casting a creature: hand goes -1, board goes +P+T. Net should
    be positive because typical creatures have P+T > 1 normalized."""
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.game import StackItem
    adapter = _adapter()
    engine = adapter.engine_state
    evaluator = MtgHeuristicEvaluator()

    # Put a creature in hand.
    creature = engine.new_object(
        SYNTHETIC_CREATURES["Battlefield Recruit"],
        owner_id=0, zone=Zone.HAND,
    )
    engine.players[0].hand.append(creature)
    pre = evaluator._evaluate_nonterminal(engine, player_id=0)

    # Simulate casting: hand → stack.
    engine.players[0].hand.remove(creature)
    creature.zone = Zone.STACK
    engine.stack.append(
        StackItem(source=creature, controller_id=0, ability=None)
    )
    post = evaluator._evaluate_nonterminal(engine, player_id=0)
    assert post > pre, (
        "casting a creature should raise score "
        f"(was {pre}, now {post}) — the +P+T board contribution "
        f"must outweigh the -1 hand size"
    )


def test_playing_a_land_does_not_decrease_card_count():
    """Playing a land moves it from hand to battlefield. Without
    counting permanents toward card_count, this would look like
    "lost a card" and the eval would penalize ramping. With
    permanents counted, hand-to-battlefield is a no-op for the card
    term."""
    from mtg_bot.cards import BASIC_LANDS
    adapter = _adapter()
    engine = adapter.engine_state
    evaluator = MtgHeuristicEvaluator()

    forest = engine.new_object(
        BASIC_LANDS["Forest"], owner_id=0, zone=Zone.HAND,
    )
    engine.players[0].hand.append(forest)
    pre_count = evaluator._card_count(engine, 0)

    # Simulate playing the land: hand → battlefield.
    engine.players[0].hand.remove(forest)
    forest.zone = Zone.BATTLEFIELD
    forest.controller_id = 0
    engine.battlefield.append(forest)

    post_count = evaluator._card_count(engine, 0)
    assert post_count == pre_count


def test_phased_out_permanents_excluded_from_card_count():
    """Phased-out permanents don't exist for game purposes; they
    shouldn't count toward "deployed value" either."""
    from mtg_bot.cards import BASIC_LANDS
    adapter = _adapter()
    engine = adapter.engine_state
    evaluator = MtgHeuristicEvaluator()

    plains = engine.new_object(
        BASIC_LANDS["Plains"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    plains.controller_id = 0
    engine.battlefield.append(plains)
    pre_count = evaluator._card_count(engine, 0)

    plains.phased_out = True
    post_count = evaluator._card_count(engine, 0)
    assert post_count == pre_count - 1


def test_triggered_ability_on_stack_does_not_score():
    """Triggered abilities (StackItem.ability != None) aren't "the
    player's value being deployed" in the same way — they're already-
    fired triggers waiting to resolve. Skipped by both the board and
    card terms."""
    from mtg_bot.game import StackItem
    adapter = _adapter()
    engine = adapter.engine_state
    evaluator = MtgHeuristicEvaluator()

    # Synthesize a triggered-ability stack item: a sentinel non-None
    # value for ability is enough to gate it out of both terms.
    obj = engine.new_object(
        SYNTHETIC_CREATURES["Battlefield Recruit"],
        owner_id=0, zone=Zone.STACK,
    )
    engine.stack.append(
        StackItem(source=obj, controller_id=0, ability=object()),
    )
    base = evaluator._evaluate_nonterminal(engine, player_id=0)

    # Add an actual creature spell — that should change the score.
    _put_creature_spell_on_stack(engine, "Battlefield Recruit", 0)
    after = evaluator._evaluate_nonterminal(engine, player_id=0)
    assert after > base
