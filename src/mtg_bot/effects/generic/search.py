"""Generic effects cluster module. Behavior and API unchanged from
the pre-split mtg_bot.effects.generic monolith; this is a pure file move."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mtg_bot.effects.base import (
    Effect, Target, TriggeredAbility,
    _apply_damage, _multicolored_permanents_count,
    _find_moonlit_replacement_source,
)
from mtg_bot.effects.generic.targets_helpers import (
    _eff_subtypes,
    _slot_target_still_legal,
    _fizzle_message,
    _describe_targets,
    _describe_filter,
    _bounce_to_hand,
)

if TYPE_CHECKING:
    from mtg_bot.cards import ManaCost
    from mtg_bot.effects.formulas import Formula
    from mtg_bot.game import GameState


@dataclass(frozen=True)
class SearchLibraryForCard(Effect):
    """Search your library for a card matching the named filter, reveal
    it, put it into your hand, then shuffle.

    ``filter_name`` selects the filter applied to cards in the library:
      - ``"legendary_creature"`` — creature with Legendary supertype
      - ``"basic_plains"`` / ``"basic_island"`` / ... — specific basic
      - ``"creature_small"`` — creature with mana value ≤ ``max_mv``

    If ``may_fail`` is True, the controller may decline to fetch
    (shuffle happens either way). Always shuffles at the end — matches
    MTG wording.
    """

    filter_name: str
    max_mv: int = 0
    may_fail: bool = True

    def _matches(self, printing) -> bool:
        fn = self.filter_name
        if fn == "legendary_creature":
            return (
                printing.is_creature and "Legendary" in printing.supertypes
            )
        # Generic ``basic land card`` (any of the five basics) — Spineseeker
        # Centipede's ETB tutor. Distinct from the per-color
        # ``basic_plains`` / ``basic_island`` / ... filters which pin a
        # single basic by name.
        if fn == "basic_land":
            return printing.is_basic_land
        if fn.startswith("basic_"):
            wanted = fn[len("basic_"):].capitalize()
            return printing.is_basic_land and printing.name == wanted
        if fn == "creature_small":
            return (
                printing.is_creature
                and printing.mana_cost.total <= self.max_mv
            )
        if fn == "artifact":
            return printing.is_artifact
        if fn == "spacecraft":
            return printing.is_spacecraft
        if fn == "sliver":
            return "Sliver" in printing.subtypes
        # Demonic Counsel (Duskmourn) — tutor for a Demon creature
        # card. Mirrors the ``sliver`` shape (subtype-keyed filter on
        # creature printings); adding the filter here is purely
        # additive and reuses the existing tutor-via-subtype
        # convention.
        if fn == "demon":
            return "Demon" in printing.subtypes
        return False

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone, reveal_to_all, shuffle_library

        p = state.player_by_id(controller_id)
        options = [c for c in p.library if self._matches(c.printing)]
        if not options:
            state.log.append(
                f"P{controller_id} searches library — no "
                f"{self.filter_name} found"
            )
            shuffle_library(state, controller_id)
            return
        chosen_id = None
        if p.agent is not None:
            chosen_id = p.agent.choose_card_from_library(
                state, controller_id, [c.id for c in options]
            )
        if chosen_id is None:
            if self.may_fail:
                state.log.append(
                    f"P{controller_id} declines to fetch"
                )
                shuffle_library(state, controller_id)
                return
            chosen_id = options[0].id
        card = next((c for c in options if c.id == chosen_id), options[0])
        p.library.remove(card)
        card.zone = Zone.HAND
        p.hand.append(card)
        state.log.append(
            f"P{controller_id} fetches {card.printing.name} to hand"
        )
        reveal_to_all(state, card)
        shuffle_library(state, controller_id)

    def describe(self) -> str:
        return (
            f"search your library for a {self.filter_name} card, reveal "
            f"it, put it into your hand, then shuffle"
        )



@dataclass(frozen=True)
class SearchLibraryForBasicLandTapped(Effect):
    """Search the controller's library for up to ``count`` basic land
    cards, put them onto the battlefield tapped, then shuffle.

    Picks the FIRST ``count`` basic lands in library order (a
    deterministic stand-in for the player's free choice of which basic
    to fetch — the chosen card is hidden information, so picking the
    topmost match is strength-neutral). If fewer basic lands exist,
    puts what it finds.

    **Round-54 post-search shuffle restoration (SEARCH_LIMITATIONS
    #15 closure).** CR 701.19 / 701.22 require the library to be
    shuffled after a search, whether or not a card was found. Every
    sibling library-search Effect in this module
    (``SearchLibraryForCard`` / ``SearchLibraryForEquipmentToBattlefield``
    / ``SearchLibraryForGreenCreatureWithMVAtMostX``) already calls
    ``shuffle_library(state, controller_id)`` at the end of its
    ``resolve``; this Effect's prior omission was a Stage-3
    simplification (the now-removed "no extra shuffle" note). The Rust
    ``Effect::SearchLibraryForBasicLandTapped`` resolve arm has always
    shuffled post-search (SEARCH_LIMITATIONS #16). ``shuffle_library``
    calls ``state.rng.shuffle(p.library)``; when the cross-engine
    parity harness installs the SAME ``random.Random`` instance on
    ``state.rng`` (Python) and via ``GameState.set_external_rng`` (Rust
    — which Fisher-Yates over the identical ``_randbelow`` draw
    sequence per #16), the two engines' post-search library orders are
    byte-identical. In production (no shared rng installed) the shuffle
    is the CR-correct behavior with ``state.rng``'s own stream.
    """

    count: int = 1

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone, shuffle_library
        from mtg_bot.turn import fire_landfall_triggers

        p = state.player_by_id(controller_id)
        for _ in range(self.count):
            land = next(
                (c for c in p.library if c.printing.is_basic_land), None,
            )
            if land is None:
                state.log.append(
                    f"P{controller_id} searches but finds no more basic lands"
                )
                # CR 701.19 / 701.22: shuffle even when the search
                # finds nothing (matches the sibling search Effects'
                # no-match early-return shuffle, and the Rust arm which
                # always shuffles post-search). Mirrors #16.
                shuffle_library(state, controller_id)
                return
            p.library.remove(land)
            land.zone = Zone.BATTLEFIELD
            land.tapped = True
            land.controller_id = controller_id
            state.battlefield.append(land)
            state.log.append(
                f"P{controller_id} puts {land.printing.name} onto the "
                f"battlefield tapped"
            )
            # ``fire_landfall_triggers`` covers both the legacy
            # string-key path and the predicate-style ENTERS dispatch.
            fire_landfall_triggers(state, land)
        # CR 701.19 / 701.22 post-search shuffle (SEARCH_LIMITATIONS
        # #15 closure, round 54). Byte-equal to the Rust arm's
        # post-search Fisher-Yates when a shared rng is threaded (#16).
        shuffle_library(state, controller_id)

    def describe(self) -> str:
        if self.count == 1:
            return (
                "search your library for a basic land card, put it onto "
                "the battlefield tapped, then shuffle"
            )
        return (
            f"search your library for up to {self.count} basic land "
            f"cards, put them onto the battlefield tapped, then shuffle"
        )



@dataclass(frozen=True)
class SearchLibraryForEquipmentToBattlefield(Effect):
    """Search the controller's library for an Equipment card, put it
    onto the battlefield (untapped, under the controller's control),
    then shuffle.

    Models Honored Knight-Captain's activated tutor: ``{4}{W}{W},
    Sacrifice this creature: Search your library for an Equipment card,
    put it onto the battlefield, then shuffle.``

    The agent picks which Equipment via ``choose_card_from_library``.
    If no Equipment exists in library, the search fails and a shuffle
    still happens. The card enters via ``put_into_battlefield`` so any
    ETB triggers (e.g., the auto-attach riders on EoE Equipment) fire
    normally.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import put_into_battlefield
        from mtg_bot.game import shuffle_library

        p = state.player_by_id(controller_id)
        options = [
            c for c in p.library
            if "Equipment" in c.printing.subtypes
        ]
        if not options:
            state.log.append(
                f"P{controller_id} searches but finds no Equipment"
            )
            shuffle_library(state, controller_id)
            return
        chosen_id = None
        if p.agent is not None:
            chosen_id = p.agent.choose_card_from_library(
                state, controller_id, [c.id for c in options]
            )
        card = next(
            (c for c in options if c.id == chosen_id), options[0],
        )
        p.library.remove(card)
        state.log.append(
            f"P{controller_id} fetches {card.printing.name} to "
            f"battlefield (Honored Knight-Captain)"
        )
        put_into_battlefield(state, card, controller_id)
        shuffle_library(state, controller_id)

    def describe(self) -> str:
        return (
            "search your library for an Equipment card, put it onto "
            "the battlefield, then shuffle"
        )



@dataclass(frozen=True)
class SearchLibraryForGreenCreatureWithMVAtMostX(Effect):
    """Matches Green Sun's Zenith: "Search your library for a green
    creature card with mana value X or less, put it onto the battlefield,
    then shuffle." X is read from ``state.resolving_x_value``.

    Green creature: printing has "G" in ``mana_cost.colors``. Mana value
    uses ``mana_cost.total`` (includes the green pip). Declining to
    fetch is legal (matches the "search ... may fail" convention).
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import put_into_battlefield
        from mtg_bot.game import shuffle_library

        x = state.resolving_x_value
        p = state.player_by_id(controller_id)
        options = [
            c for c in p.library
            if c.printing.is_creature
            and "G" in c.printing.mana_cost.colors
            and c.printing.mana_cost.total <= x
        ]
        if not options:
            state.log.append(
                f"P{controller_id} searches for a green creature with "
                f"MV ≤ {x} — none found"
            )
            shuffle_library(state, controller_id)
            return
        chosen_id = None
        if p.agent is not None:
            chosen_id = p.agent.choose_card_from_library(
                state, controller_id, [c.id for c in options]
            )
        if chosen_id is None:
            state.log.append(
                f"P{controller_id} declines to fetch from Green Sun's Zenith"
            )
            shuffle_library(state, controller_id)
            return
        card = next((c for c in options if c.id == chosen_id), options[0])
        p.library.remove(card)
        state.log.append(
            f"P{controller_id} fetches {card.printing.name} onto the battlefield"
        )
        put_into_battlefield(state, card, controller_id)
        shuffle_library(state, controller_id)

    def describe(self) -> str:
        return (
            "search your library for a green creature card with mana "
            "value X or less, put it onto the battlefield, then shuffle"
        )
