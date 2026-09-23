"""TOML config + CLI-override merge for the unified launcher.

Schema lives in the :class:`LaunchConfig` dataclass. The TOML file is
the source of truth; CLI ``--section.key value`` flags override the
TOML on a per-key basis. The merge result is fully validated before
the launcher takes any side effect (registering a runs.db row,
spinning up AWS, writing shards_config, ...).

Sections:

- ``[iter]`` (Phase A: consumed in full) -- target_iter, nodes,
  samples, games_per_iteration, epochs, architecture,
  bootstrap_version.
- ``[cluster]`` (Phase A: consumed in full) -- local_only,
  master_url, mac_url, win10_url. Worker URLs are verify-only at
  Phase A (heartbeat check + IDLE assertion); restart logic is out
  of scope here.
- ``[aws]`` (Phase B owns; parsed-but-ignored at Phase A) -- count,
  instance_type, az_fallback, storage_uri.
- ``[ui]`` (Phase C owns; parsed-but-mostly-ignored at Phase A) --
  auto_start_training_ui, base_url. The launcher reads ``base_url``
  today so the cycle's clickable link prints correctly; the
  auto_start_training_ui flag is parsed but the actual subprocess
  spawn is a TODO Phase C fills.

CLI override syntax: ``--<section>.<key> <value>`` -- e.g.
``--cluster.local-only`` (bool, no arg = ``true``),
``--iter.nodes 800``, ``--aws.count 12``. The merge is a strict
allow-list: an unknown key raises ``LaunchConfigError`` so a typo
fails loudly rather than silently dropping into a no-op.
"""

from __future__ import annotations

import tomllib
import typing
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Optional, Union


class LaunchConfigError(ValueError):
    """Raised when a TOML / CLI-override is malformed.

    Always carries an actionable message: the offending key / value
    plus a hint about what was expected. The launcher's CLI wrapper
    surfaces these as ``exit 2`` with the message to stderr so the
    user sees the problem without a Python traceback.
    """


# ---------------------------------------------------------------------------
# Section dataclasses
# ---------------------------------------------------------------------------


@dataclass
class IterSection:
    """The ``[iter]`` section: what training cycle to run.

    All fields have sane defaults so a minimal TOML only needs
    ``target_iter``. ``architecture`` and ``bootstrap_version``
    pass through to ``mtg_bot iterate`` unchanged.
    """

    target_iter: int = 0
    nodes: int = 200
    samples: int = 8
    games_per_iteration: int = 8000
    epochs: int = 4
    architecture: str = "structured"
    bootstrap_version: Optional[str] = None
    # Self-play exploration knobs, passed straight through to
    # ``mtg_bot iterate --root-dirichlet-alpha/--root-dirichlet-eps/
    # --move-temperature/--temperature-cutoff``. Self-play only; the
    # eval gate stays deterministic-argmax. ``root_dirichlet_alpha
    # <= 0`` disables the root noise.
    root_dirichlet_alpha: float = 0.5
    root_dirichlet_eps: float = 0.25
    move_temperature: float = 1.0
    temperature_cutoff: int = 30


@dataclass
class ClusterSection:
    """The ``[cluster]`` section: which workers + local-vs-distributed.

    ``local_only`` short-circuits AWS fleet management entirely (the
    Phase A scope). When ``False`` the launcher will (Phase B) bring
    up AWS workers; today it errors out with "Phase B not yet
    implemented" so the launcher fails loudly rather than silently
    proceeding without workers.

    ``master_url`` / ``mac_url`` / ``win10_url`` are heartbeat
    targets: the launcher GETs ``/v2/heartbeat`` on each and refuses
    to proceed unless every worker reports ``IDLE``. Worker daemon
    restart is intentionally out of scope -- a busy worker is the
    operator's problem, not the launcher's.
    """

    local_only: bool = False
    master_url: Optional[str] = None
    mac_url: Optional[str] = None
    win10_url: Optional[str] = None


