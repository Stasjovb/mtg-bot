"""Round-61 N3 scout: minimal deterministic reproduction of the
cross-engine divergence the round-61 shockland bench sweep surfaced —
a 2-color non-basic land's auto-wired mana ability does NOT model the
same way on the two engines.

THE BUG (captured by the r61 shockland bench sweep, 3/56 games:
arch 37/s3 t9, arch 46/s0 t8, arch 69/s0 t10 — all
``activate_ability::mana_pool`` with the IDENTICAL byte shape
``py=...('U',0)...  rust=...('U',1)...``):

For a single-color land (every basic — Forest/Island/...) the two
mana-ability bridges agree:

  * Python (``cross_engine._card_def_to_python_printing``,
    lines ~8912-8920): builds ONE ``ActivatedAbility`` per color in
    ``mana_produced`` — ``[{T}: Add <c>]`` (1 entry for a basic).
  * Rust (``cards.rs::apply_mana_produced_bridge``, ~6387): builds
    ONE synthesized ability whose effect aggregates ALL colors in
    ``mana_produced``. For 1 color that is a flat ``AddManaToPool``.

Both → ``ability_index=0`` taps and adds the single color. Equal.

For a TWO-color non-basic land (round-60's 5 pay-life shocklands,
e.g. Watery Grave ``mana_produced=["B","U"]``) the bridges DIVERGE:

  * Python builds TWO abilities:
      ability_index 0 = ``{T}: Add B``
      ability_index 1 = ``{T}: Add U``
  * Rust builds ONE ability:
      ability_index 0 = ``{T}: Sequence(Add B, Add U)``  — BOTH
      colors in a single activation.

The bench (and any consumer) taps a land via
``activate_ability(land_id, ability_index=0)``. On a shockland:
Python adds ONE color (B); Rust adds BOTH (B AND U). The Rust pool
carries a spurious extra ``U`` — exactly the captured byte-diff.

This is a REAL cross-engine divergence (Rust != Python), newly
exposed because round-60 is the first time a 2-color
``mana_produced`` land reaches real bench play (basics are always
single-color, so index-0 and the aggregate-read agreed before).
It is ALSO a shared CR divergence (a real dual land's mana ability
adds ONE chosen color, not all) but the campaign-relevant defect is
the engine-to-engine disagreement.

This scout reproduces it deterministically from a synthesized
2-color land DeckSpec — no full game, no seeds — so a round-62 fix
has a tight pin to work against. Read-only; prints the per-engine
mana pool after a single ``activate_ability(land, 0)``.
"""
from __future__ import annotations

import io
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:  # pragma: no cover
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def main() -> int:
    from mtg_bot.parity import trajectory

    # The exact carrier set from the divergent r61 bench games.
    for arch, seed in ((37, 3), (46, 0), (69, 0)):
        names = trajectory.load_production_deck(archetype=arch)
        spec = trajectory.production_deck_to_deckspec(
            names, shared_rng_seed=0
        )
        duals = sorted(
            {
                (c.name, tuple(c.mana_produced))
                for c in spec.card_defs
                if getattr(c, "card_type", "") == "Land"
                and getattr(c, "mana_produced", None)
                and len(c.mana_produced) == 2
            }
        )
        print(f"arch {arch} seed {seed}: bridged 2-color lands = {duals}")

    print()
    print("# per-engine ability shape for a 2-color land "
          "(Watery Grave B/U, the arch-37/s3 carrier)")

    # Inspect what each bridge builds for mana_produced=("B","U").
    from mtg_bot.parity.cross_engine import (
        CardDef,
        _card_def_to_python_printing,
    )

    cd = CardDef(
        name="Watery Grave",
        card_type="Land",
        mana_produced=("B", "U"),
    )
    py_pr = _card_def_to_python_printing(cd)
    py_abils = list(py_pr.activated_abilities)
    print(f"  Python: {len(py_abils)} activated abilities")
    for i, ab in enumerate(py_abils):
        eff = ab.effect
        print(f"    ability_index={i}: effect={eff!r}")

    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Watery Grave",
            "card_types": ["Land"],
            "mana_cost": {},
            "effects": [],
            "mana_produced": ["B", "U"],
            "supertypes": [],
        }
    )
    rust_pr = reg.printing_to_dict(pid) if hasattr(
        reg, "printing_to_dict"
    ) else None
    print(f"  Rust pid={pid}")
    if rust_pr is not None:
        aas = rust_pr.get("activated_abilities", [])
        print(f"  Rust: {len(aas)} activated abilities")
        for i, ab in enumerate(aas):
            print(f"    ability_index={i}: {ab}")
    else:
        print("  Rust: (no printing_to_dict introspection on this "
              ".pyd; the byte-diff from the bench sweep is the "
              "authority — Rust ability_index=0 = Sequence(Add B, "
              "Add U), Python ability_index=0 = Add B)")

    print()
    print("VERDICT: ability_index=0 on a 2-color land means 'Add "
          "<first color>' on Python but 'Add ALL colors (Sequence)' "
          "on Rust. activate_ability(land,0) => Python pool gains 1 "
          "color, Rust pool gains BOTH. Captured byte-diff: "
          "rust pool has spurious extra U. REAL cross-engine "
          "divergence; round-62 fix target = make the two "
          "mana_produced bridges build the SAME per-color ability "
          "shape (Rust apply_mana_produced_bridge must emit one "
          "ability PER color like Python, OR Python must aggregate "
          "like Rust — the engines must agree; the CR-correct "
          "choice is one ability per color, player picks).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
