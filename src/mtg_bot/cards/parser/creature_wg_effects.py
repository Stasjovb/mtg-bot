"""Effect-phrase recognizers for the cube W/G creature bucket.

Hooked into :func:`mtg_bot.cards.parser.effects._parse_effect` as the
very last fallback (after the planeswalker extension grammar and the
card-flow grammar), so these shapes only claim phrases nothing else
understood and can never change an existing parse. Phrases arrive
normalized: no trailing period, lower-cased first letter; later
sentences keep their capitalization.

Shapes:

* ``[up to one ]target player puts all the cards from their graveyard
  on the bottom of their library in a random order`` ->
  :class:`TargetPlayerPutsGraveyardOnBottomRandom` (Endurance)
"""

from __future__ import annotations

import re

from mtg_bot.effects.base import Effect


_GRAVEYARD_ON_BOTTOM_RE = re.compile(
    r"^(?P<upto>up to one )?target player puts all the cards from their "
    r"graveyard on the bottom of their library in a random order$"
)


def parse_wg_effect(phrase: str) -> Effect | None:
    """Last-resort W/G bucket recognizers (see the module docstring)."""
    m = _GRAVEYARD_ON_BOTTOM_RE.match(phrase)
    if m is not None:
        from mtg_bot.effects.generic.cube_creatures_wg import (
            TargetPlayerPutsGraveyardOnBottomRandom,
        )

        return TargetPlayerPutsGraveyardOnBottomRandom(
            up_to_one=bool(m.group("upto")),
        )
    return None


__all__ = ["parse_wg_effect"]
