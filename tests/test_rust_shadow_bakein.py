"""B3-S4 — the ``rust_shadow`` mode + the 4-assertion equivalence
tripwire (LEGAL_SET_EQ / CHOSEN_EQ / STATE_EQ / NO_RAISE).

Covers:
* ``canon_decision`` / ``canon_set`` — order-independent, scoped to
  the LEGAL_SET_EQ kinds;
* a clean shadow-checked game runs divergence-clean to terminal (the
  tripwire holds every step on a matched state);
* the tripwire FIRES LOUDLY on an injected divergence (negative
  control — proves the bake-in is not a silent no-op:
  feedback_no_fallback_hybrids / feedback_silent_noop_pipelines);
* ``decision_source="rust_shadow"`` is reachable via the factory
  bake-in entry point; the parity-safe default ("python") is
  untouched.
"""

from __future__ import annotations

import random

import pytest

from mtg_bot.actions import CastSpell, PassPriority, PlayLand
from mtg_bot.search.protocol import GameState as GameStateProtocol
from mtg_bot.search.rust_shadow import (
    ShadowDivergenceError, canon_decision, canon_set,
)


# ---------------------------------------------------------------------------
# canon
# ---------------------------------------------------------------------------


def test_canon_decision_keys():
    assert canon_decision(PassPriority()) == ("pass",)
    assert canon_decision(PlayLand(card_id=5)) == ("play_land", 5)
    assert canon_decision(CastSpell(card_id=7, use_warp=True)) == (
        "cast_spell", 7, True, False, False, False, None,
    )


def test_canon_set_is_order_independent_and_scoped():
    a = [PassPriority(), PlayLand(card_id=2), PlayLand(card_id=1)]
    b = [PlayLand(card_id=1), PassPriority(), PlayLand(card_id=2)]
    assert canon_set(a) == canon_set(b)
    # Resolution* / unknown kinds are NOT in the scoped set.

    class _Weird:
        pass

    assert canon_set([_Weird(), PassPriority()]) == {("pass",)}


# ---------------------------------------------------------------------------
# clean shadow run — divergence-clean to terminal
# ---------------------------------------------------------------------------


def _shadow(spec_fn=None):
    pytest.importorskip("mtg_bot_engine")
    from mtg_bot.parity.cross_engine import tiny_synthetic_deckspec
    from mtg_bot.search.engine_adapter_factory import (
        build_shadow_checked_adapter,
    )

    return build_shadow_checked_adapter(
        (spec_fn or tiny_synthetic_deckspec)()
    )


def test_shadow_is_protocol_conformant():
    adapter = _shadow()
    assert isinstance(adapter, GameStateProtocol)
    assert adapter.players() == [0, 1]
    assert adapter.chance_outcomes() == []


def test_shadow_runs_divergence_clean_over_the_valid_prefix():
    """The bake-in must run divergence-clean (all four assertions
    hold every step) over the matched start state + a bounded prefix.
    This proves the shadow-checker harness itself is correct + the
    matched states start byte-equal. 40 steps is comfortably inside
    the divergence-clean window for the tiny synthetic deck.

    (Pre-G4-closure this window stopped at ~step 143 where the I20
    mana-timing asymmetry tripped LEGAL_SET_EQ; G4 is now CLOSED by
    the lockstep mana mirror — see
    test_g4_i20_cast_set_axis_is_closed_by_lockstep — so the clean
    window now extends through the entire mana-floating window.)"""
    adapter = _shadow()
    rng = random.Random(2026)
    for _ in range(40):
        if adapter.is_terminal():
            break
        legal = adapter.legal_decisions()  # asserts LEGAL_SET_EQ
        assert legal
        choice = rng.choice(legal)
        adapter.apply(choice)  # CHOSEN_EQ + STATE_EQ + NO_RAISE
    # Reaching here without ShadowDivergenceError == the harness is
    # divergence-clean over the valid window.


