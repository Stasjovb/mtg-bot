"""Integration tests for the AWS-mode launcher path.

Exercises ``mtg_bot.cli.iterate_distributed._launch`` with
``cluster.local_only=false`` to verify:

- FleetManager is constructed + launch_fleet / wait_for_healthy fire.
- The rendered shards_config combines cluster URLs (master / mac) +
  AWS-fleet URLs in order.
- The iterate subprocess (stubbed) sees the per-cycle shards_config.
- The cycle_lifecycle's on_finalize hook registers the fleet
  teardown so ``terminate_fleet`` fires on test exit -- including
  on exception paths.

Uses ``moto[s3]``'s ``mock_aws`` decorator for in-process EC2 mock
plus a stub heartbeat / sleep to keep wall-clock pressure to zero.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import boto3
import pytest
from moto import mock_aws

from mtg_bot.cli import iterate_distributed as id_mod
from mtg_bot.cli.runs import db as runs_db
from mtg_bot.launcher.aws_fleet import FleetHealthTimeoutError, FleetManager


# ---------------------------------------------------------------------------
# Fixtures (paralleling the local-only test module)
# ---------------------------------------------------------------------------


@pytest.fixture
def aws_toml(tmp_path: Path) -> Path:
    p = tmp_path / "launch.toml"
    p.write_text("""
[iter]
target_iter = 22
bootstrap_version = "v5"
nodes = 200
samples = 8

[cluster]
local_only = false
master_url = "http://desktop-j05412i:5198"
mac_url = "http://greggs-macbook-pro:5198"

[aws]
count = 2
instance_type = "c7a.2xlarge"
az_fallback = ["us-east-1a", "us-east-1b"]
storage_uri = "s3://test-bucket/"
""", encoding="utf-8")
    return p


@pytest.fixture
def progress_dir(tmp_path: Path) -> Path:
    p = tmp_path / "tp"
    p.mkdir(parents=True, exist_ok=True)
    conn = runs_db.connect(p / "runs.db")
    conn.close()
    return p


@pytest.fixture(autouse=True)
def _dummy_tailscale_authkey(monkeypatch):
    """FleetManager.launch reads the worker Tailscale auth key from
    the launcher host's environment (never the TOML / repo)."""
    monkeypatch.setenv("MTG_BOT_TAILSCALE_AUTHKEY", "tskey-auth-dummy")


@pytest.fixture
def runs_db_env(progress_dir: Path, monkeypatch):
    monkeypatch.setenv(
        "MTG_BOT_RUN_DB_PATH", str(progress_dir / "runs.db"),
    )
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    yield progress_dir / "runs.db"


@pytest.fixture
def stub_heartbeat(monkeypatch):
    """Bypass the live IDLE check on the cluster URLs."""
    monkeypatch.setattr(
        id_mod, "verify_worker_idle",
        lambda url, **kwargs: {"state": "IDLE", "git_commit": "deadbee"},
    )


def _seed_iam_instance_profile(name: str = "mtg-bot-spot-worker") -> None:
    """Mirror of ``test_launcher_aws_fleet._seed_iam_instance_profile``.

    moto starts each ``@mock_aws`` test with a fresh IAM state; the
    production runspec template references an IamInstanceProfile.Name
    that moto's ``run_instances`` validates against. Without seeding,
    every aws-mode integration test raises NoSuchEntity. Call this
    inside every ``@mock_aws`` test BEFORE the first
    ``boto3.client('ec2', ...)`` -> launcher path.
    """
    trust = (
        '{"Version":"2012-10-17","Statement":[{"Effect":"Allow",'
        '"Principal":{"Service":"ec2.amazonaws.com"},'
        '"Action":"sts:AssumeRole"}]}'
    )
    iam = boto3.client("iam", region_name="us-east-1")
    iam.create_role(RoleName=name, AssumeRolePolicyDocument=trust)
    iam.create_instance_profile(InstanceProfileName=name)
    iam.add_role_to_instance_profile(
        InstanceProfileName=name, RoleName=name,
    )


