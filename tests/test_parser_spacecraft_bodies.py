"""Parser support for Spacecraft body abilities — slice 2: a single
``"When this Spacecraft enters, <effect>."`` ETB trigger alongside the
Station + tier-keyword pair already claimed by slice 1.

Slice 1 (``test_parser_spacecraft_builder.py``) covers the bare
Station + tier-keyword shape and the negative cases for cards that
fall outside the body-less grammar. This file focuses on the new
ETB-trigger arm: the cards it newly claims (Wedgelight Rammer,
Wurmwall Sweeper) plus the negatives that keep adjacent body-ability
shapes — multiple triggers, attack triggers, non-trigger clauses —
out of scope for this slice.

Wedgelight Rammer's ``"create a 2/2 colorless Robot artifact creature
token"`` and Wurmwall Sweeper's ``"surveil 2"`` are both effects whose
phrase already resolves through ``_parse_effect_phrase``, so the
parser-built printing equals the static one byte-for-byte without any
new effect-grammar work — the only new code lives in the spacecraft
builder.
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    TriggeredAbility,
    make_spacecraft,
)
from mtg_bot.cards.parser.spacecraft_builder import (
    _build_spacecraft_printing,
)
from mtg_bot.cards.parser_source import OracleParserCardSource
from mtg_bot.cards.source import StaticCardSource
from mtg_bot.effects.generic import (
    CreateToken,
    Surveil,
)
from mtg_bot.effects.predicates import Event, IsSelf
from mtg_bot.cards.tokens import TOKEN_PRINTINGS


_WEDGELIGHT_RAMMER_CARD = {
    "name": "Wedgelight Rammer",
    "mana_cost": "{3}{W}",
    "type_line": "Artifact — Spacecraft",
    "power": "3",
    "toughness": "4",
    "oracle_text": (
        "When this Spacecraft enters, create a 2/2 colorless Robot "
        "artifact creature token.\n"
        "Station (Tap another creature you control: Put charge counters "
        "equal to its power on this Spacecraft. Station only as a "
        "sorcery. It's an artifact creature at 9+.)\n"
        "9+ | Flying, first strike"
    ),
}

_WURMWALL_SWEEPER_CARD = {
    "name": "Wurmwall Sweeper",
    "mana_cost": "{2}",
    "type_line": "Artifact — Spacecraft",
    "power": "2",
    "toughness": "2",
    "oracle_text": (
        "When this Spacecraft enters, surveil 2.\n"
        "Station (Tap another creature you control: Put charge counters "
        "equal to its power on this Spacecraft. Station only as a "
        "sorcery. It's an artifact creature at 4+.)\n"
        "4+ | Flying"
    ),
}


def test_build_spacecraft_printing_claims_wedgelight_rammer():
    """The Wedgelight Rammer Scryfall record builds a white Spacecraft
    with station_threshold=9, stationed_keywords={flying, first strike},
    and a single self-ETB ``CreateToken(Robot)`` trigger - exactly what
    the static registry passes to ``make_spacecraft``."""
    printing = _build_spacecraft_printing(_WEDGELIGHT_RAMMER_CARD)
    assert printing is not None
    assert printing.name == "Wedgelight Rammer"
    assert "Spacecraft" in printing.subtypes
    assert "Artifact" in printing.card_types
    assert printing.power == 3
    assert printing.toughness == 4
    assert printing.station_threshold == 9
    assert printing.stationed_keywords == frozenset(
        {"flying", "first strike"}
    )
    assert len(printing.triggered_abilities) == 1
    trig = printing.triggered_abilities[0]
    assert trig.event == Event.ENTERS
    assert trig.predicate == IsSelf()
    assert trig.effect == CreateToken(
        token_printing=TOKEN_PRINTINGS["Robot"], count=1,
    )
    # No statics, no activated abilities - this slice claims only the
    # ETB-trigger shape.
    assert printing.static_abilities == ()
    assert printing.activated_abilities == ()


def test_build_spacecraft_printing_claims_wurmwall_sweeper():
    """Wurmwall Sweeper's surveil-2 ETB is a different effect family
    (graveyard-mill / library-look) than Wedgelight Rammer's token
    create, but flows through the same ``_parse_clause`` arm and lands
    as a single ``TriggeredAbility(event=ENTERS, predicate=IsSelf(),
    effect=Surveil(amount=2))``."""
    printing = _build_spacecraft_printing(_WURMWALL_SWEEPER_CARD)
    assert printing is not None
    assert printing.name == "Wurmwall Sweeper"
    assert printing.station_threshold == 4
    assert printing.stationed_keywords == frozenset({"flying"})
    assert len(printing.triggered_abilities) == 1
    trig = printing.triggered_abilities[0]
    assert trig.event == Event.ENTERS
    assert trig.predicate == IsSelf()
    assert trig.effect == Surveil(amount=2)


def test_build_spacecraft_printing_matches_static_wedgelight_rammer():
    """Per-card parity with the canonical static registry. The parser-
    built printing must equal what ``make_spacecraft`` produces with
    the same arguments - the parity gate in ``test_parser_parity.py``
    asserts the same property at the source level, but pinning it
    here gives faster feedback when the static card and the parser
    drift."""
    parsed = _build_spacecraft_printing(_WEDGELIGHT_RAMMER_CARD)
    expected = make_spacecraft(
        "Wedgelight Rammer", "{3}{W}", 3, 4,
        station_threshold=9,
        stationed_keywords={"flying", "first strike"},
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS, predicate=IsSelf(),
                effect=CreateToken(
                    token_printing=TOKEN_PRINTINGS["Robot"], count=1,
                ),
            ),
        ),
    )
    assert parsed == expected


def test_build_spacecraft_printing_matches_static_wurmwall_sweeper():
    """Same byte-equality parity check for Wurmwall Sweeper - covers
    the surveil-effect arm of the new trigger handling."""
    parsed = _build_spacecraft_printing(_WURMWALL_SWEEPER_CARD)
    expected = make_spacecraft(
        "Wurmwall Sweeper", "{2}", 2, 2,
        station_threshold=4,
        stationed_keywords={"flying"},
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS, predicate=IsSelf(),
                effect=Surveil(amount=2),
            ),
        ),
    )
    assert parsed == expected


def test_build_spacecraft_printing_skips_attack_trigger():
    """A Spacecraft with an attack trigger (like Specimen Freighter's
    defender-mill or Sledge-Class Seedship's free-creature-into-play)
    is a non-ETB trigger shape this slice doesn't model. Even if the
    attack-trigger effect happened to parse, the builder rejects any
    trigger whose event isn't ``Event.ENTERS`` so we don't mis-wire it
    as an ETB."""
    card = {
        "name": "Hand-Crafted Attack-Trigger Spacecraft",
        "mana_cost": "{2}",
        "type_line": "Artifact — Spacecraft",
        "power": "2",
        "toughness": "2",
        "oracle_text": (
            "Whenever this Spacecraft attacks, surveil 2.\n"
            "Station (Tap another creature you control: Put charge "
            "counters equal to its power on this Spacecraft. Station "
            "only as a sorcery. It's an artifact creature at 4+.)\n"
            "4+ | Flying"
        ),
    }
    assert _build_spacecraft_printing(card) is None


def test_build_spacecraft_printing_skips_two_etb_triggers():
    """A Spacecraft with two ETB trigger lines is out of scope for this
    slice - claiming only the first would silently drop the second.
    No EoE Spacecraft prints two ETB lines today, but the defensive
    skip means a future printing won't be half-claimed."""
    card = {
        "name": "Hand-Crafted Double-ETB Spacecraft",
        "mana_cost": "{2}",
        "type_line": "Artifact — Spacecraft",
        "power": "2",
        "toughness": "2",
        "oracle_text": (
            "When this Spacecraft enters, surveil 2.\n"
            "When this Spacecraft enters, create a 2/2 colorless Robot "
            "artifact creature token.\n"
            "Station (Tap another creature you control: Put charge "
            "counters equal to its power on this Spacecraft. Station "
            "only as a sorcery. It's an artifact creature at 4+.)\n"
            "4+ | Flying"
        ),
    }
    assert _build_spacecraft_printing(card) is None


def test_build_spacecraft_printing_skips_etb_plus_attack_trigger():
    """A Spacecraft that pairs an ETB with an attack trigger (Specimen
    Freighter-shaped: ETB returns creatures, attack trigger mills the
    defender) skips because the attack trigger line either fails
    ``_parse_clause`` outright or returns a non-ENTERS trigger - either
    way the per-line dispatch bails on the attack line."""
    card = {
        "name": "Hand-Crafted ETB-Plus-Attack Spacecraft",
        "mana_cost": "{5}{U}",
        "type_line": "Artifact — Spacecraft",
        "power": "4",
        "toughness": "3",
        "oracle_text": (
            "When this Spacecraft enters, surveil 2.\n"
            "Station (Tap another creature you control: Put charge "
            "counters equal to its power on this Spacecraft. Station "
            "only as a sorcery. It's an artifact creature at 9+.)\n"
            "9+ | Flying\n"
            "Whenever this Spacecraft attacks, surveil 2."
        ),
    }
    assert _build_spacecraft_printing(card) is None


def test_build_spacecraft_printing_skips_clause_returning_static():
    """A Spacecraft whose body line parses through ``_parse_clause`` to
    something other than a trigger (e.g. a bare keyword line that the
    keyword parser claims, or a static ability) is not the shape this
    slice claims. The builder accepts only triggers from
    ``_parse_clause``; anything else skips the whole card to avoid
    silently dropping or mis-wiring the ability."""
    # A standalone "Flying" line on a Spacecraft is grammatically odd
    # (Spacecraft grant keywords through tier lines, not bare lines),
    # but ``_parse_keyword_line`` will recognize it. The builder must
    # reject the non-trigger clause.
    card = {
        "name": "Hand-Crafted Bare-Keyword-Line Spacecraft",
        "mana_cost": "{2}",
        "type_line": "Artifact — Spacecraft",
        "power": "2",
        "toughness": "2",
        "oracle_text": (
            "Flying\n"
            "Station (Tap another creature you control: Put charge "
            "counters equal to its power on this Spacecraft. Station "
            "only as a sorcery. It's an artifact creature at 4+.)\n"
            "4+ | Flying"
        ),
    }
    assert _build_spacecraft_printing(card) is None


def test_source_claims_wedgelight_rammer_and_wurmwall_sweeper():
    """End-to-end: ``OracleParserCardSource`` walks the cached EoE
    Scryfall data and now claims both new Spacecraft alongside the
    slice-1 Galvanizing Sawship via the extended spacecraft-builder
    arm."""
    source = OracleParserCardSource()
    claimed = set(source.claimed_names)
    assert "Wedgelight Rammer" in claimed
    assert "Wurmwall Sweeper" in claimed
    # Slice-1 claim still in place.
    assert "Galvanizing Sawship" in claimed


def test_parity_wedgelight_rammer_and_wurmwall_sweeper():
    """Per-card parity: the parser-built printings for both newly-
    claimed Spacecraft must equal the static registry's copies. This
    is also asserted by the parametrized parity gate, but pinning it
    here surfaces drift in this batch's specific cards immediately."""
    parser_printings = OracleParserCardSource().get_printings()
    static_printings = StaticCardSource().get_printings()
    for name in ("Wedgelight Rammer", "Wurmwall Sweeper"):
        assert parser_printings[name] == static_printings[name]
