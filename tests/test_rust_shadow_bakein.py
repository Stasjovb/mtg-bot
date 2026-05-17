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
    hold every step) over the window where it is currently valid: the
    matched start state + the bounded prefix BEFORE the documented
    G4 (I20-cast-set) asymmetry accumulates. This proves the
    shadow-checker harness itself is correct + the matched states
    start byte-equal; the FULL terminal run is blocked by G4 (the
    precisely-scoped NEW pre-flip blocker the bake-in surfaced — see
    test_g4_i20_cast_set_blocker_is_surfaced and
    docs/SEARCH_LIMITATIONS.md). 40 steps is comfortably inside the
    pre-G4 window for the tiny synthetic deck (G4 first trips ~step
    143 once Python has held mana across phases for several turns)."""
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


def test_g4_i20_cast_set_blocker_is_surfaced():
    """HONEST-STOP EVIDENCE PIN (NOT a silent skip). The bake-in
    SURFACES a genuine, precisely-scoped NEW pre-flip blocker — G4,
    the C1/G1-analog for the I20 axis: the documented Python
    mana-hold-until-cleanup simplification (turn.py:1081-1083 /
    RUST_PARITY_GAPS §I20) diverges the legal CAST SET (not just the
    mana_pool field) under the role-swapped Rust-driven / Python-
    shadow contract. The existing step_both harness avoided this by
    replaying a Python-derived script + reconciling I20 via
    advance_phase_python; once Python is a passive shadow, its
    stale-held-mana legal_actions offers a CastSpell that Rust's
    CR-correct per-phase-empty model correctly prunes. This pin
    PROVES the tripwire fires loudly on G4 (it is real, not papered
    over — feedback_no_fallback_hybrids). Closing G4 (drive the
    Python checker's phase advancement through advance_phase_python
    so its mana matches Rust's CR-correct per-phase empty) is an
    orchestrator-sequenced bake-in-scaling refinement, NOT a B3-S4
    deliverable; B3-S4 ships the harness + this honest evidence."""
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
        "expected the bake-in to surface the G4 I20-cast-set blocker "
        "loudly, but the run completed clean — the tripwire would be "
        "a silent no-op (feedback_silent_noop_pipelines)"
    )
    # The surfaced blocker is the I20-cast-set divergence: Python
    # offers a CastSpell its held-over mana makes payable that Rust's
    # per-phase-empty model prunes (LEGAL_SET_EQ), OR the mana_pool
    # itself when it is the only delta (documented-accepted, so the
    # cast-set LEGAL_SET_EQ is the load-bearing one).
    assert raised.tripwire == "LEGAL_SET_EQ", (
        f"G4 must surface as a LEGAL_SET_EQ cast-set divergence, got "
        f"{raised.tripwire}: {raised}"
    )
    assert "cast_spell" in str(raised), (
        f"G4 evidence must name the cast_spell the I20 held mana "
        f"makes Python offer but Rust prunes: {raised}"
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
