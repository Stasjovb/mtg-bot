"""Multi-mode spells (:mod:`mtg_bot.effects.generic.multi_modal`,
:mod:`mtg_bot.cards.parser.modal_spells`): Kolaghan's Command (choose
two), Fiery / Mystic Confluence (choose three, repeats), Collective
Brutality (escalate), Three Steps Ahead (spree)."""

from __future__ import annotations

import pytest

from mtg_bot.actions import CastSpell
from mtg_bot.cards.parser.modal_spells import parse_multi_modal
from mtg_bot.effects.generic.draw_mill import DrawCards
from mtg_bot.effects.generic.multi_modal import ChooseModes
from mtg_bot.effects.generic.targeted_removal import RemoveTargetPermanents
from mtg_bot.effects.object_predicates import IsArtifact, IsCreature
from mtg_bot.legal import legal_actions

from tests._spells_a_helpers import (
    ScriptedAgent,
    cast,
    cast_and_resolve,
    cube,
    lands,
    new_game,
    put,
    resolve,
    to_hand,
    to_library,
)


def _casts(state, pid, card):
    return [
        a for a in legal_actions(state, pid)
        if isinstance(a, CastSpell) and a.card_id == card.id
    ]


# ---------- Kolaghan's Command ----------


def test_kolaghans_command_discard_and_shock():
    agent = ScriptedAgent(modes=[1, 3], prefer=[("player", 1)])
    state = new_game(agent)
    lands(state, 0, "Swamp", 1)
    lands(state, 0, "Mountain", 2)
    victim = to_hand(state, "Island", owner=1)
    cast(state, 0, to_hand(state, "Kolaghan's Command"))
    assert state.stack[-1].chosen_modes == (1, 3)
    assert state.stack[-1].targets == (("player", 1), ("player", 1))
    resolve(state)
    assert victim in state.players[1].graveyard
    assert state.players[1].life == 18


def test_kolaghans_command_pads_to_two_distinct_modes():
    agent = ScriptedAgent(modes=[2, 2], prefer=[("player", 1)])
    state = new_game(agent)
    lands(state, 0, "Swamp", 1)
    lands(state, 0, "Mountain", 2)
    ring = put(state, "Sol Ring", controller=1)
    agent.prefer = [ring.id, ("player", 1)]
    cast(state, 0, to_hand(state, "Kolaghan's Command"))
    modes = state.stack[-1].chosen_modes
    assert len(modes) == 2 and modes[0] == 2 and len(set(modes)) == 2
    resolve(state)
    assert ring in state.players[1].graveyard


# ---------- Confluences ----------


def test_fiery_confluence_same_mode_three_times():
    state = new_game(ScriptedAgent(modes=[1, 1, 1]))
    lands(state, 0, "Mountain", 4)
    cast_and_resolve(state, 0, to_hand(state, "Fiery Confluence"))
    assert state.players[1].life == 14
    assert state.players[0].life == 20


def test_fiery_confluence_pads_by_repeating_the_agents_pick():
    state = new_game(ScriptedAgent(modes=[0]))
    lands(state, 0, "Mountain", 4)
    kavu = put(state, "Flametongue Kavu", controller=1)  # 4/2
    cast(state, 0, to_hand(state, "Fiery Confluence"))
    assert state.stack[-1].chosen_modes == (0, 0, 0)
    resolve(state)
    assert kavu in state.players[1].graveyard


def test_fiery_confluence_skips_unavailable_artifact_mode():
    state = new_game(ScriptedAgent(modes=[2, 2, 2]))
    lands(state, 0, "Mountain", 4)
    cast(state, 0, to_hand(state, "Fiery Confluence"))
    assert 2 not in state.stack[-1].chosen_modes


def test_mystic_confluence_counter_and_draws():
    agent = ScriptedAgent(modes=[0, 2, 2])
    opp = ScriptedAgent(yes=True)
    state = new_game(agent, opp)
    lands(state, 1, "Mountain", 1)
    bolt = to_hand(state, "Lightning Bolt", owner=1)
    cast(state, 1, bolt)
    lands(state, 0, "Island", 5)
    for _ in range(2):
        to_library(state, "Island", owner=0)
    cast(state, 0, to_hand(state, "Mystic Confluence"))
    resolve(state)
    assert state.stack[-1].countered  # opponent can't pay {3}
    assert len(state.players[0].hand) == 2


# ---------- Collective Brutality (escalate) ----------


def test_collective_brutality_escalate_discards_per_extra_mode():
    agent = ScriptedAgent(modes=[2, 1], prefer=[("player", 1)])
    state = new_game(agent)
    lands(state, 0, "Swamp", 2)
    elf = put(state, "Llanowar Elves", controller=1)
    agent.prefer = [("player", 1), elf.id]
    fodder = to_hand(state, "Island")
    cast(state, 0, to_hand(state, "Collective Brutality"))
    assert fodder in state.players[0].graveyard
    resolve(state)
    assert state.players[1].life == 18 and state.players[0].life == 22
    assert elf in state.players[1].graveyard


def test_collective_brutality_escalate_is_limited_by_hand_size():
    agent = ScriptedAgent(modes=[2, 1, 0])
    state = new_game(agent)
    lands(state, 0, "Swamp", 2)
    put(state, "Llanowar Elves", controller=1)
    cast(state, 0, to_hand(state, "Collective Brutality"))
    assert state.stack[-1].chosen_modes == (2,)


