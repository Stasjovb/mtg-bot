"""Codecracker Hound — Cycle 1 (refined) + Cycle 2 substrate pins.

**Lanes (composite).**
 * **Cycle 1 (refined):** ``feature/codecracker-hound-cycle-1-refined-
   parser-fold-p1`` (commit ``bd37cca0``, 2026-05-24).
 * **Cycle 2 (this lane):** ``feature/codecracker-hound-cycle-2-admit-
   widen-p1`` (2026-05-24).

The refined-Cycle-1 fold collapsed the prior bespoke
``LookAtTopTwoSplitHandGraveyard`` engine class into a parameterized
alias of ``LookTopNPutOneInHandRestToGraveyard(n=2,
reveal_chosen=False)``. This is the parser-CLAUDE-faithful path (b)
from ``docs/CODECRACKER_HOUND_CYCLE_1_HONEST_STOP_2026-05-24.md`` §6.

Cycle 2 widens ``_python_ta_to_safe_dict`` to admit the 9th
ENTERS+IsSelf leaf (``look_top_n_put_one_in_hand_rest_to_graveyard``),
threads ``reveal_chosen`` through the bridge dict shape (Codecracker
Hound's no-reveal observable preserved cross-engine via the recognizer
gate ``eff.reveal_chosen == False``), and flips
``_printing_is_bridge_pure_warp_creature(Codecracker Hound) DECLINED →
ADMITTED``. The Cycle-1 substrate-only invariant pin
``test_codecracker_hound_stays_declined_post_refined_cycle_1`` was
INVERTED to ``test_codecracker_hound_now_admits_at_admit_gate_post_
cycle_2`` (this slice). Cycle 3 ships the per-card real-EoE
byte-equality probe under both warp-cast and normal-cast lifecycles.

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
3. **Cross-engine bridge round-trip (Cycle 2 widen).** The bridge arm
   dict ``{"kind": "look_top_n_put_one_in_hand_rest_to_graveyard",
   "n": 2, "reveal_chosen": False}`` yields a class instance equal to
   ``LookTopNPutOneInHandRestToGraveyard(n=2, reveal_chosen=False)``
   — the bridge now threads the rider so a safe-trigger admit (the
   Codecracker Hound consumer) round-trips byte-equal across engines.
   A dict omitting ``reveal_chosen`` (the prior Commune-with-Evil-
   default n=4 consumer path) keeps the back-compat default of
   ``reveal_chosen=True`` for legacy producers, so no prior bridge
   consumer regresses.
4. **Admit-gate invariant (Cycle-2 FLIP).** Codecracker Hound is now
   ADMITTED at ``_printing_is_bridge_pure_warp_creature`` (its
   structural admit gate as a warp creature — the warp arm, not the
   plain simple-creature arm, is the load-bearing admit path). The
   inversion from Cycle-1's "stays declined" invariant is load-
   bearing: it makes Codecracker Hound reachable by the Cycle-3
   real-EoE byte-equality probe.
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
    """Pin #3 — cross-engine bridge round-trip (Cycle-2 widen, with
    back-compat).

    The Cycle-2 widen threads ``reveal_chosen`` through the bridge
    dict shape. A dict explicitly carrying ``"reveal_chosen": False``
    (the safe-trigger emit shape for Codecracker Hound, n=2)
    reconstructs the Python instance with the matching flag; a dict
    OMITTING the field (the legacy Commune-with-Evil-default n=4
    producer path, which never threaded the flag) keeps the prior
    default ``reveal_chosen=True`` — back-compat for prior consumers.
    The §2 silent-mistranslation teeth live in
    ``_python_ta_to_safe_dict`` (it gates on ``eff.reveal_chosen ==
    False`` and emits the flag into the dict), NOT in the bridge.
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.effects.generic.library_lookat import (
        LookTopNPutOneInHandRestToGraveyard,
    )

    # Cycle-2: dict with ``reveal_chosen=False`` threads the flag through.
    rt_n2_no_reveal = _ta_dict_to_python_effect({
        "kind": "look_top_n_put_one_in_hand_rest_to_graveyard",
        "n": 2, "reveal_chosen": False,
    })
    assert rt_n2_no_reveal == LookTopNPutOneInHandRestToGraveyard(
        n=2, reveal_chosen=False,
    ), (
        f"Bridge n=2 round-trip with reveal_chosen=False must produce "
        f"the matching no-reveal instance; got {rt_n2_no_reveal!r}"
    )
    assert rt_n2_no_reveal.reveal_chosen is False

    # Back-compat: dict without ``reveal_chosen`` field defaults to True
    # (the legacy Commune-with-Evil-default n=4 producer never threaded
    # the flag; preserve the prior round-trip semantics for those
    # consumers).
    rt_n4 = _ta_dict_to_python_effect({
        "kind": "look_top_n_put_one_in_hand_rest_to_graveyard", "n": 4,
    })
    assert rt_n4 == LookTopNPutOneInHandRestToGraveyard(n=4), (
        f"Bridge n=4 round-trip without reveal_chosen must produce "
        f"default-flag instance; got {rt_n4!r}"
    )
    assert rt_n4.reveal_chosen is True


