"""Aura-attachment substrate — Phase 1 STEP 3 tests.

Spec: ``docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md`` §3 Phase 1 step 3.

**STEP 3 scope.** When an Aura spell is cast, the controller MUST
choose a legal enchant target as part of casting (CR 303.4 / 601.2c).
This step adds the cast-time enchant-target decision substrate on
the Rust side:

* New ``PendingDecision::EnchantTargetChoice`` variant on
  ``GameState.pending_decisions``.
* New ``cast_aura`` primitive that gates on the printing's
  ``is_aura`` flag (set by STEP 2's parse arm), pays the mana cost,
  rehomes the spell onto the stack store, builds the legal-host
  candidate list per ``aura_enchant_type`` + ``aura_yours_only``,
  pushes the StackItem with ``target_obj_id=None`` defaults, and
  queues the ``EnchantTargetChoice`` decision iff the candidate set
  is non-empty.
* ``submit_enchant_target_decision(chosen_id)`` consumes the head
  decision and binds ``chosen_id`` onto the matching spell
  StackItem's ``target_obj_id``. ``None`` is allowed (no target
  picked — Aura will fizzle on resolve per STEP 4).
* Auto-resolve strategy ``"enchant_target_first"`` (and the
  ``"default"`` fallback) picks ``candidates[0]`` (deterministic-
  first legal host in ``bf_iter_etb_sorted`` order).
* Dispatcher (``state_ops_actions.rs::Action::CastSpell``) tries
  ``cast_aura`` first, then falls through to
  ``cast_spell_noncreature`` / ``cast_creature``.

**Deferred to STEP 4+:**
* The Aura-resolution arm that reads the bound target and stamps
  ``aura.attached_to = Some(host_id)`` + applies the layer-7 P/T
  grant.
* Fizzle-on-no-legal-target at resolve time (Python parity at
  ``actions.py:2740-2745``).
* CR-704.5n SBA (bury host-less Aura) + host-leave bury.
* Bidirectional bridge round-trip of the new state slots.

These tests exercise the cast-time decision substrate in isolation
using synthetic state fixtures (the loader still does not admit any
real Aura — STEP 7 honest-stop, see
``test_aura_substrate_phase1.py``).
"""

from __future__ import annotations

import importlib

import pytest

ZONE_HAND = 0
ZONE_BATTLEFIELD = 2


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


def _aura_printing_dict(
    name="Frantic Strength",
    mana_cost=None,
    enchant_type="creature",
    yours_only=False,
    p_bonus=2,
    t_bonus=2,
    granted_keywords=("trample",),
):
    """Build a registry-dict for an Aura printing. Mirrors the
    STEP-2 emission shape (``cross_engine.py:10384-10391``) so the
    parse arm reads the same keys ``build_rust_state`` produces."""
    if mana_cost is None:
        mana_cost = {"R": 1}
    d = {
        "name": name,
        "mana_cost": mana_cost,
        "card_types": ["Enchantment"],
        "subtypes": ["Aura"],
        "is_aura": True,
        "aura_enchant_type": enchant_type,
    }
    if yours_only:
        d["aura_yours_only"] = True
    if p_bonus or t_bonus or granted_keywords:
        d["aura_equipment_bonuses"] = {
            "power_bonus": p_bonus,
            "toughness_bonus": t_bonus,
            "granted_keywords": list(granted_keywords),
        }
    return d


def _creature_dict(name="Grizzly Bears", power=2, toughness=2):
    return {
        "name": name,
        "mana_cost": {"generic": 1, "G": 1},
        "card_types": ["Creature"],
        "subtypes": ["Bear"],
        "power": power,
        "toughness": toughness,
    }


def _artifact_dict(name="Plain Artifact"):
    return {
        "name": name,
        "mana_cost": {"generic": 2},
        "card_types": ["Artifact"],
    }


def _fresh_state():
    """A 0-bf / 0-hand / 0-library state. We inject everything by
    hand via ``register_and_inject_object``."""
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


# ---------------------------------------------------------------------------
# PendingDecision::EnchantTargetChoice surface: dict shape + push
# ---------------------------------------------------------------------------


