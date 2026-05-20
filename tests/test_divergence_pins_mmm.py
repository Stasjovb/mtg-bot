"""Divergence-pin tests: batch MMM (probe-batch-mmm, round 20).

Each test is named ``test_cross_engine_real_eoe_<slug>_*_divergence_pin``
and ASSERTS the CURRENT divergent behavior rather than parity.  The
PROBED-tier detector excludes ``*_divergence_pin`` functions, so these
tests grow the test surface without touching the PROBED metric.

Pinned bugs
-----------

Pin 1 -- ``spells_cast_this_turn`` StatePredicate kind NOT wired in the
Python cross-engine state-predicate bridge (4 EoE cards blocked).

    Python's ``SpellsCastThisTurn`` class
    (``cards/parser/triggers.py``) is a frozen dataclass with one
    required field -- ``n: int`` -- that implements the
    "whenever you cast your Nth spell each turn" oracle pattern.  It
    is a ``StatePredicate`` (``effects/state_predicates.py``) and is
    used inside a ``StateBound`` trigger predicate wrapper:

        ``StateBound(inner=SpellsCastThisTurn(n=2))``

    The two-tier bridge in ``cross_engine.py``:
      * Tier 1 (``_ta_dict_to_python_predicate``): handles
        ``kind="state_bound"`` by delegating the inner dict to
        ``_ta_dict_to_python_state_predicate`` -- WIRED.
      * Tier 2 (``_ta_dict_to_python_state_predicate``): handles
        ``kind="void_active"`` and
        ``kind="any_player_controls_no_creatures"`` -- does NOT
        handle ``kind="spells_cast_this_turn"``.  The terminal error
        arm raises::

            ValueError: "cross_engine triggered_abilities bridge:
            unsupported StatePredicate kind 'spells_cast_this_turn'
            (extend `_ta_dict_to_python_state_predicate` ...)"

    The Rust ``parse_state_predicate`` (``rust/src/cards.rs``) is
    equally limited: its ``match`` arm only recognises ``"void_active"``
    and ``"any_player_controls_no_creatures"``; the terminal error arm
    explicitly lists only those two as valid.  Passing a dict with
    ``kind="spells_cast_this_turn"`` to the Rust function raises
    ``PyValueError`` with ``"unknown StatePredicate kind 'spells_cast_this_turn'"``
    (or similar).

    The "you cast your second spell each turn" predicate composition is:

        ``And(left=Controlled(YOU), right=StateBound(SpellsCastThisTurn(n=2)))``

    The outer ``And`` and ``Controlled`` arms ARE wired in both the
    Python bridge and the Rust parser; the blocker is exclusively the
    ``SpellsCastThisTurn`` inner kind.

    Scale (EoE cards blocked):
      * Cosmogrand Zenith -- "Whenever you cast your second spell each
        turn, choose one -- Create two 1/1 white Human Soldier creature
        tokens; or Put a +1/+1 counter on each creature you control."
      * Sunstar Lightsmith -- "Whenever you cast your second spell each
        turn, put a +1/+1 counter on this creature and draw a card."
      * Illvoi Operative -- "Whenever you cast your second spell each
        turn, put a +1/+1 counter on this creature."
      * Station Monitor -- "Whenever you cast your second spell each
        turn, create a 1/1 colorless Drone artifact creature token with
        flying ..."

    Observable divergence:
      ``_ta_dict_to_python_state_predicate({"kind":
      "spells_cast_this_turn", "n": 2})`` raises ``ValueError``
      (unsupported StatePredicate kind).  The analogous ``void_active``
      call succeeds.

    Closure path:
      1. Add ``"spells_cast_this_turn"`` arm to Python
         ``_ta_dict_to_python_state_predicate`` in ``cross_engine.py``
         that reads ``n`` (int) and constructs
         ``SpellsCastThisTurn(n=n)``.
      2. Add ``"spells_cast_this_turn"`` arm to Rust
         ``parse_state_predicate`` in ``cards.rs`` that reads ``n``
         (i32) and constructs ``StatePredicate::SpellsCastThisTurn { n }``.
      3. Add a ``StatePredicate::SpellsCastThisTurn`` variant to the
         Rust ``StatePredicate`` enum and its ``test`` logic (checks
         ``state.spells_cast_this_turn[viewer_id] >= n``).
      4. Wire a ``spells_cast_this_turn`` counter per player in Rust
         ``GameState`` -- increment in the ``CastSpell`` resolve arm,
         reset at each cleanup step (alongside ``life_gained_this_turn``).

Pin 2 -- ``discards_card`` event string NOT wired in the Python
cross-engine event bridge (Entropic Battlecruiser blocked at the
bridge layer).

    Python's ``Event.DISCARDS_CARD`` enum member (value
    ``"discards_card"``) encodes "whenever an opponent discards a card"
    triggers.  The string ``"discards_card"`` is NOT in the
    ``_ta_dict_to_python_triggered_ability`` event-string elif chain in
    ``cross_engine.py``; passing a triggered-ability dict with
    ``"event": "discards_card"`` causes the bridge to fall through to::

        raise ValueError(
            "cross_engine triggered_abilities bridge: event
            'discards_card' is not yet wired"
        )

    The Rust ``dispatch_event`` allowlist (``state_ops_resolve.rs``)
    does NOT include a ``DiscardCard`` event variant; the Rust
    ``Event`` enum (``cards.rs``) does not declare one either.
    Both engines need the event added before real parity probes are
    possible.  The Python bridge gap is the first-layer blocker.

    Companion predicate gap: Entropic Battlecruiser's trigger uses
    ``Controlled(by=OPPONENT)`` as its predicate ("whenever an
    OPPONENT discards ..."), which requires a
    ``kind="controlled_by_opponent"`` dict.  That predicate kind is
    also NOT wired in the Python bridge ``_ta_dict_to_python_predicate``
    (see Pin 3 below for the predicate gap; this pin focuses on the
    event-string gap).

    Scale (EoE card with ``DISCARDS_CARD`` triggered ability):
      * Entropic Battlecruiser (1+ tier) -- "Whenever an opponent
        discards a card, they lose 3 life."
        Parser: ``Event.DISCARDS_CARD + Controlled(by=OPPONENT)``
        trigger; effect: ``TargetPlayerLosesLife(amount=3)`` (the
        discarding player is pre-wired as the target via
        ``fixed_targets`` in the dispatch call).

    Observable divergence:
      ``_ta_dict_to_python_triggered_ability({"event": "discards_card",
      ...})`` raises ``ValueError`` with message containing
      ``"discards_card"`` and ``"not yet wired"``.  The analogous
      ``_ta_dict_to_python_triggered_ability({"event": "is_sacrificed",
      ...})`` call (a wired event added in RR) succeeds.

    Closure path:
      Add ``elif event_str == "discards_card":
          event = Event.DISCARDS_CARD``
      to the event-string elif chain in
      ``_ta_dict_to_python_triggered_ability``.  When that arm lands, the
      ValueError will no longer fire here; the companion
      ``controlled_by_opponent`` predicate gap (Pin 3) becomes the next
      blocker.  Full end-to-end parity additionally requires the Rust
      ``Event::DiscardsCard`` variant, its ``parse_triggered_ability``
      arm, and a ``dispatch_event`` dispatch site (at the Python
      cleanup-hand discard chokepoint in ``turn.py``).

Pin 3 -- ``controlled_by_opponent`` predicate kind NOT wired in the
Python cross-engine predicate bridge (observer-opponent triggers
blocked).

    Python's ``Controlled(by=OPPONENT, subject=None)`` trigger predicate
    (``effects/predicates.py``) encodes "the subject of this event is
    controlled by an opponent of the source's controller."  It is the
    dual of ``Controlled(by=YOU, subject=None)`` which IS wired in the
    bridge as ``kind="controlled_by_you"``.

    The ``_ta_dict_to_python_predicate`` function in ``cross_engine.py``
    handles ``kind="controlled_by_you"`` via an explicit if-arm that
    returns ``Controlled(by=YOU)``.  There is NO corresponding arm for
    ``kind="controlled_by_opponent"``; passing such a dict causes the
    bridge to fall through to::

        raise ValueError(
            "cross_engine triggered_abilities bridge: unsupported
            predicate kind 'controlled_by_opponent'"
        )

    Rust's ``parse_predicate`` likewise has only ``"controlled_by_you"``
    and no ``"controlled_by_opponent"`` arm.

    This gap blocks all "observer-opponent" triggered abilities -- triggers
    that fire when something belonging to an opponent satisfies the
    event predicate.  Entropic Battlecruiser's ``DISCARDS_CARD`` trigger
    is the prime EoE example (predicate: "an opponent discards", i.e.,
    the discarding player is an opponent of the source's controller).

    Observable divergence:
      ``_ta_dict_to_python_predicate({"kind": "controlled_by_opponent"})``
      raises ``ValueError`` with message containing
      ``"controlled_by_opponent"`` and ``"unsupported predicate kind"``.
      The analogous call with ``{"kind": "controlled_by_you"}`` succeeds
      and returns ``Controlled(by=YOU)``.

    Closure path:
      Add ``if kind == "controlled_by_opponent":
          return Controlled(by=OPPONENT)``
      to the elif chain in ``_ta_dict_to_python_predicate``, mirroring
      the ``"controlled_by_you"`` arm.  Add a corresponding
      ``"controlled_by_opponent" => Ok(Predicate::ControlledByOpponent)``
      arm to Rust ``parse_predicate`` with a new enum variant
      ``Predicate::ControlledByOpponent`` whose ``matches`` logic checks
      ``subject_controller != source_controller``.

Dropped pins
------------

  * Room_fully_unlocked (OO Pin 1, 10 cards): deferred -- Room subsystem
    not yet scoped.

  * would_create_token (UU Pin 2): preemptive structural guard, deferred.

  * DrawCardsByConditionMultiplier (GGG Pin 3 / AAA Pin 3): deferred --
    Condition serialization not yet designed.

  * dyadrine_attack_effect + put_poison_counters_on_target_player Rust
    parse_effect gaps (JJJ Pin 1+2): NNN concurrent sibling is targeting
    these; not re-pinned here.

  * DDD Pins 1+2+3 (SurveyMechanActivationEffect / ExileTopXOfLibrary /
    SearchLibraryForEquipmentToBattlefield): still deferred.

  * beginning_of_postcombat_main bridge gap: deferred -- no EoE card in
    edge_of_eternities.json currently exercises this event; pinning
    would create a test with zero card coverage.

  * conditional_if_you_gained_life_at_least Rust parse_effect gap (JJJ
    Pin 3): NNN scope includes this; not re-pinned here.
"""

