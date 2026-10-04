"""Instant-speed activated abilities of permanents (CR 117.1b / 602.5).

A player may activate an activated ability of a permanent they control
whenever they have priority, unless the ability or a rule restricts its
timing. ``legal.activation_timing_permits`` is the single per-ability
timing predicate; ``legal.battlefield_ability_activations`` is the one
enumerator, shared by both exits of ``legal_actions`` and by the search
capability check. See ``docs/INSTANT_SPEED_ACTIVATIONS_DESIGN.md``.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    PassPriority,
    apply_action,
)
from mtg_bot.cards.base import (
    ActivatedAbility,
    ActivationCost,
    make_creature,
    parse_mana_cost,
)
from mtg_bot.effects.generic.counterspells import CounterSpell
from mtg_bot.effects.generic.draw_mill import DrawCards
from mtg_bot.effects.generic.mana import AddManaToPool
from mtg_bot.game import Zone
from mtg_bot.legal import (
    activation_timing_permits,
    battlefield_ability_activations,
    legal_actions,
)
from mtg_bot.turn import Step
from tests._cube_artifact_helpers import arena, put, to_hand

_DRAW = DrawCards(amount=1)

def _cube(name: str):
    """A PowerLSV cube card built through the parser source's own claim
    path (``build_card_record``), asserting it is claimed."""
    from mtg_bot.cards.parser.source import build_card_record
    from tests._cube_artifact_helpers import cube_card

    built = build_card_record(cube_card(name))
    assert built is not None, f"{name} should be claimed by the parser"
    return built



def _ability(**kw) -> ActivatedAbility:
    cost = kw.pop("cost", ActivationCost())
    return ActivatedAbility(cost=cost, effect=kw.pop("effect", _DRAW), **kw)


def _creature(*abilities, name="Activator"):
    return replace(
        make_creature(name, "{1}", 1, 1), activated_abilities=abilities,
    )


def _activations(state, pid, obj=None):
    state.priority_player_idx = pid
    return [
        a for a in legal_actions(state, pid)
        if isinstance(a, ActivateAbility)
        and (obj is None or a.source_id == obj.id)
    ]


def _windows():
    """``(label, active_idx, step, stack_nonempty)`` for every
    non-sorcery window P0 can hold priority in."""
    return [
        ("opponent's upkeep", 1, Step.UPKEEP, False),
        ("opponent's main phase", 1, Step.PRECOMBAT_MAIN, False),
        ("opponent's declare attackers", 1, Step.DECLARE_ATTACKERS, False),
        ("opponent's end step", 1, Step.END, False),
        ("own upkeep", 0, Step.UPKEEP, False),
        ("own beginning of combat", 0, Step.BEGINNING_OF_COMBAT, False),
        ("own combat damage step", 0, Step.COMBAT_DAMAGE, False),
        ("own main phase, stack non-empty", 0, Step.PRECOMBAT_MAIN, True),
    ]


def _put_window(state, active, step, stack_nonempty):
    from mtg_bot.game import StackItem

    state.active_player_idx = active
    state.step = step
    if stack_nonempty:
        dummy = state.new_object(
            make_creature("Stacked", "{1}", 1, 1), owner_id=1,
            zone=Zone.STACK,
        )
        state.stack.append(StackItem(source=dummy, controller_id=1))


# ---------------------------------------------------------------------
# The timing predicate
# ---------------------------------------------------------------------


def test_timing_permits_every_ability_at_sorcery_timing():
    state = arena()
    obj = put(state, _creature(_ability()))
    for ab in (
        _ability(), _ability(sorcery_speed=True),
        _ability(is_mana_ability=True),
    ):
        assert activation_timing_permits(state, obj, ab, sorcery_timing=True)


def test_timing_off_sorcery_window_by_ability_kind():
    state = arena()
    obj = put(state, _creature(_ability()))
    assert activation_timing_permits(
        state, obj, _ability(), sorcery_timing=False,
    )
    assert not activation_timing_permits(
        state, obj, _ability(sorcery_speed=True), sorcery_timing=False,
    )
    # Mana abilities keep the engine-wide handling: explicit mana
    # abilities are offered in a sorcery window only.
    assert not activation_timing_permits(
        state, obj, _ability(is_mana_ability=True), sorcery_timing=False,
    )


def test_timing_loyalty_abilities_need_sorcery_timing_even_unflagged():
    """CR 606.3: a planeswalker's (loyalty) abilities are sorcery-timed
    whether or not the printing flags them (the cross-engine bridge
    builds walker abilities without the flag)."""
    walker = replace(
        _cube("Jace, the Mind Sculptor"),
        activated_abilities=(_ability(),),
    )
    state = arena()
    obj = put(state, walker)
    assert not activation_timing_permits(
        state, obj, walker.activated_abilities[0], sorcery_timing=False,
    )


# ---------------------------------------------------------------------
# legal_actions: the general rule in every priority window
# ---------------------------------------------------------------------


@pytest.mark.parametrize("label,active,step,stack", _windows())
def test_plain_ability_is_offered_in_every_priority_window(
    label, active, step, stack,
):
    state = arena()
    obj = put(state, _creature(_ability()))
    _put_window(state, active, step, stack)
    assert _activations(state, 0, obj) == [ActivateAbility(obj.id, 0)], label


@pytest.mark.parametrize("label,active,step,stack", _windows())
def test_sorcery_speed_and_mana_abilities_wait_for_sorcery_timing(
    label, active, step, stack,
):
    state = arena()
    obj = put(state, _creature(
        _ability(sorcery_speed=True),
        _ability(
            is_mana_ability=True, effect=AddManaToPool(produces=(("G", 1),)),
        ),
        _ability(),
    ))
    _put_window(state, active, step, stack)
    assert _activations(state, 0, obj) == [ActivateAbility(obj.id, 2)], label


def test_sorcery_window_still_offers_every_ability_in_order():
    state = arena()
    obj = put(state, _creature(
        _ability(sorcery_speed=True),
        _ability(
            is_mana_ability=True, effect=AddManaToPool(produces=(("G", 1),)),
        ),
        _ability(),
    ))
    assert _activations(state, 0, obj) == [
        ActivateAbility(obj.id, 0), ActivateAbility(obj.id, 1),
        ActivateAbility(obj.id, 2),
    ]


def test_no_priority_no_activations():
    state = arena(active=1)
    put(state, _creature(_ability()))
    state.priority_player_idx = 1
    assert legal_actions(state, 0) == [PassPriority()]


def test_opponents_permanents_are_not_ours_to_activate():
    state = arena(active=1)
    put(state, _creature(_ability()), 1)
    assert _activations(state, 0) == []


def test_cost_and_target_gates_apply_at_instant_speed():
    state = arena(active=1)
    state.step = Step.END
    tapper = put(state, _creature(
        _ability(cost=ActivationCost(tap_self=True)),
    ))
    tapper.summoning_sick = True
    assert _activations(state, 0, tapper) == []  # CR 302.6
    tapper.summoning_sick = False
    tapper.tapped = True
    assert _activations(state, 0, tapper) == []
    tapper.tapped = False
    assert _activations(state, 0, tapper) == [ActivateAbility(tapper.id, 0)]
    pricey = put(state, _creature(_ability(cost=ActivationCost(
        mana=parse_mana_cost("{5}"), mana_str="{5}",
    ))))
    assert _activations(state, 0, pricey) == []
    # A targeted ability with no legal target isn't offered.
    counter = put(state, _creature(_ability(effect=CounterSpell())))
    assert _activations(state, 0, counter) == []


def test_activate_only_during_your_turn_is_respected_at_instant_speed():
    """Wishclaw Talisman: "Activate only during your turn." -- its own
    upkeep (an instant window) yes, the opponent's turn no."""
    talisman_pr = _cube("Wishclaw Talisman")
    state = arena(active=0)
    talisman = put(state, talisman_pr)
    talisman.named_counters = (("wish", 3),)
    from mtg_bot.cards import BASIC_LANDS

    put(state, BASIC_LANDS["Plains"])
    state.step = Step.UPKEEP
    assert _activations(state, 0, talisman) == [
        ActivateAbility(talisman.id, 0),
    ]
    state.active_player_idx = 1
    assert _activations(state, 0, talisman) == []


