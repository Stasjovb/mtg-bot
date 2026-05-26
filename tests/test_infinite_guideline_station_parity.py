"""Infinite Guideline Station -- per-card real-EoE cross-engine
byte-equal probe (``covered_by_construction`` -> PROBED tier flip;
Spacecraft Station substrate Phase 3C Cycle 4 closure marker for
Scenarios A+B per design doc §6.4 #16; **PHASE 3 CLOSED**).

Infinite Guideline Station is a ``{W}{U}{B}{R}{G}`` Legendary Artifact
-- Spacecraft in the EoE pool carrying the Phase-3C-Cycle-4 two-trigger
shape:

    Power/Toughness: 7/15
    Station threshold: 12
    Stationed keywords: flying
    Triggered abilities:
      MODE 0 -- ETB trigger (always fires; tier=0):
        event = Event.ENTERS
        predicate = IsSelf(subject=None)
        effect = CreateTokenPerMulticoloredPermanent(
                     token_printing=Robot 2/2, tapped=True)
        tier_threshold = 0
        once_per_turn = False
      MODE 1 -- ATTACKS trigger (always fires; tier=0):
        event = Event.ATTACKS
        predicate = IsSelf(subject=None)
        effect = DrawCardPerMulticoloredPermanent()
        tier_threshold = 0
        once_per_turn = False

Per design doc §3C, Infinite Guideline Station is the FINAL trigger-leg
carrier in the Phase 3C admit set. The strict admit predicate
:func:`mtg_bot.parity.trajectory._printing_is_bridge_phase_3_trigger_
spacecraft` positively rejects every non-Phase-3 carrier. **PHASE 3
CLOSED** -- the only Spacecraft remaining DECLINED post-Cycle-4 is The
Eternity Elevator (Phase 4 territory).

**Multi-cycle DECLINED -> ADMITTED -> PROBED transition.**

  * **Phase 3C Cycle 1 (Rust substrate landing, commit ``ebc94a5c``).**
    Rust substrate: ``TriggeredAbility.tier_threshold: i32`` slot +
    trigger-firing-time gate. Infinite Guideline Station STAYED
    DECLINED.
  * **Phase 3C Cycle 2 (Synthesizer Labship FLIP, commit ``277ad6d6``).**
    Synthesizer Labship admitted; Infinite Guideline Station STAYED
    DECLINED.
  * **Phase 3C Cycle 3 (Entropic Battlecruiser FLIP, commit ``e24df399``).**
    Entropic Battlecruiser admitted; Infinite Guideline Station STAYED
    DECLINED.
  * **Phase 3C Cycle 4 (THE FLIP, this slice; PHASE 3 CLOSED).**
    Combined Rust + Python cycle:
      - New ``Effect::CreateTokenPerMulticoloredPermanent { token_
        printing_id: u32, tapped: bool }`` Rust variant on
        ``cards.rs::Effect`` + parse / to_pydict / resolve arms +
        cross-engine bridge dict-to-Python arm in ``cross_engine.py``.
      - New ``Effect::DrawCardPerMulticoloredPermanent`` unit Rust
        variant + same parse / to_pydict / resolve / bridge arm
        family.
      - Widen :data:`_PHASE_3A_SPACECRAFT_TRIGGER_EFFECT_CLASSES` to
        include BOTH new Effect classes (5 -> 7 classes;
        event-shape table UNCHANGED at 4 because IGS's two triggers
        use existing ``(ENTERS, IsSelf)`` and ``(ATTACKS, IsSelf)``
        shapes added in Phase 3A C2 / Phase 3B C2 respectively).
      - Per-card builder's matching Effect-dict-emit arms (the ETB
        arm emits a symbolic ``_token_card_def`` Robot ref for the
        loader's ``_seat_token_printings`` pass, which is extended
        this cycle to recognize the new ``create_token_per_
        multicolored_permanent`` kind).
    Infinite Guideline Station DECLINED -> ADMITTED (admit set 6 -> 7;
    the SEVENTH Spacecraft admit after Sawship + Lumen-Class Frigate +
    Larval Scoutlander + Sledge-Class Seedship + Synthesizer Labship +
    Entropic Battlecruiser).
  * **Phase 3C Cycle 4 (THIS LANE; THE PROBE -- Scenarios A+B).**
    Per-card real-EoE cross-engine byte-equality probe driving BOTH
    engines through TWO scenarios across the multicolored-permanent-
    count axis per design doc §6.4 #16:

    (A) **ETB trigger with N multicolored permanents (load-bearing
        token-spawn path).** Infinite Guideline Station ETBs on p0's
        bf with TWO synthetic multicolored permanents already on the
        bf (a Boros-Reckoner-shape ``{R}{W}`` artifact + a Maelstrom-
        Wanderer-shape ``{B}{G}{R}{U}{W}`` artifact). The ETB
        trigger fires + resolves: the multicolored-permanent count
        is THREE (IGS itself + 2 synthetics; IGS's ``{W}{U}{B}{R}
        {G}`` cost has 5 colors so it counts as multicolored). THREE
        Robot 2/2 tokens enter p0's bf tapped. Byte-equal token
        count across engines.

    (B) **Stationed + ATTACKS trigger at charge>=12 with 2
        multicolored permanents (load-bearing draw path).** Infinite
        Guideline Station stationed (charge=12, animate threshold);
        TWO synthetic multicolored permanents on p0's bf (same as
        Scenario A). Declare IGS as attacker; mode-1 ATTACKS trigger
        fires + resolves: multicolored count is THREE (IGS itself +
        2 synthetics); p0 draws 3 cards. Byte-equal draw count
        across engines.

**Multicolored-permanent count primitive.** Both engines compute the
count at TRIGGER RESOLUTION time (CR 603.3) by walking the source-
controller's battlefield and counting every object whose printing's
mana cost has 2+ distinct nonzero color slots. The IGS itself counts
(5 colors); the two synthetic Boros-Reckoner-shape (W+R = 2 colors)
and Maelstrom-Wanderer-shape (5 colors) also count. A single-color
permanent (e.g. a ``{R}`` artifact) does NOT count.

**Real-EoE-signal discipline.** This module uses the live
``OracleParserCardSource`` Infinite Guideline Station printing on the
Python side AND the canonical Rust registry dict shape emitted by the
C4 bridge forward arm
``_spec_card_to_printing_dict(_phase_3_trigger_spacecraft_card_def(
p))`` on the Rust side -- the SAME printing shape both engines read
(verified pre-flight via the C4 bridge round-trip pin below). The
synthetic multicolored artifacts and the Robot 2/2 token printing
register through the cross-engine bridge map per the established
``register_token_printing`` pattern.

This module is the Spacecraft Phase 3C Cycle 4 closure marker;
**PHASE 3 CLOSED**.
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


# Canonical Rust dict for the Robot 2/2 token (vanilla artifact
# creature; mirrors TOKEN_PRINTINGS["Robot"]).
_ROBOT_TOKEN_RUST_DICT = {
    "name": "Robot",
    "card_types": ["Artifact", "Creature"],
    "subtypes": ["Robot"],
    "supertypes": ["Token"],
    "mana_cost": {},
    "effects": [],
    "power": 2,
    "toughness": 2,
}


# Canonical synthetic 2-color artifact dict (Boros-Reckoner-shape: a
# ``{R}{W}`` multicolored artifact). Used as one of the multicolored
# permanents the IGS triggers count.
_BOROS_RECKONER_SHAPE_RUST_DICT = {
    "name": "Test Boros Artifact",
    "card_types": ["Artifact"],
    "subtypes": [],
    "mana_cost": {"R": 1, "W": 1},
    "effects": [],
}


# Canonical synthetic 5-color artifact dict (Maelstrom-Wanderer-shape:
# a ``{W}{U}{B}{R}{G}`` multicolored artifact). Second multicolored
# permanent.
_MAELSTROM_WANDERER_SHAPE_RUST_DICT = {
    "name": "Test 5Color Artifact",
    "card_types": ["Artifact"],
    "subtypes": [],
    "mana_cost": {"W": 1, "U": 1, "B": 1, "R": 1, "G": 1},
    "effects": [],
}


# ---------------------------------------------------------------------------
# (1) Parser SoT -- Infinite Guideline Station is parser-claimed and emits
# the expected Phase-3C-Cycle-4 shape.
# ---------------------------------------------------------------------------


def test_infinite_guideline_station_parser_claims_card():
    """Pins the active CardSource produces Infinite Guideline Station
    under its canonical EoE name.
    """
    assert "Infinite Guideline Station" in _PRINTINGS, (
        "Infinite Guideline Station must be parser-claimed by the "
        "active CardSource (EoE set + reprint coverage)"
    )


def test_infinite_guideline_station_printed_attrs():
    """Pins the basic printing surface: Legendary Artifact -- Spacecraft,
    7/15, cost ``{W}{U}{B}{R}{G}``, ``station_threshold=12``,
    stationed_keywords = ``{flying}``, TWO triggers (mode-0 ETB +
    mode-1 ATTACKS) with the canonical Phase-3C-Cycle-4 shape.
    """
    p = _PRINTINGS["Infinite Guideline Station"]
    assert p.card_types == ("Artifact",)
    assert "Spacecraft" in p.subtypes
    assert "Legendary" in p.supertypes
    assert p.power == 7 and p.toughness == 15
    assert p.mana_cost.generic == 0
    # 5-color cost (one pip per color).
    for sym in ("W", "U", "B", "R", "G"):
        assert (sym, 1) in p.mana_cost.colored, (
            f"Infinite Guideline Station's mana cost must include 1 "
            f"{sym} pip; got {p.mana_cost.colored!r}"
        )
    assert p.station_threshold == 12
    assert p.stationed_keywords == frozenset({"flying"})
    # The §2 teeth -- TWO triggers; zero static/activated; no warp /
    # spell_effect / loyalty / room_halves / cost_reductions.
    assert p.activated_abilities == ()
    assert p.static_abilities == ()
    assert p.spell_effect is None
    assert p.warp_cost is None
    assert p.keywords == frozenset()
    assert len(p.triggered_abilities) == 2
    from mtg_bot.effects.generic.draw_mill import (
        DrawCardPerMulticoloredPermanent,
    )
    from mtg_bot.effects.generic.tokens import (
        CreateTokenPerMulticoloredPermanent,
    )
    from mtg_bot.effects.predicates import Event, IsSelf
    mode_0, mode_1 = p.triggered_abilities
    # Mode 0 -- ETB / IsSelf / CreateTokenPerMulticoloredPermanent(Robot, tapped=True).
    assert mode_0.event is Event.ENTERS
    assert isinstance(mode_0.predicate, IsSelf)
    assert mode_0.predicate.subject is None
    assert isinstance(mode_0.effect, CreateTokenPerMulticoloredPermanent)
    assert mode_0.effect.token_printing.name == "Robot"
    assert mode_0.effect.tapped is True
    assert mode_0.tier_threshold == 0
    assert mode_0.once_per_turn is False
    # Mode 1 -- ATTACKS / IsSelf / DrawCardPerMulticoloredPermanent.
    assert mode_1.event is Event.ATTACKS
    assert isinstance(mode_1.predicate, IsSelf)
    assert mode_1.predicate.subject is None
    assert isinstance(mode_1.effect, DrawCardPerMulticoloredPermanent)
    assert mode_1.tier_threshold == 0
    assert mode_1.once_per_turn is False


# ---------------------------------------------------------------------------
# (2) Bridge round-trip -- the C4 forward arm
# ``_spec_card_to_printing_dict`` (post-seating) on the genuine parsed
# Infinite Guideline Station printing emits a Rust dict whose
# triggered_abilities carry the new Cycle-4 effect kinds.
# ---------------------------------------------------------------------------


def test_infinite_guideline_station_bridge_round_trip_post_seating():
    """The C4 admit-gate's bridge: Python printing ->
    :func:`_phase_3_trigger_spacecraft_card_def` -> CardDef ->
    ``_seat_token_printings`` (resolves the symbolic ``_token_card_def``
    to a numeric ``token_printing_id``) -> ``_spec_card_to_printing_dict``
    -> canonical Rust registry dict. Both engines see the same shape
    after seating.
    """
    import dataclasses
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _spec_card_to_printing_dict

    p_orig = _PRINTINGS["Infinite Guideline Station"]
    cd = trajectory._phase_3_trigger_spacecraft_card_def(p_orig)
    assert cd is not None, (
        "Infinite Guideline Station must pass the Phase-3C-Cycle-4 "
        "admit predicate post-FLIP"
    )
    # Pre-seating: the ETB trigger's effect carries a symbolic
    # ``_token_card_def`` reference, NOT a numeric ``token_printing_id``.
    assert cd.triggered_abilities[0]["effect"]["kind"] == (
        "create_token_per_multicolored_permanent"
    )
    assert "_token_card_def" in cd.triggered_abilities[0]["effect"]
    assert cd.triggered_abilities[0]["effect"]["tapped"] is True
    # ATTACKS trigger is the unit-variant draw effect.
    assert cd.triggered_abilities[1]["effect"] == {
        "kind": "draw_card_per_multicolored_permanent",
    }

    # Post-seating: simulate the loader's ``_seat_token_printings`` pass
    # by walking the IGS CardDef + a fresh union list. The seating
    # rewrites the symbolic ref to a numeric ``token_printing_id``.
    seated = trajectory._seat_token_printings([cd])
    # Carrier + 1 Robot token CardDef post-seating.
    assert len(seated) == 2
    carrier = seated[0]
    robot_cd = seated[1]
    assert carrier.name == "Infinite Guideline Station"
    assert robot_cd.name == "Robot"
    # Symbolic ref is gone; numeric pid is present.
    eff_post = carrier.triggered_abilities[0]["effect"]
    assert "_token_card_def" not in eff_post
    assert eff_post["kind"] == "create_token_per_multicolored_permanent"
    assert eff_post["tapped"] is True
    assert eff_post["token_printing_id"] == 1  # Robot's pid in this 2-elt union

    # Forward emit to Rust dict shape -- byte-equal.
    pd = _spec_card_to_printing_dict(carrier)
    assert pd["name"] == "Infinite Guideline Station"
    assert pd["station_threshold"] == 12
    assert sorted(pd["stationed_keywords"]) == ["flying"]
    assert pd["power"] == 7
    assert pd["toughness"] == 15
    assert pd["supertypes"] == ("Legendary",) or pd["supertypes"] == [
        "Legendary"
    ]
    assert len(pd["triggered_abilities"]) == 2
    pd_ta0 = pd["triggered_abilities"][0]
    assert pd_ta0["event"] == "enters"
    assert pd_ta0["predicate"] == {"kind": "source_is_self"}
    assert pd_ta0["effect"]["kind"] == (
        "create_token_per_multicolored_permanent"
    )
    assert pd_ta0["effect"]["tapped"] is True
    assert pd_ta0["effect"]["token_printing_id"] == 1
    pd_ta1 = pd["triggered_abilities"][1]
    assert pd_ta1["event"] == "attacks"
    assert pd_ta1["predicate"] == {"kind": "source_is_self"}
    assert pd_ta1["effect"] == {
        "kind": "draw_card_per_multicolored_permanent",
    }


# ---------------------------------------------------------------------------
# (3) Rust effect-arm parse smoke -- Rust accepts the canonical IGS
# dict (post-seating) on ``register_printing``.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_canonical_infinite_guideline_station_dict():
    """Lockstep pin: Rust's parse arm accepts the canonical Infinite
    Guideline Station registry-dict shape. Threading
    ``triggered_abilities`` with the new
    ``create_token_per_multicolored_permanent`` effect kind (carrying
    the Robot pid + tapped=True) + the new
    ``draw_card_per_multicolored_permanent`` unit effect kind round-
    trips byte-equal through ``Registry.register_printing``.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    robot_pid = reg.register_printing(_ROBOT_TOKEN_RUST_DICT)
    igs_dict = {
        "name": "Infinite Guideline Station",
        "card_types": ["Artifact"],
        "mana_cost": {"W": 1, "U": 1, "B": 1, "R": 1, "G": 1},
        "effects": [],
        "power": 7,
        "toughness": 15,
        "subtypes": ["Spacecraft"],
        "supertypes": ["Legendary"],
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "create_token_per_multicolored_permanent",
                    "tapped": True,
                    "token_printing_id": robot_pid,
                },
            },
            {
                "event": "attacks",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "draw_card_per_multicolored_permanent",
                },
            },
        ],
        "station_threshold": 12,
        "stationed_keywords": ["flying"],
    }
    pid = reg.register_printing(igs_dict)
    assert isinstance(pid, int)
    assert reg.get_printing_name(pid) == "Infinite Guideline Station"


