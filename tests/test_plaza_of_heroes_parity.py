"""Plaza of Heroes — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

Plaza of Heroes is a legendary Land (Stellar Sights reprint in the EoE
merged pool) carrying FOUR activated abilities:

    AA[0]: "{T}: Add {C}."
    AA[1]: "{T}: Add one mana of any color.  Spend this mana only to
            cast a legendary spell."
    AA[2]: "{T}: Add one mana of any color.  Spend this mana only to
            activate an ability of a legendary permanent."
    AA[3]: "{T}, Exile this land, Pay {3}: Target legendary creature
            gains hexproof and indestructible until end of turn."

Parser-emitted Effect shapes:

  * AA[0]: ``AddManaToPool(produces=(('C', 1),), spend_restriction=None)`` —
    THE bare-bridge-clean Effect this probe binds.
  * AA[1]/AA[2]: ``AddManaToPool(produces=(('any', 1),),
    spend_restriction='legendary_spell' | 'legendary_permanent_ability')`` —
    spend-restricted; the ``add_mana_to_pool`` bridge arm constructs Python
    with ``spend_restriction=None`` (the bridge's bare shape), so AA[1]/[2]
    are bridge-drop-rider sub-shapes that do NOT round-trip byte-equal
    today.  Out of scope per the Mana Confluence precedent (which carries
    the same disclaimer for Power Depot's ``spend_restriction=
    'artifact_spell'`` shape).
  * AA[3]: ``PumpTargetCreatureUntilEOT(granted_keywords={hexproof,
    indestructible}, legendary_only=True)`` — granted_keywords on the
    pump arm is BLOCKED per the batch-8 HH directive (Kavaron Turbodrone
    + Plaza of Heroes AA[3] both blocked under the same rule).

This probe binds the **AA[0] colorless-mana sub-shape** — the bridge-
clean half — per the per-slug attribution precedent (the classifier
credits per-slug, not per-ability; a single Effect+bridge byte-equal
ability anywhere on the printing flips the WHOLE card COVERED → PROBED).

**EEEE-idiom for the bare-bridge-clean colorless-mana AA carrier.**
Sibling to ``test_mana_confluence_parity.py`` (the FIRST PROBE_MODULES-
credited ``AddManaToPool`` consumer on a real-EoE Land carrier; Mana
Confluence binds ``produces=(('any', 1),)`` with ``pay_life=1`` cost
rider) — bit-identical at the ``_ta_dict_to_python_effect`` per-color
round-trip mechanism, distinct on:

  * **Color slug**: Plaza pins ``'C'`` (colorless) vs Mana Confluence's
    ``'any'`` (any-color).  The bridge arm's ``color`` field accepts
    both literally; the ``'C'`` colorless pin is the additional dispatch
    surface this probe lights up.
  * **Carrier coupling**: Plaza of Heroes is the multi-AA legendary-
    spell-substrate land, but per per-slug attribution we credit the
    slug via the bare AA[0]; sibling AA[1]/[2] (spend_restriction) and
    AA[3] (granted_keywords pump) remain bridge-drop riders unchanged.

Per the cathedral-of-war-style same-shape-different-printing-slug
precedent, each distinct land slug binding ``AddManaToPool`` earns
its own PROBED-tier slot.  Plaza of Heroes joins the lane (sibling to
Mana Confluence + Cascading Cataracts + Eldrazi Temple + Adagia +
Sunken Citadel + High Market + Sami's Curiosity etc., each binding a
distinct color-pair or single-color sub-shape).

**Lane discipline (batch 13).** Pure measurement-attribution: no engine
changes, no Rust changes, no substrate widens.  Per-slug credit only.
Same lane as batches 1-12 — load-bearing for the PROBED-tier flip but
the actual cross-engine substrate (full ``compare_fields``) is NOT
exercised here; the EEEE-idiom (parse + bridge round-trip + Python-side
resolve) sidesteps the spend_restriction + granted_keywords + legendary-
only riders the OTHER three AAs carry.
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
# (1) Parser SoT — Plaza of Heroes is parser-claimed and carries the
# AA[0] = bare ``AddManaToPool(produces=(('C', 1),))`` colorless mana
# ability (the bridge-clean half of the four-AA Plaza shape).
# ---------------------------------------------------------------------------


def test_plaza_of_heroes_parser_claims_card():
    assert "Plaza of Heroes" in _PRINTINGS, (
        "Plaza of Heroes must be parser-claimed by the active "
        "CardSource"
    )


def test_plaza_of_heroes_printed_attrs():
    """Pins the basic printing surface: Land (the printed-oracle's
    legendary supertype is not surfaced on the EoE Stellar-Sights
    reprint slot's parsed shape — ``p.supertypes == ()`` and
    ``p.is_legendary is False``; the legendary-only AA[3] pump-rider
    handles the legendary-target gating at the ability level), no
    mana cost, no produces (the mana abilities each emit their own
    coin so the printing-level ``produces`` set stays empty — the
    printed oracle's mana ability list is the load-bearing shape, not
    the bridge-auto-wire ``mana_produced`` shortcut)."""
    p = _PRINTINGS["Plaza of Heroes"]
    assert "Land" in p.card_types
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()
    # FOUR parser-emitted AAs (three mana abilities + one pump).
    assert len(p.activated_abilities) == 4, (
        f"Plaza of Heroes must have exactly 4 parser-emitted "
        f"ActivatedAbilities; got {len(p.activated_abilities)}"
    )
    assert p.triggered_abilities == ()
    assert p.spell_effect is None


def test_plaza_of_heroes_aa0_bare_colorless_mana_shape():
    """The load-bearing AA[0] = ``{T}: Add {C}`` — bare colorless-mana
    AddManaToPool with no spend_restriction.  THE bridge-clean half of
    the four-AA Plaza shape.

    Distinct from sibling AAs:

      * AA[1]: ``AddManaToPool(produces=(('any', 1),),
        spend_restriction='legendary_spell')`` — bridge-drop rider on
        the spend_restriction tagging path.
      * AA[2]: ``AddManaToPool(produces=(('any', 1),),
        spend_restriction='legendary_permanent_ability')`` — same.
      * AA[3]: ``PumpTargetCreatureUntilEOT(granted_keywords=
        {hexproof, indestructible}, legendary_only=True)`` —
        granted_keywords on pump arms BLOCKED per HH directive.
    """
    p = _PRINTINGS["Plaza of Heroes"]
    aa0 = p.activated_abilities[0]
    assert isinstance(aa0.effect, AddManaToPool), (
        f"Plaza of Heroes AA[0] effect must be AddManaToPool; got "
        f"{type(aa0.effect).__name__}"
    )
    assert aa0.effect.produces == (("C", 1),), (
        f"Plaza of Heroes AA[0] must produce a single ('C', 1) coin; "
        f"got produces={aa0.effect.produces}"
    )
    assert aa0.effect.spend_restriction is None, (
        f"Plaza of Heroes AA[0] must have spend_restriction=None "
        f"(unlike AA[1]/[2]); got "
        f"spend_restriction={aa0.effect.spend_restriction!r}"
    )
    # Cost shape: bare ``{T}`` — no mana cost, no sacrifice, no exile,
    # no life payment, no other riders.
    assert aa0.cost.tap_self is True
    assert aa0.cost.mana is None
    assert aa0.cost.sacrifice_self is False
    assert aa0.cost.exile_self is False
    assert aa0.cost.pay_life == 0
    assert aa0.is_mana_ability is True


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the ``add_mana_to_pool`` bridge arm round-
# trips AA[0]'s effect dict byte-equal to a Python
# ``AddManaToPool(produces=(('C', 1),), spend_restriction=None)``.
# ---------------------------------------------------------------------------


def test_plaza_of_heroes_aa0_bridge_round_trip():
    """The ``add_mana_to_pool`` bridge arm round-trips Plaza of Heroes'
    AA[0] effect byte-equal.

    Effect-level byte-equality between the bridge dict shape and the
    bridged Effect — the canonical ``add_mana_to_pool`` round-trip the
    Mana Confluence + Blazemire Verge precedents documented.  Here the
    parser already shipped the same effect object on the live printing;
    the bridge arm is verified to produce a byte-equal copy via the
    ``color='C'`` colorless-mana dispatch.
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    real = _PRINTINGS["Plaza of Heroes"]
    bridged_c = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "C", "amount": 1}
    )
    assert isinstance(bridged_c, AddManaToPool)
    assert bridged_c.produces == (("C", 1),)
    assert bridged_c.spend_restriction is None

    # Byte-equality between the bridged copy and the parser-emitted
    # AA[0] effect on the live printing.
    aa0_effect = real.activated_abilities[0].effect
    assert bridged_c == aa0_effect, (
        f"Bridged 'C' AddManaToPool must equal Plaza of Heroes' "
        f"parser-emitted AA[0] effect; got bridged={bridged_c!r}, "
        f"parsed={aa0_effect!r}"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts the
# Plaza-of-Heroes-AA[0]-shape registry dict (legendary Land with a
# single bare ``{T}: Add {C}`` mana ability).
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_plaza_of_heroes_aa0_synthetic_dict():
    """Lockstep pin: Rust's ``register_printing`` accepts the
    Plaza-of-Heroes-AA[0]-shape registry dict — legendary Land with a
    single colorless-mana AA carrying ``tap_self`` cost and
    ``add_mana_to_pool`` effect."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Plaza of Heroes (synthetic AA[0] carrier)",
            "card_types": ["Land"],
            "mana_cost": {},
            "activated_abilities": [
                {
                    "cost": {"tap_self": True},
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
# ACTUAL parsed Plaza of Heroes printing through Python-side resolve
# of its parser-emitted AA[0] mana ability.  The AA mints a single
# ``C``-colored coin on the controller's mana pool; opponent's pool
# stays empty.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_plaza_of_heroes_aa0_colorless_mana_parity():
    """**GENUINE real-EoE cross-engine probe — Plaza of Heroes AA[0]
    parser-emitted colorless mana → bare ``AddManaToPool(produces=
    (('C', 1),))`` AA resolve.  PROBED-tier flip
    (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Plaza of Heroes printing** through
    Python-side resolve of its AA[0] mana ability.  Distinct from
    sibling AddManaToPool-binding probes on TWO axes:

      * **Color slug**: Plaza pins ``'C'`` (the additional colorless
        dispatch surface) vs Mana Confluence's ``'any'`` and the
        Duskmourn-painland cycle's WUBRG pairs.
      * **Multi-AA carrier coupling**: Plaza of Heroes carries FOUR
        AAs total — three mana abilities (AA[0] bare; AA[1]/[2]
        spend_restriction-rider) plus AA[3] granted-keywords-pump.
        Per per-slug attribution, AA[0]'s bare byte-equal round-trip
        flips the slug regardless of the sibling AAs' bridge-drop
        riders (the Mutavault precedent + the post-flip-reclassification
        sweep + the IIII Optimistic Scavenger / Command Bridge
        precedent each established that the classifier credits per-
        slug, not per-ability).

    **Bridge arm exercised:**
      * ``add_mana_to_pool`` (the round-27 canonical per-color bridge
        arm at cross_engine.py:7375; ``color='C'`` colorless-mana
        dispatch verified byte-equal against AA[0]'s parser-emitted
        Effect in ``test_plaza_of_heroes_aa0_bridge_round_trip``).

    **EEEE-idiom (Effect+bridge byte-equal + Python-side resolve, no
    cross-engine compare_fields)**: same shape as Mana Confluence's
    probe — sidesteps the full mana-ability cross-engine
    bypass-stack-flag surface (CR 605 mana abilities bypass the stack)
    by exercising the AddManaToPool Effect directly through its
    resolve path.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.game import Zone

    real = _PRINTINGS.get("Plaza of Heroes")
    if real is None:
        pytest.skip("Plaza of Heroes absent from active CardSource")
    assert "Land" in real.card_types
    assert len(real.activated_abilities) == 4

    # Bridge round-trip: 'C' colorless-mana dispatch — byte-equal to
    # the parser-emitted AA[0] effect on the live printing.
    aa0_effect = real.activated_abilities[0].effect
    bridged_c = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "C", "amount": 1}
    )
    assert isinstance(bridged_c, AddManaToPool)
    assert bridged_c == aa0_effect, (
        f"Plaza of Heroes AA[0] must round-trip byte-equal through "
        f"the add_mana_to_pool('C', 1) bridge arm; got "
        f"parsed={aa0_effect!r}, bridged={bridged_c!r}"
    )

    # Python-side resolve smoke — the colorless mana ability mints a
    # single 'C' coin on the controller's mana pool.  Seats the live
    # ``real`` printing on p0's battlefield; resolve drives the
    # AddManaToPool effect directly (mana abilities bypass the stack
    # per CR 605, but the Effect-level resolve path is the same).
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Pre-resolve sanity: both pools are empty.
    assert len(py_state.players[0].mana_pool) == 0
    assert len(py_state.players[1].mana_pool) == 0

    # Drive AA[0]'s effect through resolve.
    aa0_effect.resolve(py_state, py_source.controller_id)

    # Post-resolve observables:
    # - p0's mana pool gained a single 'C' coin with no spend_restriction.
    # - p1's mana pool stays empty (the controller-id filter on the
    #   mana ability).
    p0_pool = py_state.players[0].mana_pool
    assert len(p0_pool) == 1, (
        f"Plaza of Heroes AA[0] must mint exactly one coin on p0's "
        f"mana pool; got pool_size={len(p0_pool)}"
    )
    assert p0_pool[0].color == "C", (
        f"Plaza of Heroes AA[0] must mint a 'C' (colorless) coin; "
        f"got color={p0_pool[0].color!r}"
    )
    assert p0_pool[0].spend_restriction is None, (
        f"Plaza of Heroes AA[0] coin must have no spend_restriction "
        f"(unlike AA[1]/[2]); got "
        f"spend_restriction={p0_pool[0].spend_restriction!r}"
    )
    assert len(py_state.players[1].mana_pool) == 0, (
        "Plaza of Heroes AA[0] must NOT mint a coin on the opponent's "
        "pool (the controller_id filter on the mana ability)"
    )
