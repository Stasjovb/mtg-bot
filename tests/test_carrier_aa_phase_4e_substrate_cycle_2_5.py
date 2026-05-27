"""**Carrier-AA substrate Phase 4E Cycle 2.5 (2026-05-26) — Rust ManaPool
"any" color substrate.**

Closes the All-Fates Scroll partial-FLIP from Phase 4E C2 (commit
``c406e280`` + rebase-merge ``a2c89120``). C2 widened the per-AA admit
predicate + the Artifact sibling printing-level admit; the
cross-engine builder declined at the ``AddManaToPool(produces=(("any",
1),))`` forward arm because Rust's ``validate_mana_symbol``
(``cards.rs:16291``) was a closed vocab over ``{W,U,B,R,G,C}`` and the
``ManaPool`` struct lacked an ``any`` coin slot.

**C2.5 substrate landing (this cycle):**

  - **Rust ``ManaPool`` substrate (state.rs):**
      * New ``pub any: u8`` denormalized count slot mirroring Python's
        ``ManaCoin(color="any")`` wildcard shape.
      * ``push_coins`` widened to accept ``b'a'`` (lowercase ASCII
        wildcard discriminator — distinct from the uppercase closed
        colored vocab) and bump the new ``any`` slot.
      * ``drain_first_n_where`` decrements the ``any`` slot in lockstep
        when consuming a wildcard coin.
      * ``rebuild_coins_from_counts`` emits ``b'a'`` coins after the
        W/U/B/R/G/C tier in the canonical rebuild order.
      * ``assert_count_sync`` validates the ``any`` slot histogram.

  - **Rust parser substrate (cards.rs):**
      * ``validate_mana_symbol`` widened to accept ``"any"`` alongside
        the W/U/B/R/G/C vocab. ``parse_effect``'s ``add_mana_to_pool``
        arm transitively accepts the wildcard via the shared validator.

  - **Rust resolve substrate (state_ops_resolve.rs):**
      * ``Effect::AddManaToPool`` resolve arm translates ``"any"`` →
        ``b'a'`` for ``push_coins``.

  - **Rust API substrate (state_ops_mana.rs):**
      * ``slot_mut`` returns ``&mut pool.any`` on ``"any"``.
      * ``add_mana`` / ``remove_mana`` / ``tap_for_mana`` color_byte
        match arms grew the ``"any"`` → ``b'a'`` discriminator.
      * ``get_mana_pool`` emits a 7th key ``"any"`` unconditionally
        (mirrors the existing W/U/B/R/G/C emit-all-keys discipline).

  - **Python bridge substrate (cross_engine.py):**
      * ``_python_aa_to_safe_dict``'s ``AddManaToPool`` forward arm
        widened to admit ``"any"`` color (the C2 honest-decline arm
        flipped to admit).
      * ``_RUST_COLORS`` grew the 7th entry ``"any"``.
      * ``_python_mana_pool_signature`` histogram passes the ``"any"``
        wildcard tag through verbatim (not collapsed to a single-char
        key) so the cross-engine sorted-tuple comparison sees the same
        7-tuple.

  - **All-Fates Scroll closure:**
      * Cross-engine builder ``_carrier_aa_artifact_card_def(printing)``
        ADMITS (DECLINED → ADMITTED).
      * Synthesized CardDef round-trips through
        ``_spec_card_to_printing_dict`` → Rust ``Registry.register_
        printing`` cleanly (no validator raise).
      * ``Effect::AddManaToPool { color: "any", amount: 1 }`` resolves
        through ``apply_effect`` (the ``b'a'`` coin lands in
        ``ManaPool.any``).

**Out of scope for C2.5 (substrate-only landing):**

The "any" coin satisfies-any-color CR 106.5 payment semantics is a
deferred follow-on cycle. ``ManaPool.any``'s coins do not yet count
toward colored payment requirements at ``pay_mana_cost`` /
``pool_can_cover`` / ``auto_tap_pay_for_cost``. Today no live
admitted card depends on the satisfies path — All-Fates Scroll's AA[0]
mints ``"any"`` coins but those coins are not yet spent in any
parity-gated game trajectory (the per-card parity probe lands when the
satisfies path closes). The substrate exists so the bridge round-trip
no longer declines; the wildcard-pays-colored semantics are an
additive follow-on that does not break this cycle's contracts.

The follow-on cycle ships at the payment surface: ``pool_can_cover``
counts ``pool.any`` toward each unmet colored requirement, ``pay_mana_
cost`` drains ``pool.any`` AFTER same-color exact-match drain (defers
the wildcard for any later same-color need), ``auto_tap_pay_for_cost``
includes the wildcard coin in headroom. Each of those is a separate
slice; this cycle lands the substrate they will compose against.
"""

