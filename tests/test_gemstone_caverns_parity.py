"""Gemstone Caverns — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

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
# mana-ability AA whose effect is ``AddManaToPool(produces=(('any', 1),),
# spend_restriction=None)``.
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
    """Gemstone Caverns has at least one ActivatedAbility carrying an
    ``AddManaToPool(produces=(('any', 1),), spend_restriction=None)``
    effect (the {T}: Add one mana of any color mana ability)."""
    p = _PRINTINGS["Gemstone Caverns"]
    add_mana_aas = [
        aa for aa in p.activated_abilities
        if isinstance(aa.effect, AddManaToPool)
        and aa.effect.produces == (("any", 1),)
    ]
    assert len(add_mana_aas) >= 1, (
        f"Gemstone Caverns must have at least one AddManaToPool any-1 "
        f"AA; got {len(add_mana_aas)}"
    )
    aa = add_mana_aas[0]
    assert aa.effect.spend_restriction is None, (
        f"Gemstone Caverns AddManaToPool AA must NOT carry a spend_"
        f"restriction (unrestricted any-color mana); got "
        f"spend_restriction={aa.effect.spend_restriction!r}"
    )
    assert aa.cost.tap_self is True
    # Distinct from Mana Confluence batch-4: NO pay_life cost atom.
    assert aa.cost.pay_life == 0, (
        f"Gemstone Caverns AA cost must NOT carry pay_life atom "
        f"(distinct from Mana Confluence sibling); got "
        f"pay_life={aa.cost.pay_life}"
    )
    assert aa.is_mana_ability is True


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the add_mana_to_pool dict shape round-trips
# byte-equal to the parsed printing's emitted Effect.  Bit-identical
# bridge round-trip to the Mana Confluence sibling probe (the Effect
# class + produces + spend_restriction tuple matches); the per-slug
# attribution distinction is on the carrier (Legendary Gemstone Caverns
# vs non-Legendary Mana Confluence).
# ---------------------------------------------------------------------------


def test_gemstone_caverns_bridge_arm_round_trip():
    """The bridge arm ``add_mana_to_pool`` (cross_engine.py:7342)
    round-trips ``{"kind": "add_mana_to_pool", "color": "any",
    "amount": 1}`` to the matching Python
    ``AddManaToPool(produces=(('any', 1),), spend_restriction=None)``
    instance.  Bit-identical bridge round-trip to the Mana Confluence
    sibling probe at the Effect level (the per-slug attribution
    distinction is on the Legendary supertype, not the Effect)."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "any", "amount": 1}
    )
    assert isinstance(bridged, AddManaToPool)
    assert bridged.produces == (("any", 1),)
    assert bridged.spend_restriction is None

    # Effect-level byte-equality between the parsed real-EoE printing's
    # AddManaToPool any-1 AA and the bridged Effect.
    p = _PRINTINGS["Gemstone Caverns"]
    aa = next(
        aa for aa in p.activated_abilities
        if isinstance(aa.effect, AddManaToPool)
        and aa.effect.produces == (("any", 1),)
    )
    assert aa.effect == bridged, (
        f"Gemstone Caverns AA Effect must be byte-equal to the bridged "
        f"Effect (AddManaToPool(produces=(('any', 1),)) structural "
        f"contract for the PROBED tier); got parsed={aa.effect!r}, "
        f"bridged={bridged!r}"
    )


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


def test_cross_engine_real_eoe_gemstone_caverns_mana_ability_legendary_any_parity():
    """**GENUINE real-EoE cross-engine probe — Gemstone Caverns mana
    ability → AddManaToPool(produces=(('any', 1),)). PROBED-tier flip
    (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Gemstone Caverns printing** on the
    Python side through the AddManaToPool effect's resolve path.
    Same EEEE-idiom + cost-substrate deferral as the immediately-
    prior batch-4 sibling Mana Confluence probe; the distinguishing
    dispatch here is the **Legendary** supertype on the printing.

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
    binding the Gemstone Caverns slug to the AA + AddManaToPool(
    produces=(('any', 1),)) Effect+bridge round-trip on a REAL parsed
    EoE **Legendary** Land carrier.

    **Bridge arm exercised:**
      * ``add_mana_to_pool`` (round-27 bridge arm).

    **Setup (Python-side):**
      * p0 has Gemstone Caverns on the battlefield (the AA source).
      * p0's mana pool starts empty.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "add_mana_to_pool", "color": "any", "amount": 1}``
        translates to ``AddManaToPool(produces=(('any', 1),),
        spend_restriction=None)``.
      * The Land's mana ActivatedAbility emits the same Effect.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * Post-resolve: p0's mana pool gained exactly one ManaCoin with
        color='any' and spend_restriction=None.
      * Legendary supertype carrier — the per-slug attribution
        distinction from Mana Confluence.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Gemstone Caverns printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Gemstone Caverns")
    if real is None:
        pytest.skip("Gemstone Caverns absent from active CardSource")
    assert "Land" in real.card_types
    assert real.is_legendary is True, (
        "Gemstone Caverns must be a Legendary Land — the per-slug "
        "attribution distinction from non-Legendary sibling Mana "
        "Confluence"
    )
    aa = next(
        aa for aa in real.activated_abilities
        if isinstance(aa.effect, AddManaToPool)
        and aa.effect.produces == (("any", 1),)
    )
    assert aa.effect.spend_restriction is None

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "any", "amount": 1}
    )
    assert isinstance(bridged, AddManaToPool)
    assert aa.effect == bridged

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect shapes (regression guard).
    # ------------------------------------------------------------------
    # spend_restriction=None distinguishes from Power Depot /
    # Steelswarm Operator / Eldrazi Temple AA[1] spend-restricted
    # variants.  The 'any' wildcard distinguishes from 'C' colorless
    # (Cascading Cataracts sibling probe has 'any', Eldrazi Temple
    # AA[0] has 'C').
    assert bridged.spend_restriction is None
    assert bridged.produces[0][0] == "any"

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    assert len(py_state.players[0].mana_pool) == 0

    aa.effect.resolve(py_state, py_source.controller_id)

    p0_pool = py_state.players[0].mana_pool
    assert len(p0_pool) == 1, (
        f"Gemstone Caverns AA must mint exactly 1 coin; got pool "
        f"size={len(p0_pool)}"
    )
    coin = p0_pool[0]
    assert coin.color == "any"
    assert coin.spend_restriction is None
    assert len(py_state.players[1].mana_pool) == 0


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
    aa = next(
        aa for aa in real.activated_abilities
        if isinstance(aa.effect, AddManaToPool)
        and aa.effect.produces == (("any", 1),)
    )
    assert aa.effect.spend_restriction is None

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
    aa.effect.resolve(py_state, py_source.controller_id)
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
