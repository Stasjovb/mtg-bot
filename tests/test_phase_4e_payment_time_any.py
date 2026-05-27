"""**Phase 4E payment-time satisfies-any-color follow-on (2026-05-27).**

Closes the C2.5 substrate's deferred follow-on at the payment surface.
The C2.5 cycle (commit ``a82cf1e8``) shipped the Rust ``ManaPool.any``
slot + 7-tuple snapshot + Python ``_RUST_COLORS`` widen. It explicitly
deferred the satisfies-any-color CR 106.5 payment semantics to a
follow-on; this module exercises that follow-on.

**What landed this slice:**

  - ``state_ops_legal::pool_can_cover`` counts ``pool.any`` toward any
    colored requirement's shortfall, then folds leftover ``any`` coins
    into the generic-payable total.
  - ``state_ops_decisions::can_pay_mana_cost_internal`` /
    ``pay_mana_cost_internal`` carry the same widening for the
    decision-callback count-only pay path.
  - ``state_ops_cast::pay_mana_cost`` (the legacy count-only pay
    primitive) drains same-color FIFO first, then drains ``b'a'``
    coins for any shortfall, then drains generic in the legacy
    ``C → W → U → B → R → G`` priority with ``b'a'`` appended at the
    tail (defers wildcard flexibility for future costs from this same
    pool).
  - ``state_ops_mana::GameState::pay_mana_cost`` PyMethod gains the
    same widening.
  - ``state_ops_cast::auto_tap_pay_for_cost`` accepts ``b'a'`` coins
    as matching any colored requirement at its FIFO enumerate-walk —
    byte-mirror of Python ``actions._coin_matches_color`` returning
    True for ``coin.color == "any"``.
  - ``state_ops_legal::auto_tap_headroom_pool`` credits a battlefield
    permanent's ``mana_produced=["any"]`` symbol to ``pool.any``
    headroom alongside the closed colored vocab.

**Out of scope for this slice:**

  - Per-card real-EoE byte-equal probes for All-Fates Scroll and
    Gemstone Caverns (Phase 4E Cycle 3 / variant probe — separate
    cycle each, the substrate they compose against ships here).
  - POOL_PARITY + SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY refresh — a
    separate metric-doc cycle.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# pay_mana_cost PyMethod — payment-time satisfies-any-color semantics
# ---------------------------------------------------------------------------


def test_pay_mana_cost_any_coin_satisfies_one_colored_requirement():
    """A pool of ``[any: 1]`` can pay a ``{W}`` cost. The wildcard coin
    drains from ``pool.any``; the W slot was already 0.
    """
    import mtg_bot_engine as e

    r = e.Registry()
    gs = e.make_state(r, [], [])
    gs.add_mana(0, "any", 1)
    ok = gs.pay_mana_cost(0, {"W": 1})
    assert ok
    pool = gs.get_mana_pool(0)
    assert pool["any"] == 0
    assert pool["W"] == 0


def test_pay_mana_cost_any_coins_satisfy_multiple_colored_requirements():
    """A pool of ``[any: 2]`` can pay ``{W}{U}``. Each wildcard pays
    one colored requirement.
    """
    import mtg_bot_engine as e

    r = e.Registry()
    gs = e.make_state(r, [], [])
    gs.add_mana(0, "any", 2)
    ok = gs.pay_mana_cost(0, {"W": 1, "U": 1})
    assert ok
    pool = gs.get_mana_pool(0)
    assert pool["any"] == 0
    assert pool["W"] == 0
    assert pool["U"] == 0


def test_pay_mana_cost_same_color_drains_before_any_for_colored():
    """``[W: 1, any: 1]`` paying ``{W}`` drains the ``W`` coin first
    and keeps the wildcard reserved for future costs.
    """
    import mtg_bot_engine as e

    r = e.Registry()
    gs = e.make_state(r, [], [])
    gs.add_mana(0, "W", 1)
    gs.add_mana(0, "any", 1)
    ok = gs.pay_mana_cost(0, {"W": 1})
    assert ok
    pool = gs.get_mana_pool(0)
    assert pool["W"] == 0, "same-color slot must drain first"
    assert pool["any"] == 1, "wildcard must remain — same-color covered the need"


def test_pay_mana_cost_any_covers_partial_colored_shortfall():
    """``[W: 1, any: 1]`` paying ``{W}{W}`` drains the W coin first,
    then drains the wildcard to cover the second W. Pool fully empty.
    """
    import mtg_bot_engine as e

    r = e.Registry()
    gs = e.make_state(r, [], [])
    gs.add_mana(0, "W", 1)
    gs.add_mana(0, "any", 1)
    ok = gs.pay_mana_cost(0, {"W": 2})
    assert ok
    pool = gs.get_mana_pool(0)
    assert pool["W"] == 0
    assert pool["any"] == 0


def test_pay_mana_cost_any_leftover_pays_generic():
    """``[W: 1, any: 2]`` paying ``{W}{1}`` drains W for the colored
    pip, then drains one wildcard for generic. The remaining wildcard
    stays.
    """
    import mtg_bot_engine as e

    r = e.Registry()
    gs = e.make_state(r, [], [])
    gs.add_mana(0, "W", 1)
    gs.add_mana(0, "any", 2)
    ok = gs.pay_mana_cost(0, {"W": 1, "generic": 1})
    assert ok
    pool = gs.get_mana_pool(0)
    assert pool["W"] == 0
    assert pool["any"] == 1, (
        "wildcard drains LAST for generic (after C→W→U→B→R→G); the leftover "
        "stays available for future costs"
    )


def test_pay_mana_cost_insufficient_total_with_any():
    """``[any: 1]`` cannot pay ``{W}{U}`` — only one wildcard but two
    colored pips. Fail without mutation.
    """
    import mtg_bot_engine as e

    r = e.Registry()
    gs = e.make_state(r, [], [])
    gs.add_mana(0, "any", 1)
    ok = gs.pay_mana_cost(0, {"W": 1, "U": 1})
    assert not ok
    # Pool unchanged.
    pool = gs.get_mana_pool(0)
    assert pool["any"] == 1


def test_pay_mana_cost_any_pays_pure_generic():
    """``[any: 2]`` can pay ``{2}`` (pure-generic cost). Both wildcards
    drain at the generic tail.
    """
    import mtg_bot_engine as e

    r = e.Registry()
    gs = e.make_state(r, [], [])
    gs.add_mana(0, "any", 2)
    ok = gs.pay_mana_cost(0, {"generic": 2})
    assert ok
    pool = gs.get_mana_pool(0)
    assert pool["any"] == 0


def test_pay_mana_cost_generic_drain_prefers_colorless_before_any():
    """``[C: 1, any: 1]`` paying ``{1}`` drains the colorless coin
    (legacy C→W→U→B→R→G priority preserved); the wildcard stays.
    """
    import mtg_bot_engine as e

    r = e.Registry()
    gs = e.make_state(r, [], [])
    gs.add_mana(0, "C", 1)
    gs.add_mana(0, "any", 1)
    ok = gs.pay_mana_cost(0, {"generic": 1})
    assert ok
    pool = gs.get_mana_pool(0)
    assert pool["C"] == 0
    assert pool["any"] == 1, (
        "generic drain order C→W→U→B→R→G→a preserves wildcard flexibility "
        "for future costs"
    )


def test_pay_mana_cost_colored_priority_over_generic_when_both_present():
    """``[W: 1, any: 1]`` paying ``{W}{1}`` drains W for the colored
    pip and the wildcard for generic (last-tier of the generic order).
    Pool fully empty.
    """
    import mtg_bot_engine as e

    r = e.Registry()
    gs = e.make_state(r, [], [])
    gs.add_mana(0, "W", 1)
    gs.add_mana(0, "any", 1)
    ok = gs.pay_mana_cost(0, {"W": 1, "generic": 1})
    assert ok
    pool = gs.get_mana_pool(0)
    assert pool["W"] == 0
    assert pool["any"] == 0


# ---------------------------------------------------------------------------
# Cross-engine parity smoke — ManaPool ".any" payment-time semantics
# ---------------------------------------------------------------------------


def test_python_actions_any_coin_satisfies_colored_cost():
    """Sanity-check the Python SoT: Python's ``_coin_matches_color``
    returns True for ``coin.color == "any"`` against any color string.
    The Rust widening mirrors this.
    """
    from mtg_bot.actions import _coin_matches_color
    from mtg_bot.game import ManaCoin

    any_coin = ManaCoin(color="any")
    for color in ("W", "U", "B", "R", "G", "C"):
        assert _coin_matches_color(any_coin, color)


def test_cross_engine_parity_pool_any_payment_signature():
    """Cross-engine signature parity: after both engines mint an
    ``any`` coin and spend it on a single colored requirement, the
    7-tuple snapshot is identical (both empty pools).
    """
    import mtg_bot_engine as e

    from mtg_bot.game import ManaCoin
    from mtg_bot.parity.cross_engine import _python_mana_pool_signature

    # Python side: a coin of "any" pays {W} — both Python actions
    # surface and the cross-engine snapshot should reflect an empty
    # pool after spending.
    py_pool: list = [ManaCoin(color="any")]
    # Simulate the spend by popping the coin (this is what
    # auto_tap_for_cost does for a {W} cost).
    py_pool.pop(0)
    py_sig = _python_mana_pool_signature(py_pool)

    # Rust side: add "any" coin, pay {W}, snapshot.
    r = e.Registry()
    gs = e.make_state(r, [], [])
    gs.add_mana(0, "any", 1)
    ok = gs.pay_mana_cost(0, {"W": 1})
    assert ok
    rust_pool = gs.get_mana_pool(0)
    rust_sig = tuple(sorted(rust_pool.items()))

    assert py_sig == rust_sig, (
        f"Python ({py_sig}) vs Rust ({rust_sig}) mana-pool snapshot "
        f"must match byte-equal after spending the wildcard on a "
        f"colored requirement"
    )


# ---------------------------------------------------------------------------
# Edge cases — empty pool, zero costs, large pools
# ---------------------------------------------------------------------------


def test_pay_mana_cost_empty_pool_with_zero_cost_succeeds():
    """A zero-cost spell can be paid from an empty pool (no
    requirements to satisfy).
    """
    import mtg_bot_engine as e

    r = e.Registry()
    gs = e.make_state(r, [], [])
    ok = gs.pay_mana_cost(0, {})
    assert ok


def test_pay_mana_cost_any_three_for_three_colored():
    """``[any: 3]`` paying ``{W}{U}{B}`` — three wildcards, three
    distinct colored pips. Each wildcard pays one colored.
    """
    import mtg_bot_engine as e

    r = e.Registry()
    gs = e.make_state(r, [], [])
    gs.add_mana(0, "any", 3)
    ok = gs.pay_mana_cost(0, {"W": 1, "U": 1, "B": 1})
    assert ok
    pool = gs.get_mana_pool(0)
    assert pool["any"] == 0


def test_pay_mana_cost_pool_unchanged_on_fail():
    """A pay attempt that fails leaves the pool exactly unchanged
    (snapshot/rollback semantics preserved through the widening).
    """
    import mtg_bot_engine as e

    r = e.Registry()
    gs = e.make_state(r, [], [])
    gs.add_mana(0, "W", 1)
    gs.add_mana(0, "any", 1)
    # Need {W}{U}{B} — only 1 W + 1 any = 2 coins, but 3 colored pips.
    # Fast-fail path (insufficient total).
    ok = gs.pay_mana_cost(0, {"W": 1, "U": 1, "B": 1})
    assert not ok
    pool = gs.get_mana_pool(0)
    assert pool["W"] == 1
    assert pool["any"] == 1


def test_pay_mana_cost_any_after_underflow_on_same_color():
    """``[W: 0, U: 0, any: 2]`` paying ``{W}{U}{U}`` — 2 wildcards for
    3 colored pips. Fails; pool unchanged.
    """
    import mtg_bot_engine as e

    r = e.Registry()
    gs = e.make_state(r, [], [])
    gs.add_mana(0, "any", 2)
    ok = gs.pay_mana_cost(0, {"W": 1, "U": 2})
    assert not ok
    pool = gs.get_mana_pool(0)
    assert pool["any"] == 2


def test_pay_mana_cost_mixed_colored_and_any_priority():
    """``[W: 2, any: 1]`` paying ``{W}{W}{U}`` — both W coins pay the
    two W pips, then the wildcard pays the single U pip. Empty pool.
    """
    import mtg_bot_engine as e

    r = e.Registry()
    gs = e.make_state(r, [], [])
    gs.add_mana(0, "W", 2)
    gs.add_mana(0, "any", 1)
    ok = gs.pay_mana_cost(0, {"W": 2, "U": 1})
    assert ok
    pool = gs.get_mana_pool(0)
    assert pool["W"] == 0
    assert pool["U"] == 0
    assert pool["any"] == 0
