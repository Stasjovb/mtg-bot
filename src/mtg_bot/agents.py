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

    def choose_permanent_to_tap(
        self,
        state: "GameState",
        player_id: int,
        legal_object_ids: list[int],
    ) -> int | None:
        """For "Tap an untapped permanent you control" activation costs
        (Gene Pollinator). Pick which battlefield object to tap as cost
        payment. ``legal_object_ids`` are the untapped permanents the
        player controls (source excluded). Return None to fall back to
        the first option.

        Default: returns the first id. Concrete agents override for
        smarter selection.
        """
        return legal_object_ids[0] if legal_object_ids else None

    def choose_mode(
        self,
        state: "GameState",
        player_id: int,
        mode_descriptions: list[str],
    ) -> int:
        """For modal "choose one" spells/abilities, return the index of the
        chosen mode. Default: 0 (first mode)."""
        raise NotImplementedError

    def choose_modes(
        self,
        state: "GameState",
        player_id: int,
        mode_descriptions: list[str],
    ) -> list[int]:
        """For modal "choose one or both" (or "choose any number") spells
        and abilities, return an ordered list of mode indices to resolve.
        The list order is the resolution order (CR 700.2d).

        Base implementation returns ``[0]`` — the first mode only —
        which preserves backwards-compat for any agent that hasn't
        opted into multi-mode picks."""
        return [0]

    def choose_pay_shock_life(
        self,
        state: "GameState",
        player_id: int,
        life_cost: int,
    ) -> bool:
        """When playing a shock land, decide: True = pay ``life_cost``
        life and enter untapped; False = enter tapped."""
        raise NotImplementedError

    def choose_card_from_opponent_hand(
        self,
        state: "GameState",
        player_id: int,
        opponent_hand_ids: list[int],
    ) -> int:
        """For directed-discard effects (Temporal Intervention) where
        the CASTER chooses which card the opponent reveals/discards.
        Must return an id from the given list."""
        raise NotImplementedError

    def choose_card_from_library(
        self,
        state: "GameState",
        player_id: int,
        option_ids: list[int],
    ) -> int | None:
        """For tutor effects: pick which card from a filtered list of
        the player's own library to fetch. Return None to decline
        fetching ("search... you may reveal a creature card"); return
        an id from ``option_ids`` to fetch that specific card."""
        raise NotImplementedError

    def choose_x(
        self,
        state: "GameState",
        player_id: int,
        card_name: str,
        upper_bound: int,
    ) -> int:
        """For spells or abilities with {X} in their cost, pick a value
        for X at cast time. ``upper_bound`` is the maximum X that the
        player can afford with currently-available mana. Must return
        an int in ``[0, upper_bound]``."""
        raise NotImplementedError

    def choose_devour_lands(
        self,
        state: "GameState",
        player_id: int,
        land_ids: list[int],
    ) -> list[int]:
        """For Devour land N: pick any subset of ``land_ids`` to
        sacrifice. Returning an empty list declines. Returned ids must
        be a subset of ``land_ids``; others are ignored."""
        raise NotImplementedError

    def choose_mana_color(
        self,
        state: "GameState",
        player_id: int,
        options: list[str],
    ) -> str:
        """For mana abilities like Lotus Field's "Add three mana of any
        one color" or Reflecting Pool's "Add one mana of any type that
        a land you control could produce", pick exactly one color from
        ``options`` (e.g. ``["W", "U", "B", "R", "G"]``, or a constrained
        subset). Default returns the first option; concrete agents
        override. Implementations must return a value from ``options``;
        ``options`` is guaranteed non-empty by the caller."""
        return options[0]

    def choose_yes_no(
        self,
        state: "GameState",
        player_id: int,
        prompt: str,
    ) -> bool:
        """Generic yes/no decision point — for "may" abilities where the
        controller chooses whether to take the optional action.

        Default: ``True`` (take the action). Many cards in the codebase
        encode "may → always yes" simplifications and depend on this
        baseline; only cards that explicitly call this callback give
        the controller a real choice. Override on a per-agent basis to
        get smarter behavior, or pass an override-equipped agent in
        tests to exercise the no-branch."""
        return True

    def choose_convoke_creatures(
        self,
        state: "GameState",
        player_id: int,
        candidates: list[int],
        remaining_generic: int,
        remaining_colored: list[tuple[str, int]],
    ) -> list[int]:
        """Convoke (CR 702.51) cost-payment helper. The caster picks
        which of their own untapped creatures to tap toward the
        spell's cost. Each creature pays {1} or one mana of its
        color (engine picks the better assignment per remaining
        cost).

        ``candidates`` is the list of legal creature object ids
        (untapped, controlled by ``player_id``,
        ``is_creature_now``). ``remaining_generic`` and
        ``remaining_colored`` describe the post-cost-reduction
        cost yet to be paid AFTER any pool / land contribution
        already accounted for. Caller assigns each tapped
        creature to a slot greedily.

        Return a list of object ids to tap, in order. Returning
        more than needed is harmless — extras are ignored. Return
        an empty list to skip convoke.

        Default: convoke ALL candidates, capped at the number
        actually needed by the cost (caller bounds-checks).
        Concrete agents can override for smarter selection (e.g.,
        prefer creatures with no abilities, or summoning-sick
        creatures since convoke doesn't require haste).
        """
        return list(candidates)

    def choose_sac_for_mana(
        self,
        state: "GameState",
        player_id: int,
        candidates: list[tuple[int, tuple[tuple[str, int], ...]]],
        remaining_generic: int,
        remaining_colored: list[tuple[str, int]],
    ) -> list[int]:
        """CR 605 + 601.2g: pick which sac-for-mana mana abilities to
        activate during a spell's cost-payment step. Each candidate is
        ``(object_id, produces)`` where ``produces`` is the source's
        per-activation mana output (tuple of ``(color, count)``).

        ``remaining_generic`` and ``remaining_colored`` describe the
        post-reduction cost not yet covered by the pool or lands. The
        caller activates the returned sources in order while the cost
        remains unpayable; once payable the rest are left alone (so
        Treasures aren't blown up unless they're actually needed).

        Default: return every candidate id in the order presented —
        matches the engine's auto-greedy behavior. Override for smarter
        selection (e.g., prefer Treasures whose color the cost
        actually needs, defer "any"-color sources, etc.).
        """
        return [oid for oid, _produces in candidates]

    def choose_legend_keep(
        self,
        state: "GameState",
        player_id: int,
        legend_object_ids: list[int],
    ) -> int:
        """Legend-rule SBA decision (CR 704.5j): when ``player_id``
        controls multiple legendary permanents with the same name,
        pick which one to KEEP. The rest go to their owners'
        graveyards.

        Default: returns the first id (deterministic). Concrete
        agents override for smarter selection (e.g., pick the most
        valuable one). Implementations must return a value in
        ``legend_object_ids``; the list is guaranteed to have at
        least 2 entries (otherwise no legend rule fires).
        """
        return legend_object_ids[0]

    def choose_replacement_order(
        self,
        candidates: list,
        state: "GameState",
        affected_player_id: int,
    ) -> tuple[int, ...]:
        """CR 616.1 — when multiple replacement effects apply to the
        same event, the affected player chooses the order. ``candidates``
        is the ordered list of :class:`mtg_bot.effects.modifiers
        .ReplacementEffect` instances (the dispatcher pre-collected
        them); return a tuple of indices specifying the application
        order.

        Default: identity ordering — apply in the order the
        dispatcher collected them (which is itself sorted by source
        object id for determinism). Concrete agents override when a
        smarter ordering matters (e.g., apply Prevent first to short-
        circuit subsequent Multiply transforms when that's beneficial
        to the affected player). Implementations must return a tuple
        of indices in ``range(len(candidates))``; missing or out-of-
        range entries are filled in by the dispatcher's sanitisation
        pass.
        """
        return tuple(range(len(candidates)))


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

    def choose_permanent_to_tap(self, state, player_id, legal_object_ids):
        if not legal_object_ids:
            return None
        return self.rng.choice(legal_object_ids)

    def choose_mode(self, state, player_id, mode_descriptions):
        return self.rng.randrange(len(mode_descriptions))

    def choose_modes(self, state, player_id, mode_descriptions):
        # Pick a random non-empty subset of modes in a random order.
        n = len(mode_descriptions)
        if n == 0:
            return []
        # Each mode included independently with p=0.5; if the subset is
        # empty, force-include one mode (modal spells always resolve at
        # least one).
        picked = [i for i in range(n) if self.rng.random() < 0.5]
        if not picked:
            picked = [self.rng.randrange(n)]
        self.rng.shuffle(picked)
        return picked

    def choose_pay_shock_life(self, state, player_id, life_cost):
        # Simple heuristic: pay the life if we have healthy buffer,
        # otherwise enter tapped.
        return state.player_by_id(player_id).life > life_cost + 3

    def choose_card_from_opponent_hand(self, state, player_id, opponent_hand_ids):
        return self.rng.choice(opponent_hand_ids)

    def choose_card_from_library(self, state, player_id, option_ids):
        if not option_ids:
            return None
        return self.rng.choice(option_ids)

    def choose_x(self, state, player_id, card_name, upper_bound):
        # Commit all available mana to X. Maximises spell impact, which is
        # almost always correct for a random-action baseline — saving mana
        # rarely pays off when the agent picks moves uniformly at random.
        return upper_bound

    def choose_devour_lands(self, state, player_id, land_ids):
        # Random-baseline: never sacrifice lands for Devour. Trading
        # lands for +1/+1 counters is usually a losing trade and a
        # uniform random agent has no way to evaluate the tradeoff.
        return []

    def choose_mana_color(self, state, player_id, options):
        return self.rng.choice(options)

    def choose_yes_no(self, state, player_id, prompt):
        # Coin flip — true to the random-action baseline.
        return self.rng.random() < 0.5

    def choose_sac_for_mana(
        self, state, player_id, candidates,
        remaining_generic, remaining_colored,
    ):
        # Random shuffle so different runs explore different sac
        # orderings; the engine still stops as soon as the cost is
        # payable, so unnecessary sacrifices are avoided regardless
        # of the order returned.
        ids = [oid for oid, _produces in candidates]
        self.rng.shuffle(ids)
        return ids