def _stub_tailnet_resolver(instance_id: str) -> str:
    """Mirror of ``test_launcher_aws_fleet._stub_tailnet_resolver``;
    keeps wait_for_healthy IP assignment off the host tailscale
    daemon."""
    suffix = int(instance_id.replace("-", "")[-4:], 16) % 254 + 1
    return f"100.64.0.{suffix}"


def _spawn_stub(record: dict[str, Any], *, exit_code: int = 0):
    def _spawn(argv, env=None, cwd=None, popen_factory=None, **kwargs):
        record["argv"] = list(argv)
        record["env"] = dict(env or {})
        return exit_code
    return _spawn


def _make_aws_fleet_factory(
    *, moto_client, http_get_responses=None, sleep_noop=True,
):
    """Build a FleetManager factory that injects the moto boto3
    client + a stubbed heartbeat poller + no-op sleep.

    By default heartbeats return IDLE on first poll (fast happy path).
    Pass ``http_get_responses`` to drive non-default behavior.
    """
    if http_get_responses is None:
        def http_get(url, *, timeout=5.0):
            return 200, {"state": "IDLE"}
    else:
        http_get = http_get_responses
    sleep_fn = (lambda _: None) if sleep_noop else None

    def factory(aws_section, paths):
        return FleetManager(
            aws_section, paths,
            boto3_client=moto_client,
            http_get=http_get,
            sleep=sleep_fn or (lambda _: None),
            tailnet_resolver=_stub_tailnet_resolver,
        )

    return factory


# ---------------------------------------------------------------------------
# AWS path: launch + healthy + shards_config + terminate-on-exit
# ---------------------------------------------------------------------------


@mock_aws
def test_aws_mode_full_flow(
    aws_toml: Path, progress_dir: Path, stub_heartbeat,
    runs_db_env: Path, monkeypatch,
):
    """End-to-end AWS-mode launch: FleetManager fires, shards_config
    has cluster + AWS URLs, iterate subprocess sees the right argv,
    fleet is terminated on exit."""
    _seed_iam_instance_profile()
    moto_client = boto3.client("ec2", region_name="us-east-1")
    record: dict[str, Any] = {}
    monkeypatch.setattr(
        id_mod, "spawn_iterate_subprocess",
        _spawn_stub(record, exit_code=0),
    )

    # Capture the fleet instance so we can assert teardown.
    created: dict[str, Any] = {}
    base_factory = _make_aws_fleet_factory(moto_client=moto_client)

    def factory(*a, **kw):
        fm = base_factory(*a, **kw)
        created["fleet"] = fm
        return fm

    monkeypatch.setattr(id_mod, "FleetManager", factory)
    rc = id_mod.main([
        "--config", str(aws_toml),
        "--progress-dir", str(progress_dir),
        "--deck-pool", "data/decks.json.gz",
    ])
    assert rc == 0

    # Cycle row is completed.
    conn = runs_db.connect(progress_dir / "runs.db")
    try:
        row = runs_db.get_run(conn, "iter_022_cycle")
    finally:
        conn.close()
    assert row["run"]["status"] == "completed"

    # Argv references the per-cycle shards_config.
    argv = record["argv"]
    sc_idx = argv.index("--shards-config")
    sc_path = Path(argv[sc_idx + 1])
    assert sc_path.is_file()
    data = json.loads(sc_path.read_text(encoding="utf-8"))
    # Cluster URLs come first, then AWS URLs (in launch order).
    assert data["worker_urls"][:2] == [
        "http://desktop-j05412i:5198",
        "http://greggs-macbook-pro:5198",
    ]
    # 2 AWS workers, each http://<ip>:5198.
    aws_part = data["worker_urls"][2:]
    assert len(aws_part) == 2
    for u in aws_part:
        assert u.startswith("http://")
        assert u.endswith(":5198")

    # aws_instances.json reflects the launched + terminated fleet.
    aws_state = json.loads(
        (progress_dir / "launches" / "iter_022_cycle"
         / "aws_instances.json").read_text(encoding="utf-8"),
    )
    assert aws_state["phase"] == "filled"
    assert len(aws_state["instances"]) == 2
    for inst in aws_state["instances"]:
        assert inst["daemon_health"] == "IDLE"
        # terminate_fleet ran on lifecycle finalisation.
        assert inst["terminated_at"] is not None
        assert inst["terminate_reason"] == "launcher_finalize"

    # The FleetManager has _terminated=True.
    assert created["fleet"]._terminated is True


