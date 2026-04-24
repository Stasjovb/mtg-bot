"""Search-side decision types for factored combat.

When ``MtgGameStateAdapter`` is constructed with
``expose_combat_decisions=True``, declare-attackers and
declare-blockers are no longer single atomic decisions made by the
tactical policy. Instead the adapter walks each eligible attacker
(then each eligible blocker) one at a time and asks search to choose
between just a handful of options per step.

Why factored, not atomic:

- An atomic ``declare_attackers`` decision over N eligible attackers
  has 2^N branches. Atomic ``declare_blockers`` is even worse —
  approximately ``(|attackers| + 1)^|blockers|``.
- Per-attacker: 2 branches each (attack / don't).
  Per-blocker: ``|attackers| + 1`` branches each (block which, or
  none).
- Total leaf count is the same in the limit, but tree depth grows
  while branching factor stays small. MCTS handles deep narrow trees
  natively; UCB1 doesn't degrade with depth, only with branching.
- Combined with progressive widening, only a few sub-branches at
  each level get explored — the search's effective combat-tree
  cost is much smaller than the worst-case enumeration.

Tradeoff: per-* factorization breaks coupling between sub-decisions.
"Block A with B" might only be good if "C also blocks D" — the
factored search has to discover that coupling through MCTS visits
rather than seeing it in one shot. With enough budget this is fine;
with very tight budgets the factored search may prefer locally-good
but jointly-bad combat patterns.

These decisions are search-only — they never reach the engine's
``apply_action``. The adapter recognizes them, accumulates them, and
emits a single engine-level ``DeclareAttackers`` / ``DeclareBlockers``
once all per-creature decisions have been collected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AttackerDecision:
    """Should ``attacker_id`` attack this combat?

    Issued once per eligible attacker (in the order the adapter
    enumerates them). Hashable for transposition tables / MCTS
    bookkeeping. Compared by value.
    """

    attacker_id: int
    attack: bool


@dataclass(frozen=True)
class BlockerDecision:
    """Which attacker (if any) should ``blocker_id`` block?

    ``attacker_id is None`` means "don't block." Otherwise the value
    must be one of the currently-attacking creatures' ids.

    Issued once per eligible blocker (in the order the adapter
    enumerates them). Note that we currently don't expose
    "block A with B AND block A with C" as a separate sub-decision —
    multiple blockers can block the same attacker by issuing
    ``BlockerDecision(blocker_id=B, attacker_id=A)`` and
    ``BlockerDecision(blocker_id=C, attacker_id=A)`` in sequence.
    """

    blocker_id: int
    attacker_id: Optional[int]
