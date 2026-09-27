"""Phrase-level grammar for the non-normal card layouts (cube layouts
bucket): transform / return-transformed effects and the trigger
conditions and effect bodies printed on the faces of the bucket's
double-faced cards, Sagas, Classes and levelers.

Both entry points are wired as the LAST fallback of their grammar
(:func:`parse_layout_effect` after every other effect recognizer in
``effects._parse_effect``; :func:`parse_layout_trigger_phrase` after
every other predicate-trigger phrase in
``triggers._parse_predicate_trigger_phrase``), so they only claim
phrases nothing else understood and can't change an existing parse.

Phrases arrive normalized: no trailing period, first letter lowercased,
the card's own name (full or short form) rewritten to ``this creature``.
"""

from __future__ import annotations

import re

from mtg_bot.effects.base import Effect

_PRONOUN = r"(?:him|her|it|them)"
_POSSESSIVE = r"(?:his|her|its|their)"

_TRANSFORM_SELF = re.compile(
    r"^transform (?:this (?:creature|permanent|artifact|enchantment)|it)$"
)
_EXILE_RETURN_TRANSFORMED = re.compile(
    r"^exile this (?:creature|saga|permanent|artifact|enchantment), then "
    rf"return {_PRONOUN} to the battlefield transformed under "
    rf"(?P<whose>{_POSSESSIVE} owner's|your) control$"
)


# "[you may] have <this creature> deal that much damage to any target"
# (The Sensational She-Hulk): the damage the triggering event dealt
# (``state.resolving_combat_damage_amount``, threaded by the
# DEALT_DAMAGE / damage-trigger dispatch) to any target.
_HAVE_SELF_DEAL_THAT_MUCH = re.compile(
    r"^(?:have this creature deal|deals) that much damage to any target$"
)


# "All <permanents> you control become P/T creatures until end of turn.
# They're still <permanents>." (Life) -- a one-shot mass animation.
_ALL_YOURS_BECOME_CREATURES_UEOT = re.compile(
    r"^all (?P<noun>lands|artifacts|enchantments) you control become "
    r"(?P<p>\d+)/(?P<t>\d+) creatures until end of turn\. "
    r"[Tt]hey're still (?P=noun)$"
)
_TYPE_OF_NOUN = {"lands": "Land", "artifacts": "Artifact", "enchantments": "Enchantment"}


def parse_layout_effect(phrase: str) -> Effect | None:
    """Effect for a normalized ``phrase`` of this bucket's shapes, or
    ``None``."""
    from mtg_bot.effects.generic.layout_effects import (
        ExileSourceThenReturnTransformed,
        TransformSource,
    )

    if _TRANSFORM_SELF.match(phrase):
        return TransformSource()
    m = _ALL_YOURS_BECOME_CREATURES_UEOT.match(phrase)
    if m is not None:
        from mtg_bot.effects.generic.layout_effects import (
            YourPermanentsBecomeCreaturesUEOT,
        )

        return YourPermanentsBecomeCreaturesUEOT(
            card_type=_TYPE_OF_NOUN[m.group("noun")],
            power=int(m.group("p")), toughness=int(m.group("t")),
        )
    if _HAVE_SELF_DEAL_THAT_MUCH.match(phrase):
        from mtg_bot.effects.generic.cube_creatures_rmc import (
            DealDamageFromEvent,
            ResolvingDamageAmount,
        )
        from mtg_bot.effects.targets import TargetSpec, any_target_filter

        return DealDamageFromEvent(
            amount=ResolvingDamageAmount(),
            targets=(TargetSpec(any_target_filter()),),
        )
    m = _EXILE_RETURN_TRANSFORMED.match(phrase)
    if m is not None:
        return ExileSourceThenReturnTransformed(
            under_owners_control=m.group("whose") != "your",
        )
    return None


_TRANSFORMS_INTO_SELF = re.compile(
    r"^this creature transforms into this creature$"
)


def parse_layout_trigger_phrase(phrase: str):
    """``(Event, Predicate)`` for a trigger-condition ``phrase`` of this
    bucket's shapes, or ``None``."""
    from mtg_bot.effects.predicates import Event, IsSelf

    if phrase == "a creature you control is dealt damage":
        from mtg_bot.effects.object_predicates import IsCreature
        from mtg_bot.effects.predicates import YOU, Controlled, Subject

        return (
            Event.DEALT_DAMAGE,
            Subject(None, IsCreature()) & Controlled(YOU),
        )
    if _TRANSFORMS_INTO_SELF.match(phrase):
        # "When this creature transforms into <this face's name>" -- the
        # ability lives on that face, so it's active only once the
        # permanent has turned to it (``layouts.transform_permanent``
        # dispatches after the face change); entering transformed isn't
        # transforming (CR 701.28e).
        return (Event.TRANSFORMS, IsSelf())
    return None
