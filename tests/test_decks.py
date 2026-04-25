"""Tests for ``mtg_bot.decks`` (17lands CSV ingestion).

Synthetic CSV fixtures only — no network, no real 17lands data
required. Validates the parser shape (deduplication on
draft_id+build_index, expansion of card-count columns to a flat
list, win-rate aggregation across multiple game rows for the same
build, exclude-cards filter, max-decks early exit) and the
JSON round-trip.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from mtg_bot.decks import (
    UNMODELED_CARDS,
    Deck,
    coverage_report,
    decks_from_json,
    decks_to_json,
    filter_decks,
    parse_17lands_csv,
)


# ---------- CSV fixtures ----------------------------------------------------


def _write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    """Write a synthetic CSV. headers and each row are aligned."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [",".join(headers)]
    for row in rows:
        lines.append(",".join(row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_gzip_csv(
    path: Path, headers: list[str], rows: list[list[str]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(
        [",".join(headers)] + [",".join(r) for r in rows]
    ) + "\n"
    with gzip.open(path, "wb") as f:
        f.write(payload.encode("utf-8"))


# ---------- parse_17lands_csv ----------------------------------------------


def test_parse_basic_deck(tmp_path: Path):
    csv_path = tmp_path / "g.csv"
    _write_csv(
        csv_path,
        headers=[
            "draft_id", "build_index", "won", "main_colors",
            "deck_Plains", "deck_Forest", "deck_Llanowar Elves",
        ],
        rows=[
            ["d1", "0", "True", "GW", "8", "8", "2"],
        ],
    )
    decks = list(parse_17lands_csv(csv_path))
    assert len(decks) == 1
    deck = decks[0]
    assert deck.draft_id == "d1"
    assert deck.build_index == 0
    assert deck.cards.count("Plains") == 8
    assert deck.cards.count("Forest") == 8
    assert deck.cards.count("Llanowar Elves") == 2
    assert deck.card_count == 18
    assert deck.main_colors == "GW"
    assert deck.total_games == 1
    assert deck.total_wins == 1
    assert deck.win_rate == 1.0


def test_parse_dedupes_on_draft_and_build_index(tmp_path: Path):
    """Three game rows for the same (draft_id, build_index) yield
    exactly one Deck; the win_rate aggregates over all rows."""
    csv_path = tmp_path / "g.csv"
    _write_csv(
        csv_path,
        headers=[
            "draft_id", "build_index", "won", "deck_Forest",
        ],
        rows=[
            ["d1", "0", "True", "17"],
            ["d1", "0", "False", "17"],
            ["d1", "0", "True", "17"],
        ],
    )
    decks = list(parse_17lands_csv(csv_path))
    assert len(decks) == 1
    assert decks[0].total_games == 3
    assert decks[0].total_wins == 2
    assert decks[0].win_rate == pytest.approx(2 / 3)


def test_parse_distinguishes_different_builds(tmp_path: Path):
    """Different build_index for the same draft_id → separate Decks."""
    csv_path = tmp_path / "g.csv"
    _write_csv(
        csv_path,
        headers=["draft_id", "build_index", "won", "deck_Forest"],
        rows=[
            ["d1", "0", "True", "10"],
            ["d1", "1", "False", "12"],
        ],
    )
    decks = list(parse_17lands_csv(csv_path))
    assert len(decks) == 2
    assert {d.build_index for d in decks} == {0, 1}


def test_parse_skips_decks_with_excluded_cards(tmp_path: Path):
    csv_path = tmp_path / "g.csv"
    _write_csv(
        csv_path,
        headers=[
            "draft_id", "build_index", "won",
            "deck_Forest", "deck_Paradox Haze",
        ],
        rows=[
            ["d1", "0", "True", "17", "1"],   # has Paradox Haze → skip
            ["d2", "0", "True", "17", "0"],   # clean → keep
        ],
    )
    decks = list(parse_17lands_csv(csv_path))
    assert len(decks) == 1
    assert decks[0].draft_id == "d2"


def test_parse_excludes_uses_default_unmodeled_set(tmp_path: Path):
    """Sanity that the default exclude_cards covers Paradox Haze."""
    assert "Paradox Haze" in UNMODELED_CARDS


def test_parse_can_disable_exclusion(tmp_path: Path):
    """Pass exclude_cards=() to keep everything."""
    csv_path = tmp_path / "g.csv"
    _write_csv(
        csv_path,
        headers=["draft_id", "build_index", "won",
                 "deck_Forest", "deck_Paradox Haze"],
        rows=[["d1", "0", "True", "17", "1"]],
    )
    decks = list(parse_17lands_csv(csv_path, exclude_cards=()))
    assert len(decks) == 1
    assert "Paradox Haze" in decks[0].cards


def test_parse_ignores_sideboard_columns(tmp_path: Path):
    csv_path = tmp_path / "g.csv"
    _write_csv(
        csv_path,
        headers=[
            "draft_id", "build_index", "won",
            "deck_Forest", "sideboard_Forest", "sideboard_Naturalize",
        ],
        rows=[["d1", "0", "True", "17", "5", "2"]],
    )
    decks = list(parse_17lands_csv(csv_path))
    deck = decks[0]
    # Only deck_Forest counted; sideboard columns ignored.
    assert deck.cards.count("Forest") == 17
    assert "Naturalize" not in deck.cards


def test_parse_max_decks_caps_iteration(tmp_path: Path):
    csv_path = tmp_path / "g.csv"
    _write_csv(
        csv_path,
        headers=["draft_id", "build_index", "won", "deck_Forest"],
        rows=[
            ["d1", "0", "True", "17"],
            ["d2", "0", "True", "17"],
            ["d3", "0", "True", "17"],
            ["d4", "0", "True", "17"],
        ],
    )
    decks = list(parse_17lands_csv(csv_path, max_decks=2))
    assert len(decks) == 2


def test_parse_handles_gzipped_csv(tmp_path: Path):
    csv_path = tmp_path / "g.csv.gz"
    _write_gzip_csv(
        csv_path,
        headers=["draft_id", "build_index", "won", "deck_Forest"],
        rows=[["d1", "0", "True", "17"]],
    )
    decks = list(parse_17lands_csv(csv_path))
    assert len(decks) == 1
    assert decks[0].cards == ["Forest"] * 17


def test_parse_progress_callback_fires(tmp_path: Path):
    """Progress callback fires every 10k rows. With <10k rows it
    should NOT fire (no false-positive log spam)."""
    csv_path = tmp_path / "g.csv"
    _write_csv(
        csv_path,
        headers=["draft_id", "build_index", "won", "deck_Forest"],
        rows=[["d1", "0", "True", "17"]],
    )
    calls: list[tuple] = []
    list(parse_17lands_csv(
        csv_path, progress_callback=lambda r, y: calls.append((r, y)),
    ))
    assert calls == []  # only 1 row, well under 10k


def test_parse_handles_invalid_count_as_zero(tmp_path: Path):
    """Non-integer card-count cells default to 0 rather than crashing."""
    csv_path = tmp_path / "g.csv"
    _write_csv(
        csv_path,
        headers=["draft_id", "build_index", "won",
                 "deck_Forest", "deck_Plains"],
        rows=[["d1", "0", "True", "17", "garbage"]],
    )
    decks = list(parse_17lands_csv(csv_path))
    assert len(decks) == 1
    assert decks[0].cards.count("Plains") == 0
    assert decks[0].cards.count("Forest") == 17


def test_parse_skips_empty_decks(tmp_path: Path):
    """A row with all deck columns at 0 produces no Deck."""
    csv_path = tmp_path / "g.csv"
    _write_csv(
        csv_path,
        headers=["draft_id", "build_index", "won", "deck_Forest"],
        rows=[["d1", "0", "True", "0"]],
    )
    decks = list(parse_17lands_csv(csv_path))
    assert decks == []


# ---------- filter_decks ----------------------------------------------------


def test_filter_decks_min_total_games():
    decks = [
        Deck(draft_id="a", build_index=0, cards=["X"], total_games=1),
        Deck(draft_id="b", build_index=0, cards=["X"], total_games=5),
        Deck(draft_id="c", build_index=0, cards=["X"], total_games=10),
    ]
    out = filter_decks(decks, min_total_games=5)
    assert {d.draft_id for d in out} == {"b", "c"}


def test_filter_decks_min_win_rate():
    decks = [
        Deck(draft_id="a", build_index=0, cards=["X"],
             total_games=10, total_wins=3),  # 30%
        Deck(draft_id="b", build_index=0, cards=["X"],
             total_games=10, total_wins=7),  # 70%
        Deck(draft_id="c", build_index=0, cards=["X"],
             total_games=0, total_wins=0),   # win_rate=None → excluded
    ]
    out = filter_decks(decks, min_win_rate=0.5)
    assert {d.draft_id for d in out} == {"b"}


def test_filter_decks_card_count_bounds():
    decks = [
        Deck(draft_id="a", build_index=0, cards=["X"] * 30),
        Deck(draft_id="b", build_index=0, cards=["X"] * 40),
        Deck(draft_id="c", build_index=0, cards=["X"] * 60),
    ]
    out = filter_decks(decks, min_card_count=35, max_card_count=50)
    assert {d.draft_id for d in out} == {"b"}


def test_filter_decks_exclude_cards():
    decks = [
        Deck(draft_id="a", build_index=0,
             cards=["Plains", "Plains", "Forest"]),
        Deck(draft_id="b", build_index=0,
             cards=["Plains", "Paradox Haze"]),
    ]
    out = filter_decks(decks, exclude_cards={"Paradox Haze"})
    assert {d.draft_id for d in out} == {"a"}


# ---------- JSON round-trip -------------------------------------------------


def test_json_round_trip_plain(tmp_path: Path):
    decks = [
        Deck(draft_id="d1", build_index=0,
             cards=["Plains", "Forest"], main_colors="GW",
             total_games=3, total_wins=2),
        Deck(draft_id="d2", build_index=1,
             cards=["Mountain"], total_games=1, total_wins=0),
    ]
    path = tmp_path / "decks.json"
    decks_to_json(decks, path)
    restored = decks_from_json(path)
    assert restored == decks


def test_json_round_trip_gzipped(tmp_path: Path):
    decks = [Deck(draft_id="d1", build_index=0, cards=["Forest"])]
    path = tmp_path / "decks.json.gz"
    decks_to_json(decks, path)
    # Verify it's actually gzip-compressed (first two bytes = 1f 8b).
    with open(path, "rb") as f:
        assert f.read(2) == b"\x1f\x8b"
    restored = decks_from_json(path)
    assert restored == decks


# ---------- coverage_report -------------------------------------------------


def test_coverage_report_full_match():
    decks = [
        Deck(draft_id="a", build_index=0,
             cards=["Plains", "Plains", "Forest"]),
        Deck(draft_id="b", build_index=0,
             cards=["Plains", "Mountain"]),
    ]
    report = coverage_report(decks, ["Plains", "Forest", "Mountain"])
    assert report["unique_cards"] == 3
    assert report["modeled_cards"] == 3
    assert report["unmodeled_cards"] == []
    assert report["decks_fully_modeled"] == 2
    assert report["decks_with_gaps"] == 0


def test_coverage_report_missing_card_listed_and_decks_flagged():
    decks = [
        Deck(draft_id="a", build_index=0,
             cards=["Plains", "Forest"]),
        Deck(draft_id="b", build_index=0,
             cards=["Plains", "MysteryCard"]),
    ]
    report = coverage_report(decks, ["Plains", "Forest"])
    assert report["unique_cards"] == 3
    assert report["modeled_cards"] == 2
    assert report["unmodeled_cards"] == ["MysteryCard"]
    assert report["decks_fully_modeled"] == 1  # deck a only
    assert report["decks_with_gaps"] == 1
