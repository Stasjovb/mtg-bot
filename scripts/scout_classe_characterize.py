"""Characterize ALL 31 Class-E repros: confirm each is the same
generic-cost pool-drain-order divergence (Python pool-list-order vs
Rust fixed C->W->U->B->R->G), and record the diverging decision +
cost shape + pre/post pools for each.
"""
import random
import sys
from collections import Counter

from mtg_bot.parity import trajectory
from mtg_bot.search.rust_shadow import (
    ShadowDivergenceError,
    build_shadow_checked_adapter,
)

CLASS_E = [
    (1, 0), (10, 0), (11, 0), (12, 0), (15, 3), (21, 0), (24, 1),
    (25, 1), (28, 1), (28, 3), (28, 4), (32, 1), (32, 2), (37, 2),
    (37, 3), (39, 2), (39, 4), (42, 0), (42, 3), (45, 0), (46, 0),
    (48, 0), (48, 1), (48, 2), (48, 3), (50, 3), (52, 1), (52, 2),
    (52, 3), (55, 0), (55, 3),
]


def _pool_list(adapter, pid):
    st = adapter._py.engine_state
    p = next(pp for pp in st.players if pp.id == pid)
    return [c.color for c in p.mana_pool]


def characterize(archetype, seed):
    deck = trajectory.load_production_deck(archetype=archetype)
    spec = trajectory.production_deck_to_deckspec(
        deck, shared_rng_seed=seed
    )
    ad = build_shadow_checked_adapter(spec)
    rng = random.Random(seed)
    steps = 0
    last = None
    cost_shape = None
    pre_pool = None
    try:
        while steps < 4000:
            if ad.is_terminal():
                return ("TERMINAL", None, None, None, None)
            legal = ad.legal_decisions()
            if not legal:
                return ("EMPTY_LEGAL", steps, None, None, None)
            ch = rng.choice(legal)
            last = ch
            if type(ch).__name__ == "ActivateAbility":
                st = ad._py.engine_state
                src = next((o for o in st.battlefield
                            if o.id == ch.source_id), None)
                if src is not None:
                    from mtg_bot.game import effective_activated_abilities
                    abs_ = effective_activated_abilities(st, src)
                    if 0 <= ch.ability_index < len(abs_):
                        ab = abs_[ch.ability_index]
                        cost_shape = repr(ab.cost.mana)
                pre_pool = {0: _pool_list(ad, 0), 1: _pool_list(ad, 1)}
            elif type(ch).__name__ == "CastSpell":
                pre_pool = {0: _pool_list(ad, 0), 1: _pool_list(ad, 1)}
                cost_shape = "CastSpell"
            ad.apply(ch)
            steps += 1
    except ShadowDivergenceError as e:
        return (e.tripwire, steps, type(last).__name__,
                cost_shape, (str(e)[:130], pre_pool))
    except Exception as e:  # noqa: BLE001
        return ("EXC:" + type(e).__name__, steps, type(last).__name__,
                cost_shape, str(e)[:130])
    return ("TIMEOUT", steps, None, None, None)


def main():
    gen_cost_pool_order = 0
    other = []
    for a, s in CLASS_E:
        kind, step, last_t, cost, extra = characterize(a, s)
        is_gen = (
            kind == "STATE_EQ"
            and "mana_pool" in (extra[0] if isinstance(extra, tuple)
                                else str(extra))
        )
        tag = "GEN-POOL-ORDER" if is_gen else "OTHER"
        if is_gen:
            gen_cost_pool_order += 1
        else:
            other.append((a, s, kind, step, last_t, cost))
        print(f"arch{a}/s{s}: {tag} kind={kind} step={step} "
              f"last={last_t} cost={cost}")
        if isinstance(extra, tuple) and extra[1]:
            print(f"    detail={extra[0]}")
            print(f"    pre_pool={extra[1]}")
    print("=" * 60)
    print(f"GEN-POOL-ORDER (same root): {gen_cost_pool_order}/31")
    print(f"OTHER: {len(other)}")
    for o in other:
        print("  ", o)


if __name__ == "__main__":
    sys.exit(main())
