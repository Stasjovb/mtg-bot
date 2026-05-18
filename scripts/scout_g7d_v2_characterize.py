"""Throwaway diagnostic: characterize the 12 G7 S6 v2 Class-D
cast_spell residuals (LEGAL_SET_EQ rust\\py=[] py\\rust=['cast_spell',N,...]).

Specifically targets the v2 residuals — PY emits a cast_spell the
Rust gate refuses to emit (Rust over-restricts emission). All 12
have variant-flag shape `(cast_spell, hand_idx, False, False, False, False, None)`
i.e. no warp / no kicker / no free / no impending / no Room-half.

For each pair, identifies the candidate card by inspecting the
queried-player's hand at the divergence point and matching against
`only_py` ids; then evaluates Python's C1 gates (_can_cast /
_targets_are_satisfiable / _additional_costs_payable) for the
queried player to see whether ALL three admit the card from the
Python side.

NOT a production entrypoint — agent-generated investigation tool.
"""
from __future__ import annotations

import sys
import json

from mtg_bot.parity import trajectory
from mtg_bot.search.rust_shadow import (
    ShadowDivergenceError,
    build_shadow_checked_adapter,
    canon_set,
)
import random


# 12 residual arch/seed pairs from s6_scale_verify_v2.json.
G7D_V2_RESIDUALS = [
    (5, 1),
    (9, 3),
    (10, 1),
    (11, 1),
    (12, 1),
    (16, 2),
    (17, 2),
    (21, 4),
    (38, 0),
    (39, 3),
    (42, 4),
    (51, 0),
]


def _instrument_cache(adapter):
    """Wrap _legal_dicts_cached to record every populate event."""
    ra = adapter._rust
    history = []
    orig = ra._legal_dicts_cached
    orig_inv = ra._invalidate_legal_cache
    orig_legal = ra.legal_decisions

    def wrapped(pid):
        was_cached = (
            ra._legal_cache_value is not None
            and ra._legal_cache_player == pid
        )
        result = orig(pid)
        kinds = sorted({d.get("kind") for d in result})
        history.append({
            "event": "cached_query" if was_cached else "populate",
            "pid": pid,
            "kinds": kinds,
            "n": len(result),
            "rust_phase": int(ra._rust.current_phase()),
            "rust_pri": int(ra._rust.get_priority_player()),
            "rust_act": int(ra._rust.active_player_idx),
            "rust_turn": int(ra._rust.turn_number),
            "rust_stack_size": int(ra._rust.stack_size()),
            "ra_combat_phase": ra._combat_phase,
            "ra_finalized": ra._finalized_combat_window,
        })
        return result

    def wrapped_inv():
        if ra._legal_cache_value is not None:
            history.append({"event": "invalidate"})
        orig_inv()

    def wrapped_legal():
        history.append({"event": "legal_decisions_enter"})
        try:
            result = orig_legal()
        finally:
            kinds_out = sorted({d.__class__.__name__ for d in (result if isinstance(result, list) else [])}) if "result" in dir() else None
        history.append({
            "event": "legal_decisions_exit",
            "n": len(result) if result else 0,
            "kinds": sorted({type(d).__name__ for d in result}) if result else [],
        })
        return result

    ra._legal_dicts_cached = wrapped
    ra._invalidate_legal_cache = wrapped_inv
    ra.legal_decisions = wrapped_legal
    return history


def characterize(arch: int, seed: int) -> dict:
    deck_names = trajectory.load_production_deck(archetype=arch)
    spec = trajectory.production_deck_to_deckspec(
        deck_names, shared_rng_seed=seed,
    )
    adapter = build_shadow_checked_adapter(spec)
    cache_history = _instrument_cache(adapter)
    rng = random.Random(seed)
    steps = 0
    info: dict = {"arch": arch, "seed": seed, "_history": cache_history}
    while steps < 4000:
        if adapter.is_terminal():
            info["result"] = "terminal-no-divergence"
            return info
        try:
            legal = adapter.legal_decisions()
        except ShadowDivergenceError as e:
            if e.tripwire != "LEGAL_SET_EQ":
                info["result"] = f"other-tripwire:{e.tripwire}"
                info["detail"] = str(e)[:300]
                return info
            return _dump_divergence(adapter, steps, str(e), info)
        if not legal:
            info["result"] = "empty-legal"
            return info
        choice = rng.choice(legal)
        adapter.apply(choice)
        steps += 1
    info["result"] = "timeout"
    return info


