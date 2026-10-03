"""Vintage Roto P3: rituals, dynamic mana and the Force of Despair sweep
(``cards/parser/roto_mana.py`` / ``effects/generic/roto_mana.py``)."""

from __future__ import annotations

from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    _activate_ability,
    apply_action,
    put_into_battlefield,
    resolve_top_of_stack,
)
from mtg_bot.cards.base import make_artifact, make_basic_land, make_creature
from mtg_bot.cards.parser.roto_mana import (
    parse_activate_only_if_condition,
    parse_roto_mana_effect,
)
from mtg_bot.effects.generic import roto_mana as rm
from mtg_bot.game import ManaCoin, Zone
from mtg_bot.legal import legal_actions

from tests._roto_helpers import (
    arena,
    printing,
    put,
    to_graveyard,
    to_hand,
    to_library,
)

MOUNTAIN = make_basic_land("Mountain", "R")
SWAMP = make_basic_land("Swamp", "B")
BEAR = make_creature("Bear", "{1}{G}", 2, 2)


def _pool(state, pid=0):
    return sorted(c.color for c in state.players[pid].mana_pool)


# ---------------------------------------------------------------------------
# Rite of Flame
# ---------------------------------------------------------------------------


def test_rite_of_flame_counts_every_graveyards_copies():
    s = arena()
    rite = printing("Rite of Flame")
    to_graveyard(s, rite, 0)
    to_graveyard(s, rite, 1)
    to_graveyard(s, BEAR, 1)  # other cards don't count
    put(s, MOUNTAIN, 0)
    card = to_hand(s, rite, 0)
    apply_action(s, 0, CastSpell(card.id))
    resolve_top_of_stack(s)
    # {R}{R} plus one {R} per Rite of Flame in each graveyard (the
    # resolving copy is on the stack, not in a graveyard).
    assert _pool(s) == ["R"] * 4
    assert card in s.players[0].graveyard


def test_rite_of_flame_alone_adds_two():
    s = arena()
    put(s, MOUNTAIN, 0)
    card = to_hand(s, printing("Rite of Flame"), 0)
    apply_action(s, 0, CastSpell(card.id))
    resolve_top_of_stack(s)
    assert _pool(s) == ["R", "R"]


def test_cards_named_formula_reads_all_graveyards():
    s = arena()
    to_graveyard(s, BEAR, 0)
    to_graveyard(s, BEAR, 1)
    assert rm.CardsNamedInAllGraveyards("Bear").value(s, 0) == 2
    assert rm.CardsNamedInAllGraveyards("Elk").value(s, 0) == 0


# ---------------------------------------------------------------------------
# Spire of Industry
# ---------------------------------------------------------------------------


def _spire_mana_ability_index(spire):
    return next(
        i for i, a in enumerate(spire.printing.activated_abilities)
        if a.activate_only_if is not None
    )


def test_spire_any_color_needs_an_artifact_and_costs_life():
    s = arena()
    spire = put(s, printing("Spire of Industry"), 0)
    idx = _spire_mana_ability_index(spire)
    offered = ActivateAbility(source_id=spire.id, ability_index=idx)
    assert offered not in legal_actions(s, 0)
    put(s, make_artifact("Trinket", "{1}"), 0)
    assert offered in legal_actions(s, 0)
    _activate_ability(s, 0, spire.id, idx)
    assert spire.tapped
    assert s.players[0].life == 19
    assert _pool(s) == ["any"]


def test_spire_taps_for_colorless_without_an_artifact():
    s = arena()
    spire = put(s, printing("Spire of Industry"), 0)
    assert spire.printing.produces == frozenset({"C"})
    # An opponent's artifact doesn't count.
    put(s, make_artifact("Trinket", "{1}"), 1)
    idx = _spire_mana_ability_index(spire)
    assert ActivateAbility(source_id=spire.id, ability_index=idx) not in (
        legal_actions(s, 0)
    )


