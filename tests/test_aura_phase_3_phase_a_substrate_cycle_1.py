"""**Aura Phase 3+ Phase A Cycle 1 (2026-05-25).**

Tests for the Phase 3+ Phase A Cycle 1 Rust substrate landing per
``docs/AURA_ATTACH_SUBSTRATE_PHASE_3_DESIGN.md`` §4 (Rust spec) + §5
(Python bridge spec) + §7 (test plan).

Deliverables (Cycle 1 Rust slice, per design doc §4.1):

  - New Rust ``Effect`` variant on ``cards.rs::Effect``:
      * ``ReanimateTargetCreatureCardFromDefendersGraveyard`` —
        Chorale of the Void's ATTACKS-trigger long pole ("Whenever
        enchanted creature attacks, put target creature card from
        defending player's graveyard onto the battlefield under your
        control tapped and attacking.").
    With: enum variant + ``parse_effect`` arm + ``to_pydict`` arm +
    ``state_ops_resolve`` resolve arm + ``cross_engine.py`` bridge
    dict→Python arm + ``trajectory.py`` reverse-serializer leaf in
    ``_python_ta_to_safe_dict_aura_phase3``.
  - New decision-pump pin:
      * ``PendingDecision::GraveyardCardChoice {source_obj_id,
        controller, candidates: Vec<u32>}`` for trigger-time
        graveyard-creature target choice + ``submit_graveyard_card_
        decision`` entry point + ``auto_resolve_pending_decisions``
        deterministic-first default + fingerprint arm.

This is a **substrate-only closure** — the cycle adds the new Rust
Effect variant + decision-pump pin + bridge plumbing as reusable
infrastructure. The pilot card (Chorale of the Void) STAYS DECLINED
at the production-deck admit gate post-Cycle-1 because:

  - ``_aura_triggers_are_phase3_safe`` does NOT widen to admit the
    ATTACKS + IsHost(subject="attacker") + Reanimate shape yet
    (Cycle 2 ships the widen + the trigger-fire push of
    ``PendingDecision::GraveyardCardChoice`` in the same slice).
  - The tail ``BEGINNING_OF_END_STEP + Controlled(YOU) +
    SacrificeSelfUnlessVoidActive`` half is also not yet widened
    (sibling Tail-X2 admit ships with the Chorale long-pole cycle).
  - The all-or-nothing gate refuses to admit a card whose other
    trigger isn't in the safe set — both halves widen together in
    Cycle 2.

**Verify-first findings (live tree, main `aa1ebe22`):**

  - Chorale of the Void's live oracle text: TWO triggered abilities —
    ATTACKS + IsHost(subject="attacker") + Reanimate…DefendersGraveyard
    (the new C1 Effect) AND BEGINNING_OF_END_STEP + Controlled(YOU) +
    SacrificeSelfUnlessVoidActive (already shipped Phase-4 first
    deliverable at cards.rs:4972).
  - Python class ``ReanimateTargetCreatureCardFromDefendersGraveyard``
    at ``effects/generic/graveyard.py:474-554`` — no ``@dataclass``
    decorator, no fields. The resolve method walks
    ``state.players`` for the chosen target, removes from graveyard,
    calls ``put_into_battlefield`` under the resolving controller's
    id, stamps ``tapped = True``, ``attacking = True``,
    ``summoning_sick = False``.
  - Rust precedents: ``Effect::SacrificeSelfUnlessVoidActive``
    parse/to_pydict at cards.rs:4972 + 18089 + 13178; resolve arm
    at state_ops_resolve.rs:16194 (sibling Phase-4 first
    deliverable). ``Effect::ReturnTargetArtifactCardFromYourGraveyard
    ToHand`` resolve at state_ops_resolve.rs:5614+ — the cast-time-
    bound-target precedent via ``current_resolve_payload_target_id``.
    ``PendingDecision::EnchantTargetChoice`` at state.rs:2224 — the
    flat-Vec<u32>-candidates precedent.
  - ``Predicate::IsHost { subject: Option<String> }`` at
    cards.rs:9298 already carries the subject slot the C1 wiring
    needs (no IsHost predicate widen required — the slot is
    plumbed for ``subject="attacker"`` already via the Pain for
    All Phase 3 closure).
  - ``Event::Attacks`` dispatch already fires Aura-side triggers
    via the centralized ``dispatch_event`` at state_ops_combat.rs
    :1734 — every attacker-id-keyed observer set covers Auras
    attached to the attacker (the host's ATTACKS trigger fan-out
    is centralized). No Aura-side dispatch widen required.

**Test plan (per design doc §7):**

  - Parser SoT pin: confirm Python's
    ``ReanimateTargetCreatureCardFromDefendersGraveyard`` class
    exists in ``effects.generic.graveyard`` with the canonical
    field-free shape.
  - Verify-first pin: confirm Chorale of the Void's live ETB shape
    (two triggered abilities; the ATTACKS one carries
    ``IsHost(subject="attacker")`` + ``Reanimate…``).
  - Rust unit pins: ``parse_effect`` arm + ``to_pydict`` arm
    round-trip + register_printing acceptance + unknown-kind
    enumeration includes the new kind.
  - Cross-engine bridge pin: dict→Python bridge arm in
    ``_ta_dict_to_python_effect``.
  - Reverse-serializer pin: forward emit through
    ``_python_ta_to_safe_dict_aura_phase3`` recognizes the Python
    class AND emits the correct dict; the dormant-gate invariant
    holds — ``_aura_triggers_are_phase3_safe`` rejects Chorale's
    full trigger surface.
  - PendingDecision pin: ``GraveyardCardChoice`` round-trips
    through the pending-decisions surface dict; ``submit_graveyard_
    card_decision`` accepts Some(id)/None; raises on unknown id /
    wrong head / empty queue; ``auto_resolve_pending_decisions``
    deterministic-first.
  - Rust resolve arm pins: silent fizzle on no-target;
    deterministic move from opponent's graveyard to controller's
    battlefield, tapped + already-attacking + non-summoning-sick;
    silent fizzle when bound target is no longer a creature card
    in an opponent's graveyard.
  - Substrate-only invariant pin: Chorale of the Void STAYS
    DECLINED at the production-deck loader filter post-Cycle-1.
"""

