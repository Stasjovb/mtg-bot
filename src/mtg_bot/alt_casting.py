"""Alternative and additional casting costs shared by the cast pipeline
(``actions._cast_spell``) and legal-move enumeration (``legal.py``).

Covers the generic keyword costs the PowerLSV cube's instants and
sorceries print:

* **Flashback** (CR 702.34) — cast from the graveyard for the printed
  flashback cost; the card is exiled when it leaves the stack.
* **Delve** (CR 702.66) — exile cards from your graveyard as you cast
  the spell; each pays for {1}.
* **Buyback** (CR 702.27) — optional additional cost; the spell returns
  to its owner's hand as it resolves.
* **"As an additional cost to cast this spell, sacrifice a <filter>."**
  (Tinker, Natural Order, Crop Rotation) — ``CardPrinting.
  additional_cost_sacrifice_filter``.
* **"As an additional cost to cast this spell, pay X life."** (Toxic
  Deluge) — ``CardPrinting.additional_cost_pay_x_life``.

Every piece is keyed off ``CardPrinting`` fields, so creature / other
permanent printings that carry the same keyword reuse the same path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mtg_bot.cards import ManaCost

if TYPE_CHECKING:
    from mtg_bot.game import GameObject, GameState


# ---------------------------------------------------------------------
# Additional sacrifice cost
# ---------------------------------------------------------------------


def permanent_matches_filter(state: "GameState", obj: "GameObject", card_filter) -> bool:
    """Test a battlefield permanent against a ``CardFilter``.

    Card types and supertypes read the printing, except ``Creature``
    which reads ``is_creature_now`` (an animated land is a creature;
    an impending Overlord is not). Color reads ``effective_colors``.
    """
    from mtg_bot.game import effective_colors, is_creature_now

    pr = obj.printing
    if card_filter.any_types:
        ok = False
        for t in card_filter.any_types:
            if t == "Creature":
                if is_creature_now(obj):
                    ok = True
                    break
            elif t == "Permanent" or t in pr.card_types:
                ok = True
                break
        if not ok:
            return False
    for t in card_filter.excluded_types:
        if t == "Creature":
            if is_creature_now(obj):
                return False
        elif t in pr.card_types:
            return False
    if card_filter.max_mv is not None and pr.mana_cost.total > card_filter.max_mv:
        return False
    if card_filter.color is not None and card_filter.color not in effective_colors(state, obj):
        return False
    if card_filter.supertype is not None and card_filter.supertype not in pr.supertypes:
        return False
    return True


def sacrifice_cost_options(
    state: "GameState", player_id: int, card: "GameObject",
) -> list["GameObject"]:
    """Permanents ``player_id`` controls that can pay ``card``'s
    additional sacrifice cost (empty when the card has none)."""
    f = card.printing.additional_cost_sacrifice_filter
    if f is None:
        return []
    return [
        o for o in state.battlefield
        if o.controller_id == player_id
        and permanent_matches_filter(state, o, f)
    ]


def additional_costs_payable(
    state: "GameState", player_id: int, card: "GameObject",
) -> bool:
    """Gate for the casting-substrate additional costs. A sacrifice
    cost needs at least one eligible permanent; "pay X life" is always
    payable (X may be 0)."""
    if card.printing.additional_cost_sacrifice_filter is not None:
        if not sacrifice_cost_options(state, player_id, card):
            return False
    return True


def pay_additional_sacrifice(
    state: "GameState", player_id: int, card: "GameObject",
) -> "GameObject | None":
    """Pay ``card``'s additional sacrifice cost (agent pick via
    ``choose_sacrifice``). Returns the sacrificed permanent, or ``None``
    when the card has no such cost."""
    options = sacrifice_cost_options(state, player_id, card)
    if not options:
        return None
    from mtg_bot.turn import sacrifice

    p = state.player_by_id(player_id)
    chosen = options[0]
    if p.agent is not None:
        pick = p.agent.choose_sacrifice(state, player_id, [o.id for o in options])
        chosen = next((o for o in options if o.id == pick), options[0])
    state.log.append(
        f"additional cost: P{player_id} sacrifices {chosen.printing.name}"
    )
    sacrifice(state, chosen)
    return chosen


# ---------------------------------------------------------------------
# Pay X life
# ---------------------------------------------------------------------


def pay_x_life_upper_bound(state: "GameState", player_id: int, card: "GameObject") -> int:
    """Largest X offered for a "pay X life" additional cost.

    CR 119.4 lets a player pay any amount of life up to their total;
    paying their whole life total loses the game, so the offered range
    stops one short of it. When the spell's effect can say how much X
    is ever useful (``Effect.useful_x_cap``), larger X values are
    dominated and pruned (documented in ``docs/SEARCH_LIMITATIONS.md``).
    """
    p = state.player_by_id(player_id)
    bound = max(0, p.life - 1)
    eff = card.printing.spell_effect
    cap_fn = getattr(eff, "useful_x_cap", None)
    if cap_fn is not None:
        cap = cap_fn(state, player_id)
        if cap is not None:
            bound = min(bound, max(0, cap))
    return bound


def choose_pay_x_life(state: "GameState", player_id: int, card: "GameObject") -> int:
    """Ask the caster for X (``choose_x``) for a "pay X life" cost."""
    p = state.player_by_id(player_id)
    upper = pay_x_life_upper_bound(state, player_id, card)
    x = upper
    if p.agent is not None:
        x = p.agent.choose_x(state, player_id, card.printing.name, upper)
    x = max(0, min(upper, x))
    state.log.append(f"P{player_id} chooses to pay X={x} life for {card.printing.name}")
    return x


# ---------------------------------------------------------------------
# Delve
# ---------------------------------------------------------------------


def _delvable_cards(state: "GameState", player_id: int, card: "GameObject") -> list:
    p = state.player_by_id(player_id)
    return [c for c in p.graveyard if c.id != card.id]


def delve_affordability_cost(
    state: "GameState", player_id: int, card: "GameObject", cost: ManaCost,
) -> ManaCost:
    """Upper-bound cost for legality checks: delve as much generic mana
    as the graveyard allows (delve only ever makes a spell cheaper)."""
    if not card.printing.has_delve:
        return cost
    return cost.reduced(len(_delvable_cards(state, player_id, card)))


def pay_delve(
    state: "GameState", player_id: int, card: "GameObject", cost: ManaCost,
) -> ManaCost:
    """Exile cards from the caster's graveyard to pay generic mana.

    The number of cards is chosen via ``choose_x`` (bounded by the
    generic portion and the graveyard size). Cards without flashback
    are exiled first, oldest first — which specific cards get delved is
    not offered as a choice (``docs/SEARCH_LIMITATIONS.md``). Returns
    the remaining cost.
    """
    if not card.printing.has_delve:
        return cost
    from mtg_bot.game import Zone

    pool = _delvable_cards(state, player_id, card)
    upper = min(cost.generic, len(pool))
    if upper <= 0:
        return cost
    p = state.player_by_id(player_id)
    n = upper
    if p.agent is not None:
        n = p.agent.choose_x(state, player_id, f"{card.printing.name} (delve)", upper)
    n = max(0, min(upper, n))
    if n == 0:
        return cost
    ordered = sorted(
        pool, key=lambda c: c.printing.flashback_cost is not None,
    )
    exiled = ordered[:n]
    for c in exiled:
        p.graveyard.remove(c)
        c.zone = Zone.EXILE
        p.exile.append(c)
    state.log.append(
        f"P{player_id} delves {n} card(s) for {card.printing.name}"
    )
    return cost.reduced(n)


# ---------------------------------------------------------------------
# Buyback
# ---------------------------------------------------------------------


def cost_plus(cost: ManaCost, extra: "ManaCost | None") -> ManaCost:
    """Merge an additional mana cost (buyback / kicker) into ``cost``."""
    if extra is None:
        return cost
    merged: dict[str, int] = dict(cost.colored)
    for color, n in extra.colored:
        merged[color] = merged.get(color, 0) + n
    return ManaCost(
        generic=cost.generic + extra.generic,
        colored=tuple(sorted(merged.items())),
        x_pips=cost.x_pips + extra.x_pips,
        hybrid=cost.hybrid + extra.hybrid,
        phyrexian=cost.phyrexian + extra.phyrexian,
    )


# ---------------------------------------------------------------------
# Flashback
# ---------------------------------------------------------------------


def flashback_cost(card: "GameObject") -> "ManaCost | None":
    """The flashback cost ``card`` can currently be cast for from its
    owner's graveyard, or ``None``: the printed flashback cost, else a
    granted "flashback cost equal to its mana cost" (the Flashback
    card)."""
    if card.printing.flashback_cost is not None:
        return card.printing.flashback_cost
    if card.flashback_granted_until_eot:
        return card.printing.mana_cost
    return None


# ---------------------------------------------------------------------
# Pitch alternative cost + free-cast permissions
# ---------------------------------------------------------------------


def pitch_options(state: "GameState", player_id: int, card: "GameObject") -> list:
    """Other hand cards that can pay ``card``'s "exile a <filter> card
    from your hand rather than pay this spell's mana cost"."""
    f = card.printing.alt_cost_exile_from_hand
    if f is None:
        return []
    p = state.player_by_id(player_id)
    return [c for c in p.hand if c.id != card.id and f.matches(c.printing)]


