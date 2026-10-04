"""Local cache for Scryfall card images.

Scryfall JSON cards carry an ``image_uris`` map with CDN URLs at several sizes.
We resolve a card by name against the cached EoE data, then download the image
lazily into ``data/card_images/<size>/<scryfall_id>.jpg``. The Flask UI serves
from that directory.

Pure functions + an injectable ``fetcher`` so the test suite never hits the
network.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable


SIZES: tuple[str, ...] = ("small", "normal", "large", "art_crop", "border_crop")
DEFAULT_SIZES: tuple[str, ...] = ("small", "normal")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Kept for callers that want a single file; ``CardIndex.load()`` with no
# argument indexes every dump in the active card pool instead.
DEFAULT_CARD_DATA = _PROJECT_ROOT / "data" / "edge_of_eternities.json"
DEFAULT_CACHE_ROOT = _PROJECT_ROOT / "data" / "card_images"

_USER_AGENT = "mtg-bot/0.0.1 (+local dev)"

Fetcher = Callable[[str], bytes]


def http_fetcher(url: str) -> bytes:
    """Default fetcher: urllib GET with a User-Agent. Scryfall requires one."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": "image/jpeg, image/png"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


def _validate_size(size: str) -> None:
    if size not in SIZES:
        raise ValueError(f"unknown size {size!r}; expected one of {SIZES}")


@dataclass(frozen=True)
class CardIndex:
    """Lookup over one or more Scryfall dumps."""

    by_name: dict[str, dict[str, Any]]
    by_id: dict[str, dict[str, Any]]

    @classmethod
    def load(
        cls, path: Path | Iterable[Path] | None = None,
    ) -> "CardIndex":
        """Index ``path`` (one dump), each of an iterable of dumps, or,
        when ``None``, every dump in the active card pool (see
        ``mtg_bot.cards.pools``). First occurrence of a name wins."""
        if path is None:
            from mtg_bot.cards.pools import pool_data_paths
            paths: list[Path] = list(pool_data_paths())
        elif isinstance(path, (str, Path)):
            paths = [Path(path)]
        else:
            paths = [Path(p) for p in path]
        by_name: dict[str, dict[str, Any]] = {}
        by_id: dict[str, dict[str, Any]] = {}
        for p in paths:
            data = json.loads(p.read_text(encoding="utf-8"))
            for card in data:
                by_name.setdefault(card["name"], card)
                by_id.setdefault(card["id"], card)
        return cls(by_name=by_name, by_id=by_id)

    def resolve(self, name: str) -> dict[str, Any] | None:
        return self.by_name.get(name)


def image_url(card: dict[str, Any], size: str) -> str | None:
    """Scryfall CDN URL for this card at ``size``, or None if unavailable."""
    _validate_size(size)
    return (card.get("image_uris") or {}).get(size)


def cached_path(
    scryfall_id: str,
    size: str,
    root: Path = DEFAULT_CACHE_ROOT,
) -> Path:
    """Where an image would live on disk. Does not create the file."""
    _validate_size(size)
    return Path(root) / size / f"{scryfall_id}.jpg"


def fetch_image(
    card: dict[str, Any],
    size: str,
    *,
    root: Path = DEFAULT_CACHE_ROOT,
    fetcher: Fetcher = http_fetcher,
) -> Path:
    """Return the local path to the cached image, downloading if missing.

    Raises ``LookupError`` if the card has no image URI at this size.
    """
    path = cached_path(card["id"], size, root)
    if path.exists():
        return path
    url = image_url(card, size)
    if url is None:
        raise LookupError(f"card {card.get('name')!r} has no {size!r} image")
    payload = fetcher(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def prefetch_all(
    cards: Iterable[dict[str, Any]],
    sizes: Iterable[str] = DEFAULT_SIZES,
    *,
    root: Path = DEFAULT_CACHE_ROOT,
    fetcher: Fetcher = http_fetcher,
    on_progress: Callable[[str, str, bool], None] | None = None,
) -> int:
    """Warm the cache. Returns how many downloads actually happened. Cards that
    have no image at a given size are silently skipped. ``on_progress`` is
    called with ``(card_name, size, did_download)`` after each attempt."""
    sizes = tuple(sizes)
    for size in sizes:
        _validate_size(size)
    downloaded = 0
    for card in cards:
        for size in sizes:
            path = cached_path(card["id"], size, root)
            was_cached = path.exists()
            did_download = False
            if not was_cached:
                try:
                    fetch_image(card, size, root=root, fetcher=fetcher)
                    did_download = True
                    downloaded += 1
                except LookupError:
                    pass
            if on_progress is not None:
                on_progress(card["name"], size, did_download)
    return downloaded
