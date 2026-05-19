"""Divergence-pin tests: batch UU (probe-batch-uu).

Each test is named ``test_cross_engine_real_eoe_<slug>_*_divergence_pin``
and ASSERTS the CURRENT divergent behavior rather than parity.  The
PROBED-tier detector excludes ``*_divergence_pin`` functions, so these
tests grow the test surface without touching the PROBED metric.

Pinned bugs
-----------

Pin 1 -- ``would_draw_cards`` event NOT wired in triggered-ability bridge
(WOULD_* replacement-event category; cross-engine bridge event gap; 1 EoE
card blocked).

    Python's ``Event`` enum (``effects/predicates.py``) has an
    ``Event.WOULD_DRAW_CARDS`` member (value ``"would_draw_cards"``).  The
    string ``"would_draw_cards"`` is not in the bridge's elif chain at
    ``cross_engine.py:8902-8974``; passing a triggered-ability dict with
    that event value causes the function to fall through to:

        raise ValueError(
            "cross_engine triggered_abilities bridge: event "
            "'would_draw_cards' is not yet wired"
        )

    WOULD_* event category:
      ``Event.WOULD_DRAW_CARDS`` is a *replacement-effect trigger* event --
      it fires *before* a draw resolves, allowing effects to intercept and
      modify the draw action (similar to Anointed Procession's
      "if you would create a token" pattern).  This is semantically
      distinct from a plain triggered-ability event like ``Event.DIES``
      or ``Event.COUNTERS_ADDED``.  In Python, the WOULD_* events
      nevertheless flow through the same ``TriggeredAbility`` / bridge
      pathway when the Rust engine serializes them to the Python bridge;
      the bridge's elif chain simply lacks arms for them.

      The full WOULD_* family in the Python Event enum:
        ``Event.WOULD_DRAW_CARDS``    (value ``"would_draw_cards"``)
        ``Event.WOULD_CREATE_TOKEN``  (value ``"would_create_token"``)
        ``Event.WOULD_PLACE_COUNTER`` (value ``"would_place_counter"``)
        ``Event.WOULD_GO_TO_GRAVEYARD`` (value ``"would_go_to_graveyard"``)

      None of the four WOULD_* events have bridge arms.  This pin focuses
      on WOULD_DRAW_CARDS; Pin 2 documents WOULD_CREATE_TOKEN with its
      additional multi-subject hazard.

    Subject structure:
      ``Event.WOULD_DRAW_CARDS`` carries subject ``("player",)`` per
      ``EVENT_SUBJECTS`` (``effects/predicates.py``) -- a single subject,
      the player who would draw.  This is the same single-subject shape as
      ``Event.ENTERS`` and ``Event.DIES``, so the ``slot=None`` optimisation
      in ``_resolve_subject`` DOES apply: ``Subject(slot=None, ...)`` will
      correctly resolve to the player object on a ``WOULD_DRAW_CARDS``
      dispatch (unlike the IS_CAST two-subject trap pinned in batch LL Pin 2
      or the WOULD_CREATE_TOKEN multi-subject trap in Pin 2 below).

    Scale:
      1 EoE card carries a replacement effect on the ``would_draw_cards``
      event:
        * Quantum Riddler -- "As long as you have one or fewer cards in hand,
          if you would draw one or more cards, you draw that many cards plus
          one instead."

    Observable divergence (bridge sentinel):
      ``_ta_dict_to_python_triggered_ability({"event": "would_draw_cards",
      "predicate": {"kind": "always"}, "effect": {"kind": "draw_cards",
      "count": 1}})`` raises ``ValueError`` with message containing
      ``"would_draw_cards"`` and ``"not yet wired"``.

    Closure path:
      Add ``elif event_str == "would_draw_cards":
          event = Event.WOULD_DRAW_CARDS``
      to the event-string elif chain in ``_ta_dict_to_python_triggered_ability``.
      WOULD_DRAW_CARDS is single-subject so no predicate-slot companion fix
      is needed (contrast Pin 2's WOULD_CREATE_TOKEN).  Quantum Riddler's
      "one or fewer cards in hand" gate also requires a ``hand_size_at_most``
      predicate bridge arm (a separate closure step beyond wiring the event).

    This pin is pure Python (no Rust extension required).

Pin 2 -- ``would_create_token`` event NOT wired in triggered-ability bridge
(WOULD_* replacement-event category; two-subject event; multi-subject
slot-rewrite hazard; cross-engine bridge event gap).

    Python's ``Event`` enum has ``Event.WOULD_CREATE_TOKEN`` (value
    ``"would_create_token"``).  The string ``"would_create_token"`` is not
    in the bridge elif chain; passing a triggered-ability dict with that
    event value causes the bridge to raise:

        raise ValueError(
            "cross_engine triggered_abilities bridge: event "
            "'would_create_token' is not yet wired"
        )

    Two-subject structure and multi-subject slot trap:
      ``Event.WOULD_CREATE_TOKEN`` carries TWO named subjects:
      ``("controller", "kind")`` per ``EVENT_SUBJECTS``
      (``effects/predicates.py``).

        * ``"controller"`` -- the player who would create the token.
        * ``"kind"`` -- the token-type descriptor (identifying what kind of
          token would be created).

      This TWO-subject shape means that ``Subject(slot=None, ...)`` or
      ``IsSelf(subject=None)`` predicates will hit the LL Pin 2 multi-subject
      hazard: ``_resolve_subject(subjects, None)`` returns ``None`` when
      ``len(subjects) == 2``, causing any slot=None predicate to evaluate
      ALWAYS FALSE on ``WOULD_CREATE_TOKEN`` dispatches.

      The predicate-slot rewrite already implemented for DEALS_COMBAT_DAMAGE
      (``_rewrite_predicate_for_deals_combat_damage`` at
      ``cross_engine.py:8984-8985``) fixes up slot=None → ``"source"`` for
      that two-subject event.  A similar rewrite will be needed for
      WOULD_CREATE_TOKEN when the elif arm lands -- the correct explicit slot
      for most "if you would create a token" predicates is ``"controller"``
      (the player subject, parallel to ``"source"`` for DEALS_COMBAT_DAMAGE).

      Events pinned in prior batches with a similar multi-subject structure:
        * ``Event.IS_CAST``              -- ``("spell", "controller")``   [LL Pin 2]
        * ``Event.DEALS_COMBAT_DAMAGE``  -- ``("source", "target")``      [OO Pin 2; CLOSED by SS]
        * ``Event.WOULD_CREATE_TOKEN``   -- ``("controller", "kind")``    [THIS PIN]
        * ``Event.PLAYS_LAND``           -- ``("land", "controller")``    [Pin 3 below]

    Scale:
      No EoE cards currently use ``would_create_token`` as a triggered-ability
      event (the EoE card set has no Anointed Procession-style doublers).
      The pin is a preemptive structural guard: documenting the multi-subject
      shape so the predicate-slot companion fix is not forgotten when the
      elif arm is added.

    Observable divergence (bridge sentinel):
      ``_ta_dict_to_python_triggered_ability({"event":
      "would_create_token", ...})`` raises ``ValueError`` with message
      containing ``"would_create_token"`` and ``"not yet wired"``.

    Closure path:
      1. Add ``elif event_str == "would_create_token":
             event = Event.WOULD_CREATE_TOKEN``
         to the event-string elif chain.
      2. Add a predicate-slot rewrite analogous to
         ``_rewrite_predicate_for_deals_combat_damage`` that converts
         slot=None predicates to explicit ``"controller"`` slot bindings.
      Both steps must land together to avoid the multi-subject slot trap.

    This pin is pure Python (no Rust extension required).

Pin 3 -- ``plays_land`` event NOT wired in triggered-ability bridge
(cross-engine bridge event gap; two-subject event; multi-subject slot
hazard; 1 EoE card affected by standalone bridge gap; compound-disjunction
need is a SEPARATE follow-on issue).

    Python's ``Event`` enum has ``Event.PLAYS_LAND`` (value ``"plays_land"``).
    The string ``"plays_land"`` is not in the bridge elif chain; passing a
    triggered-ability dict with that event value causes the bridge to raise:

        raise ValueError(
            "cross_engine triggered_abilities bridge: event "
            "'plays_land' is not yet wired"
        )

    PLAYS_LAND vs ENTERS (Landfall) distinction:
      ``Event.PLAYS_LAND`` fires when a player PLAYS a land (CR 305 play-land
      action: put a land from hand onto the battlefield during their main
      phase using the once-per-turn land play right).  This is distinct from:
        * ``Event.ENTERS`` (``"enters"``; WIRED) -- fires when ANY permanent
          enters the battlefield, including lands put onto the battlefield by
          effects such as ramp spells and Lander activations.  Landfall cards
          ("Whenever a land you control enters, ...") use ENTERS, not
          PLAYS_LAND, because they trigger regardless of HOW the land
          entered.

      The distinction matters for cards like The Endstone ("Whenever you
      play a land or cast a spell, draw a card") -- the "play a land" clause
      maps to PLAYS_LAND, not ENTERS.

    Two-subject structure and multi-subject slot trap:
      ``Event.PLAYS_LAND`` carries TWO named subjects:
      ``("land", "controller")`` per ``EVENT_SUBJECTS``
      (``effects/predicates.py``).

        * ``"land"`` -- the land card being played.
        * ``"controller"`` -- the player who plays the land.

      This two-subject shape creates the LL Pin 2 / OO Pin 2 multi-subject
      slot trap: ``Subject(slot=None, ...)`` evaluates ALWAYS FALSE on
      PLAYS_LAND dispatches because ``_resolve_subject`` returns ``None``
      when ``len(subjects) == 2``.  A predicate-slot companion fix (analogous
      to ``_rewrite_predicate_for_deals_combat_damage``) will be needed when
      the elif arm lands, pinning slot=None predicates to ``"land"`` or
      ``"controller"`` as appropriate for the card's oracle text.

    Compound-disjunction issue (The Endstone) -- a SEPARATE follow-on:
      The sole EoE card that uses ``plays_land`` (The Endstone) combines
      the event with ``is_cast`` via a logical OR: "Whenever you play a land
      OR cast a spell, draw a card."  The bridge's triggered-ability model
      represents each triggered ability as a single event; there is no
      disjunction support in the bridge (no OR-of-events arm in the elif
      chain, and no multi-event TriggeredAbility constructor).  This
      disjunction gap was documented and DROPPED in batch RR; it is NOT
      what this pin measures.  This pin measures ONLY the standalone bridge
      gap for ``"plays_land"`` as a single event -- a necessary prerequisite
      for any future disjunction closure.

    Scale:
      1 EoE card carries a triggered ability on the ``plays_land`` event:
        * The Endstone -- "Whenever you play a land or cast a spell, draw a
          card." (The ``is_cast`` half of the disjunction is a separate
          closure item; the ``plays_land`` half cannot proceed until the
          bridge arm lands.)

    Observable divergence (bridge sentinel):
      ``_ta_dict_to_python_triggered_ability({"event": "plays_land", ...})``
      raises ``ValueError`` with message containing ``"plays_land"`` and
      ``"not yet wired"``.

    Closure path:
      1. Add ``elif event_str == "plays_land":
             event = Event.PLAYS_LAND``
         to the event-string elif chain.
      2. Add a predicate-slot companion rewrite (slot=None → ``"land"`` or
         ``"controller"`` per the predicate's semantic intent).
      3. Wire the disjunction support needed for The Endstone (requires a
         multi-event TriggeredAbility representation or a compound OR
         predicate that emits under either event dispatch -- a third
         distinct closure step beyond this pin).

    This pin is pure Python (no Rust extension required).

Dropped pins
------------

  * ``beginning_of_postcombat_main`` bridge gap: Dropped in batch RR; no
    EoE cards identified.  Not revisited here.

  * ``discards_card`` bridge gap (1 EoE card: Entropic Battlecruiser):
    Dropped in batch RR; multi-subject predicate complexity (subject:
    ``("player",)``).  Not revisited here.

  * ``would_place_counter`` bridge gap: Two-subject ``("obj", "kind")``
    shape -- similar compound-closure complexity as WOULD_CREATE_TOKEN.
    No EoE cards use it; dropped in favor of WOULD_CREATE_TOKEN (Pin 2)
    which documents the WOULD_* two-subject pattern.

  * ``would_go_to_graveyard`` bridge gap: Single-subject ``("card",)``;
    no EoE cards use it.  Dropped for now; add when a specific card
    surfaces.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Pin 1 -- would_draw_cards event not wired in triggered-ability bridge
#          (WOULD_* replacement-event category; single subject)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_would_draw_cards_event_bridge_gap_sentinel_FIXED_parity():
    """Bridge arm for ``would_draw_cards`` event is now wired.

    UU Pin 1 -- CLOSED.  The bridge arm for ``event_str == "would_draw_cards"``
    was added to the elif chain in ``_ta_dict_to_python_triggered_ability``
    in ``src/mtg_bot/parity/cross_engine.py``.

    This test verifies the wired behavior (no ValueError raised, correct
    TriggeredAbility returned) and asserts the structural invariants the
    pin originally documented.

    WOULD_* family note:
      ``Event.WOULD_DRAW_CARDS`` is the first member of the WOULD_*
      replacement-event family to be wired.  All four WOULD_* events
      (``would_draw_cards``, ``would_create_token``, ``would_place_counter``,
      ``would_go_to_graveyard``) previously shared the same missing-elif-arm
      bridge gap.  Pin 2 (WOULD_CREATE_TOKEN) documents the additional
      multi-subject hazard for the two-subject WOULD_* events.

    Scale:
      1 EoE card carries a replacement effect on the ``would_draw_cards``
      event: Quantum Riddler (oracle text: "As long as you have one or fewer
      cards in hand, if you would draw one or more cards, you draw that many
      cards plus one instead.").

    Subject structure note:
      ``Event.WOULD_DRAW_CARDS`` carries a single subject ``("player",)``
      (the player who would draw).  Single-subject shape means
      ``Subject(slot=None, ...)`` WILL resolve correctly on
      WOULD_DRAW_CARDS dispatch -- no predicate-slot rewrite needed.

    This pin is pure Python (no Rust extension required).
    """
    from mtg_bot.effects.predicates import Event, EVENT_SUBJECTS
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_triggered_ability

    # 1. The Python Event enum has WOULD_DRAW_CARDS.
    assert hasattr(Event, "WOULD_DRAW_CARDS"), (
        "Event.WOULD_DRAW_CARDS should be a member of the Event enum "
        "(effects/predicates.py). If this fails the enum member was renamed "
        "-- update both this pin and the bridge arm."
    )
    assert isinstance(Event.WOULD_DRAW_CARDS, Event), (
        "Event.WOULD_DRAW_CARDS should be an Event enum instance."
    )
    assert Event.WOULD_DRAW_CARDS.value == "would_draw_cards", (
        "Event.WOULD_DRAW_CARDS.value should be 'would_draw_cards'; "
        f"got {Event.WOULD_DRAW_CARDS.value!r}"
    )

    # 2. WOULD_DRAW_CARDS has a single subject ("player",) -- NOT a two-subject
    #    event.  Subject(slot=None, ...) resolves correctly here (single-subject
    #    optimisation in _resolve_subject applies), unlike WOULD_CREATE_TOKEN
    #    (Pin 2) which has the IS_CAST-style two-subject slot trap.
    subjects = EVENT_SUBJECTS.get(Event.WOULD_DRAW_CARDS)
    assert subjects == ("player",), (
        "Event.WOULD_DRAW_CARDS should carry one subject: ('player',) per "
        "EVENT_SUBJECTS (effects/predicates.py).  This single-subject shape "
        "means Subject(slot=None, ...) resolves correctly on WOULD_DRAW_CARDS "
        "dispatch -- unlike WOULD_CREATE_TOKEN's two-subject ('controller', "
        "'kind') shape (Pin 2).  "
        f"Got subjects={subjects!r}"
    )

    # 3. Assert the full WOULD_* family exists in the Event enum.
    for would_event_name, expected_val in (
        ("WOULD_DRAW_CARDS", "would_draw_cards"),
        ("WOULD_CREATE_TOKEN", "would_create_token"),
        ("WOULD_PLACE_COUNTER", "would_place_counter"),
        ("WOULD_GO_TO_GRAVEYARD", "would_go_to_graveyard"),
    ):
        assert hasattr(Event, would_event_name), (
            f"Event.{would_event_name} should be a member of the Event enum "
            f"(effects/predicates.py).  The full WOULD_* replacement-event "
            f"family should be present.  If this fails the enum member was "
            f"renamed -- update this pin and the bridge arm."
        )
        assert getattr(Event, would_event_name).value == expected_val, (
            f"Event.{would_event_name}.value should be {expected_val!r}; "
            f"got {getattr(Event, would_event_name).value!r}"
        )

    # 4. Bridge NO LONGER raises ValueError -- the arm is wired.
    from mtg_bot.effects.base import TriggeredAbility
    wired_ta_dict = {
        "event": "would_draw_cards",
        "predicate": {"kind": "always"},
        "effect": {
            "kind": "draw_cards",
            "count": 1,
        },
    }
    result = _ta_dict_to_python_triggered_ability(wired_ta_dict)
    assert isinstance(result, TriggeredAbility), (
        "Bridge arm for 'would_draw_cards' should return a TriggeredAbility; "
        f"got {type(result).__name__!r}."
    )
    assert result.event == Event.WOULD_DRAW_CARDS, (
        "Bridge arm for 'would_draw_cards' should set event=Event.WOULD_DRAW_CARDS; "
        f"got {result.event!r}."
    )

    # 5. Sanity: a WIRED event ("becomes_tapped") still round-trips.
    wired_tapped_dict = {
        "event": "becomes_tapped",
        "predicate": {"kind": "always"},
        "effect": {
            "kind": "draw_cards",
            "count": 1,
        },
    }
    try:
        tapped_result = _ta_dict_to_python_triggered_ability(wired_tapped_dict)
        assert isinstance(tapped_result, TriggeredAbility), (
            "Wired event 'becomes_tapped' should produce a TriggeredAbility; "
            f"got {type(tapped_result).__name__}."
        )
        assert tapped_result.event == Event.BECOMES_TAPPED, (
            "Wired event 'becomes_tapped' should translate to "
            f"Event.BECOMES_TAPPED; got {tapped_result.event!r}."
        )
    except ValueError as e:
        raise AssertionError(
            "Sanity: 'becomes_tapped' is a wired event and should NOT raise "
            f"ValueError -- got: {e}"
        ) from e

    # 6. Document the 1 EoE card unblocked by this fix.
    unblocked_eoe_cards = [
        "Quantum Riddler",   # "As long as you have one or fewer cards in hand,
                             #  if you would draw one or more cards, you draw
                             #  that many cards plus one instead."
                             # Note: the "one or fewer cards in hand" condition
                             # also requires a hand_size_at_most predicate bridge
                             # arm -- a separate closure step.
    ]
    assert len(unblocked_eoe_cards) == 1, (
        "The 'would_draw_cards' event arm unblocks 1 EoE card (Quantum Riddler); "
        f"enumerated list has {len(unblocked_eoe_cards)} entries."
    )


# ---------------------------------------------------------------------------
# Pin 2 -- would_create_token event not wired in triggered-ability bridge
#          (WOULD_* two-subject event; multi-subject slot-rewrite hazard)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_would_create_token_event_bridge_gap_sentinel_divergence_pin():
    """Pin the bridge gap for the ``would_create_token`` event string in
    ``_ta_dict_to_python_triggered_ability``, and document its multi-subject
    slot-rewrite hazard.

    Bug location:
      ``src/mtg_bot/parity/cross_engine.py:8902-8974`` -- the elif chain
      in ``_ta_dict_to_python_triggered_ability`` does not include an arm
      for ``"would_create_token"``.  All unrecognised strings fall through to:

          raise ValueError(
              "cross_engine triggered_abilities bridge: event "
              "'would_create_token' is not yet wired"
          )

      Python's ``Event`` enum has ``Event.WOULD_CREATE_TOKEN`` (value
      ``"would_create_token"``); the enum member exists, but there is no
      bridge arm to wire it.

    Multi-subject slot-rewrite hazard:
      Unlike Pin 1 (WOULD_DRAW_CARDS, single-subject ``("player",)``),
      ``Event.WOULD_CREATE_TOKEN`` carries TWO named subjects:
      ``("controller", "kind")`` per ``EVENT_SUBJECTS``
      (``effects/predicates.py``).

      This two-subject shape means any predicate translated by the bridge
      with ``Subject(slot=None, ...)`` will hit the LL Pin 2 / OO Pin 2
      multi-subject hazard:

          ``_resolve_subject(subjects, None)``
          → returns ``None`` when ``len(subjects) == 2``
          → ``Subject.matches(...)`` returns ``False`` (predicate always fails)

      The fix pattern -- already established for DEALS_COMBAT_DAMAGE
      (``_rewrite_predicate_for_deals_combat_damage`` at
      ``cross_engine.py:8984-8985``) -- requires a companion predicate-slot
      rewrite that maps slot=None to an explicit slot name.  For
      WOULD_CREATE_TOKEN the appropriate explicit slot for "if you would
      create a token" predicates is ``"controller"`` (the player subject).

      This is a TWO-STEP closure:
        Step A: add the elif arm (eliminates the ValueError).
        Step B: add the slot-rewrite pass (eliminates silent predicate
                misfires after Step A lands).
      Both steps must land together; landing Step A alone would silence the
      ValueError but introduce a harder-to-detect always-false predicate bug.

    Scale:
      0 EoE cards currently carry triggered abilities on the
      ``would_create_token`` event (the EoE set has no Anointed
      Procession-style token-doubling effects as triggered abilities).
      This is a preemptive structural guard: documenting the multi-subject
      shape and required closure steps before a card surfaces that needs them.

    Observable divergence (bridge sentinel):
      ``_ta_dict_to_python_triggered_ability({"event":
      "would_create_token", ...})`` raises ``ValueError`` with message
      containing ``"would_create_token"`` and ``"not yet wired"``.

    Probe shape:
      1. Assert ``Event.WOULD_CREATE_TOKEN`` exists and has the correct
         string value ``"would_create_token"``.
      2. Assert ``EVENT_SUBJECTS[Event.WOULD_CREATE_TOKEN]`` is
         ``("controller", "kind")`` (two-subject shape -- documents the
         multi-subject slot trap).
      3. Assert WOULD_CREATE_TOKEN is distinct from WOULD_DRAW_CARDS
         (different WOULD_* family members, different subject shapes).
      4. Assert the bridge raises ``ValueError`` for the unwired event.
      5. Assert the message mentions ``"would_create_token"`` and
         ``"not yet wired"``.
      6. Assert WOULD_DRAW_CARDS (Pin 1, single-subject) does NOT have
         the same two-subject shape (contrast the two WOULD_* events).
      7. Sanity: assert a wired event (``"attacks"``) does NOT raise.

    This pin is pure Python (no Rust extension required).
    """
    from mtg_bot.effects.predicates import Event, EVENT_SUBJECTS
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_triggered_ability

    # 1. The Python Event enum has WOULD_CREATE_TOKEN.
    assert hasattr(Event, "WOULD_CREATE_TOKEN"), (
        "Event.WOULD_CREATE_TOKEN should be a member of the Event enum "
        "(effects/predicates.py). If this fails the enum member was renamed "
        "-- update both this pin and the bridge arm."
    )
    assert isinstance(Event.WOULD_CREATE_TOKEN, Event), (
        "Event.WOULD_CREATE_TOKEN should be an Event enum instance."
    )
    assert Event.WOULD_CREATE_TOKEN.value == "would_create_token", (
        "Event.WOULD_CREATE_TOKEN.value should be 'would_create_token'; "
        f"got {Event.WOULD_CREATE_TOKEN.value!r}"
    )

    # 2. WOULD_CREATE_TOKEN has TWO subjects ("controller", "kind") --
    #    the two-subject shape that creates the LL Pin 2 / OO Pin 2
    #    multi-subject slot trap.  Subject(slot=None, ...) resolves to
    #    None on WOULD_CREATE_TOKEN dispatch (len(subjects)==2 branch in
    #    _resolve_subject), causing any slot=None predicate to ALWAYS FAIL.
    #    A predicate-slot companion rewrite is needed alongside the elif arm.
    subjects = EVENT_SUBJECTS.get(Event.WOULD_CREATE_TOKEN)
    assert subjects == ("controller", "kind"), (
        "Event.WOULD_CREATE_TOKEN should carry two subjects: "
        "('controller', 'kind') per EVENT_SUBJECTS (effects/predicates.py). "
        "This two-subject shape means Subject(slot=None, ...) resolves to None "
        "on WOULD_CREATE_TOKEN dispatch (the LL Pin 2 multi-subject hazard). "
        "A predicate-slot rewrite (slot=None -> 'controller') must accompany "
        "the elif arm when this gap is closed. "
        f"Got subjects={subjects!r}"
    )

    # 3. WOULD_CREATE_TOKEN is distinct from WOULD_DRAW_CARDS (Pin 1).
    #    They are different WOULD_* family members with different subject
    #    shapes: WOULD_DRAW_CARDS is single-subject ("player",), safe for
    #    slot=None; WOULD_CREATE_TOKEN is two-subject ("controller", "kind"),
    #    hazardous for slot=None.  Wiring one does NOT wire the other.
    assert Event.WOULD_CREATE_TOKEN is not Event.WOULD_DRAW_CARDS, (
        "Event.WOULD_CREATE_TOKEN must be a distinct enum member from "
        "Event.WOULD_DRAW_CARDS.  They are different WOULD_* family events "
        "with different subject shapes (two-subject vs single-subject). "
        "Adding the elif arm for one does NOT add it for the other."
    )

    # 4-5. Bridge raises ValueError for "would_create_token" -- pin the gap.
    unwired_ta_dict = {
        "event": "would_create_token",
        "predicate": {"kind": "always"},
        "effect": {
            "kind": "draw_cards",
            "count": 1,
        },
    }
    with pytest.raises(ValueError) as exc_info:
        _ta_dict_to_python_triggered_ability(unwired_ta_dict)

    err_msg = str(exc_info.value)
    assert "would_create_token" in err_msg, (
        "Bridge gap sentinel: the ValueError message should mention "
        "'would_create_token' so the gap is immediately identifiable.  "
        f"Got message: {err_msg!r}"
    )
    assert "not yet wired" in err_msg, (
        "Bridge gap sentinel: the ValueError should contain 'not yet wired' "
        "confirming the event-elif chain produced this error, not some "
        "other ValueError.  "
        f"Got message: {err_msg!r}"
    )

    # 6. Contrast: WOULD_DRAW_CARDS (Pin 1) is single-subject ("player",),
    #    NOT ("controller", "kind").  This structural difference means
    #    WOULD_DRAW_CARDS does NOT need the slot-rewrite companion fix;
    #    WOULD_CREATE_TOKEN does.
    draw_subjects = EVENT_SUBJECTS.get(Event.WOULD_DRAW_CARDS)
    assert draw_subjects == ("player",), (
        "Event.WOULD_DRAW_CARDS should carry one subject: ('player',) -- "
        "the single-subject shape that makes it safe for slot=None predicates. "
        "This contrasts with WOULD_CREATE_TOKEN's two-subject shape. "
        f"Got draw_subjects={draw_subjects!r}"
    )
    assert len(draw_subjects) == 1 and len(subjects) == 2, (
        "WOULD_DRAW_CARDS (Pin 1) should have 1 subject and WOULD_CREATE_TOKEN "
        "(Pin 2) should have 2 subjects -- documenting the structural difference "
        "between the safe-for-slot-None and unsafe-for-slot-None WOULD_* events. "
        f"Got draw_subjects={draw_subjects!r}, create_subjects={subjects!r}"
    )

    # 7. Sanity: a WIRED event ("attacks") round-trips cleanly.
    wired_ta_dict = {
        "event": "attacks",
        "predicate": {"kind": "always"},
        "effect": {
            "kind": "draw_cards",
            "count": 1,
        },
    }
    try:
        result = _ta_dict_to_python_triggered_ability(wired_ta_dict)
        from mtg_bot.effects.base import TriggeredAbility
        assert isinstance(result, TriggeredAbility), (
            "Wired event 'attacks' should produce a TriggeredAbility; "
            f"got {type(result).__name__}."
        )
        assert result.event == Event.ATTACKS, (
            "Wired event 'attacks' should translate to Event.ATTACKS; "
            f"got {result.event!r}."
        )
    except ValueError as e:
        raise AssertionError(
            "Sanity: 'attacks' is a wired event and should NOT raise "
            f"ValueError -- got: {e}"
        ) from e


# ---------------------------------------------------------------------------
# Pin 3 -- plays_land event not wired in triggered-ability bridge
#          (two-subject event; multi-subject slot hazard; distinct from
#          ENTERS / Landfall; compound-disjunction need is a SEPARATE issue)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_plays_land_event_bridge_gap_sentinel_FIXED_parity():
    """Bridge arm for ``plays_land`` event is now wired (with slot-rewrite).

    UU Pin 3 -- CLOSED.  The bridge arm for ``event_str == "plays_land"``
    was added to the elif chain in ``_ta_dict_to_python_triggered_ability``,
    AND ``_rewrite_predicate_for_plays_land`` was added to handle the
    two-subject slot-rewrite hazard (slot=None -> slot="land").

    This test verifies the wired behavior (no ValueError raised, correct
    TriggeredAbility with PLAYS_LAND event returned, slot-rewrite applied)
    and asserts the structural invariants the pin originally documented.

    PLAYS_LAND vs ENTERS (Landfall) distinction:
      ``Event.PLAYS_LAND`` fires when a player PLAYS a land (the CR 305
      play-land action from hand during the main phase).  The wired
      ``Event.ENTERS`` fires when ANY permanent (including lands) enters the
      battlefield via ANY means (ramp spells, Lander activations, or the
      play-land action).  Landfall triggers use ENTERS; The Endstone uses
      PLAYS_LAND.  Wiring ENTERS does NOT wire PLAYS_LAND.

    Two-subject structure and slot-rewrite fix:
      ``Event.PLAYS_LAND`` carries TWO named subjects:
      ``("land", "controller")`` per ``EVENT_SUBJECTS``.
      The companion ``_rewrite_predicate_for_plays_land`` fixes
      slot=None predicates to slot="land" — matching the parser's output
      of ``IsSelf(subject="land")`` for "whenever you play a land" triggers.

    Compound-disjunction issue (The Endstone) is a SEPARATE follow-on:
      The Endstone says "Whenever you play a land OR cast a spell, draw a
      card."  The disjunction between PLAYS_LAND and IS_CAST requires a
      multi-event TriggeredAbility representation not yet in the bridge.
      This pin closes only the standalone PLAYS_LAND bridge gap; the
      disjunction is a separate follow-on closure item.

    Scale:
      1 EoE card carries a triggered ability on the ``plays_land`` event:
        * The Endstone -- "Whenever you play a land or cast a spell, draw a
          card."  (Also affected by the compound-disjunction gap; the
          standalone bridge gap pinned here must be closed first.)

    This pin is pure Python (no Rust extension required).
    """
    from mtg_bot.effects.predicates import Event, EVENT_SUBJECTS
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_triggered_ability

    # 1. The Python Event enum has PLAYS_LAND.
    assert hasattr(Event, "PLAYS_LAND"), (
        "Event.PLAYS_LAND should be a member of the Event enum "
        "(effects/predicates.py). If this fails the enum member was renamed "
        "-- update both this pin and the bridge arm."
    )
    assert isinstance(Event.PLAYS_LAND, Event), (
        "Event.PLAYS_LAND should be an Event enum instance."
    )
    assert Event.PLAYS_LAND.value == "plays_land", (
        "Event.PLAYS_LAND.value should be 'plays_land'; "
        f"got {Event.PLAYS_LAND.value!r}"
    )

    # 2. PLAYS_LAND is distinct from ENTERS (Landfall).
    assert Event.PLAYS_LAND is not Event.ENTERS, (
        "Event.PLAYS_LAND must be a distinct enum member from Event.ENTERS. "
        "Landfall cards use ENTERS ('whenever a land you control enters'); "
        "The Endstone uses PLAYS_LAND ('whenever you play a land'). "
        "Wiring ENTERS (Slice 1 in cross_engine.py) did NOT wire PLAYS_LAND."
    )
    assert Event.ENTERS.value == "enters", (
        "Event.ENTERS.value should be 'enters' (a wired event -- sanity check "
        "that the enum was not restructured). "
        f"Got {Event.ENTERS.value!r}"
    )

    # 3. PLAYS_LAND has TWO subjects ("land", "controller").
    plays_subjects = EVENT_SUBJECTS.get(Event.PLAYS_LAND)
    enters_subjects = EVENT_SUBJECTS.get(Event.ENTERS)
    assert plays_subjects == ("land", "controller"), (
        "Event.PLAYS_LAND should carry two subjects: ('land', 'controller') per "
        "EVENT_SUBJECTS (effects/predicates.py).  "
        f"Got plays_subjects={plays_subjects!r}"
    )
    # ENTERS is single-subject ("obj",) -- safe for slot=None.
    assert enters_subjects == ("obj",), (
        "Event.ENTERS should carry one subject: ('obj',) per EVENT_SUBJECTS. "
        "Contrast with PLAYS_LAND's two-subject shape: ENTERS is single-subject "
        "and safe for slot=None predicates.  "
        f"Got enters_subjects={enters_subjects!r}"
    )

    # 4. Bridge NO LONGER raises ValueError -- the arm is wired.
    from mtg_bot.effects.base import TriggeredAbility
    wired_ta_dict = {
        "event": "plays_land",
        "predicate": {"kind": "always"},
        "effect": {
            "kind": "draw_cards",
            "count": 1,
        },
    }
    result = _ta_dict_to_python_triggered_ability(wired_ta_dict)
    assert isinstance(result, TriggeredAbility), (
        "Bridge arm for 'plays_land' should return a TriggeredAbility; "
        f"got {type(result).__name__!r}."
    )
    assert result.event == Event.PLAYS_LAND, (
        "Bridge arm for 'plays_land' should set event=Event.PLAYS_LAND; "
        f"got {result.event!r}."
    )

    # 5. Slot-rewrite verification: IsSelf(subject=None) should be rewritten
    #    to IsSelf(subject="land") by _rewrite_predicate_for_plays_land.
    from mtg_bot.parity.cross_engine import _rewrite_predicate_for_plays_land
    from mtg_bot.effects.predicates import IsSelf, Subject
    from mtg_bot.effects.object_predicates import IsLand

    # IsSelf(subject=None) -> IsSelf(subject="land")
    rewritten_isself = _rewrite_predicate_for_plays_land(IsSelf(subject=None))
    assert isinstance(rewritten_isself, IsSelf), (
        "_rewrite_predicate_for_plays_land should return an IsSelf instance "
        f"for IsSelf input; got {type(rewritten_isself).__name__!r}."
    )
    assert rewritten_isself.subject == "land", (
        "_rewrite_predicate_for_plays_land should rewrite IsSelf(subject=None) "
        f"to IsSelf(subject='land'); got subject={rewritten_isself.subject!r}."
    )

    # IsSelf with explicit slot passes through unchanged.
    explicit_isself = IsSelf(subject="controller")
    rewritten_explicit = _rewrite_predicate_for_plays_land(explicit_isself)
    assert rewritten_explicit.subject == "controller", (
        "IsSelf with explicit slot 'controller' should pass through unchanged; "
        f"got subject={rewritten_explicit.subject!r}."
    )

    # Subject(slot=None, ...) -> Subject(slot="land", ...)
    rewritten_subject = _rewrite_predicate_for_plays_land(Subject(slot=None, inner=IsLand()))
    assert isinstance(rewritten_subject, Subject), (
        "_rewrite_predicate_for_plays_land should return a Subject instance; "
        f"got {type(rewritten_subject).__name__!r}."
    )
    assert rewritten_subject.slot == "land", (
        "_rewrite_predicate_for_plays_land should rewrite Subject(slot=None) "
        f"to Subject(slot='land'); got slot={rewritten_subject.slot!r}."
    )

    # 6. Sanity: "enters" (wired since Slice 1) still round-trips.
    wired_enters_dict = {
        "event": "enters",
        "predicate": {"kind": "always"},
        "effect": {
            "kind": "draw_cards",
            "count": 1,
        },
    }
    try:
        enters_result = _ta_dict_to_python_triggered_ability(wired_enters_dict)
        assert isinstance(enters_result, TriggeredAbility), (
            "Wired event 'enters' should produce a TriggeredAbility; "
            f"got {type(enters_result).__name__}."
        )
        assert enters_result.event == Event.ENTERS, (
            "Wired event 'enters' should translate to Event.ENTERS; "
            f"got {enters_result.event!r}."
        )
    except ValueError as e:
        raise AssertionError(
            "Sanity: 'enters' is a wired event and should NOT raise "
            f"ValueError -- got: {e}"
        ) from e

    # 7. Document the 1 EoE card unblocked (prerequisite step) by this fix.
    unblocked_eoe_cards = [
        "The Endstone",    # "Whenever you play a land or cast a spell, draw a
                           #  card."  (Also needs compound-disjunction support
                           #  for the 'or cast a spell' half -- a separate
                           #  closure item beyond this bridge gap.)
    ]
    assert len(unblocked_eoe_cards) == 1, (
        "The 'plays_land' event bridge arm (standalone) unblocks 1 EoE card "
        "(The Endstone -- compound-disjunction gap is a separate issue); "
        f"enumerated list has {len(unblocked_eoe_cards)} entries."
    )
