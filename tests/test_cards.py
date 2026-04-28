from mtg_bot.cards import BASIC_LANDS, ManaCost, SYNTHETIC_CREATURES, parse_mana_cost

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


def test_parse_empty_cost():
    assert parse_mana_cost("") == ManaCost()


def test_parse_generic_only():
    c = parse_mana_cost("{3}")
    assert c.generic == 3
    assert c.colored == ()
    assert c.total == 3


def test_parse_mixed_cost():
    c = parse_mana_cost("{2}{G}{G}")
    assert c.generic == 2
    assert c.colored == (("G", 2),)
    assert c.total == 4
    assert c.colors == {"G"}


def test_parse_multicolor():
    c = parse_mana_cost("{W}{U}{B}{R}{G}")
    assert c.generic == 0
    assert c.total == 5
    assert c.colors == {"W", "U", "B", "R", "G"}


def test_basic_land_produces_one_color():
    forest = BASIC_LANDS["Forest"]
    assert forest.is_land
    assert forest.is_basic_land
    assert forest.produces == frozenset({"G"})


def test_creature_has_power_toughness():
    bear = SYNTHETIC_CREATURES["Wild Bear"]
    assert bear.is_creature
    assert bear.power == 2
    assert bear.toughness == 2


def test_creature_defaults_to_no_keywords():
    bear = SYNTHETIC_CREATURES["Wild Bear"]
    assert bear.keywords == frozenset()


def test_make_creature_accepts_keywords():
    from mtg_bot.cards import make_creature
    c = make_creature("Test Flier", "{1}{U}", 2, 2, keywords={"flying", "vigilance"})
    assert c.keywords == frozenset({"flying", "vigilance"})


def test_make_creature_keywords_from_tuple():
    from mtg_bot.cards import make_creature
    c = make_creature("Test", "{R}", 1, 1, keywords=("haste",))
    assert "haste" in c.keywords


def test_build_deck_is_60_cards():
    deck = get_active_source().build_mono_color_deck("G", seed=1)
    assert len(deck) == 60
    assert deck.count("Forest") == 24
    # Every non-Forest card must be a card in the pool whose color is either
    # green or colorless (colorless cards get included in any mono-color deck).
    for name in deck:
        if name == "Forest":
            continue
        assert name in _PRINTINGS
        colors = _PRINTINGS[name].mana_cost.colors
        assert "G" in colors or not colors


def test_build_deck_is_deterministic_with_seed():
    assert get_active_source().build_mono_color_deck("R", seed=7) == get_active_source().build_mono_color_deck("R", seed=7)
