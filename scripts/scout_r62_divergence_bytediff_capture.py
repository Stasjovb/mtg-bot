"""Round-62 N3 scout: capture the PRECISE per-engine byte-diff for the
``activate_ability::mana_pool`` FAIL_DIVERGENCE games the round-62
broad bench sweep (Batch B) surfaced, to triage them definitively as
either the KNOWN round-61 shockland 2-color mana-ability shape (Rust
over-produces the land's 2nd color; Agent N1 is fixing that Rust bug
this round — must NOT be re-reported as new) OR a genuinely NEW
divergence shape (the high-value round-63 target).

Round-62 Batch B (arch 43,46,86,88,122,123,124,125,128,129,130,131,
132,160,161 x s0-3) returned 6 FAIL_DIVERGENCE, all shape
``activate_ability::mana_pool_pX``, on archetypes carrying exactly one
2-color shockland (arch 46/130 Breeding Pool G/U; arch 122/123 Watery
Grave B/U). This scout re-runs each divergent (archetype, seed) via
the bench's OWN ``drive_one_game`` (so the trajectory is bit-identical
to the sweep) and prints ``GameResult.exception_message`` — which the
bench populates with ``diff shape: <field>(py=..., rust=...)`` — so
the raw byte values can be matched against the round-61 signature:

  KNOWN r61 shape: py = (..., (<2nd-color>, 0), ...)
                   rust= (..., (<2nd-color>, 1), ...)
  i.e. Rust's pool carries a spurious extra coin of the dual land's
  SECOND color — because Rust's ``apply_mana_produced_bridge`` builds
  ONE ability adding ALL colors (Sequence) where Python builds one
  ability per color and ``activate_ability(land, 0)`` adds only the
  first.

Read-only diagnostic. Per the scout convention (CLAUDE.md) throwaway
``scout_*.py`` diagnostics stay under ``scripts/``.
"""
from __future__ import annotations

import io
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:  # pragma: no cover
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


# The 6 Batch-B FAIL_DIVERGENCE games (from tmp/bench_r62_batchB.json).
DIVERGENT = [
    (46, 0),
    (122, 0),
    (122, 1),
    (123, 0),
    (123, 1),
    (130, 0),
]


def main() -> int:
    sys.path.insert(0, "scripts")
    import bench_trajectory_parity as B
    from mtg_bot.parity import trajectory

    print("# Round-62 byte-diff capture for the 6 Batch-B "
          "activate_ability::mana_pool divergences")
    print("# (re-run via the bench's own drive_one_game — "
          "trajectory bit-identical to the sweep)")
    print()

    known_r61 = 0
    novel = 0

    for arch, seed in DIVERGENT:
        deck_names = trajectory.load_production_deck(archetype=arch)
        spec = trajectory.production_deck_to_deckspec(
            deck_names, shared_rng_seed=0
        )
        duals = sorted(
            {
                (c.name, tuple(c.mana_produced))
                for c in spec.card_defs
                if getattr(c, "card_type", "") == "Land"
                and getattr(c, "mana_produced", None)
                and len(c.mana_produced) >= 2
            }
        )
        r = B.drive_one_game(
            archetype=arch,
            seed=seed,
            max_turns=22,
            combat_strategy="attack_all",
            mulligans=0,
            verbose=False,
            activate_lander_sac=False,
        )
        print(f"## arch {arch} seed {seed}  bridged_duals={duals}")
        print(f"   status={r.status} turn={r.divergence_turn} "
              f"a-idx={r.divergence_action_index} "
              f"kind={r.divergence_kind} "
              f"fields={','.join(r.divergence_fields or ())}")
        msg = r.exception_message or ""
        print(f"   {msg}")
        verdict = _triage(msg, duals)
        print(f"   -> TRIAGE: {verdict}")
        if verdict.startswith("KNOWN-r61"):
            known_r61 += 1
        elif r.status == "FAIL_DIVERGENCE":
            novel += 1
        print()

    print("=" * 64)
    print(f"KNOWN-r61-shockland-shape divergences: {known_r61}/6")
    print(f"NOVEL (high-value, round-63 target):   {novel}/6")
    if novel == 0:
        print("VERDICT: every Batch-B divergence is the KNOWN round-61 "
              "2-color shockland mana-ability shape (Agent N1 is fixing "
              "the Rust apply_mana_produced_bridge bug this round). NOT "
              "re-reported as a new find. The broad sweep surfaced NO "
              "other latent cross-engine divergence.")
    else:
        print("VERDICT: a NON-shockland divergence shape was captured — "
              "see NOVEL rows above; that is the round-63 target.")
    return 0


def _triage(msg: str, duals) -> str:
    """Match the bench's 'diff shape: mana_pool_pX(py=..., rust=...)'
    against the r61 signature: rust pool has exactly one extra coin of
    the dual land's 2nd color."""
    if not msg or "diff shape" not in msg:
        return f"INDETERMINATE (no diff-shape message: {msg[:80]!r})"
    # Pull the first mana_pool field's py= and rust= reprs.
    m = re.search(
        r"mana_pool_p\d+\(py=(.+?), rust=(.+?)\)(?:,|\Z|$)", msg
    )
    if not m:
        return f"NOVEL/UNPARSED (msg={msg[:120]!r})"
    py_repr, ru_repr = m.group(1), m.group(2)
    py_d = _counts(py_repr)
    ru_d = _counts(ru_repr)
    if py_d is None or ru_d is None:
        return f"NOVEL/UNPARSED (py={py_repr[:60]!r} rust={ru_repr[:60]!r})"
    colors = set(py_d) | set(ru_d)
    delta = {
        c: ru_d.get(c, 0) - py_d.get(c, 0)
        for c in colors
        if ru_d.get(c, 0) != py_d.get(c, 0)
    }
    if not delta:
        return "NOVEL (mana_pool flagged but counts equal)"
    second_colors = {mp[1] for _, mp in duals if len(mp) >= 2}
    if (
        len(delta) == 1
        and list(delta.values())[0] == 1
        and list(delta.keys())[0] in second_colors
    ):
        c = list(delta.keys())[0]
        return (
            f"KNOWN-r61-shockland-shape (rust +1 '{c}' = the dual "
            f"land's 2nd color; identical to the r61 byte signature)"
        )
    return f"NOVEL (rust-py delta = {delta}; NOT the r61 +1-2nd-color shape)"


def _counts(repr_str: str):
    """Parse a tuple-of-(color,count) repr like ('B', 2),('U', 1) into
    {color: count}. Returns None if it doesn't look like that shape."""
    pairs = re.findall(r"\('([A-Z])',\s*(\d+)\)", repr_str)
    if not pairs:
        return None
    out: dict = {}
    for c, n in pairs:
        out[c] = out.get(c, 0) + int(n)
    return out


if __name__ == "__main__":
    sys.exit(main())
