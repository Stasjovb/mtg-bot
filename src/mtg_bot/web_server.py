"""Run the Forgetful Fish website with a production server.

``python -m mtg_bot.web_server`` serves the website (see :func:`mtg_bot.ui.create_app`)
with waitress, which is pure Python: the same command runs on this PC and in a
Linux container. Everything is set with environment variables:

- ``MTG_BOT_HOST``: interface to bind. Default ``127.0.0.1``; the Docker image
  sets ``0.0.0.0``.
- ``PORT`` (or ``MTG_BOT_PORT``): port. Default ``5002``.
- ``MTG_BOT_CARD_POOL``: card pool. Default ``fish``.
- ``MTG_BOT_FEEDBACK_DIR``: where Feedback reports and ``REVIEW_LIST.md`` are
  written (see :mod:`mtg_bot.feedback`).
- ``MTG_BOT_REPLAYS_ROOT``: folder the replay list reads. Default ``replays``
  in the working directory.
- ``MTG_BOT_SECRET_KEY``: Flask's secret key, which signs the log-in cookies.
  When unset a random key is made for each start, so everyone has to log in
  again after a restart; set it to keep log-ins across restarts.
- ``MTG_BOT_INVITE_CODE``: when set, the site has accounts (see
  :mod:`mtg_bot.accounts`): every page and API route needs a log-in, and people
  register with this invite code. It replaces the password gate below.
- ``MTG_BOT_ACCOUNTS_FILE``: the accounts file. Default ``accounts/accounts.json``
  in the working directory.
- ``MTG_BOT_ACCESS_PASSWORD``: without accounts, every page needs HTTP basic
  authentication with this password (any user name). When unset the site is
  open to anyone who can reach it. Basic authentication sends the password
  with every request, so use it only behind HTTPS.

The health check ``/healthz`` never asks for the password or a log-in.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5002
DEFAULT_CARD_POOL = "fish"
SERVER_THREADS = 8
HEALTH_PATH = "/healthz"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServerSettings:
    host: str
    port: int
    card_pool: str
    feedback_root: Optional[Path]
    replays_root: Optional[Path]
    secret_key: Optional[str]
    access_password: Optional[str]
    invite_code: Optional[str] = None
    accounts_file: Optional[Path] = None


def load_settings(env: Optional[Mapping[str, str]] = None) -> ServerSettings:
    """The server settings from the environment (``os.environ`` by default).
    Empty values count as unset."""
    env = os.environ if env is None else env

    def value(name: str) -> Optional[str]:
        return env.get(name) or None

    port_text = value("PORT") or value("MTG_BOT_PORT") or str(DEFAULT_PORT)
    try:
        port = int(port_text)
    except ValueError:
        raise ValueError(f"the port must be a number, got {port_text!r}") from None
    if not 1 <= port <= 65535:
        raise ValueError(f"the port must be 1-65535, got {port}")

    feedback = value("MTG_BOT_FEEDBACK_DIR")
    replays = value("MTG_BOT_REPLAYS_ROOT")
    accounts = value("MTG_BOT_ACCOUNTS_FILE")
    return ServerSettings(
        host=value("MTG_BOT_HOST") or DEFAULT_HOST,
        port=port,
        card_pool=value("MTG_BOT_CARD_POOL") or DEFAULT_CARD_POOL,
        feedback_root=Path(feedback) if feedback else None,
        replays_root=Path(replays) if replays else None,
        secret_key=value("MTG_BOT_SECRET_KEY"),
        access_password=value("MTG_BOT_ACCESS_PASSWORD"),
        invite_code=value("MTG_BOT_INVITE_CODE"),
        accounts_file=Path(accounts) if accounts else None,
    )


def password_matches(authorization: str, password: str) -> bool:
    """True when an ``Authorization: Basic ...`` header carries ``password``
    (the user name is ignored)."""
    if not authorization.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(authorization[len("Basic "):], validate=True)
    except (binascii.Error, ValueError):
        return False
    _, _, given = decoded.decode("utf-8", errors="replace").partition(":")
    return hmac.compare_digest(given.encode("utf-8"), password.encode("utf-8"))


def basic_auth_gate(app: Callable, password: str) -> Callable:
    """WSGI middleware: every request except the health check needs the
    password (HTTP basic authentication)."""
    body = b"Password required."

    def gate(environ, start_response):
        if environ.get("PATH_INFO") == HEALTH_PATH:
            return app(environ, start_response)
        if password_matches(environ.get("HTTP_AUTHORIZATION", ""), password):
            return app(environ, start_response)
        start_response("401 Unauthorized", [
            ("WWW-Authenticate", 'Basic realm="Forgetful Fish"'),
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ])
        return [body]

    return gate


ACCOUNT_OPEN_PATHS = frozenset({"/healthz", "/login", "/register", "/logout"})
SESSION_DAYS = 30


def install_accounts(app, store) -> None:
    """Log-ins for the site (see :mod:`mtg_bot.accounts`): every page and API
    route needs a logged-in session, except the health check, the log-in pages
    and the static files. An API call without a log-in gets a 401 JSON answer;
    a page goes to ``/login``."""
    from datetime import timedelta

    from flask import jsonify, redirect, render_template, request, session

    from mtg_bot.accounts import AccountError

    app.permanent_session_lifetime = timedelta(days=SESSION_DAYS)

    @app.before_request
    def require_log_in():
        path = request.path
        if path in ACCOUNT_OPEN_PATHS or path.startswith("/static/"):
            return None
        if session.get("user"):
            return None
        if path.startswith("/api/"):
            return jsonify({"error": "Log in first."}), 401
        return redirect("/login")

    def start_session(name: str) -> None:
        session.clear()
        session.permanent = True
        session["user"] = name

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "GET":
            return render_template("login.html", mode="login", error=None, username="")
        typed = request.form.get("username", "")
        try:
            name = store.verify(typed, request.form.get("password", ""))
        except AccountError as exc:
            return render_template(
                "login.html", mode="login", error=str(exc), username=typed,
            ), 401
        start_session(name)
        return redirect("/")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "GET":
            return render_template("login.html", mode="register", error=None, username="")
        typed = request.form.get("username", "")
        try:
            name = store.register(
                typed, request.form.get("password", ""), request.form.get("invite_code", ""),
            )
        except AccountError as exc:
            return render_template(
                "login.html", mode="register", error=str(exc), username=typed,
            ), 400
        start_session(name)
        return redirect("/")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect("/login")


def make_app(settings: Optional[ServerSettings] = None) -> Callable:
    """The WSGI application for ``settings`` (read from the environment when
    not given), with the health check and the optional password gate."""
    from flask import jsonify

    from mtg_bot.ui import create_app

    settings = settings or load_settings()
    app = create_app(
        replays_root=settings.replays_root,
        feedback_root=settings.feedback_root,
    )
    if settings.secret_key is None:
        logger.warning(
            "MTG_BOT_SECRET_KEY is not set: using a random secret key for this run",
        )
    app.config["SECRET_KEY"] = settings.secret_key or secrets.token_hex(32)

    @app.route(HEALTH_PATH)
    def healthz():
        return jsonify({"status": "ok"})

    if settings.invite_code:
        from mtg_bot.accounts import AccountStore

        if settings.access_password:
            logger.warning(
                "MTG_BOT_ACCESS_PASSWORD is ignored: log-ins with accounts "
                "(MTG_BOT_INVITE_CODE) replace it",
            )
        accounts_file = settings.accounts_file or Path("accounts") / "accounts.json"
        install_accounts(app, AccountStore(accounts_file, settings.invite_code))
        return app.wsgi_app
    if settings.access_password:
        return basic_auth_gate(app.wsgi_app, settings.access_password)
    return app.wsgi_app


def main() -> None:  # pragma: no cover - the entry point; tests call make_app
    from waitress import serve

    settings = load_settings()
    os.environ.setdefault("MTG_BOT_CARD_POOL", settings.card_pool)
    logging.basicConfig(level=logging.INFO)
    print(f"Serving at http://{settings.host}:{settings.port}")
    serve(make_app(settings), host=settings.host, port=settings.port, threads=SERVER_THREADS)


if __name__ == "__main__":  # pragma: no cover
    main()
