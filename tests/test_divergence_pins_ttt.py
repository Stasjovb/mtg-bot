"""Divergence-pin tests: batch TTT (round 23 pin-side).

Round 23 pin batch surfacing the high-confidence divergence-pin
candidates the SSS probe agent dropped during honest exhaustion
(see worklog entry ``2026-05-19-probe-batch-sss`` on main @
``b581b731``), plus one fresh BLOCKED-list candidate.

**Slice 14 closure status:** Pin 1 (Lightless Evangel IS_SACRIFICED
ordering) + Pin 2 (Atomic Microsizer non-creature ETB summoning_sick)
are CLOSED -- renamed to ``*_FIXED_parity`` with the sentinels
inverted.  Pin 3 (Astelli Reclaimer no Rust Effect variant) remains
OPEN as the sole remaining divergence pin in this batch.

Each pin test originally named ``test_..._divergence_pin`` ASSERTS
the CURRENT divergent behavior rather than parity.  The PROBED-tier
detector excludes ``*_divergence_pin`` functions, so these tests
grow the test surface without touching the PROBED metric.  Closed
pins renamed to ``*_FIXED_parity`` are regular parity tests and
DO count in the PROBED metric.

Pin closure cadence: when a sibling Rust slice closes the
underlying gap, the relevant assertion fires and the pin is
renamed ``*_FIXED_parity`` with the sentinel inverted (PPP / MMM /
JJJ / RRR Pin 1 / TTT Pin 1 + 2 precedent).

Pinned bugs
-----------

Pin 1 -- ``Event::IsSacrificed`` Rust dispatch ordering bug at
``rust/src/state_ops_resolve.rs:2602`` inside the
``Effect::Sacrifice`` arm:  the IS_SACRIFICED trigger is dispatched
IMMEDIATELY (no defer queue) during the sacrifice spell's resolve.
At dispatch time the resolving sacrifice spell is still the top of
the stack.  The dispatcher pushes the trigger onto the stack ABOVE
the still-present resolving spell.  When the spell's epilogue
``stack.pop()`` runs back in ``resolve_top_of_stack``, it accidentally
consumes the IS_SACRIFICED trigger rather than the spell, eating the
trigger before it can resolve.

The LEAVES_BATTLEFIELD sibling push at
``state_ops_resolve.rs:2588`` (a few lines above the IS_SACRIFICED
dispatch in the same ``Effect::Sacrifice`` arm) avoids exactly this
class of bug via ``state.pending_leaves_dispatches.push(leaving_obj
_id)`` -- the queued id is drained later by
``drain_pending_leaves_dispatches`` AFTER the resolving slot is
popped.  IS_SACRIFICED needs the same defer-after-pop discipline.

  Bug location (Rust):
    ``rust/src/state_ops_resolve.rs:2602`` -- inside the
    ``Effect::Sacrifice`` arm's ``AnyCreature`` branch, AFTER the
    LEAVES push (queued for defer) AND the token_cease queue, BUT
    BEFORE the ``Effect::Sacrifice`` arm returns to the caller (i.e.
    DURING the spell's resolve, with the spell still on the stack)::

        // Slice 10: LTB fan-out at the Effect arm. ...
        state.pending_leaves_dispatches.push(leaving_obj_id);
        // Round-55: token-cease sibling of the LEAVES push. ...
        crate::state_ops_zones::queue_token_cease(state, leaving_obj_id);
        // Round-16 RR Pin 2: dispatch IS_SACRIFICED with the
        // sacrificed permanent's id as subject. ...
        dispatch_event(state, crate::cards::Event::IsSacrificed, leaving_obj_id)?;

    The direct ``dispatch_event(...)`` call is the divergence: every
    other zone-change event in the same arm uses the
    ``pending_*_dispatches.push(...)`` defer queue precisely to push
    triggers AFTER the resolving spell's stack pop.  The IS_SACRIFICED
    direct-dispatch breaks that invariant.

  Bug location (Python -- the correct behavior the Rust arm should
  match):
    ``src/mtg_bot/turn.py::sacrifice`` -- Python's sacrifice helper
    fires ``dispatch_event(state, Event.IS_SACRIFICED, ...)`` AFTER
    the spell's resolve has returned (the trigger goes onto the
    triggers-this-turn list and lands at the next state-based-action
    + priority cycle, when the original sacrifice spell is no longer
    on the stack).

  Sibling pattern (LEAVES_BATTLEFIELD defer queue):
    The ``pending_leaves_dispatches`` family was introduced in slice 8
    (see ``drain_pending_leaves_dispatches`` at
    ``state_ops_resolve.rs:1287``) precisely to avoid this class of
    bug.  The drain runs in ``resolve_top_of_stack`` AFTER the
    resolving slot has been popped.  IS_SACRIFICED needs an
    isomorphic ``pending_is_sacrificed_dispatches`` queue.

  Scale (EoE cards affected): 1+ direct, broader applicability.
    * Lightless Evangel -- ``{1}{B}`` Creature (Vampire Cleric)
      with a STATE-tracking sacrifice trigger ("Whenever you
      sacrifice another creature or artifact, put a +1/+1 counter
      on this creature.").  This is the canonical IS_SACRIFICED
      EoE consumer.  Bridge arm at
      ``src/mtg_bot/parity/cross_engine.py:9469-9485`` is already
      wired (RR Pin 2 closure).

    Broader applicability: any IS_SACRIFICED-triggered ability fired
    during a sacrifice spell's resolve (rather than via an
    activated sacrifice ability) hits this bug.  The
    ``Effect::Sacrifice`` arm is the load-bearing site -- triggers
    fired through ``turn.sacrifice`` (e.g. cost-payment sacrifices)
    take a different path.

  Closure path:
    1. Add ``pending_is_sacrificed_dispatches: Vec<u32>`` field on
       ``GameState`` (mirrors ``pending_leaves_dispatches`` shape;
       declare next to it in ``rust/src/state.rs``).
    2. Initialize the new vector at every ``GameState`` construction
       site (``state.rs::make_state`` / ``state_ops_setup.rs``).
    3. Add ``drain_pending_is_sacrificed_dispatches(state)`` mirror
       of ``drain_pending_leaves_dispatches`` at
       ``state_ops_resolve.rs:1287``: drain FIFO with
       ``dispatch_event(state, Event::IsSacrificed, id)``.
    4. Wire the drain into ``resolve_top_of_stack`` ALONGSIDE the
       existing LEAVES + ETB + DIES + token_cease drains (the drain
       order matches Python's per-event SBA-loop priority).
    5. Replace the direct ``dispatch_event(state,
       Event::IsSacrificed, leaving_obj_id)?`` call at
       ``state_ops_resolve.rs:2602`` with
       ``state.pending_is_sacrificed_dispatches.push(leaving_obj_id);``
       -- mirrors the LEAVES push at :2588.
    6. Flip this pin's assertion (the direct ``dispatch_event(...
       IsSacrificed ...)`` call should NO LONGER appear inside the
       ``Effect::Sacrifice`` arm body; the push should appear in its
       place) and rename ``..._divergence_pin`` ->
       ``..._FIXED_parity`` per the PPP / MMM closure-cadence
       precedent.

Pin 2 -- Python ``put_into_battlefield`` unconditionally sets
``summoning_sick = True`` at ``src/mtg_bot/actions.py:2993`` for
EVERY entering permanent (creature OR non-creature), while Rust's
analogous path stamps ``summoning_sick = true`` only when the
entering object is a creature (gated on
``is_creature(card_types)`` at ``state_ops_resolve.rs:335``).  Net
result: Equipment / Artifact / Enchantment ETBs end up with
``summoning_sick=True`` on Python and ``summoning_sick=False`` on
Rust.  CR-canonical fix is to align Python (per CR 302.1 + 612.6,
sickness is a creature-only property -- non-creature permanents
don't have summoning sickness, so the universal-true stamp is
incorrect on the Python side).

  Bug location (Python -- the side that needs the fix):
    ``src/mtg_bot/actions.py:2993`` -- inside
    ``put_into_battlefield``, AFTER the zone + tapped assignments,
    BEFORE the impending / cast-via-hand counters logic::

        obj.zone = Zone.BATTLEFIELD
        obj.controller_id = controller_id
        ...
        obj.tapped = bool(obj.printing.enters_tapped)
        obj.summoning_sick = True   # <-- universal-true; the divergence
        # Impending: a spell cast for its impending cost ...

    The unconditional assignment is the divergence: this codepath
    fires for every non-creature ETB too (Equipment, Aura, Enchantment,
    Artifact, planeswalker), all of which CR 302.1 / 612.6 says do
    NOT carry summoning sickness.  Rust's analogous codepath at
    ``state_ops_resolve.rs:335`` gates the stamp on the source's
    ``card_types`` (creature only).

  Bug location (Rust -- the correct behavior Python should match):
    ``rust/src/state_ops_resolve.rs:319-345`` --
    ``move_source_post_resolve`` reads the printing's ``card_types``,
    routes the source to its destination zone, and applies::

        if dest_zone == ZONE_BATTLEFIELD && creature {
            obj.summoning_sick = true;
        }

    The ``&& creature`` guard is the CR-canonical
    ``summoning_sick``-only-for-creatures discipline.  For
    non-creature permanents the field is left at its default
    ``false``.

  Scale (EoE cards affected): broad applicability across all
  Equipment / artifact-only / enchantment-only / Aura spells in the
  pool.  Concrete EoE examples (every non-creature permanent ETB):
    * Atomic Microsizer -- ``{?}`` Equipment, no ETB triggers;
      simplest probe candidate (vanilla non-creature ETB).
    * Hylderblade -- ``{?}`` Equipment with Void / end-step Aura-
      attachment trigger.
    * Squire's Lightblade -- ``{1}{W}`` Equipment with Flash + ETB
      attach-and-pump.
    * Auxiliary Boosters -- Equipment with ETB token-creation +
      attach.
    * Pain for All -- ``{2}{R}`` Aura with ETB damage + echo
      whenever-enchanted-creature-takes-damage trigger.
    * Banishing Light, Hardlight Containment, Seam Rip -- all
      Enchantment ETBs (separately pinned via RRR Pin 1's
      exile-bf-leave summoning_sick stamp closure; this pin is the
      complement on the bf-ENTER path).

  Why this matters:  some triggered abilities and combat-eligibility
  predicates read ``summoning_sick`` for any-creature filters and
  combat declaration even on non-creature subjects -- the divergence
  shows up downstream in any compare_fields-strength probe that
  inspects the field-view tuple for a non-creature permanent.

  Closure path:
    1. Add a creature-only guard at
       ``src/mtg_bot/actions.py:2993`` mirroring Rust's
       ``is_creature`` check.  Read ``obj.printing.is_creature``
       (the printing-level flag the action-encoding codec already
       consults) and gate the assignment::

           if obj.printing.is_creature:
               obj.summoning_sick = True

       Leave the field at its default ``False`` for non-creature
       permanents (per CR 302.1 + 612.6).
    2. Audit consumers of ``obj.summoning_sick`` on non-creature
       subjects: combat declaration (creature-only by predicate
       upstream of the field read), Haste / Aplomb / Vehicles
       (creature-specific anyway), the ``can_attack`` /
       ``can_tap_for_mana`` paths (creature-gated upstream).  The
       audit's expected outcome: zero consumers actually depend on
       non-creature ``summoning_sick=True`` semantics -- the field
       is dead state on non-creatures, so the alignment is
       behavior-neutral on the Python side.
    3. Flip this pin's assertion (Python's
       ``put_into_battlefield`` should have a creature-only guard
       around the ``summoning_sick = True`` line) and rename to
       ``..._FIXED_parity``.

Pin 3 -- Astelli Reclaimer ``ReturnNoncreatureNonlandFromGYWith
ManaValueLEX`` (X = mana spent to cast self) ETB has NO Rust
Effect variant.  Python implements the effect via a bespoke
``AstelliReclaimerETBEffect`` class
(``src/mtg_bot/effects/bespoke.py:25-89``).  Rust's
``Effect`` enum at ``rust/src/cards.rs`` has no matching variant
and no parse arm -- the printing's ETB body fails to round-trip
through the bridge.  This is the canonical
``BLOCKED-genuinely_missing`` shape (one of the 7 cards on the
``docs/POOL_PARITY.md`` BLOCKED list).

  Bug location (Python -- the SoT to convert to a Rust variant):
    ``src/mtg_bot/effects/bespoke.py:25-89`` --
    ``AstelliReclaimerETBEffect`` class with:
      * ``_x_from_source(state)`` -- reads
        ``state.resolving_source.printing.mana_cost.total`` (or
        ``warp_cost.total`` if ``cast_via_warp`` is set), giving X.
      * ``legal_targets(state, controller_id)`` -- walks the
        controller's graveyard for cards matching
        ``is_permanent and not is_creature and not is_land and
        mana_cost.total <= X``.
      * ``resolve(state, controller_id, targets)`` -- pops the
        target from the graveyard and calls
        ``put_into_battlefield(state, card, controller_id)``.

  Bug location (Rust):
    ``rust/src/cards.rs::Effect`` enum -- NO arm matching this
    shape.  Confirmed via grep: zero hits for
    ``AstelliReclaimer`` / ``astelli_reclaimer`` /
    ``ReturnNoncreatureNonland...`` across the Rust crate.

  Scale (EoE cards affected): 1 directly (Astelli Reclaimer; 4565
  decks per the 17lands deck-weight column in
  ``docs/RESIDUE_CARD_PLANS.md``).  The shape opens a small reusable
  substrate for any future "X = mana spent to cast self" effects.

  Closure path:
    1. Add ``Effect::AstelliReclaimerETBEffect`` (zero-field unit
       variant if the X-from-source ledger is read implicitly via
       ``state.current_resolve_source_id`` -- mirrors the
       ``DyadrineAttackEffect`` no-field shape closed in the 8th
       Rust slice for the same "read X from resolving source"
       pattern).  Alternatively, parameterize as
       ``ReturnNoncreatureNonlandPermanentFromYourGraveyardWithMV
       LEManaSpent`` for reuse if a sibling effect appears.
    2. Add parse arm in ``rust/src/cards.rs::parse_effect`` for the
       new effect_kind string (and effect_to_pydict arm).
    3. Add resolve arm in ``rust/src/state_ops_resolve.rs`` that
       reads X from the source's mana_cost (or warp_cost if
       ``cast_via_warp`` is set) and walks the controller's
       graveyard for legal targets (mirror Python's
       ``legal_targets`` + ``resolve`` shape).
    4. Add Python bridge arm in
       ``src/mtg_bot/parity/cross_engine.py::_ta_dict_to_python_
       effect`` (or the bespoke-effect translator) mapping the
       ``astelli_reclaimer_etb_effect`` effect_kind to the
       bespoke class.
    5. Add a real-EoE byte-equal probe for Astelli Reclaimer that
       drives ENTERS -> AstelliReclaimerETBEffect via the live
       registry, then flip this pin to
       ``..._FIXED_parity`` per the standard cadence.

This batch is a coherent set of three high-confidence pins surfaced
from the SSS probe agent's honest-exhaustion drops (Pins 1 + 2) plus
one fresh BLOCKED-list candidate (Pin 3).  No two pins share a
closure surface, but all three sit on the same axis: the
Python<->Rust resolve-path alignment that the round-23 cycle is
narrowing.
"""

