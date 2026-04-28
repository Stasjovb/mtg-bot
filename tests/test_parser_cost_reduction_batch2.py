"""Batch-2 cost-reduction parser additions.

Extends ``mtg_bot.cards.parser.cost_reduction`` to recognize the
no-``if`` connector shape ``This spell costs {N} less to cast
<connector>.``. The closed connector list seeds with ``"during your
turn"`` (Mental Modulation), mapped to the engine condition
``during_your_turn`` newly wired in ``actions._evaluate_cost_reduction``.

The recognizer continues to accept the original ``...less to cast if
<condition>.`` shape with no behavioral change — these tests guard the
new connector path AND check the cross-table integrity (no condition
phrase appears on both whitelists).

Coverage targets:
  - The recognizer extracts the new ``during_your_turn`` rule from
    the no-``if`` shape with the right amount.
  - End-to-end Mental Modulation parses through ``_build_spell_
    printing`` with the new cost-reduction rule on the resulting
    printing.
  - The engine path (``_evaluate_cost_reduction``) reduces a cast cost
    by the rule amount when the caster is the active player and
    leaves it unchanged otherwise.
  - ``_detect_cost_reductions`` surfaces the no-``if`` rule the same
    way it surfaces ``if``-shape rules.
  - Integrity: connector phrase ``"during your turn"`` must NOT have
    crept onto the ``if``-shape whitelist (which would silently
    accept a malformed ``...less to cast if during your turn.``
    line); the two whitelists are disjoint by construction.
"""

from __future__ import annotations

import json
from pathlib import Path

from mtg_bot.actions import _evaluate_cost_reduction
from mtg_bot.cards.base import (
    CostReduction,
    DrawCards,
    ManaCost,
    Sequence,
    TapTargetArtifactOrCreature,
    make_instant,
)
from mtg_bot.cards.parser.cost_reduction import (
    _COST_REDUCTION_CONDITIONS,
    _COST_REDUCTION_CONDITIONS_NO_IF,
    _parse_cost_reduction_line,
)
from mtg_bot.cards.parser.spell_builder import (
    _build_spell_printing,
    _detect_cost_reductions,
)
from mtg_bot.cards.parser_source import OracleParserCardSource


_DATA_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "edge_of_eternities.json"
)


def _eoe_card(name: str) -> dict:
    with _DATA_PATH.open("r", encoding="utf-8") as f:
        for card in json.load(f):
            if card["name"] == name:
                return card
    raise LookupError(f"no EoE card named {name!r}")


# ---------- recognizer: no-``if`` connector shape ----------


def test_recognizer_extracts_during_your_turn():
    line = "This spell costs {1} less to cast during your turn."
    assert _parse_cost_reduction_line(line) == CostReduction(
        amount=1, condition="during_your_turn",
    )


def test_recognizer_extracts_during_your_turn_higher_amount():
    # Defensive — the regex captures any ``\d+`` amount, not just 1.
    # Synthetic since the only EoE printing ships at {1}.
    line = "This spell costs {3} less to cast during your turn."
    assert _parse_cost_reduction_line(line) == CostReduction(
        amount=3, condition="during_your_turn",
    )


def test_recognizer_handles_surrounding_whitespace_no_if_shape():
    line = "  This spell costs {1} less to cast during your turn.  "
    assert _parse_cost_reduction_line(line) == CostReduction(
        amount=1, condition="during_your_turn",
    )


# ---------- _detect_cost_reductions: integration ----------


def test_detect_cost_reductions_surfaces_during_your_turn():
    text = (
        "This spell costs {1} less to cast during your turn.\n"
        "Tap target artifact or creature.\n"
        "Draw a card."
    )
    assert _detect_cost_reductions(text) == (
        CostReduction(amount=1, condition="during_your_turn"),
    )


# ---------- end-to-end: Mental Modulation claim + parity ----------


def test_mental_modulation_now_claimed_with_during_your_turn_rider():
    card = _eoe_card("Mental Modulation")
    parsed = _build_spell_printing(card)
    assert parsed is not None
    assert parsed.name == "Mental Modulation"
    assert parsed.cost_reductions == (
        CostReduction(amount=1, condition="during_your_turn"),
    )
    # Body effect parses to the same Sequence the static side ships.
    assert parsed.spell_effect == Sequence(effects=(
        TapTargetArtifactOrCreature(),
        DrawCards(amount=1),
    ))




# ---------- engine: _evaluate_cost_reduction during_your_turn branch ----------


def _two_player_state():
    """Spin up a minimal two-player ``GameState`` whose active player
    is player 0. Mirrors the lightweight fixture used by other
    cost-reduction engine tests (e.g. ``tests/test_actions.py``)."""
    from mtg_bot.game import GameState, Player

    s = GameState()
    s.players.append(Player(id=0))
    s.players.append(Player(id=1))
    s.active_player_idx = 0
    return s


def test_during_your_turn_reduces_when_caster_is_active_player():
    s = _two_player_state()
    rule = CostReduction(amount=1, condition="during_your_turn")
    # Active player (id=0) is the caster: reduction applies.
    assert _evaluate_cost_reduction(rule, s, caster_id=0) == 1


def test_during_your_turn_no_reduction_when_caster_is_not_active():
    s = _two_player_state()
    rule = CostReduction(amount=1, condition="during_your_turn")
    # Caster is the non-active player (id=1): no reduction.
    assert _evaluate_cost_reduction(rule, s, caster_id=1) == 0


def test_apply_cost_reductions_threads_during_your_turn():
    # End-to-end through ``apply_cost_reductions`` — the rule must
    # reduce the generic-mana portion of a base cost when the caster
    # is the active player. Ensures the wiring between
    # ``CardPrinting.cost_reductions`` and the new engine branch is
    # intact (the per-rule branch test above is necessary but not
    # sufficient — a typo in the apply walker would slip through).
    from mtg_bot.actions import apply_cost_reductions

    parser_printing = (
        OracleParserCardSource().get_printings()["Mental Modulation"]
    )
    s = _two_player_state()
    base = ManaCost(generic=1, colored=(("U", 1),))
    reduced = apply_cost_reductions(parser_printing, s, caster_id=0, base_cost=base)
    assert reduced.generic == 0
    assert reduced.colored == (("U", 1),)
    # Opponent's turn: no discount.
    s.active_player_idx = 1
    unreduced = apply_cost_reductions(parser_printing, s, caster_id=0, base_cost=base)
    assert unreduced == base


# ---------- whitelist integrity ----------


def test_during_your_turn_only_on_no_if_table():
    # The two whitelists are disjoint — ``"during your turn"`` lives
    # only on the no-``if`` table, NOT on the ``if``-shape table.
    # Otherwise the recognizer's two regexes could both claim a
    # synthetic ``...less to cast if during your turn.`` line and
    # the precedence between them would matter; today the disjoint
    # invariant means precedence is moot.
    assert "during your turn" in _COST_REDUCTION_CONDITIONS_NO_IF
    assert "during your turn" not in _COST_REDUCTION_CONDITIONS


def test_no_if_table_keys_have_engine_condition_strings():
    # Defensive — every entry maps to a non-empty engine-condition
    # string (caught by the parity tests indirectly, but explicit
    # here so a typo localizes to this file).
    for phrase, key in _COST_REDUCTION_CONDITIONS_NO_IF.items():
        assert isinstance(key, str) and key, (
            f"phrase {phrase!r} maps to empty engine key {key!r}"
        )