def _dump_divergence(adapter, steps, detail, info):
    from mtg_bot.legal import legal_actions
    from mtg_bot.legal import (
        _has_priority,
        _is_sorcery_timing,
        _can_cast,
        _targets_are_satisfiable,
        _additional_costs_payable,
    )
    from mtg_bot.actions import apply_cost_reductions

    py = adapter._py
    rust = adapter._rust
    es = py.engine_state

    rust_legal = rust.legal_decisions()
    ap = adapter._rust.active_player()
    py_ref = legal_actions(es, ap)

    r = canon_set(rust_legal)
    p = canon_set(py_ref)
    only_rust = sorted(r - p)
    only_py = sorted(p - r)

    info["result"] = "LEGAL_SET_EQ"
    info["step"] = steps
    info["detail"] = detail[:300]
    info["only_rust"] = [str(x) for x in only_rust]
    info["only_py"] = [str(x) for x in only_py]
    info["rust_active_player"] = ap
    info["py_priority_player_idx"] = es.priority_player_idx
    info["py_active_player_idx"] = es.active_player_idx
    info["py_step"] = str(es.step)
    info["py_stack_len"] = len(es.stack)

    # _has_priority gate check for the queried (Rust-driver active) pid
    info["py_has_priority(ap)"] = _has_priority(es, ap)
    info["py_is_sorcery_timing(ap)"] = _is_sorcery_timing(es, ap)
    info["py_can_cast_sorcery(ap)"] = (
        _is_sorcery_timing(es, ap)
        and _has_priority(es, ap)
        and len(es.stack) == 0
    )
    # Each only_py cast_spell tuple is (kind, card_id, use_warp, kicked,
    # cast_for_free, use_impending, cast_room_half)
    casts = [
        x for x in only_py
        if isinstance(x, tuple) and x and x[0] == "cast_spell"
    ]

    # Rust-side state at divergence
    try:
        ra = adapter._rust  # the RustGameStateAdapter (Python-side wrapper)
        rs = ra._rust  # underlying GameState
        info["rust_priority_player"] = int(rs.get_priority_player())
        info["rust_active_player_idx"] = int(rs.active_player_idx)
        info["rust_phase"] = int(rs.current_phase())
        info["rust_hand_size"] = int(rs.hand_sizes[ap])
        info["ra_combat_phase"] = getattr(ra, "_combat_phase", "<none>")
        info["ra_pending_attackers"] = list(getattr(ra, "_pending_attackers", []))
        info["ra_pending_blockers"] = list(getattr(ra, "_pending_blockers", []))
        info["ra_finalized_combat_window"] = getattr(ra, "_finalized_combat_window", "<none>")
        info["ra_legal_cache_player"] = getattr(ra, "_legal_cache_player", "<none>")
        info["ra_active_player()"] = ra.active_player()
        # Inspect Rust's legal_decisions list and look for what it
        # DID emit; compare against the only_py cast_spell.
        info["py_combat_phase"] = getattr(adapter._py, "combat_phase", "<none>")
        info["py_pending_attackers"] = list(getattr(adapter._py, "_pending_attackers", []))
        info["py_pending_blockers"] = list(getattr(adapter._py, "_pending_blockers", []))
        # Probe Rust determinism: call rs.legal_decisions(ap) twice
        rs_call_1 = sorted({d.get("kind") for d in rs.legal_decisions(ap)})
        rs_call_2 = sorted({d.get("kind") for d in rs.legal_decisions(ap)})
        info["rs_call_1_kinds"] = rs_call_1
        info["rs_call_2_kinds"] = rs_call_2
        # query Rust adapter the same way the harness did
        ra_legal_set = canon_set(ra.legal_decisions())
        info["ra_legal_set"] = [str(x) for x in sorted(ra_legal_set)]
        # Inspect what was cached
        info["ra_cached_value_kinds"] = sorted(
            {d.get("kind") for d in (ra._legal_cache_value or [])}
        )
        # Force invalidate the cache and re-query — does it still differ?
        ra._invalidate_legal_cache()
        ra_legal_set_post = canon_set(ra.legal_decisions())
        info["ra_legal_set_post_invalidate"] = [
            str(x) for x in sorted(ra_legal_set_post)
        ]
        # And raw rust dicts for `ap`
        rust_dicts = list(rs.legal_decisions(ap))
        info["rust_raw_n"] = len(rust_dicts)
        info["rust_raw_kinds"] = sorted({d.get("kind") for d in rust_dicts})
        rust_cast_ids = sorted(
            d.get("card_id") for d in rust_dicts if d.get("kind") == "cast_spell"
        )
        info["rust_raw_cast_card_ids"] = rust_cast_ids
        # Try the printing_name lookup for the divergent ids
        miss_ids = []
        for c in casts:
            cid = c[1]
            try:
                nm = rs.printing_name_of(cid)
            except Exception:
                nm = None
            miss_ids.append({"card_id": cid, "rust_printing_name": nm})
        info["divergent_id_in_rust_zones"] = miss_ids
    except Exception as e:  # noqa: BLE001
        info["rust_inspect_err"] = str(e)
    # Show cache history events for the divergence phase only
    history = info.pop("_history", [])
    # Find the first populate where pid=1 returned just [pass_priority]
    # AT phase=5 — that's the stale-causing populate we need.
    info["cache_history_n_total"] = len(history)
    target_idx = None
    # Find the LAST populate with pid=1 kinds=[pass_priority] at phase 5
    # — that's the stale-causing populate.
    for i, e in enumerate(history):
        if (e.get("event") == "populate"
            and e.get("pid") == 1
            and e.get("kinds") == ["pass_priority"]
            and e.get("rust_phase") == 5
            and e.get("rust_pri") == 0):
            target_idx = i
    if target_idx is not None:
        info["stale_populate_idx"] = target_idx
        info["events_around_stale_populate"] = history[max(0,target_idx-3):target_idx+25]
    info["cast_details"] = []
    for c in casts:
        cid = c[1]
        # locate the card in any of the queried player's zones
        card = None
        owner_pid = None
        for pl in es.players:
            for z_name, z in (("hand", pl.hand), ("graveyard", pl.graveyard),
                              ("exile", pl.exile)):
                for o in z:
                    if o.id == cid:
                        card = o
                        owner_pid = pl.id
        cd = {"card_id": cid, "canon": str(c)}
        if card is None:
            cd["card"] = "<NOT FOUND in any zone>"
            info["cast_details"].append(cd)
            continue
        pr = card.printing
        cd["name"] = pr.name
        cd["zone"] = str(card.zone)
        cd["owner_pid"] = owner_pid
        cd["is_instant"] = pr.is_instant
        cd["is_creature"] = pr.is_creature
        cd["is_sorcery"] = pr.is_sorcery
        cd["is_enchantment"] = getattr(pr, "is_enchantment", False)
        cd["is_artifact"] = getattr(pr, "is_artifact", False)
        cd["is_planeswalker"] = getattr(pr, "is_planeswalker", False)
        cd["is_land"] = getattr(pr, "is_land", False)
        cd["is_battle"] = getattr(pr, "is_battle", False)
        cd["is_room"] = getattr(pr, "is_room", False)
        cd["mana_cost"] = str(pr.mana_cost)
        cd["keywords"] = sorted(pr.keywords)
        # Surface salient cost / additional-cost flags that drive
        # additional_costs_payable.
        cost_flags = {}
        for attr in dir(pr):
            if attr.startswith("_"):
                continue
            if (attr.startswith("additional_cost_")
                or attr.startswith("has_")
                or attr in ("impending_cost", "impending_cost_str",
                            "warp_cost", "warp_cost_str",
                            "kicker_cost", "kicker_costs",
                            "alt_cost", "alt_casting_costs")):
                try:
                    v = getattr(pr, attr)
                except Exception:
                    continue
                if v not in (False, None, "", [], {}, ()):
                    cost_flags[attr] = str(v)[:120]
        cd["cost_flags"] = cost_flags
        # Evaluate Python's C1 gates for the queried player (ap)
        try:
            eff = apply_cost_reductions(pr, es, ap, pr.mana_cost)
            cd["effective_mana_cost"] = str(eff)
            cd["can_cast(mana)"] = _can_cast(es, ap, card, eff)
        except Exception as e:  # noqa: BLE001
            cd["can_cast(mana)"] = f"<err {e}>"
        try:
            cd["targets_satisfiable"] = _targets_are_satisfiable(
                es, ap, card
            )
        except Exception as e:  # noqa: BLE001
            cd["targets_satisfiable"] = f"<err {e}>"
        try:
            cd["additional_costs_payable"] = _additional_costs_payable(
                es, ap, card
            )
        except Exception as e:  # noqa: BLE001
            cd["additional_costs_payable"] = f"<err {e}>"
        # Whether the card is even in the queried player's hand
        qp = es.player_by_id(ap)
        cd["in_queried_player_hand"] = any(
            o.id == cid for o in qp.hand
        )
        info["cast_details"].append(cd)
    return info


