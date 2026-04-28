"""Tests for the DSK creature ``This creature enters tapped.`` clause.

The engine has long carried the printing-level ``enters_tapped: bool``
field (consumed by ``actions.put_into_battlefield`` and
``effects/combinators.py``). What was missing was the parser side —
the ``creature_builder`` ``_parse_clause`` pipeline didn't recognize
the ``This creature enters tapped.`` line so any creature whose oracle
text included it stayed unclaimed. This batch adds the recognizer and
threads the flag through ``make_creature``.

Surfaces on Piranha Fly's two-line oracle text (``Flying`` + ``This
creature enters tapped.``); a future creature whose oracle text only
prints the line without other clauses would claim via the same path
without further grammar work.
"""

from __future__ import annotations

from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.cards.base import make_creature
from mtg_bot.cards.parser.printing_keywords import _parse_enters_tapped_line
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.game import GameState, Player, Zone


def _claimed_names() -> frozenset[str]:
    return frozenset(OracleParserCardSource().claimed_names)


# ---------- line recognizer ----------


def test_parse_enters_tapped_line_recognizes_canonical_form():
    # The verbatim Scryfall surface form. Whitespace tolerant — the
    # caller passes lines through ``_strip_reminder_text`` which
    # already strips trailing spaces, but the recognizer's own
    # ``.strip()`` is a belt-and-suspenders for hand-fed input.
    assert _parse_enters_tapped_line("This creature enters tapped.") is True


def test_parse_enters_tapped_line_rejects_other_forms():
    # Variants we DON'T match: missing period, the broader "This
    # permanent enters tapped" wording, or the printed-with-counters
    # variant. Each of those would land its own recognizer rather
    # than parameterizing this one — the strict 1:1 mapping mirrors
    # the ``Ward—Discard`` precedent.
    assert _parse_enters_tapped_line("This creature enters tapped") is False
    assert _parse_enters_tapped_line(
        "This permanent enters tapped."
    ) is False
    assert _parse_enters_tapped_line(
        "This creature enters tapped with a +1/+1 counter on it."
    ) is False
    assert _parse_enters_tapped_line("") is False


# ---------- make_creature kwarg threading ----------


def test_make_creature_threads_enters_tapped_flag():
    # Direct sanity check that the new ``enters_tapped=True`` kwarg
    # reaches the produced ``CardPrinting`` field. The default stays
    # ``False`` for every creature that doesn't pass the kwarg.
    p = make_creature("Test ETB Tapped", "{1}", 1, 1, enters_tapped=True)
    assert p.enters_tapped is True
    p_default = make_creature("Test Default", "{1}", 1, 1)
    assert p_default.enters_tapped is False


# ---------- end-to-end claim ----------


def test_piranha_fly_claimed_by_parser():
    # Piranha Fly ``{1}{U}`` 2/1 Fish Insect. Two oracle lines:
    # ``Flying`` (existing keyword) and ``This creature enters
    # tapped.`` (new printing-keyword recognizer). Claims via the
    # existing flying keyword grammar plus the new
    # ``_parse_enters_tapped_line`` recognizer flipping the
    # ``enters_tapped=True`` kwarg on ``make_creature``.
    assert "Piranha Fly" in _claimed_names()


def test_piranha_fly_carries_enters_tapped_flag():
    # The claimed printing must actually carry the field — without
    # the threading from the builder to ``make_creature`` to the
    # printing's ``enters_tapped`` field, the engine wouldn't tap
    # the creature on ETB even though the line was recognized.
    src = OracleParserCardSource()
    printings = {p.name: p for p in src.get_printings().values()}
    p = printings["Piranha Fly"]
    assert p.enters_tapped is True
    assert "flying" in p.keywords


# ---------- engine ETB-tap behavior (sanity, not coverage gain) ----------


def test_creature_with_enters_tapped_true_etbs_tapped():
    # Belt-and-suspenders that the engine's existing ETB-tapped path
    # actually fires for a creature flagged ``enters_tapped=True``.
    # Uses a tiny synthetic fixture rather than Piranha Fly so the
    # test stays decoupled from the parser claim above (a future
    # parity-test refactor that drops the Piranha Fly claim wouldn't
    # take this engine-side test out with it).
    from mtg_bot.actions import put_into_battlefield
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    printing = make_creature(
        "ETBTappedFixture", "{1}{U}", 2, 1,
        keywords={"flying"}, enters_tapped=True,
    )
    obj = state.new_object(printing, owner_id=0, zone=Zone.HAND)
    state.players[0].hand.append(obj)
    put_into_battlefield(state, obj, controller_id=0)
    assert obj.tapped is True
    assert obj in state.battlefield


def test_synthetic_vanilla_etbs_untapped_unchanged():
    # Belt-and-suspenders that adding the ``enters_tapped=`` kwarg
    # didn't accidentally flip the default for every other creature.
    # Wild Bear has no such flag on its printing; ETB stays untapped.
    from mtg_bot.actions import put_into_battlefield
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.HAND,
    )
    state.players[0].hand.append(bear)
    put_into_battlefield(state, bear, controller_id=0)
    assert bear.tapped is False
