"""Throwaway diagnostic: re-characterize the S6 Class-C population
(the 44/300 the S6 evidence labelled 'warp-EMISSION/S4b — warp
creatures resolve atomically') from the committed s6_scale_verify.json,
splitting it into the REAL sub-classes verified at HEAD 3a963e0f:

  C-warpexile : the warp-EXILE delayed-trigger-vs-deterministic-sweep
                divergence (SEARCH_LIMITATIONS.md:1790-1909 documented
                deliberate divergence) — signature: a warp creature in
                rust exile_pX + NOT on rust bf, while py has it on bf
                AND a (None,...,oid) WarpExileSelf trigger on the stack.
  C-libshuffle: library_pX same-multiset different-order (shuffle-RNG
                not lockstep) — the SEPARATE filed todo b3f7c0a9, NOT
                this lane / NOT warp-atomic.
  C-other     : anything else under the S6 'fields:*warp*creature*'
                bucket that doesn't match the two above.

Reads ONLY the committed JSON (no engine run) so it is a pure
re-characterization of the SAME evidence the brief cites.
Not a production entrypoint (scripts/scout_* convention).
"""
import json
import sys

WARP_CREATURES = (
    "Starbreach Whale", "Germinating Wurm", "Timeline Culler",
    "Knight Luminary", "Red Tiger Mechan", "Bygone Colossus",
    "Quantum Riddler",
)


def classify(g):
    msg = g.get("exception_message") or ""
    fields = " ".join(g.get("divergence_fields") or [])
    if g["status"] != "FAIL_DIVERGENCE" or g["divergence_kind"] != "STATE_EQ":
        return None
    has_warp = any(w in msg or w in fields for w in WARP_CREATURES)
    is_bf_exile_stack = (
        ("battlefield" in fields) and ("exile_p" in fields)
        and ("stack" in fields)
    )
    only_library = (
        ("library_p" in fields)
        and ("battlefield" not in fields)
        and ("exile_p" not in fields)
        and ("stack" not in fields)
    )
    if has_warp and is_bf_exile_stack:
        return "C-warpexile"
    if only_library:
        return "C-libshuffle"
    if has_warp or ("exile_p" in fields and "stack" in fields):
        return "C-other"
    return None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "s6_scale_verify.json"
    d = json.load(open(path))
    buckets = {}
    examples = {}
    for g in d["games"]:
        c = classify(g)
        if c is None:
            continue
        buckets[c] = buckets.get(c, 0) + 1
        examples.setdefault(c, []).append((g["archetype"], g["seed"]))
    total = sum(buckets.values())
    print(f"S6 Class-C re-characterization ({path}) — {total} games "
          f"in the warp/exile-stack/library bucket:")
    for c in sorted(buckets):
        ex = ", ".join(f"arch{a}/s{s}" for a, s in examples[c][:6])
        print(f"  {c:<14} {buckets[c]:>3}   e.g. {ex}")


if __name__ == "__main__":
    main()
