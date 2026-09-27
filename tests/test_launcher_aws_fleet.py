"""Tests for the AWS spot-fleet manager.

Built on ``moto[s3]>=5.0``'s ``mock_aws`` decorator (which also covers
EC2). The pattern is: enter ``mock_aws()``, construct a real
``boto3.client('ec2', region_name='us-east-1')`` -- moto intercepts
the API calls at the botocore layer -- inject that client into the
:class:`FleetManager`, and drive ``launch_fleet`` /
``wait_for_healthy`` / ``terminate_fleet`` end-to-end without
touching real AWS.

The capacity-fallback tests can't rely on moto naturally raising
``InsufficientInstanceCapacity`` (moto's EC2 mock accepts every
``run_instances`` call), so those tests wrap the client with a
side-effect-on-call shim that raises ``ClientError`` for the first
AZ(s) before delegating to the real moto client.
"""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any, Optional
from unittest.mock import MagicMock

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from mtg_bot.launcher.aws_fleet import (
    DEFAULT_AMI_ID,
    FleetCapacityError,
    FleetConfigError,
    FleetHealthTimeoutError,
    FleetInstance,
    FleetManager,
    _build_env_injection,
    _region_from_az,
    _render_runspec,
)
from mtg_bot.launcher.config import AwsSection
from mtg_bot.launcher.state import LaunchPaths


@pytest.fixture(autouse=True)
def _dummy_tailscale_authkey(monkeypatch):
    """FleetManager.launch reads the Tailscale auth key from the
    launcher host's environment (never the TOML / repo). Give every
    test in this module a dummy so launch paths render user-data."""
    monkeypatch.setenv("MTG_BOT_TAILSCALE_AUTHKEY", "tskey-auth-dummy")


def _stub_tailnet_resolver(instance_id: str) -> str:
    """Test-only resolver stub: maps each EC2 instance_id to a
    deterministic 100.x.x.x IP. The production default at
    ``aws_fleet._default_tailnet_resolver`` shells out to
    ``tailscale status`` and matches hostname
    ``mtg-bot-aws-warm-<instance_id>``; tests inject this stub so
    ``wait_for_healthy`` assigns a non-None ``tailnet_ip`` without
    depending on the host machine's tailscale daemon or real
    instance registrations.
    """
    suffix = int(instance_id.replace("-", "")[-4:], 16) % 254 + 1
    return f"100.64.0.{suffix}"


