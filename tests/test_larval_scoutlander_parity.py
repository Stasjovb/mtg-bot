"""Larval Scoutlander — per-card real-EoE cross-engine byte-equal
probe (``covered_by_construction`` → PROBED tier flip; Spacecraft
Station substrate Phase 3A Cycle 2 closure marker for Scenarios A+B
per design doc §6.2).

Larval Scoutlander is a ``{2}{G}`` Artifact — Spacecraft in the EoE
pool carrying the Phase-3A-pilot single-trigger ETB shape:

    Power/Toughness: 3/3
    Station threshold: 7
    Stationed keywords: flying
    Triggered abilities: ONE ETB trigger —
        event = Event.ENTERS
        predicate = IsSelf(subject=None)
        effect = OptionalSacLandOrLanderForBasicLandRamp(
            land_count=2,
        )
        tier_threshold = 0 (always-fire)
        once_per_turn = False

It is the SOLE Spacecraft printing admitted by the Phase-3A strict
1-class / 1-shape gate per design doc §5.4: the other 4 deferred
Phase-3 Spacecraft each fail at least one clause (Sledge-Class
Seedship has ATTACKS event; Synthesizer Labship has
BEGINNING_OF_COMBAT + Controlled(YOU) predicate; Entropic
Battlecruiser has different effect classes; Infinite Guideline
Station has a non-allowlisted CreateTokenPerMulticoloredPermanent
effect). The strict admit predicate
:func:`mtg_bot.parity.trajectory._printing_is_bridge_phase_3_trigger_
spacecraft` positively rejects every non-Phase-3A carrier (the §6.4
decline-set bench check pins this exhaustively in
``test_spacecraft_phase_3a_cycle_2_flip.py``).

**Multi-cycle DECLINED → ADMITTED → PROBED transition.**

  * **Phase 3A Cycle 1 (Rust substrate landing, commit ``83d775cf``,
    2026-05-25).** Rust substrate: new
    ``Effect::OptionalSacLandOrLanderForBasicLandRamp`` variant on
    ``cards.rs::Effect`` + parse / to_pydict / resolve arms +
    cross-engine bridge dict-to-Python arm in ``cross_engine.py`` +
    reverse-serializer leaf in ``trajectory.py:4510``. Larval
    Scoutlander STAYED DECLINED at every admit gate
    (substrate-only invariant).
  * **Phase 3A Cycle 2 (THE FLIP, this slice, 2026-05-25).** New
    Python admit predicate
    :func:`_printing_is_bridge_phase_3_trigger_spacecraft` (sibling
    of Phase-1 / Phase-2 admit predicates) +
    :func:`_phase_3_trigger_spacecraft_card_def` builder + OR-chain
    disjunct registration in :func:`_filter_deck_to_bridge_supported`.
    Larval Scoutlander DECLINED → ADMITTED (admit set 41 → 42; the
    THIRD Spacecraft admit after Sawship + Lumen-Class Frigate).
  * **Phase 3A Cycle 2 (THIS LANE; THE PROBE — Scenarios A+B).**
    Per-card real-EoE cross-engine byte-equality probe driving BOTH
    engines through TWO scenarios across the eligible-target axis per
    design doc §6.2 #9:

    (A) **Empty battlefield, no Lands or Landers (silent no-op
        decline path):** Larval Scoutlander cast (synthetic seat
        on bf via ``put_into_battlefield`` Python /
        ``register_and_inject_object`` Rust to fire the ETB) into a
        bf with NO Lands and NO Lander tokens; assert the ETB
        trigger queues + resolves; the optional-sac arm finds no
        eligible target on either engine and silent-no-ops; no
        basic Lands are fetched; full field-view byte-equal across
        engines (only Larval Scoutlander itself on each bf).

    (B) **Bf has 1 Forest + 1 Lander (optional-accept path):**
        Larval Scoutlander cast onto a bf carrying 1 Forest + 1
        Lander token; assert the ETB trigger queues + resolves
        through the optional-accept-then-sacrifice path; the
        controller's :class:`_PayOptionalSacFirstAgent` shim makes
        Python take Rust's deterministic single-branch (yes +
        first eligible). The target fan-out is the 2-element
        eligible set (Forest + Lander); first-pick = Forest
        (insertion order on both engines). Post-resolve: Forest
        sacrificed; 2 basic Plains entered tapped from library;
        full field-view byte-equal across engines.

**Scripted-picker semantics.** The probe uses
:class:`_PayOptionalSacFirstAgent` to make Python take Rust's
deterministic resolve branch (yes + first eligible sacrifice
target). This IS the optional-cost-mirror shim canon established
in ``tests/parity/_picker_shims.py:367-471`` —
``OptionalSacLandOrLanderForBasicLandRamp`` is a sibling shape of
``OptionalSacArtifactForEffect`` on the optional-sac wrapper axis,
and the same mirror principle applies (Rust auto-says-yes-and-picks-
first; Python's agent surface is steered onto that lone branch). On
the search-fan-out axis the post-resolve fold takes the FIRST
eligible target (controller's bf-iter-first Land-or-Lander pick) —
sibling pattern to the Carrier-AA Phase 1.5a Swarmyard probe.

**Real-EoE-signal discipline (round-46).** This module uses the live
``OracleParserCardSource`` Larval Scoutlander printing on the Python
side AND the canonical Rust registry dict shape emitted by the C2
bridge forward arm
``_spec_card_to_printing_dict(_phase_3_trigger_spacecraft_card_def(
p))`` on the Rust side — the SAME printing shape both engines read
(verified pre-flight via the C2 substrate flip pins
``test_larval_scoutlander_now_admits_at_admit_gate_post_cycle_2``
and ``test_loader_filter_admits_larval_scoutlander_post_cycle_2``).
Forest + Plains use the canonical EoE basic-land printings.

This module is the Spacecraft Phase 3A closure marker; the full
Phase-3A admit set is exhaustively pinned at exactly Larval
Scoutlander post-Cycle-2.
"""

