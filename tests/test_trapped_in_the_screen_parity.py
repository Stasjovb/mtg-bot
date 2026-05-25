"""Trapped in the Screen — per-card real-EoE cross-engine byte-equal
probe (covered_by_construction → PROBED tier flip).

Trapped in the Screen is a ``{2}{W}`` Enchantment (Duskmourn special
guest in the EoE pool — bit-identical effect-class shape to PROBED
Banishing Light but distinct printing carrier):

    "When this enchantment enters, exile target nonland permanent an
    opponent controls until this enchantment leaves the battlefield."

Parser-emitted shape:
    ENTERS + IsSelf trigger →
    ``ExileOpponentsNonlandPermanentUntilLeaves(max_mv=0)``

This module is the **load-bearing PROBED-tier flip evidence** for
Trapped in the Screen. The substrate is already shipped — the FIRST
real-EoE consumer of ``exile_opponents_nonland_permanent_until_leaves``
was Banishing Light (PROBED via
``test_parity_smoke.py::test_cross_engine_real_eoe_banishing_light_etb_
exile_nonland_permanent_until_leaves_parity`` at the I80 lane). This
probe pins the SAME bridge arm against Trapped in the Screen's
distinct printing (per-slug attribution credit — same precedent as
the 2026-05-24 post-flip-reclassification-scout 12-card sweep that
established per-slug attribution even for bit-identical effect-class
shapes).

**Why this is a valid PROBED-tier flip** (re: prior CCCC / IIII / JJJJ
honest-stop drops citing "bit-identical to PROBED Banishing Light"):
the 2026-05-24 sweep precedent (``test_arabella_abandoned_doll_parity``,
``test_terminal_velocity_parity``, etc.) explicitly established that
per-slug attribution credits a PROBED slot per-printing — even when the
underlying Effect+bridge arm is bit-identical to a sibling PROBED card,
the printing-keyed `_PRINTINGS.get("<Card>")` binding inside a canonical
``test_cross_engine_real_eoe_<slug>_..._parity`` function delivers an
independent PROBED-tier slot. Mirrors Optimistic Scavenger's IIII
precedent ("the classifier credits per-slug, not per-effect-class").

Probe shape: same as Banishing Light (P0 source, P1 victim, bait
artifact). The bridge arm is the unit-variant Rust effect
``Effect::ExileOpponentsNonlandPermanentUntilLeaves`` matching Python's
zero-arg ``ExileOpponentsNonlandPermanentUntilLeaves()`` bare default
(``max_mv=0`` = no MV cap, matching Trapped in the Screen's oracle
text which has no MV cap).
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.exile import (
    ExileOpponentsNonlandPermanentUntilLeaves,
)


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Zone constants (mirror Rust's u8 zone IDs).
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3
ZONE_EXILE = 5


# ---------------------------------------------------------------------------
# (1) Parser SoT — Trapped in the Screen is parser-claimed and emits the
# ENTERS+IsSelf+ExileOpponentsNonlandPermanentUntilLeaves(max_mv=0) shape.
# ---------------------------------------------------------------------------


def test_trapped_in_the_screen_parser_claims_card():
    assert "Trapped in the Screen" in _PRINTINGS, (
        "Trapped in the Screen must be parser-claimed by the active "
        "CardSource"
    )


def test_trapped_in_the_screen_printed_attrs():
    """Pins the basic printing surface: enchantment type, {2}{W} cost,
    no Aura subtype (the bare-Enchantment carrier shape distinguishing
    Trapped in the Screen from Aura-shape siblings like Hardlight
    Containment)."""
    p = _PRINTINGS["Trapped in the Screen"]
    assert "Enchantment" in p.card_types
    assert "Aura" not in p.subtypes, (
        "Trapped in the Screen is a bare Enchantment, NOT an Aura"
    )
    assert p.mana_cost.generic == 2
    assert p.mana_cost.colored == (("W", 1),)


def test_trapped_in_the_screen_enters_trigger_shape():
    """The parsed ENTERS+IsSelf trigger emits
    ``ExileOpponentsNonlandPermanentUntilLeaves(max_mv=0)`` — the
    bare-default shape (no MV cap, matching the oracle text)."""
    from mtg_bot.effects.predicates import Event, IsSelf

    p = _PRINTINGS["Trapped in the Screen"]
    enters_tas = [
        ta for ta in p.triggered_abilities if ta.event is Event.ENTERS
    ]
    assert len(enters_tas) == 1, (
        f"Trapped in the Screen must have exactly 1 ENTERS triggered "
        f"ability; got {len(enters_tas)}"
    )
    (ta,) = enters_tas
    assert isinstance(ta.predicate, IsSelf), (
        f"ENTERS predicate must be IsSelf; got {type(ta.predicate).__name__}"
    )
    assert isinstance(ta.effect, ExileOpponentsNonlandPermanentUntilLeaves), (
        f"ENTERS effect must be ExileOpponentsNonlandPermanentUntilLeaves; "
        f"got {type(ta.effect).__name__}"
    )
    assert ta.effect.max_mv == 0, (
        f"ENTERS effect must be max_mv=0 (no MV cap); got "
        f"max_mv={ta.effect.max_mv}"
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the dict shape Trapped in the Screen's safe-
# trigger recognizer emits round-trips to the matching Python class.
# ---------------------------------------------------------------------------


def test_trapped_in_the_screen_bridge_arm_round_trip():
    """The bridge arm ``exile_opponents_nonland_permanent_until_leaves``
    (cross_engine.py:3966) round-trips the bare unit-variant dict shape
    ``{"kind": "exile_opponents_nonland_permanent_until_leaves"}`` to the
    matching Python ``ExileOpponentsNonlandPermanentUntilLeaves()``
    instance (bare default = ``max_mv=0``, no MV cap)."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    rt = _ta_dict_to_python_effect(
        {"kind": "exile_opponents_nonland_permanent_until_leaves"}
    )
    assert isinstance(rt, ExileOpponentsNonlandPermanentUntilLeaves)
    assert rt.max_mv == 0, (
        "bare-default bridge round-trip must yield max_mv=0 "
        "(no MV cap, matching Trapped in the Screen's oracle text)"
    )

    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect.
    p = _PRINTINGS["Trapped in the Screen"]
    (ta,) = p.triggered_abilities
    assert ta.effect == rt, (
        "Trapped in the Screen's parsed Effect must be byte-equal to "
        "the bridged Effect (structural contract for the PROBED tier)"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts the
# bridged trigger dict shape on a Trapped-in-the-Screen-shape carrier.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_trapped_in_the_screen_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the
    ``{"kind": "exile_opponents_nonland_permanent_until_leaves"}``
    dict shape on a Trapped-in-the-Screen-shape Enchantment carrier."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Trapped in the Screen (synthetic carrier)",
            "card_types": ["Enchantment"],
            "mana_cost": {"generic": 2, "W": 1},
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": (
                            "exile_opponents_nonland_permanent_until_leaves"
                        ),
                    },
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Trapped in the Screen printing on Python and a bridged
# synthetic carrier on Rust through the ENTERS+IsSelf dispatch and
# verifies the exile-target-nonland-permanent-an-opponent-controls-
# until-leaves resolve byte-equal.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_trapped_in_the_screen_etb_exile_nonland_permanent_until_leaves_parity():
    """**GENUINE real-EoE cross-engine probe — Trapped in the Screen ETB
    ExileOpponentsNonlandPermanentUntilLeaves(max_mv=0). PROBED-tier
    flip (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Trapped in the Screen printing** on the
    Python side through the existing I80 ``exile_opponents_nonland_
    permanent_until_leaves`` bridge arm — same probe shape as the
    Banishing Light I80 probe at
    ``test_parity_smoke.py::test_cross_engine_real_eoe_banishing_light_
    etb_exile_nonland_permanent_until_leaves_parity``, distinct printing
    carrier (per-slug attribution credit per the 2026-05-24 sweep
    precedent).

    Probe direction: **same-controller** (P0 source, P1 victim). P0
    casts Trapped in the Screen from hand, it ETBs on P0's bf, the
    ETB-trigger picks a P1-controlled bait artifact and exiles it.

    Setup:
      * P1 has a vanilla bait artifact on bf (the opponent non-land
        permanent the ETB will exile — picking an Artifact load-bears
        the I80 widening over the I79 creatures-only picker).
      * Inject Trapped in the Screen onto P0's bf via
        ``register_and_inject_object`` (Rust) / new_object + bf append
        + manual ``_trigger_etb_abilities`` (Python).
      * Both engines dispatch ENTERS for the just-arrived enchantment;
        SourceIsSelf matches, the trigger lands on the stack with
        controller=0.

    Drain both stacks. Assert both engines exile the bait to P1's exile
    zone with the source-link stamped (``exiled_with_source`` /
    ``exiled_by_source``).

    Source-leaves recall: invoke ``return_paired_exiles_for(source_id)``
    / ``_release_exiled_until_leaves(state, source_id)`` — both engines
    return the bait artifact to P1's bf, proving the source-link was
    stamped.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from tests.parity._picker_shims import (
        _PickFirstOpponentTargetCreaturePreferredAgent,
    )

    real = _PRINTINGS.get("Trapped in the Screen")
    if real is None:
        pytest.skip(
            "Trapped in the Screen absent from active CardSource"
        )
    assert "Enchantment" in real.card_types

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Rust: inject bait artifact onto P1's bf ----
    rust_bait_dict = {
        "name": "Trapped Screen Bait Artifact",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 1},
        "effects": [],
        "triggered_abilities": [],
    }
    rust_bait_id = rust_state.register_and_inject_object(
        rust_bait_dict, 1, ZONE_BATTLEFIELD,
    )
    assert rust_state.stack_size() == 0

    # Inject Trapped in the Screen (Enchantment carrier) onto P0's bf.
    rust_source_dict = {
        "name": "Trapped in the Screen",
        "card_types": ["Enchantment"],
        "mana_cost": {"generic": 2, "W": 1},
        "effects": [],
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": (
                        "exile_opponents_nonland_permanent_until_leaves"
                    ),
                },
            }
        ],
    }
    rust_source_id = rust_state.register_and_inject_object(
        rust_source_dict, 0, ZONE_BATTLEFIELD,
    )
    assert rust_state.stack_size() == 1, (
        "Rust: Trapped in the Screen's arrival on P0 should fire the "
        "SourceIsSelf ENTERS trigger and land "
        "ExileOpponentsNonlandPermanentUntilLeaves on the stack. "
        f"Got stack_size={rust_state.stack_size()}"
    )

    # ---- Python side: mirror setup with the real parsed printing ----
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone

    bait_printing = CardPrinting(
        name="Trapped Screen Bait Artifact",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=()),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        triggered_abilities=(),
    )
    py_bait = py_state.new_object(
        bait_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_bait.summoning_sick = False
    py_bait.tapped = False
    py_bait.damage = 0
    py_bait.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_bait)

    # Target-picking agent on P0 (the source's controller).
    py_state.players[0].agent = (
        _PickFirstOpponentTargetCreaturePreferredAgent()
    )

    # Seat the GENUINE parsed Trapped in the Screen printing on P0's bf
    # and fire the ETB trigger manually (the inject-and-fire convention).
    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.summoning_sick = False
    py_source.tapped = False
    py_source.damage = 0
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)
    _trigger_etb_abilities(py_state, py_source)
    assert len(py_state.stack) == 1, (
        "Python: Trapped in the Screen's arrival on P0 should fire "
        "the IsSelf ENTERS trigger and land "
        "ExileOpponentsNonlandPermanentUntilLeaves on the stack. "
        f"Got stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks, then compare ----
    from mtg_bot.actions import resolve_top_of_stack
    while py_state.stack:
        resolve_top_of_stack(py_state)
    from mtg_bot.turn import state_based_actions as py_sba
    py_sba(py_state)
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()
    rust_state.apply_sbas()

    # Stacks empty.
    assert rust_state.stack_size() == 0
    assert len(py_state.stack) == 0

    # Rust post-state: bait left P1's bf, landed in P1's exile.
    rust_p0_bf_after = sum(
        1 for o in rust_state.battlefield_snapshot()
        if int(o["controller_id"]) == 0
    )
    rust_p1_bf_after = sum(
        1 for o in rust_state.battlefield_snapshot()
        if int(o["controller_id"]) == 1
    )
    assert rust_p0_bf_after == 1, (
        f"Rust: P0's bf should still hold the source Enchantment; "
        f"got p0_bf={rust_p0_bf_after}"
    )
    assert rust_p1_bf_after == 0, (
        f"Rust: P1's bf should drop the bait artifact; "
        f"got p1_bf={rust_p1_bf_after}"
    )
    rust_p1_exile_after = rust_state.exile_snapshot(1)
    assert len(rust_p1_exile_after) == 1
    assert (
        rust_p1_exile_after[0]["printing_name"]
        == "Trapped Screen Bait Artifact"
    )
    assert int(rust_p1_exile_after[0]["id"]) == rust_bait_id

    # Python post-state: same shape.
    py_p0_bf_after = sum(
        1 for o in py_state.battlefield if o.controller_id == 0
    )
    py_p1_bf_after = sum(
        1 for o in py_state.battlefield if o.controller_id == 1
    )
    assert py_p0_bf_after == 1
    assert py_p1_bf_after == 0
    assert len(py_state.players[1].exile) == 1
    assert (
        py_state.players[1].exile[0].printing.name
        == "Trapped Screen Bait Artifact"
    )
    assert py_state.players[1].exile[0].id == py_bait.id

    # ---- Source-leaves recall: bait returns to P1's bf ----
    rust_returned = rust_state.return_paired_exiles_for(rust_source_id)
    assert rust_returned == 1, (
        f"Rust source-leaves recall should return exactly 1 paired "
        f"exile (the bait artifact); got {rust_returned}"
    )
    rust_p1_bf_post_recall = sum(
        1 for o in rust_state.battlefield_snapshot()
        if int(o["controller_id"]) == 1
    )
    assert rust_p1_bf_post_recall == 1, (
        f"Rust post-recall: P1's bf should hold the returned bait; "
        f"got={rust_p1_bf_post_recall}"
    )
    assert len(rust_state.exile_snapshot(1)) == 0

    from mtg_bot.turn import _release_exiled_until_leaves
    _release_exiled_until_leaves(py_state, py_source.id)
    py_p1_bf_post_recall = sum(
        1 for o in py_state.battlefield if o.controller_id == 1
    )
    assert py_p1_bf_post_recall == 1
    assert len(py_state.players[1].exile) == 0