def test_codecracker_hound_now_admits_at_admit_gate_post_cycle_2():
    """Pin #4 — admit-gate INVARIANT FLIP (Cycle-2 load-bearing closure
    marker).

    The Cycle-2 admit-widen flips Codecracker Hound DECLINED → ADMITTED
    at its structural admit gate ``_printing_is_bridge_pure_warp_
    creature`` (the warp arm — Codecracker Hound is a Creature with
    ``warp_cost``, NOT a spell, so the spell-card-bridge gate
    ``_printing_is_bridge_simple_spell`` is the WRONG gate; the C1 pin
    that asserted ``_printing_is_bridge_simple_spell is False`` was
    trivially true because that predicate filters all creatures out at
    line 6142-6143, and is preserved here only as a defensive cross-
    check). Both ``_printing_is_bridge_pure_warp_creature`` AND the
    spell-card-bridge gate are pinned: the warp arm FLIPS True (the
    load-bearing flip); the spell-card-bridge gate STAYS False
    (creature-side; Cycle 2 did not touch the spell arm).

    The flip is driven by the Cycle-2 widen to ``_python_ta_to_safe_
    dict`` (the 9th ENTERS+IsSelf leaf
    ``look_top_n_put_one_in_hand_rest_to_graveyard``) + the matching
    ``_SAFE_TRIGGERS`` entry + the matching ``_SAFE_EFFECT_KEYS`` key-
    whitelist + the bridge-arm ``reveal_chosen`` thread. With CH's
    ETB trigger now classified as safe, the warp arm's
    ``nonsafe_triggered_ability`` gate closes and the warp arm admits.

    If this assertion FAILS post-Cycle-2, the Cycle-2 widen regressed
    — either the safe-set entry was dropped, the ``reveal_chosen=False``
    gate inverted, or the warp arm's logic drifted; investigate before
    further Cycle-3 work depends on this admit state.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    cc = src.get("Codecracker Hound")
    if cc is None:
        pytest.skip("Codecracker Hound absent from active CardSource")
    # The Cycle-2 FLIP — the warp arm now admits Codecracker Hound.
    assert trajectory._printing_is_bridge_pure_warp_creature(cc) is True, (
        "Codecracker Hound MUST be ADMITTED at the warp creature "
        "admit gate post-Cycle-2. A False here means the Cycle-2 "
        "widen regressed — either the 9th ENTERS+IsSelf leaf entry "
        "was dropped from _SAFE_TRIGGERS / _SAFE_EFFECT_KEYS / "
        "_python_ta_to_safe_dict, or the warp arm's logic drifted."
    )
    # Defensive cross-check: the spell-card-bridge gate stays False
    # (CH is a Creature; this gate filters creatures by construction).
    assert trajectory._printing_is_bridge_simple_spell(cc) is False, (
        "Codecracker Hound is a Creature — the spell-card-bridge "
        "gate must continue to filter it out at the creature-type "
        "check; if this asserts True, Cycle-2 has accidentally "
        "widened the spell arm too."
    )
    # The plain simple-creature arm stays False — CH has warp_cost,
    # which the simple-creature arm positively rejects (line 4127);
    # the warp arm is the LOAD-BEARING admit path. This mirrors the
    # ``test_probe_warp_admitted`` ``_verify_warp_admitted`` discipline.
    assert (
        trajectory._printing_is_bridge_simple_creature(cc) is False
    ), (
        "The plain simple-creature arm must continue to reject "
        "Codecracker Hound (warp_cost trips it); the warp arm is "
        "the load-bearing admit path."
    )


def test_codecracker_hound_safe_trigger_round_trips():
    """Pin #4b — Cycle-2 safe-trigger round-trip (the recognizer +
    dict-side gate composition).

    Codecracker Hound's parsed ETB trigger (ENTERS+IsSelf+
    LookTopNPutOneInHandRestToGraveyard(n=2, reveal_chosen=False))
    round-trips byte-equal through the
    ``_python_ta_to_safe_dict`` → ``_is_safe_trigger_dict`` →
    ``cross_engine._ta_dict_to_python_effect`` chain. The emitted dict
    shape carries the ``reveal_chosen=False`` rider (the load-bearing
    §2 silent-mistranslation gate — Rust never reveals, so admitting a
    ``reveal_chosen=True`` instance would diverge on the post-resolve
    ``publicly_known_to`` observable).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.effects.generic.library_lookat import (
        LookTopNPutOneInHandRestToGraveyard,
    )

    src = get_active_source().get_printings()
    cc = src.get("Codecracker Hound")
    if cc is None:
        pytest.skip("Codecracker Hound absent from active CardSource")
    (ta,) = cc.triggered_abilities
    d = trajectory._python_ta_to_safe_dict(ta)
    assert d == {
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {
            "kind": "look_top_n_put_one_in_hand_rest_to_graveyard",
            "n": 2,
            "reveal_chosen": False,
        },
    }, f"Safe-dict emit shape regressed; got {d!r}"
    assert trajectory._is_safe_trigger_dict(d), (
        "Emitted safe-dict must satisfy the dict-side gate "
        "(_is_safe_trigger_dict); see _SAFE_EFFECT_KEYS whitelist."
    )
    # Bridge round-trip: dict → Python class with reveal_chosen=False.
    rt = _ta_dict_to_python_effect(d["effect"])
    assert rt == LookTopNPutOneInHandRestToGraveyard(
        n=2, reveal_chosen=False,
    ), f"Bridge round-trip diverged from parser-emitted effect; got {rt!r}"
    assert rt == ta.effect


