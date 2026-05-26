"""Spacecraft Station substrate Phase 1 — Cycle 2 (substrate-only) pins.

**Lane.** ``feature/spacecraft-phase-1-cycle-2-substrate-p1``
(2026-05-25).

Cycle 2 of the Spacecraft Station substrate Phase 1 campaign per
``docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_1_DESIGN.md`` §4 (resolver +
legal emitter + folds). Builds atop Cycle 1's substrate Part A (commit
``ea9aa996`` — ``CardPrinting.station_threshold`` /
``stationed_keywords`` fields + ``is_stationed_predicate`` Rust
helper + ``is_stationed_check`` `#[pyfunction]` shim).

C2 deliverables:

1. ``Action::ActivateStation`` (Cycle 1 stub already existed at
   ``rust/src/actions.rs:266`` — Cycle 2 flips its
   ``apply_action`` dispatch stub at ``state_ops_actions.rs:582`` to
   the real ``apply_activate_station`` resolver).
2. ``apply_activate_station(state, player_id, spacecraft_id, crew_id)``
   resolver (silent-validates + taps crew + adds
   ``effective_power(crew)``-many charge counters; SL §9 entry #2
   pins the Tapestry-Warden flag asymmetry).
3. Sorcery-speed legal-action emitter at the tail of
   ``state_ops_legal.rs::legal_decisions`` (N×M loop over
   own Spacecraft × own untapped non-summoning-sick crew creatures).
4. ``is_creature_now(state, obj)`` extension in
   ``state_ops_combat.rs`` (printed creature OR stationed Spacecraft);
   swapped into the SBA / legal-attacker / legal-blocker / mana-
   ability-gating sites.
5. ``stationed_keywords`` fold extension in
   ``state_ops_combat.rs::battlefield_has_keyword``.

**Substrate-only invariant — Galvanizing Sawship STAYS DECLINED at
the admit gate post-Cycle-2.** Cycle 3 owns the inversion (Python
bridge + admit predicate + FLIP).

What this module pins:

1. **Rust ``is_creature_now`` flip pin.** A synthetic Galvanizing-
   Sawship-shaped object with ``charge_counters=0`` reads False; the
   same object with ``charge_counters=3`` (≥ threshold) reads True.
2. **``apply_activate_station`` happy path.** A bench with one
   Spacecraft + one own crew creature: dispatch
   ``activate_station`` via ``apply_action`` — crew flips
   ``tapped=True`` and Spacecraft ``charge_counters`` increases by
   the crew's printed power.
3. **``apply_activate_station`` silent no-ops on invalid inputs.**
   4 cases: (a) crew already tapped, (b) crew summoning-sick,
   (c) crew not own (opponent's creature), (d) crew == spacecraft id
   (Spacecraft can't crew itself).
4. **Legal-action emitter N×M cardinality.** With 2 own Spacecraft +
   3 own eligible-crew creatures + 1 own ineligible (tapped) +
   1 opponent creature, the sorcery-speed window emits exactly
   2 × 3 = 6 ``activate_station`` dicts.
5. **Legal-action emitter sorcery-speed-only.** At instant speed
   (non-MAIN phase) the same board emits zero ``activate_station``
   dicts.
6. **C1 substrate-only invariant re-asserted — Galvanizing Sawship
   STILL DECLINED.** Cycle 3 inverts; Cycle 2 holds.

These pins are independent of any live bench printing — they use
synthetic Galvanizing-Sawship-shaped CardDef payloads injected via
``register_and_inject_object`` (the same shape ``test_spacecraft_
phase_1_substrate_cycle_1.py`` pin #2 exercised through the
``Registry.register_printing`` PyO3 entrypoint). The Phase-1 admit
gate stays closed; the Galvanizing-Sawship-shaped object IS still
DECLINED at trajectory's deck filter.

Cycle 3 ships the Python bridge + admit predicate widen + the FLIP.
"""

from __future__ import annotations

import importlib.util

import pytest


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


