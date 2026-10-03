"""Roto P1: spell taxes (Sphere of Resistance, Thorn of Amethyst, Defense
Grid), Trinisphere's cost floor and the artifact activation locks (Null
Rod, Stony Silence)."""

from __future__ import annotations

from dataclasses import replace

from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    apply_action,
    apply_cost_reductions,
    can_pay_cost,
    resolve_top_of_stack,
)
from mtg_bot.cards.base import ManaCost, parse_mana_cost
from mtg_bot.cards.parser.roto_stack import (
    merge_fields,
    parse_roto_stack_line,
)
from mtg_bot.creature_statics_wg import spell_cost_increase
from mtg_bot.legal import legal_actions
from mtg_bot.roto_restrictions import (
    MinimumSpellCost,
    SpellTax,
    apply_minimum_spell_cost,
    minimum_spell_cost,
)
from mtg_bot.turn import Step

from tests._roto_helpers import agent, arena, printing, put, to_hand


def _lands(state, name, n, pid=0):
    return [put(state, printing(name), pid) for _ in range(n)]


def _casts(state, pid=0):
    return [a for a in legal_actions(state, pid) if isinstance(a, CastSpell)]


# ---------------------------------------------------------------------
# Sphere of Resistance / Thorn of Amethyst
# ---------------------------------------------------------------------


def test_sphere_taxes_every_spell_of_every_player():
    state = arena()
    put(state, printing("Sphere of Resistance"), 1)
    assert spell_cost_increase(state, printing("Lightning Bolt"), 0) == 1
    assert spell_cost_increase(state, printing("Llanowar Elves"), 1) == 1
    bolt = to_hand(state, printing("Lightning Bolt"))
    _lands(state, "Mountain", 1)
    assert CastSpell(bolt.id) not in _casts(state)
    _lands(state, "Mountain", 1)
    assert CastSpell(bolt.id) in _casts(state)
    apply_action(state, 0, CastSpell(bolt.id))
    assert all(o.tapped for o in state.battlefield if o.printing.name == "Mountain")


def test_thorn_taxes_only_noncreature_spells():
    state = arena()
    put(state, printing("Thorn of Amethyst"), 0)
    assert spell_cost_increase(state, printing("Lightning Bolt"), 1) == 1
    assert spell_cost_increase(state, printing("Llanowar Elves"), 1) == 0


def test_two_taxes_stack():
    state = arena()
    put(state, printing("Sphere of Resistance"), 0)
    put(state, printing("Thorn of Amethyst"), 1)
    bolt = printing("Lightning Bolt")
    assert apply_cost_reductions(bolt, state, 0, bolt.mana_cost).generic == 2


# ---------------------------------------------------------------------
# Defense Grid
# ---------------------------------------------------------------------


def test_defense_grid_taxes_only_off_turn_spells():
    state = arena(active=0)
    put(state, printing("Defense Grid"), 0)
    bolt = printing("Lightning Bolt")
    assert spell_cost_increase(state, bolt, 0) == 0
    assert spell_cost_increase(state, bolt, 1) == 3
    state.active_player_idx = 1
    assert spell_cost_increase(state, bolt, 1) == 0
    assert spell_cost_increase(state, bolt, 0) == 3


def test_defense_grid_blocks_an_off_turn_counterspell():
    state = arena(active=0)
    put(state, printing("Defense Grid"), 0)
    bolt = to_hand(state, printing("Lightning Bolt"))
    _lands(state, "Mountain", 1)
    counter = to_hand(state, printing("Counterspell"), 1)
    _lands(state, "Island", 4, pid=1)
    apply_action(state, 0, CastSpell(bolt.id))
    state.priority_player_idx = 1
    # {U}{U} + {3}: four Islands can't pay five mana.
    assert CastSpell(counter.id) not in _casts(state, 1)
    _lands(state, "Island", 1, pid=1)
    assert CastSpell(counter.id) in _casts(state, 1)


# ---------------------------------------------------------------------
# Trinisphere
# ---------------------------------------------------------------------


def test_trinisphere_floor_only_while_untapped():
    state = arena()
    tri = put(state, printing("Trinisphere"), 1)
    assert minimum_spell_cost(state) == 3
    tri.tapped = True
    assert minimum_spell_cost(state) == 0
    tri.tapped = False
    cost = apply_minimum_spell_cost(state, parse_mana_cost("{R}"))
    assert cost.total == 3 and dict(cost.colored) == {"R": 1}
    # Already three or more: unchanged.
    big = parse_mana_cost("{2}{U}{U}")
    assert apply_minimum_spell_cost(state, big) is big
    # Phyrexian pips already paid with life count toward the total.
    assert apply_minimum_spell_cost(state, ManaCost(), already_paid=1).total == 2


def test_trinisphere_makes_bolt_cost_three():
    state = arena()
    put(state, printing("Trinisphere"), 1)
    bolt = to_hand(state, printing("Lightning Bolt"))
    _lands(state, "Mountain", 2)
    assert CastSpell(bolt.id) not in _casts(state)
    _lands(state, "Mountain", 1)
    assert CastSpell(bolt.id) in _casts(state)
    apply_action(state, 0, CastSpell(bolt.id))
    assert sum(o.tapped for o in state.battlefield) == 3
    assert any("raised to 3" in line for line in state.log)


