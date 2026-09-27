"""``scripts/fetch_cube.py`` — CubeCobra → Scryfall pool fetch, offline."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "fetch_cube.py"


@pytest.fixture(scope="module")
def fc():
    spec = importlib.util.spec_from_file_location("_fetch_cube_under_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _cube_json(ids: list[str]) -> dict:
    return {
        "shortId": "TestCube", "name": "Test Cube", "cardCount": len(ids),
        "dateLastUpdated": 1_700_000_000_000,
        "cards": {"mainboard": [
            {"name": f"Card {i}", "cardID": sid, "details": {"scryfall_id": sid}}
            for i, sid in enumerate(ids)
        ], "maybeboard": []},
    }


def test_extract_scryfall_ids_in_order_deduped(fc):
    ids = fc.extract_scryfall_ids(_cube_json(["a", "b", "a", "c"]))
    assert ids == ["a", "b", "c"]


def test_extract_scryfall_ids_falls_back_to_cardID(fc):
    payload = {"cards": {"mainboard": [{"name": "X", "cardID": "zz", "details": {}}]}}
    assert fc.extract_scryfall_ids(payload) == ["zz"]


def test_extract_scryfall_ids_rejects_bad_payloads(fc):
    with pytest.raises(ValueError, match="no cards.mainboard"):
        fc.extract_scryfall_ids({"cards": []})
    with pytest.raises(ValueError, match="empty"):
        fc.extract_scryfall_ids({"cards": {"mainboard": []}})
    with pytest.raises(ValueError, match="no scryfall_id"):
        fc.extract_scryfall_ids({"cards": {"mainboard": [{"name": "X", "details": {}}]}})


def test_chunked(fc):
    assert list(fc.chunked(range(5), 2)) == [[0, 1], [2, 3], [4]]
    assert list(fc.chunked([], 3)) == []


def test_fetch_collection_batches_and_collects(fc):
    calls: list[dict] = []

    def post(url, payload):
        calls.append(payload)
        return {"data": [{"name": i["id"]} for i in payload["identifiers"]], "not_found": []}

    idents = [{"id": str(i)} for i in range(fc.SCRYFALL_COLLECTION_BATCH + 1)]
    cards = fc.fetch_collection(idents, post=post, delay_sec=0)
    assert len(cards) == len(idents)
    assert [len(c["identifiers"]) for c in calls] == [fc.SCRYFALL_COLLECTION_BATCH, 1]


def test_fetch_collection_not_found_is_loud(fc):
    def post(url, payload):
        return {"data": [], "not_found": [{"id": "missing"}]}

    with pytest.raises(ValueError, match="could not resolve 1"):
        fc.fetch_collection([{"id": "missing"}], post=post, delay_sec=0)


def test_dedupe_by_name(fc):
    out = fc.dedupe_by_name([{"name": "A", "v": 1}, {"name": "A", "v": 2}, {"name": "B"}])
    assert [(c["name"], c.get("v")) for c in out] == [("A", 1), ("B", None)]


def test_build_pool_appends_basics_and_dedupes(fc):
    def post(url, payload):
        data = []
        for ident in payload["identifiers"]:
            if "id" in ident:
                data.append({"name": f"Card {ident['id']}", "id": ident["id"]})
            else:
                data.append({"name": ident["name"], "id": f"basic-{ident['name']}"})
        return {"data": data, "not_found": []}

    pool = fc.build_pool(_cube_json(["a", "b"]), post=post, delay_sec=0)
    names = [c["name"] for c in pool]
    assert names == ["Card a", "Card b", *fc.BASIC_LAND_NAMES]


def test_cube_metadata(fc):
    meta = fc.cube_metadata(_cube_json(["a"]), n_cards=6)
    assert meta["cube_id"] == "TestCube"
    assert meta["cube_card_count"] == 1
    assert meta["pool_card_count"] == 6
    assert meta["cube_last_updated"].startswith("2023-11-14")
    assert meta["includes_basic_lands"] == list(fc.BASIC_LAND_NAMES)
    assert fc.cube_metadata({}, n_cards=0)["cube_last_updated"] is None


def test_main_writes_pool_and_meta(fc, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fc, "get_json", lambda url: _cube_json(["a"]))
    monkeypatch.setattr(fc, "post_json", lambda url, payload: {
        "data": [{"name": i.get("name") or f"Card {i['id']}", "id": "x"} for i in payload["identifiers"]],
        "not_found": [],
    })
    monkeypatch.setattr(fc, "REQUEST_DELAY_SEC", 0)
    out = tmp_path / "pool.json"
    assert fc.main(["--cube", "TestCube", "--out", str(out)]) == 0
    cards = json.loads(out.read_text(encoding="utf-8"))
    assert len(cards) == 1 + len(fc.BASIC_LAND_NAMES)
    meta = json.loads((tmp_path / "pool.meta.json").read_text(encoding="utf-8"))
    assert meta["cube_id"] == "TestCube"
    assert "Wrote" in capsys.readouterr().out


def test_main_empty_pool_fails(fc, tmp_path, monkeypatch):
    monkeypatch.setattr(fc, "get_json", lambda url: _cube_json(["a"]))
    monkeypatch.setattr(fc, "build_pool", lambda cube_json: [])
    assert fc.main(["--out", str(tmp_path / "pool.json")]) == 1


def test_committed_pool_matches_meta(fc):
    """The committed dump is what the script would write: 541 cube cards
    + 5 basics, and the sidecar agrees."""
    pool_path = fc.DEFAULT_OUT_PATH
    meta = json.loads(pool_path.with_suffix(".meta.json").read_text(encoding="utf-8"))
    cards = json.loads(pool_path.read_text(encoding="utf-8"))
    assert meta["pool_card_count"] == len(cards)
    assert meta["cube_id"] == fc.DEFAULT_CUBE_ID
    names = {c["name"] for c in cards}
    assert set(fc.BASIC_LAND_NAMES) <= names
    assert len(names) == len(cards)
