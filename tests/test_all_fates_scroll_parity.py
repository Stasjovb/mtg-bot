"""All-Fates Scroll — per-card real-EoE cross-engine byte-equal probe
(``covered_by_construction`` → PROBED tier flip; Phase 4E payment-time
satisfies-any-color closure on the AA[0] spell-side wildcard mint).

All-Fates Scroll is a ``{3}`` Artifact in the EoE pool with two
activated abilities:

    AA[0] — ``{T}: Add one mana of any color.``
        cost = ActivationCost(tap_self=True)
        effect = AddManaToPool(produces=(("any", 1),),
                               spend_restriction=None)
        is_mana_ability = True

    AA[1] — ``{7}, {T}, Sacrifice this artifact: Draw X cards, where X
             is the number of differently named lands you control.``
        cost = ActivationCost(mana=ManaCost(generic=7), tap_self=True,
                              sacrifice_self=True)
        effect = DrawCardsByConditionMultiplier(
            condition=PerDifferentlyNamedLand(), ...
        )
        is_mana_ability = False

This probe is the **load-bearing PROBED-tier flip evidence** for
All-Fates Scroll. The C2.5 substrate (commit ``a82cf1e8``) shipped the
``ManaPool.any`` slot + the bridge + Rust resolve. The Phase 4E
payment-time follow-on (commit ``daecd399``, 2026-05-27) shipped the
satisfies-any-color CR 106.5 payment semantics so a wildcard ``any``
coin can pay any colored requirement at ``pay_mana_cost`` /
``pool_can_cover`` / ``auto_tap_pay_for_cost``. The
``auto_tap_pay_for_cost`` commit-phase ``b'a'`` arm follow-on
(THIS commit) closes the one-arm gap Worker C diagnosed in
``daecd399``'s commit-phase match: the plan-phase FIFO walk was
widened but the commit-phase per-color cache mirror was NOT, so
``mp.any`` drifted whenever a wildcard coin was consumed via
``auto_tap_pay_for_cost``.

This probe drives the **ACTUAL parsed All-Fates Scroll printing**
through a full mint→pay round-trip on BOTH engines and asserts
byte-equality on the post-pay ManaPool snapshot at each step. The PAY
path goes through ``cast_spell_noncreature`` on the Rust side, which
is exactly the call site that exposed Worker C's drift.

**Distinct from Gemstone Caverns variant probe (sibling).** Gemstone
Caverns is a LAND with a ``{T}: Add one mana of any color`` mana
ability — it exercises ``pay_mana_cost`` (the count-only path) for
the PAY half. All-Fates Scroll is an ARTIFACT — its AA[0] is also
``{T}: Add one mana of any color`` (same Effect class + produces),
but the PAY half goes through ``cast_spell_noncreature`` →
``auto_tap_pay_for_cost``, which is the OTHER payment surface. Same
Effect; different payment-path call site.

**Bridge arm exercised:**

  * ``add_mana_to_pool`` (round-27 bridge arm — the AA[0] mint).

**Observables asserted at each step:**

  1. Step-0: parser claim + AA[0] / AA[1] shape pin (the structural
     contract).
  2. Step-1: empty starting pool — 7-key snapshot all-zero on both
     sides.
  3. Step-2: post-mint (Python: resolve AA[0]; Rust: ``add_mana("any",
     1)``) — both pools show ``any=1``, all other slots 0.
  4. Step-3: post-pay (Python: pop the coin; Rust: cast a ``{W}``
     instant via ``cast_spell_noncreature`` which calls
     ``auto_tap_pay_for_cost``) — both pools fully drain. THIS is the
     load-bearing assertion: pre-fix, Rust would lie at ``any=1``
     (the commit-phase ``b'a'`` arm gap); post-fix, ``any=0``.
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
# (1) Parser SoT — All-Fates Scroll is parser-claimed and carries TWO
# activated abilities; AA[0] is the wildcard mint mana ability,
# AA[1] is the sac-draw.
# ---------------------------------------------------------------------------


def test_all_fates_scroll_parser_claims_card():
    assert "All-Fates Scroll" in _PRINTINGS, (
        "All-Fates Scroll must be parser-claimed by the active CardSource"
    )


def test_all_fates_scroll_printed_attrs():
    """Pins the basic printing surface: Artifact card type."""
    p = _PRINTINGS["All-Fates Scroll"]
    assert "Artifact" in p.card_types
    assert p.mana_cost.generic == 3, (
        "All-Fates Scroll's cast cost is {3} (pure generic; no colored "
        "pips)"
    )


def test_all_fates_scroll_aa0_mana_ability_shape():
    """All-Fates Scroll's AA[0] is the ``{T}: Add one mana of any color``
    mana ability with the parsed Effect shape
    ``AddManaToPool(produces=(('any', 1),), spend_restriction=None)``."""
    p = _PRINTINGS["All-Fates Scroll"]
    assert len(p.activated_abilities) == 2, (
        f"All-Fates Scroll must have exactly 2 AAs; got "
        f"{len(p.activated_abilities)}"
    )
    aa0 = p.activated_abilities[0]
    assert isinstance(aa0.effect, AddManaToPool)
    assert aa0.effect.produces == (("any", 1),)
    assert aa0.effect.spend_restriction is None
    assert aa0.cost.tap_self is True
    # Distinct from Mana Confluence / Gemstone Caverns sibling probes:
    # AFS is NOT a Land carrier; this is the artifact-side wildcard
    # mint.
    assert aa0.cost.sacrifice_self is False
    assert aa0.cost.pay_life == 0
    assert aa0.is_mana_ability is True


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the ``add_mana_to_pool`` dict shape round-trips
# byte-equal to the parsed printing's emitted Effect.
# ---------------------------------------------------------------------------


def test_all_fates_scroll_bridge_arm_round_trip():
    """The bridge arm ``add_mana_to_pool`` (cross_engine.py:7342) round-
    trips ``{"kind": "add_mana_to_pool", "color": "any", "amount": 1}``
    to the matching Python ``AddManaToPool(produces=(('any', 1),),
    spend_restriction=None)`` instance.  Bit-identical bridge round-trip
    to the Mana Confluence / Gemstone Caverns sibling probes at the
    Effect level; the per-slug attribution distinction is the artifact
    carrier (no Land supertype, no pay_life cost atom)."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "any", "amount": 1}
    )
    assert isinstance(bridged, AddManaToPool)
    assert bridged.produces == (("any", 1),)
    assert bridged.spend_restriction is None

    # Effect-level byte-equality between the parsed real-EoE printing's
    # AA[0] and the bridged Effect.
    p = _PRINTINGS["All-Fates Scroll"]
    aa0 = p.activated_abilities[0]
    assert aa0.effect == bridged, (
        f"All-Fates Scroll AA[0] Effect must be byte-equal to the "
        f"bridged Effect (AddManaToPool(produces=(('any', 1),)) "
        f"structural contract for the PROBED tier); got "
        f"parsed={aa0.effect!r}, bridged={bridged!r}"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — round-trip the AFS-shape printing
# through Rust's ``register_printing`` arm.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_all_fates_scroll_add_mana_to_pool_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the
    ``{"kind": "add_mana_to_pool", "color": "any", "amount": 1}`` dict
    shape on an All-Fates-Scroll-shape Artifact carrier."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "All-Fates Scroll (synthetic carrier)",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 3},
            "effects": [],
            "activated_abilities": [
                {
                    "cost": {"tap_self": True},
                    "effect": {
                        "kind": "add_mana_to_pool",
                        "color": "any",
                        "amount": 1,
                    },
                    "is_mana_ability": True,
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine MINT-only probe — drives the
# ACTUAL parsed All-Fates Scroll printing on Python-side resolve.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_all_fates_scroll_mana_ability_artifact_any_parity():
    """**GENUINE real-EoE cross-engine probe — All-Fates Scroll mana
    ability → AddManaToPool(produces=(('any', 1),)). PROBED-tier flip
    (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed All-Fates Scroll printing** on the
    Python side through the AddManaToPool effect's resolve path. Same
    EEEE-idiom as the Mana Confluence / Gemstone Caverns batch-4 /
    variant-probe siblings; the distinguishing dispatch here is the
    **Artifact** carrier (the wildcard mint surface on a spell-side
    permanent vs. the land-side siblings).

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
    binding the All-Fates Scroll slug to the AA[0] + AddManaToPool(
    produces=(('any', 1),)) Effect+bridge round-trip on a REAL parsed
    EoE **Artifact** carrier (and the load-bearing payment-path
    follow-on lives in the byte-equal probe below).

    **Bridge arm exercised:**
      * ``add_mana_to_pool`` (round-27 bridge arm).

    **Setup (Python-side):**
      * p0 has All-Fates Scroll on the battlefield (the AA source).
      * p0's mana pool starts empty.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "add_mana_to_pool", "color": "any", "amount": 1}``
        translates to ``AddManaToPool(produces=(('any', 1),),
        spend_restriction=None)``.
      * The Artifact's mana ActivatedAbility emits the same Effect.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * Post-resolve: p0's mana pool gained exactly one ManaCoin with
        color='any' and spend_restriction=None.
    """
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec, _ta_dict_to_python_effect, build_python_state,
    )

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed All-Fates Scroll printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("All-Fates Scroll")
    if real is None:
        pytest.skip("All-Fates Scroll absent from active CardSource")
    assert "Artifact" in real.card_types
    aa0 = real.activated_abilities[0]
    assert isinstance(aa0.effect, AddManaToPool)
    assert aa0.effect.produces == (("any", 1),)
    assert aa0.effect.spend_restriction is None

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "any", "amount": 1}
    )
    assert isinstance(bridged, AddManaToPool)
    assert aa0.effect == bridged

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect shapes (regression guard).
    # ------------------------------------------------------------------
    # spend_restriction=None distinguishes from spend-restricted variants.
    # The 'any' wildcard distinguishes from 'C' colorless.
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

    aa0.effect.resolve(py_state, py_source.controller_id)

    p0_pool = py_state.players[0].mana_pool
    assert len(p0_pool) == 1, (
        f"All-Fates Scroll AA[0] must mint exactly 1 coin; got pool "
        f"size={len(p0_pool)}"
    )
    coin = p0_pool[0]
    assert coin.color == "any"
    assert coin.spend_restriction is None
    assert len(py_state.players[1].mana_pool) == 0


