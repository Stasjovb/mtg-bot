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


# ---------------------------------------------------------------------
# Emerge (CR 702.119)
# ---------------------------------------------------------------------


def _emerge_candidates(state: "GameState", player_id: int, card: "GameObject"):
    from mtg_bot.game import is_creature_now

    kind = card.printing.emerge_sacrifice_type
    return [
        o for o in state.battlefield
        if o.controller_id == player_id
        and (
            is_creature_now(o) if kind == "Creature"
            else kind in o.printing.card_types
        )
    ]


def _emerge_cost_after(card: "GameObject", sac: "GameObject") -> ManaCost:
    return card.printing.emerge_cost.reduced(sac.printing.mana_cost.total)


def emerge_cast_actions(state: "GameState", player_id: int) -> list:
    """``CastSpell(id, use_emerge=True)`` for hand cards with Emerge
    whose reduced cost is payable with some sacrifice (sorcery timing
    unless the card has flash)."""
    from mtg_bot.actions import CastSpell, can_pay_cost
    from mtg_bot.legal import (
        _additional_costs_payable, _is_sorcery_timing, _targets_are_satisfiable,
    )

    p = state.player_by_id(player_id)
    out: list = []
    seen: set[str] = set()
    for card in p.hand:
        if card.printing.emerge_cost is None or card.printing.name in seen:
            continue
        if not ("flash" in card.printing.keywords or _is_sorcery_timing(
            state, player_id,
        )):
            continue
        if not (
            _targets_are_satisfiable(state, player_id, card)
            and _additional_costs_payable(state, player_id, card)
        ):
            continue
        if any(
            can_pay_cost(state, player_id, _emerge_cost_after(card, sac))
            for sac in _emerge_candidates(state, player_id, card)
        ):
            seen.add(card.printing.name)
            out.append(CastSpell(card.id, use_emerge=True))
    return out


def pay_emerge_sacrifice(
    state: "GameState", player_id: int, card: "GameObject",
) -> ManaCost:
    """Sacrifice the caster's pick among permanents that keep the
    emerge cost payable, and return the emerge cost reduced by its mana
    value."""
    from mtg_bot.actions import can_pay_cost
    from mtg_bot.turn import sacrifice

    options = [
        o for o in _emerge_candidates(state, player_id, card)
        if can_pay_cost(state, player_id, _emerge_cost_after(card, o))
    ]
    if not options:  # pragma: no cover - legal_actions gates
        raise ValueError(f"no emerge sacrifice for {card.printing.name}")
    p = state.player_by_id(player_id)
    chosen = options[0]
    if p.agent is not None:
        pick = p.agent.choose_sacrifice(state, player_id, [o.id for o in options])
        chosen = next((o for o in options if o.id == pick), chosen)
    cost = _emerge_cost_after(card, chosen)
    state.log.append(
        f"P{player_id} emerges {card.printing.name}, sacrificing "
        f"{chosen.printing.name}"
    )
    sacrifice(state, chosen)
    return cost


# ---------------------------------------------------------------------
# Miracle (CR 702.94)
# ---------------------------------------------------------------------

_MIRACLE_ABILITY_INDEX = 2101


