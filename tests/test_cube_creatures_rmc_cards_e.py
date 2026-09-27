"""Cube creatures (R / multicolor / colorless) bucket: per-card engine
behavior, batch 7 — multikicker (Batroc the Leaper), die-roll tables
("Name Sticker" Goblin), the library/graveyard exile watcher (Laelia,
the Blade Reforged)."""

from __future__ import annotations

import random

from mtg_bot.actions import CastSpell, put_into_battlefield
from mtg_bot.cards.parser.creature_rmc_grammar import (
    _parse_batch7_line,
    assemble_die_roll_trigger,
)
from mtg_bot.effects.generic.cube_creatures_rmc import (
    CardsExiledFromLibraryOrGraveyard,
    ControlsAtMostNamed,
    DealPowerDamageToEachOfUpToKickedTargets,
    EnteredNotFromZones,
    NameStickerGate,
    RollDieTable,
    exile_card,
    sweep_library_graveyard_exile_watch,
)
from mtg_bot.effects.generic.mana import AddManaToPool
from mtg_bot.game import Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step, state_based_actions
from tests._rmc_helpers import (
    add,
    add_lands,
    cast,
    make_state,
    printing,
    resolve_all,
)

STICKER = '"Name Sticker" Goblin'


# ---------------------------------------------------------------------------
# Batroc the Leaper — multikicker
# ---------------------------------------------------------------------------


def test_batroc_parse_shape():
    pr = printing("Batroc the Leaper")
    assert pr.multikicker and pr.enters_with_counter_per_kick
    assert pr.kicker_cost_str == "{2}" and pr.kicker_cost.generic == 2
    (trig,) = pr.triggered_abilities
    assert isinstance(trig.effect, DealPowerDamageToEachOfUpToKickedTargets)


def test_batroc_multikicked_counters_and_damage():
    state = make_state()
    add_lands(state, 0, "Mountain", 8)
    victim = add(state, 1, "Orcish Lumberjack")
    batroc = add(state, 0, "Batroc the Leaper", Zone.HAND)
    agent = state.players[0].agent
    agent.scripts["x"] = [2]  # two extra kicks on top of the first
    agent.scripts["target"] = [("player", 1), ("creature", victim.id), None]
    cast(state, 0, batroc, kicked=True)
    assert batroc in state.battlefield
    assert batroc.kick_count == 3 and batroc.plus_one_counters == 3
    assert state.players[1].life == 15  # 5 power
    assert victim in state.players[1].graveyard
    # The agent was offered at most three targets.
    assert sum(1 for hook, _ in agent.calls if hook == "target") == 3


def test_batroc_unkicked_has_no_targets_and_no_counters():
    state = make_state()
    add_lands(state, 0, "Mountain", 2)
    batroc = add(state, 0, "Batroc the Leaper", Zone.HAND)
    assert CastSpell(batroc.id, kicked=True) not in legal_actions(state, 0)
    cast(state, 0, batroc)
    assert batroc.kick_count == 0 and batroc.plus_one_counters == 0
    assert state.players[1].life == 20
    # Leaving the battlefield resets the kick count.
    from mtg_bot.turn import move_off_battlefield

    batroc.kick_count = 2
    move_off_battlefield(state, batroc, "graveyard")
    assert batroc.kick_count == 0


def test_batroc_single_kick_when_only_one_affordable():
    state = make_state()
    add_lands(state, 0, "Mountain", 5)
    batroc = add(state, 0, "Batroc the Leaper", Zone.HAND)
    state.players[0].agent.scripts["target"] = [("player", 1)]
    cast(state, 0, batroc, kicked=True)
    assert batroc.kick_count == 1 and batroc.plus_one_counters == 1
    assert state.players[1].life == 17
    assert not any(hook == "x" for hook, _ in state.players[0].agent.calls)


def test_power_damage_effect_edges():
    eff = DealPowerDamageToEachOfUpToKickedTargets()
    state = make_state()
    src = add(state, 0, "Batroc the Leaper")
    src.kick_count = 2
    assert eff.dynamic_target_count_range(state, src) == (0, 2)
    # Source gone: last-known power from the printing + counters.
    state.battlefield.remove(src)
    src.plus_one_counters = 1
    state.resolving_source = src
    eff.resolve(state, 0, (("player", 1),))
    assert state.players[1].life == 17
    # Zero power: nothing.
    src.plus_one_counters = -2
    eff.resolve(state, 0, (("player", 1),))
    assert state.players[1].life == 17
    state.resolving_source = None
    eff.resolve(state, 0, (("player", 1),))
    assert state.players[1].life == 17
    # A target that left is skipped.
    state.resolving_source = add(state, 0, "Batroc the Leaper")
    eff.resolve(state, 0, (("creature", 9999), ("player", 1)))
    assert state.players[1].life == 15
    assert "up to X" in eff.describe()