def test_python_ta_to_safe_dict_rejects_reveal_chosen_true():
    """Pin #4c — §2 silent-mistranslation teeth: a synthetic ENTERS+
    IsSelf trigger carrying ``LookTopNPutOneInHandRestToGraveyard(n=2,
    reveal_chosen=True)`` is REJECTED by the recognizer.

    Rust's resolve at ``state_ops_resolve.rs:6366-6394`` never
    reveals; admitting a ``reveal_chosen=True`` instance would
    silently mistranslate the post-resolve ``publicly_known_to``
    observable across engines (Python's ``reveal_to_all`` rider sets
    it; Rust leaves it unchanged). The recognizer gate is the §2
    teeth — distinct from the dict-side ``_is_safe_trigger_dict``
    gate (which validates the dict's KEY whitelist but NOT the
    Python-side rider value). A future EoE / standard-format
    printing parser-emitting a ``reveal_chosen=True`` ETB would stay
    DECLINED here until the bridge gains the matching Rust-side
    reveal step (out of scope today).
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.library_lookat import (
        LookTopNPutOneInHandRestToGraveyard,
    )
    from mtg_bot.parity.trajectory import _python_ta_to_safe_dict

    ta = TriggeredAbility(
        event=Event.ENTERS,
        predicate=IsSelf(),
        effect=LookTopNPutOneInHandRestToGraveyard(n=2, reveal_chosen=True),
    )
    assert _python_ta_to_safe_dict(ta) is None, (
        "A reveal_chosen=True trigger must be REJECTED by the "
        "safe-trigger recognizer (Rust never reveals — admitting "
        "would silently mistranslate publicly_known_to)."
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