if __name__ == "__main__":
    targets = G7D_V2_RESIDUALS
    if len(sys.argv) > 1:
        a, s = int(sys.argv[1]), int(sys.argv[2])
        targets = [(a, s)]
    out = []
    for a, s in targets:
        try:
            info = characterize(a, s)
        except Exception as e:  # noqa: BLE001
            import traceback
            info = {
                "arch": a, "seed": s, "result": f"EXC:{type(e).__name__}",
                "msg": str(e)[:300],
                "tb": traceback.format_exc()[-800:],
            }
        out.append(info)
        print(json.dumps(info, indent=2, default=str))
        print("=" * 70)
    # Summary across all
    print("\n\n#### SUMMARY ####")
    for info in out:
        r = info.get("result")
        if r == "LEGAL_SET_EQ":
            cds = info.get("cast_details", [])
            names = "; ".join(
                f"{c.get('name','?')} "
                f"[I={c.get('is_instant')} C={c.get('is_creature')} "
                f"S={c.get('is_sorcery')} E={c.get('is_enchantment')} "
                f"A={c.get('is_artifact')} L={c.get('is_land')} "
                f"BTL={c.get('is_battle')} ROOM={c.get('is_room')}] "
                f"cost={c.get('mana_cost')} "
                f"add={c.get('additional_costs')} "
                f"kw={c.get('keywords')} "
                f"can_cast(mana)={c.get('can_cast(mana)')} "
                f"tgt={c.get('targets_satisfiable')} "
                f"addgate={c.get('additional_costs_payable')} "
                f"inhand={c.get('in_queried_player_hand')} "
                f"flags={c.get('cost_flags')}"
                for c in cds
            )
            print(
                f"arch{info['arch']}/s{info['seed']} step{info['step']} "
                f"queried_ap={info.get('rust_active_player')} "
                f"has_prio={info.get('py_has_priority(ap)')} "
                f"sorc={info.get('py_is_sorcery_timing(ap)')} "
                f"step={info.get('py_step')} stack={info.get('py_stack_len')} "
                f":: {names}"
            )
        else:
            print(
                f"arch{info['arch']}/s{info['seed']} -> {r} "
                f"{info.get('detail','')[:120]}"
            )
