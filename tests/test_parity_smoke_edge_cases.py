"""Phase-5 cross-engine smoke harness — edge-case coverage.

Companion file to ``tests/test_parity_smoke.py``. Lives separately to avoid
edit conflicts with the parallel CE4 closure work that's actively flipping
xfail markers in the main parity-smoke test file.

The tests below exercise boundary conditions that the inaugural Phase-5
smoke harness (in the main test file) doesn't cover:

* **Library boundary** — empty library + 1-card library, exercised via
  the ``play_a_land_selector`` side-channel ``draw_card`` on step 0 and
  via the ``multi_turn_selector`` advance-phase composition.
* **Asymmetric deck sizes** — p0 holds a larger library than p1; the
  harness should walk parity-clean since the per-player snapshot
  pathways are independent.
* **Scale stress** — drive ``play_a_land_selector`` for 200+ decisions
  on the slightly_bigger_deckspec; checks that the parity-clean walk
  shape doesn't degrade as the step count grows.
* **Shuffle seed** — Python uses Mersenne Twister, Rust uses xorshift64.
  Distinct PRNGs => distinct shuffle permutations on the same seed.
  This is a documented (and intentionally accepted) bridge limitation;
  pin it as a strict-xfail at step 0 so any future "we fixed shuffle
  parity" closure breaks loudly when this test flips to xpass.

NOVEL divergence surfaced (Phase 5 edge-case slice, 2026-05-11):

* **CE-pure-derivation-is_over** — when ``draw_card`` is called on an
  empty library via the harness side-channel, Rust's ``is_over`` /
  ``winner_id`` flip immediately (pure-derivation predicate over
  ``has_lost || attempted_draw_on_empty || life<=0``), but Python's
  stay stale because Python's ``GameState.is_over`` reads
  ``winner_id`` which is only written by an SBA pass (no eager
  derivation). The harness's walk does NOT run SBAs between steps,
  so the two engines diverge on ``is_over`` / ``winner_id`` even
  though the underlying loss-cause flags (``has_lost`` /
  ``attempted_draw_on_empty``) agree on both sides.

  See the strict-xfail test below; this is the first finding of the
  edge-case slice and is reported back to the user for filing as a
  formal CE<n> entry in ``docs/RUST_PARITY_GAPS.md`` (kept out of the
  doc here to avoid conflicting with the parallel CE4 closure agent
  editing the same file).
"""

from __future__ import annotations

import importlib.util

import pytest


# Skip the whole module if the Rust extension isn't built — mirrors the
# main test file's policy.
pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# Edge case #1: empty-library side-channel draw flags a NOVEL is_over /
# winner_id divergence. Strict-xfail pin so any future closure (Python
# growing a pure-derivation is_over OR the harness gaining an SBA pass
# between steps) flips this to xpass and the maintainer removes the marker.
# ---------------------------------------------------------------------------