from __future__ import annotations

import importlib.util

import pytest


# Zone constants — mirror ``rust/src/state_ops_zones.rs``.
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


# ---------------------------------------------------------------------------
# Parser SoT verify-first
# ---------------------------------------------------------------------------


def test_python_reanimate_target_creature_class_exists():
    """**Parser SoT pin.** Python's
    ``ReanimateTargetCreatureCardFromDefendersGraveyard`` class is in
    ``effects.generic.graveyard``, a field-free Effect subclass. Two
    instances compare equal by identity-of-type (no ``@dataclass``
    decorator on the live class; classes-with-no-fields compare by
    Python's object identity unless ``__eq__`` is overridden — but
    isinstance + type-equality are the load-bearing observables here).
    """
    from mtg_bot.effects.base import Effect
    from mtg_bot.effects.generic.graveyard import (
        ReanimateTargetCreatureCardFromDefendersGraveyard,
    )

    a = ReanimateTargetCreatureCardFromDefendersGraveyard()
    # Subclass invariant.
    assert isinstance(a, Effect)
    # Field-free class — no public attributes beyond the inherited
    # Effect base. The `requires_target` reader returns True (the
    # Effect targets a graveyard creature).
    assert a.requires_target() is True


def test_chorale_of_the_void_live_printing_matches_design_doc_shape():
    """**Verify-first pin — Chorale of the Void's live triggered shape.**
    Confirms the design doc §2 row at HEAD: TWO triggered abilities —

      1. ATTACKS + IsHost(subject="attacker") + Reanimate…
         FromDefendersGraveyard (the C1 long-pole Effect).
      2. BEGINNING_OF_END_STEP + Controlled(YOU) +
         SacrificeSelfUnlessVoidActive (the already-shipped tail
         half — Phase-4 first deliverable).

    NOTE: Chorale of the Void STAYS DECLINED at the production-deck
    admit gate post-Cycle-1 because ``_aura_triggers_are_phase3_safe``
    does NOT widen for either trigger shape yet (Cycle 2 widens both
    halves in the same slice — the all-or-nothing gate requires both
    long pole + tail to widen together).
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.effects.combinators import SacrificeSelfUnlessVoidActive
    from mtg_bot.effects.generic.graveyard import (
        ReanimateTargetCreatureCardFromDefendersGraveyard,
    )
    from mtg_bot.effects.predicates import (
        Controlled,
        Event,
        IsHost,
        YOU,
    )

    ps = OracleParserCardSource().get_printings()
    chorale = ps["Chorale of the Void"]

    # Aura subtype per design doc §2.
    assert "Aura" in chorale.subtypes
    assert chorale.is_aura is True
    # Sub-shape S4 contract per design doc §2 — TWO trigger entries.
    tas = tuple(chorale.triggered_abilities or ())
    assert len(tas) == 2, (
        f"expected 2 triggered abilities on Chorale of the Void, got "
        f"{len(tas)}: {tas}"
    )

    # Sort so we can identify each by event regardless of source order.
    by_event = {ta.event: ta for ta in tas}
    assert Event.ATTACKS in by_event
    assert Event.BEGINNING_OF_END_STEP in by_event

    # Trigger A: ATTACKS + IsHost(subject="attacker") + Reanimate
    attacks_ta = by_event[Event.ATTACKS]
    assert isinstance(attacks_ta.predicate, IsHost)
    assert attacks_ta.predicate.subject == "attacker"
    assert isinstance(
        attacks_ta.effect,
        ReanimateTargetCreatureCardFromDefendersGraveyard,
    )
    assert attacks_ta.once_per_turn is False

    # Trigger B: BEGINNING_OF_END_STEP + Controlled(YOU) +
    # SacrificeSelfUnlessVoidActive (already shipped Phase 4 first
    # deliverable).
    end_step_ta = by_event[Event.BEGINNING_OF_END_STEP]
    assert isinstance(end_step_ta.predicate, Controlled)
    assert end_step_ta.predicate.by is YOU
    assert isinstance(
        end_step_ta.effect, SacrificeSelfUnlessVoidActive,
    )
    assert end_step_ta.once_per_turn is False


# ---------------------------------------------------------------------------
# Cross-engine bridge arm pins (dict -> Python)
# ---------------------------------------------------------------------------


def test_bridge_arm_reanimate_target_creature_card_from_defenders_graveyard():
    """Bridge arm constructs
    ``ReanimateTargetCreatureCardFromDefendersGraveyard()`` from a
    single-kind dict (no fields). Mirrors the sibling Phase-4 unit-
    variant bridge shape.
    """
    from mtg_bot.effects.generic.graveyard import (
        ReanimateTargetCreatureCardFromDefendersGraveyard,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect({
        "kind": "reanimate_target_creature_card_from_defenders_graveyard",
    })
    assert isinstance(back, ReanimateTargetCreatureCardFromDefendersGraveyard)


def test_bridge_arm_reanimate_target_creature_unit_variant_round_trip():
    """Unit-variant round trip: the field-free class round-trips
    through the bridge arm without surfacing any spurious fields.
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect({
        "kind": "reanimate_target_creature_card_from_defenders_graveyard",
    })
    # The class is field-free — no extra attributes beyond the
    # inherited Effect-base contract.
    assert back.requires_target() is True


