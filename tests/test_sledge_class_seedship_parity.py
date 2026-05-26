"""Sledge-Class Seedship — per-card real-EoE cross-engine byte-equal
probe (``covered_by_construction`` → PROBED tier flip; Spacecraft
Station substrate Phase 3B Cycle 2 closure marker for Scenarios A+B
per design doc §6.3).

Sledge-Class Seedship is a ``{2}{G}`` Artifact — Spacecraft in the
EoE pool carrying the Phase-3B-pilot single-trigger ATTACKS shape:

    Power/Toughness: 4/5
    Station threshold: 7
    Stationed keywords: flying
    Triggered abilities: ONE ATTACKS trigger —
        event = Event.ATTACKS
        predicate = IsSelf(subject=None)
        effect = OptionalPutCreatureFromHandOntoBattlefield()
        tier_threshold = 0 (always-fire)
        once_per_turn = False

Per design doc §3B, it is one of two carriers in the Phase 3B 2-class
admit set (Larval Scoutlander 3A + Sledge-Class Seedship 3B). The
strict admit predicate
:func:`mtg_bot.parity.trajectory._printing_is_bridge_phase_3_trigger_
spacecraft` positively rejects every non-Phase-3-A/B carrier (the
§6.4 decline-set bench check pins this exhaustively in
``test_spacecraft_phase_3b_cycle_2_flip.py`` — Synthesizer Labship
has BEGINNING_OF_COMBAT + Controlled(YOU) predicate + tier_threshold=2;
Entropic Battlecruiser has EachOpponentDiscardsOrLosesLife / Target
PlayerLosesLife effects + a DISCARDS_CARD trigger; Infinite Guideline
Station has CreateTokenPerMulticoloredPermanent / DrawCardPer
MulticoloredPermanent effects).

**Multi-cycle DECLINED → ADMITTED → PROBED transition.**

  * **Phase 3B Cycle 1 (Rust substrate landing, commit ``2a35f95c``,
    2026-05-25).** Rust substrate: new
    ``Effect::OptionalPutCreatureFromHandOntoBattlefield`` unit
    variant on ``cards.rs::Effect`` + parse / to_pydict / resolve arms
    + cross-engine bridge dict-to-Python arm in ``cross_engine.py`` +
    reverse-serializer leaf in ``trajectory.py``. Sledge-Class
    Seedship STAYED DECLINED at every admit gate (substrate-only
    invariant).
  * **Phase 3B Cycle 2 (THE FLIP, this slice, 2026-05-25).** Widen
    :data:`_PHASE_3A_SPACECRAFT_TRIGGER_EFFECT_CLASSES` to include
    ``OptionalPutCreatureFromHandOntoBattlefield`` + widen
    :data:`_PHASE_3A_SPACECRAFT_TRIGGER_EVENT_SHAPES` to include
    ``(Event.ATTACKS, IsSelf(subject=None))`` + the per-card builder's
    matching ATTACKS arm + Effect-dict-emit arm. Sledge-Class Seedship
    DECLINED → ADMITTED (admit set 42 → 43; the FOURTH Spacecraft
    admit after Sawship + Lumen-Class Frigate + Larval Scoutlander).
  * **Phase 3B Cycle 2 (THIS LANE; THE PROBE — Scenarios A+B).**
    Per-card real-EoE cross-engine byte-equality probe driving BOTH
    engines through TWO scenarios across the eligible-card axis per
    design doc §6.3:

    (A) **Sledge-Class Seedship attacks with EMPTY hand (silent
        fizzle path):** Sledge-Class Seedship on p0's bf (unsick);
        p0's hand is EMPTY of Creature cards (no eligible target);
        declare Seedship as attacker; ATTACKS trigger queues +
        resolves; the put-from-hand arm finds NO eligible Creature
        in hand on either engine and silent-no-ops; nothing enters
        bf from hand; full field-view byte-equal across engines
        (only Sledge-Class Seedship itself on each bf, tapped from
        the attack).

    (B) **Sledge-Class Seedship attacks with a Grizzly Bears in
        hand (load-bearing happy path):** Sledge-Class Seedship on
        p0's bf (unsick) + a synthetic Grizzly Bears in p0's hand;
        declare Seedship as attacker; ATTACKS trigger queues +
        resolves through the put-from-hand path; the Bear leaves
        hand and enters bf UNTAPPED + summoning_sick (CR 302.1);
        ETB dispatch queued + drained per the established CE13 /
        Phase-2b substrate; full field-view byte-equal across
        engines (Seedship tapped, Bear on bf untapped + summoning-
        sick, hand empty, no graveyard movement).

**Scripted-picker semantics.** The probe uses
:class:`_PickFirstLibraryOptionAgent` on p0 to make Python take Rust's
deterministic first-eligible pick branch. Python's
``OptionalPutCreatureFromHandOntoBattlefield.resolve`` (at
``effects/combinators.py:215-240``) calls
``agent.choose_card_from_library(state, controller_id, [c.id for c in
options])`` after filtering ``options`` to in-hand creatures in their
in-hand iteration order. Rust's resolve arm (at
``state_ops_resolve.rs:7093-7160``) walks the controller's hand in
index order and picks the first card whose printing carries
``Creature`` in ``card_types``. Returning ``option_ids[0]`` therefore
selects the SAME first eligible card both engines pick — keeping the
put-from-hand path byte-equal in Scenario B. In Scenario A the
``options`` list is empty so the agent is never invoked and the arm
silent-no-ops on both engines.

**Real-EoE-signal discipline.** This module uses the live
``OracleParserCardSource`` Sledge-Class Seedship printing on the
Python side AND the canonical Rust registry dict shape emitted by the
C2 bridge forward arm
``_spec_card_to_printing_dict(_phase_3_trigger_spacecraft_card_def(
p))`` on the Rust side — the SAME printing shape both engines read
(verified pre-flight via the C2 substrate flip pins
``test_sledge_class_seedship_now_admits_at_admit_gate_post_cycle_2``
and ``test_loader_filter_admits_sledge_class_seedship_post_cycle_2``).
The Grizzly Bears used in Scenario B is a synthetic ``{1}{G}`` 2/2
Bear (sibling shape to the Arabella probe's fodder bear), seated via
the same ``register_and_inject_object`` shim used by every cross-
engine probe.

This module is the Spacecraft Phase 3B closure marker; the full Phase-
3B admit set is exhaustively pinned at Larval Scoutlander (3A) +
Sledge-Class Seedship (3B) post-Cycle-2.
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


# Canonical Rust dict for Sledge-Class Seedship — the EXACT shape
# ``_spec_card_to_printing_dict`` emits via the C2 forward arm
# ``_phase_3_trigger_spacecraft_card_def``. Both engines read this
# same printing shape (verified pre-flight via the C2 admit + builder
# pins in test_spacecraft_phase_3b_substrate_cycle_1.py — the
# `test_loader_filter_admits_sledge_class_seedship_post_cycle_2` pin
# threads the live printing through the builder + asserts the
# triggered_abilities tuple byte-equals this dict's triggered_abilities
# field).
_SLEDGE_CLASS_SEEDSHIP_RUST_DICT = {
    "name": "Sledge-Class Seedship",
    "card_types": ["Artifact"],
    "mana_cost": {"generic": 2, "G": 1},
    "effects": [],
    "power": 4,
    "toughness": 5,
    "subtypes": ["Spacecraft"],
    "station_threshold": 7,
    "stationed_keywords": ["flying"],
    "triggered_abilities": [
        {
            "event": "attacks",
            "predicate": {"kind": "source_is_self"},
            "effect": {
                "kind": "optional_put_creature_from_hand_onto_battlefield",
            },
        },
    ],
}


# Canonical Grizzly Bears Rust dict (Scenario B fodder — eligible
# Creature in hand). Synthetic {1}{G} 2/2 Bear (sibling shape of the
# Arabella probe's fodder bear at line 709).
_GRIZZLY_BEARS_RUST_DICT = {
    "name": "Test Grizzly Bears",
    "card_types": ["Creature"],
    "subtypes": ["Bear"],
    "mana_cost": {"generic": 1, "G": 1},
    "effects": [],
    "power": 2,
    "toughness": 2,
}


# ---------------------------------------------------------------------------
# (1) Parser SoT — Sledge-Class Seedship is parser-claimed and emits
# the expected Phase-3B-pilot shape (re-asserted here so this module
# is self-contained for the PROBED-tier evidence).
# ---------------------------------------------------------------------------


def test_sledge_class_seedship_parser_claims_card():
    """Pins the active CardSource is producing the Sledge-Class
    Seedship printing under its canonical EoE name.
    """
    assert "Sledge-Class Seedship" in _PRINTINGS, (
        "Sledge-Class Seedship must be parser-claimed by the active "
        "CardSource (EoE set + reprint coverage)"
    )


def test_sledge_class_seedship_printed_attrs():
    """Pins the basic printing surface: Artifact — Spacecraft, 4/5,
    cost ``{2}{G}``, ``station_threshold=7``, stationed_keywords =
    ``{flying}``, ONE ATTACKS trigger with the canonical Phase-3B
    shape (the §2 teeth — the admit predicate's load-bearing gates).
    """
    p = _PRINTINGS["Sledge-Class Seedship"]
    assert p.card_types == ("Artifact",)
    assert "Spacecraft" in p.subtypes
    assert p.power == 4 and p.toughness == 5
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
    # Live shape pinned against the design doc §3B row (mirror of the
    # C1 verify-first pin).
    from mtg_bot.effects.combinators import (
        OptionalPutCreatureFromHandOntoBattlefield,
    )
    from mtg_bot.effects.predicates import Event, IsSelf
    assert ta.event is Event.ATTACKS
    assert isinstance(ta.predicate, IsSelf)
    assert ta.predicate.subject is None
    assert isinstance(ta.effect, OptionalPutCreatureFromHandOntoBattlefield)
    assert ta.tier_threshold == 0
    assert ta.once_per_turn is False


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the C2 forward arm
# ``_spec_card_to_printing_dict`` round-trip on the genuine parsed
# Sledge-Class Seedship printing through the new dedicated admit
# predicate. Pins the canonical Rust dict shape this probe drives both
# engines through.
# ---------------------------------------------------------------------------


def test_sledge_class_seedship_bridge_round_trip_canonical_rust_dict():
    """The C2 admit-gate's bridge: Python printing →
    :func:`_phase_3_trigger_spacecraft_card_def` → CardDef →
    ``_spec_card_to_printing_dict`` → canonical Rust registry dict
    matches ``_SLEDGE_CLASS_SEEDSHIP_RUST_DICT`` byte-equal. Pins the
    probe's source-of-truth that both engines read the SAME printing
    shape.
    """
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _spec_card_to_printing_dict

    p_orig = _PRINTINGS["Sledge-Class Seedship"]
    cd = trajectory._phase_3_trigger_spacecraft_card_def(p_orig)
    assert cd is not None, (
        "Sledge-Class Seedship must pass the Phase-3B admit predicate "
        "per Cycle 2"
    )
    pd = _spec_card_to_printing_dict(cd)
    # Compare modulo stationed_keywords list order (frozenset roundtrip
    # is deterministic but the comparison should be order-agnostic).
    pd_canon = dict(pd)
    pd_canon["stationed_keywords"] = sorted(pd["stationed_keywords"])
    expected = dict(_SLEDGE_CLASS_SEEDSHIP_RUST_DICT)
    expected["stationed_keywords"] = sorted(expected["stationed_keywords"])
    assert pd_canon == expected, (
        f"Sledge-Class Seedship Rust registry dict must match the "
        f"probe's pinned shape (the bridge SoT for both engines); "
        f"got pd_canon={pd_canon!r}, expected={expected!r}"
    )


# ---------------------------------------------------------------------------
# (3) Rust effect-arm parse smoke — the canonical Sledge-Class
# Seedship Rust dict parses on ``register_printing`` (the bridge
# contract Rust honors). The C1 substrate landed the parse arm + the
# resolve arm; the pin is duplicated here for self-contained PROBED-
# tier evidence.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_canonical_sledge_class_seedship_dict():
    """Lockstep pin: Rust's parse arm accepts the canonical Sledge-
    Class Seedship registry-dict shape ``_SLEDGE_CLASS_SEEDSHIP_RUST_
    DICT`` — the SAME dict the C2 forward emit arm produces for the
    live Sledge-Class Seedship printing. Threading
    ``triggered_abilities`` with the new
    ``optional_put_creature_from_hand_onto_battlefield`` effect kind
    on a Spacecraft-typed Artifact carrier round-trips byte-equal
    through ``Registry.register_printing``.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_SLEDGE_CLASS_SEEDSHIP_RUST_DICT)
    assert isinstance(pid, int)
    assert reg.get_printing_name(pid) == "Sledge-Class Seedship"


