"""Agent interface + a random-legal-action agent."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mtg_bot.actions import Action, PassPriority

if TYPE_CHECKING:
    from mtg_bot.game import GameObject, GameState


class Agent:
    """An entity that decides what a player does at each decision point."""

    name: str = "agent"

    def choose_action(
        self, state: "GameState", player_id: int, legal: list[Action]
    ) -> Action:
        raise NotImplementedError

    def declare_attackers(
        self, state: "GameState", player_id: int, eligible: list["GameObject"]
    ) -> list[int]:
        raise NotImplementedError

    def declare_blockers(
        self,
        state: "GameState",
        player_id: int,
        eligible: list["GameObject"],
        attackers: list["GameObject"],
    ) -> dict[int, int]:
        raise NotImplementedError


@dataclass
class RandomAgent(Agent):
    """Picks uniformly among legal non-pass actions when any exist, else passes.

    Biased away from pass so games actually progress — a uniform random agent
    would almost always pass (pass is legal every decision point).
    """

    name: str = "random"
    rng: random.Random = field(default_factory=random.Random)
    block_probability: float = 0.6

    def choose_action(self, state, player_id, legal):
        non_pass = [a for a in legal if not isinstance(a, PassPriority)]
        if non_pass:
            return self.rng.choice(non_pass)
        return PassPriority()

    def declare_attackers(self, state, player_id, eligible):
        return [o.id for o in eligible]

    def declare_blockers(self, state, player_id, eligible, attackers):
        if not attackers:
            return {}
        assignments: dict[int, int] = {}
        for b in eligible:
            if self.rng.random() < self.block_probability:
                assignments[b.id] = self.rng.choice(attackers).id
        return assignments
