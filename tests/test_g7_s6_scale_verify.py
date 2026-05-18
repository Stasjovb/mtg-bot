"""G7 Slice S6 — the ``rust_shadow`` bake-in SCALE-VERIFY pins
(NO new masking; the penultimate G7 slice before S7 CE5-removal).

These pins are the committed, discriminating record of the S6
scale-verify finding (the full evidence is in
``docs/G7_S6_SCALE_VERIFY_EVIDENCE.md`` + the committed
``s6_scale_verify.json``). They live in a **NEW module** (NOT
``tests/test_rust_shadow_bakein.py`` — Lane B owns that file's
combat-blocker closure-flip pin; this module has zero pin contention
with it) and assert two load-bearing S6 conclusions:

1. **The S5a/S5b/S5-triggers-closed ``hand_p0`` atomic-cast axis +
   the cycle-30 combat-blocker ``LEGAL_SET_EQ`` STAY CLOSED at scale**
   — the dominant 238/300 STATE_EQ ``[('battlefield', ...),
   ('stack', ...)]`` + caster ``hand_pX`` shape that the ORIGINAL C4
   re-sweep (0/300 @ ``e87a6ebe``) tripped on, and the S5a-era
   ``('blocker', N, None)`` over-emission, do **NOT** reappear
   anywhere in the 300-game production population. Verified by
   characterizing the FULL frontier set (below) and confirming none
   is the closed shape, AND by the negative controls in
   ``test_rust_shadow_bakein.py`` (STATE_EQ / LEGAL_SET_EQ / NO_RAISE
   all still FIRE LOUDLY on injected divergence;
   ``_DOCUMENTED_ACCEPTED_FIELDS`` is empty — nothing masked).

2. **The complete S6 frontier inventory is an ENUMERATED FINITE set
   of distinct, pre-existing, already-tracked axes** — each maps to a
   known class (B1-axis / G5-family / warp-EMISSION-S4b /
   B1-keystone-C1). The bake-in is a faithful tripwire: it trips
   LOUDLY at each, no silent passes, no axis masked rather than
   fixed. This is the S7-readiness evidence: the gap between here and
   a clean CE5-free C4 is exactly this finite frontier set, NOT a
   structural/masking problem.

The pins drive the EXACT ``drive_shadow_game_to_terminal`` idiom
(uniform-random over ``adapter.legal_decisions()``, apply until
terminal) the scale sweep uses, so each pinned trip is byte-identical
to the committed ``s6_scale_verify.json``. Per the established
G4/G5/G6/S5a surfaced→characterized discipline: if a pinned frontier
stops firing at its characterized boundary, the axis was closed
elsewhere — RE-CHARACTERIZE this pin, do NOT silently bump or pass.
"""
from __future__ import annotations

import random

import pytest

from mtg_bot.search.rust_shadow import ShadowDivergenceError


def _drive_to_trip(arch: int, seed: int, max_steps: int = 4000):
    """Drive the role-swapped bake-in exactly as
    ``drive_shadow_game_to_terminal`` does; return
    ``(steps, raised, raw_exc)`` at the first trip (or terminal)."""
    from mtg_bot.parity import trajectory
    from mtg_bot.search.engine_adapter_factory import (
        build_shadow_checked_adapter,
    )

    names = trajectory.load_production_deck(archetype=arch)
    spec = trajectory.production_deck_to_deckspec(
        names, shared_rng_seed=seed
    )
    adapter = build_shadow_checked_adapter(spec)
    rng = random.Random(seed)
    steps = 0
    raised: ShadowDivergenceError | None = None
    raw_exc: BaseException | None = None
    while not adapter.is_terminal() and steps < max_steps:
        try:
            legal = adapter.legal_decisions()
        except ShadowDivergenceError as e:
            raised = e
            break
        if not legal:
            break
        choice = rng.choice(legal)
        try:
            adapter.apply(choice)
        except ShadowDivergenceError as e:
            raised = e
            break
        except Exception as e:  # noqa: BLE001 — captured, asserted
            raw_exc = e
            break
        steps += 1
    return steps, raised, raw_exc


