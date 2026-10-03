"""Roto P1 counterspell variants: Mental Misstep, Spell Snare,
Spellstutter Sprite, Swan Song, Strix Serenade, Glen Elendra Guardian,
Stubborn Denial, Mystical Dispute, Long Goodbye, Venser, Shaper Savant,
Mindbreak Trap."""

from __future__ import annotations

from dataclasses import replace

import pytest

from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    apply_action,
    put_into_battlefield,
    resolve_top_of_stack,
)
from mtg_bot.cards.base import make_creature, parse_mana_cost
from mtg_bot.cards.parser.roto_stack import (
    parse_roto_cost_piece,
    parse_roto_stack_effect,
    roto_alt_cost_condition,
    roto_cost_reduction_condition,
    roto_counter_variant,
    roto_rider_condition,
)
from mtg_bot.effects.generic.counterspells import CounterSpell
from mtg_bot.effects.generic.roto_stack import (
    ExileTargetSpells,
    IsColorless,
    RemoveAnyCounterFromSelfCost,
    SpellManaValueIs,
    TargetsSpellMatching,
    pop_stack_item,
    stack_mana_value,
)
from mtg_bot.effects.value_predicates import HasColor
from mtg_bot.game import Zone
from mtg_bot.legal import legal_actions

from tests._roto_helpers import ScriptedAgent, agent, arena, printing, put, to_hand


def _lands(state, name, n, pid=0):
    return [put(state, printing(name), pid) for _ in range(n)]


def _cast(state, pid, card, **kw):
    apply_action(state, pid, CastSpell(card.id, **kw))


def _drain(state):
    while state.stack:
        resolve_top_of_stack(state)


def _bolt_on_stack(state, pid=1, target=("player", 0)):
    bolt = to_hand(state, printing("Lightning Bolt"), pid)
    _lands(state, "Mountain", 1, pid)
    agent(state, pid).targets = [target]
    _cast(state, pid, bolt)
    return bolt


def _legal(state, pid):
    state.priority_player_idx = pid
    return legal_actions(state, pid)


# ---------------------------------------------------------------------
# Mental Misstep / Spell Snare
# ---------------------------------------------------------------------


def test_mental_misstep_counters_only_mana_value_one():
    state = arena(active=1)
    bolt = _bolt_on_stack(state)
    counter = to_hand(state, printing("Counterspell"), 1)
    _lands(state, "Island", 2, 1)
    misstep = to_hand(state, printing("Mental Misstep"))
    _lands(state, "Island", 1)
    eff = printing("Mental Misstep").spell_effect
    assert eff.legal_targets(state, 0) == [("stack", 0)]
    # Counterspell (mana value 2) isn't a legal target.
    agent(state, 1).targets = [("stack", 0)]
    _cast(state, 1, counter)
    assert eff.legal_targets(state, 0) == [("stack", 0)]
    state.stack.pop()
    agent(state, 0).targets = [("stack", 0)]
    agent(state, 0).yes = False  # pay {U}, not 2 life
    _cast(state, 0, misstep)
    _drain(state)
    assert bolt in state.players[1].graveyard
    assert state.players[0].life == 20


def test_spell_snare_matches_mana_value_two_only():
    state = arena(active=1)
    _bolt_on_stack(state)
    snare = printing("Spell Snare").spell_effect
    assert snare.legal_targets(state, 0) == []
    elves = to_hand(state, printing("Tarmogoyf"), 1)
    _lands(state, "Forest", 2, 1)
    _cast(state, 1, elves)
    assert snare.legal_targets(state, 0) == [("stack", 1)]


def test_spell_mana_value_counts_x_on_the_stack():
    state = arena()
    _bolt_on_stack(state)
    item = state.stack[0]
    xspell = replace(printing("Lightning Bolt"), mana_cost=parse_mana_cost("{X}{R}"))
    item.source.printing = xspell
    item.x_value = 1
    assert stack_mana_value(state, item.source) == 2
    assert SpellManaValueIs(2).test(item.source, state)
    # Off the stack X is 0.
    card = to_hand(state, xspell)
    assert stack_mana_value(state, card) == 1
    assert not SpellManaValueIs(1).test(object(), state)


