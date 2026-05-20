"""Divergence-pin tests: batch DDD (probe-batch-ddd, round 17).

**Slice 17 closure status:** Pins 1, 2, and 3 are ALL CLOSED -- the
three bridge arms (``survey_mechan_activation_effect``,
``search_library_for_equipment_to_battlefield``,
``exile_top_x_of_library_may_play_this_turn``) now land in
``_ta_dict_to_python_effect`` (``src/mtg_bot/parity/cross_engine.py``).
Pin 2's closure introduced a new ``_ta_dict_to_python_formula``
dispatcher (first Formula bridge dispatcher in cross_engine.py;
currently handles ``mv_of_cost_paid_object_plus`` + ``constant``).
All 3 tests have been renamed to ``*_FIXED_parity`` with the
assertions inverted -- they now verify the wired behavior rather than
pin the absent-arm divergence.

3 EoE cards unblocked by this slice: Survey Mechan (Pin 1), Memorial
Vault (Pin 2), Honored Knight-Captain (Pin 3).

Each test originally named ``test_..._divergence_pin`` ASSERTED the
CURRENT divergent behavior rather than parity. The PROBED-tier
detector excludes ``*_divergence_pin`` functions, so these tests grow
the test surface without touching the PROBED metric. Closed pins
renamed to ``*_FIXED_parity`` are regular parity tests and DO count
in the PROBED metric.

Pin closure cadence: when a sibling Rust slice closes the underlying
gap, the relevant assertion fires and the pin is renamed
``*_FIXED_parity`` with the sentinel inverted (PPP / MMM / JJJ / RRR
Pin 1 / TTT Pin 1 + 2 + 3 / AAA Pin 1 + 2 precedent).

Pinned bugs (now CLOSED)
------------------------

Pin 1 -- ``SurveyMechanActivationEffect`` effect kind NOT wired in the
cross-engine effect bridge (CLOSED; bridge arm added in slice 17).

    Python's ``SurveyMechanActivationEffect`` class
    (``effects/bespoke.py``) is a bespoke zero-field dataclass that
    encodes Survey Mechan's activated ability body: "It deals 3 damage
    to any target.  Target player draws three cards and gains 3 life."

    Closure: a ``kind == "survey_mechan_activation_effect"`` arm in
    ``_ta_dict_to_python_effect`` constructs and returns
    ``SurveyMechanActivationEffect()`` with no sub-fields to read from
    the dict (zero-field unit-variant convention; mirrors AAA Pin 1
    DyadrineAttackEffect bridge arm). 1 EoE card unblocked: Survey
    Mechan.

Pin 2 -- ``ExileTopXOfLibraryMayPlayThisTurn`` effect kind NOT wired
in the cross-engine effect bridge (CLOSED; bridge arm + new
``_ta_dict_to_python_formula`` dispatcher added in slice 17).

    Python's ``ExileTopXOfLibraryMayPlayThisTurn`` class
    (``effects/generic/exile.py``) is a frozen dataclass with a single
    ``amount: Formula | None`` field that encodes the "exile the top X
    cards of your library, where X is <formula>; you may play those
    cards this turn" oracle shape.

    Closure pieces:
      * New ``_ta_dict_to_python_formula`` helper in cross_engine.py
        -- first Formula dispatcher in the bridge module; currently
        dispatches ``mv_of_cost_paid_object_plus`` (Memorial Vault's
        ``MVOfCostPaidObjectPlus(constant=N)`` binding) and ``constant``
        (the static fallback).
      * New ``kind == "exile_top_x_of_library_may_play_this_turn"`` arm
        in ``_ta_dict_to_python_effect`` that reads an optional
        ``amount`` sub-dict via the Formula helper, defaulting to
        ``None`` (the no-op / zero-card sentinel) when absent, then
        constructs ``ExileTopXOfLibraryMayPlayThisTurn(amount=formula)``.

    1 EoE card unblocked: Memorial Vault.

Pin 3 -- ``SearchLibraryForEquipmentToBattlefield`` effect kind NOT
wired in the cross-engine effect bridge (CLOSED; bridge arm added in
slice 17).

    Python's ``SearchLibraryForEquipmentToBattlefield`` class
    (``effects/generic/search.py``) is a frozen zero-field dataclass
    that encodes the "search your library for an Equipment card, put
    it onto the battlefield, then shuffle" oracle shape.

    Closure: a ``kind == "search_library_for_equipment_to_battlefield"``
    arm constructs and returns ``SearchLibraryForEquipmentToBattlefield()``
    with no sub-fields to read (zero-field unit-variant convention).
    Distinct from the wired sibling ``SearchLibraryForCard`` (which
    needs ``filter_name`` / ``max_mv`` / ``may_fail`` and supports a
    may_fail asymmetric-agent path) and ``SearchLibraryForBasicLandTapped``
    (which uses a ``count`` field). 1 EoE card unblocked: Honored
    Knight-Captain.

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
# Pin 1 -- SurveyMechanActivationEffect bridge arm wired (CLOSED).
#          (EE drop; 1 EoE card unblocked: Survey Mechan)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_survey_mechan_activation_effect_bridge_gap_sentinel_FIXED_parity():
    """**17th Rust slice (DDD Pin 1 closure)** -- bridge arm for
    ``SurveyMechanActivationEffect`` is now wired.

    Pre-closure (the divergence DDD Pin 1 locked in): the bridge had no
    arm for ``kind="survey_mechan_activation_effect"`` and fell through
    to the terminal ``ValueError("unsupported effect kind ...")``.

    Post-closure (asserted here): a ``kind ==
    "survey_mechan_activation_effect"`` arm in
    ``_ta_dict_to_python_effect`` constructs and returns
    ``SurveyMechanActivationEffect()`` with no sub-fields to read
    (zero-field unit-variant convention).

    Card context:
      Survey Mechan -- "{2}{U}{R}: It deals 3 damage to any target.
      Target player draws three cards and gains 3 life."

      The parser uses the bespoke ``SurveyMechanActivationEffect()``
      dataclass (``effects/bespoke.py``) for this activated-ability
      body.  The class is a zero-field dataclass -- all resolution
      logic lives in its ``resolve`` method; the two targeting slots
      (any_damage_target, player) are enforced by the activation
      machinery.

    Probe shape:
      1. Assert ``SurveyMechanActivationEffect`` exists in
         ``effects.bespoke`` and is a zero-field dataclass.
      2. Assert the bridge NO LONGER raises ``ValueError`` for the kind
         (the closure inversion).
      3. Assert the bridge returns a ``SurveyMechanActivationEffect``
         instance.
      4. Assert a wired effect kind (``"draw_cards"``) does NOT raise
         (sanity regression guard).
      5. Enumerate the 1 EoE card unblocked by this fix.

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
        "-- update this FIXED_parity test and the bridge arm."
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

    # 2-3. **Closure inversion** -- bridge NO LONGER raises ValueError,
    #      returns a SurveyMechanActivationEffect instance.
    wired_eff_dict = {"kind": "survey_mechan_activation_effect"}
    result = _ta_dict_to_python_effect(wired_eff_dict)
    assert isinstance(result, SurveyMechanActivationEffect), (
        "Bridge arm for 'survey_mechan_activation_effect' should return "
        "a SurveyMechanActivationEffect instance (DDD Pin 1 closure).  "
        f"Got {type(result).__name__!r}."
    )
    assert isinstance(result, Effect), (
        "Returned object should satisfy the Effect type contract.  "
        f"Got {type(result).__name__!r}."
    )

    # 4. Sanity: a WIRED effect kind ("draw_cards") still round-trips.
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

    # 5. Enumerate the EoE cards unblocked by this fix.
    unblocked_eoe_cards = [
        "Survey Mechan",
        # "{2}{U}{R}: It deals 3 damage to any target.  Target player
        # draws three cards and gains 3 life."
        # Parser: SurveyMechanActivationEffect() via effects.py bespoke
        # branch at cards/parser/effects.py.
    ]
    assert len(unblocked_eoe_cards) == 1, (
        "The 'survey_mechan_activation_effect' bridge arm unblocks 1 EoE "
        "card (Survey Mechan).  "
        f"Enumerated list has {len(unblocked_eoe_cards)} entries."
    )


