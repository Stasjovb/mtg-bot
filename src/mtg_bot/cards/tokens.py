"""Token printings created by effects (Lander, Robot, Drone, Sliver, etc.).

Tokens are never cast or drawn. They're created by resolving effects and
cease to exist when they leave the battlefield. This module keeps the
token registry separate from the main card pool.
"""

from __future__ import annotations

from mtg_bot.cards.base import *  # noqa: F401,F403
from mtg_bot.cards.base import _parse_type_line
from mtg_bot.effects.predicates import Event, IsSelf


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
    # 1/1 colorless Drone artifact creature with flying and "this
    # token can block only creatures with flying." Created by Pinnacle
    # Emissary, Station Monitor, and other EoE artifact triggers. The
    # block-restriction is enforced via
    # CardPrinting.can_only_block_creatures_with_flying, which
    # combat.can_block consults when the blocker is a Drone.
    "Drone": make_token_creature(
        "Drone", 1, 1, subtypes=("Drone",), artifact=True,
        keywords=frozenset({"flying"}),
        can_only_block_creatures_with_flying=True,
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
    # 2/1 white Insect creature token with flying — the Mistmoors
    # Overlord (Duskmourn) creates two of these whenever it enters
    # or attacks. Color isn't tracked through tokens (the engine
    # derives color from mana_cost.colors() and tokens have an
    # empty mana cost), so this surfaces as a colorless 2/1 Insect
    # with flying — a simplification that matches how every other
    # color-bearing token is shipped today (no token printing
    # carries an explicit color tag yet).
    "Insect": make_token_creature(
        "Insect", 2, 1, subtypes=("Insect",),
        keywords=frozenset({"flying"}),
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
                event=Event.LEAVES_BATTLEFIELD, predicate=IsSelf(),
                effect=DealDamageAnyTarget(amount=2),
            ),
        ),
    ),
    # Treasure: the standard evergreen colorless artifact token. Single
    # activated ability: "{T}, Sacrifice this token: Add one mana of
    # any color." The mana ability is flagged ``is_mana_ability=True``
    # so the engine bypasses the stack at activation per CR 605 — the
    # same pattern Lander and Eldrazi Scion use for their
    # sac-for-mana abilities. Modeled identically to the in-print
    # printing on Scryfall: an artifact (no creature type), no P/T,
    # no flavor text, exactly one ability.
    "Treasure": CardPrinting(
        name="Treasure",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Token Artifact — Treasure",
        supertypes=("Token",),
        card_types=("Artifact",),
        subtypes=("Treasure",),
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    tap_self=True,
                    sacrifice_self=True,
                ),
                effect=AddManaToPool(produces=(("any", 1),)),
                is_mana_ability=True,
            ),
        ),
    ),
    # Glimmer: 1/1 white Glimmer enchantment creature token. Created
    # by Tunnel Surveyor's ETB (and other Duskmourn cards that
    # interact with the Glimmer subtype). The first
    # enchantment-creature token in the EoE/Duskmourn pool — both
    # ``Enchantment`` and ``Creature`` appear in ``card_types``,
    # mirroring the printed type line. The token has no abilities and
    # no flavor text; it's a vanilla 1/1 with the dual card type so
    # enchantment-targeting effects can interact with it the same way
    # they would with a non-token enchantment creature.
    "Glimmer": CardPrinting(
        name="Glimmer",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Token Enchantment Creature — Glimmer",
        supertypes=("Token",),
        card_types=("Enchantment", "Creature"),
        subtypes=("Glimmer",),
        power=1, toughness=1,
    ),
}
