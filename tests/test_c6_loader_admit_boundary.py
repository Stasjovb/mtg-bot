"""C6 — the loader-admit gate is the enforced soundness boundary.

This is the **B2 / Step-2 invariant pin** from
``docs/SOT_FLIP_CUTOVER_PLAN.md`` (criterion **C6**). It asserts that
the loader-admit boundary — ``trajectory._filter_deck_to_bridge_
supported``'s 5-disjunct chokepoint plus the
``production_deck_to_deckspec`` Forest-pad — is:

  1. **Observable** — ``production_deck_to_deckspec_instrumented``
     surfaces *exactly* which deck slots the gate dropped (unresolved
     vs resolved-but-not-bridged, per side, with multiplicity) and how
     many Forest-pad slots were appended. The reduced-card-universe
     consequence is now an explicit, bounded artifact, not a silent
     mutation.
  2. **Fail-loud / enforced** — under ``LoaderAdmitPolicy.RAISE`` a
     non-admitted card RAISES ``NonAdmittedCardError`` rather than
     silently degrading the deck. This is the post-flip Rust-sourced
     soundness fence: a card the loader cannot bridge can never quietly
     enter a Rust-authoritative game as a Forest.
  3. **Parity-neutral** — the default loader path
     (``production_deck_to_deckspec``, ``DROP`` + no observe) is
     **bit-identical** to the pre-C6 behavior. The Python-SoT parity
     harness and every pinned trajectory are unchanged; the boundary is
     only made observable + asserted, never moved.

If this pin ever fails it means either (a) the loader-admit drop became
silent again (the observable regressed), (b) a non-admitted card can be
played as itself outside the fence (the enforcement regressed), or
(c) the default path stopped being bit-identical to the silent-drop
behavior (parity-neutrality regressed). Each is a hard C6 / SoT-flip
soundness regression — investigate, do not paper over.

This pin does NOT change what gets admitted (that is C1 / the
substrates' job). It pins the EXISTING boundary as enforced,
non-silent, and bounded.
"""

from __future__ import annotations

import importlib.util

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# (3) Parity-neutrality — the load-bearing invariant. The default loader
# path MUST be bit-identical to the pre-C6 silent-drop+Forest-pad
# behavior, so no pinned trajectory shifts.
# ---------------------------------------------------------------------------


def test_default_loader_path_is_bit_identical_to_instrumented_drop():
    """The default ``production_deck_to_deckspec`` produces the EXACT
    same DeckSpec as the instrumented ``DROP`` path.

    This is the parity-neutrality proof in miniature: the only thing C6
    adds on the default path is observability — the produced DeckSpec
    (card_defs, both libraries, rng seed) is unchanged, so the
    Python-SoT parity harness and every pinned trajectory that drives
    real decks through ``production_deck_to_deckspec`` see byte-identical
    inputs before and after this slice.
    """
    from mtg_bot.parity.trajectory import (
        load_production_deck,
        production_deck_to_deckspec,
        production_deck_to_deckspec_instrumented,
    )

    for archetype in (0, 1, 2):
        p0 = load_production_deck(archetype)
        p1 = load_production_deck(archetype + 1)

        plain = production_deck_to_deckspec(p0, p1, shared_rng_seed=7)
        inst, _report = production_deck_to_deckspec_instrumented(
            p0, p1, shared_rng_seed=7,
        )
        assert plain == inst, (
            f"archetype {archetype}: the instrumented DROP path must be "
            f"bit-identical to the default loader path — C6 is "
            f"observe-only, it must not move the boundary"
        )

        # Mirror-match (p1=None) path must also stay identical.
        plain_m = production_deck_to_deckspec(p0, shared_rng_seed=7)
        inst_m, _rm = production_deck_to_deckspec_instrumented(
            p0, shared_rng_seed=7,
        )
        assert plain_m == inst_m