from __future__ import annotations

import dataclasses

import pytest


# ---------------------------------------------------------------------------
# Pin 1 -- spells_cast_this_turn StatePredicate NOT wired in bridge
#          (Python _ta_dict_to_python_state_predicate + Rust parse_state_predicate)
#          4 EoE cards blocked: Cosmogrand Zenith, Sunstar Lightsmith,
#          Illvoi Operative, Station Monitor
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_spells_cast_this_turn_state_predicate_bridge_gap_divergence_pin():
    """Pin the state-predicate bridge gap for ``spells_cast_this_turn``.

    Bug location (Python layer):
      ``src/mtg_bot/parity/cross_engine.py`` --
      ``_ta_dict_to_python_state_predicate`` handles only
      ``"void_active"`` and ``"any_player_controls_no_creatures"``.
      Passing ``kind="spells_cast_this_turn"`` reaches the terminal
      ``raise ValueError`` arm.

    Bug location (Rust layer -- structural, no compiled extension):
      ``rust/src/cards.rs`` -- ``fn parse_state_predicate`` match arms
      list only ``"void_active"`` and
      ``"any_player_controls_no_creatures"`` as valid.  The terminal
      ``other =>`` arm raises ``PyValueError`` with the invalid kind.

    EoE cards blocked (4):
      * Cosmogrand Zenith
      * Sunstar Lightsmith
      * Illvoi Operative
      * Station Monitor
      All carry "Whenever you cast your second spell each turn" triggers
      whose predicate composes to
      ``And(Controlled(YOU), StateBound(SpellsCastThisTurn(n=2)))``.
      The outer ``And``/``Controlled``/``StateBound`` arms ARE wired;
      the ``SpellsCastThisTurn`` inner kind is the sole blocker.

    Probe shape:
      1. Assert ``SpellsCastThisTurn`` is a ``StatePredicate`` dataclass
         with one required field ``n``.
      2. Assert ``void_active`` round-trips through the state-predicate
         bridge without error (sanity: analogous wired kind).
      3. Assert ``spells_cast_this_turn`` raises ``ValueError`` from the
         state-predicate bridge (Python gap; gap sentinel).
      4. Assert the error message mentions ``"spells_cast_this_turn"``
         so the gap is immediately identifiable.
      5. Assert the full second-spell TA dict (``cast`` event +
         ``And(controlled_by_you, state_bound(spells_cast_this_turn))``
         predicate) also raises, confirming the gap cascades up through
         the full bridge call.
      6. Enumerate the 4 EoE cards blocked by this gap.

    Closure path:
      Add ``"spells_cast_this_turn"`` arm to Python
      ``_ta_dict_to_python_state_predicate`` (reads ``n`` int, returns
      ``SpellsCastThisTurn(n=n)``).  Rust counterpart: add
      ``"spells_cast_this_turn"`` to ``parse_state_predicate`` + enum
      variant + ``test`` logic + per-player counter in ``GameState``.
    """
    from mtg_bot.cards.parser.triggers import SpellsCastThisTurn
    from mtg_bot.effects.state_predicates import StatePredicate, VoidActive
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_state_predicate,
        _ta_dict_to_python_triggered_ability,
    )

    # 1. SpellsCastThisTurn is a StatePredicate dataclass with field 'n'.
    assert issubclass(SpellsCastThisTurn, StatePredicate), (
        "SpellsCastThisTurn should be a StatePredicate subclass "
        "(cards/parser/triggers.py).  "
        "If this fails the class hierarchy changed -- update this pin."
    )
    assert dataclasses.is_dataclass(SpellsCastThisTurn), (
        "SpellsCastThisTurn should be a dataclass.  "
        "If this fails the class was restructured -- update this pin."
    )
    fields = {f.name: f for f in dataclasses.fields(SpellsCastThisTurn)}
    assert "n" in fields, (
        "SpellsCastThisTurn should have a field named 'n' (the spell-count "
        "threshold, e.g. n=2 for 'your second spell').  "
        f"Got fields: {list(fields.keys())!r}"
    )
    assert fields["n"].default is dataclasses.MISSING, (
        "SpellsCastThisTurn.n should have no default -- it is a required "
        "constructor argument; the bridge arm MUST read it from the dict.  "
        f"Got default: {fields['n'].default!r}"
    )
    # Verify the class is usable.
    sc_instance = SpellsCastThisTurn(n=2)
    assert sc_instance.n == 2, (
        f"SpellsCastThisTurn(n=2).n should be 2; got {sc_instance.n!r}"
    )

    # 2. Sanity: 'void_active' round-trips through the state-predicate
    #    bridge without error (the analogous wired StatePredicate kind).
    try:
        wired_result = _ta_dict_to_python_state_predicate({"kind": "void_active"})
        assert wired_result is not None, (
            "Sanity: 'void_active' state predicate bridge should return a "
            "non-None object; got None."
        )
    except (ValueError, Exception) as e:
        raise AssertionError(
            "Sanity: 'void_active' is a wired StatePredicate kind and should "
            "NOT raise from _ta_dict_to_python_state_predicate.  "
            f"Got: {e}"
        ) from e

    # 3. 'spells_cast_this_turn' raises ValueError (Python bridge gap).
    with pytest.raises(ValueError) as exc_info:
        _ta_dict_to_python_state_predicate(
            {"kind": "spells_cast_this_turn", "n": 2}
        )

    err_msg = str(exc_info.value)

    # 4. Error message identifies the gap kind.
    assert "spells_cast_this_turn" in err_msg, (
        "Bridge gap sentinel: the ValueError message should mention "
        "'spells_cast_this_turn' so the gap is immediately identifiable.  "
        f"Got message: {err_msg!r}.  "
        "If 'spells_cast_this_turn' is absent from the message, the terminal "
        "error arm changed -- update this assertion."
    )

    # 5. Full second-spell TA dict (the real composition) also fails.
    #    Dict shape mirrors what the parser produces:
    #    IS_CAST event (bridge key 'cast') + And(controlled_by_you,
    #    state_bound(spells_cast_this_turn)) + put_plus_one_counter_on_self.
    second_spell_ta_dict = {
        "event": "cast",
        "predicate": {
            "kind": "and",
            "left": {"kind": "controlled_by_you"},
            "right": {
                "kind": "state_bound",
                "inner": {"kind": "spells_cast_this_turn", "n": 2},
            },
        },
        "effect": {"kind": "put_plus_one_counter_on_self"},
    }
    with pytest.raises(ValueError) as full_exc_info:
        _ta_dict_to_python_triggered_ability(second_spell_ta_dict)

    full_err = str(full_exc_info.value)
    assert "spells_cast_this_turn" in full_err, (
        "Full second-spell TA bridge should also raise mentioning "
        "'spells_cast_this_turn'.  "
        f"Got: {full_err!r}.  "
        "If the error message changed, update this assertion."
    )

    # 6. Enumerate the 4 EoE cards blocked by this state-predicate gap.
    blocked_eoe_cards = [
        "Cosmogrand Zenith",
        # "Whenever you cast your second spell each turn, choose one --
        #  Create two 1/1 white Human Soldier creature tokens; or Put a
        #  +1/+1 counter on each creature you control."
        # Predicate: And(Controlled(YOU), StateBound(SpellsCastThisTurn(n=2)))
        "Sunstar Lightsmith",
        # "Whenever you cast your second spell each turn, put a +1/+1
        #  counter on this creature and draw a card."
        # Predicate: And(Controlled(YOU), StateBound(SpellsCastThisTurn(n=2)))
        "Illvoi Operative",
        # "Whenever you cast your second spell each turn, put a +1/+1
        #  counter on this creature."
        # Predicate: And(Controlled(YOU), StateBound(SpellsCastThisTurn(n=2)))
        "Station Monitor",
        # "Whenever you cast your second spell each turn, create a 1/1
        #  colorless Drone artifact creature token with flying ..."
        # Predicate: And(Controlled(YOU), StateBound(SpellsCastThisTurn(n=2)))
    ]
    assert len(blocked_eoe_cards) == 4, (
        "The 'spells_cast_this_turn' StatePredicate bridge gap blocks 4 EoE "
        f"cards; enumerated list has {len(blocked_eoe_cards)} entries.  "
        "Update the list if new cards are found or the count changes."
    )