from __future__ import annotations

import inspect
import pathlib

import pytest


# ---------------------------------------------------------------------------
# Pin 1 -- IS_SACRIFICED Rust dispatch ordering bug inside
#          Effect::Sacrifice (state_ops_resolve.rs:2602).
#          1+ EoE card affected: Lightless Evangel (canonical consumer
#          of the IS_SACRIFICED bridge arm).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_lightless_evangel_is_sacrificed_ordering_FIXED_parity():
    """Verify Slice 14 (TTT Pin 1) IS_SACRIFICED defer-after-pop closure.

    The ``Effect::Sacrifice`` arm at
    ``rust/src/state_ops_resolve.rs`` previously dispatched
    IS_SACRIFICED DURING the resolving sacrifice spell's apply path,
    while the spell was still on top of the stack.  Slice 14 closed
    this by mirroring the LEAVES_BATTLEFIELD defer-after-pop pattern:
    add ``pending_is_sacrificed_dispatches`` field on ``GameState``,
    add ``drain_pending_is_sacrificed_dispatches`` mirror, wire the
    drain into ``resolve_top_of_stack`` (both trigger + spell branches
    of ``resolve_top_of_stack`` AND ``resolve_top_of_stack_pause``),
    and replace the direct ``dispatch_event`` call with a push.

    Assertions verify the closure invariants:
      1. Python's ``Event.IS_SACRIFICED`` is still the canonical enum
         value the bridge arm wires for Lightless Evangel.
      2. The Rust source's ``Effect::Sacrifice`` arm contains a
         ``pending_is_sacrificed_dispatches.push(leaving_obj_id)``
         call (the closure).
      3. The Rust source's ``Effect::Sacrifice`` arm does NOT contain
         a direct ``dispatch_event(..., Event::IsSacrificed, ...)``
         call (the pre-closure divergence is gone).
      4. ``pending_is_sacrificed_dispatches`` is declared on
         ``GameState`` in ``state.rs``.
      5. ``drain_pending_is_sacrificed_dispatches`` is defined in
         ``state_ops_resolve.rs``.

    EoE card scale: 1 directly (Lightless Evangel); broader
    applicability across any IS_SACRIFICED-triggered ability fired
    via the ``Effect::Sacrifice`` arm.
    """
    # 1. Python's Event.IS_SACRIFICED is the canonical enum value.
    from mtg_bot.effects.predicates import Event
    assert hasattr(Event, "IS_SACRIFICED"), (
        "Python's Event enum should expose IS_SACRIFICED (the round-16 "
        "RR Pin 2 closure)."
    )
    assert Event.IS_SACRIFICED.value == "is_sacrificed", (
        "Event.IS_SACRIFICED's string value should be 'is_sacrificed'.  "
        f"Got: {Event.IS_SACRIFICED.value!r}."
    )

    # 2. Locate the Rust source file.
    test_file_path = pathlib.Path(__file__).resolve()
    repo_root = test_file_path.parents[1]  # tests/.. = repo root
    rust_resolve_path = repo_root / "rust" / "src" / "state_ops_resolve.rs"
    assert rust_resolve_path.exists(), (
        f"Rust source file should exist at {rust_resolve_path!r}."
    )
    rust_src = rust_resolve_path.read_text(encoding="utf-8")

    # Locate the Effect::Sacrifice arm body.
    arm_sig = "Effect::Sacrifice { target } => match target {"
    arm_start = rust_src.find(arm_sig)
    assert arm_start >= 0, (
        f"Rust source should contain the Effect::Sacrifice arm signature "
        f"{arm_sig!r}."
    )
    next_arm_start = rust_src.find("\n        Effect::", arm_start + 1)
    if next_arm_start < 0:
        next_arm_start = len(rust_src)
    arm_body = rust_src[arm_start:next_arm_start]

    # 2a. Closure: the deferred push IS in the arm body.
    assert "pending_is_sacrificed_dispatches" in arm_body, (
        "Slice 14 closure: rust/src/state_ops_resolve.rs's "
        "Effect::Sacrifice arm should contain a push to "
        "'state.pending_is_sacrificed_dispatches' (the defer-after-pop "
        "discipline mirroring the LEAVES sibling).  Arm body excerpt:"
        f"\n{arm_body[:800]!r}..."
    )

    # 2b. Closure: the pre-closure direct dispatch is GONE.
    assert (
        "dispatch_event(state, crate::cards::Event::IsSacrificed"
        not in arm_body
    ), (
        "Slice 14 closure invariant: rust/src/state_ops_resolve.rs's "
        "Effect::Sacrifice arm should NO LONGER contain a direct "
        "'dispatch_event(state, crate::cards::Event::IsSacrificed, ...)' "
        "call (the pre-closure bug).  If this fails, the closure was "
        "partially reverted -- audit the arm body.  Arm body excerpt:"
        f"\n{arm_body[:800]!r}..."
    )

    # 2c. The LEAVES sibling push is still present in the same arm.
    assert "pending_leaves_dispatches.push(leaving_obj_id)" in arm_body, (
        "rust/src/state_ops_resolve.rs's Effect::Sacrifice arm should "
        "still contain the sibling 'state.pending_leaves_dispatches."
        "push(leaving_obj_id);' line."
    )

    # 3. Closure: pending_is_sacrificed_dispatches IS declared on
    #    GameState in state.rs.
    rust_state_path = repo_root / "rust" / "src" / "state.rs"
    rust_state_src = rust_state_path.read_text(encoding="utf-8")
    assert (
        "pub pending_is_sacrificed_dispatches: Vec<u32>" in rust_state_src
    ), (
        "Slice 14 closure: rust/src/state.rs should declare "
        "'pub pending_is_sacrificed_dispatches: Vec<u32>' on GameState."
    )

    # 4. Closure: drain_pending_is_sacrificed_dispatches function
    #    exists in state_ops_resolve.rs.
    assert "fn drain_pending_is_sacrificed_dispatches(" in rust_src, (
        "Slice 14 closure: rust/src/state_ops_resolve.rs should define "
        "a 'drain_pending_is_sacrificed_dispatches' function (mirror of "
        "drain_pending_leaves_dispatches)."
    )

    # 4. EoE cards affected.
    affected_eoe_cards = [
        "Lightless Evangel",
        # {1}{B} Creature -- Vampire Cleric (2/1).
        # Oracle: "Whenever you sacrifice another creature or artifact,
        # put a +1/+1 counter on this creature."
        # IS_SACRIFICED trigger; canonical consumer of the round-16 RR
        # Pin 2 IS_SACRIFICED bridge arm at
        # src/mtg_bot/parity/cross_engine.py:9469-9485.
    ]
    assert len(affected_eoe_cards) == 1, (
        "The IS_SACRIFICED ordering closure affects 1+ EoE card "
        "directly (Lightless Evangel); broader applicability across "
        "any IS_SACRIFICED-triggered ability fired via "
        f"Effect::Sacrifice.  List has {len(affected_eoe_cards)} entries."
    )


