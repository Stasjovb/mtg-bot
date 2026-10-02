"""Vintage Roto P2, F12 graveyard hate: Rest in Peace, Sanctifier en-Vec,
Bojuka Bog and the exile-instead replacement they (and Leyline of the
Void's shape) share."""

from __future__ import annotations

from mtg_bot import apply
from mtg_bot.actions import (
    CastSpell,
    _send_to_graveyard_or_library,
    drain_stack,
    put_into_battlefield,
)
from mtg_bot.cards import BASIC_LANDS, make_creature
from mtg_bot.cards.base import make_enchantment
from mtg_bot.cards.parser.roto_zones import (
    parse_roto_zones_creature_line,
    parse_roto_zones_effect,
    parse_roto_zones_static_line,
)
from mtg_bot.cards.tokens import TOKEN_PRINTINGS
from mtg_bot.effects.generic import DiscardSelf
from mtg_bot.effects.generic.roto_zones import (
    ExileGraveyardCardsOfColors,
    ExileTargetPlayersGraveyard,
    GraveyardExileInstead,
    apply_graveyard_exile_instead,
    graveyard_exile_instead_applies,
    put_into_graveyard,
)
from mtg_bot.game import Zone
from mtg_bot.turn import move_off_battlefield, state_based_actions

from tests._roto_helpers import (
    agent,
    arena,
    printing,
    put,
    to_graveyard,
    to_hand,
    to_library,
)


BEAR = make_creature("Test Bear", "{1}{G}", 2, 2)
ZOMBIE = make_creature("Test Zombie", "{1}{B}", 2, 2)
GOBLIN = make_creature("Test Goblin", "{R}", 1, 1)


def _enter(state, pr, controller=0):
    obj = state.new_object(pr, owner_id=controller, zone=Zone.STACK)
    put_into_battlefield(state, obj, controller)
    return obj


def _names(zone):
    return sorted(c.printing.name for c in zone)


def _leyline_like(opponents_only=True, tokens=False, colors=frozenset()):
    return _with_spec(
        make_enchantment("Test Leyline", "{2}{B}{B}"),
        GraveyardExileInstead(opponents_only, tokens, colors),
    )


def _with_spec(pr, spec):
    import dataclasses

    return dataclasses.replace(pr, zone_abilities=(spec,))


# --- grammar --------------------------------------------------------------------

def test_static_line_grammar():
    rip = parse_roto_zones_static_line(
        "If a card or token would be put into a graveyard from anywhere, "
        "exile it instead.", "",
    )["zone_abilities"][0]
    assert rip == GraveyardExileInstead(tokens=True)
    leyline = parse_roto_zones_static_line(
        "If a card would be put into an opponent's graveyard from anywhere, "
        "exile it instead.", "",
    )["zone_abilities"][0]
    assert leyline == GraveyardExileInstead(opponents_only=True)
    sanct = parse_roto_zones_static_line(
        "If a black or red permanent, spell, or card not on the battlefield "
        "would be put into a graveyard, exile it instead.", "",
    )["zone_abilities"][0]
    assert sanct.colors == frozenset({"B", "R"}) and sanct.tokens
    assert "opponent's" in leyline.describe() and "B or R" in sanct.describe()
    assert "card or token" in rip.describe()
    hand = parse_roto_zones_static_line(
        "If this card is in your opening hand, you may begin the game with it "
        "on the battlefield.", "",
    )
    assert "opening_hand_action" in hand
    assert parse_roto_zones_static_line("Flying", "") is None
    assert parse_roto_zones_creature_line("Flying", {"name": "X"}) is None
    assert parse_roto_zones_effect("exile all cards that are green from all "
                                   "graveyards") == ExileGraveyardCardsOfColors(
        colors=frozenset({"G"}))


def test_enchantment_line_merges_fields():
    from mtg_bot.cards.parser.roto_zones import _merge_fields

    into = {}
    assert _merge_fields(into, {"zone_abilities": (1,)})
    assert _merge_fields(into, {"zone_abilities": (2,)})
    assert into["zone_abilities"] == (1, 2)
    assert _merge_fields(into, {"opening_hand_action": 1})
    assert not _merge_fields(into, {"opening_hand_action": 2})


# --- Rest in Peace ------------------------------------------------------------