def test_activate_only_if_control_type_rider_grammar():
    cond = parse_activate_only_if_condition("you control a creature")
    s = arena()
    assert not cond.matches(s, 0)
    put(s, BEAR, 0)
    assert cond.matches(s, 0)
    assert parse_activate_only_if_condition("you control a goblin") is None


# ---------------------------------------------------------------------------
# Force of Despair
# ---------------------------------------------------------------------------


def _fresh_creature(state, controller):
    """A creature that enters this turn through the ETB pipeline."""
    obj = state.new_object(BEAR, owner_id=controller, zone=Zone.STACK)
    put_into_battlefield(state, obj, controller)
    return obj


def test_force_of_despair_destroys_only_creatures_that_entered_this_turn():
    s = arena(active=1)
    s.priority_player_idx = 0
    old = put(s, BEAR, 1)
    new_theirs = _fresh_creature(s, 1)
    new_mine = _fresh_creature(s, 0)
    force = to_hand(s, printing("Force of Despair"), 0)
    to_hand(s, printing("Rite of Flame"), 0)  # not black
    black = to_hand(s, printing("Force of Despair"), 0)
    # Not my turn: the pitch alternative cost is offered.
    assert CastSpell(force.id, cast_for_free=True) in legal_actions(s, 0)
    apply_action(s, 0, CastSpell(force.id, cast_for_free=True))
    assert black in s.players[0].exile
    resolve_top_of_stack(s)
    assert old in s.battlefield
    assert new_theirs not in s.battlefield
    assert new_mine not in s.battlefield


def test_force_of_despair_alt_cost_only_on_opponents_turn():
    s = arena(active=0)
    force = to_hand(s, printing("Force of Despair"), 0)
    to_hand(s, printing("Force of Despair"), 0)
    assert CastSpell(force.id, cast_for_free=True) not in legal_actions(s, 0)


def test_land_creature_played_this_turn_counts_as_entered():
    from mtg_bot.actions import PlayLand

    s = arena(active=0)
    card = to_hand(s, printing("Dryad Arbor"), 0)
    apply_action(s, 0, PlayLand(card.id))
    assert rm.EnteredThisTurn().test(card, s)
    s.turn_number += 1
    assert not rm.EnteredThisTurn().test(card, s)


def test_entered_this_turn_grammar_requires_a_destroy_base():
    assert parse_roto_mana_effect("destroy all creatures that entered this turn")
    assert parse_roto_mana_effect(
        "destroy all frobnicators that entered this turn"
    ) is None


# ---------------------------------------------------------------------------
# Jeska's Will
# ---------------------------------------------------------------------------


def _jeska_arena(mode: int):
    s = arena()
    for _ in range(3):
        put(s, MOUNTAIN, 0)
    agent0 = s.players[0].agent
    agent0.choose_mode = lambda state, pid, options: mode
    return s


def test_jeskas_will_is_choose_one_and_mode_one_counts_opponents_hand():
    from mtg_bot.effects.combinators import ModalChooseOne

    eff = printing("Jeska's Will").spell_effect
    # The commander upgrade never applies in the engine's games.
    assert isinstance(eff, ModalChooseOne) and not eff.or_both
    s = _jeska_arena(0)
    for _ in range(4):
        to_hand(s, BEAR, 1)
    card = to_hand(s, printing("Jeska's Will"), 0)
    apply_action(s, 0, CastSpell(card.id))
    assert s.stack[-1].targets == (("player", 1),)
    resolve_top_of_stack(s)
    assert _pool(s) == ["R"] * 4


def test_jeskas_will_mode_two_exiles_three_playable_this_turn():
    s = _jeska_arena(1)
    lib = [to_library(s, BEAR, 0) for _ in range(4)]
    card = to_hand(s, printing("Jeska's Will"), 0)
    apply_action(s, 0, CastSpell(card.id))
    resolve_top_of_stack(s)
    exiled = [c for c in s.players[0].exile]
    assert len(exiled) == 3 and lib[3] in s.players[0].library
    for c in exiled:
        assert c.playable_from_exile_this_turn or c.exile_play_permission


