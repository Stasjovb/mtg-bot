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
from mtg_bot.search.resolution_channel import (
    KIND_CARD_FROM_LIBRARY, KIND_CARD_FROM_OPPONENT_HAND,
    KIND_DEVOUR_LANDS, KIND_DISCARD, KIND_MODE, KIND_SACRIFICE,
    KIND_SHOCK_LIFE, KIND_SURVEIL, KIND_TARGET, KIND_X,
    KIND_YES_NO,
    ResolutionChannelAgent, _ResolutionPause,
)
from mtg_bot.search.resolution_decisions import (
    ResolutionCardFromLibraryDecision,
    ResolutionCardFromOpponentHandDecision,
    ResolutionDevourLandsDecision, ResolutionDiscardDecision,
    ResolutionModeDecision, ResolutionSacrificeDecision,
    ResolutionShockLifeDecision, ResolutionSurveilDecision,
    ResolutionTargetDecision, ResolutionXDecision,
    ResolutionYesNoDecision,
)
from mtg_bot.search.tactical import DefaultTacticalAgent
from mtg_bot.simulate import _advance_to_next_active_player, _next_alive
from mtg_bot.turn import (
    STEP_ORDER,
    STEPS_WITH_PRIORITY,
    Step,
    run_beginning_of_combat_triggers,
    run_beginning_of_end_step_triggers,
    run_beginning_of_postcombat_main_triggers,
    run_beginning_of_upkeep_triggers,
    run_cleanup_step,
    run_delayed_end_step_triggers,
    run_draw_step,
    run_untap_step,
    state_based_actions,
)


# Combat-phase sentinel values for ``_combat_phase``.
_COMBAT_NONE = None
_COMBAT_ATTACKERS = "attackers"
_COMBAT_BLOCKERS = "blockers"


