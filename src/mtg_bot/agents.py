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

    def choose_target(
        self,
        state: "GameState",
        player_id: int,
        legal_targets: list[tuple[str, int]],
    ) -> tuple[str, int] | None:
        """Pick one of the legal (kind, id) targets, or None to decline."""
        raise NotImplementedError

    def choose_discard(
        self,
        state: "GameState",
        player_id: int,
        hand_card_ids: list[int],
    ) -> int:
        """Pick which of the player's hand cards to discard."""
        raise NotImplementedError

    def choose_surveil(
        self,
        state: "GameState",
        player_id: int,
        top_card_id: int,
    ) -> bool:
        """When surveilling, decide for the top card: True = mill it to the
        graveyard, False = leave it on top of the library."""
        raise NotImplementedError

    def choose_sacrifice(
        self,
        state: "GameState",
        player_id: int,
        legal_object_ids: list[int],
    ) -> int:
        """When forced to sacrifice, pick which battlefield object to sac.

        Consumers (e.g., "each opponent sacrifices a nontoken creature")
        pass the list of legal IDs they want the player to pick from.
        """
        raise NotImplementedError

    def choose_mode(
        self,
        state: "GameState",
        player_id: int,
        mode_descriptions: list[str],
    ) -> int:
        """For modal "choose one" spells/abilities, return the index of the
        chosen mode. Default: 0 (first mode)."""
        raise NotImplementedError

    def choose_pay_shock_life(
        self,
        state: "GameState",
        player_id: int,
        life_cost: int,
    ) -> bool:
        """When playing a shock land, decide: True = pay ``life_cost``
        life and enter untapped; False = enter tapped."""
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

    def choose_target(self, state, player_id, legal_targets):
        if not legal_targets:
            return None
        return self.rng.choice(legal_targets)

    def choose_discard(self, state, player_id, hand_card_ids):
        return self.rng.choice(hand_card_ids)

    def choose_surveil(self, state, player_id, top_card_id):
        # Coin flip: mill or keep. Good enough for a random-action baseline.
        return self.rng.random() < 0.5

    def choose_sacrifice(self, state, player_id, legal_object_ids):
        return self.rng.choice(legal_object_ids)

    def choose_mode(self, state, player_id, mode_descriptions):
        return self.rng.randrange(len(mode_descriptions))

    def choose_pay_shock_life(self, state, player_id, life_cost):
        # Simple heuristic: pay the life if we have healthy buffer,
        # otherwise enter tapped.
        return state.player_by_id(player_id).life > life_cost + 3
