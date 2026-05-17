"""Round-59 N2 scout: enumerate the 23 ``nonbasic_land_substrate``-gated
pool-parity cards with their exact land shape.

`docs/SUBSYSTEM_ROADMAP.md` (round-58 N2) data-ranked the
non-basic-land substrate as the highest-leverage CLEAN next lever (23
cards, ALL single-gated, 34,575 cumulative 17lands decks). This scout
materializes each of those 23 from the live parser, classifies it into
a land sub-shape (vanilla-nonbasic-dual / enters-tapped / pay-life
(shock) / surveil-land / fetch-or-sac / activated-ability land /
planet-or-cave rider / mana-only), and attaches its 17lands
deck-count, so `docs/NONBASIC_LAND_SUBSTRATE_PLAN.md` can scope phases
data-first instead of by guesswork.

It reuses the round-58 ``subsystem_attribution`` helper VERBATIM
(``scripts/scout_r58_subsystem_attribution.py``) so the 23 here can
never disagree with the roadmap's non-basic-land single-gated set. The
sub-shape classifier reads the SAME live ``OracleParserCardSource``
printing the production-deck loader sees, plus the raw Scryfall
``oracle_text`` for the human-facing shape audit (the parser may not
materialize every rider as a structured field — the audit must reflect
real card text, not just parsed structure).

Read-only. Prints a per-card table + per-sub-shape rollup; writes
nothing.

Per the scout convention (CLAUDE.md), throwaway ``scout_*.py``
diagnostics stay under ``scripts/``.
"""

from __future__ import annotations

import collections
import gzip
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
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _resolve_data_file(rel: Path) -> Path:
    """Worktree-aware resolve: a feature worktree's gitignored data/
    blobs live only in the sibling main checkout (CLAUDE.md layout)."""
    local = REPO_ROOT / rel
    if local.exists():
        return local
    for cand in (
        REPO_ROOT.parent.parent / "mtg-bot" / rel,
        REPO_ROOT.parent / "mtg-bot" / rel,
    ):
        if cand.exists():
            return cand
    return local


DECKS_GZ = _resolve_data_file(Path("data") / "17lands" / "eoe_decks.json.gz")
EOE_JSON = _resolve_data_file(Path("data") / "edge_of_eternities.json")


# -------------------------------------------------- land sub-shapes
#
# Stable keys (the plan doc references these verbatim). Ordered roughly
# cleanest -> riskiest for the §2 bridge-correctness audit.
SHAPE_MANA_ONLY = "mana_only"               # untapped, {T}: Add — no rider
SHAPE_ENTERS_TAPPED = "enters_tapped"       # vanilla "enters tapped" dual
SHAPE_PAY_LIFE_SHOCK = "pay_life_shock"     # tapped-unless-pay-2-life
SHAPE_SURVEIL_LAND = "surveil_land"         # enters tapped + surveil ETB
SHAPE_FETCH_OR_SAC = "fetch_or_sac"         # fetchland / sac-for-effect
SHAPE_ACTIVATED_LAND = "activated_land"     # carries a non-mana activated
SHAPE_PLANET_CAVE_RIDER = "planet_cave_rider"  # planet/cave w/ a rider
SHAPE_UNKNOWN = "unknown"                    # classifier could not place

_SHAPE_LABEL = {
    SHAPE_MANA_ONLY: "mana-only (untapped vanilla nonbasic)",
    SHAPE_ENTERS_TAPPED: "enters-tapped (vanilla nonbasic dual)",
    SHAPE_PAY_LIFE_SHOCK: "pay-life shock (tapped unless pay 2 life)",
    SHAPE_SURVEIL_LAND: "surveil-land (enters tapped + surveil ETB)",
    SHAPE_FETCH_OR_SAC: "fetch / sac land",
    SHAPE_ACTIVATED_LAND: "activated-ability land (non-mana activated)",
    SHAPE_PLANET_CAVE_RIDER: "planet / cave with a rider",
    SHAPE_UNKNOWN: "UNKNOWN (needs hand re-walk)",
}


