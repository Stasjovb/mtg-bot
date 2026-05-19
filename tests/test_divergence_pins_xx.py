"""Divergence-pin tests: batch XX (probe-batch-xx).

Pins 1, 2, and 3 are CLOSED by the bridge-conditional-and-state-predicates
slice.  Tests have been renamed from ``*_divergence_pin`` to ``*_FIXED_parity``
and the assertions inverted to verify the bridge now correctly constructs the
expected Python objects rather than raising ``ValueError``.

Closed pins
-----------

Pin 1 -- ``ConditionalIfYouGainedLifeAtLeast`` effect NOT wired in the
cross-engine effect bridge (VV phase-step substrate gap; 1 EoE card
blocked: Haliya, Guided by Light).

    Python's ``ConditionalIfYouGainedLifeAtLeast`` class
    (``effects/combinators.py:966-1002``) wraps an inner ``Effect`` and
    gates its resolution on whether the controller has gained at least
    ``threshold`` life this turn (reads
    ``Player.life_gained_this_turn``). It is produced by the parser
    (``cards/parser/triggers.py:1759``) for the trailing-if form "At
    the beginning of <when>, <inner_effect> if you've gained N or more
    life this turn."

    The cross-engine effect bridge (``_ta_dict_to_python_effect`` at
    ``cross_engine.py:525-8702``) has no arm for the effect-dict kind
    that would correspond to ``ConditionalIfYouGainedLifeAtLeast``.
    Passing a dict with ``kind="conditional_if_you_gained_life_at_least"``
    causes the bridge to fall through to the terminal ``raise ValueError``:

        raise ValueError(
            "cross_engine triggered_abilities bridge: unsupported "
            "effect kind 'conditional_if_you_gained_life_at_least' ..."
        )

    Scale:
      1 EoE card carries a ``ConditionalIfYouGainedLifeAtLeast`` trigger:
        * Haliya, Guided by Light -- "At the beginning of your end step,
          draw a card if you've gained 3 or more life this turn."
          The parser wraps ``DrawCards(1)`` in
          ``ConditionalIfYouGainedLifeAtLeast(threshold=3, inner=...)``.

    Relationship to VV phase-step gap:
      The VV probe batch expanded phase-step (BEGINNING_OF_END_STEP)
      bridge coverage, unblocking the trigger's event arm. But the
      ``ConditionalIfYouGainedLifeAtLeast`` effect wrapper that Haliya's
      parser output places around the inner ``DrawCards`` still has no
      bridge arm, so Haliya, Guided by Light remains blocked at the
      effect layer even after the VV event-arm fix lands.

    Class structure (Python-side):
      ``ConditionalIfYouGainedLifeAtLeast(threshold: int, inner: Effect)``
      * ``threshold`` -- the minimum life-gained count (e.g. 3 for
        Haliya, Guided by Light).
      * ``inner`` -- the ``Effect`` to resolve when the threshold is met
        (e.g. ``DrawCards(1)``).
      * ``resolve`` reads ``state.player_by_id(controller_id).life_gained_this_turn``
        and silently no-ops when the gained count is below ``threshold``.

    Closure path:
      Add a ``kind == "conditional_if_you_gained_life_at_least"`` arm to
      ``_ta_dict_to_python_effect`` that extracts ``threshold: int`` and
      recursively translates the ``inner`` effect dict, then constructs
      ``ConditionalIfYouGainedLifeAtLeast(threshold=threshold, inner=inner)``.
      Required fields: ``threshold`` (int, required), ``inner`` (effect
      dict, required).  No Rust substrate exists yet for this effect kind
      (the EoE Rust parser does not emit ``ConditionalIfYouGainedLifeAtLeast``
      dicts); the bridge arm is therefore a Python-only prerequisite for
      cross-engine parity testing of Haliya, Guided by Light.

    This pin is pure Python (no Rust extension required).

Pin 2 -- ``ConditionalIfSourcePowerAtLeast`` effect NOT wired in the
cross-engine effect bridge (VV phase-step / leaves-battlefield substrate
gap; EoE cards blocked: Syr Vondam, Sunstar Exemplar; Dawnstrike Vanguard;
Frontline War-Rager).

    Python's ``ConditionalIfSourcePowerAtLeast`` class
    (``effects/combinators.py:1055-1107``) wraps an inner ``Effect`` and
    gates its resolution on whether the triggering source's effective
    power is at least ``threshold`` at resolve time (reads
    ``state.resolving_source`` + ``effective_power(state, source)``).
    It is produced by the parser for the "while its power is N or greater"
    intervening-while gate (``_INTERVENING_WHILE_EFFECT_WRAPPERS`` at
    ``cards/parser/triggers.py:1423-1426``).

    The cross-engine effect bridge (``_ta_dict_to_python_effect``) has
    no arm for ``kind="conditional_if_source_power_at_least"``.  Passing
    such a dict causes the bridge to raise ``ValueError``:

        raise ValueError(
            "cross_engine triggered_abilities bridge: unsupported "
            "effect kind 'conditional_if_source_power_at_least' ..."
        )

    Scale:
      EoE cards that carry a ``ConditionalIfSourcePowerAtLeast`` gate:
        * Syr Vondam, Sunstar Exemplar -- "When this creature dies or is
          put into exile while its power is 4 or greater, destroy up to
          one target nonland permanent."  Parser wraps the destroy effect
          in ``ConditionalIfSourcePowerAtLeast(threshold=4, effect=...)``.
          (Note: the Python class uses ``effect`` as the field name;
          ``ConditionalIfSourcePowerAtLeast.effect``, not ``.inner``.)
        * Dawnstrike Vanguard / Frontline War-Rager -- "while its power
          is 4 or greater" intervening-while clause on attack or combat
          triggers; same ``_INTERVENING_WHILE_EFFECT_WRAPPERS`` entry.

    Class structure (Python-side):
      ``ConditionalIfSourcePowerAtLeast(effect: Effect, threshold: int = 4)``
      * ``effect`` -- the ``Effect`` to resolve when the threshold is met.
        (Field name is ``effect``, not ``inner``; distinct from
        ``ConditionalIfYouGainedLifeAtLeast.inner`` -- a naming gap that
        the bridge arm must handle.)
      * ``threshold`` -- the minimum effective-power count (default 4,
        matching every EoE card today).
      * ``resolve`` reads ``state.resolving_source`` and calls
        ``effective_power(state, source)``; silently no-ops when power
        is below threshold or source is None.

    Naming skew note (bridge arm requirement):
      Python's class stores the inner effect as ``self.effect``, not
      ``self.inner`` (unlike ``ConditionalIfYouGainedLifeAtLeast``).
      The bridge arm must construct
      ``ConditionalIfSourcePowerAtLeast(effect=inner_translated, threshold=N)``
      and must accept EITHER ``"inner"`` OR ``"effect"`` as the dict
      field name for the nested effect (Rust has not yet standardized a
      serialization key). This naming skew is a second closure step
      distinct from Pin 1's simpler ``inner``-keyed construction.

    Closure path:
      Add a ``kind == "conditional_if_source_power_at_least"`` arm that
      reads ``threshold`` (int, default 4) and recursively translates the
      nested effect (accepting both ``"inner"`` and ``"effect"`` keys),
      then constructs ``ConditionalIfSourcePowerAtLeast(effect=inner,
      threshold=threshold)``.  No Rust substrate emits this kind yet.

    This pin is pure Python (no Rust extension required).

Pin 3 -- ``StateBound`` predicate family NOT wired in the cross-engine
predicate bridge (VV phase-step substrate gap; ``VoidActive`` and
``AnyPlayerControlsNoCreatures`` StatePredicate kinds missing; EoE cards
blocked: Sothera, the Supervoid; Voidforged Titan; Insatiable Skittermaw;
Kavaron Skywarden; Hylderblade; Alpharael Stonechosen; + others).

    Python's ``StateBound(inner: StatePredicate)``
    (``effects/predicates.py:392-406``) wraps a ``StatePredicate`` and
    binds it to the triggering source's controller: it delegates to
    ``inner.test(state, source.controller_id)`` for every trigger
    dispatch.  ``StateBound`` is the standard combinator for the
    "intervening-if gate that reads from the source controller's
    perspective" family -- Void (``StateBound(VoidActive())``), Delirium
    (``StateBound(Delirium())``), opponent-controls-no-creatures
    (``StateBound(AnyPlayerControlsNoCreatures())``), etc.

    The cross-engine predicate bridge (``_ta_dict_to_python_predicate``
    at ``cross_engine.py:8705-8836``) has no arm for:
      * ``kind="state_bound"`` -- the ``StateBound`` wrapper kind.
      * ``kind="void_active"`` -- the ``VoidActive`` inner ``StatePredicate``.
      * ``kind="any_player_controls_no_creatures"`` -- the
        ``AnyPlayerControlsNoCreatures`` inner ``StatePredicate``.

    All three unsupported kinds fall through to the terminal raise:

        raise ValueError(
            "cross_engine triggered_abilities bridge: unsupported "
            "predicate kind <kind!r>"
        )

    Scale (EoE cards blocked by the StateBound predicate gap):
      * ``StateBound(VoidActive())`` -- Void -- gated triggers on
        Voidforged Titan, Insatiable Skittermaw, Kavaron Skywarden,
        Hylderblade, Alpharael Stonechosen, Roving Actuator (6+ cards).
        (Note: the Rust engine represents these via ``requires_void=True``
        on the ``TriggeredAbility``; the Python predicate-bridge gap is
        the Python-side reconstruction path, not the Rust-side gate.)
      * ``StateBound(AnyPlayerControlsNoCreatures())`` -- Sothera, the
        Supervoid's end-step intervening-if gate: "if a player controls
        no creatures" (1 card; the gate phrase maps to
        ``StateBound(AnyPlayerControlsNoCreatures())`` in
        ``_INTERVENING_IF_PHRASES`` at ``parser/triggers.py:1332-1333``).

    Closure path (three-step):
      Step A: Add ``kind == "void_active"`` arm that returns
        ``StateBound(VoidActive())``.  (Note: ``VoidActive`` is a
        ``StatePredicate``, not a ``TriggerPredicate``; the bridge arm
        must wrap it in ``StateBound`` because the predicate contract at
        the ``TriggeredAbility`` boundary requires a ``TriggerPredicate``.)
      Step B: Add ``kind == "state_bound"`` arm that recursively
        translates ``pred_dict["inner"]`` AS a ``StatePredicate`` kind
        (distinct from the ``TriggerPredicate`` kinds; requires a
        second dispatcher ``_ta_dict_to_python_state_predicate``), then
        wraps the result in ``StateBound(inner)``.
      Step C: Add ``kind == "any_player_controls_no_creatures"`` arm
        (into the ``StatePredicate`` dispatcher from Step B) that
        returns ``AnyPlayerControlsNoCreatures()``.

      Step B requires a NEW helper function ``_ta_dict_to_python_state_predicate``
      that dispatches ``StatePredicate`` sub-kinds (``void_active``,
      ``any_player_controls_no_creatures``, ``delirium``,
      ``spells_cast_this_turn``, ``lone_attacker_for_you``, etc.) --
      these are a SEPARATE kind-space from the ``TriggerPredicate`` kinds
      in ``_ta_dict_to_python_predicate``.  All three steps must land
      together to avoid a partial-construction hazard.

    This pin is pure Python (no Rust extension required for the bridge
    gap itself; Rust uses ``requires_void`` natively for the Void family).

Dropped pins
------------

  * Equip lane ``_zone_signature`` ``attached_to=None`` representation gap
    (EE drop): Dropped in batch RR; not revisited here.

  * Endless Sands AA[0] ``ExileTargetCreatureUntilSourceLeaves``
    ``yours_only=True`` semantic mismatch (HH drop): Documented in
    batch-HH worklog; not re-pinned here.

  * ``MovePlusOneCounterBetweenPermanentsYouControl`` 2-target diffs=[]
    false-positive (EE drop): Deferred; no new information vs EE drop.

  * Cast event LIFO-ordering divergence (AA finding): Rust dispatches
    IS_CAST BEFORE push; Python after. Dropped here in favor of the
    effect/predicate substrate gaps which block more EoE cards.

  * Compound-event disjunction need (RR drop: The Endstone "plays_land
    OR is_cast"): Already documented in batch UU Pin 3. Not revisited.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Pin 1 -- CLOSED: ConditionalIfYouGainedLifeAtLeast effect bridge arm added
#          bridge-conditional-and-state-predicates slice; 1 EoE card
#          unblocked: Haliya, Guided by Light
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_conditional_if_you_gained_life_at_least_effect_bridge_gap_sentinel_FIXED_parity():
    """Pin 1 CLOSED -- bridge arm for ``ConditionalIfYouGainedLifeAtLeast``
    now wired in ``_ta_dict_to_python_effect``.

    The bridge slice ``bridge-conditional-and-state-predicates`` added
    the ``kind == "conditional_if_you_gained_life_at_least"`` arm that
    extracts ``threshold: int`` and recursively translates the ``inner``
    effect dict, constructing
    ``ConditionalIfYouGainedLifeAtLeast(threshold=N, inner=inner_effect)``.

    Inverted assertions verify correct round-trip rather than ValueError.

    EoE card unlocked: Haliya, Guided by Light.
    """
    import dataclasses
    from mtg_bot.effects.combinators import (
        ConditionalIfYouGainedLifeAtLeast,
        ConditionalIfSourcePowerAtLeast,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    # 1. ConditionalIfYouGainedLifeAtLeast exists and has the expected fields.
    assert hasattr(ConditionalIfYouGainedLifeAtLeast, "__dataclass_fields__") or (
        hasattr(ConditionalIfYouGainedLifeAtLeast, "__annotations__")
    ), (
        "ConditionalIfYouGainedLifeAtLeast should be a dataclass or typed class "
        "(effects/combinators.py:966-1002).  If this fails the class was renamed "
        "-- update this pin and the bridge arm."
    )
    fields = {f.name for f in dataclasses.fields(ConditionalIfYouGainedLifeAtLeast)}
    assert "threshold" in fields, (
        "ConditionalIfYouGainedLifeAtLeast should have a 'threshold' field (int). "
        f"Got fields: {fields!r}"
    )
    assert "inner" in fields, (
        "ConditionalIfYouGainedLifeAtLeast should have an 'inner' field (Effect). "
        "This is the wrapped Effect that resolves when the threshold is met. "
        f"Got fields: {fields!r}"
    )

    # 2-3. Bridge NOW returns a ConditionalIfYouGainedLifeAtLeast -- no longer raises.
    eff_dict = {
        "kind": "conditional_if_you_gained_life_at_least",
        "threshold": 3,
        "inner": {"kind": "draw_cards", "count": 1},
    }
    result = _ta_dict_to_python_effect(eff_dict)
    assert isinstance(result, ConditionalIfYouGainedLifeAtLeast), (
        "Bridge should now return a ConditionalIfYouGainedLifeAtLeast instance "
        "for kind='conditional_if_you_gained_life_at_least'. "
        f"Got: {type(result).__name__!r}"
    )
    assert result.threshold == 3, (
        "Bridge should extract threshold=3 from the dict. "
        f"Got threshold={result.threshold!r}"
    )
    from mtg_bot.effects.generic.draw_mill import DrawCards
    assert isinstance(result.inner, DrawCards), (
        "Bridge should recursively translate the inner 'draw_cards' dict to a "
        f"DrawCards instance. Got: {type(result.inner).__name__!r}"
    )

    # 4. Sanity: a WIRED effect kind ("draw_cards") round-trips without error.
    from mtg_bot.effects.base import Effect
    wired_eff_dict = {"kind": "draw_cards", "count": 1}
    try:
        r2 = _ta_dict_to_python_effect(wired_eff_dict)
        assert isinstance(r2, Effect), (
            "Wired effect 'draw_cards' should produce an Effect instance; "
            f"got {type(r2).__name__}."
        )
    except ValueError as e:
        raise AssertionError(
            "Sanity: 'draw_cards' is a wired effect kind and should NOT raise "
            f"ValueError -- got: {e}"
        ) from e

    # 5. ConditionalIfYouGainedLifeAtLeast is DISTINCT from
    #    ConditionalIfSourcePowerAtLeast (Pin 2).  They model different gates:
    #    this one reads player life-gained-this-turn (controller-bound state);
    #    Pin 2 reads source effective power (source-object bound).
    #    They also have different field name conventions for the inner effect:
    #    this class uses ``inner``; Pin 2 uses ``effect``.  Wiring one does
    #    NOT wire the other; both bridge arms must land separately.
    assert ConditionalIfYouGainedLifeAtLeast is not ConditionalIfSourcePowerAtLeast, (
        "ConditionalIfYouGainedLifeAtLeast must be a distinct class from "
        "ConditionalIfSourcePowerAtLeast.  They gate on different quantities "
        "(life-gained-this-turn vs source-power) and have different inner-effect "
        "field names ('inner' vs 'effect').  Closing one bridge gap does NOT "
        "close the other."
    )
    pin2_fields = {f.name for f in dataclasses.fields(ConditionalIfSourcePowerAtLeast)}
    assert "effect" in pin2_fields, (
        "ConditionalIfSourcePowerAtLeast should use 'effect' as its inner-effect "
        "field (not 'inner'), distinguishing it from this class's 'inner' field. "
        f"Pin 2 fields: {pin2_fields!r}"
    )
    assert "inner" not in pin2_fields, (
        "ConditionalIfSourcePowerAtLeast should NOT have an 'inner' field "
        "(it uses 'effect' per effects/combinators.py:1055-1107). "
        f"Pin 2 fields: {pin2_fields!r}"
    )

    # 6. Enumerate the 1 EoE card now unblocked by this fix.
    unblocked_eoe_cards = [
        "Haliya, Guided by Light",  # "At the beginning of your end step,
                                    #  draw a card if you've gained 3 or more
                                    #  life this turn."
                                    # Parser: DrawCards(1) wrapped in
                                    # ConditionalIfYouGainedLifeAtLeast(threshold=3)
    ]
    assert len(unblocked_eoe_cards) == 1, (
        "The 'conditional_if_you_gained_life_at_least' bridge fix unblocks "
        "1 EoE card (Haliya, Guided by Light); "
        f"enumerated list has {len(unblocked_eoe_cards)} entries."
    )


# ---------------------------------------------------------------------------
# Pin 2 -- CLOSED: ConditionalIfSourcePowerAtLeast effect bridge arm added
#          bridge-conditional-and-state-predicates slice; 3+ EoE cards
#          unblocked: Syr Vondam, Sunstar Exemplar; Dawnstrike Vanguard;
#          Frontline War-Rager
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_conditional_if_source_power_at_least_effect_bridge_gap_sentinel_FIXED_parity():
    """Pin 2 CLOSED -- bridge arm for ``ConditionalIfSourcePowerAtLeast``
    now wired in ``_ta_dict_to_python_effect``.

    The bridge slice ``bridge-conditional-and-state-predicates`` added
    the ``kind == "conditional_if_source_power_at_least"`` arm that
    reads ``threshold`` (int, default 4) and recursively translates the
    nested effect (accepting both ``"inner"`` and ``"effect"`` keys for
    forward-compat), constructing
    ``ConditionalIfSourcePowerAtLeast(effect=inner_translated,
    threshold=threshold)``.

    FIELD-NAME SKEW handled: Python class uses ``effect=`` (not ``inner=``).
    Bridge arm accepts both ``"inner"`` and ``"effect"`` dict keys.

    EoE cards unblocked: Syr Vondam Sunstar Exemplar, Dawnstrike Vanguard,
    Frontline War-Rager.
    """
    import dataclasses
    from mtg_bot.effects.combinators import ConditionalIfSourcePowerAtLeast
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    # 1. ConditionalIfSourcePowerAtLeast exists and has the expected fields.
    fields = {f.name for f in dataclasses.fields(ConditionalIfSourcePowerAtLeast)}
    assert "effect" in fields, (
        "ConditionalIfSourcePowerAtLeast should have an 'effect' field (Effect) "
        "-- NOT 'inner'. This naming skew vs ConditionalIfYouGainedLifeAtLeast "
        "(Pin 1, which uses 'inner') matters for the bridge arm's construction. "
        f"Got fields: {fields!r}"
    )
    assert "threshold" in fields, (
        "ConditionalIfSourcePowerAtLeast should have a 'threshold' field (int). "
        f"Got fields: {fields!r}"
    )
    assert "inner" not in fields, (
        "ConditionalIfSourcePowerAtLeast should NOT have an 'inner' field; "
        "it uses 'effect' as the inner-effect field name (unlike Pin 1's class "
        "which uses 'inner'). "
        f"Got fields: {fields!r}"
    )

    # 2-3. Bridge NOW returns a ConditionalIfSourcePowerAtLeast -- no longer raises.
    eff_dict = {
        "kind": "conditional_if_source_power_at_least",
        "threshold": 4,
        "inner": {"kind": "draw_cards", "count": 1},
    }
    result = _ta_dict_to_python_effect(eff_dict)
    assert isinstance(result, ConditionalIfSourcePowerAtLeast), (
        "Bridge should now return a ConditionalIfSourcePowerAtLeast instance "
        "for kind='conditional_if_source_power_at_least'. "
        f"Got: {type(result).__name__!r}"
    )
    assert result.threshold == 4, (
        "Bridge should extract threshold=4 from the dict. "
        f"Got threshold={result.threshold!r}"
    )
    from mtg_bot.effects.generic.draw_mill import DrawCards
    assert isinstance(result.effect, DrawCards), (
        "Bridge should recursively translate the inner 'draw_cards' dict to a "
        "DrawCards instance stored in the 'effect' field. "
        f"Got: {type(result.effect).__name__!r}"
    )

    # 2b. Also verify the bridge accepts the "effect" key (not just "inner").
    eff_dict_effect_key = {
        "kind": "conditional_if_source_power_at_least",
        "threshold": 4,
        "effect": {"kind": "draw_cards", "count": 1},
    }
    result2 = _ta_dict_to_python_effect(eff_dict_effect_key)
    assert isinstance(result2, ConditionalIfSourcePowerAtLeast), (
        "Bridge should accept 'effect' as the dict key for the nested effect "
        "(forward-compat for when Rust standardizes the serialization key). "
        f"Got: {type(result2).__name__!r}"
    )

    # 4. Sanity: a WIRED effect kind ("draw_cards") round-trips cleanly.
    from mtg_bot.effects.base import Effect
    try:
        r3 = _ta_dict_to_python_effect({"kind": "draw_cards", "count": 1})
        assert isinstance(r3, Effect), (
            "Wired effect 'draw_cards' should produce an Effect instance; "
            f"got {type(r3).__name__}."
        )
    except ValueError as e:
        raise AssertionError(
            "Sanity: 'draw_cards' is a wired effect kind and should NOT raise "
            f"ValueError -- got: {e}"
        ) from e

    # 5. The default threshold is 4 -- matching every EoE card that uses this
    #    wrapper today.
    threshold_field = next(
        f for f in dataclasses.fields(ConditionalIfSourcePowerAtLeast)
        if f.name == "threshold"
    )
    assert threshold_field.default == 4, (
        "ConditionalIfSourcePowerAtLeast.threshold default should be 4 "
        "(matching every EoE card today: Syr Vondam, Sunstar Exemplar; "
        "Dawnstrike Vanguard; Frontline War-Rager). "
        f"Got default: {threshold_field.default!r}"
    )

    # 6. Field-name skew vs Pin 1: 'effect' present, 'inner' absent.
    assert "effect" in fields and "inner" not in fields, (
        "ConditionalIfSourcePowerAtLeast field layout: 'effect' present, "
        "'inner' absent -- contrasting with ConditionalIfYouGainedLifeAtLeast "
        "(Pin 1) which has 'inner' present, 'effect' absent. "
        "The bridge arm uses the correct field name for each class. "
        f"Got fields: {sorted(fields)!r}"
    )


# ---------------------------------------------------------------------------
# Pin 3 -- CLOSED: StateBound predicate family bridge arms added
#          bridge-conditional-and-state-predicates slice; 7+ EoE cards
#          unblocked (substrate): Sothera, the Supervoid; Voidforged Titan;
#          Insatiable Skittermaw; Kavaron Skywarden; Hylderblade;
#          Alpharael Stonechosen; Roving Actuator
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_state_bound_predicate_family_bridge_gap_sentinel_FIXED_parity():
    """Pin 3 CLOSED -- bridge arms for the ``StateBound`` predicate family
    now wired in ``_ta_dict_to_python_predicate`` + new helper
    ``_ta_dict_to_python_state_predicate``.

    The bridge slice ``bridge-conditional-and-state-predicates`` added:
      * ``kind == "state_bound"`` arm in ``_ta_dict_to_python_predicate``
        that calls ``_ta_dict_to_python_state_predicate(pred_dict["inner"])``
        and wraps the result: ``StateBound(inner_state_pred)``.
      * New helper ``_ta_dict_to_python_state_predicate`` that dispatches
        ``StatePredicate`` sub-kinds (``void_active``,
        ``any_player_controls_no_creatures``).

    Two-tier predicate architecture respected:
      Tier 1 ``TriggerPredicate`` (``StateBound``) wraps
      Tier 2 ``StatePredicate`` (``VoidActive``, ``AnyPlayerControlsNoCreatures``).

    EoE cards now having predicate substrate: Voidforged Titan, Insatiable
    Skittermaw, Kavaron Skywarden, Hylderblade, Alpharael Stonechosen,
    Roving Actuator (Void family) + Sothera, the Supervoid
    (AnyPlayerControlsNoCreatures).
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

    # 1. StateBound, VoidActive, AnyPlayerControlsNoCreatures exist
    #    and are the correct types.
    assert issubclass(StateBound, TriggerPredicate), (
        "StateBound should be a TriggerPredicate subclass "
        "(effects/predicates.py:392-406).  It bridges a StatePredicate "
        "into the TriggerPredicate tier by binding to source.controller_id. "
        "If this fails the class hierarchy was restructured -- update this pin."
    )
    assert issubclass(VoidActive, StatePredicate), (
        "VoidActive should be a StatePredicate subclass "
        "(effects/state_predicates.py:93-107).  It is a Tier-2 predicate: "
        "carries test(state, viewer_id) rather than matches(state, subjects, "
        "source). It must be wrapped in StateBound to be usable as a trigger "
        "predicate. "
        "If this fails the class hierarchy was restructured -- update this pin."
    )
    assert issubclass(AnyPlayerControlsNoCreatures, StatePredicate), (
        "AnyPlayerControlsNoCreatures should be a StatePredicate subclass "
        "(effects/state_predicates.py:231-259).  Same Tier-2 status as "
        "VoidActive. "
        "If this fails the class hierarchy was restructured -- update this pin."
    )

    # 2. StateBound wraps a StatePredicate (two-tier bridge).
    #    VoidActive and AnyPlayerControlsNoCreatures are NOT TriggerPredicates
    #    -- they can't be passed directly to TriggeredAbility.predicate.
    assert not issubclass(VoidActive, TriggerPredicate), (
        "VoidActive should NOT be a TriggerPredicate subclass -- it is a "
        "Tier-2 StatePredicate.  It must be wrapped in StateBound to reach "
        "the TriggerPredicate tier.  If VoidActive were promoted to "
        "TriggerPredicate, the StateBound wrapper would be unnecessary and "
        "the bridge gap would have a different shape."
    )
    assert not issubclass(AnyPlayerControlsNoCreatures, TriggerPredicate), (
        "AnyPlayerControlsNoCreatures should NOT be a TriggerPredicate "
        "subclass -- it is a Tier-2 StatePredicate.  Same reasoning as "
        "VoidActive above."
    )

    # 3. (a) state_bound + void_active: bridge now returns StateBound(VoidActive()).
    result_sb_va = _ta_dict_to_python_predicate(
        {"kind": "state_bound", "inner": {"kind": "void_active"}}
    )
    assert isinstance(result_sb_va, StateBound), (
        "Bridge should return a StateBound instance for kind='state_bound'. "
        f"Got: {type(result_sb_va).__name__!r}"
    )
    assert isinstance(result_sb_va.inner, VoidActive), (
        "StateBound.inner should be a VoidActive instance for "
        "inner kind='void_active'. "
        f"Got: {type(result_sb_va.inner).__name__!r}"
    )

    # 3b. state_bound + any_player_controls_no_creatures.
    result_sb_ap = _ta_dict_to_python_predicate(
        {
            "kind": "state_bound",
            "inner": {"kind": "any_player_controls_no_creatures"},
        }
    )
    assert isinstance(result_sb_ap, StateBound), (
        "Bridge should return a StateBound instance for kind='state_bound' "
        "with inner='any_player_controls_no_creatures'. "
        f"Got: {type(result_sb_ap).__name__!r}"
    )
    assert isinstance(result_sb_ap.inner, AnyPlayerControlsNoCreatures), (
        "StateBound.inner should be an AnyPlayerControlsNoCreatures instance. "
        f"Got: {type(result_sb_ap.inner).__name__!r}"
    )

    # 4. _ta_dict_to_python_state_predicate dispatches correctly.
    va = _ta_dict_to_python_state_predicate({"kind": "void_active"})
    assert isinstance(va, VoidActive), (
        "State predicate dispatcher should return VoidActive() for "
        "kind='void_active'. "
        f"Got: {type(va).__name__!r}"
    )
    ap = _ta_dict_to_python_state_predicate({"kind": "any_player_controls_no_creatures"})
    assert isinstance(ap, AnyPlayerControlsNoCreatures), (
        "State predicate dispatcher should return AnyPlayerControlsNoCreatures() "
        "for kind='any_player_controls_no_creatures'. "
        f"Got: {type(ap).__name__!r}"
    )

    # 5. Sanity: a WIRED predicate kind (``"always"``) round-trips cleanly.
    try:
        r_always = _ta_dict_to_python_predicate({"kind": "always"})
        from mtg_bot.effects.predicates import Always
        assert isinstance(r_always, Always), (
            "Wired predicate 'always' should produce an Always instance; "
            f"got {type(r_always).__name__}."
        )
    except ValueError as e:
        raise AssertionError(
            "Sanity: 'always' is a wired predicate kind and should NOT raise "
            f"ValueError -- got: {e}"
        ) from e

    # 6. Unknown StatePredicate kind raises ValueError from the state-predicate
    #    dispatcher (not a silent failure).
    with pytest.raises(ValueError) as exc_info_unk:
        _ta_dict_to_python_state_predicate({"kind": "totally_unknown_state_pred"})
    assert "totally_unknown_state_pred" in str(exc_info_unk.value), (
        "Unknown StatePredicate kind should raise ValueError mentioning the "
        "unknown kind name for easy debugging. "
        f"Got: {exc_info_unk.value!r}"
    )

    # 7. Document EoE cards now having predicate substrate via this fix.
    void_unblocked = [
        "Voidforged Titan",       # Void -- at beginning of end step trigger
        "Insatiable Skittermaw",  # Void -- at beginning of end step trigger
        "Kavaron Skywarden",      # Void -- at beginning of upkeep trigger
        "Hylderblade",            # Void -- at beginning of end step trigger
        "Alpharael Stonechosen",  # Void -- whenever Alpharael attacks
        "Roving Actuator",        # Void -- at beginning of end step trigger
    ]
    any_player_unblocked = [
        "Sothera, the Supervoid",  # end-step gate: "if a player controls
                                   # no creatures" (StateBound(
                                   # AnyPlayerControlsNoCreatures()))
    ]
    assert len(void_unblocked) >= 5, (
        "The StateBound(VoidActive()) predicate fix unblocks at least 5 EoE "
        f"cards; enumerated list has only {len(void_unblocked)} entries."
    )
    assert len(any_player_unblocked) == 1, (
        "The StateBound(AnyPlayerControlsNoCreatures()) predicate fix unblocks "
        "1 EoE card (Sothera, the Supervoid); "
        f"enumerated list has {len(any_player_unblocked)} entries."
    )
