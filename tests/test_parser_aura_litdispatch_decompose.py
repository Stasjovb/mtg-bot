"""Tests for the audit-litdispatch-auras decomposition of
``_AURA_LITERAL_TRIGGER_LINES``.

The parent audit flagged the 8-entry literal-trigger-line table on
``mtg_bot.cards.parser.enchantment_builder`` as "hidden bespoke
dispatch": each entry mapped a verbatim oracle trigger line to a
``TriggeredAbility`` rather than letting the unified
``_parse_triggered_ability_line`` grammar claim the line. Seven of
the eight entries were migrated to grammar-driven dispatch (the
trigger condition resolves through the predicate-trigger phrasebook
in ``triggers.py``; the effect body resolves through the unified
effect grammar in ``effects.py``). One entry — Chorale of the
Void's attacks-trigger reanimate — remains as a literal because the
engine doesn't yet have a generic primitive for "defending player's
graveyard" reanimation.

This file asserts:

* every migrated trigger line still parses through the unified
  ``_parse_triggered_ability_line`` path to the same
  ``TriggeredAbility`` shape the literal table previously
  produced;
* the single remaining entry (Chorale's attacks trigger) still
  routes via the literal table — its unified-grammar counterpart
  is intentionally not yet wired (architectural blocker
  documented in ``_AURA_LITERAL_TRIGGER_LINES``);
* Chorale of the Void's "Void —" end-step rider, which uses the
  "sacrifice unless" surface (not the standard intervening-if
  Void-gate surface), parses with ``requires_void=False`` because
  the void check rides the resolving effect class
  (``SacrificeSelfUnlessVoidActive``) rather than the trigger
  flag.
"""

from __future__ import annotations

import pytest

from mtg_bot.cards.base import TriggeredAbility
from mtg_bot.cards.parser.enchantment_builder import (
    _AURA_LITERAL_TRIGGER_LINES,
)
from mtg_bot.cards.parser.triggers import _parse_triggered_ability_line
from mtg_bot.effects import (
    ChoraleReanimateDefenderGraveCreatureEffect,
    DestroyEnchantedPermanent,
    EnchantedCreatureFightsTargetEffect,
    PainForAllDamageEchoEffect,
    PainForAllETBEffect,
    SacrificeSelfUnlessVoidActive,
    TargetOpponentLookHandMayDiscard,
    TargetOpponentSacrificesCreatureOtherThanEnchanted,
)
from mtg_bot.effects.predicates import (
    YOU,
    Controlled,
    Event,
    IsHost,
    IsSelf,
)


# ---------- migrated entries: parse via unified path ----------


