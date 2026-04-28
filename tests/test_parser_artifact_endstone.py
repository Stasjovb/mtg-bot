"""Parser claims The Endstone via literal-trigger-line dispatch.

The Endstone is a Legendary Artifact whose oracle text is two trigger
lines:

    Whenever you play a land or cast a spell, draw a card.
    At the beginning of your end step, your life total becomes half
    your starting life total, rounded up.

Both lines fall outside the unified ``_parse_clause`` grammar:

  * The first is a composite trigger — two events (``play a land`` /
    ``cast a spell``) joined by ``or`` — that the static registry
    splits into two ``TriggeredAbility`` primitives (one per event).
    The legacy fused ``cast_spell_or_play_land`` trigger key is not
    introduced here; predicate vocabulary stays primitive (one event
    per ability).
  * The second carries a bespoke ``SetLifeToHalfStartingRoundedUp``
    effect class — the body ("your life total becomes half your
    starting life total, rounded up") isn't a unified-grammar
    primitive.

Round 20 grows a sister table to ``_LITERAL_ACTIVATED_LINES`` —
``_LITERAL_TRIGGER_LINES`` — that maps the full post-reminder-strip
oracle line to a factory returning a tuple of ``TriggeredAbility``
(one or more arms, mirroring the per-arm fan-out shape Cryogen Relic's
compound enters-or-leaves trigger uses). Same "literal match for
bespoke effect text" pattern Round 18 used for Hylderblade and Robe
of Stars in the equipment_builder, just on the trigger side.

The Legendary supertype rides through ``make_artifact(legendary=True)``
the builder already wires off the parsed type-line.
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    DrawCards,
    SetLifeToHalfStartingRoundedUp,
    TriggeredAbility,
)
from mtg_bot.cards.parser.artifact_builder import _build_artifact_printing
from mtg_bot.effects.predicates import Controlled, Event, YOU


_ENDSTONE_CARD = {
    "name": "The Endstone",
    "mana_cost": "{7}",
    "type_line": "Legendary Artifact",
    "oracle_text": (
        "Whenever you play a land or cast a spell, draw a card.\n"
        "At the beginning of your end step, your life total becomes "
        "half your starting life total, rounded up."
    ),
}


def test_build_artifact_printing_claims_the_endstone():
    """The Scryfall-shaped Endstone record builds a Legendary Artifact
    with three ``TriggeredAbility`` entries — IS_CAST + PLAYS_LAND for
    the composite first line (per-arm fan-out), and BEGINNING_OF_END_STEP
    for the bespoke ``SetLifeToHalfStartingRoundedUp`` body — same shape
    the static registry's ``make_artifact(legendary=True, ...)``
    produces."""
    printing = _build_artifact_printing(_ENDSTONE_CARD)
    assert printing is not None
    assert printing.name == "The Endstone"
    assert printing.is_legendary is True
    assert printing.triggered_abilities == (
        TriggeredAbility(
            event=Event.IS_CAST,
            predicate=Controlled(YOU, subject="controller"),
            effect=DrawCards(amount=1),
        ),
        TriggeredAbility(
            event=Event.PLAYS_LAND,
            predicate=Controlled(YOU, subject="controller"),
            effect=DrawCards(amount=1),
        ),
        TriggeredAbility(
            event=Event.BEGINNING_OF_END_STEP,
            predicate=Controlled(YOU),
            effect=SetLifeToHalfStartingRoundedUp(),
        ),
    )
    assert printing.activated_abilities == ()
    assert printing.static_abilities == ()
    assert printing.keywords == frozenset()


def test_parser_claims_the_endstone_end_to_end():
    """End-to-end: ``OracleParserCardSource`` walks the cached EoE
    Scryfall data and ends up claiming The Endstone via the artifact-
    builder dispatch arm with the new literal-trigger-line table."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.cards.source import StaticCardSource
    parser = OracleParserCardSource().get_printings()
    static = StaticCardSource().get_printings()
    assert "The Endstone" in parser
    assert parser["The Endstone"] == static["The Endstone"]
