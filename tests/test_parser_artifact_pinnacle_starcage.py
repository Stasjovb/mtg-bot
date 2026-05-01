"""Parser claims Pinnacle Starcage end-to-end through the unified
clause grammar (ETB line) plus one literal-activated dispatch.

Pinnacle Starcage prints:

    When this artifact enters, exile all artifacts and creatures with
    mana value 2 or less until this artifact leaves the battlefield.
    {6}{W}{W}: Put each card exiled with this artifact into its
    owner's graveyard, then create a 2/2 colorless Robot artifact
    creature token for each card put into a graveyard this way.
    Sacrifice this artifact.

The ETB line claims through the unified clause grammar: the
``"this artifact enters"`` predicate-trigger phrase produces
``(ENTERS, IsSelf())`` and the ``_EXILE_ALL_MATCHING_UNTIL_LEAVES``
effect-phrase regex maps the body to the generic
``ExileAllMatchingUntilSourceLeaves`` engine class
(``match_artifact=True, match_creature=True, max_mv=2``).

The activation line is still literal-matched — its body is bespoke
(``PinnacleStarcageSacEffect`` encodes the put-to-graveyard-plus-
mint-Robot-tokens-plus-sacrifice behavior). The activation cost is
just the mana piece — the ``Sacrifice this artifact.`` clause is part
of the effect body, not the cost (the bespoke effect's resolve
method handles the sacrifice itself).
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    ActivatedAbility,
    ActivationCost,
    ExileAllMatchingUntilSourceLeaves,
    PinnacleStarcageSacEffect,
    TriggeredAbility,
    parse_mana_cost,
)
from mtg_bot.cards.parser.artifact_builder import _build_artifact_printing
from mtg_bot.effects.predicates import (
    Event,
    IsSelf,
)


_PINNACLE_STARCAGE_CARD = {
    "name": "Pinnacle Starcage",
    "mana_cost": "{1}{W}{W}",
    "type_line": "Artifact",
    "oracle_text": (
        "When this artifact enters, exile all artifacts and creatures "
        "with mana value 2 or less until this artifact leaves the "
        "battlefield.\n"
        "{6}{W}{W}: Put each card exiled with this artifact into its "
        "owner's graveyard, then create a 2/2 colorless Robot artifact "
        "creature token for each card put into a graveyard this way. "
        "Sacrifice this artifact."
    ),
}


def test_build_artifact_printing_claims_pinnacle_starcage():
    """The Scryfall-shaped Pinnacle Starcage record builds an Artifact
    whose ETB carries the generic ``ExileAllMatchingUntilSourceLeaves``
    engine class (replacing the deleted bespoke ``PinnacleStarcage
    ETBEffect``) and whose ``{6}{W}{W}`` activation carries the
    bespoke ``PinnacleStarcageSacEffect``."""
    printing = _build_artifact_printing(_PINNACLE_STARCAGE_CARD)
    assert printing is not None
    assert printing.name == "Pinnacle Starcage"
    assert printing.triggered_abilities == (
        TriggeredAbility(
            event=Event.ENTERS,
            predicate=IsSelf(),
            effect=ExileAllMatchingUntilSourceLeaves(
                match_artifact=True,
                match_creature=True,
                max_mv=2,
            ),
        ),
    )
    assert printing.activated_abilities == (
        ActivatedAbility(
            cost=ActivationCost(
                mana=parse_mana_cost("{6}{W}{W}"),
                mana_str="{6}{W}{W}",
            ),
            effect=PinnacleStarcageSacEffect(),
        ),
    )
    assert printing.static_abilities == ()
    assert printing.keywords == frozenset()