from __future__ import annotations

import importlib.util

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


# Canonical Rust dict for Larval Scoutlander — the EXACT shape
# ``_spec_card_to_printing_dict`` emits via the C2 forward arm
# ``_phase_3_trigger_spacecraft_card_def``. Both engines read this
# same printing shape (verified pre-flight via the C2 admit + builder
# pins in test_spacecraft_phase_3a_cycle_2_flip.py).
_LARVAL_SCOUTLANDER_RUST_DICT = {
    "name": "Larval Scoutlander",
    "card_types": ["Artifact"],
    "mana_cost": {"generic": 2, "G": 1},
    "effects": [],
    "power": 3,
    "toughness": 3,
    "subtypes": ["Spacecraft"],
    "station_threshold": 7,
    "stationed_keywords": ["flying"],
    "triggered_abilities": [
        {
            "event": "enters",
            "predicate": {"kind": "source_is_self"},
            "effect": {
                "kind": "optional_sac_land_or_lander_for_basic_land_ramp",
                "land_count": 2,
            },
        },
    ],
}


# Canonical basic land Rust dicts (Plains as the library-search target;
# Forest as the sacrifice target). Both basics are admitted by the
# Phase-1 ``_printing_is_bridge_basic_land`` predicate, but the probe
# seats them via the same ``register_and_inject_object`` shim used by
# every cross-engine probe.
_FOREST_RUST_DICT = {
    "name": "Forest",
    "card_types": ["Land"],
    "supertypes": ["Basic"],
    "subtypes": ["Forest"],
    "mana_cost": {},
    "effects": [],
}
_PLAINS_RUST_DICT = {
    "name": "Plains",
    "card_types": ["Land"],
    "supertypes": ["Basic"],
    "subtypes": ["Plains"],
    "mana_cost": {},
    "effects": [],
}


# Canonical Lander token Rust dict (the Spacecraft-substrate Lander
# subtype that counts as a valid sacrifice target for the
# ``OptionalSacLandOrLanderForBasicLandRamp`` Effect).
_LANDER_RUST_DICT = {
    "name": "Lander",
    "card_types": ["Artifact"],
    "subtypes": ["Lander"],
    "mana_cost": {},
    "effects": [],
}


# ---------------------------------------------------------------------------
# (1) Parser SoT — Larval Scoutlander is parser-claimed and emits the
# expected Phase-3A-pilot shape (re-asserted here so this module is
# self-contained for the PROBED-tier evidence).
# ---------------------------------------------------------------------------


