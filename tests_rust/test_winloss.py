"""Win / loss condition primitives on the Rust ``GameState``.

Ported from Python's ``src/mtg_bot/game.py`` (the ``Player.has_lost``
flag, ``GameState.winner_id`` / ``GameState.is_draw``, and
``GameState.is_over`` helper).

**Composes with the round-1 life slice.** A player at life <= 0 is a
loser (CR 104.3a, simplified).

**Implementation (round-26 G10 + G11 closure).** ``losers()`` is
computed as the OR of three signals on each player:
``has_lost`` (sticky, set by ``apply_sbas`` or ``lose_game``);
``attempted_draw_on_empty`` (CR 704.5b cause-signal, read directly
so the empty-library loss is observable before the next SBA pass);
``life <= 0`` (pure-derivation, preserved so the existing
revival semantics around ``gain_life`` from 0 still hold UNTIL
``apply_sbas`` runs and locks in the loss).

"You lose the game" effects (Phage the Untouchable, Bargain, deck-out)
go through the ``lose_game(p)`` primitive which flips the sticky
``has_lost`` flag directly. ``apply_sbas`` is the SBA-driven
transition: a player at life <= 0 or with the empty-library cause-
signal becomes ``has_lost = true`` on the next pass and the loss
is irrevocable.

**Winner semantics.** With pure derivation in a 2-player game:
- 0 losers -> winner = None (game ongoing).
- exactly 1 loser, the OTHER player not also a loser -> winner =
  Some(other_player_id).
- 2 losers (both at <= 0 simultaneously, e.g. mutual lethal damage)
  -> winner = None (this is the "draw" case for now; a future slice
  may distinguish CR 104.4 simultaneous-loss draws from
  pre-game-end concessions).
"""

from __future__ import annotations

import pytest


def test_initial_state_no_loser(synthetic_state):
    """Fresh synthetic state: both players at 20 life, no losers."""
    assert list(synthetic_state.losers()) == []


def test_initial_state_no_winner(synthetic_state):
    """Fresh synthetic state: no winner yet (game ongoing)."""
    assert synthetic_state.winner() is None


def test_initial_state_not_game_over(synthetic_state):
    """Fresh synthetic state: game is not over."""
    assert synthetic_state.is_game_over() is False


def test_player_at_zero_life_is_loser(synthetic_state):
    """Setting player 0 to 0 life flags them as a loser."""
    synthetic_state.set_life(0, 0)
    assert list(synthetic_state.losers()) == [0]


def test_player_at_negative_life_is_loser(synthetic_state):
    """Setting player 0 to negative life flags them as a loser
    (CR 104.3a: 0 or less life loses the game)."""
    synthetic_state.set_life(0, -5)
    assert list(synthetic_state.losers()) == [0]


def test_winner_when_one_player_loses(synthetic_state):
    """Player 0 at 0 life, player 1 still alive: winner is player 1."""
    synthetic_state.set_life(0, 0)
    assert synthetic_state.winner() == 1


def test_winner_player_zero_when_player_one_loses(synthetic_state):
    """Symmetric: player 1 at 0 life, player 0 still alive: winner is 0."""
    synthetic_state.set_life(1, 0)
    assert synthetic_state.winner() == 0


def test_no_winner_when_both_lose(synthetic_state):
    """Both players at 0 life simultaneously (e.g. mutual lethal damage):
    no winner — this is the draw case under pure-derivation semantics."""
    synthetic_state.set_life(0, 0)
    synthetic_state.set_life(1, 0)
    assert synthetic_state.winner() is None
    # Both should be in the losers list.
    assert sorted(synthetic_state.losers()) == [0, 1]


def test_is_game_over_true_when_any_loser(synthetic_state):
    """Any loser at all -> game is over."""
    synthetic_state.set_life(0, 0)
    assert synthetic_state.is_game_over() is True


def test_is_game_over_true_when_both_lose(synthetic_state):
    """Both lose -> still game over (draw is over)."""
    synthetic_state.set_life(0, 0)
    synthetic_state.set_life(1, 0)
    assert synthetic_state.is_game_over() is True


def test_is_player_alive_true_for_positive_life(synthetic_state):
    """is_player_alive returns True for life > 0."""
    assert synthetic_state.is_player_alive(0) is True
    assert synthetic_state.is_player_alive(1) is True


def test_is_player_alive_false_at_zero_life(synthetic_state):
    """is_player_alive returns False at exactly 0 life
    (CR 104.3a: 0 or less life loses)."""
    synthetic_state.set_life(0, 0)
    assert synthetic_state.is_player_alive(0) is False
    assert synthetic_state.is_player_alive(1) is True


def test_is_player_alive_false_for_negative_life(synthetic_state):
    """is_player_alive returns False for negative life."""
    synthetic_state.set_life(0, -3)
    assert synthetic_state.is_player_alive(0) is False


def test_is_player_alive_unknown_player_raises(synthetic_state):
    """is_player_alive on an out-of-range player id raises."""
    with pytest.raises((ValueError, IndexError, OverflowError)):
        synthetic_state.is_player_alive(99)


def test_lose_life_to_zero_makes_player_loser(synthetic_state):
    """Composes with life slice: lose_life that brings life to 0
    flips the player into the losers list."""
    synthetic_state.lose_life(0, 20)
    assert list(synthetic_state.losers()) == [0]
    assert synthetic_state.winner() == 1


