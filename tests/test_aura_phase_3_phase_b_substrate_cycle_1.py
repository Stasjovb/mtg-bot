"""**Aura Phase 3+ Phase B Cycle 1 (2026-05-26).**

Tests for the Phase 3+ Phase B Cycle 1 Rust substrate landing per
``docs/AURA_ATTACH_SUBSTRATE_PHASE_3_DESIGN.md`` §4 (Rust spec) + §5
(Python bridge spec) + §7 (test plan) + §8 row 3.

Deliverables (Cycle 1 Rust slice, per design doc §4.1):

  - New Rust ``Effect`` variant on ``cards.rs::Effect``:
      * ``TargetOpponentLookHandMayDiscard`` -- Cracked Skull's ETB
        long-pole Effect ("Look at target opponent's hand. You may
        choose a nonland card from it. That player discards that
        card.").
    With: enum variant + ``parse_effect`` arm + ``to_pydict`` arm +
    ``state_ops_resolve`` resolve arm + ``cross_engine.py`` bridge
    dict->Python arm + ``trajectory.py`` reverse-serializer leaf in
    ``_python_ta_to_safe_dict_aura_phase3``.
  - Two new decision-pump pins:
      * ``PendingDecision::MayDiscardChoice {source_obj_id, controller,
        target_player_id, nonland_card_ids: Vec<u32>}`` for the
        "may force discard?" yes/no gate.
      * ``PendingDecision::OpponentHandCardChoice {source_obj_id,
        controller, target_player_id, candidates: Vec<u32>}`` for the
        directed-discard card pick.
    With: ``submit_may_discard_decision`` +
    ``submit_opponent_hand_card_decision`` entry points +
    ``auto_resolve_pending_decisions`` deterministic-first defaults +
    fingerprint arms + pending-decisions surface dict.
  - New ``GameObject.publicly_known_to_caster_bits: u32`` one-way
    reveal bitfield primitive (1 bit per player id; set by the
    look-at-hand step in the new resolve arm) + ``object_to_pydict``
    surface key for the bitfield.

This is a **substrate-only closure** -- Cracked Skull STAYS DECLINED at
the production-deck admit gate post-Cycle-1 because
``_aura_triggers_are_phase3_safe`` doesn't widen for the
ENTERS+IsSelf+TargetOpponentLookHandMayDiscard shape yet (Cycle 2 ships
the widen).

**Verify-first findings (live tree, main `63ef90b6`):** see commit msg.
"""

from __future__ import annotations

import importlib.util

import pytest


# Zone constants -- mirror ``rust/src/state_ops_zones.rs``.
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3
ZONE_EXILE = 5


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


@pytest.fixture
def engine():
    """The ``mtg_bot_engine`` module, or skip if not installed."""
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")
    import mtg_bot_engine
    return mtg_bot_engine


def _look_hand_may_discard_spell_dict():
    """A Sorcery-shape spell carrying the new Effect as its spell
    effect -- used for direct resolve-arm pins via the stack-push
    path. The Sorcery shape lets us drive the resolve arm WITHOUT
    routing through the Cracked Skull Aura admit gate (which stays
    closed in C1 by design).
    """
    return {
        "name": "Test Look Hand May Discard Spell",
        "card_types": ["Sorcery"],
        "effects": [{"kind": "target_opponent_look_hand_may_discard"}],
    }


# ---------------------------------------------------------------------------
# Parser SoT verify-first
# ---------------------------------------------------------------------------


def test_python_target_opponent_look_hand_may_discard_class_exists():
    """**Parser SoT pin.** Python's
    ``TargetOpponentLookHandMayDiscard`` class is in
    ``effects.generic.discard``, a field-free Effect subclass.
    """
    from mtg_bot.effects.base import Effect
    from mtg_bot.effects.generic.discard import (
        TargetOpponentLookHandMayDiscard,
    )

    a = TargetOpponentLookHandMayDiscard()
    assert isinstance(a, Effect)
    assert a.requires_target() is True


