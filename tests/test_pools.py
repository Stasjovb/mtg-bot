"""``mtg_bot.cards.pools`` — pool registry + env selection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mtg_bot.cards import pools
from mtg_bot.cards.parser_source import OracleParserCardSource


def _write(path: Path, cards: list[dict]) -> None:
    path.write_text(json.dumps(cards), encoding="utf-8")


@pytest.fixture
def fake_data_dir(tmp_path: Path) -> Path:
    for fname in pools.EOE_POOL_FILES:
        _write(tmp_path / fname, [{"name": f"EoE {fname}"}])
    _write(tmp_path / pools.EOE_POOL_FILES[0], [
        {"name": "Shared"}, {"name": "Only EoE"},
    ])
    _write(tmp_path / pools.CUBE_POOL_FILES[0], [
        {"name": "Shared", "set": "cube"}, {"name": "Only Cube"},
    ])
    return tmp_path


# ------------------------------------------------------------------ names


def test_resolve_pool_name_defaults_and_normalizes():
    assert pools.resolve_pool_name(None) == pools.DEFAULT_POOL
    assert pools.resolve_pool_name("") == pools.DEFAULT_POOL
    assert pools.resolve_pool_name(" CUBE ") == "cube"
    assert pools.resolve_pool_name("eoe") == "eoe"


def test_resolve_pool_name_rejects_unknown():
    with pytest.raises(ValueError, match="unknown MTG_BOT_CARD_POOL"):
        pools.resolve_pool_name("vintage")


def test_active_pool_name_reads_env(monkeypatch):
    monkeypatch.delenv(pools.POOL_ENV_VAR, raising=False)
    assert pools.active_pool_name() == pools.DEFAULT_POOL
    monkeypatch.setenv(pools.POOL_ENV_VAR, "cube")
    assert pools.active_pool_name() == "cube"


def test_registry_shape():
    assert pools.TARGET_POOL == "cube"
    assert set(pools.POOLS) == {"all", "cube", "eoe"}
    assert pools.POOLS["all"] == pools.EOE_POOL_FILES + pools.CUBE_POOL_FILES
    assert pools.POOLS["cube"] == pools.CUBE_POOL_FILES


# ------------------------------------------------------------------ paths


def test_pool_data_paths_explicit_and_env(monkeypatch, tmp_path):
    paths = pools.pool_data_paths("cube", data_dir=tmp_path)
    assert paths == (tmp_path / "cube_power_lsv.json",)
    monkeypatch.setenv(pools.POOL_ENV_VAR, "eoe")
    env_paths = pools.pool_data_paths(data_dir=tmp_path)
    assert [p.name for p in env_paths] == list(pools.EOE_POOL_FILES)


def test_real_pool_files_exist():
    """Every registered dump is committed — a fresh checkout must be
    able to build the default source without a fetch step."""
    for path in pools.pool_data_paths("all"):
        assert path.exists(), path


# ------------------------------------------------------------------ load


def test_load_pool_cards_dedupes_first_file_wins(fake_data_dir):
    cards = pools.load_pool_cards("all", data_dir=fake_data_dir)
    names = [c["name"] for c in cards]
    assert names.count("Shared") == 1
    shared = next(c for c in cards if c["name"] == "Shared")
    assert "set" not in shared  # the EoE-file record came first
    assert "Only Cube" in names and "Only EoE" in names


def test_load_pool_cards_cube_only(fake_data_dir):
    names = pools.pool_card_names("cube", data_dir=fake_data_dir)
    assert names == frozenset({"Shared", "Only Cube"})


def test_load_pool_cards_missing_file_is_loud(tmp_path):
    with pytest.raises(FileNotFoundError, match="fetch_cube.py"):
        pools.load_pool_cards("cube", data_dir=tmp_path)
    (tmp_path / pools.CUBE_POOL_FILES[0]).write_text("[]", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match=r"fetch_\*\.py"):
        pools.load_pool_cards("all", data_dir=tmp_path)


# ------------------------------------------------------------------ source


def test_parser_source_honors_explicit_pool():
    cube = OracleParserCardSource(pool="cube")
    assert cube.pool_name == "cube"
    claimed = set(cube.claimed_names)
    # Basics ride along with the cube list; power is claimed.
    assert {"Plains", "Island", "Swamp", "Mountain", "Forest"} <= claimed
    assert "Mox Sapphire" in claimed
    # An EoE-only card is not in a cube-only source.
    assert "Anticausal Vestige" not in claimed


def test_parser_source_default_pool_is_union(monkeypatch):
    monkeypatch.delenv(pools.POOL_ENV_VAR, raising=False)
    union = OracleParserCardSource()
    assert union.pool_name == "all"
    claimed = set(union.claimed_names)
    assert "Mox Sapphire" in claimed
    assert "Lightning Bolt" in claimed


def test_parser_source_rejects_unknown_pool():
    with pytest.raises(ValueError):
        OracleParserCardSource(pool="nope")
