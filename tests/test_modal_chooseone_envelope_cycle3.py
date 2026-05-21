"""ModalChooseOne envelope — Cycle 3 (reverse serializer).

Spec: `docs/SEARCH_LIMITATIONS.md` "Spell-card-bridge — `ModalChooseOne`
envelope is a multi-round substrate effort" entry. This module covers
**Cycle 3 (partial)** of the 6-slice plan: the
`_python_spell_effect_to_dict` reverse-serializer arm for
`ModalChooseOne`.

**Cycle 3 scope (substrate-only).** Adds the composer arm so a
``ModalChooseOne(modes=...)`` Python spell-effect round-trips to its
Rust ``{"kind": "choose_one_mode", "modes": [...]}`` dict — recursing
into each mode via the existing ``_leaf`` table, bailing if ANY mode
is unrecognized (the round-trip-or-bail teeth, same shape as the
``Sequence`` composer).

**`or_both` deferral.** Bail on ``or_both=True`` explicitly — Cycle 1's
``StackItem.chosen_mode_idx: Option<u8>`` carries a single pick; the
or_both variant needs an ordered list of picks (a future cycle widens
the field).

**Cycle 3 does NOT widen the admit predicate.** ``_printing_is_bridge_
simple_spell`` still positively rejects ``ModalChooseOne`` at line
4444 (the substrate-only landing). The reverse serializer is forward
substrate for the day per-leaf Effect arms (Ruinous Rampage's
``DealDamageToEachOpponent``, Split Up's ``DestroyAllTapped/
UntappedCreatures``, Let's Play a Game's drain/discard) land in the
``_leaf`` table — at which point the admit-set widen can flip those
cards into the bench (auto-grow). Today, NO EoE modal card has all
its modes ``_leaf``-recognized, so no card moves into the admit set
yet — the serializer ships in isolation to unblock future per-leaf
slices.

**Cross-engine probe (Cycle 6).** Deferred until at least one EoE
modal card has all-leaf-recognized modes AND the admit predicate
flip lands. Today the Cycle 3 substrate is tested via the
serializer's direct call.
"""

from __future__ import annotations

import pytest


def test_serializer_emits_choose_one_mode_dict_for_recognized_modes():
    """A ``ModalChooseOne`` whose modes are all in the ``_leaf`` table
    serializes to the canonical Rust ``{"kind": "choose_one_mode",
    "modes": [...]}`` shape.

    Driver: a synthetic ``ModalChooseOne(modes=(GainLife(3),
    GainLife(7)))`` — both modes are ``GainLife`` which IS on the
    ``_leaf`` table at ``trajectory.py:4131``. Each mode round-trips
    to its ``gain_life`` dict.
    """
    from mtg_bot.effects.combinators import ModalChooseOne
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    eff = ModalChooseOne(modes=(GainLife(amount=3), GainLife(amount=7)))
    d = _python_spell_effect_to_dict(eff)
    assert d is not None
    assert d == {
        "kind": "choose_one_mode",
        "modes": [
            {"kind": "gain_life", "amount": 3},
            {"kind": "gain_life", "amount": 7},
        ],
    }


def test_serializer_bails_when_any_mode_is_unrecognized():
    """Round-trip-or-bail teeth: a ``ModalChooseOne`` where ANY mode
    is not in the ``_leaf`` table returns ``None``. Drives the
    no-fallback-hybrid discipline — a partially-serializable modal
    spell would silently drop the unrecognized mode on Rust.

    Driver: mix a recognized ``GainLife`` mode with an unrecognized
    ``DrawCards`` mode (DrawCards is NOT on the ``_leaf`` pid-free-
    covered table today). The serializer must bail.
    """
    from mtg_bot.effects.combinators import ModalChooseOne
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.effects import DrawCards
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    eff = ModalChooseOne(modes=(GainLife(amount=3), DrawCards(amount=1)))
    d = _python_spell_effect_to_dict(eff)
    assert d is None


def test_serializer_bails_on_or_both():
    """``or_both=True`` is explicitly deferred — Cycle 1's
    ``chosen_mode_idx: Option<u8>`` only carries a single pick.
    Admitting an ``or_both`` modal would diverge on the multi-pick
    semantics. Bail at the serializer to prevent the admit
    predicate from accidentally bench-admitting it later.
    """
    from mtg_bot.effects.combinators import ModalChooseOne
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    eff = ModalChooseOne(
        modes=(GainLife(amount=3), GainLife(amount=7)),
        or_both=True,
    )
    d = _python_spell_effect_to_dict(eff)
    assert d is None


def test_serializer_handles_three_mode_spell():
    """A 3-mode ``ModalChooseOne`` with all recognized modes
    serializes to a 3-element ``modes`` list — the loop scales
    arity-cleanly.
    """
    from mtg_bot.effects.combinators import ModalChooseOne
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    eff = ModalChooseOne(
        modes=(
            GainLife(amount=1),
            GainLife(amount=2),
            GainLife(amount=3),
        ),
    )
    d = _python_spell_effect_to_dict(eff)
    assert d is not None
    assert d["kind"] == "choose_one_mode"
    assert len(d["modes"]) == 3
    assert d["modes"][0]["amount"] == 1
    assert d["modes"][1]["amount"] == 2
    assert d["modes"][2]["amount"] == 3


def test_serializer_round_trips_through_bridge():
    """End-to-end: a recognized ``ModalChooseOne`` Python effect →
    `_python_spell_effect_to_dict` → ``_ta_dict_to_python_effect`` →
    a structurally-equivalent ``ModalChooseOne``. This is the
    bidirectional bridge invariant.
    """
    from mtg_bot.effects.combinators import ModalChooseOne
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    src = ModalChooseOne(
        modes=(GainLife(amount=3), GainLife(amount=7)),
    )
    d = _python_spell_effect_to_dict(src)
    assert d is not None
    rt = _ta_dict_to_python_effect(d)
    assert isinstance(rt, ModalChooseOne)
    assert len(rt.modes) == 2
    assert all(isinstance(m, GainLife) for m in rt.modes)
    assert rt.modes[0].amount == 3
    assert rt.modes[1].amount == 7
    assert rt.or_both is False


# ---------------------------------------------------------------------------
# Admit predicate is UNCHANGED (substrate-only landing)
# ---------------------------------------------------------------------------


def test_admit_predicate_still_rejects_modal_spells():
    """**Substrate-only landing pin.** Cycle 3 ships only the
    reverse serializer — the admit predicate at
    ``trajectory.py:4444`` still positively rejects every
    ``ModalChooseOne`` spell. Cycle 5 will widen the predicate
    once enough per-leaf modes land to make the auto-grow viable.

    Driver: use Ruinous Rampage (a real EoE ``ModalChooseOne`` whose
    modes are all untargeted — the natural Cycle-5 admit candidate
    once its per-leaf effects land). The predicate's modal reject
    runs at line 4444 and refuses regardless of any other condition.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity.trajectory import _printing_is_bridge_simple_spell

    prs = get_active_source().get_printings()
    p = prs["Ruinous Rampage"]
    # The admit predicate still rejects it (Cycle 5 deferred —
    # substrate-only landing).
    assert _printing_is_bridge_simple_spell(p) is False
    # Sanity: Reroute Systems too (the lane-V honest-stop card).
    rr = prs["Reroute Systems"]
    assert _printing_is_bridge_simple_spell(rr) is False
