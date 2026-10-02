"""Vintage Roto P5: mass effects keyed on mana value / counters, per-
player damage, tap-all, and the cost atoms that came with them (Price
of Progress, Cryptic Command, Engineered Explosives, Pernicious Deed,
Seal of Cleansing, Claws of Gix, The Filigree Sylex)."""

from __future__ import annotations

from mtg_bot.cards.parser.effects import _parse_effect
from mtg_bot.cards.parser.roto_board import (
    parse_roto_board_effect,
    parse_roto_cost_piece,
    permanent_phrase,
)
from mtg_bot.cards.parser.creature_rmc_grammar import rmc_grammar_disabled
from mtg_bot.effects.generic.roto_board import (
    DamageEachPlayerPerControlled,
    HasManaValueEqualToSourceCounters,
    RemoveCountersFromAmongPermanentsCost,
    TapAllMatching,
)
from mtg_bot.effects.generic.multi_modal import ChooseModes
from mtg_bot.game import Zone, counter_count, set_named_counters
from mtg_bot.turn import Step

from tests._roto_p5_helpers import (
    activate,
    can_activate,
    cast,
    lands,
    make_state,
    place,
    printing,
    resolve_all,
    script,
    vanilla,
)


# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------


def test_effect_grammar_shapes():
    eff = _parse_effect(
        "deals damage to each player equal to twice the number of nonbasic "
        "lands that player controls"
    )
    assert isinstance(eff, DamageEachPlayerPerControlled)
    assert eff.multiplier == 2
    once = parse_roto_board_effect(
        "deals damage to each player equal to the number of artifacts that "
        "player controls"
    )
    assert once.multiplier == 1
    assert "the number of artifacts" in once.describe()
    assert isinstance(_parse_effect("tap all creatures your opponents control"),
                      TapAllMatching)
    # Unknown words never widen the printed set.
    assert parse_roto_board_effect("tap all gizmos") is None
    assert parse_roto_board_effect(
        "deals damage to each player equal to the number of gizmos that "
        "player controls"
    ) is None
    assert parse_roto_board_effect(
        "destroy each gizmo with mana value equal to the number of charge "
        "counters on this artifact"
    ) is None
    assert parse_roto_board_effect("draw seven cards") is None


def test_grammar_is_off_for_eoe_only_printings():
    with rmc_grammar_disabled():
        assert parse_roto_board_effect("tap all creatures") is None
        assert parse_roto_cost_piece("Sacrifice a permanent") is None


def test_permanent_phrase_extra_modifiers(state=None):
    state = make_state()
    legend = place(state, 0, vanilla(2, 2, name="Legend", legendary=True))
    bear = place(state, 0, vanilla(1, 1, name="Bear"))
    f = permanent_phrase("legendary permanent")
    assert f.test(legend, state) and not f.test(bear, state)
    one_one = permanent_phrase("1/1 creature")
    assert one_one.test(bear, state) and not one_one.test(legend, state)
    assert permanent_phrase("gizmo") is None
    seal = place(state, 1, "Seal of Cleansing")
    non_aura = permanent_phrase("non-Aura enchantment")
    assert non_aura.test(seal, state)


def test_cost_pieces():
    sac = parse_roto_cost_piece("Sacrifice this enchantment")
    assert sac.kind == "sacrifice_self"
    perm = parse_roto_cost_piece("Sacrifice a permanent")
    assert perm.kind == "extra" and perm.atom.describe() == "Sacrifice a permanent"
    oil = parse_roto_cost_piece(
        "Remove ten oil counters from among permanents you control"
    )
    assert oil.atom == RemoveCountersFromAmongPermanentsCost(kind="oil", count=10)
    assert parse_roto_cost_piece(
        "Remove many oil counters from among permanents you control"
    ) is None
    assert parse_roto_cost_piece("Sacrifice a gizmo") is None


# ---------------------------------------------------------------------------
# Price of Progress
# ---------------------------------------------------------------------------


