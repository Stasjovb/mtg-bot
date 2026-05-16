"""Round-50 N2 scout (docs-only slice): for each BLOCKED-RUST-EFFECT
residue card named in the round-49 EOE_PROBE_READINESS_AUDIT.md
refresh, pull its verbatim oracle text from data/edge_of_eternities.json
and its real-impact deck count from the 17lands EoE deck pool
(data/17lands/eoe_decks.json.gz).

"Deck count" = number of distinct 17lands archetype decks (out of the
~5000 in the pool) whose card list contains the residue card. This is
the real-world frequency signal used to rank which residue cards are
worth a bespoke Rust arm — a card in 0 decks closes 0 real probes no
matter how clean the shape.

Read-only. Prints a table; writes nothing. Per the scout convention
(CLAUDE.md), throwaway scout_*.py diagnostics stay under scripts/.
"""

from __future__ import annotations

import gzip
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
EOE_JSON = REPO / "data" / "edge_of_eternities.json"
DECKS_GZ = REPO / "data" / "17lands" / "eoe_decks.json.gz"

# The round-49-refresh BLOCKED-RUST-EFFECT residue (truly no-Rust-arm
# asks). Names must match the Scryfall `name` field in the EoE JSON.
RESIDUE = [
    "Astelli Reclaimer",
    "Command Bridge",
    "Pain for All",
    "Meltstrider's Resolve",
    "Lightstall Inquisitor",
    "Perigee Beckoner",
    "Monoist Circuit-Feeder",
    "Dauntless Scrapbot",
    "Faller's Faithful",
    "Roving Actuator",
    "Famished Worldsire",
    "Tractor Beam",
    "Pulsar Squadron Ace",
    "Mightform Harmonizer",
    "Warmaker Gunship",
    "Mechanozoa",
    "Extinguisher Battleship",
]


def load_eoe_oracle() -> dict[str, str]:
    raw = json.loads(EOE_JSON.read_text(encoding="utf-8"))
    cards = raw["data"] if isinstance(raw, dict) and "data" in raw else raw
    out: dict[str, str] = {}
    for c in cards:
        name = c.get("name")
        if not name:
            continue
        txt = c.get("oracle_text")
        if txt is None and "card_faces" in c:
            txt = " // ".join(
                f.get("oracle_text", "") for f in c["card_faces"]
            )
        tline = c.get("type_line", "")
        mc = c.get("mana_cost", "")
        out[name] = f"[{tline}] {mc}\n{txt or ''}".strip()
    return out


def deck_counts(names: list[str]) -> dict[str, int]:
    with gzip.open(DECKS_GZ, "rt", encoding="utf-8") as fh:
        decks = json.load(fh)
    counts = {n: 0 for n in names}
    nameset = set(names)
    for d in decks:
        # deck records vary; collect any card-name-bearing fields
        seen: set[str] = set()
        cardlist = None
        if isinstance(d, dict):
            for key in ("cards", "maindeck", "deck", "main", "pool"):
                if key in d:
                    cardlist = d[key]
                    break
        else:
            cardlist = d
        if cardlist is None:
            continue
        if isinstance(cardlist, dict):
            seen.update(cardlist.keys())
        elif isinstance(cardlist, list):
            for entry in cardlist:
                if isinstance(entry, str):
                    seen.add(entry)
                elif isinstance(entry, dict):
                    nm = entry.get("name") or entry.get("card")
                    if nm:
                        seen.add(nm)
        for n in nameset & seen:
            counts[n] += 1
    return counts


def main() -> int:
    oracle = load_eoe_oracle()
    counts = deck_counts(RESIDUE)
    print(f"# 17lands pool: {DECKS_GZ}")
    for n in RESIDUE:
        print("=" * 72)
        print(f"{n}   |   decks={counts.get(n, 0)}   |   in_eoe_json={n in oracle}")
        print("-" * 72)
        print(oracle.get(n, "<<NOT FOUND IN EOE JSON>>"))
    print("=" * 72)
    print("SUMMARY (name -> deck count):")
    for n, c in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {c:>5}  {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
