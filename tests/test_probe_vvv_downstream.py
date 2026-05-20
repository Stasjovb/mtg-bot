"""Genuine real-EoE cross-engine byte-equality probes -- batch VVV downstream
(15th Rust slice; closes VVV Pin 1).

The 15th Rust slice added a player-subject tautology arm to the Rust
``Predicate::SourceIsSelf::matches`` evaluator at ``rust/src/cards.rs``
(VVV Pin 1 closure 2026-05-20).  Phase-step events
(e.g. ``BEGINNING_OF_POSTCOMBAT_MAIN`` closed by slice 10) dispatch
with ``PLAYER_SUBJECT_OFFSET + active_player`` as the subject_id
sentinel rather than a permanent's id; the previous bare
``source_id == subject_id`` check always returned False for these
events, silently preventing the EoE Survivor postcombat-main triggers
from pushing on Rust.  The closure mirrors the sibling
``Predicate::ControlledByYou`` arm: ``subject_id >=
PLAYER_SUBJECT_OFFSET => true`` (tautological on player subjects;
matches Python's ``IsSelf.matches`` ``not hasattr(obj, "printing")``
arm at ``src/mtg_bot/effects/predicates.py:428-436``).

The pre-closure ``test_probe_ppp_downstream.py`` probes for Cautious
Survivor + Savior of the Small verified parse-acceptance only --
they injected the triggered ability via ``register_and_inject_object``
and confirmed no PyValueError but never DROVE the dispatcher past
PHASE_MAIN2 (no event fires, no stack trigger pushed, no compare to
make).  This module is the end-to-end byte-equal companion: drive the
trigger through the actual postcombat-main dispatch on both engines
and assert the observable matches.

PROBE CARDS
-----------

Probe 1 -- Cautious Survivor (BEGINNING_OF_POSTCOMBAT_MAIN +
GainLife(2)).  Survival creature: at the beginning of your second
main phase, if this creature is tapped, you gain 2 life.  Predicate
composition ``And(And(Controlled(YOU), IsSelf()), Source(IsTapped()))``
-- the IsSelf clause is the load-bearing player-subject-tautology
arm that the 15th Rust slice closure unblocks.

Probe 2 -- Defiant Survivor (BEGINNING_OF_POSTCOMBAT_MAIN +
ManifestDread(1)) -- empty-library no-op variant.  Same Survival
predicate composition; ManifestDread fizzles on an empty library
(``effects/generic/library_lookat.py:399-400`` short-circuit:
``if not p.library: return``).  Rust mirrors the no-op shape on
``state_ops_resolve.rs`` (empty examined-pool => decision skipped).
Byte-equal observable: the trigger PUSHES on both engines (post-
closure), then resolves with no net state change beyond the stack-
drain itself.  Pre-closure, the trigger silently NEVER pushes on
Rust, so the empty-lib probe is sufficient to surface the gap
without needing matching Manifest token registrations.

Probe 3 -- Shrewd Storyteller (BEGINNING_OF_POSTCOMBAT_MAIN +
PutPlusOneCounterOnTargetCreature(amount=1)) -- self-target variant.
Same Survival predicate composition; the +1/+1-counter effect picks
the first-legal-target creature on bf.  With Storyteller as the only
creature on the battlefield, both engines deterministically pick it
as the target (Python via ``DefaultTacticalAgent.choose_target`` ->
``legal_targets[0]``; Rust via ``first_legal_trigger_target`` at
push time -- the smallest-bf-index filter-passing object).  Resolve
adds 1 +1/+1 counter to Storyteller; the cross-engine assertion
checks Python's ``plus_one_counters == 1`` matches Rust's
``get_counters(storyteller_id) == 1``.

Probe 4 -- Savior of the Small (BEGINNING_OF_POSTCOMBAT_MAIN +
ReturnCreatureFromYourGraveyardToHand(max_mv=3)) -- non-empty-
graveyard variant.  Same Survival predicate composition; the
graveyard-return effect picks the first creature in the controller's
graveyard whose printing's mana value is <= max_mv.  Setup: a single
vanilla Emissary Escort (MV 2 <= 3) seeded into p0's graveyard
matches the cap.  Both engines deterministically return it to p0's
hand (Python via ``DefaultTacticalAgent.choose_target`` over
``ReturnFromGraveyard.legal_targets``; Rust via the resolve-arm
``state.players[controller_idx].graveyard.iter().find_map`` which
auto-picks the first Creature-typed graveyard card -- see
``rust/src/state_ops_resolve.rs:4561-4595``).  The byte-equal
observable: p0 graveyard size: 1 -> 0; p0 hand size: 0 -> 1 on
both engines.

Honest-exhaustion drop -- House Cartographer.  The 5th Survivor card
(House Cartographer's "Reveal cards from the top of your library
until you reveal a land card. ...") resolves to a bespoke Python-
only effect class ``HouseCartographerSurvivalEffect`` at
``src/mtg_bot/effects/bespoke.py:2667-2727``.  The Rust engine has
NO matching ``Effect`` variant and NO ``"house_cartographer_survival"``
parse_effect arm (verified 2026-05-20: ``parse_effect`` enumerates
the valid kinds and rejects unknown ones with PyValueError).  Adding
the Rust resolver is a separate slice -- a real reveal-until-land
walk with random-order placement on library bottom is a non-trivial
effect lane.  Closing the family today would require either a Rust
slice (out of scope per the lane's "no Rust touch" discipline) or a
parse-acceptance-only probe (declined: parity probes assert byte-
equal RESOLVE, not parse).  Dropped with this docstring note in
favor of shipping the two clean probes above.
"""

from __future__ import annotations

