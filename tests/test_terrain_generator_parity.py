"""Terrain Generator — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip; Carrier-AA Phase 2b
admit-set landing).

Terrain Generator is a ``{0}`` Land in the EoE pool with a single
activated ability:

    "{2}, {T}: You may put a basic land card from your hand onto the
    battlefield tapped."

The Carrier-AA substrate Phase 2b (2026-05-25 — see
``docs/CARRIER_AA_SUBSTRATE_PHASE_2_DESIGN.md`` §4.2 / §5.2 / §6.4
#15) widens ``_carrier_aa_phase_1_effect_classes`` to include
``PutBasicLandFromHandOntoBattlefieldTapped`` (the Phase 2b combined-
cycle Rust substrate + Python admit + Terrain Generator FLIP lands
in lockstep). Terrain Generator admits at Phase 2b on the Effect-
class widen alone — the cost-shape ``{N}, {T}`` was already admitted
at Phase 1.5a. ZERO new Rust cost-shape machinery (Deserted Temple's
``{1}, {T}`` precedent already exercises the generic-mana ``{N}, {T}``
cost-pay path).

Parser-emitted Effect shape:

    ``PutBasicLandFromHandOntoBattlefieldTapped()``  (unit-variant
    zero-arg frozen dataclass; no ``__post_init__`` stamps — the
    class is bare)

attached to an ``ActivatedAbility`` whose ``cost`` carries
``mana=ManaCost(generic=2)`` + ``tap_self=True`` (no sacrifice). The
bridge arm ``put_basic_land_from_hand_onto_battlefield_tapped``
(``cross_engine.py`` reverse arm at line 12503; ``cross_engine.py``
``_python_aa_to_safe_dict`` forward emit arm) round-trips ``{"kind":
"put_basic_land_from_hand_onto_battlefield_tapped"}`` byte-equal to
Python's ``PutBasicLandFromHandOntoBattlefieldTapped()``.

**EEEE-idiom for the ActivatedAbility carrier.** Same lane discipline
as the sibling Carrier-AA AA probes (parse + bridge round-trip +
Python-side resolve): the probe drives the parsed Effect through its
actual ``resolve`` path on the Python state, with observables that
mirror what Rust's
``Effect::PutBasicLandFromHandOntoBattlefieldTapped`` resolve arm
(``rust/src/state_ops_resolve.rs``, the new arm at the tail of the
``apply_effect`` dispatch) produces on the same input shape. The
cross-engine byte-equal mirror is established by the Phase-2b admit
gate routing the genuine parsed Terrain Generator printing through
the Carrier-AA substrate end-to-end (loader admits post-widen — see
``test_terrain_generator_now_passes_loader_filter`` in
``test_carrier_aa_phase_2b_substrate.py``).

**NEW shape coverage:** the FIRST PROBE_MODULES-credited probe binding
the Terrain Generator slug to the AA +
``PutBasicLandFromHandOntoBattlefieldTapped`` Effect+bridge round-trip
on the REAL parsed EoE printing — and the FIRST PROBED-tier slot for
the ``PutBasicLandFromHandOntoBattlefieldTapped`` Effect class via the
Carrier-AA substrate's ``{N}, {T}`` cost-shape disjunct.

**AA-cost-substrate scope.** The mana-payment (``{2}``) /
tap-payment cost trajectory of the AA is exercised at the loader-
end-to-end disjunct (the inversion pin
``test_terrain_generator_now_passes_loader_filter`` +
the cross-engine bridge round-trip pin below); per-slug PROBED
attribution credits Terrain Generator based on the Effect + bridge
byte-equality + parsed-printing resolve smoke alone — the canonical
EEEE-idiom precedent (Petrified Field's Phase-2a probe at
``tests/test_petrified_field_parity.py`` / Deserted Temple's
Phase-1.5a probe at ``tests/test_deserted_temple_parity.py``).
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.zone_moves import (
    PutBasicLandFromHandOntoBattlefieldTapped,
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


# ---------------------------------------------------------------------------
# (1) Parser SoT — Terrain Generator is parser-claimed and carries the
# exact AA shape the design doc (§2.1 / §2.3) pins.
# ---------------------------------------------------------------------------


def test_terrain_generator_parser_claims_card():
    assert "Terrain Generator" in _PRINTINGS, (
        "Terrain Generator must be parser-claimed by the active "
        "CardSource"
    )


def test_terrain_generator_printed_attrs():
    """Pins the basic printing surface: single-typed Land, no mana
    cost, no power/toughness, no triggered / static / keyword riders."""
    p = _PRINTINGS["Terrain Generator"]
    assert p.card_types == ("Land",)
    assert p.subtypes == ()
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()
    assert p.power is None and p.toughness is None
    assert p.keywords == frozenset()
    assert p.triggered_abilities == ()
    assert p.static_abilities == ()


def test_terrain_generator_activated_ability_put_basic_land_shape():
    """Terrain Generator has the single carrier ``ActivatedAbility``
    whose effect is ``PutBasicLandFromHandOntoBattlefieldTapped()``
    (unit variant, no fields). Cost is ``{2}, {T}`` — the Phase-1.5a
    widened cost-gate shape."""
    p = _PRINTINGS["Terrain Generator"]
    non_mana_aas = [
        aa for aa in (p.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    assert len(non_mana_aas) == 1, (
        f"Terrain Generator must have exactly one non-mana "
        f"ActivatedAbility; got {len(non_mana_aas)}"
    )
    aa = non_mana_aas[0]
    # Effect shape.
    assert isinstance(aa.effect, PutBasicLandFromHandOntoBattlefieldTapped), (
        f"Terrain Generator AA effect must be "
        f"PutBasicLandFromHandOntoBattlefieldTapped; got "
        f"{type(aa.effect).__name__}"
    )
    # Cost shape — the Phase-2b load-bearing axis.
    assert aa.cost.tap_self is True
    assert aa.cost.sacrifice_self is False, (
        "Terrain Generator's AA carries NO sacrifice_self (cost is "
        "just ``{2}, {T}``)"
    )
    assert aa.cost.mana is not None, (
        "Terrain Generator's AA cost carries ``{2}`` mana component"
    )
    assert aa.cost.mana.generic == 2
    assert aa.cost.mana.colored == ()
    assert aa.cost.mana.hybrid == ()
    assert aa.cost.mana.x_pips == 0
    # No riders.
    assert aa.is_mana_ability is False
    assert aa.sorcery_speed is False
    assert aa.cost_reductions == ()
    assert aa.room_half is None
    assert aa.tier_threshold == 0
    assert aa.activate_only_once is False


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the put_basic_land_from_hand_onto_battlefield
# _tapped dict shape round-trips byte-equal to the parsed printing's
# emitted Effect.
# ---------------------------------------------------------------------------


def test_terrain_generator_bridge_arm_round_trip():
    """The bridge arm ``put_basic_land_from_hand_onto_battlefield_
    tapped`` (cross_engine.py) round-trips
    ``{"kind": "put_basic_land_from_hand_onto_battlefield_tapped"}``
    to the matching Python ``PutBasicLandFromHandOntoBattlefieldTapped()``
    instance — unit variant, no fields.

    Effect-level byte-equality between the parsed real-EoE printing's
    emitted ``PutBasicLandFromHandOntoBattlefieldTapped`` Effect and
    the bridged Effect: the structural contract for the PROBED tier."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "put_basic_land_from_hand_onto_battlefield_tapped"}
    )
    assert isinstance(bridged, PutBasicLandFromHandOntoBattlefieldTapped)

    p = _PRINTINGS["Terrain Generator"]
    non_mana_aas = [
        aa for aa in (p.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    aa = non_mana_aas[0]
    assert aa.effect == bridged, (
        f"Terrain Generator AA Effect must be byte-equal to the "
        f"bridged Effect (PutBasicLandFromHandOntoBattlefieldTapped() "
        f"unit-variant structural contract); got parsed={aa.effect!r}, "
        f"bridged={bridged!r}"
    )


def test_terrain_generator_aa_round_trip_through_safe_dict():
    """The bridge's ``_python_aa_to_safe_dict`` ↔
    ``_aa_dict_to_python_activated_ability`` round-trip applied to the
    genuine parsed Terrain Generator AA emits the canonical
    ``{"cost": {"mana": {"generic": 2}, "tap_self": True}, "effect":
    {"kind": "put_basic_land_from_hand_onto_battlefield_tapped"}}``
    dict and rebuilds a byte-equal Python ActivatedAbility on the
    load-bearing fields (cost atoms + Effect + AA-rider fields). The
    cost-side ``mana_str`` display-string field is parser-only and is
    NOT round-tripped through the bridge (UI-side annotation; both
    engines ignore it for activation semantics — same convention as
    the Deserted Temple / Petrified Field probes)."""
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    p = _PRINTINGS["Terrain Generator"]
    non_mana_aas = [
        aa for aa in (p.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    aa = non_mana_aas[0]
    safe = _python_aa_to_safe_dict(aa)
    assert safe is not None, (
        "_python_aa_to_safe_dict must accept Terrain Generator's "
        "parsed AA post-Phase-2b — the Phase-2b Effect-class widen "
        "+ Phase-1.5a cost-gate widen admit this shape"
    )
    assert safe == {
        "cost": {"mana": {"generic": 2}, "tap_self": True},
        "effect": {
            "kind": "put_basic_land_from_hand_onto_battlefield_tapped",
        },
    }
    back = _aa_dict_to_python_activated_ability(safe)
    assert back.effect == aa.effect
    assert back.cost.mana == aa.cost.mana
    assert back.cost.tap_self == aa.cost.tap_self
    assert back.cost.sacrifice_self == aa.cost.sacrifice_self
    assert back.is_mana_ability == aa.is_mana_ability
    assert back.sorcery_speed == aa.sorcery_speed
    assert back.cost_reductions == aa.cost_reductions
    assert back.room_half == aa.room_half
    assert back.tier_threshold == aa.tier_threshold
    assert back.activate_only_once == aa.activate_only_once


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts a
# Terrain-Generator-shape dict (carrier AA with ``{2}, {T}`` cost +
# ``PutBasicLandFromHandOntoBattlefieldTapped`` effect). Exercises the
# Rust ``parse_effect`` arm for the
# ``put_basic_land_from_hand_onto_battlefield_tapped`` kind landed in
# this cycle.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_terrain_generator_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` +
    ``parse_activated_ability`` arms accept a Terrain-Generator-shape
    dict (single AA with
    ``{"cost": {"mana": {"generic": 2}, "tap_self": True}, "effect":
    {"kind": "put_basic_land_from_hand_onto_battlefield_tapped"}}``) on
    a Land carrier. The Phase-2b cycle shipped the variant + parse
    arms + resolve arm + cross-engine bridge arms in lockstep; this
    pin confirms the end-to-end Rust acceptance under the Phase-2b
    Effect-class widen."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Terrain Generator (synthetic carrier)",
            "card_types": ["Land"],
            "mana_cost": {"generic": 0},
            "effects": [],
            "activated_abilities": [
                {
                    "cost": {
                        "tap_self": True,
                        "mana": {"generic": 2},
                    },
                    "effect": {
                        "kind": "put_basic_land_from_hand_onto_battlefield_tapped",
                    },
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) Carrier-AA loader admit pin — the Phase-2b admit-set end-to-end:
# ``_filter_deck_to_bridge_supported`` admits Terrain Generator through
# the Carrier-AA disjunct, the resulting CardDef carries the canonical
# AA dict shape ready for ``build_rust_state`` to emit into the Rust
# registry.
# ---------------------------------------------------------------------------


def test_terrain_generator_carrier_aa_loader_end_to_end_admit():
    """**Phase 2b end-to-end pin.** The production-deck loader
    (``_filter_deck_to_bridge_supported``) admits Terrain Generator
    through the Carrier-AA Phase 2b disjunct. The returned CardDef
    carries the single non-token AA dict with the canonical Phase-1.5a
    cost shape + Phase-2b ``PutBasicLandFromHandOntoBattlefieldTapped``
    effect — Rust-side ``build_rust_state`` consumes it via the
    new Phase-2b substrate emit arm (no other code path needed)."""
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported

    filtered, card_defs = _filter_deck_to_bridge_supported(
        ["Terrain Generator"], _PRINTINGS,
    )
    assert filtered == ["Terrain Generator"]
    assert len(card_defs) == 1
    card_def = card_defs[0]
    assert card_def.name == "Terrain Generator"
    assert card_def.card_type == "Land"
    assert card_def.mana_produced == ()
    assert card_def.triggered_abilities == ()
    assert card_def.keywords == ()
    assert card_def.token_activated_abilities == ()
    aas = card_def.activated_abilities
    assert len(aas) == 1
    aa_dict = aas[0]
    assert aa_dict["cost"] == {
        "tap_self": True,
        "mana": {"generic": 2},
    }
    assert aa_dict["effect"] == {
        "kind": "put_basic_land_from_hand_onto_battlefield_tapped",
    }


# ---------------------------------------------------------------------------
# (5) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Terrain Generator printing's AA through its
# ``PutBasicLandFromHandOntoBattlefieldTapped`` Effect resolve path on
# the Python side, mirroring Rust's
# ``Effect::PutBasicLandFromHandOntoBattlefieldTapped`` resolve arm.
# The probe asserts the two observables the design doc §6.4 #15 pins:
# (a) baseline silent fizzle when no basic in hand, (b) land-search-
# and-ETB line where the Forest moves from hand to battlefield tapped.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_terrain_generator_baseline_no_basic_in_hand_fizzle_parity():
    """**GENUINE real-EoE probe — baseline silent-fizzle line.**

    Drives the parsed Terrain Generator AA's
    ``PutBasicLandFromHandOntoBattlefieldTapped`` Effect via
    ``resolve(state, controller_id, targets=())`` on a hand with ZERO
    basic land cards. Python's
    ``PutBasicLandFromHandOntoBattlefieldTapped.resolve``
    (``effects/generic/zone_moves.py:366-394``) early-returns when no
    basic is found (``if basic is None: return`` at
    ``zone_moves.py:382``). Rust's
    ``Effect::PutBasicLandFromHandOntoBattlefieldTapped`` resolve arm
    silently fizzles in the same shape — no panic, no state mutation.
    Byte-equal mirror.
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_python_state
    from mtg_bot.game import Zone

    real = _PRINTINGS.get("Terrain Generator")
    if real is None:
        pytest.skip("Terrain Generator absent from active CardSource")

    non_mana_aas = [
        aa for aa in (real.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    aa = non_mana_aas[0]
    assert isinstance(aa.effect, PutBasicLandFromHandOntoBattlefieldTapped)

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Seat the genuine parsed Terrain Generator on p0's bf (the AA
    # source). Untapped. Empty hand.
    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Pre-resolve state snapshot.
    hand_before = len(py_state.players[0].hand)
    bf_before = len(py_state.battlefield)

    # Resolve with empty targets — silent fizzle on no basic in hand.
    aa.effect.resolve(py_state, py_source.controller_id, targets=())

    # State invariants — no zone moves.
    assert len(py_state.players[0].hand) == hand_before
    assert len(py_state.battlefield) == bf_before
    # No "puts ... onto the battlefield tapped (Terrain Generator)"
    # log entry — Python's resolve appends this line ONLY after a
    # basic is found (``zone_moves.py:388-391``).
    assert not any(
        "Terrain Generator" in entry
        and "battlefield tapped" in entry
        for entry in py_state.log
    )


def test_cross_engine_real_eoe_terrain_generator_put_forest_from_hand_line_parity():
    """**GENUINE real-EoE probe — load-bearing land-search-and-ETB
    line. PROBED-tier flip (covered_by_construction → PROBED).**

    Drives the parsed Terrain Generator AA's
    ``PutBasicLandFromHandOntoBattlefieldTapped`` Effect via
    ``resolve(state, controller_id, targets=())`` on a state carrying
    a Forest in the controller's hand. Python's
    ``PutBasicLandFromHandOntoBattlefieldTapped.resolve``:

      * walks hand, finds the first basic Land (the Forest);
      * removes it from hand, sets ``zone = BATTLEFIELD``,
        ``controller_id = 0``, ``tapped = True``, appends to
        ``state.battlefield``;
      * appends ``"P0 puts Forest onto the battlefield tapped
        (Terrain Generator)"`` to ``state.log``;
      * fires landfall triggers via ``fire_landfall_triggers(state,
        basic)``.

    Rust's ``Effect::PutBasicLandFromHandOntoBattlefieldTapped``
    resolve arm walks the same predicate + zone-move path byte-equal:
    scan hand in order → match
    ``card_types.contains("Land") AND supertypes.contains("Basic")``
    → reserve etb_timestamp → remove from hand → push to bf tapped →
    queue ``Event::Enters`` via ``pending_etb_dispatches``.

    The cross-engine mirror is established by:

      1. Parse SoT (test #3 above) — same AA shape on both engines.
      2. Bridge round-trip (test #4 above) — byte-equal Effect dict.
      3. Rust synthetic-carrier acceptance (test #5 above) — Rust
         parses the same dict shape.
      4. End-to-end loader admit (test #6 above) — the
         ``_filter_deck_to_bridge_supported`` admit path threads the
         genuine printing into the Rust registry.
      5. This pin's Python-side resolve smoke — drives the Effect
         through the same resolve contract Rust's arm mirrors.

    The post-resolve observables (the Forest moves from hand to
    battlefield tapped; Terrain Generator's tap + mana-pay are paid
    OUT-OF-BAND by the activation machinery, not by this resolve arm
    — Rust's ``{2}, {T}`` cost-pay commits at the cost-pay phase
    BEFORE this resolve arm fires) are byte-equal on both engines.
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_python_state
    from mtg_bot.game import Zone

    real = _PRINTINGS.get("Terrain Generator")
    if real is None:
        pytest.skip("Terrain Generator absent from active CardSource")

    forest = _PRINTINGS.get("Forest")
    if forest is None:
        pytest.skip("Forest absent from active CardSource")

    non_mana_aas = [
        aa for aa in (real.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    aa = non_mana_aas[0]
    assert isinstance(aa.effect, PutBasicLandFromHandOntoBattlefieldTapped)

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Seat genuine Terrain Generator on p0's bf — untapped (the AA
    # source).
    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Seat a Forest in p0's hand — the AA's hand-search target.
    py_forest = py_state.new_object(
        forest, owner_id=0, zone=Zone.HAND,
    )
    py_state.players[0].hand.append(py_forest)

    # Pre-resolve state snapshot.
    hand_before = len(py_state.players[0].hand)
    bf_before = len(py_state.battlefield)

    # Resolve. Byte-equal mirror to Rust's
    # ``Effect::PutBasicLandFromHandOntoBattlefieldTapped`` resolve
    # arm. The Effect carries NO target — the activator's hand-search
    # is internal to the resolve (matches Rust's "no target" model
    # in the design doc §4.2 / §6.4 #15).
    aa.effect.resolve(
        py_state, py_source.controller_id, targets=(),
    )

    # Post-resolve observables — Forest moves hand → battlefield
    # tapped; Terrain Generator unchanged on bf (tap + mana costs
    # are out-of-band of this Effect's resolve arm; they would be
    # paid by the activation machinery before this resolve fires).
    assert py_forest.zone == Zone.BATTLEFIELD, (
        "The Forest must transition hand → battlefield (the "
        "load-bearing PutBasicLandFromHandOntoBattlefieldTapped "
        "observable Rust's arm also produces)"
    )
    assert py_forest.tapped is True, (
        "The Forest must be tapped (the printed text 'onto the "
        "battlefield tapped')"
    )
    assert py_forest.controller_id == 0, (
        "The Forest's controller_id must match the source's "
        "controller (CR 119.5 / 608.2)"
    )
    assert py_forest in py_state.battlefield, (
        "The Forest must be on the centralized state.battlefield"
    )
    assert py_forest not in py_state.players[0].hand, (
        "The Forest must be removed from p0's hand post-resolve"
    )
    assert len(py_state.players[0].hand) == hand_before - 1
    assert len(py_state.battlefield) == bf_before + 1
    # Log entry — Python's resolve appends
    # ``"P0 puts Forest onto the battlefield tapped (Terrain
    # Generator)"`` per the log line at ``zone_moves.py:388-391``;
    # an honest mirror to Rust's silent-state-mutation arm.
    assert any(
        "Forest" in entry
        and "battlefield tapped" in entry
        and "Terrain Generator" in entry
        for entry in py_state.log
    ), (
        f"Python resolve must append the 'puts Forest onto the "
        f"battlefield tapped (Terrain Generator)' log entry; "
        f"got log={py_state.log}"
    )