def test_larval_scoutlander_parser_claims_card():
    """Pins the active CardSource is producing the Larval Scoutlander
    printing under its canonical EoE name.
    """
    assert "Larval Scoutlander" in _PRINTINGS, (
        "Larval Scoutlander must be parser-claimed by the active "
        "CardSource (EoE set + reprint coverage)"
    )


def test_larval_scoutlander_printed_attrs():
    """Pins the basic printing surface: Artifact — Spacecraft, 3/3,
    cost ``{2}{G}``, ``station_threshold=7``, stationed_keywords =
    ``{flying}``, ONE ETB trigger with the canonical Phase-3A shape
    (the §2 teeth — the admit predicate's load-bearing gates).
    """
    p = _PRINTINGS["Larval Scoutlander"]
    assert p.card_types == ("Artifact",)
    assert "Spacecraft" in p.subtypes
    assert p.power == 3 and p.toughness == 3
    assert p.mana_cost.generic == 2
    assert ("G", 1) in p.mana_cost.colored
    assert p.station_threshold == 7
    assert p.stationed_keywords == frozenset({"flying"})
    # The §2 teeth — ONE trigger; zero static/activated; no warp /
    # spell_effect / loyalty / room_halves / cost_reductions.
    assert p.activated_abilities == ()
    assert p.static_abilities == ()
    assert p.spell_effect is None
    assert p.warp_cost is None
    assert p.keywords == frozenset()
    assert len(p.triggered_abilities) == 1
    (ta,) = p.triggered_abilities
    # Live shape pinned against the design doc §3A row (mirror of the
    # C1 verify-first pin).
    from mtg_bot.effects.combinators import (
        OptionalSacLandOrLanderForBasicLandRamp,
    )
    from mtg_bot.effects.predicates import Event, IsSelf
    assert ta.event is Event.ENTERS
    assert isinstance(ta.predicate, IsSelf)
    assert ta.predicate.subject is None
    assert isinstance(ta.effect, OptionalSacLandOrLanderForBasicLandRamp)
    assert ta.effect.land_count == 2
    assert ta.tier_threshold == 0
    assert ta.once_per_turn is False


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the C2 forward arm
# ``_spec_card_to_printing_dict`` round-trip on the genuine parsed
# Larval Scoutlander printing through the new dedicated admit
# predicate. Pins the canonical Rust dict shape this probe drives both
# engines through.
# ---------------------------------------------------------------------------


def test_larval_scoutlander_bridge_round_trip_canonical_rust_dict():
    """The C2 admit-gate's bridge: Python printing →
    :func:`_phase_3_trigger_spacecraft_card_def` → CardDef →
    ``_spec_card_to_printing_dict`` → canonical Rust registry dict
    matches ``_LARVAL_SCOUTLANDER_RUST_DICT`` byte-equal. Pins the
    probe's source-of-truth that both engines read the SAME printing
    shape.
    """
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _spec_card_to_printing_dict

    p_orig = _PRINTINGS["Larval Scoutlander"]
    cd = trajectory._phase_3_trigger_spacecraft_card_def(p_orig)
    assert cd is not None, (
        "Larval Scoutlander must pass the Phase-3A admit predicate "
        "per Cycle 2"
    )
    pd = _spec_card_to_printing_dict(cd)
    # Compare modulo stationed_keywords list order (frozenset roundtrip
    # is deterministic but the comparison should be order-agnostic).
    pd_canon = dict(pd)
    pd_canon["stationed_keywords"] = sorted(pd["stationed_keywords"])
    expected = dict(_LARVAL_SCOUTLANDER_RUST_DICT)
    expected["stationed_keywords"] = sorted(expected["stationed_keywords"])
    assert pd_canon == expected, (
        f"Larval Scoutlander Rust registry dict must match the probe's "
        f"pinned shape (the bridge SoT for both engines); "
        f"got pd_canon={pd_canon!r}, expected={expected!r}"
    )


