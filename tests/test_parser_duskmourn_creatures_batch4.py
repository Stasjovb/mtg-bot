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


# ---------- ``basic_land`` SearchLibraryForCard filter ----------


def test_search_library_for_card_basic_land_filter_matches_basics():
    # ``filter_name="basic_land"`` matches every basic land printing —
    # Plains / Island / Swamp / Mountain / Forest. Belt-and-suspenders
    # that the new generic filter covers the full set rather than
    # accidentally pinning a single basic by name.
    from mtg_bot.cards import BASIC_LANDS
    from mtg_bot.effects.generic import SearchLibraryForCard
    eff = SearchLibraryForCard(filter_name="basic_land")
    for basic in ("Plains", "Island", "Swamp", "Mountain", "Forest"):
        assert eff._matches(BASIC_LANDS[basic]) is True


def test_search_library_for_card_basic_land_filter_rejects_nonbasic():
    # The ``basic_land`` filter must NOT match a non-basic land
    # (Terramorphic Expanse) or a non-land (Wild Bear). Pinning the
    # rejection here keeps a future regression where ``basic_land`` got
    # widened to ``is_land`` from going unnoticed.
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.effects.generic import SearchLibraryForCard
    eff = SearchLibraryForCard(filter_name="basic_land")
    printings = OracleParserCardSource().get_printings()
    if "Terramorphic Expanse" in printings:
        assert eff._matches(printings["Terramorphic Expanse"]) is False
    assert eff._matches(SYNTHETIC_CREATURES["Wild Bear"]) is False


def test_parse_search_library_for_basic_land_card_phrase():
    # End-to-end through the effect-phrase parser. The phrase
    # ``search your library for a basic land card, reveal it, put it
    # into your hand, then shuffle`` parses to
    # ``SearchLibraryForCard(filter_name="basic_land", may_fail=True)``.
    from mtg_bot.cards.parser.effects import _parse_effect_phrase
    from mtg_bot.effects.generic import SearchLibraryForCard
    parsed = _parse_effect_phrase(
        "search your library for a basic land card, reveal it, "
        "put it into your hand, then shuffle"
    )
    assert parsed == SearchLibraryForCard(
        filter_name="basic_land", may_fail=True,
    )


def test_spineseeker_centipede_claimed_by_parser():
    # Spineseeker Centipede ``{2}{G}`` 2/1 Insect. Two oracle lines:
    # ``When this creature enters, search your library for a basic
    # land card, reveal it, put it into your hand, then shuffle.``
    # and ``Delirium — This creature gets +1/+2 and has vigilance as
    # long as there are four or more card types among cards in your
    # graveyard.`` Claims via the existing ETB-trigger grammar fed by
    # the new ``basic_land`` SearchLibraryForCard filter, plus the new
    # Delirium static gate from the Wildfire Wickerfolk slice.
    assert "Spineseeker Centipede" in _claimed_names()


def test_spineseeker_centipede_carries_basic_land_etb_and_delirium_static():
    # Belt-and-suspenders that the claimed printing actually wires the
    # new ``basic_land`` filter into its ETB trigger and the
    # ``requires_delirium=True`` field into its static — otherwise the
    # parser could mis-claim the card with a different effect that
    # passed the surface-text gate.
    from mtg_bot.effects.generic import SearchLibraryForCard
    src = OracleParserCardSource()
    sc = src.get_printings()["Spineseeker Centipede"]
    assert len(sc.triggered_abilities) == 1
    trig = sc.triggered_abilities[0]
    assert trig.effect == SearchLibraryForCard(
        filter_name="basic_land", may_fail=True,
    )
    assert len(sc.static_abilities) == 1
    static = sc.static_abilities[0]
    assert static.power_bonus == 1
    assert static.toughness_bonus == 2
    assert static.granted_keywords == frozenset({"vigilance"})
    assert static.requires_delirium is True