@dataclass
class AwsSection:
    """The ``[aws]`` section: AWS fleet shape (spot or on-demand).

    Parsed but only Phase B consumes it. ``az_fallback`` is the list
    of availability zones to try in order when capacity is
    unavailable. ``storage_uri`` is the bucket prefix workers upload
    artifacts to (``s3://bucket/prefix`` or ``file:///nfs/path``).
    ``market_type`` selects spot vs on-demand: spot is cheaper but
    can be reclaimed and is subject to the per-region spot quota
    (32 vCPU on the default mtg-bot account today); on-demand is
    ~3x more expensive but reliable and uses a separate quota
    (16 vCPU). FleetManager pops ``InstanceMarketOptions`` from
    the runspec when market_type=="on_demand".
    """

    count: int = 0
    instance_type: str = "c7i.4xlarge"
    az_fallback: list[str] = field(default_factory=list)
    storage_uri: Optional[str] = None
    market_type: str = "spot"


@dataclass
class UiSection:
    """The ``[ui]`` section: clickable links + auto-start training UI.

    ``base_url`` defaults to the user's tailnet hostname (per the
    project's Tailscale-only link policy) so the cycle's URL prints
    correctly even on a fresh checkout with no override.
    ``auto_start_training_ui`` is parsed but Phase C wires the actual
    subprocess spawn -- Phase A only honours it via a documented TODO.
    """

    auto_start_training_ui: bool = False
    base_url: str = "http://desktop-j05412i:5103"


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------


@dataclass
class LaunchConfig:
    """Fully-resolved launcher config (TOML merged with CLI overrides).

    Construct via :func:`load_config` -- never instantiate directly
    in user code. The dataclass is mutable for ergonomics, but the
    launcher treats the instance as immutable after the load.
    """

    iter: IterSection = field(default_factory=IterSection)
    cluster: ClusterSection = field(default_factory=ClusterSection)
    aws: AwsSection = field(default_factory=AwsSection)
    ui: UiSection = field(default_factory=UiSection)

    # ---- derived properties --------------------------------------------

    @property
    def iter_label(self) -> str:
        """``iter_NNN`` -- matches :mod:`mtg_bot.cli.iterate`'s
        internal ``iter_label`` format (see iterate.py L2019).
        Used as the prefix for the cycle_id and the per-cycle paths.
        """
        return f"iter_{self.iter.target_iter:03d}"

    @property
    def cycle_id(self) -> str:
        """``iter_NNN_cycle`` -- matches iterate.py L2034.

        This is the runs.db row id the launcher pre-registers, and
        the UI's force-kill button maps a click to.
        """
        return f"{self.iter_label}_cycle"


# ---------------------------------------------------------------------------
# Section registry + validation
# ---------------------------------------------------------------------------


# Maps section name -> dataclass type. The merge code uses this to
# look up which fields a given section accepts and what their types
# should be.
_SECTION_TYPES: dict[str, type] = {
    "iter": IterSection,
    "cluster": ClusterSection,
    "aws": AwsSection,
    "ui": UiSection,
}


def _section_field_names(section: str) -> set[str]:
    """The set of allowed keys for a TOML/CLI section."""
    return {f.name for f in fields(_SECTION_TYPES[section])}


def _coerce_value(
    section: str, key: str, value: Any, target_type: type,
) -> Any:
    """Coerce a string / TOML-parsed value to the dataclass field
    type. Used for CLI overrides (always strings) and a defensive
    check on TOML values (TOML parses ints / bools / lists natively
    so the no-op path is the common case).
    """
    # TOML may already parse to the right type; pass-through.
    origin = typing.get_origin(target_type)
    if origin is list or target_type is list:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            # Comma-separated string from CLI overrides.
            return [s.strip() for s in value.split(",") if s.strip()]
        raise LaunchConfigError(
            f"{section}.{key}: expected list, got {type(value).__name__}",
        )
    # Optional[T] -- Union[T, None]; pull T out.
    if origin is Union:
        args = [a for a in typing.get_args(target_type) if a is not type(None)]
        if not args:
            return value
        target_type = args[0]
    if target_type is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            low = value.strip().lower()
            if low in ("true", "1", "yes", "on"):
                return True
            if low in ("false", "0", "no", "off", ""):
                return False
            raise LaunchConfigError(
                f"{section}.{key}: invalid bool {value!r}; "
                f"use true/false",
            )
        raise LaunchConfigError(
            f"{section}.{key}: expected bool, got {type(value).__name__}",
        )
    if target_type is int:
        if isinstance(value, bool):
            # bool is a subclass of int but a CLI override of "true"
            # for an int field is almost certainly a typo.
            raise LaunchConfigError(
                f"{section}.{key}: expected int, got bool",
            )
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError as exc:
                raise LaunchConfigError(
                    f"{section}.{key}: invalid int {value!r}",
                ) from exc
        raise LaunchConfigError(
            f"{section}.{key}: expected int, got {type(value).__name__}",
        )
    if target_type is float:
        if isinstance(value, bool):
            raise LaunchConfigError(
                f"{section}.{key}: expected float, got bool",
            )
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError as exc:
                raise LaunchConfigError(
                    f"{section}.{key}: invalid float {value!r}",
                ) from exc
        raise LaunchConfigError(
            f"{section}.{key}: expected float, got {type(value).__name__}",
        )
    if target_type is str:
        if isinstance(value, str):
            return value
        raise LaunchConfigError(
            f"{section}.{key}: expected str, got {type(value).__name__}",
        )
    # Unknown target type -- pass through and let dataclass __init__ catch it.
    return value


