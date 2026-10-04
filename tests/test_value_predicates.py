"""Characteristic-value object predicates
(:mod:`mtg_bot.effects.value_predicates`)."""

from __future__ import annotations

from mtg_bot.effects.value_predicates import (
    HasColor,
    HasManaValueAtMost,
    HasTotalPowerAndToughnessAtMost,
    IsPermanent,
    mana_value_of,
)

from tests._spells_a_helpers import new_game, put


def test_is_permanent_rejects_players():
    state = new_game()
    elf = put(state, "Llanowar Elves")
    assert IsPermanent().test(elf, state)
    assert not IsPermanent().test(state.players[0], state)


def test_mana_value_at_most():
    state = new_game()
    griselbrand = put(state, "Griselbrand")  # {4}{B}{B}{B}{B}
    elf = put(state, "Llanowar Elves")
    assert mana_value_of(griselbrand) == 8
    assert HasManaValueAtMost(8).test(griselbrand, state)
    assert not HasManaValueAtMost(7).test(griselbrand, state)
    assert HasManaValueAtMost(1).test(elf, state)
    assert not HasManaValueAtMost(3).test(state.players[1], state)


def test_has_color_reads_effective_colors():
    state = new_game()
    elf = put(state, "Llanowar Elves")
    sol_ring = put(state, "Sol Ring")
    assert HasColor("G").test(elf, state)
    assert not HasColor("B").test(elf, state)
    assert (~HasColor("B")).test(elf, state)
    assert not HasColor("G").test(sol_ring, state)
    assert not HasColor("G").test(state.players[0], state)


def test_total_power_and_toughness():
    state = new_game()
    kavu = put(state, "Flametongue Kavu")  # 4/2
    griselbrand = put(state, "Griselbrand")  # 7/7
    assert HasTotalPowerAndToughnessAtMost(6).test(kavu, state)
    assert not HasTotalPowerAndToughnessAtMost(5).test(kavu, state)
    assert not HasTotalPowerAndToughnessAtMost(5).test(griselbrand, state)
    assert not HasTotalPowerAndToughnessAtMost(5).test(state.players[0], state)


def test_total_power_and_toughness_non_creature_is_false():
    state = new_game()
    sol_ring = put(state, "Sol Ring")
    assert not HasTotalPowerAndToughnessAtMost(5).test(sol_ring, state)