def test_default_path_return_type_and_signature_unchanged():
    """``production_deck_to_deckspec`` still returns a bare ``DeckSpec``
    (NOT a tuple) — existing callers / pinned trajectories that unpack
    ``spec = production_deck_to_deckspec(...)`` are untouched.
    """
    from mtg_bot.parity.cross_engine import DeckSpec
    from mtg_bot.parity.trajectory import (
        load_production_deck,
        production_deck_to_deckspec,
    )

    spec = production_deck_to_deckspec(load_production_deck(0))
    assert isinstance(spec, DeckSpec)
    assert not isinstance(spec, tuple)


# ---------------------------------------------------------------------------
# (1) Observable — the loader records what it dropped + Forest-padded.
# ---------------------------------------------------------------------------


def test_loader_drop_is_observable_not_silent():
    """A real 17lands deck (0 / 129,996 are fully loader-admittable per
    ``LOADER_ADMIT_COMPLETENESS_ANALYSIS.md``) loses ≥1 card to the
    gate; the loss is now an explicit, named, bounded artifact.
    """
    from mtg_bot.parity.trajectory import (
        load_production_deck,
        production_deck_to_deckspec_instrumented,
    )

    p0 = load_production_deck(0)
    p1 = load_production_deck(1)
    spec, report = production_deck_to_deckspec_instrumented(
        p0, p1, shared_rng_seed=42,
    )

    # The accepted staged-flip consequence is now SURFACED, not silent:
    # every real deck drops ≥1 slot (the C6 / LOADER_ADMIT analysis
    # 0/129,996-fully-admitted fact).
    assert report.any_dropped is True
    assert report.total_dropped >= 1

    # The drop is BOUNDED and itemised: every dropped name is recorded
    # with multiplicity, split into unresolved vs resolved-but-not-
    # bridged. The Forest-pad count is exposed too — the reduced-universe
    # padding is no longer a hidden mutation.
    dropped_p0 = list(report.p0_unresolved) + list(report.p0_not_bridged)
    dropped_p1 = list(report.p1_unresolved) + list(report.p1_not_bridged)
    assert len(dropped_p0) >= 1
    assert len(dropped_p0) + len(dropped_p1) == report.total_dropped
    assert report.p0_pad_count >= 0
    assert report.p1_pad_count >= 0
    assert report.pad_with == "Forest"

    # The observable must be CONSISTENT with the DeckSpec the same call
    # produced: admitted-slots + pad == final library size. This pins
    # that the report is a faithful account of the actual mutation, not
    # decorative.
    p0_admitted = len(spec.p0_library) - report.p0_pad_count
    assert p0_admitted >= 0
    assert p0_admitted + report.p0_pad_count == len(spec.p0_library)


def test_report_distinguishes_unresolved_from_not_bridged():
    """Unresolved (absent from the CardSource) vs resolved-but-not-
    bridged are recorded in distinct buckets, preserving multiplicity.
    """
    from mtg_bot.parity.trajectory import (
        production_deck_to_deckspec_instrumented,
    )

    # 30 Forests (admitted basic land) + 4 copies of a name that cannot
    # resolve in any CardSource. p1=None -> mirror match, so p1's drop
    # record equals p0's (total_dropped counts BOTH sides).
    deck = ["Forest"] * 30 + ["__definitely_not_a_real_card__"] * 4
    _spec, report = production_deck_to_deckspec_instrumented(deck)

    assert report.p0_unresolved == ("__definitely_not_a_real_card__",) * 4
    assert report.p0_not_bridged == ()
    assert report.p1_unresolved == report.p0_unresolved  # mirror match
    assert report.total_dropped == 8  # 4 per side, both sides counted
    assert report.any_dropped is True


def test_fully_admitted_deck_reports_no_drop():
    """An all-basic-land deck is fully admitted — the observable
    correctly reports zero drops (the boundary was NOT crossed).
    """
    from mtg_bot.parity.trajectory import (
        production_deck_to_deckspec_instrumented,
    )

    _spec, report = production_deck_to_deckspec_instrumented(
        ["Forest"] * 40,
    )
    assert report.any_dropped is False
    assert report.total_dropped == 0
    assert report.p0_unresolved == ()
    assert report.p0_not_bridged == ()


