"""Read a pasted decklist into card names.

Accepted lines: ``4 Island``, ``4x Island``, ``Island`` (one copy), and
MTG Arena / MTGO exports (``4 Island (M21) 263``). Blank lines, ``#`` /
``//`` comments and section headers (``Deck``, ``Commander``, ...) are
skipped; a ``Sideboard`` / ``Maybeboard`` header ends the list (those
cards are not part of the library).

``resolve_names`` matches names against the card pool ignoring case and
accents (``Dandan`` finds ``Dandân``) and a double-faced card's front face.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Mapping

_COUNT_LINE = re.compile(r"^(\d+)\s*[xX]?\s+(.+)$")
# Arena / MTGO set + collector number suffix: "(M21) 263", "(DMU) 12a".
_SET_SUFFIX = re.compile(r"\s+\([A-Za-z0-9]{2,6}\)(?:\s+[A-Za-z0-9-]+)?$")
_SKIP_HEADERS = {"deck", "main", "maindeck", "main deck", "commander",
                 "companion", "library"}
_END_HEADERS = {"sideboard", "maybeboard", "considering"}


@dataclass(frozen=True)
class Decklist:
    """A parsed list: ``counts`` keeps the file's spelling and order;
    ``errors`` are lines that could not be read."""

    counts: dict[str, int]
    errors: tuple[str, ...] = ()

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def names(self) -> list[str]:
        """One entry per card."""
        return [n for n, k in self.counts.items() for _ in range(k)]


def parse_decklist(text: str) -> Decklist:
    counts: Counter[str] = Counter()
    errors: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "//")):
            continue
        header = line.rstrip(":").strip().lower()
        if header in _END_HEADERS:
            break
        if header in _SKIP_HEADERS:
            continue
        m = _COUNT_LINE.match(line)
        count, name = (int(m.group(1)), m.group(2)) if m else (1, line)
        name = _SET_SUFFIX.sub("", name).strip()
        if count < 1 or not name:
            errors.append(raw)
            continue
        counts[name] += count
    return Decklist(counts=dict(counts), errors=tuple(errors))


def _fold(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name)
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(plain.casefold().replace("’", "'").split())


def resolve_names(
    decklist: Decklist, known_names: Iterable[str],
) -> tuple[dict[str, int], list[str]]:
    """Map the list's names onto ``known_names`` (the card pool).

    Returns ``(counts by pool name, unknown names as written)``.
    """
    index: dict[str, str] = {}
    for known in known_names:
        index.setdefault(_fold(known), known)
        if " // " in known:
            index.setdefault(_fold(known.split(" // ")[0]), known)
    resolved: Counter[str] = Counter()
    unknown: list[str] = []
    for name, count in decklist.counts.items():
        match = index.get(_fold(name))
        if match is None:
            unknown.append(name)
        else:
            resolved[match] += count
    return dict(resolved), unknown


# "Tutors": any card that searches a library (Forgetful Fish lists are
# tutor-free by the user's rule; with one shared library a search would
# reach both players' cards).
_LIBRARY_SEARCH = re.compile(
    r"\bsearch(?:es)? (?:your|their|its owner's|its controller's|"
    r"that player's|target player's|target opponent's|each player's|"
    r"his or her) library",
    re.IGNORECASE,
)


def _oracle_texts(card: Mapping) -> list[str]:
    texts = [card.get("oracle_text", "")]
    texts += [face.get("oracle_text", "") for face in card.get("card_faces", ())]
    return [t for t in texts if t]


def tutor_names(
    names: Iterable[str], cards: Iterable[Mapping],
) -> list[str]:
    """The names (deduplicated, in list order) whose Scryfall record's
    rules text searches a library. ``cards`` are raw Scryfall records
    (``cards.pools.load_pool_cards``)."""
    searching = {
        c["name"] for c in cards
        if any(_LIBRARY_SEARCH.search(t) for t in _oracle_texts(c))
    }
    return [n for n in dict.fromkeys(names) if n in searching]


def decklist_names(
    text: str, printings: Mapping[str, object],
) -> tuple[list[str], list[str], tuple[str, ...]]:
    """Parse ``text`` against ``printings``: ``(one name per card,
    unknown names, unreadable lines)``."""
    parsed = parse_decklist(text)
    resolved, unknown = resolve_names(parsed, printings)
    names = [n for n, k in resolved.items() for _ in range(k)]
    return names, unknown, parsed.errors
