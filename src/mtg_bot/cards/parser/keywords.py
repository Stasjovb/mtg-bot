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

    Scryfall's printing convention for multi-keyword lines is
    sentence-case: only the FIRST piece is capitalized, every
    subsequent piece starts lowercase (``"Flying, haste"``,
    ``"Trample, haste"``, ``"Vigilance, menace"`` etc.). We
    normalize the first letter of every piece AFTER the first to
    upper-case before the ``_KEYWORD_LINES`` lookup so the printed
    sentence-case form parses. The first piece is matched as-is
    (case-sensitive) — a lowercase single keyword like
    ``"hexproof"`` doesn't match because lowercase keyword names
    only appear mid-sentence, not as a printed keyword line.
    """
    pieces = [p.strip() for p in line.split(", ")]
    if not pieces:  # pragma: no cover - defensive; ``str.split`` always returns ≥1 piece
        return None
    normalized = [pieces[0]] + [
        p[:1].upper() + p[1:] if p else p for p in pieces[1:]
    ]
    if not all(p in _KEYWORD_LINES for p in normalized):
        return None
    return tuple(_KEYWORD_LINES[p] for p in normalized)
