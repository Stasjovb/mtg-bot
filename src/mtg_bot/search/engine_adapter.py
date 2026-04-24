"""Adapter bridging the real MTG engine (``mtg_bot.game.GameState``)
to the search-framework ``GameState`` protocol.

This is the one object that touches both sides of the wall. Search
algorithms (MCTS etc.) call its abstract protocol methods; internally
it drives the real engine one decision at a time.

Design choices for this first cut (documented so the next iteration
knows what it's stepping into):

- **Deterministic tactical policy.** Every player's ``agent`` is
  replaced with ``DefaultTacticalAgent`` (first-legal / conservative
  defaults). Mid-resolution callbacks (choose_target, choose_x,
  choose_sacrifice, etc.) and combat declarations (declare_attackers,
  declare_blockers) all go through this policy rather than being
  exposed as search nodes. Same state + same sequence of top-level
  decisions → same resulting position, which is what MCTS needs.
- **Priority loop reimplemented here.** Rather than refactoring
  ``simulate.priority_loop`` to be pausable, the adapter runs its
  own priority-loop body in ``apply``. ``_pass_count`` lives on the
  adapter instance so it survives between ``apply()`` calls.
- **Non-priority steps auto-advance.** Between the caller's
  decisions, ``_advance_to_next_decision`` runs ``UNTAP`` /
  ``CLEANUP`` / step transitions / pre-priority triggers so the
  caller sees one decision moment after another instead of needing
  to manage turn structure.
- **Chance nodes not modeled.** Card draw uses the current library
  order deterministically. Full determinization — sampling possible
  library orderings for hidden-information search — is a later
  wave.
- **Combat not exposed.** ``declare_attackers`` / ``declare_blockers``
  are handled by the tactical policy. Exposing them as search
  decisions (one node per attacker subset, one per block mapping)
  blows up the branching factor and needs its own design pass.

What IS exposed to search: priority-action choices — casting spells,
activating abilities, playing lands, passing priority. That alone is
the bulk of strategic MTG decision-making.
"""

from __future__ import annotations

from typing import Optional

from mtg_bot.actions import (
    Action, DeclareAttackers, DeclareBlockers, PassPriority,
    apply_action, resolve_top_of_stack,
)
from mtg_bot.agents import Agent
from mtg_bot.combat import (
    clear_combat_state, eligible_attackers, eligible_blockers,
    resolve_combat_damage,
)
from mtg_bot.game import GameState as EngineGameState
from mtg_bot.legal import legal_actions
from mtg_bot.search.protocol import Decision, PlayerID
from mtg_bot.search.tactical import DefaultTacticalAgent
from mtg_bot.simulate import _advance_to_next_active_player, _next_alive
from mtg_bot.turn import (
    STEP_ORDER,
    STEPS_WITH_PRIORITY,
    Step,
    run_beginning_of_combat_triggers,
    run_beginning_of_end_step_triggers,
    run_beginning_of_upkeep_triggers,
    run_cleanup_step,
    run_delayed_end_step_triggers,
    run_draw_step,
    run_end_step_warp_exile,
    run_untap_step,
    state_based_actions,
)


