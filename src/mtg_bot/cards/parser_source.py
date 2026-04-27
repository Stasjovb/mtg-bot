"""Oracle-text parser card source.

Today this is a stub: it claims a small set of vanilla creatures and
returns their ``CardPrinting``s by passthrough from the static
registry. Trivial structural parity. The stub exists so the parity
harness has something concrete to exercise; it will be replaced by a
real text-driven parser that produces ``CardPrinting``s by reading
Scryfall ``oracle_text``.

Once the real parser is in place, ``claimed_names`` grows as new
templates come online. The structural parity test in
``tests/test_parser_parity.py`` is parametrized over
``claimed_names``, so each newly-claimed card immediately gates on
matching the static registry's printing.
"""

from __future__ import annotations

from mtg_bot.cards.base import CardPrinting


class StubParserCardSource:
    claimed_names: tuple[str, ...] = (
        "Battlefield Recruit",
        "Wild Bear",
        "Raging Goblin",
    )

    def get_printings(self) -> dict[str, CardPrinting]:
        from mtg_bot.cards.registry import all_printings

        all_p = all_printings()
        return {name: all_p[name] for name in self.claimed_names}

    def build_mono_color_deck(
        self, color: str, seed: int | None = None
    ) -> list[str]:
        raise NotImplementedError(
            "stub parser source does not build decks; wrap with "
            "FallbackCardSource(parser, StaticCardSource()) to delegate "
            "deck building to the static pool during parser build-out"
        )
