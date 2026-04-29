"""Tests for the fourth Duskmourn creature parser batch.

This batch grows the parser to claim a new cluster of Duskmourn
creatures by layering small additive primitives on top of the existing
engine surface — no new events or core data fields are required beyond
two trailing-rider gates on ``StaticAbility``.

* **``requires_delirium`` static gate** + **static ability-word prefix
  stripper** — Wildfire Wickerfolk (``{R}{G}`` 3/2 Artifact Creature —
  Scarecrow). Prints ``Haste`` plus
  ``Delirium — This creature gets +1/+1 and has trample as long as
  there are four or more card types among cards in your graveyard.``
  The ``Delirium —`` prefix carries no rules consequence (CR 207.2c)
  so the new ``_strip_static_ability_word_prefix`` helper drops it
  before the trailing static grammar dispatches; the ``as long as``
  tail then maps to ``requires_delirium=True`` via a new
  ``_STATIC_CONDITION_KWARGS`` entry. The engine's
  ``StaticAbility.applies_to`` evaluates the gate by walking the
  controller's graveyard and counting distinct card types — same
  semantics as the trigger-side ``Delirium()`` predicate.
"""

from __future__ import annotations

from mtg_bot.cards.base import StaticAbility, StaticScope
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.cards.parser.statics import (
    _parse_static_ability_line,
    _strip_static_ability_word_prefix,
)


def _claimed_names() -> frozenset[str]:
    return frozenset(OracleParserCardSource().claimed_names)


# ---------- ``_strip_static_ability_word_prefix`` ----------


def test_strip_static_ability_word_prefix_strips_delirium():
    # The canonical use case: a ``Delirium — This creature gets ...``
    # static line. The ability-word prefix peels off and the body is
    # returned unchanged so the existing trailing-static grammar can
    # handle it.
    stripped = _strip_static_ability_word_prefix(
        "Delirium — This creature gets +1/+1 and has trample as long "
        "as there are four or more card types among cards in your "
        "graveyard."
    )
    assert stripped == (
        "This creature gets +1/+1 and has trample as long as there are "
        "four or more card types among cards in your graveyard."
    )


def test_strip_static_ability_word_prefix_strips_anthem_body():
    # Forward-looking grammar coverage for an ability-word + anthem-
    # body printing (no DSK card today, but the regex permits the
    # combination because the body matcher includes the
    # ``Creatures you control`` family). The stripper drops the prefix
    # so the body parses through ``_parse_anthem_static_line``.
    stripped = _strip_static_ability_word_prefix(
        "Delirium — Creatures you control get +1/+1."
    )
    assert stripped == "Creatures you control get +1/+1."


def test_strip_static_ability_word_prefix_leaves_trigger_lines_alone():
    # The static stripper deliberately doesn't peel a prefix from a
    # ``When``/``Whenever`` body — that family is the trigger-layer
    # ``_strip_ability_word_prefix``'s job. Returning the line unchanged
    # here lets the static dispatcher fail back to the trigger path on
    # the original surface form.
    line = "Delirium — Whenever this creature attacks, draw a card."
    assert _strip_static_ability_word_prefix(line) == line


def test_strip_static_ability_word_prefix_no_prefix_unchanged():
    # A static line with no leading ``<Word> — `` ability-word prefix
    # passes through untouched so non-Delirium statics keep their
    # exact surface form into the grammar.
    line = "This creature gets +1/+1 as long as it's your turn."
    assert _strip_static_ability_word_prefix(line) == line


# ---------- ``requires_delirium`` static gate ----------


def test_static_delirium_gate_inactive_below_threshold():
    # ``StaticAbility`` with ``requires_delirium=True`` is inert until
    # the controller's graveyard contains four or more distinct card
    # types. With an empty graveyard, the ability does NOT apply to
    # its source.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.game import GameState, Player, Zone
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    src = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(src)
    static = StaticAbility(
        scope=StaticScope.SELF,
        power_bonus=1,
        toughness_bonus=1,
        granted_keywords=frozenset({"trample"}),
        requires_delirium=True,
    )
    assert static.applies_to(src, src, state) is False


def test_static_delirium_gate_active_at_threshold():
    # With four distinct card types in the controller's graveyard the
    # ability applies to its source. We seed the graveyard with one
    # card per type — Creature / Sorcery / Instant / Land — using the
    # parser pool so the printings carry real ``card_types`` entries.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.game import GameState, Player, Zone
    state = GameState()
    p = Player(id=0, agent=RandomAgent())
    state.players.append(p)
    src = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(src)
    printings = OracleParserCardSource().get_printings()
    needed = {"Creature", "Sorcery", "Instant", "Land"}
    seen: set[str] = set()
    for name, prn in printings.items():
        types = set(prn.card_types) & needed
        if not types - seen:
            continue
        obj = state.new_object(prn, owner_id=0, zone=Zone.GRAVEYARD)
        p.graveyard.append(obj)
        seen.update(types)
        if seen >= needed:
            break
    assert seen >= needed
    static = StaticAbility(
        scope=StaticScope.SELF,
        power_bonus=1,
        toughness_bonus=1,
        granted_keywords=frozenset({"trample"}),
        requires_delirium=True,
    )
    assert static.applies_to(src, src, state) is True