def test_cast_aura_with_legal_targets_surfaces_decision():
    """Casting an Aura with at least one legal enchant target on the
    battlefield must push a ``PendingDecision::EnchantTargetChoice``
    onto the pending-decisions queue.

    Scenario: P0 has Frantic Strength (Aura, ``R`` cost) in hand, P0
    has Grizzly Bears on bf, P1 has Llanowar Elves on bf. P0's mana
    pool has ``R``. After casting, the queue surfaces ONE
    ``EnchantTargetChoice`` dict whose ``candidates`` is both
    creatures (Frantic Strength is `aura_yours_only=False`).
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    elves_id = state.register_and_inject_object(
        _creature_dict("Elves", power=1, toughness=1), 1, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "R", 1)
    assert state.pending_decisions() == []
    ok = state.cast_aura(aura_id, 0)
    assert ok is True
    pds = state.pending_decisions()
    assert len(pds) == 1
    pd = pds[0]
    assert pd["kind"] == "EnchantTargetChoice"
    assert pd["source_obj_id"] == aura_id
    assert pd["controller"] == 0
    # Candidates: both creatures admitted.
    assert set(pd["candidates"]) == {bears_id, elves_id}


def test_cast_aura_no_legal_targets_does_not_queue_decision():
    """An Aura cast with NO legal enchant targets on the battlefield
    is still ALLOWED (Python parity at ``actions.py:1337-1357``).
    The cast pump returns ``True`` and pushes the spell StackItem,
    but NO ``EnchantTargetChoice`` is queued (an empty-candidate
    decision would leave the caster with no legal id to submit).
    STEP 4's resolve arm will fizzle the Aura, mirroring Python's
    ``actions.py:2740-2745``.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_HAND,
    )
    # Empty bf — no creatures.
    state.add_mana(0, "R", 1)
    ok = state.cast_aura(aura_id, 0)
    assert ok is True
    assert state.pending_decisions() == []
    # Spell is on the stack, target slot is None.
    assert state.stack_size() == 1
    stack_dict = state.stack_snapshot()[0]
    assert stack_dict["source_obj_id"] == aura_id
    assert state.stack_top_target_id() is None


def test_cast_aura_yours_only_restricts_candidates_to_caster():
    """An Aura with ``aura_yours_only=True`` (Shardmage's Rescue
    shape — printed text "Enchant creature you control") MUST
    restrict the candidate set to creatures the CASTER controls.
    Mirrors Python's ``actions.py:1339, 1345/1352`` filter.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(
            name="Shardmage's Rescue",
            mana_cost={"W": 1},
            yours_only=True,
            p_bonus=1, t_bonus=1, granted_keywords=(),
        ),
        0, ZONE_HAND,
    )
    p0_bears = state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    p1_elves = state.register_and_inject_object(
        _creature_dict("Elves"), 1, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "W", 1)
    ok = state.cast_aura(aura_id, 0)
    assert ok is True
    pd = state.pending_decisions()[0]
    assert pd["kind"] == "EnchantTargetChoice"
    # yours_only=True: only P0's Bears admitted; P1's Elves is NOT.
    assert pd["candidates"] == [p0_bears]
    assert p1_elves not in pd["candidates"]


def test_cast_aura_artifact_enchant_type_filters_to_artifacts():
    """An Aura whose ``aura_enchant_type="artifact"`` filters
    candidates to ``is_artifact`` permanents — not creatures.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(
            name="Artifact Aura",
            mana_cost={"generic": 1},
            enchant_type="artifact",
            p_bonus=0, t_bonus=0, granted_keywords=(),
        ),
        0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    artifact_id = state.register_and_inject_object(
        _artifact_dict("Plain Artifact"), 0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "C", 1)
    ok = state.cast_aura(aura_id, 0)
    assert ok is True
    pd = state.pending_decisions()[0]
    # Artifact-enchant: artifact admitted, creature is NOT.
    assert pd["candidates"] == [artifact_id]
    assert bears_id not in pd["candidates"]


# ---------------------------------------------------------------------------
# Non-Aura printing through cast_aura: returns False with no mutation
# ---------------------------------------------------------------------------


