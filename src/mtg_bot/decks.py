"""17lands deck-list ingestion.

Parses 17lands "GameView" CSV exports into our engine's deck format
(a list of card names, one entry per copy). The point is to train
on real Limited matchups instead of synthetic mono-color decks —
real archetypes have removal, evasion, multi-color manabases, and
curve considerations that the engine should learn to play around.

17lands GameView format (one row per game):

    expansion,event_type,draft_id,build_index,match_number,
    game_number,...,won,deck_<CardName1>,deck_<CardName2>,...,
    sideboard_<CardName1>,...

Each ``deck_*`` column is an integer count (0 / 1 / 2 / 3 / 4) of
that card in the player's maindeck for that game. We extract the
maindeck counts and ignore sideboards.

A unique deck is identified by ``(draft_id, build_index)`` — the
same draft ID with different build_index values represents the
player rebuilding their deck mid-event. Different games with the
same (draft_id, build_index) all have identical deck columns; we
dedupe on first sight.

Public API:

- ``Deck`` dataclass: cards (list[str]) + metadata (draft_id, build_index,
  main_colors, won_in_first_seen_game, total_games, total_wins).
- ``parse_17lands_csv(path, ...)``: streaming generator over Decks.
- ``filter_decks(decks, exclude_cards=...)``: convenience filter
  for skipping decks containing unmodeled cards (Paradox Haze).
- ``decks_to_json`` / ``decks_from_json``: cache parsed decks to
  disk for fast reload.

Files are typically large (~100s of MB compressed). The streaming
parser yields decks incrementally and supports ``max_decks`` for
early exit; production use should always cap unless you actually
want every deck in the dataset.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import IO, Any, Callable, Iterable, Iterator, Optional


# Card name(s) we don't fully model and want to skip decks containing.
# Paradox Haze is documented in the EQ project memory as the only
# main-set EOE card that's a no-op in our engine (the extra-upkeep
# mechanic is out of scope, and aura_enchant_type="player" isn't
# modeled). Decks playing it would have its effect silently ignored,
# making them poor training data.
UNMODELED_CARDS: frozenset[str] = frozenset({"Paradox Haze"})


@dataclass
class Deck:
    """One 17lands maindeck.

    ``cards`` is the expanded list (one entry per copy), in card-name
    alphabetical order so ``Deck`` is hashable-friendly via tuple
    conversion. Use ``to_decklist()`` for the engine's setup_game
    decks= parameter.

    Metadata fields are best-effort from the 17lands columns;
    missing values default to None. ``win_rate`` summarizes across
    all games seen with this build (not just the first one).
    """

    draft_id: str
    build_index: int
    cards: list[str] = field(default_factory=list)
    main_colors: Optional[str] = None
    splash_colors: Optional[str] = None
    total_games: int = 0
    total_wins: int = 0

    @property
    def card_count(self) -> int:
        return len(self.cards)

    @property
    def win_rate(self) -> Optional[float]:
        if self.total_games == 0:
            return None
        return self.total_wins / self.total_games

    def to_decklist(self) -> list[str]:
        """The list passed to ``setup_game(decks=[...])``. Returns
        a fresh copy so caller mutations don't leak back."""
        return list(self.cards)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Deck":
        return cls(
            draft_id=d["draft_id"],
            build_index=int(d["build_index"]),
            cards=list(d.get("cards", [])),
            main_colors=d.get("main_colors"),
            splash_colors=d.get("splash_colors"),
            total_games=int(d.get("total_games", 0)),
            total_wins=int(d.get("total_wins", 0)),
        )


def _open_csv(path: Path) -> IO[str]:
    """Open .csv or .csv.gz transparently, returning a text stream."""
    path = Path(path)
    if path.suffix == ".gz":
        return io.TextIOWrapper(
            gzip.open(path, "rb"), encoding="utf-8", newline="",
        )
    return open(path, "r", encoding="utf-8", newline="")


def _deck_columns(fieldnames: list[str]) -> list[tuple[str, str]]:
    """Identify ``deck_<CardName>`` columns in the CSV header.

    Returns list of (column_name, card_name) tuples. The card name
    is the column suffix after ``deck_``. Sideboard columns are
    ignored — we only train on what was actually played."""
    out: list[tuple[str, str]] = []
    for col in fieldnames:
        if col.startswith("deck_"):
            out.append((col, col[len("deck_"):]))
    return out


