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
    # "Attack with everything, block with nothing" — aggressive and
    # wrong in lots of positions, but deterministic and makes games
    # terminate. Combat is exposed as search decisions by default
    # (``MtgGameStateAdapter(..., expose_combat_decisions=True)``)
    # so MCTS branches per-creature on attack/block; these methods
    # only fire on the auto-resolve path (callers that opt out of
    # combat exposure) and during rollouts past the search depth.
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

    def choose_permanent_to_tap(self, state, player_id, legal_object_ids):
        # Tap the first listed untapped permanent (deterministic for
        # search; tactical policy can override for smarter selection).
        return legal_object_ids[0] if legal_object_ids else None

    def choose_mode(self, state, player_id, mode_descriptions):
        return 0

    def choose_modes(self, state, player_id, mode_descriptions):
        # Deterministic: first mode only. Matches choose_mode's
        # first-legal default.
        return [0]

    def choose_pay_shock_life(self, state, player_id, life_cost):
        # Decline paying life — enter tapped. Conservative.
        return False

    def choose_card_from_opponent_hand(self, state, player_id, opponent_hand_ids):
        return opponent_hand_ids[0] if opponent_hand_ids else 0

    def choose_card_from_library(self, state, player_id, option_ids):
        return option_ids[0] if option_ids else None

    def choose_card_from_hand(self, state, player_id, option_ids):
        # Take the first qualifying card — deterministic for search.
        # Preserves the "may → take the action" default.
        return option_ids[0] if option_ids else None

    def choose_x(self, state, player_id, card_name, upper_bound):
        # Commit all available mana to X — same default RandomAgent
        # uses; matches the "use your resources" heuristic.
        return upper_bound

    def choose_devour_lands(self, state, player_id, land_ids):
        return []

    def choose_mana_color(self, state, player_id, options):
        # First option (W under the standard ordering, or first sorted
        # element when caller pre-sorts). Deterministic for search;
        # future tactical policy can pick by analysing the cards in
        # hand or pending costs on the stack.
        return options[0]

    def choose_yes_no(self, state, player_id, prompt):
        # Take the optional action by default — preserves the existing
        # "may → always yes" behavior that many cards in the codebase
        # rely on. Deterministic for MCTS.
        return True

    def choose_legend_keep(self, state, player_id, legend_object_ids):
        # Legend rule SBA: keep the first legendary in the group.
        # Deterministic for search; tactical policy can override to
        # pick the strongest one.
        return legend_object_ids[0]

    def choose_replacement_order(
        self, candidates, state, affected_player_id,
    ):
        # CR 616.1 — when ≥2 replacement effects apply to the same
        # event, pick the application order. Deterministic identity
        # ordering for search: apply in the order the dispatcher
        # collected them (sorted by source object id). Tactical
        # policies can override to favor Prevent first, etc.
        return tuple(range(len(candidates)))

    def choose_mulligan(self, state, player_id, hand, mulls_taken):
        # Extreme-only heuristic: mulligan if 0 lands or all lands;
        # keep everything else. The London rule still bottoms a
        # card per mulligan taken, so the policy stays cost-
        # disciplined. Pre-game decisions aren't search-driven so
        # a deterministic closed-form heuristic is fine; smarter
        # agents (NN-trained on mulligan supervision) override.
        from mtg_bot.mulligan import heuristic_mulligan_decision
        return heuristic_mulligan_decision(hand, mulls_taken)

    def choose_bottom(self, state, player_id, hand, n):
        # Bottom the highest-mana-value non-land cards first
        # (slowest to deploy, worst tempo if drawn). Deterministic
        # — two clones of the same state with the same agent
        # produce the same library order, important for search.
        from mtg_bot.mulligan import heuristic_bottom_choice
        return heuristic_bottom_choice(hand, n)

    def choose_convoke_creatures(
        self, state, player_id, candidates,
        remaining_generic, remaining_colored,
    ):
        # Convoke: tap as many candidates as the cost needs. The
        # caller bounds-checks. Deterministic ordering for search.
        return list(candidates)

    def choose_sac_for_mana(
        self, state, player_id, candidates,
        remaining_generic, remaining_colored,
    ):
        # Sac-for-mana: offer every candidate in the order the engine
        # surfaced them. Caller stops as soon as the cost is payable,
        # so Treasures don't get blown up unnecessarily. Deterministic
        # for search.
        return [oid for oid, _produces in candidates]