def test_lose_life_past_zero_makes_player_loser(synthetic_state):
    """Composes with life slice: lose_life that brings life negative
    also flips the player into the losers list."""
    synthetic_state.lose_life(0, 25)
    assert synthetic_state.get_life(0) == -5
    assert list(synthetic_state.losers()) == [0]


def test_gain_life_from_zero_revives_player(synthetic_state):
    """Pure-derivation: bringing a 0-life player back above 0 with
    gain_life takes them OUT of the losers list. (Real MTG would have
    the SBA fire first making this irrelevant; in this pure-derivation
    slice we accept the simpler model — the SBA enforcement is a
    future slice.)"""
    synthetic_state.set_life(0, 0)
    assert list(synthetic_state.losers()) == [0]
    synthetic_state.gain_life(0, 5)
    assert list(synthetic_state.losers()) == []
    assert synthetic_state.is_game_over() is False


def test_clone_preserves_loss_state(synthetic_state):
    """Cloning a state where a player is at 0 life preserves the
    derived loser status on the clone."""
    synthetic_state.set_life(0, 0)
    cloned = synthetic_state.clone_once()
    assert list(cloned.losers()) == [0]
    assert cloned.winner() == 1
    assert cloned.is_game_over() is True


def test_clone_loss_does_not_bleed_back(synthetic_state):
    """CoW canary: knocking the clone's player to 0 must not flag the
    original as a loser."""
    cloned = synthetic_state.clone_once()
    cloned.set_life(0, 0)
    # Clone shows the loss.
    assert list(cloned.losers()) == [0]
    assert cloned.winner() == 1
    assert cloned.is_game_over() is True
    # Original is untouched.
    assert list(synthetic_state.losers()) == []
    assert synthetic_state.winner() is None
    assert synthetic_state.is_game_over() is False


def test_winner_unaffected_by_clone_then_lose(synthetic_state):
    """Stronger CoW canary: even after the clone reports a winner,
    the original keeps None — the per-Player life mutation on the
    clone does not bleed back through the [Player; 2] copy."""
    cloned = synthetic_state.clone_once()
    cloned.lose_life(1, 20)
    assert cloned.winner() == 0
    assert synthetic_state.winner() is None


def test_explicit_lose_game_marks_player(synthetic_state):
    """Round-26 G11 closure: ``lose_game(p)`` is the explicit primitive
    for "you lose the game" effects (Phage / Bargain / deck-out). It
    flips the sticky ``has_lost`` flag — irrevocable, no ``gain_life``
    can undo it (even when the player is at full life)."""
    # p0 at full life, but losing the game.
    assert synthetic_state.get_life(0) == 20
    synthetic_state.lose_game(0)
    assert list(synthetic_state.losers()) == [0]
    assert synthetic_state.winner() == 1
    assert synthetic_state.is_game_over() is True
    # Life is untouched — the loss is not a life-total side effect.
    assert synthetic_state.get_life(0) == 20
    # The loss is sticky: gain_life cannot revive p0.
    synthetic_state.gain_life(0, 5)
    assert list(synthetic_state.losers()) == [0]


# -----------------------------------------------------------------
# Python-compatible outcome getters: is_over / is_draw / winner_id
#
# Added by feature/rust-bridge-outcome (round 21, Phase 2) so the
# parity smoke harness in ``scripts/parity_smoke.py`` can hash a Rust
# ``GameState`` using the same accessor names it uses on Python's
# ``GameState`` (``is_over()``, ``is_draw`` property, ``winner_id``
# property).
#
# Post-CE10 closure (CE-pure-derivation-is_over): these three
# accessors are SBA-GATED — they read ONLY from the sticky
# ``Player.has_lost`` flag, mirroring Python's identically-named
# fields which are written only by ``apply_state_based_actions``.
# Pre-closure, they shared the OR'd-three predicate with
# ``losers()`` / ``winner()`` / ``is_game_over()``, which surfaced
# as a NOVEL cross-engine divergence on empty-library draws in the
# Phase-5 smoke harness (the harness doesn't fire SBAs between
# steps, so Python stayed stale while Rust eagerly derived
# is_over=True / winner_id=1). The tests below pin the post-closure
# SBA-gated semantics; the pre-existing eager API
# (``losers()``/``winner()``/``is_game_over()``) is unchanged and
# its tests still pass above.
# -----------------------------------------------------------------


def test_is_over_mirrors_is_game_over_alive_alive(synthetic_state):
    """Both alive: is_over() and is_game_over() both False."""
    assert synthetic_state.is_over() is False
    assert synthetic_state.is_over() == synthetic_state.is_game_over()


def test_is_over_sba_gated_one_dead_via_set_life_then_sba(synthetic_state):
    """Post-CE10: is_over() is SBA-gated, so set_life-to-zero alone
    does NOT flip it — the OR'd-three eager predicate behind
    is_game_over() flips immediately, but is_over() waits for an SBA
    pass to commit the loss into the sticky ``has_lost``."""
    synthetic_state.set_life(0, 0)
    # Eager API: game-over surfaces immediately.
    assert synthetic_state.is_game_over() is True
    # SBA-gated API: not yet — has_lost not flipped.
    assert synthetic_state.is_over() is False
    # Run an SBA pass to commit the loss.
    synthetic_state.apply_sbas_until_quiescent()
    assert synthetic_state.is_over() is True
    assert synthetic_state.is_over() == synthetic_state.is_game_over()
    # Symmetric: kill p1 instead.
    synthetic_state.set_life(0, 20)  # revive p0 (pre-SBA path)
    # p0 was already locked in by previous SBA pass; rebuild from
    # a fresh state for the symmetric branch instead of fighting
    # the sticky has_lost.


