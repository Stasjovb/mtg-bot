"""Planeswalker ``CardPrinting`` builder — oracle-text driven.

A printed planeswalker line is either a triggered ability (parsed
through the unified triggered-ability grammar) or a *loyalty-activated*
ability — a line whose printed cost is the ``[+−]?<digit(s)>:`` loyalty
prefix (Scryfall renders the negative sign as the U+2212 minus character
``−``, the positive sign as ``+``, and bare zero as ``0:``).

Loyalty-activated abilities are now modeled (the loyalty-activation
subsystem: signed-loyalty :class:`ActivationCost`, the sorcery-speed +
once-per-turn-per-walker gate, and the per-ability effects). Each
recognized loyalty line is converted to an
:class:`ActivatedAbility` with:

  * ``cost=ActivationCost(loyalty=N)`` — the signed loyalty cost. A
    printed ``+2`` ability stamps ``loyalty=-2`` (ADD); a printed
    ``-3`` ability stamps ``loyalty=3`` (PAY); ``0:`` stamps
    ``loyalty=0``. Mirrors Rust's sign convention exactly.
  * ``sorcery_speed=True`` — loyalty abilities are inherently
    sorcery-speed (CR 606.3 timing: only as a sorcery, your main phase,
    empty stack).
  * ``effect`` — the per-line effect (see ``_LOYALTY_ABILITY_EFFECTS``).

The effect body of each loyalty line is matched against a literal-line
table (``_LOYALTY_ABILITY_EFFECTS``) keyed on the printed effect text.
A loyalty line whose effect body is NOT in that table is STRIPPED (the
ability is dropped) rather than failing the whole card — see the
emblem-deferral note below.

**Deferred (HONEST-STOP): the ``-7`` emblem.** Tezzeret, Cruel
Captain's ``-7`` grants an emblem, which has no emblem-object substrate
on EITHER engine. That single line's effect body is intentionally
absent from ``_LOYALTY_ABILITY_EFFECTS``, so the ``-7`` ability is
stripped (not modeled). The ``0`` and ``-3`` abilities ARE modeled.
See docs/SEARCH_LIMITATIONS.md for the emblem-substrate map.

Any NON-loyalty line outside the supported triggered-ability grammar
still causes the whole card to fall through (returns ``None``) so the
planeswalker isn't silently shipped with a partially-parsed body.
"""

from __future__ import annotations

import re

from mtg_bot.cards.base import (
    ActivatedAbility,
    ActivationCost,
    CardPrinting,
    TriggeredAbility,
    make_planeswalker,
)
from mtg_bot.cards.parser.text import _strip_reminder_text
from mtg_bot.cards.parser.triggers import _parse_triggered_ability_line
from mtg_bot.cards.parser.type_line import _parse_type_line
from mtg_bot.effects.generic.search import SearchLibraryForCard
from mtg_bot.effects.generic.tap import (
    UntapTargetArtifactOrCreatureConditionalCounter,
)


# Loyalty-activation cost prefix on a printed planeswalker line.
# Scryfall renders the negative sign as U+2212 (``−``); ``+`` and the
# bare-zero ``0:`` form share the same regex via the optional sign
# group. Capture group 1 is the signed cost. The cost-then-colon-then-
# space pattern is anchored at the start of the line so a colon embedded
# mid-effect (e.g. inside a triggered-ability body) doesn't match.
_LOYALTY_ACTIVATION_PREFIX = re.compile(r"^([+\-−]?\d+): (.+)$")


def _printed_loyalty_to_signed_cost(printed: str) -> int:
    """Convert a printed loyalty cost token (``"+2"``, ``"-3"``, ``"0"``,
    or the U+2212 minus form ``"−7"``) into the signed
    ``ActivationCost.loyalty`` convention: a ``+N`` ability is
    ``loyalty=-N`` (ADD), a ``-N`` ability is ``loyalty=+N`` (PAY),
    ``0`` is ``loyalty=0``. Mirrors Rust's sign convention."""
    # Normalize the U+2212 minus to ASCII hyphen.
    token = printed.replace("−", "-")
    if token.startswith("+"):
        # +N ability → loyalty = -N (add-loyalty).
        return -int(token[1:])
    # "-N" or bare "0" / "N": int() handles the leading hyphen.
    # A "-N" ability → loyalty = +N (pay-loyalty); "0" → 0.
    return -int(token)