def test_g7s4_rust_shadow_warp_deck_clean_prefix_then_known_legal_emit_gap():
    """**G7 S4 rust_shadow pin** — drives the role-swapped
    ``ShadowCheckedRustAdapter`` over a synthetic *warp* deck
    (``_r63_warp_synth_deckspec``: {3}{R} / warp {1}{R} 3/3 +
    Forests) with the uniform-random driver
    (``drive_shadow_game_to_terminal`` contract).

    **VERIFIED (this commit, both engines built from source):**

    1. **S4 does NOT regress the bake-in.** The run is
       divergence-clean over the bounded prefix BEFORE the
       pre-existing step-220 trip point — byte-IDENTICAL to ``main``
       @ ``cd3a5f4e`` (same seed=2026, same first-divergence step
       220, same error). S4 changes the warp-cast *resolve shape*
       (atomic → stack-then-resolve); it does NOT move the bake-in's
       first-divergence boundary. (S1's plain-creature rust_shadow
       proof used the same "clean over the window" contract.)

    2. **The step-220 divergence is a PRE-EXISTING, main-identical
       ``LEGAL_SET_EQ`` warp-cast-EMISSION gap — NOT S4's scope, NOT
       a regression, NOT papered.** At step ~220 the role-swapped
       contract surfaces ``rust\\py=[('cast_spell', 0, True, ...)]
       py\\rust=[]``: Rust's ``legal_decisions`` offers a warp
       ``cast_spell`` the Python shadow's legal set does not (a
       legal-EMISSION asymmetry on the warp-cast OFFER — the
       I20/G4-class mana-timing / warp legal-emission axis). The
       random driver never even APPLIES a warp cast because the
       legal-set diverges first. This was verified byte-identical on
       ``main`` (pre-S4) — S4 owns the warp-cast resolve SHAPE
       (proven byte-equal by the direct ``apply`` + ``step_both``
       cross-engine probes in ``test_cross_engine_etb_triggers.py``),
       NOT the warp-cast legal-EMISSION parity, which is a separate
       axis owned by a later slice (S5+/legal-emission; see
       ``docs/G7_S4_VERIFY_FINDING.md`` §5 + ``docs/
       SEARCH_LIMITATIONS.md`` G7-S4 note).

    This pin is the honest-stop: it asserts the prefix is clean
    (no S4 regression) AND that the known pre-existing divergence is
    SURFACED at its characterized boundary (loud, not masked). If a
    future slice closes the warp legal-emission axis, the
    ``raised is not None`` assertion flips and this pin must be
    updated to the closed contract (new-code-is-right)."""
    from tests.test_cross_engine_etb_triggers import (
        _r63_warp_synth_deckspec,
    )

    adapter = _shadow(_r63_warp_synth_deckspec)
    rng = random.Random(2026)
    steps = 0
    raised: ShadowDivergenceError | None = None
    clean_prefix = 0
    while not adapter.is_terminal() and steps < 400:
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
        steps += 1
        clean_prefix = steps

    # (1) No S4 regression: a substantial divergence-clean prefix
    # (the pre-existing trip is at ~step 220; require the prefix to
    # reach well past where an atomic-vs-stack warp-cast STATE_EQ
    # regression would have fired — i.e. S4's stack-then-resolve
    # composes clean for every decision the driver applied here).
    assert clean_prefix >= 200, (
        f"S4 must NOT regress the bake-in: the divergence-clean "
        f"prefix over the synthetic warp deck must reach the "
        f"pre-existing ~step-220 boundary (byte-identical to main). "
        f"Got only {clean_prefix} clean steps — an atomic-vs-stack "
        f"warp-cast STATE_EQ regression would fire MUCH earlier. "
        f"err={raised!r}"
    )
    # (2) The known pre-existing legal-emission gap is SURFACED
    # (honest-stop, not masked). It is a LEGAL_SET_EQ on a warp
    # cast_spell OFFER (Rust offers, Python shadow does not) — the
    # legal-EMISSION axis, NOT S4's resolve-shape scope; verified
    # main-identical (pre-S4).
    assert raised is not None, (
        "the known pre-existing warp legal-emission divergence must "
        "still SURFACE (it was verified main-identical). If it no "
        "longer fires, the legal-emission axis was closed elsewhere "
        "— update this pin to the closed contract (do NOT silently "
        "let it pass)."
    )
    msg = str(raised)
    assert "LEGAL_SET_EQ" in msg and "cast_spell" in msg, (
        f"the surfaced divergence must be the characterized "
        f"warp-cast LEGAL_SET_EQ emission gap (legal-emission axis, "
        f"S5+/separate slice — NOT S4's resolve-shape scope, NOT a "
        f"regression). Got a DIFFERENT divergence: {msg!r} — this "
        f"would be an honest-stop-unmasked NEW divergence; pin it + "
        f"flag the slice owner per the S4 brief, do NOT paper it."
    )