@mock_aws
def test_aws_mode_terminate_fires_on_iterate_failure(
    aws_toml: Path, progress_dir: Path, stub_heartbeat,
    runs_db_env: Path, monkeypatch,
):
    """If iterate exits non-zero, the fleet teardown hook still
    fires (the lifecycle's _finalize runs on every exit path)."""
    _seed_iam_instance_profile()
    moto_client = boto3.client("ec2", region_name="us-east-1")
    created: dict[str, Any] = {}
    base_factory = _make_aws_fleet_factory(moto_client=moto_client)

    def factory(*a, **kw):
        fm = base_factory(*a, **kw)
        created["fleet"] = fm
        return fm

    monkeypatch.setattr(id_mod, "FleetManager", factory)
    monkeypatch.setattr(
        id_mod, "spawn_iterate_subprocess",
        _spawn_stub({}, exit_code=7),
    )

    rc = id_mod.main([
        "--config", str(aws_toml),
        "--progress-dir", str(progress_dir),
        "--deck-pool", "data/decks.json.gz",
    ])
    assert rc == 7
    # Fleet still terminated.
    assert created["fleet"]._terminated is True
    for inst in created["fleet"].instances:
        assert inst.terminated_at is not None


@mock_aws
def test_aws_mode_terminate_fires_on_spawn_exception(
    aws_toml: Path, progress_dir: Path, stub_heartbeat,
    runs_db_env: Path, monkeypatch,
):
    """If the iterate subprocess raises (rare; usually iterate's
    exit code is the signal), the lifecycle's exception path still
    fires the fleet teardown hook."""
    _seed_iam_instance_profile()
    moto_client = boto3.client("ec2", region_name="us-east-1")
    created: dict[str, Any] = {}
    base_factory = _make_aws_fleet_factory(moto_client=moto_client)

    def factory(*a, **kw):
        fm = base_factory(*a, **kw)
        created["fleet"] = fm
        return fm

    monkeypatch.setattr(id_mod, "FleetManager", factory)

    def boom(*a, **kw):
        raise RuntimeError("simulated spawn failure")

    monkeypatch.setattr(id_mod, "spawn_iterate_subprocess", boom)

    with pytest.raises(RuntimeError, match="simulated"):
        id_mod.main([
            "--config", str(aws_toml),
            "--progress-dir", str(progress_dir),
            "--deck-pool", "data/decks.json.gz",
        ])
    # Fleet was torn down despite the body exception.
    assert created["fleet"]._terminated is True


