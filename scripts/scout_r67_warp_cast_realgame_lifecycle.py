"""Round-67 bench scout: drive the warp_cost Phase-1 warp-CAST branch
through a REAL production-deck game context and assert byte-equal
cross-engine at every step.

Why this scout exists (the honest gap the broad bench Sweep A leaves)
---------------------------------------------------------------------
The broad ``bench_trajectory_parity.py`` Sweep A validates that the
warp carriers (Red Tiger Mechan / Bygone Colossus) now ADMIT through
the post-Phase-1 bridge and that the resulting real games stay
byte-equal — but the bench's ``_try_cast_one_creature`` always issues
a *base* ``{"kind":"cast_spell"}`` (pays ``mana_cost``); it never
emits ``use_warp=True``. So Sweep A validates the CardDef warp-bridge
round-trip + the Rust ``legal_actions`` warp emitter (the base+warp
CastSpell pair must match — the primary pre-Phase-1 divergence) + the
2 harness-bug fixes on the general cast pipeline, but it does NOT
itself drive the warp-CAST branch (``Action::CastSpell{use_warp:true}``
→ ``cast_creature_warp`` → PHASE_END_STEP exile sweep →
recast-from-exile). That branch is covered only by the in-test
genuine probe on a SYNTHETIC 39-Forest library
(``test_parity_smoke.py::test_cross_engine_real_eoe_warp_phase1_full_
lifecycle_byte_equal``).

This scout closes that gap honestly: it loads an ACTUAL 17lands
carrier-archetype deck via the REAL production loader
(``trajectory.production_deck_to_deckspec`` — the exact bench path),
sets up the matched game, walks the real game, and when the real warp
card is in hand at a p0 main phase with enough mana on the
battlefield, drives the EXPLICIT ``use_warp=True`` cast → following
end step (warp-exile sweep) → a later turn's recast-from-exile at
NORMAL cost — all on BOTH engines via ``step_both`` /
``advance_phase_python``, asserting 0 divergence at every step. This
is the real-deck-game exercise of the warp-cast path the bench
strategy structurally can't drive (r61 scout-then-sweep discipline:
the bench sweep is the broad collateral net, this is the targeted
new-code-path driver).

Read-only / no production change. ``--json-out`` records the
per-archetype lifecycle verdict. Per the scout convention
(CLAUDE.md), throwaway ``scout_*.py`` diagnostics stay under
``scripts/``.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:  # pragma: no cover
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parents[1]
# `tests` is a package — import the helper as ``tests.test_trajectory_
# parity`` with REPO_ROOT (not REPO_ROOT/tests) on sys.path.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

WARP_CARDS = ("Red Tiger Mechan", "Bygone Colossus")


def _is_basic_landname(spec, name: str) -> bool:
    """True iff `name` resolves to a Land CardDef in the spec pool."""
    for c in spec.card_defs:
        if c.name == name:
            return c.card_type == "Land"
    return False


def _mana_total(cost_str: str) -> int:
    return sum(
        int(x) if x.isdigit() else 1
        for x in re.findall(r"\{([^}]+)\}", cost_str)
    )


def _pick_lands_for_cost(untapped, mana_cost):
    """Pick a COLOR-CORRECT subset of untapped basic lands that
    exactly covers `mana_cost` (a ManaCost: .generic + .colored
    pairs). Returns the list of land GameObjects to tap, or None if
    the available lands can't cover the cost. Reuses the bench's
    `_basic_land_color` so the color mapping matches production."""
    import importlib
    btp = importlib.import_module("bench_trajectory_parity")
    by_color = {}
    for o in untapped:
        c = btp._basic_land_color(o.printing)
        by_color.setdefault(c, []).append(o)
    used = set()
    pick = []
    for color, n in (mana_cost.colored or ()):
        avail = [o for o in by_color.get(color, [])
                 if id(o) not in used]
        if len(avail) < n:
            return None
        for o in avail[:n]:
            used.add(id(o))
            pick.append(o)
    generic = int(getattr(mana_cost, "generic", 0))
    rest = [o for o in untapped if id(o) not in used]
    if len(rest) < generic:
        return None
    pick.extend(rest[:generic])
    return pick


def _drive_one(archetype: int, seed: int, front_load: bool = True) -> dict:
    """Load a real carrier deck, set up the matched game, and drive
    the full warp lifecycle for whichever warp card the deck carries.
    Returns a per-archetype verdict dict."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        step_both, advance_phase_python, compare_fields,
    )
    from mtg_bot.legal import legal_actions
    from tests.test_trajectory_parity import _step_views

    rec: dict = {
        "archetype": archetype, "seed": seed, "card": None,
        "status": "ok", "stage_reached": "setup",
        "warp_cast_driven": False, "exiled_ok": False,
        "recast_ok": False, "divergence": None,
    }

    deck_names = trajectory.load_production_deck(archetype=archetype)
    card_name = next((c for c in WARP_CARDS if c in set(deck_names)), None)
    if card_name is None:
        rec["status"] = "no-warp-card-in-deck"
        return rec
    rec["card"] = card_name

    src = get_active_source().get_printings()
    real = src.get(card_name)
    if real is None or real.warp_cost is None:
        rec["status"] = "warp-printing-absent"
        return rec
    warp_str = real.warp_cost_str
    normal_str = real.mana_cost_str

    # The EXACT bench path: real deck → bridged deckspec (the warp card
    # now materializes as a has_warp CardDef post-Phase-1). The
    # CardDefs come from the REAL parsed printings via the production
    # bridge (`trajectory._printing_to_card_def`) — real-EoE
    # discipline preserved.
    base_spec = trajectory.production_deck_to_deckspec(
        deck_names, shared_rng_seed=None if front_load else seed,
    )
    cd_names = {c.name for c in base_spec.card_defs}
    if card_name not in cd_names:
        rec["status"] = "warp-card-not-admitted"
        return rec
    cd = next(c for c in base_spec.card_defs if c.name == card_name)
    if not getattr(cd, "has_warp", False):
        rec["status"] = "admitted-without-has_warp"  # guardrail teeth
        return rec

    spec = base_spec
    if front_load:
        # Real-deck-game context, but deterministically front-load p0's
        # library so the (single-copy) warp card surfaces within the
        # window — the standing bridge creature-floor (round-65) buries
        # a 1-copy warp card in a ~40-card lands-heavy bridged deck so
        # it ~never reaches hand+castable in 40 turns under a shuffle.
        # We keep the REAL bridged CardDef pool + REAL warp printing;
        # only p0's DRAW ORDER is controlled (same discipline as the
        # in-test genuine probe's `(card_name,)+("Forest",)*39`, but
        # over the real carrier deck's bridged library). p1 keeps the
        # shuffled real mirror so the opponent side is a genuine game.
        from mtg_bot.parity.cross_engine import DeckSpec as _DeckSpec
        from dataclasses import replace as _dc_replace

        lib = list(base_spec.p0_library)
        lands = [n for n in lib if n != card_name
                 and _is_basic_landname(base_spec, n)]
        warp_copies = [n for n in lib if n == card_name]
        rest = [n for n in lib
                if n != card_name and n not in set(lands)]
        if not warp_copies or len(lands) < 9:
            rec["status"] = "front-load-insufficient-mana-base"
            return rec
        # Opening 7 + a few draws of lands, then the warp card, then
        # the rest — guarantees the warp card is drawn by ~turn 4-5
        # with a live mana base under it.
        new_p0 = (
            lands[:6] + [card_name] + lands[6:] + warp_copies[1:] + rest
        )
        spec = _dc_replace(
            base_spec, p0_library=tuple(new_p0),
            shared_rng_seed=None, shuffle_seed=None,
        )

    py, rs = trajectory.setup_matched_game(
        spec, seed=None if front_load else seed)
    rec["stage_reached"] = "matched_game"

    def adv(n):
        for _ in range(n):
            advance_phase_python(py)
            rs.advance_phase()
            pv, rv = _step_views(py, rs)
            d = compare_fields(pv, rv)
            if d:
                raise AssertionError(
                    f"phase-advance divergence at "
                    f"({pv['step']}, turn {pv['turn']}): "
                    f"{[(x.field, x.py_value, x.rust_value) for x in d]}"
                )

    def walk_to_p0_main(max_phases=60):
        """Advance phases until p0 is at PRECOMBAT_MAIN (or budget
        exhausted). Returns True if reached."""
        for _ in range(max_phases):
            pv2, _ = _step_views(py, rs)
            if (py.active_player_idx == 0
                    and pv2["step"] == "PRECOMBAT_MAIN"):
                return True
            adv(1)
        return False

    # Walk up to ~25 p0 turns: each p0 MAIN1, play a land if we have
    # one, and once the warp card is in hand with enough untapped
    # unsick lands to cover the warp cost, drive the warp lifecycle.
    warp_total = _mana_total(warp_str)
    normal_total = _mana_total(normal_str)
    adv(3)  # turn 1 → p0 MAIN1

    drove = False
    for _turn in range(25):
        if not walk_to_p0_main():
            break
        ai = py.active_player_idx
        pv, _rv = _step_views(py, rs)
        at_p0_main = (ai == 0 and pv["step"] == "PRECOMBAT_MAIN")
        if at_p0_main:
            p = py.players[0]
            # Play a land if one is in hand and none played yet.
            if p.lands_played_this_turn == 0:
                hand_land = next(
                    (o for o in p.hand if o.printing.is_land), None
                )
                if hand_land is not None:
                    s = step_both(
                        py, rs,
                        {"kind": "play_land",
                         "card_id": int(hand_land.id)},
                    )
                    if s.divergences:
                        rec["status"] = "FAIL_DIVERGENCE"
                        rec["stage_reached"] = "play_land"
                        rec["divergence"] = [
                            (d.field, str(d.py_value), str(d.rust_value))
                            for d in s.divergences
                        ]
                        return rec
            # Is the warp card castable for its warp cost now?
            card_obj = next(
                (o for o in py.players[0].hand
                 if o.printing.name == card_name), None
            )
            untapped = [
                o for o in py.battlefield
                if o.controller_id == 0 and o.printing.is_land
                and not o.tapped and not o.summoning_sick
            ]
            warp_pick = _pick_lands_for_cost(
                untapped, real.warp_cost)
            if card_obj is not None and warp_pick is not None:
                # Tap a COLOR-CORRECT set covering the warp cost
                # (matching colored pips first, then generic) so
                # Python's `_can_cast` actually offers the warp cast —
                # a color-naive tap leaves Python unable to afford the
                # colored pip and it emits nothing (the documented
                # Rust-no-_can_cast asymmetry, not an engine bug).
                bad = False
                for o in warp_pick:
                    s = step_both(
                        py, rs,
                        {"kind": "activate_ability",
                         "source_id": int(o.id), "ability_index": 0},
                    )
                    if s.divergences:
                        rec["status"] = "FAIL_DIVERGENCE"
                        rec["stage_reached"] = "tap_for_warp"
                        rec["divergence"] = [
                            (d.field, str(d.py_value), str(d.rust_value))
                            for d in s.divergences
                        ]
                        return rec
                if bad:
                    return rec
                # (1) The Phase-1 invariant: BOTH engines offer the
                # `use_warp=True` variant when warp_cost is present.
                # NOTE: the BASE (use_warp=False) variant's presence
                # legitimately differs across engines — Python's
                # legal.py gates the base CastSpell on `_can_cast`
                # (mana payability), Rust's cast_spell_dict has NO
                # payability gate (documented "Deliberate divergence"
                # in state_ops_legal.rs; WARP_COST_PHASE1_DESIGN.md
                # §2.2 caveat 1). When we've tapped exactly the warp
                # cost, Python can't afford the higher NORMAL cost so
                # it drops the base variant ([True]) while Rust emits
                # both ([False, True]). This pre-existing asymmetry is
                # tolerated by the bench's step_both harness for EVERY
                # card; the warp variant inherits the same accepted
                # shape. So assert ONLY that the warp variant is
                # offered on BOTH engines (the Phase-1 emitter
                # invariant) — the byte-equality of the warp CAST
                # itself is the authoritative check on the next line
                # via step_both (which DOES tolerate the documented
                # _can_cast asymmetry).
                py_pair = sorted(
                    a.use_warp for a in legal_actions(py, 0)
                    if getattr(a, "card_id", None) == card_obj.id
                )
                rs_pair = sorted(
                    a["use_warp"] for a in rs.legal_decisions(0)
                    if a.get("kind") == "cast_spell"
                    and a.get("card_id") == card_obj.id
                )
                if not (True in py_pair and True in rs_pair):
                    rec["status"] = "FAIL_DIVERGENCE"
                    rec["stage_reached"] = "legal_warp_variant_absent"
                    rec["divergence"] = [
                        ("warp_variant_offered_both", str(py_pair),
                         str(rs_pair))
                    ]
                    return rec
                rec["legal_pair_py"] = str(py_pair)
                rec["legal_pair_rs"] = str(rs_pair)
                # (2) The explicit warp cast — byte-equal post-cast.
                s = step_both(
                    py, rs,
                    {"kind": "cast_spell",
                     "card_id": int(card_obj.id), "use_warp": True},
                )
                if s.divergences:
                    rec["status"] = "FAIL_DIVERGENCE"
                    rec["stage_reached"] = "warp_cast"
                    rec["divergence"] = [
                        (d.field, str(d.py_value), str(d.rust_value))
                        for d in s.divergences
                    ]
                    return rec
                if not (py.spell_warped_this_turn
                        and rs.spell_warped_this_turn):
                    rec["status"] = "FAIL_DIVERGENCE"
                    rec["stage_reached"] = "spell_warped_flag"
                    rec["divergence"] = [
                        ("spell_warped_this_turn",
                         str(py.spell_warped_this_turn),
                         str(rs.spell_warped_this_turn))
                    ]
                    return rec
                rec["warp_cast_driven"] = True
                rec["stage_reached"] = "warp_cast_done"
                # (3) Following end step — warp-exile sweep, byte-equal.
                adv(7)  # MAIN1 → END (exile fires on both)
                py_ex = sorted(
                    o.printing.name for o in py.players[0].exile)
                rs_ex = sorted(
                    o["printing_name"] for o in rs.exile_snapshot(0))
                if not (py_ex == rs_ex and card_name in py_ex):
                    rec["status"] = "FAIL_DIVERGENCE"
                    rec["stage_reached"] = "end_step_exile"
                    rec["divergence"] = [
                        ("exile_after_end", str(py_ex), str(rs_ex))
                    ]
                    return rec
                rec["exiled_ok"] = True
                rec["stage_reached"] = "exiled"
                # (4) Later turn — recast from exile at NORMAL cost.
                # Walk forward up to ~12 p0 turns, playing a land each
                # p0 main, until enough untapped lands exist to cover
                # the (higher) normal recast cost.
                def _untap_lands():
                    return [
                        o for o in py.battlefield
                        if o.controller_id == 0 and o.printing.is_land
                        and not o.tapped and not o.summoning_sick
                    ]

                recast_ready = False
                for _rt in range(12):
                    if not walk_to_p0_main():
                        break
                    p2 = py.players[0]
                    if p2.lands_played_this_turn == 0:
                        fl = next(
                            (o for o in p2.hand
                             if o.printing.is_land), None)
                        if fl is not None:
                            s = step_both(
                                py, rs,
                                {"kind": "play_land",
                                 "card_id": int(fl.id)})
                            if s.divergences:
                                rec["status"] = "FAIL_DIVERGENCE"
                                rec["stage_reached"] = "recast_play_land"
                                rec["divergence"] = [
                                    (d.field, str(d.py_value),
                                     str(d.rust_value))
                                    for d in s.divergences
                                ]
                                return rec
                    if _pick_lands_for_cost(
                            _untap_lands(), real.mana_cost) is not None:
                        recast_ready = True
                        break
                    adv(2)
                untap2 = _untap_lands()
                recast_pick = _pick_lands_for_cost(
                    untap2, real.mana_cost)
                if not recast_ready or recast_pick is None:
                    # Not enough COLOR-CORRECT mana to recast within
                    # the window — the warp-cast + exile halves still
                    # validated; mark recast as not-exercised (not a
                    # failure).
                    rec["status"] = "ok-recast-mana-short"
                    return rec
                for o in recast_pick:
                    s = step_both(
                        py, rs,
                        {"kind": "activate_ability",
                         "source_id": int(o.id),
                         "ability_index": 0})
                    if s.divergences:
                        rec["status"] = "FAIL_DIVERGENCE"
                        rec["stage_reached"] = "recast_tap"
                        rec["divergence"] = [
                            (d.field, str(d.py_value),
                             str(d.rust_value)) for d in s.divergences
                        ]
                        return rec
                exiled_obj = next(
                    o for o in py.players[0].exile
                    if o.printing.name == card_name)
                s = step_both(
                    py, rs,
                    {"kind": "cast_spell",
                     "card_id": int(exiled_obj.id),
                     "use_warp": False})
                if s.divergences:
                    rec["status"] = "FAIL_DIVERGENCE"
                    rec["stage_reached"] = "exile_recast"
                    rec["divergence"] = [
                        (d.field, str(d.py_value), str(d.rust_value))
                        for d in s.divergences
                    ]
                    return rec
                py_bf = any(o.printing.name == card_name
                            for o in py.battlefield)
                rs_bf = any(o["printing_name"] == card_name
                            for o in rs.battlefield_snapshot())
                if not (py_bf and rs_bf):
                    rec["status"] = "FAIL_DIVERGENCE"
                    rec["stage_reached"] = "recast_on_bf"
                    rec["divergence"] = [
                        ("recast_on_bf", str(py_bf), str(rs_bf))
                    ]
                    return rec
                rec["recast_ok"] = True
                rec["stage_reached"] = "recast_done"
                drove = True
                break
        # Step off the current p0 PRECOMBAT_MAIN so the next
        # walk_to_p0_main lands on the FOLLOWING p0 turn (one adv()
        # would leave us still on/near this main and busy-loop).
        adv(2)

    if not drove and not rec["warp_cast_driven"]:
        rec["status"] = "warp-card-never-castable-in-window"
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--archetypes",
        default="61,99,127,153,159,198,236,364",
        help="Comma-separated carrier archetype indices (from "
             "scout_r67_warp_p1_carrier_archetypes.py).",
    )
    ap.add_argument("--seeds", default="0,1")
    ap.add_argument(
        "--no-front-load", action="store_true",
        help="Disable the deterministic p0 draw-order front-load "
             "(default ON: needed so the single-copy warp card "
             "surfaces within the window over the real bridged "
             "carrier deck — the standing creature-floor buries it "
             "under a shuffle). With this flag the warp card "
             "~never reaches hand+castable (creature-floor artifact, "
             "honestly reported as warp-card-never-castable).",
    )
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args(argv)
    front_load = not args.no_front_load

    arches = [int(x) for x in args.archetypes.split(",") if x.strip()]
    seeds = [int(x) for x in args.seeds.split(",") if x.strip()]
    records = []
    n_warp_driven = 0
    n_recast = 0
    n_div = 0
    for a in arches:
        for s in seeds:
            try:
                r = _drive_one(a, s, front_load=front_load)
            except AssertionError as e:
                r = {
                    "archetype": a, "seed": s, "status": "FAIL_DIVERGENCE",
                    "stage_reached": "phase_advance",
                    "divergence": str(e)[:400],
                }
            except Exception as e:  # noqa: BLE001
                r = {
                    "archetype": a, "seed": s,
                    "status": f"FAIL_EXCEPTION:{type(e).__name__}",
                    "stage_reached": "?",
                    "divergence": str(e)[:400],
                }
            records.append(r)
            if r.get("warp_cast_driven"):
                n_warp_driven += 1
            if r.get("recast_ok"):
                n_recast += 1
            if str(r.get("status", "")).startswith("FAIL"):
                n_div += 1
            sys.stderr.write(
                f"[scout] arch={a:4d} seed={s} card={r.get('card')}"
                f" status={r.get('status')} "
                f"stage={r.get('stage_reached')} "
                f"warp_cast={r.get('warp_cast_driven')} "
                f"exiled={r.get('exiled_ok')} "
                f"recast={r.get('recast_ok')}\n"
            )

    print("=" * 66)
    print(
        f"warp-CAST real-deck-game lifecycle: {len(records)} games, "
        f"warp-cast driven in {n_warp_driven}, recast-from-exile "
        f"completed in {n_recast}, FAIL (div/exc) = {n_div}"
    )
    verdict = (
        "VALIDATED byte-equal (0 FAIL)" if n_div == 0
        else f"DIVERGENCE CAPTURED ({n_div} FAIL)"
    )
    print(f"VERDICT: {verdict}")

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "n_games": len(records),
                    "n_warp_cast_driven": n_warp_driven,
                    "n_recast_completed": n_recast,
                    "n_fail": n_div,
                    "verdict": verdict,
                    "records": records,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        sys.stderr.write(f"[scout] wrote {out}\n")
    return 0 if n_div == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
