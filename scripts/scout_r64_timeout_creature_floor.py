"""Round-64 N3 scout: quantify the FAIL_TIMEOUT creature-floor drag.

The standing ~50% FAIL_TIMEOUT floor (r56/r58/r61/r62/r63) is the
campaign's biggest non-divergence signal drag. Root cause established
r47/r50/r58: the CardDef bridge-admit filter collapses each 17lands
archetype's 10-13 distinct creature *names* to ~1-2 admitted creature
copies, pads the remaining ~58 slots with basic lands → a
near-creatureless mirror → games never reach lethal → max-turns cap →
FAIL_TIMEOUT (no trajectory-divergence signal).

This scout instruments a representative ~60-game sweep (the round-62
broad-surface grid shape, HARD ≤3-min cap) with per-game telemetry the
plain bench doesn't capture:

  * **admitted creature copies** per deck (post-filter, pre-pad) —
    derived from the REAL production loader's filtered DeckSpec, so the
    number is exactly what the bench plays with.
  * **distinct admitted creature names** + the **raw distinct creature
    count** the filter dropped them from (the collapse ratio).
  * **turns played** + final life totals.
  * **timeout cause classification** for every FAIL_TIMEOUT:
      - ``never_cast_creature`` — 0 creatures ever cast (the carrier
        was buried in ~58 lands, never drawn into a castable position).
      - ``cast_but_stalled`` — ≥1 creature cast + attacked, but too
        small/slow to close 20 life before the cap.

Pure read-only diagnostic — reuses the bench's exact per-step
primitives (identical trajectory to a real bench run) + the REAL
production loader. Writes nothing except an optional JSON artifact.
NOT a production entrypoint.

Run from a worktree::

    PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \\
        scripts/scout_r64_timeout_creature_floor.py \\
        --archetypes 0,1,2,3,4,5,7,8,9,10,11,12,13,40,42 --seeds 0-3 \\
        --max-turns 22 --json-out tmp/scout_r64_timeout_floor.json
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
import time
from typing import Optional

# Path bootstrap so `python scripts/...` works from a fresh worktree.
_HERE = pathlib.Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mtg_bot.parity import trajectory  # noqa: E402
from mtg_bot.turn import Step  # noqa: E402

# Reuse the bench's exact per-step primitives so the trajectory is
# byte-identical to a real bench_trajectory_parity.py run.
from bench_trajectory_parity import (  # noqa: E402
    _DivergenceError,
    _advance_phase_with_compare,
    _game_over,
    _try_cast_one_creature,
    _try_play_one_land,
)


def _parse_range(spec: str) -> list[int]:
    if "," in spec:
        return sorted({int(p) for p in spec.split(",") if p.strip()})
    if "-" in spec:
        lo, hi = spec.split("-", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(spec)]


def _admitted_creature_profile(archetype: int) -> dict:
    """Return the admitted-creature profile for one archetype's deck.

    Uses the REAL production loader path
    (``_filter_deck_to_bridge_supported``) so the counts are EXACTLY
    what the bench plays. ``copies`` = total admitted creature card
    copies in the 40-card deck (duplicates preserved, the bench's
    pre-pad library). ``names`` = distinct admitted creature names.
    ``raw_distinct`` = distinct creature names in the RAW deck before
    the admit filter (the collapse denominator).
    """
    from mtg_bot.cards.source import get_active_source

    deck_names = trajectory.load_production_deck(archetype=archetype)
    src = get_active_source()
    printings = src.get_printings()

    raw_creature_names: set[str] = set()
    admitted_creature_copies = 0
    admitted_creature_names: set[str] = set()
    for name in deck_names:
        pr = printings.get(name)
        if pr is None:
            continue
        if "Creature" in pr.card_types:
            raw_creature_names.add(name)
            if trajectory._printing_is_bridge_simple_creature(pr):
                admitted_creature_copies += 1
                admitted_creature_names.add(name)
    return {
        "raw_distinct_creatures": len(raw_creature_names),
        "admitted_creature_copies": admitted_creature_copies,
        "admitted_creature_names": sorted(admitted_creature_names),
        "n_admitted_distinct": len(admitted_creature_names),
    }


def _scan_one(
    archetype: int, seed: int, max_turns: int, strategy: str,
) -> dict:
    """Drive one (archetype, seed) game with the bench primitives +
    per-game timeout instrumentation."""
    prof = _admitted_creature_profile(archetype)
    rec = {
        "archetype": archetype,
        "seed": seed,
        "status": "PASS",
        "turns": 0,
        "creatures_cast": 0,
        "attack_eligible_turns": 0,
        "final_life": None,
        "timeout_cause": None,
        **prof,
    }
    t0 = time.perf_counter()
    try:
        deck_names = trajectory.load_production_deck(archetype=archetype)
        py_state, rust_state = trajectory.setup_matched_game_from_real_decks(
            deck_names, shared_rng_seed=seed,
        )
    except ValueError as e:
        msg = str(e)
        if "empty library" in msg or "production deck filter" in msg:
            rec["status"] = "ARCHETYPE_FILTERED"
        else:
            rec["status"] = "FAIL_EXCEPTION"
            rec["exc"] = msg[:200]
        rec["elapsed"] = time.perf_counter() - t0
        return rec
    except Exception as e:  # noqa: BLE001 — scout is signal-gen
        rec["status"] = "FAIL_EXCEPTION"
        rec["exc"] = f"{type(e).__name__}: {e}"[:200]
        rec["elapsed"] = time.perf_counter() - t0
        return rec

    combat_agent = trajectory.RealGameCombatAgent(strategy=strategy)
    creatures_cast = 0
    attack_eligible_turns = 0
    try:
        while not _game_over(py_state):
            if py_state.turn_number > max_turns:
                rec["status"] = "FAIL_TIMEOUT"
                break
            if py_state.step == Step.PRECOMBAT_MAIN:
                _try_play_one_land(py_state, rust_state)
                while True:
                    cast = _try_cast_one_creature(py_state, rust_state)
                    if cast is None:
                        break
                    creatures_cast += 1
                # Count this turn's active player having ≥1 attack-able
                # creature (on bf, a creature, not summoning sick) — the
                # "could this game ever have closed via combat" signal.
                active = py_state.active_player_idx
                if any(
                    o.controller_id == active
                    and "Creature" in o.printing.card_types
                    and not getattr(o, "summoning_sick", False)
                    for o in py_state.battlefield
                ):
                    attack_eligible_turns += 1
                _advance_phase_with_compare(py_state, rust_state)
                continue
            if py_state.step == Step.DECLARE_ATTACKERS:
                trajectory.drive_combat_phase(
                    py_state, rust_state, combat_agent,
                )
                _advance_phase_with_compare(py_state, rust_state)
                continue
            _advance_phase_with_compare(py_state, rust_state)
    except _DivergenceError:
        rec["status"] = "FAIL_DIVERGENCE"
    except AssertionError:
        rec["status"] = "FAIL_DIVERGENCE"
    except Exception as e:  # noqa: BLE001
        rec["status"] = "FAIL_EXCEPTION"
        rec["exc"] = f"{type(e).__name__}: {e}"[:200]

    rec["turns"] = py_state.turn_number
    rec["creatures_cast"] = creatures_cast
    rec["attack_eligible_turns"] = attack_eligible_turns
    try:
        rec["final_life"] = [int(p.life) for p in py_state.players]
    except Exception:  # noqa: BLE001
        rec["final_life"] = None
    if rec["status"] == "FAIL_TIMEOUT":
        rec["timeout_cause"] = (
            "never_cast_creature" if creatures_cast == 0
            else "cast_but_stalled"
        )
    rec["elapsed"] = time.perf_counter() - t0
    return rec


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="scout_r64_timeout_creature_floor")
    ap.add_argument("--archetypes", default="0,1,2,3,4,5,7,8,9,10,11,12,13,40,42")
    ap.add_argument("--seeds", default="0-3")
    ap.add_argument("--max-turns", type=int, default=22)
    ap.add_argument("--combat-strategy", default="attack_all")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args(argv)

    arches = _parse_range(args.archetypes)
    seeds = _parse_range(args.seeds)
    total = len(arches) * len(seeds)
    sys.stderr.write(
        f"[scout_r64] {len(arches)} arch x {len(seeds)} seed = {total} "
        f"games; strategy={args.combat_strategy}, "
        f"max_turns={args.max_turns}\n"
    )

    games: list[dict] = []
    n = 0
    for a in arches:
        for s in seeds:
            n += 1
            r = _scan_one(a, s, args.max_turns, args.combat_strategy)
            games.append(r)
            sys.stderr.write(
                f"[scout_r64] {n:>3d}/{total} arch={a:3d} seed={s} "
                f"{r['status']:16s} cre_copies={r['admitted_creature_copies']} "
                f"cast={r['creatures_cast']} t={r['turns']} "
                f"cause={r['timeout_cause']} ({r['elapsed']:.2f}s)\n"
            )

    # ---- Aggregate -------------------------------------------------------
    status_ct = collections.Counter(g["status"] for g in games)
    timeouts = [g for g in games if g["status"] == "FAIL_TIMEOUT"]
    cause_ct = collections.Counter(
        g["timeout_cause"] for g in timeouts
    )
    copy_dist = collections.Counter(
        g["admitted_creature_copies"] for g in games
    )
    # collapse ratio per archetype (raw distinct -> admitted distinct)
    per_arch = {}
    for g in games:
        a = g["archetype"]
        if a not in per_arch:
            per_arch[a] = {
                "raw_distinct_creatures": g["raw_distinct_creatures"],
                "admitted_creature_copies": g["admitted_creature_copies"],
                "n_admitted_distinct": g["n_admitted_distinct"],
                "admitted_creature_names": g["admitted_creature_names"],
                "status": collections.Counter(),
            }
        per_arch[a]["status"][g["status"]] += 1

    out = []
    out.append("=" * 72)
    out.append("round-64 FAIL_TIMEOUT creature-floor instrumentation")
    out.append("=" * 72)
    out.append(f"  total games:     {len(games)}")
    for st in ("PASS", "FAIL_TIMEOUT", "FAIL_DIVERGENCE",
               "ARCHETYPE_FILTERED", "FAIL_EXCEPTION"):
        out.append(f"  {st:18s} {status_ct.get(st, 0)}")
    tot = len(games)
    to_ct = status_ct.get("FAIL_TIMEOUT", 0)
    out.append(
        f"  FAIL_TIMEOUT %:    {100.0 * to_ct / tot:.1f}%  ({to_ct}/{tot})"
    )
    out.append("")
    out.append("timeout cause split (of FAIL_TIMEOUT):")
    for cause, ct in cause_ct.most_common():
        pct = 100.0 * ct / max(1, len(timeouts))
        out.append(f"  {cause:24s} {ct:4d}  ({pct:.0f}%)")
    out.append("")
    out.append("admitted-creature-copies distribution (all games):")
    for copies in sorted(copy_dist):
        out.append(f"  {copies} copies: {copy_dist[copies]} games")
    out.append("")
    out.append("per-archetype (raw distinct creatures -> admitted):")
    for a in sorted(per_arch):
        d = per_arch[a]
        st = ", ".join(f"{k}={v}" for k, v in sorted(d["status"].items()))
        out.append(
            f"  arch {a:3d}: raw={d['raw_distinct_creatures']:2d} "
            f"-> admitted_copies={d['admitted_creature_copies']} "
            f"({d['n_admitted_distinct']} distinct: "
            f"{','.join(d['admitted_creature_names']) or '-'})  [{st}]"
        )
    report = "\n".join(out)
    sys.stdout.write(report + "\n")

    if args.json_out:
        payload = {
            "config": {
                "archetypes": args.archetypes,
                "seeds": args.seeds,
                "max_turns": args.max_turns,
                "combat_strategy": args.combat_strategy,
            },
            "status_counts": dict(status_ct),
            "timeout_cause_counts": dict(cause_ct),
            "copies_distribution": dict(sorted(copy_dist.items())),
            "games": games,
        }
        pathlib.Path(args.json_out).write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8",
        )
        sys.stderr.write(f"[scout_r64] wrote {args.json_out}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
