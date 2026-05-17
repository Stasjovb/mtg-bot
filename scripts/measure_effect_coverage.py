"""Measure Rust Effect bridge coverage vs Python's Effect vocabulary.

Produces a side-by-side comparison report of:
  * the set of distinct Python ``Effect`` class names that appear when
    parsing the EoE (+ stellar_sights + special_guests_eoe + duskmourn)
    pool via ``OracleParserCardSource``;
  * the set of Rust ``Effect`` enum variant names parsed out of
    ``rust/src/cards.rs``.

Writes a markdown summary to ``docs/RUST_EFFECT_COVERAGE.md`` (auto-
overwritten on each run) AND prints the same markdown to stdout.

Run with::

    PYTHONPATH=src \\
    ../../mtg-bot/.venv-py313/Scripts/python.exe \\
    scripts/measure_effect_coverage.py

Rust → Python name mapping
--------------------------
Most Rust variants are 1:1 with Python class names by CamelCase
(e.g. ``Effect::DealDamage`` ↔ Python ``DealDamage``,
``Effect::Surveil`` ↔ Python ``Surveil``,
``Effect::DestroyAllCreatures`` ↔ Python ``DestroyAllCreatures``).

The handful of intentional name differences are listed in
``RUST_TO_PYTHON_OVERRIDES`` below — for example, the Rust bridge's
``ReturnToHand`` variant exists as a generic primitive but maps to
Python's ``ReturnTargetCreatureToOwnersHand`` /
``ReturnTargetPermanentYouControlToOwnersHand`` family, so the
override pins it to the most common Python counterpart.

This script does not depend on the Rust extension being built — it
parses ``rust/src/cards.rs`` as plain text. The companion test
``tests/test_effect_coverage.py`` does ``pytest.importorskip
("mtg_bot_engine")`` and is skipped on fresh checkouts.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

# Round-66 covered-set extraction precursor: the parser primitives +
# the Rust→Python override tables + the covered-set computation are now
# canonically defined in the production-importable
# ``mtg_bot.parity.effect_coverage`` module (so the spell-card-bridge
# Phase 1 guardrail can query the live covered set without a
# ``scripts/`` import). This script RE-EXPORTS them so its public API
# (``collect_python_effect_vocab`` / ``collect_rust_effect_variants`` /
# ``map_rust_to_python`` / ``RUST_TO_PYTHON_OVERRIDES`` /
# ``RUST_AHEAD_OF_POOL`` / ``RUST_CARDS_FILE``) is byte-for-byte
# unchanged for its existing consumers (``tests/test_effect_coverage.py``,
# ``scripts/check_audit_coverage_staleness.py``,
# ``scripts/measure_pool_parity.py``). Exactly ONE definition of
# "covered" — the §2-teeth requirement.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from mtg_bot.parity.effect_coverage import (  # noqa: E402
    RUST_AHEAD_OF_POOL,
    RUST_CARDS_FILE,
    RUST_TO_PYTHON_OVERRIDES,
    _maybe_walk,
    _walk_effect,
    collect_python_effect_vocab,
    collect_rust_effect_variants,
    map_rust_to_python,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:  # pragma: no cover
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


OUTPUT_DOC = REPO_ROOT / "docs" / "RUST_EFFECT_COVERAGE.md"

# ---------------------------------------------------------------- markdown


def render_markdown(
    py_classes: Counter,
    py_examples: dict,
    rust_variants: list[str],
    n_printings: int,
) -> str:
    py_class_set = set(py_classes.keys())
    rust_py_names: list[tuple[str, str]] = [
        (v, map_rust_to_python(v)) for v in rust_variants
    ]
    rust_py_name_set = {py for _, py in rust_py_names}

    total_emissions = sum(py_classes.values())

    # Coverage by class-count: classes whose Python name has a Rust
    # counterpart.
    covered_classes = sorted(py_class_set & rust_py_name_set)
    uncovered_classes = sorted(py_class_set - rust_py_name_set)

    # Orphan check: a Rust variant is an "orphan" iff its Python
    # counterpart name doesn't appear anywhere in the parsed pool AND
    # the variant isn't on the explicit RUST_AHEAD_OF_POOL allowlist
    # (variants the bridge built before any pool card uses them).
    # The orphan listing carries both names so the warning shows the
    # Rust side ("which variant is wrong") and the mapped Python side
    # ("what we expected to find on a card").
    rust_orphans: list[tuple[str, str]] = sorted(
        (rust_name, py)
        for rust_name, py in rust_py_names
        if py not in py_class_set and rust_name not in RUST_AHEAD_OF_POOL
    )
    ahead_of_pool = sorted(
        rust_name for rust_name in rust_variants
        if rust_name in RUST_AHEAD_OF_POOL
    )

    n_total = len(py_class_set)
    n_covered = len(covered_classes)
    pct_classes = (100.0 * n_covered / n_total) if n_total else 0.0

    # Coverage by card-emissions weight.
    covered_emissions = sum(py_classes[c] for c in covered_classes)
    pct_emissions = (
        (100.0 * covered_emissions / total_emissions) if total_emissions else 0.0
    )

    # Frequency tiers.
    high_freq = [c for c, n in py_classes.items() if n >= 10]
    mid_freq = [c for c, n in py_classes.items() if 2 <= n < 10]
    long_tail = [c for c, n in py_classes.items() if n == 1]

    high_covered = sorted(c for c in high_freq if c in rust_py_name_set)
    high_uncovered = sorted(c for c in high_freq if c not in rust_py_name_set)
    mid_covered = sum(1 for c in mid_freq if c in rust_py_name_set)
    long_covered = sum(1 for c in long_tail if c in rust_py_name_set)

    lines: list[str] = []
    lines.append(
        "Generated by `scripts/measure_effect_coverage.py` — "
        "DO NOT EDIT MANUALLY. Run the script to refresh."
    )
    lines.append("")
    lines.append("# Rust Effect bridge coverage vs Python vocab")
    lines.append("")
    lines.append(
        "This page is the rolling-progress snapshot for the Rust engine "
        "port's `Effect` enum. It compares the closed-vocabulary Rust "
        "side (variants in `rust/src/cards.rs`) against the open-ended "
        "Python side (every `Effect` subclass observed when the parser "
        "walks the EoE + stellar_sights + special_guests_eoe + "
        "duskmourn pools)."
    )
    lines.append("")
    lines.append("## Headline numbers")
    lines.append("")
    lines.append(
        f"- **{n_covered} of {n_total} Python Effect classes covered "
        f"({pct_classes:.1f}%)** — by distinct-class count."
    )
    lines.append(
        f"- **{covered_emissions} of {total_emissions} per-card "
        f"emissions covered ({pct_emissions:.1f}%)** — weighted by "
        f"how many cards each class appears on. This is the more "
        f"load-bearing metric: high-frequency classes pull the bulk "
        f"of cards into Rust even at low class-count coverage."
    )
    lines.append(
        f"- **{len(rust_variants)} Rust `Effect` variants** in "
        f"`rust/src/cards.rs` today; {n_printings} parser-claimed "
        f"printings across the loaded pools."
    )
    if rust_orphans:
        orphan_strs = ", ".join(
            f"`Effect::{r}` -> `{p}`" for r, p in rust_orphans
        )
        lines.append(
            f"- **WARNING: {len(rust_orphans)} Rust variant(s) with no "
            f"Python counterpart**: {orphan_strs}. "
            f"This indicates bridge drift — either Python emits the class "
            f"under a different name, or the Rust variant is unused. Audit "
            f"`RUST_TO_PYTHON_OVERRIDES` / `RUST_AHEAD_OF_POOL` in "
            f"`scripts/measure_effect_coverage.py`."
        )
    else:
        lines.append(
            "- **0 Rust variants without a Python counterpart** — the "
            "bridge is in sync with the Python vocabulary."
        )
    if ahead_of_pool:
        lines.append(
            f"- **{len(ahead_of_pool)} Rust variant(s) built ahead of "
            f"the pool** (allowlisted in `RUST_AHEAD_OF_POOL`): "
            f"{', '.join('`' + n + '`' for n in ahead_of_pool)}. These "
            f"have no pool card exercising them today and are NOT "
            f"counted as orphans."
        )
    lines.append("")

    lines.append("## Coverage by frequency tier")
    lines.append("")
    lines.append(
        f"Python Effect classes are split by how many cards they "
        f"appear on. The Rust port has prioritized the high-frequency "
        f"head where cards-covered-per-variant is highest."
    )
    lines.append("")

    # Tier 1: high-frequency.
    lines.append(f"### Frequency >= 10 ({len(high_freq)} classes)")
    lines.append("")
    lines.append(
        f"- Covered by Rust: **{len(high_covered)} / {len(high_freq)}** "
        f"({100.0 * len(high_covered) / max(len(high_freq), 1):.1f}%)"
    )
    lines.append("")
    lines.append("| Python class | Frequency | Rust support |")
    lines.append("|---|---:|---|")
    high_freq_sorted = sorted(high_freq, key=lambda c: (-py_classes[c], c))
    for c in high_freq_sorted:
        mark = "yes" if c in rust_py_name_set else "no"
        lines.append(f"| `{c}` | {py_classes[c]} | {mark} |")
    lines.append("")

    # Tier 2: mid-frequency.
    lines.append(f"### Frequency 2-9 ({len(mid_freq)} classes)")
    lines.append("")
    lines.append(
        f"- Covered by Rust: **{mid_covered} / {len(mid_freq)}** "
        f"({100.0 * mid_covered / max(len(mid_freq), 1):.1f}%)"
    )
    lines.append("")

    # Tier 3: long-tail.
    lines.append(f"### Frequency 1 ({len(long_tail)} singletons)")
    lines.append("")
    lines.append(
        f"- Covered by Rust: **{long_covered} / {len(long_tail)}** "
        f"({100.0 * long_covered / max(len(long_tail), 1):.1f}%)"
    )
    lines.append(
        "- The long tail is dominated by bespoke per-card classes; "
        "porting these to Rust before the generic vocabulary fills out "
        "would be poor return on investment."
    )
    lines.append("")

    # Rust variant inventory.
    lines.append("## Rust variants and their Python counterparts")
    lines.append("")
    lines.append("| # | Rust variant | Python class | Python frequency |")
    lines.append("|---:|---|---|---:|")
    for i, (rust_name, py_name) in enumerate(rust_py_names, start=1):
        freq = py_classes.get(py_name, 0)
        lines.append(f"| {i} | `Effect::{rust_name}` | `{py_name}` | {freq} |")
    lines.append("")

    # Uncovered list — abridged because it's the bulk of the work
    # ahead, and we already show the high-frequency uncovered head in
    # the tier table.
    if high_uncovered:
        lines.append("## High-frequency Python classes NOT yet in Rust")
        lines.append("")
        lines.append(
            "These are the next-best ports by cards-covered-per-variant "
            "and are the recommended top of the to-do queue:"
        )
        lines.append("")
        lines.append("| Python class | Frequency | Example card |")
        lines.append("|---|---:|---|")
        for c in sorted(high_uncovered, key=lambda c: (-py_classes[c], c)):
            ex = sorted(py_examples.get(c, set()))[0] if py_examples.get(c) else "?"
            lines.append(f"| `{c}` | {py_classes[c]} | {ex} |")
        lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- entrypoint


def main():
    py_classes, py_examples, n_printings = collect_python_effect_vocab()
    rust_variants = collect_rust_effect_variants()
    md = render_markdown(py_classes, py_examples, rust_variants, n_printings)

    OUTPUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_DOC.write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