def test_jeskas_will_mana_mode_fizzles_without_an_opponent_target():
    eff = rm.AddManaPerCardInTargetOpponentsHand(color="R")
    s = arena()
    eff.resolve(s, 0, ())
    eff.resolve(s, 0, (("player", 0),))  # never yourself
    eff.resolve(s, 0, (("creature", 1),))
    assert s.players[0].mana_pool == []
    assert "target opponent" in eff.describe()


# ---------------------------------------------------------------------------
# Burnt Offering
# ---------------------------------------------------------------------------


def test_burnt_offering_adds_the_sacrificed_creatures_mana_value():
    s = arena()
    put(s, SWAMP, 0)
    ogre = put(s, make_creature("Ogre", "{3}{R}", 4, 4), 0)
    offering = to_hand(s, printing("Burnt Offering"), 0)
    s.players[0].agent.colors = ["B", "R", "R", "B"]
    apply_action(s, 0, CastSpell(offering.id))
    assert ogre in s.players[0].graveyard
    resolve_top_of_stack(s)
    assert _pool(s) == ["B", "B", "R", "R"]


def test_x_formula_grammar_paths():
    from mtg_bot.effects.formulas import MVOfCostPaidObjectPlus

    eff = parse_roto_mana_effect(
        "add X mana in any combination of {U} and/or {R}, where X is this "
        "creature's power"
    )
    assert isinstance(eff.formula, rm.SourcePower)
    assert "any combination" in eff.describe()
    eff = parse_roto_mana_effect(
        "add X mana in any combination of {B} and/or {R}, where X is the "
        "sacrificed creature's mana value"
    )
    assert eff.formula == MVOfCostPaidObjectPlus(constant=0)
    assert parse_roto_mana_effect(
        "add X mana in any combination of {B} and/or {R}, where X is the "
        "number of frobs"
    ) is None
    assert parse_roto_mana_effect(
        "draw X cards, where X is the sacrificed creature's mana value"
    ) is None


def test_source_power_formula_reads_the_resolving_source():
    s = arena()
    s.resolving_source = put(s, make_creature("Bear", "{1}{G}", 2, 2), 0)
    assert rm.SourcePower().value(s, 0) == 2
    s.resolving_source = None
    assert rm.SourcePower().value(s, 0) == 0


# ---------------------------------------------------------------------------
# Culling Ritual
# ---------------------------------------------------------------------------


def test_culling_ritual_adds_mana_per_permanent_actually_destroyed():
    from dataclasses import replace

    s = arena()
    for _ in range(2):
        put(s, SWAMP, 0)
    for _ in range(2):
        put(s, make_basic_land("Forest", "G"), 0)
    elf = put(s, make_creature("Elf", "{G}", 1, 1), 0)
    rock = put(s, make_artifact("Rock", "{2}"), 1)
    ogre = put(s, make_creature("Ogre", "{2}{R}", 3, 3), 1)
    wall = put(
        s, replace(make_creature("Wall", "{1}", 0, 4),
                   keywords=frozenset({"indestructible"})), 1,
    )
    ritual = to_hand(s, printing("Culling Ritual"), 0)
    s.players[0].agent.colors = ["G", "B"]
    apply_action(s, 0, CastSpell(ritual.id))
    resolve_top_of_stack(s)
    assert elf not in s.battlefield and rock not in s.battlefield
    assert ogre in s.battlefield and wall in s.battlefield
    assert _pool(s) == ["B", "G"]
    eff = printing("Culling Ritual").spell_effect
    assert "destroyed this way" in eff.describe()


def test_culling_ritual_grammar_needs_a_destroy_sweep():
    assert parse_roto_mana_effect(
        "exile each creature. Add {B} or {G} for each permanent destroyed "
        "this way"
    ) is None


# ---------------------------------------------------------------------------
# Channel
# ---------------------------------------------------------------------------