# ---------------------------------------------------------------------------
# "Name Sticker" Goblin — die-roll table
# ---------------------------------------------------------------------------


def _pool_r(state, pid):
    return sum(1 for c in state.player_by_id(pid).mana_pool if c.color == "R")


def test_name_sticker_parse_shape():
    (trig,) = printing(STICKER).triggered_abilities
    assert isinstance(trig.effect, RollDieTable)
    assert trig.effect.sides == 20
    assert [(lo, hi) for lo, hi, _ in trig.effect.table] == [(1, 6), (7, 14), (15, 20)]
    assert [e.produces for _, _, e in trig.effect.table] == [
        (("R", 4),), (("R", 5),), (("R", 6),),
    ]
    assert trig.effect.gate == NameStickerGate(name=STICKER, at_most=9)
    assert trig.effect.describe() == "roll a d20"


def test_name_sticker_cast_rolls_and_adds_mana():
    for seed in range(6):
        state = make_state()
        state.rng = random.Random(seed)
        expected_roll = random.Random(seed).randint(1, 20)
        expected = 4 if expected_roll <= 6 else 5 if expected_roll <= 14 else 6
        add_lands(state, 0, "Mountain", 3)
        goblin = add(state, 0, STICKER, Zone.HAND)
        cast(state, 0, goblin)
        assert goblin.entered_from_zone == "stack"
        assert _pool_r(state, 0) == expected


def test_name_sticker_not_from_graveyard_or_exile():
    for zone in (Zone.GRAVEYARD, Zone.EXILE):
        state = make_state()
        goblin = add(state, 0, STICKER, zone)
        getattr(state.players[0], zone.value).remove(goblin)
        put_into_battlefield(state, goblin, 0)
        assert goblin.entered_from_zone == zone.value
        assert not state.stack
    # From the library (e.g. a "put onto the battlefield" search): triggers.
    state = make_state()
    goblin = add(state, 0, STICKER, Zone.LIBRARY)
    state.players[0].library.remove(goblin)
    put_into_battlefield(state, goblin, 0)
    assert len(state.stack) == 1


def test_name_sticker_ten_named_cap_and_resolution_gate():
    state = make_state()
    for _ in range(9):
        add(state, 0, STICKER)
    tenth = add(state, 0, STICKER, Zone.HAND)
    state.players[0].hand.remove(tenth)
    put_into_battlefield(state, tenth, 0)
    assert not state.stack  # ten named creatures
    # Nine (counting itself) triggers; leaving before resolution: no roll.
    state2 = make_state()
    for _ in range(8):
        add(state2, 0, STICKER)
    ninth = add(state2, 0, STICKER, Zone.HAND)
    state2.players[0].hand.remove(ninth)
    put_into_battlefield(state2, ninth, 0)
    assert len(state2.stack) == 1
    from mtg_bot.turn import move_off_battlefield

    move_off_battlefield(state2, ninth, "graveyard")
    resolve_all(state2)
    assert _pool_r(state2, 0) == 0
    # Gate counts only the controller's own creatures.
    gate = NameStickerGate(name=STICKER, at_most=0)
    other = add(state2, 1, STICKER)
    state2.resolving_source = other
    assert gate.matches(state2, 1) is False  # itself counts: 1 > 0
    assert NameStickerGate(name=STICKER, at_most=1).matches(state2, 1)
    assert ControlsAtMostNamed(name=STICKER, at_most=1).matches(state2, {}, other)
    assert EnteredNotFromZones().matches(state2, {}, other)