def _field_type(section: str, key: str) -> type:
    """Look up the dataclass-declared type for a section + key.

    ``dataclasses.fields(...)`` returns ``Field.type`` as a string
    when the module has ``from __future__ import annotations`` -- so
    we resolve via ``typing.get_type_hints`` which evaluates the
    string back into a live type object.
    """
    hints = typing.get_type_hints(_SECTION_TYPES[section])
    if key not in hints:
        raise LaunchConfigError(f"unknown key {section}.{key!r}")
    return hints[key]


def _apply_section_overrides(
    target: LaunchConfig,
    section: str,
    overrides: dict[str, Any],
) -> None:
    """Mutate ``target.<section>`` with the coerced overrides.

    Unknown keys raise -- this is an allow-list, not a free-form bag.
    """
    sec_obj = getattr(target, section)
    allowed = _section_field_names(section)
    for key, value in overrides.items():
        if key not in allowed:
            raise LaunchConfigError(
                f"unknown key {section}.{key!r}; allowed: "
                f"{sorted(allowed)}",
            )
        target_type = _field_type(section, key)
        coerced = _coerce_value(section, key, value, target_type)
        setattr(sec_obj, key, coerced)


# ---------------------------------------------------------------------------
# Public API: load + merge
# ---------------------------------------------------------------------------


def _load_toml(path: Path) -> dict[str, Any]:
    """Read a TOML file from disk. Raises :class:`LaunchConfigError`
    on missing-file / parse-error so the launcher's wrapper can
    surface a clean stderr message.
    """
    if not path.is_file():
        raise LaunchConfigError(f"config file not found: {path}")
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise LaunchConfigError(
            f"{path}: TOML parse error: {exc}",
        ) from exc


def _build_from_toml(data: dict[str, Any]) -> LaunchConfig:
    """Apply a TOML dict onto a fresh :class:`LaunchConfig`.

    Top-level keys outside the four section names raise so a typo
    like ``[itr]`` (missing ``e``) fails loudly. Section bodies are
    forwarded to :func:`_apply_section_overrides` for per-key
    validation.
    """
    cfg = LaunchConfig()
    for section_name, section_body in data.items():
        if section_name not in _SECTION_TYPES:
            raise LaunchConfigError(
                f"unknown top-level section {section_name!r}; "
                f"allowed: {sorted(_SECTION_TYPES)}",
            )
        if not isinstance(section_body, dict):
            raise LaunchConfigError(
                f"section [{section_name}] must be a table, got "
                f"{type(section_body).__name__}",
            )
        _apply_section_overrides(cfg, section_name, section_body)
    return cfg


