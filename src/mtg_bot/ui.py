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
from mtg_bot.game import GameState
from mtg_bot.interactive import create_session, get_session
from mtg_bot.recommend import recommend_from_snapshot, recommend_from_state
from mtg_bot.serialize import serialize_state
from mtg_bot.simulate import simulate_game


_GAME_CACHE_MAX = 20


@dataclass
class CachedGame:
    """One simulated game: the serialized snapshots the UI renders, plus
    a parallel list of engine-state clones for the engine-recommendation
    panel to call PIMC against.

    ``engine_states[i]`` is a clone of the engine state taken at the
    same moment as ``snapshots[i]``. Either list may contain ``None``
    entries — a snapshot whose state wasn't captured falls back to the
    serialize-only recommend path. ``len(snapshots) == len(engine_states)``
    is an invariant; constructors that don't capture states should pass
    ``[None] * len(snapshots)``.
    """

    snapshots: list[dict[str, Any]]
    engine_states: list[Optional[GameState]]


class GameCache:
    """In-memory LRU cache of simulated games produced by /api/play.

    Keys are opaque game ids (hex UUIDs); values are ``CachedGame``
    instances bundling the serialized snapshots and (optionally) the
    engine-state clones at each snapshot. Oldest entries are evicted
    when the cache exceeds ``max_entries``. Not threadsafe — Flask dev
    server is single-request, and prod can add a lock if this ever
    matters.
    """

    def __init__(self, max_entries: int = _GAME_CACHE_MAX) -> None:
        self._games: "OrderedDict[str, CachedGame]" = OrderedDict()
        self._max = max_entries

    def store(
        self,
        game_id: str,
        snapshots: list[dict[str, Any]],
        engine_states: Optional[list[Optional[GameState]]] = None,
    ) -> None:
        if engine_states is None:
            engine_states = [None] * len(snapshots)
        if len(engine_states) != len(snapshots):
            raise ValueError(
                f"engine_states length {len(engine_states)} != "
                f"snapshots length {len(snapshots)}"
            )
        self._games[game_id] = CachedGame(
            snapshots=snapshots, engine_states=engine_states
        )
        self._games.move_to_end(game_id)
        while len(self._games) > self._max:
            self._games.popitem(last=False)

    def get(self, game_id: str) -> Optional[CachedGame]:
        game = self._games.get(game_id)
        if game is not None:
            self._games.move_to_end(game_id)
        return game

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
    replays_root: Optional[Path] = None,
) -> Flask:
    """Build the Flask app.

    All injectables default to production wiring (real Scryfall data, real
    network fetcher, fresh cache). Tests pass fakes.

    ``replays_root`` is the directory ``/api/list_replays`` and
    ``/api/load_replay/<filename>`` read from. Defaults to ``replays/``
    relative to the cwd. Filenames must not contain path-traversal
    components (``..``, absolute paths) — both endpoints reject them.
    """
    app = Flask(__name__)
    index = card_index if card_index is not None else CardIndex.load(DEFAULT_CARD_DATA)
    fetcher = image_fetcher if image_fetcher is not None else http_fetcher
    cache = game_cache if game_cache is not None else GameCache()
    name_to_id = {name: card["id"] for name, card in index.by_name.items()}
    replays_dir = (replays_root or Path("replays")).resolve()

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
        engine_states: list[Optional[GameState]] = []
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
            # Clone the engine state so the engine-recommendation panel
            # can run PIMC against the exact moment the snapshot was
            # taken. The clone is independent of the live state, so the
            # ongoing simulation can mutate freely without corrupting
            # the recommendation surface.
            engine_states.append(state.clone())

        state = simulate_game(
            colors=[c1, c2], seed=seed, max_turns=max_turns,
            on_snapshot=capture,
            snapshot_granularity=granularity,
        )
        game_id = uuid4().hex
        cache.store(game_id, snapshots, engine_states)
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
        game = cache.get(game_id)
        if game is None:
            abort(404, description="unknown game_id")
        if idx < 0 or idx >= len(game.snapshots):
            abort(404, description=f"snapshot idx out of range (0..{len(game.snapshots) - 1})")
        return jsonify(game.snapshots[idx])

    @app.route("/api/recommend/<game_id>/<int:idx>")
    def api_recommend(game_id: str, idx: int):
        """Return the top-N engine recommendations for a specific snapshot.

        Calls PIMC-driven ``recommend_from_state`` when the engine state
        for this snapshot was captured (the standard /api/play path).
        Falls back to ``recommend_from_snapshot`` (the stub) when only
        the serialized snapshot is available — keeps the endpoint
        callable for callers that pre-populated the cache without
        engine states (legacy tests, future sources).
        """
        game = cache.get(game_id)
        if game is None:
            abort(404, description="unknown game_id")
        if idx < 0 or idx >= len(game.snapshots):
            abort(404, description=f"snapshot idx out of range (0..{len(game.snapshots) - 1})")
        n_raw = request.args.get("n", "3")
        try:
            n = int(n_raw)
        except ValueError:
            abort(400, description="n must be an integer")
        if n < 1 or n > 50:
            abort(400, description="n must be between 1 and 50")
        engine_state = game.engine_states[idx]
        if engine_state is not None:
            result = recommend_from_state(
                engine_state, name_to_id=name_to_id, n=n,
            )
        else:
            result = recommend_from_snapshot(game.snapshots[idx], n=n)
        result["snapshot_idx"] = idx
        return jsonify(result)

    @app.route("/api/list_replays")
    def api_list_replays():
        """Return the .json.gz files available in ``replays_root``.

        Scans recursively so iterate_alphazero's per-run subdirectories
        (``replays/iter_001_self_play_v6/foo.json.gz`` etc.) show up.
        Returned filenames are POSIX-style relative subpaths so the
        ``/api/load_replay/<subpath>`` endpoint can locate them
        unambiguously regardless of host OS path-separator quirks.
        Path traversal isn't a risk here (we only return paths
        rooted at ``replays_root``), but we still require the file
        to resolve inside ``replays_root`` when loading.
        """
        if not replays_dir.is_dir():
            return jsonify({"replays": []})
        files = sorted(
            p.relative_to(replays_dir).as_posix()
            for p in replays_dir.rglob("*.json.gz")
        )
        return jsonify({"replays": files, "root": str(replays_dir)})

    @app.route("/api/load_replay/<path:filename>")
    def api_load_replay(filename: str):
        """Load a saved replay file into the cache and return a
        game_id the existing scrubber UI can use.

        ``filename`` may be a single basename (legacy flat layout —
        ``foo.json.gz``) or a POSIX-style subpath under ``replays_root``
        (``iter_001_self_play_v6/foo.json.gz``). Backslashes and
        leading dots are rejected; the resolved path must still live
        inside ``replays_root`` (defense-in-depth against any OS
        path-handling oddity).
        """
        from mtg_bot.replay import load_replay

        # Reject Windows-style separators and any traversal-suggesting
        # leading dot. Forward slashes ARE allowed now to support the
        # per-run subdirectories iterate_alphazero produces.
        if "\\" in filename or filename.startswith("."):
            abort(400, description="invalid replay filename")
        # Block .. anywhere as a component to keep the resolve() check
        # below from being the only line of defense.
        if any(part == ".." for part in filename.split("/")):
            abort(400, description="invalid replay filename")
        if not filename.endswith(".json.gz"):
            abort(400, description="replay filename must end in .json.gz")
        target = (replays_dir / filename).resolve()
        try:
            target.relative_to(replays_dir)
        except ValueError:
            abort(400, description="replay path outside replays_root")
        if not target.is_file():
            abort(404, description=f"replay not found: {filename}")

        replay = load_replay(target)
        # The stored snapshots may not have been enriched with
        # scryfall_ids — replay capture writes raw serialize_state
        # output. Enrich on load so the scrubber can render images.
        snapshots = [
            _enrich_snapshot(dict(s), name_to_id)
            for s in replay.snapshots
        ]
        engine_states = [None] * len(snapshots)
        game_id = uuid4().hex
        cache.store(game_id, snapshots, engine_states)
        return jsonify({
            "game_id": game_id,
            "snapshot_count": len(snapshots),
            "metadata": replay.metadata,
            "source_filename": filename,
        })

    @app.route("/api/snapshots_index/<game_id>")
    def api_snapshots_index(game_id: str):
        """Compact index of every snapshot's turn + step, for fast step/turn
        navigation in the scrubber without fetching each snapshot's full
        payload. Returned as a parallel array so the client can index by
        snapshot idx directly.

        ``log_size`` is the cumulative ``len(snapshot.log)`` at that moment.
        Logs grow monotonically across snapshots, so a client wanting to
        find "which snapshot first introduced log entry N" can binary-
        search this array for the smallest index where ``log_size > N``."""
        game = cache.get(game_id)
        if game is None:
            abort(404, description="unknown game_id")
        return jsonify([
            {
                "turn_number": s["turn_number"],
                "step": s["step"],
                "log_size": len(s["log"]),
            }
            for s in game.snapshots
        ])

    @app.route("/api/log/<game_id>")
    def api_log(game_id: str):
        """Return the game's complete log as a flat array of strings.

        The viewer fetches this once at activation so it can render the
        whole game's events, including future ones, with each entry
        clickable to jump (forward or backward) to the snapshot that
        introduced it. Logs only grow across snapshots, so the final
        snapshot's log is the canonical full log; if there are no
        snapshots, the result is an empty list."""
        game = cache.get(game_id)
        if game is None:
            abort(404, description="unknown game_id")
        if not game.snapshots:
            return jsonify([])
        return jsonify(list(game.snapshots[-1]["log"]))

    # ------------------------------------------------------------------
    # Interactive play API.  All routes are under /api/interactive/.
    # ------------------------------------------------------------------

    @app.route("/api/interactive/new", methods=["POST"])
    def api_interactive_new():
        """Start a new interactive game and return the session_id.

        Expected JSON body::

            {
                "seed": 0,
                "c1": "G",     // color for Player 0
                "c2": "R",     // color for Player 1
                "human_player": 0,   // 0 or 1
                "max_turns": 300
            }
        """
        body = request.get_json(force=True, silent=True) or {}
        seed = int(body.get("seed", 0))
        c1 = body.get("c1", "G")
        c2 = body.get("c2", "R")
        if c1 not in COLORS:
            abort(400, description=f"c1 must be one of {list(COLORS)}")
        if c2 not in COLORS:
            abort(400, description=f"c2 must be one of {list(COLORS)}")
        human_player = int(body.get("human_player", 0))
        if human_player not in (0, 1):
            abort(400, description="human_player must be 0 or 1")
        max_turns = int(body.get("max_turns", 300))
        if max_turns < 1:
            abort(400, description="max_turns must be >= 1")

        def enrich(state):
            snap = _enrich_snapshot(serialize_state(state), name_to_id)
            return snap

        session = create_session(
            seed=seed,
            colors=[c1, c2],
            human_player_id=human_player,
            n2id=name_to_id,
            enrich_fn=enrich,
            max_turns=max_turns,
        )
        return jsonify({
            "session_id": session.session_id,
            "human_player_id": human_player,
            "colors": [c1, c2],
            "seed": seed,
        })

    @app.route("/api/interactive/state/<session_id>")
    def api_interactive_state(session_id: str):
        """Return the current board snapshot and any pending decision.

        Poll this endpoint at ~250ms intervals while the game is live.
        When ``pending`` is non-null, the human player must act.
        When ``is_over`` is true, ``result`` describes the outcome.
        """
        session = get_session(session_id)
        if session is None:
            abort(404, description="unknown session_id")
        return jsonify(session.get_state())

    @app.route("/api/interactive/action/<session_id>", methods=["POST"])
    def api_interactive_action(session_id: str):
        """Submit the human player's response to the current pending decision.

        Expected JSON body::

            {"response": <value>}

        The shape of ``value`` depends on the pending decision ``type``:

        * ``choose_action``      → ``{"idx": N}``
        * ``declare_attackers``  → ``{"ids": [N, ...]}``
        * ``declare_blockers``   → ``{"assignments": {"blocker_id": attacker_id, ...}}``
        * ``choose_target``      → ``{"idx": N}`` or ``{"decline": true}``
        * ``choose_discard``     → ``{"id": N}``
        * ``choose_surveil``     → ``{"mill": true|false}``
        * ``choose_sacrifice``   → ``{"id": N}``
        * ``choose_mode``        → ``{"idx": N}``
        * ``choose_modes``       → ``{"indices": [N, ...]}``
        * ``choose_yes_no``      → ``{"yes": true|false}``
        * ``choose_card``        → ``{"id": N}`` or ``{"decline": true}``
        * ``choose_x``           → ``{"value": N}``
        * ``choose_multi_ids``   → ``{"ids": [N, ...]}``
        * ``choose_mana_color``  → ``{"color": "G"}``
        * ``choose_one_id``      → ``{"id": N}``
        """
        session = get_session(session_id)
        if session is None:
            abort(404, description="unknown session_id")
        if session.is_over:
            abort(400, description="game is already over")
        body = request.get_json(force=True, silent=True) or {}
        if "response" not in body:
            abort(400, description="missing 'response' field")
        session.human_agent.submit_response(body["response"])
        return jsonify({"ok": True})

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
    replays_root: Optional[Path]


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
    parser.add_argument(
        "--replays-root",
        type=Path,
        default=None,
        help=(
            "Directory to serve replay files from. ``/api/list_replays`` "
            "scans this recursively, so iterate_alphazero's per-run "
            "subdirectories (replays/iter_001_self_play_v6/...) show up. "
            "Default: 'replays' under the cwd."
        ),
    )
    ns = parser.parse_args(argv)
    return CliArgs(
        host=ns.host, port=ns.port, replays_root=ns.replays_root,
    )


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
    create_app(replays_root=args.replays_root).run(
        host=args.host, port=args.port, debug=False,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
