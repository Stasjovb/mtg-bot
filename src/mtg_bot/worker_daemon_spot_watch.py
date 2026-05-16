"""AWS EC2 spot-interruption watcher for the v2 worker daemon.

When ``--spot-watch`` is enabled the daemon starts a poller (this
module, on a daemon thread) that watches the EC2 instance-metadata
**interruption** endpoint. AWS publishes a ~2-minute warning before it
reclaims a spot instance; on the first sighting of that notice the
watcher fires a single ``on_interruption(action, time)`` callback and
stops. The daemon wires that callback to its existing graceful-stop
path (the same one ``/v2/stop`` triggers), so the worker:

1. **stops claiming new games immediately** (the claim loop sees
   ``stop_requested`` and exits the claim/play/report cycle after the
   in-flight game), and
2. **drains its in-flight game locally** rather than getting torn down
   mid-game by the hypervisor.

What this buys us
-----------------

The coordinator reclaims a vanished worker's in-flight claims one of
two ways (see ``mtg_bot.cli.runs.heartbeat_poller`` +
``queue_db.requeue_expired_claims``):

- the heartbeat poller marks the worker ``DEAD`` after
  ``STALE_MAX_S`` (90s) of missed ``/v2/heartbeat`` polls and
  re-queues its claims, OR
- the slower claim-TTL sweep re-queues expired leases.

Without spot-watch, an AWS-reclaimed worker's games sit unreclaimed
for up to ~90s after the instance vanishes (the heartbeat-DEAD path),
because the daemon dies abruptly with no chance to drain. With
spot-watch the daemon gets the ~2-minute warning and proactively
drains, so the games are either *finished and reported* or *released
by the local graceful stop* within seconds — the ~90s
heartbeat-DEAD reclaim lag is removed from the common spot-reclaim
case.

**Scope of the win is "stop claiming + fast LOCAL drain".** As of
this PR the coordinator has **no** proactive per-worker
"reclaim this worker's claims now" endpoint — the v2 surface is
``/v2/stage/*``, ``/v2/claim``, ``/v2/report_result``,
``/v2/weights/<v>``, ``/v2/healthz`` (see
``mtg_bot.cli.runs.v2_endpoints``). We deliberately do NOT invent a
coordinator endpoint here. A still-in-progress game at warning time
is reported normally if it finishes inside the ~2-minute window;
otherwise it falls back to the existing heartbeat/claim-TTL reclaim
once the instance is gone — same as today, just no *new* claims piled
on top. Proactive coordinator-side reclaim (a worker telling the
coordinator "release my claims now" on interruption) is noted as
possible future work in ``docs/DISTRIBUTED_API_v2.md``.

IMDSv2
------

The poll is IMDSv2 (token-authenticated), the AWS default:

1. ``PUT http://169.254.169.254/latest/api/token`` with header
   ``X-aws-ec2-metadata-token-ttl-seconds: 21600`` → an opaque token.
2. ``GET http://169.254.169.254/latest/meta-data/spot/instance-action``
   with header ``X-aws-ec2-metadata-token: <token>``.

The steady-state response to step 2 is **HTTP 404** (no interruption
scheduled). When AWS schedules a reclaim it returns **200** with a
JSON body ``{"action": "terminate"|"stop", "time": "<iso8601>"}``.
A **401** means the token expired (TTL elapsed / IMDS rotated it);
the watcher transparently re-fetches a token and retries.

Separated from :mod:`mtg_bot.worker_daemon` (mirrors
:mod:`mtg_bot.worker_daemon_self_update`) so the HTTP / sleep
plumbing doesn't crowd the Flask handler module and the whole
token→poll→detect loop is unit-testable: the metadata base URL, the
HTTP transport, the poll interval, and the sleep are injectable
seams a test swaps for fakes — no test does real network I/O or
real sleeping.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

#: Link-local EC2 instance-metadata base. Constant on every EC2
#: instance; an injectable :class:`SpotWatchConfig` field so tests
#: point it at a fake transport instead.
DEFAULT_IMDS_BASE = "http://169.254.169.254"

#: IMDSv2 token endpoint (PUT) and the spot interruption endpoint
#: (GET), relative to :data:`DEFAULT_IMDS_BASE`.
TOKEN_PATH = "/latest/api/token"
INSTANCE_ACTION_PATH = "/latest/meta-data/spot/instance-action"

#: TTL we request for the IMDSv2 token (seconds). 6h — the AWS max;
#: long-lived so a steady-state poll rarely pays the token round-trip.
#: A 401 mid-stream still transparently re-fetches.
TOKEN_TTL_S = 21600

#: Default seconds between interruption polls. AWS guarantees ~120s of
#: warning, so 5s leaves plenty of slack to react while keeping IMDS
#: request volume trivial.
DEFAULT_POLL_INTERVAL_S = 5.0

#: Per-request HTTP timeout (seconds). IMDS is link-local and replies
#: in single-digit ms; a generous bound just keeps a wedged request
#: from stalling the watcher thread forever.
DEFAULT_HTTP_TIMEOUT_S = 5.0

#: HTTP header names for the IMDSv2 handshake.
TOKEN_TTL_HEADER = "X-aws-ec2-metadata-token-ttl-seconds"
TOKEN_HEADER = "X-aws-ec2-metadata-token"


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass
class SpotWatchConfig:
    """Inputs for one spot-watch poller.

    ``imds_base`` is the instance-metadata service base URL — constant
    in production, an injectable seam in tests. ``poll_interval_s`` is
    the gap between interruption polls.
    """

    imds_base: str = DEFAULT_IMDS_BASE
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S
    http_timeout_s: float = DEFAULT_HTTP_TIMEOUT_S
    token_ttl_s: int = TOKEN_TTL_S

    @property
    def token_url(self) -> str:
        return f"{self.imds_base.rstrip('/')}{TOKEN_PATH}"

    @property
    def instance_action_url(self) -> str:
        return f"{self.imds_base.rstrip('/')}{INSTANCE_ACTION_PATH}"


@dataclass
class SpotWatchCallbacks:
    """Side-effect seam — mirrors ``ClaimLoop``'s ``StateCallbacks``
    pattern so the poller stays pure and the daemon owns the state
    machine.

    - ``on_interruption`` is called **exactly once**, with the parsed
      ``(action, time)`` from the interruption notice (``action`` is
      ``"terminate"`` or ``"stop"``; ``time`` is the ISO-8601 string
      AWS scheduled the reclaim for, or ``None`` if absent from the
      body). The watcher stops polling after firing it. The daemon
      wires this to its graceful-stop path.
    - ``on_error`` is called with a human-readable detail on any
      transport / parse failure. It is **tolerated** — a flaky IMDS
      call must NOT kill the watcher; polling continues. Default
      production wiring just logs.
    """

    on_interruption: Callable[[str, Optional[str]], None]
    on_error: Callable[[str], None]


class SpotWatchError(RuntimeError):
    """Raised internally by a primitive when an IMDS step fails; the
    poll loop converts it to an ``on_error`` callback and keeps
    polling (a transient IMDS hiccup must not kill the watcher)."""


# ---------------------------------------------------------------------------
# Injectable primitives
# ---------------------------------------------------------------------------

# ``Transport`` is the urllib.request.urlopen-shaped seam every IMDS
# request goes through. The production default is
# :func:`urllib.request.urlopen`; tests pass a fake that routes on the
# request's method / URL and returns canned bodies / raises canned
# urllib errors. We build :class:`urllib.request.Request` objects so
# the IMDSv2 method + headers ride along.
Transport = Callable[..., Any]
# ``Sleeper`` is the time.sleep-shaped seam the inter-poll wait goes
# through so tests advance "time" without really sleeping.
Sleeper = Callable[[float], None]


def fetch_token(
    cfg: SpotWatchConfig,
    *,
    transport: Transport = urllib.request.urlopen,
) -> str:
    """IMDSv2 step 1 — ``PUT <imds_base>/latest/api/token`` with the
    TTL header. Returns the opaque token string.

    Any network failure / empty body is normalized to
    :class:`SpotWatchError`.
    """
    req = urllib.request.Request(
        cfg.token_url,
        method="PUT",
        headers={TOKEN_TTL_HEADER: str(cfg.token_ttl_s)},
    )
    try:
        with transport(req, timeout=cfg.http_timeout_s) as resp:
            token = resp.read().decode("utf-8").strip()
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise SpotWatchError(
            f"IMDSv2 token fetch from {cfg.token_url} failed: {exc}"
        ) from exc
    if not token:
        raise SpotWatchError(
            f"IMDSv2 token fetch from {cfg.token_url} returned an "
            f"empty token"
        )
    return token


def _http_status(exc: urllib.error.HTTPError) -> int:
    """``HTTPError.code`` is the response status; isolated so the poll
    loop reads cleanly."""
    return exc.code


def poll_instance_action(
    cfg: SpotWatchConfig,
    token: str,
    *,
    transport: Transport = urllib.request.urlopen,
) -> Optional[dict[str, Any]]:
    """IMDSv2 step 2 — ``GET <imds_base>/latest/meta-data/spot/
    instance-action`` with the token header.

    Return value encodes the three meaningful outcomes:

    - **No interruption scheduled** → IMDS replies **404**; we return
      ``None`` (the steady-state hot path — NOT an error).
    - **Interruption scheduled** → IMDS replies **200** with a JSON
      body; we return the parsed ``dict``.
    - **Token expired** → IMDS replies **401**; we raise
      :class:`TokenExpired` so the caller re-fetches a token and
      retries this poll without counting it as a hard error.

    Any other HTTP status, a transport failure, or an unparseable
    200 body is normalized to :class:`SpotWatchError`.
    """
    req = urllib.request.Request(
        cfg.instance_action_url,
        method="GET",
        headers={TOKEN_HEADER: token},
    )
    try:
        with transport(req, timeout=cfg.http_timeout_s) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        status = _http_status(exc)
        if status == 404:
            # Steady state: no interruption scheduled. Not an error.
            return None
        if status == 401:
            # Token expired / rotated — caller refreshes + retries.
            raise TokenExpired(
                f"IMDSv2 token rejected (401) at "
                f"{cfg.instance_action_url}"
            ) from exc
        raise SpotWatchError(
            f"unexpected IMDS status {status} at "
            f"{cfg.instance_action_url}"
        ) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise SpotWatchError(
            f"IMDS poll of {cfg.instance_action_url} failed: {exc}"
        ) from exc
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SpotWatchError(
            f"IMDS interruption body was not valid JSON: {exc}"
        ) from exc
    if not isinstance(body, dict):
        raise SpotWatchError(
            f"IMDS interruption body was not a JSON object: "
            f"{body!r}"
        )
    return body


class TokenExpired(SpotWatchError):
    """IMDS returned 401 — the token TTL elapsed or IMDS rotated it.
    The poll loop catches this specifically, re-fetches a token, and
    retries the same poll WITHOUT firing ``on_error`` (an expected,
    self-healing condition, not a fault)."""


def parse_interruption(body: dict[str, Any]) -> tuple[str, Optional[str]]:
    """Extract ``(action, time)`` from a 200 interruption body.

    AWS documents ``{"action": "terminate"|"stop", "time":
    "<iso8601>"}``. We're permissive on shape so a future field /
    casing tweak in IMDS doesn't wedge the drain: ``action`` falls
    back to ``"terminate"`` (the conservative assumption — drain now)
    if missing/blank, ``time`` to ``None``.
    """
    action = str(body.get("action") or "terminate").strip() or "terminate"
    raw_time = body.get("time")
    when = str(raw_time) if raw_time else None
    return action, when


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


class SpotWatcher:
    """The poll loop. Owns the single-fire latch + the cached IMDSv2
    token.

    Construct once per daemon, ``run()`` on a daemon thread. ``run()``
    **never raises**: every transport / parse failure is funneled to
    ``cbs.on_error`` and polling continues (a flaky IMDS call must not
    kill the watcher). The loop exits cleanly only when an
    interruption is detected (after firing ``on_interruption`` exactly
    once) or when :meth:`stop` is called (so the daemon can shut the
    watcher down on a normal/graceful exit).

    The single-fire guarantee is structural: ``_fired`` flips before
    ``on_interruption`` is invoked and the loop ``return``s in the
    same branch, so even a re-entrant callback can't double-fire.
    """

    def __init__(
        self,
        cfg: SpotWatchConfig,
        cbs: SpotWatchCallbacks,
        *,
        transport: Transport = urllib.request.urlopen,
        sleeper: Sleeper = time.sleep,
    ):
        self._cfg = cfg
        self._cbs = cbs
        self._transport = transport
        self._sleeper = sleeper
        self._token: Optional[str] = None
        self._fired = False
        self._stopped = False

    # ------------------------------------------------------------------
    # Control

    def stop(self) -> None:
        """Ask the loop to exit at its next poll boundary. Idempotent.

        Used by the daemon to tear the watcher down on a normal
        shutdown so the thread doesn't outlive the process intent.
        """
        self._stopped = True

    @property
    def fired(self) -> bool:
        """True once ``on_interruption`` has been delivered. Lets the
        daemon / tests assert the single-fire contract."""
        return self._fired

    # ------------------------------------------------------------------
    # Internals

    def _ensure_token(self) -> str:
        """Return the cached token, fetching one on first use / after
        a 401 invalidation."""
        if self._token is None:
            self._token = fetch_token(
                self._cfg, transport=self._transport
            )
        return self._token

    def _poll_once(self) -> Optional[dict[str, Any]]:
        """One interruption poll, transparently refreshing the token on
        a 401. Returns the interruption body, or ``None`` for the
        no-interruption steady state. Raises :class:`SpotWatchError`
        (non-token) on a hard failure for the caller to funnel to
        ``on_error``."""
        token = self._ensure_token()
        try:
            return poll_instance_action(
                self._cfg, token, transport=self._transport
            )
        except TokenExpired:
            # Drop the stale token and retry once with a fresh one. A
            # second failure (including another 401) propagates so the
            # loop logs it via on_error and tries again next tick.
            self._token = None
            token = self._ensure_token()
            return poll_instance_action(
                self._cfg, token, transport=self._transport
            )

    def run(self) -> None:
        """Poll until an interruption is detected or :meth:`stop` is
        called. Never raises; never fires ``on_interruption`` twice.
        """
        while not self._stopped and not self._fired:
            try:
                body = self._poll_once()
            except SpotWatchError as exc:
                # Flaky IMDS / unexpected status — tolerate + keep
                # polling. A real interruption will be caught on a
                # later tick (we have ~120s of warning, well over the
                # default 5s poll interval).
                log.warning("spot-watch poll error: %s", exc)
                self._cbs.on_error(str(exc))
            except Exception as exc:  # defensive — never let the thread die
                log.exception("spot-watch unexpected poll failure")
                self._cbs.on_error(f"unexpected: {exc!r}")
            else:
                if body is not None:
                    action, when = parse_interruption(body)
                    # Flip the latch BEFORE the callback so a
                    # re-entrant / exception-raising callback can't
                    # cause a second fire.
                    self._fired = True
                    log.warning(
                        "spot-watch: interruption notice action=%s "
                        "time=%s — draining worker",
                        action,
                        when,
                    )
                    try:
                        self._cbs.on_interruption(action, when)
                    except Exception as exc:  # defensive
                        log.exception(
                            "spot-watch on_interruption callback raised"
                        )
                        self._cbs.on_error(
                            f"on_interruption raised: {exc!r}"
                        )
                    return
            # Sleep between polls. Skipped once we're stopping/fired so
            # shutdown / detection isn't delayed by a full interval.
            if not self._stopped and not self._fired:
                self._sleeper(self._cfg.poll_interval_s)


def run_spot_watch(
    cfg: SpotWatchConfig,
    cbs: SpotWatchCallbacks,
    *,
    transport: Transport = urllib.request.urlopen,
    sleeper: Sleeper = time.sleep,
) -> SpotWatcher:
    """Build a :class:`SpotWatcher` and run its loop to completion.

    Convenience entry point mirroring
    :func:`mtg_bot.worker_daemon_self_update.perform_self_update`'s
    "single orchestrator call" shape — the daemon targets this from a
    daemon thread. Returns the watcher (already terminated) so the
    caller can introspect :attr:`SpotWatcher.fired` for tests /
    logging. Never raises.
    """
    watcher = SpotWatcher(cfg, cbs, transport=transport, sleeper=sleeper)
    watcher.run()
    return watcher