import importlib.util

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# Probe 1 -- Cautious Survivor: BEGINNING_OF_POSTCOMBAT_MAIN + GainLife(2)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_cautious_survivor_postcombat_main_gain_life_parity():
    """**GENUINE real-EoE cross-engine probe -- Cautious Survivor
    (15th Rust slice; VVV Pin 1 byte-equal verification).**

    Drives the **real parsed Cautious Survivor printing** on the
    Python side and a bridged synthetic carrier on the Rust side
    through the BEGINNING_OF_POSTCOMBAT_MAIN dispatch.  The Survival
    predicate ``And(And(Controlled(YOU), IsSelf()), Source(IsTapped()))``
    fires the GainLife(2) trigger on both engines once the source is
    tapped at the start of post-combat main.

    Pre-15th-slice behavior (the VVV Pin 1 divergence):
      * Python: trigger pushes on the stack at PHASE_MAIN2 entry;
        GainLife(2) resolves; p0 life: 20 -> 22.
      * Rust: trigger silently NEVER pushes -- the predicate
        composition gates False because ``Predicate::SourceIsSelf``
        evaluated ``source_id == PLAYER_SUBJECT_OFFSET + active_player``
        (always False; the source's id is a small permanent id, not
        the sentinel).  p0 life stays at 20.

    Post-closure (15th Rust slice) byte-equal observable:
      * Both engines: p0 life: 20 -> 22 (GainLife(2) resolved).
      * Both engines: stack empty after drain.
      * Both engines: Cautious Survivor still on p0's battlefield
        (no zone movement).

    Setup:
      * Empty libraries on both sides (no GainLife dependency on
        library state; keeps the comparison surgical).
      * p0 has Cautious Survivor on bf, tapped, summoning_sick=False.
      * Active player = p0; start at PHASE_MAIN2 on both engines.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.predicates import Event
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.game import Zone
    from mtg_bot.actions import drain_stack
    from mtg_bot.turn import (
        Step,
        run_beginning_of_postcombat_main_triggers,
    )

    # ------------------------------------------------------------------
    # 1. Verify the real parsed Cautious Survivor printing.
    # ------------------------------------------------------------------
    src = get_active_source()
    real = src.get_printings().get("Cautious Survivor")
    if real is None:
        pytest.skip("Cautious Survivor absent from active CardSource")
    assert "Creature" in real.card_types
    pcm_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.BEGINNING_OF_POSTCOMBAT_MAIN
        ),
        None,
    )
    assert pcm_ta is not None
    assert isinstance(pcm_ta.effect, GainLife)
    assert pcm_ta.effect.amount == 2

    # ------------------------------------------------------------------
    # 2. Shared triggered-ability dict (Rust carrier).
    # ------------------------------------------------------------------
    cs_ta_dict = {
        "event": "beginning_of_postcombat_main",
        "predicate": {
            "kind": "and",
            "left": {
                "kind": "and",
                "left": {"kind": "controlled_by_you"},
                "right": {"kind": "source_is_self"},
            },
            "right": {"kind": "source_is_tapped"},
        },
        "effect": {"kind": "gain_life", "amount": 2},
    }

    # ------------------------------------------------------------------
    # 3. Build cross-engine states with EMPTY libraries.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rs = build_rust_state(spec)
    py = build_python_state(spec)
    ZB = 2  # ZONE_BATTLEFIELD

    # ------------------------------------------------------------------
    # 4. Rust: inject Cautious Survivor carrier; tap; advance to MAIN2.
    # ------------------------------------------------------------------
    rs_cs_id = rs.register_and_inject_object(
        {
            "name": "Cautious Survivor",
            "card_types": ["Creature"],
            "subtypes": ["Survivor"],
            "power": int(real.power),
            "toughness": int(real.toughness),
            "keywords": [],
            "effects": [],
            "triggered_abilities": [cs_ta_dict],
        },
        0,  # owner_id = p0
        ZB,
    )
    rs.clear_summoning_sick_for_player(0)
    rs.tap_object(rs_cs_id)
    # Drain any spurious ETB stack noise (Cautious Survivor's only TA
    # is the postcombat-main; no ENTERS trigger).
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_life0_before = rs.get_life(0)
    assert rs_life0_before == 20

    # Advance phases until reaching PHASE_MAIN2 (= 9).  The Rust
    # advance_phase increments through UNTAP/UPKEEP/DRAW/MAIN1/
    # combat sub-phases/MAIN2 — the dispatch site at
    # state_ops_steps.rs:622-639 fires
    # ``Event::BeginningOfPostcombatMain`` with the
    # ``PLAYER_SUBJECT_OFFSET + active_player`` sentinel on MAIN2
    # entry.  Cap iterations to prevent runaway loops if the phase
    # graph ever changes.
    PHASE_MAIN2 = 9
    for _ in range(30):
        rs.advance_phase()
        if rs.current_phase() == PHASE_MAIN2:
            break
    assert rs.current_phase() == PHASE_MAIN2, (
        f"Rust: must reach PHASE_MAIN2; got {rs.current_phase()}"
    )

    # Post-closure: trigger must have pushed on MAIN2 entry.  Pre-
    # closure, the bare ``Predicate::SourceIsSelf => source_id ==
    # subject_id`` arm gated the trigger to False.
    assert rs.stack_size() == 1, (
        f"Rust: exactly 1 trigger (Cautious Survivor GainLife(2)) "
        f"must be on the stack after MAIN2 entry post-VVV-Pin-1 "
        f"closure; got {rs.stack_size()}.  If 0, the closure was "
        "reverted -- audit Predicate::SourceIsSelf in cards.rs."
    )

    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_life0_after = rs.get_life(0)
    assert rs_life0_after == 22, (
        f"Rust: p0 life must be 22 after GainLife(2); got "
        f"{rs_life0_after}.  If 20, the trigger never pushed -- "
        "VVV Pin 1 closure regressed."
    )

    # ------------------------------------------------------------------
    # 5. Python: seat the real Cautious Survivor printing on p0's bf;
    #    tap; step into POSTCOMBAT_MAIN; fire triggers.
    # ------------------------------------------------------------------
    py_cs = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_cs.summoning_sick = False
    py_cs.tapped = True
    py_cs.damage = 0
    py_cs.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_cs)

    # Drain any ETB noise (the Survival trigger doesn't push on ETB).
    while py.stack:
        from mtg_bot.actions import resolve_top_of_stack
        resolve_top_of_stack(py)

    py_life0_before = py.players[0].life
    assert py_life0_before == 20

    # Set step to POSTCOMBAT_MAIN (the Python turn-loop's
    # postcombat-main dispatch lane).  Mirrors the
    # _new_state_in_postcombat_main pattern in test_survival.py:303.
    py.step = Step.POSTCOMBAT_MAIN
    py.active_player_idx = 0
    py.priority_player_idx = 0

    run_beginning_of_postcombat_main_triggers(py)

    assert len(py.stack) == 1, (
        f"Python: exactly 1 trigger (Cautious Survivor GainLife(2)) "
        f"must be on the stack; got {len(py.stack)}"
    )
    drain_stack(py)

    py_life0_after = py.players[0].life
    assert py_life0_after == 22, (
        f"Python: p0 life must be 22 after GainLife(2); got "
        f"{py_life0_after}"
    )

    # ------------------------------------------------------------------
    # 6. Cross-engine byte-equality on targeted observables.
    # ------------------------------------------------------------------
    assert rs_life0_after == py_life0_after == 22, (
        f"p0 life after MAIN2 GainLife(2): Rust={rs_life0_after}, "
        f"Python={py_life0_after} (must be byte-equal at 22 -- the "
        "Survivor postcombat-main trigger fired identically on both "
        "engines post-VVV-Pin-1 closure)"
    )
    assert rs.get_life(1) == py.players[1].life == 20, (
        f"p1 life: Rust={rs.get_life(1)}, Python={py.players[1].life} "
        f"(must be byte-equal at 20 -- untouched by p0's GainLife)"
    )
    # Battlefield counts: Cautious Survivor on p0; p1 empty.
    assert rs.battlefield_sizes[0] == len(py.battlefield) == 1, (
        f"p0 battlefield: Rust={rs.battlefield_sizes[0]}, "
        f"Python={len(py.battlefield)} (must be byte-equal at 1 -- "
        "Cautious Survivor only)"
    )


# ---------------------------------------------------------------------------
# Probe 2 -- Defiant Survivor: BEGINNING_OF_POSTCOMBAT_MAIN +
#            ManifestDread(1) empty-library no-op variant.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_defiant_survivor_postcombat_main_manifest_dread_empty_lib_parity():
    """**GENUINE real-EoE cross-engine probe -- Defiant Survivor
    (15th Rust slice; VVV Pin 1 byte-equal verification, empty-lib
    no-op variant).**

    Same Survival predicate composition as Cautious Survivor:
    ``And(And(Controlled(YOU), IsSelf()), Source(IsTapped()))``.
    Different effect lane: ``ManifestDread(count=1)``.  With p0's
    library EMPTY on both engines, ManifestDread short-circuits:

      * Python: ``effects/generic/library_lookat.py:399-400``::
            if not p.library:
                return
      * Rust: the Manifest-Dread resolve arm queues a
        ``PendingDecision::ManifestDreadChoice`` only when the
        examined-pool is non-empty (mirrors Surveil/Scry no-op
        shape).  Empty library => no decision queued, no agent
        contact.

    Pre-closure: the trigger silently NEVER pushes on Rust (same
    Pin 1 gap as Cautious Survivor).
    Post-closure: both engines push the trigger; both resolve as a
    no-op (no library cards to walk); state is byte-equal end-to-
    end.

    Why the empty-library no-op variant suffices:
      The closure target is the predicate-evaluator gate, not the
      effect resolution.  Whether ManifestDread spawns a 2/2 token
      face-down or short-circuits is orthogonal to whether the
      trigger PUSHES on MAIN2.  Empty library lets the probe pin
      the closure with a surgical observable (stack push count =
      1 on both engines after MAIN2 entry) without needing matching
      face-down-creature registration substrate.

    Observables asserted (targeted):
      * Stack push count: 1 on both engines at MAIN2 entry
        (the Pin 1 gate observable).
      * Stack drain leaves stack empty on both engines.
      * No pending decisions on Rust side (empty-lib short-circuit).
      * Lives unchanged at 20 (ManifestDread doesn't touch life).
      * Both libraries still empty (no manifest, no graveyard mill).
      * p0 battlefield: Defiant Survivor only (1 object).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.predicates import Event
    from mtg_bot.effects.generic.library_lookat import ManifestDread
    from mtg_bot.game import Zone
    from mtg_bot.actions import drain_stack
    from mtg_bot.turn import (
        Step,
        run_beginning_of_postcombat_main_triggers,
    )

    # ------------------------------------------------------------------
    # 1. Verify the real parsed Defiant Survivor printing.
    # ------------------------------------------------------------------
    src = get_active_source()
    real = src.get_printings().get("Defiant Survivor")
    if real is None:
        pytest.skip("Defiant Survivor absent from active CardSource")
    assert "Creature" in real.card_types
    pcm_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.BEGINNING_OF_POSTCOMBAT_MAIN
        ),
        None,
    )
    assert pcm_ta is not None
    assert isinstance(pcm_ta.effect, ManifestDread)
    assert pcm_ta.effect.count == 1

    # ------------------------------------------------------------------
    # 2. Shared triggered-ability dict (Rust carrier).
    # ------------------------------------------------------------------
    ds_ta_dict = {
        "event": "beginning_of_postcombat_main",
        "predicate": {
            "kind": "and",
            "left": {
                "kind": "and",
                "left": {"kind": "controlled_by_you"},
                "right": {"kind": "source_is_self"},
            },
            "right": {"kind": "source_is_tapped"},
        },
        "effect": {"kind": "manifest_dread", "count": 1},
    }

    # ------------------------------------------------------------------
    # 3. Build cross-engine states with EMPTY libraries.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rs = build_rust_state(spec)
    py = build_python_state(spec)
    ZB = 2  # ZONE_BATTLEFIELD

    # ------------------------------------------------------------------
    # 4. Rust: inject Defiant Survivor carrier; tap; advance to MAIN2.
    # ------------------------------------------------------------------
    rs_ds_id = rs.register_and_inject_object(
        {
            "name": "Defiant Survivor",
            "card_types": ["Creature"],
            "subtypes": ["Survivor"],
            "power": int(real.power),
            "toughness": int(real.toughness),
            "keywords": [],
            "effects": [],
            "triggered_abilities": [ds_ta_dict],
        },
        0,
        ZB,
    )
    rs.clear_summoning_sick_for_player(0)
    rs.tap_object(rs_ds_id)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    assert rs.library_sizes[0] == 0
    assert rs.library_sizes[1] == 0
    assert rs.get_life(0) == 20
    assert rs.get_life(1) == 20

    # Advance phases until reaching PHASE_MAIN2.
    PHASE_MAIN2 = 9
    for _ in range(30):
        rs.advance_phase()
        if rs.current_phase() == PHASE_MAIN2:
            break
    assert rs.current_phase() == PHASE_MAIN2, (
        f"Rust: must reach PHASE_MAIN2; got {rs.current_phase()}"
    )
    # Post-closure: the trigger PUSHES on MAIN2 entry.
    assert rs.stack_size() == 1, (
        f"Rust: exactly 1 trigger (Defiant Survivor ManifestDread(1)) "
        f"must be on the stack after MAIN2 entry post-VVV-Pin-1 "
        f"closure; got {rs.stack_size()}.  If 0, the closure was "
        "reverted -- audit Predicate::SourceIsSelf in cards.rs."
    )

    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    # Empty-lib short-circuit: no PendingDecision queued; no
    # graveyard mill; library still empty.
    assert not rs.has_pending_decision(), (
        f"Rust: no pending decisions must remain after empty-lib "
        f"ManifestDread resolve; got {rs.pending_decisions()}"
    )
    assert rs.library_sizes[0] == 0, (
        f"Rust: p0 library must be unchanged (empty -> empty); got "
        f"{rs.library_sizes[0]}"
    )
    assert rs.graveyard_sizes[0] == 0, (
        f"Rust: p0 graveyard must be unchanged (no mill on empty "
        f"library); got {rs.graveyard_sizes[0]}"
    )

    # ------------------------------------------------------------------
    # 5. Python: seat the real Defiant Survivor printing; tap; fire
    #    postcombat-main triggers.
    # ------------------------------------------------------------------
    py_ds = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_ds.summoning_sick = False
    py_ds.tapped = True
    py_ds.damage = 0
    py_ds.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_ds)

    while py.stack:
        from mtg_bot.actions import resolve_top_of_stack
        resolve_top_of_stack(py)

    assert len(py.players[0].library) == 0
    assert len(py.players[0].graveyard) == 0

    py.step = Step.POSTCOMBAT_MAIN
    py.active_player_idx = 0
    py.priority_player_idx = 0

    run_beginning_of_postcombat_main_triggers(py)
    assert len(py.stack) == 1, (
        f"Python: exactly 1 trigger (Defiant Survivor ManifestDread(1)) "
        f"must be on the stack; got {len(py.stack)}"
    )
    drain_stack(py)

    assert len(py.players[0].library) == 0, (
        f"Python: p0 library must be unchanged (empty -> empty); "
        f"got {len(py.players[0].library)}"
    )
    assert len(py.players[0].graveyard) == 0, (
        f"Python: p0 graveyard must be unchanged (no mill on empty "
        f"library); got {len(py.players[0].graveyard)}"
    )

    # ------------------------------------------------------------------
    # 6. Cross-engine byte-equality on targeted observables.
    # ------------------------------------------------------------------
    assert rs.library_sizes[0] == len(py.players[0].library) == 0, (
        f"p0 library: Rust={rs.library_sizes[0]}, "
        f"Python={len(py.players[0].library)} (must be byte-equal "
        "at 0 -- empty-lib ManifestDread no-op on both engines)"
    )
    assert rs.graveyard_sizes[0] == len(py.players[0].graveyard) == 0, (
        f"p0 graveyard: Rust={rs.graveyard_sizes[0]}, "
        f"Python={len(py.players[0].graveyard)} (must be byte-equal "
        "at 0 -- no mill on empty library on either engine)"
    )
    assert rs.get_life(0) == py.players[0].life == 20, (
        f"p0 life: Rust={rs.get_life(0)}, Python={py.players[0].life} "
        "(must be byte-equal at 20 -- ManifestDread doesn't touch life)"
    )
    assert rs.get_life(1) == py.players[1].life == 20, (
        f"p1 life: Rust={rs.get_life(1)}, Python={py.players[1].life} "
        "(must be byte-equal at 20 -- untouched)"
    )
    # Defiant Survivor remains on p0's bf (no zone movement from the
    # empty-lib no-op resolve).
    assert rs.battlefield_sizes[0] == len(py.battlefield) == 1, (
        f"p0 battlefield: Rust={rs.battlefield_sizes[0]}, "
        f"Python={len(py.battlefield)} (must be byte-equal at 1 -- "
        "Defiant Survivor only; ManifestDread short-circuited before "
        "spawning a face-down 2/2 token)"
    )


