"""Control-change-UEOT subsystem — Cycle 1 (substrate-only).

Spec: lane brief (2026-05-21). The Rust side gains the per-object
``controller_override`` field, the ``effective_controller_id`` helper,
the cleanup-step drain that resets the override back to ``None``, the
bridge ``controller_override`` snapshot key, and the
``grant_control_change_ueot(target_id, new_controller_id)`` PyO3
method that mints the override.

Cycle 1 substrate-only — no live mint site is wired (no
Mutinous-Massacre / Systems-Override resolution arm in Rust); the
helper + drain are wired but no internal Rust read site routes
through the helper yet (Cycle 2 reroutes the call sites in
``state_ops_legal`` / ``state_ops_combat`` / ``state_ops_decisions``
/ ``state_ops_actions``).

Mirrors Python's `GameState.grant_control_change_ueot` in
`src/mtg_bot/game.py:2949` and `effective_controller(state, obj)` in
`game.py:999`. Cycle 3 will wire the cross-engine bridge round-trip;
this slice's tests use the Rust-side primitive directly without
crossing the Python ↔ Rust boundary on a real state.

**Tests cover:**

1. Default — every freshly-allocated object has
   ``controller_override = None``; snapshot surfaces ``None``.
2. Grant — ``grant_control_change_ueot(target_id, new_pid)`` sets
   the override; ``effective_controller_id(target_id)`` reads back
   the new pid; snapshot shows the override.
3. Idempotent — granting the same controller twice is a no-op on
   the second call (no observable change beyond ``True``).
4. Same-controller short-circuit — granting an object's CURRENT
   effective controller is a no-op (no override is set, since the
   answer is already the requested pid).
5. Missing target — silent ``False`` return when no battlefield
   permanent has the requested id (mirrors Python's defensive
   no-op at the head of `grant_control_change_ueot`).
6. Validation — out-of-range ``new_controller_id`` raises
   ``IndexError``.
7. Cleanup drain — ``cleanup_step_for_active_player`` reports the
   drain count in its returned dict; the override is reset to
   ``None`` after the cleanup pass.
8. Cleanup drain (standalone) — ``clear_controller_overrides_all``
   is callable independently; same drain semantics.
9. CoW — granting an override on a cloned state does NOT mutate
   the source's overrides. Same for the drain.
10. Bridge — the per-object snapshot dict emits ``controller_override:
    None`` when no override is set, and ``controller_override: <pid>``
    when set.
"""

from __future__ import annotations

import importlib
import importlib.util

import pytest


ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


def _fresh_state():
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


def _creature_dict(name="Bears", power=2, toughness=2):
    return {
        "name": name,
        "mana_cost": {"generic": 1, "G": 1},
        "card_types": ["Creature"],
        "subtypes": ["Bear"],
        "power": power,
        "toughness": toughness,
        "keywords": [],
    }


def _bf_obj(state, obj_id):
    for o in state.battlefield_snapshot():
        if o["id"] == obj_id:
            return o
    return None


# ---------------------------------------------------------------------------
# Default + snapshot
# ---------------------------------------------------------------------------


def test_default_controller_override_is_none():
    """Every freshly-allocated GameObject (via
    register_and_inject_object) has ``controller_override = None``.
    The snapshot surfaces ``None`` (the back-compat default). No
    pre-Cycle-1 pinned baseline observes a non-None value."""
    _require_engine()
    state = _fresh_state()
    bears_id = state.register_and_inject_object(
        _creature_dict(), 0, ZONE_BATTLEFIELD,
    )
    bf = _bf_obj(state, bears_id)
    assert bf is not None
    assert bf["controller_override"] is None


def test_snapshot_key_present_on_all_zones():
    """The ``controller_override`` key is in every per-object dict
    regardless of zone (hand / library / battlefield / graveyard).
    Pre-Cycle-1 the key didn't exist; this is the bridge-stable
    surface that downstream parity readers must agree on. Substrate-
    only: every value is ``None`` until Cycle 4 mints overrides."""
    _require_engine()
    state = _fresh_state()
    hand_id = state.register_and_inject_object(
        _creature_dict("HandBear"), 0, ZONE_HAND,
    )
    lib_id = state.register_and_inject_object(
        _creature_dict("LibBear"), 0, ZONE_LIBRARY,
    )
    bf_id = state.register_and_inject_object(
        _creature_dict("BfBear"), 0, ZONE_BATTLEFIELD,
    )
    gy_id = state.register_and_inject_object(
        _creature_dict("GyBear"), 0, ZONE_GRAVEYARD,
    )
    hand = next(o for o in state.hand_snapshot(0) if o["id"] == hand_id)
    lib = next(o for o in state.library_snapshot(0) if o["id"] == lib_id)
    bf = _bf_obj(state, bf_id)
    gy = next(o for o in state.graveyard_snapshot(0) if o["id"] == gy_id)
    for d in (hand, lib, bf, gy):
        assert "controller_override" in d
        assert d["controller_override"] is None


