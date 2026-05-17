"""Process-global search-work counters: NN evaluations and search nodes.

Motivation
----------
"Games/hour" and "seconds/game" conflate three independent axes —
game length (number of decisions), the search budget per decision
(``samples * inner_nodes``), and the per-node cost regime
(cpu / cuda / SHM). Two runs at different ``--nodes`` are not
comparable in games/hour, which is exactly why broken-benchmark
perf multipliers survived as long as they did.

This module exposes the two depth-invariant units that *are*
comparable:

* **search nodes** — one ``Budget.consume_node()`` tick. The unit of
  intended search work; linear in the ``inner_nodes`` / ``--nodes``
  budget (each tree node stores its own state, so expanding a child
  is one ``clone()`` + one ``apply()`` — O(1) per node, not an
  O(depth) root replay; verified in ``mcts.py``).
* **NN-evaluated states** — a state that actually went through the
  network (terminal leaves short-circuit to exact ±1/0 and per-search
  NN-eval cache hits short-circuit before the evaluator, so neither
  increments this). This is exactly the work GPU / SHM accelerate, so
  ``wall_seconds / nn_eval_states`` (``ms / NN-eval``) is the right
  cross-device, cross-depth comparison unit.

Their ratio is itself the single diagnostic that matters:
``skipped = nodes - nn_eval_states`` is the count of search nodes
that needed no forward (terminal **or** cache hit), and
``nn_eval_fraction`` is how cache-effective / terminal-heavy the
search was.

Design
------
Counters are plain module-global ints, no lock. A self-play game runs
its PIMC/MCTS search single-threaded within one process; ``mp.Pool``
workers are separate processes with independent module globals; the
SHM eval server is a separate process and its client counts the
states it *submits* (the game-relevant work is the same regardless of
where the matmul physically runs). So there is genuinely no
intra-process concurrency on these counters, and a lock would only
add overhead to the very hot path we are trying to measure. The
increment helpers are a single ``global`` int add — sub-100ns,
<0.1% of a per-node clone+apply+forward.

A harness brackets a unit of work with :func:`reset` then
:func:`snapshot`; see ``EvalCounters`` for the derived views.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "EvalCounters",
    "record_node",
    "record_nn_eval",
    "reset",
    "snapshot",
]


_nodes: int = 0
_nn_eval_states: int = 0
_nn_forward_calls: int = 0


def record_node(n: int = 1) -> None:
    """Record ``n`` search nodes consumed (default 1).

    Called once per ``Budget.consume_node()`` — i.e. exactly once per
    expanded tree node, in both the serial and the batched MCTS
    search paths (and ISMCTS, which shares the ``Budget`` contract).
    """
    global _nodes
    _nodes += n


def record_nn_eval(n_states: int, n_calls: int = 1) -> None:
    """Record an NN forward over ``n_states`` non-terminal states.

    ``n_calls`` is the number of *logical* evaluator invocations the
    states were grouped into (1 for a batched call covering many
    states; the SHM client may internally chunk a batched submit but
    still reports it as one logical invocation). ``n_states`` is the
    quantity that matters — it is the ``ms / NN-eval`` denominator;
    ``n_calls`` only feeds the secondary ``states_per_call`` batch-fill
    diagnostic.

    Must be called only for states that genuinely reach the network:
    terminal short-circuits (exact ±1/0) and per-search NN-eval cache
    hits must NOT call this.
    """
    global _nn_eval_states, _nn_forward_calls
    _nn_eval_states += n_states
    _nn_forward_calls += n_calls


def reset() -> None:
    """Zero all counters. Call before the unit of work to bracket."""
    global _nodes, _nn_eval_states, _nn_forward_calls
    _nodes = 0
    _nn_eval_states = 0
    _nn_forward_calls = 0


@dataclass(frozen=True)
class EvalCounters:
    """Immutable snapshot of the process-global counters.

    ``nodes``           total search-budget nodes consumed.
    ``nn_eval_states``  states that actually went through the network.
    ``nn_forward_calls``logical (possibly batched) evaluator calls.
    """

    nodes: int
    nn_eval_states: int
    nn_forward_calls: int

    @property
    def skipped(self) -> int:
        """Search nodes that needed no NN forward — terminal leaves
        (exact ±1/0) plus per-search NN-eval cache hits.

        Clamped at 0: belief / opponent-policy forwards add
        ``nn_eval_states`` without a matching search node, so the raw
        difference can go negative on belief-weighted runs. That is
        expected and honest — those forwards are real accelerated work
        and belong in the ``ms / NN-eval`` denominator even though
        they are not search-budget nodes.
        """
        return max(0, self.nodes - self.nn_eval_states)

    @property
    def states_per_call(self) -> float:
        """Mean batch fill: ``nn_eval_states / nn_forward_calls``.

        Diagnostic only — explains *why* a regime is fast/slow (a
        microsecond batched forward dominated by per-call overhead is
        the documented SHM-loses-at-small-trunk mechanism), but it is
        not the comparison unit.
        """
        if self.nn_forward_calls <= 0:
            return 0.0
        return self.nn_eval_states / self.nn_forward_calls

    @property
    def nn_eval_fraction(self) -> float:
        """Fraction of search nodes that hit the network
        (``nn_eval_states / nodes``). Lower ⇒ more terminal-heavy or
        more cache-effective search."""
        if self.nodes <= 0:
            return 0.0
        return self.nn_eval_states / self.nodes

    def __sub__(self, other: "EvalCounters") -> "EvalCounters":
        """Delta between two snapshots (``after - before``). Lets a
        harness bracket without a global reset when nesting."""
        return EvalCounters(
            nodes=self.nodes - other.nodes,
            nn_eval_states=self.nn_eval_states - other.nn_eval_states,
            nn_forward_calls=(
                self.nn_forward_calls - other.nn_forward_calls
            ),
        )


def snapshot() -> EvalCounters:
    """Return an immutable snapshot of the current counters."""
    return EvalCounters(
        nodes=_nodes,
        nn_eval_states=_nn_eval_states,
        nn_forward_calls=_nn_forward_calls,
    )
