"""Parser claims Nutrient Block via graveyard-from-battlefield trigger.

Nutrient Block prints:

    Indestructible (Effects that say "destroy" don't destroy this
    artifact.)
    {2}, {T}, Sacrifice this artifact: You gain 3 life.
    When this artifact is put into a graveyard from the battlefield,
    draw a card.

The new grammar atom is the trigger phrase ``"this artifact is put
into a graveyard from the battlefield"``. Per CR 700-series the
graveyard-from-battlefield zone change is a strict subset of
LEAVES_BATTLEFIELD (the latter also fires on exile / hand / library
returns). The static-registry ``Nutrient Block`` entry already
simplifies the printed graveyard-zone trigger to LEAVES_BATTLEFIELD
with a documented "slightly looser — also fires if exiled" caveat;
the parser mirrors that simplification so per-card parity holds.

Other lines (Indestructible keyword, ``{2}, {T}, Sacrifice this
artifact: You gain 3 life.`` activated ability) all already parse via
the unified clause grammar — only the graveyard-zone-change trigger
phrase was missing.
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    ActivatedAbility,
    ActivationCost,
    DrawCards,
    GainLife,
    TriggeredAbility,
    parse_mana_cost,
)
from mtg_bot.cards.parser.artifact_builder import _build_artifact_printing
from mtg_bot.cards.parser.clause import _parse_clause
from mtg_bot.effects.predicates import Event, IsSelf


# --- Trigger-phrase level ------------------------------------------------

def test_artifact_grave_from_battlefield_trigger_parses():
    """``When this artifact is put into a graveyard from the
    battlefield, draw a card.`` parses to a single
    ``TriggeredAbility(event=LEAVES_BATTLEFIELD, predicate=IsSelf(),
    effect=DrawCards(amount=1))`` — same shape the static registry
    produces for Nutrient Block."""
    line = (
        "When this artifact is put into a graveyard from the "
        "battlefield, draw a card."
    )
    clause = _parse_clause(line)
    assert clause is not None
    assert clause.triggers == (
        TriggeredAbility(
            event=Event.LEAVES_BATTLEFIELD,
            predicate=IsSelf(),
            effect=DrawCards(amount=1),
        ),
    )


# --- Per-card builder level ----------------------------------------------

_NUTRIENT_BLOCK_CARD = {
    "name": "Nutrient Block",
    "mana_cost": "{1}",
    "type_line": "Artifact — Food",
    "oracle_text": (
        "Indestructible (Effects that say \"destroy\" don't destroy "
        "this artifact.)\n"
        "{2}, {T}, Sacrifice this artifact: You gain 3 life.\n"
        "When this artifact is put into a graveyard from the "
        "battlefield, draw a card."
    ),
}


def test_build_artifact_printing_claims_nutrient_block():
    """The Scryfall-shaped Nutrient Block record builds an Artifact
    with the indestructible keyword, the LEAVES_BATTLEFIELD trigger
    drawing a card, and the ``{2}, {T}, Sacrifice this artifact: You
    gain 3 life.`` activated ability — same shape as the static
    registry's ``make_artifact(...)``."""
    printing = _build_artifact_printing(_NUTRIENT_BLOCK_CARD)
    assert printing is not None
    assert printing.name == "Nutrient Block"
    assert printing.keywords == frozenset({"indestructible"})
    assert printing.triggered_abilities == (
        TriggeredAbility(
            event=Event.LEAVES_BATTLEFIELD,
            predicate=IsSelf(),
            effect=DrawCards(amount=1),
        ),
    )
    assert printing.activated_abilities == (
        ActivatedAbility(
            cost=ActivationCost(
                mana=parse_mana_cost("{2}"), mana_str="{2}",
                tap_self=True, sacrifice_self=True,
            ),
            effect=GainLife(amount=3),
        ),
    )


def test_parser_claims_nutrient_block_end_to_end():
    """End-to-end: ``OracleParserCardSource`` walks the cached EoE
    Scryfall data and ends up claiming Nutrient Block via the
    artifact-builder dispatch arm with the new graveyard-from-
    battlefield trigger phrase."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.cards.source import StaticCardSource
    parser = OracleParserCardSource().get_printings()
    static = StaticCardSource().get_printings()
    assert "Nutrient Block" in parser
    assert parser["Nutrient Block"] == static["Nutrient Block"]