def test_cross_engine_empty_library_side_channel_draw_walks_clean():
    """Drive ``play_a_land_selector`` for 2 decisions on a deck whose
    libraries are EMPTY at game start. The selector's step-0 side-channel
    ``draw_card`` fires on both engines; both engines now agree on the
    surface ``is_over`` / ``winner_id`` reading because both are SBA-gated.

    **Post-CE10 closure (CE-pure-derivation-is_over, 2026-05-11):**
    Rust's surface ``is_over`` / ``winner_id`` getters (in
    ``state_ops_winloss.rs``) were changed from the eager OR'd-three
    predicate (``has_lost || attempted_draw_on_empty || life<=0`` on
    any player) to SBA-gated (``has_lost`` only — the sticky flag
    written by ``apply_sbas``). This matches Python's surface, where
    ``GameState.is_over`` / ``winner_id`` / ``is_draw`` are written
    only by ``apply_state_based_actions``. The eager pure-derivation
    is still available through ``losers()`` / ``winner()`` /
    ``is_game_over()`` for callers that need pre-SBA loss
    observability (e.g. the SBA loop itself).

    Post-closure both engines walk parity-clean on this harness: the
    side-channel ``draw_card`` flips ``attempted_draw_on_empty`` on
    Rust and ``has_lost`` on Python, but neither side's surface
    ``is_over`` flips until an SBA pass commits the loss — and the
    harness does NOT fire SBAs between steps.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef,
        DeckSpec,
        play_a_land_selector,
        walk_both,
    )

    forest = CardDef(name="Forest", card_type="Land", mana_produced=("G",))
    bears = CardDef(
        name="Grizzly Bears",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=2,
        toughness=2,
    )
    deck = DeckSpec(card_defs=(forest, bears), p0_library=(), p1_library=())
    result = walk_both(
        deck, n_decisions=2, decision_selector=play_a_land_selector
    )
    assert result.error is None
    assert result.aborted_at is None
    # The strict-xfail assertion: divergences empty across the walk.
    for step in result.steps:
        assert step.divergences == [], (
            f"step {step.step_index}: "
            f"{[(d.field, d.py_value, d.rust_value) for d in step.divergences]}"
        )


def test_cross_engine_empty_library_side_channel_draw_post_closure_both_engines_stay_stale():
    """Post-CE10 closure (CE-pure-derivation-is_over) inverted-shape
    pin. Pre-closure, this test pinned the SHAPE of the divergence
    (Rust True/1 vs Python False/None on is_over/winner_id). Post-
    closure, both engines stay stale on the surface getters because
    both are SBA-gated and the harness does not fire SBAs.

    Asserts the post-closure shape:
      * The is_over / winner_id fields do NOT diverge at step 0.
      * BOTH engines report is_over=False, winner_id=None — surface
        is stale on both sides because no SBA fired.
      * The underlying loss-cause flag (Python: ``p0.has_lost``,
        Rust: ``p0.attempted_draw_on_empty``) is still set eagerly
        on both sides; the surface accessors just don't observe it
        until SBA commits.

    If this test ever fails post-closure, the most likely cause is
    that Rust's surface ``is_over`` / ``winner_id`` regressed to the
    eager OR'd-three predicate. Mirror invariant pin tests in
    ``tests_rust/test_winloss.py``:
      - ``test_winner_id_pre_sba_stale_matches_python_semantics``
      - ``test_is_over_winner_id_eager_for_empty_library_draw_via_pure_derivation``
    """
    from mtg_bot.parity.cross_engine import (
        CardDef,
        DeckSpec,
        play_a_land_selector,
        walk_both,
    )

    forest = CardDef(name="Forest", card_type="Land", mana_produced=("G",))
    bears = CardDef(
        name="Grizzly Bears",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=2,
        toughness=2,
    )
    deck = DeckSpec(card_defs=(forest, bears), p0_library=(), p1_library=())
    result = walk_both(
        deck, n_decisions=2, decision_selector=play_a_land_selector
    )
    assert result.error is None
    # First step's divergences: is_over + winner_id MUST NOT appear.
    step_0 = result.steps[0]
    fields = {d.field for d in step_0.divergences}
    assert "is_over" not in fields, (
        f"post-CE10, is_over should agree (both stale); got fields={sorted(fields)}"
    )
    assert "winner_id" not in fields, (
        f"post-CE10, winner_id should agree (both stale); got fields={sorted(fields)}"
    )
    # Both engines report stale surface (no SBA fired in this harness).
    assert step_0.py_view["is_over"] is False
    assert step_0.rust_view["is_over"] is False
    assert step_0.py_view.get("winner_id") is None
    assert step_0.rust_view.get("winner_id") is None


# ---------------------------------------------------------------------------
# Edge case #2: scale stress. play_a_land_selector walks parity-clean to
# N=10 today (existing test). Crank to N=200 to make sure no long-tail
# divergence creeps in as the step count grows. Regression-harden if clean.
# ---------------------------------------------------------------------------


def test_cross_engine_play_a_land_selector_walks_clean_at_n_200():
    """The existing N=10 test pins play_a_land_selector parity-clean on
    slightly_bigger_deckspec. Scale to N=200 — if some long-tail
    divergence is lurking past the 10-decision horizon (e.g.
    accumulated mana-pool state, end-of-turn cleanup, library drain to
    empty), this test catches it.

    Outcome at landing: clean (Phase-5 edge-case slice). Regression-
    hardened against any future change that introduces step-count-
    dependent drift on this selector.
    """
    from mtg_bot.parity.cross_engine import (
        play_a_land_selector,
        slightly_bigger_deckspec,
        walk_both,
    )

    result = walk_both(
        slightly_bigger_deckspec(),
        n_decisions=200,
        decision_selector=play_a_land_selector,
    )
    assert result.error is None
    assert result.aborted_at is None
    assert len(result.steps) == 200
    for step in result.steps:
        assert step.divergences == [], (
            f"unexpected divergence at step {step.step_index}: "
            f"{[(d.field, d.py_value, d.rust_value) for d in step.divergences]}"
        )


# ---------------------------------------------------------------------------
# Edge case #3: asymmetric deck sizes. The harness's per-player snapshot
# pathway is independent (each side has its own library_pN / hand_pN
# field-view slot), so a p0-bigger / p1-smaller deck should walk just
# as cleanly as a symmetric one — but the inaugural smoke only
# exercised symmetric 3-4 card decks. This is the first asymmetric
# coverage.
# ---------------------------------------------------------------------------


def test_cross_engine_asymmetric_deck_sizes_walk_clean():
    """p0 holds 10 cards, p1 holds 1 card. play_a_land_selector
    side-channel-draws on step 0 (p0 has a card to draw; p1's draw
    pulls their single Forest), then drives PassPriority for the
    remaining steps. Both engines should walk parity-clean — there's
    no cross-player coupling in the snapshot path that an asymmetry
    could violate.

    Guards against a future refactor that, e.g., accidentally
    indexes the wrong player's library in a per-player loop on one
    side. Regression-harden if clean.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef,
        DeckSpec,
        play_a_land_selector,
        walk_both,
    )

    forest = CardDef(name="Forest", card_type="Land", mana_produced=("G",))
    bears = CardDef(
        name="Grizzly Bears",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=2,
        toughness=2,
    )
    deck = DeckSpec(
        card_defs=(forest, bears),
        # p0: 8 Forests + 2 Bears = 10 cards. p1: 1 Forest.
        p0_library=tuple(["Forest"] * 8 + ["Grizzly Bears"] * 2),
        p1_library=("Forest",),
    )
    result = walk_both(
        deck, n_decisions=15, decision_selector=play_a_land_selector
    )
    assert result.error is None
    assert result.aborted_at is None
    assert len(result.steps) == 15
    for step in result.steps:
        assert step.divergences == [], (
            f"asymmetric-deck divergence at step {step.step_index}: "
            f"{[(d.field, d.py_value, d.rust_value) for d in step.divergences]}"
        )


