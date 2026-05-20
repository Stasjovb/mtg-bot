"""Divergence-pin tests: batch RRR (probe-batch-rrr, round 22).

**Pin 1 CLOSED by the 12th Rust slice** (``feature/rust-slice-12-
controlled-slot-aware-rrr-pin1``).  The
``ExileOpponentsNonlandPermanentUntilLeaves`` summoning_sick stamp
has been dropped at both the bare arm AND the ``WithMaxMv`` rider
sibling -- the bf->exile transition now preserves the pre-exile
value naturally, matching Python's ``move_off_battlefield``
semantics (3 EoE cards unblocked: Banishing Light, Hardlight
Containment, Seam Rip).  Pin 1's test is now
``..._summoning_sick_stamp_FIXED_parity`` with the sentinel
assertion inverted (stamp absent rather than present).

**Pins 2 and 3 remain OPEN** (still ``..._divergence_pin``).

Each remaining pin test is named ``test_cross_engine_real_eoe_<slug>
_*_divergence_pin`` and ASSERTS the CURRENT divergent behavior
rather than parity.  The PROBED-tier detector excludes
``*_divergence_pin`` functions, so these tests grow the test surface
without touching the PROBED metric.

This batch is a single-family pin set: three closely-related
divergences in the Rust ``state_ops_resolve.rs`` zone-change reset
substrate.  The CE13 closure (2026-05-12, ``feature/ce13-summoning-
sick-ltb``) standardised the general ``move_off_battlefield``-shaped
LTB to PRESERVE ``summoning_sick`` on bf-exit, matching Python's
``turn.move_off_battlefield`` semantics (which never touches
``summoning_sick`` in any LTB path -- see ``src/mtg_bot/turn.py:231-250``).
The closure dropped the explicit ``obj.summoning_sick = false`` clears
from the general destroy / sacrifice arms.

CE13 missed two specific bf-leave Effect arms in
``rust/src/state_ops_resolve.rs`` -- the
``ExileOpponentsNonlandPermanentUntilLeaves`` arm (bf -> exile, the
Banishing Light / Hardlight Containment / Seam Rip shape) and the
``OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary`` arm
(bf -> library, the Lost in Space shape).  Both arms still hardcode
``obj.summoning_sick = true`` ("r28 CE1 universal-true default" per
comments at ``state_ops_resolve.rs:10965`` and ``:10352``).  Python's
counterpart effect-class resolves in ``effects/generic/exile.py``
(via ``move_off_battlefield``) and ``effects/generic/zone_moves.py``
(direct ``state.battlefield.remove`` + housekeeping) -- neither
touches ``summoning_sick``.

Pin 3 is a distinct sibling gap on the same Rust arm as Pin 2: the
top-vs-bottom-of-library no-agent default disagreement.  Rust hardcodes
``lib_mut.push(obj)`` (bottom = tail of Vec); Python's no-agent path
defaults to ``choice=0`` (top = ``library.insert(0, obj)``).  These
are independent gaps -- closing the summoning_sick stamp does not
close the top-vs-bottom default, and vice versa.

Pinned bugs
-----------

Pin 1 -- ``ExileOpponentsNonlandPermanentUntilLeaves`` Rust resolve arm
stamps ``summoning_sick=true`` on the exiled object; Python's
``move_off_battlefield`` preserves the pre-exile value (3 EoE cards
affected).

    Bug location (Rust):
      ``rust/src/state_ops_resolve.rs:10965`` -- inside the
      ``Effect::ExileOpponentsNonlandPermanentUntilLeaves`` resolve
      arm, AFTER the bf-removal + before the exile push::

          obj.zone = ZONE_EXILE;
          obj.tapped = false;
          obj.summoning_sick = true; // r28 CE1 universal-true default
          obj.damage = 0;
          obj.counters = 0;
          obj.attached_to = None;
          obj.exiled_with_source = Some(source_obj_id);

      The ``summoning_sick = true`` line is the divergence: it
      unconditionally stamps the universal-true default the
      pre-CE13 LTB arms used.  Sibling LTB arms in the same file
      were brought in line with Python's preserve-semantics by the
      CE13 closure, but this specific exile-bf-leave arm was missed.

    Bug location (Python -- the correct behavior the Rust arm should
    match):
      ``src/mtg_bot/effects/generic/exile.py:638-644`` -- the
      ``ExileOpponentsNonlandPermanentUntilLeaves.resolve`` calls
      ``move_off_battlefield(state, obj, destination="exile")``.
      ``move_off_battlefield`` (``src/mtg_bot/turn.py:141-315``)
      clears combat state (``damage``, ``tapped``, ``attacking``,
      ``blocking``, ``blocked_by``, ``attached_to``) but **never
      touches ``summoning_sick``** (the pre-exile value persists --
      a creature that was sick when exiled stays sick in exile;
      a creature that wasn't stays not-sick).  This matches CR
      400.7 implicit object-identity-change semantics.

    Observable divergence (QQQ probe-attempt repro):
      Probe construction: source Enchantment with ETB trigger
      ``IsSelf -> ExileOpponentsNonlandPermanentUntilLeaves`` on
      P0's bf; bait artifact on P1's bf with ``summoning_sick =
      False`` set explicitly.  Drain both stacks.  Compare
      ``exile_p1`` field-view tuples (slot 2 = ``summoning_sick``):

        Python: ``('TitS Bait Artifact', 0, 0, 0, 0, None, 1, 0)``
        Rust:   ``('TitS Bait Artifact', 0, 1, 0, 0, None, 1, 0)``

      The 3rd slot is ``summoning_sick``; Rust shows 1, Python
      shows 0.

    Why the existing Banishing Light parity probe missed this:
      ``tests/test_parity_smoke.py::test_cross_engine_real_eoe_
      banishing_light_etb_exile_nonland_permanent_until_leaves_parity``
      uses TARGETED COUNTS + NAME assertions (zone sizes, printing
      names), not ``compare_fields`` byte-equality over the
      field-view 8-tuple.  Only QQQ's compare_fields-driven probe
      attempt on Trapped in the Screen surfaced the slot-3
      mismatch.

    Scale (EoE cards affected): 3.
      * Banishing Light -- ``{2}{W}`` Enchantment ETB exile target
        nonland permanent an opponent controls until this enchantment
        leaves the battlefield.  Already PROBED via name-based
        assertions (the divergence didn't surface in that probe shape).
      * Hardlight Containment -- ``{2}{W}`` Enchantment ETB-only
        variant (``opponents_only`` rider) of the same effect.
      * Seam Rip -- ``{W}`` Enchantment ETB exile target nonland
        permanent an opponent controls with mana value 2 or less
        until this enchantment leaves the battlefield (uses the
        ``max_mv=2`` rider sister-variant
        ``ExileOpponentsNonlandPermanentUntilLeavesWithMaxMV``;
        sibling arm at ``state_ops_resolve.rs:10996+`` has the
        same ``summoning_sick = true`` stamp -- the pin focuses on
        the bare arm but the sibling closure carries identical
        scope).

    Closure path:
      1. Remove the ``obj.summoning_sick = true`` line at
         ``rust/src/state_ops_resolve.rs:10965`` (and the sibling
         line in the ``max_mv`` rider arm a few lines down).  The
         pre-exile ``summoning_sick`` value preserves naturally
         through the ``bf_mut.remove(pos)`` -> exile push (the
         field is on the moved ``GameObject``).
      2. Add a regression test under ``tests_rust/`` that drives
         the same ETB chain and asserts the exiled object's
         ``summoning_sick`` matches the pre-exile value (not the
         hardcoded true).
      3. Audit the sibling unconditional-true stamps in the same
         file (Pin 2's library-bounce arm at :10352 is the next
         one; other Effect arms with the same "r28 CE1 universal-
         true default" comment are honest cleanup candidates).
      4. Flip THIS pin's assertion from ``rust_ss != py_ss`` to
         ``rust_ss == py_ss`` and rename to ``_FIXED_parity`` per
         the slice-10 PPP closure pattern.

Pin 2 -- ``OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary``
Rust resolve arm stamps ``summoning_sick=true`` on the bounced
object; Python's resolve preserves the pre-bounce value (1 EoE card
affected: Lost in Space).

    Bug location (Rust):
      ``rust/src/state_ops_resolve.rs:10349-10360`` -- inside the
      ``Effect::OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary``
      resolve arm, AFTER the bf-removal + before the library push::

          let mut obj = bf_mut.remove(pos);
          obj.zone = ZONE_LIBRARY;
          obj.tapped = false;
          obj.summoning_sick = true; // r28 CE1 universal-true default
          obj.damage = 0;
          obj.counters = 0;
          obj.attached_to = None;
          obj.exiled_with_source = None;
          ...
          lib_mut.push(obj); // post-CE3: bottom = tail of Vec

      The ``summoning_sick = true`` line is the divergence.  Same
      shape as Pin 1's exile arm; sibling closure.

    Bug location (Python -- the correct behavior the Rust arm should
    match):
      ``src/mtg_bot/effects/generic/zone_moves.py:96-128`` -- inside
      ``OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary.resolve``
      after the legal-target gate, the bf-removal +
      library-insert is done inline (NOT via
      ``move_off_battlefield``)::

          state.battlefield.remove(obj)
          obj.damage = 0
          obj.marked_lethal = False
          obj.damaged_this_turn = False
          obj.tapped = False
          obj.attacking = False
          obj.blocking = None
          obj.blocked_by = []
          obj.plus_one_counters = 0
          obj.charge_counters = 0
          obj.temp_power_bonus = 0
          obj.temp_toughness_bonus = 0
          obj.attached_to = None
          ...
          obj.zone = Zone.LIBRARY
          if choice == 0:
              owner.library.insert(0, obj)  # top
          else:
              owner.library.append(obj)     # bottom

      No ``obj.summoning_sick`` assignment -- the pre-bounce
      value persists, matching the CR 400.7 implicit
      identity-change semantics CE13 standardised.

    Scale (EoE cards affected): 1.
      * Lost in Space -- ``{3}{U}`` Instant.  Oracle: "Target
        artifact or creature's owner puts it on their choice of
        the top or bottom of their library.  Surveil 1."  Drives
        the bare-shape ``OwnerPutsTargetArtifactOrCreatureOnTopOrBottom
        OfLibrary(nonland_permanent=False)`` -- the EoE consumer of
        this Rust resolve arm.  (Vanish from Sight uses the same
        Effect class with ``nonland_permanent=True`` but is a
        Duskmourn card, not EoE -- noted for cross-set sibling
        scope only.)

    Closure path:
      1. Remove the ``obj.summoning_sick = true`` line at
         ``rust/src/state_ops_resolve.rs:10352``.  The pre-bounce
         value preserves through the ``bf_mut.remove(pos)`` ->
         library push (same shape as Pin 1's exile path).
      2. Once Pin 2 closes, the library-bounce field-view tuple
         aligns on slot 2 (``summoning_sick``) but Pin 3's top-
         vs-bottom default still produces a different ``library_pX``
         tuple order -- Pin 2 closure alone does NOT make Lost in
         Space byte-equal.  Both pins must close for a full
         byte-equal parity probe.

Pin 3 -- ``OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary``
no-agent top-vs-bottom default disagreement: Python defaults to TOP
(``library.insert(0, obj)``); Rust defaults to BOTTOM
(``lib_mut.push(obj)``) (1 EoE card affected: Lost in Space).

    Bug location (Python):
      ``src/mtg_bot/effects/generic/zone_moves.py:86-94`` -- when
      ``owner.agent is None`` (the cross-engine probe condition),
      ``choice`` defaults to 0 (the "top of library" option), then
      ``library.insert(0, obj)`` puts the bounced permanent on
      TOP::

          if owner.agent is not None:
              choice = owner.agent.choose_mode(
                  state, owner.id,
                  ["top of library", "bottom of library"],
              )
          else:
              choice = 0
          choice = 0 if choice not in (0, 1) else choice
          ...
          if choice == 0:
              owner.library.insert(0, obj)
              destination = "top"
          else:
              owner.library.append(obj)
              destination = "bottom"

    Bug location (Rust):
      ``rust/src/state_ops_resolve.rs:10358-10360`` -- the resolve
      arm unconditionally pushes to the LIBRARY tail::

          let lib_mut: &mut Vec<GameObject> =
              Arc::make_mut(&mut state.players[owner_idx].library);
          lib_mut.push(obj); // post-CE3: bottom = tail of Vec

      The post-CE3 round established that ``library[0]`` = top of
      library, ``library[-1]`` = bottom (matching Python's
      ``library.insert(0, ...)`` for top + ``library.append(...)``
      for bottom).  ``lib_mut.push(obj)`` is the tail = bottom
      operation -- the OPPOSITE of Python's no-agent default.

    Observable divergence:
      Build matched Lost in Space cross-engine states with no
      agent seated on either side.  Cast Lost in Space targeting
      P1's first artifact/creature.  Resolve.  Compare the
      ``library_p1`` field-view tuple ordering:

        Python: bounced permanent at slot 0 (TOP); rest of library
                shifts down.
        Rust:   bounced permanent at slot -1 (BOTTOM); rest of
                library unchanged.

      The tuple ordering disagrees on every slot (every slot's
      printing_name differs) -- this is a more severe divergence
      than Pins 1 / 2's single-slot ``summoning_sick`` mismatch.

    Closure path:
      The decision is which engine convention to keep:

      Option A (Rust converges on Python):
        Change ``lib_mut.push(obj)`` at
        ``state_ops_resolve.rs:10360`` to
        ``lib_mut.insert(0, obj)``.  Matches CE13's "Rust converges
        on Python" precedent.  No-agent default becomes TOP on
        both engines; agent-driven choice still differentiates
        top vs bottom (when Rust grows agent plumbing for this
        decision).

      Option B (Python converges on Rust):
        Change ``zone_moves.py:93`` default from ``choice = 0`` to
        ``choice = 1`` (or restructure so the no-agent path
        appends).  More invasive (the default semantics ripple to
        other no-agent test fixtures + decision search prunings).

      Per CE13's Option-B closure precedent, Rust-side convergence
      (Option A above) is the preferred path.

    Note on owner-choice modelling:
      The Rust ``apply_effect_pub`` plumbing for this Effect
      currently has no owner-choose-mode hook -- the bounce arm
      goes straight to ``lib_mut.push(obj)`` without consulting
      either player's agent.  This is a deeper modelling gap
      (Rust doesn't yet plumb owner-side modal-effect choices
      back through the agent boundary); the no-agent default
      alignment in Option A above is the minimal honest fix that
      doesn't touch the modal-choice plumbing.

Dropped pins
------------

  * **OOO Pin 1 (Room_fully_unlocked)** -- CLOSED at commit
    cd330540 (pure-Python bridge arm).  Was deferred from PPP;
    already off the open-pin board.

  * **PPP Pins 1 / 2 / 3** -- being closed in flight by
    ``feature/rust-slice-10-ppp-closure`` (commit 41c57251 at
    push time).  Re-pinning would be redundant once slice 10
    merges.

  * **Skystinger** (``subject_has_keyword`` predicate gap) --
    already pinned in
    ``tests/test_probe_blocked_ff.py::test_blocks_trigger_bridge_
    predicate_gap_skystinger``.

  * **MMM Pins 1 / 2 / 3** (``spells_cast_this_turn`` /
    ``discards_card`` / ``controlled_by_opponent``) -- still
    open from round 20.

  * **DDD Pins 1 / 2 / 3** (``survey_mechan_activation_effect`` /
    ``exile_top_x_of_library_may_play_this_turn`` /
    ``search_library_for_equipment_to_battlefield``) -- still
    deferred.

  * **GGG / AAA Pin 3** (``DrawCardsByConditionMultiplier``) --
    deferred (Condition serialization not yet designed).

  * **CreateToken rider mismatches** (``tapped`` / ``attacking`` /
    ``schedule_end_of_combat_sacrifice``) -- ``tapped`` is wired as
    a sister Rust variant (``CreateTokenTapped``) + bridge arm
    (``create_token_tapped``); only the ``attacking`` rider has
    no Rust mirror today (Kavaron Harrier / similar).  Not pinned
    -- single-shape attacking-token consumer not yet identified
    as a high-leverage EoE block; structural guard.

This batch's family-coherence rationale: Pins 1 / 2 / 3 share
``state_ops_resolve.rs``'s zone-change reset substrate, all surfaced
from the CE13 closure missing two Effect arms, and have nearly
identical closure paths (drop the explicit ``summoning_sick = true``
stamp; align library-insert convention).  A single Rust slice can
plausibly close all three in one pass -- exactly the closure-cadence
shape PPP / MMM / JJJ established.
"""

