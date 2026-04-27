"""Printing-level parametric keywords (Warp, Ward).

These take a mana-cost argument so they don't fit the literal-line
``_KEYWORD_LINES`` map in ``keywords.py``. Both share the same shape:
a keyword name followed by a mana cost on its own line, with optional
parenthesized reminder text. The cost string round-trips into the
``make_creature`` ``warp=`` / ``ward=`` kwarg.

Riders (``Warp—{B}, Pay 2 life.`` em-dash variants, ``Ward — Discard
a card.`` etc.) are out of scope — they intentionally don't match
and cause the enclosing card to be skipped.
"""

from __future__ import annotations

import re


_WARP_LINE = re.compile(
    r"^Warp (\{[^}]+\}(?:\{[^}]+\})*)(?: \([^)]*\))?$"
)


def _parse_warp_line(line: str) -> str | None:
    """Return the warp cost string (e.g. ``"{1}{R}"``) if ``line`` is a
    simple Warp clause, else ``None``. Lines with riders (additional
    life cost, graveyard-castable, etc.) intentionally don't match.
    """
    m = _WARP_LINE.match(line.strip())
    if m is None:
        return None
    return m.group(1)


_WARD_LINE = re.compile(
    r"^Ward (\{[^}]+\}(?:\{[^}]+\})*)(?: \([^)]*\))?$"
)


def _parse_ward_line(line: str) -> str | None:
    """Return the ward cost string (e.g. ``"{2}"``) if ``line`` is a
    simple ``Ward {cost}`` clause, else ``None``. Lines with riders
    (em-dash + life cost, em-dash + discard) intentionally don't match.
    """
    m = _WARD_LINE.match(line.strip())
    if m is None:
        return None
    return m.group(1)
