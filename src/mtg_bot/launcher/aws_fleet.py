"""AWS spot-fleet manager for the unified distributed-iter launcher.

Owns the lifecycle of an ephemeral EC2 spot fleet: pick an AZ, call
``ec2.run_instances`` with the launcher's runspec template, poll for
each instance to come up + register on the tailnet + answer
``GET /v2/heartbeat`` with ``state=IDLE``, hand the resulting list of
tailnet URLs back to the launcher's main flow, and tear the fleet
down on cycle finalisation (success OR failure).

Phase B scope deliberately stays *open-loop*:

- Spot reclaim mid-iter is NOT auto-recovered. If AWS pulls an
  instance, the heartbeat poller in the coordinator notices
  (state=DEAD) and the launcher logs it, but no new instance gets
  spawned to replace it. Iterate's shard rebalance handles the
  reduced fleet for the rest of the cycle. (v2 launcher scope.)
- No cost-cap kill switch. Spot pricing is monitored separately.
- ``user-data.worker.warm.sh`` is the single bootstrap script; no
  per-iter variant. The script is base64-encoded and stuffed into
  the runspec's ``UserData`` field at launch time.

The interesting design choice: ``boto3_client`` is an injection point
on ``FleetManager.__init__`` so the moto-backed tests pass in a
``mock_aws``-decorated ``boto3.client('ec2', ...)`` and the rest of
the class flows without a single ``import moto``. The production
path constructs the client lazily from ``boto3.client('ec2',
region_name=...)`` if nothing was injected.
"""

from __future__ import annotations

import base64
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

# botocore.exceptions.ClientError is the canonical AWS error type
# (raised for InsufficientInstanceCapacity, SpotMaxPriceTooLow,
# UnauthorizedOperation, ...). We catch it explicitly in the AZ
# fallback loop and re-raise / fall through based on the error code.
from botocore.exceptions import ClientError

from mtg_bot.launcher.config import AwsSection
from mtg_bot.launcher.state import LaunchPaths, write_aws_instances_json


logger = logging.getLogger(__name__)


# The canonical AMI baked with python3.13 + cpu-only torch + the
# mtg-bot repo + the .pyd + the deck pool. See
# ``project_mtg_bot_aws_warm_launch`` in the user's memory for the
# bake history. Override via ``MTG_BOT_AWS_AMI_ID`` env var (not
# wired through config today; the template's ``{{ami_id}}`` would
# accept a config field if/when needed).
DEFAULT_AMI_ID = "ami-07bd7300ab2800515"

# Region inferred from the AZ (e.g. ``us-east-1a`` -> ``us-east-1``).
# A future config field could override this; for now the launcher
# only operates in one region per cycle and the AZ list disambiguates.
def _region_from_az(az: str) -> str:
    """Strip the trailing zone letter from an AZ to get the region.

    ``us-east-1a`` -> ``us-east-1``. AWS guarantees the last char of
    an AZ is the zone identifier; this is the standard way SDKs
    derive region from AZ.
    """
    if len(az) < 2 or not az[-1].isalpha():
        raise FleetConfigError(
            f"az {az!r}: does not look like an AWS AZ "
            f"(expected suffix like '...1a' / '...2c')",
        )
    return az[:-1]


# Heartbeat / readiness defaults. The launcher overrides via
# ``wait_for_healthy(timeout_s=...)`` when a slower bootstrap is
# acceptable; the default 900s (15 min) covers the warm-AMI's
# real-world ~7-10 min worst case: tailscale auth + repo.bundle
# pull (the bundle is ~75MB and Tailscale -> WSL2/Windows coord
# can throttle to ~1MB/s, so the curl has a 180s budget) + boot-
# time boto3 install (~5s) + daemon startup + the bootstrap
# script's own 36*5s=180s internal healthcheck loop. Previous
# 420s default was too tight and timed out wait_for_healthy on
# instances that DID eventually reach IDLE.
HEARTBEAT_POLL_INTERVAL_S = 5.0
WORKER_PORT = 5198

