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


def test_g7_classc_warpexile_delayed_trigger_root_cause_closed_then_next_frontier_surfaced():
    """**G7 S6-Class-C delayed-trigger port CLOSED — next frontier
    SURFACED (the Class-B priority-port lane).**

    The S6 scale-verify evidence
    (``docs/G7_S6_SCALE_VERIFY_EVIDENCE.md`` + ``s6_scale_verify.json``)
    labelled Class C (44/300) *"warp-EMISSION/S4b — warp creatures
    resolve atomically in Rust vs on-stack in Python; the S1/S5a
    treatment never applied to the warp cast path"*. **Cycle-36
    (``feature/g7-classc-warp-onstack``) verify-first against ``main``
    @ ``3a963e0f`` CONTRADICTED that premise** — the warp CAST is on-
    stack on both engines (S4 + S5a already landed) — and re-
    characterized the real Class-C root cause as the warp-EXILE
    **delayed-trigger-vs-deterministic-sweep** divergence (filed todo
    ``8d353e80``). **This pin's previous contract** asserted the
    Class-C divergence surfaces in arch1/s1 at the end step (step 169,
    Starbreach Whale obj 81: Python has the warp creature on the
    battlefield + ``WarpExileSelf`` trigger on the stack; Rust has
    the creature in exile_pX, stack empty). **This contract IS NOW
    FLIPPED to the closed-axis pattern** because the delayed-trigger
    port (this round, ``feature/g7-classc-warp-delayed-trigger``)
    has landed:

    1. **CLOSURE — the warp-EXILE delayed-trigger axis is fixed in
       Rust.** ``cast_creature_warp`` (``rust/src/state_ops_cast.rs``)
       schedules a ``DelayedTrigger { fire_at_turn, controller_id,
       source_id, effect: WarpExileSelf }`` onto the new
       ``state.delayed_triggers`` Vec (``rust/src/state.rs``) at
       cast time — mirroring Python's ``actions.py:1550-1559``. At
       PHASE_END_STEP entry, the new
       ``state_ops_steps.rs::run_delayed_end_step_triggers``
       **replaces** the round-63 deterministic
       ``warp_exile_sweep_on_end_step`` and pushes matching entries
       as real ``StackItem::TriggeredAbility`` slots via
       ``push_triggered_ability``. The new
       ``Effect::WarpExileSelf`` resolver arm
       (``state_ops_resolve.rs``) does the bf→owner-exile move with
       the CR-400.7 reset + ``warped=true`` stamp on non-tokens.
       Result: at the former divergence step (arch1/s1 step 169 /
       arch4/s0 step 192), Rust keeps the warp creature on the
       battlefield with the ``WarpExileSelf`` trigger on the stack
       — byte-equal Python (the on-stack response window of CR
       603.7 is faithfully modelled).

    2. **NEXT FRONTIER SURFACED — the Class-B priority-port lane.**
       With the warp-EXILE axis closed, the canonical Class-C repros
       run **MANY steps PAST the former trip step** and then trip on
       a different, named, distinct divergence — the
       ``priority_player`` STATE_EQ at a ``DECLARE_ATTACKERS``
       window (arch1/s1: trip at ~step 351 / arch4/s0: ~322 — both
       well past the former 169/192). This is the exact shape of the
       S6 evidence's dominant Class-B 138/300 lane (re-characterized
       cycle 35 as a Rust-engine slice in
       ``state_ops_actions.rs:1444-1446`` /
       ``state_ops_legal.rs:1199`` carried-priority gap vs the
       ``simulate.py`` SoT; owned by the
       ``feature/g7-classb-engine`` sibling lane).

    3. **What the assertions guard.** This pin locks BOTH the
       closure AND the next-frontier-surfaced shape so a future
       regression cannot silently pass:

       * The warp creature must still appear on BOTH stacks at cast
         (no atomic-resolve regression).
       * The run MUST still trip somewhere (Class B is open).
       * The surfaced shape must NOT name the warp creature, the
         exile_pX zone, or the ``WarpExileSelf``-on-stack-3-field
         pattern (no regression to the deterministic-sweep shape).
       * The surfaced divergence must be the ``priority_player``
         next-frontier (a sanity check that the next-unmasked axis
         is the known Class-B lane, not some unexpected new shape).

    If the Class-B sibling lane closes the priority-port axis, this
    pin's next-frontier assertion will fire; update it to the
    *new* next-frontier (full closure → terminal-clean would be the
    happy ending — at which point this pin's ``raised`` assertion
    flips to ``raised is None``)."""
    pytest.importorskip("mtg_bot_engine")
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        build_python_field_view, compare_fields, parity_smoke,
    )
    from mtg_bot.search.rust_shadow import (
        build_shadow_checked_adapter as _bsca,
    )

    # The canonical Class-C repro the S6 evidence cites: arch1/s1,
    # Starbreach Whale (Warp {1}{U}), obj 81, former divergence step
    # 169 — closed (the run now reaches step ~351 before the Class-B
    # priority-port next-frontier surfaces).
    deck = trajectory.load_production_deck(archetype=1)
    spec = trajectory.production_deck_to_deckspec(deck, shared_rng_seed=1)
    adapter = _bsca(spec)
    py_a, rust_a = adapter.py_adapter, adapter.rust_adapter
    ps = parity_smoke()

    rng = random.Random(1)
    steps = 0
    raised: ShadowDivergenceError | None = None
    cast_seen_on_stack_both = False
    warp_exile_window_passed = False
    while not adapter.is_terminal() and steps < 4000:
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
        # Window proof (point 1 — closure proof): right after the
        # warp cast the creature is on the stack on BOTH engines.
        # The warp-EXILE axis is closed when the run progresses PAST
        # the former trip step (~169 for arch1/s1) without the
        # creature-in-exile_pX-vs-bf signature.
        if not cast_seen_on_stack_both:
            pv = build_python_field_view(py_a.engine_state)
            rv = ps._build_field_view(rust_a.rust_state)
            in_stack = lambda v: any(  # noqa: E731
                isinstance(t, (list, tuple)) and t and t[-1] == 81
                for t in (v or ())
            )
            if in_stack(pv.get("stack")) and in_stack(rv.get("stack")):
                cast_seen_on_stack_both = True
        # Closure progress proof: any progress beyond step 200 means
        # we have crossed the former arch1/s1 step-169 warp-EXILE
        # divergence boundary on a run that did NOT trip there.
        if steps >= 200 and not warp_exile_window_passed:
            warp_exile_window_passed = True
        steps += 1

    # (1) The warp creature WAS on the stack on BOTH engines —
    # cast_creature_warp is NOT atomic (S4 / S5a are still in
    # force; no regression).
    assert cast_seen_on_stack_both, (
        "REGRESSION GUARD: the warp creature (obj 81) must still "
        "appear on the stack on BOTH engines after the warp "
        "CastSpell — proving cast_creature_warp is NOT atomic "
        "(S4+S5a). If this no longer holds, the warp cast path "
        "regressed to atomic."
    )

    # (2) CLOSURE PROOF: the run progressed past the former
    # warp-EXILE trip step (~169 for arch1/s1). If it didn't, the
    # warp-exile delayed-trigger port has regressed.
    assert warp_exile_window_passed, (
        f"CLOSURE GUARD: arch1/s1 must run past step 200 to prove "
        f"the warp-EXILE delayed-trigger axis closed (former trip at "
        f"~step 169). Tripped/halted at step {steps} instead — the "
        f"delayed-trigger port has regressed. last raised: "
        f"{str(raised)[:300] if raised else None!r}"
    )

    # (3) NEXT-FRONTIER SURFACED: the run must STILL trip somewhere
    # past the warp-EXILE closure window. Silent pass would mean
    # another axis got masked.
    #
    # RE-CHARACTERIZED at merge-time (cycle-37 serial-merge pipeline,
    # post-Class-B + Class-C lanes both landed): the original
    # contract here expected the next-frontier to be the Class-B
    # priority-port lane (``priority_player`` STATE_EQ at a
    # DECLARE_ATTACKERS window). Class-B has ALSO landed in main
    # (cycle-37 merge #2), so the priority-port axis is CLOSED too,
    # and the bake-in now runs PAST what would have been the Class-B
    # trip and surfaces a NEW life-total STATE_EQ at step ~356:
    # ``('life_p0', 17, 20)`` — a 3-life delta that ONLY shows up
    # when BOTH the warp-EXILE closure (this lane) AND the
    # priority-port closure stack (the random walk reaches a new
    # code path that neither lane alone reveals). This is a genuine
    # cross-lane surfaced axis, NOT a regression of either lane's
    # closure contract: the warp-creature-on-stack window proof (1)
    # and the past-step-200 closure-progress proof (2) both hold.
    assert raised is not None, (
        "NEXT-FRONTIER GUARD: the cross-lane life-total axis is OPEN "
        "(surfaced at merge-time, post-Class-B+Class-C closures) so "
        "the run MUST still trip somewhere downstream of the "
        "warp-exile closure. A clean to-terminal run on arch1/s1 "
        "would mean the surfaced life-total axis was closed elsewhere "
        "(re-characterize this pin to the new next-frontier) OR an "
        "axis was silently masked (bad — the S6 discipline forbids "
        "it)."
    )
    assert raised.tripwire == "STATE_EQ", (
        f"expected the merge-surfaced life-total STATE_EQ "
        f"next-frontier shape, got {raised.tripwire}: "
        f"{str(raised)[:300]!r}"
    )
    msg = str(raised)

    # (4) The surfaced divergence is the merge-time life-total axis
    # (cycle-37 serial-merge-pipeline cross-lane surface). Pin its
    # known shape so a future regression can't drift to a different
    # unexpected axis.
    assert "life_p0" in msg, (
        f"NEXT-FRONTIER SHAPE GUARD: the surfaced divergence must "
        f"be the merge-time cross-lane life-total axis "
        f"('life_p0' STATE_EQ). Got: {msg[:400]!r}"
    )

    # (5) REGRESSION GUARDS — the surfaced shape must NOT be the
    # warp-EXILE deterministic-sweep pattern.
    assert "Starbreach Whale" not in msg, (
        f"REGRESSION GUARD (warp-EXILE closure): the surfaced "
        f"divergence must NOT name the warp creature — the "
        f"warp-EXILE axis is closed. Got: {msg[:400]!r}"
    )
    pv = build_python_field_view(py_a.engine_state)
    rv = ps._build_field_view(rust_a.rust_state)
    divs = {d.field: (d.py_value, d.rust_value)
            for d in compare_fields(pv, rv)}
    # Concrete shape guard: the surfaced divergence must NOT contain
    # an exile_pX / battlefield / stack pattern with obj 81 (the
    # pre-port warp-EXILE signature).
    has_whale_on_python_bf_only = (
        "battlefield" in divs
        and any(t and t[-1] == 81 for t in divs["battlefield"][0])
        and not any(t and t[-1] == 81 for t in divs["battlefield"][1])
    )
    has_rust_exile_whale = (
        "exile_p1" in divs
        and any(t and t[-1] == 81 for t in (divs["exile_p1"][1] or ()))
    )
    assert not (has_whale_on_python_bf_only and has_rust_exile_whale), (
        f"REGRESSION GUARD (warp-EXILE closure): the surfaced shape "
        f"must NOT be the pre-port deterministic-sweep signature "
        f"(Python: Whale on bf + trigger on stack; Rust: Whale in "
        f"exile_p1). Got divs={divs!r}"
    )
    # Closed-axis regression guard: the hand_p0 axis (the pre-S4
    # closed atomic-cast hand-side residue axis) must NOT appear.
    assert "hand_p0" not in msg, (
        f"REGRESSION GUARD (S4 closed-axis): the CLOSED non-warp "
        f"atomic-cast hand_p0 axis must NOT appear. Got: "
        f"{msg[:400]!r}"
    )
    # Closed-axis regression guard: the priority_player axis (the
    # cycle-37 Class-B closure) must NOT reappear as the surfaced
    # field — if it does, the Class-B closure regressed.
    assert "priority_player" not in divs, (
        f"REGRESSION GUARD (Class-B priority-port closure): "
        f"priority_player must NOT appear in the compare_fields "
        f"divergence set (it is CLOSED post-cycle-37 merge #2). "
        f"Got divs.keys()={list(divs.keys())}"
    )
    # (6) life_p0 is the diverging field — pin the specific
    # closed-vs-next-frontier shape.
    assert "life_p0" in divs, (
        f"NEXT-FRONTIER FIELD GUARD: life_p0 must be in the "
        f"compare_fields divergence set. Got divs.keys()={list(divs.keys())}"
    )


