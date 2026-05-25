"""Deserted Temple — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip; Carrier-AA Phase 1.5a
admit-set landing).

Deserted Temple is a ``{0}`` Land in the EoE pool with a single
activated ability:

    "{1}, {T}: Untap target land."

The Carrier-AA substrate Phase 1.5a (2026-05-25 — see
``docs/CARRIER_AA_SUBSTRATE_PHASE_1_5_DESIGN.md`` §2/§5) widens the
``_aa_is_phase1_sub_shape_a`` cost gate from STRICT bare-``{T}`` to
bare-``{T}`` OR ``{N}, {T}`` (generic-only mana — no colored / hybrid
/ X-pip). Deserted Temple was the Phase-1 honest-stop on the cost
gate; Phase 1.5a admits it immediately on the gate-widen alone — the
``UntapTargetLand`` Effect was already in the Phase-1 admit set
(``226c9738`` C1 substrate). ZERO Rust changes (Rust already routes
generic mana for AAs via the ``_python_aa_to_safe_dict`` round-trip).

Parser-emitted Effect shape:

    ``UntapTargetLand()``  (unit-variant, no fields)

attached to an ``ActivatedAbility`` whose ``cost`` carries
``mana=ManaCost(generic=1)`` + ``tap_self=True``. The bridge arm
``untap_target_land`` (``cross_engine.py:12395`` parse arm;
``cross_engine.py:14159`` ``_python_aa_to_safe_dict`` emit arm)
round-trips ``{"kind": "untap_target_land"}`` byte-equal to Python's
``UntapTargetLand()``.

**EEEE-idiom for the ActivatedAbility carrier.** Same lane discipline
as the sibling Carrier-AA AA probes (parse + bridge round-trip +
Python-side resolve): the probe drives the parsed Effect through its
actual ``resolve`` path on the Python state, with observables that
mirror what Rust's ``Effect::UntapTargetLand`` resolve arm
(``rust/src/state_ops_resolve.rs`` ~22710) produces on the same input
shape. The cross-engine byte-equal mirror is established by the
Phase-1.5a admit gate routing the genuine parsed Deserted Temple
printing through the Carrier-AA substrate end-to-end (loader admits
post-widen — see ``test_carrier_aa_phase_1_substrate_cycle_2.py``
pin ``test_filter_deck_to_bridge_supported_admits_deserted_temple``).

**NEW shape coverage:** the FIRST PROBE_MODULES-credited probe binding
the Deserted Temple slug to the AA + ``UntapTargetLand`` Effect+bridge
round-trip on the REAL parsed EoE printing — and the FIRST PROBED-
tier slot for the ``UntapTargetLand`` Effect class via the Carrier-AA
substrate's ``{N}, {T}`` cost-shape disjunct.

**AA-cost-substrate scope.** The mana-payment / tap-payment cost
trajectory of the AA is exercised at the loader-end-to-end disjunct
(``test_filter_deck_to_bridge_supported_admits_deserted_temple`` in
the C2 module + the cross-engine bridge round-trip pin below); per-
slug PROBED attribution credits Deserted Temple based on the Effect +
bridge byte-equality + parsed-printing resolve smoke alone — the
canonical EEEE-idiom precedent.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.tap import UntapTargetLand


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Zone constants (mirror Rust's u8 zone IDs).
ZONE_BATTLEFIELD = 2


# ---------------------------------------------------------------------------
# (1) Parser SoT — Deserted Temple is parser-claimed and carries the
# exact AA shape the design doc (§2.1 / §2.3) pins.
# ---------------------------------------------------------------------------


def test_deserted_temple_parser_claims_card():
    assert "Deserted Temple" in _PRINTINGS, (
        "Deserted Temple must be parser-claimed by the active "
        "CardSource"
    )


def test_deserted_temple_printed_attrs():
    """Pins the basic printing surface: single-typed Land, no mana
    cost, no power/toughness."""
    p = _PRINTINGS["Deserted Temple"]
    assert p.card_types == ("Land",)
    assert p.subtypes == ()
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()
    assert p.power is None and p.toughness is None
    assert p.keywords == frozenset()
    assert p.triggered_abilities == ()
    assert p.static_abilities == ()


def test_deserted_temple_activated_ability_untap_target_land_shape():
    """Deserted Temple has exactly one ``ActivatedAbility`` whose
    effect is ``UntapTargetLand()`` (unit variant, no fields). Cost
    is ``{1}, {T}`` — the Phase-1.5a widened cost-gate's load-bearing
    shape (was Phase-1 honest-stop on the STRICT bare-``{T}`` gate)."""
    p = _PRINTINGS["Deserted Temple"]
    assert len(p.activated_abilities) == 1, (
        f"Deserted Temple must have exactly one ActivatedAbility; "
        f"got {len(p.activated_abilities)}"
    )
    aa = p.activated_abilities[0]
    # Effect shape.
    assert isinstance(aa.effect, UntapTargetLand), (
        f"Deserted Temple AA effect must be UntapTargetLand; got "
        f"{type(aa.effect).__name__}"
    )
    # Cost shape — the Phase-1.5a load-bearing axis.
    assert aa.cost.tap_self is True
    assert aa.cost.mana is not None, (
        "Deserted Temple's AA cost must carry a mana component "
        "({1}) — the Phase-1.5a {N}, {T} shape"
    )
    assert aa.cost.mana.generic == 1
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
# (2) Bridge round-trip — the untap_target_land dict shape round-trips
# byte-equal to the parsed printing's emitted Effect (the closed-vocab
# bridge arm at ``cross_engine.py:12395``).
# ---------------------------------------------------------------------------


def test_deserted_temple_bridge_arm_round_trip():
    """The bridge arm ``untap_target_land`` (cross_engine.py:12395)
    round-trips ``{"kind": "untap_target_land"}`` to the matching
    Python ``UntapTargetLand()`` instance — unit variant, no fields.

    Effect-level byte-equality between the parsed real-EoE printing's
    emitted ``UntapTargetLand`` Effect and the bridged Effect: the
    structural contract for the PROBED tier."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "untap_target_land"}
    )
    assert isinstance(bridged, UntapTargetLand)

    p = _PRINTINGS["Deserted Temple"]
    aa = p.activated_abilities[0]
    assert aa.effect == bridged, (
        f"Deserted Temple AA Effect must be byte-equal to the bridged "
        f"Effect (UntapTargetLand() unit-variant structural contract); "
        f"got parsed={aa.effect!r}, bridged={bridged!r}"
    )