# Errors that mean "this AZ doesn't have capacity right now -- try
# the next one in az_fallback". Anything else propagates up to the
# launcher (auth / quota / misconfig / ...).
_RETRYABLE_AZ_ERRORS = frozenset({
    "InsufficientInstanceCapacity",
    "SpotMaxPriceTooLow",
    # Spot can also reject with these less-common codes for the same
    # "no capacity in this AZ" semantic; we include them so a real
    # quota miss doesn't masquerade as a spot-supply blip.
    "Unsupported",  # e.g. instance type not available in this AZ
    "MaxSpotInstanceCountExceeded",
})


# ---------------------------------------------------------------------------
# Exception types
# ---------------------------------------------------------------------------


class FleetConfigError(ValueError):
    """A required input (AZ list, template path, runspec field) is
    malformed -- raised before any AWS call so a bad config can't
    even attempt to spin instances."""


class FleetCapacityError(RuntimeError):
    """Every AZ in ``aws.az_fallback`` returned a retryable
    capacity error. The launcher surfaces this as "no spot capacity
    in any AZ; try again later or widen the AZ list".

    Carries the per-AZ error codes for forensics::

        FleetCapacityError("no capacity in any AZ",
            attempts=[("us-east-1a", "InsufficientInstanceCapacity"),
                      ("us-east-1b", "SpotMaxPriceTooLow")])
    """

    def __init__(self, message: str, *, attempts: list[tuple[str, str]]):
        super().__init__(message)
        self.attempts = attempts


class FleetHealthTimeoutError(RuntimeError):
    """``wait_for_healthy`` ran out of time before every instance
    answered ``/v2/heartbeat`` with ``state=IDLE``. Includes the
    per-instance last-known state so the launcher can log a useful
    error before tearing the fleet down."""

    def __init__(
        self,
        message: str,
        *,
        unhealthy_instance_ids: list[str],
    ):
        super().__init__(message)
        self.unhealthy_instance_ids = unhealthy_instance_ids


# ---------------------------------------------------------------------------
# FleetInstance dataclass -- the per-instance state we persist + return
# ---------------------------------------------------------------------------


@dataclass
class FleetInstance:
    """One EC2 instance in the launcher-managed fleet.

    Serialised into ``aws_instances.json`` at every state change
    (launched / healthy / terminated) so a launcher crash leaves the
    operator a forensic trail of which instances were spun and need
    manual cleanup via the EC2 console / ``aws ec2 terminate-instances``.
    """

    instance_id: str
    az: str
    tailnet_ip: Optional[str] = None
    daemon_health: Optional[str] = None  # "IDLE" once healthy
    launched_at: Optional[str] = None  # ISO-8601 UTC
    terminated_at: Optional[str] = None  # ISO-8601 UTC
    terminate_reason: Optional[str] = None

    def heartbeat_url(self) -> Optional[str]:
        """``http://<tailnet_ip>:5198/v2/heartbeat`` once we know the IP.

        Returns ``None`` if the tailnet IP hasn't been observed yet --
        callers use this as a "is this instance ready to be polled?"
        sentinel.
        """
        if not self.tailnet_ip:
            return None
        return f"http://{self.tailnet_ip}:{WORKER_PORT}/v2/heartbeat"

    def worker_url(self) -> Optional[str]:
        """``http://<tailnet_ip>:5198`` -- the form iterate consumes
        via the shards_config worker_urls list."""
        if not self.tailnet_ip:
            return None
        return f"http://{self.tailnet_ip}:{WORKER_PORT}"


# ---------------------------------------------------------------------------
# Module helpers (overridable for tests)
# ---------------------------------------------------------------------------