# ---------------------------------------------------------------------------
# Edge case #4: 1-card libraries + multi_turn_selector. The
# advance_phase composition on BOTH engines uses an "inline" draw_card
# variant. Historical state (before feature/draw-card-inline-flag):
#
# * Python: advance_phase_python calls turn.draw_card which DOES set
#   has_lost eagerly on empty pop, but Python's is_over reads
#   winner_id (only written by an SBA pass) so the loss didn't
#   surface via the is_over field-view in this harness.
# * Rust: state_ops_steps.rs::draw_card_inline was a SILENT no-op on
#   empty libraries — the sibling pymethod draw_card /
#   Effect::DrawCards arms set attempted_draw_on_empty but the
#   auto-draw inline path didn't, leaving the active player
#   un-flagged when they decked out via the DRAW step.
#
# So the parity here used to be "consistently wrong in different
# ways" — both engines silently failed to surface the deck-out loss
# on is_over and the per-field comparison stayed clean.
#
# Post-closure (feature/draw-card-inline-flag, 2026-05-11): the Rust
# auto-draw inline path now flips attempted_draw_on_empty on empty
# pop, mirroring the pymethod / Effect::DrawCards arms. The closure
# SURFACES the SAME CE-pure-derivation-is_over divergence pinned by
# the strict-xfail above (Rust derives is_over eagerly over the
# loss-cause flags; Python's is_over reads winner_id which only an
# SBA writes). The test below is now strict-xfailed for the same
# reason — see its xfail marker for the closure plan.
# ---------------------------------------------------------------------------


