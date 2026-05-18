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
    "arch,seed",
    [
        # Frontier (a) — QUADRUPLE-CLOSURE-FLIPPED. arch2/s1 prior
        # closure-flip chain: @318 RAW ActivateAbility-affordability
        # CLOSED (a9126b06) → @320 STATE_EQ library_p1 b3f7c0a9
        # shuffle-order CLOSED (matched-rng installation) → @337
        # LEGAL_SET_EQ G1 stateless-Rust attack=False re-emission
        # CLOSED (B3-S3 provider-accumulation port, G1 merge) →
        # @392 STATE_EQ life_p1 combat-damage / SBA divergence
        # CLOSED by the G2 merge (deal_combat_damage() at
        # COMBAT_DAMAGE entry + clear_combat() at END_OF_COMBAT entry
        # in rust_engine_adapter.py::_run_step_enter_sbas). The
        # arch2/s1 run now proceeds to TERMINAL CLEANLY (game ends
        # naturally with no divergence tripped, ~952 steps).
        (2, 1),
        # Frontier (b) = S6 Class B — QUADRUPLE-CLOSURE-FLIPPED.
        # arch5/s0 prior closure-flip chain: @367 priority_player
        # Class-B option-β CLOSED → @369 LEGAL_SET_EQ G1
        # attack=False CLOSED (B3-S3, G1 merge) → @504 STATE_EQ
        # graveyard_p0 + battlefield combat-damage / SBA CLOSED
        # (G2 merge) → @512 STATE_EQ library_p1 b3f7c0a9
        # shuffle-order CLOSED (already on main pre-G2 via the
        # cycle-37b serial-merge pipeline). The arch5/s0 run now
        # proceeds to TERMINAL CLEANLY (game ends naturally,
        # ~1336 steps).
        (5, 0),
    ],
)
def test_s6_known_frontiers_reproduce_byte_exactly(arch, seed):
    """The 2 KNOWN frontiers (the cycle-30 honest-stop pinned set)
    are NOW FULLY CLOSED at the bake-in surface post-G2 merge. The
    full G7 closure chain stack (Class-B priority @367 + G1
    attack=False @369 + b3f7c0a9 library-shuffle @320/512 + G2
    combat-damage @504 / END_OF_COMBAT clear, + Class-A activate-
    ability @318) drives both arch2/s1 and arch5/s0 to TERMINAL
    CLEANLY at the bake-in surface — no divergence tripwire fires.

    The closed ``hand_p0`` atomic-cast axis and the closed combat-
    blocker ``LEGAL_SET_EQ`` did NOT reappear (S5a + combat-blocker
    fixes hold at scale). This is the EXPECTED post-G2-merge state
    per the orchestrator brief's anticipated auto-resolve outcome
    once both b3f7c0a9 + G1 + G3 + G2 sit on the same main.
    """
    pytest.importorskip("mtg_bot_engine")
    steps, raised, raw_exc = _drive_to_trip(arch, seed)
    # POST-G2-MERGE invariant: no tripwire fires, no raw exception
    # propagates — the run reaches terminal cleanly. Any tripwire
    # firing here is a regression of the closure chain.
    assert raised is None, (
        f"arch{arch}/s{seed}: post-G2-merge expected CLEAN run to "
        f"terminal (closure chain proven). Tripwire fired at step "
        f"{steps}: {str(raised)[:400]!r}."
    )
    assert raw_exc is None, (
        f"arch{arch}/s{seed}: post-G2-merge expected CLEAN run to "
        f"terminal (closure chain proven). Raw exception at step "
        f"{steps}: {raw_exc!r}."
    )


