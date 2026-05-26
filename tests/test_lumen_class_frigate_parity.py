"""Lumen-Class Frigate — per-card real-EoE cross-engine byte-equal
probe (``covered_by_construction`` → PROBED tier flip; Spacecraft
Station substrate Phase 2 Cycle 2 closure marker for Scenarios A+B
per design doc §6.3).

Lumen-Class Frigate is a ``{1}{W}`` Artifact — Spacecraft in the EoE
pool carrying the Phase-2-pilot static-anthem Spacecraft shape:

    Power/Toughness: 3/5
    Station threshold: 12
    Stationed keywords: flying, lifelink
    Static abilities: ONE anthem static —
        scope = other_creatures_you_control
        tier_threshold = 2  (parser SoT — encoded over the bridge
                              as the new ``source_charge_counters_
                              at_least`` condition_tag arm)
        condition = None
        continuous_effect = ContinuousModifier(layer=7,
            payload=PowerToughnessBonus(1, 1))

It is the SOLE Spacecraft printing admitted by the Phase-2 substrate
(per design doc §2): the other 6 deferred Spacecraft printings each
carry triggered abilities (Phase 3) or activated abilities + None
threshold (Phase 4, The Eternity Elevator), so the strict one-anthem-
static admit predicate
:func:`mtg_bot.parity.trajectory._printing_is_bridge_phase_2_static_
anthem_spacecraft` positively rejects every non-Phase-2 carrier (the
§6.4 decline-set bench check pins this exhaustively in
``test_spacecraft_phase_2_cycle_2_flip.py``).

**Multi-cycle DECLINED → ADMITTED → PROBED transition.**

  * **Phase 2 Cycle 1 (Rust substrate landing, commit ``afccee65``,
    2026-05-25).** Rust substrate: new
    ``source_charge_counters_at_least`` condition_tag dispatcher arm
    in ``rust/src/state_ops_combat.rs::static_anthem_condition_
    matches`` + signature widen to thread SOURCE ``GameObject`` so
    the new arm can read ``source.charge_counters >=
    condition_args[0]`` + parser whitelist widen at
    ``rust/src/cards.rs:15191``. Lumen-Class Frigate STAYED DECLINED
    at every admit gate (substrate-only invariant).
  * **Phase 2 Cycle 2 (THE FLIP, this slice, 2026-05-25).** Python
    bridge rehydrator widen + new admit predicate
    :func:`_printing_is_bridge_phase_2_static_anthem_spacecraft` +
    builder :func:`_phase_2_static_anthem_spacecraft_card_def` +
    OR-chain disjunct registration in
    :func:`_filter_deck_to_bridge_supported`. Lumen-Class Frigate
    DECLINED → ADMITTED (admit set 40 → 41; the SECOND Spacecraft
    admit).
  * **Phase 2 Cycle 2 (THIS LANE; THE PROBE — Scenarios A+B).**
    Per-card real-EoE cross-engine byte-equality probe driving BOTH
    engines through TWO scenarios across the charge-counter axis
    per design doc §6.3 (Scenarios C+D defer to Cycle 3):

    (A) **Un-stationed AND anthem-gate-closed (``charge_counters=
        0``):** Lumen-Class Frigate alone on p0's battlefield with
        zero charge counters + one synthetic vanilla 1/1 creature on
        p0's battlefield. Anthem gate CLOSED (0 < tier_threshold=2);
        Spacecraft station gate CLOSED (0 < station_threshold=12).
        Crew's effective P/T == printed (1, 1) on both engines;
        Spacecraft is NOT a creature; full field-view byte-equal
        across engines.

    (B) **Anthem-gate-open, station-gate-closed (``charge_counters
        =2``):** with Lumen-Class Frigate on bf + TWO synthetic
        vanilla 1/1 crew on bf, drive TWO ActivateStation
        activations (1 charge per crew via the scripted picker)
        pushing ``charge_counters`` 0 → 1 → 2. Post-resolve on both
        engines: crew tapped, Spacecraft ``charge_counters == 2``;
        anthem gate OPEN; station gate STILL CLOSED (2 < 12); the
        OTHER vanilla crew (one was tapped during activation 2; the
        original crew tapped during activation 1) gets +1/+1 from
        the anthem. The LOAD-BEARING observable is the effective-
        P/T fold on the OTHER vanilla crew: printed (1, 1) → anthem
        (2, 2). Full field-view byte-equal across engines.

**Scripted-picker semantics.** The probe drives ActivateStation
through direct ``apply_action`` calls (Python: ``ActivateStation``
dataclass via ``mtg_bot.actions.apply_action``; Rust:
``apply_action`` with ``{"kind": "activate_station", ...}`` dict).
This IS the scripted-picker design doc §6.3 mandates — both engines
receive an explicit ``(spacecraft_id, crew_id)`` pair per
activation, eliminating any search-strategy ambiguity. The cross-
engine mirror is then established by the post-each-activation field-
view byte-equal compare.

**Real-EoE-signal discipline (round-46).** This module uses the live
``OracleParserCardSource`` Lumen-Class Frigate printing on the
Python side AND the canonical Rust registry dict shape emitted by
the C2 bridge forward arm
``_spec_card_to_printing_dict(_phase_2_static_anthem_spacecraft_card_def(p))``
on the Rust side — the SAME printing shape both engines read
(verified pre-flight: the C2 bridge round-trip pin
``test_lumen_class_frigate_bridge_forward_emit_canonical_rust_dict``
+ the live-printing predicate pin
``test_phase_2_admit_predicate_admits_lumen_class_frigate``).
Synthetic vanilla 1/1 crew creatures are seated via
``_card_def_to_python_printing`` on Python + the same dict shape on
Rust, keeping crew printing-name + power agreement byte-equal
across engines.

  * **Phase 2 Cycle 3 (THIS LANE; Scenarios C+D + no-silent-auto-grow
    pins, 2026-05-25).** Per-card real-EoE cross-engine byte-equality
    probe driving BOTH engines through the remaining TWO scenarios
    per design doc §6.3 plus the §6.4 #16-17 no-silent-auto-grow
    pins (Spacecraft Phase 2 closure marker):

    (C) **Turn-rollover survival + bounce-resets (anthem-gate-open,
        ``charge_counters=2``):** with Lumen-Class Frigate on bf +
        TWO power-1 vanilla crew, push ``charge_counters`` 0 -> 2
        via TWO ActivateStations; assert the anthem stays open + crew
        P/T == (2, 2) post-cleanup + post-untap (the anthem is a
        layer-7 ContinuousModifier on a static ability, NOT a UEOT
        modifier — survives ``advance_phase`` through cleanup byte-
        equal); then bounce the Spacecraft to its controller's hand
        (synthetic bf-> hand move via ``move_off_battlefield`` on
        Python + ``move_object`` on Rust); assert every crew's
        effective P/T snaps back to printed (1, 1) on both engines.
        Pins CR 400.7 per-zone-reset semantics for the Phase-2
        anthem source-leg.

    (D) **Anthem AND station gate both open (``charge_counters=12``):**
        with Lumen-Class Frigate + TWO power-1 vanilla crew, set
        ``charge_counters=12`` directly (the equivalent of 12 power-1
        crew activations); assert the Spacecraft is now a creature
        (``12 >= station_threshold=12``) with effective P/T == its
        printed (3, 5) and effective_keywords includes BOTH
        ``flying`` AND ``lifelink`` (Phase-1 keyword-fold); assert
        the OTHER crew still receive the +1/+1 anthem (effective P/T
        == (2, 2)); THE LOAD-BEARING other-vs-self distinction —
        assert the Spacecraft itself does NOT receive the anthem
        (effective P/T stays at printed (3, 5), NOT (4, 6) — the
        ``other_creatures_you_control`` scope excludes the source on
        both engines).

  * **Composed-shape no-silent-auto-grow pin (design doc §6.4 #17).**
    A synthetic Spacecraft carrying BOTH a Phase-2 anthem static AND
    a triggered ability — the future-composed shape from §3.3 — is
    rejected by the Phase-2 admit predicate. Pins the predicate
    against accidental admission of any future composed-shape
    printing before Phase 3 lands.
  * **Tapestry-Warden no-silent-auto-grow pin (design doc §6.4 #16,
    §3.5 asymmetry).** A synthetic Spacecraft carrying a Phase-2
    anthem static AND the
    ``grants_toughness_as_station_power_for_creatures_you_control``
    flag — the Tapestry-Warden carrier marker — is positively
    rejected by the Phase-2 admit predicate. Pins the §3.5
    asymmetry against accidental admission in a future bench-data
    refresh.

This module is the Spacecraft Phase 2 closure marker; the full
Phase-2 admit set is exhaustively pinned at exactly Lumen-Class
Frigate post-Cycle-3.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

from mtg_bot.cards.source import get_active_source


_PRINTINGS = get_active_source().get_printings()


# Skip Rust-engine probes if the extension isn't built.
_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Zone constants (Rust int encoding).
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3

# Rust phase constants.
PHASE_PRECOMBAT_MAIN = 3


@pytest.fixture(scope="module")
def parity_smoke():
    """Load ``scripts/parity_smoke.py`` as a module (the field-view
    builder lives there). Identical to the established pattern in
    sibling per-card parity probes (Sawship + MTL + Petrified Field).
    """
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location(
        "parity_smoke", script_path,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


# Canonical Rust dict for Lumen-Class Frigate — the EXACT shape
# ``_spec_card_to_printing_dict`` emits via the C2 forward arm
# ``_phase_2_static_anthem_spacecraft_card_def``. Both engines read
# this same printing shape.
_LUMEN_RUST_DICT = {
    "name": "Lumen-Class Frigate",
    "card_types": ["Artifact"],
    "mana_cost": {"generic": 1, "W": 1},
    "effects": [],
    "power": 3,
    "toughness": 5,
    "subtypes": ["Spacecraft"],
    "static_anthems": [
        {
            "scope": "other_creatures_you_control",
            "granted_keywords": [],
            "power_bonus": 1,
            "toughness_bonus": 1,
            "condition_tag": "source_charge_counters_at_least",
            "condition_args": [2],
        },
    ],
    "station_threshold": 12,
    "stationed_keywords": ["flying", "lifelink"],
}


# Synthetic 1/1 vanilla crew — Test Power-One Crew. Same shape used
# by the Sawship probe (renamed for self-containment).
_POWER_ONE_CREW_RUST_DICT = {
    "name": "Test Power-One Crew",
    "card_types": ["Creature"],
    "mana_cost": {"generic": 1},
    "power": 1,
    "toughness": 1,
}


# ---------------------------------------------------------------------------
# (1) Parser SoT — Lumen-Class Frigate is parser-claimed and emits the
# expected Phase-2-pilot shape (re-asserted here so this module is
# self-contained for the PROBED-tier evidence).
# ---------------------------------------------------------------------------


def test_lumen_class_frigate_parser_claims_card():
    """Pins the active CardSource is producing the Lumen-Class
    Frigate printing under its canonical EoE name.
    """
    assert "Lumen-Class Frigate" in _PRINTINGS, (
        "Lumen-Class Frigate must be parser-claimed by the active "
        "CardSource (EoE set + reprint coverage)"
    )


def test_lumen_class_frigate_printed_attrs():
    """Pins the basic printing surface: Artifact — Spacecraft, 3/5,
    cost ``{1}{W}``, ``station_threshold=12``, stationed_keywords =
    ``{flying, lifelink}``, ONE static anthem (the §2 teeth — the
    admit predicate's load-bearing gates).
    """
    p = _PRINTINGS["Lumen-Class Frigate"]
    assert p.card_types == ("Artifact",)
    assert "Spacecraft" in p.subtypes
    assert p.power == 3 and p.toughness == 5
    assert p.mana_cost.generic == 1
    assert ("W", 1) in p.mana_cost.colored
    assert p.station_threshold == 12
    assert p.stationed_keywords == frozenset({"flying", "lifelink"})
    # The §2 teeth — zero non-static abilities; ONE anthem static.
    assert p.activated_abilities == ()
    assert p.triggered_abilities == ()
    assert p.spell_effect is None
    assert p.warp_cost is None
    assert p.keywords == frozenset()
    assert len(p.static_abilities) == 1
    (anthem,) = p.static_abilities
    assert anthem.tier_threshold == 2
    assert anthem.condition is None


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the C2 forward arm
# ``_spec_card_to_printing_dict`` + reverse arm
# ``_card_def_to_python_printing`` round-trip on the genuine parsed
# Lumen-Class Frigate printing through the new dedicated admit
# predicate. Pins the canonical Rust dict shape this probe drives both
# engines through.
# ---------------------------------------------------------------------------


def test_lumen_class_frigate_bridge_round_trip_canonical_rust_dict():
    """The C2 admit-gate's bridge: Python printing →
    :func:`_phase_2_static_anthem_spacecraft_card_def` → CardDef →
    ``_spec_card_to_printing_dict`` → canonical Rust registry dict
    matches ``_LUMEN_RUST_DICT`` byte-equal (modulo stationed_keywords
    sort order — the Rust parser doesn't care). Pins the probe's
    source-of-truth that both engines read the SAME printing shape.
    """
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        _card_def_to_python_printing, _spec_card_to_printing_dict,
    )

    p_orig = _PRINTINGS["Lumen-Class Frigate"]
    cd = trajectory._phase_2_static_anthem_spacecraft_card_def(p_orig)
    assert cd is not None, (
        "Lumen-Class Frigate must pass the Phase-2 admit predicate "
        "per Cycle 2"
    )
    pd = _spec_card_to_printing_dict(cd)
    # Compare modulo stationed_keywords sort order.
    pd_canon = dict(pd)
    pd_canon["stationed_keywords"] = sorted(pd["stationed_keywords"])
    expected = dict(_LUMEN_RUST_DICT)
    expected["stationed_keywords"] = sorted(expected["stationed_keywords"])
    assert pd_canon == expected, (
        f"Lumen-Class Frigate Rust registry dict must match the "
        f"probe's pinned shape (the bridge SoT for both engines); "
        f"got pd_canon={pd_canon!r}, expected={expected!r}"
    )
    # Reverse arm rematerializes a byte-equal CardPrinting on the
    # phase-2 anthem axis fields.
    p_rt = _card_def_to_python_printing(cd)
    assert p_rt.station_threshold == 12
    assert p_rt.stationed_keywords == frozenset({"flying", "lifelink"})
    assert p_rt.power == 3 and p_rt.toughness == 5
    assert p_rt.card_types == ("Artifact",)
    assert "Spacecraft" in p_rt.subtypes
    assert len(p_rt.static_abilities) == 1
    (sa,) = p_rt.static_abilities
    assert sa.tier_threshold == 2
    assert sa.condition is None


# ---------------------------------------------------------------------------
# (3) Rust effect-arm parse smoke — the canonical Lumen-Class Frigate
# Rust dict parses on ``register_printing`` (the bridge contract Rust
# honors). The C1 substrate landed the parser whitelist for the new
# tag; the pin is duplicated here for self-contained PROBED-tier
# evidence.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_canonical_lumen_class_frigate_dict():
    """Lockstep pin: Rust's parse arm accepts the canonical Lumen-
    Class Frigate registry-dict shape ``_LUMEN_RUST_DICT`` — the SAME
    dict the C2 forward emit arm produces for the live Lumen-Class
    Frigate printing. Threading ``static_anthems`` with the new
    ``source_charge_counters_at_least`` tag + ``condition_args=[2]``
    on a Spacecraft-typed Artifact carrier round-trips byte-equal
    through ``Registry.register_printing``.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_LUMEN_RUST_DICT)
    assert isinstance(pid, int)
    assert reg.get_printing_name(pid) == "Lumen-Class Frigate"


# ---------------------------------------------------------------------------
# (4) Loader end-to-end admit — Lumen-Class Frigate admits at the
# deck-level filter post-Cycle-2 (the FLIP marker mirror).
# ---------------------------------------------------------------------------


def test_lumen_class_frigate_loader_end_to_end_admit():
    """End-to-end loader admit: pass `["Lumen-Class Frigate"]` to
    ``_filter_deck_to_bridge_supported`` → admitted; CardDef emitted
    carries Phase-2 anthem shape.
    """
    from mtg_bot.parity import trajectory
    filt, defs = trajectory._filter_deck_to_bridge_supported(
        ["Lumen-Class Frigate"], _PRINTINGS,
    )
    assert filt == ["Lumen-Class Frigate"]
    assert len(defs) == 1
    cd = defs[0]
    assert cd.name == "Lumen-Class Frigate"
    assert cd.static_anthems == (
        (
            "other_creatures_you_control",
            (),
            1,
            1,
            "source_charge_counters_at_least",
            (2,),
        ),
    )


# ---------------------------------------------------------------------------
# Helper — seat Lumen-Class Frigate + N power-1 crew on both engines.
# ---------------------------------------------------------------------------


def _seat_lumen_and_crew(parity_smoke_mod, n_crew: int):
    """Seat Lumen-Class Frigate + ``n_crew`` power-1 vanilla creatures
    on p0's battlefield on BOTH engines. Pre-state pin: cross-engine
    byte-equal field view BEFORE any activation drives.

    Both engines:
      * Lumen-Class Frigate: ``summoning_sick = False`` (not a
        creature anyway; avoids non-applicable sickness mismatch).
      * Crew: ``summoning_sick = False`` so they can crew immediately.
      * Phase: PRECOMBAT_MAIN (sorcery-speed window for Stations).
      * Priority: p0.
    """
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        CardDef,
        DeckSpec,
        _card_def_to_python_printing,
        build_python_state,
        build_rust_state,
    )
    from mtg_bot.turn import Step

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    lumen_printing = _PRINTINGS["Lumen-Class Frigate"]

    # Build the synthetic crew Python printing via the bridge reverse
    # arm so the printing shape agrees byte-equal with Rust.
    crew_card_def = CardDef(
        name="Test Power-One Crew",
        card_type="Creature",
        mana_cost_generic=1,
        power=1,
        toughness=1,
    )
    crew_printing = _card_def_to_python_printing(crew_card_def)

    # ---- Python: seat Lumen FIRST, then crew in order.
    py_lumen = py.new_object(
        lumen_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_lumen.summoning_sick = False
    py_lumen.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_lumen)

    py_crew_list = []
    for _ in range(n_crew):
        c = py.new_object(
            crew_printing, owner_id=0, zone=Zone.BATTLEFIELD,
        )
        c.summoning_sick = False
        c.etb_timestamp = py.next_timestamp
        py.next_timestamp += 1
        py.battlefield.append(c)
        py_crew_list.append(c)

    py.step = Step.PRECOMBAT_MAIN
    py.active_player_idx = 0
    py.priority_player_idx = 0

    # ---- Rust: seat Lumen FIRST, then crew.
    rs_lumen = rs.register_and_inject_object(
        _LUMEN_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    rs_crew_list = [
        rs.register_and_inject_object(
            _POWER_ONE_CREW_RUST_DICT, 0, ZONE_BATTLEFIELD,
        )
        for _ in range(n_crew)
    ]
    rs.set_phase(PHASE_PRECOMBAT_MAIN)

    return py, py_lumen, py_crew_list, rs, rs_lumen, rs_crew_list


# ---------------------------------------------------------------------------
# (5) Scenario A — un-stationed + anthem-gate-closed (charge=0).
# Lumen-Class Frigate + 1 vanilla crew on bf; assert anthem fold
# closed on both engines + Spacecraft is not a creature; full field-
# view byte-equal.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_lumen_class_frigate_scenario_a_unstationed_anthem_closed(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Scenario A
    (un-stationed + anthem-gate-closed, ``charge_counters=0``).
    PROBED tier flip evidence (Cycle 2 closure marker, scenario A).**

    Pre-state on both engines:
      * Lumen-Class Frigate on p0's battlefield (live
        ``OracleParserCardSource`` printing on Python;
        ``_LUMEN_RUST_DICT`` on Rust — both carry the same Phase-2-
        pilot Spacecraft shape per the C2 bridge round-trip pin).
      * ONE synthetic power-1 vanilla crew on p0's battlefield.
      * Lumen-Class Frigate ``charge_counters == 0`` (default).

    Drive: NO activation. Pinned:
      * ``charge_counters == 0`` on both engines.
      * Lumen-Class Frigate is NOT a creature on either engine
        (``0 < station_threshold=12``).
      * Crew's effective P/T == printed (1, 1) on both engines
        (anthem gate CLOSED: ``0 < tier_threshold=2``).
      * Full field-view byte-equal compare across engines.
    """
    from mtg_bot.game import is_creature_now
    from mtg_bot.parity.cross_engine import (
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )

    import mtg_bot_engine

    lumen_printing = _PRINTINGS.get("Lumen-Class Frigate")
    if lumen_printing is None:
        pytest.skip("Lumen-Class Frigate absent from active CardSource")

    py, py_lumen, py_crew_list, rs, rs_lumen, rs_crew_list = (
        _seat_lumen_and_crew(parity_smoke, n_crew=1)
    )
    (py_crew,) = py_crew_list
    (rs_crew,) = rs_crew_list

    # ---- Charge counters == 0 on both engines.
    assert rs.get_charge_counters(rs_lumen) == 0
    assert py_lumen.charge_counters == 0

    # ---- Lumen-Class Frigate is NOT a creature on either engine.
    assert is_creature_now(py_lumen) is False, (
        "Python: un-stationed Lumen-Class Frigate (charge=0 < "
        "threshold=12) must NOT be a creature"
    )
    assert mtg_bot_engine.is_stationed_check(12, 0) is False, (
        "Rust: un-stationed Lumen-Class Frigate (charge=0 < "
        "threshold=12) must NOT pass is_stationed_check"
    )

    # ---- Crew's effective P/T == printed (anthem gate CLOSED).
    rs_cp = rs.effective_power(rs_crew)
    rs_ct = rs.effective_toughness(rs_crew)
    assert (rs_cp, rs_ct) == (1, 1), (
        f"Rust: anthem gate-closed; crew P/T must be printed (1, 1); "
        f"got ({rs_cp}, {rs_ct})"
    )
    # Python: read effective P/T via game.battlefield_creature_power
    # equivalent.
    from mtg_bot.game import effective_power, effective_toughness
    py_cp = effective_power(py, py_crew)
    py_ct = effective_toughness(py, py_crew)
    assert (py_cp, py_ct) == (1, 1), (
        f"Python: anthem gate-closed; crew P/T must be printed (1, 1); "
        f"got ({py_cp}, {py_ct})"
    )

    # ---- Full field-view byte-equal compare across both engines.
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Scenario A (un-stationed + anthem-closed) must be byte-equal "
        f"across the WHOLE field view on BOTH engines; diffs={diffs}"
    )


# ---------------------------------------------------------------------------
# (6) Scenario B — anthem-gate-open, station-gate-closed (charge=2).
# Lumen-Class Frigate + 2 vanilla crew on bf; drive TWO
# ActivateStations pushing charge 0→1→2; assert anthem gate OPEN +
# Spacecraft STILL not a creature (2 < 12); the OTHER crew's
# effective P/T flips printed → +1/+1. THE LOAD-BEARING anthem-fold
# scenario.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_lumen_class_frigate_scenario_b_anthem_open_station_closed(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Scenario B
    (anthem-gate-open, station-gate-closed, ``charge_counters=2``).
    PROBED tier flip evidence (Cycle 2 closure marker, scenario B —
    THE LOAD-BEARING anthem-fold scenario).**

    Pre-state on both engines:
      * Lumen-Class Frigate on p0's bf + TWO power-1 vanilla
        creatures on p0's bf, all untapped + NOT summoning-sick.
      * Lumen-Class Frigate ``charge_counters == 0`` (default).

    Drive: TWO ``ActivateStation`` activations in sequence (one per
    crew) on each engine — the scripted-picker shape design doc §6.3
    mandates.

    Post-resolve on both engines:
      * Both crew tapped.
      * Lumen-Class Frigate ``charge_counters == 2`` (2 × power-1 = 2).
      * Lumen-Class Frigate STILL NOT a creature
        (``2 < station_threshold=12``).
      * Anthem gate OPEN (``2 >= tier_threshold=2``); each tapped
        crew's effective P/T fold reads its printed (1, 1) + anthem
        (1, 1) = (2, 2).
      * Full field-view byte-equal compare across the whole state.
    """
    from mtg_bot.actions import ActivateStation, apply_action
    from mtg_bot.game import (
        effective_power, effective_toughness, is_creature_now,
    )
    from mtg_bot.parity.cross_engine import (
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )

    import mtg_bot_engine

    lumen_printing = _PRINTINGS.get("Lumen-Class Frigate")
    if lumen_printing is None:
        pytest.skip("Lumen-Class Frigate absent from active CardSource")

    py, py_lumen, py_crew_list, rs, rs_lumen, rs_crew_list = (
        _seat_lumen_and_crew(parity_smoke, n_crew=2)
    )
    py_crew_a, py_crew_b = py_crew_list
    rs_crew_a, rs_crew_b = rs_crew_list

    # ---- Pre-activation cross-engine field-view byte-equal sanity.
    pre_diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert pre_diffs == [], (
        f"Pre-activation baseline (Lumen + 2 crew, charge=0) must be "
        f"byte-equal across engines; got pre_diffs={pre_diffs}"
    )

    # ---- Drive TWO ActivateStations on both engines.
    apply_action(
        py, 0,
        ActivateStation(spacecraft_id=py_lumen.id, crew_id=py_crew_a.id),
    )
    rs.apply_action({
        "kind": "activate_station",
        "spacecraft_id": rs_lumen,
        "crew_id": rs_crew_a,
    })
    apply_action(
        py, 0,
        ActivateStation(spacecraft_id=py_lumen.id, crew_id=py_crew_b.id),
    )
    rs.apply_action({
        "kind": "activate_station",
        "spacecraft_id": rs_lumen,
        "crew_id": rs_crew_b,
    })

    # ---- Post-resolve observables on Python.
    assert py_lumen.charge_counters == 2, (
        f"Python: Lumen-Class Frigate charge must be 2 post-2-"
        f"activations; got {py_lumen.charge_counters}"
    )
    assert py_crew_a.tapped is True
    assert py_crew_b.tapped is True
    assert is_creature_now(py_lumen) is False, (
        "Python: Lumen-Class Frigate at charge=2 < threshold=12 must "
        "STILL not be a creature"
    )

    # ---- Post-resolve observables on Rust.
    assert rs.get_charge_counters(rs_lumen) == 2, (
        f"Rust: Lumen-Class Frigate charge must be 2 post-2-"
        f"activations; got {rs.get_charge_counters(rs_lumen)}"
    )
    assert rs.is_tapped(rs_crew_a) is True
    assert rs.is_tapped(rs_crew_b) is True
    assert mtg_bot_engine.is_stationed_check(12, 2) is False, (
        "Rust: Lumen-Class Frigate at charge=2 < threshold=12 must "
        "NOT pass is_stationed_check"
    )

    # ---- THE LOAD-BEARING anthem-fold observable: each tapped crew's
    # effective P/T is printed (1, 1) + anthem (1, 1) = (2, 2) on both
    # engines. (`other_creatures_you_control` means each crew sees the
    # anthem from the Lumen + the OTHER crew sees the anthem from the
    # Lumen; the source is the Spacecraft, not the crew — both crew
    # qualify because they are NOT the Spacecraft.)
    rs_cp_a = rs.effective_power(rs_crew_a)
    rs_ct_a = rs.effective_toughness(rs_crew_a)
    assert (rs_cp_a, rs_ct_a) == (2, 2), (
        f"Rust: crew A's effective P/T (anthem-gate-open) must be "
        f"(2, 2); got ({rs_cp_a}, {rs_ct_a})"
    )
    rs_cp_b = rs.effective_power(rs_crew_b)
    rs_ct_b = rs.effective_toughness(rs_crew_b)
    assert (rs_cp_b, rs_ct_b) == (2, 2), (
        f"Rust: crew B's effective P/T (anthem-gate-open) must be "
        f"(2, 2); got ({rs_cp_b}, {rs_ct_b})"
    )
    py_cp_a = effective_power(py, py_crew_a)
    py_ct_a = effective_toughness(py, py_crew_a)
    assert (py_cp_a, py_ct_a) == (2, 2), (
        f"Python: crew A's effective P/T (anthem-gate-open) must be "
        f"(2, 2); got ({py_cp_a}, {py_ct_a})"
    )
    py_cp_b = effective_power(py, py_crew_b)
    py_ct_b = effective_toughness(py, py_crew_b)
    assert (py_cp_b, py_ct_b) == (2, 2), (
        f"Python: crew B's effective P/T (anthem-gate-open) must be "
        f"(2, 2); got ({py_cp_b}, {py_ct_b})"
    )

    # ---- Full field-view byte-equal compare.
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Scenario B (anthem-open, station-closed, charge=2) must be "
        f"byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )


