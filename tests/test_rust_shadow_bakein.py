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
    NOT priority/active), tracked as blocker **G6** and honestly
    pinned by
    ``test_post_player_loss_is_over_timing_divergence_is_surfaced``.
    None of G5/G6 is the I20/G4 mana axis; G4 closure does not depend
    on either and is complete without them
    (docs/SEARCH_LIMITATIONS.md / SOT_FLIP_CUTOVER_PLAN ledger)."""
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

    NOTE — closing G5 honestly UNMASKS a SEPARATE, distinct,
    pre-existing divergence (exactly as G4's closure unmasked G5): a
    game-over-detection-TIMING gap (``is_over`` / ``winner_id``, NOT
    priority/active). Python flips ``is_over``/``winner_id`` via
    ``state_based_actions`` at the next ``_enter_step`` after a player
    decks out; the Rust-driver port does not call ``apply_sbas()`` on
    the step-end / auto-advance path, so Rust's ``is_over()`` lags by
    one step. That is a DISTINCT Rust-driver SBA-timing port gap (NOT
    the G5 ``_next_alive`` priority axis, NOT the closed G4 mana
    axis), honestly pinned by
    ``test_post_player_loss_is_over_timing_divergence_is_surfaced``
    below and filed as its own blocker (G6) for the orchestrator
    (SOT_FLIP_CUTOVER_PLAN ledger / SEARCH_LIMITATIONS). This pin
    therefore asserts G5 closure over the window UP TO that distinct
    G6 trip point — keeping both the G5 closure AND the G6
    honest-stop true (feedback_no_fallback_hybrids /
    feedback_silent_noop_pipelines)."""
    adapter = _shadow()
    rng = random.Random(2026)
    steps = 0
    raised: ShadowDivergenceError | None = None
    # 150 steps clears the old step-~149 G5 priority_player trip point
    # with margin but stops BEFORE the distinct ~step-151 is_over-
    # timing divergence (G6, pinned independently below). The point of
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


def test_post_player_loss_is_over_timing_divergence_is_surfaced():
    """HONEST-STOP EVIDENCE PIN for a SEPARATE, distinct,
    pre-existing divergence the G5 closure now UNMASKS (it was MASKED
    by G5 tripping first at step ~149 on ``priority_player`` before
    the game-over-timing window) — tracked as blocker **G6**.

    Root cause (verified): in the degenerate 3-card
    ``tiny_synthetic_deckspec`` a player decks out by ~turn 8. After
    the pass-round at the post-deck-out PRECOMBAT_MAIN step ends,
    Python advances the step and its next ``_enter_step`` runs
    ``state_based_actions`` which flips ``is_over=True`` /
    ``winner_id=<survivor>``. The Rust-driver port
    (``RustGameStateAdapter._advance_to_next_decision`` / the step-end
    ``advance_phase`` branch) does NOT call ``apply_sbas()`` on the
    step-end / auto-advance path (only after resolution / non-pass
    actions), so Rust's ``is_over()`` / ``winner_id`` lag Python's by
    a step — a STATE_EQ ``is_over`` / ``winner_id`` divergence at
    step ~151. (Verified independently: Rust's own ``apply_sbas()``
    DOES flip ``is_over``/``winner_id`` when invoked — the gap is
    purely that the adapter does not call it on this path.)

    This is **NOT the G5 ``_next_alive`` priority/active axis** (G5
    is closed — see ``test_post_player_loss_priority_port_is_closed``)
    and **NOT the closed G4 I20 mana axis**. It is a distinct
    Rust-driver SBA-timing port gap, filed for the orchestrator as
    its own blocker (G6) in ``docs/SOT_FLIP_CUTOVER_PLAN.md`` /
    ``docs/SEARCH_LIMITATIONS.md``. This pin keeps it HONEST (the
    tripwire fires loudly on it — it is real, not papered over:
    feedback_no_fallback_hybrids / feedback_silent_noop_pipelines)."""
    adapter = _shadow()
    rng = random.Random(2026)
    steps = 0
    raised: ShadowDivergenceError | None = None
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
    assert raised is not None, (
        "expected the bake-in to surface the separate post-deck-out "
        "is_over/winner_id SBA-timing divergence loudly, but the run "
        "completed clean — the tripwire would be a silent no-op "
        "(feedback_silent_noop_pipelines)"
    )
    # It surfaces as a STATE_EQ is_over / winner_id divergence (NOT
    # the now-closed G5 priority_player, NOT the closed G4 I20
    # cast_spell).
    assert raised.tripwire == "STATE_EQ", (
        f"the separate post-loss is_over-timing issue must surface as "
        f"STATE_EQ, got {raised.tripwire}: {raised}"
    )
    assert (
        "is_over" in str(raised) or "winner_id" in str(raised)
    ), (
        f"the separate post-loss issue must name the is_over/"
        f"winner_id game-over-timing divergence (NOT the closed G5 "
        f"priority_player, NOT the closed G4 cast_spell): {raised}"
    )
    assert "priority_player" not in str(raised), (
        f"this must NOT be the now-CLOSED G5 priority-port signature "
        f"(closed by the _next_alive alive-skip port): {raised}"
    )
    assert "cast_spell" not in str(raised), (
        f"this must NOT be the closed G4 I20 cast-set signature: "
        f"{raised}"
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