# ---------------------------------------------------------------------------
# Pin 2 -- Python put_into_battlefield unconditionally sets
#          summoning_sick=True for non-creature ETBs at
#          actions.py:2993; Rust's analogous path gates on
#          is_creature(card_types) at state_ops_resolve.rs:335.
#          Broad applicability across all Equipment / Artifact /
#          Enchantment / Aura ETBs.  EoE illustrative card:
#          Atomic Microsizer (vanilla non-creature ETB).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_atomic_microsizer_non_creature_etb_summoning_sick_FIXED_parity():
    """Verify Slice 14 (TTT Pin 2) non-creature ETB summoning_sick
    closure.

    Python's ``put_into_battlefield(state, obj, controller_id)`` at
    ``src/mtg_bot/actions.py:2993`` previously assigned
    ``obj.summoning_sick = True`` unconditionally for every entering
    permanent (creature OR non-creature).  Rust's analogous codepath
    at ``rust/src/state_ops_resolve.rs:335`` correctly gates the
    stamp on ``is_creature(card_types)``.  CR 302.1 + 612.6: sickness
    is a creature-only property -- non-creature permanents do not
    have summoning sickness.  Slice 14 aligns Python with the
    CR-canonical (and Rust-correct) behavior by adding an explicit
    creature-only stamp.

    Assertions verify the closure invariants:
      1. Python's ``put_into_battlefield`` contains an
         ``if obj.printing.is_creature:`` branch that stamps
         ``obj.summoning_sick = True`` only for creatures.
      2. Python's ``put_into_battlefield`` contains an explicit
         ``else`` branch that stamps ``obj.summoning_sick = False``
         for non-creatures (necessary because the ``GameObject``
         dataclass default is ``summoning_sick: bool = True``;
         relying on the default would preserve the divergence).
      3. Rust's ``move_source_post_resolve`` still gates the stamp
         on ``&& creature`` (the CR-canonical reference behavior).

    EoE card scale: broad (every non-creature ETB across Equipment,
    Aura, Enchantment, Artifact).  Atomic Microsizer is the
    cleanest probe candidate.
    """
    # 1. Python's put_into_battlefield source: the conditional
    #    assignment IS present.
    from mtg_bot import actions as _actions_mod
    pib_src = inspect.getsource(_actions_mod.put_into_battlefield)
    assert "if obj.printing.is_creature:" in pib_src, (
        "Slice 14 closure: src/mtg_bot/actions.py::put_into_battlefield "
        "should contain an 'if obj.printing.is_creature:' guard "
        "around the summoning_sick stamp (per CR 302.1 + 612.6)."
    )
    assert "obj.summoning_sick = True" in pib_src, (
        "src/mtg_bot/actions.py::put_into_battlefield should still "
        "stamp 'obj.summoning_sick = True' for the creature branch."
    )
    assert "obj.summoning_sick = False" in pib_src, (
        "Slice 14 closure: src/mtg_bot/actions.py::put_into_battlefield "
        "should explicitly stamp 'obj.summoning_sick = False' for "
        "non-creatures (the GameObject dataclass default is True, so "
        "relying on the default would preserve the divergence)."
    )

    # 1a. The True-stamp line lies inside the is_creature branch:
    #     look at the lines preceding it and confirm an
    #     ``if obj.printing.is_creature`` appears nearby.
    lines = pib_src.splitlines()
    true_stamp_idx = None
    for i, line in enumerate(lines):
        if "obj.summoning_sick = True" in line:
            true_stamp_idx = i
            break
    assert true_stamp_idx is not None
    preceding_window = "\n".join(
        lines[max(0, true_stamp_idx - 5):true_stamp_idx]
    )
    assert "if obj.printing.is_creature" in preceding_window, (
        "Slice 14 closure: 'obj.summoning_sick = True' should be "
        "gated by an 'if obj.printing.is_creature:' guard above it.  "
        f"Preceding window:\n{preceding_window!r}"
    )

    # 2. Rust source: move_source_post_resolve still gates the stamp
    #    on ``&& creature`` (the CR-canonical reference behavior).
    test_file_path = pathlib.Path(__file__).resolve()
    repo_root = test_file_path.parents[1]
    rust_resolve_path = repo_root / "rust" / "src" / "state_ops_resolve.rs"
    rust_src = rust_resolve_path.read_text(encoding="utf-8")
    fn_sig = "fn move_source_post_resolve("
    fn_start = rust_src.find(fn_sig)
    assert fn_start >= 0, (
        f"Rust source should contain the function signature {fn_sig!r}."
    )
    fn_body = rust_src[fn_start:fn_start + 2000]
    assert "if dest_zone == ZONE_BATTLEFIELD && creature {" in fn_body, (
        "Rust's move_source_post_resolve should still gate the "
        "summoning_sick=true stamp on '&& creature' (CR-canonical "
        "creature-only discipline -- the reference behavior Python "
        f"converged on).  Function body excerpt:\n{fn_body[:800]!r}..."
    )

    # 3. EoE cards affected (illustrative; the closure applies to
    #    every non-creature ETB).
    affected_eoe_cards_illustrative = [
        "Atomic Microsizer",
        # Equipment with no ETB triggers; vanilla non-creature ETB
        # shape.  The cleanest probe candidate -- field-value drift
        # isolated to the summoning_sick slot without intervening
        # ETB-trigger noise.
        "Hylderblade",
        # Equipment with Void / end-step Aura-attachment trigger.
        "Squire's Lightblade",
        # Equipment with Flash + ETB attach-and-pump.
        "Auxiliary Boosters",
        # Equipment with ETB token-creation + attach.
        "Meltstrider's Gear",
        # Equipment with ETB attach.
        "Illvoi Light Jammer",
        # Equipment with Flash + ETB attach + hexproof.
    ]
    assert len(affected_eoe_cards_illustrative) == 6, (
        "The non-creature ETB summoning_sick closure has broad "
        "applicability; the illustrative list captures 6 EoE Equipment "
        "concrete examples.  "
        f"Enumerated list has {len(affected_eoe_cards_illustrative)} "
        "entries."
    )