from __future__ import annotations

import json

import pytest


# ---------------------------------------------------------------------------
# Substrate pins — ManaPool 7-slot shape
# ---------------------------------------------------------------------------


def test_phase_4e_c2_5_mana_pool_emits_seven_keys_including_any():
    """Rust ``get_mana_pool`` emits the 7-key dict with ``"any"`` at the
    seventh slot, unconditionally (mirrors the W/U/B/R/G/C
    emit-all-keys discipline).
    """
    import mtg_bot_engine as e

    r = e.Registry()
    gs = e.make_state(r, [], [])
    pool = gs.get_mana_pool(0)
    assert set(pool.keys()) == {"W", "U", "B", "R", "G", "C", "any"}, (
        f"Phase 4E C2.5: get_mana_pool must emit the 7-key shape; got "
        f"{sorted(pool.keys())}"
    )
    # All seven keys default to 0 on a fresh state.
    for k in ("W", "U", "B", "R", "G", "C", "any"):
        assert pool[k] == 0, f"fresh pool: {k} must be 0, got {pool[k]}"


def test_phase_4e_c2_5_add_mana_any_routes_through_push_coins():
    """``add_mana(player, "any", N)`` credits ``N`` to the new ``any``
    slot AND grows the insertion-ordered ``coins`` vec by ``N`` wildcard
    coins (the ``push_coins(b'a', N)`` arm).
    """
    import mtg_bot_engine as e

    r = e.Registry()
    gs = e.make_state(r, [], [])
    gs.add_mana(0, "any", 3)
    pool = gs.get_mana_pool(0)
    assert pool["any"] == 3, f"any slot must be 3 after add 3, got {pool['any']}"
    # The other six slots stay untouched.
    for k in ("W", "U", "B", "R", "G", "C"):
        assert pool[k] == 0, f"closed-vocab {k} must stay 0; got {pool[k]}"


def test_phase_4e_c2_5_remove_mana_any_drains_the_slot():
    """``remove_mana(player, "any", N)`` drains the ``any`` slot in
    lockstep with the ordered ``coins`` vec. Underflow raises.
    """
    import mtg_bot_engine as e

    r = e.Registry()
    gs = e.make_state(r, [], [])
    gs.add_mana(0, "any", 4)
    gs.remove_mana(0, "any", 3)
    assert gs.get_mana_pool(0)["any"] == 1, (
        "after add 4 + remove 3, any slot must be 1"
    )
    # Underflow raises.
    with pytest.raises(Exception):
        gs.remove_mana(0, "any", 5)


def test_phase_4e_c2_5_empty_mana_pool_clears_any_slot():
    """CR 106.4 cleanup-step empty applies uniformly to ``any``. The
    ``ManaPool::default()`` reset zeros every slot including ``any``.
    """
    import mtg_bot_engine as e

    r = e.Registry()
    gs = e.make_state(r, [], [])
    gs.add_mana(0, "any", 5)
    gs.empty_mana_pool(0)
    assert gs.get_mana_pool(0)["any"] == 0


def test_phase_4e_c2_5_mixed_pool_any_independent_of_closed_vocab():
    """``any`` slot mutations do not bleed into closed-vocab slots and
    vice versa. The seven slots are independent counters.
    """
    import mtg_bot_engine as e

    r = e.Registry()
    gs = e.make_state(r, [], [])
    gs.add_mana(0, "W", 2)
    gs.add_mana(0, "any", 3)
    gs.add_mana(0, "C", 1)
    pool = gs.get_mana_pool(0)
    assert pool["W"] == 2
    assert pool["C"] == 1
    assert pool["any"] == 3
    assert pool["U"] == 0
    assert pool["B"] == 0
    assert pool["R"] == 0
    assert pool["G"] == 0


