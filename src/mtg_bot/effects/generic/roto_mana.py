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
        from mtg_bot.game import _CowList

        if isinstance(p.graveyard, _CowList):
            # The flags below mutate a graveyard card in place: isolate
            # this state's graveyard from search clones first.
            p.graveyard.fork()
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


def _top_card_kind_matches(state: "GameState", card, kinds) -> bool:
    from mtg_bot.game import effective_colors

    if card.printing.is_land:
        return False
    if "artifact" in kinds and card.printing.is_artifact:
        return True
    return "colorless" in kinds and not effective_colors(state, card)


def top_of_library_cast_allowed(
    state: "GameState", player_id: int, card,
) -> bool:
    """"You may cast <kind> spells from the top of your library." (Mystic
    Forge's ``cast_from_top_of_library_kinds``): ``card`` is the top of
    ``player_id``'s library and a permanent they control grants its
    kind."""
    p = state.player_by_id(player_id)
    if not p.library or p.library[0] is not card:
        return False
    return any(
        o.controller_id == player_id
        and o.printing.cast_from_top_of_library_kinds
        and _top_card_kind_matches(
            state, card, o.printing.cast_from_top_of_library_kinds,
        )
        for o in state.battlefield
    )


def _castable_now(state: "GameState", player_id: int, card, *, free: bool) -> bool:
    """Targets, additional costs and (unless free) the mana cost of
    casting ``card`` from outside the hand are all satisfiable."""
    from mtg_bot.actions import apply_cost_reductions
    from mtg_bot.creature_casting_ub import casting_origin
    from mtg_bot.game import Zone
    from mtg_bot.legal import (
        _additional_costs_payable, _can_cast, _targets_are_satisfiable,
    )

    if not (
        _targets_are_satisfiable(state, player_id, card)
        and _additional_costs_payable(state, player_id, card)
    ):
        return False
    if free:
        return True
    with casting_origin(
        card.zone != Zone.HAND, from_graveyard=card.zone == Zone.GRAVEYARD,
    ):
        cost = apply_cost_reductions(
            card.printing, state, player_id, card.printing.mana_cost,
        )
    return _can_cast(state, player_id, card, cost)


def _instant_speed(card) -> bool:
    return card.printing.is_instant or "flash" in card.printing.keywords


def permission_cast_actions(
    state: "GameState", player_id: int, existing: list, *,
    sorcery_timing: bool,
) -> list:
    """``CastSpell`` actions granted by this bucket's cast permissions
    (the single ``legal._legal_actions_core`` hook, placed before the
    instant-speed early return so every later restriction filter sees
    them). At sorcery timing every permitted cast is offered; otherwise
    only instants and flash cards. Actions already in ``existing`` are
    not repeated."""
    from mtg_bot.actions import CastSpell

    out: list = []
    seen = set(existing)

    def _emit(action) -> None:
        if action not in seen:
            seen.add(action)
            out.append(action)

    p = state.player_by_id(player_id)
    # Suspend (CR 702.62a): the special action from hand.
    seen_suspend: set[str] = set()
    for card in p.hand:
        if card.printing.name in seen_suspend:
            continue
        if suspend_castable(
            state, player_id, card, sorcery_timing=sorcery_timing,
        ):
            seen_suspend.add(card.printing.name)
            _emit(CastSpell(card.id, use_suspend=True))
    # Mystic Forge: the top card of the library.
    if p.library:
        top = p.library[0]
        if (
            (sorcery_timing or _instant_speed(top))
            and top_of_library_cast_allowed(state, player_id, top)
            and _castable_now(state, player_id, top, free=False)
        ):
            _emit(CastSpell(top.id))
    return out


# ---------------------------------------------------------------------------
# Library effects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExileTopCardsOfYourLibrary(Effect):
    """"Exile the top [N] card[s] of your library." (Mystic Forge's
    ``{T}, Pay 1 life`` ability) -- face up, no play permission."""

    count: int = 1

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        p = state.player_by_id(controller_id)
        for _ in range(min(self.count, len(p.library))):
            card = p.library.pop(0)
            card.zone = Zone.EXILE
            p.exile.append(card)
            state.log.append(
                f"P{controller_id} exiles {card.printing.name} from the top "
                "of their library"
            )

    def describe(self) -> str:
        return f"exile the top {self.count} card(s) of your library"