# ---------------------------------------------------------------------------
# (4) Loader end-to-end admit -- Infinite Guideline Station admits at
# the deck-level filter post-Cycle-4 (the FLIP marker mirror).
# ---------------------------------------------------------------------------


def test_infinite_guideline_station_loader_end_to_end_admit():
    """End-to-end loader admit: pass ``["Infinite Guideline Station"]``
    to ``_filter_deck_to_bridge_supported`` -> admitted; CardDef emitted
    carries the Phase-3C-Cycle-4 two-trigger shape.
    """
    from mtg_bot.parity import trajectory
    filt, defs = trajectory._filter_deck_to_bridge_supported(
        ["Infinite Guideline Station"], _PRINTINGS,
    )
    assert filt == ["Infinite Guideline Station"]
    assert len(defs) == 1
    cd = defs[0]
    assert cd.name == "Infinite Guideline Station"
    assert len(cd.triggered_abilities) == 2
    # ETB / IsSelf / CreateTokenPerMulticoloredPermanent (with symbolic
    # _token_card_def -- the production seating pass would resolve it).
    eff0 = cd.triggered_abilities[0]["effect"]
    assert eff0["kind"] == "create_token_per_multicolored_permanent"
    assert eff0["tapped"] is True
    assert "_token_card_def" in eff0
    # ATTACKS / IsSelf / DrawCardPerMulticoloredPermanent.
    assert cd.triggered_abilities[1] == {
        "event": "attacks",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "draw_card_per_multicolored_permanent"},
    }