class MtgGameStateAdapter:
    """Wrap a real-engine ``GameState`` so MCTS (and friends) can
    drive it through the ``mtg_bot.search.protocol.GameState``
    interface.

    Ownership: the adapter owns the wrapped state — in particular it
    rewrites every player's ``agent`` to the tactical policy on
    construction. If the caller later hands the state to something
    else (a simulate loop, say), they should not expect the original
    agents to still be installed.
    """

    def __init__(
        self,
        engine_state: EngineGameState,
        tactical_agent: Optional[Agent] = None,
    ) -> None:
        self._state = engine_state
        self._tactical = tactical_agent or DefaultTacticalAgent()
        for p in self._state.players:
            p.agent = self._tactical
        # Consecutive priority passes since the last non-pass or
        # stack resolution. Lives on the adapter (not the engine
        # state) because this is search-loop bookkeeping rather than
        # game state.
        self._pass_count = 0
        # Tracks whether the current step's pre-priority logic has
        # been run. False on fresh construction (nothing's run yet);
        # True once ``_enter_step`` has been invoked for the current
        # step; flipped back to False by ``_advance_to_next_step``.
        self._step_entered = False
        # Drive forward until we either hit a terminal state or a
        # priority moment where the caller must decide.
        self._advance_to_next_decision()

    # ---------------------------------------------------------------
    # search.GameState protocol
    # ---------------------------------------------------------------

    def clone(self) -> "MtgGameStateAdapter":
        c = MtgGameStateAdapter.__new__(MtgGameStateAdapter)
        c._state = self._state.clone()
        c._tactical = self._tactical
        # Agents are shared refs in GameState.clone; restate for
        # clarity and so a custom tactical passed to the original
        # still applies to the clone.
        for p in c._state.players:
            p.agent = c._tactical
        c._pass_count = self._pass_count
        c._step_entered = self._step_entered
        return c

    def active_player(self) -> PlayerID:
        # Only called at decision moments, which the adapter's own
        # advancement logic has ensured correspond to the state's
        # current priority holder.
        return self._state.priority_player_idx

    def legal_decisions(self) -> list[Decision]:
        if self._state.is_over():
            return []
        return list(legal_actions(self._state, self.active_player()))

    def chance_outcomes(self) -> list[tuple[Decision, float]]:
        # V1: no chance nodes. Determinization is a later wave.
        return []

    def is_terminal(self) -> bool:
        return self._state.is_over()

    def winner(self) -> Optional[PlayerID]:
        return self._state.winner_id

    def players(self) -> list[PlayerID]:
        return [p.id for p in self._state.players]

    def apply(self, decision: Decision) -> None:
        if self._state.is_over():
            raise ValueError("apply() called on terminal state")
        if not isinstance(decision, Action):
            raise TypeError(
                f"MtgGameStateAdapter expects an mtg_bot.actions.Action, "
                f"got {type(decision).__name__}: {decision!r}"
            )

        pid = self.active_player()

        if isinstance(decision, PassPriority):
            self._pass_count += 1
            alive = sum(
                1 for p in self._state.players if not p.has_lost
            )
            if self._pass_count >= alive:
                # Everyone passed in succession.
                self._pass_count = 0
                if self._state.stack:
                    resolve_top_of_stack(self._state)
                    state_based_actions(self._state)
                    if self._state.is_over():
                        return
                    # Priority returns to active player after each
                    # resolution. Still the same step.
                    self._state.priority_player_idx = _next_alive(
                        self._state, self._state.active_player_idx
                    )
                else:
                    # All passed with empty stack — step ends.
                    self._advance_to_next_step()
            else:
                # Pass to the next player.
                self._state.priority_player_idx = _next_alive(
                    self._state,
                    (pid + 1) % len(self._state.players),
                )
        else:
            apply_action(self._state, pid, decision)
            state_based_actions(self._state)
            if self._state.is_over():
                return
            self._pass_count = 0
            # Priority returns to active after any action.
            self._state.priority_player_idx = _next_alive(
                self._state, self._state.active_player_idx
            )

        self._advance_to_next_decision()

    # ---------------------------------------------------------------
    # Engine-driving internals
    # ---------------------------------------------------------------

    def _advance_to_next_decision(self) -> None:
        """From whatever state we're in, drive the engine forward
        until either the game ends or the next priority decision is
        pending. Idempotent: safe to call when we're already at a
        decision moment (the while-loop exits immediately in that
        case)."""
        while not self._state.is_over():
            if self._state.step is None:
                self._state.step = Step.UNTAP
                self._step_entered = False

            if not self._step_entered:
                self._enter_step(self._state.step)
                self._step_entered = True
                if self._state.is_over():
                    return

            if self._state.step in STEPS_WITH_PRIORITY:
                return
            # Non-priority step already fully handled by
            # _enter_step; move on.
            self._advance_to_next_step()

    def _advance_to_next_step(self) -> None:
        """Current step has concluded. Bump ``state.step`` to the
        next step (rolling over the turn after CLEANUP). Does NOT
        run the new step's pre-priority logic — that happens the
        next time _advance_to_next_decision is called."""
        current = self._state.step
        if current == Step.CLEANUP:
            self._state.turn_number += 1
            _advance_to_next_active_player(self._state)
            self._state.step = Step.UNTAP
        else:
            idx = STEP_ORDER.index(current)
            self._state.step = STEP_ORDER[idx + 1]
        self._step_entered = False

    def _enter_step(self, step: Step) -> None:
        """Run a step's pre-priority logic (or full logic for
        non-priority steps). Mirrors the step-specific dispatch
        inside ``simulate.run_step`` but stops just before
        ``priority_loop`` — the adapter drives priority itself.

        For priority steps: sets up ``priority_player_idx`` and
        ``_pass_count`` for the first decision of this step.
        """
        if step == Step.UNTAP:
            run_untap_step(self._state)
            return

        if step == Step.UPKEEP:
            run_beginning_of_upkeep_triggers(self._state)
            state_based_actions(self._state)

        elif step == Step.DRAW:
            # Starting player skips their very first draw step —
            # same rule run_step enforces.
            starting_player_first_draw = (
                self._state.turn_number == 1
                and self._state.active_player_idx == 0
            )
            if not starting_player_first_draw:
                run_draw_step(self._state)

        elif step == Step.BEGINNING_OF_COMBAT:
            run_beginning_of_combat_triggers(self._state)
            state_based_actions(self._state)

        elif step == Step.DECLARE_ATTACKERS:
            ap = self._state.active_player()
            eligible = eligible_attackers(self._state, ap.id)
            chosen = ap.agent.declare_attackers(
                self._state, ap.id, eligible
            )
            apply_action(
                self._state, ap.id,
                DeclareAttackers(attacker_ids=frozenset(chosen)),
            )

        elif step == Step.DECLARE_BLOCKERS:
            attackers = [
                o for o in self._state.battlefield if o.attacking
            ]
            if attackers:
                defender_idx = _next_alive(
                    self._state,
                    (self._state.active_player_idx + 1)
                    % len(self._state.players),
                )
                defender = self._state.players[defender_idx]
                eligible = eligible_blockers(self._state, defender.id)
                assignments = defender.agent.declare_blockers(
                    self._state, defender.id, eligible, attackers
                )
                apply_action(
                    self._state, defender.id,
                    DeclareBlockers(
                        assignments=tuple(assignments.items())
                    ),
                )

        elif step == Step.COMBAT_DAMAGE:
            if any(o.attacking for o in self._state.battlefield):
                defender_idx = _next_alive(
                    self._state,
                    (self._state.active_player_idx + 1)
                    % len(self._state.players),
                )
                resolve_combat_damage(
                    self._state, self._state.players[defender_idx].id
                )
                state_based_actions(self._state)

        elif step == Step.END:
            run_beginning_of_end_step_triggers(self._state)
            state_based_actions(self._state)
            if not self._state.is_over():
                run_delayed_end_step_triggers(self._state)
                state_based_actions(self._state)
            if not self._state.is_over():
                run_end_step_warp_exile(self._state)
                state_based_actions(self._state)

        elif step == Step.CLEANUP:
            run_cleanup_step(self._state)
            return

        if self._state.is_over():
            return

        # END_OF_COMBAT post-hook — matches tail of
        # simulate.run_step.
        if step == Step.END_OF_COMBAT:
            clear_combat_state(self._state)

        if step in STEPS_WITH_PRIORITY:
            # Prime priority for the first pass of this step's
            # priority window.
            self._pass_count = 0
            self._state.priority_player_idx = _next_alive(
                self._state, self._state.active_player_idx
            )

    # ---------------------------------------------------------------
    # Debug / test helpers
    # ---------------------------------------------------------------

    @property
    def engine_state(self) -> EngineGameState:
        """The wrapped engine state. Tests and debug tools reach
        through this; search code should not."""
        return self._state
