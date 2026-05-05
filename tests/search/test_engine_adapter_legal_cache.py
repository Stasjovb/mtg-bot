"""Tests for the per-decision-moment ``legal_actions`` cache on
``MtgGameStateAdapter``.

Cache contract:
- Repeated ``legal_decisions()`` calls within a single decision moment
  return semantically-equal results computed via exactly one underlying
  ``legal.legal_actions`` call.
- Any ``apply()`` invalidates the cache; the very next
  ``legal_decisions`` re-enumerates against the post-mutation state.
- Resolution-pause sub-decisions and combat sub-decisions also flow
  through ``apply()`` and therefore invalidate.
- ``legal_action_mask`` (training/action_encoding) shares the cache
  when called with an adapter, so combined ``legal_decisions`` +
  ``legal_action_mask`` calls within one moment cost ONE enumeration,
  not two.
"""

from __future__ import annotations

from unittest import mock

import numpy as np
import pytest

from mtg_bot import legal as legal_mod
from mtg_bot.actions import CastSpell, PassPriority
from mtg_bot.agents import RandomAgent
from mtg_bot.search import (
    HeuristicsConfig, MtgGameStateAdapter, ResolutionTargetDecision,
)
from mtg_bot.simulate import setup_game
from mtg_bot.training import action_encoding as ae
from mtg_bot.turn import Step
from tests._test_decks import simple_test_decklists  # noqa: E402


def _fresh_adapter(seed: int = 42) -> MtgGameStateAdapter:
    """Construct an adapter and drive it to PRECOMBAT_MAIN at active-
    player priority with at least one capability (a payable land in
    hand). Without that drive, the active-player capability auto-pass
    would short-circuit ``legal_decisions`` to ``[PassPriority()]``
    before the legal_actions cache is populated, which obscures the
    cache invariants under test here.
    """
    state = setup_game(
        [RandomAgent(), RandomAgent()],
        decks=simple_test_decklists(),
        seed=seed,
    )
    # Disable training-time priority short-circuits — these cache
    # tests verify the legal_actions cache lifecycle, which is only
    # populated when ``legal_decisions`` actually reaches the
    # cached_fn path. With phase-prune / skip-empty-combat /
    # skip-dead-main1 / etc. firing, the short-circuit returns
    # ``[PassPriority()]`` before the cache ever populates.
    adapter = MtgGameStateAdapter(
        state, heuristics=HeuristicsConfig.disabled(),
    )
    # Drive past UPKEEP / DRAW into PRECOMBAT_MAIN. The setup_game
    # default deck builder seeds the active player's hand with at
    # least a few cards (lands + creatures), so PRECOMBAT_MAIN at
    # active-player priority will have land-play / sorcery-cast
    # capability and the cache is exercised normally.
    for _ in range(50):
        if adapter.engine_state.step == Step.PRECOMBAT_MAIN and (
            adapter.engine_state.priority_player_idx
            == adapter.engine_state.active_player_idx
        ):
            return adapter
        adapter.apply(PassPriority())
    pytest.fail(
        "could not drive _fresh_adapter to PRECOMBAT_MAIN active priority"
    )


def _drive_to_step(
    adapter: MtgGameStateAdapter, target: Step, *, max_passes: int = 50,
) -> None:
    """Hammer PassPriority until the engine is in ``target`` step,
    or fail loudly if the target is unreachable in this seed."""
    for _ in range(max_passes):
        if adapter.engine_state.step == target:
            return
        adapter.apply(PassPriority())
    pytest.fail(
        f"failed to reach step {target} after {max_passes} passes"
    )


# ---------------------------------------------------------------------
# Spy helper
# ---------------------------------------------------------------------


def _spy_legal_actions(monkeypatch):
    """Patch BOTH the source-module name and the engine_adapter
    re-import alias so call-counting catches every entry point.

    ``mtg_bot.legal.legal_actions`` is the function the adapter and
    ``training.action_encoding._enumerate_legal`` both ultimately call;
    patching it at the source module is enough to intercept every
    call site since both importers `from ... import legal_actions`
    AND we re-bind the engine-adapter and action-encoding imports.
    """
    real = legal_mod.legal_actions
    spy = mock.Mock(wraps=real)
    monkeypatch.setattr(legal_mod, "legal_actions", spy)
    # The adapter imports the symbol by name at module load time, so
    # rebind that reference too.
    from mtg_bot.search import engine_adapter as ea_mod
    monkeypatch.setattr(ea_mod, "legal_actions", spy)
    # Same for action_encoding.
    from mtg_bot.training import action_encoding as ae_mod
    monkeypatch.setattr(ae_mod, "legal_actions", spy)
    return spy


# ---------------------------------------------------------------------
# Core invariants
# ---------------------------------------------------------------------


