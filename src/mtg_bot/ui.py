"""Flask web UI for viewing simulated games.

Run locally on this machine only:
    python -m mtg_bot.ui
Expose on Tailscale / LAN (see scripts/serve.ps1 for the Windows helper):
    python -m mtg_bot.ui --host 0.0.0.0 --port 5002
Then visit http://<tailscale-hostname-or-ip>:5002/ from any tailnet peer.
"""

from __future__ import annotations

import argparse
import subprocess
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from flask import Flask, abort, jsonify, render_template, request, send_file

from mtg_bot.art import (
    DEFAULT_CACHE_ROOT,
    DEFAULT_CARD_DATA,
    SIZES,
    CardIndex,
    Fetcher,
    fetch_image,
    http_fetcher,
)
from mtg_bot.cards import COLORS
from mtg_bot.recommend import recommend_from_snapshot
from mtg_bot.serialize import serialize_state
from mtg_bot.simulate import simulate_game


_GAME_CACHE_MAX = 20


class GameCache:
    """In-memory LRU cache of snapshot streams produced by /api/play.

    Keys are opaque game ids (hex UUIDs); values are the list of serialized
    snapshot dicts captured during simulation. Oldest entries are evicted when
    the cache exceeds ``max_entries``. Not threadsafe — Flask dev server is
    single-request, and prod can add a lock if this ever matters.
    """

    def __init__(self, max_entries: int = _GAME_CACHE_MAX) -> None:
        self._games: "OrderedDict[str, list[dict[str, Any]]]" = OrderedDict()
        self._max = max_entries

    def store(self, game_id: str, snapshots: list[dict[str, Any]]) -> None:
        self._games[game_id] = snapshots
        self._games.move_to_end(game_id)
        while len(self._games) > self._max:
            self._games.popitem(last=False)

    def get(self, game_id: str) -> Optional[list[dict[str, Any]]]:
        snapshots = self._games.get(game_id)
        if snapshots is not None:
            self._games.move_to_end(game_id)
        return snapshots

    def __len__(self) -> int:
        return len(self._games)


def _parse_int_arg(name: str, default: int) -> int:
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        abort(400, description=f"{name} must be an integer")


def _validate_play_args() -> tuple[int, int, str, str]:
    seed = _parse_int_arg("seed", 0)
    max_turns = _parse_int_arg("max_turns", 300)
    c1 = request.args.get("c1", "G")
    c2 = request.args.get("c2", "R")
    if c1 not in COLORS:
        abort(400, description=f"c1 must be one of {list(COLORS)}")
    if c2 not in COLORS:
        abort(400, description=f"c2 must be one of {list(COLORS)}")
    if max_turns < 1:
        abort(400, description="max_turns must be >= 1")
    return seed, max_turns, c1, c2


def _enrich_snapshot(snap: dict[str, Any], name_to_id: dict[str, str]) -> dict[str, Any]:
    """Annotate every card dict in the snapshot with its Scryfall id so the
    client can build /card_image URLs without an extra round-trip. Unknown
    names (tokens not in the EoE dump, synthetic test cards) map to None."""

    def tag(card: dict[str, Any]) -> None:
        card["scryfall_id"] = name_to_id.get(card["name"])

    for p in snap["players"]:
        for c in p["hand"]:
            tag(c)
        for c in p["graveyard"]:
            tag(c)
        for c in p["exile"]:
            tag(c)
        for o in p["battlefield"]:
            tag(o)
    for item in snap["stack"]:
        tag(item)
    return snap


