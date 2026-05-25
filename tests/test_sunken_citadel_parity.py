"""Sunken Citadel — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

Sunken Citadel is a ``{0}`` Land in the EoE pool (a dual-purpose any-
color mana land with a spend-restricted second mana ability for paid
Land-activations) with two activated mana abilities:

    "{T}: Add one mana of any color.
     {T}: Add two mana of any color. Spend this mana only to activate
     abilities of lands."

The load-bearing AA for this probe is the **first** mana ability —
the bare ``{T}: Add one mana of any color`` shape — distinct from
the second AA's spend-restricted shape.

Parser-emitted Effect shape for AA[0]:

    ``AddManaToPool(produces=(('any', 1),), spend_restriction=None)``

attached to an ActivatedAbility whose ``cost`` carries
``tap_self=True`` and no mana cost.  The bridge arm
``add_mana_to_pool`` (round-27, cross_engine.py:7342) round-trips
``{"kind": "add_mana_to_pool", "color": "any", "amount": 1}`` byte-
equal to Python's
``AddManaToPool(produces=(('any', 1),), spend_restriction=None)``.

This module is the **load-bearing PROBED-tier flip evidence** for
Sunken Citadel.  Templates on the immediately-prior batch-4 sibling
``test_mana_confluence_parity.py`` / ``test_gemstone_caverns_parity.py``
+ THIS batch's batch-5 sibling ``test_gene_pollinator_parity.py``
(all consume the same AddManaToPool(any, 1) Effect shape with
spend_restriction=None).  The per-slug attribution distinction is
the printing identity (Sunken Citadel is a non-Legendary EoE Land
with a {T} cost + a spend-restricted sibling AA, distinct from
Gemstone Caverns's Legendary supertype + Mana Confluence's
pay_life=1 cost + Gene Pollinator's Artifact Creature carrier).

**FFFF EEEE-idiom.**  Same lane discipline as batches 1-4 (parse +
bridge round-trip + Python-side resolve, NO cross-engine
``compare_fields``).

**NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
binding the Sunken Citadel slug to its parsed AA[0]
``AddManaToPool(produces=(('any', 1),))`` shape.

**AA[1] half-coverage scope.**  Sunken Citadel's second mana ability
(AA[1], the ``{T}: Add {2} of any color. Spend this mana only to
activate abilities of lands.`` form) emits ``AddManaToPool(produces=
(('any', 2),), spend_restriction='land_activation')`` — the
spend_restriction='land_activation' rider is NOT passed through the
current bridge arm (the bridge constructs ``spend_restriction=None``
regardless), so AA[1] would byte-fail-bridge.  Per the batch-4
Eldrazi Temple AA[1] colorless_eldrazi precedent + the batch-2
Wickerfolk Thresher / batch-3 Cosmogrand Zenith narrow-pin half-
coverage precedent + the IIII / HHHH "covered carrier with spend-
restriction rider" implicit drop precedent, AA[0] alone carries the
load-bearing slug-attribution flip.
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
# (1) Parser SoT — Sunken Citadel is parser-claimed and carries two
# mana-ability AAs; AA[0] is the bare ``AddManaToPool(produces=
# (('any', 1),), spend_restriction=None)``; AA[1] is the spend-
# restricted land_activation sibling (deferred per the AA[1] drop
# precedent).
# ---------------------------------------------------------------------------


def test_sunken_citadel_parser_claims_card():
    assert "Sunken Citadel" in _PRINTINGS, (
        "Sunken Citadel must be parser-claimed by the active "
        "CardSource"
    )


def test_sunken_citadel_printed_attrs():
    """Pins the basic printing surface: Land type, no mana cost."""
    p = _PRINTINGS["Sunken Citadel"]
    assert "Land" in p.card_types
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()


def test_sunken_citadel_mana_abilities_shape():
    """Sunken Citadel has exactly two ActivatedAbilities; AA[0] is the
    bare ``{T}: Add one mana of any color`` (this probe's load-bearing
    AA); AA[1] is the spend-restricted ``{T}: Add {2}. Spend this mana
    only to activate abilities of lands.`` ability (covered by the
    parser SoT only — per the AA[1] deferral docstring above)."""
    p = _PRINTINGS["Sunken Citadel"]
    assert len(p.activated_abilities) == 2, (
        f"Sunken Citadel must have exactly two ActivatedAbilities; "
        f"got {len(p.activated_abilities)}"
    )
    aa0 = p.activated_abilities[0]
    assert isinstance(aa0.effect, AddManaToPool)
    assert aa0.effect.produces == (("any", 1),), (
        f"AA[0] must produce exactly one ('any', 1) coin; got "
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
    assert aa1.effect.produces == (("any", 2),), (
        f"AA[1] must produce ('any', 2) batch; got "
        f"produces={aa1.effect.produces}"
    )
    assert aa1.effect.spend_restriction == "land_activation", (
        f"AA[1] must carry spend_restriction='land_activation'; got "
        f"spend_restriction={aa1.effect.spend_restriction!r}"
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the add_mana_to_pool dict shape round-trips
# byte-equal to the parsed printing's AA[0] emitted Effect.
# ---------------------------------------------------------------------------


def test_sunken_citadel_aa0_bridge_arm_round_trip():
    """The bridge arm ``add_mana_to_pool`` (round-27, cross_engine.py:
    7342) round-trips ``{"kind": "add_mana_to_pool", "color": "any",
    "amount": 1}`` to the matching Python ``AddManaToPool(produces=
    (('any', 1),), spend_restriction=None)`` instance.  Bit-identical
    bridge round-trip to the batch-4 Mana Confluence / Gemstone
    Caverns siblings + the batch-5 Gene Pollinator sibling at the
    Effect level."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "any", "amount": 1}
    )
    assert isinstance(bridged, AddManaToPool)
    assert bridged.produces == (("any", 1),)
    assert bridged.spend_restriction is None

    # Effect-level byte-equality between the parsed real-EoE printing's
    # AA[0] emitted Effect and the bridged Effect.
    p = _PRINTINGS["Sunken Citadel"]
    aa0 = p.activated_abilities[0]
    assert aa0.effect == bridged, (
        f"Sunken Citadel AA[0] Effect must be byte-equal to the "
        f"bridged Effect (AddManaToPool(produces=(('any', 1),)) "
        f"structural contract for the PROBED tier); got "
        f"parsed={aa0.effect!r}, bridged={bridged!r}"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts the
# bridged add_mana_to_pool dict shape on a Sunken-Citadel-shape Land
# carrier.  Per the Mana Confluence batch-4 precedent + the round-27
# bridge-arm docstring, the synthetic carrier uses a closed-vocab
# color (``C``) since Rust's validate_mana_symbol rejects ``"any"``.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_sunken_citadel_add_mana_to_pool_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the
    ``add_mana_to_pool`` dict shape on a Sunken-Citadel-shape Land
    carrier with a synthetic tap-only AA cost (closed-vocab color per
    the Mana Confluence batch-4 precedent)."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Sunken Citadel (synthetic carrier)",
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
# ACTUAL parsed Sunken Citadel printing's AA[0] on Python-side
# resolve.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_sunken_citadel_mana_ability_aa0_add_any_parity():
    """**GENUINE real-EoE cross-engine probe — Sunken Citadel AA[0]
    ({T}: Add one mana of any color) → AddManaToPool(produces=
    (('any', 1),)). PROBED-tier flip (covered_by_construction →
    PROBED).**

    Drives the **ACTUAL parsed Sunken Citadel printing's AA[0]** on
    the Python side through the AddManaToPool effect's resolve path.
    Same EEEE-idiom + cost-substrate deferral as the sibling batch-4
    + batch-5 probes; the distinguishing dispatch here is the printing
    identity (Sunken Citadel is non-Legendary with a spend-restricted
    sibling AA, distinct from Gemstone Caverns Legendary + Mana
    Confluence pay_life=1 + Gene Pollinator Artifact Creature carrier).

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
    binding the Sunken Citadel slug to AA[0]'s AddManaToPool(produces=
    (('any', 1),)) Effect+bridge round-trip on the REAL parsed EoE
    printing.

    **AA[1] half-coverage scope.**  Sunken Citadel's second mana
    ability (AA[1], the ``{T}: Add {2}. Spend this mana only to
    activate abilities of lands.`` form) emits ``AddManaToPool(
    produces=(('any', 2),), spend_restriction='land_activation')`` —
    the spend_restriction='land_activation' rider is NOT passed
    through the current bridge arm (mirroring the batch-4 Eldrazi
    Temple AA[1] colorless_eldrazi precedent).  Per the batch-2
    Wickerfolk Thresher / batch-3 Cosmogrand Zenith narrow-pin half-
    coverage precedent + the IIII / HHHH "covered carrier with spend-
    restriction rider" implicit drop precedent, AA[0] alone carries
    the load-bearing slug-attribution flip.

    **Bridge arm exercised:**
      * ``add_mana_to_pool`` (round-27 bridge arm; the amount=1
        any-color dispatch).

    **Setup (Python-side):**
      * p0 has Sunken Citadel on the battlefield (the AA source).
      * p0's mana pool starts empty.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "add_mana_to_pool", "color": "any", "amount": 1}``
        translates to ``AddManaToPool(produces=(('any', 1),),
        spend_restriction=None)``.
      * The Land's AA[0] emits the same Effect.
      * Effect-level byte-equality between the parsed real-EoE
        emission and the bridged Effect.
      * Post-resolve: p0's mana pool gained exactly one ManaCoin with
        color='any' and spend_restriction=None.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Sunken Citadel printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Sunken Citadel")
    if real is None:
        pytest.skip("Sunken Citadel absent from active CardSource")
    assert "Land" in real.card_types
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
    # 3. Distinctness regression guard.
    # ------------------------------------------------------------------
    # AA[0] (spend_restriction=None) is distinct from AA[1]
    # (spend_restriction='land_activation') — the bridge arm
    # constructs spend_restriction=None regardless, so only AA[0]
    # byte-equals the bridged Effect.
    assert bridged.spend_restriction is None, (
        "Bridged AddManaToPool must NOT carry a spend_restriction — "
        "AA[0] is the bare any-color shape; AA[1]'s "
        "spend_restriction='land_activation' rider is implicit-drop"
    )
    assert bridged.produces[0][0] == "any"
    assert bridged.produces[0][1] == 1, (
        "Bridged AddManaToPool must produce amount=1 — distinct from "
        "AA[1]'s amount=2 batch-mint"
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke — drive the parsed effect.
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
        f"Sunken Citadel AA[0] must mint exactly 1 coin; got pool "
        f"size={len(p0_pool)}"
    )
    coin = p0_pool[0]
    assert coin.color == "any", (
        f"Minted coin must be 'any'-color (wildcard); got "
        f"color={coin.color!r}"
    )
    assert coin.spend_restriction is None, (
        f"Minted coin must have no spend_restriction; got "
        f"spend_restriction={coin.spend_restriction!r}"
    )
    assert len(py_state.players[1].mana_pool) == 0