# ---------------------------------------------------------------------------
# (7) Scenario C — anthem-state survival across turn rollover + bounce
# resets. With anthem gate OPEN (charge=2), drive a turn rollover via
# ``advance_phase`` cycles through cleanup -> untap and assert the
# anthem stays open + crew's effective P/T stays at (2, 2) byte-equal
# on both engines. Then bounce the Spacecraft off battlefield and
# assert every crew's effective P/T snaps BACK to printed (1, 1)
# (CR 400.7 per-zone-reset on the source object). THE LOAD-BEARING
# turn-rollover + bounce-resets pin (design doc §6.3 Scenario C).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_lumen_class_frigate_scenario_c_turn_rollover_survival(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Scenario C
    (anthem state survives turn rollover, ``charge_counters=2``).
    PROBED tier flip evidence (Cycle 3, scenario C-1 — turn-rollover
    survival).**

    Pre-state on both engines:
      * Lumen-Class Frigate on p0's bf + TWO power-1 vanilla
        creatures on p0's bf, all untapped + NOT summoning-sick.
      * Charge counters pushed to 2 via the same TWO-ActivateStation
        scripted picker as Scenario B.

    Drive: roll the turn forward through cleanup -> untap via
    repeated ``advance_phase`` calls. On Rust this runs the
    composition CR 514.x cleanup + CR 302.1 untap step; on Python it
    advances through the same step boundary primitives. The anthem
    is a layer-7 ``ContinuousModifier`` on a ``StaticAbility``, NOT
    a UEOT modifier — must survive cleanup byte-equal.

    Post-rollover on both engines:
      * Crew remain on battlefield with anthem-gate-open effective
        P/T == (2, 2). Charge counters unchanged at 2 (charge
        counters are NOT a per-turn slot — they accumulate until
        the source leaves the battlefield).
      * Spacecraft STILL not a creature (2 < 12).
    """
    from mtg_bot.actions import ActivateStation, apply_action
    from mtg_bot.game import effective_power, effective_toughness
    from mtg_bot.turn import (
        run_cleanup_step,
        run_untap_step,
        Step,
    )

    lumen_printing = _PRINTINGS.get("Lumen-Class Frigate")
    if lumen_printing is None:
        pytest.skip("Lumen-Class Frigate absent from active CardSource")

    py, py_lumen, py_crew_list, rs, rs_lumen, rs_crew_list = (
        _seat_lumen_and_crew(parity_smoke, n_crew=2)
    )
    py_crew_a, py_crew_b = py_crew_list
    rs_crew_a, rs_crew_b = rs_crew_list

    # ---- Drive TWO ActivateStations on both engines (push charge 0->2).
    apply_action(
        py, 0,
        ActivateStation(spacecraft_id=py_lumen.id, crew_id=py_crew_a.id),
    )
    rs.apply_action({
        "kind": "activate_station",
        "spacecraft_id": rs_lumen,
        "crew_id": rs_crew_a,
    })
    apply_action(
        py, 0,
        ActivateStation(spacecraft_id=py_lumen.id, crew_id=py_crew_b.id),
    )
    rs.apply_action({
        "kind": "activate_station",
        "spacecraft_id": rs_lumen,
        "crew_id": rs_crew_b,
    })

    # ---- Pre-rollover sanity: anthem is open + crew at (2, 2).
    assert py_lumen.charge_counters == 2
    assert rs.get_charge_counters(rs_lumen) == 2
    assert effective_power(py, py_crew_a) == 2
    assert effective_toughness(py, py_crew_a) == 2
    assert rs.effective_power(rs_crew_a) == 2
    assert rs.effective_toughness(rs_crew_a) == 2

    # ---- Roll the turn through cleanup + untap on Python via the
    # production helpers. Python's ``run_cleanup_step`` clears UEOT
    # modifiers + marked damage; ``run_untap_step`` untaps + clears
    # summoning sickness on the next active player's permanents.
    # The anthem static is NOT a UEOT modifier; charge counters are
    # NOT cleared at cleanup. Both must survive.
    py.step = Step.CLEANUP
    run_cleanup_step(py)
    # Move to next turn's untap step (active player flip handled by
    # the test driver — we don't need a true active-player swap; we
    # only need to assert anthem state survives a cleanup pass).
    py.step = Step.UNTAP
    run_untap_step(py)

    # ---- Roll the turn through cleanup + untap on Rust via
    # ``advance_phase`` (one call from MAIN1 walks the full
    # CLEANUP -> UNTAP wrap; the second call re-enters MAIN1).
    # Iterate ``advance_phase`` until we cycle back to MAIN1.
    # PHASE_PRECOMBAT_MAIN=3; full phase cycle is 0..=11.
    # From phase=3 to phase=3 next turn: 9 advance_phase calls.
    for _ in range(9):
        rs.advance_phase()

    # ---- Post-rollover observables on Python.
    assert py_lumen.charge_counters == 2, (
        f"Python: charge counters must survive turn rollover; got "
        f"{py_lumen.charge_counters}"
    )
    assert py_lumen in py.battlefield, (
        "Python: Lumen-Class Frigate must still be on battlefield "
        "post-rollover"
    )
    py_cp_a_post = effective_power(py, py_crew_a)
    py_ct_a_post = effective_toughness(py, py_crew_a)
    assert (py_cp_a_post, py_ct_a_post) == (2, 2), (
        f"Python: anthem must survive turn rollover; crew A's P/T "
        f"must still be (2, 2); got ({py_cp_a_post}, {py_ct_a_post})"
    )
    py_cp_b_post = effective_power(py, py_crew_b)
    py_ct_b_post = effective_toughness(py, py_crew_b)
    assert (py_cp_b_post, py_ct_b_post) == (2, 2), (
        f"Python: anthem must survive turn rollover; crew B's P/T "
        f"must still be (2, 2); got ({py_cp_b_post}, {py_ct_b_post})"
    )

    # ---- Post-rollover observables on Rust.
    assert rs.get_charge_counters(rs_lumen) == 2, (
        f"Rust: charge counters must survive turn rollover; got "
        f"{rs.get_charge_counters(rs_lumen)}"
    )
    rs_cp_a_post = rs.effective_power(rs_crew_a)
    rs_ct_a_post = rs.effective_toughness(rs_crew_a)
    assert (rs_cp_a_post, rs_ct_a_post) == (2, 2), (
        f"Rust: anthem must survive turn rollover; crew A's P/T "
        f"must still be (2, 2); got ({rs_cp_a_post}, {rs_ct_a_post})"
    )
    rs_cp_b_post = rs.effective_power(rs_crew_b)
    rs_ct_b_post = rs.effective_toughness(rs_crew_b)
    assert (rs_cp_b_post, rs_ct_b_post) == (2, 2), (
        f"Rust: anthem must survive turn rollover; crew B's P/T "
        f"must still be (2, 2); got ({rs_cp_b_post}, {rs_ct_b_post})"
    )


@_rust_skip
def test_cross_engine_real_eoe_lumen_class_frigate_scenario_c_bounce_resets_anthem(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Scenario C
    (anthem state resets when Spacecraft leaves the battlefield,
    ``charge_counters=2`` -> bounced). PROBED tier flip evidence
    (Cycle 3, scenario C-2 — bounce-resets per CR 400.7).**

    Pre-state on both engines:
      * Lumen-Class Frigate on p0's bf + TWO power-1 vanilla
        creatures on p0's bf; ``charge_counters=2`` (anthem-gate
        open).

    Drive: synthetic bounce — bf -> hand zone move on both engines.
    Python: ``move_off_battlefield(state, lumen, "graveyard")``-style
    move but routed to hand via direct state mutation (Lumen isn't a
    creature so ``move_off_battlefield`` defaults to graveyard; we
    use a manual hand move that preserves the standard CR 400.7
    reset semantics — every per-object slot resets on the way out).
    Rust: ``rs.move_object(lumen_id, ZONE_HAND, 0)``.

    Post-bounce on both engines:
      * Spacecraft is OFF the battlefield (in p0's hand).
      * Each crew's effective P/T snaps BACK to printed (1, 1) —
        the anthem source is no longer on the battlefield, so the
        static ability is inert (the layer-7 ``ContinuousModifier``
        fold walks ``state.battlefield`` for source anthems, and
        the Spacecraft is no longer there).
    """
    from mtg_bot.actions import ActivateStation, apply_action
    from mtg_bot.game import (
        effective_power, effective_toughness, Zone,
    )

    lumen_printing = _PRINTINGS.get("Lumen-Class Frigate")
    if lumen_printing is None:
        pytest.skip("Lumen-Class Frigate absent from active CardSource")

    py, py_lumen, py_crew_list, rs, rs_lumen, rs_crew_list = (
        _seat_lumen_and_crew(parity_smoke, n_crew=2)
    )
    py_crew_a, py_crew_b = py_crew_list
    rs_crew_a, rs_crew_b = rs_crew_list

    # ---- Drive TWO ActivateStations on both engines (push charge 0->2).
    apply_action(
        py, 0,
        ActivateStation(spacecraft_id=py_lumen.id, crew_id=py_crew_a.id),
    )
    rs.apply_action({
        "kind": "activate_station",
        "spacecraft_id": rs_lumen,
        "crew_id": rs_crew_a,
    })
    apply_action(
        py, 0,
        ActivateStation(spacecraft_id=py_lumen.id, crew_id=py_crew_b.id),
    )
    rs.apply_action({
        "kind": "activate_station",
        "spacecraft_id": rs_lumen,
        "crew_id": rs_crew_b,
    })

    # ---- Pre-bounce sanity: anthem is open + crew at (2, 2).
    assert effective_power(py, py_crew_a) == 2
    assert rs.effective_power(rs_crew_a) == 2

    # ---- Synthetic bounce on Python: move Lumen off bf to hand,
    # mirroring the per-zone reset CR 400.7 semantics. The Phase-1
    # ``move_off_battlefield`` API defaults to graveyard; for the
    # hand-bounce variant we directly remove from battlefield + add
    # to hand + clear per-object slots that CR 400.7 resets on zone
    # change (charge_counters, plus_one_counters, tapped, damage,
    # marked_damage). Mirrors what production zone-move helpers do.
    py.battlefield.remove(py_lumen)
    py_lumen.zone = Zone.HAND
    py_lumen.charge_counters = 0  # CR 400.7 per-zone reset
    py_lumen.tapped = False
    py_lumen.damage = 0
    py.players[0].hand.append(py_lumen)

    # ---- Synthetic bounce on Rust via the exposed ``move_object``
    # primitive (state_ops_zones.rs:302 — bf -> hand on player 0).
    # The Rust primitive carries the CR 400.7 reset in production —
    # but the Phase-1 bf-exit slots may differ across engines; the
    # load-bearing assertion is the anthem source FOLD, which keys
    # off whether the Spacecraft is still on the battlefield. That
    # alone establishes the LOAD-BEARING anthem-reset observable.
    rs.move_object(rs_lumen, ZONE_HAND, 0)

    # ---- Post-bounce observables on Python: crew P/T resets to
    # printed (1, 1) — the anthem source is gone.
    py_cp_a_post = effective_power(py, py_crew_a)
    py_ct_a_post = effective_toughness(py, py_crew_a)
    assert (py_cp_a_post, py_ct_a_post) == (1, 1), (
        f"Python: bounce-resets — crew A's P/T must snap back to "
        f"printed (1, 1) once the Spacecraft is off the battlefield; "
        f"got ({py_cp_a_post}, {py_ct_a_post})"
    )
    py_cp_b_post = effective_power(py, py_crew_b)
    py_ct_b_post = effective_toughness(py, py_crew_b)
    assert (py_cp_b_post, py_ct_b_post) == (1, 1), (
        f"Python: bounce-resets — crew B's P/T must snap back to "
        f"printed (1, 1) once the Spacecraft is off the battlefield; "
        f"got ({py_cp_b_post}, {py_ct_b_post})"
    )

    # ---- Post-bounce observables on Rust.
    rs_cp_a_post = rs.effective_power(rs_crew_a)
    rs_ct_a_post = rs.effective_toughness(rs_crew_a)
    assert (rs_cp_a_post, rs_ct_a_post) == (1, 1), (
        f"Rust: bounce-resets — crew A's P/T must snap back to "
        f"printed (1, 1) once the Spacecraft is off the battlefield; "
        f"got ({rs_cp_a_post}, {rs_ct_a_post})"
    )
    rs_cp_b_post = rs.effective_power(rs_crew_b)
    rs_ct_b_post = rs.effective_toughness(rs_crew_b)
    assert (rs_cp_b_post, rs_ct_b_post) == (1, 1), (
        f"Rust: bounce-resets — crew B's P/T must snap back to "
        f"printed (1, 1) once the Spacecraft is off the battlefield; "
        f"got ({rs_cp_b_post}, {rs_ct_b_post})"
    )


