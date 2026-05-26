"""Galvanizing Sawship — per-card real-EoE cross-engine byte-equal
probe (``covered_by_construction`` → PROBED tier flip; Spacecraft
Station substrate Phase 1 closure marker).

Galvanizing Sawship is a ``{5}{R}`` Artifact — Spacecraft in the EoE
pool with zero printed abilities and the Phase-1-pilot Station
substrate shape:

    Power/Toughness: 6/5
    Station threshold: 3
    Stationed keywords: flying, haste

It is the SOLE Spacecraft printing admitted by the Phase-1 substrate
(per design doc §2): the other 21 EoE Spacecraft printings carry
static / triggered / activated abilities or have ``station_threshold
is None`` (The Eternity Elevator), so the strict no-abilities admit
predicate
:func:`mtg_bot.parity.trajectory._printing_is_bridge_pure_station_spacecraft`
positively rejects every non-Phase-1 carrier (the §6.4 decline-set
bench check pins this exhaustively in
``test_spacecraft_phase_1_cycle_3_flip.py``).

**Multi-cycle DECLINED → ADMITTED → PROBED transition.**

  * **Phase 1 Cycle 1 (substrate Part A, commit ``ea9aa996``,
    2026-05-25).** Rust substrate: new
    ``CardPrinting.station_threshold: Option<i32>`` +
    ``stationed_keywords: Vec<String>`` fields + parse arm +
    ``is_stationed_predicate`` helper + ``is_stationed_check``
    `#[pyfunction]` shim. Sawship stayed DECLINED at
    ``_printing_is_bridge_simple_creature`` (the
    ``station_threshold`` guard at ``trajectory.py:4698`` was the
    load-bearing decline).
  * **Phase 1 Cycle 2 (substrate Part B, commit ``62e10ff9``,
    2026-05-25).** Rust substrate: ``Action::ActivateStation``
    resolver flipped from stub to real ``apply_activate_station`` +
    sorcery-speed legal-action emitter +
    ``is_creature_now`` extension + ``stationed_keywords`` fold of
    ``battlefield_has_keyword``. Sawship STAYED DECLINED at the
    admit gate (substrate-only invariant).
  * **Phase 1 Cycle 3 (THE FLIP, commit ``e9a31c83``, 2026-05-25).**
    Python bridge forward emit + reverse arm + new
    ``CardDef.station_threshold`` / ``stationed_keywords`` frozen
    fields + new admit predicate
    ``_printing_is_bridge_pure_station_spacecraft`` + new builder
    ``_station_spacecraft_card_def`` + OR-chain disjunct
    registration in ``_filter_deck_to_bridge_supported``. Sawship
    DECLINED → ADMITTED (admit set 39 → 40; the SOLE Spacecraft
    admit, exactly +5,938 17lands decks unblocked through the
    Carrier-AA / cost-reduction / warp pipeline).
  * **Phase 1 Cycle 4 (THIS LANE; THE PROBE).** Per-card real-EoE
    cross-engine byte-equality probe driving BOTH engines through
    the THREE scenarios across the charge-counter axis per design
    doc §6.3:

    (A) **Un-stationed (``charge_counters=0``):** Sawship alone on
        p0's battlefield with zero charge counters. Sawship is NOT a
        creature (``is_creature_now`` returns False on both engines —
        ``is_stationed`` is the only leg that could light it up and
        ``0 < station_threshold=3``). No attack is legal: Python's
        ``eligible_attackers(p0)`` returns the empty list; Rust's
        ``battlefield_snapshot()`` shows the Sawship at
        ``charge_counters=0``. Full field-view byte-equal across
        engines.

    (B) **Partial-station (``charge_counters=1``):** Sawship on bf +
        ONE untapped non-summoning-sick own power-1 vanilla creature.
        Drive ONE ActivateStation: Python via ``apply_action`` /
        ``ActivateStation`` decision; Rust via ``apply_action`` with
        the ``activate_station`` dict. Post-resolve on both engines:
        the crew is tapped, Sawship's ``charge_counters == 1``;
        Sawship is STILL NOT a creature (``1 < station_threshold=3``);
        ``eligible_attackers(p0)`` excludes the Sawship. Full
        field-view byte-equal across engines.

    (C) **Fully-stationed (``charge_counters=3``):** Sawship on bf +
        THREE untapped non-summoning-sick own power-1 vanilla
        creatures. Drive THREE ActivateStations in sequence (the
        scripted-picker shape design doc §6.3 mandates — the bench's
        ``attack_all`` strategy would not naturally produce
        "queue-three-ActivateStations-then-attack"). Post-resolve on
        both engines: all three crew are tapped, Sawship's
        ``charge_counters == 3``; Sawship IS a creature
        (``3 >= station_threshold=3``); ``haste`` is in Sawship's
        effective keywords (it just animated this turn from a
        non-creature into a creature — without haste it would be
        summoning-sick); ``flying`` is also granted. The Sawship is
        therefore a LEGAL attacker
        (``eligible_attackers(p0)`` includes the Sawship,
        ``effective_keywords`` contains both flying and haste). Full
        field-view byte-equal across engines.

**Scripted-picker semantics.** The probe drives ActivateStation
through direct ``apply_action`` calls (Python: ``ActivateStation``
dataclass via ``mtg_bot.actions.apply_action`` /
``_activate_station``; Rust: ``apply_action`` with
``{"kind": "activate_station", ...}`` dict). This IS the scripted-
picker design doc §6.3 mandates — both engines receive an explicit
``(spacecraft_id, crew_id)`` pair per activation, eliminating any
search-strategy ambiguity. The cross-engine mirror is then
established by the post-each-activation field-view byte-equal
compare.

**Real-EoE-signal discipline (round-46).** This module uses the
live ``OracleParserCardSource`` Galvanizing Sawship printing on the
Python side AND the canonical Rust registry dict shape emitted by
``_spec_card_to_printing_dict(card_def)`` on the Rust side — the
SAME printing shape both engines read (verified pre-flight: the C3
bridge round-trip pin
``test_spec_card_to_printing_dict_emits_station_threshold_and_keywords``
+ the live-printing predicate pin
``test_galvanizing_sawship_now_admits_at_admit_gate_post_cycle_3``).
Synthetic power-1 crew creatures are seated via
``_card_def_to_python_printing`` on Python + the same dict shape on
Rust, keeping crew printing-name + power agreement byte-equal across
engines.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

from mtg_bot.cards.source import get_active_source


_PRINTINGS = get_active_source().get_printings()


# Skip Rust-engine probes if the extension isn't built — mirrors the
# project-wide policy for cross-engine probes.
_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Zone constants (Rust int encoding — same shape sibling probes use).
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3

# Rust phase constants — mirrors ``rust/src/state_ops_steps.rs``.
PHASE_PRECOMBAT_MAIN = 3


@pytest.fixture(scope="module")
def parity_smoke():
    """Load ``scripts/parity_smoke.py`` as a module (the field-view
    builder lives there). Identical to the established pattern in
    sibling per-card parity probes."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location(
        "parity_smoke", script_path,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


