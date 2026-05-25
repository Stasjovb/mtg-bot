"""Eldrazi Temple — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

Eldrazi Temple is a ``{0}`` Land in the EoE pool (the classic Battle
for Zendikar / Rise of the Eldrazi land reprint) with two activated
mana abilities:

    "{T}: Add {C}.
     {T}: Add {C}{C}. Spend this mana only to cast colorless Eldrazi
     spells or activate abilities of colorless Eldrazi."

The load-bearing AA for this probe is the **first** mana ability —
the bare ``{T}: Add {C}`` shape — distinct from the second AA's
spend-restricted ``{C}{C}`` Eldrazi-restricted shape.  Parser-emitted
Effect shape for AA[0]:

    ``AddManaToPool(produces=(('C', 1),), spend_restriction=None)``

attached to an ActivatedAbility whose ``cost`` carries
``tap_self=True`` and no mana cost.  The bridge arm
``add_mana_to_pool`` round-trips ``{"kind": "add_mana_to_pool",
"color": "C", "amount": 1}`` byte-equal to Python's
``AddManaToPool(produces=(('C', 1),), spend_restriction=None)``.

This module is the **load-bearing PROBED-tier flip evidence** for
Eldrazi Temple.  Templates on the immediately-prior batch-4 siblings
Mana Confluence + Gemstone Caverns (any-1 variants) + Cascading
Cataracts (any-5 variant); THIS probe distinguishes itself by
exercising the **'C' (colorless) color** instead of 'any' — the
first PROBED-tier slot for the 'C'-color produces tuple via the
add_mana_to_pool bridge arm.

**FFFF EEEE-idiom.**  Same lane discipline as batches 1-3 + the
sibling batch-4 probes (parse + bridge round-trip + Python-side
resolve, NO cross-engine ``compare_fields``).

**NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
binding the Eldrazi Temple slug to its parsed AA[0] (the bare
``{T}: Add {C}`` mana ability).  Distinct from the batch-4 sibling
Land probes that pin ``'any'`` produces — Eldrazi Temple AA[0] pins
``'C'`` colorless produces (distinct dispatch on the AddManaToPool
``produces`` tuple's color field).

**AA[1] deferral.**  Eldrazi Temple's second mana ability emits
``AddManaToPool(produces=(('C', 2),), spend_restriction=
'colorless_eldrazi')``.  The bridge arm currently maps to
``spend_restriction=None`` (the bridge does not pass through
``spend_restriction``) — the ``colorless_eldrazi`` restriction is a
documented spend-restriction-tagging extension out of scope for the
bare bridge round-trip.  Per the IIII / HHHH "covered carrier with
spend-restriction rider" implicit drop precedent + the batch-2
Wickerfolk Thresher / batch-3 Cosmogrand Zenith narrow-pin
half-coverage precedent, the AA[0] alone carries the load-bearing
slug-attribution flip; per-slug attribution credits Eldrazi Temple
regardless of the AA[1] half-coverage.
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
# (1) Parser SoT — Eldrazi Temple is parser-claimed and carries two
# mana-ability AAs; AA[0] is the bare ``AddManaToPool(produces=
# (('C', 1),), spend_restriction=None)``.
# ---------------------------------------------------------------------------


def test_eldrazi_temple_parser_claims_card():
    assert "Eldrazi Temple" in _PRINTINGS, (
        "Eldrazi Temple must be parser-claimed by the active "
        "CardSource"
    )


def test_eldrazi_temple_printed_attrs():
    """Pins the basic printing surface: Land type, no mana cost."""
    p = _PRINTINGS["Eldrazi Temple"]
    assert "Land" in p.card_types
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()


def test_eldrazi_temple_mana_abilities_shape():
    """Eldrazi Temple has exactly two ActivatedAbilities; AA[0] is the
    bare ``{T}: Add {C}`` (this probe's load-bearing AA); AA[1] is the
    spend-restricted ``{T}: Add {C}{C}. Spend this mana only to cast
    colorless Eldrazi spells...`` ability (covered by the parser SoT
    only — per the AA[1] deferral docstring above)."""
    p = _PRINTINGS["Eldrazi Temple"]
    assert len(p.activated_abilities) == 2, (
        f"Eldrazi Temple must have exactly two ActivatedAbilities "
        f"(AA[0]: {{T}}:{{C}}, AA[1]: {{T}}:{{C}}{{C}} Eldrazi-"
        f"restricted); got {len(p.activated_abilities)}"
    )
    aa0 = p.activated_abilities[0]
    assert isinstance(aa0.effect, AddManaToPool)
    assert aa0.effect.produces == (("C", 1),), (
        f"AA[0] must produce exactly one ('C', 1) colorless coin; got "
        f"produces={aa0.effect.produces}"
    )
    assert aa0.effect.spend_restriction is None, (
        f"AA[0] must NOT carry a spend_restriction; got "
        f"spend_restriction={aa0.effect.spend_restriction!r}"
    )
    assert aa0.cost.tap_self is True
    assert aa0.is_mana_ability is True
    # AA[1] sanity (documented for context per the AA[1] deferral
    # docstring — the spend-restricted half is not load-bearing for
    # this probe).
    aa1 = p.activated_abilities[1]
    assert isinstance(aa1.effect, AddManaToPool)
    assert aa1.effect.produces == (("C", 2),), (
        f"AA[1] must produce ('C', 2) colorless batch; got "
        f"produces={aa1.effect.produces}"
    )
    assert aa1.effect.spend_restriction == "colorless_eldrazi", (
        f"AA[1] must carry spend_restriction='colorless_eldrazi'; "
        f"got spend_restriction={aa1.effect.spend_restriction!r}"
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the add_mana_to_pool dict shape (with 'C'
# color) round-trips byte-equal to the parsed printing's AA[0] emitted
# Effect.
# ---------------------------------------------------------------------------


def test_eldrazi_temple_aa0_bridge_arm_round_trip():
    """The bridge arm ``add_mana_to_pool`` (cross_engine.py:7342)
    round-trips ``{"kind": "add_mana_to_pool", "color": "C",
    "amount": 1}`` to the matching Python ``AddManaToPool(produces=
    (('C', 1),), spend_restriction=None)`` instance.  The 'C' color
    (colorless) is the distinguishing dispatch from the sibling
    batch-4 'any'-color Land probes."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "C", "amount": 1}
    )
    assert isinstance(bridged, AddManaToPool)
    assert bridged.produces == (("C", 1),)
    assert bridged.spend_restriction is None

    # Effect-level byte-equality between the parsed real-EoE printing's
    # AA[0] emitted Effect and the bridged Effect.
    p = _PRINTINGS["Eldrazi Temple"]
    aa0 = p.activated_abilities[0]
    assert aa0.effect == bridged, (
        f"Eldrazi Temple AA[0] Effect must be byte-equal to the "
        f"bridged Effect (AddManaToPool(produces=(('C', 1),)) "
        f"structural contract for the PROBED tier); got "
        f"parsed={aa0.effect!r}, bridged={bridged!r}"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts the
# bridged add_mana_to_pool dict shape with 'C' color (Rust's
# validate_mana_symbol natively accepts 'C', so no closed-vocab
# translation needed here — distinct from the Mana Confluence /
# Cascading Cataracts / Gemstone Caverns siblings where 'any' had to
# be coerced to 'C' on the synthetic side).
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_eldrazi_temple_add_mana_to_pool_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the
    ``{"kind": "add_mana_to_pool", "color": "C", "amount": 1}`` dict
    shape on an Eldrazi-Temple-shape Land carrier — direct closed-
    vocab dispatch (no 'any' → 'C' coercion needed, distinct from the
    batch-4 sibling Land probes)."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Eldrazi Temple (synthetic carrier)",
            "card_types": ["Land"],
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
# ACTUAL parsed Eldrazi Temple printing's AA[0] on Python-side
# resolve.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_eldrazi_temple_mana_ability_aa0_colorless_parity():
    """**GENUINE real-EoE cross-engine probe — Eldrazi Temple AA[0]
    ({T}: Add {C}) → AddManaToPool(produces=(('C', 1),)). PROBED-tier
    flip (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Eldrazi Temple printing's AA[0]** on
    the Python side through the AddManaToPool effect's resolve path.
    Same EEEE-idiom + cost-substrate deferral as the sibling batch-4
    probes; the distinguishing dispatch here is the **'C' (colorless)
    color** in the produces tuple (the bare bridge round-trip
    exercises Rust's native colorless-mana validation natively, no
    'any' → 'C' coercion).

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
    binding the Eldrazi Temple slug to AA[0]'s AddManaToPool(
    produces=(('C', 1),)) Effect+bridge round-trip on the REAL parsed
    EoE printing.  The FIRST PROBED-tier slot for the 'C' (colorless)
    color via the add_mana_to_pool bridge arm.

    **AA[1] half-coverage scope.**  Eldrazi Temple's second mana
    ability (AA[1], the ``{T}: Add {C}{C}. Spend this mana only to
    cast colorless Eldrazi spells...`` form) emits ``AddManaToPool(
    produces=(('C', 2),), spend_restriction='colorless_eldrazi')`` —
    the spend_restriction='colorless_eldrazi' rider is NOT passed
    through the current bridge arm (the bridge constructs
    ``spend_restriction=None`` regardless), so AA[1] would byte-
    fail-bridge.  Per the batch-2 Wickerfolk Thresher / batch-3
    Cosmogrand Zenith narrow-pin half-coverage precedent + the IIII /
    HHHH "covered carrier with spend-restriction rider" implicit drop
    precedent, AA[0] alone carries the load-bearing slug-attribution
    flip.

    **Bridge arm exercised:**
      * ``add_mana_to_pool`` (round-27 bridge arm; the 'C'-color
        dispatch).

    **Setup (Python-side):**
      * p0 has Eldrazi Temple on the battlefield (the AA source).
      * p0's mana pool starts empty.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "add_mana_to_pool", "color": "C", "amount": 1}``
        translates to ``AddManaToPool(produces=(('C', 1),),
        spend_restriction=None)``.
      * The Land's AA[0] emits the same Effect.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * Post-resolve: p0's mana pool gained exactly one ManaCoin with
        color='C' (colorless, NOT 'any' wildcard) and
        spend_restriction=None.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Eldrazi Temple printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Eldrazi Temple")
    if real is None:
        pytest.skip("Eldrazi Temple absent from active CardSource")
    assert "Land" in real.card_types
    aa0 = real.activated_abilities[0]
    assert isinstance(aa0.effect, AddManaToPool)
    assert aa0.effect.produces == (("C", 1),)
    assert aa0.effect.spend_restriction is None

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "C", "amount": 1}
    )
    assert isinstance(bridged, AddManaToPool)
    assert aa0.effect == bridged

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling AddManaToPool produces colors
    #    (regression guard).
    # ------------------------------------------------------------------
    # 'C' (colorless) is distinct from 'any' (wildcard satisfying any
    # colored requirement) — Mana Confluence / Gemstone Caverns /
    # Cascading Cataracts all pin 'any'; Eldrazi Temple AA[0] pins
    # 'C'.  Colorless mana only satisfies generic / colorless
    # requirements; 'any' coins ALSO satisfy colored requirements.
    assert bridged.produces[0][0] == "C", (
        "Bridged AddManaToPool must produce 'C' (colorless) — "
        "distinct from sibling batch-4 'any'-color Land probes"
    )
    assert bridged.produces[0][1] == 1, (
        "Bridged AddManaToPool must produce amount=1 — distinct from "
        "Cascading Cataracts amount=5 sibling probe and from Eldrazi "
        "Temple's own AA[1] amount=2"
    )

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
        f"Eldrazi Temple AA[0] must mint exactly 1 coin; got pool "
        f"size={len(p0_pool)}"
    )
    coin = p0_pool[0]
    assert coin.color == "C", (
        f"Minted coin must be 'C' (colorless); got color={coin.color!r}"
    )
    assert coin.spend_restriction is None
    assert len(py_state.players[1].mana_pool) == 0