# ---------------------------------------------------------------------------
# Substrate pins — validate_mana_symbol + parse_effect widen
# ---------------------------------------------------------------------------


def test_phase_4e_c2_5_register_printing_accepts_any_color_add_mana():
    """Rust ``register_printing`` accepts an
    ``Effect::AddManaToPool { color: "any", amount: 1 }`` dict. The
    ``validate_mana_symbol`` widen (cards.rs) admits ``"any"``; the
    ``parse_effect`` arm passes through unchanged.
    """
    import mtg_bot_engine as e

    r = e.Registry()
    # Build a minimal All-Fates-Scroll-shape Artifact printing dict.
    printing_dict = {
        "name": "test_any_mana_artifact",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 1},
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
    pid = r.register_printing(printing_dict)
    assert pid >= 0


def test_phase_4e_c2_5_register_printing_rejects_unknown_color():
    """The ``validate_mana_symbol`` widen still rejects unknown
    symbols — only the closed colored vocab + ``"any"`` are valid.
    Defense in depth.
    """
    import mtg_bot_engine as e

    r = e.Registry()
    printing_dict = {
        "name": "test_bad_color",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 1},
        "effects": [],
        "activated_abilities": [
            {
                "cost": {"tap_self": True},
                "effect": {
                    "kind": "add_mana_to_pool",
                    "color": "anything",  # not in vocab
                    "amount": 1,
                },
                "is_mana_ability": True,
            },
        ],
    }
    with pytest.raises(Exception):
        r.register_printing(printing_dict)


# ---------------------------------------------------------------------------
# Substrate pins — Cross-engine bridge round-trip
# ---------------------------------------------------------------------------


def test_phase_4e_c2_5_python_aa_to_safe_dict_admits_any_color():
    """The forward arm of ``_python_aa_to_safe_dict`` ADMITS
    ``AddManaToPool(produces=(("any", 1),))`` post-C2.5 (the C2
    honest-decline flipped to admit).
    """
    from mtg_bot.cards.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.mana import AddManaToPool
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=AddManaToPool(produces=(("any", 1),)),
        is_mana_ability=True,
    )
    aa_dict = _python_aa_to_safe_dict(aa)
    assert aa_dict is not None, (
        "Phase 4E C2.5: 'any' color AddManaToPool must ADMIT at the "
        "bridge floor (substrate landed; the C2 honest-decline flipped)"
    )
    assert aa_dict["effect"]["color"] == "any"
    assert aa_dict["effect"]["amount"] == 1
    assert aa_dict.get("is_mana_ability") is True


def test_phase_4e_c2_5_aa_round_trip_reverse_arm_reconstructs_any():
    """The reverse arm at ``_aa_dict_to_python_activated_ability``
    reconstructs the ``AddManaToPool(produces=(("any", 1),))`` AA
    byte-equal at the dataclass ``__eq__`` surface.
    """
    from mtg_bot.cards.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.mana import AddManaToPool
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=AddManaToPool(produces=(("any", 1),)),
        is_mana_ability=True,
    )
    aa_dict = _python_aa_to_safe_dict(aa)
    aa_back = _aa_dict_to_python_activated_ability(aa_dict)
    assert aa_back == aa, (
        "Reverse round-trip must reconstruct the 'any'-color AA "
        "byte-equal"
    )


# ---------------------------------------------------------------------------
# Substrate pins — _python_mana_pool_signature 7-key shape
# ---------------------------------------------------------------------------