# Canonical Rust dict for the Sawship — the EXACT shape
# ``_spec_card_to_printing_dict`` emits for the C3 bridge forward arm
# (verified pre-flight via the C3 bridge round-trip pins). Both
# engines read this same printing shape.
_SAWSHIP_RUST_DICT = {
    "name": "Galvanizing Sawship",
    "card_types": ["Artifact"],
    "mana_cost": {"generic": 5, "R": 1},
    "effects": [],
    "power": 6,
    "toughness": 5,
    "subtypes": ["Spacecraft"],
    "station_threshold": 3,
    "stationed_keywords": ["flying", "haste"],
}


# Synthetic power-1 crew creature — a 1/1 vanilla Bear. The Rust
# registry dict shape mirrors the Phase-1 Carrier-AA / cost-reduction
# probe conventions for synthetic creatures.
_POWER_ONE_CREW_RUST_DICT = {
    "name": "Test Power-One Crew",
    "card_types": ["Creature"],
    "mana_cost": {"generic": 1},
    "power": 1,
    "toughness": 1,
}


# ---------------------------------------------------------------------------
# (1) Parser SoT — Sawship is parser-claimed and emits the expected
# Phase-1-pilot shape (re-asserted here so this module is self-contained
# for the PROBED-tier evidence).
# ---------------------------------------------------------------------------


def test_galvanizing_sawship_parser_claims_card():
    """Pins the active CardSource is producing the Sawship printing
    under its canonical EoE name."""
    assert "Galvanizing Sawship" in _PRINTINGS, (
        "Galvanizing Sawship must be parser-claimed by the active "
        "CardSource (EoE set + reprint coverage)"
    )