def test_cracked_skull_live_printing_matches_design_doc_shape():
    """**Verify-first pin -- Cracked Skull's live triggered shape.**
    Confirms the design doc §2 row at HEAD: TWO triggered abilities --

      1. ENTERS + IsSelf(subject=None) +
         TargetOpponentLookHandMayDiscard (the C1 long-pole Effect).
      2. DEALT_DAMAGE + IsHost + DestroyEnchantedPermanent (Tail-X1;
         not widened in C1).
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.effects.generic.destroy import DestroyEnchantedPermanent
    from mtg_bot.effects.generic.discard import (
        TargetOpponentLookHandMayDiscard,
    )
    from mtg_bot.effects.predicates import Event, IsHost, IsSelf

    ps = OracleParserCardSource().get_printings()
    cracked = ps["Cracked Skull"]
    assert "Aura" in cracked.subtypes
    assert cracked.is_aura is True

    tas = tuple(cracked.triggered_abilities or ())
    assert len(tas) == 2, (
        f"expected 2 triggered abilities on Cracked Skull, got "
        f"{len(tas)}: {tas}"
    )
    by_event = {ta.event: ta for ta in tas}
    assert Event.ENTERS in by_event
    assert Event.DEALT_DAMAGE in by_event

    etb_ta = by_event[Event.ENTERS]
    assert isinstance(etb_ta.predicate, IsSelf)
    assert isinstance(etb_ta.effect, TargetOpponentLookHandMayDiscard)
    assert etb_ta.once_per_turn is False

    dealt_ta = by_event[Event.DEALT_DAMAGE]
    assert isinstance(dealt_ta.predicate, IsHost)
    assert isinstance(dealt_ta.effect, DestroyEnchantedPermanent)
    assert dealt_ta.once_per_turn is False


# ---------------------------------------------------------------------------
# Cross-engine bridge arm pins (dict -> Python)
# ---------------------------------------------------------------------------


def test_bridge_arm_target_opponent_look_hand_may_discard():
    """Bridge arm constructs ``TargetOpponentLookHandMayDiscard()``
    from a single-kind dict.
    """
    from mtg_bot.effects.generic.discard import (
        TargetOpponentLookHandMayDiscard,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect({
        "kind": "target_opponent_look_hand_may_discard",
    })
    assert isinstance(back, TargetOpponentLookHandMayDiscard)


def test_bridge_arm_unit_variant_round_trip():
    """Unit-variant round trip: the field-free class round-trips
    through the bridge arm.
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect({
        "kind": "target_opponent_look_hand_may_discard",
    })
    assert back.requires_target() is True


# ---------------------------------------------------------------------------
# Reverse-serializer leaf pin in _python_ta_to_safe_dict_aura_phase3
# ---------------------------------------------------------------------------