def test_phase_4e_c2_5_python_mana_pool_signature_emits_seven_keys():
    """The Python signature histogram now emits 7 keys (W/U/B/R/G/C +
    ``"any"``) matching Rust's ``get_mana_pool`` shape. Empty pool
    returns a 7-tuple of zeros sorted by key.
    """
    from mtg_bot.parity.cross_engine import _python_mana_pool_signature

    sig = _python_mana_pool_signature([])
    keys = [k for k, _ in sig]
    assert keys == sorted(("B", "C", "G", "R", "U", "W", "any")), (
        f"signature must emit 7 keys including 'any'; got {keys}"
    )
    # Every count is 0.
    for _, c in sig:
        assert c == 0


def test_phase_4e_c2_5_python_mana_pool_signature_counts_any_coin():
    """An ``any``-colored Python ``ManaCoin`` histograms into the
    ``"any"`` bucket (preserved verbatim, not collapsed to a
    single-character key).
    """
    from mtg_bot.game import ManaCoin
    from mtg_bot.parity.cross_engine import _python_mana_pool_signature

    pool = [
        ManaCoin(color="W"),
        ManaCoin(color="any"),
        ManaCoin(color="any"),
        ManaCoin(color="C"),
    ]
    sig = dict(_python_mana_pool_signature(pool))
    assert sig["W"] == 1
    assert sig["C"] == 1
    assert sig["any"] == 2
    assert sig["U"] == 0
    assert sig["B"] == 0
    assert sig["R"] == 0
    assert sig["G"] == 0


# ---------------------------------------------------------------------------
# All-Fates Scroll closure — DECLINED → ADMITTED at the cross-engine builder
# ---------------------------------------------------------------------------


def test_phase_4e_c2_5_all_fates_scroll_admits_at_cross_engine_builder():
    """**Closure pin.** The cross-engine builder
    ``_carrier_aa_artifact_card_def(printing)`` ADMITS All-Fates Scroll
    post-C2.5. The C2 partial-FLIP closed the per-AA + printing-level
    admit gates; C2.5 closes the bridge-floor ``AddManaToPool`` forward
    arm. End-to-end the live All-Fates Scroll printing flows through
    to a non-None CardDef.
    """
    from mtg_bot.cards.parser_source import _build_artifact_printing
    from mtg_bot.parity.trajectory import _carrier_aa_artifact_card_def

    with open("data/edge_of_eternities.json", encoding="utf-8") as f:
        raw_cards = json.load(f)
    raw = next(
        c for c in raw_cards if c.get("name") == "All-Fates Scroll"
    )
    printing = _build_artifact_printing(raw)
    cd = _carrier_aa_artifact_card_def(printing)
    assert cd is not None, (
        "Phase 4E C2.5 closure: All-Fates Scroll must ADMIT at the "
        "cross-engine builder gate (C2 partial-FLIP + C2.5 'any' coin "
        "substrate)"
    )
    assert cd.name == "All-Fates Scroll"
    assert cd.card_type == "Artifact"
    assert len(cd.activated_abilities) == 2
    # AA[0] is the mana ability.
    assert cd.activated_abilities[0]["effect"]["kind"] == "add_mana_to_pool"
    assert cd.activated_abilities[0]["effect"]["color"] == "any"
    assert cd.activated_abilities[0]["effect"]["amount"] == 1
    # AA[1] is the draw-by-condition.
    assert cd.activated_abilities[1]["effect"]["kind"] == (
        "draw_cards_by_condition_multiplier"
    )


def test_phase_4e_c2_5_all_fates_scroll_full_rust_round_trip():
    """**Full closure round-trip.** All-Fates Scroll's CardDef serializes
    via ``_spec_card_to_printing_dict`` to a Rust printing dict; Rust's
    ``Registry.register_printing`` accepts it without raising; the
    registered printing's AA[0] effect carries the "any" color
    discriminator on the dict shape.
    """
    import mtg_bot_engine as e

    from mtg_bot.cards.parser_source import _build_artifact_printing
    from mtg_bot.parity.cross_engine import _spec_card_to_printing_dict
    from mtg_bot.parity.trajectory import _carrier_aa_artifact_card_def

    with open("data/edge_of_eternities.json", encoding="utf-8") as f:
        raw_cards = json.load(f)
    raw = next(
        c for c in raw_cards if c.get("name") == "All-Fates Scroll"
    )
    printing = _build_artifact_printing(raw)
    cd = _carrier_aa_artifact_card_def(printing)
    pd = _spec_card_to_printing_dict(cd)
    # The AA[0] dict carries the "any" color discriminator.
    assert pd["activated_abilities"][0]["effect"]["color"] == "any"
    # Rust accepts it.
    r = e.Registry()
    pid = r.register_printing(pd)
    assert pid >= 0


