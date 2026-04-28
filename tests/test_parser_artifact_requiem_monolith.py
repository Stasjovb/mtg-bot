"""Parser claims Requiem Monolith via literal-line bespoke-effect dispatch.

Requiem Monolith prints:

    {T}: Until end of turn, target creature gains "Whenever this
    creature is dealt damage, you draw that many cards and lose that
    much life." That creature's controller may have this artifact deal
    1 damage to it. Activate only as a sorcery.

The printed body is two-step (grant a UEOT ``this_dealt_damage``
trigger to the target, then offer the target's controller an optional
``deal 1`` ping) and is wrapped in a bespoke
``RequiemMonolithActivatedEffect`` engine class. The full oracle line
is matched as a literal in the artifact builder's
``_LITERAL_ACTIVATED_LINES`` table, which dispatches to a factory that
returns the canonical static-shape ``ActivatedAbility(...,
sorcery_speed=True)``. Same "literal match for bespoke effect text"
pattern Round 18 used for Hylderblade and Robe of Stars.

The trailing ``Activate only as a sorcery.`` rider is part of the
literal key — the literal-line layer doesn't peel it off because the
factory hard-codes ``sorcery_speed=True``. (The unified activation
grammar's inline-rider strip path isn't reached for these literal-
matched lines.)
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    ActivatedAbility,
    ActivationCost,
    RequiemMonolithActivatedEffect,
)
from mtg_bot.cards.parser.artifact_builder import _build_artifact_printing


_REQUIEM_MONOLITH_CARD = {
    "name": "Requiem Monolith",
    "mana_cost": "{2}{B}",
    "type_line": "Artifact",
    "oracle_text": (
        "{T}: Until end of turn, target creature gains \"Whenever "
        "this creature is dealt damage, you draw that many cards and "
        "lose that much life.\" That creature's controller may have "
        "this artifact deal 1 damage to it. Activate only as a sorcery."
    ),
}


def test_build_artifact_printing_claims_requiem_monolith():
    """The Scryfall-shaped Requiem Monolith record builds an Artifact
    with the canonical ``{T}`` sorcery-speed activation whose effect is
    ``RequiemMonolithActivatedEffect`` — same shape as the static
    registry's ``make_artifact(...)``."""
    printing = _build_artifact_printing(_REQUIEM_MONOLITH_CARD)
    assert printing is not None
    assert printing.name == "Requiem Monolith"
    assert printing.activated_abilities == (
        ActivatedAbility(
            cost=ActivationCost(tap_self=True),
            effect=RequiemMonolithActivatedEffect(),
            sorcery_speed=True,
        ),
    )
    assert printing.triggered_abilities == ()
    assert printing.static_abilities == ()
    assert printing.keywords == frozenset()


def test_parser_claims_requiem_monolith_end_to_end():
    """End-to-end: ``OracleParserCardSource`` walks the cached EoE
    Scryfall data and ends up claiming Requiem Monolith via the
    artifact-builder dispatch arm with the new literal-line bespoke-
    effect table."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.cards.source import StaticCardSource
    parser = OracleParserCardSource().get_printings()
    static = StaticCardSource().get_printings()
    assert "Requiem Monolith" in parser
    assert parser["Requiem Monolith"] == static["Requiem Monolith"]