def test_die_table_assembly_rejects_gaps_and_orphans():
    ok = AddManaToPool(produces=(("R", 1),))
    assert assemble_die_roll_trigger({}) is None
    assert assemble_die_roll_trigger({"_die_roll": (6, 9, "X")}) == "invalid"
    assert assemble_die_roll_trigger({"_die_row_001": (1, 6, ok)}) == "invalid"
    gap = {"_die_roll": (6, 9, "X"), "_die_row_001": (1, 2, ok), "_die_row_004": (4, 6, ok)}
    assert assemble_die_roll_trigger(gap) == "invalid"
    short = {"_die_roll": (6, 9, "X"), "_die_row_001": (1, 5, ok)}
    assert assemble_die_roll_trigger(short) == "invalid"
    fields = {"_die_roll": (6, 9, "X"), "_die_row_001": (1, 6, ok), "other": 1}
    trig = assemble_die_roll_trigger(fields)
    assert trig.effect.table == ((1, 6, ok),) and fields == {"other": 1}
    # Line grammar: single-number rows, targeted rows rejected, word counts.
    assert _parse_batch7_line("3 | Add {R}.", "X").printing_fields == {
        "_die_row_003": (3, 3, AddManaToPool(produces=(("R", 1),))),
    }
    assert _parse_batch7_line("1-2 | Destroy target creature.", "X") is None
    assert _parse_batch7_line("1-2 | Frobnicate.", "X") is None
    header = (
        "When this creature enters from anywhere other than a graveyard or "
        "exile, if it's on the battlefield and you control {n} or fewer "
        "creatures named Bob, roll a 6-sided die."
    )
    assert _parse_batch7_line(header.format(n="3"), "Y").printing_fields == {
        "_die_roll": (6, 3, "Bob"),
    }
    assert _parse_batch7_line(header.format(n="many"), "Y") is None
    # The card naming itself (self-name substituted) + a word count.
    assert _parse_batch7_line(header.format(n="three"), "Bob").printing_fields == {
        "_die_roll": (6, 3, "Bob"),
    }


def test_roll_die_table_gate_and_no_matching_row():
    state = make_state()
    state.rng = random.Random(0)
    table = RollDieTable(sides=6, table=((1, 1, AddManaToPool(produces=(("R", 1),))),))
    for _ in range(20):
        table.resolve(state, 0)
    assert 0 < _pool_r(state, 0) < 20  # only rolls of 1 add mana


# ---------------------------------------------------------------------------
# Laelia, the Blade Reforged — library / graveyard exile watcher
# ---------------------------------------------------------------------------


def test_laelia_parse_shape():
    pr = printing("Laelia, the Blade Reforged")
    assert pr.watches_library_graveyard_exile
    watcher = pr.triggered_abilities[1]
    assert watcher.predicate == CardsExiledFromLibraryOrGraveyard()
    assert not watcher.predicate.matches(None, {}, None)
    assert hash(watcher.predicate) == hash(CardsExiledFromLibraryOrGraveyard())
    assert repr(watcher.predicate) == "CardsExiledFromLibraryOrGraveyard()"


def test_laelia_attack_exile_grows_her():
    state = make_state(step=Step.DECLARE_ATTACKERS)
    laelia = add(state, 0, "Laelia, the Blade Reforged")
    top = add(state, 0, "Lightning Bolt", Zone.LIBRARY)
    add(state, 0, "Mountain", Zone.LIBRARY)
    state_based_actions(state)  # the watcher's snapshot
    from mtg_bot.combat import declare_attackers

    declare_attackers(state, [laelia.id])
    resolve_all(state)
    assert top in state.players[0].exile
    assert laelia.plus_one_counters == 1


def _exile(state, card):
    getattr(state.player_by_id(card.owner_id), card.zone.value).remove(card)
    exile_card(state, card)


def test_laelia_batches_and_sources():
    state = make_state()
    laelia = add(state, 0, "Laelia, the Blade Reforged")
    lib = [add(state, 0, "Mountain", Zone.LIBRARY) for _ in range(3)]
    gy = add(state, 0, "Lightning Bolt", Zone.GRAVEYARD)
    opp = add(state, 1, "Mountain", Zone.LIBRARY)
    assert not sweep_library_graveyard_exile_watch(state)  # snapshot only
    # Two library cards and a graveyard card at once: one trigger.
    for card in (lib[0], lib[1], gy):
        _exile(state, card)
    resolve_all(state)
    assert laelia.plus_one_counters == 1
    # The opponent's library: nothing.
    _exile(state, opp)
    resolve_all(state)
    assert laelia.plus_one_counters == 1
    # No change since the last sweep: nothing.
    assert not sweep_library_graveyard_exile_watch(state)
    # Without a watcher the snapshot is dropped.
    from mtg_bot.turn import move_off_battlefield

    move_off_battlefield(state, laelia, "graveyard")
    state_based_actions(state)
    assert state.players[0].library_graveyard_watch == frozenset()
    assert lib[2] in state.players[0].library
