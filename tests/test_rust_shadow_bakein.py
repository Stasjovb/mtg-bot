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
    """**G7 S6-Class-E CLOSURE pin** (was the verify-first
    honest-stop root-cause pin; flipped surfaced→closure when the
    ordered-pool `ManaPool` representation landed).

    The S6 scale-verify evidence
    (``docs/G7_S6_SCALE_VERIFY_EVIDENCE.md`` + ``s6_scale_verify.json``)
    labelled Class E (31/300) *"C1-family mana-source COLOR on
    ``ActivateAbility``"*. Verify-first REFINED that framing: the real
    root cause was the **GENERIC-cost drain ORDER from the floating
    mana POOL**. Python's ``auto_tap_for_cost`` (``actions.py:919-986``,
    the SoT for ``_cast_spell:1662`` and ``_activate_ability:1992-1995``)
    drains by tracking COIN INDICES in ``p.mana_pool`` (a
    ``list[ManaCoin]``) and iterating ``enumerate(p.mana_pool)`` in
    **insertion / FIFO order** for BOTH colored and generic phases.
    Rust's pre-fix ``auto_tap_pay_for_cost`` drained the GENERIC phase
    in a fixed ``C→W→U→B→R→G`` color priority — wrong SoT for the
    cast/activate pay path. On arch1/s0 the p1 pool list at step 598
    is ``[G, G, U, U]`` with cost ``{2}``: Python consumes the first
    two list entries (``G, G``) → residual ``U:2``; Rust's fixed
    order drained ``U`` before ``G`` → residual ``G:2``. SAME cost,
    SAME total drained, DIFFERENT colored residual.

    **THE FIX (this commit):** ``ManaPool`` (``rust/src/state.rs``)
    now carries an insertion-ordered ``coins: Vec<ManaCoin>`` SoT
    alongside the per-color count fields (the counts stay as a
    denormalized cache for O(1) reads — fingerprint, snapshot,
    ``pool_can_cover``, ``get_mana_pool`` are unchanged). Every
    ``add_mana``-shape mutation site (``add_mana``,
    ``tap_for_mana``, ``Effect::AddManaToPool``,
    ``Effect::AddNManaOfChosenColor``) routes through
    ``pool.push_coins(byte, n)`` to keep both sides synced. Every
    drain site (``pay_mana_cost``, ``pay_mana_cost_pub``,
    ``pay_mana_cost_internal``, ``remove_mana``) routes through
    ``pool.drain_first_n_color(byte, n)`` so the ``coins`` vec
    follows the count cache. ``auto_tap_pay_for_cost`` now
    byte-mirrors Python's ``auto_tap_for_cost``: it tracks
    ``used_coin_indices`` in the controller's ``coins`` vec, walks
    the vec in insertion order for both colored matching and
    generic FIFO, and commits by removing the indices high-to-low
    (exactly Python's ``sorted(used_coin_ids, reverse=True)``).

    **CLOSURE CONTRACT (this pin):** the canonical arch1/s0 repro
    no longer trips at step 598 on a ``mana_pool_p1`` STATE_EQ. The
    bake-in proceeds PAST 598, surfacing a DIFFERENT divergence at
    a later step that is **not** the Class-E mana-pool color
    residual — that's the regression guard. The next-frontier pin
    (sibling test below) asserts WHICH new frontier surfaces.

    If a future change regresses Class E, the ``mana_pool_pX``
    color-residual divergence will resurface and trip THIS pin's
    "must not be a mana_pool_pX STATE_EQ" guard. Do NOT relax that
    guard — it's the only protection against silently undoing the
    ordered-pool fix.
    """
    pytest.importorskip("mtg_bot_engine")
    from mtg_bot.parity import trajectory
    from mtg_bot.search.rust_shadow import (
        build_shadow_checked_adapter as _bsca,
    )

    # Same arch1/s0 driver as the original honest-stop pin —
    # production deck #1, shared RNG seed 0, uniform-random
    # rust_shadow bake-in.
    deck = trajectory.load_production_deck(archetype=1)
    spec = trajectory.production_deck_to_deckspec(deck, shared_rng_seed=0)
    adapter = _bsca(spec)

    rng = random.Random(0)
    steps = 0
    raised: ShadowDivergenceError | None = None
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
        steps += 1

    # **CLOSURE assertion (1).** The Class-E boundary step 598 NO
    # LONGER trips on the mana_pool_p1 color-residual STATE_EQ.
    # Either the run continues past 598 (most likely, surfacing the
    # next-frontier divergence at a later step — see the sibling
    # next-frontier pin), or it runs to terminal. Either is OK; what
    # is NOT OK is tripping at exactly step 598 with the Class-E
    # signature.
    if raised is not None:
        msg = str(raised)
        # The Class-E shape was a STATE_EQ on `mana_pool_p1` at step
        # 598. If the run trips at step 598 OR with a `mana_pool_p1`
        # color-residual signature, the ordered-pool fix regressed.
        regressed_at_598 = steps == 598
        regressed_signature = (
            raised.tripwire == "STATE_EQ" and "mana_pool_p1" in msg
        )
        assert not (regressed_at_598 and regressed_signature), (
            f"REGRESSION: the Class-E mana-pool generic-drain-order "
            f"divergence has re-surfaced at the original boundary step "
            f"598 with the original signature. The ordered-pool "
            f"`ManaPool` representation was REVERTED or a new drain "
            f"site is bypassing the `coins` vec. err={msg[:400]!r}"
        )
        # Also guard the narrower signature alone — if `mana_pool_p1`
        # COLOR-residual surfaces at ANY step, that's also a Class-E
        # regression (we no longer expect the engine to ever produce
        # a same-total-different-color residual on a generic-drain).
        if raised.tripwire == "STATE_EQ" and "mana_pool_p1" in msg:
            from mtg_bot.parity.cross_engine import (
                build_python_field_view, compare_fields, parity_smoke,
            )
            py_a, rust_a = adapter.py_adapter, adapter.rust_adapter
            pv = build_python_field_view(py_a.engine_state)
            rv = parity_smoke()._build_field_view(rust_a.rust_state)
            divs = {d.field: (d.py_value, d.rust_value)
                    for d in compare_fields(pv, rv)}
            if "mana_pool_p1" in divs:
                py_pool, rust_pool = divs["mana_pool_p1"]
                py_total = sum(n for _, n in py_pool)
                rust_total = sum(n for _, n in rust_pool)
                # A same-total-different-color residual IS the Class-E
                # signature. An unequal-total mana_pool_p1 divergence
                # is a different axis (affordability / count drift) —
                # not a Class-E regression.
                assert not (
                    py_total == rust_total and py_pool != rust_pool
                ), (
                    f"REGRESSION: `mana_pool_p1` STATE_EQ at step "
                    f"{steps} has the Class-E SAME-total-DIFFERENT-"
                    f"color signature (py={py_pool!r} rust={rust_pool!r}). "
                    f"The ordered-pool fix was undone."
                )


