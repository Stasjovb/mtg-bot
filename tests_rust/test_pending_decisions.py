"""Tests for the round-27 / round-28 decision-callback substrate.

Round-27 closes parity gap G20 (Surveil) by introducing a state-machine
decision callback: effects that need a controller-provided choice push
a ``PendingDecision`` onto ``state.pending_decisions`` and short-
circuit. The caller (MCTS, parity_smoke, test harness) inspects via
``pending_decisions()`` / ``has_pending_decision()``, submits a choice
via ``submit_surveil_decision(card_ids_to_top, card_ids_to_graveyard)``,
or auto-resolves via ``auto_resolve_pending_decisions(strategy)``.

The substrate is decoupled from ``resolve_top_of_stack``:

* ``resolve_top_of_stack`` auto-resolves with ``"keep_all_on_top"`` so
  pre-r27 baseline tests (``test_library.py`` r23 surveil etc.) are
  bit-equal to the pre-r27 path.
* ``resolve_top_of_stack_pause`` runs the same resolution flow WITHOUT
  the auto-resolve — leaving the pending-decision queue for the
  caller to inspect / submit.

Round-28 extends the substrate with a ``MayDoChoice`` variant
(`Effect::MayDo` wrapper — "you may [inner effect]"). The dispatcher
adds ``submit_may_do_decision(yes: bool)``, and auto-resolve gains
``"may_do_yes"`` / ``"may_do_no"`` / ``"default"`` strategies (the
"default" answers "yes" to match Python's base-Agent no-seated-agent
shape). The pattern generalizes — future ``IfYouDo`` / optional-mana-
cost / look-at-top-N variants slot in by adding (1) a PendingDecision
arm, (2) a submit_*_decision dispatcher, (3) a parse + resolve arm.
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
    top_id_before = synthetic_state.library_snapshot(0)[0]["id"]

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
    top_id_before = synthetic_state.library_snapshot(0)[0]["id"]
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
    assert synthetic_state.library_snapshot(0)[0]["id"] == top_id_before


# --- submit: route to graveyard --------------------------------------


def test_submit_surveil_decision_to_graveyard_mills_card(synthetic_state):
    """``submit_surveil_decision([], [card_id])`` sends the card to
    graveyard. After submission, the pending queue is empty, library
    stays smaller, and the card lives in graveyard."""
    library_before = synthetic_state.library_sizes[0]
    graveyard_before = synthetic_state.graveyard_sizes[0]
    top_id_before = synthetic_state.library_snapshot(0)[0]["id"]
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
    # Post-CE3: lib[:3] is already top-first (cards[0] = topmost).
    lib_top_three = [obj["id"] for obj in state.library_snapshot(0)[:3]]

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
    assert state.library_snapshot(0)[0]["id"] == lib_top_three[0]
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
    top_id_before = synthetic_state.library_snapshot(0)[0]["id"]
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
    assert synthetic_state.library_snapshot(0)[0]["id"] == top_id_before


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
    top_id_before = synthetic_state.library_snapshot(0)[0]["id"]
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
    top_id_before = synthetic_state.library_snapshot(0)[0]["id"]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _surveil_dict(count=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.library_sizes[0] == library_before
    assert synthetic_state.graveyard_sizes[0] == graveyard_before + 1
    assert synthetic_state.library_snapshot(0)[0]["id"] == top_id_before


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


# =====================================================================
# Round-28 MayDo decision substrate
# =====================================================================
#
# Round-28 extends the round-27 substrate with ``PendingDecision::
# MayDoChoice`` — the "you may [inner effect]" wrapper. On resolve, the
# Effect pushes a MayDoChoice onto the queue and short-circuits; the
# controller drains via ``submit_may_do_decision(yes)`` (manual) or
# ``auto_resolve_pending_decisions("default" | "may_do_yes" |
# "may_do_no")``. "Yes" applies the inner effect; "no" drops it.


def _may_do_draw_dict(count: int = 1, prompt: str = ""):
    """A may-do sorcery whose inner effect is ``draw_cards`` —
    verifiable via the controller's hand size."""
    eff = {
        "kind": "may_do",
        "inner_effect": {"kind": "draw_cards", "count": count},
    }
    if prompt:
        eff["prompt"] = prompt
    return {
        "name": f"Test MayDo Draw {count}",
        "card_types": ["Sorcery"],
        "mana_cost": {"U": 1},
        "effects": [eff],
    }


# --- register / parse round-trip -------------------------------------


def test_may_do_registers_as_effect_with_inner(engine):
    """A may_do sorcery registers cleanly and surfaces its inner
    effect through the printing readback (the dict round-trip)."""
    reg = engine.Registry()
    pid = reg.register_printing(_may_do_draw_dict(count=2, prompt="Draw two?"))
    effects = reg.get_printing_effects(pid)
    assert len(effects) == 1
    eff = effects[0]
    assert eff["kind"] == "may_do"
    assert eff["prompt"] == "Draw two?"
    assert eff["inner_effect"]["kind"] == "draw_cards"
    assert eff["inner_effect"]["count"] == 2


def test_may_do_missing_inner_effect_raises(engine):
    """``may_do`` without ``inner_effect`` is a hard ValueError."""
    reg = engine.Registry()
    bad = {
        "name": "Bad MayDo",
        "card_types": ["Sorcery"],
        "mana_cost": {"U": 1},
        "effects": [{"kind": "may_do"}],
    }
    with pytest.raises(ValueError):
        reg.register_printing(bad)


# --- resolve pushes MayDoChoice --------------------------------------


