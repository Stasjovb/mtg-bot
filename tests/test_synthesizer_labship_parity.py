"""Synthesizer Labship — per-card real-EoE cross-engine byte-equal
probe (``covered_by_construction`` → PROBED tier flip; Spacecraft
Station substrate Phase 3C Cycle 2 closure marker for Scenarios A+B
per design doc §6.4 #14).

Synthesizer Labship is a ``{U}`` Artifact — Spacecraft in the EoE
pool carrying the Phase-3C-Cycle-2 tier-gated single-trigger shape:

    Power/Toughness: 4/4
    Station threshold: 9
    Stationed keywords: flying, vigilance
    Triggered abilities: ONE BEGINNING_OF_COMBAT trigger —
        event = Event.BEGINNING_OF_COMBAT
        predicate = Controlled(by=YOU, subject=None)
        effect = TargetArtifactBecomesCreatureUEOT(
            power=2, toughness=2, granted_keywords=frozenset({"flying"}))
        tier_threshold = 2 (LOAD-BEARING — the FIRST consumer of the
            Phase-3C C1 tier-gate substrate; trigger fires only when
            the source's charge_counters >= 2)
        once_per_turn = False

Per design doc §3C, Synthesizer Labship is one of three carriers in
the Phase 3C admit set (Synthesizer Labship 3C-C2 + Entropic
Battlecruiser 3C-C3 + Infinite Guideline Station 3C-C4). The strict
admit predicate
:func:`mtg_bot.parity.trajectory._printing_is_bridge_phase_3_trigger_
spacecraft` positively rejects every non-Phase-3-A/B/C-Cycle-2
carrier (the §6.6 decline-set bench check pins this exhaustively in
``test_spacecraft_phase_3a_cycle_2_flip.py`` — Entropic Battlecruiser
has EachOpponentDiscardsOrLosesLife / TargetPlayerLosesLife effects;
Infinite Guideline Station has CreateTokenPerMulticoloredPermanent /
DrawCardPerMulticoloredPermanent effects — both stay DECLINED until
their C3 + C4 cycles ship).

**Multi-cycle DECLINED → ADMITTED → PROBED transition.**

  * **Phase 3C Cycle 1 (Rust substrate landing, commit ``ebc94a5c``,
    2026-05-26).** Rust substrate: new ``TriggeredAbility.tier_threshold:
    i32`` slot on ``cards.rs::TriggeredAbility`` + trigger-firing-time
    gate at ``state_ops_resolve.rs::dispatch_event`` chokepoint +
    cross-engine bridge dict-to-Python tier_threshold thread-through in
    ``cross_engine.py``. Synthesizer Labship STAYED DECLINED at every
    admit gate (substrate-only invariant).
  * **Phase 3C Cycle 2 (THE FLIP, this slice, 2026-05-26).** Combined
    Rust + Python cycle:
      - New ``Effect::TargetArtifactBecomesCreatureUEOT { power,
        toughness, granted_keywords }`` Rust variant on
        ``cards.rs::Effect`` + parse / to_pydict / resolve arms +
        cross-engine bridge dict-to-Python arm in ``cross_engine.py``.
      - Widen :data:`_PHASE_3A_SPACECRAFT_TRIGGER_EFFECT_CLASSES` to
        include ``TargetArtifactBecomesCreatureUEOT`` + widen
        :data:`_PHASE_3A_SPACECRAFT_TRIGGER_EVENT_SHAPES` to include
        ``(Event.BEGINNING_OF_COMBAT, Controlled(by=YOU, subject=None))``.
      - Per-card builder's matching BEGINNING_OF_COMBAT arm +
        Controlled(YOU) predicate dict + TargetArtifactBecomesCreatureUEOT
        Effect-dict-emit arm (threading the new ``tier_threshold`` slot
        positively when > 0).
    Synthesizer Labship DECLINED → ADMITTED (admit set 43 → 44; the
    FIFTH Spacecraft admit after Sawship + Lumen-Class Frigate +
    Larval Scoutlander + Sledge-Class Seedship).
  * **Phase 3C Cycle 2 (THIS LANE; THE PROBE — Scenarios A+B).**
    Per-card real-EoE cross-engine byte-equality probe driving BOTH
    engines through TWO scenarios across the CHARGE-COUNTER axis (the
    load-bearing tier-gate axis per design doc §6.4 #14):

    (A) **Tier-gate CLOSED (charge=1, below tier=2 threshold): trigger
        does NOT fire.** Synthesizer Labship on p0's bf (unsick) with
        ``charge_counters=1`` + a synthetic Lander artifact on p0's bf
        (the only eligible target). Drive the BEGINNING_OF_COMBAT
        dispatch on both engines; the tier-gate at
        ``state_ops_resolve.rs::dispatch_event`` (Rust) / Python's
        ``should_fire_trigger`` rejects the firing because
        ``charge_counters < tier_threshold``. The Lander stays a non-
        creature artifact with no granted keywords on both engines.

    (B) **Tier-gate OPEN (charge=2, at tier=2 threshold): trigger
        FIRES + UEOT animation lands on Lander.** Synthesizer Labship
        on p0's bf (unsick) with ``charge_counters=2`` + the same
        synthetic Lander artifact on p0's bf. Drive the BEGINNING_OF_
        COMBAT dispatch on both engines; the tier-gate now ADMITS the
        firing; the trigger queues + resolves through the new
        ``TargetArtifactBecomesCreatureUEOT`` arm; the Lander gains
        creature-now status + base P/T 2/2 + the "flying" keyword
        UEOT. Synthesizer Labship itself is UNAFFECTED (the "other"
        filter excludes it).

**Scripted-picker semantics.** The probe sets the picker shim on p0
to make Python deterministically pick the first eligible target.
Python's ``TargetArtifactBecomesCreatureUEOT.legal_targets`` returns
``[("permanent", lander.id)]`` (the one other artifact). The picker
returns option_ids[0] = the Lander. Rust's resolve arm walks the
source-controller's battlefield in iteration order and picks the
first artifact-not-source, which is also the Lander — keeping the
animation path byte-equal in Scenario B. In Scenario A the trigger
NEVER fires (tier-gate closed) so the picker is never invoked.

**Real-EoE-signal discipline.** This module uses the live
``OracleParserCardSource`` Synthesizer Labship printing on the Python
side AND the canonical Rust registry dict shape emitted by the C2
bridge forward arm
``_spec_card_to_printing_dict(_phase_3_trigger_spacecraft_card_def(
p))`` on the Rust side — the SAME printing shape both engines read
(verified pre-flight via the C2 substrate flip pins
``test_synthesizer_labship_admits_at_phase_3_admit_gate_post_cycle_2``
in test_spacecraft_phase_3c_substrate_cycle_1.py). The synthetic
Lander used as the target is a ``{0}`` non-creature artifact
(sibling shape to the TOKEN_PRINTINGS["Lander"] used at the existing
synthetic-Python test ``test_synthesizer_labship_animation.py``),
seated via the same ``register_and_inject_object`` shim used by every
cross-engine probe.

This module is the Spacecraft Phase 3C Cycle 2 closure marker; the
Phase-3C-Cycle-2 admit set is exhaustively pinned at Larval
Scoutlander (3A) + Sledge-Class Seedship (3B) + Synthesizer Labship
(3C-C2) post-Cycle-2.
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


# Phase constants (Rust int encoding; mirror of PHASE_BEGIN_COMBAT in
# rust/src/state_ops_steps.rs). The dispatch fires upon advance_phase
# entering this step.
PHASE_BEGIN_COMBAT = 4


# Canonical Rust dict for Synthesizer Labship — the EXACT shape
# ``_spec_card_to_printing_dict`` emits via the C2 forward arm
# ``_phase_3_trigger_spacecraft_card_def``. Both engines read this
# same printing shape (verified pre-flight via the C2 admit + builder
# pins in test_spacecraft_phase_3c_substrate_cycle_1.py — the
# `test_synthesizer_labship_admits_at_phase_3_admit_gate_post_cycle_2`
# pin threads the live printing through the builder + asserts the
# triggered_abilities tuple byte-equals this dict's triggered_abilities
# field).
_SYNTHESIZER_LABSHIP_RUST_DICT = {
    "name": "Synthesizer Labship",
    "card_types": ["Artifact"],
    "mana_cost": {"U": 1},
    "effects": [],
    "power": 4,
    "toughness": 4,
    "subtypes": ["Spacecraft"],
    "station_threshold": 9,
    "stationed_keywords": ["flying", "vigilance"],
    "triggered_abilities": [
        {
            "event": "beginning_of_combat",
            "predicate": {"kind": "controlled_by_you"},
            "effect": {
                "kind": "target_artifact_becomes_creature_ueot",
                "power": 2,
                "toughness": 2,
                "granted_keywords": ["flying"],
            },
            "tier_threshold": 2,
        },
    ],
}


# Canonical synthetic Lander Rust dict — a ``{0}`` non-creature
# artifact (the eligible target for the trigger).
_LANDER_RUST_DICT = {
    "name": "Test Lander",
    "card_types": ["Artifact"],
    "subtypes": ["Lander"],
    "mana_cost": {"generic": 0},
    "effects": [],
}


# ---------------------------------------------------------------------------
# (1) Parser SoT — Synthesizer Labship is parser-claimed and emits the
# expected Phase-3C-pilot shape (re-asserted here so this module is
# self-contained for the PROBED-tier evidence).
# ---------------------------------------------------------------------------


def test_synthesizer_labship_parser_claims_card():
    """Pins the active CardSource is producing the Synthesizer Labship
    printing under its canonical EoE name.
    """
    assert "Synthesizer Labship" in _PRINTINGS, (
        "Synthesizer Labship must be parser-claimed by the active "
        "CardSource (EoE set + reprint coverage)"
    )


def test_synthesizer_labship_printed_attrs():
    """Pins the basic printing surface: Artifact — Spacecraft, 4/4,
    cost ``{U}``, ``station_threshold=9``, stationed_keywords =
    ``{flying, vigilance}``, ONE BEGINNING_OF_COMBAT trigger with the
    canonical Phase-3C-Cycle-2 shape (the §2 teeth — the admit
    predicate's load-bearing gates).
    """
    p = _PRINTINGS["Synthesizer Labship"]
    assert p.card_types == ("Artifact",)
    assert "Spacecraft" in p.subtypes
    assert p.power == 4 and p.toughness == 4
    assert p.mana_cost.generic == 0
    assert ("U", 1) in p.mana_cost.colored
    assert p.station_threshold == 9
    assert p.stationed_keywords == frozenset({"flying", "vigilance"})
    # The §2 teeth — ONE trigger; zero static/activated; no warp /
    # spell_effect / loyalty / room_halves / cost_reductions.
    assert p.activated_abilities == ()
    assert p.static_abilities == ()
    assert p.spell_effect is None
    assert p.warp_cost is None
    assert p.keywords == frozenset()
    assert len(p.triggered_abilities) == 1
    (ta,) = p.triggered_abilities
    # Live shape pinned against the design doc §3C row.
    from mtg_bot.effects.generic.become_type import (
        TargetArtifactBecomesCreatureUEOT,
    )
    from mtg_bot.effects.predicates import Controlled, Event, YOU
    assert ta.event is Event.BEGINNING_OF_COMBAT
    assert isinstance(ta.predicate, Controlled)
    assert ta.predicate.by is YOU
    assert ta.predicate.subject is None
    assert isinstance(ta.effect, TargetArtifactBecomesCreatureUEOT)
    assert ta.effect.power == 2
    assert ta.effect.toughness == 2
    assert ta.effect.granted_keywords == frozenset({"flying"})
    # **LOAD-BEARING — the tier-gate substrate carrier.**
    assert ta.tier_threshold == 2, (
        "Synthesizer Labship's BEGINNING_OF_COMBAT trigger MUST carry "
        "tier_threshold=2 — this is the FIRST Phase-3 consumer of the "
        "Cycle-1 tier-gate substrate."
    )
    assert ta.once_per_turn is False


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the C2 forward arm
# ``_spec_card_to_printing_dict`` round-trip on the genuine parsed
# Synthesizer Labship printing through the new dedicated admit
# predicate. Pins the canonical Rust dict shape this probe drives both
# engines through.
# ---------------------------------------------------------------------------


def test_synthesizer_labship_bridge_round_trip_canonical_rust_dict():
    """The C2 admit-gate's bridge: Python printing →
    :func:`_phase_3_trigger_spacecraft_card_def` → CardDef →
    ``_spec_card_to_printing_dict`` → canonical Rust registry dict
    matches ``_SYNTHESIZER_LABSHIP_RUST_DICT`` byte-equal. Pins the
    probe's source-of-truth that both engines read the SAME printing
    shape.
    """
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _spec_card_to_printing_dict

    p_orig = _PRINTINGS["Synthesizer Labship"]
    cd = trajectory._phase_3_trigger_spacecraft_card_def(p_orig)
    assert cd is not None, (
        "Synthesizer Labship must pass the Phase-3C-Cycle-2 admit "
        "predicate post-FLIP"
    )
    pd = _spec_card_to_printing_dict(cd)
    # Compare modulo stationed_keywords list order (frozenset round-
    # trip is deterministic but the comparison should be order-
    # agnostic).
    pd_canon = dict(pd)
    pd_canon["stationed_keywords"] = sorted(pd["stationed_keywords"])
    expected = dict(_SYNTHESIZER_LABSHIP_RUST_DICT)
    expected["stationed_keywords"] = sorted(expected["stationed_keywords"])
    assert pd_canon == expected, (
        f"Synthesizer Labship Rust registry dict must match the probe's "
        f"pinned shape (the bridge SoT for both engines); got "
        f"pd_canon={pd_canon!r}, expected={expected!r}"
    )


# ---------------------------------------------------------------------------
# (3) Rust effect-arm parse smoke — the canonical Synthesizer Labship
# Rust dict parses on ``register_printing`` (the bridge contract Rust
# honors).
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_canonical_synthesizer_labship_dict():
    """Lockstep pin: Rust's parse arm accepts the canonical Synthesizer
    Labship registry-dict shape ``_SYNTHESIZER_LABSHIP_RUST_DICT`` — the
    SAME dict the C2 forward emit arm produces for the live Synthesizer
    Labship printing. Threading ``triggered_abilities`` with the new
    ``target_artifact_becomes_creature_ueot`` effect kind + the
    ``controlled_by_you`` predicate + ``beginning_of_combat`` event +
    ``tier_threshold=2`` round-trips byte-equal through
    ``Registry.register_printing``.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_SYNTHESIZER_LABSHIP_RUST_DICT)
    assert isinstance(pid, int)
    assert reg.get_printing_name(pid) == "Synthesizer Labship"


# ---------------------------------------------------------------------------
# (4) Loader end-to-end admit — Synthesizer Labship admits at the deck-
# level filter post-Cycle-2 (the FLIP marker mirror).
# ---------------------------------------------------------------------------


def test_synthesizer_labship_loader_end_to_end_admit():
    """End-to-end loader admit: pass ``["Synthesizer Labship"]`` to
    ``_filter_deck_to_bridge_supported`` → admitted; CardDef emitted
    carries the Phase-3C-Cycle-2 trigger shape with tier_threshold=2.
    """
    from mtg_bot.parity import trajectory
    filt, defs = trajectory._filter_deck_to_bridge_supported(
        ["Synthesizer Labship"], _PRINTINGS,
    )
    assert filt == ["Synthesizer Labship"]
    assert len(defs) == 1
    cd = defs[0]
    assert cd.name == "Synthesizer Labship"
    assert cd.triggered_abilities == (
        {
            "event": "beginning_of_combat",
            "predicate": {"kind": "controlled_by_you"},
            "effect": {
                "kind": "target_artifact_becomes_creature_ueot",
                "power": 2,
                "toughness": 2,
                "granted_keywords": ["flying"],
            },
            "tier_threshold": 2,
        },
    )


# ---------------------------------------------------------------------------
# (5) Scenario A — tier-gate CLOSED (charge=1, below tier=2). The
# BEGINNING_OF_COMBAT trigger does NOT fire on either engine; the
# Lander stays a non-creature artifact with no granted keywords.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_synthesizer_labship_tier_gate_closed_scenario_a_parity():
    """**GENUINE real-EoE cross-engine probe — Scenario A (tier-gate
    CLOSED, charge=1 < tier=2). PROBED tier flip evidence (Cycle 2
    closure marker, scenario A — the tier-gate-closed silent decline
    path).**

    Pre-state on both engines:
      * Synthesizer Labship on p0's bf (unsick) with
        ``charge_counters=1`` (one BELOW the tier_threshold=2 gate).
      * A synthetic Lander artifact on p0's bf (the eligible target).
      * Active phase advancing through into BEGIN_COMBAT.

    Drive: ``advance_phase`` to PHASE_BEGIN_COMBAT (Rust) /
    ``run_beginning_of_combat_triggers`` (Python) attempts to dispatch
    the BEGINNING_OF_COMBAT event. The C1 tier-gate at Rust's
    ``state_ops_resolve.rs::dispatch_event`` chokepoint sees
    ``tier_threshold=2`` AND ``source.charge_counters=1 < 2`` and
    SKIPS the firing (skip via the ``_ => continue`` arm in the
    tier-gate match). Python's
    ``mtg_bot.turn.should_fire_trigger`` enforces the SAME gate
    semantics. NEITHER engine pushes the trigger onto the stack.

    Post-resolve (both engines):
      * Stack empty.
      * Lander is NOT a creature; has no flying.
      * Synthesizer Labship still has charge_counters=1.
    """
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import (
        Zone, effective_keywords, is_creature_now,
    )
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.turn import Step, run_beginning_of_combat_triggers

    syn_printing = _PRINTINGS.get("Synthesizer Labship")
    if syn_printing is None:
        pytest.skip("Synthesizer Labship absent from active CardSource")

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python side: seat Synthesizer Labship on p0's bf, unsick,
    # charge_counters=1 (BELOW tier=2).
    py_syn = py.new_object(
        syn_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_syn.summoning_sick = False
    py_syn.charge_counters = 1
    py_syn.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_syn)
    # Seat a synthetic Lander artifact (non-creature, no riders) on
    # p0's bf. We use a CardPrinting directly to mirror the Rust
    # printing dict exactly.
    from mtg_bot.cards.base import CardPrinting, ManaCost
    lander_printing = CardPrinting(
        name="Test Lander",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=()),
        type_line="Artifact - Lander",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=("Lander",),
        power=None,
        toughness=None,
        produces=frozenset(),
        keywords=frozenset(),
    )
    py_lander = py.new_object(
        lander_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_lander.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_lander)
    py.active_player_idx = 0
    py.priority_player_idx = 0
    py.step = Step.BEGINNING_OF_COMBAT
    # No agent needed — Scenario A's trigger never fires so no target
    # pick is requested.
    py.players[0].agent = None
    py.players[1].agent = None

    # ---- Rust side: same shape via register_and_inject_object +
    # charge counter setter.
    rs_syn = rs.register_and_inject_object(
        _SYNTHESIZER_LABSHIP_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    rs.clear_summoning_sick_for_player(0)
    rs.set_charge_counters(rs_syn, 1)
    rs_lander = rs.register_and_inject_object(
        _LANDER_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    # Advance Rust's phase to BEGIN_COMBAT directly. set_phase only
    # writes the slot; we then call dispatch_event manually to mirror
    # advance_phase's BEGINNING_OF_COMBAT fire site (which would
    # otherwise also do mana-pool / untap / priority swap side
    # effects we don't want in the probe). The fire site is the
    # SAME ``dispatch_event(state, Event::BeginningOfCombat,
    # player_subject)`` call that advance_phase performs at line
    # 693 of state_ops_steps.rs — the tier-gate is at the dispatch
    # site, NOT at the advance_phase call site, so the parity is
    # preserved.
    rs.set_phase(PHASE_BEGIN_COMBAT)
    rs.dispatch_beginning_of_combat()

    # ---- Drive the Python side's trigger dispatch (no-op on closed
    # gate).
    run_beginning_of_combat_triggers(py)
    # ---- Drain (no-op on either side since the trigger never queued).
    while py.stack:
        resolve_top_of_stack(py)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    # ---- Post-resolve observables.
    # Stack empty on both engines (tier-gate closed → no fire).
    assert len(py.stack) == 0, (
        f"Python: tier-gate CLOSED — stack must be empty (no trigger "
        f"fired); got stack={py.stack!r}"
    )
    assert rs.stack_size() == 0, (
        f"Rust: tier-gate CLOSED — stack must be empty (no trigger "
        f"fired); got stack_size={rs.stack_size()!r}"
    )

    # Lander is still a non-creature artifact on both engines.
    assert not is_creature_now(py_lander), (
        "Python: Lander must NOT be a creature (tier-gate closed → no "
        "animation)"
    )
    assert "flying" not in effective_keywords(py, py_lander), (
        "Python: Lander must NOT have flying (tier-gate closed → no "
        "keyword grant)"
    )
    # Rust: ueot_modifier_count(lander) == 0 — no SetBasePT /
    # BecomesLandCreature / GrantKeyword pushes.
    assert rs.ueot_modifier_count(rs_lander) == 0, (
        f"Rust: Lander must carry zero UEOT modifiers (tier-gate "
        f"closed → no animation); got "
        f"{rs.ueot_modifier_count(rs_lander)} modifiers"
    )
    # Synthesizer Labship's charge_counters unchanged on both engines.
    assert py_syn.charge_counters == 1, (
        f"Python: Synthesizer Labship's charge_counters must remain 1 "
        f"(no mutation); got {py_syn.charge_counters}"
    )
    assert rs.get_charge_counters(rs_syn) == 1, (
        f"Rust: Synthesizer Labship's charge_counters must remain 1 "
        f"(no mutation); got {rs.get_charge_counters(rs_syn)}"
    )


# ---------------------------------------------------------------------------
# (6) Scenario B — tier-gate OPEN (charge=2, at tier=2). The trigger
# FIRES + resolves + the Lander gains creature-now status + base P/T
# 2/2 + the "flying" keyword UEOT.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_synthesizer_labship_tier_gate_open_scenario_b_parity():
    """**GENUINE real-EoE cross-engine probe — Scenario B (tier-gate
    OPEN, charge=2 == tier=2). PROBED tier flip evidence (Cycle 2
    closure marker, scenario B — THE LOAD-BEARING tier-gate-open
    animation path; proves the C1 tier-gate substrate FIRES correctly
    under real charge counters).**

    Pre-state on both engines:
      * Synthesizer Labship on p0's bf (unsick) with
        ``charge_counters=2`` (AT the tier_threshold=2 gate — exactly
        the load-bearing >= threshold case).
      * A synthetic Lander artifact on p0's bf (the eligible target).
      * Active phase advancing through into BEGIN_COMBAT.

    Drive: ``run_beginning_of_combat_triggers`` (Python) /
    ``dispatch_beginning_of_combat`` (Rust) dispatches the
    BEGINNING_OF_COMBAT event. The C1 tier-gate at Rust's
    ``state_ops_resolve.rs::dispatch_event`` sees
    ``tier_threshold=2`` AND ``source.charge_counters=2 >= 2`` and
    ADMITS the firing. Python's ``should_fire_trigger`` enforces the
    SAME gate. BOTH engines push the trigger onto the stack. The
    trigger resolves through the new
    ``TargetArtifactBecomesCreatureUEOT`` arm:
      1. Source-controller resolution.
      2. Target selection: legal_targets returns
         [("permanent", lander.id)] (the only other artifact). The
         picker shim deterministically picks the first.
      3. UEOT modifiers pushed onto the Lander:
         - Rust: ``UeotModifier::BecomesLandCreature { power=2,
           toughness=2, color_or_subtype: "" }`` (base P/T set + the
           is-creature-now flag) + one ``UeotModifier::GrantKeyword
           { keyword: "flying" }``.
         - Python: ``ApplyEffect(BecomeType(types=("creature",),
           base_pt=(2,2)), EndOfTurn)`` + ``ApplyEffect(GrantKeywords
           ({flying}), EndOfTurn)`` (the layer-4 add_type "creature"
           + layer-7 set_base_pt + layer-6 grant_keyword registry
           writes).

    Post-resolve (both engines):
      * Stack empty.
      * Lander IS a creature now (UEOT animation active).
      * Lander has effective_power=2 + effective_toughness=2 + flying.
      * Synthesizer Labship is UNAFFECTED (the "other" filter excluded
        it from being a legal target).
    """
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.agents import Agent
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import (
        Zone, effective_keywords, effective_power, effective_toughness,
        is_creature_now,
    )
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.turn import Step, run_beginning_of_combat_triggers

    syn_printing = _PRINTINGS.get("Synthesizer Labship")
    if syn_printing is None:
        pytest.skip("Synthesizer Labship absent from active CardSource")

    class _PickFirstTarget(Agent):
        """Picks the first legal target — deterministic first-eligible
        mirror of Rust's source-controller-bf first-artifact scan."""

        def choose_target(self, state, player_id, legal_targets):
            return legal_targets[0] if legal_targets else None

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python side: seat Synthesizer Labship on p0's bf, unsick,
    # charge_counters=2 (AT tier=2 — gate OPEN).
    py_syn = py.new_object(
        syn_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_syn.summoning_sick = False
    py_syn.charge_counters = 2
    py_syn.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_syn)
    # Synthetic Lander artifact.
    lander_printing = CardPrinting(
        name="Test Lander",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=()),
        type_line="Artifact - Lander",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=("Lander",),
        power=None,
        toughness=None,
        produces=frozenset(),
        keywords=frozenset(),
    )
    py_lander = py.new_object(
        lander_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_lander.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_lander)
    py.active_player_idx = 0
    py.priority_player_idx = 0
    py.step = Step.BEGINNING_OF_COMBAT
    # Pre-state assertion — Lander is not a creature.
    assert not is_creature_now(py_lander)
    assert "flying" not in effective_keywords(py, py_lander)
    # Picker shim on p0 — picks legal_targets[0] for choose_target.
    py.players[0].agent = _PickFirstTarget()
    py.players[1].agent = None

    # ---- Rust side: same shape via register_and_inject_object +
    # charge counter setter.
    rs_syn = rs.register_and_inject_object(
        _SYNTHESIZER_LABSHIP_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    rs.clear_summoning_sick_for_player(0)
    rs.set_charge_counters(rs_syn, 2)
    rs_lander = rs.register_and_inject_object(
        _LANDER_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    # Pre-state Rust: Lander has zero UEOT modifiers + is not a
    # creature via UEOT.
    assert rs.ueot_modifier_count(rs_lander) == 0
    # Pre-trigger stacks empty.
    assert rs.stack_size() == 0 and len(py.stack) == 0

    # ---- Drive: BEGINNING_OF_COMBAT dispatch on both engines.
    run_beginning_of_combat_triggers(py)
    # Python: the trigger pushed onto the stack (gate OPEN).
    assert len(py.stack) == 1, (
        f"Python: tier-gate OPEN — trigger MUST push onto the stack; "
        f"got stack={py.stack!r}"
    )

    rs.set_phase(PHASE_BEGIN_COMBAT)
    rs.dispatch_beginning_of_combat()
    # Rust: the trigger pushed onto the stack (gate OPEN).
    assert rs.stack_size() == 1, (
        f"Rust: tier-gate OPEN — trigger MUST push onto the stack; "
        f"got stack_size={rs.stack_size()!r}"
    )

    # ---- Drain stacks (trigger resolves through the new
    # TargetArtifactBecomesCreatureUEOT arm).
    while py.stack:
        resolve_top_of_stack(py)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    # ---- Post-resolve observables (the load-bearing pins).
    # Stack empty on both engines.
    assert len(py.stack) == 0
    assert rs.stack_size() == 0

    # **Python: Lander is now a 2/2 flying creature UEOT.**
    assert is_creature_now(py_lander), (
        "Python: Lander MUST be a creature now (UEOT animation by "
        "Synthesizer Labship's tier-2 trigger)"
    )
    assert effective_power(py, py_lander) == 2, (
        f"Python: Lander effective_power must be 2 (base P/T set); "
        f"got {effective_power(py, py_lander)}"
    )
    assert effective_toughness(py, py_lander) == 2, (
        f"Python: Lander effective_toughness must be 2 (base P/T set); "
        f"got {effective_toughness(py, py_lander)}"
    )
    assert "flying" in effective_keywords(py, py_lander), (
        "Python: Lander MUST have flying (UEOT keyword grant)"
    )

    # **Rust: Lander carries the UEOT modifiers — 1 BecomesLandCreature
    # (layer-7B P/T set + creature-now flag) + 1 GrantKeyword (flying).
    # Total = 2 UEOT modifiers.**
    assert rs.ueot_modifier_count(rs_lander) == 2, (
        f"Rust: Lander MUST carry exactly 2 UEOT modifiers "
        f"(BecomesLandCreature + GrantKeyword(flying)); got "
        f"{rs.ueot_modifier_count(rs_lander)}"
    )
    # **Effective P/T from the BecomesLandCreature modifier**
    # (`ueot_becomes_land_creature_pt` gives the base, then layer 7c
    # additive bonuses stack on top — none in this scenario, so the
    # effective is the base).
    assert rs.effective_power(rs_lander) == 2, (
        f"Rust: Lander effective_power must be 2; got "
        f"{rs.effective_power(rs_lander)}"
    )
    assert rs.effective_toughness(rs_lander) == 2, (
        f"Rust: Lander effective_toughness must be 2; got "
        f"{rs.effective_toughness(rs_lander)}"
    )
    # **Flying keyword grant honored via UeotModifier::GrantKeyword.**
    assert rs.has_keyword(rs_lander, "flying"), (
        "Rust: Lander MUST have flying (UEOT GrantKeyword grant)"
    )

    # Synthesizer Labship is UNAFFECTED on both engines (the "other"
    # filter excluded it from being a legal target).
    assert py_syn.charge_counters == 2  # no mutation
    assert rs.get_charge_counters(rs_syn) == 2  # no mutation
    # Synthesizer Labship carries zero UEOT modifiers (it wasn't a
    # target — the "other" filter excluded it).
    assert rs.ueot_modifier_count(rs_syn) == 0, (
        f"Rust: Synthesizer Labship MUST carry zero UEOT modifiers "
        f"(the 'other' filter excluded it from being a target); got "
        f"{rs.ueot_modifier_count(rs_syn)}"
    )