def test_price_of_progress_counts_each_players_own_nonbasics():
    state = make_state()
    lands(state, 0, "Mountain", 2)
    place(state, 0, "Wasteland")
    lands(state, 1, "Underground Sea", 2)
    lands(state, 1, "Ancient Tomb", 1)
    lands(state, 1, "Island", 2)
    pop = place(state, 0, "Price of Progress", Zone.HAND)
    cast(state, 0, pop)
    assert state.players[0].life == 20 - 2      # one nonbasic, twice
    assert state.players[1].life == 20 - 6      # three nonbasics, twice
    assert pop in state.players[0].graveyard


def test_price_of_progress_deals_no_damage_without_nonbasics():
    state = make_state()
    lands(state, 0, "Mountain", 2)
    pop = place(state, 0, "Price of Progress", Zone.HAND)
    cast(state, 0, pop)
    assert [p.life for p in state.players] == [20, 20]


# ---------------------------------------------------------------------------
# Cryptic Command
# ---------------------------------------------------------------------------


def test_cryptic_command_taps_opponents_creatures_and_draws():
    state = make_state()
    lands(state, 0, "Island", 4)
    mine = place(state, 0, vanilla(2, 2, name="Mine"))
    theirs = [place(state, 1, vanilla(2, 2, name=f"Theirs {i}")) for i in range(2)]
    place(state, 0, "Island", Zone.LIBRARY)
    cryptic = place(state, 0, "Cryptic Command", Zone.HAND)
    assert isinstance(cryptic.printing.spell_effect, ChooseModes)
    script(state, 0, "modes", [2, 3])
    hand_before = len(state.players[0].hand)
    cast(state, 0, cryptic)
    assert all(t.tapped for t in theirs)
    assert not mine.tapped
    assert len(state.players[0].hand) == hand_before - 1 + 1


def test_cryptic_command_counter_and_bounce():
    state = make_state()
    lands(state, 0, "Island", 4)
    lands(state, 1, "Mountain", 1)
    bolt = place(state, 1, "Lightning Bolt", Zone.HAND)
    bear = place(state, 1, vanilla(2, 2, name="Bear"))
    state.active_player_idx = 1
    state.priority_player_idx = 1
    script(state, 1, "target", ("player", 0))
    cast(state, 1, bolt, resolve=False)
    cryptic = place(state, 0, "Cryptic Command", Zone.HAND)
    state.priority_player_idx = 0
    script(state, 0, "modes", [0, 1])
    script(state, 0, "target", ("stack", 0), ("creature", bear.id))
    cast(state, 0, cryptic)
    assert bolt in state.players[1].graveyard
    assert state.players[0].life == 20
    assert bear in state.players[1].hand


# ---------------------------------------------------------------------------
# Engineered Explosives / The Filigree Sylex / Pernicious Deed
# ---------------------------------------------------------------------------


def test_engineered_explosives_destroys_nonland_permanents_with_mv_equal_to_counters():
    state = make_state()
    lands(state, 0, "Island", 2)
    ee = place(state, 0, "Engineered Explosives")
    ee.charge_counters = 2
    two = place(state, 1, vanilla(2, 2, name="Two Drop", cost="{1}{G}"))
    three = place(state, 1, vanilla(3, 3, name="Three Drop", cost="{2}{G}"))
    my_two = place(state, 0, vanilla(2, 2, name="My Two", cost="{2}"))
    land = place(state, 1, "Underground Sea")
    activate(state, 0, ee)
    assert two in state.players[1].graveyard
    assert my_two in state.players[0].graveyard
    assert three in state.battlefield and land in state.battlefield
    assert ee in state.players[0].graveyard


def test_engineered_explosives_at_zero_kills_tokens_and_zero_drops():
    state = make_state()
    lands(state, 0, "Island", 2)
    ee = place(state, 0, "Engineered Explosives")
    mox = place(state, 1, "Mox Pearl")
    bear = place(state, 1, vanilla(2, 2, name="Bear", cost="{1}{G}"))
    activate(state, 0, ee)
    assert mox in state.players[1].graveyard
    assert bear in state.battlefield


