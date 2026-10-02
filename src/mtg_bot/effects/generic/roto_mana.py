"""Engine effects for the Vintage Roto P3 bucket: mana, costs and cast
permissions (``docs/ROTO_COVERAGE_PLAN.md`` section 4).

The parser side lives in ``cards/parser/roto_mana.py``; every effect
here is built only by that grammar. Formulas and predicates the effects
need sit next to them so the shared ``effects/formulas.py`` /
``object_predicates.py`` modules stay untouched by this package.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mtg_bot.effects.base import Effect, Target
from mtg_bot.effects.formulas import Formula
from mtg_bot.effects.generic.mana import AddManaToPool
from mtg_bot.effects.object_predicates import ObjectPredicate

if TYPE_CHECKING:
    from mtg_bot.game import GameState


# ---------------------------------------------------------------------------
# Formulas
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CardsNamedInAllGraveyards(Formula):
    """The number of cards named ``name`` in every graveyard (Rite of
    Flame's "for each card named Rite of Flame in each graveyard"). The
    resolving spell is on the stack, so it never counts itself."""

    name: str

    def value(self, state: "GameState", controller_id: int) -> int:
        return sum(
            1 for p in state.players for c in p.graveyard
            if c.printing.name == self.name
        )


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EnteredThisTurn(ObjectPredicate):
    """A permanent that entered the battlefield this turn ("creatures
    that entered this turn", Force of Despair). Reads the
    ``GameObject.entered_battlefield_turn`` stamp
    ``actions.put_into_battlefield`` writes for every permanent."""

    def test(self, obj, state) -> bool:
        turn = getattr(obj, "entered_battlefield_turn", None)
        return turn is not None and turn == state.turn_number


# ---------------------------------------------------------------------------
# Spend restrictions (``ManaCoin.spend_restriction`` tags of this bucket)
# ---------------------------------------------------------------------------

# Payment-context tags (``actions._coin_satisfies_context``) that mark a
# payment as something other than casting a spell: activating an
# ability (``legal`` / ``actions._activate_ability`` add
# "activated_ability") or turning a face-down creature up.
_NON_SPELL_CONTEXTS = frozenset({"activated_ability"})


def roto_coin_satisfies(coin, kinds: "frozenset[str]") -> bool:
    """Whether a coin carrying one of this bucket's restriction tags may
    pay in the payment context ``kinds``.

    - ``"not_nonartifact_spell"``: "This mana can't be spent to cast
      nonartifact spells." (The Mightstone and Weakstone) -- it pays for
      artifact spells and for anything that isn't casting a spell.
    - ``"creature_type:<T>"``: "Spend this mana only to cast a creature
      spell of the chosen type" (Cavern of Souls) -- matched against
      the ``creature_type:<T>`` tags ``roto_spell_kinds`` adds for a
      creature spell (``creature_type:*`` for a changeling).
    """
    tag = coin.spend_restriction or ""
    if tag == "not_nonartifact_spell":
        return "artifact_spell" in kinds or bool(kinds & _NON_SPELL_CONTEXTS)
    if tag.startswith("creature_type:"):
        return tag in kinds or (
            tag != "creature_type:" and "creature_type:*" in kinds
        )
    return False


def roto_spell_kinds(card) -> "frozenset[str]":
    """Payment-context tags this bucket adds when ``card`` is cast (the
    casting contexts in ``legal._spell_kinds_for_card`` and
    ``actions._cast_spell``): one ``creature_type:<T>`` per creature type
    of a creature spell, ``creature_type:*`` for a changeling (every
    creature type, CR 702.73a)."""
    pr = card.printing
    if not pr.is_creature:
        return frozenset()
    if "changeling" in pr.keywords:
        return frozenset({"creature_type:*"})
    return frozenset(f"creature_type:{s}" for s in pr.subtypes)


# ---------------------------------------------------------------------------
# As-enters choices
# ---------------------------------------------------------------------------


def creature_types_owned_by(state: "GameState", player_id: int) -> list[str]:
    """Creature types among creature cards ``player_id`` owns in any zone
    (library, hand, graveyard, exile, battlefield, stack), sorted -- the
    offered set of "choose a creature type" (a type no card of yours has
    can't matter to an own-spell restriction)."""
    p = state.player_by_id(player_id)
    zones = list(p.library) + list(p.hand) + list(p.graveyard) + list(p.exile)
    zones += [o for o in state.battlefield if o.owner_id == player_id]
    zones += [
        item.source for item in state.stack
        if getattr(item, "source", None) is not None
        and item.source.owner_id == player_id
    ]
    types: set[str] = set()
    for c in zones:
        if c.printing.is_creature and not c.printing.is_token:
            types.update(c.printing.subtypes)
    return sorted(types)


def apply_roto_land_as_enters(
    state: "GameState", player_id: int, card,
) -> None:
    """This bucket's "As this land enters, ..." choices (called from
    ``actions.apply_land_etb_replacements``)."""
    if card.printing.enters_choosing_creature_type:
        choose_creature_type_as_enters(state, player_id, card)


def choose_creature_type_as_enters(
    state: "GameState", player_id: int, card,
) -> None:
    """"As this land enters, choose a creature type." (Cavern of Souls):
    ``choose_mode`` over ``creature_types_owned_by``; with no creature
    card owned the choice is moot and recorded as ``None``."""
    options = creature_types_owned_by(state, player_id)
    card.chosen_creature_type = None
    if not options:
        state.log.append(f"{card.printing.name}: no creature type to choose")
        return
    idx = 0
    agent = state.player_by_id(player_id).agent
    if agent is not None and len(options) > 1:
        picked = agent.choose_mode(state, player_id, options)
        if isinstance(picked, int) and 0 <= picked < len(options):
            idx = picked
    card.chosen_creature_type = options[idx]
    state.log.append(
        f"{card.printing.name}: P{player_id} chooses {options[idx]}"
    )


# ---------------------------------------------------------------------------
# Mana effects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AddManaPerCardInTargetOpponentsHand(Effect):
    """"Add {C} for each card in target opponent's hand." (Jeska's Will).
    A spell mode, not a mana ability: it targets and uses the stack. The
    hand is counted as the spell resolves."""

    color: str = "R"

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int,
    ) -> list[Target]:
        return [
            ("player", p.id) for p in state.players
            if p.id != controller_id and not p.has_lost
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import ManaCoin

        if not targets or targets[0][0] != "player":
            return
        opp = next(
            (p for p in state.players if p.id == targets[0][1]), None,
        )
        if opp is None or opp.id == controller_id:
            return
        n = len(opp.hand)
        pool = state.player_by_id(controller_id).mana_pool
        pool.extend(ManaCoin(color=self.color) for _ in range(n))
        state.log.append(
            f"P{controller_id} adds {{{self.color}}}x{n} (cards in "
            f"P{opp.id}'s hand)"
        )

    def describe(self) -> str:
        return f"add {{{self.color}}} for each card in target opponent's hand"


@dataclass(frozen=True)
class AddAnyColorManaForChosenCreatureType(AddManaToPool):
    """"Add one mana of any color. Spend this mana only to cast a creature
    spell of the chosen type, and that spell can't be countered."
    (Cavern of Souls). An ``AddManaToPool`` (so it is a mana ability and
    is never folded into automatic payment) whose coin's restriction is
    read from the source's ``chosen_creature_type`` as it resolves."""

    produces: tuple = (("any", 1),)
    makes_spell_uncounterable: bool = True

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import ManaCoin

        src = state.resolving_source
        chosen = getattr(src, "chosen_creature_type", None) or ""
        state.player_by_id(controller_id).mana_pool.append(
            ManaCoin(
                color="any",
                spend_restriction=f"creature_type:{chosen}",
                makes_spell_uncounterable=True,
            )
        )
        state.log.append(
            f"P{controller_id} adds {{any}} (only for a {chosen or 'no'} "
            f"creature spell; it can't be countered)"
        )

    def describe(self) -> str:
        return (
            "add one mana of any color (only to cast a creature spell of "
            "the chosen type; that spell can't be countered)"
        )


# ---------------------------------------------------------------------------
# Cast permissions
# ---------------------------------------------------------------------------


def _source_power(state: "GameState") -> int:
    """The resolving source's power (last known information once it has
    left the battlefield: the object keeps its counters and the
    registry entries keyed to it until cleanup)."""
    from mtg_bot.game import effective_power

    src = state.resolving_source
    return effective_power(state, src) if src is not None else 0


@dataclass(frozen=True)
class MayCastTargetGraveyardCardFree(Effect):
    """"You may cast target <filter> card [with mana value less than or
    equal to this creature's power] from your graveyard without paying
    its mana cost. If that spell would be put into your graveyard, exile
    it instead." (Dreadhorde Arcanist). The target is a card in the
    controller's graveyard, re-checked (filter, mana value bound) on
    resolution; the spell is cast during the resolution (CR 608.2g,
    timing ignored) through ``creature_casting_ub.cast_now``."""

    card_filter: object = None
    mv_at_most_source_power: bool = False

    def _ok(self, state: "GameState", card) -> bool:
        if not self.card_filter.matches(card.printing):
            return False
        if self.mv_at_most_source_power:
            return card.printing.mana_cost.total <= _source_power(state)
        return True

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int,
    ) -> list[Target]:
        return [
            ("graveyard_card", c.id)
            for c in state.player_by_id(controller_id).graveyard
            if self._ok(state, c)
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.creature_casting_ub import can_cast_now, cast_now

        if not targets or targets[0][0] != "graveyard_card":
            return
        p = state.player_by_id(controller_id)
        card = next((c for c in p.graveyard if c.id == targets[0][1]), None)
        if card is None or not self._ok(state, card):
            state.log.append("graveyard cast target is no longer legal")
            return
        if not can_cast_now(state, controller_id, card, free=True):
            return
        if p.agent is not None and not p.agent.choose_yes_no(
            state, controller_id, f"Cast {card.printing.name} for free?",
        ):
            return
        card.exile_if_put_into_graveyard_from_stack = True
        cast_now(state, controller_id, card, free=True)

    def describe(self) -> str:
        bound = (
            " with mana value up to this creature's power"
            if self.mv_at_most_source_power else ""
        )
        return (
            f"you may cast target {self.card_filter.describe()}{bound} from "
            "your graveyard free; exile it instead of putting it into your "
            "graveyard"
        )


__all__ = [
    "AddAnyColorManaForChosenCreatureType",
    "MayCastTargetGraveyardCardFree",
    "AddManaPerCardInTargetOpponentsHand",
    "CardsNamedInAllGraveyards",
    "EnteredThisTurn",
]
