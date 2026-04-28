"""Parser claims All-Fates Scroll via two-line dispatch.

All-Fates Scroll prints:

    {T}: Add one mana of any color.
    {7}, {T}, Sacrifice this artifact: Draw X cards, where X is the
    number of differently named lands you control.

Two pieces compose the claim:

  * **New effect-grammar primitive** ``add one mana of any color`` →
    ``AddManaToPool(produces=(("any", 1),))``. Lifts the first
    activation through the unified activation grammar — the activation
    layer auto-flags ``is_mana_ability=True`` because the produced
    effect is a non-targeting ``AddManaToPool`` (CR 605). Distinct
    from the bracketed ``add {<color>}`` shape: the latter mints a
    fixed-color coin known at parse time, this one defers the
    color choice to resolution.
  * **Literal-line bespoke-effect dispatch** for the second activation:
    the body ``Draw X cards, where X is the number of differently named
    lands you control.`` is wrapped in
    ``AllFatesScrollDrawEffect`` (a single-card engine class) and the
    full post-reminder-strip oracle line is matched as a literal in the
    artifact builder's ``_LITERAL_ACTIVATED_LINES`` table. Same
    "literal match for bespoke effect text" pattern Round 18 used for
    Hylderblade and Robe of Stars.

The mana ability's three-piece cost ``{7}, {T}, Sacrifice this artifact``
is otherwise a recognized unified-grammar shape; only the effect body
is bespoke.
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    ActivatedAbility,
    ActivationCost,
    AddManaToPool,
    AllFatesScrollDrawEffect,
    parse_mana_cost,
)
from mtg_bot.cards.parser.activated import _parse_activated_ability_line
from mtg_bot.cards.parser.artifact_builder import _build_artifact_printing
from mtg_bot.cards.parser.effects import _parse_effect


# --- Effect-grammar level ------------------------------------------------

def test_add_one_mana_of_any_color_effect_parses():
    """``add one mana of any color`` parses to
    ``AddManaToPool(produces=(("any", 1),))`` — same production tuple
    ``land_builder``'s Mana Confluence wiring uses for the at-resolution
    choose-color coin."""
    eff = _parse_effect("add one mana of any color")
    assert eff == AddManaToPool(produces=(("any", 1),))


# --- Activated-line level ------------------------------------------------

def test_add_one_mana_of_any_color_activation_is_mana_ability():
    """``{T}: Add one mana of any color.`` lifts to an
    ``ActivatedAbility`` with ``is_mana_ability=True`` — the activation
    layer auto-flags it because the produced ``AddManaToPool`` doesn't
    target (CR 605)."""
    ability = _parse_activated_ability_line(
        "{T}: Add one mana of any color."
    )
    assert ability is not None
    assert ability.cost == ActivationCost(tap_self=True)
    assert ability.effect == AddManaToPool(produces=(("any", 1),))
    assert ability.is_mana_ability is True


# --- Per-card builder level ----------------------------------------------

_ALL_FATES_SCROLL_CARD = {
    "name": "All-Fates Scroll",
    "mana_cost": "{3}",
    "type_line": "Artifact",
    "oracle_text": (
        "{T}: Add one mana of any color.\n"
        "{7}, {T}, Sacrifice this artifact: Draw X cards, where X is "
        "the number of differently named lands you control."
    ),
}


def test_build_artifact_printing_claims_all_fates_scroll():
    """The Scryfall-shaped All-Fates Scroll record builds an Artifact
    with two activated abilities — the unified-grammar mana ability and
    the literal-matched bespoke-effect draw activation — same shape as
    the static registry's ``make_artifact(...)``."""
    printing = _build_artifact_printing(_ALL_FATES_SCROLL_CARD)
    assert printing is not None
    assert printing.name == "All-Fates Scroll"
    assert printing.activated_abilities == (
        ActivatedAbility(
            cost=ActivationCost(tap_self=True),
            effect=AddManaToPool(produces=(("any", 1),)),
            is_mana_ability=True,
        ),
        ActivatedAbility(
            cost=ActivationCost(
                mana=parse_mana_cost("{7}"),
                mana_str="{7}",
                tap_self=True,
                sacrifice_self=True,
            ),
            effect=AllFatesScrollDrawEffect(),
        ),
    )
    assert printing.triggered_abilities == ()
    assert printing.static_abilities == ()
    assert printing.keywords == frozenset()


