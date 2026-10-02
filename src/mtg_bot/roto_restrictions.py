"""Rules-restricting statics for the Vintage Roto P1 package (stack &
restrictions), modeled on :mod:`mtg_bot.creature_statics_wg`.

The parser (``cards.parser.roto_stack``) puts static descriptors on
``CardPrinting.roto_statics``; this module reads them off permanents on
the battlefield and off command-zone emblems (the "this turn" player
restrictions a resolved spell leaves behind, which expire at cleanup):

* :class:`SpellTax` -- "<Spells> cost {N} more to cast" with the riders
  the existing ``spell_cost_increases`` field can't express: "except
  during its controller's turn" (Defense Grid), "with the chosen name"
  (Disruptor Flute). Added by ``creature_statics_wg.
  spell_cost_increase`` (CR 601.2f increases).
* :class:`MinimumSpellCost` -- "As long as this artifact is untapped,
  each spell that would cost less than three mana to cast costs three
  mana to cast." (Trinisphere), applied after every other cost change
  (:func:`apply_minimum_spell_cost`).
* :class:`CastProhibition` -- can't-cast statics: the chosen name
  (Meddling Mage), player-scoped "this turn" restrictions (Silence,
  Orim's Chant, Ranger-Captain of Eos).
* :class:`ActivationProhibition` -- "Activated abilities of sources with
  the chosen name can't be activated [unless they're mana abilities]."
  (Pithing Needle, Phyrexian Revoker, Disruptor Flute).

``legal.legal_actions`` drops the forbidden ``CastSpell`` /
``ActivateAbility`` proposals through :func:`filter_actions`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import GameObject, GameState


# ---------------------------------------------------------------------
# Descriptors
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class SpellTax:
    """A spell-cost increase (CR 601.2f).

    ``spell_filter`` (a ``CardFilter``; ``None`` = every spell) selects
    the taxed spells; ``opponents_only`` limits it to spells the
    source's controller's opponents cast; ``except_during_casters_turn``
    exempts a spell cast during its controller's own turn;
    ``from_graveyard_or_exile`` taxes only spells cast from a graveyard
    ``named`` taxes only spells with the source's chosen
    card name."""

    amount: int
    spell_filter: object = None
    opponents_only: bool = False
    except_during_casters_turn: bool = False
    from_graveyard_or_exile: bool = False
    named: bool = False


@dataclass(frozen=True)
class MinimumSpellCost:
    """"each spell that would cost less than ``total`` mana to cast costs
    ``total`` mana to cast" -- only while the source is untapped when
    ``while_untapped``."""

    total: int
    while_untapped: bool = False


@dataclass(frozen=True)
class CastProhibition:
    """Spells matching ``spell_filter`` (an ``ObjectPredicate`` over the
    card; ``None`` = every spell) can't be cast by the restricted
    players: ``who`` is ``"each"`` (every player), ``"opponents"`` (the
    source's controller's opponents) or ``"player"`` (``player_id``).
    ``named``: only spells with the source's chosen card name."""

    who: str = "each"
    spell_filter: object = None
    player_id: int = -1
    named: bool = False

    def __post_init__(self) -> None:
        if self.who not in ("each", "opponents", "player"):
            raise ValueError(f"unknown CastProhibition scope: {self.who!r}")


@dataclass(frozen=True)
class ActivationProhibition:
    """"Activated abilities of sources with the chosen name can't be
    activated[ unless they're mana abilities]." """

    except_mana_abilities: bool = False


# ---------------------------------------------------------------------
# Static sources
# ---------------------------------------------------------------------


def _static_sources(state: "GameState"):
    """``(object, descriptor)`` for every roto static in play: permanents
    on the battlefield and command-zone emblems."""
    for o in state.battlefield:
        if o.printing.roto_statics and not o.phased_out:
            for s in o.printing.roto_statics:
                yield o, s
    for e in state.emblems:
        for s in e.printing.roto_statics:
            yield e, s


def any_roto_statics(state: "GameState") -> bool:
    return any(True for _ in _static_sources(state))


# ---------------------------------------------------------------------
# Spell taxes and the Trinisphere floor
# ---------------------------------------------------------------------


def _casting_from_graveyard_or_exile() -> bool:
    """The spell whose cost is being determined is cast from a graveyard
    or from exile (``creature_casting_ub.casting_origin``; the library
    origin is told apart by ``CASTING_FROM_EXILE``)."""
    from mtg_bot.creature_casting_ub import (
        CASTING_FROM_GRAVEYARD,
        CASTING_FROM_OUTSIDE_HAND,
    )

    if CASTING_FROM_GRAVEYARD.get():
        return True
    return CASTING_FROM_OUTSIDE_HAND.get() and CASTING_FROM_EXILE.get()


