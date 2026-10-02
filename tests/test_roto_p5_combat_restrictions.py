"""Vintage Roto P5: combat restrictions -- Carrion Feeder ("This
creature can't block."), Ensnaring Bridge and Moat -- and the
board-rule plumbing in ``mtg_bot.roto_board_statics``."""

from __future__ import annotations

from mtg_bot.cards.demo_layers import BLOOD_MOON, HUMILITY
from mtg_bot.cards.parser.roto_board import (
    merge_board_fields,
    parse_roto_board_line,
)
from mtg_bot.combat import eligible_attackers, eligible_blockers
from mtg_bot.game import Zone
from mtg_bot.roto_board_statics import (
    CantAttack,
    CantBlock,
    PowerGreaterThanControllersHandSize,
    WithoutKeyword,
    abilities_suppressed,
    filter_attackers,
)
from tests._roto_p5_helpers import (
    activate,
    make_state,
    place,
    printing,
    vanilla,
)


def _line(text, name="Test Card"):
    return parse_roto_board_line(text, {"name": name})


# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------


def test_combat_line_grammar():
    moat = _line("Creatures without flying can't attack.")
    assert moat.fields["board_rules"] == (
        CantAttack(condition=WithoutKeyword("flying")),
    )
    bridge = _line(
        "Creatures with power greater than the number of cards in your "
        "hand can't attack."
    )
    assert bridge.fields["board_rules"] == (
        CantAttack(condition=PowerGreaterThanControllersHandSize()),
    )
    feeder = _line("This creature can't block.", name="Carrion Feeder")
    assert feeder.fields["board_rules"] == (CantBlock(self_only=True),)
    named = _line("Carrion Feeder can't block.", name="Carrion Feeder")
    assert named.fields["board_rules"] == (CantBlock(self_only=True),)
    assert _line("Creatures can't block.").fields["board_rules"] == (
        CantBlock(),
    )
    # Unknown conditions / a self rule with a condition stay unclaimed.
    assert _line("Creatures without gizmos can't attack.") is None
    assert _line("Creatures with power 3 or less can't attack.") is None
    assert _line("This creature without flying can't attack.") is None


def test_rule_descriptions():
    assert CantAttack(condition=WithoutKeyword("flying")).describe() == (
        "Creatures without flying can't attack."
    )
    assert CantBlock(self_only=True).describe() == "This creature can't block."
    assert "cards in your hand" in CantAttack(
        condition=PowerGreaterThanControllersHandSize()
    ).describe()


def test_board_rules_accumulate_across_lines():
    acc: dict = {}
    merge_board_fields(acc, {"board_rules": (CantBlock(self_only=True),)})
    merge_board_fields(acc, {"board_rules": (CantAttack(self_only=True),),
                             "other": 1})
    assert acc["board_rules"] == (
        CantBlock(self_only=True), CantAttack(self_only=True),
    )
    assert acc["other"] == 1


# ---------------------------------------------------------------------------
# Carrion Feeder
# ---------------------------------------------------------------------------


def test_carrion_feeder_cant_block_but_can_attack():
    state = make_state()
    feeder = place(state, 0, "Carrion Feeder")
    bear = place(state, 0, vanilla(2, 2))
    assert feeder not in eligible_blockers(state, 0)
    assert bear in eligible_blockers(state, 0)
    assert feeder in eligible_attackers(state, 0)


def test_carrion_feeder_grows_by_sacrificing_creatures():
    state = make_state()
    feeder = place(state, 0, "Carrion Feeder")
    bear = place(state, 0, vanilla(2, 2))
    state.players[0].agent.scripts["sacrifice"] = [bear.id]
    activate(state, 0, feeder)
    assert bear in state.players[0].graveyard
    assert feeder.plus_one_counters == 1


def test_creatures_losing_all_abilities_lose_the_block_restriction():
    state = make_state()
    feeder = place(state, 0, "Carrion Feeder")
    place(state, 1, HUMILITY)
    assert abilities_suppressed(state, feeder)
    assert feeder in eligible_blockers(state, 0)


def test_layer6_wipe_entry_suppresses_a_noncreature_source():
    state = make_state()
    moat = place(state, 0, "Moat")
    bear = place(state, 1, vanilla(2, 2))
    assert bear not in eligible_attackers(state, 1)
    state.add_continuous_effect(
        source_id=moat.id, layer=6, kind="lose_all_abilities",
        target_id=moat.id, description="test wipe",
    )
    assert abilities_suppressed(state, moat)
    assert bear in eligible_attackers(state, 1)


# ---------------------------------------------------------------------------
# Ensnaring Bridge
# ---------------------------------------------------------------------------


def test_ensnaring_bridge_uses_its_controllers_hand_size():
    state = make_state()
    place(state, 0, "Ensnaring Bridge")
    small = place(state, 1, vanilla(1, 1, name="Small"))
    big = place(state, 1, vanilla(3, 3, name="Big"))
    zero = place(state, 1, vanilla(0, 4, name="Wall-ish"))
    mine = place(state, 0, vanilla(2, 2, name="Mine"))
    # Bridge's controller has an empty hand: only power 0 may attack.
    assert eligible_attackers(state, 1) == [zero]
    assert eligible_attackers(state, 0) == []
    place(state, 0, "Island", Zone.HAND)
    assert eligible_attackers(state, 1) == [small, zero]
    place(state, 0, "Island", Zone.HAND)
    assert mine in eligible_attackers(state, 0)
    # The opponent's hand doesn't matter.
    for _ in range(5):
        place(state, 1, "Island", Zone.HAND)
    assert big not in eligible_attackers(state, 1)


# ---------------------------------------------------------------------------
# Moat
# ---------------------------------------------------------------------------


def test_moat_stops_creatures_without_flying():
    state = make_state()
    place(state, 0, "Moat")
    walker = place(state, 1, vanilla(2, 2, name="Walker"))
    flier = place(state, 1, vanilla(2, 2, name="Flier", keywords=frozenset({"flying"})))
    mine = place(state, 0, vanilla(2, 2, name="Mine"))
    assert eligible_attackers(state, 1) == [flier]
    assert eligible_attackers(state, 0) == []
    assert walker in eligible_blockers(state, 1)
    assert mine in eligible_blockers(state, 0)
    assert filter_attackers(state, []) == []


def test_blood_moon_strips_a_land_sources_board_rules():
    """CR 305.7: a nonbasic land under Blood Moon loses its rules-text
    abilities -- board rules included."""
    from dataclasses import replace

    state = make_state()
    gate = replace(
        printing("Wasteland"), name="Test Gate",
        board_rules=(CantAttack(),),
    )
    land = place(state, 0, gate)
    bear = place(state, 1, vanilla(2, 2))
    assert eligible_attackers(state, 1) == []
    place(state, 0, BLOOD_MOON)
    assert abilities_suppressed(state, land)
    assert eligible_attackers(state, 1) == [bear]
