"""Parser claims Pinnacle Starcage via two literal-line dispatches.

Pinnacle Starcage prints:

    When this artifact enters, exile all artifacts and creatures with
    mana value 2 or less until this artifact leaves the battlefield.
    {6}{W}{W}: Put each card exiled with this artifact into its
    owner's graveyard, then create a 2/2 colorless Robot artifact
    creature token for each card put into a graveyard this way.
    Sacrifice this artifact.

Both lines fall outside the unified ``_parse_clause`` grammar — both
bodies are wrapped in single-card bespoke engine classes
(``PinnacleStarcageETBEffect`` encodes the exile-AND-return-on-leave
behavior, ``PinnacleStarcageSacEffect`` encodes the put-to-graveyard-
plus-mint-Robot-tokens-plus-sacrifice behavior).

Two literal-line entries claim the printing:

  * The ETB line is added to ``_LITERAL_TRIGGER_LINES`` (returning a
    1-tuple of ``TriggeredAbility(event=ENTERS, predicate=IsSelf(),
    effect=PinnacleStarcageETBEffect())``).
  * The activation line is added to ``_LITERAL_ACTIVATED_LINES``
    (returning ``ActivatedAbility(cost=ActivationCost(mana=...,
    mana_str="{6}{W}{W}"), effect=PinnacleStarcageSacEffect())``).

The activation cost is just the mana piece — the ``Sacrifice this
artifact.`` clause is part of the effect body, not the cost (the
bespoke effect's resolve method handles the sacrifice itself). This
matches the static registry's ``ActivationCost(mana=..., mana_str=...)``
without ``sacrifice_self``.
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    ActivatedAbility,
    ActivationCost,
    PinnacleStarcageETBEffect,
    PinnacleStarcageSacEffect,
    TriggeredAbility,
    parse_mana_cost,
)
from mtg_bot.cards.parser.artifact_builder import _build_artifact_printing
from mtg_bot.effects.predicates import Event, IsSelf


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
    with the bespoke ETB exile trigger plus the bespoke ``{6}{W}{W}``
    sacrifice activation — same shape as the static registry's
    ``make_artifact(...)``."""
    printing = _build_artifact_printing(_PINNACLE_STARCAGE_CARD)
    assert printing is not None
    assert printing.name == "Pinnacle Starcage"
    assert printing.triggered_abilities == (
        TriggeredAbility(
            event=Event.ENTERS,
            predicate=IsSelf(),
            effect=PinnacleStarcageETBEffect(),
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


