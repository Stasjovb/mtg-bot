"""Default tactical-policy Agent used by ``MtgGameStateAdapter``.

MCTS decides top-level priority actions via search. Everything else —
mid-resolution callbacks (choose_target during spell/ability resolve,
choose_sacrifice, X-value picks, surveil, ward-discard choice) AND
combat declarations (declare_attackers, declare_blockers) — is routed
through a default policy. The adapter installs this agent on every
player so the engine's resolve-path callbacks have somewhere to go.

The policy is **deterministic** (first-legal, conservative defaults).
Deterministic matters a lot for search: two clones of the same state
that apply the same sequence of top-level decisions MUST reach
identical positions, so MCTS's value estimates converge. A RandomAgent
would break that unless seeded from ``state.rng`` — which is doable
but deferred. First-legal is boring but predictable.

Future waves replace this with something smarter (an evaluator-
driven tactical policy, or expose mid-resolution decisions as search
nodes themselves).
"""

from __future__ import annotations

from mtg_bot.actions import Action, PassPriority
from mtg_bot.agents import Agent


class DefaultTacticalAgent(Agent):
    """Deterministic first-legal / conservative-default policy.

    See module docstring for why this shape. All methods MUST be
    deterministic given state — that's the whole contract.
    """

    name: str = "default_tactical"

    # --- Top-level decision paths ------------------------------------
    # The adapter drives the priority loop itself, so ``choose_action``
    # normally isn't called on this agent. We provide a safe default
    # anyway — pass if possible, otherwise the first legal action —
    # so any unexpected caller (e.g., a test driving priority_loop
    # directly against an adapter-managed state) doesn't crash.
    def choose_action(self, state, player_id, legal):
        for action in legal:
            if isinstance(action, PassPriority):
                return action
        return legal[0] if legal else PassPriority()

    # --- Combat declarations -----------------------------------------
    # Ship V1 with "attack with everything, block with nothing". This
    # is aggressive and wrong in lots of positions, but it's
    # deterministic and makes games terminate. Wave 2 of the adapter
    # will expose combat declarations as search decisions.
    def declare_attackers(self, state, player_id, eligible):
        return [o.id for o in eligible]

    def declare_blockers(self, state, player_id, eligible, attackers):
        return {}

    # --- Mid-resolution callbacks ------------------------------------

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_discard(self, state, player_id, hand_card_ids):
        return hand_card_ids[0] if hand_card_ids else 0

    def choose_surveil(self, state, player_id, top_card_id):
        # False = keep on top. The safer default when we don't know
        # what the top card is worth.
        return False

    def choose_sacrifice(self, state, player_id, legal_object_ids):
        return legal_object_ids[0] if legal_object_ids else 0

    def choose_mode(self, state, player_id, mode_descriptions):
        return 0

    def choose_pay_shock_life(self, state, player_id, life_cost):
        # Decline paying life — enter tapped. Conservative.
        return False

    def choose_card_from_opponent_hand(self, state, player_id, opponent_hand_ids):
        return opponent_hand_ids[0] if opponent_hand_ids else 0

    def choose_card_from_library(self, state, player_id, option_ids):
        return option_ids[0] if option_ids else None

    def choose_x(self, state, player_id, card_name, upper_bound):
        # Commit all available mana to X — same default RandomAgent
        # uses; matches the "use your resources" heuristic.
        return upper_bound

    def choose_devour_lands(self, state, player_id, land_ids):
        return []
