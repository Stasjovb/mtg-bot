"""Round-53 N1 scout (Phase 3a): enumerate the fixed-single-Lander-
token carriers in the EoE pool + their 17lands deck counts, and report
which flip drop->admit under Phase 3a vs. which stay §2-declined.

Phase 3a admits a carrier iff:
  * it is a bridge-simple creature on every OTHER axis (keywords ⊆
    _SAFE_KEYWORDS, no static/activated/warp/etc.),
  * its ONLY token-creating trigger is the fixed-single-token shape
    (ENTERS|DIES + IsSelf + CreateToken count>=1, all riders default
    EXCEPT the bare/tapped already-supported profiles),
  * the produced token is the bare Lander whose ONLY activated
    ability is the bridge-correct
    ``{2}, Sac: SearchLibraryForBasicLandTapped`` shape (the round-52
    precursor verified this round-trips with NO §2 gap), and
  * the Lander carries NO keywords / static / triggered / nested
    abilities beyond that single activated ability.

Any carrier whose Lander rider is each_player/attacking/scheduled, or
whose Lander has an extra ability, stays declined.

Pure diagnostic — not a production entrypoint.
"""
from __future__ import annotations

import collections
import gzip
import json
import pathlib

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.tokens import CreateToken

REPO = pathlib.Path(__file__).resolve().parents[1]
POOL = REPO / "data" / "17lands" / "eoe_decks.json.gz"
if not POOL.exists():
    POOL = REPO.parent / "mtg-bot" / "data" / "17lands" / "eoe_decks.json.gz"


def _is_bare_lander_token(tp) -> tuple[bool, str]:
    """True iff ``tp`` is the bare Lander: non-creature Artifact, no
    P/T, NO keywords/static/triggered, exactly ONE activated ability
    which is the bridge-correct {2},Sac:SearchLibraryForBasicLandTapped.
    """
    from mtg_bot.effects.base import ActivatedAbility
    from mtg_bot.effects.generic.search import (
        SearchLibraryForBasicLandTapped,
    )

    if tp is None:
        return False, "token is None"
    if tp.name != "Lander":
        return False, f"token name={tp.name!r} (not Lander)"
    if "Creature" in (tp.card_types or ()):
        return False, "token is a Creature (vanilla path handles it)"
    if tp.keywords:
        return False, f"token keywords={sorted(tp.keywords)}"
    if getattr(tp, "static_abilities", None):
        return False, "token has static abilities"
    if getattr(tp, "triggered_abilities", None):
        return False, "token has triggered abilities"
    aas = tuple(tp.activated_abilities or ())
    if len(aas) != 1:
        return False, f"token has {len(aas)} activated abilities (need 1)"
    aa = aas[0]
    if not isinstance(aa, ActivatedAbility):
        return False, "activated ability is not ActivatedAbility"
    c = aa.cost
    if c.mana is None or c.mana.generic != 2 or c.mana.colored:
        return False, f"cost mana not exactly {{2}}: {c.mana!r}"
    if not c.sacrifice_self:
        return False, "cost lacks sacrifice_self"
    # No other cost component (tap, other sac, target, etc.)
    for fld in (
        "tap_self", "requires_target_creature_you_control",
        "sacrifice_another_creature_or_artifact", "sacrifice_a_land",
        "sacrifice_another_artifact", "sacrifice_food",
        "sacrifice_a_desert",
    ):
        if getattr(c, fld, False):
            return False, f"cost has extra component {fld}"
    if not isinstance(aa.effect, SearchLibraryForBasicLandTapped):
        return False, f"effect {type(aa.effect).__name__} not search"
    if aa.effect.count != 1:
        return False, f"search count={aa.effect.count} (need 1)"
    if aa.is_mana_ability:
        return False, "ability flagged is_mana_ability"
    return True, "bare bridge-correct Lander"