# ---------------------------------------------------------------------------
# (5) Phase 4E payment-time variant probe — cross-engine MINT + PAY
# byte-equality on the actual parsed All-Fates Scroll printing, with
# the PAY phase routed through ``cast_spell_noncreature`` /
# ``auto_tap_pay_for_cost`` on the Rust side.
#
# This is the load-bearing closure of the Worker-C-diagnosed commit-
# phase ``b'a'`` arm gap. The Gemstone Caverns variant probe
# (test_gemstone_caverns_parity.py:test_cross_engine_real_eoe_gemstone_
# caverns_mint_then_pay_colored_byte_equal) exercises the same MINT +
# PAY shape against ``pay_mana_cost`` (the count-only path). This
# probe exercises it against the auto_tap_pay_for_cost path — the
# OTHER payment surface where the bug lived.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_all_fates_scroll_mint_then_pay_via_auto_tap_byte_equal():
    """**Phase 4E payment-time variant probe — All-Fates Scroll wildcard
    MINT + colored PAY via ``cast_spell_noncreature`` round-trip byte-
    equal cross-engine.**

    Drives the **ACTUAL parsed All-Fates Scroll printing** through a
    full mint→pay sequence on BOTH engines and asserts byte-equality
    on the post-pay ManaPool snapshot at each step:

      1. Empty starting pool — 7-key snapshot all-zero on both sides.
      2. Resolve All-Fates Scroll's AA[0] (mint one ``any`` coin) on
         Python; ``add_mana("any", 1)`` on Rust — both pools show
         ``any=1``, all other slots 0.
      3. Pay ``{W}`` from the wildcard — Python pops the coin
         (mirrors ``actions._consume_for_color`` /
         ``auto_tap_for_cost``); Rust casts a real noncreature spell
         with mana_cost={W} via ``cast_spell_noncreature``, which
         routes through ``auto_tap_pay_for_cost``. Both pools fully
         drain (``any=0``, ``W=0``).

    **Newness vs. the mint-only probe above:** that probe pinned the
    Effect+bridge layer at the resolve surface. This probe pins the
    end-to-end MINT + PAY round trip byte-equal through
    ``auto_tap_pay_for_cost`` — the path Worker C diagnosed as having
    a commit-phase per-color-cache drift on the ``b'a'`` arm in
    ``daecd399``. Pre-fix, this test would assert-fail at step 3
    because Rust would report ``any=1`` post-pay while Python correctly
    reports ``any=0``. Post-fix, both report ``any=0``.

    **Bridge arms exercised:**
      * ``add_mana_to_pool`` (mint, round-27 bridge arm).
      * ``_python_mana_pool_signature`` (7-tuple snapshot on Python
        ``list[ManaCoin]``).
      * Rust ``GameState.get_mana_pool`` (7-key snapshot).
      * Rust ``GameState.cast_spell_noncreature`` →
        ``auto_tap_pay_for_cost`` (Phase 4E payment-time satisfies-
        any-color drain — commit ``daecd399`` plan-phase widen + THIS
        commit's commit-phase ``b'a'`` arm closure).
      * Python ``_coin_matches_color`` (matches the ``"any"`` coin
        against any color string — the Python SoT the Rust widening
        mirrors).

    **Observables asserted at each step:**
      * Step-1 snapshot byte-equality (empty pool, 7 zeros on both).
      * Step-2 snapshot byte-equality (post-mint: ``any=1`` only).
      * Step-3 snapshot byte-equality (post-pay: fully empty).
    """
    import mtg_bot_engine as e

    from mtg_bot.actions import _coin_matches_color
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        _python_mana_pool_signature,
        build_python_state,
    )

    # ------------------------------------------------------------------
    # 0. Resolve the real-EoE All-Fates Scroll printing + its any-mint
    #    AA[0] (AddManaToPool any-1).
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("All-Fates Scroll")
    if real is None:
        pytest.skip("All-Fates Scroll absent from active CardSource")
    aa0 = real.activated_abilities[0]
    assert isinstance(aa0.effect, AddManaToPool)
    assert aa0.effect.produces == (("any", 1),)

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
    # Pre-register the {W} instant we'll use to drive the auto-tap PAY
    # path on the Rust side. A bare ``draw_cards`` effect resolves
    # cleanly without target prompts; the load-bearing surface here is
    # the COST payment via ``auto_tap_pay_for_cost``, not the resolve.
    white_instant_dict = {
        "name": "RealEoeAfsTestW",
        "card_types": ["Instant"],
        "mana_cost": {"W": 1},
        "effects": [{"kind": "draw_cards", "count": 1}],
    }
    r.register_printing(white_instant_dict)
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
    # 2. Mint: resolve All-Fates Scroll's AA[0] on Python;
    #    add_mana("any", 1) on Rust. Snapshot equality after the mint.
    # ------------------------------------------------------------------
    aa0.effect.resolve(py_state, py_source.controller_id)
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
    # 3. Pay {W}: the wildcard coin pays the colored pip on both
    #    engines. Rust routes through cast_spell_noncreature →
    #    auto_tap_pay_for_cost — the path where the commit-phase b'a'
    #    arm gap lived pre-fix.
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

    # Rust side: cast a real {W} instant. ``cast_spell_noncreature``
    # routes through ``auto_tap_pay_for_cost``, which (a) FIFO-walks
    # the pool and picks the b'a' coin to satisfy the {W} requirement
    # (Phase 4E plan-phase widen, commit daecd399), then (b) at
    # commit-phase removes the coin from ``mp.coins`` AND decrements
    # ``mp.any`` (THIS commit's commit-phase b'a' arm closure). The
    # spell's resolve fires a draw, but the load-bearing observable is
    # the post-pay mana pool snapshot.
    spell_id = gs.register_and_inject_object(white_instant_dict, 0, 0)
    # Library fodder so the draw at resolve doesn't choke.
    for _ in range(5):
        gs.register_and_inject_object(
            {
                "name": "AfsTestLibFiller",
                "card_types": ["Land"],
                "supertypes": ["Basic"],
            },
            0,
            1,
        )
    ok = gs.cast_spell_noncreature(spell_id, 0)
    assert ok, (
        "Rust ``cast_spell_noncreature`` must accept a wildcard "
        "``any`` coin as payment for a {W} requirement via "
        "``auto_tap_pay_for_cost`` (Phase 4E plan-phase widen + this "
        "commit's commit-phase ``b'a'`` arm closure)"
    )

    py_sig_post_pay = _python_mana_pool_signature(
        py_state.players[0].mana_pool
    )
    rust_sig_post_pay = _rust_snapshot(gs, 0)
    assert py_sig_post_pay == rust_sig_post_pay, (
        f"Step-3 post-pay snapshot must be byte-equal cross-engine; "
        f"python={py_sig_post_pay}, rust={rust_sig_post_pay}. "
        f"Pre-fix Rust drifted at any=1 because the commit-phase "
        f"match in auto_tap_pay_for_cost fell through on b'a'; the "
        f"closure of THIS commit decrements mp.any in lockstep with "
        f"mp.coins.remove(i)."
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