def test_g7_classe_mana_generic_pool_drain_order_root_cause_pinned():
    """**G7 S6-Class-E verify-first root-cause pin (HONEST-STOP).**

    The S6 scale-verify evidence
    (``docs/G7_S6_SCALE_VERIFY_EVIDENCE.md`` + ``s6_scale_verify.json``)
    labelled Class E (31/300) *"C1-family mana-source COLOR on
    ``ActivateAbility`` — Rust taps a different-colored mana SOURCE
    than Python (the auto-tap land/source pick order diverges)"*.
    **Verify-first against live ``main`` @ ``430f3b39`` REFINES that
    framing** and this pin locks the REAL, empirically-verified root
    cause so a future fix lane cannot regress to the (imprecise)
    land-tap-color framing:

    1. **It is NOT a land-tap / colored-pip ordering issue.** The
       colored-pip iteration order (Python ``ManaCost.colored`` =
       ``sorted`` = ``B,G,R,U,W``; ``cards.base.parse_mana_cost:391``)
       and the colored-land tap order ALREADY byte-match Python — that
       was settled by frontier-a (``auto_tap_pay_for_cost``,
       ``state_ops_cast.rs:431-470``). In every Class-E repro the
       diverging ability/spell cost is **PURE GENERIC** (e.g. the
       canonical arch1/s0 repro: ``ActivateAbility(source_id=120,
       ability_index=0)`` — Lander, ``ManaCost(generic=2, colored=())``
       — and the pre-apply pool is ALL floating mana, every land
       already tapped, so NO land is tapped at all).

    2. **The REAL root cause is the GENERIC-cost drain ORDER from the
       floating mana POOL.** Python's ``auto_tap_for_cost``
       (``actions.py:964-976`` — the SoT both ``_cast_spell``
       ``actions.py:1662`` and ``_activate_ability``
       ``actions.py:1992-1995`` pay through) drains the generic cost
       from ``p.mana_pool`` in **list / insertion order**
       (``for idx, coin in enumerate(p.mana_pool)`` — FIFO over the
       coin list, NO color preference). Rust's ``auto_tap_pay_for_cost``
       (``state_ops_cast.rs:472-483``) drains generic in a **fixed
       ``C→W→U→B→R→G`` color priority** (copied from
       ``state_ops_mana.rs::pay_mana_cost:271-295``, the WRONG SoT for
       the cast/activate pay path). On the canonical arch1/s0 repro the
       p1 pool at step 598 is the list ``[G, G, U, U]`` with cost
       ``{2}``: Python consumes the first two list entries (``G, G``) →
       leftover ``U:2``; Rust's fixed order drains ``U`` before ``G`` →
       leftover ``G:2``. SAME cost, SAME total drained (2), DIFFERENT
       colored residual — exactly the ``mana_pool_pX`` STATE_EQ shape.

    3. **Class E is HOMOGENEOUS — 31/31 the same root cause**
       (``scripts/scout_classe_characterize.py`` over the committed
       ``s6_scale_verify.json``): every Class-E STATE_EQ is this
       ``auto_tap_for_cost`` generic-pool-drain-order divergence (mix
       of ``ActivateAbility`` and ``CastSpell`` last-actions — both pay
       through the IDENTICAL ``auto_tap_for_cost``; ONE root cause, not
       a heterogeneous set).

    4. **The faithful fix is OUT OF THIS LANE'S SCOPE (honest-stop,
       per the brief — ``>1 safe slice`` and outside the authorized
       ``state_ops_cast.rs``/``state_ops_mana.rs`` files).** Byte-
       mirroring Python's pool-LIST-order generic drain requires Rust
       to know the pool coin **insertion order**. Rust's ``ManaPool``
       (``state.rs:509``) is a per-color **count** struct
       (``white/blue/black/red/green/colorless: u8``) — it discards
       insertion order at ``add_mana`` time
       (``state_ops_mana.rs:117-127``: ``*slot = slot.saturating_add``).
       The pre-pool dumps are genuinely interleaved
       (``[W,W,G,W,U,W,G]``, ``[R,G,G,G,G,G,G,R,G,G,G]``) and
       provably **NOT reconstructable from per-color counts** — a
       count-only heuristic (e.g. "drain G last") would be a
       ``feedback_no_fallback_hybrids`` fallback that gets the
       interleaved cases wrong. The only faithful fix is an
       **ordered-pool representation** in ``state.rs::ManaPool`` +
       every add/drain/clone/fingerprint/snapshot/decisions site
       updated (**186 per-color pool-field references across 9
       ``rust/src`` files**, INCLUDING ``cards.rs`` which fires the
       cron structural arm and is off-limits this lane). That is a
       multi-file engine-representation refactor — materially more
       than one safe slice. Filed as the genuine-fix follow-up todo;
       this lane ships ZERO engine diff (manufacturing a partial
       count-only diff would be a fabricated no-op /
       ``feedback_no_fallback_hybrids``).

    If a future lane lands the ordered-pool representation and closes
    Class E, the ``raised is not None`` / signature assertions flip
    and this pin must be updated to the closed contract
    (new-code-is-right) — it must NEVER silently pass (that would be
    exactly the masking S6 exists to rule out)."""
    pytest.importorskip("mtg_bot_engine")
    from mtg_bot.game import effective_activated_abilities
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        build_python_field_view, compare_fields, parity_smoke,
    )
    from mtg_bot.search.rust_shadow import (
        build_shadow_checked_adapter as _bsca,
    )

    # The canonical Class-E repro the S6 evidence cites: arch1/s0,
    # ActivateAbility(source_id=120) (Lander, {2} generic),
    # divergence step 598, Python U:2 vs Rust G:2.
    deck = trajectory.load_production_deck(archetype=1)
    spec = trajectory.production_deck_to_deckspec(deck, shared_rng_seed=0)
    adapter = _bsca(spec)
    py_a, rust_a = adapter.py_adapter, adapter.rust_adapter
    ps = parity_smoke()

    rng = random.Random(0)
    steps = 0
    raised: ShadowDivergenceError | None = None
    last_choice = None
    pre_pool_list: list[str] | None = None
    cost_was_pure_generic = False
    while not adapter.is_terminal() and steps < 4000:
        try:
            legal = adapter.legal_decisions()
        except ShadowDivergenceError as e:
            raised = e
            break
        if not legal:
            break
        choice = rng.choice(legal)
        # Snapshot the pre-apply Python pool LIST + the cost shape of
        # the about-to-apply mana-spending decision (the root-cause
        # evidence: a PURE-GENERIC cost + a multi-color pool list).
        if type(choice).__name__ == "ActivateAbility":
            st = py_a.engine_state
            src = next((o for o in st.battlefield
                        if o.id == choice.source_id), None)
            if src is not None:
                abs_ = effective_activated_abilities(st, src)
                if 0 <= choice.ability_index < len(abs_):
                    mc = abs_[choice.ability_index].cost.mana
                    cost_was_pure_generic = (
                        mc is not None and mc.generic > 0
                        and not mc.colored and not mc.hybrid
                    )
            p1 = next(pp for pp in st.players if pp.id == 1)
            pre_pool_list = [c.color for c in p1.mana_pool]
        last_choice = choice
        try:
            adapter.apply(choice)
        except ShadowDivergenceError as e:
            raised = e
            break
        steps += 1

    # (1) The bake-in trips LOUDLY at the characterized boundary —
    # not masked, not silently passing.
    assert raised is not None, (
        "the Class-E generic-pool-drain-order divergence must still "
        "SURFACE on arch1/s0. If it no longer fires, the axis was "
        "closed elsewhere (the ordered-pool representation landed) — "
        "UPDATE this pin to the closed contract; do NOT let it "
        "silently pass (that would be exactly the masking S6 exists "
        "to rule out)."
    )
    assert steps == 598, (
        f"arch1/s0: expected the characterized Class-E boundary step "
        f"598, got {steps}. A different step means the frontier MOVED "
        f"(an axis closed/opened elsewhere) — re-characterize, do NOT "
        f"silently bump. err={str(raised)[:200]!r}"
    )
    assert raised.tripwire == "STATE_EQ", (
        f"expected the Class-E mana-pool STATE_EQ shape, got "
        f"{raised.tripwire}: {str(raised)[:300]!r}"
    )
    msg = str(raised)
    # (2) The exact verified signature: a mana_pool_p1 divergence
    # where the two engines disagree only on the COLOR of the
    # residual (same total), NOT on hand/battlefield/stack.
    assert "mana_pool_p1" in msg, (
        f"the surfaced divergence must be the p1 mana-pool color "
        f"residual. Got: {msg[:400]!r}"
    )
    assert "hand_p0" not in msg and "blocker" not in msg, (
        "REGRESSION GUARD: the CLOSED non-warp atomic-cast hand_p0 / "
        f"combat-blocker axes must NOT appear in the Class-E shape. "
        f"Got: {msg[:300]!r}"
    )
    # (3) Root-cause proof: the decision that tripped is a PURE-GENERIC
    # cost (so it is NOT a colored-pip / land-tap-color issue — frontier
    # -a settled those), and the pre-apply Python pool was a multi-color
    # LIST whose insertion order is what Python's generic drain honors.
    assert type(last_choice).__name__ == "ActivateAbility", (
        f"the canonical arch1/s0 Class-E trip is on an ActivateAbility "
        f"(Lander {{2}}). Got {last_choice!r} — re-characterize."
    )
    assert cost_was_pure_generic, (
        "ROOT-CAUSE PROOF: the diverging decision's cost must be PURE "
        "GENERIC (no colored / hybrid pips) — Class E is the "
        "generic-from-POOL drain-order divergence, NOT a colored-pip "
        "or land-tap-color issue (frontier-a already byte-matched "
        "those). If this fails the repro is no longer the "
        "characterized root cause."
    )
    assert pre_pool_list is not None and len(set(pre_pool_list)) >= 2, (
        f"ROOT-CAUSE PROOF: the pre-apply p1 pool must be a "
        f"MULTI-COLOR list (Python drains it in insertion/list order; "
        f"Rust drains a fixed C→W→U→B→R→G order — the divergence only "
        f"manifests when >1 color is present). Got {pre_pool_list!r}."
    )
    # (4) The residual disagreement is COLOR-only at equal total — the
    # signature of a same-cost different-color drain (NOT an
    # affordability/count issue, which is the closed Class A).
    pv = build_python_field_view(py_a.engine_state)
    rv = ps._build_field_view(rust_a.rust_state)
    divs = {d.field: (d.py_value, d.rust_value)
            for d in compare_fields(pv, rv)}
    assert "mana_pool_p1" in divs, (
        f"expected a mana_pool_p1 compare_fields divergence, got "
        f"fields={sorted(divs)!r}"
    )
    py_pool, rust_pool = divs["mana_pool_p1"]
    py_total = sum(n for _, n in py_pool)
    rust_total = sum(n for _, n in rust_pool)
    assert py_total == rust_total and py_pool != rust_pool, (
        f"ROOT-CAUSE PROOF: Class E is SAME total ({py_total} vs "
        f"{rust_total}) but DIFFERENT colored residual "
        f"(py={py_pool!r} rust={rust_pool!r}). An unequal total would "
        f"be an affordability/count issue (the closed Class A), not "
        f"the generic-drain-ORDER root cause."
    )


