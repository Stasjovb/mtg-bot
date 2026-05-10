"""Dataset 2 — count per-Action-subclass frequency in a single self-played
game between two RandomAgents on synthetic mono-color (G/R) decks.

Run with:
    PYTHONPATH=src \\
    ../../mtg-bot/.venv-py313/Scripts/python.exe \\
    scripts/parity_discovery_action_dist.py
"""

from __future__ import annotations

import io
import random
import sys
from collections import Counter
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:  # pragma: no cover
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def main():
    from mtg_bot import actions as A
    from mtg_bot import simulate as S
    from mtg_bot.agents import RandomAgent
    from mtg_bot.simulate import simulate_game

    # Instrument apply_action so we tally every action that the engine
    # actually applies (including the priority loop's PassPriority
    # branch which is handled in-loop without going through apply_action).
    counter: Counter[str] = Counter()
    sample_reprs: dict[str, str] = {}
    raised: list[tuple[str, str]] = []

    # Wrap apply_action (called by priority_loop for non-pass actions).
    real_apply = A.apply_action

    def wrapped_apply(state, player_id, action):
        cls = type(action).__name__
        counter[cls] += 1
        if cls not in sample_reprs:
            try:
                sample_reprs[cls] = repr(action)
            except Exception:
                sample_reprs[cls] = f"<unrepr-able {cls}>"
        try:
            return real_apply(state, player_id, action)
        except Exception as e:
            raised.append((cls, repr(e)))
            raise

    # Wrap priority_loop's PassPriority via patching choose_action
    # accounting at the agent level — but simpler: also tally in the
    # priority loop by monkeypatching PassPriority's handling. We can
    # tally PassPriority by instrumenting the agent decisions instead.

    # Instrument the agent's choose_action so every returned action is
    # counted (this captures PassPriority too, since priority_loop
    # doesn't go through apply_action for passes).
    real_random_choose = RandomAgent.choose_action

    def wrapped_choose(self, state, player_id, legal):
        action = real_random_choose(self, state, player_id, legal)
        cls = type(action).__name__
        # Only PassPriority is "decided but not apply_action'd". Count
        # those here (others get counted via apply_action).
        if isinstance(action, A.PassPriority):
            counter[cls] += 1
            if cls not in sample_reprs:
                sample_reprs[cls] = repr(action)
        return action

    # DeclareAttackers / DeclareBlockers go through apply_action too
    # (see run_step), so they're caught above. No extra wrapping needed.

    A.apply_action = wrapped_apply
    S.apply_action = wrapped_apply  # patch the binding the simulate module already imported
    RandomAgent.choose_action = wrapped_choose

    # Also count agent.declare_attackers / declare_blockers boundary
    # invocations so we know combat-decisions are happening. The
    # resulting DeclareAttackers / DeclareBlockers Action instances
    # flow through apply_action so they show up in the main tally too.

    seed = 42
    rng = random.Random(seed)
    agents = [
        RandomAgent(rng=random.Random(rng.randint(0, 10**9))),
        RandomAgent(rng=random.Random(rng.randint(0, 10**9))),
    ]
    outcome = None
    end_turn = None
    state = None
    crash = None
    try:
        state = simulate_game(
            agents=agents,
            colors=["G", "R"],
            seed=seed,
            max_turns=30,
        )
        end_turn = state.turn_number
        if state.is_draw:
            outcome = "draw"
        else:
            winners = [p.id for p in state.players if not p.has_lost]
            if len(winners) == 1:
                outcome = f"player {winners[0]} wins"
            else:
                outcome = f"unclear (alive: {winners})"
    except Exception as e:
        import traceback
        crash = traceback.format_exc()

    # Restore wrapping (cleanliness).
    A.apply_action = real_apply
    S.apply_action = real_apply
    RandomAgent.choose_action = real_random_choose

    total = sum(counter.values())
    out = []
    out.append("## Dataset 2 — Action distribution in one self-played game")
    out.append("")
    out.append(f"- **Seed**: {seed}")
    out.append(f"- **Deck setup**: synthetic mono-color G vs R via `simulate.simulate_game(colors=['G','R'])`")
    out.append(f"- **Agents**: two `RandomAgent`s")
    out.append(f"- **Turn cap**: 30")
    out.append(f"- **Total decisions** (agent-action returns + apply_action calls minus overlap): {total}")
    out.append(f"- **Ended on turn**: {end_turn}")
    out.append(f"- **Outcome**: {outcome}")
    if crash is not None:
        out.append("")
        out.append("### Crash")
        out.append("```")
        out.append(crash)
        out.append("```")
    if raised:
        out.append("")
        out.append("### Exceptions raised mid-apply_action")
        for cls, err in raised:
            out.append(f"- `{cls}` raised `{err}`")

    out.append("")
    out.append("### Action class frequency (apply_action + PassPriority decisions)")
    out.append("")
    out.append("| Action class | Count | Sample repr |")
    out.append("|---|---:|---|")
    for cls, n in counter.most_common():
        sr = sample_reprs.get(cls, "")
        # Trim very long reprs.
        if len(sr) > 80:
            sr = sr[:77] + "..."
        out.append(f"| `{cls}` | {n} | `{sr}` |")

    rare = [(c, n) for c, n in counter.items() if n < 5]
    if rare:
        out.append("")
        out.append("### Notable rare actions (< 5 occurrences)")
        for c, n in sorted(rare, key=lambda kv: (kv[1], kv[0])):
            out.append(f"- `{c}`: {n}")

    print("\n".join(out))


if __name__ == "__main__":
    main()