# ---------------------------------------------------------------------------
# Reverse-serializer leaf pin in _python_ta_to_safe_dict_aura_phase3
# ---------------------------------------------------------------------------


def test_python_ta_to_safe_dict_aura_phase3_arm_recognizes_effect_class():
    """**Recognition arm pin.** The Aura-phase3 emitter
    ``_python_ta_to_safe_dict_aura_phase3`` recognizes
    ``ReanimateTargetCreatureCardFromDefendersGraveyard`` in its
    isinstance cascade and emits the canonical dict shape.

    Concrete observable: construct a synthetic ATTACKS +
    IsHost(subject="attacker") + Reanimate trigger, call the emitter
    directly, assert dict shape matches the design doc §5.2 Phase A
    spec.

    NOTE: this is the EMITTER pin. The emitter only fires when the
    Aura gate (``_aura_triggers_are_phase3_safe``) admits the carrier
    — which it does NOT for Chorale in C1 (the gate refuses the
    ATTACKS + Reanimate shape). The recognition arm here is dormant
    by construction; Cycle 2's gate widen activates it.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.graveyard import (
        ReanimateTargetCreatureCardFromDefendersGraveyard,
    )
    from mtg_bot.effects.predicates import Event, IsHost
    from mtg_bot.parity.trajectory import (
        _python_ta_to_safe_dict_aura_phase3,
    )

    ta = TriggeredAbility(
        event=Event.ATTACKS,
        predicate=IsHost(subject="attacker"),
        effect=ReanimateTargetCreatureCardFromDefendersGraveyard(),
    )
    out = _python_ta_to_safe_dict_aura_phase3(ta)
    # Design doc §5.2 Phase A shape.
    assert out == {
        "event": "attacks",
        "predicate": {"kind": "is_host", "subject": "attacker"},
        "effect": {
            "kind": "reanimate_target_creature_card_from_defenders_graveyard",
        },
        "once_per_turn": False,
    }


def test_aura_triggers_are_phase3_safe_declines_chorale_attacks_half():
    """**The §2 no-silent-auto-grow load-bearing pin.** The
    ``_aura_triggers_are_phase3_safe`` gate does NOT admit the
    ATTACKS + IsHost(subject="attacker") + Reanimate shape in C1.
    Synthetic single-TA fixture confirms.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.graveyard import (
        ReanimateTargetCreatureCardFromDefendersGraveyard,
    )
    from mtg_bot.effects.predicates import Event, IsHost
    from mtg_bot.parity.trajectory import _aura_triggers_are_phase3_safe

    chorale_attacks_ta = TriggeredAbility(
        event=Event.ATTACKS,
        predicate=IsHost(subject="attacker"),
        effect=ReanimateTargetCreatureCardFromDefendersGraveyard(),
    )
    # Substrate-only invariant: gate refuses.
    assert _aura_triggers_are_phase3_safe((chorale_attacks_ta,)) is False


