"""Pin: Affinity-for-artifacts counts a Treasure-style artifact at
cost-determination (CR 601.2f).

Per CR 601.2:
- 601.2f: total cost is determined. Affinity discount counts every
  artifact in play, INCLUDING any artifact that's about to be
  sacrificed for mana at 601.2g/h.
- 601.2g/h: mana abilities are activated and cost is paid. A
  Treasure can be sacrificed for mana here.

Test scope: this file pins the cost-determination side (601.2f).
The combined scenario "discount applies AND treasure sacrificed
on same cast" requires the pipeline to interleave mana-ability
activation with cost payment, which is the same plumbing Convoke
needs. That's tracked as a separate gap and tested when Convoke
lands.
"""

from __future__ import annotations

from mtg_bot.actions import apply_cost_reductions
from mtg_bot.cards.base import (
    ActivatedAbility, ActivationCost, CardPrinting, ManaCost,
    parse_mana_cost,
)
from mtg_bot.effects.generic import AddManaToPool
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


# Synthetic Treasure: artifact token with "Sacrifice this: Add one
# mana of any color" (modeled as colorless for simplicity — the
# question this file probes is "does Affinity count it as an
# artifact at 601.2f", not which color of mana it adds).
_TREASURE_TOKEN = CardPrinting(
    name="Treasure (test)",
    mana_cost_str="",
    mana_cost=ManaCost(),
    type_line="Token Artifact — Treasure",
    supertypes=("Token",),
    card_types=("Artifact",),
    subtypes=("Treasure",),
    activated_abilities=(
        ActivatedAbility(
            cost=ActivationCost(sacrifice_self=True),
            effect=AddManaToPool(produces=(("C", 1),)),
            is_mana_ability=True,
        ),
    ),
)


# Dummy spell printing for cost-reduction probes — only the
# mana_cost / cost_reductions fields matter.
def _spell(cost_str: str) -> CardPrinting:
    return CardPrinting(
        name="dummy", mana_cost_str=cost_str,
        mana_cost=parse_mana_cost(cost_str),
        type_line="Sorcery", supertypes=(),
        card_types=("Sorcery",), subtypes=(),
    )


def _new_state():
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def test_affinity_counts_treasure_in_play():
    """Sami + 1 Treasure → spells cast by Sami's controller get a
    {1} discount because the Treasure counts as an artifact at
    601.2f cost-determination."""
    state = _new_state()
    _put(state, _PRINTINGS["Sami, Wildcat Captain"], 0)
    _put(state, _TREASURE_TOKEN, 0)
    # Spell {1}{R}. Affinity reduces by 1 → {0}{R}.
    reduced = apply_cost_reductions(
        _spell("{1}{R}"), state, caster_id=0,
        base_cost=parse_mana_cost("{1}{R}"),
    )
    assert reduced.generic == 0
    assert reduced.colored == (("R", 1),)


def test_affinity_counts_two_treasures():
    """Two Treasures + Sami → discount of {2}."""
    state = _new_state()
    _put(state, _PRINTINGS["Sami, Wildcat Captain"], 0)
    _put(state, _TREASURE_TOKEN, 0)
    _put(state, _TREASURE_TOKEN, 0)
    reduced = apply_cost_reductions(
        _spell("{3}{R}"), state, caster_id=0,
        base_cost=parse_mana_cost("{3}{R}"),
    )
    assert reduced.generic == 1
    assert reduced.colored == (("R", 1),)


def test_affinity_does_not_count_sami_herself():
    """Sami is a creature, not an artifact. With only Sami in play,
    no discount applies (RAW: spell-being-cast isn't on battlefield
    AND Sami isn't an artifact). Pin the gate."""
    state = _new_state()
    _put(state, _PRINTINGS["Sami, Wildcat Captain"], 0)
    reduced = apply_cost_reductions(
        _spell("{1}{R}"), state, caster_id=0,
        base_cost=parse_mana_cost("{1}{R}"),
    )
    assert reduced.generic == 1
    assert reduced.colored == (("R", 1),)


def test_affinity_does_not_count_opponents_artifacts():
    """Sami's affinity is "artifacts YOU control". Opponent's
    Treasure doesn't grant a discount."""
    state = _new_state()
    _put(state, _PRINTINGS["Sami, Wildcat Captain"], 0)
    treasure_oppo = _put(state, _TREASURE_TOKEN, 1)
    treasure_oppo.controller_id = 1
    reduced = apply_cost_reductions(
        _spell("{2}{R}"), state, caster_id=0,
        base_cost=parse_mana_cost("{2}{R}"),
    )
    # No discount: opp's Treasure doesn't count for our affinity.
    assert reduced.generic == 2
