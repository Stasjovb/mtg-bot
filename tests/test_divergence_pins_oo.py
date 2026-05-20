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


def test_cross_engine_real_eoe_room_fully_unlocked_event_bridge_gap_sentinel_FIXED_parity():
    """**OO Pin 1 CLOSED (9th Rust slice — room_fully_unlocked bridge arm).**

    The bridge gap for ``"room_fully_unlocked"`` in
    ``_ta_dict_to_python_triggered_ability`` is now FIXED.

    **What was broken (pre-9th-slice):**
      ``_ta_dict_to_python_triggered_ability`` raised ``ValueError:
      event 'room_fully_unlocked' is not yet wired`` for any
      triggered-ability dict with ``"event": "room_fully_unlocked"``.
      10 EoE Room-mechanic cards were blocked from cross-engine probing.

    **What was fixed:**
      Added ``elif event_str == "room_fully_unlocked":``
          ``event = Event.ROOM_FULLY_UNLOCKED``
      to the event-string elif chain in ``_ta_dict_to_python_triggered_ability``
      (``cross_engine.py``).  The bridge now maps the string value to the
      correct ``Event`` enum member without raising.

    **Scope note:**
      This fix is pure Python — no Rust extension change required.  The
      ``UnlockRoomHalf`` dispatch in Rust is still a stub (``state_ops_actions.rs``
      raises ``ValueError`` — Room half-state is not yet in Rust's
      ``GameObject``).  The bridge arm lands independently; Room-unlock
      triggers will fire in real cross-engine games once a future slice
      adds ``unlocked_halves`` to Rust's ``GameObject`` and flips the
      dispatch stub.

    **Assertions (inverted from the former divergence-pin):**
      1. ``Event.ROOM_FULLY_UNLOCKED`` exists and has value
         ``"room_fully_unlocked"``.
      2. The bridge does NOT raise for ``event="room_fully_unlocked"``.
      3. The result is a ``TriggeredAbility`` with
         ``event == Event.ROOM_FULLY_UNLOCKED``.
      4. Enumerate the 10 EoE cards unblocked at the bridge layer.

    **EoE cards unblocked at the bridge layer (10 cards):**
      Cult Healer, Optimistic Scavenger, Entity Tracker, Balemurk Leech,
      Dashing Bloodsucker, Erratic Apparition, Gremlin Tamer, Infernal
      Phantom, Scrabbling Skullcrab, Skullsnap Nuisance.
    """
    from mtg_bot.effects.predicates import Event
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_triggered_ability
    from mtg_bot.effects.base import TriggeredAbility

    # 1. The Python Event enum has ROOM_FULLY_UNLOCKED with the correct value.
    assert hasattr(Event, "ROOM_FULLY_UNLOCKED"), (
        "Event.ROOM_FULLY_UNLOCKED should be a member of the Event enum "
        "(effects/predicates.py). If this fails the enum member was renamed "
        "-- update both this test and the bridge arm."
    )
    assert isinstance(Event.ROOM_FULLY_UNLOCKED, Event), (
        "Event.ROOM_FULLY_UNLOCKED should be an Event enum instance."
    )
    assert Event.ROOM_FULLY_UNLOCKED.value == "room_fully_unlocked", (
        "Event.ROOM_FULLY_UNLOCKED.value should be 'room_fully_unlocked'; "
        f"got {Event.ROOM_FULLY_UNLOCKED.value!r}"
    )

    # 2-3. Bridge NO LONGER raises for "room_fully_unlocked" -- OO Pin 1 CLOSED.
    ta_dict = {
        "event": "room_fully_unlocked",
        "predicate": {"kind": "always"},
        "effect": {
            "kind": "draw_cards",
            "count": 1,
        },
    }
    result = _ta_dict_to_python_triggered_ability(ta_dict)
    assert isinstance(result, TriggeredAbility), (
        "Bridge should produce a TriggeredAbility for event='room_fully_unlocked'; "
        f"got {type(result).__name__}."
    )
    assert result.event == Event.ROOM_FULLY_UNLOCKED, (
        "Bridge should map event_str 'room_fully_unlocked' to "
        f"Event.ROOM_FULLY_UNLOCKED; got {result.event!r}."
    )

    # Sanity: "becomes_tapped" (previously wired) still round-trips cleanly.
    wired_ta_dict = {
        "event": "becomes_tapped",
        "predicate": {"kind": "source_is_self"},
        "effect": {
            "kind": "draw_cards",
            "count": 1,
        },
    }
    wired_result = _ta_dict_to_python_triggered_ability(wired_ta_dict)
    assert isinstance(wired_result, TriggeredAbility), (
        "Regression: 'becomes_tapped' should still produce a TriggeredAbility; "
        f"got {type(wired_result).__name__}."
    )
    assert wired_result.event == Event.BECOMES_TAPPED, (
        "Regression: 'becomes_tapped' should still translate to "
        f"Event.BECOMES_TAPPED; got {wired_result.event!r}."
    )

    # 4. Enumerate the 10 EoE cards unblocked at the bridge layer.
    #    (Enumerated via OracleParserCardSource; verified 2026-05-19.)
    unblocked_eoe_cards = [
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
    assert len(unblocked_eoe_cards) == 10, (
        "OO Pin 1 closure unblocks 10 EoE Room-mechanic cards at the bridge "
        f"layer; enumerated list has {len(unblocked_eoe_cards)} entries."
    )


# ---------------------------------------------------------------------------
# Pin 2 -- deals_combat_damage event not wired in triggered-ability bridge
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_deals_combat_damage_event_bridge_FIXED_parity():
    """Verify the ``deals_combat_damage`` bridge arm is NOW wired correctly.

    Round-13 wired the ``"deals_combat_damage"`` / ``"deals_damage"``
    event string in ``_ta_dict_to_python_triggered_ability``.  This test
    was previously a ``_divergence_pin`` sentinel asserting the ValueError
    (the gap was real); after the fix it asserts the CORRECT behavior:

    1. ``Event.DEALS_COMBAT_DAMAGE`` exists with the right string value.
    2. ``EVENT_SUBJECTS[Event.DEALS_COMBAT_DAMAGE]`` is
       ``("source", "target")`` — two-subject shape, still intact.
    3. ``_ta_dict_to_python_triggered_ability({"event":
       "deals_combat_damage", ...})`` now produces a ``TriggeredAbility``
       with ``event == Event.DEALS_COMBAT_DAMAGE`` (no ValueError).
    4. The ``"deals_damage"`` spelling (Rust TA dict key) also round-trips
       to ``Event.DEALS_COMBAT_DAMAGE`` — bridge accepts both spellings.
    5. A ``source_is_self`` predicate on a deals_combat_damage TA gets
       rewritten to ``IsSelf(subject="source")`` by
       ``_rewrite_predicate_for_deals_combat_damage`` — the LL Pin 2
       multi-subject hazard fix.

    Renamed from ``_divergence_pin`` to ``_FIXED_parity`` following the
    pattern established in batch DD (grant_keyword bridge fix).
    """
    from mtg_bot.effects.predicates import Event, EVENT_SUBJECTS, IsSelf
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_triggered_ability
    from mtg_bot.effects.base import TriggeredAbility

    # 1. The Python Event enum still has DEALS_COMBAT_DAMAGE.
    assert hasattr(Event, "DEALS_COMBAT_DAMAGE"), (
        "Event.DEALS_COMBAT_DAMAGE should be a member of the Event enum."
    )
    assert Event.DEALS_COMBAT_DAMAGE.value == "deals_combat_damage"

    # 2. Two-subject shape documented: ("source", "target").
    subjects = EVENT_SUBJECTS.get(Event.DEALS_COMBAT_DAMAGE)
    assert subjects == ("source", "target"), (
        f"Expected ('source', 'target'); got {subjects!r}"
    )

    # 3. Bridge now wires "deals_combat_damage" -- no ValueError.
    ta_dict_python_key = {
        "event": "deals_combat_damage",
        "predicate": {"kind": "always"},
        "effect": {"kind": "draw_cards", "count": 1},
    }
    result = _ta_dict_to_python_triggered_ability(ta_dict_python_key)
    assert isinstance(result, TriggeredAbility), (
        f"Expected TriggeredAbility; got {type(result).__name__}"
    )
    assert result.event == Event.DEALS_COMBAT_DAMAGE, (
        f"Expected DEALS_COMBAT_DAMAGE; got {result.event!r}"
    )

    # 4. Rust spelling "deals_damage" also accepted.
    ta_dict_rust_key = {
        "event": "deals_damage",
        "predicate": {"kind": "always"},
        "effect": {"kind": "draw_cards", "count": 1},
    }
    result2 = _ta_dict_to_python_triggered_ability(ta_dict_rust_key)
    assert isinstance(result2, TriggeredAbility)
    assert result2.event == Event.DEALS_COMBAT_DAMAGE

    # 5. source_is_self predicate gets slot-rewritten to IsSelf(subject="source")
    #    so the two-subject event resolves correctly (LL Pin 2 fix).
    ta_dict_self = {
        "event": "deals_combat_damage",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "draw_cards", "count": 1},
    }
    result3 = _ta_dict_to_python_triggered_ability(ta_dict_self)
    assert isinstance(result3.predicate, IsSelf), (
        f"Expected IsSelf predicate; got {type(result3.predicate).__name__}"
    )
    assert result3.predicate.subject == "source", (
        f"Expected IsSelf(subject='source'); got subject={result3.predicate.subject!r}"
    )


