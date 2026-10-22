"""``mtg_bot cards`` -- card-pool data exports.

Actions::

    mtg_bot cards export-ir --pool cube --out DIR [--name powerlsv]
    mtg_bot cards roundtrip --pool cube roto eoe all

``export-ir`` writes the pool's card IR (``<name>.ir.json``) and the
schema it was encoded with (``<name>.schema.json``); see
``docs/CARD_IR.md``. ``roundtrip`` checks that every printing of each
pool decodes back to an identical object (types included) and that
re-encoding is a fixpoint; it exits 1 on any difference.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

# File stem per pool when ``--name`` is not given.
POOL_FILE_NAMES = {"cube": "powerlsv", "roto": "vintage_roto"}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mtg_bot cards",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="action", required=True)
    exp = sub.add_parser("export-ir", help="Write a pool's card IR + schema.")
    exp.add_argument("--pool", default="cube", help="cube | roto | eoe | all (default cube)")
    exp.add_argument("--out", type=Path, default=Path("."), help="Output directory.")
    exp.add_argument(
        "--name", default=None,
        help="File stem (default: powerlsv for cube, vintage_roto for roto, else the pool).",
    )
    rt = sub.add_parser("roundtrip", help="Check decode(encode(p)) == p for pools.")
    rt.add_argument("--pool", nargs="+", default=["cube", "roto", "eoe", "all"])
    return parser


def export_ir(pool: str, out: Path, name: str | None = None) -> dict:
    """Write ``<name>.ir.json`` and ``<name>.schema.json`` into ``out``;
    returns a summary."""
    from mtg_bot.cards import ir

    doc, schema = ir.build_document(pool)
    stem = name or POOL_FILE_NAMES.get(pool, pool)
    out.mkdir(parents=True, exist_ok=True)
    ir_path = out / f"{stem}.ir.json"
    schema_path = out / f"{stem}.schema.json"
    text = ir.dumps(doc)
    ir_path.write_text(text, encoding="utf-8", newline="\n")
    schema_path.write_text(
        json.dumps(schema.to_json(), sort_keys=True, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n",
    )
    data = text.encode("utf-8")
    return {
        "pool": pool,
        "cards": len(doc["cards"]),
        "classes": len(schema.classes),
        "ir_bytes": len(data),
        "ir_gzip_bytes": len(gzip.compress(data, mtime=0)),
        "schema_sha256": doc["schema_sha256"],
        "ir_path": str(ir_path),
        "schema_path": str(schema_path),
    }


def roundtrip(pools: Sequence[str]) -> list[str]:
    """Problems found (empty when every pool round-trips)."""
    from mtg_bot.cards import ir

    problems: list[str] = []
    for pool in pools:
        printings = ir.pool_printings(pool)
        doc, schema = ir.build_document(pool, printings)
        text = ir.dumps(doc)
        back = ir.decode_document(json.loads(text), schema)
        bad = sorted(n for n in printings if not ir.strict_equal(printings[n], back[n]))
        if bad:
            problems.append(f"{pool}: {len(bad)} printings differ after decode: {bad[:5]}")
        again, _ = ir.build_document(pool, back, schema)
        if ir.dumps(again) != text:
            problems.append(f"{pool}: re-encoding the decoded printings is not a fixpoint")
        print(f"{pool}: {len(printings)} cards, {len(schema.classes)} classes, "
              f"{len(text)} bytes, {'ok' if not bad else 'MISMATCH'}")
    return problems


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    if args.action == "export-ir":
        summary = export_ir(args.pool, args.out, args.name)
        print(json.dumps(summary, indent=1))
        return 0
    problems = roundtrip(args.pool)
    for p in problems:
        print(p, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
