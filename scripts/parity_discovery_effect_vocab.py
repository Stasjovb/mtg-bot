"""Dataset 1 — count distinct Python Effect class names emitted by the
OracleParserCardSource when loading every printing in the EoE pool.

Run with:
    PYTHONPATH=src \\
    ../../mtg-bot/.venv-py313/Scripts/python.exe \\
    scripts/parity_discovery_effect_vocab.py

Outputs a markdown-ish summary to stdout.
"""

from __future__ import annotations

import io
import json
import sys
import traceback
from collections import Counter, defaultdict
from dataclasses import fields, is_dataclass
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:  # pragma: no cover
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def _walk_effect(eff, *, classes, examples, parent_card_name, seen_ids):
    """Recursively walk an Effect-like object and record class names.

    We also follow nested fields that hold other Effects (sequence
    members, modal modes, conditional inners, optional wrappers, etc.).
    """
    if eff is None:
        return
    obj_id = id(eff)
    if obj_id in seen_ids:
        return
    seen_ids.add(obj_id)

    cls_name = type(eff).__name__
    classes[cls_name] += 1
    examples[cls_name].add(parent_card_name)

    # Walk dataclass fields whose values look like Effects or
    # tuples/lists of Effects. Don't import Effect here — we want to
    # work on duck-typed objects too.
    if is_dataclass(eff):
        for f in fields(eff):
            try:
                v = getattr(eff, f.name)
            except Exception:
                continue
            _maybe_walk(v, classes, examples, parent_card_name, seen_ids)
    else:
        # Some Effects might not be dataclasses; walk __dict__ defensively.
        for v in getattr(eff, "__dict__", {}).values():
            _maybe_walk(v, classes, examples, parent_card_name, seen_ids)


def _maybe_walk(v, classes, examples, parent_card_name, seen_ids):
    # Primitive types we never want to descend into.
    if v is None or isinstance(v, (str, bytes, int, float, bool, frozenset)):
        return
    # Effect-like: has resolve() method.
    if hasattr(v, "resolve") and hasattr(v, "describe"):
        _walk_effect(
            v,
            classes=classes,
            examples=examples,
            parent_card_name=parent_card_name,
            seen_ids=seen_ids,
        )
        return
    # Sequences / tuples of effects or ability dataclasses.
    if isinstance(v, (list, tuple, set)):
        for item in v:
            _maybe_walk(item, classes, examples, parent_card_name, seen_ids)
        return
    # Ability dataclasses (ActivatedAbility, TriggeredAbility,
    # StaticAbility) carry .effect or similar — duck-walk fields.
    if is_dataclass(v):
        for f in fields(v):
            try:
                inner = getattr(v, f.name)
            except Exception:
                continue
            _maybe_walk(inner, classes, examples, parent_card_name, seen_ids)


def main():
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.effect_coverage import PARITY_POOL

    src = OracleParserCardSource(pool=PARITY_POOL)
    printings = src.get_printings()

    classes: Counter[str] = Counter()
    examples: dict[str, set[str]] = defaultdict(set)
    seen_ids: set[int] = set()
    n_printings = 0
    failed: list[tuple[str, str]] = []

    for name, printing in printings.items():
        n_printings += 1
        try:
            # Walk spell_effect
            seen_ids_card: set[int] = set()
            _maybe_walk(
                printing.spell_effect,
                classes,
                examples,
                name,
                seen_ids_card,
            )
            # Triggered abilities → .effect
            for ta in printing.triggered_abilities:
                _maybe_walk(ta, classes, examples, name, seen_ids_card)
            # Activated abilities live on activated_abilities (tuple)
            for aa in getattr(printing, "activated_abilities", ()) or ():
                _maybe_walk(aa, classes, examples, name, seen_ids_card)
            # Static abilities
            for sa in getattr(printing, "static_abilities", ()) or ():
                _maybe_walk(sa, classes, examples, name, seen_ids_card)
        except Exception as e:
            failed.append((name, repr(e)))

    # Also try to load *all* the cards in the JSON pools, not just those
    # the parser claimed, so we know the raw input volume.
    pool_path = Path(__file__).resolve().parents[1] / "data" / "edge_of_eternities.json"
    with pool_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    # Figure out bespoke vs generic by module path.
    bespoke_classes: set[str] = set()
    generic_classes: set[str] = set()
    other_classes: set[str] = set()
    import mtg_bot.effects.bespoke as _bes
    import mtg_bot.effects.generic as _gen
    bespoke_names = set(dir(_bes))
    generic_names = set(dir(_gen))
    for cls in classes:
        if cls in bespoke_names and cls not in generic_names:
            bespoke_classes.add(cls)
        elif cls in generic_names and cls not in bespoke_names:
            generic_classes.add(cls)
        elif cls in generic_names and cls in bespoke_names:
            # Prefer treating as generic (re-export likely).
            generic_classes.add(cls)
        else:
            other_classes.add(cls)

    out = []
    out.append(f"## Dataset 1 — Effect vocabulary")
    out.append("")
    out.append(f"- **Raw EoE Scryfall entries**: {len(raw)}")
    out.append(f"- **Total printings claimed by parser** (across all loaded pools — eoe + stellar_sights + special_guests_eoe + duskmourn): {n_printings}")
    out.append(f"- **Failures during effect walk**: {len(failed)}")
    if failed[:10]:
        out.append("")
        out.append("### Sample failures")
        for nm, err in failed[:10]:
            out.append(f"- `{nm}` — {err}")

    total_classes = len(classes)
    ge_10 = sum(1 for n in classes.values() if n >= 10)
    one_use = sum(1 for n in classes.values() if n == 1)
    out.append("")
    out.append(f"### Cardinality")
    out.append(f"- **Total distinct Effect class names**: {total_classes}")
    out.append(f"- Classes appearing >= 10 times: **{ge_10}**")
    out.append(f"- Classes appearing in exactly 1 card: **{one_use}**")
    out.append(f"- Generic effects: **{len(generic_classes)}**, Bespoke effects: **{len(bespoke_classes)}**, Other (combinators/ability dataclasses/conditions/etc.): **{len(other_classes)}**")

    def _table(title: str, items: list[tuple[str, int]]):
        out.append("")
        out.append(f"### {title}")
        out.append("")
        out.append("| Class | Count | Example card |")
        out.append("|---|---:|---|")
        for cls, cnt in items:
            ex = sorted(examples[cls])[0] if examples[cls] else "?"
            out.append(f"| `{cls}` | {cnt} | {ex} |")

    generic_sorted = sorted(
        [(c, classes[c]) for c in generic_classes],
        key=lambda kv: (-kv[1], kv[0]),
    )
    bespoke_sorted = sorted(
        [(c, classes[c]) for c in bespoke_classes],
        key=lambda kv: (-kv[1], kv[0]),
    )
    other_sorted = sorted(
        [(c, classes[c]) for c in other_classes],
        key=lambda kv: (-kv[1], kv[0]),
    )

    _table("Generic effects (mtg_bot.effects.generic.*)", generic_sorted)
    _table("Bespoke effects (mtg_bot.effects.bespoke.*)", bespoke_sorted)
    _table("Other (combinators / ability dataclasses / conditions / etc.)", other_sorted)

    print("\n".join(out))


if __name__ == "__main__":
    main()