# Literal-line table of loyalty-ability effect bodies → engine Effect.
# Keyed on the printed effect text (the part AFTER the ``N:`` cost
# prefix, reminder-text stripped). A loyalty line whose effect body is
# NOT in this table is stripped (the ability dropped) — the deferral
# hook for the -7 emblem, whose effect body is deliberately absent (no
# emblem-object substrate on either engine; see module docstring +
# docs/SEARCH_LIMITATIONS.md).
#
# Today the only planeswalker in the EoE pool is Tezzeret, Cruel
# Captain, so this is a literal-line table (one card's three lines).
# When a SECOND planeswalker lands, the right move is to parameterize
# the recurring loyalty-effect shapes (untap-target, tutor-by-filter,
# emblem) into the unified ``_parse_effect_phrase`` grammar — per the
# parser CLAUDE.md "two literals → one regex" rule.
_LOYALTY_ABILITY_EFFECTS: dict[str, object] = {
    # Tezzeret, Cruel Captain's 0 ability.
    "Untap target artifact or creature. If it's an artifact creature, "
    "put a +1/+1 counter on it.":
        UntapTargetArtifactOrCreatureConditionalCounter(),
    # Tezzeret, Cruel Captain's -3 ability — tutor for an artifact card
    # with mana value 1 or less.
    "Search your library for an artifact card with mana value 1 or "
    "less, reveal it, put it into your hand, then shuffle.":
        SearchLibraryForCard(
            filter_name="artifact_small", max_mv=1, may_fail=True,
        ),
}


def _build_planeswalker_printing(card: dict) -> CardPrinting | None:
    """Parse a Scryfall planeswalker record into a ``CardPrinting`` via
    oracle-text recognition.

    Returns ``None`` if the card isn't a Planeswalker, has more than
    one printed subtype (the engine takes a single-subtype string),
    has no printed loyalty, or contains an unparseable non-loyalty
    line.
    """
    supertypes, card_types, subtypes = _parse_type_line(
        card.get("type_line", "")
    )
    if "Planeswalker" not in card_types:
        return None
    if len(subtypes) != 1:
        return None
    loyalty_str = card.get("loyalty")
    if loyalty_str is None:
        return None
    try:
        loyalty = int(loyalty_str)
    except (TypeError, ValueError):
        return None

    triggers: list[TriggeredAbility] = []
    activated: list[ActivatedAbility] = []
    for raw_line in card.get("oracle_text", "").split("\n"):
        line = _strip_reminder_text(raw_line)
        if not line:
            continue
        loyalty_match = _LOYALTY_ACTIVATION_PREFIX.match(line)
        if loyalty_match:
            cost_token, effect_body = loyalty_match.groups()
            effect = _LOYALTY_ABILITY_EFFECTS.get(effect_body)
            if effect is None:
                # Unmodeled loyalty-ability effect body (the -7 emblem) —
                # strip the ability rather than failing the whole card.
                # See module docstring + docs/SEARCH_LIMITATIONS.md.
                continue
            activated.append(
                ActivatedAbility(
                    cost=ActivationCost(
                        loyalty=_printed_loyalty_to_signed_cost(cost_token)
                    ),
                    effect=effect,  # type: ignore[arg-type]
                    sorcery_speed=True,
                )
            )
            continue
        parsed = _parse_triggered_ability_line(line, name=card["name"])
        if parsed is None:
            return None
        if isinstance(parsed, tuple):
            triggers.extend(parsed)
        else:
            triggers.append(parsed)

    return make_planeswalker(
        name=card["name"],
        cost=card.get("mana_cost", ""),
        loyalty=loyalty,
        subtype=subtypes[0],
        legendary="Legendary" in supertypes,
        triggered_abilities=tuple(triggers),
        activated_abilities=tuple(activated),
    )
