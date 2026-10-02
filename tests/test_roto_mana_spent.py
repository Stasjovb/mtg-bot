"""Vintage Roto P3: mana-spent conditions (Together as One's converge,
Exhibition Tidecaller's Opus)."""

from __future__ import annotations

from mtg_bot.actions import CastSpell, apply_action, drain_stack
from mtg_bot.cards.base import make_basic_land
from mtg_bot.effects.generic import roto_mana as rm

from tests._roto_helpers import arena, printing, put, to_hand, to_library

LANDS = {
    c: make_basic_land(n, c)
    for c, n in (("W", "Plains"), ("U", "Island"), ("B", "Swamp"),
                 ("R", "Mountain"))
}


def test_together_as_one_scales_with_colors_spent():
    s = arena()
    for color in ("W", "U", "B", "W", "U", "B"):
        put(s, LANDS[color], 0)
    for _ in range(5):
        to_library(s, LANDS["R"], 0)
    one = to_hand(s, printing("Together as One"), 0)
    s.players[0].agent.targets = [("player", 0), ("player", 1)]
    apply_action(s, 0, CastSpell(one.id))
    assert one.mana_spent_to_cast == 6 and one.sunburst_colors_spent == 3
    drain_stack(s)
    assert len(s.players[0].hand) == 3
    assert s.players[1].life == 17
    assert s.players[0].life == 23


def test_together_as_one_with_colorless_mana_does_nothing():
    from mtg_bot.game import ManaCoin

    s = arena()
    s.players[0].mana_pool.extend(ManaCoin(color="C") for _ in range(6))
    one = to_hand(s, printing("Together as One"), 0)
    apply_action(s, 0, CastSpell(one.id))
    drain_stack(s)
    assert s.players[1].life == 20 and s.players[0].life == 20


def test_exhibition_tidecaller_mills_more_off_big_spells():
    s = arena()
    put(s, printing("Exhibition Tidecaller"), 0)
    for _ in range(20):
        to_library(s, LANDS["R"], 1)
    put(s, LANDS["R"], 0)
    bolt = to_hand(s, printing("Lightning Bolt"), 0)
    # The Bolt's target, then the Opus trigger's.
    s.players[0].agent.targets = [("player", 1), ("player", 1)]
    apply_action(s, 0, CastSpell(bolt.id))
    drain_stack(s)
    assert len(s.players[1].graveyard) == 3
    for color in ("W", "U", "B", "W", "U", "B"):
        put(s, LANDS[color], 0)
    one = to_hand(s, printing("Together as One"), 0)
    s.players[0].agent.targets = [("player", 1), ("player", 0), ("player", 1)]
    apply_action(s, 0, CastSpell(one.id))
    drain_stack(s)
    assert len(s.players[1].graveyard) == 13


def test_mana_spent_helpers():
    eff = rm.MillTargetPlayerMoreIfManaSpent(
        amount=3, amount_if_spent=10, mana_spent_at_least=5,
    )
    assert "10" in eff.describe()
    assert eff.event_subject_id({}) == -1
    s = arena()
    assert rm._object_by_id(s, 12345) is None
    assert "colors of mana" in printing("Together as One").spell_effect.describe()
