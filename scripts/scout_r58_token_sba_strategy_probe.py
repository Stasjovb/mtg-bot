"""Round-58 N3 scout: does the round-55 token-cease-to-exist SBA
(CR 111.7) FIRE in real production-deck games, and can a different
bench *combat strategy* unlock it?

Round-56/57 finding: under ``attack_all`` the token-cease-to-exist
SBA NEVER fires in real games (token created but never leaves the
battlefield in 0/120 games) because:

  1. the bench never emits ``activate_ability`` for the Lander's
     ``{2},Sac`` ability (only mana taps) — so a Lander never
     self-sacrifices; AND
  2. under ``attack_all`` the DEFENDER never blocks (empty block
     assignments), so nothing trades in the bridge-filtered
     creatureless mirror — neither a DIES carrier nor a 2/2 Robot
     token ever dies in combat.

This scout is the round-56 lifecycle scan, generalized over the
``--combat-strategy`` axis. The hypothesis under test: a strategy in
which the DEFENDER BLOCKS (``attack_all_block_smallest`` /
``block_with_largest_able``) lets the Gravpack Monoist 2/2 Robot
token (or a DIES carrier) trade in real combat → leave the
battlefield → fire the round-55 SBA. Both engines apply the SAME
emitted block assignments via ``step_both`` (the Phase-5/6
byte-equal invariant), so a token death is observed identically on
both — the bench's existing FAIL_DIVERGENCE check still does the
parity work; this scout only answers "did the path FIRE".

Signals are exactly the round-56 scout's (Python is the source of
truth for "did it fire"; cross-engine byte-equality is the bench's
job — captured here via the same _DivergenceError/AssertionError
gate as the bench):

  * carrier reached bf  ── a CARRIERS creature ever on the Python bf.
  * token created       ── any ``printing.is_token`` object ever on
    the Python bf.
  * token LEFT bf       ── ``"<name> token ceases to exist"`` in
    ``py_state.log`` (Python ``turn.move_off_battlefield`` logs this
    for EVERY token bf-exit — the exact event that triggers the
    round-55 Rust SBA on the other engine).

Pure diagnostic — not a production entrypoint.
"""
from __future__ import annotations

import argparse
import collections
import sys
import time

from mtg_bot.parity import trajectory
from mtg_bot.turn import Step

# Reuse the bench's exact per-step primitives so the trajectory is
# identical to a bench run (same land/cast/combat driver).
from bench_trajectory_parity import (  # noqa: E402
    _DivergenceError,
    _advance_phase_with_compare,
    _game_over,
    _try_cast_one_creature,
    _try_play_one_land,
)

CARRIERS = ("Galactic Wayfarer", "Beamsaw Prospector", "Gravpack Monoist")
TOKEN_NAMES = ("Lander", "Robot")


def _tokens_on_bf(py_state) -> set[str]:
    return {
        o.printing.name
        for o in py_state.battlefield
        if getattr(o.printing, "is_token", False)
    }


def _carriers_on_bf(py_state) -> set[str]:
    return {
        o.printing.name
        for o in py_state.battlefield
        if o.printing.name in CARRIERS
    }