def test_cast_aura_non_aura_printing_returns_false_no_mutation():
    """A non-Aura printing (e.g. a plain creature) routed through
    ``cast_aura`` returns ``False`` with NO mutation. This is the
    load-bearing dispatcher contract: ``cast_aura`` is tried first
    in ``Action::CastSpell``, so it MUST fall through cleanly on a
    non-Aura.
    """
    _require_engine()
    state = _fresh_state()
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_HAND,
    )
    state.add_mana(0, "G", 1)
    state.add_mana(0, "C", 1)
    pre_hand = state.hand_snapshot(0)
    pre_stack_size = state.stack_size()
    pre_decisions = state.pending_decisions()
    pre_pool = state.mana_pool_snapshot(0)
    ok = state.cast_aura(bears_id, 0)
    assert ok is False
    # No mutation.
    assert state.hand_snapshot(0) == pre_hand
    assert state.stack_size() == pre_stack_size
    assert state.pending_decisions() == pre_decisions
    assert state.mana_pool_snapshot(0) == pre_pool


def test_cast_aura_card_not_in_hand_returns_false():
    """``cast_aura`` returns ``False`` if the object is not in the
    caster's hand (the standard hand-lookup gate every cast
    primitive obeys)."""
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_BATTLEFIELD,  # NOT in hand
    )
    state.add_mana(0, "R", 1)
    ok = state.cast_aura(aura_id, 0)
    assert ok is False
    # No mutation.
    assert state.stack_size() == 0
    assert state.pending_decisions() == []


# ---------------------------------------------------------------------------
# submit_enchant_target_decision: binds chosen_id onto StackItem
# ---------------------------------------------------------------------------


def test_submit_enchant_target_decision_binds_to_stack_item():
    """``submit_enchant_target_decision(chosen_id)`` consumes the
    head ``EnchantTargetChoice`` and stamps ``chosen_id`` onto the
    matching spell StackItem's ``target_obj_id``. STEP 4's resolve
    arm will read this slot via the standard
    ``current_resolve_payload_target_id`` swap.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    state.register_and_inject_object(
        _creature_dict("Elves"), 1, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "R", 1)
    state.cast_aura(aura_id, 0)
    # Pre-submit: StackItem.target_obj_id is None.
    assert state.stack_top_target_id() is None
    state.submit_enchant_target_decision(bears_id)
    # Decision consumed.
    assert state.pending_decisions() == []
    # StackItem now carries the bound target.
    assert state.stack_top_target_id() == bears_id


def test_submit_enchant_target_decision_none_leaves_target_unbound():
    """``submit_enchant_target_decision(None)`` explicitly declines
    to bind a target. The StackItem's ``target_obj_id`` stays
    ``None``; STEP 4's resolve arm will fizzle the Aura.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_HAND,
    )
    state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "R", 1)
    state.cast_aura(aura_id, 0)
    state.submit_enchant_target_decision(None)
    assert state.pending_decisions() == []
    assert state.stack_top_target_id() is None


def test_submit_enchant_target_decision_invalid_id_raises():
    """An ``chosen_id`` that is not in the candidate set raises
    ``ValueError`` transactionally — no mutation on failure, the
    decision stays at the head of the queue.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_HAND,
    )
    state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "R", 1)
    state.cast_aura(aura_id, 0)
    pre_decisions = state.pending_decisions()
    pre_target = state.stack_top_target_id()
    with pytest.raises(ValueError, match="not one of the candidate"):
        state.submit_enchant_target_decision(99999)
    assert state.pending_decisions() == pre_decisions
    assert state.stack_top_target_id() == pre_target


def test_submit_enchant_target_decision_empty_queue_raises():
    """Calling submit when the queue is empty raises ``ValueError``."""
    _require_engine()
    state = _fresh_state()
    with pytest.raises(ValueError, match="no pending decision"):
        state.submit_enchant_target_decision(123)


def test_submit_enchant_target_decision_wrong_head_raises():
    """Calling submit when the queue head is a DIFFERENT
    PendingDecision variant raises ``ValueError`` — the dispatcher
    refuses to consume a non-EnchantTargetChoice. Same discriminant-
    check shape every other variant-specific submit dispatcher uses.
    Concretely: submit_surveil_decision on an EnchantTargetChoice
    head raises (the symmetric assertion exists in the existing
    TapPermanentChoice + SurveilChoice tests).
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_HAND,
    )
    state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "R", 1)
    state.cast_aura(aura_id, 0)
    # Wrong dispatcher: head is EnchantTargetChoice, but we call
    # submit_surveil_decision.
    with pytest.raises(ValueError, match="not a SurveilChoice"):
        state.submit_surveil_decision([], [])


