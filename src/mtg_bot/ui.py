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
from dataclasses import dataclass
from typing import Optional

from flask import Flask, abort, render_template_string, request

from mtg_bot.cards import COLORS
from mtg_bot.serialize import serialize_state
from mtg_bot.simulate import simulate_game


_BASE_STYLE = """
body { font-family: -apple-system, Segoe UI, sans-serif; margin: 1.5em;
       background: #1a1a2e; color: #eee; }
h1 { margin: 0 0 0.5em; }
h2 { margin: 0 0 0.3em; font-size: 1.1em; }
h3 { margin: 1em 0 0.4em; }
a { color: #9cf; }
form { background: #222; padding: 1em; border-radius: 6px; margin-bottom: 1em;
       display: flex; flex-wrap: wrap; gap: 0.8em; align-items: center; }
form label { display: inline-flex; align-items: center; gap: 0.3em; }
form input, form select { background: #111; color: #eee; border: 1px solid #444;
                          padding: 0.3em 0.5em; border-radius: 3px; }
form button { background: #446; color: #eee; border: none; padding: 0.4em 1em;
              border-radius: 3px; cursor: pointer; }
form button:hover { background: #558; }
.player { border: 2px solid #333; padding: 0.8em; margin-bottom: 0.8em;
          border-radius: 6px; }
.player.lost { border-color: #a44; opacity: 0.85; }
.player.winner { border-color: #4a4; }
.life { font-size: 1.8em; font-weight: bold; display: inline-block;
        min-width: 1.8em; text-align: center; }
.life.low { color: #f66; }
.life.high { color: #6f6; }
.cards { display: flex; flex-wrap: wrap; gap: 0.3em; margin: 0.3em 0; }
.card { background: #333; padding: 0.25em 0.5em; border-radius: 3px;
        font-size: 0.85em; white-space: nowrap; }
.card.tapped { opacity: 0.55; }
.card.land { background: #2a3544; }
.card.creature { background: #2a4432; }
.card .pt { color: #fc8; font-weight: bold; }
.card .dmg { color: #f77; }
.result { padding: 0.8em 1em; border-radius: 6px; margin-bottom: 1em;
          font-size: 1.15em; background: #2a2a4e; }
.result.winner { border-left: 4px solid #6f6; }
.result.draw { border-left: 4px solid #aaa; }
.log { background: #111; padding: 0.8em; border-radius: 4px;
       max-height: 380px; overflow-y: auto; font-family: ui-monospace, monospace;
       font-size: 0.85em; }
.log .entry { padding: 1px 0; }
.meta { color: #999; font-size: 0.85em; }
"""

_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>MTG Bot — Game Viewer</title>
<style>{{ style }}</style>
</head>
<body>
<h1>MTG Bot — Game Viewer</h1>
<form action="/play" method="get">
  <label>Seed <input type="number" name="seed" value="{{ seed }}" /></label>
  <label>P0 color
    <select name="c1">
      {% for c in colors %}<option value="{{ c }}" {% if c == c1 %}selected{% endif %}>{{ c }}</option>{% endfor %}
    </select>
  </label>
  <label>P1 color
    <select name="c2">
      {% for c in colors %}<option value="{{ c }}" {% if c == c2 %}selected{% endif %}>{{ c }}</option>{% endfor %}
    </select>
  </label>
  <label>Max turns <input type="number" name="max_turns" value="{{ max_turns }}" /></label>
  <button type="submit">Run game</button>
</form>

{% if data %}
  <div class="result {% if data.is_draw %}draw{% elif data.winner_id is not none %}winner{% endif %}">
    {% if data.is_draw %}Result: DRAW
    {% elif data.winner_id is not none %}Result: Player {{ data.winner_id }} wins
    {% else %}Game did not finish
    {% endif %}
    <span class="meta">— after {{ data.turn_number }} turn(s), {{ data.log | length }} log events</span>
  </div>

  {% for p in data.players %}
    <div class="player {% if p.has_lost %}lost{% elif data.winner_id == p.id %}winner{% endif %}">
      <h2>Player {{ p.id }}
        {% if p.has_lost %}<span class="meta">— lost: {{ p.lost_reason }}</span>
        {% elif data.winner_id == p.id %}<span class="meta">— winner</span>
        {% endif %}
      </h2>
      <span class="life {% if p.life <= 5 %}low{% elif p.life >= 15 %}high{% endif %}">{{ p.life }}</span>
      <span class="meta">life • library {{ p.library_size }} • graveyard {{ p.graveyard_size }} • hand {{ p.hand_size }}</span>
      {% if p.hand %}
        <div><strong>Hand:</strong></div>
        <div class="cards">
          {% for c in p.hand %}
            <span class="card">{{ c.name }}{% if c.mana_cost %} {{ c.mana_cost }}{% endif %}{% if c.power is not none %} <span class="pt">{{ c.power }}/{{ c.toughness }}</span>{% endif %}</span>
          {% endfor %}
        </div>
      {% endif %}
      {% if p.battlefield %}
        <div><strong>Battlefield:</strong></div>
        <div class="cards">
          {% for o in p.battlefield %}
            <span class="card {% if o.tapped %}tapped{% endif %} {% if o.is_land %}land{% elif o.is_creature %}creature{% endif %}">
              {{ o.name }}{% if o.is_creature %} <span class="pt">{{ o.power }}/{{ o.toughness }}</span>{% if o.damage %} <span class="dmg">[{{ o.damage }}]</span>{% endif %}{% endif %}
            </span>
          {% endfor %}
        </div>
      {% endif %}
    </div>
  {% endfor %}

  {% if data.stack %}
    <h3>Stack ({{ data.stack | length }})</h3>
    <div class="cards">
      {% for item in data.stack %}<span class="card">{{ item.name }} (P{{ item.controller_id }})</span>{% endfor %}
    </div>
  {% endif %}

  <h3>Game Log</h3>
  <div class="log">
    {% for entry in data.log %}<div class="entry">{{ entry }}</div>{% endfor %}
  </div>
{% else %}
  <p class="meta">Pick a seed and colors, then run a game.</p>
{% endif %}
</body>
</html>
"""


def _parse_int_arg(name: str, default: int) -> int:
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        abort(400, description=f"{name} must be an integer")


def create_app() -> Flask:
    app = Flask(__name__)

    @app.route("/")
    def index():
        return render_template_string(
            _PAGE_HTML,
            style=_BASE_STYLE,
            colors=list(COLORS),
            seed=0,
            c1="G",
            c2="R",
            max_turns=300,
            data=None,
        )

    @app.route("/play")
    def play():
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

        state = simulate_game(colors=[c1, c2], seed=seed, max_turns=max_turns)
        data = serialize_state(state)
        return render_template_string(
            _PAGE_HTML,
            style=_BASE_STYLE,
            colors=list(COLORS),
            seed=seed,
            c1=c1,
            c2=c2,
            max_turns=max_turns,
            data=data,
        )

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
