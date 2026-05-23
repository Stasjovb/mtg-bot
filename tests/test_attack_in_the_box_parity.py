"""Cross-engine parity probes for Attack-in-the-Box.

**Attack-in-the-Box Cycle 1 closure (2026-05-23).** ``{3}`` Artifact
Creature — Toy, 2/4 (DSK — sourced from ``data/duskmourn.json``). Attack
trigger body: "Whenever this creature attacks, you may have it get
+4/+0 until end of turn. If you do, sacrifice it at the beginning of
the next end step."

The parser composes the body (``cards/parser/effects.py:3903-3912``)
as ``IfYouDo(MayDo(PumpSelfUntilEOT(+4/+0)),
ScheduleSelfSacAtNextEndStep())``: ``MayDo`` gates the pump on the
controller's ``choose_yes_no``, ``IfYouDo`` fires the sac schedule only
when the pump landed, and ``ScheduleSelfSacAtNextEndStep`` schedules a
delayed ``SacrificeSourceDelayed`` keyed at the current turn.

This cycle ports the ``ScheduleSelfSacAtNextEndStep`` substrate to Rust
(``Effect::ScheduleSelfSacAtNextEndStep`` — field-free unit variant;
parser arm round-trips the bare ``{"kind":
"schedule_self_sac_at_next_end_step"}`` dict shape; resolve arm in
``state_ops_resolve.rs`` appends a ``DelayedTrigger {effect:
SacrificeSourceDelayed, source_id: source_obj_id, fire_at_turn:
state.turn_number, controller_id}`` onto ``state.delayed_triggers``).
Composes with the existing ``Effect::SacrificeSourceDelayed`` substrate
(landed in Devastating Onslaught Cycle 1, ``cards.rs:6328``) — the
delayed trigger's body re-walks both bfs for the source and sacrifices
it via the CR 400.7 reset + graveyard push path.

**Multi-gated card; classifier stays multi-gated.** Per the round-58
subsystem-attribution classifier (``scripts/scout_r58_subsystem_
attribution.py``), Attack-in-the-Box is multi-gated:

  * ``effect_uncovered`` — closed by this cycle. The new Rust variant
    ``Effect::ScheduleSelfSacAtNextEndStep`` makes the Python class
    ``ScheduleSelfSacAtNextEndStep`` covered via the 1:1 identity-
    mapping rule in ``effect_coverage.map_rust_to_python``; the
    classifier's ``missing_effect_classes`` array shrinks by one for
    this card.
  * ``nonsafe_triggered_ability`` — **STAYS active**. The trajectory
    safe-trigger admit gate (``parity/trajectory.py::
    _python_ta_to_safe_dict``) is INTENTIONALLY NOT widened — same
    per-card real-EoE probe precedent as Comet Crawler / Dyadrine
    Attack / Mutinous Massacre / Boilerbilges Ripper / Fanatic of
    the Harrowing / Terrapact Intimidator. The trajectory-side
    bench admit set is a distinct concern from per-card real-EoE
    parity probes.

**Per-card dedicated parity probe path (PROBED tier flip).** Even
though the classifier keeps the card multi-gated at
``nonsafe_triggered_ability``, this test module is the dedicated
per-card real-EoE byte-equal cross-engine probe that flips Attack-in-
the-Box to PROBED tier. Same precedent as
``test_boilerbilges_ripper_parity.py``,
``test_fanatic_of_the_harrowing_parity.py``,
``test_terrapact_intimidator_parity.py``,
``test_comet_crawler_parity.py``, ``test_dyadrine_attack.py``, and
``test_mutinous_massacre_parity.py``: a per-card probe drives the
real printing through both engines and pins byte-equal observables;
the safe-trigger bench admit set is widened in a separate cycle when
the production-deck bench needs it.

**NOT a spell-card-bridge admit-set extension.** Attack-in-the-Box is
an Artifact Creature, not a non-creature spell. The spell-card-bridge
admit set (``trajectory.py::_python_spell_effect_to_dict`` + its §2
teeth) gates non-creature spells only. The per-card probe approach is
the right tool here, exactly the Comet Crawler / Mutinous Massacre /
Dyadrine Attack / Boilerbilges Ripper / Fanatic of the Harrowing /
Terrapact Intimidator convention.

**Cycle 1 scope — substrate landing.** This cycle lands ONLY the
``ScheduleSelfSacAtNextEndStep`` substrate (Rust variant + parse +
to_pydict + resolve + cross-engine bridge + per-leaf serializer). The
full parent-composition byte-equal probe through the agent-driven
``IfYouDo(MayDo(PumpSelfUntilEOT), ScheduleSelfSac...)`` cluster
requires driving both engines through ``submit_may_do_decision`` +
``submit_if_you_do_decision`` (or their no-agent auto-resolve
defaults) — the cross-engine harness's agent surface for those
decisions is honest-stopped today (see ``docs/SEARCH_LIMITATIONS.md``
— Attack-in-the-Box Cycle 1 entry).

Coverage:

- Parser SoT pin: the live parser maps Attack-in-the-Box's attack
  trigger to ``IfYouDo(do_action=MayDo(PumpSelfUntilEOT(+4/+0)),
  then_action=ScheduleSelfSacAtNextEndStep())``.
- Serializer round-trip: dict→Python via ``_ta_dict_to_python_effect``
  rebuilds ``ScheduleSelfSacAtNextEndStep()``; Rust
  ``Effect::ScheduleSelfSacAtNextEndStep`` → dict via
  ``Registry.get_printing_etb_effects`` emits the expected one-key
  dict shape.
- Effect-coverage class pin: ``ScheduleSelfSacAtNextEndStep`` is in
  the covered-by-rust set after this cycle (1:1 identity-mapping rule).
- Rust resolve-arm unit pins:
    * Schedules a ``SacrificeSourceDelayed`` delayed trigger keyed at
      the current turn with ``source_id == source_obj_id``,
      ``controller_id == source's controller``,
      ``effect_kind == "sacrifice_source_delayed"``.
    * End-step drain triggers the sacrifice: after advancing the
      phase to END_STEP, the source is removed from the battlefield
      and pushed onto its controller's graveyard.
- **GENUINE real-EoE cross-engine byte-equal probe** drives the
  parsed Attack-in-the-Box printing through BOTH engines's
  ``trajectory._python_spell_effect_to_dict`` →
  ``cross_engine._ta_dict_to_python_effect`` round-trip surface, and
  through the directly-applied schedule + drain observable.
"""