# ---------------------------------------------------------------------------
# Grant + effective_controller_id read
# ---------------------------------------------------------------------------


def test_grant_sets_override_and_effective_reads_back():
    """``grant_control_change_ueot(target_id, 0)`` on a P1-controlled
    permanent sets the override to 0. ``effective_controller_id``
    reads back the new pid. The raw ``controller`` field (visible
    via the snapshot) stays at the printed baseline (1) — Cycle 1
    does NOT mutate ``controller``; the override is the source-of-
    truth. (Python writes `obj.controller_id` as a write-through
    cache; the Rust shape stores the override separately for
    lighter mutation footprint.)"""
    _require_engine()
    state = _fresh_state()
    bears_id = state.register_and_inject_object(
        _creature_dict(), 1, ZONE_BATTLEFIELD,  # P1's creature
    )
    # Pre-grant baseline.
    bf = _bf_obj(state, bears_id)
    assert bf["controller_id"] == 1
    assert bf["controller_override"] is None
    # Pre-grant effective controller = printed baseline.
    assert state.effective_controller_id(bears_id) == 1
    # Grant — P0 takes control UEOT.
    ok = state.grant_control_change_ueot(bears_id, 0)
    assert ok is True
    # Effective controller flips to P0.
    assert state.effective_controller_id(bears_id) == 0
    # Snapshot: override is set to 0; raw controller still 1.
    bf = _bf_obj(state, bears_id)
    assert bf["controller_override"] == 0
    assert bf["controller_id"] == 1


def test_grant_p0_to_p1_then_p1_to_p0_chain():
    """Granting the override twice in succession with different
    target controllers — the second call overwrites the first.
    Models the "first Threaten resolves, second Threaten resolves
    later in the same turn" shape — only the most-recent override
    is in effect at any given moment."""
    _require_engine()
    state = _fresh_state()
    bears_id = state.register_and_inject_object(
        _creature_dict(), 0, ZONE_BATTLEFIELD,  # P0's creature
    )
    # P1 takes control first.
    state.grant_control_change_ueot(bears_id, 1)
    assert state.effective_controller_id(bears_id) == 1
    # Then P0 takes control back. (Hypothetical — would require
    # a Mutinous-Massacre-shape Effect on P0's turn; Cycle 1 is
    # substrate-only so we drive this from the Python primitive.)
    state.grant_control_change_ueot(bears_id, 0)
    assert state.effective_controller_id(bears_id) == 0


def test_grant_idempotent_same_pid_twice():
    """Granting the same controller twice is observable as ``True``
    + ``True`` and the override stays at that pid. No double-write
    artifact."""
    _require_engine()
    state = _fresh_state()
    bears_id = state.register_and_inject_object(
        _creature_dict(), 1, ZONE_BATTLEFIELD,
    )
    ok1 = state.grant_control_change_ueot(bears_id, 0)
    ok2 = state.grant_control_change_ueot(bears_id, 0)
    assert ok1 is True
    assert ok2 is True
    bf = _bf_obj(state, bears_id)
    assert bf["controller_override"] == 0


def test_grant_to_existing_controller_short_circuits():
    """Granting an object's CURRENT effective controller is a no-op
    (no override is set, since the answer is already that pid).
    Mirrors Python's
    `if effective_controller(...) == new_controller_id: return`
    short-circuit. The ``controller_override`` stays ``None`` (we
    didn't need to mint one), matching the conservation principle —
    the override is only set when it actually CHANGES the answer."""
    _require_engine()
    state = _fresh_state()
    bears_id = state.register_and_inject_object(
        _creature_dict(), 0, ZONE_BATTLEFIELD,  # P0's creature
    )
    # P0 "takes control" of its own creature. No-op.
    ok = state.grant_control_change_ueot(bears_id, 0)
    assert ok is True  # Returned True (we agreed with the request).
    bf = _bf_obj(state, bears_id)
    # Override stays None — we didn't need to mint one.
    assert bf["controller_override"] is None
    assert state.effective_controller_id(bears_id) == 0