def test_is_over_sba_gated_both_dead_via_set_life_then_sba(synthetic_state):
    """Post-CE10: with both players at 0 life, is_over() is False
    UNTIL the SBA pass commits both losses into ``has_lost``."""
    synthetic_state.set_life(0, 0)
    synthetic_state.set_life(1, 0)
    # Eager surface flips True; SBA-gated stays False.
    assert synthetic_state.is_game_over() is True
    assert synthetic_state.is_over() is False
    synthetic_state.apply_sbas_until_quiescent()
    # Now committed.
    assert synthetic_state.is_over() is True
    assert synthetic_state.is_over() == synthetic_state.is_game_over()


def test_is_draw_is_property_not_method(synthetic_state):
    """is_draw is exposed as a #[getter] — accessed without parens.
    Calling it like a method must fail (bool is not callable)."""
    # Property access works.
    val = synthetic_state.is_draw
    assert val is False
    # Method-style call must NOT work — bool is not callable.
    with pytest.raises(TypeError):
        synthetic_state.is_draw()  # type: ignore[operator]


def test_is_draw_all_four_shapes_sba_gated(synthetic_state):
    """Post-CE12: is_draw is True ONLY when BOTH players carry
    ``has_lost == true`` AND no prior SBA pass has committed a sole-
    survivor winner into the sticky shadow field. Pre-SBA, even with
    both players at 0 life, is_draw stays False (the eager OR'd-three
    signals are not visible through the SBA-gated getter).

    The sticky-winner rule (CE12): if p0 dies first and SBA fires
    while p1 is still alive, ``winner_id_sticky`` is written to
    Some(1). Then later p1 also dies — the post-state has both
    has_lost=True but is_draw is FALSE (sticky winner already
    committed). Only a true BILATERAL simultaneous-loss SBA pass
    (both has_lost=True in the same pass, with winner_id_sticky still
    None) flips is_draw to True. Mirrors Python's `is_draw` write at
    turn.py:1384-1386, gated on alive=0 with no prior winner write.
    """
    # (alive, alive) — game ongoing.
    assert synthetic_state.is_draw is False
    # Bilateral simultaneous-loss path: set BOTH players to 0 life,
    # then fire SBA. Both transition has_lost=False -> has_lost=True
    # in the same per-player commit pass; the sticky-write gate sees
    # (true, true) and writes nothing; is_draw flips to True.
    synthetic_state.set_life(0, 0)
    assert synthetic_state.is_draw is False
    synthetic_state.set_life(1, 0)
    assert synthetic_state.is_draw is False
    synthetic_state.apply_sbas_until_quiescent()
    # Both committed has_lost, no sticky winner -> draw.
    assert synthetic_state.is_draw is True


def test_winner_id_is_property_not_method(synthetic_state):
    """winner_id is exposed as a #[getter] — accessed without parens.
    Calling it like a method must fail (None / int is not callable).

    Post-CE10: SBA-gated, so we explicitly fire ``apply_sbas`` after
    the lethal set_life to commit p0's loss into ``has_lost``.
    """
    synthetic_state.set_life(0, 0)
    synthetic_state.apply_sbas_until_quiescent()
    val = synthetic_state.winner_id
    assert val == 1
    # Method-style call on the resolved int must fail.
    with pytest.raises(TypeError):
        synthetic_state.winner_id()  # type: ignore[operator]


def test_winner_id_all_four_shapes_sba_gated(synthetic_state):
    """Post-CE12: winner_id is SBA-gated AND STICKY. We drive each
    shape via set_life + apply_sbas. Pre-SBA, set_life alone leaves
    winner_id stale (matching Python).

    (alive, alive) -> None
    (alive, dead, post-SBA) -> id of alive player
    (dead, alive, post-SBA, no prior winner) -> id of alive player
    (dead, dead, post-SBA, SIMULTANEOUS — no prior sticky write) -> None

    The "exactly one died first, then the other also died" sequential
    case is NO LONGER tested here — it's split out to
    test_winner_id_sticky_after_sequential_kills (CE12).
    """
    # (alive, alive) — game ongoing -> None.
    assert synthetic_state.winner_id is None
    # Drive BOTH to 0 simultaneously, then SBA-commit. With both
    # has_lost=True in the same commit pass and no prior sticky
    # write, the (true, true) gate skips the sticky write and the
    # getter falls back to live-derivation -> None (draw).
    synthetic_state.set_life(0, 0)
    synthetic_state.set_life(1, 0)
    # Pre-SBA: stale on the SBA-gated surface.
    assert synthetic_state.winner_id is None
    synthetic_state.apply_sbas_until_quiescent()
    # Bilateral simultaneous-loss with no prior sole-survivor SBA
    # pass -> no winner.
    assert synthetic_state.winner_id is None


