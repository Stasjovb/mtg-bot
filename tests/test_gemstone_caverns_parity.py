"""Gemstone Caverns — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

**2026-09-28 update (``feature/cube-fixes-1``):** the Python parse now
models the printed card faithfully — "{T}: Add {C}. If Gemstone Caverns
has a luck counter on it, instead add one mana of any color." is a
luck-counter-gated ``IfConditionElse`` and the CR 103.6 opening-hand line
is ``CardPrinting.opening_hand_action``. The ``AddManaToPool(any)`` shape
described below dropped the "{C} without a luck counter" clause; the
frozen Rust bridge still emits it, so the shape / bridge / mint probes are
now ``*_divergence_pin`` tests, and the MINT + PAY probe drives the
luck-counter branch (where the engines still agree).

Gemstone Caverns is a ``{0}`` Legendary Land in the EoE pool (the
classic Coldsnap legendary "you may have this in play turn 0" land).
The load-bearing parity-relevant ability for this probe is the
activated mana ability:

    "{T}: Add one mana of any color."

Parser-emitted Effect shape (the EFFECT half, distinct from any
turn-0 free-into-play machinery — that's a separate substrate
surface not covered by the AddManaToPool Effect):

    ``AddManaToPool(produces=(('any', 1),), spend_restriction=None)``

attached to an ActivatedAbility whose ``cost`` carries
``tap_self=True`` and no mana cost (compare Mana Confluence batch-4
sibling: same Effect, but Mana Confluence's AA cost also carries
``pay_life=1``).  Same bridge arm; the EFFECT-side bridge round-trip
is byte-equal to Mana Confluence's.

This module is the **load-bearing PROBED-tier flip evidence** for
Gemstone Caverns.  Templates on the immediately-prior batch-4
sibling ``test_mana_confluence_parity.py`` (the FIRST PROBE_MODULES-
credited real-EoE Land + AddManaToPool consumer with amount=1); the
distinguishing dispatch here is the **Legendary** supertype (the
``is_legendary`` boolean is set on the printing) — Gemstone Caverns
is a Legendary Land while Mana Confluence is non-Legendary.

Per the IIII Optimistic Scavenger / Command Bridge precedent +
batches 1-3 lane discipline (per-slug attribution credits a PROBED
slot per-printing), this probe pins the Gemstone Caverns slug-
attribution.  Same EEEE-idiom (parse + bridge round-trip + Python-
side resolve) — no cross-engine ``compare_fields``.

**Distinct from the Mana Confluence sibling probe (batch-4).**  Mana
Confluence's AA cost carries ``pay_life=1``; Gemstone Caverns's AA
cost has no life-payment atom (just ``{T}``).  Same Effect class +
produces tuple + spend_restriction; the cost-side distinction is
not in scope for the Effect+bridge byte-equality lane discipline but
IS pinned on the parser-SoT side (the cost asserts below).
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.mana import AddManaToPool


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Zone constants (mirror Rust's u8 zone IDs).
ZONE_BATTLEFIELD = 2


# ---------------------------------------------------------------------------
# (1) Parser SoT — Gemstone Caverns is parser-claimed and carries one
# mana-ability AA. Since 2026-09-28 its effect is the luck-counter-gated
# ``IfConditionElse(SourceHasCounter("luck"), Add{any}, Add{C})`` (it was
# ``AddManaToPool(produces=(('any', 1),))`` before).
# ---------------------------------------------------------------------------


def test_gemstone_caverns_parser_claims_card():
    assert "Gemstone Caverns" in _PRINTINGS, (
        "Gemstone Caverns must be parser-claimed by the active "
        "CardSource"
    )


def test_gemstone_caverns_printed_attrs():
    """Pins the basic printing surface: Legendary Land type."""
    p = _PRINTINGS["Gemstone Caverns"]
    assert "Land" in p.card_types
    assert p.is_legendary is True, (
        "Gemstone Caverns must be a Legendary Land (the supertype "
        "distinguishing it from the non-Legendary Mana Confluence "
        "sibling)"
    )


def test_gemstone_caverns_mana_ability_shape():
    """Gemstone Caverns' single mana ability is the faithful
    luck-counter-gated shape (2026-09-28, ``feature/cube-fixes-1``):
    "{T}: Add {C}. If Gemstone Caverns has a luck counter on it, instead
    add one mana of any color." ->
    ``IfConditionElse(SourceHasCounter("luck"), AddManaToPool(any),
    AddManaToPool(C))``; automatic payment mirrors it through
    ``produces={C}`` + ``produces_with_counter=("luck", WUBRG)``, and the
    opening-hand line is ``opening_hand_action``. (The pre-2026-09-28
    ``AddManaToPool(produces=(("any", 1),))`` pinned here dropped the
    "{C} without a luck counter" clause.)"""
    from mtg_bot.effects.combinators import IfConditionElse
    from mtg_bot.effects.conditions import SourceHasCounter
    from mtg_bot.opening_hand import BeginGameOnBattlefield

    p = _PRINTINGS["Gemstone Caverns"]
    (aa,) = p.activated_abilities
    assert aa.effect == IfConditionElse(
        condition=SourceHasCounter("luck"),
        then_effect=AddManaToPool(produces=(("any", 1),)),
        else_effect=AddManaToPool(produces=(("C", 1),)),
    )
    assert aa.cost.tap_self is True
    # Distinct from Mana Confluence batch-4: NO pay_life cost atom.
    assert aa.cost.pay_life == 0
    assert aa.is_mana_ability is True
    assert p.produces == frozenset({"C"})
    assert p.mana_only_from_produces is True
    assert p.produces_with_counter == ("luck", frozenset("WUBRG"))
    assert p.opening_hand_action == BeginGameOnBattlefield(
        only_if_not_starting_player=True,
        counters=(("luck", 1),),
        exile_from_hand=1,
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the add_mana_to_pool dict shape round-trips
# byte-equal to the parsed printing's emitted Effect.  Bit-identical
# bridge round-trip to the Mana Confluence sibling probe (the Effect
# class + produces + spend_restriction tuple matches); the per-slug
# attribution distinction is on the carrier (Legendary Gemstone Caverns
# vs non-Legendary Mana Confluence).
# ---------------------------------------------------------------------------


def test_gemstone_caverns_bridge_arm_round_trip_luck_counter_gate_divergence_pin():
    """**Divergence pin (2026-09-28, ``feature/cube-fixes-1``).** The
    frozen Rust bridge still emits Gemstone Caverns' mana ability as the
    old ungated ``{"kind": "add_mana_to_pool", "color": "any"}`` ->
    ``AddManaToPool(produces=(("any", 1),))``. That shape dropped the
    printed clause "{T}: Add {C}. If Gemstone Caverns has a luck counter
    on it, instead ..." -- without a luck counter the land makes {C}.

    The Python parse (source of truth) is the gated
    ``IfConditionElse(SourceHasCounter("luck"), Add{any}, Add{C})``: the
    bridged Rust effect equals ONLY its luck-counter branch. Closure
    path: a Rust counter-gated mana effect + bridge arm; when it lands,
    ``parsed == bridged`` holds again and this pin must be inverted.
    """
    from mtg_bot.effects.combinators import IfConditionElse
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "any", "amount": 1}
    )
    assert isinstance(bridged, AddManaToPool)
    assert bridged.produces == (("any", 1),)
    assert bridged.spend_restriction is None

    (aa,) = _PRINTINGS["Gemstone Caverns"].activated_abilities
    assert isinstance(aa.effect, IfConditionElse)
    # The divergence: the parsed effect is not the bridged one ...
    assert aa.effect != bridged
    # ... the bridged shape is only the luck-counter branch; the
    # dropped clause is the colorless else-branch.
    assert aa.effect.then_effect == bridged
    assert aa.effect.else_effect == AddManaToPool(produces=(("C", 1),))


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — closed-vocab color per the
# Mana Confluence batch-4 precedent.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_gemstone_caverns_add_mana_to_pool_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the
    ``{"kind": "add_mana_to_pool", "color": "C", "amount": 1}`` dict
    shape on a Gemstone-Caverns-shape Legendary Land carrier (closed-
    vocab color per the Mana Confluence batch-4 precedent + the
    round-27 bridge-arm docstring)."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Gemstone Caverns (synthetic carrier)",
            "card_types": ["Land"],
            "supertypes": ["Legendary"],
            "mana_cost": {"generic": 0},
            "effects": [],
            "activated_abilities": [
                {
                    "cost": {"mana": {"generic": 0}},
                    "effect": {
                        "kind": "add_mana_to_pool",
                        "color": "C",
                        "amount": 1,
                    },
                    "is_mana_ability": True,
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Gemstone Caverns printing on Python-side resolve.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_gemstone_caverns_mana_ability_luck_counter_gate_divergence_pin():
    """**Divergence pin (2026-09-28, ``feature/cube-fixes-1``) --
    replaces the pre-2026-09-28 ``..._legendary_any_parity`` probe.**

    The frozen Rust side mints ``any`` whenever Gemstone Caverns taps
    (bridged ``AddManaToPool(produces=(("any", 1),))``). The printed
    ability is "{T}: Add {C}. If Gemstone Caverns has a luck counter on
    it, instead add one mana of any color." -- the old shape dropped the
    "{C} without a luck counter" clause. The Python parse (source of
    truth) resolves:

      * WITHOUT a luck counter -> one ``C`` coin (Rust: ``any``) --
        the pinned divergence;
      * WITH a luck counter -> one ``any`` coin, equal to the bridged
        Rust emission.

    Closure path: a Rust counter-gated mana effect + bridge arm (and the
    CR 103.6 opening-hand hook for the counter to exist at all).
    """
    from mtg_bot.game import Zone, add_counters
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )

    real = _PRINTINGS.get("Gemstone Caverns")
    if real is None:
        pytest.skip("Gemstone Caverns absent from active CardSource")
    assert "Land" in real.card_types
    assert real.is_legendary is True
    (aa,) = real.activated_abilities

    bridged = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "any", "amount": 1}
    )

    def mint(with_luck, effect):
        py_state = build_python_state(
            DeckSpec(card_defs=(), p0_library=(), p1_library=())
        )
        src = py_state.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
        py_state.battlefield.append(src)
        if with_luck:
            add_counters(py_state, src, "luck", 1)
        py_state.resolving_source = src
        effect.resolve(py_state, src.controller_id)
        py_state.resolving_source = None
        assert len(py_state.players[1].mana_pool) == 0
        return [
            (c.color, c.spend_restriction)
            for c in py_state.players[0].mana_pool
        ]

    # Without a luck counter: the pinned divergence (Python C, Rust any).
    assert mint(False, aa.effect) == [("C", None)]
    assert mint(False, bridged) == [("any", None)]
    # With a luck counter: the two agree.
    assert mint(True, aa.effect) == mint(True, bridged) == [("any", None)]


# ---------------------------------------------------------------------------
# (5) Phase 4E variant probe — cross-engine MINT + PAY byte-equality on
# the actual parsed Gemstone Caverns printing.
#
# This closes the "different probe shape" follow-on identified in the
# 2026-05-25 Rust-parity-campaign handoff: Gemstone Caverns is a LAND
# that produces ``any`` on tap (no AA mint, just produces ``any`` on
# tap) and therefore exercises the Phase 4E payment-time satisfies-any-
# color path on a real-EoE Land carrier — distinct from the AA[0] spell-
# side wildcard mint shape (All-Fates Scroll / batch-3 sibling).
#
# The mint-only probe above closed the substrate-only contract at the
# AddManaToPool resolve surface.  The Phase 4E payment-time substrate
# (commit ``daecd399``, 2026-05-27) shipped the deferred CR 106.5
# satisfies-any-color semantics: a wildcard ``any`` coin satisfies any
# colored requirement at ``pay_mana_cost`` / ``pool_can_cover`` /
# ``auto_tap_pay_for_cost``.  This test composes Gemstone Caverns's
# AA-emitted ``any`` coin against that newly-landed payment surface
# cross-engine — the FIRST PROBE_MODULES-credited probe binding a
# real-EoE Land's wildcard MINT to the Phase 4E PAYMENT-time semantics
# round-tripped byte-equal between Rust ``ManaPool`` and Python
# ``ManaCoin`` pool.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_gemstone_caverns_mint_then_pay_colored_byte_equal():
    """**Phase 4E variant probe — Gemstone Caverns wildcard MINT + colored
    PAY round-trip byte-equal cross-engine.**

    Drives the **ACTUAL parsed Gemstone Caverns printing** through a
    full mint→pay sequence on BOTH engines and asserts byte-equality
    on the post-pay ManaPool snapshot at each step:

      1. Empty starting pool — 7-key snapshot all-zero on both sides.
      2. Resolve Gemstone Caverns's mana ability (mint one ``any``
         coin) — both pools show ``any=1``, all other slots 0.
      3. Pay ``{W}`` from the wildcard — both pools fully drain
         (``any=0``, ``W=0``).

    **Newness vs. the mint-only probe above:** that probe pinned the
    Effect+bridge layer at the resolve surface but did NOT exercise
    the Phase 4E payment surface — at the time it landed, paying a
    colored cost with an ``any`` coin was a deferred follow-on. Now
    that the payment substrate has landed (commit ``daecd399``), this
    test pins the end-to-end MINT + PAY round trip byte-equal,
    closing the variant probe the 2026-05-25 handoff flagged.

    **Bridge arms exercised:**
      * ``add_mana_to_pool`` (mint, round-27 bridge arm).
      * ``_python_mana_pool_signature`` (7-tuple snapshot on Python
        ``list[ManaCoin]``).
      * Rust ``GameState.get_mana_pool`` (7-key snapshot).
      * Rust ``GameState.pay_mana_cost`` (Phase 4E payment-time
        satisfies-any-color drain — ``daecd399``).
      * Python ``_coin_matches_color`` (matches the ``"any"`` coin
        against any color string — the Python SoT the Rust widening
        mirrors).

    **Observables asserted at each step:**
      * Step-1 snapshot byte-equality (empty pool, 7 zeros on both).
      * Step-2 snapshot byte-equality (post-mint: ``any=1`` only).
      * Step-3 snapshot byte-equality (post-pay: fully empty).
    """
    import mtg_bot_engine as e

    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.mana import AddManaToPool
    from mtg_bot.game import ManaCoin, Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        _python_mana_pool_signature,
        build_python_state,
    )
    from mtg_bot.actions import _coin_matches_color

    # ------------------------------------------------------------------
    # 0. Resolve the real-EoE Gemstone Caverns printing + its any-mint
    #    AddManaToPool AA.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Gemstone Caverns")
    if real is None:
        pytest.skip("Gemstone Caverns absent from active CardSource")
    # 2026-09-28: the mana ability is luck-counter gated (see the
    # ``..._luck_counter_gate_divergence_pin`` above); this MINT + PAY
    # probe drives the luck-counter branch, where Python and the frozen
    # Rust ``any`` emission still agree byte-for-byte.
    (aa,) = real.activated_abilities
    assert aa.effect.then_effect == AddManaToPool(produces=(("any", 1),))

    # ------------------------------------------------------------------
    # 1. Empty-pool snapshot byte-equality (sanity / pre-mint).
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)
    py_source = py_state.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    r = e.Registry()
    gs = e.make_state(r, [], [])

    def _rust_snapshot(gs_, pid):
        return tuple(sorted(gs_.get_mana_pool(pid).items()))

    py_sig_empty = _python_mana_pool_signature(py_state.players[0].mana_pool)
    rust_sig_empty = _rust_snapshot(gs, 0)
    assert py_sig_empty == rust_sig_empty, (
        f"Step-1 empty-pool snapshot must be byte-equal cross-engine; "
        f"python={py_sig_empty}, rust={rust_sig_empty}"
    )

    # ------------------------------------------------------------------
    # 2. Mint: resolve Gemstone Caverns's AA on Python; add_mana("any",1)
    #    on Rust. Snapshot equality after the mint.
    # ------------------------------------------------------------------
    from mtg_bot.game import add_counters

    add_counters(py_state, py_source, "luck", 1)
    py_state.resolving_source = py_source
    aa.effect.resolve(py_state, py_source.controller_id)
    py_state.resolving_source = None
    gs.add_mana(0, "any", 1)

    py_sig_post_mint = _python_mana_pool_signature(
        py_state.players[0].mana_pool
    )
    rust_sig_post_mint = _rust_snapshot(gs, 0)
    assert py_sig_post_mint == rust_sig_post_mint, (
        f"Step-2 post-mint snapshot must be byte-equal cross-engine; "
        f"python={py_sig_post_mint}, rust={rust_sig_post_mint}"
    )
    # And exactly the expected 7-tuple shape.
    expected_post_mint = (
        ("B", 0), ("C", 0), ("G", 0), ("R", 0),
        ("U", 0), ("W", 0), ("any", 1),
    )
    assert py_sig_post_mint == expected_post_mint, (
        f"Step-2 snapshot must reflect a single wildcard coin; got "
        f"{py_sig_post_mint}"
    )

    # ------------------------------------------------------------------
    # 3. Pay {W}: the wildcard coin pays the colored pip on both engines
    #    via the Phase 4E payment-time satisfies-any-color semantics.
    # ------------------------------------------------------------------
    # Python SoT pin: the ``any`` coin matches the W color string at
    # the matches-color predicate.
    py_coin = py_state.players[0].mana_pool[0]
    assert _coin_matches_color(py_coin, "W"), (
        "Python ``_coin_matches_color`` must return True for an "
        "``any`` coin against any color string — this is the Python "
        "SoT the Rust widening mirrors"
    )
    # Drain the wildcard coin on the Python side (mirrors the spend
    # by ``actions._consume_for_color`` / ``auto_tap_for_cost``).
    py_state.players[0].mana_pool.pop(0)

    # Rust side: pay_mana_cost drains the wildcard coin from the
    # `any` slot via the Phase 4E payment-time satisfies-any-color path.
    ok = gs.pay_mana_cost(0, {"W": 1})
    assert ok, (
        "Rust ``pay_mana_cost`` must accept a wildcard ``any`` coin "
        "as payment for a {W} requirement (Phase 4E payment-time "
        "satisfies-any-color semantics — commit daecd399)"
    )

    py_sig_post_pay = _python_mana_pool_signature(
        py_state.players[0].mana_pool
    )
    rust_sig_post_pay = _rust_snapshot(gs, 0)
    assert py_sig_post_pay == rust_sig_post_pay, (
        f"Step-3 post-pay snapshot must be byte-equal cross-engine; "
        f"python={py_sig_post_pay}, rust={rust_sig_post_pay}"
    )
    # And both pools fully empty post-pay.
    expected_post_pay = (
        ("B", 0), ("C", 0), ("G", 0), ("R", 0),
        ("U", 0), ("W", 0), ("any", 0),
    )
    assert py_sig_post_pay == expected_post_pay, (
        f"Step-3 snapshot must reflect a fully-drained pool; got "
        f"{py_sig_post_pay}"
    )
    # p1's pool untouched throughout.
    assert _rust_snapshot(gs, 1) == expected_post_pay
    assert (
        _python_mana_pool_signature(py_state.players[1].mana_pool)
        == expected_post_pay
    )