def create_app(
    *,
    card_index: Optional[CardIndex] = None,
    image_root: Path = DEFAULT_CACHE_ROOT,
    image_fetcher: Optional[Fetcher] = None,
    game_cache: Optional[GameCache] = None,
) -> Flask:
    """Build the Flask app.

    All injectables default to production wiring (real Scryfall data, real
    network fetcher, fresh cache). Tests pass fakes.
    """
    app = Flask(__name__)
    index = card_index if card_index is not None else CardIndex.load(DEFAULT_CARD_DATA)
    fetcher = image_fetcher if image_fetcher is not None else http_fetcher
    cache = game_cache if game_cache is not None else GameCache()
    name_to_id = {name: card["id"] for name, card in index.by_name.items()}

    @app.route("/")
    def home():
        return render_template("index.html")

    # ------------------------------------------------------------------
    # JSON API. Consumed by static/app.js.
    # ------------------------------------------------------------------

    @app.route("/api/play")
    def api_play():
        seed, max_turns, c1, c2 = _validate_play_args()
        granularity = request.args.get("granularity", "step")
        if granularity not in ("step", "priority"):
            abort(400, description="granularity must be 'step' or 'priority'")
        reveal = request.args.get("reveal", "all")
        if reveal not in ("all", "p0", "p1", "none"):
            abort(400, description="reveal must be 'all', 'p0', 'p1', or 'none'")
        snapshots: list[dict[str, Any]] = []
        # Track log length across snapshots so each one can carry the entries
        # that appeared since the previous snapshot — useful for highlighting
        # "events this step" in the UI's log panel.
        log_offset = [0]

        def _redact_hands(snap: dict[str, Any]) -> None:
            """Strip hand contents per the ``reveal`` mode. hand_size stays so
            the UI can render face-down placeholders for the hidden cards."""
            if reveal == "all":
                return
            for p in snap["players"]:
                hide = (
                    reveal == "none"
                    or (reveal == "p0" and p["id"] != 0)
                    or (reveal == "p1" and p["id"] != 1)
                )
                if hide:
                    p["hand"] = []

        def capture(state):
            snap = _enrich_snapshot(serialize_state(state), name_to_id)
            _redact_hands(snap)
            snap["log_since_last"] = list(snap["log"][log_offset[0]:])
            log_offset[0] = len(snap["log"])
            snapshots.append(snap)

        state = simulate_game(
            colors=[c1, c2], seed=seed, max_turns=max_turns,
            on_snapshot=capture,
            snapshot_granularity=granularity,
        )
        game_id = uuid4().hex
        cache.store(game_id, snapshots)
        return jsonify({
            "game_id": game_id,
            "snapshot_count": len(snapshots),
            "turn_number": state.turn_number,
            "winner_id": state.winner_id,
            "is_draw": state.is_draw,
            "seed": seed,
            "colors": [c1, c2],
            "granularity": granularity,
            "reveal": reveal,
        })

    @app.route("/api/snapshot/<game_id>/<int:idx>")
    def api_snapshot(game_id: str, idx: int):
        snapshots = cache.get(game_id)
        if snapshots is None:
            abort(404, description="unknown game_id")
        if idx < 0 or idx >= len(snapshots):
            abort(404, description=f"snapshot idx out of range (0..{len(snapshots) - 1})")
        return jsonify(snapshots[idx])

    @app.route("/api/recommend/<game_id>/<int:idx>")
    def api_recommend(game_id: str, idx: int):
        """Return the top-N engine recommendations for a specific snapshot.

        Contract: see ``recommend_from_snapshot`` in mtg_bot/recommend.py.
        Stubbed until the real evaluator ships; the UI can be built against
        this endpoint's stable response shape.
        """
        snapshots = cache.get(game_id)
        if snapshots is None:
            abort(404, description="unknown game_id")
        if idx < 0 or idx >= len(snapshots):
            abort(404, description=f"snapshot idx out of range (0..{len(snapshots) - 1})")
        n_raw = request.args.get("n", "3")
        try:
            n = int(n_raw)
        except ValueError:
            abort(400, description="n must be an integer")
        if n < 1 or n > 50:
            abort(400, description="n must be between 1 and 50")
        result = recommend_from_snapshot(snapshots[idx], n=n)
        result["snapshot_idx"] = idx
        return jsonify(result)

    @app.route("/api/snapshots_index/<game_id>")
    def api_snapshots_index(game_id: str):
        """Compact index of every snapshot's turn + step, for fast step/turn
        navigation in the scrubber without fetching each snapshot's full
        payload. Returned as a parallel array so the client can index by
        snapshot idx directly."""
        snapshots = cache.get(game_id)
        if snapshots is None:
            abort(404, description="unknown game_id")
        return jsonify([
            {"turn_number": s["turn_number"], "step": s["step"]}
            for s in snapshots
        ])

    @app.route("/api/card/<scryfall_id>")
    def api_card(scryfall_id: str):
        card = index.by_id.get(scryfall_id)
        if card is None:
            abort(404, description="unknown card id")
        return jsonify({
            "id": card["id"],
            "name": card["name"],
            "mana_cost": card.get("mana_cost"),
            "type_line": card.get("type_line"),
            "oracle_text": card.get("oracle_text"),
            "power": card.get("power"),
            "toughness": card.get("toughness"),
            "colors": card.get("colors", []),
            "image_sizes": sorted((card.get("image_uris") or {}).keys()),
        })

    @app.route("/card_image/<scryfall_id>/<size>")
    def card_image(scryfall_id: str, size: str):
        if size not in SIZES:
            abort(400, description=f"size must be one of {list(SIZES)}")
        card = index.by_id.get(scryfall_id)
        if card is None:
            abort(404, description="unknown card id")
        try:
            path = fetch_image(card, size, root=image_root, fetcher=fetcher)
        except LookupError:
            abort(404, description=f"card has no {size} image")
        return send_file(path, mimetype="image/jpeg")

    return app


@dataclass(frozen=True)
class CliArgs:
    host: str
    port: int


def parse_args(argv: Optional[list[str]] = None) -> CliArgs:
    parser = argparse.ArgumentParser(
        prog="mtg_bot.ui",
        description="Flask web UI for the MTG bot.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help=(
            "Host to bind to (default: 127.0.0.1). "
            "Use 0.0.0.0 to expose on LAN / Tailscale."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5002,
        help="Port to listen on (default: 5002).",
    )
    ns = parser.parse_args(argv)
    return CliArgs(host=ns.host, port=ns.port)


def detect_tailscale_ip() -> Optional[str]:
    """Return this machine's IPv4 Tailscale address, or None if unavailable.

    Shells out to the ``tailscale`` CLI. Returns None if Tailscale isn't
    installed, the command times out, the command exits non-zero, or the
    output is empty.
    """
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    stdout = (result.stdout or "").strip()
    if not stdout:
        return None
    return stdout.splitlines()[0].strip() or None


def describe_urls(host: str, port: int) -> list[str]:
    """Return human-readable URLs to show on startup."""
    if host in ("0.0.0.0", "::", ""):
        urls = [f"http://localhost:{port}"]
        ip = detect_tailscale_ip()
        if ip:
            urls.append(f"http://{ip}:{port}  (Tailscale)")
        return urls
    return [f"http://{host}:{port}"]


def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    for url in describe_urls(args.host, args.port):
        print(f"Serving at {url}")
    create_app().run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":  # pragma: no cover
    main()