def _raw_oracle_by_name() -> dict[str, str]:
    """Map Scryfall card name -> oracle_text from the raw EoE dump.

    The parser may normalize / drop rider text into structured fields;
    the §2 audit must reflect the REAL printed text, so we read it
    straight from the cached Scryfall JSON.
    """
    if not EOE_JSON.exists():
        return {}
    with open(EOE_JSON, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    cards = data.get("data") if isinstance(data, dict) else data
    out: dict[str, str] = {}
    for c in cards or []:
        nm = c.get("name")
        if not nm:
            continue
        txt = c.get("oracle_text")
        if txt is None and "card_faces" in c:
            txt = "\n".join(
                f.get("oracle_text", "") for f in c["card_faces"]
            )
        out[nm] = txt or ""
    return out


def _classify_shape(printing, oracle: str) -> str:
    """Classify a non-basic land printing into a sub-shape.

    Reads structured printing fields first (the parser's view, which is
    what the bridge would have to carry) and falls back to the raw
    oracle text for riders the parser may not have structured.
    """
    o = (oracle or "").lower()

    # Activated-ability land: the parser materialized a non-mana
    # activated ability (the campaign-wide §2 decline — CardDef carries
    # no activated_abilities field for the production-deck loader).
    if printing.activated_abilities:
        return SHAPE_ACTIVATED_LAND

    # Fetch / sac land: text sacrifices itself to search/fetch.
    if "sacrifice" in o and ("search your library" in o or "{t}" in o):
        if "search your library" in o:
            return SHAPE_FETCH_OR_SAC

    # Surveil land: enters tapped AND a surveil ETB.
    if "surveil" in o and "enters tapped" in o:
        return SHAPE_SURVEIL_LAND

    # Pay-life shock: "unless you pay 2 life" gated tapped-entry.
    if "unless you pay" in o and "life" in o and "enters tapped" in o:
        return SHAPE_PAY_LIFE_SHOCK

    # A triggered ETB ability that isn't surveil/shock — planet/cave or
    # other rider.
    if printing.triggered_abilities:
        return SHAPE_PLANET_CAVE_RIDER

    # Plain "enters tapped" with no other rider.
    if "enters tapped" in o or re.search(
        r"enters the battlefield tapped", o
    ):
        return SHAPE_ENTERS_TAPPED

    # No tapped clause, no rider, just a mana ability.
    return SHAPE_MANA_ONLY


def _deck_counts(names: set[str]) -> dict[str, int]:
    if not DECKS_GZ.exists():
        return {n: 0 for n in names}
    with gzip.open(DECKS_GZ, "rt", encoding="utf-8") as fh:
        decks = json.load(fh)
    counts = {n: 0 for n in names}
    for d in decks:
        cl = d.get("cards") if isinstance(d, dict) else d
        if not cl:
            continue
        seen = set(cl) if isinstance(cl, list) else set()
        for n in names & seen:
            counts[n] += 1
    return counts


def main() -> int:
    import scout_r58_subsystem_attribution as r58  # noqa: E402
    from mtg_bot.cards.parser.source import OracleParserCardSource

    attr = r58.subsystem_attribution()
    nonbasic = sorted(
        attr["by_subsystem"].get(r58.SUB_NONBASIC_LAND, [])
    )
    single = set(attr["single_gate"].get(r58.SUB_NONBASIC_LAND, []))

    printings = OracleParserCardSource().get_printings()
    oracle = _raw_oracle_by_name()
    dc = _deck_counts(set(nonbasic))

    by_shape: dict[str, list[tuple[str, int, str]]] = (
        collections.defaultdict(list)
    )

    print(
        f"# non-basic-land substrate enumeration — "
        f"{len(nonbasic)} cards (round-58 roadmap non-basic-land row)"
    )
    print(
        f"# single-gated: {len(single)} / {len(nonbasic)}  "
        f"(roadmap claims ALL single-gated; reconcile below)"
    )
    print()
    hdr = (
        f"{'card':<26} {'shape':<22} {'decks':>6} {'1g':>3} "
        f"{'type_line':<34} {'produces':<10}"
    )
    print(hdr)
    print("-" * len(hdr))
    for name in nonbasic:
        pr = printings[name]
        shape = _classify_shape(pr, oracle.get(name, ""))
        n_decks = dc.get(name, 0)
        is_single = "Y" if name in single else "."
        produces = ",".join(sorted(pr.produces)) if pr.produces else "-"
        tline = getattr(pr, "type_line", "") or ""
        by_shape[shape].append((name, n_decks, oracle.get(name, "")))
        print(
            f"{name:<26} {shape:<22} {n_decks:>6} {is_single:>3} "
            f"{tline:<34} {produces:<10}"
        )

    print()
    print("# per-sub-shape rollup")
    roll_hdr = f"{'sub-shape':<46} {'#cards':>6} {'decks':>8}"
    print(roll_hdr)
    print("-" * len(roll_hdr))
    shape_order = [
        SHAPE_MANA_ONLY,
        SHAPE_ENTERS_TAPPED,
        SHAPE_PAY_LIFE_SHOCK,
        SHAPE_SURVEIL_LAND,
        SHAPE_FETCH_OR_SAC,
        SHAPE_ACTIVATED_LAND,
        SHAPE_PLANET_CAVE_RIDER,
        SHAPE_UNKNOWN,
    ]
    for sh in shape_order:
        members = by_shape.get(sh, [])
        if not members:
            continue
        tot = sum(d for _, d, _ in members)
        print(f"{_SHAPE_LABEL[sh]:<46} {len(members):>6} {tot:>8}")

    print()
    print("# oracle text per card (the §2 audit source of truth)")
    for sh in shape_order:
        members = by_shape.get(sh, [])
        if not members:
            continue
        print(f"\n## {_SHAPE_LABEL[sh]}")
        for name, n_decks, txt in sorted(
            members, key=lambda m: -m[1]
        ):
            flat = " | ".join(
                ln.strip() for ln in txt.splitlines() if ln.strip()
            )
            print(f"  - {name} ({n_decks} decks): {flat}")

    # Reconciliation: the roadmap claims ALL 23 single-gated.
    print()
    print(
        f"reconcile: nonbasic_land members={len(nonbasic)}; "
        f"single-gated={len(single)}; "
        f"multi-gated={len(nonbasic) - len(single)}"
    )
    n_unknown = len(by_shape.get(SHAPE_UNKNOWN, []))
    print(f"unknown-shape (needs hand re-walk): {n_unknown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
