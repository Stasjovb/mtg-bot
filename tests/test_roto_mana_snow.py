"""Vintage Roto P3: snow and Dark Depths (state triggers, self-named
counter lines)."""

from __future__ import annotations

from mtg_bot.actions import (
    ActivateAbility,
    PlayLand,
    _activate_ability,
    apply_action,
    drain_stack,
    resolve_top_of_stack,
)
from mtg_bot.cards.base import make_basic_land
from mtg_bot.cards.parser.roto_mana import parse_roto_land_line
from mtg_bot.effects.generic import roto_mana as rm
from mtg_bot.game import counter_count, effective_keywords, set_named_counters
from mtg_bot.legal import legal_actions
from mtg_bot.turn import state_based_actions

from tests._roto_helpers import arena, printing, put, to_hand

MOUNTAIN = make_basic_land("Mountain", "R")


def _depths_in_play(ice=10):
    s = arena()
    depths = to_hand(s, printing("Dark Depths"), 0)
    apply_action(s, 0, PlayLand(depths.id))
    set_named_counters(depths, "ice", ice)
    return s, depths


def test_dark_depths_is_a_legendary_snow_land_entering_with_ten_ice():
    pr = printing("Dark Depths")
    assert set(pr.supertypes) == {"Legendary", "Snow"}
    assert pr.type_line == "Legendary Snow Land"
    assert pr.produces == frozenset() and pr.mana_only_from_produces
    s = arena()
    depths = to_hand(s, pr, 0)
    apply_action(s, 0, PlayLand(depths.id))
    assert counter_count(depths, "ice") == 10


def test_dark_depths_removes_an_ice_counter_for_three():
    s, depths = _depths_in_play()
    for _ in range(3):
        put(s, MOUNTAIN, 0)
    act = ActivateAbility(source_id=depths.id, ability_index=0)
    assert act in legal_actions(s, 0)
    apply_action(s, 0, act)
    drain_stack(s)
    assert counter_count(depths, "ice") == 9


def test_dark_depths_makes_marit_lage_when_the_last_ice_counter_goes():
    s, depths = _depths_in_play(ice=1)
    for _ in range(3):
        put(s, MOUNTAIN, 0)
    _activate_ability(s, 0, depths.id, 0)
    resolve_top_of_stack(s)
    state_based_actions(s)
    assert len(s.stack) == 1  # the state trigger
    state_based_actions(s)
    assert len(s.stack) == 1  # it doesn't trigger again while waiting
    resolve_top_of_stack(s)
    assert depths not in s.battlefield
    lage = next(o for o in s.battlefield if o.printing.name == "Marit Lage")
    assert (lage.printing.power, lage.printing.toughness) == (20, 20)
    assert lage.printing.is_legendary
    assert {"flying", "indestructible"} <= effective_keywords(s, lage)


def test_no_marit_lage_if_dark_depths_already_left():
    s, depths = _depths_in_play(ice=0)
    state_based_actions(s)
    assert len(s.stack) == 1
    s.battlefield.remove(depths)  # gone before the trigger resolves
    resolve_top_of_stack(s)
    assert not any(o.printing.name == "Marit Lage" for o in s.battlefield)


def test_counter_effects_guard_and_describe():
    eff = rm.RemoveCountersFromSource(kind="ice", amount=1)
    assert "ice" in eff.describe()
    s = arena()
    s.resolving_source = None
    eff.resolve(s, 0, ())
    sac = rm.SacrificeSourceThen(then_effect=eff)
    assert "sacrifice it" in sac.describe()
    sac.resolve(s, 0, ())


def test_land_line_hook_paths():
    assert parse_roto_land_line(
        "Other Card enters with ten ice counters on it.", "Dark Depths",
    ) is None
    assert parse_roto_land_line(
        "Dark Depths enters with lots ice counters on it.", "Dark Depths",
    ) is None
    assert parse_roto_land_line(
        "When Dark Depths has no ice counters on it, frobnicate.",
        "Dark Depths",
    ) is None
    line = parse_roto_land_line(
        "This land enters with 3 ice counters on it.".replace(
            "This land", "Dark Depths"), "Dark Depths",
    )
    assert line.fields == {"enters_with_named_counters": (("ice", 3),)}
    assert parse_roto_land_line("{T}: Frobnicate Dark Depths.", "Dark Depths") is None