def test_rest_in_peace_exiles_graveyards_on_entry():
    state = arena()
    old0 = to_graveyard(state, BEAR)
    old1 = to_graveyard(state, ZOMBIE, owner=1)
    _enter(state, printing("Rest in Peace"))
    drain_stack(state)
    assert old0 in state.players[0].exile and old1 in state.players[1].exile
    assert state.players[0].graveyard == [] == state.players[1].graveyard


def test_rest_in_peace_dying_creature_is_exiled_and_never_dies():
    state = arena()
    put(state, printing("Rest in Peace"))
    hulk = put(state, printing("Protean Hulk"), 1)
    to_library(state, BEAR, owner=1)
    move_off_battlefield(state, hulk, "graveyard")
    drain_stack(state)
    assert hulk in state.players[1].exile
    # No dies trigger: the Bear is still in the library.
    assert len(state.players[1].library) == 1


def test_rest_in_peace_tokens_never_die():
    state = arena()
    put(state, printing("Rest in Peace"))
    token = state.new_object(TOKEN_PRINTINGS["Treasure"], owner_id=0,
                             zone=Zone.BATTLEFIELD)
    state.battlefield.append(token)
    assert graveyard_exile_instead_applies(state, token)
    move_off_battlefield(state, token, "graveyard")
    assert token not in state.battlefield
    assert token not in state.players[0].graveyard


def test_rest_in_peace_resolved_spell_and_discard_are_exiled():
    state = arena()
    put(state, printing("Rest in Peace"))
    for _ in range(2):
        put(state, BASIC_LANDS["Swamp"])
    to_library(state, BEAR)
    grave = to_hand(state, printing("Unmarked Grave"))
    apply(state, CastSpell(card_id=grave.id), 0)
    drain_stack(state)
    p = state.players[0]
    # Unmarked Grave itself and the Bear it put into the graveyard.
    assert grave in p.exile
    state_based_actions(state)
    assert p.graveyard == []
    assert _names(p.exile) == ["Test Bear", "Unmarked Grave"]
    card = to_hand(state, ZOMBIE, owner=1)
    DiscardSelf().resolve(state, 1)
    assert card in state.players[1].graveyard
    state_based_actions(state)
    assert card in state.players[1].exile


def test_spell_copies_are_not_affected():
    state = arena()
    put(state, printing("Rest in Peace"))
    copy = state.new_object(BEAR, owner_id=0, zone=Zone.STACK)
    copy.is_spell_copy = True
    assert not graveyard_exile_instead_applies(state, copy)


def test_cards_already_in_graveyard_stay_until_etb_resolves():
    state = arena()
    old = to_graveyard(state, BEAR)
    rip = state.new_object(printing("Rest in Peace"), owner_id=0,
                           zone=Zone.STACK)
    put_into_battlefield(state, rip, 0)
    assert apply_graveyard_exile_instead(state) is False
    assert old in state.players[0].graveyard
    drain_stack(state)
    assert old in state.players[0].exile


def test_card_returning_to_graveyard_is_caught_by_the_sweep():
    state = arena()
    old = to_graveyard(state, BEAR)
    put(state, _leyline_like(opponents_only=False))
    from mtg_bot.effects.generic.roto_zones import (
        note_exile_instead_source_entered,
    )

    note_exile_instead_source_entered(state, state.battlefield[-1])
    p = state.players[0]
    p.graveyard.remove(old)
    old.zone = Zone.HAND
    p.hand.append(old)
    assert apply_graveyard_exile_instead(state) is False
    p.hand.remove(old)
    old.zone = Zone.GRAVEYARD
    p.graveyard.append(old)
    assert apply_graveyard_exile_instead(state) is True
    assert old in p.exile


def test_source_without_abilities_does_not_apply():
    state = arena()
    rip = put(state, printing("Rest in Peace"))
    bear = put(state, BEAR, 1)
    assert graveyard_exile_instead_applies(state, bear)
    state.add_continuous_effect(
        source_id=rip.id, layer=6, kind="lose_all_abilities",
        target_id=rip.id,
    )
    assert not graveyard_exile_instead_applies(state, bear)


# --- Leyline of the Void's shape (opponents only, cards only) ---------------------

