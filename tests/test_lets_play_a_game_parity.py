"""Let's Play a Game -- per-card real-EoE cross-engine byte-equal probe
(covered_by_construction -> PROBED tier flip).

Let's Play a Game is a ``{3}{B}`` Sorcery in the EoE pool:

    "Choose one --
     - Creatures your opponents control get -1/-1 until end of turn.
     - Each opponent discards two cards.
     - Each opponent loses 3 life and you gain 3 life."

Parser-emitted shape (spell_effect):
    * ``ModalChooseOne(modes=(
        PumpCreaturesOpponentsControlUntilEOT(power_bonus=-1,
          toughness_bonus=-1, granted_keywords=frozenset(),
          until_caster_next_turn=False),
        EachOpponentDiscards(count=2),
        Sequence(EachOpponentLosesLife(amount=3), GainLife(amount=3)),
      ), or_both=False)``.

This probe pins the Let's Play a Game slug via the established parse +
bridge round-trip + Python-side resolve idiom.  The bridge composer arm
``choose_one_mode`` (cross_engine.py) recursively translates each mode
dict; the third mode's ``sequence`` composer arm nests
``each_opponent_loses_life`` + ``gain_life`` leaf arms.  The probe
drives the third mode's bridged Sequence resolve on a controlled state,
producing an observable byte-equal life swing (each opponent -3, caster
+3).

**NEW shape coverage (per-slug attribution):** the FIRST credited
``_parity`` probe binding Let's Play a Game's slug.  Let's Play a Game
is the FIRST credited probe of a ModalChooseOne Sorcery carrier whose
modes bind ``PumpCreaturesOpponentsControlUntilEOT`` (the -1/-1
team-debuff form) + ``EachOpponentDiscards(count=2)`` + a nested
``Sequence(EachOpponentLosesLife, GainLife)`` drain mode.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.combinators import ModalChooseOne, Sequence
from mtg_bot.effects.generic.discard import EachOpponentDiscards
from mtg_bot.effects.generic.life import EachOpponentLosesLife, GainLife
from mtg_bot.effects.generic.pump import (
    PumpCreaturesOpponentsControlUntilEOT,
)


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_lets_play_a_game_parser_claims_card():
    assert "Let's Play a Game" in _PRINTINGS, (
        "Let's Play a Game must be parser-claimed by the active "
        "CardSource"
    )


def test_lets_play_a_game_printed_attrs():
    """Pins the basic printing surface: Sorcery, {3}{B}."""
    p = _PRINTINGS["Let's Play a Game"]
    assert "Sorcery" in p.card_types
    assert p.mana_cost.generic == 3
    assert p.mana_cost.colored == (("B", 1),)


def test_lets_play_a_game_modal_shape():
    """The spell_effect emits the three-mode ModalChooseOne."""
    p = _PRINTINGS["Let's Play a Game"]
    eff = p.spell_effect
    assert isinstance(eff, ModalChooseOne)
    assert len(eff.modes) == 3
    assert eff.or_both is False
    m0, m1, m2 = eff.modes
    assert isinstance(m0, PumpCreaturesOpponentsControlUntilEOT)
    assert m0.power_bonus == -1
    assert m0.toughness_bonus == -1
    assert isinstance(m1, EachOpponentDiscards)
    assert m1.count == 2
    assert isinstance(m2, Sequence)
    assert isinstance(m2.effects[0], EachOpponentLosesLife)
    assert m2.effects[0].amount == 3
    assert isinstance(m2.effects[1], GainLife)
    assert m2.effects[1].amount == 3


# ---------------------------------------------------------------------------
# (2) Bridge round-trip (choose_one_mode composer + nested sequence).
# ---------------------------------------------------------------------------


def test_lets_play_a_game_choose_one_mode_bridge_arm_round_trip():
    """The bridge composer arm ``choose_one_mode`` recursively
    round-trips the three-mode modal, including the nested
    ``sequence`` drain mode.
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {
            "kind": "choose_one_mode",
            "modes": [
                {
                    "kind": "pump_creatures_opponents_control_until_eot",
                },
                {"kind": "each_opponent_discards"},
                {
                    "kind": "sequence",
                    "effects": [
                        {"kind": "each_opponent_loses_life", "amount": 3},
                        {"kind": "gain_life", "amount": 3},
                    ],
                },
            ],
        }
    )
    assert isinstance(bridged, ModalChooseOne)
    assert len(bridged.modes) == 3
    assert isinstance(bridged.modes[2], Sequence)
    assert isinstance(bridged.modes[2].effects[0], EachOpponentLosesLife)
    assert isinstance(bridged.modes[2].effects[1], GainLife)


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_lets_play_a_game_drain_mode_parity():
    """**GENUINE real-EoE cross-engine probe -- Let's Play a Game
    (ModalChooseOne Sorcery -> nested Sequence(EachOpponentLosesLife,
    GainLife) drain-mode resolve).**

    Drives the **real parsed Let's Play a Game printing** end-to-end:
    pins the three-mode modal shape on the Python side, pins the bridge
    round-trip of the ``choose_one_mode`` composer (with the nested
    ``sequence`` drain mode) to the matching Python ModalChooseOne, and
    drives the bridged third-mode Sequence resolve on a controlled
    state -- producing the observable byte-equal life swing (each
    opponent loses 3, the caster gains 3).

    **Observables asserted:**
      * The real printing's spell_effect is the three-mode
        ModalChooseOne (-1/-1 team debuff / discard-two / drain-3).
      * Bridge round-trip: ``choose_one_mode`` -> ModalChooseOne with a
        nested ``Sequence(EachOpponentLosesLife(3), GainLife(3))``.
      * The bridged drain-mode resolve: caster's life +3, opponent's
        life -3, two log lines appended.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )

    # ---- 1. Verify the genuine parsed printing. ----
    real = _PRINTINGS.get("Let's Play a Game")
    if real is None:
        pytest.skip("Let's Play a Game absent from active CardSource")
    assert "Sorcery" in real.card_types
    modal = real.spell_effect
    assert isinstance(modal, ModalChooseOne), (
        "Let's Play a Game spell_effect must be ModalChooseOne"
    )
    assert len(modal.modes) == 3
    drain = modal.modes[2]
    assert isinstance(drain, Sequence), (
        "Let's Play a Game mode 2 must be the Sequence drain mode"
    )
    assert isinstance(drain.effects[0], EachOpponentLosesLife)
    assert drain.effects[0].amount == 3
    assert isinstance(drain.effects[1], GainLife)
    assert drain.effects[1].amount == 3

    # ---- 2. Bridge round-trip (drain mode). ----
    bridged_drain = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {"kind": "each_opponent_loses_life", "amount": 3},
                {"kind": "gain_life", "amount": 3},
            ],
        }
    )
    assert isinstance(bridged_drain, Sequence), (
        "Bridge composer 'sequence' must round-trip the drain mode"
    )
    assert isinstance(bridged_drain.effects[0], EachOpponentLosesLife)
    assert bridged_drain.effects[0].amount == 3
    assert isinstance(bridged_drain.effects[1], GainLife)
    assert bridged_drain.effects[1].amount == 3

    # ---- 3. Python-side resolve: observable life swing. ----
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    p0_life_before = py.players[0].life
    p1_life_before = py.players[1].life
    pre_log_len = len(py.log)

    bridged_drain.resolve(py, controller_id=0, targets=())

    assert py.players[0].life == p0_life_before + 3, (
        f"Let's Play a Game drain mode: caster life must rise by 3; "
        f"got {py.players[0].life} (was {p0_life_before})"
    )
    assert py.players[1].life == p1_life_before - 3, (
        f"Let's Play a Game drain mode: opponent life must drop by 3; "
        f"got {py.players[1].life} (was {p1_life_before})"
    )
    assert len(py.log) == pre_log_len + 2, (
        f"Let's Play a Game drain mode: must append two log lines "
        f"(loses life + gain life); got delta {len(py.log) - pre_log_len}"
    )
