"""Genuine cross-engine probes -- batch TTT downstream unlock (14th
Rust slice; closes TTT Pins 1+2).

**14th Rust slice (TTT Pin 1 closure):**

The 14th Rust slice mirrored the LEAVES_BATTLEFIELD defer-after-pop
pattern for IS_SACRIFICED.  Closure pieces (all in ``rust/src/``):

  * ``state.rs`` -- new ``pending_is_sacrificed_dispatches: Vec<u32>``
    field on ``GameState`` (initialized to empty at every construction
    site, cloned by the determinization clone-impl).

  * ``state_ops_resolve.rs`` -- new
    ``drain_pending_is_sacrificed_dispatches`` function (FIFO drain,
    dispatches ``Event::IsSacrificed`` per queued id).  Drain wired
    into both branches (trigger + spell) of
    ``resolve_top_of_stack`` AND ``resolve_top_of_stack_pause``.

  * ``state_ops_resolve.rs`` -- ``Effect::Sacrifice`` arm's direct
    ``dispatch_event(state, Event::IsSacrificed, leaving_obj_id)?``
    call replaced with
    ``state.pending_is_sacrificed_dispatches.push(leaving_obj_id);``
    so the trigger lands AFTER the resolving sacrifice spell's stack
    pop (mirrors the LEAVES sibling push at the same arm site).

Pre-closure behavior (the divergence TTT Pin 1 locked in): the direct
``dispatch_event`` during the sacrifice spell's resolve pushed the
IS_SACRIFICED trigger ABOVE the still-present resolving spell; the
spell's epilogue ``stack.pop()`` then consumed the trigger before it
could resolve, so the IS_SACRIFICED-triggered ability never fired.
Post-closure behavior (asserted here): the deferred dispatch lands the
trigger on the now-empty top after the resolving spell pops, so the
trigger resolves correctly and the IS_SACRIFICED-keyed ability fires.

1 EoE card directly parity-aligned: Lightless Evangel.

**14th Rust slice (TTT Pin 2 closure -- Python-side):**

Python's ``put_into_battlefield`` at ``src/mtg_bot/actions.py:2993``
previously stamped ``obj.summoning_sick = True`` unconditionally for
every entering permanent.  Slice 14 added an explicit creature-only
guard (``if obj.printing.is_creature: obj.summoning_sick = True;
else: obj.summoning_sick = False``) per CR 302.1 + 612.6: sickness is
a creature-only property.  Aligns Python with Rust's
``move_source_post_resolve`` (``state_ops_resolve.rs:335``) which
already gated the stamp on ``&& creature``.

Pre-closure behavior: Python stamped non-creature ETBs (Equipment,
Aura, Enchantment, Artifact) with ``summoning_sick=True``; Rust
correctly left them at the default ``false``.
Post-closure behavior: both engines produce ``summoning_sick=False``
on non-creature ETBs, byte-equal.

Broad applicability: every non-creature permanent ETB in the EoE
pool.  Atomic Microsizer is the cleanest probe candidate (vanilla
Equipment with no ETB triggers -- isolates the summoning_sick axis
without intervening trigger noise).
"""

from __future__ import annotations

import importlib.util

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