# ---------------------------------------------------------------------------
# Probe 3 -- Shrewd Storyteller: BEGINNING_OF_POSTCOMBAT_MAIN +
#            PutPlusOneCounterOnTargetCreature(amount=1)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_shrewd_storyteller_postcombat_main_plus_one_counter_parity():
    """**GENUINE real-EoE cross-engine probe -- Shrewd Storyteller
    (15th Rust slice; VVV Pin 1 byte-equal verification, self-target
    +1/+1-counter variant).**

    Same Survival predicate composition as Cautious/Defiant Survivor:
    ``And(And(Controlled(YOU), IsSelf()), Source(IsTapped()))``.
    Different effect lane: ``PutPlusOneCounterOnTargetCreature
    (amount=1, attacking_only=False)``.

    This effect REQUIRES a legal creature target -- the count_min=1
    contract is gated on both engines via
    ``lever_trigger_requires_target`` (Rust:
    ``state_ops_resolve.rs:1087-1104`` admits
    ``Effect::PutPlusOneCounterOnTargetCreature``) and
    ``push_triggered_ability``'s ``if not legal and min_t > 0:
    return False`` fizzle path (Python: ``actions.py:3237-3242``).
    With Storyteller as the ONLY creature on the battlefield, both
    engines deterministically pick it as the first-legal target:

      * Rust: ``first_legal_trigger_target`` (the smallest-bf-index
        filter-passing object) seats Storyteller's id at push time
        via ``current_resolve_payload_target_id``.
      * Python: ``DefaultTacticalAgent.choose_target`` (seated on
        ``py.players[0].agent``) returns ``legal_targets[0]`` -- the
        same object the Rust seat picks (the cross-engine harness
        keeps bf insertion order + ids in lockstep).

    Pre-15th-slice behavior (the VVV Pin 1 divergence):
      * Python: trigger pushes at PHASE_MAIN2 entry with Storyteller
        seated as the +1/+1 target; resolves to give Storyteller
        ``plus_one_counters = 1``.
      * Rust: trigger silently NEVER pushes -- ``Predicate::
        SourceIsSelf`` gates False on the PLAYER_SUBJECT_OFFSET
        sentinel.  Storyteller's ``get_counters()`` stays 0.

    Post-closure byte-equal observable:
      * Both engines: stack pushes exactly 1 trigger at MAIN2 entry.
      * Both engines: after drain, Storyteller has counters=1.
      * Both engines: no other state change (life 20/20; bf size 1).

    Setup:
      * Empty libraries on both sides (no draw / library
        dependency).
      * p0 has Shrewd Storyteller on bf, tapped, summoning_sick=
        False.
      * ``DefaultTacticalAgent`` seated on both players so Python's
        ``push_triggered_ability`` target-pick loop chooses
        ``legal_targets[0]`` deterministically -- matches Rust's
        first-legal seat.
      * Active player = p0; start at PHASE_MAIN2 on both engines.

    Why self-targeting (vs seeding a second creature):
      A second bf creature would split bf insertion order between
      Storyteller (id 0) and the bystander (id 1).  Rust's
      ``first_legal_trigger_target`` scans
      ``bf_iter_etb_sorted`` (etb_timestamp-ordered) -- Storyteller
      enters first so it is bf[0] and the seat is unambiguous.
      Python's ``legal_targets`` walks ``state.battlefield`` in
      append order, also picking bf[0].  But self-targeting keeps
      the probe surgical: a single bf object, a single counter
      delta, no bystander-state to track.  +1/+1 counter on the
      source itself is a CR-legal target choice (the source is a
      creature on the battlefield; targeting itself is permitted).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.predicates import Event
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCounterOnTargetCreature,
    )
    from mtg_bot.game import Zone
    from mtg_bot.actions import drain_stack
    from mtg_bot.turn import (
        Step,
        run_beginning_of_postcombat_main_triggers,
    )
    from mtg_bot.search.tactical import DefaultTacticalAgent

    # ------------------------------------------------------------------
    # 1. Verify the real parsed Shrewd Storyteller printing.
    # ------------------------------------------------------------------
    src = get_active_source()
    real = src.get_printings().get("Shrewd Storyteller")
    if real is None:
        pytest.skip("Shrewd Storyteller absent from active CardSource")
    assert "Creature" in real.card_types
    pcm_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.BEGINNING_OF_POSTCOMBAT_MAIN
        ),
        None,
    )
    assert pcm_ta is not None
    assert isinstance(pcm_ta.effect, PutPlusOneCounterOnTargetCreature)
    assert pcm_ta.effect.amount == 1
    assert pcm_ta.effect.attacking_only is False

    # ------------------------------------------------------------------
    # 2. Shared triggered-ability dict (Rust carrier).
    # ------------------------------------------------------------------
    ss_ta_dict = {
        "event": "beginning_of_postcombat_main",
        "predicate": {
            "kind": "and",
            "left": {
                "kind": "and",
                "left": {"kind": "controlled_by_you"},
                "right": {"kind": "source_is_self"},
            },
            "right": {"kind": "source_is_tapped"},
        },
        "effect": {
            "kind": "put_plus_one_counter_on_target_creature",
            "amount": 1,
            "attacking_only": False,
        },
    }

    # ------------------------------------------------------------------
    # 3. Build cross-engine states with EMPTY libraries.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rs = build_rust_state(spec)
    py = build_python_state(spec)
    ZB = 2  # ZONE_BATTLEFIELD

    # ------------------------------------------------------------------
    # 4. Rust: inject Shrewd Storyteller carrier; tap; advance to MAIN2.
    # ------------------------------------------------------------------
    rs_ss_id = rs.register_and_inject_object(
        {
            "name": "Shrewd Storyteller",
            "card_types": ["Creature"],
            "subtypes": ["Human", "Survivor"],
            "power": int(real.power),
            "toughness": int(real.toughness),
            "keywords": [],
            "effects": [],
            "triggered_abilities": [ss_ta_dict],
        },
        0,  # owner_id = p0
        ZB,
    )
    rs.clear_summoning_sick_for_player(0)
    rs.tap_object(rs_ss_id)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    assert rs.get_counters(rs_ss_id) == 0

    # Advance phases until reaching PHASE_MAIN2 (= 9).
    PHASE_MAIN2 = 9
    for _ in range(30):
        rs.advance_phase()
        if rs.current_phase() == PHASE_MAIN2:
            break
    assert rs.current_phase() == PHASE_MAIN2, (
        f"Rust: must reach PHASE_MAIN2; got {rs.current_phase()}"
    )

    # Post-closure: trigger pushes with Storyteller seated as target.
    assert rs.stack_size() == 1, (
        f"Rust: exactly 1 trigger (Shrewd Storyteller "
        f"+1/+1-counter) must be on the stack after MAIN2 entry "
        f"post-VVV-Pin-1 closure; got {rs.stack_size()}.  If 0, the "
        "closure was reverted -- audit Predicate::SourceIsSelf in "
        "cards.rs."
    )

    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_counters_after = rs.get_counters(rs_ss_id)
    assert rs_counters_after == 1, (
        f"Rust: Shrewd Storyteller must have counters=1 after "
        f"PutPlusOneCounterOnTargetCreature(1) resolves on itself; "
        f"got {rs_counters_after}.  If 0, either the trigger "
        "fizzled (target seat missing) or the closure regressed."
    )

    # ------------------------------------------------------------------
    # 5. Python: seat the real Shrewd Storyteller printing; tap; fire
    #    postcombat-main triggers.  DefaultTacticalAgent on both
    #    players so Python's choose_target picks legal_targets[0]
    #    deterministically (matches Rust's first-legal-target seat).
    # ------------------------------------------------------------------
    py_ss = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_ss.summoning_sick = False
    py_ss.tapped = True
    py_ss.damage = 0
    py_ss.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_ss)

    py.players[0].agent = DefaultTacticalAgent()
    py.players[1].agent = DefaultTacticalAgent()

    while py.stack:
        from mtg_bot.actions import resolve_top_of_stack
        resolve_top_of_stack(py)

    assert py_ss.plus_one_counters == 0

    py.step = Step.POSTCOMBAT_MAIN
    py.active_player_idx = 0
    py.priority_player_idx = 0

    run_beginning_of_postcombat_main_triggers(py)
    assert len(py.stack) == 1, (
        f"Python: exactly 1 trigger (Shrewd Storyteller "
        f"+1/+1-counter) must be on the stack; got {len(py.stack)}"
    )
    drain_stack(py)

    py_counters_after = py_ss.plus_one_counters
    assert py_counters_after == 1, (
        f"Python: Shrewd Storyteller must have plus_one_counters=1 "
        f"after PutPlusOneCounterOnTargetCreature(1) resolves on "
        f"itself; got {py_counters_after}"
    )

    # ------------------------------------------------------------------
    # 6. Cross-engine byte-equality on targeted observables.
    # ------------------------------------------------------------------
    assert rs_counters_after == py_counters_after == 1, (
        f"Shrewd Storyteller counters after MAIN2 trigger: "
        f"Rust={rs_counters_after}, Python={py_counters_after} "
        "(must be byte-equal at 1 -- the Survivor postcombat-main "
        "trigger fired identically on both engines post-VVV-Pin-1 "
        "closure with self-target seated)"
    )
    assert rs.get_life(0) == py.players[0].life == 20, (
        f"p0 life: Rust={rs.get_life(0)}, Python={py.players[0].life} "
        f"(must be byte-equal at 20 -- "
        "PutPlusOneCounterOnTargetCreature doesn't touch life)"
    )
    assert rs.get_life(1) == py.players[1].life == 20, (
        f"p1 life: Rust={rs.get_life(1)}, Python={py.players[1].life} "
        f"(must be byte-equal at 20 -- untouched)"
    )
    # Battlefield counts: Storyteller on p0; p1 empty.
    assert rs.battlefield_sizes[0] == len(py.battlefield) == 1, (
        f"p0 battlefield: Rust={rs.battlefield_sizes[0]}, "
        f"Python={len(py.battlefield)} (must be byte-equal at 1 -- "
        "Shrewd Storyteller only)"
    )


# ---------------------------------------------------------------------------
# Probe 4 -- Savior of the Small: BEGINNING_OF_POSTCOMBAT_MAIN +
#            ReturnCreatureFromYourGraveyardToHand(max_mv=3)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_savior_of_the_small_postcombat_main_return_creature_parity():
    """**GENUINE real-EoE cross-engine probe -- Savior of the Small
    (15th Rust slice; VVV Pin 1 byte-equal verification,
    graveyard-return variant).**

    Same Survival predicate composition as Cautious/Defiant Survivor:
    ``And(And(Controlled(YOU), IsSelf()), Source(IsTapped()))``.
    Different effect lane:
    ``ReturnCreatureFromYourGraveyardToHand(max_mv=3)`` -- return a
    target creature card with mana value 3 or less from your
    graveyard to your hand.

    Setup chooses a non-empty graveyard variant rather than the
    empty-graveyard no-op variant.  The empty-graveyard case would
    DIVERGE post-closure: ``Effect::ReturnCreatureFromYourGraveyardToHand``
    is NOT in Rust's ``lever_trigger_requires_target``
    (``state_ops_resolve.rs:1087-1104``), so Rust unconditionally
    pushes the trigger and the resolve arm no-ops on the empty
    graveyard scan -- BUT Python's ``ReturnFromGraveyard``
    (``effects/generic/graveyard.py:167``) sets
    ``target_count_range = (1, 1)``, so
    ``push_triggered_ability`` (actions.py:3237-3242) hits the
    ``if not legal and min_t > 0`` fizzle path and Python SKIP-
    pushes.  Stack size: 1 (Rust) vs 0 (Python) -- a divergence
    orthogonal to the VVV Pin 1 closure.  Probing the non-empty-
    graveyard variant pins the closure on both engines pushing AND
    resolving with the same observable.

    With a single Creature-typed card (Emissary Escort, MV 2 -- the
    smallest-MV vanilla EoE creature with no triggered/activated/
    keyword baggage) in p0's graveyard:

      * Rust: the resolve arm (``state_ops_resolve.rs:4561-4595``)
        scans ``state.players[controller_idx].graveyard`` for the
        first object whose printing has ``card_types`` containing
        "Creature".  Emissary Escort is the only Creature in the
        graveyard, so it's picked unambiguously.  The object is
        moved gy -> hand.  Note: the Rust unit variant carries NO
        ``max_mv`` field (the dict shape is bare
        ``{"kind": "return_creature_from_your_graveyard_to_hand"}``
        -- extra rider fields are silently ignored), so any
        Creature is eligible at the resolve-arm scan.  Since
        Emissary Escort has MV 2 (< Python's max_mv=3 cap), both
        engines pick the same card.
      * Python: ``ReturnFromGraveyard.legal_targets`` filters by
        ``_matches`` (creature=True, max_mv=3), enumerates
        ``[("graveyard_creature", escort_id)]``, and
        ``DefaultTacticalAgent.choose_target`` picks
        ``legal_targets[0]`` -- the same Emissary Escort the Rust
        seat picks.  ``ReturnFromGraveyard.resolve`` moves the
        card gy -> hand (``_move_one`` at graveyard.py:285-295).

    Pre-15th-slice behavior (the VVV Pin 1 divergence):
      * Python: trigger pushes at PHASE_MAIN2 entry with Emissary
        Escort seated as target; resolves gy -> hand.
      * Rust: trigger silently NEVER pushes -- ``Predicate::
        SourceIsSelf`` gates False on the player-subject sentinel.
        Emissary Escort stays in gy.

    Post-closure byte-equal observable:
      * Both engines: stack pushes exactly 1 trigger at MAIN2 entry.
      * Both engines: after drain, p0 graveyard size: 1 -> 0;
        p0 hand size: 0 -> 1.
      * Both engines: bf unchanged (1 = Savior of the Small only).
      * Both engines: life unchanged (20/20).

    Setup:
      * Empty libraries on both sides.
      * p0 has Savior of the Small on bf, tapped, summoning_sick=
        False.
      * p0 has Emissary Escort (MV 2 vanilla) in graveyard --
        registered FIRST on Rust (id=0) so it appears before
        Savior in the bf-iter / graveyard-iter scans.
      * ``DefaultTacticalAgent`` seated on both players for
        deterministic Python target picking.
      * Active player = p0; start at PHASE_MAIN2 on both engines.

    Why Emissary Escort:
      * Pure vanilla (no keywords, no triggered/activated abilities)
        so injecting it doesn't pull in collateral parse machinery.
      * MV 2 <= 3 satisfies Savior's max_mv cap (the Rust unit
        variant doesn't enforce the cap at resolve, but the cap
        DOES filter Python's legal_targets -- using a card under
        the cap avoids spurious skip).
      * EoE-pool card, so the real parsed printing is available
        via ``get_active_source().get_printings()`` and the
        Python side can use it directly.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.predicates import Event
    from mtg_bot.effects.generic.bounce import (
        ReturnCreatureFromYourGraveyardToHand,
    )
    from mtg_bot.game import Zone
    from mtg_bot.actions import drain_stack
    from mtg_bot.turn import (
        Step,
        run_beginning_of_postcombat_main_triggers,
    )
    from mtg_bot.search.tactical import DefaultTacticalAgent

    # ------------------------------------------------------------------
    # 1. Verify the real parsed Savior of the Small + Emissary Escort
    #    printings.
    # ------------------------------------------------------------------
    src = get_active_source()
    real = src.get_printings().get("Savior of the Small")
    if real is None:
        pytest.skip("Savior of the Small absent from active CardSource")
    escort = src.get_printings().get("Emissary Escort")
    if escort is None:
        pytest.skip("Emissary Escort absent from active CardSource")
    assert "Creature" in real.card_types
    assert "Creature" in escort.card_types
    # Sanity: Emissary Escort's MV fits Savior's max_mv=3 cap.
    assert escort.mana_cost.total <= 3, (
        f"Emissary Escort mv must be <= 3 to be eligible under "
        f"Savior's max_mv cap; got {escort.mana_cost.total}"
    )
    pcm_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event == Event.BEGINNING_OF_POSTCOMBAT_MAIN
        ),
        None,
    )
    assert pcm_ta is not None
    assert isinstance(pcm_ta.effect, ReturnCreatureFromYourGraveyardToHand)
    assert pcm_ta.effect.max_mv == 3

    # ------------------------------------------------------------------
    # 2. Shared triggered-ability dict (Rust carrier).
    # ------------------------------------------------------------------
    sots_ta_dict = {
        "event": "beginning_of_postcombat_main",
        "predicate": {
            "kind": "and",
            "left": {
                "kind": "and",
                "left": {"kind": "controlled_by_you"},
                "right": {"kind": "source_is_self"},
            },
            "right": {"kind": "source_is_tapped"},
        },
        "effect": {
            "kind": "return_creature_from_your_graveyard_to_hand",
        },
    }

    # ------------------------------------------------------------------
    # 3. Build cross-engine states with EMPTY libraries.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rs = build_rust_state(spec)
    py = build_python_state(spec)
    ZB = 2  # ZONE_BATTLEFIELD
    ZG = 3  # ZONE_GRAVEYARD

    # ------------------------------------------------------------------
    # 4. Rust: register Emissary Escort in p0 graveyard FIRST (so it
    #    has the smallest id and the resolve-arm graveyard scan picks
    #    it unambiguously), then Savior of the Small on bf; tap;
    #    advance to MAIN2.
    # ------------------------------------------------------------------
    rs_escort_id = rs.register_and_inject_object(
        {
            "name": "Emissary Escort",
            "card_types": ["Creature"],
            "subtypes": ["Robot", "Soldier"],
            "power": int(escort.power),
            "toughness": int(escort.toughness),
            "keywords": [],
            "effects": [],
            "triggered_abilities": [],
        },
        0,  # owner_id = p0
        ZG,
    )
    rs_savior_id = rs.register_and_inject_object(
        {
            "name": "Savior of the Small",
            "card_types": ["Creature"],
            "subtypes": ["Kor", "Survivor"],
            "power": int(real.power),
            "toughness": int(real.toughness),
            "keywords": [],
            "effects": [],
            "triggered_abilities": [sots_ta_dict],
        },
        0,
        ZB,
    )
    rs.clear_summoning_sick_for_player(0)
    rs.tap_object(rs_savior_id)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    assert rs.graveyard_sizes[0] == 1
    assert rs.hand_sizes[0] == 0
    assert rs.battlefield_sizes[0] == 1

    # Advance phases until reaching PHASE_MAIN2.
    PHASE_MAIN2 = 9
    for _ in range(30):
        rs.advance_phase()
        if rs.current_phase() == PHASE_MAIN2:
            break
    assert rs.current_phase() == PHASE_MAIN2, (
        f"Rust: must reach PHASE_MAIN2; got {rs.current_phase()}"
    )

    # Post-closure: trigger pushes.
    assert rs.stack_size() == 1, (
        f"Rust: exactly 1 trigger (Savior of the Small ReturnCreature) "
        f"must be on the stack after MAIN2 entry post-VVV-Pin-1 "
        f"closure; got {rs.stack_size()}.  If 0, the closure was "
        "reverted -- audit Predicate::SourceIsSelf in cards.rs."
    )

    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_gy_after = rs.graveyard_sizes[0]
    rs_hand_after = rs.hand_sizes[0]
    assert rs_gy_after == 0 and rs_hand_after == 1, (
        f"Rust: Emissary Escort must move gy -> hand; got "
        f"gy={rs_gy_after}, hand={rs_hand_after}.  If gy=1 hand=0, "
        "either the trigger fizzled or the resolve-arm graveyard "
        "scan failed to find the creature."
    )

    # ------------------------------------------------------------------
    # 5. Python: seed Emissary Escort in p0's graveyard FIRST (id
    #    allocation order matches Rust), then Savior of the Small on
    #    bf; tap; fire postcombat-main triggers.
    # ------------------------------------------------------------------
    py_escort = py.new_object(escort, owner_id=0, zone=Zone.GRAVEYARD)
    py.players[0].graveyard.append(py_escort)

    py_savior = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_savior.summoning_sick = False
    py_savior.tapped = True
    py_savior.damage = 0
    py_savior.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_savior)

    py.players[0].agent = DefaultTacticalAgent()
    py.players[1].agent = DefaultTacticalAgent()

    while py.stack:
        from mtg_bot.actions import resolve_top_of_stack
        resolve_top_of_stack(py)

    assert len(py.players[0].graveyard) == 1
    assert len(py.players[0].hand) == 0

    py.step = Step.POSTCOMBAT_MAIN
    py.active_player_idx = 0
    py.priority_player_idx = 0

    run_beginning_of_postcombat_main_triggers(py)
    assert len(py.stack) == 1, (
        f"Python: exactly 1 trigger (Savior of the Small "
        f"ReturnCreature) must be on the stack; got {len(py.stack)}"
    )
    drain_stack(py)

    py_gy_after = len(py.players[0].graveyard)
    py_hand_after = len(py.players[0].hand)
    assert py_gy_after == 0 and py_hand_after == 1, (
        f"Python: Emissary Escort must move gy -> hand; got "
        f"gy={py_gy_after}, hand={py_hand_after}"
    )

    # ------------------------------------------------------------------
    # 6. Cross-engine byte-equality on targeted observables.
    # ------------------------------------------------------------------
    assert rs_gy_after == py_gy_after == 0, (
        f"p0 graveyard: Rust={rs_gy_after}, Python={py_gy_after} "
        "(must be byte-equal at 0 -- Emissary Escort moved gy -> "
        "hand identically on both engines post-VVV-Pin-1 closure)"
    )
    assert rs_hand_after == py_hand_after == 1, (
        f"p0 hand: Rust={rs_hand_after}, Python={py_hand_after} "
        "(must be byte-equal at 1 -- Emissary Escort lands in p0's "
        "hand on both engines)"
    )
    assert rs.get_life(0) == py.players[0].life == 20, (
        f"p0 life: Rust={rs.get_life(0)}, Python={py.players[0].life} "
        f"(must be byte-equal at 20 -- ReturnCreature doesn't touch "
        "life)"
    )
    assert rs.get_life(1) == py.players[1].life == 20, (
        f"p1 life: Rust={rs.get_life(1)}, Python={py.players[1].life} "
        f"(must be byte-equal at 20 -- untouched)"
    )
    # Bf size: Savior remains; Emissary Escort never reached bf (gy
    # -> hand, not gy -> bf).
    assert rs.battlefield_sizes[0] == len(py.battlefield) == 1, (
        f"p0 battlefield: Rust={rs.battlefield_sizes[0]}, "
        f"Python={len(py.battlefield)} (must be byte-equal at 1 -- "
        "Savior of the Small only; Emissary Escort returned to hand "
        "not bf)"
    )
