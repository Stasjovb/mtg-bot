"""Game setup and the main simulation loop."""

from __future__ import annotations

import random
from typing import Optional

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
    run_cleanup_step,
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


def _build_player(
    state: GameState, player_id: int, color: str, agent: Agent, seed: int
) -> Player:
    p = Player(id=player_id, agent=agent)
    deck_names = build_mono_color_deck(color, seed=seed)
    printings = all_printings()
    for name in deck_names:
        obj = state.new_object(printings[name], owner_id=player_id, zone=Zone.LIBRARY)
        p.library.append(obj)
    return p


def setup_game(
    agents: list[Agent], colors: list[str], seed: Optional[int] = None
) -> GameState:
    state = GameState()
    rng = random.Random(seed)
    for i, (agent, color) in enumerate(zip(agents, colors)):
        p = _build_player(state, i, color, agent, rng.randint(0, 10**9))
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


def priority_loop(state: GameState) -> None:
    """Run the priority loop until all alive players pass with empty stack."""
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
                    resolve_top_of_stack(state)
                    state_based_actions(state)
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
            if state.is_over():
                return
            pass_count = 0
            priority_idx = _next_alive(state, state.active_player_idx)


def run_step(state: GameState, step: Step) -> None:
    state.step = step

    if step == Step.UNTAP:
        run_untap_step(state)
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

    elif step == Step.CLEANUP:
        run_cleanup_step(state)
        return

    # Turn-based actions at the beginning of the end step: warp-exile any
    # permanents cast via their warp cost this turn.
    if step == Step.END:
        run_end_step_warp_exile(state)
        state_based_actions(state)
        if state.is_over():
            return

    if step in STEPS_WITH_PRIORITY:
        priority_loop(state)
        if state.is_over():
            return

    if step == Step.END_OF_COMBAT:
        clear_combat_state(state)


def run_turn(state: GameState) -> None:
    for step in STEP_ORDER:
        run_step(state, step)
        if state.is_over():
            return


def simulate_game(
    agents: Optional[list[Agent]] = None,
    colors: Optional[list[str]] = None,
    seed: Optional[int] = None,
    max_turns: int = 150,
    verbose: bool = False,
) -> GameState:
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
    while not state.is_over() and state.turn_number <= max_turns:
        if verbose:
            print(
                f"--- Turn {state.turn_number}, Player {state.active_player_idx} "
                f"(life: {[p.life for p in state.players]}, "
                f"bf: {len(state.battlefield)}) ---"
            )
        run_turn(state)
        if state.is_over():
            break
        state.turn_number += 1
        state.active_player_idx = _next_alive(
            state, (state.active_player_idx + 1) % len(state.players)
        )

    if not state.is_over():
        state.is_draw = True
        state.log.append(f"draw: reached max {max_turns} turns")
    return state