def test_python_ta_to_safe_dict_phase3_recognizes_look_hand_may_discard():
    """**Recognition arm pin (Cycle 2 fix).** The Aura-phase3 emitter
    recognizes ``TargetOpponentLookHandMayDiscard`` and emits the
    canonical dict shape (ENTERS + IsSelf + target_opponent_look_hand_
    may_discard). Cycle 2 fixed the predicate kind string from the
    Cycle 1 placeholder ``"is_self"`` to the canonical
    ``"source_is_self"`` that Rust's ``parse_predicate`` recognizes
    (sibling of Pain for All / Tap-Enchanted-Permanent emitters at
    ``trajectory.py:7497 / 7841 / 7867``). The Cycle 1 dormant leaf
    was never invoked end-to-end so the mismatch was harmless; Cycle
    2 flips the admit gate ON and the bench-loader feeds Rust the
    emitted dict, so the kind string MUST match.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.discard import (
        TargetOpponentLookHandMayDiscard,
    )
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.parity.trajectory import (
        _python_ta_to_safe_dict_aura_phase3,
    )

    ta = TriggeredAbility(
        event=Event.ENTERS,
        predicate=IsSelf(),
        effect=TargetOpponentLookHandMayDiscard(),
        once_per_turn=False,
    )
    d = _python_ta_to_safe_dict_aura_phase3(ta)
    assert d == {
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "target_opponent_look_hand_may_discard"},
        "once_per_turn": False,
    }


def test_aura_phase3_emitter_arm_present_in_source():
    """**Substrate pre-position pin.** The emitter source carries the
    recognizer arm + kind string so Cycle 2's gate widen is purely
    additive.
    """
    import inspect
    from mtg_bot.parity import trajectory

    source = inspect.getsource(
        trajectory._python_ta_to_safe_dict_aura_phase3,
    )
    assert "TargetOpponentLookHandMayDiscard" in source, (
        "isinstance arm for TargetOpponentLookHandMayDiscard must be "
        "present in _python_ta_to_safe_dict_aura_phase3 (substrate "
        "pre-position for Cycle 2's additive gate widen)."
    )
    assert "target_opponent_look_hand_may_discard" in source, (
        "kind string must be emitted by the substrate's recognition arm."
    )


def test_aura_triggers_phase3_safe_admits_cracked_skull_post_cycle_2():
    """**INVERTED-IN-PLACE post Phase B Cycle 2 (2026-05-26).**
    Cracked Skull's full trigger surface now PASSES the Phase-3
    safe-trigger gate — both halves widened in lockstep:

      * ENTERS + IsSelf(subject=None) + TargetOpponentLookHandMayDiscard
        (Shape A — Cracked Skull's ETB long pole)
      * DEALT_DAMAGE + IsHost(subject=None) + DestroyEnchantedPermanent
        (Tail-X1 — shared with Sporogenic Infection per design doc §3)

    The all-or-nothing gate required both halves to widen together;
    Phase C will reuse the Tail-X1 admit and close Sporogenic by widening
    the ENTERS half (``TargetOpponentSacrificesCreatureOtherThanEnchanted``).
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _aura_triggers_are_phase3_safe

    ps = OracleParserCardSource().get_printings()
    cracked = ps["Cracked Skull"]
    assert _aura_triggers_are_phase3_safe(cracked.triggered_abilities) is True


def test_cracked_skull_now_admits_at_admit_gate_post_cycle_2():
    """**INVERTED-IN-PLACE post Phase B Cycle 2 (2026-05-26) — THE FLIP.**
    Cracked Skull now admits at the production-deck loader filter. The
    +0 17lands-deck flip (Cracked Skull is a positive-control carrier
    with 0 EoE decks; the deck-count signal is purely on substrate
    correctness, not deck volume — design doc §0 row 2).
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _printing_is_bridge_simple_aura

    ps = OracleParserCardSource().get_printings()
    cracked = ps["Cracked Skull"]
    assert _printing_is_bridge_simple_aura(cracked) is True


# ---------------------------------------------------------------------------
# Rust unit pins -- parse + register + to_pydict
# ---------------------------------------------------------------------------


def test_rust_register_target_opponent_look_hand_may_discard_unit_variant():
    """**Rust parse arm pin.** ``register_printing`` accepts a spell
    carrying the new effect kind.
    """
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_look_hand_may_discard_spell_dict())
    assert reg.get_printing_name(pid) == (
        "Test Look Hand May Discard Spell"
    )


def test_rust_unknown_effect_kind_enumeration_includes_new_kind():
    """**Rust parse arm pin -- completeness of unknown-kind error msg.**
    The trailing "unknown effect kind" error msg in parse_effect
    enumerates EVERY valid kind; the new C1 kind must be in that list.
    """
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError) as exc_info:
        reg.register_printing({
            "name": "Test Unknown Kind Trigger",
            "card_types": ["Sorcery"],
            "effects": [{"kind": "definitely_not_a_real_effect_kind"}],
        })
    msg = str(exc_info.value)
    assert "target_opponent_look_hand_may_discard" in msg, (
        "valid-kinds enumeration in parse_effect's unknown-kind "
        "error msg must list the new C1 kind so it is discoverable."
    )


# ---------------------------------------------------------------------------
# PendingDecision substrate pins
# ---------------------------------------------------------------------------


def test_submit_may_discard_decision_raises_on_empty_queue(engine):
    """**Substrate pin.** Calling submit_may_discard_decision with no
    pending decision raises ValueError.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=10,
    )
    with pytest.raises(ValueError, match="no pending decision"):
        state.submit_may_discard_decision(True)
    with pytest.raises(ValueError, match="no pending decision"):
        state.submit_may_discard_decision(False)


