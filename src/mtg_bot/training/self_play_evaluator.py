"""Which evaluator drives a self-play stage: the NN, or the heuristic.

Background (measured 2026-09-24)
================================

The AlphaZero loop bootstraps from a random-init network. With an
uninformative evaluator the PIMC/PUCT search degenerates to PASS --
``PassPriority`` is the first legal action and therefore the first
child expanded (``training/action_encoding``+``legal.py``), so a
flat prior and a flat value leave the visit counts piled on the pass
slot. Ladder results at ``nodes=100 / samples=2``:

* ``v1`` (random-init, s2 lineage) vs ``random``:  8-16 (loses)
* the s2 lineage's best net vs ``random``:        68-132 (loses)
* ``heuristic_pimc`` vs ``random``:               182-18 (wins)
* ``heuristic_pimc`` vs the nets:                 191-9  (wins)

Every self-play shard generated so far therefore has BOTH targets
poisoned: the policy target imitates a random-init agent, and the
value target is the outcome of a game two incompetent agents played.

The fix is a warm start: generate the first corpus with the SAME
PIMC search but the heuristic evaluator (``HeuristicConfig()`` ->
``MtgHeuristicEvaluator``), train the structured net on it, then
continue the AlphaZero loop from that net. The heuristic evaluator
is also ~50-100x cheaper per game (no torch forward pass at all).

This module is the single source of truth for the *evaluator kind*
that a self-play stage runs under, so the local pool path
(``cli/iterate._self_play``), the v2 stage spec
(``distributed_rest_orchestrator``) and the worker
(``worker_daemon_production_runner``) can't drift.

The old-worker contract
=======================

A heuristic self-play stage must NEVER be silently played by an
old worker that doesn't understand the ``evaluator`` field -- it
would fall back to the NN and quietly produce exactly the corpus
this whole feature exists to avoid.

:func:`heuristic_stage_weights` is the interlock. A heuristic stage
carries ``weights = {"p0": "", "p1": ""}``; an old worker's first
statement is::

    version = weights.get("p0") or weights.get("new")
    if not version:
        raise RuntimeError(f"self-play claim missing weights.p0: ...")

so it crashes on every claim, reports ``crashed``, and the stage
yields zero samples -- which ``iterate.self_play_yield_error`` turns
into a hard ``sys.exit`` with an actionable message. Loud, not
silent. A new worker reads ``evaluator == "heuristic"`` first and
never looks at ``weights`` at all.

Dirichlet root noise
====================

``root_dirichlet_alpha`` / ``root_dirichlet_eps`` are carried
through to the heuristic stage's :class:`PimcConfig` for symmetry
with the NN path, but be aware of what they can and cannot do:
``MCTS._apply_root_dirichlet_noise`` mixes noise into the root
children's ``prior`` values, and priors are only *read* under PUCT
selection (``puct=True``), which in turn requires a policy-head
evaluator. The heuristic evaluator has no policy head, so its MCTS
runs UCB1 and the noise is structurally inert.

Rather than let that be a silent no-op, :func:`build_heuristic_pimc_config`
logs a one-time warning when a non-``None`` alpha is passed. Under
UCB1 with ``FullEnumeration`` every root child is expanded and
evaluated at least once anyway; the actual self-play diversity knob
for a heuristic corpus is ``--move-temperature`` /
``--temperature-cutoff``, which is applied in
``data_gen._play_one_game_recording`` and is entirely
strategy-agnostic (it samples the PLAYED move from whatever visit
counts the search returned).
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

from mtg_bot.training.config import HeuristicConfig, PimcConfig

log = logging.getLogger(__name__)

__all__ = [
    "EVALUATOR_HEURISTIC",
    "EVALUATOR_NN",
    "SELF_PLAY_EVALUATORS",
    "build_heuristic_pimc_config",
    "claim_evaluator",
    "heuristic_stage_weights",
    "normalize_evaluator",
]


EVALUATOR_NN = "nn"
EVALUATOR_HEURISTIC = "heuristic"
SELF_PLAY_EVALUATORS = (EVALUATOR_NN, EVALUATOR_HEURISTIC)

# Module-level latch so the "noise is inert under UCB1" warning is
# emitted once per process instead of once per game (the worker
# rebuilds the config per claim).
_noise_warned = False


def normalize_evaluator(value: Optional[str]) -> str:
    """Validate a self-play evaluator kind.

    ``None`` / ``""`` -> ``"nn"`` (the historical default, and what a
    stage spec written by an older orchestrator looks like). Anything
    outside :data:`SELF_PLAY_EVALUATORS` raises ``ValueError`` --
    a typo'd kind must not silently fall back to the NN.
    """
    if value is None or value == "":
        return EVALUATOR_NN
    if not isinstance(value, str):
        raise ValueError(
            f"self-play evaluator must be a string, got {value!r}"
        )
    kind = value.strip().lower()
    if kind not in SELF_PLAY_EVALUATORS:
        raise ValueError(
            f"unknown self-play evaluator {value!r}; expected one of "
            f"{', '.join(SELF_PLAY_EVALUATORS)}"
        )
    return kind


def claim_evaluator(claim: Mapping[str, Any]) -> str:
    """Read the evaluator kind off a ``/v2/claim`` payload.

    Claims from a coordinator that predates this feature have no
    ``evaluator`` key at all -> ``"nn"``, byte-identical behaviour to
    before. See the module docstring for why the reverse direction
    (new coordinator, old worker) is made to fail loudly instead.
    """
    return normalize_evaluator(claim.get("evaluator"))


def heuristic_stage_weights() -> dict[str, str]:
    """The ``weights`` block a heuristic self-play stage spec carries.

    Deliberately empty strings rather than a placeholder version
    label: an old worker treats a falsy ``weights["p0"]`` as a hard
    error, which is exactly the behaviour we want. See the
    "old-worker contract" section of the module docstring.
    """
    return {"p0": "", "p1": ""}


def build_heuristic_pimc_config(
    *,
    nodes: int,
    samples: int,
    root_dirichlet_alpha: Optional[float] = None,
    root_dirichlet_eps: float = 0.25,
    heuristic: Optional[HeuristicConfig] = None,
) -> PimcConfig:
    """Build the heuristic-evaluator PIMC config for self-play.

    Mirrors how ``cli/ladder.resolve_agent`` builds its ``heuristic``
    participant (``PimcConfig(samples=..., inner_nodes=...,
    heuristic=HeuristicConfig(), batch_size=1)``) so the corpus is
    generated by the exact agent the ladder measured at 182-18 vs
    random. ``batch_size=1`` because there is no NN forward pass to
    amortize -- batching only adds virtual-loss bookkeeping.
    """
    global _noise_warned
    if root_dirichlet_alpha is not None and not _noise_warned:
        _noise_warned = True
        log.warning(
            "[self_play_evaluator] root_dirichlet_alpha=%s was "
            "requested for a HEURISTIC self-play stage. Dirichlet "
            "root noise perturbs PUCT priors, and the heuristic "
            "evaluator has no policy head, so its MCTS runs UCB1 "
            "and the noise has NO effect on the search. The "
            "effective exploration knob for this corpus is "
            "--move-temperature / --temperature-cutoff.",
            root_dirichlet_alpha,
        )
    return PimcConfig(
        samples=int(samples),
        inner_nodes=int(nodes),
        heuristic=heuristic if heuristic is not None else HeuristicConfig(),
        batch_size=1,
        root_dirichlet_alpha=root_dirichlet_alpha,
        root_dirichlet_eps=root_dirichlet_eps,
    )