def test_equip_is_sorcery_speed():
    greaves = _cube("Lightning Greaves")
    state = arena(active=1)
    eq = put(state, greaves)
    put(state, make_creature("Bear", "{1}{G}", 2, 2))
    state.step = Step.END
    assert _activations(state, 0, eq) == []
    state.active_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    assert _activations(state, 0, eq) == [ActivateAbility(eq.id, 0)]


def test_loyalty_abilities_stay_sorcery_timed():
    state = arena(active=0)
    jace = put(state, _cube("Jace, the Mind Sculptor"))
    jace.loyalty_counters = 3
    put(state, make_creature("Bear", "{1}{G}", 2, 2), 1)
    assert _activations(state, 0, jace)  # own main phase: yes
    state.step = Step.UPKEEP
    assert _activations(state, 0, jace) == []


def test_wandering_emperor_activates_at_instant_speed_the_turn_she_entered():
    state = arena(active=1)
    state.step = Step.DECLARE_ATTACKERS
    emperor = put(state, _cube("The Wandering Emperor"))
    emperor.loyalty_counters = 3
    emperor.entered_battlefield_turn = state.turn_number
    offered = _activations(state, 0, emperor)
    assert ActivateAbility(emperor.id, 1) in offered  # -1: Samurai
    emperor.entered_battlefield_turn = state.turn_number - 1
    assert _activations(state, 0, emperor) == []