def test_g7_combat_blocker_legalset_closed_then_next_frontier_surfaced():
    """**G7 combat-blocker LEGAL_SET closure-flip** (was
    ``test_g7_s5a_spellstack_zone_closed_then_blocker_legalset_surfaced``;
    todo ``fec5f14``).

    **PRIOR FRONTIER — CLOSED by the combat-blocker legal-emission
    fix (engine, new-code-is-right toward the Python SoT).** The S5a
    honest-stop pinned a post-``hand_p0``-closure ``LEGAL_SET_EQ`` at
    arch2/s1 step **312** / arch5/s0 step **344**: in a
    DECLARE_BLOCKERS step with priority on the off-active (defender)
    player, empty stack, and an untapped defender creature but **ZERO
    attacking creatures**, Rust's blocker-decision emitter
    (``rust/src/state_ops_legal.rs`` declare-blockers region) still
    emitted ``('blocker', N, None)`` (arch2/s1 N=9, arch5/s0 N=12),
    whereas Python's ``MtgGameStateAdapter._enter_declare_blockers``
    (``engine_adapter.py:1322-1329``) takes the
    ``if not attackers: self._enter_priority_for_current_step();
    return`` branch — it NEVER sets ``_combat_phase``, so the
    rust_shadow combat-window reference (``rust_shadow.py:281-286``,
    the Python adapter's ``legal_decisions()``) emits NO
    ``BlockerDecision`` (``py\\rust`` empty = Rust over-emits). **The
    fix adds the byte-mirror no-attackers gate to the Rust emitter:
    ``&& !self.attackers.is_empty()``** (Rust's canonical
    "is attacking" predicate is ``state.attackers`` membership — see
    the ``FocusFireEffect`` arm, ``state_ops_legal.rs:789-790``; the
    byte-equal analog of Python's ``[o for o in battlefield if
    o.attacking]``). The combat-blocker ``LEGAL_SET_EQ`` NO LONGER
    fires at 312/344: both runs proceed PAST the old boundary.

    **NEXT DISTINCT DIVERGENCE SURFACED (honest-stop — SEPARATE,
    pre-existing, surfaced — NOT introduced — by closing the
    combat-blocker axis; per-repro, NOT this lane's scope).** With the
    combat-blocker ``LEGAL_SET_EQ`` closed the bake-in runs further
    and trips a DIFFERENT divergence on each repro:

    * **arch2/s1 — step 318:** a RAW ``ValueError`` (NOT a
      ``ShadowDivergenceError`` tripwire — the rust_shadow harness
      calls ``self._rust.apply`` raw before the NO_RAISE wrapper, so a
      Rust-side raise is not converted). Rust's ``legal_decisions``
      offers ``ActivateAbility(source_id=121, ability_index=0)`` but
      Rust's own ``apply_action`` rejects it: *"ActivateAbility:
      source 121 cost is unaffordable from controller's mana pool
      (mana_cost generic=2, W=0, U=0, B=0, R=0, G=0)"*. A
      **Rust-internal legal-emit-vs-apply self-inconsistency** on
      activated-ability mana-affordability (a C1-class legal-emission
      gap — the Rust emitter offers a ``{2}``-cost ability without an
      affordability gate; Rust apply correctly rejects).

    * **arch5/s0 — step 367:** a ``ShadowDivergenceError`` tripwire
      ``STATE_EQ`` on ``('priority_player', 1, 0)`` (Python=1,
      Rust=0) on a ``PassPriority()`` at a DECLARE_ATTACKERS step — a
      distinct priority-player STATE_EQ divergence (G5-family
      priority-port region, a deeper production-deck manifestation).

    Both are DISTINCT, pre-existing axes filed as the next G7
    follow-up in ``SOT_FLIP_CUTOVER_PLAN.md`` §4 +
    ``SEARCH_LIMITATIONS.md``. Per the established
    G4/G5/G6/S5a surfaced→closure-flip discipline this pin asserts
    BOTH: (1) the prior combat-blocker ``LEGAL_SET_EQ`` axis is CLOSED
    (each run goes PAST the old 312/344 boundary; no combat-blocker
    ``('blocker', N, None)`` over-emission), and (2) the new per-repro
    frontier surfaces LOUDLY at its freshly-characterized boundary
    (do NOT silently let it pass; if it stops firing the next axis was
    closed elsewhere — re-characterize this pin, do NOT just bump)."""
    pytest.importorskip("mtg_bot_engine")
    from mtg_bot.parity import trajectory
    from mtg_bot.search.engine_adapter_factory import (
        build_shadow_checked_adapter,
    )

    # Per-repro freshly-characterized next-frontier contract:
    #   old_boundary  — the closed combat-blocker LEGAL_SET_EQ step
    #                    (a trip at/before this == the fix regressed)
    #   exp_step       — the new next-frontier step
    #   kind           — "raw" (uncaught Rust-side ValueError) or
    #                    a ShadowDivergenceError tripwire name
    #   needle         — a substring uniquely characterizing it
    for (arch, seed, old_boundary, exp_step, kind, needle) in (
        (2, 1, 312, 318, "raw",
         "ActivateAbility: source 121 cost is unaffordable"),
        (5, 0, 344, 367, "STATE_EQ", "('priority_player', 1, 0)"),
    ):
        names = trajectory.load_production_deck(archetype=arch)
        spec = trajectory.production_deck_to_deckspec(
            names, shared_rng_seed=seed
        )
        adapter = build_shadow_checked_adapter(spec)
        rng = random.Random(seed)
        steps = 0
        raised: ShadowDivergenceError | None = None
        raw_exc: BaseException | None = None
        while not adapter.is_terminal() and steps < 400:
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
                # The rust_shadow harness only converts a *Python*-side
                # apply raise to NO_RAISE; a Rust-side apply_action
                # raise propagates raw. The arch2/s1 next frontier is
                # exactly this (Rust legal/apply self-inconsistency).
                raw_exc = e
                break
            steps += 1

        # (1) PRIOR combat-blocker LEGAL_SET_EQ AXIS CLOSED: the run
        # proceeds PAST the old S5a-era boundary (arch2/s1 312,
        # arch5/s0 344). A trip at/before the old boundary means the
        # no-attackers gate did NOT close the combat-blocker
        # over-emission (regression — do NOT bump the boundary, fix
        # the engine).
        assert steps > old_boundary, (
            f"arch{arch}/s{seed}: with the no-attackers gate closing "
            f"the combat-blocker LEGAL_SET_EQ the run must proceed "
            f"PAST the old boundary step {old_boundary} (it stopped at "
            f"{steps}). A stop at/before {old_boundary} means the "
            f"Rust blocker-emission no-attackers gate regressed — fix "
            f"the engine, do NOT bump the boundary."
        )
        assert steps == exp_step, (
            f"arch{arch}/s{seed}: expected the freshly-characterized "
            f"next-frontier boundary step {exp_step}, got {steps}. A "
            f"different step means the surfaced frontier moved — "
            f"re-characterize this pin, do NOT just bump."
        )
        # (2) THE NEW DISTINCT PER-REPRO FRONTIER SURFACES LOUDLY. It
        # is NOT the (now-closed) combat-blocker LEGAL_SET_EQ.
        if kind == "raw":
            assert raw_exc is not None and raised is None, (
                f"arch{arch}/s{seed}: expected the characterized "
                f"Rust-side raw {needle!r} legal/apply "
                f"self-inconsistency (NOT a ShadowDivergenceError). "
                f"raw={raw_exc!r} tripwire={raised!r}. If it no longer "
                f"fires the axis was closed elsewhere — re-characterize."
            )
            assert needle in str(raw_exc), (
                f"arch{arch}/s{seed}: the surfaced raw exception must "
                f"be PRECISELY the characterized {needle!r}. Got: "
                f"{str(raw_exc)[:300]!r}."
            )
        else:
            assert raised is not None and raw_exc is None, (
                f"arch{arch}/s{seed}: the next distinct divergence "
                f"must SURFACE as a {kind} ShadowDivergenceError. "
                f"raised={raised!r} raw={raw_exc!r}. If it no longer "
                f"fires it was closed elsewhere — re-characterize this "
                f"pin (do NOT silently pass)."
            )
            assert raised.tripwire == kind, (
                f"arch{arch}/s{seed}: expected tripwire {kind}, got "
                f"{raised.tripwire}: {str(raised)[:300]!r} — a "
                f"DIFFERENT tripwire is a further honest-stop-unmasked "
                f"divergence; re-characterize + flag the slice owner, "
                f"do NOT paper."
            )
            assert needle in str(raised), (
                f"arch{arch}/s{seed}: the surfaced {kind} must be "
                f"PRECISELY the characterized {needle!r}. Got: "
                f"{str(raised)[:300]!r}."
            )
        # The closed axis must NOT be what surfaced: neither path may
        # be the old combat-blocker ('blocker', N, None) over-emission.
        surfaced_msg = str(raised) if raised is not None else str(raw_exc)
        assert "blocker" not in surfaced_msg, (
            f"arch{arch}/s{seed}: the surfaced divergence still "
            f"mentions a blocker — the combat-blocker LEGAL_SET_EQ was "
            f"NOT actually closed: {surfaced_msg[:300]!r}."
        )