def test_grant_missing_target_returns_false():
    """``grant_control_change_ueot`` on a target_id with no matching
    battlefield permanent is a silent no-op returning ``False``.
    Mirrors Python's defensive ``if target is None: return`` head
    of the method. No exception is raised — the caller (a Mutinous-
    Massacre `for o in state.battlefield` loop) constructs the
    call from a known-valid iteration so the not-found branch is
    paranoia, not a hot path."""
    _require_engine()
    state = _fresh_state()
    # No battlefield permanent at id 99999.
    ok = state.grant_control_change_ueot(99999, 0)
    assert ok is False


def test_grant_off_battlefield_target_returns_false():
    """An object in HAND (not BATTLEFIELD) is not a valid target —
    CR 613 layer-2 control-change only applies to permanents (which
    means battlefield objects per CR 110.4). Returns ``False``
    silently, no override is minted. (Python's
    `grant_control_change_ueot` walks `self.battlefield` only.)"""
    _require_engine()
    state = _fresh_state()
    in_hand = state.register_and_inject_object(
        _creature_dict("InHand"), 0, ZONE_HAND,
    )
    ok = state.grant_control_change_ueot(in_hand, 1)
    assert ok is False


def test_grant_invalid_pid_raises_index_error():
    """``new_controller_id`` must be 0 or 1 (the two-player engine);
    anything else raises IndexError. The lookup never runs (the
    validation gates first), so even a missing-target with bad pid
    raises rather than silently returning ``False``."""
    _require_engine()
    state = _fresh_state()
    bears_id = state.register_and_inject_object(
        _creature_dict(), 0, ZONE_BATTLEFIELD,
    )
    with pytest.raises(IndexError):
        state.grant_control_change_ueot(bears_id, 2)
    with pytest.raises(IndexError):
        state.grant_control_change_ueot(bears_id, 7)


def test_effective_controller_missing_target_raises():
    """``effective_controller_id`` on an off-battlefield id raises
    ``IndexError`` — distinct from ``grant_control_change_ueot``'s
    silent-no-op. The asymmetry is intentional: the grant call is
    often constructed inside a battlefield iteration where the not-
    found branch is dead code, but the read call is asked by
    downstream code that expects an answer."""
    _require_engine()
    state = _fresh_state()
    with pytest.raises(IndexError):
        state.effective_controller_id(99999)


# ---------------------------------------------------------------------------
# Cleanup-step drain
# ---------------------------------------------------------------------------


def test_cleanup_step_drains_controller_overrides():
    """``cleanup_step_for_active_player`` includes a CR 514.3 drain
    pass that resets every ``controller_override`` back to ``None``.
    The returned summary dict includes
    ``"controller_overrides_cleared"`` counting how many objects
    were drained."""
    _require_engine()
    state = _fresh_state()
    # Two creatures on P1's bf — P0 grants override on both.
    a_id = state.register_and_inject_object(
        _creature_dict("A"), 1, ZONE_BATTLEFIELD,
    )
    b_id = state.register_and_inject_object(
        _creature_dict("B"), 1, ZONE_BATTLEFIELD,
    )
    state.grant_control_change_ueot(a_id, 0)
    state.grant_control_change_ueot(b_id, 0)
    # Pre-cleanup: both overrides set.
    assert state.effective_controller_id(a_id) == 0
    assert state.effective_controller_id(b_id) == 0
    # Cleanup the active player (P0 by default).
    summary = state.cleanup_step_for_active_player()
    assert summary["controller_overrides_cleared"] == 2
    # Post-cleanup: overrides drained.
    a_bf = _bf_obj(state, a_id)
    b_bf = _bf_obj(state, b_id)
    assert a_bf["controller_override"] is None
    assert b_bf["controller_override"] is None
    # Effective controller reverts to the printed baseline.
    assert state.effective_controller_id(a_id) == 1
    assert state.effective_controller_id(b_id) == 1


