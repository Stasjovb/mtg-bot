"""Tests for the adapter-carried structured-NN action history.

``MtgGameStateAdapter.apply`` records every strategically-relevant
decision (pre-apply snapshot + turn / step / actor) into
``adapter.recent_actions`` via
``mtg_bot.search.action_history.record_action_event``; ``clone()``
shares the tuple. ``data_gen`` (training rows) and ``NNEvaluator``
(search) both tokenize from that one attribute, so the load-bearing
property is: tokenizing with ``adapter.recent_actions`` is
byte-identical to tokenizing with the unbounded per-decision history
list the training writer used to keep by hand.

Covers:

- integration parity against the legacy data_gen construction over a
  real random trajectory, at every sample point, for both viewers;
- the ``DEFAULT_ACTION_HISTORY_N`` bound (applied after the §3
  filter, so the window holds the last N *relevant* events);
- clone / determinized-world inheritance (shared tuple, no aliasing
  between parent and child, snapshots immune to determinization);
- commit-after-success semantics (a raising apply leaves history
  untouched) and the no-clone fast path for filtered actions;
- ``record_action_event`` unit behaviour with synthetic events.
"""

from __future__ import annotations

import random

import numpy as np
import pytest

from mtg_bot.actions import PassPriority, PlayLand
from mtg_bot.agents import RandomAgent
from mtg_bot.search import MtgGameStateAdapter
from mtg_bot.search.action_history import (
    DEFAULT_ACTION_HISTORY_N,
    ActionEvent,
    _is_strategically_relevant,
    record_action_event,
)
from mtg_bot.search.determinize import determinize
from mtg_bot.simulate import setup_game
from mtg_bot.training import state_tokenizer
from mtg_bot.training.state_tokenizer import tokenize_state
from mtg_bot.training.structured_model import TOKEN_TYPE_ACTION_EVENT

from tests._test_decks import simple_test_deck_pool

# The trajectory tests below play random self-play through the
# adapter. Sample every k-th decision like data_gen does.
_SAMPLE_EVERY = 7


def _fresh_adapter(seed: int, **kwargs) -> MtgGameStateAdapter:
    pool = simple_test_deck_pool()
    d0, d1 = pool[seed % len(pool)], pool[(seed + 1) % len(pool)]
    engine = setup_game(
        [
            RandomAgent(rng=random.Random(seed + 1)),
            RandomAgent(rng=random.Random(seed + 2)),
        ],
        decks=[d0.cards, d1.cards],
        seed=seed,
    )
    return MtgGameStateAdapter(
        engine, expose_combat_decisions=True, **kwargs,
    )


def _legacy_event(adapter: MtgGameStateAdapter, decision) -> ActionEvent:
    """Build the event exactly the way ``data_gen`` used to before the
    history moved onto the adapter: clone the pre-apply engine state,
    capture turn / step / actor, record EVERY decision (the tokenizer
    filtered afterwards)."""
    engine_now = adapter.engine_state
    return ActionEvent(
        action=decision,
        state_snapshot=adapter.clone().engine_state,
        turn=engine_now.turn_number,
        step=engine_now.step,
        actor_player_id=adapter.active_player(),
    )


def _assert_token_dicts_equal(a: dict, b: dict) -> None:
    assert a.keys() == b.keys()
    for key in a:
        np.testing.assert_array_equal(a[key], b[key], err_msg=key)


def _n_action_tokens(tok: dict) -> int:
    return int((tok["token_type"] == TOKEN_TYPE_ACTION_EVENT).sum())


def _play_trajectory(
    adapter: MtgGameStateAdapter,
    rng: random.Random,
    max_decisions: int,
    on_sample=None,
) -> list[ActionEvent]:
    """Drive ``adapter`` with random legal decisions, keeping the
    legacy unbounded event list alongside. ``on_sample(adapter,
    legacy)`` fires every ``_SAMPLE_EVERY`` decisions (pre-apply,
    like data_gen's sample points)."""
    legacy: list[ActionEvent] = []
    for idx in range(max_decisions):
        if adapter.is_terminal():
            break
        legal = adapter.legal_decisions()
        if not legal:
            break
        if on_sample is not None and idx % _SAMPLE_EVERY == 0:
            on_sample(adapter, legacy)
        decision = rng.choice(legal)
        event = _legacy_event(adapter, decision)
        adapter.apply(decision)
        legacy.append(event)
    return legacy


# ---------------------------------------------------------------------
# (1) Integration parity vs the legacy data_gen construction
# ---------------------------------------------------------------------