# ---------------------------------------------------------------------------
# 1. The CLOSED axes STAY CLOSED at scale (the load-bearing S6 question).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "arch,seed,exp_step,kind,needle",
    [
        # Frontier (a) — CLOSURE-FLIPPED twice. The B1-axis analog
        # (Rust legal-emit-vs-apply self-inconsistency on
        # ActivateAbility mana-affordability) was @318 RAW
        # ValueError, CLOSED by feature/fix-g7-frontier-a-
        # activateability-affordability (a9126b06 → main). With (a)
        # closed the bake-in surfaced the b3f7c0a9 library-shuffle-
        # order STATE_EQ @320 (post-Lander-search per-engine shuffle
        # RNG not lockstep). b3f7c0a9 is now ALSO closed (matched
        # ``random.Random(shared_rng_seed)`` installation in
        # ``build_shadow_checked_adapter`` — both engines' in-game
        # Fisher-Yates byte-equal). The run proceeds PAST 320 to
        # @337: ``LEGAL_SET_EQ py\rust=["('pass',)"]`` — the SAME
        # pre-existing G1 stateless-Rust ``attack=False`` re-emission
        # axis the arch5/s0 row pins at @369 (and arch7/s0 at @757),
        # surfacing here on arch2/s1's attacker_id=9. Filed as the
        # next G7 follow-up (G1 provider-accumulation / B3-S3 port —
        # already a tracked sibling-owned lane). The load-bearing
        # identity is the ``py\rust=["('pass',)"]`` shape, not the
        # specific attacker_id.
        (2, 1, 337, "LEGAL_SET_EQ", "py\\rust=[\"('pass',)\"]"),
        # Frontier (b) = S6 Class B — CLOSURE-FLIPPED. The dominant
        # 138/300 ``STATE_EQ ('priority_player', 1, 0)`` @367 is
        # CLOSED by the coordinated G7 S6 Class-B option-β
        # engine+adapter slice (``state_ops_legal.rs`` option-β +
        # ``rust_engine_adapter.py`` deferred-priority-reset /
        # combat-decision-maker ``active_player()``+``legal_decisions()``
        # / factored-combat ``PassPriority`` strip). The run proceeds
        # PAST 367 to a NEW distinct frontier @369: ``LEGAL_SET_EQ``
        # ``py\rust=["('pass',)"]`` — the pre-existing **G1
        # stateless-Rust ``attack=False`` re-emission gap** (Rust's
        # ``apply_action(AttackerDecision, attack=false)`` is a
        # deliberate no-op and the ``RustGameStateAdapter`` does not
        # port Python's provider-side ``_pending_attackers.pop(0)`` +
        # ``_finalize_attacker_phase`` — the B3-S3 sibling slice the
        # G1 design defers), unmasked — NOT introduced — by closing
        # 367 (zero provider accumulation at ``dc22ebc4``; arch5/s0
        # never reached a factored ``attack=False`` before, blocked at
        # 344/367). Filed as the next G7 follow-up.
        (5, 0, 369, "LEGAL_SET_EQ", "py\\rust=[\"('pass',)\"]"),
    ],
)
def test_s6_known_frontiers_reproduce_byte_exactly(
    arch, seed, exp_step, kind, needle
):
    """The 2 KNOWN frontiers (the cycle-30 honest-stop pinned set)
    reproduce byte-exactly at scale on ``main`` @ ``a9126b06``. This
    is the continuity check: the closed ``hand_p0`` atomic-cast axis
    and the closed combat-blocker ``LEGAL_SET_EQ`` did NOT reappear
    (both runs proceed to the SAME freshly-characterized boundary the
    cycle-30 pin asserts — a trip at/before the old 312/344 boundary
    would mean a regression). The surfaced divergence is the
    characterized next-frontier, NOT the closed axis."""
    pytest.importorskip("mtg_bot_engine")
    steps, raised, raw_exc = _drive_to_trip(arch, seed)
    assert steps == exp_step, (
        f"arch{arch}/s{seed}: expected the characterized S6 frontier "
        f"boundary step {exp_step}, got {steps}. A different step "
        f"means the frontier MOVED (an axis closed/opened elsewhere) "
        f"— re-characterize this pin, do NOT silently bump."
    )
    surfaced = str(raised) if raised is not None else str(raw_exc)
    # The closed axes must NOT be what surfaced.
    assert "hand_p0" not in surfaced and "blocker" not in surfaced, (
        f"arch{arch}/s{seed}: the surfaced divergence mentions a "
        f"CLOSED axis (hand_p0 / blocker) — S5a or the combat-blocker "
        f"fix REGRESSED at scale: {surfaced[:300]!r}."
    )
    if kind == "raw":
        assert raw_exc is not None and raised is None, (
            f"arch{arch}/s{seed}: expected the characterized Rust-side "
            f"raw ValueError (NOT a ShadowDivergenceError). "
            f"raw={raw_exc!r} tripwire={raised!r}."
        )
        assert needle in str(raw_exc), (
            f"arch{arch}/s{seed}: expected {needle!r}, got "
            f"{str(raw_exc)[:300]!r}."
        )
    else:
        assert raised is not None and raw_exc is None, (
            f"arch{arch}/s{seed}: expected a {kind} "
            f"ShadowDivergenceError. raised={raised!r} raw={raw_exc!r}."
        )
        assert raised.tripwire == kind, (
            f"arch{arch}/s{seed}: expected tripwire {kind}, got "
            f"{raised.tripwire}: {str(raised)[:300]!r}."
        )
        assert needle in str(raised), (
            f"arch{arch}/s{seed}: expected {needle!r}, got "
            f"{str(raised)[:300]!r}."
        )