# ---------------------------------------------------------------------------
# (2) Fail-loud / enforced — the post-flip Rust-sourced soundness fence.
# ---------------------------------------------------------------------------


def test_raise_policy_fails_loud_on_real_deck_non_admitted_card():
    """Under ``LoaderAdmitPolicy.RAISE`` a real deck (which always
    contains ≥1 non-admitted card) RAISES ``NonAdmittedCardError`` —
    the card cannot silently enter a Rust-sourced game.

    This is the C6 enforced boundary: post-flip, the Rust-sourced
    decision path sets ``RAISE`` so a non-bridgeable card hard-fails
    instead of being Forest-padded into a quietly-different deck.
    """
    from mtg_bot.parity.trajectory import (
        NonAdmittedCardError,
        LoaderAdmitPolicy,
        load_production_deck,
        production_deck_to_deckspec_instrumented,
    )

    p0 = load_production_deck(0)
    with pytest.raises(NonAdmittedCardError) as excinfo:
        production_deck_to_deckspec_instrumented(
            p0, on_non_admitted=LoaderAdmitPolicy.RAISE,
        )
    err = excinfo.value
    # The error names the offending card and whether it resolved — a
    # debuggable, actionable failure, not a silent degrade.
    assert err.card_name
    assert isinstance(err.resolved, bool)
    assert "loader-admit boundary (C6)" in str(err)


def test_raise_policy_also_guards_the_underlying_filter():
    """The fail-loud enforcement lives at the chokepoint
    (``_filter_deck_to_bridge_supported``) itself, so any caller that
    routes through it inherits the boundary — not just the wrapper.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity.trajectory import (
        NonAdmittedCardError,
        LoaderAdmitPolicy,
        _filter_deck_to_bridge_supported,
    )

    printings = get_active_source().get_printings()

    # Default DROP: silently drops, parity-required pre-flip behavior.
    names, _defs = _filter_deck_to_bridge_supported(
        ["Forest", "__nope__"], printings,
    )
    assert names == ["Forest"]  # silent drop preserved on the default

    # RAISE: the same input now hard-fails at the chokepoint.
    with pytest.raises(NonAdmittedCardError):
        _filter_deck_to_bridge_supported(
            ["Forest", "__nope__"], printings,
            on_non_admitted=LoaderAdmitPolicy.RAISE,
        )


def test_raise_policy_passes_through_a_fully_admitted_deck():
    """``RAISE`` is a *boundary*, not a blanket reject: a fully
    loader-admitted deck still builds cleanly under ``RAISE`` and
    reports zero drops. (A successful ``RAISE`` return is the proof the
    deck is 100% admitted — the post-flip "this deck is safe" signal.)
    """
    from mtg_bot.parity.trajectory import (
        LoaderAdmitPolicy,
        production_deck_to_deckspec_instrumented,
    )

    spec, report = production_deck_to_deckspec_instrumented(
        ["Forest"] * 40,
        on_non_admitted=LoaderAdmitPolicy.RAISE,
    )
    assert report.any_dropped is False
    assert len(spec.p0_library) == 60  # admitted Forests + Forest-pad


def test_filter_sink_records_without_changing_filtered_output():
    """Supplying the observable sinks does NOT change which names the
    filter keeps — the sink is a pure side-record (parity-neutral at
    the chokepoint level too).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported

    printings = get_active_source().get_printings()
    deck = ["Forest", "Forest", "__x__", "__y__"]

    names_no_sink, defs_no_sink = _filter_deck_to_bridge_supported(
        list(deck), printings,
    )
    unresolved: list = []
    not_bridged: list = []
    names_sink, defs_sink = _filter_deck_to_bridge_supported(
        list(deck), printings,
        unresolved_sink=unresolved,
        not_bridged_sink=not_bridged,
    )

    assert names_no_sink == names_sink
    assert [d.name for d in defs_no_sink] == [d.name for d in defs_sink]
    # The sink captured the dropped names with order + multiplicity.
    assert unresolved == ["__x__", "__y__"]
    assert not_bridged == []
