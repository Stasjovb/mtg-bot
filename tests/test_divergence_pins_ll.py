"""Divergence-pin tests: batch LL (probe-batch-ll).

Each test is named ``test_cross_engine_real_eoe_<slug>_*_divergence_pin``
and ASSERTS the CURRENT divergent behavior rather than parity.  The
PROBED-tier detector excludes ``*_divergence_pin`` functions, so these
tests grow the test surface without touching the PROBED metric.

Pinned bugs
-----------

Pin 1 -- ``requires_own_creature_power_at_least`` activation-cost bridge gap
(Python ``ActivationCost`` field not in Rust struct + bridge ``_AA_COST_BOOL_KEYS``).

    Python's ``ActivationCost`` dataclass (``effects/base.py:394``) has a
    field ``requires_own_creature_power_at_least: int = 0`` (default 0 =
    no gate active).  When non-zero the legal-actions loop in
    ``legal.py:732-742`` skips any activation for which the controller does
    not control a creature whose effective power is >= the threshold.
    This gate is used by Bonders' Enclave-style land abilities ("Activate
    only if you control a creature with power 4 or greater").

    The cross-engine activation-cost bridge (``_aa_dict_to_python_activation_
    cost`` at ``cross_engine.py:9296``) maintains a whitelist of recognized
    bool-key names in ``_AA_COST_BOOL_KEYS`` (``cross_engine.py:9282``).
    ``requires_own_creature_power_at_least`` is NOT in that whitelist; it is
    an int field, not a bool, and the bridge's accepted-key set covers only
    the fields that are structural bools in Rust's ``ActivationCost`` struct.

    Rust's ``ActivationCost`` struct (``rust/src/cards.rs:4454``) does not
    have a ``requires_own_creature_power_at_least`` field at all -- the
    power-gate logic exists exclusively in Python's ``legal.py``.  The
    field is absent from the Rust struct, absent from the bridge whitelist,
    and therefore unrepresentable in any Rust-sourced ``ActivateAbility``
    dict that flows through ``_aa_dict_to_python_activation_cost``.

    Observable consequence:
      Any Rust-sourced card whose ``parse_activation_cost`` dict includes a
      ``requires_own_creature_power_at_least`` key would cause
      ``_aa_dict_to_python_activation_cost`` to raise ``ValueError`` with
      the "unsupported activation_cost key(s)" message rather than silently
      translating to a Python ``ActivationCost`` that enforces the gate.
      Without the gate in the Rust legal-actions emission, Rust would emit
      the activation even when the activating player controls no creature
      with power >= the threshold.

    Python class exists and is correct:
      ``ActivationCost.requires_own_creature_power_at_least`` (``base.py:394``)
      is read by ``legal.py:732-742``.  The Python gate is correctly
      implemented; the bug is that the bridge has no arm to translate the
      int field from a Rust-origin dict, and Rust's struct omits the field
      entirely so no Rust-built card can emit the gate.

    Closure path:
      Add ``requires_own_creature_power_at_least`` support to the Rust
      ``ActivationCost`` struct and its ``parse_activation_cost`` parser,
      extend ``_AA_COST_BOOL_KEYS`` (or add a separate int-key table for
      non-bool cost fields), and add the corresponding gate to Rust's
      legal-actions emission loop (``state_ops_legal.rs``).  When all three
      land, the ``ValueError`` will no longer fire, and a Rust-sourced
      Bonders' Enclave-shaped card will correctly withhold the activation
      when the threshold is not met.

    This pin is pure Python (no Rust extension required).

Pin 2 -- ``subject_is_artifact`` predicate with IS_CAST event: ``Subject(slot=None)``
resolves to ``None`` and predicate evaluates false (AA drop).

    When the cross-engine bridge translates a predicate dict with
    ``kind == "subject_is_artifact"`` it unconditionally returns
    ``Subject(slot=None, inner=IsArtifact())``
    (``cross_engine.py:8751-8752``).

    The ``Subject.matches`` implementation (``effects/predicates.py:368-372``)
    calls ``_resolve_subject(subjects, self.slot)``.  ``_resolve_subject``
    (``predicates.py:340-350``) short-circuits to the event's only slot when
    ``slot=None`` AND ``len(subjects) == 1`` (the single-subject optimisation
    for ENTERS / DIES etc.).

    The ``IS_CAST`` event dispatches with TWO subjects: ``"spell"`` (the card
    being cast) and ``"controller"`` (the casting player) -- see
    ``actions.py:1796-1798`` and the comment at ``triggers.py:729``.
    Because ``len(subjects) == 2`` (not 1), ``_resolve_subject`` returns
    ``None``, and ``Subject.matches`` short-circuits to ``False``.

    The correct slot for IS_CAST artifact predicates is ``"spell"`` -- the
    card-parser spells this ``Subject("spell", IsArtifact())`` (see
    ``triggers.py:735`` for the "you cast an artifact spell" shape used by
    Pinnacle Emissary).  The bridge's ``subject_is_artifact`` arm uses
    ``slot=None``, which is correct for single-subject events (ENTERS) but
    wrong for IS_CAST's two-subject dispatch.

    Observable consequence:
      A Rust-sourced card whose triggered-ability dict carries
      ``event="cast"`` and ``predicate={"kind": "subject_is_artifact"}``
      would translate to a ``TriggeredAbility`` whose predicate ALWAYS
      evaluates ``False`` -- the trigger would never fire when an artifact
      spell is cast.

    What's right:
      The bridge should detect when ``subject_is_artifact`` is paired with
      ``event="cast"`` and return ``Subject("spell", IsArtifact())`` instead
      of ``Subject(None, IsArtifact())``.  Alternatively, the bridge could
      require an explicit slot key in the predicate dict and use it directly.

    CR reference: CR 603.1 -- a triggered ability triggers whenever the
    condition is met; if the predicate never evaluates true because of a
    wrong slot lookup, the trigger is silently suppressed.

    This pin is pure Python (no Rust extension required).

Pin 3 -- ``beginning_of_end_step`` event NOT wired in triggered-ability bridge
(cross-engine bridge event gap; 51 EoE cards blocked).

    The cross-engine triggered-ability bridge function
    ``_ta_dict_to_python_triggered_ability`` (``cross_engine.py:8807``)
    converts event-string values into Python ``Event`` enum members.  The
    elif chain at ``cross_engine.py:8819-8855`` recognises only six event
    strings: ``"enters"``, ``"dies"``, ``"cast"``, ``"attacks"``,
    ``"blocks"``, ``"leaves_battlefield"``, and ``"becomes_tapped"``.

    Python's ``Event`` enum (``effects/predicates.py``) has 24 members
    including ``Event.BEGINNING_OF_END_STEP``.  The string value
    ``"beginning_of_end_step"`` is not in the bridge's elif chain; passing
    a triggered-ability dict with that event value causes the function to
    fall through to the final:

        raise ValueError(
            "cross_engine triggered_abilities bridge: event "
            "'beginning_of_end_step' is not yet wired"
        )

    Observable consequence:
      51 EoE cards carry "At the beginning of [the/your] end step, ..."
      triggered abilities.  Any Rust-sourced token or carrier that emits a
      ``triggered_abilities`` dict with ``event="beginning_of_end_step"``
      cannot be routed through the bridge.  The probe that would exercise
      such a card would crash at bridge-translation time rather than
      producing diffs.

    Closure path:
      Add an ``elif event_str == "beginning_of_end_step":`` arm that maps
      to ``Event.BEGINNING_OF_END_STEP``.  Also add ``"beginning_of_upkeep"``
      (``Event.BEGINNING_OF_UPKEEP``) and ``"beginning_of_combat"``
      (``Event.BEGINNING_OF_COMBAT``) in the same pass -- they share the
      same gap and follow the same single-arm pattern.  When those arms land,
      the ``ValueError`` will no longer be raised, flipping this sentinel to
      a failure that signals the pin should be updated.

    This pin is pure Python (no Rust extension required).

Dropped pins
------------

  * Endless Sands AA[0] ``ExileTargetCreatureUntilSourceLeaves``
    ``yours_only=True`` semantic mismatch (batch HH / AA):  Already
    documented in the batch-HH worklog.  Not re-pinned here.

  * MovePlusOneCounterBetweenPermanentsYouControl 2-target diffs=[]
    false-positive (batch EE): already documented in
    ``test_probe_activated_abilities_ee.py:76-84``.  Not re-pinned here.

  * Cast event LIFO-ordering divergence (batch AA finding): requires a
    real game trajectory with IS_CAST trigger + stack ordering observable;
    too fragile for a standalone pin at this time.  Dropped.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Pin 1 -- requires_own_creature_power_at_least activation-cost bridge gap
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_requires_own_creature_power_at_least_bridge_gap_divergence_pin():
    """Pin the bridge gap for the ``requires_own_creature_power_at_least``
    activation-cost field.

    Bug location:
      ``src/mtg_bot/parity/cross_engine.py:9282-9293`` --
      ``_AA_COST_BOOL_KEYS`` does not include
      ``"requires_own_creature_power_at_least"``.  The function
      ``_aa_dict_to_python_activation_cost`` raises ``ValueError`` for any
      dict key not in ``{"mana"} | _AA_COST_BOOL_KEYS``.

      ``rust/src/cards.rs:4454-4608`` -- Rust's ``ActivationCost`` struct
      has no ``requires_own_creature_power_at_least`` field.

      ``src/mtg_bot/effects/base.py:394`` -- Python's ``ActivationCost``
      dataclass has ``requires_own_creature_power_at_least: int = 0``; it
      is read by ``legal.py:732-742`` to gate legal activations when the
      controller controls no creature with power >= the threshold.

    What's wrong:
      Python has the field and the legal-gate logic; Rust and the bridge do
      not.  A Rust-sourced card that carries a power-gate activation condition
      can never round-trip through the bridge -- the ValueError fires before
      any effect resolution.

    Closure path:
      Add the field to Rust's ``ActivationCost`` struct, extend
      ``_AA_COST_BOOL_KEYS`` (or add a separate int-cost-key table), and
      add the gate to Rust's legal-actions emission.  When all three land,
      the ValueError will no longer fire here.

    Probe shape:
      1. Assert ``ActivationCost.requires_own_creature_power_at_least``
         exists as a field on the Python dataclass.
      2. Assert that calling ``_aa_dict_to_python_activation_cost`` with a
         dict that includes the key raises ``ValueError`` (bridge gap active).
      3. Assert the raised message mentions the unsupported key.
      4. Assert that calling ``_aa_dict_to_python_activation_cost`` WITHOUT
         the key succeeds (confirming the error is key-specific).

    This pin is pure Python (no Rust extension required).
    """
    import dataclasses

    from mtg_bot.effects.base import ActivationCost
    from mtg_bot.parity.cross_engine import _aa_dict_to_python_activation_cost

    # The Python ActivationCost dataclass has the field.
    field_names = {f.name for f in dataclasses.fields(ActivationCost)}
    assert "requires_own_creature_power_at_least" in field_names, (
        "ActivationCost should have 'requires_own_creature_power_at_least' "
        "as a dataclass field (effects/base.py:394). If this fails, the "
        "field was renamed or removed -- update both this pin and legal.py."
    )

    # The default value is 0 (disabled).
    default_cost = ActivationCost()
    assert default_cost.requires_own_creature_power_at_least == 0, (
        "ActivationCost default for 'requires_own_creature_power_at_least' "
        "should be 0 (no gate active). "
        f"Got {default_cost.requires_own_creature_power_at_least!r}"
    )

    # The bridge raises ValueError for this key -- pin the gap.
    cost_dict_with_power_gate = {"requires_own_creature_power_at_least": 4}
    with pytest.raises(ValueError) as exc_info:
        _aa_dict_to_python_activation_cost(cost_dict_with_power_gate)

    err_msg = str(exc_info.value)
    assert "requires_own_creature_power_at_least" in err_msg, (
        "Bridge gap sentinel: the ValueError message should mention the "
        "unsupported key 'requires_own_creature_power_at_least'. "
        f"Got message: {err_msg!r}"
    )

    # The 'unsupported activation_cost key(s)' phrasing confirms the
    # sentinel fired at the right branch (not some other ValueError).
    assert "unsupported activation_cost" in err_msg, (
        "Bridge gap sentinel: the ValueError message should contain "
        "'unsupported activation_cost' (from _aa_dict_to_python_activation_cost "
        "at cross_engine.py:9324-9332). "
        f"Got message: {err_msg!r}"
    )

    # Sanity: a legal cost dict (no power-gate key) round-trips without error.
    legal_cost_dict = {"tap_self": True}
    legal_cost = _aa_dict_to_python_activation_cost(legal_cost_dict)
    assert legal_cost.tap_self is True, (
        "A legal cost dict {tap_self: True} should translate to "
        "ActivationCost(tap_self=True) without error -- the ValueError is "
        "key-specific to 'requires_own_creature_power_at_least'. "
        f"Got: {legal_cost}"
    )


# ---------------------------------------------------------------------------
# Pin 2 -- subject_is_artifact + IS_CAST: Subject(slot=None) resolves to None
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_is_cast_subject_is_artifact_slot_none_predicate_false_divergence_pin():
    """Pin the divergence: ``subject_is_artifact`` predicate returns False
    on IS_CAST events because ``Subject(slot=None)`` resolves to None when
    the event has two subjects.

    Bug location:
      ``src/mtg_bot/parity/cross_engine.py:8751-8752`` -- the bridge arm
      for ``kind == "subject_is_artifact"`` unconditionally returns
      ``Subject(slot=None, inner=IsArtifact())``.

      ``src/mtg_bot/effects/predicates.py:340-350`` -- ``_resolve_subject``
      returns None when ``slot is None`` and ``len(subjects) != 1``.

      ``src/mtg_bot/actions.py:1796-1798`` -- ``dispatch_event`` fires
      IS_CAST with ``spell=card, controller=player`` (two subjects).

    What's wrong:
      ``Subject(slot=None, ...)`` is designed for single-subject events
      (ENTERS / DIES / ATTACKS) where the unique subject is unambiguous.
      IS_CAST carries two named subjects (``"spell"`` and ``"controller"``);
      ``_resolve_subject`` returns None for len!=1, so Subject.matches
      short-circuits to False.  The predicate NEVER fires on IS_CAST.

    What's right:
      The correct predicate for IS_CAST artifact triggers uses the explicit
      slot ``"spell"``: ``Subject("spell", IsArtifact())``.  The card-parser
      builds this correctly at ``triggers.py:735`` for the "you cast an
      artifact spell" shape (Pinnacle Emissary).  The bridge's
      ``subject_is_artifact`` arm should be event-aware, or the Rust predicate
      dict should carry an explicit slot field.

    CR reference: CR 603.1 -- a triggered ability triggers when its condition
    is met; slot-None evaluating false silently suppresses the trigger.

    Verified observable divergence (both paths -- no Rust extension required):
      * ``Subject("spell", IsArtifact()).matches(state, is_cast_subjects, ...)``
          returns True  (correct slot, artifact spell).
      * ``Subject(slot=None, IsArtifact()).matches(state, is_cast_subjects, ...)``
          returns False (slot=None resolves to None; 2 subjects).

    Probe shape:
      1. Build a minimal Python GameState; create an Artifact card object.
      2. Simulate IS_CAST subject dict: ``{"spell": artifact_obj,
         "controller": p0}``.
      3. Evaluate ``Subject("spell", IsArtifact())`` (correct path) on
         is_cast_subjects -- assert True.
      4. Evaluate the bridge-returned predicate ``Subject(slot=None,
         inner=IsArtifact())`` on is_cast_subjects -- assert False.
      5. Compare via bridge: translate
         ``{"kind": "subject_is_artifact"}`` through
         ``_ta_dict_to_python_predicate``; verify it returns
         ``Subject(slot=None, ...)``, not ``Subject("spell", ...)``.
      6. Assert predicate_bridge.matches(is_cast_subjects) == False.
      7. Assert correct.matches != bridge.matches (non-parity).

    This pin is pure Python (no Rust extension required).
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.object_predicates import IsArtifact
    from mtg_bot.effects.predicates import Subject
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_predicate
    from mtg_bot.turn import Step

    # ---- Build minimal state ----
    state = GameState()
    state.players.append(Player(id=0, life=20))
    state.players.append(Player(id=1, life=20))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN

    artifact_printing = CardPrinting(
        name="Cast Artifact Bait",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
    )

    # The spell being cast -- an Artifact.
    spell_obj = state.new_object(artifact_printing, owner_id=0, zone=Zone.GRAVEYARD)

    # IS_CAST subject dict: two named subjects.
    is_cast_subjects = {
        "spell": spell_obj,
        "controller": state.players[0],
    }

    # ---- Correct path: explicit "spell" slot ----
    correct_pred = Subject(slot="spell", inner=IsArtifact())
    correct_result = correct_pred.matches(state, is_cast_subjects, source=None)

    assert correct_result is True, (
        "Correct path: Subject('spell', IsArtifact()).matches with IS_CAST "
        "subjects should be True -- the 'spell' slot resolves to the "
        "artifact object and IsArtifact().test passes. "
        f"Got: {correct_result}"
    )

    # ---- Bridge path: Subject(slot=None) -- the bug ----
    # _ta_dict_to_python_predicate for "subject_is_artifact" returns
    # Subject(slot=None, inner=IsArtifact()) (cross_engine.py:8751-8752).
    bridge_pred = _ta_dict_to_python_predicate({"kind": "subject_is_artifact"})

    # Pin the slot: bridge returns slot=None, not slot="spell".
    assert isinstance(bridge_pred, Subject), (
        "Bridge should return a Subject instance for 'subject_is_artifact'; "
        f"got {type(bridge_pred).__name__}."
    )
    assert bridge_pred.slot is None, (
        "Bridge pin: _ta_dict_to_python_predicate for 'subject_is_artifact' "
        "should return Subject(slot=None, ...) -- the WRONG slot for IS_CAST. "
        "If slot is not None, the bridge was fixed -- update this pin to "
        "assert slot == 'spell' and verify correct_result == bridge_result. "
        f"Got slot={bridge_pred.slot!r}"
    )
    assert isinstance(bridge_pred.inner, IsArtifact), (
        "Bridge predicate's inner should be IsArtifact; "
        f"got {type(bridge_pred.inner).__name__}."
    )

    # The bridge-returned predicate evaluates False on IS_CAST subjects.
    bridge_result = bridge_pred.matches(state, is_cast_subjects, source=None)

    assert bridge_result is False, (
        "Bridge path: Subject(slot=None, IsArtifact()).matches with IS_CAST "
        "subjects (len == 2) should be False -- _resolve_subject returns "
        "None when slot=None and len(subjects) != 1 (predicates.py:348-350), "
        "so Subject.matches short-circuits to False (predicates.py:370-371). "
        f"Got: {bridge_result}"
    )

    # Cross-path divergence: correct path True, bridge path False.
    assert correct_result != bridge_result, (
        "Cross-path divergence: Subject('spell', IsArtifact()) (True) must "
        "not equal bridge Subject(None, IsArtifact()) (False) until the "
        "bridge arm is fixed to return Subject('spell', IsArtifact()) when "
        "translating 'subject_is_artifact' paired with event='cast'. "
        f"correct={correct_result}, bridge={bridge_result}"
    )

    # Extra sanity: on a single-subject event (ENTERS, 1 subject), slot=None
    # DOES resolve correctly.  This confirms the bug is event-multiplicity-
    # specific, not a general Subject(None) breakage.
    enters_subjects = {"obj": spell_obj}
    bridge_on_enters = bridge_pred.matches(state, enters_subjects, source=None)
    assert bridge_on_enters is True, (
        "Sanity: Subject(slot=None, IsArtifact()) on ENTERS (1 subject) "
        "should return True -- _resolve_subject returns the lone subject "
        "when len(subjects) == 1 (predicates.py:348-349). "
        f"Got: {bridge_on_enters}"
    )


