"""Vintage Roto P3: Wistfulness ("if {G}{G} / {U}{U} was spent to cast
it" enters triggers, settled from the colors of the mana spent)."""

from __future__ import annotations

from mtg_bot.actions import CastSpell, apply_action, drain_stack
from mtg_bot.cards.base import make_artifact, make_basic_land
from mtg_bot.effects.generic import roto_mana as rm
from mtg_bot.game import ManaCoin

from tests._roto_helpers import arena, printing, put, to_hand, to_library

FOREST = make_basic_land("Forest", "G")
ISLAND = make_basic_land("Island", "U")
WIST = "Wistfulness"


def _cast(lands, *, evoke=False, pool=(), mode=None):
    s = arena()
    if mode is not None:
        s.players[0].agent.choose_mode = lambda state, pid, opts: mode
    for land in lands:
        put(s, land, 0)
    s.players[0].mana_pool.extend(pool)
    rock = put(s, make_artifact("Rock", "{1}"), 1)
    for _ in range(3):
        to_library(s, ISLAND, 0)
    to_hand(s, FOREST, 0)  # something to discard
    card = to_hand(s, printing(WIST), 0)
    s.players[0].agent.targets = [("permanent", rock.id), ("artifact", rock.id)]
    apply_action(s, 0, CastSpell(card.id, use_evoke=evoke))
    drain_stack(s)
    return s, card, rock


def test_wistfulness_hardcast_with_both_pairs_gets_both_triggers():
    s, card, rock = _cast([FOREST, FOREST, ISLAND, ISLAND, FOREST])
    assert card in s.battlefield
    assert rock not in s.battlefield  # GG: exiled the artifact
    assert len(s.players[0].hand) == 2  # UU: drew two, discarded one


def test_wistfulness_with_only_green_gets_the_exile():
    s, card, rock = _cast([FOREST] * 5)
    assert rock not in s.battlefield
    assert len(s.players[0].hand) == 1  # no loot


def test_evoked_with_two_flexible_mana_chooses_one_trigger():
    any2 = [ManaCoin(color="any"), ManaCoin(color="any")]
    s, card, rock = _cast([], evoke=True, pool=any2, mode=0)
    assert card.spent_color_choice == frozenset({("G", 2)})
    assert rock not in s.battlefield and len(s.players[0].hand) == 1
    assert card not in s.battlefield  # evoked: sacrificed
    s, card, rock = _cast([], evoke=True, pool=list(any2), mode=1)
    assert card.spent_color_choice == frozenset({("U", 2)})
    assert rock in s.battlefield and len(s.players[0].hand) == 2


def test_spent_mana_conditions_need_a_cast():
    from mtg_bot.actions import put_into_battlefield
    from mtg_bot.game import Zone

    s = arena()
    card = s.new_object(printing(WIST), owner_id=0, zone=Zone.GRAVEYARD)
    card.mana_spent_color_sources = (frozenset("G"), frozenset("G"))
    put_into_battlefield(s, card, 0)  # reanimated, not cast
    assert s.stack == []


def test_color_assignment_helpers():
    g, u, any_ = frozenset("G"), frozenset("U"), frozenset("WUBRG")
    assert rm._colors_assignable((g, g), (("G", 2),))
    assert not rm._colors_assignable((g, any_), (("G", 2), ("U", 1)))
    assert rm._colors_assignable((g, any_, u), (("G", 2), ("U", 1)))
    demands = rm._mana_spent_demands(printing(WIST))
    assert set(demands) == {("G", 2), ("U", 2)}
