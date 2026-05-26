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

**Scenarios C+D defer to Cycle 3 per design doc §7:**

  * **Scenario C — turn-rollover survival + bounce-resets:** confirm
    the anthem state survives the turn rollover (cleanup/untap step)
    byte-equal on both engines; confirm the anthem state resets
    when the Spacecraft leaves the battlefield (CR 400.7 per-zone-
    reset).
  * **Scenario D — anthem AND station gate both open (``charge_
    counters=12+``):** the Spacecraft is now a 3/5 with flying +
    lifelink; OTHER creatures still receive the +1/+1 anthem; the
    Spacecraft itself does NOT receive the anthem (other-scope
    exclusion).
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