# ---------------------------------------------------------------------------
# Pin 2 -- discards_card event string NOT wired in triggered-ability bridge
#          (Entropic Battlecruiser 1+ tier blocked at the bridge layer)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_discards_card_event_bridge_gap_divergence_pin():
    """Pin the bridge gap for the ``discards_card`` event string in
    ``_ta_dict_to_python_triggered_ability``.

    Bug location:
      ``src/mtg_bot/parity/cross_engine.py`` --
      ``_ta_dict_to_python_triggered_ability``'s event-string elif chain
      does NOT include ``"discards_card"``.  Passing a triggered-ability
      dict with ``"event": "discards_card"`` causes the bridge to fall
      through to::

          raise ValueError(
              "cross_engine triggered_abilities bridge: event
              'discards_card' is not yet wired"
          )

    Rust-side gap (structural):
      The Rust ``Event`` enum (``rust/src/cards.rs``) has no
      ``DiscardCard`` (or equivalent) variant.  The Rust
      ``dispatch_event`` allowlist (``state_ops_resolve.rs``) likewise
      does not include it.  Until both the Python bridge and the Rust
      event machinery are wired, no cross-engine probe for
      Entropic Battlecruiser's 1+ tier trigger is possible.

    EoE card blocked (1):
      * Entropic Battlecruiser (1+ tier) -- "Whenever an opponent
        discards a card, they lose 3 life."
        Parser: ``Event.DISCARDS_CARD + Controlled(by=OPPONENT)``
        predicate; effect: ``TargetPlayerLosesLife(amount=3)``.
        Both the companion predicate gap (``controlled_by_opponent`` --
        Pin 3 below) and this event gap must be closed before a
        parity probe is possible.

    Relationship to the existing wired events:
      ``"is_sacrificed"`` (RR Pin 2 CLOSED), ``"counters_added"``
      (RR Pin 1 CLOSED), and ``"dealt_damage"`` (RR Pin 3 CLOSED)
      are all now wired in the bridge's elif chain.
      ``"discards_card"`` was noted in the OO batch's dropped-pins
      section; this pin provides the formal test surface.

    Observable divergence:
      ``_ta_dict_to_python_triggered_ability({"event": "discards_card",
      ...})`` raises ``ValueError`` with message containing
      ``"discards_card"`` and ``"not yet wired"``.
      The analogous call with ``{"event": "is_sacrificed", ...}``
      (a wired event from the RR batch) succeeds.

    Probe shape:
      1. Assert ``Event.DISCARDS_CARD`` exists in the Python enum and
         has the expected string value ``"discards_card"``.
      2. Assert the bridge raises ``ValueError`` for
         ``event="discards_card"`` (pin the gap).
      3. Assert the error message contains ``"discards_card"`` and
         ``"not yet wired"``.
      4. Assert a wired event (``"is_sacrificed"``) does NOT raise
         (sanity: the same bridge function works for recently-added
         events).
      5. Enumerate the EoE card blocked by this gap.

    Closure path:
      Add ``elif event_str == "discards_card":
          event = Event.DISCARDS_CARD``
      to the event-string elif chain.  Full end-to-end parity also
      requires the Rust ``Event::DiscardsCard`` variant +
      ``parse_triggered_ability`` arm + ``dispatch_event`` entry +
      a dispatch site at Python's cleanup-hand discard chokepoint
      (``turn.py:dispatch_discards_card_event``).
    """
    from mtg_bot.effects.predicates import Event, EVENT_SUBJECTS
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_triggered_ability
    from mtg_bot.effects.base import TriggeredAbility

    # 1. Event.DISCARDS_CARD exists in the Python enum.
    assert hasattr(Event, "DISCARDS_CARD"), (
        "Event.DISCARDS_CARD should be a member of the Event enum "
        "(effects/predicates.py).  "
        "If this fails the enum member was renamed -- update this pin."
    )
    assert isinstance(Event.DISCARDS_CARD, Event), (
        "Event.DISCARDS_CARD should be an Event enum instance."
    )
    assert Event.DISCARDS_CARD.value == "discards_card", (
        "Event.DISCARDS_CARD.value should be 'discards_card'; "
        f"got {Event.DISCARDS_CARD.value!r}"
    )
    # Subject shape: ('player',) -- the discarding player.
    dc_subjects = EVENT_SUBJECTS.get(Event.DISCARDS_CARD)
    assert dc_subjects == ("player",), (
        "Event.DISCARDS_CARD subjects should be ('player',) per "
        "EVENT_SUBJECTS (effects/predicates.py).  "
        f"Got: {dc_subjects!r}"
    )

    # 2-3. Bridge raises ValueError for the unwired event.
    unwired_ta_dict = {
        "event": "discards_card",
        "predicate": {"kind": "always"},
        "effect": {"kind": "draw_cards", "count": 1},
    }
    with pytest.raises(ValueError) as exc_info:
        _ta_dict_to_python_triggered_ability(unwired_ta_dict)

    err_msg = str(exc_info.value)
    assert "discards_card" in err_msg, (
        "Bridge gap sentinel: the ValueError message should mention "
        "'discards_card' so the gap is immediately identifiable.  "
        f"Got message: {err_msg!r}.  "
        "If 'discards_card' is absent, the error-arm message changed -- "
        "update this assertion."
    )
    assert "not yet wired" in err_msg, (
        "Bridge gap sentinel: the ValueError should contain 'not yet wired' "
        "(from the terminal event-elif fallthrough).  "
        f"Got message: {err_msg!r}.  "
        "If the message changed, update this assertion."
    )

    # 4. A wired event ('is_sacrificed', added in RR slice) does NOT raise.
    wired_ta_dict = {
        "event": "is_sacrificed",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "draw_cards", "count": 1},
    }
    try:
        result = _ta_dict_to_python_triggered_ability(wired_ta_dict)
        assert isinstance(result, TriggeredAbility), (
            "Wired event 'is_sacrificed' should produce a TriggeredAbility; "
            f"got {type(result).__name__}."
        )
        assert result.event == Event.IS_SACRIFICED, (
            "Wired event 'is_sacrificed' should translate to "
            f"Event.IS_SACRIFICED; got {result.event!r}."
        )
    except ValueError as e:
        raise AssertionError(
            "Sanity: 'is_sacrificed' is a wired event (RR slice) and should "
            f"NOT raise ValueError -- got: {e}"
        ) from e

    # 5. EoE card blocked by this gap.
    blocked_eoe_cards = [
        "Entropic Battlecruiser",
        # 1+ tier: "Whenever an opponent discards a card, they lose 3 life."
        # Parser: Event.DISCARDS_CARD + Controlled(by=OPPONENT)
        # Effect: TargetPlayerLosesLife(amount=3)
        # Companion gap: controlled_by_opponent predicate (Pin 3 below)
    ]
    assert len(blocked_eoe_cards) == 1, (
        "The 'discards_card' event bridge gap blocks 1 EoE card; "
        f"enumerated list has {len(blocked_eoe_cards)} entries."
    )