def test_g7_activateability_affordability_closed_then_next_frontier_surfaced():
    """**G7 ActivateAbility-affordability closure-flip** (was
    ``test_g7_combat_blocker_legalset_closed_then_next_frontier_surfaced``
    → was ``test_g7_s5a_spellstack_zone_closed_then_blocker_legalset_surfaced``;
    todo ``04d67d99`` / ``fec5f14``-successor).

    **PRIOR FRONTIER (a) — CLOSED by the ``ActivateAbility`` apply
    auto-tap fix (engine, new-code-is-right toward the Python SoT).**
    The combat-blocker closure honest-stop pinned, for arch2/s1, a
    post-combat-blocker RAW ``ValueError`` at step **318**: Rust's
    ``legal_decisions`` offered ``ActivateAbility(source_id=121,
    ability_index=0)`` (the ``{2}`` Lander sac-search ability — emitted
    on pool **+ auto-tap headroom**, ``state_ops_legal.rs:2105`` →
    ``auto_tap_headroom_pool``, the ``can_pay_cost`` shape byte-equal to
    Python's ``legal.py:653`` activated-ability predicate) but Rust's
    own ``apply_action`` paid the cost **STRICTLY from the floating
    pool** (``state_ops_actions.rs`` Phase 4 → ``pay_mana_cost_pub``,
    no auto-tap) and raw-rejected it (pool ``{U:1}`` could not cover
    ``{2}`` though 2 untapped Forests could): *"ActivateAbility: source
    121 cost is unaffordable from controller's mana pool"*. A
    **Rust-internal legal-emit-vs-apply self-inconsistency** — the
    **§2-4 analog for ``ActivateAbility``**: Python's
    ``_activate_ability`` (``actions.py:1992-1995``) pays the ability
    mana via the IDENTICAL ``auto_tap_for_cost`` call ``_cast_spell``
    makes (``actions.py:1662``), i.e. Python's apply auto-taps lands.
    **The fix routes the Rust ``ActivateAbility`` apply mana-pay through
    the SAME ``state_ops_cast::auto_tap_pay_for_cost`` helper the three
    §2-4 cast pay sites use** (the lands-only, plan-then-commit
    byte-mirror of Python's ``auto_tap_for_cost``; promoted
    ``pub(crate)``). Apply now honors what legal offered, exactly as
    Python's ``_activate_ability`` does. The arch2/s1 RAW ``ValueError``
    NO LONGER fires at 318: the run proceeds PAST it. **arch5/s0 is
    UNAFFECTED** by this fix (its 367 frontier (b) is not an
    ActivateAbility-affordability axis); its prior closed axis stays the
    combat-blocker ``LEGAL_SET_EQ`` @344.

    **NEXT DISTINCT DIVERGENCE SURFACED (honest-stop — SEPARATE,
    pre-existing, surfaced — NOT introduced — by closing frontier (a);
    per-repro, NOT this lane's scope).** With (a) closed the arch2/s1
    bake-in runs further and trips a DIFFERENT divergence; arch5/s0's
    frontier (b) is held intact (distinct, STILL-OPEN follow-up):

    * **arch2/s1 — step 320:** a ``ShadowDivergenceError`` tripwire
      ``STATE_EQ`` on ``('library_p1', ...)`` — a **library-ORDERING
      divergence**. With ``ActivateAbility(121,0)`` (the Lander
      "Search your library for a basic land card ... then **shuffle**"
      ability) now applying byte-equal on both engines, the post-search
      **shuffle produces a DIFFERENT library order** in Rust vs Python
      (identical 50-card multiset, divergent order; the per-engine
      shuffle RNG is not lockstep). The step-320 boundary + the
      ``STATE_EQ``/``library_p1`` shape are deterministic across runs;
      only the library *content order* varies run-to-run (that variance
      IS the divergence). A NEW G7 frontier (search-then-shuffle
      library-order parity) — distinct from (a) (closed) and from (b).

    * **arch5/s0 — step 367 → CLOSED; new frontier @369:** frontier
      (b) = S6 Class B (the dominant 138/300
      ``STATE_EQ ('priority_player', 1, 0)`` @367) is now **CLOSED**
      by the coordinated G7 S6 Class-B **option-β engine+adapter
      slice** (``state_ops_legal.rs`` option-β: relocate the
      factored-combat DECLARE_ATTACKERS/DECLARE_BLOCKERS emission
      above the line-1199 priority gate, keyed on the structural
      decision-maker, the relocated ``is_priority_holder`` early
      return fencing only the genuine priority-window emission; +
      the coordinated ``rust_engine_adapter.py`` half: defer
      ``_reset_priority_to_active`` for factored-combat steps so
      Rust's ``priority_player`` stays CARRIED like the
      ``simulate.py`` SoT, make ``active_player()`` /
      ``legal_decisions()`` resolve the combat decision-maker
      (active/structural-defender) instead of the carried priority,
      and strip the structural ``PassPriority`` from the
      factored-combat set to byte-mirror Python's adapter combat
      emission). Step 367 no longer trips (nor the step-368
      combat-window ``('pass',)`` follow-on the engine half alone
      would have surfaced). The run proceeds PAST to a NEW distinct
      frontier @369: a ``LEGAL_SET_EQ`` tripwire —
      ``py\rust=["('pass',)"]`` while Rust still emits the factored
      ``attacker_decision`` pair for the lone declined attacker. This
      is the **pre-existing G1 stateless-Rust ``attack=False``
      re-emission gap** (Rust's ``apply_action(AttackerDecision,
      attack=false)`` is a deliberate no-op and the
      ``RustGameStateAdapter`` does not port Python's provider-side
      ``_pending_attackers.pop(0)`` + ``_finalize_attacker_phase``
      accumulation — the B3-S3 sibling slice the G1 design defers),
      unmasked — NOT introduced — by closing 367 (zero provider
      accumulation at ``dc22ebc4``; arch5/s0 simply never reached a
      factored-attacker ``attack=False`` before, blocked at 344/367).
      Honest count: the coordinated fix closes the Class-B
      ``priority_player`` axis broadly (a representative
      arch5/s0-family Class-B re-sweep: 25/25 first-25 CLOSED_PAST,
      0 STILL_PRIORITY, 0 REGRESSED; full 138 re-characterized in
      the report). DISTINCT, pre-existing axis filed as the next G7
      follow-up (G1 provider-accumulation / B3-S3 port).

    Both are DISTINCT, pre-existing axes filed as the next G7
    follow-up in ``SOT_FLIP_CUTOVER_PLAN.md`` §4 +
    ``SEARCH_LIMITATIONS.md``. Per the established
    G4/G5/G6/S5a surfaced→closure-flip discipline this pin asserts
    BOTH: (1) the prior per-repro axis is CLOSED (each run goes PAST
    its old boundary — arch2/s1 PAST the (a) step-318
    ActivateAbility-affordability boundary; arch5/s0 PAST the
    combat-blocker 344 — and the surfaced msg is NOT the old
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
    #   old_boundary  — the per-repro CLOSED axis step (a trip
    #                    at/before this == the fix regressed). For
    #                    arch2/s1 this is the frontier-(a)
    #                    ActivateAbility-affordability step 318 the
    #                    auto_tap_pay_for_cost reroute just closed; for
    #                    arch5/s0 it is the (unchanged) combat-blocker
    #                    LEGAL_SET_EQ step 344.
    #   exp_step       — the new next-frontier step
    #   kind           — "raw" (uncaught Rust-side ValueError) or
    #                    a ShadowDivergenceError tripwire name
    #   needle         — a substring uniquely characterizing it
    for (arch, seed, old_boundary, exp_step, kind, needle) in (
        # arch2/s1: frontier (a) (ActivateAbility apply pool-only
        # raw-reject @318) CLOSED → next = a STATE_EQ library-ORDER
        # divergence @320 (post-Lander-search shuffle order parity;
        # the step + tripwire + field are deterministic, only the
        # library content order varies run-to-run = the divergence).
        (2, 1, 318, 320, "STATE_EQ", "('library_p1'"),
        # arch5/s0: frontier (b) = S6 Class B (the dominant 138/300
        # ``('priority_player', 1, 0)`` STATE_EQ @367) CLOSED by the
        # coordinated G7 S6 Class-B option-β engine+adapter slice
        # (``state_ops_legal.rs`` option-β + the
        # ``rust_engine_adapter.py`` deferred-priority-reset /
        # combat-decision-maker ``active_player()`` /
        # decision-maker ``legal_decisions()`` query /
        # factored-combat ``PassPriority`` strip). The carried-priority-
        # through-factored-combat axis now byte-mirrors the
        # ``simulate.py`` SoT; step 367 no longer trips (nor the
        # step-368 combat-window ``('pass',)`` follow-on the engine
        # half alone would have surfaced). The run proceeds PAST to a
        # NEW distinct frontier @369: ``LEGAL_SET_EQ`` —
        # ``py\rust=["('pass',)"]`` while Rust still emits the
        # factored ``attacker_decision`` pair for the lone declined
        # attacker (obj 12). This is the **pre-existing G1
        # stateless-Rust ``attack=False`` re-emission gap**: Rust's
        # ``apply_action(AttackerDecision, attack=false)`` is a
        # deliberate no-op (the G1 stateless-Rust /
        # stateful-provider split, ``state_ops_legal.rs``
        # ~1283-1294 / ``state_ops_actions.rs:1356-1385``), and the
        # ``RustGameStateAdapter`` does NOT port Python's provider-side
        # ``_apply_attacker_decision`` ``_pending_attackers.pop(0)`` +
        # ``_finalize_attacker_phase`` accumulation
        # (``engine_adapter.py:1080-1108`` — the B3-S3 "sibling slice"
        # the G1 design explicitly defers), so a factored
        # ``attack=False`` on the LAST eligible attacker leaves the
        # creature eligible and Rust re-emits the same head forever
        # while Python finalizes combat and moves to the priority
        # window (``[PassPriority]``). DISTINCT from Class-B's
        # priority axis, pre-existing (zero provider accumulation at
        # ``dc22ebc4``), unmasked — NOT introduced — by closing 367
        # (arch5/s0 never reached a factored-attacker ``attack=False``
        # before; blocked at 344/367). Filed as the next G7 follow-up
        # (the G1 provider-accumulation / B3-S3 port). Boundary +
        # tripwire + the ``py\rust=["('pass',)"]`` signature are
        # deterministic across runs.
        (5, 0, 367, 369, "LEGAL_SET_EQ", "py\\rust=[\"('pass',)\"]"),
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

        # (1) PRIOR PER-REPRO AXIS CLOSED: the run proceeds PAST its
        # old boundary. arch2/s1: PAST step 318 — the frontier-(a)
        # ActivateAbility apply pool-only raw-reject, closed by the
        # auto_tap_pay_for_cost reroute. arch5/s0: PAST step 367 — the
        # S6 Class-B ``('priority_player', 1, 0)`` STATE_EQ, closed by
        # the coordinated option-β engine+adapter slice. A trip
        # at/before the old boundary means the relevant axis regressed
        # (do NOT bump the boundary — fix the engine).
        assert steps > old_boundary, (
            f"arch{arch}/s{seed}: the prior per-repro axis must be "
            f"CLOSED — the run must proceed PAST its old boundary step "
            f"{old_boundary} (it stopped at {steps}). A stop at/before "
            f"{old_boundary} means the closed axis regressed "
            f"(arch2/s1: the ActivateAbility apply auto-tap; arch5/s0: "
            f"the coordinated Class-B option-β engine+adapter slice) — "
            f"fix the engine, do NOT bump the boundary. "
            f"err={raised!r} raw={raw_exc!r}"
        )
        assert steps == exp_step, (
            f"arch{arch}/s{seed}: expected the freshly-characterized "
            f"next-frontier boundary step {exp_step}, got {steps}. A "
            f"different step means the surfaced frontier moved — "
            f"re-characterize this pin, do NOT just bump."
        )
        # (2) THE NEW DISTINCT PER-REPRO FRONTIER SURFACES LOUDLY. It
        # is NEITHER the closed combat-blocker LEGAL_SET_EQ NOR (for
        # arch2/s1) the closed ActivateAbility-affordability axis.
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


def test_g7_classd_castset_seqwrap_targets_closed_then_next_frontier():
    """**G7 S6-Class-D closure-flip** (the B1-keystone/C1
    ``legal_decisions==legal_actions`` cast-set asymmetry — 23/300 in
    ``docs/G7_S6_SCALE_VERIFY_EVIDENCE.md`` / ``s6_scale_verify.json``;
    todo ``g7-classd-castset``).

    **Verify-first INVERTED the S6-evidence framing.** The S6 evidence
    labelled Class D *"the secondary 22/300 C4 LEGAL_SET_EQ shape; the
    already-OPEN B1 keystone co-blocker (C1
    ``legal_decisions==legal_actions`` mana/target/additional-cost
    asymmetry); NOT a new G-axis — co-evolves, its own B1 lane"*. The
    verify-first characterization is more precise:

    1. **It is NOT a downstream artifact of Class B/C/E and NOT a
       priority/timing re-diagnosis.** Across ALL 23 repros the
       divergence fires at a normal priority window
       (``has_priority(ap)==True``, ``stack==0``, ``combat=None``,
       ``priority_player_idx==active_player_idx``) — priority/timing
       AGREES on both engines. The discriminator is purely the
       per-card cast gate.

    2. **22/23 are a single, genuine, in-scope C1-Slice-2
       (target-satisfiability) bug — the SEQUENCE-RECURSION hole.**
       Every one of the 22 is **Radiant Strike** (id 76 / id 75…)
       ``Sequence(DestroyTargetArtifactOrTappedCreature, GainLife{3})``
       in the queried player's hand: ``can_cast(mana)==True``,
       ``additional_costs_payable==True``, but Python's
       ``_targets_are_satisfiable==False`` (CR 601.2c — zero legal
       targets: no artifact, no tapped creature on the byte-identical
       battlefield). Python's ``legal_actions`` correctly OMITS the
       cast; Rust's ``legal_decisions`` still EMITTED it because
       ``state_ops_legal.rs::spell_targets_satisfiable`` iterated
       ``printing.effects`` matching ONLY top-level ``Effect``
       variants. The bridge's ``sequence`` arm
       (``cross_engine.py:1494``) sends the whole spell body as ONE
       ``{"kind":"sequence",...}`` dict → ``cards.rs parse_effect``
       materializes a SINGLE nested ``Effect::Sequence{effects:[..]}``
       element. The targeted leaf
       ``DestroyTargetArtifactOrTappedCreature`` is a CHILD of that
       Sequence, so the flat loop hit the ``_ => {}`` catch-all on the
       Sequence wrapper and fell through to the conservative ``true``
       — NEVER pruning a zero-target Sequence-wrapped spell. (The
       function's OWN docstring claimed *"matching the targeted
       variant ANYWHERE in the Vec — see the find below"* but no such
       find/recursion existed — the doc described an unimplemented
       contract.) **FIXED** (new-code-is-right toward Python's SoT —
       Python's ``spell_effect`` IS the Sequence whose
       ``requires_target()``/``legal_targets()`` delegate to the
       targeted child): ``spell_targets_satisfiable`` now depth-first
       flattens ``Effect::Sequence`` children before the targeted-leaf
       match. Parity-NEUTRAL by construction (it only ADDS pruning of
       zero-legal-target Sequence-wrapped casts, which Python also
       prunes; the per-leaf scan logic is byte-unchanged — it cannot
       over-prune). All 10 C1 Slice-1/2/3 pins stay GREEN.

    3. **1/23 (arch30/s1 step 111) is a DISTINCT, SEPARATE mana
       sub-axis — NOT closed here (honest-stop, filed).** Thawbringer
       (id 80, ``{2}{G}`` creature, ``spell_effect=None``):
       ``_targets_are_satisfiable==True`` but
       ``_can_cast(mana)==False`` — Python prunes for INSUFFICIENT
       MANA (p1 has 2 untapped lands incl. Stomping Ground for a
       3-mana cost); Rust's ``legal_decisions`` over-emits it. A
       distinct C1-Slice-1 / ``can_pay_cost`` mana-headroom residual
       in a DIFFERENT code path (``state_ops_mana::can_pay_cost`` /
       auto-tap-headroom, NOT the target-satisfiability gate). Filed
       as a separate follow-up todo; the closing of the homogeneous 22
       does not depend on it.

    **NEXT DISTINCT FRONTIER SURFACED (honest-stop — SEPARATE,
    pre-existing, surfaced — NOT introduced — by closing the Sequence
    hole; Class D was UPSTREAM, masking it in the random walk).**
    With the false ``cast_spell 76`` no longer in the legal set the
    arch7/s0 random driver picks differently and the bake-in runs
    PAST step 453 to step 700, where it trips a ``STATE_EQ`` on
    ``('exile_p1', ...)`` (Knight Luminary on Rust's exile_p1, not
    Python's) — the already-tracked **Class C warp-EXILE
    delayed-trigger-vs-deterministic-sweep** axis (todo
    ``8d353e80``), NOT a new G-axis and NOT a regression.

    Per the established G4/G5/G6/S5a/combat-blocker
    surfaced→closure-flip discipline this pin asserts BOTH: (1) the
    Class-D ``cast_spell``/``Sequence``-target axis is CLOSED (the run
    proceeds PAST its old step-453 boundary AND the surfaced msg is
    NOT the old ``('cast_spell', 76, ...)`` LEGAL_SET_EQ
    over-emission), and (2) the next distinct frontier surfaces
    LOUDLY at its freshly-characterized boundary (do NOT silently let
    it pass; if it stops firing the next axis was closed elsewhere —
    re-characterize, do NOT just bump)."""
    pytest.importorskip("mtg_bot_engine")
    from mtg_bot.parity import trajectory
    from mtg_bot.search.engine_adapter_factory import (
        build_shadow_checked_adapter,
    )

    # arch7/s0: Class-D Radiant-Strike Sequence-target axis CLOSED at
    # its old step-453 boundary.
    #
    # RE-CHARACTERIZED at merge-time (cycle-37 serial-merge pipeline):
    # the original pin expected the next-frontier to be the
    # already-tracked Class-C warp-EXILE STATE_EQ @700
    # ('exile_p1', ...) — Knight Luminary on Rust's exile_p1 vs the
    # battlefield on Python. Class-C delayed-trigger port has now
    # ALSO landed in main (cycle-37 merge #3), so the warp-EXILE axis
    # is CLOSED on arch7/s0 too; the bake-in runs PAST step 700 and
    # surfaces at step 757 on the SAME G1 stateless-Rust
    # ``attack=False`` re-emission LEGAL_SET_EQ axis the Class-B
    # canonical arch5/s0 surfaces at step 369:
    # ``LEGAL_SET_EQ rust\py=["('attacker', 120, False)",
    # "('attacker', 120, True)"] py\rust=["('pass',)"]``. The
    # attacker is the same Knight Luminary that was on Rust exile_p1
    # at the old @700 pin (obj id 120), but the new divergence shape
    # is the unrelated G1 attacker-decision axis (B3-S3
    # provider-accumulation port; sibling lane the cycle-37 Class-B
    # row at @369 surfaces).
    arch, seed, old_boundary, exp_step, kind, needle = (
        7, 0, 453, 757, "LEGAL_SET_EQ", "('attacker', 120, False)"
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
    while not adapter.is_terminal() and steps < 4000:
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

    # (1) CLASS-D CAST-SET / SEQUENCE-TARGET AXIS CLOSED: the run
    # proceeds PAST the old step-453 boundary. A trip at/before 453
    # means the Sequence-recursion fix regressed (do NOT bump the
    # boundary — fix the engine).
    assert steps > old_boundary, (
        f"arch{arch}/s{seed}: the Class-D cast-set / Sequence-target "
        f"axis must be CLOSED — the run must proceed PAST its old "
        f"boundary step {old_boundary} (it stopped at {steps}). A stop "
        f"at/before {old_boundary} means the spell_targets_satisfiable "
        f"Sequence-recursion fix regressed — fix the engine, do NOT "
        f"bump the boundary. err={raised!r} raw={raw_exc!r}"
    )
    surfaced_msg = str(raised) if raised is not None else str(raw_exc)
    assert "cast_spell" not in surfaced_msg, (
        f"arch{arch}/s{seed}: the surfaced divergence still mentions a "
        f"cast_spell over-emission — the Class-D LEGAL_SET_EQ "
        f"cast-set asymmetry was NOT actually closed: "
        f"{surfaced_msg[:300]!r}."
    )
    # (2) THE NEXT DISTINCT FRONTIER SURFACES LOUDLY at its
    # freshly-characterized boundary. It is the already-tracked
    # Class-C warp-EXILE STATE_EQ (todo 8d353e80), NOT a new G-axis.
    assert steps == exp_step, (
        f"arch{arch}/s{seed}: expected the freshly-characterized "
        f"next-frontier boundary step {exp_step}, got {steps}. A "
        f"different step means the surfaced frontier moved — "
        f"re-characterize this pin, do NOT just bump. "
        f"err={raised!r} raw={raw_exc!r}"
    )
    assert raised is not None and raw_exc is None, (
        f"arch{arch}/s{seed}: the next distinct divergence must "
        f"SURFACE as a {kind} ShadowDivergenceError. raised={raised!r} "
        f"raw={raw_exc!r}. If it no longer fires it was closed "
        f"elsewhere — re-characterize this pin (do NOT silently pass)."
    )
    assert raised.tripwire == kind, (
        f"arch{arch}/s{seed}: expected tripwire {kind}, got "
        f"{raised.tripwire}: {str(raised)[:300]!r}."
    )
    assert needle in str(raised), (
        f"arch{arch}/s{seed}: the surfaced {kind} must be PRECISELY "
        f"the characterized G1 attacker-decision re-emission "
        f"{needle!r} (cycle-37 cross-lane next-frontier). Got: "
        f"{str(raised)[:300]!r}."
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
