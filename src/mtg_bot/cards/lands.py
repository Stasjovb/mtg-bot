"""Basic lands, EoE Planet lands, and the shock-land cycle.

Small fixed registries. Larger land sets (Stellar Sights bonus-sheet reprints)
live in ``stellar_sights.py``.
"""

from __future__ import annotations

from mtg_bot.effects import (
    ActivatedAbility, ActivationCost, AddManaToPool,
    SacrificeSelfUnlessTapPermanent, TriggeredAbility,
)
from mtg_bot.cards.base import (
    CardPrinting, make_basic_land, make_colorless_land, make_planet_land,
    make_shock_land, make_utility_land,
)


BASIC_LANDS: dict[str, CardPrinting] = {
    "Plains": make_basic_land("Plains", "W"),
    "Island": make_basic_land("Island", "U"),
    "Swamp": make_basic_land("Swamp", "B"),
    "Mountain": make_basic_land("Mountain", "R"),
    "Forest": make_basic_land("Forest", "G"),
}


# Shock-land cycle from EoE. Each is Land — L1 L2 producing both colors,
# "As this land enters, you may pay 2 life. If you don't, it enters
# tapped."
PLANET_LANDS: dict[str, CardPrinting] = {
    "Adagia, Windswept Bastion": make_planet_land(
        "Adagia, Windswept Bastion", "W",
    ),
    "Uthros, Titanic Godcore": make_planet_land(
        "Uthros, Titanic Godcore", "U",
    ),
    "Susur Secundi, Void Altar": make_planet_land(
        "Susur Secundi, Void Altar", "B",
    ),
    "Kavaron, Memorial World": make_planet_land(
        "Kavaron, Memorial World", "R",
    ),
    "Evendo, Waking Haven": make_planet_land(
        "Evendo, Waking Haven", "G",
    ),
}


UTILITY_LANDS: dict[str, CardPrinting] = {
    # Secluded Starforge: simplified to just a {T}: Add {C} utility
    # land. Dropped: the "{2},{T}, Tap X artifacts: +X/+0 UEOT" and
    # "{5},{T}: create a Robot token" activated abilities (tap-X-things
    # cost + Robot-token activated not worth wiring for one card).
    "Secluded Starforge": make_colorless_land("Secluded Starforge"),
    # Command Bridge: enters tapped; "When this land enters, sacrifice
    # it unless you tap an untapped permanent you control"; {T}: add
    # one mana of any color. The any-color tap is via an explicit
    # mana ActivatedAbility (mirrors Gemstone Caverns/All-Fates Scroll
    # pattern). The ETB rider runs through SacrificeSelfUnlessTapPermanent
    # which delegates the tap-or-sac choice to the controller's agent.
    "Command Bridge": make_utility_land(
        "Command Bridge",
        enters_tapped=True,
        triggered_abilities=(
            TriggeredAbility(
                trigger="etb", effect=SacrificeSelfUnlessTapPermanent(),
            ),
        ),
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(tap_self=True),
                effect=AddManaToPool(produces=(("any", 1),)),
                is_mana_ability=True,
            ),
        ),
    ),
}


SHOCK_LANDS: dict[str, CardPrinting] = {
    "Breeding Pool": make_shock_land(
        "Breeding Pool", ("G", "U"), "Forest Island",
    ),
    "Godless Shrine": make_shock_land(
        "Godless Shrine", ("W", "B"), "Plains Swamp",
    ),
    "Sacred Foundry": make_shock_land(
        "Sacred Foundry", ("R", "W"), "Mountain Plains",
    ),
    "Stomping Ground": make_shock_land(
        "Stomping Ground", ("R", "G"), "Mountain Forest",
    ),
    "Watery Grave": make_shock_land(
        "Watery Grave", ("U", "B"), "Island Swamp",
    ),
}
