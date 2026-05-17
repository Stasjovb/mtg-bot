"""Scout: anatomy of a FAIL_TIMEOUT bench game (the dimension round-65 missed).

Round-65 N3 quantified the creature-floor as an *admit-count* problem
(``< 3`` admitted creature copies → structural never-converter) and
concluded the only real lever is a multi-round Rust substrate. That
analysis measured WHICH decks time out but never measured WHERE inside a
game it stalls: turn count vs the cap, life trajectory (still moving or
frozen), and the per-game action distribution.

This scout reuses ``bench_trajectory_parity``'s EXACT per-step
primitives + the REAL production loader (byte-identical trajectory to a
real bench run — it imports and calls the bench's own helpers, it does
not re-implement them), and instruments each game with a snapshot at
every turn boundary so a FAIL_TIMEOUT can be dissected:

  * turns_played vs max_turns (did it hit the cap, or end early?)
  * life totals over time (monotone decreasing = progressing; flat for
    the last K turns = a frozen stalemate the turn budget can't fix)
  * creatures on bf per side + total power per side at the cap
  * action counts: lands played, creatures cast, combat phases driven,
    attackers declared (summed)
  * the LAST 6 turns' (p0_life, p1_life) deltas — the load-bearing new
    datum: a timeout where life is still dropping every turn is a
    *budget* problem (raise the cap); a timeout where life has been
    flat for many turns is a *stalemate* (cap is irrelevant; the bench
    player or the mirror structure is the cause).

Read-only diagnostic. Modifies no production / ``_SAFE_*`` / bench code.
Default-off everywhere; nothing imports it.
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))
sys.path.insert(0, str(_REPO / "scripts"))

# Reuse the bench's EXACT primitives — do not re-implement.
import bench_trajectory_parity as bench  # noqa: E402


def _parse_int_list(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.extend(range(int(lo), int(hi) + 1))
        else:
            out.append(int(part))
    return out


@dataclass
class GameAnatomy:
    archetype: int
    seed: int
    status: str = "PASS"
    turns_played: int = 0
    max_turns: int = 0
    # life trajectory: list of (turn, p0_life, p1_life) sampled at each
    # PRECOMBAT_MAIN entry of the active player.
    life_track: list = field(default_factory=list)
    # action tally
    lands_played: int = 0
    creatures_cast: int = 0
    combat_phases: int = 0
    attackers_declared_total: int = 0
    # board at end
    p0_creatures_end: int = 0
    p1_creatures_end: int = 0
    p0_power_end: int = 0
    p1_power_end: int = 0
    p0_life_end: int = 0
    p1_life_end: int = 0
    # derived: turns since either life total last changed (the new datum)
    flat_life_tail_turns: int = 0
    timeout_class: str = ""  # see _classify_timeout


def _board_snapshot(py_state) -> tuple[int, int, int, int]:
    """(p0_creatures, p1_creatures, p0_total_power, p1_total_power) on bf."""
    c = [0, 0]
    pw = [0, 0]
    for o in py_state.battlefield:
        if "Creature" not in o.printing.card_types:
            continue
        cid = o.controller_id
        if cid not in (0, 1):
            continue
        c[cid] += 1
        pw[cid] += int(getattr(o.printing, "power", 0) or 0)
    return c[0], c[1], pw[0], pw[1]


def _classify_timeout(a: GameAnatomy) -> str:
    """The load-bearing classification round-65 never produced.

    * ``budget_progressing`` — life was STILL dropping in the last 4
      sampled turns (sum of life-deltas over the tail < 0). The game
      would have ended with a larger turn budget; the cap is the cause.
    * ``frozen_stalemate`` — life totals flat for the entire sampled
      tail (>= 6 turns no change). Neither player can damage the other;
      raising the cap converts NOTHING. Cause is the bench
      player/mirror structure, not the budget.
    * ``no_board`` — neither side ever had a creature on bf at the cap
      (the round-65 ``never_cast`` structural population).
    * ``slow_partial`` — some life movement but not in the immediate
      tail (oscillating / very slow); ambiguous.
    """
    if a.p0_creatures_end == 0 and a.p1_creatures_end == 0:
        return "no_board"
    track = a.life_track
    if len(track) < 3:
        return "slow_partial"
    tail = track[-6:] if len(track) >= 6 else track
    p0_delta = tail[-1][1] - tail[0][1]
    p1_delta = tail[-1][2] - tail[0][2]
    if p0_delta == 0 and p1_delta == 0:
        return "frozen_stalemate"
    # progressing if life dropped over the last <=4 sampled turns
    short = track[-4:] if len(track) >= 4 else track
    if (short[-1][1] - short[0][1]) < 0 or (short[-1][2] - short[0][2]) < 0:
        return "budget_progressing"
    return "slow_partial"


def drive_one_game_instrumented(
    archetype: int, seed: int, max_turns: int, combat_strategy: str,
) -> GameAnatomy:
    """Mirror of ``bench.drive_one_game`` with a per-turn snapshot.

    Structurally identical action loop to the bench (same helpers, same
    order, same advance) so the trajectory is byte-identical; the only
    addition is recording a snapshot at each active-player
    PRECOMBAT_MAIN entry. No parity assertions are weakened.
    """
    from mtg_bot.parity import trajectory
    from mtg_bot.turn import Step

    a = GameAnatomy(archetype=archetype, seed=seed, max_turns=max_turns)
    try:
        deck_names = trajectory.load_production_deck(archetype=archetype)
    except (FileNotFoundError, IndexError) as e:
        a.status = "FAIL_EXCEPTION"
        a.timeout_class = f"setup:{type(e).__name__}"
        return a

    try:
        py_state, rust_state = trajectory.setup_matched_game_from_real_decks(
            deck_names, shared_rng_seed=seed,
        )
    except ValueError as e:
        msg = str(e)
        if "empty library" in msg or "production deck filter" in msg:
            a.status = "ARCHETYPE_FILTERED"
            a.timeout_class = "empty_post_filter"
            return a
        a.status = "FAIL_EXCEPTION"
        a.timeout_class = f"setup:{type(e).__name__}"
        return a
    except Exception as e:  # noqa: BLE001
        a.status = "FAIL_EXCEPTION"
        a.timeout_class = f"setup:{type(e).__name__}"
        return a

    combat_agent = trajectory.RealGameCombatAgent(strategy=combat_strategy)
    last_sampled_turn = -1

    try:
        while not bench._game_over(py_state):
            if py_state.turn_number > max_turns:
                a.status = "FAIL_TIMEOUT"
                break

            if py_state.step == Step.PRECOMBAT_MAIN:
                # snapshot once per turn at the first PRECOMBAT_MAIN
                if py_state.turn_number != last_sampled_turn:
                    last_sampled_turn = py_state.turn_number
                    p0l = int(getattr(py_state.players[0], "life", 0))
                    p1l = int(getattr(py_state.players[1], "life", 0))
                    a.life_track.append(
                        (py_state.turn_number, p0l, p1l)
                    )
                played_land = bench._try_play_one_land(py_state, rust_state)
                if played_land is not None:
                    a.lands_played += 1
                while True:
                    cast = bench._try_cast_one_creature(py_state, rust_state)
                    if cast is None:
                        break
                    a.creatures_cast += 1
                bench._advance_phase_with_compare(py_state, rust_state)
                continue

            if py_state.step == Step.DECLARE_ATTACKERS:
                attackers = combat_agent.pick_attackers(py_state)
                a.attackers_declared_total += len(attackers)
                trajectory.drive_combat_phase(
                    py_state, rust_state, combat_agent,
                )
                a.combat_phases += 1
                bench._advance_phase_with_compare(py_state, rust_state)
                continue

            bench._advance_phase_with_compare(py_state, rust_state)

        if a.status == "PASS" and bench._game_over(py_state):
            pass  # PASS

    except Exception as e:  # noqa: BLE001
        a.status = "FAIL_EXCEPTION"
        a.timeout_class = f"loop:{type(e).__name__}:{str(e)[:120]}"
        return a

    a.turns_played = py_state.turn_number
    a.p0_life_end = int(getattr(py_state.players[0], "life", 0))
    a.p1_life_end = int(getattr(py_state.players[1], "life", 0))
    (a.p0_creatures_end, a.p1_creatures_end,
     a.p0_power_end, a.p1_power_end) = _board_snapshot(py_state)

    # flat-life-tail: how many trailing sampled turns had ZERO life change
    track = a.life_track
    flat = 0
    for i in range(len(track) - 1, 0, -1):
        if track[i][1] == track[i - 1][1] and track[i][2] == track[i - 1][2]:
            flat += 1
        else:
            break
    a.flat_life_tail_turns = flat

    if a.status == "FAIL_TIMEOUT":
        a.timeout_class = _classify_timeout(a)
    return a


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archetypes", default="0,1,2,3,4,5,7,8,9,10,11,12,13,40,42")
    ap.add_argument("--seeds", default="0-3")
    ap.add_argument("--max-turns", type=int, default=25)
    ap.add_argument("--combat-strategy", default="attack_all")
    ap.add_argument("--json-out", default="tmp/scout_timeout_stall_anatomy.json")
    args = ap.parse_args()

    archs = _parse_int_list(args.archetypes)
    seeds = _parse_int_list(args.seeds)

    results: list[GameAnatomy] = []
    t0 = time.perf_counter()
    for arch in archs:
        for sd in seeds:
            r = drive_one_game_instrumented(
                arch, sd, args.max_turns, args.combat_strategy,
            )
            results.append(r)
            print(
                f"  arch={arch:>3} seed={sd} {r.status:<18} "
                f"{r.turns_played:>2}t cast={r.creatures_cast} "
                f"atk={r.attackers_declared_total} "
                f"life=({r.p0_life_end},{r.p1_life_end}) "
                f"cre=({r.p0_creatures_end},{r.p1_creatures_end}) "
                f"flat_tail={r.flat_life_tail_turns} "
                f"{r.timeout_class}"
            )
    wall = time.perf_counter() - t0

    by_status: dict = collections.Counter(r.status for r in results)
    timeouts = [r for r in results if r.status == "FAIL_TIMEOUT"]
    by_to_class: dict = collections.Counter(r.timeout_class for r in timeouts)

    print()
    print(f"=== {len(results)} games / {wall:.1f}s wall ===")
    for k, v in sorted(by_status.items()):
        print(f"  {k:<20} {v:>4} ({100*v/len(results):.1f}%)")
    print(f"--- FAIL_TIMEOUT anatomy ({len(timeouts)}) ---")
    for k, v in sorted(by_to_class.items()):
        share = 100 * v / len(timeouts) if timeouts else 0.0
        print(f"  {k:<22} {v:>4} ({share:.1f}% of timeouts)")
    if timeouts:
        avg_flat = sum(r.flat_life_tail_turns for r in timeouts) / len(timeouts)
        avg_turns = sum(r.turns_played for r in timeouts) / len(timeouts)
        avg_atk = sum(r.attackers_declared_total for r in timeouts) / len(timeouts)
        avg_cast = sum(r.creatures_cast for r in timeouts) / len(timeouts)
        n_hit_cap = sum(1 for r in timeouts if r.turns_played > args.max_turns)
        print(
            f"  avg turns_played={avg_turns:.1f} (cap {args.max_turns}; "
            f"{n_hit_cap}/{len(timeouts)} hit the cap), "
            f"avg flat_life_tail={avg_flat:.1f} turns, "
            f"avg attackers_declared={avg_atk:.1f}, "
            f"avg creatures_cast={avg_cast:.1f}"
        )

    out = pathlib.Path(args.json_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {
            "params": vars(args),
            "by_status": dict(by_status),
            "by_timeout_class": dict(by_to_class),
            "games": [vars(r) for r in results],
            "wall_seconds": wall,
        },
        indent=2,
    ))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
