"""``RustGameStateAdapter`` — the Rust-backed ``search.protocol.GameState``
implementation (B3-S1).

The **second** concrete ``search.protocol.GameState`` implementation,
beside ``MtgGameStateAdapter``. Search cannot tell the difference (it
implements exactly the same 8-method Protocol, ``protocol.py:42-99``),
but its internals drive the Rust ``#[pymethods]`` surface instead of
``mtg_bot.game.GameState``.

**Scope of B3-S1 (this slice).** The priority-window axis:
``pass_priority`` / ``play_land`` / ``cast_spell`` /
``activate_ability``. The Rust ``legal_decisions`` enumerator already
mana/target/cost-prunes the cast set (C1) and emits the **factored**
per-creature ``attacker_decision`` / ``blocker_decision`` shape (G1,
``f5c11231``); S1 passes those factored combat dicts straight through
the dict adapter and applies them one-at-a-time via the G1
``Action::AttackerDecision`` / ``BlockerDecision`` apply arms (Rust
accumulates the declared set internally). The full provider-side
combat *accumulation* + the determinizer-via-Rust plumbing is B3-S3;
the codec slot-source switch is B3-S2; the ``rust_shadow`` lock-step
shadow-checker is B3-S4.

**The reimplemented priority loop (spec §3.1).** Rust's
``apply_action({"kind":"pass_priority"})`` is a deliberate **no-op**
(CE2 closure, ``state_ops_actions.rs:89``): priority handoff + step
advancement in Rust are driven by the side-channel
``advance_phase`` / ``resolve_top_of_stack`` primitives, NOT by
``apply_action``. So — exactly as ``MtgGameStateAdapter`` reimplements
``simulate.priority_loop`` in Python (``engine_adapter.py:18-21``) —
this provider reimplements the priority-loop body in Python and only
its *engine calls* become Rust:

* a non-pass priority action -> ``rust.apply_action(dict)`` +
  ``rust.apply_sbas()`` (the Rust-side port of
  ``engine_adapter.py:979-987``);
* ``PassPriority`` -> a Python-side pass counter; when both alive
  players have passed in succession, either drain the stack
  (``rust.resolve_top_of_stack()`` + ``rust.apply_sbas()`` —
  effect-dispatching, unlike the pop-only
  ``complete_step_via_priority_round``) or, on an empty stack, end
  the step (``rust.advance_phase()``) — the Rust-side port of
  ``engine_adapter.py:951-977``;
* after every applied decision, ``_advance_to_next_decision`` drives
  Rust forward (``advance_phase`` through the auto steps UNTAP /
  CLEANUP whose hooks Rust's ``advance_phase`` already composes) until
  the next priority/decision moment — the Rust-side port of
  ``engine_adapter.py:1159-1189``.

**Parity-safety (the load-bearing invariant).** This entire module is
*dormant* under ``decision_source="python"`` (the default): the
``make_game_state_adapter`` factory returns the unchanged
``MtgGameStateAdapter`` and this class is never constructed. With the
flag OFF every existing trajectory / probe / training pin is
byte-unchanged because no existing code path imports or instantiates
``RustGameStateAdapter``. It is exercised only by its own dedicated
B3 unit tests and (B3-S4 onward) the ``rust_shadow`` bake-in.
"""

from __future__ import annotations

from typing import Any, Optional

from mtg_bot.actions import PassPriority
from mtg_bot.search.combat_decisions import (
    AttackerDecision, BlockerDecision,
)
from mtg_bot.search.protocol import Decision, PlayerID
from mtg_bot.search.rust_decision_adapter import (
    decision_to_rust_dict, rust_dict_to_decision,
)

# Rust phase constants (rust/src/state_ops_steps.rs:96-113). Mirrored
# here so the provider's priority loop can classify the current phase
# without a Rust round-trip per check.
_PHASE_UNTAP = 0
_PHASE_DECLARE_ATTACKERS = 5
_PHASE_DECLARE_BLOCKERS = 6
_PHASE_CLEANUP = 11
# STEPS_WITH_PRIORITY mirror (turn.py:42 — every step except UNTAP and
# CLEANUP). The two combat-declare phases ALSO have priority but are
# the factored-combat windows (Rust legal_decisions emits the G1
# factored dicts there); they are decision moments, not auto-advance
# phases.
_AUTO_ADVANCE_PHASES = frozenset({_PHASE_UNTAP, _PHASE_CLEANUP})
_COMBAT_DECLARE_PHASES = frozenset(
    {_PHASE_DECLARE_ATTACKERS, _PHASE_DECLARE_BLOCKERS}
)

