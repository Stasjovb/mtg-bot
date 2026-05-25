"""Mana Confluence — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

Mana Confluence is a ``{0}`` Land in the EoE pool (a long-time City-
of-Brass-style any-color land) with a single activated mana ability:

    "{T}, Pay 1 life: Add one mana of any color."

Parser-emitted Effect shape (the EFFECT half, distinct from the cost
half):

    ``AddManaToPool(produces=(('any', 1),), spend_restriction=None)``

attached to an ActivatedAbility whose ``cost`` carries
``tap_self=True`` + ``pay_life=1`` (the cost-side machinery is
captured separately on the ActivationCost; out-of-scope at the
Effect+bridge byte-equality layer this probe verifies).  The bridge
arm ``add_mana_to_pool`` (round-27, cross_engine.py:7342) round-trips
``{"kind": "add_mana_to_pool", "color": "any", "amount": 1}`` byte-
equal to Python's
``AddManaToPool(produces=(('any', 1),), spend_restriction=None)``.

This module is the **load-bearing PROBED-tier flip evidence** for
Mana Confluence and the FIRST PROBE_MODULES-credited consumer of the
``add_mana_to_pool`` bridge arm on a real-EoE Land carrier.  The
substrate is already shipped — round-27 closed the bridge gap; this
probe lights up the slug-attribution for Mana Confluence.

**FFFF EEEE-idiom for the ActivatedAbility carrier.**  Same lane
discipline as batches 1-3 (parse + bridge round-trip + Python-side
resolve, NO cross-engine ``compare_fields``).  The Python-side
resolve drives the AddManaToPool Effect directly through its resolve
path; the post-resolve observable is "p0's mana pool gained one
``any``-colored coin with no spend_restriction".  The full
activated-mana-ability bypass-stack trajectory (mana abilities
bypass the stack per CR 605) + the pay_life cost-atom + Rust
parallel observation are documented in cost-substrate landings + the
test_probe_activated_abilities_o2-family scope and stay substrate-
deferred for this lane.

**NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
binding the Mana Confluence slug to its parsed
``ActivatedAbility(AddManaToPool(produces=(('any', 1),)))`` shape;
the FIRST PROBED-tier slot for the AddManaToPool Effect class on a
real-EoE Land carrier (the round-27 bridge arm landed end-to-end
without a slug-attribution probe).
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
# (1) Parser SoT — Mana Confluence is parser-claimed and carries one
# mana-ability AA whose effect is ``AddManaToPool(produces=(('any', 1),),
# spend_restriction=None)``.
# ---------------------------------------------------------------------------


def test_mana_confluence_parser_claims_card():
    assert "Mana Confluence" in _PRINTINGS, (
        "Mana Confluence must be parser-claimed by the active "
        "CardSource"
    )


def test_mana_confluence_printed_attrs():
    """Pins the basic printing surface: Land type, no mana cost."""
    p = _PRINTINGS["Mana Confluence"]
    assert "Land" in p.card_types
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()


def test_mana_confluence_mana_ability_shape():
    """Mana Confluence has exactly one ActivatedAbility (the mana
    ability); its effect is the bare ``AddManaToPool(produces=(('any',
    1),), spend_restriction=None)`` — the canonical "Add one mana of
    any color" City-of-Brass shape (distinct from spend-restricted
    variants like Power Depot's ``spend_restriction='artifact_spell'``
    or Eldrazi Temple's second AA's
    ``spend_restriction='colorless_eldrazi'``)."""
    p = _PRINTINGS["Mana Confluence"]
    assert len(p.activated_abilities) == 1, (
        f"Mana Confluence must have exactly one ActivatedAbility (the "
        f"mana ability); got {len(p.activated_abilities)}"
    )
    aa = p.activated_abilities[0]
    assert isinstance(aa.effect, AddManaToPool), (
        f"Mana Confluence AA effect must be AddManaToPool; got "
        f"{type(aa.effect).__name__}"
    )
    assert aa.effect.produces == (("any", 1),), (
        f"Mana Confluence AA must produce exactly one ('any', 1) coin; "
        f"got produces={aa.effect.produces}"
    )
    assert aa.effect.spend_restriction is None, (
        f"Mana Confluence AA must NOT carry a spend_restriction "
        f"(unrestricted any-color mana); got spend_restriction="
        f"{aa.effect.spend_restriction!r}"
    )
    # Cost-side: {T} + Pay 1 life.  Documented for context; the
    # Effect-side bridge round-trip is what credits PROBED per-slug.
    assert aa.cost.tap_self is True
    assert aa.cost.pay_life == 1
    assert aa.is_mana_ability is True


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the add_mana_to_pool dict shape round-trips
# byte-equal to the parsed printing's emitted Effect.
# ---------------------------------------------------------------------------


def test_mana_confluence_bridge_arm_round_trip():
    """The bridge arm ``add_mana_to_pool`` (round-27, cross_engine.py:
    7342) round-trips ``{"kind": "add_mana_to_pool", "color": "any",
    "amount": 1}`` to the matching Python
    ``AddManaToPool(produces=(('any', 1),), spend_restriction=None)``
    instance.  Note the bridge-side dict uses scalar ``color`` +
    ``amount`` fields (mirroring Rust's struct-variant) while the
    Python class field is the richer ``produces: tuple[tuple[str,
    int], ...]`` shape — the bridge arm folds the scalar pair into a
    one-tuple of one (color, amount) pair."""
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
    p = _PRINTINGS["Mana Confluence"]
    aa = p.activated_abilities[0]
    assert aa.effect == bridged, (
        f"Mana Confluence AA Effect must be byte-equal to the bridged "
        f"Effect (AddManaToPool(produces=(('any', 1),)) structural "
        f"contract for the PROBED tier); got parsed={aa.effect!r}, "
        f"bridged={bridged!r}"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts the
# bridged add_mana_to_pool dict shape on a Mana-Confluence-shape Land
# carrier.  The full mana-ability bypass-stack + pay_life cost-atom
# surfaces are exercised in the cost-substrate landings; this synthetic
# Rust pin restricts to the EFFECT half (mirroring the batch-1/2/3
# simpler-cost Rust-carrier precedent).
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_mana_confluence_add_mana_to_pool_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the
    ``add_mana_to_pool`` dict shape on a Mana-Confluence-shape Land
    carrier with a synthetic tap-only AA cost.

    **Color narrowing.**  Rust's ``validate_mana_symbol`` (cards.rs:
    3300) only accepts the closed-vocab set ``{"W","U","B","R","G",
    "C"}`` — ``"any"`` is a Python-side wildcard that the round-27
    bridge arm folds in at the Python-side ``produces`` tuple only.
    Per the round-27 bridge-arm docstring (``add_mana_to_pool``,
    cross_engine.py:7376-7383): "Python's AddManaToPool has no
    equivalent runtime validation — the produces tuple accepts any
    string — so the bridge does NOT re-validate here.  The Rust
    parser surface lockstep test ensures any invalid color string
    fails on the Rust side first."  This synthetic Rust pin
    therefore exercises a closed-vocab color (``C``) — the EFFECT-
    half lockstep is on the dict-shape acceptance, not on the
    wildcard color (the wildcard color is a documented Python-side
    representation; Mana Confluence's Python printing carries
    ``produces=(('any', 1),)`` while the Rust side would carry
    ``(('C', 1),)`` if the parser ever saw it).  Mirrors the
    batch-1/2/3 simpler-cost / simpler-predicate Rust-carrier
    precedent.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Mana Confluence (synthetic carrier)",
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
# ACTUAL parsed Mana Confluence printing on Python-side resolve for
# the AddManaToPool effect.  Mirrors the FFFF EEEE-idiom (parse +
# bridge round-trip + Python-side resolve, NO cross-engine
# compare_fields).  The full activated-mana-ability bypass-stack
# trajectory + pay_life cost-payment + cross-engine observer parity
# stay AA-cost-substrate-deferred; the slug-attribution credits the
# Mana Confluence slot regardless of the cost-payment scope.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_mana_confluence_mana_ability_add_any_parity():
    """**GENUINE real-EoE cross-engine probe — Mana Confluence mana
    ability → AddManaToPool(produces=(('any', 1),)). PROBED-tier flip
    (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Mana Confluence printing** on the
    Python side through the AddManaToPool effect's resolve path.
    Mirrors the FFFF EEEE-idiom (parse + bridge round-trip + Python-
    side resolve, no cross-engine ``compare_fields``); same lane
    discipline as batches 1-3.

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
    binding the Mana Confluence slug to the AA + AddManaToPool(
    produces=(('any', 1),)) Effect+bridge round-trip on the REAL
    parsed EoE printing.  The FIRST PROBED-tier slot for the
    AddManaToPool Effect class on a real-EoE Land carrier (the
    round-27 bridge arm landed end-to-end without a slug-attribution
    probe).

    **Bridge arm exercised:**
      * ``add_mana_to_pool`` (round-27 bridge arm at cross_engine.py:
        7342; scalar color/amount → Python's richer produces tuple
        narrowing).

    **AA-cost-substrate deferral.**  The full activated-mana-ability
    cost-payment trajectory (the ``tap_self`` + ``pay_life=1`` cost
    atoms on the ActivationCost, the mana-ability stack-bypass per
    CR 605, the cross-engine observer parity on the pool delta) is
    the cost-substrate / test_probe_activated_abilities_o2 family
    scope and stays substrate-deferred for this lane.  Per-slug
    attribution credits the slug based on the Effect+bridge byte-
    equality alone (the round-1 PROBED-tier definition + the batches
    1-3 EEEE-idiom precedent).

    **Setup (Python-side):**
      * p0 has Mana Confluence on the battlefield (the AA source;
        the Effect resolves on the source's controller).
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
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Mana Confluence printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Mana Confluence")
    if real is None:
        pytest.skip("Mana Confluence absent from active CardSource")
    assert "Land" in real.card_types
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
        f"Mana Confluence AA Effect must be byte-equal to bridged; "
        f"got parsed={aa.effect!r}, bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. Distinctness from sibling Effect shapes (regression guard).
    # ------------------------------------------------------------------
    # AddManaToPool with spend_restriction=None is NOT the same as the
    # spend-restricted Power Depot / Steelswarm Operator /
    # Eldrazi Temple AA[1] shapes — the unrestricted any-color mana
    # is what distinguishes Mana Confluence from those sibling Land /
    # artifact-mana-rock carriers.  The 'any' wildcard is also
    # distinct from a 'C' colorless coin (Cascading Cataracts /
    # Eldrazi Temple AA[0]) — 'any' satisfies colored requirements
    # while 'C' does not.
    assert bridged.spend_restriction is None, (
        "Bridged AddManaToPool must NOT carry a spend_restriction — "
        "that's Power Depot / Eldrazi Temple AA[1]'s shape, not Mana "
        "Confluence's"
    )
    assert bridged.produces[0][0] == "any", (
        "Bridged AddManaToPool must produce 'any'-color coin "
        "(unrestricted color slot) — distinct from 'C' (colorless) / "
        "single-color produces sibling shapes"
    )

    # ------------------------------------------------------------------
    # 4. Python-side resolve smoke — drive the parsed effect through
    #    its actual resolve path.  p0's mana pool gains one 'any' coin.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Seat the GENUINE parsed Mana Confluence on p0's bf (the AA
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
        f"Mana Confluence AA must mint exactly 1 coin in p0's pool; "
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
        "contract — Mana Confluence mints into the source's "
        "controller's pool only)"
    )