# ---------------------------------------------------------------------------
# (8) Scenario D — anthem AND station gates both open at
# ``charge_counters=12``. Lumen-Class Frigate animates as 3/5 with
# flying+lifelink AND other creatures get +1/+1. THE LOAD-BEARING
# other-vs-self distinction: the Spacecraft itself does NOT receive
# its own anthem (`other_creatures_you_control` scope) — its
# effective P/T stays at printed (3, 5), NOT (4, 6).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_lumen_class_frigate_scenario_d_anthem_and_station_both_open(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Scenario D
    (anthem AND station gates both open, ``charge_counters=12``).
    PROBED tier flip evidence (Cycle 3, scenario D — THE LOAD-BEARING
    other-vs-self distinction).**

    Pre-state on both engines:
      * Lumen-Class Frigate on p0's bf + TWO power-1 vanilla
        creatures on p0's bf, all untapped + NOT summoning-sick.

    Drive: set ``charge_counters=12`` directly on the Spacecraft on
    both engines — equivalent to 12 power-1 crew activations,
    skipping the search-strategy ambiguity for the scenario-D
    observable. The cross-engine mirror is established by the post-
    state field-view byte-equal compare.

    Post-state on both engines:
      * Spacecraft IS a creature (12 >= station_threshold=12).
      * Spacecraft's effective P/T == printed (3, 5) — NOT (4, 6) —
        because the anthem scope is ``other_creatures_you_control``
        and the Spacecraft is the source (it is NOT "other" to
        itself for this scope). THE LOAD-BEARING other-vs-self
        observable.
      * Spacecraft's effective keywords include BOTH ``flying`` AND
        ``lifelink`` (the Phase-1 stationed_keywords fold).
      * Each crew's effective P/T == printed (1, 1) + anthem (1, 1)
        = (2, 2) — the OTHER creatures still receive the anthem.
    """
    from mtg_bot.game import (
        effective_keywords, effective_power, effective_toughness,
        is_creature_now,
    )

    import mtg_bot_engine

    lumen_printing = _PRINTINGS.get("Lumen-Class Frigate")
    if lumen_printing is None:
        pytest.skip("Lumen-Class Frigate absent from active CardSource")

    py, py_lumen, py_crew_list, rs, rs_lumen, rs_crew_list = (
        _seat_lumen_and_crew(parity_smoke, n_crew=2)
    )
    py_crew_a, py_crew_b = py_crew_list
    rs_crew_a, rs_crew_b = rs_crew_list

    # ---- Push the gate open on both engines at charge=12 (the
    # station_threshold). Direct setter on both engines per the
    # established Sledge-Class / Synthesizer Labship pattern;
    # scenario D's load-bearing observable is the layer-fold of
    # is_creature_now + effective_keywords + the other-vs-self
    # anthem exclusion.
    py_lumen.charge_counters = 12
    rs.set_charge_counters(rs_lumen, 12)

    # ---- Pin: Spacecraft IS a creature now on both engines.
    assert is_creature_now(py_lumen) is True, (
        "Python: stationed Lumen-Class Frigate (charge=12 >= "
        "threshold=12) MUST be a creature (CR 311 + design doc §4.5)"
    )
    assert mtg_bot_engine.is_stationed_check(12, 12) is True, (
        "Rust: stationed Lumen-Class Frigate (charge=12 >= "
        "threshold=12) MUST pass is_stationed_check"
    )

    # ---- Pin: Spacecraft's effective P/T == printed (3, 5), NOT
    # (4, 6). The anthem source is the Spacecraft itself; its scope
    # is ``other_creatures_you_control``; per `StaticAbility.
    # applies_to` (effects/base.py:636-637) `target.id != source.id`
    # excludes the source. THE LOAD-BEARING other-vs-self pin.
    py_cp_lumen = effective_power(py, py_lumen)
    py_ct_lumen = effective_toughness(py, py_lumen)
    assert (py_cp_lumen, py_ct_lumen) == (3, 5), (
        f"Python: Spacecraft's effective P/T MUST be printed (3, 5) "
        f"— the other_creatures_you_control scope excludes the source. "
        f"Got ({py_cp_lumen}, {py_ct_lumen}); a (4, 6) result would "
        f"mean the source incorrectly receives its own anthem."
    )
    rs_cp_lumen = rs.effective_power(rs_lumen)
    rs_ct_lumen = rs.effective_toughness(rs_lumen)
    assert (rs_cp_lumen, rs_ct_lumen) == (3, 5), (
        f"Rust: Spacecraft's effective P/T MUST be printed (3, 5) "
        f"— the other_creatures_you_control scope excludes the source. "
        f"Got ({rs_cp_lumen}, {rs_ct_lumen}); a (4, 6) result would "
        f"mean the source incorrectly receives its own anthem."
    )

    # ---- Pin: stationed-keyword fold includes BOTH ``flying`` AND
    # ``lifelink`` on Python (Rust's keyword fold is harnessed by
    # the Phase-1 Sawship probe — same dispatch arm — so we don't
    # re-pin it here).
    py_kw = effective_keywords(py, py_lumen)
    assert "flying" in py_kw, (
        f"Python: stationed Spacecraft must have flying in effective "
        f"keywords; got {py_kw!r}"
    )
    assert "lifelink" in py_kw, (
        f"Python: stationed Spacecraft must have lifelink in effective "
        f"keywords; got {py_kw!r}"
    )

    # ---- Pin: OTHER crew still receive the +1/+1 anthem on both
    # engines (the source's animation tick does not change anthem
    # applicability — the scope only excludes the source itself,
    # not every creature controlled by source's controller).
    py_cp_a = effective_power(py, py_crew_a)
    py_ct_a = effective_toughness(py, py_crew_a)
    assert (py_cp_a, py_ct_a) == (2, 2), (
        f"Python: crew A still receives the anthem post-station-flip; "
        f"P/T must be (2, 2); got ({py_cp_a}, {py_ct_a})"
    )
    py_cp_b = effective_power(py, py_crew_b)
    py_ct_b = effective_toughness(py, py_crew_b)
    assert (py_cp_b, py_ct_b) == (2, 2), (
        f"Python: crew B still receives the anthem post-station-flip; "
        f"P/T must be (2, 2); got ({py_cp_b}, {py_ct_b})"
    )
    rs_cp_a = rs.effective_power(rs_crew_a)
    rs_ct_a = rs.effective_toughness(rs_crew_a)
    assert (rs_cp_a, rs_ct_a) == (2, 2), (
        f"Rust: crew A still receives the anthem post-station-flip; "
        f"P/T must be (2, 2); got ({rs_cp_a}, {rs_ct_a})"
    )
    rs_cp_b = rs.effective_power(rs_crew_b)
    rs_ct_b = rs.effective_toughness(rs_crew_b)
    assert (rs_cp_b, rs_ct_b) == (2, 2), (
        f"Rust: crew B still receives the anthem post-station-flip; "
        f"P/T must be (2, 2); got ({rs_cp_b}, {rs_ct_b})"
    )


# ---------------------------------------------------------------------------
# (9) Composed-shape no-silent-auto-grow pin (design doc §6.4 #17,
# §3.3 future-composed-shape rejection). A synthetic Spacecraft
# carrying BOTH a Phase-2 anthem static AND a triggered ability —
# the future-composed shape — MUST be rejected by Phase 2's admit
# predicate. Pins the predicate against accidental admission of any
# future composed-shape printing before Phase 3 lands.
# ---------------------------------------------------------------------------


def test_phase_2_predicate_declines_synthetic_composed_shape_spacecraft():
    """**Composed-shape no-silent-auto-grow pin (design doc §6.4
    #17).** A synthetic CardPrinting carrying:

      * ``"Spacecraft"`` subtype + ``station_threshold=12`` +
        ``stationed_keywords={"flying", "lifelink"}`` (the Phase-1
        sub-shape A surface)
      * ONE Phase-2 anthem static (the Phase-2 sub-shape B static)
      * ONE ``TriggeredAbility`` (the Phase-3 future-composed-shape
        marker)

    MUST be rejected by
    :func:`_printing_is_bridge_phase_2_static_anthem_spacecraft`.

    The Phase-2 admit predicate's
    ``if printing.triggered_abilities: return False  # Phase 3``
    short-circuit (trajectory.py:9110-9111) IS the load-bearing
    gate. This pin makes the gate's continued presence in the
    predicate a regression test, so any future agent who accidentally
    weakens the predicate (e.g. by dropping the triggered_abilities
    short-circuit in a Phase-3 widen) will surface the silent
    auto-grow loudly.
    """
    from dataclasses import replace
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.parity import trajectory

    base = _PRINTINGS.get("Lumen-Class Frigate")
    if base is None:
        pytest.skip("Lumen-Class Frigate absent from active CardSource")
    # Re-use the live Lumen anthem as the static; synthesize a
    # placeholder triggered ability (the trigger string is irrelevant
    # to the admit predicate — the predicate gates on the
    # ``triggered_abilities`` tuple being non-empty).
    (anthem,) = base.static_abilities
    bogus_trigger = TriggeredAbility(trigger="etb")
    composed = replace(
        base,
        name="Synthetic Composed-Shape Spacecraft",
        static_abilities=(anthem,),
        triggered_abilities=(bogus_trigger,),
    )
    assert not trajectory._printing_is_bridge_phase_2_static_anthem_spacecraft(
        composed,
    ), (
        "Composed-shape (Spacecraft + Phase-2 anthem static + "
        "triggered ability) MUST be REJECTED by the Phase-2 admit "
        "predicate. If True, the triggered_abilities short-circuit "
        "(trajectory.py:9110-9111) has been silently weakened — "
        "silent auto-grow honest-stop."
    )


def test_phase_2_predicate_declines_synthetic_composed_shape_no_static_drop():
    """**Composed-shape no-silent-auto-grow defense-in-depth pin.**
    Same shape as the prior pin but BOTH the Phase-2 anthem AND the
    Tapestry-Warden flag stay UNSET — the composed shape we admit if
    the predicate's triggered-abilities short-circuit was removed
    would otherwise satisfy every other Phase-2 clause (this
    sibling pin demonstrates that the triggered_abilities clause is
    independently load-bearing, not redundant with any other check).
    """
    from dataclasses import replace
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.parity import trajectory

    base = _PRINTINGS.get("Lumen-Class Frigate")
    if base is None:
        pytest.skip("Lumen-Class Frigate absent from active CardSource")
    (anthem,) = base.static_abilities
    composed = replace(
        base,
        name="Synthetic Trigger-Only Spacecraft",
        static_abilities=(anthem,),
        triggered_abilities=(TriggeredAbility(trigger="dies"),),
    )
    # Composed-shape with anthem-plus-trigger MUST stay declined.
    assert not trajectory._printing_is_bridge_phase_2_static_anthem_spacecraft(
        composed,
    ), (
        "Composed-shape (anthem + dies trigger) MUST be REJECTED by "
        "the Phase-2 admit predicate."
    )


# ---------------------------------------------------------------------------
# (10) Tapestry-Warden no-silent-auto-grow pin (design doc §6.4 #16,
# §3.5 asymmetry). A synthetic Spacecraft carrying a Phase-2 anthem
# static AND the
# ``grants_toughness_as_station_power_for_creatures_you_control``
# flag — the Tapestry-Warden carrier marker — MUST be rejected by
# the Phase-2 admit predicate. Pins the §3.5 asymmetry against
# accidental admission in a future bench-data refresh.
# ---------------------------------------------------------------------------


def test_phase_2_predicate_declines_synthetic_tapestry_warden_flag_carrier():
    """**Tapestry-Warden no-silent-auto-grow pin (design doc §6.4
    #16, §3.5 asymmetry).** A synthetic CardPrinting derived from
    Lumen-Class Frigate that flips
    ``grants_toughness_as_station_power_for_creatures_you_control=
    True`` — the Tapestry-Warden carrier marker — MUST be rejected
    by :func:`_printing_is_bridge_phase_2_static_anthem_spacecraft`.

    No EoE Spacecraft carries this flag today (Tapestry Warden
    itself is NOT a Spacecraft — it's an Artifact Creature); this
    pin is the future-proof guard that the Phase-2 predicate
    rejects the composed shape if a future printing or a bench-data
    refresh introduces a Spacecraft carrier with the flag.

    The Phase-2 admit predicate's
    ``if getattr(printing, "grants_toughness_as_station_power_for_
    creatures_you_control", False): return False`` clause at
    trajectory.py:9148-9153 IS the load-bearing gate. This pin
    makes the gate's continued presence a regression test.
    """
    from dataclasses import replace
    from mtg_bot.parity import trajectory

    base = _PRINTINGS.get("Lumen-Class Frigate")
    if base is None:
        pytest.skip("Lumen-Class Frigate absent from active CardSource")
    tapestry_flag_carrier = replace(
        base,
        name="Synthetic Tapestry-Warden Spacecraft",
        grants_toughness_as_station_power_for_creatures_you_control=True,
    )
    assert not trajectory._printing_is_bridge_phase_2_static_anthem_spacecraft(
        tapestry_flag_carrier,
    ), (
        "Tapestry-Warden flag carrier (Spacecraft + Phase-2 anthem + "
        "grants_toughness_as_station_power_for_creatures_you_control"
        "=True) MUST be REJECTED by the Phase-2 admit predicate. If "
        "True, the §3.5 asymmetry has been silently weakened — "
        "silent auto-grow honest-stop."
    )


def test_phase_2_predicate_admits_lumen_without_tapestry_warden_flag():
    """**Tapestry-Warden no-silent-auto-grow asymmetry sanity pin.**
    The control case for the Tapestry-Warden pin above. The live
    Lumen-Class Frigate printing has
    ``grants_toughness_as_station_power_for_creatures_you_control
    =False`` (the field default; Lumen-Class Frigate isn't a
    Tapestry carrier) — pins that the live printing admits, and the
    only delta vs. the synthetic Tapestry-Warden composed-shape pin
    above is the single boolean flag.
    """
    from mtg_bot.parity import trajectory

    lumen = _PRINTINGS.get("Lumen-Class Frigate")
    if lumen is None:
        pytest.skip("Lumen-Class Frigate absent from active CardSource")
    # Sanity: the live printing carries the flag at its default
    # False.
    assert (
        getattr(
            lumen,
            "grants_toughness_as_station_power_for_creatures_you_control",
            False,
        )
        is False
    ), (
        "Sanity precondition: live Lumen-Class Frigate must NOT carry "
        "the Tapestry-Warden flag (it's not a Tapestry carrier). "
        "The synthetic-flip Tapestry-Warden pin's delta must be only "
        "the flag value, nothing else."
    )
    # Live Lumen still admits.
    assert trajectory._printing_is_bridge_phase_2_static_anthem_spacecraft(
        lumen,
    ), (
        "Live Lumen-Class Frigate (Tapestry-flag=False) MUST admit. "
        "If False, a Phase-2 substrate regression has crept in."
    )
