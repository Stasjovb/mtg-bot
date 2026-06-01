"""Blast Zone -- per-card real-EoE cross-engine byte-equal probe
(``blocked_subsystem_gated`` -> PROBED tier flip; the genuinely-new
``DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters`` Effect
substrate's closure marker).

**Card (real EoE printing).** Blast Zone is a ``Land`` that enters
tapped with a charge counter and carries:

  * ENTERS trigger: ``PutChargeCountersOnSelf(amount=1)``.
  * AA[0]: ``PutChargeCountersOnSelf(amount=1, amount_from_x=True)``
    (cost ``{X}{X}`` + tap-self -- the parser's cross-wired charge-add
    AA; see VERIFY-FIRST note below).
  * AA[1]: ``DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters``
    (cost ``{3}`` + tap-self + **sacrifice-self**) -- the payoff wipe.

**VERIFY-FIRST (the parsed printing, NOT the printed oracle text).**
The live parser maps Blast Zone's two AAs in a shape that differs from
the printed card -- the ``{X}{X}`` cost lands on the charge-add AA and
the ``{3}`` + sac-self cost lands on the destroy AA. Cross-engine parity
is defined against the PARSED printing (both engines consume the same
parsed form), so this probe drives the parsed shape. The first test
below freezes that parser SoT.

**The genuinely-new piece.** ``DestroyEachNonlandPermanentWithMVEqual
ToSourceChargeCounters`` is a board wipe whose MV filter is read at
resolution time from the SOURCE's ``charge_counters`` (NOT a parse-time
constant). The Rust substrate (Effect variant + parse/to_pydict/valid-
kinds + resolve arm + cross-engine bridge) landed in the prior slice.

**This slice (2026-06-01, ``feature/blast-zone-aa-cost``) -- the REAL
activated-ability cost path.** The earlier probe drove the wipe via an
ENTERS-trigger shim (the lowest-cost cross-engine driver that seats
``resolving_source`` identically). This slice replaces that shim with
the GENUINE ``ActivateAbility`` cost-payment path on BOTH engines:

  * Python ``actions._activate_ability``: pays ``{3}`` mana from the
    pool (auto-tap), taps the source (``tap_self``), sacrifices the
    source (``sacrifice_self`` -> ``turn.sacrifice`` moves it to the
    graveyard), then pushes the AA onto the stack;
    ``resolve_top_of_stack`` seats ``state.resolving_source = item.
    source`` (the now-sacrificed GameObject, whose ``charge_counters``
    survived the move) and fires the wipe.
  * Rust ``Action::ActivateAbility`` (``state_ops_actions.rs``): the
    SAME three cost atoms -- ``mana`` via ``auto_tap_pay_for_cost``,
    ``tap_self`` (Phase 5), ``sacrifice_self`` (Phase 5b, which does
    NOT zero ``charge_counters`` on the way to the graveyard) -- then
    pushes a ``new_trigger`` StackItem carrying ``source_obj_id``;
    ``resolve_top_of_stack`` fires the wipe whose resolve arm scans
    all zones (incl. the graveyard) for ``source_obj_id`` and reads
    its surviving ``charge_counters`` as the filter MV (last-known-
    info, since the source sacrificed itself).

No new Rust cost atom was required -- the ``{3}`` + ``tap_self`` +
``sacrifice_self`` shape is exactly what the CE20 activated-ability
substrate + the Lander sacrifice-self cost-commit already support.

**Resolve semantics (parity-load-bearing).**
  * MV computation: ``generic + W + U + B + R + G`` (X = 0 off-stack
    per CR 202.3b) -- mirrors Python's ``printing.mana_cost.total``.
  * Lands skipped (Blast Zone never wipes lands).
  * Indestructible honored inline (CR 702.12).
  * Each victim goes to its OWN controller's graveyard.
  * MV-0 token edge: a token has printed MV 0 and IS destroyed when the
    source has 0 charge counters (oracle-compliant; both engines honor).

This module lives OUTSIDE ``test_parity_smoke.py`` (per the concurrent-
agent merge-conflict-minimization convention) and is registered in
``scripts/measure_pool_parity.PROBE_MODULES`` so the
``test_cross_engine_real_eoe_blast_zone_*_parity`` functions credit the
card to the PROBED tier.
"""