# ---------------------------------------------------------------------------
# Pin 3 -- controlled_by_opponent predicate NOT wired in Python bridge
#          (observer-opponent triggers blocked at the predicate layer)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_controlled_by_opponent_predicate_bridge_gap_divergence_pin():
    """Pin the bridge gap for the ``controlled_by_opponent`` predicate kind
    in ``_ta_dict_to_python_predicate``.

    Bug location (Python bridge):
      ``src/mtg_bot/parity/cross_engine.py`` --
      ``_ta_dict_to_python_predicate`` handles ``"controlled_by_you"``
      via an explicit if-arm that returns ``Controlled(by=YOU)``.  There
      is NO corresponding arm for ``"controlled_by_opponent"``; passing
      such a dict causes the bridge to fall through to::

          raise ValueError(
              "cross_engine triggered_abilities bridge: unsupported
              predicate kind 'controlled_by_opponent'"
          )

    Bug location (Rust parser -- structural):
      ``rust/src/cards.rs`` -- ``fn parse_predicate`` handles
      ``"controlled_by_you"`` via ``Ok(Predicate::ControlledByYou)``.
      There is no ``"controlled_by_opponent"`` arm.

    Scope:
      ``Controlled(by=OPPONENT)`` is needed for any triggered ability
      where the OBSERVER fires when the EVENT SUBJECT belongs to an
      opponent -- e.g. "whenever an opponent discards a card" (subject
      = the discarding player, predicate checks it is an opponent of the
      source's controller).

    Observable divergence:
      ``_ta_dict_to_python_predicate({"kind": "controlled_by_opponent"})``
      raises ``ValueError`` with message containing
      ``"controlled_by_opponent"`` and ``"unsupported predicate kind"``.
      The analogous ``_ta_dict_to_python_predicate({"kind":
      "controlled_by_you"})`` succeeds and returns
      ``Controlled(by=YOU)``.

    Python side -- Controlled class structure:
      ``Controlled(by: _Controller, subject: str | None = None)``
      from ``effects/predicates.py``.  ``_Controller.YOU`` maps to the
      string ``"you"``; ``_Controller.OPPONENT`` maps to ``"opponent"``.
      The bridge arm for ``"controlled_by_you"`` constructs
      ``Controlled(by=YOU)``.  The missing arm would construct
      ``Controlled(by=OPPONENT)``.

    Probe shape:
      1. Assert ``Event.DISCARDS_CARD`` + ``Controlled(OPPONENT)`` is
         the predicate composition Entropic Battlecruiser uses (document
         the pair via the parser's trigger-phrase table).
      2. Assert ``Controlled(by=YOU)`` bridge arm (``"controlled_by_you"``)
         succeeds (sanity: the symmetric wired predicate).
      3. Assert ``Controlled(by=OPPONENT)`` bridge arm
         (``"controlled_by_opponent"``) raises ``ValueError`` (pin the
         gap).
      4. Assert the error message contains ``"controlled_by_opponent"``
         and ``"unsupported predicate kind"``.
      5. Assert that the full Entropic Battlecruiser TA dict
         (discards_card event + controlled_by_opponent predicate) fails at
         the event layer (Pin 2) rather than the predicate layer, since
         the event is checked first in the bridge.
      6. Enumerate the EoE card(s) that need ``controlled_by_opponent``.

    Closure path:
      Add ``if kind == "controlled_by_opponent":
          return Controlled(by=OPPONENT)``
      to the elif chain in ``_ta_dict_to_python_predicate``, mirroring
      the ``"controlled_by_you"`` arm.  Add a Rust counterpart
      ``"controlled_by_opponent" =>
          Ok(Predicate::ControlledByOpponent)`` with a new enum variant
      whose ``matches`` logic checks that the subject's controller is
      NOT the source's controller (i.e., is an opponent).
    """
    from mtg_bot.effects.predicates import (
        Controlled, YOU, OPPONENT, Event,
    )
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_predicate,
        _ta_dict_to_python_triggered_ability,
    )
    from mtg_bot.cards.parser.triggers import _PREDICATE_TRIGGER_PHRASES

    # 1. Document the Entropic Battlecruiser predicate composition.
    #    The phrasebook maps "an opponent discards a card" to
    #    (Event.DISCARDS_CARD, Controlled(by=OPPONENT)).
    phrase_key = "an opponent discards a card"
    assert phrase_key in _PREDICATE_TRIGGER_PHRASES, (
        "The trigger phrasebook should map 'an opponent discards a card' "
        "to (Event.DISCARDS_CARD, Controlled(OPPONENT)).  "
        f"Got phrasebook keys (sample): {list(_PREDICATE_TRIGGER_PHRASES.keys())[:10]!r}.  "
        "If the phrase changed, update this assertion."
    )
    event_val, pred_val = _PREDICATE_TRIGGER_PHRASES[phrase_key]
    assert event_val == Event.DISCARDS_CARD, (
        f"Phrasebook 'an opponent discards a card' should map to "
        f"Event.DISCARDS_CARD; got {event_val!r}"
    )
    assert isinstance(pred_val, Controlled), (
        f"Phrasebook predicate should be a Controlled instance; "
        f"got {type(pred_val).__name__!r}"
    )
    assert pred_val.by == OPPONENT, (
        f"Phrasebook predicate should be Controlled(by=OPPONENT); "
        f"got by={pred_val.by!r}"
    )

    # 2. Sanity: 'controlled_by_you' IS wired and returns Controlled(YOU).
    try:
        wired = _ta_dict_to_python_predicate({"kind": "controlled_by_you"})
        assert isinstance(wired, Controlled), (
            "Bridge for 'controlled_by_you' should return a Controlled instance; "
            f"got {type(wired).__name__!r}."
        )
        assert wired.by == YOU, (
            f"Bridge for 'controlled_by_you' should return Controlled(by=YOU); "
            f"got by={wired.by!r}."
        )
    except ValueError as e:
        raise AssertionError(
            "Sanity: 'controlled_by_you' is a wired predicate kind and should "
            f"NOT raise -- got: {e}"
        ) from e

    # 3-4. 'controlled_by_opponent' raises ValueError (Python bridge gap).
    with pytest.raises(ValueError) as exc_info:
        _ta_dict_to_python_predicate({"kind": "controlled_by_opponent"})

    err_msg = str(exc_info.value)
    assert "controlled_by_opponent" in err_msg, (
        "Bridge gap sentinel: the ValueError message should mention "
        "'controlled_by_opponent' so the gap is immediately identifiable.  "
        f"Got message: {err_msg!r}."
    )
    assert "unsupported predicate kind" in err_msg, (
        "Bridge gap sentinel: the ValueError should contain 'unsupported "
        "predicate kind' (from the terminal error arm in "
        "_ta_dict_to_python_predicate).  "
        f"Got message: {err_msg!r}."
    )

    # 5. Full Entropic Battlecruiser TA dict fails at the EVENT layer (Pin 2)
    #    rather than the predicate layer, because the bridge checks the event
    #    string before parsing the predicate.  This confirms Pin 2 and Pin 3
    #    are layered blockers -- the event gap is the outer blocker.
    entropic_ta_dict = {
        "event": "discards_card",
        "predicate": {"kind": "controlled_by_opponent"},
        "effect": {"kind": "target_player_loses_life", "amount": 3},
    }
    with pytest.raises(ValueError) as full_exc_info:
        _ta_dict_to_python_triggered_ability(entropic_ta_dict)

    full_err = str(full_exc_info.value)
    # The event check happens first -- the error should be about "discards_card"
    # (the event gap from Pin 2), not "controlled_by_opponent" (Pin 3).
    assert "discards_card" in full_err, (
        "Full Entropic Battlecruiser TA dict should fail with the event-gap "
        "error ('discards_card' not yet wired) since the event is checked "
        "before the predicate.  "
        f"Got error: {full_err!r}.  "
        "If the error mentions 'controlled_by_opponent' instead, the bridge "
        "changed parse order -- update both Pin 2 and Pin 3 accordingly."
    )

    # 6. EoE card(s) that need 'controlled_by_opponent'.
    blocked_eoe_cards = [
        "Entropic Battlecruiser",
        # 1+ tier: "Whenever an opponent discards a card, they lose 3 life."
        # Predicate: Controlled(by=OPPONENT) on DISCARDS_CARD event.
        # Both discards_card (Pin 2) and controlled_by_opponent (Pin 3)
        # must be closed before a parity probe is possible.
    ]
    assert len(blocked_eoe_cards) == 1, (
        "The 'controlled_by_opponent' predicate bridge gap directly blocks "
        "1 EoE card (in combination with the discards_card event gap); "
        f"enumerated list has {len(blocked_eoe_cards)} entries."
    )