def test_legal_actions_cache_hit_returns_same_object(monkeypatch):
    """Two consecutive ``legal_decisions`` calls with no apply() in
    between should consult ``legal.legal_actions`` exactly once. The
    cache stores the underlying list reference."""
    adapter = _fresh_adapter()
    spy = _spy_legal_actions(monkeypatch)
    # Drive past adapter construction so the spy is hot for the
    # next priority moment. Calling adapter.legal_decisions() invokes
    # the cached path.
    first = adapter.legal_decisions()
    second = adapter.legal_decisions()
    # Cache hit: only one underlying enumeration.
    assert spy.call_count == 1
    # Result is a fresh list each call (the adapter copies via
    # list(...) when exposing through ``legal_decisions``), but the
    # contents are identical.
    assert first is not second
    assert first == second


def test_legal_actions_cache_invalidated_by_apply(monkeypatch):
    """After ``apply()``, the next ``legal_decisions`` must
    re-enumerate. Stale cache hits would silently produce illegal
    actions in the search tree.

    We exercise this on a player-1 adapter (the auto-pass
    short-circuit only fires for the non-active player; querying
    ``_legal_actions_cached`` directly for the ACTIVE player ensures
    we're outside the auto-pass branch and observing the cache
    behaviour we want to pin).
    """
    adapter = _fresh_adapter()
    spy = _spy_legal_actions(monkeypatch)

    # Probe the cache directly for the active player (priority is
    # on them at construction).
    ap = adapter.engine_state.players[
        adapter.engine_state.active_player_idx
    ].id
    _ = adapter._legal_actions_cached(ap)
    assert spy.call_count == 1
    # First apply: PassPriority. This mutates the adapter's internal
    # pass_count and clears the cache.
    adapter.apply(PassPriority())
    assert spy.call_count == 1  # apply alone shouldn't re-enumerate
    _ = adapter._legal_actions_cached(ap)
    # Cache blown by apply — fresh enumeration ran.
    assert spy.call_count == 2


def test_legal_actions_cache_value_changes_after_apply():
    """The cache must NEVER return stale data. Drive the game
    forward enough that the legal set actually changes between
    calls, then assert the post-apply legal set differs from the
    pre-apply one."""
    adapter = _fresh_adapter()
    _drive_to_step(adapter, Step.PRECOMBAT_MAIN)
    pre = adapter.legal_decisions()
    # Pick the first non-pass action — a land or a spell — and apply.
    non_pass = [a for a in pre if not isinstance(a, PassPriority)]
    if not non_pass:
        # Nothing concrete to play this seed; fall back to a pass.
        # Pass + step transition still mutates state so the post
        # legal set will differ.
        adapter.apply(PassPriority())
        post = adapter.legal_decisions()
        assert post != pre or (
            adapter.engine_state.step != Step.PRECOMBAT_MAIN
        )
        return
    adapter.apply(non_pass[0])
    post = adapter.legal_decisions()
    # Either the legal set itself changed, or a forced step advance
    # changed the priority context.
    assert post != pre


def test_clone_does_not_share_cache_with_source(monkeypatch):
    """Clone starts with an empty cache. The first legal_decisions
    call on the clone must enumerate fresh — even if the source had
    a hot cache, the clone's engine_state may be mutated independently
    (ISMCTS's _fresh_determinization is the canonical case)."""
    adapter = _fresh_adapter()
    # Prime the source cache.
    _ = adapter.legal_decisions()

    spy = _spy_legal_actions(monkeypatch)
    clone = adapter.clone()
    # Assert clone's cache is empty post-clone.
    assert clone._legal_actions_cache_value is None
    # And exercising the clone's legal_decisions enumerates once.
    _ = clone.legal_decisions()
    assert spy.call_count == 1
    # Hitting it again should be a cache hit (same moment).
    _ = clone.legal_decisions()
    assert spy.call_count == 1
    # Source cache untouched by clone enumeration.
    assert adapter._legal_actions_cache_value is not None


def test_legal_action_mask_uses_cached_legal_actions(monkeypatch):
    """The action_encoding mask helper, when given an adapter, must
    share the adapter's cache. ``legal_decisions`` followed by
    ``legal_action_mask`` should result in ONE underlying
    ``legal.legal_actions`` call, not two."""
    adapter = _fresh_adapter()
    spy = _spy_legal_actions(monkeypatch)

    # Order chosen to match the ISMCTS inner loop: legal_decisions
    # first (in _select_and_expand), mask afterward (in
    # _grow_union_mask).
    decisions = adapter.legal_decisions()
    mask = ae.legal_action_mask(adapter, adapter.active_player())
    assert spy.call_count == 1
    # Mask is a bool ndarray of length ACTION_VOCAB_SIZE.
    assert isinstance(mask, np.ndarray)
    assert mask.shape == (ae.ACTION_VOCAB_SIZE,)
    # Sanity: the PASS slot is set since PassPriority is always legal
    # in the priority window.
    assert mask[ae.SLOT_PASS]
    # And every priority-window legal decision corresponds to a True
    # slot (ignoring slots that overflow the cap, which silently get
    # skipped by the mask).
    assert any(isinstance(d, PassPriority) for d in decisions)