def test_collective_brutality_reveal_mode_takes_an_instant():
    state = new_game(ScriptedAgent(modes=[0]))
    lands(state, 0, "Swamp", 2)
    bolt = to_hand(state, "Lightning Bolt", owner=1)
    land = to_hand(state, "Mountain", owner=1)
    cast_and_resolve(state, 0, to_hand(state, "Collective Brutality"))
    assert bolt in state.players[1].graveyard
    assert land in state.players[1].hand


# ---------- Three Steps Ahead (spree) ----------


def test_three_steps_ahead_spree_pays_each_chosen_mode():
    state = new_game(ScriptedAgent(modes=[2]))
    islands = lands(state, 0, "Island", 3)
    for _ in range(2):
        to_library(state, "Island", owner=0)
    to_hand(state, "Mountain")
    cast_and_resolve(state, 0, to_hand(state, "Three Steps Ahead"))
    assert all(i.tapped for i in islands)
    assert len(state.players[0].hand) == 2  # +2 drawn, -1 discarded


def test_three_steps_ahead_trims_unaffordable_modes():
    state = new_game(ScriptedAgent(modes=[2, 1]))
    lands(state, 0, "Island", 3)
    put(state, "Sol Ring", controller=0)
    to_library(state, "Island", owner=0)
    to_library(state, "Island", owner=0)
    cast(state, 0, to_hand(state, "Three Steps Ahead"))
    assert state.stack[-1].chosen_modes == (2,)


def test_three_steps_ahead_needs_mana_for_some_mode():
    state = new_game()
    lands(state, 0, "Island", 1)
    tsa = to_hand(state, "Three Steps Ahead")
    assert _casts(state, 0, tsa) == []
    lands(state, 0, "Island", 2)
    assert _casts(state, 0, tsa) == [CastSpell(tsa.id)]


def test_three_steps_ahead_copies_an_artifact():
    state = new_game(ScriptedAgent(modes=[1]))
    lands(state, 0, "Island", 4)
    ring = put(state, "Sol Ring", controller=0)
    cast_and_resolve(state, 0, to_hand(state, "Three Steps Ahead"))
    copies = [o for o in state.battlefield if o.printing.name == "Sol Ring"]
    assert len(copies) == 2 and any(o.printing.is_token for o in copies)
    assert ring in copies


# ---------- grammar / construction ----------


def test_parse_multi_modal_shapes():
    choose_two = parse_multi_modal(
        ["Choose two —", "• Draw a card.", "• Draw two cards."],
        "X",
    )
    assert choose_two.min_modes == 2 and choose_two.max_modes == 2
    split = parse_multi_modal(
        [
            "Choose three.", "You may choose the same mode more than once.",
            "• Draw a card.", "• Draw two cards.",
        ],
        "X",
    )
    assert split.repeats and split.min_modes == 3
    assert parse_multi_modal(["Choose one —", "• Draw a card.",
                              "• Draw two cards."], "X") is None
    assert parse_multi_modal(["Choose three —", "• Draw a card.",
                              "• Draw two cards."], "X") is None
    assert parse_multi_modal(["Choose two —", "• Blorp."], "X") is None
    assert parse_multi_modal(["Escalate—Discard a card."], "X") is None
    assert parse_multi_modal(
        ["Escalate—Discard a card.", "Choose two —",
         "• Draw a card.", "• Draw two cards."], "X",
    ) is None
    assert parse_multi_modal(["Spree", "+ {1} — Draw a card."], "X") is None
    assert parse_multi_modal([], "X") is None
    assert parse_multi_modal(["Draw a card."], "X") is None
    # Multi-target modes are out of scope for ChooseModes.
    assert parse_multi_modal(
        ["Choose two —", "• Draw a card.",
         "• Destroy up to two target artifacts."], "X",
    ) is None


def test_choose_modes_validation_and_surface():
    with pytest.raises(ValueError):
        ChooseModes(modes=(DrawCards(1),), mode_mana_costs=("{1}", "{2}"))
    eff = cube("Kolaghan's Command").spell_effect
    assert not eff.requires_target()
    assert eff.target_count_range() == (0, 0)
    assert "Choose two" in eff.describe()
    state = new_game()
    ring = put(state, "Sol Ring", controller=1)
    assert ("permanent", ring.id) in eff.legal_targets(state, 0)
    assert eff.mode_mana_cost((0,)).total == 0
    assert [c.total for c in eff.single_mode_mana_costs()] == [0]


def test_choose_modes_resolve_skips_mode_without_target():
    state = new_game()
    eff = ChooseModes(
        modes=(
            DrawCards(1),
            RemoveTargetPermanents(action="destroy", target_filter=IsArtifact()),
        ),
        min_modes=2, max_modes=2,
    )
    to_library(state, "Island", owner=0)
    state.resolving_modes = (1, 0)
    eff.resolve(state, 0, ())
    assert any("skipped" in line for line in state.log)
    assert len(state.players[0].hand) == 1


def test_choose_at_cast_with_nothing_available():
    state = new_game()
    eff = ChooseModes(
        modes=(
            RemoveTargetPermanents(action="destroy", target_filter=IsArtifact()),
            RemoveTargetPermanents(action="destroy", target_filter=IsCreature()),
        ),
        min_modes=1, max_modes=2,
    )
    card = to_hand(state, "Kolaghan's Command")
    assert eff.choose_at_cast(state, 0, card, card.printing.mana_cost) == ()