@pytest.mark.parametrize(
    "line,expected",
    [
        # Cryoshatter / Cracked Skull / Sporogenic Infection
        # ``destroy it`` Aura DEALT_DAMAGE body.
        (
            "When enchanted creature is dealt damage, destroy it.",
            TriggeredAbility(
                event=Event.DEALT_DAMAGE,
                predicate=IsHost(),
                effect=DestroyEnchantedPermanent(),
            ),
        ),
        # Meltstrider's Resolve fight ETB.
        (
            "When this Aura enters, enchanted creature fights up to one "
            "target creature an opponent controls.",
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=EnchantedCreatureFightsTargetEffect(),
            ),
        ),
        # Pain for All ETB body.
        (
            "When this Aura enters, enchanted creature deals damage equal "
            "to its power to any other target.",
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=PainForAllETBEffect(),
            ),
        ),
        # Pain for All damage-echo body.
        (
            "Whenever enchanted creature is dealt damage, it deals that "
            "much damage to each opponent.",
            TriggeredAbility(
                event=Event.DEALT_DAMAGE,
                predicate=IsHost(),
                effect=PainForAllDamageEchoEffect(),
            ),
        ),
        # Cracked Skull look-at-hand multi-sentence body.
        (
            "When this Aura enters, look at target player's hand. "
            "You may choose a nonland card from it. "
            "That player discards that card.",
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=TargetOpponentLookHandMayDiscard(),
            ),
        ),
        # Sporogenic Infection target-opp-sacs body.
        (
            "When this Aura enters, target player sacrifices a creature "
            "of their choice other than enchanted creature.",
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=TargetOpponentSacrificesCreatureOtherThanEnchanted(),
            ),
        ),
        # Chorale's "Void — sacrifice unless" end-step rider.
        # ``requires_void=False`` here is correct: the void check
        # rides the resolving effect class itself
        # (``SacrificeSelfUnlessVoidActive``) which inverts the
        # trigger-flag semantics — the trigger fires every turn, the
        # SACRIFICE only happens when Void is inactive.
        (
            "Void — At the beginning of your end step, sacrifice this "
            "Aura unless a nonland permanent left the battlefield this "
            "turn or a spell was warped this turn.",
            TriggeredAbility(
                event=Event.BEGINNING_OF_END_STEP,
                predicate=Controlled(YOU),
                effect=SacrificeSelfUnlessVoidActive(),
                requires_void=False,
            ),
        ),
    ],
)
def test_migrated_aura_trigger_lines_parse_via_unified_path(
    line: str, expected: TriggeredAbility,
) -> None:
    """Each migrated line claims through ``_parse_triggered_ability_line``
    and produces the same ``TriggeredAbility`` shape the literal table
    previously held. The literal table no longer carries any of these
    lines."""
    assert line not in _AURA_LITERAL_TRIGGER_LINES
    parsed = _parse_triggered_ability_line(line)
    assert parsed == expected


# ---------- remaining literal entry: Chorale attacks trigger ----------


def test_chorale_attacks_trigger_remains_in_literal_table() -> None:
    """Chorale of the Void's attacks-trigger reanimate body
    (``put target creature card from defending player's graveyard
    onto the battlefield under your control tapped and attacking``)
    still routes via the literal table because the engine doesn't
    have a generic ``ReanimateFromDefendingPlayersGraveyard``
    primitive yet — it's the sole remaining entry, documented as
    an architectural blocker.
    """
    line = (
        "Whenever enchanted creature attacks, put target creature card "
        "from defending player's graveyard onto the battlefield under "
        "your control tapped and attacking."
    )
    assert line in _AURA_LITERAL_TRIGGER_LINES
    expected = TriggeredAbility(
        event=Event.ATTACKS,
        predicate=IsHost(subject="attacker"),
        effect=ChoraleReanimateDefenderGraveCreatureEffect(),
    )
    assert _AURA_LITERAL_TRIGGER_LINES[line] == expected


def test_chorale_attacks_trigger_is_not_yet_grammar_claimable() -> None:
    """The unified ``_parse_triggered_ability_line`` path returns
    ``None`` for Chorale's attacks-trigger body — by design. The
    literal-table dispatch in ``_build_aura_via_oracle_text`` claims
    the line BEFORE the grammar parser runs, so the card still lands.
    When the engine grows a ``ReanimateFromDefendingPlayersGraveyard``
    primitive (or the existing reanimate family is parameterized to
    accept that filter), the literal entry can be removed and the
    body will claim through the unified path automatically.
    """
    line = (
        "Whenever enchanted creature attacks, put target creature card "
        "from defending player's graveyard onto the battlefield under "
        "your control tapped and attacking."
    )
    assert _parse_triggered_ability_line(line) is None


def test_aura_literal_table_has_only_one_remaining_entry() -> None:
    """After the audit decomposition, the literal-trigger table
    contains exactly ONE entry (Chorale's attacks-trigger reanimate
    — see ``test_chorale_attacks_trigger_remains_in_literal_table``).
    Adding a new entry should require either a documented
    architectural blocker or a planned migration to the unified
    grammar — not a silent literal-table addition that bypasses
    the grammar.
    """
    assert len(_AURA_LITERAL_TRIGGER_LINES) == 1
