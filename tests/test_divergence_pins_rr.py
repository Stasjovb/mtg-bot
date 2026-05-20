"""Divergence-pin tests: batch RR (probe-batch-rr).

Each test is named ``test_cross_engine_real_eoe_<slug>_*_divergence_pin``
and ASSERTS the CURRENT divergent behavior rather than parity.  The
PROBED-tier detector excludes ``*_divergence_pin`` functions, so these
tests grow the test surface without touching the PROBED metric.

Pinned bugs
-----------

Pin 1 -- ``counters_added`` event NOT wired in triggered-ability bridge
(cross-engine bridge event gap; 2 EoE cards blocked).

    Python's ``Event`` enum (``effects/predicates.py``) has an
    ``Event.COUNTERS_ADDED`` member (value ``"counters_added"``).  The
    string ``"counters_added"`` is not in the bridge's elif chain at
    ``cross_engine.py:8838-8874``; passing a triggered-ability dict with
    that event value causes the function to fall through to:

        raise ValueError(
            "cross_engine triggered_abilities bridge: event "
            "'counters_added' is not yet wired"
        )

    Subject structure:
      ``Event.COUNTERS_ADDED`` carries subject ``("obj",)`` per
      ``EVENT_SUBJECTS`` (``effects/predicates.py``) -- a single subject,
      the permanent that received the counters.  This is the same
      single-subject shape as ``Event.ENTERS`` and ``Event.DIES``, so
      the ``slot=None`` optimisation in ``_resolve_subject`` DOES apply:
      ``Subject(slot=None, ...)`` will correctly resolve to the permanent
      object on a ``COUNTERS_ADDED`` dispatch (unlike the IS_CAST
      two-subject trap pinned in batch LL Pin 2).

    Scale:
      2 EoE cards carry "whenever you put one or more counters on ..."
      triggered abilities that map to ``COUNTERS_ADDED``:
        * Terrasymbiosis -- "Whenever you put one or more +1/+1 counters
          on a creature you control, you may draw that many cards.  Do
          this only once each turn."  (The once-per-turn rider adds a
          stateful gate on top of the bridge gap.)
        * Haliya, Ascendant Cadet -- "Whenever one or more creatures you
          control with +1/+1 counters on them deal combat damage to a
          player, draw a card."  (The combat-damage clause uses a
          different event; only Haliya's counter-placement text maps to
          COUNTERS_ADDED.)

    Observable divergence (bridge sentinel):
      ``_ta_dict_to_python_triggered_ability({"event":
      "counters_added", "predicate": {"kind": "always"}, "effect":
      {"kind": "draw_cards", "count": 1}})`` raises ``ValueError``
      with message containing ``"counters_added"`` and
      ``"not yet wired"``.

    Closure path:
      Add ``elif event_str == "counters_added":
          event = Event.COUNTERS_ADDED``
      to the event-string elif chain in ``_ta_dict_to_python_triggered_ability``.
      When the arm lands, the ValueError will no longer fire, and
      Terrasymbiosis-shaped cards can be exercised via cross-engine
      probes.  The once-per-turn rider on Terrasymbiosis requires a
      separate once-per-turn bridge arm (``max_once_per_turn`` field
      on ``TriggeredAbility`` or equivalent); that is a second closure
      step beyond wiring the event.

    This pin is pure Python (no Rust extension required).

Pin 2 -- ``is_sacrificed`` event NOT wired in triggered-ability bridge
(cross-engine bridge event gap; 2 EoE cards blocked).

    Python's ``Event`` enum has ``Event.IS_SACRIFICED`` (value
    ``"is_sacrificed"``).  The string ``"is_sacrificed"`` is not in the
    bridge elif chain; passing a triggered-ability dict with that event
    value causes the bridge to raise:

        raise ValueError(
            "cross_engine triggered_abilities bridge: event "
            "'is_sacrificed' is not yet wired"
        )

    Subject structure:
      ``Event.IS_SACRIFICED`` carries subject ``("obj",)`` per
      ``EVENT_SUBJECTS`` -- a single subject, the permanent that was
      sacrificed.  Single-subject shape means ``Subject(slot=None, ...)``
      resolves correctly on dispatch (same as ENTERS / DIES).

    Scale:
      2 EoE cards carry "whenever you sacrifice ..." triggered abilities
      that map to ``IS_SACRIFICED``:
        * Lightless Evangel -- "Whenever you sacrifice another creature
          or artifact, put a +1/+1 counter on this creature."
        * Biotech Specialist -- "Whenever you sacrifice an artifact,
          this creature deals 2 damage to target opponent."

      Note: IS_SACRIFICED is distinct from the Python
      ``ExileTargetCreatureUntilSourceLeaves``'s ``yours_only`` flag
      (the HH / AA mismatch) -- the event gap here is purely the
      bridge's elif chain having no arm for ``"is_sacrificed"``.

    Observable divergence (bridge sentinel):
      ``_ta_dict_to_python_triggered_ability({"event":
      "is_sacrificed", ...})`` raises ``ValueError`` with message
      containing ``"is_sacrificed"`` and ``"not yet wired"``.

    Closure path:
      Add ``elif event_str == "is_sacrificed":
          event = Event.IS_SACRIFICED``
      to the event-string elif chain.  When that arm lands, the ValueError
      will no longer fire, enabling Lightless Evangel-style cross-engine
      probes.  The target-opponent constraint in Biotech Specialist's
      damage effect also requires the ``"deal_damage_to_target"`` effect
      bridge arm (a separate closure item).

    This pin is pure Python (no Rust extension required).

Pin 3 -- ``dealt_damage`` event NOT wired in triggered-ability bridge
(cross-engine bridge event gap; 2 EoE cards blocked; distinct from
``deals_combat_damage`` pinned in batch OO).

    Python's ``Event`` enum has BOTH:
      * ``Event.DEALS_COMBAT_DAMAGE`` (``"deals_combat_damage"``; two
        subjects: ``("source", "target")``), pinned in batch OO Pin 2.
        Fires for the DEALER of combat damage; used by "whenever ~ deals
        combat damage to a player" triggers.
      * ``Event.DEALT_DAMAGE`` (``"dealt_damage"``; one subject: ``("obj",)``),
        pinned HERE.  Fires for the RECEIVER of damage; used by "whenever
        ~ is dealt damage" triggers.

    The two events model opposite perspectives of the same damage event.
    Wiring ``deals_combat_damage`` (the dealing side) without wiring
    ``dealt_damage`` (the receiving side) means the 2 EoE cards that
    trigger on the RECEIVING side of damage cannot be exercised via the
    bridge.

    The string ``"dealt_damage"`` is not in the bridge elif chain; passing
    a triggered-ability dict with that event value causes the bridge to
    raise:

        raise ValueError(
            "cross_engine triggered_abilities bridge: event "
            "'dealt_damage' is not yet wired"
        )

    Subject structure:
      ``Event.DEALT_DAMAGE`` carries subject ``("obj",)`` -- a single
      subject, the permanent that was dealt damage.  Single-subject shape
      means ``Subject(slot=None, ...)`` resolves correctly on dispatch.
      This is SIMPLER than ``DEALS_COMBAT_DAMAGE``'s two-subject structure;
      there is no multi-subject slot-resolution trap here.

    Scale:
      2 EoE cards carry "whenever ~ is dealt damage" triggered abilities:
        * Requiem Monolith -- triggers on receiving damage.
        * Pain for All -- triggers on receiving damage.

    Observable divergence (bridge sentinel):
      ``_ta_dict_to_python_triggered_ability({"event":
      "dealt_damage", ...})`` raises ``ValueError`` with message
      containing ``"dealt_damage"`` and ``"not yet wired"``.

    Closure path:
      Add ``elif event_str == "dealt_damage":
          event = Event.DEALT_DAMAGE``
      to the event-string elif chain.  When that arm lands, the ValueError
      will no longer fire.  Note: this is independent of the OO Pin 2
      ``deals_combat_damage`` closure -- both arms must land separately.

    This pin is pure Python (no Rust extension required).

Dropped pins
------------

  * Equip lane ``_zone_signature`` ``attached_to=None`` representation gap
    (batch EE): Dropped in batch OO; not revisited here.

  * Endless Sands AA[0] ``ExileTargetCreatureUntilSourceLeaves``
    ``yours_only=True`` semantic mismatch (batch HH/AA): Already
    documented in batch-HH worklog.  Not re-pinned here.

  * ``beginning_of_postcombat_main`` bridge gap: Follows the same elif-chain
    closure path as the three pinned events above; no EoE cards identified
    with this specific trigger shape via oracle-text sweep.  Dropped for
    now; add when a specific card surfaces.

  * ``discards_card`` bridge gap (1 EoE card: Entropic Battlecruiser):
    Entropic Battlecruiser's discard trigger requires a ``DISCARDS_CARD``
    event arm AND a multi-subject predicate path (subjects: ``("player",)``);
    follow-on closure complexity deferred.  Not pinned in this batch.

  * ``plays_land`` bridge gap (1 EoE card: The Endstone): The Endstone
    combines ``"plays_land"`` AND ``"is_cast"`` in the same trigger clause
    ("Whenever you play a land or cast a spell"); the compound-event shape
    requires disjunction support in the bridge beyond a single elif arm.
    Dropped for now.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Pin 1 -- counters_added event not wired in triggered-ability bridge
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_counters_added_event_bridge_gap_sentinel_FIXED_parity():
    """Pin the bridge gap for the ``counters_added`` event string in
    ``_ta_dict_to_python_triggered_ability``.

    Bug location:
      ``src/mtg_bot/parity/cross_engine.py:8838-8874`` -- the elif chain
      in ``_ta_dict_to_python_triggered_ability`` recognises only the
      event strings ``"enters"``, ``"dies"``, ``"cast"``, ``"attacks"``,
      ``"blocks"``, ``"leaves_battlefield"``, ``"becomes_tapped"``.  All
      other strings fall through to:

          raise ValueError(
              "cross_engine triggered_abilities bridge: event "
              "'counters_added' is not yet wired"
          )

      Python's ``Event`` enum has ``Event.COUNTERS_ADDED`` (value
      ``"counters_added"``); the enum member exists, but there is no
      bridge arm to wire it.

    Scale:
      2 EoE cards carry triggered abilities on the ``counters_added``
      event: Terrasymbiosis and Haliya, Ascendant Cadet.

    Subject structure note:
      ``Event.COUNTERS_ADDED`` carries a single subject ``("obj",)``
      (the permanent that received the counters).  Unlike the IS_CAST
      two-subject trap (batch LL Pin 2), ``Subject(slot=None, ...)``
      WILL resolve correctly on COUNTERS_ADDED dispatch because
      ``_resolve_subject`` returns the lone subject when
      ``len(subjects) == 1``.  The bridge gap is purely the missing
      elif arm -- no predicate-slot fix is needed alongside it.

    Closure path:
      Add ``elif event_str == "counters_added":
          event = Event.COUNTERS_ADDED``
      in the event-string elif chain.  When that arm lands, the
      ValueError will no longer be raised and this sentinel will flip
      to FAIL -- the signal to promote to a parity probe for
      Terrasymbiosis or Haliya, Ascendant Cadet.

    Probe shape:
      1. Assert ``Event.COUNTERS_ADDED`` exists and has the correct
         string value ``"counters_added"``.
      2. Assert ``EVENT_SUBJECTS[Event.COUNTERS_ADDED]`` is ``("obj",)``
         (documenting the single-subject shape and the absence of the
         IS_CAST multi-subject slot trap).
      3. Assert the bridge raises ``ValueError`` for the unwired event.
      4. Assert the message mentions ``"counters_added"`` and
         ``"not yet wired"``.
      5. Assert a wired event (``"dies"``) does NOT raise (sanity).
      6. Enumerate the 2 EoE cards blocked by this gap.

    This pin is pure Python (no Rust extension required).
    """
    from mtg_bot.effects.predicates import Event, EVENT_SUBJECTS
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_triggered_ability

    # 1. The Python Event enum has COUNTERS_ADDED.
    assert hasattr(Event, "COUNTERS_ADDED"), (
        "Event.COUNTERS_ADDED should be a member of the Event enum "
        "(effects/predicates.py). If this fails the enum member was renamed "
        "-- update both this pin and the bridge arm."
    )
    assert isinstance(Event.COUNTERS_ADDED, Event), (
        "Event.COUNTERS_ADDED should be an Event enum instance."
    )
    assert Event.COUNTERS_ADDED.value == "counters_added", (
        "Event.COUNTERS_ADDED.value should be 'counters_added'; "
        f"got {Event.COUNTERS_ADDED.value!r}"
    )

    # 2. COUNTERS_ADDED has a single subject ("obj",) -- NOT a two-subject
    #    event. Subject(slot=None, ...) resolves correctly here.
    subjects = EVENT_SUBJECTS.get(Event.COUNTERS_ADDED)
    assert subjects == ("obj",), (
        "Event.COUNTERS_ADDED should carry one subject: ('obj',) per "
        "EVENT_SUBJECTS (effects/predicates.py). This single-subject shape "
        "means Subject(slot=None, ...) resolves correctly -- unlike IS_CAST's "
        "two-subject ('spell', 'controller') shape (batch LL Pin 2). "
        f"Got subjects={subjects!r}"
    )

    # 3-4. FIXED: Bridge now translates "counters_added" without raising.
    #      Inversion of the original divergence-pin assertion — the elif arm
    #      was added in the RR slice and the ValueError is no longer raised.
    now_wired_ta_dict = {
        "event": "counters_added",
        "predicate": {"kind": "always"},
        "effect": {
            "kind": "draw_cards",
            "count": 1,
        },
    }
    from mtg_bot.effects.base import TriggeredAbility
    try:
        result = _ta_dict_to_python_triggered_ability(now_wired_ta_dict)
    except ValueError as e:
        raise AssertionError(
            "RR Pin 1 FIXED: 'counters_added' should now be wired in the "
            f"bridge elif chain and must NOT raise ValueError -- got: {e}"
        ) from e
    assert isinstance(result, TriggeredAbility), (
        "RR Pin 1 FIXED: 'counters_added' bridge result must be a "
        f"TriggeredAbility; got {type(result).__name__}."
    )
    assert result.event == Event.COUNTERS_ADDED, (
        "RR Pin 1 FIXED: 'counters_added' bridge result event must be "
        f"Event.COUNTERS_ADDED; got {result.event!r}."
    )

    # 5. Sanity: a previously-WIRED event ("dies") still round-trips cleanly.
    wired_ta_dict = {
        "event": "dies",
        "predicate": {"kind": "always"},
        "effect": {
            "kind": "draw_cards",
            "count": 1,
        },
    }
    try:
        dies_result = _ta_dict_to_python_triggered_ability(wired_ta_dict)
        assert isinstance(dies_result, TriggeredAbility), (
            "Wired event 'dies' should produce a TriggeredAbility; "
            f"got {type(dies_result).__name__}."
        )
        assert dies_result.event == Event.DIES, (
            "Wired event 'dies' should translate to Event.DIES; "
            f"got {dies_result.event!r}."
        )
    except ValueError as e:
        raise AssertionError(
            "Sanity: 'dies' is a wired event and should NOT raise "
            f"ValueError -- got: {e}"
        ) from e

    # 6. Document the 2 EoE cards now unblocked.
    unblocked_eoe_cards = [
        "Terrasymbiosis",        # "Whenever you put one or more +1/+1 counters on
                                 #  a creature you control, you may draw that many
                                 #  cards. Do this only once each turn."
        "Haliya, Ascendant Cadet",  # "Whenever one or more creatures you control
                                    #  with +1/+1 counters on them deal combat damage
                                    #  to a player, draw a card."
    ]
    assert len(unblocked_eoe_cards) == 2, (
        "The 'counters_added' event wire unblocks 2 EoE cards (Terrasymbiosis, "
        f"Haliya, Ascendant Cadet); enumerated list has {len(unblocked_eoe_cards)} entries."
    )


# ---------------------------------------------------------------------------
# Pin 2 -- is_sacrificed event not wired in triggered-ability bridge
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_is_sacrificed_event_bridge_gap_sentinel_FIXED_parity():
    """Pin the bridge gap for the ``is_sacrificed`` event string in
    ``_ta_dict_to_python_triggered_ability``.

    Bug location:
      ``src/mtg_bot/parity/cross_engine.py:8838-8874`` -- the elif chain
      in ``_ta_dict_to_python_triggered_ability`` does not include an arm
      for ``"is_sacrificed"``.  All unrecognised strings fall through to
      the final ``raise ValueError``.

    Semantic note -- IS_SACRIFICED vs related events:
      ``Event.IS_SACRIFICED`` fires on the PERMANENT that was sacrificed
      (subject: ``("obj",)``).  This is a game-action event distinct from:
        * ``Event.DIES`` (``"dies"``; WIRED) -- fires when any permanent
          goes to the graveyard from the battlefield, including via
          sacrifice; subject ``("obj",)``.
        * The HH/AA ``ExileTargetCreatureUntilSourceLeaves`` /
          ``yours_only=True`` mismatch (a semantic gap in a different
          effect class, not an event-bridge gap).

      Cards that say "whenever you sacrifice ..." trigger on IS_SACRIFICED,
      not on DIES, because the trigger condition is specifically the
      sacrifice action rather than the general death event.  This is the
      same distinction that exists between CR 701.17 (sacrifice) and
      CR 700.4 (a permanent "dies").

    Scale:
      2 EoE cards carry "whenever you sacrifice ..." triggered abilities:
        * Lightless Evangel -- "Whenever you sacrifice another creature
          or artifact, put a +1/+1 counter on this creature."
        * Biotech Specialist -- "Whenever you sacrifice an artifact,
          this creature deals 2 damage to target opponent."

    Observable divergence (bridge sentinel):
      ``_ta_dict_to_python_triggered_ability({"event":
      "is_sacrificed", ...})`` raises ``ValueError`` with message
      containing ``"is_sacrificed"`` and ``"not yet wired"``.

    Closure path:
      Add ``elif event_str == "is_sacrificed":
          event = Event.IS_SACRIFICED``
      to the event-string elif chain.  When that arm lands, the ValueError
      will no longer fire.  Biotech Specialist additionally requires a
      ``deal_damage_to_target_opponent`` effect bridge arm (a second
      closure step).

    Probe shape:
      1. Assert ``Event.IS_SACRIFICED`` exists and has the correct string
         value ``"is_sacrificed"``.
      2. Assert ``EVENT_SUBJECTS[Event.IS_SACRIFICED]`` is ``("obj",)``
         (single subject -- the sacrificed permanent).
      3. Assert IS_SACRIFICED is distinct from DIES (documenting the
         sacrifice-vs-death semantic distinction).
      4. Assert the bridge raises ``ValueError`` for the unwired event.
      5. Assert the message mentions ``"is_sacrificed"`` and
         ``"not yet wired"``.
      6. Assert a wired event (``"leaves_battlefield"``) does NOT raise.

    This pin is pure Python (no Rust extension required).
    """
    from mtg_bot.effects.predicates import Event, EVENT_SUBJECTS
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_triggered_ability

    # 1. The Python Event enum has IS_SACRIFICED.
    assert hasattr(Event, "IS_SACRIFICED"), (
        "Event.IS_SACRIFICED should be a member of the Event enum "
        "(effects/predicates.py). If this fails the enum member was renamed "
        "-- update both this pin and the bridge arm."
    )
    assert isinstance(Event.IS_SACRIFICED, Event), (
        "Event.IS_SACRIFICED should be an Event enum instance."
    )
    assert Event.IS_SACRIFICED.value == "is_sacrificed", (
        "Event.IS_SACRIFICED.value should be 'is_sacrificed'; "
        f"got {Event.IS_SACRIFICED.value!r}"
    )

    # 2. IS_SACRIFICED has a single subject ("obj",).
    subjects = EVENT_SUBJECTS.get(Event.IS_SACRIFICED)
    assert subjects == ("obj",), (
        "Event.IS_SACRIFICED should carry one subject: ('obj',) per "
        "EVENT_SUBJECTS (effects/predicates.py). The subject is the "
        "permanent that was sacrificed. "
        f"Got subjects={subjects!r}"
    )

    # 3. IS_SACRIFICED is distinct from DIES -- sacrifice-specific vs
    #    general-death. Cards that say 'whenever you sacrifice ...' trigger
    #    on IS_SACRIFICED; cards that say 'whenever ~ dies' trigger on DIES.
    #    Both events fire when a permanent is sacrificed; IS_SACRIFICED
    #    additionally lets predicates distinguish the sacrifice cause.
    assert Event.IS_SACRIFICED is not Event.DIES, (
        "Event.IS_SACRIFICED must be a distinct enum member from Event.DIES. "
        "'Whenever you sacrifice ...' (IS_SACRIFICED) is oracle-text-distinct "
        "from 'whenever ~ dies' (DIES) even though sacrifice causes death; "
        "conflating them would mis-fire or suppress triggers."
    )

    # 4-5. FIXED: Bridge now translates "is_sacrificed" without raising.
    #      Inversion of the original divergence-pin assertion — the elif arm
    #      was added in the RR slice and the ValueError is no longer raised.
    now_wired_ta_dict = {
        "event": "is_sacrificed",
        "predicate": {"kind": "always"},
        "effect": {
            "kind": "draw_cards",
            "count": 1,
        },
    }
    from mtg_bot.effects.base import TriggeredAbility
    try:
        result = _ta_dict_to_python_triggered_ability(now_wired_ta_dict)
    except ValueError as e:
        raise AssertionError(
            "RR Pin 2 FIXED: 'is_sacrificed' should now be wired in the "
            f"bridge elif chain and must NOT raise ValueError -- got: {e}"
        ) from e
    assert isinstance(result, TriggeredAbility), (
        "RR Pin 2 FIXED: 'is_sacrificed' bridge result must be a "
        f"TriggeredAbility; got {type(result).__name__}."
    )
    assert result.event == Event.IS_SACRIFICED, (
        "RR Pin 2 FIXED: 'is_sacrificed' bridge result event must be "
        f"Event.IS_SACRIFICED; got {result.event!r}."
    )

    # 6. Sanity: a previously-WIRED event ("leaves_battlefield") still round-trips.
    wired_ta_dict = {
        "event": "leaves_battlefield",
        "predicate": {"kind": "always"},
        "effect": {
            "kind": "draw_cards",
            "count": 1,
        },
    }
    try:
        ltb_result = _ta_dict_to_python_triggered_ability(wired_ta_dict)
        assert isinstance(ltb_result, TriggeredAbility), (
            "Wired event 'leaves_battlefield' should produce a TriggeredAbility; "
            f"got {type(ltb_result).__name__}."
        )
        assert ltb_result.event == Event.LEAVES_BATTLEFIELD, (
            "Wired event 'leaves_battlefield' should translate to "
            f"Event.LEAVES_BATTLEFIELD; got {ltb_result.event!r}."
        )
    except ValueError as e:
        raise AssertionError(
            "Sanity: 'leaves_battlefield' is a wired event and should NOT "
            f"raise ValueError -- got: {e}"
        ) from e


# ---------------------------------------------------------------------------
# Pin 3 -- dealt_damage event not wired in triggered-ability bridge
#          (distinct from deals_combat_damage pinned in batch OO)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_dealt_damage_event_bridge_gap_sentinel_FIXED_parity():
    """Pin the bridge gap for the ``dealt_damage`` event string in
    ``_ta_dict_to_python_triggered_ability``.

    Bug location:
      ``src/mtg_bot/parity/cross_engine.py:8838-8874`` -- the elif chain
      in ``_ta_dict_to_python_triggered_ability`` does not include an arm
      for ``"dealt_damage"``.  All unrecognised strings fall through to the
      final ``raise ValueError``.

    Semantic note -- DEALT_DAMAGE vs DEALS_COMBAT_DAMAGE (batch OO Pin 2):
      Two distinct events model opposite perspectives of a damage exchange:

        ``Event.DEALS_COMBAT_DAMAGE`` (``"deals_combat_damage"``; UNWIRED,
        pinned in batch OO Pin 2; two subjects: ``("source", "target")``):
          Fires from the DEALER's perspective.  Used by "whenever ~ deals
          combat damage to a player" triggers (e.g. Illvoi Infiltrator,
          Starwinder).  The two-subject structure means Subject(slot=None)
          resolves to None -- an additional predicate-slot fix is needed
          alongside the elif arm (also documented in OO Pin 2).

        ``Event.DEALT_DAMAGE`` (``"dealt_damage"``; UNWIRED, pinned HERE;
        one subject: ``("obj",)``):
          Fires from the RECEIVER's perspective.  Used by "whenever ~ is
          dealt damage" triggers (e.g. Requiem Monolith, Pain for All).
          The single-subject structure means Subject(slot=None) resolves
          correctly -- no predicate-slot companion fix is needed.

      The batch OO Pin 2 closure (wiring ``deals_combat_damage``) does NOT
      close this gap: the two elif arms must be added independently.

    Scale:
      2 EoE cards carry "whenever ~ is dealt damage" triggered abilities:
        * Requiem Monolith -- triggers when it is dealt damage.
        * Pain for All -- triggers when a player or permanent is dealt damage.

    Observable divergence (bridge sentinel):
      ``_ta_dict_to_python_triggered_ability({"event":
      "dealt_damage", ...})`` raises ``ValueError`` with message
      containing ``"dealt_damage"`` and ``"not yet wired"``.

    Closure path:
      Add ``elif event_str == "dealt_damage":
          event = Event.DEALT_DAMAGE``
      to the event-string elif chain.  When that arm lands, the ValueError
      will no longer fire.  Because ``DEALT_DAMAGE`` is single-subject, no
      predicate-slot companion fix is needed (contrast OO Pin 2).

    Probe shape:
      1. Assert ``Event.DEALT_DAMAGE`` exists and has value
         ``"dealt_damage"``.
      2. Assert ``Event.DEALS_COMBAT_DAMAGE`` is a DISTINCT enum member
         (documenting the dealer-vs-receiver distinction and confirming the
         OO Pin 2 closure would not accidentally close this gap).
      3. Assert ``EVENT_SUBJECTS[Event.DEALT_DAMAGE]`` is ``("obj",)``
         (single subject; contrast OO Pin 2's two-subject
         ``("source", "target")`` for DEALS_COMBAT_DAMAGE).
      4. Assert the bridge raises ``ValueError`` for ``"dealt_damage"``.
      5. Assert the message mentions ``"dealt_damage"`` and
         ``"not yet wired"``.
      6. Assert a wired event (``"enters"``) does NOT raise (sanity).

    This pin is pure Python (no Rust extension required).
    """
    from mtg_bot.effects.predicates import Event, EVENT_SUBJECTS
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_triggered_ability

    # 1. The Python Event enum has DEALT_DAMAGE.
    assert hasattr(Event, "DEALT_DAMAGE"), (
        "Event.DEALT_DAMAGE should be a member of the Event enum "
        "(effects/predicates.py). If this fails the enum member was renamed "
        "-- update both this pin and the bridge arm."
    )
    assert isinstance(Event.DEALT_DAMAGE, Event), (
        "Event.DEALT_DAMAGE should be an Event enum instance."
    )
    assert Event.DEALT_DAMAGE.value == "dealt_damage", (
        "Event.DEALT_DAMAGE.value should be 'dealt_damage'; "
        f"got {Event.DEALT_DAMAGE.value!r}"
    )

    # 2. DEALT_DAMAGE is distinct from DEALS_COMBAT_DAMAGE (batch OO Pin 2).
    #    Closing OO Pin 2 (wiring deals_combat_damage) does NOT close this
    #    gap; they require separate elif arms.
    assert Event.DEALT_DAMAGE is not Event.DEALS_COMBAT_DAMAGE, (
        "Event.DEALT_DAMAGE must be a distinct enum member from "
        "Event.DEALS_COMBAT_DAMAGE. They model opposite perspectives: "
        "DEALT_DAMAGE fires on the RECEIVER ('whenever ~ is dealt damage'); "
        "DEALS_COMBAT_DAMAGE fires on the DEALER ('whenever ~ deals combat "
        "damage to a player'). Wiring one does not wire the other."
    )

    # 3. DEALT_DAMAGE has a single subject ("obj",) -- simpler than
    #    DEALS_COMBAT_DAMAGE's two-subject ("source", "target") structure.
    #    Subject(slot=None, ...) resolves correctly here (single-subject
    #    optimisation in _resolve_subject applies).
    dealt_subjects = EVENT_SUBJECTS.get(Event.DEALT_DAMAGE)
    deals_combat_subjects = EVENT_SUBJECTS.get(Event.DEALS_COMBAT_DAMAGE)
    assert dealt_subjects == ("obj",), (
        "Event.DEALT_DAMAGE should carry one subject: ('obj',) per "
        "EVENT_SUBJECTS (effects/predicates.py). This single-subject shape "
        "means Subject(slot=None, ...) resolves correctly -- unlike "
        "DEALS_COMBAT_DAMAGE's two-subject shape (OO Pin 2). "
        f"Got dealt_subjects={dealt_subjects!r}"
    )
    assert deals_combat_subjects == ("source", "target"), (
        "Event.DEALS_COMBAT_DAMAGE should carry two subjects: "
        "('source', 'target') per EVENT_SUBJECTS (as documented in OO Pin 2). "
        "Confirming the structural difference between the two damage events. "
        f"Got deals_combat_subjects={deals_combat_subjects!r}"
    )

    # 4-5. FIXED: Bridge now translates "dealt_damage" without raising.
    #      Inversion of the original divergence-pin assertion — the elif arm
    #      was added in the RR slice and the ValueError is no longer raised.
    now_wired_ta_dict = {
        "event": "dealt_damage",
        "predicate": {"kind": "always"},
        "effect": {
            "kind": "draw_cards",
            "count": 1,
        },
    }
    from mtg_bot.effects.base import TriggeredAbility
    try:
        result = _ta_dict_to_python_triggered_ability(now_wired_ta_dict)
    except ValueError as e:
        raise AssertionError(
            "RR Pin 3 FIXED: 'dealt_damage' should now be wired in the "
            f"bridge elif chain and must NOT raise ValueError -- got: {e}"
        ) from e
    assert isinstance(result, TriggeredAbility), (
        "RR Pin 3 FIXED: 'dealt_damage' bridge result must be a "
        f"TriggeredAbility; got {type(result).__name__}."
    )
    assert result.event == Event.DEALT_DAMAGE, (
        "RR Pin 3 FIXED: 'dealt_damage' bridge result event must be "
        f"Event.DEALT_DAMAGE; got {result.event!r}."
    )

    # 6. Sanity: a previously-WIRED event ("enters") still round-trips cleanly.
    wired_ta_dict = {
        "event": "enters",
        "predicate": {"kind": "always"},
        "effect": {
            "kind": "draw_cards",
            "count": 1,
        },
    }
    try:
        enters_result = _ta_dict_to_python_triggered_ability(wired_ta_dict)
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
