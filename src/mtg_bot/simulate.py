"""Game setup and the main simulation loop."""

from __future__ import annotations

import random
from typing import Callable, Literal, Optional

SnapshotCallback = Callable[["GameState"], None]
SnapshotGranularity = Literal["step", "priority"]

from mtg_bot.actions import (
    DeclareAttackers,
    DeclareBlockers,
    PassPriority,
    apply_action,
    resolve_top_of_stack,
)
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import all_printings, build_mono_color_deck
from mtg_bot.combat import (
    clear_combat_state,
    eligible_attackers,
    eligible_blockers,
    resolve_combat_damage,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import (
    STEP_ORDER,
    STEPS_WITH_PRIORITY,
    Step,
    draw_card,
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


def _next_alive(state: GameState, start_idx: int) -> int:
    idx = start_idx
    for _ in range(len(state.players)):
        if not state.players[idx].has_lost:
            return idx
        idx = (idx + 1) % len(state.players)
    return start_idx


def _build_player_from_names(
    state: GameState, player_id: int, deck_names: list[str], agent: Agent,
) -> Player:
    """Materialize a player with a library built from explicit card
    names. Caller is responsible for shuffling — this just instantiates
    one GameObject per name in the order given."""
    p = Player(id=player_id, agent=agent)
    printings = all_printings()
    unknown = [name for name in deck_names if name not in printings]
    if unknown:
        raise ValueError(
            f"deck for player {player_id} contains unknown cards: "
            f"{sorted(set(unknown))}"
        )
    for name in deck_names:
        obj = state.new_object(
            printings[name], owner_id=player_id, zone=Zone.LIBRARY,
        )
        p.library.append(obj)
    return p


def _build_player(
    state: GameState, player_id: int, color: str, agent: Agent, seed: int
) -> Player:
    """Mono-color path: build a deck via ``build_mono_color_deck`` and
    materialize. Kept around because existing tests + the default
    ``setup_game`` color path still use it."""
    deck_names = build_mono_color_deck(color, seed=seed)
    return _build_player_from_names(state, player_id, deck_names, agent)


def setup_game(
    agents: list[Agent],
    colors: Optional[list[str]] = None,
    seed: Optional[int] = None,
    decks: Optional[list[list[str]]] = None,
) -> GameState:
    """Build a fresh game state.

    Two ways to provide each player's library:

    - ``colors``: pass ``["G", "R"]`` and each player gets a mono-
      color synthetic deck via ``build_mono_color_deck``. Quick and
      contrived; fine for tests.
    - ``decks``: pass ``[[card_name, ...], [card_name, ...]]`` — one
      explicit decklist per agent. Card names must all exist in
      ``all_printings()``. This is the path the 17lands data ingestion
      will use.

    Exactly one of ``colors`` and ``decks`` must be provided.
    """
    if (colors is None) == (decks is None):
        raise ValueError(
            "exactly one of `colors` or `decks` must be provided"
        )
    if colors is not None and len(colors) != len(agents):
        raise ValueError(
            f"colors length {len(colors)} != agents length {len(agents)}"
        )
    if decks is not None and len(decks) != len(agents):
        raise ValueError(
            f"decks length {len(decks)} != agents length {len(agents)}"
        )

    state = GameState()
    # Seed the canonical game RNG off the caller's seed so every
    # engine-level shuffle / random choice is reproducible across
    # processes. The local ``rng`` below stays scoped to setup —
    # deck-build + initial shuffle — to keep that work deterministic
    # even if future engine work draws from state.rng during setup.
    state.rng.seed(seed)
    rng = random.Random(seed)

    if colors is not None:
        for i, (agent, color) in enumerate(zip(agents, colors)):
            p = _build_player(
                state, i, color, agent, rng.randint(0, 10**9),
            )
            state.players.append(p)
    else:
        assert decks is not None  # narrowed above
        for i, (agent, deck) in enumerate(zip(agents, decks)):
            p = _build_player_from_names(state, i, list(deck), agent)
            state.players.append(p)

    for p in state.players:
        rng.shuffle(p.library)
        for _ in range(7):
            draw_card(state, p.id)
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.UNTAP
    state.turn_number = 1
    return state


def priority_loop(
    state: GameState,
    on_snapshot: Optional[SnapshotCallback] = None,
) -> None:
    """Run the priority loop until all alive players pass with empty stack.

    When ``on_snapshot`` is provided, it fires after each applied (non-pass)
    action and around each stack resolution (once just before the top of the
    stack is resolved, once just after), giving the UI a chance to render
    spells mid-flight instead of only seeing drained end-of-step state.
    """
    alive_count = lambda: sum(1 for p in state.players if not p.has_lost)
    pass_count = 0
    priority_idx = _next_alive(state, state.active_player_idx)

    while True:
        state_based_actions(state)
        if state.is_over():
            return

        p = state.players[priority_idx]
        if p.has_lost:
            priority_idx = _next_alive(state, (priority_idx + 1) % len(state.players))
            continue

        state.priority_player_idx = priority_idx
        legal = legal_actions(state, p.id)
        action = p.agent.choose_action(state, p.id, legal)

        if isinstance(action, PassPriority):
            pass_count += 1
            if pass_count >= alive_count():
                if state.stack:
                    # Snapshot the stack populated state before resolution —
                    # this is the "you can see the Counterspell targeting a
                    # Lightning Bolt" moment.
                    if on_snapshot is not None:
                        on_snapshot(state)
                    resolve_top_of_stack(state)
                    state_based_actions(state)
                    if on_snapshot is not None:
                        on_snapshot(state)
                    if state.is_over():
                        return
                    pass_count = 0
                    priority_idx = _next_alive(state, state.active_player_idx)
                else:
                    return
            else:
                priority_idx = _next_alive(
                    state, (priority_idx + 1) % len(state.players)
                )
        else:
            apply_action(state, p.id, action)
            state_based_actions(state)
            if on_snapshot is not None:
                on_snapshot(state)
            if state.is_over():
                return
            pass_count = 0
            priority_idx = _next_alive(state, state.active_player_idx)


def run_step(
    state: GameState,
    step: Step,
    priority_on_snapshot: Optional[SnapshotCallback] = None,
) -> None:
    """Run one step of a turn. ``priority_on_snapshot`` (if provided) is
    forwarded to the priority loop for fine-grained mid-stack snapshots."""
    state.step = step

    if step == Step.UNTAP:
        run_untap_step(state)
        return

    if step == Step.UPKEEP:
        run_beginning_of_upkeep_triggers(state)
        state_based_actions(state)
        if state.is_over():
            return

    if step == Step.DRAW:
        # Starting player skips their very first draw step.
        starting_player_first_draw = (
            state.turn_number == 1 and state.active_player_idx == 0
        )
        if not starting_player_first_draw:
            run_draw_step(state)

    elif step == Step.DECLARE_ATTACKERS:
        ap = state.active_player()
        eligible = eligible_attackers(state, ap.id)
        chosen = ap.agent.declare_attackers(state, ap.id, eligible)
        apply_action(
            state, ap.id, DeclareAttackers(attacker_ids=frozenset(chosen))
        )

    elif step == Step.DECLARE_BLOCKERS:
        attackers = [o for o in state.battlefield if o.attacking]
        if attackers:
            defender_idx = _next_alive(
                state, (state.active_player_idx + 1) % len(state.players)
            )
            defender = state.players[defender_idx]
            eligible = eligible_blockers(state, defender.id)
            assignments = defender.agent.declare_blockers(
                state, defender.id, eligible, attackers
            )
            apply_action(
                state,
                defender.id,
                DeclareBlockers(assignments=tuple(assignments.items())),
            )

    elif step == Step.COMBAT_DAMAGE:
        if any(o.attacking for o in state.battlefield):
            defender_idx = _next_alive(
                state, (state.active_player_idx + 1) % len(state.players)
            )
            resolve_combat_damage(state, state.players[defender_idx].id)
            state_based_actions(state)
            if state.is_over():
                return

    elif step == Step.BEGINNING_OF_COMBAT:
        run_beginning_of_combat_triggers(state)
        state_based_actions(state)
        if state.is_over():
            return

    elif step == Step.CLEANUP:
        run_cleanup_step(state)
        return

    # Turn-based actions at the beginning of the end step. Order:
    #   1. Fire "beginning of end step" triggered abilities (Void, etc.) —
    #      they see the turn's state before warp-exile creates new events.
    #   2. Warp-exile any permanents cast via their warp cost this turn.
    if step == Step.END:
        run_beginning_of_end_step_triggers(state)
        state_based_actions(state)
        if state.is_over():
            return
        run_delayed_end_step_triggers(state)
        state_based_actions(state)
        if state.is_over():
            return
        run_end_step_warp_exile(state)
        state_based_actions(state)
        if state.is_over():
            return

    if step in STEPS_WITH_PRIORITY:
        priority_loop(state, on_snapshot=priority_on_snapshot)
        if state.is_over():
            return

    if step == Step.END_OF_COMBAT:
        clear_combat_state(state)


def _advance_to_next_active_player(state: GameState) -> None:
    """Pick the next turn's active player.

    If ``state.extra_turn_queue`` has a still-alive player, they go
    next. Otherwise fall back to the natural next-alive rotation.
    Exposed as a top-level helper so the extra-turn branches are
    directly unit-testable.
    """
    queued_next_player = None
    while state.extra_turn_queue:
        candidate_id = state.extra_turn_queue.pop(0)
        candidate = next(
            (p for p in state.players if p.id == candidate_id), None,
        )
        if candidate is not None and not candidate.has_lost:
            queued_next_player = candidate_id
            break
    if queued_next_player is not None:
        state.active_player_idx = next(
            i for i, p in enumerate(state.players)
            if p.id == queued_next_player
        )
        state.log.append(f"P{queued_next_player} takes an extra turn")
    else:
        state.active_player_idx = _next_alive(
            state, (state.active_player_idx + 1) % len(state.players)
        )


def run_turn(
    state: GameState,
    on_snapshot: Optional[SnapshotCallback] = None,
    priority_on_snapshot: Optional[SnapshotCallback] = None,
) -> None:
    """Run one turn. ``on_snapshot`` (if set) fires after each step.
    ``priority_on_snapshot`` (if set) fires additionally at priority
    boundaries inside each step's priority loop."""
    state.log.append(
        f"--- Turn {state.turn_number}: P{state.active_player_idx} ---"
    )
    for step in STEP_ORDER:
        run_step(state, step, priority_on_snapshot=priority_on_snapshot)
        if on_snapshot is not None:
            on_snapshot(state)
        if state.is_over():
            return


def simulate_game(
    agents: Optional[list[Agent]] = None,
    colors: Optional[list[str]] = None,
    seed: Optional[int] = None,
    max_turns: int = 150,
    verbose: bool = False,
    on_snapshot: Optional[SnapshotCallback] = None,
    snapshot_granularity: SnapshotGranularity = "step",
) -> GameState:
    """Run a full game.

    When ``on_snapshot`` is provided it is called with the current ``GameState``
    once after setup, after each step inside every turn, and once at game end.

    ``snapshot_granularity`` controls whether extra snapshots also fire during
    each step's priority loop:

    - ``"step"`` (default): only end-of-step snapshots. ~150-200 per game.
    - ``"priority"``: additionally after every action applied and around every
      stack resolution. Much finer (~1000-2000 per game). The stack is
      typically populated in these snapshots, so the UI can render spells
      mid-resolution instead of only the drained end-of-step state.

    The callback receives a live reference — callers that want a persistable
    snapshot should serialize inside the callback.
    """
    if snapshot_granularity not in ("step", "priority"):
        raise ValueError(
            f"snapshot_granularity must be 'step' or 'priority', "
            f"got {snapshot_granularity!r}"
        )
    priority_on_snapshot = (
        on_snapshot if snapshot_granularity == "priority" else None
    )
    if colors is None:
        colors = ["G", "R"]
    if agents is None:
        rng = random.Random(seed)
        agents = [
            RandomAgent(rng=random.Random(rng.randint(0, 10**9)))
            for _ in range(len(colors))
        ]
    if len(agents) != len(colors):
        raise ValueError("agents and colors must have same length")

    state = setup_game(agents, colors, seed=seed)
    if on_snapshot is not None:
        on_snapshot(state)
    while not state.is_over() and state.turn_number <= max_turns:
        if verbose:
            print(
                f"--- Turn {state.turn_number}, Player {state.active_player_idx} "
                f"(life: {[p.life for p in state.players]}, "
                f"bf: {len(state.battlefield)}) ---"
            )
        run_turn(
            state,
            on_snapshot=on_snapshot,
            priority_on_snapshot=priority_on_snapshot,
        )
        if state.is_over():
            break
        state.turn_number += 1
        _advance_to_next_active_player(state)

    if not state.is_over():
        state.is_draw = True
        state.log.append(f"draw: reached max {max_turns} turns")
    if on_snapshot is not None:
        on_snapshot(state)
    return state
