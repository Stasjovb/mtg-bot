"""Round-62 N3 scout: characterize the FULL admitted production-deck
surface across a WIDE archetype span (not just the round-58-60
shockland / Seedship / Perigee carriers the round-61 scout targeted).

Round-61 N3's sweep was deliberately scoped to the newly-admitted
post-r57 surface and found the 2-color shockland mana-ability
divergence (Agent N1 is fixing that specific Rust bug this round).
Round-62 N3's job is a BROADER sweep across the full admitted surface
to surface any *other* latent cross-engine divergence before subsystem
work resumes.

This scout walks the 17lands pool in evenly-spaced archetype-index
windows, deep-loads each through the REAL production loader
(``production_deck_to_deckspec``), and tallies the admitted feature
classes per window so the round-62 bench sweep can target a wide span
that exercises:

- vanilla / simple-trigger creatures (the keyword-only admit floor)
- the r58 ``BECOMES_TAPPED`` admits (Seedship Agrarian family)
- basics + nonbasic manabases (incl. the r60 shocklands — but NOT
  re-chasing the known r61 shockland bug; we want OTHER shapes)
- ETB / DIES / ATTACKS / landfall triggers (r36/37/48/59 leaves)

Read-only. Prints tables; writes nothing. Per the scout convention
(CLAUDE.md), throwaway ``scout_*.py`` diagnostics stay under
``scripts/``.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import io
import json
import pathlib
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:  # pragma: no cover
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _resolve_data_file(rel: pathlib.Path) -> pathlib.Path:
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


DECKS_GZ = _resolve_data_file(
    pathlib.Path("data") / "17lands" / "eoe_decks.json.gz"
)


def _load_decks() -> list[list[str]]:
    with gzip.open(DECKS_GZ, "rt", encoding="utf-8") as fh:
        data = json.load(fh)
    out = []
    for d in data:
        cl = d.get("cards") if isinstance(d, dict) else d
        out.append(list(cl) if cl else [])
    return out


def _characterize(spec) -> dict:
    """Tally the admitted feature classes of one bridged deckspec."""
    cd = list(spec.card_defs)
    creatures = [c for c in cd if getattr(c, "card_type", "") == "Creature"]
    lands = [c for c in cd if getattr(c, "card_type", "") == "Land"]
    dual_lands = [
        c
        for c in lands
        if getattr(c, "mana_produced", None)
        and len(c.mana_produced) >= 2
    ]
    kw = collections.Counter()
    trig_events = collections.Counter()
    n_trig_creatures = 0
    n_vanilla = 0
    for c in creatures:
        kws = tuple(getattr(c, "keywords", ()) or ())
        for k in kws:
            kw[k] += 1
        trigs = tuple(getattr(c, "triggered_abilities", ()) or ())
        if trigs:
            n_trig_creatures += 1
            for t in trigs:
                ev = getattr(t, "event", None) or (
                    t.get("event") if isinstance(t, dict) else None
                )
                if ev:
                    trig_events[str(ev)] += 1
        if not kws and not trigs:
            n_vanilla += 1
    return {
        "cd_total": len(cd),
        "n_creatures": len(creatures),
        "n_vanilla_creatures": n_vanilla,
        "n_trig_creatures": n_trig_creatures,
        "n_lands": len(lands),
        "n_dual_lands": len(dual_lands),
        "keywords": kw,
        "trig_events": trig_events,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--windows",
        default="0,40,80,120,160,200,300,400,600,800",
        help="Comma list of archetype-index window starts.",
    )
    ap.add_argument(
        "--window-size",
        type=int,
        default=14,
        help="Archetypes deep-loaded per window.",
    )
    args = ap.parse_args(argv)

    from mtg_bot.parity import trajectory

    decks = _load_decks()
    n_decks = len(decks)
    print(f"# 17lands pool: {n_decks} decks ({DECKS_GZ})")
    print(f"# window-size={args.window_size}")
    print()

    starts = sorted({int(x) for x in args.windows.split(",") if x.strip()})
    hdr = (
        f"{'win':>5} {'admit':>6} {'cd':>4} {'crea':>5} {'van':>4} "
        f"{'trig':>5} {'land':>5} {'dual':>5}  top_kw / top_trig_events"
    )
    print(hdr)
    print("-" * len(hdr))

    agg_kw = collections.Counter()
    agg_ev = collections.Counter()
    sweepable: list[int] = []
    feature_arches: dict[str, list[int]] = collections.defaultdict(list)

    for st in starts:
        win = list(range(st, min(st + args.window_size, n_decks)))
        for a in win:
            names = decks[a]
            if not names:
                continue
            try:
                spec = trajectory.production_deck_to_deckspec(
                    names, shared_rng_seed=0
                )
            except Exception as e:  # noqa: BLE001
                print(f"{a:>5} {'ERR':>6}  {type(e).__name__}: {str(e)[:50]}")
                continue
            ch = _characterize(spec)
            if ch["cd_total"] == 0 or ch["n_creatures"] == 0:
                # filtered to nothing playable
                continue
            sweepable.append(a)
            agg_kw.update(ch["keywords"])
            agg_ev.update(ch["trig_events"])
            if ch["n_dual_lands"]:
                feature_arches["dual_land"].append(a)
            if ch["n_trig_creatures"]:
                feature_arches["trig_creature"].append(a)
            if ch["n_vanilla_creatures"]:
                feature_arches["vanilla_creature"].append(a)
            for ev in ch["trig_events"]:
                feature_arches[f"ev:{ev}"].append(a)
            top_kw = ",".join(
                f"{k}:{v}" for k, v in ch["keywords"].most_common(3)
            )
            top_ev = ",".join(
                f"{k}:{v}" for k, v in ch["trig_events"].most_common(3)
            )
            print(
                f"{a:>5} {'YES':>6} {ch['cd_total']:>4} "
                f"{ch['n_creatures']:>5} {ch['n_vanilla_creatures']:>4} "
                f"{ch['n_trig_creatures']:>5} {ch['n_lands']:>5} "
                f"{ch['n_dual_lands']:>5}  {top_kw} / {top_ev}"
            )

    print()
    print(f"# sweepable archetypes ({len(sweepable)}): {sweepable}")
    print()
    print("# aggregate admitted keywords:")
    for k, v in agg_kw.most_common():
        print(f"  {k:<20} {v}")
    print()
    print("# aggregate admitted trigger events:")
    for k, v in agg_ev.most_common():
        print(f"  {k:<28} {v}")
    print()
    print("# feature -> carrier archetypes (for sweep grid selection):")
    for feat, archs in sorted(feature_arches.items()):
        print(f"  {feat:<22} ({len(archs):>3}) {sorted(set(archs))[:30]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