@dataclass(frozen=True)
class ExileHandDrawThatManyMayPlayThem(Effect):
    """"Exile all the cards from your hand, then draw that many cards.
    Until the end of your next turn, you may play cards exiled this way."
    (Hex Magic): each exiled card carries an exile play permission
    (``UNTIL_END_OF_YOUR_NEXT_TURN``, normal costs, lands playable with a
    land drop)."""

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.effects.generic.cube_creatures_rmc import (
            UNTIL_END_OF_YOUR_NEXT_TURN,
            grant_exile_play,
        )
        from mtg_bot.game import Zone
        from mtg_bot.turn import draw_card

        p = state.player_by_id(controller_id)
        exiled = list(p.hand)
        for card in exiled:
            p.hand.remove(card)
            card.zone = Zone.EXILE
            p.exile.append(card)
            grant_exile_play(
                state, card, controller_id,
                duration=UNTIL_END_OF_YOUR_NEXT_TURN,
            )
        state.log.append(
            f"P{controller_id} exiles their hand ({len(exiled)} cards); may "
            "play them until the end of their next turn"
        )
        for _ in range(len(exiled)):
            draw_card(state, controller_id)

    def describe(self) -> str:
        return (
            "exile your hand, then draw that many; until the end of your "
            "next turn, you may play the exiled cards"
        )


# ---------------------------------------------------------------------------
# Suspend (CR 702.62)
# ---------------------------------------------------------------------------


def is_suspended(card) -> bool:
    """CR 702.62b: a card is suspended if it's in exile, has suspend and
    has a time counter on it."""
    from mtg_bot.game import Zone

    return (
        card.zone == Zone.EXILE
        and card.printing.suspend_count > 0
        and card.time_counters > 0
    )


def suspend_castable(state: "GameState", player_id: int, card, *,
                     sorcery_timing: bool) -> bool:
    """Could ``player_id`` suspend ``card`` from their hand now: "If you
    could begin to cast this card by putting it onto the stack from your
    hand" (its normal timing permission) and the suspend cost is
    payable."""
    pr = card.printing
    if pr.suspend_count <= 0 or pr.suspend_cost is None:
        return False
    if not (sorcery_timing or _instant_speed(card)):
        return False
    from mtg_bot.actions import can_pay_cost

    return can_pay_cost(state, player_id, pr.suspend_cost, sac_for_mana=True)


def suspend_card(state: "GameState", player_id: int, card_id: int) -> None:
    """The suspend special action (CR 702.62a, CR 116.2f): pay the suspend
    cost and exile the card from hand face up with N time counters. It
    doesn't use the stack and isn't a cast."""
    from mtg_bot.actions import (
        _activate_sac_for_mana_for_cost,
        auto_tap_for_cost,
    )
    from mtg_bot.game import Zone, reveal_to_all

    p = state.player_by_id(player_id)
    card = next((c for c in p.hand if c.id == card_id), None)
    if card is None or card.printing.suspend_count <= 0:  # pragma: no cover - legal_actions gates
        raise ValueError(f"card {card_id} can't be suspended by P{player_id}")
    cost = _activate_sac_for_mana_for_cost(
        state, player_id, card.printing.suspend_cost, frozenset({"spell"}),
    )
    auto_tap_for_cost(state, player_id, cost, spell_kind=frozenset({"spell"}))
    p.hand.remove(card)
    card.zone = Zone.EXILE
    card.time_counters = card.printing.suspend_count
    p.exile.append(card)
    reveal_to_all(state, card)
    state.log.append(
        f"P{player_id} suspends {card.printing.name} with "
        f"{card.time_counters} time counters ({card.printing.suspend_cost_str})"
    )


