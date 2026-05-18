"""S6 frontier classifier (throwaway diagnostic — scripts/scout_*).

Reads the committed s6_scale_verify.json, prints the full
PASS/FAIL counts, the divergence-shape histogram, and maps every
distinct shape to one of the 5 enumerated S6 frontier classes:

  A  B1-axis (ActivateAbility legal-emit-vs-apply affordability)
  B  G5-family (priority-port STATE_EQ)
  C  warp-EMISSION/S4b (warp-creature atomic resolve; battlefield/
     exile/stack OR library projections — same root cause)
  D  B1-keystone/C1 (legal_decisions==legal_actions cast set)
  E  C1-family (mana-source color selection on ActivateAbility)
  T  FAIL_TIMEOUT (degenerate land-only random walk — NOT a parity
     verdict; same class as the original C4 40/300 residual)
  X  FAIL_EXCEPTION non-frontier (loader/setup) — should be ~0

Used to assert the S6 headline is an ENUMERATED FINITE set with NO
unclassified residual (a leftover unclassified shape would be a NEW
frontier the inventory missed — surface it LOUD).
"""
from __future__ import annotations

import json
import sys


def classify(kind: str, fields: str, msg: str) -> str:
    f = fields or ""
    m = msg or ""
    if kind == "LEGAL_SET_EQ" and "cast_spell" in f:
        return "D"
    if kind == "STATE_EQ":
        if "priority_player" in f:
            return "B"
        # warp-EMISSION: a warp creature resolved atomically in Rust
        # (battlefield/exile/stack OR library/exile projections).
        if (
            "stack" in f or "exile_p0" in f or "exile_p1" in f
            or "library_p0" in f or "library_p1" in f
            or "battlefield" in f
        ):
            return "C"
        if "mana_pool" in f:
            return "E"
    return "?"


def classify_exc(msg: str) -> str:
    if "ActivateAbility" in msg and "unaffordable" in msg:
        return "A"
    return "X"


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "s6_scale_verify.json"
    data = json.load(open(path))
    games = data["games"]
    summ = data["summary"]
    print("=== S6 SCALE-VERIFY HEADLINE ===")
    for k in (
        "total_games", "passes", "fail_divergence", "fail_timeout",
        "archetype_filtered", "fail_exception",
    ):
        print(f"  {k:22s} {summ.get(k)}")
    print(f"  wall_seconds           "
          f"{summ.get('total_elapsed_seconds'):.1f}")

    buckets: dict[str, int] = {}
    unclassified: list = []
    closed_hits: list = []
    for g in games:
        st = g["status"]
        if st == "PASS":
            buckets["PASS"] = buckets.get("PASS", 0) + 1
            continue
        if st == "FAIL_TIMEOUT":
            buckets["T"] = buckets.get("T", 0) + 1
            continue
        if st == "ARCHETYPE_FILTERED":
            buckets["FILTERED"] = buckets.get("FILTERED", 0) + 1
            continue
        msg = g.get("exception_message") or ""
        # CLOSED-axis regression guard.
        if "hand_p0" in msg or "('blocker'," in msg:
            closed_hits.append((g["archetype"], g["seed"], msg[:120]))
        if st == "FAIL_EXCEPTION":
            c = classify_exc(msg)
        else:  # FAIL_DIVERGENCE
            kind = g.get("divergence_kind") or ""
            fields = ",".join(g.get("divergence_fields") or [])
            c = classify(kind, fields, msg)
        buckets[c] = buckets.get(c, 0) + 1
        if c in ("?", "X"):
            unclassified.append(
                (g["archetype"], g["seed"], g.get("divergence_kind"),
                 ",".join(g.get("divergence_fields") or []), msg[:140])
            )

    print("\n=== FRONTIER-CLASS BUCKETS ===")
    label = {
        "A": "B1-axis (ActivateAbility affordability, raw ValueError)",
        "B": "G5-family (priority-port STATE_EQ)",
        "C": "warp-EMISSION/S4b (warp-creature atomic resolve)",
        "D": "B1-keystone/C1 (legal_decisions==legal_actions cast)",
        "E": "C1-family (mana-source color on ActivateAbility)",
        "T": "FAIL_TIMEOUT (degenerate land-only walk; NOT a verdict)",
        "PASS": "PASS (divergence-clean to terminal)",
        "FILTERED": "ARCHETYPE_FILTERED",
        "X": "FAIL_EXCEPTION non-frontier (loader/setup)",
        "?": "UNCLASSIFIED (a NEW frontier — surface LOUD)",
    }
    for k in ("PASS", "A", "B", "C", "D", "E", "T", "FILTERED",
              "X", "?"):
        if k in buckets:
            print(f"  {k:8s} {buckets[k]:4d}  {label[k]}")

    print("\n=== CLOSED-AXIS REGRESSION GUARD ===")
    if closed_hits:
        print(f"  !!! {len(closed_hits)} games mention a CLOSED axis "
              f"(hand_p0 / blocker) — S5a/combat-blocker REGRESSED:")
        for a, s, m in closed_hits[:10]:
            print(f"    arch{a}/s{s}: {m}")
    else:
        print("  CLEAN — zero games mention hand_p0 or "
              "('blocker', ...). The closed axes STAY CLOSED.")

    print("\n=== UNCLASSIFIED (must be 0 for S7-readiness) ===")
    if unclassified:
        print(f"  {len(unclassified)} unclassified:")
        for row in unclassified[:20]:
            print(f"    {row}")
    else:
        print("  ZERO unclassified — the frontier set is an "
              "ENUMERATED FINITE set (the S7 gate condition).")

    print("\n=== RAW SHAPE HISTOGRAM ===")
    for shape, n in (
        summ.get("divergence_shape_histogram") or {}
    ).items():
        print(f"  {n:4d}  {shape}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
