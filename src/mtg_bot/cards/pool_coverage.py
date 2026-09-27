"""Parser coverage of a card pool: which cards the oracle-text parser
claims, bucketed so the modeling campaign can be prioritized.

Pure functions over raw Scryfall records + the set of claimed names;
``scripts/measure_cube_coverage.py`` renders the result to
``docs/CUBE_POOL_COVERAGE.md``.

"Claimed" is binary and honest: the parser returns ``None`` for any
card with a single unrecognized oracle line, so a claimed card is
modeled end-to-end at full oracle text (see the parser CLAUDE.md).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

PRIMARY_TYPES: tuple[str, ...] = (
    "Planeswalker", "Battle", "Creature", "Instant", "Sorcery",
    "Artifact", "Enchantment", "Land",
)

_REMINDER_RE = re.compile(r"\s*\([^)]*\)")
_NUMBER_RE = re.compile(r"\b\d+\b")
_MANA_RE = re.compile(r"\{[^}]*\}")


def primary_type(card: dict) -> str:
    """First matching primary type of the card's front face."""
    front = card.get("type_line", "").split(" // ")[0]
    for t in PRIMARY_TYPES:
        if t in front:
            return t
    return "Other"


def strip_reminder_text(line: str) -> str:
    return _REMINDER_RE.sub("", line).strip()


def oracle_lines(card: dict) -> list[str]:
    """Reminder-stripped, non-empty oracle lines across all faces."""
    texts: list[str] = []
    if card.get("card_faces"):
        for face in card["card_faces"]:
            texts.append(face.get("oracle_text", ""))
    else:
        texts.append(card.get("oracle_text", ""))
    out: list[str] = []
    for text in texts:
        for raw in text.split("\n"):
            line = strip_reminder_text(raw)
            if line:
                out.append(line)
    return out


def line_shape(line: str, card_name: str) -> str:
    """Normalize an oracle line into a coarse grammar 'shape' so the
    same template printed on many cards counts once: numbers -> N,
    mana symbols -> {M}, the card's own name -> CARDNAME."""
    s = line
    short = card_name.split(" // ")[0]
    for alias in (card_name, short, short.split(",")[0]):
        if alias:
            s = s.replace(alias, "CARDNAME")
    s = _MANA_RE.sub("{M}", s)
    s = _NUMBER_RE.sub("N", s)
    return s


@dataclass
class CoverageSummary:
    pool_name: str
    total: int
    claimed: int
    by_type: dict[str, tuple[int, int]]          # type -> (claimed, total)
    by_layout: dict[str, tuple[int, int]]        # layout -> (claimed, total)
    unclaimed_keywords: list[tuple[str, int]]
    unclaimed_shapes: list[tuple[str, int, str]]  # shape, count, example card
    unclaimed_cards: list[dict] = field(default_factory=list)
    claimed_names: list[str] = field(default_factory=list)

    @property
    def pct(self) -> float:
        return 100.0 * self.claimed / self.total if self.total else 0.0


def summarize_coverage(
    cards: Iterable[dict],
    claimed_names: Iterable[str],
    *,
    pool_name: str = "cube",
    top_keywords: int = 40,
    top_shapes: int = 60,
) -> CoverageSummary:
    cards = list(cards)
    claimed = set(claimed_names)
    by_type: dict[str, list[int]] = {}
    by_layout: dict[str, list[int]] = {}
    kw_counter: Counter[str] = Counter()
    shape_counter: Counter[str] = Counter()
    shape_example: dict[str, str] = {}
    unclaimed: list[dict] = []
    n_claimed = 0
    for card in cards:
        name = card["name"]
        is_claimed = name in claimed
        t = primary_type(card)
        layout = card.get("layout", "normal")
        by_type.setdefault(t, [0, 0])[1] += 1
        by_layout.setdefault(layout, [0, 0])[1] += 1
        if is_claimed:
            n_claimed += 1
            by_type[t][0] += 1
            by_layout[layout][0] += 1
            continue
        kw_counter.update(card.get("keywords", []))
        lines = oracle_lines(card)
        for line in lines:
            shape = line_shape(line, name)
            shape_counter[shape] += 1
            shape_example.setdefault(shape, name)
        unclaimed.append({
            "name": name,
            "type_line": card.get("type_line", ""),
            "mana_cost": card.get("mana_cost", ""),
            "layout": layout,
            "oracle_lines": lines,
        })
    shapes = [
        (shape, n, shape_example[shape])
        for shape, n in shape_counter.most_common()
        if n >= 2
    ][:top_shapes]
    return CoverageSummary(
        pool_name=pool_name,
        total=len(cards),
        claimed=n_claimed,
        by_type={k: (v[0], v[1]) for k, v in sorted(by_type.items())},
        by_layout={k: (v[0], v[1]) for k, v in sorted(by_layout.items())},
        unclaimed_keywords=kw_counter.most_common(top_keywords),
        unclaimed_shapes=shapes,
        unclaimed_cards=sorted(
            unclaimed, key=lambda c: (primary_type(c), c["name"]),
        ),
        claimed_names=sorted(claimed & {c["name"] for c in cards}),
    )