@dataclass(frozen=True)
class RemoveTimeCounterFromSuspendedSource(Effect):
    """Suspend's upkeep trigger: "At the beginning of your upkeep, if this
    card is suspended, remove a time counter from it." (the intervening
    "if" is re-checked on resolution). Removing the last counter triggers
    ``CastSuspendedSourceFree``. Also the effect of Greater Gargadon's
    "Remove a time counter from this card."."""

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        card = state.resolving_source
        if card is None or not is_suspended(card):
            return
        remove_time_counter(state, card)

    def describe(self) -> str:
        return "remove a time counter from this suspended card"


def _fork_exile_of(state: "GameState", card) -> None:
    from mtg_bot.game import _CowList

    exile = state.player_by_id(card.owner_id).exile
    if isinstance(exile, _CowList):
        exile.fork()


def remove_time_counter(state: "GameState", card) -> None:
    """Remove one time counter from a suspended ``card``; when it was the
    last, its "When the last time counter is removed" trigger goes on the
    stack (CR 702.62a)."""
    from mtg_bot.actions import push_triggered_ability
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import Always, Event

    _fork_exile_of(state, card)
    card.time_counters -= 1
    state.log.append(
        f"{card.printing.name}: a time counter is removed "
        f"({card.time_counters} left)"
    )
    if card.time_counters == 0:
        push_triggered_ability(
            state,
            source=card,
            ability=TriggeredAbility(
                event=Event.BEGINNING_OF_UPKEEP, predicate=Always(),
                effect=CastSuspendedSourceFree(),
            ),
            ability_index=-1,
            controller_id=card.owner_id,
            label="suspend (last time counter)",
        )


@dataclass(frozen=True)
class CastSuspendedSourceFree(Effect):
    """"When the last time counter is removed from this card, if it's
    exiled, you may cast it without paying its mana cost if able. If you
    don't, it remains exiled. If you cast a creature spell this way, it
    gains haste until you lose control of the spell or the permanent it
    becomes." (CR 702.62a). Cast during the resolution through
    ``creature_casting_ub.cast_now`` (timing ignored, CR 608.2g)."""

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.creature_casting_ub import can_cast_now, cast_now
        from mtg_bot.game import Zone

        card = state.resolving_source
        if card is None or card.zone != Zone.EXILE:
            return
        if card not in state.player_by_id(card.owner_id).exile:
            return
        if not can_cast_now(state, controller_id, card, free=True):
            state.log.append(f"{card.printing.name} can't be cast; stays exiled")
            return
        p = state.player_by_id(controller_id)
        if p.agent is not None and not p.agent.choose_yes_no(
            state, controller_id,
            f"Cast suspended {card.printing.name} for free?",
        ):
            return
        if card.printing.is_creature:
            state.add_continuous_effect(
                source_id=card.id, layer=6, kind="grant_keyword",
                target_id=card.id, params=("haste",),
                description=f"{card.printing.name} has haste (suspend)",
            )
        cast_now(state, controller_id, card, free=True)

    def describe(self) -> str:
        return "you may cast this suspended card without paying its mana cost"


def push_suspend_upkeep_triggers(state: "GameState") -> None:
    """At the beginning of the active player's upkeep, each card they own
    that is suspended triggers (the single ``turn`` upkeep hook)."""
    from mtg_bot.actions import push_triggered_ability
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import Always, Event

    ap = state.active_player()
    for card in list(ap.exile):
        if card.owner_id != ap.id or not is_suspended(card):
            continue
        push_triggered_ability(
            state,
            source=card,
            ability=TriggeredAbility(
                event=Event.BEGINNING_OF_UPKEEP, predicate=Always(),
                effect=RemoveTimeCounterFromSuspendedSource(),
            ),
            ability_index=-1,
            controller_id=ap.id,
            label="suspend upkeep",
        )


__all__ = [
    "AddAnyColorManaForChosenCreatureType",
    "CastSuspendedSourceFree",
    "RemoveTimeCounterFromSuspendedSource",
    "ExileHandDrawThatManyMayPlayThem",
    "ExileTopCardsOfYourLibrary",
    "MayCastTargetGraveyardCardFree",
    "AddManaPerCardInTargetOpponentsHand",
    "CardsNamedInAllGraveyards",
    "EnteredThisTurn",
]
