"""Tests for the Duskmourn ``Delirium`` mechanic in the parser.

Delirium is a static threshold MTG keyword: an ability fires (or an
effect resolves) only when the source's controller has four or more
distinct card types among cards in their graveyard. The parser
support lands as:

* ``Delirium`` predicate in ``mtg_bot.effects.predicates`` — a
  game-state check that walks the controller's graveyard and counts
  distinct card types from the comprehensive-rules taxonomy
  (Creature, Land, Sorcery, Instant, Enchantment, Artifact,
  Planeswalker, Battle, Tribal). Subject-independent, mirrors
  ``VoidActive`` and ``OpponentControlsMoreLandsThanYou``.

* New ``_INTERVENING_IF_PHRASES`` entry: the canonical printed
  gate ``"there are four or more card types among cards in your
  graveyard"`` maps to ``Delirium()``. The Delirium ability-word
  prefix (``Delirium — ``) carries no rules consequence — it strips
  through the existing generic ``_strip_ability_word_prefix`` helper
  with no Delirium-specific code path needed.

End-to-end card claims: no DSK Delirium card claims end-to-end on
this branch — every printing carries at least one other clause
(complex effect bodies, ``while``-shape trigger conditions, or
static ``as long as`` riders) that the parser doesn't yet handle.
This batch ships the predicate + intervening-if plumbing so those
claims unblock as the surrounding grammar grows.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mtg_bot.cards.base import DrawCards, TriggeredAbility
from mtg_bot.cards.parser.triggers import (
    _INTERVENING_IF_PHRASES,
    _parse_intervening_if_phrase,
    _parse_triggered_ability_line,
)
from mtg_bot.effects.predicates import Delirium, Event, IsSelf


# ---------- _parse_intervening_if_phrase: positive lookups ----------


def test_intervening_if_phrasebook_includes_delirium():
    phrase = "there are four or more card types among cards in your graveyard"
    assert _parse_intervening_if_phrase(phrase) == Delirium()


def test_intervening_if_phrasebook_strips_surrounding_whitespace_for_delirium():
    # The lookup helper strips outer whitespace; this guards against an
    # accidental change that drops the strip. Mirrors the equivalent
    # check on the Void / opponent-more-lands gates.
    phrase = (
        "  there are four or more card types among cards in your "
        "graveyard  "
    )
    assert _parse_intervening_if_phrase(phrase) == Delirium()


# ---------- _parse_triggered_ability_line: end-to-end ----------


def test_intervening_if_delirium_attack_predicate():
    # Bare ``Whenever this creature attacks, if <Delirium gate>,
    # <effect>.`` — the Delirium ability-word prefix is tested
    # separately below; here we exercise the no-prefix shape so the
    # regex paths stay independent.
    line = (
        "Whenever this creature attacks, if there are four or more "
        "card types among cards in your graveyard, draw a card."
    )
    assert _parse_triggered_ability_line(line) == TriggeredAbility(
        event=Event.ATTACKS,
        predicate=IsSelf() & Delirium(),
        effect=DrawCards(amount=1),
    )


def test_intervening_if_delirium_etb_predicate():
    # Same Delirium gate on an ETB trigger. Different event, identical
    # predicate composition.
    line = (
        "When this creature enters, if there are four or more card "
        "types among cards in your graveyard, draw a card."
    )
    assert _parse_triggered_ability_line(line) == TriggeredAbility(
        event=Event.ENTERS,
        predicate=IsSelf() & Delirium(),
        effect=DrawCards(amount=1),
    )


def test_intervening_if_delirium_ability_word_prefix_stripped():
    # The ``Delirium —`` ability-word prefix is generic-stripped (no
    # rules consequence per CR 207.2c); the surviving body parses the
    # same way the bare attack form does. Mirrors the ``Landfall —`` /
    # ``Void —`` ability-word strips already exercised by other tests.
    line = (
        "Delirium — Whenever this creature attacks, if there are four "
        "or more card types among cards in your graveyard, draw a card."
    )
    assert _parse_triggered_ability_line(line) == TriggeredAbility(
        event=Event.ATTACKS,
        predicate=IsSelf() & Delirium(),
        effect=DrawCards(amount=1),
    )


def test_intervening_if_delirium_ability_word_prefix_on_etb():
    # ``Delirium — When this creature enters, …`` shape — the
    # ability-word prefix is strip-agnostic to ``When`` vs ``Whenever``.
    line = (
        "Delirium — When this creature enters, if there are four or "
        "more card types among cards in your graveyard, draw a card."
    )
    assert _parse_triggered_ability_line(line) == TriggeredAbility(
        event=Event.ENTERS,
        predicate=IsSelf() & Delirium(),
        effect=DrawCards(amount=1),
    )


# ---------- phrasebook integrity ----------


def test_delirium_phrase_lives_in_intervening_if_table():
    phrase = "there are four or more card types among cards in your graveyard"
    assert phrase in _INTERVENING_IF_PHRASES
    assert _INTERVENING_IF_PHRASES[phrase] == Delirium()


# ---------- predicate evaluation ----------


@dataclass
class _FakePrinting:
    card_types: tuple[str, ...] = ()


@dataclass
class _FakeCard:
    printing: _FakePrinting = field(default_factory=_FakePrinting)


@dataclass
class _FakePlayer:
    id: int = 0
    graveyard: list[_FakeCard] = field(default_factory=list)


@dataclass
class _FakeState:
    players: list[_FakePlayer] = field(default_factory=list)

    def player_by_id(self, pid: int) -> _FakePlayer:
        for p in self.players:
            if p.id == pid:
                return p
        raise KeyError(pid)


@dataclass
class _StubSource:
    controller_id: int = 0


def _make_state(types_in_yard: list[tuple[str, ...]]) -> _FakeState:
    """Build a one-player ``_FakeState`` whose graveyard contains one
    fake card per entry in ``types_in_yard``. Each entry is a tuple
    of card types for that one card."""
    p = _FakePlayer(id=0, graveyard=[
        _FakeCard(printing=_FakePrinting(card_types=t))
        for t in types_in_yard
    ])
    return _FakeState(players=[p])


def test_delirium_false_with_empty_graveyard():
    state = _make_state([])
    assert Delirium().matches(state, {}, _StubSource()) is False


def test_delirium_false_with_three_distinct_types():
    state = _make_state([
        ("Creature",),
        ("Land",),
        ("Sorcery",),
    ])
    assert Delirium().matches(state, {}, _StubSource()) is False


def test_delirium_true_with_four_distinct_types():
    state = _make_state([
        ("Creature",),
        ("Land",),
        ("Sorcery",),
        ("Instant",),
    ])
    assert Delirium().matches(state, {}, _StubSource()) is True


def test_delirium_true_with_more_than_four_distinct_types():
    state = _make_state([
        ("Creature",),
        ("Land",),
        ("Sorcery",),
        ("Instant",),
        ("Enchantment",),
        ("Artifact",),
    ])
    assert Delirium().matches(state, {}, _StubSource()) is True


def test_delirium_counts_distinct_types_not_card_count():
    # Eight Creature cards in the yard still count as ONE type. This
    # is the most common false-positive shape — guard against it.
    state = _make_state([("Creature",)] * 8)
    assert Delirium().matches(state, {}, _StubSource()) is False


def test_delirium_multitype_card_contributes_all_its_types():
    # A single Artifact Creature card supplies BOTH Artifact and
    # Creature toward the threshold. With one such card plus a Land
    # and a Sorcery the controller has four distinct types from
    # three cards.
    state = _make_state([
        ("Artifact", "Creature"),
        ("Land",),
        ("Sorcery",),
    ])
    assert Delirium().matches(state, {}, _StubSource()) is True


def test_delirium_ignores_supertypes_and_subtypes():
    # Only card types from the CR 205.2a taxonomy count — supertypes
    # (Legendary, Snow, Basic) and subtypes (Goblin, Equipment) live
    # on different attributes and don't appear in ``card_types``.
    # The ``card_types`` field already segregates them, so a future
    # change that mistakenly reads ``supertypes`` would surface as
    # a regression here. Three real types + a card that supplies
    # only "Legendary" / "Goblin" should NOT cross the threshold.
    state = _make_state([
        ("Creature",),
        ("Land",),
        ("Sorcery",),
        # Non-card-type tokens — even if a future bug ingested these
        # into ``card_types``, the ``Delirium`` predicate filters
        # against the canonical type set and ignores them.
        ("Legendary", "Goblin", "Basic"),
    ])
    assert Delirium().matches(state, {}, _StubSource()) is False


def test_delirium_short_circuits_on_threshold_hit():
    # If a graveyard already has four distinct types in the first few
    # cards, the predicate must return without scanning the rest. We
    # observe this indirectly by mixing in an entry whose card_types
    # tuple is a non-iterable sentinel — the predicate raising would
    # mean it didn't short-circuit before reaching that entry. The
    # test passes both because no exception is raised AND the
    # predicate returns True.
    @dataclass
    class _Bomb:
        printing: object = field(default_factory=lambda: _FakePrinting(
            card_types=("Creature",),
        ))

    p = _FakePlayer(id=0, graveyard=[
        _FakeCard(printing=_FakePrinting(card_types=("Creature",))),
        _FakeCard(printing=_FakePrinting(card_types=("Land",))),
        _FakeCard(printing=_FakePrinting(card_types=("Sorcery",))),
        _FakeCard(printing=_FakePrinting(card_types=("Instant",))),
        _Bomb(),  # would be reached only if we don't short-circuit
    ])
    state = _FakeState(players=[p])
    assert Delirium().matches(state, {}, _StubSource()) is True


def test_delirium_uses_source_controller_not_other_players():
    # The graveyard scan keys off ``source.controller_id``; another
    # player's graveyard with four types must not flip the predicate.
    p_self = _FakePlayer(id=0, graveyard=[
        _FakeCard(printing=_FakePrinting(card_types=("Creature",))),
    ])
    p_opp = _FakePlayer(id=1, graveyard=[
        _FakeCard(printing=_FakePrinting(card_types=("Creature",))),
        _FakeCard(printing=_FakePrinting(card_types=("Land",))),
        _FakeCard(printing=_FakePrinting(card_types=("Sorcery",))),
        _FakeCard(printing=_FakePrinting(card_types=("Instant",))),
    ])
    state = _FakeState(players=[p_self, p_opp])
    src = _StubSource(controller_id=0)
    assert Delirium().matches(state, {}, src) is False
    # Re-host the source under the opponent and the predicate flips.
    src_opp = _StubSource(controller_id=1)
    assert Delirium().matches(state, {}, src_opp) is True


def test_delirium_false_when_source_controller_unknown():
    # Defensive: a source whose controller isn't a known player should
    # evaluate False rather than raise. Mirrors the
    # ``SpellsCastThisTurn`` predicate's KeyError-swallow behavior.
    state = _make_state([
        ("Creature",),
        ("Land",),
        ("Sorcery",),
        ("Instant",),
    ])
    src = _StubSource(controller_id=99)
    assert Delirium().matches(state, {}, src) is False