def render_markdown(
    summary: CoverageSummary,
    *,
    script_name: str = "scripts/measure_cube_coverage.py",
) -> str:
    s = summary
    lines: list[str] = []
    lines.append(
        f"Generated by `{script_name}` - DO NOT EDIT MANUALLY. "
        "Run the script to refresh."
    )
    lines.append("")
    lines.append(f"# Parser coverage of the `{s.pool_name}` card pool")
    lines.append("")
    lines.append(
        f"**{s.claimed} of {s.total} cards claimed ({s.pct:.1f}%).** "
        "A card counts as claimed only when every oracle line parses; "
        "there are no partial claims."
    )
    lines.append("")
    lines.append("## By primary type")
    lines.append("")
    lines.append("| Type | Claimed | Total | % |")
    lines.append("|---|---:|---:|---:|")
    for t, (c, n) in s.by_type.items():
        lines.append(f"| {t} | {c} | {n} | {100.0 * c / n:.0f}% |")
    lines.append("")
    lines.append("## By layout")
    lines.append("")
    lines.append("| Layout | Claimed | Total |")
    lines.append("|---|---:|---:|")
    for lay, (c, n) in s.by_layout.items():
        lines.append(f"| {lay} | {c} | {n} |")
    lines.append("")
    lines.append("## Keywords on unclaimed cards")
    lines.append("")
    lines.append(
        "Scryfall `keywords` frequency across unclaimed cards. A keyword "
        "the engine lacks blocks every card carrying it."
    )
    lines.append("")
    lines.append("| Keyword | Unclaimed cards |")
    lines.append("|---|---:|")
    for kw, n in s.unclaimed_keywords:
        lines.append(f"| {kw} | {n} |")
    lines.append("")
    lines.append("## Most common oracle-line shapes on unclaimed cards")
    lines.append("")
    lines.append(
        "Numbers -> `N`, mana symbols -> `{M}`, self-reference -> "
        "`CARDNAME`. Each shape is roughly one parameterized recognizer's "
        "worth of work (some may already parse: a card is unclaimed if "
        "*any* of its lines fails)."
    )
    lines.append("")
    lines.append("| Cards | Shape | Example |")
    lines.append("|---:|---|---|")
    for shape, n, example in s.unclaimed_shapes:
        safe = shape.replace("|", "\\|")
        lines.append(f"| {n} | {safe} | {example} |")
    lines.append("")
    lines.append("## Unclaimed cards")
    lines.append("")
    current = None
    for card in s.unclaimed_cards:
        t = primary_type(card)
        if t != current:
            current = t
            lines.append(f"### {t}")
            lines.append("")
        text = " / ".join(card["oracle_lines"]) or "(no rules text)"
        text = text.replace("|", "\\|")
        lines.append(
            f"- **{card['name']}** `{card['mana_cost']}` - "
            f"{card['type_line']} - {text}"
        )
    lines.append("")
    lines.append("## Claimed cards")
    lines.append("")
    lines.append(", ".join(s.claimed_names))
    lines.append("")
    return "\n".join(lines)