def main() -> None:
    src = get_active_source()
    printings = src.get_printings()

    deck_count: collections.Counter = collections.Counter()
    n_decks = 0
    if POOL.exists():
        with gzip.open(POOL, "rt") as fh:
            decks = json.load(fh)
        n_decks = len(decks)
        for d in decks:
            for nm in set(d["cards"]):
                deck_count[nm] += 1

    rows = []
    for name, pr in printings.items():
        tas = tuple(getattr(pr, "triggered_abilities", ()) or ())
        ct_tas = [
            ta for ta in tas
            if isinstance(getattr(ta, "effect", None), CreateToken)
        ]
        if not ct_tas:
            continue
        # Only look at carriers whose CreateToken makes a Lander.
        lander_tas = [
            ta for ta in ct_tas
            if getattr(getattr(ta, "effect", None), "token_printing", None)
            is not None
            and ta.effect.token_printing.name == "Lander"
        ]
        if not lander_tas:
            continue
        info = {
            "carrier": name,
            "type_line": pr.type_line,
            "deck_count": deck_count.get(name, 0),
            "n_create_token_tas": len(ct_tas),
            "n_lander_tas": len(lander_tas),
            "n_total_tas": len(tas),
            "keywords": sorted(pr.keywords or frozenset()),
            "activated": len(pr.activated_abilities or ()),
            "static": len(pr.static_abilities or ()),
            "warp": pr.warp_cost is not None,
            "is_creature": "Creature" in (pr.card_types or ()),
        }
        decisions = []
        for ta in lander_tas:
            eff = ta.effect
            riders = {
                "count": eff.count,
                "each_player": eff.each_player,
                "tapped": eff.tapped,
                "attacking": eff.attacking,
                "sched": getattr(
                    eff, "schedule_end_of_combat_sacrifice", False
                ),
            }
            ev = getattr(ta.event, "name", str(ta.event))
            pred = type(ta.predicate).__name__ if ta.predicate else None
            ok_tok, tok_reason = _is_bare_lander_token(
                eff.token_printing
            )
            # Phase 3a supported rider profile: bare (all default) or
            # tapped=True only (Phase 4 sister). each_player/attacking/
            # sched => declined.
            rider_ok = (
                not eff.each_player
                and not eff.attacking
                and not riders["sched"]
            )
            decisions.append({
                "event": ev,
                "predicate": pred,
                "riders": riders,
                "token_ok": ok_tok,
                "token_reason": tok_reason,
                "rider_ok": rider_ok,
            })
        info["decisions"] = decisions
        rows.append(info)

    print(f"=== EoE Lander-token carriers: {len(rows)} "
          f"(pool {n_decks} decks) ===\n")
    admit_total = 0
    declined = []
    for r in sorted(rows, key=lambda x: (-x["deck_count"], x["carrier"])):
        print(f"--- {r['carrier']}  ({r['type_line']})")
        print(f"    deck_count = {r['deck_count']}")
        print(
            f"    carrier    : creature={r['is_creature']} "
            f"kw={r['keywords']} activated={r['activated']} "
            f"static={r['static']} warp={r['warp']} "
            f"total_tas={r['n_total_tas']} lander_tas={r['n_lander_tas']}"
        )
        all_ok = (
            r["is_creature"]
            and r["activated"] == 0
            and r["static"] == 0
            and not r["warp"]
        )
        for d in r["decisions"]:
            print(
                f"      trig: ev={d['event']} pred={d['predicate']} "
                f"riders={d['riders']}"
            )
            print(
                f"            token_ok={d['token_ok']} "
                f"({d['token_reason']}) rider_ok={d['rider_ok']}"
            )
            if not (d["token_ok"] and d["rider_ok"]):
                all_ok = False
        verdict = "ADMIT" if all_ok else "DECLINE"
        if all_ok:
            admit_total += r["deck_count"]
        else:
            declined.append(r["carrier"])
        print(f"    => Phase 3a: {verdict}\n")

    print(f"=== Phase 3a cumulative 17lands decks admitted: "
          f"{admit_total} ===")
    print(f"=== Declined carriers: {declined} ===")


if __name__ == "__main__":
    main()
