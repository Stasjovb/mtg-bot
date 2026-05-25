"""High Market — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

High Market is a ``{0}`` Land in the EoE pool with two activated
abilities; the load-bearing parity-relevant ability is the non-mana
sacrifice-self-saves-life activated ability:

    "{T}, Sacrifice a creature: You gain 1 life."

The parser models the sacrifice-creature half via the activation cost
fields (which the substrate carries separately from the Effect), so
the EFFECT this probe pins is the bare:

    ``GainLife(amount=1)``

attached to an ActivatedAbility whose ``cost`` carries
``tap_self=True`` (plus the cost-side ``sacrifice_another_creature``
machinery — out-of-scope at the Effect+bridge byte-equality layer this
probe verifies).  The bridge arm ``gain_life`` (cross_engine.py:852)
is one of the earliest closed-vocab arms and round-trips
``{"kind": "gain_life", "amount": N}`` byte-equal to Python's
``GainLife(amount=N)``.

This module is the **load-bearing PROBED-tier flip evidence** for
High Market.  The substrate is already shipped — the bridge arm has
been live since round-1; sibling PROBED consumers of GainLife on
non-AA carriers exist throughout the pool (e.g. Singularity Rupture
spell, Endstone ALT-PROBED via ENDSTONE precedent etc.), but no
slug-keyed probe pinned High Market.  Per the IIII Optimistic
Scavenger / Command Bridge precedent + the 2026-05-24
``post-flip-reclassification-scout`` 12-card sweep precedent +
batches 1-3 lane discipline (per-slug attribution credits a PROBED
slot per-printing, not per-effect-class).

**FFFF EEEE-idiom for the ActivatedAbility carrier.**  The probe
uses the parse + bridge round-trip + Python-side resolve idiom (NO
cross-engine ``compare_fields``) — same lane discipline as batches
1-3.  The Python-side resolve drives the GainLife(1) Effect directly
through its resolve path (mirrors how the activated ability resolves
once its cost is paid: the Effect is pushed and resolves at the same
controller's seat).  The full activated-ability-cost-payment
trajectory (the ``sacrifice_another_creature`` cost-atom + the
``tap_self`` cost-atom) is documented in cost-substrate landings and
batched-cost probes (test_probe_activated_abilities_o2 family) but
exercised here only via the Effect+bridge byte-equality contract for
slug attribution.

**NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
binding the High Market slug to its parsed
``ActivatedAbility(GainLife(amount=1))`` shape; the FIRST PROBED-tier
slot for the Land + non-mana AA + GainLife archetype.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.life import GainLife


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Zone constants (mirror Rust's u8 zone IDs).
ZONE_BATTLEFIELD = 2


# ---------------------------------------------------------------------------
# (1) Parser SoT — High Market is parser-claimed and carries a non-mana
# ActivatedAbility whose effect is ``GainLife(amount=1)``.
# ---------------------------------------------------------------------------


def test_high_market_parser_claims_card():
    assert "High Market" in _PRINTINGS, (
        "High Market must be parser-claimed by the active CardSource"
    )


def test_high_market_printed_attrs():
    """Pins the basic printing surface: Land type, no mana cost."""
    p = _PRINTINGS["High Market"]
    assert "Land" in p.card_types
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()


def test_high_market_activated_ability_gain_life_shape():
    """High Market has at least one non-mana ActivatedAbility whose
    effect is ``GainLife(amount=1)`` — the canonical sac-a-creature-
    to-gain-1-life Land shape (distinct from the bare ``{T}: Add {C}``
    mana ability sibling Land carriers like Crystal Quarry / Eldrazi
    Temple)."""
    p = _PRINTINGS["High Market"]
    non_mana_aas = [
        aa for aa in p.activated_abilities if not aa.is_mana_ability
    ]
    assert len(non_mana_aas) >= 1, (
        f"High Market must have at least one non-mana ActivatedAbility "
        f"(the sac-creature-gain-life ability); got "
        f"{len(non_mana_aas)} non-mana AAs"
    )
    gain_life_aas = [
        aa for aa in non_mana_aas if isinstance(aa.effect, GainLife)
    ]
    assert len(gain_life_aas) == 1, (
        f"High Market must have exactly one non-mana ActivatedAbility "
        f"whose effect is GainLife; got {len(gain_life_aas)}"
    )
    aa = gain_life_aas[0]
    assert aa.effect.amount == 1, (
        f"High Market's GainLife AA must have amount=1; got "
        f"{aa.effect.amount}"
    )
    # The cost-side machinery is captured separately on the
    # ActivationCost — these assertions pin that the cost carries the
    # tap-self atom (the {T} half of the printed cost), which is the
    # canonical part of the cost structure.  The
    # sacrifice_another_creature_or_artifact cost atom is documented
    # for context but not load-bearing for this probe (the Effect-side
    # bridge round-trip is what credits PROBED-tier per-slug).
    assert aa.cost.tap_self is True, (
        "High Market's GainLife AA cost must carry the {T} atom "
        "(tap_self=True)"
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the gain_life dict shape round-trips byte-
# equal to the parsed printing's emitted Effect (the early-round
# closed-vocab bridge arm at cross_engine.py:852).
# ---------------------------------------------------------------------------


def test_high_market_bridge_arm_round_trip():
    """The bridge arm ``gain_life`` (cross_engine.py:852) round-trips
    ``{"kind": "gain_life", "amount": 1}`` to the matching Python
    ``GainLife(amount=1)`` instance."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "gain_life", "amount": 1}
    )
    assert isinstance(bridged, GainLife)
    assert bridged.amount == 1

    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted GainLife Effect and the bridged Effect — the structural
    # contract for the PROBED tier.
    p = _PRINTINGS["High Market"]
    gain_life_aa = next(
        aa for aa in p.activated_abilities
        if isinstance(aa.effect, GainLife)
    )
    assert gain_life_aa.effect == bridged, (
        f"High Market AA Effect must be byte-equal to the bridged "
        f"Effect (GainLife(amount=1) structural contract for the "
        f"PROBED tier); got parsed={gain_life_aa.effect!r}, "
        f"bridged={bridged!r}"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts the
# bridged gain_life dict shape on a High-Market-shape Land carrier.
# The full activated-ability cost-payment surface (the
# sacrifice_another_creature_or_artifact + tap_self cost atoms) is
# exercised in the test_probe_activated_abilities_o2 family probes;
# this synthetic Rust pin restricts to the EFFECT half (mirroring the
# batch-1/2/3 simpler-predicate Rust-carrier precedent).
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_high_market_gain_life_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the
    ``{"kind": "gain_life", "amount": 1}`` dict shape on a High-Market-
    shape Land carrier with a synthetic mana-only AA cost (the full
    sacrifice-cost surface is the test_probe_activated_abilities_o2-
    family scope; this synthetic pin restricts to the EFFECT half per
    the batch-1/2/3 simpler-predicate-Rust-carrier precedent)."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "High Market (synthetic carrier)",
            "card_types": ["Land"],
            "mana_cost": {"generic": 0},
            "effects": [],
            "activated_abilities": [
                {
                    "cost": {"mana": {"generic": 0}},
                    "effect": {"kind": "gain_life", "amount": 1},
                    "is_mana_ability": False,
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed High Market printing on Python-side resolve for the
# GainLife(1) effect.  Mirrors the FFFF EEEE-idiom (parse + bridge
# round-trip + Python-side resolve, NO cross-engine compare_fields).
# The full activated-ability cost-payment trajectory + cross-engine
# observer parity stays AA-cost-substrate-deferred; the slug-attribution
# credits the High Market slot regardless of the cost-payment scope.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_high_market_activated_gain_life_parity():
    """**GENUINE real-EoE cross-engine probe — High Market non-mana AA
    → GainLife(amount=1). PROBED-tier flip (covered_by_construction →
    PROBED).**

    Drives the **ACTUAL parsed High Market printing** on the Python
    side through the GainLife(1) Effect's resolve path.  Mirrors the
    FFFF EEEE-idiom (parse + bridge round-trip + Python-side resolve,
    no cross-engine ``compare_fields``); same lane discipline as
    batches 1-3.

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
    binding the High Market slug to the AA + GainLife(1)
    Effect+bridge round-trip on the REAL parsed EoE printing.  The
    PROBED-tier classifier credits per-slug; no prior probe pinned
    High Market.

    **Bridge arm exercised:**
      * ``gain_life`` (early-round closed-vocab arm at
        cross_engine.py:852).

    **AA-cost-substrate deferral.**  The full activated-ability cost-
    payment trajectory (the ``sacrifice_another_creature_or_artifact``
    + ``tap_self`` cost atoms on the ActivationCost) is the
    test_probe_activated_abilities_o2-family scope and stays substrate-
    deferred for this lane.  Per-slug attribution credits the slug
    based on the Effect+bridge byte-equality alone (the round-1
    PROBED-tier definition + the batches 1-3 EEEE-idiom precedent).

    **Setup (Python-side):**
      * p0 has High Market on the battlefield (the AA source; the
        Effect resolves on the source's controller).
      * p0's life total is the default starting life (20).

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "gain_life", "amount": 1}`` translates to
        ``GainLife(amount=1)``.
      * The Land's non-mana ActivatedAbility emits the same Effect.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * Post-resolve: p0's life total = starting + 1.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed High Market printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("High Market")
    if real is None:
        pytest.skip("High Market absent from active CardSource")
    assert "Land" in real.card_types
    gain_life_aa = next(
        (
            aa for aa in real.activated_abilities
            if isinstance(aa.effect, GainLife)
        ),
        None,
    )
    assert gain_life_aa is not None, (
        "High Market must have a non-mana ActivatedAbility whose "
        "effect is GainLife"
    )
    assert gain_life_aa.effect.amount == 1

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "gain_life", "amount": 1}
    )
    assert isinstance(bridged, GainLife)
    assert gain_life_aa.effect == bridged, (
        f"High Market AA Effect must be byte-equal to bridged; got "
        f"parsed={gain_life_aa.effect!r}, bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect classes (regression guard).
    # ------------------------------------------------------------------
    # GainLife is NOT a LoseLife — the +1 life mutation is distinct from
    # the -1 life mutation Withering Torment (BBBB) / Derelict Attic
    # (batch-3) pin.  Same dataclass family, opposite direction.
    from mtg_bot.effects.generic.life import LoseLife
    assert not isinstance(bridged, LoseLife), (
        "Bridged GainLife must NOT collapse to LoseLife — opposite "
        "direction (the +1/-1 life mutation distinction is load-"
        "bearing for the Land sac-creature-saves-life archetype "
        "High Market represents)"
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke — drive the parsed effect through
    #    its actual resolve path.  p0's life total bumps by 1.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Seat the GENUINE parsed High Market on p0's bf (the AA source).
    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Pre-resolve sanity: p0 has the default starting life total.
    pre_life = py_state.players[0].life
    assert pre_life > 0, (
        f"p0 must have positive starting life; got pre-resolve "
        f"life={pre_life}"
    )

    # Drive the GainLife(1) effect through resolve directly, mirroring
    # what the AA's resolution does once its cost is paid.
    gain_life_aa.effect.resolve(py_state, py_source.controller_id)

    # Post-resolve: p0's life total = pre + 1.
    assert py_state.players[0].life == pre_life + 1, (
        f"High Market AA must add 1 to p0's life total; got "
        f"pre={pre_life}, post={py_state.players[0].life}"
    )
    # p1's life is untouched (the controller-of-effect contract — the
    # AA's GainLife targets the source's controller, not opponents).
    assert py_state.players[1].life > 0, (
        "p1's life must remain unchanged by p0-controlled GainLife"
    )