def test_mental_misstep_pays_phyrexian_mana_with_life():
    state = arena(active=1)
    _bolt_on_stack(state)
    misstep = to_hand(state, printing("Mental Misstep"))
    agent(state, 0).targets = [("stack", 0)]
    assert CastSpell(misstep.id) in _legal(state, 0)
    _cast(state, 0, misstep)
    _drain(state)
    assert state.players[0].life == 18


# ---------------------------------------------------------------------
# Spellstutter Sprite
# ---------------------------------------------------------------------


def test_spellstutter_counts_faeries_including_itself():
    state = arena(active=1)
    goyf = to_hand(state, printing("Tarmogoyf"), 1)
    _lands(state, "Forest", 2, 1)
    _cast(state, 1, goyf)
    sprite = printing("Spellstutter Sprite")
    trigger = sprite.triggered_abilities[0]
    # One Faerie (the Sprite) -> mana value 1 or less: Tarmogoyf (2) isn't legal.
    put(state, sprite, 0)
    assert trigger.effect.legal_targets(state, 0) == []
    put(state, printing("Glen Elendra Guardian"), 0)
    assert trigger.effect.legal_targets(state, 0) == [("stack", 0)]


def test_spellstutter_etb_counters_and_rechecks_on_resolution():
    state = arena(active=1)
    goyf = to_hand(state, printing("Tarmogoyf"), 1)
    _lands(state, "Forest", 2, 1)
    _cast(state, 1, goyf)
    glen = put(state, printing("Glen Elendra Guardian"), 0)
    sprite = to_hand(state, printing("Spellstutter Sprite"))
    _lands(state, "Island", 2)
    agent(state, 0).targets = [("stack", 0)]
    _cast(state, 0, sprite)
    resolve_top_of_stack(state)  # the Sprite enters; its trigger goes on the stack
    assert state.stack[-1].ability is not None
    # A Faerie leaves in response: X drops to 1 -> the target is illegal.
    from mtg_bot.turn import move_off_battlefield

    move_off_battlefield(state, glen, destination="graveyard")
    resolve_top_of_stack(state)
    assert any("no longer a legal target" in line for line in state.log)
    _drain(state)
    assert any(o.printing.name == "Tarmogoyf" for o in state.battlefield)


def test_spellstutter_counters_with_enough_faeries():
    state = arena(active=1)
    goyf = to_hand(state, printing("Tarmogoyf"), 1)
    _lands(state, "Forest", 2, 1)
    _cast(state, 1, goyf)
    put(state, printing("Glen Elendra Guardian"), 0)
    sprite = to_hand(state, printing("Spellstutter Sprite"))
    _lands(state, "Island", 2)
    agent(state, 0).targets = [("stack", 0)]
    _cast(state, 0, sprite)
    _drain(state)
    assert goyf in state.players[1].graveyard


# ---------------------------------------------------------------------
# Swan Song / Strix Serenade / Glen Elendra Guardian
# ---------------------------------------------------------------------


def _birds(state, pid):
    return [
        o for o in state.battlefield
        if o.controller_id == pid and o.printing.name == "Bird"
    ]


def test_swan_song_counters_an_instant_and_gives_its_controller_a_bird():
    state = arena(active=1)
    bolt = _bolt_on_stack(state)
    swan = to_hand(state, printing("Swan Song"))
    _lands(state, "Island", 1)
    agent(state, 0).targets = [("stack", 0)]
    _cast(state, 0, swan)
    _drain(state)
    assert bolt in state.players[1].graveyard
    (bird,) = _birds(state, 1)
    assert "flying" in bird.printing.keywords
    assert (bird.printing.power, bird.printing.toughness) == (2, 2)
    assert state.players[0].life == 20


def test_swan_song_cant_target_creature_spells_strix_can():
    state = arena(active=1)
    goyf = to_hand(state, printing("Tarmogoyf"), 1)
    _lands(state, "Forest", 2, 1)
    _cast(state, 1, goyf)
    assert printing("Swan Song").spell_effect.legal_targets(state, 0) == []
    strix = to_hand(state, printing("Strix Serenade"))
    _lands(state, "Island", 1)
    agent(state, 0).targets = [("stack", 0)]
    _cast(state, 0, strix)
    _drain(state)
    assert goyf in state.players[1].graveyard
    assert len(_birds(state, 1)) == 1


