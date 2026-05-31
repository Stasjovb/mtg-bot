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
constant). The Rust substrate landed in THIS slice:

  * ``Effect::DestroyEachNonlandPermanentWithMVEqualToSourceCharge
    Counters`` unit variant (cards.rs) + parse arm + ``to_pydict`` arm
    + valid-kinds entry.
  * Resolve arm (state_ops_resolve.rs, beside ``ExileAllArtifactsWith
    ManaValueAtMost``): reads ``source.charge_counters`` across all
    zones (the source is typically a now-sacrificed Blast Zone in the
    graveyard -- the count survives the sacrifice), then destroys every
    nonland permanent on either bf whose printed MV equals that count,
    skipping lands + indestructible permanents. Mirrors the
    ``DestroyAllCreatures`` graveyard-move body.
  * Cross-engine bridge: dict->Python arm (cross_engine.py) + Python->
    dict ``_leaf`` (trajectory.py) -- both field-free, byte-equal
    round-trip.

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


# ---------------------------------------------------------------------------
# (1) VERIFY-FIRST: freeze the parsed Blast Zone printing's AA shape.
# ---------------------------------------------------------------------------


def test_real_eoe_blast_zone_parsed_printing_shape():
    """**Verify-first.** The live parser maps Blast Zone to the AA shape
    this probe drives. Freeze the parser SoT so a parser drift is caught
    here, not silently downstream."""
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
    # AA[1]: the destroy wipe + sacrifice-self cost.
    assert isinstance(
        aas[1].effect,
        DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters,
    )
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
    assert d == {
        "kind": (
            "destroy_each_nonland_permanent_with_mv_equal_to_"
            "source_charge_counters"
        ),
    }
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(
        rebuilt, DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters
    )
    assert rebuilt == eff


# ---------------------------------------------------------------------------
# (3) Synthetic battlefield seater -- shared by the resolve probes.
# Seats a Blast-Zone-shaped SOURCE carrying the destroy effect with
# `charge_counters = count` on p0's bf, plus victim/survivor permanents
# of given MVs split across both players. Drives the destroy effect via
# the proven `push_to_stack` + `resolve_top_of_stack` synthetic shape
# (the destroy effect reads the source's charge counters mid-resolve,
# BEFORE the source's post-resolve move).
# ---------------------------------------------------------------------------


_DESTROY_KIND = (
    "destroy_each_nonland_permanent_with_mv_equal_to_source_charge_counters"
)


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


