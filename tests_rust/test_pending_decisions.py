"""Tests for the round-27 G20 decision-callback substrate.

Round-27 closes parity gap G20 (Surveil) by introducing a state-machine
decision callback: effects that need a controller-provided choice push
a ``PendingDecision`` onto ``state.pending_decisions`` and short-
circuit. The caller (MCTS, parity_smoke, test harness) inspects via
``pending_decisions()`` / ``has_pending_decision()``, submits a choice
via ``submit_surveil_decision(card_ids_to_top, card_ids_to_graveyard)``,
or auto-resolves via ``auto_resolve_pending_decisions(strategy)``.

These tests exercise the substrate end-to-end via the Surveil arm —
the first effect to use it. Future modal / scry-on-keep / London
bottom-N effects will follow the same shape.

The substrate is decoupled from ``resolve_top_of_stack``:

* ``resolve_top_of_stack`` auto-resolves with ``"keep_all_on_top"`` so
  pre-r27 baseline tests (``test_library.py`` r23 surveil etc.) are
  bit-equal to the pre-r27 path.
* ``resolve_top_of_stack_pause`` runs the same resolution flow WITHOUT
  the auto-resolve — leaving the pending-decision queue for the
  caller to inspect / submit.
"""

from __future__ import annotations

import pytest


# Zone constants per state_ops_zones — keep in sync with the Rust side.
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3
ZONE_EXILE = 4


def _surveil_dict(count: int = 1):
    """A surveil-N sorcery — Effect::Surveil dispatched on resolve."""
    return {
        "name": f"Test Surveil {count} (pending-decision)",
        "card_types": ["Sorcery"],
        "mana_cost": {"U": 1},
        "effects": [{"kind": "surveil", "count": count}],
    }


# --- queue introspection ---------------------------------------------


def test_initial_state_has_no_pending_decision(synthetic_state):
    """A freshly built synthetic state has no pending decision."""
    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.pending_decisions() == []


# --- Surveil-1: pause variant emits a SurveilChoice ------------------