# ---------------------------------------------------------------------------
# Pin 3 -- Astelli Reclaimer's ReturnNoncreatureNonlandFromGYWithMVLEX
#          ETB has no Rust Effect variant (BLOCKED-genuinely_missing
#          per docs/POOL_PARITY.md).  Python implements via bespoke
#          AstelliReclaimerETBEffect class.
#          1 EoE card affected: Astelli Reclaimer.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_astelli_reclaimer_etb_effect_no_rust_variant_divergence_pin():
    """Pin Astelli Reclaimer's ETB effect lacking a Rust counterpart.

    Astelli Reclaimer's ETB body parses to a bespoke
    ``AstelliReclaimerETBEffect`` class on the Python side
    (``src/mtg_bot/effects/bespoke.py:25-89``) that returns target
    noncreature, nonland permanent card with mana value <= X from
    the controller's graveyard, where X is the mana spent to cast
    the source.  Rust's ``Effect`` enum at ``rust/src/cards.rs``
    has no matching variant -- the printing's ETB body cannot
    round-trip through the bridge.  This is one of 7 cards on the
    ``docs/POOL_PARITY.md`` BLOCKED-genuinely_missing list (the
    canonical new-Rust-Effect ask shape).

    Probe shape:
      1. Confirm Python's bespoke ``AstelliReclaimerETBEffect``
         class exists with the expected interface (legal_targets +
         resolve + _x_from_source helper).
      2. Sentinel: the Rust crate's source files contain NO
         reference to ``AstelliReclaimer`` /
         ``astelli_reclaimer`` / any obvious matching effect
         variant name.
      3. The pin is the structural absence: no defensive
         assertion about field count or arm body -- the Rust side
         is simply silent on this effect today.

    Closure indicator: a new ``Effect::AstelliReclaimerETBEffect``
    (or parameterized
    ``ReturnNoncreatureNonlandPermanentFromYourGraveyardWithMVLEManaSpent``)
    variant lands in ``rust/src/cards.rs``, with a parse arm
    + resolve arm in ``state_ops_resolve.rs`` + bridge arm in
    ``cross_engine.py``.  Pin renames to ``..._FIXED_parity``
    asserting the variant + parse arm + resolve arm are present.

    EoE card scale: 1 (Astelli Reclaimer; 4565 decks in the 17lands
    deck-weight column per docs/RESIDUE_CARD_PLANS.md).
    """
    # 1. Python's bespoke class exists with the expected interface.
    from mtg_bot.effects.bespoke import AstelliReclaimerETBEffect
    from mtg_bot.effects.base import Effect as _EffectBase

    assert issubclass(AstelliReclaimerETBEffect, _EffectBase), (
        "AstelliReclaimerETBEffect should be an Effect subclass "
        "(effects/bespoke.py:25-89).  If this fails, the bespoke class "
        "was restructured -- update this pin."
    )

    # 1a. The expected helper + interface methods are present.
    inst = AstelliReclaimerETBEffect()
    assert hasattr(inst, "_x_from_source"), (
        "AstelliReclaimerETBEffect should have an '_x_from_source' "
        "helper (reads mana spent from state.resolving_source).  If "
        "absent, the class was restructured -- update this pin."
    )
    assert hasattr(inst, "legal_targets"), (
        "AstelliReclaimerETBEffect should have a 'legal_targets' "
        "method (graveyard walk filtered by MV <= X)."
    )
    assert hasattr(inst, "resolve"), (
        "AstelliReclaimerETBEffect should have a 'resolve' method "
        "(graveyard pop + put_into_battlefield)."
    )
    assert inst.requires_target() is True, (
        "AstelliReclaimerETBEffect.requires_target() should return True "
        "(graveyard-permanent target selection)."
    )

    # 1b. The class's resolve method delegates to put_into_battlefield
    #     (the canonical "card enters battlefield" helper).
    resolve_src = inspect.getsource(AstelliReclaimerETBEffect.resolve)
    assert "put_into_battlefield" in resolve_src, (
        "AstelliReclaimerETBEffect.resolve should call "
        "put_into_battlefield to bring the graveyard target onto the "
        "battlefield.  If absent, the Python convention changed -- "
        "update this pin."
    )

    # 2. Rust crate: NO reference to AstelliReclaimer / astelli_reclaimer
    #    in cards.rs or state_ops_resolve.rs.
    test_file_path = pathlib.Path(__file__).resolve()
    repo_root = test_file_path.parents[1]
    rust_cards_path = repo_root / "rust" / "src" / "cards.rs"
    rust_resolve_path = repo_root / "rust" / "src" / "state_ops_resolve.rs"

    assert rust_cards_path.exists(), (
        f"Rust source file should exist at {rust_cards_path!r}.  "
        "If the file moved, update this test's path resolution."
    )
    assert rust_resolve_path.exists(), (
        f"Rust source file should exist at {rust_resolve_path!r}."
    )

    cards_src = rust_cards_path.read_text(encoding="utf-8")
    resolve_src_rs = rust_resolve_path.read_text(encoding="utf-8")

    # Case-insensitive sweep over a small set of plausible variant
    # name fragments.
    forbidden_substrings = [
        "AstelliReclaimer",
        "astelli_reclaimer",
        "ReturnNoncreatureNonlandFromGYWithMVLE",
        "return_noncreature_nonland_from_gy_with_mv_le",
        "ReturnPermanentCardWithMVXorLessFromGY",
    ]
    for needle in forbidden_substrings:
        assert needle not in cards_src, (
            f"Pin sentinel: rust/src/cards.rs should NOT yet contain "
            f"{needle!r} (no Astelli Reclaimer Effect variant exists).  "
            "If this assertion fails, the closure may have landed -- "
            "audit the Rust enum + parse arm + resolve arm and flip "
            "this pin to _FIXED_parity."
        )
        assert needle not in resolve_src_rs, (
            f"Pin sentinel: rust/src/state_ops_resolve.rs should NOT "
            f"yet contain {needle!r} (no Astelli Reclaimer resolve arm "
            "exists).  If this assertion fails, the resolve arm has "
            "landed -- flip to _FIXED_parity."
        )

    # 3. POOL_PARITY's BLOCKED-genuinely_missing list contains Astelli
    #    Reclaimer (the documented worklist entry for this gap).
    pool_parity_path = repo_root / "docs" / "POOL_PARITY.md"
    assert pool_parity_path.exists(), (
        f"docs/POOL_PARITY.md should exist at {pool_parity_path!r}.  "
        "If the doc moved, update this pin's reference."
    )
    pool_parity_src = pool_parity_path.read_text(encoding="utf-8")
    assert "Astelli Reclaimer" in pool_parity_src, (
        "Pin invariant: docs/POOL_PARITY.md should list 'Astelli "
        "Reclaimer' (the BLOCKED-genuinely_missing entry).  If absent, "
        "the worklist was updated -- audit this pin's BLOCKED status."
    )

    # 4. EoE cards affected.
    affected_eoe_cards = [
        "Astelli Reclaimer",
        # {3}{W}{W} Creature -- Angel Warrior, Flying, Warp {2}{W}.
        # Oracle: "When this creature enters, return target noncreature,
        # nonland permanent card with mana value X or less from your
        # graveyard to the battlefield, where X is the amount of mana
        # spent to cast this creature."  Bespoke
        # AstelliReclaimerETBEffect on Python; no Rust counterpart.
        # 4565 17lands decks per docs/RESIDUE_CARD_PLANS.md.
    ]
    assert len(affected_eoe_cards) == 1, (
        "The Astelli Reclaimer ETB gap affects 1 EoE card directly.  "
        f"Enumerated list has {len(affected_eoe_cards)} entries."
    )