def test_stack_targeting_ability_with_a_sacrifice_cost_is_offered():
    """P1's narrow special case offered counter-a-spell abilities only
    with mana / {T} / composable costs; the general rule has no such
    exclusion."""
    from tests.test_roto_stack_counterspells import _bolt_on_stack

    state = arena(active=1)
    counter = put(state, _creature(_ability(
        cost=ActivationCost(sacrifice_self=True), effect=CounterSpell(),
    )))
    assert _activations(state, 0, counter) == []  # nothing to target
    _bolt_on_stack(state)
    assert _activations(state, 0, counter) == [ActivateAbility(counter.id, 0)]


def test_activation_locks_apply_at_instant_speed():
    """Split second (CR 702.61b) leaves only mana abilities -- and
    those aren't offered off sorcery timing -- so nothing activates."""
    from mtg_bot.game import StackItem
    from tests._roto_helpers import printing

    state = arena(active=1)
    state.step = Step.END
    obj = put(state, _creature(_ability()))
    assert _activations(state, 0, obj)
    sudden = state.new_object(
        printing("Angel's Grace"), owner_id=1, zone=Zone.STACK,
    )
    state.stack.append(StackItem(source=sudden, controller_id=1))
    assert _activations(state, 0, obj) == []


def test_first_only_stops_at_the_first_activation():
    state = arena(active=1)
    a = put(state, _creature(_ability(), _ability()))
    put(state, _creature(_ability()))
    every = battlefield_ability_activations(state, 0, sorcery_timing=False)
    assert len(every) == 3
    assert battlefield_ability_activations(
        state, 0, sorcery_timing=False, first_only=True,
    ) == [ActivateAbility(a.id, 0)]
    assert battlefield_ability_activations(
        arena(), 0, sorcery_timing=False, first_only=True,
    ) == []


def test_activation_in_response_resolves_before_the_spell():
    """An activation made while a spell is on the stack goes above it
    and resolves first (CR 405.5)."""
    from mtg_bot.actions import resolve_top_of_stack
    from tests.test_roto_stack_counterspells import _bolt_on_stack

    state = arena(active=1)
    drawer = put(state, _creature(_ability()))
    from tests._cube_artifact_helpers import to_library

    to_library(state, make_creature("Top", "{1}", 1, 1), 0)
    _bolt_on_stack(state)
    hand_before = len(state.players[0].hand)
    life_before = state.players[0].life
    state.priority_player_idx = 0
    apply_action(state, 0, ActivateAbility(drawer.id, 0))
    assert len(state.stack) == 2
    resolve_top_of_stack(state)
    assert len(state.players[0].hand) == hand_before + 1
    assert state.players[0].life == life_before  # Bolt not resolved yet
    resolve_top_of_stack(state)
    assert state.players[0].life == life_before - 3


def test_teferi_confinement_does_not_touch_activations():
    """Teferi, Time Raveler limits SPELLS to sorcery timing; abilities
    are unaffected."""
    state = arena(active=1)
    put(state, _cube("Teferi, Time Raveler"), 1)
    state.step = Step.END
    obj = put(state, _creature(_ability()))
    assert _activations(state, 0, obj) == [ActivateAbility(obj.id, 0)]
    assert not any(isinstance(a, CastSpell) for a in legal_actions(state, 0))


# ---------------------------------------------------------------------
# Unmodelled timing riders are rejected, never dropped
# ---------------------------------------------------------------------


@pytest.mark.parametrize("rider", [
    "Activate only during combat.",
    "Activate only during your upkeep.",
    "Activate only before blockers are declared.",
    "Activate only during an opponent's turn.",
])
def test_unmodelled_timing_rider_rejects_the_line(rider):
    from mtg_bot.cards.parser.activated import _parse_activated_ability_line

    assert _parse_activated_ability_line("{T}: Draw a card.") is not None
    assert _parse_activated_ability_line(f"{{T}}: Draw a card. {rider}") is None