# ---------------------------------------------------------------------------
# Pin 2 -- ExileTopXOfLibraryMayPlayThisTurn bridge arm wired (CLOSED).
#          (EE drop; 1 EoE card unblocked: Memorial Vault)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_exile_top_x_of_library_may_play_this_turn_bridge_gap_sentinel_FIXED_parity():
    """**17th Rust slice (DDD Pin 2 closure)** -- bridge arm for
    ``ExileTopXOfLibraryMayPlayThisTurn`` is now wired, alongside a
    new ``_ta_dict_to_python_formula`` dispatcher.

    Pre-closure (the divergence DDD Pin 2 locked in): the bridge had no
    arm for ``kind="exile_top_x_of_library_may_play_this_turn"`` AND no
    Formula serialization protocol -- the Formula-driven ``amount`` field
    could not round-trip from a dict.

    Post-closure (asserted here):
      * A new ``_ta_dict_to_python_formula(formula_dict)`` helper
        dispatches Formula sub-dicts; currently handles
        ``mv_of_cost_paid_object_plus`` (Memorial Vault's
        ``MVOfCostPaidObjectPlus(constant=N)``) and ``constant``
        (the static fallback).
      * A new ``kind == "exile_top_x_of_library_may_play_this_turn"``
        arm in ``_ta_dict_to_python_effect`` reads an optional ``amount``
        sub-dict via the Formula helper, defaulting to ``None`` (the
        no-op / zero-card sentinel) when absent.

    Card context:
      Memorial Vault -- "{2}, {T}, Sacrifice another artifact: Exile
      the top X cards of your library, where X is one plus the mana
      value of the sacrificed artifact.  You may play those cards this
      turn."

      The parser maps this to
      ``ExileTopXOfLibraryMayPlayThisTurn(
          amount=MVOfCostPaidObjectPlus(constant=1))``.  The ``amount``
      field is a ``Formula`` instance evaluated at resolve time to
      determine the card count; ``MVOfCostPaidObjectPlus`` reads the
      mana value of the cost-paid object (the sacrificed artifact) plus
      a constant.

    Class structure (Python-side):
      ``ExileTopXOfLibraryMayPlayThisTurn(amount: Formula | None = None)``
      from ``effects/generic/exile.py``.  Distinct from the fixed-count
      sibling ``ExileTopOfLibraryMayPlayThisTurn(amount: int = 1)``
      (singular), which takes a static int rather than a Formula.

    Probe shape:
      1. Assert ``ExileTopXOfLibraryMayPlayThisTurn`` exists in
         ``effects.generic`` and has the expected ``amount`` field with
         default ``None``.
      2. Assert ``ExileTopXOfLibraryMayPlayThisTurn`` is DISTINCT from
         ``ExileTopOfLibraryMayPlayThisTurn``.
      3. Assert ``MVOfCostPaidObjectPlus`` is a Formula subclass.
      4. Assert the bridge NO LONGER raises for the kind (closure
         inversion); the no-amount call returns
         ``ExileTopXOfLibraryMayPlayThisTurn(amount=None)``.
      5. Assert the bridge round-trips Memorial Vault's
         ``amount=MVOfCostPaidObjectPlus(constant=1)`` shape.
      6. Assert the Formula dispatcher round-trips ``Constant(amount=N)``.
      7. Assert the Formula dispatcher raises on an unknown formula
         kind (surfacing future extension needs cleanly).
      8. Assert a wired effect kind (``"draw_cards"``) does NOT raise.
      9. Enumerate the 1 EoE card unblocked.

    This pin is pure Python (no Rust extension required for the bridge
    gap itself).
    """
    import dataclasses
    from mtg_bot.effects.generic.exile import (
        ExileTopXOfLibraryMayPlayThisTurn,
        ExileTopOfLibraryMayPlayThisTurn,
    )
    from mtg_bot.effects.formulas import (
        Formula, MVOfCostPaidObjectPlus, Constant,
    )
    from mtg_bot.effects.base import Effect
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_effect,
        _ta_dict_to_python_formula,
    )

    # 1. ExileTopXOfLibraryMayPlayThisTurn exists and has the expected field.
    assert dataclasses.is_dataclass(ExileTopXOfLibraryMayPlayThisTurn), (
        "ExileTopXOfLibraryMayPlayThisTurn should be a dataclass "
        "(effects/generic/exile.py).  "
        "If this fails the class was restructured -- update this test."
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
    amount_field = fields["amount"]
    assert amount_field.default is None, (
        "ExileTopXOfLibraryMayPlayThisTurn.amount default should be None "
        "(the no-op / zero-card sentinel).  The bridge arm should pass "
        "None when the sub-dict is absent.  "
        f"Got default: {amount_field.default!r}"
    )

    # 2. ExileTopXOfLibraryMayPlayThisTurn is DISTINCT from the singular.
    assert ExileTopXOfLibraryMayPlayThisTurn is not ExileTopOfLibraryMayPlayThisTurn, (
        "ExileTopXOfLibraryMayPlayThisTurn must be a distinct class from "
        "ExileTopOfLibraryMayPlayThisTurn.  The singular variant uses a "
        "static int count (amount: int = 1); the plural variant uses a "
        "Formula evaluated at resolve time (amount: Formula | None = None)."
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

    # 3. MVOfCostPaidObjectPlus is a Formula subclass (canonical EoE binding).
    assert issubclass(MVOfCostPaidObjectPlus, Formula), (
        "MVOfCostPaidObjectPlus should be a Formula subclass "
        "(effects/formulas.py).  It reads the mana value of the first "
        "cost-paid object (the sacrificed artifact for Memorial Vault) "
        "and adds a constant."
    )
    mv_fields = {f.name: f for f in dataclasses.fields(MVOfCostPaidObjectPlus)}
    assert "constant" in mv_fields, (
        "MVOfCostPaidObjectPlus should have a 'constant' field (int).  "
        f"Got fields: {list(mv_fields.keys())!r}"
    )
    assert mv_fields["constant"].default == 0, (
        "MVOfCostPaidObjectPlus.constant default should be 0.  "
        f"Got default: {mv_fields['constant'].default!r}"
    )

    # 4. **Closure inversion** -- bridge NO LONGER raises ValueError.
    #    The no-amount call returns amount=None (the no-op sentinel).
    no_amount_eff_dict = {"kind": "exile_top_x_of_library_may_play_this_turn"}
    no_amount_result = _ta_dict_to_python_effect(no_amount_eff_dict)
    assert isinstance(no_amount_result, ExileTopXOfLibraryMayPlayThisTurn), (
        "Bridge arm should return an ExileTopXOfLibraryMayPlayThisTurn "
        "instance (DDD Pin 2 closure).  "
        f"Got {type(no_amount_result).__name__!r}."
    )
    assert no_amount_result.amount is None, (
        "Bridge arm should pass amount=None when the sub-dict is absent "
        "(the no-op / zero-card sentinel).  "
        f"Got amount={no_amount_result.amount!r}."
    )

    # 5. Memorial Vault binding round-trips through the bridge.
    mv_eff_dict = {
        "kind": "exile_top_x_of_library_may_play_this_turn",
        "amount": {"kind": "mv_of_cost_paid_object_plus", "constant": 1},
    }
    mv_result = _ta_dict_to_python_effect(mv_eff_dict)
    assert isinstance(mv_result, ExileTopXOfLibraryMayPlayThisTurn), (
        f"Memorial Vault bridge round-trip should return "
        f"ExileTopXOfLibraryMayPlayThisTurn; got {type(mv_result).__name__!r}."
    )
    assert isinstance(mv_result.amount, MVOfCostPaidObjectPlus), (
        "Memorial Vault binding should produce an MVOfCostPaidObjectPlus "
        "amount; got "
        f"{type(mv_result.amount).__name__!r}."
    )
    assert mv_result.amount.constant == 1, (
        "Memorial Vault's binding should carry constant=1 (the 'one plus "
        "the mana value of the sacrificed artifact' offset).  "
        f"Got constant={mv_result.amount.constant!r}."
    )

    # 6. Formula dispatcher round-trips Constant(amount=N) (static fallback).
    const_formula = _ta_dict_to_python_formula({"kind": "constant", "amount": 4})
    assert isinstance(const_formula, Constant), (
        "Formula dispatcher should return a Constant instance for "
        f"kind='constant'; got {type(const_formula).__name__!r}."
    )
    assert const_formula.amount == 4, (
        f"Constant(amount=4) round-trip; got amount={const_formula.amount!r}."
    )

    # 7. Formula dispatcher raises on an unknown formula kind.
    with pytest.raises(ValueError) as exc_info_formula:
        _ta_dict_to_python_formula({"kind": "unknown_formula_kind"})
    err_formula = str(exc_info_formula.value)
    assert "unknown_formula_kind" in err_formula, (
        "Formula dispatcher's terminal error should name the unknown "
        f"kind for clear surfacing.  Got message: {err_formula!r}"
    )
    assert "unsupported" in err_formula, (
        "Formula dispatcher's terminal error should contain 'unsupported' "
        "(matching the parent dispatcher's terminal-arm shape).  "
        f"Got message: {err_formula!r}"
    )

    # 8. Sanity: a WIRED effect kind ("draw_cards") still round-trips.
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

    # 9. Enumerate the EoE card unblocked.
    unblocked_eoe_cards = [
        "Memorial Vault",
        # "{2}, {T}, Sacrifice another artifact: Exile the top X cards
        # of your library, where X is one plus the mana value of the
        # sacrificed artifact.  You may play those cards this turn."
        # Parser: ExileTopXOfLibraryMayPlayThisTurn(
        #             amount=MVOfCostPaidObjectPlus(constant=1))
    ]
    assert len(unblocked_eoe_cards) == 1, (
        "The 'exile_top_x_of_library_may_play_this_turn' bridge arm "
        "unblocks 1 EoE card (Memorial Vault).  "
        f"Enumerated list has {len(unblocked_eoe_cards)} entries."
    )


# ---------------------------------------------------------------------------
# Pin 3 -- SearchLibraryForEquipmentToBattlefield bridge arm wired (CLOSED).
#          (EE drop; 1 EoE card unblocked: Honored Knight-Captain)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_search_library_for_equipment_to_battlefield_bridge_gap_sentinel_FIXED_parity():
    """**17th Rust slice (DDD Pin 3 closure)** -- bridge arm for
    ``SearchLibraryForEquipmentToBattlefield`` is now wired.

    Pre-closure (the divergence DDD Pin 3 locked in): the bridge had no
    arm for ``kind="search_library_for_equipment_to_battlefield"`` and
    fell through to the terminal ``ValueError("unsupported effect kind
    ...")``.

    Post-closure (asserted here): a ``kind ==
    "search_library_for_equipment_to_battlefield"`` arm in
    ``_ta_dict_to_python_effect`` constructs and returns
    ``SearchLibraryForEquipmentToBattlefield()`` (zero-field).

    Card context:
      Honored Knight-Captain -- "{4}{W}{W}, Sacrifice Honored
      Knight-Captain: Search your library for an Equipment card, put it
      onto the battlefield, then shuffle."

      The parser maps this activated-ability body to
      ``SearchLibraryForEquipmentToBattlefield()``.  The "Equipment"
      filter and the untapped ETB semantics are baked into the class's
      ``resolve`` method.

    Distinctness from sibling search effects (preserved):
      Three library-search Effect classes coexist in the codebase:
        1. ``SearchLibraryForBasicLandTapped`` -- basic land, tapped
           ETB; wired in bridge (kind=
           "search_library_for_basic_land_tapped").
        2. ``SearchLibraryForCard(filter_name, max_mv, may_fail)`` --
           generic named-subtype tutor with optional max-mv constraint
           and may_fail asymmetric-agent path; wired in bridge (kind=
           "search_library_for_card").
        3. ``SearchLibraryForEquipmentToBattlefield()`` -- Equipment
           card, UNTAPPED ETB; NOW wired in bridge (this slice).
      All three share a "search + shuffle" post-step but are not
      interchangeable.  Closing one arm does NOT close the others.

    Probe shape:
      1. Assert ``SearchLibraryForEquipmentToBattlefield`` exists in
         ``effects.generic`` and is a zero-field dataclass.
      2. Assert the bridge NO LONGER raises ``ValueError`` for the kind
         (closure inversion).
      3. Assert the bridge returns a
         ``SearchLibraryForEquipmentToBattlefield`` instance.
      4. Assert distinctness from ``SearchLibraryForCard`` is preserved
         (different class, different field layout).
      5. Assert the sibling ``SearchLibraryForCard`` arm is still wired
         (regression guard -- closing one arm did not break the others).
      6. Assert a wired effect kind (``"draw_cards"``) does NOT raise.
      7. Enumerate the 1 EoE card unblocked.

    This pin is pure Python (no Rust extension required).
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
        "If this fails the class was restructured -- update this test."
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

    # 2-3. **Closure inversion** -- bridge NO LONGER raises ValueError,
    #      returns a SearchLibraryForEquipmentToBattlefield instance.
    wired_eff_dict = {"kind": "search_library_for_equipment_to_battlefield"}
    result = _ta_dict_to_python_effect(wired_eff_dict)
    assert isinstance(result, SearchLibraryForEquipmentToBattlefield), (
        "Bridge arm for 'search_library_for_equipment_to_battlefield' "
        "should return a SearchLibraryForEquipmentToBattlefield instance "
        "(DDD Pin 3 closure).  "
        f"Got {type(result).__name__!r}."
    )
    assert isinstance(result, Effect), (
        "Returned object should satisfy the Effect type contract.  "
        f"Got {type(result).__name__!r}."
    )

    # 4. SearchLibraryForEquipmentToBattlefield is DISTINCT from
    #    SearchLibraryForCard (preserved invariant).
    assert SearchLibraryForEquipmentToBattlefield is not SearchLibraryForCard, (
        "SearchLibraryForEquipmentToBattlefield must remain a distinct "
        "class from SearchLibraryForCard.  The Equipment tutor has zero "
        "fields and untapped-ETB semantics; SearchLibraryForCard requires "
        "a filter_name field and supports a may_fail asymmetric-agent "
        "path.  Closing one arm did NOT collapse them."
    )
    card_fields = {f.name for f in dataclasses.fields(SearchLibraryForCard)}
    assert "filter_name" in card_fields, (
        "SearchLibraryForCard should have a 'filter_name' field "
        "(the card-type discriminator; e.g. 'Equipment', 'Instant').  "
        f"Got fields: {sorted(card_fields)!r}"
    )
    assert "may_fail" in card_fields, (
        "SearchLibraryForCard should have a 'may_fail' field "
        "(controls the asymmetric-agent path for deck-out edge cases).  "
        f"Got fields: {sorted(card_fields)!r}"
    )

    # 5. Sibling arms are still wired (regression guard).
    try:
        result_card = _ta_dict_to_python_effect({
            "kind": "search_library_for_card",
            "filter_name": "Creature",
        })
        assert isinstance(result_card, SearchLibraryForCard), (
            "Wired sibling 'search_library_for_card' should produce a "
            f"SearchLibraryForCard instance; got {type(result_card).__name__}."
        )
    except ValueError as e:
        raise AssertionError(
            "Sibling sanity: 'search_library_for_card' is a wired effect "
            "kind and should NOT raise ValueError -- got: "
            f"{e}"
        ) from e

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

    # 6. Sanity: a WIRED effect kind ("draw_cards") still round-trips.
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

    # 7. Enumerate the EoE card unblocked.
    unblocked_eoe_cards = [
        "Honored Knight-Captain",
        # "{4}{W}{W}, Sacrifice Honored Knight-Captain: Search your
        # library for an Equipment card, put it onto the battlefield,
        # then shuffle."
        # Parser: SearchLibraryForEquipmentToBattlefield()
        # at cards/parser/effects.py (literal-line recognizer, zero-
        # field construction, Equipment filter + untapped ETB in resolve).
    ]
    assert len(unblocked_eoe_cards) == 1, (
        "The 'search_library_for_equipment_to_battlefield' bridge arm "
        "unblocks 1 EoE card (Honored Knight-Captain).  "
        f"Enumerated list has {len(unblocked_eoe_cards)} entries."
    )