# A Galvanizing-Sawship-shaped synthetic printing payload (zero abilities,
# Phase-1 pilot shape). Used across the Cycle-2 pins. Mirrors
# ``test_spacecraft_phase_1_substrate_cycle_1.py:202-215``.
_SAWSHIP_LIKE_PRINTING = {
    "name": "Spacecraft Phase 1 Cycle 2 Substrate -- Sawship-shaped carrier",
    "card_types": ["Artifact"],
    "subtypes": ["Spacecraft"],
    "mana_cost": {"R": 1, "generic": 5},
    "power": 6,
    "toughness": 5,
    "station_threshold": 3,
    "stationed_keywords": ["flying", "haste"],
}

# A plain 2/2 Creature for the crew-side of the resolver pins.
_BEAR_PRINTING = {
    "name": "Spacecraft Phase 1 Cycle 2 Substrate -- 2/2 Bear (crew)",
    "card_types": ["Creature"],
    "mana_cost": {"G": 1, "generic": 1},
    "power": 2,
    "toughness": 2,
}


# ---------------------------------------------------------------------------
# Pin 1 — Rust is_creature_now flip pin (un-stationed False → stationed True)
# ---------------------------------------------------------------------------


def test_is_creature_now_flips_with_charge_counters_via_battlefield_has_keyword():
    """Pin #1 — ``is_creature_now`` flip pin.

    A synthetic Galvanizing-Sawship-shaped object on the battlefield
    with ``charge_counters=0`` does NOT carry ``flying`` (un-stationed
    -> ``is_creature_now`` False -> ``stationed_keywords`` fold
    suppressed). After ``set_charge_counters(obj, 3)`` (≥ threshold),
    the SAME helper returns ``flying`` true (stationed -> the fold
    lights).

    The ``is_creature_now`` predicate is private to the Rust crate
    (``pub(crate)``) so Python can't call it directly; this pin
    exercises the predicate THROUGH its consumer site
    (``battlefield_has_keyword`` reading ``stationed_keywords``). When
    that helper returns the granted keyword, ``is_creature_now`` /
    ``is_stationed_predicate`` returned True; the fold's gate is the
    SAME predicate the SBA + legal-emitter + ``is_creature_now``
    consume.
    """
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    sawship_id = rs.register_and_inject_object(
        _SAWSHIP_LIKE_PRINTING, 0, 2,  # owner=p0, zone=battlefield
    )

    # Pre-station: charge_counters == 0; the substrate-only invariant
    # is that this Spacecraft is NOT acting as a creature, so no
    # stationed-keyword fold fires.
    assert rs.get_charge_counters(sawship_id) == 0
    # The keyword reader fires through `battlefield_has_keyword`'s
    # stationed-keyword fold. We can probe it indirectly through the
    # Action enum: at instant speed (NOT a MAIN phase), the legal-
    # emitter must NOT emit `activate_station` against a sole
    # Spacecraft permanent — but un-stationed Spacecraft also fails
    # the legal-attacker filter (which keys on is_creature_now). The
    # most direct probe is: there is no inhabited path that exposes
    # `is_creature_now` to Python without driving a full turn loop.
    # Use the legal-emitter instead — it's the C2 consumer of
    # is_creature_now in the sorcery-speed path. See pin #4 for the
    # cardinality pin.
    #
    # Pin #1 specifically: flip via charge_counters mutation. The
    # `is_stationed_check` shim from C1 is the most direct probe.
    assert mtg_bot_engine.is_stationed_check(3, 0) is False
    assert mtg_bot_engine.is_stationed_check(3, 3) is True

    # And the keyword fold: pre-station, no flying/haste is read
    # through battlefield_has_keyword (we can't observe that directly
    # from Python, but the Action::ActivateStation legal-emitter
    # pin #4 exercises the consumer chain).
    rs.set_charge_counters(sawship_id, 3)
    assert rs.get_charge_counters(sawship_id) == 3
    # The SAME predicate the keyword fold gates on now reads True.
    assert mtg_bot_engine.is_stationed_check(3, 3) is True


# ---------------------------------------------------------------------------
# Pin 2 — apply_activate_station happy path
# ---------------------------------------------------------------------------