def _channeled():
    s = arena()
    for _ in range(2):
        put(s, make_basic_land("Forest", "G"), 0)
    channel = to_hand(s, printing("Channel"), 0)
    apply_action(s, 0, CastSpell(channel.id))
    resolve_top_of_stack(s)
    return s


def test_channel_pays_life_for_colorless_mana():
    from mtg_bot.actions import can_pay_cost
    from mtg_bot.cards.base import parse_mana_cost

    s = _channeled()
    giant = to_hand(s, make_creature("Colossus", "{8}", 8, 8), 0)
    assert CastSpell(giant.id) in legal_actions(s, 0)
    apply_action(s, 0, CastSpell(giant.id))
    assert s.players[0].life == 12
    resolve_top_of_stack(s)
    assert giant in s.battlefield
    # Colored mana can't come from Channel; nor can the opponent use it.
    assert not can_pay_cost(s, 0, parse_mana_cost("{R}"))
    assert not can_pay_cost(s, 1, parse_mana_cost("{1}"))


def test_channel_never_pays_down_to_zero_and_ends_at_cleanup():
    from mtg_bot.actions import can_pay_cost
    from mtg_bot.cards.base import parse_mana_cost
    from mtg_bot.turn import run_cleanup_step

    s = _channeled()
    s.players[0].life = 3
    assert can_pay_cost(s, 0, parse_mana_cost("{2}"))
    assert not can_pay_cost(s, 0, parse_mana_cost("{3}"))
    run_cleanup_step(s)
    assert not can_pay_cost(s, 0, parse_mana_cost("{1}"))


def test_channel_pays_only_the_shortfall():
    s = _channeled()
    for _ in range(3):
        put(s, MOUNTAIN, 0)
    giant = to_hand(s, make_creature("Colossus", "{5}", 5, 5), 0)
    apply_action(s, 0, CastSpell(giant.id))
    assert s.players[0].life == 18  # three Mountains + 2 life
    assert "1 life" in rm.GrantLifeForColorlessUntilEndOfTurn().describe()


# ---------------------------------------------------------------------------
# Firestorm
# ---------------------------------------------------------------------------


def test_firestorm_discards_x_and_deals_x_to_each_of_x_targets():
    s = arena()
    put(s, MOUNTAIN, 0)
    bear = put(s, BEAR, 1)
    giant = put(s, make_creature("Giant", "{4}", 5, 5), 1)
    storm = to_hand(s, printing("Firestorm"), 0)
    discards = [to_hand(s, BEAR, 0) for _ in range(2)]
    agent0 = s.players[0].agent
    agent0.x_value = 2
    agent0.targets = [("creature", bear.id), ("player", 1)]
    apply_action(s, 0, CastSpell(storm.id))
    assert all(c in s.players[0].graveyard for c in discards)
    assert s.stack[-1].targets == (("creature", bear.id), ("player", 1))
    assert s.stack[-1].x_value == 2
    resolve_top_of_stack(s)
    from mtg_bot.turn import state_based_actions

    state_based_actions(s)
    assert bear not in s.battlefield and giant in s.battlefield
    assert s.players[1].life == 18


def test_firestorm_x_is_bounded_by_hand_and_targets():
    s = arena()
    put(s, MOUNTAIN, 0)
    storm = to_hand(s, printing("Firestorm"), 0)
    for _ in range(5):
        to_hand(s, BEAR, 0)
    s.players[0].agent.x_value = None  # take the largest X
    # Two players are the only legal targets: X <= 2.
    assert rm.choose_additional_cost_x(s, 0, storm) == 2
    assert rm.choose_additional_cost_x(s, 0, to_hand(s, BEAR, 0)) is None


def test_firestorm_with_x_zero_does_nothing():
    s = arena()
    put(s, MOUNTAIN, 0)
    storm = to_hand(s, printing("Firestorm"), 0)
    s.players[0].agent.x_value = 0
    apply_action(s, 0, CastSpell(storm.id))
    resolve_top_of_stack(s)
    assert s.players[1].life == 20
    assert "each of X targets" in rm.DealXDamageToEachOfXTargets().describe()