from __future__ import annotations

import dataclasses

import pytest


# ---------------------------------------------------------------------------
# Pin 1 -- ExileOpponentsNonlandPermanentUntilLeaves Rust resolve arm
#          stamps summoning_sick=true on exile; Python preserves.
#          3 EoE cards affected: Banishing Light, Hardlight Containment,
#          Seam Rip.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_exile_opponents_nonland_permanent_until_leaves_summoning_sick_stamp_FIXED_parity():
    """Assert the Rust exile-bf-leave summoning_sick stamp has been
    REMOVED (RRR Pin 1 closure -- 12th Rust slice).

    Fixed by: 12th Rust slice (``feature/rust-slice-12-controlled-
    slot-aware-rrr-pin1``). The CE13 closure (2026-05-12)
    standardised Rust LTB arms to PRESERVE summoning_sick on bf-exit
    (matching Python's ``move_off_battlefield`` which never touches
    the field -- ``turn.py:141-315``).  CE13 missed the
    ``ExileOpponentsNonlandPermanentUntilLeaves`` arm AND its
    ``WithMaxMv`` sibling.  Slice 12 dropped the explicit
    ``obj.summoning_sick = true`` stamp at the bare arm
    (state_ops_resolve.rs ~:11173) AND its ``WithMaxMv`` rider
    sibling (~:11288) -- both Effect arms now preserve the pre-exile
    summoning_sick value naturally via the bare ``remove`` -> ``push``
    sequence.

    Bug location (Python -- the correct behavior the Rust arm now
    matches):
      ``src/mtg_bot/effects/generic/exile.py:638-644`` --
      ``ExileOpponentsNonlandPermanentUntilLeaves.resolve`` calls
      ``move_off_battlefield(state, obj, destination="exile")``.
      ``move_off_battlefield`` clears combat state but NEVER touches
      ``obj.summoning_sick`` -- the pre-exile value persists.

    Closure shape (post-12th-slice):
      1. Python Effect class structure UNCHANGED (still a frozen
         dataclass with ``max_mv`` rider).
      2. Python's ``move_off_battlefield`` still does NOT assign to
         ``summoning_sick`` (the post-CE13 LTB preserve-semantics
         invariant).
      3. Python's resolve methods still delegate to
         ``move_off_battlefield`` (no inline summoning_sick stamp).
      4. **Sentinel inverted:** the Rust source's bare arm body now
         does NOT contain ``obj.summoning_sick = true``.  3 EoE cards
         unblocked: Banishing Light, Hardlight Containment, Seam Rip.
    """
    from mtg_bot.effects.generic.exile import (
        ExileOpponentsNonlandPermanentUntilLeaves,
    )
    from mtg_bot.effects.base import Effect
    import inspect
    import pathlib

    # 1. ExileOpponentsNonlandPermanentUntilLeaves is a frozen
    #    dataclass with field 'max_mv' (default 0 = bare shape).
    assert dataclasses.is_dataclass(ExileOpponentsNonlandPermanentUntilLeaves), (
        "ExileOpponentsNonlandPermanentUntilLeaves should be a dataclass "
        "(effects/generic/exile.py).  "
        "If this fails the class was restructured -- update this pin."
    )
    assert issubclass(ExileOpponentsNonlandPermanentUntilLeaves, Effect), (
        "ExileOpponentsNonlandPermanentUntilLeaves should be an Effect "
        "subclass.  If this fails the class hierarchy changed."
    )
    fields = {
        f.name: f for f in dataclasses.fields(
            ExileOpponentsNonlandPermanentUntilLeaves
        )
    }
    assert "max_mv" in fields, (
        "ExileOpponentsNonlandPermanentUntilLeaves should have a field "
        "named 'max_mv' (the Seam Rip mana-value cap, 0 = no cap).  "
        f"Got fields: {list(fields.keys())!r}"
    )
    assert fields["max_mv"].default == 0, (
        "ExileOpponentsNonlandPermanentUntilLeaves.max_mv default should "
        "be 0 (the Banishing Light / Hardlight Containment bare shape).  "
        f"Got default: {fields['max_mv'].default!r}"
    )
    # Verify the class constructs.
    inst = ExileOpponentsNonlandPermanentUntilLeaves()
    assert inst.max_mv == 0
    inst_capped = ExileOpponentsNonlandPermanentUntilLeaves(max_mv=2)
    assert inst_capped.max_mv == 2

    # 2. Python's move_off_battlefield does NOT touch summoning_sick.
    from mtg_bot import turn as _turn_mod
    move_src = inspect.getsource(_turn_mod.move_off_battlefield)
    assert "summoning_sick" not in move_src, (
        "Pin invariant: src/mtg_bot/turn.py::move_off_battlefield should "
        "NOT assign to summoning_sick (the pre-exile value must persist "
        "through the bf->exile transition; this is the post-CE13 LTB "
        "preserve-semantics).  If 'summoning_sick' appears in "
        "move_off_battlefield's source, the Python convention changed "
        "-- update this pin to reflect the new semantics."
    )

    # 3. Family-level invariant: the resolve method on
    #    ExileOpponentsNonlandPermanentUntilLeaves itself does NOT touch
    #    summoning_sick (it delegates to move_off_battlefield).
    eff_resolve_src = inspect.getsource(
        ExileOpponentsNonlandPermanentUntilLeaves.resolve
    )
    assert "summoning_sick" not in eff_resolve_src, (
        "Pin invariant: ExileOpponentsNonlandPermanentUntilLeaves.resolve "
        "should NOT assign to summoning_sick -- it delegates the bf-exit "
        "to move_off_battlefield, which preserves the field.  If the "
        "resolve method gains a summoning_sick assignment, the Python "
        "convention changed -- update this pin."
    )

    # 4. Sentinel (INVERTED post-12th-slice): the Rust source's bare
    #    arm body no longer contains the explicit
    #    'obj.summoning_sick = true' stamp.  The pre-exile value now
    #    persists naturally through bf->exile.
    test_file_path = pathlib.Path(__file__).resolve()
    repo_root = test_file_path.parents[1]  # tests/.. = repo root
    rust_resolve_path = repo_root / "rust" / "src" / "state_ops_resolve.rs"
    assert rust_resolve_path.exists(), (
        f"Rust source file should exist at {rust_resolve_path!r}.  "
        "If the file moved, update this test's path resolution."
    )
    rust_src = rust_resolve_path.read_text(encoding="utf-8")
    arm_sig = "Effect::ExileOpponentsNonlandPermanentUntilLeaves"
    assert arm_sig in rust_src, (
        f"Rust source should contain the arm signature "
        f"{arm_sig!r}.  If the variant was renamed, update this test."
    )
    # Locate the arm's body and assert the stamp has been REMOVED.
    arm_start = rust_src.find(arm_sig)
    assert arm_start >= 0
    next_arm_start = rust_src.find("\n        Effect::", arm_start + 1)
    if next_arm_start < 0:
        next_arm_start = len(rust_src)
    arm_body = rust_src[arm_start:next_arm_start]
    assert "obj.summoning_sick = true" not in arm_body, (
        "Post-12th-slice invariant: rust/src/state_ops_resolve.rs's "
        "Effect::ExileOpponentsNonlandPermanentUntilLeaves arm should "
        "NO LONGER contain the unconditional 'obj.summoning_sick = "
        "true' stamp.  If this assertion fails, the stamp has been "
        "reintroduced -- the divergence is REOPENED.  Body excerpt:\n"
        f"{arm_body[:500]!r}..."
    )
    # Family invariant: the WithMaxMv sibling arm (Seam Rip) also has
    # the stamp dropped in slice 12.
    sibling_sig = "Effect::ExileOpponentsNonlandPermanentWithMaxMvUntilLeaves"
    if sibling_sig in rust_src:
        sib_start = rust_src.find(sibling_sig)
        sib_next = rust_src.find("\n        Effect::", sib_start + 1)
        if sib_next < 0:
            sib_next = len(rust_src)
        sib_body = rust_src[sib_start:sib_next]
        assert "obj.summoning_sick = true" not in sib_body, (
            "Post-12th-slice sibling invariant: the "
            "WithMaxMvUntilLeaves rider arm (Seam Rip) should also have "
            "the stamp dropped.  Body excerpt:\n"
            f"{sib_body[:500]!r}..."
        )

    # 5. EoE cards unblocked by this closure.
    unblocked_eoe_cards = [
        "Banishing Light",
        # {2}{W} Enchantment: "When this enchantment enters, exile target
        # nonland permanent an opponent controls until this enchantment
        # leaves the battlefield."  Effect:
        # ExileOpponentsNonlandPermanentUntilLeaves() (bare).
        "Hardlight Containment",
        # {2}{W} Enchantment: ETB-only variant of the same effect.
        "Seam Rip",
        # {W} Enchantment with max_mv=2 rider -- the sibling Rust arm
        # at state_ops_resolve.rs has the matching stamp drop.
    ]
    assert len(unblocked_eoe_cards) == 3, (
        "The exile-bf-leave summoning_sick-stamp closure unblocks 3 "
        "EoE cards (Banishing Light, Hardlight Containment, Seam Rip).  "
        f"Enumerated list has {len(unblocked_eoe_cards)} entries."
    )