# ---------------------------------------------------------------------------
# (3) Rust effect-arm parse smoke — the canonical Larval Scoutlander
# Rust dict parses on ``register_printing`` (the bridge contract Rust
# honors). The C1 substrate landed the parse arm + the resolve arm;
# the pin is duplicated here for self-contained PROBED-tier evidence.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_canonical_larval_scoutlander_dict():
    """Lockstep pin: Rust's parse arm accepts the canonical Larval
    Scoutlander registry-dict shape ``_LARVAL_SCOUTLANDER_RUST_DICT``
    — the SAME dict the C2 forward emit arm produces for the live
    Larval Scoutlander printing. Threading
    ``triggered_abilities`` with the new
    ``optional_sac_land_or_lander_for_basic_land_ramp`` effect kind
    on a Spacecraft-typed Artifact carrier round-trips byte-equal
    through ``Registry.register_printing``.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_LARVAL_SCOUTLANDER_RUST_DICT)
    assert isinstance(pid, int)
    assert reg.get_printing_name(pid) == "Larval Scoutlander"


# ---------------------------------------------------------------------------
# (4) Loader end-to-end admit — Larval Scoutlander admits at the
# deck-level filter post-Cycle-2 (the FLIP marker mirror).
# ---------------------------------------------------------------------------


def test_larval_scoutlander_loader_end_to_end_admit():
    """End-to-end loader admit: pass ``["Larval Scoutlander"]`` to
    ``_filter_deck_to_bridge_supported`` → admitted; CardDef emitted
    carries Phase-3A trigger shape.
    """
    from mtg_bot.parity import trajectory
    filt, defs = trajectory._filter_deck_to_bridge_supported(
        ["Larval Scoutlander"], _PRINTINGS,
    )
    assert filt == ["Larval Scoutlander"]
    assert len(defs) == 1
    cd = defs[0]
    assert cd.name == "Larval Scoutlander"
    assert cd.triggered_abilities == (
        {
            "event": "enters",
            "predicate": {"kind": "source_is_self"},
            "effect": {
                "kind": "optional_sac_land_or_lander_for_basic_land_ramp",
                "land_count": 2,
            },
        },
    )


# ---------------------------------------------------------------------------
# (5) Scenario A — empty bf, no Lands/Landers (silent no-op decline
# path). Larval Scoutlander enters an empty bf; ETB queues + resolves;
# optional-sac arm finds no eligible target; no basic lands are
# fetched. Asserts byte-equal post-state across engines (only Larval
# Scoutlander itself on bf; library untouched; no graveyard movement).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_larval_scoutlander_empty_bf_scenario_a_parity():
    """**GENUINE real-EoE cross-engine probe — Scenario A (empty bf
    no eligible target). PROBED tier flip evidence (Cycle 2 closure
    marker, scenario A — the silent no-op decline path).**

    Pre-state on both engines:
      * Empty battlefield (no Lands, no Lander tokens).
      * Library carries 2 Plains on each side (would be searched IF
        the optional-sac arm took the accept path).
      * Larval Scoutlander on p0's hand.

    Drive: ``put_into_battlefield`` (Python) /
    ``register_and_inject_object(..., ZONE_BATTLEFIELD)`` (Rust)
    fires the ETB trigger on both engines. The trigger queues onto
    the stack; resolution walks the optional-sac arm and finds NO
    eligible Land-or-Lander permanent the controller controls; the
    arm silent-no-ops on both engines (Rust resolve arm at
    ``state_ops_resolve.rs`` C1 substrate; Python
    ``OptionalSacLandOrLanderForBasicLandRamp.resolve`` at
    ``effects/combinators.py:699`` early-returns when ``options``
    is empty).

    Post-resolve (both engines):
      * Larval Scoutlander on bf (the fresh ETB-arrival permanent).
      * Library still carries 2 Plains (no search fired).
      * Graveyard empty.
      * Stack empty.
    """
    from mtg_bot.actions import put_into_battlefield, resolve_top_of_stack
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import BASIC_LANDS
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_rust_state,
    )
    from tests.parity._picker_shims import _PayOptionalSacFirstAgent

    larval_printing = _PRINTINGS.get("Larval Scoutlander")
    if larval_printing is None:
        pytest.skip("Larval Scoutlander absent from active CardSource")

    # ---- Python side: fresh state with the picker shim agent on p0.
    py = GameState()
    py.players.append(Player(id=0, agent=_PayOptionalSacFirstAgent()))
    py.players.append(Player(id=1, agent=RandomAgent()))

    # Library: 2 Plains (would be searched on the accept path).
    for _ in range(2):
        lib = py.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        py.players[0].library.append(lib)

    # Larval Scoutlander on p0's hand (will be ETB'd via
    # put_into_battlefield).
    py_scout = py.new_object(larval_printing, 0, Zone.HAND)
    py.players[0].hand.append(py_scout)

    # ---- Rust side: build a snapshot-shaped state via the bridge so
    # the cross-engine harness's registry is bootstrapped, then seat
    # the canonical Larval Scoutlander dict via
    # ``register_and_inject_object`` which routes through the
    # registry-build path.
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rs = build_rust_state(spec)

    # Library: 2 Plains on Rust side too (Rust's library is a Vec; we
    # seat via ZONE_LIBRARY which appends).
    for _ in range(2):
        rs.register_and_inject_object(_PLAINS_RUST_DICT, 0, ZONE_LIBRARY)

    # Larval Scoutlander into bf to fire ETB on Rust (the
    # register-and-inject ZONE_BATTLEFIELD path also drains pending
    # ETB dispatches by design).
    rs_scout = rs.register_and_inject_object(
        _LARVAL_SCOUTLANDER_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )

    # ---- Python: drive the ETB trigger via put_into_battlefield.
    put_into_battlefield(py, py_scout, controller_id=0)
    while py.stack:
        resolve_top_of_stack(py)

    # ---- Rust: drain stack.
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()

    # ---- Post-resolve observables.
    # Stack empty on both engines.
    assert len(py.stack) == 0
    assert rs.stack_size() == 0

    # Larval Scoutlander on bf on both engines.
    assert py_scout.zone == Zone.BATTLEFIELD
    assert rs.find_object_zone(rs_scout) == ZONE_BATTLEFIELD

    # No Plains fetched (silent no-op on the optional-sac arm).
    py_bf_plains = [
        o for o in py.battlefield
        if o.printing.name == "Plains" and o.controller_id == 0
    ]
    assert len(py_bf_plains) == 0, (
        f"Python: scenario A must silent-no-op (no eligible Land or "
        f"Lander to sac → no Plains fetched); got {len(py_bf_plains)} "
        f"Plains on bf."
    )

    # Library still has 2 Plains (no search fired on either engine).
    assert len(py.players[0].library) == 2, (
        f"Python: library must still carry 2 Plains; "
        f"got {len(py.players[0].library)}"
    )

    # Graveyard empty (no sacrifice fired).
    assert py.players[0].graveyard == []


# ---------------------------------------------------------------------------
# (6) Scenario B — 1 Forest + 1 Lander on bf (optional-accept +
# sac-first-eligible + 2 basic Plains enter tapped). Larval Scoutlander
# enters a bf with 1 Forest + 1 Lander; ETB queues + resolves; sacrifice
# arm picks the first eligible (Forest, insertion order); 2 Plains enter
# tapped from library. Asserts byte-equal across engines.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_larval_scoutlander_forest_lander_scenario_b_parity():
    """**GENUINE real-EoE cross-engine probe — Scenario B (Forest +
    Lander on bf; optional-accept; sac Forest; search 2 Plains
    tapped). PROBED tier flip evidence (Cycle 2 closure marker,
    scenario B — THE LOAD-BEARING happy path).**

    Pre-state on both engines:
      * 1 Forest on p0's battlefield (seated FIRST so it's bf[0]
        eligibility-iter — both engines pick this as the sacrifice).
      * 1 Lander token on p0's battlefield (seated SECOND; the
        second eligible target — still valid for sac, but the
        deterministic-first pick on both engines picks Forest).
      * Library carries 2 Plains on p0 (the search target pool).
      * Larval Scoutlander on p0's hand.

    Drive: ``put_into_battlefield`` / ``register_and_inject_object``
    fires the ETB on both engines. The trigger queues + resolves
    through the optional-accept path:
      1. ``OptionalSacLandOrLanderForBasicLandRamp.resolve`` walks
         the bf for Land-or-Lander permanents the controller owns;
         finds 2 candidates (Forest, Lander).
      2. ``_PayOptionalSacFirstAgent.choose_yes_no`` → True (Rust
         has no decline path).
      3. ``_PayOptionalSacFirstAgent.choose_sacrifice`` →
         ``legal_object_ids[0]`` = Forest.
      4. Forest moved to graveyard (LEAVES + IS_SACRIFICED
         dispatches on both engines).
      5. Inner ``SearchLibraryForBasicLandTapped(count=2)`` fires;
         picks 2 Plains from library deterministically; enters them
         tapped; post-search Fisher-Yates shuffle on both engines.

    Post-resolve (both engines):
      * Forest in p0's graveyard (sacrificed).
      * Lander still on p0's bf (NOT sacrificed; first-pick won).
      * 2 Plains on p0's bf, tapped.
      * 0 Plains in p0's library.
      * Larval Scoutlander on bf (the ETB carrier).
      * Stack empty.
    """
    from mtg_bot.actions import put_into_battlefield, resolve_top_of_stack
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import BASIC_LANDS, TOKEN_PRINTINGS
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_rust_state,
    )
    from tests.parity._picker_shims import _PayOptionalSacFirstAgent

    larval_printing = _PRINTINGS.get("Larval Scoutlander")
    if larval_printing is None:
        pytest.skip("Larval Scoutlander absent from active CardSource")

    # ---- Python side.
    py = GameState()
    py.players.append(Player(id=0, agent=_PayOptionalSacFirstAgent()))
    py.players.append(Player(id=1, agent=RandomAgent()))

    # bf order: Forest FIRST (eligible-iter [0]; both engines pick
    # this as the sacrifice), Lander SECOND.
    py_forest = py.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
    py.battlefield.append(py_forest)
    py_lander = py.new_object(TOKEN_PRINTINGS["Lander"], 0, Zone.BATTLEFIELD)
    py.battlefield.append(py_lander)

    # Library: 2 Plains.
    for _ in range(2):
        lib = py.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        py.players[0].library.append(lib)

    # Larval Scoutlander on hand (will be cast via put_into_battlefield).
    py_scout = py.new_object(larval_printing, 0, Zone.HAND)
    py.players[0].hand.append(py_scout)

    # ---- Rust side.
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rs = build_rust_state(spec)

    # bf order: Forest FIRST, Lander SECOND.
    rs_forest = rs.register_and_inject_object(
        _FOREST_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    rs_lander = rs.register_and_inject_object(
        _LANDER_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )

    # Library: 2 Plains.
    for _ in range(2):
        rs.register_and_inject_object(_PLAINS_RUST_DICT, 0, ZONE_LIBRARY)

    # Larval Scoutlander into bf to fire ETB on Rust.
    rs_scout = rs.register_and_inject_object(
        _LARVAL_SCOUTLANDER_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )

    # ---- Python: fire ETB.
    put_into_battlefield(py, py_scout, controller_id=0)
    while py.stack:
        resolve_top_of_stack(py)

    # ---- Rust: drain stack.
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()

    # ---- Post-resolve observables (both engines).
    # Stack empty.
    assert len(py.stack) == 0
    assert rs.stack_size() == 0

    # Forest in graveyard (sacrificed by first-pick).
    assert py_forest.zone == Zone.GRAVEYARD, (
        f"Python: Forest must be sacrificed to graveyard; "
        f"got zone={py_forest.zone}"
    )
    assert rs.find_object_zone(rs_forest) == ZONE_GRAVEYARD, (
        f"Rust: Forest must be sacrificed to graveyard; "
        f"got zone={rs.find_object_zone(rs_forest)}"
    )

    # Lander still on bf (NOT sacrificed; deterministic-first-pick
    # already took Forest).
    assert py_lander.zone == Zone.BATTLEFIELD
    assert rs.find_object_zone(rs_lander) == ZONE_BATTLEFIELD

    # Larval Scoutlander on bf (the ETB carrier).
    assert py_scout.zone == Zone.BATTLEFIELD
    assert rs.find_object_zone(rs_scout) == ZONE_BATTLEFIELD

    # 2 Plains on p0's bf (the search-tap result).
    py_bf_plains = [
        o for o in py.battlefield
        if o.printing.name == "Plains" and o.controller_id == 0
    ]
    assert len(py_bf_plains) == 2, (
        f"Python: scenario B accept path must fetch 2 Plains tapped; "
        f"got {len(py_bf_plains)} Plains on bf."
    )
    # And they're tapped on Python.
    for p_plain in py_bf_plains:
        assert p_plain.tapped is True, (
            "Python: searched-up Plains must enter tapped (per the "
            "Effect class semantics)"
        )

    # Library drained (no Plains left).
    py_lib_plains = [
        o for o in py.players[0].library
        if o.printing.name == "Plains"
    ]
    assert len(py_lib_plains) == 0, (
        f"Python: library must be drained of Plains post-search; "
        f"got {len(py_lib_plains)} Plains in library."
    )