# Maps the ``_ResolutionPause.kind`` value to the search-side
# decision class the adapter expects when search answers that pause.
_RESOLUTION_KIND_TO_DECISION_CLASS = {
    KIND_TARGET: ResolutionTargetDecision,
    KIND_DISCARD: ResolutionDiscardDecision,
    KIND_MODE: ResolutionModeDecision,
    KIND_SACRIFICE: ResolutionSacrificeDecision,
    KIND_X: ResolutionXDecision,
    KIND_SURVEIL: ResolutionSurveilDecision,
    KIND_SHOCK_LIFE: ResolutionShockLifeDecision,
    KIND_CARD_FROM_LIBRARY: ResolutionCardFromLibraryDecision,
    KIND_CARD_FROM_OPPONENT_HAND: ResolutionCardFromOpponentHandDecision,
    KIND_DEVOUR_LANDS: ResolutionDevourLandsDecision,
    KIND_YES_NO: ResolutionYesNoDecision,
}


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
        expose_combat_decisions: bool = True,
        expose_resolution_decisions: bool = False,
    ) -> None:
        self._state = engine_state
        self._tactical = tactical_agent or DefaultTacticalAgent()
        self._expose_resolution = expose_resolution_decisions
        # Agent installation. With resolution exposure we need the
        # ``ResolutionChannelAgent`` to intercept callbacks; non-
        # exposed callbacks fall through to the tactical policy.
        if self._expose_resolution:
            self._channel_agent: Optional[ResolutionChannelAgent] = (
                ResolutionChannelAgent(fallback=self._tactical)
            )
            primary_agent = self._channel_agent
        else:
            self._channel_agent = None
            primary_agent = self._tactical
        for p in self._state.players:
            p.agent = primary_agent
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
        # Factored-combat exposure flag and per-phase state. Default
        # is True: search sees AttackerDecision / BlockerDecision
        # nodes (one branch per creature) at combat steps instead of
        # the adapter auto-resolving via DefaultTacticalAgent's
        # "attack-everything, block-nothing" policy. Pass False to
        # restore the auto-resolve path (used by a handful of tests
        # that drive non-combat behavior and want the simpler flow).
        self._expose_combat = expose_combat_decisions
        self._combat_phase: Optional[str] = _COMBAT_NONE
        # Order matters — search will see the next-pending creature
        # first. Sort by id for reproducibility across clones.
        self._pending_attackers: list[int] = []
        self._chosen_attackers: list[int] = []
        self._pending_blockers: list[int] = []
        self._chosen_blocks: dict[int, int] = {}
        self._combat_defender_id: Optional[PlayerID] = None
        # Resolution-pause state. When a priority action's resolution
        # raises ``_ResolutionPause``, the adapter rolls back to a
        # snapshot taken before the action and surfaces the decision
        # to search. ``_pre_action_clone`` is the snapshot;
        # ``_pending_replay_decision`` is the priority action being
        # replayed with growing resolution-queue answers.
        self._resolution_paused = False
        self._resolution_kind: Optional[str] = None
        self._resolution_player: Optional[PlayerID] = None
        self._resolution_options: tuple = ()
        self._pre_action_clone: Optional[EngineGameState] = None
        self._pending_replay_decision: Optional[Decision] = None
        # Per-decision-moment cache of ``legal.legal_actions`` results.
        # ISMCTS calls ``legal_decisions`` AND ``legal_action_mask`` AND
        # ``_grow_union_mask`` (downstream of mask) all on the SAME
        # engine state per descent step — three identical enumerations
        # of a function that consumes 37% of self-play wall time per
        # ``docs/perf_self_play_20260504.md``. Cache one entry keyed by
        # the player whose priority-window legal set was computed; the
        # cache is invalidated whenever any engine-state mutation runs
        # (every ``apply()`` and every internal step transition that
        # alters ``self._state``). The cache stores the list reference
        # itself; callers that need a private copy do their own
        # ``list(...)`` of it. Lifetime: per priority moment, never
        # crosses an ``apply()`` boundary.
        self._legal_actions_cache_player: Optional[PlayerID] = None
        self._legal_actions_cache_value: Optional[list[Action]] = None
        # Drive forward until we either hit a terminal state or a
        # priority moment where the caller must decide.
        self._advance_to_next_decision()

    # ---------------------------------------------------------------
    # Per-decision-moment legal_actions cache
    # ---------------------------------------------------------------

    def _invalidate_legal_actions_cache(self) -> None:
        """Drop any cached ``legal_actions`` result. Called from every
        site that mutates ``self._state`` (or replaces it with a new
        clone via the resolution-pause snapshot path). Cheap: two
        attribute writes.
        """
        self._legal_actions_cache_player = None
        self._legal_actions_cache_value = None

    def _legal_actions_cached(
        self, player_id: PlayerID,
    ) -> list[Action]:
        """Return ``legal.legal_actions(self._state, player_id)``,
        memoized for the current decision moment. The first call after
        an ``apply()`` (or other state-mutating event) computes and
        stores; subsequent calls within the same decision moment for
        the same ``player_id`` return the cached list directly.

        The cached list is the SAME object across cache hits — callers
        must treat it as read-only. ``legal_decisions`` already does
        ``list(...)`` on the result before exposing it to search; the
        mask helper iterates without mutating. If a hypothetical
        future caller needs a private copy, they should ``list(...)``
        the result themselves.
        """
        if (
            self._legal_actions_cache_value is not None
            and self._legal_actions_cache_player == player_id
        ):
            return self._legal_actions_cache_value
        result = legal_actions(self._state, player_id)
        self._legal_actions_cache_player = player_id
        self._legal_actions_cache_value = result
        return result

    # ---------------------------------------------------------------
    # search.GameState protocol
    # ---------------------------------------------------------------

    def clone(self) -> "MtgGameStateAdapter":
        c = MtgGameStateAdapter.__new__(MtgGameStateAdapter)
        c._state = self._state.clone()
        c._tactical = self._tactical
        c._expose_resolution = self._expose_resolution
        # Resolution-channel agent is per-adapter-instance so each
        # clone has its own replay queue. Snapshot/restore preserves
        # queue state from the source.
        if self._expose_resolution and self._channel_agent is not None:
            c._channel_agent = ResolutionChannelAgent(
                fallback=self._tactical,
            )
            c._channel_agent.restore(self._channel_agent.snapshot())
            primary_agent = c._channel_agent
        else:
            c._channel_agent = None
            primary_agent = self._tactical
        for p in c._state.players:
            p.agent = primary_agent
        c._pass_count = self._pass_count
        c._step_entered = self._step_entered
        c._expose_combat = self._expose_combat
        c._combat_phase = self._combat_phase
        c._pending_attackers = list(self._pending_attackers)
        c._chosen_attackers = list(self._chosen_attackers)
        c._pending_blockers = list(self._pending_blockers)
        c._chosen_blocks = dict(self._chosen_blocks)
        c._combat_defender_id = self._combat_defender_id
        # Resolution-pause state.
        c._resolution_paused = self._resolution_paused
        c._resolution_kind = self._resolution_kind
        c._resolution_player = self._resolution_player
        c._resolution_options = self._resolution_options
        c._pre_action_clone = (
            self._pre_action_clone.clone()
            if self._pre_action_clone is not None else None
        )
        c._pending_replay_decision = self._pending_replay_decision
        # Cache lifetime is per-adapter-per-priority-moment: the clone
        # starts with an empty cache. Sharing the source's cached list
        # with the clone would be tempting (the engine_state at clone
        # time is a deep copy of the source's, so legal_actions would
        # match) — but ISMCTS calls ``_fresh_determinization`` which
        # MUTATES ``c.engine_state`` in place right after this clone
        # returns, permuting hidden-zone printings. After that mutation
        # a shared cache would silently return stale entries (e.g. for
        # the Mm'menon cast-from-library-top check, which inspects
        # ``library[0]``). Starting with an empty cache forces the
        # next ``legal_decisions`` call on the clone to re-enumerate
        # against the post-determinization state — which is what we
        # want and is no worse than the pre-cache behavior.
        c._legal_actions_cache_player = None
        c._legal_actions_cache_value = None
        return c

    def active_player(self) -> PlayerID:
        # During mid-resolution pauses, it's the player the engine
        # callback was asking — not whoever held engine priority.
        if self._resolution_paused:
            assert self._resolution_player is not None
            return self._resolution_player
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
        if self._resolution_paused:
            return self._resolution_legal_decisions()
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
        return list(self._legal_actions_cached(self.active_player()))

    def _resolution_legal_decisions(self) -> list[Decision]:
        """Materialize resolution-pause options as search-side
        decision objects. Each option becomes one ``Resolution*``
        instance."""
        kind = self._resolution_kind
        opts = self._resolution_options
        if kind == KIND_TARGET:
            return [ResolutionTargetDecision(target=t) for t in opts]
        if kind == KIND_DISCARD:
            return [ResolutionDiscardDecision(card_id=cid) for cid in opts]
        if kind == KIND_MODE:
            return [ResolutionModeDecision(mode_index=i) for i in opts]
        if kind == KIND_SACRIFICE:
            return [
                ResolutionSacrificeDecision(object_id=oid) for oid in opts
            ]
        if kind == KIND_X:
            return [ResolutionXDecision(x_value=v) for v in opts]
        if kind == KIND_SURVEIL:
            return [ResolutionSurveilDecision(mill=v) for v in opts]
        if kind == KIND_SHOCK_LIFE:
            return [ResolutionShockLifeDecision(pay=v) for v in opts]
        if kind == KIND_CARD_FROM_LIBRARY:
            return [
                ResolutionCardFromLibraryDecision(card_id=cid) for cid in opts
            ]
        if kind == KIND_CARD_FROM_OPPONENT_HAND:
            return [
                ResolutionCardFromOpponentHandDecision(card_id=cid)
                for cid in opts
            ]
        if kind == KIND_DEVOUR_LANDS:
            return [
                ResolutionDevourLandsDecision(land_ids=subset)
                for subset in opts
            ]
        if kind == KIND_YES_NO:
            # opts is always (True, False) — channel agent supplies
            # both branches; the prompt itself isn't part of the
            # decision space. Yes-first matches the order the channel
            # agent enumerates.
            return [ResolutionYesNoDecision(yes=v) for v in opts]
        raise RuntimeError(f"unknown resolution kind: {kind!r}")

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

        # Cache invariant: any ``apply()`` will mutate ``self._state``
        # (or replace it via resolution-pause rollback). Dropping the
        # cached legal_actions here guarantees the next
        # ``legal_decisions()`` call re-enumerates against the fresh
        # state. Putting the invalidation at the top of ``apply()``
        # rather than inside each mutator is the simplest invariant
        # that survives every dispatch branch below.
        self._invalidate_legal_actions_cache()

        # Resolution-pause answer routing — consume a Resolution*
        # decision, push to the channel agent's replay queue, rollback
        # state, and retry the saved priority action.
        if self._resolution_paused:
            self._apply_resolution_decision(decision)
            return

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

        # With resolution exposure, wrap the priority action in a
        # pause-catch + replay harness. Without, just run it — no
        # snapshot, no replay.
        if self._expose_resolution:
            self._run_priority_action_with_resolution_capture(decision)
        else:
            self._run_priority_action(decision)
            self._advance_to_next_decision()

    def _run_priority_action(self, decision: Decision) -> None:
        """The original priority-action body, extracted so it can be
        invoked from multiple call sites (normal path and replay
        from resolution rollback)."""
        pid = self._state.priority_player_idx

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

    # ---------------------------------------------------------------
    # Resolution decision handling
    # ---------------------------------------------------------------

    def _run_priority_action_with_resolution_capture(
        self, decision: Decision,
    ) -> None:
        """Save a pre-action snapshot, run the priority action, and
        catch any ``_ResolutionPause``. On pause, rollback state and
        store the pending decision for replay."""
        assert self._channel_agent is not None
        # Snapshot the full engine state BEFORE the action. On pause
        # we roll back to this clone (re-cloning each time so the
        # snapshot itself stays pristine for subsequent pauses).
        self._pre_action_clone = self._state.clone()
        self._pending_replay_decision = decision
        self._channel_agent.reset_queue()
        self._attempt_priority_action()

    def _rollback_to_snapshot(self) -> None:
        """Restore ``self._state`` from ``self._pre_action_clone``
        and re-install the per-adapter channel agent on the
        rolled-back players.

        The snapshot carries whatever agent was installed at the
        time it was taken — typically the original adapter's channel
        agent. After cloning the adapter, the clone has its OWN
        channel agent but the snapshot still points at the original.
        Re-installing agents here keeps each adapter's resolution
        queue isolated from its siblings.
        """
        assert self._pre_action_clone is not None
        assert self._channel_agent is not None
        self._state = self._pre_action_clone.clone()
        for p in self._state.players:
            p.agent = self._channel_agent

    def _attempt_priority_action(self) -> None:
        """Try the current pending priority action. Handles pause,
        success (advances to next decision), and cleanup."""
        assert self._pending_replay_decision is not None
        assert self._channel_agent is not None
        try:
            self._run_priority_action(self._pending_replay_decision)
            if not self._state.is_over():
                self._advance_to_next_decision()
        except _ResolutionPause as pause:
            # Engine asked for a callback we don't have in the queue.
            # Rollback to the pre-action snapshot and expose the
            # decision to search. Keep the snapshot around for the
            # next replay attempt.
            self._rollback_to_snapshot()
            self._channel_agent.rewind()
            self._resolution_paused = True
            self._resolution_kind = pause.kind
            self._resolution_player = pause.player_id
            self._resolution_options = pause.options
            return
        # Success — discard the snapshot and replay state.
        self._pre_action_clone = None
        self._pending_replay_decision = None

    def _apply_resolution_decision(self, decision: Decision) -> None:
        """Caller supplied an answer to the currently-paused
        resolution callback. Push it to the replay queue and retry."""
        assert self._channel_agent is not None
        expected_type = _RESOLUTION_KIND_TO_DECISION_CLASS[
            self._resolution_kind
        ]
        if not isinstance(decision, expected_type):
            raise TypeError(
                f"Resolution pause expects {expected_type.__name__} "
                f"for a {self._resolution_kind} callback; got "
                f"{type(decision).__name__}: {decision!r}"
            )
        self._channel_agent.push_answer(decision)
        # Clear pause metadata; state will be reset by the retry.
        self._resolution_paused = False
        self._resolution_kind = None
        self._resolution_player = None
        self._resolution_options = ()
        # Rollback and replay. ``_attempt_priority_action`` handles
        # the outcome (next pause or successful completion).
        self._rollback_to_snapshot()
        self._channel_agent.rewind()
        self._attempt_priority_action()

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
            # same rule run_step enforces. ``turn_number == 1`` alone
            # is the correct condition: on turn 1 the active player
            # IS the starting player regardless of which seat they
            # occupy, so this works for both standard (seat 0 starts)
            # and alternating-seat (seat 1 starts) games.
            if self._state.turn_number != 1:
                run_draw_step(self._state)

        elif step == Step.BEGINNING_OF_COMBAT:
            run_beginning_of_combat_triggers(self._state)
            state_based_actions(self._state)

        elif step == Step.POSTCOMBAT_MAIN:
            # Mirror the simulate.run_step wiring for the DSK Survival
            # second-main-phase trigger family.
            run_beginning_of_postcombat_main_triggers(self._state)
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
        """The wrapped engine state. MTG-aware search code (PIMC, the
        determinizer) reaches through this to operate on the engine
        directly; the rest of search should stay on the protocol
        surface. Mutating it bypasses adapter bookkeeping (priority
        counter, combat phase, resolution-pause snapshot,
        legal_actions cache) and is unsupported.

        Callers that DO need to mutate the engine state directly (the
        ISMCTS / PIMC determinizer being the canonical example) must
        either (a) only do so on a freshly-cloned adapter whose cache
        was empty to begin with — see ``clone()`` — or (b) call
        ``_invalidate_legal_actions_cache()`` after the mutation to
        drop any stale entries.
        """
        return self._state

    @property
    def combat_phase(self) -> Optional[str]:
        """Current combat sub-phase, or None if the adapter is at a
        priority moment. Useful for tests / introspection."""
        return self._combat_phase
