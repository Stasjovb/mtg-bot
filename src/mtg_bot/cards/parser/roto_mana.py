"""Parser recognizers for the Vintage Roto P3 bucket: mana, costs and
cast permissions (``docs/ROTO_COVERAGE_PLAN.md`` section 4).

Every entry point is a last-resort fallback hooked into a shared
dispatcher with a single import-and-call, so no phrase an older
recognizer claims changes meaning. Like the cube buckets, the grammar is
switched off for printings that exist only in the EoE-era dumps (the
shared ``creature_rmc_grammar`` switch), so no EoE printing's parse can
change. Engine effects live in ``effects/generic/roto_mana.py``.
"""

from __future__ import annotations

import re

from mtg_bot.effects.base import Effect


def _disabled() -> bool:
    from mtg_bot.cards.parser.creature_rmc_grammar import _DISABLED

    return _DISABLED[0]


# ---------------------------------------------------------------------------
# "Activate only if <condition>." riders
# ---------------------------------------------------------------------------

# "you control a[n] <card type>" (Spire of Industry: "Activate only if you
# control an artifact.").
_YOU_CONTROL_A_TYPE_RE = re.compile(
    r"^you control an? (?P<type>artifact|creature|enchantment|land"
    r"|planeswalker)$"
)


def parse_activate_only_if_condition(phrase: str):
    """The ``Condition`` for an ``Activate only if <phrase>.`` rider the
    base activated grammar doesn't know, or ``None``."""
    if _disabled():
        return None
    m = _YOU_CONTROL_A_TYPE_RE.match(phrase)
    if m is not None:
        from mtg_bot.effects.conditions import ControlPermanent
        from mtg_bot.effects.object_predicates import (
            IsArtifact,
            IsCreature,
            IsEnchantment,
            IsLand,
            IsPlaneswalker,
        )

        pred = {
            "artifact": IsArtifact,
            "creature": IsCreature,
            "enchantment": IsEnchantment,
            "land": IsLand,
            "planeswalker": IsPlaneswalker,
        }[m.group("type")]()
        return ControlPermanent(pred)
    return None


# ---------------------------------------------------------------------------
# Effect phrases
# ---------------------------------------------------------------------------

# "add {C} for each card named <name> in each graveyard" (Rite of Flame).
_ADD_PER_CARD_NAMED_IN_GRAVEYARDS_RE = re.compile(
    r"^add \{(?P<c>[WUBRGC])\} for each card named (?P<name>.+) in each "
    r"graveyard$"
)
# "destroy all <permanents> that entered this turn" (Force of Despair).
_DESTROY_ALL_ENTERED_THIS_TURN_RE = re.compile(
    r"^destroy all (?P<np>.+?) that entered this turn$"
)
# "add {C} for each card in target opponent's hand" (Jeska's Will).
_ADD_PER_CARD_IN_TARGET_OPPONENTS_HAND_RE = re.compile(
    r"^add \{(?P<c>[WUBRGC])\} for each card in target opponent's hand$"
)
# "add {C}{C}. This mana can't be spent to cast <kind> spells" -- a
# negative spend restriction (The Mightstone and Weakstone: nonartifact).
_ADD_MANA_CANT_BE_SPENT_ON_RE = re.compile(
    r"^add (?P<mana>(?:\{[WUBRGC]\})+)\. This mana can't be spent to cast "
    r"(?P<kind>[a-z]+) spells$"
)
# Restriction tags of ``ManaCoin.spend_restriction`` this bucket adds
# (checked by ``effects.generic.roto_mana.roto_coin_satisfies``).
_CANT_BE_SPENT_ON_KIND_TAGS = {"nonartifact": "not_nonartifact_spell"}
# Cavern of Souls' restricted, uncounterable any-color mana. A literal:
# the only card in the pools with this restriction; broader grammar
# (other "of the chosen type" spend restrictions) deferred until a second
# example exists.
_CHOSEN_CREATURE_TYPE_MANA_LINE = (
    "add one mana of any color. Spend this mana only to cast a creature "
    "spell of the chosen type, and that spell can't be countered"
)


