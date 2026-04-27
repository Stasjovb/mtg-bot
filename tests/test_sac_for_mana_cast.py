"""Pin: sac-for-mana mana abilities (Treasure-style) fire during the
cast pipeline's cost-payment step, including the combined case where
the source provides BOTH the affinity discount (counted at 601.2f
because it's still on the battlefield) AND the mana that pays the
remainder (sacrificed at 601.2g).

CR refs:
- 601.2f: total cost determined; Sami's affinity counts the Treasure
  on the battlefield → discount applies.
- 601.2g/h: mana abilities activated and cost paid. The Treasure is
  sacrificed for mana here. Mana abilities (CR 605) don't use the
  stack, so this is a single atomic "cost-payment" step from the
  outside.

This was the deferred half of test_affinity_plus_treasure.py — the
plumbing for it landed in the convoke branch, and this file makes
the combined scenario observable end-to-end.
"""

from __future__ import annotations

from mtg_bot.actions import (
    CastSpell, apply_action, can_pay_cost, resolve_top_of_stack,
)
from mtg_bot.agents import Agent
from mtg_bot.cards import BASIC_LANDS, EOE_CREATURES
from mtg_bot.cards.base import (
    ActivatedAbility, ActivationCost, CardPrinting, ManaCost,
    parse_mana_cost,
)
from mtg_bot.effects.generic import (
    AddManaToPool, DealDamageToTargetCreature,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step


def _treasure(produces_color: str) -> CardPrinting:
    """Synthetic Treasure-style token: artifact with "Sacrifice this:
    Add {<color>}". Real MTG Treasure produces "any" color; using a
    fixed color keeps tests focused on the cost-payment plumbing."""
    return CardPrinting(
        name=f"Treasure-{produces_color} (test)",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Token Artifact — Treasure",
        supertypes=("Token",),
        card_types=("Artifact",),
        subtypes=("Treasure",),
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(sacrifice_self=True),
                effect=AddManaToPool(produces=((produces_color, 1),)),
                is_mana_ability=True,
            ),
        ),
    )


_TREASURE_R = _treasure("R")
_TREASURE_C = _treasure("C")
_TREASURE_ANY = _treasure("any")


def _instant(name: str, cost_str: str, amount: int = 2) -> CardPrinting:
    """Synthetic damage-dealing instant for cost-payment probes."""
    return CardPrinting(
        name=name, mana_cost_str=cost_str,
        mana_cost=parse_mana_cost(cost_str),
        type_line="Instant", supertypes=(),
        card_types=("Instant",), subtypes=(),
        spell_effect=DealDamageToTargetCreature(amount=amount),
    )


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        for kind, tid in legal_targets:
            if kind == "creature":
                obj = next(
                    (o for o in state.battlefield if o.id == tid), None,
                )
                if obj is not None and obj.controller_id != player_id:
                    return (kind, tid)
        return legal_targets[0] if legal_targets else None


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def _hand(state, printing, owner_id=0):
    p = state.players[owner_id]
    obj = state.new_object(printing, owner_id, Zone.HAND)
    p.hand.append(obj)
    return obj


def test_treasure_sacrificed_to_pay_for_spell():
    """1 Treasure-R + 0 lands. Cast {R} instant. Treasure sacs for
    {R}; cost paid; spell on stack."""
    state = _new_state()
    treasure = _put(state, _TREASURE_R, 0)
    _put(state, EOE_CREATURES["Wild Bear"], 1) if False else None
    # Need a creature target for DealDamageToTargetCreature.
    from mtg_bot.cards import SYNTHETIC_CREATURES
    victim = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    bolt = _hand(state, _instant("Solo R", "{R}"), 0)
    apply_action(state, 0, CastSpell(bolt.id))
    # Treasure sac'd → no longer on battlefield. Tokens cease to
    # exist on leaving the battlefield, so we don't check graveyard.
    assert treasure not in state.battlefield
    # Spell on stack.
    assert state.stack
    resolve_top_of_stack(state)
    assert victim.damage == 2


def test_affinity_discount_AND_treasure_sacrificed_on_same_cast():
    """The deferred case from test_affinity_plus_treasure.py: Sami
    grants -1 because the Treasure is on the battlefield at 601.2f.
    The same Treasure is then sacrificed at 601.2g to pay the
    remaining {R}. End-to-end probe of interleaved cost-determination
    and mana-ability activation on a single cast."""
    state = _new_state()
    _put(state, EOE_CREATURES["Sami, Wildcat Captain"], 0)
    treasure = _put(state, _TREASURE_R, 0)
    from mtg_bot.cards import SYNTHETIC_CREATURES
    victim = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    # {1}{R} — Sami's affinity for artifacts on Treasure → -1 →
    # cost = {0}{R}. Treasure sac → {R} in pool. Auto-tap consumes
    # the {R}. Spell goes on stack.
    bolt = _hand(state, _instant("Bolt 1R", "{1}{R}"), 0)
    apply_action(state, 0, CastSpell(bolt.id))
    # Treasure sacrificed (token → ceases to exist on leaving play).
    assert treasure not in state.battlefield
    # Pool empty (the {R} was consumed paying the post-discount cost).
    assert state.players[0].mana_pool == []
    assert state.stack
    resolve_top_of_stack(state)
    assert victim.damage == 2