def test_g4_i20_cast_set_axis_is_closed_by_lockstep():
    """G4 CLOSURE PIN. G4 (the C1/G1-analog for the I20 axis: the
    documented Python mana-hold-until-cleanup simplification,
    turn.py:1081-1083 / RUST_PARITY_GAPS §I20, diverging the legal
    CAST SET under the role-swapped Rust-driven / Python-shadow
    contract) is **CLOSED** by
    ``ShadowCheckedRustAdapter._install_i20_phase_exit_mana_mirror``
    — it drives the Python shadow's per-phase-exit mana empty in
    lockstep with the Rust driver's CR-106.4 empty (the same
    ``advance_phase_python``-step-1 semantics the existing
    ``cross_engine.step_both`` harness already proves).

    Pre-closure, this seed tripped a LEGAL_SET_EQ ``cast_spell``
    divergence at step ~143 (Python's held-over floating mana made it
    offer a CastSpell Rust's per-phase-empty model correctly pruned).
    This pin PROVES that divergence is GONE: the run is now
    divergence-clean through the ENTIRE mana-floating window (well
    past the old step-143 G4 trip point), and the mana_pool_p0/p1
    carve-out is removed (``_DOCUMENTED_ACCEPTED_FIELDS`` is empty),
    so STATE_EQ now also asserts full mana-pool byte-equality.

    NOTE — the SEPARATE post-deck-out issue G4's closure unmasked is
    blocker **G5** (the Rust-driver priority-reset port
    ``RustGameStateAdapter._reset_priority_to_active`` vs Python's
    alive-aware ``_next_alive`` on ``priority_player``). G5 is now
    **CLOSED** (the ``_next_alive`` alive-skip port — see
    ``test_post_player_loss_priority_port_is_closed``). Closing G5 in
    turn unmasked a further distinct pre-existing
    game-over-detection-TIMING divergence (``is_over``/``winner_id``,
    NOT priority/active), tracked as blocker **G6** — also now
    **CLOSED** (the ``_run_step_enter_sbas`` SBA-cadence port — see
    ``test_post_player_loss_is_over_timing_is_closed``). None of
    G5/G6 is the I20/G4 mana axis; G4 closure does not depend on
    either and is complete without them (docs/SEARCH_LIMITATIONS.md /
    SOT_FLIP_CUTOVER_PLAN ledger)."""
    adapter = _shadow()
    rng = random.Random(2026)
    steps = 0
    raised: ShadowDivergenceError | None = None
    # 145 steps clears the old step-143 G4 trip point with margin but
    # stops BEFORE the separate ~step-149 post-deck-out priority-port
    # divergence (pinned independently below). The point of THIS pin
    # is: the I20 cast-set divergence no longer occurs in its window.
    while not adapter.is_terminal() and steps < 145:
        try:
            legal = adapter.legal_decisions()
        except ShadowDivergenceError as e:
            raised = e
            break
        choice = rng.choice(legal)
        try:
            adapter.apply(choice)
        except ShadowDivergenceError as e:
            raised = e
            break
        steps += 1
    assert raised is None, (
        f"G4 (the I20 mana-timing cast-set asymmetry) must be CLOSED "
        f"by the lockstep mana mirror — the run must be "
        f"divergence-clean through the entire mana-floating window "
        f"(it tripped at step ~143 pre-closure). Got a divergence at "
        f"step {steps}: [{raised.tripwire}] {raised}"
        if raised is not None else ""
    )
    # We ran well past the old G4 trip point with no divergence: the
    # I20 cast-set axis is closed. (>=144 also guards against a
    # premature terminal masking the result on this seed.)
    assert steps >= 144, (
        f"expected to run past the old step-143 G4 trip point; only "
        f"reached step {steps} (terminal={adapter.is_terminal()})"
    )