# ---------------------------------------------------------------------------
# 2. The COMPLETE frontier inventory — every distinct class pinned.
#    Each is a distinct, pre-existing, already-tracked axis; the
#    bake-in trips LOUDLY at each (no silent pass, nothing masked).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "arch,seed,exp_step,kind,needle,axis_class",
    [
        # Class A — CLOSURE-FLIPPED twice (B1-axis (a) closed; then
        # b3f7c0a9 library-shuffle-order closed). The original
        # @318-RAW ``ActivateAbility: source 121 cost is unaffordable``
        # is CLOSED by feature/fix-g7-frontier-a-activateability-
        # affordability (a9126b06 → main); the @320 b3f7c0a9
        # ``STATE_EQ ('library_p1', ...)`` library-shuffle-order
        # frontier that surfaced behind (a) is CLOSED by the
        # matched-rng installation in ``build_shadow_checked_adapter``.
        # The run proceeds PAST both to @337: ``LEGAL_SET_EQ
        # py\rust=["('pass',)"]`` — the SAME pre-existing G1
        # stateless-Rust ``attack=False`` re-emission axis as Class B
        # (arch5/s0 @369) and Class D (arch7/s0 @757), surfacing here
        # on arch2/s1's attacker_id=9. NOT a new G-axis — it is the
        # already-tracked G1 provider-accumulation / B3-S3 port
        # sibling-owned lane.
        (2, 1, 337, "LEGAL_SET_EQ", "py\\rust=[\"('pass',)\"]",
         "G1 stateless-Rust attack=False re-emission (cross-arch "
         "twin of Class B @369 / Class D @757; surfaced behind the "
         "stacked frontier-(a) + b3f7c0a9 closures on arch2/s1)"),
        # Class B — CLOSURE-FLIPPED. The dominant 138/300 G5-family
        # ``STATE_EQ ('priority_player', 1, 0)`` @367 is CLOSED by the
        # coordinated G7 S6 Class-B option-β engine+adapter slice
        # (carry ``priority_player`` through the factored-combat
        # window byte-faithful to the ``simulate.py`` SoT — relocate
        # the factored-combat emission above the ``state_ops_legal.rs``
        # line-1199 priority gate keyed on the structural
        # decision-maker; defer the adapter's eager
        # ``_reset_priority_to_active`` for factored-combat steps; make
        # ``active_player()``/``legal_decisions()`` resolve the combat
        # decision-maker; strip the structural ``PassPriority`` from
        # the factored-combat set). The run proceeds PAST 367 to a NEW
        # distinct frontier @369: ``LEGAL_SET_EQ``
        # ``py\rust=["('pass',)"]`` — the pre-existing **G1
        # stateless-Rust ``attack=False`` re-emission gap** (the
        # ``RustGameStateAdapter`` does not port Python's provider-side
        # ``_pending_attackers.pop(0)`` + ``_finalize_attacker_phase``
        # accumulation — the B3-S3 sibling slice the G1 design
        # defers), unmasked — NOT introduced — by closing 367 (zero
        # provider accumulation at ``dc22ebc4``; arch5/s0 never reached
        # a factored ``attack=False`` before, blocked at 344/367).
        # Filed as the next G7 follow-up (G1 provider-accumulation /
        # B3-S3 port).
        (5, 0, 369, "LEGAL_SET_EQ", "py\\rust=[\"('pass',)\"]",
         "G1 stateless-Rust attack=False re-emission (B3-S3 "
         "provider-accumulation port; Class-B priority axis CLOSED)"),
        # Class C — CLOSED via the delayed-trigger port
        # (feature/g7-classc-warp-delayed-trigger). The warp-EXILE
        # delayed-trigger-vs-deterministic-sweep axis previously
        # surfaced at arch1/s1 step 169 ("Starbreach Whale", three-
        # field {bf, exile_p1, stack} STATE_EQ). With the new Rust
        # state.delayed_triggers + Effect::WarpExileSelf +
        # run_delayed_end_step_triggers landed, arch1/s1 runs MANY
        # steps past 169.  RE-CHARACTERIZED at merge-time (cycle-37
        # serial-merge pipeline, post-Class-B+Class-C lanes both
        # landed): Class-B closure (priority-port axis at @367 now
        # CLOSED on this seed too) shifts the next-frontier from the
        # previously-pinned priority_player STATE_EQ @351 to a NEW
        # life-total STATE_EQ at step 356 ('life_p0', 17, 20).  This
        # is a genuine cross-lane interaction: neither Class-B nor
        # Class-C alone surfaces it (a 3-life delta from a divergent
        # damage/effect application that only the random walk's
        # post-Class-B+Class-C path reaches). NOT a regression — the
        # warp-EXILE closure-progress contract (run past step 169) +
        # the priority-port closure (no priority_player divergence)
        # both hold; this is the new axis surfaced behind the joint
        # closure.  The library_pX sub-variants remain a SEPARATE
        # shuffle-order axis (todo b3f7c0a9), not Class C.
        (1, 1, 356, "STATE_EQ", "('life_p0', 17, 20)",
         "life-total STATE_EQ (next-frontier after BOTH warp-EXILE "
         "(Class-C) AND priority-port (Class-B) closures landed; "
         "cross-lane surfaced axis — neither alone reveals it)"),
        # Class D — CLOSED (verify-first @ feature/g7-classd-castset;
        # see test_rust_shadow_bakein.py::
        # test_g7_classd_castset_seqwrap_targets_closed_then_next_frontier).
        # The S6-evidence label "the secondary 22/300 C4 LEGAL_SET_EQ
        # shape; the already-OPEN B1 keystone co-blocker (C1
        # legal_decisions==legal_actions mana/target/additional-cost
        # asymmetry); co-evolves its own B1 lane" is INVERTED:
        # verify-first found 22/23 are a SINGLE genuine in-scope
        # C1-Slice-2 bug — spell_targets_satisfiable did NOT recurse
        # Effect::Sequence, so Radiant Strike's
        # Sequence(DestroyTargetArtifactOrTappedCreature, GainLife{3})
        # (whose targeted leaf has ZERO legal targets — CR 601.2c) was
        # NEVER pruned (the flat loop hit the _ => {} catch-all on the
        # Sequence wrapper → conservative true). FIXED by depth-first
        # flattening Sequence children (new-code-is-right toward
        # Python's SoT; parity-neutral — only ADDS pruning Python also
        # does; all 10 C1 Slice-1/2/3 pins green). 1/23 (arch30/s1) is
        # a DISTINCT mana sub-axis (Thawbringer {2}{G}, can_pay_cost,
        # NOT the target gate) — separate filed follow-up, NOT closed
        # here.  RE-CHARACTERIZED at merge-time (cycle-37 serial-merge
        # pipeline): Class-C warp-EXILE delayed-trigger port has now
        # ALSO landed in main, so the @700 STATE_EQ ('exile_p1', ...)
        # next-frontier behind Class-D closure is itself closed; the
        # run proceeds PAST 700 to step 757 where it surfaces the
        # SAME G1 stateless-Rust attack=False re-emission axis the
        # Class-B canonical arch5/s0 row surfaces at step 369:
        # LEGAL_SET_EQ rust\py=["('attacker', 120, False)", "('attacker',
        # 120, True)"] py\rust=["('pass',)"]. The arch7/s0 attacker_id
        # 120 happens to be the same Knight Luminary that was on Rust
        # exile_p1 at the old @700 pin, but the new divergence shape
        # is the unrelated G1 attacker-decision axis (B3-S3
        # provider-accumulation port; same lane as the Class-B
        # @369-surfaced row).  Filed follow-up: f5145c1d (the Class-D
        # 1/23 Thawbringer mana sub-axis remains separate).
        (7, 0, 757, "LEGAL_SET_EQ", "('attacker', 120, False)",
         "G1 stateless-Rust attack=False re-emission (same axis as "
         "Class-B @369 row; unmasked deeper in arch7/s0 by stacking "
         "Class-D + Class-C closures)"),
        # Class E — CLOSED by the ordered-pool `ManaPool`
        # representation (rust/src/state.rs::ManaPool now carries
        # `coins: Vec<ManaCoin>` as Python-parity insertion-ordered SoT;
        # auto_tap_pay_for_cost byte-mirrors auto_tap_for_cost by
        # walking the `coins` vec in insertion order for both colored
        # matching and generic FIFO drain). The arch1/s0 bake-in now
        # proceeds PAST the old step-598 mana_pool_p1 color-residual
        # trip to step 600, surfacing the SEPARATE library_pX
        # shuffle-order axis (todo b3f7c0a9, NOT a mana-pool axis).
        # See test_rust_shadow_bakein.py::
        # test_g7_classe_mana_generic_pool_drain_order_root_cause_pinned
        # (closure pin) +
        # test_g7_classe_closed_then_library_shuffle_order_next_frontier_surfaced
        # (next-frontier pin) for the dedicated red-before/green-after
        # contract.
        # Class E — CLOSED by ordered-pool ``ManaPool``; the
        # b3f7c0a9 library-shuffle-order axis that surfaced behind
        # Class-E @600 is ALSO CLOSED (matched-rng installation in
        # ``build_shadow_checked_adapter``). The run proceeds PAST
        # @600 to @610 where it surfaces a STATE_EQ on ``life_p0``
        # (16, 20) — a 4-life delta on p0. Same life-total STATE_EQ
        # axis as the Class-C arch1/s1 @356 row (``('life_p0', 17,
        # 20)``), just a different seed/step. Pre-existing axis,
        # unmasked — NOT introduced — by stacking the b3f7c0a9
        # closure on top of Class-E.
        (1, 0, 610, "STATE_EQ", "('life_p0', 16, 20)",
         "life-total STATE_EQ (next-frontier behind the stacked "
         "Class-E + b3f7c0a9 closures; cross-seed twin of the "
         "Class-C arch1/s1 row)"),
    ],
)
def test_s6_complete_frontier_inventory(
    arch, seed, exp_step, kind, needle, axis_class
):
    """Every distinct S6 frontier class trips LOUDLY at its
    freshly-characterized boundary — the bake-in is a faithful
    tripwire (no silent passes, no axis masked). Each class is a
    distinct, pre-existing, already-tracked axis (``axis_class``).
    The enumerated finite set IS the S7 gate: if any pinned frontier
    stops firing here, the axis was closed elsewhere — RE-CHARACTERIZE
    (do NOT silently pass; that would be exactly the masking S6
    exists to rule out)."""
    pytest.importorskip("mtg_bot_engine")
    steps, raised, raw_exc = _drive_to_trip(arch, seed)
    assert steps == exp_step, (
        f"[{axis_class}] arch{arch}/s{seed}: expected boundary step "
        f"{exp_step}, got {steps}. Frontier MOVED — re-characterize "
        f"(do NOT bump/pass silently)."
    )
    surfaced = str(raised) if raised is not None else str(raw_exc)
    assert "hand_p0" not in surfaced and "blocker" not in surfaced, (
        f"[{axis_class}] arch{arch}/s{seed}: surfaced divergence "
        f"mentions a CLOSED axis (hand_p0/blocker) — REGRESSION: "
        f"{surfaced[:300]!r}."
    )
    if kind == "raw":
        assert raw_exc is not None and raised is None, (
            f"[{axis_class}] arch{arch}/s{seed}: expected RAW "
            f"exception, raw={raw_exc!r} tripwire={raised!r}."
        )
        assert needle in str(raw_exc), (
            f"[{axis_class}] arch{arch}/s{seed}: expected {needle!r}, "
            f"got {str(raw_exc)[:300]!r}."
        )
    else:
        assert raised is not None and raw_exc is None, (
            f"[{axis_class}] arch{arch}/s{seed}: expected a {kind} "
            f"ShadowDivergenceError, raised={raised!r} raw={raw_exc!r}."
        )
        assert raised.tripwire == kind, (
            f"[{axis_class}] arch{arch}/s{seed}: expected tripwire "
            f"{kind}, got {raised.tripwire}: {str(raised)[:300]!r}."
        )
        assert needle in str(raised), (
            f"[{axis_class}] arch{arch}/s{seed}: expected {needle!r}, "
            f"got {str(raised)[:300]!r}."
        )


