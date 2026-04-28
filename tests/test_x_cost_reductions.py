"""Pin: cost reductions on an X-spell preserve the ``{X}`` template.

Regression for a bug where ``ManaCost.reduced(amount)`` dropped the
``x_pips`` field because the constructor's default is 0. With
``apply_cost_reductions`` calling ``cost.reduced(...)`` between the
printed cost and the X prompt, an affinity discount on a ``{2}{X}{R}``
spell would silently zero ``x_pips``, the cast pipeline would skip
``_choose_and_apply_x``, and the player effectively cast for X=0.

Coverage:
- ``ManaCost.reduced`` preserves ``x_pips`` directly.
- ``apply_cost_reductions`` on a ``{2}{X}{R}`` synthetic spell with
  Sami + 2 Treasures yields ``{0}{X}{R}`` (generic zeroed, x_pips=1
  retained).
- End-to-end: cast a synthetic ``{2}{X}{B}`` X-sorcery with Sami +
  Treasures on the battlefield. The player picks X via the agent and
  the affinity discount applies to generic only — X stays a real
  choice.
"""

from __future__ import annotations

from mtg_bot.actions import (
    CastSpell, apply_action, apply_cost_reductions, resolve_top_of_stack,
)
from mtg_bot.agents import Agent
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.cards.base import (
    ActivatedAbility, ActivationCost, CardPrinting, ManaCost,
    parse_mana_cost,
)
from mtg_bot.effects.generic import (
    AddManaToPool, DealDamageToTargetCreature,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


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


def _x_spell(cost_str: str) -> CardPrinting:
    """Synthetic X-cost sorcery: {cost_str} with deal-X-damage effect.
    Only the printing-shape fields matter for the cost-reduction
    probe."""
    return CardPrinting(
        name="x-spell-test",
        mana_cost_str=cost_str,
        mana_cost=parse_mana_cost(cost_str),
        type_line="Sorcery",
        supertypes=(),
        card_types=("Sorcery",),
        subtypes=(),
    )


def _new_state(p0_agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=p0_agent))
    state.players.append(Player(id=1))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def test_mana_cost_reduced_preserves_x_pips():
    """Direct probe on the dataclass helper — drop guard against the
    default-x_pips bug."""
    mc = ManaCost(generic=2, colored=(("R", 1),), x_pips=1)
    assert mc.reduced(1).x_pips == 1
    assert mc.reduced(1).generic == 1
    assert mc.reduced(2).x_pips == 1
    assert mc.reduced(2).generic == 0
    # Over-reduction still preserves x_pips.
    assert mc.reduced(99).x_pips == 1
    assert mc.reduced(99).generic == 0


def test_affinity_discount_on_x_spell_preserves_x_template():
    """Sami + 2 Treasures grants -2 generic via affinity. Applied to
    {2}{X}{R}, the result must keep ``x_pips=1`` so the cast pipeline
    still prompts for X."""
    state = _new_state()
    _put(state, _PRINTINGS["Sami, Wildcat Captain"], 0)
    _put(state, _TREASURE_TOKEN, 0)
    _put(state, _TREASURE_TOKEN, 0)
    spell = _x_spell("{2}{X}{R}")
    reduced = apply_cost_reductions(
        spell, state, caster_id=0, base_cost=spell.mana_cost,
    )
    assert reduced.generic == 0
    assert reduced.colored == (("R", 1),)
    assert reduced.x_pips == 1


def test_affinity_discount_on_pure_x_cost_preserves_x_pips():
    """``{X}{B}`` is base-generic 0; affinity reductions clamp at 0
    and waste the discount, but x_pips must still survive so the
    player gets to pick X."""
    state = _new_state()
    _put(state, _PRINTINGS["Sami, Wildcat Captain"], 0)
    _put(state, _TREASURE_TOKEN, 0)
    spell = _x_spell("{X}{B}")
    reduced = apply_cost_reductions(
        spell, state, caster_id=0, base_cost=spell.mana_cost,
    )
    assert reduced.generic == 0
    assert reduced.colored == (("B", 1),)
    assert reduced.x_pips == 1


class _PickXAgent(Agent):
    """Agent that always picks X = ``self.x`` when prompted, and
    targets the first opponent creature for damage spells."""
    def __init__(self, x: int):
        self.x = x

    def choose_x(self, state, player_id, card_name, upper_bound):
        return min(self.x, upper_bound)

    def choose_target(self, state, player_id, legal_targets):
        for kind, tid in legal_targets:
            if kind == "creature":
                obj = next(
                    (o for o in state.battlefield if o.id == tid), None,
                )
                if obj is not None and obj.controller_id != player_id:
                    return (kind, tid)
        return legal_targets[0] if legal_targets else None


def test_x_spell_with_affinity_still_prompts_for_x_via_cast_pipeline():
    """End-to-end: player casts a synthetic {2}{X}{R} sorcery with
    Sami + 2 Treasures on the battlefield. The pre-fix bug zeroed
    x_pips on apply_cost_reductions, so _choose_and_apply_x never
    fired and X defaulted to 0. With the fix, the agent's choose_x
    is called and X=3 is honored."""
    spell = CardPrinting(
        name="X Bolt", mana_cost_str="{2}{X}{R}",
        mana_cost=parse_mana_cost("{2}{X}{R}"),
        type_line="Sorcery", supertypes=(),
        card_types=("Sorcery",), subtypes=(),
        spell_effect=DealDamageToTargetCreature(amount=0),
    )
    state = _new_state(p0_agent=_PickXAgent(x=3))
    p = state.players[0]
    _put(state, _PRINTINGS["Sami, Wildcat Captain"], 0)
    _put(state, _TREASURE_TOKEN, 0)
    _put(state, _TREASURE_TOKEN, 0)
    # Need to pay {0}{X=3}{R} after affinity-2 discount = {3}{R}.
    # 3 Mountains cover the {3} generic; 1 Mountain covers {R}.
    for _ in range(4):
        _put(state, BASIC_LANDS["Mountain"], 0)
    bolt = state.new_object(spell, 0, Zone.HAND)
    p.hand.append(bolt)
    apply_action(state, 0, CastSpell(bolt.id))
    # X must have been prompted (agent returned 3). Inspect the
    # StackItem's chosen_x.
    assert state.stack
    si = state.stack[-1]
    assert si.x_value == 3
    # All 4 Mountains tapped to pay {3}{R}.
    mountain_count = sum(
        1 for o in state.battlefield if o.printing.is_land and o.tapped
    )
    assert mountain_count == 4
    resolve_top_of_stack(state)