def test_post_player_loss_priority_port_is_closed():
    """G5 CLOSURE PIN (flipped from the former
    ``test_post_player_loss_priority_port_divergence_is_surfaced``,
    the same closure-flip pattern the G4 lane used).

    G5 was: in the degenerate 3-card ``tiny_synthetic_deckspec`` a
    player decks out by ~turn 8; when the active player has lost,
    Python's priority/active resets use ``_next_alive``
    (``simulate.py:46`` — CR-aware: skip the lost active player), but
    the Rust-driver port
    ``RustGameStateAdapter._reset_priority_to_active`` set priority to
    the (lost) active player UNCONDITIONALLY — a ``priority_player``
    STATE_EQ divergence at step ~149.

    G5 is now **CLOSED** by porting the CR-aware alive-skipping
    (``RustGameStateAdapter._next_alive_idx`` — a byte-exact mirror of
    ``simulate._next_alive`` that uses Rust's ``losers()`` eager
    OR'd-three predicate, which ``rust/src/state_ops_winloss.rs``
    explicitly documents as the byte-equal analog of Python's eager
    ``has_lost``) at ``_reset_priority_to_active`` AND the sibling
    sites carrying the same "no-loss model" assumption (the
    single-pass priority handoff and the ``_alive_count`` pass-round
    threshold). Pure Python in ``rust_engine_adapter.py`` — no Rust
    pymethod (``losers()`` already exists), no ``.pyd`` rebuild.

    This pin PROVES the G5 priority-port divergence is GONE: the
    bake-in runs divergence-CLEAN through the entire post-deck-out
    priority window (past the old step-~149 G5 ``priority_player``
    trip point) on this seed.

    NOTE — closing G5 honestly UNMASKED a SEPARATE, distinct,
    pre-existing divergence (exactly as G4's closure unmasked G5): a
    game-over-detection-TIMING gap (``is_over`` / ``winner_id``, NOT
    priority/active). Python flips ``is_over``/``winner_id`` via
    ``state_based_actions`` at the next ``_enter_step`` after a player
    decks out; the Rust-driver port did not call ``apply_sbas()`` on
    the step-end / auto-advance path, so Rust's ``is_over()`` lagged
    by one step. That DISTINCT Rust-driver SBA-timing port gap (NOT
    the G5 ``_next_alive`` priority axis, NOT the closed G4 mana
    axis) was tracked as blocker **G6** and is now itself **CLOSED**
    (the ``_run_step_enter_sbas`` SBA-cadence port — see
    ``test_post_player_loss_is_over_timing_is_closed``, which now
    drives the SAME tail divergence-clean all the way to terminal).
    This pin keeps its bounded 150-step window (it predates and is
    independent of G6's closure — it isolates the G5 priority axis
    specifically); the full-tail-to-terminal clean run is asserted by
    the G6 closure pin (feedback_no_fallback_hybrids /
    feedback_silent_noop_pipelines)."""
    adapter = _shadow()
    rng = random.Random(2026)
    steps = 0
    raised: ShadowDivergenceError | None = None
    # 150 steps clears the old step-~149 G5 priority_player trip point
    # with margin. (Pre-G6-closure this bound also stopped BEFORE the
    # distinct ~step-151 is_over-timing divergence; G6 is now closed
    # and the G6 pin below drives the same tail clean to terminal.
    # This bound stays as the isolated G5-axis window.) The point of
    # THIS pin: the G5 priority-port divergence no longer occurs.
    while not adapter.is_terminal() and steps < 150:
        try:
            legal = adapter.legal_decisions()
        except ShadowDivergenceError as e:
            raised = e
            break
        choice = rng.choice(legal)
        try:
            adapter.apply(choice)
        except ShadowDivergenceError as e:
            raised = e
            break
        steps += 1
    assert raised is None, (
        f"G5 (the post-deck-out Rust-driver priority-port "
        f"_next_alive gap) must be CLOSED by the alive-skip port — "
        f"the run must be divergence-clean through the post-deck-out "
        f"priority window (it tripped at step ~149 pre-closure on "
        f"priority_player). Got a divergence at step {steps}: "
        f"[{raised.tripwire}] {raised}"
        if raised is not None else ""
    )
    # We ran past the old G5 trip point (~149) with no divergence: the
    # priority-port axis is closed. (>=150 also guards against a
    # premature terminal masking the result on this seed.)
    assert steps >= 150, (
        f"expected to run past the old step-~149 G5 priority_player "
        f"trip point; only reached step {steps} "
        f"(terminal={adapter.is_terminal()})"
    )