def roto_spell_tax(
    state: "GameState", printing: "CardPrinting", caster_id: "int | None",
) -> int:
    """Generic mana the roto :class:`SpellTax` statics add to the cost of
    ``caster_id`` casting ``printing``."""
    total = 0
    active_id = state.players[state.active_player_idx].id if state.players else None
    for src, s in _static_sources(state):
        if not isinstance(s, SpellTax):
            continue
        if s.spell_filter is not None and not s.spell_filter.matches(printing):
            continue
        if s.opponents_only and (caster_id is None or caster_id == src.controller_id):
            continue
        if s.except_during_casters_turn and caster_id == active_id:
            continue
        if s.from_graveyard_or_exile and not _casting_from_graveyard_or_exile():
            continue
        if s.named and src.chosen_card_name != printing.name:
            continue
        total += s.amount
    return total


def minimum_spell_cost(state: "GameState") -> int:
    """The largest active "costs at least N mana" floor (0 = none)."""
    floor = 0
    for src, s in _static_sources(state):
        if not isinstance(s, MinimumSpellCost):
            continue
        if s.while_untapped and src.tapped:
            continue
        floor = max(floor, s.total)
    return floor


def apply_minimum_spell_cost(
    state: "GameState", cost: "ManaCost", already_paid: int = 0,
    *, log: bool = False,
) -> "ManaCost":
    """Raise ``cost`` with generic mana so the spell's total cost is at
    least the active floor. ``already_paid`` counts mana-value units of
    the total cost already settled another way (Phyrexian pips paid with
    life). Trinisphere applies after every other cost change (CR
    601.2f), so callers pass the final total cost."""
    floor = minimum_spell_cost(state)
    if not floor:
        return cost
    from mtg_bot.cards.base import ManaCost

    missing = floor - (cost.total + already_paid)
    if missing <= 0:
        return cost
    if log:
        state.log.append(f"spell's total cost raised to {floor} mana")
    return ManaCost(
        generic=cost.generic + missing, colored=cost.colored,
        x_pips=cost.x_pips, hybrid=cost.hybrid, phyrexian=cost.phyrexian,
    )


# ---------------------------------------------------------------------
# Cast prohibitions
# ---------------------------------------------------------------------


def _restricts(state: "GameState", src, s: CastProhibition, player_id: int) -> bool:
    if s.who == "each":
        return True
    if s.who == "opponents":
        return player_id != src.controller_id
    return player_id == s.player_id


def cast_prohibited(
    state: "GameState", player_id: int, card: "GameObject",
) -> bool:
    """Whether a roto can't-cast static forbids ``player_id`` from casting
    ``card`` right now."""
    for src, s in _static_sources(state):
        if not isinstance(s, CastProhibition):
            continue
        if not _restricts(state, src, s, player_id):
            continue
        if s.named and src.chosen_card_name != card.printing.name:
            continue
        if s.spell_filter is not None and not s.spell_filter.test(card, state):
            continue
        return True
    return False


# ---------------------------------------------------------------------
# Activation prohibitions
# ---------------------------------------------------------------------


def activation_prohibited(
    state: "GameState", source: "GameObject", ability,
) -> bool:
    """Whether a named activation lock forbids activating ``ability`` of
    ``source`` (a permanent, or a card in a hand or graveyard)."""
    for src, s in _static_sources(state):
        if not isinstance(s, ActivationProhibition):
            continue
        if src.chosen_card_name is None:
            continue
        if src.chosen_card_name != source.printing.name:
            continue
        if s.except_mana_abilities and getattr(ability, "is_mana_ability", False):
            continue
        return True
    return False


def _find_activation_source(state: "GameState", player_id: int, source_id: int):
    """``(source, abilities)`` for an ``ActivateAbility``'s source: a
    permanent, or a card in the activator's hand or graveyard."""
    for o in state.battlefield:
        if o.id == source_id:
            from mtg_bot.game import effective_activated_abilities

            return o, effective_activated_abilities(state, o)
    p = state.player_by_id(player_id)
    for c in p.hand:
        if c.id == source_id:
            return c, c.printing.hand_activated_abilities
    for c in p.graveyard:
        if c.id == source_id:
            return c, c.printing.graveyard_activated_abilities
    return None, ()


def _find_cast_card(state: "GameState", player_id: int, card_id: int):
    p = state.player_by_id(player_id)
    for zone in (p.hand, p.graveyard, p.library):
        for c in zone:
            if c.id == card_id:
                return c
    for pl in state.players:
        for c in pl.exile:
            if c.id == card_id:
                return c
    return None


def filter_actions(state: "GameState", player_id: int, actions: list) -> list:
    """Drop the ``CastSpell`` / ``ActivateAbility`` / ``ActivateStation``
    proposals a roto prohibition forbids (the plot special action isn't
    a cast and stays legal)."""
    if not any_roto_statics(state):
        return actions
    from mtg_bot.actions import ActivateAbility, ActivateStation, CastSpell

    out = []
    for a in actions:
        if isinstance(a, CastSpell) and not a.use_plot:
            card = _find_cast_card(state, player_id, a.card_id)
            if card is not None and cast_prohibited(state, player_id, card):
                continue
        elif isinstance(a, ActivateAbility):
            src, abilities = _find_activation_source(state, player_id, a.source_id)
            if (
                src is not None
                and 0 <= a.ability_index < len(abilities)
                and activation_prohibited(state, src, abilities[a.ability_index])
            ):
                continue
        elif isinstance(a, ActivateStation):
            src = next(
                (o for o in state.battlefield if o.id == a.spacecraft_id), None,
            )
            if src is not None and activation_prohibited(state, src, None):
                continue
        out.append(a)
    return out