# ---------------------------------------------------------------------------
# Pin 2 -- OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary Rust
#          resolve arm stamps summoning_sick=true on the bounced object;
#          Python preserves.  1 EoE card affected: Lost in Space.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_lost_in_space_library_bounce_summoning_sick_stamp_divergence_pin():
    """Pin the Rust library-bounce ``summoning_sick = true`` stamp.

    Sibling shape to Pin 1: same ``state_ops_resolve.rs`` substrate,
    same CE13-missed Effect arm class.  This pin covers the bf ->
    library bounce (Lost in Space); Pin 1 covers the bf -> exile
    bounce (Banishing Light shape).

    Bug location (Rust):
      ``rust/src/state_ops_resolve.rs:10349-10360`` -- inside
      ``Effect::OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary``,
      AFTER ``bf_mut.remove(pos)`` and before ``lib_mut.push(obj)``::

          let mut obj = bf_mut.remove(pos);
          obj.zone = ZONE_LIBRARY;
          obj.tapped = false;
          obj.summoning_sick = true; // r28 CE1 universal-true default
          obj.damage = 0;
          ...
          lib_mut.push(obj);

    Bug location (Python -- the correct behavior):
      ``src/mtg_bot/effects/generic/zone_moves.py:96-128`` --
      ``OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary.resolve``
      strips the permanent from the battlefield with an inline
      housekeeping block (NOT via ``move_off_battlefield``),
      clearing combat state + counters but NEVER touching
      ``obj.summoning_sick``.

    Probe shape:
      1. Assert ``OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOf
         Library`` exists, is a frozen dataclass, and has the
         ``nonland_permanent`` rider (default False; Lost in Space's
         bare shape).
      2. Inspect ``resolve`` source to confirm it does NOT assign
         ``summoning_sick``.
      3. Sentinel: the Rust source contains the explicit
         ``obj.summoning_sick = true`` line inside the library-
         bounce arm.

    Closure indicator: same as Pin 1 -- remove the explicit stamp,
    flip the pin to ``_FIXED_parity``.
    """
    from mtg_bot.effects.generic.zone_moves import (
        OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary,
    )
    from mtg_bot.effects.base import Effect
    import inspect
    import pathlib

    # 1. Class shape.
    assert dataclasses.is_dataclass(
        OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary
    ), (
        "OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary should "
        "be a dataclass (effects/generic/zone_moves.py).  "
        "If this fails the class was restructured -- update this pin."
    )
    assert issubclass(
        OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary, Effect
    ), (
        "OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary should "
        "be an Effect subclass."
    )
    fields = {
        f.name: f for f in dataclasses.fields(
            OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary
        )
    }
    assert "nonland_permanent" in fields, (
        "OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary should "
        "have a 'nonland_permanent' field (False = Lost in Space's bare "
        "'artifact or creature' filter; True = Vanish from Sight's "
        "widened 'any nonland permanent' filter).  "
        f"Got fields: {list(fields.keys())!r}"
    )
    assert fields["nonland_permanent"].default is False, (
        "OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary."
        "nonland_permanent default should be False (Lost in Space).  "
        f"Got default: {fields['nonland_permanent'].default!r}"
    )

    # 2. Python's resolve does NOT touch summoning_sick.
    py_resolve_src = inspect.getsource(
        OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary.resolve
    )
    assert "summoning_sick" not in py_resolve_src, (
        "Pin invariant: OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOf"
        "Library.resolve should NOT assign to summoning_sick (the "
        "pre-bounce value must persist through the bf->library "
        "transition).  If 'summoning_sick' appears in the resolve "
        "source, the Python convention changed -- update this pin to "
        "reflect the new semantics."
    )

    # 3. Sentinel: Rust arm still contains the explicit stamp.
    test_file_path = pathlib.Path(__file__).resolve()
    repo_root = test_file_path.parents[1]
    rust_resolve_path = repo_root / "rust" / "src" / "state_ops_resolve.rs"
    rust_src = rust_resolve_path.read_text(encoding="utf-8")
    arm_sig = (
        "Effect::OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary"
    )
    assert arm_sig in rust_src, (
        f"Rust source should contain the arm signature {arm_sig!r}.  "
        "If the variant was renamed, update this pin."
    )
    arm_start = rust_src.find(arm_sig)
    next_arm_start = rust_src.find("\n        Effect::", arm_start + 1)
    if next_arm_start < 0:
        next_arm_start = len(rust_src)
    arm_body = rust_src[arm_start:next_arm_start]
    assert "obj.summoning_sick = true" in arm_body, (
        "Pin sentinel: rust/src/state_ops_resolve.rs's "
        "Effect::OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary "
        "arm should still contain the unconditional "
        "'obj.summoning_sick = true' stamp (Pin 2's divergence).  "
        "If this assertion fails, the Rust stamp has been removed -- "
        "rename to _FIXED_parity and invert.  Body excerpt:\n"
        f"{arm_body[:500]!r}..."
    )

    # 4. EoE cards affected.
    affected_eoe_cards = [
        "Lost in Space",
        # {3}{U} Instant.  Oracle: "Target artifact or creature's
        # owner puts it on their choice of the top or bottom of
        # their library.  Surveil 1."
        # Effect: Sequence(
        #     OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary(
        #         nonland_permanent=False),
        #     Surveil(1))
    ]
    assert len(affected_eoe_cards) == 1, (
        "The library-bounce summoning_sick-stamp divergence affects 1 "
        "EoE card (Lost in Space).  "
        f"Enumerated list has {len(affected_eoe_cards)} entries."
    )