# ---------------------------------------------------------------------------
# Snow mana and {S} (Arcum's Astrolabe)
# ---------------------------------------------------------------------------


def _snow_island():
    from dataclasses import replace

    return replace(
        make_basic_land("Snow-Covered Island", "U"),
        supertypes=("Basic", "Snow"),
        type_line="Basic Snow Land — Island",
    )


def test_snow_mana_symbol_parses_as_a_non_color_pip():
    from mtg_bot.cards.base import parse_mana_cost

    cost = parse_mana_cost("{S}")
    assert cost.total == 1 and cost.colors == frozenset()
    pr = printing("Arcum's Astrolabe")
    assert pr.supertypes == ("Snow",) and pr.mana_cost.total == 1


def test_astrolabe_needs_snow_mana():
    from mtg_bot.actions import CastSpell
    from mtg_bot.game import ManaCoin

    s = arena()
    put(s, MOUNTAIN, 0)
    astro = to_hand(s, printing("Arcum's Astrolabe"), 0)
    s.players[0].mana_pool.append(ManaCoin(color="any"))
    assert CastSpell(astro.id) not in legal_actions(s, 0)
    s.players[0].mana_pool.append(ManaCoin(color="U", snow=True))
    assert CastSpell(astro.id) in legal_actions(s, 0)
    apply_action(s, 0, CastSpell(astro.id))
    assert [c.snow for c in s.players[0].mana_pool] == [False]


def test_astrolabe_cast_off_a_snow_land_draws_and_makes_snow_mana():
    from mtg_bot.actions import CastSpell
    from tests._roto_helpers import to_library

    s = arena()
    island = put(s, _snow_island(), 0)
    put(s, MOUNTAIN, 0)
    put(s, MOUNTAIN, 0)
    to_library(s, MOUNTAIN, 0)
    astro = to_hand(s, printing("Arcum's Astrolabe"), 0)
    apply_action(s, 0, CastSpell(astro.id))
    assert island.tapped  # the snow land paid {S}
    drain_stack(s)  # the spell, then its ETB draw
    assert astro in s.battlefield and len(s.players[0].hand) == 1
    _activate_ability(s, 0, astro.id, 0)
    coins = s.players[0].mana_pool
    assert len(coins) == 1 and coins[0].snow and coins[0].color == "any"


def test_nonsnow_sources_never_pay_snow():
    from mtg_bot.actions import _coin_matches_color, _produces_satisfies
    from mtg_bot.game import ManaCoin

    assert not _coin_matches_color(ManaCoin(color="any"), "S")
    assert _coin_matches_color(ManaCoin(color="G", snow=True), "S")
    assert _coin_matches_color(ManaCoin(color="G", snow=True), "G")
    assert not _produces_satisfies((("any", 1),), "S")


def test_after_mana_ability_marks_only_snow_sources():
    from mtg_bot.game import ManaCoin

    s = arena()
    plain = put(s, MOUNTAIN, 0)
    s.players[0].mana_pool.append(ManaCoin(color="R"))
    rm.after_mana_ability(s, 0, plain, 0)
    assert not s.players[0].mana_pool[0].snow
    snowy = put(s, _snow_island(), 0)
    rm.after_mana_ability(s, 0, snowy, 0)
    assert s.players[0].mana_pool[0].snow


def test_blood_moon_stops_dark_depths_state_trigger():
    # The state trigger is a board rule (one mechanism with Drop of
    # Honey's): under Blood Moon, Dark Depths is a Mountain with no
    # abilities, so having no ice counters makes no Marit Lage.
    s, depths = _depths_in_play(ice=0)
    moon = put(s, printing("Blood Moon"), 1)
    state_based_actions(s)
    assert not s.stack
    s.battlefield.remove(moon)
    state_based_actions(s)
    assert len(s.stack) == 1


def test_dark_depths_state_trigger_describes_its_condition():
    (rule,) = printing("Dark Depths").board_rules
    assert rule.describe().startswith(
        "When this permanent has no ice counters on it, sacrifice"
    )
