"""``mtg_bot.formats.decklist``: reading pasted decklists."""

from __future__ import annotations

from mtg_bot.formats.decklist import (
    Decklist,
    decklist_names,
    parse_decklist,
    resolve_names,
    tutor_names,
)


def test_counts_with_and_without_x():
    d = parse_decklist("4 Island\n3x Brainstorm\n2 X Ponder\nPredict\n")
    assert d.counts == {
        "Island": 4, "Brainstorm": 3, "Ponder": 2, "Predict": 1,
    }
    assert d.total == 10
    assert d.errors == ()


def test_repeated_lines_add_up_and_keep_order():
    d = parse_decklist("2 Island\n1 Dandân\n3 Island")
    assert d.counts == {"Island": 5, "Dandân": 1}
    assert list(d.counts) == ["Island", "Dandân"]
    assert d.names() == ["Island"] * 5 + ["Dandân"]


def test_arena_export_set_and_number_are_dropped():
    d = parse_decklist("Deck\n4 Island (M21) 263\n2 Memory Lapse (MIR) 70a\n")
    assert d.counts == {"Island": 4, "Memory Lapse": 2}


def test_comments_blank_lines_and_headers_are_skipped():
    d = parse_decklist(
        "# my fish list\n// another comment\n\nMain Deck:\n4 Island\n"
        "Commander\nCompanion\n"
    )
    assert d.counts == {"Island": 4}


def test_sideboard_header_ends_the_list():
    d = parse_decklist("4 Island\n\nSideboard\n2 Hydroblast\n")
    assert d.counts == {"Island": 4}


def test_zero_count_is_an_error():
    d = parse_decklist("0 Island\n4 Brainstorm")
    assert d.counts == {"Brainstorm": 4}
    assert d.errors == ("0 Island",)


def test_empty_text():
    d = parse_decklist("")
    assert d == Decklist(counts={})
    assert d.total == 0
    assert d.names() == []


def test_resolve_ignores_case_accents_and_apostrophes():
    d = parse_decklist("10 dandan\n2 Lat-Nam’s Legacy\n4 ISLAND")
    known = ["Dandân", "Lat-Nam's Legacy", "Island"]
    resolved, unknown = resolve_names(d, known)
    assert resolved == {"Dandân": 10, "Lat-Nam's Legacy": 2, "Island": 4}
    assert unknown == []


def test_resolve_matches_a_double_faced_front_face():
    d = parse_decklist("1 Delver of Secrets")
    resolved, unknown = resolve_names(
        d, ["Delver of Secrets // Insectile Aberration"],
    )
    assert resolved == {"Delver of Secrets // Insectile Aberration": 1}


def test_resolve_reports_unknown_names_as_written():
    d = parse_decklist("4 Island\n2 Not A Card")
    resolved, unknown = resolve_names(d, ["Island"])
    assert resolved == {"Island": 4}
    assert unknown == ["Not A Card"]


def test_decklist_names_against_printings():
    names, unknown, errors = decklist_names(
        "2 island\n1 Nope\n0 Bad", {"Island": object()},
    )
    assert names == ["Island", "Island"]
    assert unknown == ["Nope"]
    assert errors == ("0 Bad",)


_CARDS = [
    {"name": "Island", "oracle_text": "({T}: Add {U}.)"},
    {"name": "Brainstorm", "oracle_text": "Draw three cards, then put two "
     "cards from your hand on top of your library in any order."},
    {"name": "Mystical Tutor", "oracle_text": "Search your library for an "
     "instant or sorcery card, reveal it, then shuffle and put that card "
     "on top."},
    {"name": "Path to Exile", "oracle_text": "Exile target creature. Its "
     "controller may search their library for a basic land card, put that "
     "card onto the battlefield tapped, then shuffle."},
    {"name": "Split Tutor // Other Half", "card_faces": [
        {"name": "Split Tutor", "oracle_text": "Draw a card."},
        {"name": "Other Half", "oracle_text": "Search target player's "
         "library for a card."},
    ]},
]


def test_tutor_names_flags_cards_that_search_a_library():
    names = ["Island", "Mystical Tutor", "Brainstorm", "Path to Exile",
             "Mystical Tutor", "Split Tutor // Other Half"]
    assert tutor_names(names, _CARDS) == [
        "Mystical Tutor", "Path to Exile", "Split Tutor // Other Half",
    ]


def test_tutor_names_ignores_cards_without_a_record():
    assert tutor_names(["Unknown Card"], _CARDS) == []
    assert tutor_names(["Brainstorm", "Island"], _CARDS) == []