# ---------------------------------------------------------------------
# Activated abilities that target spells, at instant speed
# ---------------------------------------------------------------------


def _targets_spells_only(effect) -> bool:
    """Whether ``effect``'s targets are objects on the stack (a
    counterspell ability -- Glen Elendra Guardian's "Counter target
    noncreature spell. Its controller draws a card.")."""
    from mtg_bot.effects.generic.counterspells import CounterSpell
    from mtg_bot.effects.generic.cube_creatures_ub import (
        CounterTargetStackObject,
        ThenItsControllerDraws,
    )
    from mtg_bot.effects.generic.roto_stack import (
        CounterSpellThenControllerEffect,
        ExileTargetSpells,
    )
    from mtg_bot.effects.generic.stack_control import CounterTargetSpell

    if isinstance(effect, ThenItsControllerDraws):
        effect = effect.inner
    return isinstance(effect, (
        CounterSpell, CounterTargetSpell, CounterSpellThenControllerEffect,
        ExileTargetSpells, CounterTargetStackObject,
    ))


def _simple_cost(cost) -> bool:
    """The cost is only mana, ``{T}`` and composable cost atoms."""
    from dataclasses import replace

    from mtg_bot.effects.base import ActivationCost

    return replace(
        cost, mana=None, mana_str="", tap_self=False, extra_costs=(),
    ) == ActivationCost()


def instant_speed_spell_targeting_activations(
    state: "GameState", player_id: int,
) -> list:
    """``ActivateAbility`` proposals for battlefield abilities whose
    targets are spells (counter-a-spell abilities), offered whenever
    their controller holds priority.

    ``legal.legal_actions`` otherwise offers battlefield activated
    abilities only in an empty-stack sorcery window, where such an
    ability can never have a target. Only abilities whose cost is mana,
    ``{T}`` and composable atoms are offered; restrictions (sorcery
    speed, "activate only if / during your turn", locks) apply."""
    from mtg_bot.actions import (
        ActivateAbility,
        _effective_ability_mana_cost,
        can_pay_cost,
    )
    from mtg_bot.game import effective_activated_abilities, is_creature_now
    from mtg_bot.keyword_rules import filter_targetable

    out: list = []
    if not state.stack:
        return out  # nothing to target
    for obj in state.battlefield:
        if obj.controller_id != player_id or obj.phased_out:
            continue
        if not any(
            _targets_spells_only(a.effect)
            for a in obj.printing.activated_abilities
        ):
            continue
        abilities = effective_activated_abilities(state, obj)
        for idx, ability in enumerate(abilities):
            if not _targets_spells_only(ability.effect):
                continue
            if ability.sorcery_speed or ability.is_mana_ability:
                continue
            if not _simple_cost(ability.cost):
                continue
            if (
                ability.activate_only_if is not None
                and not ability.activate_only_if.matches(state, player_id)
            ):
                continue
            if (
                ability.activate_only_during_your_turn
                and state.active_player().id != player_id
            ):
                continue
            cost = ability.cost
            if cost.tap_self and (
                obj.tapped or (is_creature_now(obj) and obj.summoning_sick)
            ):
                continue
            if any(not a.payable(state, player_id, obj) for a in cost.extra_costs):
                continue
            from mtg_bot.creature_statics_wg import ability_cost_increase

            if cost.mana is not None or ability_cost_increase(state, obj, ability):
                mana = _effective_ability_mana_cost(state, obj, ability)
                if not can_pay_cost(state, player_id, mana):
                    continue
            if not filter_targetable(
                state, ability.effect.legal_targets(state, player_id),
                obj, player_id,
            ):
                continue
            out.append(ActivateAbility(source_id=obj.id, ability_index=idx))
    return out


# ---------------------------------------------------------------------
# Cast origin: exile vs. the top of a library
# ---------------------------------------------------------------------

import contextvars  # noqa: E402

# Set while a spell cast from exile has its cost determined (paired with
# ``creature_casting_ub.casting_origin``'s outside-hand flag, which is
# also set for casts from the top of a library).
CASTING_FROM_EXILE: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "roto_casting_from_exile", default=False,
)


__all__ = [
    "ActivationProhibition",
    "CASTING_FROM_EXILE",
    "CastProhibition",
    "MinimumSpellCost",
    "SpellTax",
    "activation_prohibited",
    "any_roto_statics",
    "apply_minimum_spell_cost",
    "cast_prohibited",
    "filter_actions",
    "instant_speed_spell_targeting_activations",
    "minimum_spell_cost",
    "roto_spell_tax",
]