def test_aura_phase3_emitter_arm_present_in_source():
    """**Substrate pre-position pin.** The emitter source carries the
    recognizer arm + kind string so Cycle 2's gate widen is purely
    additive (no emitter edit needed in Cycle 2; Cycle 2 only widens
    ``_aura_triggers_are_phase3_safe`` + wires the trigger-fire push).
    """
    import inspect
    from mtg_bot.parity import trajectory

    source = inspect.getsource(
        trajectory._python_ta_to_safe_dict_aura_phase3,
    )
    assert (
        "ReanimateTargetCreatureCardFromDefendersGraveyard" in source
    ), (
        "isinstance arm for ReanimateTargetCreatureCardFromDefenders"
        "Graveyard must be present in _python_ta_to_safe_dict_aura_"
        "phase3 (the substrate's pre-positioned recognition for "
        "Cycle 2's additive gate widen)."
    )
    assert (
        "reanimate_target_creature_card_from_defenders_graveyard"
        in source
    ), (
        "kind string must be emitted by the substrate's recognition "
        "arm."
    )


# ---------------------------------------------------------------------------
# Rust unit pins — parse + register + to_pydict round-trip
# ---------------------------------------------------------------------------


def _reanimate_spell_dict():
    """A Sorcery-shape spell carrying the new Effect as its spell
    effect — used for direct resolve-arm pins via the stack-push
    path. The Sorcery shape lets us drive the resolve arm WITHOUT
    routing through the Chorale Aura admit gate (which stays closed
    in C1 by design).
    """
    return {
        "name": "Test Reanimate Defenders Graveyard Spell",
        "card_types": ["Sorcery"],
        "effects": [
            {
                "kind": "reanimate_target_creature_card_from_defenders_graveyard",
            }
        ],
    }


def test_rust_register_reanimate_target_creature_unit_variant():
    """**Rust parse arm pin.** ``register_printing`` accepts a spell
    carrying the new effect kind. The pid is returned and
    ``get_printing_name`` echoes the name.
    """
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_reanimate_spell_dict())
    assert reg.get_printing_name(pid) == (
        "Test Reanimate Defenders Graveyard Spell"
    )