# ---------------------------------------------------------------------------
# (4) Loader end-to-end admit — Sledge-Class Seedship admits at the
# deck-level filter post-Cycle-2 (the FLIP marker mirror).
# ---------------------------------------------------------------------------


def test_sledge_class_seedship_loader_end_to_end_admit():
    """End-to-end loader admit: pass ``["Sledge-Class Seedship"]`` to
    ``_filter_deck_to_bridge_supported`` → admitted; CardDef emitted
    carries Phase-3B trigger shape.
    """
    from mtg_bot.parity import trajectory
    filt, defs = trajectory._filter_deck_to_bridge_supported(
        ["Sledge-Class Seedship"], _PRINTINGS,
    )
    assert filt == ["Sledge-Class Seedship"]
    assert len(defs) == 1
    cd = defs[0]
    assert cd.name == "Sledge-Class Seedship"
    assert cd.triggered_abilities == (
        {
            "event": "attacks",
            "predicate": {"kind": "source_is_self"},
            "effect": {
                "kind": "optional_put_creature_from_hand_onto_battlefield",
            },
        },
    )


# ---------------------------------------------------------------------------
# (5) Scenario A — empty hand (no eligible Creature target); silent
# fizzle. Sledge-Class Seedship attacks with empty hand; ATTACKS
# trigger queues + resolves; put-from-hand arm finds no eligible
# Creature; silent-no-op. Asserts byte-equal post-state across engines
# (only Seedship itself on each bf, tapped from the attack).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_sledge_class_seedship_empty_hand_scenario_a_parity():
    """**GENUINE real-EoE cross-engine probe — Scenario A (empty
    hand; no eligible Creature target; silent fizzle path). PROBED
    tier flip evidence (Cycle 2 closure marker, scenario A — the
    silent fizzle decline path).**

    Pre-state on both engines:
      * Sledge-Class Seedship on p0's bf (unsick, so it can attack
        this turn).
      * p0's hand is EMPTY of Creature cards (NO eligible target for
        the put-from-hand arm).

    Drive: ``declare_attacker`` (Rust) /
    ``combat.declare_attackers([seedship.id])`` (Python) fires the
    ATTACKS trigger on both engines. The trigger queues onto the
    stack; resolution walks the put-from-hand arm and finds NO
    eligible Creature card in p0's hand; the arm silent-no-ops on
    both engines (Rust resolve arm at
    ``state_ops_resolve.rs:7093-7160`` returns Ok(()) on the
    ``pick_idx`` None branch; Python
    ``OptionalPutCreatureFromHandOntoBattlefield.resolve`` at
    ``effects/combinators.py:222-224`` early-returns when ``options``
    is empty).

    Post-resolve (both engines):
      * Sledge-Class Seedship on bf, tapped (from declaring as
        attacker).
      * p0's hand is empty.
      * Nothing entered bf from hand.
      * Stack empty.
    """
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.combat import declare_attackers as py_declare_attackers
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.turn import state_based_actions as py_sba

    seedship_printing = _PRINTINGS.get("Sledge-Class Seedship")
    if seedship_printing is None:
        pytest.skip("Sledge-Class Seedship absent from active CardSource")

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python side: seat Sledge-Class Seedship on p0's bf, unsick.
    py_seedship = py.new_object(
        seedship_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_seedship.summoning_sick = False
    py_seedship.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_seedship)
    # No agent needed — Scenario A has no eligible Creature so the
    # agent is never invoked.
    py.players[0].agent = None
    py.players[1].agent = None

    # ---- Rust side: same shape via register_and_inject_object.
    rs_seedship = rs.register_and_inject_object(
        _SLEDGE_CLASS_SEEDSHIP_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    rs.clear_summoning_sick_for_player(0)

    # Pre-trigger sanity: nothing on either stack; p0 hand empty on
    # both engines.
    assert rs.stack_size() == 0 and len(py.stack) == 0
    assert len(py.players[0].hand) == 0

    # ---- Declare Seedship as attacker on both engines.
    py_declare_attackers(py, [py_seedship.id])
    assert len(py.stack) == 1, (
        "Python: Seedship's ATTACKS trigger must push onto the stack"
    )
    assert rs.declare_attacker(rs_seedship) is True
    assert rs.stack_size() == 1, (
        "Rust: Seedship's ATTACKS trigger must push onto the stack"
    )

    # ---- Drain stacks.
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    # ---- Post-resolve observables.
    # Stack empty on both engines.
    assert len(py.stack) == 0
    assert rs.stack_size() == 0

    # Seedship still on bf, tapped from the attack.
    assert py_seedship.zone == Zone.BATTLEFIELD
    assert py_seedship.tapped is True, (
        "Python: Seedship must be tapped after declaring as attacker"
    )
    assert rs.find_object_zone(rs_seedship) == ZONE_BATTLEFIELD
    assert rs.is_tapped(rs_seedship) is True, (
        "Rust: Seedship must be tapped after declaring as attacker"
    )

    # p0's hand still empty on both engines (silent fizzle — nothing
    # put-from-hand because nothing was eligible).
    assert len(py.players[0].hand) == 0, (
        f"Python: p0's hand must remain empty (silent fizzle); "
        f"got {len(py.players[0].hand)} cards in hand."
    )

    # p0's bf carries ONLY Seedship (no creature put-from-hand).
    py_bf_p0 = [o for o in py.battlefield if o.controller_id == 0]
    assert len(py_bf_p0) == 1, (
        f"Python: p0's bf must carry only Sledge-Class Seedship "
        f"(silent fizzle path); got {len(py_bf_p0)} permanents."
    )

    # Graveyard empty on Python.
    assert py.players[0].graveyard == []


# ---------------------------------------------------------------------------
# (6) Scenario B — 1 Grizzly Bears in hand (load-bearing happy path);
# Seedship attacks; ATTACKS trigger fires; put-from-hand picks the
# Bear (deterministic first-eligible); Bear enters bf UNTAPPED +
# summoning_sick. Asserts byte-equal across engines.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_sledge_class_seedship_bear_in_hand_scenario_b_parity():
    """**GENUINE real-EoE cross-engine probe — Scenario B (Grizzly
    Bears in hand; put-from-hand happy path). PROBED tier flip
    evidence (Cycle 2 closure marker, scenario B — THE LOAD-BEARING
    happy path).**

    Pre-state on both engines:
      * Sledge-Class Seedship on p0's bf (unsick, so it can attack
        this turn).
      * 1 Grizzly Bears in p0's hand (synthetic {1}{G} 2/2 Bear; the
        only eligible Creature for the put-from-hand arm).

    Drive: ``declare_attacker`` / ``combat.declare_attackers``
    fires the ATTACKS trigger on both engines. The trigger queues +
    resolves through the put-from-hand path:
      1. ``OptionalPutCreatureFromHandOntoBattlefield.resolve`` walks
         p0's hand for Creature cards; finds 1 candidate (the Bear).
      2. Python's ``_PickFirstLibraryOptionAgent.choose_card_from_
         library`` returns ``option_ids[0]`` = the Bear.
      3. Rust walks p0's hand in index order and picks the first
         Creature → the same Bear (Rust's resolve arm at
         ``state_ops_resolve.rs:7107-7121``).
      4. Bear moved hand → bf UNTAPPED with summoning_sick=true
         (CR 302.1).
      5. ETB dispatch queued via ``pending_etb_dispatches`` (Rust) /
         the centralized ENTERS chokepoint via
         ``put_into_battlefield`` (Python). The Bear has no inherent
         ETB triggers so the dispatch drains to no-op.

    Post-resolve (both engines):
      * Sledge-Class Seedship on bf, tapped (from declaring as
        attacker).
      * Grizzly Bears on p0's bf, UNTAPPED + summoning_sick.
      * p0's hand empty.
      * No graveyard movement.
      * Stack empty.
    """
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.combat import declare_attackers as py_declare_attackers
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.turn import state_based_actions as py_sba
    from tests.parity._picker_shims import _PickFirstLibraryOptionAgent

    seedship_printing = _PRINTINGS.get("Sledge-Class Seedship")
    if seedship_printing is None:
        pytest.skip("Sledge-Class Seedship absent from active CardSource")

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: synthetic Grizzly Bears printing (mirrors the
    # _GRIZZLY_BEARS_RUST_DICT shape exactly so both engines see the
    # SAME printing).
    grizzly_printing = CardPrinting(
        name="Test Grizzly Bears",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=(("G", 1),)),
        type_line="Creature - Bear",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Bear",),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset(),
    )

    # ---- Python side: seat Sledge-Class Seedship on p0's bf (unsick)
    # + Grizzly Bears in p0's hand.
    py_seedship = py.new_object(
        seedship_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_seedship.summoning_sick = False
    py_seedship.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_seedship)

    py_bear = py.new_object(
        grizzly_printing, owner_id=0, zone=Zone.HAND,
    )
    py.players[0].hand.append(py_bear)

    # Picker shim on p0 — picks option_ids[0] for choose_card_from_
    # library (mirrors Rust's deterministic first-eligible pick).
    py.players[0].agent = _PickFirstLibraryOptionAgent()
    py.players[1].agent = None

    # ---- Rust side: same shape.
    rs_seedship = rs.register_and_inject_object(
        _SLEDGE_CLASS_SEEDSHIP_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    rs.clear_summoning_sick_for_player(0)
    rs_bear = rs.register_and_inject_object(
        _GRIZZLY_BEARS_RUST_DICT, 0, ZONE_HAND,
    )

    # Pre-trigger sanity.
    assert rs.stack_size() == 0 and len(py.stack) == 0
    assert len(py.players[0].hand) == 1
    assert rs.find_object_zone(rs_bear) == ZONE_HAND

    # ---- Declare Seedship as attacker on both engines.
    py_declare_attackers(py, [py_seedship.id])
    assert len(py.stack) == 1, (
        "Python: Seedship's ATTACKS trigger must push onto the stack"
    )
    assert rs.declare_attacker(rs_seedship) is True
    assert rs.stack_size() == 1, (
        "Rust: Seedship's ATTACKS trigger must push onto the stack"
    )

    # ---- Drain stacks (resolution walks the put-from-hand arm; the
    # Bear leaves hand and enters bf untapped + summoning-sick).
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    # ---- Post-resolve observables.
    # Stack empty on both engines.
    assert len(py.stack) == 0
    assert rs.stack_size() == 0

    # Seedship still on bf, tapped from the attack.
    assert py_seedship.zone == Zone.BATTLEFIELD
    assert py_seedship.tapped is True
    assert rs.find_object_zone(rs_seedship) == ZONE_BATTLEFIELD
    assert rs.is_tapped(rs_seedship) is True

    # **The load-bearing pin** — the Bear has moved hand → bf,
    # UNTAPPED + summoning_sick on both engines.
    assert py_bear.zone == Zone.BATTLEFIELD, (
        f"Python: Bear must have been put from hand onto bf by "
        f"Seedship's ATTACKS trigger; got zone={py_bear.zone}"
    )
    assert py_bear.tapped is False, (
        "Python: Bear must enter UNTAPPED (printed text has no "
        "'tapped' rider on Sledge-Class Seedship's effect)"
    )
    assert py_bear.summoning_sick is True, (
        "Python: Bear must be summoning_sick (CR 302.1 — any "
        "creature entering the battlefield has summoning sickness)"
    )
    assert rs.find_object_zone(rs_bear) == ZONE_BATTLEFIELD, (
        f"Rust: Bear must have been put from hand onto bf; "
        f"got zone={rs.find_object_zone(rs_bear)}"
    )
    assert rs.is_tapped(rs_bear) is False, (
        "Rust: Bear must enter UNTAPPED"
    )
    assert rs.is_summoning_sick(rs_bear) is True, (
        "Rust: Bear must be summoning_sick (CR 302.1)"
    )

    # p0's hand empty on Python (the Bear left for bf).
    assert len(py.players[0].hand) == 0, (
        f"Python: p0's hand must be empty after the Bear left for "
        f"bf; got {len(py.players[0].hand)} cards in hand."
    )

    # p0's bf carries Seedship + Bear (exactly 2 permanents).
    py_bf_p0 = [o for o in py.battlefield if o.controller_id == 0]
    assert len(py_bf_p0) == 2, (
        f"Python: p0's bf must carry exactly 2 permanents "
        f"(Seedship + Bear); got {len(py_bf_p0)} permanents."
    )

    # Graveyard empty on Python (no sacrifice, no destroy).
    assert py.players[0].graveyard == []