from __future__ import annotations

import importlib.util

import pytest


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)

# Zone constants (Rust int encoding).
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3

# The destroy effect's serialized kind tag (field-free unit variant).
_DESTROY_KIND = (
    "destroy_each_nonland_permanent_with_mv_equal_to_source_charge_counters"
)


# ---------------------------------------------------------------------------
# (1) VERIFY-FIRST: freeze the parsed Blast Zone printing's AA shape.
# ---------------------------------------------------------------------------


def test_real_eoe_blast_zone_parsed_printing_shape():
    """**Verify-first.** The live parser maps Blast Zone to the AA shape
    this probe drives. Freeze the parser SoT so a parser drift is caught
    here, not silently downstream. The destroy AA's cost is the exact
    ``{3}`` mana + tap-self + sacrifice-self shape the real-AA probes
    below pay end-to-end."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.counters import PutChargeCountersOnSelf
    from mtg_bot.effects.generic.destroy import (
        DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters,
    )

    p = get_active_source().get_printings().get("Blast Zone")
    if p is None:
        pytest.skip("Blast Zone absent from active CardSource")
    assert "Land" in p.card_types
    # ENTERS trigger puts a charge counter on self.
    assert any(
        isinstance(ta.effect, PutChargeCountersOnSelf)
        for ta in p.triggered_abilities
    )
    aas = p.activated_abilities
    assert len(aas) == 2
    # AA[0]: charge-add (amount_from_x).
    assert isinstance(aas[0].effect, PutChargeCountersOnSelf)
    # AA[1]: the destroy wipe -- the EXACT cost shape the real-AA probes
    # pay: {3} generic mana + tap-self + sacrifice-self.
    assert isinstance(
        aas[1].effect,
        DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters,
    )
    assert aas[1].cost.mana.generic == 3
    assert aas[1].cost.mana.colored == ()
    assert aas[1].cost.mana.x_pips == 0
    assert aas[1].cost.tap_self is True
    assert aas[1].cost.sacrifice_self is True


# ---------------------------------------------------------------------------
# (2) Bridge round-trip pin: field-free unit-variant byte-equal.
# ---------------------------------------------------------------------------


def test_cross_engine_blast_zone_destroy_effect_serializer_round_trip():
    """The trajectory reverse-serializer emits a clean field-free dict
    AND the dict->Python bridge reconstructs the original effect."""
    from mtg_bot.effects.generic.destroy import (
        DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters,
    )
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    eff = DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters()
    d = trajectory._python_spell_effect_to_dict(eff)
    assert d == {"kind": _DESTROY_KIND}
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(
        rebuilt, DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters
    )
    assert rebuilt == eff


# ---------------------------------------------------------------------------
# (3) Real-AA seaters -- shared by the resolve probes.
#
# Seats a Blast-Zone-shaped SOURCE on p0's bf carrying the GENUINE parsed
# destroy AA (``{3}`` + tap-self + sacrifice-self) with ``charge_counters
# = count``, plus victim/survivor permanents of given MVs split across
# both players. Pre-funds p0's pool with {3} generic so the real
# ``ActivateAbility`` cost path can be paid, then DRIVES the wipe by
# activating AA-index-0 (the destroy AA is the only AA on the synthetic
# source), paying mana + tap + sacrifice-self, pushing the AA onto the
# stack, and resolving it.
#
# **Why the real AA (not the ETB shim).** The prior probe used an
# ENTERS-trigger shim because it was the lowest-cost cross-engine driver
# that seated ``resolving_source`` identically. This slice closes that
# shortcut: both engines now pay the genuine activated-ability cost
# (mana + tap_self + sacrifice_self) and reach the (already-byte-equal)
# resolve. The source's ``charge_counters`` survive the sacrifice (the
# source is in the graveyard at resolve time -- last-known-info), and the
# resolve arm reads the count via an all-zones scan on both engines.
# ---------------------------------------------------------------------------


def _build_py_source_and_victims(py, count, victims, destroy_aa):
    """Python: seat a Blast-Zone-shaped SOURCE on p0's bf carrying the
    GENUINE parsed destroy ACTIVATED ability (``destroy_aa``, cost
    ``{3}`` + tap-self + sacrifice-self) + ``count`` charge counters +
    the given victims. ``victims`` is a list of ``(name, mv, owner_id)``
    tuples. Pre-funds p0's pool with {3} generic so the cost is payable.
    Returns the source GameObject.

    The source is a Land, so it is intrinsically skipped by the wipe's
    nonland filter -- it is never a victim regardless of MV (it leaves
    the bf via the sacrifice cost anyway).
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import ManaCoin, Zone

    src_printing = CardPrinting(
        name="Blast Zone Source",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Land",
        supertypes=(),
        card_types=("Land",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        activated_abilities=(destroy_aa,),
    )
    src = py.new_object(src_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    src.summoning_sick = False
    src.charge_counters = count
    py.battlefield.append(src)
    for name, mv, owner in victims:
        vp = CardPrinting(
            name=name,
            mana_cost_str="",
            mana_cost=ManaCost(generic=mv),
            type_line="Artifact",
            supertypes=(),
            card_types=("Artifact",),
            subtypes=(),
            power=None,
            toughness=None,
            produces=frozenset(),
        )
        vo = py.new_object(vp, owner_id=owner, zone=Zone.BATTLEFIELD)
        vo.summoning_sick = False
        py.battlefield.append(vo)
    # Pre-fund p0's pool with {3} generic so the real cost is payable.
    for _ in range(3):
        py.players[0].mana_pool.append(ManaCoin(color="C"))
    return src


def _drive_py_destroy(py, src):
    """Drive the wipe via the GENUINE activated-ability cost path: pay
    ``{3}`` + tap-self + sacrifice-self, push the AA onto the stack,
    drain the stack, run SBAs. The destroy AA is the only AA on the
    synthetic source, so it is at index 0."""
    from mtg_bot.actions import _activate_ability, resolve_top_of_stack
    from mtg_bot.turn import state_based_actions

    _activate_ability(py, 0, src.id, 0)
    while py.stack:
        resolve_top_of_stack(py)
    state_based_actions(py)


def _build_rust_source_and_victims(rs, count, victims):
    """Rust: seat a Blast-Zone-shaped SOURCE on p0's bf carrying the
    destroy effect as a GENUINE activated ability (cost ``{3}`` mana +
    tap-self + sacrifice-self) + ``count`` charge counters + the given
    victims. Pre-funds p0's pool with {3} colorless so the real
    ``ActivateAbility`` cost path can auto-pay. Returns the source id."""
    src = rs.register_and_inject_object(
        {
            "name": "Blast Zone Source",
            "card_types": ["Land"],
            "effects": [],
            "activated_abilities": [
                {
                    "cost": {
                        "mana": {"generic": 3},
                        "tap_self": True,
                        "sacrifice_self": True,
                    },
                    "effect": {"kind": _DESTROY_KIND},
                    "is_mana_ability": False,
                },
            ],
        },
        0,
        ZONE_BATTLEFIELD,
    )
    if count != 0:
        rs.set_charge_counters(src, count)
    for name, mv, owner in victims:
        rs.register_and_inject_object(
            {
                "name": name,
                "card_types": ["Artifact"],
                "mana_cost": {"generic": mv},
                "effects": [],
            },
            owner,
            ZONE_BATTLEFIELD,
        )
    rs.add_mana(0, "C", 3)
    return src


def _drive_rust_destroy(rs, src):
    """Drive the wipe via the GENUINE ``ActivateAbility`` cost path:
    pay ``{3}`` (auto-tap) + tap-self + sacrifice-self, push the AA
    onto the stack, drain the stack, run SBAs."""
    rs.apply_action(
        {
            "kind": "activate_ability",
            "source_id": src,
            "ability_index": 0,
        }
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()


def _zone_names_py(py, player_id, zone_attr):
    if zone_attr == "battlefield":
        # Python uses a centralized `state.battlefield`; filter by
        # controller (Rust groups per-player, so compare controller-
        # filtered slices on both sides).
        return [
            o.printing.name
            for o in py.battlefield
            if o.controller_id == player_id
        ]
    return [o.printing.name for o in getattr(py.players[player_id], zone_attr)]


def _zone_names_rust(rs, player_id, zone):
    if zone == "battlefield":
        snap = rs.battlefield_snapshot()
        return [
            d["printing_name"]
            for d in snap
            if d["controller_id"] == player_id
        ]
    snap = rs.graveyard_snapshot(player_id)
    return [d["printing_name"] for d in snap]


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe -- the headline.
# Source with 2 charge counters; MV-2 victims on both players die,
# MV-1 + MV-3 survivors live, lands untouched. Driven by the REAL
# activated-ability cost path (mana + tap + sacrifice-self) on BOTH
# engines -- NOT the ETB-trigger shim the earlier probe used.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_blast_zone_destroy_wipe_parity():
    """**GENUINE real-EoE cross-engine byte-equal probe -- Blast Zone
    wipe at charge_counters=2, driven by the REAL activated-ability
    cost path. PROBED tier flip evidence.**

    Pre-state on both engines (identical):
      * Blast-Zone-shaped source on p0's bf carrying the GENUINE parsed
        ``DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters``
        AA (cost ``{3}`` + tap-self + sacrifice-self) with
        ``charge_counters = 2``; p0's pool pre-funded with ``{3}``.
      * p0 bf: MV-2 artifact (DIES), MV-1 artifact (LIVES).
      * p1 bf: MV-2 artifact (DIES), MV-3 artifact (LIVES).

    Drive: activate the AA -- pay ``{3}`` (auto-tap), tap the source,
    sacrifice the source (it moves to p0's graveyard with its 2 charge
    counters intact), push the AA, resolve it. The destroy effect reads
    the source's 2 charge counters (last-known-info from the graveyard)
    and destroys EVERY nonland permanent with MV 2 on either bf (the
    source is a Land -> never a victim, and it is gone anyway).

    Observe: the surviving non-source permanents (MV 1, MV 3) remain;
    the MV-2 victims are in their OWN controllers' graveyards; the
    sacrificed Blast Zone source is in p0's graveyard. Byte-equal on
    both engines.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.destroy import (
        DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters,
    )
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
    )

    # Genuine parsed Blast Zone AA[1] drives the Python source.
    real = get_active_source().get_printings().get("Blast Zone")
    if real is None:
        pytest.skip("Blast Zone absent from active CardSource")
    destroy_aa = real.activated_abilities[1]
    assert isinstance(
        destroy_aa.effect,
        DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters,
    )
    assert destroy_aa.cost.sacrifice_self is True
    assert destroy_aa.cost.tap_self is True
    assert destroy_aa.cost.mana.generic == 3

    victims = [
        ("MV2 P0 victim", 2, 0),
        ("MV1 P0 survivor", 1, 0),
        ("MV2 P1 victim", 2, 1),
        ("MV3 P1 survivor", 3, 1),
    ]
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())

    py = build_python_state(spec)
    py_src = _build_py_source_and_victims(py, 2, victims, destroy_aa)
    _drive_py_destroy(py, py_src)

    rs = build_rust_state(spec)
    rs_src = _build_rust_source_and_victims(rs, 2, victims)
    _drive_rust_destroy(rs, rs_src)

    # ---- Post-state observable: surviving bf non-source permanents +
    # per-player graveyard contents. Byte-equal across engines.
    # P0 bf survivors (source sacrificed; MV-1 survives).
    py_p0_bf = sorted(_zone_names_py(py, 0, "battlefield"))
    rs_p0_bf = sorted(_zone_names_rust(rs, 0, "battlefield"))
    assert py_p0_bf == rs_p0_bf
    assert py_p0_bf == ["MV1 P0 survivor"]

    py_p1_bf = sorted(_zone_names_py(py, 1, "battlefield"))
    rs_p1_bf = sorted(_zone_names_rust(rs, 1, "battlefield"))
    assert py_p1_bf == rs_p1_bf
    assert py_p1_bf == ["MV3 P1 survivor"]

    # Graveyards: the sacrificed source + the MV-2 victim land in p0's
    # graveyard; p1's MV-2 victim in p1's graveyard.
    py_p0_gy = sorted(_zone_names_py(py, 0, "graveyard"))
    rs_p0_gy = sorted(_zone_names_rust(rs, 0, "graveyard"))
    assert py_p0_gy == rs_p0_gy
    assert py_p0_gy == sorted(["Blast Zone Source", "MV2 P0 victim"])

    py_p1_gy = sorted(_zone_names_py(py, 1, "graveyard"))
    rs_p1_gy = sorted(_zone_names_rust(rs, 1, "graveyard"))
    assert py_p1_gy == rs_p1_gy
    assert py_p1_gy == ["MV2 P1 victim"]


# ---------------------------------------------------------------------------
# (5) Edge: charge_counters=0 destroys MV-0 permanents (oracle-compliant
# "each nonland permanent with MV 0"). Lands still skipped. Driven by the
# REAL activated-ability cost path on both engines. This edge also pins
# the last-known-info survival of charge_counters across the sacrifice:
# the source sacrifices itself (count 0), and the resolve reads 0 from
# the graveyard, wiping MV-0 permanents.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_blast_zone_zero_counters_wipes_mv0_parity():
    """**Edge probe -- charge_counters=0 wipes MV-0 nonland permanents,
    driven by the REAL activated-ability cost path.**

    At 0 charge counters, the effect destroys every nonland permanent
    with printed MV 0. An MV-1 permanent survives; the Land source is
    sacrificed (to p0's graveyard). Byte-equal on both engines.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.destroy import (
        DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters,
    )
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
    )

    # Genuine parsed Blast Zone AA[1] drives the Python source.
    real = get_active_source().get_printings().get("Blast Zone")
    if real is None:
        pytest.skip("Blast Zone absent from active CardSource")
    destroy_aa = real.activated_abilities[1]
    assert isinstance(
        destroy_aa.effect,
        DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters,
    )

    victims = [
        ("MV0 victim", 0, 0),
        ("MV1 survivor", 1, 1),
    ]
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())

    py = build_python_state(spec)
    py_src = _build_py_source_and_victims(py, 0, victims, destroy_aa)
    _drive_py_destroy(py, py_src)

    rs = build_rust_state(spec)
    rs_src = _build_rust_source_and_victims(rs, 0, victims)
    _drive_rust_destroy(rs, rs_src)

    # P0 bf: source sacrificed; MV-0 victim destroyed -> empty.
    py_p0_bf = sorted(_zone_names_py(py, 0, "battlefield"))
    rs_p0_bf = sorted(_zone_names_rust(rs, 0, "battlefield"))
    assert py_p0_bf == rs_p0_bf
    assert py_p0_bf == []

    # P0 graveyard: the sacrificed source + the MV-0 victim.
    py_p0_gy = sorted(_zone_names_py(py, 0, "graveyard"))
    rs_p0_gy = sorted(_zone_names_rust(rs, 0, "graveyard"))
    assert py_p0_gy == rs_p0_gy
    assert py_p0_gy == sorted(["Blast Zone Source", "MV0 victim"])

    py_p1_bf = sorted(_zone_names_py(py, 1, "battlefield"))
    rs_p1_bf = sorted(_zone_names_rust(rs, 1, "battlefield"))
    assert py_p1_bf == rs_p1_bf
    assert py_p1_bf == ["MV1 survivor"]