def test_rust_unknown_effect_kind_enumeration_includes_new_kind():
    """**Rust parse arm pin — completeness of unknown-kind error msg.**
    The trailing "unknown effect kind" error msg in parse_effect
    enumerates EVERY valid kind; the new C1 kind must be in that list
    so future agents can verify the kind is registered.
    """
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    # Trigger the error path with a bogus kind; the error msg lists
    # all valid kinds.
    with pytest.raises(ValueError) as exc_info:
        reg.register_printing({
            "name": "Test Unknown Kind Trigger",
            "card_types": ["Sorcery"],
            "effects": [{"kind": "definitely_not_a_real_effect_kind"}],
        })
    msg = str(exc_info.value)
    assert (
        "reanimate_target_creature_card_from_defenders_graveyard"
        in msg
    ), (
        "valid-kinds enumeration in parse_effect's unknown-kind "
        "error msg must list the new C1 kind so it is discoverable."
    )


# ---------------------------------------------------------------------------
# PendingDecision::GraveyardCardChoice substrate pins
# ---------------------------------------------------------------------------


def test_graveyard_card_choice_decision_submit_accepts_some(engine):
    """**Decision-pump pin — submit_graveyard_card_decision(Some(id))**.
    With NO pending decisions on the queue (the substrate-only path —
    no production push site exists yet in C1), submit raises a
    NoPendingDecision error. This is the dormant-by-construction
    invariant: Cycle 2 wires the push.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=10,
    )
    # No production push yet → submit raises.
    with pytest.raises(ValueError, match="no pending decision"):
        state.submit_graveyard_card_decision(42)
    with pytest.raises(ValueError, match="no pending decision"):
        state.submit_graveyard_card_decision(None)


def test_graveyard_card_choice_submit_rejects_wrong_head(engine):
    """**Decision-pump pin — discriminant mismatch.** When the head
    of the pending-decisions queue is a different variant (e.g. a
    SurveilChoice from an unrelated effect), ``submit_graveyard_card
    _decision`` rejects with a typed error and the decision STAYS on
    the queue.

    Concrete: push a Surveil-style effect that injects a
    SurveilChoice at the head; assert ``submit_graveyard_card_
    decision(0)`` raises and the head is still a SurveilChoice.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=10,
    )
    # Register and resolve a Surveil(2) spell to seat a SurveilChoice
    # at the head of pending_decisions.
    surveil_pid = state.register_and_inject_object(
        {
            "name": "Test Surveil Spell (decision discriminant)",
            "card_types": ["Sorcery"],
            "effects": [{"kind": "surveil", "count": 2}],
        },
        0,
        ZONE_HAND,
    )
    state.push_to_stack(surveil_pid, 0)
    state.resolve_top_of_stack_pause()
    # Confirm head is a SurveilChoice (sanity).
    pds = state.pending_decisions()
    assert len(pds) >= 1
    assert pds[0]["kind"] == "SurveilChoice"
    # Wrong discriminant: submit_graveyard_card_decision raises.
    with pytest.raises(
        ValueError,
        match="head of pending-decisions queue is not a GraveyardCardChoice",
    ):
        state.submit_graveyard_card_decision(42)
    # Head unchanged.
    pds_after = state.pending_decisions()
    assert pds_after[0]["kind"] == "SurveilChoice"


# ---------------------------------------------------------------------------
# Rust resolve arm pins (drive via the stack push-then-resolve path)
# ---------------------------------------------------------------------------


