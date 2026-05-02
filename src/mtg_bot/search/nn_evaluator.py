"""Neural-network evaluator. Phase C of the learned-evaluator work.

Wraps a small PyTorch MLP in the ``Evaluator`` interface so MCTS can
call it like any other evaluator. Phase D adds the training loop that
fits the weights from self-play data; this PR ships the architecture,
the inference path, and load/save plumbing — no training code.

Architecture: 51-dim input (FEATURE_DIM from features.py) → 128 →
128 → 64 → 1, ReLU activations between, ``tanh`` on the output to
clamp into [-1, 1] (the Evaluator contract). ~25k parameters.
Tiny by NN standards; trains in seconds on CPU. Easy to scale up
later — change ``HIDDEN_SIZES`` and retrain.

Inference path:

1. ``extract_features(state, viewer_id)`` → np.float32[51]
2. Convert to torch tensor + add batch dimension
3. ``model.forward()`` → scalar
4. Return as Python float

CPU-only here. Phase D adds CUDA for *training* on the 5090; for
*inference* during MCTS, the per-call Python↔CUDA round-trip
overhead is much higher than running a tiny MLP on CPU.

Batched inference: ``batch_evaluate(states, player_id)`` stacks
the feature vectors into a single ``(B, FEATURE_DIM)`` tensor and
runs one forward pass — the path that lets MCTS amortize the
Python↔C overhead across the batch. MCTS opts in via its
``batch_size`` knob; ``batch_size=1`` falls through to the
per-state path. CUDA would also pay off here once batched
inference is the dominant rollout cost.

Save / load uses ``torch.save(model.state_dict(), path)`` — standard
PyTorch convention. Old saved weights become incompatible if
``FEATURE_DIM`` changes (new features) or ``HIDDEN_SIZES`` changes
(new architecture). That's the cost of fixed-shape networks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

import numpy as np
import torch
import torch.nn as nn

from mtg_bot.features import FEATURE_DIM, extract_features
from mtg_bot.game import GameState as EngineGameState
from mtg_bot.search.evaluator import Evaluator
from mtg_bot.search.protocol import GameState, PlayerID

# Hidden-layer widths. 3 hidden layers, ReLU between. ~25k params at
# these sizes (51 → 128 → 128 → 64 → 1).
#
# History: the 2026-05-02 architecture-scaling experiment bumped
# this to (512, 512, 256) ≈ 420k params (commit fd095a1) testing
# the hypothesis "v2 didn't beat heuristic because the 25k network
# was capacity-bound." v3 (the 420k network trained on the same
# 398k samples) was strictly WORSE: 23-77 vs heuristic vs v2's
# 45-55 — capacity wasn't the constraint. The bigger network
# fit the heuristic-driven training distribution tighter and
# generalized worse to the MCTS-driven evaluation distribution,
# and value-only training without policy supervision can't
# direct search any more than the heuristic does.
#
# The actual gating items are A4 (policy head — the network
# learns to predict MCTS visit-count distributions per state, not
# just outcomes) and A5 (PUCT MCTS — uses the policy as a search
# prior). Once those land we can re-explore capacity with a
# richer training signal. Until then, the 25k arch is the
# known-OK baseline.
HIDDEN_SIZES: tuple[int, ...] = (128, 128, 64)


class _ValueMLP(nn.Module):
    """The actual network. FEATURE_DIM → HIDDEN_SIZES... → 1, with
    ReLU between hidden layers and tanh on output.

    Defined as a separate ``nn.Module`` so save/load uses the
    standard ``state_dict`` pattern (not pickling the whole
    NNEvaluator wrapper, which would make weights non-portable
    across small refactors).
    """

    def __init__(
        self,
        input_dim: int = FEATURE_DIM,
        hidden_sizes: tuple[int, ...] = HIDDEN_SIZES,
    ) -> None:
        super().__init__()
        layers: list[nn.Module] = []
        prev = input_dim
        for size in hidden_sizes:
            layers.append(nn.Linear(prev, size))
            layers.append(nn.ReLU())
            prev = size
        # Final value head: single scalar, tanh-squashed to [-1, 1].
        layers.append(nn.Linear(prev, 1))
        layers.append(nn.Tanh())
        self.net = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class NNEvaluator(Evaluator):
    """Wraps a ``_ValueMLP`` in the ``Evaluator`` interface.

    Construction:
    - No args → fresh random-init network. Useful for tests and
      for the first iteration of training (which initializes from
      random and then trains via self-play).
    - ``weights_path`` → load a saved ``state_dict`` from disk.
      The architecture is fixed (FEATURE_DIM input, HIDDEN_SIZES
      hidden), so saved weights are tied to those constants;
      bumping either invalidates old saves.

    Inference is single-state per call (one tensor, one forward pass)
    on CPU. ``torch.no_grad()`` and ``model.eval()`` skip gradient
    tracking and any train-mode behaviors (dropout, batchnorm) for
    speed. Output is converted back to a Python float because the
    Evaluator contract returns ``float``, not tensor.
    """

    def __init__(
        self,
        weights_path: Optional[Path] = None,
        *,
        device: str = "cpu",
    ) -> None:
        self.device = torch.device(device)
        self.model = _ValueMLP()
        if weights_path is not None:
            state_dict = torch.load(
                weights_path, map_location=self.device,
                weights_only=True,
            )
            self.model.load_state_dict(state_dict)
        self.model.to(self.device)
        self.model.eval()

    def _evaluate_nonterminal(
        self, state: GameState, player_id: PlayerID,
    ) -> float:
        engine = self._engine_state(state)
        features = extract_features(engine, player_id)
        with torch.no_grad():
            x = torch.from_numpy(features).unsqueeze(0).to(self.device)
            value = self.model(x).item()
        return value

    def batch_evaluate(
        self, states: Sequence[GameState], player_id: PlayerID,
    ) -> list[float]:
        """Single forward pass over a stacked batch of feature
        vectors. Captures the 5–20× win the per-state path forfeits
        to Python↔C round-trip overhead — at batch size 1 there's
        almost no compute being done; at batch 32 the same wall-
        clock buys 32 evaluations.

        Terminal states short-circuit to ±1/0 (matches the
        per-state path) without touching the network. Non-terminal
        states are extracted, stacked into a ``(B, FEATURE_DIM)``
        tensor, run through ``self.model``, and unpacked. The
        returned list preserves input order and includes the
        terminal short-circuits intermixed with NN-scored values.
        """
        if not states:
            return []
        # Partition into (index, kind, value-or-engine-state) so we
        # can run the NN only over the non-terminal subset and
        # stitch the terminals back in by index.
        terminal_results: list[tuple[int, float]] = []
        nonterminal_indices: list[int] = []
        nonterminal_features: list[np.ndarray] = []
        for i, s in enumerate(states):
            if s.is_terminal():
                winner = s.winner()
                if winner is None:
                    terminal_results.append((i, 0.0))
                else:
                    terminal_results.append(
                        (i, 1.0 if winner == player_id else -1.0)
                    )
                continue
            engine = self._engine_state(s)
            nonterminal_indices.append(i)
            nonterminal_features.append(
                extract_features(engine, player_id)
            )

        out: list[float] = [0.0] * len(states)
        for i, v in terminal_results:
            out[i] = v
        if nonterminal_features:
            stacked = np.stack(nonterminal_features, axis=0)
            with torch.no_grad():
                x = torch.from_numpy(stacked).to(self.device)
                # ``self.model(x)`` returns ``(B, 1)``; squeeze the
                # value dim and pull values back to the host as a
                # Python list.
                values = self.model(x).squeeze(-1).cpu().tolist()
            for idx, v in zip(nonterminal_indices, values):
                out[idx] = v
        return out

    def save(self, path: Path) -> None:
        """Persist ``state_dict`` to disk. Standard PyTorch convention."""
        torch.save(self.model.state_dict(), path)

    @staticmethod
    def _engine_state(state: GameState) -> EngineGameState:
        """Reach through the adapter (or accept a raw engine state
        directly, mirroring MtgHeuristicEvaluator's helper)."""
        engine = getattr(state, "engine_state", None)
        if engine is not None:
            return engine
        return state  # assume already an EngineGameState