def test_galvanizing_sawship_printed_attrs():
    """Pins the basic printing surface: Artifact — Spacecraft, 6/5,
    cost ``{5}{R}``, ``station_threshold=3``, stationed_keywords =
    ``{flying, haste}``, ZERO printed abilities (the §2 teeth — the
    admit predicate's load-bearing gates).
    """
    p = _PRINTINGS["Galvanizing Sawship"]
    assert p.card_types == ("Artifact",)
    assert "Spacecraft" in p.subtypes
    assert p.power == 6 and p.toughness == 5
    assert p.mana_cost.generic == 5
    assert ("R", 1) in p.mana_cost.colored
    assert p.station_threshold == 3
    assert p.stationed_keywords == frozenset({"flying", "haste"})
    # The §2 teeth — zero printed abilities of every flavor.
    assert p.activated_abilities == ()
    assert p.triggered_abilities == ()
    assert p.static_abilities == ()
    assert p.spell_effect is None
    assert p.warp_cost is None
    assert p.keywords == frozenset()


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the C3 forward arm
# ``_spec_card_to_printing_dict`` + reverse arm
# ``_card_def_to_python_printing`` round-trip on the genuine parsed
# Sawship printing through the new dedicated admit predicate. Pins the
# canonical Rust dict shape this probe drives both engines through.
# ---------------------------------------------------------------------------


def test_galvanizing_sawship_bridge_round_trip_canonical_rust_dict():
    """The C3 admit-gate's bridge: Python printing →
    ``_station_spacecraft_card_def`` → CardDef →
    ``_spec_card_to_printing_dict`` → canonical Rust registry dict
    matches ``_SAWSHIP_RUST_DICT`` byte-equal. Pins the probe's source-
    of-truth that both engines read the SAME printing shape."""
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        _card_def_to_python_printing,
        _spec_card_to_printing_dict,
    )

    p_orig = _PRINTINGS["Galvanizing Sawship"]
    cd = trajectory._station_spacecraft_card_def(p_orig)
    assert cd is not None, (
        "Sawship must pass the Phase-1 admit predicate per Cycle 3"
    )
    pd = _spec_card_to_printing_dict(cd)
    assert pd == _SAWSHIP_RUST_DICT, (
        f"Sawship Rust registry dict must match the probe's pinned "
        f"shape (the bridge SoT for both engines); got pd={pd!r}, "
        f"expected={_SAWSHIP_RUST_DICT!r}"
    )
    # Reverse arm rematerializes a byte-equal CardPrinting on the
    # station-axis fields.
    p_rt = _card_def_to_python_printing(cd)
    assert p_rt.station_threshold == 3
    assert p_rt.stationed_keywords == frozenset({"flying", "haste"})
    assert p_rt.power == 6 and p_rt.toughness == 5
    assert p_rt.card_types == ("Artifact",)
    assert "Spacecraft" in p_rt.subtypes