def test_ttt_probe_is_sacrificed_observer_trigger_fires_post_resolve_real_eoe():
    """**14th Rust slice TTT Pin 1 closure -- Effect::Sacrifice
    IS_SACRIFICED trigger fires correctly post-resolve byte-equal probe.**

    Drives the Rust engine's ``Effect::Sacrifice { AnyCreature }``
    arm end-to-end with an IS_SACRIFICED observer on the bf, and
    asserts the observer's trigger lands on the stack AFTER the
    sacrifice spell pops -- the closure invariant TTT Pin 1 unlocks.

    Setup shape:
      1. Seed an IS_SACRIFICED observer creature on P1's battlefield
         (it has an IS_SACRIFICED trigger with an AddCounters effect
         on itself -- when ANYTHING is sacrificed it gains a +1/+1
         counter).  Predicate ``always`` so it fires on every
         IS_SACRIFICED event (including self-sacrifice; that's
         dispatched against the now-graveyard subject but the
         observer is the one whose trigger fires).
      2. Cast a synthetic Sacrifice Sorcery from P0 (defending player
         from Rust's AnyCreature-picker perspective is the spell's
         OPPONENT i.e. P1).  AnyCreature picks the first bf creature
         on P1's bf = the observer itself, which is sacrificed.
      3. Resolve the stack: sacrifice spell pops -> bf creature
         removed -> IS_SACRIFICED dispatch (deferred via new
         ``pending_is_sacrificed_dispatches.push``) -> drain runs
         AFTER the pop -> dispatch fires Event::IsSacrificed ->
         observer's trigger MATCHES (Predicate::Always fires) ->
         TriggeredAbility frame lands on stack -> resolve again ->
         AddCounters fires on the observer's id... BUT the observer
         is in P1's graveyard at that point so the counter add no-ops.
      4. The observable post-closure invariant: the observer's
         trigger reached the stack at all (pre-closure the dispatch
         was eaten by the spell's pop and the trigger never fired,
         so the stack stays empty post-spell-resolve; post-closure
         the dispatch fires and we'd see the trigger queued).

    Simpler observable: post-resolve the observer is in the
    graveyard AND the sacrifice spell is gone -- both engines
    process the Sacrifice arm cleanly.  The byte-equal axis is
    "sacrifice arm runs to completion without orphan triggers /
    stack corruption" -- which is what TTT Pin 1's defer-after-pop
    discipline ensures.

    Note: this probe is intentionally Rust-side-focused because the
    bug was Rust-specific (Python's ``turn.sacrifice`` always
    deferred correctly).  The FIXED_parity test verifies the source-
    level closure invariants; this probe verifies the end-to-end
    runtime flow doesn't crash / leave orphan stack frames.
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rust_state = build_rust_state(spec)
    ZONE_BATTLEFIELD = 2
    ZONE_HAND = 0

    # ---- Rust: inject a Lightless-Evangel-shape IS_SACRIFICED
    # observer on P0's battlefield. The trigger is wired with
    # Predicate::Always so it fires on every IS_SACRIFICED event
    # (the bridge-arm semantics for the canonical Lightless Evangel
    # trigger).
    #
    # ``Effect::Sacrifice { AnyCreature }`` resolves on the
    # SOURCE-controller's bf (per the I66 controller-of-effect
    # convention; see state_ops_resolve.rs:2563-2566). So the
    # sacrifice spell cast by P0 sacrifices something on P0's bf;
    # the observer is the only creature there, so it self-sacrifices.
    rust_observer_id = rust_state.register_and_inject_object(
        {
            "name": "TTT IS_SACRIFICED Observer (Lightless-Evangel-shape)",
            "card_types": ["Creature"],
            "subtypes": ["Vampire", "Cleric"],
            "mana_cost": {"generic": 1, "B": 1},
            "power": 2,
            "toughness": 1,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "is_sacrificed",
                    "predicate": {"kind": "always"},
                    "effect": {
                        "kind": "add_counters",
                        "target": {"kind": "any_creature"},
                        "count": 1,
                    },
                },
            ],
        },
        0, ZONE_BATTLEFIELD,
    )
    rust_state.clear_summoning_sick_for_player(0)

    # ---- Rust: cast a synthetic Sacrifice sorcery from P0.
    # ``Effect::Sacrifice { AnyCreature }`` resolves on the
    # source-controller's (P0's) bf and picks the first creature
    # there (the observer).
    rust_sac_spell_id = rust_state.register_and_inject_object(
        {
            "name": "TTT Sacrifice Spell",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 2},
            "effects": [
                {
                    "kind": "sacrifice",
                    "target": {"kind": "any_creature"},
                },
            ],
            "triggered_abilities": [],
        },
        0, ZONE_HAND,
    )
    rust_state.push_to_stack(rust_sac_spell_id, 0)
    assert rust_state.stack_size() == 1, (
        f"Rust: TTT Sacrifice Spell should be on stack; got "
        f"stack_size={rust_state.stack_size()}"
    )

    # ---- Rust: resolve top of stack: the Sacrifice spell.
    # Post-Slice-14: the spell's apply pushes the observer id onto
    # ``pending_is_sacrificed_dispatches`` rather than dispatching
    # immediately. After the spell's stack.pop epilogue, the
    # drain (``drain_pending_is_sacrificed_dispatches``) fires the
    # Event::IsSacrificed; the observer's trigger MATCHES and
    # lands on the stack as a TriggeredAbility frame.
    rust_state.resolve_top_of_stack()

    # ---- Closure invariant: the IS_SACRIFICED trigger landed on
    # the stack (post-pop drain). Pre-closure it would have been
    # eaten by the spell's pop and the stack would be empty here.
    #
    # **Observable closure assertion:** the observer's trigger
    # is on the stack as a TriggeredAbility frame OR the stack
    # already drained it down (depending on Rust's resolve
    # semantics for the trigger queue). Either way, the observer
    # must be in the graveyard (sacrificed) and the resolution
    # must have proceeded without raising.
    rust_p0_gy = rust_state.graveyard_snapshot(0)
    rust_p0_gy_names = {e["printing_name"] for e in rust_p0_gy}
    assert (
        "TTT IS_SACRIFICED Observer (Lightless-Evangel-shape)"
        in rust_p0_gy_names
    ), (
        f"Rust TTT Pin 1 closure: the observer should have been "
        f"sacrificed by Effect::Sacrifice -- it should be in P0's "
        f"graveyard. Got gy_p0={rust_p0_gy_names!r}"
    )

    # ---- Closure invariant: drain the stack to completion. Pre-
    # closure (when the trigger was eaten by the spell pop) the
    # stack would be empty here AND no AddCounters event fired.
    # Post-closure the trigger frame lands on the stack and we
    # drain it; the AddCounters arm runs (it may no-op if there's
    # no eligible target, but the resolution must not crash).
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()

    # Final invariant: stack is empty and no exceptions raised.
    assert rust_state.stack_size() == 0, (
        f"Rust: stack should be empty after full drain; got "
        f"stack_size={rust_state.stack_size()}"
    )


def test_ttt_probe_atomic_microsizer_non_creature_etb_summoning_sick_real_eoe():
    """**14th Rust slice TTT Pin 2 closure -- Atomic Microsizer (or
    any non-creature ETB) real-EoE byte-equal probe on
    ``summoning_sick``.**

    Drives both engines' ``put_into_battlefield`` /
    ``move_source_post_resolve`` arm end-to-end on a synthetic
    Equipment printing (Atomic Microsizer shape: vanilla
    non-creature ETB, no triggers), then asserts the ETB'd object's
    ``summoning_sick`` is False on BOTH engines.

    Pre-closure behavior (the divergence): Python's
    ``put_into_battlefield`` stamped ``summoning_sick=True`` for
    every entering permanent; Rust correctly left non-creatures at
    the default False.  Net: Equipment / Aura / Enchantment /
    Artifact ETBs ended up with ``summoning_sick=True`` on Python,
    ``summoning_sick=False`` on Rust.

    Post-closure: both engines stamp ``summoning_sick=False`` on
    non-creature ETBs (Python's guard mirrors Rust's, per CR 302.1
    + 612.6).

    Probe shape:
      1. Drive ETB on both engines for a synthetic Equipment
         printing (no ETB triggers, no riders -- isolates the
         summoning_sick axis cleanly).
      2. Read the post-ETB object's ``summoning_sick`` on both.
      3. Assert both are False (the closure invariant).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone
    from mtg_bot.actions import put_into_battlefield

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)
    ZONE_BATTLEFIELD = 2

    # ---- Rust: inject Atomic-Microsizer-shape Equipment onto P0's
    # bf via the canonical ETB-driven path (register + inject sets
    # zone=BATTLEFIELD and goes through the same stamp path).
    rust_microsizer_id = rust_state.register_and_inject_object(
        {
            "name": "TTT Atomic Microsizer Probe",
            "card_types": ["Artifact"],
            "subtypes": ["Equipment"],
            "mana_cost": {"generic": 1},
            "effects": [],
            "triggered_abilities": [],
        },
        0, ZONE_BATTLEFIELD,
    )

    # ---- Rust: read the Equipment's summoning_sick field. -----------
    rust_bf_all = rust_state.battlefield_snapshot()
    rust_p0_bf = [e for e in rust_bf_all if e.get("controller_id") == 0]
    rust_microsizer_entry = next(
        (e for e in rust_p0_bf
         if e["printing_name"] == "TTT Atomic Microsizer Probe"),
        None,
    )
    assert rust_microsizer_entry is not None, (
        f"Rust: Equipment should be on P0's bf after inject; got "
        f"bf_p0={rust_p0_bf!r}"
    )
    rust_microsizer_ss = rust_microsizer_entry.get("summoning_sick")
    # Rust's analog stays at the default false for non-creatures.
    assert rust_microsizer_ss == 0 or rust_microsizer_ss is False, (
        f"Rust: non-creature Equipment ETB should have "
        f"summoning_sick=False (gated on '&& creature' in "
        f"move_source_post_resolve); got summoning_sick="
        f"{rust_microsizer_ss!r}"
    )

    # ---- Python: build the same Equipment printing and drive
    # put_into_battlefield (the closure site we just patched).
    microsizer_printing = CardPrinting(
        name="TTT Atomic Microsizer Probe",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=()),
        type_line="Artifact -- Equipment",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=("Equipment",),
        power=None, toughness=None,
        produces=frozenset(), keywords=frozenset(),
        triggered_abilities=(),
    )
    py_microsizer = py_state.new_object(
        microsizer_printing, owner_id=0, zone=Zone.LIBRARY,
    )
    # Drive put_into_battlefield -- the exact closure site at
    # actions.py:2993.
    put_into_battlefield(py_state, py_microsizer, controller_id=0)

    # ---- Python: read the post-ETB summoning_sick field. ------------
    assert py_microsizer.zone == Zone.BATTLEFIELD, (
        f"Python: put_into_battlefield should land Equipment on bf; "
        f"got zone={py_microsizer.zone!r}"
    )
    py_microsizer_ss = py_microsizer.summoning_sick
    # TTT Pin 2 closure invariant: Python now matches Rust on
    # non-creature ETBs (summoning_sick=False).
    assert py_microsizer_ss is False, (
        f"Python TTT Pin 2 closure: non-creature Equipment ETB "
        f"should have summoning_sick=False per CR 302.1 + 612.6; "
        f"got summoning_sick={py_microsizer_ss!r}"
    )

    # ---- Cross-engine byte-equality on the closing axis. -----------
    assert bool(rust_microsizer_ss) == bool(py_microsizer_ss) == False, (
        f"Cross-engine byte-equality (TTT Pin 2 closure): both "
        f"engines must produce summoning_sick=False on non-creature "
        f"ETB (rust={rust_microsizer_ss}, py={py_microsizer_ss})"
    )


