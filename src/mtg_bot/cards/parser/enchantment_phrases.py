"""Effect-phrase recognizers for the PowerLSV cube enchantment bucket
(``feature/cube-enchantments``).

:func:`parse_enchantment_phrase` is registered as a fallback recognizer
in :mod:`mtg_bot.cards.parser.precise_grammar`, so it only runs on
normalized phrases (no trailing period, lowercased first letter) that
every earlier grammar rejected — it can never change how an
already-claimed printing parses.

Shapes:

* ``add one mana of any type the sacrificed land could produce`` ->
  :class:`AddOneManaSacrificedLandCouldProduce` (Squandered Resources).
* ``exile [up to one ]target <noun> until this <permanent> leaves the
  battlefield`` -> :class:`ExileTargetUntilSourceLeaves` (Touch the
  Spirit Realm), any noun the compositional noun-phrase parser reads.
* ``exile target <noun>. Return it to the battlefield under its owner's
  control at the beginning of the next end step`` ->
  :class:`ExileTargetReturnAtNextEndStep` (Touch the Spirit Realm's
  Channel ability).
* ``each player returns to the battlefield all cards they own exiled
  with <it|this permanent>`` -> :class:`EachPlayerReturnsCardsExiledWithSource`
  (Parallax Wave).
* Oath of Druids' upkeep body -> :class:`OathRevealUntilCreature`.

:func:`parse_reanimation_aura_line` claims whole oracle lines of the
reanimation-Aura family (Animate Dead, Necromancy) for the cube
enchantment builder.
"""

from __future__ import annotations

import re

from mtg_bot.effects.base import Effect


_SACRIFICED_LAND_MANA = "add one mana of any type the sacrificed land could produce"

_SELF_NOUN = r"this (?:enchantment|artifact|creature|permanent)"

_EXILE_UNTIL_SOURCE_LEAVES = re.compile(
    rf"^exile (?P<upto>up to one )?target (?P<noun>.+?) until {_SELF_NOUN} "
    rf"leaves the battlefield$"
)

_EXILE_RETURN_AT_NEXT_END_STEP = re.compile(
    r"^exile target (?P<noun>.+?)\. [Rr]eturn it to the battlefield under "
    r"its owner's control at the beginning of the next end step$"
)

_EACH_PLAYER_RETURNS_EXILED_WITH = re.compile(
    rf"^each player returns to the battlefield all cards they own exiled "
    rf"with (?:it|{_SELF_NOUN})$"
)

# Oath of Druids (only card in the pool with the "player who controls
# more creatures" target + reveal-until-creature body; the pieces are
# parameterized on the revealed card type so a second "reveal until a
# <type> card" printing needs no new class).
_OATH_BODY = re.compile(
    r"^that player chooses target player who controls more creatures than "
    r"they do and is their opponent\. The first player may reveal cards "
    r"from the top of their library until they reveal an? (?P<type>[a-z]+) "
    r"card\. If the first player does, that player puts that card onto the "
    r"battlefield and all other cards revealed this way into their "
    r"graveyard$"
)


def parse_enchantment_phrase(phrase: str) -> Effect | None:
    from mtg_bot.cards.parser.effects_ext import _target_spec
    from mtg_bot.effects.generic.enchantment_mechanics import (
        AddOneManaSacrificedLandCouldProduce,
        EachPlayerReturnsCardsExiledWithSource,
        ExileTargetReturnAtNextEndStep,
        ExileTargetUntilSourceLeaves,
        OathRevealUntilCreature,
    )

    if phrase == _SACRIFICED_LAND_MANA:
        return AddOneManaSacrificedLandCouldProduce()
    m = _EXILE_UNTIL_SOURCE_LEAVES.match(phrase)
    if m is not None:
        spec = _target_spec(m.group("noun"), bool(m.group("upto")))
        if spec is None:
            return None
        return ExileTargetUntilSourceLeaves(targets=(spec,))
    m = _EXILE_RETURN_AT_NEXT_END_STEP.match(phrase)
    if m is not None:
        spec = _target_spec(m.group("noun"), False)
        if spec is None:
            return None
        return ExileTargetReturnAtNextEndStep(targets=(spec,))
    if _EACH_PLAYER_RETURNS_EXILED_WITH.match(phrase):
        return EachPlayerReturnsCardsExiledWithSource()
    m = _OATH_BODY.match(phrase)
    if m is not None:
        return OathRevealUntilCreature(card_type=m.group("type"))
    return None


# The reanimation-Aura enters/leaves paragraph. Two printed variants:
# the Aura that already enchants a graveyard card (Animate Dead) and the
# non-Aura enchantment that becomes one and targets (Necromancy).
_REANIMATION_TRIGGER_LINE = re.compile(
    r"^When this (?P<self>Aura|enchantment) enters, if it's on the "
    r"battlefield, (?:"
    r"it loses \"enchant creature card in a graveyard\" and gains \"enchant "
    r"creature put onto the battlefield with this Aura\.\" Return enchanted "
    r"creature card to the battlefield under your control and attach this "
    r"Aura to it"
    r"|it becomes an Aura with \"enchant creature put onto the battlefield "
    r"with [^\"]+\.\" Put (?P<target>target) creature card from a graveyard "
    r"onto the battlefield under your control and attach this enchantment "
    r"to it"
    r")\. When this (?P=self) leaves the battlefield, that creature's "
    r"controller sacrifices it\.$"
)

# Necromancy's cast permission + instant-speed rider. Literal: the only
# "as though it had flash ... next cleanup step" card in the pool.
_AS_THOUGH_FLASH_CLEANUP_SACRIFICE_LINE = (
    "You may cast this spell as though it had flash. If you cast it any "
    "time a sorcery couldn't have been cast, the controller of the "
    "permanent it becomes sacrifices it at the beginning of the next "
    "cleanup step."
)


def parse_reanimation_aura_line(line: str):
    """Whole-line recognizer for the reanimation-Aura family. Returns
    ``(triggers, printing_fields)`` or ``None``.

    * The enters/leaves paragraph -> an ``ENTERS`` trigger with
      :class:`ReanimateAndAttachSource` (``from_target`` for the
      "Put target creature card from a graveyard" variant) and a
      ``LEAVES_BATTLEFIELD`` trigger with
      :class:`LinkedCreatureControllerSacrifices`.
    * Necromancy's cast line -> ``flash`` (cast permission) plus
      ``sacrifice_at_cleanup_if_cast_without_sorcery_timing``.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.enchantment_mechanics import (
        LinkedCreatureControllerSacrifices,
        ReanimateAndAttachSource,
    )
    from mtg_bot.effects.predicates import Event, IsSelf

    if line == _AS_THOUGH_FLASH_CLEANUP_SACRIFICE_LINE:
        return (), {
            "flash": True,
            "sacrifice_at_cleanup_if_cast_without_sorcery_timing": True,
        }
    m = _REANIMATION_TRIGGER_LINE.match(line)
    if m is None:
        return None
    triggers = (
        TriggeredAbility(
            event=Event.ENTERS, predicate=IsSelf(),
            effect=ReanimateAndAttachSource(
                from_target=m.group("target") is not None,
            ),
        ),
        TriggeredAbility(
            event=Event.LEAVES_BATTLEFIELD, predicate=IsSelf(),
            effect=LinkedCreatureControllerSacrifices(),
        ),
    )
    return triggers, {}


__all__ = ["parse_enchantment_phrase", "parse_reanimation_aura_line"]