def parse_cli_overrides(
    overrides: list[str],
) -> dict[str, dict[str, Any]]:
    """Parse a sequence of ``--<section>.<key>=<value>`` (or
    ``--<section>.<key> <value>`` pairs) into a nested dict.

    Bare ``--<section>.<key>`` (no value) is treated as a bool flag
    set to ``true`` -- the convention ``--cluster.local-only``
    matches argparse's ``store_true`` behaviour, which the launcher
    CLI surface exposes for common bool flags.

    Returns ``{section: {key: value}}``. The caller passes this to
    :func:`load_config` which forwards to
    :func:`_apply_section_overrides`.
    """
    out: dict[str, dict[str, Any]] = {}
    i = 0
    while i < len(overrides):
        token = overrides[i]
        if not token.startswith("--"):
            raise LaunchConfigError(
                f"override {token!r}: must start with --section.key",
            )
        rest = token[2:]
        if "=" in rest:
            keypath, value = rest.split("=", 1)
            i += 1
        else:
            keypath = rest
            # Peek at next token; if it doesn't start with --, treat
            # as the value. Otherwise this is a bool flag.
            if i + 1 < len(overrides) and not overrides[i + 1].startswith(
                "--",
            ):
                value = overrides[i + 1]
                i += 2
            else:
                value = "true"
                i += 1
        if "." not in keypath:
            raise LaunchConfigError(
                f"override --{keypath}: missing section prefix (use "
                f"--section.key)",
            )
        section, key = keypath.split(".", 1)
        # Normalise dashes to underscores so --cluster.local-only
        # routes to ``local_only``.
        key = key.replace("-", "_")
        out.setdefault(section, {})[key] = value
    return out


def load_config(
    toml_path: Optional[Path] = None,
    *,
    overrides: Optional[dict[str, dict[str, Any]]] = None,
) -> LaunchConfig:
    """Load + merge a launch config.

    Order: defaults -> TOML -> CLI overrides. CLI wins.

    ``toml_path`` may be ``None`` (no file; CLI-only). ``overrides``
    is the parsed CLI-overrides dict from
    :func:`parse_cli_overrides`; pass ``None`` to skip.

    Raises :class:`LaunchConfigError` on any validation failure:
    unknown section, unknown key, wrong type, missing required field.
    """
    if toml_path is not None:
        data = _load_toml(toml_path)
        cfg = _build_from_toml(data)
    else:
        cfg = LaunchConfig()
    if overrides:
        for section_name, section_body in overrides.items():
            if section_name not in _SECTION_TYPES:
                raise LaunchConfigError(
                    f"unknown override section {section_name!r}; "
                    f"allowed: {sorted(_SECTION_TYPES)}",
                )
            _apply_section_overrides(cfg, section_name, section_body)
    _validate(cfg)
    return cfg


def _validate(cfg: LaunchConfig) -> None:
    """Cross-field validation after the merge.

    Cheaper-to-surface checks live here so the launcher fails before
    any side effect:

    - ``iter.target_iter`` must be > 0.
    - When ``cluster.local_only`` is False (Phase B AWS path):
      ``aws.count`` must be >= 1 AND ``aws.az_fallback`` must have
      at least one entry. Otherwise the launcher would unconditionally
      raise inside FleetManager.launch_fleet -- catching the config
      mistake here means the failure surfaces at config-load time
      with a clean stderr message, before runs.db ever sees the row.
    - When ``cluster.local_only`` is True, ``aws.*`` fields are parsed
      but unused (the launcher skips the FleetManager call path
      entirely). Defaults are allowed and intentionally not validated.
    """
    if cfg.iter.target_iter <= 0:
        raise LaunchConfigError(
            f"iter.target_iter must be positive; got "
            f"{cfg.iter.target_iter}",
        )
    if not cfg.cluster.local_only:
        # Phase B AWS path: validate the AWS section is actionable.
        if cfg.aws.count < 1:
            raise LaunchConfigError(
                f"aws.count must be >= 1 when cluster.local_only is "
                f"false; got {cfg.aws.count}. Either set "
                f"[aws].count in the TOML / pass --aws.count N, or "
                f"flip cluster.local_only = true.",
            )
        if not cfg.aws.az_fallback:
            raise LaunchConfigError(
                "aws.az_fallback is empty when cluster.local_only is "
                "false; supply at least one AZ for the launcher to "
                "try (e.g. [aws].az_fallback = [\"us-east-1a\", "
                "\"us-east-1b\"]).",
            )
        if cfg.aws.market_type not in {"spot", "on_demand"}:
            raise LaunchConfigError(
                f"aws.market_type must be 'spot' or 'on_demand'; got "
                f"{cfg.aws.market_type!r}.",
            )


__all__ = [
    "AwsSection",
    "ClusterSection",
    "IterSection",
    "LaunchConfig",
    "LaunchConfigError",
    "UiSection",
    "load_config",
    "parse_cli_overrides",
]
