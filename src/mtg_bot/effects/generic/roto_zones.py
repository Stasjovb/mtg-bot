"""Engine effects for the Vintage Roto P2 package: library, graveyard
and hand (``docs/ROTO_COVERAGE_PLAN.md`` section 2).

Grammar lives in :mod:`mtg_bot.cards.parser.roto_zones`; every class
here models one printed shape faithfully (shortcuts are listed in
``docs/SEARCH_LIMITATIONS.md`` under "Roto P2").

Library searches made by this module's effects go through
:func:`search_pick`, the one place a P2 search picks a card.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mtg_bot.effects.base import Effect, Target
from mtg_bot.effects.generic.card_flow import CardFilter
from mtg_bot.effects.generic.targeted_removal import RemovalRider

if TYPE_CHECKING:
    from mtg_bot.cards.base import CardPrinting
    from mtg_bot.game import GameObject, GameState, Player


# ---------------------------------------------------------------------
# Card filters
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class RotoCardFilter(CardFilter):
    """:class:`CardFilter` plus the descriptor words the roto tutors and
    reanimation spells print on top of the base grammar:

    * ``excluded_supertypes`` -- "a nonlegendary card" (Unmarked Grave,
      Persist).
    * ``max_power`` / ``max_toughness`` -- "a creature card with power 2
      or less" (Imperial Recruiter, Reveillark) / "with toughness 2 or
      less" (Recruiter of the Guard). A card with no printed power (a
      ``*`` or a noncreature) has power 0 in every zone but the stack
      and battlefield (CR 208.3), so it matches.
    """

    excluded_supertypes: tuple[str, ...] = ()
    max_power: "int | None" = None
    max_toughness: "int | None" = None

    @property
    def has_quality(self) -> bool:
        return (
            super().has_quality
            or bool(self.excluded_supertypes)
            or self.max_power is not None
            or self.max_toughness is not None
        )

    def matches(self, printing: "CardPrinting") -> bool:
        if not super().matches(printing):
            return False
        for s in self.excluded_supertypes:
            if s in printing.supertypes:
                return False
        if self.max_power is not None and (printing.power or 0) > self.max_power:
            return False
        if (
            self.max_toughness is not None
            and (printing.toughness or 0) > self.max_toughness
        ):
            return False
        return True

    def describe(self) -> str:
        text = super().describe()
        for s in self.excluded_supertypes:
            text = f"non{s.lower()} {text}"
        if self.max_power is not None:
            text += f" with power {self.max_power} or less"
        if self.max_toughness is not None:
            text += f" with toughness {self.max_toughness} or less"
        return text


# ---------------------------------------------------------------------
# Library search helper
# ---------------------------------------------------------------------


def search_pick(
    state: "GameState", searcher: "Player", options: list,
    *, may_fail: bool,
) -> "GameObject | None":
    """The searching player's pick among ``options`` (cards in their
    library matching the search's description). ``may_fail`` is CR
    701.19b: a search for a card with a stated quality may find nothing
    even when one is there (the agent returns ``None``); a search for
    just "a card" finds one whenever the library has any."""
    if not options:
        return None
    picked = None
    if searcher.agent is not None:
        picked = searcher.agent.choose_card_from_library(
            state, searcher.id, [c.id for c in options],
        )
    chosen = next((c for c in options if c.id == picked), None)
    if chosen is None and not may_fail:
        chosen = options[0]
    return chosen


# ---------------------------------------------------------------------
# Tutors (F10)
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class SearchToHandDiscardAtRandomThenShuffle(Effect):
    """"Search your library for <a card>, put that card into your hand,
    discard a card at random, then shuffle." (Gamble.) The random
    discard is from the whole hand -- it may be the card just found."""

    card_filter: CardFilter = CardFilter()

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.effects.generic.card_flow import discard_card
        from mtg_bot.game import Zone, reveal_to, shuffle_library

        p = state.player_by_id(controller_id)
        options = [c for c in p.library if self.card_filter.matches(c.printing)]
        found = search_pick(
            state, p, options, may_fail=self.card_filter.has_quality,
        )
        if found is not None:
            p.library.remove(found)
            found.zone = Zone.HAND
            p.hand.append(found)
            reveal_to(found, controller_id)
            state.log.append(f"P{controller_id} tutors a card into hand")
        if p.hand:
            card = p.hand[state.rng.randrange(len(p.hand))]
            discard_card(state, p, card)
        shuffle_library(state, controller_id)

    def describe(self) -> str:
        return (
            f"search your library for a {self.card_filter.describe()}, put "
            f"it into your hand, discard a card at random, then shuffle"
        )


@dataclass(frozen=True)
class SearchOntoBattlefieldTappedUntapIfLands(Effect):
    """"Search your library for <a basic land card>, put it onto the
    battlefield tapped, then shuffle. Then if you control N or more
    lands, untap that land." (Fabled Passage.) The land count is taken
    after the found land is on the battlefield."""

    card_filter: CardFilter = CardFilter()
    min_lands: int = 4

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.actions import put_into_battlefield
        from mtg_bot.game import shuffle_library

        p = state.player_by_id(controller_id)
        options = [c for c in p.library if self.card_filter.matches(c.printing)]
        found = search_pick(
            state, p, options, may_fail=self.card_filter.has_quality,
        )
        if found is not None:
            p.library.remove(found)
            state.log.append(
                f"P{controller_id} puts {found.printing.name} onto the "
                f"battlefield tapped"
            )
            put_into_battlefield(state, found, controller_id)
            if found in state.battlefield:
                found.tapped = True
        shuffle_library(state, controller_id)
        if found is None or found not in state.battlefield:
            return
        lands = sum(
            1 for o in state.battlefield
            if o.controller_id == controller_id and o.printing.is_land
        )
        if lands >= self.min_lands:
            found.tapped = False
            state.log.append(f"{found.printing.name} untaps")

    def describe(self) -> str:
        return (
            f"search your library for a {self.card_filter.describe()}, put "
            f"it onto the battlefield tapped, then shuffle; then if you "
            f"control {self.min_lands} or more lands, untap that land"
        )


@dataclass(frozen=True)
class SearchAnyNumberTotalManaValueOntoBattlefield(Effect):
    """"Search your library for any number of <creature> cards with total
    mana value N or less, put them onto the battlefield, then shuffle."
    (Protean Hulk.) Picks go one at a time through
    ``choose_card_from_library`` (``None`` stops); each pick is limited
    to cards that still fit the remaining mana-value budget."""

    card_filter: CardFilter = CardFilter()
    max_total_mv: int = 6

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.actions import put_into_battlefield
        from mtg_bot.game import shuffle_library

        p = state.player_by_id(controller_id)
        budget = self.max_total_mv
        found = []
        while True:
            options = [
                c for c in p.library
                if self.card_filter.matches(c.printing)
                and c.printing.mana_cost.total <= budget
            ]
            pick = search_pick(state, p, options, may_fail=True)
            if pick is None:
                break
            p.library.remove(pick)
            found.append(pick)
            budget -= pick.printing.mana_cost.total
        for card in found:
            put_into_battlefield(state, card, controller_id)
        shuffle_library(state, controller_id)
        state.log.append(
            f"P{controller_id} puts {len(found)} card(s) with total mana "
            f"value {self.max_total_mv - budget} onto the battlefield"
        )

    def describe(self) -> str:
        return (
            f"search your library for any number of "
            f"{self.card_filter.describe()}s with total mana value "
            f"{self.max_total_mv} or less, put them onto the battlefield, "
            f"then shuffle"
        )


@dataclass(frozen=True)
class ExileSourceCardFromGraveyard(Effect):
    """"[You may] exile it." in a dies trigger: exile the card that went
    to the graveyard (the trigger's source). Returns ``False`` when the
    card is no longer in its owner's graveyard (it left, so it can't be
    exiled and an "If you do" rider doesn't happen)."""

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.game import Zone

        card = state.resolving_source
        if card is None:
            return False
        owner = state.player_by_id(card.owner_id)
        if card not in owner.graveyard:
            return False
        owner.graveyard.remove(card)
        card.zone = Zone.EXILE
        owner.exile.append(card)
        state.log.append(f"{card.printing.name} is exiled from the graveyard")
        return True

    def describe(self) -> str:
        return "exile it"


@dataclass(frozen=True)
class ControllerMaySearchOntoBattlefield(RemovalRider):
    """"Its controller may search their library for <a basic land card>,
    put it onto the battlefield[ tapped], then shuffle." (Ghost Quarter's
    untapped search; the tapped Path to Exile form is the base's
    ``ControllerSearchesForBasicLand``.) The removed permanent's last
    controller decides (``choose_yes_no``) and picks the card; declining
    skips the search and the shuffle."""

    card_filter: CardFilter = CardFilter()
    tapped: bool = False

    def apply(self, state, info):
        from mtg_bot.actions import put_into_battlefield
        from mtg_bot.game import shuffle_library

        pid = info.controller_id
        p = state.player_by_id(pid)
        if p.has_lost:
            return
        if p.agent is not None and not p.agent.choose_yes_no(
            state, pid, f"search your library for a {self.card_filter.describe()}?",
        ):
            state.log.append(f"P{pid} declines to search")
            return
        options = [c for c in p.library if self.card_filter.matches(c.printing)]
        found = search_pick(state, p, options, may_fail=True)
        if found is not None:
            p.library.remove(found)
            state.log.append(
                f"P{pid} puts {found.printing.name} onto the battlefield"
            )
            put_into_battlefield(state, found, pid)
            if self.tapped and found in state.battlefield:
                found.tapped = True
        shuffle_library(state, pid)

    def describe(self) -> str:
        tapped = " tapped" if self.tapped else ""
        return (
            f"its controller may search their library for a "
            f"{self.card_filter.describe()}, put it onto the battlefield"
            f"{tapped}, then shuffle"
        )


# ---------------------------------------------------------------------
# Graveyard hate & exile-instead replacement (F12)
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class GraveyardExileInstead:
    """A ``CardPrinting.zone_replacements`` spec: "If <what> would be put
    into <whose> graveyard[ from anywhere], exile it instead."

    * ``opponents_only`` -- "an opponent's graveyard" (Leyline of the
      Void): only cards owned by the source's controller's opponents.
    * ``tokens`` -- tokens are affected too ("a card or token", Rest in
      Peace; "a ... permanent", Sanctifier en-Vec). A token exiled this
      way never dies; it then ceases to exist.
    * ``colors`` -- only objects of one of these colors ("a black or red
      permanent, spell, or card not on the battlefield"); empty = any.

    Copies of spells are neither cards nor tokens and are never
    affected (they cease to exist anyway, CR 707.10a).
    """

    opponents_only: bool = False
    tokens: bool = False
    colors: frozenset = frozenset()

    def affects(self, state, source, obj) -> bool:
        from mtg_bot.game import effective_colors

        if getattr(obj, "is_spell_copy", False):
            return False
        if obj.printing.is_token and not self.tokens:
            return False
        if self.opponents_only and obj.owner_id == source.controller_id:
            return False
        if self.colors and not (effective_colors(state, obj) & self.colors):
            return False
        return True

    def affects_player(self, source, player_id: int) -> bool:
        return not (self.opponents_only and player_id == source.controller_id)

    def describe(self) -> str:
        what = "a card or token" if self.tokens else "a card"
        if self.colors:
            what = "a " + " or ".join(sorted(self.colors)) + " object"
        whose = "an opponent's" if self.opponents_only else "a"
        return f"if {what} would be put into {whose} graveyard, exile it instead"


def _exile_instead_sources(state):
    """``(source, spec)`` for every battlefield permanent with an active
    exile-instead replacement (a source that lost all abilities has
    none)."""
    from mtg_bot.game import _source_layer6_wiped

    out = []
    for o in state.battlefield:
        for spec in o.printing.zone_replacements:
            if isinstance(spec, GraveyardExileInstead) and not (
                state.continuous_effects and _source_layer6_wiped(state, o)
            ):
                out.append((o, spec))
    return out


def graveyard_exile_instead_applies(state, obj) -> bool:
    """Would ``obj`` (a card or token about to be put into a graveyard)
    be exiled instead? Consulted by ``turn.move_off_battlefield`` (so an
    affected creature never dies), ``actions._send_to_graveyard_or_
    library`` (spells leaving the stack) and this module's own
    graveyard moves; :func:`apply_graveyard_exile_instead` catches every
    other path."""
    return any(
        spec.affects(state, src, obj) for src, spec in _exile_instead_sources(state)
    )


def exile_instead_of_graveyard(state, card) -> None:
    """Put ``card`` (already out of its previous zone) into its owner's
    exile, replacing a move to the graveyard."""
    from mtg_bot.game import Zone

    card.zone = Zone.EXILE
    state.player_by_id(card.owner_id).exile.append(card)
    state.log.append(f"{card.printing.name} is exiled instead of going to a graveyard")


def put_into_graveyard(state, card) -> None:
    """Move ``card`` (already out of its previous zone) to its owner's
    graveyard, or into exile if an exile-instead replacement applies.
    Used by this module's effects so their own graveyard moves honor the
    replacement immediately."""
    from mtg_bot.game import Zone

    if graveyard_exile_instead_applies(state, card):
        exile_instead_of_graveyard(state, card)
        return
    card.zone = Zone.GRAVEYARD
    state.player_by_id(card.owner_id).graveyard.append(card)


def note_exile_instead_source_entered(state, obj) -> None:
    """An exile-instead source entered the battlefield: the cards
    already in the graveyards it affects stay (the replacement applies
    only from now on); snapshot them for the SBA catch-all."""
    for spec in obj.printing.zone_replacements:
        if not isinstance(spec, GraveyardExileInstead):
            continue
        for p in state.players:
            if spec.affects_player(obj, p.id):
                p.graveyard_exile_instead_snapshot = frozenset(
                    c.id for c in p.graveyard
                )


def apply_graveyard_exile_instead(state) -> bool:
    """State-based catch-all for the exile-instead replacements: an
    affected card that reached a graveyard through a path that doesn't
    consult the replacement directly (discard, mill, ...) is exiled.
    Cards that were already there when the replacement began applying
    (``Player.graveyard_exile_instead_snapshot``) stay; the snapshot is
    pruned to the current graveyard so a card that leaves and comes back
    is caught."""
    sources = _exile_instead_sources(state)
    if not sources:
        return False
    changed = False
    for p in state.players:
        snap = p.graveyard_exile_instead_snapshot
        movers = [
            c for c in p.graveyard
            if c.id not in snap
            and any(spec.affects(state, src, c) for src, spec in sources)
        ]
        for c in movers:
            p.graveyard.remove(c)
            exile_instead_of_graveyard(state, c)
            changed = True
        p.graveyard_exile_instead_snapshot = frozenset(
            c.id for c in p.graveyard if c.id in snap
        )
    return changed


@dataclass(frozen=True)
class ExileTargetPlayersGraveyard(Effect):
    """"Exile target player's graveyard." (Bojuka Bog.)"""

    def requires_target(self) -> bool:
        return True

    def legal_targets(self, state, controller_id):
        return [("player", p.id) for p in state.players if not p.has_lost]

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.game import Zone

        p = next(
            (state.player_by_id(t[1]) for t in targets if t[0] == "player"),
            None,
        )
        if p is None or p.has_lost:
            return
        n = len(p.graveyard)
        for c in list(p.graveyard):
            p.graveyard.remove(c)
            c.zone = Zone.EXILE
            p.exile.append(c)
        state.log.append(f"P{p.id}'s graveyard is exiled ({n} cards)")

    def describe(self) -> str:
        return "exile target player's graveyard"


@dataclass(frozen=True)
class ExileGraveyardCardsOfColors(Effect):
    """"Exile all cards that are <black or red> from all graveyards."
    (Sanctifier en-Vec.)"""

    colors: frozenset = frozenset()

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.game import Zone, effective_colors

        n = 0
        for p in state.players:
            for c in list(p.graveyard):
                if effective_colors(state, c) & self.colors:
                    p.graveyard.remove(c)
                    c.zone = Zone.EXILE
                    p.exile.append(c)
                    n += 1
        state.log.append(f"{n} card(s) exiled from all graveyards")

    def describe(self) -> str:
        return (
            "exile all cards that are " + " or ".join(sorted(self.colors))
            + " from all graveyards"
        )