def _utcnow_iso() -> str:
    """ISO-8601 UTC timestamp for the launched/terminated columns.

    Wrapped as a module function (not inlined) so tests can
    monkeypatch a deterministic clock if they need stable JSON
    diffing; today the tests just assert the field is non-empty.
    """
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _default_http_get(url: str, *, timeout: float = 5.0) -> tuple[int, dict[str, Any]]:
    """The production heartbeat-GET. Returns ``(status, parsed_json)``.

    Catches the network-error shape ``urllib.error.URLError`` and
    re-raises uniformly as ``ConnectionError`` so callers don't have
    to know about the urllib taxonomy; ``wait_for_healthy``'s poll
    loop treats any exception as "not ready yet, keep polling".
    """
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            return resp.status, json.loads(raw)
    except (urllib.error.URLError, OSError) as exc:
        raise ConnectionError(f"{url}: {exc}") from exc


def _default_tailnet_resolver(instance_id: str) -> Optional[str]:
    """Resolve an EC2 instance_id to its Tailscale 100.x address by
    running ``tailscale status`` and matching the hostname pattern
    the warm bootstrap sets (``mtg-bot-aws-warm-<instance_id>`` --
    see ``scripts/aws/user-data.worker.warm.sh`` ``tailscale up
    --hostname=...`` line).

    Why we don't use EC2 public/private IPs: those are AWS-internal
    (172.31.x / 34.x.x.x) and have no relationship to the Tailscale
    overlay address (100.x.x.x) the daemon binds on. The earlier
    pass-through default ``return instance_ip`` looked plausible
    but caused ``wait_for_healthy`` to silently poll the wrong IP
    forever and time out.

    Returns ``None`` if Tailscale isn't installed locally, if
    ``tailscale status`` errors, or if the matching hostname
    hasn't appeared yet -- ``wait_for_healthy`` reads ``None`` as
    "keep polling, daemon not yet visible on the tailnet".

    Tests inject a dict-lookup stub keyed on instance_id.
    """
    import subprocess  # local import: keep top-of-file lean
    hostname = f"mtg-bot-aws-warm-{instance_id}"
    try:
        result = subprocess.run(
            ["tailscale", "status"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        parts = line.split()
        # Tailscale status format: ``<100.x.ip>  <hostname>  <user>  ...``
        if len(parts) >= 2 and parts[1] == hostname:
            return parts[0]
    return None


# ---------------------------------------------------------------------------
# Runspec template renderer
# ---------------------------------------------------------------------------


def _render_runspec(
    template_path: Path,
    *,
    instance_type: str,
    ami_id: str,
    az: str,
    count: int,
    user_data: bytes,
    market_type: str = "spot",
) -> dict[str, Any]:
    """Read the template, substitute ``{{var}}`` placeholders, return
    the JSON dict ready for ``boto3.client('ec2').run_instances(**spec)``.

    The substitution is plain ``str.replace`` -- no Jinja runtime --
    so the template file MUST quote string placeholders ("...") and
    leave int placeholders bare. See ``scripts/aws/runspec.template.json``
    for the canonical form.

    ``user_data`` is the raw script bytes; the renderer base64-encodes
    it because EC2's ``UserData`` field expects base64 when the spec
    goes over the boto3 wire. (The aws-cli accepts raw bytes and
    encodes for you; boto3 does NOT, so we encode here.)

    Strips the leading ``_comment`` field if present so the spec is
    valid for ``run_instances`` (which rejects unknown keys).
    """
    if not template_path.is_file():
        raise FleetConfigError(
            f"runspec template not found: {template_path}",
        )
    raw = template_path.read_text(encoding="utf-8")
    user_data_b64 = base64.b64encode(user_data).decode("ascii")
    substitutions = {
        "{{instance_type}}": instance_type,
        "{{ami_id}}": ami_id,
        "{{az}}": az,
        "{{count}}": str(int(count)),
        "{{user_data_b64}}": user_data_b64,
    }
    for placeholder, value in substitutions.items():
        raw = raw.replace(placeholder, value)
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FleetConfigError(
            f"runspec template {template_path}: not valid JSON after "
            f"substitution: {exc}",
        ) from exc
    # Drop the _comment field BEFORE the un-substituted-placeholder
    # check (the comment intentionally contains literal "{{var}}"
    # placeholder names as documentation).
    spec.pop("_comment", None)
    # On-demand path: strip InstanceMarketOptions entirely. The
    # template carries the spot block as the default; popping it
    # leaves a vanilla on-demand run_instances call. Cheaper than
    # maintaining two templates and one source of truth.
    if market_type == "on_demand":
        spec.pop("InstanceMarketOptions", None)
    elif market_type != "spot":
        raise FleetConfigError(
            f"market_type must be 'spot' or 'on_demand'; got "
            f"{market_type!r}",
        )
    # Sanity: any un-substituted placeholders left in the live spec?
    # Catch the operator-facing typo case (template references a
    # placeholder we forgot to add to the substitutions dict) before
    # boto3 returns a cryptic validation error.
    serialised = json.dumps(spec)
    if "{{" in serialised:
        start = serialised.index("{{")
        end = serialised.index("}}", start) + 2
        bad = serialised[start:end]
        raise FleetConfigError(
            f"runspec template {template_path}: un-substituted "
            f"placeholder {bad!r}; known vars: "
            f"{sorted(substitutions)}",
        )
    return spec


# ---------------------------------------------------------------------------
# FleetManager: the public surface
# ---------------------------------------------------------------------------


class FleetManager:
    """Manages an ephemeral AWS spot-fleet for one launcher cycle.

    Public methods (consumed by ``mtg_bot.cli.iterate_distributed``):

    - :meth:`launch_fleet` -- spin the fleet, retrying across
      ``config.az_fallback``. Writes ``aws_instances.json`` after
      each attempt.
    - :meth:`wait_for_healthy` -- poll each instance's tailnet IP +
      ``GET /v2/heartbeat`` until state==IDLE. Returns the list of
      ``http://<ip>:5198`` URLs the launcher passes to
      ``render_shards_config``.
    - :meth:`terminate_fleet` -- ``ec2.terminate_instances`` for every
      still-running instance, idempotent across re-calls. Tagged with
      the supplied reason for cost forensics.

    Injection points (tests):

    - ``boto3_client`` -- pre-built EC2 client (e.g. a moto
      ``mock_aws``-decorated boto3 session client). When ``None``,
      the manager creates a real client on first use.
    - ``http_get`` -- function ``(url, *, timeout) -> (status, json)``
      used by ``wait_for_healthy``. Default is the urllib-based GET.
    - ``tailnet_resolver`` -- function ``(instance_public_ip) ->
      Optional[tailnet_ip]``. Default returns the public IP unchanged
      (production injects a Tailscale resolver).
    - ``sleep`` -- the poll-loop sleep function; tests pass a no-op
      to avoid real wall-clock waits.
    """

    def __init__(
        self,
        config: AwsSection,
        paths: LaunchPaths,
        *,
        boto3_client: Any = None,
        template_path: Optional[Path] = None,
        ami_id: str = DEFAULT_AMI_ID,
        http_get: Callable[..., tuple[int, dict[str, Any]]] = _default_http_get,
        tailnet_resolver: Callable[[str], Optional[str]] = _default_tailnet_resolver,
        sleep: Callable[[float], None] = time.sleep,
        utcnow: Callable[[], str] = _utcnow_iso,
    ):
        self.config = config
        self.paths = paths
        self._client = boto3_client
        self.ami_id = ami_id
        self.http_get = http_get
        self.tailnet_resolver = tailnet_resolver
        self.sleep = sleep
        self.utcnow = utcnow
        # Resolve template path: explicit > scripts/aws under the
        # repo root inferred from the launcher state's progress_root.
        if template_path is None:
            template_path = self._default_template_path()
        self.template_path = template_path
        self.user_data_path = self._default_user_data_path(template_path)
        self.instances: list[FleetInstance] = []
        self._terminated = False

    # ------------------------------------------------------------------
    # Path defaults: live under scripts/aws/ in the repo root
    # ------------------------------------------------------------------

    def _default_template_path(self) -> Path:
        """``<repo_root>/scripts/aws/runspec.template.json``.

        The repo root is inferred via this module's filesystem
        location -- the launcher always runs with the worktree as the
        cwd in production, but the module-path inference keeps tests
        portable to any working directory.
        """
        # src/mtg_bot/launcher/aws_fleet.py -> repo root is parents[3]
        return Path(__file__).resolve().parents[3] / "scripts" / "aws" / "runspec.template.json"

    def _default_user_data_path(self, template_path: Path) -> Path:
        """User-data script lives alongside the template."""
        return template_path.parent / "user-data.worker.warm.sh"

    # ------------------------------------------------------------------
    # EC2 client lazy-construction
    # ------------------------------------------------------------------

    def _ec2(self, az: Optional[str] = None) -> Any:
        """Return the EC2 client. Lazy-constructs from the AZ's region
        if no client was injected at __init__ time."""
        if self._client is not None:
            return self._client
        if az is None:
            # Try the first AZ in the fallback list; we need a region
            # to construct a real client.
            if not self.config.az_fallback:
                raise FleetConfigError(
                    "no AZ available to derive region from; pass "
                    "boto3_client= or set aws.az_fallback in config",
                )
            az = self.config.az_fallback[0]
        # Late import so tests that never go down this path don't
        # have to mock boto3.
        import boto3
        self._client = boto3.client("ec2", region_name=_region_from_az(az))
        return self._client

    # ------------------------------------------------------------------
    # _write_state: persist instances to aws_instances.json
    # ------------------------------------------------------------------

    def _write_state(self) -> None:
        """Dump ``self.instances`` to disk. Called after every state
        change (launch / health update / terminate) so a launcher
        crash leaves the operator a forensic snapshot."""
        write_aws_instances_json(
            self.paths.aws_instances_path,
            [asdict(inst) for inst in self.instances],
        )

    # ------------------------------------------------------------------
    # launch_fleet: the AZ-fallback loop
    # ------------------------------------------------------------------

    def launch_fleet(self) -> list[FleetInstance]:
        """Spin ``config.count`` spot instances; try ``az_fallback`` in
        order, fall through on capacity errors.

        Returns the list of ``FleetInstance`` records (one per
        instance). Persists ``aws_instances.json`` after each
        attempt (success and failure).

        Raises:
            FleetConfigError: missing template, bad AZ format,
              ``config.count <= 0``, ``config.az_fallback`` empty.
            FleetCapacityError: every AZ returned a retryable
              capacity error.
            botocore.exceptions.ClientError: a non-retryable error
              (auth / quota / typo) -- propagated unchanged so the
              caller sees the original AWS error code.
        """
        if self.config.count <= 0:
            raise FleetConfigError(
                f"aws.count must be positive; got {self.config.count}",
            )
        if not self.config.az_fallback:
            raise FleetConfigError(
                "aws.az_fallback is empty; supply at least one AZ "
                "for the launcher to try.",
            )
        # Read user-data once; the same payload goes into every AZ
        # attempt (only InstanceType / Placement differ).
        if not self.user_data_path.is_file():
            raise FleetConfigError(
                f"user-data script not found: {self.user_data_path}",
            )
        user_data_bytes = self.user_data_path.read_bytes()

        attempts: list[tuple[str, str]] = []
        for az in self.config.az_fallback:
            spec = _render_runspec(
                self.template_path,
                instance_type=self.config.instance_type,
                ami_id=self.ami_id,
                az=az,
                count=self.config.count,
                user_data=user_data_bytes,
                market_type=self.config.market_type,
            )
            client = self._ec2(az=az)
            try:
                logger.info(
                    "FleetManager.launch_fleet: requesting %d x %s in %s",
                    self.config.count, self.config.instance_type, az,
                )
                response = client.run_instances(**spec)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                attempts.append((az, code))
                if code in _RETRYABLE_AZ_ERRORS:
                    logger.warning(
                        "FleetManager.launch_fleet: AZ %s returned %s; "
                        "trying next AZ in fallback list", az, code,
                    )
                    # Persist the attempted-but-failed state so the
                    # operator can see we tried.
                    self._write_state()
                    continue
                # Non-retryable: propagate the original AWS error.
                logger.error(
                    "FleetManager.launch_fleet: AZ %s returned "
                    "non-retryable %s; aborting", az, code,
                )
                raise
            # Success: build FleetInstance records, persist, return.
            now = self.utcnow()
            for raw_inst in response.get("Instances", []):
                self.instances.append(
                    FleetInstance(
                        instance_id=raw_inst["InstanceId"],
                        az=raw_inst.get(
                            "Placement", {},
                        ).get("AvailabilityZone", az),
                        launched_at=now,
                    ),
                )
            self._write_state()
            logger.info(
                "FleetManager.launch_fleet: launched %d instances in %s",
                len(self.instances), az,
            )
            return list(self.instances)

        # Fell through every AZ -- raise the aggregated capacity error.
        self._write_state()
        raise FleetCapacityError(
            f"no spot capacity in any AZ "
            f"(tried {len(attempts)}: "
            f"{', '.join(f'{az}={code}' for az, code in attempts)})",
            attempts=attempts,
        )

    # ------------------------------------------------------------------
    # wait_for_healthy: tailnet-IP + heartbeat-state poll loop
    # ------------------------------------------------------------------

    def wait_for_healthy(
        self,
        instances: Optional[list[FleetInstance]] = None,
        *,
        timeout_s: float = 900.0,
    ) -> list[str]:
        """Poll each instance for tailnet IP + ``state=IDLE``.

        Returns the list of healthy worker URLs (``http://<ip>:5198``)
        in the same order as ``instances``. Mutates each instance's
        ``tailnet_ip`` and ``daemon_health`` fields as they become
        observable and rewrites ``aws_instances.json`` on every state
        change.

        Raises :class:`FleetHealthTimeoutError` if any instance fails
        to reach IDLE within ``timeout_s``. The launcher's lifecycle
        hook fires regardless so the unhealthy fleet still gets
        terminated.
        """
        targets = instances if instances is not None else self.instances
        deadline = time.monotonic() + timeout_s
        client = self._ec2()
        # Index for fast updates -- keep a mapping back to the actual
        # FleetInstance in self.instances so the asdict() snapshot
        # reflects health.
        by_id = {inst.instance_id: inst for inst in targets}
        healthy: set[str] = set()
        while time.monotonic() < deadline:
            pending_ids = [
                iid for iid in by_id if iid not in healthy
            ]
            if not pending_ids:
                break
            # 1) Resolve any still-missing tailnet IPs via EC2 +
            #    the tailnet resolver.
            try:
                resp = client.describe_instances(
                    InstanceIds=pending_ids,
                )
            except ClientError as exc:
                logger.warning(
                    "FleetManager.wait_for_healthy: describe_instances "
                    "failed (%s); will retry", exc,
                )
                self.sleep(HEARTBEAT_POLL_INTERVAL_S)
                continue
            for reservation in resp.get("Reservations", []):
                for raw in reservation.get("Instances", []):
                    inst = by_id.get(raw["InstanceId"])
                    if inst is None:
                        continue
                    # EC2 lifecycle state -- if the instance is already
                    # terminated / shutting-down, skip the heartbeat
                    # check (it'll never come up).
                    state = raw.get("State", {}).get("Name", "")
                    if state in ("terminated", "shutting-down"):
                        inst.daemon_health = f"ec2:{state}"
                        # Don't mark healthy; the timeout loop will
                        # surface this instance in the failure list.
                        continue
                    if inst.tailnet_ip is None:
                        # Resolver takes the instance_id (the warm
                        # bootstrap sets the tailnet hostname from
                        # it) and returns the matching 100.x IP, or
                        # None if not yet registered.
                        tailnet_ip = self.tailnet_resolver(
                            raw["InstanceId"],
                        )
                        if tailnet_ip:
                            inst.tailnet_ip = tailnet_ip
            # 2) For every instance with a tailnet IP, GET heartbeat.
            for iid in pending_ids:
                inst = by_id[iid]
                hb_url = inst.heartbeat_url()
                if hb_url is None:
                    continue
                try:
                    status, body = self.http_get(hb_url, timeout=5.0)
                except Exception as exc:  # noqa: BLE001 - poll-loop
                    logger.debug(
                        "FleetManager.wait_for_healthy: %s not "
                        "answering yet (%s)", hb_url, exc,
                    )
                    continue
                if status != 200:
                    continue
                state = body.get("state")
                inst.daemon_health = state
                if state == "IDLE":
                    healthy.add(iid)
            # Persist the partial-state snapshot every iteration.
            self._write_state()
            if len(healthy) == len(by_id):
                break
            self.sleep(HEARTBEAT_POLL_INTERVAL_S)
        # Final check.
        unhealthy = [iid for iid in by_id if iid not in healthy]
        if unhealthy:
            raise FleetHealthTimeoutError(
                f"wait_for_healthy timed out after {timeout_s}s; "
                f"{len(unhealthy)}/{len(by_id)} instance(s) never "
                f"reached IDLE: {unhealthy}",
                unhealthy_instance_ids=unhealthy,
            )
        # Healthy: return URLs in input order.
        urls = [by_id[inst.instance_id].worker_url() for inst in targets]
        # All should be non-None at this point (every healthy
        # instance has a tailnet IP) -- filter defensively.
        return [u for u in urls if u]

    # ------------------------------------------------------------------
    # terminate_fleet: idempotent teardown
    # ------------------------------------------------------------------

    def terminate_fleet(self, reason: str) -> None:
        """``ec2.terminate_instances`` for every still-running
        instance + update ``aws_instances.json``.

        Idempotent: a re-call after the first terminate is a no-op
        (the launcher's lifecycle hook may fire twice if the operator
        catches a SIGTERM mid-finalise; this guarantees we don't
        double-tag or double-poll).

        ``reason`` is recorded on each FleetInstance's
        ``terminate_reason`` field for cost forensics. EC2 does NOT
        accept arbitrary metadata on the terminate_instances call;
        the reason lives in our JSON snapshot only. (The launch-time
        Tags carry the cycle ID for AWS-side forensics.)
        """
        if self._terminated:
            logger.info(
                "FleetManager.terminate_fleet: already terminated; "
                "skipping re-terminate (reason=%s)", reason,
            )
            return
        live_ids = [
            inst.instance_id for inst in self.instances
            if inst.terminated_at is None
        ]
        if not live_ids:
            logger.info(
                "FleetManager.terminate_fleet: no live instances; "
                "marking terminated (reason=%s)", reason,
            )
            self._terminated = True
            return
        client = self._ec2()
        try:
            client.terminate_instances(InstanceIds=live_ids)
        except ClientError as exc:
            # Log but don't raise -- the launcher's finaliser is the
            # last-line cleanup and we'd rather over-log than leave
            # the operator unable to exit the launcher cleanly.
            logger.error(
                "FleetManager.terminate_fleet: terminate_instances "
                "failed for %s (reason=%s): %s",
                live_ids, reason, exc,
            )
        now = self.utcnow()
        for inst in self.instances:
            if inst.terminated_at is None:
                inst.terminated_at = now
                inst.terminate_reason = reason
        self._write_state()
        self._terminated = True
        logger.info(
            "FleetManager.terminate_fleet: terminated %d instance(s) "
            "(reason=%s)", len(live_ids), reason,
        )


__all__ = [
    "DEFAULT_AMI_ID",
    "FleetCapacityError",
    "FleetConfigError",
    "FleetHealthTimeoutError",
    "FleetInstance",
    "FleetManager",
    "_render_runspec",
    "_region_from_az",
]