from __future__ import annotations

import importlib
import importlib.util
import pathlib
import sys

import pytest


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3


# -------------------------------------------------------------------
# Verify-first: parser SoT pin.
# -------------------------------------------------------------------


def test_real_attack_in_the_box_attack_trigger_is_ifyoudo_compound():
    """**Verify-first.** The live parser maps Attack-in-the-Box's
    attack trigger to ``IfYouDo(MayDo(PumpSelfUntilEOT(+4/+0)),
    ScheduleSelfSacAtNextEndStep())``. Pin the shape so a parser drift
    is caught here, not silently downstream in the cross-engine
    probe."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.combinators import IfYouDo, MayDo
    from mtg_bot.effects.generic import (
        PumpSelfUntilEOT, ScheduleSelfSacAtNextEndStep,
    )
    from mtg_bot.effects.predicates import Event

    p = get_active_source().get_printings().get("Attack-in-the-Box")
    if p is None:
        pytest.skip("Attack-in-the-Box absent from active CardSource")
    assert "Artifact" in p.card_types
    assert "Creature" in p.card_types
    assert p.power == 2
    assert p.toughness == 4
    # Single ATTACKS triggered ability.
    attack_tas = [
        ta for ta in p.triggered_abilities if ta.event is Event.ATTACKS
    ]
    assert len(attack_tas) == 1, (
        f"Attack-in-the-Box must have exactly 1 ATTACKS triggered "
        f"ability; got {len(attack_tas)}"
    )
    ta = attack_tas[0]
    assert isinstance(ta.effect, IfYouDo), (
        f"attack trigger effect must be IfYouDo; got "
        f"{type(ta.effect).__name__}"
    )
    assert isinstance(ta.effect.do_action, MayDo), (
        f"IfYouDo.do_action must be MayDo; got "
        f"{type(ta.effect.do_action).__name__}"
    )
    inner = ta.effect.do_action.inner
    assert isinstance(inner, PumpSelfUntilEOT), (
        f"MayDo.inner must be PumpSelfUntilEOT; got "
        f"{type(inner).__name__}"
    )
    assert inner.power_bonus == 4
    assert inner.toughness_bonus == 0
    assert isinstance(ta.effect.then_action, ScheduleSelfSacAtNextEndStep), (
        f"IfYouDo.then_action must be ScheduleSelfSacAtNextEndStep; "
        f"got {type(ta.effect.then_action).__name__}"
    )
    # Field-free unit dataclass — equality with a fresh
    # default-constructed instance.
    assert ta.effect.then_action == ScheduleSelfSacAtNextEndStep()


# -------------------------------------------------------------------
# Serializer round-trip pins.
# -------------------------------------------------------------------


def test_schedule_self_sac_serializer_round_trip():
    """Python ``ScheduleSelfSacAtNextEndStep()`` →
    ``trajectory._python_spell_effect_to_dict`` emits the bare unit-
    variant dict ``{"kind": "schedule_self_sac_at_next_end_step"}``;
    ``cross_engine._ta_dict_to_python_effect`` reconstructs the
    default-constructed instance. Bridge arm is the lever flip —
    without it, a Rust→Python triggered-ability translation would
    raise on the unknown kind."""
    from mtg_bot.effects.generic import ScheduleSelfSacAtNextEndStep
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    d = trajectory._python_spell_effect_to_dict(
        ScheduleSelfSacAtNextEndStep()
    )
    assert d == {"kind": "schedule_self_sac_at_next_end_step"}, (
        f"ScheduleSelfSacAtNextEndStep reverse serializer must emit "
        f"the bare unit-variant dict; got {d}"
    )
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, ScheduleSelfSacAtNextEndStep), (
        f"dict→Python bridge must round-trip to "
        f"ScheduleSelfSacAtNextEndStep; got {type(rebuilt).__name__}"
    )
    # Field-free unit dataclass; equality with a fresh instance.
    assert rebuilt == ScheduleSelfSacAtNextEndStep()


def test_schedule_self_sac_rust_effect_to_pydict_round_trip():
    """Rust ``Effect::ScheduleSelfSacAtNextEndStep`` → dict emits the
    expected one-key shape. Drives the round-trip through
    ``Registry.register_printing`` (the parse path) +
    ``get_printing_etb_effects`` (the ``effect_to_pydict`` readback).
    Using ``etb_effects`` instead of ``triggered_abilities`` because
    the Registry exposes an ``effect_to_pydict``-walking getter for
    the former but not the latter; the parse + serialize arms being
    exercised are identical (both walk ``parse_effect`` then
    ``effect_to_pydict`` on the same ``Effect`` variant)."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Schedule Self Sac Round-trip",
            "card_types": ["Artifact", "Creature"],
            "power": 2,
            "toughness": 2,
            "mana_cost": {"generic": 3},
            "etb_effects": [
                {"kind": "schedule_self_sac_at_next_end_step"},
            ],
        }
    )
    effs = reg.get_printing_etb_effects(pid)
    assert len(effs) == 1, f"expected 1 etb_effect, got {len(effs)}"
    eff = effs[0]
    assert eff["kind"] == "schedule_self_sac_at_next_end_step"
    # Field-free unit variant — no other keys.
    assert set(eff.keys()) == {"kind"}, (
        f"unit-variant to_pydict must emit ONLY 'kind'; got keys "
        f"{sorted(eff.keys())}"
    )


