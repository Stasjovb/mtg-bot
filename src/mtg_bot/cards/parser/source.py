"""``OracleParserCardSource`` — top-level card source backed by the
oracle-text parser.

Walks the active card pool (see ``mtg_bot.cards.pools`` — the
``MTG_BOT_CARD_POOL`` env var picks ``all`` / ``cube`` / ``eoe``) once
at construction, asks each of the per-card-type builders to attempt a
printing, and stores every success in a name-keyed dict. The parser's "claimed_names" property
lists exactly which cards the parser handles end-to-end today; the
structural-parity gate in ``tests/test_parser_parity.py`` runs against
every name in that tuple.
"""

from __future__ import annotations

from dataclasses import replace

from mtg_bot.cards.base import CardPrinting
from mtg_bot.cards.parser.printing_keywords import _parse_cycling_line
from mtg_bot.cards.parser.text import _strip_reminder_text
from mtg_bot.cards.pools import load_pool_cards, resolve_pool_name, active_pool_name
from mtg_bot.cards.parser.artifact_builder import _build_artifact_printing
from mtg_bot.cards.parser.creature_builder import _build_creature_printing
from mtg_bot.cards.parser.equipment_builder import _build_equipment_printing
from mtg_bot.cards.parser.land_builder import _build_land_printing
from mtg_bot.cards.parser.spacecraft_builder import _build_spacecraft_printing
from mtg_bot.cards.parser.enchantment_builder import (
    _build_enchantment_printing,
)
from mtg_bot.cards.parser.room_builder import _build_room_printing
from mtg_bot.cards.parser.planeswalker_builder import (
    _build_planeswalker_printing,
)
from mtg_bot.cards.parser.spell_builder import _build_spell_printing
from mtg_bot.cards.parser.layout_builder import _build_layout_printing


def _load_scryfall_data(pool: str | None = None) -> list[dict]:
    """Raw Scryfall records for ``pool`` (``None`` -> env-selected)."""
    return load_pool_cards(pool)


_BASIC_LAND_TYPES = frozenset({"Plains", "Island", "Swamp", "Mountain", "Forest"})


def _split_hand_abilities(card: dict) -> tuple[dict, tuple]:
    """Peel the hand-activated keyword lines (cycling family) off a
    single-faced card's oracle text. Returns the card with those lines
    removed (so every per-type builder sees only its own grammar) and
    the parsed ``ActivatedAbility`` tuple for
    ``CardPrinting.hand_activated_abilities``."""
    text = card.get("oracle_text")
    if not text or card.get("card_faces"):
        return card, ()
    if "Land" in card.get("type_line", ""):
        # Land lines own their Cycling grammar (``parser.land_lines``).
        return card, ()
    kept: list[str] = []
    abilities = []
    for raw in text.split("\n"):
        ability = _parse_cycling_line(_strip_reminder_text(raw))
        if ability is None:
            kept.append(raw)
        else:
            abilities.append(ability)
    if not abilities:
        return card, ()
    stripped = dict(card)
    stripped["oracle_text"] = "\n".join(kept)
    return stripped, tuple(abilities)


def _with_hand_abilities(printing: CardPrinting, abilities: tuple) -> CardPrinting:
    if not abilities:
        return printing
    landcycling = printing.landcycling
    if landcycling is None:
        for ab in abilities:
            subs = getattr(ab.effect, "subtypes", ())
            if len(subs) == 1 and subs[0] in _BASIC_LAND_TYPES:
                landcycling = (subs[0], ab.cost.mana_str)
                break
    return replace(
        printing,
        hand_activated_abilities=(
            tuple(printing.hand_activated_abilities) + tuple(abilities)
        ),
        landcycling=landcycling,
    )


def _build_printing(card: dict) -> CardPrinting | None:
    """Run the per-card-type builders in claim order.

    The cube-creatures grammar (``creature_rmc_grammar``) is switched off
    for printings that exist only in the EoE-era dumps, keeping the EoE
    claimed set (the parity evidence base) unchanged."""
    from mtg_bot.cards.parser.creature_rmc_grammar import (
        is_eoe_only_printing,
        rmc_grammar_disabled,
    )

    if is_eoe_only_printing(card.get("name", "")):
        with rmc_grammar_disabled():
            return _run_builders(card)
    return _run_builders(card)


def _run_builders(card: dict) -> CardPrinting | None:
    """The cube W/G creature grammar is pinned off for a few EoE-pool
    printings whose claim it would otherwise change
    (``creature_wg_effects.EOE_PINNED_NAMES``)."""
    from mtg_bot.cards.parser.creature_wg_effects import wg_grammar_pinned_off

    with wg_grammar_pinned_off(card.get("name", "")):
        return _build_printing_unpinned(card)


# Multi-face layouts whose faces the per-type builders model themselves:
# Duskmourn Rooms (``split``) and spell // land modal DFCs.
_FACE_AWARE_LAYOUTS = frozenset({"split", "modal_dfc"})


def _build_printing_unpinned(card: dict) -> CardPrinting | None:
    built = _build_layout_printing(card)
    if built is not None:
        return built
    if card.get("card_faces") and card.get("layout") not in _FACE_AWARE_LAYOUTS:
        # Unmodeled faces: never claim the card as a silent vanilla built
        # from the face-less top-level record.
        return None
    for builder in (
        _build_room_printing,
        _build_enchantment_printing,
        _build_planeswalker_printing,
        _build_creature_printing,
        _build_spell_printing,
        _build_land_printing,
        _build_equipment_printing,
        _build_spacecraft_printing,
        _build_artifact_printing,
    ):
        built = builder(card)
        if built is not None:
            return built
    return None


class OracleParserCardSource:
    def __init__(self, pool: str | None = None) -> None:
        self._pool_name = (
            resolve_pool_name(pool) if pool is not None else active_pool_name()
        )
        printings: dict[str, CardPrinting] = {}
        for card in _load_scryfall_data(self._pool_name):
            body, hand_abilities = _split_hand_abilities(card)
            built = _build_printing(body)
            if built is not None:
                printings[card["name"]] = _with_hand_abilities(
                    built, hand_abilities,
                )
        self._printings = printings

    @property
    def pool_name(self) -> str:
        """Which registered pool this source was built from."""
        return self._pool_name

    @property
    def claimed_names(self) -> tuple[str, ...]:
        return tuple(self._printings)

    def get_printings(self) -> dict[str, CardPrinting]:
        return dict(self._printings)
