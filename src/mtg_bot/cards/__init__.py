"""Card printings, mana cost parsing, basic lands, and the Stage-1 synthetic pool.

Public API: everything below remains importable from ``mtg_bot.cards`` for
back-compat. Internal layout (submodules):

- ``base``           — CardPrinting + ManaCost + all ``make_*`` helpers +
                       pre-built granted-ability constants.
- ``lands``          — Basic lands, Planet lands, Utility lands, Shock lands.
- ``stellar_sights`` — EoE Stellar Sights bonus-sheet reprints (set ``eos``).
- ``special_guests`` — EoE Special Guests subset (set ``spg``, 10 cards).
- ``synthetic``      — Stage-1 invented vanilla creatures.
- ``tokens``         — Token printings created by effects (Lander, Robot,
                       Drone, Sliver, Munitions).
- ``eoe_creatures``  — Edge of Eternities creature printings.
- ``eoe_spells``     — Edge of Eternities instants and sorceries.
- ``registry``       — NONLAND_POOL + ``all_printings`` + deck builder.
"""

from __future__ import annotations

# Re-export the full effects surface that used to be imported at the
# top of cards.py — tests and other modules rely on names like
# ActivatedAbility / TriggeredAbility being reachable via
# ``from mtg_bot.cards import X``.
from mtg_bot.cards.base import *  # noqa: F401,F403
from mtg_bot.cards.base import (
    COLORS,
    CardPrinting,
    CostReduction,
    DOMINION_BRACELET_GRANTED_ABILITY,
    ManaCost,
    RAGOST_FOOD_GRANTED_ABILITY,
    cost,
    make_artifact,
    make_aura,
    make_basic_land,
    make_colorless_land,
    make_creature,
    make_enchantment,
    make_equipment,
    make_instant,
    make_planet_land,
    make_planeswalker,
    make_shock_land,
    make_sorcery,
    make_spacecraft,
    make_token_creature,
    make_utility_land,
    parse_mana_cost,
)
from mtg_bot.cards.eoe_creatures import EOE_CREATURES
from mtg_bot.cards.eoe_spells import EOE_SPELLS
from mtg_bot.cards.lands import (
    BASIC_LANDS, PLANET_LANDS, SHOCK_LANDS, UTILITY_LANDS,
)
from mtg_bot.cards.registry import (
    CREATURE_POOL,
    NONLAND_POOL,
    all_printings,
    build_mono_color_deck,
)
from mtg_bot.cards.special_guests import SPECIAL_GUESTS_EOE
from mtg_bot.cards.stellar_sights import STELLAR_SIGHTS_LANDS
from mtg_bot.cards.synthetic import SYNTHETIC_CREATURES
from mtg_bot.cards.tokens import TOKEN_PRINTINGS