def offer_miracle(state: "GameState", player, card: "GameObject") -> None:
    """``card`` was just drawn as ``player``'s first card this turn: they
    may reveal it (``choose_yes_no``); if they do, the miracle trigger
    goes on the stack."""
    from mtg_bot.actions import push_triggered_ability
    from mtg_bot.effects import TriggeredAbility
    from mtg_bot.effects.generic.cube_creatures_ub import (
        MayCastSourceFromHandForMiracleCost,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import reveal_to_all

    if player.agent is not None and not player.agent.choose_yes_no(
        state, player.id, f"Reveal {card.printing.name} for its miracle?",
    ):
        return
    reveal_to_all(state, card)
    state.log.append(f"P{player.id} reveals {card.printing.name} (miracle)")
    push_triggered_ability(
        state,
        source=card,
        ability=TriggeredAbility(
            event=Event.DRAWS_CARD, effect=MayCastSourceFromHandForMiracleCost(),
        ),
        ability_index=_MIRACLE_ABILITY_INDEX,
        controller_id=player.id,
        label="miracle",
    )


def cast_from_hand_for(
    state: "GameState", player_id: int, card: "GameObject", cost: ManaCost,
) -> bool:
    """Cast ``card`` from its owner's hand for the alternative mana cost
    ``cost`` while an effect resolves (Miracle). Returns False when it
    isn't in hand, can't be cast, or ``cost`` isn't payable."""
    from mtg_bot.actions import _cast_spell, apply_cost_reductions, can_pay_cost
    from mtg_bot.legal import _additional_costs_payable, _targets_are_satisfiable

    p = state.player_by_id(player_id)
    if card not in p.hand or card.printing.is_land:
        return False
    if not (
        _targets_are_satisfiable(state, player_id, card)
        and _additional_costs_payable(state, player_id, card)
    ):
        return False
    if not can_pay_cost(
        state, player_id,
        apply_cost_reductions(card.printing, state, player_id, cost),
        sac_for_mana=True,
    ):
        return False
    _cast_spell(state, player_id, card.id, alt_mana_cost=cost)
    return True


# ---------------------------------------------------------------------
# Spell origin for "spells you cast from anywhere other than your hand"
# ---------------------------------------------------------------------

import contextlib as _contextlib
import contextvars as _contextvars

CASTING_FROM_OUTSIDE_HAND: "_contextvars.ContextVar[bool]" = (
    _contextvars.ContextVar("casting_from_outside_hand", default=False)
)


@_contextlib.contextmanager
def casting_origin(outside_hand: bool):
    """Mark the spell whose cost is being determined as cast from
    outside its caster's hand (graveyard, exile, library) for the
    duration of the block (read by ``SpellCastFromOutsideHand``)."""
    token = CASTING_FROM_OUTSIDE_HAND.set(outside_hand)
    try:
        yield
    finally:
        CASTING_FROM_OUTSIDE_HAND.reset(token)


# ---------------------------------------------------------------------
# Casting a spell while an effect resolves
# ---------------------------------------------------------------------


def can_cast_now(
    state: "GameState", player_id: int, card: "GameObject", *, free: bool,
) -> bool:
    """Could ``player_id`` cast ``card`` right now (during an effect's
    resolution): not a land, targets available, additional costs and --
    unless free -- the mana cost payable."""
    from mtg_bot.actions import apply_cost_reductions
    from mtg_bot.game import Zone
    from mtg_bot.legal import (
        _additional_costs_payable, _can_cast, _targets_are_satisfiable,
    )

    if card.printing.is_land:
        return False
    if not (
        _targets_are_satisfiable(state, player_id, card)
        and _additional_costs_payable(state, player_id, card)
    ):
        return False
    if free:
        return True
    with casting_origin(card.zone != Zone.HAND):
        cost = apply_cost_reductions(
            card.printing, state, player_id, card.printing.mana_cost,
        )
    return _can_cast(state, player_id, card, cost)


def cast_now(
    state: "GameState", player_id: int, card: "GameObject", *, free: bool,
) -> bool:
    """Cast ``card`` from its graveyard or exile while an effect
    resolves ("you may cast the discarded card without paying its mana
    cost", "you may cast a spell from among cards exiled this way").
    The spell goes on the stack above the resolving ability (CR
    608.2g); timing restrictions don't apply. The caller has already
    obtained the player's "may" consent and checked ``can_cast_now``.
    Returns False when the card isn't in a castable zone."""
    from mtg_bot.actions import _cast_spell
    from mtg_bot.game import Zone

    if card.zone == Zone.GRAVEYARD and card in state.player_by_id(
        player_id,
    ).graveyard:
        card.castable_from_graveyard_this_turn = True
    elif card.zone == Zone.EXILE and card in state.player_by_id(
        card.owner_id,
    ).exile:
        card.may_play_by = player_id
        card.may_play_free = free
    else:
        return False
    _cast_spell(state, player_id, card.id, cast_for_free=free)
    return True
