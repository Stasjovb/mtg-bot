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
"""

from __future__ import annotations

from mtg_bot.cards.base import CardPrinting, make_aura, make_creature


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
