"""Token printings created by effects (Lander, Robot, Drone, Sliver, etc.).

Tokens are never cast or drawn. They're created by resolving effects and
cease to exist when they leave the battlefield. This module keeps the
token registry separate from the main card pool.
"""

from __future__ import annotations

from mtg_bot.cards.base import *  # noqa: F401,F403
from mtg_bot.cards.base import _parse_type_line


def _make_lander_token() -> CardPrinting:
    """EoE Lander: a colorless artifact token with an activated ability.

    "{2}, Sacrifice this artifact: Search your library for a basic land
    card, put it onto the battlefield tapped, then shuffle."
    """
    type_line = "Token Artifact — Lander"
    supertypes, card_types, subtypes = _parse_type_line(type_line)
    return CardPrinting(
        name="Lander",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line=type_line,
        supertypes=supertypes,
        card_types=card_types,
        subtypes=subtypes,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{2}"),
                    mana_str="{2}",
                    sacrifice_self=True,
                ),
                effect=SearchLibraryForBasicLandTapped(),
            ),
        ),
    )


TOKEN_PRINTINGS: dict[str, CardPrinting] = {
    "Human Soldier": make_token_creature(
        "Human Soldier", 1, 1, subtypes=("Human", "Soldier")
    ),
    # 2/2 colorless Robot artifact creature — EoE's generic Robot token,
    # created by many Spacecraft ETBs and dies-triggered creatures.
    "Robot": make_token_creature(
        "Robot", 2, 2, subtypes=("Robot",), artifact=True
    ),
    # 1/1 colorless Drone artifact creature with flying. Created by
    # Pinnacle Emissary and other EoE artifact triggers. The printed
    # "can block only creatures with flying" restriction isn't
    # modeled here (block-restriction machinery would need a new
    # hook); kept as a plain flying 1/1.
    "Drone": make_token_creature(
        "Drone", 1, 1, subtypes=("Drone",), artifact=True,
        keywords=frozenset({"flying"}),
    ),
    # Lander — artifact token (not a creature) with a sacrifice-to-ramp
    # activated ability. Created by many EoE spells and triggers.
    "Lander": _make_lander_token(),
    # 1/1 colorless Sliver creature token — Thrumming Hivepool's upkeep
    # trigger.
    "Sliver": make_token_creature(
        "Sliver", 1, 1, subtypes=("Sliver",),
    ),
    # 1/1 colorless Eldrazi Scion creature token with "Sacrifice this
    # token: Add {C}." Created by Warping Wail's third mode. The sac-
    # for-{C} ability is a mana ability (bypasses the stack) just like
    # Lander's tap/sac ramp — modeled via is_mana_ability=True so the
    # spell-cast mana pipeline can consume the produced {C} before
    # passing priority.
    "Eldrazi Scion": make_token_creature(
        "Eldrazi Scion", 1, 1, subtypes=("Eldrazi", "Scion"),
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(sacrifice_self=True),
                effect=AddManaToPool(produces=(("C", 1),)),
                is_mana_ability=True,
            ),
        ),
    ),
    # Munitions: colorless artifact token created by Weapons Manufacturing.
    # "When this token leaves the battlefield, it deals 2 damage to any
    # target." Modeled via a leaves-battlefield trigger on the token.
    "Munitions": CardPrinting(
        name="Munitions",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Token Artifact — Munitions",
        supertypes=("Token",),
        card_types=("Artifact",),
        subtypes=("Munitions",),
        triggered_abilities=(
            TriggeredAbility(
                trigger="leaves_battlefield",
                effect=DealDamageAnyTarget(amount=2),
            ),
        ),
    ),
}