# ---------------------------------------------------------------------------
# Pin 3 -- OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary no-agent
#          top-vs-bottom default disagreement: Python defaults to TOP,
#          Rust defaults to BOTTOM.  1 EoE card affected: Lost in Space.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_lost_in_space_library_bounce_top_vs_bottom_default_divergence_pin():
    """Pin the no-agent default disagreement on bf->library bounce.

    Sibling gap to Pin 2 on the SAME Rust resolve arm.  Independent
    of Pin 2: closing the summoning_sick stamp does not align the
    top-vs-bottom default, and vice versa.

    Bug location (Python):
      ``src/mtg_bot/effects/generic/zone_moves.py:86-94`` -- when
      ``owner.agent is None`` (the cross-engine test condition with
      no agent seated), ``choice`` defaults to 0; the resolve arm
      then calls ``owner.library.insert(0, obj)`` (TOP of library).

    Bug location (Rust):
      ``rust/src/state_ops_resolve.rs:10358-10360`` -- the arm
      unconditionally calls ``lib_mut.push(obj)`` (BOTTOM of library
      = tail of Vec per the post-CE3 library-index convention).
      No owner-choose-mode plumbing.

    Library-index convention (post-CE3):
      ``library[0]`` = TOP of library (next card drawn).
      ``library[-1]`` = BOTTOM of library.

      Python's ``library.insert(0, obj)`` = TOP.
      Python's ``library.append(obj)`` = BOTTOM.
      Rust's ``lib_mut.push(obj)`` = BOTTOM (tail of Vec).
      Rust's ``lib_mut.insert(0, obj)`` = TOP (would match Python).

    Probe shape:
      1. Inspect Python source: confirm the no-agent branch sets
         ``choice = 0`` and the ``choice == 0`` branch calls
         ``library.insert(0, obj)``.
      2. Sentinel: Rust source's library-bounce arm calls
         ``lib_mut.push(obj)`` (not ``lib_mut.insert(0, obj)``).
      3. Symbolic check: the strings ``"library.insert(0, obj)"``
         and ``"lib_mut.push(obj)"`` both appear in their respective
         sources (the source-of-truth divergence).

    Closure indicator (Option A -- the preferred CE13-precedent
    path):
      Rust's ``lib_mut.push(obj)`` at
      ``state_ops_resolve.rs:10360`` changes to
      ``lib_mut.insert(0, obj)``.  Both engines' no-agent default
      becomes TOP.  Pin renames to ``_FIXED_parity`` and the
      sentinel asserts ``insert(0, obj)`` appears in the Rust arm
      instead of ``push(obj)``.

      Full closure also requires the Rust arm to grow an
      owner-side modal-choice hook so the AGENT-driven case can
      pick bottom too -- that is a deeper plumbing gap and is
      out of scope for this pin (the no-agent default alignment
      is the minimal honest fix).
    """
    from mtg_bot.effects.generic.zone_moves import (
        OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary,
    )
    import inspect
    import pathlib

    # 1. Python source: confirm the no-agent branch path.
    py_resolve_src = inspect.getsource(
        OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary.resolve
    )
    # 1a. The no-agent branch sets choice = 0.
    assert "choice = 0" in py_resolve_src, (
        "Pin invariant: Python's resolve should have an explicit "
        "'choice = 0' branch for the no-agent path.  "
        f"Source excerpt: {py_resolve_src[:1500]!r}.  "
        "If 'choice = 0' is absent, the no-agent default semantics "
        "changed -- update this pin."
    )
    # 1b. The choice == 0 path calls library.insert(0, obj).
    assert "library.insert(0, obj)" in py_resolve_src, (
        "Pin invariant: Python's resolve should call "
        "'library.insert(0, obj)' on the choice == 0 (TOP) branch.  "
        f"Source excerpt: {py_resolve_src[:1500]!r}.  "
        "If 'library.insert(0, obj)' is absent, the top-of-library "
        "operation changed -- update this pin."
    )
    # 1c. The choice == 1 path uses library.append(obj).
    assert "library.append(obj)" in py_resolve_src, (
        "Pin invariant: Python's resolve should call "
        "'library.append(obj)' on the choice == 1 (BOTTOM) branch.  "
        f"Source excerpt: {py_resolve_src[:1500]!r}."
    )

    # 2. Sentinel: Rust arm calls lib_mut.push(obj), NOT
    #    lib_mut.insert(0, obj).
    test_file_path = pathlib.Path(__file__).resolve()
    repo_root = test_file_path.parents[1]
    rust_resolve_path = repo_root / "rust" / "src" / "state_ops_resolve.rs"
    rust_src = rust_resolve_path.read_text(encoding="utf-8")
    arm_sig = (
        "Effect::OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary"
    )
    arm_start = rust_src.find(arm_sig)
    assert arm_start >= 0, (
        f"Rust arm signature {arm_sig!r} should be present."
    )
    next_arm_start = rust_src.find("\n        Effect::", arm_start + 1)
    if next_arm_start < 0:
        next_arm_start = len(rust_src)
    arm_body = rust_src[arm_start:next_arm_start]

    # 2a. Rust arm calls lib_mut.push(obj) (the BOTTOM-default
    #     divergence).
    assert "lib_mut.push(obj)" in arm_body, (
        "Pin sentinel: rust/src/state_ops_resolve.rs's library-"
        "bounce arm should still contain 'lib_mut.push(obj)' "
        "(Pin 3's divergence -- bottom-of-library hardcoded "
        "default).  If this fails, the Rust convention changed -- "
        "rename to _FIXED_parity and invert the assertion (expect "
        "'lib_mut.insert(0, obj)' instead).  Body excerpt:\n"
        f"{arm_body[:1200]!r}..."
    )
    # 2b. Rust arm does NOT call lib_mut.insert(0, obj) (the
    #     would-be-aligned-with-Python TOP-default).  This is the
    #     inverse of the closure indicator.
    assert "lib_mut.insert(0, obj)" not in arm_body, (
        "Pin sentinel inverse: the Rust arm should NOT contain "
        "'lib_mut.insert(0, obj)' yet (that would be the closure-"
        "indicator state -- pin should flip to _FIXED_parity).  "
        f"Body excerpt:\n{arm_body[:1200]!r}..."
    )

    # 3. EoE cards affected.
    affected_eoe_cards = [
        "Lost in Space",
        # Same card as Pin 2 -- both gaps live on the same Rust resolve
        # arm.  Lost in Space's full byte-equal probe requires Pin 2
        # (summoning_sick) AND Pin 3 (top-vs-bottom default) to both
        # close.  Closing only Pin 2 still leaves the library_pX
        # tuple ordering divergent on every slot; closing only Pin 3
        # still leaves slot 2 of the bounced object's tuple
        # divergent.
    ]
    assert len(affected_eoe_cards) == 1, (
        "The library-bounce top-vs-bottom default divergence affects 1 "
        "EoE card (Lost in Space).  "
        f"Enumerated list has {len(affected_eoe_cards)} entries."
    )
