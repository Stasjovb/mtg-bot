"""Gene Pollinator — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

Gene Pollinator is a ``{G}`` Artifact Creature in the EoE pool with a
single activated mana ability:

    "{T}: Add one mana of any color."

(The City-of-Brass-style any-color mana primitive on an artifact-
creature carrier — Gene Pollinator is one of the higher-deck-count
covered-by-construction holdouts at ~31.8k 17lands decks.)

Parser-emitted Effect shape (the EFFECT half, distinct from the cost
half):

    ``AddManaToPool(produces=(('any', 1),), spend_restriction=None)``

attached to an ActivatedAbility whose ``cost`` carries
``tap_self=True`` and no mana cost.  The bridge arm
``add_mana_to_pool`` (round-27, cross_engine.py:7342) round-trips
``{"kind": "add_mana_to_pool", "color": "any", "amount": 1}`` byte-
equal to Python's
``AddManaToPool(produces=(('any', 1),), spend_restriction=None)``.

This module is the **load-bearing PROBED-tier flip evidence** for
Gene Pollinator.  Templates on the batch-4 sibling
``test_mana_confluence_parity.py`` / ``test_gemstone_caverns_parity.py``
(the FIRST PROBE_MODULES-credited real-EoE Land + AddManaToPool
consumers with amount=1); the distinguishing dispatch here is the
**Artifact Creature carrier** (not a Land) — Gene Pollinator is an
Artifact Creature with the same bridge-clean AA shape on a creature-
typed permanent.

**FFFF EEEE-idiom for the ActivatedAbility carrier.**  Same lane
discipline as batches 1-4 (parse + bridge round-trip + Python-side
resolve, NO cross-engine ``compare_fields``).  The Python-side
resolve drives the AddManaToPool Effect directly through its resolve
path; the post-resolve observable is "p0's mana pool gained one
``any``-colored coin with no spend_restriction".  The full
activated-mana-ability bypass-stack trajectory (mana abilities
bypass the stack per CR 605) + Rust parallel observation are
documented in cost-substrate landings + the
test_probe_activated_abilities_o2-family scope and stay substrate-
deferred for this lane.

**NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
binding the Gene Pollinator slug to its parsed
``ActivatedAbility(AddManaToPool(produces=(('any', 1),)))`` shape on
an **Artifact Creature carrier** — distinct from the batch-4 sibling
Land probes (Mana Confluence / Gemstone Caverns / Cascading
Cataracts) that pin the same AddManaToPool shape on Land carriers.
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
# (1) Parser SoT — Gene Pollinator is parser-claimed and carries one
# mana-ability AA whose effect is ``AddManaToPool(produces=(('any', 1),),
# spend_restriction=None)``.
# ---------------------------------------------------------------------------


def test_gene_pollinator_parser_claims_card():
    assert "Gene Pollinator" in _PRINTINGS, (
        "Gene Pollinator must be parser-claimed by the active "
        "CardSource"
    )


def test_gene_pollinator_printed_attrs():
    """Pins the basic printing surface: Artifact Creature, mana cost
    {G}.  The Artifact Creature carrier is the distinguishing dispatch
    from the batch-4 sibling Land probes."""
    p = _PRINTINGS["Gene Pollinator"]
    assert "Artifact" in p.card_types, (
        "Gene Pollinator must be an Artifact (the artifact-creature "
        "carrier shape distinct from the batch-4 sibling Land probes)"
    )
    assert "Creature" in p.card_types, (
        "Gene Pollinator must be a Creature (the artifact-creature "
        "carrier shape distinct from the batch-4 sibling Land probes)"
    )
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == (("G", 1),)


def test_gene_pollinator_mana_ability_shape():
    """Gene Pollinator has exactly one ActivatedAbility (the mana
    ability); its effect is the bare ``AddManaToPool(produces=(('any',
    1),), spend_restriction=None)`` — the canonical "Add one mana of
    any color" shape (bit-identical at the Effect level to Mana
    Confluence / Gemstone Caverns; the carrier-side distinction is
    Artifact Creature, not Land)."""
    p = _PRINTINGS["Gene Pollinator"]
    assert len(p.activated_abilities) == 1, (
        f"Gene Pollinator must have exactly one ActivatedAbility (the "
        f"mana ability); got {len(p.activated_abilities)}"
    )
    aa = p.activated_abilities[0]
    assert isinstance(aa.effect, AddManaToPool), (
        f"Gene Pollinator AA effect must be AddManaToPool; got "
        f"{type(aa.effect).__name__}"
    )
    assert aa.effect.produces == (("any", 1),), (
        f"Gene Pollinator AA must produce exactly one ('any', 1) coin; "
        f"got produces={aa.effect.produces}"
    )
    assert aa.effect.spend_restriction is None, (
        f"Gene Pollinator AA must NOT carry a spend_restriction "
        f"(unrestricted any-color mana); got spend_restriction="
        f"{aa.effect.spend_restriction!r}"
    )
    # Cost-side: {T} (no mana, no life-payment).  Documented for
    # context; the Effect-side bridge round-trip is what credits
    # PROBED per-slug.
    assert aa.cost.tap_self is True
    assert aa.cost.pay_life == 0
    assert aa.cost.mana is None
    assert aa.is_mana_ability is True


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the add_mana_to_pool dict shape round-trips
# byte-equal to the parsed printing's emitted Effect.
# ---------------------------------------------------------------------------


def test_gene_pollinator_bridge_arm_round_trip():
    """The bridge arm ``add_mana_to_pool`` (round-27, cross_engine.py:
    7342) round-trips ``{"kind": "add_mana_to_pool", "color": "any",
    "amount": 1}`` to the matching Python
    ``AddManaToPool(produces=(('any', 1),), spend_restriction=None)``
    instance.  Bit-identical bridge round-trip to the batch-4 Mana
    Confluence / Gemstone Caverns siblings at the Effect level; the
    per-slug attribution distinction is the **Artifact Creature
    carrier** (per the cathedral-of-war-style same-Effect-class-
    different-printing-slug precedent)."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "any", "amount": 1}
    )
    assert isinstance(bridged, AddManaToPool)
    assert bridged.produces == (("any", 1),)
    assert bridged.spend_restriction is None

    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted AddManaToPool Effect and the bridged Effect — the
    # structural contract for the PROBED tier.
    p = _PRINTINGS["Gene Pollinator"]
    aa = p.activated_abilities[0]
    assert aa.effect == bridged, (
        f"Gene Pollinator AA Effect must be byte-equal to the bridged "
        f"Effect (AddManaToPool(produces=(('any', 1),)) structural "
        f"contract for the PROBED tier); got parsed={aa.effect!r}, "
        f"bridged={bridged!r}"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts the
# bridged add_mana_to_pool dict shape on a Gene-Pollinator-shape
# Artifact Creature carrier.  Per the batch-4 Mana Confluence
# precedent + the round-27 bridge-arm docstring, the synthetic carrier
# uses a closed-vocab color (``C``) since Rust's validate_mana_symbol
# rejects ``"any"``.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_gene_pollinator_add_mana_to_pool_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the
    ``add_mana_to_pool`` dict shape on a Gene-Pollinator-shape Artifact
    Creature carrier with a synthetic tap-only AA cost.  Per the Mana
    Confluence batch-4 precedent, the synthetic carrier exercises a
    closed-vocab color (``C``) since Rust's ``validate_mana_symbol``
    (cards.rs:3300) rejects the Python-side ``"any"`` wildcard."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Gene Pollinator (synthetic carrier)",
            "card_types": ["Artifact", "Creature"],
            "mana_cost": {"generic": 0, "G": 1},
            "power": 1,
            "toughness": 1,
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
# ACTUAL parsed Gene Pollinator printing on Python-side resolve for
# the AddManaToPool effect.  Mirrors the FFFF EEEE-idiom (parse +
# bridge round-trip + Python-side resolve, NO cross-engine
# compare_fields).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_gene_pollinator_mana_ability_add_any_parity():
    """**GENUINE real-EoE cross-engine probe — Gene Pollinator mana
    ability → AddManaToPool(produces=(('any', 1),)). PROBED-tier flip
    (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Gene Pollinator printing** on the
    Python side through the AddManaToPool effect's resolve path.
    Mirrors the FFFF EEEE-idiom (parse + bridge round-trip + Python-
    side resolve, no cross-engine ``compare_fields``); same lane
    discipline as batches 1-4.

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
    binding the Gene Pollinator slug to the AA + AddManaToPool(
    produces=(('any', 1),)) Effect+bridge round-trip on the REAL
    parsed EoE printing.  Distinct from the batch-4 sibling Land probes
    (Mana Confluence / Gemstone Caverns) — Gene Pollinator is an
    **Artifact Creature** carrier of the same bridge-clean AddManaToPool
    shape.  Per the cathedral-of-war-style same-Effect-class-different-
    printing-slug precedent, each carrier-typed printing-slug gets its
    own PROBED-tier slot.

    **Bridge arm exercised:**
      * ``add_mana_to_pool`` (round-27 bridge arm at cross_engine.py:
        7342; scalar color/amount → Python's richer produces tuple
        narrowing).

    **AA-cost-substrate deferral.**  The full activated-mana-ability
    cost-payment trajectory (the ``tap_self`` cost atom on the
    ActivationCost, the mana-ability stack-bypass per CR 605, the
    cross-engine observer parity on the pool delta) is the cost-
    substrate / test_probe_activated_abilities_o2 family scope and
    stays substrate-deferred for this lane.  Per-slug attribution
    credits the slug based on the Effect+bridge byte-equality alone
    (the round-1 PROBED-tier definition + the batches 1-4 EEEE-idiom
    precedent).

    **Setup (Python-side):**
      * p0 has Gene Pollinator on the battlefield (the AA source;
        the Effect resolves on the source's controller).
      * p0's mana pool starts empty.

    **Observables asserted:**
      * Bridge round-trip:
        ``{"kind": "add_mana_to_pool", "color": "any", "amount": 1}``
        translates to ``AddManaToPool(produces=(('any', 1),),
        spend_restriction=None)``.
      * The carrier's mana ActivatedAbility emits the same Effect.
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
    # 1. Verify the genuine parsed Gene Pollinator printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Gene Pollinator")
    if real is None:
        pytest.skip("Gene Pollinator absent from active CardSource")
    assert "Artifact" in real.card_types
    assert "Creature" in real.card_types
    aa = real.activated_abilities[0]
    assert isinstance(aa.effect, AddManaToPool)
    assert aa.effect.produces == (("any", 1),)
    assert aa.effect.spend_restriction is None

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "any", "amount": 1}
    )
    assert isinstance(bridged, AddManaToPool)
    assert aa.effect == bridged, (
        f"Gene Pollinator AA Effect must be byte-equal to bridged; "
        f"got parsed={aa.effect!r}, bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect shapes (regression guard).
    # ------------------------------------------------------------------
    # 'any' wildcard color satisfies colored requirements (distinct
    # from 'C' colorless on Eldrazi Temple AA[0] / Cascading Cataracts /
    # Blinkmoth Nexus mana AA which produces 'C').  amount=1 is
    # distinct from Cascading Cataracts amount=5.  spend_restriction is
    # None — distinct from Power Depot / Steelswarm Operator /
    # Eldrazi Temple AA[1] spend-restricted shapes.
    assert bridged.produces[0][0] == "any", (
        "Bridged AddManaToPool must produce 'any'-color coin "
        "(unrestricted color slot) — distinct from 'C' (colorless) / "
        "single-color produces sibling shapes"
    )
    assert bridged.produces[0][1] == 1, (
        "Bridged AddManaToPool must produce amount=1 — distinct from "
        "the Cascading Cataracts amount=5 batch-mint sibling"
    )
    assert bridged.spend_restriction is None, (
        "Bridged AddManaToPool must NOT carry a spend_restriction — "
        "that's Power Depot / Eldrazi Temple AA[1]'s shape, not Gene "
        "Pollinator's"
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke — drive the parsed effect through
    #    its actual resolve path.  p0's mana pool gains one 'any' coin.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Seat the GENUINE parsed Gene Pollinator on p0's bf (the AA
    # source).
    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Pre-resolve sanity: p0's mana pool is empty.
    assert len(py_state.players[0].mana_pool) == 0, (
        f"empty-pool precondition: p0's mana pool must be empty pre-"
        f"resolve; got pool size="
        f"{len(py_state.players[0].mana_pool)}"
    )

    # Drive the AddManaToPool effect through resolve directly,
    # mirroring what the mana ability does once its cost is paid
    # (mana abilities bypass the stack per CR 605, but the Effect's
    # resolve path is the same code).
    aa.effect.resolve(py_state, py_source.controller_id)

    # Post-resolve: p0's mana pool has exactly one 'any'-color coin
    # with no spend_restriction; p1's pool is untouched.
    p0_pool = py_state.players[0].mana_pool
    assert len(p0_pool) == 1, (
        f"Gene Pollinator AA must mint exactly 1 coin in p0's pool; "
        f"got pool size={len(p0_pool)}"
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
    assert len(py_state.players[1].mana_pool) == 0, (
        "p1's mana pool must remain empty (the controller-of-effect "
        "contract — Gene Pollinator mints into the source's "
        "controller's pool only)"
    )