# Combat-phase sentinels — same vocabulary MtgGameStateAdapter uses
# so the S3 combat-accumulation port can share semantics.
_COMBAT_NONE: Optional[str] = None
_COMBAT_ATTACKERS = "attackers"
_COMBAT_BLOCKERS = "blockers"


class RustGameStateAdapter:
    """Rust-engine-backed ``search.protocol.GameState``.

    Construct with a live Rust ``GameState`` handle (a
    ``mtg_bot_engine.GameState``, e.g. from
    ``cross_engine.build_rust_state`` / ``build_matched_states`` — the
    surviving loader path per ``BRIDGE_VESTIGIALIZATION_PLAN.md``
    §2.1).
    """

    def __init__(
        self,
        rust_state: Any,
        *,
        expose_combat_decisions: bool = True,
    ) -> None:
        self._rust = rust_state
        self._expose_combat = expose_combat_decisions
        # Consecutive priority passes since the last non-pass or stack
        # resolution. Lives on the provider (not Rust state) because it
        # is search-loop bookkeeping — Rust's apply_action(pass) is a
        # no-op and does NOT track this. Mirrors
        # MtgGameStateAdapter._pass_count.
        self._pass_count = 0
        # Per-priority-moment cache of the Rust legal_decisions dict
        # list, keyed by the player whose set was computed. Mirrors
        # MtgGameStateAdapter's _legal_actions_cache lifetime: per
        # decision moment, never crosses an apply() boundary.
        self._legal_cache_player: Optional[PlayerID] = None
        self._legal_cache_value: Optional[list[dict]] = None
        # B3-S3 combat-accumulation bookkeeping placeholders (the
        # factored-combat provider side ports engine_adapter.py:
        # 1080-1144 here). S1 leaves them inert.
        self._combat_phase: Optional[str] = _COMBAT_NONE
        self._pending_attackers: list[int] = []
        self._chosen_attackers: list[int] = []
        self._pending_blockers: list[int] = []
        self._chosen_blocks: dict[int, int] = {}
        # Drive forward until we hit a terminal state or a priority /
        # decision moment (mirrors MtgGameStateAdapter.__init__'s
        # trailing _advance_to_next_decision()).
        self._advance_to_next_decision()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _priority_pid(self) -> int:
        return int(self._rust.get_priority_player())

    def _phase(self) -> int:
        return int(self._rust.current_phase())

    def _alive_count(self) -> int:
        # 2-player model. winner_id() is set only post-game; pre-game
        # both players are alive. A player that has lost flips is_over.
        return 2

    def _invalidate_legal_cache(self) -> None:
        self._legal_cache_player = None
        self._legal_cache_value = None

    def _legal_dicts_cached(self, pid: int) -> list[dict]:
        if (
            self._legal_cache_value is not None
            and self._legal_cache_player == pid
        ):
            return self._legal_cache_value
        dicts = list(self._rust.legal_decisions(pid))
        self._legal_cache_player = pid
        self._legal_cache_value = dicts
        return dicts

    def _advance_to_next_decision(self) -> None:
        """Drive Rust forward until the game ends or the next
        priority/decision moment is pending. Rust's ``advance_phase``
        composes the UNTAP untap-sweep + DRAW draw + CLEANUP hooks
        internally, so an auto phase (UNTAP / CLEANUP) just advances;
        a priority phase (everything else, incl. the factored-combat
        declare phases) is a decision moment — stop. Idempotent.
        """
        # Bounded so a Rust contract bug can't spin forever — a single
        # turn is 12 phases; this cap covers many consecutive auto
        # phases without masking a real hang.
        for _ in range(64):
            if self._rust.is_over():
                return
            phase = self._phase()
            if phase in _AUTO_ADVANCE_PHASES:
                self._rust.advance_phase()
                self._invalidate_legal_cache()
                self._pass_count = 0
                continue
            # A priority phase (incl. the factored-combat declare
            # phases) — the caller must decide here.
            return

    def _run_priority_action(self, decision: Decision) -> None:
        """Rust-side port of ``engine_adapter.py:945-987``.

        ``PassPriority`` drives the Python-side pass counter; a
        completed pass round either resolves the top of the stack
        (effect-dispatching ``resolve_top_of_stack`` + SBA) or ends
        the step (``advance_phase``). Any other action applies on Rust
        then runs SBAs and resets the pass counter.
        """
        if isinstance(decision, PassPriority):
            self._pass_count += 1
            if self._pass_count >= self._alive_count():
                self._pass_count = 0
                if self._rust.stack_size() > 0:
                    # Resolve one stack item with real effect dispatch
                    # (NOT the pop-only complete_step_via_priority_round
                    # — that does not fire effects). Priority returns
                    # to the active player after a resolution (CR
                    # 117.1c); Rust's resolve_top_of_stack already
                    # resets priority_player = active_player.
                    self._rust.resolve_top_of_stack()
                    self._rust.apply_sbas()
                else:
                    # Empty stack, both passed -> the step ends.
                    self._rust.advance_phase()
            else:
                # Pass priority to the other player (2-player toggle).
                self._rust.pass_priority()
        else:
            d = decision_to_rust_dict(decision)
            self._rust.apply_action(d)
            self._rust.apply_sbas()
            self._pass_count = 0

    # ------------------------------------------------------------------
    # search.GameState protocol
    # ------------------------------------------------------------------

    def clone(self) -> "RustGameStateAdapter":
        c = RustGameStateAdapter.__new__(RustGameStateAdapter)
        # VERIFY-FIRST RE-ANCHOR: the B3 spec §2.1 table lists
        # ``clone()`` (``state.rs:1689``) but that is the internal
        # Rust trait impl — the exposed ``#[pymethods]`` deep-copy is
        # ``clone_once()`` (``state.rs:1789``). The code wins over the
        # spec prose.
        c._rust = self._rust.clone_once()
        c._expose_combat = self._expose_combat
        c._pass_count = self._pass_count
        # Cache lifetime is per-priority-moment; the clone starts
        # empty (same rationale as MtgGameStateAdapter.clone — a
        # post-clone determinizer mutation would otherwise be served
        # stale). Combat bookkeeping is copied so an in-flight
        # accumulation survives the clone (S3 relies on this).
        c._legal_cache_player = None
        c._legal_cache_value = None
        c._combat_phase = self._combat_phase
        c._pending_attackers = list(self._pending_attackers)
        c._chosen_attackers = list(self._chosen_attackers)
        c._pending_blockers = list(self._pending_blockers)
        c._chosen_blocks = dict(self._chosen_blocks)
        return c

    def active_player(self) -> PlayerID:
        # Rust resolves priority/active internally; the priority holder
        # is the decision-maker. For the factored-combat windows Rust's
        # legal_decisions already gates emission on active==priority
        # (attackers) / active!=priority (blockers), so the priority
        # holder is still the right decision-maker key. The S3
        # combat-accumulation port refines the active/defender split.
        return self._priority_pid()

    def legal_decisions(self) -> list[Decision]:
        if self._rust.is_over():
            return []
        pid = self._priority_pid()
        dicts = self._legal_dicts_cached(pid)
        return [rust_dict_to_decision(d) for d in dicts]

    def chance_outcomes(self) -> list[tuple[Decision, float]]:
        # Unchanged from MtgGameStateAdapter — no chance nodes;
        # determinization is root-level (§3.4).
        return []

    def apply(self, decision: Decision) -> None:
        if self._rust.is_over():
            raise ValueError("apply() called on terminal state")
        self._invalidate_legal_cache()
        self._run_priority_action(decision)
        if not self._rust.is_over():
            self._advance_to_next_decision()

    def is_terminal(self) -> bool:
        return bool(self._rust.is_over())

    def winner(self) -> Optional[PlayerID]:
        # VERIFY-FIRST RE-ANCHOR: the B3 spec §2.1 table lists
        # ``winner_id()`` but the LIVE Rust surface exposes it as a
        # ``#[getter]`` property (read as a plain attribute, NOT
        # called) — consistent with ``scripts/parity_smoke.py:1038``
        # which reads ``state.winner_id``. ``is_over`` / ``fingerprint``
        # ARE methods. The code wins over the spec prose.
        w = self._rust.winner_id
        return None if w is None else int(w)

    def players(self) -> list[PlayerID]:
        # 2-player model, same as MtgGameStateAdapter / the Rust
        # GameState (players[0], players[1]).
        return [0, 1]

    # ------------------------------------------------------------------
    # Introspection helpers (test / shadow-checker support)
    # ------------------------------------------------------------------

    @property
    def rust_state(self) -> Any:
        """The wrapped Rust ``GameState`` handle. The shadow-checker
        (B3-S4) and combat-accumulation port (B3-S3) reach through
        this; the rest of search stays on the Protocol surface."""
        return self._rust

    @property
    def combat_phase(self) -> Optional[str]:
        """Current combat sub-phase, or ``None`` at a priority moment.
        S1 leaves this ``None`` (combat dicts pass through); S3's
        accumulation port drives it."""
        return self._combat_phase

    def fingerprint(self) -> str:
        """Canonical Rust state hash — the shadow-checker equivalence
        key (B3-S4, ``rust_state.fingerprint()``)."""
        return self._rust.fingerprint()