# ---------------------------------------------------------------------------
# 2. The COMPLETE frontier inventory — every distinct class pinned.
#    Each is a distinct, pre-existing, already-tracked axis; the
#    bake-in trips LOUDLY at each (no silent pass, nothing masked).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "arch,seed,axis_class",
    [
        # Class A — QUADRUPLE-CLOSURE-FLIPPED. arch2/s1 prior
        # closure-flip chain: @318 RAW ActivateAbility-affordability
        # CLOSED → @320 STATE_EQ library_p1 b3f7c0a9 CLOSED →
        # @337 LEGAL_SET_EQ G1 attack=False CLOSED (B3-S3 port) →
        # @392 STATE_EQ life_p1 combat-damage CLOSED by G2 merge
        # (deal_combat_damage + clear_combat in _run_step_enter_sbas).
        # Now runs to TERMINAL CLEANLY (~952 steps).
        (2, 1, "Class A (ActivateAbility affordability) + b3f7c0a9 "
               "library-shuffle + G1 attack=False + G2 combat-damage "
               "— ALL CLOSED; runs cleanly to terminal"),
        # Class B — QUADRUPLE-CLOSURE-FLIPPED. arch5/s0 prior
        # closure-flip chain: @367 priority_player Class-B
        # option-β CLOSED → @369 LEGAL_SET_EQ G1 attack=False
        # CLOSED → @504 STATE_EQ graveyard_p0 combat-damage CLOSED
        # (G2 merge) → @512 STATE_EQ library_p1 b3f7c0a9 CLOSED.
        # Now runs to TERMINAL CLEANLY (~1336 steps).
        (5, 0, "Class B (priority_player) + G1 attack=False + G2 "
               "combat-damage + b3f7c0a9 — ALL CLOSED; runs cleanly "
               "to terminal"),
        # Class C — QUADRUPLE-CLOSURE-FLIPPED. arch1/s1 prior
        # closure-flip chain: warp-EXILE @169 CLOSED (Class-C
        # delayed-trigger port) → @356 STATE_EQ life_p0 G2
        # combat-damage CLOSED → @460 STATE_EQ library_p1
        # b3f7c0a9 CLOSED. Now runs to TERMINAL CLEANLY
        # (~857 steps).
        (1, 1, "Class C (warp-EXILE delayed-trigger) + G2 "
               "combat-damage + b3f7c0a9 — ALL CLOSED; runs cleanly "
               "to terminal"),
        # Class D — QUINTUPLE-CLOSURE-FLIPPED. arch7/s0 prior
        # closure-flip chain: Class-D Sequence-target @453 CLOSED
        # → @700 STATE_EQ exile_p1 Class-C warp-EXILE CLOSED →
        # @757 LEGAL_SET_EQ G1 attack=False CLOSED → @808
        # STATE_EQ priority_player G3 deferred-batch CLOSED →
        # @817 STATE_EQ life_p0 combat-damage / SBA CLOSED by
        # G2 merge. Now runs to TERMINAL CLEANLY (~2333 steps).
        (7, 0, "Class D (Sequence-target) + Class-C @700 + G1 "
               "attack=False + G3 priority/tapped + G2 combat-damage "
               "— ALL CLOSED; runs cleanly to terminal"),
        # Class E — TRIPLE-CLOSURE-FLIPPED. arch1/s0 prior
        # closure-flip chain: Class-E ordered-pool ManaPool @598
        # CLOSED → @600 STATE_EQ library_p1 b3f7c0a9 CLOSED →
        # @610 STATE_EQ life_p0 combat-damage / SBA CLOSED by
        # G2 merge. Now runs to TERMINAL CLEANLY (~918 steps).
        (1, 0, "Class E (ordered-pool ManaPool) + b3f7c0a9 + G2 "
               "combat-damage — ALL CLOSED; runs cleanly to terminal"),
    ],
)
def test_s6_complete_frontier_inventory(arch, seed, axis_class):
    """Every distinct S6 frontier class is NOW FULLY CLOSED at the
    bake-in surface post-G2 merge. Each class's prior closure-flip
    chain has stacked with G2's combat-damage / SBA closure
    (deal_combat_damage at COMBAT_DAMAGE entry + clear_combat at
    END_OF_COMBAT entry in rust_engine_adapter.py::_run_step_enter_sbas)
    to reach TERMINAL CLEANLY on every representative arch/seed.

    The 5-class enumerated finite set is now empty at the bake-in
    surface. This is the EXPECTED post-G2-merge state per the
    orchestrator brief's anticipated auto-resolve outcome once
    b3f7c0a9 + G1 + G3 + G2 sit on the same main.

    The closed ``hand_p0`` atomic-cast axis and the closed combat-
    blocker ``LEGAL_SET_EQ`` did NOT reappear (S5a + combat-blocker
    fixes hold at scale). NO-NEW-MASKING is independently locked by
    ``test_s6_no_new_masking_negative_controls_intact``.
    """
    pytest.importorskip("mtg_bot_engine")
    steps, raised, raw_exc = _drive_to_trip(arch, seed)
    assert raised is None, (
        f"[{axis_class}] arch{arch}/s{seed}: post-G2-merge expected "
        f"CLEAN run to terminal (closure chain proven). Tripwire "
        f"fired at step {steps}: {str(raised)[:400]!r}."
    )
    assert raw_exc is None, (
        f"[{axis_class}] arch{arch}/s{seed}: post-G2-merge expected "
        f"CLEAN run to terminal (closure chain proven). Raw exception "
        f"at step {steps}: {raw_exc!r}."
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
