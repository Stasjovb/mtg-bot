"""Printed alternative costs ("... rather than pay this spell's mana
cost") and one-of additional costs ("As an additional cost to cast this
spell, discard a card or pay 3 life") for instants and sorceries.

Data lives on ``CardPrinting.alternative_costs`` /
``CardPrinting.additional_cost_options``; this module owns the
payability checks (``legal.legal_actions`` gates casts on them) and the
payment steps (``actions._cast_spell`` runs them). The casting
substrate's own costs (plain pitch alternative cost, sacrifice-a-
<permanent> and pay-X-life additional costs, flashback, delve, ...)
live in :mod:`mtg_bot.alt_casting`.

Alternative costs (CR 118.9) share ONE cast path with the substrate's
pitch cost: the ``CastSpell(cast_for_free=True)`` action variant ("cast
without paying its mana cost"). ``legal_actions`` offers it whenever an
alternative cost is payable; ``_cast_spell`` then casts for that
alternative (``select_alternative_cost``) — paying its mana, if any, in
place of the mana cost, and its other parts with the additional costs.
The ordinary ``CastSpell`` pays the printed mana cost.

Alternative-cost components (combined with "and"):

- ``mana``: pay this mana instead ("You may pay {1}{B} rather than ...")
- ``pay_life``: pay N life
- ``exile_card_color``: exile a card of this color from your hand
  (other than the spell being cast)
- ``return_subtype``: return a permanent you control with this subtype
  to its owner's hand (Daze)
- ``sacrifice_subtype``: sacrifice a permanent with this subtype
  (Mine Collapse)

and optional gates: ``turn`` ("yours" / "not_yours"),
``requires_control_subtype`` ("If you control a Swamp, ...").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.effects.object_predicates import ObjectPredicate
    from mtg_bot.game import GameObject, GameState


_COLOR_WORDS = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}


def _controls_subtype(state: "GameState", player_id: int, subtype: str) -> list:
    from mtg_bot.game import effective_subtypes

    return [
        o for o in state.battlefield
        if o.controller_id == player_id
        and subtype in effective_subtypes(state, o)
    ]


def _pick(agent, state, player_id, options: list):
    """Ask the player's agent to pick one permanent from ``options``
    (``choose_sacrifice`` — the "which permanent do I give up" hook)."""
    if agent is None:
        return options[0]
    pick = agent.choose_sacrifice(state, player_id, [o.id for o in options])
    return next((o for o in options if o.id == pick), options[0])


# ---------------------------------------------------------------------------
# Alternative costs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AlternativeCost:
    mana: str = ""
    pay_life: int = 0
    exile_card_color: str = ""
    return_subtype: str = ""
    sacrifice_subtype: str = ""
    turn: str = ""
    requires_control_subtype: str = ""
    # Overload (CR 702.96): casting for this cost changes "target" in
    # the spell's text to "each". The printing's ``spell_effect`` is an
    # ``IfConditionElse(AlternativeCostWasPaid(), <each-version>,
    # <target-version>)``.
    overload: bool = False

    def mana_cost(self) -> "ManaCost":
        from mtg_bot.cards.base import ManaCost, parse_mana_cost

        return parse_mana_cost(self.mana) if self.mana else ManaCost()

    def describe(self) -> str:
        parts: list[str] = []
        if self.mana:
            parts.append(f"pay {self.mana}")
        if self.pay_life:
            parts.append(f"pay {self.pay_life} life")
        if self.exile_card_color:
            color = _COLOR_WORDS[self.exile_card_color]
            parts.append(f"exile a {color} card from your hand")
        if self.return_subtype:
            parts.append(
                f"return a {self.return_subtype} you control to its "
                f"owner's hand"
            )
        if self.sacrifice_subtype:
            parts.append(f"sacrifice a {self.sacrifice_subtype}")
        text = " and ".join(parts)
        if self.overload:
            text += " (overload: \"target\" becomes \"each\")"
        if self.requires_control_subtype:
            text = f"if you control a {self.requires_control_subtype}, {text}"
        if self.turn == "yours":
            text = f"if it's your turn, {text}"
        elif self.turn == "not_yours":
            text = f"if it's not your turn, {text}"
        return text


def _exile_candidates(state, player_id, card, color) -> list:
    from mtg_bot.game import effective_colors

    p = state.player_by_id(player_id)
    return [
        c for c in p.hand
        if c is not card and color in effective_colors(state, c)
    ]


def alternative_cost_payable(
    state: "GameState", player_id: int, card: "GameObject",
    alt: AlternativeCost,
) -> bool:
    """Whether ``player_id`` could cast ``card`` for ``alt`` right now
    (turn / control gates plus every component)."""
    from mtg_bot.actions import apply_cost_reductions, can_pay_cost

    is_my_turn = state.active_player().id == player_id
    if alt.turn == "yours" and not is_my_turn:
        return False
    if alt.turn == "not_yours" and is_my_turn:
        return False
    if alt.requires_control_subtype and not _controls_subtype(
        state, player_id, alt.requires_control_subtype,
    ):
        return False
    p = state.player_by_id(player_id)
    if alt.pay_life and p.life < alt.pay_life:
        return False
    if alt.exile_card_color and not _exile_candidates(
        state, player_id, card, alt.exile_card_color,
    ):
        return False
    if alt.return_subtype and not _controls_subtype(
        state, player_id, alt.return_subtype,
    ):
        return False
    if alt.sacrifice_subtype and not _controls_subtype(
        state, player_id, alt.sacrifice_subtype,
    ):
        return False
    if alt.mana:
        cost = apply_cost_reductions(
            card.printing, state, player_id, alt.mana_cost(),
        )
        if not can_pay_cost(state, player_id, cost, sac_for_mana=True):
            return False
    return True


def payable_alternative_costs(
    state: "GameState", player_id: int, card: "GameObject",
) -> list[int]:
    """Indices into ``card.printing.alternative_costs`` payable now."""
    return [
        i for i, alt in enumerate(card.printing.alternative_costs)
        if alternative_cost_payable(state, player_id, card, alt)
    ]


def select_alternative_cost(
    state: "GameState", player_id: int, card: "GameObject",
) -> int | None:
    """Which alternative cost an alternative-cost cast
    (``CastSpell(cast_for_free=True)``) of ``card`` uses: the payable
    one, or — when several are payable — the agent's ``choose_mode``
    pick among them. ``None`` if none is payable."""
    options = payable_alternative_costs(state, player_id, card)
    if not options:
        return None
    agent = state.player_by_id(player_id).agent
    if len(options) == 1 or agent is None:
        return options[0]
    idx = agent.choose_mode(
        state, player_id,
        [card.printing.alternative_costs[i].describe() for i in options],
    )
    return options[max(0, min(idx, len(options) - 1))]


def pay_alternative_cost_components(
    state: "GameState", player_id: int, card: "GameObject",
    alt: AlternativeCost,
) -> None:
    """Pay the non-mana components of ``alt`` (the mana is paid by the
    ordinary cost-payment step)."""
    from mtg_bot.effects.generic.targets_helpers import _bounce_to_hand
    from mtg_bot.game import Zone
    from mtg_bot.turn import sacrifice

    p = state.player_by_id(player_id)
    if alt.pay_life:
        p.life -= alt.pay_life
        state.log.append(
            f"alternative cost: P{player_id} pays {alt.pay_life} life "
            f"(life: {p.life})"
        )
    if alt.exile_card_color:
        # Same decision + reveal as the substrate's plain pitch cost
        # (``alt_casting.pay_pitch_cost``): ``choose_discard`` picks the
        # hand card given up.
        from mtg_bot.game import reveal_to_all

        options = _exile_candidates(state, player_id, card, alt.exile_card_color)
        chosen = options[0]
        if p.agent is not None:
            pick = p.agent.choose_discard(
                state, player_id, [c.id for c in options],
            )
            chosen = next((c for c in options if c.id == pick), options[0])
        p.hand.remove(chosen)
        chosen.zone = Zone.EXILE
        p.exile.append(chosen)
        reveal_to_all(state, chosen)
        state.log.append(
            f"alternative cost: P{player_id} exiles {chosen.printing.name} "
            f"from hand"
        )
    if alt.return_subtype:
        options = _controls_subtype(state, player_id, alt.return_subtype)
        chosen = _pick(p.agent, state, player_id, options)
        state.log.append(
            f"alternative cost: P{player_id} returns {chosen.printing.name} "
            f"to hand"
        )
        _bounce_to_hand(state, chosen)
    if alt.sacrifice_subtype:
        options = _controls_subtype(state, player_id, alt.sacrifice_subtype)
        chosen = _pick(p.agent, state, player_id, options)
        state.log.append(
            f"alternative cost: P{player_id} sacrifices {chosen.printing.name}"
        )
        sacrifice(state, chosen)


# ---------------------------------------------------------------------------
# One-of additional costs
# ---------------------------------------------------------------------------


_ADDITIONAL_KINDS = ("discard", "pay_life", "sacrifice")


@dataclass(frozen=True)
class AdditionalCostOption:
    """One arm of an "As an additional cost to cast this spell, A or B"
    clause (a single-arm clause is a one-element tuple).

    ``kind``: ``"discard"`` (``amount`` cards), ``"pay_life"``
    (``amount`` life), ``"sacrifice"`` (a permanent you control
    matching ``permanent_filter``). A single-arm "sacrifice a <filter>"
    or "pay X life" cost is the substrate's
    (``CardPrinting.additional_cost_sacrifice_filter`` /
    ``additional_cost_pay_x_life``).
    """

    kind: str
    amount: int = 1
    permanent_filter: "ObjectPredicate | None" = None
    label: str = ""

    def __post_init__(self) -> None:
        if self.kind not in _ADDITIONAL_KINDS:
            raise ValueError(f"unknown additional cost kind: {self.kind!r}")

    def describe(self) -> str:
        if self.kind == "discard":
            return "discard a card" if self.amount == 1 else (
                f"discard {self.amount} cards"
            )
        if self.kind == "pay_life":
            return f"pay {self.amount} life"
        return f"sacrifice a {self.label}"


def _sacrifice_candidates(state, player_id, option) -> list:
    prior = state.resolving_controller_id
    try:
        state.resolving_controller_id = player_id
        return [
            o for o in state.battlefield
            if o.controller_id == player_id
            and option.permanent_filter.test(o, state)
        ]
    finally:
        state.resolving_controller_id = prior


def additional_option_payable(
    state: "GameState", player_id: int, card: "GameObject",
    option: AdditionalCostOption,
) -> bool:
    p = state.player_by_id(player_id)
    if option.kind == "discard":
        others = [c for c in p.hand if c is not card]
        return len(others) >= option.amount
    if option.kind == "pay_life":
        return p.life >= option.amount
    return bool(_sacrifice_candidates(state, player_id, option))


def additional_costs_payable(
    state: "GameState", player_id: int, card: "GameObject",
) -> bool:
    options = card.printing.additional_cost_options
    if not options:
        return True
    return any(
        additional_option_payable(state, player_id, card, o) for o in options
    )


def pay_additional_cost_option(
    state: "GameState", player_id: int, card: "GameObject",
) -> None:
    """Choose (``choose_mode`` when more than one arm is payable) and
    pay one arm of ``card``'s additional cost."""
    from mtg_bot.game import Zone
    from mtg_bot.turn import fire_opponent_discards_triggers, sacrifice

    options = [
        o for o in card.printing.additional_cost_options
        if additional_option_payable(state, player_id, card, o)
    ]
    if not options:
        return
    p = state.player_by_id(player_id)
    option = options[0]
    if len(options) > 1 and p.agent is not None:
        idx = p.agent.choose_mode(
            state, player_id, [o.describe() for o in options],
        )
        option = options[max(0, min(idx, len(options) - 1))]
    if option.kind == "discard":
        for _ in range(option.amount):
            ids = [c.id for c in p.hand]
            pick = p.agent.choose_discard(state, player_id, ids) if (
                p.agent is not None
            ) else ids[0]
            chosen = next((c for c in p.hand if c.id == pick), p.hand[0])
            p.hand.remove(chosen)
            chosen.zone = Zone.GRAVEYARD
            p.graveyard.append(chosen)
            state.log.append(
                f"additional cost: P{player_id} discards {chosen.printing.name}"
            )
            fire_opponent_discards_triggers(state, player_id, card=chosen)
        return
    if option.kind == "pay_life":
        p.life -= option.amount
        state.log.append(
            f"additional cost: P{player_id} pays {option.amount} life "
            f"(life: {p.life})"
        )
        return
    candidates = _sacrifice_candidates(state, player_id, option)
    chosen = _pick(p.agent, state, player_id, candidates)
    state.log.append(
        f"additional cost: P{player_id} sacrifices {chosen.printing.name}"
    )
    sacrifice(state, chosen)


__all__ = [
    "AdditionalCostOption",
    "AlternativeCost",
    "additional_costs_payable",
    "additional_option_payable",
    "alternative_cost_payable",
    "select_alternative_cost",
    "pay_additional_cost_option",
    "pay_alternative_cost_components",
    "payable_alternative_costs",
]