def test_mv_equal_counters_predicate_without_source_is_false():
    state = make_state()
    bear = place(state, 0, vanilla(2, 2))
    assert not HasManaValueEqualToSourceCounters("charge").test(bear, state)
    assert not HasManaValueEqualToSourceCounters("charge").test(
        state.players[0], state,
    )


def test_filigree_sylex_oil_counters_and_both_payoffs():
    state = make_state()
    sylex = place(state, 0, "The Filigree Sylex")
    activate(state, 0, sylex, 0)
    assert counter_count(sylex, "oil") == 1
    sylex.tapped = False
    one = place(state, 1, "Llanowar Elves")
    two = place(state, 1, vanilla(2, 2, name="Two", cost="{1}{G}"))
    activate(state, 0, sylex, 1)
    assert one in state.players[1].graveyard
    assert two in state.battlefield
    assert sylex in state.players[0].graveyard


def test_filigree_sylex_ten_counters_deal_ten():
    state = make_state()
    sylex = place(state, 0, "The Filigree Sylex")
    other = place(state, 0, "Engineered Explosives")
    assert not can_activate(state, 0, sylex, 2)
    set_named_counters(sylex, "oil", 6)
    set_named_counters(other, "oil", 4)
    assert can_activate(state, 0, sylex, 2)
    script(state, 0, "target", ("permanent", other.id), ("permanent", other.id),
           ("permanent", other.id), ("permanent", other.id))
    script(state, 0, "target", ("player", 1))
    # The damage target is chosen before the counters are removed.
    state.players[0].agent.scripts["target"].insert(0, ("player", 1))
    activate(state, 0, sylex, 2)
    assert state.players[1].life == 10
    assert sylex in state.players[0].graveyard
    assert counter_count(other, "oil") == 0


def test_pernicious_deed_x_or_less():
    state = make_state()
    lands(state, 0, "Swamp", 2)
    deed = place(state, 0, "Pernicious Deed")
    small = place(state, 1, vanilla(2, 2, name="Small", cost="{1}{G}"))
    big = place(state, 1, vanilla(3, 3, name="Big", cost="{2}{G}"))
    mox = place(state, 1, "Mox Pearl")
    seal = place(state, 1, "Seal of Cleansing")
    land = place(state, 1, "Underground Sea")
    script(state, 0, "x", 2)
    activate(state, 0, deed)
    assert small in state.players[1].graveyard
    assert mox in state.players[1].graveyard
    assert seal in state.players[1].graveyard
    assert big in state.battlefield and land in state.battlefield
    assert deed in state.players[0].graveyard


# ---------------------------------------------------------------------------
# Seal of Cleansing / Claws of Gix
# ---------------------------------------------------------------------------


def test_seal_of_cleansing_destroys_artifact_or_enchantment():
    state = make_state()
    seal = place(state, 0, "Seal of Cleansing")
    rod = place(state, 1, "Mox Pearl")
    bear = place(state, 1, vanilla(2, 2))
    effect = seal.printing.activated_abilities[0].effect
    legal = effect.legal_targets(state, 0)
    assert ("permanent", rod.id) in legal
    assert ("creature", bear.id) not in legal
    script(state, 0, "target", ("permanent", rod.id))
    activate(state, 0, seal)
    assert rod in state.players[1].graveyard
    assert seal in state.players[0].graveyard


def test_claws_of_gix_sacrifices_any_permanent_including_itself():
    state = make_state()
    lands(state, 0, "Plains", 2)
    claws = place(state, 0, "Claws of Gix")
    land = place(state, 0, "Wasteland")
    script(state, 0, "sacrifice", land.id)
    activate(state, 0, claws)
    assert land in state.players[0].graveyard
    assert state.players[0].life == 21
    script(state, 0, "sacrifice", claws.id)
    activate(state, 0, claws)
    assert claws in state.players[0].graveyard
    assert state.players[0].life == 22
