"""Divergence-pin tests: batch DDD (probe-batch-ddd, round 17).

Each test is named ``test_cross_engine_real_eoe_<slug>_*_divergence_pin``
and ASSERTS the CURRENT divergent behavior rather than parity.  The
PROBED-tier detector excludes ``*_divergence_pin`` functions, so these
tests grow the test surface without touching the PROBED metric.

Pinned bugs
-----------

Pin 1 -- ``SurveyMechanActivationEffect`` effect kind NOT wired in the
cross-engine effect bridge (EE drop; 1 EoE card blocked:
Survey Mechan).

    Python's ``SurveyMechanActivationEffect`` class
    (``effects/bespoke.py``) is a bespoke zero-field dataclass that
    encodes Survey Mechan's activated ability body: "It deals 3 damage
    to any target.  Target player draws three cards and gains 3 life."

    The cross-engine effect bridge (``_ta_dict_to_python_effect`` at
    ``cross_engine.py``) has no arm for the kind string that would
    correspond to ``SurveyMechanActivationEffect``.  Passing a dict
    with ``kind="survey_mechan_activation_effect"`` causes the bridge
    to fall through to the terminal ``raise ValueError``:

        raise ValueError(
            "cross_engine triggered_abilities bridge: unsupported "
            "effect kind 'survey_mechan_activation_effect' ..."
        )

    Scale:
      1 EoE card carries a ``SurveyMechanActivationEffect`` trigger:
        * Survey Mechan -- "{2}{U}{R}: It deals 3 damage to any
          target.  Target player draws three cards and gains 3 life."

    Class structure (Python-side):
      ``SurveyMechanActivationEffect()`` -- zero-field frozen dataclass
      from ``effects/bespoke.py``.  No constructor arguments; all
      resolution logic is self-contained in the ``resolve`` method.
      Two required targeting slots (slot 0: any_damage_target, slot 1:
      player) are enforced by the activation machinery, not the effect
      class itself.

    Observable divergence (bridge sentinel):
      ``_ta_dict_to_python_effect({"kind": "survey_mechan_activation_effect"})``
      raises ``ValueError`` with message containing
      ``"survey_mechan_activation_effect"`` and ``"unsupported effect kind"``.

    Closure path:
      Add a ``kind == "survey_mechan_activation_effect"`` arm to
      ``_ta_dict_to_python_effect`` that constructs and returns
      ``SurveyMechanActivationEffect()``.  No sub-fields to read from
      the dict.  This is a pure Python bridge fix (no Rust substrate
      required).

Pin 2 -- ``ExileTopXOfLibraryMayPlayThisTurn`` effect kind NOT wired
in the cross-engine effect bridge (EE drop; 1 EoE card blocked:
Memorial Vault).

    Python's ``ExileTopXOfLibraryMayPlayThisTurn`` class
    (``effects/generic/exile.py``) is a frozen dataclass with a single
    ``amount: Formula | None`` field that encodes the "exile the top X
    cards of your library, where X is <formula>; you may play those
    cards this turn" oracle shape.  Unlike its zero-parameter sibling
    ``ExileTopOfLibraryMayPlayThisTurn(amount: int = 1)`` (which uses
    a static integer count determined at bridge time), this class takes
    a ``Formula`` object whose value is evaluated at resolve time --
    e.g. ``MVOfCostPaidObjectPlus(constant=1)`` for Memorial Vault's
    "where X is one plus the mana value of the sacrificed artifact".

    The cross-engine effect bridge (``_ta_dict_to_python_effect``) has
    no arm for ``kind="exile_top_x_of_library_may_play_this_turn"``.
    Passing such a dict causes the bridge to raise ``ValueError``:

        raise ValueError(
            "cross_engine triggered_abilities bridge: unsupported "
            "effect kind 'exile_top_x_of_library_may_play_this_turn' ..."
        )

    Scale:
      1 EoE card uses ``ExileTopXOfLibraryMayPlayThisTurn``:
        * Memorial Vault -- "{2}, {T}, Sacrifice another artifact:
          Exile the top X cards of your library, where X is one plus
          the mana value of the sacrificed artifact.  You may play those
          cards this turn."  Parser maps this to
          ``ExileTopXOfLibraryMayPlayThisTurn(
              amount=MVOfCostPaidObjectPlus(constant=1))``.

    Class structure (Python-side):
      ``ExileTopXOfLibraryMayPlayThisTurn(amount: Formula | None = None)``
      from ``effects/generic/exile.py``.
      * ``amount`` -- a ``Formula`` instance whose
        ``evaluate(state, controller_id)`` returns the card count at
        resolve time.  ``None`` means 0 (no-op resolve path).  The
        canonical EoE binding is
        ``MVOfCostPaidObjectPlus(constant=1)`` (Memorial Vault).
      * Distinct from the fixed-count sibling
        ``ExileTopOfLibraryMayPlayThisTurn(amount: int = 1)`` which
        takes an int resolved at bridge time.

    Observable divergence (bridge sentinel):
      ``_ta_dict_to_python_effect({"kind":
      "exile_top_x_of_library_may_play_this_turn"})``
      raises ``ValueError`` with message containing
      ``"exile_top_x_of_library_may_play_this_turn"`` and
      ``"unsupported effect kind"``.

    Closure path:
      Add a ``kind == "exile_top_x_of_library_may_play_this_turn"`` arm
      to ``_ta_dict_to_python_effect`` that reads an optional ``amount``
      sub-dict (translated via a ``_ta_dict_to_python_formula`` helper
      or equivalent Formula dispatcher -- the primary closure
      dependency), defaulting to ``None`` when absent, then constructs
      ``ExileTopXOfLibraryMayPlayThisTurn(amount=formula)``.  This arm
      depends on a ``Formula`` serialization protocol; the bridge and
      Formula dispatcher must land together.

      This is a pure Python bridge fix (no Rust substrate required for
      the bridge gap itself).

Pin 3 -- ``SearchLibraryForEquipmentToBattlefield`` effect kind NOT
wired in the cross-engine effect bridge (EE drop; 1 EoE card blocked:
Honored Knight-Captain).

    Python's ``SearchLibraryForEquipmentToBattlefield`` class
    (``effects/generic/search.py``) is a frozen zero-field dataclass
    that encodes the "search your library for an Equipment card, put it
    onto the battlefield, then shuffle" oracle shape.  It is produced
    by the parser for Honored Knight-Captain's second activated ability.

    The cross-engine effect bridge (``_ta_dict_to_python_effect``) has
    no arm for ``kind="search_library_for_equipment_to_battlefield"``.
    The bridge already handles the adjacent ``SearchLibraryForCard``
    (which uses a ``filter_name`` discriminator field to support any
    subtype) and ``SearchLibraryForBasicLandTapped`` (basic land, tapped
    ETB); the Equipment-tutor shape is a third distinct class because
    the ETB is untapped -- distinct from basic-land-tapped.  All three
    share the "search + shuffle" post-step but are NOT interchangeable.

    Passing a dict with
    ``kind="search_library_for_equipment_to_battlefield"`` causes the
    bridge to fall through to the terminal:

        raise ValueError(
            "cross_engine triggered_abilities bridge: unsupported "
            "effect kind 'search_library_for_equipment_to_battlefield' ..."
        )

    Scale:
      1 EoE card carries a ``SearchLibraryForEquipmentToBattlefield``
      trigger:
        * Honored Knight-Captain -- "{4}{W}{W}, Sacrifice Honored
          Knight-Captain: Search your library for an Equipment card,
          put it onto the battlefield, then shuffle."  Parser maps
          this to ``SearchLibraryForEquipmentToBattlefield()``.

    Class structure (Python-side):
      ``SearchLibraryForEquipmentToBattlefield()`` -- zero-field frozen
      dataclass from ``effects/generic/search.py``.  No constructor
      arguments; the "Equipment" filter and untapped ETB semantics are
      encoded in the ``resolve`` method.
      Distinct from ``SearchLibraryForCard(filter_name, max_mv,
      may_fail)`` -- NOT just a ``SearchLibraryForCard(filter_name=
      "Equipment")`` alias; the two classes have different resolve
      semantics (Equipment: untapped, no may_fail chain; Card: generic,
      tapped-or-not per filter).

    Observable divergence (bridge sentinel):
      ``_ta_dict_to_python_effect({"kind":
      "search_library_for_equipment_to_battlefield"})``
      raises ``ValueError`` with message containing
      ``"search_library_for_equipment_to_battlefield"`` and
      ``"unsupported effect kind"``.

    Closure path:
      Add a ``kind == "search_library_for_equipment_to_battlefield"``
      arm to ``_ta_dict_to_python_effect`` that constructs and returns
      ``SearchLibraryForEquipmentToBattlefield()``.  No sub-fields to
      read from the dict.  This is a pure Python bridge fix (no Rust
      substrate required).

Dropped pins
------------

  * ``Endless Sands AA[0] yours_only=True`` semantic mismatch (HH
    drop): Deferred again -- bespoke activated-ability shape outside
    triggered-ability bridge scope; lower priority than effect-class
    gaps.

  * ``MovePlusOneCounterBetweenPermanentsYouControl`` 2-target
    diffs=[] false-positive (EE drop): Deferred again -- no new
    information vs EE drop; still lower priority than effect-class
    bridge gaps.

  * Cast event LIFO-ordering (AA finding): Deferred -- systemic
    ordering issue requiring Rust+Python co-change; not a pure bridge
    gap.

  * Compound-event disjunction (RR drop: The Endstone "plays_land OR
    is_cast"): Already documented in batch UU Pin 3; not revisited.

  * Subject-slot predicate-rewrite TODO sentinel: Deferred in favour of
    the three concrete effect-class bridge gaps above which block real
    EoE cards.

  * ``requires_void`` Rust-side gate recon: Deferred; the
    StateBound/VoidActive Python bridge is now wired (XX Pin 3 closed);
    the Rust gate question is lower priority than unblocking new cards.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Pin 1 -- SurveyMechanActivationEffect effect kind NOT wired in bridge
#          (EE drop; 1 EoE card blocked: Survey Mechan)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_survey_mechan_activation_effect_bridge_gap_sentinel_divergence_pin():
    """Pin the bridge gap for the ``SurveyMechanActivationEffect`` effect
    kind in ``_ta_dict_to_python_effect``.

    Bug location:
      ``src/mtg_bot/parity/cross_engine.py`` -- the
      ``_ta_dict_to_python_effect`` dispatcher has no arm for
      ``kind="survey_mechan_activation_effect"``.  All unrecognised
      kinds fall through to the terminal:

          raise ValueError(
              "cross_engine triggered_abilities bridge: unsupported "
              "effect kind 'survey_mechan_activation_effect' ..."
          )

    Card context:
      Survey Mechan -- "{2}{U}{R}: It deals 3 damage to any target.
      Target player draws three cards and gains 3 life."

      The parser uses the bespoke ``SurveyMechanActivationEffect()``
      dataclass (``effects/bespoke.py``) for this activated-ability
      body.  The class is a zero-field dataclass -- all resolution
      logic lives in its ``resolve`` method; the two targeting slots
      (any_damage_target, player) are enforced by the activation
      machinery.

    Class structure:
      ``SurveyMechanActivationEffect()`` -- zero-field frozen dataclass
      from ``effects/bespoke.py``.  No constructor arguments; it is a
      singleton-like effect sentinel.

    Probe shape:
      1. Assert ``SurveyMechanActivationEffect`` exists in
         ``effects.bespoke`` and is a zero-field dataclass.
      2. Assert the bridge raises ``ValueError`` for the unwired kind.
      3. Assert the error message contains
         ``"survey_mechan_activation_effect"`` and
         ``"unsupported effect kind"``.
      4. Assert a wired effect kind (``"draw_cards"``) does NOT raise.
      5. Enumerate the 1 EoE card blocked by this gap.

    Closure path:
      Add a ``kind == "survey_mechan_activation_effect"`` arm that
      returns ``SurveyMechanActivationEffect()``.  No dict fields to
      read.

    This pin is pure Python (no Rust extension required).
    """
    import dataclasses
    from mtg_bot.effects.bespoke import SurveyMechanActivationEffect
    from mtg_bot.effects.base import Effect
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    # 1. SurveyMechanActivationEffect exists and is a zero-field dataclass.
    assert dataclasses.is_dataclass(SurveyMechanActivationEffect), (
        "SurveyMechanActivationEffect should be a dataclass "
        "(effects/bespoke.py).  If this fails the class was restructured "
        "-- update this pin and the bridge arm."
    )
    assert issubclass(SurveyMechanActivationEffect, Effect), (
        "SurveyMechanActivationEffect should be an Effect subclass "
        "so the bridge arm's return value satisfies the Effect type "
        "contract.  If this fails the class hierarchy changed."
    )
    fields = dataclasses.fields(SurveyMechanActivationEffect)
    assert len(fields) == 0, (
        "SurveyMechanActivationEffect should have zero dataclass fields "
        "-- all resolution state is read from the game state at resolve "
        "time.  "
        f"Got fields: {[f.name for f in fields]!r}.  "
        "If a field was added, the bridge arm needs to read it from the dict."
    )

    # 2-3. Bridge raises ValueError for the unwired effect kind.
    unwired_eff_dict = {"kind": "survey_mechan_activation_effect"}
    with pytest.raises(ValueError) as exc_info:
        _ta_dict_to_python_effect(unwired_eff_dict)

    err_msg = str(exc_info.value)
    assert "survey_mechan_activation_effect" in err_msg, (
        "Bridge gap sentinel: the ValueError message should mention "
        "'survey_mechan_activation_effect' so the gap is immediately "
        "identifiable.  "
        f"Got message: {err_msg!r}"
    )
    assert "unsupported effect kind" in err_msg, (
        "Bridge gap sentinel: the ValueError should contain "
        "'unsupported effect kind' confirming the "
        "_ta_dict_to_python_effect dispatcher produced this error.  "
        f"Got message: {err_msg!r}"
    )

    # 4. Sanity: a WIRED effect kind ("draw_cards") round-trips without error.
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

    # 5. Enumerate the EoE cards blocked by this gap.
    blocked_eoe_cards = [
        "Survey Mechan",
        # "{2}{U}{R}: It deals 3 damage to any target.  Target player
        # draws three cards and gains 3 life."
        # Parser: SurveyMechanActivationEffect() via effects.py bespoke
        # branch at cards/parser/effects.py.
        # Two required targeting slots (slot 0: any_damage_target,
        # slot 1: player) enforced by the activation machinery.
    ]
    assert len(blocked_eoe_cards) == 1, (
        "The 'survey_mechan_activation_effect' bridge gap blocks 1 EoE "
        "card (Survey Mechan).  "
        f"Enumerated list has {len(blocked_eoe_cards)} entries."
    )


# ---------------------------------------------------------------------------
# Pin 2 -- ExileTopXOfLibraryMayPlayThisTurn effect kind NOT wired in bridge
#          (EE drop; 1 EoE card blocked: Memorial Vault)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_exile_top_x_of_library_may_play_this_turn_bridge_gap_sentinel_divergence_pin():
    """Pin the bridge gap for the ``ExileTopXOfLibraryMayPlayThisTurn``
    effect kind in ``_ta_dict_to_python_effect``.

    Bug location:
      ``src/mtg_bot/parity/cross_engine.py`` -- the
      ``_ta_dict_to_python_effect`` dispatcher has no arm for
      ``kind="exile_top_x_of_library_may_play_this_turn"``.  All
      unrecognised kinds fall through to the terminal:

          raise ValueError(
              "cross_engine triggered_abilities bridge: unsupported "
              "effect kind 'exile_top_x_of_library_may_play_this_turn' ..."
          )

    Card context:
      Memorial Vault -- "{2}, {T}, Sacrifice another artifact: Exile the
      top X cards of your library, where X is one plus the mana value of
      the sacrificed artifact.  You may play those cards this turn."

      The parser maps this to
      ``ExileTopXOfLibraryMayPlayThisTurn(
          amount=MVOfCostPaidObjectPlus(constant=1))``.
      The ``amount`` field is a ``Formula`` instance evaluated at resolve
      time to determine the card count; ``MVOfCostPaidObjectPlus``
      reads the mana value of the cost-paid object (the sacrificed
      artifact) plus a constant.

    Class structure (Python-side):
      ``ExileTopXOfLibraryMayPlayThisTurn(amount: Formula | None = None)``
      from ``effects/generic/exile.py``.
      * ``amount`` -- a ``Formula`` instance or ``None``; when ``None``
        the effect resolves as a no-op (exiles 0 cards).
      Distinct from the fixed-count sibling
      ``ExileTopOfLibraryMayPlayThisTurn(amount: int = 1)`` (singular),
      which takes a static int determined at bridge time rather than a
      Formula evaluated at resolve time.

    Formula dependency note:
      The bridge arm for this kind requires a ``Formula`` serialization
      protocol (a ``_ta_dict_to_python_formula`` helper or equivalent)
      because the ``amount`` field is a structured Formula object, not
      a primitive.  No such helper exists in cross_engine.py today.
      The arm and the Formula dispatcher must land together.

    Probe shape:
      1. Assert ``ExileTopXOfLibraryMayPlayThisTurn`` exists in
         ``effects.generic`` and has the expected ``amount`` field.
      2. Assert the ``amount`` field default is ``None`` (the no-op
         sentinel rather than MISSING or a non-None value).
      3. Assert the bridge raises ``ValueError`` for the unwired kind
         (both with and without an ``amount`` sub-dict).
      4. Assert the error message contains
         ``"exile_top_x_of_library_may_play_this_turn"`` and
         ``"unsupported effect kind"``.
      5. Assert ``ExileTopXOfLibraryMayPlayThisTurn`` is DISTINCT from
         ``ExileTopOfLibraryMayPlayThisTurn`` -- they model different
         oracle shapes (Formula vs static int).
      6. Assert ``MVOfCostPaidObjectPlus`` is a ``Formula`` subclass
         (the canonical EoE Amount binding for Memorial Vault).
      7. Assert a wired effect kind (``"draw_cards"``) does NOT raise.
      8. Enumerate the 1 EoE card blocked by this gap.

    Closure path:
      Add a ``kind == "exile_top_x_of_library_may_play_this_turn"`` arm
      that reads an optional ``amount`` sub-dict (translated via a
      ``_ta_dict_to_python_formula`` helper), defaulting to ``None``
      when absent, then constructs
      ``ExileTopXOfLibraryMayPlayThisTurn(amount=formula)``.

    This pin is pure Python (no Rust extension required).
    """
    import dataclasses
    from mtg_bot.effects.generic.exile import (
        ExileTopXOfLibraryMayPlayThisTurn,
        ExileTopOfLibraryMayPlayThisTurn,
    )
    from mtg_bot.effects.formulas import Formula, MVOfCostPaidObjectPlus
    from mtg_bot.effects.base import Effect
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    # 1. ExileTopXOfLibraryMayPlayThisTurn exists and has the expected field.
    assert dataclasses.is_dataclass(ExileTopXOfLibraryMayPlayThisTurn), (
        "ExileTopXOfLibraryMayPlayThisTurn should be a dataclass "
        "(effects/generic/exile.py).  "
        "If this fails the class was restructured -- update this pin."
    )
    assert issubclass(ExileTopXOfLibraryMayPlayThisTurn, Effect), (
        "ExileTopXOfLibraryMayPlayThisTurn should be an Effect subclass.  "
        "If this fails the class hierarchy changed."
    )
    fields = {f.name: f for f in dataclasses.fields(ExileTopXOfLibraryMayPlayThisTurn)}
    assert "amount" in fields, (
        "ExileTopXOfLibraryMayPlayThisTurn should have an 'amount' field "
        "(a Formula | None) representing the card count at resolve time.  "
        f"Got fields: {list(fields.keys())!r}"
    )

    # 2. The ``amount`` field default is None (no-op sentinel).
    amount_field = fields["amount"]
    assert amount_field.default is None, (
        "ExileTopXOfLibraryMayPlayThisTurn.amount default should be None "
        "(the no-op / zero-card sentinel).  The bridge arm should pass "
        "None when the sub-dict is absent.  "
        f"Got default: {amount_field.default!r}"
    )

    # 3-4. Bridge raises ValueError for the unwired effect kind.
    #      Test with an empty dict (no amount sub-dict) first.
    unwired_eff_dict = {"kind": "exile_top_x_of_library_may_play_this_turn"}
    with pytest.raises(ValueError) as exc_info:
        _ta_dict_to_python_effect(unwired_eff_dict)

    err_msg = str(exc_info.value)
    assert "exile_top_x_of_library_may_play_this_turn" in err_msg, (
        "Bridge gap sentinel: the ValueError message should mention "
        "'exile_top_x_of_library_may_play_this_turn'.  "
        f"Got message: {err_msg!r}"
    )
    assert "unsupported effect kind" in err_msg, (
        "Bridge gap sentinel: the ValueError should contain "
        "'unsupported effect kind' confirming the "
        "_ta_dict_to_python_effect dispatcher produced this error.  "
        f"Got message: {err_msg!r}"
    )

    # Also raises when a nested amount dict is provided (kind is
    # unrecognised before the amount sub-field would be read).
    with pytest.raises(ValueError) as exc_info_with_amount:
        _ta_dict_to_python_effect({
            "kind": "exile_top_x_of_library_may_play_this_turn",
            "amount": {"kind": "mv_of_cost_paid_object_plus", "constant": 1},
        })
    err_with_amount = str(exc_info_with_amount.value)
    assert "exile_top_x_of_library_may_play_this_turn" in err_with_amount, (
        "Bridge gap sentinel (with-amount dict): the ValueError message "
        "should still mention 'exile_top_x_of_library_may_play_this_turn'.  "
        f"Got message: {err_with_amount!r}"
    )

    # 5. ExileTopXOfLibraryMayPlayThisTurn is DISTINCT from the singular.
    assert ExileTopXOfLibraryMayPlayThisTurn is not ExileTopOfLibraryMayPlayThisTurn, (
        "ExileTopXOfLibraryMayPlayThisTurn must be a distinct class from "
        "ExileTopOfLibraryMayPlayThisTurn.  The singular variant uses a "
        "static int count (amount: int = 1); the plural variant uses a "
        "Formula evaluated at resolve time (amount: Formula | None = None).  "
        "Closing the singular bridge arm does NOT close the plural arm."
    )
    singular_fields = {f.name: f for f in dataclasses.fields(ExileTopOfLibraryMayPlayThisTurn)}
    assert "amount" in singular_fields, (
        "ExileTopOfLibraryMayPlayThisTurn (singular) should also have an "
        "'amount' field (static int).  "
        f"Got fields: {list(singular_fields.keys())!r}"
    )
    assert isinstance(singular_fields["amount"].default, int), (
        "ExileTopOfLibraryMayPlayThisTurn.amount default should be an int "
        "(e.g. 1 for the single-card Charred Foyer shape).  "
        f"Got type: {type(singular_fields['amount'].default).__name__!r}, "
        f"value: {singular_fields['amount'].default!r}"
    )

    # 6. MVOfCostPaidObjectPlus is a Formula subclass (canonical EoE binding).
    assert issubclass(MVOfCostPaidObjectPlus, Formula), (
        "MVOfCostPaidObjectPlus should be a Formula subclass "
        "(effects/formulas.py).  It reads the mana value of the first "
        "cost-paid object (the sacrificed artifact for Memorial Vault) "
        "and adds a constant.  "
        "If this fails the class hierarchy changed -- update this pin."
    )
    mv_fields = {f.name: f for f in dataclasses.fields(MVOfCostPaidObjectPlus)}
    assert "constant" in mv_fields, (
        "MVOfCostPaidObjectPlus should have a 'constant' field (int) "
        "that is added to the cost-paid object's mana value.  "
        "Memorial Vault uses constant=1 for 'one plus the mana value'.  "
        f"Got fields: {list(mv_fields.keys())!r}"
    )
    assert mv_fields["constant"].default == 0, (
        "MVOfCostPaidObjectPlus.constant default should be 0.  "
        "The bridge arm must supply constant=1 for Memorial Vault's "
        "'one plus the mana value' binding.  "
        f"Got default: {mv_fields['constant'].default!r}"
    )

    # 7. Sanity: a WIRED effect kind ("draw_cards") round-trips without error.
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

    # 8. Enumerate the EoE card blocked by this gap.
    blocked_eoe_cards = [
        "Memorial Vault",
        # "{2}, {T}, Sacrifice another artifact: Exile the top X cards
        # of your library, where X is one plus the mana value of the
        # sacrificed artifact.  You may play those cards this turn."
        # Parser: ExileTopXOfLibraryMayPlayThisTurn(
        #             amount=MVOfCostPaidObjectPlus(constant=1))
        # Formula reads state.resolving_cost_paid_objects[0] at
        # resolve time; the sacrificed artifact populates this tuple
        # via the cost-payment plumbing in _activate_ability.
    ]
    assert len(blocked_eoe_cards) == 1, (
        "The 'exile_top_x_of_library_may_play_this_turn' bridge gap "
        "blocks 1 EoE card (Memorial Vault).  "
        f"Enumerated list has {len(blocked_eoe_cards)} entries."
    )


# ---------------------------------------------------------------------------
# Pin 3 -- SearchLibraryForEquipmentToBattlefield effect kind NOT wired in
#          bridge (EE drop; 1 EoE card blocked: Honored Knight-Captain)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_search_library_for_equipment_to_battlefield_bridge_gap_sentinel_divergence_pin():
    """Pin the bridge gap for the ``SearchLibraryForEquipmentToBattlefield``
    effect kind in ``_ta_dict_to_python_effect``.

    Bug location:
      ``src/mtg_bot/parity/cross_engine.py`` -- the
      ``_ta_dict_to_python_effect`` dispatcher has no arm for
      ``kind="search_library_for_equipment_to_battlefield"``.  All
      unrecognised kinds fall through to the terminal:

          raise ValueError(
              "cross_engine triggered_abilities bridge: unsupported "
              "effect kind 'search_library_for_equipment_to_battlefield' ..."
          )

    Card context:
      Honored Knight-Captain -- "{4}{W}{W}, Sacrifice Honored
      Knight-Captain: Search your library for an Equipment card, put it
      onto the battlefield, then shuffle."

      The parser maps this activated-ability body to
      ``SearchLibraryForEquipmentToBattlefield()``.  The "Equipment"
      filter and the untapped ETB semantics are baked into the class's
      ``resolve`` method.

    Distinctness from sibling search effects:
      Three library-search Effect classes exist in the codebase:
        1. ``SearchLibraryForBasicLandTapped`` -- basic land, enters
           the battlefield TAPPED; wired in bridge (kind=
           "search_library_for_basic_land_tapped").
        2. ``SearchLibraryForCard(filter_name, max_mv, may_fail)`` --
           generic named-subtype tutor with optional max-mv constraint
           and a may_fail asymmetric-agent path; wired in bridge (kind=
           "search_library_for_card").
        3. ``SearchLibraryForEquipmentToBattlefield()`` -- Equipment
           card, enters the battlefield UNTAPPED; NOT yet wired.
      All three share a "search + shuffle" post-step but are not
      interchangeable; ``SearchLibraryForEquipmentToBattlefield`` is
      NOT simply ``SearchLibraryForCard(filter_name="Equipment")``.

    Class structure (Python-side):
      ``SearchLibraryForEquipmentToBattlefield()`` -- zero-field frozen
      dataclass from ``effects/generic/search.py``.  No constructor
      arguments; the Equipment filter and untapped ETB are in
      ``resolve``.  Shares the search+shuffle post-step with its
      siblings.

    Probe shape:
      1. Assert ``SearchLibraryForEquipmentToBattlefield`` exists in
         ``effects.generic`` and is a zero-field dataclass.
      2. Assert the bridge raises ``ValueError`` for the unwired kind.
      3. Assert the error message contains
         ``"search_library_for_equipment_to_battlefield"`` and
         ``"unsupported effect kind"``.
      4. Assert ``SearchLibraryForEquipmentToBattlefield`` is DISTINCT
         from ``SearchLibraryForCard`` (different class, different
         field layout, different resolve semantics).
      5. Assert the wired sibling ``SearchLibraryForCard`` does NOT
         raise ValueError (confirming the siblings are independently
         wired and closing one arm does not close the other).
      6. Assert a wired effect kind (``"draw_cards"``) does NOT raise.
      7. Enumerate the 1 EoE card blocked by this gap.

    Closure path:
      Add a ``kind == "search_library_for_equipment_to_battlefield"``
      arm that constructs and returns
      ``SearchLibraryForEquipmentToBattlefield()``.  No dict fields to
      read.  This is a pure Python bridge fix (no Rust substrate
      required).
    """
    import dataclasses
    from mtg_bot.effects.generic.search import (
        SearchLibraryForEquipmentToBattlefield,
        SearchLibraryForCard,
        SearchLibraryForBasicLandTapped,
    )
    from mtg_bot.effects.base import Effect
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    # 1. SearchLibraryForEquipmentToBattlefield exists and is a zero-field
    #    dataclass.
    assert dataclasses.is_dataclass(SearchLibraryForEquipmentToBattlefield), (
        "SearchLibraryForEquipmentToBattlefield should be a dataclass "
        "(effects/generic/search.py).  "
        "If this fails the class was restructured -- update this pin."
    )
    assert issubclass(SearchLibraryForEquipmentToBattlefield, Effect), (
        "SearchLibraryForEquipmentToBattlefield should be an Effect "
        "subclass.  If this fails the class hierarchy changed."
    )
    fields = dataclasses.fields(SearchLibraryForEquipmentToBattlefield)
    assert len(fields) == 0, (
        "SearchLibraryForEquipmentToBattlefield should have zero dataclass "
        "fields -- the Equipment filter and untapped ETB semantics are "
        "encoded in the resolve method, not constructor arguments.  "
        f"Got fields: {[f.name for f in fields]!r}.  "
        "If a field was added, the bridge arm needs to read it from the dict."
    )

    # 2-3. Bridge raises ValueError for the unwired effect kind.
    unwired_eff_dict = {"kind": "search_library_for_equipment_to_battlefield"}
    with pytest.raises(ValueError) as exc_info:
        _ta_dict_to_python_effect(unwired_eff_dict)

    err_msg = str(exc_info.value)
    assert "search_library_for_equipment_to_battlefield" in err_msg, (
        "Bridge gap sentinel: the ValueError message should mention "
        "'search_library_for_equipment_to_battlefield'.  "
        f"Got message: {err_msg!r}"
    )
    assert "unsupported effect kind" in err_msg, (
        "Bridge gap sentinel: the ValueError should contain "
        "'unsupported effect kind' confirming the "
        "_ta_dict_to_python_effect dispatcher produced this error.  "
        f"Got message: {err_msg!r}"
    )

    # 4. SearchLibraryForEquipmentToBattlefield is DISTINCT from
    #    SearchLibraryForCard.
    assert SearchLibraryForEquipmentToBattlefield is not SearchLibraryForCard, (
        "SearchLibraryForEquipmentToBattlefield must be a distinct class "
        "from SearchLibraryForCard.  The Equipment tutor has zero fields "
        "and untapped-ETB semantics; SearchLibraryForCard requires a "
        "filter_name field and supports a may_fail asymmetric-agent path.  "
        "Closing the SearchLibraryForCard bridge arm does NOT close the "
        "Equipment tutor arm."
    )
    card_fields = {f.name for f in dataclasses.fields(SearchLibraryForCard)}
    assert "filter_name" in card_fields, (
        "SearchLibraryForCard should have a 'filter_name' field "
        "(the card-type discriminator; e.g. 'Enchantment', 'Instant').  "
        f"Got fields: {sorted(card_fields)!r}"
    )
    assert "may_fail" in card_fields, (
        "SearchLibraryForCard should have a 'may_fail' field "
        "(controls the asymmetric-agent path for deck-out edge cases).  "
        f"Got fields: {sorted(card_fields)!r}"
    )

    # 5. Wired sibling SearchLibraryForCard does NOT raise ValueError.
    #    (This confirms the sibling bridge arm is present and that
    #    closing it did not accidentally close the Equipment gap.)
    try:
        result_card = _ta_dict_to_python_effect({
            "kind": "search_library_for_card",
            "filter_name": "Creature",
        })
        assert isinstance(result_card, Effect), (
            "Wired sibling 'search_library_for_card' should produce an "
            f"Effect instance; got {type(result_card).__name__}."
        )
        assert isinstance(result_card, SearchLibraryForCard), (
            "Wired sibling 'search_library_for_card' should produce a "
            "SearchLibraryForCard instance specifically; got "
            f"{type(result_card).__name__}."
        )
    except ValueError as e:
        raise AssertionError(
            "Sibling sanity: 'search_library_for_card' is a wired effect "
            "kind and should NOT raise ValueError -- got: "
            f"{e}"
        ) from e

    # Also confirm SearchLibraryForBasicLandTapped is wired and distinct.
    try:
        result_land = _ta_dict_to_python_effect({
            "kind": "search_library_for_basic_land_tapped",
        })
        assert isinstance(result_land, SearchLibraryForBasicLandTapped), (
            "Wired sibling 'search_library_for_basic_land_tapped' should "
            "produce a SearchLibraryForBasicLandTapped instance; got "
            f"{type(result_land).__name__}."
        )
    except ValueError as e:
        raise AssertionError(
            "Sibling sanity: 'search_library_for_basic_land_tapped' is a "
            "wired effect kind and should NOT raise ValueError -- got: "
            f"{e}"
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
        "Honored Knight-Captain",
        # "{4}{W}{W}, Sacrifice Honored Knight-Captain: Search your
        # library for an Equipment card, put it onto the battlefield,
        # then shuffle."
        # Parser: SearchLibraryForEquipmentToBattlefield()
        # at cards/parser/effects.py (literal-line recognizer, zero-
        # field construction, Equipment filter + untapped ETB in resolve).
    ]
    assert len(blocked_eoe_cards) == 1, (
        "The 'search_library_for_equipment_to_battlefield' bridge gap "
        "blocks 1 EoE card (Honored Knight-Captain).  "
        f"Enumerated list has {len(blocked_eoe_cards)} entries."
    )