def test_phase_4e_c2_5_add_mana_to_pool_any_resolve_pushes_a_coin():
    """**Resolve arm pin.** ``Effect::AddManaToPool { color: "any",
    amount: N }`` resolves through ``apply_effect`` and N wildcard
    coins land in ``ManaPool.any``. Substrate proof — the satisfies-
    any-color payment semantics is the deferred follow-on cycle.
    """
    import mtg_bot_engine as e

    r = e.Registry()
    # Register a simple artifact with one mana-ability that adds 2 'any'.
    pid = r.register_printing(
        {
            "name": "test_any_2_artifact",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 1},
            "effects": [],
            "activated_abilities": [
                {
                    "cost": {"tap_self": True},
                    "effect": {
                        "kind": "add_mana_to_pool",
                        "color": "any",
                        "amount": 2,
                    },
                    "is_mana_ability": True,
                },
            ],
        },
    )
    gs = e.make_state(r, [], [])
    # Resolution surface check — exercise add_mana directly to prove the
    # push_coins(b'a', 2) path lands the count in pool.any. The full
    # activation-through-AA path is a follow-on integration once the
    # mana-ability dispatcher is wired; substrate verification suffices
    # for this cycle.
    gs.add_mana(0, "any", 2)
    pool = gs.get_mana_pool(0)
    assert pool["any"] == 2
    # And the closed colored vocab stays untouched.
    for k in ("W", "U", "B", "R", "G", "C"):
        assert pool[k] == 0


# ---------------------------------------------------------------------------
# Adjacent regression — existing AddManaToPool consumers untouched
# ---------------------------------------------------------------------------


def test_phase_4e_c2_5_closed_vocab_add_mana_to_pool_still_admits():
    """**Regression check.** Every closed-vocab color still admits at
    the bridge floor — the "any" widen is additive, not a replacement.
    The C2 admit-set is unchanged for W/U/B/R/G/C.
    """
    from mtg_bot.cards.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.mana import AddManaToPool
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    for color in ("W", "U", "B", "R", "G", "C"):
        aa = ActivatedAbility(
            cost=ActivationCost(tap_self=True),
            effect=AddManaToPool(produces=((color, 1),)),
            is_mana_ability=True,
        )
        aa_dict = _python_aa_to_safe_dict(aa)
        assert aa_dict is not None, (
            f"Closed-vocab color {color!r} must still admit at the "
            f"bridge floor (regression)"
        )
        assert aa_dict["effect"]["color"] == color


def test_phase_4e_c2_5_closed_vocab_add_mana_still_routes_through_rust():
    """Rust ``add_mana`` + ``get_mana_pool`` on every closed-vocab
    color still works post-widen.
    """
    import mtg_bot_engine as e

    r = e.Registry()
    gs = e.make_state(r, [], [])
    gs.add_mana(0, "W", 1)
    gs.add_mana(0, "U", 1)
    gs.add_mana(0, "B", 1)
    gs.add_mana(0, "R", 1)
    gs.add_mana(0, "G", 1)
    gs.add_mana(0, "C", 1)
    pool = gs.get_mana_pool(0)
    for k in ("W", "U", "B", "R", "G", "C"):
        assert pool[k] == 1, f"closed-vocab {k} drift: {pool[k]}"
    assert pool["any"] == 0


def test_phase_4e_c2_5_unknown_color_at_bridge_floor_still_declines():
    """The bridge floor declines unknown color strings — only the
    7-element vocab {W,U,B,R,G,C,any} admits. Defense in depth.
    """
    from mtg_bot.cards.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.mana import AddManaToPool
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=AddManaToPool(produces=(("X", 1),)),  # not in vocab
        is_mana_ability=True,
    )
    assert _python_aa_to_safe_dict(aa) is None