# ---------------------------------------------------------------------------
# (5) Scenario A -- ETB trigger with N=3 multicolored permanents.
# IGS ETBs (counts itself as multicolored) + 2 synthetic multicolored
# artifacts on bf -> N=3 Robot tokens spawn tapped on both engines.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_igs_etb_token_spawn_scenario_a_parity():
    """**GENUINE real-EoE cross-engine probe -- Scenario A (ETB +
    CreateTokenPerMulticoloredPermanent + N=3 multicolored permanents).
    PROBED tier flip evidence (Cycle 4 closure marker, scenario A --
    THE LOAD-BEARING token-spawn path).**

    Pre-state on both engines:
      * Two synthetic multicolored artifacts on p0's bf (Boros-shape
        ``{R}{W}`` and 5-color-shape ``{W}{U}{B}{R}{G}``).

    Drive: register Infinite Guideline Station + a Robot 2/2 token
    printing on the Rust side; on Python register the token printing
    via ``register_token_printing``. Inject IGS via ETB on both
    engines (the ETB queues the ENTERS trigger which resolves into
    the CreateTokenPerMulticoloredPermanent arm).

    Post-resolve (both engines):
      * IGS itself is multicolored (5 colors) so the multicolored count
        is THREE (IGS + 2 synthetics). Three Robot 2/2 tokens enter
        p0's bf tapped.
      * Each token's printing is the registered Robot.
      * Each token is summoning_sick (tokens are creatures).
    """
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
        register_token_printing,
        clear_token_printings,
    )

    igs_printing = _PRINTINGS.get("Infinite Guideline Station")
    if igs_printing is None:
        pytest.skip(
            "Infinite Guideline Station absent from active CardSource"
        )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Rust side: register Robot token pid via `registry_size`
    # snapshot before injecting (Pinnacle Emissary pattern at
    # tests/test_probe_cast_spell_aa.py:294). The token printing is
    # seeded into p1's library (inert pid-assignment holder, doesn't
    # affect p0's bf which we measure); the actual token spawn happens
    # at ETB resolve time when the new
    # `Effect::CreateTokenPerMulticoloredPermanent` arm fires.
    robot_pid = rs.registry_size
    rs.register_and_inject_object(
        _ROBOT_TOKEN_RUST_DICT, 1, ZONE_LIBRARY,
    )

    # Seat the bridge map so the Python side can resolve token_pid
    # -> CardPrinting at any time during ETB resolve.
    clear_token_printings()
    from mtg_bot.cards.tokens import TOKEN_PRINTINGS
    register_token_printing(robot_pid, TOKEN_PRINTINGS["Robot"])

    # IGS Rust dict (post-seating) -- carries the robot pid + tapped=True.
    igs_rust_dict = {
        "name": "Infinite Guideline Station",
        "card_types": ["Artifact"],
        "mana_cost": {"W": 1, "U": 1, "B": 1, "R": 1, "G": 1},
        "effects": [],
        "power": 7,
        "toughness": 15,
        "subtypes": ["Spacecraft"],
        "supertypes": ["Legendary"],
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "create_token_per_multicolored_permanent",
                    "tapped": True,
                    "token_printing_id": robot_pid,
                },
            },
            {
                "event": "attacks",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "draw_card_per_multicolored_permanent",
                },
            },
        ],
        "station_threshold": 12,
        "stationed_keywords": ["flying"],
    }

    # ---- Python side: build synthetic multicolored artifacts.
    boros_printing = CardPrinting(
        name="Test Boros Artifact",
        mana_cost_str="{R}{W}",
        mana_cost=ManaCost(generic=0, colored=(("R", 1), ("W", 1))),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        keywords=frozenset(),
    )
    fivecolor_printing = CardPrinting(
        name="Test 5Color Artifact",
        mana_cost_str="{W}{U}{B}{R}{G}",
        mana_cost=ManaCost(
            generic=0,
            colored=(
                ("W", 1), ("U", 1), ("B", 1), ("R", 1), ("G", 1),
            ),
        ),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        keywords=frozenset(),
    )

    # Seat 2 multicolored artifacts on p0's bf (Python side).
    py_boros = py.new_object(
        boros_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_boros.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_boros)
    py_5c = py.new_object(
        fivecolor_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_5c.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_5c)

    # Seat IGS on p0's bf (Python side) + queue + resolve the ENTERS
    # trigger.
    from mtg_bot.actions import dispatch_event as py_dispatch_event
    from mtg_bot.effects.predicates import Event as PyEvent
    py_igs = py.new_object(
        igs_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_igs.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_igs)
    py.active_player_idx = 0
    py.priority_player_idx = 0
    py.players[0].agent = None
    py.players[1].agent = None
    # Manually dispatch ENTERS as if IGS just ETB'd (mirrors the
    # production ETB pipeline at actions.py:3472).
    py_dispatch_event(py, PyEvent.ENTERS, label="enters", obj=py_igs)

    # ---- Rust side: seat 2 multicolored artifacts on p0's bf, then
    # IGS on p0's bf, then dispatch ENTERS on IGS via the test-helper.
    rs_boros = rs.register_and_inject_object(
        _BOROS_RECKONER_SHAPE_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    rs_5c = rs.register_and_inject_object(
        _MAELSTROM_WANDERER_SHAPE_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    # `register_and_inject_object` into ZONE_BATTLEFIELD automatically
    # queues + drains the ENTERS dispatch (RS8 -- see
    # state_ops_resolve.rs:25454). So the IGS ETB trigger is already
    # pushed onto the stack at this point.
    rs_igs = rs.register_and_inject_object(
        igs_rust_dict, 0, ZONE_BATTLEFIELD,
    )

    # ---- Drain stacks (the ENTERS trigger resolves -> 3 tokens
    # spawn on each engine).
    while py.stack:
        resolve_top_of_stack(py)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    # ---- Post-resolve observables.
    assert len(py.stack) == 0
    assert rs.stack_size() == 0

    # Python: count Robot tokens on p0's bf.
    py_robots = [
        o for o in py.battlefield
        if o.controller_id == 0 and o.printing.name == "Robot"
    ]
    assert len(py_robots) == 3, (
        f"Python: must create 3 Robot tokens (multicolored count = "
        f"IGS+Boros+5C = 3); got {len(py_robots)}"
    )
    # Every Robot is tapped (the variant's tapped=True rider applies).
    for tok in py_robots:
        assert tok.tapped is True, (
            f"Python: Robot token must enter tapped; got tapped="
            f"{tok.tapped}"
        )

    # Rust: count Robot tokens on p0's bf via the registry name.
    rs_robot_count = rs.count_objects_by_printing_name_on_bf(
        "Robot", 0,
    )
    assert rs_robot_count == 3, (
        f"Rust: must create 3 Robot tokens (multicolored count = 3); "
        f"got {rs_robot_count}"
    )

    # Clean up the bridge map.
    clear_token_printings()


# ---------------------------------------------------------------------------
# (6) Scenario B -- Stationed + ATTACKS trigger at charge>=12 with
# 2 multicolored permanents -> p0 draws 3 cards (multicolored count = 3).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_igs_attacks_draw_scenario_b_parity():
    """**GENUINE real-EoE cross-engine probe -- Scenario B (Stationed
    + ATTACKS + DrawCardPerMulticoloredPermanent + N=3 multicolored
    permanents). PROBED tier flip evidence (Cycle 4 closure marker,
    scenario B -- THE LOAD-BEARING draw-card path).**

    Pre-state on both engines:
      * Infinite Guideline Station on p0's bf with charge_counters=12
        (at the station threshold -- IGS is a creature).
      * Two synthetic multicolored artifacts on p0's bf (Boros-shape
        + 5-color-shape) -- same as Scenario A.
      * p0's library has at least 3 cards (so the draw doesn't bail
        on empty-library).
      * Both players at 20 life.

    Drive: ``declare_attacker`` fires the mode-1 ATTACKS trigger
    (tier=0). Resolves through ``DrawCardPerMulticoloredPermanent``:
    multicolored count = 3 (IGS itself + Boros + 5C); p0 draws 3
    cards.

    Post-resolve (both engines):
      * p0's hand has +3 cards.
      * p0's library has -3 cards.
      * Stack empty.
    """
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.combat import declare_attackers as py_declare_attackers
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
        register_token_printing,
        clear_token_printings,
    )

    igs_printing = _PRINTINGS.get("Infinite Guideline Station")
    if igs_printing is None:
        pytest.skip(
            "Infinite Guideline Station absent from active CardSource"
        )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # Inert Robot token pid assignment via the Pinnacle Emissary
    # pattern (registry_size snapshot + library inject). Inject into
    # p1's library so it doesn't pollute p0's library count (which we
    # measure post-resolve to verify the 3-card draw).
    robot_pid = rs.registry_size
    rs.register_and_inject_object(
        _ROBOT_TOKEN_RUST_DICT, 1, ZONE_LIBRARY,
    )
    clear_token_printings()
    from mtg_bot.cards.tokens import TOKEN_PRINTINGS
    register_token_printing(robot_pid, TOKEN_PRINTINGS["Robot"])

    igs_rust_dict = {
        "name": "Infinite Guideline Station",
        "card_types": ["Artifact"],
        "mana_cost": {"W": 1, "U": 1, "B": 1, "R": 1, "G": 1},
        "effects": [],
        "power": 7,
        "toughness": 15,
        "subtypes": ["Spacecraft"],
        "supertypes": ["Legendary"],
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "create_token_per_multicolored_permanent",
                    "tapped": True,
                    "token_printing_id": robot_pid,
                },
            },
            {
                "event": "attacks",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "draw_card_per_multicolored_permanent",
                },
            },
        ],
        "station_threshold": 12,
        "stationed_keywords": ["flying"],
    }

    # Synthetic library fillers (vanilla {0} artifacts).
    dummy_lib_printing = CardPrinting(
        name="Test Dummy Library Card",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=()),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        keywords=frozenset(),
    )
    dummy_lib_rust_dict = {
        "name": "Test Dummy Library Card",
        "card_types": ["Artifact"],
        "subtypes": [],
        "mana_cost": {"generic": 0},
        "effects": [],
    }

    # Multicolored artifact printings.
    boros_printing = CardPrinting(
        name="Test Boros Artifact",
        mana_cost_str="{R}{W}",
        mana_cost=ManaCost(generic=0, colored=(("R", 1), ("W", 1))),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        keywords=frozenset(),
    )
    fivecolor_printing = CardPrinting(
        name="Test 5Color Artifact",
        mana_cost_str="{W}{U}{B}{R}{G}",
        mana_cost=ManaCost(
            generic=0,
            colored=(
                ("W", 1), ("U", 1), ("B", 1), ("R", 1), ("G", 1),
            ),
        ),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        keywords=frozenset(),
    )

    # ---- Python: seat the 2 multicolored artifacts + IGS (unsick,
    # charge=12 = stationed creature mode) + 5 library fillers on p0.
    py_boros = py.new_object(
        boros_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_boros.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_boros)
    py_5c = py.new_object(
        fivecolor_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_5c.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_5c)
    py_igs = py.new_object(
        igs_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_igs.summoning_sick = False
    py_igs.charge_counters = 12
    py_igs.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_igs)
    for _ in range(5):
        c = py.new_object(
            dummy_lib_printing, owner_id=0, zone=Zone.LIBRARY,
        )
        py.players[0].library.append(c)
    py.active_player_idx = 0
    py.priority_player_idx = 0
    py.players[0].agent = None
    py.players[1].agent = None

    # Pre-state pins.
    assert len(py.players[0].hand) == 0
    assert len(py.players[0].library) == 5

    # ---- Rust: same shape. `register_and_inject_object` into the
    # battlefield auto-dispatches Event::Enters, which fires IGS's ETB
    # CreateTokenPerMulticoloredPermanent trigger. Drain THAT stack
    # before declaring attacker so the only stack item we measure is
    # the ATTACKS trigger Scenario B targets.
    rs_boros = rs.register_and_inject_object(
        _BOROS_RECKONER_SHAPE_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    rs_5c = rs.register_and_inject_object(
        _MAELSTROM_WANDERER_SHAPE_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    rs_igs = rs.register_and_inject_object(
        igs_rust_dict, 0, ZONE_BATTLEFIELD,
    )
    rs.clear_summoning_sick_for_player(0)
    rs.set_charge_counters(rs_igs, 12)
    for _ in range(5):
        rs.register_and_inject_object(
            dummy_lib_rust_dict, 0, ZONE_LIBRARY,
        )
    # Drain the auto-dispatched ENTERS-trigger stack item (IGS's ETB
    # CreateTokenPerMulticoloredPermanent fires + spawns 3 Robot tokens
    # in setup -- we don't measure those here; Scenario A's pin covers
    # token-spawn parity).
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    # ---- Declare IGS as attacker.
    py_declare_attackers(py, [py_igs.id])
    assert len(py.stack) == 1, (
        "Python: IGS's ATTACKS trigger MUST push onto the stack"
    )
    assert rs.declare_attacker(rs_igs) is True
    assert rs.stack_size() == 1, (
        "Rust: IGS's ATTACKS trigger MUST push onto the stack"
    )

    # ---- Drain stacks (the ATTACKS trigger resolves -> p0 draws 3 cards).
    while py.stack:
        resolve_top_of_stack(py)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    # ---- Post-resolve observables (the load-bearing pins).
    assert len(py.stack) == 0
    assert rs.stack_size() == 0
    # p0 drew 3 cards.
    assert len(py.players[0].hand) == 3, (
        f"Python: p0 MUST have drawn 3 cards (multicolored count = "
        f"IGS+Boros+5C = 3); got hand size {len(py.players[0].hand)}"
    )
    assert len(py.players[0].library) == 2, (
        f"Python: p0's library MUST be -3 (5 - 3); got "
        f"{len(py.players[0].library)}"
    )
    rs_hand_sizes = rs.hand_sizes
    rs_lib_sizes = rs.library_sizes
    assert rs_hand_sizes[0] == 3, (
        f"Rust: p0 MUST have drawn 3 cards (multicolored count = 3); "
        f"got hand size {rs_hand_sizes[0]}"
    )
    assert rs_lib_sizes[0] == 2, (
        f"Rust: p0's library MUST be -3 (5 - 3); got {rs_lib_sizes[0]}"
    )

    # IGS is tapped from attacking.
    assert py_igs.tapped is True
    assert rs.is_tapped(rs_igs) is True

    clear_token_printings()