def _seed_iam_instance_profile(name: str = "mtg-bot-spot-worker") -> None:
    """Create the IAM role + instance profile that the production
    runspec template references. moto starts each ``@mock_aws`` test
    with a fresh IAM state; without seeding, ``ec2.run_instances``
    raises NoSuchEntity on the IamInstanceProfile.Name validation.

    The role + profile names match the production IAM (provisioned
    via ``aws iam create-role mtg-bot-spot-worker`` on the live
    account); tests that exercise launch_fleet via moto need the
    same name so the template's hardcoded ``IamInstanceProfile.Name``
    resolves.
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


# ---------------------------------------------------------------------------
# Fixtures: shared template + paths
# ---------------------------------------------------------------------------


@pytest.fixture
def template_path() -> Path:
    """The canonical runspec template under scripts/aws/."""
    return (
        Path(__file__).resolve().parents[1]
        / "scripts" / "aws" / "runspec.template.json"
    )


@pytest.fixture
def user_data_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "scripts" / "aws" / "user-data.worker.warm.sh"
    )


@pytest.fixture
def paths(tmp_path: Path) -> LaunchPaths:
    return LaunchPaths.for_cycle(
        tmp_path / "tp", "iter_999_cycle",
    ).ensure()


def _make_config(
    *, count: int = 3,
    az_fallback: Optional[list[str]] = None,
    instance_type: str = "c7a.2xlarge",
) -> AwsSection:
    return AwsSection(
        count=count,
        instance_type=instance_type,
        az_fallback=list(
            az_fallback if az_fallback is not None else ["us-east-1a"],
        ),
        storage_uri="s3://test-bucket/",
    )


# ---------------------------------------------------------------------------
# _render_runspec
# ---------------------------------------------------------------------------


def test_render_runspec_substitutes_all_vars(
    template_path: Path, tmp_path: Path,
):
    user_data = b"#!/bin/bash\necho hi\n"
    spec = _render_runspec(
        template_path,
        instance_type="c7i.4xlarge",
        ami_id="ami-12345",
        az="us-east-2b",
        count=5,
        user_data=user_data,
    )
    assert spec["InstanceType"] == "c7i.4xlarge"
    assert spec["ImageId"] == "ami-12345"
    assert spec["MinCount"] == 5
    assert spec["MaxCount"] == 5
    assert spec["Placement"]["AvailabilityZone"] == "us-east-2b"
    # UserData is base64-encoded.
    assert spec["UserData"] == base64.b64encode(user_data).decode("ascii")
    # _comment was stripped.
    assert "_comment" not in spec


def test_render_runspec_missing_template_raises(tmp_path: Path):
    with pytest.raises(FleetConfigError, match="not found"):
        _render_runspec(
            tmp_path / "nope.json",
            instance_type="t", ami_id="a", az="us-east-1a",
            count=1, user_data=b"",
        )


def test_render_runspec_default_market_type_is_spot(
    template_path: Path,
):
    """Default market_type='spot' keeps the InstanceMarketOptions
    block from the template so AWS treats this as a spot request."""
    spec = _render_runspec(
        template_path,
        instance_type="c7a.2xlarge", ami_id="ami-x", az="us-east-1a",
        count=1, user_data=b"#!/bin/bash\n",
    )
    assert "InstanceMarketOptions" in spec
    assert spec["InstanceMarketOptions"]["MarketType"] == "spot"


def test_render_runspec_on_demand_strips_spot_options(
    template_path: Path,
):
    """market_type='on_demand' pops InstanceMarketOptions so the
    same template renders an on-demand run_instances spec without
    needing a second template file."""
    spec = _render_runspec(
        template_path,
        instance_type="c7a.2xlarge", ami_id="ami-x", az="us-east-1a",
        count=1, user_data=b"#!/bin/bash\n",
        market_type="on_demand",
    )
    assert "InstanceMarketOptions" not in spec
    # Everything else (InstanceType, AMI, AZ, count, UserData, IAM
    # profile) is still rendered identically -- on-demand only flips
    # the market_type bit.
    assert spec["InstanceType"] == "c7a.2xlarge"
    assert spec["ImageId"] == "ami-x"
    assert spec["Placement"]["AvailabilityZone"] == "us-east-1a"


def test_render_runspec_invalid_market_type_raises(template_path: Path):
    with pytest.raises(FleetConfigError, match="market_type"):
        _render_runspec(
            template_path,
            instance_type="c7a.2xlarge", ami_id="ami-x", az="us-east-1a",
            count=1, user_data=b"#!/bin/bash\n",
            market_type="reserved",
        )


def test_render_runspec_un_substituted_placeholder_raises(tmp_path: Path):
    """If the template has a typo (placeholder we don't substitute),
    the renderer must fail loudly before sending the spec to AWS."""
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"InstanceType": "{{instance_type}}", '
        '"Bogus": "{{not_a_real_var}}", "ImageId": "{{ami_id}}", '
        '"Placement": {"AvailabilityZone": "{{az}}"}, '
        '"MinCount": {{count}}, "MaxCount": {{count}}, '
        '"UserData": "{{user_data_b64}}"}',
        encoding="utf-8",
    )
    with pytest.raises(FleetConfigError, match="un-substituted"):
        _render_runspec(
            bad,
            instance_type="t", ami_id="a", az="us-east-1a",
            count=1, user_data=b"",
        )


def test_render_runspec_invalid_json_after_subst_raises(tmp_path: Path):
    """If a substituted value breaks JSON validity (shouldn't happen
    with our template, but defensive), the renderer must catch it."""
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{{not_json{{instance_type}}}}',
        encoding="utf-8",
    )
    with pytest.raises(FleetConfigError):
        _render_runspec(
            bad,
            instance_type="t", ami_id="a", az="us-east-1a",
            count=1, user_data=b"",
        )


# ---------------------------------------------------------------------------
# _build_env_injection + env-injection wiring in _render_runspec
# ---------------------------------------------------------------------------


def test_build_env_injection_emits_export_for_s3_uri():
    block = _build_env_injection(
        "s3://mtg-bot-artifacts-630589799985/launcher/", "tskey-auth-dummy",
    )
    lines = block.splitlines()
    # shlex.quote keeps URIs without special chars unquoted, but s3://
    # has no shell metachars so the URI appears verbatim.
    assert lines[0] == (
        "export MTG_BOT_ARTIFACT_STORAGE_URI="
        "s3://mtg-bot-artifacts-630589799985/launcher/"
    )
    assert lines[1] == "export MTG_BOT_TAILSCALE_AUTHKEY=tskey-auth-dummy"


def test_build_env_injection_strips_whitespace_around_authkey():
    """Regression (2026-09-27): the key file on the launcher host was
    CRLF-terminated and the s2 scripts only stripped LF, so the worker
    ran ``tailscale up --authkey=tskey-...<CR>`` and the control plane
    rejected it ("invalid key"). The renderer now strips."""
    block = _build_env_injection("null://", "tskey-auth-abc123\r\n")
    assert "export MTG_BOT_TAILSCALE_AUTHKEY=tskey-auth-abc123" in block
    assert "\r" not in block
    # Whitespace-only still counts as missing.
    with pytest.raises(FleetConfigError):
        _build_env_injection("null://", " \r\n")

def test_build_env_injection_quotes_shell_metachars():
    """Defensive: storage_uri values with spaces / dollar signs / etc
    must survive intact through shell parsing on the worker."""
    line = _build_env_injection(
        "file:///tmp/with spaces/$weird", "tskey-auth-dummy",
    ).splitlines()[0]
    # shlex.quote wraps in single quotes for any non-trivial input.
    assert "MTG_BOT_ARTIFACT_STORAGE_URI=" in line
    # Round-trip via shlex to confirm the worker would see the
    # original value back.
    import shlex as _shlex
    after_eq = line.split("=", 1)[1]
    parsed = _shlex.split(f"x={after_eq}")[0].split("=", 1)[1]
    assert parsed == "file:///tmp/with spaces/$weird"


def test_build_env_injection_null_uri_is_accepted():
    """``null://`` is a valid storage_uri for dev / local-only AWS
    runs that exercise the launcher path without burning S3 puts."""
    line = _build_env_injection("null://", "tskey-auth-dummy").splitlines()[0]
    assert line == "export MTG_BOT_ARTIFACT_STORAGE_URI=null://"


def test_build_env_injection_empty_raises():
    """A missing aws.storage_uri fails at config-time, NOT at
    daemon-boot-time -- the launcher's whole point is structurally
    enforced wiring, so a TOML missing storage_uri shouldn't get
    far enough to spin spot capacity."""
    with pytest.raises(FleetConfigError, match="aws.storage_uri must be set"):
        _build_env_injection(None, "tskey-auth-dummy")
    with pytest.raises(FleetConfigError, match="aws.storage_uri must be set"):
        _build_env_injection("", "tskey-auth-dummy")


def test_build_env_injection_missing_tailscale_key_raises():
    """The Tailscale auth key comes from the launcher host's
    environment, never the TOML or the repo. Missing key fails at
    config-time so no spot capacity is spun up for workers that could
    never join the tailnet."""
    with pytest.raises(FleetConfigError, match="MTG_BOT_TAILSCALE_AUTHKEY"):
        _build_env_injection("null://", None)
    with pytest.raises(FleetConfigError, match="MTG_BOT_TAILSCALE_AUTHKEY"):
        _build_env_injection("null://", "")


def test_user_data_script_has_no_literal_tailscale_key(user_data_path: Path):
    """Regression guard: a literal ``tskey-auth-...`` was committed in
    the bootstrap script (commit 11861b8a); it must only ever reference
    the injected ``MTG_BOT_TAILSCALE_AUTHKEY`` env var."""
    text = user_data_path.read_text(encoding="utf-8")
    assert "tskey-auth-" not in text
    assert "${MTG_BOT_TAILSCALE_AUTHKEY:?" in text


def test_user_data_script_parses_under_bash(user_data_path: Path):
    """Regression (2026-09-27): commit 44f43c34 put an apostrophe
    ("host's") inside the ``${MTG_BOT_TAILSCALE_AUTHKEY:?...}`` message.
    Bash reads a bare ``'`` inside a parameter expansion as an opened
    quote, so the script died with "unexpected EOF while looking for
    matching `}'" the moment cloud-init reached that line -- both
    validation instances never joined the tailnet. Two guards: the
    expansion messages stay apostrophe-free (always), and ``bash -n``
    accepts the whole script (when a bash is on PATH)."""
    import re
    import shutil
    import subprocess

    text = user_data_path.read_text(encoding="utf-8")
    for m in re.finditer(r"\$\{[A-Z_]+:\?([^}]*)\}", text):
        assert "'" not in m.group(1), (
            f"apostrophe inside ${{VAR:?...}} message: {m.group(0)!r}"
        )
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on PATH")
    proc = subprocess.run(
        [bash, "-n", str(user_data_path)],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr


def test_render_runspec_injects_env_into_user_data(
    template_path: Path, user_data_path: Path,
):
    """The real user-data script has the {{LAUNCHER_ENV_INJECTION}}
    placeholder; rendering with a non-empty env_injection must
    replace the placeholder line with the export(s) BEFORE
    base64-encoding (so the worker actually sees the exports)."""
    user_data = user_data_path.read_bytes()
    assert b"{{LAUNCHER_ENV_INJECTION}}" in user_data, (
        "fixture sanity: real user-data must carry the placeholder"
    )
    env = "export MTG_BOT_ARTIFACT_STORAGE_URI=s3://test-bucket/p/"
    spec = _render_runspec(
        template_path,
        instance_type="c7a.2xlarge", ami_id="ami-x", az="us-east-1a",
        count=1, user_data=user_data,
        env_injection=env,
    )
    # base64-decode and confirm the export landed, AND the
    # placeholder line is gone.
    decoded = base64.b64decode(spec["UserData"]).decode("utf-8")
    assert env in decoded
    assert "{{LAUNCHER_ENV_INJECTION}}" not in decoded


def test_render_runspec_strict_when_env_injection_supplied_but_placeholder_missing(
    template_path: Path,
):
    """A bare-bones user-data without the placeholder + non-empty
    env_injection is a wiring bug: the launcher would silently fail
    to set MTG_BOT_ARTIFACT_STORAGE_URI on the worker. Fail loud."""
    with pytest.raises(FleetConfigError, match="LAUNCHER_ENV_INJECTION"):
        _render_runspec(
            template_path,
            instance_type="c7a.2xlarge", ami_id="ami-x", az="us-east-1a",
            count=1, user_data=b"#!/bin/bash\necho hi\n",
            env_injection="export MTG_BOT_ARTIFACT_STORAGE_URI=null://",
        )


def test_render_runspec_empty_env_injection_is_back_compat(
    template_path: Path,
):
    """Existing tests pass user_data without the placeholder and no
    env_injection arg. That path must keep working (no injection
    requested -> no placeholder requirement)."""
    spec = _render_runspec(
        template_path,
        instance_type="c7a.2xlarge", ami_id="ami-x", az="us-east-1a",
        count=1, user_data=b"#!/bin/bash\necho hi\n",
    )
    decoded = base64.b64decode(spec["UserData"]).decode("utf-8")
    assert decoded == "#!/bin/bash\necho hi\n"


# ---------------------------------------------------------------------------
# _region_from_az
# ---------------------------------------------------------------------------


def test_region_from_az_basic():
    assert _region_from_az("us-east-1a") == "us-east-1"
    assert _region_from_az("eu-west-2c") == "eu-west-2"


def test_region_from_az_bad_input_raises():
    with pytest.raises(FleetConfigError, match="does not look like"):
        _region_from_az("us-east-1")  # no zone suffix
    with pytest.raises(FleetConfigError):
        _region_from_az("")


# ---------------------------------------------------------------------------
# launch_fleet: happy path (single AZ succeeds first try)
# ---------------------------------------------------------------------------


@mock_aws
def test_launch_fleet_happy_single_az(
    paths: LaunchPaths, template_path: Path, user_data_path: Path,
):
    client = boto3.client("ec2", region_name="us-east-1")
    _seed_iam_instance_profile()
    config = _make_config(count=3, az_fallback=["us-east-1a"])
    fm = FleetManager(
        config, paths,
        boto3_client=client,
        template_path=template_path,
    )
    instances = fm.launch_fleet()
    assert len(instances) == 3
    assert all(inst.instance_id.startswith("i-") for inst in instances)
    assert all(inst.az == "us-east-1a" for inst in instances)
    assert all(inst.launched_at for inst in instances)
    # aws_instances.json is populated.
    data = json.loads(paths.aws_instances_path.read_text(encoding="utf-8"))
    assert data["phase"] == "filled"
    assert len(data["instances"]) == 3
    assert all(rec["instance_id"].startswith("i-") for rec in data["instances"])


# ---------------------------------------------------------------------------
# launch_fleet: AZ fallback
# ---------------------------------------------------------------------------


class _AZFallbackClient:
    """Wraps a real moto EC2 client to raise
    ``InsufficientInstanceCapacity`` for the first N AZs before
    delegating to the underlying client."""

    def __init__(self, real_client, failing_azs: list[str]):
        self._real = real_client
        self._failing_azs = set(failing_azs)
        self.run_instances_calls: list[dict[str, Any]] = []

    def run_instances(self, **kwargs):
        self.run_instances_calls.append(kwargs)
        placement = kwargs.get("Placement", {})
        az = placement.get("AvailabilityZone")
        if az in self._failing_azs:
            err = {
                "Error": {
                    "Code": "InsufficientInstanceCapacity",
                    "Message": f"no capacity in {az}",
                },
            }
            raise ClientError(err, "RunInstances")
        return self._real.run_instances(**kwargs)

    def terminate_instances(self, **kwargs):
        return self._real.terminate_instances(**kwargs)

    def describe_instances(self, **kwargs):
        return self._real.describe_instances(**kwargs)


@mock_aws
def test_launch_fleet_az_fallback_second_az_succeeds(
    paths: LaunchPaths, template_path: Path,
):
    real_client = boto3.client("ec2", region_name="us-east-1")
    _seed_iam_instance_profile()
    wrapped = _AZFallbackClient(real_client, failing_azs=["us-east-1a"])
    config = _make_config(
        count=2,
        az_fallback=["us-east-1a", "us-east-1b", "us-east-1c"],
    )
    fm = FleetManager(
        config, paths,
        boto3_client=wrapped,
        template_path=template_path,
    )
    instances = fm.launch_fleet()
    # First AZ tried (failed), second AZ tried (succeeded).
    assert len(wrapped.run_instances_calls) == 2
    azs_attempted = [
        call["Placement"]["AvailabilityZone"]
        for call in wrapped.run_instances_calls
    ]
    assert azs_attempted == ["us-east-1a", "us-east-1b"]
    # Returned instances live in us-east-1b.
    assert len(instances) == 2
    for inst in instances:
        assert inst.az == "us-east-1b"


@mock_aws
def test_launch_fleet_all_azs_exhausted_raises(
    paths: LaunchPaths, template_path: Path,
):
    real_client = boto3.client("ec2", region_name="us-east-1")
    _seed_iam_instance_profile()
    wrapped = _AZFallbackClient(
        real_client, failing_azs=["us-east-1a", "us-east-1b", "us-east-1c"],
    )
    config = _make_config(
        count=2,
        az_fallback=["us-east-1a", "us-east-1b", "us-east-1c"],
    )
    fm = FleetManager(
        config, paths,
        boto3_client=wrapped,
        template_path=template_path,
    )
    with pytest.raises(FleetCapacityError) as exc_info:
        fm.launch_fleet()
    err = exc_info.value
    assert len(err.attempts) == 3
    assert {az for az, _ in err.attempts} == {
        "us-east-1a", "us-east-1b", "us-east-1c",
    }
    assert all(code == "InsufficientInstanceCapacity"
               for _, code in err.attempts)
    # State file reflects the no-instance final state.
    data = json.loads(paths.aws_instances_path.read_text(encoding="utf-8"))
    assert data["instances"] == []


# ---------------------------------------------------------------------------
# launch_fleet: non-retryable errors propagate
# ---------------------------------------------------------------------------


class _AuthFailingClient:
    """Always raises ``UnauthorizedOperation`` (non-retryable)."""

    def run_instances(self, **kwargs):
        raise ClientError(
            {"Error": {"Code": "UnauthorizedOperation",
                       "Message": "bad creds"}},
            "RunInstances",
        )


def test_launch_fleet_non_retryable_error_propagates(
    paths: LaunchPaths, template_path: Path,
):
    config = _make_config(az_fallback=["us-east-1a"])
    fm = FleetManager(
        config, paths,
        boto3_client=_AuthFailingClient(),
        template_path=template_path,
    )
    with pytest.raises(ClientError) as exc_info:
        fm.launch_fleet()
    assert (
        exc_info.value.response["Error"]["Code"] == "UnauthorizedOperation"
    )


def test_launch_fleet_count_zero_raises(
    paths: LaunchPaths, template_path: Path,
):
    config = _make_config(count=0, az_fallback=["us-east-1a"])
    fm = FleetManager(
        config, paths,
        boto3_client=MagicMock(),
        template_path=template_path,
    )
    with pytest.raises(FleetConfigError, match="aws.count"):
        fm.launch_fleet()


def test_launch_fleet_empty_az_fallback_raises(
    paths: LaunchPaths, template_path: Path,
):
    config = _make_config(az_fallback=[])
    fm = FleetManager(
        config, paths,
        boto3_client=MagicMock(),
        template_path=template_path,
    )
    with pytest.raises(FleetConfigError, match="az_fallback is empty"):
        fm.launch_fleet()


def test_launch_fleet_missing_user_data_raises(
    paths: LaunchPaths, template_path: Path, tmp_path: Path,
):
    """When the user-data script is missing alongside the template,
    raise before any AWS call."""
    # Point template at a tmp template whose neighbour user-data
    # script doesn't exist.
    alt_template = tmp_path / "runspec.template.json"
    alt_template.write_text(
        template_path.read_text(encoding="utf-8"), encoding="utf-8",
    )
    # NO user-data.worker.warm.sh in tmp_path.
    config = _make_config(az_fallback=["us-east-1a"])
    fm = FleetManager(
        config, paths,
        boto3_client=MagicMock(),
        template_path=alt_template,
    )
    with pytest.raises(FleetConfigError, match="user-data script"):
        fm.launch_fleet()


# ---------------------------------------------------------------------------
# wait_for_healthy
# ---------------------------------------------------------------------------


@mock_aws
def test_wait_for_healthy_happy_path(
    paths: LaunchPaths, template_path: Path,
):
    client = boto3.client("ec2", region_name="us-east-1")
    _seed_iam_instance_profile()
    config = _make_config(count=2, az_fallback=["us-east-1a"])
    # Heartbeat stub: every URL returns IDLE.
    def http_get(url, *, timeout=5.0):
        return 200, {"state": "IDLE"}

    fm = FleetManager(
        config, paths,
        boto3_client=client,
        template_path=template_path,
        http_get=http_get,
        sleep=lambda _: None,  # no real waits
        tailnet_resolver=_stub_tailnet_resolver,
    )
    instances = fm.launch_fleet()
    urls = fm.wait_for_healthy(instances, timeout_s=10.0)
    assert len(urls) == 2
    for u in urls:
        assert u.startswith("http://")
        assert u.endswith(":5198")
    # Per-instance health snapshot recorded.
    for inst in fm.instances:
        assert inst.tailnet_ip is not None
        assert inst.daemon_health == "IDLE"
    data = json.loads(paths.aws_instances_path.read_text(encoding="utf-8"))
    assert all(rec["daemon_health"] == "IDLE" for rec in data["instances"])


@mock_aws
def test_wait_for_healthy_timeout(
    paths: LaunchPaths, template_path: Path,
):
    """An instance whose heartbeat never reaches IDLE raises after
    timeout_s with the bad instance IDs in the exception."""
    client = boto3.client("ec2", region_name="us-east-1")
    _seed_iam_instance_profile()
    config = _make_config(count=2, az_fallback=["us-east-1a"])
    # All heartbeats time out (raise).
    def never_healthy(url, *, timeout=5.0):
        raise ConnectionError("never up")

    # Drive monotonic forward fast: patch time.monotonic via the
    # module's reference indirectly by giving sleep() side effects.
    fake_time = {"now": 0.0}

    def fake_sleep(s):
        fake_time["now"] += s

    # Patch time.monotonic so the timeout actually fires.
    import mtg_bot.launcher.aws_fleet as aws_fleet_mod
    real_monotonic = aws_fleet_mod.time.monotonic

    def fake_monotonic():
        return fake_time["now"]

    aws_fleet_mod.time.monotonic = fake_monotonic
    try:
        fm = FleetManager(
            config, paths,
            boto3_client=client,
            template_path=template_path,
            http_get=never_healthy,
            sleep=fake_sleep,
            tailnet_resolver=_stub_tailnet_resolver,
        )
        instances = fm.launch_fleet()
        with pytest.raises(FleetHealthTimeoutError) as exc_info:
            fm.wait_for_healthy(instances, timeout_s=10.0)
        err = exc_info.value
        assert len(err.unhealthy_instance_ids) == 2
    finally:
        aws_fleet_mod.time.monotonic = real_monotonic


@mock_aws
def test_wait_for_healthy_unrecognized_state_keeps_polling(
    paths: LaunchPaths, template_path: Path,
):
    """An instance returning non-IDLE state (e.g. BUSY) doesn't count
    as healthy; the loop keeps polling until either IDLE or timeout."""
    client = boto3.client("ec2", region_name="us-east-1")
    _seed_iam_instance_profile()
    config = _make_config(count=1, az_fallback=["us-east-1a"])
    call_count = {"n": 0}

    def http_get(url, *, timeout=5.0):
        call_count["n"] += 1
        if call_count["n"] < 3:
            return 200, {"state": "BUSY"}
        return 200, {"state": "IDLE"}

    fm = FleetManager(
        config, paths,
        boto3_client=client,
        template_path=template_path,
        http_get=http_get,
        sleep=lambda _: None,
        tailnet_resolver=_stub_tailnet_resolver,
    )
    instances = fm.launch_fleet()
    urls = fm.wait_for_healthy(instances, timeout_s=10.0)
    assert len(urls) == 1
    assert call_count["n"] >= 3


@mock_aws
def test_wait_for_healthy_skips_terminated_instances(
    paths: LaunchPaths, template_path: Path,
):
    """If an instance enters terminated/shutting-down state in EC2
    before its heartbeat goes IDLE, wait_for_healthy must surface it
    as unhealthy rather than waiting forever."""
    client = boto3.client("ec2", region_name="us-east-1")
    _seed_iam_instance_profile()
    config = _make_config(count=1, az_fallback=["us-east-1a"])
    fm = FleetManager(
        config, paths,
        boto3_client=client,
        template_path=template_path,
        http_get=lambda url, *, timeout: (200, {"state": "IDLE"}),
        sleep=lambda _: None,
        tailnet_resolver=_stub_tailnet_resolver,
    )
    instances = fm.launch_fleet()
    # Terminate the instance behind moto's back.
    client.terminate_instances(InstanceIds=[instances[0].instance_id])
    # Drive monotonic forward.
    fake_time = {"now": 0.0}

    def fake_sleep(s):
        fake_time["now"] += s

    import mtg_bot.launcher.aws_fleet as aws_fleet_mod
    real_monotonic = aws_fleet_mod.time.monotonic
    aws_fleet_mod.time.monotonic = lambda: fake_time["now"]
    try:
        fm.sleep = fake_sleep
        with pytest.raises(FleetHealthTimeoutError):
            fm.wait_for_healthy(instances, timeout_s=10.0)
    finally:
        aws_fleet_mod.time.monotonic = real_monotonic
    # The instance's daemon_health reflects the EC2-side termination.
    assert fm.instances[0].daemon_health is not None
    assert "ec2:" in fm.instances[0].daemon_health


@mock_aws
def test_wait_for_healthy_describe_instances_retry(
    paths: LaunchPaths, template_path: Path,
):
    """A transient describe_instances ClientError must be retried
    rather than aborting the whole wait loop."""
    real_client = boto3.client("ec2", region_name="us-east-1")
    _seed_iam_instance_profile()
    config = _make_config(count=1, az_fallback=["us-east-1a"])

    class _FlakyDescribe:
        def __init__(self, real):
            self._real = real
            self._describe_calls = 0

        def run_instances(self, **kw):
            return self._real.run_instances(**kw)

        def terminate_instances(self, **kw):
            return self._real.terminate_instances(**kw)

        def describe_instances(self, **kw):
            self._describe_calls += 1
            if self._describe_calls == 1:
                raise ClientError(
                    {"Error": {"Code": "RequestLimitExceeded",
                               "Message": "slow down"}},
                    "DescribeInstances",
                )
            return self._real.describe_instances(**kw)

    flaky = _FlakyDescribe(real_client)
    fm = FleetManager(
        config, paths,
        boto3_client=flaky,
        template_path=template_path,
        http_get=lambda url, *, timeout: (200, {"state": "IDLE"}),
        sleep=lambda _: None,
        tailnet_resolver=_stub_tailnet_resolver,
    )
    instances = fm.launch_fleet()
    urls = fm.wait_for_healthy(instances, timeout_s=30.0)
    assert len(urls) == 1
    assert flaky._describe_calls >= 2


# ---------------------------------------------------------------------------
# terminate_fleet
# ---------------------------------------------------------------------------


@mock_aws
def test_terminate_fleet_calls_ec2_and_updates_state(
    paths: LaunchPaths, template_path: Path,
):
    client = boto3.client("ec2", region_name="us-east-1")
    _seed_iam_instance_profile()
    config = _make_config(count=2, az_fallback=["us-east-1a"])
    fm = FleetManager(
        config, paths,
        boto3_client=client,
        template_path=template_path,
    )
    instances = fm.launch_fleet()
    instance_ids = [inst.instance_id for inst in instances]
    fm.terminate_fleet(reason="launcher_finalize")
    # Every FleetInstance has terminated_at + terminate_reason set.
    for inst in fm.instances:
        assert inst.terminated_at is not None
        assert inst.terminate_reason == "launcher_finalize"
    # State file reflects.
    data = json.loads(paths.aws_instances_path.read_text(encoding="utf-8"))
    for rec in data["instances"]:
        assert rec["terminated_at"] is not None
        assert rec["terminate_reason"] == "launcher_finalize"
    # EC2 actually saw the call (instances now show shutting-down /
    # terminated).
    resp = client.describe_instances(InstanceIds=instance_ids)
    states = [
        inst["State"]["Name"]
        for res in resp["Reservations"]
        for inst in res["Instances"]
    ]
    assert all(s in ("shutting-down", "terminated") for s in states)


@mock_aws
def test_terminate_fleet_idempotent_recall(
    paths: LaunchPaths, template_path: Path,
):
    """A re-call after the first terminate must be a no-op (no
    duplicate EC2 calls, no field mutation)."""
    real_client = boto3.client("ec2", region_name="us-east-1")
    _seed_iam_instance_profile()
    config = _make_config(count=1, az_fallback=["us-east-1a"])

    class _CountTerminate:
        def __init__(self, real):
            self._real = real
            self.terminate_calls = 0

        def run_instances(self, **kw):
            return self._real.run_instances(**kw)

        def terminate_instances(self, **kw):
            self.terminate_calls += 1
            return self._real.terminate_instances(**kw)

        def describe_instances(self, **kw):
            return self._real.describe_instances(**kw)

    counted = _CountTerminate(real_client)
    fm = FleetManager(
        config, paths,
        boto3_client=counted,
        template_path=template_path,
    )
    instances = fm.launch_fleet()
    fm.terminate_fleet(reason="first")
    first_terminated_at = fm.instances[0].terminated_at
    assert counted.terminate_calls == 1
    fm.terminate_fleet(reason="second")
    # Second call did NOT hit EC2 again.
    assert counted.terminate_calls == 1
    # Field wasn't mutated by the second call (reason stays first's).
    assert fm.instances[0].terminate_reason == "first"
    assert fm.instances[0].terminated_at == first_terminated_at


def test_terminate_fleet_no_instances_no_op(
    paths: LaunchPaths, template_path: Path,
):
    """Calling terminate_fleet before any launch_fleet succeeded must
    not error or call EC2."""
    config = _make_config(az_fallback=["us-east-1a"])
    bogus_client = MagicMock()
    fm = FleetManager(
        config, paths,
        boto3_client=bogus_client,
        template_path=template_path,
    )
    fm.terminate_fleet(reason="empty")
    bogus_client.terminate_instances.assert_not_called()


@mock_aws
def test_terminate_fleet_swallows_client_error(
    paths: LaunchPaths, template_path: Path, caplog,
):
    """If EC2's terminate_instances itself errors, the manager logs
    but does NOT re-raise -- the launcher's finaliser is last-line
    cleanup and we'd rather over-log than block exit."""
    real_client = boto3.client("ec2", region_name="us-east-1")
    _seed_iam_instance_profile()
    config = _make_config(count=1, az_fallback=["us-east-1a"])

    class _TerminateBoom:
        def __init__(self, real):
            self._real = real

        def run_instances(self, **kw):
            return self._real.run_instances(**kw)

        def terminate_instances(self, **kw):
            raise ClientError(
                {"Error": {"Code": "InvalidInstanceID.NotFound",
                           "Message": "gone"}},
                "TerminateInstances",
            )

        def describe_instances(self, **kw):
            return self._real.describe_instances(**kw)

    fm = FleetManager(
        config, paths,
        boto3_client=_TerminateBoom(real_client),
        template_path=template_path,
    )
    fm.launch_fleet()
    with caplog.at_level("ERROR"):
        fm.terminate_fleet(reason="oops")
    # State still gets updated despite the EC2 failure.
    assert fm._terminated is True
    assert any(
        "terminate_instances failed" in rec.message
        for rec in caplog.records
    )


# ---------------------------------------------------------------------------
# FleetInstance helpers
# ---------------------------------------------------------------------------


def test_fleet_instance_urls_require_tailnet_ip():
    inst = FleetInstance(instance_id="i-abc", az="us-east-1a")
    assert inst.heartbeat_url() is None
    assert inst.worker_url() is None
    inst.tailnet_ip = "100.64.1.2"
    assert inst.heartbeat_url() == "http://100.64.1.2:5198/v2/heartbeat"
    assert inst.worker_url() == "http://100.64.1.2:5198"


# ---------------------------------------------------------------------------
# AMI / template path defaults
# ---------------------------------------------------------------------------


def test_fleet_manager_default_template_path_points_at_scripts_aws(
    paths: LaunchPaths,
):
    """The default template resolution points at the repo's
    scripts/aws/ directory (no caller config needed in production)."""
    fm = FleetManager(_make_config(), paths, boto3_client=MagicMock())
    assert fm.template_path.name == "runspec.template.json"
    assert fm.template_path.parent.name == "aws"


def test_fleet_manager_default_ami_id(
    paths: LaunchPaths,
):
    fm = FleetManager(_make_config(), paths, boto3_client=MagicMock())
    assert fm.ami_id == DEFAULT_AMI_ID


# ---------------------------------------------------------------------------
# Lazy boto3 client construction (when nothing injected)
# ---------------------------------------------------------------------------


@mock_aws
def test_fleet_manager_lazy_boto3_client_when_not_injected(
    paths: LaunchPaths, template_path: Path,
):
    """No injected client + valid AZ list -> manager constructs a real
    boto3.client('ec2') on first use. Under mock_aws this stays
    in-process."""
    config = _make_config(count=1, az_fallback=["us-east-1a"])
    fm = FleetManager(
        config, paths,
        boto3_client=None,
        template_path=template_path,
    )
    # First _ec2() call constructs the client.
    client = fm._ec2()
    assert client is not None
    # Sanity: it's a real boto3 EC2 client (has describe_instances).
    assert hasattr(client, "describe_instances")


def test_fleet_manager_lazy_client_needs_az_fallback(
    paths: LaunchPaths, template_path: Path,
):
    """Lazy client construction without any AZ available raises a
    clear FleetConfigError rather than crashing inside boto3."""
    config = _make_config(az_fallback=[])
    fm = FleetManager(
        config, paths,
        boto3_client=None,
        template_path=template_path,
    )
    with pytest.raises(FleetConfigError, match="no AZ available"):
        fm._ec2()