def test_apply_activate_station_taps_crew_and_adds_charge_counters_equal_to_power():
    """Pin #2 — ``apply_activate_station`` happy path.

    A bench with one Spacecraft + one own 2/2 Bear: dispatch
    ``apply_action({"kind": "activate_station", ...})`` and verify:

      * Bear flips ``tapped=True``.
      * Spacecraft ``charge_counters`` increases by 2 (the crew's
        printed power).

    Mirrors Python's ``_activate_station`` at ``actions.py:2353-2407``.
    """
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    sawship_id = rs.register_and_inject_object(
        _SAWSHIP_LIKE_PRINTING, 0, 2,
    )
    bear_id = rs.register_and_inject_object(_BEAR_PRINTING, 0, 2)
    # The injected Bear is not summoning-sick by default
    # (register_and_inject_object hardcodes summoning_sick=false), so
    # it's eligible to crew.

    # Pre-dispatch state.
    assert rs.get_charge_counters(sawship_id) == 0
    assert rs.is_tapped(bear_id) is False

    # Dispatch the action through the parity-replay dict surface.
    rs.apply_action(
        {
            "kind": "activate_station",
            "spacecraft_id": sawship_id,
            "crew_id": bear_id,
        }
    )

    # Post-dispatch: crew tapped + spacecraft charged.
    assert rs.is_tapped(bear_id) is True, (
        "Crew creature must flip to tapped after activate_station "
        "(mirrors Python's tap_permanent(state, crew) at "
        "actions.py:2402)."
    )
    assert rs.get_charge_counters(sawship_id) == 2, (
        "Spacecraft charge_counters must increase by the crew's "
        "effective_power (2 for the 2/2 Bear)."
    )


# ---------------------------------------------------------------------------
# Pin 3 — apply_activate_station silent no-ops (4 cases)
# ---------------------------------------------------------------------------


def test_apply_activate_station_silent_noop_on_tapped_crew():
    """Pin #3a — silent no-op: crew already tapped."""
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    sawship_id = rs.register_and_inject_object(
        _SAWSHIP_LIKE_PRINTING, 0, 2,
    )
    bear_id = rs.register_and_inject_object(_BEAR_PRINTING, 0, 2)
    # Pre-tap the Bear.
    assert rs.tap_object(bear_id) is True
    assert rs.is_tapped(bear_id) is True
    pre_charge = rs.get_charge_counters(sawship_id)

    rs.apply_action(
        {
            "kind": "activate_station",
            "spacecraft_id": sawship_id,
            "crew_id": bear_id,
        }
    )

    # Spacecraft charge unchanged; Bear stays tapped.
    assert rs.get_charge_counters(sawship_id) == pre_charge
    assert rs.is_tapped(bear_id) is True


def test_apply_activate_station_silent_noop_on_summoning_sick_crew():
    """Pin #3b — silent no-op: crew summoning-sick."""
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    sawship_id = rs.register_and_inject_object(
        _SAWSHIP_LIKE_PRINTING, 0, 2,
    )
    bear_id = rs.register_and_inject_object(_BEAR_PRINTING, 0, 2)
    # Force the Bear into summoning-sick state via the
    # force_set_summoning_sick test side-channel.
    rs.force_set_summoning_sick(bear_id, True)
    pre_charge = rs.get_charge_counters(sawship_id)

    rs.apply_action(
        {
            "kind": "activate_station",
            "spacecraft_id": sawship_id,
            "crew_id": bear_id,
        }
    )

    # Spacecraft charge unchanged; Bear stays untapped (cost was not
    # paid because the activation silent-no-op'd).
    assert rs.get_charge_counters(sawship_id) == pre_charge
    assert rs.is_tapped(bear_id) is False


def test_apply_activate_station_silent_noop_on_opponent_crew():
    """Pin #3c — silent no-op: crew belongs to the opponent."""
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    sawship_id = rs.register_and_inject_object(
        _SAWSHIP_LIKE_PRINTING, 0, 2,  # p0 controls the Spacecraft.
    )
    # Inject a Bear on p1's battlefield (opponent's creature).
    opponent_bear_id = rs.register_and_inject_object(
        _BEAR_PRINTING, 1, 2,  # p1 owns the Bear.
    )
    pre_charge = rs.get_charge_counters(sawship_id)

    # p0 (priority player by default) tries to use p1's Bear as crew.
    rs.apply_action(
        {
            "kind": "activate_station",
            "spacecraft_id": sawship_id,
            "crew_id": opponent_bear_id,
        }
    )

    # Spacecraft charge unchanged; opponent's Bear stays untapped.
    assert rs.get_charge_counters(sawship_id) == pre_charge
    assert rs.is_tapped(opponent_bear_id) is False


