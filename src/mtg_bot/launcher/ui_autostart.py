"""Best-effort training-UI auto-start.

The launcher calls :func:`ensure_training_ui` before it registers the
cycle row. If the training UI is already responding at
``cfg.ui.base_url``, the call is a no-op. Otherwise the helper asks
the hub (port 9000) to start the registered project
``mtg_bot_train_ui_windows`` and waits up to 30s for it to become
responsive.

Failure is **never fatal**: every error path logs at WARNING and
returns. The launcher must not be coupled to the UI's liveness --
the operator can also start the UI manually, or simply not care if
they don't need it for this cycle.

Why this lives in its own module: testability. The Phase A launcher
already imports heavy modules; adding HTTP-poll-sleep logic to
``iterate_distributed.py`` would force every unit test to patch
``time.sleep`` and stub urllib. Pulling the side-effect surface into
:mod:`mtg_bot.launcher.ui_autostart` keeps the launcher CLI module
mockable with a single ``monkeypatch.setattr(id_mod,
'ensure_training_ui', stub)``.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Optional
from urllib.parse import urljoin


logger = logging.getLogger(__name__)


# The hub project id for the Windows-native training UI. Matches the
# entry in ``hub/app.py``'s PROJECTS list. The launcher only ever
# triggers the Windows-native UI auto-start; the WSL2-side UI on
# port 5003 is operator-managed (and offline as of 2026-05).
DEFAULT_UI_PROJECT_ID = "mtg_bot_train_ui_windows"

# The hub itself. Hardcoded because the hub is a singleton on the
# master at a well-known port (see CLAUDE.md "Dev Hub" section).
DEFAULT_HUB_URL = "http://localhost:9000"

# Readiness probe path. The training UI doesn't currently expose a
# dedicated ``/healthz`` -- ``/api/runs?limit=1`` is the cheapest
# read that exercises the Flask route table + the SQLite open path.
# If a real ``/healthz`` lands later, swap the constant; the polling
# loop accepts any 2xx as a pass.
READINESS_PROBE_PATH = "/api/runs?limit=1"

# Defaults tuned for the Windows-native Flask UI's cold-start time
# (~3-8s on the master; pad to 30s for safety on a slow disk).
DEFAULT_WAIT_TIMEOUT_S = 30.0
DEFAULT_POLL_INTERVAL_S = 0.5


class UiAutostartError(RuntimeError):
    """Raised when the hub returns a non-200 to the start request.

    The launcher catches this + logs a warning -- never propagates.
    Exposed so unit tests can assert on the error path explicitly.
    """


def _http_get(
    url: str, *, timeout: float = 3.0,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> tuple[int, bytes]:
    """GET ``url`` and return ``(status, body)``. Network errors
    propagate; the caller decides how to translate them."""
    req = urllib.request.Request(url, method="GET")
    with opener(req, timeout=timeout) as resp:
        return resp.status, resp.read()


def _http_post(
    url: str, *, timeout: float = 5.0,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> tuple[int, bytes]:
    """POST ``url`` with an empty body. Used for the hub's
    ``/api/start/<project_id>`` endpoint which doesn't take a
    request body."""
    req = urllib.request.Request(url, method="POST", data=b"")
    with opener(req, timeout=timeout) as resp:
        return resp.status, resp.read()


def is_ui_responding(
    base_url: str,
    *,
    timeout: float = 3.0,
    opener: Optional[Callable[..., Any]] = None,
) -> bool:
    """``True`` if ``GET <base_url>/api/runs?limit=1`` returns 2xx.

    Any network error (connection refused, timeout, DNS failure, ...)
    returns ``False`` -- the contract is "is the UI reachable", not
    "did the probe succeed without exceptions". ``opener`` is a test
    injection point so the unit tests can stub urllib without
    monkeypatching the global.
    """
    probe_url = urljoin(base_url.rstrip("/") + "/", READINESS_PROBE_PATH.lstrip("/"))
    kwargs: dict[str, Any] = {"timeout": timeout}
    if opener is not None:
        kwargs["opener"] = opener
    try:
        status, _ = _http_get(probe_url, **kwargs)
    except (urllib.error.URLError, OSError, ConnectionError):
        return False
    return 200 <= status < 300


def request_hub_start(
    project_id: str = DEFAULT_UI_PROJECT_ID,
    *,
    hub_url: str = DEFAULT_HUB_URL,
    timeout: float = 5.0,
    opener: Optional[Callable[..., Any]] = None,
) -> dict[str, Any]:
    """POST ``<hub_url>/api/start/<project_id>``. Returns the parsed
    JSON response body. Raises :class:`UiAutostartError` on non-2xx.

    The hub's response shape (see ``hub/app.py:api_start``):

    - ``{"message": "already running", "running": True}`` if the port
      is already bound.
    - ``{"message": "starting...", "running": False}`` if the start
      is already in flight.
    - ``{"started": True}`` if this call kicked off the launch.

    The launcher treats all three as "success, now poll the UI" --
    the distinction matters for logging but not for control flow.
    """
    start_url = urljoin(hub_url.rstrip("/") + "/", f"api/start/{project_id}")
    kwargs: dict[str, Any] = {"timeout": timeout}
    if opener is not None:
        kwargs["opener"] = opener
    try:
        status, body = _http_post(start_url, **kwargs)
    except (urllib.error.URLError, OSError, ConnectionError) as exc:
        raise UiAutostartError(
            f"hub POST {start_url} failed: {exc}; is the hub running "
            f"on port 9000?",
        ) from exc
    if not (200 <= status < 300):
        raise UiAutostartError(
            f"hub POST {start_url} returned HTTP {status}: "
            f"{body[:200]!r}",
        )
    try:
        return json.loads(body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UiAutostartError(
            f"hub POST {start_url}: malformed JSON response: {exc}",
        ) from exc


def wait_for_ui_ready(
    base_url: str,
    *,
    timeout_s: float = DEFAULT_WAIT_TIMEOUT_S,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
    opener: Optional[Callable[..., Any]] = None,
) -> bool:
    """Poll the readiness probe until 2xx or ``timeout_s`` elapses.

    Returns ``True`` on success, ``False`` on timeout. ``sleep`` /
    ``now`` are injected for deterministic tests -- production callers
    take the defaults.
    """
    deadline = now() + timeout_s
    while True:
        if is_ui_responding(base_url, opener=opener):
            return True
        if now() >= deadline:
            return False
        sleep(poll_interval_s)


def ensure_training_ui(
    base_url: str,
    *,
    project_id: str = DEFAULT_UI_PROJECT_ID,
    hub_url: str = DEFAULT_HUB_URL,
    wait_timeout_s: float = DEFAULT_WAIT_TIMEOUT_S,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
    opener: Optional[Callable[..., Any]] = None,
) -> bool:
    """Best-effort: make sure the training UI at ``base_url`` is up.

    Flow:

    1. Probe ``base_url`` -- if it's already responding, return True
       (no hub call needed).
    2. POST ``<hub_url>/api/start/<project_id>`` to ask the hub to
       launch the registered project.
    3. Poll the readiness probe until 2xx or ``wait_timeout_s``
       elapses.
    4. Log at INFO on success (with started state), at WARNING on
       any failure path. Failures NEVER raise out of this function;
       the launcher's contract is "UI auto-start is best-effort".

    Returns ``True`` if the UI is responsive when this function
    returns, ``False`` otherwise (operator can still launch it
    manually or click the hub's Start button).
    """
    if is_ui_responding(base_url, opener=opener):
        logger.info(
            "[ui_autostart] training UI already up at %s; no action.",
            base_url,
        )
        return True

    logger.info(
        "[ui_autostart] training UI not responding at %s; asking hub "
        "to start project %r.",
        base_url, project_id,
    )
    try:
        resp = request_hub_start(
            project_id, hub_url=hub_url, opener=opener,
        )
    except UiAutostartError as exc:
        logger.warning(
            "[ui_autostart] hub start request failed: %s; the "
            "launcher will continue without the UI -- start it "
            "manually if you need it.",
            exc,
        )
        return False

    logger.info("[ui_autostart] hub start response: %s", resp)

    ready = wait_for_ui_ready(
        base_url,
        timeout_s=wait_timeout_s,
        poll_interval_s=poll_interval_s,
        sleep=sleep,
        now=now,
        opener=opener,
    )
    if ready:
        logger.info(
            "[ui_autostart] training UI is now responding at %s.",
            base_url,
        )
    else:
        logger.warning(
            "[ui_autostart] training UI did not respond at %s "
            "within %.1fs; continuing without it. Check the hub "
            "(http://localhost:9000) or the UI's start log.",
            base_url, wait_timeout_s,
        )
    return ready


__all__ = [
    "DEFAULT_HUB_URL",
    "DEFAULT_POLL_INTERVAL_S",
    "DEFAULT_UI_PROJECT_ID",
    "DEFAULT_WAIT_TIMEOUT_S",
    "READINESS_PROBE_PATH",
    "UiAutostartError",
    "ensure_training_ui",
    "is_ui_responding",
    "request_hub_start",
    "wait_for_ui_ready",
]