def test_trinisphere_applies_to_free_spells():
    state = arena(active=1)
    state.priority_player_idx = 0
    put(state, printing("Trinisphere"), 1)
    force = to_hand(state, printing("Force of Will"))
    to_hand(state, printing("Counterspell"))
    free = CastSpell(force.id, cast_for_free=True)
    # Something to counter.
    bolt = to_hand(state, printing("Lightning Bolt"), 1)
    _lands(state, "Mountain", 3, pid=1)
    apply_action(state, 1, CastSpell(bolt.id))
    state.priority_player_idx = 0
    assert free not in legal_actions(state, 0)
    _lands(state, "Island", 3)
    assert free in legal_actions(state, 0)


def test_tapped_trinisphere_lets_bolt_cost_one():
    state = arena()
    put(state, printing("Trinisphere"), 1, tapped=True)
    bolt = to_hand(state, printing("Lightning Bolt"))
    _lands(state, "Mountain", 1)
    assert CastSpell(bolt.id) in _casts(state)


# ---------------------------------------------------------------------
# Null Rod / Stony Silence
# ---------------------------------------------------------------------


def _activations(state, obj, pid=0):
    return [
        a for a in legal_actions(state, pid)
        if isinstance(a, ActivateAbility) and a.source_id == obj.id
    ]


def test_null_rod_locks_artifact_mana_abilities():
    state = arena()
    ring = put(state, printing("Sol Ring"), 0)
    assert _activations(state, ring)
    put(state, printing("Null Rod"), 1)
    assert not _activations(state, ring)


def test_stony_silence_locks_artifacts_but_not_creatures():
    state = arena()
    ring = put(state, printing("Sol Ring"), 0)
    birds = put(state, printing("Birds of Paradise"), 0)
    put(state, printing("Stony Silence"), 1)
    assert not _activations(state, ring)
    assert _activations(state, birds)


def test_null_rod_locks_artifact_land_mana():
    state = arena()
    seat = put(state, printing("Seat of the Synod"), 0)
    assert _activations(state, seat)
    put(state, printing("Null Rod"), 1)
    assert not _activations(state, seat)


def test_activation_lock_stops_automatic_payment_from_a_locked_land():
    # A land whose types the lock names (an artifact land) can't be
    # tapped for mana by automatic payment either.
    state = arena()
    land = replace(printing("Island"), card_types=("Artifact", "Land"))
    put(state, land, 0)
    assert can_pay_cost(state, 0, parse_mana_cost("{U}"))
    put(state, printing("Null Rod"), 1)
    assert not can_pay_cost(state, 0, parse_mana_cost("{U}"))


# ---------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------


def test_line_grammar():
    card = {"name": "X"}
    sphere = parse_roto_stack_line("Spells cost {2} more to cast.", card)
    ((f, n),) = sphere.fields["spell_cost_increases"]
    assert n == 2 and not f.has_quality
    assert parse_roto_stack_line("Wombat spells cost {1} more to cast.", card) is None
    grid = parse_roto_stack_line(
        "Each spell costs {3} more to cast except during its controller's turn.",
        card,
    )
    assert grid.fields["roto_statics"] == (
        SpellTax(amount=3, except_during_casters_turn=True),
    )
    tri = parse_roto_stack_line(
        "Each spell that would cost less than two mana to cast costs two mana "
        "to cast.", card,
    )
    assert tri.fields["roto_statics"] == (MinimumSpellCost(total=2),)
    assert parse_roto_stack_line(
        "Each spell that would cost less than two mana to cast costs three "
        "mana to cast.", card,
    ) is None
    assert parse_roto_stack_line(
        "Each spell that would cost less than many mana to cast costs many "
        "mana to cast.", card,
    ) is None
    assert parse_roto_stack_line("Flying", card) is None


def test_merge_fields_concatenates_tuple_fields():
    into: dict = {}
    merge_fields(into, {"roto_statics": (1,), "enters_tapped": True})
    merge_fields(into, {"roto_statics": (2,)})
    assert into == {"roto_statics": (1, 2), "enters_tapped": True}


def test_grammar_is_off_for_eoe_only_printings():
    from mtg_bot.cards.parser.creature_rmc_grammar import rmc_grammar_disabled
    from mtg_bot.cards.parser.roto_stack import parse_roto_stack_effect

    with rmc_grammar_disabled():
        assert parse_roto_stack_line("Spells cost {1} more to cast.", {"name": "X"}) is None
        assert parse_roto_stack_effect("anything") is None


def test_resolving_with_no_statics_is_untouched():
    state = arena()
    state.step = Step.PRECOMBAT_MAIN
    bolt = to_hand(state, printing("Lightning Bolt"))
    _lands(state, "Mountain", 1)
    agent(state).targets = [("player", 1)]
    apply_action(state, 0, CastSpell(bolt.id))
    resolve_top_of_stack(state)
    assert state.players[1].life == 17