def test_post_player_loss_is_over_timing_is_closed():
    """G6 CLOSURE PIN (flipped from the former
    ``test_post_player_loss_is_over_timing_divergence_is_surfaced``,
    the same closure-flip pattern the G4 and G5 lanes used).

    G6 was: in the degenerate 3-card ``tiny_synthetic_deckspec`` a
    player decks out by ~turn 8. After the pass-round at the
    post-deck-out PRECOMBAT_MAIN step ends, Python's source-of-truth
    advances the step and its next ``_enter_step`` runs
    ``state_based_actions`` (engine_adapter.py:1224/1238/1244/1264/
    1268) which flips ``is_over=True`` / ``winner_id=<survivor>``.
    The Rust-driver port
    (``RustGameStateAdapter._advance_to_next_decision`` / the step-end
    ``advance_phase`` branch in ``_run_priority_action``) did NOT call
    ``apply_sbas()`` on the step-end / auto-advance path (only after
    resolution / non-pass actions), so Rust's ``is_over()`` /
    ``winner_id`` lagged Python's by a step — a STATE_EQ ``is_over`` /
    ``winner_id`` divergence at step ~151.

    G6 is now **CLOSED** by porting Python's
    ``state_based_actions``-at-``_enter_step`` cadence into the
    Rust-driver adapter: ``RustGameStateAdapter._run_step_enter_sbas``
    calls the EXISTING Rust ``apply_sbas()`` pymethod at exactly the
    phases Python's ``_enter_step`` runs SBA at — UPKEEP /
    BEGINNING_OF_COMBAT / POSTCOMBAT_MAIN / END unconditionally and
    COMBAT_DAMAGE under Python's ``any(o.attacking ...)`` guard — and
    is invoked right after the step-progression ``advance_phase()``
    on BOTH the auto-advance loop (``_advance_to_next_decision``) and
    the empty-stack pass-round step-end (``_run_priority_action``).
    No more / no fewer ``apply_sbas()`` calls than Python's
    ``state_based_actions`` cadence (over-calling at a phase Python
    skips is forbidden). Pure Python in ``rust_engine_adapter.py`` —
    the Rust ``apply_sbas()`` pymethod already exists and is
    idempotent / write-once on the player-loss / ``winner_id`` axis
    (``state_ops_sba.rs:328-362``), so no Rust / ``.pyd`` rebuild.

    This pin PROVES the G6 is_over/winner_id SBA-timing divergence is
    GONE: the bake-in now runs divergence-CLEAN through the ENTIRE
    post-deck-out tail to terminal (past the old step-~151 G6 trip
    point) on this seed.

    NOTE — closing G6 does NOT unmask a further divergence: the run
    completes clean to the natural terminal state (the degenerate
    3-card both-decked-out tail). The G4->G5->G6 chain (all in the
    same narrow post-deck-out game-end region — mana / priority /
    SBA bookkeeping) is now fully CONVERGENT and closed; no G7
    successor was surfaced (the bake-in reaches terminal without any
    STATE_EQ raise). G6 is NOT the closed G5 ``_next_alive``
    priority/active axis and NOT the closed G4 I20 mana axis; it was
    the distinct Rust-driver SBA-timing port gap, now closed
    (docs/SEARCH_LIMITATIONS.md / SOT_FLIP_CUTOVER_PLAN ledger). The
    negative-control tests below still prove the STATE_EQ tripwire
    fires loudly on a genuine injected divergence — the closure did
    NOT weaken it (feedback_no_fallback_hybrids /
    feedback_silent_noop_pipelines)."""
    adapter = _shadow()
    rng = random.Random(2026)
    steps = 0
    raised: ShadowDivergenceError | None = None
    # Drive the SAME degenerate both-decked-out tail all the way to
    # terminal (the old G6 trip point was step ~151; the run now
    # completes clean a step or two later when the second player also
    # decks out). 4000 is the same generous cap the surfaced-pin used.
    while not adapter.is_terminal() and steps < 4000:
        try:
            legal = adapter.legal_decisions()
        except ShadowDivergenceError as e:
            raised = e
            break
        choice = rng.choice(legal)
        try:
            adapter.apply(choice)
        except ShadowDivergenceError as e:
            raised = e
            break
        steps += 1
    assert raised is None, (
        f"G6 (the post-deck-out Rust-driver is_over/winner_id "
        f"SBA-timing port gap) must be CLOSED by the "
        f"_run_step_enter_sbas cadence port — the bake-in must run "
        f"divergence-clean through the entire post-deck-out tail to "
        f"terminal (it tripped at step ~151 pre-closure on "
        f"is_over/winner_id). Got a divergence at step {steps}: "
        f"[{raised.tripwire}] {raised}"
        if raised is not None else ""
    )
    # The clean run must actually have reached the terminal state
    # (guard against a premature non-terminal break masking the
    # result) AND have run past the old step-~151 G6 trip point.
    assert adapter.is_terminal(), (
        f"expected the bake-in to reach the natural terminal state "
        f"after closing G6; stopped non-terminal at step {steps}"
    )
    assert steps >= 151, (
        f"expected to run at least to the old step-~151 G6 trip "
        f"point before terminal; only reached step {steps}"
    )


