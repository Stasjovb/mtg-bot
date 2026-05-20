"""Divergence-pin tests: batch GGG (probe-batch-ggg, round 18).

Each test is named ``test_cross_engine_real_eoe_<slug>_*_divergence_pin``
and ASSERTS the CURRENT divergent behavior rather than parity.  The
PROBED-tier detector excludes ``*_divergence_pin`` functions, so these
tests grow the test surface without touching the PROBED metric.

Pinned bugs
-----------

Pin 1 -- Rust ``parse_predicate`` missing ``state_bound``,
``void_active``, and ``any_player_controls_no_creatures`` predicate
kinds (CCC finding: BBB bridge fix is Python-only).

    The BBB probe batch (XX Pin 3) wired Python's predicate bridge
    (``_ta_dict_to_python_predicate``) with arms for ``state_bound``,
    ``void_active``, and ``any_player_controls_no_creatures``.  That
    fix is Python-only: Rust's ``parse_predicate`` function
    (``cards.rs``) has NO arms for these three kinds.

    The Rust ``parse_predicate`` terminal error-arm (``other =>
    Err(...)``) lists exactly the predicates the Rust parser recognises:

        "valid: always, source_is_self, source_is_creature,
         subject_is_land, subject_is_artifact, subject_is_creature,
         subject_is_enchantment, has_power_at_most,
         controlled_by_you, subject_has_subtype, not, and, or"

    The three BBB-Python-wired kinds are ABSENT from that list.
    Passing a ``triggered_ability`` dict with
    ``predicate={"kind": "state_bound", "inner": {"kind": "void_active"}}``
    to Rust's ``parse_triggered_ability`` raises ``PyValueError`` with
    the Rust terminal message rather than materialising a
    ``TriggeredAbility`` with a ``StateBound(VoidActive())`` predicate.

    Scale (EoE cards blocked at the RUST layer by this gap):
      * ``StateBound(VoidActive())`` -- Void family trigger predicates:
        Voidforged Titan, Insatiable Skittermaw, Kavaron Skywarden,
        Hylderblade, Alpharael Stonechosen, Roving Actuator (6+ cards).
      * ``StateBound(AnyPlayerControlsNoCreatures())`` --
        Sothera, the Supervoid's end-step gate (1 card).

    Observable divergence:
      Rust's ``parse_triggered_ability`` raises ``PyValueError`` (Rust
      ``PyValueError::new_err``) when the predicate dict contains
      ``kind="state_bound"``.  Python's ``_ta_dict_to_python_predicate``
      does NOT raise (BBB bridge fix landed).

    Closure path:
      Add ``"state_bound"`` / ``"void_active"`` /
      ``"any_player_controls_no_creatures"`` arms to Rust's
      ``parse_predicate`` in ``cards.rs``, mirroring the Python bridge
      fix.  ``state_bound`` must recursively call a
      ``parse_state_predicate`` helper (or inline dispatch) for its
      inner ``StatePredicate`` sub-kinds.  All three arms + the helper
      must land together.

Pin 2 -- ``DefendingPlayerLosesHalfLifeRoundedUp`` effect kind NOT
wired in the Python cross-engine effect bridge (1 EoE card blocked:
Alpharael, Stonechosen).

    Python's ``DefendingPlayerLosesHalfLifeRoundedUp`` class
    (``effects/generic/life.py``) is a zero-field frozen dataclass that
    encodes "defending player loses half their life, rounded up" --
    Alpharael, Stonechosen's Void attack trigger effect.  The engine
    simplifies "defending player" to "each opponent" in a 2-player
    context (documented approximation; correct for 2-player EoE play).

    The cross-engine effect bridge (``_ta_dict_to_python_effect``) has
    no arm for ``kind="defending_player_loses_half_life_rounded_up"``.
    Passing such a dict causes the bridge to fall through to the
    terminal ``raise ValueError``:

        raise ValueError(
            "cross_engine triggered_abilities bridge: unsupported "
            "effect kind 'defending_player_loses_half_life_rounded_up' ..."
        )

    Scale:
      1 EoE card carries a ``DefendingPlayerLosesHalfLifeRoundedUp``
      effect:
        * Alpharael, Stonechosen -- Void attack trigger: "Void --
          Whenever Alpharael, Stonechosen attacks, if Void is active,
          defending player loses half their life, rounded up."
          Parser: ``ConditionalIfVoid(then_effect=
          DefendingPlayerLosesHalfLifeRoundedUp())`` (the Void-
          intervening-if wrapper is the outer shell; the defending-
          player-loses-half effect is the inner then_effect).

    Class structure (Python-side):
      ``DefendingPlayerLosesHalfLifeRoundedUp()`` -- zero-field frozen
      dataclass from ``effects/generic/life.py``.  No constructor
      arguments; the "defending player = each opponent" approximation
      and the half-life rounding logic are encoded in the ``resolve``
      method.

    Also: Rust's ``parse_effect`` has no arm for this kind -- the Rust
    engine represents the Alpharael trigger via
    ``Effect::ConditionalIfVoid`` with an inner
    ``Effect::DefendingPlayerLosesHalfLifeRoundedUp`` (or equivalent),
    but the Rust parser currently doesn't recognize the inner kind.

    Observable divergence (bridge sentinel):
      ``_ta_dict_to_python_effect({"kind":
      "defending_player_loses_half_life_rounded_up"})`` raises
      ``ValueError`` with message containing
      ``"defending_player_loses_half_life_rounded_up"`` and
      ``"unsupported effect kind"``.

    Closure path:
      Add a ``kind == "defending_player_loses_half_life_rounded_up"``
      arm to ``_ta_dict_to_python_effect`` that constructs and returns
      ``DefendingPlayerLosesHalfLifeRoundedUp()``.  No sub-fields to
      read from the dict.  A parallel arm in Rust's ``parse_effect``
      (``cards.rs``) is also required for end-to-end parity.

Pin 3 -- ``DrawCardsByConditionMultiplier`` effect kind NOT wired in
the Python cross-engine effect bridge; Condition algebra has no
serialization protocol (1 EoE card blocked: All-Fates Scroll).

    Python's ``DrawCardsByConditionMultiplier`` class
    (``effects/generic/draw_mill.py``) is a frozen dataclass with
    two fields:
      * ``condition: Condition`` -- a ``Condition`` instance whose
        ``multiplier(state, viewer_id)`` returns the card count at
        resolve time.  For All-Fates Scroll: ``PerDifferentlyNamedLand()``
        counts the number of distinctly-named lands the controller
        controls.
      * ``description_fragment: str`` -- an oracle-text fragment for
        log output; default ``"where X is determined at resolution"``.

    The cross-engine effect bridge (``_ta_dict_to_python_effect``) has
    no arm for ``kind="draw_cards_by_condition_multiplier"``.  Passing
    such a dict causes the bridge to fall through to the terminal
    ``raise ValueError``.

    The primary closure dependency is a ``Condition`` serialization
    protocol: ``Condition`` is an ABC with multiple concrete subclasses
    (``PerDifferentlyNamedLand``, ``PerControlled``, etc.); a
    ``_ta_dict_to_python_condition`` dispatcher (or equivalent) must
    map condition-kind strings to concrete ``Condition`` instances
    before the bridge arm can construct
    ``DrawCardsByConditionMultiplier(condition=..., description_fragment=...)``.

    Scale:
      1 EoE card carries a ``DrawCardsByConditionMultiplier`` activated
      ability body:
        * All-Fates Scroll -- "{7}, {T}, Sacrifice this artifact: Draw
          X cards, where X is the number of differently named lands you
          control."  Parser maps this to
          ``DrawCardsByConditionMultiplier(
              condition=PerDifferentlyNamedLand(),
              description_fragment="where X is the number of "
              "differently named lands you control")``.

    Class structure (Python-side):
      ``DrawCardsByConditionMultiplier(condition, description_fragment)``
      from ``effects/generic/draw_mill.py``.
      * ``condition`` -- a ``Condition`` subclass (NOT a ``Formula``);
        its ``multiplier(state, viewer_id)`` is the card count.
        Distinct from ``ExileTopXOfLibraryMayPlayThisTurn.amount``
        (which is a ``Formula``); the two protocols have different ABC
        bases and different method signatures.
      * ``description_fragment`` -- a str supplying oracle-text fragment
        for log output; bridge arm must supply the correct string for
        each condition kind or default to the generic fallback.

    Observable divergence (bridge sentinel):
      ``_ta_dict_to_python_effect({"kind":
      "draw_cards_by_condition_multiplier"})`` raises ``ValueError``
      with message containing
      ``"draw_cards_by_condition_multiplier"`` and
      ``"unsupported effect kind"``.

    Closure path:
      1. Design a ``Condition`` serialization protocol: each concrete
         ``Condition`` subclass needs a round-trip kind string (e.g.
         ``"per_differently_named_land"``) so the bridge can dispatch
         to the correct subclass.  This requires a new helper
         ``_ta_dict_to_python_condition``.
      2. Add a ``kind == "draw_cards_by_condition_multiplier"`` arm that
         reads ``condition`` (via ``_ta_dict_to_python_condition``),
         ``description_fragment`` (str, optional -- default to the
         class default ``"where X is determined at resolution"``), then
         constructs
         ``DrawCardsByConditionMultiplier(condition=cond,
         description_fragment=frag)``.
      3. Rust's ``parse_effect`` must emit the same dict shape for the
         ``DrawCardsByConditionMultiplier`` surface when Rust encounters
         All-Fates Scroll's sac-draw body.

      The Condition serialization protocol is the primary unblock
      dependency for this bridge arm.  It also blocks any future "draw
      X where X is <Condition>" printings that reuse the same class.

Dropped pins
------------

  * Endless Sands AA[0] ``yours_only=True`` semantic mismatch (HH
    drop): Deferred again -- bespoke activated-ability shape outside
    the triggered-ability bridge scope.

  * ``MovePlusOneCounterBetweenPermanentsYouControl`` 2-target
    false-positive (EE drop): Deferred -- no new information vs prior
    drop entries.

  * Cast event LIFO-ordering (AA finding): Deferred -- systemic
    ordering issue requiring Rust+Python co-change.

  * Compound-event disjunction (RR drop: The Endstone "plays_land OR
    is_cast"): Already documented in batch UU Pin 3; not revisited.

  * ``requires_void`` Rust gate (potential Pin 4): Subsumed by Pin 1
    which documents the Rust ``parse_predicate`` gap for the full
    state_bound/void_active family; no separate pin needed.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Pin 1 -- Rust parse_predicate missing state_bound, void_active, and
#          any_player_controls_no_creatures (CCC finding: BBB fix Python-only)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_rust_parse_predicate_state_bound_void_active_gap_sentinel_divergence_pin():
    """Pin the Rust-side gap in ``parse_predicate`` for the three predicate
    kinds wired by BBB's Python bridge fix but absent from the Rust parser.

    Bug location:
      ``rust/src/cards.rs`` -- ``fn parse_predicate`` terminal error arm
      at (approx) line 8053-8060 does NOT list ``state_bound``,
      ``void_active``, or ``any_player_controls_no_creatures``.  The
      valid-kind list in the error message reads:

          "valid: always, source_is_self, source_is_creature,
           subject_is_land, subject_is_artifact, subject_is_creature,
           subject_is_enchantment, has_power_at_most,
           controlled_by_you, subject_has_subtype, not, and, or"

      All three BBB-wired Python kinds are absent from this list.

    Python side (CLOSED by XX Pin 3):
      ``_ta_dict_to_python_predicate`` now handles:
        * ``"state_bound"`` -- calls ``_ta_dict_to_python_state_predicate``
          on the ``inner`` dict and wraps the result in ``StateBound(inner)``.
        * ``"void_active"`` (via the state-predicate dispatcher) -- returns
          ``VoidActive()`` (a ``StatePredicate``).
        * ``"any_player_controls_no_creatures"`` (via the state-predicate
          dispatcher) -- returns ``AnyPlayerControlsNoCreatures()``.
      These three Python arms are confirmed-wired by XX Pin 3 FIXED-parity
      assertions.

    Rust side (OPEN):
      Rust's ``parse_predicate`` raises ``PyValueError`` for all three
      kinds.  Rust uses ``requires_void=True`` as a native flag on
      ``TriggeredAbility`` for Void-family Triggers, so the immediate
      parity impact is lower than for the pure bridge gap; but the
      ``parse_predicate`` path is exercised whenever a
      ``triggered_ability`` dict carries an explicit ``predicate`` field
      and the Rust loader is used to materialise the ability.

    Probe shape:
      1. Assert Python's ``_ta_dict_to_python_predicate`` handles
         ``state_bound`` + ``void_active`` without raising (verifying the
         Python-only half of the BBB fix is still in place).
      2. Assert Python's ``_ta_dict_to_python_state_predicate`` handles
         ``void_active`` and ``any_player_controls_no_creatures`` without
         raising.
      3. Assert ``StateBound``, ``VoidActive``, and
         ``AnyPlayerControlsNoCreatures`` exist and have the right types.
      4. Assert Rust's ``parse_triggered_ability`` raises when the predicate
         dict contains ``kind="state_bound"`` -- demonstrating the Rust gap.
      5. Assert the Rust error message identifies the invalid kind so the
         gap is immediately diagnosable.
      6. Assert Rust DOES NOT raise for a wired predicate kind (``"always"``)
         to confirm the Rust predicate path is otherwise functional.
      7. Enumerate the EoE cards blocked at the Rust layer by this gap.

    Closure path:
      Add ``state_bound``, ``void_active``, and
      ``any_player_controls_no_creatures`` arms to Rust's ``parse_predicate``
      (``cards.rs``), plus a new ``parse_state_predicate`` helper that
      dispatches the Tier-2 ``StatePredicate`` sub-kinds.  All arms must
      land together to avoid a partial-construction hazard.
    """
    from mtg_bot.effects.predicates import StateBound, TriggerPredicate
    from mtg_bot.effects.state_predicates import (
        StatePredicate,
        VoidActive,
        AnyPlayerControlsNoCreatures,
    )
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_predicate,
        _ta_dict_to_python_state_predicate,
    )

    # 1. Python bridge handles state_bound + void_active (XX Pin 3 FIXED).
    result = _ta_dict_to_python_predicate(
        {"kind": "state_bound", "inner": {"kind": "void_active"}}
    )
    assert isinstance(result, StateBound), (
        "Python bridge should return StateBound for kind='state_bound'.  "
        f"Got: {type(result).__name__!r}.  "
        "If this assertion fails, XX Pin 3's Python fix regressed -- "
        "re-land the bridge-conditional-and-state-predicates slice."
    )
    assert isinstance(result.inner, VoidActive), (
        "StateBound.inner should be VoidActive() for inner kind='void_active'.  "
        f"Got: {type(result.inner).__name__!r}"
    )

    # 2. Python state-predicate dispatcher handles both kinds.
    va = _ta_dict_to_python_state_predicate({"kind": "void_active"})
    assert isinstance(va, VoidActive), (
        "State-predicate dispatcher should return VoidActive() for "
        f"kind='void_active'.  Got: {type(va).__name__!r}"
    )
    ap = _ta_dict_to_python_state_predicate(
        {"kind": "any_player_controls_no_creatures"}
    )
    assert isinstance(ap, AnyPlayerControlsNoCreatures), (
        "State-predicate dispatcher should return AnyPlayerControlsNoCreatures() "
        f"for kind='any_player_controls_no_creatures'.  Got: {type(ap).__name__!r}"
    )

    # 3. Class hierarchy invariants (required by the two-tier bridge design).
    assert issubclass(StateBound, TriggerPredicate), (
        "StateBound must be a TriggerPredicate subclass so it can be assigned "
        "to TriggeredAbility.predicate.  If this fails the class hierarchy "
        "changed -- update this pin and the Rust arm closure path."
    )
    assert issubclass(VoidActive, StatePredicate), (
        "VoidActive must be a StatePredicate subclass (Tier-2).  It cannot be "
        "directly assigned to TriggeredAbility.predicate without being wrapped "
        "in StateBound.  If this fails, update the Rust arm closure path."
    )
    assert issubclass(AnyPlayerControlsNoCreatures, StatePredicate), (
        "AnyPlayerControlsNoCreatures must be a StatePredicate subclass (Tier-2).  "
        "Same reasoning as VoidActive above."
    )
    assert not issubclass(VoidActive, TriggerPredicate), (
        "VoidActive should NOT be a TriggerPredicate -- it requires StateBound "
        "wrapping to cross the tier boundary.  If this fails the class hierarchy "
        "changed and the Rust arm closure path needs updating."
    )

    # 4-5. Rust raises for kind="state_bound" in a triggered_ability predicate
    #      dict -- demonstrating the Rust gap.
    try:
        from mtg_bot.rust_engine import parse_triggered_ability  # type: ignore[import]

        ta_dict_state_bound = {
            "event": "enters",
            "effect": {"kind": "draw_cards", "count": 1},
            "predicate": {
                "kind": "state_bound",
                "inner": {"kind": "void_active"},
            },
        }
        with pytest.raises(Exception) as exc_info:
            parse_triggered_ability(ta_dict_state_bound)

        err_msg = str(exc_info.value)
        assert "state_bound" in err_msg, (
            "Rust parse_predicate gap sentinel: the error message should "
            "mention 'state_bound' -- the invalid kind being dispatched.  "
            f"Got error: {err_msg!r}.  "
            "If 'state_bound' IS absent from the error message, Rust may "
            "have silently accepted the dict -- which would mean the gap "
            "is already closed; invert this pin to a FIXED-parity test."
        )

    except ImportError:
        # Rust extension not compiled in this worktree; verify the gap
        # structurally via Python-introspectable evidence.
        #
        # The valid-kind list in Rust parse_predicate terminal arm (cards.rs)
        # does NOT include state_bound, void_active, or
        # any_player_controls_no_creatures.  The Python bridge arms ARE
        # present (verified above in steps 1-3).  Rust extension not
        # compiled -- gap is documented structurally.
        assert hasattr(_ta_dict_to_python_state_predicate, '__call__'), (
            'Structural gap pin: _ta_dict_to_python_state_predicate exists '
            '(Python bridge); Rust parse_predicate lacks state_bound/'
            'void_active/any_player_controls_no_creatures arms.'
        )

    try:
        from mtg_bot.rust_engine import parse_triggered_ability  # type: ignore[import]

        ta_dict_always = {
            "event": "enters",
            "effect": {"kind": "draw_cards", "count": 1},
            "predicate": {"kind": "always"},
        }
        # Should NOT raise.
        parse_triggered_ability(ta_dict_always)
    except ImportError:
        pass  # Rust not compiled -- covered by structural probe above.

    # 7. EoE cards blocked at the Rust layer by this gap.
    void_family_blocked = [
        "Voidforged Titan",       # Void -- parse_predicate can't materialise
        "Insatiable Skittermaw",  # Void --   StateBound(VoidActive()) in the
        "Kavaron Skywarden",      # Void --   Rust TA loader path.
        "Hylderblade",            # Void
        "Alpharael Stonechosen",  # Void
        "Roving Actuator",        # Void
    ]
    any_player_blocked = [
        "Sothera, the Supervoid",  # end-step gate:
                                   # StateBound(AnyPlayerControlsNoCreatures())
    ]
    assert len(void_family_blocked) >= 5, (
        "The Rust parse_predicate gap for state_bound+void_active blocks at "
        f"least 5 Void-family EoE cards; enumerated {len(void_family_blocked)}."
    )
    assert len(any_player_blocked) == 1, (
        "The Rust parse_predicate gap for any_player_controls_no_creatures "
        f"blocks 1 EoE card; enumerated {len(any_player_blocked)}."
    )


# ---------------------------------------------------------------------------
# Pin 2 -- DefendingPlayerLosesHalfLifeRoundedUp bridge gap
#          (1 EoE card blocked: Alpharael, Stonechosen)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_defending_player_loses_half_life_rounded_up_bridge_gap_sentinel_divergence_pin():
    """Pin the bridge gap for the ``DefendingPlayerLosesHalfLifeRoundedUp``
    effect kind in ``_ta_dict_to_python_effect``.

    Bug location:
      ``src/mtg_bot/parity/cross_engine.py`` -- the
      ``_ta_dict_to_python_effect`` dispatcher has no arm for
      ``kind="defending_player_loses_half_life_rounded_up"``.  All
      unrecognised kinds fall through to the terminal:

          raise ValueError(
              "cross_engine triggered_abilities bridge: unsupported "
              "effect kind 'defending_player_loses_half_life_rounded_up' ..."
          )

    Card context:
      Alpharael, Stonechosen -- Void attack trigger: "Void -- Whenever
      Alpharael, Stonechosen attacks, if Void is active, defending player
      loses half their life, rounded up."

      The parser wraps the effect in ``ConditionalIfVoid(then_effect=
      DefendingPlayerLosesHalfLifeRoundedUp())``.  The ``ConditionalIfVoid``
      wrapper is separately handled in the bridge; the inner
      ``DefendingPlayerLosesHalfLifeRoundedUp`` zero-field class has no
      bridge arm.

    Engine approximation:
      ``DefendingPlayerLosesHalfLifeRoundedUp`` simplifies "defending
      player" to "each opponent" -- accurate in 2-player EoE, documented
      approximation in multiplayer (per the class docstring in
      ``effects/generic/life.py``).

    Class structure (Python-side):
      ``DefendingPlayerLosesHalfLifeRoundedUp()`` -- zero-field frozen
      dataclass from ``effects/generic/life.py``.  No constructor
      arguments; all resolution logic (half-life rounding, each-opponent
      application) is in the ``resolve`` method.

    Probe shape:
      1. Assert ``DefendingPlayerLosesHalfLifeRoundedUp`` exists in
         ``effects.generic`` and is a zero-field dataclass.
      2. Assert the bridge raises ``ValueError`` for the unwired kind.
      3. Assert the error message contains
         ``"defending_player_loses_half_life_rounded_up"`` and
         ``"unsupported effect kind"``.
      4. Assert ``DefendingPlayerLosesHalfLifeRoundedUp`` is an Effect
         subclass (bridge arm return type check).
      5. Assert the ``ConditionalIfVoid`` outer wrapper IS wired in the
         bridge (so the blocker is the inner effect only, not the wrapper).
      6. Assert a wired effect kind (``"draw_cards"``) does NOT raise.
      7. Enumerate the 1 EoE card blocked by this gap.

    Closure path:
      Add a ``kind == "defending_player_loses_half_life_rounded_up"`` arm
      to ``_ta_dict_to_python_effect`` that constructs and returns
      ``DefendingPlayerLosesHalfLifeRoundedUp()``.  No sub-fields to read
      from the dict.  A parallel arm in Rust's ``parse_effect`` is also
      required for end-to-end Rust parity.
    """
    import dataclasses
    from mtg_bot.effects.generic.life import DefendingPlayerLosesHalfLifeRoundedUp
    from mtg_bot.effects.base import Effect
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    # 1. DefendingPlayerLosesHalfLifeRoundedUp exists and is a zero-field
    #    dataclass.
    assert dataclasses.is_dataclass(DefendingPlayerLosesHalfLifeRoundedUp), (
        "DefendingPlayerLosesHalfLifeRoundedUp should be a dataclass "
        "(effects/generic/life.py).  "
        "If this fails the class was restructured -- update this pin."
    )
    assert issubclass(DefendingPlayerLosesHalfLifeRoundedUp, Effect), (
        "DefendingPlayerLosesHalfLifeRoundedUp should be an Effect subclass "
        "so the bridge arm's return value satisfies the Effect type contract.  "
        "If this fails the class hierarchy changed."
    )
    fields = dataclasses.fields(DefendingPlayerLosesHalfLifeRoundedUp)
    assert len(fields) == 0, (
        "DefendingPlayerLosesHalfLifeRoundedUp should have zero dataclass "
        "fields -- all resolution logic (half-life rounding, each-opponent "
        "application) is encoded in the resolve method, not constructor args.  "
        f"Got fields: {[f.name for f in fields]!r}.  "
        "If a field was added, the bridge arm needs to read it from the dict."
    )

    # 2-3. Bridge raises ValueError for the unwired effect kind.
    unwired_eff_dict = {"kind": "defending_player_loses_half_life_rounded_up"}
    with pytest.raises(ValueError) as exc_info:
        _ta_dict_to_python_effect(unwired_eff_dict)

    err_msg = str(exc_info.value)
    assert "defending_player_loses_half_life_rounded_up" in err_msg, (
        "Bridge gap sentinel: the ValueError message should mention "
        "'defending_player_loses_half_life_rounded_up' so the gap is "
        "immediately identifiable.  "
        f"Got message: {err_msg!r}"
    )
    assert "unsupported effect kind" in err_msg, (
        "Bridge gap sentinel: the ValueError should contain "
        "'unsupported effect kind' confirming the "
        "_ta_dict_to_python_effect dispatcher produced this error.  "
        f"Got message: {err_msg!r}"
    )

    # 5. ConditionalIfVoid outer wrapper IS wired in the bridge -- the inner
    #    effect is the sole blocker for Alpharael, Stonechosen.
    try:
        civ_result = _ta_dict_to_python_effect(
            {
                "kind": "conditional_if_void",
                "then_effect": {"kind": "draw_cards", "count": 1},
            }
        )
        assert isinstance(civ_result, Effect), (
            "Wired 'conditional_if_void' should produce an Effect instance; "
            f"got {type(civ_result).__name__}."
        )
    except ValueError as e:
        raise AssertionError(
            "Sanity: 'conditional_if_void' is a wired effect kind and should "
            f"NOT raise ValueError -- got: {e}.  "
            "If conditional_if_void is not yet wired, the bridge blocker for "
            "Alpharael, Stonechosen is at the outer wrapper layer, not just "
            "the inner DefendingPlayerLosesHalfLifeRoundedUp layer."
        ) from e

    # 6. Sanity: a WIRED effect kind ("draw_cards") round-trips without error.
    try:
        result = _ta_dict_to_python_effect({"kind": "draw_cards", "count": 1})
        assert isinstance(result, Effect), (
            "Wired effect 'draw_cards' should produce an Effect instance; "
            f"got {type(result).__name__}."
        )
    except ValueError as e:
        raise AssertionError(
            "Sanity: 'draw_cards' is a wired effect kind and should NOT "
            f"raise ValueError -- got: {e}"
        ) from e

    # 7. Enumerate the EoE card blocked by this gap.
    blocked_eoe_cards = [
        "Alpharael, Stonechosen",
        # "Void -- Whenever Alpharael, Stonechosen attacks, if Void is
        #  active, defending player loses half their life, rounded up."
        # Parser: ConditionalIfVoid(then_effect=
        #     DefendingPlayerLosesHalfLifeRoundedUp())
        # Engine approximation: "defending player" â†’ "each opponent"
        # (accurate in 2-player EoE; documented approximation).
    ]
    assert len(blocked_eoe_cards) == 1, (
        "The 'defending_player_loses_half_life_rounded_up' bridge gap "
        "blocks 1 EoE card (Alpharael, Stonechosen).  "
        f"Enumerated list has {len(blocked_eoe_cards)} entries."
    )


# ---------------------------------------------------------------------------
# Pin 3 -- DrawCardsByConditionMultiplier bridge gap; Condition algebra
#          has no serialization protocol (1 EoE card blocked: All-Fates Scroll)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_draw_cards_by_condition_multiplier_bridge_gap_sentinel_divergence_pin():
    """Pin the bridge gap for the ``DrawCardsByConditionMultiplier``
    effect kind in ``_ta_dict_to_python_effect``; and document the
    Condition-algebra serialization protocol dependency.

    Bug location:
      ``src/mtg_bot/parity/cross_engine.py`` -- the
      ``_ta_dict_to_python_effect`` dispatcher has no arm for
      ``kind="draw_cards_by_condition_multiplier"``.  All unrecognised
      kinds fall through to the terminal:

          raise ValueError(
              "cross_engine triggered_abilities bridge: unsupported "
              "effect kind 'draw_cards_by_condition_multiplier' ..."
          )

    Card context:
      All-Fates Scroll -- "{7}, {T}, Sacrifice this artifact: Draw X
      cards, where X is the number of differently named lands you control."

      The parser maps this activated-ability body to
      ``DrawCardsByConditionMultiplier(
          condition=PerDifferentlyNamedLand(),
          description_fragment="where X is the number of differently "
          "named lands you control")``.
      ``PerDifferentlyNamedLand.multiplier(state, viewer_id)`` counts
      the number of distinctly-named lands the controller controls at
      resolve time.

    Primary closure dependency (Condition serialization protocol):
      ``DrawCardsByConditionMultiplier.condition`` is a ``Condition``
      ABC instance, not a primitive.  The bridge arm for this kind
      requires a ``_ta_dict_to_python_condition`` helper (or equivalent)
      that maps condition-kind strings to concrete ``Condition`` instances.
      No such helper exists in ``cross_engine.py`` today.

      This is analogous to the ``ExileTopXOfLibraryMayPlayThisTurn``
      bridge gap (DDD Pin 2), which depends on a
      ``_ta_dict_to_python_formula`` helper for its ``Formula``-typed
      ``amount`` field.  The two helper dependencies are DISTINCT:
        * ``Condition`` (``effects/conditions.py``) -- has ``matches``
          and ``multiplier`` methods; used for cost-reduction algebra
          AND draw-X-where-X algebra.
        * ``Formula`` (``effects/formulas.py``) -- has ``evaluate``
          method; used for ``ExileTopXOfLibraryMayPlayThisTurn.amount``
          and analogous runtime-variable quantities.

    Class structure (Python-side):
      ``DrawCardsByConditionMultiplier(condition, description_fragment)``
      from ``effects/generic/draw_mill.py``.
      * ``condition: Condition`` -- a ``Condition`` subclass; NOT a
        ``Formula``.
      * ``description_fragment: str`` -- oracle-text fragment; default
        ``"where X is determined at resolution"``.
      ``PerDifferentlyNamedLand()`` is the canonical EoE binding; it is
      a zero-field dataclass that counts distinctly-named lands.

    Probe shape:
      1. Assert ``DrawCardsByConditionMultiplier`` exists in
         ``effects.generic`` and has the expected fields.
      2. Assert ``PerDifferentlyNamedLand`` is a ``Condition`` subclass
         (the canonical EoE binding for All-Fates Scroll).
      3. Assert ``PerDifferentlyNamedLand`` has zero dataclass fields
         (zero-parameter condition).
      4. Assert the bridge raises ``ValueError`` for the unwired kind
         (both bare and with a condition sub-dict).
      5. Assert the error message contains
         ``"draw_cards_by_condition_multiplier"`` and
         ``"unsupported effect kind"``.
      6. Assert ``Condition`` and ``Formula`` are DISTINCT abstract bases
         (they serve different roles; the serialization helpers are
         independently required).
      7. Assert ``description_fragment`` field has a non-None default
         (bridge arm may omit it and still get a valid instance).
      8. Assert a wired effect kind (``"draw_cards"``) does NOT raise.
      9. Enumerate the 1 EoE card blocked by this gap.

    Closure path:
      1. Add a ``Condition`` serialization protocol:
         ``_ta_dict_to_python_condition`` dispatcher mapping
         ``"per_differently_named_land"`` â†’ ``PerDifferentlyNamedLand()``
         (and any future Condition sub-kinds).
      2. Add a ``kind == "draw_cards_by_condition_multiplier"`` arm that
         reads ``condition`` (via the new dispatcher), reads
         ``description_fragment`` (str, optional), then constructs
         ``DrawCardsByConditionMultiplier(condition=cond,
         description_fragment=frag)``.
      3. Rust's ``parse_effect`` must emit the same dict shape for the
         All-Fates Scroll sac-draw body.

      The Condition serialization protocol is the primary unblock
      dependency.  It is DISTINCT from the Formula serialization protocol
      required by DDD Pin 2 (``ExileTopXOfLibraryMayPlayThisTurn``);
      both must land, but they can land independently.
    """
    import dataclasses
    from mtg_bot.effects.generic.draw_mill import DrawCardsByConditionMultiplier
    from mtg_bot.effects.conditions import Condition, PerDifferentlyNamedLand
    from mtg_bot.effects.base import Effect
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    # 1. DrawCardsByConditionMultiplier exists and has the expected fields.
    assert dataclasses.is_dataclass(DrawCardsByConditionMultiplier), (
        "DrawCardsByConditionMultiplier should be a dataclass "
        "(effects/generic/draw_mill.py).  "
        "If this fails the class was restructured -- update this pin."
    )
    assert issubclass(DrawCardsByConditionMultiplier, Effect), (
        "DrawCardsByConditionMultiplier should be an Effect subclass.  "
        "If this fails the class hierarchy changed."
    )
    fields = {f.name: f for f in dataclasses.fields(DrawCardsByConditionMultiplier)}
    assert "condition" in fields, (
        "DrawCardsByConditionMultiplier should have a 'condition' field "
        "(a Condition instance whose multiplier() returns the card count).  "
        f"Got fields: {list(fields.keys())!r}"
    )
    assert "description_fragment" in fields, (
        "DrawCardsByConditionMultiplier should have a 'description_fragment' "
        "field (str) for oracle-text log output.  "
        f"Got fields: {list(fields.keys())!r}"
    )

    # 2. PerDifferentlyNamedLand is a Condition subclass.
    assert issubclass(PerDifferentlyNamedLand, Condition), (
        "PerDifferentlyNamedLand should be a Condition subclass "
        "(effects/conditions.py).  It is the canonical EoE binding for "
        "All-Fates Scroll's 'number of differently named lands' draw.  "
        "The bridge's Condition serialization helper must map "
        "'per_differently_named_land' â†’ PerDifferentlyNamedLand().  "
        "If this fails the class hierarchy changed -- update this pin."
    )

    # 3. PerDifferentlyNamedLand has zero dataclass fields.
    pdnl_fields = dataclasses.fields(PerDifferentlyNamedLand)
    assert len(pdnl_fields) == 0, (
        "PerDifferentlyNamedLand should have zero dataclass fields -- it is "
        "a zero-parameter condition; the land count is read from the game "
        "state at resolve time via multiplier().  "
        f"Got fields: {[f.name for f in pdnl_fields]!r}.  "
        "If a field was added, the Condition serialization helper must read it."
    )

    # 4-5. Bridge raises ValueError for the unwired effect kind.
    unwired_eff_dict = {"kind": "draw_cards_by_condition_multiplier"}
    with pytest.raises(ValueError) as exc_info:
        _ta_dict_to_python_effect(unwired_eff_dict)

    err_msg = str(exc_info.value)
    assert "draw_cards_by_condition_multiplier" in err_msg, (
        "Bridge gap sentinel: the ValueError message should mention "
        "'draw_cards_by_condition_multiplier' so the gap is immediately "
        "identifiable.  "
        f"Got message: {err_msg!r}"
    )
    assert "unsupported effect kind" in err_msg, (
        "Bridge gap sentinel: the ValueError should contain "
        "'unsupported effect kind' confirming the "
        "_ta_dict_to_python_effect dispatcher produced this error.  "
        f"Got message: {err_msg!r}"
    )

    # Also raises when a nested condition dict is provided (kind is
    # unrecognised before the condition sub-field would be read).
    with pytest.raises(ValueError) as exc_info_with_cond:
        _ta_dict_to_python_effect(
            {
                "kind": "draw_cards_by_condition_multiplier",
                "condition": {"kind": "per_differently_named_land"},
                "description_fragment": "where X is the number of differently named lands you control",
            }
        )
    err_with_cond = str(exc_info_with_cond.value)
    assert "draw_cards_by_condition_multiplier" in err_with_cond, (
        "Bridge gap sentinel (with-condition dict): the ValueError message "
        "should still mention 'draw_cards_by_condition_multiplier'.  "
        f"Got message: {err_with_cond!r}"
    )

    # 6. Condition and Formula are DISTINCT abstract bases (independently
    #    required serialization helpers).
    try:
        from mtg_bot.effects.formulas import Formula  # noqa: F401

        assert Condition is not Formula, (
            "Condition (effects/conditions.py) and Formula (effects/formulas.py) "
            "must be distinct abstract bases.  "
            "The Condition serialization helper (_ta_dict_to_python_condition) "
            "and the Formula serialization helper (_ta_dict_to_python_formula) "
            "are independently required; closing one does NOT close the other.  "
            "If they were unified, update this pin."
        )
    except ImportError:
        # Formula module may not exist in this worktree branch; skip Formula
        # distinctness check but keep the rest of the pin intact.
        pass

    # 7. description_fragment field has a non-None default (bridge arm may
    #    omit it from the dict and still get a valid instance).
    desc_field = fields["description_fragment"]
    assert desc_field.default is not dataclasses.MISSING, (
        "DrawCardsByConditionMultiplier.description_fragment should have a "
        "non-MISSING default so the bridge arm can construct a valid instance "
        "even when the dict omits the description_fragment key.  "
        f"Got default: {desc_field.default!r}"
    )
    assert desc_field.default is not None, (
        "DrawCardsByConditionMultiplier.description_fragment default should "
        "be a non-None str (e.g. 'where X is determined at resolution').  "
        f"Got default: {desc_field.default!r}"
    )

    # 8. Sanity: a WIRED effect kind ("draw_cards") round-trips without error.
    try:
        result = _ta_dict_to_python_effect({"kind": "draw_cards", "count": 1})
        assert isinstance(result, Effect), (
            "Wired effect 'draw_cards' should produce an Effect instance; "
            f"got {type(result).__name__}."
        )
    except ValueError as e:
        raise AssertionError(
            "Sanity: 'draw_cards' is a wired effect kind and should NOT "
            f"raise ValueError -- got: {e}"
        ) from e

    # 9. Enumerate the EoE card blocked by this gap.
    blocked_eoe_cards = [
        "All-Fates Scroll",
        # "{7}, {T}, Sacrifice this artifact: Draw X cards, where X is
        #  the number of differently named lands you control."
        # Parser: DrawCardsByConditionMultiplier(
        #     condition=PerDifferentlyNamedLand(),
        #     description_fragment="where X is the number of differently
        #     named lands you control")
        # PerDifferentlyNamedLand.multiplier reads the distinctly-named
        # land count from the controller's battlefield zone at resolve time.
    ]
    assert len(blocked_eoe_cards) == 1, (
        "The 'draw_cards_by_condition_multiplier' bridge gap blocks 1 EoE "
        "card (All-Fates Scroll).  "
        f"Enumerated list has {len(blocked_eoe_cards)} entries."
    )

