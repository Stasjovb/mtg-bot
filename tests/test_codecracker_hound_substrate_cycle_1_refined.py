"""Codecracker Hound — refined Cycle 1 substrate pins (2026-05-24).

**Lane:** ``feature/codecracker-hound-cycle-1-refined-parser-fold-p1``.

The refined-Cycle-1 fold collapsed the prior bespoke
``LookAtTopTwoSplitHandGraveyard`` engine class into a parameterized
alias of ``LookTopNPutOneInHandRestToGraveyard(n=2,
reveal_chosen=False)``. This is the parser-CLAUDE-faithful path (b)
from ``docs/CODECRACKER_HOUND_CYCLE_1_HONEST_STOP_2026-05-24.md`` §6.

**What this module pins (substrate-only invariants).**

1. **Parser SoT.** The printed surface form "look at the top two
   cards of your library. Put one into your hand and the other into
   your graveyard" now parses to
   ``LookTopNPutOneInHandRestToGraveyard(n=2, reveal_chosen=False)``,
   NOT to a (deleted) ``LookAtTopTwoSplitHandGraveyard`` class.
2. **Reveal-flag fidelity.** The fold preserves Codecracker Hound's
   no-reveal observable via ``reveal_chosen=False``; Commune-with-
   Evil's parser path (which dispatches through the same primitive
   at n=4 via the more-specific gain-life recognizer) keeps
   ``reveal_chosen=True`` (default), preserving the prior reveal
   semantics.
3. **Cross-engine bridge round-trip stays stable.** The bridge arm
   dict ``{"kind": "look_top_n_put_one_in_hand_rest_to_graveyard",
   "n": 2}`` still yields a class instance equal to
   ``LookTopNPutOneInHandRestToGraveyard(n=2)`` (default
   ``reveal_chosen=True``) — the bridge dict shape was not widened
   in this cycle; the Codecracker Hound consumer of the bridge arm
   is gated out by the admit-set guardrail today (Cycle-2 work).
4. **Substrate-only admit-gate invariant (load-bearing for Cycle 2).**
   Codecracker Hound STAYS DECLINED at
   ``_printing_is_bridge_simple_spell`` post-fold. The refined
   Cycle-1 ships parser/engine surgery only; the admit-predicate
   widen + admit-set pin bump are Cycle-2 deliverables. If this
   assertion fails after Cycle 1, Cycle 1 has accidentally widened
   the gate — that's a scope-creep regression to investigate.
5. **Class deletion pin.** The prior ``LookAtTopTwoSplitHandGraveyard``
   name is no longer exported from ``mtg_bot.effects`` (or any of
   the re-export surfaces). The deletion is permanent and
   regression-guarded here.
"""

from __future__ import annotations

import pytest


def test_parser_codecracker_surface_folds_to_parameterized_primitive():
    """Pin #1 — parser SoT. Codecracker Hound's two-sentence printed
    surface parses to the parameterized primitive at ``n=2`` with
    ``reveal_chosen=False`` (the refined-Cycle-1 fold)."""
    from mtg_bot.cards.parser.effects import _parse_effect
    from mtg_bot.effects.generic.library_lookat import (
        LookTopNPutOneInHandRestToGraveyard,
    )

    parsed = _parse_effect(
        "look at the top two cards of your library. "
        "Put one into your hand and the other into your graveyard"
    )
    assert parsed == LookTopNPutOneInHandRestToGraveyard(
        n=2, reveal_chosen=False,
    ), (
        f"Codecracker Hound surface form must parse to "
        f"LookTopNPutOneInHandRestToGraveyard(n=2, "
        f"reveal_chosen=False); got {parsed!r}"
    )


def test_commune_with_evil_parser_path_keeps_reveal_chosen_true():
    """Pin #2 — reveal-flag fidelity (back-compat). The parser's
    Commune-with-Evil three-sentence path (``_LOOK_TOP_N_PUT_ONE_IN_
    HAND_REST_TO_GRAVEYARD_GAIN_M_LIFE``) emits a Sequence whose
    look-pick-split leaf uses the DEFAULT ``reveal_chosen=True`` —
    preserving the prior reveal_to_all observable for n=4 consumers
    that flow through this parser path (NOT the bespoke
    CommuneWithEvilEffect static-registry path)."""
    from mtg_bot.cards.parser.effects import _parse_effect
    from mtg_bot.effects.generic.library_lookat import (
        LookTopNPutOneInHandRestToGraveyard,
    )
    from mtg_bot.effects import GainLife, Sequence

    parsed = _parse_effect(
        "look at the top four cards of your library. "
        "Put one of them into your hand and the rest into your graveyard. "
        "You gain 3 life"
    )
    assert parsed == Sequence(effects=(
        LookTopNPutOneInHandRestToGraveyard(n=4),  # default reveal_chosen=True
        GainLife(amount=3),
    )), (
        f"Commune-with-Evil parser path must produce a Sequence with "
        f"reveal_chosen=True (default) at the n=4 leaf; got {parsed!r}"
    )


