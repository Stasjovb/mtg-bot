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
  choose_sacrifice, etc.) all go through this policy rather than
  being exposed as search nodes. Same state + same sequence of
  top-level decisions → same resulting position, which is what MCTS
  needs.
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
- **Combat declarations: opt-in factored decisions.** With
  ``expose_combat_decisions=False`` (default), declare-attackers and
  declare-blockers go through the tactical policy as a single
  atomic step. With ``expose_combat_decisions=True``, the adapter
  walks each eligible attacker (then each eligible blocker) one at
  a time and exposes ``AttackerDecision`` / ``BlockerDecision``
  search-decision values. This trades shallow-and-wide combat
  branching for deep-and-narrow per-creature decisions, which MCTS
  with progressive widening handles much better.

What IS exposed to search by default: priority-action choices —
casting spells, activating abilities, playing lands, passing
priority. With ``expose_combat_decisions=True``, also the per-
attacker / per-blocker decisions during combat.
"""

from __future__ import annotations

from typing import Optional, Union

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
from mtg_bot.search.combat_decisions import (
    AttackerDecision, BlockerDecision,
)
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


# Combat-phase sentinel values for ``_combat_phase``.
_COMBAT_NONE = None
_COMBAT_ATTACKERS = "attackers"
_COMBAT_BLOCKERS = "blockers"


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
        expose_combat_decisions: bool = False,
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
        # Factored-combat opt-in flag and per-phase state.
        self._expose_combat = expose_combat_decisions
        self._combat_phase: Optional[str] = _COMBAT_NONE
        # Order matters — search will see the next-pending creature
        # first. Sort by id for reproducibility across clones.
        self._pending_attackers: list[int] = []
        self._chosen_attackers: list[int] = []
        self._pending_blockers: list[int] = []
        self._chosen_blocks: dict[int, int] = {}
        self._combat_defender_id: Optional[PlayerID] = None
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
        c._expose_combat = self._expose_combat
        c._combat_phase = self._combat_phase
        c._pending_attackers = list(self._pending_attackers)
        c._chosen_attackers = list(self._chosen_attackers)
        c._pending_blockers = list(self._pending_blockers)
        c._chosen_blocks = dict(self._chosen_blocks)
        c._combat_defender_id = self._combat_defender_id
        return c

    def active_player(self) -> PlayerID:
        # During factored combat, the decision-maker isn't whoever
        # holds engine priority — it's the active player (for
        # attacker decisions) or the defender (for blocker decisions).
        if self._combat_phase == _COMBAT_ATTACKERS:
            return self._state.active_player_idx
        if self._combat_phase == _COMBAT_BLOCKERS:
            assert self._combat_defender_id is not None
            return self._combat_defender_id
        return self._state.priority_player_idx

    def legal_decisions(self) -> list[Decision]:
        if self._state.is_over():
            return []
        if self._combat_phase == _COMBAT_ATTACKERS:
            # One pending attacker at a time; each can attack or not.
            next_id = self._pending_attackers[0]
            return [
                AttackerDecision(attacker_id=next_id, attack=True),
                AttackerDecision(attacker_id=next_id, attack=False),
            ]
        if self._combat_phase == _COMBAT_BLOCKERS:
            next_id = self._pending_blockers[0]
            attacking_ids = [
                o.id for o in self._state.battlefield
                if o.attacking
            ]
            options: list[Decision] = [
                BlockerDecision(blocker_id=next_id, attacker_id=atk_id)
                for atk_id in attacking_ids
            ]
            options.append(
                BlockerDecision(blocker_id=next_id, attacker_id=None)
            )
            return options
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

        # Combat sub-decisions are routed before the generic Action
        # type-check because they're search-side types, not engine
        # actions.
        if self._combat_phase == _COMBAT_ATTACKERS:
            self._apply_attacker_decision(decision)
            self._advance_to_next_decision()
            return
        if self._combat_phase == _COMBAT_BLOCKERS:
            self._apply_blocker_decision(decision)
            self._advance_to_next_decision()
            return

        if not isinstance(decision, Action):
            raise TypeError(
                f"MtgGameStateAdapter expects an mtg_bot.actions.Action "
                f"at priority moments, got {type(decision).__name__}: "
                f"{decision!r}"
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
    # Combat decision handling
    # ---------------------------------------------------------------

    def _apply_attacker_decision(self, decision: Decision) -> None:
        if not isinstance(decision, AttackerDecision):
            raise TypeError(
                f"In attacker decision phase, adapter expects "
                f"AttackerDecision; got {type(decision).__name__}: "
                f"{decision!r}"
            )
        next_id = self._pending_attackers[0]
        if decision.attacker_id != next_id:
            raise ValueError(
                f"AttackerDecision is for attacker {decision.attacker_id}, "
                f"but the next pending attacker is {next_id}. The adapter "
                f"enumerates pending attackers in a fixed order; pass "
                f"a decision for the head of legal_decisions()."
            )
        if decision.attack:
            self._chosen_attackers.append(decision.attacker_id)
        self._pending_attackers.pop(0)
        if not self._pending_attackers:
            self._finalize_attacker_phase()

    def _finalize_attacker_phase(self) -> None:
        ap = self._state.active_player()
        apply_action(
            self._state, ap.id,
            DeclareAttackers(
                attacker_ids=frozenset(self._chosen_attackers)
            ),
        )
        self._combat_phase = _COMBAT_NONE
        self._chosen_attackers = []
        # Now enter the step's priority window.
        self._enter_priority_for_current_step()

    def _apply_blocker_decision(self, decision: Decision) -> None:
        if not isinstance(decision, BlockerDecision):
            raise TypeError(
                f"In blocker decision phase, adapter expects "
                f"BlockerDecision; got {type(decision).__name__}: "
                f"{decision!r}"
            )
        next_id = self._pending_blockers[0]
        if decision.blocker_id != next_id:
            raise ValueError(
                f"BlockerDecision is for blocker {decision.blocker_id}, "
                f"but the next pending blocker is {next_id}."
            )
        if decision.attacker_id is not None:
            self._chosen_blocks[decision.blocker_id] = decision.attacker_id
        self._pending_blockers.pop(0)
        if not self._pending_blockers:
            self._finalize_blocker_phase()

    def _finalize_blocker_phase(self) -> None:
        assert self._combat_defender_id is not None
        apply_action(
            self._state, self._combat_defender_id,
            DeclareBlockers(
                assignments=tuple(self._chosen_blocks.items())
            ),
        )
        self._combat_phase = _COMBAT_NONE
        self._chosen_blocks = {}
        self._combat_defender_id = None
        self._enter_priority_for_current_step()

    def _enter_priority_for_current_step(self) -> None:
        """After finalizing a combat sub-phase, the current step
        still needs its priority window opened. Mirrors the tail of
        ``_enter_step``."""
        self._pass_count = 0
        self._state.priority_player_idx = _next_alive(
            self._state, self._state.active_player_idx
        )

    # ---------------------------------------------------------------
    # Engine-driving internals
    # ---------------------------------------------------------------

    def _advance_to_next_decision(self) -> None:
        """From whatever state we're in, drive the engine forward
        until either the game ends or the next decision is pending.
        Idempotent: safe to call when we're already at a decision
        moment (the while-loop exits immediately in that case)."""
        while not self._state.is_over():
            # Combat sub-decisions trump step-advancement — the caller
            # must clear them first.
            if self._combat_phase != _COMBAT_NONE:
                return

            if self._state.step is None:
                self._state.step = Step.UNTAP
                self._step_entered = False

            if not self._step_entered:
                self._enter_step(self._state.step)
                self._step_entered = True
                if self._state.is_over():
                    return
                # Entering a combat-decision step might have set up a
                # combat phase; if so, return to caller for the
                # sub-decision.
                if self._combat_phase != _COMBAT_NONE:
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
        For DECLARE_ATTACKERS / DECLARE_BLOCKERS with combat
        decisions exposed: sets up ``_combat_phase`` and pending
        decisions instead of entering priority directly.
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
            self._enter_declare_attackers()
            return  # _enter_declare_attackers handles the priority-tail.

        elif step == Step.DECLARE_BLOCKERS:
            self._enter_declare_blockers()
            return

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
            self._enter_priority_for_current_step()

    def _enter_declare_attackers(self) -> None:
        """Set up DECLARE_ATTACKERS step. With combat exposed,
        switch into the per-attacker decision phase. Without,
        delegate to the tactical agent and apply the engine action
        immediately."""
        ap = self._state.active_player()
        eligible = eligible_attackers(self._state, ap.id)
        if not self._expose_combat or not eligible:
            # No eligible attackers OR combat not exposed — let the
            # tactical agent (or atomic-empty default) handle it and
            # enter the step's priority window directly.
            chosen = (
                ap.agent.declare_attackers(self._state, ap.id, eligible)
                if eligible else []
            )
            apply_action(
                self._state, ap.id,
                DeclareAttackers(attacker_ids=frozenset(chosen)),
            )
            if self._state.is_over():
                return
            self._enter_priority_for_current_step()
            return

        # Switch into the attacker-decision phase. Sort for clone
        # determinism.
        self._combat_phase = _COMBAT_ATTACKERS
        self._pending_attackers = sorted(o.id for o in eligible)
        self._chosen_attackers = []

    def _enter_declare_blockers(self) -> None:
        """Set up DECLARE_BLOCKERS step. With combat exposed AND
        there's something to block, switch into the per-blocker
        decision phase. Otherwise delegate / no-op."""
        attackers = [
            o for o in self._state.battlefield if o.attacking
        ]
        if not attackers:
            # No attackers — no blocking phase, no engine action,
            # just enter the step's priority window.
            self._enter_priority_for_current_step()
            return

        defender_idx = _next_alive(
            self._state,
            (self._state.active_player_idx + 1)
            % len(self._state.players),
        )
        defender = self._state.players[defender_idx]
        eligible = eligible_blockers(self._state, defender.id)

        if not self._expose_combat or not eligible:
            # Combat not exposed OR nothing eligible to block —
            # tactical assigns and we enter priority.
            assignments = (
                defender.agent.declare_blockers(
                    self._state, defender.id, eligible, attackers
                ) if eligible else {}
            )
            apply_action(
                self._state, defender.id,
                DeclareBlockers(
                    assignments=tuple(assignments.items())
                ),
            )
            if self._state.is_over():
                return
            self._enter_priority_for_current_step()
            return

        self._combat_phase = _COMBAT_BLOCKERS
        self._combat_defender_id = defender.id
        self._pending_blockers = sorted(o.id for o in eligible)
        self._chosen_blocks = {}

    # ---------------------------------------------------------------
    # Debug / test helpers
    # ---------------------------------------------------------------

    @property
    def engine_state(self) -> EngineGameState:
        """The wrapped engine state. Tests and debug tools reach
        through this; search code should not."""
        return self._state

    @property
    def combat_phase(self) -> Optional[str]:
        """Current combat sub-phase, or None if the adapter is at a
        priority moment. Useful for tests / introspection."""
        return self._combat_phase
