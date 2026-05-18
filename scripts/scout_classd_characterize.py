"""Throwaway diagnostic: characterize the G7 S6 Class-D cast-set
asymmetry (LEGAL_SET_EQ rust\\py=['cast_spell',N,...] py\\rust=[]).

Drives a Class-D repro through the role-swapped rust_shadow harness,
intercepts at the exact divergence step, and dumps:
  * the divergent decision (card id, card name, variant flags)
  * priority_player_idx / active_player_idx on BOTH engines
  * step / phase
  * the Python legal_actions vs Rust legal_decisions split
  * whether Python's _has_priority gate is the discriminator
  * whether the C1 gates (_can_cast / _targets_are_satisfiable /
    _additional_costs_payable) admit the card when queried for the
    Rust-driver active player

NOT a production entrypoint — agent-generated investigation tool.
"""
from __future__ import annotations

import sys

from mtg_bot.parity import trajectory
from mtg_bot.search import rust_shadow
from mtg_bot.search.rust_shadow import (
    ShadowDivergenceError,
    build_shadow_checked_adapter,
    canon_decision,
)
import random


CLASSD = [
    (7, 0), (7, 3), (8, 3), (8, 4), (16, 3), (17, 3), (18, 2),
    (18, 3), (30, 1), (34, 1), (34, 3), (38, 0), (38, 1), (38, 3),
    (41, 0), (41, 1), (41, 2), (41, 3), (41, 4), (44, 1), (44, 3),
    (59, 1), (59, 4),
]


def characterize(arch: int, seed: int, verbose: bool = True) -> dict:
    deck_names = trajectory.load_production_deck(archetype=arch)
    spec = trajectory.production_deck_to_deckspec(
        deck_names, shared_rng_seed=seed,
    )
    adapter = build_shadow_checked_adapter(spec)
    rng = random.Random(seed)
    steps = 0
    info: dict = {"arch": arch, "seed": seed}
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
            # Re-derive the split WITHOUT the assertion so we can
            # inspect both engines' raw legal output + state.
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
    py_ap = py.active_player()
    py_ref = legal_actions(es, ap)

    from mtg_bot.search.rust_shadow import canon_set

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
    info["py_active_player"] = py_ap
    info["py_priority_player_idx"] = es.priority_player_idx
    info["py_active_player_idx"] = es.active_player_idx
    info["py_priority_player_id"] = es.players[es.priority_player_idx].id
    info["py_active_player_id"] = es.players[es.active_player_idx].id
    info["py_step"] = str(es.step)
    info["py_stack_len"] = len(es.stack)
    info["py_combat_phase"] = py.combat_phase
    try:
        info["rust_priority_player"] = rust.rust_state.priority_player()
    except Exception as e:  # noqa: BLE001
        info["rust_priority_player"] = f"<err {e}>"
    try:
        info["rust_active_player_idx"] = rust.rust_state.active_player()
    except Exception as e:  # noqa: BLE001
        info["rust_active_player_idx"] = f"<err {e}>"

    # _has_priority gate check for the queried (Rust-driver active) pid
    info["py_has_priority(ap)"] = _has_priority(es, ap)
    info["py_is_sorcery_timing(ap)"] = _is_sorcery_timing(es, ap)

    # For each only-rust cast_spell, find the card and check the C1
    # gates as Python would evaluate them for the queried player.
    casts = [
        x for x in only_rust
        if isinstance(x, tuple) and x and x[0] == "cast_spell"
    ]
    info["cast_details"] = []
    for c in casts:
        cid = c[1]
        # locate the card
        card = None
        owner_pid = None
        for pl in es.players:
            for z in (pl.hand, pl.graveyard, pl.exile):
                for o in z:
                    if o.id == cid:
                        card = o
                        owner_pid = pl.id
        cd = {"card_id": cid, "canon": str(c)}
        if card is None:
            cd["card"] = "<NOT FOUND in py hand/gy/exile>"
            info["cast_details"].append(cd)
            continue
        pr = card.printing
        cd["name"] = pr.name
        cd["zone"] = str(card.zone)
        cd["owner_pid"] = owner_pid
        cd["is_instant"] = pr.is_instant
        cd["is_creature"] = pr.is_creature
        cd["is_sorcery"] = pr.is_sorcery
        cd["keywords"] = sorted(pr.keywords)
        # Evaluate the C1 gates for the queried player (ap)
        try:
            eff = apply_cost_reductions(pr, es, ap, pr.mana_cost)
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
    import json

    targets = CLASSD
    if len(sys.argv) > 1:
        # scout_classd_characterize.py 7 0  -> single
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
            names = ",".join(
                f"{c.get('name','?')}"
                f"[mana={c.get('can_cast(mana)')},"
                f"tgt={c.get('targets_satisfiable')},"
                f"add={c.get('additional_costs_payable')},"
                f"inhand={c.get('in_queried_player_hand')}]"
                for c in cds
            )
            print(
                f"arch{info['arch']}/s{info['seed']} step{info['step']} "
                f"py_prio_idx={info.get('py_priority_player_idx')} "
                f"py_act_idx={info.get('py_active_player_idx')} "
                f"rust_prio={info.get('rust_priority_player')} "
                f"rust_act={info.get('rust_active_player_idx')} "
                f"queried_ap={info.get('rust_active_player')} "
                f"has_prio(ap)={info.get('py_has_priority(ap)')} "
                f"sorc(ap)={info.get('py_is_sorcery_timing(ap)')} "
                f"step={info.get('py_step')} "
                f"stack={info.get('py_stack_len')} "
                f"combat={info.get('py_combat_phase')} :: {names}"
            )
        else:
            print(
                f"arch{info['arch']}/s{info['seed']} -> {r} "
                f"{info.get('detail','')[:120]}"
            )