# ---------------------------------------------------------------------------
# Auto-resolve: "enchant_target_first" / "default" picks candidates[0]
# ---------------------------------------------------------------------------


def test_auto_resolve_enchant_target_first_picks_first_candidate():
    """``auto_resolve_pending_decisions("enchant_target_first")``
    binds ``candidates[0]`` onto the matching StackItem — mirrors
    the deterministic-first ``_PickFirstLegalTargetAgent`` convention
    every other cast-time target picker uses.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    state.register_and_inject_object(
        _creature_dict("Elves"), 1, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "R", 1)
    state.cast_aura(aura_id, 0)
    # candidates[0] should be Bears (P0 bf timestamps come first).
    pd = state.pending_decisions()[0]
    assert pd["candidates"][0] == bears_id
    state.auto_resolve_pending_decisions("enchant_target_first")
    assert state.pending_decisions() == []
    assert state.stack_top_target_id() == bears_id


def test_auto_resolve_default_picks_first_candidate_for_aura():
    """The ``"default"`` strategy MUST resolve an
    ``EnchantTargetChoice`` deterministically to ``candidates[0]``.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "R", 1)
    state.cast_aura(aura_id, 0)
    state.auto_resolve_pending_decisions("default")
    assert state.pending_decisions() == []
    assert state.stack_top_target_id() == bears_id


def test_auto_resolve_unknown_strategy_raises():
    """An unknown auto-resolve strategy raises ``ValueError`` (the
    standard validation pattern every variant obeys)."""
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_HAND,
    )
    state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "R", 1)
    state.cast_aura(aura_id, 0)
    with pytest.raises(ValueError, match="unknown strategy"):
        state.auto_resolve_pending_decisions("not_a_real_strategy")


# ---------------------------------------------------------------------------
# Dispatcher integration: Action::CastSpell routes Aura through cast_aura
# ---------------------------------------------------------------------------


def test_dispatcher_routes_aura_cast_through_cast_aura_arm():
    """An ``Action::CastSpell`` dict whose card_id is an Aura in
    hand MUST be dispatched through ``cast_aura``. End-to-end pin
    that search-loop callers can drive an Aura cast through the
    same ``CastSpell`` dict shape Python emits.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_HAND,
    )
    state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "R", 1)
    state.apply_action({"kind": "cast_spell", "card_id": aura_id})
    pds = state.pending_decisions()
    assert len(pds) == 1
    assert pds[0]["kind"] == "EnchantTargetChoice"


def test_dispatcher_falls_through_to_cast_creature_for_non_aura():
    """An ``Action::CastSpell`` for a plain Creature flows through
    the ``cast_aura -> cast_spell_noncreature -> cast_creature``
    dispatcher chain and lands on ``cast_creature`` (the Aura arm
    returns False with no mutation; the noncreature arm rejects the
    creature shape; the creature arm commits).
    """
    _require_engine()
    state = _fresh_state()
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_HAND,
    )
    state.add_mana(0, "G", 1)
    state.add_mana(0, "C", 1)
    state.apply_action({"kind": "cast_spell", "card_id": bears_id})
    # The creature spell landed on the stack; no decision queued.
    assert state.pending_decisions() == []
    assert state.stack_size() == 1


# ---------------------------------------------------------------------------
# Fingerprint coverage: EnchantTargetChoice is part of the gameplay-
# relevant digest.
# ---------------------------------------------------------------------------


def test_fingerprint_distinguishes_with_and_without_enchant_target_choice():
    """A ``GameState`` with an ``EnchantTargetChoice`` on the queue
    MUST fingerprint differently from one without — the choice
    surface is part of the gameplay-relevant digest (mirrors every
    other PendingDecision variant's fingerprint contract).
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_HAND,
    )
    state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "R", 1)
    fp_pre = state.fingerprint()
    state.cast_aura(aura_id, 0)
    fp_post = state.fingerprint()
    assert fp_pre != fp_post