def test_shadow_clone_independent():
    adapter = _shadow()
    adapter.legal_decisions()
    clone = adapter.clone()
    assert isinstance(clone, GameStateProtocol)
    # Mutating the clone must not raise on the original's next step.
    clone.apply(PassPriority())
    assert not adapter.is_terminal()


# ---------------------------------------------------------------------------
# negative control — the tripwire FIRES loudly (not a silent no-op)
# ---------------------------------------------------------------------------


def test_legal_set_eq_fires_on_injected_divergence():
    """Inject a divergent Rust legal set; LEGAL_SET_EQ must raise
    ShadowDivergenceError tagged LEGAL_SET_EQ — proving the assertion
    is real (compares the Rust set vs Python's RULES-legal set), not
    a silent pass."""
    adapter = _shadow()

    # Poison the Rust driver to emit an EXTRA decision the Python
    # RULES-legal set (raw legal_actions) never would (a phantom
    # PlayLand). LEGAL_SET_EQ compares the Rust set against Python's
    # legal_actions reference, so this is reference-independent.
    real_rust_legal = adapter._rust.legal_decisions

    def _poisoned():
        return list(real_rust_legal()) + [PlayLand(card_id=999_999)]

    adapter._rust.legal_decisions = _poisoned
    with pytest.raises(ShadowDivergenceError) as ei:
        adapter.legal_decisions()
    assert ei.value.tripwire == "LEGAL_SET_EQ"


