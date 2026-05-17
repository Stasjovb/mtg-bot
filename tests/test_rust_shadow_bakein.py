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

    NOTE — a SEPARATE, pre-existing, non-G4 issue is honestly pinned
    by ``test_post_player_loss_priority_port_divergence_is_surfaced``:
    once a player decks out (degenerate 3-card synthetic deck, ~turn
    6-8) the Rust-driver priority-reset port
    (``RustGameStateAdapter._reset_priority_to_active``) diverges from
    Python's alive-aware ``_next_alive`` on ``priority_player`` /
    ``active_player``. That is NOT the I20/G4 mana axis (it is the
    Rust-driver priority port, a distinct surface) — G4 closure does
    not depend on it and is complete without it; it is flagged for
    the orchestrator as a separate follow-up
    (docs/SEARCH_LIMITATIONS.md / SOT_FLIP_CUTOVER_PLAN ledger G4
    entry)."""
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


def test_post_player_loss_priority_port_divergence_is_surfaced():
    """HONEST-STOP EVIDENCE PIN for a SEPARATE, pre-existing, NON-G4
    issue the strengthened tripwire now surfaces (it was MASKED by G4
    tripping first at step ~143 before any player decked out).

    Root cause (verified): in the degenerate 3-card
    ``tiny_synthetic_deckspec`` both players deck out by ~turn 6-8.
    When the active player has lost, Python's
    ``_enter_priority_for_current_step`` uses ``_next_alive`` (CR-
    aware: skips the lost active player), but the Rust-driver port
    ``RustGameStateAdapter._reset_priority_to_active`` sets priority
    to the (lost) active player unconditionally — a ``priority_player``
    then ``active_player`` STATE_EQ divergence.

    This is **NOT the I20/G4 mana axis** (G4 is closed — see
    test_g4_i20_cast_set_axis_is_closed_by_lockstep) and **NOT
    introduced by the G4 mana mirror** (which only clears mana
    pools). It is a distinct Rust-driver priority-port gap in the
    post-player-loss tail, flagged for the orchestrator
    (docs/SEARCH_LIMITATIONS.md / SOT_FLIP_CUTOVER_PLAN ledger G4
    entry). This pin keeps it HONEST (the tripwire fires loudly on it
    — it is real, not papered over: feedback_no_fallback_hybrids /
    feedback_silent_noop_pipelines)."""
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
        "priority-port divergence loudly, but the run completed clean "
        "— the tripwire would be a silent no-op "
        "(feedback_silent_noop_pipelines)"
    )
    # It surfaces as a STATE_EQ priority_player / active_player
    # divergence (NOT a LEGAL_SET_EQ cast_spell — that was the now-
    # closed G4 I20 signature).
    assert raised.tripwire == "STATE_EQ", (
        f"the separate post-loss issue must surface as STATE_EQ, got "
        f"{raised.tripwire}: {raised}"
    )
    assert (
        "priority_player" in str(raised)
        or "active_player" in str(raised)
    ), (
        f"the separate post-loss issue must name the priority/active "
        f"player port divergence (NOT the closed G4 cast_spell): "
        f"{raised}"
    )
    assert "cast_spell" not in str(raised), (
        f"this must NOT be the closed G4 I20 cast-set signature "
        f"(that axis is closed by the lockstep mana mirror): {raised}"
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