def test_treasure_only_sac_when_needed():
    """If pool + lands already cover the cost, the Treasure stays put
    — ``_activate_sac_for_mana_for_cost`` short-circuits when
    can_pay_cost is already True."""
    state = _new_state()
    treasure = _put(state, _TREASURE_R, 0)
    # 2 Mountains cover {1}{R} without help.
    for _ in range(2):
        _put(state, BASIC_LANDS["Mountain"], 0)
    from mtg_bot.cards import SYNTHETIC_CREATURES
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    bolt = _hand(state, _instant("Bolt 1R", "{1}{R}"), 0)
    apply_action(state, 0, CastSpell(bolt.id))
    assert treasure in state.battlefield
    assert treasure not in state.players[0].graveyard


def test_treasure_with_wrong_color_doesnt_help_colored_pip():
    """Treasure-C produces {C}; can't pay a {R} requirement. With 0
    lands and {1}{R} cost, the cast must be illegal even though the
    Treasure exists."""
    state = _new_state()
    _put(state, _TREASURE_C, 0)
    bolt = _hand(state, _instant("Bolt 1R", "{1}{R}"), 0)
    cast_acts = [
        a for a in legal_actions(state, 0)
        if isinstance(a, CastSpell) and a.card_id == bolt.id
    ]
    assert cast_acts == []


def test_two_treasures_pay_2_generic():
    """2 Treasure-Cs cover a {2} cost via two sac-for-{C}
    activations."""
    state = _new_state()
    t1 = _put(state, _TREASURE_C, 0)
    t2 = _put(state, _TREASURE_C, 0)
    from mtg_bot.cards import SYNTHETIC_CREATURES
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    spell = _hand(state, _instant("Generic 2", "{2}"), 0)
    apply_action(state, 0, CastSpell(spell.id))
    # Both treasures sacrificed (tokens → cease to exist).
    assert t1 not in state.battlefield
    assert t2 not in state.battlefield
    assert state.players[0].mana_pool == []


def test_affordability_check_counts_treasure_as_payable():
    """legal_actions includes a {R} bolt cast when the only mana
    source is a Treasure-R — sac_for_mana=True is wired through.
    Needs a target on the battlefield since the synthetic instant
    targets a creature."""
    from mtg_bot.cards import SYNTHETIC_CREATURES
    state = _new_state()
    _put(state, _TREASURE_R, 0)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    bolt = _hand(state, _instant("Solo R", "{R}"), 0)
    cast_acts = [
        a for a in legal_actions(state, 0)
        if isinstance(a, CastSpell) and a.card_id == bolt.id
    ]
    assert len(cast_acts) == 1


def test_sac_for_mana_max_contribution_with_zero_cost():
    """Edge case: zero cost short-circuits without scanning."""
    state = _new_state()
    _put(state, _TREASURE_R, 0)
    assert can_pay_cost(state, 0, ManaCost(), sac_for_mana=True)


def test_treasure_any_color_satisfies_any_pip():
    """A Treasure that produces "any" color matches a colored pip in
    any color (mirrors real Treasure tokens)."""
    state = _new_state()
    _put(state, _TREASURE_ANY, 0)
    from mtg_bot.cards import SYNTHETIC_CREATURES
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    bolt = _hand(state, _instant("Solo R", "{R}"), 0)
    apply_action(state, 0, CastSpell(bolt.id))
    # Cast succeeded.
    assert state.stack


def test_sac_skips_when_no_other_costs_payable():
    """If the cost can't be paid even with all sac-for-mana
    activations, the helper bails out without sacrificing anything
    — Treasures shouldn't blow up for a cost we can't actually
    cover (the legality gate prevents this from being reached in
    practice, but pin the safety branch)."""
    state = _new_state()
    treasure = _put(state, _TREASURE_C, 0)
    # Synthesize a CastSpell action manually since legal_actions
    # would correctly say no — we want to probe the sac helper's
    # bail-out behavior under a forced cast.
    from mtg_bot.actions import _activate_sac_for_mana_for_cost
    cost = parse_mana_cost("{R}")  # {C} treasure can't pay {R}
    _activate_sac_for_mana_for_cost(state, 0, cost, frozenset({"spell"}))
    # Treasure stays put — sacking it wouldn't have helped pay {R}.
    assert treasure in state.battlefield