def test_surveil_1_pause_pops_one_card_and_pushes_pending_decision(synthetic_state):
    """Surveil 1 via the pause-aware resolve path:
    1. Pops 1 card from library top (library size decreases by 1).
    2. Pushes one ``SurveilChoice`` onto the pending-decisions queue.
    3. The popped card is NOT yet in the graveyard.

    The source Sorcery still moves to its controller's graveyard via
    CR 608.2m, so graveyard grows by exactly 1 (the source, not the
    surveil-routed card)."""
    library_before = synthetic_state.library_sizes[0]
    graveyard_before = synthetic_state.graveyard_sizes[0]
    # The synthetic seed lays p0's library so top-of-library has the
    # highest id in the [17, 67) range.
    top_id_before = synthetic_state.library_snapshot(0)[-1]["id"]

    spell_obj_id = synthetic_state.register_and_inject_object(
        _surveil_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    # Library lost the top card.
    assert synthetic_state.library_sizes[0] == library_before - 1
    # Graveyard gained ONE card — the source Sorcery, not the popped
    # surveil card.
    assert synthetic_state.graveyard_sizes[0] == graveyard_before + 1
    # The popped surveil card is NOT in the graveyard.
    assert synthetic_state.find_object_zone(top_id_before) != ZONE_GRAVEYARD
    # ...nor in the library.
    assert synthetic_state.find_object_zone(top_id_before) != ZONE_LIBRARY

    # The pending decision is a SurveilChoice carrying the popped id.
    assert synthetic_state.has_pending_decision() is True
    pds = synthetic_state.pending_decisions()
    assert len(pds) == 1
    pd = pds[0]
    assert pd["kind"] == "SurveilChoice"
    assert pd["controller"] == 0
    assert pd["source_obj_id"] == spell_obj_id
    assert pd["cards"] == [top_id_before]


# --- submit: route to top --------------------------------------------


def test_submit_surveil_decision_to_top_returns_card_to_library(synthetic_state):
    """``submit_surveil_decision([card_id], [])`` returns the card to
    library top. After submission, the pending queue is empty and the
    library size is back to its pre-Surveil value."""
    library_before = synthetic_state.library_sizes[0]
    top_id_before = synthetic_state.library_snapshot(0)[-1]["id"]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _surveil_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    assert synthetic_state.has_pending_decision() is True

    synthetic_state.submit_surveil_decision([top_id_before], [])

    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.pending_decisions() == []
    # Library is back to its pre-Surveil size.
    assert synthetic_state.library_sizes[0] == library_before
    # The card is back in the library, and it's at the top.
    assert synthetic_state.find_object_zone(top_id_before) == ZONE_LIBRARY
    assert synthetic_state.library_snapshot(0)[-1]["id"] == top_id_before


# --- submit: route to graveyard --------------------------------------


def test_submit_surveil_decision_to_graveyard_mills_card(synthetic_state):
    """``submit_surveil_decision([], [card_id])`` sends the card to
    graveyard. After submission, the pending queue is empty, library
    stays smaller, and the card lives in graveyard."""
    library_before = synthetic_state.library_sizes[0]
    graveyard_before = synthetic_state.graveyard_sizes[0]
    top_id_before = synthetic_state.library_snapshot(0)[-1]["id"]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _surveil_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    synthetic_state.submit_surveil_decision([], [top_id_before])

    assert synthetic_state.has_pending_decision() is False
    # Library shrank by 1 (the surveil-routed card) and didn't come back.
    assert synthetic_state.library_sizes[0] == library_before - 1
    # Graveyard grew by 2: the source Sorcery (CR 608.2m) AND the
    # surveil-routed card.
    assert synthetic_state.graveyard_sizes[0] == graveyard_before + 2
    assert synthetic_state.find_object_zone(top_id_before) == ZONE_GRAVEYARD


# --- Surveil-3: partial submit (split top/graveyard) -----------------


def test_surveil_3_partial_submit_one_top_two_graveyard(engine):
    """Surveil 3 + partial submit: 1 card stays on top, 2 cards go to
    graveyard. Confirms the multi-card SurveilChoice surface."""
    state = engine.make_synthetic_state()
    library_before = state.library_sizes[0]
    graveyard_before = state.graveyard_sizes[0]

    # The surveil pops the top 3 ids; library is laid in push-order so
    # the top of library has the highest id, etc.
    lib_top_three = [obj["id"] for obj in state.library_snapshot(0)[-3:]]
    lib_top_three.reverse()  # cards[0] = topmost (popped first)

    spell_obj_id = state.register_and_inject_object(
        _surveil_dict(count=3), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack_pause()

    # SurveilChoice has 3 cards.
    pds = state.pending_decisions()
    assert len(pds) == 1
    assert pds[0]["cards"] == lib_top_three

    # Submit: send cards[0] to top, cards[1..3] to graveyard.
    keep = [lib_top_three[0]]
    mill = lib_top_three[1:]
    state.submit_surveil_decision(keep, mill)

    assert state.has_pending_decision() is False
    # Library shrank by 2 (the two milled), not 3.
    assert state.library_sizes[0] == library_before - 2
    # Graveyard grew by 3 (source + 2 milled).
    assert state.graveyard_sizes[0] == graveyard_before + 3
    # The kept card is the new top of library.
    assert state.find_object_zone(lib_top_three[0]) == ZONE_LIBRARY
    assert state.library_snapshot(0)[-1]["id"] == lib_top_three[0]
    # The milled cards live in graveyard.
    for mid in mill:
        assert state.find_object_zone(mid) == ZONE_GRAVEYARD


# --- auto-resolve: keep-all-on-top reproduces r23 baseline -----------


def test_auto_resolve_keep_all_on_top_reproduces_r23_baseline(synthetic_state):
    """``auto_resolve_pending_decisions("keep_all_on_top")`` is the
    r23 deterministic-keep-all behavior: surveil-popped cards return
    to library top in the original order, nothing routed to graveyard.

    After auto-resolve the state is bit-equal (zone-wise) to a state
    where the Surveil never paused — same library, same graveyard."""
    library_before = synthetic_state.library_sizes[0]
    graveyard_before = synthetic_state.graveyard_sizes[0]
    top_id_before = synthetic_state.library_snapshot(0)[-1]["id"]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _surveil_dict(count=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    assert synthetic_state.has_pending_decision() is True

    synthetic_state.auto_resolve_pending_decisions("keep_all_on_top")

    assert synthetic_state.has_pending_decision() is False
    # Library is unchanged by the round-trip.
    assert synthetic_state.library_sizes[0] == library_before
    # Graveyard gained only the source Sorcery.
    assert synthetic_state.graveyard_sizes[0] == graveyard_before + 1
    # Top of library is the same id as before.
    assert synthetic_state.library_snapshot(0)[-1]["id"] == top_id_before


def test_auto_resolve_send_all_to_graveyard_mills_surveiled_cards(synthetic_state):
    """``auto_resolve_pending_decisions("send_all_to_graveyard")``: every
    pending SurveilChoice's cards land in the controller's graveyard."""
    library_before = synthetic_state.library_sizes[0]
    graveyard_before = synthetic_state.graveyard_sizes[0]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _surveil_dict(count=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    synthetic_state.auto_resolve_pending_decisions("send_all_to_graveyard")

    assert synthetic_state.has_pending_decision() is False
    # Library lost 2 cards (the Surveil pop).
    assert synthetic_state.library_sizes[0] == library_before - 2
    # Graveyard gained 3: source + 2 milled.
    assert synthetic_state.graveyard_sizes[0] == graveyard_before + 3


def test_auto_resolve_with_unknown_strategy_raises(synthetic_state):
    """An unknown strategy is a hard ValueError, not a silent no-op."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _surveil_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    with pytest.raises(ValueError):
        synthetic_state.auto_resolve_pending_decisions("nonsense")
    # Queue not consumed on a failed strategy.
    assert synthetic_state.has_pending_decision() is True


# --- Invalid submission paths ----------------------------------------


def test_submit_surveil_with_unknown_id_raises(synthetic_state):
    """An id not in the pending SurveilChoice raises ValueError."""
    top_id_before = synthetic_state.library_snapshot(0)[-1]["id"]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _surveil_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    # 999999 is not the pending card's id.
    with pytest.raises(ValueError):
        synthetic_state.submit_surveil_decision([999999], [])
    # Failed submit leaves the queue intact (transactional).
    assert synthetic_state.has_pending_decision() is True

    # Recover: submit the right id.
    synthetic_state.submit_surveil_decision([top_id_before], [])
    assert synthetic_state.has_pending_decision() is False


def test_submit_surveil_missing_id_raises(synthetic_state):
    """Every pending id must appear in the submission. Surveil 2 with
    only one id submitted raises ValueError."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _surveil_dict(count=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    pending_ids = synthetic_state.pending_decisions()[0]["cards"]
    assert len(pending_ids) == 2

    # Submit only one of the two pending ids.
    with pytest.raises(ValueError):
        synthetic_state.submit_surveil_decision([pending_ids[0]], [])
    assert synthetic_state.has_pending_decision() is True


def test_submit_surveil_duplicate_id_raises(synthetic_state):
    """Submitting the same id in both top and graveyard (would route
    the same card twice) raises ValueError."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _surveil_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    pending_id = synthetic_state.pending_decisions()[0]["cards"][0]

    with pytest.raises(ValueError):
        synthetic_state.submit_surveil_decision([pending_id], [pending_id])
    assert synthetic_state.has_pending_decision() is True


def test_submit_surveil_decision_with_empty_queue_raises(synthetic_state):
    """Calling submit when there's no pending decision raises ValueError."""
    assert synthetic_state.has_pending_decision() is False
    with pytest.raises(ValueError):
        synthetic_state.submit_surveil_decision([42], [])


# --- count clamping & zero count -------------------------------------


def test_surveil_zero_emits_empty_surveilchoice(synthetic_state):
    """Surveil 0 with the pause variant emits a SurveilChoice with no
    cards — the substrate invariant (every Surveil emits exactly one
    PendingDecision) holds even for the trivial case. auto-resolve
    handles it as an O(1) no-op."""
    library_before = synthetic_state.library_sizes[0]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _surveil_dict(count=0), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    pds = synthetic_state.pending_decisions()
    assert len(pds) == 1
    assert pds[0]["cards"] == []
    assert synthetic_state.library_sizes[0] == library_before

    # Auto-resolve drains it cleanly.
    synthetic_state.auto_resolve_pending_decisions("keep_all_on_top")
    assert synthetic_state.has_pending_decision() is False


def test_surveil_count_exceeds_library_clamps_to_library_size(engine):
    """CR 701.43 clamps Surveil count to library size. Surveil 5 with a
    library of size 2 emits a SurveilChoice carrying exactly 2 cards."""
    state = engine.make_synthetic_state(num_battlefield=0, num_hand=0, num_library=2)
    spell_obj_id = state.register_and_inject_object(
        _surveil_dict(count=5), 0, ZONE_BATTLEFIELD
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack_pause()

    pds = state.pending_decisions()
    assert len(pds) == 1
    assert len(pds[0]["cards"]) == 2
    assert state.library_sizes[0] == 0


# --- resolve_top_of_stack auto-resolves (preserves r23 baseline) -----


def test_resolve_top_of_stack_auto_resolves_surveil(synthetic_state):
    """``resolve_top_of_stack`` (no -pause suffix) auto-resolves with
    "keep_all_on_top" — the r23-baseline-preserving path. After
    resolution there is NO pending decision and the library is
    unchanged."""
    library_before = synthetic_state.library_sizes[0]
    graveyard_before = synthetic_state.graveyard_sizes[0]
    top_id_before = synthetic_state.library_snapshot(0)[-1]["id"]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _surveil_dict(count=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.library_sizes[0] == library_before
    assert synthetic_state.graveyard_sizes[0] == graveyard_before + 1
    assert synthetic_state.library_snapshot(0)[-1]["id"] == top_id_before


# --- Fingerprint: pending decision changes the digest ---------------


def test_fingerprint_pending_decision_differs_from_empty(synthetic_state):
    """A state with a pending SurveilChoice fingerprints differently
    from the same state with no pending decisions. Confirms the
    fingerprint serializer participates in the decision queue.

    Pre-r27 baselines (every state in test_fingerprint.py has empty
    pending_decisions) are preserved — the fingerprint serializer
    appends the pending_decisions slot ONLY when non-empty. So a
    fresh synthetic state still hashes to the pre-r27 baseline; only
    states with a pending decision shift."""
    fp_clean = synthetic_state.fingerprint()
    spell_obj_id = synthetic_state.register_and_inject_object(
        _surveil_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    assert synthetic_state.has_pending_decision() is True
    fp_pending = synthetic_state.fingerprint()
    assert fp_pending != fp_clean

    # After draining, the digest should differ from `fp_pending` —
    # the SurveilChoice slot vanished and the library / graveyard
    # state shifted.
    synthetic_state.auto_resolve_pending_decisions("keep_all_on_top")
    fp_resolved = synthetic_state.fingerprint()
    assert fp_resolved != fp_pending


# --- Clone: pending decisions clone with the state ------------------


def test_clone_carries_pending_decisions(synthetic_state):
    """``clone_once()`` deep-clones the pending-decisions queue.
    Mutating one state's queue (via submit or auto-resolve) does NOT
    affect the other state's queue — the CoW canary for the new
    field."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _surveil_dict(count=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    assert synthetic_state.has_pending_decision() is True
    pending_ids = synthetic_state.pending_decisions()[0]["cards"]

    clone = synthetic_state.clone_once()
    assert clone.has_pending_decision() is True
    assert clone.pending_decisions()[0]["cards"] == pending_ids

    # Drain the clone — source must remain pending.
    clone.auto_resolve_pending_decisions("send_all_to_graveyard")
    assert clone.has_pending_decision() is False
    assert synthetic_state.has_pending_decision() is True
    assert synthetic_state.pending_decisions()[0]["cards"] == pending_ids