@pytest.mark.parametrize("seed", [3, 11])
def test_adapter_history_tokenizes_identically_to_legacy_data_gen_list(
    seed: int,
) -> None:
    """At every sample point, for both viewers, ``tokenize_state``
    fed ``adapter.recent_actions`` must equal ``tokenize_state`` fed
    the unbounded every-decision list data_gen used to build. This is
    the train/inference-parity guarantee: the NN evaluator reads the
    same attribute the training writer now reads."""
    adapter = _fresh_adapter(seed)
    rng = random.Random(seed)
    checks = {"points": 0, "with_history": 0}

    def on_sample(ad: MtgGameStateAdapter, legacy: list[ActionEvent]) -> None:
        engine = ad.engine_state
        for viewer in (0, 1):
            got = tokenize_state(
                engine, viewer_id=viewer, recent_actions=ad.recent_actions,
            )
            want = tokenize_state(
                engine, viewer_id=viewer, recent_actions=legacy,
            )
            _assert_token_dicts_equal(got, want)
            checks["points"] += 1
            if _n_action_tokens(got) > 0:
                checks["with_history"] += 1

    legacy = _play_trajectory(adapter, rng, max_decisions=600, on_sample=on_sample)
    # The comparison must have been exercised on non-trivial history.
    assert checks["points"] > 20
    assert checks["with_history"] > 10
    # And the recorded tuple is exactly the filtered-then-bounded
    # legacy list (same action objects, same order).
    relevant = [
        ev for ev in legacy
        if _is_strategically_relevant(ev.action, ev.state_snapshot)
    ]
    assert [ev.action for ev in adapter.recent_actions] == [
        ev.action for ev in relevant[-DEFAULT_ACTION_HISTORY_N:]
    ]
    assert [(ev.turn, ev.step, ev.actor_player_id) for ev in adapter.recent_actions] == [
        (ev.turn, ev.step, ev.actor_player_id)
        for ev in relevant[-DEFAULT_ACTION_HISTORY_N:]
    ]


def test_parity_holds_with_resolution_decisions_exposed() -> None:
    """The resolution-pause path (rollback + replay inside the
    adapter) must record exactly one event per ``apply`` call — the
    priority action that paused AND each Resolution* answer — with
    the rolled-back pre-apply snapshot, matching the legacy list."""
    adapter = _fresh_adapter(5, expose_resolution_decisions=True)
    rng = random.Random(5)

    def on_sample(ad: MtgGameStateAdapter, legacy: list[ActionEvent]) -> None:
        engine = ad.engine_state
        for viewer in (0, 1):
            _assert_token_dicts_equal(
                tokenize_state(engine, viewer, ad.recent_actions),
                tokenize_state(engine, viewer, legacy),
            )

    legacy = _play_trajectory(adapter, rng, max_decisions=400, on_sample=on_sample)
    assert len(legacy) > 50


# ---------------------------------------------------------------------
# (2) Bounded at DEFAULT_ACTION_HISTORY_N
# ---------------------------------------------------------------------


def test_history_is_bounded_to_last_n_relevant_events() -> None:
    adapter = _fresh_adapter(21)
    rng = random.Random(21)
    legacy = _play_trajectory(adapter, rng, max_decisions=900)
    relevant = [
        ev for ev in legacy
        if _is_strategically_relevant(ev.action, ev.state_snapshot)
    ]
    # Random play through the adapter must have produced more relevant
    # decisions than the window so the bound is actually exercised.
    assert len(relevant) > DEFAULT_ACTION_HISTORY_N
    assert len(adapter.recent_actions) == DEFAULT_ACTION_HISTORY_N
    # ...and the window is the MOST RECENT relevant events (filter
    # before bound: PassPriority never consumes a slot).
    assert [ev.action for ev in adapter.recent_actions] == [
        ev.action for ev in relevant[-DEFAULT_ACTION_HISTORY_N:]
    ]
    assert not any(
        isinstance(ev.action, PassPriority) for ev in adapter.recent_actions
    )


def test_bound_matches_tokenizer_default_window() -> None:
    """The adapter's bound and the tokenizer's default ``n`` are the
    same constant — the whole point is that filter-then-truncate on
    the tokenizer side is a no-op for adapter-carried history."""
    assert DEFAULT_ACTION_HISTORY_N == 32
    assert state_tokenizer.DEFAULT_ACTION_HISTORY_N is DEFAULT_ACTION_HISTORY_N
    assert state_tokenizer.ActionEvent is ActionEvent
    assert state_tokenizer.record_action_event is record_action_event


# ---------------------------------------------------------------------
# (3) Clones and determinized worlds keep history
# ---------------------------------------------------------------------


def _adapter_with_some_history(seed: int = 8) -> MtgGameStateAdapter:
    adapter = _fresh_adapter(seed)
    rng = random.Random(seed)
    for _ in range(300):
        if adapter.is_terminal() or len(adapter.recent_actions) >= 6:
            break
        legal = adapter.legal_decisions()
        if not legal:
            break
        adapter.apply(rng.choice(legal))
    assert len(adapter.recent_actions) >= 6
    assert not adapter.is_terminal()
    return adapter