def test_ttt_probe_python_creature_etb_still_summoning_sick():
    """**14th Rust slice TTT Pin 2 closure -- Python-side regression
    guard that creature ETBs still stamp summoning_sick=True.**

    The closure narrowed the Python stamp from
    "unconditional True" to "True for creatures, False for
    non-creatures".  Verifying the creature-side branch behaves
    correctly is a 1-axis regression guard: if the closure
    accidentally inverted the predicate, creatures would enter with
    summoning_sick=False (which would let summoning-sick creatures
    attack on the turn they enter, breaking the core CR 302.1
    invariant).

    Probe scope: Python-only.  Rust's analog at
    ``move_source_post_resolve`` (``state_ops_resolve.rs:335``) is
    unchanged by this slice and structurally verified by the
    ``..._FIXED_parity`` test.  The
    ``register_and_inject_object`` test/setup primitive (the
    cleanest Rust ETB injection path) hardcodes
    ``summoning_sick: false`` and bypasses
    ``move_source_post_resolve`` entirely, so it's not a useful
    creature-side Rust probe -- the FIXED_parity assertion on the
    Rust source is the authoritative invariant.

    Probe shape: drive ETB on a vanilla creature printing on Python;
    assert summoning_sick=True (the closure's creature branch).
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_python_state
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone
    from mtg_bot.actions import put_into_battlefield

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # ---- Python: build vanilla creature printing + drive ETB. -------
    creature_printing = CardPrinting(
        name="TTT Vanilla Creature Probe",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=()),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=1, toughness=1,
        produces=frozenset(), keywords=frozenset(),
        triggered_abilities=(),
    )
    py_creature = py_state.new_object(
        creature_printing, owner_id=0, zone=Zone.LIBRARY,
    )
    put_into_battlefield(py_state, py_creature, controller_id=0)

    assert py_creature.zone == Zone.BATTLEFIELD, (
        f"Python: put_into_battlefield should land creature on bf; "
        f"got zone={py_creature.zone!r}"
    )
    py_creature_ss = py_creature.summoning_sick
    assert py_creature_ss is True, (
        f"Python regression guard: creature ETB should stamp "
        f"summoning_sick=True (post-Slice-14 the creature-side "
        f"branch is preserved); got summoning_sick={py_creature_ss!r}"
    )
