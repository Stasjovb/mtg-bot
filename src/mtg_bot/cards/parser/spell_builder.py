"""Instant / sorcery ``CardPrinting`` builder.

Single-line spells are parsed straight via the unified spell-effect
phrase parser. Multi-line spells split on ``\\n`` into clauses and
combine them via one of two combinators — ``ConditionalIfVoid`` for
the Plasma-Bolt-shaped Void rider, otherwise ``Sequence`` if every
clause parses as a plain spell-effect sentence. Any unparseable
clause skips the whole spell.
"""

from __future__ import annotations

import re

from mtg_bot.cards.base import (
    CardPrinting,
    ConditionalIfVoid,
    DealDamageAnyTarget,
    Effect,
    Sequence,
    make_instant,
    make_sorcery,
)
from mtg_bot.cards.parser.effects import _parse_spell_effect_phrase
from mtg_bot.cards.parser.type_line import _parse_type_line


# Plasma-Bolt-shaped Void rider: a second clause of the form
# "Void — <Name> deals M damage instead if a nonland permanent left the
# battlefield this turn or a spell was warped this turn."
# Pairs with a preceding "<Name> deals N damage to any target." clause
# to form a ConditionalIfVoid switching the damage amount.
_SPELL_VOID_DAMAGE_REPLACEMENT = (
    r"^Void — {name} deals (\d+) damage instead "
    r"if a nonland permanent left the battlefield this turn "
    r"or a spell was warped this turn\.$"
)


def _parse_void_damage_replacement(
    phrase: str, name: str, base_effect: Effect
) -> Effect | None:
    """If ``phrase`` is a Void rider replacing the damage amount of
    ``base_effect``, return the void-branch ``Effect`` (same shape as
    base, new amount). Returns ``None`` otherwise.

    Currently only handles ``DealDamageAnyTarget`` as the base — the
    only damage shape that pairs with a Void rider in the EoE pool we
    support today (Plasma Bolt). Extend per-card as new pairings show up.
    """
    if not isinstance(base_effect, DealDamageAnyTarget):
        return None
    name_re = re.escape(name)
    m = re.match(
        _SPELL_VOID_DAMAGE_REPLACEMENT.format(name=name_re), phrase.strip()
    )
    if m is None:
        return None
    return DealDamageAnyTarget(amount=int(m.group(1)))


def _parse_spell_oracle_text(text: str, name: str) -> Effect | None:
    """Parse a spell's full oracle text into a single ``Effect``.

    Single-line: parsed by ``_parse_spell_effect_phrase`` directly.
    Multi-line: each ``\\n``-separated clause is parsed; clauses are
    combined either via ``ConditionalIfVoid`` (when the second clause
    is a Void replacement of the first damage effect) or via
    ``Sequence`` (every clause is a plain spell-effect sentence).
    Returns ``None`` if any clause fails to parse.
    """
    clauses = [c.strip() for c in text.split("\n") if c.strip()]
    if not clauses:
        return None
    if len(clauses) == 1:
        return _parse_spell_effect_phrase(clauses[0], name)
    # Two-clause Void-replacement shape (Plasma Bolt).
    if len(clauses) == 2:
        first = _parse_spell_effect_phrase(clauses[0], name)
        if first is not None:
            void_then = _parse_void_damage_replacement(
                clauses[1], name, first
            )
            if void_then is not None:
                return ConditionalIfVoid(
                    then_effect=void_then, else_effect=first
                )
    # Sequence shape: every clause must be a plain spell-effect sentence.
    parsed: list[Effect] = []
    for clause in clauses:
        eff = _parse_spell_effect_phrase(clause, name)
        if eff is None:
            return None
        parsed.append(eff)
    return Sequence(effects=tuple(parsed))


def _build_spell_printing(card: dict) -> CardPrinting | None:
    """Try to produce a ``CardPrinting`` for an instant or sorcery
    ``card`` (a Scryfall record). Returns ``None`` if the card is
    neither an instant nor a sorcery, or if its oracle text doesn't
    parse into a supported single-effect or composite shape.
    """
    supertypes, card_types, subtypes = _parse_type_line(
        card.get("type_line", "")
    )
    if "Instant" not in card_types and "Sorcery" not in card_types:
        return None
    text = card.get("oracle_text", "").strip()
    if not text:
        return None
    effect = _parse_spell_oracle_text(text, card["name"])
    if effect is None:
        return None
    factory = make_instant if "Instant" in card_types else make_sorcery
    return factory(
        name=card["name"],
        cost=card["mana_cost"],
        effect=effect,
    )