def test_counter_then_controller_effect_fizzles_on_an_illegal_target():
    state = arena(active=1)
    _bolt_on_stack(state)
    eff = printing("Swan Song").spell_effect
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("stack", 7),))
    eff.resolve(state, 0, (("player", 1),))
    state.stack[0].countered = True
    eff.resolve(state, 0, (("stack", 0),))
    state.stack[0].countered = False
    # No longer matches the filter (became a creature spell).
    state.stack[0].source.printing = printing("Tarmogoyf")
    eff.resolve(state, 0, (("stack", 0),))
    assert not _birds(state, 1)
    assert "its controller" in eff.describe()


def test_glen_elendra_enters_with_a_counter_and_trades_it_for_a_counter():
    state = arena(active=1)
    glen = to_hand(state, printing("Glen Elendra Guardian"))
    state.players[0].hand.remove(glen)
    glen.zone = Zone.STACK
    put_into_battlefield(state, glen, 0)
    glen.summoning_sick = False
    assert glen.minus_one_counters == 1
    bolt = _bolt_on_stack(state)
    _lands(state, "Island", 2)
    acts = [
        a for a in _legal(state, 0)
        if isinstance(a, ActivateAbility) and a.source_id == glen.id
    ]
    assert acts
    agent(state, 0).targets = [("stack", 0)]
    hand_before = len(state.players[1].hand)
    apply_action(state, 0, acts[0])
    assert glen.minus_one_counters == 0
    _drain(state)
    assert bolt in state.players[1].graveyard
    assert len(state.players[1].hand) == hand_before + 1 or not state.players[1].library
    # No counters left: the ability can't be activated again.
    _bolt_on_stack(state)
    _lands(state, "Island", 2)
    assert not [
        a for a in _legal(state, 0)
        if isinstance(a, ActivateAbility) and a.source_id == glen.id
    ]


def test_remove_any_counter_cost_picks_among_kinds():
    state = arena()
    obj = put(state, printing("Tarmogoyf"), 0)
    cost = RemoveAnyCounterFromSelfCost()
    assert not cost.payable(state, 0, obj)
    assert not cost.payable(state, 0, None)
    obj.plus_one_counters = 1
    obj.named_counters = (("oil", 2),)
    agent(state, 0).scripts = None
    assert cost.payable(state, 0, obj)
    from tests._roto_helpers import ScriptedAgent

    class _Pick(ScriptedAgent):
        def choose_mode(self, state, player_id, options):
            return 1

    state.players[0].agent = _Pick()
    cost.pay(state, 0, obj)
    assert obj.plus_one_counters == 1 and obj.named_counters == (("oil", 1),)
    assert cost.describe().startswith("Remove a counter")


# ---------------------------------------------------------------------
# Stubborn Denial / Mystical Dispute
# ---------------------------------------------------------------------


def test_stubborn_denial_taxes_without_ferocious():
    state = arena(active=1)
    bolt = _bolt_on_stack(state)
    _lands(state, "Mountain", 1, 1)  # the opponent can pay {1}
    denial = to_hand(state, printing("Stubborn Denial"))
    _lands(state, "Island", 1)
    agent(state, 0).targets = [("stack", 0)]
    _cast(state, 0, denial)
    _drain(state)
    assert state.players[0].life == 17
    assert bolt in state.players[1].graveyard  # resolved, not countered


def test_stubborn_denial_hard_counters_with_ferocious():
    state = arena(active=1)
    _bolt_on_stack(state)
    _lands(state, "Mountain", 1, 1)
    put(state, make_creature("Big", "{4}{G}", 4, 4), 0)
    denial = to_hand(state, printing("Stubborn Denial"))
    _lands(state, "Island", 1)
    agent(state, 0).targets = [("stack", 0)]
    _cast(state, 0, denial)
    _drain(state)
    assert state.players[0].life == 20


