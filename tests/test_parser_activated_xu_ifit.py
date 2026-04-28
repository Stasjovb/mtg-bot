"""Activated reanimate with the Xu-Ifit, Osteoharmonist Skeleton-rider.

Xu-Ifit's printed activated ability is

  ``{T}: Return target creature card from your graveyard to the
  battlefield. It's a Skeleton in addition to its other types and
  has no abilities. Activate only as a sorcery.``

The static registry intentionally drops the ``It's a Skeleton …``
rider — the engine doesn't yet model "has no abilities" suppression
nor in-place subtype grants on an arriving creature. This batch
mirrors that simplification in the parser by adding an explicit
multi-sentence regex that maps the full Xu-Ifit surface to the same
bare ``ReturnCreatureFromYourGraveyardToBattlefield`` primitive the
short-form regex produces.

Keeping the rider as its own regex (rather than a generic
preprocessing strip) makes the simplification local and explicit:
any future "raise dead" printing with a DIFFERENT rider tail will
miss the bare regex's ``$`` anchor and surface a parser miss instead
of being silently dropped.
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    ActivatedAbility,
    ActivationCost,
    ReturnCreatureFromYourGraveyardToBattlefield,
)
from mtg_bot.cards.parser.activated import _parse_activated_ability_line
from mtg_bot.cards.parser.effects import _parse_effect


def test_reanimate_with_skeleton_rider_parses():
    """Multi-sentence Xu-Ifit surface (without the trailing
    ``Activate only as a sorcery.`` rider, which the
    ``_parse_activated_ability_line`` strips before handing the
    effect phrase to the unified grammar) parses to the same bare
    reanimate primitive the static registry uses."""
    eff = _parse_effect(
        "return target creature card from your graveyard to the "
        "battlefield. It's a Skeleton in addition to its other types "
        "and has no abilities"
    )
    assert eff == ReturnCreatureFromYourGraveyardToBattlefield()


def test_reanimate_bare_form_unaffected():
    """Smoke check: the bare reanimate regex still claims the
    short-form phrase. The Xu-Ifit-specific multi-sentence regex is
    more-specific and is tried first; the bare regex below it is
    untouched."""
    eff = _parse_effect(
        "return target creature card from your graveyard to the battlefield"
    )
    assert eff == ReturnCreatureFromYourGraveyardToBattlefield()


def test_xu_ifit_activated_ability_line():
    """End-to-end shape: ``{T}: Return target creature card from your
    graveyard to the battlefield. It's a Skeleton in addition to its
    other types and has no abilities. Activate only as a sorcery.``"""
    line = (
        "{T}: Return target creature card from your graveyard to the "
        "battlefield. It's a Skeleton in addition to its other types "
        "and has no abilities. Activate only as a sorcery."
    )
    ability = _parse_activated_ability_line(line)
    assert ability == ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=ReturnCreatureFromYourGraveyardToBattlefield(),
        sorcery_speed=True,
    )


def test_parser_claims_xu_ifit():
    """Xu-Ifit, Osteoharmonist is now parser-claimed: the multi-
    sentence reanimate-as-Skeleton regex collapses to the same
    primitive the static registry uses, the inline sorcery rider
    flips ``sorcery_speed=True``, and the static's ``Human Wizard``
    subtypes were backfilled per the parser-is-right rule."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.cards.source import StaticCardSource
    parser = OracleParserCardSource().get_printings()
    static = StaticCardSource().get_printings()
    assert "Xu-Ifit, Osteoharmonist" in parser
    assert (
        parser["Xu-Ifit, Osteoharmonist"]
        == static["Xu-Ifit, Osteoharmonist"]
    )
