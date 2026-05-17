"""Round-76 minimal-repro tracer (read-only diagnostic).

Drives ONE bench game (arch/seed from argv) via the UNMODIFIED bench
machinery, intercepts the first `_DivergenceError`, and dumps the
per-zone Python-vs-Rust field-view diff (the exact `battlefield`
tuple delta) so the residual divergence can be attributed to a
specific card / mechanic. Agent-generated diagnostic — stays under
scripts/ per the project CLAUDE.md (the round-74 tracer precedent).
No production / harness / Rust change.
"""

from __future__ import annotations

import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_REPO = _HERE.parent
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import scripts.bench_trajectory_parity as bench  # noqa: E402
from mtg_bot.parity.cross_engine import (  # noqa: E402
    build_python_field_view,
    parity_smoke,
)


def _dump_views(py_state, rust_state, tag: str) -> None:
    ps = parity_smoke()
    pv = build_python_field_view(py_state)
    rv = ps._build_field_view(rust_state)
    sys.stdout.write(f"\n===== FIELD-VIEW DIFF @ {tag} =====\n")
    keys = sorted(set(pv) | set(rv))
    for k in keys:
        a = pv.get(k)
        b = rv.get(k)
        if a != b:
            sys.stdout.write(f"\n  >>> ZONE {k} DIVERGES <<<\n")
            sys.stdout.write(f"  PY  ({k}): {a!r}\n")
            sys.stdout.write(f"  RST ({k}): {b!r}\n")
            if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
                sa, sb = set(map(repr, a)), set(map(repr, b))
                sys.stdout.write(f"  ONLY-IN-PY : {sorted(sa - sb)}\n")
                sys.stdout.write(f"  ONLY-IN-RST: {sorted(sb - sa)}\n")
        else:
            sys.stdout.write(f"  zone {k}: identical\n")


def main(argv: list[str]) -> int:
    arch = int(argv[0])
    seed = int(argv[1])
    max_turns = int(argv[2]) if len(argv) > 2 else 120

    from mtg_bot.parity import trajectory  # noqa: F401

    captured = {}

    import mtg_bot.parity.cross_engine as ce

    real_compare = ce.compare_fields

    def spy_compare(pv, rv):
        divs = real_compare(pv, rv)
        if divs and "views" not in captured:
            captured["views"] = (dict(pv), dict(rv), divs)
        return divs

    ce.compare_fields = spy_compare
    # bench imports `compare_fields` by-name at call sites inside
    # functions, so the module-attr patch is picked up.

    try:
        res = bench.drive_one_game(
            archetype=arch,
            seed=seed,
            max_turns=max_turns,
            combat_strategy="attack_all",
            mulligans=0,
        )
    finally:
        ce.compare_fields = real_compare

    sys.stdout.write(f"\nRESULT status={res.status} "
                     f"turn={res.divergence_turn} "
                     f"action={res.divergence_action_index} "
                     f"kind={res.divergence_kind} "
                     f"fields={res.divergence_fields}\n")
    if "views" in captured:
        pv, rv, divs = captured["views"]
        sys.stdout.write(f"\ncompare_fields divs = {divs}\n")
        keys = sorted(set(pv) | set(rv))
        for k in keys:
            a, b = pv.get(k), rv.get(k)
            if a != b:
                sys.stdout.write(f"\n  >>> ZONE {k} DIVERGES <<<\n")
                sys.stdout.write(f"  PY  : {a!r}\n")
                sys.stdout.write(f"  RST : {b!r}\n")
                if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
                    sa = [repr(x) for x in a]
                    sb = [repr(x) for x in b]
                    onlypy = [x for x in sa if x not in sb]
                    onlyrst = [x for x in sb if x not in sa]
                    sys.stdout.write(f"  ONLY-IN-PY : {onlypy}\n")
                    sys.stdout.write(f"  ONLY-IN-RST: {onlyrst}\n")
    else:
        sys.stdout.write("\n(no divergence captured — game PASSed?)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