def free_cast_permission(state: "GameState", player_id: int, card: "GameObject") -> bool:
    """Is ``card`` castable without paying its mana cost with no further
    cost: Weftwalking's first-spell grant or the card's own
    ``free_cast_condition`` (Once Upon a Time)?"""
    p = state.player_by_id(player_id)
    if (
        state.players[state.active_player_idx].id == player_id
        and p.spells_cast_this_turn == 0
        and any(o.printing.grants_first_spell_each_turn_free for o in state.battlefield)
    ):
        return True
    cond = card.printing.free_cast_condition
    return cond is not None and cond.matches(state, player_id)


def pay_pitch_cost(state: "GameState", player_id: int, card: "GameObject") -> None:
    """Exile the pitched card (picked through ``choose_discard`` — the
    "which hand card do I give up" decision)."""
    from mtg_bot.game import Zone, reveal_to_all

    options = pitch_options(state, player_id, card)
    if not options:  # pragma: no cover - legal_actions gates
        raise ValueError(f"no card to exile for {card.printing.name}")
    p = state.player_by_id(player_id)
    chosen = options[0]
    if p.agent is not None:
        pick = p.agent.choose_discard(state, player_id, [c.id for c in options])
        chosen = next((c for c in options if c.id == pick), options[0])
    p.hand.remove(chosen)
    chosen.zone = Zone.EXILE
    p.exile.append(chosen)
    reveal_to_all(state, chosen)
    state.log.append(
        f"P{player_id} exiles {chosen.printing.name} to cast "
        f"{card.printing.name} without paying its mana cost"
    )