def test_submit_opponent_hand_card_decision_raises_on_empty_queue(engine):
    """**Substrate pin.** Calling submit_opponent_hand_card_decision
    with no pending decision raises ValueError.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=10,
    )
    with pytest.raises(ValueError, match="no pending decision"):
        state.submit_opponent_hand_card_decision(42)
    with pytest.raises(ValueError, match="no pending decision"):
        state.submit_opponent_hand_card_decision(None)


def test_submit_may_discard_rejects_wrong_head(engine):
    """**Decision-pump pin -- discriminant mismatch.** When the head
    of the pending-decisions queue is a different variant (e.g. a
    SurveilChoice), submit_may_discard_decision rejects with a typed
    error and the decision STAYS on the queue.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=10,
    )
    surveil_pid = state.register_and_inject_object(
        {
            "name": "Test Surveil Spell (discriminant guard)",
            "card_types": ["Sorcery"],
            "effects": [{"kind": "surveil", "count": 2}],
        },
        0,
        ZONE_HAND,
    )
    state.push_to_stack(surveil_pid, 0)
    state.resolve_top_of_stack_pause()
    pds = state.pending_decisions()
    assert len(pds) >= 1
    assert pds[0]["kind"] == "SurveilChoice"
    with pytest.raises(
        ValueError,
        match="head of pending-decisions queue is not a MayDiscardChoice",
    ):
        state.submit_may_discard_decision(True)
    pds_after = state.pending_decisions()
    assert pds_after[0]["kind"] == "SurveilChoice"