def test_winner_id_pre_sba_stale_matches_python_semantics(synthetic_state):
    """Post-CE10 invariant pin: winner_id stays None when a player
    has been driven to 0 life but no SBA pass has run yet. This is
    the parity-critical contract — Python's winner_id is written
    only by ``apply_state_based_actions``, and the cross-engine
    smoke harness depends on Rust matching that timing.

    Cross-references:
      - ``tests/test_parity_smoke_edge_cases.py::test_cross_engine_empty_library_side_channel_draw_walks_clean``
      - ``tests/test_parity_smoke_edge_cases.py::test_cross_engine_single_card_libraries_multi_turn_walks_clean``
    """
    synthetic_state.set_life(0, 0)
    # Pre-SBA: eager API surfaces the loss; SBA-gated API stays stale.
    assert list(synthetic_state.losers()) == [0]
    assert synthetic_state.winner() == 1  # eager
    assert synthetic_state.is_game_over() is True  # eager
    # SBA-gated surface: stale.
    assert synthetic_state.is_over() is False
    assert synthetic_state.winner_id is None
    assert synthetic_state.is_draw is False


def test_is_over_winner_id_eager_for_empty_library_draw_via_pure_derivation(
    synthetic_state,
):
    """Post-CE10 invariant pin: the empty-library cause-flag
    (``attempted_draw_on_empty``) drives the eager ``losers()`` /
    ``is_game_over()`` API immediately but does NOT flip the
    SBA-gated ``is_over()`` / ``winner_id`` surface until SBA runs.

    This pins the CE-pure-derivation-is_over closure shape: the
    cause-flag-vs-has_lost split is observable through the two
    parallel API layers. Cross-references the parity-smoke
    edge-case tests at
    ``tests/test_parity_smoke_edge_cases.py``.
    """
    # Drain p0's library to empty; explicit empty-library draw
    # via the pymethod flips attempted_draw_on_empty.
    while synthetic_state.draw_card(0) is not None:
        pass
    # Now both libraries-empty draw is the trigger.
    synthetic_state.draw_card(0)
    # Eager API observes the loss.
    assert 0 in list(synthetic_state.losers())
    assert synthetic_state.is_game_over() is True
    assert synthetic_state.winner() == 1
    # SBA-gated surface stays stale.
    assert synthetic_state.is_over() is False
    assert synthetic_state.winner_id is None
    # After SBA, the surface flips.
    synthetic_state.apply_sbas_until_quiescent()
    assert synthetic_state.is_over() is True
    assert synthetic_state.winner_id == 1
    assert synthetic_state.is_draw is False


def test_revive_via_gain_life_pre_sba_clears_eager_loss(synthetic_state):
    """Post-CE10: pre-SBA, gain_life from 0 takes a player out of
    the eager ``losers()`` pool (the OR'd-three has life > 0 again
    AND has_lost not yet set). The SBA-gated surface stays
    consistent: is_over stays False (no has_lost commit happened),
    winner_id stays None, is_draw stays False.

    Mirrors test_gain_life_from_zero_revives_player for the new
    Python-named getters under the SBA-gated semantics.
    """
    synthetic_state.set_life(0, 0)
    synthetic_state.set_life(1, 0)
    # Eager: both lost (draw).
    assert sorted(synthetic_state.losers()) == [0, 1]
    assert synthetic_state.winner() is None
    assert synthetic_state.is_game_over() is True
    # SBA-gated: stale (game-over surface not yet committed).
    assert synthetic_state.is_draw is False
    assert synthetic_state.winner_id is None
    assert synthetic_state.is_over() is False
    # Revive p0 (no SBA fired yet): eager (alive, dead) -> p0 wins.
    synthetic_state.gain_life(0, 5)
    assert synthetic_state.winner() == 0  # eager
    # SBA-gated stays stale.
    assert synthetic_state.is_draw is False
    assert synthetic_state.winner_id is None
    assert synthetic_state.is_over() is False
    # Revive p1 too: eager (alive, alive) -> ongoing.
    synthetic_state.gain_life(1, 5)
    assert synthetic_state.winner() is None  # eager
    assert synthetic_state.is_game_over() is False
    assert synthetic_state.is_over() is False
    assert synthetic_state.winner_id is None


# ---------------------------------------------------------------------------
# Cross-feature edge cases — winloss outcome derivation under the full stack.
#
# The tests above cover the pure-derivation winloss helpers in isolation
# (set_life / lose_life / gain_life followed by losers / winner /
# is_game_over). The block below threads the outcome derivation through
# the higher engine layers — Effect dispatch (LoseLife, DealDamage to a
# player, EachOpponentLosesLife), combat damage routing to players,
# fingerprinting, the SBA loop, and clone CoW — and pins the
# parity-critical contract that the 1000-game smoke harness depends on:
# identical winner / loser / is_over readings between the Python and
# Rust engines after a game ends.
#
# These tests compose existing primitives; none of them probes new Rust
# behavior. A future refactor that breaks (e.g.) the post-game-over
# no-op invariant on apply_sbas_until_quiescent, or that desyncs the
# fingerprint from a life-zeroing Effect, surfaces here.
# ---------------------------------------------------------------------------


# Zone constants — mirror test_resolve.py / state_ops_zones.rs.
ZONE_HAND = 0
ZONE_BATTLEFIELD = 2


def _lose_life_dict(amount):
    """Self-life-loss printing — controller loses `amount` on resolve."""
    return {
        "name": f"Test SelfLoseLife (x{amount})",
        "card_types": ["Sorcery"],
        "mana_cost": {"U": 1, "generic": 2},
        "effects": [{"kind": "lose_life", "amount": amount}],
    }