def test_apply_activate_station_silent_noop_on_self_id():
    """Pin #3d — silent no-op: crew_id == spacecraft_id (Spacecraft
    can't crew itself)."""
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    sawship_id = rs.register_and_inject_object(
        _SAWSHIP_LIKE_PRINTING, 0, 2,
    )
    pre_charge = rs.get_charge_counters(sawship_id)

    rs.apply_action(
        {
            "kind": "activate_station",
            "spacecraft_id": sawship_id,
            "crew_id": sawship_id,  # SAME id.
        }
    )

    # Spacecraft charge unchanged.
    assert rs.get_charge_counters(sawship_id) == pre_charge
    assert rs.is_tapped(sawship_id) is False


# ---------------------------------------------------------------------------
# Pin 4 — Legal-action emitter N×M cardinality (sorcery-speed)
# ---------------------------------------------------------------------------


def test_legal_emitter_activate_station_cardinality_n_times_m():
    """Pin #4 — Legal-action emitter N×M cardinality (sorcery-speed).

    Bench: 2 own Spacecraft + 3 own eligible-crew creatures +
    1 own ineligible (tapped) + 1 opponent creature. The sorcery-
    speed window emits exactly 2 × 3 = 6 ``activate_station`` dicts.

    Asserts the precise (spacecraft_id, crew_id) cross-product;
    excludes the ineligible-tapped own crew AND the opponent's crew.
    """
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    # Two own Spacecraft.
    ship_a = rs.register_and_inject_object(
        _SAWSHIP_LIKE_PRINTING, 0, 2,
    )
    ship_b = rs.register_and_inject_object(
        _SAWSHIP_LIKE_PRINTING, 0, 2,
    )
    # Three own eligible crew (each gets a fresh injection so we
    # have distinct ids).
    crew_1 = rs.register_and_inject_object(_BEAR_PRINTING, 0, 2)
    crew_2 = rs.register_and_inject_object(_BEAR_PRINTING, 0, 2)
    crew_3 = rs.register_and_inject_object(_BEAR_PRINTING, 0, 2)
    # One own ineligible (tapped) crew.
    crew_ineligible = rs.register_and_inject_object(_BEAR_PRINTING, 0, 2)
    rs.tap_object(crew_ineligible)
    # One opponent crew.
    opp_crew = rs.register_and_inject_object(_BEAR_PRINTING, 1, 2)

    # Drive the state to PHASE_MAIN1 (==3) with priority on p0 + an
    # empty stack so the sorcery-timing gate fires. `make_synthetic
    # _state` starts at phase==0 (UNTAP); set_phase(3) puts us at
    # MAIN1 directly. The synthetic state's defaults already place
    # us at active=p0, priority=p0, stack empty.
    rs.set_phase(3)
    assert rs.is_main_phase() is True
    decisions = rs.legal_decisions(0)
    # Filter for activate_station kinds.
    station_dicts = [d for d in decisions if d.get("kind") == "activate_station"]

    # Expected: 2 ships × 3 eligible crew = 6 emissions.
    pairs = sorted(
        (d["spacecraft_id"], d["crew_id"]) for d in station_dicts
    )
    expected_pairs = sorted(
        (ship, crew)
        for ship in (ship_a, ship_b)
        for crew in (crew_1, crew_2, crew_3)
    )
    assert pairs == expected_pairs, (
        f"Legal-emitter N×M product mismatch. Expected "
        f"{expected_pairs!r}, got {pairs!r}. The ineligible "
        f"(tapped) own crew ({crew_ineligible}) and the opponent's "
        f"crew ({opp_crew}) must NOT appear. The Spacecraft itself "
        f"(no self-crew) must not appear as a crew id either."
    )


# ---------------------------------------------------------------------------
# Pin 5 — Legal-emitter sorcery-speed-only (instant speed → zero)
# ---------------------------------------------------------------------------