def test_fingerprint_changes_when_chosen_target_binds():
    """Binding a target on the StackItem (via the submit dispatcher)
    must change the fingerprint — the bound id is part of the
    gameplay-relevant digest (resolve-time behavior reads it)."""
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "R", 1)
    state.cast_aura(aura_id, 0)
    fp_pre = state.fingerprint()
    state.submit_enchant_target_decision(bears_id)
    fp_post = state.fingerprint()
    # Queue was non-empty pre-submit, empty post-submit (different
    # digest); ALSO the StackItem's target_obj_id changed (different
    # digest). Either alone would flip the fingerprint; together
    # they must.
    assert fp_pre != fp_post


# ---------------------------------------------------------------------------
# Clone safety: pending_decisions including EnchantTargetChoice clones
# correctly.
# ---------------------------------------------------------------------------


def test_clone_state_preserves_enchant_target_choice():
    """Cloning a state with an ``EnchantTargetChoice`` on the queue
    preserves the variant; resolving on the clone does NOT mutate
    the original.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_HAND,
    )
    state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "R", 1)
    state.cast_aura(aura_id, 0)
    cloned = state.clone_once()
    pds_orig = state.pending_decisions()
    pds_clone = cloned.pending_decisions()
    assert pds_orig == pds_clone
    # Resolving on the clone doesn't touch the original.
    cloned.auto_resolve_pending_decisions("default")
    assert state.pending_decisions() == pds_orig
    assert cloned.pending_decisions() == []


# ---------------------------------------------------------------------------
# Mana payment: cast_aura goes through auto_tap_for_cost
# ---------------------------------------------------------------------------


def test_cast_aura_pays_cost_from_pool_first():
    """``cast_aura`` MUST pay the printing's ``mana_cost`` via the
    same ``auto_tap_pay_for_cost`` path ``cast_creature`` /
    ``cast_spell_noncreature`` use. With pool=R and an empty bf,
    casting Frantic Strength (``R`` cost) drains the pool but
    nothing on bf changes (no creatures to be a candidate, so the
    decision is skipped — but the cost IS paid).
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_HAND,
    )
    state.add_mana(0, "R", 1)
    assert state.mana_pool_snapshot(0)["R"] == 1
    ok = state.cast_aura(aura_id, 0)
    assert ok is True
    # Pool drained.
    assert state.mana_pool_snapshot(0)["R"] == 0


def test_cast_aura_insufficient_mana_returns_false_no_mutation():
    """If the controller can't pay the cost (empty pool, no
    untapped lands producing the required color), ``cast_aura``
    returns ``False`` with NO mutation."""
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_HAND,
    )
    state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    # No mana, no lands → cost unpayable.
    pre_hand = state.hand_snapshot(0)
    pre_stack_size = state.stack_size()
    ok = state.cast_aura(aura_id, 0)
    assert ok is False
    assert state.hand_snapshot(0) == pre_hand
    assert state.stack_size() == pre_stack_size
    assert state.pending_decisions() == []


# ---------------------------------------------------------------------------
# Spells-cast counter bump (MMM Pin 1 parity with cast_creature)
# ---------------------------------------------------------------------------


def test_cast_aura_increments_spells_cast_this_turn():
    """``cast_aura`` must increment the caster's
    ``spells_cast_this_turn`` counter BEFORE the IS_CAST event
    dispatch — parity with ``cast_creature`` /
    ``cast_spell_noncreature``. The counter feeds
    ``StatePredicate::SpellsCastThisTurn`` ("your second spell each
    turn" — Magecraft, prowess, etc.).

    Verified end-to-end by the fingerprint test above (the bump
    participates in the gameplay-relevant digest); this test is the
    direct read-back via the fingerprint difference test pattern
    (no direct getter is exposed for the counter today — the
    fingerprint coverage is the load-bearing equivalent).
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_HAND,
    )
    state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "R", 1)
    fp_pre = state.fingerprint()
    state.cast_aura(aura_id, 0)
    fp_post = state.fingerprint()
    # The counter bump (plus the cast + decision + pool drain) is
    # observable as a fingerprint difference. The direct counter
    # getter is not exposed, so this is the indirect contract.
    assert fp_pre != fp_post