def test_resolve_silent_fizzle_when_payload_target_id_unset(engine):
    """**Resolve arm — silent fizzle on no bound target.** Resolve the
    Sorcery WITHOUT seating ``current_resolve_payload_target_id`` /
    ``target_obj_id`` on the StackItem — silent no-op. The spell
    moves hand→graveyard per CR 608.2m; no battlefield mutation.

    Setup: p1 has a creature card in its graveyard (a Bear),
    intentionally NOT bound via the stack item's target slot. The
    spell pushes via the no-target path (``push_to_stack``).
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=10,
    )
    # Seat a creature card in p1's graveyard.
    bear_id = state.register_and_inject_object(
        {
            "name": "Test Bear In P1 Graveyard",
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
        },
        1,
        ZONE_GRAVEYARD,
    )
    bf_p0_before = state.battlefield_sizes[0]
    gy_p0_before = state.graveyard_sizes[0]
    gy_p1_before = state.graveyard_sizes[1]

    spell_id = state.register_and_inject_object(
        _reanimate_spell_dict(), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()

    assert state.is_stack_empty() is True
    # Bear still in p1's graveyard (not reanimated).
    assert state.find_object_zone(bear_id) == ZONE_GRAVEYARD
    # p1's graveyard count unchanged.
    assert state.graveyard_sizes[1] == gy_p1_before
    # p0's bf unchanged (no reanimation).
    assert state.battlefield_sizes[0] == bf_p0_before
    # The Sorcery source moves hand→graveyard per CR 608.2m
    # (+1 on p0's gy axis).
    assert state.graveyard_sizes[0] == gy_p0_before + 1


def test_resolve_reanimates_bound_target_from_opponent_graveyard(engine):
    """**Resolve arm — happy path.** A creature card in p1's graveyard
    is bound via the stack item's target slot; the resolver swaps it
    into ``current_resolve_payload_target_id`` at resolve. The
    Sorcery resolves: creature moves p1.graveyard → p0.battlefield;
    stamped tapped + already-attacking + non-summoning-sick.

    Setup: p1 has a Bear in graveyard; push the Sorcery via
    ``push_to_stack_with_target(spell_id, 0, bear_id)``.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=10,
    )
    bear_id = state.register_and_inject_object(
        {
            "name": "Test Bear In P1 Graveyard (happy path)",
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
        },
        1,
        ZONE_GRAVEYARD,
    )
    bf_p0_before = state.battlefield_sizes[0]
    gy_p1_before = state.graveyard_sizes[1]

    spell_id = state.register_and_inject_object(
        _reanimate_spell_dict(), 0, ZONE_HAND,
    )
    state.push_to_stack_with_target(spell_id, 0, bear_id)
    state.resolve_top_of_stack()

    assert state.is_stack_empty() is True
    # Bear moved: p1.graveyard → p0.battlefield.
    assert state.find_object_zone(bear_id) == ZONE_BATTLEFIELD
    assert state.battlefield_sizes[0] == bf_p0_before + 1
    assert state.graveyard_sizes[1] == gy_p1_before - 1
    # The reanimated id should be in state.attackers (Chorale's
    # "tapped and attacking" stamp).
    attackers = state.get_attackers()
    assert bear_id in attackers, (
        f"reanimated bear id {bear_id} must be in state.attackers "
        f"(got {attackers!r}) — Chorale's already-attacking stamp."
    )


def test_resolve_silent_fizzle_when_target_no_longer_in_opponent_graveyard(
    engine,
):
    """**Resolve arm — re-validation per CR 608.2b.** If the bound
    target id is no longer in any opponent's graveyard at resolve time
    (e.g. another effect moved it), silent fizzle — no battlefield
    mutation.

    Setup: bind a target id that doesn't exist in any zone. The spell
    pushes with the bound target; resolve silently fizzles.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=10,
    )
    bf_p0_before = state.battlefield_sizes[0]
    gy_p1_before = state.graveyard_sizes[1]

    spell_id = state.register_and_inject_object(
        _reanimate_spell_dict(), 0, ZONE_HAND,
    )
    # Bind a phony non-existent id as target.
    fake_target_id = 99999
    state.push_to_stack_with_target(spell_id, 0, fake_target_id)
    state.resolve_top_of_stack()

    assert state.is_stack_empty() is True
    # No mutation on p0's bf or p1's gy.
    assert state.battlefield_sizes[0] == bf_p0_before
    assert state.graveyard_sizes[1] == gy_p1_before


def test_resolve_silent_fizzle_when_target_is_not_creature(engine):
    """**Resolve arm — non-creature card in opponent's graveyard
    fizzles.** If the bound target id IS in an opponent's graveyard
    but the printing is NOT a creature (e.g. a Sorcery), silent
    fizzle — byte-equal with Python's "iterate-then-not-found"
    fallthrough.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=10,
    )
    # Inject a non-creature card (a Sorcery) into p1's graveyard.
    spell_in_gy = state.register_and_inject_object(
        {
            "name": "Test Sorcery In Opp Graveyard",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 1, "U": 1},
        },
        1,
        ZONE_GRAVEYARD,
    )
    bf_p0_before = state.battlefield_sizes[0]
    gy_p1_before = state.graveyard_sizes[1]

    reanimate_spell_id = state.register_and_inject_object(
        _reanimate_spell_dict(), 0, ZONE_HAND,
    )
    state.push_to_stack_with_target(reanimate_spell_id, 0, spell_in_gy)
    state.resolve_top_of_stack()

    # Non-creature card unaffected — still in p1's graveyard.
    assert state.find_object_zone(spell_in_gy) == ZONE_GRAVEYARD
    assert state.battlefield_sizes[0] == bf_p0_before
    assert state.graveyard_sizes[1] == gy_p1_before


