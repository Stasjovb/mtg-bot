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
        # Frontier (a) — the B1-axis analog: Rust legal-emit-vs-apply
        # self-inconsistency on ActivateAbility mana-affordability. RAW
        # ValueError (rust_shadow only converts a *Python*-side apply
        # raise to NO_RAISE; a Rust-side raise propagates raw).
        (2, 1, 318, "raw",
         "ActivateAbility: source 121 cost is unaffordable"),
        # Frontier (b) — TRIPLE-CLOSURE-FLIPPED (the present G2 slice
        # extends the prior closure stack). The cycle-37 S6 Class-B
        # option-β engine+adapter slice closed the @367
        # ``priority_player`` axis; the cycle-38 B3-S3
        # provider-accumulation port closed the @369 G1 stateless-Rust
        # ``attack=False`` re-emission gap; the present G2 slice
        # (``feature/g7-g2-combat-damage-sba-axis``,
        # ``rust_engine_adapter.py::_run_step_enter_sbas``: add
        # ``deal_combat_damage()`` BEFORE the SBA at COMBAT_DAMAGE
        # entry + add ``clear_combat()`` at END_OF_COMBAT entry)
        # closes the @504 ``STATE_EQ`` combat-damage outcome / SBA
        # divergence (todo ``504a1c7d``). Step 504 no longer trips.
        # The run proceeds PAST 504 to step 512 surfacing the
        # b3f7c0a9 library-SHUFFLE-ORDER axis ``('library_p1', ...)``
        # — SIBLING-OWNED
        # (``feature/g7-b3f7c0a9-library-shuffle-order-parity``,
        # LANDED on its branch, NOT MERGED at the time of the present
        # G2 slice). NOT a regression of @367 / @369 / @504 — the
        # surfaced axis is the next per-repro frontier the sibling
        # lane owns.
        (5, 0, 512, "STATE_EQ", "('library_p1'"),
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
        # Class A — B1-axis analog (ActivateAbility legal-emit-vs-apply
        # mana-affordability self-inconsistency). RAW ValueError.
        (2, 1, 318, "raw",
         "ActivateAbility: source 121 cost is unaffordable",
         "B1-axis (ActivateAbility affordability)"),
        # Class B — TRIPLE-CLOSURE-FLIPPED. The cycle-37 Class-B
        # option-β engine+adapter slice closed the @367 priority axis;
        # the cycle-38 B3-S3 provider-accumulation port closed the
        # @369 G1 stateless-Rust ``attack=False`` re-emission axis;
        # the present G2 slice closes the @504 combat-damage outcome
        # / SBA divergence (todo ``504a1c7d``;
        # ``feature/g7-g2-combat-damage-sba-axis``; adds
        # ``deal_combat_damage()`` BEFORE the SBA at COMBAT_DAMAGE
        # entry + adds ``clear_combat()`` at END_OF_COMBAT entry in
        # ``rust_engine_adapter.py::_run_step_enter_sbas``). The
        # arch5/s0 row proceeds PAST step 504 to step 512 surfacing
        # the b3f7c0a9 library-SHUFFLE-ORDER axis ``('library_p1',
        # ...)`` — SIBLING-OWNED
        # (``feature/g7-b3f7c0a9-library-shuffle-order-parity``,
        # LANDED on its branch, NOT MERGED at the time of the present
        # G2 slice). The next per-repro frontier the sibling lane
        # owns.
        (5, 0, 512, "STATE_EQ", "('library_p1'",
         "b3f7c0a9 library-shuffle-order axis (Class-B priority @367 "
         "+ G1 attack=False @369 + G2 combat-damage @504 ALL CLOSED; "
         "sibling-owned next-frontier)"),
        # Class C — CLOSED via the delayed-trigger port
        # (feature/g7-classc-warp-delayed-trigger). The warp-EXILE
        # delayed-trigger-vs-deterministic-sweep axis previously
        # surfaced at arch1/s1 step 169 ("Starbreach Whale", three-
        # field {bf, exile_p1, stack} STATE_EQ). With the new Rust
        # state.delayed_triggers + Effect::WarpExileSelf +
        # run_delayed_end_step_triggers landed, arch1/s1 runs MANY
        # steps past 169.  RE-CHARACTERIZED at G7 G2 combat-damage /
        # SBA closure (this slice,
        # ``feature/g7-g2-combat-damage-sba-axis``): the prior
        # cross-lane life-total STATE_EQ at step 356 (`('life_p0',
        # 17, 20)`) had the G2 combat-damage outcome / SBA divergence
        # as its UNDERLYING root cause — the Rust bridge's
        # ``_run_step_enter_sbas`` at COMBAT_DAMAGE entry mirrored
        # Python's ``state_based_actions`` call but not Python's
        # preceding ``resolve_combat_damage`` call
        # (``engine_adapter.py:1261-1264``). G2 fix closes the
        # life-total divergence: arch1/s1 runs PAST step 356 and
        # surfaces at step 460 on the b3f7c0a9 library-SHUFFLE-ORDER
        # axis ``('library_p1', ...)`` — SIBLING-OWNED
        # (``feature/g7-b3f7c0a9-library-shuffle-order-parity``,
        # LANDED on its branch, NOT MERGED at the time of the present
        # G2 slice). NOT a regression of Class-C / Class-B / G2 — the
        # surfaced axis is the next per-repro frontier the sibling
        # lane owns.
        (1, 1, 460, "STATE_EQ", "('library_p1'",
         "b3f7c0a9 library-shuffle-order axis (warp-EXILE Class-C + "
         "priority-port Class-B + G2 combat-damage life-total ALL "
         "CLOSED; sibling-owned next-frontier)"),
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
        # Class D — TRIPLE-CLOSURE-FLIPPED. Class-D Sequence-target
        # axis (was @453) + Class-C warp-EXILE @700 + the present
        # @757 G1 attack=False axis are now ALL closed; arch7/s0
        # proceeds PAST 757 to step 808 on a NEW distinct G-axis:
        # ``STATE_EQ`` ``('priority_player', 0, 1)`` + a battlefield
        # diff on Knight Luminary's tapped state (obj id 70:
        # ``tapped=0`` py vs ``tapped=1`` rust). NEW G-axis (priority
        # + tapped state divergence in the post-combat-damage tail);
        # filed as the next G7 follow-up.
        (7, 0, 808, "STATE_EQ", "('priority_player', 0, 1)",
         "priority + tapped-state STATE_EQ (G1 attack=False @757 + "
         "Class-D Sequence-target @453 + Class-C @700 ALL CLOSED; "
         "new G-axis surfaced past @757)"),
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
        (1, 0, 600, "STATE_EQ", "library_p1",
         "Class-E CLOSED → next frontier is the b3f7c0a9 "
         "library-shuffle-order axis (SEPARATE, NOT a mana-pool "
         "regression)"),
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