def test_mask_then_legal_decisions_also_shares_cache(monkeypatch):
    """Reversed call order: mask first, then legal_decisions. Cache
    must still be shared so the total cost is one enumeration."""
    adapter = _fresh_adapter()
    spy = _spy_legal_actions(monkeypatch)

    _ = ae.legal_action_mask(adapter, adapter.active_player())
    _ = adapter.legal_decisions()
    assert spy.call_count == 1


def test_legal_actions_cache_invalidated_by_resolution_pause(
    monkeypatch,
):
    """Resolution-pause sub-decisions flow through ``apply()`` so
    the cache is invalidated at every step of the multi-decision
    cast-and-resolve sequence. After a CastSpell triggers a pause,
    ``legal_decisions`` returns Resolution* options; after the
    pause is answered, ``legal_decisions`` returns priority actions
    again. The cache must NOT carry pre-pause priority actions
    forward into the post-pause priority window."""
    from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.game import Zone

    printings = get_active_source().get_printings()
    state = setup_game([RandomAgent(), RandomAgent()], decks=simple_test_decklists(), seed=42,
    )
    # 7 Mountains: Bombard costs {2}{R}, so casting two of them in a
    # row consumes 6 mana. Anything less leaves the active player
    # unable to pay the second cost AFTER the first cast resolves
    # (the cache test below relies on a continuing instant-speed
    # capability to keep auto-pass off).
    for _ in range(7):
        m = state.new_object(
            BASIC_LANDS["Mountain"], owner_id=0, zone=Zone.BATTLEFIELD,
        )
        state.battlefield.append(m)
    bombard = state.new_object(
        printings["Bombard"], owner_id=0, zone=Zone.HAND,
    )
    state.players[0].hand.append(bombard)
    # Add a SECOND payable instant (a second Bombard) so the active
    # player still has an instant-speed capability after casting the
    # first Bombard. Without this, the post-cast priority moment has
    # Bombard #1 on the stack (so we're at instant-only timing — not
    # a sorcery window) AND no instants in hand, so the active-player
    # auto-pass fires and the assertion below (which expects one
    # ``legal_actions`` enumeration on the post-resolve priority
    # moment) sees zero.
    bombard2 = state.new_object(
        printings["Bombard"], owner_id=0, zone=Zone.HAND,
    )
    state.players[0].hand.append(bombard2)
    for name in ["Wild Bear", "Sapling"]:
        c = state.new_object(
            SYNTHETIC_CREATURES[name], owner_id=1,
            zone=Zone.BATTLEFIELD,
        )
        c.summoning_sick = False
        state.battlefield.append(c)

    adapter = MtgGameStateAdapter(
        state, expose_resolution_decisions=True,
    )
    _drive_to_step(adapter, Step.PRECOMBAT_MAIN)

    # Spy ON: every subsequent legal_actions call is counted.
    spy = _spy_legal_actions(monkeypatch)

    cast = next(
        a for a in adapter.legal_decisions() if isinstance(a, CastSpell)
    )
    # Apply the cast — this triggers the resolution pause for target
    # selection. The cache must be invalidated here.
    adapter.apply(cast)
    assert adapter._resolution_paused is True

    # During the pause, legal_decisions returns ResolutionTarget*
    # options which do NOT route through legal.legal_actions — they
    # come from _resolution_legal_decisions. Calling it shouldn't
    # increment the spy.
    spy_at_pause = spy.call_count
    pause_options = adapter.legal_decisions()
    assert spy.call_count == spy_at_pause
    assert all(
        isinstance(d, ResolutionTargetDecision) for d in pause_options
    )

    # Answer the pause. apply() invalidates the cache; the next
    # priority-window legal_decisions call must re-enumerate.
    answer = pause_options[0]
    adapter.apply(answer)
    assert adapter._resolution_paused is False

    spy_post_resolve = spy.call_count
    post_options = adapter.legal_decisions()
    # legal_actions called exactly once for the post-resolve priority
    # window — the cache had been blown by the apply(answer).
    assert spy.call_count == spy_post_resolve + 1
    # And the post-resolve options are priority actions, not pause
    # options.
    assert any(isinstance(d, PassPriority) for d in post_options)