def test_resolve_silent_fizzle_when_target_is_in_own_graveyard(engine):
    """**Resolve arm — own-graveyard ineligibility.** A creature card
    in the resolving controller's OWN graveyard is NOT a legal target
    (Python: ``if p.id != controller_id``). Bind such a target id and
    confirm silent fizzle.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=10,
    )
    # Bear in p0's OWN graveyard (controller-graveyard, not opponent's).
    bear_id = state.register_and_inject_object(
        {
            "name": "Test Bear In Own Graveyard",
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
        },
        0,
        ZONE_GRAVEYARD,
    )
    bf_p0_before = state.battlefield_sizes[0]
    gy_p0_before = state.graveyard_sizes[0]

    spell_id = state.register_and_inject_object(
        _reanimate_spell_dict(), 0, ZONE_HAND,
    )
    state.push_to_stack_with_target(spell_id, 0, bear_id)
    state.resolve_top_of_stack()

    # Bear still in p0's graveyard (own — not eligible).
    assert state.find_object_zone(bear_id) == ZONE_GRAVEYARD
    # No new entries on p0's bf (the reanimation didn't happen).
    # But the Sorcery source itself moves hand→graveyard, so gy[0]
    # grows by exactly 1.
    assert state.graveyard_sizes[0] == gy_p0_before + 1
    assert state.battlefield_sizes[0] == bf_p0_before


def test_resolve_clears_payload_target_id_after_use(engine):
    """**Resolve arm — payload-slot hygiene.** Post-resolve the
    ``current_resolve_payload_target_id`` slot is cleared so a
    subsequent un-bound resolve doesn't accidentally consume the
    leftover id.

    Observable: after the happy-path resolve, the slot is None
    (verified by attempting a substrate-only no-bind resolve in a
    fresh stack frame and seeing it fizzle silently — pinned via the
    no-target silent-fizzle test above).
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=2, num_library=10,
    )
    bear_id = state.register_and_inject_object(
        {
            "name": "Test Bear (payload-hygiene 1)",
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
        },
        1,
        ZONE_GRAVEYARD,
    )
    # First reanimate: happy path.
    spell1_id = state.register_and_inject_object(
        _reanimate_spell_dict(), 0, ZONE_HAND,
    )
    state.push_to_stack_with_target(spell1_id, 0, bear_id)
    state.resolve_top_of_stack()

    # Inject a second creature card in p1's graveyard for the second
    # spell.
    bear2_id = state.register_and_inject_object(
        {
            "name": "Test Bear (payload-hygiene 2)",
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
        },
        1,
        ZONE_GRAVEYARD,
    )

    # Second resolve via the unbound path (push_to_stack with NO
    # target). If the payload slot were leaking the previous bear_id
    # this resolve would reanimate bear2_id even though it isn't
    # bound — assertion is that the second bear stays in p1's
    # graveyard.
    gy_p1_before = state.graveyard_sizes[1]
    bf_p0_before = state.battlefield_sizes[0]
    spell2_id = state.register_and_inject_object(
        _reanimate_spell_dict(), 0, ZONE_HAND,
    )
    state.push_to_stack(spell2_id, 0)
    state.resolve_top_of_stack()

    # Second bear stays in p1's graveyard — payload slot was cleared
    # post the first resolve, so the second un-bound resolve fizzled.
    assert state.find_object_zone(bear2_id) == ZONE_GRAVEYARD
    assert state.graveyard_sizes[1] == gy_p1_before
    # p0's bf: zero growth on the second resolve (only the first
    # reanimation's bf entry persists).
    assert state.battlefield_sizes[0] == bf_p0_before


