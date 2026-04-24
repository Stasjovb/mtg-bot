import json
import urllib.request
from pathlib import Path

import pytest

from mtg_bot import art


# ------------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------------


def _make_card(
    scryfall_id: str = "abc-123",
    name: str = "Sample Card",
    with_images: bool = True,
    sizes: tuple[str, ...] = ("small", "normal"),
) -> dict:
    card: dict = {"id": scryfall_id, "name": name}
    if with_images:
        card["image_uris"] = {
            size: f"https://cards.example/{size}/{scryfall_id}.jpg"
            for size in sizes
        }
    return card


# ------------------------------------------------------------------------
# cached_path
# ------------------------------------------------------------------------


def test_cached_path_layout(tmp_path):
    p = art.cached_path("abc-123", "small", tmp_path)
    assert p == tmp_path / "small" / "abc-123.jpg"


def test_cached_path_rejects_bad_size(tmp_path):
    with pytest.raises(ValueError, match="unknown size"):
        art.cached_path("abc-123", "jumbo", tmp_path)


# ------------------------------------------------------------------------
# image_url
# ------------------------------------------------------------------------


def test_image_url_returns_uri_for_size():
    card = _make_card()
    assert art.image_url(card, "small") == "https://cards.example/small/abc-123.jpg"


def test_image_url_missing_image_returns_none():
    card = _make_card(with_images=False)
    assert art.image_url(card, "small") is None


def test_image_url_unknown_size_in_uris_returns_none():
    card = _make_card(sizes=("small",))
    assert art.image_url(card, "normal") is None


def test_image_url_rejects_bad_size():
    with pytest.raises(ValueError):
        art.image_url(_make_card(), "jumbo")


# ------------------------------------------------------------------------
# fetch_image
# ------------------------------------------------------------------------


def test_fetch_image_downloads_when_missing(tmp_path):
    card = _make_card()
    calls: list[str] = []

    def fake_fetcher(url: str) -> bytes:
        calls.append(url)
        return b"IMGBYTES"

    path = art.fetch_image(card, "small", root=tmp_path, fetcher=fake_fetcher)

    assert path == tmp_path / "small" / "abc-123.jpg"
    assert path.read_bytes() == b"IMGBYTES"
    assert calls == ["https://cards.example/small/abc-123.jpg"]


def test_fetch_image_uses_cache_hit(tmp_path):
    card = _make_card()
    path = tmp_path / "small" / "abc-123.jpg"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"already-here")

    def boom(_url: str) -> bytes:
        raise AssertionError("fetcher must not be called on cache hit")

    returned = art.fetch_image(card, "small", root=tmp_path, fetcher=boom)
    assert returned == path
    assert path.read_bytes() == b"already-here"


def test_fetch_image_raises_when_card_has_no_image(tmp_path):
    card = _make_card(with_images=False)
    with pytest.raises(LookupError, match="no 'small' image"):
        art.fetch_image(card, "small", root=tmp_path, fetcher=lambda _u: b"x")


def test_fetch_image_creates_parent_dir(tmp_path):
    card = _make_card()
    assert not (tmp_path / "small").exists()
    art.fetch_image(card, "small", root=tmp_path, fetcher=lambda _u: b"IMG")
    assert (tmp_path / "small").is_dir()


def test_fetch_image_rejects_bad_size(tmp_path):
    card = _make_card()
    with pytest.raises(ValueError):
        art.fetch_image(card, "jumbo", root=tmp_path, fetcher=lambda _u: b"x")


# ------------------------------------------------------------------------
# prefetch_all
# ------------------------------------------------------------------------


def test_prefetch_all_downloads_every_combo(tmp_path):
    cards = [_make_card("id-1", "One"), _make_card("id-2", "Two")]
    fetched: list[str] = []
    count = art.prefetch_all(
        cards, ["small", "normal"],
        root=tmp_path,
        fetcher=lambda u: (fetched.append(u), b"DATA")[1],
    )
    assert count == 4
    assert len(fetched) == 4
    assert (tmp_path / "small" / "id-1.jpg").exists()
    assert (tmp_path / "normal" / "id-2.jpg").exists()


def test_prefetch_all_skips_cached(tmp_path):
    cards = [_make_card("id-1", "One")]
    existing = tmp_path / "small" / "id-1.jpg"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"cached")

    fetched: list[str] = []
    count = art.prefetch_all(
        cards, ["small"],
        root=tmp_path,
        fetcher=lambda u: (fetched.append(u), b"NEW")[1],
    )
    assert count == 0
    assert fetched == []
    assert existing.read_bytes() == b"cached"


def test_prefetch_all_progress_callback(tmp_path):
    cards = [_make_card("id-1", "One"), _make_card("id-2", "Two")]
    events: list[tuple[str, str, bool]] = []
    art.prefetch_all(
        cards, ["small"],
        root=tmp_path,
        fetcher=lambda _u: b"X",
        on_progress=lambda name, size, did: events.append((name, size, did)),
    )
    assert events == [("One", "small", True), ("Two", "small", True)]


def test_prefetch_all_tolerates_missing_images(tmp_path):
    cards = [_make_card("id-1", "One", with_images=False)]
    events: list[tuple[str, str, bool]] = []
    count = art.prefetch_all(
        cards, ["small"],
        root=tmp_path,
        fetcher=lambda _u: b"X",
        on_progress=lambda n, s, d: events.append((n, s, d)),
    )
    assert count == 0
    assert events == [("One", "small", False)]


def test_prefetch_all_rejects_bad_size(tmp_path):
    with pytest.raises(ValueError):
        art.prefetch_all([_make_card()], ["jumbo"], root=tmp_path,
                         fetcher=lambda _u: b"X")


# ------------------------------------------------------------------------
# CardIndex
# ------------------------------------------------------------------------


def test_card_index_load_builds_both_maps(tmp_path):
    data = [
        {"id": "id-1", "name": "Alpha", "image_uris": {"small": "u1"}},
        {"id": "id-2", "name": "Beta", "image_uris": {"small": "u2"}},
    ]
    path = tmp_path / "cards.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    idx = art.CardIndex.load(path)
    assert set(idx.by_name.keys()) == {"Alpha", "Beta"}
    assert idx.by_id["id-1"]["name"] == "Alpha"


def test_card_index_resolve_hit_and_miss(tmp_path):
    data = [{"id": "id-1", "name": "Alpha"}]
    path = tmp_path / "cards.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    idx = art.CardIndex.load(path)
    assert idx.resolve("Alpha")["id"] == "id-1"
    assert idx.resolve("Nonexistent") is None


# ------------------------------------------------------------------------
# http_fetcher
# ------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_http_fetcher_sets_user_agent(monkeypatch):
    seen: dict = {}

    def fake_urlopen(req, timeout):  # noqa: ARG001 — signature must match urlopen
        seen["url"] = req.full_url
        seen["headers"] = dict(req.header_items())
        return _FakeResponse(b"PAYLOAD")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    payload = art.http_fetcher("https://cards.example/small/id-1.jpg")
    assert payload == b"PAYLOAD"
    assert seen["url"] == "https://cards.example/small/id-1.jpg"
    assert any(k.lower() == "user-agent" for k in seen["headers"])
    ua = next(v for k, v in seen["headers"].items() if k.lower() == "user-agent")
    assert "mtg-bot" in ua
