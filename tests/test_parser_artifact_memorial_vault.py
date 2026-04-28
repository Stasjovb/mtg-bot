"""Parser claims Memorial Vault via literal-line bespoke-effect dispatch.

Memorial Vault prints:

    {T}, Sacrifice another artifact: Exile the top X cards of your
    library, where X is one plus the mana value of the sacrificed
    artifact. You may play those cards this turn.

The cost atom ``{T}, Sacrifice another artifact`` is already a
recognized unified-grammar shape, but the effect body is a bespoke
single-card behavior (``MemorialVaultActivatedEffect`` reads X from
the most-recently-graveyarded artifact at resolution time and grants
"may play this turn" to each exiled card). Rather than push the body
into the unified ``_parse_effect`` grammar, the artifact builder's new
``_LITERAL_ACTIVATED_LINES`` table maps the full post-reminder-strip
oracle line to a factory that returns the canonical static-shape
``ActivatedAbility``.

Same "literal match for bespoke effect text" pattern Round 18 used for
Hylderblade and Robe of Stars in the equipment_builder.
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    ActivatedAbility,
    ActivationCost,
    MemorialVaultActivatedEffect,
)
from mtg_bot.cards.parser.artifact_builder import _build_artifact_printing


_MEMORIAL_VAULT_CARD = {
    "name": "Memorial Vault",
    "mana_cost": "{3}{R}",
    "type_line": "Artifact",
    "oracle_text": (
        "{T}, Sacrifice another artifact: Exile the top X cards of "
        "your library, where X is one plus the mana value of the "
        "sacrificed artifact. You may play those cards this turn."
    ),
}


def test_build_artifact_printing_claims_memorial_vault():
    """The Scryfall-shaped Memorial Vault record builds an Artifact
    with the canonical ``{T}, Sacrifice another artifact`` activation
    plus the bespoke ``MemorialVaultActivatedEffect`` payload — same
    shape as the static registry's ``make_artifact(...)``."""
    printing = _build_artifact_printing(_MEMORIAL_VAULT_CARD)
    assert printing is not None
    assert printing.name == "Memorial Vault"
    assert printing.activated_abilities == (
        ActivatedAbility(
            cost=ActivationCost(
                tap_self=True,
                sacrifice_another_artifact=True,
            ),
            effect=MemorialVaultActivatedEffect(),
        ),
    )
    # Memorial Vault has no triggered/static abilities or keywords.
    assert printing.triggered_abilities == ()
    assert printing.static_abilities == ()
    assert printing.keywords == frozenset()


def test_parser_claims_memorial_vault_end_to_end():
    """End-to-end: ``OracleParserCardSource`` walks the cached EoE
    Scryfall data and ends up claiming Memorial Vault via the
    artifact-builder dispatch arm with the new literal-line bespoke-
    effect table."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.cards.source import StaticCardSource
    parser = OracleParserCardSource().get_printings()
    static = StaticCardSource().get_printings()
    assert "Memorial Vault" in parser
    assert parser["Memorial Vault"] == static["Memorial Vault"]
