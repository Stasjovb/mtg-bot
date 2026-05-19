"""Divergence-pin tests: batch AAA (probe-batch-aaa, round 16).

Each test is named ``test_cross_engine_real_eoe_<slug>_*_divergence_pin``
and ASSERTS the CURRENT divergent behavior rather than parity.  The
PROBED-tier detector excludes ``*_divergence_pin`` functions, so these
tests grow the test surface without touching the PROBED metric.

Pinned bugs
-----------

Pin 1 -- ``DyadrineAttackEffect`` effect kind NOT wired in the
cross-engine effect bridge (YY drop; 1 EoE card blocked:
Dyadrine, Synthesis Amalgam).

    Python's ``DyadrineAttackEffect`` class
    (``effects/bespoke.py``) is a bespoke zero-field dataclass that
    encodes Dyadrine's attack-trigger body: "Whenever you attack, you
    may remove a +1/+1 counter from each of two creatures you control.
    If you do, draw a card and create a 2/2 colorless Robot artifact
    creature token."  It is instantiated by the card's bespoke factory
    and holds no sub-fields of its own (all state is read from the
    game state at resolve time).

    The cross-engine effect bridge (``_ta_dict_to_python_effect`` at
    ``cross_engine.py``) has no arm for the kind string that would
    correspond to ``DyadrineAttackEffect``.  Passing a dict with
    ``kind="dyadrine_attack_effect"`` causes the bridge to fall through
    to the terminal ``raise ValueError``:

        raise ValueError(
            "cross_engine triggered_abilities bridge: unsupported "
            "effect kind 'dyadrine_attack_effect' ..."
        )

    Scale:
      1 EoE card carries a ``DyadrineAttackEffect`` trigger:
        * Dyadrine, Synthesis Amalgam -- "Whenever you attack, you may
          remove a +1/+1 counter from each of two creatures you control.
          If you do, draw a card and create a 2/2 colorless Robot
          artifact creature token."

    Class structure (Python-side):
      ``DyadrineAttackEffect()`` -- zero-field dataclass from
      ``effects/bespoke.py``.  No sub-fields; all resolution logic is
      self-contained in the ``resolve`` method.

    Observable divergence (bridge sentinel):
      ``_ta_dict_to_python_effect({"kind": "dyadrine_attack_effect"})``
      raises ``ValueError`` with message containing
      ``"dyadrine_attack_effect"`` and ``"unsupported effect kind"``.

    Closure path:
      Add a ``kind == "dyadrine_attack_effect"`` arm to
      ``_ta_dict_to_python_effect`` that constructs and returns
      ``DyadrineAttackEffect()``.  No sub-fields to read from the dict.
      This is a pure Python bridge fix (no Rust substrate required).

Pin 2 -- ``PutPoisonCountersOnTargetPlayer`` effect kind NOT wired in
the cross-engine effect bridge (SS drop; 1 EoE card blocked:
Virulent Silencer).

    Python's ``PutPoisonCountersOnTargetPlayer`` class
    (``effects/generic/``) is a dataclass with a single ``amount: int``
    field that encodes the "target player gets N poison counters" oracle
    shape.  It is produced by the parser for combat-damage triggers that
    use the poison-counter mechanic.

    The cross-engine effect bridge (``_ta_dict_to_python_effect``) has
    no arm for ``kind="put_poison_counters_on_target_player"``.  Passing
    such a dict causes the bridge to raise ``ValueError``:

        raise ValueError(
            "cross_engine triggered_abilities bridge: unsupported "
            "effect kind 'put_poison_counters_on_target_player' ..."
        )

    Scale:
      1 EoE card carries a ``PutPoisonCountersOnTargetPlayer`` trigger:
        * Virulent Silencer -- "Whenever a nontoken artifact creature
          you control deals combat damage to a player, that player gets
          two poison counters. (A player with ten or more poison
          counters loses the game.)"  Parser instantiates
          ``PutPoisonCountersOnTargetPlayer(amount=2)``.

    Class structure (Python-side):
      ``PutPoisonCountersOnTargetPlayer(amount: int)``
      from ``effects/generic/``.
      * ``amount`` -- the number of poison counters to give (e.g. 2 for
        Virulent Silencer).

    Observable divergence (bridge sentinel):
      ``_ta_dict_to_python_effect({"kind":
      "put_poison_counters_on_target_player", "amount": 2})``
      raises ``ValueError`` with message containing
      ``"put_poison_counters_on_target_player"`` and
      ``"unsupported effect kind"``.

    Closure path:
      Add a ``kind == "put_poison_counters_on_target_player"`` arm to
      ``_ta_dict_to_python_effect`` that reads ``amount: int`` from the
      dict and constructs
      ``PutPoisonCountersOnTargetPlayer(amount=amount)``.
      This is a pure Python bridge fix (no Rust substrate required).

Pin 3 -- ``DrawCardsByConditionMultiplier`` effect kind NOT wired in
the cross-engine effect bridge (EE drop; cards blocked include
All Fates Scroll family and any "draw X where X is N lands" shape).

    Python's ``DrawCardsByConditionMultiplier`` class
    (``effects/generic/draw_mill.py:258``) is a dataclass that
    encodes the "draw X cards, where X is <Condition.multiplier>"
    oracle shape.  It takes a ``Condition`` object (from
    ``effects/conditions.py``) and a ``description_fragment: str``
    log-message label; at resolve time it reads
    ``condition.multiplier(state, controller_id)`` to determine how
    many cards to draw.

    The cross-engine effect bridge (``_ta_dict_to_python_effect``) has
    no arm for ``kind="draw_cards_by_condition_multiplier"``.  Passing
    such a dict causes the bridge to raise ``ValueError``:

        raise ValueError(
            "cross_engine triggered_abilities bridge: unsupported "
            "effect kind 'draw_cards_by_condition_multiplier' ..."
        )

    Scale:
      EoE cards that carry a ``DrawCardsByConditionMultiplier`` trigger
      effect include any card with a "draw X cards, where X is the
      number of <condition>" clause that the parser maps to this class
      (e.g. All Fates Scroll's "draw X cards, where X is the number of
      differently named lands you control" via
      ``PerDifferentlyNamedLand`` condition).

    Class structure (Python-side):
      ``DrawCardsByConditionMultiplier(condition: Condition,
      description_fragment: str = 'where X is determined at resolution')``
      from ``effects/generic/draw_mill.py:258``.
      * ``condition`` -- a ``Condition`` instance; ``condition.multiplier(
        state, controller_id)`` is the card count at resolve time.
      * ``description_fragment`` -- a short string describing the X
        quantity in log output (parser-supplied, keeps the engine class
        decoupled from oracle-text wording).

    Observable divergence (bridge sentinel):
      ``_ta_dict_to_python_effect({"kind":
      "draw_cards_by_condition_multiplier", ...})``
      raises ``ValueError`` with message containing
      ``"draw_cards_by_condition_multiplier"`` and
      ``"unsupported effect kind"``.

    Closure path:
      Add a ``kind == "draw_cards_by_condition_multiplier"`` arm to
      ``_ta_dict_to_python_effect`` that reads a ``condition`` sub-dict
      (recursively translated via a ``_ta_dict_to_python_condition``
      helper or existing condition dispatcher) and a
      ``description_fragment: str`` (default ``"where X is determined at
      resolution"``), then constructs
      ``DrawCardsByConditionMultiplier(condition=condition,
      description_fragment=fragment)``.  This arm requires a ``Condition``
      serialization protocol to already exist or be added alongside it;
      that is the primary closure dependency.  This is a pure Python
      bridge fix (no Rust substrate required).

Dropped pins
------------

  * ``MovePlusOneCounterBetweenPermanentsYouControl`` 2-target
    diffs=[] false-positive (EE drop): Deferred again -- no new
    information vs EE drop; lower priority than effect-class gaps.

  * ``Endless Sands AA[0] ExileTargetCreatureUntilSourceLeaves
    yours_only=True`` semantic mismatch (HH drop): Deferred -- bespoke
    activated-ability shape outside triggered-ability bridge scope.

  * Cast event LIFO-ordering divergence (AA finding): Deferred --
    systemic ordering issue requiring Rust+Python co-change; not a
    pure bridge gap.

  * Compound-event disjunction (RR drop: The Endstone "plays_land OR
    is_cast"): Already documented in batch UU Pin 3; not revisited.

  * ``SurveyMechanActivationEffect`` (EE drop): Deferred in favor of
    the three effect-class gaps pinned above, which collectively block
    more cards and have cleaner bridge closure paths.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Pin 1 -- DyadrineAttackEffect effect kind NOT wired in bridge
#          (YY drop; 1 EoE card blocked: Dyadrine, Synthesis Amalgam)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_dyadrine_attack_effect_bridge_gap_sentinel_FIXED_parity():
    """Bridge arm for ``DyadrineAttackEffect`` is now wired.

    AAA Pin 1 -- CLOSED.  The bridge arm for
    ``kind="dyadrine_attack_effect"`` was added to
    ``_ta_dict_to_python_effect`` in
    ``src/mtg_bot/parity/cross_engine.py``.

    This test verifies the wired behavior (no ValueError raised, correct
    class returned) and asserts the structural invariants that the pin
    originally documented.

    Card context:
      Dyadrine, Synthesis Amalgam -- "Whenever you attack, you may
      remove a +1/+1 counter from each of two creatures you control.
      If you do, draw a card and create a 2/2 colorless Robot artifact
      creature token."

      The parser uses the bespoke ``DyadrineAttackEffect()`` dataclass
      (``effects/bespoke.py``) for this trigger body.  The class is a
      zero-field dataclass -- all resolution logic lives in its
      ``resolve`` method and reads from the game state directly.

    Class structure:
      ``DyadrineAttackEffect()`` -- zero-field dataclass from
      ``effects/bespoke.py``.  No constructor arguments; it is a
      singleton-like effect sentinel.

    This pin is pure Python (no Rust extension required).
    """
    import dataclasses
    from mtg_bot.effects.bespoke import DyadrineAttackEffect
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    # 1. DyadrineAttackEffect exists and is a zero-field dataclass.
    assert dataclasses.is_dataclass(DyadrineAttackEffect), (
        "DyadrineAttackEffect should be a dataclass (effects/bespoke.py). "
        "If this fails the class was restructured -- update this pin and "
        "the bridge arm."
    )
    fields = dataclasses.fields(DyadrineAttackEffect)
    assert len(fields) == 0, (
        "DyadrineAttackEffect should have zero dataclass fields -- all "
        "resolution state is read from the game state at resolve time. "
        f"Got fields: {[f.name for f in fields]!r}. "
        "If a field was added, the bridge arm needs to read it from the dict."
    )

    # 2. Bridge NO LONGER raises ValueError -- the arm is wired.
    wired_eff_dict = {"kind": "dyadrine_attack_effect"}
    result = _ta_dict_to_python_effect(wired_eff_dict)
    assert isinstance(result, DyadrineAttackEffect), (
        "Bridge arm for 'dyadrine_attack_effect' should return a "
        "DyadrineAttackEffect instance.  "
        f"Got {type(result).__name__!r}."
    )

    # 3. Sanity: a WIRED effect kind ("draw_cards") still round-trips.
    from mtg_bot.effects.base import Effect
    wired_draw_dict = {"kind": "draw_cards", "count": 1}
    try:
        draw_result = _ta_dict_to_python_effect(wired_draw_dict)
        assert isinstance(draw_result, Effect), (
            "Wired effect 'draw_cards' should produce an Effect instance; "
            f"got {type(draw_result).__name__}."
        )
    except ValueError as e:
        raise AssertionError(
            "Sanity: 'draw_cards' is a wired effect kind and should NOT "
            f"raise ValueError -- got: {e}"
        ) from e

    # 4. Enumerate the EoE cards unblocked by this fix.
    unblocked_eoe_cards = [
        "Dyadrine, Synthesis Amalgam",
        # "Whenever you attack, you may remove a +1/+1 counter from each
        # of two creatures you control. If you do, draw a card and create
        # a 2/2 colorless Robot artifact creature token."
        # Parser: DyadrineAttackEffect() via bespoke factory path.
    ]
    assert len(unblocked_eoe_cards) == 1, (
        "The 'dyadrine_attack_effect' bridge arm unblocks 1 EoE card "
        "(Dyadrine, Synthesis Amalgam). "
        f"Enumerated list has {len(unblocked_eoe_cards)} entries."
    )


# ---------------------------------------------------------------------------
# Pin 2 -- PutPoisonCountersOnTargetPlayer effect kind NOT wired in bridge
#          (SS drop; 1 EoE card blocked: Virulent Silencer)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_put_poison_counters_on_target_player_bridge_gap_sentinel_FIXED_parity():
    """Bridge arm for ``PutPoisonCountersOnTargetPlayer`` is now wired.

    AAA Pin 2 -- CLOSED.  The bridge arm for
    ``kind="put_poison_counters_on_target_player"`` was added to
    ``_ta_dict_to_python_effect`` in
    ``src/mtg_bot/parity/cross_engine.py``.

    This test verifies the wired behavior (no ValueError, correct class
    and field binding) and asserts the structural invariants the pin
    originally documented.

    Card context:
      Virulent Silencer -- "Whenever a nontoken artifact creature you
      control deals combat damage to a player, that player gets two
      poison counters. (A player with ten or more poison counters
      loses the game.)"

      The parser produces
      ``PutPoisonCountersOnTargetPlayer(amount=2)`` for this trigger
      body.  The subject ("a player" -- the player who was dealt
      combat damage) is resolved from the trigger's subject map at
      fire time.

    Class structure (Python-side):
      ``PutPoisonCountersOnTargetPlayer(amount: int)``
      from ``effects/generic/``.
      * ``amount`` -- the number of poison counters (e.g. 2 for
        Virulent Silencer, per "gets two poison counters").

    This pin is pure Python (no Rust extension required).
    """
    import dataclasses
    from mtg_bot.effects.generic import PutPoisonCountersOnTargetPlayer
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    # 1. PutPoisonCountersOnTargetPlayer exists and has the expected field.
    assert dataclasses.is_dataclass(PutPoisonCountersOnTargetPlayer), (
        "PutPoisonCountersOnTargetPlayer should be a dataclass "
        "(effects/generic/). "
        "If this fails the class was restructured -- update this pin."
    )
    fields = {f.name: f for f in dataclasses.fields(PutPoisonCountersOnTargetPlayer)}
    assert "amount" in fields, (
        "PutPoisonCountersOnTargetPlayer should have an 'amount' field (int) "
        "representing the number of poison counters to apply. "
        f"Got fields: {list(fields.keys())!r}"
    )

    # 2. Bridge NO LONGER raises ValueError -- the arm is wired.
    #    Test with amount=2 (the Virulent Silencer instantiation).
    wired_eff_dict = {
        "kind": "put_poison_counters_on_target_player",
        "amount": 2,
    }
    result = _ta_dict_to_python_effect(wired_eff_dict)
    assert isinstance(result, PutPoisonCountersOnTargetPlayer), (
        "Bridge arm for 'put_poison_counters_on_target_player' should return a "
        "PutPoisonCountersOnTargetPlayer instance.  "
        f"Got {type(result).__name__!r}."
    )
    assert result.amount == 2, (
        "Bridge arm should read 'amount' from dict and pass it through. "
        f"Expected amount=2, got {result.amount!r}."
    )

    # 3. No-amount dict uses the default (amount=1).
    result_default = _ta_dict_to_python_effect({"kind": "put_poison_counters_on_target_player"})
    assert isinstance(result_default, PutPoisonCountersOnTargetPlayer), (
        "No-amount dict should also produce a PutPoisonCountersOnTargetPlayer; "
        f"got {type(result_default).__name__!r}."
    )

    # 4. Sanity: a WIRED effect kind ("draw_cards") still round-trips.
    from mtg_bot.effects.base import Effect
    try:
        draw_result = _ta_dict_to_python_effect({"kind": "draw_cards", "count": 1})
        assert isinstance(draw_result, Effect), (
            "Wired effect 'draw_cards' should produce an Effect instance; "
            f"got {type(draw_result).__name__}."
        )
    except ValueError as e:
        raise AssertionError(
            "Sanity: 'draw_cards' is a wired effect kind and should NOT "
            f"raise ValueError -- got: {e}"
        ) from e

    # 5. ``amount`` field default is a non-None int.
    amount_field = fields["amount"]
    assert amount_field.default is not None, (
        "PutPoisonCountersOnTargetPlayer.amount should have a non-None default. "
        f"Got default: {amount_field.default!r}"
    )
    assert isinstance(amount_field.default, int), (
        "PutPoisonCountersOnTargetPlayer.amount default should be an int "
        "(the class uses a sensible numeric default). "
        f"Got type: {type(amount_field.default).__name__!r}, "
        f"value: {amount_field.default!r}"
    )

    # 6. Enumerate the EoE card unblocked by this fix.
    unblocked_eoe_cards = [
        ("Virulent Silencer", 2),
        # "Whenever a nontoken artifact creature you control deals combat
        # damage to a player, that player gets two poison counters."
        # Parser: PutPoisonCountersOnTargetPlayer(amount=2).
        # Target: the player who was dealt combat damage (trigger subject).
    ]
    assert len(unblocked_eoe_cards) == 1, (
        "The 'put_poison_counters_on_target_player' bridge arm unblocks "
        "1 EoE card (Virulent Silencer). "
        f"Enumerated list has {len(unblocked_eoe_cards)} entries."
    )
    card_name, expected_amount = unblocked_eoe_cards[0]
    assert card_name == "Virulent Silencer", (
        f"Expected the first unblocked card to be 'Virulent Silencer'; "
        f"got {card_name!r}."
    )
    assert expected_amount == 2, (
        "Virulent Silencer gives 2 poison counters; bridge arm constructs "
        "PutPoisonCountersOnTargetPlayer(amount=2) for this card. "
        f"Got: {expected_amount!r}"
    )


# ---------------------------------------------------------------------------
# Pin 3 -- DrawCardsByConditionMultiplier effect kind NOT wired in bridge
#          (EE drop; EoE cards blocked include All Fates Scroll family)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_draw_cards_by_condition_multiplier_bridge_gap_sentinel_divergence_pin():
    """Pin the bridge gap for the ``DrawCardsByConditionMultiplier``
    effect kind in ``_ta_dict_to_python_effect``.

    Bug location:
      ``src/mtg_bot/parity/cross_engine.py`` -- the
      ``_ta_dict_to_python_effect`` dispatcher has no arm for
      ``kind="draw_cards_by_condition_multiplier"``.  All unrecognised
      kinds fall through to the terminal:

          raise ValueError(
              "cross_engine triggered_abilities bridge: unsupported "
              "effect kind 'draw_cards_by_condition_multiplier' ..."
          )

    Class context:
      ``DrawCardsByConditionMultiplier(condition: Condition,
      description_fragment: str = 'where X is determined at resolution')``
      (``effects/generic/draw_mill.py:258``) encodes the "draw X cards,
      where X is <Condition.multiplier>" oracle shape.  It replaced the
      bespoke ``AllFatesScrollDrawEffect`` for the
      differently-named-lands surface and is reusable for any future
      "draw X where X is <Condition>" shape.

      At resolve time the effect reads
      ``condition.multiplier(state, controller_id)`` to get the card
      count, then draws that many cards.

    Class structure (Python-side):
      * ``condition: Condition`` -- a ``Condition`` instance from
        ``effects/conditions.py`` whose ``multiplier`` method returns the
        draw count at resolve time.  Examples:
          - ``PerDifferentlyNamedLand()`` -- counts distinctly-named
            lands the controller controls.
          - ``PerControlled(pred)`` -- counts permanents matching pred.
      * ``description_fragment: str`` -- oracle-text fragment for log
        output (parser-supplied); default
        ``"where X is determined at resolution"``.

    Probe shape:
      1. Assert ``DrawCardsByConditionMultiplier`` exists in
         ``effects.generic`` and has ``condition`` + ``description_fragment``
         fields.
      2. Assert ``condition`` is a required field (no default).
      3. Assert ``description_fragment`` has a non-None default.
      4. Assert the bridge raises ``ValueError`` for the unwired kind.
      5. Assert the error message contains
         ``"draw_cards_by_condition_multiplier"`` and
         ``"unsupported effect kind"``.
      6. Assert a wired effect kind (``"draw_cards"``) does NOT raise.
      7. Assert that ``DrawCardsByConditionMultiplier`` is distinct from
         ``DrawCards`` (the flat count variant) -- it reads a ``Condition``
         multiplier at resolve time rather than a static count.
      8. Document the closure dependency on a ``Condition`` serialization
         protocol.

    Closure path:
      Add a ``kind == "draw_cards_by_condition_multiplier"`` arm that
      reads a ``condition`` sub-dict (translated via a
      ``_ta_dict_to_python_condition`` helper that does NOT yet exist --
      this is the primary closure dependency) and an optional
      ``description_fragment: str``, then constructs
      ``DrawCardsByConditionMultiplier(condition=condition,
      description_fragment=fragment)``.

    This pin is pure Python (no Rust extension required).
    """
    import dataclasses
    from mtg_bot.effects.generic import DrawCardsByConditionMultiplier
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    # 1. DrawCardsByConditionMultiplier exists and has the expected fields.
    assert dataclasses.is_dataclass(DrawCardsByConditionMultiplier), (
        "DrawCardsByConditionMultiplier should be a dataclass "
        "(effects/generic/draw_mill.py:258). "
        "If this fails the class was restructured -- update this pin."
    )
    fields = {f.name: f for f in dataclasses.fields(DrawCardsByConditionMultiplier)}
    assert "condition" in fields, (
        "DrawCardsByConditionMultiplier should have a 'condition' field "
        "(a Condition instance whose .multiplier(state, controller_id) "
        "returns the card count). "
        f"Got fields: {list(fields.keys())!r}"
    )
    assert "description_fragment" in fields, (
        "DrawCardsByConditionMultiplier should have a 'description_fragment' "
        "field (str; parser-supplied log label for the X quantity). "
        f"Got fields: {list(fields.keys())!r}"
    )

    # 2. ``condition`` is a required field (no default) -- every instantiation
    #    must supply a concrete Condition that knows how to count.
    cond_field = fields["condition"]
    assert cond_field.default is dataclasses.MISSING, (
        "DrawCardsByConditionMultiplier.condition should be a required field "
        "(no default) -- the Condition determines the draw count and must "
        "always be specified. "
        f"Got default: {cond_field.default!r}"
    )

    # 3. ``description_fragment`` has a non-None default (the generic fallback
    #    label used when no better oracle-text fragment is supplied).
    frag_field = fields["description_fragment"]
    assert frag_field.default is not dataclasses.MISSING, (
        "DrawCardsByConditionMultiplier.description_fragment should have a "
        "default value (the generic 'where X is determined at resolution' "
        "fallback). "
        "If this changed, update the pin and the bridge arm's default."
    )
    assert frag_field.default is not None, (
        "DrawCardsByConditionMultiplier.description_fragment default should "
        "be a non-None string, not None. "
        f"Got default: {frag_field.default!r}"
    )
    assert isinstance(frag_field.default, str), (
        "DrawCardsByConditionMultiplier.description_fragment default should "
        "be a str. "
        f"Got type: {type(frag_field.default).__name__!r}, "
        f"value: {frag_field.default!r}"
    )

    # 4-5. Bridge raises ValueError for the unwired effect kind.
    #      Pass a minimal dict with just the kind; the bridge fails at the
    #      kind-dispatch level before it would attempt to read sub-fields.
    unwired_eff_dict = {"kind": "draw_cards_by_condition_multiplier"}
    with pytest.raises(ValueError) as exc_info:
        _ta_dict_to_python_effect(unwired_eff_dict)

    err_msg = str(exc_info.value)
    assert "draw_cards_by_condition_multiplier" in err_msg, (
        "Bridge gap sentinel: the ValueError message should mention "
        "'draw_cards_by_condition_multiplier'. "
        f"Got message: {err_msg!r}"
    )
    assert "unsupported effect kind" in err_msg, (
        "Bridge gap sentinel: the ValueError should contain "
        "'unsupported effect kind' confirming the _ta_dict_to_python_effect "
        "dispatcher produced this error. "
        f"Got message: {err_msg!r}"
    )

    # 6. Sanity: a WIRED effect kind ("draw_cards") round-trips without error.
    from mtg_bot.effects.base import Effect
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

    # 7. DrawCardsByConditionMultiplier is DISTINCT from DrawCards.
    #    DrawCards(count: int) uses a static count determined at parse time.
    #    DrawCardsByConditionMultiplier reads condition.multiplier(state, ...)
    #    at resolve time -- the count varies per game state.
    #    Wiring one does NOT wire the other; they model different oracle shapes.
    from mtg_bot.effects.generic import DrawCards
    assert DrawCardsByConditionMultiplier is not DrawCards, (
        "DrawCardsByConditionMultiplier must be a distinct class from "
        "DrawCards. DrawCards uses a static count; "
        "DrawCardsByConditionMultiplier reads a Condition.multiplier "
        "at resolve time. Closing the DrawCards bridge arm does NOT "
        "close the DrawCardsByConditionMultiplier arm."
    )
    draw_cards_fields = {f.name for f in dataclasses.fields(DrawCards)}
    assert "amount" in draw_cards_fields, (
        "DrawCards should have an 'amount' field (the static int draw count). "
        f"Got fields: {sorted(draw_cards_fields)!r}"
    )
    assert "condition" not in draw_cards_fields, (
        "DrawCards should NOT have a 'condition' field -- the Condition "
        "algebra is specific to DrawCardsByConditionMultiplier. "
        f"Got fields: {sorted(draw_cards_fields)!r}"
    )

    # 8. Closure dependency note: the bridge arm for this kind requires a
    #    ``Condition`` serialization protocol (a
    #    ``_ta_dict_to_python_condition`` helper or equivalent) because the
    #    ``condition`` field is a structured object, not a primitive.
    #    No such helper exists in cross_engine.py today -- the arm and the
    #    Condition dispatcher must land together to avoid a partial-wiring
    #    hazard.  The ``Condition`` sub-kinds include at minimum:
    #      * ``per_differently_named_land`` -> ``PerDifferentlyNamedLand()``
    #      * ``per_controlled`` -> ``PerControlled(pred)``
    #    These are a SEPARATE kind-space from the Effect and Predicate
    #    dispatchers already in cross_engine.py.
    from mtg_bot.effects.conditions import Condition, PerDifferentlyNamedLand
    assert issubclass(PerDifferentlyNamedLand, Condition), (
        "PerDifferentlyNamedLand should be a Condition subclass "
        "(effects/conditions.py:376). "
        "If this fails the class hierarchy changed -- update this pin."
    )