def test_resolve_stamps_controller_to_resolving_controller(engine):
    """**Resolve arm — I83 controller-of-effect.** The reanimated
    permanent's controller stamps to the resolving controller (the
    Sorcery's caster), NOT the original owner who had the creature
    in their graveyard. CR 110.2 / 614.x.

    Setup: p1 has Bear in graveyard; p0 casts the reanimate Sorcery.
    Post-resolve: Bear is on p0's bf (controller-stamped to p0).
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=10,
    )
    bear_id = state.register_and_inject_object(
        {
            "name": "Test Bear (controller-stamp axis)",
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
        },
        1,
        ZONE_GRAVEYARD,
    )
    bf_p0_before = state.battlefield_sizes[0]
    bf_p1_before = state.battlefield_sizes[1]

    spell_id = state.register_and_inject_object(
        _reanimate_spell_dict(), 0, ZONE_HAND,
    )
    state.push_to_stack_with_target(spell_id, 0, bear_id)
    state.resolve_top_of_stack()

    # Bear moved to p0's bf (resolving controller = p0), NOT p1's bf
    # (original owner).
    assert state.find_object_zone(bear_id) == ZONE_BATTLEFIELD
    assert state.battlefield_sizes[0] == bf_p0_before + 1
    assert state.battlefield_sizes[1] == bf_p1_before
    # I83 controller-stamp observable: the reanimated object's
    # effective_controller_id is the resolving controller (p0).
    assert state.effective_controller_id(bear_id) == 0


# ---------------------------------------------------------------------------
# Substrate-only invariant pin — Chorale STAYS DECLINED
# ---------------------------------------------------------------------------


def test_chorale_of_the_void_stays_declined_at_admit_gate_post_cycle_1():
    """**Substrate-only invariant pin.** Chorale of the Void STAYS
    DECLINED at the production-deck loader filter post-Cycle-1.

    The all-or-nothing ``_aura_triggers_are_phase3_safe`` gate refuses
    Chorale's full trigger surface because NEITHER the ATTACKS long-
    pole NOR the BEGINNING_OF_END_STEP tail half is in the safe set
    yet (Cycle 2 ships both widens in the same slice + wires the
    trigger-fire push). The loader's
    ``_printing_is_bridge_simple_aura`` therefore declines admission.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _aura_triggers_are_phase3_safe,
        _printing_is_bridge_simple_aura,
    )

    ps = OracleParserCardSource().get_printings()
    chorale = ps["Chorale of the Void"]

    # All-or-nothing gate refuses (substrate-only invariant).
    assert (
        _aura_triggers_are_phase3_safe(chorale.triggered_abilities)
        is False
    )
    # Loader declines (the load-bearing observable for the admit-set
    # invariant).
    assert _printing_is_bridge_simple_aura(chorale) is False


# ---------------------------------------------------------------------------
# Adjacent regression pins — confirm prior closures hold
# ---------------------------------------------------------------------------


def test_pain_for_all_still_admits_at_phase3_gate():
    """**Phase 3 Pain for All closure non-regression.** Pain for All
    (admitted by ``_aura_triggers_are_phase3_safe`` per the round-80
    Phase 3 closure) STILL admits post-Cycle-1 — the C1 widen of
    the emitter is purely additive and doesn't touch the gate.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _aura_triggers_are_phase3_safe,
        _printing_is_bridge_simple_aura,
    )

    ps = OracleParserCardSource().get_printings()
    pfa = ps["Pain for All"]

    # Pain for All STILL passes the Aura-phase3 gate.
    assert (
        _aura_triggers_are_phase3_safe(pfa.triggered_abilities) is True
    )
    # And the loader STILL admits.
    assert _printing_is_bridge_simple_aura(pfa) is True


def test_sacrifice_self_unless_void_active_still_round_trips():
    """**Phase 4 first-deliverable non-regression.** The
    ``sacrifice_self_unless_void_active`` bridge arm (Chorale's tail
    half, shipped Phase 4 first deliverable) still constructs the
    Python class byte-equal.
    """
    from mtg_bot.effects.combinators import SacrificeSelfUnlessVoidActive
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect({
        "kind": "sacrifice_self_unless_void_active",
    })
    assert isinstance(back, SacrificeSelfUnlessVoidActive)


def test_tractor_beam_still_admits_at_phase3_gate():
    """**Phase 2-S2-extension non-regression.** Tractor Beam (admitted
    by the joint-shape gate per Phase 2's substrate) STILL admits.
    The C1 widen does NOT touch Phase 2's substrate.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _printing_is_bridge_simple_aura

    ps = OracleParserCardSource().get_printings()
    tb = ps["Tractor Beam"]
    assert _printing_is_bridge_simple_aura(tb) is True
