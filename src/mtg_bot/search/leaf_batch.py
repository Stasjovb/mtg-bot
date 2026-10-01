"""Default MCTS leaf batch size for the production CPU search path.

Measured 2026-10-01 (ladder, 200 games per pair vs the batch-1
heuristic; ``docs/STRENGTH_LADDER.md``): batched leaf evaluation with
virtual loss at 32 leaves per wave costs the *same evaluator* about 8
points at nodes 100-200 (heuristic+b32: 41.9 % / 41.5 %) and ~3 at
nodes 400 (46.7 %), while on CPU it saves ~3 % wall (v22 b32 2223 s vs
b1 2297 s per 200 games at nodes 200). Every NN seat in the s2 lineage
(self-play, arenas, ladder) ran at 32 against a batch-1 heuristic,
which is where the 36-48 % "plateau" came from; at batch 1 v22 beats
the heuristic (52-53 %).

Batching exists for GPU throughput (``--nn-device cuda`` workers), so
``NNPimcConfig.batch_size`` keeps its own default for callers that
opt in; the production call sites below import this constant instead.
"""
from __future__ import annotations

SEARCH_LEAF_BATCH_SIZE: int = 1