# ---------------------------------------------------------------------------
# Pin 3 -- beginning_of_end_step event not wired in triggered-ability bridge
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_beginning_of_end_step_event_bridge_gap_sentinel_FIXED_parity():
    """**LL Pin 3 CLOSED (round-14 phase-step bridge slice).**

    The bridge gap for ``"beginning_of_end_step"``,
    ``"beginning_of_upkeep"``, and ``"beginning_of_combat"`` in
    ``_ta_dict_to_python_triggered_ability`` is now FIXED.

    **What was broken (pre-round-14):**
      ``_ta_dict_to_python_triggered_ability`` raised ``ValueError:
      event 'beginning_of_end_step' is not yet wired`` for all three
      phase-step event strings.  51 EoE end-step-trigger cards were
      blocked from cross-engine probing.

    **What was fixed (round-14 Rust + bridge slice):**
      1. ``Event::BeginningOfEndStep``, ``Event::BeginningOfUpkeep``,
         ``Event::BeginningOfCombat`` added to Rust ``Event`` enum.
      2. Parse arms added to ``parse_triggered_ability`` in ``cards.rs``.
      3. Dispatch sites added in ``advance_phase`` (``state_ops_steps.rs``)
         for ``PHASE_UPKEEP``, ``PHASE_BEGIN_COMBAT``, ``PHASE_END_STEP``.
      4. ``PLAYER_SUBJECT_OFFSET = 0x8000_0000`` sentinel added to safely
         encode player subjects through the ``subject_id: u32`` API.
      5. ``Predicate::ControlledByYou`` extended to resolve player-index
         subjects from the sentinel range.
      6. Three bridge arms added to ``_ta_dict_to_python_triggered_ability``
         in ``cross_engine.py``.

    **Companion probe:** ``tests/test_probe_phase_step_unlock.py`` —
    Flight-Deck Coordinator end-step GainLife(2) byte-equal probe.

    This pin is pure Python (no Rust extension required for the assertion
    inversions, though the Rust changes must be built for the full probe).
    """
    from mtg_bot.effects.predicates import Event
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_triggered_ability

    # Confirm the Python Event enum members exist (unchanged from the gap era).
    assert hasattr(Event, "BEGINNING_OF_END_STEP"), (
        "Event.BEGINNING_OF_END_STEP must be a member of the Event enum."
    )
    assert hasattr(Event, "BEGINNING_OF_UPKEEP"), (
        "Event.BEGINNING_OF_UPKEEP must be a member of the Event enum."
    )
    assert hasattr(Event, "BEGINNING_OF_COMBAT"), (
        "Event.BEGINNING_OF_COMBAT must be a member of the Event enum."
    )

    # **INVERTED from the gap-era pin**: all three event strings now
    # translate WITHOUT raising ValueError.
    for event_str, expected_event in [
        ("beginning_of_end_step", Event.BEGINNING_OF_END_STEP),
        ("beginning_of_upkeep", Event.BEGINNING_OF_UPKEEP),
        ("beginning_of_combat", Event.BEGINNING_OF_COMBAT),
    ]:
        ta_dict = {
            "event": event_str,
            "predicate": {"kind": "always"},
            "effect": {"kind": "draw_cards", "count": 1},
        }
        try:
            result = _ta_dict_to_python_triggered_ability(ta_dict)
        except ValueError as e:
            raise AssertionError(
                f"LL Pin 3 regression: bridge arm for '{event_str}' is "
                f"missing — _ta_dict_to_python_triggered_ability raised "
                f"ValueError: {e}"
            ) from e

        assert isinstance(result, TriggeredAbility), (
            f"Bridge for '{event_str}' must produce a TriggeredAbility; "
            f"got {type(result).__name__}."
        )
        assert result.event == expected_event, (
            f"Bridge must translate '{event_str}' to {expected_event!r}; "
            f"got {result.event!r}."
        )

    # Sanity: 'becomes_tapped' (pre-existing wired event) still works.
    bt_result = _ta_dict_to_python_triggered_ability({
        "event": "becomes_tapped",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "draw_cards", "count": 1},
    })
    assert isinstance(bt_result, TriggeredAbility), (
        "Sanity: 'becomes_tapped' must still produce a TriggeredAbility."
    )
    assert bt_result.event == Event.BECOMES_TAPPED, (
        f"Sanity: 'becomes_tapped' must translate to BECOMES_TAPPED; "
        f"got {bt_result.event!r}."
    )