def test_mystical_dispute_costs_less_against_a_blue_spell():
    state = arena(active=1)
    dispute = to_hand(state, printing("Mystical Dispute"))
    _lands(state, "Island", 1)
    _bolt_on_stack(state)
    assert CastSpell(dispute.id) not in _legal(state, 0)
    brainstorm = to_hand(state, printing("Brainstorm"), 1)
    _lands(state, "Island", 1, 1)
    _cast(state, 1, brainstorm)
    assert CastSpell(dispute.id) in _legal(state, 0)
    agent(state, 0).targets = [("stack", 1)]
    _cast(state, 0, dispute)
    _drain(state)
    assert brainstorm in state.players[1].graveyard
    assert any("Brainstorm is countered" in line for line in state.log)


def test_targets_spell_matching_condition():
    state = arena(active=1)
    cond = TargetsSpellMatching(HasColor("U"))
    assert not cond.matches(state, 0)
    _bolt_on_stack(state)
    assert not cond.matches(state, 0)
    assert not cond.matches(state, 0, (("stack", 0), ("stack", 9), ("player", 1)))
    state.stack[0].source.printing = printing("Brainstorm")
    assert cond.matches(state, 0, (("stack", 0),))


# ---------------------------------------------------------------------
# Long Goodbye
# ---------------------------------------------------------------------


def test_long_goodbye_cant_be_countered_even_by_ward():
    state = arena(active=0)
    warded = replace(
        make_creature("Warded", "{2}", 2, 2),
        ward_cost=parse_mana_cost("{2}"), ward_cost_str="{2}",
    )
    target = put(state, warded, 1)
    goodbye = to_hand(state, printing("Long Goodbye"))
    _lands(state, "Swamp", 2)
    agent(state, 0).targets = [("creature", target.id)]
    _cast(state, 0, goodbye)
    assert not state.stack[0].countered
    # Counterspell can't target it.
    assert printing("Counterspell").spell_effect.legal_targets(state, 1) == []
    _drain(state)
    assert target in state.players[1].graveyard


# ---------------------------------------------------------------------
# Venser, Shaper Savant
# ---------------------------------------------------------------------


def test_venser_returns_an_uncounterable_spell_to_hand():
    state = arena(active=1)
    goodbye = to_hand(state, printing("Long Goodbye"), 1)
    _lands(state, "Swamp", 2, 1)
    victim = put(state, make_creature("Bear", "{1}{G}", 2, 2), 0)
    agent(state, 1).targets = [("creature", victim.id)]
    _cast(state, 1, goodbye)
    venser = to_hand(state, printing("Venser, Shaper Savant"))
    _lands(state, "Island", 4)
    agent(state, 0).targets = [("stack", 0)]
    _cast(state, 0, venser)
    _drain(state)
    assert goodbye in state.players[1].hand
    assert victim in state.battlefield


def test_venser_can_bounce_a_land():
    state = arena()
    land = put(state, printing("Wasteland"), 1)
    trig = printing("Venser, Shaper Savant").triggered_abilities[0].effect
    assert ("permanent", land.id) in trig.legal_targets(state, 0)
    trig.resolve(state, 0, (("permanent", land.id),))
    assert land in state.players[1].hand
    trig.resolve(state, 0, ())
    trig.resolve(state, 0, (("stack", 3),))
    trig.resolve(state, 0, (("permanent", 999),))
    assert "spell or permanent" in trig.describe()


def test_pop_stack_item_repoints_other_targets():
    state = arena(active=1)
    _bolt_on_stack(state)  # index 0
    _bolt_on_stack(state)  # index 1
    _bolt_on_stack(state)  # index 2
    state.stack[2].targets = (("stack", 0), ("stack", 1), ("player", 0))
    pop_stack_item(state, 0)
    assert state.stack[1].targets == (("stack", -1), ("stack", 0), ("player", 0))


# ---------------------------------------------------------------------
# Mindbreak Trap
# ---------------------------------------------------------------------


class _TargetsThenStop(ScriptedAgent):
    """Picks the scripted targets, then declines further optional ones."""

    def __init__(self, picks):
        super().__init__()
        self.picks = list(picks)

    def choose_target(self, state, player_id, legal_targets):
        while self.picks:
            t = self.picks.pop(0)
            if t in legal_targets:
                return t
        return None