def test_schedule_self_sac_class_covered_by_rust():
    """``ScheduleSelfSacAtNextEndStep`` must be in the covered-by-
    rust set — the Rust ``Effect::ScheduleSelfSacAtNextEndStep``
    variant declaration makes ``covered_python_class_set()`` include
    it via the 1:1 identity-mapping rule in
    ``effect_coverage.map_rust_to_python``. This is the §2 covered-set
    tooth (parity-doc / coverage-script "covered" alignment) AND the
    closure of the classifier's ``effect_uncovered`` gate for
    Attack-in-the-Box."""
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    covered = covered_python_class_set()
    assert "ScheduleSelfSacAtNextEndStep" in covered, (
        "Rust Effect::ScheduleSelfSacAtNextEndStep variant must make "
        "the Python ScheduleSelfSacAtNextEndStep class covered via "
        "the 1:1 identity-mapping rule"
    )


# -------------------------------------------------------------------
# Rust resolve-arm unit pins — schedule a delayed SacrificeSourceDelayed
# trigger at the current turn, then drain it at PHASE_END_STEP entry
# and verify the sacrifice.
# -------------------------------------------------------------------


def _fresh_rust_state():
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


_BOX_LIKE_PRINTING_DICT: dict = {
    "name": "Attack-in-the-Box Probe Source",
    "card_types": ["Artifact", "Creature"],
    "power": 2,
    "toughness": 4,
    "mana_cost": {"generic": 3},
    # Synthetic shape — the "effects" list is the spell_effect list
    # the cast-pipeline resolves on push_to_stack+resolve_top_of_stack.
    # The real Attack-in-the-Box composes this Effect under
    # `IfYouDo(MayDo(PumpSelfUntilEOT), ScheduleSelfSac...)`, which
    # requires driving `submit_may_do_decision` + `submit_if_you_do_
    # decision` (agent surface, honest-stopped today). The substrate
    # unit pin exercises the SCHEDULE arm directly by driving the
    # Effect through the spell-resolution pipeline — same shape as
    # `test_devastating_onslaught_parity.py:_build_rust_devastating_
    # onslaught_state` uses for `SacrificeSourceDelayed`.
    "effects": [
        {"kind": "schedule_self_sac_at_next_end_step"},
    ],
}