def test_cross_engine_single_card_libraries_multi_turn_walks_clean():
    """Both players start with 1-card libraries. Drive 100 decisions of
    multi_turn_selector (multiple full turns, with DRAW steps on turn 2+
    that consume the single card and then attempt empty-library draws
    on turn 3+).

    **Post-CE10 closure (CE-pure-derivation-is_over, 2026-05-11):**
    The two engines now agree on the surface ``is_over`` / ``winner_id``
    reading because both are SBA-gated. The chain is:

      1. The earlier ``feature/draw-card-inline-flag`` closure aligned
         the cause-flag side: Rust's auto-draw inline path
         (``state_ops_steps.rs::draw_card_inline``) flips
         ``attempted_draw_on_empty`` on empty pop, mirroring the
         pymethod / ``Effect::DrawCards`` arms.
      2. This (CE10) closure aligned the surface side: Rust's
         ``is_over`` / ``winner_id`` getters no longer read the eager
         OR'd-three predicate; they read ``has_lost`` only, matching
         Python's SBA-written fields.

    With both aligned, the walk stays parity-clean across all 100
    steps. The deck-out cause-flag fires on both engines (Python:
    ``p.has_lost = True`` in ``turn.draw_card``; Rust:
    ``p.attempted_draw_on_empty = true`` in ``draw_card_inline``),
    but neither side's surface ``is_over`` flips because the harness
    doesn't fire SBAs.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef,
        DeckSpec,
        multi_turn_selector,
        walk_both,
    )

    forest = CardDef(name="Forest", card_type="Land", mana_produced=("G",))
    bears = CardDef(
        name="Grizzly Bears",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=2,
        toughness=2,
    )
    deck = DeckSpec(
        card_defs=(forest, bears),
        p0_library=("Forest",),
        p1_library=("Forest",),
    )
    result = walk_both(
        deck, n_decisions=100, decision_selector=multi_turn_selector
    )
    assert result.error is None
    assert result.aborted_at is None
    assert len(result.steps) == 100
    # Walk should stay parity-clean across all 100 steps (full turn
    # cycles, both engines deplete their libraries by turn 3 and then
    # silently no-op on subsequent draw steps).
    for step in result.steps:
        assert step.divergences == [], (
            f"single-card mt divergence at step {step.step_index}: "
            f"{[(d.field, d.py_value, d.rust_value) for d in step.divergences]}"
        )
    # Neither engine surfaces is_over=True — the documented
    # "consistently wrong in different ways" state.
    assert result.steps[-1].py_view["is_over"] is False
    assert result.steps[-1].rust_view["is_over"] is False


# ---------------------------------------------------------------------------
# Edge case #5: shuffle seed produces a documented library order
# divergence. Python uses Mersenne Twister (random.Random); Rust uses
# xorshift64 (build_rust_state via mtg_bot_engine.make_state). The two
# PRNGs share a seed but produce different permutations — by design.
# Pin this as a strict-xfail at step 0 so any future "we aligned the
# shuffle PRNG" closure (e.g. landing the Rust-side MT mirror, or
# adopting an externally-fed RNG stream from Python on both sides) flips
# this to xpass.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Documented bridge limitation (RUST_PARITY_PLAN.md Decision 1): "
        "Python shuffles with Mersenne Twister, Rust shuffles with "
        "xorshift64. Same seed -> different permutation -> library_p0 "
        "and library_p1 diverge at step 0. Strict-xfail until either "
        "(a) Rust adopts MT, (b) both engines accept an external RNG "
        "stream, or (c) the harness disables shuffle entirely on cross-"
        "engine specs (shuffle_seed=None bypasses this — used by every "
        "other Phase-5 test)."
    ),
)
def test_cross_engine_shuffle_seed_walks_clean():
    """Build matched states with ``shuffle_seed=42`` and assert the
    libraries match at step 0. Today they don't — the Python MT
    permutation differs from the Rust xorshift64 permutation. Strict-
    xfail pins this; when shuffle parity lands the test flips to xpass.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        slightly_bigger_deckspec,
        walk_both,
    )

    base = slightly_bigger_deckspec()
    deck = DeckSpec(
        card_defs=base.card_defs,
        p0_library=base.p0_library,
        p1_library=base.p1_library,
        shuffle_seed=42,
    )
    result = walk_both(deck, n_decisions=0)
    # The strict-xfail assertion: no initial divergence on libraries.
    fields = {d.field for d in result.initial_divergences}
    assert "library_p0" not in fields
    assert "library_p1" not in fields


def test_cross_engine_shuffle_seed_surfaces_library_divergence_for_multiple_seeds():
    """Companion symptom-present pin for the shuffle-seed strict-xfail.

    Confirms the SHAPE of the divergence across multiple seeds:
    library_p0 AND library_p1 both diverge at step 0 (initial state)
    for every seed value tested. The divergence is reproducible per-
    seed (the same seed produces the same Python permutation and the
    same Rust permutation, just different from each other).

    When shuffle parity lands:
      * The strict-xfail above flips to xpass; remove its marker.
      * This symptom test starts FAILING because the values would agree.
        Remove / invert as part of the closure pair contract.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        slightly_bigger_deckspec,
        walk_both,
    )

    base = slightly_bigger_deckspec()
    # Multiple seeds exercise the PRNG mismatch repeatably; if any seed
    # accidentally produced the same Python+Rust permutation (the
    # Birthday-style collision case), the strict-xfail above would
    # become flaky. Pin three independent seeds to make that collision
    # astronomically unlikely.
    for seed in (1, 7, 42, 100):
        deck = DeckSpec(
            card_defs=base.card_defs,
            p0_library=base.p0_library,
            p1_library=base.p1_library,
            shuffle_seed=seed,
        )
        result = walk_both(deck, n_decisions=0)
        fields = {d.field for d in result.initial_divergences}
        assert "library_p0" in fields, (
            f"seed={seed}: expected library_p0 to diverge; got fields={sorted(fields)}"
        )
        assert "library_p1" in fields, (
            f"seed={seed}: expected library_p1 to diverge; got fields={sorted(fields)}"
        )