def test_deserted_temple_aa_round_trip_through_safe_dict():
    """The bridge's ``_python_aa_to_safe_dict`` ↔
    ``_aa_dict_to_python_activated_ability`` round-trip applied to the
    genuine parsed Deserted Temple AA emits the canonical
    ``{"cost": {"mana": {"generic": 1}, "tap_self": True}, "effect":
    {"kind": "untap_target_land"}}`` dict and rebuilds a byte-equal
    Python ActivatedAbility — confirming the bridge already serializes
    generic-mana costs for AAs (no Rust change needed for Phase 1.5a)."""
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    p = _PRINTINGS["Deserted Temple"]
    aa = p.activated_abilities[0]
    safe = _python_aa_to_safe_dict(aa)
    assert safe is not None, (
        "_python_aa_to_safe_dict must accept Deserted Temple's parsed "
        "AA post-Phase-1.5a — colored/hybrid/X-pip absent + Effect in "
        "Phase-1 admit set"
    )
    assert safe == {
        "cost": {"mana": {"generic": 1}, "tap_self": True},
        "effect": {"kind": "untap_target_land"},
    }
    back = _aa_dict_to_python_activated_ability(safe)
    # Effect + cost-shape byte-equality. The cost-side ``mana_str``
    # display-string field is parser-only and is NOT round-tripped
    # through the bridge (it's a UI-side annotation; both engines
    # ignore it for activation semantics — the canonical
    # ``ManaCost`` dataclass + ``tap_self`` cost atom are the
    # bridge's load-bearing surface). Pin the load-bearing fields
    # directly.
    assert back.effect == aa.effect
    assert back.cost.mana == aa.cost.mana
    assert back.cost.tap_self == aa.cost.tap_self
    assert back.is_mana_ability == aa.is_mana_ability
    assert back.sorcery_speed == aa.sorcery_speed
    assert back.cost_reductions == aa.cost_reductions
    assert back.room_half == aa.room_half
    assert back.tier_threshold == aa.tier_threshold
    assert back.activate_only_once == aa.activate_only_once


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts a
# Deserted-Temple-shape dict (single AA, generic-1 mana + tap_self,
# UntapTargetLand effect). Exercises the Rust ``parse_effect`` arm for
# the ``untap_target_land`` kind on the Phase-1 substrate.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_deserted_temple_untap_target_land_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` + ``parse_activated_ability``
    arms accept a Deserted-Temple-shape dict (single AA with
    ``{"cost": {"mana": {"generic": 1}, "tap_self": True}, "effect":
    {"kind": "untap_target_land"}}``) on a Land carrier. The Phase-1
    C1 substrate (commit ``226c9738``) shipped the variant; this pin
    confirms the end-to-end Rust acceptance under the Phase-1.5a-widened
    AA cost shape."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Deserted Temple (synthetic carrier)",
            "card_types": ["Land"],
            "mana_cost": {"generic": 0},
            "effects": [],
            "activated_abilities": [
                {
                    "cost": {
                        "mana": {"generic": 1},
                        "tap_self": True,
                    },
                    "effect": {"kind": "untap_target_land"},
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) Carrier-AA loader admit pin — the Phase-1.5a admit-set
# end-to-end: ``_filter_deck_to_bridge_supported`` admits Deserted
# Temple through the Carrier-AA disjunct, the resulting CardDef carries
# the canonical AA dict shape ready for ``build_rust_state`` to emit
# into the Rust registry.
# ---------------------------------------------------------------------------


def test_deserted_temple_carrier_aa_loader_end_to_end_admit():
    """**Phase 1.5a end-to-end pin.** The production-deck loader
    (``_filter_deck_to_bridge_supported``) admits Deserted Temple
    through the Carrier-AA Phase 1.5a disjunct. The returned CardDef
    carries the single non-token AA dict with the canonical Phase-1.5a
    cost shape + ``UntapTargetLand`` effect — Rust-side
    ``build_rust_state`` consumes it via the existing C1 substrate
    emit arm (no new code path)."""
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported

    filtered, card_defs = _filter_deck_to_bridge_supported(
        ["Deserted Temple"], _PRINTINGS,
    )
    assert filtered == ["Deserted Temple"]
    assert len(card_defs) == 1
    card_def = card_defs[0]
    assert card_def.name == "Deserted Temple"
    assert card_def.card_type == "Land"
    assert card_def.mana_produced == ()
    assert card_def.triggered_abilities == ()
    assert card_def.keywords == ()
    assert card_def.token_activated_abilities == ()
    aas = card_def.activated_abilities
    assert len(aas) == 1
    aa_dict = aas[0]
    assert aa_dict["cost"] == {"mana": {"generic": 1}, "tap_self": True}
    assert aa_dict["effect"] == {"kind": "untap_target_land"}


# ---------------------------------------------------------------------------
# (5) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Deserted Temple printing's AA through its
# ``UntapTargetLand`` Effect resolve path on the Python side, mirroring
# Rust's ``Effect::UntapTargetLand`` resolve arm
# (``state_ops_resolve.rs`` ~22710). The probe asserts the two
# observables the design doc §6.3 pins: (a) baseline silent fizzle when
# no eligible target exists, (b) untap-a-tapped-Forest line where the
# Forest's ``tapped`` bit flips false.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_deserted_temple_baseline_no_eligible_target_fizzle_parity():
    """**GENUINE real-EoE probe — baseline silent-fizzle line.**

    Drives the parsed Deserted Temple AA's ``UntapTargetLand`` Effect
    via ``resolve(state, controller_id, targets=())`` on a battlefield
    with ZERO tapped lands. Python's
    ``UntapTargetLand.resolve``
    (``effects/generic/tap.py:193``) early-returns on empty
    ``targets`` (no eligible target → no-op). Rust's
    ``Effect::UntapTargetLand`` resolve arm
    (``state_ops_resolve.rs`` ~22710 — ``found = None`` branch +
    ``// else: silent fizzle.`` at ~22777) silently fizzles in the
    same shape — no panic, no state mutation. Byte-equal mirror.
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_python_state
    from mtg_bot.game import Zone

    real = _PRINTINGS.get("Deserted Temple")
    if real is None:
        pytest.skip("Deserted Temple absent from active CardSource")

    aa = real.activated_abilities[0]
    assert isinstance(aa.effect, UntapTargetLand)

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Seat the genuine parsed Deserted Temple on p0's bf (the AA
    # source). Untapped.
    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Pre-resolve sanity — no tapped lands anywhere; the legal-targets
    # walk yields the empty list (mirrors Rust's deterministic-first-
    # legal scan, which also finds nothing).
    assert (
        aa.effect.legal_targets(py_state, py_source.controller_id) == []
    )

    # Resolve with empty targets — silent fizzle.
    aa.effect.resolve(py_state, py_source.controller_id, targets=())

    # State invariants — no tapped flag flipped, no log entry added
    # (the log entry only fires once a target is honored at
    # ``tap.py:210``).
    assert py_source.tapped is False
    assert not any(
        "untapped" in entry for entry in py_state.log
    )


def test_cross_engine_real_eoe_deserted_temple_untap_tapped_forest_line_parity():
    """**GENUINE real-EoE probe — load-bearing untap-tapped-Forest
    line. PROBED-tier flip (covered_by_construction → PROBED).**

    Drives the parsed Deserted Temple AA's ``UntapTargetLand`` Effect
    via ``resolve(state, controller_id, targets=(('permanent',
    forest_id),))`` on a battlefield carrying a tapped Forest. Python's
    ``UntapTargetLand.resolve``:

      * verifies the target is a Land (``obj.printing.is_land``);
      * verifies it is currently tapped (``obj.tapped is True``);
      * flips ``obj.tapped = False``;
      * appends ``"Forest is untapped"`` to ``state.log``.

    Rust's ``Effect::UntapTargetLand`` resolve arm
    (``state_ops_resolve.rs`` ~22710) walks the same is_legal predicate
    + tapped-flag invariant + flips ``obj.tapped = false`` byte-equal.
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

    The post-resolve observable (the Forest's ``tapped`` bit flips
    false; Deserted Temple's ``tapped`` bit is unchanged because the
    AA's tap-self cost is paid OUT-OF-BAND by the activation
    machinery, not by this resolve arm — see Rust's arm comments at
    ~22699-22701: "Idempotent on already-untapped lands... silent
    fizzle on no eligible land") is byte-equal on both engines.
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_python_state
    from mtg_bot.game import Zone

    real = _PRINTINGS.get("Deserted Temple")
    if real is None:
        pytest.skip("Deserted Temple absent from active CardSource")

    forest = _PRINTINGS.get("Forest")
    if forest is None:
        pytest.skip("Forest absent from active CardSource")

    aa = real.activated_abilities[0]
    assert isinstance(aa.effect, UntapTargetLand)

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Seat genuine Deserted Temple on p0's bf — untapped (the AA
    # source).
    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Seat a tapped Forest on p0's bf — the AA's target.
    py_forest = py_state.new_object(
        forest, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_forest.tapped = True
    py_forest.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_forest)

    # Pre-resolve sanity — the legal-targets walk yields exactly the
    # tapped Forest (mirrors Rust's deterministic-first-legal scan).
    legals = aa.effect.legal_targets(
        py_state, py_source.controller_id,
    )
    assert legals == [("permanent", py_forest.id)], (
        f"legal_targets must yield exactly the tapped Forest; got "
        f"{legals}"
    )

    # Resolve with the Forest target. Byte-equal mirror to Rust's
    # ``Effect::UntapTargetLand`` resolve arm.
    aa.effect.resolve(
        py_state, py_source.controller_id,
        targets=(("permanent", py_forest.id),),
    )

    # Post-resolve observables — Forest untaps, Deserted Temple
    # untouched (tap-self cost is out-of-band of this Effect's resolve
    # arm).
    assert py_forest.tapped is False, (
        "The tapped Forest must untap post-resolve (the load-bearing "
        "UntapTargetLand observable Rust's arm also produces)"
    )
    assert py_source.tapped is False, (
        "Deserted Temple's tapped bit is OUT-OF-BAND of this Effect's "
        "resolve arm (the {T} tap-self cost is paid by the activation "
        "machinery, not by UntapTargetLand.resolve); mirrors Rust's "
        "arm contract"
    )
    # Log entry — Python's resolve appends ``"<name> is untapped"``;
    # an honest mirror to Rust's silent-state-mutation arm.
    assert any(
        "Forest is untapped" in entry for entry in py_state.log
    ), (
        f"Python resolve must append the 'Forest is untapped' log "
        f"entry; got log={py_state.log}"
    )

    # Idempotency check — re-resolving with the now-untapped Forest is
    # a no-op (mirrors Rust's ``if !obj.tapped { return false; }``
    # is_legal predicate early-out at ~22716 + Python's
    # ``if not obj.tapped: return`` at ``tap.py:207``). The second
    # resolve must NOT panic, NOT mutate state, NOT log.
    pre_log_len = len(py_state.log)
    aa.effect.resolve(
        py_state, py_source.controller_id,
        targets=(("permanent", py_forest.id),),
    )
    assert py_forest.tapped is False
    assert len(py_state.log) == pre_log_len, (
        "Re-resolving on the already-untapped Forest must be a no-op "
        "(idempotency mirror — Rust's is_legal early-out + Python's "
        "tap.py:207 early-out)"
    )