def test_mindbreak_trap_free_after_three_opponent_spells_and_exiles_targets():
    state = arena(active=1)
    trap = to_hand(state, printing("Mindbreak Trap"))
    free = CastSpell(trap.id, cast_for_free=True)
    first = _bolt_on_stack(state)
    second = _bolt_on_stack(state)
    assert free not in _legal(state, 0)
    third = _bolt_on_stack(state)
    assert free in _legal(state, 0)
    state.players[0].agent = _TargetsThenStop([("stack", 0), ("stack", 2)])
    _cast(state, 0, trap, cast_for_free=True)
    _drain(state)
    exile = state.players[1].exile
    assert first in exile and third in exile
    assert second in state.players[1].graveyard  # resolved
    assert state.players[0].life == 17


def test_exile_target_spells_edge_cases():
    eff = ExileTargetSpells()
    assert eff.target_count_range()[0] == 0
    state = arena(active=1)
    bolt = _bolt_on_stack(state)
    eff.resolve(state, 0, (("stack", 0), ("stack", 0), ("stack", 5), ("player", 1)))
    assert bolt in state.players[1].exile and not state.stack
    assert "any number" in eff.describe()


# ---------------------------------------------------------------------
# Grammar edges
# ---------------------------------------------------------------------


def test_effect_grammar_edges():
    assert parse_roto_stack_effect("counter target wombat spell with mana value 2") is None
    assert parse_roto_stack_effect(
        "counter target spell with mana value X or less, where X is the "
        "number of blorp blorp you control"
    ) is None
    assert parse_roto_stack_effect(
        "counter target spell. Its controller creates a frobnicator"
    ) is None
    assert parse_roto_stack_effect(
        "counter target spell. Its controller draws target card"
    ) is None
    eff = parse_roto_stack_effect(
        "counter target spell with mana value X or less, where X is the "
        "number of artifacts you control"
    )
    assert eff is not None and "X or less" in eff.describe()
    assert parse_roto_cost_piece("Remove a +1/+1 counter from this creature") is None
    assert roto_rider_condition("you control a wombat") is None
    assert roto_counter_variant("counter that spell", object()) is None
    assert roto_counter_variant("counter that spell", CounterSpell()) is None
    assert roto_counter_variant("destroy it", CounterSpell(unless_pays="{1}")) is None
    assert roto_cost_reduction_condition("it targets a wombat spell") is None
    assert roto_cost_reduction_condition("it targets a spell") is None
    assert roto_cost_reduction_condition("you're cool") is None
    assert roto_alt_cost_condition("an opponent cast many or more spells this turn") is None
    assert roto_alt_cost_condition("an opponent cast 2 or more spells this turn").n == 2
    assert roto_alt_cost_condition("you feel lucky") is None


def test_alternative_cost_describes_its_condition():
    alt = printing("Mindbreak Trap").alternative_costs[0]
    assert "an opponent cast 3 or more spells" in alt.describe()


@pytest.mark.parametrize("colors,expected", [((), True), (("U",), False)])
def test_is_colorless(colors, expected):
    state = arena()
    pr = replace(make_creature("Thing", "{2}", 1, 1), color_indicator=frozenset(colors))
    obj = put(state, pr, 0)
    assert IsColorless().test(obj, state) is expected
    assert not IsColorless().test(object(), state)


# ---------------------------------------------------------------------
# Consign to Memory
# ---------------------------------------------------------------------


def test_consign_to_memory_counters_a_triggered_ability():
    state = arena(active=1)
    goyf = to_hand(state, printing("Tarmogoyf"), 1)
    sprite = to_hand(state, printing("Spellstutter Sprite"), 1)
    _lands(state, "Island", 2, 1)
    _lands(state, "Forest", 2, 1)
    # Player 0 has a spell on the stack for the Sprite to counter.
    state.priority_player_idx = 0
    ring = to_hand(state, printing("Sol Ring"))
    _lands(state, "Mountain", 1)
    state.active_player_idx = 0
    _cast(state, 0, ring)
    agent(state, 1).targets = [("stack", 0)]
    _cast(state, 1, sprite)
    resolve_top_of_stack(state)  # Sprite enters; its ETB trigger is on the stack
    assert state.stack[-1].ability is not None
    consign = to_hand(state, printing("Consign to Memory"))
    _lands(state, "Island", 1)
    eff = printing("Consign to Memory").spell_effect
    # Targets: the trigger and the colorless Sol Ring spell.
    assert set(eff.legal_targets(state, 0)) == {("stack", 0), ("stack", 1)}
    agent(state, 0).targets = [("stack", 1)]
    agent(state, 0).yes = False
    agent(state, 0).x_value = 0
    _cast(state, 0, consign)
    _drain(state)
    assert any(o.printing.name == "Sol Ring" for o in state.battlefield)
    assert goyf in state.players[1].hand