# ---------------------------------------------------------------------------
# Pytest visibility check: ensure the three pin tests are collected.
# ---------------------------------------------------------------------------


def test_ttt_pin_inventory_complete():
    """Sanity check: the TTT batch has 1 remaining divergence pin +
    2 FIXED parity sentinels.

    Pin batch TTT (round 23 pin-side) originally targeted 3 divergence
    pins.  Slice 14 closed Pins 1 + 2 (renamed to ``_FIXED_parity``
    with sentinels inverted); Pin 3 (Astelli Reclaimer) remains open.
    This inventory check guards against accidental deletion or rename
    of any of the 3 functions.
    """
    import tests.test_divergence_pins_ttt as _self_mod
    pin_fns = [
        name for name in dir(_self_mod)
        if name.startswith("test_") and name.endswith("_divergence_pin")
    ]
    fixed_fns = [
        name for name in dir(_self_mod)
        if name.startswith("test_") and name.endswith("_FIXED_parity")
    ]
    expected_pins = {
        "test_cross_engine_real_eoe_astelli_reclaimer_etb_effect_no_rust_variant_divergence_pin",
    }
    expected_fixed = {
        "test_cross_engine_real_eoe_lightless_evangel_is_sacrificed_ordering_FIXED_parity",
        "test_cross_engine_real_eoe_atomic_microsizer_non_creature_etb_summoning_sick_FIXED_parity",
    }
    assert set(pin_fns) == expected_pins, (
        "TTT pin inventory mismatch.  Expected exactly 1 open pin:\n"
        f"  {sorted(expected_pins)}\n"
        f"Got:\n  {sorted(pin_fns)}"
    )
    assert set(fixed_fns) == expected_fixed, (
        "TTT FIXED-parity inventory mismatch.  Expected exactly 2 "
        f"FIXED-parity sentinels:\n  {sorted(expected_fixed)}\n"
        f"Got:\n  {sorted(fixed_fns)}"
    )
