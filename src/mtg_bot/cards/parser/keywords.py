"""Evergreen keyword line grammar.

A keyword line is one or more evergreen keywords joined by ``", "``.
Each piece must be a recognized standalone keyword and contributes
its lowercase engine spelling to the parsed clause's ``keywords``
tuple. Adding a new evergreen keyword is a one-line addition to
``_KEYWORD_LINES``.
"""

from __future__ import annotations


_KEYWORD_LINES: dict[str, str] = {
    "Flying": "flying",
    "Trample": "trample",
    "Vigilance": "vigilance",
    "Haste": "haste",
    "Reach": "reach",
    "Deathtouch": "deathtouch",
    "Lifelink": "lifelink",
    "Defender": "defender",
    "Flash": "flash",
    "Menace": "menace",
    "Double strike": "double strike",
    "First strike": "first strike",
    "Prowess": "prowess",
    "Hexproof": "hexproof",
    "Indestructible": "indestructible",
}


def _parse_keyword_line(line: str) -> tuple[str, ...] | None:
    """Parse a (possibly comma-separated) keyword-only line.

    A single keyword like ``"Flying"`` returns ``("flying",)``. A
    multi-keyword line like ``"Flash, Flying"`` returns
    ``("flash", "flying")``. Returns ``None`` if any piece is not a
    recognized keyword — the caller may then try other clause
    patterns (e.g. triggered abilities).
    """
    pieces = [p.strip() for p in line.split(", ")]
    if not all(p in _KEYWORD_LINES for p in pieces):
        return None
    return tuple(_KEYWORD_LINES[p] for p in pieces)
