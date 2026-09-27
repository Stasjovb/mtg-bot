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


def parse_layout_effect(phrase: str) -> Effect | None:
    """Effect for a normalized ``phrase`` of this bucket's shapes, or
    ``None``."""
    from mtg_bot.effects.generic.layout_effects import (
        ExileSourceThenReturnTransformed,
        TransformSource,
    )

    if _TRANSFORM_SELF.match(phrase):
        return TransformSource()
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

    if _TRANSFORMS_INTO_SELF.match(phrase):
        # "When this creature transforms into <this face's name>" -- the
        # ability lives on that face, so it's active only once the
        # permanent has turned to it (``layouts.transform_permanent``
        # dispatches after the face change); entering transformed isn't
        # transforming (CR 701.28e).
        return (Event.TRANSFORMS, IsSelf())
    return None