def test_consign_to_memory_counters_colorless_spells_only():
    state = arena(active=1)
    ring = to_hand(state, printing("Sol Ring"), 1)
    _lands(state, "Mountain", 1, 1)
    _cast(state, 1, ring)
    eff = printing("Consign to Memory").spell_effect
    assert eff.legal_targets(state, 0) == [("stack", 0)]
    _bolt_on_stack(state)
    assert eff.legal_targets(state, 0) == [("stack", 0)]
    assert "triggered ability" in eff.describe()


def test_counter_ability_or_spell_grammar_edges():
    assert parse_roto_stack_effect("counter target spell") is None
    assert parse_roto_stack_effect("counter target triggered ability or blorp") is None
    assert parse_roto_stack_effect(
        "counter target triggered ability or colorless wombat spell"
    ) is None
    assert parse_roto_stack_effect(
        "counter target colorless spell or colorless spell"
    ) is None
    assert parse_roto_stack_effect("counter target ability or spell") is None
    eff = parse_roto_stack_effect(
        "counter target activated ability or artifact spell"
    )
    assert eff is not None and eff.kinds == ("activated", "spell")


# ---------------------------------------------------------------------
# Spell-targeting activated abilities at instant speed
# ---------------------------------------------------------------------


def _counter_creature(**cost_kw):
    from mtg_bot.cards.base import ActivatedAbility, ActivationCost

    ability = ActivatedAbility(
        cost=ActivationCost(**cost_kw), effect=CounterSpell(),
    )
    return replace(
        make_creature("Counterer", "{1}{U}", 1, 1),
        activated_abilities=(ability,),
    )


def test_instant_speed_spell_targeting_activations():
    from mtg_bot.roto_restrictions import (
        instant_speed_spell_targeting_activations as offered,
    )
    from mtg_bot.search._player_capabilities import (
        _has_instant_speed_activatable,
    )

    state = arena(active=1)
    tapper = put(state, _counter_creature(tap_self=True), 0)
    assert offered(state, 0) == []  # empty stack
    _bolt_on_stack(state)
    assert offered(state, 0) == [ActivateAbility(tapper.id, 0)]
    assert _has_instant_speed_activatable(
        state, 0, state.players[0], is_active_player=False,
    )
    tapper.summoning_sick = True
    assert offered(state, 0) == []
    tapper.summoning_sick = False
    tapper.tapped = True
    assert offered(state, 0) == []
    tapper.tapped = False
    # Not offered: a sacrifice cost, sorcery speed, unpayable mana,
    # an activation restriction.
    tapper.printing = _counter_creature(sacrifice_self=True)
    assert offered(state, 0) == []
    tapper.printing = replace(
        _counter_creature(),
        activated_abilities=(replace(
            _counter_creature().activated_abilities[0], sorcery_speed=True,
        ),),
    )
    assert offered(state, 0) == []
    tapper.printing = _counter_creature(
        mana=parse_mana_cost("{5}"), mana_str="{5}",
    )
    assert offered(state, 0) == []
    tapper.printing = replace(
        _counter_creature(),
        activated_abilities=(replace(
            _counter_creature().activated_abilities[0],
            activate_only_during_your_turn=True,
        ),),
    )
    assert offered(state, 0) == []
    from mtg_bot.effects.conditions import HandSizeAtMost

    tapper.printing = replace(
        _counter_creature(),
        activated_abilities=(replace(
            _counter_creature().activated_abilities[0],
            activate_only_if=HandSizeAtMost(-1),
        ),),
    )
    assert offered(state, 0) == []
    # An opponent's permanent isn't ours to activate.
    tapper.printing = _counter_creature()
    tapper.controller_id = 1
    assert offered(state, 0) == []