def test_opponents_only_replacement_spares_own_cards_and_tokens():
    state = arena()
    put(state, _leyline_like())
    mine = put(state, BEAR, 0)
    theirs = put(state, ZOMBIE, 1)
    token = state.new_object(TOKEN_PRINTINGS["Treasure"], owner_id=1,
                             zone=Zone.BATTLEFIELD)
    assert not graveyard_exile_instead_applies(state, mine)
    assert graveyard_exile_instead_applies(state, theirs)
    assert not graveyard_exile_instead_applies(state, token)
    card = state.new_object(BEAR, owner_id=1, zone=Zone.STACK)
    _send_to_graveyard_or_library(state, card)
    assert card in state.players[1].exile
    mine_card = state.new_object(BEAR, owner_id=0, zone=Zone.STACK)
    put_into_graveyard(state, mine_card)
    assert mine_card in state.players[0].graveyard


# --- Sanctifier en-Vec --------------------------------------------------------------

def test_sanctifier_parses_protection_and_replacement():
    pr = printing("Sanctifier en-Vec")
    spec = pr.zone_abilities[0]
    assert spec.colors == frozenset({"B", "R"})
    assert pr.triggered_abilities[0].effect == ExileGraveyardCardsOfColors(
        colors=frozenset({"B", "R"}))


def test_sanctifier_exiles_black_and_red_only():
    state = arena()
    green = to_graveyard(state, BEAR, owner=1)
    black = to_graveyard(state, ZOMBIE, owner=1)
    red = to_graveyard(state, GOBLIN)
    _enter(state, printing("Sanctifier en-Vec"))
    drain_stack(state)
    assert green in state.players[1].graveyard
    assert black in state.players[1].exile and red in state.players[0].exile
    zombie = put(state, ZOMBIE, 1)
    bear = put(state, BEAR, 1)
    move_off_battlefield(state, zombie, "graveyard")
    move_off_battlefield(state, bear, "graveyard")
    assert zombie in state.players[1].exile
    assert bear in state.players[1].graveyard


# --- Bojuka Bog ---------------------------------------------------------------------

def test_bojuka_bog_exiles_target_players_graveyard():
    pr = printing("Bojuka Bog")
    assert pr.enters_tapped
    state = arena()
    theirs = to_graveyard(state, BEAR, owner=1)
    mine = to_graveyard(state, ZOMBIE)
    agent(state).targets = [("player", 1)]
    bog = _enter(state, pr)
    drain_stack(state)
    assert theirs in state.players[1].exile and mine in state.players[0].graveyard
    assert bog.tapped


def test_exile_target_players_graveyard_edges():
    eff = ExileTargetPlayersGraveyard()
    state = arena()
    to_graveyard(state, BEAR, owner=1)
    eff.resolve(state, 0, ())
    state.players[1].has_lost = True
    assert ("player", 1) not in eff.legal_targets(state, 0)
    eff.resolve(state, 0, (("player", 1),))
    assert len(state.players[1].graveyard) == 1
    assert eff.describe() == "exile target player's graveyard"


# --- Leyline of the Void (built with the EoE-era pin lifted) ----------------------

def test_leyline_of_the_void_is_pinned_off_as_an_eoe_era_printing():
    from mtg_bot.cards.parser.creature_rmc_grammar import is_eoe_only_printing
    from mtg_bot.cards.parser.source import build_card_record

    from tests._roto_helpers import roto_card

    # A Duskmourn-pool printing: the P2 grammar is switched off for it so
    # the EoE claimed set doesn't move (docs/ROTO_COVERAGE_PLAN.md).
    assert is_eoe_only_printing("Leyline of the Void")
    assert build_card_record(roto_card("Leyline of the Void")) is None


def test_leyline_of_the_void_lines_build_and_play(monkeypatch):
    import mtg_bot.cards.parser.roto_zones as grammar
    from mtg_bot.cards.parser.cube_enchantments import build_cube_enchantment
    from mtg_bot.opening_hand import apply_opening_hand_actions

    from tests._roto_helpers import roto_card

    monkeypatch.setattr(grammar, "_disabled", lambda: False)
    pr = build_cube_enchantment(roto_card("Leyline of the Void"))
    assert pr is not None
    assert pr.zone_abilities == (GraveyardExileInstead(opponents_only=True),)
    state = arena()
    leyline = to_hand(state, pr)
    apply_opening_hand_actions(state, 0)
    assert leyline in state.battlefield
    theirs = to_hand(state, ZOMBIE, owner=1)
    DiscardSelf().resolve(state, 1)
    state_based_actions(state)
    assert theirs in state.players[1].exile
    mine = to_hand(state, BEAR)
    DiscardSelf().resolve(state, 0)
    state_based_actions(state)
    assert mine in state.players[0].graveyard