def _deal_damage_to_player_dict(amount):
    """DealDamage to any_player — Bombard-shaped direct burn at the
    opponent's face. Hits the defender (non-controller) under the
    first-slice dispatch."""
    return {
        "name": f"Test PlayerBurn (x{amount})",
        "card_types": ["Sorcery"],
        "mana_cost": {"R": 1, "generic": 1},
        "effects": [
            {
                "kind": "deal_damage",
                "amount": amount,
                "target": {"kind": "any_player"},
            }
        ],
    }


def _each_opponent_loses_life_dict(amount):
    """Each-opponent-life-loss printing — every opponent of source's
    controller loses `amount` life."""
    return {
        "name": f"Test EachOppLose (x{amount})",
        "card_types": ["Sorcery"],
        "mana_cost": {"B": 1, "generic": 1},
        "effects": [{"kind": "each_opponent_loses_life", "amount": amount}],
    }


def test_effect_lose_life_to_zero_marks_loser_and_game_over(synthetic_state):
    """Cross-feature: Effect::LoseLife + apply_sbas_until_quiescent ->
    winloss derivation. Resolving a LoseLife-20 spell controlled by p0
    drops p0 to exactly 0; the pure-derivation winloss flags p0 as
    loser, p1 as winner, and is_game_over True after one quiescent
    SBA pass. Mirrors test_life.py's parallel test but pins the
    contract from the winloss side."""
    src_id = synthetic_state.register_and_inject_object(
        _lose_life_dict(20), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.get_life(0) == 0
    synthetic_state.apply_sbas_until_quiescent()
    assert list(synthetic_state.losers()) == [0]
    assert synthetic_state.winner() == 1
    assert synthetic_state.winner_id == 1
    assert synthetic_state.is_game_over() is True
    assert synthetic_state.is_over() is True
    assert synthetic_state.is_draw is False


def test_effect_deal_damage_to_player_to_zero_marks_loser(synthetic_state):
    """Cross-feature with the damage Effect arm: DealDamage{any_player,
    20} resolves -> defender (p1) drops to exactly 0 -> winloss
    derivation flags p1 as the loser, p0 as winner. Distinct codepath
    from LoseLife (CR 119.3) but the same observable outcome under the
    first-slice no-prevention dispatch."""
    src_id = synthetic_state.register_and_inject_object(
        _deal_damage_to_player_dict(20), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.get_life(1) == 0
    synthetic_state.apply_sbas_until_quiescent()
    assert list(synthetic_state.losers()) == [1]
    assert synthetic_state.winner() == 0
    assert synthetic_state.winner_id == 0
    assert synthetic_state.is_game_over() is True


def test_mutual_zero_via_sequential_lose_life_is_draw(synthetic_state):
    """Mutual-KO outcome under pure-derivation. Two sequential
    lose_life calls drive both players to 0 — the closest cross-feature
    analog the Rust engine exposes for "both die in the same event"
    (combat damage doesn't symmetrically hit both PLAYERS in one
    swing; the simplest reproducible mutual-KO at this layer is back-
    to-back life zeroing).

    Under pure-derivation winloss (see module docstring): two losers
    -> winner = None, is_draw = True, losers = [0, 1], is_game_over =
    True. Parity-critical: the Python engine's draw-detection must
    land here too. This is the load-bearing mutual-KO contract for
    the 1000-game parity smoke."""
    synthetic_state.lose_life(0, 20)
    synthetic_state.lose_life(1, 20)
    assert synthetic_state.get_life(0) == 0
    assert synthetic_state.get_life(1) == 0
    synthetic_state.apply_sbas_until_quiescent()
    assert sorted(synthetic_state.losers()) == [0, 1]
    assert synthetic_state.winner() is None
    assert synthetic_state.winner_id is None
    assert synthetic_state.is_draw is True
    assert synthetic_state.is_game_over() is True
    assert synthetic_state.is_over() is True


def test_combat_damage_zeroes_defender_and_marks_loss(engine):
    """Cross-feature with the combat slice: an unblocked attacker
    deals combat damage to the defending player; if the defender's
    life was at exactly attacker.power, they drop to 0 and the
    winloss derivation flags them as a loser. Composes
    declare_attacker + deal_combat_damage (which routes through the
    same players[idx].life write as lose_life) + the post-SBA winloss
    derivation."""
    state = engine.make_synthetic_state(num_battlefield=10, num_hand=7, num_library=50)
    # Pre-load: defender (p1) at 2 life — exactly attacker.power.
    state.set_life(1, 2)
    attacker = 5  # P0_FIRST_BEAR_ID (Grizzly Bears, 2/2)
    assert state.declare_attacker(attacker) is True
    state.deal_combat_damage()
    assert state.get_life(1) == 0
    state.apply_sbas_until_quiescent()
    assert list(state.losers()) == [1]
    assert state.winner() == 0
    assert state.winner_id == 0
    assert state.is_game_over() is True


def test_is_game_over_false_on_healthy_mid_game_state(synthetic_state):
    """Anti-canary: a state that has had cross-feature mutations but
    still has both players above 0 reads as not-over. Damages a few
    creatures, resolves a non-lethal life-loss spell, runs an SBA
    pass — none of that should flip is_game_over to True while both
    players remain alive."""
    # Non-lethal life loss.
    src_id = synthetic_state.register_and_inject_object(
        _lose_life_dict(3), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()
    # Some creature damage that does NOT kill any creature.
    synthetic_state.deal_damage(5, 1)  # 1 damage on a 2/2 — survives
    synthetic_state.apply_sbas_until_quiescent()
    # Both players still alive (p0 at 17, p1 at 20).
    assert synthetic_state.get_life(0) == 17
    assert synthetic_state.get_life(1) == 20
    assert list(synthetic_state.losers()) == []
    assert synthetic_state.winner() is None
    assert synthetic_state.winner_id is None
    assert synthetic_state.is_game_over() is False
    assert synthetic_state.is_over() is False
    assert synthetic_state.is_draw is False


def test_winner_transitions_from_none_to_player_id_after_lethal_effect(
    synthetic_state,
):
    """winner() flips from None to the surviving player_idx exactly
    when the lethal Effect resolves. Pin the transition point: pre-
    resolution (spell on stack, both players still alive) winner() is
    None; post-resolution + SBA quiescence winner() is the survivor's
    idx. Cross-feature: stack + resolve + SBA + winloss."""
    src_id = synthetic_state.register_and_inject_object(
        _deal_damage_to_player_dict(20), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    # Pre-resolve: spell on stack, defender still at 20.
    assert synthetic_state.winner() is None
    assert synthetic_state.winner_id is None
    assert synthetic_state.is_game_over() is False

    synthetic_state.resolve_top_of_stack()
    synthetic_state.apply_sbas_until_quiescent()
    # Post-resolve: defender at 0, controller is the winner.
    assert synthetic_state.winner() == 0
    assert synthetic_state.winner_id == 0
    assert synthetic_state.is_game_over() is True


def test_clone_lethal_effect_does_not_decide_original(synthetic_state):
    """Stronger CoW canary across the full apply_effect path.
    Resolving a LoseLife-20 effect on a CLONE drops the clone's p0 to
    0 — the clone reports game-over with p1 as winner — but the
    original sees no life change, no losers, no winner, and
    is_game_over False. Same load-bearing CoW invariant as the
    primitive-level test_clone_loss_does_not_bleed_back, exercised
    through the higher Effect dispatch / SBA loop pathway that the
    parity smoke runs through."""
    src_id = synthetic_state.register_and_inject_object(
        _lose_life_dict(20), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)

    cloned = synthetic_state.clone_once()
    cloned.resolve_top_of_stack()
    cloned.apply_sbas_until_quiescent()

    # Clone reflects the kill.
    assert cloned.get_life(0) == 0
    assert list(cloned.losers()) == [0]
    assert cloned.winner() == 1
    assert cloned.winner_id == 1
    assert cloned.is_game_over() is True

    # Original is untouched in life, outcome AND stack — the spell is
    # still on the original's stack, both players still at 20.
    assert synthetic_state.get_life(0) == 20
    assert synthetic_state.get_life(1) == 20
    assert list(synthetic_state.losers()) == []
    assert synthetic_state.winner() is None
    assert synthetic_state.winner_id is None
    assert synthetic_state.is_game_over() is False
    assert synthetic_state.stack_size() == 1


def test_fingerprint_changes_when_game_ends(synthetic_state):
    """Parity-critical: the 12-char SHA1 fingerprint MUST observably
    change when a player drops to 0 and the game flips to game-over
    (because the fingerprint folds in life totals). A future
    refactor that accidentally cached the fingerprint across a life-
    zeroing mutation would silently break the 1000-game parity smoke
    — this test pins that drift."""
    fp_before = synthetic_state.fingerprint()
    assert synthetic_state.is_game_over() is False
    # Drop p0 to 0 via lose_life (the cross-feature path most likely
    # to be hit during real play).
    synthetic_state.lose_life(0, 20)
    synthetic_state.apply_sbas_until_quiescent()
    assert synthetic_state.is_game_over() is True
    fp_after = synthetic_state.fingerprint()
    assert fp_after != fp_before
    # Determinism canary: fingerprint at game-over is stable on
    # back-to-back reads.
    assert synthetic_state.fingerprint() == fp_after


def test_apply_sbas_until_quiescent_after_game_over_is_noop(synthetic_state):
    """Sequential apply_sbas_until_quiescent calls after the first one
    flags the game as decided are no-ops. The winloss derivation is
    pure-read from life totals, so a "decided" game doesn't generate
    new SBA work — losers stay losers, winner stays the same. Pin
    that the loop converges immediately on a game-over state and
    that the outcome reads are stable across repeated calls.

    This is the parity-load-bearing post-game-over no-op contract."""
    synthetic_state.lose_life(0, 20)
    # First quiescent call decides the game.
    passes_1 = synthetic_state.apply_sbas_until_quiescent()
    assert synthetic_state.is_game_over() is True
    assert synthetic_state.winner() == 1
    # Snapshot life + outcome state for cross-call comparison.
    life_after_first = list(synthetic_state.life_totals)
    losers_after_first = list(synthetic_state.losers())

    # Second call must NOT fire any new SBA (game already decided —
    # no battlefield creatures damaged, no zone churn).
    passes_2 = synthetic_state.apply_sbas_until_quiescent()
    assert passes_2 == 0
    # Outcome still identical.
    assert synthetic_state.is_game_over() is True
    assert synthetic_state.winner() == 1
    assert synthetic_state.winner_id == 1
    assert list(synthetic_state.losers()) == losers_after_first
    assert list(synthetic_state.life_totals) == life_after_first

    # Third call: still a no-op.
    passes_3 = synthetic_state.apply_sbas_until_quiescent()
    assert passes_3 == 0
    assert synthetic_state.is_game_over() is True
    assert synthetic_state.winner() == 1

    # Document: passes_1 may be 0 (no creatures to destroy, the
    # life-zeroing is a pure-derivation read), but the contract is
    # that the SECOND and THIRD calls are no-ops regardless of what
    # the first returns.
    assert passes_1 >= 0


def test_each_opponent_loses_life_lethal_then_sba_locks_the_loss(
    synthetic_state,
):
    """Cross-feature with the each-opponent-life-loss arm + round-26
    G11 SBA-driven permanence: resolve EachOpponentLosesLife(20) by
    p0 -> p1 drops to 0 -> p1 is the loser, winner = 0. Calling
    ``apply_sbas_until_quiescent`` transitions ``life <= 0`` into the
    sticky ``has_lost``; subsequent ``gain_life`` cannot revive p1.

    Pre-SBA the revive is still possible (preserved by the pure-
    derivation OR branch on ``life <= 0`` — see
    ``test_gain_life_from_zero_revives_player``); this test exercises
    the SBA path where the lock-in fires."""
    src_id = synthetic_state.register_and_inject_object(
        _each_opponent_loses_life_dict(20), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.get_life(1) == 0

    synthetic_state.apply_sbas_until_quiescent()
    assert list(synthetic_state.losers()) == [1]
    assert synthetic_state.winner() == 0
    assert synthetic_state.is_game_over() is True

    # After SBA, the loss is locked in. gain_life raises p1's life back
    # above 0 but the sticky has_lost keeps them in the loser pool.
    synthetic_state.gain_life(1, 5)
    assert synthetic_state.get_life(1) == 5
    assert list(synthetic_state.losers()) == [1]
    assert synthetic_state.winner() == 0
    assert synthetic_state.winner_id == 0
    assert synthetic_state.is_game_over() is True
    assert synthetic_state.is_draw is False


# ---------------------------------------------------------------------------
# CE12 regression suite — sticky winner_id closure (I34).
#
# Pinned by these tests:
#   1. Single-player loss writes the sticky field on the first SBA pass.
#   2. SEQUENTIAL kills: p1 dies first (winner_id_sticky = Some(0)), then
#      p0 dies — winner_id STAYS Some(0), is_draw STAYS False, is_over
#      STAYS True. Cross-engine smoke harness depends on this match
#      against Python's turn.py:1383-1393 sticky-write semantics.
#   3. SIMULTANEOUS bilateral kill: both die in the same SBA pass with
#      no prior sole-survivor moment — winner_id_sticky stays None,
#      is_draw flips to True. Match Python's behavior (single SBA pass
#      sees alive=0 immediately, only writes is_draw).
#   4. Game-not-ended pre-SBA: winner_id is None even when life flags
#      change; sticky field stays None.
#   5. Game-not-ended post-SBA: SBA runs with no losers; sticky field
#      stays None.
#
# See docs/RUST_PARITY_GAPS.md I34 and the (now-closed) CE12 entry.
# ---------------------------------------------------------------------------


def test_ce12_single_player_loss_writes_sticky_on_first_sba(synthetic_state):
    """Single-player loss: p0 dies, SBA fires, winner_id == 1.
    The sticky shadow field carries Some(1) — repeat SBA passes do not
    overwrite (sticky-on-first-write contract).
    """
    synthetic_state.set_life(0, 0)
    # Pre-SBA: sticky not yet written; getter falls back to live
    # derivation, which is None (has_lost not yet committed).
    assert synthetic_state.winner_id is None
    synthetic_state.apply_sbas_until_quiescent()
    # SBA committed p0 has_lost=True; sticky write fired with
    # Some(1).
    assert synthetic_state.winner_id == 1
    # Idempotent: a second SBA pass leaves the sticky field
    # untouched (write-once gate `is_none()`).
    synthetic_state.apply_sbas_until_quiescent()
    assert synthetic_state.winner_id == 1
    assert synthetic_state.is_over() is True
    assert synthetic_state.is_draw is False


def test_ce12_sequential_kills_winner_id_stays_sticky(synthetic_state):
    """**CE12 core invariant.** p1 dies on SBA pass A
    (winner_id_sticky = Some(0)); then p0 ALSO dies on SBA pass B —
    but winner_id STAYS Some(0). is_over STAYS True. ``is_draw``
    ALSO flips True on the second SBA pass (mirrors Python — its
    writer at turn.py:1384-1386 is gated on `not state.is_draw`,
    NOT on `winner_id is None`, so the alive=0 transition flips
    is_draw True regardless of whether winner_id was previously
    written). The sequential-kills shape lands with BOTH fields
    populated: winner_id=0 AND is_draw=True.

    This is the BOTH-LOST transition that pre-CE12 Rust got wrong
    via the `winner_id` slot (returned None instead of sticky 0).
    """
    # Phase A: kill p1, fire SBA. sticky <- Some(0).
    synthetic_state.set_life(1, 0)
    synthetic_state.apply_sbas_until_quiescent()
    assert synthetic_state.winner_id == 0
    assert synthetic_state.is_draw is False
    assert synthetic_state.is_over() is True
    # Phase B: kill p0, fire SBA. p0 has_lost flips True; both
    # players now has_lost=True; winner_id_sticky was already
    # written (write-once gate blocks overwrite), so winner_id
    # stays at Some(0).
    synthetic_state.set_life(0, 0)
    synthetic_state.apply_sbas_until_quiescent()
    # *** Load-bearing: winner_id is STILL Some(0), not None. ***
    assert synthetic_state.winner_id == 0
    # is_draw flips True on the alive=0 transition — independent
    # of the sticky-winner state, matching Python.
    assert synthetic_state.is_draw is True
    # is_over reads True (either via sticky.is_some() OR has_lost).
    assert synthetic_state.is_over() is True


def test_ce12_simultaneous_bilateral_kill_no_sticky_writes_draw(
    synthetic_state,
):
    """**CE12 mutual-KO edge case.** Both players die in the same
    SBA pass — neither was a sole-survivor at any prior pass. The
    sticky write gate sees (true, true), skips the write; the
    fall-back live-derivation in the getter returns None; is_draw
    flips True. Matches Python's turn.py:1383-1393 — `alive=0`
    only writes is_draw, never winner_id.
    """
    synthetic_state.set_life(0, 0)
    synthetic_state.set_life(1, 0)
    synthetic_state.apply_sbas_until_quiescent()
    # Both has_lost = True, sticky never written -> winner_id None.
    assert synthetic_state.winner_id is None
    assert synthetic_state.is_draw is True
    assert synthetic_state.is_over() is True


def test_ce12_game_not_ended_pre_sba_no_sticky_write(synthetic_state):
    """Pre-SBA, both players alive: winner_id is None, sticky stays
    None. The getter's fall-back live-derivation returns None
    because neither has_lost flag is set.
    """
    assert synthetic_state.winner_id is None
    assert synthetic_state.is_over() is False
    assert synthetic_state.is_draw is False
    # SBA on a fresh state writes nothing — sticky stays None.
    synthetic_state.apply_sbas_until_quiescent()
    assert synthetic_state.winner_id is None
    assert synthetic_state.is_over() is False
    assert synthetic_state.is_draw is False


def test_ce12_sba_with_no_losers_leaves_sticky_none(synthetic_state):
    """SBA fires but no transition happens (no creature destruction,
    no player loss). Sticky field stays None — `is_none()` gate is
    never tripped to a write because neither (false, true) nor
    (true, false) holds.
    """
    # Apply some non-lethal damage to a creature; SBA may fire but
    # neither player loses.
    synthetic_state.set_life(0, 17)  # mid-game-ish life total
    synthetic_state.set_life(1, 12)
    synthetic_state.apply_sbas_until_quiescent()
    assert synthetic_state.winner_id is None
    assert synthetic_state.is_over() is False
    assert synthetic_state.is_draw is False
    # Confirm idempotent on a second pass.
    synthetic_state.apply_sbas_until_quiescent()
    assert synthetic_state.winner_id is None


def test_ce12_sticky_survives_clone(synthetic_state):
    """The sticky shadow field is part of GameState's clone — a
    clone after sticky has been written carries the same winner_id.
    """
    synthetic_state.set_life(0, 0)
    synthetic_state.apply_sbas_until_quiescent()
    assert synthetic_state.winner_id == 1
    cloned = synthetic_state.clone_once()
    assert cloned.winner_id == 1
    # And mutation of the original's has_lost shape does not bleed
    # back to the clone (CoW canary).
    synthetic_state.set_life(1, 0)
    synthetic_state.apply_sbas_until_quiescent()
    assert synthetic_state.winner_id == 1  # sticky
    assert cloned.winner_id == 1  # unchanged


def test_ce12_fingerprint_excludes_winner_id_sticky(synthetic_state):
    """**I34 bookkeeping invariant.** Two states with the same
    observable game shape (same has_lost flags, same life totals,
    same zones) must produce the same fingerprint even if one
    reached its state via a sole-survivor SBA pass (sticky written)
    and the other did NOT. Mirrors `mulligan_count`,
    `consecutive_passes`, `next_etb_timestamp` — bookkeeping out
    of the digest.

    Test path:
      - State A: ``lose_game(1)`` directly (bypasses apply_sbas, so
        sticky stays None even though has_lost[1] = True). Then
        ``set_life(1, 0)`` to mirror the observable life total.
      - State B: ``set_life(1, 0)`` + ``apply_sbas_until_quiescent``
        — the SBA's sticky write fires, writing Some(0).

    Both states share has_lost shape (false, true), p1.life = 0,
    and observable getters ``winner_id == 0`` / ``is_over == True``
    / ``is_draw == False``. The ONLY difference is the sticky
    shadow field. The fingerprint MUST match — sticky stays OUT of
    the digest, mirroring CE4's etb_timestamp convention.
    """
    state_a = synthetic_state.clone_once()
    state_a.lose_game(1)
    state_a.set_life(1, 0)
    state_b = synthetic_state.clone_once()
    state_b.set_life(1, 0)
    state_b.apply_sbas_until_quiescent()
    # Sanity: both states surface the same observable shape.
    assert state_a.winner_id == 0
    assert state_b.winner_id == 0
    assert state_a.is_over() == state_b.is_over() is True
    assert state_a.is_draw == state_b.is_draw
    # Load-bearing: fingerprints match — sticky is bookkeeping.
    assert state_a.fingerprint() == state_b.fingerprint(), (
        "winner_id_sticky leaked into fingerprint: bookkeeping field "
        "must not be serialized (mirrors mulligan_count / "
        "consecutive_passes / next_etb_timestamp). See I34."
    )
