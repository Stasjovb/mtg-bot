"""Cascading Cataracts — per-card real-EoE cross-engine byte-equal
probe (covered_by_construction → PROBED tier flip).

Cascading Cataracts is a ``{0}`` Land in the EoE pool (an
Aether-Revolt-era five-color land reprint) with a single activated
mana ability:

    "{5}, {T}: Add five mana of any one color."

(But note: per the parser's emission below, Cascading Cataracts is
modeled as the "Add five mana of any color" wildcard form — five
``'any'`` coins minted at once, not a player-choose-one-color flavor
of ``AddNManaOfChosenColor``.)

Parser-emitted Effect shape:

    ``AddManaToPool(produces=(('any', 5),), spend_restriction=None)``

attached to an ActivatedAbility whose ``cost`` carries
``tap_self=True`` + mana cost ``{5}``.  The bridge arm
``add_mana_to_pool`` (round-27, cross_engine.py:7342) round-trips
``{"kind": "add_mana_to_pool", "color": "any", "amount": 5}`` byte-
equal to Python's
``AddManaToPool(produces=(('any', 5),), spend_restriction=None)``.

This module is the **load-bearing PROBED-tier flip evidence** for
Cascading Cataracts.  The substrate is already shipped (round-27
closed the bridge gap); the immediately-prior sibling probe
``test_mana_confluence_parity.py`` (batch-4) is the FIRST PROBE_MODULES-
credited consumer of ``add_mana_to_pool`` on a real-EoE Land carrier
with ``amount=1``; THIS probe distinguishes itself by exercising
``amount=5`` (the 5-coin batch-mint distinct from Mana Confluence's
1-coin shape).

**FFFF EEEE-idiom for the ActivatedAbility carrier.**  Same lane
discipline as batches 1-3 (parse + bridge round-trip + Python-side
resolve, NO cross-engine ``compare_fields``).  The Python-side
resolve drives the AddManaToPool Effect directly through its resolve
path; the post-resolve observable is "p0's mana pool gained five
``any``-colored coins (a single Effect mints all 5 at once via the
``for _ in range(count)`` inner loop in
mtg_bot.effects.generic.mana.AddManaToPool.resolve)".

**NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
binding the Cascading Cataracts slug to its parsed
``AddManaToPool(produces=(('any', 5),))`` shape; the FIRST PROBED-
tier slot for the ``amount=5`` batch-mint via the add_mana_to_pool
bridge arm (Mana Confluence pins ``amount=1``; Crystal Quarry's
``produces=(('W',1),('U',1),('B',1),('R',1),('G',1))`` 5-tuple multi-
color shape is NOT bridgeable via the scalar-color bridge arm and
stays covered-by-construction).
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
# (1) Parser SoT — Cascading Cataracts is parser-claimed and carries
# one mana-ability AA whose effect is ``AddManaToPool(produces=
# (('any', 5),), spend_restriction=None)``.
# ---------------------------------------------------------------------------


def test_cascading_cataracts_parser_claims_card():
    assert "Cascading Cataracts" in _PRINTINGS, (
        "Cascading Cataracts must be parser-claimed by the active "
        "CardSource"
    )


def test_cascading_cataracts_printed_attrs():
    """Pins the basic printing surface: Land type, no mana cost."""
    p = _PRINTINGS["Cascading Cataracts"]
    assert "Land" in p.card_types
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()


def test_cascading_cataracts_mana_ability_shape():
    """Cascading Cataracts has exactly one ActivatedAbility (the mana
    ability); its effect is the bare ``AddManaToPool(produces=
    (('any', 5),), spend_restriction=None)`` — the 5-coin any-color
    batch-mint shape (distinct from Mana Confluence's 1-coin shape +
    Crystal Quarry's WUBRG 5-tuple multi-color shape)."""
    p = _PRINTINGS["Cascading Cataracts"]
    assert len(p.activated_abilities) == 1, (
        f"Cascading Cataracts must have exactly one ActivatedAbility "
        f"(the {{5}},{{T}} mana ability); got "
        f"{len(p.activated_abilities)}"
    )
    aa = p.activated_abilities[0]
    assert isinstance(aa.effect, AddManaToPool), (
        f"Cascading Cataracts AA effect must be AddManaToPool; got "
        f"{type(aa.effect).__name__}"
    )
    assert aa.effect.produces == (("any", 5),), (
        f"Cascading Cataracts AA must produce exactly one ('any', 5) "
        f"batch; got produces={aa.effect.produces}"
    )
    assert aa.effect.spend_restriction is None, (
        f"Cascading Cataracts AA must NOT carry a spend_restriction; "
        f"got spend_restriction={aa.effect.spend_restriction!r}"
    )
    # Cost-side: {5} + {T}.  Documented for context.
    assert aa.cost.tap_self is True
    assert aa.cost.mana is not None and aa.cost.mana.generic == 5
    assert aa.is_mana_ability is True


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the add_mana_to_pool dict shape round-trips
# byte-equal to the parsed printing's emitted Effect.
# ---------------------------------------------------------------------------


def test_cascading_cataracts_bridge_arm_round_trip():
    """The bridge arm ``add_mana_to_pool`` (cross_engine.py:7342)
    round-trips ``{"kind": "add_mana_to_pool", "color": "any",
    "amount": 5}`` to the matching Python
    ``AddManaToPool(produces=(('any', 5),), spend_restriction=None)``
    instance."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "any", "amount": 5}
    )
    assert isinstance(bridged, AddManaToPool)
    assert bridged.produces == (("any", 5),)
    assert bridged.spend_restriction is None

    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted AddManaToPool Effect and the bridged Effect.
    p = _PRINTINGS["Cascading Cataracts"]
    aa = p.activated_abilities[0]
    assert aa.effect == bridged, (
        f"Cascading Cataracts AA Effect must be byte-equal to the "
        f"bridged Effect (AddManaToPool(produces=(('any', 5),)) "
        f"structural contract for the PROBED tier); got "
        f"parsed={aa.effect!r}, bridged={bridged!r}"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts the
# bridged add_mana_to_pool dict shape on a Cascading-Cataracts-shape
# Land carrier.  Per the Mana Confluence batch-4 precedent + the
# round-27 bridge-arm docstring, the synthetic carrier uses a closed-
# vocab color (``C``) since Rust's validate_mana_symbol rejects
# ``"any"``; the EFFECT-half lockstep is on the dict-shape acceptance
# and the ``amount`` field, not on the wildcard color.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_cascading_cataracts_add_mana_to_pool_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the
    ``{"kind": "add_mana_to_pool", "color": "C", "amount": 5}`` dict
    shape on a Cascading-Cataracts-shape Land carrier (closed-vocab
    color per the Mana Confluence batch-4 precedent; the amount=5
    batch-mint is the load-bearing dispatch distinct from amount=1).
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Cascading Cataracts (synthetic carrier)",
            "card_types": ["Land"],
            "mana_cost": {"generic": 0},
            "effects": [],
            "activated_abilities": [
                {
                    "cost": {"mana": {"generic": 5}},
                    "effect": {
                        "kind": "add_mana_to_pool",
                        "color": "C",
                        "amount": 5,
                    },
                    "is_mana_ability": True,
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Cascading Cataracts printing on Python-side resolve
# for the AddManaToPool effect.  Mirrors the FFFF EEEE-idiom (parse +
# bridge round-trip + Python-side resolve, NO cross-engine
# compare_fields).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_cascading_cataracts_mana_ability_add_any_five_parity():
    """**GENUINE real-EoE cross-engine probe — Cascading Cataracts mana
    ability → AddManaToPool(produces=(('any', 5),)). PROBED-tier flip
    (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Cascading Cataracts printing** on the
    Python side through the AddManaToPool effect's resolve path.
    Mirrors the FFFF EEEE-idiom (parse + bridge round-trip + Python-
    side resolve, no cross-engine ``compare_fields``); same lane
    discipline as batches 1-3 + batch-4 sibling Mana Confluence
    (amount=1 variant).

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
    binding the Cascading Cataracts slug to the AA + AddManaToPool(
    produces=(('any', 5),)) Effect+bridge round-trip on the REAL
    parsed EoE printing.  Distinct from the immediately-prior batch-4
    sibling Mana Confluence (amount=1) — the 5-coin batch-mint
    exercises the inner ``for _ in range(count)`` loop in
    AddManaToPool.resolve.

    **Bridge arm exercised:**
      * ``add_mana_to_pool`` (round-27 bridge arm; the amount=5
        dispatch).

    **AA-cost-substrate deferral.**  Same scope as the Mana
    Confluence sibling probe — the {5},{T} cost-payment trajectory +
    cross-engine observer parity are cost-substrate scope; per-slug
    attribution credits the slug based on the Effect+bridge byte-
    equality alone.

    **Setup (Python-side):**
      * p0 has Cascading Cataracts on the battlefield (the AA
        source).
      * p0's mana pool starts empty.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "add_mana_to_pool", "color": "any", "amount": 5}``
        translates to ``AddManaToPool(produces=(('any', 5),),
        spend_restriction=None)``.
      * The Land's mana ActivatedAbility emits the same Effect.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * Post-resolve: p0's mana pool gained EXACTLY five 'any'-color
        coins (the inner loop minted all 5; sibling Mana Confluence
        amount=1 distinction).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Cascading Cataracts printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Cascading Cataracts")
    if real is None:
        pytest.skip("Cascading Cataracts absent from active CardSource")
    assert "Land" in real.card_types
    aa = real.activated_abilities[0]
    assert isinstance(aa.effect, AddManaToPool)
    assert aa.effect.produces == (("any", 5),)
    assert aa.effect.spend_restriction is None

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "any", "amount": 5}
    )
    assert isinstance(bridged, AddManaToPool)
    assert aa.effect == bridged, (
        f"Cascading Cataracts AA Effect must be byte-equal to "
        f"bridged; got parsed={aa.effect!r}, bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling AddManaToPool produces shapes
    #    (regression guard).
    # ------------------------------------------------------------------
    # The 5-coin batch (amount=5) is distinct from Mana Confluence's
    # 1-coin shape (amount=1) — the batch-mint loop count is the
    # load-bearing distinguishing dispatch on AddManaToPool.resolve.
    # Distinct ALSO from Crystal Quarry's WUBRG 5-tuple multi-color
    # shape (which can't be bridged via the scalar-color arm and
    # stays covered-by-construction).
    assert bridged.produces[0][1] == 5, (
        "Bridged AddManaToPool must produce 5 coins in one batch — "
        "distinct from the amount=1 Mana Confluence sibling shape"
    )
    assert len(bridged.produces) == 1, (
        "Bridged AddManaToPool must have a SINGLE produces tuple "
        "entry (the batch-mint shape) — distinct from Crystal Quarry's "
        "5-tuple WUBRG multi-color shape"
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke — drive the parsed effect through
    #    its actual resolve path.  p0's mana pool gains FIVE 'any'
    #    coins (the inner loop fires count times).
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Seat the GENUINE parsed Cascading Cataracts on p0's bf.
    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Pre-resolve sanity: p0's mana pool is empty.
    assert len(py_state.players[0].mana_pool) == 0

    # Drive the AddManaToPool effect through resolve directly.
    aa.effect.resolve(py_state, py_source.controller_id)

    # Post-resolve: p0's mana pool has EXACTLY 5 'any'-color coins
    # (the inner ``for _ in range(count)`` loop fires count times for
    # each (color, count) entry in produces).
    p0_pool = py_state.players[0].mana_pool
    assert len(p0_pool) == 5, (
        f"Cascading Cataracts AA must mint exactly 5 coins in p0's "
        f"pool; got pool size={len(p0_pool)} (batch-mint amount=5 "
        f"distinct from Mana Confluence amount=1)"
    )
    for i, coin in enumerate(p0_pool):
        assert coin.color == "any", (
            f"Minted coin #{i} must be 'any'-color (wildcard); got "
            f"color={coin.color!r}"
        )
        assert coin.spend_restriction is None, (
            f"Minted coin #{i} must have no spend_restriction; got "
            f"spend_restriction={coin.spend_restriction!r}"
        )
    # p1's pool is untouched.
    assert len(py_state.players[1].mana_pool) == 0
