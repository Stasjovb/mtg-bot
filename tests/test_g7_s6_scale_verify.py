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
        # Frontier (b) — the G5-family priority-port STATE_EQ
        # (deeper production-deck manifestation than the synthetic G5).
        (5, 0, 367, "STATE_EQ", "('priority_player', 1, 0)"),
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
        # Class B — G5-family priority-port STATE_EQ.
        (5, 0, 367, "STATE_EQ", "('priority_player', 1, 0)",
         "G5-family (priority-port)"),
        # Class C — RE-CHARACTERIZED (verify-first @ main 3a963e0f;
        # see test_rust_shadow_bakein.py::
        # test_g7_classc_warpexile_delayed_trigger_root_cause_pinned).
        # The S6-evidence label "warp-creature atomic resolve / S4b"
        # is CONTRADICTED: S4 (bb9e490b) + S5a (eb0fd0ca) already
        # landed (ancestors of this S6 sweep a9126b06), so
        # cast_creature_warp is NOT atomic — the warp creature
        # (Starbreach Whale, Warp {1}{U}, obj 81) goes cast→stack→bf
        # byte-IDENTICAL to Python for ~17 steps. The REAL Class-C
        # root cause is the warp-EXILE delayed-trigger-vs-
        # deterministic-sweep DOCUMENTED deliberate divergence
        # (SEARCH_LIMITATIONS.md "warp end-step exile is a
        # PHASE_END_STEP-entry sweep, NOT a CR-603.7 delayed
        # trigger"): at the END step (step 169) Python pushes the
        # WarpExileSelf delayed trigger onto the stack (response
        # window) while Rust's deterministic phase-entry sweep has
        # already moved the creature bf→exile_p1. Pre-existing
        # documented divergence surfaced at scale, NOT the brief's
        # atomic-cast hole. (boundary step + needle UNCHANGED — the
        # pin's verdict was firing correctly, only its root-cause
        # label was wrong.) The library_pX sub-variants are a
        # SEPARATE shuffle-order axis (todo b3f7c0a9), not Class C.
        (1, 1, 169, "STATE_EQ", "Starbreach Whale",
         "warp-EXILE delayed-trigger-vs-deterministic-sweep "
         "(SEARCH_LIMITATIONS documented divergence; NOT atomic-cast)"),
        # Class D — B1/C1 keystone: Rust legal_decisions offers a
        # plain CastSpell (no warp/kick/free/impending flags) Python's
        # raw legal_actions does not — the C1
        # legal_decisions==legal_actions mana/target/additional-cost
        # asymmetry (the secondary 22/300 C4 LEGAL_SET_EQ shape; the
        # already-OPEN B1 keystone co-blocker, NOT a new G-axis).
        (7, 0, 453, "LEGAL_SET_EQ",
         "('cast_spell', 76, False, False, False, False, None)",
         "B1-keystone/C1 (legal_decisions==legal_actions cast set)"),
        # Class E — RE-CHARACTERIZED (verify-first @ main 430f3b39;
        # see test_rust_shadow_bakein.py::
        # test_g7_classe_mana_generic_pool_drain_order_root_cause_pinned).
        # The S6-evidence label "C1-family mana-SOURCE color selection
        # (auto-tap land/source pick order)" is REFINED: the
        # colored-pip order + colored-land tap order ALREADY byte-match
        # Python (frontier-a settled those). The REAL root cause is the
        # GENERIC-cost drain ORDER from the floating mana POOL: Python's
        # auto_tap_for_cost (actions.py:964-976 — the SoT both
        # _cast_spell and _activate_ability pay through) drains generic
        # in p.mana_pool LIST/insertion order; Rust's
        # auto_tap_pay_for_cost (state_ops_cast.rs:472-483) drains
        # generic in a fixed C→W→U→B→R→G color priority. arch1/s0 @ 598
        # the {2}-generic Lander activation: pool list [G,G,U,U] →
        # Python keeps U:2, Rust keeps G:2 (same total, different
        # color). HOMOGENEOUS — 31/31 the same root cause
        # (scout_classe_characterize.py). The faithful fix is an
        # ordered-pool ManaPool representation (out of the
        # state_ops_cast/mana-only lane scope; filed follow-up todo).
        # (boundary step + needle UNCHANGED — the pin's verdict was
        # firing correctly, only its root-cause label was imprecise.)
        (1, 0, 598, "STATE_EQ", "mana_pool_p1",
         "auto_tap_for_cost generic-pool-drain ORDER "
         "(Python list-order vs Rust fixed C→W→U→B→R→G; "
         "ordered-pool repr fix out of lane scope)"),
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
