"""Unit tests for ``mtg_bot.effects.formulas``.

Pin the runtime-amount grammar in isolation. The integration paths
(Memorial Vault using ``MVOfCostPaidObjectPlus`` end-to-end, etc.)
already exercise the happy path. These tests cover the defensive
branches and the rest of the public surface.
"""

from __future__ import annotations

from mtg_bot.effects.formulas import (
    Constant,
    CountControlledMatching,
    MVOfCostPaidObjectPlus,
)


class _StubState:
    """Minimal state stand-in for formulas that consult cost-paid
    objects or battlefield. The grammar only touches the attributes
    referenced below; nothing else needs to exist."""

    def __init__(self, paid=(), battlefield=()):
        self.resolving_cost_paid_objects = paid
        self.battlefield = battlefield


def test_constant_returns_amount():
    """``Constant`` is a fixed-int formula — controller and state
    are ignored."""
    assert Constant(amount=4).value(_StubState(), controller_id=0) == 4


def test_constant_default_amount_is_zero():
    """Default-construction returns 0; useful as a no-op slot when
    a Formula is structurally required but the amount is fixed."""
    assert Constant().value(_StubState(), controller_id=0) == 0


def test_mv_of_cost_paid_returns_constant_when_no_paid_object():
    """Empty ``resolving_cost_paid_objects`` is the defensive branch.
    The cost gate normally guarantees ≥1 paid object, but the
    formula must not raise if a future call site invokes it without
    a paid object — instead it returns the constant alone."""
    state = _StubState(paid=())
    assert MVOfCostPaidObjectPlus(constant=2).value(
        state, controller_id=0,
    ) == 2


def test_mv_of_cost_paid_uses_first_object_mana_value():
    """Happy path: read the first paid object's mana value and add
    the constant. We use a tiny stub object — the formula only
    touches ``.printing.mana_cost.total``."""

    class _Cost:
        total = 3

    class _Printing:
        mana_cost = _Cost()

    class _Obj:
        printing = _Printing()

    state = _StubState(paid=(_Obj(),))
    assert MVOfCostPaidObjectPlus(constant=1).value(
        state, controller_id=0,
    ) == 4


def test_count_controlled_matching_filters_by_predicate_and_controller():
    """``CountControlledMatching`` walks the battlefield once, counting
    only objects controlled by the resolving controller that satisfy
    the predicate. Wrapping a trivial always-true predicate verifies
    the controller filter and the iteration shape."""

    class _AlwaysTrue:
        def test(self, obj, state):
            return True

    class _Obj:
        def __init__(self, controller_id):
            self.controller_id = controller_id

    state = _StubState(battlefield=(
        _Obj(controller_id=0),
        _Obj(controller_id=1),
        _Obj(controller_id=0),
    ))
    formula = CountControlledMatching(predicate=_AlwaysTrue())
    assert formula.value(state, controller_id=0) == 2
    assert formula.value(state, controller_id=1) == 1


def test_count_controlled_matching_zero_when_predicate_rejects():
    """Predicate ``False`` for everything → 0, even with permanents
    on the battlefield."""

    class _AlwaysFalse:
        def test(self, obj, state):
            return False

    class _Obj:
        controller_id = 0

    state = _StubState(battlefield=(_Obj(), _Obj()))
    assert CountControlledMatching(predicate=_AlwaysFalse()).value(
        state, controller_id=0,
    ) == 0