def _build_py_source_and_victims(py, count, victims, destroy_effect):
    """Python: seat a Blast-Zone-shaped SOURCE on p0's bf carrying the
    GENUINE parsed destroy effect as an ENTERS-triggered ability
    (predicate=IsSelf, ``count`` charge counters) + the given victims on
    the battlefield. ``victims`` is a list of ``(name, mv, owner_id)``
    tuples; ``destroy_effect`` is the genuine parsed AA[1] effect.
    Returns the source GameObject.

    **Why an ENTERS trigger (not a spell_effect).** The destroy effect
    reads ``state.resolving_source.charge_counters`` at resolution time,
    and only the ability-resolution path (triggered / activated) seats
    ``resolving_source`` -- the instant/sorcery spell-resolution branch
    does NOT (``actions.py:2782``). Driving the effect as the source's
    ENTERS-triggered ability is the faithful shape (real Blast Zone's
    payoff is an *activated* ability; the ENTERS trigger is the lowest-
    cost cross-engine driver that seats the source identically on both
    engines). The source is a Land, so it is intrinsically skipped by
    the wipe's nonland filter -- it is never a victim regardless of MV.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects import TriggeredAbility
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

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
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=destroy_effect,
            ),
        ),
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
    return src


def _drive_py_destroy(py, src):
    from mtg_bot.actions import _trigger_etb_abilities, resolve_top_of_stack
    from mtg_bot.turn import state_based_actions

    # Fire the source's ENTERS triggers (seats resolving_source on the
    # ability-resolution path), drain the stack, run SBAs.
    _trigger_etb_abilities(py, src)
    while py.stack:
        resolve_top_of_stack(py)
    state_based_actions(py)


def _build_rust_source_and_victims(rs, count, victims):
    # Source is a Land on p0's bf carrying the destroy effect as an
    # ENTERS-triggered ability (predicate=source_is_self) + charge
    # counters; `dispatch_enters` fires the trigger, `resolve_top_of_
    # stack` drives it. The source is a Land -> never a wipe victim.
    src = rs.register_and_inject_object(
        {
            "name": "Blast Zone Source",
            "card_types": ["Land"],
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {"kind": _DESTROY_KIND},
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
    return src


def _drive_rust_destroy(rs, src):
    rs.dispatch_enters(src)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe -- the headline.
# Source with 2 charge counters; MV-2 victims on both players die,
# MV-1 + MV-3 survivors live, lands untouched.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_blast_zone_destroy_wipe_parity():
    """**GENUINE real-EoE cross-engine byte-equal probe -- Blast Zone
    wipe at charge_counters=2. PROBED tier flip evidence.**

    Pre-state on both engines (identical):
      * Blast-Zone-shaped source on p0's bf carrying
        ``DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters``
        with ``charge_counters = 2``.
      * p0 bf: MV-2 artifact (DIES), MV-1 artifact (LIVES).
      * p1 bf: MV-2 artifact (DIES), MV-3 artifact (LIVES).

    Drive + observe: the destroy effect reads the source's 2 charge
    counters and destroys EVERY nonland permanent with MV 2 on either
    bf (the source itself is a Land -> skipped). Post-resolve, the
    surviving non-source permanents (MV 1, MV 3) remain; the MV-2
    victims are in their OWN controllers' graveyards. Byte-equal on
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

    # Genuine parsed Blast Zone AA[1] effect drives the Python source.
    real = get_active_source().get_printings().get("Blast Zone")
    if real is None:
        pytest.skip("Blast Zone absent from active CardSource")
    destroy_effect = real.activated_abilities[1].effect
    assert isinstance(
        destroy_effect,
        DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters,
    )

    victims = [
        ("MV2 P0 victim", 2, 0),
        ("MV1 P0 survivor", 1, 0),
        ("MV2 P1 victim", 2, 1),
        ("MV3 P1 survivor", 3, 1),
    ]
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())

    py = build_python_state(spec)
    py_src = _build_py_source_and_victims(py, 2, victims, destroy_effect)
    _drive_py_destroy(py, py_src)

    rs = build_rust_state(spec)
    rs_src = _build_rust_source_and_victims(rs, 2, victims)
    _drive_rust_destroy(rs, rs_src)

    # ---- Post-state observable: surviving bf non-source permanents +
    # per-player graveyard contents. Byte-equal across engines.
    # P0 bf survivors (the source is a Land, never wiped; MV-1 survives).
    py_p0_bf = sorted(_zone_names_py(py, 0, "battlefield"))
    rs_p0_bf = sorted(_zone_names_rust(rs, 0, "battlefield"))
    assert py_p0_bf == rs_p0_bf
    assert py_p0_bf == sorted(["Blast Zone Source", "MV1 P0 survivor"])

    py_p1_bf = sorted(_zone_names_py(py, 1, "battlefield"))
    rs_p1_bf = sorted(_zone_names_rust(rs, 1, "battlefield"))
    assert py_p1_bf == rs_p1_bf
    assert py_p1_bf == ["MV3 P1 survivor"]

    # Graveyards: each MV-2 victim in its OWN controller's graveyard.
    py_p0_gy = sorted(_zone_names_py(py, 0, "graveyard"))
    rs_p0_gy = sorted(_zone_names_rust(rs, 0, "graveyard"))
    assert py_p0_gy == rs_p0_gy
    assert py_p0_gy == ["MV2 P0 victim"]

    py_p1_gy = sorted(_zone_names_py(py, 1, "graveyard"))
    rs_p1_gy = sorted(_zone_names_rust(rs, 1, "graveyard"))
    assert py_p1_gy == rs_p1_gy
    assert py_p1_gy == ["MV2 P1 victim"]


# ---------------------------------------------------------------------------
# (5) Edge: charge_counters=0 destroys MV-0 permanents (oracle-compliant
# "each nonland permanent with MV 0"). Lands still skipped.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_blast_zone_zero_counters_wipes_mv0_parity():
    """**Edge probe -- charge_counters=0 wipes MV-0 nonland permanents.**

    At 0 charge counters, the effect destroys every nonland permanent
    with printed MV 0 (Python's docstring explicitly calls out this
    edge). An MV-1 permanent survives; the Land source survives. Byte-
    equal on both engines.
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

    # Genuine parsed Blast Zone AA[1] effect drives the Python source.
    real = get_active_source().get_printings().get("Blast Zone")
    if real is None:
        pytest.skip("Blast Zone absent from active CardSource")
    destroy_effect = real.activated_abilities[1].effect
    assert isinstance(
        destroy_effect,
        DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters,
    )

    victims = [
        ("MV0 victim", 0, 0),
        ("MV1 survivor", 1, 1),
    ]
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())

    py = build_python_state(spec)
    py_src = _build_py_source_and_victims(py, 0, victims, destroy_effect)
    _drive_py_destroy(py, py_src)

    rs = build_rust_state(spec)
    rs_src = _build_rust_source_and_victims(rs, 0, victims)
    _drive_rust_destroy(rs, rs_src)

    py_p0_bf = sorted(_zone_names_py(py, 0, "battlefield"))
    rs_p0_bf = sorted(_zone_names_rust(rs, 0, "battlefield"))
    assert py_p0_bf == rs_p0_bf
    assert py_p0_bf == ["Blast Zone Source"]

    py_p0_gy = sorted(_zone_names_py(py, 0, "graveyard"))
    rs_p0_gy = sorted(_zone_names_rust(rs, 0, "graveyard"))
    assert py_p0_gy == rs_p0_gy
    assert py_p0_gy == ["MV0 victim"]

    py_p1_bf = sorted(_zone_names_py(py, 1, "battlefield"))
    rs_p1_bf = sorted(_zone_names_rust(rs, 1, "battlefield"))
    assert py_p1_bf == rs_p1_bf
    assert py_p1_bf == ["MV1 survivor"]