def _scan_one(archetype: int, seed: int, max_turns: int, strategy: str) -> dict:
    rec = {
        "archetype": archetype,
        "seed": seed,
        "strategy": strategy,
        "status": "PASS",
        "carrier_on_bf": False,
        "token_created": False,
        "token_left_bf": False,
        "tokens_seen": set(),
        "cease_lines": [],
        "turns": 0,
    }
    t0 = time.perf_counter()
    try:
        deck_names = trajectory.load_production_deck(archetype=archetype)
        py_state, rust_state = trajectory.setup_matched_game_from_real_decks(
            deck_names, shared_rng_seed=seed,
        )
    except ValueError as e:
        m = str(e)
        rec["status"] = (
            "ARCHETYPE_FILTERED"
            if ("empty library" in m or "production deck filter" in m)
            else "FAIL_EXCEPTION"
        )
        rec["msg"] = m[:200]
        return rec
    except Exception as e:  # noqa: BLE001
        rec["status"] = "FAIL_EXCEPTION"
        rec["msg"] = f"{type(e).__name__}: {e}"[:200]
        return rec

    combat_agent = trajectory.RealGameCombatAgent(strategy=strategy)
    try:
        while not _game_over(py_state):
            if py_state.turn_number > max_turns:
                rec["status"] = "FAIL_TIMEOUT"
                break
            if _carriers_on_bf(py_state):
                rec["carrier_on_bf"] = True
            toks = _tokens_on_bf(py_state)
            if toks:
                rec["token_created"] = True
                rec["tokens_seen"] |= toks
            if py_state.step == Step.PRECOMBAT_MAIN:
                _try_play_one_land(py_state, rust_state)
                while _try_cast_one_creature(py_state, rust_state) is not None:
                    pass
                _advance_phase_with_compare(py_state, rust_state)
                continue
            if py_state.step == Step.DECLARE_ATTACKERS:
                trajectory.drive_combat_phase(
                    py_state, rust_state, combat_agent,
                )
                _advance_phase_with_compare(py_state, rust_state)
                continue
            _advance_phase_with_compare(py_state, rust_state)
    except _DivergenceError as e:
        rec["status"] = "FAIL_DIVERGENCE"
        rec["msg"] = (
            f"kind={e.action.get('kind')!r} "
            f"fields={[d.field for d in e.divergences]}"
        )[:300]
    except AssertionError as e:
        rec["status"] = "FAIL_DIVERGENCE"
        rec["msg"] = f"combat_phase assertion: {str(e)[:280]}"
    except Exception as e:  # noqa: BLE001
        rec["status"] = "FAIL_EXCEPTION"
        rec["msg"] = f"{type(e).__name__}: {e}"[:280]

    # Final-state sweep + log scan (catch tokens created/destroyed in
    # the last segment too).
    if _carriers_on_bf(py_state):
        rec["carrier_on_bf"] = True
    fin = _tokens_on_bf(py_state)
    if fin:
        rec["token_created"] = True
        rec["tokens_seen"] |= fin
    cease = [
        ln for ln in py_state.log
        if "token ceases to exist" in ln
        and any(t in ln for t in TOKEN_NAMES)
    ]
    if cease:
        rec["token_created"] = True  # it had to exist to cease
        rec["token_left_bf"] = True
        rec["cease_lines"] = cease[:6]
        for ln in cease:
            for t in TOKEN_NAMES:
                if t in ln:
                    rec["tokens_seen"].add(t)
    rec["turns"] = py_state.turn_number
    rec["elapsed"] = round(time.perf_counter() - t0, 2)
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archetypes", required=True)
    ap.add_argument("--seeds", default="0-5")
    ap.add_argument("--max-turns", type=int, default=24)
    ap.add_argument(
        "--combat-strategy", default="attack_all",
        help="RealGameCombatAgent strategy (the round-58 axis under "
             "test — attack_all_block_smallest makes the defender "
             "block so tokens/carriers can trade and die).",
    )
    args = ap.parse_args(argv)

    def _rng(s):
        if "," in s:
            return sorted({int(x) for x in s.split(",") if x.strip()})
        if "-" in s:
            lo, hi = s.split("-", 1)
            return list(range(int(lo), int(hi) + 1))
        return [int(s)]

    arches = _rng(args.archetypes)
    seeds = _rng(args.seeds)
    strategy = args.combat_strategy
    recs = []
    for a in arches:
        for s in seeds:
            r = _scan_one(a, s, args.max_turns, strategy)
            recs.append(r)
            ts = ",".join(sorted(r["tokens_seen"])) or "-"
            sys.stderr.write(
                f"[scan] arch={a:3d} seed={s} strat={strategy:24s} "
                f"{r['status']:16s} "
                f"carrier_bf={int(r['carrier_on_bf'])} "
                f"tok_created={int(r['token_created'])} "
                f"tok_left_bf={int(r['token_left_bf'])} "
                f"toks={ts} t={r['turns']}\n"
            )

    n = len(recs)
    by_status = collections.Counter(r["status"] for r in recs)
    carrier_bf = sum(r["carrier_on_bf"] for r in recs)
    tok_created = sum(r["token_created"] for r in recs)
    tok_left = sum(r["token_left_bf"] for r in recs)
    fired_and_clean = sum(
        1 for r in recs
        if r["token_left_bf"]
        and r["status"] in ("PASS", "FAIL_TIMEOUT")
    )
    fired_and_diverged = [
        r for r in recs
        if r["token_left_bf"] and r["status"] == "FAIL_DIVERGENCE"
    ]

    print("=" * 72)
    print(f"round-58 token-SBA strategy probe  (strategy={strategy})")
    print("=" * 72)
    print(f"  total games            : {n}")
    print(f"  status                 : {dict(by_status)}")
    print(f"  carrier reached bf     : {carrier_bf}/{n}")
    print(f"  token created          : {tok_created}/{n}")
    print(f"  token LEFT bf (SBA fire): {tok_left}/{n}")
    print(f"  token-SBA fired & no divergence : {fired_and_clean}/{n}")
    print(f"  token-SBA fired & DIVERGED      : {len(fired_and_diverged)}")
    for r in fired_and_diverged:
        print(f"    !! arch={r['archetype']} seed={r['seed']} "
              f"{r.get('msg', '')}")
    sample = [r for r in recs if r["cease_lines"]][:5]
    if sample:
        print("  sample cease-to-exist log lines:")
        for r in sample:
            print(f"    arch={r['archetype']} seed={r['seed']}: "
                  f"{r['cease_lines'][0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