def test_may_do_resolve_pushes_pending_choice(synthetic_state):
    """Resolving a MayDo sorcery pushes one MayDoChoice onto the
    queue. The inner draw has NOT yet fired (hand size unchanged
    by the inner effect). The source still moves to graveyard via
    CR 608.2m."""
    hand_before = synthetic_state.hand_sizes[0]
    graveyard_before = synthetic_state.graveyard_sizes[0]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _may_do_draw_dict(count=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    # Source moved to graveyard, but inner draw is pending.
    assert synthetic_state.graveyard_sizes[0] == graveyard_before + 1
    # Hand grew by 1 from registering+injecting the sorcery, then
    # shrank by 1 (cast moves hand → stack → graveyard). Net: same.
    assert synthetic_state.hand_sizes[0] == hand_before

    # Exactly one MayDoChoice in the queue.
    assert synthetic_state.has_pending_decision() is True
    pds = synthetic_state.pending_decisions()
    assert len(pds) == 1
    pd = pds[0]
    assert pd["kind"] == "MayDoChoice"
    assert pd["controller"] == 0
    assert pd["source_obj_id"] == spell_obj_id
    assert pd["inner_effect"]["kind"] == "draw_cards"
    assert pd["inner_effect"]["count"] == 2


# --- submit: yes / no ------------------------------------------------


def test_submit_may_do_yes_applies_inner_effect(synthetic_state):
    """``submit_may_do_decision(True)`` applies the inner draw,
    growing the controller's hand by the inner count and consuming
    the pending decision."""
    hand_before = synthetic_state.hand_sizes[0]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _may_do_draw_dict(count=3), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    assert synthetic_state.has_pending_decision() is True

    synthetic_state.submit_may_do_decision(True)

    assert synthetic_state.has_pending_decision() is False
    # The cast itself was a net zero on hand (inject +1, cast -1).
    # The inner draw added 3 to the hand.
    assert synthetic_state.hand_sizes[0] == hand_before + 3


def test_submit_may_do_no_drops_inner_effect(synthetic_state):
    """``submit_may_do_decision(False)`` drops the inner effect
    without applying it. Hand size unchanged by the may-do path."""
    hand_before = synthetic_state.hand_sizes[0]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _may_do_draw_dict(count=3), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    synthetic_state.submit_may_do_decision(False)

    assert synthetic_state.has_pending_decision() is False
    # No inner-effect application — hand is back to its pre-cast
    # value (inject +1, cast -1, no inner draw).
    assert synthetic_state.hand_sizes[0] == hand_before


# --- submit dispatcher mismatches ------------------------------------


def test_submit_may_do_decision_with_empty_queue_raises(synthetic_state):
    """``submit_may_do_decision`` on an empty queue raises ValueError."""
    assert synthetic_state.has_pending_decision() is False
    with pytest.raises(ValueError):
        synthetic_state.submit_may_do_decision(True)


def test_submit_may_do_on_surveil_head_raises(synthetic_state):
    """``submit_may_do_decision`` when the head is a SurveilChoice
    (not a MayDoChoice) raises ValueError. The queue is left intact
    so the caller can recover by calling the right dispatcher."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _surveil_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    assert synthetic_state.pending_decisions()[0]["kind"] == "SurveilChoice"

    with pytest.raises(ValueError):
        synthetic_state.submit_may_do_decision(True)
    # Transactional: queue intact, kind still SurveilChoice.
    assert synthetic_state.has_pending_decision() is True
    assert synthetic_state.pending_decisions()[0]["kind"] == "SurveilChoice"


def test_submit_surveil_on_may_do_head_raises(synthetic_state):
    """``submit_surveil_decision`` when the head is a MayDoChoice
    raises ValueError. Symmetric to the test above."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _may_do_draw_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    assert synthetic_state.pending_decisions()[0]["kind"] == "MayDoChoice"

    with pytest.raises(ValueError):
        synthetic_state.submit_surveil_decision([], [])
    # Transactional: queue intact, kind still MayDoChoice.
    assert synthetic_state.has_pending_decision() is True
    assert synthetic_state.pending_decisions()[0]["kind"] == "MayDoChoice"


# --- auto-resolve strategies -----------------------------------------


def test_auto_resolve_default_says_yes_to_may_do(synthetic_state):
    """``auto_resolve_pending_decisions("default")`` answers "yes" to
    a MayDoChoice — mirrors Python's no-agent-seated default. The
    inner draw fires."""
    hand_before = synthetic_state.hand_sizes[0]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _may_do_draw_dict(count=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    synthetic_state.auto_resolve_pending_decisions("default")

    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.hand_sizes[0] == hand_before + 2


def test_auto_resolve_may_do_yes_applies_inner(synthetic_state):
    """``auto_resolve_pending_decisions("may_do_yes")`` applies the
    inner draw — same observable effect as ``"default"``."""
    hand_before = synthetic_state.hand_sizes[0]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _may_do_draw_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    synthetic_state.auto_resolve_pending_decisions("may_do_yes")

    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.hand_sizes[0] == hand_before + 1


def test_auto_resolve_may_do_no_drops_inner(synthetic_state):
    """``auto_resolve_pending_decisions("may_do_no")`` drops the
    inner effect — hand unchanged by the MayDo arm."""
    hand_before = synthetic_state.hand_sizes[0]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _may_do_draw_dict(count=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    synthetic_state.auto_resolve_pending_decisions("may_do_no")

    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.hand_sizes[0] == hand_before


def test_resolve_top_of_stack_auto_resolves_may_do_yes(synthetic_state):
    """The non-pause ``resolve_top_of_stack`` auto-resolves the
    MayDo with the "yes" default (matches Python's base-Agent
    no-seated-agent shape). The inner draw fires automatically."""
    hand_before = synthetic_state.hand_sizes[0]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _may_do_draw_dict(count=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.hand_sizes[0] == hand_before + 2


# --- fingerprint & clone --------------------------------------------


def test_fingerprint_may_do_pending_differs_from_empty(synthetic_state):
    """A state with a pending MayDoChoice fingerprints differently
    from the same state with no pending decisions. Confirms the
    serializer participates."""
    fp_clean = synthetic_state.fingerprint()
    spell_obj_id = synthetic_state.register_and_inject_object(
        _may_do_draw_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    assert synthetic_state.has_pending_decision() is True
    fp_pending = synthetic_state.fingerprint()
    assert fp_pending != fp_clean


def test_clone_isolates_may_do_pending_decisions(synthetic_state):
    """``clone_once()`` deep-clones a pending MayDoChoice. Resolving
    the clone leaves the source's queue intact (CoW canary for the
    new variant)."""
    hand_before = synthetic_state.hand_sizes[0]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _may_do_draw_dict(count=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    assert synthetic_state.has_pending_decision() is True

    clone = synthetic_state.clone_once()
    assert clone.has_pending_decision() is True
    assert clone.pending_decisions()[0]["kind"] == "MayDoChoice"

    # Drain the clone with "yes" — source must remain pending.
    clone.submit_may_do_decision(True)
    assert clone.has_pending_decision() is False
    assert clone.hand_sizes[0] == hand_before + 2

    assert synthetic_state.has_pending_decision() is True
    # The source's hand is still pre-inner-draw.
    assert synthetic_state.hand_sizes[0] == hand_before


# =====================================================================
# Round-28 LookTopN-put-one-in-hand-rest-to-graveyard
# =====================================================================
#
# Third variant of the multi-variant decision-callback substrate:
# ``PendingDecision::PickCardFromExaminedChoice`` — examine top N
# cards of library, controller picks ONE to put into hand, rest go to
# graveyard. Dispatcher: ``submit_pick_card_decision(chosen_id)``.
# Auto-resolve: ``"default"`` / ``"pick_top"`` pick the topmost (cards[0]).


def _look_top_n_dict(n: int = 4):
    """A LookTopN sorcery — Effect::LookTopNPutOneInHandRestToGraveyard
    dispatched on resolve."""
    return {
        "name": f"Test LookTopN {n}",
        "card_types": ["Sorcery"],
        "mana_cost": {"B": 1},
        "effects": [{"kind": "look_top_n_put_one_in_hand_rest_to_graveyard", "n": n}],
    }


def test_look_top_n_registers_with_n_field(engine):
    """A LookTopN sorcery registers cleanly and round-trips its `n`
    through the printing readback."""
    reg = engine.Registry()
    pid = reg.register_printing(_look_top_n_dict(n=3))
    effects = reg.get_printing_effects(pid)
    assert len(effects) == 1
    eff = effects[0]
    assert eff["kind"] == "look_top_n_put_one_in_hand_rest_to_graveyard"
    assert eff["n"] == 3


def test_look_top_n_default_n_is_4(engine):
    """Omitting `n` defaults to 4 — Commune-with-Evil's printed value."""
    reg = engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test LookTopN default",
            "card_types": ["Sorcery"],
            "mana_cost": {"B": 1},
            "effects": [{"kind": "look_top_n_put_one_in_hand_rest_to_graveyard"}],
        }
    )
    effects = reg.get_printing_effects(pid)
    assert effects[0]["n"] == 4


def test_look_top_n_negative_n_raises(engine):
    """Negative `n` is a hard ValueError at register time."""
    reg = engine.Registry()
    with pytest.raises(ValueError):
        reg.register_printing(
            {
                "name": "Bad LookTopN",
                "card_types": ["Sorcery"],
                "mana_cost": {"B": 1},
                "effects": [{"kind": "look_top_n_put_one_in_hand_rest_to_graveyard", "n": -1}],
            }
        )


def test_look_top_n_resolve_pops_cards_and_pushes_pending_choice(synthetic_state):
    """Resolving LookTopN-2 pops 2 cards from library top and pushes
    one PickCardFromExaminedChoice carrying those 2 cards. Hand and
    graveyard are NOT yet touched by the inner routing (graveyard still
    gains the source via CR 608.2m)."""
    library_before = synthetic_state.library_sizes[0]
    graveyard_before = synthetic_state.graveyard_sizes[0]
    hand_before = synthetic_state.hand_sizes[0]
    top_two = [obj["id"] for obj in synthetic_state.library_snapshot(0)[:2]]

    spell_obj_id = synthetic_state.register_and_inject_object(
        _look_top_n_dict(n=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    assert synthetic_state.library_sizes[0] == library_before - 2
    # Graveyard gained 1 (source). Examined cards NOT yet routed.
    assert synthetic_state.graveyard_sizes[0] == graveyard_before + 1
    assert synthetic_state.hand_sizes[0] == hand_before
    for cid in top_two:
        zone = synthetic_state.find_object_zone(cid)
        assert zone not in (ZONE_HAND, ZONE_LIBRARY, ZONE_GRAVEYARD)

    pds = synthetic_state.pending_decisions()
    assert len(pds) == 1
    pd = pds[0]
    assert pd["kind"] == "PickCardFromExaminedChoice"
    assert pd["source_obj_id"] == spell_obj_id
    assert pd["controller"] == 0
    assert pd["cards"] == top_two


def test_submit_pick_card_picks_topmost_routes_one_to_hand(synthetic_state):
    """Submitting cards[0] (topmost) routes it to hand and the second
    examined card to graveyard."""
    hand_before = synthetic_state.hand_sizes[0]
    graveyard_before = synthetic_state.graveyard_sizes[0]
    top_two = [obj["id"] for obj in synthetic_state.library_snapshot(0)[:2]]

    spell_obj_id = synthetic_state.register_and_inject_object(
        _look_top_n_dict(n=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    synthetic_state.submit_pick_card_decision(top_two[0])

    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.find_object_zone(top_two[0]) == ZONE_HAND
    assert synthetic_state.find_object_zone(top_two[1]) == ZONE_GRAVEYARD
    assert synthetic_state.hand_sizes[0] == hand_before + 1
    assert synthetic_state.graveyard_sizes[0] == graveyard_before + 2


def test_submit_pick_card_picks_non_topmost(synthetic_state):
    """Picking cards[1] routes it to hand and cards[0] to graveyard."""
    top_two = [obj["id"] for obj in synthetic_state.library_snapshot(0)[:2]]

    spell_obj_id = synthetic_state.register_and_inject_object(
        _look_top_n_dict(n=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    synthetic_state.submit_pick_card_decision(top_two[1])

    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.find_object_zone(top_two[1]) == ZONE_HAND
    assert synthetic_state.find_object_zone(top_two[0]) == ZONE_GRAVEYARD


def test_submit_pick_card_unknown_id_raises(synthetic_state):
    """An id not in the examined Vec raises ValueError. Queue intact."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _look_top_n_dict(n=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    with pytest.raises(ValueError):
        synthetic_state.submit_pick_card_decision(999999)
    assert synthetic_state.has_pending_decision() is True
    assert synthetic_state.pending_decisions()[0]["kind"] == "PickCardFromExaminedChoice"


def test_submit_pick_card_with_empty_queue_raises(synthetic_state):
    """submit_pick_card_decision on an empty queue raises ValueError."""
    assert synthetic_state.has_pending_decision() is False
    with pytest.raises(ValueError):
        synthetic_state.submit_pick_card_decision(42)


def test_submit_pick_card_on_surveil_head_raises(synthetic_state):
    """submit_pick_card_decision on a SurveilChoice head raises
    ValueError. Queue intact."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _surveil_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    assert synthetic_state.pending_decisions()[0]["kind"] == "SurveilChoice"

    with pytest.raises(ValueError):
        synthetic_state.submit_pick_card_decision(42)
    assert synthetic_state.has_pending_decision() is True
    assert synthetic_state.pending_decisions()[0]["kind"] == "SurveilChoice"


def test_auto_resolve_pick_top_picks_topmost(synthetic_state):
    """auto_resolve('pick_top') picks cards[0] (the topmost examined
    card) — matches Python's no-agent-seated fallback."""
    hand_before = synthetic_state.hand_sizes[0]
    graveyard_before = synthetic_state.graveyard_sizes[0]
    top_two = [obj["id"] for obj in synthetic_state.library_snapshot(0)[:2]]

    spell_obj_id = synthetic_state.register_and_inject_object(
        _look_top_n_dict(n=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    synthetic_state.auto_resolve_pending_decisions("pick_top")

    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.find_object_zone(top_two[0]) == ZONE_HAND
    assert synthetic_state.find_object_zone(top_two[1]) == ZONE_GRAVEYARD
    assert synthetic_state.hand_sizes[0] == hand_before + 1
    assert synthetic_state.graveyard_sizes[0] == graveyard_before + 2


def test_auto_resolve_default_picks_topmost_for_pick_card_variant(synthetic_state):
    """auto_resolve('default') delivers the same outcome as 'pick_top'
    for PickCardFromExaminedChoice."""
    top_two = [obj["id"] for obj in synthetic_state.library_snapshot(0)[:2]]

    spell_obj_id = synthetic_state.register_and_inject_object(
        _look_top_n_dict(n=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    synthetic_state.auto_resolve_pending_decisions("default")

    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.find_object_zone(top_two[0]) == ZONE_HAND
    assert synthetic_state.find_object_zone(top_two[1]) == ZONE_GRAVEYARD


def test_resolve_top_of_stack_auto_resolves_look_top_n(synthetic_state):
    """The non-pause resolve_top_of_stack auto-resolves the LookTopN.
    Topmost examined card lands in hand."""
    hand_before = synthetic_state.hand_sizes[0]
    top_id_before = synthetic_state.library_snapshot(0)[0]["id"]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _look_top_n_dict(n=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.find_object_zone(top_id_before) == ZONE_HAND
    assert synthetic_state.hand_sizes[0] == hand_before + 1


def test_look_top_n_zero_emits_empty_pending(synthetic_state):
    """LookTopN with n=0 emits a PendingDecision with empty cards.
    Auto-resolve drains it as an O(1) no-op."""
    library_before = synthetic_state.library_sizes[0]
    hand_before = synthetic_state.hand_sizes[0]

    spell_obj_id = synthetic_state.register_and_inject_object(
        _look_top_n_dict(n=0), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    pds = synthetic_state.pending_decisions()
    assert len(pds) == 1
    assert pds[0]["cards"] == []
    assert synthetic_state.library_sizes[0] == library_before

    synthetic_state.auto_resolve_pending_decisions("default")
    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.hand_sizes[0] == hand_before


def test_look_top_n_count_exceeds_library_clamps(engine):
    """LookTopN with n > library size pops every available card."""
    state = engine.make_synthetic_state(num_battlefield=0, num_hand=0, num_library=2)
    spell_obj_id = state.register_and_inject_object(
        _look_top_n_dict(n=5), 0, ZONE_BATTLEFIELD
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack_pause()

    pds = state.pending_decisions()
    assert len(pds) == 1
    assert len(pds[0]["cards"]) == 2
    assert state.library_sizes[0] == 0


def test_fingerprint_pick_card_pending_differs_from_empty(synthetic_state):
    """A state with a pending PickCardFromExaminedChoice fingerprints
    differently from a state with no pending decision."""
    fp_clean = synthetic_state.fingerprint()
    spell_obj_id = synthetic_state.register_and_inject_object(
        _look_top_n_dict(n=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    fp_pending = synthetic_state.fingerprint()
    assert fp_pending != fp_clean


def test_clone_isolates_pick_card_pending_decisions(synthetic_state):
    """clone_once() deep-clones the PickCardFromExaminedChoice. Resolving
    the clone leaves the source's queue intact (CoW canary)."""
    top_two = [obj["id"] for obj in synthetic_state.library_snapshot(0)[:2]]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _look_top_n_dict(n=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    clone = synthetic_state.clone_once()
    assert clone.has_pending_decision() is True
    assert clone.pending_decisions()[0]["kind"] == "PickCardFromExaminedChoice"

    clone.submit_pick_card_decision(top_two[0])
    assert clone.has_pending_decision() is False
    assert clone.find_object_zone(top_two[0]) == ZONE_HAND

    assert synthetic_state.has_pending_decision() is True
    assert synthetic_state.pending_decisions()[0]["cards"] == top_two


# =====================================================================
# Round-28 ChooseOneMode (fourth PendingDecision variant)
# =====================================================================
#
# Fourth variant on the multi-variant decision-callback substrate:
# ``PendingDecision::ChooseModeChoice`` — "Choose one — [mode_0];
# [mode_1]; ..." Pushed by ``Effect::ChooseOneMode``. First-slice
# scope: resolve-time pick only (no cast-time mode routing, no
# or_both). Dispatcher: ``submit_choose_mode_decision(chosen_idx)``.
# Auto-resolve: ``"default"`` / ``"choose_mode_0"`` pick ``modes[0]``.


def _choose_mode_draw_gain_dict():
    """A modal sorcery with two simple modes:
    mode 0: draw_cards 1
    mode 1: gain_life 3

    Both verifiable through standard accessors."""
    return {
        "name": "Test ChooseOneMode draw-or-gain",
        "card_types": ["Sorcery"],
        "mana_cost": {"U": 1},
        "effects": [
            {
                "kind": "choose_one_mode",
                "modes": [
                    {"kind": "draw_cards", "count": 1},
                    {"kind": "gain_life", "amount": 3},
                ],
            }
        ],
    }


def test_choose_one_mode_registers_with_two_modes(engine):
    """A ChooseOneMode sorcery registers cleanly and round-trips both
    modes through the printing readback."""
    reg = engine.Registry()
    pid = reg.register_printing(_choose_mode_draw_gain_dict())
    effects = reg.get_printing_effects(pid)
    assert len(effects) == 1
    eff = effects[0]
    assert eff["kind"] == "choose_one_mode"
    assert len(eff["modes"]) == 2
    assert eff["modes"][0]["kind"] == "draw_cards"
    assert eff["modes"][0]["count"] == 1
    assert eff["modes"][1]["kind"] == "gain_life"
    assert eff["modes"][1]["amount"] == 3


def test_choose_one_mode_missing_modes_field_raises(engine):
    """``choose_one_mode`` without ``modes`` is a hard ValueError."""
    reg = engine.Registry()
    with pytest.raises(ValueError):
        reg.register_printing(
            {
                "name": "Bad ChooseOneMode",
                "card_types": ["Sorcery"],
                "mana_cost": {"U": 1},
                "effects": [{"kind": "choose_one_mode"}],
            }
        )


def test_choose_one_mode_empty_modes_raises(engine):
    """``choose_one_mode`` with an empty ``modes`` list is rejected at
    parse time so the resolve arm always has at least one mode."""
    reg = engine.Registry()
    with pytest.raises(ValueError):
        reg.register_printing(
            {
                "name": "Empty ChooseOneMode",
                "card_types": ["Sorcery"],
                "mana_cost": {"U": 1},
                "effects": [{"kind": "choose_one_mode", "modes": []}],
            }
        )


def test_choose_one_mode_resolve_pushes_pending_choice(synthetic_state):
    """Resolving a ChooseOneMode sorcery pushes one ChooseModeChoice
    onto the queue carrying both modes; neither mode has fired yet."""
    hand_before = synthetic_state.hand_sizes[0]
    life_before = synthetic_state.get_life(0)
    spell_obj_id = synthetic_state.register_and_inject_object(
        _choose_mode_draw_gain_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    # Neither mode has fired.
    assert synthetic_state.hand_sizes[0] == hand_before
    assert synthetic_state.get_life(0) == life_before

    pds = synthetic_state.pending_decisions()
    assert len(pds) == 1
    pd = pds[0]
    assert pd["kind"] == "ChooseModeChoice"
    assert pd["source_obj_id"] == spell_obj_id
    assert pd["controller"] == 0
    assert len(pd["modes"]) == 2
    assert pd["modes"][0]["kind"] == "draw_cards"
    assert pd["modes"][1]["kind"] == "gain_life"


def test_submit_choose_mode_0_fires_draw(synthetic_state):
    """``submit_choose_mode_decision(0)`` applies the draw mode."""
    hand_before = synthetic_state.hand_sizes[0]
    life_before = synthetic_state.get_life(0)
    spell_obj_id = synthetic_state.register_and_inject_object(
        _choose_mode_draw_gain_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    synthetic_state.submit_choose_mode_decision(0)

    assert synthetic_state.has_pending_decision() is False
    # Hand: +1 from inner draw (cast +1 inject, -1 cast, +1 inner = +1).
    assert synthetic_state.hand_sizes[0] == hand_before + 1
    # Life unchanged.
    assert synthetic_state.get_life(0) == life_before


def test_submit_choose_mode_1_fires_gain_life(synthetic_state):
    """``submit_choose_mode_decision(1)`` applies the gain-life mode."""
    hand_before = synthetic_state.hand_sizes[0]
    life_before = synthetic_state.get_life(0)
    spell_obj_id = synthetic_state.register_and_inject_object(
        _choose_mode_draw_gain_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    synthetic_state.submit_choose_mode_decision(1)

    assert synthetic_state.has_pending_decision() is False
    # Hand unchanged by the gain-life mode (cast +1 inject, -1 cast = 0).
    assert synthetic_state.hand_sizes[0] == hand_before
    # Life: +3 from inner gain_life.
    assert synthetic_state.get_life(0) == life_before + 3


def test_submit_choose_mode_out_of_range_raises(synthetic_state):
    """Submitting an out-of-range mode index raises ValueError.
    Queue intact (transactional)."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _choose_mode_draw_gain_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    with pytest.raises(ValueError):
        synthetic_state.submit_choose_mode_decision(5)
    assert synthetic_state.has_pending_decision() is True
    assert synthetic_state.pending_decisions()[0]["kind"] == "ChooseModeChoice"


def test_submit_choose_mode_with_empty_queue_raises(synthetic_state):
    """submit_choose_mode_decision on an empty queue raises ValueError."""
    assert synthetic_state.has_pending_decision() is False
    with pytest.raises(ValueError):
        synthetic_state.submit_choose_mode_decision(0)


def test_submit_choose_mode_on_surveil_head_raises(synthetic_state):
    """submit_choose_mode_decision on a SurveilChoice head raises
    ValueError. Queue intact."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _surveil_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    assert synthetic_state.pending_decisions()[0]["kind"] == "SurveilChoice"

    with pytest.raises(ValueError):
        synthetic_state.submit_choose_mode_decision(0)
    assert synthetic_state.has_pending_decision() is True
    assert synthetic_state.pending_decisions()[0]["kind"] == "SurveilChoice"


def test_auto_resolve_choose_mode_0_picks_first_mode(synthetic_state):
    """``auto_resolve_pending_decisions("choose_mode_0")`` picks
    modes[0] — observable as +1 hand size from the inner draw."""
    hand_before = synthetic_state.hand_sizes[0]
    life_before = synthetic_state.get_life(0)
    spell_obj_id = synthetic_state.register_and_inject_object(
        _choose_mode_draw_gain_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    synthetic_state.auto_resolve_pending_decisions("choose_mode_0")

    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.hand_sizes[0] == hand_before + 1
    assert synthetic_state.get_life(0) == life_before


def test_auto_resolve_default_picks_first_mode_for_choose_one_mode(synthetic_state):
    """``auto_resolve_pending_decisions("default")`` picks modes[0]
    for a ChooseModeChoice — same observable outcome as
    ``"choose_mode_0"``."""
    hand_before = synthetic_state.hand_sizes[0]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _choose_mode_draw_gain_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    synthetic_state.auto_resolve_pending_decisions("default")

    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.hand_sizes[0] == hand_before + 1


def test_resolve_top_of_stack_auto_resolves_choose_one_mode(synthetic_state):
    """The non-pause ``resolve_top_of_stack`` auto-resolves the
    ChooseOneMode with its per-variant default (modes[0])."""
    hand_before = synthetic_state.hand_sizes[0]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _choose_mode_draw_gain_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.has_pending_decision() is False
    # Draw mode fired automatically.
    assert synthetic_state.hand_sizes[0] == hand_before + 1


def test_fingerprint_choose_mode_pending_differs_from_empty(synthetic_state):
    """A state with a pending ChooseModeChoice fingerprints differently
    from a state with no pending decision."""
    fp_clean = synthetic_state.fingerprint()
    spell_obj_id = synthetic_state.register_and_inject_object(
        _choose_mode_draw_gain_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    fp_pending = synthetic_state.fingerprint()
    assert fp_pending != fp_clean


def test_clone_isolates_choose_mode_pending_decisions(synthetic_state):
    """clone_once() deep-clones the ChooseModeChoice. Resolving the
    clone leaves the source's queue intact (CoW canary)."""
    hand_before = synthetic_state.hand_sizes[0]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _choose_mode_draw_gain_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    clone = synthetic_state.clone_once()
    assert clone.has_pending_decision() is True
    assert clone.pending_decisions()[0]["kind"] == "ChooseModeChoice"

    clone.submit_choose_mode_decision(0)
    assert clone.has_pending_decision() is False
    assert clone.hand_sizes[0] == hand_before + 1

    assert synthetic_state.has_pending_decision() is True
    # Source hand still pre-draw.
    assert synthetic_state.hand_sizes[0] == hand_before


# =====================================================================
# Round-28 IfYouDo (fifth PendingDecision variant)
# =====================================================================
#
# Fifth variant on the multi-variant decision-callback substrate:
# ``PendingDecision::IfYouDoChoice`` — "[do_action]; if you do,
# [then_action]." Pushed by ``Effect::IfYouDo``. First-slice scope:
# do_action assumed implicitly success-on-yes (IfYouDo(MayDo(X), Y)
# "looter" form). Dispatcher: ``submit_if_you_do_decision(yes)``.
# Auto-resolve: ``"default"`` / ``"if_you_do_yes"`` apply both; ``"if_you_do_no"`` skips both.


def _if_you_do_gain_draw_dict():
    """An IfYouDo sorcery: do_action = gain_life 2, then_action = draw 1.
    Both verifiable through standard accessors. Note: in real cards
    the do_action would typically be MayDo(...) — but for the first
    slice the IfYouDoChoice doesn't care about the do_action's
    internal shape, so we use simple primitives for test verifiability."""
    return {
        "name": "Test IfYouDo gain-then-draw",
        "card_types": ["Sorcery"],
        "mana_cost": {"W": 1},
        "effects": [
            {
                "kind": "if_you_do",
                "do_action": {"kind": "gain_life", "amount": 2},
                "then_action": {"kind": "draw_cards", "count": 1},
            }
        ],
    }


def test_if_you_do_registers_with_both_actions(engine):
    """IfYouDo registers cleanly and round-trips both nested effects."""
    reg = engine.Registry()
    pid = reg.register_printing(_if_you_do_gain_draw_dict())
    effects = reg.get_printing_effects(pid)
    assert len(effects) == 1
    eff = effects[0]
    assert eff["kind"] == "if_you_do"
    assert eff["do_action"]["kind"] == "gain_life"
    assert eff["do_action"]["amount"] == 2
    assert eff["then_action"]["kind"] == "draw_cards"
    assert eff["then_action"]["count"] == 1


def test_if_you_do_missing_do_action_raises(engine):
    """if_you_do without do_action is a hard ValueError."""
    reg = engine.Registry()
    with pytest.raises(ValueError):
        reg.register_printing(
            {
                "name": "Bad IfYouDo",
                "card_types": ["Sorcery"],
                "mana_cost": {"W": 1},
                "effects": [
                    {
                        "kind": "if_you_do",
                        "then_action": {"kind": "draw_cards", "count": 1},
                    }
                ],
            }
        )


def test_if_you_do_missing_then_action_raises(engine):
    """if_you_do without then_action is a hard ValueError."""
    reg = engine.Registry()
    with pytest.raises(ValueError):
        reg.register_printing(
            {
                "name": "Bad IfYouDo",
                "card_types": ["Sorcery"],
                "mana_cost": {"W": 1},
                "effects": [
                    {
                        "kind": "if_you_do",
                        "do_action": {"kind": "gain_life", "amount": 2},
                    }
                ],
            }
        )


def test_if_you_do_resolve_pushes_pending_choice(synthetic_state):
    """Resolving an IfYouDo sorcery pushes one IfYouDoChoice carrying
    both Effects; neither has fired yet."""
    hand_before = synthetic_state.hand_sizes[0]
    life_before = synthetic_state.get_life(0)
    spell_obj_id = synthetic_state.register_and_inject_object(
        _if_you_do_gain_draw_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    # Neither nested effect has fired yet.
    assert synthetic_state.hand_sizes[0] == hand_before
    assert synthetic_state.get_life(0) == life_before

    pds = synthetic_state.pending_decisions()
    assert len(pds) == 1
    pd = pds[0]
    assert pd["kind"] == "IfYouDoChoice"
    assert pd["source_obj_id"] == spell_obj_id
    assert pd["controller"] == 0
    assert pd["do_action"]["kind"] == "gain_life"
    assert pd["then_action"]["kind"] == "draw_cards"


def test_submit_if_you_do_yes_applies_both(synthetic_state):
    """submit_if_you_do_decision(True) applies both do_action and
    then_action in order."""
    hand_before = synthetic_state.hand_sizes[0]
    life_before = synthetic_state.get_life(0)
    spell_obj_id = synthetic_state.register_and_inject_object(
        _if_you_do_gain_draw_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    synthetic_state.submit_if_you_do_decision(True)

    assert synthetic_state.has_pending_decision() is False
    # do_action: +2 life. then_action: +1 hand.
    assert synthetic_state.get_life(0) == life_before + 2
    assert synthetic_state.hand_sizes[0] == hand_before + 1


def test_submit_if_you_do_no_skips_both(synthetic_state):
    """submit_if_you_do_decision(False) skips both actions."""
    hand_before = synthetic_state.hand_sizes[0]
    life_before = synthetic_state.get_life(0)
    spell_obj_id = synthetic_state.register_and_inject_object(
        _if_you_do_gain_draw_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    synthetic_state.submit_if_you_do_decision(False)

    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.get_life(0) == life_before
    assert synthetic_state.hand_sizes[0] == hand_before


def test_submit_if_you_do_with_empty_queue_raises(synthetic_state):
    """submit_if_you_do_decision on empty queue raises ValueError."""
    assert synthetic_state.has_pending_decision() is False
    with pytest.raises(ValueError):
        synthetic_state.submit_if_you_do_decision(True)


def test_submit_if_you_do_on_surveil_head_raises(synthetic_state):
    """submit_if_you_do_decision on a SurveilChoice head raises
    ValueError. Queue intact."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _surveil_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    assert synthetic_state.pending_decisions()[0]["kind"] == "SurveilChoice"

    with pytest.raises(ValueError):
        synthetic_state.submit_if_you_do_decision(True)
    assert synthetic_state.has_pending_decision() is True
    assert synthetic_state.pending_decisions()[0]["kind"] == "SurveilChoice"


def test_auto_resolve_if_you_do_yes_applies_both(synthetic_state):
    """auto_resolve_pending_decisions('if_you_do_yes') applies both
    nested actions."""
    hand_before = synthetic_state.hand_sizes[0]
    life_before = synthetic_state.get_life(0)
    spell_obj_id = synthetic_state.register_and_inject_object(
        _if_you_do_gain_draw_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    synthetic_state.auto_resolve_pending_decisions("if_you_do_yes")

    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.get_life(0) == life_before + 2
    assert synthetic_state.hand_sizes[0] == hand_before + 1


def test_auto_resolve_if_you_do_no_skips_both(synthetic_state):
    """auto_resolve_pending_decisions('if_you_do_no') drops both."""
    hand_before = synthetic_state.hand_sizes[0]
    life_before = synthetic_state.get_life(0)
    spell_obj_id = synthetic_state.register_and_inject_object(
        _if_you_do_gain_draw_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    synthetic_state.auto_resolve_pending_decisions("if_you_do_no")

    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.get_life(0) == life_before
    assert synthetic_state.hand_sizes[0] == hand_before


def test_auto_resolve_default_says_yes_to_if_you_do(synthetic_state):
    """auto_resolve_pending_decisions('default') applies both — mirrors
    Python's no-agent-seated default ('MayDo says yes, both fire')."""
    hand_before = synthetic_state.hand_sizes[0]
    life_before = synthetic_state.get_life(0)
    spell_obj_id = synthetic_state.register_and_inject_object(
        _if_you_do_gain_draw_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    synthetic_state.auto_resolve_pending_decisions("default")

    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.get_life(0) == life_before + 2
    assert synthetic_state.hand_sizes[0] == hand_before + 1


def test_resolve_top_of_stack_auto_resolves_if_you_do(synthetic_state):
    """Non-pause resolve_top_of_stack auto-resolves the IfYouDo with
    its per-variant default ('yes'). Both actions fire automatically."""
    hand_before = synthetic_state.hand_sizes[0]
    life_before = synthetic_state.get_life(0)
    spell_obj_id = synthetic_state.register_and_inject_object(
        _if_you_do_gain_draw_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.get_life(0) == life_before + 2
    assert synthetic_state.hand_sizes[0] == hand_before + 1


def test_fingerprint_if_you_do_pending_differs_from_empty(synthetic_state):
    """A state with a pending IfYouDoChoice fingerprints differently
    from a state with no pending decision."""
    fp_clean = synthetic_state.fingerprint()
    spell_obj_id = synthetic_state.register_and_inject_object(
        _if_you_do_gain_draw_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    fp_pending = synthetic_state.fingerprint()
    assert fp_pending != fp_clean


def test_clone_isolates_if_you_do_pending_decisions(synthetic_state):
    """clone_once() deep-clones the IfYouDoChoice. Resolving the
    clone leaves the source's queue intact (CoW canary)."""
    hand_before = synthetic_state.hand_sizes[0]
    life_before = synthetic_state.get_life(0)
    spell_obj_id = synthetic_state.register_and_inject_object(
        _if_you_do_gain_draw_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    clone = synthetic_state.clone_once()
    assert clone.has_pending_decision() is True
    assert clone.pending_decisions()[0]["kind"] == "IfYouDoChoice"

    clone.submit_if_you_do_decision(True)
    assert clone.has_pending_decision() is False
    assert clone.get_life(0) == life_before + 2
    assert clone.hand_sizes[0] == hand_before + 1

    # Source still pending, source state unchanged.
    assert synthetic_state.has_pending_decision() is True
    assert synthetic_state.get_life(0) == life_before
    assert synthetic_state.hand_sizes[0] == hand_before


# =====================================================================
# Round-28 ManifestDread (Effect::ManifestDread) + ManifestDreadChoice
# =====================================================================
# CR 701.55 — "look at the top two cards of your library, manifest one
# of them, then put the other into your graveyard." First-slice: count
# = 1 only; the manifested card lands on bf with its original printing
# visible (face-down semantics deferred — see SEARCH_LIMITATIONS.md).
#
# Dispatcher: ``submit_manifest_dread_decision(chosen_id)``.
# Auto-resolve: ``"default"`` / ``"manifest_top"`` pick the topmost
# popped card (cards[0]). Empty library drains as O(1) no-op; 1-card
# library manifests the lone card with no graveyard step.


def _manifest_dread_dict(count: int = 1):
    """A ManifestDread sorcery — Effect::ManifestDread dispatched on
    resolve."""
    return {
        "name": f"Test ManifestDread {count}",
        "card_types": ["Sorcery"],
        "mana_cost": {"B": 1, "U": 1},
        "effects": [{"kind": "manifest_dread", "count": count}],
    }


# --- register / round-trip ---


def test_manifest_dread_registers_with_count_field(engine):
    """A ManifestDread sorcery registers cleanly and round-trips its
    `count` through the printing readback."""
    reg = engine.Registry()
    pid = reg.register_printing(_manifest_dread_dict(count=1))
    effects = reg.get_printing_effects(pid)
    assert len(effects) == 1
    eff = effects[0]
    assert eff["kind"] == "manifest_dread"
    assert eff["count"] == 1


def test_manifest_dread_default_count_is_1(engine):
    """Omitting `count` defaults to 1 — Python's class default."""
    reg = engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test ManifestDread default",
            "card_types": ["Sorcery"],
            "mana_cost": {"B": 1},
            "effects": [{"kind": "manifest_dread"}],
        }
    )
    effects = reg.get_printing_effects(pid)
    assert effects[0]["count"] == 1


def test_manifest_dread_negative_count_raises(engine):
    """Negative `count` is a hard ValueError at register time."""
    reg = engine.Registry()
    with pytest.raises(ValueError):
        reg.register_printing(
            {
                "name": "Bad ManifestDread",
                "card_types": ["Sorcery"],
                "mana_cost": {"B": 1},
                "effects": [{"kind": "manifest_dread", "count": -1}],
            }
        )


def test_manifest_dread_missing_count_in_round_trip_after_explicit_pass(engine):
    """Explicit count=2 parses cleanly at register time (parse layer
    accepts any non-negative count for forward-compat). The resolve
    layer rejects count != 1 — that gate is tested separately."""
    reg = engine.Registry()
    pid = reg.register_printing(_manifest_dread_dict(count=2))
    effects = reg.get_printing_effects(pid)
    assert effects[0]["count"] == 2


# --- resolve happy path ---


def test_manifest_dread_resolve_pops_two_cards_and_pushes_pending_choice(
    synthetic_state,
):
    """Resolving ManifestDread pops 2 cards from library top and pushes
    one ManifestDreadChoice carrying those 2 cards. Hand, bf, and
    graveyard (beyond the source) are NOT yet touched by the inner
    routing."""
    library_before = synthetic_state.library_sizes[0]
    graveyard_before = synthetic_state.graveyard_sizes[0]
    hand_before = synthetic_state.hand_sizes[0]
    top_two = [obj["id"] for obj in synthetic_state.library_snapshot(0)[:2]]

    spell_obj_id = synthetic_state.register_and_inject_object(
        _manifest_dread_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    assert synthetic_state.library_sizes[0] == library_before - 2
    # Graveyard gained 1 (source). Examined cards NOT yet routed.
    assert synthetic_state.graveyard_sizes[0] == graveyard_before + 1
    assert synthetic_state.hand_sizes[0] == hand_before
    for cid in top_two:
        zone = synthetic_state.find_object_zone(cid)
        assert zone not in (ZONE_HAND, ZONE_LIBRARY, ZONE_GRAVEYARD, ZONE_BATTLEFIELD)

    pds = synthetic_state.pending_decisions()
    assert len(pds) == 1
    pd = pds[0]
    assert pd["kind"] == "ManifestDreadChoice"
    assert pd["source_obj_id"] == spell_obj_id
    assert pd["controller"] == 0
    assert pd["cards"] == top_two


def test_submit_manifest_dread_picks_topmost_routes_one_to_bf(synthetic_state):
    """Submitting cards[0] (topmost) routes it to bf and the second
    examined card to graveyard."""
    bf_before = synthetic_state.battlefield_sizes[0]
    graveyard_before = synthetic_state.graveyard_sizes[0]
    top_two = [obj["id"] for obj in synthetic_state.library_snapshot(0)[:2]]

    spell_obj_id = synthetic_state.register_and_inject_object(
        _manifest_dread_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    synthetic_state.submit_manifest_dread_decision(top_two[0])

    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.find_object_zone(top_two[0]) == ZONE_BATTLEFIELD
    assert synthetic_state.find_object_zone(top_two[1]) == ZONE_GRAVEYARD
    assert synthetic_state.battlefield_sizes[0] == bf_before + 1
    # graveyard_before + 1 (source) + 1 (unchosen card) = +2
    assert synthetic_state.graveyard_sizes[0] == graveyard_before + 2


def test_submit_manifest_dread_picks_non_topmost(synthetic_state):
    """Picking cards[1] routes it to bf and cards[0] to graveyard."""
    top_two = [obj["id"] for obj in synthetic_state.library_snapshot(0)[:2]]

    spell_obj_id = synthetic_state.register_and_inject_object(
        _manifest_dread_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    synthetic_state.submit_manifest_dread_decision(top_two[1])

    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.find_object_zone(top_two[1]) == ZONE_BATTLEFIELD
    assert synthetic_state.find_object_zone(top_two[0]) == ZONE_GRAVEYARD


def test_submit_manifest_dread_unknown_id_raises(synthetic_state):
    """An id not in the examined Vec raises ValueError. Queue intact."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _manifest_dread_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    with pytest.raises(ValueError):
        synthetic_state.submit_manifest_dread_decision(999999)
    assert synthetic_state.has_pending_decision() is True
    assert synthetic_state.pending_decisions()[0]["kind"] == "ManifestDreadChoice"


def test_submit_manifest_dread_with_empty_queue_raises(synthetic_state):
    """submit_manifest_dread_decision on an empty queue raises ValueError."""
    assert synthetic_state.has_pending_decision() is False
    with pytest.raises(ValueError):
        synthetic_state.submit_manifest_dread_decision(42)


def test_submit_manifest_dread_on_surveil_head_raises(synthetic_state):
    """submit_manifest_dread_decision on a SurveilChoice head raises
    ValueError. Queue intact."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _surveil_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    assert synthetic_state.pending_decisions()[0]["kind"] == "SurveilChoice"

    with pytest.raises(ValueError):
        synthetic_state.submit_manifest_dread_decision(42)
    assert synthetic_state.has_pending_decision() is True
    assert synthetic_state.pending_decisions()[0]["kind"] == "SurveilChoice"


# --- auto-resolve ---


def test_auto_resolve_manifest_top_picks_topmost(synthetic_state):
    """auto_resolve('manifest_top') picks cards[0] (the topmost examined
    card) — matches Python's no-agent-seated fallback."""
    bf_before = synthetic_state.battlefield_sizes[0]
    graveyard_before = synthetic_state.graveyard_sizes[0]
    top_two = [obj["id"] for obj in synthetic_state.library_snapshot(0)[:2]]

    spell_obj_id = synthetic_state.register_and_inject_object(
        _manifest_dread_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    synthetic_state.auto_resolve_pending_decisions("manifest_top")

    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.find_object_zone(top_two[0]) == ZONE_BATTLEFIELD
    assert synthetic_state.find_object_zone(top_two[1]) == ZONE_GRAVEYARD
    assert synthetic_state.battlefield_sizes[0] == bf_before + 1
    assert synthetic_state.graveyard_sizes[0] == graveyard_before + 2


def test_auto_resolve_default_picks_topmost_for_manifest_dread_variant(
    synthetic_state,
):
    """auto_resolve('default') delivers the same outcome as
    'manifest_top' for ManifestDreadChoice."""
    top_two = [obj["id"] for obj in synthetic_state.library_snapshot(0)[:2]]

    spell_obj_id = synthetic_state.register_and_inject_object(
        _manifest_dread_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    synthetic_state.auto_resolve_pending_decisions("default")

    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.find_object_zone(top_two[0]) == ZONE_BATTLEFIELD
    assert synthetic_state.find_object_zone(top_two[1]) == ZONE_GRAVEYARD


def test_resolve_top_of_stack_auto_resolves_manifest_dread(synthetic_state):
    """The non-pause resolve_top_of_stack auto-resolves the ManifestDread.
    Topmost examined card lands on bf."""
    bf_before = synthetic_state.battlefield_sizes[0]
    top_id_before = synthetic_state.library_snapshot(0)[0]["id"]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _manifest_dread_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.find_object_zone(top_id_before) == ZONE_BATTLEFIELD
    assert synthetic_state.battlefield_sizes[0] == bf_before + 1


# --- ETB-state reset on manifested card ---


def test_manifest_dread_manifested_card_has_etb_state(synthetic_state):
    """The manifested card lands on bf with the standard ETB state
    reset (summoning_sick=true, tapped=false, controller = the
    manifest-dread controller)."""
    top_two = [obj["id"] for obj in synthetic_state.library_snapshot(0)[:2]]
    top_id = top_two[0]

    spell_obj_id = synthetic_state.register_and_inject_object(
        _manifest_dread_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    synthetic_state.submit_manifest_dread_decision(top_id)

    # Find the manifested card in the global battlefield snapshot.
    bf = synthetic_state.battlefield_snapshot()
    manifested = next((o for o in bf if o["id"] == top_id), None)
    assert manifested is not None
    assert manifested["tapped"] is False
    assert manifested["summoning_sick"] is True
    assert manifested["damage"] == 0
    assert manifested["counters"] == 0
    assert manifested["controller_id"] == 0


# --- partial-library edges ---


def test_manifest_dread_empty_library_emits_empty_pending(engine):
    """ManifestDread on an empty library emits a PendingDecision with
    empty cards. Auto-resolve drains as O(1) no-op."""
    state = engine.make_synthetic_state(num_battlefield=0, num_hand=0, num_library=0)
    bf_before = state.battlefield_sizes[0]
    spell_obj_id = state.register_and_inject_object(
        _manifest_dread_dict(count=1), 0, ZONE_BATTLEFIELD
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack_pause()

    pds = state.pending_decisions()
    assert len(pds) == 1
    assert pds[0]["kind"] == "ManifestDreadChoice"
    assert pds[0]["cards"] == []

    state.auto_resolve_pending_decisions("default")
    assert state.has_pending_decision() is False
    # No card was manifested (library was empty).
    assert state.battlefield_sizes[0] == bf_before


def test_manifest_dread_one_card_library_manifests_lone_card(engine):
    """ManifestDread on a 1-card library emits a PendingDecision with
    cards=[lone_top]. Auto-resolve manifests it; no graveyard step."""
    state = engine.make_synthetic_state(num_battlefield=0, num_hand=0, num_library=1)
    bf_before = state.battlefield_sizes[0]
    graveyard_before = state.graveyard_sizes[0]
    lone_id = state.library_snapshot(0)[0]["id"]

    spell_obj_id = state.register_and_inject_object(
        _manifest_dread_dict(count=1), 0, ZONE_BATTLEFIELD
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack_pause()

    pds = state.pending_decisions()
    assert len(pds) == 1
    assert pds[0]["cards"] == [lone_id]

    state.auto_resolve_pending_decisions("default")
    assert state.has_pending_decision() is False
    assert state.find_object_zone(lone_id) == ZONE_BATTLEFIELD
    assert state.battlefield_sizes[0] == bf_before + 1
    # Only the source went to graveyard via stack-resolution; no
    # second examined card to mill.
    assert state.graveyard_sizes[0] == graveyard_before + 1
    assert state.library_sizes[0] == 0


def test_manifest_dread_one_card_library_submit_picks_lone(engine):
    """Manual submit on a 1-card-library ManifestDread routes the lone
    card to bf."""
    state = engine.make_synthetic_state(num_battlefield=0, num_hand=0, num_library=1)
    lone_id = state.library_snapshot(0)[0]["id"]

    spell_obj_id = state.register_and_inject_object(
        _manifest_dread_dict(count=1), 0, ZONE_BATTLEFIELD
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack_pause()

    state.submit_manifest_dread_decision(lone_id)
    assert state.has_pending_decision() is False
    assert state.find_object_zone(lone_id) == ZONE_BATTLEFIELD


# --- count > 1 deferred (first-slice scope gate) ---


def test_manifest_dread_count_two_raises_at_resolve(synthetic_state):
    """count != 1 is deferred — resolve raises with a clear message
    pointing at SEARCH_LIMITATIONS.md. The parse layer accepts count=2
    so this gate fires only at resolve time."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _manifest_dread_dict(count=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    with pytest.raises(ValueError):
        synthetic_state.resolve_top_of_stack_pause()


def test_manifest_dread_count_zero_raises_at_resolve(synthetic_state):
    """count = 0 is also deferred — first-slice supports count = 1
    only."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _manifest_dread_dict(count=0), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    with pytest.raises(ValueError):
        synthetic_state.resolve_top_of_stack_pause()


# --- fingerprint + clone ---


def test_fingerprint_manifest_dread_pending_differs_from_empty(synthetic_state):
    """A state with a pending ManifestDreadChoice fingerprints
    differently from a state with no pending decision."""
    fp_clean = synthetic_state.fingerprint()
    spell_obj_id = synthetic_state.register_and_inject_object(
        _manifest_dread_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    fp_pending = synthetic_state.fingerprint()
    assert fp_pending != fp_clean


def test_clone_isolates_manifest_dread_pending_decisions(synthetic_state):
    """clone_once() deep-clones the ManifestDreadChoice. Resolving
    the clone leaves the source's queue intact (CoW canary)."""
    top_two = [obj["id"] for obj in synthetic_state.library_snapshot(0)[:2]]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _manifest_dread_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    clone = synthetic_state.clone_once()
    assert clone.has_pending_decision() is True
    assert clone.pending_decisions()[0]["kind"] == "ManifestDreadChoice"

    clone.submit_manifest_dread_decision(top_two[0])
    assert clone.has_pending_decision() is False
    assert clone.find_object_zone(top_two[0]) == ZONE_BATTLEFIELD

    assert synthetic_state.has_pending_decision() is True
    assert synthetic_state.pending_decisions()[0]["cards"] == top_two


# =====================================================================
# Round-28 LookAtTopNRevealOrCounter (Effect::LookAtTopNRevealOrCounter)
# + LookAtTopNRevealOrCounterChoice
# =====================================================================
# Python's `LookAtTopNRevealOrCounter(n, filter_name, max_power,
# counter_on_miss)` (Pulsar-Squadron-Ace + Living-Phone family, freq 2
# in EoE pool). Looks at top N cards; controller MAY reveal one
# matching the filter and put it in hand; the rest go to library
# bottom in popped order. On miss, optionally put a +1/+1 counter on
# source.
#
# Dispatcher: ``submit_look_at_top_n_decision(reveal: bool,
# chosen_id: int | None)``.
# Auto-resolve: ``"default"`` / ``"reveal_no"`` mirror Python's
# no-agent-seated path. ``"reveal_yes"`` picks the first examined
# card matching the filter (deterministic convenience).


def _living_phone_dict():
    """A LookAtTopNRevealOrCounter sorcery — Living-Phone shape (n=4,
    filter='creature', max_power=2, counter_on_miss=False)."""
    return {
        "name": "Test Living Phone",
        "card_types": ["Sorcery"],
        "mana_cost": {"U": 1},
        "effects": [
            {
                "kind": "look_at_top_n_reveal_or_counter",
                "n": 4,
                "filter_name": "creature",
                "max_power": 2,
                "counter_on_miss": False,
            }
        ],
    }


def _pulsar_squadron_ace_dict():
    """A Pulsar-Squadron-Ace-shape creature (n=5, filter='spacecraft',
    max_power=0, counter_on_miss=True). Exercised here by pushing the
    bf-side creature obj as the stack item — the resolve resolves the
    creature's effect as if from bf."""
    return {
        "name": "Test Pulsar Ace Body",
        "card_types": ["Creature"],
        "mana_cost": {"W": 1},
        "power": 2,
        "toughness": 2,
        "effects": [
            {
                "kind": "look_at_top_n_reveal_or_counter",
                "n": 5,
                "filter_name": "spacecraft",
                "max_power": 0,
                "counter_on_miss": True,
            }
        ],
    }


def _creature_printing_dict(name: str, power: int = 1):
    return {
        "name": name,
        "card_types": ["Creature"],
        "mana_cost": {"G": 1},
        "power": power,
        "toughness": 1,
        "effects": [],
    }


# --- register / round-trip ---


def test_look_at_top_n_registers_with_all_fields(engine):
    reg = engine.Registry()
    pid = reg.register_printing(_living_phone_dict())
    effects = reg.get_printing_effects(pid)
    assert len(effects) == 1
    eff = effects[0]
    assert eff["kind"] == "look_at_top_n_reveal_or_counter"
    assert eff["n"] == 4
    assert eff["filter_name"] == "creature"
    assert eff["max_power"] == 2
    assert eff["counter_on_miss"] is False


def test_look_at_top_n_filter_defaults(engine):
    reg = engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test default",
            "card_types": ["Sorcery"],
            "mana_cost": {"W": 1},
            "effects": [{"kind": "look_at_top_n_reveal_or_counter", "n": 5}],
        }
    )
    eff = reg.get_printing_effects(pid)[0]
    assert eff["filter_name"] == "spacecraft"
    assert eff["max_power"] == 0
    assert eff["counter_on_miss"] is True


def test_look_at_top_n_missing_n_raises(engine):
    reg = engine.Registry()
    with pytest.raises(ValueError):
        reg.register_printing(
            {
                "name": "Bad missing n",
                "card_types": ["Sorcery"],
                "mana_cost": {"W": 1},
                "effects": [{"kind": "look_at_top_n_reveal_or_counter"}],
            }
        )


def test_look_at_top_n_negative_n_raises(engine):
    reg = engine.Registry()
    with pytest.raises(ValueError):
        reg.register_printing(
            {
                "name": "Bad negative n",
                "card_types": ["Sorcery"],
                "mana_cost": {"W": 1},
                "effects": [
                    {"kind": "look_at_top_n_reveal_or_counter", "n": -3}
                ],
            }
        )


def test_look_at_top_n_unknown_filter_raises(engine):
    reg = engine.Registry()
    with pytest.raises(ValueError):
        reg.register_printing(
            {
                "name": "Bad filter",
                "card_types": ["Sorcery"],
                "mana_cost": {"W": 1},
                "effects": [
                    {
                        "kind": "look_at_top_n_reveal_or_counter",
                        "n": 5,
                        "filter_name": "land",
                    }
                ],
            }
        )


def test_look_at_top_n_negative_max_power_raises(engine):
    reg = engine.Registry()
    with pytest.raises(ValueError):
        reg.register_printing(
            {
                "name": "Bad max_power",
                "card_types": ["Sorcery"],
                "mana_cost": {"W": 1},
                "effects": [
                    {
                        "kind": "look_at_top_n_reveal_or_counter",
                        "n": 5,
                        "max_power": -1,
                    }
                ],
            }
        )


# --- resolve happy path ---


def test_look_at_top_n_resolve_pops_n_cards_and_pushes_pending(synthetic_state):
    library_before = synthetic_state.library_sizes[0]
    n = 4
    # Post-CE3: lib[0] = top, lib[..n] = top-n in top-first order.
    top_n = [obj["id"] for obj in synthetic_state.library_snapshot(0)[:n]]

    spell_obj_id = synthetic_state.register_and_inject_object(
        _living_phone_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    assert synthetic_state.library_sizes[0] == library_before - n
    pds = synthetic_state.pending_decisions()
    assert len(pds) == 1
    pd = pds[0]
    assert pd["kind"] == "LookAtTopNRevealOrCounterChoice"
    assert pd["source_obj_id"] == spell_obj_id
    assert pd["controller"] == 0
    assert pd["cards"] == top_n
    assert pd["filter_name"] == "creature"
    assert pd["max_power"] == 2
    assert pd["counter_on_miss"] is False


def test_submit_reveal_no_routes_all_to_library_bottom(synthetic_state):
    library_before = synthetic_state.library_sizes[0]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _living_phone_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    synthetic_state.submit_look_at_top_n_decision(False, None)
    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.library_sizes[0] == library_before


def test_submit_reveal_no_counter_on_miss_fires_when_source_on_bf(engine):
    state = engine.make_synthetic_state(num_battlefield=0, num_hand=0, num_library=5)
    source_id = state.register_and_inject_object(
        _pulsar_squadron_ace_dict(), 0, ZONE_BATTLEFIELD
    )
    counters_before = state.get_counters(source_id)
    state.push_to_stack(source_id, 0)
    state.resolve_top_of_stack_pause()
    state.submit_look_at_top_n_decision(False, None)

    counters_after = state.get_counters(source_id)
    assert counters_after == counters_before + 1
    assert state.find_object_zone(source_id) == ZONE_BATTLEFIELD


def test_submit_reveal_no_counter_on_miss_skipped_when_disabled(engine):
    state = engine.make_synthetic_state(num_battlefield=0, num_hand=0, num_library=5)
    source_id = state.register_and_inject_object(
        _living_phone_dict(), 0, ZONE_BATTLEFIELD
    )
    counters_before = state.get_counters(source_id)
    state.push_to_stack(source_id, 0)
    state.resolve_top_of_stack_pause()
    state.submit_look_at_top_n_decision(False, None)
    assert state.get_counters(source_id) == counters_before


def test_submit_reveal_no_counter_skipped_when_source_off_bf(synthetic_state):
    spell_obj_id = synthetic_state.register_and_inject_object(
        _pulsar_squadron_ace_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    synthetic_state.submit_look_at_top_n_decision(False, None)
    # No exception; source moved to graveyard via stack resolution.


def test_submit_reveal_yes_routes_chosen_to_hand_rest_to_bottom(synthetic_state):
    creature_id = synthetic_state.register_and_inject_object(
        _creature_printing_dict("Test Creature", power=1), 0, ZONE_LIBRARY,
    )
    hand_before = synthetic_state.hand_sizes[0]
    library_before = synthetic_state.library_sizes[0]

    spell_obj_id = synthetic_state.register_and_inject_object(
        _living_phone_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    pd = synthetic_state.pending_decisions()[0]
    assert creature_id in pd["cards"]

    synthetic_state.submit_look_at_top_n_decision(True, creature_id)

    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.find_object_zone(creature_id) == ZONE_HAND
    assert synthetic_state.hand_sizes[0] == hand_before + 1
    assert synthetic_state.library_sizes[0] == library_before - 1


def test_submit_reveal_yes_rejects_unfiltered_card(synthetic_state):
    spell_obj_id = synthetic_state.register_and_inject_object(
        _living_phone_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    pd = synthetic_state.pending_decisions()[0]
    non_matching_id = pd["cards"][0]
    with pytest.raises(ValueError):
        synthetic_state.submit_look_at_top_n_decision(True, non_matching_id)
    assert synthetic_state.has_pending_decision() is True


def test_submit_reveal_yes_rejects_creature_with_too_high_power(synthetic_state):
    big_creature_id = synthetic_state.register_and_inject_object(
        _creature_printing_dict("Big Creature", power=3), 0, ZONE_LIBRARY,
    )
    spell_obj_id = synthetic_state.register_and_inject_object(
        _living_phone_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    with pytest.raises(ValueError):
        synthetic_state.submit_look_at_top_n_decision(True, big_creature_id)


def test_submit_reveal_yes_with_no_chosen_id_raises(synthetic_state):
    spell_obj_id = synthetic_state.register_and_inject_object(
        _living_phone_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    with pytest.raises(ValueError):
        synthetic_state.submit_look_at_top_n_decision(True, None)


def test_submit_unknown_chosen_id_raises(synthetic_state):
    spell_obj_id = synthetic_state.register_and_inject_object(
        _living_phone_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    with pytest.raises(ValueError):
        synthetic_state.submit_look_at_top_n_decision(True, 999999)
    assert synthetic_state.has_pending_decision() is True


def test_submit_look_at_top_n_with_empty_queue_raises(synthetic_state):
    assert synthetic_state.has_pending_decision() is False
    with pytest.raises(ValueError):
        synthetic_state.submit_look_at_top_n_decision(False, None)


def test_submit_look_at_top_n_on_surveil_head_raises(synthetic_state):
    spell_obj_id = synthetic_state.register_and_inject_object(
        _surveil_dict(count=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    assert synthetic_state.pending_decisions()[0]["kind"] == "SurveilChoice"
    with pytest.raises(ValueError):
        synthetic_state.submit_look_at_top_n_decision(False, None)
    assert synthetic_state.pending_decisions()[0]["kind"] == "SurveilChoice"


def test_submit_may_do_on_look_at_top_n_head_raises(synthetic_state):
    spell_obj_id = synthetic_state.register_and_inject_object(
        _living_phone_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    with pytest.raises(ValueError):
        synthetic_state.submit_may_do_decision(True)
    assert synthetic_state.pending_decisions()[0]["kind"] == (
        "LookAtTopNRevealOrCounterChoice"
    )


# --- auto-resolve ---


def test_auto_resolve_default_routes_all_to_library_bottom(synthetic_state):
    library_before = synthetic_state.library_sizes[0]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _living_phone_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    synthetic_state.auto_resolve_pending_decisions("default")
    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.library_sizes[0] == library_before


def test_auto_resolve_reveal_no_matches_default(synthetic_state):
    library_before = synthetic_state.library_sizes[0]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _living_phone_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    synthetic_state.auto_resolve_pending_decisions("reveal_no")
    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.library_sizes[0] == library_before


def test_auto_resolve_reveal_yes_picks_matching_creature(synthetic_state):
    creature_id = synthetic_state.register_and_inject_object(
        _creature_printing_dict("Test Pick", power=1), 0, ZONE_LIBRARY,
    )
    hand_before = synthetic_state.hand_sizes[0]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _living_phone_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    synthetic_state.auto_resolve_pending_decisions("reveal_yes")
    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.find_object_zone(creature_id) == ZONE_HAND
    assert synthetic_state.hand_sizes[0] == hand_before + 1


def test_auto_resolve_reveal_yes_falls_through_when_no_match(engine):
    state = engine.make_synthetic_state(num_battlefield=0, num_hand=0, num_library=5)
    source_id = state.register_and_inject_object(
        _pulsar_squadron_ace_dict(), 0, ZONE_BATTLEFIELD
    )
    counters_before = state.get_counters(source_id)
    state.push_to_stack(source_id, 0)
    state.resolve_top_of_stack_pause()
    state.auto_resolve_pending_decisions("reveal_yes")
    assert state.has_pending_decision() is False
    assert state.get_counters(source_id) == counters_before + 1


def test_resolve_top_of_stack_auto_resolves_look_at_top_n(synthetic_state):
    library_before = synthetic_state.library_sizes[0]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _living_phone_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.library_sizes[0] == library_before


# --- partial-library edges ---


def test_look_at_top_n_empty_library_emits_empty_pending(engine):
    state = engine.make_synthetic_state(num_battlefield=0, num_hand=0, num_library=0)
    source_id = state.register_and_inject_object(
        _pulsar_squadron_ace_dict(), 0, ZONE_BATTLEFIELD
    )
    counters_before = state.get_counters(source_id)
    state.push_to_stack(source_id, 0)
    state.resolve_top_of_stack_pause()
    pds = state.pending_decisions()
    assert len(pds) == 1
    assert pds[0]["kind"] == "LookAtTopNRevealOrCounterChoice"
    assert pds[0]["cards"] == []
    state.auto_resolve_pending_decisions("default")
    assert state.has_pending_decision() is False
    assert state.get_counters(source_id) == counters_before + 1


def test_look_at_top_n_library_smaller_than_n_clamps(engine):
    state = engine.make_synthetic_state(num_battlefield=0, num_hand=0, num_library=2)
    library_before = state.library_sizes[0]
    spell_obj_id = state.register_and_inject_object(
        _living_phone_dict(), 0, ZONE_HAND
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack_pause()
    pds = state.pending_decisions()
    assert len(pds) == 1
    assert len(pds[0]["cards"]) == 2
    state.auto_resolve_pending_decisions("default")
    assert state.has_pending_decision() is False
    assert state.library_sizes[0] == library_before


# --- fingerprint + clone ---


def test_fingerprint_look_at_top_n_pending_differs_from_empty(synthetic_state):
    fp_clean = synthetic_state.fingerprint()
    spell_obj_id = synthetic_state.register_and_inject_object(
        _living_phone_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    fp_pending = synthetic_state.fingerprint()
    assert fp_pending != fp_clean


def test_fingerprint_look_at_top_n_diverges_across_filter_scope(engine):
    state_a = engine.make_synthetic_state(num_battlefield=0, num_hand=0, num_library=5)
    state_b = engine.make_synthetic_state(num_battlefield=0, num_hand=0, num_library=5)
    spell_a = state_a.register_and_inject_object(
        _living_phone_dict(), 0, ZONE_HAND
    )
    spell_b = state_b.register_and_inject_object(
        _pulsar_squadron_ace_dict(), 0, ZONE_HAND
    )
    state_a.push_to_stack(spell_a, 0)
    state_b.push_to_stack(spell_b, 0)
    state_a.resolve_top_of_stack_pause()
    state_b.resolve_top_of_stack_pause()
    assert state_a.fingerprint() != state_b.fingerprint()


def test_clone_isolates_look_at_top_n_pending_decisions(synthetic_state):
    library_before = synthetic_state.library_sizes[0]
    spell_obj_id = synthetic_state.register_and_inject_object(
        _living_phone_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    src_pd_cards = synthetic_state.pending_decisions()[0]["cards"]

    clone = synthetic_state.clone_once()
    assert clone.has_pending_decision() is True
    assert clone.pending_decisions()[0]["kind"] == (
        "LookAtTopNRevealOrCounterChoice"
    )

    clone.submit_look_at_top_n_decision(False, None)
    assert clone.has_pending_decision() is False
    assert clone.library_sizes[0] == library_before

    assert synthetic_state.has_pending_decision() is True
    assert synthetic_state.pending_decisions()[0]["cards"] == src_pd_cards


# -----------------------------------------------------------------
# Round-29 ManifestDreadThenAttachSelf (Conductive-Machete family).
# -----------------------------------------------------------------
# Composition: ``Effect::ManifestDreadThenAttachSelf`` reuses the
# ``PendingDecision::ManifestDreadChoice`` substrate but flips a new
# ``then_attach_to_source`` flag to True. The submit dispatcher reads
# the flag and, after the standard manifest routing, stamps
# ``source.attached_to = manifested_id`` (silent partial if the source
# has LTB'd in the decision window).


def _manifest_dread_then_attach_self_dict(count: int = 1):
    """A Conductive-Machete-shape Equipment ETB: an Artifact whose ETB
    fires ``Effect::ManifestDreadThenAttachSelf``. Modeled as an
    Artifact (the Rust registry doesn't track Equipment subtype gating;
    same shape as ``_atomic_microsizer_dict`` in test_zones.py)."""
    return {
        "name": f"Test ManifestDreadThenAttachSelf {count}",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 2},
        "etb_effects": [
            {"kind": "manifest_dread_then_attach_self", "count": count},
        ],
    }


# --- register + round-trip ---


def test_manifest_dread_then_attach_self_registers_round_trip(engine):
    """Parsing + re-serialization preserves the count field."""
    reg = engine.Registry()
    pid = reg.register_printing(_manifest_dread_then_attach_self_dict(count=1))
    etbs = reg.get_printing_etb_effects(pid)
    assert len(etbs) == 1
    assert etbs[0]["kind"] == "manifest_dread_then_attach_self"
    assert etbs[0]["count"] == 1


def test_manifest_dread_then_attach_self_default_count_is_1(engine):
    """An omitted count field defaults to 1 (mirrors the ManifestDread
    arm's default)."""
    reg = engine.Registry()
    pid = reg.register_printing({
        "name": "Default-count Test",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 2},
        "etb_effects": [{"kind": "manifest_dread_then_attach_self"}],
    })
    etbs = reg.get_printing_etb_effects(pid)
    assert etbs[0]["count"] == 1


def test_manifest_dread_then_attach_self_negative_count_rejected(engine):
    """A negative count value raises at parse time (mirrors
    ManifestDread)."""
    reg = engine.Registry()
    with pytest.raises(ValueError):
        reg.register_printing({
            "name": "Bad ManifestDreadThenAttachSelf",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 2},
            "etb_effects": [
                {"kind": "manifest_dread_then_attach_self", "count": -1},
            ],
        })


# --- happy path: manifest-then-attach chain ---


def test_manifest_dread_then_attach_self_happy_path_stamps_attached_to(synthetic_state):
    """Cast the Equipment from hand. Its ETB resolves:
    (1) Equipment lands on bf (artifact ETB).
    (2) Top 2 of p0 library popped into ManifestDreadChoice.
    (3) Submit the topmost: it lands on bf as manifested creature.
    (4) source.attached_to is stamped to the manifested card's id.
    """
    top_two = [obj["id"] for obj in synthetic_state.library_snapshot(0)[:2]]

    spell_id = synthetic_state.register_and_inject_object(
        _manifest_dread_then_attach_self_dict(count=1), 0, 0  # ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    # Equipment should be on bf already (artifact ETB lands first).
    assert synthetic_state.find_object_zone(spell_id) == ZONE_BATTLEFIELD
    # Pending decision is the ManifestDreadChoice with attach flag.
    pds = synthetic_state.pending_decisions()
    assert len(pds) == 1
    pd = pds[0]
    assert pd["kind"] == "ManifestDreadChoice"
    assert pd["source_obj_id"] == spell_id
    assert pd["then_attach_to_source"] is True
    assert pd["cards"] == top_two

    # Submit topmost → manifested card on bf, source attached to it.
    chosen_id = top_two[0]
    synthetic_state.submit_manifest_dread_decision(chosen_id)
    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.find_object_zone(chosen_id) == ZONE_BATTLEFIELD
    assert synthetic_state.find_object_zone(top_two[1]) == ZONE_GRAVEYARD
    # Source (Equipment) is now attached to the manifested creature.
    bf = synthetic_state.battlefield_snapshot()
    equipment = next(d for d in bf if d["id"] == spell_id)
    assert equipment["attached_to"] == chosen_id


def test_manifest_dread_then_attach_self_picks_non_topmost(synthetic_state):
    """Submitting cards[1] (non-topmost) routes it to bf; the source
    Equipment attaches to that picked card (not the topmost)."""
    top_two = [obj["id"] for obj in synthetic_state.library_snapshot(0)[:2]]

    spell_id = synthetic_state.register_and_inject_object(
        _manifest_dread_then_attach_self_dict(count=1), 0, 0
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    chosen_id = top_two[1]
    synthetic_state.submit_manifest_dread_decision(chosen_id)
    assert synthetic_state.find_object_zone(chosen_id) == ZONE_BATTLEFIELD
    assert synthetic_state.find_object_zone(top_two[0]) == ZONE_GRAVEYARD
    bf = synthetic_state.battlefield_snapshot()
    equipment = next(d for d in bf if d["id"] == spell_id)
    assert equipment["attached_to"] == chosen_id


def test_manifest_dread_then_attach_self_auto_resolve_picks_topmost(synthetic_state):
    """auto_resolve('default') picks cards[0] AND runs the attach."""
    top_two = [obj["id"] for obj in synthetic_state.library_snapshot(0)[:2]]

    spell_id = synthetic_state.register_and_inject_object(
        _manifest_dread_then_attach_self_dict(count=1), 0, 0
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    synthetic_state.auto_resolve_pending_decisions("default")

    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.find_object_zone(top_two[0]) == ZONE_BATTLEFIELD
    bf = synthetic_state.battlefield_snapshot()
    equipment = next(d for d in bf if d["id"] == spell_id)
    assert equipment["attached_to"] == top_two[0]


def test_manifest_dread_then_attach_self_full_resolve_auto(synthetic_state):
    """The non-pause resolve_top_of_stack auto-resolves and attaches."""
    top_id_before = synthetic_state.library_snapshot(0)[0]["id"]
    spell_id = synthetic_state.register_and_inject_object(
        _manifest_dread_then_attach_self_dict(count=1), 0, 0
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.has_pending_decision() is False
    assert synthetic_state.find_object_zone(top_id_before) == ZONE_BATTLEFIELD
    bf = synthetic_state.battlefield_snapshot()
    equipment = next(d for d in bf if d["id"] == spell_id)
    assert equipment["attached_to"] == top_id_before


# --- source LTB during decision window: silent partial ---


def test_manifest_dread_then_attach_self_source_ltb_silent_partial(synthetic_state):
    """If the source Equipment leaves the battlefield between the
    resolve-push and the submit (e.g. destroyed by a separate effect),
    the manifest step still completes but the attach step is silently
    skipped — no panic, no error."""
    top_two = [obj["id"] for obj in synthetic_state.library_snapshot(0)[:2]]

    spell_id = synthetic_state.register_and_inject_object(
        _manifest_dread_then_attach_self_dict(count=1), 0, 0
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    # Confirm the source is on bf and pending decision exists.
    assert synthetic_state.find_object_zone(spell_id) == ZONE_BATTLEFIELD
    assert synthetic_state.has_pending_decision() is True

    # Simulate LTB by moving the Equipment off the battlefield via
    # the test-only ``move_object`` primitive. This bypasses SBA /
    # destroy spells (which target by predicate filter — destroy_
    # target_artifact picks the first artifact in iteration order
    # and may not pick our injected Equipment without controller
    # coordination). The direct zone-move primitive is the most
    # surgical way to model "source has LTB'd during the decision
    # window" without setting up an entire destroy chain.
    ok = synthetic_state.move_object(spell_id, ZONE_GRAVEYARD, 0)
    assert ok is True
    assert synthetic_state.find_object_zone(spell_id) == ZONE_GRAVEYARD

    # Now submit the manifest decision (pending was preserved by the
    # destroy spell's resolution since that was a separate effect).
    chosen_id = top_two[0]
    synthetic_state.submit_manifest_dread_decision(chosen_id)

    # Manifest completed — the chosen card landed on bf.
    assert synthetic_state.find_object_zone(chosen_id) == ZONE_BATTLEFIELD
    # Source is still in graveyard. Its attached_to field is irrelevant
    # (off-bf objects don't carry meaningful attach state); the key
    # property is that no panic / no ValueError fired during submit.
    assert synthetic_state.has_pending_decision() is False


# --- empty library partial ---


def test_manifest_dread_then_attach_self_empty_library_no_op(engine):
    """ManifestDreadThenAttachSelf on an empty library: pending has
    empty cards; auto-resolve drains as no-op; source attached_to
    stays None (no manifested target to attach to)."""
    state = engine.make_synthetic_state(num_battlefield=0, num_hand=0, num_library=0)
    spell_id = state.register_and_inject_object(
        _manifest_dread_then_attach_self_dict(count=1), 0, 2  # ZONE_BATTLEFIELD
    )
    # Force ETB by triggering apply_effect via push_to_stack +
    # resolve_top_of_stack_pause: the resolve path routes ETB-effects
    # through Effect-resolve. Since the source is already on bf, the
    # ETB-driven push works.
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack_pause()

    pds = state.pending_decisions()
    assert len(pds) == 1
    assert pds[0]["kind"] == "ManifestDreadChoice"
    assert pds[0]["then_attach_to_source"] is True
    assert pds[0]["cards"] == []

    state.auto_resolve_pending_decisions("default")
    assert state.has_pending_decision() is False
    # Source attached_to stays None — no card was manifested.
    bf = state.battlefield_snapshot()
    src = next((d for d in bf if d["id"] == spell_id), None)
    if src is not None:  # source may have been resolved into gy
        assert src["attached_to"] is None


def test_manifest_dread_then_attach_self_one_card_library(engine):
    """A 1-card library manifests the lone card; the source attaches
    to it. No graveyard step from the manifest path."""
    state = engine.make_synthetic_state(num_battlefield=0, num_hand=0, num_library=1)
    lone_id = state.library_snapshot(0)[0]["id"]
    spell_id = state.register_and_inject_object(
        _manifest_dread_then_attach_self_dict(count=1), 0, 2  # ZONE_BATTLEFIELD
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack_pause()

    pds = state.pending_decisions()
    assert pds[0]["cards"] == [lone_id]
    assert pds[0]["then_attach_to_source"] is True

    state.submit_manifest_dread_decision(lone_id)
    assert state.find_object_zone(lone_id) == ZONE_BATTLEFIELD
    bf = state.battlefield_snapshot()
    src = next(d for d in bf if d["id"] == spell_id)
    assert src["attached_to"] == lone_id


# --- count > 1 deferred ---


def test_manifest_dread_then_attach_self_count_two_raises_at_resolve(synthetic_state):
    """count != 1 is deferred — same scope gate as ManifestDread."""
    spell_id = synthetic_state.register_and_inject_object(
        _manifest_dread_then_attach_self_dict(count=2), 0, 0
    )
    synthetic_state.push_to_stack(spell_id, 0)
    with pytest.raises(ValueError):
        synthetic_state.resolve_top_of_stack_pause()


# --- regression: plain ManifestDread does NOT attach ---


def test_plain_manifest_dread_does_not_attach_source(synthetic_state):
    """Regression: the existing Effect::ManifestDread arm sets
    then_attach_to_source=false, so submitting the resulting pending
    must NOT stamp source.attached_to."""
    top_two = [obj["id"] for obj in synthetic_state.library_snapshot(0)[:2]]

    spell_id = synthetic_state.register_and_inject_object(
        _manifest_dread_dict(count=1), 0, 0
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack_pause()
    # Pending decision should have the rider flag = false.
    pds = synthetic_state.pending_decisions()
    assert pds[0]["then_attach_to_source"] is False

    chosen_id = top_two[0]
    synthetic_state.submit_manifest_dread_decision(chosen_id)
    # The source spell is a sorcery — it routed to graveyard during
    # stack resolution. The manifested card on bf has attached_to None.
    bf = synthetic_state.battlefield_snapshot()
    manifested = next(d for d in bf if d["id"] == chosen_id)
    assert manifested["attached_to"] is None


# --- clone isolation ---


def test_clone_isolates_manifest_then_attach_pending(synthetic_state):
    """clone_once() deep-clones the ManifestDreadChoice including the
    then_attach_to_source flag. Resolving the clone leaves the source's
    queue intact and the source's attached_to unchanged in the source
    state."""
    top_two = [obj["id"] for obj in synthetic_state.library_snapshot(0)[:2]]
    spell_id = synthetic_state.register_and_inject_object(
        _manifest_dread_then_attach_self_dict(count=1), 0, 0
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack_pause()

    clone = synthetic_state.clone_once()
    assert clone.has_pending_decision() is True
    clone.submit_manifest_dread_decision(top_two[0])
    assert clone.has_pending_decision() is False
    clone_bf = clone.battlefield_snapshot()
    clone_eq = next(d for d in clone_bf if d["id"] == spell_id)
    assert clone_eq["attached_to"] == top_two[0]

    # Source state still has the pending decision; source still
    # un-attached (or attached_to is whatever it was, but the submit
    # path hasn't fired on the source).
    assert synthetic_state.has_pending_decision() is True
    src_bf = synthetic_state.battlefield_snapshot()
    src_eq = next(d for d in src_bf if d["id"] == spell_id)
    assert src_eq["attached_to"] is None


# --- fingerprint sensitivity to the rider flag ---


def test_fingerprint_differs_then_attach_vs_plain_manifest_dread(engine):
    """A pending ManifestDreadChoice with then_attach_to_source=true
    fingerprints differently from the same shape with the flag false.
    Guards the fingerprint serializer's inclusion of the bool slot."""
    # Build two synthetic states with the same shape but different
    # then_attach_to_source values on the pending decision.
    s1 = engine.make_synthetic_state()
    s2 = engine.make_synthetic_state()

    spell1 = s1.register_and_inject_object(_manifest_dread_dict(count=1), 0, 0)
    s1.push_to_stack(spell1, 0)
    s1.resolve_top_of_stack_pause()

    spell2 = s2.register_and_inject_object(
        _manifest_dread_then_attach_self_dict(count=1), 0, 2
    )
    s2.push_to_stack(spell2, 0)
    s2.resolve_top_of_stack_pause()

    fp1 = s1.fingerprint()
    fp2 = s2.fingerprint()
    # Even though both have a pending ManifestDreadChoice, the variants
    # differ in source_obj_id + then_attach_to_source — so fingerprints
    # MUST differ.
    assert fp1 != fp2