def test_bridge_arm_round_trips_through_default_reveal_chosen():
    """Pin #3 — cross-engine bridge round-trip. The bridge arm at
    ``cross_engine.py`` translates the Rust dict shape to the Python
    primitive with the default ``reveal_chosen=True`` (the bridge
    dict shape was NOT widened to carry the flag — substrate-only
    invariant). The Codecracker Hound n=2 consumer of this bridge
    arm is gated out by the admit-set guardrail today (Cycle-2
    flips that gate)."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.effects.generic.library_lookat import (
        LookTopNPutOneInHandRestToGraveyard,
    )

    rt_n2 = _ta_dict_to_python_effect({
        "kind": "look_top_n_put_one_in_hand_rest_to_graveyard", "n": 2,
    })
    assert rt_n2 == LookTopNPutOneInHandRestToGraveyard(n=2), (
        f"Bridge n=2 round-trip must produce default-flag instance; "
        f"got {rt_n2!r}"
    )
    # reveal_chosen=True is the default; assert it explicitly so a
    # future bridge-arm widen that flips the default to False is caught.
    assert rt_n2.reveal_chosen is True

    rt_n4 = _ta_dict_to_python_effect({
        "kind": "look_top_n_put_one_in_hand_rest_to_graveyard", "n": 4,
    })
    assert rt_n4 == LookTopNPutOneInHandRestToGraveyard(n=4), (
        f"Bridge n=4 round-trip must produce default-flag instance; "
        f"got {rt_n4!r}"
    )


def test_codecracker_hound_stays_declined_post_refined_cycle_1():
    """Pin #4 — substrate-only admit-gate invariant (LOAD-BEARING
    closure marker for Cycle 2).

    The refined Cycle-1 ships parser/engine surgery only. Codecracker
    Hound STAYS DECLINED at ``_printing_is_bridge_simple_spell``
    post-fold. The admit-predicate widen + admit-set pin bump are
    Cycle-2 deliverables (will flip warp_cost + nonsafe_triggered_
    ability gates to admit Codecracker Hound — that's the load-
    bearing pre-condition for the Cycle-3 real-EoE byte-equality
    probe to even be reachable).

    If this assertion FAILS post-Cycle-1, the Cycle-1 fold has
    accidentally widened the admit gate — that's a scope-creep
    regression to investigate before the Cycle-2 lane lands.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    cc = src.get("Codecracker Hound")
    if cc is None:
        pytest.skip("Codecracker Hound absent from active CardSource")
    assert trajectory._printing_is_bridge_simple_spell(cc) is False, (
        "Codecracker Hound MUST stay DECLINED at the bridge admit "
        "gate post-refined-Cycle-1 (substrate-only invariant). The "
        "admit-predicate widen + admit-set pin bump are Cycle-2 "
        "work — a True here means the gate widened ahead of schedule."
    )


def test_look_at_top_two_split_hand_graveyard_class_is_deleted():
    """Pin #5 — class-deletion regression guard. The prior bespoke
    ``LookAtTopTwoSplitHandGraveyard`` engine class was deleted in
    the refined-Cycle-1 fold; the name must no longer resolve from
    any of the canonical re-export surfaces."""
    import mtg_bot.effects as effects_pkg
    import mtg_bot.effects.generic as generic_pkg
    import mtg_bot.effects.generic.library_lookat as lookat_mod
    import mtg_bot.cards.base as cards_base

    for mod, label in (
        (effects_pkg, "mtg_bot.effects"),
        (generic_pkg, "mtg_bot.effects.generic"),
        (lookat_mod, "mtg_bot.effects.generic.library_lookat"),
        (cards_base, "mtg_bot.cards.base"),
    ):
        assert not hasattr(mod, "LookAtTopTwoSplitHandGraveyard"), (
            f"{label} must NOT re-export the deleted "
            f"LookAtTopTwoSplitHandGraveyard class post-refined-"
            f"Cycle-1 fold"
        )
