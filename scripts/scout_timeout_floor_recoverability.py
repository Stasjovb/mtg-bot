"""Scout: is the round-69 residual ~23% FAIL_TIMEOUT a recoverable
budget mis-size, a genuine permanent stalemate floor, or the round-65
structural-never-converter (<3 admitted creature copies) class?

Round 69 raised the bench ``--max-turns`` default 25 → 60 and recovered
~30 points of parity signal, leaving a residual ~23% of broad-sweep
games that STILL hit exactly the cap (turn 61) with no parity verdict.
Round 69's prose asserted that residual is "the genuine deep structural
floor (frozen 1/1 mirrors / empty-board never-cast)" and pointed at the
round-65 TOKEN_PRINTING_SUBSTRATE Phase-3/5 Rust lever.

That assertion was never proven per-game. The round-69 scout
classifies a *single-cap* run (``budget_progressing`` /
``frozen_stalemate`` / ``no_board``) but its ``budget_progressing``
test is a heuristic on the life tail — it does NOT prove the game
would actually converge with more turns, and it cannot distinguish a
genuinely-board-locked stalemate (will NEVER converge) from a very
slow-but-progressing game (a bigger budget converts it).

This scout supplies the missing GROUND TRUTH: it drives the SAME
(archetype, seed) game at an **escalating ladder of caps** (60 → the
ladder, default 60,90,120,160,220) reusing
``bench_trajectory_parity``'s EXACT per-step primitives + the REAL
production loader (byte-identical trajectory to a real bench run — it
imports and calls the bench's own helpers; same loop, same advance, no
engine/bench change), and records, per game:

  * the cap at which it first reaches a parity verdict (PASS/DIVERGE),
    or ``None`` if it never converges by the top of the ladder
  * the round-65 admitted-creature-copy count (the REAL production
    loader's ``_count_admitted_creature_copies`` — the exact metric
    round 65 used to define the ``<3`` structural-never-converter
    class) so the round-65 hypothesis is confirmed/refuted with
    per-game data
  * the round-69 single-cap stall class at cap-60 (life trajectory,
    flat tail) so the two diagnoses can be cross-tabulated

From that, every residual cap-60 timeout is classified into exactly
one of the THREE load-bearing buckets the campaign needs:

  * ``budget_recoverable`` — converged to a PASS/DIVERGE verdict at
    SOME higher cap on the ladder. RECOVERABLE by a further
    parity-safe budget bump; the scout reports the exact cap and the
    cumulative %-recovered curve + the wall-time cost.
  * ``genuine_stalemate`` — has a board on BOTH sides but life is
    frozen for the whole tail AND never converges at the top of the
    ladder. A true permanent floor (board-locked mirror); raising the
    cap converts nothing. The scout characterizes the deck shapes
    (admitted-copy count, board power, creature counts).
  * ``structural_never_converter`` — the round-65 class: ``< 3``
    admitted creature copies (near-creatureless mirror, typically
    ``no_board`` / sparse) that never converges at the ladder top.
    This is the population the TOKEN_PRINTING_SUBSTRATE Phase-3/5 Rust
    lever targets. The scout reports the per-game admitted-copy count
    so round-65's ``<3`` boundary is confirmed or refuted with data.

A game that converged before cap-60 in the first place is PASS at
cap-60 already and is NOT a residual timeout — those are reported as
``CONVERGED_<=60`` for the denominator but are not classified.

Read-only diagnostic. Modifies no production / ``_SAFE_*`` / bench
code. Default-off everywhere; nothing imports it.
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
class CapRunResult:
    """One drive of one (archetype, seed) at one cap."""
    cap: int
    status: str = "PASS"  # PASS / FAIL_TIMEOUT / FAIL_DIVERGENCE / FAIL_EXCEPTION / ARCHETYPE_FILTERED
    turns_played: int = 0
    p0_life_end: int = 0
    p1_life_end: int = 0
    p0_creatures_end: int = 0
    p1_creatures_end: int = 0
    p0_power_end: int = 0
    p1_power_end: int = 0
    flat_life_tail_turns: int = 0
    life_track: list = field(default_factory=list)


@dataclass
class GameRecoverability:
    archetype: int
    seed: int
    admitted_creature_copies: int = 0
    raw_deck_len: int = 0
    # the cap-60 baseline result (the round-69 residual definition)
    cap60_status: str = ""
    cap60_stall_class: str = ""  # round-69 single-cap classifier
    cap60_flat_tail: int = 0
    cap60_p0_cre: int = 0
    cap60_p1_cre: int = 0
    cap60_p0_pow: int = 0
    cap60_p1_pow: int = 0
    cap60_p0_life: int = 0
    cap60_p1_life: int = 0
    # ladder
    ladder: list = field(default_factory=list)  # list[CapRunResult-as-dict]
    converged_at_cap: Optional[int] = None  # first cap with a verdict, or None
    converged_status: Optional[str] = None  # PASS / FAIL_DIVERGENCE
    # final 3-way classification (only for residual cap-60 timeouts)
    floor_class: str = ""  # see _classify_floor


def _board_snapshot(py_state) -> tuple[int, int, int, int]:
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


def _round69_stall_class(p0_cre, p1_cre, life_track) -> str:
    """Verbatim port of the round-69 scout's _classify_timeout, so the
    two diagnoses cross-tabulate apples-to-apples."""
    if p0_cre == 0 and p1_cre == 0:
        return "no_board"
    track = life_track
    if len(track) < 3:
        return "slow_partial"
    tail = track[-6:] if len(track) >= 6 else track
    p0_delta = tail[-1][1] - tail[0][1]
    p1_delta = tail[-1][2] - tail[0][2]
    if p0_delta == 0 and p1_delta == 0:
        return "frozen_stalemate"
    short = track[-4:] if len(track) >= 4 else track
    if (short[-1][1] - short[0][1]) < 0 or (short[-1][2] - short[0][2]) < 0:
        return "budget_progressing"
    return "slow_partial"


def drive_one_at_cap(
    archetype: int, seed: int, max_turns: int, combat_strategy: str,
) -> CapRunResult:
    """Mirror of bench.drive_one_game with a per-turn snapshot, run at
    one cap. Byte-identical action loop to the bench (same helpers,
    same order, same advance) — only adds a read-only snapshot at each
    active-player PRECOMBAT_MAIN entry."""
    from mtg_bot.parity import trajectory
    from mtg_bot.turn import Step

    r = CapRunResult(cap=max_turns)
    try:
        deck_names = trajectory.load_production_deck(archetype=archetype)
    except (FileNotFoundError, IndexError) as e:
        r.status = "FAIL_EXCEPTION"
        return r

    try:
        py_state, rust_state = trajectory.setup_matched_game_from_real_decks(
            deck_names, shared_rng_seed=seed,
        )
    except ValueError as e:
        msg = str(e)
        if "empty library" in msg or "production deck filter" in msg:
            r.status = "ARCHETYPE_FILTERED"
            return r
        r.status = "FAIL_EXCEPTION"
        return r
    except Exception:  # noqa: BLE001
        r.status = "FAIL_EXCEPTION"
        return r

    combat_agent = trajectory.RealGameCombatAgent(strategy=combat_strategy)
    last_sampled_turn = -1

    try:
        while not bench._game_over(py_state):
            if py_state.turn_number > max_turns:
                r.status = "FAIL_TIMEOUT"
                break

            if py_state.step == Step.PRECOMBAT_MAIN:
                if py_state.turn_number != last_sampled_turn:
                    last_sampled_turn = py_state.turn_number
                    p0l = int(getattr(py_state.players[0], "life", 0))
                    p1l = int(getattr(py_state.players[1], "life", 0))
                    r.life_track.append((py_state.turn_number, p0l, p1l))
                bench._try_play_one_land(py_state, rust_state)
                while True:
                    cast = bench._try_cast_one_creature(py_state, rust_state)
                    if cast is None:
                        break
                bench._advance_phase_with_compare(py_state, rust_state)
                continue

            if py_state.step == Step.DECLARE_ATTACKERS:
                trajectory.drive_combat_phase(
                    py_state, rust_state, combat_agent,
                )
                bench._advance_phase_with_compare(py_state, rust_state)
                continue

            bench._advance_phase_with_compare(py_state, rust_state)

    except bench._DivergenceError:
        r.status = "FAIL_DIVERGENCE"
    except Exception:  # noqa: BLE001
        r.status = "FAIL_EXCEPTION"

    r.turns_played = py_state.turn_number
    r.p0_life_end = int(getattr(py_state.players[0], "life", 0))
    r.p1_life_end = int(getattr(py_state.players[1], "life", 0))
    (r.p0_creatures_end, r.p1_creatures_end,
     r.p0_power_end, r.p1_power_end) = _board_snapshot(py_state)

    track = r.life_track
    flat = 0
    for i in range(len(track) - 1, 0, -1):
        if track[i][1] == track[i - 1][1] and track[i][2] == track[i - 1][2]:
            flat += 1
        else:
            break
    r.flat_life_tail_turns = flat
    return r


def _classify_floor(g: GameRecoverability, copy_floor: int) -> str:
    """The load-bearing 3-way the campaign needs, computed from GROUND
    TRUTH (the actual escalating-cap ladder), not a single-cap heuristic.

    Precondition: this is only called for a game whose cap-60 status is
    FAIL_TIMEOUT (a genuine round-69 residual).

      * ``budget_recoverable`` — converged to a PASS/DIVERGE verdict at
        SOME cap on the ladder above 60. A further parity-safe budget
        bump recovers it; ``converged_at_cap`` says exactly which cap.
      * ``structural_never_converter`` — never converged at the ladder
        top AND has ``< copy_floor`` admitted creature copies (the
        round-65 ``<3`` near-creatureless class). The
        TOKEN_PRINTING_SUBSTRATE Phase-3/5 Rust lever's target.
      * ``genuine_stalemate`` — never converged at the ladder top but
        DOES carry ``>= copy_floor`` admitted copies AND has a board
        on both sides (a real board-locked mirror — the permanent
        floor that no budget and no token substrate fixes; it is a
        bench-player / mirror-structure artifact).
      * ``never_converge_other`` — never converged, ``>= copy_floor``
        copies, but NOT board-on-both-sides at cap-60 (ambiguous: e.g.
        one-sided board that still can't close — reported separately so
        the verdict stays honest rather than force-bucketed).
    """
    if g.converged_at_cap is not None:
        return "budget_recoverable"
    if g.admitted_creature_copies < copy_floor:
        return "structural_never_converter"
    if g.cap60_p0_cre > 0 and g.cap60_p1_cre > 0:
        return "genuine_stalemate"
    return "never_converge_other"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    # broad sweep: the canonical round-69 ~53/23% drag grid
    ap.add_argument("--archetypes", default="0-29")
    ap.add_argument("--seeds", default="0-1")
    ap.add_argument(
        "--cap-ladder", default="60,90,120,160,220",
        help="escalating turn caps; index 0 is the round-69 residual "
             "definition cap (60).",
    )
    ap.add_argument("--combat-strategy", default="attack_all")
    ap.add_argument(
        "--copy-floor", type=int, default=3,
        help="round-65's <N admitted-creature-copy boundary defining "
             "the structural-never-converter class (round 65 used 3).",
    )
    ap.add_argument(
        "--json-out",
        default="tmp/scout_timeout_floor_recoverability.json",
    )
    args = ap.parse_args()

    archs = _parse_int_list(args.archetypes)
    seeds = _parse_int_list(args.seeds)
    ladder = _parse_int_list(args.cap_ladder)
    ladder = sorted(set(ladder))
    cap0 = ladder[0]

    from mtg_bot.parity import trajectory

    results: list[GameRecoverability] = []
    t0 = time.perf_counter()
    for arch in archs:
        for sd in seeds:
            g = GameRecoverability(archetype=arch, seed=sd)
            try:
                deck_names = trajectory.load_production_deck(archetype=arch)
                g.raw_deck_len = len(deck_names)
                g.admitted_creature_copies = (
                    bench._count_admitted_creature_copies(deck_names)
                )
            except Exception:  # noqa: BLE001
                g.admitted_creature_copies = -1

            # cap0 (60) baseline — the round-69 residual definition
            base = drive_one_at_cap(
                arch, sd, cap0, args.combat_strategy,
            )
            g.cap60_status = base.status
            g.cap60_flat_tail = base.flat_life_tail_turns
            g.cap60_p0_cre = base.p0_creatures_end
            g.cap60_p1_cre = base.p1_creatures_end
            g.cap60_p0_pow = base.p0_power_end
            g.cap60_p1_pow = base.p1_power_end
            g.cap60_p0_life = base.p0_life_end
            g.cap60_p1_life = base.p1_life_end
            g.cap60_stall_class = (
                _round69_stall_class(
                    base.p0_creatures_end, base.p1_creatures_end,
                    base.life_track,
                )
                if base.status == "FAIL_TIMEOUT" else ""
            )
            g.ladder.append({
                "cap": base.cap, "status": base.status,
                "turns": base.turns_played,
                "life": (base.p0_life_end, base.p1_life_end),
                "cre": (base.p0_creatures_end, base.p1_creatures_end),
                "flat_tail": base.flat_life_tail_turns,
            })

            if base.status == "FAIL_TIMEOUT":
                # escalate the cap until a verdict or the ladder top
                for cap in ladder[1:]:
                    rr = drive_one_at_cap(
                        arch, sd, cap, args.combat_strategy,
                    )
                    g.ladder.append({
                        "cap": rr.cap, "status": rr.status,
                        "turns": rr.turns_played,
                        "life": (rr.p0_life_end, rr.p1_life_end),
                        "cre": (rr.p0_creatures_end, rr.p1_creatures_end),
                        "flat_tail": rr.flat_life_tail_turns,
                    })
                    if rr.status in ("PASS", "FAIL_DIVERGENCE"):
                        g.converged_at_cap = cap
                        g.converged_status = rr.status
                        break
                g.floor_class = _classify_floor(g, args.copy_floor)
            elif base.status in ("PASS", "FAIL_DIVERGENCE"):
                g.floor_class = "CONVERGED_<=%d" % cap0
            else:
                g.floor_class = base.status  # FILTERED / EXCEPTION

            results.append(g)
            print(
                f"  arch={arch:>3} seed={sd} "
                f"copies={g.admitted_creature_copies:>2} "
                f"cap{cap0}={g.cap60_status:<15} "
                f"r69cls={g.cap60_stall_class:<18} "
                f"-> {g.floor_class}"
                + (f" @cap{g.converged_at_cap}({g.converged_status})"
                   if g.converged_at_cap else "")
            )
    wall = time.perf_counter() - t0

    # ---- aggregate ----
    residual = [
        g for g in results if g.cap60_status == "FAIL_TIMEOUT"
    ]
    converged_le_60 = [
        g for g in results
        if g.cap60_status in ("PASS", "FAIL_DIVERGENCE")
    ]
    other = [
        g for g in results
        if g.cap60_status not in (
            "FAIL_TIMEOUT", "PASS", "FAIL_DIVERGENCE",
        )
    ]

    by_floor = collections.Counter(g.floor_class for g in residual)
    by_r69 = collections.Counter(g.cap60_stall_class for g in residual)

    print()
    print(f"=== {len(results)} games / {wall:.1f}s wall "
          f"(cap ladder {ladder}) ===")
    print(f"  cap-{cap0} verdict (PASS/DIV)   {len(converged_le_60):>4} "
          f"({100*len(converged_le_60)/len(results):.1f}%)")
    print(f"  cap-{cap0} FAIL_TIMEOUT (resid.) {len(residual):>4} "
          f"({100*len(residual)/len(results):.1f}%)")
    print(f"  cap-{cap0} other                 {len(other):>4} "
          f"({100*len(other)/len(results):.1f}%)")
    print(f"--- round-69 single-cap classifier on the {len(residual)} "
          f"residual cap-{cap0} timeouts ---")
    for k, v in sorted(by_r69.items()):
        sh = 100 * v / len(residual) if residual else 0
        print(f"  {k:<22} {v:>3} ({sh:.1f}%)")
    print(f"--- GROUND-TRUTH 3-way floor classification "
          f"(escalating-cap ladder; copy_floor={args.copy_floor}) ---")
    for k, v in sorted(by_floor.items()):
        sh = 100 * v / len(residual) if residual else 0
        print(f"  {k:<26} {v:>3} ({sh:.1f}% of residual)")

    # recoverability curve: cumulative % of the WHOLE-grid that has a
    # verdict at each cap on the ladder
    recov = [g for g in residual if g.converged_at_cap is not None]
    print(f"--- budget-recoverable curve "
          f"({len(recov)}/{len(residual)} residual recovered) ---")
    cum_verdict = len(converged_le_60)
    print(f"  cap {cap0:>3}: {cum_verdict:>3}/{len(results)} grid verdict "
          f"({100*cum_verdict/len(results):.1f}%)  [baseline]")
    for cap in ladder[1:]:
        got = sum(1 for g in recov if g.converged_at_cap == cap)
        cum_verdict += got
        print(f"  cap {cap:>3}: +{got:>2} recovered  "
              f"-> {cum_verdict:>3}/{len(results)} grid verdict "
              f"({100*cum_verdict/len(results):.1f}%)")

    # deck-shape characterization of the genuine permanent floor
    perm = [
        g for g in residual
        if g.floor_class in (
            "genuine_stalemate", "structural_never_converter",
            "never_converge_other",
        )
    ]
    if perm:
        print(f"--- permanent-floor deck shapes ({len(perm)}) ---")
        copies = sorted(g.admitted_creature_copies for g in perm)
        n_lt = sum(
            1 for g in perm
            if 0 <= g.admitted_creature_copies < args.copy_floor
        )
        print(f"  admitted-copy distribution: {copies}")
        print(f"  with < {args.copy_floor} admitted copies: "
              f"{n_lt}/{len(perm)} "
              f"({100*n_lt/len(perm):.1f}%) — round-65 boundary check")

    out = pathlib.Path(args.json_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {
            "params": vars(args),
            "cap_ladder": ladder,
            "n_games": len(results),
            "n_cap60_verdict": len(converged_le_60),
            "n_cap60_residual_timeout": len(residual),
            "by_floor_class": dict(by_floor),
            "by_round69_class": dict(by_r69),
            "games": [vars(g) for g in results],
            "wall_seconds": wall,
        },
        indent=2,
    ))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