def test_submit_opponent_hand_card_rejects_wrong_head(engine):
    """**Decision-pump pin -- discriminant mismatch.** When the head
    is a different variant, submit_opponent_hand_card_decision rejects.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=10,
    )
    surveil_pid = state.register_and_inject_object(
        {
            "name": "Test Surveil Spell (discriminant guard 2)",
            "card_types": ["Sorcery"],
            "effects": [{"kind": "surveil", "count": 2}],
        },
        0,
        ZONE_HAND,
    )
    state.push_to_stack(surveil_pid, 0)
    state.resolve_top_of_stack_pause()
    with pytest.raises(
        ValueError,
        match="head of pending-decisions queue is not an OpponentHandCardChoice",
    ):
        state.submit_opponent_hand_card_decision(42)


# ---------------------------------------------------------------------------
# Rust resolve arm pins (drive via the stack push-then-resolve path)
# ---------------------------------------------------------------------------


def test_resolve_silent_fizzle_when_target_hand_empty(engine):
    """**Resolve arm pin -- empty-hand gate.** Target opponent (P1)
    has empty hand -> silent fizzle, no MayDiscardChoice push.

    Setup: ``make_synthetic_state`` seeds P1's hand by default; we set
    num_hand=0 to start with empty hands, then resolve the Sorcery.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10,
    )
    spell_id = state.register_and_inject_object(
        _look_hand_may_discard_spell_dict(), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()
    assert state.is_stack_empty() is True
    # No MayDiscardChoice pushed (empty hand fizzles).
    pds = state.pending_decisions()
    may_discard = [p for p in pds if p["kind"] == "MayDiscardChoice"]
    assert may_discard == []


def test_resolve_silent_fizzle_when_target_hand_all_lands(engine):
    """**Resolve arm pin -- nonland-options gate.** When the target's
    hand has ONLY lands, the resolve arm silent-fizzles (Python parity:
    `if not options: return` at `discard.py:352-357`).
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10,
    )
    # Inject TWO lands onto P1's hand.
    for i, name in enumerate(["Test Land Alpha", "Test Land Beta"]):
        state.register_and_inject_object(
            {
                "name": name,
                "card_types": ["Land"],
                "mana_cost": {},
            },
            1,
            ZONE_HAND,
        )
    spell_id = state.register_and_inject_object(
        _look_hand_may_discard_spell_dict(), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()
    assert state.is_stack_empty() is True
    pds = state.pending_decisions()
    may_discard = [p for p in pds if p["kind"] == "MayDiscardChoice"]
    assert may_discard == [], (
        "all-land hand must silent-fizzle (Python parity)."
    )


def test_resolve_happy_path_pushes_may_discard_choice(engine):
    """**Resolve arm pin -- happy path.** With non-empty nonland
    options, the resolve arm pushes MayDiscardChoice carrying
    source_obj_id + controller=0 + target_player_id=1 +
    nonland_card_ids snapshot (filtered to non-lands).
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10,
    )
    # Inject a mix: 1 land + 2 creatures on P1's hand.
    state.register_and_inject_object(
        {
            "name": "Land A",
            "card_types": ["Land"],
            "mana_cost": {},
        },
        1,
        ZONE_HAND,
    )
    creature_ids: list[int] = []
    for name in ["Creature A", "Creature B"]:
        cid = state.register_and_inject_object(
            {
                "name": name,
                "card_types": ["Creature"],
                "subtypes": ["Bear"],
                "mana_cost": {"generic": 1, "G": 1},
                "power": 2,
                "toughness": 2,
            },
            1,
            ZONE_HAND,
        )
        creature_ids.append(cid)

    spell_id = state.register_and_inject_object(
        _look_hand_may_discard_spell_dict(), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack_pause()
    pds = state.pending_decisions()
    # The MayDiscardChoice is on the queue.
    may_discard = [p for p in pds if p["kind"] == "MayDiscardChoice"]
    assert len(may_discard) == 1
    md = may_discard[0]
    assert md["controller"] == 0
    assert md["target_player_id"] == 1
    # The nonland filter dropped the land card.
    assert sorted(md["nonland_card_ids"]) == sorted(creature_ids)


def test_resolve_look_step_stamps_publicly_known_bit(engine):
    """**One-way reveal substrate pin.** The look step stamps
    publicly_known_to_caster_bits |= (1 << controller) on EVERY card
    in the target opponent's hand (including lands -- the look-at-hand
    primitive is independent of the nonland-options gate). Caster's
    own hand is UNTOUCHED (one-way).
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10,
    )
    # Inject onto P1's hand: 1 land + 1 creature.
    target_ids: list[int] = []
    for entry in [
        {"name": "Land One", "card_types": ["Land"], "mana_cost": {}},
        {
            "name": "Creature One",
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
        },
    ]:
        cid = state.register_and_inject_object(entry, 1, ZONE_HAND)
        target_ids.append(cid)

    # Inject a card onto P0's own hand (the caster) -- one-way
    # property test.
    p0_hand_id = state.register_and_inject_object(
        {
            "name": "Caster's Own Creature",
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
        },
        0,
        ZONE_HAND,
    )

    spell_id = state.register_and_inject_object(
        _look_hand_may_discard_spell_dict(), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack_pause()

    # P1's hand -- every card has bit 0 (controller=0) set.
    reveal_bit_for_p0 = 1 << 0
    p1_hand = state.hand_snapshot(1)
    matching = [c for c in p1_hand if c["id"] in target_ids]
    assert len(matching) == len(target_ids)
    for c in matching:
        assert (
            c["publicly_known_to_caster_bits"] & reveal_bit_for_p0
        ) != 0, (
            f"target card {c['id']!r} should be publicly known to P0"
        )

    # P0's own hand card -- NOT touched (one-way semantics).
    p0_hand = state.hand_snapshot(0)
    p0_match = [c for c in p0_hand if c["id"] == p0_hand_id]
    assert len(p0_match) == 1
    assert p0_match[0]["publicly_known_to_caster_bits"] == 0, (
        "caster's own hand cards must not be stamped — one-way reveal."
    )


def test_resolve_arm_does_not_move_card_before_decisions_drained(engine):
    """**Resolve arm pin -- two-step contract.** The resolve arm
    PUSHES MayDiscardChoice but does NOT move any card -- the move
    only happens after both decisions are drained. P1's hand is
    UNCHANGED post-resolve.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10,
    )
    cid = state.register_and_inject_object(
        {
            "name": "Pretty Creature",
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
        },
        1,
        ZONE_HAND,
    )
    spell_id = state.register_and_inject_object(
        _look_hand_may_discard_spell_dict(), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack_pause()
    # MayDiscardChoice is queued; card not moved yet.
    assert state.find_object_zone(cid) == ZONE_HAND
    pds = state.pending_decisions()
    assert any(p["kind"] == "MayDiscardChoice" for p in pds)


# ---------------------------------------------------------------------------
# Two-decision flow (MayDiscard yes -> OpponentHandCardChoice)
# ---------------------------------------------------------------------------


def test_may_discard_yes_pushes_opponent_hand_card_choice(engine):
    """**Two-decision flow pin.** Submitting `True` to MayDiscardChoice
    consumes it AND pushes OpponentHandCardChoice at the FRONT with the
    same payload (source + controller + target_player_id + candidates).
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10,
    )
    creature_ids: list[int] = []
    for name in ["Bear A", "Bear B"]:
        cid = state.register_and_inject_object(
            {
                "name": name,
                "card_types": ["Creature"],
                "subtypes": ["Bear"],
                "mana_cost": {"generic": 1, "G": 1},
                "power": 2,
                "toughness": 2,
            },
            1,
            ZONE_HAND,
        )
        creature_ids.append(cid)

    spell_id = state.register_and_inject_object(
        _look_hand_may_discard_spell_dict(), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack_pause()
    # Head is MayDiscardChoice.
    pds_before = state.pending_decisions()
    assert pds_before[0]["kind"] == "MayDiscardChoice"
    # Submit YES.
    state.submit_may_discard_decision(True)
    # Now head is OpponentHandCardChoice with the carried payload.
    pds_after = state.pending_decisions()
    head = pds_after[0]
    assert head["kind"] == "OpponentHandCardChoice"
    assert head["controller"] == 0
    assert head["target_player_id"] == 1
    assert sorted(head["candidates"]) == sorted(creature_ids)


def test_may_discard_no_consumes_decision_silent_fizzle(engine):
    """**Two-decision flow pin -- NO branch.** Submitting `False`
    consumes the MayDiscardChoice WITHOUT pushing the follow-up.
    Mirrors Python's `state.log.append(...); return` at
    `discard.py:368-372`.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10,
    )
    cid = state.register_and_inject_object(
        {
            "name": "Bear C",
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
        },
        1,
        ZONE_HAND,
    )
    spell_id = state.register_and_inject_object(
        _look_hand_may_discard_spell_dict(), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack_pause()
    state.submit_may_discard_decision(False)
    # MayDiscardChoice consumed; no follow-up.
    pds = state.pending_decisions()
    has_may = any(p["kind"] == "MayDiscardChoice" for p in pds)
    has_opp = any(p["kind"] == "OpponentHandCardChoice" for p in pds)
    assert not has_may
    assert not has_opp
    # Card still in P1's hand.
    assert state.find_object_zone(cid) == ZONE_HAND


def test_opponent_hand_card_pick_moves_card_to_target_graveyard(engine):
    """**Discard-pick step pin -- happy path.** Submitting
    `Some(card_id)` removes the chosen card from the target opponent's
    hand and moves it to the target's graveyard with CR 400.7 zone-
    change reset. Mirrors Python's `target.hand.remove(chosen); chosen.
    zone = Zone.GRAVEYARD; target.graveyard.append(chosen)` at
    `discard.py:379-381`.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10,
    )
    creature_ids: list[int] = []
    for name in ["Bear D", "Bear E"]:
        cid = state.register_and_inject_object(
            {
                "name": name,
                "card_types": ["Creature"],
                "subtypes": ["Bear"],
                "mana_cost": {"generic": 1, "G": 1},
                "power": 2,
                "toughness": 2,
            },
            1,
            ZONE_HAND,
        )
        creature_ids.append(cid)
    p1_gy_before = state.graveyard_sizes[1]
    p1_hand_before = state.hand_sizes[1]

    spell_id = state.register_and_inject_object(
        _look_hand_may_discard_spell_dict(), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack_pause()
    state.submit_may_discard_decision(True)
    chosen = creature_ids[1]
    state.submit_opponent_hand_card_decision(chosen)
    # The chosen card moved hand -> graveyard.
    assert state.find_object_zone(chosen) == ZONE_GRAVEYARD
    assert state.graveyard_sizes[1] == p1_gy_before + 1
    assert state.hand_sizes[1] == p1_hand_before - 1
    # The non-chosen card stayed.
    assert state.find_object_zone(creature_ids[0]) == ZONE_HAND


def test_opponent_hand_card_decision_raises_on_unknown_id(engine):
    """**Substrate pin -- transactional failure.** Passing a chosen_id
    NOT in candidates raises ValueError BEFORE mutation (decision
    stays at the head).
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10,
    )
    state.register_and_inject_object(
        {
            "name": "Bear F",
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
        },
        1,
        ZONE_HAND,
    )
    spell_id = state.register_and_inject_object(
        _look_hand_may_discard_spell_dict(), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack_pause()
    state.submit_may_discard_decision(True)
    with pytest.raises(ValueError, match="99999"):
        state.submit_opponent_hand_card_decision(99999)
    # Head still OpponentHandCardChoice (transactional).
    pds = state.pending_decisions()
    assert pds[0]["kind"] == "OpponentHandCardChoice"


def test_opponent_hand_card_decision_none_silent_fizzle(engine):
    """**Substrate pin -- explicit decline path.** Passing None
    consumes the head WITHOUT discarding any card (defensive).
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10,
    )
    cid = state.register_and_inject_object(
        {
            "name": "Bear G",
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
        },
        1,
        ZONE_HAND,
    )
    spell_id = state.register_and_inject_object(
        _look_hand_may_discard_spell_dict(), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack_pause()
    state.submit_may_discard_decision(True)
    state.submit_opponent_hand_card_decision(None)
    pds = state.pending_decisions()
    assert not any(p["kind"] == "OpponentHandCardChoice" for p in pds)
    # Hand unchanged.
    assert state.find_object_zone(cid) == ZONE_HAND


# ---------------------------------------------------------------------------
# Auto-resolve (deterministic-first defaults)
# ---------------------------------------------------------------------------


def test_auto_resolve_default_say_yes_then_pick_first(engine):
    """**Auto-resolve pin.** `default` -> MayDiscard says YES;
    OpponentHandCardChoice picks `candidates[0]` and moves it to the
    target's graveyard.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10,
    )
    creature_ids: list[int] = []
    for name in ["Bear H", "Bear I"]:
        cid = state.register_and_inject_object(
            {
                "name": name,
                "card_types": ["Creature"],
                "subtypes": ["Bear"],
                "mana_cost": {"generic": 1, "G": 1},
                "power": 2,
                "toughness": 2,
            },
            1,
            ZONE_HAND,
        )
        creature_ids.append(cid)
    spell_id = state.register_and_inject_object(
        _look_hand_may_discard_spell_dict(), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack_pause()
    state.auto_resolve_pending_decisions("default")
    # No pending decisions left.
    pds = state.pending_decisions()
    assert pds == []
    # candidates[0] = creature_ids[0] moved to P1's graveyard.
    assert state.find_object_zone(creature_ids[0]) == ZONE_GRAVEYARD
    assert state.find_object_zone(creature_ids[1]) == ZONE_HAND


def test_auto_resolve_may_discard_no_drops_decision(engine):
    """**Auto-resolve pin -- may_discard_no.** Strategy `may_discard_no`
    drops the MayDiscardChoice without enqueueing the follow-up.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10,
    )
    cid = state.register_and_inject_object(
        {
            "name": "Bear J",
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
        },
        1,
        ZONE_HAND,
    )
    spell_id = state.register_and_inject_object(
        _look_hand_may_discard_spell_dict(), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack_pause()
    state.auto_resolve_pending_decisions("may_discard_no")
    pds = state.pending_decisions()
    assert pds == []
    # Card stayed in hand.
    assert state.find_object_zone(cid) == ZONE_HAND


def test_auto_resolve_unknown_strategy_raises(engine):
    """**Auto-resolve pin -- unknown strategy.** Unknown strategy
    names raise ValueError without mutating the queue. The valid-list
    enumerates the new strategies.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=10,
    )
    with pytest.raises(ValueError) as exc:
        state.auto_resolve_pending_decisions("this_is_not_a_real_strategy")
    msg = str(exc.value)
    assert "may_discard_yes" in msg
    assert "opponent_hand_card_first" in msg


