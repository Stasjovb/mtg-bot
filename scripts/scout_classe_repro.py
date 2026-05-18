"""Throwaway verify-first scout for G7 S6 Class-E (mana-source COLOR
divergence on ActivateAbility auto-tap-pay).

Drives the canonical Class-E repro (arch1/s0 — doc cites step 598
ActivateAbility, Python U:2 vs Rust G:2) through the role-swapped
rust_shadow bake-in, instrumenting the diverging decision: the last
decision applied before the STATE_EQ trip, the pre/post mana pools on
BOTH engines, the activated source's mana ability, and the tappable
land state.
"""
import random
import sys
from collections import Counter

from mtg_bot.parity import trajectory
from mtg_bot.search.rust_shadow import (
    ShadowDivergenceError,
    build_shadow_checked_adapter,
)


def _py_pool(adapter):
    st = adapter._py.engine_state
    out = {}
    for p in st.players:
        c = Counter()
        for coin in p.mana_pool:
            c[coin.color] += 1
        out[p.id] = dict(c)
    return out


def _rust_pool(adapter):
    try:
        from mtg_bot.parity.cross_engine import parity_smoke
        ps = parity_smoke()
        rv = ps._build_field_view(adapter._rust.rust_state)
        return {k: v for k, v in rv.items() if "mana_pool" in k}
    except Exception as e:  # noqa: BLE001
        return {"err": repr(e)}


def _py_lands(adapter):
    st = adapter._py.engine_state
    out = []
    for o in st.battlefield:
        if o.printing.is_land:
            from mtg_bot.game import effective_land_produces
            out.append(
                (o.id, o.printing.name, o.controller_id, o.tapped,
                 tuple(sorted(effective_land_produces(st, o))))
            )
    return out


def _py_source_ability(adapter, source_id):
    st = adapter._py.engine_state
    src = next((o for o in st.battlefield if o.id == source_id), None)
    if src is None:
        return f"source {source_id} not on bf"
    from mtg_bot.game import effective_activated_abilities
    abs_ = effective_activated_abilities(st, src)
    info = [f"{src.printing.name} (id={source_id}) abilities:"]
    for i, ab in enumerate(abs_):
        info.append(f"  [{i}] cost.mana={ab.cost.mana!r} "
                    f"effect={type(ab.effect).__name__} "
                    f"tap_self={ab.cost.tap_self}")
    return "\n".join(info)


def main(archetype: int, seed: int, max_steps: int = 4000):
    deck_names = trajectory.load_production_deck(archetype=archetype)
    spec = trajectory.production_deck_to_deckspec(
        deck_names, shared_rng_seed=seed
    )
    adapter = build_shadow_checked_adapter(spec)
    rng = random.Random(seed)

    history = []
    steps = 0
    prev_py_pool = None
    prev_rust_pool = None
    try:
        while steps < max_steps:
            if adapter.is_terminal():
                print("terminal, no divergence", archetype, seed)
                return 0
            legal = adapter.legal_decisions()
            if not legal:
                print("empty legal set at step", steps)
                return 2
            choice = rng.choice(legal)
            history.append((steps, repr(choice)))
            if len(history) > 8:
                history.pop(0)
            prev_py_pool = _py_pool(adapter)
            prev_rust_pool = _rust_pool(adapter)
            src_info = None
            if type(choice).__name__ == "ActivateAbility":
                src_info = _py_source_ability(adapter, choice.source_id)
            adapter.apply(choice)
            steps += 1
    except ShadowDivergenceError as e:
        print("=" * 72)
        print(f"DIVERGENCE arch{archetype}/s{seed} step {steps}  "
              f"tripwire={e.tripwire}")
        print(f"detail={e}".encode("ascii", "replace").decode())
        print("-" * 72)
        print("DIVERGING decision (the apply that tripped STATE_EQ):")
        print(f"  step {steps}: {history[-1][1]}")
        print("recent history:")
        for n, d in history:
            print(f"  step {n}: {d}")
        print("-" * 72)
        if src_info:
            print(src_info)
        print("-" * 72)
        print("PRE-apply Python pool:", prev_py_pool)
        print("PRE-apply Rust  pool:", prev_rust_pool)
        print("POST-apply Python pool:", _py_pool(adapter))
        print("POST-apply Rust  pool:", _rust_pool(adapter))
        print("-" * 72)
        print("Python lands on bf (id,name,ctrl,tapped,produces):")
        for L in _py_lands(adapter):
            print("   ", L)
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"EXCEPTION step {steps}: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 3
    print("no divergence/timeout", archetype, seed, "steps", steps)
    return 4


if __name__ == "__main__":
    a = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    s = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    raise SystemExit(main(a, s))