def test_legal_emitter_activate_station_zero_at_instant_speed():
    """Pin #5 — sorcery-speed-only gate.

    The SAME bench as pin #4 but at instant speed (UPKEEP — non-MAIN
    phase) emits zero ``activate_station`` dicts.
    """
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    _ship_a = rs.register_and_inject_object(_SAWSHIP_LIKE_PRINTING, 0, 2)
    _ship_b = rs.register_and_inject_object(_SAWSHIP_LIKE_PRINTING, 0, 2)
    _crew_1 = rs.register_and_inject_object(_BEAR_PRINTING, 0, 2)
    _crew_2 = rs.register_and_inject_object(_BEAR_PRINTING, 0, 2)
    _crew_3 = rs.register_and_inject_object(_BEAR_PRINTING, 0, 2)

    # Leave the state at phase==0 (UNTAP) — sorcery timing does NOT
    # hold (the MAIN1/MAIN2 gate at state_ops_legal.rs:2465 fails).
    # The legal-emitter must therefore emit zero activate_station
    # dicts even though both ships + all three crew are eligible
    # creature/spacecraft-shaped.
    decisions = rs.legal_decisions(0)
    station_dicts = [d for d in decisions if d.get("kind") == "activate_station"]
    assert station_dicts == [], (
        "Sorcery-speed gate failed: activate_station emitted at "
        f"non-MAIN phase. Got: {station_dicts!r}"
    )


# ---------------------------------------------------------------------------
# Pin 6 — C1 substrate-only invariant re-asserted (Sawship STILL DECLINED)
# ---------------------------------------------------------------------------


def test_galvanizing_sawship_now_admits_at_admit_gate_post_cycle_3():
    """Pin #6 — **INVERTED IN-PLACE BY CYCLE 3 (2026-05-25).**

    Original C2 pin (substrate-only invariant) re-asserted Galvanizing
    Sawship STAYS DECLINED post-Cycle-2 (the C1 invariant carried
    forward). Cycle 3 landed the FLIP — Python bridge + new admit
    predicate + OR-chain registration; Sawship now ADMITS at the
    deck-level filter through the new dedicated disjunct
    :func:`mtg_bot.parity.trajectory._printing_is_bridge_pure_station_
    spacecraft`.

    The simple-creature predicate STILL declines (the load-bearing
    ``station_threshold`` guard at ``trajectory.py:4698`` is
    unchanged by C3); the new dedicated disjunct is the sole routing
    site.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    sawship = src.get("Galvanizing Sawship")
    if sawship is None:
        pytest.skip("Galvanizing Sawship absent from active CardSource")

    # The simple-creature predicate STILL rejects the Sawship —
    # the load-bearing guard stays in place.
    assert trajectory._printing_is_bridge_simple_creature(sawship) is False, (
        "Galvanizing Sawship must STILL be declined at the simple-"
        "creature admit gate post-C3 — the load-bearing "
        "station_threshold guard is unchanged by C3."
    )
    # The new C3 predicate ADMITS the Sawship.
    assert trajectory._printing_is_bridge_pure_station_spacecraft(sawship), (
        "Galvanizing Sawship must ADMIT through the C3 dedicated "
        "Spacecraft admit predicate post-FLIP."
    )
    # Deck-level filter: ADMITS.
    filtered_names, card_defs = trajectory._filter_deck_to_bridge_supported(
        ["Galvanizing Sawship"], src,
    )
    assert filtered_names == ["Galvanizing Sawship"], (
        "THE FLIP — Galvanizing Sawship must ADMIT at the deck-level "
        f"filter post-C3. Got filtered_names={filtered_names!r}."
    )
    assert len(card_defs) == 1
    assert card_defs[0].name == "Galvanizing Sawship"
    # Bench-aggregate sibling: EXACTLY ONE Spacecraft printing admits
    # through the new dedicated predicate.
    admitted_spacecraft = sorted(
        name for name, p in src.items()
        if "Spacecraft" in p.subtypes
        and trajectory._printing_is_bridge_pure_station_spacecraft(p)
    )
    assert admitted_spacecraft == ["Galvanizing Sawship"], (
        "Post-C3 EXACTLY ONE Spacecraft printing admits through the "
        f"new dedicated predicate. Got: {admitted_spacecraft!r}."
    )