# ---------------------------------------------------------------------------
# Snapshot surface: publicly_known_to_caster_bits default + field exposure
# ---------------------------------------------------------------------------


def test_publicly_known_to_caster_bits_defaults_to_zero(engine):
    """**One-way reveal substrate pin.** Freshly-allocated objects
    have publicly_known_to_caster_bits = 0 (back-compat default; the
    field is additive but the value is invariant on snapshots that
    don't exercise the look-step).
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=10,
    )
    cid = state.register_and_inject_object(
        {
            "name": "Default Bear",
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
        },
        0,
        ZONE_HAND,
    )
    hand = state.hand_snapshot(0)
    target = next((c for c in hand if c["id"] == cid), None)
    assert target is not None
    assert target["publicly_known_to_caster_bits"] == 0


# ---------------------------------------------------------------------------
# Cycle 2 sequencing invariants (pre-positions for the gate widen)
# ---------------------------------------------------------------------------


def test_aura_triggers_phase3_safe_still_admits_chorale_post_cycle_2(
):
    """**Adjacent regression pin -- Aura Phase A Cycle 2 doesn't
    regress.** Chorale of the Void (Phase A Cycle 2 PROBED) still
    admits at the bridge gate post-C1-of-Phase-B; the new Effect
    variant adds no new declines to the Phase A gate.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _aura_triggers_are_phase3_safe

    ps = OracleParserCardSource().get_printings()
    chorale = ps["Chorale of the Void"]
    assert _aura_triggers_are_phase3_safe(chorale.triggered_abilities) is True


def test_pain_for_all_still_admits_post_phase_b_cycle_1():
    """**Adjacent regression pin -- Pain for All still admits.** The
    Phase-3 closure's Pain for All carrier is unaffected by Phase B's
    substrate landing.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _aura_triggers_are_phase3_safe

    ps = OracleParserCardSource().get_printings()
    pfa = ps["Pain for All"]
    assert _aura_triggers_are_phase3_safe(pfa.triggered_abilities) is True


def test_tractor_beam_still_admits_post_phase_b_cycle_1():
    """**Adjacent regression pin -- Tractor Beam still admits.**"""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _aura_triggers_are_phase3_safe

    ps = OracleParserCardSource().get_printings()
    tb = ps["Tractor Beam"]
    assert _aura_triggers_are_phase3_safe(tb.triggered_abilities) is True