@mock_aws
def test_aws_mode_dry_run_does_not_touch_ec2(
    aws_toml: Path, progress_dir: Path, runs_db_env: Path,
    monkeypatch, capsys,
):
    """--dry-run in AWS mode prints the resolved plan but must NOT
    call run_instances / terminate_instances. The factory should
    not even be invoked beyond construction (no launch_fleet)."""
    # If the factory tried to launch_fleet, our MagicMock client would
    # see the call. We assert NO call.
    bogus_client = MagicMock()

    factory_calls: list[Any] = []

    def factory(aws_section, paths):
        factory_calls.append((aws_section, paths))
        return FleetManager(
            aws_section, paths,
            boto3_client=bogus_client,
            sleep=lambda _: None,
            http_get=lambda url, *, timeout: (200, {"state": "IDLE"}),
            tailnet_resolver=_stub_tailnet_resolver,
        )

    monkeypatch.setattr(id_mod, "FleetManager", factory)

    rc = id_mod.main([
        "--config", str(aws_toml),
        "--progress-dir", str(progress_dir),
        "--deck-pool", "data/decks.json.gz",
        "--dry-run",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "mode=aws" in out
    assert "aws_count=2" in out
    # No EC2 calls.
    bogus_client.run_instances.assert_not_called()
    bogus_client.terminate_instances.assert_not_called()


@mock_aws
def test_aws_mode_az_fallback_succeeds(
    aws_toml: Path, progress_dir: Path, stub_heartbeat,
    runs_db_env: Path, monkeypatch,
):
    """The launcher tolerates capacity errors that get retried via
    the FleetManager's AZ fallback -- the end-to-end run still
    succeeds."""
    from botocore.exceptions import ClientError
    _seed_iam_instance_profile()
    real_client = boto3.client("ec2", region_name="us-east-1")

    class _FailFirstAZ:
        def __init__(self, real):
            self._real = real
            self.run_calls = 0

        def run_instances(self, **kw):
            self.run_calls += 1
            az = kw.get("Placement", {}).get("AvailabilityZone", "")
            if az == "us-east-1a":
                raise ClientError(
                    {"Error": {"Code": "InsufficientInstanceCapacity",
                               "Message": "1a tight"}},
                    "RunInstances",
                )
            return self._real.run_instances(**kw)

        def terminate_instances(self, **kw):
            return self._real.terminate_instances(**kw)

        def describe_instances(self, **kw):
            return self._real.describe_instances(**kw)

    wrapped = _FailFirstAZ(real_client)

    def factory(aws_section, paths):
        return FleetManager(
            aws_section, paths,
            boto3_client=wrapped,
            http_get=lambda url, *, timeout: (200, {"state": "IDLE"}),
            sleep=lambda _: None,
            tailnet_resolver=_stub_tailnet_resolver,
        )

    monkeypatch.setattr(id_mod, "FleetManager", factory)
    record: dict[str, Any] = {}
    monkeypatch.setattr(
        id_mod, "spawn_iterate_subprocess",
        _spawn_stub(record, exit_code=0),
    )

    rc = id_mod.main([
        "--config", str(aws_toml),
        "--progress-dir", str(progress_dir),
        "--deck-pool", "data/decks.json.gz",
    ])
    assert rc == 0
    # Two run_instances attempts: 1a failed, 1b succeeded.
    assert wrapped.run_calls == 2


@mock_aws
def test_aws_mode_queue_url_explicit_required_if_no_cluster(
    tmp_path: Path, progress_dir: Path, runs_db_env: Path,
    monkeypatch,
):
    """AWS-only mode (no cluster URLs) needs --queue-url because
    there's no canonical coordinator host to derive from."""
    toml = tmp_path / "launch.toml"
    toml.write_text("""
[iter]
target_iter = 30

[cluster]
local_only = false
# No master / mac / win10 URLs -- AWS-only fleet.

[aws]
count = 1
az_fallback = ["us-east-1a"]
storage_uri = "null://"
""", encoding="utf-8")
    _seed_iam_instance_profile()
    moto_client = boto3.client("ec2", region_name="us-east-1")

    def factory(aws_section, paths):
        return FleetManager(
            aws_section, paths,
            boto3_client=moto_client,
            http_get=lambda url, *, timeout: (200, {"state": "IDLE"}),
            sleep=lambda _: None,
            tailnet_resolver=_stub_tailnet_resolver,
        )

    monkeypatch.setattr(id_mod, "FleetManager", factory)
    monkeypatch.setattr(
        id_mod, "spawn_iterate_subprocess",
        _spawn_stub({}, exit_code=0),
    )

    # Without --queue-url: raises.
    with pytest.raises(Exception, match="queue-url"):
        id_mod._launch(
            id_mod.load_config(toml),
            progress_dir=progress_dir,
            deck_pool=None,
            queue_url=None,
            force_resume_from_failed=False,
            dry_run=False,
            skip_worker_verify=True,
            iterate_passthrough=[],
        )


@mock_aws
def test_aws_mode_passes_queue_url_explicit(
    tmp_path: Path, progress_dir: Path, runs_db_env: Path,
    monkeypatch,
):
    """AWS-only mode with explicit --queue-url works end-to-end."""
    toml = tmp_path / "launch.toml"
    toml.write_text("""
[iter]
target_iter = 31

[cluster]
local_only = false

[aws]
count = 1
az_fallback = ["us-east-1a"]
storage_uri = "null://"
""", encoding="utf-8")
    _seed_iam_instance_profile()
    moto_client = boto3.client("ec2", region_name="us-east-1")

    def factory(aws_section, paths):
        return FleetManager(
            aws_section, paths,
            boto3_client=moto_client,
            http_get=lambda url, *, timeout: (200, {"state": "IDLE"}),
            sleep=lambda _: None,
            tailnet_resolver=_stub_tailnet_resolver,
        )

    monkeypatch.setattr(id_mod, "FleetManager", factory)
    record: dict[str, Any] = {}
    monkeypatch.setattr(
        id_mod, "spawn_iterate_subprocess",
        _spawn_stub(record, exit_code=0),
    )

    rc = id_mod.main([
        "--config", str(toml),
        "--progress-dir", str(progress_dir),
        "--deck-pool", "data/decks.json.gz",
        "--queue-url", "http://desktop-j05412i:5099",
        "--skip-worker-verify",
    ])
    assert rc == 0
    # The argv carries the explicit queue_url.
    assert "--queue-url" in record["argv"]
    qi = record["argv"].index("--queue-url")
    assert record["argv"][qi + 1] == "http://desktop-j05412i:5099"


@mock_aws
@pytest.mark.parametrize(
    "exc",
    [FleetHealthTimeoutError("boot never IDLE", unhealthy_instance_ids=["i-x"]),
     KeyboardInterrupt()],
    ids=["health_timeout", "ctrl_c"],
)
def test_aws_mode_terminates_fleet_when_wait_for_healthy_fails(
    aws_toml: Path, progress_dir: Path, stub_heartbeat,
    runs_db_env: Path, monkeypatch, exc,
):
    """Regression (2026-09-27): the fleet-teardown finalize hook is
    only registered once the cycle lifecycle opens, which happens
    AFTER wait_for_healthy. A health timeout (or Ctrl-C) during the
    boot wait therefore leaked two running spot instances. The
    launcher must terminate the fleet itself before propagating."""
    _seed_iam_instance_profile()
    moto_client = boto3.client("ec2", region_name="us-east-1")
    created: dict[str, Any] = {}
    base_factory = _make_aws_fleet_factory(moto_client=moto_client)

    def factory(*a, **kw):
        fm = base_factory(*a, **kw)

        def _fail(instances=None, **_kw):
            raise exc
        fm.wait_for_healthy = _fail
        created["fleet"] = fm
        return fm

    monkeypatch.setattr(id_mod, "FleetManager", factory)
    spawn_record: dict[str, Any] = {}
    monkeypatch.setattr(
        id_mod, "spawn_iterate_subprocess", _spawn_stub(spawn_record),
    )

    with pytest.raises(type(exc)):
        id_mod.main([
            "--config", str(aws_toml),
            "--progress-dir", str(progress_dir),
            "--deck-pool", "data/decks.json.gz",
        ])
    fm = created["fleet"]
    assert fm._terminated is True
    assert fm.instances, "launch_fleet should have created instances"
    for inst in fm.instances:
        assert inst.terminated_at is not None
    # EC2 agrees: nothing left running.
    states = {
        i["State"]["Name"]
        for r in moto_client.describe_instances()["Reservations"]
        for i in r["Instances"]
    }
    assert "running" not in states and "pending" not in states
    # iterate was never spawned.
    assert "argv" not in spawn_record
