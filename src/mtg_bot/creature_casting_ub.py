"""Cast-time optional additional costs for the U/B cube creatures:
Squad (CR 702.157) and Offspring (CR 702.175).

Both are offered while the spell is being cast (CR 601.2b/f), like
splice (``alt_casting.offer_splices``): the caster answers an agent
prompt and the chosen payments are added to the total cost, so no new
``CastSpell`` variants are needed. The payment is recorded on the spell
object (``GameObject.squad_paid_count`` / ``offspring_paid``) for the
permanent's "if its squad / offspring cost was paid" ETB trigger.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mtg_bot.cards.base import ManaCost

if TYPE_CHECKING:
    from mtg_bot.game import GameObject, GameState

# Upper bound on squad payments offered (keeps the affordability scan
# bounded; far above anything a real board can pay).
SQUAD_PAYMENT_CAP = 10


def offer_creature_additional_costs(
    state: "GameState", player_id: int, card: "GameObject", cost: ManaCost,
) -> ManaCost:
    from mtg_bot.actions import can_pay_cost
    from mtg_bot.alt_casting import cost_plus

    p = state.player_by_id(player_id)
    kinds = frozenset({"spell"})
    card.squad_paid_count = 0
    card.offspring_paid = False
    printing = card.printing
    if printing.squad_cost is not None and p.agent is not None:
        upper = 0
        grown = cost
        while upper < SQUAD_PAYMENT_CAP:
            nxt = cost_plus(grown, printing.squad_cost)
            if not can_pay_cost(state, player_id, nxt, kinds, sac_for_mana=True):
                break
            grown = nxt
            upper += 1
        n = 0
        if upper:
            n = p.agent.choose_x(
                state, player_id, f"{printing.name} (squad payments)", upper,
            )
            n = max(0, min(upper, n))
        for _ in range(n):
            cost = cost_plus(cost, printing.squad_cost)
        card.squad_paid_count = n
        if n:
            state.log.append(
                f"P{player_id} pays squad {printing.squad_cost_str} x{n} "
                f"for {printing.name}"
            )
    if printing.offspring_cost is not None and p.agent is not None:
        grown = cost_plus(cost, printing.offspring_cost)
        if can_pay_cost(
            state, player_id, grown, kinds, sac_for_mana=True,
        ) and p.agent.choose_yes_no(
            state, player_id,
            f"Pay offspring {printing.offspring_cost_str} for {printing.name}?",
        ):
            cost = grown
            card.offspring_paid = True
            state.log.append(
                f"P{player_id} pays offspring {printing.offspring_cost_str} "
                f"for {printing.name}"
            )
    return cost