def test_clone_shares_history_tuple_without_aliasing() -> None:
    adapter = _adapter_with_some_history()
    before = adapter.recent_actions
    child = adapter.clone()
    # Shared by reference: zero per-clone cost, and identical content.
    assert child.recent_actions is before
    # Extending the child must not touch the parent (tuples rebind).
    rng = random.Random(1)
    for _ in range(200):
        if child.is_terminal():
            break
        legal = child.legal_decisions()
        if not legal:
            break
        child.apply(rng.choice(legal))
        if len(child.recent_actions) > len(before):
            break
    assert len(child.recent_actions) == len(before) + 1
    assert child.recent_actions[: len(before)] == before
    assert adapter.recent_actions is before


def test_determinized_world_inherits_history_and_tokens_unchanged() -> None:
    """PIMC / ISMCTS build a sub-search world as ``source.clone()`` +
    in-place determinization of the engine state. The world must keep
    the source's history, and — because every snapshot is its own
    clone — the action tokens must be byte-identical before and after
    the hidden zones are permuted."""
    adapter = _adapter_with_some_history()
    viewer = adapter.active_player()
    before_tokens = tokenize_state(
        adapter.engine_state, viewer, adapter.recent_actions,
    )
    world = adapter.clone()
    determinize(
        world.engine_state, viewer, random.Random(99), in_place=True,
    )
    assert world.recent_actions is adapter.recent_actions
    after = tokenize_state(world.engine_state, viewer, world.recent_actions)
    action_rows_before = before_tokens["token_type"] == TOKEN_TYPE_ACTION_EVENT
    action_rows_after = after["token_type"] == TOKEN_TYPE_ACTION_EVENT
    assert action_rows_before.sum() == action_rows_after.sum() > 0
    np.testing.assert_array_equal(
        before_tokens["token_emb_ids"][action_rows_before],
        after["token_emb_ids"][action_rows_after],
    )
    np.testing.assert_array_equal(
        before_tokens["token_scalars"][action_rows_before],
        after["token_scalars"][action_rows_after],
    )


def test_snapshot_is_a_clone_not_the_live_state() -> None:
    adapter = _adapter_with_some_history()
    for ev in adapter.recent_actions:
        assert ev.state_snapshot is not adapter.engine_state


# ---------------------------------------------------------------------
# apply() semantics
# ---------------------------------------------------------------------


def test_raising_apply_leaves_history_untouched() -> None:
    adapter = _adapter_with_some_history()
    before = adapter.recent_actions
    with pytest.raises(TypeError):
        adapter.apply("not a decision")  # type: ignore[arg-type]
    assert adapter.recent_actions is before


def test_apply_on_terminal_raises_before_recording() -> None:
    adapter = _fresh_adapter(2)
    rng = random.Random(2)
    while not adapter.is_terminal():
        legal = adapter.legal_decisions()
        if not legal:
            pytest.skip("random play stalled before a terminal state")
        adapter.apply(rng.choice(legal))
    before = adapter.recent_actions
    with pytest.raises(ValueError):
        adapter.apply(PassPriority())
    assert adapter.recent_actions is before


def test_fresh_adapter_starts_with_empty_history() -> None:
    assert _fresh_adapter(1).recent_actions == ()


# ---------------------------------------------------------------------
# record_action_event unit behaviour
# ---------------------------------------------------------------------


def test_record_action_event_skips_pass_priority_without_cloning(
    monkeypatch,
) -> None:
    adapter = _fresh_adapter(4)
    engine = adapter.engine_state
    calls = {"clone": 0}
    real_clone = type(engine).clone

    def counting_clone(self):
        calls["clone"] += 1
        return real_clone(self)

    monkeypatch.setattr(type(engine), "clone", counting_clone)
    history: tuple[ActionEvent, ...] = ()
    out = record_action_event(
        history, action=PassPriority(), pre_apply_state=engine,
        actor_player_id=0,
    )
    assert out is history
    assert calls["clone"] == 0


def test_record_action_event_captures_pre_apply_moment_and_bounds() -> None:
    adapter = _fresh_adapter(4)
    engine = adapter.engine_state
    land_id = engine.players[0].hand[0].id
    history: tuple[ActionEvent, ...] = ()
    for i in range(5):
        history = record_action_event(
            history, action=PlayLand(card_id=land_id),
            pre_apply_state=engine, actor_player_id=i % 2, n=3,
        )
    assert len(history) == 3
    # Most recent three survive, oldest first.
    assert [ev.actor_player_id for ev in history] == [0, 1, 0]
    for ev in history:
        assert ev.turn == engine.turn_number
        assert ev.step == engine.step
        assert ev.state_snapshot is not engine
        assert isinstance(ev.action, PlayLand)
    # Input tuples are never mutated.
    older = history
    newer = record_action_event(
        older, action=PlayLand(card_id=land_id),
        pre_apply_state=engine, actor_player_id=1, n=3,
    )
    assert len(older) == 3 and newer is not older
