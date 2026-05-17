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
                    if not self._rust.is_over():
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
        return [rust_dict_to_decision(d) for d in dicts]

    def _refresh_combat_phase(self, dicts: list[dict]) -> None:
        """Set ``_combat_phase`` + the pending-head list from the
        current Rust factored emission. The codec reads
        ``getattr(state, "combat_phase", None)`` and
        ``state._pending_attackers[0]`` / ``_pending_blockers[0]``
        (``action_encoding.py:973-1012``) to encode the implicit-head
        ATTACKER/BLOCKER slots; we expose exactly the head Rust is
        emitting a factored decision for (its ``attacker_id`` /
        ``blocker_id``)."""
        atk_heads = [
            int(d["attacker_id"]) for d in dicts
            if d.get("kind") == "attacker_decision"
        ]
        blk_heads = [
            int(d["blocker_id"]) for d in dicts
            if d.get("kind") == "blocker_decision"
        ]
        if atk_heads:
            self._combat_phase = _COMBAT_ATTACKERS
            # G1 emits exactly two attacker_decision dicts for ONE
            # head (attack True/False); the head is that attacker_id.
            self._pending_attackers = [atk_heads[0]]
            self._pending_blockers = []
        elif blk_heads:
            self._combat_phase = _COMBAT_BLOCKERS
            self._pending_blockers = [blk_heads[0]]
            self._pending_attackers = []
        else:
            self._combat_phase = _COMBAT_NONE
            self._pending_attackers = []
            self._pending_blockers = []

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