def parse_17lands_csv(
    path: Path,
    *,
    max_decks: Optional[int] = None,
    exclude_cards: Iterable[str] = UNMODELED_CARDS,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Iterator[Deck]:
    """Stream Decks out of a 17lands GameView CSV.

    Dedupes on ``(draft_id, build_index)``: each unique build is
    yielded once, the first time it's seen. Subsequent rows for
    the same build update its ``total_games`` / ``total_wins``
    in-place, but the Deck itself is yielded only once — meaning
    win-rate stats on yielded decks are PARTIAL until you've drained
    the file. If win-rate accuracy matters for downstream filtering,
    consume the full iterator first and then filter.

    ``exclude_cards`` defaults to ``UNMODELED_CARDS`` (skips decks
    containing Paradox Haze). Pass an empty set to disable.

    ``max_decks`` caps the number of yielded decks for early exit;
    None reads the whole file (~100MB+ for a typical set).

    ``progress_callback(rows_seen, decks_yielded)`` fires every 10k
    rows for long-running parses.
    """
    exclude = frozenset(exclude_cards)
    seen_builds: dict[tuple[str, int], Deck] = {}
    yielded = 0
    rows_seen = 0
    with _open_csv(path) as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return
        deck_cols = _deck_columns(reader.fieldnames)

        for row in reader:
            rows_seen += 1
            if progress_callback is not None and rows_seen % 10_000 == 0:
                progress_callback(rows_seen, yielded)

            draft_id = row.get("draft_id", "")
            build_index = int(row.get("build_index", 0) or 0)
            key = (draft_id, build_index)
            if key in seen_builds:
                # Update aggregate stats only; deck already yielded.
                deck = seen_builds[key]
                deck.total_games += 1
                if _row_was_won(row):
                    deck.total_wins += 1
                continue

            cards = _expand_deck_columns(row, deck_cols)
            if not cards:
                # Empty deck row (unusual; skip)
                continue
            if any(c in exclude for c in cards):
                # Mark as seen so we don't re-evaluate the column-
                # parse cost on subsequent rows for this build.
                seen_builds[key] = Deck(
                    draft_id=draft_id, build_index=build_index,
                    cards=[],
                )
                continue

            deck = Deck(
                draft_id=draft_id,
                build_index=build_index,
                cards=cards,
                main_colors=row.get("main_colors") or None,
                splash_colors=row.get("splash_colors") or None,
                total_games=1,
                total_wins=1 if _row_was_won(row) else 0,
            )
            seen_builds[key] = deck
            yield deck
            yielded += 1
            if max_decks is not None and yielded >= max_decks:
                return


def _row_was_won(row: dict[str, str]) -> bool:
    """The ``won`` column is "True"/"False" as text in the CSV."""
    val = row.get("won", "")
    return val.lower() == "true"


def _expand_deck_columns(
    row: dict[str, str],
    deck_cols: list[tuple[str, str]],
) -> list[str]:
    """Expand the ``deck_<CardName>`` count columns into a flat
    list of card names (one entry per copy). Sorted alphabetically
    for deterministic output across rows."""
    cards: list[str] = []
    for col, name in deck_cols:
        raw = row.get(col, "0")
        try:
            n = int(raw or 0)
        except ValueError:
            n = 0
        for _ in range(n):
            cards.append(name)
    cards.sort()
    return cards


def filter_decks(
    decks: Iterable[Deck],
    *,
    exclude_cards: Iterable[str] = (),
    min_card_count: Optional[int] = None,
    max_card_count: Optional[int] = None,
    min_win_rate: Optional[float] = None,
    min_total_games: int = 0,
) -> list[Deck]:
    """Apply additional filtering to a list of already-parsed decks.

    Useful for refining a cached deck pool — e.g. "only keep decks
    with ≥3 games of data and a ≥55% win rate" to bias training
    toward competently-played builds.

    All filters are AND'd; pass-through defaults (None / 0) for
    filters you don't want to apply.
    """
    excl = frozenset(exclude_cards)
    out: list[Deck] = []
    for d in decks:
        if excl and any(c in excl for c in d.cards):
            continue
        if min_card_count is not None and d.card_count < min_card_count:
            continue
        if max_card_count is not None and d.card_count > max_card_count:
            continue
        if d.total_games < min_total_games:
            continue
        if min_win_rate is not None:
            wr = d.win_rate
            if wr is None or wr < min_win_rate:
                continue
        out.append(d)
    return out


def decks_to_json(decks: Iterable[Deck], path: Path) -> None:
    """Persist a list of Decks to ``.json`` or ``.json.gz``. Used
    by the fetch script to cache parsed decks for fast reload (the
    CSV parse itself is the slow part on a 100MB file)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps([d.to_dict() for d in decks]).encode("utf-8")
    if path.suffix == ".gz":
        with gzip.open(path, "wb") as f:
            f.write(payload)
    else:
        path.write_bytes(payload)


def decks_from_json(path: Path) -> list[Deck]:
    """Load Decks previously persisted via ``decks_to_json``."""
    path = Path(path)
    if path.suffix == ".gz":
        with gzip.open(path, "rb") as f:
            data = json.loads(f.read().decode("utf-8"))
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
    return [Deck.from_dict(d) for d in data]


def coverage_report(
    decks: Iterable[Deck], known_card_names: Iterable[str],
) -> dict[str, Any]:
    """Summarize how well a deck pool is covered by our card model.

    Returns:
        ``{"unique_cards": int, "modeled_cards": int,
           "unmodeled_cards": list[str],
           "decks_fully_modeled": int, "decks_with_gaps": int}``

    Useful for triaging engine-coverage gaps before pointing
    training at a fresh set of decks. Unmodeled cards are listed so
    you can decide whether to filter the affected decks or invest
    in modeling those cards next.
    """
    known = frozenset(known_card_names)
    decks_list = list(decks)
    unique_cards: set[str] = set()
    for d in decks_list:
        unique_cards.update(d.cards)
    unmodeled = sorted(unique_cards - known)
    modeled_count = len(unique_cards) - len(unmodeled)
    fully = sum(
        1 for d in decks_list if all(c in known for c in d.cards)
    )
    return {
        "unique_cards": len(unique_cards),
        "modeled_cards": modeled_count,
        "unmodeled_cards": unmodeled,
        "decks_fully_modeled": fully,
        "decks_with_gaps": len(decks_list) - fully,
    }