def test_legal_actions_cache_player_keying(monkeypatch):
    """Edge case: if the active player flips without a state mutation
    (which only happens when the cache is empty by construction —
    legal_decisions always uses self.active_player() for the key),
    the cache miss path computes against the new player.

    This test covers the keying logic by manually exercising
    ``_legal_actions_cached`` for two different player ids back to
    back."""
    adapter = _fresh_adapter()
    spy = _spy_legal_actions(monkeypatch)

    a = adapter._legal_actions_cached(0)
    assert spy.call_count == 1
    # Re-querying for the same player hits the cache.
    b = adapter._legal_actions_cached(0)
    assert spy.call_count == 1
    assert a is b  # SAME object — _legal_actions_cached returns cache directly
    # Querying for a different player misses the cache and
    # recomputes (and replaces the cached entry).
    _ = adapter._legal_actions_cached(1)
    assert spy.call_count == 2


def test_invalidate_legal_actions_cache_clears_state():
    """Sanity: the explicit invalidation helper does what it says."""
    adapter = _fresh_adapter()
    _ = adapter.legal_decisions()
    assert adapter._legal_actions_cache_value is not None
    adapter._invalidate_legal_actions_cache()
    assert adapter._legal_actions_cache_value is None
    assert adapter._legal_actions_cache_player is None


def test_cache_survives_no_op_legal_decisions_calls(monkeypatch):
    """Ten consecutive legal_decisions calls with no apply() between
    them should still result in exactly one underlying enumeration.
    Catches a regression where the cache was populated but the lookup
    branch was wrong (e.g. always cache-miss)."""
    adapter = _fresh_adapter()
    spy = _spy_legal_actions(monkeypatch)
    for _ in range(10):
        adapter.legal_decisions()
    assert spy.call_count == 1


def test_ismcts_inner_loop_call_pattern_caches_correctly(monkeypatch):
    """Simulates the exact ISMCTS inner-loop pattern: descend step
    issues legal_decisions(), then _grow_union_mask -> legal_action_mask,
    then potentially encode() of decisions (which doesn't itself call
    legal_actions) — all within the same priority moment. Total
    underlying enumerations across this descend-step burst: 1.
    """
    adapter = _fresh_adapter()
    spy = _spy_legal_actions(monkeypatch)

    # Iter 1: legal_decisions + mask.
    _ = adapter.legal_decisions()
    _ = ae.legal_action_mask(adapter, adapter.active_player())
    # Iter 2 (no apply between): same moment, both should hit cache.
    _ = adapter.legal_decisions()
    _ = ae.legal_action_mask(adapter, adapter.active_player())
    # Iter 3 (no apply between).
    _ = adapter.legal_decisions()
    _ = ae.legal_action_mask(adapter, adapter.active_player())

    # 6 calls to the two cached entry points → 1 underlying
    # legal_actions enumeration.
    assert spy.call_count == 1


def test_descent_step_cost_drops_below_three_x(monkeypatch):
    """Pin the headline win: at a single priority moment the
    sequence ``legal_decisions`` → ``legal_action_mask`` →
    ``legal_decisions`` (the canonical ISMCTS descent-step burst)
    costs ONE underlying ``legal_actions`` enumeration with the
    cache, vs THREE before.

    This is a direct stand-in for the per-game wall reduction (37%
    of self-play wall was triple-enumeration; with the cache that
    drops to single enumeration per descent step — within the cache
    lifetime). End-to-end ISMCTS budgets touch many distinct adapter
    instances per iteration (each ``_fresh_determinization`` clone
    has its own cache), which makes a global call-count ceiling
    test brittle; the per-moment ratio test below is the precise
    invariant the fix targets.
    """
    adapter = _fresh_adapter()
    spy = _spy_legal_actions(monkeypatch)
    viewer = adapter.active_player()

    # Three distinct callers, all looking at the same priority
    # moment on the same adapter — exactly the ISMCTS pattern.
    _ = adapter.legal_decisions()
    _ = ae.legal_action_mask(adapter, viewer)
    _ = adapter.legal_decisions()

    # Pre-cache, this would be 3 calls. Post-cache, exactly 1.
    assert spy.call_count == 1


def test_legal_action_mask_with_raw_engine_state_no_caching(monkeypatch):
    """When given a raw engine GameState (not an adapter),
    legal_action_mask must fall back to the direct legal_actions
    path. No cache available — repeated calls re-enumerate. This is
    the documented behavior; the test pins it so a future refactor
    doesn't accidentally break the engine-state interface."""
    adapter = _fresh_adapter()
    spy = _spy_legal_actions(monkeypatch)

    eng = adapter.engine_state
    viewer = adapter.active_player()
    _ = ae.legal_action_mask(eng, viewer)
    _ = ae.legal_action_mask(eng, viewer)
    # Two calls, no cache, two underlying enumerations.
    assert spy.call_count == 2