def test_static_delirium_gate_requires_state_object():
    # ``state=None`` is the "unknown game state" signal every other
    # gate uses; the Delirium gate matches that convention by refusing
    # to apply when no state is available, rather than guessing or
    # raising.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.game import GameState, Player, Zone
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    src = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(src)
    static = StaticAbility(
        scope=StaticScope.SELF,
        power_bonus=1,
        toughness_bonus=1,
        requires_delirium=True,
    )
    assert static.applies_to(src, src, None) is False


def test_static_delirium_gate_ignores_opponent_graveyard():
    # Cards in an opponent's graveyard don't count toward the source
    # controller's Delirium threshold. With every needed type sitting
    # under an opponent, the source-side ability still doesn't apply.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.game import GameState, Player, Zone
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    opp = Player(id=1, agent=RandomAgent())
    state.players.append(opp)
    src = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(src)
    printings = OracleParserCardSource().get_printings()
    needed = {"Creature", "Sorcery", "Instant", "Land"}
    seen: set[str] = set()
    for prn in printings.values():
        types = set(prn.card_types) & needed
        if not types - seen:
            continue
        obj = state.new_object(prn, owner_id=1, zone=Zone.GRAVEYARD)
        opp.graveyard.append(obj)
        seen.update(types)
        if seen >= needed:
            break
    assert seen >= needed
    static = StaticAbility(
        scope=StaticScope.SELF,
        power_bonus=1,
        toughness_bonus=1,
        requires_delirium=True,
    )
    assert static.applies_to(src, src, state) is False


# ---------- end-to-end static-line parse ----------


def test_parse_delirium_trailing_static_line():
    # End-to-end through ``_parse_static_ability_line``. The
    # ``Delirium —`` ability-word prefix strips through the new
    # ``_strip_static_ability_word_prefix`` helper, then the trailing
    # ``as long as <gate>`` shape claims with the new
    # ``requires_delirium`` kwarg from the gate phrasebook.
    parsed = _parse_static_ability_line(
        "Delirium — This creature gets +1/+1 and has trample as long "
        "as there are four or more card types among cards in your "
        "graveyard."
    )
    assert parsed == StaticAbility(
        scope=StaticScope.SELF,
        power_bonus=1,
        toughness_bonus=1,
        granted_keywords=frozenset({"trample"}),
        requires_delirium=True,
    )


def test_parse_static_line_unrecognized_gate_after_delirium_prefix():
    # An unrecognized ``as long as`` gate phrase still rejects the
    # whole line even with the ``Delirium —`` prefix stripped — same
    # don't-silently-drop-the-gate discipline every other condition
    # arm uses. The stripper's job is purely surface peeling; the
    # gate phrasebook is the single source of truth for which
    # conditions are claimed.
    parsed = _parse_static_ability_line(
        "Delirium — This creature gets +1/+1 as long as the moon is full."
    )
    assert parsed is None


# ---------- end-to-end claim ----------


def test_wildfire_wickerfolk_claimed_by_parser():
    # Wildfire Wickerfolk ``{R}{G}`` 3/2 Artifact Creature — Scarecrow.
    # Two oracle lines: ``Haste`` and
    # ``Delirium — This creature gets +1/+1 and has trample as long as
    # there are four or more card types among cards in your graveyard.``
    # Claims via the existing keyword-line grammar for the first line
    # plus the new ability-word + Delirium-static gate combo for the
    # second.
    assert "Wildfire Wickerfolk" in _claimed_names()


def test_wildfire_wickerfolk_carries_delirium_static():
    # The claimed printing must actually carry the
    # ``requires_delirium=True`` field on its static ability so the
    # engine gates the +1/+1 / trample bonus on the four-card-types
    # threshold rather than applying it unconditionally.
    src = OracleParserCardSource()
    ww = src.get_printings()["Wildfire Wickerfolk"]
    assert "haste" in ww.keywords
    assert len(ww.static_abilities) == 1
    static = ww.static_abilities[0]
    assert static.power_bonus == 1
    assert static.toughness_bonus == 1
    assert static.granted_keywords == frozenset({"trample"})
    assert static.requires_delirium is True