def test_cleanup_step_warm_path_no_overrides():
    """A cleanup step on a state with no overrides set reports
    ``controller_overrides_cleared: 0`` and does not modify any
    object. (Warm-path optimization: the implementation skips the
    Arc::make_mut clone when no battlefield permanent has an
    override.)"""
    _require_engine()
    state = _fresh_state()
    a_id = state.register_and_inject_object(
        _creature_dict("A"), 1, ZONE_BATTLEFIELD,
    )
    summary = state.cleanup_step_for_active_player()
    assert summary["controller_overrides_cleared"] == 0
    a_bf = _bf_obj(state, a_id)
    assert a_bf["controller_override"] is None


def test_clear_controller_overrides_all_standalone():
    """The drain primitive is exposed independently of the full
    cleanup-step composition. Useful for tests that want to assert
    the drain in isolation from the hand-size + damage-clear
    passes."""
    _require_engine()
    state = _fresh_state()
    a_id = state.register_and_inject_object(
        _creature_dict("A"), 1, ZONE_BATTLEFIELD,
    )
    state.grant_control_change_ueot(a_id, 0)
    assert state.effective_controller_id(a_id) == 0
    cleared = state.clear_controller_overrides_all()
    assert cleared == 1
    assert state.effective_controller_id(a_id) == 1
    a_bf = _bf_obj(state, a_id)
    assert a_bf["controller_override"] is None


def test_clear_controller_overrides_warm_path():
    """``clear_controller_overrides_all`` on a state with no
    overrides reports 0 cleared, no allocation. Mirrors
    `clear_ueot_modifiers_all`'s warm-path shape."""
    _require_engine()
    state = _fresh_state()
    _ = state.register_and_inject_object(
        _creature_dict("A"), 1, ZONE_BATTLEFIELD,
    )
    cleared = state.clear_controller_overrides_all()
    assert cleared == 0


# ---------------------------------------------------------------------------
# CoW invariant — grant and drain are clone-safe
# ---------------------------------------------------------------------------


def test_grant_on_clone_does_not_affect_source():
    """Granting an override on a cloned state must not mutate the
    source. Same CoW canary shape as
    `test_clone_then_discard_does_not_affect_original` and the
    sister UEOT-modifier slice."""
    _require_engine()
    state = _fresh_state()
    bears_id = state.register_and_inject_object(
        _creature_dict(), 1, ZONE_BATTLEFIELD,
    )
    cloned = state.clone_once()
    cloned.grant_control_change_ueot(bears_id, 0)
    # Cloned: override set.
    assert cloned.effective_controller_id(bears_id) == 0
    cloned_bf = _bf_obj(cloned, bears_id)
    assert cloned_bf["controller_override"] == 0
    # Source: untouched.
    assert state.effective_controller_id(bears_id) == 1
    source_bf = _bf_obj(state, bears_id)
    assert source_bf["controller_override"] is None


def test_clear_overrides_on_clone_does_not_affect_source():
    """Draining the cloned state's overrides must not touch the
    source's overrides — sister CoW canary for the cleanup side."""
    _require_engine()
    state = _fresh_state()
    bears_id = state.register_and_inject_object(
        _creature_dict(), 1, ZONE_BATTLEFIELD,
    )
    # Grant on the SOURCE first.
    state.grant_control_change_ueot(bears_id, 0)
    cloned = state.clone_once()
    # Drain on the clone.
    cleared = cloned.clear_controller_overrides_all()
    assert cleared == 1
    # Clone: override drained.
    assert cloned.effective_controller_id(bears_id) == 1
    # Source: still has the override.
    assert state.effective_controller_id(bears_id) == 0
    source_bf = _bf_obj(state, bears_id)
    assert source_bf["controller_override"] == 0


# ---------------------------------------------------------------------------
# Cleanup composition — controller_overrides_cleared coexists with
# other drain counts
# ---------------------------------------------------------------------------


def test_cleanup_summary_carries_all_four_keys():
    """The cleanup summary dict carries
    ``discarded`` + ``damage_cleared`` + ``ueot_cleared`` +
    ``controller_overrides_cleared`` — Cycle 1 added the fourth.
    No pre-existing key was renamed; readers using the old three
    keys keep working."""
    _require_engine()
    state = _fresh_state()
    summary = state.cleanup_step_for_active_player()
    assert "discarded" in summary
    assert "damage_cleared" in summary
    assert "ueot_cleared" in summary
    assert "controller_overrides_cleared" in summary