def test_g7_classe_closed_then_library_shuffle_order_next_frontier_surfaced():
    """**G7 S6-Class-E closure → next-frontier-surfaced** companion
    to ``test_g7_classe_mana_generic_pool_drain_order_root_cause_pinned``.

    The Class-E ordered-pool fix moves the arch1/s0 bake-in PAST the
    original step-598 ``mana_pool_p1`` trip. Pre-existing axes that
    were UPSTREAM-MASKED by Class E now surface — most notably the
    already-tracked ``library_pX`` shuffle-order frontier (todo
    ``b3f7c0a9``: search-then-shuffle parity — the per-engine
    shuffle RNG is not lockstep; identical multiset, divergent
    order). This pin asserts WHICH frontier surfaces next on the
    canonical arch1/s0 driver so:

    1. We have a load-bearing regression guard: if a future change
       silently un-shuffles or re-introduces Class E, THIS pin trips
       loudly instead of the bake-in running for 4000 steps then
       silently passing.

    2. The frontier's identity is documented (it is the
       library-shuffle-order axis, NOT a new mana-pool axis).

    3. The honest-stop is structurally enforced: Class E is closed,
       library-shuffle-order is OUTSIDE this lane's scope (filed as
       its own todo).
    """
    pytest.importorskip("mtg_bot_engine")
    from mtg_bot.parity import trajectory
    from mtg_bot.search.rust_shadow import (
        build_shadow_checked_adapter as _bsca,
    )

    deck = trajectory.load_production_deck(archetype=1)
    spec = trajectory.production_deck_to_deckspec(deck, shared_rng_seed=0)
    adapter = _bsca(spec)

    rng = random.Random(0)
    steps = 0
    raised: ShadowDivergenceError | None = None
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
        steps += 1

    # (1) The bake-in MUST surface a next-frontier divergence — if it
    # runs to terminal without tripping, an axis was masked rather
    # than surfaced (exactly what S6 exists to rule out).
    assert raised is not None, (
        "Class-E closed but the bake-in ran to terminal without "
        "surfacing the next frontier. An axis is masked. Re-walk the "
        "compare_fields output for the post-598 steps to find what's "
        "being silently dropped."
    )
    # (2) The next-frontier trip surfaces at the empirically-verified
    # boundary — step 600. The +2 over 598 is the post-ActivateAbility-
    # generic-drain step plus the post-resolve step where the
    # search-and-shuffle effect lands on the library; the boundary
    # is deterministic.
    assert steps == 600, (
        f"arch1/s0 Class-E closure: expected the next-frontier "
        f"boundary step 600 (library-shuffle-order axis), got "
        f"{steps}. Either Class E re-opened (would trip at 598) or "
        f"a DIFFERENT new frontier surfaced. err={str(raised)[:300]!r}"
    )
    # (3) The next-frontier signature: a STATE_EQ on `library_p1` —
    # the search-then-shuffle library-order axis (todo `b3f7c0a9`).
    # NOT a mana_pool_pX divergence (Class E is closed).
    assert raised.tripwire == "STATE_EQ", (
        f"expected the library-shuffle-order STATE_EQ shape, got "
        f"{raised.tripwire}: {str(raised)[:300]!r}"
    )
    msg = str(raised)
    assert "library_p1" in msg, (
        f"the surfaced next frontier MUST be the library_p1 shuffle-"
        f"order axis (the already-tracked todo b3f7c0a9). Got: "
        f"{msg[:400]!r}"
    )
    assert "mana_pool" not in msg, (
        f"REGRESSION GUARD: the CLOSED Class-E mana_pool axis must "
        f"NOT appear in the next-frontier shape. Got: {msg[:400]!r}"
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
        # (cycle-37 ``feature/g7-classb-priority-port-fix``); the
        # follow-on @369 ``LEGAL_SET_EQ`` G1 stateless-Rust
        # ``attack=False`` re-emission gap (todo ``a92e7d4f``) was
        # CLOSED by the present slice (the B3-S3
        # provider-accumulation port:
        # ``rust_engine_adapter.py::_finalize_attacker_phase`` +
        # ``_finalize_blocker_phase`` mirror
        # ``MtgGameStateAdapter._finalize_attacker_phase`` /
        # ``_finalize_blocker_phase`` (``engine_adapter.py:1101-1144``);
        # ``_refresh_combat_phase`` only INITIALIZES the eligible-id
        # queue on FIRST ENTRY (mirroring
        # ``_enter_declare_attackers`` /
        # ``_enter_declare_blockers``,
        # ``engine_adapter.py:1288-1361``) and ``_run_priority_action``
        # pops the queue head per ``AttackerDecision``/
        # ``BlockerDecision`` apply, finalizing when empty —
        # byte-mirroring ``_apply_attacker_decision``
        # ``_pending_attackers.pop(0)`` semantics
        # (``engine_adapter.py:1080-1099``)). Step 369 no longer
        # trips. The run proceeds PAST to a NEW distinct frontier
        # @504: a ``STATE_EQ`` tripwire on
        # ``('graveyard_p0', ...)`` + ``('graveyard_p1', ...)`` +
        # ``('battlefield', ...)`` — Rust kept Icecave Crasher (id 12)
        # AND Seedship Agrarian (id 83) on the battlefield while
        # Python moved BOTH to graveyards (Python's combat-damage
        # resolution + SBA flipped both as lethal-damaged, Rust's
        # did not). This is a **combat-damage outcome / SBA
        # divergence** — a NEW G-axis distinct from the
        # @369 ``LEGAL_SET_EQ`` attacker-decision re-emission axis,
        # the prior @367 ``priority_player`` STATE_EQ axis, AND the
        # already-tracked library-shuffle-order axis (``b3f7c0a9``;
        # arch2/s1 row). Unmasked — NOT introduced — by closing @369
        # (combat is now actually resolving on both engines, so the
        # next downstream divergence in combat-damage / SBA
        # outcomes surfaces; arch5/s0 simply never reached a
        # post-DECLARE_ATTACKERS combat-damage step before, blocked
        # at @369). Filed as the next G7 follow-up. The boundary +
        # tripwire are deterministic across runs.
        (5, 0, 369, 504, "STATE_EQ", "('graveyard_p0'"),
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
        # Loop cap bumped from 400 -> 4000 to accommodate the
        # arch5/s0 row's new next-frontier @504 (post-@369-closure
        # surfaced combat-damage / SBA divergence); the cap stays
        # safely below the other multi-seed pins' 4000 (they reach
        # similar depths post-closure).
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
        # auto_tap_pay_for_cost reroute. arch5/s0: PAST step 369 — the
        # post-Class-B G1 stateless-Rust ``attack=False`` re-emission
        # axis, closed by the present B3-S3 provider-accumulation
        # port (``_finalize_attacker_phase`` /
        # ``_finalize_blocker_phase`` + entry-only
        # ``_refresh_combat_phase``). A trip at/before the old boundary
        # means the relevant axis regressed (do NOT bump the boundary
        # — fix the engine).
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
    # **RE-CHARACTERIZED at G7 @808 G3 closure (this slice).** The
    # prior pin expected the post-@369/@757-closure next-frontier to
    # be the @808 ``STATE_EQ`` ``('priority_player', 0, 1)`` + Knight
    # Luminary tapped-state divergence (todo ``808a3f9c``). That axis
    # has NOW been CLOSED by the present G3 deferred-batch
    # combat-decision apply (``rust_engine_adapter.py``
    # ``_run_priority_action`` no longer routes
    # ``AttackerDecision`` / ``BlockerDecision`` through Rust's
    # per-decision ``apply_action``; instead
    # ``_finalize_attacker_phase`` / ``_finalize_blocker_phase``
    # issue the batched ``Action::DeclareAttackers`` /
    # ``Action::DeclareBlockers`` call once at queue-exhaustion —
    # byte-mirroring Python's
    # ``apply_action(state, ap.id, DeclareAttackers(
    # frozenset(_chosen_attackers)))`` in
    # ``engine_adapter.py:1103-1108``). The arch7/s0 row runs PAST
    # step 808 and surfaces at step 817 on a NEW distinct G-axis:
    # ``STATE_EQ`` ``('life_p0', 19, 20)`` — a 1-life delta (py
    # p0=19 vs rust p0=20) consistent with a combat-damage outcome
    # divergence (Rust did not deal 1 damage to p0 that Python did,
    # OR vice versa). The sequence leading in is
    # ``AttackerDecision(70,T) → (120,F) → (121,T)`` then a
    # ``CastSpell(76)`` (Radiant Strike, the Class-D Sequence
    # target leaf), then PassPriorities resolving combat damage at
    # @817. This is the SAME combat-damage outcome / SBA axis the
    # sibling-owned arch5/s0 @504 + arch30/s1 @431 rows surface
    # (todos ``504a1c7d``/``431b7e2a``); arch7/s0 simply reaches the
    # post-combat-damage tail later because of the surfacing-cycle
    # @504 sibling closure cascade. NOT a regression of @808 — a
    # downstream combat-damage / SBA divergence unmasked by the
    # @808 closure. Sibling-owned (combat-damage outcome / SBA axis,
    # not a separate G-axis); leave to the @504/@431 sibling agent.
    # The boundary + tripwire shape are deterministic across runs.
    arch, seed, old_boundary, exp_step, kind, needle = (
        7, 0, 808, 817, "STATE_EQ", "('life_p0', 19, 20)"
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

    # (1) STACKED CLOSURES CONFIRMED: the run proceeds PAST the
    # ``old_boundary`` step. With the G7 @808 G3 closure landing in
    # this slice, ``old_boundary`` is now the most-recently-closed
    # axis (808 — priority + Knight Luminary tapped-state divergence
    # caused by Rust's per-decision ``AttackerDecision`` eager apply
    # vs Python's batched finalize). The underlying Class-D
    # Sequence-target axis (was @453), the @757 attacker-decision
    # axis, AND the @808 priority/tapped axis are ALL closed at this
    # row; a stop at/before 808 means a regression of EITHER the
    # spell_targets_satisfiable Sequence-recursion fix (Class-D), OR
    # the @369/@757 provider-accumulation port, OR the present G3
    # deferred-batch combat-decision apply — fix the appropriate
    # engine path, do NOT bump the boundary.
    assert steps > old_boundary, (
        f"arch{arch}/s{seed}: the stacked Class-D + G1 attack=False "
        f"+ G3 deferred-batch closures must HOLD — the run must "
        f"proceed PAST step {old_boundary} (it stopped at {steps}). "
        f"A stop at/before {old_boundary} means EITHER the Class-D "
        f"cast-set / Sequence-target fix, OR the provider-"
        f"accumulation port (@369/@757), OR the present "
        f"deferred-batch combat-decision apply regressed — fix the "
        f"appropriate engine path, do NOT bump the boundary. "
        f"err={raised!r} raw={raw_exc!r}"
    )
    surfaced_msg = str(raised) if raised is not None else str(raw_exc)
    assert "cast_spell" not in surfaced_msg, (
        f"arch{arch}/s{seed}: the surfaced divergence still mentions a "
        f"cast_spell over-emission — the Class-D LEGAL_SET_EQ "
        f"cast-set asymmetry was NOT actually closed: "
        f"{surfaced_msg[:300]!r}."
    )
    # Regression guard: the surfaced divergence must NOT be the
    # G1 stateless-Rust ``attack=False`` re-emission ``LEGAL_SET_EQ``
    # axis (the @757 axis the @369-closure slice closed).
    assert "py\\rust=[\"('pass',)\"]" not in surfaced_msg, (
        f"arch{arch}/s{seed}: the surfaced divergence still has the "
        f"G1 attack=False re-emission signature — the @369/@757 "
        f"provider-accumulation port regressed: {surfaced_msg[:300]!r}."
    )
    # Regression guard: the surfaced divergence must NOT be the
    # @808 ``('priority_player', 0, 1)`` STATE_EQ + Knight Luminary
    # tapped axis (the axis the present slice just closed). A
    # ``priority_player`` STATE_EQ with the tapped-state diff
    # signature means the G3 deferred-batch port regressed.
    assert "('priority_player', 0, 1)" not in surfaced_msg, (
        f"arch{arch}/s{seed}: the surfaced divergence still has the "
        f"@808 priority_player + Knight Luminary tapped signature — "
        f"the G3 deferred-batch combat-decision port regressed: "
        f"{surfaced_msg[:300]!r}."
    )
    # (2) THE NEXT DISTINCT FRONTIER SURFACES LOUDLY at its
    # freshly-characterized boundary. It is a NEW G-axis distinct
    # from the closed Class-D + @757 attacker-decision axes.
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


def test_g7_classd_1of23_thawbringer_mana_affordability_closed_then_next_frontier():
    """**G7 S6-Class-D 1/23 Thawbringer mana-affordability closure
    pin** (cycle-37 Phase 2 — todo ``f5145c1d``).

    The G7 S6 Class-D cast-set asymmetry (23/300) was heterogeneous.
    22/23 were the homogeneous ``spell_targets_satisfiable``
    ``Effect::Sequence``-recursion bug — CLOSED by merge #1
    (``feature/g7-classd-castset`` → ``deee7ff4``). The remaining 1/23
    is the Thawbringer ``{2}{G}`` cast at arch30/s1 step 111:
    Rust ``legal_decisions`` over-emitted the cast despite p1 having
    only 2 untapped lands (Stomping Ground + Forest) for a 3-mana
    cost — Python correctly pruned via ``can_pay_cost``.

    **Root cause** (verify-first, ``rust/src/state_ops_mana.rs::
    can_pay_cost``). The legal-side affordability gate composed
    ``pool_can_cover(&auto_tap_headroom_pool(state, idx), cost)``.
    ``auto_tap_headroom_pool`` sums each untapped land's
    ``mana_produced`` symbols into per-color counts — so a Stomping
    Ground (``mana_produced = ["R", "G"]`` — Ravnica shock-land
    disjunction) credited ``pool.red += 1`` AND ``pool.green += 1``,
    counted as TWO mana of capacity when in reality the land taps for
    ONE (CR 605.1 — choose one produced color on activation).
    For Thawbringer ``{2}{G}`` (generic=2, green=1): the headroom
    pool was (R:1, G:2) → ``pool_can_cover`` returned true (G>=1
    consumes 1 of the 2 green credits; remaining 1+1=2 >= generic 2)
    → Rust over-emitted. Python's ``actions.can_pay_cost``
    (``actions.py:336-403``) tracks lands as a SET (``used_lands``):
    each land may be used at most once for any combination of
    colored/generic — Stomping Ground used for {G} (it can produce
    G) → 1 remaining land → generic 2 unpayable → False.

    **Fix** (new-code-is-right toward the Python SoT; cycle-37 Phase
    2 commit on this branch). ``state_ops_mana.rs::can_pay_cost`` no
    longer wraps ``pool_can_cover(auto_tap_headroom_pool(...))`` for
    the live-CastSpell affordability check — it byte-ports
    ``actions.can_pay_cost`` to a set-based implementation
    (``can_pay_cost_set_based``): pool coins consumed by INDEX,
    lands by ID, each at most once. Matches the apply-time
    ``auto_tap_pay_for_cost`` Phase 1 PLAN exactly — legal-emit and
    apply now agree on what's payable. The legal-side
    ``auto_tap_headroom_pool`` + ``pool_can_cover`` primitives stay
    in place for callers that operate on a pool only with no
    land-tap headroom (e.g. ``additional_costs_payable``); only the
    live affordability seam in ``can_pay_cost`` switches to the
    set-based port.

    **Closure proof + next-frontier.** Pre-Class-D-1of23-fix arch30/s1
    trips at step 111 with ``LEGAL_SET_EQ
    rust\\py=[('cast_spell', 80, ...)] py\\rust=[]``. Post-fix the
    run proceeded PAST 111 to step 321 where the SAME G1
    stateless-Rust ``attack=False`` re-emission ``LEGAL_SET_EQ`` axis
    the Class-B canonical arch5/s0 row surfaces at step 369 + the
    Class-D arch7/s0 row surfaces at step 757 — the same B3-S3
    provider-accumulation port follow-up. **RE-CHARACTERIZED at G7
    @369 closure (this slice).** The @321 G1 attacker-decision axis
    has NOW been CLOSED by the present B3-S3 provider-accumulation
    port. The arch30/s1 row runs PAST step 321 and surfaces at step
    431 on a NEW distinct G-axis: ``STATE_EQ`` ``('life_p0', 16, 20)``
    — a 4-life delta (py p0=16 vs rust p0=20) consistent with a
    combat-damage outcome divergence (Rust did not deal combat
    damage to p0 that Python did, OR vice versa). NOT a regression
    of either the Class-D mana-affordability fix or the @321
    attacker-decision axis — a downstream combat-damage / SBA
    divergence unmasked by the @321 closure.
    """
    pytest.importorskip("mtg_bot_engine")
    from mtg_bot.parity import trajectory
    from mtg_bot.search.engine_adapter_factory import (
        build_shadow_checked_adapter,
    )

    arch, seed, old_boundary, exp_step, kind, needle = (
        30, 1, 321, 431, "STATE_EQ", "('life_p0', 16, 20)"
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

    # (1) STACKED CLOSURES CONFIRMED: the run proceeds PAST the
    # ``old_boundary`` step. The Class-D 1/23 mana-affordability axis
    # (was @111) AND the @321 G1 attacker-decision re-emission axis
    # are BOTH closed at this row; the assertion now guards step
    # 321 (the most-recently-closed boundary, the present slice).
    assert steps > old_boundary, (
        f"arch{arch}/s{seed}: the stacked Class-D mana-affordability "
        f"(was @111) + G1 attack=False (was @321) closures must HOLD "
        f"— the run must proceed PAST step {old_boundary} (it stopped "
        f"at {steps}). A stop at/before {old_boundary} means EITHER "
        f"the set-based can_pay_cost port OR the present "
        f"provider-accumulation port regressed — fix the appropriate "
        f"engine path, do NOT bump the boundary. err={raised!r} "
        f"raw={raw_exc!r}"
    )
    surfaced_msg = str(raised) if raised is not None else str(raw_exc)
    # Regression guard: the surfaced divergence must NOT be a
    # cast_spell over-emission (the closed Class-D cast-set axis).
    assert "cast_spell" not in surfaced_msg, (
        f"arch{arch}/s{seed}: the surfaced divergence still mentions a "
        f"cast_spell over-emission — the Class-D mana-affordability "
        f"axis was NOT actually closed: {surfaced_msg[:300]!r}."
    )
    # Regression guard: the surfaced divergence must NOT be the
    # G1 stateless-Rust ``attack=False`` re-emission axis (the @321
    # axis the present slice just closed).
    assert "py\\rust=[\"('pass',)\"]" not in surfaced_msg, (
        f"arch{arch}/s{seed}: the surfaced divergence still has the "
        f"G1 attack=False re-emission signature — the @369/@321 "
        f"provider-accumulation port regressed: {surfaced_msg[:300]!r}."
    )
    # (2) THE NEXT DISTINCT FRONTIER SURFACES LOUDLY at its
    # freshly-characterized boundary. It is a NEW G-axis distinct
    # from the closed Class-D + G1 attack=False axes — a combat-damage
    # outcome / SBA divergence (``('life_p0', ...)`` 4-life delta).
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
        f"{needle!r} (same axis as Class-B @369 / Class-D @757). "
        f"Got: {str(raised)[:300]!r}."
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