# ---------------------------------------------------------------------------
# Pin 3 -- you_attack event bridge gap CLOSED (round-15 YOU_ATTACK slice)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_you_attack_event_bridge_gap_sentinel_FIXED_parity():
    """**OO Pin 3 CLOSED (round-15 YOU_ATTACK bridge slice).**

    The bridge gap for ``"you_attack"`` in
    ``_ta_dict_to_python_triggered_ability`` is now FIXED.

    **What was broken (pre-round-15):**
      ``_ta_dict_to_python_triggered_ability`` raised ``ValueError:
      event 'you_attack' is not yet wired`` for any triggered-ability
      dict with ``"event": "you_attack"``.  8 EoE "whenever you attack"
      cards were blocked from cross-engine probing.

    **What was fixed (round-15 Rust + bridge slice):**
      1. ``Event::YouAttack`` added to Rust ``Event`` enum (``cards.rs``).
      2. Parse arm ``"you_attack" => Event::YouAttack`` added to
         ``parse_triggered_ability`` (``cards.rs``).
      3. ``Event::YouAttack`` added to the ``dispatch_event`` allow-list
         (``state_ops_resolve.rs``).
      4. Dispatch site added in the ``DeclareAttackers`` arm of
         ``apply_action`` (``state_ops_actions.rs``): fires once after
         the per-attacker loop when ``state.attackers`` grew, using
         ``PLAYER_SUBJECT_OFFSET + active_player`` as subject_id.
      5. Bridge arm ``elif event_str == "you_attack":
         event = Event.YOU_ATTACK`` added to
         ``_ta_dict_to_python_triggered_ability`` (``cross_engine.py``).

    **Semantic note — YOU_ATTACK vs ATTACKS:**
      ``Event.ATTACKS`` fires once per declared attacker; subject is
      ``("attacker",)`` (the attacking creature). ``Event.YOU_ATTACK``
      fires ONCE per combat; subject is ``("player",)`` (the attacking
      player). Two distinct oracle-text phrasings.

    **8 EoE cards unlocked:** Dyadrine Synthesis Amalgam, Dawnsire
    Sunstar Dreadnought, Lionheart Glimmer, Surgical Suite // Hospital
    Room, Derelict Attic // Widow's Walk, Most Valuable Slayer,
    Razorkin Hordecaller, Ticket Booth // Tunnel of Hate.

    **Companion probe:** ``tests/test_probe_you_attack_unlock.py`` —
    Lionheart Glimmer pump-all-creatures-you-control-until-EOT
    cross-engine byte-equality probe (_parity suffix).

    This pin is pure Python (no Rust extension required for the
    assertion inversions, though the Rust changes must be built for
    the full probe).
    """
    from mtg_bot.effects.predicates import Event, EVENT_SUBJECTS
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_triggered_ability

    # 1. The Python Event enum has YOU_ATTACK (unchanged from gap era).
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

    # 2. YOU_ATTACK is distinct from ATTACKS (unchanged from gap era).
    assert Event.YOU_ATTACK is not Event.ATTACKS, (
        "Event.YOU_ATTACK must be a distinct enum member from Event.ATTACKS. "
        "ATTACKS fires once per declaring creature; YOU_ATTACK fires once "
        "per combat. Conflating them would suppress or double-fire triggers."
    )

    # 3. YOU_ATTACK subject is ("player",) (unchanged from gap era).
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

    # **INVERTED from the gap-era pin**: "you_attack" now translates
    # WITHOUT raising ValueError.
    you_attack_ta_dict = {
        "event": "you_attack",
        "predicate": {"kind": "always"},
        "effect": {
            "kind": "draw_cards",
            "count": 1,
        },
    }
    try:
        result = _ta_dict_to_python_triggered_ability(you_attack_ta_dict)
    except ValueError as e:
        raise AssertionError(
            "OO Pin 3 regression: bridge arm for 'you_attack' is missing "
            "-- _ta_dict_to_python_triggered_ability raised ValueError: "
            f"{e}"
        ) from e

    assert isinstance(result, TriggeredAbility), (
        "Bridge for 'you_attack' must produce a TriggeredAbility; "
        f"got {type(result).__name__}."
    )
    assert result.event == Event.YOU_ATTACK, (
        "Bridge must translate 'you_attack' to Event.YOU_ATTACK; "
        f"got {result.event!r}."
    )

    # Sanity: "attacks" (wired per-attacker event) still round-trips cleanly.
    wired_ta_dict = {
        "event": "attacks",
        "predicate": {"kind": "always"},
        "effect": {
            "kind": "draw_cards",
            "count": 1,
        },
    }
    try:
        attacks_result = _ta_dict_to_python_triggered_ability(wired_ta_dict)
        assert isinstance(attacks_result, TriggeredAbility), (
            "Sanity: 'attacks' must still produce a TriggeredAbility; "
            f"got {type(attacks_result).__name__}."
        )
        assert attacks_result.event == Event.ATTACKS, (
            "Sanity: 'attacks' must still translate to Event.ATTACKS; "
            f"got {attacks_result.event!r}."
        )
    except ValueError as e:
        raise AssertionError(
            "Sanity: 'attacks' is a wired event and should NOT raise "
            f"ValueError -- got: {e}"
        ) from e