def test_s6_no_new_masking_negative_controls_intact():
    """NO-NEW-MASKING (the load-bearing S6 verdict). The bake-in's
    ``_DOCUMENTED_ACCEPTED_FIELDS`` is EMPTY (no field carve-out), and
    all three tripwires FIRE LOUDLY on injected divergence — so a
    frontier that no longer trips was genuinely CLOSED, never masked.
    This pin locks the empty-frozenset invariant + re-asserts the
    negative-control discipline at the S6 boundary (the same
    discipline ``test_rust_shadow_bakein.py`` proves, re-pinned here
    so S6's NO-NEW-MASKING claim has its own committed guard)."""
    pytest.importorskip("mtg_bot_engine")
    from mtg_bot.actions import PlayLand
    from mtg_bot.search.rust_shadow import ShadowCheckedRustAdapter

    # (i) The frozenset stays EMPTY — nothing is accepted/masked. A
    #     non-empty set here would be the false-green S6 must rule out.
    assert ShadowCheckedRustAdapter._DOCUMENTED_ACCEPTED_FIELDS == \
        frozenset(), (
        "S6 NO-NEW-MASKING VIOLATION: _DOCUMENTED_ACCEPTED_FIELDS is "
        "non-empty — a field was masked rather than the axis fixed. "
        f"Got {ShadowCheckedRustAdapter._DOCUMENTED_ACCEPTED_FIELDS!r}."
    )

    # (ii) The STATE_EQ tripwire still FIRES on an injected post-state
    #      divergence (not a silent pass) — the bake-in is a faithful
    #      detector at the S6 boundary.
    from mtg_bot.parity import trajectory
    from mtg_bot.search.engine_adapter_factory import (
        build_shadow_checked_adapter,
    )
    from mtg_bot.actions import PassPriority

    names = trajectory.load_production_deck(archetype=0)
    spec = trajectory.production_deck_to_deckspec(
        names, shared_rng_seed=0
    )
    adapter = build_shadow_checked_adapter(spec)
    legal = adapter.legal_decisions()
    choice = next(
        (d for d in legal if isinstance(d, PassPriority)), legal[0]
    )
    # Desync: apply to Rust only, then assert STATE_EQ catches it.
    adapter._rust.apply(choice)
    with pytest.raises(ShadowDivergenceError) as ei:
        adapter._assert_state_eq()
    assert ei.value.tripwire == "STATE_EQ", (
        "S6 NO-NEW-MASKING: STATE_EQ must fire LOUDLY on an injected "
        f"divergence (got {ei.value.tripwire})."
    )
