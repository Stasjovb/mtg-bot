"""Tests for batch-20 creature additions covering the
multi-trigger / trigger+activated cluster.

This batch grows the parser by claims that pair a triggered ability
with a second card-level component — either an activated ability on
the same printing or a second trigger arm. Each addition lands an
isolated piece of grammar; the per-card parity gate in
``tests/test_parser_parity.py`` enforces full ``CardPrinting``
equivalence so this file only needs the grammar-level assertions
plus end-to-end claim checks.

New effect-grammar primitives:

* ``put target card from a graveyard on the bottom of its owner's
  library`` → ``PutCardFromGraveyardOnBottomOfLibrary()``. Chrome
  Companion's tap-mana activated ability. Surface form is post-
  normalization (the ``it `` prefix-strip in
  ``_normalize_creature_effect_phrase`` doesn't fire because the
  phrase starts with the verb ``put``); the ``its`` pronoun in the
  effect tail survives intact, mirroring the ``put its counters
  on …`` precedent.

Newly-claimed creatures:

* **Chrome Companion** — ``Whenever this creature becomes tapped,
  you gain 1 life. {2}, {T}: Put target card from a graveyard on
  the bottom of its owner's library.`` The becomes-tapped + gain-1
  trigger half was already wired (BECOMES_TAPPED + IsSelf →
  GainLife); the activated half required the new graveyard-bottom
  primitive. Subtype ``Dog`` is added to the static registry per
  the parser-is-right rule (Scryfall prints the subtype).
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    ActivatedAbility,
    ActivationCost,
    GainLife,
    PutCardFromGraveyardOnBottomOfLibrary,
    TriggeredAbility,
    parse_mana_cost,
)
from mtg_bot.cards.parser.activated import _parse_activated_ability_line
from mtg_bot.cards.parser.effects import _parse_effect_phrase
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.cards.parser.triggers import _parse_triggered_ability_line
from mtg_bot.effects.predicates import (
    Event,
    IsSelf,
)


def _claimed_names() -> frozenset[str]:
    return frozenset(OracleParserCardSource().claimed_names)


# ---------- effect-phrase grammar ----------

def test_parse_put_card_from_graveyard_on_bottom_of_library():
    # New primitive — untyped grave-target across all players. The
    # ``its`` pronoun in the tail survives the creature-effect
    # normalizer (which only strips a leading ``it `` subject), so the
    # full surface form lands at the regex unchanged.
    phrase = (
        "put target card from a graveyard on the bottom of its "
        "owner's library"
    )
    assert _parse_effect_phrase(phrase) == (
        PutCardFromGraveyardOnBottomOfLibrary()
    )


def test_parse_put_card_from_graveyard_on_bottom_rejects_tail_drift():
    # A surface-text variant the parser must NOT silently coerce — the
    # grammar is anchored end-to-end via ``$``. A future printing whose
    # tail differs (``...top of its owner's library``) needs its own
    # primitive rather than collapsing onto this one.
    phrase = (
        "put target card from a graveyard on the top of its "
        "owner's library"
    )
    assert _parse_effect_phrase(phrase) is None


# ---------- activated-line end-to-end ----------

def test_chrome_companion_activated_ability_line():
    # End-to-end: the cost ``{2}, {T}`` decomposes via the bag-merge
    # classifier (one mana piece + one tap), the effect parses through
    # the new primitive, and the produced ``ActivatedAbility`` has no
    # mana-ability flag (``PutCardFromGraveyardOnBottomOfLibrary``
    # targets — CR 605 disqualifies it from the mana-ability fast path
    # regardless of cost).
    line = (
        "{2}, {T}: Put target card from a graveyard on the bottom "
        "of its owner's library."
    )
    parsed = _parse_activated_ability_line(line)
    assert parsed == ActivatedAbility(
        cost=ActivationCost(
            mana=parse_mana_cost("{2}"),
            mana_str="{2}",
            tap_self=True,
        ),
        effect=PutCardFromGraveyardOnBottomOfLibrary(),
    )


# ---------- trigger-line end-to-end ----------

def test_chrome_companion_becomes_tapped_trigger_line():
    # The becomes-tapped + gain-1 trigger half. Already wired in the
    # predicate-trigger phrasebook prior to this batch; asserted here
    # to anchor Chrome Companion's full claim narrative in a single
    # test file.
    line = "Whenever this creature becomes tapped, you gain 1 life."
    parsed = _parse_triggered_ability_line(line)
    assert parsed == TriggeredAbility(
        event=Event.BECOMES_TAPPED,
        predicate=IsSelf(),
        effect=GainLife(amount=1),
    )


# ---------- claim test (end-to-end via the parser source) ----------

def test_chrome_companion_claimed_by_parser():
    # End-to-end: the parser source's ``claimed_names`` includes
    # Chrome Companion. Per-card parity is enforced by
    # ``tests/test_parser_parity.py`` so a successful claim already
    # implies static-registry equivalence.
    assert "Chrome Companion" in _claimed_names()
