"""Data shapes shared by the v2 REST orchestrator + the worker daemon.

Pre-cutover this module hosted the SSH-driven self-play / eval
orchestrator (``run_distributed_self_play`` / ``run_distributed_eval``)
plus the entire SSH plumbing — ``scp``-based weight push,
``scp``-based replay collection, terminal-status SSH watchdog, the
per-iter ``run_shard_remote`` driver, the pull-mode shard runner used
by orchestrator-side workers, and the SQLite-backed master queue
helpers. All of that was deleted in the v2-cutover-followup PR after
``mtg_bot iterate`` and ``mtg_bot eval`` both switched to the REST
orchestrator (``mtg_bot.distributed_rest_orchestrator``).

What remains in this module today is just the per-stage spec
dataclasses (``SelfPlayJobSpec``, ``EvalJobSpec``) — these carry the
NN config + heuristics bundle + structured-token flag through both
the in-process iterate caller and any future serialized-spec
consumer. Workers themselves no longer receive these specs across
the wire (the v2 ``/v2/claim`` response carries just the per-game
knobs); the dataclasses stay because the iterate driver still uses
them as the single place that gathers spec config before handing it
to the REST orchestrator's stage builder, and existing tests pin
the dataclass round-trip contract.

See ``docs/DISTRIBUTED_API_v2.md`` for the v2 REST contract and
``docs/DISTRIBUTED_RUN_FLOW.md`` for the end-to-end run walkthrough.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from mtg_bot.search.heuristics_config import HeuristicsConfig


@dataclass(frozen=True)
class SelfPlayJobSpec:
    """Parameters for a self-play stage's per-game NN config.

    Used by ``mtg_bot iterate``'s self-play phase to gather config in
    one place before handing it to the REST orchestrator's stage
    builder. Frozen so it can cross a multiprocessing pickle boundary
    cleanly when iterate dispatches in-process work.

    Path fields are repo-relative by convention — the same spec
    instance is consumed both on the master (where the orchestrator
    builds it) and (conceptually) on workers (where the matching
    per-version metadata.json is fetched at /v2/weights/<v>/metadata).
    Forward-slash normalization in ``to_dict()`` is preserved so any
    historical serialized spec on disk round-trips unchanged.
    """

    weights_path: str
    samples: int
    inner_nodes: int
    hidden_sizes: Optional[tuple[int, ...]]
    base_seed: int
    per_game_timeout_sec: Optional[float]
    deck_pool_path: Optional[str] = None
    with_policy: bool = True
    decision_cap: int = 4000
    sample_every: int = 1
    capture_every: int = 0  # 0 = no replay capture
    nn_version_label: Optional[str] = None
    replays_root: Optional[str] = None
    hang_dump_root: Optional[str] = None
    use_ismcts: bool = False
    use_belief_weighted: bool = False
    # Dual-head architecture string for the shard's NNEvaluator. ``None``
    # means "use NNEvaluator's default" (= "shared", the back-compat
    # path). Iterate threads the bootstrap-or-promoted version's
    # ``metadata.architecture`` here.
    architecture: Optional[str] = None
    policy_hidden_sizes: Optional[tuple[int, ...]] = None
    # Slot-mapping convention the bootstrap weights were trained
    # against. ``None`` defaults to NNEvaluator's ``"positional_v1"``
    # (v13/v15/v16 metadata predates the field).
    action_encoding_version: Optional[str] = None
    # Bundle of priority short-circuit / filter heuristics. Self-play
    # default = every flag ON. See SEARCH_LIMITATIONS for the
    # per-heuristic rationale.
    heuristics: HeuristicsConfig = field(default_factory=HeuristicsConfig)
    # Opt into the shared-memory NN server (PR #40) on the master's
    # in-process path. Linux-only; ignored on Windows / macOS.
    use_shm_server: bool = False
    # Opt into the Step 1 structured-token data-gen writer (see
    # ``docs/NN_REPRESENTATION_ROADMAP.md``).
    write_structured_tokens: bool = False

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable dict. Forward-slash normalizes path fields
        so the same wire format works for Windows and POSIX consumers
        (any serialized spec on disk round-trips bit-identical)."""
        def _posix(p):
            return p.replace("\\", "/") if isinstance(p, str) else p
        return {
            "weights_path": _posix(self.weights_path),
            "samples": self.samples,
            "inner_nodes": self.inner_nodes,
            "hidden_sizes": (
                list(self.hidden_sizes) if self.hidden_sizes is not None
                else None
            ),
            "base_seed": self.base_seed,
            "per_game_timeout_sec": self.per_game_timeout_sec,
            "deck_pool_path": _posix(self.deck_pool_path),
            "with_policy": self.with_policy,
            "decision_cap": self.decision_cap,
            "sample_every": self.sample_every,
            "capture_every": self.capture_every,
            "nn_version_label": self.nn_version_label,
            "replays_root": _posix(self.replays_root),
            "hang_dump_root": _posix(self.hang_dump_root),
            "use_ismcts": self.use_ismcts,
            "use_belief_weighted": self.use_belief_weighted,
            "heuristics": self.heuristics.to_dict(),
            "architecture": self.architecture,
            "policy_hidden_sizes": (
                list(self.policy_hidden_sizes)
                if self.policy_hidden_sizes is not None else None
            ),
            "action_encoding_version": self.action_encoding_version,
            "use_shm_server": self.use_shm_server,
            "write_structured_tokens": self.write_structured_tokens,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SelfPlayJobSpec":
        hs = d.get("hidden_sizes")
        h = d.get("heuristics")
        heuristics = (
            HeuristicsConfig.from_dict(h) if h is not None
            else HeuristicsConfig()
        )
        return cls(
            weights_path=d["weights_path"],
            samples=int(d["samples"]),
            inner_nodes=int(d["inner_nodes"]),
            hidden_sizes=tuple(hs) if hs is not None else None,
            base_seed=int(d["base_seed"]),
            per_game_timeout_sec=d.get("per_game_timeout_sec"),
            deck_pool_path=d.get("deck_pool_path"),
            with_policy=bool(d.get("with_policy", True)),
            decision_cap=int(d.get("decision_cap", 4000)),
            sample_every=int(d.get("sample_every", 1)),
            capture_every=int(d.get("capture_every", 0)),
            nn_version_label=d.get("nn_version_label"),
            replays_root=d.get("replays_root"),
            hang_dump_root=d.get("hang_dump_root"),
            use_ismcts=bool(d.get("use_ismcts", False)),
            use_belief_weighted=bool(d.get("use_belief_weighted", False)),
            heuristics=heuristics,
            architecture=d.get("architecture"),
            policy_hidden_sizes=(
                tuple(d["policy_hidden_sizes"])
                if d.get("policy_hidden_sizes") is not None else None
            ),
            action_encoding_version=d.get("action_encoding_version"),
            use_shm_server=bool(d.get("use_shm_server", False)),
            write_structured_tokens=bool(
                d.get("write_structured_tokens", False)
            ),
        )


@dataclass(frozen=True)
class EvalJobSpec:
    """Eval-mode counterpart to :class:`SelfPlayJobSpec`.

    Carries the per-side NN config for an eval-gate match between
    ``new_weights_path`` (seat 0) and ``old_weights_path`` (seat 1).
    ``old_weights_path=None`` falls back to a heuristic opponent for
    sanity-check baseline evals.
    """

    new_weights_path: str
    old_weights_path: Optional[str]
    samples: int
    inner_nodes: int
    hidden_sizes: Optional[tuple[int, ...]]
    base_seed: int
    per_game_timeout_sec: Optional[float]
    deck_pool_path: Optional[str] = None
    capture_every: int = 0
    nn_new_version_label: Optional[str] = None
    nn_old_version_label: Optional[str] = None
    replays_root: Optional[str] = None
    hang_dump_root: Optional[str] = None
    opponent_label: str = "previous"
    use_ismcts: bool = False
    use_belief_weighted: bool = False
    new_architecture: Optional[str] = None
    old_architecture: Optional[str] = None
    policy_hidden_sizes: Optional[tuple[int, ...]] = None
    # Per-side slot-mapping convention. Cross-version evals (e.g.
    # v17[canonical_v2] vs v13[positional_v1]) genuinely need each
    # side encoded under its own version.
    new_action_encoding_version: Optional[str] = None
    old_action_encoding_version: Optional[str] = None
    # Eval default = every flag OFF (``HeuristicsConfig.disabled()``):
    # match outcomes determine acceptance, so the strength-vs-throughput
    # tradeoff that justifies the heuristics in self-play does not
    # apply here.
    heuristics: HeuristicsConfig = field(
        default_factory=HeuristicsConfig.disabled,
    )
    use_shm_server: bool = False

    def to_dict(self) -> dict[str, Any]:
        def _posix(p):
            return p.replace("\\", "/") if isinstance(p, str) else p
        return {
            "new_weights_path": _posix(self.new_weights_path),
            "old_weights_path": _posix(self.old_weights_path),
            "samples": self.samples,
            "inner_nodes": self.inner_nodes,
            "hidden_sizes": (
                list(self.hidden_sizes) if self.hidden_sizes is not None
                else None
            ),
            "base_seed": self.base_seed,
            "per_game_timeout_sec": self.per_game_timeout_sec,
            "deck_pool_path": _posix(self.deck_pool_path),
            "capture_every": self.capture_every,
            "nn_new_version_label": self.nn_new_version_label,
            "nn_old_version_label": self.nn_old_version_label,
            "replays_root": _posix(self.replays_root),
            "hang_dump_root": _posix(self.hang_dump_root),
            "opponent_label": self.opponent_label,
            "use_ismcts": self.use_ismcts,
            "use_belief_weighted": self.use_belief_weighted,
            "heuristics": self.heuristics.to_dict(),
            "new_architecture": self.new_architecture,
            "old_architecture": self.old_architecture,
            "policy_hidden_sizes": (
                list(self.policy_hidden_sizes)
                if self.policy_hidden_sizes is not None else None
            ),
            "new_action_encoding_version": (
                self.new_action_encoding_version
            ),
            "old_action_encoding_version": (
                self.old_action_encoding_version
            ),
            "use_shm_server": self.use_shm_server,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EvalJobSpec":
        hs = d.get("hidden_sizes")
        h = d.get("heuristics")
        heuristics = (
            HeuristicsConfig.from_dict(h) if h is not None
            else HeuristicsConfig.disabled()
        )
        return cls(
            new_weights_path=d["new_weights_path"],
            old_weights_path=d.get("old_weights_path"),
            samples=int(d["samples"]),
            inner_nodes=int(d["inner_nodes"]),
            hidden_sizes=tuple(hs) if hs is not None else None,
            base_seed=int(d["base_seed"]),
            per_game_timeout_sec=d.get("per_game_timeout_sec"),
            deck_pool_path=d.get("deck_pool_path"),
            capture_every=int(d.get("capture_every", 0)),
            nn_new_version_label=d.get("nn_new_version_label"),
            nn_old_version_label=d.get("nn_old_version_label"),
            replays_root=d.get("replays_root"),
            hang_dump_root=d.get("hang_dump_root"),
            opponent_label=d.get("opponent_label", "previous"),
            use_ismcts=bool(d.get("use_ismcts", False)),
            use_belief_weighted=bool(d.get("use_belief_weighted", False)),
            heuristics=heuristics,
            new_architecture=d.get("new_architecture"),
            old_architecture=d.get("old_architecture"),
            policy_hidden_sizes=(
                tuple(d["policy_hidden_sizes"])
                if d.get("policy_hidden_sizes") is not None else None
            ),
            new_action_encoding_version=d.get(
                "new_action_encoding_version"
            ),
            old_action_encoding_version=d.get(
                "old_action_encoding_version"
            ),
            use_shm_server=bool(d.get("use_shm_server", False)),
        )


__all__ = [
    "EvalJobSpec",
    "SelfPlayJobSpec",
]