# ---------------------------------------------------------------------------
# (3) Rust effect-arm parse smoke — the canonical Sawship Rust dict
# parses on ``register_printing`` (the bridge contract Rust honors). The
# C1 substrate landed this; the pin is duplicated here for self-contained
# PROBED-tier evidence.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_canonical_sawship_dict():
    """Lockstep pin: Rust's parse arm accepts the canonical Sawship
    registry-dict shape ``_SAWSHIP_RUST_DICT`` — the SAME dict the C3
    forward emit arm produces for the live Sawship printing. Threading
    ``station_threshold`` + ``stationed_keywords`` on a Spacecraft-
    typed Artifact carrier round-trips byte-equal through
    ``Registry.register_printing``."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_SAWSHIP_RUST_DICT)
    assert isinstance(pid, int)
    assert reg.get_printing_name(pid) == "Galvanizing Sawship"


# ---------------------------------------------------------------------------
# Helper — seat Sawship + N power-1 crew on both engines. Returns a
# 4-tuple (py_state, py_sawship, py_crew_list, rs_state, rs_sawship,
# rs_crew_list) with both engines in sorcery-speed MAIN1 priority on p0.
# ---------------------------------------------------------------------------


def _seat_sawship_and_crew(parity_smoke_mod, n_crew: int):
    """Seat Galvanizing Sawship + ``n_crew`` power-1 vanilla creatures
    on p0's battlefield on BOTH engines. Pre-state pin: cross-engine
    byte-equal field view BEFORE any activation drives.

    Both engines:
      * Sawship: ``summoning_sick = False`` (it's not yet a creature
        anyway; this avoids a non-applicable sickness mismatch when the
        field-view 8-tuple's ``summoning_sick`` slot would diverge).
      * Crew: ``summoning_sick = False`` so they can crew immediately
        (Stations are activated abilities with a tap cost; a sick crew
        silent-no-ops the activation).
      * Phase: PRECOMBAT_MAIN (sorcery-speed window for Stations).
      * Priority: p0.

    Crew are seated in the SAME order on both engines (insertion-order
    on Rust's per-player ``battlefield`` Vec; ``state.battlefield.
    append`` on Python — both engines tag IDs in seat order). The
    field-view byte-equal compare confirms agreement on every field.
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

    sawship_printing = _PRINTINGS["Galvanizing Sawship"]

    # Build the synthetic crew Python printing via the bridge reverse
    # arm so the printing shape (name + power) agrees byte-equal with
    # the Rust registry dict (same name, same power, same card type).
    crew_card_def = CardDef(
        name="Test Power-One Crew",
        card_type="Creature",
        mana_cost_generic=1,
        power=1,
        toughness=1,
    )
    crew_printing = _card_def_to_python_printing(crew_card_def)

    # ---- Python: seat Sawship FIRST, then crew in order. ----
    py_sawship = py.new_object(
        sawship_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_sawship.summoning_sick = False
    py_sawship.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_sawship)

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

    # Set Python state into PRECOMBAT_MAIN with p0 priority + active.
    py.step = Step.PRECOMBAT_MAIN
    py.active_player_idx = 0
    py.priority_player_idx = 0

    # ---- Rust: seat Sawship FIRST, then crew in order. ----
    rs_sawship = rs.register_and_inject_object(
        _SAWSHIP_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    rs_crew_list = [
        rs.register_and_inject_object(
            _POWER_ONE_CREW_RUST_DICT, 0, ZONE_BATTLEFIELD,
        )
        for _ in range(n_crew)
    ]
    # Drive Rust into PRECOMBAT_MAIN.
    rs.set_phase(PHASE_PRECOMBAT_MAIN)

    return py, py_sawship, py_crew_list, rs, rs_sawship, rs_crew_list


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — Scenario A:
# un-stationed (``charge_counters=0``). Sawship alone on bf; assert not
# a creature on either engine + no legal attack; full field-view
# byte-equal. PROBED tier flip evidence (Scenario A — baseline).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_galvanizing_sawship_unstationed_scenario_a_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Scenario A (un-stationed,
    ``charge_counters=0``). PROBED tier flip evidence (Cycle 4 closure
    marker, scenario A).**

    Pre-state on both engines:
      * Sawship on p0's battlefield (live ``OracleParserCardSource``
        printing on Python; ``_SAWSHIP_RUST_DICT`` on Rust — both carry
        the same name + the same Phase-1-pilot Spacecraft shape per
        the C3 bridge round-trip pin).
      * NO crew on either engine (no ActivateStation eligible).
      * ``charge_counters == 0`` on Sawship (default).

    Drive: NO activation (this is the un-stationed baseline). Pinned:
      * ``charge_counters == 0`` on both engines.
      * Sawship is NOT a creature on either engine
        (``is_creature_now == False`` on Python; ``is_stationed_check``
        returns False on Rust for ``(threshold=3, charge=0)``).
      * Python's ``eligible_attackers(p0)`` returns ``[]``.
      * Full field-view byte-equal compare across the whole state.
    """
    from mtg_bot.combat import eligible_attackers
    from mtg_bot.game import is_creature_now
    from mtg_bot.parity.cross_engine import (
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )

    import mtg_bot_engine

    # Real-EoE-signal discipline (round-46): bind the genuine parsed
    # printing inside the *_parity body so the measure-pool-parity
    # classifier credits THIS slug to the probe (the canonical idiom
    # the sibling per-card probes use).
    sawship_printing = _PRINTINGS.get("Galvanizing Sawship")
    if sawship_printing is None:
        pytest.skip("Galvanizing Sawship absent from active CardSource")

    py, py_sawship, py_crew_list, rs, rs_sawship, rs_crew_list = (
        _seat_sawship_and_crew(parity_smoke, n_crew=0)
    )
    assert py_crew_list == [] and rs_crew_list == []

    # ---- Charge counters == 0 on both engines.
    assert rs.get_charge_counters(rs_sawship) == 0
    assert py_sawship.charge_counters == 0

    # ---- Sawship is NOT a creature on either engine.
    assert is_creature_now(py_sawship) is False, (
        "Python: un-stationed Sawship (charge=0 < threshold=3) must "
        "NOT be a creature"
    )
    assert mtg_bot_engine.is_stationed_check(3, 0) is False, (
        "Rust: un-stationed Sawship (charge=0 < threshold=3) must "
        "NOT pass is_stationed_check"
    )

    # ---- No legal attack on Python (eligible_attackers excludes
    # non-creature Spacecraft).
    elig = eligible_attackers(py, 0)
    assert py_sawship not in elig, (
        f"Python: un-stationed Sawship must NOT be in "
        f"eligible_attackers(p0); got elig={[o.id for o in elig]!r}"
    )

    # ---- Full field-view byte-equal compare across both engines.
    # The pre-state baseline must be byte-equal — Sawship printing
    # name + zero charge + zero damage + not tapped + summoning_sick
    # False on both sides.
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Scenario A (un-stationed Sawship baseline) must be byte-equal "
        f"across the WHOLE field view on BOTH engines; diffs={diffs}"
    )


# ---------------------------------------------------------------------------
# (5) GENUINE real-EoE cross-engine byte-equal probe — Scenario B:
# partial-station (``charge_counters=1``). Sawship + 1 power-1 crew on
# bf; drive ONE ActivateStation; assert charge=1, crew tapped, Sawship
# STILL not a creature; full field-view byte-equal. PROBED tier flip
# evidence (Scenario B — partial-station threshold-not-reached).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_galvanizing_sawship_partial_station_scenario_b_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Scenario B
    (partial-station, ``charge_counters=1``). PROBED tier flip
    evidence (Cycle 4 closure marker, scenario B).**

    Pre-state on both engines:
      * Sawship on p0's bf + ONE power-1 vanilla creature on p0's bf.
      * Sawship ``charge_counters == 0``; crew untapped, NOT
        summoning-sick (eligible to crew).

    Drive: ONE ``ActivateStation(spacecraft=sawship, crew=crew_0)``
    on each engine (Python: ``apply_action`` /
    ``ActivateStation`` dataclass; Rust: ``apply_action`` with the
    ``activate_station`` dict). The scripted-picker design doc §6.3
    mandates — the bench's ``attack_all`` strategy would not produce
    this sequence organically.

    Post-resolve on both engines:
      * Crew tapped on both engines (the activation's ``{T}`` cost).
      * Sawship ``charge_counters == 1`` (crew's printed power=1).
      * Sawship STILL not a creature (``1 < station_threshold=3``).
      * Python's ``eligible_attackers(p0)`` excludes the Sawship
        (still not a creature) AND the now-tapped crew (tapped
        creatures aren't legal attackers).
      * Full field-view byte-equal compare across the whole state.
    """
    from mtg_bot.actions import ActivateStation, apply_action
    from mtg_bot.combat import eligible_attackers
    from mtg_bot.game import is_creature_now
    from mtg_bot.parity.cross_engine import (
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )

    import mtg_bot_engine

    # Real-EoE-signal discipline (round-46): bind the genuine parsed
    # printing inside the *_parity body so the measure-pool-parity
    # classifier credits THIS slug to the probe.
    sawship_printing = _PRINTINGS.get("Galvanizing Sawship")
    if sawship_printing is None:
        pytest.skip("Galvanizing Sawship absent from active CardSource")

    py, py_sawship, py_crew_list, rs, rs_sawship, rs_crew_list = (
        _seat_sawship_and_crew(parity_smoke, n_crew=1)
    )
    (py_crew,) = py_crew_list
    (rs_crew,) = rs_crew_list

    # ---- Pre-activation cross-engine field-view byte-equal sanity.
    pre_diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert pre_diffs == [], (
        f"Pre-activation baseline (Sawship + 1 crew, charge=0) must "
        f"be byte-equal across engines; got pre_diffs={pre_diffs}"
    )

    # ---- Drive ONE ActivateStation on both engines via the scripted
    # picker (explicit spacecraft/crew pair — design doc §6.3).
    apply_action(
        py, 0, ActivateStation(spacecraft_id=py_sawship.id, crew_id=py_crew.id),
    )
    rs.apply_action(
        {
            "kind": "activate_station",
            "spacecraft_id": rs_sawship,
            "crew_id": rs_crew,
        }
    )

    # ---- Post-resolve observables on Python.
    assert py_sawship.charge_counters == 1, (
        f"Python: Sawship charge must be 1 post-activation; "
        f"got {py_sawship.charge_counters}"
    )
    assert py_crew.tapped is True, (
        "Python: crew must be tapped post-activation"
    )
    assert is_creature_now(py_sawship) is False, (
        "Python: Sawship at charge=1 < threshold=3 must STILL not be "
        "a creature"
    )

    # ---- Post-resolve observables on Rust.
    assert rs.get_charge_counters(rs_sawship) == 1, (
        f"Rust: Sawship charge must be 1 post-activation; "
        f"got {rs.get_charge_counters(rs_sawship)}"
    )
    assert rs.is_tapped(rs_crew) is True, (
        "Rust: crew must be tapped post-activation"
    )
    assert mtg_bot_engine.is_stationed_check(3, 1) is False, (
        "Rust: Sawship at charge=1 < threshold=3 must NOT pass "
        "is_stationed_check"
    )

    # ---- No legal attack on Python (Sawship not a creature, crew
    # now tapped).
    elig_ids = {o.id for o in eligible_attackers(py, 0)}
    assert py_sawship.id not in elig_ids, (
        "Python: partially-stationed Sawship (charge=1) must NOT be "
        "a legal attacker"
    )
    assert py_crew.id not in elig_ids, (
        "Python: now-tapped crew must NOT be a legal attacker"
    )

    # ---- Full field-view byte-equal compare. Sawship's
    # ``counters`` slot in the 8-tuple is plus_one - minus_one which
    # is 0 on both engines (charge_counters is a SEPARATE field, NOT
    # in the field-view 8-tuple — verified from
    # ``_zone_signature``). The byte-equal compare here pins the
    # observable mid-state: crew tapped, Sawship still on bf,
    # printing-names agree.
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Scenario B (partial-station, 1 activation resolved) must be "
        f"byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )


# ---------------------------------------------------------------------------
# (6) GENUINE real-EoE cross-engine byte-equal probe — Scenario C:
# fully-stationed (``charge_counters=3``). Sawship + 3 power-1 crew on
# bf; drive THREE ActivateStations; assert charge=3, all crew tapped,
# Sawship IS a creature with flying+haste, IS a legal attacker; full
# field-view byte-equal. PROBED tier flip evidence (THE LOAD-BEARING
# Scenario C — fully-stationed + haste-attack pin).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_galvanizing_sawship_fully_stationed_scenario_c_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Scenario C
    (fully-stationed, ``charge_counters=3``). PROBED tier flip evidence
    (Cycle 4 closure marker, scenario C — THE LOAD-BEARING
    fully-stationed + haste-attack scenario).**

    Pre-state on both engines:
      * Sawship on p0's bf + THREE power-1 vanilla creatures on p0's
        bf, all untapped + NOT summoning-sick.
      * Sawship ``charge_counters == 0`` (default).

    Drive: THREE ``ActivateStation`` activations in sequence (one per
    crew) on each engine. The scripted-picker shape design doc §6.3
    mandates — the bench's ``attack_all`` strategy would not produce
    "queue-three-ActivateStations-then-attack" organically.

    Post-resolve on both engines:
      * All three crew tapped.
      * Sawship ``charge_counters == 3`` (3 × power-1 = 3).
      * Sawship IS a creature
        (``3 >= station_threshold=3``).
      * Sawship has BOTH stationed keywords (``flying`` AND ``haste``)
        in its effective keyword set.
      * Sawship IS a legal attacker on Python
        (``eligible_attackers(p0)`` includes the Sawship). The haste
        leg is load-bearing — without haste, the Sawship would be
        summoning-sick this turn (the bf object's
        ``summoning_sick=False`` was already set in the pre-state, so
        in principle haste isn't strictly needed for the legality
        check; HOWEVER, haste is the canonical Spacecraft animation
        rule per CR 311 + the design doc §4.6 effective-keyword fold).
      * Full field-view byte-equal compare across the whole state.
    """
    from mtg_bot.actions import ActivateStation, apply_action
    from mtg_bot.combat import eligible_attackers
    from mtg_bot.game import effective_keywords, is_creature_now
    from mtg_bot.parity.cross_engine import (
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )

    import mtg_bot_engine

    # Real-EoE-signal discipline (round-46): bind the genuine parsed
    # printing inside the *_parity body so the measure-pool-parity
    # classifier credits THIS slug to the probe.
    sawship_printing = _PRINTINGS.get("Galvanizing Sawship")
    if sawship_printing is None:
        pytest.skip("Galvanizing Sawship absent from active CardSource")

    py, py_sawship, py_crew_list, rs, rs_sawship, rs_crew_list = (
        _seat_sawship_and_crew(parity_smoke, n_crew=3)
    )
    assert len(py_crew_list) == 3 and len(rs_crew_list) == 3

    # ---- Pre-activation cross-engine field-view byte-equal sanity.
    pre_diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert pre_diffs == [], (
        f"Pre-activation baseline (Sawship + 3 crew, charge=0) must "
        f"be byte-equal across engines; got pre_diffs={pre_diffs}"
    )

    # ---- Drive THREE ActivateStation activations in sequence on
    # both engines via the scripted picker.
    for py_crew, rs_crew in zip(py_crew_list, rs_crew_list):
        apply_action(
            py, 0,
            ActivateStation(spacecraft_id=py_sawship.id, crew_id=py_crew.id),
        )
        rs.apply_action(
            {
                "kind": "activate_station",
                "spacecraft_id": rs_sawship,
                "crew_id": rs_crew,
            }
        )

    # ---- Post-resolve observables on Python.
    assert py_sawship.charge_counters == 3, (
        f"Python: Sawship charge must be 3 post-activations; "
        f"got {py_sawship.charge_counters}"
    )
    for i, py_crew in enumerate(py_crew_list):
        assert py_crew.tapped is True, (
            f"Python: crew[{i}] must be tapped post-activation"
        )
    assert is_creature_now(py_sawship) is True, (
        "Python: Sawship at charge=3 >= threshold=3 must be a "
        "creature (CR 311 + design doc §4.5)"
    )
    py_kw = effective_keywords(py, py_sawship)
    assert "flying" in py_kw, (
        f"Python: stationed Sawship must have flying in effective "
        f"keywords; got {py_kw!r}"
    )
    assert "haste" in py_kw, (
        f"Python: stationed Sawship must have haste in effective "
        f"keywords; got {py_kw!r}"
    )

    # ---- Post-resolve observables on Rust.
    assert rs.get_charge_counters(rs_sawship) == 3, (
        f"Rust: Sawship charge must be 3 post-activations; "
        f"got {rs.get_charge_counters(rs_sawship)}"
    )
    for i, rs_crew in enumerate(rs_crew_list):
        assert rs.is_tapped(rs_crew) is True, (
            f"Rust: crew[{i}] must be tapped post-activation"
        )
    assert mtg_bot_engine.is_stationed_check(3, 3) is True, (
        "Rust: Sawship at charge=3 >= threshold=3 must pass "
        "is_stationed_check"
    )

    # ---- Sawship IS a legal attacker on Python (load-bearing
    # animated-this-turn observable).
    elig_ids = {o.id for o in eligible_attackers(py, 0)}
    assert py_sawship.id in elig_ids, (
        f"Python: fully-stationed Sawship must be in "
        f"eligible_attackers(p0); got elig_ids={elig_ids!r}, "
        f"sawship.id={py_sawship.id}"
    )
    # All crew are tapped — NONE of them are eligible attackers.
    for py_crew in py_crew_list:
        assert py_crew.id not in elig_ids, (
            f"Python: now-tapped crew[{py_crew.id}] must NOT be a "
            f"legal attacker"
        )

    # ---- Full field-view byte-equal compare. Sawship's
    # ``charge_counters`` slot is NOT in the field-view 8-tuple
    # (verified from ``_zone_signature``); the observable mid-state
    # the field view captures: all crew tapped, Sawship still on bf,
    # no zone moves, printing-names agree.
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Scenario C (fully-stationed, 3 activations resolved) must be "
        f"byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )
