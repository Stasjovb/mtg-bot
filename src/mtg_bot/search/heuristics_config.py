"""Bundled training-time heuristic toggles for ``MtgGameStateAdapter``.

Five separate priority short-circuit / filter heuristics live on the
adapter (phase prune, force land drop, skip empty combat, skip opp
postcombat main, skip dead main 1). They share the same toggle shape
(boolean on/off, default ON for self-play, default OFF for eval), the
same JSON-serialization needs (the distributed orchestrator round-
trips them via ``SelfPlayJobSpec`` / ``EvalJobSpec``), and travel
together through the call chain. Bundling them as one config means
adding a sixth heuristic doesn't fan out into ~16 plumbing edits
across data_gen / self_play / distributed / both job specs / the
worker packed-args tuple.

The dataclass is frozen so it cross-pickles cleanly into mp workers
and is safe to share across the adapter's ``clone()`` (no aliasing
hazard since instances are immutable).

Production self-play default = all flags ``True`` (the dataclass
default-factory). Eval default = ``HeuristicsConfig.disabled()``
(all ``False``). Tests that want a no-heuristics adapter call
``HeuristicsConfig.disabled()`` explicitly; conftest.py wraps the
adapter so that's the default in test sessions.

Each entry's rationale + acceptable-failure case lives at the
corresponding helper docstring on ``MtgGameStateAdapter`` and at the
SEARCH_LIMITATIONS.md entries (#6, #7, #9, #10, #11).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class HeuristicsConfig:
    """Bundled toggles for the adapter's priority short-circuit
    heuristics.

    All defaults are ``True``: production self-play uses every
    heuristic. ``HeuristicsConfig.disabled()`` returns the all-False
    counterpart used by eval / correctness-sensitive runs (and by the
    test session fixture that wraps the adapter).
    """

    phase_prune_enabled: bool = True
    force_landdrop_enabled: bool = True
    skip_empty_combat_enabled: bool = True
    skip_opp_postcombat_main_enabled: bool = True
    skip_dead_main1_enabled: bool = True

    @classmethod
    def disabled(cls) -> "HeuristicsConfig":
        """Return an instance with every heuristic flag set to
        ``False``. Use for eval / tournament / correctness-sensitive
        adapters where match outcomes are load-bearing and the
        documented divergences from optimal play are not acceptable.
        """
        return cls(
            phase_prune_enabled=False,
            force_landdrop_enabled=False,
            skip_empty_combat_enabled=False,
            skip_opp_postcombat_main_enabled=False,
            skip_dead_main1_enabled=False,
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable dict. Round-trips through ``from_dict``.

        Used by ``SelfPlayJobSpec.to_dict`` / ``EvalJobSpec.to_dict``
        to ship the config across the SSH boundary to remote shards.
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "HeuristicsConfig":
        """Reconstruct from a dict produced by ``to_dict`` (or any
        compatible mapping). Missing keys default to the field's
        dataclass default — which is ``True`` for the production
        self-play default. Callers that want the eval default for
        missing keys (the prior ``EvalJobSpec.from_dict`` shape)
        should pass the dict on top of ``disabled().to_dict()``
        instead, or — more simply — call ``disabled()`` directly when
        the dict is empty.

        Boolean coercion mirrors the prior per-flag ``bool(...)``
        guards: any truthy value (1, "true", etc.) maps to True.
        """
        return cls(
            phase_prune_enabled=bool(
                d.get("phase_prune_enabled", True),
            ),
            force_landdrop_enabled=bool(
                d.get("force_landdrop_enabled", True),
            ),
            skip_empty_combat_enabled=bool(
                d.get("skip_empty_combat_enabled", True),
            ),
            skip_opp_postcombat_main_enabled=bool(
                d.get("skip_opp_postcombat_main_enabled", True),
            ),
            skip_dead_main1_enabled=bool(
                d.get("skip_dead_main1_enabled", True),
            ),
        )