def test_rust_resolve_schedules_sacrifice_source_delayed_at_current_turn():
    """Rust pin (a): On resolve, ``Effect::ScheduleSelfSacAtNextEndStep``
    appends a ``DelayedTrigger`` onto ``state.delayed_triggers`` with:

      * ``fire_at_turn == state.turn_number`` (current turn's end step
        — the "next end step on the current turn" interpretation
        matches Devastating Onslaught's per-token sac scheduling and
        Python's ``ScheduleSelfSacAtNextEndStep.resolve`` at
        ``effects/generic/delayed_actions.py:99-104``).
      * ``controller_id == 0`` (the caster — read off
        ``current_resolve_source_controller`` with active-player
        fallback).
      * ``source_id == box_id`` (the resolving source's id).
      * ``effect_kind == "sacrifice_source_delayed"`` (the composed
        leaf — the actual end-step trigger body).

    The source stays on the battlefield untouched; the schedule lands
    in the delayed-trigger Vec.
    """
    rs = _fresh_rust_state()
    # Inject the source on p0's BATTLEFIELD so the end-step drain can
    # find it later. Real Attack-in-the-Box's trigger fires from the
    # ATTACKS event with the source already on bf — mirror that
    # state shape here.
    box_id = rs.register_and_inject_object(
        _BOX_LIKE_PRINTING_DICT, 0, ZONE_BATTLEFIELD,
    )
    turn_at_cast = rs.turn_number
    delayed_before = rs.delayed_trigger_count

    # Push the schedule onto the stack as a spell whose source is the
    # injected source object. The cast-pipeline resolve fires the
    # `Effect::ScheduleSelfSacAtNextEndStep` arm with
    # `source_obj_id == box_id`.
    rs.push_to_stack(box_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, "schedule must resolve cleanly"

    # Exactly one new delayed-trigger entry.
    delayed_after = rs.delayed_trigger_count
    assert delayed_after - delayed_before == 1, (
        f"ScheduleSelfSacAtNextEndStep must add exactly 1 delayed "
        f"trigger; delayed count went {delayed_before} → "
        f"{delayed_after}"
    )

    # Inspect the schedule entry and pin its shape.
    schedules = rs.delayed_triggers_snapshot()
    new_entry = schedules[-1]
    assert new_entry["fire_at_turn"] == turn_at_cast, (
        f"fire_at_turn must equal turn_at_cast ({turn_at_cast}); "
        f"got {new_entry['fire_at_turn']}"
    )
    assert new_entry["controller_id"] == 0, (
        f"controller_id must be the caster (0); got "
        f"{new_entry['controller_id']}"
    )
    assert new_entry["source_id"] == box_id, (
        f"source_id must be the resolving source id ({box_id}); got "
        f"{new_entry['source_id']}"
    )
    assert new_entry["effect_kind"] == "sacrifice_source_delayed", (
        f"effect_kind must be sacrifice_source_delayed; got "
        f"{new_entry['effect_kind']}"
    )

    # Source still on bf — the schedule doesn't sacrifice yet.
    bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert box_id in bf_ids, (
        "schedule must NOT sacrifice the source immediately — the "
        "sac fires only when the delayed trigger drains at end step"
    )


def test_rust_end_step_drain_sacrifices_source():
    """Rust pin (b): After advancing the phase to ``PHASE_END_STEP``,
    the scheduled ``SacrificeSourceDelayed`` trigger is pushed onto
    the stack and resolves into the sacrifice — the source moves from
    battlefield → graveyard. Mirrors Python's ``run_delayed_end_step_
    triggers`` (``turn.py``) at end-step entry composed with the
    ``SacrificeSourceDelayed.resolve`` body (``effects/generic/
    delayed_actions.py:43-61``).

    End-step drain pins the composed schedule+drain pipeline byte-
    equal across engines: schedule at resolve time → fire at end step
    → sacrifice. Same drain machinery Devastating Onslaught uses for
    its per-token end-step sacs.
    """
    rs = _fresh_rust_state()
    box_id = rs.register_and_inject_object(
        _BOX_LIKE_PRINTING_DICT, 0, ZONE_BATTLEFIELD,
    )
    # Schedule the delayed sac on the current turn.
    rs.push_to_stack(box_id, 0)
    rs.resolve_top_of_stack()
    assert rs.delayed_trigger_count == 1, (
        "schedule must land exactly 1 delayed trigger"
    )

    # Advance phases until we reach PHASE_END_STEP (phase 10). The
    # synthetic state starts in PHASE_UNTAP (0). Skip ahead via
    # set_phase to avoid the cleanup-wrap rolling the active player.
    # Real Attack-in-the-Box scheduling happens during the attacker's
    # turn (declaring attacker → ATTACKS event); the same active
    # player still has the upcoming end step on the SAME turn.
    rs.set_phase(9)         # MAIN2
    rs.advance_phase()      # → END_STEP (phase 10): delayed trigger
                            #   onto stack
    assert rs.current_phase() == 10, (
        f"phase must be END_STEP (10); got {rs.current_phase()}"
    )

    # The end-step drain must have pushed the SacrificeSourceDelayed
    # trigger onto the stack as a real triggered ability.
    assert rs.stack_size() == 1, (
        f"end-step drain must push exactly 1 delayed trigger onto "
        f"the stack; got stack size {rs.stack_size()}"
    )

    # The schedule has been drained out of `delayed_triggers`.
    assert rs.delayed_trigger_count == 0, (
        f"end-step drain must consume the delayed trigger from "
        f"`delayed_triggers`; got {rs.delayed_trigger_count} "
        f"residual entries"
    )

    # Resolve the triggered ability → SacrificeSourceDelayed body
    # runs → source moves bf → graveyard.
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, (
        "SacrificeSourceDelayed must resolve cleanly off the stack"
    )

    # Source no longer on battlefield.
    bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert box_id not in bf_ids, (
        f"source must be sacrificed off bf at end step; got bf ids "
        f"{bf_ids}"
    )
    # Source is in p0's graveyard.
    gy_ids = [e["id"] for e in rs.graveyard_snapshot(0)]
    assert box_id in gy_ids, (
        f"sacrificed source must land in controller's graveyard; "
        f"got p0 gy ids {gy_ids}"
    )


# -------------------------------------------------------------------
# GENUINE real-EoE cross-engine byte-equal probe — drives the parsed
# Attack-in-the-Box printing through the trajectory →
# _ta_dict_to_python_effect round-trip pipeline. Cycle 1's substrate
# scope: the full IfYouDo(MayDo(...)) parent composition's agent-
# driven branching is honest-stopped (no agent surface for Rust's
# MayDo / IfYouDo decisions today). The probe verifies the
# `ScheduleSelfSacAtNextEndStep` leaf round-trips byte-equal across
# the trajectory serializer + cross-engine bridge — the exact same
# byte-equal contract the leaf carries when nested inside the parent
# IfYouDo at the real printing.
# -------------------------------------------------------------------


def test_cross_engine_real_eoe_attack_in_the_box_schedule_self_sac_round_trip():
    """**GENUINE real-EoE cross-engine byte-equal probe — Attack-in-
    the-Box ScheduleSelfSacAtNextEndStep leaf.** The slug-credit
    anchor for the PROBED tier flip even though the classifier multi-
    gates the card on ``nonsafe_triggered_ability``.

    Drives the **real parsed Attack-in-the-Box printing** through the
    trajectory serializer + cross-engine dict→Python bridge:

      * Extract the parsed ``IfYouDo`` attack-trigger effect from the
        real EoE printing.
      * Walk the ``IfYouDo.then_action`` — must be
        ``ScheduleSelfSacAtNextEndStep`` per the §2 parser SoT pin.
      * Serialize the leaf via ``trajectory._python_spell_effect_to_
        dict`` → ``{"kind": "schedule_self_sac_at_next_end_step"}``.
      * Round-trip via ``cross_engine._ta_dict_to_python_effect`` →
        a fresh ``ScheduleSelfSacAtNextEndStep()`` instance equal to
        the parser-emitted leaf.
      * Drive the leaf's resolve through Rust on the SAME synthetic
        state shape used in the unit pins above — the schedule lands
        a ``SacrificeSourceDelayed`` delayed trigger keyed at the
        current turn, byte-equal-observable to the round-trip dict.

    **Byte-equality scope.** Both the parser-emitted leaf and the
    bridge-reconstructed leaf compare equal as field-free unit
    dataclasses; the Rust-side schedule lands an identical
    ``DelayedTrigger`` shape (``fire_at_turn ==
    state.turn_number``, ``controller_id == caster``, ``source_id
    == source.id``, ``effect_kind ==
    "sacrifice_source_delayed"``).

    **Cycle 1 scope caveat.** The full real-EoE IfYouDo(MayDo(...))
    parent-composition byte-equal probe requires driving Rust's
    ``submit_may_do_decision`` + ``submit_if_you_do_decision`` agent
    surfaces (the cross-engine harness today exposes no
    deterministic agent for those decisions). That broader probe is
    honest-stopped at Cycle 1; the substrate-level round-trip + the
    Rust schedule+drain unit pins carry the PROBED tier flip per the
    Terrapact Intimidator / Boilerbilges Ripper / Fanatic of the
    Harrowing classifier-bypass precedent.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.combinators import IfYouDo, MayDo
    from mtg_bot.effects.generic import (
        PumpSelfUntilEOT, ScheduleSelfSacAtNextEndStep,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    real = get_active_source().get_printings().get("Attack-in-the-Box")
    if real is None:
        pytest.skip("Attack-in-the-Box absent from active CardSource")

    # §2 source-of-truth: genuine ATTACKS trigger must be
    # IfYouDo(MayDo(PumpSelfUntilEOT(+4/+0)),
    # ScheduleSelfSacAtNextEndStep()).
    attack_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event is Event.ATTACKS
        ),
        None,
    )
    assert attack_ta is not None, (
        "Attack-in-the-Box must have an ATTACKS triggered ability"
    )
    assert isinstance(attack_ta.effect, IfYouDo), (
        f"attack trigger must be IfYouDo; got "
        f"{type(attack_ta.effect).__name__}"
    )
    assert isinstance(attack_ta.effect.do_action, MayDo), (
        f"IfYouDo.do_action must be MayDo; got "
        f"{type(attack_ta.effect.do_action).__name__}"
    )
    inner = attack_ta.effect.do_action.inner
    assert isinstance(inner, PumpSelfUntilEOT), (
        f"MayDo.inner must be PumpSelfUntilEOT; got "
        f"{type(inner).__name__}"
    )
    assert (inner.power_bonus, inner.toughness_bonus) == (4, 0), (
        f"PumpSelfUntilEOT must be +4/+0; got "
        f"+{inner.power_bonus}/+{inner.toughness_bonus}"
    )
    leaf = attack_ta.effect.then_action
    assert isinstance(leaf, ScheduleSelfSacAtNextEndStep), (
        f"IfYouDo.then_action must be ScheduleSelfSacAtNextEndStep; "
        f"got {type(leaf).__name__}"
    )

    # Round-trip the leaf through trajectory serializer + cross-engine
    # dict→Python bridge.
    d = trajectory._python_spell_effect_to_dict(leaf)
    assert d == {"kind": "schedule_self_sac_at_next_end_step"}, (
        f"real-EoE leaf serializer must emit the bare unit-variant "
        f"dict; got {d}"
    )
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, ScheduleSelfSacAtNextEndStep), (
        f"dict→Python bridge must round-trip to "
        f"ScheduleSelfSacAtNextEndStep; got {type(rebuilt).__name__}"
    )
    assert rebuilt == leaf, (
        f"round-tripped leaf must equal the parser-emitted leaf "
        f"(both field-free unit dataclasses); got rebuilt={rebuilt!r}, "
        f"parser={leaf!r}"
    )

    # Drive the leaf through Rust's resolve arm on the same synthetic
    # state shape used in the unit pins. The schedule lands a
    # SacrificeSourceDelayed delayed trigger keyed at the current
    # turn — the byte-equal observable across engines.
    rs = _fresh_rust_state()
    box_id = rs.register_and_inject_object(
        _BOX_LIKE_PRINTING_DICT, 0, ZONE_BATTLEFIELD,
    )
    turn_at_cast = rs.turn_number
    rs.push_to_stack(box_id, 0)
    rs.resolve_top_of_stack()
    assert rs.delayed_trigger_count == 1, (
        f"Rust schedule must land exactly 1 delayed trigger; got "
        f"{rs.delayed_trigger_count}"
    )
    sched = rs.delayed_triggers_snapshot()[-1]
    assert sched["fire_at_turn"] == turn_at_cast
    assert sched["controller_id"] == 0
    assert sched["source_id"] == box_id
    assert sched["effect_kind"] == "sacrifice_source_delayed", (
        f"Rust schedule must carry the SacrificeSourceDelayed body; "
        f"got effect_kind={sched['effect_kind']!r}"
    )