def parse_roto_mana_effect(phrase: str) -> Effect | None:
    """Effect phrases of this bucket (the last ``_parse_effect``
    fallback)."""
    if _disabled():
        return None
    from mtg_bot.effects.generic import roto_mana as rm

    m = _ADD_PER_CARD_NAMED_IN_GRAVEYARDS_RE.match(phrase)
    if m is not None:
        from mtg_bot.effects.generic.mana import AddManaOfColorPerCount

        return AddManaOfColorPerCount(
            color=m.group("c"),
            amount=rm.CardsNamedInAllGraveyards(m.group("name")),
        )
    m = _DESTROY_ALL_ENTERED_THIS_TURN_RE.match(phrase)
    if m is not None:
        from mtg_bot.cards.parser.effects import _parse_effect

        base = _parse_effect(f"destroy all {m.group('np')}")
        if base is None or getattr(base, "action", None) != "destroy":
            return None
        from dataclasses import replace

        return replace(
            base,
            permanent_filter=base.permanent_filter & rm.EnteredThisTurn(),
            label=f"{base.label} that entered this turn",
        )
    m = _ADD_PER_CARD_IN_TARGET_OPPONENTS_HAND_RE.match(phrase)
    if m is not None:
        return rm.AddManaPerCardInTargetOpponentsHand(color=m.group("c"))
    m = _ADD_MANA_CANT_BE_SPENT_ON_RE.match(phrase)
    if m is not None:
        tag = _CANT_BE_SPENT_ON_KIND_TAGS.get(m.group("kind"))
        if tag is None:
            return None
        from mtg_bot.effects.generic.mana import AddManaToPool

        colors = re.findall(r"\{([WUBRGC])\}", m.group("mana"))
        return AddManaToPool(
            produces=tuple((c, 1) for c in colors), spend_restriction=tag,
        )
    if phrase == _CHOSEN_CREATURE_TYPE_MANA_LINE:
        return rm.AddAnyColorManaForChosenCreatureType()
    return None


# ---------------------------------------------------------------------------
# Land lines (``land_lines._try_build_line_composed_land`` hook)
# ---------------------------------------------------------------------------

_CHOOSE_CREATURE_TYPE_AS_ENTERS_RE = re.compile(
    r"^As this land enters, choose a creature type\.$"
)


def parse_roto_land_line(line: str) -> dict | None:
    """``CardPrinting`` field updates for a land line of this bucket, or
    ``None`` (the line-composed land grammar then tries its own)."""
    if _disabled():
        return None
    if _CHOOSE_CREATURE_TYPE_AS_ENTERS_RE.match(line):
        return {"enters_choosing_creature_type": True}
    return None


# ---------------------------------------------------------------------------
# Modal triggered abilities on noncreature permanents
# ---------------------------------------------------------------------------


def extract_modal_trigger_blocks(text: str, name: str):
    """Pull every ``When/Whenever <event>, choose one —`` header and its
    ``• <mode>`` lines out of a noncreature permanent's oracle ``text``
    (The Mightstone and Weakstone), parsing each block with the creature
    builder's modal-trigger grammar.

    Returns ``(remaining_text, triggers)``; ``None`` when a block is
    present but doesn't parse (the card stays unclaimed). Text without a
    block comes back unchanged with no triggers."""
    if _disabled():
        return text, ()
    from mtg_bot.cards.parser.creature_builder import (
        _MODAL_CHOOSE_ONE_SUFFIX,
        _MODAL_MODE_PREFIX,
        _parse_modal_trigger_block,
    )
    from mtg_bot.cards.parser.text import _strip_reminder_text

    lines = text.split("\n")
    kept: list[str] = []
    triggers = []
    i = 0
    while i < len(lines):
        line = _strip_reminder_text(lines[i])
        if line.endswith(_MODAL_CHOOSE_ONE_SUFFIX) and line.startswith(
            ("When ", "Whenever "),
        ):
            modes = []
            j = i + 1
            while j < len(lines) and _strip_reminder_text(lines[j]).startswith(
                _MODAL_MODE_PREFIX,
            ):
                modes.append(_strip_reminder_text(lines[j]))
                j += 1
            if modes:
                trig = _parse_modal_trigger_block(line, modes, name=name)
                if trig is None:
                    return None
                triggers.append(trig)
                i = j
                continue
        kept.append(lines[i])
        i += 1
    return "\n".join(kept), tuple(triggers)


# ---------------------------------------------------------------------------
# Spell clause rewrites (run before the spell builder splits sentences)
# ---------------------------------------------------------------------------

# "Choose one. If you control a commander as you cast this spell, you may
# choose both instead." (Jeska's Will). The engine plays two-player games
# with no commander (no player ever controls one, CR 903.3), so the
# upgrade's condition is false in every game it simulates and the header
# is exactly "Choose one —" (documented in SEARCH_LIMITATIONS).
_COMMANDER_CHOOSE_BOTH_HEADER_RE = re.compile(
    r"^Choose one\. If you control a commander as you cast this spell, you "
    r"may choose both instead\.$"
)


def rewrite_spell_clauses(clauses: list[str]) -> list[str]:
    """``clauses`` (a spell's oracle lines) with this bucket's header
    shapes rewritten to the base grammar's equivalent."""
    if _disabled():
        return clauses
    return [
        "Choose one —" if _COMMANDER_CHOOSE_BOTH_HEADER_RE.match(c) else c
        for c in clauses
    ]


__all__ = [
    "extract_modal_trigger_blocks",
    "parse_roto_land_line",
    "rewrite_spell_clauses",
    "parse_activate_only_if_condition",
    "parse_roto_mana_effect",
]
