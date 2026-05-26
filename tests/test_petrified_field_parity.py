"""Petrified Field — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip; Carrier-AA Phase 2a
admit-set landing).

Petrified Field is a ``{0}`` Land in the EoE pool with a leading
mana ability ``{T}: Add {C}.`` plus a non-mana activated ability:

    "{T}, Sacrifice this land: Return target land card from your
    graveyard to your hand."

The Carrier-AA substrate Phase 2a (2026-05-25 — see
``docs/CARRIER_AA_SUBSTRATE_PHASE_2_DESIGN.md`` §2/§5) widens the
``_aa_is_phase1_sub_shape_a`` cost gate to admit ``sacrifice_self=True``
AND extends the ``_carrier_aa_phase_1_effect_classes`` admit-set to
include ``ReturnTargetLandFromGraveyardToHand`` (the C1 substrate
landing at ``aca39437`` shipped the cross-engine Rust variant +
bridge arms). Petrified Field admits at Phase 2a Cycle 2 — the
cost-gate widen plus Effect-class widen land in lockstep. ZERO new
Rust cost-shape machinery (Lander's ``{N}, Sac:`` token-AA precedent
already wired ``ActivationCost.sacrifice_self`` parse + Phase 5b
cost-pay commit at ``state_ops_actions.rs:1300-1391``).

Parser-emitted Effect shape:

    ``ReturnTargetLandFromGraveyardToHand()``  (unit-variant zero-arg
    frozen dataclass; ``__post_init__`` stamps ``land=True``,
    ``destination='hand'``, ``target_kind='graveyard_land'``,
    ``log_suffix='(Petrified Field)'``)

attached to an ``ActivatedAbility`` whose ``cost`` carries
``tap_self=True`` + ``sacrifice_self=True`` (no mana). The bridge arm
``return_target_land_from_graveyard_to_hand`` (``cross_engine.py``
parse arm at line 12419; ``cross_engine.py:14210``
``_python_aa_to_safe_dict`` emit arm) round-trips
``{"kind": "return_target_land_from_graveyard_to_hand"}`` byte-equal
to Python's ``ReturnTargetLandFromGraveyardToHand()``.

**EEEE-idiom for the ActivatedAbility carrier.** Same lane discipline
as the sibling Carrier-AA AA probes (parse + bridge round-trip +
Python-side resolve): the probe drives the parsed Effect through its
actual ``resolve`` path on the Python state, with observables that
mirror what Rust's ``Effect::ReturnTargetLandFromGraveyardToHand``
resolve arm (``rust/src/state_ops_resolve.rs:22838``) produces on the
same input shape. The cross-engine byte-equal mirror is established
by the Phase-2a admit gate routing the genuine parsed Petrified Field
printing through the Carrier-AA substrate end-to-end (loader admits
post-widen — see the C1-pin-inverted
``test_petrified_field_now_passes_loader_filter`` in
``test_carrier_aa_phase_2a_substrate_cycle_1.py``).

**NEW shape coverage:** the FIRST PROBE_MODULES-credited probe binding
the Petrified Field slug to the AA +
``ReturnTargetLandFromGraveyardToHand`` Effect+bridge round-trip on
the REAL parsed EoE printing — and the FIRST PROBED-tier slot for the
``ReturnTargetLandFromGraveyardToHand`` Effect class via the
Carrier-AA substrate's ``{T}, Sac:`` cost-shape disjunct.

**AA-cost-substrate scope.** The mana-payment (none — Petrified
Field's AA cost has no mana component) / tap-payment / sacrifice-self
cost trajectory of the AA is exercised at the loader-end-to-end
disjunct (the C1-pin-inverted
``test_petrified_field_now_passes_loader_filter`` in the C1 module +
the cross-engine bridge round-trip pin below); per-slug PROBED
attribution credits Petrified Field based on the Effect + bridge
byte-equality + parsed-printing resolve smoke alone — the canonical
EEEE-idiom precedent (Deserted Temple's Phase-1.5a probe at
``tests/test_deserted_temple_parity.py``).
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.bounce import (
    ReturnTargetLandFromGraveyardToHand,
)


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Zone constants (mirror Rust's u8 zone IDs).
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3
ZONE_HAND = 0


# ---------------------------------------------------------------------------
# (1) Parser SoT — Petrified Field is parser-claimed and carries the
# exact AA shape the design doc (§2.1 / §2.3) pins.
# ---------------------------------------------------------------------------


def test_petrified_field_parser_claims_card():
    assert "Petrified Field" in _PRINTINGS, (
        "Petrified Field must be parser-claimed by the active "
        "CardSource"
    )


def test_petrified_field_printed_attrs():
    """Pins the basic printing surface: single-typed Land, no mana
    cost, no power/toughness, no triggered / static / keyword riders.
    The leading ``{T}: Add {C}`` mana ability lives in the parser-
    synthesized mana-ability slot, NOT on the carrier surface; the
    carrier AA (sub-shape A) is the SECOND activated_abilities entry.
    """
    p = _PRINTINGS["Petrified Field"]
    assert p.card_types == ("Land",)
    assert p.subtypes == ()
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()
    assert p.power is None and p.toughness is None
    assert p.keywords == frozenset()
    assert p.triggered_abilities == ()
    assert p.static_abilities == ()


def test_petrified_field_activated_ability_return_target_land_shape():
    """Petrified Field has the carrier ``ActivatedAbility`` (the
    sub-shape A non-mana AA) whose effect is
    ``ReturnTargetLandFromGraveyardToHand()`` (unit variant, no
    fields). Cost is ``{T}, Sac:`` — the Phase-2a widened cost-gate's
    load-bearing shape (was the Phase-1.5a honest-stop on the
    ``sacrifice_self`` axis)."""
    p = _PRINTINGS["Petrified Field"]
    non_mana_aas = [
        aa for aa in (p.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    assert len(non_mana_aas) == 1, (
        f"Petrified Field must have exactly one non-mana "
        f"ActivatedAbility; got {len(non_mana_aas)}"
    )
    aa = non_mana_aas[0]
    # Effect shape.
    assert isinstance(aa.effect, ReturnTargetLandFromGraveyardToHand), (
        f"Petrified Field AA effect must be "
        f"ReturnTargetLandFromGraveyardToHand; got "
        f"{type(aa.effect).__name__}"
    )
    # Effect's __post_init__ stamps — Phase 2a C1 substrate contract.
    assert aa.effect.land is True
    assert aa.effect.destination == "hand"
    assert aa.effect.target_kind == "graveyard_land"
    assert aa.effect.log_suffix == "(Petrified Field)"
    # Cost shape — the Phase-2a load-bearing axis.
    assert aa.cost.tap_self is True
    assert aa.cost.sacrifice_self is True
    assert aa.cost.mana is None, (
        "Petrified Field's AA cost carries NO mana component (only "
        "``{T}, Sac:``)"
    )
    # No riders.
    assert aa.is_mana_ability is False
    assert aa.sorcery_speed is False
    assert aa.cost_reductions == ()
    assert aa.room_half is None
    assert aa.tier_threshold == 0
    assert aa.activate_only_once is False


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the return_target_land_from_graveyard_to_hand
# dict shape round-trips byte-equal to the parsed printing's emitted
# Effect (the closed-vocab bridge arm at ``cross_engine.py:12419``).
# ---------------------------------------------------------------------------


def test_petrified_field_bridge_arm_round_trip():
    """The bridge arm ``return_target_land_from_graveyard_to_hand``
    (cross_engine.py:12419) round-trips
    ``{"kind": "return_target_land_from_graveyard_to_hand"}`` to the
    matching Python ``ReturnTargetLandFromGraveyardToHand()`` instance
    — unit variant, no fields. The ``__post_init__`` stamps survive
    the round-trip (every fresh instance has them set).

    Effect-level byte-equality between the parsed real-EoE printing's
    emitted ``ReturnTargetLandFromGraveyardToHand`` Effect and the
    bridged Effect: the structural contract for the PROBED tier."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "return_target_land_from_graveyard_to_hand"}
    )
    assert isinstance(bridged, ReturnTargetLandFromGraveyardToHand)
    # Post-init flags survive the round-trip.
    assert bridged.land is True
    assert bridged.destination == "hand"
    assert bridged.target_kind == "graveyard_land"
    assert bridged.log_suffix == "(Petrified Field)"

    p = _PRINTINGS["Petrified Field"]
    non_mana_aas = [
        aa for aa in (p.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    aa = non_mana_aas[0]
    assert aa.effect == bridged, (
        f"Petrified Field AA Effect must be byte-equal to the bridged "
        f"Effect (ReturnTargetLandFromGraveyardToHand() unit-variant "
        f"structural contract); got parsed={aa.effect!r}, "
        f"bridged={bridged!r}"
    )


def test_petrified_field_aa_round_trip_through_safe_dict():
    """The bridge's ``_python_aa_to_safe_dict`` ↔
    ``_aa_dict_to_python_activated_ability`` round-trip applied to the
    genuine parsed Petrified Field AA emits the canonical
    ``{"cost": {"tap_self": True, "sacrifice_self": True}, "effect":
    {"kind": "return_target_land_from_graveyard_to_hand"}}`` dict and
    rebuilds a byte-equal Python ActivatedAbility — confirming the
    bridge serializes the ``sacrifice_self`` cost-bool for AAs (no Rust
    change needed for Phase 2a; the C1 substrate landing widened the
    forward emit at ``aca39437``)."""
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    p = _PRINTINGS["Petrified Field"]
    non_mana_aas = [
        aa for aa in (p.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    aa = non_mana_aas[0]
    safe = _python_aa_to_safe_dict(aa)
    assert safe is not None, (
        "_python_aa_to_safe_dict must accept Petrified Field's parsed "
        "AA post-Phase-2a — sacrifice_self cost-bool admitted under "
        "the C1 forward-emit widen + the Effect class in the "
        "Phase-2a admit set"
    )
    assert safe == {
        "cost": {"tap_self": True, "sacrifice_self": True},
        "effect": {"kind": "return_target_land_from_graveyard_to_hand"},
    }
    back = _aa_dict_to_python_activated_ability(safe)
    # Effect + cost-shape byte-equality. The cost-side ``mana_str``
    # display-string field is parser-only and is NOT round-tripped
    # through the bridge (it's a UI-side annotation; both engines
    # ignore it for activation semantics — the canonical
    # ``ManaCost`` dataclass + ``tap_self`` + ``sacrifice_self`` cost
    # atoms are the bridge's load-bearing surface). Pin the
    # load-bearing fields directly.
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
# Petrified-Field-shape dict (carrier AA with ``{T}, Sac:`` cost +
# ``ReturnTargetLandFromGraveyardToHand`` effect). Exercises the Rust
# ``parse_effect`` arm for the
# ``return_target_land_from_graveyard_to_hand`` kind on the Phase-2a
# C1 substrate.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_petrified_field_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` +
    ``parse_activated_ability`` arms accept a Petrified-Field-shape
    dict (single AA with
    ``{"cost": {"tap_self": True, "sacrifice_self": True}, "effect":
    {"kind": "return_target_land_from_graveyard_to_hand"}}``) on a
    Land carrier. The Phase-2a C1 substrate (commit ``aca39437``)
    shipped the variant + parse arms + resolve arm + cross-engine
    bridge arms; this pin confirms the end-to-end Rust acceptance
    under the Phase-2a-widened AA cost shape."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Petrified Field (synthetic carrier)",
            "card_types": ["Land"],
            "mana_cost": {"generic": 0},
            "effects": [],
            "activated_abilities": [
                {
                    "cost": {
                        "tap_self": True,
                        "sacrifice_self": True,
                    },
                    "effect": {
                        "kind": "return_target_land_from_graveyard_to_hand",
                    },
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) Carrier-AA loader admit pin — the Phase-2a admit-set end-to-end:
# ``_filter_deck_to_bridge_supported`` admits Petrified Field through
# the Carrier-AA disjunct, the resulting CardDef carries the canonical
# AA dict shape ready for ``build_rust_state`` to emit into the Rust
# registry.
# ---------------------------------------------------------------------------


def test_petrified_field_carrier_aa_loader_end_to_end_admit():
    """**Phase 2a end-to-end pin.** The production-deck loader
    (``_filter_deck_to_bridge_supported``) admits Petrified Field
    through the Carrier-AA Phase 2a disjunct. The returned CardDef
    carries the single non-token AA dict with the canonical Phase-2a
    cost shape + ``ReturnTargetLandFromGraveyardToHand`` effect —
    Rust-side ``build_rust_state`` consumes it via the existing C1
    substrate emit arm (no new code path)."""
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported

    filtered, card_defs = _filter_deck_to_bridge_supported(
        ["Petrified Field"], _PRINTINGS,
    )
    assert filtered == ["Petrified Field"]
    assert len(card_defs) == 1
    card_def = card_defs[0]
    assert card_def.name == "Petrified Field"
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
        "sacrifice_self": True,
    }
    assert aa_dict["effect"] == {
        "kind": "return_target_land_from_graveyard_to_hand",
    }


# ---------------------------------------------------------------------------
# (5) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Petrified Field printing's AA through its
# ``ReturnTargetLandFromGraveyardToHand`` Effect resolve path on the
# Python side, mirroring Rust's
# ``Effect::ReturnTargetLandFromGraveyardToHand`` resolve arm
# (``state_ops_resolve.rs:22838``). The probe asserts the two
# observables the design doc §6.4 pins: (a) baseline silent fizzle
# when no eligible target exists, (b) return-a-Forest line where the
# Forest moves from graveyard to hand.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_petrified_field_baseline_no_eligible_target_fizzle_parity():
    """**GENUINE real-EoE probe — baseline silent-fizzle line.**

    Drives the parsed Petrified Field AA's
    ``ReturnTargetLandFromGraveyardToHand`` Effect via
    ``resolve(state, controller_id, targets=())`` on a graveyard with
    ZERO Land cards. Python's ``ReturnFromGraveyard.resolve``
    (``effects/generic/graveyard.py:195-219``) early-returns on empty
    ``targets`` (``if not targets: return``). Rust's
    ``Effect::ReturnTargetLandFromGraveyardToHand`` resolve arm
    (``state_ops_resolve.rs:22838`` —
    ``current_resolve_payload_target_id == None`` + substrate-fallback
    scan finds nothing + ``// else: silent fizzle.`` at the tail)
    silently fizzles in the same shape — no panic, no state mutation.
    Byte-equal mirror.
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_python_state
    from mtg_bot.game import Zone

    real = _PRINTINGS.get("Petrified Field")
    if real is None:
        pytest.skip("Petrified Field absent from active CardSource")

    non_mana_aas = [
        aa for aa in (real.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    aa = non_mana_aas[0]
    assert isinstance(aa.effect, ReturnTargetLandFromGraveyardToHand)

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Seat the genuine parsed Petrified Field on p0's bf (the AA
    # source). Untapped. Empty graveyard.
    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Pre-resolve sanity — graveyard is empty, the legal-targets walk
    # yields the empty list (mirrors Rust's deterministic-first-legal
    # graveyard scan, which also finds nothing).
    assert (
        aa.effect.legal_targets(py_state, py_source.controller_id) == []
    )

    # Pre-resolve state snapshot.
    gy_before = len(py_state.players[0].graveyard)
    hand_before = len(py_state.players[0].hand)

    # Resolve with empty targets — silent fizzle.
    aa.effect.resolve(py_state, py_source.controller_id, targets=())

    # State invariants — no zone moves, no log entry added (the log
    # entry only fires once a card is honored at the
    # ``returns from graveyard to hand`` line in ``graveyard.py:
    # 293``).
    assert len(py_state.players[0].graveyard) == gy_before
    assert len(py_state.players[0].hand) == hand_before
    assert not any(
        "returns from" in entry for entry in py_state.log
    )


def test_cross_engine_real_eoe_petrified_field_return_forest_from_graveyard_line_parity():
    """**GENUINE real-EoE probe — load-bearing return-a-Forest line.
    PROBED-tier flip (covered_by_construction → PROBED).**

    Drives the parsed Petrified Field AA's
    ``ReturnTargetLandFromGraveyardToHand`` Effect via
    ``resolve(state, controller_id, targets=(('graveyard_land',
    forest_id),))`` on a state carrying a Forest in the controller's
    graveyard. Python's ``ReturnFromGraveyard.resolve``:

      * matches the target_kind ``graveyard_land`` against the
        Effect's stamped target_kind (post_init);
      * finds the card by id in the controller's graveyard;
      * removes it from graveyard, sets ``zone = HAND``, appends to
        hand;
      * appends ``"Forest returns from P0's graveyard to hand
        (Petrified Field)"`` to ``state.log``.

    Rust's ``Effect::ReturnTargetLandFromGraveyardToHand`` resolve arm
    (``state_ops_resolve.rs:22838``) walks the same is_legal
    predicate + zone-move path byte-equal:
    ``current_resolve_payload_target_id`` → re-validate
    ``card_types.contains("Land")`` (CR 608.2b) → remove from
    graveyard → set zone=HAND → append to hand. No ETB triggers (CR
    603.6 — graveyard→hand zone change doesn't fire ETB).

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

    The post-resolve observables (the Forest moves from graveyard to
    hand; Petrified Field's tap + sacrifice are paid OUT-OF-BAND by
    the activation machinery, not by this resolve arm — Rust's
    ``sacrifice_self`` cost-pay commits at
    ``state_ops_actions.rs:1300-1391`` BEFORE this resolve arm fires)
    are byte-equal on both engines.
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_python_state
    from mtg_bot.game import Zone

    real = _PRINTINGS.get("Petrified Field")
    if real is None:
        pytest.skip("Petrified Field absent from active CardSource")

    forest = _PRINTINGS.get("Forest")
    if forest is None:
        pytest.skip("Forest absent from active CardSource")

    non_mana_aas = [
        aa for aa in (real.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    aa = non_mana_aas[0]
    assert isinstance(aa.effect, ReturnTargetLandFromGraveyardToHand)

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Seat genuine Petrified Field on p0's bf — untapped (the AA
    # source).
    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Seat a Forest in p0's graveyard — the AA's target.
    py_forest = py_state.new_object(
        forest, owner_id=0, zone=Zone.GRAVEYARD,
    )
    py_state.players[0].graveyard.append(py_forest)

    # Pre-resolve sanity — the legal-targets walk yields exactly the
    # Forest in graveyard (mirrors Rust's deterministic-first-legal
    # graveyard scan).
    legals = aa.effect.legal_targets(
        py_state, py_source.controller_id,
    )
    assert legals == [("graveyard_land", py_forest.id)], (
        f"legal_targets must yield exactly the Forest in graveyard; "
        f"got {legals}"
    )

    # Pre-resolve state snapshot.
    gy_before = len(py_state.players[0].graveyard)
    hand_before = len(py_state.players[0].hand)

    # Resolve with the Forest target. Byte-equal mirror to Rust's
    # ``Effect::ReturnTargetLandFromGraveyardToHand`` resolve arm.
    aa.effect.resolve(
        py_state, py_source.controller_id,
        targets=(("graveyard_land", py_forest.id),),
    )

    # Post-resolve observables — Forest moves graveyard → hand,
    # Petrified Field unchanged on bf (tap-self + sacrifice-self
    # costs are out-of-band of this Effect's resolve arm; they would
    # be paid by the activation machinery before this resolve fires
    # — see the activation pipeline at ``actions.py:1928-2002`` for
    # the Python side and ``state_ops_actions.rs:1300-1391`` for the
    # Rust side. The Effect itself does NOT sac the source).
    assert py_forest.zone == Zone.HAND, (
        "The Forest must transition graveyard → hand (the "
        "load-bearing ReturnTargetLandFromGraveyardToHand observable "
        "Rust's arm also produces)"
    )
    assert py_forest in py_state.players[0].hand, (
        "The Forest must be in p0's hand post-resolve"
    )
    assert py_forest not in py_state.players[0].graveyard, (
        "The Forest must be removed from p0's graveyard post-resolve"
    )
    assert len(py_state.players[0].graveyard) == gy_before - 1
    assert len(py_state.players[0].hand) == hand_before + 1
    # Log entry — Python's resolve appends
    # ``"<name> returns from P<x>'s graveyard to hand (Petrified
    # Field)"`` per the log_suffix stamp from
    # ``ReturnTargetLandFromGraveyardToHand.__post_init__``; an honest
    # mirror to Rust's silent-state-mutation arm.
    assert any(
        "Forest returns from" in entry
        and "(Petrified Field)" in entry
        for entry in py_state.log
    ), (
        f"Python resolve must append the 'Forest returns from ... "
        f"(Petrified Field)' log entry; got log={py_state.log}"
    )
