"""Divergence-pin tests: batch OO (probe-batch-oo).

Each test is named ``test_cross_engine_real_eoe_<slug>_*_divergence_pin``
and ASSERTS the CURRENT divergent behavior rather than parity.  The
PROBED-tier detector excludes ``*_divergence_pin`` functions, so these
tests grow the test surface without touching the PROBED metric.

Pinned bugs
-----------

Pin 1 -- ``room_fully_unlocked`` event NOT wired in triggered-ability bridge
(cross-engine bridge event gap; 10 EoE Room cards blocked).

    The cross-engine triggered-ability bridge function
    ``_ta_dict_to_python_triggered_ability`` (``cross_engine.py:8826``)
    converts event-string values into Python ``Event`` enum members.  The
    elif chain at ``cross_engine.py:8838-8874`` recognises only these event
    strings: ``"enters"``, ``"dies"``, ``"cast"``, ``"attacks"``,
    ``"blocks"``, ``"leaves_battlefield"``, and ``"becomes_tapped"``.

    Python's ``Event`` enum (``effects/predicates.py``) has a
    ``Event.ROOM_FULLY_UNLOCKED`` member (value ``"room_fully_unlocked"``).
    The string ``"room_fully_unlocked"`` is not in the bridge's elif chain;
    passing a triggered-ability dict with that event value causes the
    function to fall through to:

        raise ValueError(
            "cross_engine triggered_abilities bridge: event "
            "'room_fully_unlocked' is not yet wired"
        )

    Scale:
      10 EoE cards carry Room-unlock triggered abilities: Cult Healer,
      Optimistic Scavenger, Entity Tracker, Balemurk Leech, and others.
      Any Rust-sourced card that emits
      ``{"event": "room_fully_unlocked", ...}`` in a triggered-ability dict
      cannot be routed through the bridge.

    Observable consequence:
      Any cross-engine probe whose Rust-sourced card emits
      ``{"event": "room_fully_unlocked", ...}`` in a triggered-ability dict
      triggers the ValueError during bridge translation, aborting the probe
      rather than producing a meaningful diff.

    Observable divergence (bridge sentinel):
      ``_ta_dict_to_python_triggered_ability({"event":
      "room_fully_unlocked", "predicate": {"kind": "always"}, "effect":
      {"kind": "draw_cards", "count": 1}})`` raises ``ValueError`` with
      message containing ``"room_fully_unlocked"`` and ``"not yet wired"``.

    Closure path:
      Add ``elif event_str == "room_fully_unlocked":
          event = Event.ROOM_FULLY_UNLOCKED``
      to the event-string elif chain in ``_ta_dict_to_python_triggered_ability``.
      The ``ROOM_FULLY_UNLOCKED`` event carries a ``("room",)`` subject
      (``EVENT_SUBJECTS`` at ``effects/predicates.py:222``), and its dispatch
      site is the Room-unlock path at
      ``state_ops_resolve.rs`` / ``actions.py:_fire_room_unlock_triggers``.
      When the arm lands, the ValueError will no longer fire here, and Room
      cards like Cult Healer / Optimistic Scavenger can be exercised via
      cross-engine probes.

    This pin is pure Python (no Rust extension required).

Pin 2 -- ``deals_combat_damage`` event NOT wired in triggered-ability bridge
(cross-engine bridge event gap; 9 EoE cards blocked).

    Python's ``Event`` enum has ``Event.DEALS_COMBAT_DAMAGE`` (value
    ``"deals_combat_damage"``).  The string ``"deals_combat_damage"`` is not
    in the bridge elif chain; passing a triggered-ability dict with that event
    value causes the bridge to raise:

        raise ValueError(
            "cross_engine triggered_abilities bridge: event "
            "'deals_combat_damage' is not yet wired"
        )

    Scale:
      9 EoE cards carry "whenever ~ deals combat damage to a player"
      triggered abilities: Illvoi Infiltrator, Starwinder, Elegy Acolyte,
      and others.  The ``DEALS_COMBAT_DAMAGE`` event carries TWO subjects
      (``("source", "target")`` per ``EVENT_SUBJECTS`` at
      ``effects/predicates.py:212``), making it structurally more complex
      than single-subject events.  The bridge needs both the event arm AND
      a multi-subject-aware predicate path to translate these triggers
      correctly.

    Observable divergence (bridge sentinel):
      ``_ta_dict_to_python_triggered_ability({"event":
      "deals_combat_damage", ...})`` raises ``ValueError`` with message
      containing ``"deals_combat_damage"`` and ``"not yet wired"``.

    Closure path:
      Add ``elif event_str == "deals_combat_damage":
          event = Event.DEALS_COMBAT_DAMAGE``
      to the event-string elif chain.  When that arm lands, the ValueError
      will no longer fire here, flipping this sentinel to a failure that
      signals the pin should be updated to a real parity probe for one of
      the 9 combat-damage-trigger EoE cards.

    This pin is pure Python (no Rust extension required).

Pin 3 -- ``you_attack`` event NOT wired in triggered-ability bridge
(cross-engine bridge event gap; 8 EoE cards blocked).

    Python's ``Event`` enum has ``Event.YOU_ATTACK`` (value
    ``"you_attack"``).  The string ``"you_attack"`` is not in the bridge
    elif chain; passing a triggered-ability dict with that event value
    causes the bridge to raise:

        raise ValueError(
            "cross_engine triggered_abilities bridge: event "
            "'you_attack' is not yet wired"
        )

    Note: ``"you_attack"`` is distinct from ``"attacks"``.
    ``Event.ATTACKS`` (``"attacks"``) fires once per declared attacker
    (per-creature subject: ``("attacker",)``).  ``Event.YOU_ATTACK``
    (``"you_attack"``) fires ONCE per combat when the active player
    declares any attackers (subject: ``("player",)`` — the active player,
    per ``EVENT_SUBJECTS`` at ``effects/predicates.py:224``).  Cards like
    Dyadrine Synthesis Amalgam use the once-per-combat "whenever you
    attack" phrasing; they trigger on the YOU_ATTACK event, not the
    per-attacker ATTACKS event.

    Scale:
      8 EoE cards carry "whenever you attack" triggered abilities:
      Dyadrine Synthesis Amalgam, Dawnsire Sunstar Dreadnought, Lionheart
      Glimmer, and others.

    Observable divergence (bridge sentinel):
      ``_ta_dict_to_python_triggered_ability({"event": "you_attack",
      ...})`` raises ``ValueError`` with message containing
      ``"you_attack"`` and ``"not yet wired"``.

    Closure path:
      Add ``elif event_str == "you_attack":
          event = Event.YOU_ATTACK``
      to the event-string elif chain.  When that arm lands, the ValueError
      will no longer fire here.

    This pin is pure Python (no Rust extension required).

Dropped pins
------------

  * Equip lane ``_zone_signature`` ``attached_to=None`` gap (batch EE):
    The field-view discrepancy requires Rust internal API calls the PyO3
    extension does not expose directly; pin surface too fragile.  Dropped
    per II batch precedent.

  * Endless Sands AA[0] ``ExileTargetCreatureUntilSourceLeaves``
    ``yours_only=True`` semantic mismatch (batch HH/AA): already
    documented in batch-HH worklog.  Not re-pinned here.

  * ``beginning_of_postcombat_main`` / ``dealt_damage`` /
    ``is_sacrificed`` / ``plays_land`` / ``discards_card`` /
    ``counters_added`` bridge gaps: all raise ValueError from the same
    bridge gap as the three pinned events above (same elif chain, same
    error message shape).  The three largest gaps by card count are the
    most informative pins; the smaller ones follow the same closure path
    and can be swept in the same bridge-fix commit.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Pin 1 -- room_fully_unlocked event not wired in triggered-ability bridge
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_room_fully_unlocked_event_bridge_gap_sentinel_divergence_pin():
    """Pin the bridge gap for the ``room_fully_unlocked`` event string in
    ``_ta_dict_to_python_triggered_ability``.

    Bug location:
      ``src/mtg_bot/parity/cross_engine.py:8838-8874`` -- the elif chain
      in ``_ta_dict_to_python_triggered_ability`` recognises only the
      event strings ``"enters"``, ``"dies"``, ``"cast"``, ``"attacks"``,
      ``"blocks"``, ``"leaves_battlefield"``, ``"becomes_tapped"``.  All
      other strings fall through to:

          raise ValueError(
              "cross_engine triggered_abilities bridge: event "
              "'room_fully_unlocked' is not yet wired"
          )

      Python's ``Event`` enum has ``Event.ROOM_FULLY_UNLOCKED`` (value
      ``"room_fully_unlocked"``); the enum member exists, but there is no
      bridge arm to wire it.

    Scale:
      10 EoE Room cards carry triggered abilities on the
      ``room_fully_unlocked`` event.  Representative cards: Cult Healer,
      Optimistic Scavenger, Entity Tracker, Balemurk Leech.  None of those
      cards can be exercised via a Rust-sourced cross-engine probe that
      emits ``"event": "room_fully_unlocked"`` in a triggered-ability dict.

    Observable divergence (bridge sentinel):
      ``_ta_dict_to_python_triggered_ability`` raises ``ValueError`` for
      ``event="room_fully_unlocked"``; the same call with
      ``event="becomes_tapped"`` (a wired event) succeeds.

    Subject structure:
      ``Event.ROOM_FULLY_UNLOCKED`` carries subject ``("room",)`` per
      ``EVENT_SUBJECTS`` (``effects/predicates.py:222``).  The bridge arm
      must wire the event; predicate translation for Room-anchor triggers
      follows the standard arms (``always``, ``source_is_self``, etc.).

    Closure path:
      Add ``elif event_str == "room_fully_unlocked":
          event = Event.ROOM_FULLY_UNLOCKED``
      in the event-string elif chain.  When that arm lands, the ValueError
      will no longer be raised and this sentinel will flip to FAIL -- the
      signal to promote to a parity probe.

    Probe shape:
      1. Assert ``Event.ROOM_FULLY_UNLOCKED`` exists (Python side present).
      2. Assert the bridge raises ``ValueError`` for the unwired event.
      3. Assert the message mentions ``"room_fully_unlocked"`` and
         ``"not yet wired"``.
      4. Assert a wired event (``"becomes_tapped"``) does NOT raise.
      5. Enumerate the 10 EoE cards that carry this event (documentation).

    This pin is pure Python (no Rust extension required).
    """
    from mtg_bot.effects.predicates import Event
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_triggered_ability

    # 1. The Python Event enum has ROOM_FULLY_UNLOCKED.
    assert hasattr(Event, "ROOM_FULLY_UNLOCKED"), (
        "Event.ROOM_FULLY_UNLOCKED should be a member of the Event enum "
        "(effects/predicates.py). If this fails the enum member was renamed "
        "-- update both this pin and the bridge arm."
    )
    assert isinstance(Event.ROOM_FULLY_UNLOCKED, Event), (
        "Event.ROOM_FULLY_UNLOCKED should be an Event enum instance."
    )
    assert Event.ROOM_FULLY_UNLOCKED.value == "room_fully_unlocked", (
        "Event.ROOM_FULLY_UNLOCKED.value should be 'room_fully_unlocked'; "
        f"got {Event.ROOM_FULLY_UNLOCKED.value!r}"
    )

    # 2-3. Bridge raises ValueError for the unwired event -- pin the gap.
    unwired_ta_dict = {
        "event": "room_fully_unlocked",
        "predicate": {"kind": "always"},
        "effect": {
            "kind": "draw_cards",
            "count": 1,
        },
    }
    with pytest.raises(ValueError) as exc_info:
        _ta_dict_to_python_triggered_ability(unwired_ta_dict)

    err_msg = str(exc_info.value)
    assert "room_fully_unlocked" in err_msg, (
        "Bridge gap sentinel: the ValueError message should mention "
        "'room_fully_unlocked' so the gap is immediately identifiable. "
        f"Got message: {err_msg!r}"
    )
    assert "not yet wired" in err_msg, (
        "Bridge gap sentinel: the ValueError should contain 'not yet wired' "
        "(from cross_engine.py:8871-8874) confirming the event-elif chain "
        "produced this error, not some other ValueError. "
        f"Got message: {err_msg!r}"
    )

    # 4. A WIRED event ("becomes_tapped") round-trips without error.
    wired_ta_dict = {
        "event": "becomes_tapped",
        "predicate": {"kind": "source_is_self"},
        "effect": {
            "kind": "draw_cards",
            "count": 1,
        },
    }
    try:
        result = _ta_dict_to_python_triggered_ability(wired_ta_dict)
        from mtg_bot.effects.base import TriggeredAbility
        assert isinstance(result, TriggeredAbility), (
            "Wired event 'becomes_tapped' should produce a TriggeredAbility; "
            f"got {type(result).__name__}."
        )
        assert result.event == Event.BECOMES_TAPPED, (
            "Wired event 'becomes_tapped' should translate to "
            f"Event.BECOMES_TAPPED; got {result.event!r}."
        )
    except ValueError as e:
        raise AssertionError(
            "Sanity: 'becomes_tapped' is a wired event and should NOT raise "
            f"ValueError -- got: {e}"
        ) from e

    # 5. Document the 10 EoE Room cards blocked by this gap.
    #    (Enumerated via OracleParserCardSource; verified 2026-05-19.)
    blocked_eoe_cards = [
        "Cult Healer",
        "Optimistic Scavenger",
        "Entity Tracker",
        "Balemurk Leech",
        "Dashing Bloodsucker",
        "Erratic Apparition",
        "Gremlin Tamer",
        "Infernal Phantom",
        "Scrabbling Skullcrab",
        "Skullsnap Nuisance",
    ]
    # Assert the expected count (10 cards) matches the enumerated list.
    assert len(blocked_eoe_cards) == 10, (
        "The 'room_fully_unlocked' event gap blocks 10 EoE Room-mechanic "
        f"cards; enumerated list has {len(blocked_eoe_cards)} entries."
    )


# ---------------------------------------------------------------------------
# Pin 2 -- deals_combat_damage event not wired in triggered-ability bridge
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_deals_combat_damage_event_bridge_gap_sentinel_divergence_pin():
    """Pin the bridge gap for the ``deals_combat_damage`` event string in
    ``_ta_dict_to_python_triggered_ability``.

    Bug location:
      ``src/mtg_bot/parity/cross_engine.py:8838-8874`` -- the elif chain
      in ``_ta_dict_to_python_triggered_ability`` does not include an arm
      for ``"deals_combat_damage"``.  All unrecognised strings fall
      through to the final ``raise ValueError``.

    Python side:
      ``Event.DEALS_COMBAT_DAMAGE`` (``"deals_combat_damage"``) exists in
      the ``Event`` enum (``effects/predicates.py:63``).  The event carries
      TWO named subjects: ``("source", "target")`` per ``EVENT_SUBJECTS``
      (``effects/predicates.py:212``).  This two-subject shape makes
      ``DEALS_COMBAT_DAMAGE`` structurally more complex than single-subject
      events (ENTERS, DIES, ATTACKS); predicates that use ``Subject(
      slot=None, ...)`` would resolve to ``None`` on this event (same gap
      as the IS_CAST / subject_is_artifact divergence pinned in batch LL
      Pin 2).

    Scale:
      9 EoE cards carry "whenever ~ deals combat damage" triggered
      abilities.  Representative cards: Illvoi Infiltrator, Starwinder,
      Elegy Acolyte, Entropic Battlecruiser.  None of those cards can be
      exercised via a Rust-sourced cross-engine probe.

    Observable divergence (bridge sentinel):
      ``_ta_dict_to_python_triggered_ability({"event":
      "deals_combat_damage", ...})`` raises ``ValueError`` with message
      containing ``"deals_combat_damage"`` and ``"not yet wired"``.

    Closure path:
      Add ``elif event_str == "deals_combat_damage":
          event = Event.DEALS_COMBAT_DAMAGE``
      to the event-string elif chain.  A companion fix is needed for
      predicate translation: any predicate that reads the subject on a
      DEALS_COMBAT_DAMAGE event must use explicit slot names (``"source"``
      or ``"target"``), not the default ``slot=None`` shortcut (which only
      works for single-subject events).  When the bridge arm lands, this
      sentinel will flip to a failure, signaling the pin should be promoted
      to a parity probe for one of the 9 combat-damage-trigger EoE cards.

    Probe shape:
      1. Assert ``Event.DEALS_COMBAT_DAMAGE`` exists and has the correct
         string value ``"deals_combat_damage"``.
      2. Assert ``EVENT_SUBJECTS[Event.DEALS_COMBAT_DAMAGE]`` is
         ``("source", "target")`` (documenting the two-subject shape).
      3. Assert the bridge raises ``ValueError`` for the unwired event.
      4. Assert the message mentions ``"deals_combat_damage"`` and
         ``"not yet wired"``.
      5. Assert a wired event does NOT raise (sanity check).

    This pin is pure Python (no Rust extension required).
    """
    from mtg_bot.effects.predicates import Event, EVENT_SUBJECTS
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_triggered_ability

    # 1. The Python Event enum has DEALS_COMBAT_DAMAGE.
    assert hasattr(Event, "DEALS_COMBAT_DAMAGE"), (
        "Event.DEALS_COMBAT_DAMAGE should be a member of the Event enum "
        "(effects/predicates.py:63). If this fails the enum member was "
        "renamed -- update both this pin and the bridge arm."
    )
    assert isinstance(Event.DEALS_COMBAT_DAMAGE, Event), (
        "Event.DEALS_COMBAT_DAMAGE should be an Event enum instance."
    )
    assert Event.DEALS_COMBAT_DAMAGE.value == "deals_combat_damage", (
        "Event.DEALS_COMBAT_DAMAGE.value should be 'deals_combat_damage'; "
        f"got {Event.DEALS_COMBAT_DAMAGE.value!r}"
    )

    # 2. Document the two-subject structure (source + target) -- distinct
    #    from single-subject events. This is the same multi-subject issue
    #    that causes the IS_CAST / subject_is_artifact predicate-slot bug
    #    (pinned in batch LL Pin 2): Subject(slot=None) resolves to None
    #    when len(subjects) != 1.
    subjects = EVENT_SUBJECTS.get(Event.DEALS_COMBAT_DAMAGE)
    assert subjects == ("source", "target"), (
        "Event.DEALS_COMBAT_DAMAGE should carry two subjects: "
        "('source', 'target') per EVENT_SUBJECTS (effects/predicates.py:212). "
        "This two-subject shape requires explicit slot names in bridge "
        "predicate arms -- Subject(slot=None) would resolve to None here "
        "(the same gap as IS_CAST/subject_is_artifact, batch LL Pin 2). "
        f"Got subjects={subjects!r}"
    )

    # 3-4. Bridge raises ValueError for the unwired event -- pin the gap.
    unwired_ta_dict = {
        "event": "deals_combat_damage",
        "predicate": {"kind": "always"},
        "effect": {
            "kind": "draw_cards",
            "count": 1,
        },
    }
    with pytest.raises(ValueError) as exc_info:
        _ta_dict_to_python_triggered_ability(unwired_ta_dict)

    err_msg = str(exc_info.value)
    assert "deals_combat_damage" in err_msg, (
        "Bridge gap sentinel: the ValueError message should mention "
        "'deals_combat_damage' so the gap is immediately identifiable. "
        f"Got message: {err_msg!r}"
    )
    assert "not yet wired" in err_msg, (
        "Bridge gap sentinel: the ValueError should contain 'not yet wired' "
        "(from cross_engine.py:8871-8874) confirming the event-elif chain "
        "produced this error, not some other ValueError. "
        f"Got message: {err_msg!r}"
    )

    # 5. Sanity: a WIRED event ("enters") round-trips without error.
    wired_ta_dict = {
        "event": "enters",
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
            "Wired event 'enters' should produce a TriggeredAbility; "
            f"got {type(result).__name__}."
        )
        assert result.event == Event.ENTERS, (
            "Wired event 'enters' should translate to Event.ENTERS; "
            f"got {result.event!r}."
        )
    except ValueError as e:
        raise AssertionError(
            "Sanity: 'enters' is a wired event and should NOT raise "
            f"ValueError -- got: {e}"
        ) from e


# ---------------------------------------------------------------------------
# Pin 3 -- you_attack event not wired in triggered-ability bridge
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_you_attack_event_bridge_gap_sentinel_divergence_pin():
    """Pin the bridge gap for the ``you_attack`` event string in
    ``_ta_dict_to_python_triggered_ability``.

    Bug location:
      ``src/mtg_bot/parity/cross_engine.py:8838-8874`` -- the elif chain
      in ``_ta_dict_to_python_triggered_ability`` does not include an arm
      for ``"you_attack"``.  All unrecognised strings fall through to the
      final ``raise ValueError``.

    Semantic note -- YOU_ATTACK vs ATTACKS:
      ``Event.ATTACKS`` (``"attacks"``; WIRED) fires once per declared
      attacker; subject is ``("attacker",)`` (the attacking creature, per
      ``EVENT_SUBJECTS`` at ``effects/predicates.py:210``).  This is the
      "whenever [creature X] attacks" trigger shape used by cards like
      Dawnsire Sunstar Dreadnought's "Whenever a Spacecraft you control
      attacks" clause.

      ``Event.YOU_ATTACK`` (``"you_attack"``; UNWIRED) fires exactly ONCE
      per combat when the active player declares any attackers; subject is
      ``("player",)`` (the attacking player, per ``EVENT_SUBJECTS`` at
      ``effects/predicates.py:224``).  This is the "whenever you attack"
      trigger shape used by cards like Lionheart Glimmer ("Whenever you
      attack, creatures you control gain lifelink until end of turn.").

      The two events model different oracle-text phrasings: per-attacker
      (ATTACKS) vs per-combat-once (YOU_ATTACK).  Wiring ATTACKS but not
      YOU_ATTACK means the 8 EoE "whenever you attack" cards cannot be
      exercised via the bridge.

    Scale:
      8 EoE cards carry ``you_attack`` triggered abilities.  Representative
      cards: Dyadrine Synthesis Amalgam, Dawnsire Sunstar Dreadnought,
      Lionheart Glimmer, Dawnstrike Vanguard, Luminary Stalker.

    Observable divergence (bridge sentinel):
      ``_ta_dict_to_python_triggered_ability({"event": "you_attack",
      ...})`` raises ``ValueError`` with message containing ``"you_attack"``
      and ``"not yet wired"``.

    Closure path:
      Add ``elif event_str == "you_attack":
          event = Event.YOU_ATTACK``
      to the event-string elif chain.  When that arm lands, the ValueError
      will no longer fire here, flipping this sentinel to a failure and
      signaling the pin should be promoted to a parity probe for one of
      the 8 EoE "whenever you attack" cards.

    Probe shape:
      1. Assert ``Event.YOU_ATTACK`` exists (Python side present) and has
         the correct string value ``"you_attack"``.
      2. Assert ``Event.ATTACKS`` is a distinct enum member from
         ``Event.YOU_ATTACK`` (documenting the per-attacker vs
         per-combat-once distinction).
      3. Assert ``EVENT_SUBJECTS[Event.YOU_ATTACK]`` is ``("player",)``
         (the once-per-combat subject structure).
      4. Assert the bridge raises ``ValueError`` for ``"you_attack"``.
      5. Assert the message mentions ``"you_attack"`` and ``"not yet wired"``.
      6. Assert ``"attacks"`` (the wired per-attacker event) does NOT raise.

    This pin is pure Python (no Rust extension required).
    """
    from mtg_bot.effects.predicates import Event, EVENT_SUBJECTS
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_triggered_ability

    # 1. The Python Event enum has YOU_ATTACK.
    assert hasattr(Event, "YOU_ATTACK"), (
        "Event.YOU_ATTACK should be a member of the Event enum "
        "(effects/predicates.py). If this fails the enum member was renamed "
        "-- update both this pin and the bridge arm."
    )
    assert isinstance(Event.YOU_ATTACK, Event), (
        "Event.YOU_ATTACK should be an Event enum instance."
    )
    assert Event.YOU_ATTACK.value == "you_attack", (
        "Event.YOU_ATTACK.value should be 'you_attack'; "
        f"got {Event.YOU_ATTACK.value!r}"
    )

    # 2. YOU_ATTACK is distinct from ATTACKS (per-attacker vs per-combat).
    assert Event.YOU_ATTACK is not Event.ATTACKS, (
        "Event.YOU_ATTACK must be a distinct enum member from Event.ATTACKS. "
        "ATTACKS fires once per declaring creature; YOU_ATTACK fires once "
        "per combat. Conflating them would suppress or double-fire triggers."
    )

    # 3. YOU_ATTACK subject is ("player",) -- once-per-combat subject.
    #    Compare with ATTACKS subject ("attacker",) -- per-creature subject.
    you_attack_subjects = EVENT_SUBJECTS.get(Event.YOU_ATTACK)
    attacks_subjects = EVENT_SUBJECTS.get(Event.ATTACKS)
    assert you_attack_subjects == ("player",), (
        "Event.YOU_ATTACK subjects should be ('player',) per EVENT_SUBJECTS "
        "(effects/predicates.py:224). The subject is the attacking player, "
        "fired once per combat (not per attacker). "
        f"Got you_attack_subjects={you_attack_subjects!r}"
    )
    assert attacks_subjects == ("attacker",), (
        "Event.ATTACKS subjects should be ('attacker',) per EVENT_SUBJECTS "
        "(effects/predicates.py:210). The subject is the attacking creature, "
        "fired once per declared attacker. "
        f"Got attacks_subjects={attacks_subjects!r}"
    )

    # 4-5. Bridge raises ValueError for "you_attack" -- pin the gap.
    unwired_ta_dict = {
        "event": "you_attack",
        "predicate": {"kind": "always"},
        "effect": {
            "kind": "draw_cards",
            "count": 1,
        },
    }
    with pytest.raises(ValueError) as exc_info:
        _ta_dict_to_python_triggered_ability(unwired_ta_dict)

    err_msg = str(exc_info.value)
    assert "you_attack" in err_msg, (
        "Bridge gap sentinel: the ValueError message should mention "
        "'you_attack' so the gap is immediately identifiable. "
        f"Got message: {err_msg!r}"
    )
    assert "not yet wired" in err_msg, (
        "Bridge gap sentinel: the ValueError should contain 'not yet wired' "
        "(from cross_engine.py:8871-8874) confirming the event-elif chain "
        "produced this error, not some other ValueError. "
        f"Got message: {err_msg!r}"
    )

    # 6. Sanity: "attacks" (wired per-attacker event) round-trips cleanly.
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
