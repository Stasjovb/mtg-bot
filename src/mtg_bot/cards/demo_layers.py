"""Real Magic cards from outside the EoE pool, used to exercise
layered-effects machinery (CR 613) that no current EoE card stresses.

Not registered in ``NONLAND_POOL`` / ``all_printings`` — these aren't
draftable, deckable, or castable through the normal card pool. Tests
import the printings directly to construct GameObjects.

Currently:

- ``LIGNIFY`` (Lorwyn) — "Enchant creature. Enchanted creature is a
  Treefolk creature with base power and toughness 0/4 and has no
  abilities." Combines layer 4 (add subtype "Treefolk"), layer 6
  (lose all abilities), and layer 7 sublayer 1 (set base P/T 0/4).
- ``CLONE`` (Alpha) — "You may have Clone enter as a copy of any
  creature on the battlefield." Layer 1 copy effect: at ETB the
  controller picks a target creature, and the clone takes that
  creature's PRINTED characteristics (CR 706.2 copiable values —
  not auras, counters, or current animations). Writes a layer-1
  ``"is_copy"`` registry entry so the layered system records the
  copy event; the entry is dropped when the clone leaves play.
- ``MAGICAL_HACK`` (Alpha) — "Change the text of target spell or
  permanent by replacing all instances of one basic land type with
  another." Sorcery, layer 3 text-changing. The demo targets a
  basic land and rewrites its basic-land-type subtype, which flows
  through ``effective_subtypes`` and ``effective_land_produces`` so
  the rewritten land taps for the new color. Persistent (no
  ``expires_at``) — text changes survive cleanup per CR 612.
- ``WHITE_KNIGHT`` (Alpha) — 2/2 white Knight with first strike and
  protection from black. Used as the protection-target so layer 5
  color changes have observable consequences in combat.
- ``SCUTTLEMUTT`` (Shards of Alara) — 3/3 Scarecrow with
  ``{T}: Target creature becomes the color or colors of your choice
  until end of turn.`` Layer 5 color-changing effect that writes a
  ``"set_colors"`` registry entry with ``expires_at="cleanup"``.
"""

from __future__ import annotations

from mtg_bot.effects import (
    MagicalHackTextChangeEffect, ScuttlemuttColorChangeUEOT,
)
from mtg_bot.effects.base import ActivatedAbility, ActivationCost
from mtg_bot.cards.base import (
    CardPrinting, make_aura, make_creature, make_sorcery, parse_mana_cost,
)


LIGNIFY: CardPrinting = make_aura(
    "Lignify", "{1}{G}",
    attached_sets_base_pt=(0, 4),
    attached_grants_lose_all_abilities=True,
    attached_grants_subtype="Treefolk",
)


CLONE: CardPrinting = make_creature(
    "Clone", "{3}{U}", 0, 0,
    enters_as_copy_of_creature=True,
)


MAGICAL_HACK: CardPrinting = make_sorcery(
    "Magical Hack", "{U}",
    effect=MagicalHackTextChangeEffect(),
)


WHITE_KNIGHT: CardPrinting = make_creature(
    "White Knight", "{W}{W}", 2, 2,
    keywords={"first strike"},
    protection_from_color="B",
)


SCUTTLEMUTT: CardPrinting = make_creature(
    "Scuttlemutt", "{4}", 3, 3,
    subtypes=("Scarecrow",),
    activated_abilities=(
        ActivatedAbility(
            cost=ActivationCost(tap_self=True),
            effect=ScuttlemuttColorChangeUEOT(),
        ),
    ),
)