def test_no_raise_fires_on_python_apply_raise():
    """If the Python apply_action raises (the documented C1 failure
    mode), it must surface as the NO_RAISE tripwire, not a bare
    exception — proving NO_RAISE is wired."""
    adapter = _shadow()
    legal = adapter.legal_decisions()
    choice = next(
        (d for d in legal if isinstance(d, PassPriority)), legal[0]
    )

    def _boom(_d):
        raise RuntimeError("simulated Python apply invariant violation")

    adapter._py.apply = _boom
    with pytest.raises(ShadowDivergenceError) as ei:
        adapter.apply(choice)
    assert ei.value.tripwire == "NO_RAISE"


def test_state_eq_fires_on_divergent_post_state():
    """Force a post-apply field divergence (mutate only the Rust
    side); STATE_EQ must raise."""
    adapter = _shadow()
    legal = adapter.legal_decisions()
    choice = next(
        (d for d in legal if isinstance(d, PassPriority)), legal[0]
    )
    # Apply the choice ONLY to the Rust driver, skipping the Python
    # checker, so the two states diverge — then the next _assert_
    # state_eq (via a normal apply) must catch it. Simpler: directly
    # desync by applying to rust only, then call _assert_state_eq.
    adapter._rust.apply(choice)
    with pytest.raises(ShadowDivergenceError) as ei:
        adapter._assert_state_eq()
    assert ei.value.tripwire == "STATE_EQ"


# ---------------------------------------------------------------------------
# factory wiring — rust_shadow reachable, python default untouched
# ---------------------------------------------------------------------------


def test_factory_python_default_still_unchanged():
    """The B3-S4 changes must not perturb the parity-safe default:
    decision_source='python' still returns the unchanged
    MtgGameStateAdapter."""
    from mtg_bot.agents import RandomAgent
    from mtg_bot.search.engine_adapter import MtgGameStateAdapter
    from mtg_bot.search.engine_adapter_factory import (
        make_game_state_adapter,
    )
    from mtg_bot.search.heuristics_config import HeuristicsConfig
    from mtg_bot.simulate import setup_game

    eng = setup_game(
        [RandomAgent(rng=random.Random(1)),
         RandomAgent(rng=random.Random(2))],
        decks=[["Forest"] * 8, ["Forest"] * 8],
        seed=3,
    )
    a = make_game_state_adapter(eng, heuristics=HeuristicsConfig())
    assert type(a) is MtgGameStateAdapter


def test_factory_rust_shadow_at_python_site_raises():
    """rust_shadow at a Python-engine construction site still raises
    loudly (no silent fallback); the bake-in is built from a spec via
    build_shadow_checked_adapter, NOT a pre-built Python engine."""
    from mtg_bot.agents import RandomAgent
    from mtg_bot.search.engine_adapter_factory import (
        make_game_state_adapter,
    )
    from mtg_bot.search.heuristics_config import HeuristicsConfig
    from mtg_bot.simulate import setup_game

    eng = setup_game(
        [RandomAgent(rng=random.Random(1)),
         RandomAgent(rng=random.Random(2))],
        decks=[["Forest"] * 8, ["Forest"] * 8],
        seed=3,
    )
    with pytest.raises(NotImplementedError):
        make_game_state_adapter(
            eng,
            heuristics=HeuristicsConfig(decision_source="rust_shadow"),
        )
