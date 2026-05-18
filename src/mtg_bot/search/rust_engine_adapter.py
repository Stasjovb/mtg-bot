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
_PHASE_UPKEEP = 1
_PHASE_BEGINNING_OF_COMBAT = 4
_PHASE_DECLARE_ATTACKERS = 5
_PHASE_DECLARE_BLOCKERS = 6
_PHASE_COMBAT_DAMAGE = 7
_PHASE_END_OF_COMBAT = 8
_PHASE_POSTCOMBAT_MAIN = 9
_PHASE_END = 10
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

# G6 — the phases at whose ``_enter_step`` Python's source-of-truth
# (``engine_adapter.py``) runs ``state_based_actions(self._state)``.
# This is the EXACT cadence the Rust-driver port must mirror on its
# step-end / auto-advance path (the missing call surfaced by the G5
# closure as blocker G6 — see this module's ``_run_step_enter_sbas``
# docstring). Read straight off the Python ``_enter_step`` dispatch:
#
#   UPKEEP                (engine_adapter.py:1224)            -> always
#   BEGINNING_OF_COMBAT   (engine_adapter.py:1238)            -> always
#   POSTCOMBAT_MAIN       (engine_adapter.py:1244)            -> always
#   END                   (engine_adapter.py:1268[, :1271])   -> always
#   COMBAT_DAMAGE         (engine_adapter.py:1261-1264)        -> ONLY
#       when there are attackers (Python guards BOTH the
#       ``resolve_combat_damage`` call AND the SBA with
#       ``if any(o.attacking for o in self._state.battlefield)``).
#       The Rust mirror runs ``deal_combat_damage()`` BEFORE the
#       SBA — same order, same guard, byte-equivalent to Python's
#       ``resolve_combat_damage`` + ``state_based_actions`` pair
#       (the G2 @504/@431 combat-damage outcome / SBA divergence
#       closure).
#
# DRAW / PRECOMBAT_MAIN / END_OF_COMBAT / the two combat-DECLARE
# phases are priority/decision steps but Python's ``_enter_step`` runs
# NO SBA there; UNTAP / CLEANUP are the auto steps (also no SBA).
# Calling ``apply_sbas()`` at a phase Python does NOT is forbidden
# (over-calling can byte-shift state / mask a divergence) — so this
# set is the exact, minimal mirror, with COMBAT_DAMAGE kept
# conditional below.
_ENTER_STEP_SBA_PHASES = frozenset({
    _PHASE_UPKEEP, _PHASE_BEGINNING_OF_COMBAT,
    _PHASE_POSTCOMBAT_MAIN, _PHASE_END,
})

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

    # B3-S2 marker: the action-encoding codec's _enumerate_legal
    # routes through this provider's legal_decisions() (which already
    # maps Rust dicts -> Decisions via the non-vestigial
    # rust_decision_adapter). A class attribute (not an isinstance
    # check) so the codec needs no import of this module — avoids an
    # import cycle (action_encoding <- search).
    _is_rust_decision_provider: bool = True

    def __init__(
        self,
        rust_state: Any,
        *,
        expose_combat_decisions: bool = True,
        printing_resolver: Optional[dict] = None,
    ) -> None:
        self._rust = rust_state
        self._expose_combat = expose_combat_decisions
        # B3-S2: name -> Python CardPrinting map (built from the same
        # DeckSpec CardDefs the Rust state was built from, via the
        # SAME _card_def_to_python_printing path build_python_state
        # uses). The card parser/loader stays Python per the flip
        # architecture (SOT_FLIP_CUTOVER_PLAN §5); the codec's
        # printing.name / .is_creature / .is_spacecraft / .room_halves
        # are resolved through this so slot semantics are byte-
        # identical to the Python path. None until S2 wires it.
        self._printing_resolver: dict = printing_resolver or {}
        # Consecutive priority passes since the last non-pass or stack
        # resolution. Lives on the provider (not Rust state) because it
        # is search-loop bookkeeping — Rust's apply_action(pass) is a
        # no-op and does NOT track this. Mirrors
        # MtgGameStateAdapter._pass_count.
        self._pass_count = 0
        # B3-S2 / spec §2.4-G2 — the PlayLand per-turn-limit interim
        # mask. Rust's legal_decisions over-offers a PlayLand for
        # EVERY land in hand regardless of the one-per-turn limit (no
        # `lands_played_this_turn` field on the Rust GameState —
        # state_ops_legal.rs:40-50, SL-documented). Direction is
        # benign ("Rust offers one extra structurally; apply rejects
        # it") but it pollutes the root legal mask. The spec's
        # recommended parity-safe interim is a B3-side mask filter in
        # the provider (mirroring the existing _should_force_landdrop
        # adapter-filter pattern). We track land-played per turn via
        # Python-side bookkeeping (same shape as _pass_count) keyed by
        # the Rust turn_number, and filter ALL PlayLand decisions out
        # of legal_decisions() once a land was applied this turn
        # (max_lands == 1 on the loader-admitted surface). The proper
        # fix (the Rust field) is sequenced post-flip per the SL note.
        self._land_played_on_turn: Optional[int] = None
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
        # **G7 @369 G1 stateless-Rust attack=False re-emission /
        # B3-S3 provider-accumulation port.** Once a factored-combat
        # window is finalized (queue exhausted) Rust's emitter is
        # still structurally inside DECLARE_ATTACKERS /
        # DECLARE_BLOCKERS and — for any creature that declared
        # attack=False (or any vigilant-untapped attacker the queue
        # has popped past) — will re-emit the factored option pair on
        # the next legal_decisions() call. The adapter must NOT
        # re-enter the factored window: Python's
        # ``_enter_declare_attackers`` is called ONCE per phase entry
        # and ``_finalize_attacker_phase`` returns the adapter to the
        # priority window where it stays until the step advances.
        # We tag the (turn_number, phase) pair on finalize and
        # suppress Rust's factored emission until either tag advances
        # — exactly the byte-equal lifetime of Python's
        # _combat_phase == None state inside a DECLARE_* step.
        # ``None`` = no finalized window yet.
        self._finalized_combat_window: Optional[tuple[int, int]] = None
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

    def _n_players(self) -> int:
        # 2-player model (same as MtgGameStateAdapter / the Rust
        # GameState — players[0], players[1]). The CR-aware
        # alive-skipping walk needs the modulus; sourcing it here keeps
        # the _next_alive port a 1:1 mirror of Python's
        # ``len(state.players)``.
        return 2

    def _lost_set(self) -> frozenset[int]:
        """The set of player ids Python's ``_next_alive`` /
        ``_run_priority_action`` treats as ``has_lost``.

        Python's ``_next_alive`` (``simulate.py:46``) and the
        priority-round threshold (``engine_adapter.py:953``) key on
        ``Player.has_lost``, which ``turn.draw_card`` sets **eagerly**
        (``turn.py:110`` — the moment a player draws from an empty
        library, BEFORE the next SBA pass) plus the SBA-set life<=0 /
        poison cases. Rust's sticky ``has_lost`` flag lags that eager
        signal until its own SBA pass, but Rust's ``losers()``
        (``state_ops_winloss.rs:95``) is the eager OR'd-three predicate
        (``has_lost`` OR ``attempted_draw_on_empty`` OR ``life<=0``)
        documented to "surface the loss before the next SBA pass,
        mirroring Python's eager ``p.has_lost = True`` in
        ``turn.draw_card``" — i.e. it is the byte-equal Rust analog of
        Python's eager ``has_lost`` at the shadow STATE_EQ compare
        points. Using it (NOT raw Rust ``has_lost``) is what makes the
        port match the Python source-of-truth exactly (G5)."""
        return frozenset(int(pid) for pid in self._rust.losers())

    def _next_alive_idx(self, start_idx: int) -> int:
        """Byte-exact port of Python's ``simulate._next_alive``
        (``simulate.py:46``): start at ``start_idx``, walk
        ``+1 mod n_players`` skipping players Python treats as
        ``has_lost``, return the first alive one; if ALL are lost
        return ``start_idx`` unchanged (mirror ``_next_alive``'s
        all-lost fallback precisely — do NOT invent different
        all-lost behavior).

        The Python source-of-truth applies ``_next_alive`` at every
        priority/active reset (``engine_adapter.py:966/974/985/1151``,
        the combat-defender picks ``:1256/:1331``, and
        ``simulate._advance_to_next_active_player`` ``:432``). The
        Rust-driver adapter previously set priority to the raw active
        player UNCONDITIONALLY (the "2-player no-loss model"
        simplifying assumption flagged in
        ``_reset_priority_to_active``'s own docstring); in the
        post-player-loss tail (a decked-out active player) that
        diverged ``priority_player`` then ``active_player`` from the
        Python SoT (blocker G5). This helper closes that gap by
        mirroring ``_next_alive`` exactly."""
        n = self._n_players()
        lost = self._lost_set()
        idx = start_idx % n
        for _ in range(n):
            if idx not in lost:
                return idx
            idx = (idx + 1) % n
        return start_idx % n

    def _alive_count(self) -> int:
        """Mirror Python's pass-round-complete threshold
        ``sum(1 for p in state.players if not p.has_lost)``
        (``engine_adapter.py:953-956``). Pre-loss this is 2 (the
        no-loss 2-player model); once a player decks out Python's
        round completes after the single remaining player passes — the
        Rust-driver port must use the same alive count so the
        pass-round bookkeeping stays byte-equal in the post-loss tail
        (G5)."""
        return self._n_players() - len(self._lost_set())

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

    def _reset_priority_to_active(self) -> None:
        """Set Rust ``priority_player`` to the active player — the
        Rust-side port of ``MtgGameStateAdapter._enter_priority_for_
        current_step`` (``engine_adapter.py:1146-1153``) and the
        ``_run_priority_action`` priority resets
        (``:966,:985-987``). The Python adapter ALWAYS returns
        priority to the active player after a step ends, after a stack
        resolution (CR 117.1c), and after any non-pass action; Rust's
        ``advance_phase`` does NOT reset priority (only its
        CLEANUP->UNTAP wrap does), and ``pass_priority`` only toggles
        — so the provider must mirror the Python reset explicitly to
        keep ``priority_player`` byte-equal (the S4 STATE_EQ tripwire
        surfaced this; new-code-is-right — match the Python SoT).

        The reset target is Python's
        ``_next_alive(state, state.active_player_idx)`` — the CR-aware
        alive-skipping walk, NOT the raw active player. The three
        Python sites this mirrors all start at ``active_player_idx``:
        post-resolution (``engine_adapter.py:966``), post-non-pass-
        action (``:985``), and ``_enter_priority_for_current_step``
        / step-end (``:1151``). In the post-player-loss tail the
        active player can itself be decked-out; Python's ``_next_alive``
        skips it (G5 — the previous unconditional ``active_player_idx``
        reset diverged ``priority_player`` here)."""
        target = self._next_alive_idx(int(self._rust.active_player_idx))
        if int(self._rust.get_priority_player()) != target:
            self._rust.give_priority_to(target)

    def _run_step_enter_sbas(self) -> None:
        """Rust-side port of Python's ``state_based_actions`` calls
        inside ``MtgGameStateAdapter._enter_step`` — the G6 closure.

        **Root cause (verified — see ``test_post_player_loss_is_over_
        timing_is_closed`` and ``scripts/trace_g6*.py`` evidence).**
        Python's source-of-truth ``_enter_step`` runs
        ``state_based_actions(self._state)`` at UPKEEP
        (``engine_adapter.py:1224``), BEGINNING_OF_COMBAT (``:1238``),
        POSTCOMBAT_MAIN (``:1244``), END (``:1268`` + the post-delayed-
        trigger ``:1271``), and — *conditionally* — COMBAT_DAMAGE
        (``:1264``, guarded ``if any(o.attacking ...)``). Those SBA
        passes are what flip ``is_over`` / ``winner_id`` (and lock in
        any other SBA-derived field) the step after a player decks
        out. The Rust-driver port already mirrors Python's OTHER two
        ``state_based_actions`` sites — post-resolution
        (``:961`` -> this module's ``apply_sbas()`` after
        ``resolve_top_of_stack``) and post-non-pass-action
        (``:980`` -> ``apply_sbas()`` after ``apply_action``) — but
        had NO SBA on the step-end / auto-advance path, so Rust's
        ``is_over()`` / ``winner_id`` lagged Python's by a step. This
        method supplies exactly the missing call at exactly Python's
        ``_enter_step`` cadence — no more, no fewer (over-calling at a
        phase Python skips can byte-shift state or mask a different
        divergence; ``feedback_no_fallback_hybrids``).

        Single-pass ``apply_sbas()`` (NOT
        ``apply_sbas_until_quiescent``) for byte-consistency with the
        two already-ported sites; the Rust pymethod's player-loss /
        write-once-``winner_id`` transition is idempotent and
        documented stable (``state_ops_sba.rs:328-362``), so re-entry
        after a prior pass is a no-op on the G6 axis. Called
        immediately AFTER an ``advance_phase()`` that lands on a new
        step on the step-progression path — the byte-equivalent moment
        to Python's ``_enter_step`` running just after
        ``_advance_to_next_step`` ticked ``state.step`` forward.
        """
        phase = self._phase()
        if phase in _ENTER_STEP_SBA_PHASES:
            self._rust.apply_sbas()
        elif phase == _PHASE_COMBAT_DAMAGE:
            # COMBAT_DAMAGE: Python's source-of-truth
            # ``_enter_step(COMBAT_DAMAGE)`` runs
            # ``resolve_combat_damage(state, defender_id)`` FOLLOWED
            # by ``state_based_actions(state)``, both guarded by
            # ``if any(o.attacking for o in self._state.battlefield)``
            # (engine_adapter.py:1255-1264). Mirror that BOTH-PARTS
            # cadence here — the SBA-only port was the @504/@431
            # combat-damage outcome / SBA divergence root cause: Rust
            # ran SBAs over a battlefield that had NOT been damaged,
            # so lethally-damaged creatures stayed alive (arch5/s0
            # step 504 STATE_EQ ('graveyard_p0', ...) — Python killed
            # Icecave Crasher + Seedship Agrarian; Rust did not.
            # arch30/s1 step 431 STATE_EQ ('life_p0', 16, 20) —
            # Python applied 4 damage from unblocked Thawbringer; Rust
            # did not).
            #
            # ``deal_combat_damage`` (state_ops_combat.rs:923) runs
            # the byte-equivalent two-pass damage application
            # (first-strike + regular substeps, CR 702.7/702.4) —
            # documented limitation: no SBA between substeps (Python
            # runs one at combat.py:318); that documented divergence
            # is out of scope for this slice (no first-strike at play
            # in @504/@431) and tracked separately.
            #
            # Same ``get_attackers()`` guard as the SBA call: when no
            # creature attacked, ``deal_combat_damage`` walks an empty
            # plan (no-op) and SBA is skipped — matching Python's
            # ``if any(o.attacking ...)`` short-circuit precisely.
            if list(self._rust.get_attackers()):
                self._rust.deal_combat_damage()
                self._rust.apply_sbas()
        elif phase == _PHASE_END_OF_COMBAT:
            # END_OF_COMBAT post-hook — mirror Python's
            # ``engine_adapter.py:1282-1283`` (which mirrors
            # ``simulate.run_step``'s END_OF_COMBAT tail at
            # ``simulate.py:404-405``): ``clear_combat_state`` resets
            # ``attacking`` / ``blocking`` / ``blocked_by`` on every
            # battlefield object + expires "until end of combat"
            # continuous effects + processes
            # ``pending_end_of_combat_sacrifices``. Rust's
            # ``clear_combat()`` (state_ops_combat.rs:1381) clears
            # the equivalent Rust state — ``self.attackers`` and
            # ``self.blockers`` Vecs (Rust models combat as Vecs on
            # the GameState; the field-view fingerprint reads
            # ``attacking`` etc. straight off those Vecs via
            # ``state_ops_snapshot``).
            #
            # The pre-fix bridge skipped this entirely — Rust's
            # ``self.attackers`` Vec stayed populated turn-to-turn,
            # invisible at most field-views (because no consumer
            # walked it) UNTIL the @504/@431 sibling slice added a
            # ``deal_combat_damage()`` call at every COMBAT_DAMAGE
            # entry. Without this END_OF_COMBAT clear, the stale Vec
            # fires phantom damage on the NEXT turn's COMBAT_DAMAGE
            # even when the new active player declared zero attackers
            # (arch30/s1 trace step 458: ``rust.attackers=[80]`` from
            # the prior turn's Thawbringer attack, ``py.attackers=[]``
            # — Rust applied 4 phantom damage to p1; Python applied
            # zero). Same fix surface as the @504/@431 closure: this
            # branch IS the second half of the same one-axis G2 fix.
            self._rust.clear_combat()

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
                # G6: Python's ``_advance_to_next_decision`` calls
                # ``_enter_step`` on the step it just landed on, which
                # runs ``state_based_actions`` for the SBA-bearing
                # steps. Mirror that at the byte-equivalent moment —
                # immediately after the phase tick — so a deck-out that
                # the auto-step transition crosses (e.g. the
                # CLEANUP->UNTAP->UPKEEP wrap landing on UPKEEP) flips
                # ``is_over``/``winner_id`` in lockstep with Python.
                self._run_step_enter_sbas()
                self._invalidate_legal_cache()
                self._pass_count = 0
                continue
            # A priority phase (incl. the factored-combat declare
            # phases) — the caller must decide here. Priority is NOT
            # reset here: the Python adapter resets priority ONLY at
            # the points _run_priority_action handles (step-end /
            # resolution / non-pass action — mirrored there) and on a
            # single in-round pass priority correctly moves to the
            # OTHER player (engine_adapter.py:972-977). Resetting here
            # would clobber that mid-round handoff (the S4 STATE_EQ
            # tripwire surfaced exactly this: a single-pass window
            # must keep priority at the opponent, not the active
            # player).
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
                    # — that does not fire effects). CR 117.1c: priority
                    # returns to the active player after a resolution
                    # (engine_adapter.py:966). Mirror it explicitly —
                    # resolve_top_of_stack does not guarantee the
                    # priority reset on its own.
                    self._rust.resolve_top_of_stack()
                    self._rust.apply_sbas()
                    self._reset_priority_to_active()
                else:
                    # Empty stack, both passed -> the step ends. The
                    # Python adapter advances the step and (via
                    # _enter_priority_for_current_step) returns priority
                    # to the active player; advance_phase does NOT, so
                    # mirror the reset (engine_adapter.py:971 ->
                    # :1146-1153). _advance_to_next_decision also
                    # resets at the next priority window, but resetting
                    # here keeps priority_player byte-equal at THIS
                    # post-apply compare point (the S4 STATE_EQ check
                    # runs immediately after apply()).
                    self._rust.advance_phase()
                    # G6: Python's empty-stack pass-round end is
                    # ``_advance_to_next_step()`` (engine_adapter.py
                    # :971) followed by ``_advance_to_next_decision``
                    # ->``_enter_step(new step)`` which runs
                    # ``state_based_actions`` for the SBA-bearing
                    # steps. The Rust ``advance_phase`` here is the
                    # ``_advance_to_next_step`` analog; mirror the
                    # ``_enter_step`` SBA at the byte-equivalent
                    # moment (right after the phase tick, BEFORE the
                    # priority reset / the post-apply STATE_EQ check).
                    # This is the exact site the G5 closure unmasked
                    # as G6 — a post-deck-out PRECOMBAT_MAIN pass-round
                    # advancing to BEGINNING_OF_COMBAT, whose SBA flips
                    # ``is_over``/``winner_id`` on the Python SoT.
                    self._run_step_enter_sbas()
                    # **G7 S6 Class-B option-β — the coordinated
                    # adapter half (DEFERRED priority reset).** Python's
                    # source-of-truth does NOT reset priority when the
                    # step it just advanced into is a factored-combat
                    # step: ``_advance_to_next_step`` ->
                    # ``_enter_step(DECLARE_ATTACKERS / DECLARE_BLOCKERS)``
                    # dispatches to ``_enter_declare_attackers`` /
                    # ``_enter_declare_blockers``
                    # (``engine_adapter.py:1312-1316/:1358-1361``),
                    # which — when there is an eligible factored
                    # decision — set ``_combat_phase`` and RETURN
                    # WITHOUT ``_enter_priority_for_current_step``. So
                    # ``priority_player_idx`` stays CARRIED through the
                    # whole factored-combat decision window (the
                    # ``simulate.py`` SoT: ``run_step(DECLARE_ATTACKERS)``
                    # does NOT touch ``priority_player_idx``; only the
                    # subsequent ``priority_loop``'s first pass resets
                    # it, AFTER the attacker decision —
                    # ``simulate.py:222-247``). The pre-option-β
                    # unconditional reset here forced
                    # ``priority_player = active``, diverging from the
                    # SoT's carried value (the arch5/s0 step-367
                    # ``STATE_EQ ('priority_player',1,0)``). Mirror
                    # Python: skip the reset iff the just-entered step
                    # is a factored-combat window with a pending
                    # factored decision for the structural
                    # decision-maker (the same structural test the
                    # option-β engine gate embodies — if Rust emits NO
                    # factored decision, e.g. no eligible
                    # attackers/blockers, Python's ``_enter_declare_*``
                    # ITSELF falls through to
                    # ``_enter_priority_for_current_step``, so we still
                    # reset). Outside a factored-combat window the reset
                    # is unchanged (every prior G3/G4/G5/G6 closure
                    # depends on it). See
                    # ``docs/G7_MIDGAME_STATEEQ_VERIFY_FINDING.md``
                    # §9/§9.1.
                    if (
                        not self._rust.is_over()
                        and self._combat_decision_maker() is None
                    ):
                        self._reset_priority_to_active()
            else:
                # Single in-round pass — Python sets
                # ``priority = _next_alive((pid + 1) % n_players)``
                # (engine_adapter.py:974-977), NOT a raw toggle: in the
                # post-player-loss tail the "other" player can be
                # decked-out, and Python's alive-skip keeps priority on
                # the sole survivor (G5). ``pass_priority()`` is kept
                # for its CR-117.3 ``consecutive_passes`` bump (it is
                # not in the STATE_EQ field view, but preserving it
                # keeps Rust's internal pass bookkeeping honest); the
                # alive-skip then corrects the holder to the
                # ``_next_alive`` target when the raw toggle would land
                # on a lost player.
                pid = int(self._rust.get_priority_player())
                self._rust.pass_priority()
                target = self._next_alive_idx(
                    (pid + 1) % self._n_players()
                )
                if int(self._rust.get_priority_player()) != target:
                    self._rust.give_priority_to(target)
        else:
            # **G7 @808 G3 deferred-batch combat-decision apply / B3-S3
            # provider-accumulation port (phase 2).** For
            # ``AttackerDecision`` / ``BlockerDecision`` the engine
            # apply is **deferred to finalize** — adapter-side
            # bookkeeping only, NO per-decision engine call. Python's
            # SoT (``MtgGameStateAdapter._apply_attacker_decision`` /
            # ``_apply_blocker_decision``, ``engine_adapter.py:
            # 1080-1131``) does ZERO engine mutation per factored
            # decision; the only engine write is the batched
            # ``apply_action(state, ap.id, DeclareAttackers(frozenset(
            # _chosen_attackers)))`` call inside
            # ``_finalize_attacker_phase``
            # (``engine_adapter.py:1101-1108``). The pre-G3 G1 port
            # mirrored Python's queue-pop / finalize boundary but
            # still routed each ``AttackerDecision`` through Rust's
            # ``apply_action(Action::AttackerDecision)`` — which
            # per-decision calls ``declare_attacker(obj_id)``
            # (``state_ops_actions.rs:1382-1384`` →
            # ``state_ops_combat.rs:declare_attacker``), tapping the
            # creature + appending to ``state.attackers`` EAGERLY. So
            # for a factored sequence like
            # ``[AttackerDecision(70,True), AttackerDecision(120,?),
            #   AttackerDecision(121,?)]`` Rust had Knight Luminary
            # tapped + on ``state.attackers`` AFTER step 1 while
            # Python kept it untapped + bookkept in
            # ``_chosen_attackers`` until finalize — surfaced as the
            # arch7/s0 step-808 ``STATE_EQ`` ``('priority_player',
            # 0, 1)`` + Knight Luminary battlefield ``tapped`` diff
            # divergence (Rust per-decision ``apply_sbas`` /
            # ``_reset_priority_to_active`` ALSO ran per decision, so
            # the priority axis tracked the tap eagerly). G3 routes
            # both factored decisions through adapter-only
            # bookkeeping; the batched
            # ``{"kind":"declare_attackers","attacker_ids":[...]}`` /
            # ``{"kind":"declare_blockers","assignments":[...]}``
            # engine call happens ONCE in
            # ``_finalize_attacker_phase`` /
            # ``_finalize_blocker_phase`` exactly mirroring Python.
            # Per-decision priority resets are removed too — Python's
            # ``_apply_attacker_decision`` does not touch priority,
            # only finalize's ``_enter_priority_for_current_step``
            # does.
            if isinstance(decision, AttackerDecision):
                if not (
                    self._pending_attackers
                    and self._pending_attackers[0] == int(decision.attacker_id)
                ):
                    # **Loud failure** (feedback_silent_noop_pipelines):
                    # An ``AttackerDecision`` for an id that isn't the
                    # pending head means either a stale apply (the
                    # adapter's queue went out of sync) or a
                    # bypassed legal_decisions() filter. Either way
                    # silently accepting it would mask a real bug —
                    # raise instead.
                    raise ValueError(
                        f"RustGameStateAdapter: AttackerDecision for "
                        f"id={decision.attacker_id} but pending queue "
                        f"head is "
                        f"{self._pending_attackers[0] if self._pending_attackers else None} "
                        f"(queue={self._pending_attackers}). The "
                        f"adapter-side _pending_attackers must stay in "
                        f"lock-step with the deferred-batch apply — "
                        f"re-derivation is forbidden within a "
                        f"factored-combat window."
                    )
                if decision.attack:
                    self._chosen_attackers.append(int(decision.attacker_id))
                self._pending_attackers.pop(0)
                if not self._pending_attackers:
                    # Finalize: the single batched
                    # ``declare_attackers`` apply lives here.
                    self._finalize_attacker_phase()
                # **NO per-decision priority reset, NO per-decision
                # apply_sbas, NO _pass_count reset** — Python's
                # ``_apply_attacker_decision`` does not touch any of
                # those. The factored window is a sub-decision
                # axis inside DECLARE_ATTACKERS; the priority window
                # opens (with its priority reset + pass_count=0)
                # ONLY at finalize via
                # ``_enter_priority_for_current_step`` in
                # ``_finalize_attacker_phase``.
                return
            if isinstance(decision, BlockerDecision):
                if not (
                    self._pending_blockers
                    and self._pending_blockers[0] == int(decision.blocker_id)
                ):
                    raise ValueError(
                        f"RustGameStateAdapter: BlockerDecision for "
                        f"id={decision.blocker_id} but pending queue "
                        f"head is "
                        f"{self._pending_blockers[0] if self._pending_blockers else None} "
                        f"(queue={self._pending_blockers}). The "
                        f"adapter-side _pending_blockers must stay in "
                        f"lock-step with the deferred-batch apply — "
                        f"re-derivation is forbidden within a "
                        f"factored-combat window."
                    )
                if decision.attacker_id is not None:
                    self._chosen_blocks[int(decision.blocker_id)] = int(
                        decision.attacker_id
                    )
                self._pending_blockers.pop(0)
                if not self._pending_blockers:
                    self._finalize_blocker_phase()
                return

            d = decision_to_rust_dict(decision)
            # G2 interim mask bookkeeping: record the land drop so the
            # next legal_decisions() filters the structurally-over-
            # offered extra PlayLand(s) (Rust has no
            # lands_played_this_turn field). Recorded BEFORE apply so a
            # mid-apply raise still marks the attempt consistently
            # (apply is the hard gate either way).
            if d.get("kind") == "play_land":
                self._land_played_on_turn = int(self._rust.turn_number)
            self._rust.apply_action(d)
            self._rust.apply_sbas()
            self._pass_count = 0
            # CR 117.3c / engine_adapter.py:985-987: priority returns
            # to the active player after any non-pass action. Rust's
            # apply_action does not guarantee this; mirror it.
            if not self._rust.is_over():
                self._reset_priority_to_active()

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
        c._printing_resolver = self._printing_resolver
        c._pass_count = self._pass_count
        c._land_played_on_turn = self._land_played_on_turn
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
        c._finalized_combat_window = self._finalized_combat_window
        return c

    def _combat_decision_maker(self) -> Optional[int]:
        """The factored-combat decision-maker, or ``None`` if this is
        NOT a factored-combat decision window.

        **G7 S6 Class-B option-β — the coordinated adapter half.**
        Byte-mirror of Python ``MtgGameStateAdapter.active_player()``'s
        ``_COMBAT_*`` overrides (``engine_adapter.py:762-766``): during
        DECLARE_ATTACKERS the decision-maker is the active player; during
        DECLARE_BLOCKERS it is the structural defender
        (``_combat_defender_id = _next_alive(state,(active+1)%n)``, which
        in the loader-admitted no-loss 2-player model is
        ``1 - active``). The Rust ENGINE's option-β
        ``legal_decisions`` now keys the factored-combat emission on
        exactly that structural decision-maker (attackers:
        ``active_player == player_id``; blockers:
        ``player_id == 1 - active_player`` — the SAME
        ``1 - self.active_player`` Rust's combat-damage plan uses,
        ``state_ops_combat.rs:941``); the eager
        ``_reset_priority_to_active`` is deferred for these windows so
        Rust's ``priority_player`` stays CARRIED like the
        ``simulate.py`` SoT (and like Python's ``_enter_declare_*``
        which return WITHOUT ``_enter_priority_for_current_step``). So
        — exactly as Python's adapter computes the decision-maker
        independent of ``priority_player_idx`` during the
        factored-combat window — we resolve it structurally here:
        confirm the phase is a combat-declare phase AND Rust actually
        emits a factored decision for the structural decision-maker
        (the same existence check the option-β engine gate embodies;
        if Rust emits NOTHING — e.g. no eligible attackers/blockers —
        this is NOT a factored-combat window and the priority holder
        is the decision-maker, mirroring Python's ``_enter_declare_*``
        falling through to ``_enter_priority_for_current_step``)."""
        ph = self._phase()
        if ph not in _COMBAT_DECLARE_PHASES:
            return None
        # **G7 @369**: if we already finalized the factored window for
        # this (turn, phase) the adapter is in the priority window —
        # the priority holder is the decision-maker, mirroring
        # Python's adapter once _combat_phase has been cleared by
        # ``_finalize_attacker_phase`` / ``_finalize_blocker_phase``
        # (``engine_adapter.py:1109/:1141``: ``_combat_phase = _COMBAT_NONE``
        # makes ``active_player()`` return the priority holder).
        cur_window = (
            int(self._rust.turn_number),
            ph,
        )
        if self._finalized_combat_window == cur_window:
            return None
        act = int(self._rust.active_player_idx)
        if ph == _PHASE_DECLARE_ATTACKERS:
            dm = act
            kind = "attacker_decision"
        else:  # _PHASE_DECLARE_BLOCKERS — structural defender
            dm = 1 - act
            kind = "blocker_decision"
        for d in self._legal_dicts_cached(dm):
            if d.get("kind") == kind:
                return dm
        return None

    def active_player(self) -> PlayerID:
        # **G7 S6 Class-B option-β (coordinated adapter half).** Byte-
        # mirror Python ``MtgGameStateAdapter.active_player()``
        # (``engine_adapter.py:753-767``): during the factored-combat
        # windows the decision-maker is NOT whoever holds engine
        # priority — it is the active player (attacker decisions) or
        # the structural defender (blocker decisions); only outside a
        # factored-combat window is the priority holder the
        # decision-maker. Pre-option-β this returned ``_priority_pid()``
        # unconditionally, which was correct ONLY because the
        # Rust-driver adapter forced ``priority_player == active``
        # during combat. With the coordinated change carrying
        # ``priority_player`` like the SoT, the priority holder is no
        # longer the combat decision-maker — so resolve it structurally
        # (the ``_combat_decision_maker`` helper), exactly as Python's
        # adapter does via its ``_combat_phase`` overrides.
        dm = self._combat_decision_maker()
        if dm is not None:
            return dm
        return self._priority_pid()

    def legal_decisions(self) -> list[Decision]:
        if self._rust.is_over():
            return []
        # **G7 S6 Class-B option-β (coordinated adapter half).** Query
        # Rust for the DECISION-MAKER, not the raw priority holder.
        # Pre-option-β ``pid = self._priority_pid()`` was correct only
        # because the adapter forced ``priority_player == active``
        # during the factored-combat window, so the priority holder
        # WAS the decision-maker. With the coordinated change carrying
        # ``priority_player`` like the ``simulate.py`` SoT, the
        # priority holder is no longer the combat decision-maker — the
        # option-β Rust ``legal_decisions`` keys the factored-combat
        # emission on the STRUCTURAL decision-maker (attackers: active;
        # blockers: ``1 - active``), so querying Rust with the carried
        # priority pid would suppress the factored emission entirely
        # (Rust would return just ``[PassPriority]`` for the
        # non-decision-maker). ``active_player()`` already resolves to
        # the combat decision-maker during a factored-combat window
        # (else the priority holder) — byte-mirroring Python
        # ``MtgGameStateAdapter.legal_decisions()`` which emits the
        # factored decisions off ``_combat_phase`` for the
        # decision-maker and the priority-window set for the priority
        # holder. ``_combat_decision_maker()`` (called inside
        # ``active_player()``) primes the per-decision legal cache for
        # the decision-maker, so this is a single Rust round-trip. See
        # ``docs/G7_MIDGAME_STATEEQ_VERIFY_FINDING.md`` §9/§9.1.
        pid = self.active_player()
        dicts = self._legal_dicts_cached(pid)
        # G2 interim mask (spec §2.4-G2): if a land was already
        # played this turn, filter the structurally-over-offered
        # PlayLand dict(s) Rust still emits (no lands_played_this_turn
        # field). max_lands == 1 on the loader-admitted surface, so
        # ANY prior land this turn ⇒ no further PlayLand is legal.
        # Mirrors the MtgGameStateAdapter._should_force_landdrop
        # adapter-filter pattern (a list-comprehension prune, never a
        # reorder). PARITY-SAFE: dormant under decision_source=python
        # (this provider is not constructed); under rust_shadow the
        # S4 LEGAL_SET_EQ assertion verifies the filtered set equals
        # Python's legal_actions.
        if (
            self._land_played_on_turn is not None
            and self._land_played_on_turn == int(self._rust.turn_number)
        ):
            dicts = [
                d for d in dicts if d.get("kind") != "play_land"
            ]
        # B3-S3: refresh the factored-combat-phase bookkeeping from
        # the current Rust emission so the codec's combat-slot path
        # (_combat_phase(state) / state._pending_attackers /
        # _attacking_creatures) encodes correctly. G1 made Rust
        # legal_decisions emit the factored per-creature dicts AND
        # the apply arms accumulate the declared set internally —
        # so the provider does NOT re-implement the Python adapter's
        # _chosen_attackers accumulation (engine_adapter.py:1080-1144);
        # it only mirrors the phase + pending-HEAD bookkeeping the
        # codec reads. Stateless-Rust / stateful-codec-view split, per
        # the G1 emission docstring.
        self._refresh_combat_phase(dicts)
        # **G7 S6 Class-B option-β (coordinated adapter half).** During
        # a factored-combat decision window Python's
        # ``MtgGameStateAdapter.legal_decisions()`` returns EXACTLY the
        # factored ``AttackerDecision`` / ``BlockerDecision`` list —
        # NO ``PassPriority`` (``engine_adapter.py:808-828``: the
        # ``_combat_phase`` branches ``return`` only the factored
        # options). Rust's ``state_ops_legal.rs:legal_decisions``
        # ALWAYS pushes ``PassPriority`` at index 0
        # (``state_ops_legal.rs:1194-1195``) before any factored dict,
        # so the raw Rust combat-window set carries an extra
        # ``('pass',)`` vs the Python adapter's factored emission. The
        # ``rust_shadow`` LEGAL_SET_EQ reference for a combat window IS
        # the Python adapter's factored ``legal_decisions()``
        # (``rust_shadow.py:281-286``), so the Rust-driver adapter must
        # mirror Python and drop the structural ``PassPriority`` while
        # a factored-combat decision is pending. (Other comparison
        # contexts already filter Rust's combat dicts to the
        # ``attacker_decision``/``blocker_decision`` kind explicitly —
        # e.g. ``tests/test_cross_engine_legal_set_factored_combat``'s
        # ``_rs_combat_dicts`` — confirming Rust's raw set legitimately
        # includes the structural Pass; the Python ADAPTER's combat
        # emission is the byte-faithful target here.) This was masked
        # while arch5/s0 tripped at step 344/367 before any
        # combat-window-WITH-attackers; closing step 367 surfaced it.
        # Outside a factored-combat window the set is UNCHANGED (the
        # genuine priority-window Pass is preserved). See
        # ``docs/G7_MIDGAME_STATEEQ_VERIFY_FINDING.md`` §9/§9.1.
        if self._combat_phase in (_COMBAT_ATTACKERS, _COMBAT_BLOCKERS):
            dicts = [
                d for d in dicts if d.get("kind") != "pass_priority"
            ]
            # **G7 @369 G1 stateless-Rust attack=False re-emission /
            # B3-S3 provider-accumulation port.** Within a
            # factored-combat window the legal set must be exactly
            # the factored option pair for OUR queue's HEAD (not
            # whatever Rust's emitter chose as ``min(eligible)``).
            # Pre-port these were identical because every applied
            # ``attack=True`` tapped the creature so Rust's
            # min(eligible) advanced in lockstep with the queue pop.
            # An ``attack=False`` decision leaves the creature
            # eligible — so Rust still emits a factored pair for the
            # SAME id while our queue has advanced past it (the @369
            # arch5/s0 / @757 arch7/s0 / @321 arch30/s1 root cause).
            # Synthesize the (id, True) + (id, False) pair for
            # ``_pending_attackers[0]`` / ``_pending_blockers[0]`` and
            # drop Rust's factored emission entirely — byte-mirroring
            # Python adapter ``legal_decisions()``
            # (``engine_adapter.py:808-828``) which emits the two
            # factored options for the queue head and nothing else.
            if self._combat_phase == _COMBAT_ATTACKERS and self._pending_attackers:
                head = int(self._pending_attackers[0])
                dicts = [
                    {"kind": "attacker_decision", "attacker_id": head, "attack": True},
                    {"kind": "attacker_decision", "attacker_id": head, "attack": False},
                ]
            elif self._combat_phase == _COMBAT_BLOCKERS and self._pending_blockers:
                head = int(self._pending_blockers[0])
                # The blocker options: one BlockerDecision per
                # attacking creature (block target), plus a "no-block"
                # (attacker_id=None) decision. Byte-mirrors Python
                # adapter ``_combat_phase == _COMBAT_BLOCKERS`` branch
                # (``engine_adapter.py:815-828``): one BlockerDecision
                # per attacking id in ``state.attackers`` membership
                # (i.e. ``state.battlefield`` where ``o.attacking`` is
                # True), plus the None option.
                attacking_ids = sorted(int(a) for a in self._rust.get_attackers())
                dicts = [
                    {"kind": "blocker_decision",
                     "blocker_id": head, "attacker_id": atk}
                    for atk in attacking_ids
                ]
                dicts.append(
                    {"kind": "blocker_decision",
                     "blocker_id": head, "attacker_id": None}
                )
        else:
            # **Post-finalize / outside-window guard.** If Rust still
            # emits factored ``attacker_decision`` / ``blocker_decision``
            # dicts (e.g. an attack=False creature stays eligible after
            # finalize), filter them OUT — Python's adapter in the
            # priority window emits ONLY the priority-window set, not
            # any factored combat option.
            dicts = [
                d for d in dicts
                if d.get("kind") not in ("attacker_decision",
                                          "blocker_decision")
            ]
        return [rust_dict_to_decision(d) for d in dicts]

    def _refresh_combat_phase(self, dicts: list[dict]) -> None:
        """Set ``_combat_phase`` + the pending-head list for the
        current factored-combat window.

        **G7 @369 G1 stateless-Rust attack=False re-emission /
        B3-S3 provider-accumulation port.** Faithful mirror of
        Python ``MtgGameStateAdapter._enter_declare_attackers`` /
        ``_enter_declare_blockers`` (``engine_adapter.py:1288-1361``):
        on FIRST ENTRY into the factored-combat window we capture the
        FULL sorted eligible-attacker (or eligible-blocker) id list
        and store it as ``_pending_attackers`` (or ``_pending_blockers``).
        Within the same factored-combat window subsequent calls to
        this method LEAVE the in-flight queue alone — the
        ``_run_priority_action`` ``AttackerDecision``/
        ``BlockerDecision`` arms pop the head, and ``_finalize_*_phase``
        transitions out when the queue is exhausted. Python's
        ``_pending_attackers`` is sized ONCE at ``_enter_declare_*``
        and only mutated by pop / finalize — never re-derived from
        the current eligible set (a vigilance attacker that already
        declared ``attack=True`` is still eligible-by-Rust-criteria
        but Python's queue head has advanced past it; same for an
        already-declared-with-``attack=False`` attacker that stays
        eligible because Rust did not tap it).

        Pre-port (legacy behavior, retained as the empty-fallback
        below): the queue was sized to ``[head]`` from the head Rust
        currently emits a factored decision for, RE-DERIVED every
        ``legal_decisions()`` call. That was correct only because the
        ``attack=True`` path tapped the head (so Rust naturally
        advanced to the next ``min(eligible)``) and the
        ``attack=False`` path had never been exercised on the
        bake-in surface — the @369 frontier is exactly the case where
        ``attack=False`` leaves the creature eligible and the
        re-derive emits the SAME head again forever, while Python's
        queue has advanced past it.

        The codec reads ``getattr(state, "combat_phase", None)`` and
        ``state._pending_attackers[0]`` / ``_pending_blockers[0]``
        (``action_encoding.py:973-1012``) to encode the implicit-head
        ATTACKER/BLOCKER slots; the SAME ``_pending_attackers[0]``
        Python's adapter exposes is now exposed here too."""
        atk_heads = [
            int(d["attacker_id"]) for d in dicts
            if d.get("kind") == "attacker_decision"
        ]
        blk_heads = [
            int(d["blocker_id"]) for d in dicts
            if d.get("kind") == "blocker_decision"
        ]
        # Detect the factored-combat-window axis Rust is emitting on
        # this call. Rust's emission is keyed structurally on
        # phase/active/defender + non-empty eligible (state_ops_legal.rs
        # :1308-1397 / :1400-1576), so atk_heads/blk_heads non-empty
        # iff we're INSIDE the relevant factored-combat window with
        # an eligible decision-maker.
        #
        # **Suppress factored entry on a (turn, phase) we already
        # finalized.** Once _finalize_*_phase has run for this
        # (turn, phase) the adapter is in the priority window —
        # Python's _combat_phase == None / _enter_priority_for_current_step
        # state. Rust's emitter is still structurally in
        # DECLARE_ATTACKERS / DECLARE_BLOCKERS and may still emit
        # factored dicts (e.g. an attack=False creature stays
        # eligible), but those dicts no longer represent a real
        # decision moment — the queue was exhausted. Treat as
        # phase_axis = NONE so the priority-window set is returned.
        cur_window = (
            int(self._rust.turn_number),
            int(self._rust.current_phase()),
        )
        if self._finalized_combat_window == cur_window:
            phase_axis = _COMBAT_NONE
        elif atk_heads:
            phase_axis = _COMBAT_ATTACKERS
        elif blk_heads:
            phase_axis = _COMBAT_BLOCKERS
        else:
            phase_axis = _COMBAT_NONE

        if phase_axis == _COMBAT_NONE:
            # Outside a factored-combat window. If the adapter still
            # has a leftover in-flight queue (e.g. from a previous
            # turn that finalized cleanly) clear it.
            self._combat_phase = _COMBAT_NONE
            self._pending_attackers = []
            self._pending_blockers = []
            return

        if phase_axis == _COMBAT_ATTACKERS:
            # ENTRY: only initialize the queue on the transition into
            # the ATTACKERS window (mirrors Python's
            # _enter_declare_attackers which is called ONCE per phase
            # entry). On subsequent in-window calls the queue is
            # in-flight and must NOT be overwritten — that would
            # re-derive the head from Rust's emission and lose track
            # of which attackers have already been decided
            # (the @369 root cause).
            if self._combat_phase != _COMBAT_ATTACKERS:
                self._combat_phase = _COMBAT_ATTACKERS
                self._pending_attackers = self._compute_eligible_attackers(
                    int(self._rust.active_player_idx)
                )
                self._chosen_attackers = []
                self._pending_blockers = []
            return

        # phase_axis == _COMBAT_BLOCKERS
        if self._combat_phase != _COMBAT_BLOCKERS:
            self._combat_phase = _COMBAT_BLOCKERS
            # The defender id is the structural ``1 - active`` (the
            # no-loss 2-player model — same gate Rust's blocker
            # emission uses, state_ops_legal.rs:1407).
            defender_id = 1 - int(self._rust.active_player_idx)
            self._pending_blockers = self._compute_eligible_blockers(
                defender_id
            )
            self._chosen_blocks = {}
            self._pending_attackers = []

    def _compute_eligible_attackers(self, player_id: int) -> list[int]:
        """Sorted list of eligible-attacker ids for ``player_id``.

        Byte-equal port of Rust's ``state_ops_legal.rs:1308-1343``
        eligibility filter (the canonical SoT for the Rust-driver
        side; ``combat.py:eligible_attackers`` is the upstream Python
        SoT — same predicate, different traversal source). Eligibility
        criteria: on the player's battlefield, not tapped, is a
        Creature (``card_types`` contains ``"Creature"``), not
        summoning-sick OR has the ``haste`` keyword, does not have the
        ``defender`` keyword.

        **UEOT-granted defender caveat (in-scope honest scope).**
        Rust's emitter uses ``battlefield_has_keyword`` for the
        defender check, which includes UEOT-granted keywords
        (``state_ops_combat.rs:355-361``). The ``battlefield_snapshot``
        pymethod does NOT surface UEOT-granted keywords, so this
        Python-side recomputation only honors **printed** defender. On
        the loader-admitted EoE pool there are zero cards that grant
        ``defender`` via a UEOT modifier (greppable: no
        ``UeotModifier::GrantKeyword(.., "defender")`` schedule); the
        gap is structurally empty on the production surface. If a
        UEOT-defender card ever lands the right place to fix is a
        Rust pymethod that returns the byte-equal eligibility set —
        filed as a follow-up todo if/when it surfaces.

        Returns ids in **sorted** order to byte-mirror Python's
        ``_enter_declare_attackers``:
        ``self._pending_attackers = sorted(o.id for o in eligible)``
        (``engine_adapter.py:1315``). Rust's emitter walks the
        battlefield in iteration order and emits the ``min`` of the
        eligible set — the SAME smallest-id head Python's
        ``sorted(...)[0]`` returns — so the head Rust emits a factored
        decision for and our queue's head are byte-equal on entry.
        """
        ids: list[int] = []
        for obj in self._rust.battlefield_snapshot():
            d = dict(obj)
            if int(d.get("controller_id", -1)) != int(player_id):
                continue
            if bool(d.get("tapped", False)):
                continue
            name = d.get("printing_name", "")
            printing = self._printing_resolver.get(name)
            if printing is None:
                # Unresolved printing on the admitted surface is a
                # hard data error elsewhere (RustZoneViewError); here
                # the safe behavior is to EXCLUDE — exclusion matches
                # Rust's emitter falling through on the
                # ``registry.lookup`` None arm
                # (state_ops_legal.rs:1320-1322).
                continue
            if "Creature" not in printing.card_types:
                continue
            has_haste = "haste" in printing.keywords
            if bool(d.get("summoning_sick", False)) and not has_haste:
                continue
            if "defender" in printing.keywords:
                continue
            ids.append(int(d["id"]))
        ids.sort()
        return ids

    def _compute_eligible_blockers(self, player_id: int) -> list[int]:
        """Sorted list of eligible-blocker ids for ``player_id``.

        Byte-equal port of Rust's ``state_ops_legal.rs`` blocker
        eligibility (controller is the defender, is a Creature, not
        tapped — summoning sickness does NOT exclude blocking per
        CR 302.1) and ``combat.py:eligible_blockers``. Returns
        sorted-ascending ids (mirrors Python adapter
        ``_enter_declare_blockers`` ``self._pending_blockers =
        sorted(o.id for o in eligible)``, ``engine_adapter.py:1360``).
        """
        ids: list[int] = []
        for obj in self._rust.battlefield_snapshot():
            d = dict(obj)
            if int(d.get("controller_id", -1)) != int(player_id):
                continue
            if bool(d.get("tapped", False)):
                continue
            name = d.get("printing_name", "")
            printing = self._printing_resolver.get(name)
            if printing is None:
                continue
            if "Creature" not in printing.card_types:
                continue
            ids.append(int(d["id"]))
        ids.sort()
        return ids

    def _finalize_attacker_phase(self) -> None:
        """Exit the factored-attacker window after the queue is
        exhausted.

        **G7 @808 G3 deferred-batch combat-decision apply / B3-S3
        provider-accumulation port (phase 2).** Faithful byte-mirror
        of Python ``MtgGameStateAdapter._finalize_attacker_phase``
        (``engine_adapter.py:1101-1112``). Four load-bearing actions
        in Python's order:

        1. **Apply the batched ``DeclareAttackers`` to the engine.**
           Python calls
           ``apply_action(state, ap.id, DeclareAttackers(frozenset(
           _chosen_attackers)))`` (``engine_adapter.py:1103-1108``)
           which dispatches to ``actions._declare_attackers`` →
           ``combat.declare_attackers``, which sets
           ``obj.attacking = True``, taps the creature (modulo
           vigilance), and fires the per-attacker
           ``BECOMES_TAPPED`` + ``ATTACKS`` triggers. Mirror this on
           the Rust side by calling
           ``apply_action({"kind":"declare_attackers",
           "attacker_ids":[...]})``, which dispatches to
           ``Action::DeclareAttackers`` →
           ``state_ops_combat.rs::declare_attacker`` per id (same
           per-attacker tap + ``Event::Attacks`` dispatch the Python
           SoT performs). The pre-G3 G1 port routed each factored
           ``AttackerDecision`` through Rust's apply per-decision,
           leaving the engine state out-of-sync with Python's batched
           apply mid-queue (the @808 ``priority_player`` + Knight
           Luminary tapped divergence). The batched call here is
           the SINGLE accumulation site, byte-mirroring Python.
        2. Reset combat-phase bookkeeping
           (``_combat_phase = None``, ``_chosen_attackers = []``).
        3. Enter the priority window for the current step
           (``_enter_priority_for_current_step``,
           ``engine_adapter.py:1112``). Rust's priority is set by
           ``_reset_priority_to_active`` here — byte-mirroring
           ``self._state.priority_player_idx = _next_alive(...,
           active_player_idx)`` (``engine_adapter.py:1151-1153``).
        4. Reset the pass-priority counter to 0 — Python's
           ``_enter_priority_for_current_step`` does this via
           ``self._pass_count = 0`` (``engine_adapter.py:1150``).

        Called from ``_run_priority_action``'s ``AttackerDecision``
        arm exactly when ``_pending_attackers`` becomes empty after
        the pop (mirrors ``engine_adapter.py:1098-1099``).
        """
        # Phase 1: batched engine apply. Sort the chosen ids so the
        # per-attacker dispatch order is deterministic across runs
        # (Python's frozenset has no stable iteration order; sorted
        # matches the Rust whole-action arm's ``Vec`` order from
        # ``extract::<Vec<u32>>()`` and lines up the per-attacker
        # ``ATTACKS`` trigger stack-push order). ``apply_sbas`` after
        # so state-based actions process any tap-induced changes
        # (mirrors the same ``apply_sbas`` Python's
        # ``apply_action`` calls after every action arm via
        # ``actions.py`` post-apply hook). Skip the engine apply
        # when no attackers were chosen — Rust's
        # ``Action::DeclareAttackers`` with an empty ``attacker_ids``
        # is a no-op (``state_ops_actions.rs:216-218`` iterates an
        # empty Vec), and Python's
        # ``apply_action(DeclareAttackers(frozenset()))`` is a
        # benign-but-real call that emits an empty
        # ``combat.declare_attackers(state, [])`` — equivalent. We
        # call only when non-empty to avoid the unnecessary engine
        # round-trip.
        if self._chosen_attackers:
            self._rust.apply_action({
                "kind": "declare_attackers",
                "attacker_ids": sorted(self._chosen_attackers),
            })
            self._rust.apply_sbas()
        self._combat_phase = _COMBAT_NONE
        self._chosen_attackers = []
        self._pass_count = 0
        # Tag this (turn, phase) as finalized so _refresh_combat_phase
        # does NOT re-enter the factored window on subsequent
        # legal_decisions() calls while Rust is still structurally in
        # DECLARE_ATTACKERS but Python is in the priority window.
        self._finalized_combat_window = (
            int(self._rust.turn_number),
            int(self._rust.current_phase()),
        )
        if not self._rust.is_over():
            self._reset_priority_to_active()

    def _finalize_blocker_phase(self) -> None:
        """Exit the factored-blocker window after the queue is
        exhausted.

        **G7 @808 G3 deferred-batch combat-decision apply (phase 2).**
        Byte-mirror of Python
        ``MtgGameStateAdapter._finalize_blocker_phase``
        (``engine_adapter.py:1133-1144``): batched
        ``apply_action(state, defender_id, DeclareBlockers(
        assignments=tuple(_chosen_blocks.items())))`` call at
        ``engine_adapter.py:1135-1139``. Mirror by calling Rust's
        whole-action ``Action::DeclareBlockers`` with the same
        ``(blocker_id, attacker_id)`` pairs — which dispatches to
        ``state_ops_combat.rs::declare_blocker`` per pair and runs
        the CE16 post-validation menace unwind
        (``state_ops_actions.rs:262-275``), exactly mirroring
        ``actions._declare_blockers``'s ``validated.pop(...)`` pass
        (``actions.py:2555-2566``)."""
        if self._chosen_blocks:
            self._rust.apply_action({
                "kind": "declare_blockers",
                "assignments": [
                    (int(bid), int(aid))
                    for bid, aid in self._chosen_blocks.items()
                ],
            })
            self._rust.apply_sbas()
        self._combat_phase = _COMBAT_NONE
        self._chosen_blocks = {}
        self._pass_count = 0
        # Tag this (turn, phase) as finalized; see
        # _finalize_attacker_phase docstring.
        self._finalized_combat_window = (
            int(self._rust.turn_number),
            int(self._rust.current_phase()),
        )
        if not self._rust.is_over():
            self._reset_priority_to_active()

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
    def engine_state(self):
        """B3-S2: the codec slot-source switch. The action-encoding
        codec reaches the engine zones via ``_engine_state(state) ->
        getattr(state, "engine_state", state)``
        (``action_encoding.py:316-319``). For the Rust provider this
        returns a ``RustZoneView`` presenting the SAME
        ``player_by_id``/``battlefield`` surface, sourced from the
        Rust ``*_snapshot`` pymethods — so the codec's slot mapping is
        byte-identical (v-chain-SAFE), only its data source moves.
        Rebuilt per access from the live Rust state (the codec calls
        it once per decision moment; same order as the Python
        ``player_by_id`` walk it replaces)."""
        from mtg_bot.search.rust_zone_view import RustZoneView

        return RustZoneView(self._rust, self._printing_resolver)

    @property
    def printing_resolver(self) -> dict:
        """The name -> Python CardPrinting resolver (B3-S2). Exposed
        for the S4 shadow-checker / tests to assert resolution."""
        return self._printing_resolver

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
