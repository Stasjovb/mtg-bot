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
overhead is much higher than running a tiny MLP on CPU. If we ever
want batched evaluation across MCTS leaves, that's a Phase E
optimization (restructure the search to collect leaves into a batch
before scoring) where CUDA would actually pay off.

Save / load uses ``torch.save(model.state_dict(), path)`` — standard
PyTorch convention. Old saved weights become incompatible if
``FEATURE_DIM`` changes (new features) or ``HIDDEN_SIZES`` changes
(new architecture). That's the cost of fixed-shape networks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import torch
import torch.nn as nn

from mtg_bot.features import FEATURE_DIM, extract_features
from mtg_bot.game import GameState as EngineGameState
from mtg_bot.search.evaluator import Evaluator
from mtg_bot.search.protocol import GameState, PlayerID

# Hidden-layer widths. 3 hidden layers, ReLU between. ~25k params at
# the default sizes. Make wider/deeper later if we hit a capacity
# ceiling — but a wider network needs more training data, so don't
# scale up speculatively.
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
