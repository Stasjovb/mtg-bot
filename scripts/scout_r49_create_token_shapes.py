"""Round-49 N1 scout: enumerate the CreateToken rider shapes in the
EoE pool and the 17lands deck pool.

For every EoE printing whose parsed triggered_abilities contain a
CreateToken (or CreateToken-family) effect, print:
  * the carrier name + type-line
  * the trigger event + predicate
  * the CreateToken rider fields (count, each_player, tapped,
    attacking, schedule_end_of_combat_sacrifice)
  * the token_printing's name / type-line / power / toughness /
    keywords / activated_abilities-count / triggered_abilities-count
  * whether the carrier is otherwise bridge-simple (every OTHER
    trigger round-trips + no unsafe keyword/static/etc.)

Also reports which of these carriers appear in the 17lands deck pool
(data/17lands/eoe_decks.json.gz) and how many decks reference them.

Pure diagnostic — not a production entrypoint.
"""
from __future__ import annotations

import collections
import gzip
import json
import pathlib

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.tokens import (
    CreateToken,
    CreateTokenAndAttachSelf,
    CreateTokenCopyOfTargetCreatureYouControl,
    CreateTokenPerMulticoloredPermanent,
)

REPO = pathlib.Path(__file__).resolve().parents[1]
POOL = REPO / "data" / "17lands" / "eoe_decks.json.gz"
if not POOL.exists():
    POOL = REPO.parent / "mtg-bot" / "data" / "17lands" / "eoe_decks.json.gz"

CREATE_TOKEN_CLASSES = (
    CreateToken,
    CreateTokenAndAttachSelf,
    CreateTokenCopyOfTargetCreatureYouControl,
    CreateTokenPerMulticoloredPermanent,
)


def _token_summary(tp) -> str:
    if tp is None:
        return "<none>"
    aa = len(getattr(tp, "activated_abilities", ()) or ())
    ta = len(getattr(tp, "triggered_abilities", ()) or ())
    kw = sorted(getattr(tp, "keywords", frozenset()) or frozenset())
    return (
        f"name={tp.name!r} type={tp.type_line!r} "
        f"P/T={tp.power}/{tp.toughness} kw={kw} "
        f"activated_abilities={aa} triggered_abilities={ta}"
    )


def main() -> None:
    src = get_active_source()
    printings = src.get_printings()

    # name -> deck-count in 17lands pool
    deck_count: collections.Counter = collections.Counter()
    if POOL.exists():
        with gzip.open(POOL, "rt") as fh:
            decks = json.load(fh)
        for d in decks:
            for nm in set(d["cards"]):
                deck_count[nm] += 1

    rows = []
    for name, pr in printings.items():
        tas = getattr(pr, "triggered_abilities", ()) or ()
        for ta in tas:
            eff = getattr(ta, "effect", None)
            if not isinstance(eff, CREATE_TOKEN_CLASSES):
                continue
            ev = getattr(ta, "event", None)
            pred = getattr(ta, "predicate", None)
            tp = getattr(eff, "token_printing", None)
            rider = {}
            for fld in (
                "count", "each_player", "tapped", "attacking",
                "schedule_end_of_combat_sacrifice",
            ):
                if hasattr(eff, fld):
                    rider[fld] = getattr(eff, fld)
            rows.append({
                "carrier": name,
                "type_line": pr.type_line,
                "effect_cls": type(eff).__name__,
                "event": getattr(ev, "name", str(ev)),
                "predicate": type(pred).__name__ if pred is not None else None,
                "predicate_repr": repr(pred)[:120] if pred is not None else None,
                "rider": rider,
                "token": _token_summary(tp),
                "n_other_triggers": len(tas) - 1,
                "carrier_keywords": sorted(pr.keywords or frozenset()),
                "carrier_activated": len(pr.activated_abilities or ()),
                "carrier_static": len(pr.static_abilities or ()),
                "carrier_warp": pr.warp_cost is not None,
                "deck_count": deck_count.get(name, 0),
            })

    print(f"=== EoE CreateToken-family carriers: {len(rows)} ===\n")
    for r in sorted(rows, key=lambda x: (-x["deck_count"], x["carrier"])):
        print(f"--- {r['carrier']}  ({r['type_line']})")
        print(f"    effect_cls = {r['effect_cls']}")
        print(f"    event      = {r['event']}  predicate = {r['predicate']}")
        if r["predicate_repr"]:
            print(f"    pred_repr  = {r['predicate_repr']}")
        print(f"    rider      = {r['rider']}")
        print(f"    token      = {r['token']}")
        print(
            f"    carrier    : other_triggers={r['n_other_triggers']} "
            f"kw={r['carrier_keywords']} activated={r['carrier_activated']} "
            f"static={r['carrier_static']} warp={r['carrier_warp']}"
        )
        print(f"    deck_count = {r['deck_count']}")
        print()

    # Aggregate: distinct token printings + rider-shape histogram
    by_token = collections.Counter(
        r["token"].split(" type=")[0] for r in rows
    )
    print("=== Distinct token printings (by name) ===")
    for k, v in by_token.most_common():
        print(f"  {v:3d}  {k}")
    print()
    by_rider = collections.Counter(
        json.dumps(r["rider"], sort_keys=True) for r in rows
    )
    print("=== Rider-shape histogram ===")
    for k, v in by_rider.most_common():
        print(f"  {v:3d}  {k}")


if __name__ == "__main__":
    main()
