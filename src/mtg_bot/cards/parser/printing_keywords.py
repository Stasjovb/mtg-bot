"""Printing-level parametric keywords (Warp, Ward, Devour, Impending).

These take a numeric/mana-cost argument so they don't fit the
literal-line ``_KEYWORD_LINES`` map in ``keywords.py``. They share
the same shape: a keyword name followed by its argument on its own
line, with optional parenthesized reminder text. The argument
round-trips into the ``make_creature`` ``warp=`` / ``ward=`` /
``devour_land_multiplier=`` / ``impending=``+``impending_count=``
kwarg.

Two ``Ward`` non-mana-cost rider shapes are also recognized: the
em-dash discard-cost variants ``Ward—Discard a card.`` and
``Ward—Discard a card at random.`` (Sunset Saboteur and Alpharael
Stonechosen respectively). Each produces a sentinel return value
that the creature builder maps to the matching
``ward_discard_chosen=True`` / ``ward_discard_random=True`` kwarg
on ``make_creature``. Other riders (``Warp—{B}, Pay 2 life.``
additional-life-cost variants etc.) remain out of scope — they
intentionally don't match and cause the enclosing card to be
skipped.
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


# ``Ward—Discard a card.`` / ``Ward—Discard a card at random.`` —
# em-dash discard-cost ward riders. Scryfall prints both variants
# verbatim with no surrounding reminder text. The two variants are
# distinguished only by the trailing ``at random`` qualifier; the
# function below returns a tagged string (``"chosen"`` or
# ``"random"``) so the creature builder can map it to the matching
# ``make_creature`` boolean kwarg without re-parsing.
_WARD_DISCARD_LINE = re.compile(
    r"^Ward—Discard a card(?P<random> at random)?\.$"
)


def _parse_ward_discard_line(line: str) -> str | None:
    """Return ``"chosen"`` for ``Ward—Discard a card.``, ``"random"``
    for ``Ward—Discard a card at random.``, or ``None`` if the line
    doesn't match either em-dash discard-cost ward shape.

    Two variants only — Scryfall consistently prints these exact
    surface forms; any other discard-cost ward (a future ``Ward—
    Discard two cards.`` printing, say) would land its own entry
    rather than parameterizing this one. Keeping the surface→tag
    mapping 1:1 with the engine's ``ward_discard_chosen`` /
    ``ward_discard_random`` boolean fields preserves parser/static
    parity by construction.
    """
    m = _WARD_DISCARD_LINE.match(line.strip())
    if m is None:
        return None
    return "random" if m.group("random") else "chosen"


_IMPENDING_LINE = re.compile(
    # Impending N—{cost}. Scryfall uses an em-dash (U+2014). The
    # reminder text is stripped per-line by ``_strip_reminder_text``
    # before this lookup runs, so we match the bare keyword line.
    r"^Impending (\d+)—(\{[^}]+\}(?:\{[^}]+\})*)$"
)


def _parse_impending_line(line: str) -> tuple[int, str] | None:
    """Return ``(N, cost_str)`` if ``line`` is an Impending clause
    (``Impending N—{cost}``), else ``None``.

    Matches the verbatim Duskmourn Overlord cycle surface form. The
    reminder text — "(If you cast this spell for its impending cost,
    it enters with N time counters and isn't a creature until the
    last is removed. At the beginning of your end step, remove a
    time counter from it.)" — is stripped via the existing per-line
    reminder-text stripper before this lookup runs, so we only have
    to match the bare keyword line.
    """
    m = _IMPENDING_LINE.match(line.strip())
    if m is None:
        return None
    return int(m.group(1)), m.group(2)


_DEVOUR_LINE = re.compile(
    r"^Devour land (\d+)(?: \([^)]*\))?$"
)


def _parse_devour_line(line: str) -> int | None:
    """Return the devour multiplier ``N`` (an int) if ``line`` is a
    simple ``Devour land N`` clause, else ``None``. The EoE printing
    is Famished Worldsire's ``Devour land 3`` (sacrifice any number of
    lands; enter with three times that many +1/+1 counters). Lines
    with riders or non-``land`` Devour variants intentionally don't
    match — the enclosing card falls through and is skipped.
    """
    m = _DEVOUR_LINE.match(line.strip())
    if m is None:
        return None
    return int(m.group(1))


# ``This creature enters tapped.`` — printing-level static replacement
# (CR 614) flipping the existing ``enters_tapped: bool`` field on the
# card printing. The engine already consults this field at ETB time
# (``actions.put_into_battlefield`` and ``effects/combinators.py``);
# the parser side has been missing the line recognizer. Surfaces on
# Piranha Fly's two-line oracle text alongside Flying.
#
# A literal-string match is sufficient — no card today varies the
# wording. A future printing whose surface text differs (``This
# permanent enters tapped`` for a non-creature, or a numeric variant)
# would land its own entry rather than parameterizing this one,
# matching the ``Ward—Discard`` precedent above where each surface
# gets its own 1:1 recognizer.
_ENTERS_TAPPED_LINE = "This creature enters tapped."


def _parse_enters_tapped_line(line: str) -> bool:
    """Return ``True`` if ``line`` is the printing-level ``This creature
    enters tapped.`` clause, else ``False``. Used by
    ``creature_builder._build_creature_printing`` to flip the
    ``enters_tapped`` kwarg on ``make_creature`` directly — distinct
    from the triggered-ability path because the ETB-tapped behavior is
    a static replacement effect, not an event-firing trigger.
    """
    return line.strip() == _ENTERS_TAPPED_LINE


# ``This creature must be blocked if able.`` — printing-level static
# block-requirement (CR 509.1c). Surfaces on Fear of Being Hunted
# alongside Haste. The matching engine flag
# (``CardPrinting.must_be_blocked_if_able``) is consumed by
# ``actions._declare_blockers``: if no validated blocker is assigned
# to the attacker and at least one eligible defender exists that
# could legally block it, the engine forces one. A literal-string
# match is sufficient; future related surfaces (``This creature can't
# be blocked except by …``) would land their own recognizers.
_MUST_BE_BLOCKED_LINE = "This creature must be blocked if able."


def _parse_must_be_blocked_line(line: str) -> bool:
    """Return ``True`` if ``line`` is the printing-level ``This creature
    must be blocked if able.`` clause, else ``False``. Used by
    ``creature_builder._build_creature_printing`` to flip the
    ``must_be_blocked_if_able`` kwarg on ``make_creature``.
    """
    return line.strip() == _MUST_BE_BLOCKED_LINE
